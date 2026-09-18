"""The 2026-09-18 fix pass, dashboard group, SECOND builder.

The mediums the first builder left (dash-collector-alerts-1, res-fleet-4,
proxy-tiers-4's dashboard half, proxy-tiers-3's alert row), the lows it could
not reach, and the second half of live-1 that the coordinator found still
mailing after the first half landed.

Every test here fails on the tree as the first builder left it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import alerts
from ccsync_dashboard import auth
from ccsync_dashboard import collector as collector_mod
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import mount_status
from ccsync_dashboard.app import create_app
from ccsync_dashboard.collector import InventoryWalk
from ccsync_dashboard.settings import Settings

SECRET = "a-test-session-secret-of-length"
NOW = "2026-09-18T12:00:00+00:00"
A_WEEK_AGO = "2026-09-11T16:26:15+00:00"
AN_HOUR_AGO = "2026-09-18T11:00:00+00:00"

DRONE = "2026/Base Drone"
ANIMALS = "2026/FF5/Animals"
D_SLUG = "2026-base-drone"
A_SLUG = "2026-ff5-animals"


def walk(slug, project_rel, old, new):
    return InventoryWalk(slug=slug, project_rel=project_rel, old=list(old), new=list(new))


def orig(rel, size=100, mtime=111):
    return (rel, "original", size, mtime)


@pytest.fixture
def conn(tmp_path):
    connection = dbmod.connect(tmp_path / "dash.db")
    dbmod.migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def env(tmp_path):
    """A live app with its collector stopped, the test_alerts.py pattern."""
    app = create_app(Settings(
        db_path=str(tmp_path / "dash.db"), report_token="sekrit",
        session_secret=SECRET, admin_users=frozenset({"owen"}),
    ))
    with TestClient(app) as client:
        client.app.state.collector.stop()
        connection = dbmod.connect(tmp_path / "dash.db")
        connection.execute("DELETE FROM alert_log")
        connection.execute("DELETE FROM notices")
        connection.commit()
        try:
            yield client, connection, app.state.settings
        finally:
            connection.close()


def report_headers(editor="ruskin", token="sekrit"):
    return {"X-CCSync-Token": token,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def report(machine="DESKTOP-LQQ41TC", guard=None, lanes=None, **extra):
    body = {
        "editor_name": "Ruskin", "machine": machine,
        "companion_version": "0.9.74", "reported_at": NOW,
        "lanes": lanes if lanes is not None else [
            {"name": "lane_a_rclone_up", "state": "idle", "queued": 0,
             "transferring": 0, "last_error": None, "last_sync": None},
        ],
    }
    if guard is not None:
        body["sync_guard"] = guard
    body.update(extra)
    return body


# ---------------------------------------------------------------------------
# dash-collector-alerts-1: the two halves of a move in two different passes
# ---------------------------------------------------------------------------


def test_a_move_between_two_projects_is_paired_across_two_passes(conn):
    """The walk is WINDOWED (8 projects a cycle through a rotating cursor), so
    on a fleet with more than 8 active projects the vanish in project A and
    the appearance in project B fall in different passes - and
    `replace_nas_media` has already destroyed A's old rows by the time B is
    walked. Before this the move could never be detected: every machine
    holding those clips treated them as deletions, lane A put them back at the
    old path and lane B's breaker parked proxy download (CR-267a again)."""
    collector = collector_mod.Collector(Settings(db_path=":memory:"))
    # Pass one: only the SOURCE project is in the window.
    first = collector._record_detected_moves(conn, [walk(
        D_SLUG, DRONE,
        old=[orig("B-roll/A001.braw"), orig("B-roll/A002.braw", size=200)],
        new=[orig("B-roll/A002.braw", size=200)])], NOW)
    assert first == 0
    assert conn.execute("SELECT COUNT(*) FROM file_moves").fetchone()[0] == 0
    kept = dbmod.pending_move_halves(conn, NOW)
    assert [r["half"] for r in kept] == [dbmod.HALF_VANISHED]

    # Pass two, a cycle later: the DESTINATION project is walked.
    second = collector._record_detected_moves(conn, [walk(
        A_SLUG, ANIMALS, old=[], new=[orig("Interviewees/A001.braw")])], NOW)
    assert second == 1
    row = conn.execute("SELECT * FROM file_moves").fetchone()
    assert (row["from_slug"], row["from_rel"]) == (D_SLUG, "B-roll/A001.braw")
    assert (row["to_slug"], row["to_rel"]) == (A_SLUG, "Interviewees/A001.braw")
    assert row["is_dir"] == 0
    # ...and the halves are consumed, so a third pass records nothing again.
    assert dbmod.pending_move_halves(conn, NOW) == []


