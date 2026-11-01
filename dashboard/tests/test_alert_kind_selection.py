"""Choosing which kinds of alert are sent (2026-09-29).

The owner asked to pick which kinds of alert reach the admin. Pins: every
registry kind has a switch (KIND_GROUPS covers the registry exactly), a
switched-off kind sends nothing and writes no ledger row but is still found
by the scan, a switched-off kind's open row closes WITHOUT a "cleared"
message, switching it back on sends a still-true condition as new, a
check_failed about a switched-off kind is withheld too, the weekly report
names what is off, and the page form round-trips as a browser posts it.
"""
from __future__ import annotations

import urllib.parse

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import alerts, auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings
from test_cc_settings_review_fixes import _form_values, _hx

SECRET = "test-secret-value-alert-kinds-1234567890"
NOW = "2026-09-29T12:00:00+00:00"
# Inside the fleet halt's 24 h expiry, so the halt is still true at LATER.
LATER = "2026-09-29T13:00:00+00:00"


@pytest.fixture
def env(tmp_path):
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}))
    with TestClient(create_app(settings)) as c:
        c.app.state.collector.stop()
        conn = dbmod.connect(settings.db_path)
        conn.execute("DELETE FROM alert_log")
        conn.commit()
        c.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        try:
            yield c, conn, c.app.state.settings
        finally:
            conn.close()


class _Opener:
    def __init__(self):
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append(request)

        class _R:
            status = 200

            def read(self, *_a, **_k):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False
        return _R()


@pytest.fixture
def webhook(env, monkeypatch):
    _c, conn, _s = env
    alerts.set_settings(conn, {"alerts_sink": "webhook",
                               "alerts_webhook_url": "https://hook.example.test/x"},
                        "owen")
    conn.commit()
    opener = _Opener()
    monkeypatch.setattr(alerts, "_webhook_opener", lambda: opener)
    return opener


def _rows(conn, kind):
    return [r for r in dbmod.fetch_alerts(conn, limit=500) if r["kind"] == kind]


def _halt(conn, on, now):
    dbmod.set_fleet_halt(conn, on, "restoring the pool", "owen", now=now)
    conn.commit()


def test_every_registry_kind_is_in_exactly_one_group():
    grouped = [k for _name, kinds in alerts.KIND_GROUPS for k in kinds]
    assert len(grouped) == len(set(grouped)), "a kind is in two groups"
    assert set(grouped) == {k.kind for k in alerts.ALERT_KINDS}, \
        set(grouped) ^ {k.kind for k in alerts.ALERT_KINDS}


def test_nothing_is_muted_by_default(env):
    _c, conn, _s = env
    assert alerts.muted_kinds(conn) == frozenset()
    assert all(k["send"] for g in alerts.kind_groups_view(conn) for k in g["kinds"])


def test_an_unknown_kind_is_refused_and_nothing_is_written(env):
    _c, conn, _s = env
    with pytest.raises(alerts.AlertError):
        alerts.set_muted_kinds(conn, ["fleet_halt", "no_such_kind"], "owen")
    assert alerts.muted_kinds(conn) == frozenset()


def test_a_muted_kind_is_still_found_but_not_sent(env, webhook):
    _c, conn, settings = env
    alerts.set_muted_kinds(conn, ["fleet_halt"], "owen")
    _halt(conn, True, NOW)
    findings = alerts.scan(conn, settings, NOW)
    assert any(f["kind"] == "fleet_halt" for f in findings)
    alerts.deliver(conn, settings, findings, NOW)
    assert _rows(conn, "fleet_halt") == []
    assert not any(b"halt" in (r.data or b"").lower() for r in webhook.calls)


def test_muting_an_open_kind_closes_it_without_a_cleared_message(env, webhook):
    _c, conn, settings = env
    _halt(conn, True, NOW)
    alerts.deliver(conn, settings, alerts.scan(conn, settings, NOW), NOW)
    assert len(_rows(conn, "fleet_halt")) == 1
    sent_before = len(webhook.calls)

    alerts.set_muted_kinds(conn, ["fleet_halt"], "owen")
    _halt(conn, False, LATER)
    alerts.deliver(conn, settings, alerts.scan(conn, settings, LATER), LATER)
    closed = _rows(conn, "fleet_halt.ok")
    assert len(closed) == 1
    assert closed[0]["sent_to"] == "" and "switched off" in closed[0]["detail"]
    assert not any(b"cleared" in (r.data or b"").lower()
                   for r in webhook.calls[sent_before:])

    # Switched back on later: no stale "cleared" is owed.
    alerts.set_muted_kinds(conn, [], "owen")
    alerts.deliver(conn, settings, alerts.scan(conn, settings, LATER), LATER)
    assert len(_rows(conn, "fleet_halt.ok")) == 1


