"""`broll-index export-manifest` — the set of files to copy to the NAS: every video
EXCEPT confirmed duplicates (see broll_index/duplicates.py). This is what makes the
consolidation copy skip redundant footage, per SPEC.md's "Indexer CLI contract".

Three output formats, all plain text, all UTF-8 (the corpus has CJK filenames):

- `list`    — one absolute source path per line. Feed it to `robocopy /IF <file>` or any
  generic "copy exactly these files" tool.
- `robocopy` — a runnable .bat. robocopy takes one (source dir, dest dir, filenames...)
  triple per invocation rather than a flat file list, so lines are grouped per source
  directory. The destination mirrors `<share>/<rel_path>` under a %DEST% root the
  operator sets before running (the NAS consolidation target isn't known here — that's
  what `rebase --to-share` points at afterwards).
- `rsync`   — an `rsync --files-from`-style relative-path list, one `share/rel_path` per
  line. `--files-from` paths are resolved against a single SRC root given on rsync's own
  command line; `share/rel_path` is exactly right when that SRC root is the parent
  directory containing every share (matching the same `<share>/<rel_path>` layout the
  robocopy format targets).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable

ResolvePathFn = Callable[[dict[str, Any]], "Path | None"]


@dataclass
class ManifestPlan:
    to_copy: list[dict[str, Any]] = field(default_factory=list)  # {video, path}
    skipped_duplicates: list[dict[str, Any]] = field(default_factory=list)  # {video}
    unresolved: list[dict[str, Any]] = field(default_factory=list)  # {video} - unknown share
    bytes_saved: int = 0

    def summary(self) -> str:
        return (
            f"{len(self.to_copy)} file(s) to copy, "
            f"{len(self.skipped_duplicates)} duplicate(s) skipped, "
            f"{self.bytes_saved} byte(s) saved"
        )


def plan_manifest(videos: list[dict[str, Any]], resolve_path: ResolvePathFn) -> ManifestPlan:
    """Pure planning step — no I/O beyond `resolve_path` (which is expected to be a pure
    path-join, not a filesystem check; existence isn't required to export a manifest)."""
    plan = ManifestPlan()
    for v in videos:
        if v.get("duplicate_of"):
            plan.skipped_duplicates.append({"video": v})
            plan.bytes_saved += v.get("size_bytes") or 0
            continue

        # 'excluded' = the camera original behind a proxy we archive instead (see
        # scanner.initial_status). Deliberately counted as bytes_saved alongside
        # duplicates: both are files deliberately left behind, and on a
        # source="proxies" share they are the overwhelming majority of them --
        # 403 GB of the MOFA event's 420 GB. A manifest that copied these would
        # defeat the entire reason for indexing proxies.
        if v.get("status") == "excluded":
            plan.skipped_duplicates.append({"video": v})
            plan.bytes_saved += v.get("size_bytes") or 0
            continue

        path = resolve_path(v)
        if path is None:
            plan.unresolved.append({"video": v})
            continue
        plan.to_copy.append({"video": v, "path": Path(path)})

    return plan


def render_list(plan: ManifestPlan) -> str:
    """One absolute source path per line."""
    lines = [str(entry["path"]) for entry in plan.to_copy]
    return "\n".join(lines) + ("\n" if lines else "")


def render_robocopy(plan: ManifestPlan) -> str:
    """A runnable .bat: one `robocopy` call per source directory, listing that
    directory's files by name (robocopy copies whole directories + a file filter, not
    individual file paths)."""
    lines = [
        "@echo off",
        "REM broll-index export-manifest --format robocopy",
        "REM Set DEST to the destination root before running, e.g.:",
        "REM     set DEST=Z:\\broll-consolidated",
        "if \"%DEST%\"==\"\" (",
        "    echo Set DEST to the destination root first, e.g. set DEST=Z:\\broll-consolidated",
        "    exit /b 1",
        ")",
        "",
    ]

    by_dir: dict[tuple[str, str], list[str]] = {}
    src_dirs: dict[tuple[str, str], Path] = {}
    for entry in plan.to_copy:
        video = entry["video"]
        path: Path = entry["path"]
        rel = PurePosixPath(video["rel_path"])
        rel_dir = "" if str(rel.parent) == "." else str(rel.parent)
        key = (video["share"], rel_dir)
        by_dir.setdefault(key, []).append(rel.name)
        src_dirs[key] = path.parent

    for key in sorted(by_dir):
        share, rel_dir = key
        names = " ".join(f'"{n}"' for n in by_dir[key])
        dest_dir = f"%DEST%\\{share}"
        if rel_dir:
            dest_dir += "\\" + rel_dir.replace("/", "\\")
        lines.append(f'robocopy "{src_dirs[key]}" "{dest_dir}" {names} /R:2 /W:5')

    lines.append("")
    return "\n".join(lines)


def render_rsync(plan: ManifestPlan) -> str:
    """`--files-from`-style relative-path list: one `share/rel_path` per line."""
    lines = [f"{entry['video']['share']}/{entry['video']['rel_path']}" for entry in plan.to_copy]
    return "\n".join(lines) + ("\n" if lines else "")


RENDERERS: dict[str, Callable[[ManifestPlan], str]] = {
    "list": render_list,
    "robocopy": render_robocopy,
    "rsync": render_rsync,
}


def do_export_manifest(
    storage: Any,
    *,
    resolve_path: ResolvePathFn,
    fmt: str = "list",
) -> tuple[ManifestPlan, str]:
    if fmt not in RENDERERS:
        raise ValueError(f"unknown export-manifest format {fmt!r} (expected {sorted(RENDERERS)})")

    videos = storage.all_videos()
    plan = plan_manifest(videos, resolve_path)
    content = RENDERERS[fmt](plan)
    return plan, content
