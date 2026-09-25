"""The eleventh hunt's wave 2, group d-diag, chunk 1 (2026-09-25).

One test (or a small group) per finding, each pinning the failure the hunter
reproduced rather than the wording of the fix:

* bug-dash-diag-1: a NAS that does not answer must not close a MISSING
  protection line or mail "this has cleared";
* bug-dash-diag-3: a snapshot restore lands outside every project's Syncthing
  folder;
* bug-dash-ops-1: a Sent-folder SUBSTRING hit is not the owner's authorship,
  and nothing overrules an explicit dkim/dmarc fail;
* logic-sync-truth-1: a laptop asleep for 20 minutes is "not heard from",
  amber, never a red "Upload has stopped";
* logic-admin-1: the fleet_halt_expired alert can fire at all;
* logic-alerts-1: a page a site deliberately left off is not a fault;
* logic-alerts-2: [ UPDATE NOW ] is never the fix for a computer already on
  the current build;
* logic-alerts-3: a lagging platform with a newer build already staged is
  told to make it current, not to build it;
* ui-copy-1: the halt alerts and the recovery step name controls that exist.
"""
from __future__ import annotations

import email
import re
from email.message import EmailMessage
from pathlib import Path

import pytest

from ccsync_dashboard import alerts, health, mount_status, notices, protection
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import recovery, triage_mail
from ccsync_dashboard.settings import Settings

NOW = "2026-09-25T12:00:00+00:00"
TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "d.db")
    dbmod.migrate(c)
    yield c
    c.close()


def _settings(**kw) -> Settings:
    return Settings(session_secret="test-secret", **kw)


# ------------------------------------------------------- bug-dash-diag-1

def _open_missing(conn) -> set[str]:
    return {str(r["subject"]) for r in dbmod.open_notices(conn)
            if r["kind"] == protection.NOTICE_MISSING}


def test_a_nas_that_does_not_answer_keeps_a_missing_line_missing(conn, monkeypatch):
    """The hunter's probe: pass 1 sees no task covering the tree (MISSING),
    pass 2 cannot ask the NAS. On HEAD pass 2 stored CANNOT VERIFY, closed the
    notice and the alert scan stopped returning the finding, so deliver()
    mailed a recovery about the snapshot schedule."""
    monkeypatch.setenv(protection.ENV_TREE_DATASET, "tank/Projects")
    protection.run_cycle(conn, _settings(), NOW,
                         tasks_fn=lambda: [{"dataset": "tank/other", "enabled": True}])
    assert "snapshot_tree: tank/Projects" in _open_missing(conn)

    later = "2026-09-25T12:15:00+00:00"
    protection.run_cycle(conn, _settings(), later, tasks_fn=lambda: None)
    assert "snapshot_tree: tank/Projects" in _open_missing(conn)
    line = next(r for r in protection.page_view(conn)["lines"]
                if r["key"] == "snapshot_tree")
    assert line["state"] == protection.BROKEN
    assert "could not check it again" in line["detail"]
    assert NOW in line["detail"]
    findings = alerts._check_protection_missing(
        type("C", (), {"conn": conn})())
    assert "snapshot_tree" in {f["subject"] for f in findings}
    # ...and not ALSO a "cannot verify" warn about the same line.
    unverifiable = alerts._check_protection_unverifiable(
        type("C", (), {"conn": conn})())
    assert "snapshot_tree" not in {f["subject"] for f in unverifiable}

    # A second blind pass keeps the ORIGINAL date and detail, never nested.
    protection.run_cycle(conn, _settings(), "2026-09-25T12:30:00+00:00",
                         tasks_fn=lambda: None)
    line = next(r for r in protection.page_view(conn)["lines"]
                if r["key"] == "snapshot_tree")
    assert line["detail"].count("could not check it again") == 1
    assert NOW in line["detail"]

    # A REAL verdict replaces it: the task appears and the notice closes.
    protection.run_cycle(conn, _settings(), "2026-09-25T12:45:00+00:00",
                         tasks_fn=lambda: [{"dataset": "tank/Projects",
                                            "enabled": True}])
    assert "snapshot_tree: tank/Projects" not in _open_missing(conn)


def test_a_line_that_was_never_missing_still_reads_cannot_verify(conn, monkeypatch):
    monkeypatch.setenv(protection.ENV_TREE_DATASET, "tank/Projects")
    protection.run_cycle(conn, _settings(), NOW, tasks_fn=lambda: None)
    line = next(r for r in protection.page_view(conn)["lines"]
                if r["key"] == "snapshot_tree")
    assert line["state"] == protection.NOT_CHECKED


# ------------------------------------------------------- bug-dash-diag-3

def test_a_restore_lands_outside_every_project_folder(tmp_path, conn):
    projects = tmp_path / "projects"
    snaps = tmp_path / "snaps"
    (projects / "2026/One").mkdir(parents=True)
    (projects / "2026/One/notes.txt").write_text("live")
    (snaps / "s1/2026/One").mkdir(parents=True)
    (snaps / "s1/2026/One/lost.wav").write_text("gone")
    dbmod.upsert_project(conn, "one", "2026/One", "/x", NOW)
    conn.commit()
    result = recovery.restore_into_quarantine(
        _settings(projects_dir=str(projects)), conn, "one", "s1", "owen",
        env={recovery.ENV_SNAPSHOT_DIR: str(snaps)}, now=NOW,
        snapshot_before=lambda *_a: {"ok": False, "reason": "test"})
    restored = Path(result["directory"])
    assert (restored / "lost.wav").read_text() == "gone"
    # The project folder is a Syncthing root: nothing new appears in it.
    assert sorted(p.name for p in (projects / "2026/One").iterdir()) == ["notes.txt"]
    project = (projects / "2026/One").resolve()
    assert not restored.resolve().is_relative_to(project)
    assert result["where"].startswith(recovery.QUARANTINE_PREFIX)
    assert result["where"].endswith("/2026/One")


# ------------------------------------------------------- bug-dash-ops-1

def _mail(message_id: str, body: str = "do 1", ar: tuple[str, ...] = ()) -> bytes:
    msg = EmailMessage()
    for header in ar:
        msg["Authentication-Results"] = header
    msg["From"] = "Owner <owner@example.com>"
    msg["To"] = "owner+ccsync@example.com"
    msg["Subject"] = "Re: [CC Sync] Server check"
    msg["Message-ID"] = message_id
    msg.set_content(body)
    return msg.as_bytes()


class _Sent:
    """A Sent folder whose HEADER search is a SUBSTRING match, as RFC 3501
    says it is, holding one real message the owner sent."""

    def __init__(self, held: bytes):
        self.held = held
        self.selected = None

    def list(self):
        return "OK", [rb'(\HasNoChildren \Sent) "/" "[Gmail]/Sent Mail"']

    def select(self, box, readonly=False):
        self.selected = box
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        needle = criteria[-1].strip('"')
        held_id = str(email.message_from_bytes(self.held).get("Message-ID") or "")
        return "OK", [b"3" if needle in held_id else b""]

    def fetch(self, num, what):
        return "OK", [(b"3 (BODY[] {n}", self.held), b")"]


def test_a_message_id_fragment_is_not_the_owners_sent_copy():
    held = _mail("<CAB123xyz@mail.gmail.com>", body="the owner's real words")
    forged = _mail("mail.gmail.com", body="do 1")
    assert triage_mail._in_sent(_Sent(held), forged) is False
    # The owner's own message still passes: same id, same text.
    assert triage_mail._in_sent(_Sent(held), held) is True


def test_a_matching_id_with_different_text_is_not_the_sent_copy():
    held = _mail("<CAB123xyz@mail.gmail.com>", body="the owner's real words")
    assert triage_mail._in_sent(_Sent(held), _mail("<CAB123xyz@mail.gmail.com>",
                                                   body="do 1 2 3")) is False


def test_an_explicit_dmarc_fail_is_never_overruled_by_the_sent_proof():
    failing = ("mx.google.com; dkim=none; spf=softfail smtp.mailfrom=example.com; "
               "dmarc=fail (p=NONE) header.from=example.com")
    msg = email.message_from_bytes(_mail("<a@b>", ar=(failing,)))
    assert triage_mail.auth_results_fail(msg) is True
    assert triage_mail.auth_results_fail(
        email.message_from_bytes(_mail("<a@b>"))) is False
    # A "dmarc=fail" hidden in a comment is not a verdict.
    commented = "mx.google.com; (dmarc=fail) dkim=pass header.i=@example.com"
    assert triage_mail.auth_results_fail(
        email.message_from_bytes(_mail("<a@b>", ar=(commented,)))) is False


