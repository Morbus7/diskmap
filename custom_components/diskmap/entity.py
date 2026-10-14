"""Felles grunnlag for entitetene: én enhet per agent."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DiskmapCoordinator


class DiskmapEntity(CoordinatorEntity[DiskmapCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: DiskmapCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        summary = (coordinator.data or {}).get("summary", {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=entry.title,
            manufacturer="Diskmap", model="Agent", sw_version=summary.get("version"),
        )
