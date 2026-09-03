"""Crash reports: a local JSON file ALWAYS, a network sender only if asked.

COMMERCIAL_READINESS.md item 13, 2026-08-17. Until now an unhandled exception
in a background thread wrote a traceback into companion.log and nothing else
happened -- and companion.log rotates at 5 MB, lives on the editor's machine,
and is only ever read after someone thinks to ask for it. Meanwhile the tray
stayed up with a dead lane, which is the failure mode this fleet keeps hitting.

TWO HALVES, AND THE SPLIT IS THE WHOLE DESIGN

  LOCAL, always on, no configuration, never leaves the machine:
      ~/.ccsync/crashes/<utc-timestamp>-<thread>.json
  Traceback, version, platform, the failing thread, and the last
  BREADCRUMB_LINES lines of companion.log at the moment it happened. That last
  part is the point: by the time an editor reports "it stopped syncing", the
  lines that explain why have usually rotated away. Costs nothing, tells
  nobody, and turns "send me your log" into "send me one small file".

  NETWORK, off unless BOTH `crash_reporting = true` AND a `crash_dsn` are set
  in ~/.ccsync/config.toml, and only if `sentry_sdk` is importable at all
  (it is not in the frozen build's dependency list). Opt-in twice, in other
  words. A customer who wants vendor-side crash visibility turns it on; the
  default product phones nobody. docs/legal/TELEMETRY.md is the disclosure.

WHAT IT NEVER DOES

  - Raise. Every public function swallows everything: a crash handler that
    crashes replaces a diagnosable failure with an undiagnosable one, and this
    code runs at the exact moment the process is least healthy.
  - Exit, log at ERROR twice, or otherwise change control flow. The existing
    handlers (`log.exception` in app.run, the lane supervisors) still do their
    job; this is strictly additional.
  - Send anything by default. Not a counter, not a ping, not a version check.
  - Write an unbounded number of files. A crash loop is exactly when this would
    otherwise fill ~/.ccsync -- MAX_CRASH_FILES are kept, oldest pruned.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import config as config_mod
from . import supervisor

log = logging.getLogger("ccsync.crash")

# How much of the tail of companion.log rides along. 200 lines is ~20-40 KB and
# has covered the run-up to every lane failure looked at so far; the whole point
# is to catch what rotation would have eaten.
BREADCRUMB_LINES = 200
# Read at most this much from the end of the log. The log rotates at 5 MB, and
# seeking rather than readlines() is the same trick app.py's log tail uses
# (R15 fix 4) -- a crash handler must not pull 5 MB into memory.
BREADCRUMB_MAX_BYTES = 256_000
# A crash LOOP is when this directory would otherwise grow without bound, and a
# crash loop is also when it is least likely anyone is watching.
MAX_CRASH_FILES = 20
# APP-6 (resilience sweep 2026-08-28): the module docstring above names "the
# tray stayed up with a dead lane" as the failure this file exists to fix, and
# until the sweep NOTHING surfaced a crash file -- not the tray, not
# build_diagnostics(), not the report. A crash was written and the machine went
# on looking green. The summary below is read by app.sync_guard() on every
# report tick, so the scan is bounded (MAX_CRASH_FILES names) and cached for
# this long between rescans; a write invalidates it immediately.
SUMMARY_TTL_SECONDS = 60.0
# How many of the newest reports build_diagnostics() names, with their
# exception types. Three is what fits in a section an admin reads at a glance.
DIAGNOSTIC_CRASH_COUNT = 3

# Redaction, applied to every breadcrumb line and to the exception text.
#
# The log is not supposed to contain secrets and mostly does not -- secrets are
# never on argv and the reporter posts them in headers. "Mostly" is not a
# property to bet a customer's fleet token on, and this file is meant to be
# EMAILED, which the log never was. Cheap insurance, applied to the copy only.
_REDACTIONS = (
    (re.compile(r"(?i)\b(token|password|passwd|secret|api[_-]?key|dsn)\b\s*[:=]\s*\S+"),
     r"\1=<redacted>"),
    # Basic-auth and token-bearing URLs: scheme://user:pw@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@"), r"\1<redacted>@"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+"), "Bearer <redacted>"),
)


def redact(text: str) -> str:
    """Best-effort. Not a security boundary -- a reduction in blast radius."""
    try:
        for pattern, replacement in _REDACTIONS:
            text = pattern.sub(replacement, text)
    except Exception:  # noqa: BLE001 - see the module docstring: never raise
        return "<redaction failed>"
    return text


def crash_dir(cfg: Optional[dict[str, Any]] = None) -> Path:
    """~/.ccsync/crashes, or beside whatever log_path says.

    Derived from the log path rather than from CONFIG_DIR so a config that
    redirects the log (the tests do, via a patched DEFAULTS) redirects the
    crash files with it -- a suite that writes crash JSON into the developer's
    real ~/.ccsync would be a bug of exactly the kind conftest.py exists to
    prevent.
    """
    cfg = cfg or {}
    try:
        return config_mod.resolved_log_path(cfg).parent / "crashes"
    except Exception:  # noqa: BLE001
        return Path.home() / ".ccsync" / "crashes"


def _tail(path: Path, lines: int = BREADCRUMB_LINES) -> list[str]:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > BREADCRUMB_MAX_BYTES:
                handle.seek(size - BREADCRUMB_MAX_BYTES)
                handle.readline()  # discard the partial line the seek landed in
            text = handle.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - no log, an unreadable log: both are "no breadcrumb"
        return []
    return [redact(line) for line in text.splitlines()[-lines:]]


def _prune(directory: Path, keep: Optional[int] = None) -> None:
    # Read at call time, not bound as a default: a default argument freezes the
    # constant at import and the limit then cannot be lowered by anything --
    # tests included.
    keep = MAX_CRASH_FILES if keep is None else keep
    try:
        files = sorted(directory.glob("*.json"), key=lambda p: p.name)
        for stale in files[:-keep] if len(files) > keep else []:
            stale.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


# -- what an admin can actually see (APP-6) ---------------------------------
_summary_lock = threading.Lock()
# (taken_at_monotonic, directory, summary). One slot: there is one crash
# directory per process, and the key is carried so a test (or a config that
# redirects the log path) can never be served another directory's answer.
_summary_cache: Optional[tuple[float, str, dict[str, Any]]] = None


def invalidate_summary() -> None:
    """Drop the cached count. Called by write_report, so the report that goes
    out after a crash carries it rather than one written up to a minute
    later."""
    global _summary_cache
    with _summary_lock:
        _summary_cache = None


def _crash_files(cfg: Optional[dict[str, Any]] = None) -> list[Path]:
    """Newest LAST. Bounded by MAX_CRASH_FILES in practice (_prune), and the
    sort is by NAME because the name starts with the UTC stamp -- mtime would
    reorder a directory that was copied off the machine and back."""
    try:
        return sorted(crash_dir(cfg).glob("*.json"), key=lambda p: p.name)
    except Exception:  # noqa: BLE001 - a missing/unreadable dir is "none"
        return []


def crash_summary(cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """`{"count": n, "newest": "<filename>"}` -- the `crashes` block of the
    `sync_guard` report section. Never raises.

    A handful of bytes on every tick, and the only channel that tells an
    admin a background thread died on a machine whose lanes still look
    green."""
    global _summary_cache
    directory = ""
    try:
        directory = str(crash_dir(cfg))
    except Exception:  # noqa: BLE001
        pass
    now = time.monotonic()
    with _summary_lock:
        cached = _summary_cache
        if (cached is not None and cached[1] == directory
                and (now - cached[0]) < SUMMARY_TTL_SECONDS):
            return dict(cached[2])
    files = _crash_files(cfg)
    summary: dict[str, Any] = {
        "count": len(files),
        "newest": files[-1].name if files else None,
    }
    with _summary_lock:
        _summary_cache = (now, directory, dict(summary))
    return summary


def recent_reports(cfg: Optional[dict[str, Any]] = None,
                   limit: int = DIAGNOSTIC_CRASH_COUNT) -> list[dict[str, Any]]:
    """The newest `limit` crash files as `{name, when, thread, type}`, newest
    first, for build_diagnostics(). Never raises: an unreadable or half-written
    file is reported as such rather than dropped, because "there is a crash
    file here I cannot read" is itself the answer."""
    out: list[dict[str, Any]] = []
    for path in reversed(_crash_files(cfg)[-max(1, int(limit or 1)):]):
        entry: dict[str, Any] = {"name": path.name, "when": None,
                                 "thread": None, "type": "<unreadable>"}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                entry["when"] = data.get("when")
                entry["thread"] = data.get("thread")
                exception = data.get("exception")
                if isinstance(exception, dict):
                    entry["type"] = exception.get("type") or "<unknown>"
        except Exception:  # noqa: BLE001
            pass
        out.append(entry)
    return out


