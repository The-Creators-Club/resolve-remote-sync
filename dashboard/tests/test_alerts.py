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


# ==================================================================== wave 2
#
# "The alarm reaches someone" (usability + resilience sweep 2026-09-04):
# SYS-1 / DDIAG-16 the sink is a protection line, DDIAG-17 the dead-man's
# heartbeat, DDIAG-4 turning a sink on re-raises what is already open, and
# DDIAG-3 a computer that has been gone a fortnight stops being a daily mail.

THREE_WEEKS_LATER = "2026-09-18T12:00:00+00:00"


def _warn_finding(subject="jsmith/EDIT-PC", kind="folders_unfiltered"):
    return {"kind": kind, "severity": alerts.SEV_WARN, "title": "a warn",
            "subject": subject, "diagnosis": "something to look at",
            "fix": "look at it", "detail": ""}


# ------------------------------------------------- SYS-1: sink_deliverable()

def test_no_sink_is_not_deliverable_and_says_so_in_english(env):
    _client, conn, _settings = env
    deliverable, detail = alerts.sink_deliverable(conn, NOW)
    assert deliverable is False
    assert "nothing this server finds is ever sent" in detail


def test_a_channel_that_has_never_delivered_is_not_deliverable(env):
    _client, conn, _settings = env
    _configure_webhook(conn)
    deliverable, detail = alerts.sink_deliverable(conn, NOW)
    assert deliverable is False
    assert "nothing has ever been sent" in detail


def test_a_channel_whose_last_send_failed_is_not_deliverable(env):
    _client, conn, _settings = env
    _configure_webhook(conn)
    dbmod.record_alert(conn, "test", "test", "webhook", True, "sent", NOW)
    dbmod.record_alert(conn, "test", "test", "", False, "boom", A_DAY_LATER)
    conn.commit()
    deliverable, detail = alerts.sink_deliverable(conn, A_DAY_LATER)
    assert deliverable is False
    assert "did not go out" in detail


def test_a_month_of_silence_on_a_configured_channel_is_the_same_hole(env):
    """DDIAG-16: a mailbox that stopped accepting mail in March looks
    identical to a working one from every page in this product."""
    _client, conn, _settings = env
    _configure_webhook(conn)
    dbmod.record_alert(conn, "weekly", "weekly", "webhook", True, "sent", NOW)
    conn.commit()
    assert alerts.sink_deliverable(conn, A_DAY_LATER)[0] is True
    assert alerts.sink_deliverable(conn, THREE_WEEKS_LATER)[0] is True
    assert alerts.sink_deliverable(conn, "2026-10-28T12:00:00+00:00")[0] is False


def test_the_no_sink_rows_are_not_evidence_about_a_new_channel(env):
    """A row recorded while the site had no sink says nothing about the
    channel it has just been given."""
    _client, conn, _settings = env
    dbmod.record_alert(conn, "machine_silent", "a/PC", "", False,
                       alerts.NO_SINK_DETAIL, NOW)
    _configure_webhook(conn)
    dbmod.record_alert(conn, "test", "test", "webhook", True, "sent", NOW)
    conn.commit()
    deliverable, _detail = alerts.sink_deliverable(conn, NOW)
    assert deliverable is True


# ------------------------------------------------------ DDIAG-17: heartbeat

def test_the_heartbeat_is_off_by_default_and_needs_a_channel(env):
    _client, conn, _settings = env
    assert alerts.get_settings(conn)["alerts_heartbeat"] == "0"
    assert alerts.heartbeat_due(conn, NOW) is False
    alerts.set_settings(conn, {"alerts_heartbeat": "1"}, "owen")
    conn.commit()
    assert alerts.heartbeat_due(conn, NOW) is False
    _configure_webhook(conn)
    assert alerts.heartbeat_due(conn, NOW) is True


def test_one_heartbeat_a_calendar_day_and_not_one_per_cycle(env, monkeypatch):
    _client, conn, settings = env
    _configure_webhook(conn)
    alerts.set_settings(conn, {"alerts_heartbeat": "1", "alerts_weekly": "0"},
                        "owen")
    conn.commit()
    fake = _FakeOpener()
    monkeypatch.setattr(alerts, "_webhook_opener", lambda: fake)
    monkeypatch.setattr(alerts, "scan", lambda *_a, **_kw: [])

    first = alerts.run_cycle(conn, settings, NOW)
    assert first["heartbeat"] is True
    assert len(fake.calls) == 1
    subject = json.loads(fake.calls[0].data.decode("utf-8"))["subject"]
    assert subject.startswith("CC Sync: all quiet")
    assert "computer" in subject and "problem" in subject

    for _ in range(10):
        assert alerts.run_cycle(conn, settings, NOW)["heartbeat"] is False
    assert len(fake.calls) == 1

    assert alerts.run_cycle(conn, settings, A_DAY_LATER)["heartbeat"] is True
    assert len(fake.calls) == 2