def test_a_file_that_comes_back_to_its_old_path_is_not_a_move(conn):
    """Lane A re-uploading in the window before a command lands, or an admin
    undoing their own move: the file is at the path it left, which is not a
    move and must not become one by waiting a cycle."""
    collector = collector_mod.Collector(Settings(db_path=":memory:"))
    collector._record_detected_moves(conn, [walk(
        D_SLUG, DRONE, old=[orig("B-roll/A001.braw")], new=[])], NOW)
    assert len(dbmod.pending_move_halves(conn, NOW)) == 1
    recorded = collector._record_detected_moves(conn, [walk(
        D_SLUG, DRONE, old=[], new=[orig("B-roll/A001.braw")])], NOW)
    assert recorded == 0
    assert conn.execute("SELECT COUNT(*) FROM file_moves").fetchone()[0] == 0
    assert dbmod.pending_move_halves(conn, NOW) == []


def test_an_ambiguous_half_is_never_kept(conn):
    """Ambiguity is not a guess in the pass that sees it and does not become
    one a cycle later: two files with the same key vanishing is a copy made
    twice, not a move."""
    collector = collector_mod.Collector(Settings(db_path=":memory:"))
    collector._record_detected_moves(conn, [walk(
        D_SLUG, DRONE,
        old=[orig("B-roll/A001.braw"), orig("Copies/A001.braw")], new=[])], NOW)
    assert dbmod.pending_move_halves(conn, NOW) == []


def test_a_half_nobody_pairs_ages_out_of_the_table(conn):
    """A deletion is a deletion. The half is evidence with a shelf life, and
    `db.prune` is what enforces it - not the collector, so a container that
    stops running the inventory kind cannot grow this table for ever."""
    collector = collector_mod.Collector(Settings(db_path=":memory:"))
    collector._record_detected_moves(conn, [walk(
        D_SLUG, DRONE, old=[orig("B-roll/A001.braw")], new=[])], A_WEEK_AGO)
    assert len(dbmod.pending_move_halves(conn, A_WEEK_AGO)) == 1
    dbmod.prune(conn, NOW)
    assert conn.execute(
        "SELECT COUNT(*) FROM nas_media_pending_moves").fetchone()[0] == 0


def test_a_pass_that_could_not_read_its_evidence_is_not_a_check(conn):
    """dash-collector-alerts-1's honesty half: the stamp was unconditional, so
    a pass whose project directories were unreadable (or whose inventory the
    collapse brake refused) reported the check as having RUN over evidence it
    never saw. An unverified check is NOT CHECKED, never OK."""
    collector = collector_mod.Collector(Settings(db_path=":memory:"))
    collector._record_detected_moves(conn, [], NOW, blind=2)
    assert "file_move_detected" not in dbmod.notice_check_times(conn)
    # The cap's own kind is a fact about this pass whatever it could not read.
    assert "file_moves_dropped" in dbmod.notice_check_times(conn)
    collector._record_detected_moves(conn, [], NOW, blind=0)
    assert "file_move_detected" in dbmod.notice_check_times(conn)


# ---------------------------------------------------------------------------
# res-fleet-4: a computer that is renamed or forgotten strands its commands
# ---------------------------------------------------------------------------


def _a_move_for(conn, editor="ruskin", machine="OLD-PC"):
    move_id = dbmod.record_file_move(
        conn, from_slug=D_SLUG, from_project_rel=DRONE, from_rel="B-roll/A001.braw",
        to_slug=A_SLUG, to_project_rel=ANIMALS, to_rel="Interviewees/A001.braw",
        is_dir=False, proxies_moved=0, requested_by="owen", now=NOW,
        targets=[(editor, machine)], state=dbmod.FILE_MOVE_DONE)
    conn.commit()
    return move_id


def test_forgetting_a_computer_takes_its_outstanding_commands_with_it(conn):
    """`forget_machine` cleared ten tables and neither command table was among
    them, so the target sat with `applied_at IS NULL` for ever: never offered
    again, aged into `expired_at`, then a warn alert naming a computer the
    dashboard no longer has."""
    dbmod.upsert_machine(conn, "ruskin", "OLD-PC", now=NOW)
    _a_move_for(conn)
    dbmod.request_resolve_undo(
        conn, "ruskin", "OLD-PC", "j1", "FF5", "owen", NOW)
    conn.commit()
    dbmod.forget_machine(conn, "ruskin", "OLD-PC")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM file_move_targets").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM resolve_undo_requests").fetchone()[0] == 0


def test_a_rename_carries_the_outstanding_commands_onto_the_new_name(conn):
    """The rename hook. Both command tables are keyed on the HOSTNAME and
    nothing re-keyed them, so the move was never delivered under the new name
    - while that machine still held the file at the old path and lane A, which
    never deletes, put it back on the NAS."""
    dbmod.upsert_machine(conn, "ruskin", "OLD-PC", machine_id="mid-1", now=NOW)
    move_id = _a_move_for(conn)
    dbmod.request_resolve_undo(
        conn, "ruskin", "OLD-PC", "j1", "FF5", "owen", NOW)
    dbmod.upsert_machine(conn, "ruskin", "NEW-PC", machine_id="mid-1", now=NOW)
    conn.commit()
    assert dbmod.adopt_renamed_machine(
        conn, "ruskin", "OLD-PC", "NEW-PC", same_computer=True) is True
    conn.commit()
    moves = dbmod.pending_file_moves(conn, "ruskin", "NEW-PC", NOW)
    assert [m["id"] for m in moves] == [move_id]
    assert [u["journal_id"] for u in
            dbmod.pending_resolve_undos(conn, "ruskin", "NEW-PC")] == ["j1"]


