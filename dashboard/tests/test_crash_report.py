"""crash_report: local crash files always, DSN sender and json-lines file opt-in.

The container's counterpart to ccsync_companion.crash_report. The case worth
covering is the COLLECTOR THREAD: it can die leaving a container that answers
200 on every route forever (DASH-2), and until now the only trace was a line in
`docker logs` that nothing rotated and nothing kept.
"""

from __future__ import annotations

import json
import logging
import sys
import threading

import pytest

from ccsync_dashboard import crash_report


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    """Hooks and the module latches are process-global; DASH_* env leaks
    between tests otherwise."""
    crash_report._reset_for_tests()
    for name in ("DASH_CRASH_DIR", "DASH_SENTRY_DSN", "DASH_LOG_DIR", "DASH_DB_PATH"):
        monkeypatch.delenv(name, raising=False)
    original, thread_original = sys.excepthook, threading.excepthook
    handlers = list(logging.getLogger("ccsync").handlers)
    yield
    sys.excepthook = original
    threading.excepthook = thread_original
    for handler in list(logging.getLogger("ccsync").handlers):
        if handler not in handlers:
            handler.close()
            logging.getLogger("ccsync").removeHandler(handler)
    crash_report._reset_for_tests()


class _Settings:
    def __init__(self, db_path):
        self.db_path = str(db_path)


def _boom():
    raise ValueError("kaboom")


# -- where the file lands ---------------------------------------------------

def test_crash_dir_defaults_to_beside_the_database(tmp_path):
    """/app is read-only (an image layer in image mode); /data is the one
    persistent writable volume every deployment has."""
    settings = _Settings(tmp_path / "dashboard.db")
    assert crash_report.crash_dir(settings) == tmp_path / "crashes"


def test_dash_crash_dir_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("DASH_CRASH_DIR", str(tmp_path / "elsewhere"))
    assert crash_report.crash_dir(_Settings("/data/x.db")) == tmp_path / "elsewhere"


def test_crash_dir_falls_back_to_the_env_when_there_are_no_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "d.db"))
    assert crash_report.crash_dir(None) == tmp_path / "crashes"


# -- the report -------------------------------------------------------------

def test_handle_writes_the_traceback(tmp_path):
    settings = _Settings(tmp_path / "dashboard.db")
    try:
        _boom()
    except ValueError:
        path = crash_report.handle(*sys.exc_info(), "MainThread", settings)

    assert path is not None and path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["component"] == "ccsync-dashboard"
    assert data["exception"]["type"] == "ValueError"
    assert "_boom" in data["exception"]["traceback"]


def test_secrets_in_the_message_are_redacted(tmp_path):
    """This container's environment holds TRUENAS_PW, DASH_SESSION_SECRET,
    BROLL_INGEST_TOKEN and SYNCTHING_API_KEY, and a crash file gets emailed."""
    settings = _Settings(tmp_path / "dashboard.db")
    try:
        raise RuntimeError("POST failed: token=abcdef123456 to "
                           "https://admin:hunter2@nas.example/api")
    except RuntimeError:
        path = crash_report.handle(*sys.exc_info(), "MainThread", settings)

    text = path.read_text(encoding="utf-8")
    assert "abcdef123456" not in text
    assert "hunter2" not in text
    assert "<redacted>" in text


def test_write_report_never_raises(monkeypatch):
    monkeypatch.setattr(crash_report, "crash_dir",
                        lambda settings=None: (_ for _ in ()).throw(OSError("nope")))
    assert crash_report.write_report({"when": "x"}) is None


def test_old_reports_are_pruned(tmp_path, monkeypatch):
    monkeypatch.setattr(crash_report, "MAX_CRASH_FILES", 2)
    settings = _Settings(tmp_path / "dashboard.db")
    for n in range(6):
        crash_report.write_report({"when": f"2026081700000{n}", "thread": "T"}, settings)
    assert len(list((tmp_path / "crashes").glob("*.json"))) == 2


# -- the hooks --------------------------------------------------------------

@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_dead_background_thread_leaves_a_crash_file(tmp_path):
    """DASH-2's shape: the thread dies, the container keeps answering, and the
    healthcheck's `ok` flag is the only symptom."""
    settings = _Settings(tmp_path / "dashboard.db")
    crash_report.install(settings)

    thread = threading.Thread(target=_boom, name="collector")
    thread.start()
    thread.join()

    files = list((tmp_path / "crashes").glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["thread"] == "collector"


def test_install_is_idempotent(tmp_path):
    settings = _Settings(tmp_path / "dashboard.db")
    crash_report.install(settings)
    first = sys.excepthook
    crash_report.install(settings)
    assert sys.excepthook is first


def test_create_app_installs_the_hooks(tmp_path, monkeypatch):
    """The entrypoint is `uvicorn --factory ...:create_app`, so run() is not on
    the production path at all -- hooking there would cover nothing deployed."""
    from ccsync_dashboard.app import create_app
    from ccsync_dashboard.settings import Settings

    monkeypatch.setenv("DASH_CRASH_DIR", str(tmp_path / "crashes"))
    before = sys.excepthook
    create_app(Settings(db_path=str(tmp_path / "dashboard.db"), broll_enabled=False))
    assert sys.excepthook is not before


# -- the opt-in halves ------------------------------------------------------

def test_no_sender_without_a_dsn():
    assert crash_report.sentry_dsn() == ""
    assert crash_report.init_sender() is False
    assert crash_report._sentry is None


def test_a_dsn_without_sentry_sdk_degrades_to_files(monkeypatch):
    """sentry_sdk is deliberately absent from deploy/requirements.txt."""
    monkeypatch.setenv("DASH_SENTRY_DSN", "https://k@example.invalid/1")
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)
    assert crash_report.init_sender() is False


def test_log_rotation_is_off_unless_asked(tmp_path):
    assert crash_report.install_log_rotation() is None
    assert crash_report.install_log_rotation("") is None


def test_log_rotation_writes_json_lines(tmp_path):
    path = crash_report.install_log_rotation(str(tmp_path / "logs"))
    assert path is not None

    logging.getLogger("ccsync.test").warning("hello token=abcdef123456")
    for handler in logging.getLogger("ccsync").handlers:
        handler.flush()

    line = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert line["level"] == "WARNING"
    assert line["logger"] == "ccsync.test"
    assert "abcdef123456" not in line["msg"]


def test_log_rotation_does_not_double_up(tmp_path):
    """create_app() runs once per process, but --reload and the suite both
    construct apps repeatedly, and a second handler means every line twice."""
    first = crash_report.install_log_rotation(str(tmp_path / "logs"))
    before = len(logging.getLogger("ccsync").handlers)
    second = crash_report.install_log_rotation(str(tmp_path / "logs"))
    assert first == second
    assert len(logging.getLogger("ccsync").handlers) == before


def test_log_rotation_never_raises(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    assert crash_report.install_log_rotation(str(blocker)) is None
