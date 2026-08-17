"""The YouTube downloader page's "open the folder" action, as a /ytdl route.

    POST /ytdl/reveal   {"rel_path": "<path under the Projects root>"}
    -> {"ok": bool, "message": "<something an editor can read>"}

It hangs off broll_server's listener for exactly the reason the /music/*
group does: 127.0.0.1:8899 has one server, and a second one holding that port
breaks the tray app (CLAUDE.md). Only the dispatch in broll_server and the
mount map built in its start() are shared.

The page is served from the NAS dashboard, so it knows a downloaded clip as
`<project_label>/<rel_path>` --
"2026/FF5/Energy Transition/Youtube/links/Some Clip [abc123].mp4" -- and
NOTHING about where this machine keeps its tree. It therefore sends that
relative path and nothing else: only the companion knows the tree is P:\\ here
and /Volumes/something on a Mac, and a page that could name one local path
could name any local path. Same design, and the same reasoning, as
/music/send's {action, share, rel_path} (music_server.py's header).

The translation and its containment check are music_server.local_path_for's,
not a second copy: the '..'/drive-letter component rules, the "an absolute
rel_path is a contradiction" rule and the resolve()-based final check that
catches a symlink out of the root (MED-11) all live there, and a rule enforced
in one translator and not the other is how a traversal gets served.

Nothing here ever reaches a shell. MUSIC-2 (2026-08-11) was a command
injection in the music web app's own reveal route -- it spawned COMSPEC with
`/c explorer /select,<path>`, and cmd.exe re-parses what it is handed. These
filenames are YouTube titles, where `&` is legal and common, so the argv is a
LIST with the whole path as one element and there is no shell in between.

Added 2026-08-11 with the downloader page's download history.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from . import config as ccsync_config
from . import loopback_guard
from . import music_server
from . import resolve_bridge

log = logging.getLogger("ccsync.ytdl")

# The share this route group has, and where it sits in an editor's tree. Same
# shape as broll_server's BROLL_SHARE/BROLL_ARCHIVE_REL and music_server's
# MUSIC_SHARE: <local_root>/Projects, the root every project rel-path in this
# fleet is written against (fixer.py:153, app.py's remove_project).
PROJECTS_SHARE = "projects"
PROJECTS_REL = ("Projects",)

# This route group's share->root map, a key of its own for the reason
# music_server.MOUNTS_KEY is one: "mounts" is what GET /status hands the b-roll
# settings panel, and the project tree has no business appearing in it.
MOUNTS_KEY = "ytdl_mounts"


# -- mounts -----------------------------------------------------------------


def default_projects_mount(ccsync_cfg: dict[str, Any]) -> Optional[str]:
    """Where the project tree sits on this machine, or None.

    Derived from local_root rather than the canonical "P:\\" prefix for the
    reason default_broll_mount spells out: this string is handed to the
    filesystem and to Explorer/Finder, and on a Mac there is no drive
    namespace to resolve "P:\\" against. Existence is NOT checked -- a tree
    that is not there yet should produce the reveal's own "not on this
    machine" answer rather than "no mount configured", which sends the editor
    to a config file with nothing wrong in it.
    """
    try:
        root = ccsync_config.resolved_local_root(ccsync_cfg or {})
    except Exception:
        return None
    if not str((ccsync_cfg or {}).get("local_root") or "").strip():
        return None
    return str(Path(root, *PROJECTS_REL))


def resolve_ytdl_mounts(
    broll_cfg: dict[str, Any], ccsync_cfg: dict[str, Any]
) -> dict[str, str]:
    """The share->root map for /ytdl/*, with the "projects" default filled in.

    Reads the same ~/.broll-companion.json "mounts" table the other two route
    groups do -- one file, one mount story per machine -- and an explicit entry
    always wins. A blank one counts as absent (same rule, same reason, as
    broll_server.resolve_mounts).
    """
    mounts = dict(broll_cfg.get("mounts") or {})
    if not str(mounts.get(PROJECTS_SHARE) or "").strip():
        derived = default_projects_mount(ccsync_cfg)
        if derived:
            mounts[PROJECTS_SHARE] = derived
    return mounts


def local_path_for(rel_path: Any, mounts: dict) -> str:
    """Translate a rel_path under the Projects root for THIS machine, or raise.

    Deliberately music_server's helper rather than another translator: it is
    the contained one (absolute/drive-prefix/UNC refusal, then the
    root-relative_to check that MED-11 made unskippable), and this route hands
    its answer to a process spawner.
    """
    return music_server.local_path_for(PROJECTS_SHARE, rel_path, mounts)


# -- the file manager -------------------------------------------------------


def reveal_command(target: str, select: bool, platform: Optional[str] = None):
    """The argv that shows `target`, or None where the platform has no answer.

    A LIST, always, with the path as ONE element: no shell parses this, so a
    clip called `rock & roll [abc].mp4` -- a legal filename, and YouTube titles
    are full of them -- is an argument and not a command separator (MUSIC-2).

    `select` asks for the file to be highlighted inside its folder, which both
    desktops support natively; without it the target is opened as a folder.

    A BUNDLE is never opened, only revealed (2026-08-17,
    COMMERCIAL_READINESS.md item 5): `open <x>.app` LAUNCHES the application
    and `open <x>.dmg` mounts the image, so a share containing one turned
    "show me where this is" into "run this". Forcing select on those is not a
    degraded answer -- Finder/Explorer highlights the bundle in its parent,
    which is what the editor asked to see.
    """
    plat = platform if platform is not None else sys.platform
    if loopback_guard.is_bundle_path(target):
        select = True
    if plat.startswith("win"):
        # "/select,<path>" is one token to Explorer -- and stays one token here
        # precisely because nothing re-splits it.
        return ["explorer", f"/select,{target}"] if select else ["explorer", target]
    if plat == "darwin":
        return ["open", "-R", target] if select else ["open", target]
    return None


SELECT_SWITCH = "/select,"

# Why a ledgered clip can be absent here, in the editor's terms. YouTube
# originals sync UP only (2026-08-16); the ones on the NAS that this machine
# never downloaded stay there. Shared by both not-here branches so the two
# never drift into telling different stories.
NOT_HERE_WHY = ("YouTube originals only sync up, so a clip another editor "
                "downloaded, or one the server downloaded, stays on the NAS "
                "(P:\\ on the base rig).")


def windows_command_line(argv: list) -> str:
    """The exact command line Explorer gets, built by hand. Raises ValueError
    for a path containing `"`.

    Explorer parses its own command line instead of following argv rules, and
    Popen(list) quotes any argument containing a space -- which is EVERY path
    in this tree ("Creator Profiles", "Season 1", "Energy Transition"). The
    quote then lands in front of the switch:

        explorer "/select,F:\\...\\Season 1\\clip.mp4"    <- opens Documents
        explorer /select,"F:\\...\\Season 1\\clip.mp4"    <- selects the clip

    Explorer, handed the first form, does not error: it silently opens the
    editor's default folder, so the endpoint reported ok:true and a window
    really appeared -- for every clip, every time (an editor, 2026-08-16; the
    same one-character bug and the same fix as footage-sorter's revealArgs).
    So on Windows the switch is written bare and the quotes wrap the path
    ALONE. The path is refused rather than escaped when it contains `"`:
    Windows filenames cannot, so such a path is a corrupt entry and there is
    no correct thing to hand Explorer for it. Everything else goes through
    list2cmdline one token at a time, which is exactly what Popen would have
    done -- a plain folder open (`explorer "F:\\some folder"`) was never the
    problem, only the switch-plus-path token was.
    """
    exe, *args = [str(a) for a in argv]
    parts = [subprocess.list2cmdline([exe])]
    for arg in args:
        if arg.startswith(SELECT_SWITCH):
            path = arg[len(SELECT_SWITCH):]
            if '"' in path:
                raise ValueError(f"refusing to reveal a path containing a quote: {path!r}")
            parts.append(f'{SELECT_SWITCH}"{path}"')
        else:
            parts.append(subprocess.list2cmdline([arg]))
    return " ".join(parts)


def spawn(argv: list) -> None:
    """Launch the file manager and forget about it. Raises OSError only
    (and ValueError for a Windows path no command line can carry).

    No shell=True, no COMSPEC, nothing that re-reads the argument (MUSIC-2).
    On Windows the command line is built by windows_command_line() and handed
    to CreateProcess as ONE string -- Popen(str) on win32 passes it verbatim,
    no shell involved -- because Popen(list) would re-quote the /select token
    and Explorer would open Documents (see there). The environment is
    sanitized for the reason music_server.call's child is: PYTHONHOME/
    PYTHON3HOME are pinned process-wide at OUR _MEIPASS, which the bootloader
    deletes when we exit, and Explorer/Finder is a process every app the
    editor launches from that window inherits from.
    """
    kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": resolve_bridge.sanitized_child_env(),
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(windows_command_line(argv), **kwargs)
        return
    subprocess.Popen(argv, **kwargs)


# -- the endpoint -----------------------------------------------------------
#
# Same status-code split as the other two route groups: a 400 means the
# REQUEST was malformed (a bug in the page, or something that tried to escape
# the tree), and everything an editor could act on arrives as 200 with
# {"ok": false, "message": ...} so the page can show it inline.


def build_reveal_response(
    body: dict,
    mounts: dict,
    spawner: Optional[Callable[[list], None]] = None,
    platform: Optional[str] = None,
    isfile: Optional[Callable[[str], bool]] = None,
    isdir: Optional[Callable[[str], bool]] = None,
) -> tuple[int, dict]:
    """POST /ytdl/reveal. Returns (http_status, json_body).

    Body: {"rel_path": "2026/FF5/Energy Transition/Youtube/links/clip.mp4"}.
    """
    # Deferred: broll_server imports this module to dispatch its routes, so a
    # module-level import would be a cycle. sys.modules makes it free.
    from . import broll_server
    from . import site as site_mod

    # The whole /ytdl route group is off unless the customer's site manifest
    # turned the downloader on (2026-08-17, COMMERCIAL_READINESS.md item 2).
    # Reveal is the harmless-looking one -- it only opens a folder -- but a
    # feature that is off should have no surface at all, and a page that can
    # still make the companion open Explorer is surface. The SITE flag alone,
    # not youtube_enabled(): an editor who opted their own machine out of
    # executing downloads (`ytdl_local_downloads = false`) still browses the
    # clips the server fetched for them.
    if not site_mod.feature_enabled("youtube_download"):
        return 200, {"ok": False,
                     "message": "the YouTube downloader is not enabled for "
                                "this site"}

    rel_path = body.get("rel_path")
    try:
        local = local_path_for(rel_path, mounts)
    except broll_server.PathTraversalError as exc:
        return 400, {"ok": False, "message": str(exc)}
    except broll_server.MountNotConfiguredError as exc:
        return 200, {"ok": False, "message": str(exc)}

    file_check = isfile if isfile is not None else os.path.isfile
    dir_check = isdir if isdir is not None else os.path.isdir

    path = Path(local)
    folder = path.parent
    if file_check(str(path)):
        target, select = str(path), True
        message = f"Showing {path.name} in {folder}"
    elif dir_check(str(folder)):
        # The row is in the dashboard's ledger and the file is not here. Since
        # 2026-08-16 no lane brings YouTube ORIGINALS down (rclone_lane.
        # build_filter_rules_down): a clip this machine did not download
        # itself -- another editor's, or one that fell back to the server
        # path -- lives on the NAS only, so "still syncing" is no longer the
        # likely story and the message must not promise it. The folder is
        # still the useful answer: it is what the editor clicked to look at.
        target, select = str(folder), False
        message = (f"{path.name} is not on this machine — opened {folder} instead. "
                   f"{NOT_HERE_WHY}")
    else:
        # Nothing to point a file manager at. Spawning "explorer <missing>" here
        # would open the editor's Documents folder and look like a bug.
        return 200, {
            "ok": False,
            "message": f"{path} is not on this machine. {NOT_HERE_WHY}",
        }

    argv = reveal_command(target, select, platform)
    if argv is None:
        return 200, {
            "ok": False,
            "message": f"opening a folder is only supported on Windows and macOS "
                       f"— the file is at {target}",
        }

    run = spawner if spawner is not None else spawn
    try:
        run(argv)
    except (OSError, ValueError) as exc:
        # ValueError: windows_command_line refused a `"` in the path.
        log.warning("ytdl: could not open the file manager (%s)", exc)
        return 200, {"ok": False, "message": f"could not open the file manager: {exc}"}
    return 200, {"ok": True, "message": message}
