from __future__ import annotations

import pytest

from ccsync_dashboard import db as dbmod

T0 = "2026-07-24T10:00:00+00:00"
T1 = "2026-07-24T10:05:00+00:00"
T2 = "2026-07-24T10:30:00+00:00"


def test_migrate_idempotent(conn):
    dbmod.migrate(conn)  # second run is a no-op
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"projects", "devices", "completion_current", "completion_history",
            "missing_files", "lane_report_current", "lane_report_history",
            "poll_runs", "selections", "meta", "editor_prefs", "machine_state",
            "project_roots", "nas_media", "nas_inventory_state",
            "editor_media_project", "editor_media", "media_tree_clips",
            "active_transfers"} <= tables


def test_upsert_project_and_deactivate(conn):
    pid = dbmod.upsert_project(conn, "2025-ff4-nuclear", "2025/FF4/Nuclear", "/data/Projects/2025/FF4/Nuclear", T0)
    assert dbmod.upsert_project(conn, "2025-ff4-nuclear", "2025/FF4/Nuclear v2", "/x", T1) == pid
    row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    assert row["label"] == "2025/FF4/Nuclear v2"
    assert row["first_seen"] == T0 and row["last_seen"] == T1

    dbmod.upsert_project(conn, "other", "Other", "/o", T1)
    dbmod.deactivate_missing_projects(conn, ["other"])
    assert conn.execute("SELECT active FROM projects WHERE slug='2025-ff4-nuclear'").fetchone()[0] == 0
    assert conn.execute("SELECT active FROM projects WHERE slug='other'").fetchone()[0] == 1
    # Reappearing folder is reactivated, never duplicated.
    dbmod.upsert_project(conn, "2025-ff4-nuclear", "2025/FF4/Nuclear", "/x", T2)
    assert conn.execute("SELECT active FROM projects WHERE slug='2025-ff4-nuclear'").fetchone()[0] == 1


DEVICE_ID = "AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD-EEEEEEE-FFFFFFF-GGGGGGG-HHHHHHH"


def test_resolve_editor_username():
    assert dbmod.resolve_editor_username("jsmith") == "jsmith"
    assert dbmod.resolve_editor_username("JSmith") == "jsmith"
    assert dbmod.resolve_editor_username(DEVICE_ID) is None
    assert dbmod.resolve_editor_username("Jane's MacBook") is None
    assert dbmod.resolve_editor_username("") is None


def test_upsert_device_mapping(conn):
    did = dbmod.upsert_device(conn, DEVICE_ID, "jsmith", is_server=False, now=T0)
    row = conn.execute("SELECT * FROM devices WHERE id=?", (did,)).fetchone()
    assert row["editor_username"] == "jsmith"
    dbmod.upsert_device(conn, DEVICE_ID, DEVICE_ID, is_server=False, now=T1)
    row = conn.execute("SELECT * FROM devices WHERE id=?", (did,)).fetchone()
    assert row["editor_username"] is None  # renamed to raw ID -> unmapped


def test_set_connections(conn):
    dbmod.upsert_device(conn, "A" * 7, "a", False, T0)
    dbmod.upsert_device(conn, "B" * 7, "b", False, T0)
    dbmod.set_connections(conn, {"A" * 7: "tcp://1.2.3.4:22000"}, T1)
    a = conn.execute("SELECT * FROM devices WHERE device_id=?", ("A" * 7,)).fetchone()
    b = conn.execute("SELECT * FROM devices WHERE device_id=?", ("B" * 7,)).fetchone()
    assert a["connected"] == 1 and a["last_connected_at"] == T1
    assert b["connected"] == 0
    dbmod.set_connections(conn, {}, T2)
    a = conn.execute("SELECT * FROM devices WHERE device_id=?", ("A" * 7,)).fetchone()
    assert a["connected"] == 0 and a["last_connected_at"] == T1  # last seen preserved


def test_should_snapshot_rules():
    f = dbmod.should_snapshot
    assert f(None, 50.0, 10, T0) is True
    # steady 100%: only every 6h
    last = {"completion": 100.0, "need_items": 0, "ts": T0}
    assert f(last, 100.0, 0, "2026-07-24T12:00:00+00:00") is False
    assert f(last, 100.0, 0, "2026-07-24T16:00:00+00:00") is True
    # integer-percent crossing
    last = {"completion": 50.2, "need_items": 100, "ts": T0}
    assert f(last, 51.1, 100, T1) is True
    assert f(last, 50.9, 100, T1) is False
    # need_items delta > 10%
    assert f(last, 50.9, 89, T1) is True
    assert f(last, 50.9, 95, T1) is False
    # time-based while incomplete: >= 15 min
    assert f(last, 50.9, 100, T2) is True