def test_the_heartbeat_is_never_a_problem_and_never_recovers(env, monkeypatch):
    """It reports no condition: it must not be a registry kind, must not
    reach CURRENTLY OPEN, and must never produce a cleared message."""
    _client, conn, settings = env
    _configure_webhook(conn)
    alerts.set_settings(conn, {"alerts_heartbeat": "1", "alerts_weekly": "0"},
                        "owen")
    conn.commit()
    monkeypatch.setattr(alerts, "_webhook_opener", lambda: _FakeOpener())
    monkeypatch.setattr(alerts, "scan", lambda *_a, **_kw: [])

    result = alerts.run_cycle(conn, settings, NOW)

    assert alerts.KIND_HEARTBEAT not in {k.kind for k in alerts.ALERT_KINDS}
    assert not any(result["open"].values())
    assert alerts.KIND_HEARTBEAT not in {
        kind for kind, _subject in alerts._open_subjects(
            conn, {k.kind for k in alerts.ALERT_KINDS})}
    kinds = {r["kind"] for r in dbmod.fetch_alerts(conn, limit=50)}
    assert alerts.KIND_HEARTBEAT in kinds
    assert alerts.KIND_HEARTBEAT + alerts.RECOVERED_SUFFIX not in kinds


def test_the_weekly_report_does_not_double_as_the_heartbeat(env, monkeypatch):
    _client, conn, settings = env
    _configure_webhook(conn)
    monkeypatch.setattr(alerts, "_webhook_opener", lambda: _FakeOpener())
    monkeypatch.setattr(alerts, "scan", lambda *_a, **_kw: [])
    result = alerts.run_cycle(conn, settings, NOW)
    assert result["weekly"] is True
    assert result["heartbeat"] is False
    assert alerts.heartbeat_due(conn, NOW) is False


# ------------------------------ DDIAG-4: turning a sink on re-raises what is
#                                         already open

def test_turning_the_sink_on_delivers_the_warns_that_were_already_open(
        env, monkeypatch):
    """The finding: on the vendor default every finding gets an ok=0 no-sink
    row, and that row is what `_is_open` reads. A warn is said once, so the
    day SMTP is configured every warn open since before then was already
    said and would never be sent."""
    _client, conn, settings = env
    alerts.set_settings(conn, {"alerts_weekly": "0"}, "owen")
    conn.commit()
    monkeypatch.setattr(alerts, "scan", lambda *_a, **_kw: [_warn_finding()])

    alerts.run_cycle(conn, settings, NOW)
    row = [r for r in dbmod.fetch_alerts(conn, limit=50)
           if r["kind"] == "folders_unfiltered"][0]
    assert row["ok"] == 0 and row["detail"] == alerts.NO_SINK_DETAIL

    fake = _FakeOpener()
    monkeypatch.setattr(alerts, "_webhook_opener", lambda: fake)
    _configure_webhook(conn)

    result = alerts.run_cycle(conn, settings, NOW)

    assert result["sent"] == 1
    assert len(fake.calls) == 1
    kinds = {r["kind"] for r in dbmod.fetch_alerts(conn, limit=50)}
    assert "folders_unfiltered" + alerts.UNDELIVERED_SUFFIX in kinds


def test_a_sink_change_between_two_real_sinks_re_raises_nothing(env, monkeypatch):
    _client, conn, settings = env
    _configure_webhook(conn)
    fake = _FakeOpener()
    monkeypatch.setattr(alerts, "_webhook_opener", lambda: fake)
    monkeypatch.setattr(alerts, "scan", lambda *_a, **_kw: [_warn_finding()])
    alerts.set_settings(conn, {"alerts_weekly": "0"}, "owen")
    conn.commit()
    alerts.run_cycle(conn, settings, NOW)
    assert len(fake.calls) == 1

    alerts.set_settings(conn, {"alerts_sink": alerts.SINK_WEBHOOK,
                               "alerts_webhook_url": "https://other.example/hook"},
                        "owen")
    conn.commit()
    alerts.run_cycle(conn, settings, NOW)
    assert len(fake.calls) == 1


