"""The music library's "Send to Resolve" actions, as /music/* routes.

REHOMED from `music/web/musicweb/resolve_link.py` (port step 8, 2026-08-10).
The routes themselves hang off broll_server's loopback listener -- this module
deliberately opens NO socket. 127.0.0.1:8899 is already taken by that server
and CLAUDE.md is explicit that a second process (or a second server) holding
that port breaks the tray app, so the music actions are a route GROUP on the
one listener, not a listener of their own.

Why the move at all: `resolve_link.py` handed the worker an ABSOLUTE path,
which is only meaningful when the web app and Resolve are the same machine.
They are not over Tailscale -- the server's
`W:\\Creators_Club\\Assets\\Music\\foo.wav` is the editor's
`P:\\Assets\\Music\\foo.wav` -- so the loopback API takes (share, rel_path)
and translates it HERE, on the machine Resolve is actually running on, using
the same broll_server.translate_path the b-roll button has used since the
standalone companion. A pair that would escape the share root raises; nothing
here serves a path outside it.

Every call still runs the Resolve half in a CHILD PROCESS with a hard timeout
(see music_worker): the scripting API blocks indefinitely when Resolve is
modal, busy, or sitting on the Project Manager window, and this one runs on a
request thread of the app that moves everyone's footage.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from . import config as ccsync_config
from . import music_worker
from . import resolve_bridge

log = logging.getLogger("ccsync.music")

# The three the SPEC defines, and nothing else: "status" is a GET of its own
# and must not be reachable through the write route.
ACTIONS = ("bin", "under", "insert")

# Same 90s as musicweb/resolve_link.py. Long on purpose -- an ImportMedia of a
# wav off a cold share is slow, and the timeout exists to bound a HANG, not to
# be a responsiveness budget.
TIMEOUT = 90

# The one share this library has (music/web/musicweb/config.py's SHARE), and
# where it sits in an editor's tree. Same shape as broll_server's BROLL_SHARE
# /BROLL_ARCHIVE_REL: P:\Assets\Music next to P:\Assets\B-roll Archive.
MUSIC_SHARE = "music"
MUSIC_LIBRARY_REL = ("Assets", "Music")

# Where the server keeps this route group's share->root map. A KEY OF ITS OWN,
# not an addition to "mounts": that dict is what GET /status hands the b-roll
# settings panel, and the music library has no business appearing in it.
MOUNTS_KEY = "music_mounts"

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


# -- mounts -----------------------------------------------------------------


def default_music_mount(ccsync_cfg: dict[str, Any]) -> Optional[str]:
    """Where the music library sits in this machine's tree, or None.

    Derived from local_root for the same reason default_broll_mount is: this
    string is handed to os.path.isfile and to Resolve's ImportMedia, and on a
    Mac there is no drive namespace to resolve "P:\\" against. Existence is
    NOT checked -- a library that hasn't synced yet should produce the "is the
    share mounted?" message rather than "no mount configured", which sends the
    editor to a config file with nothing wrong in it.
    """
    try:
        root = ccsync_config.resolved_local_root(ccsync_cfg or {})
    except Exception:
        return None
    if not str((ccsync_cfg or {}).get("local_root") or "").strip():
        return None
    return str(Path(root, *MUSIC_LIBRARY_REL))


def resolve_music_mounts(
    broll_cfg: dict[str, Any], ccsync_cfg: dict[str, Any]
) -> dict[str, str]:
    """The share->root map for /music/*, with the "music" default filled in.

    Reads the same ~/.broll-companion.json "mounts" table the b-roll routes
    use -- editors have exactly one of those files and one mount story per
    machine -- and an explicit entry always wins. A blank one counts as absent
    (broll_server.resolve_mounts has the same rule and the same reason).
    """
    mounts = dict(broll_cfg.get("mounts") or {})
    if not str(mounts.get(MUSIC_SHARE) or "").strip():
        derived = default_music_mount(ccsync_cfg)
        if derived:
            mounts[MUSIC_SHARE] = derived
    return mounts


# -- (share, rel_path) -> a local absolute path ------------------------------


def local_path_for(share: str, rel_path: str, mounts: dict) -> str:
    """Translate a (share, rel_path) pair for THIS machine, or raise.

    broll_server.translate_path does the work -- the '..' and drive-letter
    component rules are its, not a second copy -- with the two extra guards
    musicweb.config.safe_join has: an ABSOLUTE rel_path is a contradiction
    (joining would hand back a path with nothing to do with the share), and a
    final containment check catches anything -- a symlink, a component none of
    these rules anticipated -- that still resolves outside the root.
    """
    # Deferred: broll_server imports THIS module to dispatch its routes, so a
    # module-level import here would be a cycle. sys.modules makes it free.
    from . import broll_server

    norm = str(rel_path or "").replace("\\", "/")
    if norm.startswith("/") or _DRIVE_RE.match(norm):
        raise broll_server.PathTraversalError(
            f"rel_path must be relative, got {rel_path!r}"
        )

    # The ROOT comes back with the path: it may have come from the /Volumes
    # probe rather than the mounts table, and reading `mounts[share]` again
    # here skipped this check entirely for a Mac editor with /Volumes/music
    # mounted and no config entry -- the documented case, and the one where a
    # symlink out of the volume was then followed (MED-11, 2026-08-11).
    root, local = broll_server.translate_path_with_root(share, rel_path, mounts)

    if root:
        try:
            Path(local).resolve(strict=False).relative_to(
                Path(root).resolve(strict=False)
            )
        except ValueError:
            raise broll_server.PathTraversalError(
                f"rel_path escapes the share root: {rel_path!r}"
            ) from None
    return local


# -- the killable child ------------------------------------------------------


def worker_command(
    request_json: str,
    executable: Optional[str] = None,
    frozen: Optional[bool] = None,
) -> list[str]:
    """The argv of a process that performs one Resolve action and exits.

    In a frozen build `sys.executable` is the COMPANION, not an interpreter --
    the same trap rclone_lane.watch_probe_command is written around -- so the
    child is this exe re-entered with music_worker.WORKER_FLAG, which
    app.run() answers before it takes the single-instance lock or starts a
    tray. From source there is a real interpreter, and `-m` keeps the worker
    importable as part of its package (its `from . import resolve_bridge` is
    what bootstraps the scripting environment on both platforms).
    """
    exe = executable or sys.executable
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    if is_frozen:
        return [exe, music_worker.WORKER_FLAG, request_json]
    return [exe, "-m", "ccsync_companion.music_worker", request_json]


def call(
    action: str,
    timeout: int = TIMEOUT,
    runner: Optional[Callable[..., Any]] = None,
    **kw: Any,
) -> dict:
    """Run one action in a child process. Returns the worker's dict; never raises.

    `runner` defaults to subprocess.run and exists so tests can drive the
    argv/timeout/decoding contract without a Resolve.
    """
    req = dict(kw)
    req["action"] = action
    argv = worker_command(json.dumps(req, ensure_ascii=False))
    run = runner if runner is not None else subprocess.run

    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        # PYTHONHOME/PYTHON3HOME are pinned process-wide at OUR _MEIPASS,
        # which the bootloader deletes when we exit; the child re-pins to its
        # own (resolve_bridge CORE-M6).
        "env": resolve_bridge.sanitized_child_env(),
    }
    if sys.platform == "win32":
        # console=False build: without this the child flashes a console window
        # on every button press.
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        proc = run(argv, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired:
        log.warning("music: the Resolve worker timed out after %ds", timeout)
        return {"ok": False, "error":
                "Resolve did not respond within %ds. It is usually busy, "
                "showing a dialog, or on the Project Manager window." % timeout}
    except OSError as exc:
        return {"ok": False,
                "error": "could not start the Resolve worker: %s" % exc}

    out = _decode(getattr(proc, "stdout", None)).strip()
    if not out:
        err = _decode(getattr(proc, "stderr", None)).strip()
        return {"ok": False,
                "error": err.splitlines()[-1] if err else
                "the Resolve worker produced no output (exit %s)"
                % getattr(proc, "returncode", "?")}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"ok": False, "error": out[:400]}


def _decode(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


# -- the endpoints -----------------------------------------------------------
#
# Same status-code split as broll_server's /insert, and for the same reason:
# the music web UI's api() helper THROWS on a non-2xx and shows only
# "<path> -> <status>", so anything an editor could act on has to arrive as
# 200 with {"ok": false, "error": ...}. A 4xx means the request itself was
# malformed -- which is a bug in the page, not a state the editor can fix.


def build_status_response(caller: Optional[Callable[..., dict]] = None) -> tuple[int, dict]:
    """GET /music/status -> the worker's status dict, verbatim.

    {"ok": true, "project", "timeline", "fps", "audio_tracks", "timecode"} or
    {"ok": false, "error"} -- the shape music/web/static/app.js's
    refreshResolveStatus() already reads.
    """
    run = caller if caller is not None else call
    return 200, run("status")


def build_reveal_response(
    body: dict,
    mounts: dict,
    spawner: Optional[Callable[[list], None]] = None,
    platform: Optional[str] = None,
    isfile: Optional[Callable[[str], bool]] = None,
    isdir: Optional[Callable[[str], bool]] = None,
) -> tuple[int, dict]:
    """POST /music/reveal. Returns (http_status, json_body).

    Body: {"share": "music", "rel_path": "Cinematic/Slow Build.wav"} -- the
    same pair /music/send takes and for the same reason: the page is served
    from the NAS and only this machine knows where the library is on it.

    MUSIC-6 (2026-08-14): the music web app's own /api/reveal drove Explorer
    ON THE SERVER. That was already the wrong machine when the app ran beside
    the editor, and since the dashboard mounted it in a Linux container it is
    permanently dead -- an editor clicking "show in folder" was asking the NAS
    to open a window nobody would ever see. Revealing a file is an action on
    the machine the editor is sitting at, which is what the loopback is, so
    the route lives here beside /music/send.

    The file manager half is ytdl_server's -- reveal_command's shell-free argv
    list (MUSIC-2, 2026-08-11: cmd.exe re-parsed `&` out of a filename) and
    its sanitized-env spawn -- rather than a second copy. One reveal
    implementation for both route groups; only the message wording and the
    `error` key differ, and both of those belong to the page that reads them.
    """
    # Deferred for the same reason local_path_for's import is: broll_server
    # imports THIS module to dispatch its routes, and ytdl_server imports it
    # too, so either at module level would be a cycle. sys.modules makes it
    # free after the first call.
    from . import broll_server
    from . import ytdl_server

    try:
        local = local_path_for(body.get("share"), body.get("rel_path"), mounts)
    except broll_server.PathTraversalError as exc:
        return 400, {"ok": False, "error": str(exc)}
    except broll_server.MountNotConfiguredError as exc:
        return 200, {"ok": False, "error": str(exc)}

    file_check = isfile if isfile is not None else os.path.isfile
    dir_check = isdir if isdir is not None else os.path.isdir

    path = Path(local)
    folder = path.parent
    if file_check(str(path)):
        target, select = str(path), True
        message = f"Showing {path.name} in {folder}"
    elif dir_check(str(folder)):
        # The track is in the index and the file is not here yet: still
        # syncing, or the share is only half-mounted. The folder is the useful
        # answer, and it is what the editor clicked the row to look at -- but
        # SAY SO. An editor on this branch is usually asking "why isn't my
        # track here", and "Showing X in Y" claims a file they can see. Word
        # for word ytdl_server's line: two route groups on one listener, one
        # language.
        target, select = str(folder), False
        message = f"{path.name} is not there — opened {folder} instead"
    else:
        # Nothing to point a file manager at. Spawning "explorer <missing>"
        # here opens the editor's Documents folder and looks like a bug.
        return 200, {
            "ok": False,
            "error": f"{path} is not on this machine — is the share mounted?",
        }

    argv = ytdl_server.reveal_command(target, select, platform)
    if argv is None:
        return 200, {
            "ok": False,
            "error": f"opening a folder is only supported on Windows and macOS "
                     f"— the file is at {target}",
        }

    run = spawner if spawner is not None else ytdl_server.spawn
    try:
        run(argv)
    except OSError as exc:
        log.warning("music: could not open the file manager (%s)", exc)
        return 200, {"ok": False, "error": f"could not open the file manager: {exc}"}
    return 200, {"ok": True, "message": message}


def build_send_response(
    body: dict, mounts: dict, caller: Optional[Callable[..., dict]] = None
) -> tuple[int, dict]:
    """POST /music/send. Returns (http_status, json_body).

    Body: {"action": "bin"|"under"|"insert", "share": ..., "rel_path": ...,
           "track": <optional int>}
    """
    run = caller if caller is not None else call

    action = body.get("action")
    if action not in ACTIONS:
        return 400, {"ok": False, "error": f"unknown action {action!r}"}

    share = body.get("share")
    rel_path = body.get("rel_path")

    # Deferred for the same reason local_path_for's is.
    from . import broll_server

    try:
        local_path_str = local_path_for(share, rel_path, mounts)
    except broll_server.PathTraversalError as exc:
        return 400, {"ok": False, "error": str(exc)}
    except broll_server.MountNotConfiguredError as exc:
        return 200, {"ok": False, "error": str(exc)}

    if not os.path.isfile(local_path_str):
        return 200, {
            "ok": False,
            "error": f"file not found at {local_path_str} — is the share mounted?",
        }

    kw: dict[str, Any] = {"path": local_path_str}
    track = body.get("track")
    if track:
        try:
            kw["track"] = int(track)
        except (TypeError, ValueError):
            return 400, {"ok": False, "error": f"track must be a number, got {track!r}"}

    return 200, run(action, **kw)
