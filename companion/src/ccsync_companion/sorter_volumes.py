"""This computer's drives, reported to the Footage Sorter's ledger.

Companion half of footage-sorter docs/LEDGER-BROWSER-DESIGN.md, "The
companion", item 1. `sorter_cards` reports the camera CARDS in the readers; this
reports every VOLUME (card readers and fixed drives, the laptop's D:) so the
dashboard's ledger knows what is plugged in where, can show "New drives" and
the watchlist's visibility, and can queue a `ledger-scan` for a tracked drive
the moment it appears.

  POST {dashboard_url}/sorter/agent/volumes   {machine, volumes: [...], digest}

Each volume is {serial, label, fs, size, free, driveType, system, removable,
drive}. The serial is the identity (`vol:<serial>` in the ledger): drive letters
move, serials do not. `system` flags the drive the OS lives on.

WHEN IT POSTS (and why each rule):

  * **On a structural change** (a drive plugged or pulled, relabelled,
    reformatted), within `CHANGE_GAP_SECONDS` of the last post: a drive that
    chatters on a loose USB port must not become a post per second.
  * **Every five minutes**, changed or not: the server's "last seen" is only
    as fresh as this, and a lost post must cost five minutes at most.
  * **On a real change of free space**, at most once a minute: a copy running
    changes `free` every second; that is a number the Drives view wants to
    follow, not a post per tick. Real = at least 1 GiB or 1 % of the volume.

The free space is NOT in the change digest for the same reason; it rides every
post that goes out for another reason.

A volume being copied from (`sorter_cards.busy_roots`) is not touched, the card
rule: it is reported as last seen.

A 404 or 503 is a site without a sorter: back off ten minutes, say nothing above
DEBUG. The answer (`{scan: [...]}`, the scans the ledger queued as a result) is
for the log only: the dashboard queues the jobs itself, so a lost answer only
delays.
"""
from __future__ import annotations

import hashlib
import json
import logging
import platform
import threading
import time
from typing import Any, Callable, Optional

from . import config as config_mod
from . import sorter_cards

log = logging.getLogger("ccsync.sortervolumes")

AGENT_PATH = "/sorter/agent/volumes"
SCAN_SECONDS = 10.0            # how often the loop looks at the drives
RESEND_SECONDS = 300.0         # every 5 minutes, changed or not
CHANGE_GAP_SECONDS = 10.0      # a structural change posts at most this often
FREE_DEBOUNCE_SECONDS = 60.0   # a free-space change posts at most this often
FREE_STEP_BYTES = 1024 ** 3    # ...and only when it moved by this much...
FREE_STEP_FRACTION = 0.01      # ...or this fraction of the volume, whichever is larger
NO_SORTER_BACKOFF_SECONDS = 600.0
REFUSED_BACKOFF_SECONDS = 300.0
POST_TIMEOUT_SECONDS = 30.0


def enabled(cfg: dict[str, Any]) -> bool:
    """`sorter_ledger_enabled`, default on. Tolerates a hand-edited string."""
    raw = (cfg or {}).get("sorter_ledger_enabled", True)
    if isinstance(raw, str):
        return raw.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(raw)


# VIRTUAL DRIVES are not drives. Google Drive for desktop mounts a "drive" (labelled "Google Drive",
# FAT32, a made-up 4 TB, and the SAME serial on every machine), OneDrive/Dropbox/iCloud do the same
# with folders: their files are the cloud's, a scan of one is a scan of somebody's account, and a
# constant serial would make every machine's copy "the same volume" in the ledger.
VIRTUAL_LABELS = ("google drive", "googledrive", "my drive", "onedrive", "dropbox", "icloud", "box drive",
                  "proton drive", "nextcloud", "pcloud", "mega", "sync.com")
VIRTUAL_FS = ("fuse", "webdav", "vboxsf", "virtiofs", "9p", "cdfs", "udf", "afs", "nfs", "cifs", "smbfs")
VIRTUAL_SERIALS = frozenset({"19831116"})       # Google Drive for desktop, every machine, seen on razer 2026-11-09
NO_SERIALS = frozenset({"", "00000000", "FFFFFFFF"})
FAT32_FAKE_BYTES = 2 * 1024 ** 4                # FAT32 volumes this big are a driver's fiction, not a disk