def test_handle_message_refuses_a_sent_hit_over_a_dmarc_fail(tmp_path):
    import hashlib
    import json

    settings = Settings(db_path=str(tmp_path / "t.db"))
    c = dbmod.connect(settings.db_path)
    dbmod.migrate(c)
    alerts.set_settings(c, {
        "alerts_sink": "smtp", "alerts_smtp_host": "smtp.gmail.com",
        "alerts_smtp_user": "owner@example.com",
        "alerts_smtp_from": "owner@example.com",
        "alerts_smtp_to": "owner@example.com", "alerts_triage": "1",
        "alerts_triage_reply_to": "owner+ccsync@example.com"}, "owen")
    token = "AbCdEfGhIjKlMnOpQrStUv"
    c.execute(
        "INSERT INTO triage_runs (id, started_at, finished_at, status, token_hash, "
        "token_expires_at, report_json, email_ok) VALUES (1, ?, ?, 'ok', ?, ?, ?, 1)",
        (NOW, NOW, hashlib.sha256(token.encode()).hexdigest(),
         "2026-09-26T12:00:00+00:00", json.dumps({"subject": "x"})))
    c.commit()
    failing = ("mx.google.com; dkim=none; "
               "dmarc=fail (p=NONE) header.from=example.com")
    raw = _mail("<forged@x>", body=f"do 1\n\nReference: CCT-{token}", ar=(failing,))
    try:
        out = triage_mail.handle_message(c, settings, raw, now=NOW, in_own_sent=True,
                                         interpreter=lambda *a, **k: {"do": []})
        assert out["verdict"] == "refused"
        # And without the fail, the owner's own no-header reply still passes.
        raw = _mail("<own@x>", body=f"do 1\n\nReference: CCT-{token}")
        out = triage_mail.handle_message(c, settings, raw, now=NOW, in_own_sent=True,
                                         interpreter=lambda *a, **k: {"do": []})
        assert out["verdict"] == "acted"
    finally:
        c.close()


# ------------------------------------------------------- logic-sync-truth-1

def _lane(name, state, received_at):
    return {"lane": name, "state": state, "received_at": received_at,
            "last_error": None, "progress_token_since": None}


def _row(received_at, now, states=("idle", "idle", "idle")):
    lanes = []
    for (name, _label), state in zip(health.LANE_STRIP, states):
        lane = _lane(name, state, received_at)
        lane["chip"], lane["chip_reason"] = health.lane_chip(lane, now)
        lanes.append(lane)
    freshness, reason = health.report_freshness(received_at, now)
    return {"lanes": lanes, "received_at": received_at,
            "status": health.worst([l["chip"] for l in lanes] + [freshness]),
            "status_reason": reason}


def test_a_laptop_asleep_for_twenty_minutes_is_amber_not_upload_has_stopped():
    received = "2026-09-25T11:40:00+00:00"
    row = _row(received, NOW)
    headline = health.fleet_headline(row)
    assert headline["reason"] == "not_reporting"
    assert headline["level"] == health.AMBER
    assert "Upload has stopped" not in headline["text"]
    assert "2026-09-25 11:40" in headline["text"]
    assert row["status"] == health.AMBER
    assert all(l["chip"] == health.AMBER for l in row["lanes"])


def test_six_hours_of_silence_is_red_and_still_about_the_computer():
    row = _row("2026-09-25T05:00:00+00:00", NOW)
    headline = health.fleet_headline(row)
    assert headline["reason"] == "not_reporting"
    assert headline["level"] == health.RED
    assert row["status"] == health.RED


def test_a_fresh_lane_error_is_still_the_headline():
    row = _row("2026-09-25T11:59:00+00:00", NOW, states=("error", "idle", "idle"))
    row["lanes"][0]["last_error"] = "rclone exited 1"
    row["lanes"][0]["chip"], row["lanes"][0]["chip_reason"] = health.lane_chip(
        row["lanes"][0], NOW)
    assert health.fleet_headline(row)["reason"] == "lane_error"


def _with_dropped_lane(row, lane_received_at, now=NOW):
    """The row plus a lane row the companion stopped sending: it lives on in
    lane_report_current (LANE_HISTORY_MAX_AGE_DAYS) with its old stamp, and
    build_editors_view's row received_at is the max over the lanes."""
    old = _lane("lane_c_syncthing", "idle", lane_received_at)
    old["chip"], old["chip_reason"] = health.lane_chip(old, now)
    row["lanes"] = [l for l in row["lanes"] if l["lane"] != "lane_c_syncthing"] + [old]
    row["status"] = health.worst([l["chip"] for l in row["lanes"]] + [
        health.report_freshness(row["received_at"], now)[0]])
    return row


def test_a_dropped_lanes_old_stamp_never_says_a_reporting_computer_is_silent():
    # Review round: the row reported ten seconds ago; a lane it no longer
    # sends last spoke at 09:00. The headline used to be "Not heard from
    # since 2026-09-25 11:59 UTC", amber, about a computer that just reported.
    row = _with_dropped_lane(
        _row("2026-09-25T11:59:50+00:00", NOW, states=("idle", "idle", "idle")),
        "2026-09-25T09:00:00+00:00")
    assert row["status_reason"] is None
    headline = health.fleet_headline(row)
    assert headline["reason"] != "not_reporting"
    assert "Not heard from" not in headline["text"]
    # ...and the same lane gone RED (seven hours old) still says nothing false.
    row = _with_dropped_lane(
        _row("2026-09-25T11:59:50+00:00", NOW), "2026-09-25T05:00:00+00:00")
    assert "Not heard from" not in health.fleet_headline(row)["text"]


def test_a_dropped_lanes_old_stamp_does_not_redden_a_computer_asleep_briefly():
    # The row is 20 minutes quiet (amber); the dropped lane is 7 hours old.
    # Amber is the row's own freshness, not red from the leftover lane.
    row = _with_dropped_lane(
        _row("2026-09-25T11:40:00+00:00", NOW), "2026-09-25T05:00:00+00:00")
    headline = health.fleet_headline(row)
    assert headline["reason"] == "not_reporting"
    assert headline["level"] == health.AMBER
    assert "2026-09-25 11:40" in headline["text"]


def test_a_computer_with_no_lane_rows_still_reads_not_heard_from():
    freshness, reason = health.report_freshness("2026-09-25T05:00:00+00:00", NOW)
    row = {"lanes": [], "received_at": "2026-09-25T05:00:00+00:00",
           "status": freshness, "status_reason": reason}
    headline = health.fleet_headline(row)
    assert headline["reason"] == "not_reporting"
    assert headline["level"] == health.RED


# logic-sync-truth-1, Fable round (2026-09-25): nothing ticked is never a
# warning, so its silence is a muted fact; a computer with ticks keeps amber.

def _nothing_ticked(row):
    row["why"] = {"reason": "no_selection",
                  "sentence": health._why_sentence("no_selection", row),
                  "informational": True}
    return row


@pytest.mark.parametrize("received", ["2026-09-25T11:40:00+00:00",
                                      "2026-09-25T05:00:00+00:00"])
def test_a_quiet_computer_with_nothing_ticked_is_not_amber(received):
    row = _nothing_ticked(_row(received, NOW))
    headline = health.fleet_headline(row)
    assert headline["level"] == health.HEADLINE_MUTED
    assert headline["reason"] == "no_selection"
    assert "Not heard from" not in headline["text"]
    assert headline["text"].startswith("Nothing ticked for this computer")
    assert received[:10] + " " + received[11:16] in headline["text"]
    assert "—" not in headline["text"]
    # No lane rows at all: the same answer.
    bare = _nothing_ticked({"lanes": [], "received_at": received,
                            "status": health.report_freshness(received, NOW)[0],
                            "status_reason": health.report_freshness(received, NOW)[1]})
    assert health.fleet_headline(bare)["level"] == health.HEADLINE_MUTED


def test_a_quiet_computer_with_ticks_keeps_the_amber_headline():
    row = _row("2026-09-25T11:40:00+00:00", NOW)
    # Upload-only is informational too, but it is a TICK: its silence is
    # footage not moving.
    row["why"] = {"reason": "upload_only", "sentence": "Upload only",
                  "informational": True}
    headline = health.fleet_headline(row)
    assert headline["reason"] == "not_reporting"
    assert headline["level"] == health.AMBER


def test_a_reporting_computer_with_nothing_ticked_reads_as_before():
    row = _nothing_ticked(_row("2026-09-25T11:59:50+00:00", NOW))
    headline = health.fleet_headline(row)
    assert headline == {"reason": "no_selection",
                        "text": "Nothing ticked for this computer",
                        "level": health.HEADLINE_MUTED}


# ------------------------------------------------------- logic-admin-1

class _HaltCtx:
    def __init__(self, conn, now):
        self.conn, self.now = conn, now
        self.halt = dbmod.get_fleet_halt(conn, now)


def test_an_expired_fleet_stop_is_reported_for_a_day(conn):
    dbmod.set_fleet_halt(conn, True, "moving the NAS", "owen",
                         now="2026-09-24T00:00:00+00:00", hours=24)
    conn.commit()
    # Still running: the stop alert, not the expired one.
    running = _HaltCtx(conn, "2026-09-24T12:00:00+00:00")
    assert alerts._check_fleet_halt(running)
    assert not alerts._check_fleet_halt_expired(running)
    # Past its expiry: THROUGH get_fleet_halt, the way Ctx.halt is built.
    expired = _HaltCtx(conn, "2026-09-25T06:00:00+00:00")
    assert expired.halt["expired"] and not expired.halt["active"]
    [finding] = alerts._check_fleet_halt_expired(expired)
    assert "past its own expiry" in finding["diagnosis"]
    assert not alerts._check_fleet_halt(expired)
    # Long after: not a standing warn for months.
    assert not alerts._check_fleet_halt_expired(
        _HaltCtx(conn, "2026-09-28T00:00:00+00:00"))
    # Released by hand: nothing expired to talk about.
    dbmod.set_fleet_halt(conn, False, "", "owen", now="2026-09-25T07:00:00+00:00")
    conn.commit()
    assert not alerts._check_fleet_halt_expired(
        _HaltCtx(conn, "2026-09-25T08:00:00+00:00"))


