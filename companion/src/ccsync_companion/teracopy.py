"""Drive TeraCopy, and find out what it actually did (Windows only).

A port of footage-sorter `lib/teracopy.js` (itself from the Auto-Backup
Utility), restored 2026-11-09 as the card copier on Windows: the Python
copier in card_copy.py reads and writes strictly in turn through one buffer,
which is too slow for footage going over SMB to the NAS. card_copy.py picks
this module on a Windows PC that has TeraCopy with verify on, and keeps its
own copier for a Mac or a PC without.

TeraCopy is a SINGLE-INSTANCE application. Once an instance is running, every
further TeraCopy.exe is only a stub that hands its file list to that instance
over IPC and exits within a second. So `spawn; wait; read the exit code` does
not wait for the copy and does not report it: it waits for the stub and gets
0 whatever happens to the files. Every job after the first would fire at
once (a card's worth of jobs running concurrently off one card, copy and
verify interleaved) and every job would report OK before a byte had moved.

The authoritative record is the SQLite database TeraCopy writes per job under
%APPDATA%\\TeraCopy\\History. `read_status` reads it; `TeraCopy.wait_for_job`
blocks until that record says the copy AND the verify pass finished, which
restores one-job-at-a-time sequencing and gives a truthful result. If the
record cannot be read the wait falls back to "TeraCopy has exited" and the
result to a presence-and-size check of the destination, which is WEAKER than
TeraCopy's own hash verify and is therefore always reported unverified.

The history database (observed, not guessed; tests/test_teracopy.py builds
fixtures to the same shape):

  Run     one row per phase. mode 1 = copy, mode 4 = verify. (mode, target,
          options, started, finished, speed, results); `finished` stays NULL
          until the phase really completes.
  Files   the job's file list (Source, Offset, Visibility, Size, Attributes,
          IsFolder, Created, Modified, Accessed, Checksum, Marked, Selected).
          No id column: the implicit rowid is the id.
  Target  one row per file per destination (file, id, result, hash, message,
          filename), UNIQUE(file, id). `file` is the Files ROWID. `filename`
          is the name actually written and is '' unless TeraCopy renamed it.
  Source  (file, result, hash, message); result is 10 in every row ever seen,
          so it is not used.

Target.result, established empirically:
  3  copied AND hash-verified   <- the only success state
  1  copied, not yet verified
  2  queued, not yet copied

SAFETY: this module writes only list files into its list directory and
whatever TeraCopy itself copies into the destination it is handed. TeraCopy
writes in place (no `.partial`), exactly as it did under the Node original;
a job that stops mid-file leaves a short file at the final name, which the
sorter's next plan sees as `partial` and resumes.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("ccsync.teracopy")

RESULT_OK = 3            # copied AND hash-verified: the only success state
RESULT_COPIED = 1        # copied, verify not (yet) done
MODE_COPY = 1
MODE_VERIFY = 4

SWITCH_SKIP = "/SkipAll"                       # copy: an existing file is NEVER replaced
SWITCH_OVERWRITE_DIFF = "/OverwriteDiffSize"   # resume only (run.js conflictSwitch)
SWITCH_RENAME = "/RenameCopied"                # collision (run.js collisionSwitch)
DEFAULT_SWITCH = SWITCH_SKIP

# The default wait limit for one job: generous, scaled to its bytes.
MIN_WAIT_SECONDS = 30 * 60
ASSUMED_BYTES_PER_SECOND = 20 * 1024 * 1024

STANDARD_EXES = (
    r"C:\Program Files\TeraCopy\TeraCopy.exe",
    r"C:\Program Files (x86)\TeraCopy\TeraCopy.exe",
)

# Result codes of copy_group, as in the original.
CODE_OK = 0
CODE_UNVERIFIED = 10
CODE_MISSING = 11
CODE_UNCONFIRMED = 12
CODE_STOPPED = 13        # the caller asked to stop waiting (a halt, a cancel); TeraCopy is left running


def wait_limit_seconds(total_bytes: int) -> float:
    """At least 30 minutes, plus the time the bytes take at 20 MB/s."""
    return MIN_WAIT_SECONDS + max(0, int(total_bytes or 0)) / ASSUMED_BYTES_PER_SECOND


def norm(path: Any) -> str:
    """Compare paths the way Windows does: case-blind, trailing separators ignored."""
    return str(path if path is not None else "").rstrip("\\/").lower()


def _created_seconds(file: Path) -> float:
    """When the database FILE was created, in unix seconds.

    A job is matched to its database by the file's creation time, never by the
    timestamps inside it: the file NAME is stamped in UTC while Run.started is
    LOCAL time suffixed 'Z', so comparing a real UTC cutoff against Run.started
    silently rejects the job's own record west of Greenwich.
    """
    st = file.stat()
    return float(getattr(st, "st_birthtime", None) or st.st_ctime)


def _open_ro(file: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{file.resolve().as_uri()}?mode=ro", uri=True, timeout=1.0)


def _blank(state: str, error: Optional[str] = None) -> dict[str, Any]:
    return {"state": state, "found": False, "copy_done": False, "verify_seen": False,
            "verify_done": False, "total": 0, "ok": 0, "bad": 0, "db_path": None,
            "db_name": None, "error": error}


def read_status(history_dir: Any, dest: Any, since: float,
                sources: Optional[list[str]] = None,
                exclude: Optional[set[str]] = None) -> dict[str, Any]:
    """The real status of one TeraCopy job into `dest` submitted at `since`.

    `state` is one of: missing (no database for this job yet), locked (a fresh
    database exists but could not be read: being written, or half-created; a
    locked database must NEVER be reported as a finished job), queued (a fresh
    database but no Run row: behind other jobs), running (copy phase not
    finished), copied (copy finished, verify not appeared/finished) or done.

    `sources`: the files this job was given. A database whose file list is
    someone else's is skipped even when it copies into the same folder: two
    cards from one shoot day copy into one folder at the same time.

    `exclude`: database names that existed BEFORE this job was launched. The
    5 s slack on `since` would otherwise let a job launched right after an
    identical one (same folder, same files: a retry, a second pass) read its
    predecessor's finished record and return at once. (Found live 2026-11-09.)
    """
    mine = {norm(s) for s in sources} if sources else None

    def ours(db: sqlite3.Connection) -> bool:
        if not mine:
            return True
        row = db.execute("select Source from Files order by rowid limit 1").fetchone()
        if not row:
            return True                      # no files written yet: cannot tell, keep it
        first = norm(row[0])
        if first in mine:
            return True
        return any(first.startswith(m + "\\") or first.startswith(m + "/") for m in mine)

    try:
        cutoff = float(since) - 5            # slack for clock granularity
    except (TypeError, ValueError):
        return _blank("missing", "bad-since")
    if cutoff != cutoff:                     # NaN
        return _blank("missing", "bad-since")
    hist = Path(str(history_dir))
    try:
        if not hist.is_dir():
            return _blank("missing", "no-history-dir")
        names = sorted(os.listdir(hist))
    except OSError:
        return _blank("missing", "no-history-dir")

    target = norm(dest)
    locked = False
    queued = 0
    best: Optional[dict[str, Any]] = None
    for name in names:
        if not name.endswith(".db") or name == "main.db" or (exclude and name in exclude):
            continue
        file = hist / name
        try:
            created = _created_seconds(file)
        except OSError:
            continue
        if created < cutoff:
            continue                         # a job from before this one was submitted
        db = None
        try:
            db = _open_ro(file)
            runs = db.execute("select mode, target, started, finished from Run").fetchall()
            is_ours = ours(db)
        except sqlite3.Error:
            # Being written right now, or half-created. (A garbage file opens
            # fine and only fails on the first query, so the query is in this
            # try.) A locked database must never be reported as finished.
            if db is not None:
                _close(db)
            locked = True
            continue
        if not is_ours:
            _close(db)
            continue
        if not runs:
            queued += 1                      # created at submit, Run row at start
            _close(db)
            continue
        if norm(runs[0][1] or "") != target:
            _close(db)
            continue
        if best is None or created > best["created"]:
            if best:
                _close(best["db"])
            best = {"name": name, "file": file, "runs": runs, "created": created, "db": db}
        else:
            _close(db)

    if best is None:
        if locked:
            return _blank("locked")
        return _blank("queued" if queued else "missing")

    runs = best["runs"]
    copy_done = any(r[0] == MODE_COPY and r[3] for r in runs)
    verify_seen = any(r[0] == MODE_VERIFY for r in runs)
    verify_done = any(r[0] == MODE_VERIFY and r[3] for r in runs)
    total = ok = bad = 0
    try:
        total = int(best["db"].execute("select count(*) from Files where IsFolder = 0").fetchone()[0])
        for result, n in best["db"].execute("select result, count(*) from Target group by result"):
            if result == RESULT_OK:
                ok += int(n)
            else:
                bad += int(n)
    except sqlite3.Error:
        pass                                 # half-written tables: 'bad' absorbs it
    finally:
        _close(best["db"])
    # A file with no Target row has not been reached; count it as outstanding
    # so `ok == total` is the only way a job is called clean.
    bad += max(0, total - ok - bad)
    state = "done" if (copy_done and verify_done) else ("copied" if copy_done else "running")
    return {"state": state, "found": True, "copy_done": copy_done, "verify_seen": verify_seen,
            "verify_done": verify_done, "total": total, "ok": ok, "bad": bad,
            "db_path": str(best["file"]), "db_name": best["name"], "error": None}


def _close(db: sqlite3.Connection) -> None:
    try:
        db.close()
    except sqlite3.Error:
        pass


def harvest(db_path: Any) -> list[dict[str, Any]]:
    """Per-file receipts from a job database: what TeraCopy says it did to each
    file. A Files row with no Target row was never reached (result None)."""
    db = _open_ro(Path(str(db_path)))
    try:
        rows = db.execute(
            "select f.rowid, f.Source, f.Size, f.IsFolder, t.result, t.hash, t.filename, t.message"
            " from Files f left join Target t on t.file = f.rowid order by f.rowid").fetchall()
    finally:
        _close(db)
    out = []
    for _rid, source, size, is_folder, result, hsh, filename, message in rows:
        out.append({
            "source": source,
            "size": None if size is None else int(size),
            "is_folder": bool(is_folder),
            "result": None if result is None else int(result),
            "verified": result == RESULT_OK,
            "hash": hsh or None,
            "filename": filename or None,
            "message": message or None,
        })
    return out


def parse_options_ini(text: str) -> dict[str, dict[str, str]]:
    """Minimal INI: `[Section]`, `key=value`, `;`/`#` comments."""
    sections: dict[str, dict[str, str]] = {"": {}}
    current = ""
    for raw in str(text or "").lstrip("\ufeff").splitlines():
        line = raw.strip()
        if not line or line[0] in ";#":
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            sections.setdefault(current, {})
            continue
        key, eq, value = line.partition("=")
        if not eq or not key.strip():
            continue
        sections[current][key.strip()] = value.strip()
    return sections


def ini_get(sections: dict[str, dict[str, str]], section: str, key: str) -> Optional[str]:
    """Case-insensitive lookup into parse_options_ini's result; None when absent."""
    for sname, bag in sections.items():
        if sname.lower() == section.lower():
            for kname, value in bag.items():
                if kname.lower() == key.lower():
                    return value
    return None


