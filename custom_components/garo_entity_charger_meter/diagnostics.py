from __future__ import annotations
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, REDACT_KEYS


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry):
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    log_state = runtime.get("log_state")
    follower = runtime.get("log_follower")
    return {
        "entry": async_redact_data(dict(entry.data), REDACT_KEYS),
        "options": async_redact_data(dict(entry.options), REDACT_KEYS),
        "has_coordinator": "coordinator" in runtime,
        "log": None if log_state is None else {
            "offset": follower.offset if follower else None,
            "current_limit": log_state.current_limit,
            "limiting_factor": log_state.limiting_factor,
            "limit_factors": log_state.limit_factors,
            "relay_mode": log_state.relay_mode,
            "connector_status": log_state.connector_status,
        },
    }
