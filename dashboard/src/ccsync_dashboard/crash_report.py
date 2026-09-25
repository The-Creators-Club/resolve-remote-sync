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

  ALWAYS   ${DASH_CRASH_DIR:-<DASH_DB_PATH's dir>/crashes}/<ts>-<thread>.json
           (then ~01, ~02 ... for more in one second),
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

import glob
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
    # bug-dash-ops-4 (2026-09-25): `\b` is no boundary after `_`, so the very
    # names above (TRUENAS_PW=, DASH_SESSION_SECRET=, SYNCTHING_API_KEY:) went
    # through untouched, and so did a JSON or dict-repr key, whose closing
    # quote sits between the name and the `:`. The boundary is now "not a
    # letter or digit" on both sides, a key may carry `_SUFFIX` parts
    # (SECRET_PREVIOUS, PW_FILE), and a quoted value is taken whole so a
    # passphrase with a space in it does not leave its second word behind.
    # Over-redacting a `token_count=5` is the cheap direction.
    (re.compile(r"(?i)(?<![a-z0-9])"
                r"((?:token|password|passwd|secret|api[_-]?key|dsn|pw)(?:_[a-z0-9]+)*)"
                r"(?![a-z0-9])[\"']?\s*[:=]\s*"
                r"(?:\"[^\"]*\"?|'[^']*'?|\S+)"),
     r"\1=<redacted>"),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@"), r"\1<redacted>@"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+"), "Bearer <redacted>"),
    # CR-266b (2026-09-11b): the key shapes that turn up BARE in an exception
    # message, with no `key=` in front of them to be recognised by the first
    # pattern - "Invalid API key: sk-ant-api03-...", a `cce1.` fleet token in
    # a 403 from our own API, a GitHub token in a release-lookup error. This
    # redactor is now also what `notices.error_detail` runs an exception
    # message through before writing it into a notice the home page renders,
    # so a shape that gets past here reaches a page and a database backup.
    (re.compile(r"(?i)\bsk-(?:ant-|proj-|or-)?[A-Za-z0-9_\-]{12,}"),
     "sk-<redacted>"),
    (re.compile(r"\bcce1\.[A-Za-z0-9._\-]{8,}"), "cce1.<redacted>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{8,}"), "gh_<redacted>"),
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
        base = f"{stamp or 'unknown'}-{thread}"
        # run.sh sets umask 077 already; this states it rather than inheriting
        # it, because a crash file is written by whatever thread crashes and
        # umask is process state anyone can change.
        #
        # bug-dash-ops-9 (2026-09-25): O_EXCL and a counter, not O_TRUNC. The
        # name is only second-resolution plus a thread name that repeats
        # (ThreadPoolExecutor-0_0, a restart loop), so a burst of two crashes
        # kept only the second - and the first of a burst is usually the cause.
        #
        # Owed round 2 (2026-09-25, the companion's review-round fix ported):
        # numbered past the HIGHEST slot on disk, not into the first free one,
        # and with `~NN`, not `-N`. `-` and a digit sort before the `.` of the
        # bare `<base>.json`, so `<base>-1.json` was named as OLDER than the
        # crash before it and _prune deleted the later crash of a burst first
        # (and `-10` sorted before `-2`); and once a prune freed the bare name,
        # a first-free search handed it, the OLDEST by the sort, to the newest
        # crash, which the next prune then deleted.
        taken = [_age_key(p) for p in directory.glob(f"{glob.escape(base)}*.json")]
        start = max((n + 1 for b, n in taken if b == base), default=0)
        handle = None
        path = directory / _crash_name(base, start)
        for n in range(start, 100):
            path = directory / _crash_name(base, n)
            try:
                handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                break
            except FileExistsError:
                continue
        if handle is None:
            return None
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        _prune(directory)
        return path
    except Exception:  # noqa: BLE001
        return None


# `~` because the prune sorts by NAME-derived age and the name starts with the
# UTC stamp: `~` (0x7e) sorts after the `.` of the bare `<base>.json`, the pad
# keeps 01..99 in order, and `~` can never come from `base` (the thread name
# is reduced to [A-Za-z0-9_.-]), so a thread called "Thread-1" is not mistaken
# for a counter. Same spelling as the companion's crash_report.
_COUNTER_SEP = "~"


def _crash_name(base: str, n: int) -> str:
    return f"{base}.json" if n == 0 else f"{base}{_COUNTER_SEP}{n:02d}.json"


def _age_key(path: Path) -> tuple[str, int]:
    """Oldest first. Spelled out rather than a plain name sort so the order
    does not rest on ASCII."""
    stem = path.name[:-len(".json")] if path.name.endswith(".json") else path.name
    base, sep, counter = stem.rpartition(_COUNTER_SEP)
    if sep and counter.isdigit():
        return base, int(counter)
    return stem, 0


def _prune(directory: Path, keep: Optional[int] = None) -> None:
    keep = MAX_CRASH_FILES if keep is None else keep
    try:
        files = sorted(directory.glob("*.json"), key=_age_key)
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
