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
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from .syncthing_lane import default_config_xml_path, read_api_key_from_config

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
    + ["(?i)Proxy", "(?i)**/Proxy", "(?i)**/Proxy/**"]
)


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
    ) -> None:
        self.base_url = syncthing_url.rstrip("/")
        self._configured_api_key = api_key
        self._http_request = http_request or globals()["http_request"]
        self.config_xml_path = config_xml_path or default_config_xml_path()
        self.timeout = timeout

    def _resolve_api_key(self) -> str:
        if self._configured_api_key:
            return self._configured_api_key
        return read_api_key_from_config(self.config_xml_path) or ""

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        api_key = self._resolve_api_key()
        url = f"{self.base_url}{path}"
        return self._http_request(method, url, api_key, body, self.timeout)

    # -- config -----------------------------------------------------
    def get_config(self) -> Any:
        return self._request("GET", "/rest/config")

    def set_folder_paused(self, folder_id: str, paused: bool) -> Any:
        return self._request("PATCH", f"/rest/config/folders/{folder_id}", {"paused": paused})

    def set_folder_path(self, folder_id: str, path: str, label: Optional[str] = None) -> Any:
        """Re-point a folder at a new local path (server-side project moves
        -- see sync/repath.py). Same PATCH shape as set_folder_paused."""
        body: dict = {"path": path}
        if label is not None:
            body["label"] = label
        return self._request("PATCH", f"/rest/config/folders/{folder_id}", body)

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
        never-swallow-errors-itself contract."""
        folder_config = {
            "id": folder_id,
            "label": label,
            "path": local_path,
            "type": "sendreceive",
            "paused": True,
            "fsWatcherEnabled": True,
            "ignorePerms": False,
            "devices": [{"deviceID": offered_by_device_id, "introducedBy": ""}],
        }
        result = self._request("POST", "/rest/config/folders", folder_config)
        self.set_ignores(folder_id, STIGNORE_LINES)
        self.set_folder_paused(folder_id, False)
        return result

    def set_ignores(self, folder_id: str, lines: list[str]) -> Any:
        return self._request("POST", f"/rest/db/ignores?folder={folder_id}", {"ignore": lines})

    # -- status -----------------------------------------------------
    def folder_status(self, folder_id: str) -> Any:
        return self._request("GET", f"/rest/db/status?folder={folder_id}")
