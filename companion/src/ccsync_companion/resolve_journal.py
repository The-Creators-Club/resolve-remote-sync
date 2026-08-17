"""Save point + undo journal for every media-pool edit the companion makes.

WHY THIS EXISTS (COMMERCIAL_READINESS.md item 9, 2026-08-17). The companion
rewrites an editor's project database from four places -- the fixer's FIX ALL,
the automatic non-canonical relink, the automatic proxy repoint, and the
post-import canonicaliser -- and two of those four are UNPROMPTED. Until this
module there was no `SaveProject`, no exported copy, and no record of what
was changed: a wrong `local_root`, a stale canonical prefix or a bad proxy
convention rewrote hundreds of clip paths with nothing to roll back to and
nothing to read afterwards. `ReplaceClip` has no inverse in Resolve's UI
either -- Undo does not cover a scripted relink.

Two guarantees, both cheap:

  1. A SAVE POINT before the first edit of a batch. `ProjectManager.SaveProject()`
     so the editor's own work is on disk before we touch anything, then
     `ProjectManager.ExportProject()` into `~/.ccsync/resolve_edits/<project>/`
     so there is a `.drp` to import if the whole pass was wrong. Export is
     BEST EFFORT: older API builds do not have it, a collaboration project
     refuses it, and neither may stop a relink that fixes Media Offline.
  2. A JOURNAL of the edits themselves -- old path, new path, which code path
     asked -- so `undo_last_relink()` can put every clip back with the
     inverse `ReplaceClip`, and so a support session can read what happened
     even when the export was refused.

The journal is the deliverable that always works; the export is the one that
is nicer when it does. Nothing here raises: this is a safety net bolted onto
the thing that keeps footage online, and a net that can throw is worse than
no net at all.

Batching: edits land in ONE file per project per burst (`SESSION_GAP_SECONDS`
of quiet starts a new one), because "undo the last relink" means the last
pass, not the last clip. FIX ALL over 158 clips is one file, one save point,
one undo.

Rate limiting lives here too. The unprompted paths may run at most once per
`AUTOMATIC_MIN_INTERVAL_SECONDS` per project per source: a misconfigured
machine used to re-offer the same rewrite every poll, and an editor cannot
consent to something that happens every 30 seconds.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("ccsync.resolve_journal")

JOURNAL_DIRNAME = "resolve_edits"

# A burst of edits shares one journal file and one save point. Two minutes:
# longer than the gap between clips in a FIX ALL (a multi-GB copy sits
# between them) and far shorter than the gap between two separate passes.
SESSION_GAP_SECONDS = 120.0

# How often a save point is worth taking for the same project. Exporting a
# large project is seconds of Resolve's main thread, and a burst that keeps
# rolling over would export on every clip.
SAVE_POINT_INTERVAL_SECONDS = 900.0

# The unprompted paths (auto canonical relink, auto proxy repoint) may act at
# most this often per project. Nothing stops a PROMPTED path -- FIX ALL is
# the editor pressing a button.
AUTOMATIC_MIN_INTERVAL_SECONDS = 900.0

# Bound on one journal file. A pathological pass (every clip in a 4,000-clip
# project) must not write an unbounded file into a home directory; the log
# still carries every line.
MAX_ENTRIES_PER_SESSION = 5000

# Journals older than this are swept on the next write. Long enough that
# "it went wrong last week" is still answerable, short enough that a machine
# doing daily FIX ALLs does not accrete forever.
RETENTION_DAYS = 60

# The edit kinds. Strings because they are read back out of JSON by an undo
# that may be running a NEWER companion than the one that wrote the file.
KIND_REPLACE_CLIP = "replace_clip"
KIND_LINK_PROXY = "link_proxy_media"
KIND_UNLINK_PROXY = "unlink_proxy_media"

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_lock = threading.Lock()
# {project slug: {"path": Path, "last": float}} -- the open burst per project.
_sessions: dict[str, dict[str, Any]] = {}
# {project slug: float} -- when the last save point was taken.
_save_points: dict[str, float] = {}
# {(project slug, source): float} -- the automatic-path rate limiter.
_automatic_at: dict[tuple[str, str], float] = {}


def journal_root() -> Path:
    """`~/.ccsync/resolve_edits`. Read through expanduser every call rather
    than captured at import: the test suite redirects HOME per test, and a
    module-level constant would write the journal into the developer's real
    home (conftest's `_isolate_ccsync_home` exists for exactly this)."""
    return Path(os.path.expanduser("~")) / ".ccsync" / JOURNAL_DIRNAME


def project_slug(project_name: Any) -> str:
    """A directory name for a Resolve project. Never empty, never a path.

    Resolve project names carry `/`, `:` and trailing dots freely ("FF4 /
    interviews v2."), and any of those would escape the journal directory or
    make an unopenable name on Windows."""
    text = str(project_name or "").strip()
    if not text:
        return "_unknown"
    text = _UNSAFE.sub("_", text).rstrip(". ")
    return text[:80] or "_unknown"


def reset_for_tests() -> None:
    """Drop the in-memory burst/rate-limit state. The module keeps its state
    in globals (one companion, one Resolve), so a test that does not clear it
    inherits the previous test's open session."""
    with _lock:
        _sessions.clear()
        _save_points.clear()
        _automatic_at.clear()


# -- rate limiting ---------------------------------------------------------

def allow_automatic(project_name: Any, source: str,
                    min_interval: Optional[float] = None,
                    clock: Callable[[], float] = time.monotonic) -> bool:
    """May an UNPROMPTED path rewrite this project again yet?

    First call for a (project, source) always wins; after that the pass is
    refused until `min_interval` has passed. The refusal is silent to the
    editor on purpose -- the condition that triggers it (clips still stored
    under a local spelling) is either fixed by the pass that just ran or is
    something no amount of repetition will fix, and a toast per poll is the
    behaviour this limiter exists to stop.
    """
    # Read off the module rather than defaulted in the signature: a default
    # argument binds at def time, so a caller (or a test) that changes
    # AUTOMATIC_MIN_INTERVAL_SECONDS would be silently ignored.
    if min_interval is None:
        min_interval = AUTOMATIC_MIN_INTERVAL_SECONDS
    try:
        key = (project_slug(project_name), str(source or ""))
        now = float(clock())
        with _lock:
            last = _automatic_at.get(key)
            if last is not None and (now - last) < float(min_interval):
                return False
            _automatic_at[key] = now
        return True
    except Exception:
        # A broken limiter must not stop a relink that fixes Media Offline.
        log.debug("resolve journal: rate limiter failed", exc_info=True)
        return True


def seconds_until_automatic(project_name: Any, source: str,
                            min_interval: Optional[float] = None,
                            clock: Callable[[], float] = time.monotonic) -> float:
    """How long the automatic path is still barred for. 0.0 when it may run.
    Read-only: unlike allow_automatic() this does NOT claim the slot."""
    if min_interval is None:
        min_interval = AUTOMATIC_MIN_INTERVAL_SECONDS
    try:
        key = (project_slug(project_name), str(source or ""))
        with _lock:
            last = _automatic_at.get(key)
        if last is None:
            return 0.0
        left = float(min_interval) - (float(clock()) - last)
        return left if left > 0 else 0.0
    except Exception:
        return 0.0


# -- the journal itself ----------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _session_path(slug: str, now: float) -> Path:
    stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%Y%m%d-%H%M%S")
    return journal_root() / slug / f"{stamp}.json"


def _read(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write(path: Path, data: dict[str, Any]) -> None:
    """Whole-file rewrite through a tmp+replace. The file is small (one
    burst) and rewriting it is what keeps it valid JSON after a crash --
    an append-per-line format would need its own reader for half a line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)


def open_session(project_name: Any, *, clock: Callable[[], float] = time.time,
                 backup: str = "", saved: Optional[bool] = None) -> Optional[Path]:
    """The journal file the next edit belongs in, creating it if the burst is
    new. Returns None when the journal cannot be written at all (a read-only
    home is not a reason to refuse a relink)."""
    slug = project_slug(project_name)
    now = float(clock())
    try:
        with _lock:
            open_at = _sessions.get(slug)
            if open_at is not None and (now - float(open_at["last"])) <= SESSION_GAP_SECONDS:
                open_at["last"] = now
                path = Path(open_at["path"])
                if backup or saved is not None:
                    data = _read(path)
                    if backup:
                        data["backup"] = backup
                    if saved is not None:
                        data["saved"] = bool(saved)
                    _write(path, data)
                return path
            path = _session_path(slug, now)
            _write(path, {
                "project": str(project_name or ""),
                "started": _iso_now(),
                "backup": backup,
                "saved": bool(saved) if saved is not None else False,
                "entries": [],
            })
            _sessions[slug] = {"path": str(path), "last": now}
        _sweep(slug, now)
        return path
    except Exception:
        log.warning("resolve journal: could not open a journal for %r -- the edit "
                    "will still be made, but it will not be undoable",
                    project_name, exc_info=True)
        return None


def record(kind: str, project_name: Any, *, clip_name: str = "",
           old_path: Any = "", new_path: Any = "", source: str = "",
           clip_path: Any = "",
           clock: Callable[[], float] = time.time) -> Optional[Path]:
    """Append one edit to the open journal. Never raises, never blocks."""
    path = open_session(project_name, clock=clock)
    if path is None:
        return None
    try:
        data = _read(path)
        entries = data.get("entries")
        if not isinstance(entries, list):
            entries = []
        if len(entries) >= MAX_ENTRIES_PER_SESSION:
            return path
        entries.append({
            "ts": _iso_now(),
            "kind": str(kind),
            "source": str(source or ""),
            "clip": str(clip_name or ""),
            # The clip's ORIGINAL path. Identical to "new" for a relink, but
            # for a proxy repoint old/new are PROXY paths and this is the only
            # thing that identifies which clip they belong to on the way back.
            "clip_path": str(clip_path or new_path or ""),
            "old": str(old_path or ""),
            "new": str(new_path or ""),
        })
        data["entries"] = entries
        _write(path, data)
        return path
    except Exception:
        log.debug("resolve journal: could not record %s", kind, exc_info=True)
        return path


def note_save_point(project_name: Any, *, saved: bool, backup: str = "",
                    clock: Callable[[], float] = time.time) -> None:
    """Stamp the open journal with what the save point achieved."""
    open_session(project_name, clock=clock, backup=backup, saved=saved)


def save_point_due(project_name: Any,
                   interval: float = SAVE_POINT_INTERVAL_SECONDS,
                   clock: Callable[[], float] = time.monotonic) -> bool:
    """Is a SaveProject+export worth taking for this project right now?

    Claims the slot when it answers True, so two threads entering
    replace_clip at once do not both export."""
    try:
        slug = project_slug(project_name)
        now = float(clock())
        with _lock:
            last = _save_points.get(slug)
            if last is not None and (now - last) < float(interval):
                return False
            _save_points[slug] = now
        return True
    except Exception:
        return False


# -- reading it back -------------------------------------------------------

def sessions(project_name: Any = None) -> list[Path]:
    """Every journal file, newest last. Filenames are UTC timestamps, so
    lexical order IS chronological order."""
    root = journal_root()
    try:
        if project_name is not None:
            dirs = [root / project_slug(project_name)]
        else:
            dirs = sorted(p for p in root.iterdir() if p.is_dir())
    except Exception:
        return []
    out: list[Path] = []
    for directory in dirs:
        try:
            out.extend(sorted(p for p in directory.glob("*.json") if p.is_file()))
        except Exception:
            continue
    out.sort(key=lambda p: (p.name, str(p.parent)))
    return out


def latest_session(project_name: Any = None) -> Optional[Path]:
    found = sessions(project_name)
    return found[-1] if found else None


def read_session(path: Any) -> dict[str, Any]:
    """The journal file as a dict, `{}` when it cannot be read."""
    return _read(Path(path))


def describe_latest(project_name: Any = None) -> str:
    """One line for a tray menu / popup: what the last pass did."""
    path = latest_session(project_name)
    if path is None:
        return ""
    data = read_session(path)
    entries = data.get("entries") or []
    if not entries:
        return ""
    return (f"{len(entries)} clip path(s) in “{data.get('project') or 'a project'}”, "
            f"{data.get('started') or 'unknown time'}")


def _sweep(slug: str, now: float) -> None:
    """Delete journals past RETENTION_DAYS for this project. Best effort:
    the sweep runs on the write path, so a failure must cost nothing."""
    cutoff = now - (RETENTION_DAYS * 86400.0)
    try:
        directory = journal_root() / slug
        for path in directory.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue
    except Exception:
        return
