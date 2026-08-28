"""Reporter health, clock skew and the three tray lines that surface them.

Resilience sweep 2026-08-28: APP-1 (nobody was told when the dashboard stopped
accepting this machine's reports), APP-6 (a crash report was written and
surfaced nowhere) and APP-13/SYS-4 (nothing measured clock skew, while the
server's own `received_at` was in every report reply and thrown away).

No network and no Tk: the reporter takes an injected `http_post` and the tray
lines are pure functions of the `sync_guard` dict (test_tray_guard.py's rule).
"""

from __future__ import annotations

import json
import time
import urllib.error

import pytest

from ccsync_companion import reporter as reporter_mod
from ccsync_companion.reporter import DashboardReporter
from ccsync_companion.tray import (
    REPORTER_FAILURE_STREAK,
    _clock_skew_line,
    _crashes_line,
    _reporter_line,
)


def _cfg(**overrides):
    cfg = {
        "editor_name": "owen",
        "dashboard_url": "http://dash.example.com",
        "dashboard_token": "tok123",
        "dashboard_report_interval": 60,
    }
    cfg.update(overrides)
    return cfg


def _reporter(tmp_path, post, notify=None):
    return DashboardReporter(lambda: [], _cfg(), http_post=post,
                             notify=notify, state_dir=tmp_path / "state")


def _http_error(code):
    return urllib.error.HTTPError("http://dash.example.com/api/v1/report", code,
                                  "nope", {}, None)


# -- APP-1: the health record ----------------------------------------------


def test_a_fresh_reporter_has_never_succeeded(tmp_path):
    health = _reporter(tmp_path, lambda *a: {}).health()
    assert health == {"last_success_at": None, "last_status": None,
                      "consecutive_failures": 0}


def test_a_successful_report_stamps_the_health_record(tmp_path):
    reporter = _reporter(tmp_path, lambda *a: {})
    reporter.post_once()
    health = reporter.health()
    assert health["last_status"] == "ok"
    assert health["consecutive_failures"] == 0
    # ISO-8601 UTC, the same spelling the dashboard's own received_at uses --
    # this string is what the fleet grid renders.
    assert str(health["last_success_at"]).endswith("+00:00")


def test_a_failed_report_counts_the_streak_and_names_the_status(tmp_path):
    def boom(*args):
        raise _http_error(401)

    reporter = _reporter(tmp_path, boom)
    for _ in range(3):
        with pytest.raises(urllib.error.HTTPError):
            reporter.post_once()
    health = reporter.health()
    assert health["consecutive_failures"] == 3
    assert health["last_status"] == "HTTP 401"
    assert health["last_success_at"] is None


def test_a_non_http_failure_is_named_by_its_exception_class(tmp_path):
    def boom(*args):
        raise TimeoutError("the NAS is rebooting")

    reporter = _reporter(tmp_path, boom)
    with pytest.raises(TimeoutError):
        reporter.post_once()
    assert reporter.health()["last_status"] == "TimeoutError"


def test_a_success_clears_the_streak(tmp_path):
    calls = {"n": 0}

    def flaky(*args):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("later")
        return {}

    reporter = _reporter(tmp_path, flaky)
    for _ in range(2):
        with pytest.raises(TimeoutError):
            reporter.post_once()
    assert reporter.consecutive_failures == 2
    reporter.post_once()
    assert reporter.consecutive_failures == 0
    assert reporter.last_status == "ok"


def test_a_failure_that_never_reached_the_post_still_counts(tmp_path):
    """_run_cycle owns this half: a getter that raises inside _build_payload
    is still a report that did not arrive."""
    reporter = DashboardReporter(lambda: (_ for _ in ()).throw(RuntimeError("boom")),
                                 _cfg(), http_post=lambda *a: {},
                                 state_dir=tmp_path / "state")
    reporter._run_cycle()
    assert reporter.consecutive_failures == 1
    assert reporter.last_status == "RuntimeError"


def test_the_health_record_survives_a_restart(tmp_path):
    first = _reporter(tmp_path, lambda *a: {})
    first.post_once()
    stamp = first.health()["last_success_at"]

    def boom(*args):
        raise TimeoutError("gone")

    second = _reporter(tmp_path, boom)
    # A restart knows when it last worked, which is the whole point: "not
    # reachable since Tuesday" is the fact a restart used to destroy.
    assert second.health()["last_success_at"] == stamp
    assert second.consecutive_failures == 0
    with pytest.raises(TimeoutError):
        second.post_once()
    assert second.health()["last_success_at"] == stamp