# ------------------------------------------------------- logic-alerts-1

def _open_mount_notices(conn) -> set[str]:
    return {str(r["subject"]) for r in conn.execute(
        "SELECT subject FROM notices WHERE kind='feature_not_mounted' "
        "AND cleared_at IS NULL")}


def test_a_page_the_site_left_off_raises_nothing_and_closes_an_old_card(conn):
    before = mount_status.snapshot()
    mount_status.reset()
    try:
        # An earlier boot where Cards WAS asked for and its checkout vanished.
        mount_status.record("cards", "absent", "the configured checkout is not there")
        for name in ("broll", "music", "ytdl"):
            mount_status.record(name, "mounted", "serving")
        notices._check_feature_mounts(conn, None, NOW)
        conn.commit()
        assert _open_mount_notices(conn) == {"cards"}

        # The vendor shape: YouTube off, no Cards configured.
        mount_status.reset()
        mount_status.record("broll", "mounted", "serving")
        mount_status.record("music", "mounted", "serving")
        mount_status.record("ytdl", "disabled",
                            "this site has not enabled the YouTube downloader")
        mount_status.record("cards", "disabled", "DASH_CARDS_ENABLED is not 1")
        notices._check_feature_mounts(conn, None, NOW)
        conn.commit()
        assert _open_mount_notices(conn) == set()

        # A page that is asked for and broken still raises its card.
        mount_status.record("music", "degraded", "the index could not be opened")
        notices._check_feature_mounts(conn, None, NOW)
        conn.commit()
        assert _open_mount_notices(conn) == {"music"}
    finally:
        mount_status.reset()
        for name, (status, detail) in before.items():
            mount_status.record(name, status, detail)


# ------------------------------------------------------- logic-alerts-2 / 3

def _publish(conn, version, platform, *, current=False, now=NOW):
    dbmod.insert_companion_package(
        conn, version=version, platform=platform, filename=f"c-{version}",
        sha256="0" * 64, size_bytes=1, published_by="owen", now=now)
    if current:
        dbmod.set_current_package(conn, platform, version, now=now)
    conn.commit()


class _FleetCtx:
    def __init__(self, conn, editors, settings=None):
        self.conn, self.now, self.editors = conn, NOW, editors
        self.settings = settings or _settings()
        self.rollout = dbmod.rollout_status(conn, now=NOW)

    def name(self, subject):
        return subject


def _studio_shelf(conn):
    """The studio on 2026-09-17: macOS current 0.9.70 (for a month), three
    newer macOS builds staged, Windows current 0.9.74."""
    month_ago = "2026-08-25T12:00:00+00:00"
    _publish(conn, "0.9.70", "macos", current=True, now=month_ago)
    for v in ("0.9.71", "0.9.72", "0.9.74"):
        _publish(conn, v, "macos")
    _publish(conn, "0.9.74", "windows", current=True)


def _mac(version="0.9.70", current="0.9.70"):
    return {"editor_username": "leso", "machine": "Mac", "platform": "macos",
            "companion_version": version, "current_companion_version": current}


def test_a_computer_on_the_current_build_is_never_told_to_update_now(conn):
    _studio_shelf(conn)
    findings = alerts._check_versions_behind(_FleetCtx(conn, [_mac()]))
    assert len(findings) == 1
    [f] = findings
    assert f["subject"] == "the macos computers"
    assert "3 releases behind" in f["diagnosis"]
    assert "UPDATE NOW ] on that" not in f["fix"]
    assert "make it current" in f["fix"]


def test_a_computer_below_current_is_still_sent_to_update_now(conn):
    _studio_shelf(conn)
    findings = alerts._check_versions_behind(
        _FleetCtx(conn, [_mac(version="0.9.66")]))
    [f] = findings
    assert f["subject"] == "leso/Mac" or "leso" in f["subject"]
    assert '"Update now"' in f["fix"]  # D8, UI port phase 7


def test_a_platform_with_nothing_current_is_not_called_the_current_build(conn):
    # Review round: nothing is current for macos here, and the feed/shelf has
    # three newer builds. The finding used to say they run "this dashboard's
    # current macos build", which is false.
    for v in ("0.9.70", "0.9.71", "0.9.72", "0.9.74"):
        _publish(conn, v, "macos")
    [f] = alerts._check_versions_behind(
        _FleetCtx(conn, [_mac(version="0.9.70", current=None)]))
    assert f["subject"] == "the macos computers"
    assert "current macos build." not in f["diagnosis"]
    assert "no current macos build" in f["diagnosis"]
    assert "UPDATE NOW ] on that" not in f["fix"]
    assert "make it current" in f["fix"]


def test_a_computer_ahead_of_current_is_not_said_to_run_current(conn):
    _studio_shelf(conn)
    for v in ("0.9.75", "0.9.76", "0.9.77"):
        _publish(conn, v, "macos")
    # current is 0.9.70, this Mac runs a hand-installed 0.9.74: three newer
    # builds exist, and "which is this dashboard's current build" is false.
    [f] = alerts._check_versions_behind(
        _FleetCtx(conn, [_mac(version="0.9.74", current="0.9.70")]))
    assert "which is this dashboard's current" not in f["diagnosis"]
    assert "current macos build is 0.9.70" in f["diagnosis"]


def test_a_staged_mac_build_is_made_current_not_built(conn):
    _studio_shelf(conn)
    [f] = alerts._check_platform_channel_stale(_FleetCtx(conn, []))
    assert "0.9.74 for macos is already published" in f["diagnosis"]
    assert "make 0.9.74 current" in f["fix"]
    assert "release_macos.sh" not in f["fix"]
    assert "until somebody builds it" not in f["diagnosis"]


def test_a_feed_site_is_never_handed_repo_commands(conn):
    month_ago = "2026-08-25T12:00:00+00:00"
    _publish(conn, "0.9.70", "macos", current=True, now=month_ago)
    _publish(conn, "0.9.74", "windows", current=True)
    feed = _settings(release_feed_url="https://example.com/feed.json")
    [f] = alerts._check_platform_channel_stale(_FleetCtx(conn, [], feed))
    assert "release_macos.sh" not in f["fix"]
    assert "vendor" in f["fix"]


def test_a_lagging_windows_channel_is_not_told_to_use_a_mac(conn):
    month_ago = "2026-08-25T12:00:00+00:00"
    _publish(conn, "0.9.70", "windows", current=True, now=month_ago)
    _publish(conn, "0.9.74", "macos", current=True)
    [f] = alerts._check_platform_channel_stale(_FleetCtx(conn, []))
    assert "On a Mac" not in f["fix"]
    assert "windows" in f["fix"]


def test_the_vendor_site_still_gets_the_mac_commands(conn):
    month_ago = "2026-08-25T12:00:00+00:00"
    _publish(conn, "0.9.70", "macos", current=True, now=month_ago)
    _publish(conn, "0.9.74", "windows", current=True)
    [f] = alerts._check_platform_channel_stale(_FleetCtx(conn, []))
    assert "release_macos.sh --publish --make-current" in f["fix"]


# ------------------------------------------------------- ui-copy-1

def _labels(text: str) -> set[str]:
    """The controls a sentence names. D8 (UI port phase 7, 2026-09-25): a
    control is its sentence-case label in double quotes (`press "Resume"`);
    returned as the classic key's text, `[ RESUME ]`, which is what the
    classic panels below still draw (the terminal key uppercases by CSS)."""
    return {f"[ {q.upper()} ]" for q in re.findall(r'"([A-Z][a-z][^"]*)"', text)}


def test_every_button_the_halt_alerts_name_is_on_the_halt_panel(conn):
    panel = (TEMPLATES / "partials" / "fleet_halt.html").read_text(encoding="utf-8")
    dbmod.set_fleet_halt(conn, True, "moving the NAS", "owen",
                         now="2026-09-24T00:00:00+00:00", hours=24)
    conn.commit()
    running = alerts._check_fleet_halt(_HaltCtx(conn, "2026-09-24T01:00:00+00:00"))
    expired = alerts._check_fleet_halt_expired(
        _HaltCtx(conn, "2026-09-25T01:00:00+00:00"))
    named = set()
    for finding in running + expired:
        assert "SYNC STATUS" not in finding["fix"]
        assert "Settings, Users" in finding["fix"]
        named |= _labels(finding["fix"])
    assert named, "the halt alerts name no button at all"
    for label in named:
        assert label in panel, f"{label} is not on the fleet halt panel"


