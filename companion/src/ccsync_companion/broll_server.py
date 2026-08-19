"""Loopback HTTP server for the b-roll library's "Send to Resolve" button.

Implements the "Companion API contract" section of broll/SPEC.md exactly:
  GET  /status
  POST /insert
plus OPTIONS preflight handling.

WHO MAY CALL IT (2026-08-17, COMMERCIAL_READINESS.md item 5 / C1). Until this
date the answer was "any page in the editor's browser": CORS was "*" with
Access-Control-Allow-Private-Network, and a loopback bind was mistaken for an
authorisation decision. It is not -- the browser is ON the machine, which is
the attacker's whole foothold, so an ad iframe could insert clips into the
timeline an editor was grading and spawn Explorer on their desktop. There are
now exactly two ways in, both spelled out in loopback_guard.py:

  * an **Origin** on this deployment's allow-list (the dashboard that serves
    the b-roll / music / ytdl pages, from `dashboard_url` and the cached site
    manifest) -- the browser's own unforgeable claim about which page is
    calling. Anything else gets 403 and no CORS headers at all;
  * the **X-CCSync-Loopback token** from ~/.ccsync/loopback-token, for
    callers that are not a browser and so have no Origin: the tray itself,
    the onboarding wizard, an operator with curl.

A request with no Origin still gets GETs -- opening /status in a tab is the
self-test all three web UIs tell editors to run, and a top-level navigation
sends no Origin -- but a state-changing POST needs one of the two above, plus
Content-Type: application/json and a loopback Host (DNS-rebinding defence).

Since port step 8 (2026-08-10) it also carries the MUSIC library's
"Send to Resolve" actions as a route group:
  GET  /music/status
  POST /music/send
  POST /music/reveal      (2026-08-14, MUSIC-6)
and since 2026-08-11 the YouTube downloader page's reveal-in-file-manager,
joined 2026-08-19 (CR-32) by the pull that makes a NAS-only original reachable:
  POST /ytdl/reveal
  POST /ytdl/fetch
and since 2026-08-14 (companion 0.8.0) the local download executor -- the
requester's own machine fetching its own YouTube clips instead of the NAS:
  GET  /ytdl/capabilities
  POST /ytdl/download
  GET  /ytdl/progress
and since 2026-08-18 the b-roll INGEST route group -- drag clips onto the
dashboard's b-roll page and this machine crunches them (docs/BROLL_INGEST_
PLAN.md §4.1):
  GET  /broll/ingest/capabilities
  POST /broll/ingest/pick
  POST /broll/ingest/prepare
  PUT  /broll/ingest/upload/{staging_id}/{local_id}
  GET  /broll/ingest/progress
  GET  /broll/ingest/thumb
  POST /broll/ingest/run
  POST /broll/ingest/control
and, since the same day, the MUSIC ingest group -- the same eight routes,
parameterised by kind, because the pipeline behind them is the same object
(docs/MUSIC_INGEST_PLAN.md §2):
  GET  /music/ingest/capabilities
  POST /music/ingest/pick
  POST /music/ingest/prepare
  PUT  /music/ingest/upload/{staging_id}/{local_id}
  GET  /music/ingest/progress
  GET  /music/ingest/thumb
  POST /music/ingest/run
  POST /music/ingest/control
That group brings the first PUT and the first non-JSON body this listener has
ever accepted, so it brings its own two rules with it (see do_PUT): the body
cap is the DECLARED size of that one file rather than MAX_BODY_BYTES, and
`application/octet-stream` is accepted on that route ALONE, and only with the
`X-CCSync-Ingest` header (or the loopback token) -- a custom header forces a
preflight, which is what keeps a hostile page from streaming bytes into
staging with a plain form POST.

They are here, on this listener, rather than on one of their own precisely
because this process already owns 8899 and a second server holding it breaks
the tray app (CLAUDE.md). Those halves' logic lives in music_server.py,
ytdl_server.py and ytdl_executor.py; only the dispatch below and the mount
maps in start() are shared, and the b-roll contract above is untouched by any
of them.

ABSORBED from the standalone b-roll companion (`broll/companion/`, package
`broll_companion`), retired 2026-08-10. The fleet was shipping two tray apps
to every editor whose only difference was this ~200-line server, and the
small one was the one nobody upgraded. Its server.py + paths.py + config.py
are merged here near-verbatim (the path-traversal rejection and the macOS
/Volumes probing are contract, not implementation detail); its
resolve_bridge.perform_insert moved into THIS package's resolve_bridge,
which was already a fork of the same file.

Stdlib http.server only -- no new dependency in the frozen bundle.

The one behaviour that is new: the "broll" share's mount no longer has to be
written into ~/.broll-companion.json by hand, because this process already
knows where the tree is (see default_broll_mount).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, unquote, urlparse

from . import broll_fetch
from . import broll_vlm_sidecar
from . import config as ccsync_config
from . import ffmpeg_tools
from . import ingest_kinds
from . import loopback_guard
from . import music_server
from . import music_worker
from . import resolve_bridge
from . import site as site_mod
from . import ytdl_executor
from . import ytdl_server

log = logging.getLogger("ccsync.broll")

HOST = "127.0.0.1"
PORT = 8899

# How long the /status probe waits for its child. Shorter than the music
# actions' 90 s (music_server.TIMEOUT) on purpose: /status is a yes/no the
# settings panel draws a dot from, and an editor staring at "checking..."
# learns nothing from the extra minute. The insert keeps the full 90 s -- an
# ImportMedia off a cold share is genuinely slow (MED-3, 2026-08-11).
STATUS_TIMEOUT = 20

# Nothing either route accepts is more than a few hundred bytes, and the
# Content-Length was taken on trust: a non-numeric one crashed the handler and
# an invented large one parked a daemon thread in an unbounded buffered read.
# The origin allow-list is newer than this cap (2026-08-17) and does not
# replace it: an ALLOWED page with a bug can still send a bad Content-Length
# (MED-10, 2026-08-11).
MAX_BODY_BYTES = 256 * 1024
_READ_CHUNK_BYTES = 64 * 1024

# -- b-roll ingest (docs/BROLL_INGEST_PLAN.md §4.1, 2026-08-18) --------------

# The route group's own prefix, and the ONE route that takes a body which is
# not JSON and not small.
INGEST_PREFIX = "/broll/ingest/"
MUSIC_INGEST_PREFIX = "/music/ingest/"
# Every ingest prefix this listener answers, longest-first is not needed (they
# do not nest) but ORDER IS: `_kind_for_path` returns the first match, and a
# route group added here without a kind in `ingest_kinds.KINDS` would dispatch
# to b-roll's orchestrator with a music page's body.
INGEST_PREFIXES = {
    INGEST_PREFIX: ingest_kinds.BROLL,
    MUSIC_INGEST_PREFIX: ingest_kinds.MUSIC,
}
_UPLOAD_PATH_RE = re.compile(
    r"^/(broll|music)/ingest/upload/([A-Za-z0-9_-]{1,64})/([A-Za-z0-9_.-]{1,80})$")

# The header that makes a dropped-file PUT possible at all. `application/
# octet-stream` is not on the CORS-safelisted list, so a cross-origin PUT
# already needs a preflight -- but a body-carrying request is exactly the
# shape browsers have historically let through in one form or another, and
# this listener has never accepted one. Requiring a custom header is a second,
# independent reason for the browser to ask permission first, and it is
# checked here as well as by the browser so a non-browser caller cannot skip
# it either (the loopback token is the alternative, for curl and the tray).
INGEST_HEADER = "X-CCSync-Ingest"

# How much more than the declared size a streamed upload may be before it is
# refused: browsers send exactly what they said they would, so this is slack
# for nothing in particular and a cap on a lying client. 1 % of a 40 GB
# original is 400 MB, hence the absolute floor beside it.
INGEST_UPLOAD_SLACK_PCT = 0.01
INGEST_UPLOAD_SLACK_FLOOR = 64 * 1024
_UPLOAD_CHUNK_BYTES = 1024 * 1024

# The native picker runs on the UI thread and an editor may take a while to
# find their card's folder. Long, but not unbounded: a dialog nobody ever
# answers must not hold a request thread for the life of the process.
PICK_TIMEOUT_SECONDS = 300

# What `run` is allowed to be asked for. Published in the capability answer so
# the page can render the choice without knowing this build's vocabulary.
INGEST_RUN_MODES = ("idle", "foreground")

# What may be dropped or picked. Shared by the picker's folder walk, the
# prepare route's per-item refusal and (as a filter) the page: three places
# that must agree, or a folder drop shows 400 clips and stages 380.
# BRAW/R3D/CRM are deliberately absent -- ffmpeg cannot decode them, so this
# machine could make neither a proxy nor a frame (proxy_scan.NEEDS_RESOLVE_EXTS
# says the same thing about the same formats).
INGEST_VIDEO_EXTS = frozenset({
    ".mp4", ".mov", ".m4v", ".mxf", ".mts", ".m2ts", ".avi", ".mkv", ".webm",
})

# The music container's per-file ceiling (`musicweb.config.
# MAX_INGEST_FILE_BYTES`, 512 MiB), enforced HERE as well as there because the
# PUT that streams a dropped track never reaches the server: an editor who
# drags a 2 GB session stem should be told by the machine that has the file,
# not by a 413 from a NAS half a continent away after the upload.
MUSIC_MAX_FILE_BYTES = 512 * 1024 * 1024

# The staging directory, inside the b-roll archive so it is on the same volume
# as everything it will produce (a rename, not a copy) and inside a tree the
# root guard already understands.
INGEST_DIR_NAME = ".ingest"

# Config file for the SHARE->MOUNT map, unchanged from the standalone
# companion: editors already have this file, the b-roll settings panel names
# this path, and an upgrade that silently stopped reading it would repoint
# every configured share at nothing.
#
# Functions rather than module constants because Path.home() would otherwise
# be captured at IMPORT time: the test suite isolates itself by redirecting
# HOME/USERPROFILE (see tests/conftest.py), and a constant computed before
# that redirection writes into the developer's real home directory.
CONFIG_NAME = ".broll-companion.json"
README_SNIPPET_NAME = ".broll-companion.README.txt"


def config_path() -> Path:
    return Path.home() / CONFIG_NAME


def readme_snippet_path() -> Path:
    return Path.home() / README_SNIPPET_NAME

DEFAULT_CONFIG: dict[str, Any] = {
    "server_url": "http://127.0.0.1:8000",
    "mounts": {},
}

# The one share this companion can place on its own: the b-roll archive syncs
# into the project tree like any other shared asset, so it is always
# <local_root>/Assets/B-roll Archive (P:\Assets\B-roll Archive on the fleet).
BROLL_SHARE = "broll"
BROLL_ARCHIVE_REL = ("Assets", "B-roll Archive")

README_SNIPPET = """B-roll Send-to-Resolve config: {config_path}