def test_a_corrupt_health_file_is_not_a_construction_failure(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / reporter_mod.REPORTER_STATE_FILENAME).write_text("{not json",
                                                             encoding="utf-8")
    reporter = _reporter(tmp_path, lambda *a: {})
    assert reporter.health()["last_success_at"] is None


def test_the_health_file_is_written_atomically(tmp_path):
    reporter = _reporter(tmp_path, lambda *a: {})
    reporter.post_once()
    path = tmp_path / "state" / reporter_mod.REPORTER_STATE_FILENAME
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["last_status"] == "ok"
    assert not (tmp_path / "state" / f"{reporter_mod.REPORTER_STATE_FILENAME}.tmp").exists()


# -- APP-1: 401/403 is a human's problem ------------------------------------


def test_a_rejected_credential_toasts_once_and_only_once(tmp_path):
    toasts = []

    def boom(*args):
        raise _http_error(403)

    reporter = _reporter(tmp_path, boom, notify=toasts.append)
    for _ in range(5):
        with pytest.raises(urllib.error.HTTPError):
            reporter.post_once()
    assert len(toasts) == 1
    assert "rejected" in toasts[0]
    assert "sign in again" in toasts[0]


def test_a_timeout_never_toasts(tmp_path):
    toasts = []

    def boom(*args):
        raise TimeoutError("the NAS is rebooting")

    reporter = _reporter(tmp_path, boom, notify=toasts.append)
    for _ in range(5):
        with pytest.raises(TimeoutError):
            reporter.post_once()
    assert toasts == []


def test_a_rejected_credential_re_logs_at_warning_every_hour(tmp_path, caplog):
    def boom(*args):
        raise _http_error(401)

    reporter = _reporter(tmp_path, boom)
    with caplog.at_level("WARNING", logger="ccsync.reporter"):
        reporter._run_cycle()          # first of the streak: WARNING
        reporter._run_cycle()          # a repeat: DEBUG, as before
        assert len(caplog.records) == 1
        # An hour later the same dead credential is worth saying again -- the
        # old "WARNING once, DEBUG forever" rule is what made a revoked token
        # look like a five-second timeout in the log a support session reads.
        reporter._auth_warned_at -= (reporter_mod.AUTH_RELOG_SECONDS + 1)
        reporter._run_cycle()
        assert len(caplog.records) == 2


def test_a_working_credential_re_arms_the_toast(tmp_path):
    toasts = []
    calls = {"n": 0}

    def flaky(*args):
        calls["n"] += 1
        if calls["n"] in (1, 3):
            raise _http_error(401)
        return {}

    reporter = _reporter(tmp_path, flaky, notify=toasts.append)
    with pytest.raises(urllib.error.HTTPError):
        reporter.post_once()
    reporter.post_once()
    with pytest.raises(urllib.error.HTTPError):
        reporter.post_once()
    assert len(toasts) == 2


# -- APP-13 / SYS-4: clock skew --------------------------------------------


def test_skew_is_measured_from_the_replys_received_at(tmp_path):
    server = time.time() - 1200      # this computer is 20 minutes AHEAD
    reply = {"ok": True, "received_at": reporter_mod._iso_utc(server)}
    reporter = _reporter(tmp_path, lambda *a: reply)
    reporter.post_once()
    assert reporter.clock_skew_seconds is not None
    assert 1150 < reporter.clock_skew_seconds < 1250


def test_a_reply_with_no_received_at_leaves_no_skew(tmp_path):
    """An older dashboard sends no such field. That is a None, never an
    exception, and never a zero -- "could not check" is not "the clock is
    fine"."""
    reporter = _reporter(tmp_path, lambda *a: {"ok": True, "lanes": 3})
    reporter.post_once()
    assert reporter.clock_skew_seconds is None
    assert reporter.last_status == "ok"


def test_a_junk_received_at_does_not_crash_the_report(tmp_path):
    for value in ("not a date", "", None, [], {"a": 1}):
        reporter = _reporter(tmp_path, lambda *a, v=value: {"received_at": v})
        reporter.post_once()
        assert reporter.clock_skew_seconds is None


def test_a_naive_received_at_is_read_as_utc():
    # CR-89 cost the dashboard three days by guessing the other way.
    naive = reporter_mod.parse_server_time("2026-08-28T09:15:00")
    aware = reporter_mod.parse_server_time("2026-08-28T09:15:00+00:00")
    assert naive == aware
    assert reporter_mod.parse_server_time("2026-08-28T09:15:00Z") == aware


