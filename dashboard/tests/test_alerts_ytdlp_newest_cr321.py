"""CR-321 (2026-09-24): `ytdlp_stale` must not fire on the newest release.

The companion marked its yt-dlp stale by age alone, so on 2026-09-24 three
computers (alex/Creator_1, alex/Razer, ruskin/DESKTOP-LQQ41TC) raised "out of
date and could not update itself" on 2026.08.19, which was the newest yt-dlp
there was. These pin the dashboard half: the structured `latest` field when a
companion sends it, and for the records already in the field, "this version
is the newest anyone here knows of AND the computer's own message says so".
A genuinely stale one (something newer exists and the update failed) still
fires, and a false alarm that stops being raised is recovered by `deliver`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import alerts
from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"
NOW = "2026-09-24T09:00:00+00:00"

# The three live records, as the owner's dashboard holds them.
NEWEST_BUT_OLD = {
    "action": "stale", "age_days": 36, "stale": True, "ok": True,
    "version": "2026.08.19",
    "message": ("yt-dlp 2026.08.19 is 36 days old and it is already the newest "
                "release -- nothing newer to take"),
    "checked_at": NOW,
}
LIVE_MACHINES = (("alex", "Creator_1"), ("alex", "Razer"),
                 ("ruskin", "DESKTOP-LQQ41TC"))


def _headers(editor):
    return {"X-CCSync-Token": "sekrit",
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def _report(client, editor, machine, ytdlp):
    body = {
        "editor_name": editor, "machine": machine, "companion_version": "0.9.76",
        "reported_at": NOW,
        "lanes": [{"name": "lane_b_proxy_down", "state": "idle", "queued": 0,
                   "transferring": 0, "last_error": None, "last_sync": None}],
        "sync_guard": {"ytdlp": ytdlp},
    }
    resp = client.post("/api/v1/report", json=body, headers=_headers(editor))
    assert resp.status_code == 200, resp.text


def _stale_subjects(conn, settings):
    return {f["subject"] for f in alerts.scan(conn, settings, NOW)
            if f["kind"] == "ytdlp_stale"}


@pytest.fixture
def env(tmp_path):
    app = create_app(Settings(
        db_path=str(tmp_path / "dash.db"), report_token="sekrit",
        session_secret=SECRET, admin_users=frozenset({"owen"}),
    ))
    with TestClient(app) as client:
        # The same reset test_alerts.py's fixture does, for the same race.
        client.app.state.collector.stop()
        conn = dbmod.connect(tmp_path / "dash.db")
        conn.execute("DELETE FROM alert_log")
        conn.execute("DELETE FROM notices")
        conn.commit()
        try:
            yield client, conn, app.state.settings
        finally:
            conn.close()


def test_the_three_live_records_do_not_fire(env):
    client, conn, settings = env
    for editor, machine in LIVE_MACHINES:
        _report(client, editor, machine, dict(NEWEST_BUT_OLD))
    assert _stale_subjects(conn, settings) == set()


def test_a_genuinely_stale_computer_still_fires_beside_them(env):
    """A newer version exists (the three above are on it) and this one could
    not update: the alarm is real."""
    client, conn, settings = env
    for editor, machine in LIVE_MACHINES:
        _report(client, editor, machine, dict(NEWEST_BUT_OLD))
    _report(client, "jsmith", "EDIT-PC", {
        "action": "stale", "age_days": 81, "stale": True, "ok": True,
        "version": "2026.07.04",
        "message": "yt-dlp 2026.07.04 is 81 days old and it could not update itself",
        "checked_at": NOW})
    subjects = _stale_subjects(conn, settings)
    assert len(subjects) == 1
    assert "EDIT-PC" in next(iter(subjects))


def test_the_newest_release_message_is_not_enough_when_something_newer_is_known(env):
    """The companion's sentence is prose, and another computer running a
    newer build is evidence that it is out of date."""
    client, conn, settings = env
    _report(client, "alex", "Creator_1", dict(NEWEST_BUT_OLD))
    _report(client, "alex", "Razer", {
        "action": "checked", "age_days": 2, "stale": False, "ok": True,
        "version": "2026.09.22", "message": None, "checked_at": NOW})
    subjects = _stale_subjects(conn, settings)
    assert len(subjects) == 1 and "Creator_1" in next(iter(subjects))


def test_newest_known_version_alone_is_not_enough_without_the_message(env):
    """A fleet all on the same old build has nothing newer among it; only the
    computer's own check can say nothing newer exists."""
    client, conn, settings = env
    for editor, machine in LIVE_MACHINES:
        _report(client, editor, machine, {
            **NEWEST_BUT_OLD,
            "message": "yt-dlp 2026.08.19 is 36 days old and it could not update itself"})
    assert len(_stale_subjects(conn, settings)) == 3


def test_the_structured_latest_field_wins_either_way(env):
    client, conn, settings = env
    # latest=True: not stale, even with no helpful message and nothing to compare.
    _report(client, "alex", "Creator_1", {**NEWEST_BUT_OLD, "latest": True,
                                          "message": None})
    # latest=False: stale, even though the message claims otherwise.
    _report(client, "alex", "Razer", {**NEWEST_BUT_OLD, "latest": False})
    subjects = _stale_subjects(conn, settings)
    assert len(subjects) == 1 and "Razer" in next(iter(subjects))


def test_the_false_alarm_already_raised_is_recovered(env, monkeypatch):
    """With the rule in place the finding leaves the scan, which `deliver`
    records as RECOVERED (`ytdlp_stale.ok`): it clears itself, no click."""
    client, conn, settings = env
    _report(client, "alex", "Razer", dict(NEWEST_BUT_OLD))
    monkeypatch.setattr(alerts, "_ytdlp_is_newest", lambda record, newest: False)
    alerts.run_cycle(conn, settings, NOW)
    raised = [r for r in dbmod.fetch_alerts(conn, limit=100) if r["kind"] == "ytdlp_stale"]
    assert raised
    monkeypatch.undo()
    alerts.run_cycle(conn, settings, NOW)
    recovered = [r for r in dbmod.fetch_alerts(conn, limit=100)
                 if r["kind"] == "ytdlp_stale" + alerts.RECOVERED_SUFFIX]
    assert recovered and recovered[0]["subject"] == raised[0]["subject"]


@pytest.mark.parametrize("a,b", [
    ("2026.9.1", "2026.08.19"),
    ("2026.08.19.1", "2026.08.19"),
    ("2026.10.02", "2026.09.30"),
])
def test_versions_compare_as_dates_not_strings(a, b):
    assert alerts._ytdlp_version_key(a) > alerts._ytdlp_version_key(b)
