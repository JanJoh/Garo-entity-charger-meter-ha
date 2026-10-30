"""Firmware updates pushed to the unit by GARO, as seen in its device log.

GARO's backend (OCPP) orders an update and the unit reports its progress:

    ocpp:57 INFO GaroCS-…: < [2,"…","SignedUpdateFirmware",{"requestId":9,"firmware":{"location":"https://…/garo-entity-3.0.12-4.10.3-imx-r5bf98996f.upd",…}}]
    ocpp:76 INFO GaroCS-…: > [2,"…","SignedFirmwareStatusNotification",{"status":"Downloading","requestId":9}]

The statuses go Downloading → Downloaded → SignatureVerified → Installing →
Installed. A charger waits with the install until its connector is free.
The version comes from the file name; the last x.y.z in it is the software
version (the first one, 3.0.12 above, is not).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

_ORDER_RE = re.compile(r'"(?:Signed)?UpdateFirmware",\s*\{.*?"location"\s*:\s*"([^"]+)"')
_STATUS_RE = re.compile(r'"(?:Signed)?FirmwareStatusNotification",\s*\{\s*"status"\s*:\s*"(\w+)"')
_VERSION_RE = re.compile(r"(?<![\d.])(\d+\.\d+\.\d+)(?![\d.])")
_REVISION_RE = re.compile(r"-r([0-9a-f]{6,})\b")

# Shown as the update's release summary.
STATUS_TEXT = {
    "DownloadScheduled": "Download scheduled",
    "Downloading": "Downloading",
    "DownloadPaused": "Download paused",
    "Downloaded": "Downloaded",
    "DownloadFailed": "Download failed",
    "SignatureVerified": "Downloaded and verified, waiting to install",
    "InvalidSignature": "Rejected: invalid signature",
    "InstallScheduled": "Install scheduled",
    "Installing": "Installing",
    "InstallRebooting": "Restarting to finish the install",
    "Installed": "Installed",
    "InstallationFailed": "Install failed",
    "InstallVerificationFailed": "Install failed verification",
}
INSTALLING = {"Installing", "InstallRebooting"}


def version_from_location(location: str) -> tuple[str | None, str | None, str]:
    """'https://…/garo-entity-3.0.12-4.10.3-imx-r5bf98996f.upd' -> ('4.10.3', '5bf98996f', file name)."""
    name = location.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    versions = _VERSION_RE.findall(name)
    revision = _REVISION_RE.search(name)
    return (versions[-1] if versions else None), (revision[1] if revision else None), name


@dataclass
class FirmwareState:
    """Latest firmware order and its progress."""

    version: str | None = None
    revision: str | None = None
    file: str | None = None
    ordered_at: datetime | None = None
    status: str | None = None
    status_at: datetime | None = None

    def feed_line(self, line: str, ts: datetime | None) -> bool:
        """Apply one log line (oldest first). Returns True if it was a firmware line."""
        if "Firmware" not in line:
            return False
        if (m := _ORDER_RE.search(line)) is not None:
            self.version, self.revision, self.file = version_from_location(m[1])
            self.ordered_at = ts
            self.status, self.status_at = None, None
            return True
        if (m := _STATUS_RE.search(line)) is not None:
            if m[1] == "Idle":
                return True  # answer to a status query, says nothing about the order
            self.status, self.status_at = m[1], ts
            return True
        return False

    def backfill_line(self, line: str, ts: datetime | None) -> None:
        """Apply one older line (newest first); stops at the newest order."""
        if self.ordered_at is not None or self.file is not None:
            return
        older = FirmwareState()
        if not older.feed_line(line, ts):
            return
        if older.file is not None:
            self.version, self.revision, self.file, self.ordered_at = (
                older.version, older.revision, older.file, older.ordered_at)
        elif older.status is not None and self.status is None:
            self.status, self.status_at = older.status, older.status_at

    @property
    def summary(self) -> str | None:
        if self.status is None:
            return "Ordered" if self.file else None
        return STATUS_TEXT.get(self.status, self.status)

    @property
    def installing(self) -> bool:
        return self.status in INSTALLING

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "revision": self.revision,
            "file": self.file,
            "ordered_at": self.ordered_at.isoformat() if self.ordered_at else None,
            "status": self.status,
            "status_at": self.status_at.isoformat() if self.status_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FirmwareState":
        def dt(value):
            try:
                return datetime.fromisoformat(value) if value else None
            except (TypeError, ValueError):
                return None
        return cls(
            version=data.get("version"),
            revision=data.get("revision"),
            file=data.get("file"),
            ordered_at=dt(data.get("ordered_at")),
            status=data.get("status"),
            status_at=dt(data.get("status_at")),
        )
