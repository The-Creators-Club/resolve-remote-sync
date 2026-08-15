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
from typing import Any, Callable, Iterator, Optional
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

# rclone's default --inplace=false writes "<name>.<token>.partial" (express:
# "<name>.<token>.exp.partial") next to the destination and renames on
# completion, so a lane A killed mid-transfer orphans one -- and lane A never
# deletes. On the NAS side those orphans were indexed and fanned out over lane
# C to every ticked editor; on THIS side the same suffix must be ignored so a
# partial that lands here (or one lane B leaves behind) is never offered back
# up. Same two forms as the .ccsync-tmp pair below, for the same reason: the
# extension patterns match by EXTENSION and match neither (KNOWN_BUGS B12).
# Kept byte-identical to server/common.PARTIAL_IGNORE_LINES and dashboard
# provision.PARTIAL_IGNORE_LINES -- server/tests/test_cross_component.py
# asserts that across all three builders.
PARTIAL_IGNORE_LINES = ["(?i)**/*.partial", "(?i)*.partial"]

# yt-dlp's in-flight files, B12's failure one lane over. The NAS-side ytdl
# worker downloads into the shared Projects tree (Youtube/), which is a
# sendreceive Syncthing root, so lane C carried every growing `.part` down to
# each editor with the project ticked -- and since the 2026-08-11 delete-
# protection retrofit set ignoreDelete=True on EDITOR folders too, the
# rename/delete the worker performs on completion never follows: what lands
# here is permanent until someone deletes it by hand (27 orphans, ~1.6 GB,
# three days, editor ruskin's machine 2026-08-13/14). rclone lane B has always
# excluded these (rclone_lane.build_filter_rules_down), so lane C was the last
# leak.
#
# This editor-side copy matters on its own: accept_folder() writes STIGNORE_
# LINES when it takes a newly offered folder, which happens before any
# dashboard provision cycle reaches that folder -- without these lines the new
# folder leaks in-flight files until the collector's pass overwrites it.
#
# `.part-FragN` needs its own pair: a fragment is "<file>.part-Frag84" and does
# NOT end in `.part`. Kept byte-identical to server/common.YTDL_IGNORE_LINES
# and dashboard provision.YTDL_IGNORE_LINES (server/tests/
# test_cross_component.py asserts it), and deliberately kept OUT of
# ASSET_STIGNORE_LINES below -- no ytdl worker writes into a shared asset
# folder, and that list must not drift from the other two components'.
YTDL_IGNORE_LINES = [
    "(?i)**/*.part", "(?i)*.part",
    "(?i)**/*.part-Frag*", "(?i)*.part-Frag*",
    "(?i)**/*.ytdl", "(?i)*.ytdl",
]

STIGNORE_LINES: list[str] = (
    [f"(?i)*{ext}" for ext in _VIDEO_EXTS]
    + PARTIAL_IGNORE_LINES
    + YTDL_IGNORE_LINES
    # The fixer copies to "<dest>.ccsync-tmp" then os.replace()s it into
    # place. The extension patterns above match by EXTENSION, so
    # "A001.braw.ccsync-tmp" matches none of them -- lane C would upload a
    # half-copied 12 GB BRAW to the NAS and fan it out to every other
    # editor if the process died mid-copy (AUDIT_2 CORE-H5).
    + ["(?i)**/*.ccsync-tmp", "(?i)*.ccsync-tmp"]
    + ["(?i)Proxy", "(?i)**/Proxy", "(?i)**/Proxy/**"]
)

# --------------------------------------------------------------------------
# Shared asset folders (added 2026-08-05)
# --------------------------------------------------------------------------
#
# One fleet-wide library, outside Projects/, that every editor gets without
# ticking anything -- see server/common.py's block for the full rationale.
# The LUT library is the first. Keep these three constants byte-identical to
# server/common.py and dashboard/provision.py (server/tests/
# test_cross_component.py asserts it).
LUTS_FOLDER_ID = "assets-luts"
LUTS_REL = "Assets/Luts"
STILLS_FOLDER_ID = "assets-stills"
STILLS_REL = "Assets/Stills"

