"""Firmware update entity: shows an update GARO has pushed to the charger.

GARO installs updates itself; this entity only reports them (no install
action). The installed version comes from /config/firmware-version, the
offered one and its progress from the device log. The order is kept across
restarts because the log only reaches back a couple of days.
"""
from __future__ import annotations

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoredExtraData
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HOST, DOMAIN
from .firmware import FirmwareState
from .sensor import _device_info

KEY = "firmware_update"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    data = hass.data[DOMAIN][entry.entry_id]
    host = entry.data.get(CONF_HOST)
    log_state = data.get("log_state")
    if log_state is None:
        # Log reading turned off in options: without the log there is nothing to report.
        registry = er.async_get(hass)
        if entity_id := registry.async_get_entity_id("update", DOMAIN, f"{host}_{KEY}"):
            registry.async_remove(entity_id)
        return
    async_add_entities([GaroFirmwareUpdate(data["coordinator"], entry, host, log_state.firmware)])


class GaroFirmwareUpdate(CoordinatorEntity, UpdateEntity):
    _attr_has_entity_name = True
    _attr_name = "Firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_title = "GARO Entity firmware"
    # Progress only; no INSTALL feature, HA never sends the unit an update command.
    _attr_supported_features = UpdateEntityFeature.PROGRESS

    def __init__(self, coordinator, entry, host, firmware: FirmwareState):
        super().__init__(coordinator)
        self._entry = entry
        self._host = host
        self._live = firmware
        self._restored = FirmwareState()
        self._attr_unique_id = f"{host}_{KEY}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_extra_data()) is not None:
            self._restored = FirmwareState.from_dict(last.as_dict())

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
        return RestoredExtraData(self._firmware.as_dict())

    @property
    def _firmware(self) -> FirmwareState:
        """The log's view, or the saved one until the log shows an order."""
        if self._live.file is not None or self._restored.file is None:
            return self._live
        return self._restored

    @property
    def _pending(self) -> bool:
        fw, installed = self._firmware, self.installed_version
        return fw.version is not None and installed is not None and fw.version != installed

    @property
    def installed_version(self) -> str | None:
        return (self.coordinator.data or {}).get("firmware_version")

    @property
    def latest_version(self) -> str | None:
        return self._firmware.version if self._pending else self.installed_version

    @property
    def in_progress(self) -> bool:
        return self._pending and self._firmware.installing

    @property
    def release_summary(self) -> str | None:
        return self._firmware.summary if self._pending else None

    @property
    def extra_state_attributes(self):
        fw = self._firmware
        if fw.file is None:
            return None
        return {
            "firmware_status": fw.status,
            "status_changed_at": fw.status_at.isoformat() if fw.status_at else None,
            "ordered_at": fw.ordered_at.isoformat() if fw.ordered_at else None,
            "file": fw.file,
        }

    @property
    def device_info(self):
        return _device_info(self.coordinator, self._entry, self._host)
