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
import zlib
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

import aiohttp

from .firmware import FirmwareState

_LOGGER = logging.getLogger(__name__)

LOG_PATH = "/log/garoevse.log"
# The charger logs ~1 MB/h, mostly HTTP access lines; 256 kB covers ~15 min,
# enough to pick up the current limit after a restart. Events older than that
# (relay mode, connector status) are restored by the entities instead.
INITIAL_TAIL_BYTES = 256 * 1024
MAX_READ_BYTES = 1024 * 1024
# One-off backward search at startup for values the tail did not contain.
BACKFILL_CHUNK_BYTES = 512 * 1024
BACKFILL_MAX_BYTES = 8 * 1024 * 1024
ROTATED_MAX_BYTES = 4 * 1024 * 1024  # compressed garoevse.log.1.gz is ~0.5 MB

_CONTENT_RANGE_RE = re.compile(r"bytes\s+(?:(\d+)-\d+|\*)/(\d+)")
_TS_RE = re.compile(r"^(\S+)\s")
_LIMIT_RE = re.compile(r"\bcharging:\d+\s+\w+\s+max_current=(-?\d+),\s*(.*)$")
_FACTOR_RE = re.compile(r"([A-Za-z0-9%]+)=(-?\d+|True|False)")
_RELAY_RE = re.compile(r"(?:Activate relays, mode=|Trying to keep relay mode=)(mode_\w+)")
_RELAY_OFF_RE = re.compile(r"deactivated relays")
_STATUS_RE = re.compile(r"Status changed, connector id: (\d+), status=(\w+)")
# The car drew >10 % more than offered for a few seconds; the charger pauses (OverloadProt).
_OVERLOAD_RE = re.compile(r"Temporary derating - Temporary derating started")

# Factors in the max_current line that are not upper limits.
NON_LIMIT_FACTORS = {"OwnerMin", "10%OverloadProt"}


def _parse_content_range(value: str | None) -> tuple[int | None, int | None]:
    """'bytes 100-199/1000' -> (100, 1000); 'bytes */1000' -> (None, 1000)."""
    m = _CONTENT_RANGE_RE.match(value or "")
    if not m:
        return None, None
    return (int(m[1]) if m[1] else None), int(m[2])


async def _read_up_to(resp: aiohttp.ClientResponse, limit: int) -> bytes:
    """Read the body until EOF or until more than `limit` bytes were received.

    resp.content.read(n) returns whatever is buffered (often 16 kB), not n bytes.
    """
    chunks, total = [], 0
    async for chunk in resp.content.iter_chunked(64 * 1024):
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            break
    return b"".join(chunks)