def test_a_command_under_a_former_hostname_is_still_offered(conn):
    """SYS-18a defers the adoption above by a report or two (a rename and a
    cloned disk look identical for the first minute), and one lane A pass in
    that window undoes the move on the NAS. So the offer looks under the
    former names of the SAME machine_id - and under no other computer of that
    editor, which would tell a machine that never held the file to move it.

    dash-db-2 (2026-09-18b) narrowed it once more: the former name has to be
    QUIET. A name still reporting is a second live computer (the cloned disk
    SYS-18a refuses to adopt), so OLD-PC is an hour old here; the live twin
    is test_bug_hunt_2026_09_18b_dashboard_highs.py's case."""
    dbmod.upsert_machine(conn, "ruskin", "OLD-PC", machine_id="mid-1",
                         now=AN_HOUR_AGO)
    dbmod.upsert_machine(conn, "ruskin", "NEW-PC", machine_id="mid-1", now=NOW)
    dbmod.upsert_machine(conn, "ruskin", "OTHER-PC", machine_id="mid-2", now=NOW)
    move_id = _a_move_for(conn)
    conn.commit()
    assert dbmod.pending_file_moves(conn, "ruskin", "NEW-PC", NOW) == []
    offered = dbmod.pending_file_moves(
        conn, "ruskin", "NEW-PC", NOW, machine_id="mid-1")
    assert [m["id"] for m in offered] == [move_id]
    assert offered[0]["target_machine"] == "OLD-PC"
    # ...and never the editor's OTHER computer.
    assert dbmod.pending_file_moves(
        conn, "ruskin", "OTHER-PC", NOW, machine_id="mid-2") == []


def test_the_file_move_alert_can_fire_at_all(env):
    """`_check_file_moves` selected `rel_path` from `file_move_targets`, which
    has no such column: every cycle since v36 raised into `_rows`' defensive
    swallow and the check has never once fired. The path is on the `file_moves`
    row and comes from the join now."""
    _client, connection, settings = env
    dbmod.upsert_machine(connection, "ruskin", "EDIT-PC", now=NOW)
    move_id = _a_move_for(connection, machine="EDIT-PC")
    connection.execute(
        "UPDATE file_move_targets SET delivered_at=?, expired_at=? WHERE move_id=?",
        (A_WEEK_AGO, A_WEEK_AGO, move_id))
    connection.commit()
    findings = alerts.scan(connection, settings, NOW)
    expired = [f for f in findings if f["kind"] == "file_move_expired"]
    assert expired, "an expired file move is mailed to nobody"
    assert "B-roll/A001.braw" in expired[0]["subject"]


def test_a_stranded_move_names_the_fleet_not_a_computer_that_is_gone(env):
    """The fix line says "once that computer is back online", and after a
    forget or a rename there is no such computer: one warn about the fleet,
    not one unanswerable row per file."""
    _client, connection, settings = env
    move_id = _a_move_for(connection, machine="GONE-PC")
    connection.execute(
        "UPDATE file_move_targets SET delivered_at=?, expired_at=? WHERE move_id=?",
        (A_WEEK_AGO, A_WEEK_AGO, move_id))
    connection.commit()
    findings = [f for f in alerts.scan(connection, settings, NOW)
                if f["kind"] == "file_move_expired"]
    assert [f["subject"] for f in findings] == ["computers this server no longer has"]


# ---------------------------------------------------------------------------
# proxy-tiers-4: a stand-in fact that travels with the fleet
# ---------------------------------------------------------------------------


def test_a_stand_in_this_machine_placed_is_known_to_the_whole_fleet(env):
    """The ledger is per machine, so the wired rig that later opens the
    project has no cheap way to know a clip was born from a stand-in - which
    is the row of the tier plan that carries goal 2. Report section in,
    reply key out, both bounded and both additive."""
    client, connection, _settings = env
    assert client.post("/api/v1/report", json=report(guard={
        "standins_placed": {"rels": ["Creators_Club/CIA_City/A001.mov"],
                            "checked_at": NOW},
    }), headers=report_headers()).status_code == 200
    rows = connection.execute("SELECT * FROM broll_standins").fetchall()
    assert [(r["archive_rel"], r["machine"]) for r in rows] == [
        ("Creators_Club/CIA_City/A001.mov", "DESKTOP-LQQ41TC")]
    # The WIRED rig asks by reporting: the answer rides its own reply.
    answer = client.post("/api/v1/report", json=report(machine="BASE-RIG"),
                         headers=report_headers()).json()
    assert answer["standins_known"]["rels"] == ["Creators_Club/CIA_City/A001.mov"]


