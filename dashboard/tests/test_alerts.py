"""alerts.py: the fleet's self-diagnosis scan and its delivery (SYS-8,
resilience sweep 2026-08-28).

Pins the resilience sweep 2026-08-28 fix pass: `scan()` finds real
conditions in a seeded database, `deliver()` dedups and recovers correctly,
sink `none` never stands `weekly_send_failed` up forever (finding 2), sink
`webhook` posts JSON to an https URL through a stubbed opener and a failed
send becomes a finding, `/api/v1/health` counts open alerts, the weekly
report names what it checked, and no secret ever reaches a page or a
response.
"""

from __future__ import annotations

import json
import urllib.error

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import alerts
from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"
NOW = "2026-08-28T12:00:00+00:00"
A_DAY_LATER = "2026-08-29T12:00:00+00:00"


def report_headers(editor="jsmith", token="sekrit"):
    return {"X-CCSync-Token": token,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def payload(guard=None):
    body = {
        "editor_name": "JSmith",
        "machine": "EDIT-PC",
        "companion_version": "0.9.55",
        "reported_at": NOW,
        "lanes": [
            {"name": "lane_b_proxy_down", "state": "idle", "queued": 0,
             "transferring": 0, "last_error": None, "last_sync": None},
        ],
    }
    if guard is not None:
        body["sync_guard"] = guard
    return body


@pytest.fixture
def env(tmp_path):
    app = create_app(Settings(
        db_path=str(tmp_path / "dash.db"), report_token="sekrit",
        session_secret=SECRET, admin_users=frozenset({"owen"}),
    ))
    with TestClient(app) as client:
        # The real background Collector thread starts on lifespan entry and
        # runs `alerts` (SYNCTHING_FREE_KINDS) on its own connection -- left
        # running, it races every direct alerts.scan/deliver/run_cycle call
        # below, both for "database is locked" (two writers) and for
        # `weekly_due()` (it can send the once-per-week report before the
        # test's own call gets to).
        client.app.state.collector.stop()
        conn = dbmod.connect(tmp_path / "dash.db")
        # The collector's first cycle can still have run (and delivered/
        # recorded a weekly report) in the gap between thread start and
        # stop() above -- a real thread-scheduling race, not something a
        # second stop() call can close. Reset to a clean, deterministic
        # baseline rather than assert around it.
        conn.execute("DELETE FROM alert_log")
        conn.execute("DELETE FROM notices")
        conn.commit()
        try:
            yield client, conn, app.state.settings
        finally:
            conn.close()


def as_admin(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    return client


# ------------------------------------------------------------- scan() findings

def test_scan_finds_a_tripped_breaker(env):
    client, conn, settings = env
    client.post("/api/v1/report", json=payload({
        "lane_b_breaker": {"tripped": True, "reason": "the NAS listed the tree as EMPTY"},
    }), headers=report_headers())
    findings = alerts.scan(conn, settings, NOW)
    kinds = {f["kind"] for f in findings}
    assert "breaker_tripped" in kinds


def test_scan_finds_a_fleet_halt(env):
    client, conn, settings = env
    dbmod.set_fleet_halt(conn, True, "restoring the pool", "owen", now=NOW)
    conn.commit()
    findings = alerts.scan(conn, settings, NOW)
    kinds = {f["kind"] for f in findings}
    assert "fleet_halt" in kinds


def test_scan_finds_a_computer_that_has_gone_quiet(env):
    """"editor behind" in the sense the registry actually has one: a
    computer that has stopped reporting altogether (`machine_silent`)."""
    client, conn, settings = env
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    conn.execute(
        "UPDATE lane_report_current SET received_at=? "
        "WHERE editor_username='jsmith' AND machine='EDIT-PC'", (NOW,))
    conn.commit()
    findings = alerts.scan(conn, settings, A_DAY_LATER)
    kinds = {f["kind"] for f in findings}
    assert "machine_silent" in kinds


def test_scan_finds_an_unreachable_update_feed(env):
    _client, conn, settings = env
    dbmod.set_feed_state(conn, last_checked_at=NOW, last_error="connection refused")
    conn.commit()
    findings = alerts.scan(conn, settings, A_DAY_LATER)
    kinds = {f["kind"] for f in findings}
    assert "feed_stale" in kinds


# ----------------------------------------------------------------- deliver()

def test_dedup_sends_an_open_error_once_per_window(env):
    client, conn, settings = env
    client.post("/api/v1/report", json=payload({
        "lane_b_breaker": {"tripped": True, "reason": "boom"},
    }), headers=report_headers())
    findings = alerts.scan(conn, settings, NOW)
    alerts.deliver(conn, settings, findings, NOW)
    alerts.deliver(conn, settings, findings, NOW)   # same cycle, same finding
    rows = [r for r in dbmod.fetch_alerts(conn, limit=50)
           if r["kind"] == "breaker_tripped"]
    assert len(rows) == 1


def test_recovery_message_is_sent_once_and_names_the_clearing(env):
    client, conn, settings = env
    client.post("/api/v1/report", json=payload({
        "lane_b_breaker": {"tripped": True, "reason": "boom"},
    }), headers=report_headers())
    findings = alerts.scan(conn, settings, NOW)
    alerts.deliver(conn, settings, findings, NOW)
    # deliver() does not commit (run_cycle does): leaving this open would
    # hold the write lock across the next client.post() below, which opens
    # its OWN connection to the same file and would deadlock against it.
    conn.commit()

    client.post("/api/v1/report", json=payload({
        "lane_b_breaker": {"tripped": False},
    }), headers=report_headers())
    clean = alerts.scan(conn, settings, A_DAY_LATER)
    assert not any(f["kind"] == "breaker_tripped" for f in clean)
    result = alerts.deliver(conn, settings, clean, A_DAY_LATER)
    assert result["recovered"] == 1
    recovered_rows = [r for r in dbmod.fetch_alerts(conn, limit=50)
                      if r["kind"] == "breaker_tripped.ok"]
    assert len(recovered_rows) == 1

    # A second clean pass finds nothing left to recover.
    result2 = alerts.deliver(conn, settings, clean, A_DAY_LATER)
    assert result2["recovered"] == 0
    assert len([r for r in dbmod.fetch_alerts(conn, limit=50)
               if r["kind"] == "breaker_tripped.ok"]) == 1


# ------------------------------------------------------------ the weekly report

def test_sink_none_records_the_weekly_report_and_raises_no_finding(env):
    """Finding 2 (resilience sweep 2026-08-28 fix pass). The vendor default
    has no sink; the weekly report must still be recorded (viewable on the
    Alerts page) and must not stand `weekly_send_failed` up forever."""
    _client, conn, settings = env
    assert alerts.get_settings(conn)["alerts_sink"] == alerts.SINK_NONE
    result = alerts.run_cycle(conn, settings, NOW)
    assert result["weekly"] is True
    weekly_rows = [r for r in dbmod.fetch_alerts(conn, limit=50) if r["kind"] == "weekly"]
    assert len(weekly_rows) == 1
    assert weekly_rows[0]["ok"] == 1
    assert "no sink configured" in weekly_rows[0]["detail"]
    findings = alerts.scan(conn, settings, NOW)
    assert not any(f["kind"] == "weekly_send_failed" for f in findings)


def test_weekly_report_names_what_it_checked(env):
    _client, conn, settings = env
    subject, text = alerts.compose_weekly(conn, NOW, settings)
    assert "CHECKED AND FOUND NOTHING WRONG" in text
    assert "  ok - " in text
    assert subject.startswith("CC Sync weekly:")


# --------------------------------------------------------------------- webhook

class _FakeResponse:
    def __init__(self, status=200, body=b"{}"):
        self.status = status
        self._body = body

    def read(self, *_a, **_k):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class _FakeOpener:
    def __init__(self, respond=None, raise_error=None):
        self.calls: list = []
        self._respond = respond
        self._raise_error = raise_error

    def open(self, request, timeout=None):
        self.calls.append(request)
        if self._raise_error is not None:
            raise self._raise_error
        return self._respond or _FakeResponse()


def _configure_webhook(conn, url="https://alerts.example.test/hook"):
    alerts.set_settings(
        conn, {"alerts_sink": "webhook", "alerts_webhook_url": url}, "owen")
    conn.commit()


def test_webhook_posts_subject_and_text_as_json_to_an_https_url(env, monkeypatch):
    """docs/GOTCHAS.md #12: stub the OPENER, never urlopen."""
    _client, conn, settings = env
    _configure_webhook(conn)
    fake = _FakeOpener()
    monkeypatch.setattr(alerts, "_webhook_opener", lambda: fake)
    result = alerts.send(conn, settings, "the subject", "the body text",
                         kind="test", dedup=False)
    assert result["ok"] is True
    assert len(fake.calls) == 1
    request = fake.calls[0]
    assert request.full_url == "https://alerts.example.test/hook"
    assert request.get_method() == "POST"
    sent = json.loads(request.data.decode("utf-8"))
    assert sent == {"subject": "the subject", "text": "the body text"}


def test_a_failed_webhook_send_becomes_weekly_send_failed(env, monkeypatch):
    _client, conn, settings = env
    _configure_webhook(conn)
    fake = _FakeOpener(raise_error=urllib.error.HTTPError(
        "https://alerts.example.test/hook", 500, "boom", {}, None))
    monkeypatch.setattr(alerts, "_webhook_opener", lambda: fake)
    result = alerts.run_cycle(conn, settings, NOW)
    assert result["weekly"] is False
    weekly_rows = [r for r in dbmod.fetch_alerts(conn, limit=50) if r["kind"] == "weekly"]
    assert weekly_rows[0]["ok"] == 0
    findings = alerts.scan(conn, settings, NOW)
    assert any(f["kind"] == "weekly_send_failed" for f in findings)


def test_a_working_webhook_never_stands_weekly_send_failed_up(env, monkeypatch):
    _client, conn, settings = env
    _configure_webhook(conn)
    fake = _FakeOpener()
    monkeypatch.setattr(alerts, "_webhook_opener", lambda: fake)
    result = alerts.run_cycle(conn, settings, NOW)
    assert result["weekly"] is True
    findings = alerts.scan(conn, settings, NOW)
    assert not any(f["kind"] == "weekly_send_failed" for f in findings)


# ------------------------------------------------------------------- /health

def test_health_counts_open_alerts_by_severity(env):
    client, conn, _settings = env
    dbmod.set_fleet_halt(conn, True, "restoring the pool", "owen", now=NOW)
    conn.commit()
    resp = as_admin(client).get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "open_alerts" in body
    assert body["open_alerts"]["warn"] >= 1     # fleet_halt is a warn kind


# -------------------------------------------------------------------- secrets

def test_no_secret_reaches_the_alerts_page_or_health(env):
    client, conn, settings = env
    secret_value = "hunter2-supersecret-smtp-password"
    alerts.set_password(settings, secret_value)
    alerts.set_settings(conn, {
        "alerts_sink": "smtp", "alerts_smtp_host": "mail.example.test",
        "alerts_smtp_from": "ccsync@example.test", "alerts_smtp_to": "owen@example.test",
    }, "owen")
    conn.commit()

    page = as_admin(client).get("/admin/alerts")
    assert page.status_code == 200
    assert secret_value not in page.text

    health = as_admin(client).get("/api/v1/health")
    assert secret_value not in health.text

    view = alerts.settings_view(conn, settings)
    assert secret_value not in json.dumps(view)
    assert view["password_set"] is True
