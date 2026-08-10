"""Loopback HTTP server for the b-roll library's "Send to Resolve" button.

Implements the "Companion API contract" section of broll/SPEC.md exactly:
  GET  /status
  POST /insert
plus OPTIONS preflight handling and permissive CORS (loopback-only bind
makes that safe -- see that spec).

Since port step 8 (2026-08-10) it also carries the MUSIC library's
"Send to Resolve" actions as a route group:
  GET  /music/status
  POST /music/send
They are here, on this listener, rather than on one of their own precisely
because this process already owns 8899 and a second server holding it breaks
the tray app (CLAUDE.md). The music half's logic lives in music_server.py;
only the dispatch below and the mount map in start() are shared, and the
b-roll contract above is untouched by it.

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
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from . import config as ccsync_config
from . import music_server
from . import resolve_bridge

log = logging.getLogger("ccsync.broll")

HOST = "127.0.0.1"
PORT = 8899

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

README_SNIPPET = """B-roll Send-to-Resolve config — {config_path}

Read by the CC Sync companion (the tray app), which is what "Send to Resolve"
in the b-roll web UI talks to. The separate BRoll Companion this file was
originally written for is retired — do not run it; it would hold port 8899
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

      The "music" share is read from this same table (the music library's
      "Send to Resolve" buttons talk to the same companion, on the same
      port) and needs no entry either: it defaults to
      <local_root>/Assets/Music.

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
    """Raised when rel_path attempts to escape the mount root (any '..' part)."""


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


def probe_darwin_mount(
    share: str, isdir: Optional[Callable[[str], bool]] = None
) -> Optional[str]:
    """Look for /Volumes/<share>, -1, -2 (Finder's collision-suffix convention).

    Returns the first candidate that exists as a directory, or None.

    `isdir` defaults to None (resolved to os.path.isdir at call time, not at
    import time) so tests can either monkeypatch os.path.isdir directly or
    inject a fake callable explicitly.
    """
    check = isdir if isdir is not None else os.path.isdir
    for candidate in (f"/Volumes/{share}", f"/Volumes/{share}-1", f"/Volumes/{share}-2"):
        if check(candidate):
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
    plat = platform if platform is not None else sys.platform

    if not rel_path or not rel_path.strip():
        raise PathTraversalError("empty rel_path")

    parts = _split_components(rel_path)
    _validate_components(parts)
    if not parts:
        raise PathTraversalError("empty rel_path after normalization")

    root = mounts.get(share)
    if root is None and plat == "darwin":
        root = probe_darwin_mount(share, isdir=isdir)
    if root is None:
        raise MountNotConfiguredError(f"no mount configured for share '{share}'")

    if plat.startswith("win"):
        # Normalize the configured root's separators, then append components
        # with backslashes. Leaves drive letters ("Y:\...") intact.
        root_norm = root.replace("/", "\\").rstrip("\\")
        return root_norm + "\\" + "\\".join(parts)

    # macOS/posix: normalize to forward slashes, preserve a leading '/'.
    root_norm = root.replace("\\", "/").rstrip("/")
    if root_norm == "":
        root_norm = "/"
    return root_norm + "/" + "/".join(parts)


# -- the two endpoints ------------------------------------------------------


def _json_bytes(obj: dict) -> bytes:
    return json.dumps(obj).encode("utf-8")


def build_status_response(mounts: dict) -> dict:
    """GET /status body, per SPEC.md: {ok, resolve_connected, mounts, version}.

    `version` is this companion's version now that the standalone one is
    retired -- the b-roll settings panel only displays it, and the number an
    editor reads off it should be the number their tray app reports.
    """
    return {
        "ok": True,
        "resolve_connected": resolve_bridge.try_connect(),
        "mounts": mounts,
        "version": ccsync_config.VERSION,
    }