def test_a_stand_in_the_machine_no_longer_lists_stops_being_reported(env):
    """A full picture per report, like `editor_media`: a rel the companion no
    longer lists has been upgraded to the real editing proxy, and a stale row
    sends a wired rig looking for a stand-in that is not there."""
    client, connection, _settings = env
    client.post("/api/v1/report", json=report(guard={
        "standins_placed": {"rels": ["a/one.mov", "a/two.mov"]}}),
        headers=report_headers())
    client.post("/api/v1/report", json=report(guard={
        "standins_placed": {"rels": ["a/two.mov"]}}), headers=report_headers())
    assert [r["archive_rel"] for r in
            connection.execute("SELECT archive_rel FROM broll_standins")] == ["a/two.mov"]
    # A report with NO section changes nothing: every build in the field today
    # sends none, and an absent section is not an empty set.
    client.post("/api/v1/report", json=report(), headers=report_headers())
    assert connection.execute(
        "SELECT COUNT(*) FROM broll_standins").fetchone()[0] == 1


def test_a_forgotten_computers_stand_ins_are_forgotten_too(conn):
    dbmod.upsert_machine(conn, "ruskin", "EDIT-PC", now=NOW)
    dbmod.record_standins_placed(conn, "ruskin", "EDIT-PC", ["a/one.mov"], NOW)
    conn.commit()
    dbmod.forget_machine(conn, "ruskin", "EDIT-PC")
    conn.commit()
    assert dbmod.standins_known(conn) == []


# ---------------------------------------------------------------------------
# proxy-tiers-3: the archive this container cannot list, mailed
# ---------------------------------------------------------------------------


def test_an_unreadable_broll_archive_is_mailed_not_only_drawn(env, tmp_path, monkeypatch):
    """A notice is on the home page for whoever opens it; an alert is MAILED.
    This is the finding whose ten silent minutes put a 540p preview into a
    Resolve project, so it has to travel."""
    _client, connection, settings = env
    gone = tmp_path / "not-mounted"
    monkeypatch.setattr(mount_status, "root_of",
                        lambda name: (str(gone), str(gone)) if name == "broll" else None)
    kinds = {f["kind"] for f in alerts.scan(connection, settings, NOW)}
    assert "broll_archive_unreadable" in kinds
    # ...and a mount that is there is not a finding.
    monkeypatch.setattr(mount_status, "root_of",
                        lambda name: (str(tmp_path), str(tmp_path)))
    kinds = {f["kind"] for f in alerts.scan(connection, settings, NOW)}
    assert "broll_archive_unreadable" not in kinds


def test_the_new_alert_kind_carries_its_weekly_line():
    """A kind the weekly report cannot name is a check nobody can prove ran."""
    kind = [k for k in alerts.ALERT_KINDS if k.kind == "broll_archive_unreadable"]
    assert kind and kind[0].what and kind[0].severity == alerts.SEV_ERROR


# ---------------------------------------------------------------------------
# live-1, second half: the daily mail about a stall that healed a week ago
# ---------------------------------------------------------------------------


def test_a_healed_stall_is_not_mailed_every_morning(env):
    """ruskin's live shape on the morning of the pass: lane A killed once on
    2026-09-11 and restarted the same day, three lanes idle with nothing owed
    a week later, a four-minute-old report - and "CC Sync: still not fixed
    after 4 day(s)" going out by mail four mornings running, with nothing any
    editor or admin could do to clear it. The first half of live-1 fixed the
    ROW's sentence; this check still fired on the record alone."""
    client, connection, settings = env
    client.post("/api/v1/report", json=report(
        guard={"stalled": {"lane": "A", "seconds": 1500, "killed": True,
                           "at": A_WEEK_AGO}},
        lanes=[{"name": "lane_a_rclone_up", "state": "idle", "queued": 0,
                "transferring": 0, "last_error": None, "last_sync": NOW}]),
        headers=report_headers())
    kinds = {f["kind"] for f in alerts.scan(connection, settings, NOW)}
    assert "lane_stalled" not in kinds


def test_a_stall_from_an_hour_ago_still_raises_the_alarm(env):
    """The guard on the fix: a real stall must still be mailed, and a record
    with no stamp at all still counts (cannot tell is not cleared)."""
    client, connection, settings = env
    client.post("/api/v1/report", json=report(
        guard={"stalled": {"lane": "A", "seconds": 1500, "killed": True,
                           "at": AN_HOUR_AGO}},
        lanes=[{"name": "lane_a_rclone_up", "state": "syncing", "queued": 3,
                "transferring": 1, "last_error": None, "last_sync": None}]),
        headers=report_headers())
    kinds = {f["kind"] for f in alerts.scan(connection, settings, NOW)}
    assert "lane_stalled" in kinds