def test_the_recovery_step_sends_the_admin_to_the_halt_panel():
    step = recovery._stop_the_fleet_step()
    assert step.href == "/admin/users#admin-fleet-halt"
    panel = (TEMPLATES / "partials" / "fleet_halt.html").read_text(encoding="utf-8")
    assert 'id="admin-fleet-halt"' in panel
    for label in _labels(step.body):
        assert label in panel



# =====================================================================
# Chunk 2 (2026-09-25): ui-copy-2, bug-dash-diag-2, bug-dash-diag-4,
# bug-dash-ops-5/6/7, logic-sync-truth-5, logic-admin-4, logic-admin-5.
# =====================================================================

# ------------------------------------------------------- ui-copy-2

_NO_SUCH_PAGE = ("Settings, Diagnostics", "send Diagnostics")


def test_no_server_notice_sends_the_owner_to_a_page_that_does_not_exist(conn):
    """ui-copy-2: five fix strings named "Settings, Diagnostics", which is not
    in the Settings strip. Drive the writers that carried them and read what
    they filed."""
    from ccsync_dashboard import ui
    pages = {label for _g, entries in ui.SETTINGS_NAV_GROUPS
             for _k, label, _h, _a in entries}
    assert "DIAGNOSTICS" not in pages          # the premise: there is no such page
    notices.record_server_error(conn, "/api/v1/x", RuntimeError("boom"), now=NOW)
    notices.record_db_busy(conn, "/api/v1/report", now=NOW)
    notices.record_slow_write(conn, "api_report", 30.0, now=NOW)
    for kind, (_meaning, fix) in notices._JOB_MEANING.items():
        assert not any(bad in fix for bad in _NO_SUCH_PAGE), kind
    rows = list(dbmod.open_notices(conn))
    assert {r["kind"] for r in rows} >= {"server_error", "db_busy", "slow_write"}
    for r in rows:
        assert not any(bad in str(r["fix"] or "") for bad in _NO_SUCH_PAGE), r["kind"]
    here = Path(notices.__file__)
    src = here.read_text(encoding="utf-8") + here.with_name("collector.py").read_text(
        encoding="utf-8")
    code = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    for bad in _NO_SUCH_PAGE:
        assert bad not in code, bad


def test_the_named_collector_panel_is_where_the_copy_says():
    """The replacement copy names the [ COLLECTOR ] panel on SYNC STATUS. It is
    included at the end of the fleet grid partial, i.e. under the computers
    table; it is NOT at the bottom of the page (fleet.html renders plan
    changes, the diagnostics div, transfers, the queue and project roots
    after the grid). Review round 2026-09-25: the first copy said "at the
    bottom of SYNC STATUS", which sent the owner to project roots."""
    grid = (TEMPLATES / "partials" / "fleet_grid.html").read_text(encoding="utf-8")
    panel = (TEMPLATES / "partials" / "collector_health.html").read_text(encoding="utf-8")
    page = (TEMPLATES / "fleet.html").read_text(encoding="utf-8")
    include = grid.index('include "partials/collector_health.html"')
    first_table_end = grid.index("</table>")
    assert first_table_end < include            # under the computers table
    assert "[ COLLECTOR ]" in panel
    assert 'include "partials/fleet_grid.html"' in page
    here = Path(notices.__file__)
    src = here.read_text(encoding="utf-8") + here.with_name("collector.py").read_text(
        encoding="utf-8")
    flat = re.sub(r'"\s*\n\s*"', "", src)      # join implicit string concatenation
    assert "bottom of SYNC STATUS" not in flat
    # UI port phase 7 (R13): the copy names the panel, never a page region,
    # because the terminal variant moves the panel; /go/collector resolves it.
    assert "under the computers table" not in flat
    assert flat.count("the Collector panel") >= 4
    fix = notices._JOB_MEANING["config"][1]
    assert "Collector panel" in fix
    from ccsync_dashboard import ui_variant
    assert ui_variant.go_href("collector", frozenset()) == "/#fleet-collector"


def test_the_resolve_undo_step_claims_no_dashboard_button_that_does_not_exist():
    """recovery's "Undo it from here" step linked /fleet (a 404) and told the
    admin to "pick the computer and the change" on a page with no such
    control. The review round made it a note naming the companion's
    [ UNDO LAST FIX ]. Owed round 2 (2026-09-25): the control exists now,
    the [ UNDO A CLIP-PATH CHANGE ] panel (id="resolve-undo") that the same
    page draws under the Resolve plan, so the step is an action again and
    points at that panel. This pins the new truth: the anchor it names is
    one the page renders for exactly this problem, and the button it names
    is the panel's own."""
    steps = recovery._plan_resolve({}, {})
    undo = steps[0]
    assert undo.kind == "action" and undo.title == "Undo it from here"
    assert undo.href == "#resolve-undo"
    assert "Pick the computer and the change" not in undo.body
    assert "no button for this" not in " ".join(s.body for s in steps)
    assert '"Undo this change"' in undo.body  # D8, UI port phase 7
    assert '"Undo last fix"' in undo.body and "Resolve section" in undo.body
    panel = (TEMPLATES / "partials" / "recovery.html").read_text(encoding="utf-8")
    gate = panel.index("{% if recovery_problem == 'resolve' %}")
    anchor = panel.index('id="resolve-undo"')
    assert gate < anchor < panel.index("{% endif %}", anchor)
    assert "[ UNDO THIS CHANGE ]" in panel
    # The plan list renders [ GO ] above the panel, in the same partial, so
    # the fragment resolves without a page load.
    assert panel.index("step.href") < anchor
    companion = (Path(__file__).resolve().parents[2] / "companion" / "src"
                 / "ccsync_companion" / "settings_window.py").read_text(encoding="utf-8")
    assert 'Button("UNDO LAST FIX"' in companion
    assert 'Section("RESOLVE"' in companion


class _UnconfirmedFacts(dict):
    """Every fact the plan asks for, none of them confirmed: the plans print
    refusals instead of commands, and every href is still drawn."""
    def __missing__(self, key):
        return recovery.Fact(key, key)


def test_the_rollback_plans_create_step_names_a_page_the_dashboard_serves():
    """Owed round 2 (2026-09-25): the whole-tree rollback's "Create it again
    from the Projects page here" step carried href="/projects", which this
    dashboard does not serve (the JSON route is /api/v1/projects): [ GO ]
    was a 404. The project-folder page is /project-setup, keyed by a Resolve
    project name; a bare /project-setup 303s to the home page, so the step
    names the keyed URL and carries no [ GO ] rather than trade the 404 for
    a bounce to a page without the control."""
    steps = recovery._plan_whole_tree(_UnconfirmedFacts(), {})
    step = next(s for s in steps if s.title.startswith("Afterwards: put back"))
    assert step.href != "/projects"
    assert not step.href                       # a bare /project-setup is a redirect
    assert "/project-setup?resolve_project=" in step.body
    assert '"Create & link"' in step.body  # D8, UI port phase 7
    assert "Projects page" not in step.body
    setup = (TEMPLATES / "partials" / "project_setup_panel.html").read_text(encoding="utf-8")
    assert "[ CREATE &amp; LINK ]" in setup


def test_every_recovery_step_href_is_a_page_or_an_anchor_on_this_one():
    """No plan step may link a route this dashboard does not serve as a GET
    page: /fleet and /projects both shipped as 404s from this module."""
    from ccsync_dashboard import ui
    pages = {r.path for r in ui.router.routes
             if "GET" in getattr(r, "methods", set())}
    panel = (TEMPLATES / "partials" / "recovery.html").read_text(encoding="utf-8")
    for problem in recovery.PROBLEMS:
        for step in recovery.plan(problem.key, _UnconfirmedFacts())["steps"]:
            href = step["href"]
            if not href:
                continue
            if href.startswith("#"):
                assert f'id="{href[1:]}"' in panel, (problem.key, href)
                continue
            path = href.split("#", 1)[0].split("?", 1)[0]
            assert path in pages, (problem.key, href)
            assert path != "/project-setup", (problem.key, href)   # 303s home bare


# ------------------------------------------------------- bug-dash-diag-2

LATER = "2026-09-25T12:20:00+00:00"


def test_a_check_that_ran_again_records_its_recovery(conn):
    """The hunter's probe: check_failed/<kind> raised once, and the next pass
    ran that check fine. HEAD never wrote check_failed.ok, so `_is_open`
    answered True for ever and the next failure weeks later was a 'repeat'."""
    settings = _settings()
    dbmod.record_alert(conn, alerts.CHECK_FAILED.kind, "breaker_tripped", "", True, "", NOW)
    conn.commit()
    assert alerts._is_open(conn, alerts.CHECK_FAILED.kind, "breaker_tripped")
    result = alerts.deliver(conn, settings, [], LATER)
    assert result["recovered"] == 1
    assert not alerts._is_open(conn, alerts.CHECK_FAILED.kind, "breaker_tripped")
    subject, _text = alerts.compose_recovered(alerts.CHECK_FAILED.kind, "breaker_tripped")
    assert alerts.CHECK_FAILED.title in subject and "check_failed" not in subject