def copy_command(exe: str, list_file: str, dest: str, switch: str) -> Optional[str]:
    """The exact command line for a copy job, or None when unusable.

    TeraCopy wants ONE verbatim command line, `"<exe>" Copy *"<list>" "<dest>"
    <switch> /Close`, with the star OUTSIDE the quotes. It is handed to
    CreateProcess as a single string (never an argv list, which Python would
    re-quote). Windows paths cannot contain a quote, so one could only be a
    corrupt entry and must not reach the command line.
    """
    parts = [str(p if p is not None else "") for p in (exe, list_file, dest, switch)]
    if any((not p) or '"' in p for p in parts):
        return None
    return f'"{parts[0]}" Copy *"{parts[1]}" "{parts[2]}" {parts[3]} /Close'


def sanitise_tag(tag: Any) -> str:
    out = "".join(c if (c.isascii() and (c.isalnum() or c in "_-")) else "_" for c in str(tag or ""))
    return out.strip("_") or "job"


def _appdata() -> str:
    return os.environ.get("APPDATA", "")


def find_exe(cfg: Optional[dict[str, Any]] = None) -> str:
    """TeraCopy.exe: config `teracopy_path`, else the standard Program Files
    locations. "" when there is none."""
    configured = str((cfg or {}).get("teracopy_path") or "").strip()
    if configured:
        return configured if os.path.isfile(configured) else ""
    for cand in STANDARD_EXES:
        if os.path.isfile(cand):
            return cand
    return ""


