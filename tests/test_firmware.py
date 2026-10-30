from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache_with_extra_data

from custom_components.garo_entity_charger_meter.const import DOMAIN
from custom_components.garo_entity_charger_meter.firmware import FirmwareState, version_from_location
from custom_components.garo_entity_charger_meter.logtail import ChargerLogState

from .test_charger import BASE, HOST

ORDER = ('2026-10-29T20:00:16.121+00:00 ocpp:57 INFO GaroCS-X: < [2,"a","SignedUpdateFirmware",{"requestId":9,'
         '"firmware":{"location":"https://example.com/fw/garo-entity-3.0.12-4.10.3-imx-r5bf98996f.upd",'
         '"retrieveDateTime":"1970-01-01T00:00:01Z","signingCertificate":"c","signature":"s"}}]')


def status(t, s):
    return f'{t} ocpp:76 INFO GaroCS-X: > [2,"b","SignedFirmwareStatusNotification",{{"status":"{s}","requestId":9}}]'


def test_version_from_location():
    assert version_from_location("https://x/y/garo-entity-3.0.12-4.10.3-imx-r5bf98996f.upd?sig=1") == (
        "4.10.3", "5bf98996f", "garo-entity-3.0.12-4.10.3-imx-r5bf98996f.upd")
    assert version_from_location("https://x/other.bin") == (None, None, "other.bin")


def test_feed_order_and_progress():
    st = ChargerLogState()
    st.feed([
        '2026-10-29T20:00:15.5+00:00 ocpp:57 INFO GaroCS-X: < [2,"t","TriggerMessage",{"requestedMessage":"FirmwareStatusNotification","connectorId":0}]',
        '2026-10-29T20:00:15.6+00:00 ocpp:76 INFO GaroCS-X: > [2,"i","FirmwareStatusNotification",{"status":"Idle"}]',
        ORDER,
        status("2026-10-29T20:01:48+00:00", "Downloaded"),
        status("2026-10-29T20:01:49+00:00", "SignatureVerified"),
    ])
    fw = st.firmware
    assert (fw.version, fw.revision, fw.status) == ("4.10.3", "5bf98996f", "SignatureVerified")
    assert fw.summary == "Downloaded and verified, waiting to install" and not fw.installing
    st.feed([status("2026-10-30T08:34:34+00:00", "Installing")])
    assert st.firmware.installing
    assert FirmwareState.from_dict(fw.as_dict()) == fw


def test_backfill_finds_newest_order_and_status():
    st = ChargerLogState()
    st.backfill(reversed([
        ORDER.replace("4.10.3", "4.9.0"),
        status("2026-10-20T10:00:00+00:00", "Installed"),
        ORDER,
        status("2026-10-29T20:01:49+00:00", "SignatureVerified"),
    ]))
    assert st.firmware.version == "4.10.3"
    assert st.firmware.status == "SignatureVerified"


async def _setup(hass, aioclient_mock, log_lines, installed="4.2.7"):
    from .test_charger import _mock_device
    log = ("cut line\n" + "\n".join(log_lines) + "\n").encode()
    aioclient_mock.get(f"{BASE}/config/firmware-version", json={"version": installed, "revision": "abc"})
    aioclient_mock.get(f"{BASE}/log/garoevse.log", content=log, status=206,
                       headers={"Content-Range": f"bytes 0-{len(log) - 1}/{len(log)}"})
    _mock_device(aioclient_mock)
    entry = MockConfigEntry(domain=DOMAIN, unique_id=HOST,
                            data={"host": HOST, "username": "u", "password": "p", "ignore_tls_errors": True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    states = hass.states.async_all("update")
    assert len(states) == 1, states
    return states[0]


async def test_update_available(hass: HomeAssistant, aioclient_mock):
    st = await _setup(hass, aioclient_mock, [ORDER, status("2026-10-29T20:01:49+00:00", "SignatureVerified")])
    assert st.state == "on"
    assert st.attributes["installed_version"] == "4.2.7"
    assert st.attributes["latest_version"] == "4.10.3"
    assert st.attributes["in_progress"] is False
    assert st.attributes["release_summary"] == "Downloaded and verified, waiting to install"
    assert st.attributes["firmware_status"] == "SignatureVerified"
    assert st.attributes["supported_features"] == 4  # PROGRESS only: reported, never installed from HA
    assert "entity_picture" not in st.attributes


async def test_installing(hass: HomeAssistant, aioclient_mock):
    st = await _setup(hass, aioclient_mock, [ORDER, status("2026-10-30T08:34:34+00:00", "Installing")])
    assert st.state == "on" and st.attributes["in_progress"] is True


async def test_installed_version_matches(hass: HomeAssistant, aioclient_mock):
    st = await _setup(hass, aioclient_mock, [ORDER, status("2026-10-30T08:41:59+00:00", "Installed")], installed="4.10.3")
    assert st.state == "off"
    assert st.attributes["latest_version"] == "4.10.3"
    assert st.attributes["release_summary"] is None


async def test_no_order_seen(hass: HomeAssistant, aioclient_mock):
    st = await _setup(hass, aioclient_mock, [])
    assert st.state == "off" and st.attributes["latest_version"] == "4.2.7"


async def test_order_restored_after_restart(hass: HomeAssistant, aioclient_mock):
    saved = FirmwareState()
    saved.feed_line(ORDER, None)
    saved.feed_line(status("2026-10-29T20:01:49+00:00", "SignatureVerified"), None)
    mock_restore_cache_with_extra_data(hass, [(State("update.charger_meter_firmware", "on"), saved.as_dict())])
    st = await _setup(hass, aioclient_mock, [])
    assert st.entity_id == "update.charger_meter_firmware"
    assert st.state == "on" and st.attributes["latest_version"] == "4.10.3"
