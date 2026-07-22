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

import os
import platform
import sys
from typing import Any, Optional


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


def get_timeline_items() -> dict[str, Any]:
    """Enumerate every video+audio timeline item on the current timeline.

    Returns {"ok": bool, "message": str, "items": [...]}. Never raises.

    Each item dict: {
        "file_path": str,               # GetClipProperty()["File Path"]
        "media_pool_item": <object>,    # for ReplaceClip / identity checks
        "clip_name": str,
        "track_type": "video" | "audio",
        "track_index": int,             # 1-based, per Resolve's own convention
        "item_index": int,              # 0-based position within the track
    }

    Items with no media pool item (generators, titles, adjustment clips) or
    an empty "File Path" are skipped entirely — per SPEC.md's watcher spec.
    """
    resolve = connect()
    if resolve is None:
        return {"ok": False, "message": "DaVinci Resolve is not running", "items": []}

    try:
        project_manager = resolve.GetProjectManager()
        project = project_manager.GetCurrentProject() if project_manager else None
    except Exception:
        project = None
    if project is None:
        return {"ok": False, "message": "no project open in Resolve", "items": []}

    try:
        timeline = project.GetCurrentTimeline()
    except Exception:
        timeline = None
    if timeline is None:
        return {"ok": False, "message": "no timeline open in Resolve", "items": []}

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
        return {"ok": False, "message": f"Resolve scripting error: {exc}", "items": []}

    return {"ok": True, "message": "", "items": items}


def replace_clip(media_pool_item, new_path: str) -> dict[str, Any]:
    """Relink `media_pool_item` to `new_path` via ReplaceClip.

    This preserves every timeline usage of the clip (per SPEC.md's fixer
    spec) rather than re-importing + re-editing. Returns
    {"ok": bool, "message": str}. Never raises.
    """
    if media_pool_item is None:
        return {"ok": False, "message": "no media pool item to relink"}
    try:
        result = media_pool_item.ReplaceClip(new_path)
    except Exception as exc:
        return {"ok": False, "message": f"Resolve scripting error: {exc}"}
    if not result:
        return {"ok": False, "message": f"ReplaceClip returned False for {new_path}"}
    return {"ok": True, "message": f"Relinked to {new_path}"}
