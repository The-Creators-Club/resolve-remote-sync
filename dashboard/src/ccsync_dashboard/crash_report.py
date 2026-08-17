"""Crash reports and optional log rotation for the container.

COMMERCIAL_READINESS.md item 13, 2026-08-17. The companion half is
`ccsync_companion.crash_report`; this is the same design on the server side,
and the same rule holds: LOCAL ALWAYS, NETWORK ONLY IF ASKED.

WHY THE CONTAINER NEEDS IT AT ALL

The dashboard logs to stdout, docker keeps some of that, and `docker logs` is
the whole story. Two things fall through that:

  1. The collector runs in a BACKGROUND THREAD. If it dies before entering its
     guarded loop, the container keeps answering 200 and the healthcheck's `ok`
     flag is the only symptom (DASH-2). A thread excepthook that writes the
     traceback somewhere persistent is how you find out WHY, days later.
  2. Container logs do not survive a `docker compose down` on either NAS, and
     nothing rotates them by default -- json-file driver limits are host
     configuration this deploy does not own.

WHAT IS OPT-IN AND WHAT IS NOT

  ALWAYS   ${DASH_CRASH_DIR:-<DASH_DB_PATH's dir>/crashes}/<ts>-<thread>.json,
           owner-only, at most MAX_CRASH_FILES kept, sent nowhere.
  OPT-IN   DASH_SENTRY_DSN -- unset means no sender is constructed at all, and
           `sentry_sdk` is not in deploy/requirements.txt, so a site that wants
           this adds the package as well as the DSN. Two deliberate acts.
  OPT-IN   DASH_LOG_DIR -- unset means stdout only, exactly as today. Set, the
           `ccsync` logger also writes JSON lines to a 5 MB x 3 rotating file
           there (the companion's numbers, for the same reasons).

Nothing here may raise: it runs at the moment the process is least healthy, and
"the dashboard is what tells everyone whether their footage is syncing"
outranks knowing why it fell over.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import platform
import re
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import VERSION

log = logging.getLogger("ccsync.crash")

MAX_CRASH_FILES = 20
# Mirrors the companion's 5 MB x 3. Small enough that /data cannot be filled by
# a log loop, large enough to hold a full collector cycle's chatter.
LOG_MAX_BYTES = 5_000_000
LOG_BACKUPS = 3

# The container's environment holds TRUENAS_PW, DASH_SESSION_SECRET,
# BROLL_INGEST_TOKEN and SYNCTHING_API_KEY. A traceback with locals is not
# written here, but exception MESSAGES routinely quote a URL or a header, and a
# crash file is a thing an operator emails.
_REDACTIONS = (
    (re.compile(r"(?i)\b(token|password|passwd|secret|api[_-]?key|dsn|pw)\b\s*[:=]\s*\S+"),
     r"\1=<redacted>"),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@"), r"\1<redacted>@"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+"), "Bearer <redacted>"),
)


def redact(text: str) -> str:
    try:
        for pattern, replacement in _REDACTIONS:
            text = pattern.sub(replacement, text)
    except Exception:  # noqa: BLE001
        return "<redaction failed>"
    return text


def crash_dir(settings: Any = None) -> Path:
    """DASH_CRASH_DIR, else `crashes/` beside the database.

    Beside the database rather than beside the code: /app is mounted read-only
    (and is an image layer in image mode), /data is the one persistent writable
    volume every deployment has.
    """
    explicit = os.environ.get("DASH_CRASH_DIR", "").strip()
    if explicit:
        return Path(explicit)
    db_path = getattr(settings, "db_path", None) or os.environ.get(
        "DASH_DB_PATH", "/data/dashboard.db")
    return Path(db_path).parent / "crashes"


def build_report(exc_type, exc_value, exc_tb, *, thread: str = "MainThread",
                 settings: Any = None) -> dict[str, Any]:
    try:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    except Exception:  # noqa: BLE001
        text = f"<traceback unavailable> {exc_type!r}"
    return {
        "schema": 1,
        "component": "ccsync-dashboard",
        "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": VERSION,
        "thread": thread,
        "platform": {"system": platform.system(), "python": platform.python_version()},
        "exception": {
            "type": getattr(exc_type, "__name__", str(exc_type)),
            "message": redact(str(exc_value)),
            "traceback": redact(text),
        },
    }


def write_report(report: dict[str, Any], settings: Any = None) -> Optional[Path]:
    try:
        directory = crash_dir(settings)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = str(report.get("when", "")).replace(":", "").replace("-", "")
        thread = re.sub(r"[^A-Za-z0-9_.-]", "_", str(report.get("thread", "?")))[:40]
        path = directory / f"{stamp or 'unknown'}-{thread}.json"
        # run.sh sets umask 077 already; this states it rather than inheriting
        # it, because a crash file is written by whatever thread crashes and
        # umask is process state anyone can change.
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        _prune(directory)
        return path
    except Exception:  # noqa: BLE001
        return None


def _prune(directory: Path, keep: Optional[int] = None) -> None:
    keep = MAX_CRASH_FILES if keep is None else keep
    try:
        files = sorted(directory.glob("*.json"), key=lambda p: p.name)
        for stale in files[:-keep] if len(files) > keep else []:
            stale.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


# -- the opt-in network half ------------------------------------------------

_sentry: Any = None


def sentry_dsn() -> str:
    return os.environ.get("DASH_SENTRY_DSN", "").strip()


def init_sender() -> bool:
    """-> True if a sender is live. Never raises.

    `sentry_sdk` is deliberately absent from dashboard/deploy/requirements.txt:
    a package installed in every container to serve a default-off feature is
    how opt-in telemetry stops being opt-in, and this container's dependency
    list is one of the things a customer's review reads.
    """
    global _sentry
    dsn = sentry_dsn()
    if not dsn:
        return False
    try:
        import sentry_sdk  # noqa: PLC0415 - optional by design
    except ImportError:
        log.info("DASH_SENTRY_DSN is set but sentry_sdk is not installed "
                 "(it is not in deploy/requirements.txt) -- crash files only")
        return False
    try:
        sentry_sdk.init(dsn=dsn, release=f"ccsync-dashboard@{VERSION}",
                        send_default_pii=False, traces_sample_rate=0.0)
        _sentry = sentry_sdk
        log.info("crash reporting: sending to DASH_SENTRY_DSN (opt-in)")
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


# -- optional json-lines rotation -------------------------------------------

class JsonLinesFormatter(logging.Formatter):
    """One JSON object per line. Docker's log driver keeps stdout as text; this
    is for the file under DASH_LOG_DIR, which is read by a machine more often
    than by a person."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "t": datetime.fromtimestamp(record.created, timezone.utc)
                 .isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def install_log_rotation(directory: Optional[str] = None) -> Optional[Path]:
    """Add a rotating json-lines handler to the `ccsync` logger. Never raises.

    ADDITIVE: stdout keeps everything it had, because `docker logs` and the
    TrueNAS/DSM app UIs are still where an operator looks first. Absent
    DASH_LOG_DIR this does nothing at all, which is the shipped default -- a
    file in /data that nobody asked for is 15 MB of somebody's pool.
    """
    target = (directory if directory is not None
              else os.environ.get("DASH_LOG_DIR", "")).strip()
    if not target:
        return None
    try:
        path = Path(target)
        path.mkdir(parents=True, exist_ok=True)
        log_file = path / "dashboard.jsonl"
        root = logging.getLogger("ccsync")
        # Idempotent: create_app() runs once per process, but uvicorn --reload
        # and the test suite both construct apps repeatedly, and a second
        # handler on the same file means every line twice.
        for handler in root.handlers:
            if getattr(handler, "baseFilename", None) == str(log_file.resolve()):
                return log_file
        handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS,
            encoding="utf-8")
        handler.setFormatter(JsonLinesFormatter())
        root.addHandler(handler)
        if root.level == logging.NOTSET:
            root.setLevel(logging.INFO)
        return log_file
    except Exception:  # noqa: BLE001
        return None


