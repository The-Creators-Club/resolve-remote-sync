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
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import config as config_mod

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

    init_sender(cfg)


def _reset_for_tests() -> None:
    """The module-level `_installed`/`_sentry` latches are process-global; the
    suite installs hooks many times over. Not part of the public surface."""
    global _installed, _sentry
    _installed = False
    _sentry = None
