
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.exceptions import ConfigEntryNotReady
import aiohttp
import async_timeout

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    _LOGGER.debug("GARO DEBUG: async_setup_entry called")

    options = entry.options
    data = entry.data

    host = options.get("host", data.get("host"))
    username = options.get("username", data.get("username"))
    password = options.get("password", data.get("password"))
    ignore_tls = options.get("ignore_tls_errors", data.get("ignore_tls_errors", True))

    session = aiohttp_client.async_get_clientsession(hass)
    auth = aiohttp.BasicAuth(username, password)
    url = f"https://{host}/status/energy-meter"
    ssl_context = False if ignore_tls else None

    try:
        async with async_timeout.timeout(10):
            _LOGGER.debug("GARO DEBUG: Sending initial connectivity test to %s", url)
            async with session.get(url, auth=auth, ssl=ssl_context) as response:
                if response.status != 200:
                    raise ConfigEntryNotReady(f"Unexpected HTTP status {response.status}")
                _LOGGER.debug("GARO DEBUG: Device responded with HTTP %s", response.status)
    except Exception as err:
        _LOGGER.error("Garo device not ready: %s", err)
        raise ConfigEntryNotReady("Device not reachable") from err

    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    return True

from .options import GaroOptionsFlowHandler


async def async_get_options_flow(config_entry):
    return GaroOptionsFlowHandler(config_entry)

