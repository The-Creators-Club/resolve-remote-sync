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


def scan_project_dirs(projects_dir: Path) -> list[str]:
    """Project rel-paths (year/series/project) at exactly depth 3, skipping
    hidden dirs at any level."""
    found = []
    for path in sorted(projects_dir.glob("*/*/*")):
        if not path.is_dir():
            continue
        rel = path.relative_to(projects_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        found.append(rel.as_posix())
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