def build_insert_response(body: dict, mounts: dict) -> tuple[int, dict]:
    """POST /insert logic. Returns (http_status, json_body).

    Path traversal is the one failure that gets a non-200 HTTP status (400);
    every other expected failure path returns 200 with {"ok": false, ...} so
    the web UI can show the message inline.
    """
    share = body.get("share")
    rel_path = body.get("rel_path")
    in_frame = body.get("in_frame")
    out_frame = body.get("out_frame")
    mode = body.get("mode", "append")

    if mode != "append":
        # mode "playhead" is reserved; anything else isn't a defined v1 mode.
        return 200, {"ok": False, "message": "not implemented yet"}

    if not isinstance(in_frame, int) or not isinstance(out_frame, int):
        return 400, {"ok": False, "message": "in_frame and out_frame must be integers"}
    if out_frame <= in_frame:
        return 200, {"ok": False, "message": "out point must be after in point"}

    try:
        local_path_str = translate_path(share, rel_path, mounts)
    except PathTraversalError as exc:
        return 400, {"ok": False, "message": str(exc)}
    except MountNotConfiguredError as exc:
        return 200, {"ok": False, "message": str(exc)}

    local_path = Path(local_path_str)
    if not local_path.is_file():
        return 200, {
            "ok": False,
            "message": f"file not found at {local_path} — is the share mounted?",
        }

    result = resolve_bridge.perform_insert(str(local_path), in_frame, out_frame)
    return 200, result


class BrollRequestHandler(BaseHTTPRequestHandler):
    server_version = f"CCSyncCompanion/{ccsync_config.VERSION}"

    def _set_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        # Private Network Access. The b-roll UI is served from the cc_sync
        # dashboard, so the page comes from a tailnet address and calls
        # loopback — exactly the public-to-private direction Chromium is
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

    def do_OPTIONS(self) -> None:  # CORS preflight
        self.send_response(204)
        self._set_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_json_body(self) -> Any:
        """The request body as parsed JSON, or None if it isn't JSON.

        Only the /music routes use this; /insert keeps its own inline copy so
        absorbing the music group changed nothing on the b-roll path.
        """
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/status":
            mounts = self.server.companion_config.get("mounts", {})
            self._send_json(200, build_status_response(mounts))
        elif path == "/music/status":
            status, result = music_server.build_status_response()
            self._send_json(status, result)
        else:
            self._send_json(404, {"ok": False, "message": f"not found: {path}"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/music/send":
            body = self._read_json_body()
            if body is None or not isinstance(body, dict):
                self._send_json(400, {"ok": False, "error": "invalid JSON body"})
                return
            mounts = self.server.companion_config.get(music_server.MOUNTS_KEY, {})
            status, result = music_server.build_send_response(body, mounts)
            self._send_json(status, result)
        elif path == "/insert":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {"ok": False, "message": "invalid JSON body"})
                return
            mounts = self.server.companion_config.get("mounts", {})
            status, result = build_insert_response(body, mounts)
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

    def __init__(self, server_address, handler_cls, companion_config: dict):
        super().__init__(server_address, handler_cls)
        self.companion_config = companion_config


def make_server(
    cfg: dict, host: str = HOST, port: int = PORT
) -> BrollCompanionServer:
    """Bind a loopback-only server. Raises OSError if the port is taken."""
    return BrollCompanionServer((host, port), BrollRequestHandler, cfg)


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


def start(ccsync_cfg: dict[str, Any]) -> Optional[BrollCompanionServer]:
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
    broll_cfg["mounts"] = resolve_mounts(broll_cfg, ccsync_cfg)
    broll_cfg[music_server.MOUNTS_KEY] = music_mounts

    try:
        server = make_server(broll_cfg, HOST, port)
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
        "/music/* mounts: %s)",
        HOST, server.server_address[1], broll_cfg["mounts"], music_mounts,
    )
    return server


def stop(server: Optional[BrollCompanionServer]) -> None:
    """Shut the server down and release the port. Never raises."""
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