def test_large_skew_warns_at_most_once_an_hour(tmp_path, caplog):
    reply = {"received_at": reporter_mod._iso_utc(time.time() - 4000)}
    reporter = _reporter(tmp_path, lambda *a: reply)
    with caplog.at_level("WARNING", logger="ccsync.reporter"):
        reporter.post_once()
        reporter.post_once()
        assert len(caplog.records) == 1
        reporter._skew_warned_at -= (reporter_mod.CLOCK_SKEW_RELOG_SECONDS + 1)
        reporter.post_once()
        assert len(caplog.records) == 2


def test_a_correct_clock_does_not_warn(tmp_path, caplog):
    reply = {"received_at": reporter_mod._iso_utc(time.time() - 2)}
    reporter = _reporter(tmp_path, lambda *a: reply)
    with caplog.at_level("WARNING", logger="ccsync.reporter"):
        reporter.post_once()
    assert caplog.records == []
    assert abs(reporter.clock_skew_seconds) < 60


def test_the_skew_survives_a_restart(tmp_path):
    reply = {"received_at": reporter_mod._iso_utc(time.time() - 3600)}
    _reporter(tmp_path, lambda *a: reply).post_once()
    assert _reporter(tmp_path, lambda *a: {}).clock_skew_seconds > 3000


def test_skew_phrase_says_which_way():
    assert reporter_mod.skew_phrase(1200) == "20 minutes ahead"
    assert reporter_mod.skew_phrase(-1200) == "20 minutes behind"
    assert reporter_mod.skew_phrase(-7200) == "2 hours behind"
    assert reporter_mod.skew_phrase(-3600) == "60 minutes behind"
    assert reporter_mod.skew_phrase(-61) == "61 seconds behind"
    assert reporter_mod.skew_phrase(None) == ""
    assert reporter_mod.skew_phrase("nonsense") == ""


# -- the tray lines --------------------------------------------------------


def _guard(**fields):
    return fields


def test_no_reporter_line_while_the_dashboard_is_answering():
    assert _reporter_line({}) is None
    assert _reporter_line(_guard(reporter={"consecutive_failures": 0,
                                           "last_status": "ok"})) is None


def test_no_reporter_line_below_the_streak():
    guard = _guard(reporter={"consecutive_failures": REPORTER_FAILURE_STREAK - 1,
                             "last_status": "TimeoutError"})
    assert _reporter_line(guard) is None


def test_the_reporter_line_names_how_long_it_has_been():
    stamp = reporter_mod._iso_utc(time.time() - 3 * 3600)
    guard = _guard(reporter={"consecutive_failures": REPORTER_FAILURE_STREAK,
                             "last_status": "TimeoutError",
                             "last_success_at": stamp})
    line = _reporter_line(guard)
    assert "3h" in line
    assert "admin" in line
    assert "—" not in line


def test_the_reporter_line_names_a_rejected_credential_differently():
    guard = _guard(reporter={"consecutive_failures": 40, "last_status": "HTTP 401",
                             "last_success_at": reporter_mod._iso_utc(time.time())})
    line = _reporter_line(guard)
    assert "sign-in was rejected" in line
    assert "Sign in again" in line


def test_the_reporter_line_says_never_when_nothing_was_ever_accepted():
    guard = _guard(reporter={"consecutive_failures": 99, "last_status": "HTTP 404",
                             "last_success_at": None})
    assert "never accepted" in _reporter_line(guard)


def test_the_clock_line_appears_past_a_minute_and_says_which_way():
    assert _clock_skew_line({}) is None
    assert _clock_skew_line(_guard(clock_skew_seconds=30)) is None
    slow = _clock_skew_line(_guard(clock_skew_seconds=-1200))
    assert "20 minutes behind" in slow
    assert "will not work correctly" in slow
    assert "20 minutes ahead" in _clock_skew_line(_guard(clock_skew_seconds=1200))


def test_the_crash_line_appears_only_with_a_crash():
    assert _crashes_line({}) is None
    assert _crashes_line(_guard(crashes={"count": 0})) is None
    line = _crashes_line(_guard(crashes={"count": 2, "newest": "x.json"}))
    assert "background task failed" in line
    assert "diagnostics" in line


def test_a_junk_guard_never_takes_a_line_down():
    for junk in ({"reporter": "nope"}, {"crashes": 7}, {"clock_skew_seconds": "x"}):
        assert _reporter_line(junk) is None or isinstance(_reporter_line(junk), str)
        assert _crashes_line(junk) is None or isinstance(_crashes_line(junk), str)
        assert _clock_skew_line(junk) is None