def is_virtual(vol: dict[str, Any]) -> bool:
    """Should this volume be left out of the report? A volume with no real serial (0 / blank), a
    known virtual serial, a cloud-sync label, a network or pseudo file system, or a FAT32 'disk' of
    2 TiB or more."""
    serial = str(vol.get("serial") or "").strip().upper()
    if serial in NO_SERIALS or serial in VIRTUAL_SERIALS:
        return True
    label = str(vol.get("label") or "").strip().lower()
    if any(label == v or label.startswith(v + " ") or label.startswith(v + "(") or label.startswith(v + "-")
           for v in VIRTUAL_LABELS):
        return True
    fs = str(vol.get("fs") or "").strip().lower()
    if fs in VIRTUAL_FS:
        return True
    size = int(vol.get("capacity") or vol.get("size") or 0)
    return fs == "fat32" and size >= FAT32_FAKE_BYTES


def to_wire(vol: dict[str, Any]) -> dict[str, Any]:
    """A `sorter_cards.list_volumes` entry -> the report's volume object. Nothing path-like but
    the drive letter goes up: the server needs identity, size and where it is plugged in."""
    removable = bool(vol.get("removable"))
    return {
        "serial": str(vol.get("serial") or "").upper(),
        "label": str(vol.get("label") or ""),
        "fs": str(vol.get("fs") or ""),
        "size": int(vol.get("capacity") or 0),
        "free": int(vol.get("free") or 0),
        "driveType": str(vol.get("drive_type") or ("removable" if removable else "fixed")),
        "system": bool(vol.get("system")),
        "removable": removable,
        "drive": str(vol.get("drive") or ""),
    }


def structure_digest(volumes: list[dict[str, Any]]) -> str:
    """Hash of everything but the free space: what makes a post worth sending at once."""
    parts = sorted([v["serial"], v["label"], v["fs"], v["size"], v["driveType"], v["system"], v["drive"]]
                   for v in volumes)
    return hashlib.sha1(json.dumps(parts).encode("utf-8")).hexdigest()


def free_moved(volumes: list[dict[str, Any]], last_free: dict[str, int]) -> bool:
    """Has any volume's free space moved by a real amount since it was last reported?"""
    for v in volumes:
        before = last_free.get(v["serial"])
        if before is None:
            continue
        step = max(FREE_STEP_BYTES, int(v["size"] * FREE_STEP_FRACTION))
        if abs(int(v["free"]) - int(before)) >= step:
            return True
    return False


