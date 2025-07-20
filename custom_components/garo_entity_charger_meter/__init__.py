from __future__ import annotations
import logging, asyncio, async_timeout, aiohttp
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.typing import ConfigType
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    DOMAIN, PLATFORMS, SERVICE_REFRESH,
    CONF_HOST, CONF_USERNAME, CONF_PASSWORD,
    CONF_IGNORE_TLS_ERRORS, CONF_USE_HTTP,
    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL,
    API_PATH
)

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: ConfigType):
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    host = entry.data[CONF_HOST]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    ignore_tls = entry.options.get(CONF_IGNORE_TLS_ERRORS, entry.data.get(CONF_IGNORE_TLS_ERRORS, False))
    use_http = entry.options.get(CONF_USE_HTTP, entry.data.get(CONF_USE_HTTP, False))
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    scheme = "http" if use_http else "https"
    url = f"{scheme}://{host}{API_PATH}"

    session = aiohttp_client.async_get_clientsession(hass, verify_ssl=not ignore_tls)
    try:
        async with async_timeout.timeout(15):
            async with session.get(url, auth=aiohttp.BasicAuth(username, password)) as resp:
                txt = await resp.text()
                if resp.status in (401,403):
                    raise ConfigEntryNotReady(f"Authentication failed (status {resp.status})")
                if resp.status == 404:
                    raise ConfigEntryNotReady("Endpoint not found (404) - adjust API_PATH")
                if resp.status >= 400:
                    raise ConfigEntryNotReady(f"HTTP {resp.status}: {txt[:120]}")
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        raise ConfigEntryNotReady(f"Connection error: {err}") from err

    hass.data[DOMAIN][entry.entry_id] = {
        CONF_HOST: host,
        CONF_USERNAME: username,
        CONF_PASSWORD: password,
        CONF_IGNORE_TLS_ERRORS: ignore_tls,
        CONF_SCAN_INTERVAL: scan_interval,
        "use_http": use_http,
        "session": session,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        async def _handle_refresh(call: ServiceCall):
            for ent_data in hass.data.get(DOMAIN, {}).values():
                coord = ent_data.get("coordinator")
                if coord:
                    await coord.async_request_refresh()
        hass.services.async_register(DOMAIN, SERVICE_REFRESH, _handle_refresh)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
