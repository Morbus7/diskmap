"""Henter oppsummeringen fra agenten jevnlig, og hele treet bare når det finnes en ny skanning."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DiskmapAuthError, DiskmapClient, DiskmapError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, EVENT_SCAN_FINISHED, FAST_INTERVAL, LOGGER

type DiskmapConfigEntry = ConfigEntry[DiskmapCoordinator]


class DiskmapCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """data = {"summary": …, "status": …}. Treet ligger i self.tree (bare i minnet)."""

    config_entry: DiskmapConfigEntry

    def __init__(self, hass: HomeAssistant, entry: DiskmapConfigEntry, client: DiskmapClient) -> None:
        self.normal_interval = timedelta(minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(hass, LOGGER, config_entry=entry, name=f"{DOMAIN} {entry.title}", update_interval=self.normal_interval)
        self.client = client
        self.tree: dict | None = None  # siste /api/tree: tree, top_files, types, scan_id …

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            summary = await self.client.summary()
            status = await self.client.status() if summary.get("running") else {}
        except DiskmapAuthError as err:
            raise ConfigEntryAuthFailed("Agenten godtar ikke tokenet") from err
        except DiskmapError as err:
            raise UpdateFailed(f"Får ikke kontakt med agenten: {err}") from err

        scan_id = summary.get("scan_id")
        old_id = self.tree.get("scan_id") if self.tree else None
        if scan_id and scan_id != old_id:
            try:
                self.tree = await self.client.tree()
            except DiskmapError as err:
                LOGGER.warning("Kunne ikke hente treet fra %s: %s", self.config_entry.title, err)
            else:
                if old_id:  # ikke ved oppstart, bare når en ny skanning er ferdig
                    self.hass.bus.async_fire(EVENT_SCAN_FINISHED, {
                        "config_entry_id": self.config_entry.entry_id, "agent": self.config_entry.title,
                        "scan_id": scan_id, "duration": summary.get("duration"),
                    })
        # Raskere oppdatering mens skanningen pågår, så fremdriften vises
        self.update_interval = FAST_INTERVAL if summary.get("running") else self.normal_interval
        return {"summary": summary, "status": status}

    async def async_scan(self) -> None:
        try:
            await self.client.scan()
        except DiskmapError as err:
            raise UpdateFailed(f"Kunne ikke starte skanning: {err}") from err
        await self.async_request_refresh()

    def root(self, name: str) -> dict | None:
        return next((r for r in (self.data or {}).get("summary", {}).get("roots", []) if r["name"] == name), None)
