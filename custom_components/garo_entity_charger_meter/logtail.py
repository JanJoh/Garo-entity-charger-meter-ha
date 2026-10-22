"""Follow the charger's /log/garoevse.log and extract charging decisions.

Several useful facts exist only in the device log, not in any REST endpoint:

    charging:1170 INFO max_current=10, DLM=10, FixCab=20, PP=0, ConfMax=12, SC=16, ... OwnerMin=6, Bracket=16, ...
    charging:2124 INFO Activate relays, mode=mode_1ph_l1_n
    charging:2080 INFO Best charge mode check: Trying to keep relay mode=mode_1ph_l1_n for time=75 s
    core:119 INFO Charging EV was disconnected or requested stop charging, deactivated relays. ...
    status_handler:... INFO Status changed, connector id: 1, status=SuspendedEV

LogFollower tails the file with HTTP Range requests: the first read takes the
last INITIAL_TAIL_BYTES, later reads fetch only what was appended since. When
the log is rotated the server answers 416 (offset past the new, smaller file)
and the follower starts over from the tail. ChargerLogState folds the lines
into the latest known values.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import aiohttp

_LOGGER = logging.getLogger(__name__)

LOG_PATH = "/log/garoevse.log"
# The charger logs ~1 MB/h, mostly HTTP access lines; 256 kB covers ~15 min,
# enough to pick up the current limit after a restart. Events older than that
# (relay mode, connector status) are restored by the entities instead.
INITIAL_TAIL_BYTES = 256 * 1024
MAX_READ_BYTES = 1024 * 1024

_CONTENT_RANGE_RE = re.compile(r"bytes\s+(?:(\d+)-\d+|\*)/(\d+)")
_TS_RE = re.compile(r"^(\S+)\s")
_LIMIT_RE = re.compile(r"\bcharging:\d+\s+\w+\s+max_current=(-?\d+),\s*(.*)$")
_FACTOR_RE = re.compile(r"([A-Za-z0-9%]+)=(-?\d+|True|False)")
_RELAY_RE = re.compile(r"(?:Activate relays, mode=|Trying to keep relay mode=)(mode_\w+)")
_RELAY_OFF_RE = re.compile(r"deactivated relays")
_STATUS_RE = re.compile(r"Status changed, connector id: (\d+), status=(\w+)")

# Factors in the max_current line that are not upper limits.
NON_LIMIT_FACTORS = {"OwnerMin", "10%OverloadProt"}


def _parse_content_range(value: str | None) -> tuple[int | None, int | None]:
    """'bytes 100-199/1000' -> (100, 1000); 'bytes */1000' -> (None, 1000)."""
    m = _CONTENT_RANGE_RE.match(value or "")
    if not m:
        return None, None
    return (int(m[1]) if m[1] else None), int(m[2])


@dataclass
class LogFollower:
    """Incremental reader of a device log over HTTP Range requests."""

    url: str
    auth: aiohttp.BasicAuth
    offset: int | None = None  # next unread byte; None = re-tail on next poll
    _partial: bytes = field(default=b"", repr=False)  # incomplete last line

    async def poll(self, session: aiohttp.ClientSession) -> list[str]:
        """Return complete lines appended since the previous poll."""
        range_header = (
            f"bytes=-{INITIAL_TAIL_BYTES}" if self.offset is None else f"bytes={self.offset}-"
        )
        async with session.get(self.url, auth=self.auth, headers={"Range": range_header}) as resp:
            start, total = _parse_content_range(resp.headers.get("Content-Range"))
            if resp.status == 416:
                if total is not None and self.offset is not None and total < self.offset:
                    _LOGGER.debug("Log rotated (size %s < offset %s)", total, self.offset)
                    self.offset, self._partial = None, b""
                return []
            if resp.status == 206:
                body = await resp.content.read(MAX_READ_BYTES + 1)
                start = start or 0
            elif resp.status == 200:
                full = await resp.read()
                if self.offset is not None and self.offset <= len(full):
                    start = self.offset
                else:
                    self.offset, self._partial = None, b""
                    start = max(0, len(full) - INITIAL_TAIL_BYTES)
                body = full[start:]
            else:
                _LOGGER.debug("Log fetch HTTP %s", resp.status)
                return []

        resync = self.offset is None
        if len(body) > MAX_READ_BYTES:
            start += len(body) - MAX_READ_BYTES
            body = body[-MAX_READ_BYTES:]
            resync = True
        self.offset = start + len(body)

        if resync:
            nl = body.find(b"\n")
            body = body[nl + 1:] if nl >= 0 else b""
            self._partial = b""

        data = self._partial + body
        last_nl = data.rfind(b"\n")
        if last_nl < 0:
            self._partial = data
            return []
        self._partial = data[last_nl + 1:]
        return data[: last_nl + 1].decode("utf-8", errors="replace").splitlines()


@dataclass
class ChargerLogState:
    """Latest values seen in the charger log."""

    current_limit: int | None = None
    limit_factors: dict[str, int | bool] = field(default_factory=dict)
    limit_logged_at: datetime | None = None
    relay_mode: str | None = None
    relay_logged_at: datetime | None = None
    connector_status: str | None = None
    status_logged_at: datetime | None = None

    def feed(self, lines: list[str]) -> None:
        for line in lines:
            ts = _timestamp(line)
            if (m := _LIMIT_RE.search(line)) is not None:
                factors: dict[str, int | bool] = {}
                for key, raw in _FACTOR_RE.findall(m[2]):
                    factors[key] = raw == "True" if raw in ("True", "False") else int(raw)
                self.current_limit = int(m[1])
                self.limit_factors = factors
                self.limit_logged_at = ts
            elif (m := _RELAY_RE.search(line)) is not None:
                self.relay_mode, self.relay_logged_at = m[1], ts
            elif _RELAY_OFF_RE.search(line):
                self.relay_mode, self.relay_logged_at = "off", ts
            elif (m := _STATUS_RE.search(line)) is not None:
                self.connector_status, self.status_logged_at = m[2], ts

    @property
    def limiting_factor(self) -> str | None:
        """Name of the factor that sets the current limit, e.g. 'DLM' or 'ConfMax'.

        When the limit is below OwnerMin the charger pauses; the factor that
        dropped below the minimum is reported then.
        """
        if self.current_limit is None or not self.limit_factors:
            return None
        limits = {
            k: v for k, v in self.limit_factors.items()
            if k not in NON_LIMIT_FACTORS and isinstance(v, int) and not isinstance(v, bool) and v > 0
        }
        if not limits:
            return None
        lowest = min(limits.values())
        names = sorted(k for k, v in limits.items() if v == lowest)
        return ", ".join(names)

    @property
    def below_minimum(self) -> bool | None:
        owner_min = self.limit_factors.get("OwnerMin")
        if self.current_limit is None or not isinstance(owner_min, int):
            return None
        return self.current_limit < owner_min


def _timestamp(line: str) -> datetime | None:
    m = _TS_RE.match(line)
    if not m:
        return None
    try:
        return datetime.fromisoformat(m[1])
    except ValueError:
        return None


RELAY_MODE_NAMES = {
    "mode_1ph_l1_n": "1-phase (L1)",
    "mode_1ph_l2_n": "1-phase (L2)",
    "mode_1ph_l3_n": "1-phase (L3)",
    "mode_3ph": "3-phase",
    "mode_3ph_n": "3-phase",
    "off": "Off",
}


def relay_mode_name(mode: str | None) -> str | None:
    if mode is None:
        return None
    return RELAY_MODE_NAMES.get(mode, mode.removeprefix("mode_"))