def test_the_save_page_promises_what_the_next_check_will_do(env):
    """The one sentence an admin who has just switched mail on is waiting
    for. It is on the page, not only in the code."""
    client, conn, _settings = env
    as_admin(client)
    response = client.post("/partials/admin/alerts/save",
                           data={"alerts_sink": "webhook",
                                 "alerts_webhook_url": "https://x.example/h"})
    assert response.status_code == 200
    assert "The next check will send everything that is currently open" in \
        response.text


# ---------------------------------------------- DDIAG-3: the silence give-up

def _quiet_since(client, conn, when=NOW):
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    conn.execute(
        "UPDATE lane_report_current SET received_at=? "
        "WHERE editor_username='jsmith' AND machine='EDIT-PC'", (when,))
    conn.commit()


def test_a_day_of_silence_is_still_a_daily_alarm(env):
    client, conn, settings = env
    _quiet_since(client, conn)
    silent = [f for f in alerts.scan(conn, settings, A_DAY_LATER)
              if f["kind"] == "machine_silent"]
    assert silent and silent[0]["repeat"] is True
    assert "[ FORGET ]" in silent[0]["fix"]


def test_a_computer_gone_a_fortnight_stops_being_a_daily_mail(env, monkeypatch):
    """DDIAG-3: a retired laptop produced 21 identical emails. It stays OPEN
    on the page (dropping it would send "this has cleared, no action is
    needed" about a computer that is dead), and it stops being sent."""
    client, conn, settings = env
    _quiet_since(client, conn)
    _configure_webhook(conn)
    alerts.set_settings(conn, {"alerts_weekly": "0"}, "owen")
    conn.commit()
    fake = _FakeOpener()
    monkeypatch.setattr(alerts, "_webhook_opener", lambda: fake)

    silent = [f for f in alerts.scan(conn, settings, THREE_WEEKS_LATER)
              if f["kind"] == "machine_silent"]
    assert silent and silent[0]["repeat"] is False

    first = alerts.deliver(conn, settings, silent, THREE_WEEKS_LATER)
    assert first["sent"] == 1
    later = alerts.deliver(conn, settings, silent, "2026-09-19T12:00:00+00:00")
    assert later["sent"] == 0 and later["recovered"] == 0
    assert len(fake.calls) == 1


# ------------------------------------------------------------- wave 2 (B2)
#
# "The alarm reaches someone": the fleet job queue (DDIAG-2 / DDIAG-6), the
# release channel's own adoption (REL-3 / REL-6 / REL-13), each computer's
# yt-dlp and 8899 loopback (CYT-7 / CMEDIA-3), the /ytdl stack (YTWEB-2 /
# YTWEB-5) and the b-roll platform (BROLL-2). One quiet shape and one firing
# shape per kind, because a check that cannot fire and a check that always
# fires are the same bug from different sides.

import sqlite3 as _sqlite3
import sys as _sys
import types as _types

from ccsync_dashboard import db as _db
from ccsync_dashboard import mount_status as _mount_status


def kinds_of(findings):
    return {f["kind"] for f in findings}


def one(findings, kind):
    rows = [f for f in findings if f["kind"] == kind]
    assert rows, f"{kind} did not fire: {sorted(kinds_of(findings))}"
    return rows[0]


@pytest.fixture
def mounts():
    """The module-level mount registry, restored after the test.

    It is process-global on purpose (DDIAG-7), so a test that records a mount
    and leaves it recorded fails whichever test runs next.
    """
    before = _mount_status.snapshot()
    yield _mount_status
    _mount_status.reset()
    for name, (status, detail) in before.items():
        _mount_status.record(name, status, detail)


# ------------------------------------------------------------ the job queue

def _queue(conn, kind="whisper", hours_old=9, now=NOW):
    created = alerts._iso_minus(now, int(hours_old * 3600))
    job_id = _db.create_job(conn, kind, {"src": ["tree", "a/b.mov"]}, now=created)
    conn.commit()
    return job_id


def test_a_fresh_queue_is_not_starved(env):
    client, conn, settings = env
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    _queue(conn, hours_old=1)
    assert "jobs_starved" not in kinds_of(alerts.scan(conn, settings, NOW))


