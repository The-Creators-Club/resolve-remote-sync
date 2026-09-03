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

# ...and at most this many times per project per day, however long the tray
# has been up. RES-2 (resilience sweep 2026-08-28): the 15-minute bar bounds
# a LOOP, not a day. A machine with a wrong canonical_prefix/local_root is
# wrong every 15 minutes, so it was entitled to ~96 unprompted rewrites of
# hundreds of clip paths a day, each one a project-database write the editor
# never asked for. The cap is what turns "keep re-offering" into "tell
# somebody".
AUTOMATIC_MAX_PER_DAY = 8

# Where the two bars above are remembered across a restart. RES-2: these
# lived in module globals, so an OTA, a crash, an EULA park or the editor
# quitting and reopening the tray reset them -- and every one of those is
# routine, which is why CLAUDE.md's rule is "never make a safety latch
# in-memory-only" (lane B's breaker is on disk for exactly this reason).
AUTO_STATE_FILENAME = "resolve_auto.json"

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
# {(project slug, source): float} -- the automatic-path rate limiter. WALL
# clock (time.time), not monotonic, because it is persisted: a monotonic
# stamp means nothing to the next process.
_automatic_at: dict[tuple[str, str], float] = {}
# {project slug: {"day": "YYYY-MM-DD", "count": int, "held": int}} -- the
# per-day cap, per project (not per source: two sources rewriting the same
# project all day is the same fault seen twice).
_automatic_daily: dict[str, dict[str, Any]] = {}
# False until the two dicts above have been read back off disk once. Lazy,
# not at import: the test suite redirects HOME per test, and importing this
# module must not touch a home directory at all.
_auto_state_loaded = False


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
    """Drop the in-memory burst/rate-limit state AND the persisted copy. The
    module keeps its state in globals (one companion, one Resolve), so a test
    that does not clear it inherits the previous test's open session."""
    global _auto_state_loaded
    with _lock:
        _sessions.clear()
        _save_points.clear()
        _automatic_at.clear()
        _automatic_daily.clear()
        _auto_state_loaded = False
        try:
            auto_state_path().unlink()
        except (OSError, NotImplementedError):
            # NotImplementedError: a test that fakes `os.name = "posix"` on
            # Windows makes Path() pick PosixPath, which cannot be built
            # here; the fixture tears down before the monkeypatch restores.
            pass


# -- the persisted half of the rate limiter (RES-2, 2026-08-28) ------------

def auto_state_path() -> Path:
    """`~/.ccsync/state/resolve_auto.json`. Expanded per call for the reason
    journal_root() is."""
    return Path(os.path.expanduser("~")) / ".ccsync" / "state" / AUTO_STATE_FILENAME


def _day_key(now: float) -> str:
    """The day a timestamp belongs to, in UTC. UTC and not local time so a
    DST change or a travelling laptop cannot hand a machine a second
    allowance of automatic rewrites."""
    return datetime.fromtimestamp(float(now), timezone.utc).strftime("%Y-%m-%d")


def _load_auto_state_locked(now: float) -> None:
    """Read the persisted limiter back, once. Caller holds `_lock`.

    Never raises and never refuses on unreadable state: a limiter that
    cannot load must degrade to "nothing remembered", not to a relink that
    never runs (Media Offline is the worse failure)."""
    global _auto_state_loaded
    _auto_state_loaded = True
    data = _read(auto_state_path())
    if not data:
        return
    corrected = False
    stamps = data.get("automatic_at")
    if isinstance(stamps, dict):
        for slug, sources in stamps.items():
            if not isinstance(sources, dict):
                continue
            for source, value in sources.items():
                try:
                    stamp = float(value)
                except (TypeError, ValueError):
                    continue
                # A stamp in the FUTURE is a clock that has been put back
                # (or a file copied off another machine). Treated as "now",
                # which bars the pass for one interval rather than either
                # letting it through or barring it until the date arrives.
                # The correction is written back, or the SAME future stamp
                # would be re-clamped to each new "now" forever and the pass
                # would never be allowed again.
                if stamp > float(now):
                    stamp = float(now)
                    corrected = True
                _automatic_at[(str(slug), str(source))] = stamp
    daily = data.get("daily")
    if isinstance(daily, dict):
        for slug, bucket in daily.items():
            if not isinstance(bucket, dict):
                continue
            try:
                _automatic_daily[str(slug)] = {
                    "day": str(bucket.get("day", "")),
                    "count": int(bucket.get("count", 0)),
                    "held": int(bucket.get("held", 0)),
                }
            except (TypeError, ValueError):
                continue
    if corrected:
        _save_auto_state_locked()


