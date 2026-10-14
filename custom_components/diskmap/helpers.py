"""Finn riktig agent (koordinator) ut fra config entry-id."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN
from .coordinator import DiskmapCoordinator


def coordinator_for(hass: HomeAssistant, entry_id: str) -> DiskmapCoordinator:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded", translation_placeholders={"entry": entry_id})
    return entry.runtime_data


def loaded(hass: HomeAssistant) -> list[DiskmapCoordinator]:
    return [e.runtime_data for e in hass.config_entries.async_loaded_entries(DOMAIN)]


def tree_slice(coordinator: DiskmapCoordinator, path: str, depth: int) -> dict:
    """Utsnitt av treet som et vanlig JSON-svar (brukes av både tjenesten og X2)."""
    from .tree import cut, find

    res = coordinator.tree
    if not res:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_scan")
    node = find(res["tree"], path)
    if node is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_path", translation_placeholders={"path": path})
    return {
        "agent": coordinator.config_entry.title, "scan_id": res.get("scan_id"), "scanned_at": res.get("scanned_at"),
        "prev_scanned_at": res.get("prev_scanned_at"), "path": path.strip("/"), "node": cut(node, depth),
    }