# -- the hooks --------------------------------------------------------------

_installed = False


def handle(exc_type, exc_value, exc_tb, thread: str = "MainThread",
           settings: Any = None) -> Optional[Path]:
    try:
        path = write_report(
            build_report(exc_type, exc_value, exc_tb, thread=thread,
                         settings=settings), settings)
        if path is not None:
            log.error("unhandled exception in %s -- crash report written to %s",
                      thread, path)
        if isinstance(exc_value, BaseException):
            _send(exc_value)
        return path
    except Exception:  # noqa: BLE001
        return None


def install(settings: Any = None) -> None:
    """Chain onto sys.excepthook / threading.excepthook, then wire the optional
    sender and the optional rotating file. Idempotent, never raises.

    Called from create_app() rather than run(): the container's entrypoint is
    `uvicorn --factory`, so run() is not on the path in production at all --
    hooking there would have covered exactly the case nobody deploys.
    """
    global _installed
    if _installed:
        return
    _installed = True

    previous_hook = sys.excepthook
    previous_thread_hook = getattr(threading, "excepthook", None)

    def _hook(exc_type, exc_value, exc_tb):
        if not issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            handle(exc_type, exc_value, exc_tb, "MainThread", settings)
        previous_hook(exc_type, exc_value, exc_tb)

    def _thread_hook(args):
        # The collector thread is the reason this exists: it can die leaving a
        # container that answers 200 forever (DASH-2).
        if args.exc_type is not None and not issubclass(
                args.exc_type, (KeyboardInterrupt, SystemExit)):
            name = getattr(args.thread, "name", None) or "unknown-thread"
            handle(args.exc_type, args.exc_value, args.exc_traceback, name, settings)
        if previous_thread_hook is not None:
            previous_thread_hook(args)

    sys.excepthook = _hook
    if previous_thread_hook is not None:
        threading.excepthook = _thread_hook

    install_log_rotation()
    init_sender()


def _reset_for_tests() -> None:
    global _installed, _sentry
    _installed = False
    _sentry = None
