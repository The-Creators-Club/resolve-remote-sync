"""crash_report: the local file always, the network sender only when asked.

conftest's autouse _isolate_ccsync_home redirects HOME and CONFIG_DIR, and
crash_dir() derives from config.resolved_log_path() precisely so it follows
that redirection -- these tests would otherwise scatter JSON through the
developer's real ~/.ccsync/crashes, which is the class of accident that
fixture exists for.
"""

from __future__ import annotations

import json
import os
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


# -- APP-6: what an admin can actually see (resilience sweep 2026-08-28) -----


def test_crash_summary_is_empty_before_anything_crashes(tmp_path):
    summary = crash_report.crash_summary(_cfg(tmp_path))
    assert summary == {"count": 0, "newest": None}


def test_crash_summary_counts_and_names_the_newest(tmp_path):
    cfg = _cfg(tmp_path)
    assert crash_report.crash_summary(cfg)["count"] == 0
    # An OLDER report, written by hand: the filename carries the stamp at
    # second resolution, so two crashes in the same second are one file (which
    # is a property of the writer, not of the counting).
    directory = crash_report.crash_dir(cfg)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "20260101T000000+0000-lane-a.json").write_text("{}", encoding="utf-8")
    crash_report.invalidate_summary()
    try:
        _boom()
    except ValueError:
        crash_report.handle(*sys.exc_info(), "lane-b", cfg)
    # The cache MUST have been invalidated by the write: a count taken before
    # the crash is exactly the silence APP-6 is about.
    summary = crash_report.crash_summary(cfg)
    assert summary["count"] == 2
    newest = sorted(p.name for p in directory.glob("*.json"))[-1]
    assert summary["newest"] == newest
    assert "lane-b" in summary["newest"]


def test_recent_reports_carries_the_exception_type(tmp_path):
    cfg = _cfg(tmp_path)
    try:
        _boom()
    except ValueError:
        crash_report.handle(*sys.exc_info(), "ccsync-sequencer", cfg)
    entries = crash_report.recent_reports(cfg)
    assert len(entries) == 1
    assert entries[0]["type"] == "ValueError"
    assert entries[0]["thread"] == "ccsync-sequencer"
    assert entries[0]["name"].endswith(".json")


def test_an_unreadable_crash_file_is_reported_not_dropped(tmp_path):
    cfg = _cfg(tmp_path)
    directory = crash_report.crash_dir(cfg)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "20260828T090000+0000-lane-a.json").write_text("{not json",
                                                                encoding="utf-8")
    crash_report.invalidate_summary()
    assert crash_report.crash_summary(cfg)["count"] == 1
    assert crash_report.recent_reports(cfg)[0]["type"] == "<unreadable>"


def test_the_summary_never_raises_on_a_hopeless_config(monkeypatch):
    def _explode(cfg=None):
        raise RuntimeError("no home directory")

    monkeypatch.setattr(crash_report, "crash_dir", _explode)
    crash_report.invalidate_summary()
    assert crash_report.crash_summary({}) == {"count": 0, "newest": None}
    assert crash_report.recent_reports({}) == []


