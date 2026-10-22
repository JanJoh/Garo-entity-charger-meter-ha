from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.garo_entity_charger_meter.const import DOMAIN
from custom_components.garo_entity_charger_meter.logtail import ChargerLogState, relay_mode_name

HOST = "192.0.2.20"
BASE = f"https://{HOST}"

LOG = (
    "cut line\n"
    "2026-10-22T10:20:08.1+00:00 charging:1170 INFO max_current=9, DLM=9, FixCab=20, PP=0, ConfMax=12, SC=16, Delayed=16, OwnerMin=6, Bracket=16, Derating=12, CPUOverTemp=16, 10%OverloadProt=False\n"
    "2026-10-22T10:20:10.0+00:00 charging:2124 INFO Activate relays, mode=mode_1ph_l1_n\n"
    "2026-10-22T10:20:54.0+00:00 charging:1170 INFO max_current=1, DLM=5, FixCab=20, PP=0, ConfMax=12, SC=16, Delayed=16, OwnerMin=6, Bracket=16, Derating=12, CPUOverTemp=16, 10%OverloadProt=False\n"
    "2026-10-22T10:20:54.5+00:00 status_handler:99 INFO Status changed, connector id: 1, status=SuspendedEVSE\n"
).encode()


def test_log_state_parsing():
    st = ChargerLogState()
    st.feed(LOG.decode().splitlines())
    assert st.current_limit == 1
    assert st.limiting_factor == "DLM"
    assert st.below_minimum is True
    assert st.limit_factors["ConfMax"] == 12 and st.limit_factors["10%OverloadProt"] is False
    assert relay_mode_name(st.relay_mode) == "1-phase (L1)"
    assert st.connector_status == "SuspendedEVSE"


def test_limiting_factor_ties_and_off():
    st = ChargerLogState()
    st.feed(["2026-10-22T10:00:00+00:00 charging:1 INFO max_current=12, DLM=12, ConfMax=12, OwnerMin=6, Bracket=16",
             "2026-10-22T10:00:01+00:00 core:119 INFO Charging EV was disconnected or requested stop charging, deactivated relays. CP"])
    assert st.limiting_factor == "ConfMax, DLM"
    assert st.below_minimum is False
    assert relay_mode_name(st.relay_mode) == "Off"


def _mock_device(aioclient_mock):
    aioclient_mock.get(f"{BASE}/status/energy-meter", json=[{"sampledValue": [
        {"measurand": "Current.Import", "phase": "L1", "value": "10.9"},
        {"measurand": "Power.Active.Import", "value": "2500"}]}])
    aioclient_mock.get(f"{BASE}/status/metervalue-sample", json={"sampledValue": [
        {"value": "12", "measurand": "Current.Offered", "unit": "A", "location": "Outlet"},
        {"value": "16", "measurand": "Current.Offered", "unit": "A", "location": "Inlet"}]})
    for p in ("/status/temperatures", "/config/firmware-version", "/config/device-id", "/config/unit-id",
              "/hal/cp-level-max", "/hal/cp-level-min", "/status/charging-state", "/hal/pp-level",
              "/netconf/network-interface", "/netconf/connection-status", "/status/sim-info", "/plc/device-status"):
        aioclient_mock.get(f"{BASE}{p}", json={})
    aioclient_mock.get(f"{BASE}/log/garoevse.log", content=LOG, status=206,
                       headers={"Content-Range": f"bytes 0-{len(LOG) - 1}/{len(LOG)}"})


async def _setup(hass, aioclient_mock, options=None):
    _mock_device(aioclient_mock)
    entry = MockConfigEntry(domain=DOMAIN, unique_id=HOST, options=options or {},
                            data={"host": HOST, "username": "u", "password": "p", "ignore_tls_errors": True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _state(hass, suffix):
    matches = [s for s in hass.states.async_all("sensor") if s.entity_id.endswith(suffix)]
    assert len(matches) == 1, (suffix, [s.entity_id for s in hass.states.async_all("sensor")])
    return matches[0]


async def test_sensors(hass: HomeAssistant, aioclient_mock):
    await _setup(hass, aioclient_mock)
    offered = _state(hass, "offered_current")
    assert offered.state == "12.0" and offered.attributes["inlet"] == 16.0
    assert _state(hass, "current_limit").state == "1"
    assert _state(hass, "current_limit").attributes["below_minimum"] is True
    assert _state(hass, "limiting_factor").state == "DLM"
    assert _state(hass, "relay_mode").state == "1-phase (L1)"
    assert _state(hass, "connector_status").state == "SuspendedEVSE"


async def test_log_sensors_removed_when_disabled(hass: HomeAssistant, aioclient_mock):
    entry = await _setup(hass, aioclient_mock)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"enable_log_sensors": False})
    await hass.async_block_till_done()
    assert not [s for s in hass.states.async_all("sensor") if s.entity_id.endswith("connector_status")]
    assert "password" not in entry.options


async def test_diagnostics_redacts(hass: HomeAssistant, aioclient_mock):
    from custom_components.garo_entity_charger_meter.diagnostics import async_get_config_entry_diagnostics
    entry = await _setup(hass, aioclient_mock)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["password"] == "**REDACTED**"
    assert diag["log"]["limiting_factor"] == "DLM"


async def test_backfill_from_rotated_log(hass: HomeAssistant, aioclient_mock):
    """Limit and status logged before the latest rotation are found in .1.gz."""
    import gzip
    from custom_components.garo_entity_charger_meter.logtail import LogFollower

    url = f"{BASE}/log/garoevse.log"
    current = (b"x" * 50 + b"\n"
               b"2026-10-22T13:00:00+00:00 charging:2080 INFO Best charge mode check: Trying to keep relay mode=mode_1ph_l1_n for time=75 s\n")
    rotated = gzip.compress(
        b"2026-10-22T10:20:54+00:00 status_handler:9 INFO Status changed, connector id: 1, status=Charging\n"
        b"2026-10-22T12:00:00+00:00 charging:1170 INFO max_current=11, DLM=11, ConfMax=12, OwnerMin=6\n"
        b"2026-10-22T12:25:17+00:00 charging:1170 INFO max_current=12, DLM=12, ConfMax=12, OwnerMin=6\n"
        b"2026-10-22T12:30:00+00:00 status_handler:9 INFO Status changed, connector id: 1, status=SuspendedEV\n")
    aioclient_mock.get(url, content=current, status=206,
                       headers={"Content-Range": f"bytes 0-{len(current) - 1}/{len(current)}"})
    aioclient_mock.get(f"{url}.1.gz", content=rotated)

    session = aioclient_mock.create_session(hass.loop)
    try:
        import aiohttp
        follower, state = LogFollower(url, aiohttp.BasicAuth("u", "p")), ChargerLogState()
        state.feed(await follower.poll(session))
        assert state.relay_mode == "mode_1ph_l1_n" and state.missing()
        await follower.read_backwards(session, state)
        assert state.current_limit == 12          # newest, not the older 11
        assert state.connector_status == "SuspendedEV"
        assert not state.missing()
    finally:
        await session.close()


def test_backfill_never_overwrites_newer_values():
    st = ChargerLogState()
    st.feed(["2026-10-22T12:00:00+00:00 status_handler:9 INFO Status changed, connector id: 1, status=Charging"])
    st.backfill(["2026-10-22T11:00:00+00:00 status_handler:9 INFO Status changed, connector id: 1, status=Available",
                 "2026-10-22T10:00:00+00:00 charging:1 INFO max_current=8, DLM=8, OwnerMin=6"])
    assert st.connector_status == "Charging"
    assert st.current_limit == 8