Read by the CC Sync companion (the tray app), which is what "Send to Resolve"
in the b-roll web UI talks to. The separate BRoll Companion this file was
originally written for is retired. Do not run it: it would hold port 8899
and the tray app's server could not start.

This file has no comments (it's plain JSON), so here's what each field means:

  server_url
      Base URL of the b-roll web app. Not required for /insert to work.

  mounts
      Maps each "share" slug used in the web UI to where that share is
      mounted on THIS machine, e.g.:
          {{"broll": "P:/Assets/B-roll Archive"}}   (Windows)
          {{"broll": "/Volumes/broll"}}             (macOS)

      The "broll" share needs no entry at all: it defaults to
      <local_root>/Assets/B-roll Archive from ~/.ccsync/config.toml. Any
      entry written here wins over that. Other shares have no derivable
      root, so they still need one line each.

      With the default in effect, a clip that isn't on this machine yet is
      fetched from the NAS automatically when "Send to Resolve" asks for it
      (over the same rclone remote the sync lanes use). Writing an explicit
      "broll" entry here switches that off: an explicit mount is somewhere
      you chose, and nothing will download into it behind your back.

      The "music" share is read from this same table (the music library's
      "Send to Resolve" buttons talk to the same companion, on the same
      port) and needs no entry either: it defaults to
      <local_root>/Assets/Music.

      The "projects" share is read from it too -- it is what the YouTube
      downloader page's download history opens a folder from -- and defaults
      to <local_root>/Projects.

      On macOS, a share with no entry here is also probed for at
      /Volumes/<share>, /Volumes/<share>-1, /Volumes/<share>-2 (Finder's
      "already mounted" renaming).

After editing this file, restart the CC Sync companion.
"""


# -- config -----------------------------------------------------------------


def ensure_config_exists(
    path: Optional[Path] = None, readme_path: Optional[Path] = None
) -> None:
    """Create the config file (and its README snippet) with defaults if missing."""
    path = config_path() if path is None else path
    readme_path = readme_snippet_path() if readme_path is None else readme_path
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")
    if not readme_path.exists():
        readme_path.parent.mkdir(parents=True, exist_ok=True)
        readme_path.write_text(
            README_SNIPPET.format(config_path=str(path)), encoding="utf-8"
        )


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    """Load the mounts config, creating it with defaults on first run.

    Malformed JSON falls back to defaults rather than crashing -- the same
    never-raise ethos as this package's own load_config, and here it also
    means a hand-edited file with a trailing comma cannot stop the sync
    companion from starting.
    """
    path = config_path() if path is None else path
    try:
        ensure_config_exists(path)
    except OSError:
        log.warning("broll: could not create %s -- using defaults", path, exc_info=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        log.warning("broll: %s is not readable JSON -- using defaults", path)
        data = {}

    merged = dict(DEFAULT_CONFIG)
    if isinstance(data, dict):
        merged.update(data)
    if not isinstance(merged.get("mounts"), dict):
        merged["mounts"] = {}
    return merged


def default_broll_mount(ccsync_cfg: dict[str, Any]) -> Optional[str]:
    """Where the b-roll archive sits in this machine's tree, or None.

    Derived from local_root rather than the canonical "P:\\" prefix on
    purpose: this path is handed to os.path.isfile and to Resolve's
    ImportMedia, and on a Mac there is no drive namespace to resolve "P:\\"
    against. Existence is NOT checked -- an archive that hasn't synced yet
    should produce /insert's "is the share mounted?" message rather than
    "no mount configured for share 'broll'", which would send the editor to
    a config file with nothing wrong in it.
    """
    try:
        root = ccsync_config.resolved_local_root(ccsync_cfg or {})
    except Exception:
        return None
    if not str(ccsync_cfg.get("local_root") or "").strip():
        return None
    return str(Path(root, *BROLL_ARCHIVE_REL))


def resolve_mounts(broll_cfg: dict[str, Any], ccsync_cfg: dict[str, Any]) -> dict[str, str]:
    """The share->root map to serve, with the "broll" default filled in.

    An explicit entry always wins; a blank one counts as absent (it is a
    leftover from the days when the settings panel told editors to fill this
    file in by hand, and treating "" as configured would translate every
    clip to a relative path).
    """
    mounts = dict(broll_cfg.get("mounts") or {})
    if not str(mounts.get(BROLL_SHARE) or "").strip():
        derived = default_broll_mount(ccsync_cfg)
        if derived:
            mounts[BROLL_SHARE] = derived
    return mounts


# -- path translation (share, rel_path) -> local absolute path --------------
#
# Per broll/SPEC.md the DB never stores absolute paths: every video is
# identified by a logical share name plus a forward-slash relative path.


class MountNotConfiguredError(Exception):
    """Raised when a share has no configured (or, on macOS, probeable) mount."""


class PathTraversalError(Exception):
    """Raised when rel_path attempts to escape the mount root (any '..' part).

    Also the channel for a request that is malformed rather than escaping --
    a non-string share/rel_path (MED-5) -- because both routes turn this one
    exception into the 400 they answer a bad request with.
    """


def _split_components(rel_path: str) -> list[str]:
    # rel_path is documented as forward-slash relative; also tolerate a stray
    # backslash from a client that used native separators by treating it the
    # same as a path component boundary.
    normalized = rel_path.replace("\\", "/")
    return [part for part in normalized.split("/") if part not in ("", ".")]


def _validate_components(parts: list[str]) -> None:
    for part in parts:
        if part == "..":
            raise PathTraversalError(
                f"path traversal rejected: '..' component in rel_path"
            )
        # Defense in depth: reject a drive letter or similar smuggled in as
        # a path segment (e.g. "C:" as one of the '/'-split parts).
        if part.endswith(":"):
            raise PathTraversalError(f"invalid path segment '{part}' in rel_path")


VOLUMES_DIR = "/Volumes"


def probe_darwin_mount(
    share: str, isdir: Optional[Callable[[str], bool]] = None,
    realpath: Optional[Callable[[str], str]] = None,
) -> Optional[str]:
    """Look for /Volumes/<share>, -1, -2 (Finder's collision-suffix convention).

    Returns the first candidate that exists as a directory, or None.

    `share` is interpolated into a PATH here, so it is vetted as one safe
    segment first and the result is realpath-contained under /Volumes after
    (2026-08-17, C1): share="../.." used to build "/Volumes/../.." and hand
    back "/", which then became the root every rel_path was joined onto -- the
    whole filesystem served through a route whose contract is one share.

    `isdir` defaults to None (resolved to os.path.isdir at call time, not at
    import time) so tests can either monkeypatch os.path.isdir directly or
    inject a fake callable explicitly; `realpath` is the same seam for the
    containment check, so a darwin layout is testable from a Windows host.
    """
    if not loopback_guard.valid_share(share):
        log.warning("broll: refusing to probe %s for share %r", VOLUMES_DIR, share)
        return None
    check = isdir if isdir is not None else os.path.isdir
    for candidate in (f"{VOLUMES_DIR}/{share}", f"{VOLUMES_DIR}/{share}-1",
                      f"{VOLUMES_DIR}/{share}-2"):
        if not check(candidate):
            continue
        if not loopback_guard.is_within(candidate, VOLUMES_DIR, realpath=realpath):
            # A symlink at /Volumes/<share> pointing out of /Volumes: the
            # segment rules cannot see it, and following it would serve
            # someone else's filesystem under a share name.
            log.warning("broll: %s does not resolve inside %s -- ignoring it",
                        candidate, VOLUMES_DIR)
            continue
        return candidate
    return None


def translate_path(
    share: str,
    rel_path: str,
    mounts: dict,
    platform: Optional[str] = None,
    isdir: Optional[Callable[[str], bool]] = None,
) -> str:
    """Translate (share, rel_path) to a local absolute path string.

    `platform` defaults to the real sys.platform; it's injectable so tests
    can exercise both Windows-style and macOS-style joining/probing from a
    single host OS. The returned string uses the separator appropriate for
    that platform — actual filesystem calls (e.g. os.path.isfile) should
    only be made against the real host's translation (the default).

    Raises MountNotConfiguredError or PathTraversalError; never silently
    returns a path outside the configured/probed root.
    """
    return translate_path_with_root(share, rel_path, mounts, platform, isdir)[1]


def translate_path_with_root(
    share: str,
    rel_path: str,
    mounts: dict,
    platform: Optional[str] = None,
    isdir: Optional[Callable[[str], bool]] = None,
) -> tuple[str, str]:
    """translate_path, plus the ROOT it resolved the pair against.

    Two callers need the root back, and neither can rediscover it: on macOS
    it may have come from the /Volumes probe rather than the mounts table, so
    music_server's final containment check -- the one thing that catches a
    symlink out of the share -- was silently skipped for exactly the
    documented "mounted but not configured" Mac case (MED-11, 2026-08-11).
    """
    plat = platform if platform is not None else sys.platform

    # Types first. Both fields come off a JSON body, so a page bug (or a
    # hand-rolled request) can hand us a list, a dict or a number, and the
    # string methods below raised AttributeError/TypeError straight out of
    # the request thread: no response at all, and no log line either, because
    # socketserver.handle_error writes to a sys.stderr that is None in the
    # windowed build (MED-5, 2026-08-11). PathTraversalError because that is
    # this module's 400 channel -- a malformed request, not a state an editor
    # can act on.
    if not isinstance(rel_path, str):
        raise PathTraversalError(
            f"rel_path must be a string, got {type(rel_path).__name__}"
        )
    if not isinstance(share, str):
        raise PathTraversalError(
            f"share must be a string, got {type(share).__name__}"
        )
    # ONE safe path segment, checked before the value is used as a mounts key
    # or interpolated into /Volumes/<share> (2026-08-17, C1). Here rather
    # than in probe_darwin_mount alone so the rule holds on every platform
    # and for every route group that translates a pair.
    if not loopback_guard.valid_share(share):
        raise PathTraversalError(f"invalid share name {share!r}")

    if not rel_path or not rel_path.strip():
        raise PathTraversalError("empty rel_path")

    parts = _split_components(rel_path)
    _validate_components(parts)
    if not parts:
        raise PathTraversalError("empty rel_path after normalization")

    root = (mounts or {}).get(share)
    if root is None and plat == "darwin":
        root = probe_darwin_mount(share, isdir=isdir)
    if root is None:
        raise MountNotConfiguredError(f"no mount configured for share '{share}'")
    if not isinstance(root, str):
        raise MountNotConfiguredError(
            f"the mount configured for share '{share}' is not a path"
        )

    if plat.startswith("win"):
        # Normalize the configured root's separators, then append components
        # with backslashes. Leaves drive letters ("Y:\...") intact.
        root_norm = root.replace("/", "\\").rstrip("\\")
        return root, root_norm + "\\" + "\\".join(parts)

    # macOS/posix: normalize to forward slashes, preserve a leading '/'.
    root_norm = root.replace("\\", "/").rstrip("/")
    if root_norm == "":
        root_norm = "/"
    return root, root_norm + "/" + "/".join(parts)


_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def contained_local_path(share: str, rel_path: str, mounts: dict) -> str:
    """translate_path, plus the two guards that make the answer safe to USE.

    An ABSOLUTE rel_path is a contradiction (joining it would hand back a
    path with nothing to do with the share), and the result must still
    resolve INSIDE the root once symlinks are followed -- the only check that
    catches an escape no component rule can see (a symlink, a junction, a
    component none of these rules anticipated).

    Lifted out of music_server.local_path_for on 2026-08-17 (C1): both guards
    had been on the music/ytdl routes since MED-11 while /insert, the route
    that hands its answer to Resolve's ImportMedia, still used the bare
    translate_path. One containment implementation for every route group.
    """
    norm = str(rel_path or "").replace("\\", "/")
    if norm.startswith("/") or _DRIVE_RE.match(norm):
        raise PathTraversalError(f"rel_path must be relative, got {rel_path!r}")

    # The ROOT comes back with the path: on macOS it may have come from the
    # /Volumes probe rather than the mounts table, and reading mounts[share]
    # again here skipped this check entirely for the documented "mounted but
    # not configured" case (MED-11, 2026-08-11).
    root, local = translate_path_with_root(share, rel_path, mounts)

    if root:
        try:
            Path(local).resolve(strict=False).relative_to(
                Path(root).resolve(strict=False)
            )
        except ValueError:
            raise PathTraversalError(
                f"rel_path escapes the share root: {rel_path!r}"
            ) from None
    return local


# -- the two endpoints ------------------------------------------------------


def _json_bytes(obj: dict) -> bytes:
    return json.dumps(obj).encode("utf-8")


# "the body was refused and its 4xx is already on the wire", told apart from
# both a valid body and an unparseable one (None).
_REFUSED = object()


class _UploadTooLarge(Exception):
    """A streamed body outgrew the cap the route was given. Internal to
    _stream_body_to, which turns it into the 413 and deletes the partial."""


def _discard(path: Path) -> None:
    """Delete a half-written staging file. Never raises -- it runs on every
    upload failure path, including the ones already sending a 5xx."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("broll ingest: could not remove %s (%s)", path, exc)


def build_status_response(mounts: dict, caller: Optional[Callable[..., dict]] = None) -> dict:
    """GET /status body, per SPEC.md: {ok, resolve_connected, mounts, version}.

    `version` is this companion's version now that the standalone one is
    retired -- the b-roll settings panel only displays it, and the number an
    editor reads off it should be the number their tray app reports.

    The Resolve half runs in the same killable child the /music routes use
    (MED-3): scriptapp() blocks indefinitely against a Resolve that is modal,
    busy, or on the Project Manager window, and this ran it in-process on a
    request thread while holding resolve_bridge._API_LOCK -- so one click on a
    settings panel could park the watcher, the fixer, FIX ALL and every tray
    Resolve read behind it. A child that never answers is killed; the panel
    then simply says Resolve: no.
    """
    probe = (caller if caller is not None else music_server.call)(
        music_worker.BROLL_STATUS_ACTION, timeout=STATUS_TIMEOUT,
    )
    return {
        "ok": True,
        "resolve_connected": bool((probe or {}).get("resolve_connected")),
        "mounts": mounts,
        "version": ccsync_config.VERSION,
    }


def _fetchable_from_nas(
    share: str, rel_path: str, mounts: dict, ccsync_cfg: Optional[dict]
) -> bool:
    """Is this missing file one the companion should pull down itself?

    Only the "broll" share, only when its effective mount is the DERIVED
    default under local_root (a hand-written ~/.broll-companion.json entry
    means the editor pointed the share somewhere deliberate -- an SMB mount,
    a mirror drive -- and rclone writing into it behind their back is not
    our call), and never on a base rig, whose local_root IS the NAS share:
    a file missing there is missing at the source, and `rclone copyto` from
    the NAS onto the NAS's own SMB mapping helps nobody.
    """
    if not ccsync_cfg or share != BROLL_SHARE:
        return False
    if str(ccsync_cfg.get("mode", "editor")).strip().lower() == "base":
        return False
    derived = default_broll_mount(ccsync_cfg)
    root = (mounts or {}).get(BROLL_SHARE)
    if not derived or not isinstance(root, str):
        return False
    return os.path.normcase(os.path.normpath(root)) == os.path.normcase(
        os.path.normpath(derived)
    )


def build_insert_response(
    body: dict, mounts: dict, caller: Optional[Callable[..., dict]] = None,
    ccsync_cfg: Optional[dict] = None,
    fetcher: Optional[Callable[..., dict]] = None,
) -> tuple[int, dict]:
    """POST /insert logic. Returns (http_status, json_body).

    Path traversal is the one failure that gets a non-200 HTTP status (400);
    every other expected failure path returns 200 with {"ok": false, ...} so
    the web UI can show the message inline.

    A missing file is no longer always terminal (2026-08-11): when the share
    is the archive at its derived place in the tree and this machine has a
    working rclone remote, the companion starts pulling that one clip down
    from the NAS and answers {"ok": false, "state": "downloading",
    "progress": {...}}. The web UI re-POSTs the same body every ~1.5 s to
    read progress; the poll that finds the file in place falls through to
    the ordinary insert. `ccsync_cfg` is None only when the caller predates
    the feature (tests pinning the old contract) -- the live handler always
    passes it. `fetcher` is broll_fetch.poll_fetch's test seam.
    """
    share = body.get("share")
    rel_path = body.get("rel_path")
    in_frame = body.get("in_frame")
    out_frame = body.get("out_frame")
    mode = body.get("mode", "append")

    if mode not in (resolve_bridge.INSERT_MODE_APPEND,
                    resolve_bridge.INSERT_MODE_PLAYHEAD):
        # "playhead" was reserved from v1 and is real as of 0.8.x; anything
        # else is a page newer than this build. Deployed pre-playhead
        # companions answer this same shape with "not implemented yet",
        # which the web UI translates into "update the companion".
        return 200, {"ok": False, "message": f"unknown insert mode {mode!r} -- "
                                             "this companion may need an update"}

    if not isinstance(in_frame, int) or not isinstance(out_frame, int):
        return 400, {"ok": False, "message": "in_frame and out_frame must be integers"}
    if out_frame <= in_frame:
        return 200, {"ok": False, "message": "out point must be after in point"}

    try:
        local_path_str = contained_local_path(share, rel_path, mounts)
    except PathTraversalError as exc:
        return 400, {"ok": False, "message": str(exc)}
    except MountNotConfiguredError as exc:
        return 200, {"ok": False, "message": str(exc)}

    local_path = Path(local_path_str)
    if not local_path.is_file():
        if not _fetchable_from_nas(share, rel_path, mounts, ccsync_cfg):
            return 200, {
                "ok": False,
                "message": f"file not found at {local_path} - is the share mounted?",
            }
        # ...and the tree this download would land in has to BE there, and
        # the destination inside it (2026-08-17, COMMERCIAL_READINESS.md
        # item 5's M-tier "on-demand fetch bypasses root guard"): rclone
        # against an unmounted macOS root does not fail, it fills the boot
        # disk (root_guard.py's opening paragraph).
        refusal = broll_fetch.fetch_refusal(ccsync_cfg, str(local_path))
        if refusal:
            return 200, {"ok": False, "message": refusal}
        # The validated components, re-joined with forward slashes: the
        # remote side of the copy must never see the raw client string that
        # translate_path only just finished vetting.
        clean_rel = "/".join(_split_components(rel_path))
        fetch = (fetcher if fetcher is not None else broll_fetch.poll_fetch)(
            ccsync_cfg, clean_rel, str(local_path)
        )
        state = fetch.get("state")
        if state == broll_fetch.STATE_DOWNLOADING:
            progress = fetch.get("progress") or {}
            percent = progress.get("percent")
            message = (
                f"syncing the clip to this machine: {percent}%"
                if isinstance(percent, int)
                else "syncing the clip to this machine…"
            )
            return 200, {"ok": False, "state": "downloading",
                         "message": message, "progress": progress}
        if state != broll_fetch.STATE_DONE:
            return 200, {
                "ok": False,
                "message": "couldn't sync the clip from the NAS: "
                           f"{fetch.get('message') or 'the download failed'}",
            }
        if not local_path.is_file():
            # "done" is only ever reported after an isfile() check inside
            # the job, so reaching here means the file vanished in between.
            return 200, {
                "ok": False,
                "message": f"file not found at {local_path} - is the share mounted?",
            }

    # In a CHILD, with a timeout, for the reason build_status_response spells
    # out (MED-3, 2026-08-11). The worker calls the same
    # resolve_bridge.perform_insert this used to call in-process, so the
    # result dict -- {"ok", "message"} -- is unchanged, and a Resolve that
    # never answers now costs one killed child instead of a wedged daemon
    # thread holding _API_LOCK.
    run = caller if caller is not None else music_server.call
    result = run(
        music_worker.BROLL_INSERT_ACTION,
        path=str(local_path), in_frame=in_frame, out_frame=out_frame,
        mode=mode,
    )
    if not isinstance(result, dict):
        return 200, {"ok": False, "message": resolve_bridge._SCRIPTING_ERROR_MESSAGE}
    if "message" not in result:
        # The worker's own failure shape is {"ok": false, "error": ...} (a
        # timeout, a child that would not start); the web UI's toast reads
        # "message".
        result = dict(result)
        result["message"] = str(result.get("error") or "the Resolve worker failed")
    return 200, result


# ---------------------------------------------------------------------------
# b-roll ingest (docs/BROLL_INGEST_PLAN.md §4.1)
# ---------------------------------------------------------------------------


def ingest_staging_root(ccsync_cfg: Optional[dict[str, Any]]) -> Optional[Path]:
    """Where dropped clips and their intermediate files live on this machine.

    `<local_root>/Assets/B-roll Archive/.ingest`, i.e. INSIDE the tree, for two
    reasons that are not convenience: everything staging produces is renamed
    (never copied) into the archive mirror beside it, and the root guard
    already refuses to write there when the drive is absent or misplaced.

    `broll_ingest_staging_dir` overrides it for the base rig, whose local_root
    IS the NAS share -- staging a 40 GB original there would push it over SMB
    twice (plan §9.2). None when this machine has no tree configured at all,
    which every caller reads as "no ingest capability here".
    """
    cfg = ccsync_cfg or {}
    override = str(cfg.get("broll_ingest_staging_dir") or "").strip()
    if override:
        return Path(override)
    mount = default_broll_mount(cfg)
    if not mount:
        return None
    return Path(mount) / INGEST_DIR_NAME


def _free_bytes_at(path: Any) -> Optional[int]:
    """Free bytes on the volume holding `path`, walking up to the first
    directory that exists. None when it cannot be answered -- staging is
    created lazily, so the directory itself usually does not exist yet."""
    try:
        current = Path(path).resolve()
    except Exception:
        return None
    for candidate in [current, *current.parents]:
        try:
            if candidate.exists():
                return int(shutil.disk_usage(str(candidate)).free)
        except OSError:
            return None
    return None


def _ingest_floor_bytes(ccsync_cfg: Optional[dict[str, Any]],
                        kind: Optional[Any] = None) -> int:
    """The staging free-space floor for `kind`, in bytes.

    Kind-aware since 2026-08-18: the ORCHESTRATOR has always read
    `<prefix>_free_space_floor_gb` through `IngestKind.cfg_key`, so a site that
    set only `music_ingest_free_space_floor_gb` got its number in the batch and
    b-roll's at the PUT that refuses before the first byte. Same key, one
    reader. No `kind` still means b-roll's, for the callers that predate it.
    """
    key = (kind.cfg_key("free_space_floor_gb") if kind is not None
           else "broll_ingest_free_space_floor_gb")
    floor_gb = ccsync_config.coerce_numeric(ccsync_cfg or {}, key, 20)
    try:
        return int(max(0.0, float(floor_gb)) * 1_000_000_000)
    except (TypeError, ValueError):
        return 20_000_000_000


def build_ingest_capabilities(ccsync_cfg: Optional[dict[str, Any]],
                              ingestor: Optional[Any] = None,
                              deps: Optional[Any] = None,
                              kind: Optional[Any] = None) -> dict[str, Any]:
    """What GET /<kind>/ingest/capabilities answers. 200 always; `ok` carries
    the verdict and `reasons` says what is missing, in editor words.

    `kind` defaults to b-roll, so every existing caller (and every test that
    pins the pre-2026-08-18 three-argument shape) gets exactly the answer it
    always did. Music is a DIFFERENT answer, not a subset: it has no tiers and
    no VRAM floor to report, and what its page needs instead is whether the
    CLAP artefact is cached and how big a first run's download would be
    (`build_music_ingest_capabilities`).

    ZERO I/O apart from one disk_usage, for ytdl's reason: the page asks this
    before it renders the drop zone, and a probe that spawned ffmpeg or
    nvidia-smi would make the panel appear a second late on every load. The
    GPU and the model cache come from broll_vlm_sidecar's cached snapshot
    (refreshed on the ingest tick), the encoder list from ffmpeg_tools' cache,
    and "is rclone there" from a which() -- never a `--version` spawn.

    `ok: false` is a complete answer, not an error: it means this machine
    cannot index, and the page says so with the reason rather than offering a
    Run button that will 503.
    """
    if kind is not None and getattr(kind, "name", "") == ingest_kinds.MUSIC:
        return build_music_ingest_capabilities(ccsync_cfg, ingestor, deps)
    cfg = ccsync_cfg or {}
    reasons: list[str] = []

    snapshot = {}
    gpu_info: dict[str, Any] = {}
    try:
        snapshot = broll_vlm_sidecar.status()
        gpu_info = dict(snapshot.get("gpu") or {})
    except Exception:  # noqa: BLE001 - a capability probe is never fatal
        log.debug("broll ingest: the sidecar snapshot failed", exc_info=True)

    tiers: dict[str, Any] = {}
    ready = dict(snapshot.get("model_ready") or {})
    for key in ("good", "best"):
        try:
            fits, why = broll_vlm_sidecar.fits(key, gpu_info or None)
        except Exception:  # noqa: BLE001
            fits, why = False, "this build cannot describe that model tier"
        cached = bool(ready.get(key))
        entry: dict[str, Any] = {"fits": bool(fits), "reason": why, "cached": cached}
        # What the SPA's "this will download N GB first" confirmation needs
        # (plan §5, §9.6), and the VRAM floor beside it so the disabled radio
        # can say WHY without parsing the sentence. Nothing here is I/O: both
        # come out of the vendored catalogue's pinned sizes.
        try:
            tier_meta = broll_vlm_sidecar._models().tier(key)
            entry["vram_gb"] = (tier_meta.apple_unified_gb
                                if gpu_info.get("apple_silicon") else tier_meta.vram_gb)
            entry["download_bytes"] = (
                0 if cached else
                tier_meta.weights.size_bytes + tier_meta.mmproj.size_bytes)
            entry["label"] = tier_meta.label
        except Exception:  # noqa: BLE001 - an unknown tier stays unadorned
            log.debug("broll ingest: no catalogue entry for tier %r", key, exc_info=True)
        tiers[key] = entry
    try:
        recommended = broll_vlm_sidecar.recommended_tier(gpu_info or None)
    except Exception:  # noqa: BLE001
        recommended = None
    if not any(t["fits"] for t in tiers.values()):
        reasons.append(tiers["good"]["reason"] or
                       "this machine's GPU cannot run the b-roll indexing model")

    ffmpeg_path = str(cfg.get("ffmpeg_path", "ffmpeg") or "ffmpeg").strip() or "ffmpeg"
    try:
        ffmpeg = ffmpeg_tools._resolve_binary(ffmpeg_path)
    except Exception:  # noqa: BLE001
        ffmpeg = None
    if not ffmpeg:
        reasons.append("ffmpeg is not installed on this machine yet: it is "
                       "fetched the first time a batch runs")
    # None, not False, when nothing has probed the encoders yet: "we have not
    # asked" and "this build has no NVENC" send an editor to different places.
    nvenc: Optional[bool] = None
    try:
        encoders = ffmpeg_tools.encoders_if_known(ffmpeg_path)
        if encoders is not None:
            nvenc = "h264_nvenc" in encoders
    except Exception:  # noqa: BLE001
        nvenc = None

    rclone_path = str(cfg.get("rclone_path", "rclone") or "rclone").strip() or "rclone"
    rclone = bool(shutil.which(rclone_path) or os.path.isfile(rclone_path))
    if not rclone:
        reasons.append("rclone is not installed on this machine, so indexed "
                       "clips could not be uploaded to the NAS")

    staging_dir = ingest_staging_root(cfg)
    floor = _ingest_floor_bytes(cfg)
    free = _free_bytes_at(staging_dir) if staging_dir is not None else None
    if staging_dir is None:
        reasons.append("this machine has no synced tree, so there is nowhere "
                       "to stage the clips")
    elif free is not None and free < floor:
        reasons.append(
            f"only {free / 1_000_000_000:.1f} GB free where the clips would be "
            f"staged (the floor is {floor / 1_000_000_000:.0f} GB)")

    busy = {"batch_uid": None, "state": ""}
    if ingestor is not None:
        try:
            busy = dict(ingestor.busy())
        except Exception:  # noqa: BLE001
            log.debug("broll ingest: busy() failed", exc_info=True)
    if busy.get("batch_uid"):
        reasons.append("this machine is already indexing a b-roll batch")

    editor = ""
    if deps is not None:
        try:
            editor = str(deps.editor() or "")
        except Exception:  # noqa: BLE001
            editor = ""
    if not editor:
        reasons.append("nobody is signed in on this machine")

    if ingestor is None:
        reasons.append("b-roll indexing is switched off on this machine")

    return {
        "ok": not reasons,
        "reasons": reasons,
        "version": ccsync_config.VERSION,
        "ffmpeg": bool(ffmpeg),
        "nvenc": nvenc,
        "rclone": rclone,
        "gpu": {
            "present": bool(gpu_info.get("present")),
            "vram_gb": gpu_info.get("vram_gb"),
            "detail": gpu_info.get("detail") or "",
            "apple_silicon": bool(gpu_info.get("apple_silicon")),
        },
        "tiers": tiers,
        "recommended_tier": recommended,
        "runtime_cached": bool(snapshot.get("runtime_ready")),
        "staging": {
            "dir": str(staging_dir) if staging_dir is not None else "",
            "free_bytes": free,
            "floor_bytes": floor,
        },
        "busy": busy,
        "signed_in": bool(editor),
        "run_modes": list(INGEST_RUN_MODES),
    }


def build_music_ingest_capabilities(
        ccsync_cfg: Optional[dict[str, Any]] = None,
        ingestor: Optional[Any] = None,
        deps: Optional[Any] = None) -> dict[str, Any]:
    """What GET /music/ingest/capabilities answers (MUSIC_INGEST_PLAN.md §2).

    b-roll's answer with `tiers`/`gpu`/`recommended_tier` replaced by one
    `clap` block, because there is nothing to choose: the CLAP audio tower is
    one 280 MB artefact that runs on the CPU. `{cached, download_bytes,
    version}` is what the page's "this will download N MB first" confirmation
    needs, and it is the ONLY thing an editor is asked to consent to here.

    NO VRAM GATE and no `fits`, deliberately: a machine with no GPU is a
    perfectly good music indexer (~90 ms per 10 s window), so the one refusal
    this kind can raise is a build with no onnxruntime -- which is a broken
    install, not a small graphics card.

    Same ZERO I/O rule as b-roll's (one disk_usage): the page asks this before
    it renders the drop zone.
    """
    from . import music_clap_sidecar

    cfg = ccsync_cfg or {}
    reasons: list[str] = []

    try:
        clap = music_clap_sidecar.capabilities(cfg)
    except Exception:  # noqa: BLE001 - a capability probe is never fatal
        log.debug("music ingest: the CLAP snapshot failed", exc_info=True)
        clap = {"cached": False, "download_bytes": 0, "version": "",
                "runtime": None, "providers": [], "feed": False, "dim": 0}
    try:
        refusal = music_clap_sidecar.refusal(cfg)
    except Exception:  # noqa: BLE001
        refusal = ""
    if refusal:
        reasons.append(refusal)

    ffmpeg_path = str(cfg.get("ffmpeg_path", "ffmpeg") or "ffmpeg").strip() or "ffmpeg"
    try:
        ffmpeg = ffmpeg_tools._resolve_binary(ffmpeg_path)
    except Exception:  # noqa: BLE001
        ffmpeg = None
    if not ffmpeg:
        reasons.append("ffmpeg is not installed on this machine yet: it is "
                       "fetched the first time a batch runs")

    rclone_path = str(cfg.get("rclone_path", "rclone") or "rclone").strip() or "rclone"
    rclone = bool(shutil.which(rclone_path) or os.path.isfile(rclone_path))
    if not rclone:
        reasons.append("rclone is not installed on this machine, so indexed "
                       "tracks could not be uploaded to the library")

    kind = ingest_kinds.MUSIC_KIND
    staging_dir = kind.staging_root(cfg)
    floor = _ingest_floor_bytes(cfg, kind)
    free = _free_bytes_at(staging_dir) if staging_dir is not None else None
    if staging_dir is None:
        reasons.append("this machine has no synced tree, so there is nowhere "
                       "to stage the tracks")
    elif free is not None and free < floor:
        reasons.append(
            f"only {free / 1_000_000_000:.1f} GB free where the tracks would "
            f"be staged (the floor is {floor / 1_000_000_000:.0f} GB)")

    busy = {"batch_uid": None, "state": ""}
    if ingestor is not None:
        try:
            busy = dict(ingestor.busy())
        except Exception:  # noqa: BLE001
            log.debug("music ingest: busy() failed", exc_info=True)
    if busy.get("batch_uid"):
        reasons.append("this machine is already indexing a music batch")

    editor = ""
    if deps is not None:
        try:
            editor = str(deps.editor() or "")
        except Exception:  # noqa: BLE001
            editor = ""
    if not editor:
        reasons.append("nobody is signed in on this machine")

    if ingestor is None:
        reasons.append("music indexing is switched off on this machine")

    return {
        "ok": not reasons,
        "reasons": reasons,
        "version": ccsync_config.VERSION,
        "kind": ingest_kinds.MUSIC,
        "ffmpeg": bool(ffmpeg),
        "rclone": rclone,
        "clap": clap,
        "audio_exts": sorted(kind.exts),
        "transcode_exts": sorted(ingest_kinds.MUSIC_TRANSCODE_EXTS),
        # The container's own per-file ceiling (musicweb.config.
        # MAX_INGEST_FILE_BYTES). Published so the page refuses a 2 GB stem
        # before it streams it, and so THIS listener and the server cannot
        # disagree about what "too big" is.
        "max_file_bytes": MUSIC_MAX_FILE_BYTES,
        "max_items": kind.max_prepare_items,
        "staging": {
            "dir": str(staging_dir) if staging_dir is not None else "",
            "free_bytes": free,
            "floor_bytes": floor,
        },
        "busy": busy,
        "signed_in": bool(editor),
        "run_modes": list(INGEST_RUN_MODES),
    }


def pick_ingest_sources(kind: str,
                        exts: Optional[Any] = None) -> tuple[int, dict[str, Any]]:
    """Run the native file/folder picker and answer with real paths.

    THE ONLY route that learns a local path from this machine rather than
    being told one, and that is the point: a browser cannot hand over a path
    (it never sees one), so an editor who wants their 400-clip card indexed IN
    PLACE -- no copy into staging at all -- has to pick it here. The dialog
    runs on the UI thread through ui_dispatch, like every other window in this
    package; a request thread that opened its own Tk root would be the second
    one in the process (CORE-M3).
    """
    from . import popup  # deferred: importing Tk plumbing costs a server that never picks

    if kind not in ("files", "folder"):
        return 400, {"ok": False, "message": "kind must be 'files' or 'folder'"}
    try:
        # `exts` is passed ONLY when a caller named one: the b-roll route does
        # not, so this stays the same call it always was down to its keyword
        # arguments (which the tests' picker doubles pin), and
        # pick_media_sources falls back to the b-roll list itself. The music
        # route names its own -- without it, a folder walk would offer an
        # editor every .mov sitting in their album folder.
        extra = {"exts": exts} if exts is not None else {}
        files = popup.pick_media_sources(kind, timeout=PICK_TIMEOUT_SECONDS,
                                         **extra)
    except Exception as exc:  # noqa: BLE001 - a picker is never fatal
        log.warning("broll ingest: the file picker failed (%s)", exc, exc_info=True)
        return 200, {"ok": False, "message": "the file picker could not be opened "
                                             "on this machine"}
    if not files:
        return 200, {"ok": False, "message": "cancelled"}
    return 200, {"ok": True, "files": files}


class BrollRequestHandler(BaseHTTPRequestHandler):
    server_version = f"CCSyncCompanion/{ccsync_config.VERSION}"

    # The caller's Origin once it has been ALLOWED, else None -- set per
    # request by _vet_request and read by _set_cors_headers. A class-level
    # default because _guarded's 500 path can reach _send_json before any
    # dispatch has run.
    _cors_origin: Optional[str] = None

    def _vet_request(self) -> bool:
        """Decide whether this request may be answered at all.

        False means a refusal is already on the wire. The order matters: Host
        before Origin, because a rebinding request that also carries a hostile
        Origin should be refused on the more specific fact, and both before
        any body is read.
        """
        self._cors_origin = None
        host = self.headers.get("Host")
        if not loopback_guard.host_allowed(host, self.server.server_address[1]):
            # DNS rebinding: a name the attacker controls, pointed at
            # 127.0.0.1, would make their page same-origin with this server
            # and the Origin check below would never fire.
            log.warning("broll: refusing %s %s -- Host %r is not this loopback",
                        self.command, self.path, host)
            self._refuse(403)
            return False

        origin = self.headers.get("Origin")
        if origin:
            allowed = getattr(self.server, "allowed_origins", frozenset())
            if not loopback_guard.origin_allowed(
                origin, allowed, dev=getattr(self.server, "dev_origins", False)
            ):
                log.warning(
                    "broll: refusing %s %s from origin %r -- this companion "
                    "serves %s. If that is the dashboard your editors actually "
                    "browse, set dashboard_url (or loopback_extra_origins) in "
                    "~/.ccsync/config.toml to match it.",
                    self.command, self.path, origin, sorted(allowed) or "no origin",
                )
                self._refuse(403)
                return False
            self._cors_origin = origin
        return True

    def _post_authorised(self) -> bool:
        """A state-changing request needs an allowed Origin or the token."""
        if self._cors_origin is not None:
            return True
        if loopback_guard.verify_token(
            self.headers.get(loopback_guard.TOKEN_HEADER)
        ):
            return True
        log.warning(
            "broll: refusing POST %s -- no allowed Origin and no valid %s "
            "header (the token is in %s)",
            self.path, loopback_guard.TOKEN_HEADER, loopback_guard.token_path(),
        )
        self._refuse(403)
        return False

    def _content_type_ok(self) -> bool:
        """Every POST body here is JSON, and saying so is load-bearing.

        text/plain, multipart/form-data and application/x-www-form-urlencoded
        are the three a cross-origin <form> can send with NO preflight at all;
        insisting on application/json is what makes the browser ask this
        server's permission before a hostile page's POST can arrive.
        """
        ctype = self.headers.get("Content-Type")
        if loopback_guard.content_type_is_json(ctype):
            return True
        log.warning("broll: refusing POST %s -- Content-Type %r is not "
                    "application/json", self.path, ctype)
        self._refuse(415)
        return False

    def _refuse(self, status: int) -> None:
        """One body for every refusal, carrying BOTH route groups' error keys.

        Generic on purpose (COMMERCIAL_READINESS.md L-tier): a caller this
        server has just declined to talk to is not owed a description of the
        allow-list it failed. The reason is always in the log.
        """
        self._send_json(status, {
            "ok": False,
            "message": loopback_guard.REFUSED_MESSAGE,
            "error": loopback_guard.REFUSED_MESSAGE,
        })

    def _set_cors_headers(self) -> None:
        # Vary unconditionally: the answer to "may this origin read the
        # response" now depends on the request, and a cache that missed that
        # would hand one page another's permission.
        self.send_header("Vary", "Origin")
        if self._cors_origin is None:
            # No Origin, or one already refused. A response with no
            # Access-Control-Allow-Origin at all is unreadable to any page,
            # which is exactly what a refused caller should get -- and it is
            # what a browser-less caller (curl, the tray) neither needs nor
            # notices.
            return
        self.send_header("Access-Control-Allow-Origin", self._cors_origin)
        self.send_header(
            "Access-Control-Allow-Headers",
            f"Content-Type, {loopback_guard.TOKEN_HEADER}, {INGEST_HEADER}",
        )
        # PUT since 2026-08-18, for the one ingest upload route. A method a
        # preflight is not told about is a method the browser refuses before
        # the request is made, so this is what makes drag-and-drop possible at
        # all -- and it costs nothing elsewhere: do_PUT answers 404 on every
        # other path.
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        # Private Network Access, for ALLOWED origins only (it was
        # unconditional until 2026-08-17). The b-roll UI is served from the
        # cc_sync dashboard, so the page comes from a tailnet address and
        # calls loopback — exactly the public-to-private direction Chromium is
        # progressively blocking, and it blocks at the PREFLIGHT, so without
        # this the insert button fails before any of our code runs. Harmless
        # on browsers that don't implement it.
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send_json(self, status: int, obj: dict) -> None:
        payload = _json_bytes(obj)
        self.send_response(status)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_bytes(self, status: int, content_type: str, payload: bytes) -> None:
        """The one non-JSON answer this listener gives: a staging thumbnail.

        no-store rather than a cache header: a `local_id` is reused within a
        staging directory as soon as an item is retried, and a browser holding
        the first attempt's frame would show the wrong clip.
        """
        self.send_response(status)
        self._set_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:  # CORS preflight
        self._guarded(self._dispatch_options)

    def _dispatch_options(self) -> None:
        if not self._vet_request():
            return
        if self._cors_origin is None:
            # A preflight is a browser asking permission; a preflight with no
            # Origin is not a browser, and answering it would publish the
            # allow-list's shape to anything that asked.
            self._refuse(403)
            return
        self.send_response(204)
        self._set_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_body(self, key: str) -> Optional[bytes]:
        """The request body as bytes, or None when it was refused.

        Refusing SENDS the 4xx itself (`key` is the route's error field --
        "message" for b-roll, "error" for music) and returns None, so a caller
        that gets None has nothing left to do.
        """
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length else 0
        except (TypeError, ValueError):
            self._send_json(400, {"ok": False, key: "invalid Content-Length"})
            return None
        if length < 0:
            self._send_json(400, {"ok": False, key: "invalid Content-Length"})
            return None
        if length > MAX_BODY_BYTES:
            self._send_json(
                413, {"ok": False, key: f"body too large (max {MAX_BODY_BYTES} bytes)"}
            )
            return None
        chunks: list[bytes] = []
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, _READ_CHUNK_BYTES))
            if not chunk:
                # The client hung up mid-body. Whatever arrived is handed on
                # and fails the JSON parse as any other truncated body does.
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _read_json_body(self, key: str = "error") -> Any:
        """The request body as parsed JSON, None if it isn't JSON, and
        _REFUSED when a 4xx has already gone out (see _read_body)."""
        raw = self._read_body(key)
        if raw is None:
            return _REFUSED
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _guarded(self, dispatch: Callable[[], None]) -> None:
        """Run one request's dispatch, never letting an exception escape.

        socketserver's handle_error prints the traceback to sys.stderr, which
        is None in the windowed build: an unexpected type in a JSON body used
        to produce no response, no log line and a client left waiting until it
        timed out (MED-5, 2026-08-11).
        """
        try:
            dispatch()
        except Exception:
            log.exception("broll: %s %s failed", self.command, self.path)
            try:
                self._send_json(
                    500, {"ok": False, "message": "the companion failed to handle "
                                                  "that request -- see its log"},
                )
            except Exception:
                log.debug("broll: could not send the 500 either", exc_info=True)

    def do_GET(self) -> None:
        # No token needed: a GET here changes nothing, and the self-test every
        # web UI tells editors to run ("open http://127.0.0.1:8899/status")
        # is a top-level navigation, which sends no Origin and could carry no
        # header of ours anyway.
        self._guarded(lambda: self._vet_request() and self._dispatch_get())

    def do_POST(self) -> None:
        self._guarded(
            lambda: self._vet_request() and self._post_authorised()
            and self._content_type_ok() and self._dispatch_post()
        )

    # How much of THIS request's body has been read. Only the PUT route has a
    # body big enough to care, and it is what lets the tail drain below know
    # whether there is anything left to swallow.
    _body_consumed = 0

    def do_PUT(self) -> None:
        """The upload route, and nothing else.

        Same envelope as a POST -- Host, Origin, then "an allowed Origin or the
        token" -- but NOT _content_type_ok: this body is bytes, and the
        content-type rule that applies here is do_PUT's own (see
        _ingest_content_type_ok).

        The `finally` matters. A refusal that leaves an unread body in the
        socket's receive buffer makes the CLOSE a reset, and the client then
        loses the 403/409/507 that explained what happened -- it sees only
        "connection aborted", which is what a firewall looks like. Every
        refusal path is covered rather than each one remembering.
        """
        self._body_consumed = 0

        def _dispatch() -> None:
            try:
                (self._vet_request() and self._post_authorised()
                 and self._dispatch_put())
            finally:
                self._drain_small_body()

        self._guarded(_dispatch)

    def _kind_for_path(self, path: str) -> Any:
        """Which ingest kind a path belongs to. b-roll unless it says music.

        The two route groups are the same eight routes with the same bodies
        (MUSIC_INGEST_PLAN.md §2), so the prefix is the ONLY thing that
        decides which orchestrator, which staging root and which fleet prefix
        a request reaches.
        """
        for prefix, name in INGEST_PREFIXES.items():
            if path.startswith(prefix):
                return ingest_kinds.kind_for(name)
        return ingest_kinds.BROLL_KIND

    def _ingest_deps(self, kind: Optional[Any] = None) -> Any:
        """What app.py handed this listener about ingest of `kind`, or None.

        None is a complete answer -- a companion whose orchestrator failed to
        construct, or one built by an older caller -- and every ingest route
        answers it the same way: this machine cannot index, in the body, with
        the page free to fall back to "ask another machine". The music
        attribute is separate rather than a dict keyed by kind so that a
        server built by an older caller (b-roll only) is exactly what it was.
        """
        if kind is not None and getattr(kind, "name", "") == ingest_kinds.MUSIC:
            return getattr(self.server, "music_ingest_deps", None)
        return getattr(self.server, "ingest_deps", None)

    def _ingestor(self, kind: Optional[Any] = None) -> Any:
        deps = self._ingest_deps(kind)
        if deps is None:
            return None
        return getattr(deps, "ingestor", None)

    def _no_ingestor(self, kind: Optional[Any] = None) -> None:
        label = getattr(kind, "label", "") or "b-roll"
        self._send_json(503, {
            "ok": False,
            "message": f"{label} indexing is not running on this machine",
        })

    def _ingest_content_type_ok(self) -> bool:
        """The upload route's own rule, replacing _content_type_ok's.

        `application/octet-stream` is accepted ONLY alongside `X-CCSync-Ingest`
        (or the loopback token). Without one of those a page could stream bytes
        into staging with no preflight at all, which is the one thing this
        route must never allow -- and JSON is refused outright here, because a
        JSON body on an upload route is a caller that has misread the contract.
        """
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/octet-stream":
            log.warning("broll ingest: refusing PUT %s -- Content-Type %r is not "
                        "application/octet-stream", self.path, ctype or None)
            self._drain_small_body()
            self._refuse(415)
            return False
        if str(self.headers.get(INGEST_HEADER) or "").strip():
            return True
        if loopback_guard.verify_token(
            self.headers.get(loopback_guard.TOKEN_HEADER)
        ):
            return True
        log.warning(
            "broll ingest: refusing PUT %s -- an octet-stream body needs the %s "
            "header (which forces a preflight) or the loopback token",
            self.path, INGEST_HEADER,
        )
        self._drain_small_body()
        self._refuse(403)
        return False

    def _stream_body_to(self, dest: Path, limit: int) -> Optional[int]:
        """Stream this request's body to `dest`, at most `limit` bytes.

        Returns the byte count, or None when a 4xx/5xx is already on the wire.
        Written to `<dest>.partial` and renamed only on a complete body, for
        broll_fetch's reason: a half-written file that looks finished is worse
        than no file, and the next attempt must be able to tell them apart.

        The limit is enforced on the BYTES READ, not on Content-Length alone: a
        client that declares 4 KB and sends 40 GB would otherwise fill the
        editor's drive, and Content-Length is the client's claim about itself.
        """
        raw_length = self.headers.get("Content-Length")
        try:
            declared = int(raw_length) if raw_length else -1
        except (TypeError, ValueError):
            self._send_json(400, {"ok": False, "message": "invalid Content-Length"})
            return None
        if declared < 0:
            self._send_json(411, {"ok": False,
                                  "message": "this upload needs a Content-Length"})
            return None
        if declared > limit:
            self._send_json(413, {"ok": False, "message": (
                f"this file is bigger than the {limit} bytes the companion was "
                "told to expect")})
            return None

        partial = dest.with_name(dest.name + ".partial")
        written = 0
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(partial, "wb") as handle:
                remaining = declared
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, _UPLOAD_CHUNK_BYTES))
                    if not chunk:
                        break
                    written += len(chunk)
                    self._body_consumed += len(chunk)
                    if written > limit:
                        raise _UploadTooLarge()
                    handle.write(chunk)
                    remaining -= len(chunk)
        except _UploadTooLarge:
            _discard(partial)
            self._send_json(413, {"ok": False, "message": (
                "this upload sent more than it declared -- nothing was kept")})
            return None
        except OSError as exc:
            _discard(partial)
            log.warning("broll ingest: could not write %s (%s)", partial, exc)
            self._send_json(507, {"ok": False, "message": (
                "the companion could not write the clip to its staging folder "
                f"-- {exc.strerror or exc}")})
            return None
        if written < declared:
            # The client hung up mid-body. The partial is dropped rather than
            # renamed: a short file that reached the hashing stage would be
            # indexed and uploaded as if it were the whole clip.
            _discard(partial)
            self._send_json(400, {"ok": False, "message": (
                "the upload stopped before the whole file arrived")})
            return None
        try:
            os.replace(str(partial), str(dest))
        except OSError as exc:
            _discard(partial)
            log.warning("broll ingest: could not publish %s (%s)", dest, exc)
            self._send_json(507, {"ok": False, "message": (
                "the companion could not finish writing the clip into staging")})
            return None
        return written

    def _drain_small_body(self, limit: int = _UPLOAD_CHUNK_BYTES) -> None:
        """Swallow up to `limit` bytes of a body we are about to refuse.

        Without it a refusal races the client's upload: this handler answers
        and closes while the browser is still writing, and on Windows the
        client sees a connection reset instead of the 409/507 that explains
        what happened. Bounded on purpose -- a 40 GB body is never drained,
        and a client that big gets the reset it would have got anyway.
        """
        raw = self.headers.get("Content-Length")
        try:
            declared = int(raw or 0)
        except (TypeError, ValueError):
            return
        remaining = min(declared - self._body_consumed, limit)
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, _READ_CHUNK_BYTES))
            if not chunk:
                return
            remaining -= len(chunk)
            self._body_consumed += len(chunk)

    def _dispatch_put(self) -> None:
        path = urlparse(self.path).path
        match = _UPLOAD_PATH_RE.match(path)
        if match is None:
            self._send_json(404, {"ok": False, "message": f"not found: {self.path}"})
            return
        kind = self._kind_for_path(path)
        ingestor = self._ingestor(kind)
        if ingestor is None:
            self._drain_small_body()
            self._no_ingestor(kind)
            return
        if not self._ingest_content_type_ok():
            return
        staging_id, local_id = match.group(2), unquote(match.group(3))

        status, slot = ingestor.upload_slot(staging_id, local_id)
        if status != 200:
            self._drain_small_body()
            self._send_json(status, slot)
            return
        dest = Path(str(slot.get("path") or ""))
        root = slot.get("staging_root")
        # Belt and braces over the orchestrator's own containment check: this
        # is the only route on this listener that WRITES a caller-named file,
        # and the id came off the wire. `.parent`, because dest does not exist
        # yet and realpath cannot follow a symlink that is not there.
        if not root or not loopback_guard.is_within(dest.parent, root):
            log.warning("broll ingest: refusing an upload to %s -- outside %s",
                        dest, root)
            self._drain_small_body()
            self._refuse(403)
            return

        declared = int(slot.get("size") or 0)
        # The music container refuses a file over its own ceiling, so a track
        # that big is bytes an editor would upload twice and lose both times.
        # Refused HERE, before the first one moves.
        if (kind.name == ingest_kinds.MUSIC and declared
                and declared > MUSIC_MAX_FILE_BYTES):
            self._drain_small_body()
            self._send_json(413, {"ok": False, "message": (
                f"that track is {declared / 1_000_000:.0f} MB and the library "
                f"takes at most {MUSIC_MAX_FILE_BYTES / 1_000_000:.0f} MB per "
                "file")})
            return
        floor = _ingest_floor_bytes(getattr(self.server, "ccsync_cfg", None), kind)
        free = _free_bytes_at(dest.parent)
        if free is not None and declared and (free - declared) < floor:
            self._drain_small_body()
            self._send_json(507, {"ok": False, "message": (
                f"not enough space to stage this clip: it needs "
                f"{declared / 1_000_000_000:.1f} GB and only "
                f"{free / 1_000_000_000:.1f} GB is free "
                f"(the floor is {floor / 1_000_000_000:.0f} GB) -- free some "
                "space and drop it again")})
            return

        limit = (declared + max(int(declared * INGEST_UPLOAD_SLACK_PCT),
                                INGEST_UPLOAD_SLACK_FLOOR)
                 if declared else MAX_BODY_BYTES)
        written = self._stream_body_to(dest, limit)
        if written is None:
            return
        status, result = ingestor.note_upload(staging_id, local_id, written)
        self._send_json(status, result)

    def _dispatch_ingest_get(self, path: str, query: dict) -> bool:
        """The three ingest GETs, for either kind. True when answered here."""
        kind = self._kind_for_path(path)
        suffix = path[len(kind.loopback_prefix):]
        if suffix == "/capabilities":
            # 200 ALWAYS with the verdict in the body, for /ytdl/capabilities'
            # reason: a non-200 reads to the page as "no companion here", which
            # is a different (and less useful) message than "this GPU is too
            # small".
            self._send_json(200, build_ingest_capabilities(
                getattr(self.server, "ccsync_cfg", None),
                self._ingestor(kind), self._ingest_deps(kind), kind=kind))
            return True
        if suffix == "/progress":
            ingestor = self._ingestor(kind)
            if ingestor is None:
                self._no_ingestor(kind)
                return True
            staging_id = (query.get("staging_id") or [""])[0]
            self._send_json(200, ingestor.progress(staging_id or None))
            return True
        if suffix == "/thumb":
            ingestor = self._ingestor(kind)
            if ingestor is None:
                self._no_ingestor(kind)
                return True
            staging_id = (query.get("staging_id") or [""])[0]
            local_id = (query.get("local_id") or [""])[0]
            status, result = ingestor.thumb(staging_id, local_id)
            if status != 200:
                self._send_json(status, result)
                return True
            self._send_bytes(200, "image/jpeg", result)
            return True
        return False

    def _dispatch_ingest_post(self, path: str) -> bool:
        """The four ingest POSTs, for either kind. True when answered here."""
        if not any(path.startswith(prefix) for prefix in INGEST_PREFIXES):
            return False
        kind = self._kind_for_path(path)
        suffix = path[len(kind.loopback_prefix):]
        if suffix == "/pick":
            body = self._read_json_body("message")
            if body is _REFUSED:
                return True
            if not isinstance(body, dict):
                self._send_json(400, {"ok": False, "message": "invalid JSON body"})
                return True
            # `kind` in THIS body is "files" or "folder" -- which picker to
            # open -- and has nothing to do with the ingest kind the path
            # carries. Same word, two meanings, and the path is the one that
            # decides where the answer goes.
            # b-roll passes NO extension list: `popup.pick_media_sources`
            # already defaults to exactly `INGEST_VIDEO_EXTS`, so naming it
            # here would be a second copy of the same set. Music must name
            # its own or the folder walk offers every .mov in the album.
            wanted = None if kind.name == ingest_kinds.BROLL else kind.exts
            status, result = pick_ingest_sources(str(body.get("kind") or "files"),
                                                 exts=wanted)
            self._send_json(status, result)
            return True

        ingestor = self._ingestor(kind)
        if suffix in ("/prepare", "/run", "/control"):
            body = self._read_json_body("message")
            if body is _REFUSED:
                return True
            if not isinstance(body, dict):
                self._send_json(400, {"ok": False, "message": "invalid JSON body"})
                return True
            if ingestor is None:
                self._no_ingestor(kind)
                return True
            if suffix == "/prepare":
                status, result = ingestor.prepare(body)
            elif suffix == "/run":
                # `batch_uid`, `staging_id` and `run_mode` and NOTHING ELSE
                # (plan §4.1). The tier, the archive names, the taxonomy and
                # the settings all come back from the server's claim under the
                # fleet token: the browser is the only party that can see both
                # the dashboard and this loopback, which is why it dispatches
                # -- not a reason to trust it with the work order.
                #
                # `run_mode` is authoritative and `start_now` is its LEGACY
                # spelling (the plan's first draft, and what a page cached
                # before 2026-08-18 still sends): a bare `start_now: true`
                # means foreground. Read second, so a body carrying both is
                # decided by the newer field rather than by dict order.
                run_mode = str(body.get("run_mode") or "").strip().lower()
                if not run_mode and body.get("start_now"):
                    run_mode = "foreground"
                status, result = ingestor.run(
                    str(body.get("batch_uid") or ""),
                    str(body.get("staging_id") or ""),
                    run_mode,
                )
            else:
                status, result = ingestor.control(str(body.get("action") or ""))
            self._send_json(status, result)
            return True
        return False

    def _ytdl_deps(self) -> Any:
        """The executor's view of this companion.

        app.py builds one at startup and hands it to start() -- it holds the
        LIVE YtDlpManager (whose cached daily check is what makes the
        capability probe answer inside the SPA's 1 s budget) and the verified
        editor identity. The fallback is deliberately capability-less rather
        than clever: a server built without deps (tests pinning the older
        contract, an app that failed to construct one) answers ok:false and the
        fleet downloads on the NAS, which is what it did before 0.8.0.
        """
        deps = getattr(self.server, "ytdl_deps", None)
        if deps is not None:
            return deps
        return ytdl_executor.Deps(getattr(self.server, "ccsync_cfg", None) or {})

    def _dispatch_get(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        # EVERY ingest prefix, not just b-roll's: this read `INGEST_PREFIX`
        # until 2026-08-18, so `GET /music/ingest/capabilities` fell through to
        # the plain 404 below and every music page decided the companion was
        # too old and uploaded through the browser instead. The POST dispatcher
        # always tested the whole set; this one is now the same shape.
        if any(path.startswith(prefix) for prefix in INGEST_PREFIXES):
            if self._dispatch_ingest_get(path, parse_qs(parsed.query)):
                return
            self._send_json(404, {"ok": False, "message": f"not found: {path}"})
            return
        if path == "/status":
            mounts = self.server.companion_config.get("mounts", {})
            self._send_json(200, build_status_response(mounts))
        elif path == "/music/status":
            status, result = music_server.build_status_response()
            self._send_json(status, result)
        elif path == "/ytdl/capabilities":
            # 200 ALWAYS, with the verdict in the body (plan §7): the SPA's
            # probe is one round trip with a 1 s budget, and a non-200 would
            # read to it as "no companion here" -- which is the same fallback,
            # but with nothing in the log to say WHY this machine declined.
            self._send_json(200, ytdl_executor.capabilities(self._ytdl_deps()))
        elif path == "/ytdl/progress":
            # The job id is a query parameter and it is OPTIONAL: with none, the
            # answer is whatever this machine is doing, which is what a page
            # that has just dispatched wants. Unparseable = None, never a 400 --
            # this endpoint is a mirror the SPA may ignore entirely.
            raw = (parse_qs(parsed.query).get("job_id") or [""])[0]
            try:
                job_id = int(raw) if raw else None
            except (TypeError, ValueError):
                job_id = None
            self._send_json(200, ytdl_executor.progress(job_id))
        else:
            self._send_json(404, {"ok": False, "message": f"not found: {path}"})

    def _dispatch_post(self) -> None:
        path = urlparse(self.path).path
        if self._dispatch_ingest_post(path):
            return
        if path == "/music/send":
            body = self._read_json_body("error")
            if body is _REFUSED:
                return
            if body is None or not isinstance(body, dict):
                self._send_json(400, {"ok": False, "error": "invalid JSON body"})
                return
            mounts = self.server.companion_config.get(music_server.MOUNTS_KEY, {})
            status, result = music_server.build_send_response(
                body, mounts, ccsync_cfg=getattr(self.server, "ccsync_cfg", None)
            )
            self._send_json(status, result)
        elif path == "/music/reveal":
            # MUSIC-6 (2026-08-14): the music app's own /api/reveal drove
            # Explorer on the SERVER, which since the dashboard mounted it in a
            # Linux container has been a button that could never work. "Show in
            # folder" is an action on the machine the editor is sitting at --
            # this one. Same body as /music/send ({share, rel_path}, never a
            # path) and the same "error" key, which is what the music page's
            # api() helper reads.
            body = self._read_json_body("error")
            if body is _REFUSED:
                return
            if body is None or not isinstance(body, dict):
                self._send_json(400, {"ok": False, "error": "invalid JSON body"})
                return
            mounts = self.server.companion_config.get(music_server.MOUNTS_KEY, {})
            status, result = music_server.build_reveal_response(body, mounts)
            self._send_json(status, result)
        elif path == "/ytdl/reveal":
            # "message", not "error": the downloader page shows this string in
            # the same toast the b-roll UI uses.
            body = self._read_json_body("message")
            if body is _REFUSED:
                return
            if body is None or not isinstance(body, dict):
                self._send_json(400, {"ok": False, "message": "invalid JSON body"})
                return
            mounts = self.server.companion_config.get(ytdl_server.MOUNTS_KEY, {})
            status, result = ytdl_server.build_reveal_response(body, mounts)
            self._send_json(status, result)
        elif path == "/ytdl/fetch":
            # The other end of reveal's `absent` (CR-32): pull ONE original the
            # server downloaded onto this machine. Same body as /ytdl/reveal --
            # a rel_path under the projects root and nothing else -- and the
            # same "message" key, because the page shows both in the same toast.
            body = self._read_json_body("message")
            if body is _REFUSED:
                return
            if body is None or not isinstance(body, dict):
                self._send_json(400, {"ok": False, "message": "invalid JSON body"})
                return
            mounts = self.server.companion_config.get(ytdl_server.MOUNTS_KEY, {})
            status, result = ytdl_server.build_fetch_response(
                body, mounts, ccsync_cfg=getattr(self.server, "ccsync_cfg", None)
            )
            self._send_json(status, result)
        elif path == "/ytdl/download":
            body = self._read_json_body("message")
            if body is _REFUSED:
                return
            if body is None or not isinstance(body, dict):
                self._send_json(400, {"ok": False, "message": "invalid JSON body"})
                return
            # `job_id` and NOTHING ELSE is read out of this body (plan §8): the
            # destination, the URLs, the quality and the naming template all
            # come from the server under the fleet token. The browser is the
            # only party that can see both the dashboard and this loopback,
            # which is why it dispatches -- not why it should be trusted with
            # the work order. Same principle as /music/send's refusal to accept
            # a path.
            status, result = ytdl_executor.start(body.get("job_id"),
                                                 self._ytdl_deps())
            self._send_json(status, result)
        elif path == "/insert":
            body = self._read_json_body("message")
            if body is _REFUSED:
                return
            if body is None or not isinstance(body, dict):
                self._send_json(400, {"ok": False, "message": "invalid JSON body"})
                return
            mounts = self.server.companion_config.get("mounts", {})
            status, result = build_insert_response(
                body, mounts, ccsync_cfg=getattr(self.server, "ccsync_cfg", None)
            )
            self._send_json(status, result)
        else:
            self._send_json(404, {"ok": False, "message": f"not found: {path}"})

    def log_message(self, fmt: str, *args) -> None:
        # The standalone companion wrote these to stdout. In the windowed
        # (console=False) PyInstaller build sys.stdout is None, so that would
        # raise inside the request handler -- on the request itself, and
        # BaseHTTPRequestHandler also calls this from its error paths.
        log.debug("broll: " + fmt, *args)


class BrollCompanionServer(ThreadingHTTPServer):
    # posix only, and that asymmetry is the point. On Linux/macOS
    # SO_REUSEADDR only skips the TIME_WAIT wait; on Windows it lets a
    # SECOND process bind a port another process is already LISTENING on
    # (verified 2026-08-10). With it set there, a stale standalone
    # broll-companion on 8899 would not fail our bind -- it would quietly
    # split the traffic with us, so half the inserts would go to a dead app
    # and the warning below could never fire.
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def __init__(self, server_address, handler_cls, companion_config: dict,
                 ccsync_cfg: Optional[dict] = None,
                 ytdl_deps: Optional[Any] = None,
                 ingest_deps: Optional[Any] = None,
                 music_ingest_deps: Optional[Any] = None):
        super().__init__(server_address, handler_cls)
        self.companion_config = companion_config
        # The companion's own config.toml dict, for the on-demand archive
        # fetch (remote/remote_root/rclone_path/tuning). None in tests that
        # pin the pre-fetch contract; the fetch simply stays off then.
        self.ccsync_cfg = ccsync_cfg
        # ytdl_executor.Deps: the live yt-dlp sidecar manager, the verified
        # editor identity and this machine's project selection, for the /ytdl
        # download executor. None = no capability (see _ytdl_deps).
        self.ytdl_deps = ytdl_deps
        # broll_ingest.IngestDeps: the orchestrator, the sidecar and the
        # verified editor identity, for the /broll/ingest/* group. Held on the
        # server object exactly like ytdl_deps above, and None on the same
        # terms -- a companion whose orchestrator failed to construct serves
        # every other route unchanged and answers "cannot index here".
        self.ingest_deps = ingest_deps
        # The same thing for the /music/ingest/* group. A SECOND attribute
        # rather than a dict keyed by kind, so a server constructed by a caller
        # that predates music ingest (every test pinning the old signature) is
        # byte-for-byte the object it was, and its music routes answer "not
        # running on this machine" rather than reaching b-roll's orchestrator.
        self.music_ingest_deps = music_ingest_deps

        # Who may drive this listener (loopback_guard.py, 2026-08-17).
        # Computed ONCE, here, rather than per request: it reads the cached
        # site manifest off disk, and a request thread is not the place for
        # that. A companion whose dashboard_url is blank ends up with an EMPTY
        # allow-list, which is the honest answer -- it is pointed at no
        # dashboard, so no page is entitled to drive it; local callers still
        # have the token.
        self.allowed_origins = frozenset()
        self.dev_origins = False
        try:
            self.allowed_origins = loopback_guard.allowed_origins(
                ccsync_cfg, site=site_mod.cached_site()
            )
            self.dev_origins = loopback_guard.dev_origins_enabled(ccsync_cfg)
        except Exception:
            log.warning("broll: could not build the origin allow-list -- "
                        "browser callers will all be refused", exc_info=True)
        # The other way in, for callers that have no Origin to offer. Best
        # effort: a machine that cannot write ~/.ccsync still serves the
        # dashboard's pages perfectly well.
        try:
            loopback_guard.ensure_token()
        except Exception:
            log.warning("broll: could not publish a loopback token",
                        exc_info=True)


def make_server(
    cfg: dict, host: str = HOST, port: int = PORT,
    ccsync_cfg: Optional[dict] = None,
    ytdl_deps: Optional[Any] = None,
    ingest_deps: Optional[Any] = None,
    music_ingest_deps: Optional[Any] = None,
) -> BrollCompanionServer:
    """Bind a loopback-only server. Raises OSError if the port is taken."""
    return BrollCompanionServer((host, port), BrollRequestHandler, cfg,
                                ccsync_cfg, ytdl_deps, ingest_deps,
                                music_ingest_deps)


# -- startup ----------------------------------------------------------------


def is_enabled(ccsync_cfg: dict[str, Any]) -> bool:
    return bool(ccsync_cfg.get("broll_server_enabled", True))


def configured_port(ccsync_cfg: dict[str, Any]) -> int:
    """The port to listen on, never raising on a hand-edited value.

    validate_config deliberately says nothing about this key: a typo in it
    must not join config_problems, which stops every sync lane (DEL-3) over
    a feature that is not sync.
    """
    raw = ccsync_cfg.get("broll_server_port", PORT)
    try:
        port = int(raw)
    except (TypeError, ValueError):
        port = -1
    if not (0 <= port <= 65535):
        log.warning(
            "broll: broll_server_port=%r is not a port number -- using %d", raw, PORT
        )
        return PORT
    return port


def start(ccsync_cfg: dict[str, Any],
          ytdl_deps: Optional[Any] = None,
          ingest_deps: Optional[Any] = None,
          music_ingest_deps: Optional[Any] = None) -> Optional[BrollCompanionServer]:
    """Start the /broll insert server on a daemon thread. Never raises.

    Returns the server (call .shutdown() then .server_close()) or None when
    the feature is off or the port could not be taken. NOTHING here may be
    allowed to stop or delay the sync companion: this is a convenience
    endpoint for one button in a web page, and the app it lives in is the
    one that moves the footage.
    """
    if not is_enabled(ccsync_cfg):
        log.info("broll: Send-to-Resolve server disabled by config")
        return None

    port = configured_port(ccsync_cfg)
    broll_cfg = load_config()
    # Computed BEFORE "mounts" is overwritten: resolve_music_mounts reads the
    # same hand-written table from the same file and adds its own default, so
    # handing it the already-derived b-roll map would carry a "broll" entry
    # into the music route group's namespace.
    music_mounts = music_server.resolve_music_mounts(broll_cfg, ccsync_cfg)
    ytdl_mounts = ytdl_server.resolve_ytdl_mounts(broll_cfg, ccsync_cfg)
    broll_cfg["mounts"] = resolve_mounts(broll_cfg, ccsync_cfg)
    broll_cfg[music_server.MOUNTS_KEY] = music_mounts
    broll_cfg[ytdl_server.MOUNTS_KEY] = ytdl_mounts

    try:
        server = make_server(broll_cfg, HOST, port, ccsync_cfg=ccsync_cfg,
                             ytdl_deps=ytdl_deps, ingest_deps=ingest_deps,
                             music_ingest_deps=music_ingest_deps)
    except OSError as exc:
        log.warning(
            "broll: could not listen on %s:%d (%s) -- \"Send to Resolve\" in the "
            "b-roll web UI will not work on this machine. The usual cause is the "
            "OLD standalone BRoll Companion still running (it is retired and its "
            "only job was this port): quit it from its own tray icon and remove it "
            "from startup, then restart this companion. Everything else -- syncing, "
            "the watcher, the tray -- is unaffected.",
            HOST, port, exc,
        )
        return None
    except Exception:
        log.warning("broll: server failed to start -- continuing without it", exc_info=True)
        return None

    try:
        thread = threading.Thread(
            target=server.serve_forever, name="ccsync-broll", daemon=True
        )
        thread.start()
    except Exception:
        log.warning("broll: could not start the server thread", exc_info=True)
        try:
            server.server_close()
        except Exception:
            pass
        return None

    log.info(
        "broll: Send-to-Resolve listening on http://%s:%d (mounts: %s; "
        "/music/* mounts: %s; /ytdl/* mounts: %s; browser origins allowed: %s)",
        HOST, server.server_address[1], broll_cfg["mounts"], music_mounts,
        ytdl_mounts, sorted(server.allowed_origins) or "NONE -- dashboard_url "
        "is blank, so no web page can drive this companion",
    )
    return server


def stop(server: Optional[BrollCompanionServer]) -> None:
    """Shut the server down and release the port. Never raises."""
    # Downloads first: they are children of this feature, and an rclone
    # still writing into the archive after the tray exits is an orphan
    # nothing supervises. Killing mid-transfer is safe -- rclone writes a
    # .partial and the next poll retries from scratch.
    try:
        broll_fetch.stop_all()
    except Exception:
        log.debug("broll: stopping fetch jobs failed", exc_info=True)
    # ...and a YouTube download running on this machine, for the same reason:
    # a yt-dlp still writing into the project tree after the tray exits is an
    # orphan nothing supervises. Its lease then expires and the server picks up
    # whatever is missing (docs/YTDL_LOCAL_DOWNLOAD.md §3).
    try:
        ytdl_executor.stop_all()
    except Exception:
        log.debug("broll: stopping the ytdl executor failed", exc_info=True)
    # ...and the b-roll ingest orchestrator, for the third time the same
    # reason: an ffmpeg or an rclone still writing into staging after the tray
    # exits is an orphan nothing supervises, and its batch's lease expires so
    # the server (or this machine on restart) picks it up from the last
    # checkpoint. Uploads first, then the crunch: killing the queue while the
    # orchestrator is still enqueueing would leave jobs behind it.
    for attr in ("ingest_deps", "music_ingest_deps"):
        deps = getattr(server, attr, None) if server is not None else None
        ingestor = getattr(deps, "ingestor", None) if deps is not None else None
        if ingestor is None:
            continue
        try:
            ingestor.stop()
        except Exception:
            log.debug("broll: stopping the %s orchestrator failed", attr,
                      exc_info=True)
    if server is None:
        return
    try:
        server.shutdown()
    except Exception:
        log.debug("broll: shutdown() failed", exc_info=True)
    try:
        server.server_close()
    except Exception:
        log.debug("broll: server_close() failed", exc_info=True)