def test_install_logs_what_an_earlier_run_left_behind(tmp_path, caplog):
    cfg = _cfg(tmp_path)
    try:
        _boom()
    except ValueError:
        crash_report.handle(*sys.exc_info(), "lane-a", cfg)
    crash_report._reset_for_tests()
    with caplog.at_level("WARNING", logger="ccsync.crash"):
        crash_report.install(cfg)
    assert any("from an earlier run" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# the native half: a death no Python hook can see (CR-93)
# ---------------------------------------------------------------------------


def test_install_native_claims_a_run_marker(tmp_path):
    cfg = _cfg(tmp_path)
    crash_report.install_native(cfg)
    marker = json.loads(crash_report.run_marker_path(cfg).read_text(encoding="utf-8"))
    assert marker["pid"] == os.getpid()
    assert marker["version"] == config_mod.VERSION
    # A first run on a clean machine is not a crash.
    assert crash_report.crash_summary(cfg)["count"] == 0


def test_faulthandler_writes_where_the_crash_files_live(tmp_path):
    """A Tcl_Panic is an abort, not an exception: the only thing that can
    describe it is faulthandler's own dump, and it has to land somewhere an
    admin is already being pointed at."""
    import faulthandler

    cfg = _cfg(tmp_path)
    crash_report.install_native(cfg)
    assert faulthandler.is_enabled()
    assert crash_report.native_log_path(cfg).is_file()
    assert crash_report.native_log_path(cfg).parent == crash_report.crash_dir(cfg)


def test_a_run_that_never_reached_shutdown_is_reported_on_the_next_start(tmp_path):
    cfg = _cfg(tmp_path)
    crash_report.install_native(cfg)          # run 1 claims the marker
    crash_report._reset_for_tests()
    crash_report.install_native(cfg)          # run 2 finds it still there

    files = sorted(crash_report.crash_dir(cfg).glob("*.json"))
    assert len(files) == 1, "an unclean exit should write exactly one report"
    report = json.loads(files[0].read_text(encoding="utf-8"))
    assert report["exception"]["type"] == "UncleanExit"
    assert str(os.getpid()) in report["exception"]["message"]
    assert report["previous_run"]["version"] == config_mod.VERSION
    # And it reaches the surfaces APP-6 built: the tray line, the diagnostics
    # bundle and the dashboard all read these two.
    assert crash_report.crash_summary(cfg)["count"] == 1
    assert crash_report.recent_reports(cfg)[0]["type"] == "UncleanExit"


def test_mark_clean_exit_is_what_makes_the_next_start_quiet(tmp_path):
    cfg = _cfg(tmp_path)
    crash_report.install_native(cfg)
    crash_report.mark_clean_exit(cfg)
    assert not crash_report.run_marker_path(cfg).exists()

    crash_report._reset_for_tests()
    crash_report.install_native(cfg)
    assert crash_report.crash_summary(cfg)["count"] == 0


def test_mark_clean_exit_on_a_machine_that_never_started_is_harmless(tmp_path):
    """shutdown() can run before install_native ever did (a config so broken
    the app gives up early), and a crash handler may not become the crash."""
    crash_report.mark_clean_exit(_cfg(tmp_path))


def test_the_native_log_does_not_grow_without_bound(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    path = crash_report.native_log_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x" * 2048, encoding="utf-8")
    monkeypatch.setattr(crash_report, "NATIVE_LOG_MAX_BYTES", 1024)
    crash_report.install_native(cfg)
    assert path.stat().st_size < 2048


def test_an_unclean_exit_carries_the_native_dump_and_the_log_tail(tmp_path):
    cfg = _cfg(tmp_path)
    log_path = config_mod.resolved_log_path(cfg)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("2026-08-29 13:19:15,813 INFO tray: opening dashboard\n",
                        encoding="utf-8")
    crash_report.install_native(cfg)
    crash_report.native_log_path(cfg).write_text(
        "Fatal Python error: Aborted\n\nThread 0x00001234 (most recent call first):\n",
        encoding="utf-8")
    crash_report._reset_for_tests()
    crash_report.install_native(cfg)

    report = json.loads(sorted(crash_report.crash_dir(cfg).glob("*.json"))[0]
                        .read_text(encoding="utf-8"))
    assert "Fatal Python error" in report["exception"]["traceback"]
    assert any("opening dashboard" in line for line in report["log_tail"])


def test_an_unclean_exit_with_no_native_dump_says_where_else_to_look(tmp_path):
    """A Tcl_Panic on Windows reaches WER, not faulthandler. The report has to
    say so, or the next person reads "no traceback" as "no information"."""
    cfg = _cfg(tmp_path)
    crash_report.install_native(cfg)
    crash_report._reset_for_tests()
    crash_report.install_native(cfg)
    report = json.loads(sorted(crash_report.crash_dir(cfg).glob("*.json"))[0]
                        .read_text(encoding="utf-8"))
    assert "0x80000003" in report["exception"]["traceback"]
