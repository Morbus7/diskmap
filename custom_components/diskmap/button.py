"""Knapp: Skann nå."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DiskmapConfigEntry, DiskmapCoordinator
from .entity import DiskmapEntity


async def async_setup_entry(hass: HomeAssistant, entry: DiskmapConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([ScanButton(entry.runtime_data)])


class ScanButton(DiskmapEntity, ButtonEntity):
    _attr_translation_key = "scan_now"
    _attr_icon = "mdi:magnify-scan"

    def __init__(self, coordinator: DiskmapCoordinator) -> None:
        super().__init__(coordinator, "scan_now")

    async def async_press(self) -> None:
        await self.coordinator.async_scan()
