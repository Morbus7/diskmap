"""Tjenestene diskmap.scan og diskmap.get_tree."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .helpers import coordinator_for, loaded, tree_slice

CONF_ENTRY = "config_entry_id"

SCAN_SCHEMA = vol.Schema({vol.Optional(CONF_ENTRY): cv.string})
TREE_SCHEMA = vol.Schema({
    vol.Required(CONF_ENTRY): cv.string,
    vol.Optional("path", default=""): cv.string,
    vol.Optional("depth", default=2): vol.All(vol.Coerce(int), vol.Range(0, 10)),
})


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def scan(call: ServiceCall) -> None:
        """Skann én agent, eller alle når ingen er valgt."""
        entry_id = call.data.get(CONF_ENTRY)
        for c in [coordinator_for(hass, entry_id)] if entry_id else loaded(hass):
            await c.async_scan()

    async def get_tree(call: ServiceCall) -> ServiceResponse:
        return tree_slice(coordinator_for(hass, call.data[CONF_ENTRY]), call.data["path"], call.data["depth"])

    hass.services.async_register(DOMAIN, "scan", scan, schema=SCAN_SCHEMA)
    hass.services.async_register(DOMAIN, "get_tree", get_tree, schema=TREE_SCHEMA, supports_response=SupportsResponse.ONLY)