# ---------------------------------------------------------------------------
# dash-api-3: as_of bounds the answer instead of flattering it
# ---------------------------------------------------------------------------


def test_as_of_is_the_oldest_walk_that_answered(conn):
    """`refreshed_at` is written per project only when that project's walk
    replaced its rows, so one project walked every cycle made every answer
    look a minute old - including an answer served entirely from a project
    refused since a NAS reboot three days ago. The companion logs this number
    beside a rename it made from that data."""
    from ccsync_dashboard import locate as locate_mod
    stale, fresh = "2026-09-15T09:00:00+00:00", NOW
    for pid, (slug, rel, at) in enumerate(
            [(D_SLUG, "B-roll/old.mov", stale), (A_SLUG, "B-roll/new.mov", fresh)], 1):
        conn.execute(
            "INSERT INTO projects (id, slug, label, path, active, first_seen, "
            "last_seen) VALUES (?,?,?,?,1,?,?)",
            (pid, slug, slug, f"/data/Projects/{slug}", NOW, NOW))
        conn.execute(
            "INSERT INTO nas_media (project_id, rel_path, kind, ext, size, mtime_ns,"
            " refreshed_at) VALUES (?,?,?,?,?,?,?)",
            (pid, rel, "original", ".mov", 100 + pid, 1, at))
    conn.commit()
    answer = locate_mod.locate(conn, [("old.mov", 101)])
    assert answer["as_of"] == stale
    # An answer with nothing to bound keeps the tree-wide freshest walk.
    assert locate_mod.locate(conn, [("nothing.mov", 7)])["as_of"] == fresh


# ---------------------------------------------------------------------------
# dash-api-5: the count names the scope it was measured under
# ---------------------------------------------------------------------------


def test_the_skipped_exists_count_carries_its_scope(env):
    """The companion scans one project prefix at a time and the stored figure
    is one number per MACHINE, stated of the whole computer - so on a machine
    syncing several projects each scan overwrote the last, and project Y's
    zero hid project X's four."""
    from ccsync_dashboard import ui as ui_mod
    client, connection, _settings = env
    client.post("/api/v1/report", json=report(guard={
        "skipped_exists": {"count": 4, "subpath": "Projects/2026/FF5"}}),
        headers=report_headers())
    guard = dbmod.fetch_sync_guard_map(connection)[("ruskin", "DESKTOP-LQQ41TC")]
    assert guard["skipped_exists_subpath"] == "Projects/2026/FF5"
    assert "Projects/2026/FF5" in ui_mod.chip_help(
        "skipped_exists", n=guard["skipped_exists"],
        scope=ui_mod.skipped_scope(guard))
    # An older companion sends no subpath: the sentence loses the scope, and
    # never invents "the whole tree", which is the claim that was wrong.
    assert ui_mod.skipped_scope({"skipped_exists_subpath": None}) == ""


# ---------------------------------------------------------------------------
# dash-collector-alerts-6: whose floor said so
# ---------------------------------------------------------------------------


def test_a_disk_verdict_this_server_guessed_says_it_is_a_guess():
    """`DISK_RED_FREE_BYTES` is the DEFAULT of `lane_b_min_free_bytes`, a
    per-machine config key. An editor who raised it to 60 GB is parked and
    this server says nothing; one who lowered it to 5 GB gets "proxy download
    stopped itself" on a computer that is still downloading."""
    from ccsync_dashboard import health
    guessed = {"guard": {"disk_root_free_bytes": 10 * 1024 ** 3}, "lanes": []}
    sentence = health._why_sentence("disk_full", guessed)
    assert "probably" in sentence.lower()
    told = {"guard": {"disk_root_free_bytes": 10 * 1024 ** 3,
                      "blocked_reason": "disk_full"}, "lanes": []}
    assert "probably" not in health._why_sentence("disk_full", told).lower()


# ---------------------------------------------------------------------------
# dash-mounts-ui-2: a vendor row's state word
# ---------------------------------------------------------------------------


def test_a_version_held_from_different_bytes_is_not_staged():
    """`_vendor_rows` called a version this server published from DIFFERENT
    bytes "held", which says the vendor's binary is already here - the one
    thing it is not - and offered MAKE CURRENT on bytes nobody compared."""
    from ccsync_dashboard import ui as ui_mod
    record = {"kind": "companion", "platform": "windows", "version": "0.9.74",
              "sha256": "a" * 64}
    mine = {"sha256": "b" * 64, "is_current": False, "retracted": False}
    assert ui_mod._vendor_state(record, mine) == "conflict"
    assert ui_mod._vendor_state(record, {"sha256": "a" * 64,
                                         "is_current": False}) == "held"
    assert ui_mod._vendor_state(record, {"sha256": "a" * 64,
                                         "is_current": True}) == "current"
    assert ui_mod._vendor_state(record, None) == "available"
    # Belt and braces: nothing offers MAKE CURRENT on a recalled build.
    assert ui_mod._vendor_state(record, {"sha256": "a" * 64,
                                         "retracted": True}) == "recalled"


