"""Report-ingest and fleet-health hardening (resilience sweep 2026-08-28).

SYS-3   an undeclared report section is accepted, named in the log and recorded
SYNC-8  sync_guard.syncthing_supervisor is declared, stored and rendered
SYS-4   retention and eviction read the SERVER's clock; a wild client clock is
        clamped and its skew measured
UX-2b   an editor dot reddens on report SILENCE, independently of `behind`
DASH-16 a machine that ages out of machine_state still gets a LOST row
"""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import api as apimod
from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import health
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"
NOW = "2026-08-28T12:00:00+00:00"


def report_headers(editor="jsmith", token="sekrit"):
    return {"X-CCSync-Token": token,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def payload(**extra):
    body = {
        "editor_name": "JSmith",
        "machine": "EDIT-PC",
        "companion_version": "0.9.55",
        "reported_at": NOW,
        "lanes": [
            {"name": "lane_c_syncthing", "state": "idle", "queued": 0,
             "transferring": 0, "last_error": None, "last_sync": None, "detail": None},
        ],
    }
    body.update(extra)
    return body


@pytest.fixture
def app_env(tmp_path):
    db_path = tmp_path / "dash.db"
    app = create_app(Settings(db_path=str(db_path), report_token="sekrit",
                              session_secret=SECRET, admin_users=frozenset({"admin"})))
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        # The log-once-per-day dedupe is process-global, so a test must not
        # inherit another test's "already logged today".
        apimod._IGNORED_SECTION_LOGGED.clear()
        yield client, conn
        conn.close()


def machine_row(conn, editor="jsmith", machine="EDIT-PC"):
    return conn.execute(
        "SELECT * FROM machine_state WHERE editor_username=? AND machine=?",
        (editor, machine),
    ).fetchone()


# ------------------------------------------------------------------- SYS-3

def test_an_undeclared_top_level_section_is_accepted_and_recorded(app_env, caplog):
    client, conn = app_env
    with caplog.at_level("WARNING"):
        r = client.post("/api/v1/report",
                        json=payload(free_disk={"bytes": 1}), headers=report_headers())
    assert r.status_code == 200          # never a 422: B6's lesson
    assert any("does not read" in m and "free_disk" in m for m in caplog.messages)
    record = dbmod.ignored_report_sections(conn)
    assert record is not None
    assert "free_disk" in record["sections"]
    assert record["sections"]["free_disk"]["machines"] == ["jsmith/EDIT-PC"]


def test_an_undeclared_sync_guard_sub_key_is_recorded_under_its_namespace(app_env):
    client, conn = app_env
    client.post("/api/v1/report",
                json=payload(sync_guard={"tray_missing": True}),
                headers=report_headers())
    record = dbmod.ignored_report_sections(conn)
    assert sorted(record["sections"]) == ["sync_guard.tray_missing"]


def test_a_declared_section_is_never_reported_as_ignored(app_env):
    client, conn = app_env
    client.post("/api/v1/report", json=payload(sync_guard={
        "syncthing_supervisor": {"down_since": NOW, "attempts": 3,
                                 "last_error": "boom", "supervising": True},
        "crashes": {"count": 2, "newest": "20260828-lane"},
        "clock_skew_seconds": 4.0,
        "folders_unfiltered": ["p/One"],
        "sync_conflicts": {"count": 1, "paths": ["a.drp"]},
        "reporter": {"last_success_at": NOW, "last_status": "401",
                     "consecutive_failures": 0},
    }), headers=report_headers())
    assert dbmod.ignored_report_sections(conn) is None


def test_the_ignored_section_warning_is_logged_once_a_day_per_machine_and_key(
        app_env, caplog):
    client, _conn = app_env
    with caplog.at_level("WARNING"):
        for _ in range(4):
            client.post("/api/v1/report", json=payload(mystery={"a": 1}),
                        headers=report_headers())
    assert sum(1 for m in caplog.messages if "mystery" in m) == 1


def test_the_record_accumulates_machines_rather_than_replacing_them(app_env):
    client, conn = app_env
    dbmod.record_ignored_report_sections(conn, NOW, "a/PC-1", ["mystery"])
    dbmod.record_ignored_report_sections(conn, NOW, "b/PC-2", ["mystery"])
    conn.commit()
    entry = dbmod.ignored_report_sections(conn)["sections"]["mystery"]
    assert entry["machines"] == ["a/PC-1", "b/PC-2"]
    assert entry["reports"] == 2


def test_the_record_is_bounded_in_every_dimension(app_env):
    _client, conn = app_env
    dbmod.record_ignored_report_sections(
        conn, NOW, "a/PC", [f"k{i}" for i in range(dbmod.MAX_IGNORED_SECTIONS * 3)])
    sections = dbmod.ignored_report_sections(conn)["sections"]
    assert len(sections) == dbmod.MAX_IGNORED_SECTIONS
    for i in range(dbmod.MAX_IGNORED_SECTION_MACHINES * 2):
        dbmod.record_ignored_report_sections(conn, NOW, f"e{i}/PC", ["k0"])
    entry = dbmod.ignored_report_sections(conn)["sections"]["k0"]
    assert len(entry["machines"]) == dbmod.MAX_IGNORED_SECTION_MACHINES
    long_key = "x" * 500
    dbmod.record_ignored_report_sections(conn, NOW, "a/PC", [long_key])
    assert all(len(k) <= dbmod.MAX_IGNORED_SECTION_KEY_CHARS
               for k in dbmod.ignored_report_sections(conn)["sections"])


def test_an_unparseable_meta_row_is_no_banner_and_no_crash(app_env):
    _client, conn = app_env
    dbmod.meta_set(conn, dbmod.META_IGNORED_REPORT_SECTIONS, "{not json")
    assert dbmod.ignored_report_sections(conn) is None


# ------------------------------------------------------------------ SYNC-8

def test_the_supervisor_section_is_flattened_onto_machine_state(app_env):
    client, conn = app_env
    client.post("/api/v1/report", json=payload(sync_guard={
        "syncthing_supervisor": {
            "down_since": "2026-08-28T06:00:00+00:00", "attempts": 3,
            "last_error": "restart refused", "supervising": True},
    }), headers=report_headers())
    row = machine_row(conn)
    assert row["supervisor_down_since"] == "2026-08-28T06:00:00+00:00"
    assert row["supervisor_attempts"] == 3
    assert row["supervisor_last_error"] == "restart refused"
    assert row["supervisor_supervising"] == 1
    guard = dbmod.fetch_sync_guard_map(conn)[("jsmith", "EDIT-PC")]
    assert guard["supervisor_attempts"] == 3
    assert guard["supervisor_supervising"] is True


def test_an_engine_that_comes_back_clears_the_incident(app_env):
    """The supervisor section is empty-when-healthy, so its ABSENCE from a
    guard-bearing report is how "the engine is up" is spelled. A COALESCE
    would have left "down since Tuesday" on the grid for ever."""
    client, conn = app_env
    client.post("/api/v1/report", json=payload(sync_guard={
        "syncthing_supervisor": {"down_since": NOW, "attempts": 1}}),
        headers=report_headers())
    assert machine_row(conn)["supervisor_down_since"] == NOW
    client.post("/api/v1/report", json=payload(sync_guard={"halt": {"active": False}}),
                headers=report_headers())
    assert machine_row(conn)["supervisor_down_since"] is None


def test_a_report_with_no_guard_section_at_all_holds_the_incident(app_env):
    client, conn = app_env
    client.post("/api/v1/report", json=payload(sync_guard={
        "syncthing_supervisor": {"down_since": NOW, "attempts": 1}}),
        headers=report_headers())
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    assert machine_row(conn)["supervisor_down_since"] == NOW


def test_a_companion_too_old_to_send_supervising_is_none_not_false(app_env):
    client, conn = app_env
    client.post("/api/v1/report", json=payload(sync_guard={
        "syncthing_supervisor": {"down_since": NOW}}), headers=report_headers())
    guard = dbmod.fetch_sync_guard_map(conn)[("jsmith", "EDIT-PC")]
    assert guard["supervisor_supervising"] is None


def test_the_other_new_guard_counters_are_stored_and_cleared(app_env):
    client, conn = app_env
    client.post("/api/v1/report", json=payload(sync_guard={
        "crashes": {"count": 2, "newest": "20260828-lane_b.json"},
        "folders_unfiltered": ["Projects/One", "Projects/Two"],
        "sync_conflicts": {"count": 4, "paths": ["a.drp"]},
    }), headers=report_headers())
    row = machine_row(conn)
    assert row["crash_count"] == 2
    assert row["crash_newest"] == "20260828-lane_b.json"
    assert row["folders_unfiltered"] == 2
    assert "Projects/One" in row["folders_unfiltered_names"]
    assert row["sync_conflicts"] == 4
    # every one of them is cleared by a guard-bearing report that omits it
    client.post("/api/v1/report", json=payload(sync_guard={"halt": {"active": False}}),
                headers=report_headers())
    row = machine_row(conn)
    assert row["crash_count"] is None and row["folders_unfiltered"] is None
    assert row["sync_conflicts"] is None


def test_an_oversize_guard_section_truncates_instead_of_422ing_the_report(app_env):
    """sync_guard is not one of ReportIn's tolerant sections, so a raising cap
    here would take the lanes, transfers and presence data down with it."""
    client, conn = app_env
    r = client.post("/api/v1/report", json=payload(sync_guard={
        "folders_unfiltered": [f"f{i}" for i in range(500)],
        "syncthing_supervisor": {"down_since": NOW, "last_error": "e" * 5000},
    }), headers=report_headers())
    assert r.status_code == 200
    row = machine_row(conn)
    assert row["folders_unfiltered"] == 64
    assert len(row["supervisor_last_error"]) == 1000


# ------------------------------------------------------------------- SYS-4

def test_clamp_reported_at_measures_skew_and_leaves_a_sane_clock_alone():
    stored, skew, clamped = dbmod.clamp_reported_at(
        "2026-08-28T11:59:00+00:00", "2026-08-28T12:00:00+00:00")
    assert stored == "2026-08-28T11:59:00+00:00"
    assert skew == pytest.approx(-60.0)      # negative = the client is BEHIND
    assert clamped is False


def test_clamp_reported_at_refuses_a_wild_clock_as_an_ordering_key():
    stored, skew, clamped = dbmod.clamp_reported_at(
        "2098-01-01T00:00:00+00:00", "2026-08-28T12:00:00+00:00")
    assert stored == "2026-08-28T12:00:00+00:00"
    assert skew > dbmod.CLOCK_SKEW_CLAMP_SECONDS and clamped is True


def test_an_unreadable_client_timestamp_is_not_reported_as_no_skew():
    stored, skew, clamped = dbmod.clamp_reported_at("yesterday", NOW)
    assert (stored, skew, clamped) == (None, None, True)


def test_the_report_stores_both_clocks_and_the_skew(app_env):
    client, conn = app_env
    # An hour behind THIS server's clock, whatever this server's clock says.
    claim = (dbmod.parse_iso(dbmod.utcnow_iso()) - dt.timedelta(hours=1)).isoformat()
    client.post("/api/v1/report", json=payload(reported_at=claim),
                headers=report_headers())
    row = machine_row(conn)
    assert row["client_reported_at"] == claim
    assert row["received_at"] is not None
    assert row["clock_skew_seconds"] == pytest.approx(-3600, abs=30)


def test_retention_reads_the_server_clock_not_the_clients(app_env):
    """A machine 40 days behind real time used to be DELETED from the fleet
    grid on every prune while reporting perfectly (SYS-4)."""
    _client, conn = app_env
    now = dbmod.utcnow_iso()
    stale_claim = (dbmod.parse_iso(now) - dt.timedelta(days=40)).isoformat()
    dbmod.upsert_machine_state(conn, "jsmith", "SLOW-CLOCK-PC", None, now,
                               client_reported_at=stale_claim)
    dbmod.prune(conn, now)
    assert machine_row(conn, machine="SLOW-CLOCK-PC") is not None
    # ...and a genuinely silent machine still ages out
    old = (dbmod.parse_iso(now) - dt.timedelta(days=40)).isoformat()
    dbmod.upsert_machine_state(conn, "jsmith", "DEAD-PC", None, old)
    dbmod.prune(conn, now)
    assert machine_row(conn, machine="DEAD-PC") is None


def test_eviction_orders_on_the_server_clock(app_env):
    """A machine claiming 2098 must not pin itself as "most recent" for ever
    and evict its owner's genuinely live computers."""
    _client, conn = app_env
    now = dbmod.utcnow_iso()
    dbmod.upsert_machine_state(conn, "jsmith", "LIAR-PC", None,
                               (dbmod.parse_iso(now) - dt.timedelta(hours=6)).isoformat(),
                               client_reported_at="2098-01-01T00:00:00+00:00")
    for i in range(dbmod.MAX_MACHINES_PER_EDITOR):
        dbmod.upsert_machine_state(conn, "jsmith", f"LIVE-{i:02d}", None, now)
    remaining = {r["machine"] for r in conn.execute(
        "SELECT machine FROM machine_state WHERE editor_username='jsmith'")}
    assert "LIAR-PC" not in remaining
    assert len(remaining) == dbmod.MAX_MACHINES_PER_EDITOR


# ------------------------------------------------------------------- UX-2b

def _status(**kw):
    base = dict(completion=100.0, need_items=0, connected=True,
                last_connected_at=NOW, completion_updated_at=None,
                syncthing_reachable=False, lanes=(), now=NOW)
    base.update(kw)
    return health.editor_status(**base)


def test_a_caught_up_machine_that_stopped_reporting_is_not_green():
    """An editor who signs out, quits, or clicks WIRED TO THE SERVER while
    caught up has behind=False, so no other branch fires."""
    fresh = "2026-08-28T11:59:00+00:00"
    amber = "2026-08-28T11:30:00+00:00"           # 30 min
    red = "2026-08-28T03:00:00+00:00"             # 9 h
    assert _status(last_report_at=fresh) == health.GREEN
    assert _status(last_report_at=amber) == health.AMBER
    assert _status(last_report_at=red) == health.RED


def test_a_device_with_no_companion_row_is_not_reddened_by_freshness():
    assert _status(last_report_at=None) == health.GREEN
    assert health.report_freshness(None, NOW) == (health.GREEN, None)


def test_the_freshness_reason_names_the_last_report_time():
    colour, reason = health.report_freshness("2026-08-28T03:00:00+00:00", NOW)
    assert colour == health.RED
    assert "2026-08-28T03:00:00+00:00" in reason


def test_an_unreadable_report_time_is_amber_not_green():
    colour, reason = health.report_freshness("not a timestamp", NOW)
    assert colour == health.AMBER and reason


def test_the_thresholds_are_the_ones_the_finding_named():
    assert health.STALE_EDITOR_AMBER_SECONDS == 3 * health.STALE_REPORT_SECONDS
    assert health.STALE_EDITOR_RED_SECONDS == 6 * 3600


def test_a_frozen_green_lane_row_does_not_keep_the_fleet_row_green(app_env):
    """The grid row's dot is worst(lane chips), and a machine that stopped
    reporting has its last states frozen mid-green."""
    client, conn = app_env
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    conn.execute("UPDATE lane_report_current SET received_at=? WHERE machine='EDIT-PC'",
                 ("2026-08-20T00:00:00+00:00",))
    conn.execute("UPDATE machine_state SET received_at=? WHERE machine='EDIT-PC'",
                 ("2026-08-20T00:00:00+00:00",))
    conn.commit()
    view = apimod.build_editors_view(conn)
    row = next(e for e in view["editors"] if e["machine"] == "EDIT-PC")
    assert row["status"] == health.RED
    assert "no report since" in row["status_reason"]


# ------------------------------------------------------------------ DASH-16

def test_a_machine_whose_state_row_aged_out_still_gets_a_lost_row(app_env):
    client, conn = app_env
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    dbmod.add_selection(conn, "jsmith", "2026/FF5", "admin", dbmod.utcnow_iso(),
                        machine="EDIT-PC")
    long_ago = (dbmod.parse_iso(dbmod.utcnow_iso()) - dt.timedelta(days=45)).isoformat()
    conn.execute("UPDATE machines SET last_seen=? WHERE machine='EDIT-PC'", (long_ago,))
    conn.execute("UPDATE machine_state SET received_at=? WHERE machine='EDIT-PC'",
                 (long_ago,))
    conn.execute("UPDATE lane_report_current SET received_at=? WHERE machine='EDIT-PC'",
                 (long_ago,))
    conn.commit()
    dbmod.prune(conn, dbmod.utcnow_iso())      # machine_state + lane rows go
    conn.commit()
    view = apimod.build_editors_view(conn)
    assert not any(e["machine"] == "EDIT-PC" for e in view["editors"])
    lost = view["lost_machines"]
    assert [m["machine"] for m in lost] == ["EDIT-PC"]
    assert lost[0]["projects"] == ["2026/FF5"]


def test_a_machine_that_is_still_on_the_grid_is_not_also_listed_as_lost(app_env):
    client, conn = app_env
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    long_ago = (dbmod.parse_iso(dbmod.utcnow_iso()) - dt.timedelta(days=45)).isoformat()
    conn.execute("UPDATE machines SET last_seen=? WHERE machine='EDIT-PC'", (long_ago,))
    conn.commit()
    view = apimod.build_editors_view(conn)
    assert any(e["machine"] == "EDIT-PC" for e in view["editors"])
    assert view["lost_machines"] == []


def test_a_recently_seen_machine_is_never_lost(app_env):
    client, conn = app_env
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    assert dbmod.lost_machines(conn, dbmod.utcnow_iso()) == []


# ------------------------------------------------------------------- SYS-1
#
# The liveness contract's ingest half: the token is stored, and
# progress_token_since is the SERVER's received_at of the first report that
# carried the CURRENT token -- so a companion re-sending the same token every
# 30 s cannot reset the clock on its own stall (CR-91b).

def lane_payload(**extra):
    body = {"name": "lane_a_video_up", "state": "syncing", "queued": 3,
            "transferring": 1, "last_error": None, "last_sync": None,
            "detail": None}
    body.update(extra)
    return body


def lane_row(conn, lane="lane_a_video_up", machine="EDIT-PC"):
    return conn.execute(
        "SELECT * FROM lane_report_current WHERE machine=? AND lane=?",
        (machine, lane),
    ).fetchone()


def test_the_lane_token_and_state_since_are_stored(app_env):
    client, conn = app_env
    client.post("/api/v1/report", json=payload(lanes=[lane_payload(
        progress_token="120:4:2026/FF5", state_since=NOW)]),
        headers=report_headers())
    row = lane_row(conn)
    assert row["progress_token"] == "120:4:2026/FF5"
    assert row["state_since"] == NOW
    assert row["progress_token_since"]


def test_the_token_stamp_only_advances_when_the_token_CHANGES(app_env):
    """The heart of it: a companion re-sending the same token every 30 s must
    not be able to reset the clock on its own stall. Back-dated by hand
    because four reports in one test land inside the same second."""
    client, conn = app_env
    client.post("/api/v1/report", json=payload(lanes=[lane_payload(
        progress_token="120:4:2026/FF5")]), headers=report_headers())
    stuck_since = (dbmod.parse_iso(dbmod.utcnow_iso())
                   - dt.timedelta(hours=2)).isoformat()
    conn.execute("UPDATE lane_report_current SET progress_token_since=?",
                 (stuck_since,))
    conn.commit()
    # the same token again, twice: nothing moved on that machine
    for _ in range(2):
        client.post("/api/v1/report", json=payload(lanes=[lane_payload(
            progress_token="120:4:2026/FF5")]), headers=report_headers())
        assert lane_row(conn)["progress_token_since"] == stuck_since
    # ...and a token that changed re-stamps it to now
    client.post("/api/v1/report", json=payload(lanes=[lane_payload(
        progress_token="900:9:2026/FF5")]), headers=report_headers())
    assert lane_row(conn)["progress_token_since"] > stuck_since


def test_a_report_with_no_token_clears_the_stamp_rather_than_keeping_it(app_env):
    client, conn = app_env
    client.post("/api/v1/report", json=payload(lanes=[lane_payload(
        progress_token="1:1:x")]), headers=report_headers())
    assert lane_row(conn)["progress_token_since"]
    client.post("/api/v1/report", json=payload(lanes=[lane_payload()]),
                headers=report_headers())
    assert lane_row(conn)["progress_token_since"] is None


def test_a_stalled_lane_reddens_the_fleet_row_and_says_why(app_env):
    """The whole finding, end to end: reports keep flowing, the lane says
    `syncing` with no error, and the row used to be amber for ever."""
    client, conn = app_env
    client.post("/api/v1/report", json=payload(lanes=[lane_payload(
        progress_token="1:1:x")]), headers=report_headers())
    stuck_since = (dbmod.parse_iso(dbmod.utcnow_iso())
                   - dt.timedelta(hours=2)).isoformat()
    conn.execute("UPDATE lane_report_current SET progress_token_since=?",
                 (stuck_since,))
    conn.commit()
    view = apimod.build_editors_view(conn)
    row = next(e for e in view["editors"] if e["machine"] == "EDIT-PC")
    assert row["status"] == health.RED
    assert "no progress for" in row["status_reason"]
    assert any("no progress for" in (l["chip_reason"] or "") for l in row["lanes"])


def test_the_machines_own_rotation_sets_the_budget(app_env):
    """A rig on a one-hour rotation is not stalled at 40 minutes."""
    client, conn = app_env
    client.post("/api/v1/report",
                json=payload(lanes=[lane_payload(progress_token="1:1:x")],
                             sync_guard={"rotation_seconds": 3600}),
                headers=report_headers())
    assert machine_row(conn)["rotation_seconds"] == 3600
    stuck_since = (dbmod.parse_iso(dbmod.utcnow_iso())
                   - dt.timedelta(minutes=40)).isoformat()
    conn.execute("UPDATE lane_report_current SET progress_token_since=?",
                 (stuck_since,))
    conn.commit()
    view = apimod.build_editors_view(conn)
    row = next(e for e in view["editors"] if e["machine"] == "EDIT-PC")
    assert row["status"] == health.AMBER


def test_the_companions_own_kill_record_is_stored_and_clears(app_env):
    client, conn = app_env
    client.post("/api/v1/report", json=payload(sync_guard={
        "stalled": {"lane": "A", "seconds": 1800, "killed": True, "at": NOW}}),
        headers=report_headers())
    row = machine_row(conn)
    assert row["stalled_lane"] == "A" and row["stalled_seconds"] == 1800
    assert row["stalled_killed"] == 1 and row["stalled_at"] == NOW
    guard = dbmod.fetch_sync_guard_map(conn)[("jsmith", "EDIT-PC")]
    assert guard["stalled_killed"] is True
    client.post("/api/v1/report", json=payload(sync_guard={"halt": {"active": False}}),
                headers=report_headers())
    assert machine_row(conn)["stalled_lane"] is None


# ------------------------------------------------------------------- SYS-5

def test_the_disk_section_is_flattened_and_chipped(app_env):
    client, conn = app_env
    gb = 1024 ** 3
    client.post("/api/v1/report", json=payload(sync_guard={"disk": {
        "root_free_bytes": 18 * gb, "root_total_bytes": 500 * gb,
        "system_free_bytes": 4 * gb, "at": NOW}}), headers=report_headers())
    row = machine_row(conn)
    assert row["disk_root_free_bytes"] == 18 * gb
    assert row["disk_root_total_bytes"] == 500 * gb
    assert row["disk_system_free_bytes"] == 4 * gb
    assert row["disk_at"] == NOW
    view = apimod.build_editors_view(conn)
    entry = next(e for e in view["editors"] if e["machine"] == "EDIT-PC")
    assert entry["guard"]["disk_status"] == health.RED
    assert round(entry["guard"]["disk_percent"]) == 4


def test_a_light_report_in_between_does_not_blank_the_last_free_space(app_env):
    """The measurement rides HEAVY ticks only. A guard-bearing light report
    must not take the DISK chip off a nearly-full machine."""
    client, conn = app_env
    gb = 1024 ** 3
    client.post("/api/v1/report", json=payload(sync_guard={"disk": {
        "root_free_bytes": 9 * gb, "root_total_bytes": 500 * gb, "at": NOW}}),
        headers=report_headers())
    client.post("/api/v1/report", json=payload(sync_guard={"halt": {"active": False}}),
                headers=report_headers())
    assert machine_row(conn)["disk_root_free_bytes"] == 9 * gb


def test_the_new_guard_sub_sections_are_declared_not_ignored(app_env):
    """SYS-3's mechanism, applied before the companion ships them: an
    undeclared sub-key is accepted, recorded and read by nobody."""
    client, conn = app_env
    client.post("/api/v1/report", json=payload(sync_guard={
        "disk": {"root_free_bytes": 1, "root_total_bytes": 2},
        "stalled": {"lane": "B", "seconds": 1},
        "restarts": {"sequencer": {"count_24h": 2, "last_error": "OSError"}},
        "rotation_seconds": 600,
    }), headers=report_headers())
    recorded = dbmod.ignored_report_sections(conn)
    assert recorded is None or not [
        k for k in recorded["sections"]
        if k.startswith("sync_guard.") and k.split(".", 1)[1] in {
            "disk", "stalled", "restarts", "rotation_seconds"}
    ]


# ------------------------------------------------------------------- UX-1

def _project_with_proxies(conn, slug, proxy_bytes):
    pid = dbmod.upsert_project(conn, slug, slug, "/mnt/tank/" + slug, NOW)
    conn.execute("""INSERT INTO nas_inventory_state
                      (project_id, bytes_proxies, n_proxies, walked_at)
                    VALUES (?, ?, ?, ?)""", (pid, proxy_bytes, 40, NOW))
    conn.commit()


def test_a_tick_warns_about_a_project_that_will_not_fit(app_env):
    client, conn = app_env
    gb = 1024 ** 3
    client.post("/api/v1/report", json=payload(sync_guard={"disk": {
        "root_free_bytes": 180 * gb, "root_total_bytes": 500 * gb, "at": NOW}}),
        headers=report_headers())
    _project_with_proxies(conn, "2026/FF5/Animals", 620 * gb)
    warning = apimod.tick_capacity_warning(conn, "jsmith", "2026/FF5/Animals")
    assert warning is not None
    assert "620 GB of proxies" in warning and "180 GB free" in warning
    assert "EDIT-PC" in warning


def test_a_project_the_collector_has_never_walked_warns_about_nothing(app_env):
    client, conn = app_env
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    dbmod.upsert_project(conn, "2026/FF5/Empty", "2026/FF5/Empty", "/mnt/tank/y", NOW)
    conn.commit()
    assert apimod.tick_capacity_warning(conn, "jsmith", "2026/FF5/Empty") is None


def test_the_tick_route_answers_with_the_warning_and_still_ticks(app_env):
    client, conn = app_env
    gb = 1024 ** 3
    client.post("/api/v1/report", json=payload(sync_guard={"disk": {
        "root_free_bytes": 30 * gb, "root_total_bytes": 500 * gb, "at": NOW}}),
        headers=report_headers())
    _project_with_proxies(conn, "ff5-big", 400 * gb)
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "admin"))
    r = client.put("/api/v1/selection/jsmith/ff5-big")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changed"] is True                    # it REFUSES NOTHING
    assert "400 GB of proxies" in (body["warning"] or "")


