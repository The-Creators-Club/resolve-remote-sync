"""Wave 2 of the usability + resilience sweep 2026-09-03: the alarm reaches
someone (DDIAG-3, DDIAG-7, DDIAG-8, DDIAG-9, DDIAG-10, SYS-1 part c).

Its own file rather than more of `test_notices.py`, which pins the 2026-08-28
contract and reads better left alone. What is pinned here: a fix sentence that
names a page also carries that page's URL, a stamped reading stops being
judged once it is not about today, a computer nobody will hear from again is
one standing notice rather than a daily mail, an optional page that failed to
mount says so on the panel, the sink being `none` is itself a finding, and the
server's own crash files finally have a reader.
"""
from __future__ import annotations

import io
import os
import zipfile

from fastapi.testclient import TestClient

from ccsync_dashboard import alerts as alertsmod
from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import notices
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

NOW = "2026-09-04T12:00:00+00:00"
LATER = "2026-09-04T12:05:00+00:00"
SECRET = "s"


# ------------------------------------------------------------------ DDIAG-8

def test_every_kind_that_names_a_page_carries_an_href():
    """The registry is the spine: a kind whose fix sentence sends an owner to
    a page must carry that page's URL, because the panel is the one alarm a
    non-technical person reads and prose is not navigation."""
    for kind in ("pending_device_approval", "feed_unreachable", "invariant_broken",
                 "protection_missing", "editor_without_machine", "alerts_sink_none",
                 "machine_forgotten", "feature_not_mounted", "server_crash_report"):
        href, label = dbmod.notice_href(kind)
        assert href.startswith("/"), kind
        assert label, kind


def test_notice_href_uses_the_real_routes_this_dashboard_serves():
    assert dbmod.notice_href("pending_device_approval")[0] == "/admin/users"
    assert dbmod.notice_href("feed_unreachable")[0] == "/admin/packages"
    assert dbmod.notice_href("invariant_check_failed")[0] == "/admin/invariants"
    assert dbmod.notice_href("protection_unverifiable")[0] == "/admin/protection"
    assert dbmod.notice_href("alerts_sink_none")[0] == "/admin/alerts"


def test_notice_href_derives_the_project_page_from_the_subject():
    """`inventory_refused` and `plan_without_share` are about ONE project when
    the subject names one, and about the fleet when it does not."""
    assert dbmod.notice_href("inventory_refused", "ff5-lab")[0] == "/project/ff5-lab"
    assert dbmod.notice_href("enforce_refusal", "share removals")[0] == "/fleet"
    assert dbmod.notice_href(
        "plan_without_share", "jsmith/EDIT-PC -> ff5-lab")[0] == "/project/ff5-lab"


def test_notice_href_is_empty_for_a_kind_with_no_page_and_never_raises():
    assert dbmod.notice_href("dev_insecure") == ("", "")
    assert dbmod.notice_href("no-such-kind-at-all") == ("", "")


def test_the_panel_renders_take_me_there_and_keeps_the_prose(tmp_path):
    app = create_app(Settings(
        db_path=str(tmp_path / "dash.db"), report_token="sekrit",
        session_secret=SECRET, admin_users=frozenset({"owen"}),
    ))
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "dash.db")
        try:
            dbmod.notice(conn, "pending_device_approval", "warn", "DEV-1",
                         body="waiting", fix="Approve it on Settings, Users.", now=NOW)
            conn.commit()
            client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
            html = client.get("/partials/notices").text
            assert "[ TAKE ME THERE ]" in html
            assert 'href="/admin/users"' in html
            # The sentence STAYS: the sink mails the same text and a mail body
            # has no link to offer.
            assert "Approve it on Settings, Users." in html
        finally:
            conn.close()


# ------------------------------------------------------------------ DDIAG-9