def test_work_nothing_can_take_is_starved(env):
    client, conn, settings = env
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    _queue(conn, hours_old=9)
    finding = one(alerts.scan(conn, settings, NOW), "jobs_starved")
    assert "no computer in the fleet can do this kind of work" in finding["diagnosis"]
    assert "Settings, JOBS" in finding["fix"]


def test_no_abandoned_jobs_is_quiet(env):
    _client, conn, settings = env
    _queue(conn, hours_old=1)
    assert "jobs_abandoned" not in kinds_of(alerts.scan(conn, settings, NOW))


def test_abandoned_jobs_are_reported_once_for_the_window(env):
    _client, conn, settings = env
    for _ in range(3):
        job_id = _queue(conn, hours_old=30)
        conn.execute("UPDATE jobs SET state='abandoned', last_error='no ffmpeg', "
                     "updated_at=? WHERE id=?", (NOW, job_id))
    conn.commit()
    findings = [f for f in alerts.scan(conn, settings, NOW)
                if f["kind"] == "jobs_abandoned"]
    assert len(findings) == 1
    assert "gave up on 3 job(s)" in findings[0]["diagnosis"]
    assert "[ TRY AGAIN ]" in findings[0]["fix"]


def test_a_pinned_job_with_cards_mounted_is_quiet(env, mounts):
    _client, conn, settings = env
    mounts.record("cards", "mounted", "")
    job_id = _queue(conn, kind="proxy-480p", hours_old=30)
    conn.execute("UPDATE jobs SET state='pinned' WHERE id=?", (job_id,))
    conn.commit()
    assert "jobs_pinned_no_executor" not in kinds_of(alerts.scan(conn, settings, NOW))


def test_a_pinned_job_with_no_cards_mount_is_an_error(env, mounts):
    _client, conn, settings = env
    mounts.record("cards", "absent", "the vault root is not mounted (/vault)")
    job_id = _queue(conn, kind="proxy-480p", hours_old=30)
    conn.execute("UPDATE jobs SET state='pinned' WHERE id=?", (job_id,))
    conn.commit()
    finding = one(alerts.scan(conn, settings, NOW), "jobs_pinned_no_executor")
    assert finding["severity"] == alerts.SEV_ERROR
    assert "wait for ever" in finding["diagnosis"]


def test_a_pinned_job_this_container_stopped_beating_on(env, mounts):
    _client, conn, settings = env
    mounts.record("cards", "mounted", "")
    job_id = _queue(conn, kind="peaks", hours_old=30)
    conn.execute(
        "UPDATE jobs SET state='pinned', claimed_machine=?, heartbeat_at=? "
        "WHERE id=?",
        (_db.PIN_HOLDER, alerts._iso_minus(NOW, 4 * 3600), job_id))
    conn.commit()
    finding = one(alerts.scan(conn, settings, NOW), "jobs_pinned_no_executor")
    assert "stranded" in finding["subject"]


def test_the_weekly_report_carries_the_queue(env):
    _client, conn, settings = env
    _queue(conn, hours_old=1)
    _subject, body = alerts.compose_weekly(conn, NOW, settings)
    assert "JOBS: 1 queued, 0 running, 0 abandoned this week" in body


# --------------------------------------------------------- the release channel

def guard_upgrade(**fields):
    return {"upgrade": {"version": "0.9.66", "attempts": 0, **fields}}


def test_a_computer_taking_updates_is_not_refusing(env):
    client, conn, settings = env
    client.post("/api/v1/report", json=payload(guard_upgrade()),
                headers=report_headers())
    assert "upgrade_refused" not in kinds_of(alerts.scan(conn, settings, NOW))


def test_a_refused_offer_is_stored_and_alerted(env):
    client, conn, settings = env
    client.post("/api/v1/report", json=payload(guard_upgrade(
        refused_version="0.9.67",
        refused_reason="release signature rejected",
        refused_at=NOW)), headers=report_headers())
    finding = one(alerts.scan(conn, settings, NOW), "upgrade_refused")
    assert finding["severity"] == alerts.SEV_ERROR
    assert "release signature rejected" in finding["diagnosis"]
    assert "cannot fix a refusal" in finding["fix"]


