"""All DaVinci Resolve scripting-API interaction lives here.

Nothing in this module ever crashes the caller: every public function
returns None / False / a friendly {"ok": False, "message": ...} dict on any
failure (Resolve not running, no project, no timeline, import failure, etc).

We lazy-import DaVinciResolveScript and lazy-connect (scriptapp("Resolve"))
on every call rather than caching a connection, since Resolve may not be
running yet, may be restarted, etc.

Forked near-verbatim from E:\\Projects\\broll-platform\\companion\\src\\broll_companion\\resolve_bridge.py
(env bootstrap + never-raise connect + _norm_path) — see that module's
docstring for the same rationale. Everything below `_norm_path` is new:
timeline-item enumeration + ReplaceClip-based relinking for the watcher and
fixer.
"""

from __future__ import annotations

import logging
import os
import platform
import sys
import threading
from typing import Any, Optional

from . import ui_state

log = logging.getLogger("ccsync.resolve")

# Serializes EVERY call into the Resolve C extension.
#
# Four threads call this module concurrently: the timeline watcher (every
# poll_interval), the media-tree refresh thread (every 120 s), tray daemon
# threads (Scan whole project / Copy this project's media in), and the
# FIX-ALL worker (replace_clip per row). fusionscript.dll is not documented
# as thread-safe and this module's own _pin_frozen_python3_home docstring
# records it faulting 0xc0000005 -- which takes the whole windowed companion
# down with zero log output. Reentrant because the public functions call
# connect() internally (AUDIT_2 CORE-H4).
_API_LOCK = threading.RLock()

# Set process-wide by _pin_frozen_python3_home() so fusionscript.dll loads
# OUR python3.dll. They must not be inherited by children: they point at the
# outgoing process's _MEI... extraction dir, which the PyInstaller bootloader
# deletes seconds later -- and the self-upgrade spawn, every rclone child,
# os.startfile() and webbrowser.open() all inherit them (AUDIT_2 CORE-M6).
PINNED_PYTHON_ENV_VARS = ("PYTHONHOME", "PYTHON3HOME")


def sanitized_child_env(base: Optional[dict] = None) -> dict:
    """A copy of the environment safe to hand to a child process."""
    env = dict(os.environ if base is None else base)
    for name in PINNED_PYTHON_ENV_VARS:
        env.pop(name, None)
    return env


def _default_modules_dir() -> Optional[str]:
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return os.path.join(
            base,
            "Blackmagic Design",
            "DaVinci Resolve",
            "Support",
            "Developer",
            "Scripting",
            "Modules",
        )
    if system == "Darwin":
        return "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Scripting/Modules"
    return None


def _default_script_lib() -> Optional[str]:
    system = platform.system()
    if system == "Windows":
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        return os.path.join(pf, "Blackmagic Design", "DaVinci Resolve", "fusionscript.dll")
    if system == "Darwin":
        return (
            "/Applications/DaVinci Resolve/DaVinci Resolve.app/"
            "Contents/Libraries/Fusion/fusionscript.so"
        )
    return None


