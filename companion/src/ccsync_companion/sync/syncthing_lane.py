"""Lane C (everything else, bidirectional) — supervises a locally-running
Syncthing instance via its REST API. This module does NOT implement sync
itself and does NOT install/launch Syncthing (per SPEC.md: "supervises a
local Syncthing... Do not auto-install Syncthing" and this task's own
constraint not to install Syncthing system-wide).

Responsibilities:
  - find the REST API (default http://127.0.0.1:8384, overridable)
  - find the API key (config override, else Syncthing's own config.xml at
    the standard per-OS path, also overridable)
  - report connection/completion status into LaneStatus
  - verify the expected folder ID(s) for the project are configured AND
    shared (folder has >1 device — i.e. not just the local device)
  - if Syncthing is unreachable -> LaneStatus(state="error",
    last_error="Syncthing not running")
"""

from __future__ import annotations

import json
import logging
import os
import platform
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlencode

from .base import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_SYNCING,
    LaneAdapter,
    LaneStatus,
)

log = logging.getLogger("ccsync.sync.syncthing")

HttpGetFn = Callable[[str, str, float], Any]

# Syncthing's connection "type" values that mean "not a direct path". A
# relay-client connection runs over the PUBLIC relay pool -- typically
# 1-5 MB/s, shared and rate-limited -- which AUDIT_2 P3 names as the most
# likely literal explanation of the ~60 mb/s ceiling this project exists to
# beat. Everything else (tcp-client/tcp-server/quic-client/quic-server) is
# a direct connection.
RELAY_CONNECTION_PREFIX = "relay"
RELAYED_DETAIL = "relayed, slow path"


def summarize_connections(payload: Any) -> dict[str, Any]:
    """Reduce /rest/system/connections to {"devices": {id: type},
    "relayed": [ids], "direct": [ids]} over CONNECTED devices only.

    Disconnected entries carry a stale/blank type and must not be counted
    as relayed -- "offline" and "relayed" are different problems with
    different fixes. Never raises."""
    devices: dict[str, str] = {}
    relayed: list[str] = []
    direct: list[str] = []
    conns = payload.get("connections") if isinstance(payload, dict) else None
    if not isinstance(conns, dict):
        return {"devices": devices, "relayed": relayed, "direct": direct}
    for device_id, entry in conns.items():
        if not isinstance(entry, dict) or not entry.get("connected"):
            continue
        conn_type = str(entry.get("type", "") or "")
        devices[str(device_id)] = conn_type
        if conn_type.lower().startswith(RELAY_CONNECTION_PREFIX):
            relayed.append(str(device_id))
        elif conn_type:
            direct.append(str(device_id))
    return {"devices": devices, "relayed": relayed, "direct": direct}


def ccsync_config_xml_path() -> Path:
    """config.xml inside the Syncthing home our own bootstrap installers run
    Syncthing with (windows_bootstrap.ps1: %LOCALAPPDATA%\\ccsync\\
    syncthing-config, macos_bootstrap.sh: ~/.local/ccsync/syncthing-config).
    """
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(base) / "ccsync" / "syncthing-config" / "config.xml"
    return Path.home() / ".local" / "ccsync" / "syncthing-config" / "config.xml"


def _stock_config_xml_path() -> Path:
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(base) / "Syncthing" / "config.xml"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Syncthing" / "config.xml"
    # Linux isn't a SPEC.md target platform, but a reasonable fallback costs nothing.
    xdg_config = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(xdg_config) / "syncthing" / "config.xml"


def default_config_xml_path() -> Path:
    """Where to read the API key from when the config doesn't override it.

    The ccsync-managed home wins when its config.xml exists -- that's the
    instance our installers actually start, and the stock location may hold
    a stale config.xml from some earlier hand-run `syncthing` whose key
    would 403 against the running instance. The stock per-OS path is only
    used for hand-rolled setups; with neither present we still return the
    managed path so the lane's "no API key (checked ...)" error points at
    the location a ccsync install is supposed to have."""
    managed = ccsync_config_xml_path()
    if managed.exists():
        return managed
    stock = _stock_config_xml_path()
    if stock.exists():
        return stock
    return managed


def read_api_key_from_config(path: Path) -> Optional[str]:
    """Parse Syncthing's config.xml for <gui><apikey>. Returns None on any
    failure (missing file, malformed XML, no apikey element) — never raises.
    """
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError):
        return None
    root = tree.getroot()
    gui = root.find("gui")
    if gui is None:
        return None
    apikey_el = gui.find("apikey")
    if apikey_el is None or not (apikey_el.text or "").strip():
        return None
    return apikey_el.text.strip()