def test_a_refusal_that_stops_clears_itself(env):
    """The LATCH rule: the next guard-bearing report with no refusal in it is
    how a computer says it is not refusing any more."""
    client, conn, settings = env
    client.post("/api/v1/report", json=payload(guard_upgrade(
        refused_version="0.9.67", refused_reason="below the downgrade floor",
        refused_at=NOW)), headers=report_headers())
    client.post("/api/v1/report", json=payload(guard_upgrade()),
                headers=report_headers())
    assert "upgrade_refused" not in kinds_of(alerts.scan(conn, settings, NOW))


def publish(conn, version, platform="windows", now=NOW, current=True):
    _db.insert_companion_package(
        conn, version=version, platform=platform, filename=f"c-{version}.exe",
        sha256="0" * 64, size_bytes=1, published_by="owen", now=now)
    if current:
        _db.set_current_package(conn, platform, version, now=now)
    conn.commit()


def test_a_build_taken_by_the_fleet_is_not_stalled(env):
    client, conn, settings = env
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    publish(conn, "0.9.55", now=alerts._iso_minus(NOW, 5 * 24 * 3600))
    assert "rollout_stalled" not in kinds_of(alerts.scan(conn, settings, NOW))


def test_a_build_nobody_takes_is_stalled(env):
    client, conn, settings = env
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    publish(conn, "0.9.66", now=alerts._iso_minus(NOW, 5 * 24 * 3600))
    finding = one(alerts.scan(conn, settings, NOW), "rollout_stalled")
    assert "0 of 1 have taken it" in finding["diagnosis"]
    assert "jsmith/EDIT-PC on 0.9.55" in finding["diagnosis"]


def test_a_build_made_current_before_v48_says_nothing(env):
    """`made_current_at` NULL is "cannot tell", never "stalled for six days"."""
    client, conn, settings = env
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    publish(conn, "0.9.66", now=alerts._iso_minus(NOW, 5 * 24 * 3600))
    conn.execute("UPDATE companion_packages SET made_current_at=NULL")
    conn.commit()
    assert "rollout_stalled" not in kinds_of(alerts.scan(conn, settings, NOW))


def test_two_channels_shipped_together_are_quiet(env):
    _client, conn, settings = env
    publish(conn, "0.9.66", platform="windows", now=NOW)
    publish(conn, "0.9.66", platform="macos", now=NOW)
    assert "platform_channel_stale" not in kinds_of(alerts.scan(conn, settings, NOW))


def test_a_mac_channel_left_behind_names_the_two_commands(env):
    _client, conn, settings = env
    publish(conn, "0.9.66", platform="windows", now=NOW)
    publish(conn, "0.9.60", platform="macos",
            now=alerts._iso_minus(NOW, 30 * 24 * 3600))
    finding = one(alerts.scan(conn, settings, NOW), "platform_channel_stale")
    assert "release_macos.sh --publish --make-current" in finding["fix"]
    assert "build_onboard_macos.sh --publish --make-current" in finding["fix"]


def test_a_channel_with_no_stamps_is_measured_in_builds(env):
    _client, conn, settings = env
    for version in ("0.9.63", "0.9.64", "0.9.65", "0.9.66"):
        publish(conn, version, platform="windows", now=NOW)
    publish(conn, "0.9.62", platform="macos", now=NOW)
    conn.execute("UPDATE companion_packages SET made_current_at=NULL")
    conn.commit()
    finding = one(alerts.scan(conn, settings, NOW), "platform_channel_stale")
    assert "4 builds behind" in finding["diagnosis"]


# ----------------------------------------------- each computer's own tools

def test_a_fresh_yt_dlp_on_a_computer_is_quiet(env):
    client, conn, settings = env
    client.post("/api/v1/report", json=payload({
        "ytdlp": {"version": "2026.09.01", "action": "checked", "ok": True,
                  "stale": False, "age_days": 3, "message": None,
                  "checked_at": NOW}}), headers=report_headers())
    kinds = kinds_of(alerts.scan(conn, settings, NOW))
    assert "ytdlp_stale" not in kinds and "ytdlp_failed" not in kinds


def test_a_stale_yt_dlp_uses_the_computers_own_message(env):
    client, conn, settings = env
    client.post("/api/v1/report", json=payload({
        "ytdlp": {"version": "2026.07.04", "action": "stale", "ok": True,
                  "stale": True, "age_days": 43,
                  "message": "yt-dlp 2026.07.04 is 43 days old and it could "
                             "not update itself",
                  "checked_at": NOW}}), headers=report_headers())
    finding = one(alerts.scan(conn, settings, NOW), "ytdlp_stale")
    assert "43 days old" in finding["diagnosis"]
    assert finding["severity"] == alerts.SEV_WARN


