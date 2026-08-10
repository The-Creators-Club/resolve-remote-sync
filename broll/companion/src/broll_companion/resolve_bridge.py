"""All DaVinci Resolve scripting-API interaction lives here.

Nothing in this module ever crashes the server: every public function
returns None / False / a friendly {"ok": False, "message": ...} dict on any
failure (Resolve not running, no project, no timeline, import failure, etc).

We lazy-import DaVinciResolveScript and lazy-connect (scriptapp("Resolve"))
on every call rather than caching a connection, since Resolve may not be
running yet, may be restarted, etc.
"""

from __future__ import annotations

import os
import platform
import sys
from typing import Optional

BIN_NAME = "B-Roll"


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


def _ensure_env_and_syspath() -> None:
    """Set up sys.path/env vars the standard Resolve way, honoring overrides.

    RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB, if already set in the
    environment, are left untouched (the whole point of the override).
    """
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
    """Return the Resolve scriptapp object, or None if unavailable. Never raises."""
    try:
        _ensure_env_and_syspath()
        import DaVinciResolveScript as dvr_script  # type: ignore

        return dvr_script.scriptapp("Resolve")
    except Exception:
        return None


def try_connect() -> bool:
    """Tolerant connectivity check for GET /status. Never raises."""
    try:
        return connect() is not None
    except Exception:
        return False


def _norm_path(p: str) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def _find_or_create_bin(media_pool, root_folder, name: str):
    for sub in root_folder.GetSubFolderList() or []:
        if sub.GetName() == name:
            return sub
    return media_pool.AddSubFolder(root_folder, name)


def _find_existing_clip(bin_folder, local_path: str):
    target = _norm_path(local_path)
    for clip in bin_folder.GetClipList() or []:
        props = clip.GetClipProperty() or {}
        if _norm_path(props.get("File Path", "")) == target:
            return clip
    return None


def perform_insert(local_path: str, in_frame: int, out_frame: int) -> dict:
    """Drive Resolve to append `local_path` (trimmed in_frame..out_frame) to
    the current timeline, per SPEC.md's Companion API contract.

    Returns {"ok": bool, "message": str}. Never raises.
    """
    resolve = connect()
    if resolve is None:
        return {"ok": False, "message": "DaVinci Resolve is not running"}

    try:
        project_manager = resolve.GetProjectManager()
        project = project_manager.GetCurrentProject() if project_manager else None
    except Exception:
        project = None
    if project is None:
        return {"ok": False, "message": "no project open in Resolve"}

    try:
        timeline = project.GetCurrentTimeline()
    except Exception:
        timeline = None
    if timeline is None:
        return {"ok": False, "message": "no timeline open — create one first"}

    try:
        media_pool = project.GetMediaPool()
        root_folder = media_pool.GetRootFolder()
        broll_bin = _find_or_create_bin(media_pool, root_folder, BIN_NAME)

        media_pool_item = _find_existing_clip(broll_bin, local_path)
        if media_pool_item is None:
            media_pool.SetCurrentFolder(broll_bin)
            imported = media_pool.ImportMedia([local_path])
            if not imported:
                return {"ok": False, "message": f"failed to import media at {local_path}"}
            media_pool_item = imported[0]

        appended = media_pool.AppendToTimeline(
            [{"mediaPoolItem": media_pool_item, "startFrame": in_frame, "endFrame": out_frame}]
        )
        if not appended:
            return {"ok": False, "message": "failed to append clip to timeline"}

        name = media_pool_item.GetName()
        n_frames = out_frame - in_frame
        return {"ok": True, "message": f"Inserted {name} ({n_frames} frames)"}
    except Exception as exc:
        return {"ok": False, "message": f"Resolve scripting error: {exc}"}
