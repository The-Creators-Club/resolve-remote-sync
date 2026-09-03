"""Usability + resilience sweep 2026-09-04, wave 1 (dashboard core).

One file, one section per finding, each pinning the PROPERTY rather than the
wording:

* DDIAG-1  a pass of alerts has a delivery budget it cannot run past, and a
           budget it spent is itself a notice.
* DDIAG-16 the panel says out loud when nobody is being told, and a pass with
           no sink stops reading as a broken mail server.
* SYS-2    a build the vendor offers and this dashboard is too old to publish
           becomes a notice, and "how far behind is the fleet" is measured
           against the vendor's channel rather than against this dashboard's
           own shelf.
* DCORE-3  a generated secret that could not be persisted refuses the boot
           instead of working until the next restart.
"""

from __future__ import annotations

import types

import pytest

from ccsync_dashboard import alerts
from ccsync_dashboard import app as appmod
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import protection
from ccsync_dashboard import release_feed
from ccsync_dashboard.settings import Settings

NOW = "2026-09-04T12:00:00+00:00"
LATER = "2026-09-04T12:20:00+00:00"


def _settings(**kw) -> Settings:
    return Settings(session_secret="test-secret-that-is-long-enough", **kw)


def _deployment():
    """A real deployment's settings: DASH_DEV_INSECURE is never set on one.
    This suite's conftest sets it at import time and `Settings` adopts it, so
    a plain Settings() here would test the bypass rather than the refusal."""
    return types.SimpleNamespace(dev_insecure=False)


def _finding(kind: str, subject: str, severity: str = alerts.SEV_ERROR) -> dict:
    return {"kind": kind, "subject": subject, "severity": severity,
            "diagnosis": "something is wrong", "fix": "do the thing",
            "detail": ""}


class _Clock:
    """A monotonic clock that only moves when a send happens, so a test can
    spend a two-minute budget without waiting two minutes."""

    def __init__(self, step: float = 20.0) -> None:
        self.now = 0.0
        self.step = step
        self.sends = 0

    def __call__(self) -> float:
        return self.now

    def spend(self) -> None:
        self.sends += 1
        self.now += self.step


@pytest.fixture
def sink_webhook(conn):
    """A configured sink, so `send()` takes its delivery path at all."""
    alerts.set_settings(conn, {"alerts_sink": alerts.SINK_WEBHOOK,
                               "alerts_webhook_url": "https://example.invalid/hook"},
                        "owen")
    conn.commit()
    return conn


# ------------------------------------------------------------------ DDIAG-1

def test_a_hanging_sink_cannot_take_a_pass_past_the_wedged_threshold(
        conn, sink_webhook, monkeypatch):
    """The finding: 46 findings x a 20 s hang = 920 s, past
    app.WATCHDOG_WEDGED_SECONDS (900 s), so the watchdog replaces the
    container every cycle for ever. The pass must stop first."""
    clock = _Clock(step=alerts.SEND_TIMEOUT_SECONDS)

    def slow_send(_conn, _settings, *_a, **kw):
        clock.spend()
        dbmod.record_alert(_conn, kw.get("kind", "x"), kw.get("dedup_subject", ""),
                           "", False, "timed out", NOW)
        return {"ok": False, "sink": alerts.SINK_WEBHOOK, "sent_to": "",
                "detail": "timed out", "deduped": False}

    monkeypatch.setattr(alerts, "_send_committed", slow_send)
    findings = [_finding("machine_silent", f"editor{i}/PC{i}") for i in range(46)]

    result = alerts.deliver(conn, _settings(), findings, NOW, clock=clock)

    assert clock.now <= alerts.ALERT_CYCLE_BUDGET_SECONDS + alerts.SEND_TIMEOUT_SECONDS
    assert clock.now < appmod.WATCHDOG_WEDGED_SECONDS
    assert result["undelivered"] > 0
    assert clock.sends + result["undelivered"] == len(findings)


def test_what_the_budget_left_is_offered_again_next_pass(conn, sink_webhook,
                                                         monkeypatch):
    """An undelivered alert must leave NO alert_log row: the row is what
    "somebody was told" means, and dedup reads any row."""
    clock = _Clock(step=1000.0)
    monkeypatch.setattr(
        alerts, "_send_committed",
        lambda *_a, **_kw: (clock.spend(), {"ok": True, "sink": alerts.SINK_WEBHOOK,
                                            "sent_to": "x", "detail": "sent",
                                            "deduped": False})[1])
    findings = [_finding("machine_silent", "a/PC"), _finding("machine_silent", "b/PC")]

    first = alerts.deliver(conn, _settings(), findings, NOW, clock=clock)
    assert first["undelivered"] == 1
    assert dbmod.last_alert_at(conn, "machine_silent", "b/PC", ok_only=False) is None

    clock.now = 0.0
    second = alerts.deliver(conn, _settings(), findings, NOW, clock=_Clock())
    assert second["undelivered"] == 0