def test_a_computer_with_no_usable_yt_dlp_is_an_error(env):
    client, conn, settings = env
    client.post("/api/v1/report", json=payload({
        "ytdlp": {"version": None, "action": "failed", "ok": False,
                  "stale": False, "age_days": None,
                  "message": "the download tool could not be installed",
                  "checked_at": NOW}}), headers=report_headers())
    finding = one(alerts.scan(conn, settings, NOW), "ytdlp_failed")
    assert finding["severity"] == alerts.SEV_ERROR


def test_a_computer_that_stops_sending_a_verdict_stops_alarming(env):
    """An ABSENT section deletes the stored verdict: a companion that has
    stopped saying has stopped knowing, and March's "43 days old" is worse
    than silence."""
    client, conn, settings = env
    client.post("/api/v1/report", json=payload({
        "ytdlp": {"action": "stale", "stale": True, "age_days": 43}}),
        headers=report_headers())
    client.post("/api/v1/report", json=payload({}), headers=report_headers())
    assert "ytdlp_stale" not in kinds_of(alerts.scan(conn, settings, NOW))


def test_a_held_loopback_port_is_reported(env):
    client, conn, settings = env
    client.post("/api/v1/report", json=payload({
        "loopback": {"enabled": True, "bound": False, "port": 8899,
                     "error": "port 8899 is in use", "since": NOW}}),
        headers=report_headers())
    finding = one(alerts.scan(conn, settings, NOW), "loopback_down")
    assert "8899" in finding["fix"]


def test_a_bound_loopback_and_a_switched_off_one_are_both_quiet(env):
    client, conn, settings = env
    client.post("/api/v1/report", json=payload({
        "loopback": {"enabled": True, "bound": True, "port": 8899,
                     "error": "", "since": ""}}), headers=report_headers())
    assert "loopback_down" not in kinds_of(alerts.scan(conn, settings, NOW))
    client.post("/api/v1/report", json=payload({
        "loopback": {"enabled": False, "bound": False, "port": 8899,
                     "error": "", "since": ""}}), headers=report_headers())
    assert "loopback_down" not in kinds_of(alerts.scan(conn, settings, NOW))


# --------------------------------------------------------- the YouTube stack

HEALTHY_YTDL = {
    "worker_alive": True, "yt_dlp_stale": False, "yt_dlp_age_days": 2,
    "yt_dlp_version": "2026.09.01", "pot_provider": "unconfigured",
    "cookies_state": "anonymous",
    "last_download": {"ok": True, "path": "anonymous", "error": ""},
    "canary": {"enabled": True, "last": {"ok": True}},
    "plugin_install": {"ok": True, "state": "ok", "error": "", "at": NOW,
                       "attempts": 1, "version": "1.3.1"},
}


def ytdl_health(monkeypatch, **overrides):
    snap = dict(HEALTHY_YTDL)
    snap.update(overrides)
    monkeypatch.setattr(alerts, "_ytdl_health", lambda mounts: snap)
    return snap


def test_a_healthy_ytdl_stack_raises_nothing(env, monkeypatch):
    _client, conn, settings = env
    ytdl_health(monkeypatch)
    kinds = kinds_of(alerts.scan(conn, settings, NOW))
    assert not {k for k in kinds if k.startswith("ytdl_")}


def test_an_absent_ytdl_mount_raises_nothing(env, monkeypatch):
    """None is "we could not ask", and it must not become a green or a red."""
    _client, conn, settings = env
    monkeypatch.setattr(alerts, "_ytdl_health", lambda mounts: None)
    kinds = kinds_of(alerts.scan(conn, settings, NOW))
    assert not {k for k in kinds if k.startswith("ytdl_")}
    assert alerts.CHECK_FAILED.kind not in kinds


def test_a_dead_download_worker_is_an_error(env, monkeypatch):
    _client, conn, settings = env
    ytdl_health(monkeypatch, worker_alive=False)
    assert one(alerts.scan(conn, settings, NOW),
               "ytdl_worker_dead")["severity"] == alerts.SEV_ERROR


def test_one_bad_video_is_not_a_broken_downloader(env, monkeypatch):
    _client, conn, settings = env
    ytdl_health(monkeypatch,
                last_download={"ok": False, "path": "anonymous", "error": "403"},
                canary={"enabled": True, "last": {"ok": True}})
    assert "ytdl_downloads_failing" not in kinds_of(alerts.scan(conn, settings, NOW))


