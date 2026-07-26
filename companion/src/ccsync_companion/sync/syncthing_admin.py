"""Local Syncthing REST-API writer for Lane C's sequencer (sequencer.py).

Unlike sync/syncthing_lane.py (read-only status polling), this module
performs the writes the sequencer needs to make "sync one project at a
time" real on the wire: pause/unpause folders, accept dashboard-driven
pending folder offers, and set per-folder ignores so the editor-side
Syncthing folder never carries video/proxy files (those are Lane A/B's
job -- see STIGNORE_LINES below).

Verified against a real (local) Syncthing instance before writing this:
  - PATCH /rest/config/folders/<id> with {"paused": true|false} -> HTTP 200
    empty body, and it persists.
  - GET /rest/cluster/pending/folders -> {} when none, else
    {"<folder-id>": {"offeredBy": {"<DEVICE-ID>": {"time": ..., "label": ...}}}}.
  - PUT/POST /rest/config/folders/<id> accept folder config objects.
  - POST /rest/db/ignores?folder=<id> with {"ignore": [lines...]} sets ignores.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote, urlencode

from .syncthing_lane import (
    default_api_key_paths,
    default_config_xml_path,
    read_api_key_from_config,
)

log = logging.getLogger("ccsync.sync.syncthing_admin")

HttpRequestFn = Callable[..., Any]

# Editor-side Syncthing folders must exclude video + Proxy: Lane A carries
# video up, Lane B carries proxies down, so if Lane C (Syncthing) also
# carried them it would race/duplicate that traffic. One "(?i)*<ext>" line
# per video extension, plus Proxy dir patterns at any depth (both a bare
# "Proxy" match and the "**/Proxy/**" glob form, for parity with the
# rclone-side belt-and-suspenders pattern in rclone_lane.py).
_VIDEO_EXTS = [
    ".braw", ".mov", ".mp4", ".mxf", ".avi", ".mts", ".m2ts", ".mkv",
    ".r3d", ".crm", ".mpg", ".mpeg", ".wmv", ".webm", ".insv", ".360",
]

STIGNORE_LINES: list[str] = (
    [f"(?i)*{ext}" for ext in _VIDEO_EXTS]
    # The fixer copies to "<dest>.ccsync-tmp" then os.replace()s it into
    # place. The extension patterns above match by EXTENSION, so
    # "A001.braw.ccsync-tmp" matches none of them -- lane C would upload a
    # half-copied 12 GB BRAW to the NAS and fan it out to every other
    # editor if the process died mid-copy (AUDIT_2 CORE-H5).
    + ["(?i)**/*.ccsync-tmp", "(?i)*.ccsync-tmp"]
    + ["(?i)Proxy", "(?i)**/Proxy", "(?i)**/Proxy/**"]
)

# Editor-side folders had NO versioning at all: the safety net existed only
# server-side (dashboard provision.py, server/setup_syncthing_folder.py), so
# any propagated delete -- from a NAS-side mistake, another editor, or any
# of the mass-delete paths in AUDIT_2 §1 -- removed the editor's only copy
# permanently. 30 days of staggered versions, cleaned hourly (AUDIT_2 DEL-6).
FOLDER_VERSIONING: dict = {
    "type": "staggered",
    "params": {"cleanInterval": "3600", "maxAge": "2592000"},
}


def http_request(
    method: str, url: str, api_key: str, body: Optional[dict] = None, timeout: float = 5.0
) -> Any:
    headers = {"X-API-Key": api_key} if api_key else {}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp_data = resp.read()
    return json.loads(resp_data.decode("utf-8")) if resp_data else {}


class SyncthingAdmin:
    """Local Syncthing REST writes needed to drive "one project at a time"
    from the sequencer. Never raises out of accessor methods that the
    sequencer treats as fault-isolated -- callers (sequencer.py) are
    responsible for catching exceptions per SPEC's fault-isolation ethos;
    this class does not swallow errors itself so tests can assert on them
    directly and the sequencer can distinguish success from failure."""

    def __init__(
        self,
        syncthing_url: str = "http://127.0.0.1:8384",
        api_key: str = "",
        http_request: Optional[HttpRequestFn] = None,
        config_xml_path: Optional[Path] = None,
        timeout: float = 5.0,
        config_write_timeout: float = 30.0,
    ) -> None:
        self.base_url = syncthing_url.rstrip("/")
        self._configured_api_key = api_key
        self._http_request = http_request or globals()["http_request"]
        # Same key-discovery scoping as SyncthingLane: an explicit
        # config_xml_path is authoritative; the default wiring tries every
        # known home's key against the live instance (a preserved-but-stale
        # managed home 403'ing against a veteran stock instance silently
        # disabled every sequencer write on alex_laptop, 2026-07-26).
        self.api_key_paths: list[Path] = (
            [config_xml_path] if config_xml_path else default_api_key_paths()
        )
        self.config_xml_path = config_xml_path or default_config_xml_path()
        self._active_api_key = ""
        self.timeout = timeout
        # Syncthing COMMITS THE CONFIG AND RESTARTS THE FOLDER on a config
        # write, which on a rig with many folders routinely takes longer
        # than the 5 s read timeout. A timeout there left the sequencer's
        # pause sweep half-applied -- worst case every selected folder
        # paused and lane C fully stopped (AUDIT_2 L-11).
        self.config_write_timeout = config_write_timeout

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

    def _request(
        self, method: str, path: str, body: Optional[dict] = None, timeout: Optional[float] = None
    ) -> Any:
        """One request with per-home API-key fallback: 401/403 means the key
        belongs to a different Syncthing home than the running instance, so
        the next candidate is tried; every other failure propagates
        unchanged per this class's never-swallow contract."""
        url = f"{self.base_url}{path}"
        effective_timeout = self.timeout if timeout is None else timeout
        last_auth_error: Optional[Exception] = None
        for api_key in self._api_key_candidates() or [""]:
            try:
                result = self._http_request(method, url, api_key, body, effective_timeout)
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    last_auth_error = exc
                    continue
                raise
            if api_key:
                self._active_api_key = api_key
            return result
        assert last_auth_error is not None  # loop always runs at least once
        raise last_auth_error

    def _write_request(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        """A config-mutating request, on the longer write timeout."""
        return self._request(method, path, body, timeout=self.config_write_timeout)

    @staticmethod
    def _folder_path(folder_id: str) -> str:
        """/rest/config/folders/<id> with the id percent-encoded.

        Folder IDs are project slugs from the dashboard, not constants of
        this codebase: an id containing "/", "?" or "#" was interpolated raw
        and silently addressed a DIFFERENT REST endpoint -- e.g. a PATCH
        meant to pause one folder landing somewhere else entirely
        (AUDIT_3 L-10). safe="" so "/" is encoded too."""
        return f"/rest/config/folders/{quote(str(folder_id), safe='')}"

    @staticmethod
    def _query(path: str, params: dict[str, Any]) -> str:
        """`path?<properly encoded query>` -- same reasoning as
        _folder_path, for the endpoints that take the folder as a query
        parameter."""
        return f"{path}?{urlencode({k: str(v) for k, v in params.items()})}"

    # -- config -----------------------------------------------------
    def get_config(self) -> Any:
        return self._request("GET", "/rest/config")

    def get_folder(self, folder_id: str) -> Any:
        return self._request("GET", self._folder_path(folder_id))

    def set_folder_paused(self, folder_id: str, paused: bool) -> Any:
        return self._write_request(
            "PATCH", self._folder_path(folder_id), {"paused": paused}
        )

    def set_folder_path(self, folder_id: str, path: str, label: Optional[str] = None) -> Any:
        """Re-point a folder at a new local path (server-side project moves
        -- see sync/repath.py). Same PATCH shape as set_folder_paused."""
        body: dict = {"path": path}
        if label is not None:
            body["label"] = label
        return self._write_request("PATCH", self._folder_path(folder_id), body)

    def ensure_versioning(self, folder_id: str, folder: Optional[dict] = None) -> bool:
        """PATCH staggered versioning onto a folder that has none.

        Folders accepted by an older companion, by hand in the Syncthing
        GUI, or before DEL-6 was fixed carry no `versioning` key at all, and
        Syncthing's default is "no versions kept" -- so every propagated
        delete is permanent on the editor. Returns True when a PATCH was
        issued. Pass `folder` to reuse a config the caller already fetched.
        """
        if folder is None:
            folder = self.get_folder(folder_id) or {}
        existing = (folder or {}).get("versioning") or {}
        if isinstance(existing, dict) and (existing.get("type") or ""):
            return False
        log.info("syncthing: folder %s had no versioning -- adding staggered", folder_id)
        self._write_request(
            "PATCH", self._folder_path(folder_id), {"versioning": FOLDER_VERSIONING}
        )
        return True

    # -- pending/accept -----------------------------------------------------
    def pending_folders(self) -> Any:
        return self._request("GET", "/rest/cluster/pending/folders")

    def accept_folder(
        self, folder_id: str, label: str, local_path: str, offered_by_device_id: str
    ) -> Any:
        """Accept a pending Syncthing folder offer with the video/Proxy
        ignores already in place before it can pull anything.

        Created paused so there is no window between the folder existing
        and set_ignores() landing during which Syncthing could start
        pulling the video/Proxy content lanes A/B already own (a
        hand-provisioned or older server folder would otherwise duplicate
        that transfer). Only unpaused after set_ignores() succeeds; if it
        raises, the folder is left paused rather than silently syncing
        unfiltered, and the exception propagates per this class's
        never-swallow-errors-itself contract.

        Versioning is set at creation, not bolted on later: a folder that
        pulls and then deletes before the first ensure_versioning() would
        lose the file outright (AUDIT_2 DEL-6)."""
        folder_config = {
            "id": folder_id,
            "label": label,
            "path": local_path,
            "type": "sendreceive",
            "paused": True,
            "fsWatcherEnabled": True,
            "ignorePerms": False,
            "versioning": dict(FOLDER_VERSIONING),
            "devices": [{"deviceID": offered_by_device_id, "introducedBy": ""}],
        }
        result = self._write_request("POST", "/rest/config/folders", folder_config)
        self.set_ignores(folder_id, STIGNORE_LINES)
        self.set_folder_paused(folder_id, False)
        return result

    def set_ignores(self, folder_id: str, lines: list[str]) -> Any:
        return self._write_request(
            "POST", self._query("/rest/db/ignores", {"folder": folder_id}), {"ignore": lines}
        )

    # -- status -----------------------------------------------------
    def folder_status(self, folder_id: str) -> Any:
        return self._request("GET", self._query("/rest/db/status", {"folder": folder_id}))

    def system_status(self) -> Any:
        return self._request("GET", "/rest/system/status")

    def connections(self) -> Any:
        """GET /rest/system/connections -- the per-device transport.

        {"total": {...}, "connections": {"<DEVICE-ID>": {"connected": true,
        "type": "tcp-client"|"quic-client"|"relay-client", "address": ...}}}

        This is the ONLY signal that distinguishes a slow editor from a
        RELAYED one, and nothing in production read it before (AUDIT_2 P3/
        C-6). Devices are added with addresses ["dynamic"] and relays are
        left at their `true` default, so falling back to the public relay
        pool -- typically 1-5 MB/s, shared and rate-limited -- is silent."""
        return self._request("GET", "/rest/system/connections")

    def get_options(self) -> Any:
        return self._request("GET", "/rest/config/options")

    def set_options(self, options: dict) -> Any:
        """PATCH /rest/config/options. Config-write timeout: Syncthing
        commits and may restart on any options write."""
        return self._write_request("PATCH", "/rest/config/options", options)

    def ensure_max_folder_concurrency(self, value: int) -> bool:
        """Set maxFolderConcurrency if it isn't already `value`.

        This is what gives "one project at a time" I/O pacing WITHOUT the
        pause/unpause scheme's config churn, folder restarts, full rescans
        and 50-minute stalls (AUDIT_2 P4/C-1). Reads first so steady state
        costs one GET and zero config commits. Returns True when a write was
        issued."""
        if value <= 0:
            return False
        options = self.get_options() or {}
        try:
            current = int(options.get("maxFolderConcurrency", 0) or 0)
        except (TypeError, ValueError):
            current = -1
        if current == value:
            return False
        log.info(
            "syncthing: maxFolderConcurrency %s -> %d (pacing lane C without pausing folders)",
            current, value,
        )
        self.set_options({"maxFolderConcurrency": value})
        return True

    def completion(self, folder_id: str, device_id: str) -> Any:
        """What the REMOTE device still needs from us for this folder.

        folder_status()'s needTotalItems is the download side only, so a
        lane C turn could end -- and the folder then be paused -- with the
        editor's own outgoing files half-sent, stalling them until that
        folder's next turn up to N x rotation seconds later (AUDIT_2 P5).
        """
        return self._request(
            "GET",
            self._query("/rest/db/completion", {"folder": folder_id, "device": device_id}),
        )