def _seed_disk(conn, editor, machine, free, disk_at, trash=None):
    conn.execute(
        "INSERT INTO machine_state (editor_username, machine, reported_at, "
        "received_at, disk_root_free_bytes, disk_root_total_bytes, disk_at, "
        "trash_bytes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (editor, machine, disk_at, disk_at, free, 500 * 1024 ** 3, disk_at, trash))


def test_a_reading_inside_the_stale_window_is_still_judged(conn):
    """30 hours is past alerts' gone-quiet line and inside this check's own: a
    laptop that was off overnight has not changed its free space, and its disk
    warning must not vanish because nobody used it on Sunday."""
    thirty_hours_ago = "2026-09-03T06:00:00+00:00"
    _seed_disk(conn, "jsmith", "EDIT-PC", 30 * 1024 ** 3, thirty_hours_ago)
    notices._check_machine_space(conn, None, NOW)
    assert [r["subject"] for r in dbmod.open_notices(conn)
            if r["kind"] == "machine_disk_low"] == ["jsmith/EDIT-PC"]


def test_a_reading_past_the_stale_hours_clears_both_machine_space_kinds(conn):
    old = "2026-09-01T00:00:00+00:00"          # ~84 h, past MACHINE_DISK_STALE_HOURS
    _seed_disk(conn, "jsmith", "OLD-PC", 10 * 1024 ** 3, old, trash=500 * 1024 ** 3)
    dbmod.notice(conn, "machine_disk_low", "warn", "jsmith/OLD-PC", now=old)
    dbmod.notice(conn, "machine_trash_oversize", "warn", "jsmith/OLD-PC", now=old)
    notices._check_machine_space(conn, None, NOW)
    open_kinds = {r["kind"] for r in dbmod.open_notices(conn)}
    assert "machine_disk_low" not in open_kinds
    assert "machine_trash_oversize" not in open_kinds
    assert notices.MACHINE_DISK_STALE_HOURS == 48


# ------------------------------------------------------------------ DDIAG-3

def _seen(conn, editor, machine, when):
    conn.execute(
        "INSERT INTO machine_state (editor_username, machine, reported_at, received_at) "
        "VALUES (?, ?, ?, ?)", (editor, machine, when, when))


def test_machine_forgotten_fires_past_the_give_up_line_and_names_forget(conn):
    _seen(conn, "jsmith", "OLD-LAPTOP", "2026-08-01T12:00:00+00:00")
    notices._check_forgotten_machines(conn, None, NOW)
    rows = [r for r in dbmod.open_notices(conn) if r["kind"] == "machine_forgotten"]
    assert [r["subject"] for r in rows] == ["jsmith/OLD-LAPTOP"]
    assert "OLD-LAPTOP" in rows[0]["body"] and "jsmith" in rows[0]["body"]
    assert "last reported" in rows[0]["body"]
    assert "[ FORGET ]" in rows[0]["fix"]
    assert dbmod.notice_href("machine_forgotten")[0] == "/fleet"
    assert notices.SILENT_GIVE_UP_DAYS == 14


def test_machine_forgotten_is_silent_for_a_machine_still_reporting(conn):
    _seen(conn, "jsmith", "EDIT-PC", "2026-09-04T11:00:00+00:00")
    notices._check_forgotten_machines(conn, None, NOW)
    assert dbmod.open_notices(conn) == []
    # ...and the kind IS checked, so the panel does not read it as a gap.
    assert "machine_forgotten" in dbmod.notice_check_times(conn)


def test_machine_forgotten_clears_when_the_machine_reports_again(conn):
    _seen(conn, "jsmith", "OLD-LAPTOP", "2026-08-01T12:00:00+00:00")
    notices._check_forgotten_machines(conn, None, NOW)
    assert any(r["kind"] == "machine_forgotten" for r in dbmod.open_notices(conn))
    conn.execute("UPDATE machine_state SET received_at=? WHERE machine='OLD-LAPTOP'",
                 (NOW,))
    notices._check_forgotten_machines(conn, None, NOW)
    assert not any(r["kind"] == "machine_forgotten" for r in dbmod.open_notices(conn))


def test_machine_forgotten_clears_when_the_row_is_forgotten(conn):
    _seen(conn, "jsmith", "OLD-LAPTOP", "2026-08-01T12:00:00+00:00")
    notices._check_forgotten_machines(conn, None, NOW)
    conn.execute("DELETE FROM machine_state WHERE machine='OLD-LAPTOP'")
    notices._check_forgotten_machines(conn, None, NOW)
    assert not any(r["kind"] == "machine_forgotten" for r in dbmod.open_notices(conn))


# ------------------------------------------------------------------ DDIAG-7

class _Mounts:
    """A stand-in for mount_status (builder B7's module): name -> (status,
    detail), recorded at boot."""

    def __init__(self, statuses):
        self._statuses = statuses

    def snapshot(self):
        return self._statuses


def test_feature_not_mounted_names_the_page_and_the_reason(conn, monkeypatch):
    monkeypatch.setattr(notices, "mount_status", _Mounts({
        "broll": ("absent", "the b-roll checkout is not on this server"),
        "music": ("mounted", ""),
    }))
    notices._check_feature_mounts(conn, None, NOW)
    rows = [r for r in dbmod.open_notices(conn) if r["kind"] == "feature_not_mounted"]
    assert [r["subject"] for r in rows] == ["broll"]
    assert "The B-ROLL page is not available on this server" in rows[0]["body"]
    assert "the b-roll checkout is not on this server" in rows[0]["body"]
    assert "Editors will not see the link in the menu." in rows[0]["body"]
    assert "docs/DOCKER.md" in rows[0]["fix"]


def test_feature_not_mounted_clears_when_the_mount_comes_back(conn, monkeypatch):
    monkeypatch.setattr(notices, "mount_status",
                        _Mounts({"cards": ("degraded", "the vault root is not mounted")}))
    notices._check_feature_mounts(conn, None, NOW)
    assert any(r["kind"] == "feature_not_mounted" for r in dbmod.open_notices(conn))
    monkeypatch.setattr(notices, "mount_status", _Mounts({"cards": ("mounted", "")}))
    notices._check_feature_mounts(conn, None, LATER)
    assert not any(r["kind"] == "feature_not_mounted" for r in dbmod.open_notices(conn))


def test_feature_not_mounted_writes_nothing_without_the_mount_status_module(conn, monkeypatch):
    """A status this build cannot read is not evidence that the four pages are
    up: nothing is written, nothing is cleared, and the kind reads
    [ NOT CHECKED ] rather than a false [ OK ]."""
    monkeypatch.setattr(notices, "mount_status", None)
    notices._check_feature_mounts(conn, None, NOW)
    assert dbmod.open_notices(conn) == []
    assert "feature_not_mounted" not in dbmod.notice_check_times(conn)


# ------------------------------------------------------------------ SYS-1(c)

def test_alerts_sink_none_stands_open_while_nobody_is_told(conn):
    notices._check_alerts_sink(conn, None, NOW)
    rows = [r for r in dbmod.open_notices(conn) if r["kind"] == "alerts_sink_none"]
    assert rows
    assert rows[0]["body"].startswith(
        "Nobody is being told when this server finds a problem.")
    assert "[ SEND A TEST ]" in rows[0]["fix"]


def test_alerts_sink_none_clears_once_a_sink_is_configured(conn):
    notices._check_alerts_sink(conn, None, NOW)
    alertsmod.set_settings(conn, {
        "alerts_sink": alertsmod.SINK_WEBHOOK,
        "alerts_webhook_url": "https://hooks.example.com/abc",
    }, "owen")
    notices._check_alerts_sink(conn, None, LATER)
    assert not any(r["kind"] == "alerts_sink_none" for r in dbmod.open_notices(conn))


# ----------------------------------------------------------------- DDIAG-10

class _CrashSettings:
    def __init__(self, db_path):
        self.db_path = str(db_path)


def _crash_file(tmp_path, name="20260904T120000-Collector.json", when=None):
    directory = tmp_path / "crashes"
    directory.mkdir(exist_ok=True)
    path = directory / name
    path.write_text('{"exception": {"message": "boom"}}', encoding="utf-8")
    if when is not None:
        os.utime(path, (when, when))
    return path


def test_server_crash_report_counts_files_written_since_this_boot(conn, tmp_path):
    settings = _CrashSettings(tmp_path / "dash.db")
    _crash_file(tmp_path)
    notices._check_server_crashes(conn, settings, NOW)
    rows = [r for r in dbmod.open_notices(conn) if r["kind"] == "server_crash_report"]
    assert rows
    assert "crashed 1 time(s) since it started" in rows[0]["body"]
    assert "[ DOWNLOAD CRASH REPORTS ]" in rows[0]["fix"]
    assert dbmod.notice_href("server_crash_report") == (
        "/admin/diagnostics/crash-reports.zip", "[ DOWNLOAD CRASH REPORTS ]")


def test_server_crash_report_ignores_a_report_from_a_previous_run(conn, tmp_path):
    """"Since it started" is the point: a crash from last month is not
    something this run has to answer for, and the file is still in the zip."""
    settings = _CrashSettings(tmp_path / "dash.db")
    _crash_file(tmp_path, when=notices._PROCESS_STARTED - 86_400)
    notices._check_server_crashes(conn, settings, NOW)
    assert not any(r["kind"] == "server_crash_report" for r in dbmod.open_notices(conn))
    assert "server_crash_report" in dbmod.notice_check_times(conn)


def test_crash_zip_holds_the_files_verbatim_and_writes_nothing(tmp_path):
    settings = _CrashSettings(tmp_path / "dash.db")
    _crash_file(tmp_path)
    before = sorted(p.name for p in (tmp_path / "crashes").iterdir())
    payload, count = notices.crash_zip_bytes(settings)
    assert count == 1
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        assert zf.namelist() == ["20260904T120000-Collector.json"]
        # Already redacted at write time by crash_report.build_report, so the
        # download hands over exactly what is on disk.
        assert b"boom" in zf.read("20260904T120000-Collector.json")
    assert sorted(p.name for p in (tmp_path / "crashes").iterdir()) == before


def test_crash_zip_survives_a_directory_that_is_not_there(tmp_path):
    settings = _CrashSettings(tmp_path / "nope" / "dash.db")
    payload, count = notices.crash_zip_bytes(settings)
    assert count == 0 and payload


def test_the_crash_download_is_admin_only(tmp_path):
    app = create_app(Settings(
        db_path=str(tmp_path / "dash.db"), report_token="sekrit",
        session_secret=SECRET, admin_users=frozenset({"owen"}),
    ))
    (tmp_path / "crashes").mkdir(exist_ok=True)
    (tmp_path / "crashes" / "20260904T120000-Collector.json").write_text(
        '{"exception": {"message": "boom"}}', encoding="utf-8")
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
        assert client.get("/admin/diagnostics/crash-reports.zip").status_code in (302, 303, 403)
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        resp = client.get("/admin/diagnostics/crash-reports.zip")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            assert zf.namelist() == ["20260904T120000-Collector.json"]


# --------------------------------------------------------- the whole pass

def test_run_checks_runs_wave_twos_checks_and_stamps_their_evidence(
        conn, tmp_path, monkeypatch):
    monkeypatch.setattr(notices, "mount_status", _Mounts({"ytdl": ("absent", "no ytdl")}))
    settings = Settings(db_path=str(tmp_path / "dash.db"))
    ran = notices.run_checks(conn, settings, now=NOW)
    assert ran >= 12
    checked = dbmod.notice_check_times(conn)
    for kind in ("machine_forgotten", "feature_not_mounted", "alerts_sink_none",
                 "server_crash_report"):
        assert kind in checked