# ------------------------------------------- REL-3 / CYT-7 (sweep 2026-09-04)
#
# Two sync_guard sub-sections whose columns (v48) and whose readers landed in
# the same wave as their ingest. A section that is declared, stored and never
# read is the shape of SYS-3; one that is READ from a column nothing writes is
# a check that can never fire, which is worse, because the page says it is
# green.

def test_a_refused_offer_lands_in_the_v48_columns(app_env):
    client, conn = app_env
    client.post("/api/v1/report", json=payload(sync_guard={"upgrade": {
        "version": "0.9.66", "attempts": 0,
        "refused_version": "0.9.67",
        "refused_reason": "release signature rejected",
        "refused_at": NOW}}), headers=report_headers())
    row = conn.execute(
        "SELECT upgrade_refused_version, upgrade_refused_reason, "
        "       upgrade_refused_at FROM machine_state "
        " WHERE editor_username='jsmith' AND machine='EDIT-PC'").fetchone()
    assert row["upgrade_refused_version"] == "0.9.67"
    assert row["upgrade_refused_reason"] == "release signature rejected"
    assert row["upgrade_refused_at"] == NOW
    # ...and the LATCH rule: the next report with no refusal in it clears
    # them, so [ REFUSING 0.9.67 ] comes off the page by itself once the
    # admin has installed that build by hand.
    client.post("/api/v1/report", json=payload(sync_guard={"upgrade": {
        "version": "0.9.67", "attempts": 0}}), headers=report_headers())
    row = conn.execute(
        "SELECT upgrade_refused_version FROM machine_state "
        " WHERE editor_username='jsmith' AND machine='EDIT-PC'").fetchone()
    assert row["upgrade_refused_version"] is None


