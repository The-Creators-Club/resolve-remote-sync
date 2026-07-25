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

from .base import STATE_ERROR, STATE_IDLE, STATE_SYNCING, LaneAdapter, LaneStatus

log = logging.getLogger("ccsync.sync.syncthing")

HttpGetFn = Callable[[str, str, float], Any]


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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._configured_api_key = api_key
        self.expected_folder_ids = expected_folder_ids or []
        self.config_xml_path = config_xml_path or default_config_xml_path()
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._http_get = http_get or default_http_get

        self._status = LaneStatus(name=self.name)
        self._lock = threading.Lock()
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

        missing_folders: list[str] = []
        try:
            config = self._get("/rest/config")
            folders = config.get("folders", []) if isinstance(config, dict) else []
            by_id = {f.get("id"): f for f in folders}
            for fid in self.expected_folder_ids:
                folder = by_id.get(fid)
                if folder is None:
                    missing_folders.append(f"{fid} (not configured)")
                    continue
                devices = folder.get("devices", []) or []
                if len(devices) <= 1:
                    missing_folders.append(f"{fid} (not shared with any device)")
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
        for fid in self.expected_folder_ids:
            try:
                db_status = self._get(f"/rest/db/status?folder={fid}")
                queued += int((db_status or {}).get("needTotalItems", 0) or 0)
            except Exception:
                log.debug("db/status check failed for folder %s", fid)

        if queued > 0:
            status = LaneStatus(name=self.name, state=STATE_SYNCING, queued=queued)
        else:
            status = LaneStatus(
                name=self.name, state=STATE_IDLE, queued=0, last_sync=datetime.now(timezone.utc)
            )
        self._set_status(status)
        return status

    # -- LaneAdapter ---------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            # Idempotent per LaneAdapter's contract. Same shape as
            # RcloneLane.start(): spawning thread #2 while #1 is still
            # alive and then clearing _stop_event would un-stick #1's own
            # wait() and leak it forever (sign-out -> sign-in in quick
            # succession).
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, name="ccsync-syncthing-poll", daemon=True)
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

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.check_once()
            except Exception:
                log.exception("%s: poll cycle failed", self.name)
            if self._stop_event.wait(self.poll_interval):
                break