# ---------------------------------------------------------------------------
# regression-5: a brand new deployment does not read STOPPED
# ---------------------------------------------------------------------------


def test_a_fresh_syncthingless_deployment_is_not_reported_as_stopped(conn):
    """Between about t+3 min and the second alerts cycle, a brand new
    zero-touch or vendor dashboard showed "the last collector cycle finished
    too long ago" on its home page and reported itself stale on
    /api/v1/health, on a perfectly healthy collector. The alert, the notice
    and the chip were all correctly silent, so the visible half was exactly
    the half CR-258B was written for."""
    five_minutes_in = "2026-09-18T12:05:00+00:00"
    conn.execute("INSERT INTO poll_runs (kind, started_at, finished_at, ok) "
                 "VALUES ('alerts', ?, ?, 1)", (NOW, NOW))
    conn.commit()
    assert dbmod.collector_stale_bound(conn) > 600
    assert dbmod.fetch_collector_status(
        conn, now=five_minutes_in)["collector_stale"] is False
    # A deployment whose Syncthing-backed kinds ARE running keeps the tight
    # bound: nothing here slows down noticing a collector that really stopped.
    conn.execute("INSERT INTO poll_runs (kind, started_at, finished_at, ok) "
                 "VALUES ('config', ?, ?, 1)", (NOW, NOW))
    conn.commit()
    assert dbmod.collector_stale_bound(conn) == dbmod.COLLECTOR_STALE_SECONDS
    assert dbmod.fetch_collector_status(
        conn, now=five_minutes_in)["collector_stale"] is True


# ---------------------------------------------------------------------------
# regression-3: the retire branch asks the schema question too
# ---------------------------------------------------------------------------


def _boot_world(tmp_path, monkeypatch, *, image_version, image_schema,
                live_schema, tree="0.7.43"):
    """A /data that has taken an OTA update, plus a REAL /app.

    regression-3 (2026-09-18): `_world` in
    test_bug_hunt_2026_09_11b_dash_mounts_ui.py never patches `APP_ROOT`, so
    `image_version()` reads a non-existent /app, returns "", and the CR-270
    retire branch never fired in any test - which is why nothing could see
    that it asks the version question alone.
    """
    import json
    import sqlite3
    import sys
    from pathlib import Path

    deploy = Path(__file__).resolve().parents[1] / "deploy"
    sys.path.insert(0, str(deploy))
    try:
        import select_code_root as scr
    finally:
        sys.path.pop(0)

    app = tmp_path / "app"
    pkg = app / "src" / "ccsync_dashboard"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(f'VERSION = "{image_version}"\n', encoding="utf-8")
    steps = "".join(f"    ({n}, SCHEMA_V{n}),\n" for n in range(1, image_schema + 1))
    (pkg / "db.py").write_text(
        f"_MIGRATION_STEPS = [\n{steps}]\nSCHEMA_VERSION = {image_schema}\n",
        encoding="utf-8")

    code = tmp_path / "code"
    (code / tree).mkdir(parents=True)
    (code / "current.json").write_text(json.dumps({
        "version": tree, "previous": "0.7.40",
        "applied_at": "2026-09-11T00:00:00Z"}), encoding="utf-8")
    (code / "boot_attempts.json").write_text(
        json.dumps({"version": tree, "attempts": 0}), encoding="utf-8")

    db_path = tmp_path / "dashboard.db"
    connection = sqlite3.connect(db_path)
    connection.execute(f"PRAGMA user_version = {live_schema}")
    connection.close()

    monkeypatch.setenv("DASH_DB_PATH", str(db_path))
    monkeypatch.setattr(scr, "APP_ROOT", app)
    monkeypatch.setattr(scr, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scr, "CODE_DIR", code)
    monkeypatch.setattr(scr, "CURRENT_JSON", code / "current.json")
    monkeypatch.setattr(scr, "BOOT_ATTEMPTS", code / "boot_attempts.json")
    monkeypatch.setattr(scr, "read_runtime_id", lambda: "rid")
    monkeypatch.setattr(scr, "check_tree", lambda v, r: (f"/data/code/{v}/src", ""))
    return scr, code


def test_a_tree_the_image_cannot_run_is_not_retired(tmp_path, monkeypatch):
    """The retire branch decides whether CR-259a's schema guard is ever
    consulted, and it asked the VERSION question alone. An image that carries
    the version but knows an older schema would retire the one tree that can
    run this database and boot into a migrate() that raises on every start."""
    import json
    scr, code = _boot_world(tmp_path, monkeypatch, image_version="0.7.50",
                            image_schema=50, live_schema=54)
    assert scr.main() == 0
    current = json.loads((code / "current.json").read_text(encoding="utf-8"))
    assert current["version"] == "0.7.43", "the tree was retired onto an image that cannot open the database"
    assert "v50" in current["revert_refused_reason"]
    assert current["revert_refused_from"] == "0.7.43"


