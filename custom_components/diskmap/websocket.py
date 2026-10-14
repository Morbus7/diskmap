"""Websocket-kommandoer for visninger (f.eks. X2). Bare for administratorer, siden filnavn vises."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .helpers import coordinator_for, loaded, tree_slice


def _agent(c) -> dict[str, Any]:
    data = c.data or {}
    return {
        "entry_id": c.config_entry.entry_id, "name": c.config_entry.title, "available": c.last_update_success,
        "summary": data.get("summary"), "status": data.get("status") or {}, "has_tree": c.tree is not None,
    }


def _wrap(handler):
    """Feil sendes tilbake som vanlig feilsvar med melding, i stedet for å bli logget som ukjent feil."""
    async def run(hass, connection, msg):
        try:
            connection.send_result(msg["id"], await handler(hass, msg))
        except HomeAssistantError as err:
            connection.send_error(msg["id"], "diskmap_error", str(err))
    return run


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "diskmap/agents"})
@websocket_api.async_response
@_wrap
async def ws_agents(hass: HomeAssistant, msg: dict) -> Any:
    return [_agent(c) for c in sorted(loaded(hass), key=lambda c: c.config_entry.title.lower())]


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "diskmap/tree", vol.Required("entry_id"): str,
    vol.Optional("path", default=""): str, vol.Optional("depth", default=2): vol.All(int, vol.Range(0, 10)),
})
@websocket_api.async_response
@_wrap
async def ws_tree(hass: HomeAssistant, msg: dict) -> Any:
    return tree_slice(coordinator_for(hass, msg["entry_id"]), msg["path"], msg["depth"])


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "diskmap/files", vol.Required("entry_id"): str,
    vol.Optional("query", default=""): str, vol.Optional("ext", default=""): str,
    vol.Optional("limit", default=100): vol.All(int, vol.Range(1, 1000)),
})
@websocket_api.async_response
@_wrap
async def ws_files(hass: HomeAssistant, msg: dict) -> Any:
    """Største filer, med filter på tekst i stien og/eller filendelse."""
    res = coordinator_for(hass, msg["entry_id"]).tree or {}
    q, ext = msg["query"].lower(), msg["ext"].lower().lstrip(".")
    files = [f for f in res.get("top_files", [])
             if (not q or q in f["p"].lower()) and (not ext or f["p"].lower().endswith("." + ext))]
    return {"scan_id": res.get("scan_id"), "files": files[: msg["limit"]], "total": len(res.get("top_files", []))}


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "diskmap/types", vol.Required("entry_id"): str})
@websocket_api.async_response
@_wrap
async def ws_types(hass: HomeAssistant, msg: dict) -> Any:
    res = coordinator_for(hass, msg["entry_id"]).tree or {}
    return {"scan_id": res.get("scan_id"), "types": res.get("types", [])}


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "diskmap/scan", vol.Required("entry_id"): str})
@websocket_api.async_response
@_wrap
async def ws_scan(hass: HomeAssistant, msg: dict) -> Any:
    c = coordinator_for(hass, msg["entry_id"])
    await c.async_scan()
    return _agent(c)


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    for cmd in (ws_agents, ws_tree, ws_files, ws_types, ws_scan):
        websocket_api.async_register_command(hass, cmd)
