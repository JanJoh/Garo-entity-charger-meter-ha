from __future__ import annotations
import logging, aiohttp, async_timeout, voluptuous as vol
from typing import Any
from homeassistant import config_entries
from homeassistant.core import callback, HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_HOST, CONF_USERNAME, CONF_PASSWORD,
    CONF_SCAN_INTERVAL, CONF_IGNORE_TLS_ERRORS,
    CONF_ENABLE_PHASE_SENSORS, CONF_ENABLE_LINE_VOLTAGES,
    CONF_USE_HTTP, DEFAULT_SCAN_INTERVAL
)

_LOGGER = logging.getLogger(__name__)

class CannotConnect(Exception): pass
class InvalidAuth(Exception): pass

async def async_validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    host = data[CONF_HOST]
    username = data[CONF_USERNAME]
    password = data[CONF_PASSWORD]
    ignore_tls = data.get(CONF_IGNORE_TLS_ERRORS, False)
    use_http = data.get(CONF_USE_HTTP, False)
    scheme = "http" if use_http else "https"
    session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=not ignore_tls))
    try:
        async with async_timeout.timeout(10):
            async with session.get(f"{scheme}://{host}/", auth=aiohttp.BasicAuth(username, password)) as resp:
                if resp.status in (401,403): raise InvalidAuth
                if resp.status >= 400: raise CannotConnect(f"HTTP {resp.status}")
    except InvalidAuth: raise
    except Exception as err: raise CannotConnect(err) from err
    finally:
        await session.close()

class GaroChargerMeterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors = {}
        if user_input is not None:
            try:
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()
                await async_validate_input(self.hass, user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating input")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=f"GARO Charger @ {user_input[CONF_HOST]}", data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_HOST, default=(user_input or {}).get(CONF_HOST, "")): str,
            vol.Required(CONF_USERNAME, default=(user_input or {}).get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD, default=(user_input or {}).get(CONF_PASSWORD, "")): str,
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
            vol.Optional(CONF_IGNORE_TLS_ERRORS, default=False): bool,
            vol.Optional(CONF_USE_HTTP, default=False): bool,
            vol.Optional(CONF_ENABLE_PHASE_SENSORS, default=True): bool,
            vol.Optional(CONF_ENABLE_LINE_VOLTAGES, default=False): bool,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

class GaroChargerMeterOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Options updated", data=user_input)
        data = {**self._entry.data, **self._entry.options}
        schema = vol.Schema({
            vol.Required(CONF_SCAN_INTERVAL, default=data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): int,
            vol.Optional(CONF_IGNORE_TLS_ERRORS, default=data.get(CONF_IGNORE_TLS_ERRORS, False)): bool,
            vol.Optional(CONF_USE_HTTP, default=data.get(CONF_USE_HTTP, False)): bool,
            vol.Optional(CONF_ENABLE_PHASE_SENSORS, default=data.get(CONF_ENABLE_PHASE_SENSORS, True)): bool,
            vol.Optional(CONF_ENABLE_LINE_VOLTAGES, default=data.get(CONF_ENABLE_LINE_VOLTAGES, False)): bool,
        })
        return self.async_show_form(step_id="init", data_schema=schema)

@callback
def async_get_options_flow(config_entry):
    return GaroChargerMeterOptionsFlow(config_entry)