def test_upsert_completion_history_no_bloat(conn):
    pid = dbmod.upsert_project(conn, "p", "P", "/p", T0)
    did = dbmod.upsert_device(conn, "D" * 7, "d", False, T0)
    kw = dict(need_bytes=0, need_deletes=0, global_items=10, global_bytes=100)
    for i, ts in enumerate([T0, T1, "2026-07-24T10:06:00+00:00"]):
        dbmod.upsert_completion(conn, pid, did, completion=100.0, need_items=0, now=ts, **kw)
    assert conn.execute("SELECT COUNT(*) FROM completion_history").fetchone()[0] == 1
    cur = conn.execute("SELECT * FROM completion_current").fetchall()
    assert len(cur) == 1 and cur[0]["updated_at"] == "2026-07-24T10:06:00+00:00"


def test_missing_files_cap_and_clear(conn):
    pid = dbmod.upsert_project(conn, "p", "P", "/p", T0)
    did = dbmod.upsert_device(conn, "D" * 7, "d", False, T0)
    files = [(f"file{i:04}.wav", i) for i in range(600)]
    dbmod.replace_missing_files(conn, pid, did, files, truncated=True, now=T0)
    assert conn.execute("SELECT COUNT(*) FROM missing_files").fetchone()[0] == dbmod.MISSING_FILES_CAP
    result = dbmod.fetch_missing(conn, pid, did)
    assert result["truncated"] is True and len(result["files"]) == 500
    dbmod.clear_missing_files(conn, pid, did)
    assert dbmod.fetch_missing(conn, pid, did) == {"files": [], "truncated": False, "refreshed_at": None}


def test_lane_report_history_only_on_transition(conn):
    kw = dict(editor_username="jsmith", machine="M1", lane="lane_a_up",
              queued=0, transferring=0, last_sync=None, detail=None,
              companion_version="0.1.0")
    dbmod.upsert_lane_report(conn, state="idle", last_error=None, reported_at=T0, received_at=T0, **kw)
    dbmod.upsert_lane_report(conn, state="idle", last_error=None, reported_at=T1, received_at=T1, **kw)
    assert conn.execute("SELECT COUNT(*) FROM lane_report_history").fetchone()[0] == 1
    dbmod.upsert_lane_report(conn, state="error", last_error="boom", reported_at=T2, received_at=T2, **kw)
    assert conn.execute("SELECT COUNT(*) FROM lane_report_history").fetchone()[0] == 2
    cur = conn.execute("SELECT * FROM lane_report_current").fetchall()
    assert len(cur) == 1 and cur[0]["state"] == "error" and cur[0]["received_at"] == T2


def test_prune(conn):
    pid = dbmod.upsert_project(conn, "p", "P", "/p", T0)
    did = dbmod.upsert_device(conn, "D" * 7, "d", False, T0)
    now = "2026-07-24T10:00:00+00:00"
    # 3 same-hour rows from 3 days ago (thinned to 1), one from 40 days ago (dropped).
    for ts in ["2026-07-21T09:10:00+00:00", "2026-07-21T09:20:00+00:00",
               "2026-07-21T09:30:00+00:00", "2026-06-14T09:00:00+00:00"]:
        conn.execute(
            "INSERT INTO completion_history (project_id, device_id, ts, completion, need_items, need_bytes) "
            "VALUES (?, ?, ?, 50, 5, 5)", (pid, did, ts))
    for i in range(dbmod.POLL_RUNS_KEEP + 50):
        dbmod.record_poll_run(conn, "completion", now, now, True, None)
    dbmod.prune(conn, now)
    assert conn.execute("SELECT COUNT(*) FROM completion_history").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM poll_runs").fetchone()[0] == dbmod.POLL_RUNS_KEEP