def test_a_check_still_failing_is_not_recovered(conn):
    settings = _settings()
    dbmod.record_alert(conn, alerts.CHECK_FAILED.kind, "breaker_tripped", "", True, "", NOW)
    conn.commit()
    still = [{"kind": alerts.CHECK_FAILED.kind, "severity": alerts.SEV_ERROR,
              "title": alerts.CHECK_FAILED.title, "subject": "breaker_tripped",
              "diagnosis": "x", "fix": "y"}]
    result = alerts.deliver(conn, settings, still, LATER)
    assert result["recovered"] == 0
    assert alerts._is_open(conn, alerts.CHECK_FAILED.kind, "breaker_tripped")


def test_a_scan_that_could_not_run_clears_nothing(conn):
    """The same line's other hole: with the scan context unbuildable the only
    finding is check_failed/"the whole scan", whose subject is no kind name,
    so HEAD counted every registry kind as checked and mailed every open alert
    as cleared by a scan that checked nothing."""
    settings = _settings()
    dbmod.record_alert(conn, "breaker_tripped", "ruskin/DESKTOP-1", "", True, "", NOW)
    conn.commit()
    whole = [{"kind": alerts.CHECK_FAILED.kind, "severity": alerts.SEV_ERROR,
              "title": alerts.CHECK_FAILED.title,
              "subject": "the whole scan", "diagnosis": "x", "fix": "y"}]
    result = alerts.deliver(conn, settings, whole, LATER)
    assert result["recovered"] == 0
    assert alerts._is_open(conn, "breaker_tripped", "ruskin/DESKTOP-1")


# ------------------------------------------------------- bug-dash-diag-4

def test_a_failed_migrate_is_retried_and_its_connection_closed(tmp_path, monkeypatch):
    """collector._loop assigned `conn` before db.migrate, so a migrate that
    raised left `conn` set: the retry never ran again and every cycle ran on a
    connection whose schema nobody had confirmed."""
    import sqlite3
    import time

    from ccsync_dashboard import collector as collector_mod
    from ccsync_dashboard.syncthing_client import SyncthingClient

    db_path = tmp_path / "c.db"
    settings = Settings(db_path=str(db_path), interval_prune=0.01)
    col = collector_mod.Collector(settings, client=SyncthingClient("", "", timeout=1))
    real_migrate = dbmod.migrate
    calls = {"n": 0}
    opened: list = []
    real_open = col._open_conn

    def tracking_open():
        c = real_open()
        opened.append(c)
        return c

    def flaky_migrate(c, *a, **kw):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise sqlite3.OperationalError("database is locked")
        return real_migrate(c, *a, **kw)

    monkeypatch.setattr(collector_mod, "DB_OPEN_RETRY_SECONDS", 0.05)
    monkeypatch.setattr(dbmod, "migrate", flaky_migrate)
    monkeypatch.setattr(col, "_open_conn", tracking_open)
    col.start()
    try:
        deadline = time.monotonic() + 10.0
        rows = 0
        while rows == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
            probe = dbmod.connect(db_path)
            try:
                rows = probe.execute(
                    "SELECT COUNT(*) FROM poll_runs WHERE kind='prune'").fetchone()[0]
            except sqlite3.OperationalError:
                rows = 0
            finally:
                probe.close()
    finally:
        col.stop()
    assert calls["n"] >= 3, "the failed migrate was never retried"
    assert rows > 0, "no cycle ran on a migrated connection"
    # The two connections whose migrate failed were closed, not kept.
    for c in opened[:2]:
        with pytest.raises(sqlite3.ProgrammingError):
            c.execute("SELECT 1")


# ------------------------------------------------------- bug-dash-ops-5

class _Inbox:
    """A search result whose message N has Message-ID <mN>."""

    def fetch(self, num, what):
        return "OK", [(b"1", f"Message-ID: <m{int(num)}>\r\n\r\n".encode())]


def test_handled_messages_do_not_use_up_the_poll_cap(conn):
    """25 messages in the window, the newest 20 already handled: HEAD took the
    newest 20 BEFORE the skip, so the five older unhandled replies were never
    read, poll after poll, until they left the SINCE window."""
    for i in range(6, 26):
        conn.execute("INSERT INTO triage_replies (message_id, received_at, verdict) "
                     "VALUES (?, ?, 'acted')", (f"<m{i}>", NOW))
    conn.commit()
    numbers = [str(i).encode() for i in range(1, 26)]
    picked = triage_mail._unhandled_numbers(conn, _Inbox(), numbers)
    assert picked == [b"1", b"2", b"3", b"4", b"5"]


def test_the_poll_cap_still_bounds_a_flood(conn):
    numbers = [str(i).encode() for i in range(1, 101)]
    picked = triage_mail._unhandled_numbers(conn, _Inbox(), numbers)
    # The newest ones, handled in the order they arrived.
    assert picked == numbers[-triage_mail.MAX_MESSAGES_PER_POLL:]


# ------------------------------------------------------- bug-dash-ops-6

def test_the_stored_report_never_holds_the_live_reference(conn):
    """The run row keeps only sha256(token); the stored copy of the mailed
    body carried `Reference: CCT-<token>` in full, served on the check's page
    and copied into every backup."""
    import json

    from ccsync_dashboard import triage
    token = "AbCdEfGhIjKlMnOpQrStUvWx"
    conn.execute("INSERT INTO triage_runs (id, started_at, status) "
                 "VALUES (1, ?, 'running')", (NOW,))
    body = f"[1] Resume\n\nReference: CCT-{token}   (valid until ...)\n"
    triage._finish(conn, 1, NOW, "ok", {"subject": "s", "body": body}, True, "")
    stored = conn.execute("SELECT report_json FROM triage_runs WHERE id=1").fetchone()[0]
    assert token not in stored
    assert "CCT-...UvWx" in json.loads(stored)["body"]
    # A row written before the fix is masked on the way out.
    conn.execute("INSERT INTO triage_runs (id, started_at, status, report_json) "
                 "VALUES (2, ?, 'ok', ?)",
                 (NOW, json.dumps({"subject": "s", "body": body})))
    shown = triage.report_text(conn, 2) or ""
    assert token not in shown and "[1] Resume" in shown


# ------------------------------------------------------- bug-dash-ops-7

def _gmail_site(tmp_path, token):
    import hashlib
    import json

    settings = Settings(db_path=str(tmp_path / "t.db"))
    c = dbmod.connect(settings.db_path)
    dbmod.migrate(c)
    alerts.set_settings(c, {
        "alerts_sink": "smtp", "alerts_smtp_host": "smtp.gmail.com",
        "alerts_smtp_user": "owner@example.com",
        "alerts_smtp_from": "owner@example.com",
        "alerts_smtp_to": "owner@example.com", "alerts_triage": "1",
        "alerts_triage_reply_to": "owner+ccsync@example.com"}, "owen")
    c.execute(
        "INSERT INTO triage_runs (id, started_at, finished_at, status, token_hash, "
        "token_expires_at, report_json, email_ok) VALUES (1, ?, ?, 'ok', ?, ?, ?, 1)",
        (NOW, NOW, hashlib.sha256(token.encode()).hexdigest(),
         "2026-09-26T12:00:00+00:00", json.dumps({"subject": "x"})))
    c.commit()
    return settings, c


def test_a_sender_written_results_header_is_not_the_receivers(tmp_path):
    """Google adds no Authentication-Results to mail that never leaves the
    Workspace, so the topmost header can be one the sender wrote. On a Gmail
    mailbox only a header naming mx.google.com is the receiver's."""
    token = "AbCdEfGhIjKlMnOpQrStUv"
    settings, c = _gmail_site(tmp_path, token)
    forged = "attacker.example; dkim=pass header.d=example.com"
    try:
        raw = _mail("<forged2@x>", body=f"do 1\n\nReference: CCT-{token}", ar=(forged,))
        out = triage_mail.handle_message(c, settings, raw, now=NOW,
                                         interpreter=lambda *a, **k: {"do": []})
        assert out["verdict"] == "refused"
        # The receiver's own header still passes.
        real = "mx.google.com; dkim=pass header.i=@example.com header.d=example.com"
        raw = _mail("<real@x>", body=f"do 1\n\nReference: CCT-{token}", ar=(real,))
        out = triage_mail.handle_message(c, settings, raw, now=NOW,
                                         interpreter=lambda *a, **k: {"do": []})
        assert out["verdict"] == "acted"
    finally:
        c.close()


def test_an_unknown_receiver_keeps_the_topmost_rule():
    msg = email.message_from_bytes(_mail(
        "<a@x>", ar=("mail.example.net; dkim=pass header.d=example.com",)))
    assert triage_mail.expected_authserv_id({"alerts_smtp_host": "smtp.example.net"}) == ""
    assert triage_mail.auth_results_pass(msg, "example.com", "")[0]


# ------------------------------------------------------- logic-sync-truth-5

def test_idle_lanes_with_uploads_owed_never_say_nothing_owed():
    """Lanes sit idle between passes while originals are still owed; HEAD
    said "Idle, nothing owed" from lane states alone."""
    row = {"lanes": [{"lane": "lane_a_video_up", "state": "idle", "chip": "green"}]}
    assert "nothing owed" not in health.fleet_headline(row)["text"]
    owed = health.fleet_headline({**row, "owed_files": 60})
    assert "60 files" in owed["text"] and "nothing owed" not in owed["text"]
    assert owed["level"] == health.HEADLINE_MUTED
    assert health.fleet_headline({**row, "owed_files": 0})["text"] == "Idle, nothing owed"