def _ensure_auto_state_locked(now: float) -> None:
    if not _auto_state_loaded:
        _load_auto_state_locked(now)


def _save_auto_state_locked() -> None:
    """Persist the limiter. Caller holds `_lock`. Never raises."""
    stamps: dict[str, dict[str, float]] = {}
    for (slug, source), value in _automatic_at.items():
        stamps.setdefault(slug, {})[source] = value
    try:
        _write(auto_state_path(), {"automatic_at": stamps, "daily": _automatic_daily})
    except Exception:
        log.debug("resolve journal: could not persist the automatic-pass limiter",
                  exc_info=True)


# -- rate limiting ---------------------------------------------------------

def allow_automatic(project_name: Any, source: str,
                    min_interval: Optional[float] = None,
                    clock: Callable[[], float] = time.time,
                    max_per_day: Optional[int] = None) -> bool:
    """May an UNPROMPTED path rewrite this project again yet?

    First call for a (project, source) always wins; after that the pass is
    refused until `min_interval` has passed, and refused for the rest of the
    day once the project has had `max_per_day` of them. The refusal is silent
    to the editor on purpose -- the condition that triggers it (clips still
    stored under a local spelling) is either fixed by the pass that just ran
    or is something no amount of repetition will fix, and a toast per poll is
    the behaviour this limiter exists to stop. The DAILY cap does log a
    WARNING, because by then it is a machine that needs a person.

    The clock is wall clock (`time.time`), not monotonic: both bars are
    persisted to auto_state_path() and survive a restart (RES-2, 2026-08-28),
    and a monotonic stamp means nothing to the next process.
    """
    # Read off the module rather than defaulted in the signature: a default
    # argument binds at def time, so a caller (or a test) that changes
    # AUTOMATIC_MIN_INTERVAL_SECONDS would be silently ignored.
    if min_interval is None:
        min_interval = AUTOMATIC_MIN_INTERVAL_SECONDS
    if max_per_day is None:
        max_per_day = AUTOMATIC_MAX_PER_DAY
    try:
        slug = project_slug(project_name)
        key = (slug, str(source or ""))
        now = float(clock())
        with _lock:
            _ensure_auto_state_locked(now)
            last = _automatic_at.get(key)
            if last is not None and (now - min(last, now)) < float(min_interval):
                return False
            day = _day_key(now)
            bucket = _automatic_daily.get(slug) or {}
            count = int(bucket.get("count", 0)) if bucket.get("day") == day else 0
            held = int(bucket.get("held", 0)) if bucket.get("day") == day else 0
            if int(max_per_day) > 0 and count >= int(max_per_day):
                _automatic_daily[slug] = {"day": day, "count": count, "held": held + 1}
                _save_auto_state_locked()
                log.warning(
                    "resolve journal: %s has already had %d unprompted rewrites "
                    "today, so this one is held (%d held so far) -- this looks "
                    "like a configuration problem, Tray > Settings > COPY "
                    "DIAGNOSTICS FOR YOUR ADMIN",
                    slug, count, held + 1,
                )
                return False
            _automatic_at[key] = now
            _automatic_daily[slug] = {"day": day, "count": count + 1, "held": held}
            _save_auto_state_locked()
        return True
    except Exception:
        # A broken limiter must not stop a relink that fixes Media Offline.
        log.debug("resolve journal: rate limiter failed", exc_info=True)
        return True


def seconds_until_automatic(project_name: Any, source: str,
                            min_interval: Optional[float] = None,
                            clock: Callable[[], float] = time.time) -> float:
    """How long the automatic path is still barred for. 0.0 when it may run.
    Read-only: unlike allow_automatic() this does NOT claim the slot, and it
    does not answer for the DAILY cap (which is not a countdown)."""
    if min_interval is None:
        min_interval = AUTOMATIC_MIN_INTERVAL_SECONDS
    try:
        key = (project_slug(project_name), str(source or ""))
        with _lock:
            _ensure_auto_state_locked(float(clock()))
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