def test_v1_to_v2_migration_preserves_data(tmp_path):
    # Build a genuine v1 database (schema.sql only), populate, then migrate.
    import sqlite3
    path = tmp_path / "v1.db"
    raw = sqlite3.connect(path)
    raw.executescript(dbmod.SCHEMA_PATH.read_text(encoding="utf-8"))
    raw.execute("PRAGMA user_version = 1")
    raw.execute("INSERT INTO projects (slug, label, path, first_seen, last_seen) "
                "VALUES ('p', 'P', '/p', ?, ?)", (T0, T0))
    raw.commit()
    raw.close()

    conn = dbmod.connect(path)
    dbmod.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == dbmod.SCHEMA_VERSION
    assert conn.execute("SELECT slug FROM projects").fetchone()[0] == "p"
    dbmod.add_selection(conn, "jsmith", "p", "jsmith", T0)  # selections table exists
    cols = {r[1] for r in conn.execute("PRAGMA table_info(completion_current)")}
    assert "rate_bytes_per_sec" in cols
    cols = {r[1] for r in conn.execute("PRAGMA table_info(lane_report_current)")}
    assert {"current_project", "speed_bps", "eta_seconds"} <= cols
    dbmod.migrate(conn)  # idempotent
    conn.close()


def test_selection_helpers(conn):
    assert dbmod.add_selection(conn, "jsmith", "a", "jsmith", T0) is True
    assert dbmod.add_selection(conn, "jsmith", "b", "alex", T1) is True
    assert dbmod.add_selection(conn, "jsmith", "a", "jsmith", T1) is False  # already ticked
    sels = dbmod.fetch_selections(conn, "jsmith")
    assert [(s["slug"], s["position"]) for s in sels] == [("a", 1), ("b", 2)]
    assert dbmod.remove_selection(conn, "jsmith", "a") is True
    assert dbmod.remove_selection(conn, "jsmith", "a") is False
    # re-tick goes to the back
    dbmod.add_selection(conn, "jsmith", "a", "jsmith", T2)
    assert [s["slug"] for s in dbmod.fetch_selections(conn, "jsmith")] == ["b", "a"]
    assert dbmod.fetch_all_selections(conn) == {"b": ["jsmith"], "a": ["jsmith"]}


def test_meta_helpers(conn):
    assert dbmod.meta_get(conn, "x") is None
    dbmod.meta_set(conn, "x", "1")
    dbmod.meta_set(conn, "x", "2")
    assert dbmod.meta_get(conn, "x") == "2"


def test_compute_rate_ema():
    f = dbmod.compute_rate_ema
    assert f(None, None, 100, 30.0) is None            # no history
    assert f(1000, None, 700, 30.0) == 10.0            # first sample
    assert f(700, 10.0, 400, 30.0) == pytest.approx(0.3 * 10.0 + 0.7 * 10.0)
    assert f(400, 10.0, 900, 30.0) == 0.0              # need grew -> reset to sample
    assert f(400, 10.0, 400, 0.0) == 10.0              # dt=0 keeps prior


def test_upsert_completion_tracks_rate(conn):
    pid = dbmod.upsert_project(conn, "p", "P", "/p", T0)
    did = dbmod.upsert_device(conn, "D" * 7, "d", False, T0)
    kw = dict(need_deletes=0, global_items=10, global_bytes=100)
    dbmod.upsert_completion(conn, pid, did, completion=50.0, need_items=5,
                            need_bytes=3000, now=T0, **kw)
    dbmod.upsert_completion(conn, pid, did, completion=60.0, need_items=4,
                            need_bytes=0, now=T1, **kw)  # 3000 bytes over 300s = 10 B/s
    row = conn.execute("SELECT rate_bytes_per_sec FROM completion_current").fetchone()
    assert row[0] == pytest.approx(10.0)


def test_replace_nas_media_computes_rollup(conn):
    pid = dbmod.upsert_project(conn, "p", "P", "/p", T0)
    rows = [
        ("B-roll/a.braw", "original", ".braw", 1000, 111),
        ("B-roll/b.mov", "original", ".mov", 500, 222),
        ("B-roll/Proxy/a.mov", "proxy", ".mov", 50, 333),
    ]
    dbmod.replace_nas_media(conn, pid, rows, "sig1", 3, T0)
    summary = dbmod.fetch_nas_media_summary(conn, pid)
    assert summary == {"n_originals": 2, "bytes_originals": 1500,
                       "n_proxies": 1, "bytes_proxies": 50}
    assert dbmod.nas_inventory_sig(conn, pid) == "sig1"
    assert conn.execute("SELECT COUNT(*) FROM nas_media").fetchone()[0] == 3
    # replace with a new set drops the old rows
    dbmod.replace_nas_media(conn, pid, [("c.braw", "original", ".braw", 9, 9)], "sig2", 1, T1)
    assert conn.execute("SELECT COUNT(*) FROM nas_media").fetchone()[0] == 1
    assert dbmod.nas_inventory_sig(conn, pid) == "sig2"


