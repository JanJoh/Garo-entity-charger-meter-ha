from __future__ import annotations
import logging, asyncio, aiohttp
from datetime import timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers import aiohttp_client, device_registry as dr
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    UnitOfElectricCurrent, UnitOfElectricPotential, UnitOfPower, UnitOfEnergy, UnitOfTemperature
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN, CONF_HOST, CONF_USERNAME, CONF_PASSWORD,
    CONF_SCAN_INTERVAL, CONF_SLOW_SCAN_INTERVAL,
    CONF_IGNORE_TLS_ERRORS, CONF_ENABLE_PHASE_SENSORS,
    CONF_ENABLE_LINE_VOLTAGES, CONF_USE_HTTP, MANUFACTURER, PRODUCT_NAME,
    API_PATH, DEFAULT_SLOW_SCAN_INTERVAL
)

try:
    from .const import CONF_AUTH_SCHEME  # optional extension
except ImportError:
    CONF_AUTH_SCHEME = "auth_scheme"

API_PATH_TEMPS = "/status/temperatures"
API_PATH_FIRMWARE_VERSION = "/config/firmware-version"
API_PATH_DEVICE_ID = "/config/device-id"
API_PATH_UNIT_ID = "/config/unit-id"
API_PATH_CP_LEVEL_MAX = "/hal/cp-level-max"
API_PATH_CP_LEVEL_MIN = "/hal/cp-level-min"
API_PATH_CHARGING_STATE = "/status/charging-state"
API_PATH_PP_LEVEL = "/hal/pp-level"
API_PATH_NETWORK_INTERFACE = "/netconf/network-interface"
API_PATH_CONNECTION_STATUS = "/netconf/connection-status"
API_PATH_SIM_INFO = "/status/sim-info"
API_PATH_PLC_STATUS = "/plc/device-status"

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
    "cpu_temperature": {"name":"Charger CPU Temperature","device_class":SensorDeviceClass.TEMPERATURE,"unit":UnitOfTemperature.CELSIUS,"state_class":SensorStateClass.MEASUREMENT},
    "board_temperature": {"name":"Charger Board Temperature","device_class":SensorDeviceClass.TEMPERATURE,"unit":UnitOfTemperature.CELSIUS,"state_class":SensorStateClass.MEASUREMENT},
    "firmware_version": {"name":"Firmware Version","device_class":None,"unit":None,"state_class":None,"entity_category":EntityCategory.DIAGNOSTIC,"enabled_default":False},
    "device_id": {"name":"Device ID","device_class":None,"unit":None,"state_class":None,"entity_category":EntityCategory.DIAGNOSTIC,"enabled_default":False},
    "unit_id": {"name":"Unit ID","device_class":None,"unit":None,"state_class":None,"entity_category":EntityCategory.DIAGNOSTIC,"enabled_default":False},
    "cp_level_max": {"name":"CP Signal Max","device_class":SensorDeviceClass.VOLTAGE,"unit":UnitOfElectricPotential.VOLT,"state_class":SensorStateClass.MEASUREMENT,"enabled_default":False},
    "cp_level_min": {"name":"CP Signal Min","device_class":SensorDeviceClass.VOLTAGE,"unit":UnitOfElectricPotential.VOLT,"state_class":SensorStateClass.MEASUREMENT,"enabled_default":False},
    "charging_state": {"name":"Charging State","device_class":None,"unit":None,"state_class":None,"enabled_default":False},
    "pp_level": {"name":"PP Level","device_class":SensorDeviceClass.VOLTAGE,"unit":UnitOfElectricPotential.VOLT,"state_class":SensorStateClass.MEASUREMENT,"enabled_default":False},
    "cp_state": {"name":"CP State","device_class":None,"unit":None,"state_class":None,"enabled_default":True},
    "network_interface": {"name":"Network Interface","device_class":None,"unit":None,"state_class":None,"entity_category":EntityCategory.DIAGNOSTIC,"enabled_default":False},
    "ip_address": {"name":"IP Address","device_class":None,"unit":None,"state_class":None,"entity_category":EntityCategory.DIAGNOSTIC,"enabled_default":False},
    "wifi_ssid": {"name":"Wi-Fi SSID","device_class":None,"unit":None,"state_class":None,"entity_category":EntityCategory.DIAGNOSTIC,"enabled_default":False},
    "wifi_signal": {"name":"Wi-Fi Signal","device_class":SensorDeviceClass.SIGNAL_STRENGTH,"unit":"dBm","state_class":SensorStateClass.MEASUREMENT,"entity_category":EntityCategory.DIAGNOSTIC,"enabled_default":False},
    "sim_iccid": {"name":"SIM ICCID","device_class":None,"unit":None,"state_class":None,"entity_category":EntityCategory.DIAGNOSTIC,"enabled_default":False},
    "sim_operator": {"name":"SIM Operator","device_class":None,"unit":None,"state_class":None,"entity_category":EntityCategory.DIAGNOSTIC,"enabled_default":False},
    "plc_firmware_version": {"name":"PLC Firmware Version","device_class":None,"unit":None,"state_class":None,"entity_category":EntityCategory.DIAGNOSTIC,"enabled_default":False},
    "plc_zero_cross": {"name":"PLC Zero Cross","device_class":None,"unit":None,"state_class":None,"entity_category":EntityCategory.DIAGNOSTIC,"enabled_default":False},
}

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    data = hass.data[DOMAIN][entry.entry_id]

    def opt(key):
        return entry.options.get(key, entry.data.get(key))

    host = opt(CONF_HOST)
    username = opt(CONF_USERNAME)
    password = opt(CONF_PASSWORD)
    scan_interval = opt(CONF_SCAN_INTERVAL)
    slow_scan_interval = opt(CONF_SLOW_SCAN_INTERVAL) or DEFAULT_SLOW_SCAN_INTERVAL
    ignore_tls = opt(CONF_IGNORE_TLS_ERRORS)
    use_http = opt(CONF_USE_HTTP)
    auth_scheme = opt(CONF_AUTH_SCHEME)

    _LOGGER.debug(
        "Setup entry with host=%s user=%s password_set=%s auth_scheme=%s",
        host,
        username,
        bool(password),
        auth_scheme,
    )

    scheme = "http" if use_http else "https"
    base_url = f"{scheme}://{host}{API_PATH}"
    temp_url = f"{scheme}://{host}{API_PATH_TEMPS}"
    firmware_url = f"{scheme}://{host}{API_PATH_FIRMWARE_VERSION}"
    device_id_url = f"{scheme}://{host}{API_PATH_DEVICE_ID}"
    unit_id_url = f"{scheme}://{host}{API_PATH_UNIT_ID}"
    cp_max_url = f"{scheme}://{host}{API_PATH_CP_LEVEL_MAX}"
    cp_min_url = f"{scheme}://{host}{API_PATH_CP_LEVEL_MIN}"
    charging_state_url = f"{scheme}://{host}{API_PATH_CHARGING_STATE}"
    pp_level_url = f"{scheme}://{host}{API_PATH_PP_LEVEL}"
    network_interface_url = f"{scheme}://{host}{API_PATH_NETWORK_INTERFACE}"
    connection_status_url = f"{scheme}://{host}{API_PATH_CONNECTION_STATUS}"
    sim_info_url = f"{scheme}://{host}{API_PATH_SIM_INFO}"
    plc_status_url = f"{scheme}://{host}{API_PATH_PLC_STATUS}"

    def _extract_simple(payload):
        """Pull a scalar out of a single-value JSON response (dict or bare value)."""
        if isinstance(payload, dict):
            return next(iter(payload.values()), None)
        return payload

    session = data.get("session") or aiohttp_client.async_get_clientsession(hass, verify_ssl=not ignore_tls)

    async def _update_slow():
        result = {}

        # --- Temperature metrics ---
        try:
            async with asyncio.timeout(10):
                async with session.get(temp_url, auth=aiohttp.BasicAuth(username, password)) as resp:
                    t_text = await resp.text()
                    if resp.status == 200:
                        try:
                            temps = await resp.json(content_type=None)
                        except Exception:
                            _LOGGER.warning("Temp JSON decode failed URL=%s Raw=%s", temp_url, t_text[:120])
                        else:
                            if isinstance(temps, dict):
                                cpu = temps.get("cpu")
                                board = temps.get("base_board")
                                if isinstance(cpu, (int, float)):
                                    result["cpu_temperature"] = float(cpu)
                                if isinstance(board, (int, float)):
                                    result["board_temperature"] = float(board)
                    else:
                        _LOGGER.debug("Temp endpoint status %s body=%s", resp.status, t_text[:120])
        except Exception as e:
            _LOGGER.debug("Temperature update failed: %s", e)

        # --- Firmware version, device ID, unit ID ---
        for label, url, key in (
            ("firmware_version", firmware_url, "firmware_version"),
            ("device_id", device_id_url, "device_id"),
            ("unit_id", unit_id_url, "unit_id"),
        ):
            try:
                async with asyncio.timeout(10):
                    async with session.get(url, auth=aiohttp.BasicAuth(username, password)) as resp:
                        if resp.status == 200:
                            try:
                                raw = await resp.json(content_type=None)
                            except Exception:
                                raw = await resp.text()
                            val = _extract_simple(raw)
                            if val is not None:
                                result[key] = str(val)
                        else:
                            _LOGGER.debug("%s endpoint status %s", label, resp.status)
            except Exception as e:
                _LOGGER.debug("%s fetch failed: %s", label, e)

        # --- Network interface and connection status ---
        try:
            async with asyncio.timeout(10):
                async with session.get(network_interface_url, auth=aiohttp.BasicAuth(username, password)) as resp:
                    if resp.status == 200:
                        try:
                            raw = await resp.json(content_type=None)
                        except Exception:
                            raw = await resp.text()
                        val = _extract_simple(raw)
                        _LOGGER.debug("network_interface=%r (raw=%r)", val, raw)
                        if val is not None:
                            result["network_interface"] = str(val)
                    else:
                        _LOGGER.debug("network_interface endpoint status %s", resp.status)
        except Exception as e:
            _LOGGER.debug("network_interface fetch failed: %s", e)

        try:
            async with asyncio.timeout(10):
                async with session.get(connection_status_url, auth=aiohttp.BasicAuth(username, password)) as resp:
                    if resp.status == 200:
                        try:
                            raw = await resp.json(content_type=None)
                        except Exception:
                            _LOGGER.debug("connection_status JSON decode failed")
                        else:
                            _LOGGER.debug("connection_status raw=%r", raw)
                            if isinstance(raw, dict):
                                for key in ("ip_address", "ip", "address", "ipv4"):
                                    if key in raw:
                                        result["ip_address"] = str(raw[key])
                                        break
                                for key in ("ssid", "SSID", "wifi_ssid"):
                                    if key in raw:
                                        result["wifi_ssid"] = str(raw[key])
                                        break
                                for key in ("rssi", "RSSI", "signal", "signal_strength", "signal_level"):
                                    if key in raw:
                                        try:
                                            result["wifi_signal"] = float(raw[key])
                                        except (ValueError, TypeError):
                                            pass
                                        break
                    else:
                        _LOGGER.debug("connection_status endpoint status %s", resp.status)
        except Exception as e:
            _LOGGER.debug("connection_status fetch failed: %s", e)

        # --- SIM card info ---
        try:
            async with asyncio.timeout(10):
                async with session.get(sim_info_url, auth=aiohttp.BasicAuth(username, password)) as resp:
                    if resp.status == 200:
                        try:
                            raw = await resp.json(content_type=None)
                        except Exception:
                            _LOGGER.debug("sim_info JSON decode failed")
                        else:
                            _LOGGER.debug("sim_info raw=%r", raw)
                            if isinstance(raw, dict):
                                for k in ("iccid", "ICCID"):
                                    if k in raw:
                                        result["sim_iccid"] = str(raw[k])
                                        break
                                for k in ("operator", "carrier", "network", "plmn"):
                                    if k in raw:
                                        result["sim_operator"] = str(raw[k])
                                        break
                    else:
                        _LOGGER.debug("sim_info endpoint status %s", resp.status)
        except Exception as e:
            _LOGGER.debug("sim_info fetch failed: %s", e)

        # --- PLC device status ---
        try:
            async with asyncio.timeout(10):
                async with session.get(plc_status_url, auth=aiohttp.BasicAuth(username, password)) as resp:
                    if resp.status == 200:
                        try:
                            raw = await resp.json(content_type=None)
                        except Exception:
                            _LOGGER.debug("plc_device_status JSON decode failed")
                        else:
                            _LOGGER.debug("plc_device_status raw=%r", raw)
                            if isinstance(raw, dict):
                                if "firmware_version" in raw:
                                    result["plc_firmware_version"] = str(raw["firmware_version"])
                                if "zero_cross" in raw:
                                    result["plc_zero_cross"] = str(raw["zero_cross"])
                    else:
                        _LOGGER.debug("plc_device_status endpoint status %s", resp.status)
        except Exception as e:
            _LOGGER.debug("plc_device_status fetch failed: %s", e)

        return result

    async def _update_fast():
        # Start with last known slow data so entities always have a full picture
        result = dict(slow_coordinator.data or {})

        # --- Energy / electrical metrics ---
        try:
            async with asyncio.timeout(15):
                async with session.get(base_url, auth=aiohttp.BasicAuth(username, password)) as resp:
                    text = await resp.text()
                    if resp.status != 200:
                        _LOGGER.warning("Status %s energy URL=%s body=%s", resp.status, base_url, text[:160])
                    else:
                        try:
                            payload = await resp.json(content_type=None)
                        except Exception:
                            _LOGGER.error("JSON decode failed energy URL=%s Raw=%s", base_url, text[:160])
                        else:
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
                                        kwh = val / 1000.0
                                        prev = (fast_coordinator.data or {}).get("energy")
                                        if prev is not None and kwh < prev:
                                            _LOGGER.warning("Energy counter decreased (%.3f -> %.3f), keeping previous", prev, kwh)
                                            kwh = prev
                                        result["energy"] = kwh
                                    elif meas == "Power.Active.Import":
                                        result["power"] = val
        except Exception as e:
            _LOGGER.warning("Energy update failed: %s", e)

        # Derived metrics
        if all(k in result for k in ("current_l1", "current_l2", "current_l3")):
            result["current_total"] = result["current_l1"] + result["current_l2"] + result["current_l3"]
        if all(k in result for k in ("voltage_l1", "voltage_l2", "voltage_l3")):
            result["voltage_avg"] = (
                result["voltage_l1"] + result["voltage_l2"] + result["voltage_l3"]
            ) / 3.0

        # --- CP signal levels ---
        for label, url, key in (
            ("cp_level_max", cp_max_url, "cp_level_max"),
            ("cp_level_min", cp_min_url, "cp_level_min"),
        ):
            try:
                async with asyncio.timeout(10):
                    async with session.get(url, auth=aiohttp.BasicAuth(username, password)) as resp:
                        if resp.status == 200:
                            try:
                                raw = await resp.json(content_type=None)
                            except Exception:
                                _LOGGER.debug("%s JSON decode failed", label)
                                continue
                            val = _extract_simple(raw)
                            try:
                                result[key] = float(val)
                            except (ValueError, TypeError):
                                _LOGGER.debug("%s unexpected value: %r", label, val)
                        else:
                            _LOGGER.debug("%s endpoint status %s", label, resp.status)
            except Exception as e:
                _LOGGER.debug("%s fetch failed: %s", label, e)

        # --- Derived IEC 61851 CP state ---
        if "cp_level_max" in result:
            v = result["cp_level_max"]
            if v > 10.5:
                result["cp_state"] = "No vehicle connected"
            elif v > 7.5:
                result["cp_state"] = "Vehicle connected"
            elif v > 4.5:
                result["cp_state"] = "Charging"
            elif v > 1.5:
                result["cp_state"] = "Charging (ventilation required)"
            elif v > -1.5:
                result["cp_state"] = "No power"
            else:
                result["cp_state"] = "Fault"

        # --- Charging state ---
        try:
            async with asyncio.timeout(10):
                async with session.get(charging_state_url, auth=aiohttp.BasicAuth(username, password)) as resp:
                    if resp.status == 200:
                        try:
                            raw = await resp.json(content_type=None)
                        except Exception:
                            raw = await resp.text()
                        val = _extract_simple(raw)
                        if val is not None:
                            result["charging_state"] = str(val)
                            _LOGGER.debug("charging_state=%s (raw=%r)", val, raw)
                    else:
                        _LOGGER.debug("charging_state endpoint status %s", resp.status)
        except Exception as e:
            _LOGGER.debug("charging_state fetch failed: %s", e)

        # --- PP level (Proximity Pilot — cable connection/type) ---
        try:
            async with asyncio.timeout(10):
                async with session.get(pp_level_url, auth=aiohttp.BasicAuth(username, password)) as resp:
                    if resp.status == 200:
                        try:
                            raw = await resp.json(content_type=None)
                        except Exception:
                            _LOGGER.debug("pp_level JSON decode failed")
                        else:
                            val = _extract_simple(raw)
                            _LOGGER.debug("pp_level=%r (raw=%r)", val, raw)
                            try:
                                result["pp_level"] = float(val)
                            except (ValueError, TypeError):
                                _LOGGER.debug("pp_level unexpected value: %r", val)
                    else:
                        _LOGGER.debug("pp_level endpoint status %s", resp.status)
        except Exception as e:
            _LOGGER.debug("pp_level fetch failed: %s", e)

        return result

    slow_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="garo_charger_meter_slow",
        update_method=_update_slow,
        update_interval=timedelta(seconds=slow_scan_interval),
    )
    fast_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="garo_charger_meter_fast",
        update_method=_update_fast,
        update_interval=timedelta(seconds=scan_interval),
    )
    data["coordinator"] = fast_coordinator
    data["slow_coordinator"] = slow_coordinator
    await slow_coordinator.async_config_entry_first_refresh()
    await fast_coordinator.async_config_entry_first_refresh()
    # DataUpdateCoordinator only self-schedules while it has listeners.
    # Entities subscribe to fast_coordinator, so drive the slow coordinator
    # with an independent HA interval timer instead.
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            lambda _now: hass.async_create_task(slow_coordinator.async_refresh()),
            timedelta(seconds=slow_scan_interval),
        )
    )

    enable_phase = entry.options.get(CONF_ENABLE_PHASE_SENSORS, entry.data.get(CONF_ENABLE_PHASE_SENSORS, True))
    enable_line = entry.options.get(CONF_ENABLE_LINE_VOLTAGES, entry.data.get(CONF_ENABLE_LINE_VOLTAGES, False))

    wanted = [
        "power","energy","current_total","voltage_avg",
        "cpu_temperature","board_temperature",
        "firmware_version","device_id","unit_id",
        "cp_level_max","cp_level_min","cp_state",
        "charging_state","pp_level",
        "network_interface","ip_address","wifi_ssid","wifi_signal",
        "sim_iccid","sim_operator",
        "plc_firmware_version","plc_zero_cross",
    ]
    if enable_phase:
        wanted += ["current_l1","current_l2","current_l3","voltage_l1","voltage_l2","voltage_l3"]
    if enable_line:
        wanted += ["voltage_l1_l2","voltage_l2_l3","voltage_l3_l1"]

    entities = [GaroChargerMeterSensor(fast_coordinator, entry, host, k) for k in wanted if k in SENSOR_MAP]
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
        self._attr_entity_category = info.get("entity_category")
        self._attr_entity_registry_enabled_default = info.get("enabled_default", True)

    @property
    def native_value(self):
        return self.coordinator.data.get(self._key)

    @property
    def device_info(self):
        data = self.coordinator.hass.data[DOMAIN][self._entry.entry_id]
        scheme = "http" if data.get("use_http") else "https"
        coord_data = self.coordinator.data or {}
        fw = coord_data.get("firmware_version")
        device_id = coord_data.get("device_id")
        unit_id = coord_data.get("unit_id")

        connections: set = set()
        if unit_id and "-" in unit_id:
            mac_raw = unit_id.split("-")[-1]
            if len(mac_raw) == 12 and all(c in "0123456789ABCDEFabcdef" for c in mac_raw):
                mac = ":".join(mac_raw[i:i+2] for i in range(0, 12, 2))
                connections.add((dr.CONNECTION_NETWORK_MAC, mac.upper()))

        return DeviceInfo(
            identifiers={(DOMAIN, device_id or self._host)},
            connections=connections,
            manufacturer=MANUFACTURER,
            name=PRODUCT_NAME,
            model="EV Charger",
            serial_number=device_id,
            sw_version=fw,
            configuration_url=f"{scheme}://{self._host}"
        )
