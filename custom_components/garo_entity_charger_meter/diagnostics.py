from __future__ import annotations
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, REDACT_KEYS

async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry):
    redacted = {}
    for k,v in entry.data.items():
        redacted[k] = "***" if k in REDACT_KEYS else v
    return {
        "entry": redacted,
        "options": entry.options,
        "has_coordinator": "coordinator" in hass.data.get(DOMAIN, {}).get(entry.entry_id, {}),
    }