def _pin_frozen_python3_home() -> None:
    """Point fusionscript at the frozen bundle's own python3.dll.

    fusionscript.dll has no static Python import: at load time it locates a
    Python 3 itself -- PYTHON3HOME/PYTHONHOME first, else the PEP 514
    registry (HK**\\SOFTWARE\\Python\\PythonCore\\<ver>\\InstallPath) -- and
    LoadLibrary()s that install's python3.dll by full path. Inside the
    PyInstaller exe that is fatal whenever the editor's registered Python
    doesn't match our bundled 3.12: the stable-ABI forwarder drags a second,
    uninitialized python3XY runtime into the process and the first C-API
    call segfaults (0xc0000005). No installed Python at all just as
    silently disables the bridge.

    So when frozen, pin PYTHON3HOME/PYTHONHOME to sys._MEIPASS, where
    build.spec now bundles the build interpreter's python3.dll -- that
    forwarder resolves (by module name) to the python312.dll already loaded
    in this process, on any machine, whatever Python is or isn't installed.
    Deliberately overwrites any inherited value: inside this exe, the only
    correct Python is our own.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    if os.path.exists(os.path.join(meipass, "python3.dll")):
        os.environ["PYTHON3HOME"] = meipass
        os.environ["PYTHONHOME"] = meipass


def _ensure_env_and_syspath() -> None:
    """Set up sys.path/env vars the standard Resolve way, honoring overrides.

    RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB, if already set in the
    environment, are left untouched (the whole point of the override).
    """
    _pin_frozen_python3_home()
    api_dir = os.environ.get("RESOLVE_SCRIPT_API")
    if api_dir:
        modules_dir = os.path.join(api_dir, "Modules")
    else:
        modules_dir = _default_modules_dir()
        if modules_dir:
            # "Modules" is one level below the Scripting dir that
            # RESOLVE_SCRIPT_API is documented to point at.
            os.environ.setdefault("RESOLVE_SCRIPT_API", os.path.dirname(modules_dir))

    if modules_dir and modules_dir not in sys.path:
        sys.path.append(modules_dir)

    if "RESOLVE_SCRIPT_LIB" not in os.environ:
        lib = _default_script_lib()
        if lib:
            os.environ["RESOLVE_SCRIPT_LIB"] = lib


def connect():
    """Return the Resolve scriptapp object, or None if unavailable. Never raises.

    Logs WHY on failure. Without this, a wrong RESOLVE_SCRIPT_LIB, a missing
    fusionscript.dll, a failed import and "Resolve simply isn't running" were
    all indistinguishable -- same message to the caller, nothing in the log,
    impossible to diagnose remotely (AUDIT_2 §2-low)."""
    with _API_LOCK:
        try:
            _ensure_env_and_syspath()
        except Exception:
            log.warning("resolve: could not set up the scripting environment", exc_info=True)
            return None
        try:
            import DaVinciResolveScript as dvr_script  # type: ignore
        except Exception as exc:
            log.debug(
                "resolve: DaVinciResolveScript import failed (%s) -- RESOLVE_SCRIPT_API=%r "
                "RESOLVE_SCRIPT_LIB=%r",
                exc, os.environ.get("RESOLVE_SCRIPT_API"), os.environ.get("RESOLVE_SCRIPT_LIB"),
            )
            return None
        try:
            app = dvr_script.scriptapp("Resolve")
        except Exception as exc:
            log.debug("resolve: scriptapp('Resolve') raised (%s)", exc)
            return None
        if app is None:
            log.debug("resolve: scriptapp('Resolve') returned None -- Resolve is not running")
        return app


def try_connect() -> bool:
    """Tolerant connectivity check (e.g. for tray status). Never raises."""
    try:
        return connect() is not None
    except Exception:
        return False


def _norm_path(p: str) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def _safe_clip_name(media_pool_item) -> str:
    try:
        name = media_pool_item.GetName()
        return name if name else ""
    except Exception:
        return ""


def _safe_folder_name(folder) -> str:
    try:
        name = folder.GetName()
        return name if name else ""
    except Exception:
        return ""


def _safe_project_name(project) -> str:
    try:
        name = project.GetName()
        return name if name else ""
    except Exception:
        return ""


def get_timeline_items() -> dict[str, Any]:
    """Enumerate every video+audio timeline item on the current timeline.

    Returns {"ok": bool, "message": str, "items": [...], "project_name": str}.
    Never raises.

    Each item dict: {
        "file_path": str,               # GetClipProperty()["File Path"]
        "media_pool_item": <object>,    # for ReplaceClip / identity checks
        "clip_name": str,
        "track_type": "video" | "audio",
        "track_index": int,             # 1-based, per Resolve's own convention
        "item_index": int,              # 0-based position within the track
    }

    "project_name" is the current Resolve project's GetName() (empty string
    if unavailable) — the watcher attaches it to OUT_OF_TREE items so the
    popup fixer can suggest a destination inside the project actually being
    edited, instead of a static config value (see fixer.match_project_dir).

    Items with no media pool item (generators, titles, adjustment clips) or
    an empty "File Path" are skipped entirely — per SPEC.md's watcher spec.
    """
    # Defer while the tray menu is open: a fusionscript call holds the GIL
    # for its full native duration, and the open menu's highlight repaints
    # run through a Python window procedure that needs that same GIL -- one
    # poll here froze the hover highlight for a second-plus (2026-07-26).
    ui_state.wait_while_menu_open()
    with _API_LOCK:
        return _get_timeline_items_locked()


def _get_timeline_items_locked() -> dict[str, Any]:
    resolve = connect()
    if resolve is None:
        return {"ok": False, "message": "DaVinci Resolve is not running", "items": [], "project_name": ""}

    try:
        project_manager = resolve.GetProjectManager()
        project = project_manager.GetCurrentProject() if project_manager else None
    except Exception:
        project = None
    if project is None:
        return {"ok": False, "message": "no project open in Resolve", "items": [], "project_name": ""}

    project_name = _safe_project_name(project)

    try:
        timeline = project.GetCurrentTimeline()
    except Exception:
        timeline = None
    if timeline is None:
        return {"ok": False, "message": "no timeline open in Resolve", "items": [], "project_name": project_name}

    items: list[dict[str, Any]] = []
    try:
        for track_type in ("video", "audio"):
            try:
                track_count = timeline.GetTrackCount(track_type) or 0
            except Exception:
                track_count = 0
            for track_index in range(1, track_count + 1):
                try:
                    track_items = timeline.GetItemListInTrack(track_type, track_index) or []
                except Exception:
                    track_items = []
                for item_index, timeline_item in enumerate(track_items):
                    try:
                        media_pool_item = timeline_item.GetMediaPoolItem()
                    except Exception:
                        media_pool_item = None
                    if media_pool_item is None:
                        continue  # generator/title/adjustment clip — no source file
                    try:
                        props = media_pool_item.GetClipProperty() or {}
                    except Exception:
                        props = {}
                    file_path = (props.get("File Path") or "").strip()
                    if not file_path:
                        continue
                    items.append(
                        {
                            "file_path": file_path,
                            "media_pool_item": media_pool_item,
                            "clip_name": _safe_clip_name(media_pool_item),
                            "track_type": track_type,
                            "track_index": track_index,
                            "item_index": item_index,
                        }
                    )
    except Exception as exc:
        log.warning("resolve: timeline enumeration failed: %s", exc, exc_info=True)
        return {"ok": False, "message": _SCRIPTING_ERROR_MESSAGE, "items": [],
                "project_name": project_name}

    return {"ok": True, "message": "", "items": items, "project_name": project_name}


# Editor-facing. The raw f"Resolve scripting error: {exc}" reached tray
# toasts and the fixer dialog verbatim, where it means nothing to anyone and
# suggests no action (AUDIT_2 UX-16). The exception itself is logged.
_SCRIPTING_ERROR_MESSAGE = "Resolve didn't answer. Make sure a project is open, then try again."


# Defensive cap on media pool folder recursion depth: a real Resolve
# project tree is never anywhere near this deep, but a malformed/circular
# folder graph (or a test double) must not hang the watcher/tray thread.
_MAX_MEDIA_POOL_DEPTH = 64


def _walk_media_pool_folder(
    folder, project_name: str, items: list[dict[str, Any]], depth: int = 0, bin_path: str = ""
) -> None:
    """Recurse the media pool, tagging every clip with its bin path.

    `bin_path` is the "/"-joined chain of folder names BELOW the root
    folder (the root itself is excluded) -- root-level clips get "", a
    clip one bin deep gets e.g. "Interviews", two deep "Master/Interviews".
    """
    if depth > _MAX_MEDIA_POOL_DEPTH:
        return

    try:
        clips = folder.GetClipList() or []
    except Exception:
        clips = []
    for clip in clips:
        try:
            props = clip.GetClipProperty() or {}
        except Exception:
            props = {}
        file_path = (props.get("File Path") or "").strip()
        if not file_path:
            continue  # timelines, compound clips, generators have no File Path
        items.append(
            {
                "file_path": file_path,
                "media_pool_item": clip,
                "clip_name": _safe_clip_name(clip),
                "resolve_project_name": project_name,
                "bin_path": bin_path,
                # The clip's SECOND path. Independent of "File Path" and not
                # shown by Reveal in Folder, so a clip can look correctly
                # linked while its proxy points at a drive that has never
                # existed here -- see proxy_relink.py.
                "proxy_path": (props.get("Proxy Media Path") or "").strip(),
                # "1920x1080" when the proxy resolves, "Offline" when
                # attached but unreachable, "None" when there is none.
                "proxy_state": (props.get("Proxy") or "").strip(),
            }
        )

    try:
        subfolders = folder.GetSubFolderList() or []
    except Exception:
        subfolders = []
    for subfolder in subfolders:
        subfolder_name = _safe_folder_name(subfolder)
        child_bin_path = f"{bin_path}/{subfolder_name}" if bin_path else subfolder_name
        _walk_media_pool_folder(subfolder, project_name, items, depth + 1, child_bin_path)


def get_media_pool_items() -> dict[str, Any]:
    """Enumerate every media pool item (clip) anywhere in the current
    project's media pool, recursively walking every bin — unlike
    get_timeline_items, this finds media imported but never cut onto a
    timeline.

    Returns {"ok": bool, "message": str, "items": [...], "project_name": str}.
    Never raises.

    Each item dict: {
        "file_path": str,               # GetClipProperty()["File Path"]
        "media_pool_item": <object>,    # for ReplaceClip / identity checks
        "clip_name": str,
        "resolve_project_name": str,    # the current project's GetName()
    }

    Unlike get_timeline_items (where the watcher attaches
    "resolve_project_name" itself), this function includes it directly on
    every item, since there's no separate watcher layer in between here and
    the popup/fixer for a manual whole-project scan (see app.scan_whole_project).

    Items with no media pool item, or an empty "File Path" (timelines,
    compound clips, generators, titles), are skipped entirely — same rule as
    get_timeline_items.
    """
    ui_state.wait_while_menu_open()  # same GIL courtesy as get_timeline_items
    with _API_LOCK:
        return _get_media_pool_items_locked()


def _get_media_pool_items_locked() -> dict[str, Any]:
    resolve = connect()
    if resolve is None:
        return {"ok": False, "message": "DaVinci Resolve is not running", "items": [], "project_name": ""}

    try:
        project_manager = resolve.GetProjectManager()
        project = project_manager.GetCurrentProject() if project_manager else None
    except Exception:
        project = None
    if project is None:
        return {"ok": False, "message": "no project open in Resolve", "items": [], "project_name": ""}

    project_name = _safe_project_name(project)

    try:
        media_pool = project.GetMediaPool()
    except Exception:
        media_pool = None
    if media_pool is None:
        return {"ok": False, "message": "no media pool available", "items": [], "project_name": project_name}

    try:
        root_folder = media_pool.GetRootFolder()
    except Exception:
        root_folder = None
    if root_folder is None:
        return {"ok": False, "message": "no root folder in media pool", "items": [], "project_name": project_name}

    items: list[dict[str, Any]] = []
    try:
        _walk_media_pool_folder(root_folder, project_name, items)
    except Exception as exc:
        log.warning("resolve: media pool walk failed: %s", exc, exc_info=True)
        return {"ok": False, "message": _SCRIPTING_ERROR_MESSAGE, "items": [],
                "project_name": project_name}

    return {"ok": True, "message": "", "items": items, "project_name": project_name}


def replace_clip(media_pool_item, new_path: str) -> dict[str, Any]:
    """Relink `media_pool_item` to `new_path` via ReplaceClip.

    This preserves every timeline usage of the clip (per SPEC.md's fixer
    spec) rather than re-importing + re-editing. Returns
    {"ok": bool, "message": str}. Never raises.
    """
    if media_pool_item is None:
        return {"ok": False, "message": "no media pool item to relink"}
    with _API_LOCK:
        try:
            result = media_pool_item.ReplaceClip(new_path)
        except Exception as exc:
            log.warning("resolve: ReplaceClip(%s) raised: %s", new_path, exc, exc_info=True)
            return {"ok": False, "message": _SCRIPTING_ERROR_MESSAGE}
    if not result:
        log.warning("resolve: ReplaceClip returned False for %s", new_path)
        return {
            "ok": False,
            "message": (
                "Copied the file in, but Resolve wouldn't relink it. Close the clip's "
                "timeline and use tray → Scan whole project again."
            ),
        }
    return {"ok": True, "message": f"Relinked to {new_path}"}


def link_proxy_media(media_pool_item, proxy_path: str) -> dict[str, Any]:
    """Point `media_pool_item`'s PROXY at `proxy_path`. Never raises.

    Distinct from replace_clip: that repoints the ORIGINAL, this repoints the
    separate proxy attachment (see proxy_relink.py for why the two drift
    apart). Resolve validates the pairing itself and returns False on a
    timecode/frame-count mismatch, so a same-named but wrong file is refused
    rather than silently attached.
    """
    if media_pool_item is None:
        return {"ok": False, "message": "no media pool item to relink"}
    if not proxy_path:
        return {"ok": False, "message": "no proxy path given"}
    with _API_LOCK:
        try:
            result = media_pool_item.LinkProxyMedia(proxy_path)
        except Exception as exc:
            log.warning("resolve: LinkProxyMedia(%s) raised: %s", proxy_path, exc, exc_info=True)
            return {"ok": False, "message": _SCRIPTING_ERROR_MESSAGE}
    if not result:
        return {
            "ok": False,
            "message": f"Resolve wouldn't accept {proxy_path} as this clip's proxy",
        }
    return {"ok": True, "message": f"Proxy relinked to {proxy_path}"}
