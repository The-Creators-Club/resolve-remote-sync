"""Dashboard-driven file moves, the companion half (docs/FILE_MOVES.md,
2026-08-27).

An admin moved a file (or a folder) between two places in the Projects tree
ON THE SERVER, and this machine held a copy at the old path. Lane A is a
one-way copy that never deletes, so without this the next pass would put
the file straight back where the admin just moved it from -- which is
exactly what happened to leso's card dump. The dashboard tells us through
the report reply (`commands.file_moves`); we move our own copy the same way,
carry its proxies with it, repoint every Resolve clip that referenced the
old path, and answer through the next report (`file_moves_applied`).

Two safety rules, both the same shape as the removal gate's:

* NOTHING here deletes. A move whose destination already exists on this
  machine is refused and reported, with the local file left where it was.
* Every move this machine has HEARD OF keeps its old path out of lane A for
  a day (`recent_excludes`), applied or refused, so a local copy that could
  not be moved still cannot re-upload itself while the admin sorts it out.

The ledger is on disk (`~/.ccsync/state/file_moves.json`): a command that
is redelivered after a restart must not be applied twice, and the exclusion
must survive the process that learned it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("ccsync.file_moves")

LEDGER_FILENAME = "file_moves.json"
LEDGER_MAX_ENTRIES = 200
# How long a move's OLD path stays out of lane A. Long enough to cover the
# machine that was asleep when the command arrived and the admin who is
# still deciding what to do with a refused one; short enough that a path
# reused for genuinely new footage next week uploads normally.
EXCLUDE_WINDOW_SECONDS = 24 * 3600
PROJECTS_PREFIX = "Projects/"

_BAD_SEGMENT = re.compile(r"^\.\.?$")


def safe_rel(raw: Any) -> Optional[str]:
    """A project-relative posix path from the wire, or None. Refuses
    absolute paths, drive letters, `..`, and control characters: the
    dashboard validated it too, but the command travelled through a JSON
    reply and this is the last stop before a filesystem call."""
    if not isinstance(raw, str):
        return None
    value = raw.strip().replace("\\", "/").strip("/")
    if not value or ":" in value or any(ord(ch) < 32 for ch in value):
        return None
    parts = [p for p in value.split("/") if p]
    if not parts or any(_BAD_SEGMENT.match(p) or not p.strip() for p in parts):
        return None
    return "/".join(parts)


def parse_command(raw: Any) -> Optional[dict[str, Any]]:
    """One `commands.file_moves` entry, validated, or None."""
    if not isinstance(raw, dict):
        return None
    try:
        move_id = int(raw.get("id"))
    except (TypeError, ValueError):
        return None
    from_project = safe_rel(raw.get("from_project_rel"))
    to_project = safe_rel(raw.get("to_project_rel"))
    from_rel = safe_rel(raw.get("from_rel"))
    to_rel = safe_rel(raw.get("to_rel"))
    if not (from_project and to_project and from_rel and to_rel):
        return None
    return {
        "id": move_id,
        "from_project_rel": from_project, "from_rel": from_rel,
        "to_project_rel": to_project, "to_rel": to_rel,
        "is_dir": bool(raw.get("is_dir")),
        "requested_by": str(raw.get("requested_by") or "your administrator").strip(),
    }


def _same_file(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def _is_inside(path: Path, root: Path) -> bool:
    p = os.path.normcase(os.path.normpath(str(path)))
    r = os.path.normcase(os.path.normpath(str(root)))
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


def move_proxy_siblings(src: Path, dest: Path) -> int:
    """The `Proxy/<stem>.*` beside a file goes where the file goes -- the
    convention Resolve's auto-link and both rclone lanes are built on. Never
    overwrites; returns how many were moved."""
    proxy_dir = src.parent / "Proxy"
    if not proxy_dir.is_dir():
        return 0
    moved = 0
    for candidate in sorted(proxy_dir.iterdir()):
        if not candidate.is_file() or candidate.stem.lower() != src.stem.lower():
            continue
        target_dir = dest.parent / "Proxy"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / candidate.name
        if target.exists():
            continue
        candidate.replace(target)
        moved += 1
    return moved


def apply_move(move: dict[str, Any], local_root: str) -> tuple[bool, str, Optional[tuple[str, str]]]:
    """Move this machine's copy. Returns (ok, detail, (old_local, new_local))
    -- the pair is None when nothing was here to move. Never deletes and
    never overwrites; every refusal leaves the tree exactly as it was."""
    root = Path(local_root) / "Projects"
    src = root / Path(*move["from_project_rel"].split("/")) / Path(*move["from_rel"].split("/"))
    dest = root / Path(*move["to_project_rel"].split("/")) / Path(*move["to_rel"].split("/"))
    if not src.exists():
        return True, "nothing at the old path on this machine", None
    if _same_file(src, dest):
        return True, "already where the server has it", None
    if dest.exists():
        return False, f"the destination already exists on this machine ({dest})", None
    if src.is_dir() and _is_inside(dest, src):
        return False, "a folder cannot be moved into itself", None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dest)
        proxies = 0 if src.is_dir() or dest.is_dir() else move_proxy_siblings(src, dest)
    except OSError as exc:
        return False, f"could not move it on this machine: {exc}", None
    detail = "moved" + (f", {proxies} proxy file(s) with it" if proxies else "")
    return True, detail, (str(src), str(dest))


class FileMoveLedger:
    """What this machine has done about each move it was told of."""

    def __init__(self, state_dir: Path, now: Callable[[], float] = time.time) -> None:
        self._path = Path(state_dir) / LEDGER_FILENAME
        self._now = now
        self._entries: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        entries = data.get("entries") if isinstance(data, dict) else None
        if isinstance(entries, list):
            self._entries = [e for e in entries if isinstance(e, dict) and "id" in e]

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"entries": self._entries[-LEDGER_MAX_ENTRIES:]},
                                      indent=1), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            log.exception("file moves: could not write the ledger")

    def entry(self, move_id: int) -> Optional[dict[str, Any]]:
        for e in self._entries:
            if e.get("id") == move_id:
                return e
        return None

    def record(self, move: dict[str, Any], ok: bool, detail: str) -> dict[str, Any]:
        entry = {
            "id": move["id"],
            "from_project_rel": move["from_project_rel"], "from_rel": move["from_rel"],
            "to_project_rel": move["to_project_rel"], "to_rel": move["to_rel"],
            "ok": bool(ok), "detail": detail[:512], "at": float(self._now()),
        }
        self._entries = [e for e in self._entries if e.get("id") != move["id"]] + [entry]
        self._entries = self._entries[-LEDGER_MAX_ENTRIES:]
        self._save()
        return entry

    def recent_excludes(self, subpath: Optional[str]) -> list[str]:
        """Old paths, relative to `subpath` (a lane A run root such as
        `Projects/2026/Base Drone`), of every move heard of in the last
        EXCLUDE_WINDOW_SECONDS. Applied or refused: both mean the server no
        longer wants the file there.

        SYNC-11 (resilience sweep 2026-08-28): every path is emitted in BOTH
        Unicode spellings, NFC and NFD, deduped. The dashboard's `from_rel`
        is NFC; a Mac's own filesystem hands the same name to rclone in NFD,
        and rclone matches an exclude rule against the bytes it reads off the
        disk -- so before this, a moved path with any diacritic was simply
        not excluded and lane A put it straight back on the NAS, the one
        failure this whole feature exists to stop (CR-90's lesson, CR-90
        itself being why it went unnoticed: CJK names never warn you). These
        are `-` rules, so the spelling that matches nothing costs nothing.
        Comparison/matching only: `apply_move` still uses the raw path."""
        if not subpath:
            return []
        wanted = subpath.replace("\\", "/").strip("/")
        if wanted.lower().startswith(PROJECTS_PREFIX.lower()):
            wanted = wanted[len(PROJECTS_PREFIX):]
        cutoff = float(self._now()) - EXCLUDE_WINDOW_SECONDS
        out: list[str] = []
        for e in self._entries:
            if float(e.get("at") or 0) < cutoff:
                continue
            if str(e.get("from_project_rel", "")).lower() != wanted.lower():
                continue
            rel = str(e.get("from_rel") or "")
            if not rel:
                continue
            for spelling in (unicodedata.normalize("NFC", rel),
                             unicodedata.normalize("NFD", rel)):
                if spelling not in out:
                    out.append(spelling)
        return out