# ------------------------------------------------------- logic-admin-4 / -5

def _recovery_site(tmp_path, conn, live: dict[str, str], snap: dict[str, str]):
    projects = tmp_path / "projects"
    snaps = tmp_path / "snaps"
    (projects / "2026/One").mkdir(parents=True)
    for rel, text in live.items():
        (projects / "2026/One" / rel).write_text(text)
    (snaps / "s1/2026/One").mkdir(parents=True)
    for rel, text in snap.items():
        (snaps / "s1/2026/One" / rel).write_text(text)
    dbmod.upsert_project(conn, "one", "2026/One", "/x", NOW)
    conn.commit()
    return _settings(projects_dir=str(projects)), {recovery.ENV_SNAPSHOT_DIR: str(snaps)}


def _no_snap(*_a):
    return {"ok": False, "reason": "test"}


def test_a_preview_after_a_restore_says_it_was_already_restored(tmp_path, conn):
    settings, env = _recovery_site(tmp_path, conn, {"notes.txt": "live"},
                                   {"notes.txt": "live", "lost.wav": "gone"})
    first = recovery.preview_restore(settings, conn, "one", "s1", env=env)
    assert "already restored" not in first["note"]
    result = recovery.restore_into_quarantine(
        settings, conn, "one", "s1", "owen", env=env, now=NOW, snapshot_before=_no_snap)
    again = recovery.preview_restore(settings, conn, "one", "s1", env=env)
    # Still missing from the project (true: the copy is beside it) ...
    assert again["missing_count"] == 1
    # ... but the page now says where the earlier copy went.
    assert "already restored" in again["note"]
    assert result["where"] in again["note"]
    assert again["earlier_restores"][0]["where"] == result["where"]


def test_a_changed_only_restore_names_the_box_that_does_it(tmp_path, conn):
    settings, env = _recovery_site(tmp_path, conn, {"cut.drp": "short"},
                                   {"cut.drp": "the longer original"})
    preview = recovery.preview_restore(settings, conn, "one", "s1", env=env)
    assert preview["missing_count"] == 0 and preview["changed_count"] == 1
    with pytest.raises(recovery.RecoveryError) as refused:
        recovery.restore_into_quarantine(
            settings, conn, "one", "s1", "owen", env=env, now=NOW,
            snapshot_before=_no_snap)
    assert "also bring back the ones that are there but different" in str(refused.value)
    # With the box ticked it copies the one file.
    done = recovery.restore_into_quarantine(
        settings, conn, "one", "s1", "owen", include_changed=True, env=env, now=NOW,
        snapshot_before=_no_snap)
    assert done["files"] == 1


# =====================================================================
# Chunk 3 (2026-09-25): logic-alerts-4..8, ui-dash-admin-10, ui-copy-3.
# (logic-alerts-9 is chunk 2's bug-dash-ops-5; ui-dash-admin-13's server
# half is chunk 2's logic-admin-5 and its template half is d-ui's.)
# =====================================================================

# ------------------------------------------------------- logic-alerts-4

def _triage_run(tmp_path, monkeypatch, stdout: str | None):
    """One triage.run with the CLI answering `stdout` (None: the gate says
    no, so the fallback is sent). -> the one message handed to the sink."""
    import datetime as dt
    import subprocess

    from ccsync_dashboard import triage

    settings = Settings(db_path=str(tmp_path / "dash.db"))
    c = dbmod.connect(settings.db_path)
    dbmod.migrate(c)
    alerts.set_settings(c, {
        "alerts_sink": "smtp", "alerts_smtp_host": "smtp.gmail.com",
        "alerts_smtp_user": "owner@example.com", "alerts_smtp_from": "owner@example.com",
        "alerts_smtp_to": "owner@example.com", "alerts_triage": "1",
        "alerts_triage_hours": "6,18",
        "alerts_triage_reply_to": "owner+ccsync@example.com",
    }, "owen")
    c.execute("INSERT INTO machines (editor_username, machine, platform, first_seen, "
              "last_seen) VALUES ('ruskin', 'DESKTOP-1', 'windows', ?, ?)", (NOW, NOW))
    c.execute("INSERT INTO machine_state (editor_username, machine, reported_at, verified, "
              "platform, companion_version, breaker_tripped, guard_at) "
              "VALUES ('ruskin', 'DESKTOP-1', ?, 1, 'windows', '0.9.74', 1, ?)", (NOW, NOW))
    c.commit()
    c.close()
    monkeypatch.setattr(alerts, "_zone_or_utc", lambda _c: (dt.timezone.utc, "UTC"))
    sent: list[dict] = []

    def fake(conn, settings, subject, text, *, label="", reply_to=""):
        sent.append({"subject": subject, "text": text, "reply_to": reply_to})
        return {"ok": True, "sink": "smtp", "sent_to": "owner@example.com", "detail": "sent"}

    monkeypatch.setattr(alerts, "_transmit", fake)
    if stdout is None:
        monkeypatch.setattr(triage, "cli_gate", lambda conn, settings: ("", "no CLI here"))
    else:
        monkeypatch.setattr(triage, "cli_gate", lambda conn, settings: ("/x/claude", ""))
        monkeypatch.setattr(triage, "_spawn", lambda argv, prompt, cwd, env, timeout:
                            subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=""))
    triage.run(settings, now=NOW)
    [mail] = sent
    return mail


def _cli(report: dict) -> str:
    import json
    return json.dumps({"type": "result", "is_error": False, "result": json.dumps(report),
                       "modelUsage": {"claude-opus-5-5": {}}})


def test_an_all_clear_carries_no_reply_address(tmp_path, monkeypatch):
    """A reply to it could only be refused under `reference` and open a card
    telling the owner to reply to an email with nothing to reply with."""
    mail = _triage_run(tmp_path, monkeypatch, _cli(
        {"subject": "all clear", "headline": "Nothing needs you.", "all_clear": True,
         "findings": [], "actions": []}))
    assert "Reference: CCT-" not in mail["text"]
    assert mail["reply_to"] == ""


def test_the_fallback_carries_no_reply_address(tmp_path, monkeypatch):
    mail = _triage_run(tmp_path, monkeypatch, None)
    assert "could not run" in mail["subject"]
    assert mail["reply_to"] == ""


def test_a_report_with_actions_still_carries_the_reply_address(tmp_path, monkeypatch):
    mail = _triage_run(tmp_path, monkeypatch, _cli({
        "subject": "one computer stopped", "headline": "Proxy download stopped.",
        "all_clear": False,
        "findings": [{"title": "Proxy download stopped", "severity": "error",
                      "action_refs": [1]}],
        "actions": [{"n": 1, "action": "resume_breaker",
                     "params": {"editor": "ruskin", "machine": "DESKTOP-1"}}]}))
    assert "Reference: CCT-" in mail["text"]
    assert mail["reply_to"] == "owner+ccsync@example.com"


# ------------------------------------------------------- logic-alerts-5

def _inv_ctx(conn, tasks):
    from ccsync_dashboard import invariants
    return invariants.Ctx(conn, _settings(), NOW, snapshot_tasks_fn=lambda: tasks)


def test_a_task_on_the_dashboards_dataset_does_not_cover_the_tree(conn, monkeypatch):
    """The CR-227 shape: one task on the apps dataset, none on the footage.
    Invariant 9 read green while protection's tree line said MISSING."""
    from ccsync_dashboard import invariants
    monkeypatch.setenv("DASH_TREE_DATASET", "tank/Projects")
    monkeypatch.setenv("DASH_UPDATE_SNAPSHOT_DATASET", "tank/apps/ccsync-dashboard")
    out = invariants._check_snapshot_schedule(_inv_ctx(conn, [
        {"dataset": "tank/apps/ccsync-dashboard", "enabled": True}]))
    assert out.state == dbmod.INVARIANT_BROKEN
    [(subject, why)] = out.subjects
    assert subject == "tank/Projects" and "project tree" in why


def test_an_uncovered_dashboard_dataset_is_not_sent_to_snapshot_the_tree(conn, monkeypatch):
    from ccsync_dashboard import invariants
    monkeypatch.delenv("DASH_TREE_DATASET", raising=False)
    monkeypatch.setenv("DASH_UPDATE_SNAPSHOT_DATASET", "tank/apps/ccsync-dashboard")
    out = invariants._check_snapshot_schedule(_inv_ctx(conn, [
        {"dataset": "tank/Projects", "enabled": True}]))
    assert out.state == dbmod.INVARIANT_BROKEN
    [(subject, why)] = out.subjects
    assert subject == "tank/apps/ccsync-dashboard" and "dashboard's own data" in why
    fix = invariants.BY_KEY["snapshot_schedule"].fix
    assert "project tree" not in fix and "named below" in fix


