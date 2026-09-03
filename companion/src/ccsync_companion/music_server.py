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
import subprocess
import sys
import threading
import time
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

    Since 2026-08-17 (COMMERCIAL_READINESS.md item 5) the implementation is
    broll_server.contained_local_path -- the same two guards, moved so that
    /insert gets them too rather than only the routes that grew them here.
    This name stays because three modules and their tests call it.
    """
    # Deferred: broll_server imports THIS module to dispatch its routes, so a
    # module-level import here would be a cycle. sys.modules makes it free.
    from . import broll_server

    return broll_server.contained_local_path(share, rel_path, mounts)


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


# -- the status probes ------------------------------------------------------
#
# GET /status and GET /music/status each SPAWN a child (`call` above re-enters
# this exe as a Resolve worker), and a GET is deliberately exempt from the
# token and from the Origin rule when no Origin is sent -- a subresource load
# (<img src>, an iframe) sends none, so any page in any browser can ask for
# one. Unbounded that is hundreds of copies of the frozen companion at ~80 MB
# each, all knocking on fuscript's door (CR-68), because an ad frame said so
# (bug-hunt-2026-09-03 comp-broll-music-3). The answer these routes carry is a
# yes/no a settings dot draws, so N requests inside a few seconds may share
# ONE child: fresh answers are served from the slot, and the losers of the
# race wait for the winner's rather than starting their own.

PROBE_TTL_S = 3.0


class _ProbeSlot:
    __slots__ = ("lock", "deadline", "value")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.deadline = 0.0
        self.value: Optional[dict] = None


_probe_guard = threading.Lock()
_probe_slots: dict[Any, _ProbeSlot] = {}


def cached_probe(run: Callable[..., dict], action: str,
                 ttl: Optional[float] = None, **kw: Any) -> dict:
    """`run(action, **kw)`, at most once per `ttl` seconds and never twice at
    the same time.

    Keyed on the CALLER as well as the action: a caller that supplied its own
    probe function must never be handed an answer produced by someone else's
    (and it is what keeps two tests, each with its own stub, out of each
    other's results).
    """
    ttl = PROBE_TTL_S if ttl is None else ttl
    key = (run, action)
    with _probe_guard:
        slot = _probe_slots.get(key)
        if slot is None:
            if len(_probe_slots) > 16:
                # Production has one key. A long-lived process that somehow
                # grew more must not accumulate them for ever.
                now = time.monotonic()
                for stale_key, stale in list(_probe_slots.items()):
                    if stale.deadline <= now and not stale.lock.locked():
                        _probe_slots.pop(stale_key, None)
            slot = _probe_slots[key] = _ProbeSlot()
    if slot.value is not None and time.monotonic() < slot.deadline:
        return slot.value
    with slot.lock:
        if slot.value is not None and time.monotonic() < slot.deadline:
            # The winner filled the slot while this thread queued: the whole
            # point, N requests costing one child.
            return slot.value
        result = run(action, **kw)
        slot.value = result
        slot.deadline = time.monotonic() + ttl
        return result


def reset_probe_cache() -> None:
    """Forget every memoised probe, so the next request spawns a child."""
    with _probe_guard:
        _probe_slots.clear()


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
    return 200, cached_probe(run, "status")


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
        message = f"{path.name} is not there - opened {folder} instead"
    else:
        # Nothing to point a file manager at. Spawning "explorer <missing>"
        # here opens the editor's Documents folder and looks like a bug.
        return 200, {
            "ok": False,
            "error": f"{path} is not on this machine - is the share mounted?",
        }

    argv = ytdl_server.reveal_command(target, select, platform)
    if argv is None:
        return 200, {
            "ok": False,
            "error": f"opening a folder is only supported on Windows and macOS. "
                     f"The file is at {target}",
        }

    run = spawner if spawner is not None else ytdl_server.spawn
    try:
        run(argv)
    except (OSError, ValueError) as exc:
        # ValueError: windows_command_line refused a `"` in the path. The
        # exception text (a spawn errno, a full path, a quoted command line)
        # stays in the log -- the page gets the fact, not the internals
        # (2026-08-17, COMMERCIAL_READINESS.md L-tier "error detail leaks").
        log.warning("music: could not open the file manager (%s)", exc)
        return 200, {"ok": False,
                     "error": "could not open the file manager -- see the "
                              "companion's log"}
    return 200, {"ok": True, "message": message}


def fetchable_from_nas(share: str, mounts: dict, ccsync_cfg: Optional[dict]) -> bool:
    """Is a missing track one the companion should pull down itself?

    broll_server._fetchable_from_nas's rule, for the music share: only when
    the effective mount is the DERIVED default under local_root (an explicit
    ~/.broll-companion.json entry means the editor pointed the share
    somewhere deliberate, and rclone writing into it behind their back is not
    our call), and never on a base rig, whose local_root IS the NAS share.
    """
    if not ccsync_cfg or share != MUSIC_SHARE:
        return False
    if str(ccsync_cfg.get("mode", "editor")).strip().lower() == "base":
        return False
    derived = default_music_mount(ccsync_cfg)
    root = (mounts or {}).get(MUSIC_SHARE)
    if not derived or not isinstance(root, str):
        return False
    return os.path.normcase(os.path.normpath(root)) == os.path.normcase(
        os.path.normpath(derived)
    )


def build_send_response(
    body: dict, mounts: dict, caller: Optional[Callable[..., dict]] = None,
    ccsync_cfg: Optional[dict] = None,
    fetcher: Optional[Callable[..., dict]] = None,
) -> tuple[int, dict]:
    """POST /music/send. Returns (http_status, json_body).

    Body: {"action": "bin"|"under"|"insert", "share": ..., "rel_path": ...,
           "track": <optional int>}

    A missing track is no longer terminal (2026-08-16): the music library is
    not a synced folder any more than the b-roll archive is, so on every
    remote editor's machine "+ Resolve" answered "file not found -- is the
    share mounted?" and stopped (an editor, 2026-08-16) -- the exact dead end
    b-roll's /insert escaped on 2026-08-11. Same escape here: when the share
    is the library at its derived place in the tree and this machine has a
    working rclone remote, the companion pulls that ONE track down and
    answers {"ok": false, "state": "downloading", "progress": {...}}; the web
    UI re-POSTs the same body every ~1.5 s, and the poll that finds the file
    in place falls through to the ordinary send. `ccsync_cfg` is None only
    for callers that predate the feature (tests pinning the old contract);
    the live handler always passes it. `fetcher` is broll_fetch.poll_fetch's
    test seam. The error key stays "error" -- that is this route's contract
    with the music page (b-roll's is "message").
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
        if not fetchable_from_nas(share, mounts, ccsync_cfg):
            return 200, {
                "ok": False,
                "error": f"file not found at {local_path_str} - is the share mounted?",
            }
        # Deferred for the reason local_path_for's is; the vetted components
        # re-joined with forward slashes, never the raw client string.
        from . import broll_fetch

        # The tree has to be mounted, and the destination inside it, before
        # anything downloads into it (2026-08-17, COMMERCIAL_READINESS.md
        # item 5): rclone against an absent macOS root does not fail, it
        # fills the boot disk (root_guard.py).
        refusal = broll_fetch.fetch_refusal(ccsync_cfg, local_path_str)
        if refusal:
            return 200, {"ok": False, "error": refusal}
        clean_rel = "/".join(broll_server._split_components(rel_path))
        fetch = (fetcher if fetcher is not None else broll_fetch.poll_fetch)(
            ccsync_cfg, clean_rel, local_path_str,
            remote_rel=broll_fetch.MUSIC_REMOTE_REL,
        )
        state = fetch.get("state")
        if state == broll_fetch.STATE_DOWNLOADING:
            progress = fetch.get("progress") or {}
            percent = progress.get("percent")
            message = (
                f"syncing the track to this machine: {percent}%"
                if isinstance(percent, int)
                else "syncing the track to this machine…"
            )
            return 200, {"ok": False, "state": "downloading",
                         "error": message, "progress": progress}
        if state != broll_fetch.STATE_DONE:
            return 200, {
                "ok": False,
                "error": "couldn't sync the track from the NAS: "
                         f"{fetch.get('message') or 'the download failed'}",
            }
        if not os.path.isfile(local_path_str):
            # "done" is only reported after an isfile() inside the job, so
            # reaching here means the file vanished in between.
            return 200, {
                "ok": False,
                "error": f"file not found at {local_path_str} - is the share mounted?",
            }

    kw: dict[str, Any] = {"path": local_path_str}
    track = body.get("track")
    if track:
        try:
            kw["track"] = int(track)
        except (TypeError, ValueError):
            return 400, {"ok": False, "error": f"track must be a number, got {track!r}"}

    return 200, run(action, **kw)