def test_a_spent_budget_is_a_notice_with_its_fix(conn, sink_webhook, monkeypatch):
    monkeypatch.setattr(alerts, "scan",
                        lambda *_a, **_kw: [_finding("machine_silent", "a/PC"),
                                            _finding("machine_silent", "b/PC")])
    monkeypatch.setattr(alerts, "ALERT_CYCLE_BUDGET_SECONDS", 0.0)

    result = alerts.run_cycle(conn, _settings(), NOW)

    assert result["undelivered"] == 2
    assert "sent this pass" in (result["note"] or "")
    rows = [r for r in dbmod.open_notices(conn)
            if r["kind"] == "alerts_delivery_slow"]
    assert rows and rows[0]["fix"]


def test_the_budget_notice_closes_when_the_sink_speeds_up(conn, sink_webhook,
                                                          monkeypatch):
    monkeypatch.setattr(alerts, "scan",
                        lambda *_a, **_kw: [_finding("machine_silent", "a/PC")])
    monkeypatch.setattr(alerts, "ALERT_CYCLE_BUDGET_SECONDS", 0.0)
    alerts.run_cycle(conn, _settings(), NOW)
    assert any(r["kind"] == "alerts_delivery_slow" for r in dbmod.open_notices(conn))

    monkeypatch.setattr(alerts, "ALERT_CYCLE_BUDGET_SECONDS", 120.0)
    monkeypatch.setattr(alerts, "_send_committed",
                        lambda *_a, **_kw: {"ok": True, "sink": alerts.SINK_WEBHOOK,
                                            "sent_to": "x", "detail": "sent",
                                            "deduped": False})
    alerts.run_cycle(conn, _settings(), LATER)

    assert not any(r["kind"] == "alerts_delivery_slow" for r in dbmod.open_notices(conn))
    # ... and the kind is provably CHECKED, not merely quiet.
    assert "alerts_delivery_slow" in dbmod.notice_check_times(conn)


def test_the_registered_kinds_all_have_a_writer_in_this_wave(conn, monkeypatch):
    """The 08-28 lesson: a kind in NOTICE_KINDS with no writer ticks [ OK ]
    for ever. Both kinds this wave adds are stamped by a pass that found
    nothing wrong."""
    monkeypatch.setattr(alerts, "scan", lambda *_a, **_kw: [])
    alerts.run_cycle(conn, _settings(), NOW)
    release_feed.record_offer_state(conn, [], NOW)
    checked = dbmod.notice_check_times(conn)
    assert "alerts_delivery_slow" in checked
    assert "feed_publish_refused" in checked
    for kind in ("alerts_delivery_slow", "feed_publish_refused"):
        assert kind in dbmod.NOTICE_KINDS


# ----------------------------------------------------------------- DDIAG-16

def test_no_sink_is_a_protection_line_that_says_nobody_is_told(conn):
    row = protection._check_alerts_sink(
        protection.Ctx(conn, _settings(), NOW, tasks_fn=lambda: None, env={}))
    assert row.state == protection.BROKEN
    assert "nobody is told" in row.detail
    assert protection.BY_KEY["alerts_sink"].severity == "warn"


def test_a_sink_that_has_delivered_nothing_for_a_month_is_the_same_hole(
        conn, sink_webhook):
    ctx = protection.Ctx(conn, _settings(), NOW, tasks_fn=lambda: None, env={})
    assert protection._check_alerts_sink(ctx).state == protection.BROKEN

    dbmod.record_alert(conn, alerts.KIND_WEEKLY, "weekly", "webhook", True, "sent",
                       "2026-06-01T12:00:00+00:00")
    conn.commit()
    assert protection._check_alerts_sink(ctx).state == protection.BROKEN

    dbmod.record_alert(conn, alerts.KIND_WEEKLY, "weekly", "webhook", True, "sent",
                       "2026-09-03T12:00:00+00:00")
    conn.commit()
    assert protection._check_alerts_sink(ctx).state == protection.OK


def test_the_weekly_report_carries_the_alarm_is_off_line(conn):
    protection.run_cycle(conn, _settings(), NOW, tasks_fn=lambda: None)
    text = "\n".join(protection.weekly_lines(conn))
    assert "somebody is told when this breaks" in text


def test_a_pass_with_no_sink_does_not_read_as_a_broken_mail_server(
        conn, monkeypatch):
    monkeypatch.setattr(alerts, "scan",
                        lambda *_a, **_kw: [_finding("machine_silent", "a/PC")])
    result = alerts.run_cycle(conn, _settings(), NOW)
    note = result["note"] or ""
    assert result["failed"] == 1
    assert "could not be delivered" not in note
    assert "nobody was told" in note