def test_an_image_that_has_caught_up_still_retires_the_tree(tmp_path, monkeypatch):
    """The guard on the fix: CR-270's whole point is that an OTA bundle the
    image carries is retired rather than left naming a stale version for
    weeks."""
    import json
    scr, code = _boot_world(tmp_path, monkeypatch, image_version="0.7.50",
                            image_schema=54, live_schema=54)
    assert scr.main() == 0
    current = json.loads((code / "current.json").read_text(encoding="utf-8"))
    assert current["version"] == ""
    assert current["retired_from"] == "0.7.43"


def test_a_retire_drops_a_refusal_the_admin_could_never_clear(
        tmp_path, monkeypatch):
    """dash-mounts-ui-1 (2026-09-18b mediums), replacing regression-3's
    `test_a_retire_keeps_an_earlier_refusal_where_the_alert_looks_for_it`.

    The carry that test pinned was permanent: with `version` now "", every
    later boot returns at `if not version:` BEFORE the clearing rule, so
    nothing in this script could drop the keys again and the admin read
    "restore a backup" on a healthy container for ever. The sentence is also
    false the moment it is written here - this branch is reached only after
    `revert_refusal("")` said the image can run this database. Keeping the
    evidence for `alerts.py` is moot once `applied` is "": that check returns
    nothing when there is no applied version to disagree about."""
    import json
    scr, code = _boot_world(tmp_path, monkeypatch, image_version="0.7.50",
                            image_schema=54, live_schema=54)
    payload = json.loads((code / "current.json").read_text(encoding="utf-8"))
    payload["revert_refused_reason"] = "the image knows v50 and this database is on v54"
    payload["revert_refused_from"] = "0.7.43"
    (code / "current.json").write_text(json.dumps(payload), encoding="utf-8")
    assert scr.main() == 0
    current = json.loads((code / "current.json").read_text(encoding="utf-8"))
    assert current["retired_from"] == "0.7.43"
    assert "revert_refused_reason" not in current
    assert "revert_refused_from" not in current
    # And a second boot leaves it alone rather than reviving the banner.
    assert scr.main() == 0
    again = json.loads((code / "current.json").read_text(encoding="utf-8"))
    assert "revert_refused_reason" not in again


# ---------------------------------------------------------------------------
# dash-collector-alerts-6, completed: the machine's OWN floor
# ---------------------------------------------------------------------------


GB = 1024 ** 3


def _floor_report(machine, free_gb, floor_gb, total_gb=1000):
    return report(machine=machine, guard={
        "disk": {"root_free_bytes": free_gb * GB,
                 "root_total_bytes": total_gb * GB, "at": NOW},
        "disk_floor": {"parked": free_gb < floor_gb, "floor_bytes": floor_gb * GB,
                       "free_bytes": free_gb * GB, "at": NOW},
    })


def test_a_machine_with_a_raised_floor_is_judged_against_its_own_number(env):
    """`lane_b_min_free_bytes` is a per-machine config key with 20 GB only as
    its DEFAULT, and `DiskFloorLatch.report()` has sent the effective value on
    every report since SYNC-7. Nothing stored it, so an editor on a small SSD
    who raised it to 60 GB was parked at 55 GB and this server said nothing at
    all."""
    from ccsync_dashboard import health
    client, connection, _settings = env
    client.post("/api/v1/report", json=_floor_report("SMALL-SSD", 55, 60),
                headers=report_headers())
    guard = dbmod.fetch_sync_guard_map(connection)[("ruskin", "SMALL-SSD")]
    assert guard["disk_floor_bytes"] == 60 * GB
    assert health.machine_disk_floor(guard) == 60 * GB
    row = {"guard": guard, "lanes": []}
    assert health._disk_floor_hit(guard["disk_root_free_bytes"],
                                  health.machine_disk_floor(guard)) is True
    # ...and because the number came from the machine, the sentence is flat:
    # nothing here is this server's guess any more.
    sentence = health._why_sentence("disk_full", row)
    assert "probably" not in sentence.lower()


def test_a_machine_with_a_lowered_floor_is_not_accused_of_stopping(env):
    """The mirror image, and the one that put "proxy download stopped itself"
    on a row for a computer that was still downloading."""
    from ccsync_dashboard import health
    client, connection, settings = env
    client.post("/api/v1/report", json=_floor_report("BIG-RIG", 15, 5, total_gb=100),
                headers=report_headers())
    guard = dbmod.fetch_sync_guard_map(connection)[("ruskin", "BIG-RIG")]
    assert guard["disk_floor_bytes"] == 5 * GB
    assert health._disk_floor_hit(guard["disk_root_free_bytes"],
                                  health.machine_disk_floor(guard)) is False
    # ...and it is not mailed about either.
    kinds = {f["kind"] for f in alerts.scan(connection, settings, NOW)}
    assert "disk_low" not in kinds and "disk_park" not in kinds


