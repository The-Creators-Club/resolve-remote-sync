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

import dataclasses
import json
import ssl
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
    # deliver() commits around every send() since 2026-09-03 (database is
    # locked, api_report held the lock), so this is belt and braces now
    # rather than load-bearing: an open write transaction here would hold the
    # lock across the next client.post() below, which opens its OWN
    # connection to the same file.
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


# --------------------------------------------- bug-hunt-2026-09-03 fix pass

def test_a_crashed_check_is_not_printed_in_the_clean_list(env, monkeypatch):
    """dash-collector-1: `scan` files a crashed check under check_failed with
    the failing kind's NAME as its subject, so a clean list computed from
    by_kind alone printed `ok - <what>` for the very kind the same report
    lists under COULD NOT BE CHECKED."""
    _client, conn, settings = env
    victim = alerts.ALERT_KINDS[0]

    def _boom(_ctx):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(
        alerts, "ALERT_KINDS",
        (dataclasses.replace(victim, check=_boom),) + alerts.ALERT_KINDS[1:])
    _subject, text = alerts.compose_weekly(conn, NOW, settings)
    assert "COULD NOT BE CHECKED" in text
    assert victim.kind in text
    assert f"  ok - {victim.what}" not in text
    # The denominator still states how many kinds exist.
    assert f"of {len(alerts.ALERT_KINDS)})" in text


class _FakeSMTP:
    """Stands in for smtplib.SMTP through alerts._smtp_class."""

    seen: dict = {}

    def __init__(self, host, port, timeout=None):
        type(self).seen = {"host": host, "port": port}

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def starttls(self, context=None):
        type(self).seen["context"] = context

    def login(self, user, password):
        type(self).seen["login"] = user

    def send_message(self, message):
        type(self).seen["sent"] = True


def _configure_smtp(conn, **extra):
    values = {"alerts_sink": "smtp", "alerts_smtp_host": "mail.example.test",
              "alerts_smtp_from": "ccsync@example.test",
              "alerts_smtp_to": "owen@example.test"}
    values.update(extra)
    alerts.set_settings(conn, values, "owen")
    conn.commit()


