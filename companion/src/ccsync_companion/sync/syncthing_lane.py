"""Lane C (everything else, bidirectional) — supervises a locally-running
Syncthing instance via its REST API. This module does NOT implement sync
itself and does NOT INSTALL Syncthing (per SPEC.md: "supervises a local
Syncthing... Do not auto-install Syncthing" and this task's own constraint
not to install Syncthing system-wide).

It does now RE-LAUNCH one that has died, which is a different thing and was
added for SYNC-17 (2026-08-18): an editor's Syncthing died with his Windows
session and nothing on the machine was ever going to start it again, because
the autostart entry that starts it fires at logon only. The install is still
the installer's; only the lifetime is ours, and only through the launcher the
installer registered. See sync/syncthing_supervisor.py -- this poll is where
it is driven from, since it is the only thread that knows whether
127.0.0.1:8384 answered.

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
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional
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

# How long this lane may go on believing its own device id (comp-lane-c-3,
# 2026-08-21). One loopback GET per interval; see _get_my_device_id.
DEVICE_ID_REFRESH_SECONDS = 300.0


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


def default_api_key_paths() -> list[Path]:
    """Every config.xml a live 127.0.0.1:8384 instance's key might be in:
    the ccsync-managed home first, then the stock per-OS home.

    Static preference between the two homes has now bitten in BOTH
    directions: a stale stock config 403'ing against the managed instance
    (the original default_config_xml_path fix), and -- on owen_laptop,
    2026-07-26 -- a preserved managed home 403'ing against a veteran stock
    instance, which silenced every sequencer write (no ignores, no folder
    policy) while lane C reported a misleading error. The only reliable
    arbiter of "which key is right" is the running instance itself, so
    callers try each candidate against it in order (see _get/_request)."""
    paths = [ccsync_config_xml_path(), _stock_config_xml_path()]
    unique: list[Path] = []
    for p in paths:
        if p not in unique:
            unique.append(p)
    return unique


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
        supervisor: Optional[Any] = None,
        unfiltered_folders_fn: Optional[Callable[[], list[str]]] = None,
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
        # SYNC-5 (resilience sweep 2026-08-28): the slugs the sequencer is
        # deliberately keeping paused because their .stignore never landed
        # (Sequencer.unconfirmed_slugs). One paused folder out of five never
        # reached the PAUSED branch below -- only ALL-paused does -- so the
        # lane published idle/queued=0/last_sync=now while that project
        # synced nothing, indefinitely. Optional and duck-typed, like the
        # supervisor: a lane built without one behaves exactly as before.
        self.unfiltered_folders_fn = unfiltered_folders_fn
        # SYNC-17 (2026-08-18): this poll is the only thread in the companion
        # that knows whether 127.0.0.1:8384 answered, so it is where the
        # supervisor is driven from (sync/syncthing_supervisor.py). Optional,
        # and duck-typed rather than imported for a type: a lane built without
        # one behaves exactly as it did before, which is what every existing
        # test of this file assumes.
        self.supervisor = supervisor
        # An EXPLICIT config_xml_path scopes key discovery to that one file
        # (tests, power users); only the default wiring fans out over every
        # known home -- see default_api_key_paths for why.
        self.api_key_paths: list[Path] = (
            [config_xml_path] if config_xml_path else default_api_key_paths()
        )
        self.config_xml_path = config_xml_path or default_config_xml_path()
        # The key the running instance last accepted -- tried first so steady
        # state costs no extra requests.
        self._active_api_key = ""
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._http_get = http_get or default_http_get

        self._status = LaneStatus(name=self.name)
        # This instance's own device ID (cached; it never changes) -- needed
        # to tell OUTGOING need (what remote devices still lack from us)
        # apart from our own downloads. See check_once's sending branch.
        self._my_device_id: Optional[str] = None
        # Monotonic stamp of the last successful myID read (comp-lane-c-3).
        self._my_device_id_at = 0.0
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

    def _api_key_candidates(self) -> list[str]:
        """Ordered, deduplicated keys to try: the config override alone when
        set, else the last-accepted key first, then each home's config.xml."""
        if self._configured_api_key:
            return [self._configured_api_key]
        candidates: list[str] = []
        if self._active_api_key:
            candidates.append(self._active_api_key)
        for path in self.api_key_paths:
            key = read_api_key_from_config(path)
            if key and key not in candidates:
                candidates.append(key)
        return candidates

    def _api_key_attempts(self) -> Iterator[str]:
        """The same order as _api_key_candidates, LAZILY.

        SYNC-8 (2026-08-14): the twin of SyncthingAdmin._api_key_attempts,
        and the hotter of the two -- _poll_loop makes roughly 3 + 2N requests
        every 15 s, each of which rebuilt the candidate list by ET.parse-ing
        up to two whole config.xml files to re-learn a key that has not
        changed since boot. The key the instance last accepted is tried
        first; the multi-home fallback below is unchanged and still runs on
        the 401/403 that is its only trigger (see default_api_key_paths for
        why it exists at all)."""
        if self._configured_api_key:
            yield self._configured_api_key
            return
        tried: set[str] = set()
        if self._active_api_key:
            tried.add(self._active_api_key)
            yield self._active_api_key
        for key in self._api_key_candidates():
            if key and key not in tried:
                tried.add(key)
                yield key

    def _has_any_api_key(self) -> bool:
        """Is there any key at all to try? A key the running instance has
        already accepted answers it without touching the disk (SYNC-8)."""
        return bool(
            self._configured_api_key or self._active_api_key or self._api_key_candidates()
        )

    def _get(self, path: str) -> Any:
        """GET with per-home API-key fallback: a 401/403 means "running, but
        that key belongs to a different Syncthing home", so the next
        candidate is tried; any other failure propagates unchanged."""
        url = f"{self.base_url}{path}"
        last_auth_error: Optional[Exception] = None
        tried_any = False
        for api_key in self._api_key_attempts():
            tried_any = True
            try:
                result = self._http_get(url, api_key, self.timeout)
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    last_auth_error = exc
                    continue
                raise
            if api_key:
                self._active_api_key = api_key
            return result
        if not tried_any:
            # No key anywhere: one unauthenticated attempt, exactly as the
            # `or [""]` fallback this replaced did.
            return self._http_get(url, "", self.timeout)
        assert last_auth_error is not None
        raise last_auth_error

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

    def unfiltered_folders(self) -> list[str]:
        """Selected projects whose Syncthing folder is parked without its
        filter list (SYNC-5, 2026-08-28). Never raises: a diagnostic that
        could fail the poll would take the whole lane report with it."""
        if self.unfiltered_folders_fn is None:
            return []
        try:
            return [str(s) for s in (self.unfiltered_folders_fn() or []) if s]
        except Exception:
            log.debug("unfiltered_folders_fn failed", exc_info=True)
            return []

    @staticmethod
    def unfiltered_sentence(slugs: list[str]) -> str:
        """The one sentence an editor and an admin both read for SYNC-5."""
        shown = ", ".join(slugs[:5])
        if len(slugs) > 5:
            shown += f", +{len(slugs) - 5} more"
        return (
            f"{len(slugs)} project(s) are not sharing yet - waiting for their "
            f"filter list: {shown}"
        )

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

    def _get_my_device_id(self) -> str:
        """This instance's own device id, re-read on a slow cadence.

        It was cached for the process ("it never changes"), which is true of
        a Syncthing home that survives -- and the supervisor restarting a
        home whose key/cert are gone mints a NEW identity, which is the one
        event that changes myID under a running companion, and one this
        companion causes itself (comp-lane-c-3, 2026-08-21). The outgoing-need
        calculation then compared remote devices against an id that no longer
        exists. A failed re-read keeps the known id: Syncthing being down for
        a poll is not evidence of a new identity."""
        now = time.monotonic()
        if self._my_device_id and (now - self._my_device_id_at) < DEVICE_ID_REFRESH_SECONDS:
            return self._my_device_id
        try:
            status = self._get("/rest/system/status")
            my_id = str((status or {}).get("myID") or "")
        except Exception:
            my_id = ""
        if my_id:
            if self._my_device_id and my_id != self._my_device_id:
                log.warning(
                    "%s: this machine's Syncthing device id changed (%s -> %s) -- its "
                    "config was regenerated", self.name, self._my_device_id, my_id)
            self._my_device_id = my_id
            self._my_device_id_at = now
        return my_id or (self._my_device_id or "")

    @staticmethod
    def _human_size(n: int) -> str:
        size = float(n or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return "?"

    def api_reachable(self) -> bool:
        """Does 127.0.0.1:8384 answer AT ALL, right now?

        The supervisor's post-launch probe (SYNC-17). Deliberately weaker
        than check_once: a 401/403 is TRUE here, because the question is
        "did the process come back", not "can we drive it" -- restarting a
        Syncthing that answers with the wrong key would be an infinite loop
        of the wrong fix. Never raises."""
        try:
            self._get("/rest/system/ping")
            return True
        except urllib.error.HTTPError as exc:
            return exc.code in (401, 403)
        except Exception:
            return False

    def _note_supervisor(self, reachable: bool) -> None:
        """Hand this poll's verdict to the supervisor. Never raises: a lane
        must not go dark because the thing that restarts Syncthing threw."""
        if self.supervisor is None:
            return
        try:
            self.supervisor.tick(bool(reachable))
        except Exception:
            log.exception("%s: syncthing supervisor tick failed", self.name)

    def _unreachable_status(self) -> LaneStatus:
        """The lane verdict for "127.0.0.1:8384 did not answer".

        SYNC-17 (2026-08-18). ERROR, always -- lane C carries the audio,
        graphics, subtitles and .drp files, and with the engine dead it is
        carrying none of them. The message comes from the supervisor when
        there is one, because only it knows whether a restart is under way,
        has failed three times, or is being deliberately withheld; "Syncthing
        not running" is the unsupervised fallback and the string this lane
        published for a year, so the tray's classifier still recognises it.
        """
        self._note_supervisor(False)
        detail = ""
        if self.supervisor is not None:
            try:
                detail = str(self.supervisor.lane_error() or "")
            except Exception:
                log.exception("%s: supervisor lane_error() failed", self.name)
        return LaneStatus(
            name=self.name,
            state=STATE_ERROR,
            last_error=detail or "Syncthing not running",
        )

    def check_once(self) -> LaneStatus:
        """Single synchronous status check. Never raises."""
        if not self._has_any_api_key():
            # The supervisor is told, and told UNREACHABLE (comp-lane-c-4,
            # 2026-08-21). No key anywhere means no config.xml anywhere,
            # which is the state a wiped or never-generated Syncthing home is
            # in -- and `syncthing serve --home=...` (what the shim runs)
            # regenerates the home and brings the API back. This branch
            # returned before saying anything at all, so the one thing that
            # could repair it was never asked, and an incident opened before
            # the file vanished could never be closed either.
            self._note_supervisor(False)
            status = LaneStatus(
                name=self.name,
                state=STATE_ERROR,
                last_error=f"no Syncthing API key (checked {self.config_xml_path})",
            )
            self._set_status(status)
            return status

        try:
            self._get("/rest/system/ping")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                # Running, but owned by a different home than any key we
                # hold -- "not running" here sent the 2026-07-26 laptop
                # debugging in exactly the wrong direction. It ANSWERED, so
                # the supervisor is told the process is alive: restarting a
                # Syncthing that is up and merely holding a different key
                # would be the wrong fix applied forever.
                self._note_supervisor(True)
                checked = ", ".join(str(p) for p in self.api_key_paths)
                status = LaneStatus(
                    name=self.name,
                    state=STATE_ERROR,
                    last_error=f"Syncthing is running but rejected every known API key (checked {checked})",
                )
            else:
                status = self._unreachable_status()
            self._set_status(status)
            return status
        except Exception:
            status = self._unreachable_status()
            self._set_status(status)
            return status
        self._note_supervisor(True)

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
            # A folder the server has OFFERED but the sequencer hasn't
            # accepted yet is a freshly ticked project spinning up, not a
            # broken lane -- C:error flashed on every tick for the minute
            # the accept took (2026-07-26).
            pending_ids: set = set()
            try:
                pending = self._get("/rest/cluster/pending/folders") or {}
                if isinstance(pending, dict):
                    pending_ids = set(pending.keys())
            except Exception:
                log.debug("pending folders check failed", exc_info=True)
            missing_ids = {m.split(" ")[0] for m in missing_folders}
            if missing_ids and missing_ids <= pending_ids:
                status = LaneStatus(
                    name=self.name, state=STATE_SYNCING, queued=0,
                    detail=self._with_path_detail(
                        f"setting up {len(missing_ids)} newly ticked project(s)",
                        path_detail,
                    ),
                )
                self._set_status(status)
                return status
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
                    # The actual error TEXT, not just the state name: "folder
                    # marker missing" is the tell for "project deleted
                    # locally while still ticked", which the tray turns into
                    # an instruction instead of a generic PROBLEM line.
                    err_text = str(db_status.get("error") or "")
                    detail = err_text or db_status.get("stateChanged") or state or f"{errors} error(s)"
                    errored.append(f"{fid} ({detail})")
            except Exception:
                log.debug("db/status check failed for folder %s", fid)

        # OUTGOING need: what the folder's remote devices (the server) still
        # lack from this machine. A 400 MB mp3 uploading via lane C showed
        # "up to date" in the tray and idle on the dashboard the whole time
        # (2026-07-26) -- needTotalItems only counts OUR downloads.
        outgoing_items = 0
        outgoing_bytes = 0
        my_id = self._get_my_device_id()
        if my_id:
            for fid in expected:
                folder = by_id.get(fid)
                if folder is None:
                    continue
                for dev in folder.get("devices", []) or []:
                    did = str(dev.get("deviceID") or "")
                    if not did or did == my_id:
                        continue
                    try:
                        comp = self._get(
                            f"/rest/db/completion?{urlencode({'folder': fid, 'device': did})}"
                        ) or {}
                        outgoing_items += int(comp.get("needItems", 0) or 0)
                        outgoing_bytes += int(comp.get("needBytes", 0) or 0)
                    except Exception:
                        log.debug("outgoing completion check failed for %s/%s", fid, did)

        # SYNC-5: a folder parked for missing ignores is a STOP for that
        # project, not a slow pass, and it outranks every green branch below
        # (it used to reach none of them). It is reported alongside a real
        # folder error rather than instead of it: an admin needs both.
        unfiltered = self.unfiltered_folders()
        if errored or unfiltered:
            reasons = []
            if errored:
                reasons.append("folder(s) in error: " + ", ".join(errored))
            if unfiltered:
                reasons.append(self.unfiltered_sentence(unfiltered))
            status = LaneStatus(
                name=self.name,
                state=STATE_ERROR,
                queued=queued,
                last_error=" | ".join(reasons),
                detail=path_detail,
            )
        elif queued > 0:
            status = LaneStatus(
                name=self.name, state=STATE_SYNCING, queued=queued, detail=path_detail,
            )
        elif outgoing_items > 0:
            status = LaneStatus(
                name=self.name, state=STATE_SYNCING, queued=outgoing_items,
                detail=self._with_path_detail(
                    f"sending {outgoing_items} file(s) ({self._human_size(outgoing_bytes)}) to the server",
                    path_detail,
                ),
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
