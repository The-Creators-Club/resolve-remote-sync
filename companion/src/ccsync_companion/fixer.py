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
import re
import shutil
from pathlib import Path
from typing import Any, Iterable, Optional

from . import resolve_bridge

log = logging.getLogger("ccsync.fixer")

AUDIO_EXTS = {".wav", ".mp3", ".aif", ".aiff", ".flac", ".m4a", ".ogg"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".psd", ".exr"}

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


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


def suggest_destination(path: str, editor_name: str, project_prefix: str = "") -> str:
    """Return a local_root-relative destination dir, '/'-separated.

    audio -> "Audio/Music"
    still image -> "B-roll/Stills"
    video / other -> "B-roll/Editor Added/<editor_name>"

    `project_prefix` (e.g. "Projects/2025/FF4/Nuclear") is prepended when
    set — destinations must land INSIDE the active project, not at the
    Creators_Club root, or editor media uploads to an orphan path on the
    NAS that no Resolve project references.
    """
    kind = classify_ext(path)
    if kind == "audio":
        dest = "Audio/Music"
    elif kind == "image":
        dest = "B-roll/Stills"
    else:
        editor = editor_name or "Unknown"
        dest = f"B-roll/Editor Added/{editor}"
    prefix = (project_prefix or "").strip("/").replace("\\", "/")
    return f"{prefix}/{dest}" if prefix else dest


def _tokenize(text: str) -> set[str]:
    """Lowercase alnum-only tokens, split on any run of non-alnum chars."""
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def match_project_dir(resolve_project_name: str, project_rel_paths: list[str]) -> Optional[str]:
    """Best-effort match of the LIVE Resolve project name to one of the
    tree's Projects/<year>/<series>/<project> directories, by token overlap.

    Both sides are normalized to lowercase alnum-only tokens (split on any
    run of non-alnum characters) before comparing. A candidate must share at
    least one NON-YEAR token with `resolve_project_name` to qualify — a
    project name that happens to contain a 4-digit year is not, by itself,
    grounds to file media under every project from that year. The candidate
    with the most overlapping tokens wins; a tie (or no qualifying
    candidate) returns None rather than guessing.

    Example: resolve_project_name="CCT Creator Profiles" matches tree dir
    "2026/Creator Profiles/Season 1" (tokens creator+profiles overlap) and
    NOT "2025/FF4/Nuclear" (no overlap).
    """
    if not resolve_project_name or not project_rel_paths:
        return None

    name_tokens = _tokenize(resolve_project_name)
    if not name_tokens:
        return None

    best_score = 0
    best_matches: list[str] = []
    for rel in project_rel_paths:
        path_tokens = _tokenize(rel)
        overlap = name_tokens & path_tokens
        # Trivial tokens never count toward a match: 4-digit years AND short
        # bare numbers ("1", "2" -- season/part counters). Without the
        # latter, "Event 1 Videos" matched ".../Season 1" on the shared "1"
        # alone (seen live 2026-07-25 on the dashboard's twin of this
        # matcher, db.match_project_label -- keep the two in sync).
        meaningful = {
            t for t in overlap if not (t.isdigit() and len(t) <= 4)
        }
        if not meaningful:
            continue
        score = len(meaningful)
        if score > best_score:
            best_score = score
            best_matches = [rel]
        elif score == best_score:
            best_matches.append(rel)

    if best_score == 0 or len(best_matches) != 1:
        return None
    return best_matches[0]


# Intentional copy of the dashboard's provision.MARKER_FILENAME convention
# (see that module's marker docs) -- markers sync to editors via lane C, so
# a local project dir self-identifies at any depth. Keep in sync.
MARKER_FILENAME = ".ccsync-project"


def list_project_dirs(local_root: str, extra_rels: Iterable[str] = ()) -> list[str]:
    """Project rel-paths ('/'-separated, sorted) under local_root/Projects.

    Since 2026-07-25 a project is any directory carrying the
    .ccsync-project marker, at ANY depth (descent prunes at markers -- no
    nested projects; hidden dirs skipped). `extra_rels` (e.g. the
    dashboard-selected rels, which are authoritative) are unioned in for
    dirs whose marker hasn't synced down yet. Tolerant of a missing/partial
    tree — never raises, just returns fewer (or no) entries.
    """
    if not local_root:
        return []
    projects_dir = Path(local_root) / "Projects"
    rels: set[str] = set()

    try:
        for dirpath, dirnames, filenames in os.walk(projects_dir):
            rel = Path(dirpath).relative_to(projects_dir)
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            if rel == Path("."):
                continue
            if MARKER_FILENAME in filenames:
                rels.add(rel.as_posix())
                dirnames[:] = []
    except OSError:
        pass

    for extra in extra_rels or ():
        extra = str(extra).strip().strip("/")
        if extra and (projects_dir / Path(*extra.split("/"))).is_dir():
            rels.add(extra)
    return sorted(rels)


def pick_project_prefix(
    resolve_project_name: str,
    project_rel_paths: list[str],
    project_prefix: str = "",
) -> str:
    """Fallback order for the popup suggestion base, per SPEC: the tree
    project dir matching the CURRENT Resolve project name -> the configured
    `active_project` (`project_prefix`) -> the tree root (no prefix, "").

    Pure — `project_rel_paths` is expected to come from list_project_dirs,
    kept as a separate argument here so this stays filesystem-free and
    trivially testable.
    """
    matched = match_project_dir(resolve_project_name, project_rel_paths)
    if matched:
        return f"Projects/{matched}"
    return project_prefix or ""


def default_destination_dirs(editor_name: str, project_prefix: str = "") -> set[str]:
    editor = editor_name or "Unknown"
    dests = {"Audio/Music", "B-roll/Stills", f"B-roll/Editor Added/{editor}"}
    prefix = (project_prefix or "").strip("/").replace("\\", "/")
    if prefix:
        dests = {f"{prefix}/{d}" for d in dests}
    return dests


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
    media_pool_items: Any,
    copy_fn=shutil.copy2,
    replace_clip_fn=resolve_bridge.replace_clip,
) -> dict[str, Any]:
    """Copy `file_path` into local_root/dest_rel (collision-safe) once, then
    relink EVERY media pool item in `media_pool_items` to that one copy via
    ReplaceClip.

    `media_pool_items` may be a single item (back-compat with callers/tests
    that only ever deal with one) or a list — the same source file can be
    referenced by several timeline items (e.g. the same clip cut onto
    multiple places in the sequence), and popup.py collapses those into one
    row per unique path (see popup.dedupe_out_of_tree_items), so fixing the
    row has to relink all of them, not just the first.

    Returns {"ok": bool, "message": str, "copied_to": Optional[str]}. Never
    raises — every failure path (missing source, copy error, ReplaceClip
    failure) is reported in the returned dict. The original file at
    `file_path` is NEVER deleted or moved, regardless of outcome.
    """
    items = media_pool_items if isinstance(media_pool_items, list) else [media_pool_items]

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

    failures: list[str] = []
    for media_pool_item in items:
        relink_result = replace_clip_fn(media_pool_item, str(dest_path))
        if not relink_result.get("ok"):
            failures.append(relink_result.get("message", "unknown error"))

    if failures:
        return {
            "ok": False,
            "message": (
                f"copied to {dest_path} but relink failed for {len(failures)}/{len(items)} "
                f"item(s): {'; '.join(failures)}"
            ),
            "copied_to": str(dest_path),
        }

    return {
        "ok": True,
        "message": f"Fixed: copied to {dest_path} and relinked {len(items)} item(s)",
        "copied_to": str(dest_path),
    }