def test_starttls_is_negotiated_with_a_verifying_context(env, monkeypatch):
    """dash-collector-3: a bare starttls() builds ssl._create_stdlib_context(),
    which checks neither the certificate nor the hostname - and the next call
    hands the stored SMTP password to whoever answered."""
    _client, conn, settings = env
    _configure_smtp(conn)
    monkeypatch.setattr(alerts, "_smtp_class", lambda: _FakeSMTP)
    result = alerts.send(conn, settings, "s", "t", kind="test", dedup=False)
    assert result["ok"] is True
    context = _FakeSMTP.seen["context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_the_certificate_check_can_be_turned_off_explicitly(env, monkeypatch):
    """dash-collector-3's other half: an opt-out an admin chose, never a
    silent fallback after a verification failure."""
    _client, conn, settings = env
    _configure_smtp(conn, alerts_smtp_verify_tls="0")
    monkeypatch.setattr(alerts, "_smtp_class", lambda: _FakeSMTP)
    alerts.send(conn, settings, "s", "t", kind="test", dedup=False)
    context = _FakeSMTP.seen["context"]
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE


def test_an_unverifiable_certificate_is_a_refusal_naming_the_host(env, monkeypatch):
    _client, conn, settings = env
    _configure_smtp(conn)

    class _RefusingSMTP(_FakeSMTP):
        def starttls(self, context=None):
            raise ssl.SSLCertVerificationError("self-signed certificate")

    monkeypatch.setattr(alerts, "_smtp_class", lambda: _RefusingSMTP)
    result = alerts.send(conn, settings, "s", "t", kind="test", dedup=False)
    assert result["ok"] is False
    assert "mail.example.test" in result["detail"]


def test_an_open_warn_is_still_offered_after_600_newer_rows(env):
    """dash-collector-4: a WARN writes ONE row and is then silent, so its row
    aged out of the 500-row window `_open_subjects` used to page - and once it
    had, no `<kind>.ok` was ever written and that subject's warn was muted for
    ever."""
    _client, conn, _settings = env
    dbmod.record_alert(conn, "folders_unfiltered", "ruskin/RUSKIN-PC", "", True,
                       "", NOW)
    for i in range(600):
        dbmod.record_alert(conn, "crashes", f"ed/M{i}", "", True, "", A_DAY_LATER)
    conn.commit()
    assert alerts._is_open(conn, "folders_unfiltered", "ruskin/RUSKIN-PC")
    offered = alerts._open_subjects(conn, {"folders_unfiltered"})
    assert ("folders_unfiltered", "ruskin/RUSKIN-PC") in offered


def test_only_the_webhook_origin_is_recorded_and_shown(env, monkeypatch):
    """dash-collector-5: a Slack/Teams/Discord URL's PATH is the credential,
    and alert_log plus the settings view are read from a backup."""
    _client, conn, settings = env
    url = "https://hooks.slack.test/services/T0000/B1111/abcdefSECRETdefgh"
    _configure_webhook(conn, url)
    fake = _FakeOpener()
    monkeypatch.setattr(alerts, "_webhook_opener", lambda: fake)
    result = alerts.send(conn, settings, "the subject", "the body",
                         kind="test", dedup=False)
    assert result["ok"] is True
    assert fake.calls[0].full_url == url            # the real URL is still used
    assert result["sent_to"] == "https://hooks.slack.test"
    rows = [r for r in dbmod.fetch_alerts(conn, limit=50) if r["kind"] == "test"]
    assert rows and "abcdefSECRETdefgh" not in str(rows[0]["sent_to"])

    view = alerts.settings_view(conn, settings)
    assert "abcdefSECRETdefgh" not in json.dumps(view)
    assert view["webhook_origin"] == "https://hooks.slack.test"


def test_saving_the_masked_webhook_url_back_keeps_the_stored_one(env):
    """The page renders the mask, so an untouched field posts the mask back."""
    _client, conn, settings = env
    url = "https://hooks.slack.test/services/T0000/B1111/abcdefSECRETdefgh"
    _configure_webhook(conn, url)
    view = alerts.settings_view(conn, settings)
    alerts.set_settings(conn, {"alerts_webhook_url": view["alerts_webhook_url"],
                               "alerts_smtp_host": "mail.example.test"}, "owen")
    conn.commit()
    assert alerts.get_settings(conn)["alerts_webhook_url"] == url


# ------------------------------ 2026-09-03, studio dashboard false alarms
#
# Three kinds fired on the live studio dashboard for states that are not
# problems. Each of these seeds the exact live state and asserts silence,
# with a companion case asserting the real fault still speaks.

def _base_rig_payload(**extra):
    body = payload({"syncthing_supervisor": {
        "down_since": "2026-08-22T12:00:00+00:00", "attempts": 3,
        "last_error": "no lane C on this machine"}})
    body["machine"] = "CREATOR-1"
    body.update(extra)
    return body


def test_a_wired_base_rig_is_never_the_sync_engine_being_down(env):
    """The base rig runs sync_enabled=false and starts no lanes, so its
    Syncthing is retired, not down - and the supervisor's incident is never
    polled clear. Six days of "the sync engine on alex/Creator_1 has been
    down" about the machine the tree lives on."""
    client, conn, settings = env
    client.post("/api/v1/report", json=_base_rig_payload(mode="base"),
                headers=report_headers())
    findings = alerts.scan(conn, settings, NOW)
    assert not any(f["kind"] == "engine_down" for f in findings)


def test_an_editors_machine_with_its_engine_down_still_alerts(env):
    client, conn, settings = env
    client.post("/api/v1/report", json=_base_rig_payload(mode="editor"),
                headers=report_headers())
    findings = alerts.scan(conn, settings, NOW)
    assert any(f["kind"] == "engine_down" for f in findings)


def test_an_empty_enforce_plan_is_not_a_sharing_change_being_held(env):
    """The collector writes DASH-3's dry-run record every cycle, so the
    steady state is a plan with nothing in it."""
    _client, conn, settings = env
    dbmod.record_enforce_plan(conn, NOW, [])
    conn.commit()
    findings = alerts.scan(conn, settings, NOW)
    assert not any(f["kind"] == "enforce_plan" for f in findings)


def test_a_plan_with_something_in_it_is_still_held(env):
    _client, conn, settings = env
    dbmod.record_enforce_plan(conn, NOW, [("2026-ff5", {"DEVICE-A"}, set())])
    conn.commit()
    findings = alerts.scan(conn, settings, NOW)
    assert any(f["kind"] == "enforce_plan" for f in findings)


def _publish(conn, version, *, rollout, is_current, platform="windows"):
    conn.execute(
        "INSERT INTO companion_packages (version, platform, filename, sha256, "
        "size_bytes, published_at, published_by, is_current, kind, rollout) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (version, platform, f"ccsync-{version}.exe", "0" * 64, 1,
         NOW, "owen", 1 if is_current else 0, "companion", rollout))


def _machine_on(client, version, machine="RUSKIN-PC"):
    body = payload({"crashes": {"count": 3, "newest": NOW}})
    body["machine"] = machine
    body["companion_version"] = version
    client.post("/api/v1/report", json=body, headers=report_headers())


def test_a_staged_build_older_than_current_has_lost_its_trial(env):
    """0.9.63 (windows) staged with three crashes, a week after 0.9.65 went
    current. A build that can never be handed to everybody cannot be a
    warning about handing it to everybody. version_tuple, never a string
    compare: the companion goes 0.9.9 -> 0.9.10."""
    client, conn, settings = env
    _publish(conn, "0.9.63", rollout="staged", is_current=False)
    _publish(conn, "0.9.65", rollout="current", is_current=True)
    conn.commit()
    _machine_on(client, "0.9.63")
    findings = alerts.scan(conn, settings, NOW)
    assert not any(f["kind"] == "soak_failed" for f in findings)


def test_a_staged_build_newer_than_current_still_fails_its_soak(env):
    client, conn, settings = env
    _publish(conn, "0.9.65", rollout="current", is_current=True)
    _publish(conn, "0.10.0", rollout="staged", is_current=False)
    conn.commit()
    _machine_on(client, "0.10.0")
    findings = alerts.scan(conn, settings, NOW)
    assert any(f["kind"] == "soak_failed" for f in findings)