@dataclass
class LogFollower:
    """Incremental reader of a device log over HTTP Range requests."""

    url: str
    auth: aiohttp.BasicAuth
    offset: int | None = None  # next unread byte; None = re-tail on next poll
    tail_start: int | None = None  # where the latest (re)tail began; bytes before it are unread
    _partial: bytes = field(default=b"", repr=False)  # incomplete last line
    _head_fragment: bytes = field(default=b"", repr=False)  # end of the line cut by the tail start

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
                body = await _read_up_to(resp, MAX_READ_BYTES)
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
            self.tail_start = start
            self._head_fragment = body[: nl + 1] if nl >= 0 else body
            body = body[nl + 1:] if nl >= 0 else b""
            self._partial = b""

        data = self._partial + body
        last_nl = data.rfind(b"\n")
        if last_nl < 0:
            self._partial = data
            return []
        self._partial = data[last_nl + 1:]
        return data[: last_nl + 1].decode("utf-8", errors="replace").splitlines()

    async def read_backwards(self, session: aiohttp.ClientSession, state: "ChargerLogState") -> int:
        """Search the log before tail_start for values `state` is still missing.

        Reads BACKFILL_CHUNK_BYTES at a time towards the start of the file, newest
        first, and stops when nothing is missing or BACKFILL_MAX_BYTES were read.
        Only fills values that are unset, so newer values are never overwritten.
        Returns the number of bytes read.
        """
        if self.tail_start is None:
            return 0
        end, carry, read = self.tail_start, self._head_fragment, 0
        while end > 0 and read < BACKFILL_MAX_BYTES and state.missing():
            start = max(0, end - BACKFILL_CHUNK_BYTES)
            async with session.get(self.url, auth=self.auth, headers={"Range": f"bytes={start}-{end - 1}"}) as resp:
                if resp.status != 206:
                    _LOGGER.debug("Backfill read HTTP %s, stopping", resp.status)
                    break
                body = await resp.read()
            read += len(body)
            data = body + carry
            if start > 0:
                # The first line of this chunk starts in the previous one; keep it for the next round.
                nl = data.find(b"\n")
                carry, data = (data, b"") if nl < 0 else (data[: nl + 1], data[nl + 1:])
            else:
                carry = b""
            lines = data.decode("utf-8", errors="replace").splitlines()
            state.backfill(reversed(lines))
            end = start

        if end == 0 and state.missing() and read < BACKFILL_MAX_BYTES:
            # Current file exhausted (it was rotated recently): try the previous one.
            read += await self._read_rotated(session, state)
        return read

    async def _read_rotated(self, session: aiohttp.ClientSession, state: "ChargerLogState") -> int:
        async with session.get(f"{self.url}.1.gz", auth=self.auth) as resp:
            if resp.status != 200:
                _LOGGER.debug("Rotated log HTTP %s", resp.status)
                return 0
            body = await _read_up_to(resp, ROTATED_MAX_BYTES)
        if len(body) > ROTATED_MAX_BYTES:
            _LOGGER.debug("Rotated log larger than %d bytes, skipped", ROTATED_MAX_BYTES)
            return len(body)
        try:
            text = zlib.decompress(body, wbits=zlib.MAX_WBITS | 16).decode("utf-8", errors="replace")
        except zlib.error as err:
            _LOGGER.debug("Rotated log not gzip: %s", err)
            return len(body)
        state.backfill(reversed(text.splitlines()))
        return len(body)


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
    firmware: FirmwareState = field(default_factory=FirmwareState)
    overload_pauses: deque = field(default_factory=lambda: deque(maxlen=50))  # timestamps

    def missing(self) -> bool:
        return self.current_limit is None or self.relay_mode is None or self.connector_status is None

    def backfill(self, lines_newest_first) -> None:
        """Fill only unset values from older lines (given newest first)."""
        for line in lines_newest_first:
            if not self.missing():
                return
            self.firmware.backfill_line(line, _timestamp(line))
            older = ChargerLogState()
            older.feed([line])
            if self.current_limit is None and older.current_limit is not None:
                self.current_limit, self.limit_factors, self.limit_logged_at = (
                    older.current_limit, older.limit_factors, older.limit_logged_at)
            if self.relay_mode is None and older.relay_mode is not None:
                self.relay_mode, self.relay_logged_at = older.relay_mode, older.relay_logged_at
            if self.connector_status is None and older.connector_status is not None:
                self.connector_status, self.status_logged_at = older.connector_status, older.status_logged_at

    def feed(self, lines: list[str]) -> None:
        for line in lines:
            ts = _timestamp(line)
            if self.firmware.feed_line(line, ts):
                continue
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
            elif _OVERLOAD_RE.search(line) and ts is not None:
                self.overload_pauses.append(ts)

    @property
    def limiting_factor(self) -> str | None:
        """Name of the factor that sets the current limit, e.g. 'DLM' or 'ConfMax'.

        When the limit is below OwnerMin the charger pauses; the factor that
        dropped below the minimum is reported then, or "Overload protection"
        when the pause is because the car drew more than it was offered.
        """
        if self.current_limit is None or not self.limit_factors:
            return None
        if self.limit_factors.get("10%OverloadProt") is True and self.below_minimum:
            return "Overload protection"
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