def test_a_machine_that_has_never_said_keeps_the_default_and_the_guess(env):
    """An older build sends no floor. The constant is the fallback, and the
    sentence says it is one."""
    from ccsync_dashboard import health
    row = {"guard": {"disk_root_free_bytes": 10 * GB}, "lanes": []}
    assert health.machine_disk_floor(row["guard"]) is None
    assert health._disk_floor_hit(10 * GB, None) is True
    assert "probably" in health._why_sentence("disk_full", row).lower()


# ---------------------------------------------------------------------------
# res-fleet-3's answer word: "trashed locally, destination not synced here"
# ---------------------------------------------------------------------------


def _a_move_to_follow(connection, editor="ruskin", machine="DESKTOP-LQQ41TC"):
    move_id = dbmod.record_file_move(
        connection, from_slug=D_SLUG, from_project_rel=DRONE,
        from_rel="B-roll/A001.braw", to_slug=A_SLUG, to_project_rel=ANIMALS,
        to_rel="Interviewees/A001.braw", is_dir=False, proxies_moved=0,
        requested_by="owen", now=NOW, targets=[(editor, machine)],
        state=dbmod.FILE_MOVE_DONE)
    connection.commit()
    return move_id


def test_a_move_trashed_locally_is_a_terminal_answer(env):
    """HAND_MOVES_ON_THE_SERVER.md section 4b: the machine holds the file and
    does not sync the DESTINATION project, so it trashes its copy rather than
    filing it into a directory with no `.ccsync-project` marker - which was a
    permanent invisible orphan reported as done (res-fleet-3). The companion's
    real answer shape, through the report route."""
    client, connection, _settings = env
    move_id = _a_move_to_follow(connection)
    answer = client.post("/api/v1/report", json=report(file_moves_applied=[{
        "id": move_id, "ok": True, "state": "not_synced_here",
        "detail": "trashed locally, destination not synced here"}]),
        headers=report_headers())
    assert answer.status_code == 200
    row = connection.execute(
        "SELECT * FROM file_move_targets WHERE move_id=?", (move_id,)).fetchone()
    assert row["state"] == dbmod.FILE_MOVE_TARGET_NOT_SYNCED_HERE
    assert row["applied_at"] and row["ok"] == 1
    # TERMINAL: the command is not offered again on the next report.
    assert "file_moves" not in (answer.json().get("commands") or {})
    assert dbmod.pending_file_moves(
        connection, "ruskin", "DESKTOP-LQQ41TC", NOW) == []


def test_the_moves_history_gives_it_its_own_words(env):
    """"moved" would be untrue and "FAILED" would send an admin looking for a
    fault that is not there."""
    client, connection, _settings = env
    move_id = _a_move_to_follow(connection)
    client.post("/api/v1/report", json=report(file_moves_applied=[{
        "id": move_id, "ok": True, "state": "not_synced_here",
        "detail": "trashed locally, destination not synced here"}]),
        headers=report_headers())
    connection.execute(
        "INSERT INTO projects (slug, label, path, active, first_seen, last_seen) "
        "VALUES (?,?,?,1,?,?)",
        (D_SLUG, DRONE, f"/data/Projects/{DRONE}", NOW, NOW))
    connection.commit()
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    page = client.get(f"/partials/project/{D_SLUG}")
    assert page.status_code == 200
    assert "does not sync the destination project" in page.text
    assert "FAILED" not in page.text


def test_a_state_word_this_build_does_not_know_never_422s_the_report(env):
    """`file_moves_applied` is not a tolerant section, so until now a
    companion that grew a state word ahead of its dashboard 422'd the WHOLE
    report - lanes, presence and alarms - every thirty seconds. An unknown
    word is no word now: answered, terminal, and the machine's own sentence
    kept."""
    client, connection, _settings = env
    move_id = _a_move_to_follow(connection)
    answer = client.post("/api/v1/report", json=report(file_moves_applied=[{
        "id": move_id, "ok": True, "state": "some_future_word",
        "detail": "whatever the next wave calls it"}]),
        headers=report_headers())
    assert answer.status_code == 200
    row = connection.execute(
        "SELECT * FROM file_move_targets WHERE move_id=?", (move_id,)).fetchone()
    assert row["state"] is None and row["applied_at"] and row["ok"] == 1
    assert row["detail"] == "whatever the next wave calls it"


def test_the_report_reply_says_which_dashboard_answered(env):
    """res-fleet-3 (2026-09-18): a companion that grows a wire word needs
    something to gate it on, and the reply has never said which dashboard is
    answering. `file_moves_applied` is not a tolerant section, so an unknown
    `state` 422s the whole report - the companion has to be able to tell a
    0.7.49 from a 0.7.50 before it sends `not_synced_here` to either."""
    from ccsync_dashboard import VERSION
    client, _connection, _settings = env
    answer = client.post("/api/v1/report", json=report(),
                         headers=report_headers()).json()
    assert answer["dashboard_version"] == VERSION