def test_a_recursive_parent_covers_both_and_an_unnamed_tree_is_said(conn, monkeypatch):
    from ccsync_dashboard import invariants
    monkeypatch.setenv("DASH_TREE_DATASET", "tank/Projects")
    monkeypatch.setenv("DASH_UPDATE_SNAPSHOT_DATASET", "tank/apps")
    tasks = [{"dataset": "tank", "enabled": True, "recursive": True}]
    assert invariants._check_snapshot_schedule(_inv_ctx(conn, tasks)).state == \
        dbmod.INVARIANT_OK
    monkeypatch.delenv("DASH_TREE_DATASET")
    out = invariants._check_snapshot_schedule(_inv_ctx(conn, tasks))
    assert out.state == dbmod.INVARIANT_OK
    assert "DASH_TREE_DATASET" in out.detail and "not checked here" in out.detail


# ------------------------------------------------------- logic-alerts-6

def test_a_clean_pass_leaves_the_collector_panel_green(conn, monkeypatch):
    """The two registry skips made every pass "2 not checked here", which
    `collector_health` renders amber for ever."""
    from ccsync_dashboard import invariants

    def result(inv, state):
        return {"key": inv.key, "number": inv.number, "title": inv.title,
                "consequence": inv.consequence, "fix": inv.fix, "severity": inv.severity,
                "state": state, "detail": "d", "subjects": [], "truncated": False,
                "found": ()}

    def static_skip(inv):
        return bool(inv.skip_reason or inv.check is None)

    fake = [result(inv, dbmod.INVARIANT_NOT_CHECKED if static_skip(inv)
                   else dbmod.INVARIANT_OK) for inv in invariants.INVARIANTS]
    skipped = [r for r in fake if r["state"] == dbmod.INVARIANT_NOT_CHECKED]
    assert skipped
    monkeypatch.setattr(invariants, "evaluate", lambda ctx: [dict(r) for r in fake])
    out = invariants.run_cycle(conn, _settings(), NOW)
    assert out["note"] is None
    # The page's own counts still say they were not checked.
    assert out["counts"][dbmod.INVARIANT_NOT_CHECKED] == len(skipped)
    # A checkable invariant that could not answer THIS pass still shows.
    checkable = next(inv for inv in invariants.INVARIANTS if not static_skip(inv))
    fake2 = [dict(r, state=dbmod.INVARIANT_NOT_CHECKED) if r["key"] == checkable.key
             else r for r in fake]
    monkeypatch.setattr(invariants, "evaluate", lambda ctx: [dict(r) for r in fake2])
    assert invariants.run_cycle(conn, _settings(), NOW)["note"] == "1 not checked here"


# ------------------------------------------------------- logic-alerts-7

def test_a_hand_move_no_computer_held_closes_after_its_minimum_time(conn):
    import datetime as dt
    t0 = "2026-09-24T08:00:00+00:00"

    def at(hours):
        return (dt.datetime.fromisoformat(t0) + dt.timedelta(hours=hours)).isoformat()

    conn.execute(
        "INSERT INTO file_moves (from_slug, from_project_rel, from_rel, to_slug, "
        "to_project_rel, to_rel, requested_by, requested_at, source) "
        "VALUES ('p', 'Projects/P', 'a/clip.mov', 'p', 'Projects/P', 'b/clip.mov', "
        "'detected', ?, ?)", (t0, dbmod.FILE_MOVE_SOURCE_DETECTED))
    dbmod.notice(conn, "file_move_detected", "info", "Projects/P/b/clip.mov", now=t0)

    def still_open():
        return [r for r in dbmod.open_notices(conn) if r["kind"] == "file_move_detected"]

    notices._check_resolved(conn, None, at(1))
    assert still_open()                   # an FYI stays long enough to be read
    notices._check_resolved(conn, None, at(notices.FILE_MOVE_DETECTED_MIN_HOURS))
    assert not still_open()               # ... and not for the 7-day quiet period
    assert notices.FILE_MOVE_DETECTED_MIN_HOURS < notices.FILE_MOVE_DETECTED_QUIET_HOURS


# ------------------------------------------------------- logic-alerts-8

GB = 1024 ** 3


class _DiskCtx:
    def __init__(self, editors, full=frozenset(), base_only=()):
        self.editors = editors
        self.now = NOW
        self.base_only = set(base_only)
        self.full_tick_pairs = set(full) if full is not None else None

    def guard(self, e):
        return e.get("guard") or {}

    def name(self, s):
        return s


def _disk_row(machine, mode="remote"):
    return {"editor_username": "alex", "machine": machine, "mode": mode,
            "guard": {"disk_root_free_bytes": 10 * GB, "disk_root_total_bytes": 500 * GB,
                      "disk_at": NOW}}


def _subject(finding):
    return finding["subject"] if isinstance(finding, dict) else finding.subject


def test_a_computer_that_downloads_nothing_is_not_mailed_proxy_download_fears():
    rows = [_disk_row("Razer"), _disk_row("BASE", mode="base"), _disk_row("EDIT-PC")]
    found = alerts._check_disk_low(_DiskCtx(rows, full={("alex", "EDIT-PC")}))
    assert [_subject(f) for f in found] == ["alex/EDIT-PC"]
    # Could not read the ticks: the old behaviour (an editor's machine alerts).
    assert len(alerts._check_disk_low(_DiskCtx(rows[:1], full=None))) == 1


def test_the_disk_notice_for_a_computer_with_nothing_ticked_names_no_untick(conn):
    for machine in ("Razer", "EDIT-PC", "LAPTOP"):
        conn.execute(
            "INSERT INTO machine_state (editor_username, machine, reported_at, "
            "received_at, disk_root_free_bytes, disk_root_total_bytes, disk_at) "
            "VALUES ('alex', ?, ?, ?, ?, ?, ?)",
            (machine, NOW, NOW, 10 * GB, 500 * GB, NOW))
    dbmod.upsert_machine(conn, "alex", "EDIT-PC", NOW, machine_id="m-1")
    dbmod.add_selection(conn, "alex", "ff5", "owen", NOW, machine="EDIT-PC")
    # Review round: an upload-only tick downloads nothing, so LAPTOP lands in
    # the no-download branch while the admin can SEE a tick on it.
    dbmod.upsert_machine(conn, "alex", "LAPTOP", NOW, machine_id="m-2")
    dbmod.add_selection(conn, "alex", "ff5", "owen", NOW, machine="LAPTOP",
                        sync_mode=dbmod.SYNC_MODE_UPLOAD_ONLY)
    notices._check_machine_space(conn, None, NOW)
    cards = {r["subject"]: r for r in dbmod.open_notices(conn)
             if r["kind"] == "machine_disk_low"}
    assert set(cards) == {"alex/Razer", "alex/EDIT-PC", "alex/LAPTOP"}
    for quiet in ("alex/Razer", "alex/LAPTOP"):
        body = cards[quiet]["body"]
        assert "Untick" not in cards[quiet]["fix"]
        assert "Proxy" not in body
        # No claim the admin can see is false (LAPTOP has a tick), and no
        # promise that its syncing is safe: shared asset folders still come
        # down with no ticks at all (SPEC "Shared asset libraries").
        assert "nothing is ticked" not in body
        assert "not at risk" not in body
        assert "shared LUT library" in body
    assert "Untick" in cards["alex/EDIT-PC"]["fix"]


# ------------------------------------------------------- ui-dash-admin-10

def test_todays_local_date_east_of_utc_is_not_the_future(conn):
    """07:00 in Taiwan is 23:00 UTC the day before; the picker offers the
    local date."""
    now = "2026-09-24T23:00:00+00:00"
    key = sorted(protection.ACK_KEYS)[0]
    entry = protection.set_ack(conn, key, "2026-09-25", "owen", now=now)
    assert entry["date"] == "2026-09-25"
    with pytest.raises(ValueError, match="future"):
        protection.set_ack(conn, key, "2026-09-26", "owen", now=now)
    with pytest.raises(ValueError, match="future"):
        protection.set_ack(conn, key, "2027-09-25", "owen", now=now)


# ------------------------------------------------------- ui-copy-3

def _code(module) -> str:
    """Module source with comment lines dropped and adjacent string literals
    joined, so a label split across two literals is still one label."""
    lines = [ln for ln in Path(module.__file__).read_text(encoding="utf-8").splitlines()
             if not ln.strip().startswith("#")]
    return re.sub(r'"\s*\n\s*"', "", "\n".join(lines))


def test_the_named_controls_exist_under_the_names_the_copy_uses():
    """Every control these fixes name is a real one, and none sends the
    owner to a Settings page called Projects."""
    from ccsync_dashboard import collector, invariants
    corpus = "".join(p.read_text(encoding="utf-8") for p in TEMPLATES.rglob("*.html"))
    assert "[ ASK THIS COMPUTER WHY ]" in corpus
    assert '\\"Ask this computer why\\", then' in _code(alerts)  # D8
    assert "[ ASK WHY ]" not in _code(alerts)
    assert "[ UPDATE THE DASHBOARD ]" not in _code(notices)
    assert 'press \\"Update now\\" in the Dashboard panel' in _code(notices)
    upd = (TEMPLATES / "partials" / "admin_dashboard_update.html").read_text(encoding="utf-8")
    assert "[ DASHBOARD ]" in upd and "[ UPDATE NOW ]" in upd
    for module in (collector, invariants):
        assert "Settings, Projects" not in _code(module)
    # Review round: the tray's "Set up ... on the server" item shows only for
    # a Resolve project with no project_roots row (api.py report ingest ->
    # resolve_project_unmapped), which a project that lost its marker almost
    # never is, so neither marker fix may send the owner there; both say how
    # to put the file back, and the page address they cite is a real route.
    for module in (collector, invariants):
        assert "tray icon" not in _code(module)
        assert "Set up '" not in _code(module)
    marker_fix = invariants.BY_KEY["project_markers"].fix
    assert ".ccsync-project" in marker_fix and '"slug"' in marker_fix
    assert "/project/<id>" in marker_fix
    from ccsync_dashboard import ui
    assert any(getattr(r, "path", "") == "/project/{slug}" for r in ui.router.routes)