def test_no_em_dash_in_what_this_wave_puts_in_front_of_a_person(conn):
    """The owner's rule, for the strings this wave adds."""
    strings = [protection.BY_KEY["alerts_sink"].consequence,
               protection.BY_KEY["alerts_sink"].fix,
               protection.BY_KEY["alerts_sink"].title,
               dbmod.NOTICE_KINDS["feed_publish_refused"]["what"],
               dbmod.NOTICE_KINDS["alerts_delivery_slow"]["what"]]
    assert not any("—" in s for s in strings)


# -------------------------------------------------------------------- SYS-2

def _companion_record(version: str, requires: str = "") -> dict:
    record = {"kind": "companion", "platform": "windows", "version": version,
              "filename": f"ccsync-{version}.exe", "sha256": "0" * 64,
              "size_bytes": 1, "url": "https://example.invalid/x"}
    if requires:
        record["requires_dashboard"] = requires
    return record


def test_a_build_this_dashboard_is_too_old_to_publish_becomes_a_notice(conn):
    refused = release_feed.record_offer_state(
        conn, [_companion_record("9.9.9", requires="99.0.0")], NOW)

    assert refused == ["companion/windows 9.9.9"]
    rows = [r for r in dbmod.open_notices(conn) if r["kind"] == "feed_publish_refused"]
    assert len(rows) == 1
    assert "99.0.0" in rows[0]["body"]
    assert rows[0]["severity"] == "error"
    assert "PACKAGES" in rows[0]["fix"]


def test_the_refusal_notice_closes_once_the_dashboard_can_publish_it(conn):
    release_feed.record_offer_state(
        conn, [_companion_record("9.9.9", requires="99.0.0")], NOW)
    release_feed.record_offer_state(conn, [_companion_record("9.9.9")], LATER)
    assert not [r for r in dbmod.open_notices(conn)
                if r["kind"] == "feed_publish_refused"]


def test_what_the_vendor_offers_survives_a_dashboard_that_refuses_to_publish(conn):
    """The half that made this invisible: with nothing published here, every
    machine measured as 0 releases behind while the fleet had stopped
    updating."""
    class _Ctx:
        def __init__(self, connection):
            self.conn = connection
            self.now = NOW
            self.editors = [{"editor_username": "jsmith", "machine": "PC",
                             "companion_version": "0.9.60", "platform": "windows",
                             "current_companion_version": "0.9.60"}]

        def name(self, subject):
            return subject

    ctx = _Ctx(conn)
    assert alerts._check_versions_behind(ctx) == []

    release_feed.record_offer_state(
        conn, [_companion_record("0.9.61", requires="99.0.0"),
               _companion_record("0.9.62", requires="99.0.0"),
               _companion_record("0.9.63", requires="99.0.0")], NOW)

    findings = alerts._check_versions_behind(ctx)
    assert len(findings) == 1
    assert "3 releases behind" in findings[0]["diagnosis"]


def test_an_unread_feed_means_unknown_and_never_up_to_date(conn):
    assert dbmod.get_feed_offered(conn) == {}


# ------------------------------------------------------------------ DCORE-3

def test_a_generated_secret_that_never_reached_the_disk_refuses_the_boot(
        tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "dashboard.db"))
    lost = appmod.check_persisted_secrets({"DASH_SESSION_SECRET": "generated"})
    assert lost == ["DASH_SESSION_SECRET"]

    with pytest.raises(RuntimeError) as excinfo:
        appmod._refuse_ephemeral_secrets({"DASH_SESSION_SECRET": "generated"},
                                         _deployment())
    message = str(excinfo.value)
    assert "DASH_SESSION_SECRET" in message
    assert "signed out" in message
    assert "—" not in message


def test_a_secret_that_was_written_or_came_from_the_environment_boots(
        tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "dashboard.db"))
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "dash_session_secret").write_text("x", encoding="utf-8")
    provenance = {"DASH_SESSION_SECRET": "generated",
                  "DASH_REPORT_TOKEN": "env",
                  "BROLL_INGEST_TOKEN": "file"}
    assert appmod.check_persisted_secrets(provenance) == []
    appmod._refuse_ephemeral_secrets(provenance, _deployment())


def test_the_dev_hatch_is_the_only_bypass_and_says_so(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "dashboard.db"))
    with caplog.at_level("WARNING"):
        appmod._refuse_ephemeral_secrets({"DASH_SESSION_SECRET": "generated"},
                                         types.SimpleNamespace(dev_insecure=True))
    assert any("bypassed a boot refusal" in r.message for r in caplog.records)
