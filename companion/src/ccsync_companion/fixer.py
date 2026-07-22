"""Fixer logic for OUT_OF_TREE clips — Component 2 of SPEC.md's companion app
(the non-GUI half; popup.py wires this to a tkinter dialog).

Contract, per SPEC.md:
  - destination suggested by extension (audio/stills/video-or-other).
  - destination dropdown lists existing directories under local_root (minus
    any "Proxy" dirs) plus the type defaults; free text is allowed by popup.
  - "Fix all": copy file to local_root/<dest>/<filename>, collision -> append
    " (2)", " (3)", ... then relink via mediaPoolItem.ReplaceClip(new_path).
  - Never delete/move the original — copy only, even on ReplaceClip failure.
  - "Ignore": per-session suppression, keyed by normalized path.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any, Optional

from . import resolve_bridge

log = logging.getLogger("ccsync.fixer")

AUDIO_EXTS = {".wav", ".mp3", ".aif", ".aiff", ".flac", ".m4a", ".ogg"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".psd", ".exr"}


class IgnoreTracker:
    """Per-session suppression, keyed by normalized path.

    Shared between the watcher (so an ignored path isn't re-popped) and the
    popup's "Ignore" button. Intentionally in-memory only — SPEC.md calls
    this out as per-session, not persisted.
    """

    def __init__(self) -> None:
        self._ignored: set[str] = set()

    def is_ignored(self, path: str) -> bool:
        return resolve_bridge._norm_path(path) in self._ignored

    def ignore(self, path: str) -> None:
        self._ignored.add(resolve_bridge._norm_path(path))

    def clear(self) -> None:
        self._ignored.clear()


def classify_ext(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in IMAGE_EXTS:
        return "image"
    return "other"  # video + anything else share the same default per SPEC.md


def suggest_destination(path: str, editor_name: str) -> str:
    """Return a local_root-relative destination dir, '/'-separated.

    audio -> "Audio/Music"
    still image -> "B-roll/Stills"
    video / other -> "B-roll/Editor Added/<editor_name>"
    """
    kind = classify_ext(path)
    if kind == "audio":
        return "Audio/Music"
    if kind == "image":
        return "B-roll/Stills"
    editor = editor_name or "Unknown"
    return f"B-roll/Editor Added/{editor}"


def default_destination_dirs(editor_name: str) -> set[str]:
    editor = editor_name or "Unknown"
    return {"Audio/Music", "B-roll/Stills", f"B-roll/Editor Added/{editor}"}


def list_destination_dirs(local_root: str, editor_name: str) -> list[str]:
    """Existing directories under local_root ('/'-separated, relative),
    excluding any directory literally named "Proxy" (and its contents), plus
    the three type-default destinations (present even if they don't exist
    yet, so the dropdown always offers a sane choice).
    """
    dirs: set[str] = set(default_destination_dirs(editor_name))

    root = Path(local_root) if local_root else None
    if root is not None and root.is_dir():
        for dirpath, dirnames, _filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d.lower() != "proxy"]
            rel = os.path.relpath(dirpath, root)
            if rel == os.curdir:
                continue
            dirs.add(rel.replace(os.sep, "/"))

    return sorted(dirs)


def unique_destination_path(dest_dir: Path, filename: str) -> Path:
    """Pick a non-colliding path in dest_dir for filename, appending
    " (2)", " (3)", ... before the extension as needed. Does not create
    dest_dir or the file — pure path arithmetic, easy to unit test.
    """
    stem, ext = os.path.splitext(filename)
    candidate = dest_dir / filename
    n = 2
    while candidate.exists():
        candidate = dest_dir / f"{stem} ({n}){ext}"
        n += 1
    return candidate


def fix_clip(
    file_path: str,
    dest_rel: str,
    local_root: str,
    media_pool_item: Any,
    copy_fn=shutil.copy2,
    replace_clip_fn=resolve_bridge.replace_clip,
) -> dict[str, Any]:
    """Copy `file_path` into local_root/dest_rel (collision-safe) then relink
    `media_pool_item` to the copy via ReplaceClip.

    Returns {"ok": bool, "message": str, "copied_to": Optional[str]}. Never
    raises — every failure path (missing source, copy error, ReplaceClip
    failure) is reported in the returned dict. The original file at
    `file_path` is NEVER deleted or moved, regardless of outcome.
    """
    src = Path(file_path)
    if not src.is_file():
        return {"ok": False, "message": f"source file not found: {file_path}", "copied_to": None}

    dest_dir = Path(local_root) / dest_rel.replace("/", os.sep)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = unique_destination_path(dest_dir, src.name)
        copy_fn(src, dest_path)
    except OSError as exc:
        return {"ok": False, "message": f"copy failed: {exc}", "copied_to": None}

    relink_result = replace_clip_fn(media_pool_item, str(dest_path))
    if not relink_result.get("ok"):
        return {
            "ok": False,
            "message": f"copied to {dest_path} but relink failed: {relink_result.get('message')}",
            "copied_to": str(dest_path),
        }

    return {
        "ok": True,
        "message": f"Fixed: copied to {dest_path} and relinked",
        "copied_to": str(dest_path),
    }