def _tmp_path(path: Path) -> Path:
    """The scratch file `_write` renames into place.

    bug-hunt-2026-09-03 comp-resolve-1: pid + thread id, because a fixed
    `<file>.json.tmp` is shared by every writer and on Windows the loser of
    that race gets a PermissionError out of os.replace rather than merely a
    lost entry. Not swept: `SWEPT_SUFFIXES` matches `*.json`, and a tmp that
    is left behind is unlinked by the writer that made it.
    """
    return path.with_name(f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")


def _write(path: Path, data: dict[str, Any]) -> None:
    """Whole-file rewrite through a tmp+replace. The file is small (one
    burst) and rewriting it is what keeps it valid JSON after a crash --
    an append-per-line format would need its own reader for half a line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(path)
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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
        # bug-hunt-2026-09-03 comp-resolve-1: the read-append-write is one
        # critical section. Both callers (replace_clip, link_proxy_media)
        # record OUTSIDE `_API_LOCK`, so FIX ALL on the tray thread and the
        # 120 s proxy-relink pass really are inside here at once, and an
        # unlocked RMW loses whichever entry lost the os.replace race -- an
        # edit undo_last_relink would then silently not undo.
        with _lock:
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
                # The clip's ORIGINAL path. Identical to "new" for a relink,
                # but for a proxy repoint old/new are PROXY paths and this is
                # the only thing that identifies which clip they belong to on
                # the way back.
                "clip_path": str(clip_path or new_path or ""),
                "old": str(old_path or ""),
                "new": str(new_path or ""),
            })
            data["entries"] = entries
            _write(path, data)
        return path
    except Exception:
        # An entry that could not be journalled is an edit that cannot be
        # undone (bug-hunt-2026-09-03 comp-resolve-1): open_session says that
        # out loud at WARNING, and so must this.
        log.warning("resolve journal: could not record %s -- that edit will "
                    "not be undoable", kind, exc_info=True)
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


# -- naming one journal from off the machine (SYS-15b, 2026-08-29) ---------
#
# The dashboard's admin-side undo has to NAME a journal, and the only thing
# it knows about this machine is what this machine has told it. So a journal
# gets an id -- "<project slug>/<file name>" -- which travels in the report,
# comes back in the command, and is resolved here rather than anywhere near a
# path from the wire.


def journal_id(path: Any) -> str:
    """The id for one journal file: its project directory and its name."""
    p = Path(path)
    return f"{p.parent.name}/{p.name}"


def session_by_id(text: Any) -> Optional[Path]:
    """The journal named by `journal_id`, or None.

    REFUSES ANYTHING THAT IS NOT EXACTLY TWO PLAIN SEGMENTS. This value
    arrives in a report reply from the network, and the file it names is
    about to be read and replayed against Resolve's media pool: `..`, an
    absolute path or a drive letter must not resolve to anything at all.
    """
    raw = str(text or "").strip().replace("\\", "/")
    parts = [p for p in raw.split("/") if p]
    if len(parts) != 2 or any(p in (".", "..") for p in parts):
        return None
    slug, name = parts
    if not name.endswith(".json") or slug != project_slug(slug):
        return None
    root = journal_root()
    candidate = root / slug / name
    try:
        if not candidate.resolve().is_relative_to(root.resolve()):
            return None
        return candidate if candidate.is_file() else None
    except (OSError, ValueError):
        return None


def summaries(limit: int = 20) -> list[dict[str, Any]]:
    """The newest journals on this machine, as the dashboard is told about
    them: names and counts, NEVER the entries.

    A journal's entries are this editor's own paths, and the dashboard has no
    use for them -- an admin picks a change to undo by project and time. Never
    raises: this runs on the reporter thread.
    """
    out: list[dict[str, Any]] = []
    try:
        found = sessions()
    except Exception:
        return []
    for path in reversed(found[-max(1, int(limit)):]):
        try:
            data = read_session(path)
            entries = data.get("entries") or []
            sources = sorted({str(e.get("source") or "") for e in entries
                              if isinstance(e, dict) and e.get("source")})
            out.append({
                "id": journal_id(path),
                "project": str(data.get("project") or ""),
                "started": str(data.get("started") or ""),
                "entries": len(entries),
                "sources": ",".join(sources)[:128],
            })
        except Exception:
            continue
    return out


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


# What the sweep is allowed to delete. `.drp` as well as `.json`
# (comp-resolve-4, 2026-08-21): save_project() writes its exported rollback
# copy into this same directory, up to once per project per 15 minutes of
# editing, and only the journals were ever swept -- so a machine that
# auto-relinks regularly accreted a copy of the whole project DATABASE (tens
# of MB each) in the editor's home forever, while
# docs/RESOLVE_EDIT_SAFETY.md's Housekeeping section told their admin that
# "journals and exports older than 60 days are swept on the next write".
SWEPT_SUFFIXES = ("*.json", "*.drp")


def _sweep(slug: str, now: float) -> None:
    """Delete journals and rollback exports past RETENTION_DAYS for this
    project. Best effort: the sweep runs on the write path, so a failure must
    cost nothing."""
    cutoff = now - (RETENTION_DAYS * 86400.0)
    try:
        directory = journal_root() / slug
        for pattern in SWEPT_SUFFIXES:
            for path in directory.glob(pattern):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError:
                    continue
    except Exception:
        return