def test_a_failed_download_and_a_failed_canary_is_a_finding(env, monkeypatch):
    _client, conn, settings = env
    ytdl_health(monkeypatch,
                last_download={"ok": False, "path": "anonymous", "error": "403"},
                canary={"enabled": True, "last": {"ok": False}})
    assert one(alerts.scan(conn, settings, NOW), "ytdl_downloads_failing")


def test_an_unconfigured_pot_provider_is_not_a_problem(env, monkeypatch):
    _client, conn, settings = env
    ytdl_health(monkeypatch, pot_provider="unconfigured")
    assert "ytdl_pot_provider_unreachable" not in kinds_of(
        alerts.scan(conn, settings, NOW))


def test_a_configured_pot_provider_that_stopped_answering_is(env, monkeypatch):
    _client, conn, settings = env
    ytdl_health(monkeypatch, pot_provider="unreachable")
    assert one(alerts.scan(conn, settings, NOW), "ytdl_pot_provider_unreachable")


def test_an_anonymous_cookie_jar_is_the_healthy_state(env, monkeypatch):
    """CR-80 inverted the 2026-08-11 rule: signed-in cookies are the CAUSE
    now, so nothing here may alarm on `anonymous`."""
    _client, conn, settings = env
    ytdl_health(monkeypatch, cookies_state="anonymous")
    assert not {k for k in kinds_of(alerts.scan(conn, settings, NOW))
                if k.startswith("ytdl_")}


def test_a_failed_plugin_install_names_its_error(env, monkeypatch):
    _client, conn, settings = env
    ytdl_health(monkeypatch, plugin_install={
        "ok": False, "state": "failed", "error": "[Errno 13] /venv is read-only",
        "at": NOW, "attempts": 3, "version": ""})
    finding = one(alerts.scan(conn, settings, NOW), "ytdl_plugin_install_failed")
    assert "3 attempt(s)" in finding["diagnosis"]
    assert "Errno 13" in finding["detail"]


def test_a_plugin_install_nobody_recorded_is_not_a_failure(env, monkeypatch):
    _client, conn, settings = env
    ytdl_health(monkeypatch, plugin_install={"ok": None, "state": "unknown",
                                             "error": "", "at": "",
                                             "attempts": 0, "version": ""})
    assert "ytdl_plugin_install_failed" not in kinds_of(
        alerts.scan(conn, settings, NOW))


def test_this_servers_stale_yt_dlp_is_a_finding(env, monkeypatch):
    _client, conn, settings = env
    ytdl_health(monkeypatch, yt_dlp_stale=True, yt_dlp_age_days=61)
    assert "61 days old" in one(alerts.scan(conn, settings, NOW),
                                "ytdl_stale")["diagnosis"]


def test_the_ytdl_seam_reads_the_mount_registry(env, mounts, monkeypatch):
    """`_ytdl_health` has no app object: it takes the status from
    mount_status and hands ytdl.health_snapshot a stand-in carrying it."""
    _client, conn, _settings = env
    mounts.reset()
    assert alerts._ytdl_health(mounts.snapshot()) is None
    fake = _types.ModuleType("ytdlweb.routes_api")
    fake.health_snapshot = lambda app, allow_probe=True: {"worker_alive": True}
    monkeypatch.setitem(_sys.modules, "ytdlweb.routes_api", fake)
    mounts.record("ytdl", "mounted", "")
    assert alerts._ytdl_health(mounts.snapshot()) == {"worker_alive": True}


# ------------------------------------------------------------------- b-roll

def _broll_dbs(tmp_path, batches=(), shares=()):
    index = tmp_path / "broll.db"
    conn = _sqlite3.connect(index)
    conn.execute("CREATE TABLE ingest_batches (uid TEXT, editor TEXT, "
                 "machine TEXT, share TEXT, state TEXT, n_items INT, "
                 "n_done INT, created_at TEXT, last_heartbeat_at TEXT)")
    conn.executemany("INSERT INTO ingest_batches VALUES (?,?,?,?,?,?,?,?,?)",
                     batches)
    conn.commit()
    conn.close()
    ledger = tmp_path / "client_shares.db"
    conn = _sqlite3.connect(ledger)
    conn.execute("CREATE TABLE client_folders (id INT, title TEXT, "
                 "expires_at TEXT, revoked_at TEXT)")
    conn.executemany("INSERT INTO client_folders VALUES (?,?,?,?)", shares)
    conn.commit()
    conn.close()
    return index, ledger