def test_switching_back_on_sends_a_still_true_condition_as_new(env, webhook):
    _c, conn, settings = env
    alerts.set_muted_kinds(conn, ["fleet_halt"], "owen")
    _halt(conn, True, NOW)
    alerts.deliver(conn, settings, alerts.scan(conn, settings, NOW), NOW)
    assert _rows(conn, "fleet_halt") == []

    alerts.set_muted_kinds(conn, [], "owen")
    alerts.deliver(conn, settings, alerts.scan(conn, settings, LATER), LATER)
    rows = _rows(conn, "fleet_halt")
    assert len(rows) == 1 and rows[0]["ok"]


def test_a_failed_check_of_a_muted_kind_is_withheld(env, webhook):
    _c, conn, settings = env
    alerts.set_muted_kinds(conn, ["fleet_halt"], "owen")
    failed = [{"kind": alerts.CHECK_FAILED.kind, "subject": "fleet_halt",
               "severity": alerts.SEV_ERROR, "title": "a health check could not run",
               "diagnosis": "boom", "fix": "", "detail": ""},
              {"kind": alerts.CHECK_FAILED.kind, "subject": "disk_low",
               "severity": alerts.SEV_ERROR, "title": "a health check could not run",
               "diagnosis": "boom", "fix": "", "detail": ""}]
    alerts.deliver(conn, settings, failed, NOW)
    subjects = {r["subject"] for r in _rows(conn, alerts.CHECK_FAILED.kind)}
    assert subjects == {"disk_low"}


def test_the_weekly_report_names_what_is_switched_off(env):
    _c, conn, settings = env
    _subject, text = alerts.compose_weekly(conn, NOW, settings)
    assert "NOT SENT AS ALERTS" not in text
    alerts.set_muted_kinds(conn, ["fleet_halt"], "owen")
    _subject, text = alerts.compose_weekly(conn, NOW, settings)
    assert "NOT SENT AS ALERTS (1" in text
    assert f"off - {alerts.KIND_BY_NAME['fleet_halt'].what}" in text


# ------------------------------------------------------------------ the page

def test_the_rendered_form_posts_back_unchanged(env):
    client, conn, _s = env
    html = client.get("/admin/alerts").text
    pairs = _form_values(html, "alerts-kinds-form")
    assert {v for k, v in pairs if k == "send"} == {k.kind for k in alerts.ALERT_KINDS}
    r = client.post("/partials/admin/alerts/kinds",
                    content=urllib.parse.urlencode(pairs),
                    headers={**_hx(client, "/admin/alerts"),
                             "Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200, r.text[:300]
    assert "saved." in r.text
    assert alerts.muted_kinds(conn) == frozenset()


def test_unticking_a_kind_mutes_it_and_the_page_shows_it_unticked(env):
    client, conn, _s = env
    html = client.get("/admin/alerts").text
    pairs = [(k, v) for k, v in _form_values(html, "alerts-kinds-form")
             if not (k == "send" and v == "crashes")]
    r = client.post("/partials/admin/alerts/kinds",
                    content=urllib.parse.urlencode(pairs),
                    headers={**_hx(client, "/admin/alerts"),
                             "Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200, r.text[:300]
    assert alerts.muted_kinds(conn) == frozenset({"crashes"})
    after = _form_values(r.text, "alerts-kinds-form")
    assert ("send", "crashes") not in after
    assert ("send", "disk_low") in after
    assert any(row["action"] == "alerts.kinds"
               for row in dbmod.fetch_audit(conn, limit=20))


@pytest.mark.parametrize("preset,expect_on", [
    ("errors", {k.kind for k in alerts.ALERT_KINDS if k.severity == alerts.SEV_ERROR}),
    ("none", set()),
    ("all", {k.kind for k in alerts.ALERT_KINDS}),
])
def test_the_presets(env, preset, expect_on):
    client, conn, _s = env
    r = client.post("/partials/admin/alerts/kinds",
                    content=urllib.parse.urlencode([("preset", preset)]),
                    headers={**_hx(client, "/admin/alerts"),
                             "Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200, r.text[:300]
    on = {k.kind for k in alerts.ALERT_KINDS} - alerts.muted_kinds(conn)
    assert on == expect_on