def test_editor_media_cap(conn):
    files = [(f"f{i}.braw", "original", i) for i in range(dbmod.EDITOR_MEDIA_CAP + 50)]
    dbmod.replace_editor_media(conn, "jsmith", "PC", "p", files, T0)
    assert conn.execute("SELECT COUNT(*) FROM editor_media").fetchone()[0] == dbmod.EDITOR_MEDIA_CAP


def test_media_tree_and_uploading_flag(conn):
    dbmod.replace_media_tree(conn, "jsmith", "PC", "p", [
        ("", "root clip", "P:/x/root.braw", "original", True),
        ("Interviews", "int1", "P:/x/int1.braw", "original", False),
        ("Interviews", "int2", "P:/x/int2.mov", "original", True),
    ], T0)
    # int1 is currently uploading
    dbmod.replace_active_transfers(conn, "jsmith", "PC", [
        {"lane": "lane_a_video_up", "name": "int1.braw", "direction": "up",
         "percentage": 40.0, "speed_bps": 1000.0}], T0)
    tree = dbmod.fetch_media_tree(conn, "jsmith", "PC", "p", T0)
    bins = {b["bin_path"]: b for b in tree["bins"]}
    assert bins["Interviews"]["present"] == 1 and bins["Interviews"]["total"] == 2
    int1 = next(c for c in bins["Interviews"]["clips"] if c["clip_name"] == "int1")
    assert int1["present"] is False and int1["uploading"] is True


def test_active_transfers_freshness(conn):
    old = "2026-07-25T09:00:00+00:00"
    now = "2026-07-25T09:10:00+00:00"   # 10 min later, past the 120s window
    dbmod.replace_active_transfers(conn, "jsmith", "PC", [
        {"lane": "lane_a_video_up", "name": "x.braw", "direction": "up"}], old)
    assert dbmod.fetch_active_transfers(conn, old) != []      # fresh at report time
    assert dbmod.fetch_active_transfers(conn, now) == []      # stale later


def test_prune_media_tables(conn):
    now = "2026-07-25T12:00:00+00:00"
    old = "2026-06-01T12:00:00+00:00"                          # >14 days
    dbmod.upsert_editor_media_project(conn, editor="j", machine="PC", slug="p", mode="editor",
                                      n_originals=1, bytes_originals=1, n_proxies=0,
                                      bytes_proxies=0, truncated=False, now=old)
    dbmod.replace_active_transfers(conn, "j", "PC",
                                   [{"lane": "a", "name": "x", "direction": "up"}], old)
    dbmod.prune(conn, now)
    assert conn.execute("SELECT COUNT(*) FROM editor_media_project").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM active_transfers").fetchone()[0] == 0


def test_purge_nas_media_for_inactive(conn):
    pid = dbmod.upsert_project(conn, "gone", "Gone", "/g", T0)
    dbmod.replace_nas_media(conn, pid, [("a.braw", "original", ".braw", 1, 1)], "s", 1, T0)
    dbmod.deactivate_missing_projects(conn, [])   # marks 'gone' inactive
    dbmod.purge_nas_media_for_inactive(conn)
    assert conn.execute("SELECT COUNT(*) FROM nas_media").fetchone()[0] == 0


def test_fetch_collector_status(conn):
    assert dbmod.fetch_collector_status(conn)["syncthing_reachable"] is False
    dbmod.record_poll_run(conn, "completion", T0, T0, True, None)
    dbmod.record_poll_run(conn, "connections", T1, T1, False, "connection refused")
    status = dbmod.fetch_collector_status(conn)
    assert status["syncthing_reachable"] is False  # latest run failed
    assert status["kinds"]["completion"]["ok"] == 1
    dbmod.record_poll_run(conn, "connections", T2, T2, True, None)
    assert dbmod.fetch_collector_status(conn)["syncthing_reachable"] is True