def test_a_damaged_marker_notice_says_how_to_put_the_file_back(conn, tmp_path):
    """ui-copy-3 review round: driven through the real provision pass. A
    served folder is told the exact id to write back (and that the server
    usually rewrites it); a folder Syncthing does not serve is told where the
    id is found, or to delete the file. Neither is sent to a tray item that
    only exists for a Resolve project with no project_roots row."""
    from fake_syncthing import FakeSyncthing

    from ccsync_dashboard.collector import Collector
    from ccsync_dashboard.syncthing_client import SyncthingClient

    projects = tmp_path / "projects"
    served = projects / "2025/FF4/Nuclear"
    stray = projects / "2025/FF4/Stray"
    for d in (served, stray):
        d.mkdir(parents=True)
        (d / ".ccsync-project").write_text("{not json", encoding="utf-8")
    (served / ".stfolder").mkdir()      # what makes the self-heal allowed
    fake = FakeSyncthing().start()

    def cards():
        return {r["subject"]: r for r in dbmod.open_notices(conn)
                if r["kind"] == "unreadable_project_marker"}

    try:
        settings = Settings(syncthing_url=fake.url, syncthing_api_key="k",
                            projects_dir=str(projects))
        c = Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))
        c._run_provision(conn)
        first = cards()
        # The fix's "the server usually writes a fresh marker by itself" is
        # true: the same pass rewrote it, and the next pass closes the card.
        c._run_provision(conn)
        second = cards()
    finally:
        fake.stop()
    assert set(first) == {"2025/FF4/Nuclear", "2025/FF4/Stray"}
    for card in first.values():
        assert "tray icon" not in card["fix"] and "Set up" not in card["fix"]
        assert ".ccsync-project" in card["fix"]
    assert '"slug" to "2025-ff4-nuclear"' in first["2025/FF4/Nuclear"]["fix"]
    stray_fix = first["2025/FF4/Stray"]["fix"]
    assert "/project/<id>" in stray_fix and "delete the damaged file" in stray_fix
    assert set(second) == {"2025/FF4/Stray"}


# ===================================================== OWED round (2026-09-25)
# Items other groups' builders left for d-diag's files.

# ------------------------------------------------------- ui-copy-5

def test_the_dashboard_names_the_diagnostics_route_the_companion_uses():
    """HEAD said "Settings > Help > Copy diagnostics" while the companion's
    ui_copy.DIAGNOSTICS (c-ui, this wave) says the HELP section and the
    button's own label. Read from the companion SOURCE: the dashboard venv
    does not carry the companion package."""
    src = (Path(__file__).resolve().parents[2] / "companion" / "src"
           / "ccsync_companion" / "ui_copy.py").read_text(encoding="utf-8")
    m = re.search(r'^DIAGNOSTICS = "([^"]+)"', src, re.M)
    assert m, "ui_copy.DIAGNOSTICS moved; this test reads it by name"
    assert health.COMPANION_DIAGNOSTICS_PATH == m.group(1)


def test_the_crash_alert_reads_with_the_new_route(conn):
    ctx = type("C", (), {})()
    ctx.editors = [{"editor_username": "ed", "machine": "LAP"}]
    ctx.guard = lambda e: {"crash_count": 2, "crash_newest": "x"}
    ctx.name = lambda who: who
    findings = alerts._check_crashes(ctx)
    assert findings
    fix = findings[0]["fix"]
    assert (f"Ask that editor to use {health.COMPANION_DIAGNOSTICS_PATH} on "
            "that computer") in fix
    assert "HELP > COPY DIAGNOSTICS FOR YOUR ADMIN" in fix


# ------------------------------------------------------- logic-ytdl-jobs-1

def test_a_queue_only_silent_computers_could_take_is_starved(conn, monkeypatch):
    """jobs.explain (d-cards, this wave) answers machines_not_reporting when
    every capable computer has gone quiet. HEAD's meaning map had no row for
    it, so six hours of work waiting on switched-off machines raised nothing."""
    from ccsync_dashboard import jobs as jobs_mod

    created = alerts._iso_minus(NOW, 9 * 3600)
    job_id = dbmod.create_job(conn, "whisper", {"src": ["tree", "a/b.mov"]},
                              now=created)
    conn.commit()
    monkeypatch.setattr(jobs_mod, "explain", lambda *_a, **_k: {
        "reason_code": jobs_mod.REASON_SILENT, "schedulable": False})
    ctx = type("C", (), {"conn": conn, "now": NOW})()
    findings = alerts._check_jobs_starved(ctx)
    assert len(findings) == 1
    assert "stopped reporting" in findings[0]["diagnosis"]
    assert f"job #{job_id}" in findings[0]["detail"]


def test_a_transient_reason_is_still_not_starved(conn, monkeypatch):
    from ccsync_dashboard import jobs as jobs_mod

    dbmod.create_job(conn, "whisper", {"src": ["tree", "a/b.mov"]},
                     now=alerts._iso_minus(NOW, 9 * 3600))
    conn.commit()
    monkeypatch.setattr(jobs_mod, "explain", lambda *_a, **_k: {
        "reason_code": jobs_mod.REASON_ALL_BUSY})
    ctx = type("C", (), {"conn": conn, "now": NOW})()
    assert alerts._check_jobs_starved(ctx) == []


# ------------------------------------------------------- logic-ytdl-jobs-5

def test_the_collectors_lease_sweep_uses_the_operators_cooldown(tmp_path):
    """DASH_JOBS_COOLDOWN_SECONDS = 0 means no cooldown. HEAD's _run_prune
    called db.prune without it, so the 120 s default parked the machine."""
    from ccsync_dashboard import collector as collector_mod

    settings = Settings(db_path=str(tmp_path / "p.db"),
                        session_secret="test-secret", jobs_cooldown_seconds=0)
    c = dbmod.connect(settings.db_path)
    dbmod.migrate(c)
    ago = alerts._iso_minus(NOW, 3600)
    dbmod.upsert_machine_state(c, "ed", "LAP", None, NOW)
    job = dbmod.create_job(c, "peaks", {"a": 1}, now=ago)
    assert dbmod.claim_job(c, job, "ed", "LAP", now=ago, lease_seconds=60)
    c.commit()
    coll = collector_mod.Collector(settings, client=object(),
                                   now_fn=lambda: NOW)
    coll._run_prune(c)
    c.commit()
    assert dbmod.get_job(c, job)["state"] == dbmod.JOB_QUEUED
    until, _reason = dbmod.machine_job_cooldown(c, "ed", "LAP")
    assert not until or until <= NOW
    c.close()


# ------------------------------------------------------- logic-admin-7

def _pinned_job(conn) -> int:
    job = dbmod.create_job(conn, "peaks", {"a": 1}, now=NOW)
    conn.execute("UPDATE jobs SET state=? WHERE id=?", (dbmod.JOB_PINNED, job))
    conn.commit()
    return job


def test_a_mailed_cancel_of_a_pinned_job_names_this_server(conn):
    from ccsync_dashboard import triage_actions

    job = _pinned_job(conn)
    said = triage_actions._x_cancel_job(conn, _settings(), {"job_id": job}, "owen")
    # HEAD: "the computer running it is the only thing that can end it".
    assert "this server's own worker" in said
    assert "computer running it" not in said
    assert "—" not in said and " -- " not in said


def test_a_mailed_cancel_of_a_held_job_still_names_the_computer(conn):
    from ccsync_dashboard import triage_actions

    dbmod.upsert_machine_state(conn, "ed", "LAP", None, NOW)
    job = dbmod.create_job(conn, "peaks", {"a": 1}, now=NOW)
    assert dbmod.claim_job(conn, job, "ed", "LAP", now=NOW, lease_seconds=600)
    conn.commit()
    said = triage_actions._x_cancel_job(conn, _settings(), {"job_id": job}, "owen")
    assert "the computer running it" in said


# ------------------------------------------------------- ui-copy-6

def test_the_slow_write_notice_has_no_typewriter_em_dash(conn):
    notices.record_slow_write(conn, "report from ed/LAP", 12.5, now=NOW)
    row = next(r for r in dbmod.open_notices(conn)
               if r["kind"] == notices.SLOW_WRITE_KIND)
    # HEAD: "Every other writer in that window -- a companion report, ...".
    assert " -- " not in str(row["body"])
    assert "(a companion report, the collector, a page)" in str(row["body"])