def default_history_dir() -> str:
    return os.path.join(_appdata(), "TeraCopy", "History")


def default_options_ini() -> str:
    return os.path.join(_appdata(), "TeraCopy", "Options.ini")


def verify_is_on(options_ini: str) -> tuple[bool, Optional[str]]:
    """-> (TestAlways=1 under [Transfer], a warning when that cannot be said)."""
    try:
        text = Path(options_ini).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False, (f"TeraCopy Options.ini not found at {options_ini}: launch TeraCopy "
                       f"once, then re-check")
    on = str(ini_get(parse_options_ini(text), "Transfer", "TestAlways") or "").strip() == "1"
    if not on:
        return False, ("TeraCopy verify is OFF: set TestAlways=1 under [Transfer] in "
                       "Options.ini, then restart TeraCopy so it reloads the file")
    return True, None


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def default_is_running() -> bool:
    """Is TeraCopy.exe running? The in-process snapshot first (audit
    comp-field-11, 2026-11-11: the wait loop asks every 5 s per lane for the
    whole copy, and each ask was a `tasklist` spawn), then, when that cannot
    answer, `tasklist /FI "IMAGENAME eq TeraCopy.exe" /NH`: a process filter,
    not a shell."""
    try:
        from . import resolve_prefs
        seen = resolve_prefs.process_state("TeraCopy.exe")
        if seen is not None:
            return seen
    except Exception:                                           # noqa: BLE001
        pass
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq TeraCopy.exe", "/NH"],
                             capture_output=True, text=True, timeout=15,
                             creationflags=_no_window())
    except (OSError, subprocess.SubprocessError):
        return False
    return "TeraCopy.exe" in (out.stdout or "")


