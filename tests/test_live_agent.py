"""Test mot en agent som kjører lokalt (DISKMAP_TEST_URL=host:port, DISKMAP_TEST_TOKEN).

Kjør: pytest tests -p no:cacheprovider --allow-hosts=127.0.0.1
"""
import asyncio
import os

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.diskmap.const import DOMAIN, EVENT_SCAN_FINISHED

HOST, PORT = os.environ.get("DISKMAP_TEST_URL", "127.0.0.1:8799").split(":")
TOKEN = os.environ.get("DISKMAP_TEST_TOKEN", "testtesttesttest1234")


async def add_agent(hass, token=TOKEN, port=PORT):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    return await hass.config_entries.flow.async_configure(r["flow_id"], {"name": "Testagent", "host": HOST, "port": int(port), "token": token})


async def test_flow_errors(hass: HomeAssistant, socket_enabled) -> None:
    assert (await add_agent(hass, token="feil-token-feil-token"))["errors"] == {"base": "invalid_auth"}
    assert (await add_agent(hass, port=1))["errors"] == {"base": "cannot_connect"}


async def test_full(hass: HomeAssistant, socket_enabled, hass_ws_client) -> None:
    r = await add_agent(hass)
    assert r["type"] is FlowResultType.CREATE_ENTRY, r
    entry_id = r["result"].entry_id
    await hass.async_block_till_done()

    states = {s.entity_id: s for s in hass.states.async_all() if s.entity_id.split(".")[1].startswith("testagent")}
    for eid, s in sorted(states.items()):
        print(eid, s.state, s.attributes.get("unit_of_measurement"), {k: v for k, v in s.attributes.items() if k in ("growth", "share", "files")})
    assert float(states["sensor.testagent_usr_used"].state) > 0
    assert states["sensor.testagent_usr_used"].attributes["unit_of_measurement"] == "GB"
    assert states["binary_sensor.testagent_scanning"].state in ("on", "off")
    assert any(s.attributes.get("path") == "usr/lib" for s in states.values())

    # Tjenesten med svar
    res = await hass.services.async_call(DOMAIN, "get_tree", {"config_entry_id": entry_id, "path": "usr", "depth": 1}, blocking=True, return_response=True)
    assert res["node"]["n"] == "usr" and res["node"]["c"], res
    assert all("c" not in c for c in res["node"]["c"])  # bare ett nivå

    # Websocket (for X2)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "diskmap/agents"})
    msg = await ws.receive_json()
    assert msg["success"] and msg["result"][0]["name"] == "Testagent", msg
    ents = msg["result"][0]["entities"]
    print("entiteter:", ents)
    assert ents["folders"]["usr/lib"] == "sensor.testagent_usr_lib" and ents["used"]["usr"] == "sensor.testagent_usr_used"
    await ws.send_json({"id": 2, "type": "diskmap/tree", "entry_id": entry_id, "path": "usr/lib", "depth": 2})
    msg = await ws.receive_json()
    assert msg["success"] and msg["result"]["node"]["n"] == "lib", msg
    await ws.send_json({"id": 3, "type": "diskmap/tree", "entry_id": entry_id, "path": "finnes/ikke"})
    msg = await ws.receive_json()
    assert not msg["success"], msg
    print("feilmelding:", msg["error"])
    await ws.send_json({"id": 4, "type": "diskmap/files", "entry_id": entry_id, "ext": "so", "limit": 3})
    msg = await ws.receive_json()
    assert msg["success"] and all(f["p"].endswith(".so") for f in msg["result"]["files"]), msg
    await ws.send_json({"id": 5, "type": "diskmap/types", "entry_id": entry_id})
    msg = await ws.receive_json()
    assert msg["success"] and msg["result"]["types"], msg

    # Skann nå (knappen) og vent på hendelsen når skanningen er ferdig
    events = []
    hass.bus.async_listen(EVENT_SCAN_FINISHED, events.append)
    await hass.services.async_call("button", "press", {"entity_id": "button.testagent_scan_now"}, blocking=True)
    coordinator = hass.config_entries.async_get_entry(entry_id).runtime_data
    for _ in range(60):
        await asyncio.sleep(0.5)
        await coordinator.async_refresh()
        if events:
            break
    assert events, "ingen diskmap_scan_finished"
    print("hendelse:", events[0].data)

    # Valg: intervall og antall mappesensorer
    r = await hass.config_entries.options.async_init(entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"scan_interval": 10, "top_sensors": 1})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.config_entries.async_get_entry(entry_id).runtime_data.update_interval.total_seconds() == 600

    assert await hass.config_entries.async_unload(entry_id)
