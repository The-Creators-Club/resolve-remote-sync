"""crash_report: the local file always, the network sender only when asked.

conftest's autouse _isolate_ccsync_home redirects HOME and CONFIG_DIR, and
crash_dir() derives from config.resolved_log_path() precisely so it follows
that redirection -- these tests would otherwise scatter JSON through the
developer's real ~/.ccsync/crashes, which is the class of accident that
fixture exists for.
"""

from __future__ import annotations

import json
import sys
import threading

import pytest

from ccsync_companion import config as config_mod
from ccsync_companion import crash_report


@pytest.fixture(autouse=True)
def _reset_hooks(monkeypatch):
    """`install()` latches process-globally and swaps sys.excepthook. Both are
    restored here so one test's hook cannot fire during another's failure."""
    crash_report._reset_for_tests()
    original, thread_original = sys.excepthook, threading.excepthook
    yield
    sys.excepthook = original
    threading.excepthook = thread_original
    crash_report._reset_for_tests()


def _cfg(tmp_path):
    return {"log_path": str(tmp_path / "companion.log")}


def _boom():
    raise ValueError("kaboom")


# -- the local half ---------------------------------------------------------

def test_crash_dir_follows_the_configured_log_path(tmp_path):
    cfg = _cfg(tmp_path)
    assert crash_report.crash_dir(cfg) == tmp_path / "crashes"


def test_crash_dir_survives_a_garbage_log_path():
    """resolved_log_path() never raises for exactly this reason; neither may we."""
    assert crash_report.crash_dir({"log_path": 5}).name == "crashes"


def test_handle_writes_a_report_with_the_traceback(tmp_path):
    cfg = _cfg(tmp_path)
    try:
        _boom()
    except ValueError:
        path = crash_report.handle(*sys.exc_info(), "MainThread", cfg)

    assert path is not None and path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["exception"]["type"] == "ValueError"
    assert "kaboom" in data["exception"]["message"]
    assert "_boom" in data["exception"]["traceback"]
    assert data["version"] == config_mod.VERSION
    assert data["thread"] == "MainThread"


def test_the_report_carries_the_tail_of_the_log(tmp_path):
    """The whole reason this exists: companion.log rotates at 5 MB, so the
    lines explaining a failure are usually gone by the time anyone asks."""
    log = tmp_path / "companion.log"
    log.write_text("\n".join(f"line {n}" for n in range(500)), encoding="utf-8")
    cfg = _cfg(tmp_path)

    try:
        _boom()
    except ValueError:
        path = crash_report.handle(*sys.exc_info(), "MainThread", cfg)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["log_tail"]) == crash_report.BREADCRUMB_LINES
    assert data["log_tail"][-1] == "line 499"


def test_a_huge_log_is_read_from_the_end_only(tmp_path):
    """A crash handler that pulls 5 MB into memory is a second failure."""
    log = tmp_path / "companion.log"
    log.write_text("x" * (crash_report.BREADCRUMB_MAX_BYTES * 2) + "\ntail line\n",
                   encoding="utf-8")
    tail = crash_report._tail(log)
    assert tail[-1] == "tail line"
    assert sum(len(line) for line in tail) <= crash_report.BREADCRUMB_MAX_BYTES


def test_a_missing_log_is_not_an_error(tmp_path):
    cfg = _cfg(tmp_path)
    try:
        _boom()
    except ValueError:
        path = crash_report.handle(*sys.exc_info(), "MainThread", cfg)
    assert json.loads(path.read_text(encoding="utf-8"))["log_tail"] == []


def test_secrets_in_the_breadcrumb_are_redacted(tmp_path):
    """This file is meant to be EMAILED, which companion.log never was."""
    log = tmp_path / "companion.log"
    log.write_text(
        "reporter: token=abcdef123456 posting\n"
        "rclone: sftp://editor:hunter2@nas.example/tree\n"
        "http: Authorization: Bearer eyJhbGciOi.PAYLOAD.sig\n",
        encoding="utf-8")
    tail = crash_report._tail(log)
    joined = "\n".join(tail)
    assert "abcdef123456" not in joined
    assert "hunter2" not in joined
    assert "eyJhbGciOi.PAYLOAD.sig" not in joined
    assert "<redacted>" in joined


def test_redaction_failure_is_not_a_crash(monkeypatch):
    monkeypatch.setattr(crash_report, "_REDACTIONS", "not iterable as pairs")
    assert crash_report.redact("anything") == "<redaction failed>"


def test_write_report_never_raises_on_an_unwritable_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(crash_report, "crash_dir",
                        lambda cfg=None: (_ for _ in ()).throw(OSError("nope")))
    assert crash_report.write_report({"when": "x"}, _cfg(tmp_path)) is None