SHARED_ASSET_FOLDERS = [
    (LUTS_FOLDER_ID, LUTS_REL, "Assets/Luts (LUT library)"),
    (STILLS_FOLDER_ID, STILLS_REL, "Assets/Stills (Resolve gallery)"),
]

SHARED_ASSET_FOLDER_IDS = frozenset(fid for fid, _rel, _label in SHARED_ASSET_FOLDERS)

ASSET_JUNK_IGNORE_LINES = [
    "(?i)**/.DS_Store", "(?i).DS_Store",
    "(?i)**/Thumbs.db", "(?i)Thumbs.db",
    "(?i)**/desktop.ini", "(?i)desktop.ini",
    "(?i)**/*.tmp", "(?i)*.tmp",
    "(?i)**/*.ccsync-tmp", "(?i)*.ccsync-tmp",
]

# The .stignore for a shared asset folder. NOT STIGNORE_LINES: there is no
# lane A or B under this folder, so anything ignored here simply never syncs.
# OS junk (which would otherwise conflict-copy between editors) plus video as
# a blast-radius brake -- this folder reaches every machine in the fleet and
# has no tick to opt out of. See server/common.build_asset_stignore_lines.
ASSET_STIGNORE_LINES: list[str] = (
    [f"(?i)*{ext}" for ext in _VIDEO_EXTS]
    + PARTIAL_IGNORE_LINES
    + ASSET_JUNK_IGNORE_LINES
)


def missing_asset_ignore_lines(fetched: Any) -> list[str]:
    """missing_ignore_lines() for a shared asset folder. Same fail-closed
    shape handling: an unrecognised body (notably `{"ignore": null}`, which
    is what a folder with no .stignore at all reports) counts every line as
    missing."""
    lines = fetched.get("ignore") if isinstance(fetched, dict) else fetched
    if not isinstance(lines, (list, tuple)):
        return list(ASSET_STIGNORE_LINES)
    present = {str(line).strip() for line in lines}
    return [want for want in ASSET_STIGNORE_LINES if want not in present]


# Editor-side folders had NO versioning at all: the safety net existed only
# server-side (dashboard provision.py, server/setup_syncthing_folder.py), so
# any propagated delete -- from a NAS-side mistake, another editor, or any
# of the mass-delete paths in AUDIT_2 §1 -- removed the editor's only copy
# permanently. 30 days of staggered versions, cleaned hourly (AUDIT_2 DEL-6).
FOLDER_VERSIONING: dict = {
    "type": "staggered",
    "params": {"cleanInterval": "3600", "maxAge": "2592000"},
}


