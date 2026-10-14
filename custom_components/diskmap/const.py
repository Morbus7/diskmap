"""Konstanter for Diskmap."""
from datetime import timedelta
import logging

DOMAIN = "diskmap"
LOGGER = logging.getLogger(__package__)

CONF_TOKEN = "token"
CONF_SCAN_INTERVAL = "scan_interval"  # minutter mellom hver henting av /api/summary
CONF_TOP_SENSORS = "top_sensors"      # antall toppmapper per rot som blir sensorer

DEFAULT_PORT = 8787
DEFAULT_SCAN_INTERVAL = 5
DEFAULT_TOP_SENSORS = 10
FAST_INTERVAL = timedelta(seconds=15)  # mens en skanning pågår, så fremdriften vises

EVENT_SCAN_FINISHED = "diskmap_scan_finished"
