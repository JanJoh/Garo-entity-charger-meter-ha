
import logging
import aiohttp
import async_timeout
from datetime import timedelta
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.entity import DeviceInfo

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    session = aiohttp_client.async_get_clientsession(hass)
    coordinator = GaroDataUpdateCoordinator(hass, session, entry.data["host"])

    await coordinator.async_config_entry_first_refresh()

    sensors = [
        GaroSensor(coordinator, key, description)
        for key, description in coordinator.data.items()
    ]
    async_add_entities(sensors)

class GaroDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, session, host):
        super().__init__(
            hass,
            _LOGGER,
            name="Garo Charger Meter",
            update_interval=SCAN_INTERVAL,
        )
        self.session = session
        self.host = host

    async def _async_update_data(self):
        url = f"http://{self.host}/status/measurements"
        try:
            async with async_timeout.timeout(10):
                async with self.session.get(url) as response:
                    if response.status != 200:
                        raise Exception(f"HTTP error {response.status}")
                    raw_data = await response.json()

            parsed = {}
            for block in raw_data:
                for item in block.get("sampledValue", []):
                    measurand = item.get("measurand", "Unknown")
                    unit = item.get("unit", "")
                    value = float(item.get("value", 0.0))
                    phase = item.get("phase", "")
                    key_parts = [measurand]
                    if phase:
                        key_parts.append(phase)
                    key = "_".join(key_parts)
                    parsed[key] = {
                        "name": f"{measurand} {phase}".strip(),
                        "unit": unit,
                        "value": value,
                    }

            return parsed
        except Exception as e:
            _LOGGER.error("Error fetching data: %s", e)
            return {}

class GaroSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, key, description):
        super().__init__(coordinator)
        self._key = key
        self._attr_name = description["name"]
        self._attr_native_unit_of_measurement = description["unit"]
        self._attr_unique_id = f"garo_charger_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(self.coordinator.host, "garo_entity_charger_meter")},
            name="Garo Charger Meter",
            manufacturer="Garo",
        )

    @property
    def native_value(self):
        return self.coordinator.data.get(self._key, {}).get("value")