def build_report(exc_type, exc_value, exc_tb, *, thread: str = "MainThread",
                 cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    cfg = cfg or {}
    try:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    except Exception:  # noqa: BLE001
        text = f"<traceback unavailable> {exc_type!r}"
    log_path = None
    try:
        log_path = config_mod.resolved_log_path(cfg)
    except Exception:  # noqa: BLE001
        pass
    return {
        "schema": 1,
        "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": getattr(config_mod, "VERSION", "?"),
        "thread": thread,
        # `frozen` distinguishes a PyInstaller build from a source run, which is
        # the first thing anyone asks about a companion report (CLAUDE.md: verify
        # against the DEPLOYED build, not the repo).
        "frozen": bool(getattr(sys, "frozen", False)),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "exception": {
            "type": getattr(exc_type, "__name__", str(exc_type)),
            "message": redact(str(exc_value)),
            "traceback": redact(text),
        },
        "log_tail": _tail(log_path) if log_path else [],
    }


def write_report(report: dict[str, Any],
                 cfg: Optional[dict[str, Any]] = None) -> Optional[Path]:
    """-> the file written, or None. Never raises."""
    try:
        directory = crash_dir(cfg)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = str(report.get("when", "")).replace(":", "").replace("-", "")
        thread = re.sub(r"[^A-Za-z0-9_.-]", "_", str(report.get("thread", "?")))[:40]
        path = directory / f"{stamp or 'unknown'}-{thread}.json"
        # Owner-only: this file carries a redacted log tail and absolute paths,
        # and on Windows a default umask would hand it to every local account.
        # 0o600 via os.open rather than chmod-after-write, which leaves a window.
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        handle = os.open(path, flags, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        _prune(directory)
        # APP-6: before the return, so the next report tick and the next tray
        # render both carry this crash rather than a count taken before it.
        invalidate_summary()
        return path
    except Exception:  # noqa: BLE001
        return None


# -- the opt-in network half ------------------------------------------------

_sentry: Any = None


def sentry_enabled(cfg: dict[str, Any]) -> bool:
    """Both switches, in the right order. `crash_reporting = true` with no DSN
    is NOT "send to some default endpoint" -- there is no default endpoint."""
    try:
        return bool(cfg.get("crash_reporting")) and bool(str(cfg.get("crash_dsn", "")).strip())
    except Exception:  # noqa: BLE001
        return False


def init_sender(cfg: dict[str, Any]) -> bool:
    """-> True if a sender is live. Never raises, never installs anything.

    `sentry_sdk` is an OPTIONAL import and is deliberately not in
    pyproject.toml's dependency list: it is not in the frozen build, so a
    customer who wants this compiles their own or installs the companion from
    source. Shipping the SDK in every editor's exe to serve a default-off
    feature is how "opt-in telemetry" quietly stops being opt-in.
    """
    global _sentry
    if not sentry_enabled(cfg):
        return False
    try:
        import sentry_sdk  # noqa: PLC0415 - optional by design
    except ImportError:
        log.info("crash_reporting is on but sentry_sdk is not installed "
                 "(the frozen build does not ship it) -- crash files only")
        return False
    try:
        sentry_sdk.init(
            dsn=str(cfg["crash_dsn"]).strip(),
            release=f"ccsync-companion@{getattr(config_mod, 'VERSION', '0')}",
            # No breadcrumbs of their own and no PII: everything we want is
            # already in the local report, and `send_default_pii` would attach
            # usernames and IPs to it. traces_sample_rate 0 -- this is crash
            # reporting, not performance monitoring.
            send_default_pii=False,
            traces_sample_rate=0.0,
            environment="frozen" if getattr(sys, "frozen", False) else "source",
        )
        _sentry = sentry_sdk
        log.info("crash reporting: sending to the configured DSN (opt-in)")
        return True
    except Exception:  # noqa: BLE001
        log.warning("crash reporting: sentry_sdk.init failed -- crash files only",
                    exc_info=True)
        return False


def _send(exc_value: BaseException) -> None:
    if _sentry is None:
        return
    try:
        _sentry.capture_exception(exc_value)
    except Exception:  # noqa: BLE001
        pass


# -- the hooks --------------------------------------------------------------

_installed = False


def handle(exc_type, exc_value, exc_tb, thread: str = "MainThread",
           cfg: Optional[dict[str, Any]] = None) -> Optional[Path]:
    """One exception -> one crash file (+ a send, if enabled). Never raises."""
    try:
        report = build_report(exc_type, exc_value, exc_tb, thread=thread, cfg=cfg)
        path = write_report(report, cfg)
        if path is not None:
            log.error("unhandled exception in %s -- crash report written to %s",
                      thread, path)
        if isinstance(exc_value, BaseException):
            _send(exc_value)
        return path
    except Exception:  # noqa: BLE001
        return None


def install(cfg: Optional[dict[str, Any]] = None) -> None:
    """Chain onto sys.excepthook and threading.excepthook. Idempotent.

    CHAINED, not replaced: the previous hook still runs afterwards, so Python's
    own "Exception in thread X" on stderr and anything a future hook adds keep
    working. A crash reporter that swallows the interpreter's own report makes
    the machine harder to debug, not easier -- which is the opposite of the job.

    KeyboardInterrupt and SystemExit are passed straight through: Ctrl-C during
    a source run and the tray's own `sys.exit` are not crashes, and writing a
    file for every quit would bury the real ones.
    """
    global _installed
    if _installed:
        return
    _installed = True
    cfg = cfg or {}

    previous_hook = sys.excepthook
    previous_thread_hook = getattr(threading, "excepthook", None)

    def _hook(exc_type, exc_value, exc_tb):
        if not issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            handle(exc_type, exc_value, exc_tb, "MainThread", cfg)
        previous_hook(exc_type, exc_value, exc_tb)

    def _thread_hook(args):
        if args.exc_type is not None and not issubclass(
                args.exc_type, (KeyboardInterrupt, SystemExit)):
            name = getattr(args.thread, "name", None) or "unknown-thread"
            handle(args.exc_type, args.exc_value, args.exc_traceback, name, cfg)
        if previous_thread_hook is not None:
            previous_thread_hook(args)

    sys.excepthook = _hook
    if previous_thread_hook is not None:
        threading.excepthook = _thread_hook

    # APP-6: count what an EARLIER run left behind. A machine that starts with
    # crash files already in the directory is a machine that has been failing
    # and restarting, and until the sweep the only trace of that was files
    # nobody looked at.
    try:
        existing = crash_summary(cfg)
        if existing.get("count"):
            log.warning("%s crash report(s) from an earlier run are in %s "
                        "(newest: %s)", existing["count"], crash_dir(cfg),
                        existing.get("newest"))
    except Exception:  # noqa: BLE001 - see the module docstring: never raise
        pass

    init_sender(cfg)


# -- the half a Python hook can never see: native aborts (CR-93) ------------
#
# Everything above starts from an exception object. A Tcl_Panic does not have
# one: it calls abort(), the process is gone mid-instruction, and no hook,
# `finally` or atexit runs. That is exactly how CR-93 hid for eleven days --
# the tray vanished, companion.log's last line was whatever it had been
# doing, and only the Windows Event Log knew there had been a crash at all.
#
# Two cheap things close that gap, and neither can fail loudly:
#
#   faulthandler writes the C-level and Python stack of every thread into
#   <crashes>/native.log when the process dies on a fatal signal (SIGABRT
#   among them, which is what abort() raises). It costs nothing while
#   nothing is wrong.
#
#   A RUN MARKER says "a companion with this pid was alive and had not
#   decided to exit". Deleted the moment shutdown() starts, so it survives
#   only a death nobody asked for. The NEXT start finds it and writes a
#   normal crash report -- which means an unclean exit reaches the tray, the
#   diagnostics bundle and the dashboard through the machinery APP-6 already
#   built, instead of nowhere.
#
# A pulled power cord and a `taskkill /f` land here too, and that is correct:
# the report says the companion did not shut down tidily, which is true, and
# names the native.log that distinguishes the cases.
NATIVE_LOG_FILENAME = "native.log"
NATIVE_LOG_MAX_BYTES = 512_000
# Deliberately NOT a .json name: this directory's *.json files ARE the
# crash reports -- _crash_files() counts them and _prune() deletes the
# oldest, so a marker with that suffix would report itself as a crash on
# every start and then be pruned away by a busy one.
RUN_MARKER_FILENAME = "running.marker"
# How much of native.log rides along in the report for an unclean exit. A
# faulthandler dump of 50 threads is long; the top of it is the answer.
NATIVE_TAIL_LINES = 120

_native_handle: Any = None


def native_log_path(cfg: Optional[dict[str, Any]] = None) -> Path:
    return crash_dir(cfg) / NATIVE_LOG_FILENAME


def run_marker_path(cfg: Optional[dict[str, Any]] = None) -> Path:
    return crash_dir(cfg) / RUN_MARKER_FILENAME


def _read_run_marker(cfg: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    try:
        data = json.loads(run_marker_path(cfg).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - absent, empty or half-written: no marker
        return None
    return data if isinstance(data, dict) else None


def write_run_marker(cfg: Optional[dict[str, Any]] = None) -> Optional[Path]:
    """Claim "a companion is running" for this pid. Never raises."""
    try:
        directory = crash_dir(cfg)
        directory.mkdir(parents=True, exist_ok=True)
        path = run_marker_path(cfg)
        payload = {
            "pid": os.getpid(),
            "version": getattr(config_mod, "VERSION", "?"),
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "frozen": bool(getattr(sys, "frozen", False)),
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path
    except Exception:  # noqa: BLE001
        return None


def mark_clean_exit(cfg: Optional[dict[str, Any]] = None) -> None:
    """"This process MEANT to stop." Called at the top of shutdown(), not at
    the bottom: everything after that decision -- including app.py's hard-exit
    backstop for a wedged thread -- is a deliberate exit, and reporting it as
    a crash on the next start would bury the ones that are. Never raises.

    Only OUR marker: a self-upgrade starts the new build before the old one
    has finished shutting down, and the newcomer's marker (its own pid) is by
    then the one on disk. Deleting it here would leave the newcomer's death
    unreported and, since 2026-08-30, tell its supervisor it had quit on
    purpose."""
    try:
        marker = _read_run_marker(cfg)
        if marker is not None and int(marker.get("pid", -1)) not in (-1, os.getpid()):
            log.debug("run marker belongs to pid %s, not us -- leaving it", marker.get("pid"))
            return
    except Exception:  # noqa: BLE001 - unreadable: ours to remove
        pass
    try:
        run_marker_path(cfg).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def _pid_is_alive(pid: int) -> bool:
    """Liveness of another process, fail-safe: "cannot tell" is alive."""
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            return supervisor.pid_is_alive_win32(pid)
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:  # noqa: BLE001
        return True


def _native_tail(cfg: Optional[dict[str, Any]] = None) -> list[str]:
    path = native_log_path(cfg)
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return []
    except Exception:  # noqa: BLE001
        return []
    return _tail(path, NATIVE_TAIL_LINES)


def _log_tail(cfg: Optional[dict[str, Any]] = None) -> list[str]:
    """The end of companion.log, or nothing. Never raises -- this runs during
    startup, where a bad log_path is already handled elsewhere."""
    try:
        return _tail(config_mod.resolved_log_path(cfg or {}))
    except Exception:  # noqa: BLE001
        return []


def _report_unclean_exit(marker: dict[str, Any],
                         cfg: Optional[dict[str, Any]] = None,
                         relaunch: Optional[dict[str, Any]] = None) -> Optional[Path]:
    """One crash file for a previous run that never reached shutdown()."""
    native = _native_tail(cfg)
    detail = (
        f"a companion (pid {marker.get('pid', '?')}, version "
        f"{marker.get('version', '?')}, started {marker.get('started', '?')}) "
        "stopped without ever starting a shutdown"
    )
    if relaunch:
        detail += (
            f" -- the supervisor relaunched it at {relaunch.get('when', '?')} "
            f"(exit code {relaunch.get('exit_code', '?')}, relaunch "
            f"{relaunch.get('attempt', '?')} of {supervisor.MAX_RELAUNCHES} this hour)"
        )
    report = {
        "schema": 1,
        "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": getattr(config_mod, "VERSION", "?"),
        "thread": "process",
        "frozen": bool(getattr(sys, "frozen", False)),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "exception": {
            # A TYPE, so recent_reports() and the diagnostics section that
            # reads it show something an admin can act on rather than
            # "<unknown>". It is not a Python exception and does not pretend
            # to be one.
            "type": "UncleanExit",
            "message": redact(detail),
            "traceback": redact("\n".join(native)) if native else
                         "no native.log entry -- the process was killed, lost "
                         "power, or died somewhere faulthandler could not "
                         "report (a Tcl_Panic on Windows reaches WER, not us: "
                         "check the Event Log for exception 0x80000003 in "
                         "tcl86t.dll, which is CR-93)",
        },
        "previous_run": {k: marker.get(k) for k in ("pid", "version", "started", "frozen")},
        "log_tail": _log_tail(cfg),
    }
    if relaunch:
        report["relaunch"] = relaunch
    path = write_report(report, cfg)
    log.error("the previous companion did not shut down cleanly: %s%s", detail,
              f" -- report written to {path}" if path else "")
    return path


def install_native(cfg: Optional[dict[str, Any]] = None) -> None:
    """faulthandler + the run marker. Call ONCE, after the single-instance
    lock is held: the marker is one file for the machine, and a second
    instance that is about to exit must not touch the live one's. Never
    raises -- a companion that cannot write a marker still syncs.
    """
    global _native_handle
    cfg = cfg or {}
    try:
        marker = _read_run_marker(cfg)
        relaunch = supervisor.read_relaunch_note(crash_dir(cfg))
        previous_pid = int(marker.get("pid", -1)) if marker is not None else -1
        if marker is not None and previous_pid != os.getpid() and _pid_is_alive(previous_pid):
            # A self-upgrade's predecessor, still tearing its lanes down while
            # we start (upgrade._default_spawn's hand-off). Not a death.
            log.debug("run marker names pid %s, which is still running -- a "
                      "hand-off, not a crash", marker.get("pid"))
            marker = None
        if marker is not None:
            _report_unclean_exit(marker, cfg, relaunch)
        if relaunch:
            log.warning(
                "this companion was RELAUNCHED by its supervisor: pid %s died with "
                "exit code %s at %s and never started a shutdown (%s). It was down "
                "for about %.0f s. Relaunch %s of %s this hour; the crash report "
                "above carries the native dump if faulthandler caught it.",
                relaunch.get("previous_pid"), relaunch.get("exit_code"),
                relaunch.get("when"), relaunch.get("reason"),
                supervisor.RELAUNCH_DELAY_SECONDS, relaunch.get("attempt"),
                supervisor.MAX_RELAUNCHES,
            )
    except Exception:  # noqa: BLE001
        log.debug("could not check the previous run's marker", exc_info=True)
    try:
        directory = crash_dir(cfg)
        directory.mkdir(parents=True, exist_ok=True)
        path = native_log_path(cfg)
        # Truncate rather than rotate: this file is only ever read right after
        # a native death, one dump is what matters, and a rotation scheme is
        # more code than the thing it protects.
        try:
            if path.is_file() and path.stat().st_size > NATIVE_LOG_MAX_BYTES:
                path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        import faulthandler  # noqa: PLC0415 - stdlib, but only needed here

        # Held in a module global for the life of the process ON PURPOSE:
        # faulthandler keeps the fd, and a closed file would make the dump
        # land nowhere at the one moment it is wanted.
        _native_handle = open(path, "a", encoding="utf-8", errors="replace")
        faulthandler.enable(file=_native_handle, all_threads=True)
    except Exception:  # noqa: BLE001
        log.debug("faulthandler could not be enabled", exc_info=True)
    write_run_marker(cfg)


def start_supervisor(cfg: Optional[dict[str, Any]] = None,
                     spawn: Optional[Any] = None) -> bool:
    """Spawn the relaunch-on-abort supervisor for THIS process (CR-93's
    safety net, supervisor.py). Call right after install_native(): the run
    marker it reads must exist and name us. Never raises; returns whether
    one was started -- False on a source run, off-Windows, `supervise =
    false`, or CCSYNC_NO_SUPERVISOR in the environment."""
    cfg = cfg or {}
    if not cfg.get("supervise", True):
        log.info("supervisor: disabled by config (supervise = false) -- a crash "
                 "leaves this machine without a companion until the next logon")
        return False
    try:
        state_dir = config_mod.resolved_log_path(cfg).parent / "state"
        child = supervisor.spawn_for(
            os.getpid(), Path(sys.executable), crash_dir(cfg), state_dir, spawn=spawn)
    except Exception:  # noqa: BLE001
        log.warning("supervisor: could not start one -- a crash leaves this "
                    "machine without a companion until the next logon", exc_info=True)
        return False
    if child is None:
        # bug-hunt-2026-09-03 comp-core-2: this used to be a DEBUG line, on the
        # strength of supervisor.spawn_for's claim that launchd covers macOS.
        # It does not -- the companion LaunchAgent has no KeepAlive by design
        # -- so a Mac has no relaunch-after-abort net at all and its log said
        # nothing about it. WARNING there, INFO everywhere else (a source run
        # is a developer's own choice).
        line = ("supervisor: not started (source run, not Windows, or %s set) -- "
                "if this companion dies without shutting down, nothing relaunches "
                "it and this machine syncs nothing until the next logon")
        if sys.platform == "darwin":
            log.warning(line, supervisor.DISABLE_ENV)
        else:
            log.info(line, supervisor.DISABLE_ENV)
        return False
    log.info("supervisor: pid %s is watching this companion and will relaunch it "
             "after a crash (never after a Quit or an upgrade)", getattr(child, "pid", "?"))
    return True


def _reset_for_tests() -> None:
    """The module-level `_installed`/`_sentry` latches are process-global; the
    suite installs hooks many times over. Not part of the public surface."""
    global _installed, _sentry, _native_handle
    _installed = False
    _sentry = None
    handle, _native_handle = _native_handle, None
    if handle is not None:
        try:
            import faulthandler

            faulthandler.disable()
            handle.close()
            # Back to the default sink rather than off: pytest's own
            # faulthandler runs for the whole session, and a suite that
            # silently took it away would hide the next hang in some other
            # test. Raises under a windowed build (no stderr) -- test-only
            # code, so that is the caller's problem and not ours.
            faulthandler.enable()
        except Exception:  # noqa: BLE001
            pass
    invalidate_summary()
