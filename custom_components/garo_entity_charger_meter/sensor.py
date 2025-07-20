from __future__ import annotations
import logging, async_timeout, aiohttp
from datetime import timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import aiohttp_client
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    UnitOfElectricCurrent, UnitOfElectricPotential, UnitOfPower, UnitOfEnergy
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN, CONF_HOST, CONF_USERNAME, CONF_PASSWORD,
    CONF_SCAN_INTERVAL, CONF_IGNORE_TLS_ERRORS, CONF_ENABLE_PHASE_SENSORS,
    CONF_ENABLE_LINE_VOLTAGES, CONF_USE_HTTP, MANUFACTURER, PRODUCT_NAME,
    API_PATH
)

# Optional auth scheme constant if added later
try:
    from .const import CONF_AUTH_SCHEME  # optional extension
except ImportError:
    CONF_AUTH_SCHEME = "auth_scheme"

_LOGGER = logging.getLogger(__name__)

SENSOR_MAP = {
    "current_l1": {"name":"Charger L1 Current","device_class":SensorDeviceClass.CURRENT,"unit":UnitOfElectricCurrent.AMPERE,"state_class":SensorStateClass.MEASUREMENT},
    "current_l2": {"name":"Charger L2 Current","device_class":SensorDeviceClass.CURRENT,"unit":UnitOfElectricCurrent.AMPERE,"state_class":SensorStateClass.MEASUREMENT},
    "current_l3": {"name":"Charger L3 Current","device_class":SensorDeviceClass.CURRENT,"unit":UnitOfElectricCurrent.AMPERE,"state_class":SensorStateClass.MEASUREMENT},
    "voltage_l1": {"name":"Charger L1 Voltage","device_class":SensorDeviceClass.VOLTAGE,"unit":UnitOfElectricPotential.VOLT,"state_class":SensorStateClass.MEASUREMENT},
    "voltage_l2": {"name":"Charger L2 Voltage","device_class":SensorDeviceClass.VOLTAGE,"unit":UnitOfElectricPotential.VOLT,"state_class":SensorStateClass.MEASUREMENT},
    "voltage_l3": {"name":"Charger L3 Voltage","device_class":SensorDeviceClass.VOLTAGE,"unit":UnitOfElectricPotential.VOLT,"state_class":SensorStateClass.MEASUREMENT},
    "voltage_l1_l2": {"name":"Charger L1-L2 Voltage","device_class":SensorDeviceClass.VOLTAGE,"unit":UnitOfElectricPotential.VOLT,"state_class":SensorStateClass.MEASUREMENT},
    "voltage_l2_l3": {"name":"Charger L2-L3 Voltage","device_class":SensorDeviceClass.VOLTAGE,"unit":UnitOfElectricPotential.VOLT,"state_class":SensorStateClass.MEASUREMENT},
    "voltage_l3_l1": {"name":"Charger L3-L1 Voltage","device_class":SensorDeviceClass.VOLTAGE,"unit":UnitOfElectricPotential.VOLT,"state_class":SensorStateClass.MEASUREMENT},
    "power": {"name":"Charger Active Power","device_class":SensorDeviceClass.POWER,"unit":UnitOfPower.WATT,"state_class":SensorStateClass.MEASUREMENT},
    "energy": {"name":"Charger Imported Energy","device_class":SensorDeviceClass.ENERGY,"unit":UnitOfEnergy.KILO_WATT_HOUR,"state_class":SensorStateClass.TOTAL_INCREASING},
    "current_total": {"name":"Charger Total Current","device_class":SensorDeviceClass.CURRENT,"unit":UnitOfElectricCurrent.AMPERE,"state_class":SensorStateClass.MEASUREMENT},
    "voltage_avg": {"name":"Charger Average Voltage","device_class":SensorDeviceClass.VOLTAGE,"unit":UnitOfElectricPotential.VOLT,"state_class":SensorStateClass.MEASUREMENT},
}

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    data = hass.data[DOMAIN][entry.entry_id]

    def opt(key):
        return entry.options.get(key, entry.data.get(key))

    host = opt(CONF_HOST)
    username = opt(CONF_USERNAME)
    password = opt(CONF_PASSWORD)
    scan_interval = opt(CONF_SCAN_INTERVAL)
    ignore_tls = opt(CONF_IGNORE_TLS_ERRORS)
    use_http = opt(CONF_USE_HTTP)
    auth_scheme = opt(CONF_AUTH_SCHEME)

    scheme = "http" if use_http else "https"
    base_url = f"{scheme}://{host}{API_PATH}"
    session = data.get("session") or aiohttp_client.async_get_clientsession(hass, verify_ssl=not ignore_tls)

    async def _async_update_data():
        url = base_url
        result = {}
        try:
            async with async_timeout.timeout(15):
                async with session.get(url, auth=aiohttp.BasicAuth(username, password)) as resp:
                    text = await resp.text()
                    if resp.status != 200:
                        _LOGGER.warning(
                            "Status %s URL=%s body=%s (user=%s pass_set=%s)",
                            resp.status,
                            url,
                            text[:160],
                            username,
                            bool(password),
                        )
                        return result
                    try:
                        payload = await resp.json(content_type=None)
                    except Exception:
                        _LOGGER.error("JSON decode failed URL=%s Raw=%s", url, text[:160])
                        return result
        except Exception as e:
            _LOGGER.warning("Update failed: %s (host=%s)", e, host)
            return result

        for block in payload:
            for sv in block.get("sampledValue", []):
                meas = sv.get("measurand")
                phase = sv.get("phase")
                raw = sv.get("value")
                if raw is None:
                    continue
                try:
                    val = float(raw)
                except (ValueError, TypeError):
                    continue
                if meas == "Current.Import":
                    if phase == "L1": result["current_l1"] = val
                    elif phase == "L2": result["current_l2"] = val
                    elif phase == "L3": result["current_l3"] = val
                elif meas == "Voltage":
                    if phase == "L1-N": result["voltage_l1"] = val
                    elif phase == "L2-N": result["voltage_l2"] = val
                    elif phase == "L3-N": result["voltage_l3"] = val
                    elif phase == "L1-L2": result["voltage_l1_l2"] = val
                    elif phase == "L2-L3": result["voltage_l2_l3"] = val
                    elif phase == "L3-L1": result["voltage_l3_l1"] = val
                elif meas == "Energy.Active.Import.Register":
                    result["energy"] = val / 1000.0
                elif meas == "Power.Active.Import":
                    result["power"] = val

        if all(k in result for k in ("current_l1","current_l2","current_l3")):
            result["current_total"] = result["current_l1"] + result["current_l2"] + result["current_l3"]
        if all(k in result for k in ("voltage_l1","voltage_l2","voltage_l3")):
            result["voltage_avg"] = (result["voltage_l1"] + result["voltage_l2"] + result["voltage_l3"]) / 3.0
        return result

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="garo_entity_charger_meter",
        update_method=_async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )
    data["coordinator"] = coordinator
    await coordinator.async_config_entry_first_refresh()

    enable_phase = entry.options.get(CONF_ENABLE_PHASE_SENSORS, entry.data.get(CONF_ENABLE_PHASE_SENSORS, True))
    enable_line = entry.options.get(CONF_ENABLE_LINE_VOLTAGES, entry.data.get(CONF_ENABLE_LINE_VOLTAGES, False))
    wanted = ["power","energy","current_total","voltage_avg"]
    if enable_phase:
        wanted += ["current_l1","current_l2","current_l3","voltage_l1","voltage_l2","voltage_l3"]
    if enable_line:
        wanted += ["voltage_l1_l2","voltage_l2_l3","voltage_l3_l1"]

    entities = [GaroChargerMeterSensor(coordinator, entry, host, k) for k in wanted if k in SENSOR_MAP]
    async_add_entities(entities)

class GaroChargerMeterSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator, entry, host, key):
        super().__init__(coordinator)
        self._key = key
        self._entry = entry
        self._host = host
        info = SENSOR_MAP[key]
        self._attr_name = info["name"]
        self._attr_unique_id = f"{host}_{key}"
        self._attr_device_class = info.get("device_class")
        self._attr_native_unit_of_measurement = info.get("unit")
        self._attr_state_class = info.get("state_class")

    @property
    def native_value(self):
        return self.coordinator.data.get(self._key)

    @property
    def device_info(self):
        scheme = "http" if self.coordinator.hass.data[DOMAIN][self._entry.entry_id].get("use_http") else "https"
        return DeviceInfo(
            identifiers={(DOMAIN, self._host)},
            manufacturer=MANUFACTURER,
            name=PRODUCT_NAME,
            model="EV Charger",
            configuration_url=f"{scheme}://{self._host}"
        )