def test_a_report_with_no_guard_leaves_a_refusal_alone(app_env):
    """A companion too old to send a guard section has SAID NOTHING, which is
    not the same as "nothing is refused"."""
    client, conn = app_env
    client.post("/api/v1/report", json=payload(sync_guard={"upgrade": {
        "refused_version": "0.9.67", "refused_reason": "below the floor",
        "refused_at": NOW}}), headers=report_headers())
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    row = conn.execute(
        "SELECT upgrade_refused_version FROM machine_state "
        " WHERE editor_username='jsmith' AND machine='EDIT-PC'").fetchone()
    assert row["upgrade_refused_version"] == "0.9.67"


def test_the_yt_dlp_verdict_is_stored_and_cleared(app_env):
    client, conn = app_env
    client.post("/api/v1/report", json=payload(sync_guard={"ytdlp": {
        "version": "2026.07.04", "action": "stale", "ok": True, "stale": True,
        "age_days": 43, "message": "it could not update itself",
        "checked_at": NOW}}), headers=report_headers())
    stored = dbmod.meta_get_json(conn, f"{apimod.YTDLP_META_PREFIX}jsmith/EDIT-PC")
    assert stored["stale"] is True and stored["age_days"] == 43
    # An ABSENT section deletes it: a companion that stopped sending one has
    # stopped knowing, and a stale verdict from March is worse than silence.
    client.post("/api/v1/report", json=payload(sync_guard={"upgrade": {}}),
                headers=report_headers())
    assert dbmod.meta_get_json(
        conn, f"{apimod.YTDLP_META_PREFIX}jsmith/EDIT-PC") is None


def test_neither_section_is_reported_as_ignored(app_env):
    """Declared, not merely allowed as an extra: an undeclared sub-key is
    accepted, named in the ignored-sections banner and then dropped, which is
    where sync_guard.syncthing_supervisor spent months."""
    body = apimod.ReportIn(**payload(sync_guard={
        "ytdlp": {"action": "checked", "ok": True},
        "upgrade": {"refused_version": "0.9.67", "refused_reason": "nope"},
    }))
    assert apimod.undeclared_report_sections(body) == []