def default_http_get(url: str, api_key: str, timeout: float) -> Any:
    headers = {"X-API-Key": api_key} if api_key else {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8")) if data else {}


class SyncthingLane(LaneAdapter):
    name = "lane_c_syncthing"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8384",
        api_key: str = "",
        expected_folder_ids: Optional[list[str]] = None,
        config_xml_path: Optional[Path] = None,
        timeout: float = 5.0,
        poll_interval: float = 15.0,
        http_get: Optional[HttpGetFn] = None,
        expected_folder_ids_fn: Optional[Callable[[], list[str]]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._configured_api_key = api_key
        self.expected_folder_ids = expected_folder_ids or []
        # Managed mode learns its folders from the dashboard SELECTION, which
        # the sequencer owns -- the static `syncthing_folder_ids` config key
        # is written as a literal [] by every installer and populated by
        # nothing, so check_once() used to iterate an empty list and report
        # idle/queued=0/last_sync=now forever while lane C was paused,
        # un-ignored or hours behind (AUDIT_2 L-6/UX-3). Supply
        # `expected_folder_ids_fn` (e.g. Sequencer.expected_folder_slugs) and
        # it is evaluated fresh on every poll.
        self.expected_folder_ids_fn = expected_folder_ids_fn
        self.config_xml_path = config_xml_path or default_config_xml_path()
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._http_get = http_get or default_http_get

        self._status = LaneStatus(name=self.name)
        # Last /rest/system/connections summary (AUDIT_2 C-6). Public via
        # connection_path_summary() so the reporter payload -- owned
        # elsewhere -- can send it to the dashboard without re-polling.
        self._connection_summary: dict[str, Any] = {}
        self._lock = threading.Lock()
        # One event per thread generation -- see RcloneLane.__init__ for why
        # a single re-cleared event could not be right for both start() and
        # a stop() whose join times out (AUDIT_2 L-2).
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _resolve_api_key(self) -> str:
        if self._configured_api_key:
            return self._configured_api_key
        return read_api_key_from_config(self.config_xml_path) or ""

    def _get(self, path: str) -> Any:
        api_key = self._resolve_api_key()
        return self._http_get(f"{self.base_url}{path}", api_key, self.timeout)

    def _set_status(self, status: LaneStatus) -> None:
        with self._lock:
            self._status = status

    def _effective_folder_ids(self) -> list[str]:
        """The folder set this poll should judge the lane against."""
        if self.expected_folder_ids_fn is not None:
            try:
                return [str(fid) for fid in (self.expected_folder_ids_fn() or [])]
            except Exception:
                log.debug("expected_folder_ids_fn failed; falling back to the static list")
        return list(self.expected_folder_ids)

    def connection_path_summary(self) -> dict[str, Any]:
        """Last-seen per-device connection types, e.g.
        {"devices": {"ABC...": "relay-client"}, "relayed": [...], "direct": [...]}.

        Public on purpose: the reporter payload (another module's concern)
        needs this to make a relayed editor distinguishable from a merely
        slow one on the fleet strip (AUDIT_2 C-6)."""
        with self._lock:
            return dict(self._connection_summary)

    def _refresh_connection_summary(self) -> dict[str, Any]:
        """Poll connections; never fails the lane over it (an older
        Syncthing, or one mid-restart, is not a lane C error)."""
        try:
            summary = summarize_connections(self._get("/rest/system/connections"))
        except Exception:
            log.debug("connections check failed", exc_info=True)
            return {}
        with self._lock:
            self._connection_summary = summary
        return summary

    @staticmethod
    def _path_detail(summary: dict[str, Any]) -> str:
        relayed = summary.get("relayed") or []
        if not relayed:
            return ""
        return f"{RELAYED_DETAIL} ({len(relayed)} device(s) via relay)"

    @staticmethod
    def _with_path_detail(detail: str, path_detail: str) -> str:
        if not path_detail:
            return detail
        return f"{detail}; {path_detail}" if detail else path_detail

    def check_once(self) -> LaneStatus:
        """Single synchronous status check. Never raises."""
        api_key = self._resolve_api_key()
        if not api_key:
            status = LaneStatus(
                name=self.name,
                state=STATE_ERROR,
                last_error=f"no Syncthing API key (checked {self.config_xml_path})",
            )
            self._set_status(status)
            return status

        try:
            self._get("/rest/system/ping")
        except Exception:
            status = LaneStatus(name=self.name, state=STATE_ERROR, last_error="Syncthing not running")
            self._set_status(status)
            return status

        # Path diagnostics BEFORE the folder verdict, so every branch below
        # can carry "relayed, slow path" (AUDIT_2 C-6). A relayed lane C and
        # a slow lane C look identical without this.
        path_detail = self._path_detail(self._refresh_connection_summary())

        expected = self._effective_folder_ids()
        if not expected:
            # NOTHING was checked, so nothing may be claimed. Reporting
            # "idle, last synced just now" here is what kept every editor's
            # lane C dot green while lane C did nothing at all (AUDIT_2
            # L-6/UX-3) -- carry the previous last_sync through untouched.
            status = LaneStatus(
                name=self.name,
                state=STATE_IDLE,
                queued=0,
                last_sync=self.status().last_sync,
                detail=self._with_path_detail("no project folders to check yet", path_detail),
            )
            self._set_status(status)
            return status

        missing_folders: list[str] = []
        paused_folders: list[str] = []
        try:
            config = self._get("/rest/config")
            folders = config.get("folders", []) if isinstance(config, dict) else []
            by_id = {f.get("id"): f for f in folders}
            for fid in expected:
                folder = by_id.get(fid)
                if folder is None:
                    missing_folders.append(f"{fid} (not configured)")
                    continue
                devices = folder.get("devices", []) or []
                if len(devices) <= 1:
                    missing_folders.append(f"{fid} (not shared with any device)")
                    continue
                if folder.get("paused"):
                    paused_folders.append(fid)
        except Exception as exc:
            status = LaneStatus(
                name=self.name, state=STATE_ERROR, last_error=f"failed to read Syncthing config: {exc}"
            )
            self._set_status(status)
            return status

        if missing_folders:
            status = LaneStatus(
                name=self.name,
                state=STATE_ERROR,
                last_error="folder(s) not configured/shared: " + ", ".join(missing_folders),
            )
            self._set_status(status)
            return status

        queued = 0
        errored: list[str] = []
        for fid in expected:
            try:
                # urlencode, not an f-string: folder IDs are dashboard
                # project slugs, and a "/", "?" or "#" in one silently
                # addressed a different endpoint (AUDIT_3 L-10).
                db_status = self._get(f"/rest/db/status?{urlencode({'folder': fid})}") or {}
                queued += int(db_status.get("needTotalItems", 0) or 0)
                # A folder in "error" state (the classic being "folder marker
                # missing" after a failed repath) syncs NOTHING, and reading
                # only needTotalItems reports that as a serene 0.
                state = str(db_status.get("state", "") or "")
                errors = int(db_status.get("errors", 0) or 0)
                if state == "error" or errors > 0:
                    detail = db_status.get("stateChanged") or state or f"{errors} error(s)"
                    errored.append(f"{fid} ({detail})")
            except Exception:
                log.debug("db/status check failed for folder %s", fid)

        if errored:
            status = LaneStatus(
                name=self.name,
                state=STATE_ERROR,
                queued=queued,
                last_error="folder(s) in error: " + ", ".join(errored),
                detail=path_detail,
            )
        elif queued > 0:
            status = LaneStatus(
                name=self.name, state=STATE_SYNCING, queued=queued, detail=path_detail,
            )
        elif len(paused_folders) == len(expected):
            # Every folder paused: the sequencer pauses all but the current
            # project by design, so only ALL-paused is a real stop.
            status = LaneStatus(
                name=self.name,
                state=STATE_PAUSED,
                queued=0,
                last_sync=self.status().last_sync,
                detail=self._with_path_detail(
                    f"{len(paused_folders)} folder(s) paused", path_detail
                ),
            )
        else:
            status = LaneStatus(
                name=self.name, state=STATE_IDLE, queued=0,
                last_sync=datetime.now(timezone.utc), detail=path_detail,
            )
        self._set_status(status)
        return status

    # -- LaneAdapter ---------------------------------------------------
    def start(self) -> None:
        if (
            self._thread is not None
            and self._thread.is_alive()
            and not self._stop_event.is_set()
        ):
            # Genuinely running -> idempotent per LaneAdapter's contract.
            return
        # Same generation-event scheme as RcloneLane.start(): retire the old
        # event (a no-op when stop() already set it) and hand the new thread
        # its own, so a stale thread can never be re-armed AND a stop() whose
        # join timed out can never leave the lane permanently dead
        # (AUDIT_2 L-2).
        self._stop_event.set()
        stop_event = threading.Event()
        self._stop_event = stop_event
        self._thread = threading.Thread(
            target=self._poll_loop, args=(stop_event,),
            name="ccsync-syncthing-poll", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            # Bounded join -- see RcloneLane.stop() for why this can't wait
            # indefinitely (an in-flight REST call could stall).
            self._thread.join(timeout=5)

    def status(self) -> LaneStatus:
        with self._lock:
            return LaneStatus(**vars(self._status))

    def run_once(self) -> LaneStatus:
        return self.check_once()

    def _poll_loop(self, stop_event: Optional[threading.Event] = None) -> None:
        # This generation's own event -- never self._stop_event, which by
        # then may belong to a newer one.
        stop_event = stop_event if stop_event is not None else self._stop_event
        while not stop_event.is_set():
            try:
                self.check_once()
            except Exception:
                log.exception("%s: poll cycle failed", self.name)
            if stop_event.wait(self.poll_interval):
                break
