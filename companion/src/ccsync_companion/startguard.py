"""Start-up bookkeeping that runs BEFORE the app is imported (GL-22, CR-370).

WHY THIS EXISTS. The APP-5 / REL-2 auto-rollback counted a start only once
`CompanionApp.run()` was reached. A build with a missing frozen module, an
import error or an exception in `__init__` died earlier than that, was never
counted, and exited 1 -- which the supervisor reads as deliberate. So a bad
build that a machine took by self-upgrade stayed on disk with its working
predecessor sitting unused as `.old`, and sync and reporting stopped until a
human renamed a file on every machine (PL-RES-03, 2026-10-06 review).

Three small things live here, deliberately light on imports (the launcher
calls `begin()` before `ccsync_companion.app`, and a broken import in the app
must not take this down with it):

  * `begin()` records a start ATTEMPT (`start_attempt.json`). A later launch of
    the same version that finds the previous attempt dead before it reached the
    single-instance lock has found a start failure; two of them on a build we
    still hold the predecessor of restore that predecessor, exactly as the
    three-starts-in-ten-minutes guard does. A second copy of the exe launched
    by hand while the tray is up never reaches the lock either, but its pid is
    ALIVE or it was the loser of the lock (see `reached_lock`), so it is not
    counted.
  * `note_started()` is the "started" marker (`handoff_started.json`): written
    at the very top of the module-level `run()`, i.e. once the build has
    imported everything and is about to wait for the single-instance slot. The
    self-upgrade waits for it (upgrade.wait_for_child_started) instead of the
    old 2 s guess, which was shorter than a onefile extraction.
  * `--self-test`: the frozen exe imports its own package and exits 0, so a
    release step can LAUNCH what it built (no pipeline ever did).

Never raises out of `begin()`/`note_started()`: a failure here must degrade to
"no extra protection", never to "no companion".
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

SELF_TEST_FLAG = "--self-test"
SELF_TEST_OUT_FLAG = "--self-test-out"
ATTEMPT_FILENAME = "start_attempt.json"
HANDOFF_FILENAME = "handoff_started.json"
# Dead-before-the-lock launches of one version that restore its predecessor.
# Two, not one: a single death can be an antivirus holding the extraction.
EARLY_FAILURE_LIMIT = 2
# argv flags of this exe's re-entries that are NOT a companion start (a music
# worker child, the installer's prefs call, the supervisor, the self-test).
# Spelled here because importing music_worker/app would defeat the point.
_NOT_A_START_FLAGS = ("--supervise", "--setup-resolve-prefs", SELF_TEST_FLAG,
                      "--music-resolve-worker")

# What begin() learned, for crash_report's run marker (a supervisor reads it).
_fresh_build = False


def fresh_build() -> bool:
    """True when this process is the first (or a repeat of the first) start of
    a version the machine had not run before."""
    return _fresh_build


def state_dir_for(cfg: Optional[dict] = None) -> Path:
    from . import config as config_mod  # noqa: PLC0415

    cfg = cfg if cfg is not None else config_mod.load_config()
    return config_mod.resolved_log_path(cfg).parent / "state"


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - absent, empty, half-written
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, data: dict) -> bool:
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception:  # noqa: BLE001
        try:
            tmp.unlink()
        except Exception:  # noqa: BLE001
            pass
        return False


def _pid_alive(pid: int) -> bool:
    from . import supervisor  # noqa: PLC0415

    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            return supervisor.pid_is_alive_win32(pid)
        return supervisor.pid_is_alive_posix(pid)
    except Exception:  # noqa: BLE001 - cannot tell: alive (never count a live one)
        return True


def begin(argv: list[str], *, cfg: Optional[dict] = None,
          alive: Optional[Callable[[int], bool]] = None,
          revert: Optional[Callable[..., Any]] = None,
          version: Optional[str] = None) -> str:
    """Record this start attempt and judge the previous one.

    -> "skip" (not a companion start), "ok", or "reverted" (the predecessor
    build was restored and launched: the caller must exit and not start the
    app). Never raises."""
    global _fresh_build
    if any(flag in argv for flag in _NOT_A_START_FLAGS):
        return "skip"
    try:
        from . import config as config_mod  # noqa: PLC0415

        version = version or config_mod.VERSION
        state = state_dir_for(cfg)
        path = state / ATTEMPT_FILENAME
        prev = _read(path)
        is_alive = alive or _pid_alive
        same = str(prev.get("version") or "") == version
        failed = 0
        fresh = False
        # A self-upgrade hand-off child whose predecessor is alive: the
        # predecessor (upgrade.watch_child_takeover / _apply_inner) owns the
        # rollback, so this launch must not count, record a version start or
        # revert (GL-22 round 2, CR-370, 2026-10-07: two rollbacks raced and
        # left no exe at the canonical path).
        handoff_child = False
        spawner = 0
        try:
            spawner = int(os.environ.get("CCSYNC_REPLACES_PID") or 0)
            handoff_child = spawner > 0 and spawner != os.getpid() and is_alive(spawner)
        except Exception:  # noqa: BLE001
            handoff_child = False
        if same:
            failed = int(prev.get("failed_starts") or 0)
            fresh = bool(prev.get("fresh_build"))
            prev_pid = int(prev.get("pid") or 0)
            # Dead before the lock, OR past the lock but never booted (an
            # exception in CompanionApp.__init__ / a startup step: CR-370 /
            # GL-22 overseer defect 2, 2026-10-07). The lock reset used to
            # clear the count, so a build dying after the lock was never
            # counted. A duplicate that lost the lock is neither; an old
            # record without the `booted` key is not judged.
            unfinished = (not prev.get("reached_lock")) or (
                prev.get("booted") is False and not prev.get("duplicate"))
            # A dead previous attempt that was a hand-off child is the
            # spawner's to roll back ONLY while that spawner is still alive.
            # A plain launch of the same version proves the spawner did not
            # restore its build, so the death counts (GL-22 round 2 overseer,
            # CR-370, 2026-10-07: skipping it always made the revert take
            # three launches, past the supervisor's 3-an-hour ceiling).
            prev_spawner = int(prev.get("spawner") or 0)
            spawner_owns = bool(prev.get("handoff_child")) and prev_spawner > 0 \
                and is_alive(prev_spawner)
            if (unfinished and not spawner_owns
                    and prev_pid != os.getpid() and not is_alive(prev_pid)):
                failed += 1
        if not same:
            from . import upgrade as upgrade_mod  # noqa: PLC0415

            before = str(upgrade_mod.read_version_state(state).get("version") or "").strip()
            fresh = bool(before) and before != version
        _fresh_build = fresh
        _write(path, {"version": version, "pid": os.getpid(), "at": time.time(),
                      "reached_lock": False, "booted": False,
                      "handoff_child": handoff_child,
                      "spawner": spawner if handoff_child else 0,
                      "failed_starts": failed, "fresh_build": fresh})
        if handoff_child or failed < 1:
            return "ok"
        from . import upgrade as upgrade_mod  # noqa: PLC0415

        # A start failure is a start: this makes the version record name THIS
        # version with the predecessor in previous_version, which is what the
        # revert reads (the dead attempt never wrote it).
        record = upgrade_mod.note_version_start(state)
        if failed < EARLY_FAILURE_LIMIT:
            return "ok"
        do_revert = revert or upgrade_mod.revert_to_previous_build
        restored, refusal = do_revert(state, cfg if cfg is not None else config_mod.load_config())
        if restored:
            # Do not clobber the restored build's own record (it has usually
            # written one by now); only overwrite while the record is ours.
            if int(_read(path).get("pid") or 0) == os.getpid():
                _write(path, {"version": version, "pid": os.getpid(), "at": time.time(),
                              "reached_lock": True, "booted": True, "failed_starts": 0,
                              "fresh_build": False})
            return "reverted"
        _log_line(state, f"v{version} failed to start {failed} times and was NOT rolled "
                         f"back: {refusal or 'no reason given'} (record {record.get('starts')})")
    except Exception as exc:  # noqa: BLE001
        try:
            _log_line(state_dir_for(cfg), f"begin() failed: {exc!r}")
        except Exception:  # noqa: BLE001
            pass
    return "ok"


def _log_line(state: Path, message: str) -> None:
    """The log is not configured yet; one line beside the record, capped."""
    try:
        path = state / "startguard.log"
        if path.is_file() and path.stat().st_size > 64_000:
            path.unlink()
        with open(path, "a", encoding="utf-8", errors="replace") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")
    except Exception:  # noqa: BLE001
        pass


def reached_lock(cfg: Optional[dict] = None, got_lock: bool = True) -> None:
    """Call right after the single-instance attempt, WHATEVER its outcome. It
    only records that the lock was reached; it does NOT clear the failure
    count (that is `mark_booted`'s job, so a death in __init__ still counts).
    A loser of the lock is a clean duplicate, never a failed start. Never
    raises."""
    try:
        path = state_dir_for(cfg) / ATTEMPT_FILENAME
        data = _read(path)
        if int(data.get("pid") or 0) == os.getpid():
            data["reached_lock"] = True
            if not got_lock:
                data["duplicate"] = True
            _write(path, data)
    except Exception:  # noqa: BLE001
        pass


def mark_booted(cfg: Optional[dict] = None) -> None:
    """This process finished starting: the attempt is a real run, the failure
    count restarts at zero. Never raises."""
    try:
        path = state_dir_for(cfg) / ATTEMPT_FILENAME
        data = _read(path)
        if int(data.get("pid") or 0) == os.getpid():
            data["booted"] = True
            data["failed_starts"] = 0
            _write(path, data)
    except Exception:  # noqa: BLE001
        pass


def note_started(cfg: Optional[dict] = None, version: Optional[str] = None) -> bool:
    """The "started" marker (see the module docstring). Never raises."""
    try:
        from . import config as config_mod  # noqa: PLC0415

        return _write(state_dir_for(cfg) / HANDOFF_FILENAME,
                      {"pid": os.getpid(), "ppid": os.getppid(),
                       "version": version or config_mod.VERSION, "at": time.time()})
    except Exception:  # noqa: BLE001
        return False


def read_started(state_dir: Path) -> dict:
    return _read(Path(state_dir) / HANDOFF_FILENAME)


# -- --self-test ---------------------------------------------------------------

# Modules whose import is allowed to fail on a platform that does not have
# their OS (the PyObjC tray on Windows, the ctypes tray on macOS).
_PLATFORM_ONLY = {"win32": ("mac", "darwin", "objc", "appkit"),
                  "darwin": ("win32", "windows", "tray_native_win")}


def self_test(argv: list[str], *, package: str = "ccsync_companion") -> int:
    """Import the app and every module of the package, load the config
    (read-only) and answer 0, or 2 with the failures. Takes no single-instance
    lock, writes no marker, starts no thread: a release step may run it beside
    a live companion."""
    import importlib  # noqa: PLC0415
    import pkgutil  # noqa: PLC0415

    failures: list[str] = []
    imported = 0
    try:
        importlib.import_module(f"{package}.app")
        imported += 1
    except BaseException as exc:  # noqa: BLE001 - SystemExit from a module too
        failures.append(f"{package}.app: {exc!r}")
    names: list[str] = []
    try:
        pkg = importlib.import_module(package)
        names = [m.name for m in pkgutil.iter_modules(pkg.__path__)]
    except Exception as exc:  # noqa: BLE001
        failures.append(f"{package}: cannot list modules: {exc!r}")
    skip_words = _PLATFORM_ONLY.get(sys.platform, ())
    for name in sorted(names):
        if name in ("__main__", "app", "launcher"):
            continue
        try:
            importlib.import_module(f"{package}.{name}")
            imported += 1
        except BaseException as exc:  # noqa: BLE001
            if any(w in name.lower() for w in skip_words):
                continue
            failures.append(f"{package}.{name}: {exc!r}")
    try:
        from . import config as config_mod  # noqa: PLC0415

        version = config_mod.VERSION
    except Exception as exc:  # noqa: BLE001
        version = "?"
        failures.append(f"config: {exc!r}")
    ok = not failures
    line = (f"SELF-TEST OK v{version} ({imported} modules)" if ok
            else f"SELF-TEST FAILED v{version}: " + "; ".join(failures))
    out: Optional[str] = None
    for i, item in enumerate(argv):
        if item == SELF_TEST_OUT_FLAG and i + 1 < len(argv):
            out = argv[i + 1]
    if out:
        try:
            Path(out).write_text(line + "\n", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    try:
        if sys.stdout is not None:
            print(line, flush=True)
    except Exception:  # noqa: BLE001
        pass
    return 0 if ok else 2