def default_spawn(command: str) -> Any:
    """Launch the verbatim command line, detached; the stub's exit code means nothing."""
    flags = _no_window() | getattr(subprocess, "DETACHED_PROCESS", 0) \
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)


_LAUNCH_LOCK = threading.Lock()      # one stub hands its job over at a time (see launch)
LAUNCH_TRIES = 3                     # a job whose database never shows is launched again, twice
REGISTER_SECONDS = 20.0              # how long a launch waits for its job's history database
REGISTER_AGAIN_SECONDS = 6.0         # ...after a launch that never registered, and on every re-launch
BROKEN_MEMORY_SECONDS = 300.0        # how long a failed registration shortens the waits
MAYBE_POLLS = 12                     # our files, no run row for this long (3 s): queued, take it
_BROKEN_AT: Optional[float] = None
_CLAIMED: set[str] = set()           # history databases already taken by a launch
_CLAIMED_MAX = 4000


def _claim(name: str) -> None:
    if len(_CLAIMED) > _CLAIMED_MAX:
        _CLAIMED.clear()
    _CLAIMED.add(name)


class TeraCopy:
    """One TeraCopy install. Every seam (clock, sleep, process check, spawn,
    status reader, log) is injectable so the suite never launches TeraCopy,
    reads the real history or waits in real time."""

    def __init__(self, exe: str, *, history_dir: Optional[str] = None,
                 options_ini: Optional[str] = None, list_dir: Optional[str] = None,
                 poll_seconds: float = 5, start_grace_seconds: float = 120,
                 idle_grace_seconds: float = 60, verify_grace_seconds: float = 180,
                 timeout_minutes: float = 0,
                 spawn: Optional[Callable[[str], Any]] = None,
                 now: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep,
                 is_running: Optional[Callable[[], bool]] = None,
                 read_status_fn: Optional[Callable[..., dict[str, Any]]] = None,
                 log_fn: Optional[Callable[..., None]] = None) -> None:
        self.exe = exe
        self.history_dir = history_dir or default_history_dir()
        self.options_ini = options_ini or default_options_ini()
        self.list_dir = list_dir or os.path.join(
            os.environ.get("TEMP", "."), "ccsync-teracopy-lists")
        self.poll_seconds = float(poll_seconds)
        self.start_grace_seconds = float(start_grace_seconds)
        self.idle_grace_seconds = float(idle_grace_seconds)
        self.verify_grace_seconds = float(verify_grace_seconds)
        self.timeout_minutes = float(timeout_minutes)
        self._spawn = spawn or default_spawn
        self._now = now
        self._sleep = sleep
        self._is_running = is_running or default_is_running
        self._read_status = read_status_fn or (
            lambda dest, since, sources, exclude=None: read_status(
                self.history_dir, dest, since, sources, exclude))
        self._log = log_fn or (lambda msg, level="info": log.log(
            logging.WARNING if level == "warn" else logging.ERROR if level == "error"
            else logging.INFO, "%s", msg))

    # -- install ------------------------------------------------------------
    def check(self) -> dict[str, Any]:
        """Is TeraCopy installed, and will it verify what it copies?"""
        warnings: list[str] = []
        exe_present = os.path.isfile(self.exe)
        if not exe_present:
            warnings.append(f"TeraCopy not found at: {self.exe}")
        history_present = os.path.isdir(self.history_dir)
        if not history_present:
            warnings.append(
                f"TeraCopy history folder not found at {self.history_dir}: copies can then "
                f"only be checked by presence and size, never by TeraCopy's own hash verify")
        verify_on, why = verify_is_on(self.options_ini)
        if why:
            warnings.append(why)
        return {"ok": exe_present, "exe_present": exe_present,
                "history_dir_present": history_present, "verify_on": verify_on,
                "warnings": warnings}

    # -- launch / wait ------------------------------------------------------
    def _write_list(self, list_file: str, files: list[str]) -> None:
        """UTF-8, no BOM, one path per line; written to a temp name and renamed
        so TeraCopy can never open a half-written list."""
        # Unique per write, not per process: field mode runs several lanes off
        # one card in one process at once (a shared .tmp-<pid> name made two of
        # three lanes fail with "Permission denied", found live 2026-11-09).
        tmp = f"{list_file}.tmp-{os.getpid()}-{threading.get_ident()}-{uuid.uuid4().hex[:8]}"
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write("\r\n".join(files) + "\r\n")
        os.replace(tmp, list_file)

    def launch(self, files: list[str], dest: str, switch: str = DEFAULT_SWITCH,
               tag: str = "", should_stop: Optional[Callable[[], str]] = None) -> dict[str, Any]:
        """Write the list file and fire TeraCopy at it. Deliberately does NOT
        wait: this process is usually the IPC stub and waiting on it proves
        nothing. -> {since, list_file, pid}"""
        files = [str(f) for f in files if f]
        if not files:
            raise ValueError("teracopy: nothing to copy")
        if not dest:
            raise ValueError("teracopy: no destination")
        os.makedirs(dest, exist_ok=True)
        os.makedirs(self.list_dir, exist_ok=True)
        self._prune_lists()
        # Stamp the clock BEFORE launching so the status reader can tell this
        # job from an earlier one into the same folder.
        since = int(self._now())
        label = sanitise_tag(tag)
        # Never let one list replace another: claim the name atomically
        # (O_EXCL), because lanes launched in the same second from the same
        # card folder pick the same label and second.
        n = 1
        while True:
            name = f"{label}-{since}.txt" if n == 1 else f"{label}-{since}-{n}.txt"
            list_file = os.path.join(self.list_dir, name)
            try:
                os.close(os.open(list_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                break
            except FileExistsError:
                n += 1
        self._write_list(list_file, files)
        command = copy_command(self.exe, list_file, str(dest), switch or DEFAULT_SWITCH)
        if command is None:
            raise ValueError("teracopy: unusable path (empty, or contains a quote)")
        # ONE LAUNCH AT A TIME. Several TeraCopy.exe stubs handing jobs to the
        # single instance in the same moment lose all but one of them: three
        # field lanes launched together made one job and two silent no-shows
        # (found live 2026-11-09, creator-1). So launches are serialised, and
        # each waits until TeraCopy has REGISTERED its job (its history
        # database appears; it is created at submit, before the copy starts,
        # even when queued behind other jobs). The jobs still run side by side.
        #
        # A launch counts as REGISTERED only when the new history database lists THIS job's
        # files and destination: an empty database (TeraCopy woke and lost the job) and another
        # lane's late database are not it. A job whose database stays empty or never appears is
        # launched again (safe: /SkipAll never replaces a file, and a job that did register
        # twice finds its files already there). A TeraCopy that is cold has no History folder
        # yet: that is "wait", not "skip the wait". After a launch that never registered, the
        # next ones wait less, so a broken TeraCopy does not hold every lane for 20 s each.
        global _BROKEN_AT
        stopped = False
        pid = None
        with _LAUNCH_LOCK:
            known: set[str] = set()
            for attempt in range(LAUNCH_TRIES):
                try:
                    known = set(os.listdir(self.history_dir))
                except OSError:
                    known = set()
                self._log(f"TeraCopy ({label}): {command}")
                pid = None
                try:
                    child = self._spawn(command)
                    pid = getattr(child, "pid", None)
                except OSError as exc:
                    self._log(f"TeraCopy ({label}): could not launch: {exc}", "warn")
                if pid is None:
                    break
                recently_broken = _BROKEN_AT is not None and time.monotonic() - _BROKEN_AT < BROKEN_MEMORY_SECONDS
                seconds = REGISTER_SECONDS if (attempt == 0 and not recently_broken) else REGISTER_AGAIN_SECONDS
                state = self._await_registration(known, label, [str(f) for f in files], str(dest),
                                                 seconds=seconds, should_stop=should_stop)
                if state == "registered":
                    _BROKEN_AT = None
                    break
                if state == "stopped":
                    stopped = True
                    break
                _BROKEN_AT = time.monotonic()
                if not (os.path.isdir(self.history_dir) and attempt + 1 < LAUNCH_TRIES):
                    break
                self._log(f"TeraCopy ({label}): launching it again", "warn")
        return {"since": since, "list_file": list_file, "pid": pid, "known": known, "stopped": stopped}

    def _job_state(self, db_file: Path, mine: set[str], dest_norm: str) -> str:
        """What one new history database says about THIS job: "mine" (it lists our files and its
        run targets our destination), "maybe" (our files, no run row yet), "empty" (no files),
        "other" (someone else's job) or "unreadable" (being written)."""
        db = None
        try:
            db = _open_ro(db_file)
            sources = [norm(r[0]) for r in db.execute("select Source from Files limit 500")]
            if not sources:
                return "empty"
            if not any(s in mine or any(s.startswith(m + "\\") or s.startswith(m + "/") for m in mine)
                       for s in sources):
                return "other"
            runs = db.execute("select target from Run").fetchall()
            if not runs:
                return "maybe"
            return "mine" if norm(runs[0][0] or "") == dest_norm else "other"
        except sqlite3.Error:
            return "unreadable"
        finally:
            if db is not None:
                _close(db)

    def _await_registration(self, known: set[str], label: str, files: list[str], dest: str,
                            seconds: float = REGISTER_SECONDS, step: float = 0.25,
                            should_stop: Optional[Callable[[], str]] = None) -> str:
        """Wait (bounded by a count of polls, so a fake clock cannot hang it) for the history
        database of THIS job. -> "registered" | "stopped" | "missing"."""
        mine = {norm(f) for f in files}
        dest_norm = norm(dest)
        maybe_polls = 0
        polls = max(1, int(seconds / step))
        for _ in range(polls):
            if should_stop is not None:
                try:
                    if should_stop():
                        return "stopped"
                except Exception:                                    # noqa: BLE001
                    pass
            try:
                names = [n for n in os.listdir(self.history_dir)
                         if n.endswith(".db") and n != "main.db" and n not in known
                         and os.path.join(self.history_dir, n) not in _CLAIMED]
            except OSError:
                names = []                                           # cold: no History folder yet
            seen_maybe = None
            for n in names:
                got = self._job_state(Path(self.history_dir) / n, mine, dest_norm)
                if got == "mine":
                    _claim(os.path.join(self.history_dir, n))
                    return "registered"
                if got == "maybe":
                    seen_maybe = n
            if seen_maybe is not None:
                maybe_polls += 1
                if maybe_polls >= MAYBE_POLLS:                       # our files, still no run row: it is queued
                    _claim(os.path.join(self.history_dir, seen_maybe))
                    return "registered"
            self._sleep(step)
        self._log(f"TeraCopy ({label}): no history record of this job within {seconds:.0f} s of launch",
                  "warn")
        return "missing"

    def _prune_lists(self, days: int = 14) -> None:
        cutoff = self._now() - days * 86400
        try:
            for name in os.listdir(self.list_dir):
                p = os.path.join(self.list_dir, name)
                if name.endswith(".txt") and os.path.getmtime(p) < cutoff:
                    os.unlink(p)
        except OSError:
            pass

    def wait_for_job(self, dest: str, since: float, *, tag: str = "",
                     on_tick: Optional[Callable[[dict[str, Any], int], None]] = None,
                     sources: Optional[list[str]] = None,
                     expect_verify: bool = True,
                     exclude: Optional[set[str]] = None,
                     should_stop: Optional[Callable[[], str]] = None,
                     max_seconds: Optional[float] = None) -> dict[str, Any]:
        """Block until this job is genuinely finished; -> the final status (which
        may still say 'missing' when the wait fell back to watching the process).

        `should_stop` is asked on every poll; a reason ends the WAIT (not the
        job: TeraCopy is one shared instance that may also be running the
        person's own copies, so it is never killed) and the status comes back
        with `"stopped": <reason>`. `max_seconds` (else `timeout_minutes`, else
        no limit) bounds the whole wait, a verify pass included. The verify
        grace applies only while no verify pass has been SEEN: once TeraCopy is
        verifying, the wait is for it to finish.

        `expect_verify=False` (verify is off and the escape is on) ends the
        wait when the copy phase does, instead of idling out the verify grace.
        """
        t0 = self._now()
        last_report = t0
        seen_job = False
        idle_since: Optional[float] = None
        copied_since: Optional[float] = None
        status: dict[str, Any] = _blank("missing")
        while True:
            status = self._read_status(dest, since, sources, exclude)
            state = status.get("state") if status else "unknown"
            if status and state not in ("missing", "locked"):
                seen_job = True
            if on_tick:
                try:
                    on_tick(status, int(self._now() - t0))
                except Exception:                                # noqa: BLE001
                    pass                    # a UI tick must not break the wait
            if state == "done":
                return status
            if should_stop:
                reason = should_stop()
                if reason:
                    self._log(f"TeraCopy ({tag}): stopped waiting: {reason}", "warn")
                    return {**(status or _blank("missing")), "stopped": str(reason)}
            if state == "copied":
                if not expect_verify:
                    return status
                if status.get("verify_seen"):
                    copied_since = None          # verifying: wait for it, bounded by the limit
                elif copied_since is None:
                    copied_since = self._now()
                elif self._now() - copied_since >= self.verify_grace_seconds:
                    self._log(f"TeraCopy ({tag}): copy finished but no verify pass after "
                              f"{self.verify_grace_seconds:g}s.", "warn")
                    return status
            else:
                copied_since = None
            running = bool(self._is_running())
            # TeraCopy gone: finished and closed (/Close), or cancelled. Require
            # the absence to persist so a gap between queued jobs is not read as
            # the end of the queue.
            if not running:
                if idle_since is None:
                    idle_since = self._now()
                elif self._now() - idle_since >= self.idle_grace_seconds:
                    if not status or state == "missing":
                        self._log(f"TeraCopy ({tag}): process gone; falling back to a "
                                  f"destination check.", "warn")
                    elif not seen_job:
                        self._log(f"TeraCopy ({tag}): process gone and no job record "
                                  f"appeared.", "warn")
                    return status
            else:
                idle_since = None
            if not seen_job and not running and self._now() - t0 >= self.start_grace_seconds:
                self._log(f"TeraCopy ({tag}): no job started within "
                          f"{self.start_grace_seconds:g}s.", "warn")
                return status
            limit = float(max_seconds) if max_seconds else self.timeout_minutes * 60
            if limit > 0 and self._now() - t0 >= limit:
                self._log(f"TeraCopy ({tag}): still unfinished after "
                          f"{limit / 60:g} min; giving up waiting.", "warn")
                return status
            if self._now() - last_report >= 60:
                last_report = self._now()
                mins = int((self._now() - t0) // 60)
                if status and status.get("total"):
                    self._log(f"TeraCopy ({tag}): {state}, {status['ok']}/{status['total']} "
                              f"file(s) verified, {mins} min elapsed.")
                else:
                    self._log(f"TeraCopy ({tag}): waiting ({state}), {mins} min elapsed.")
            self._sleep(self.poll_seconds)

    # -- after ----------------------------------------------------------------
    @staticmethod
    def check_landed(files: list[str], dest: str) -> dict[str, Any]:
        """Independent check that every source file landed at `dest` with the
        same size. Weaker than TeraCopy's hash verify (it cannot see
        corruption) but the only evidence when the job record cannot be read."""
        missing = wrong = checked = 0
        out = []
        for source in files:
            dst = os.path.join(str(dest), os.path.basename(source))
            try:
                src_size = os.stat(source).st_size
            except OSError:
                # source vanished: not counted, but it still gets a receipt
                out.append({"source": source, "dst": dst, "landed": False,
                            "src_size": None, "dst_size": None})
                continue
            checked += 1
            try:
                dst_size: Optional[int] = os.stat(dst).st_size
            except OSError:
                dst_size = None
            if dst_size is None:
                missing += 1
            elif dst_size != src_size:
                wrong += 1
            out.append({"source": source, "dst": dst, "landed": dst_size == src_size,
                        "src_size": src_size, "dst_size": dst_size})
        return {"checked": checked, "missing": missing, "wrong_size": wrong, "files": out}

    def copy_group(self, files: list[str], dest: str, switch: str = DEFAULT_SWITCH,
                   tag: str = "", on_tick: Optional[Callable[..., None]] = None,
                   expect_verify: bool = True,
                   should_stop: Optional[Callable[[], str]] = None,
                   max_seconds: Optional[float] = None) -> dict[str, Any]:
        """Run TeraCopy for `files` into `dest`, wait for it to genuinely
        finish, and return {code, status, receipts, list_file, since}:

            None  nothing to copy
            0     every file copied and hash-verified
            10    job finished but some files were not verified
            11    a file is missing from the destination, or its size differs
            12    completion could not be confirmed
            13    `should_stop` ended the wait; the result also has `stopped`
                  (the reason) and only the files TeraCopy had verified count
                  as landed (the rest say `landed: False`)

        Only TeraCopy's own record earns a 0. When the record cannot be read but
        every file is present at the right size the code is 12 with
        landed=True on each receipt: the files arrived and nothing verified them.
        """
        files = [str(f) for f in files if f]
        if not files:
            return {"code": None, "status": None, "receipts": [], "list_file": None, "since": None}
        launched = self.launch(files, dest, switch, tag, should_stop=should_stop)
        if max_seconds is None:
            total = 0
            for f in files:
                try:
                    total += os.stat(f).st_size
                except OSError:
                    pass
            max_seconds = wait_limit_seconds(total)
        status = self.wait_for_job(dest, launched["since"], tag=tag, on_tick=on_tick,
                                   sources=files, expect_verify=expect_verify,
                                   exclude=launched["known"], should_stop=should_stop,
                                   max_seconds=max_seconds)
        base = {"list_file": launched["list_file"], "since": launched["since"]}
        if status and status.get("stopped"):
            receipts = []
            if status.get("db_path"):
                try:
                    receipts = harvest(status["db_path"])
                except (sqlite3.Error, OSError):
                    pass
            for r in receipts:
                r["landed"] = bool(r["verified"])
            return {"code": CODE_STOPPED, "status": status, "receipts": receipts,
                    "stopped": status["stopped"], **base}
        if status and status.get("state") in ("done", "copied") and status.get("db_path") \
                and (status["state"] == "done" or not expect_verify):
            receipts: list[dict[str, Any]] = []
            try:
                receipts = harvest(status["db_path"])
            except (sqlite3.Error, OSError):
                pass                      # the database went away between read and harvest
            if status["state"] == "done":
                ok, bad, total = status["ok"], status["bad"], status["total"]
                if bad == 0 and ok == total and total > 0:
                    self._log(f"TeraCopy ({tag}): {ok}/{total} file(s) copied and verified.")
                    return {"code": CODE_OK, "status": status, "receipts": receipts, **base}
                self._log(f"TeraCopy ({tag}): finished with {bad} of {total} file(s) "
                          f"not verified.", "error")
                return {"code": CODE_UNVERIFIED, "status": status, "receipts": receipts, **base}
            self._log(f"TeraCopy ({tag}): copied, verify is off: nothing is verified.", "warn")
            return {"code": CODE_UNVERIFIED, "status": status, "receipts": receipts, **base}
        # No trustworthy record: check the destination ourselves.
        landed = self.check_landed(files, dest)
        receipts = [{"source": f["source"], "size": f["src_size"], "is_folder": False,
                     "result": None, "verified": False, "hash": None, "filename": None,
                     "message": None, "landed": f["landed"]} for f in landed["files"]]
        if landed["missing"] or landed["wrong_size"]:
            self._log(f"TeraCopy ({tag}): {landed['missing']} file(s) missing and "
                      f"{landed['wrong_size']} with a different size at the destination.", "error")
            return {"code": CODE_MISSING, "status": status, "receipts": receipts, **base}
        self._log(f"TeraCopy ({tag}): {landed['checked']} file(s) present at the destination "
                  f"with matching sizes, but TeraCopy's own verify result could not be read: "
                  f"treating as UNCONFIRMED.", "warn")
        return {"code": CODE_UNCONFIRMED, "status": status, "receipts": receipts, **base}


def detect_here(cfg: Optional[dict[str, Any]] = None) -> tuple[Optional[TeraCopy], str]:
    """The TeraCopy to copy cards with on THIS machine, or (None, why not).

    Windows only; config `card_copier = "python"` opts out; the exe is
    `teracopy_path` or a standard location; verify must be on (TestAlways=1)
    unless `teracopy_allow_unverified` (the original's `ingest.allowUnverified`
    escape), because a copier that cannot verify must not be the one that
    claims `verified`.
    """
    cfg = cfg or {}
    if os.name != "nt":
        return None, "TeraCopy is Windows-only"
    if str(cfg.get("card_copier") or "auto").strip().lower() == "python":
        return None, "card_copier is set to python"
    exe = find_exe(cfg)
    if not exe:
        return None, "TeraCopy is not installed"
    tc = TeraCopy(exe)
    verify, why = verify_is_on(tc.options_ini)
    if not verify and not _truthy(cfg.get("teracopy_allow_unverified")):
        return None, why or "TeraCopy verify is off"
    return tc, ""


# card_copy calls `teracopy.detect`; the suite replaces THAT name (conftest) so no
# test can launch the real TeraCopy, and tests of the detection use detect_here.
detect = detect_here


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def status_for_capabilities(cfg: Optional[dict[str, Any]] = None) -> tuple[bool, bool]:
    """-> (teracopy usable here, its verify is on)."""
    if os.name != "nt":
        return False, False
    exe = find_exe(cfg)
    if not exe:
        return False, False
    return True, verify_is_on(default_options_ini())[0]