def missing_ignore_lines(fetched: Any) -> list[str]:
    """Which of STIGNORE_LINES are absent from a GET /rest/db/ignores body.

    An empty list means this folder's .stignore carries every load-bearing
    pattern -- the per-extension video lines, the .partial pair, yt-dlp's
    in-flight trio, the .ccsync-tmp pair and the Proxy patterns -- so lane C
    cannot offer anything lanes A/B already own.

    Fails CLOSED on every shape that is not a list of lines: Syncthing sends
    `{"ignore": null}` for a folder with no .stignore AT ALL, which is the
    single most dangerous state a `sendreceive` folder can be unpaused in
    and the one an unrecognised shape most likely means. Extra lines
    (a hand-edited .stignore, an older companion's leftovers) are fine --
    this asks "is everything we need present?", not "is this byte-identical
    to what we would write?", so a folder is never latched over cosmetics.
    """
    lines = fetched.get("ignore") if isinstance(fetched, dict) else fetched
    if not isinstance(lines, (list, tuple)):
        return list(STIGNORE_LINES)
    present = {str(line).strip() for line in lines}
    return [want for want in STIGNORE_LINES if want not in present]


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
        # Folder IDs whose accept_folder() got as far as writing the folder
        # config but NOT as far as a confirmed set_ignores. Such a folder
        # EXISTS in Syncthing's config (so it has left pending_folders() and
        # nothing will ever re-offer it) while carrying no .stignore at all
        # -- unpausing it makes lane C index and offer every .braw/.mov
        # original and the whole Proxy/ tree bidirectionally. The set_ignores
        # POST cannot be issued before the folder exists (the endpoint is
        # per-folder and 404s otherwise), so the half-accepted window is
        # tracked instead: see ignores_confirmed(), which the sequencer's
        # leak-recovery unpause sweeps consult.
        self._ignores_unconfirmed: set[str] = set()

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

        SYNC-8 (2026-08-14): syncthing_api_key ships as "" (config.py /
        config.example.toml), so on every real editor the fallback path runs
        -- and building the candidate LIST means an ET.parse of up to two
        whole config.xml files. _request is called once per REST call, and
        the callers are hot: _wait_for_folder_sync polls folder_status every
        5 s for up to a 600 s turn, lane C polls ~3+2N endpoints every 15 s.
        That was order 150k config.xml parses a machine a day to re-learn a
        key that has not changed since boot. Yielding the key the instance
        last accepted FIRST and parsing only if it is refused leaves the
        multi-home fallback (default_api_key_paths) exactly as it was -- it
        still runs on the 401/403 that is its only trigger.
        """
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
        tried_any = False
        for api_key in self._api_key_attempts():
            tried_any = True
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
        if not tried_any:
            # No key anywhere: one unauthenticated attempt, exactly as the
            # `or [""]` fallback this replaced did (a GUI with auth off).
            return self._http_request(method, url, "", body, effective_timeout)
        assert last_auth_error is not None
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

    def get_folders(self) -> Any:
        """GET /rest/config/folders -- every folder's config in ONE request.

        What the sequencer's between-passes unpause sweep reads before it
        writes (SYNC-7, 2026-08-14): asking per folder would only trade N
        config PATCHes for N GETs; this trades them for one. A read, so the
        short timeout."""
        return self._request("GET", "/rest/config/folders")

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

    def ensure_ignore_delete(self, folder_id: str, folder: Optional[dict] = None) -> bool:
        """PATCH ignoreDelete=true onto a folder that lacks it.

        Deletes are near-always mistakes in an asset/audio tree; a folder
        with ignoreDelete does not apply a delete another device made, so an
        editor's accidental single-file delete never removes the NAS or
        another editor's copy. Returns True when a PATCH was issued. Pass
        `folder` to reuse a config the caller already fetched. See
        docs/delete-protection-ignoredelete.md for the fleet-wide policy this
        assumes (real deletes need an explicit prune).
        """
        if folder is None:
            folder = self.get_folder(folder_id) or {}
        if (folder or {}).get("ignoreDelete") is True:
            return False
        log.info("syncthing: folder %s had no ignoreDelete -- adding it", folder_id)
        self._write_request("PATCH", self._folder_path(folder_id), {"ignoreDelete": True})
        return True

    # -- pending/accept -----------------------------------------------------
    def pending_folders(self) -> Any:
        return self._request("GET", "/rest/cluster/pending/folders")

    def accept_folder(
        self,
        folder_id: str,
        label: str,
        local_path: str,
        offered_by_device_id: str,
        ignore_lines: Optional[list[str]] = None,
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
        lose the file outright (AUDIT_2 DEL-6).

        "Left paused" is only half the guarantee, though: the folder config
        is necessarily POSTed FIRST (set_ignores addresses an existing
        folder), so a failed set_ignores leaves a folder that exists,
        carries no ignores, and has left pending_folders() -- nothing will
        ever offer it again, so the "it stays paused" promise has to survive
        past this call. It does, via ignores_confirmed(): the id is marked
        unconfirmed BEFORE the config write and only cleared by a set_ignores
        that actually returned.

        `ignore_lines` defaults to the project list; a shared asset folder
        passes ASSET_STIGNORE_LINES instead. It is a parameter rather than a
        lookup on folder_id so that the "no folder is ever created before its
        ignores are decided" property stays visible at the call site."""
        self._ignores_unconfirmed.add(str(folder_id))
        lines = list(STIGNORE_LINES if ignore_lines is None else ignore_lines)
        folder_config = {
            "id": folder_id,
            "label": label,
            "path": local_path,
            "type": "sendreceive",
            "paused": True,
            "fsWatcherEnabled": True,
            "ignorePerms": False,
            "versioning": dict(FOLDER_VERSIONING),
            # delete-protection (2026-08-11, docs/delete-protection-ignoredelete.md):
            # this device never APPLIES a delete another device made, so one
            # editor's accidental single-file delete cannot remove the NAS's
            # or another editor's copy. Set at creation for the same reason
            # versioning is -- a folder that pulls and then receives a delete
            # before the first ensure_ignore_delete() turn is already
            # unprotected. Kept byte-identical to server/
            # setup_syncthing_folder.py and dashboard/provision.py's two
            # builders (server/tests/test_cross_component.py asserts it).
            "ignoreDelete": True,
            "devices": [{"deviceID": offered_by_device_id, "introducedBy": ""}],
        }
        result = self._write_request("POST", "/rest/config/folders", folder_config)
        self.set_ignores(folder_id, lines)
        self.set_folder_paused(folder_id, False)
        return result

    def remove_folder(self, folder_id: str) -> Any:
        """DELETE the folder from the local Syncthing config. Files on disk
        are untouched -- Syncthing simply stops tracking them, which is
        exactly what "Remove this project from this machine" needs before
        the local copy is deleted (a still-configured folder would go into
        the folder-marker-missing error state instead)."""
        return self._write_request("DELETE", self._folder_path(folder_id))

    def get_ignores(self, folder_id: str) -> Any:
        """GET /rest/db/ignores?folder=<id> -- what this folder's .stignore
        actually contains right now.

        {"ignore": ["(?i)*.braw", ...], "expanded": [...]}, with `ignore`
        null for a folder that has none at all.

        The read side of set_ignores, and the only way to answer "is this
        folder actually filtered?" across a restart: ignores_confirmed()
        below is in-memory only, so it says nothing at all about a folder
        half-accepted by the PREVIOUS run -- which is exactly the folder the
        sequencer's startup leak-recovery sweep is about to unpause. A GET,
        so the short read timeout, not config_write_timeout."""
        return self._request("GET", self._query("/rest/db/ignores", {"folder": folder_id}))

    def set_ignores(self, folder_id: str, lines: list[str]) -> Any:
        result = self._write_request(
            "POST", self._query("/rest/db/ignores", {"folder": folder_id}), {"ignore": lines}
        )
        # Only a call that actually RETURNED clears the half-accepted latch
        # -- a timed-out config write is exactly the case this exists for.
        self._ignores_unconfirmed.discard(str(folder_id))
        return result

    def note_ignores_confirmed(self, folder_id: str) -> None:
        """Clear the half-accepted latch for a folder whose .stignore has been
        READ and found complete.

        SYNC-6 (2026-08-14): the latch was cleared only by a set_ignores that
        returned, which was enough while the sequencer re-asserted
        unconditionally every turn. Now that it reads first and writes only
        when a line is actually missing, a folder whose ignores DID land --
        from a set_ignores whose config write exceeded config_write_timeout
        after Syncthing had already applied it, the exact case the latch
        exists for -- would otherwise stay latched for the life of the
        process and be excluded from every leak-recovery unpause sweep. A GET
        that proves the file is complete is stronger evidence than a POST
        that returned."""
        self._ignores_unconfirmed.discard(str(folder_id))

    def ignores_confirmed(self, folder_id: str) -> bool:
        """False only while this process knows a folder's ignores are NOT in
        place: accept_folder() wrote the folder config and the set_ignores
        that followed never returned. True for every other folder, including
        ones this instance has never touched -- absence of evidence about a
        long-accepted folder is not evidence of a missing .stignore, and the
        sequencer re-asserts the ignores once per turn anyway."""
        return str(folder_id) not in self._ignores_unconfirmed

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