class VolumeReporter:
    """The background loop that reports this computer's volumes. Every seam is a constructor
    parameter (HTTP call, volumes, clock, identity), so the suite needs no drives and no
    dashboard, like SorterCards."""

    def __init__(
        self,
        cfg: dict[str, Any],
        request_fn: Optional[Callable[..., tuple[int, Any]]] = None,
        identity_token_fn: Optional[Callable[[], Optional[str]]] = None,
        volumes_fn: Optional[Callable[..., list[dict[str, Any]]]] = None,
        clock: Callable[[], float] = time.monotonic,
        machine_name: str = "",
    ) -> None:
        self.cfg = cfg if cfg is not None else {}
        self._request = request_fn
        self._identity_token_fn = identity_token_fn
        self._volumes = volumes_fn or sorter_cards.list_volumes
        self._clock = clock
        self._machine_name = machine_name
        self.scan_seconds = config_mod.coerce_numeric(
            self.cfg, "sorter_ledger_volume_seconds", SCAN_SECONDS)
        self._last_struct: Optional[str] = None
        self._last_sent: Optional[float] = None
        self._last_free: dict[str, int] = {}
        self._known: dict[str, dict[str, Any]] = {}        # serial -> last wire entry seen
        self._backoff_until = 0.0
        self.last_status: Optional[int] = None
        self.last_answer: Any = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- config ----------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return enabled(self.cfg)

    @property
    def _dashboard_url(self) -> str:
        return str(self.cfg.get("dashboard_url", "") or "").strip().rstrip("/")

    @property
    def _token(self) -> str:
        return str(self.cfg.get("dashboard_token", "") or "").strip()

    @property
    def machine(self) -> str:
        return self._machine_name or platform.node()

    def _headers(self) -> dict[str, str]:
        identity = ""
        if self._identity_token_fn is not None:
            try:
                identity = str(self._identity_token_fn() or "")
            except Exception:                                 # noqa: BLE001
                log.debug("sorter volumes: identity_token_fn failed", exc_info=True)
        return {"Content-Type": "application/json",
                "X-CCSync-Token": self._token,
                "X-CCSync-Identity": identity}

    # -- the loop --------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None or not self.enabled:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ccsync-sorter-volumes", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:                                 # noqa: BLE001
                log.exception("sorter volumes: the tick failed")
            self._stop.wait(max(1.0, float(self.scan_seconds)))

    def current_volumes(self) -> list[dict[str, Any]]:
        """Look at the drives -> wire volumes. A volume being copied from is not touched: it is
        reported as it was last seen."""
        busy = sorter_cards.busy_roots()
        found = [to_wire(v) for v in self._volumes("all", busy) if not is_virtual(v)]
        present = {v["serial"] for v in found}
        known = {**self._known, **{v["serial"]: v for v in found}}
        for serial in sorted(sorter_cards.busy_serials() - present):
            if serial in known:
                found.append(known[serial])
        found = [v for v in found if v["serial"]]
        self._known = {v["serial"]: v for v in found}
        found.sort(key=lambda v: (v["drive"], v["serial"]))
        return found

    def due(self, volumes: list[dict[str, Any]], now: float) -> str:
        """Why a post should go out now, or "" for not now."""
        struct = structure_digest(volumes)
        if self._last_struct is None or self._last_sent is None:
            return "first"
        since = now - self._last_sent
        if struct != self._last_struct:
            return "change" if since >= CHANGE_GAP_SECONDS else ""
        if since >= RESEND_SECONDS:
            return "resend"
        if since >= FREE_DEBOUNCE_SECONDS and free_moved(volumes, self._last_free):
            return "free"
        return ""

    def tick(self) -> Optional[int]:
        """One pass: look, and post when it is time. -> the HTTP status of the post, or None
        when nothing was sent."""
        if not self.enabled or not self._dashboard_url or not self._token:
            return None
        now = self._clock()
        if now < self._backoff_until:
            return None
        volumes = self.current_volumes()
        if not self.due(volumes, now):
            return None
        return self._post(volumes, now)

    def _post(self, volumes: list[dict[str, Any]], now: float) -> Optional[int]:
        request = self._request
        if request is None:
            from .broll_ingest import default_request
            request = default_request
        struct = structure_digest(volumes)
        body = {"machine": self.machine, "volumes": volumes, "digest": struct}
        try:
            status, parsed = request("POST", f"{self._dashboard_url}{AGENT_PATH}",
                                     body, self._headers(), POST_TIMEOUT_SECONDS)
        except Exception as exc:                              # noqa: BLE001
            log.debug("sorter volumes: could not reach the dashboard (%s)", exc)
            self._backoff_until = now + 30.0
            return None
        self.last_status = int(status)
        if status in (404, 503):
            log.debug("sorter volumes: the dashboard has no sorter ledger (HTTP %s)", status)
            self._backoff_until = now + NO_SORTER_BACKOFF_SECONDS
            return int(status)
        if status in (401, 403):
            log.warning("sorter volumes: the dashboard refused this computer's volume report (HTTP %s)", status)
            self._backoff_until = now + REFUSED_BACKOFF_SECONDS
            return int(status)
        if status != 200:
            log.debug("sorter volumes: the volume report answered HTTP %s", status)
            self._backoff_until = now + 60.0
            return int(status)
        self._last_struct, self._last_sent = struct, now
        self._last_free = {v["serial"]: int(v["free"]) for v in volumes}
        self.last_answer = parsed
        scans = parsed.get("scan") if isinstance(parsed, dict) else None
        if scans:
            log.info("sorter volumes: the ledger queued %d scan(s) for this computer's drives", len(scans))
        return 200
