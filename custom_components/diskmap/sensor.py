"""Sensorer: kapasitet per rot, sist skannet, og én sensor per toppmappe (med vekst som attributt)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfInformation
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_TOP_SENSORS, DEFAULT_TOP_SENSORS
from .coordinator import DiskmapConfigEntry, DiskmapCoordinator
from .entity import DiskmapEntity

CAPACITY_KEYS = ("used", "free", "total", "used_percent", "hidden")


async def async_setup_entry(hass: HomeAssistant, entry: DiskmapConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    top_n = int(entry.options.get(CONF_TOP_SENSORS, DEFAULT_TOP_SENSORS))
    known: set[str] = set()

    @callback
    def add_new() -> None:
        """Nye røtter og nye toppmapper kan dukke opp etter en skanning: lag sensorer for dem da."""
        roots = (coordinator.data or {}).get("summary", {}).get("roots", [])
        multi = len(roots) > 1
        new: list[SensorEntity] = []
        if "last_scan" not in known:
            known.add("last_scan")
            new.append(LastScanSensor(coordinator))
        for root in roots:
            for key in CAPACITY_KEYS:
                uid = f"{root['name']}_{key}"
                if uid not in known:
                    known.add(uid)
                    new.append(CapacitySensor(coordinator, root["name"], key, multi))
            folders = [c for c in root.get("top", []) if c.get("t") != "o"][:top_n]
            for item in folders:
                uid = f"{root['name']}_folder_{item['n']}"
                if uid not in known:
                    known.add(uid)
                    new.append(FolderSensor(coordinator, root["name"], item["n"], multi))
        if new:
            async_add_entities(new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class CapacitySensor(DiskmapEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: DiskmapCoordinator, root: str, key: str, multi: bool) -> None:
        super().__init__(coordinator, f"{root}_{key}")
        self._root, self._key = root, key
        # Med flere røtter står rotnavnet i entitetsnavnet, ellers bare «Brukt», «Ledig» …
        self._attr_translation_key = f"{key}_root" if multi else key
        self._attr_translation_placeholders = {"root": root}
        if key == "used_percent":
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_suggested_display_precision = 1
        else:
            self._attr_device_class = SensorDeviceClass.DATA_SIZE
            self._attr_native_unit_of_measurement = UnitOfInformation.BYTES
            self._attr_suggested_unit_of_measurement = UnitOfInformation.GIGABYTES
            self._attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float | int | None:
        cap = (self.coordinator.root(self._root) or {}).get("cap")
        if not cap:
            return None
        if self._key == "used_percent":
            return round(100 * cap["used"] / cap["total"], 2) if cap.get("total") else None
        return cap.get(self._key)


class LastScanSensor(DiskmapEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_scan"

    def __init__(self, coordinator: DiskmapCoordinator) -> None:
        super().__init__(coordinator, "last_scan")

    @property
    def native_value(self) -> datetime | None:
        ts = self.coordinator.data["summary"].get("scanned_at")
        return datetime.fromtimestamp(ts, UTC) if ts else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.coordinator.data["summary"]
        return {"scan_id": s.get("scan_id"), "duration_s": s.get("duration"), "files": s.get("files"), "errors": s.get("errors")}


class FolderSensor(DiskmapEntity, SensorEntity):
    """Størrelsen på én mappe (eller stor fil) rett under roten. Vekst siden forrige skanning er attributt."""

    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfInformation.BYTES
    _attr_suggested_unit_of_measurement = UnitOfInformation.GIGABYTES
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:folder"

    def __init__(self, coordinator: DiskmapCoordinator, root: str, name: str, multi: bool) -> None:
        super().__init__(coordinator, f"{root}_folder_{name}")
        self._root, self._name = root, name
        self._attr_name = f"{root}/{name}" if multi else name

    def _item(self) -> dict | None:
        return next((c for c in (self.coordinator.root(self._root) or {}).get("top", []) if c["n"] == self._name and c.get("t") != "o"), None)

    @property
    def available(self) -> bool:
        return super().available and self._item() is not None  # mappen er borte eller for liten til å være med

    @property
    def native_value(self) -> int | None:
        item = self._item()
        return item["s"] if item else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item, root = self._item() or {}, self.coordinator.root(self._root) or {}
        return {
            "path": f"{self._root}/{self._name}",
            "growth": item.get("g"),
            "new": bool(item.get("new")),
            "files": item.get("f"),
            "share": round(100 * item["s"] / root["size"], 1) if item.get("s") and root.get("size") else None,
            "kind": "file" if item.get("t") == "f" else "folder",
        }
