"""Binærsensor: skanning pågår (med fremdrift som attributter)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DiskmapConfigEntry, DiskmapCoordinator
from .entity import DiskmapEntity


async def async_setup_entry(hass: HomeAssistant, entry: DiskmapConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([ScanningSensor(entry.runtime_data)])


class ScanningSensor(DiskmapEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "scanning"

    def __init__(self, coordinator: DiskmapCoordinator) -> None:
        super().__init__(coordinator, "scanning")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data["summary"].get("running"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        st = self.coordinator.data.get("status") or {}
        return {"percent": st.get("percent"), "files": st.get("files"), "started_at": st.get("started_at")}
