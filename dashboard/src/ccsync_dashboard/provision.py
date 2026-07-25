"""Auto-provisioning helpers: discover project dirs that have no Syncthing
folder yet and build the folder config for them.

slugify() and build_stignore_lines() are intentional copies of
server/common.py (the dashboard container cannot import server/) -- if the
conventions there change, change them here too. The folder config mirrors
server/setup_syncthing_folder.py so hand-provisioned and auto-provisioned
folders are indistinguishable.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

VIDEO_EXTENSIONS = [
    ".braw", ".mov", ".mp4", ".mxf", ".avi", ".mts", ".m2ts", ".mkv",
    ".r3d", ".crm", ".mpg", ".mpeg", ".wmv", ".webm", ".insv", ".360",
]
_VIDEO_EXT_SET = frozenset(VIDEO_EXTENSIONS)

# Intentional copy of server/common.py's TEMPLATE_FOLDERS (same reason as
# slugify above: the container cannot import server/) -- if the standard
# project template changes there, change it here too. Used by the
# /project-setup "create new project" flow (api.create_tree_project).
TEMPLATE_FOLDERS = [
    "AE",
    "Audio/Music",
    "Audio/Voiceover",
    "B-roll",
    "Interviewees",
    "Render in Place",
    "Subs",
    "Youtube",
]


def classify_media(rel_parts: Iterable[str], ext: str) -> str | None:
    """Classify a file for the NAS media inventory. Only video counts:
    'proxy' when it lives under a Proxy/ dir (any depth, case-insensitive),
    else 'original'. Non-video returns None (skipped). Mirrors the
    .stignore convention in build_stignore_lines()."""
    if ext.lower() not in _VIDEO_EXT_SET:
        return None
    return "proxy" if any(p.lower() == "proxy" for p in rel_parts) else "original"


def slugify(text: str) -> str:
    text = text.replace("\\", "/").strip().lower()
    parts = [p for p in re.split(r"[^a-z0-9]+", text) if p]
    slug = "-".join(parts)
    if not slug:
        raise ValueError(f"slugify({text!r}) produced an empty slug")
    return slug


def build_stignore_lines() -> list[str]:
    lines = [f"(?i)*{ext}" for ext in VIDEO_EXTENSIONS]
    lines.append("(?i)Proxy")
    lines.append("(?i)**/Proxy")
    lines.append("(?i)**/Proxy/**")
    return lines


# The explicit project marker (added 2026-07-25). A directory IS a project
# because it carries this file -- never because of its depth or name. The
# slug inside is the project's IMMUTABLE identity: it travels with the
# directory when it's moved/renamed on the NAS, which is what lets the
# collector retarget the Syncthing folder instead of treating a move as a
# delete + brand-new project. Written by every create path (dashboard
# /project-setup, server setup_tree.py) and self-healed each provision
# cycle for known folders. Same JSON shape as server/common.py's marker
# helpers -- intentional copy, keep in sync.
MARKER_FILENAME = ".ccsync-project"


def read_marker(directory: Path) -> str | None:
    """The marker's slug, or None (missing/unreadable/malformed -- never
    raises; callers treat None as 'not a project' or log-and-skip)."""
    import json

    try:
        data = json.loads((Path(directory) / MARKER_FILENAME).read_text(encoding="utf-8-sig"))
        slug = str(data.get("slug", "")).strip()
        return slug or None
    except (OSError, ValueError):
        return None


def write_marker(directory: Path, slug: str, created_by: str = "dashboard") -> None:
    """Atomic marker write (tmp + replace) so a concurrent scan never sees a
    partial file. Raises OSError on failure -- callers decide severity."""
    import datetime as _dt
    import json
    import os as _os

    payload = json.dumps({
        "slug": slug,
        "created_by": created_by,
        "created_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
    }, indent=1)
    target = Path(directory) / MARKER_FILENAME
    tmp = Path(directory) / (MARKER_FILENAME + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    _os.replace(tmp, target)


def scan_project_dirs(projects_dir: Path, max_depth: int = 8) -> list[tuple[str, str | None]]:
    """(rel_posix, marker_slug) for every directory carrying MARKER_FILENAME,
    at ANY depth up to max_depth. Hidden dirs are skipped; descent is PRUNED
    at each marker (projects cannot nest). marker_slug is None when the
    marker file exists but is unreadable/malformed -- callers log + skip.

    Bare directories (no marker) are deliberately invisible: since
    2026-07-25 a folder is a project only because someone designated it
    (picker, create flow, setup_tree.py). The old rule -- 'anything at
    exactly depth 3' -- mis-provisioned container folders the moment the
    tree grew a fourth level.
    """
    import os as _os

    projects_dir = Path(projects_dir)
    found: list[tuple[str, str | None]] = []
    for dirpath, dirnames, filenames in _os.walk(projects_dir):
        current = Path(dirpath)
        rel = current.relative_to(projects_dir)
        parts = () if rel == Path(".") else rel.parts
        depth = len(parts)
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if depth > max_depth:
            dirnames[:] = []
            continue
        if depth == 0:
            continue  # the Projects root itself is never a project
        if MARKER_FILENAME in filenames:
            found.append((rel.as_posix(), read_marker(current)))
            dirnames[:] = []  # no nested projects
    found.sort()
    return found


def build_folder_config(
    slug: str, rel: str, data_prefix: str, device_ids: list[str]
) -> dict:
    return {
        "id": slug,
        "label": rel,
        "path": f"{data_prefix.rstrip('/')}/{rel}",
        "type": "sendreceive",
        "fsWatcherEnabled": True,
        # dataset is aclmode=restricted; chmod fails without this
        "ignorePerms": True,
        "rescanIntervalS": 3600,
        "versioning": {
            "type": "staggered",
            "params": {"cleanInterval": "3600", "maxAge": "31536000"},
        },
        "devices": [{"deviceID": device_id, "introducedBy": ""} for device_id in device_ids],
    }