def test_old_reports_are_pruned(tmp_path, monkeypatch):
    """A crash LOOP is when this directory would otherwise fill ~/.ccsync, and
    a crash loop is also when nobody is watching."""
    monkeypatch.setattr(crash_report, "MAX_CRASH_FILES", 3)
    cfg = _cfg(tmp_path)
    for n in range(8):
        crash_report.write_report(
            {"when": f"2026081700000{n}", "thread": "T"}, cfg)
    remaining = sorted(p.name for p in (tmp_path / "crashes").glob("*.json"))
    assert len(remaining) == 3
    assert remaining[-1].startswith("20260817000007")


def test_the_report_file_is_owner_only(tmp_path):
    """It carries absolute paths and a log tail; a default umask on Windows
    would hand it to every local account."""
    cfg = _cfg(tmp_path)
    path = crash_report.write_report({"when": "20260817T000000", "thread": "T"}, cfg)
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o077 == 0


# -- the hooks --------------------------------------------------------------

@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_install_catches_a_worker_thread_exception(tmp_path):
    """The failure mode this was built for: a lane thread dies, the tray stays
    up, and the only trace is a log line that later rotates away."""
    cfg = _cfg(tmp_path)
    crash_report.install(cfg)

    thread = threading.Thread(target=_boom, name="lane-b")
    thread.start()
    thread.join()

    files = list((tmp_path / "crashes").glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["thread"] == "lane-b"
    assert data["exception"]["type"] == "ValueError"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_install_chains_rather_than_replacing(tmp_path):
    """Python's own 'Exception in thread X' must survive: a reporter that
    swallows the interpreter's report makes the machine harder to debug."""
    seen = []
    threading.excepthook = lambda args: seen.append(args.exc_type)
    crash_report.install(_cfg(tmp_path))

    thread = threading.Thread(target=_boom, name="worker")
    thread.start()
    thread.join()

    assert seen == [ValueError]


def test_keyboard_interrupt_and_sysexit_are_not_crashes(tmp_path):
    cfg = _cfg(tmp_path)
    crash_report.install(cfg)
    for exc in (KeyboardInterrupt, SystemExit):
        try:
            raise exc()
        except BaseException:
            sys.excepthook(*sys.exc_info())
    assert not (tmp_path / "crashes").exists()


def test_install_is_idempotent(tmp_path):
    crash_report.install(_cfg(tmp_path))
    first = sys.excepthook
    crash_report.install(_cfg(tmp_path))
    assert sys.excepthook is first


# -- the opt-in network half ------------------------------------------------

def test_sender_is_off_by_default():
    assert crash_report.sentry_enabled(dict(config_mod.DEFAULTS)) is False
    assert config_mod.DEFAULTS["crash_reporting"] is False
    assert config_mod.DEFAULTS["crash_dsn"] == ""


def test_crash_reporting_true_with_no_dsn_still_sends_nothing():
    """There is no vendor endpoint compiled in -- `true` alone must not be
    read as 'send it somewhere sensible'."""
    assert crash_report.sentry_enabled({"crash_reporting": True, "crash_dsn": ""}) is False
    assert crash_report.sentry_enabled({"crash_reporting": True, "crash_dsn": "   "}) is False


def test_a_dsn_without_the_switch_sends_nothing():
    assert crash_report.sentry_enabled(
        {"crash_reporting": False, "crash_dsn": "https://k@example.invalid/1"}) is False


def test_init_sender_does_nothing_when_disabled(tmp_path):
    assert crash_report.init_sender(_cfg(tmp_path)) is False
    assert crash_report._sentry is None


def test_init_sender_degrades_when_sentry_sdk_is_absent(monkeypatch):
    """The frozen build deliberately does not ship sentry_sdk: a customer who
    turns this on without it must get crash FILES, not a broken companion."""
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
        else __builtins__.__import__

    def _no_sentry(name, *args, **kwargs):
        if name == "sentry_sdk":
            raise ImportError("no sentry_sdk in the frozen build")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _no_sentry)
    assert crash_report.init_sender(
        {"crash_reporting": True, "crash_dsn": "https://k@example.invalid/1"}) is False


def test_handle_sends_when_a_sender_is_live(tmp_path):
    sent = []

    class _FakeSentry:
        @staticmethod
        def capture_exception(exc):
            sent.append(exc)

    crash_report._sentry = _FakeSentry
    try:
        _boom()
    except ValueError as exc:
        crash_report.handle(*sys.exc_info(), "MainThread", _cfg(tmp_path))
        assert sent == [exc]


def test_a_failing_sender_never_breaks_the_local_report(tmp_path):
    class _BrokenSentry:
        @staticmethod
        def capture_exception(exc):
            raise RuntimeError("network is down")

    crash_report._sentry = _BrokenSentry
    cfg = _cfg(tmp_path)
    try:
        _boom()
    except ValueError:
        path = crash_report.handle(*sys.exc_info(), "MainThread", cfg)
    assert path is not None and path.exists()