def test_broll_checks_are_silent_when_broll_is_not_mounted(env, mounts,
                                                           monkeypatch, tmp_path):
    _client, conn, settings = env
    mounts.reset()
    paths = _broll_dbs(tmp_path, batches=[
        ("u1", "jsmith", "EDIT-PC", "FF5", "running", 40, 2,
         "2026-08-01T00:00:00+00:00", "2026-08-01T00:00:00+00:00")])
    monkeypatch.setattr(alerts, "_broll_paths", lambda: paths)
    kinds = kinds_of(alerts.scan(conn, settings, NOW))
    assert "broll_batch_stuck" not in kinds


def test_a_moving_batch_is_not_stuck(env, mounts, monkeypatch, tmp_path):
    _client, conn, settings = env
    mounts.record("broll", "mounted", "")
    paths = _broll_dbs(tmp_path, batches=[
        ("u1", "jsmith", "EDIT-PC", "FF5", "running", 40, 2, NOW, NOW)])
    monkeypatch.setattr(alerts, "_broll_paths", lambda: paths)
    assert "broll_batch_stuck" not in kinds_of(alerts.scan(conn, settings, NOW))


def test_a_batch_with_no_heartbeat_for_a_day_is_stuck(env, mounts,
                                                      monkeypatch, tmp_path):
    _client, conn, settings = env
    mounts.record("broll", "mounted", "")
    old = alerts._iso_minus(NOW, 3 * 24 * 3600)
    paths = _broll_dbs(tmp_path, batches=[
        ("u1", "jsmith", "EDIT-PC", "FF5", "running", 40, 2, old, old)])
    monkeypatch.setattr(alerts, "_broll_paths", lambda: paths)
    finding = one(alerts.scan(conn, settings, NOW), "broll_batch_stuck")
    assert "FF5" in finding["subject"]
    assert "2 of 40" in finding["diagnosis"]


def test_a_client_link_with_months_left_is_quiet(env, mounts, monkeypatch,
                                                 tmp_path):
    _client, conn, settings = env
    mounts.record("broll", "mounted", "")
    paths = _broll_dbs(tmp_path, shares=[
        (1, "Acme cut 3", "2026-12-01T00:00:00+00:00", None)])
    monkeypatch.setattr(alerts, "_broll_paths", lambda: paths)
    assert "broll_share_expiring" not in kinds_of(alerts.scan(conn, settings, NOW))


def test_a_client_link_expiring_this_week_is_reported(env, mounts, monkeypatch,
                                                      tmp_path):
    _client, conn, settings = env
    mounts.record("broll", "mounted", "")
    soon = alerts._iso_minus(NOW, -3 * 24 * 3600)
    paths = _broll_dbs(tmp_path, shares=[(1, "Acme cut 3", soon, None),
                                         (2, "Revoked one", soon, NOW)])
    monkeypatch.setattr(alerts, "_broll_paths", lambda: paths)
    findings = [f for f in alerts.scan(conn, settings, NOW)
                if f["kind"] == "broll_share_expiring"]
    assert len(findings) == 1
    assert "Acme cut 3" in findings[0]["subject"]


def test_every_new_kind_is_in_the_registry_and_the_weekly_list(env):
    """Adding a check is adding a registry row: the dedup, the recovery
    message, the page and the report's "checked and found nothing wrong" list
    all come from it, so a kind that is only a function is a kind nobody is
    told about."""
    _client, conn, settings = env
    registered = {k.kind for k in alerts.ALERT_KINDS}
    for kind in ("jobs_starved", "jobs_abandoned", "jobs_pinned_no_executor",
                 "upgrade_refused", "rollout_stalled", "platform_channel_stale",
                 "ytdlp_stale", "ytdlp_failed", "loopback_down",
                 "ytdl_worker_dead", "ytdl_downloads_failing",
                 "ytdl_pot_provider_unreachable", "ytdl_plugin_install_failed",
                 "ytdl_stale", "broll_batch_stuck", "broll_share_expiring"):
        assert kind in registered, kind
    _subject, body = alerts.compose_weekly(conn, NOW, settings)
    assert "the fleet job queue" in body
    assert "computers refusing the offer outright" in body
