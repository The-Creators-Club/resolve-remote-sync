"""G0 of the legal-gap features (docs/LEGAL_GAP_FEATURES_PLAN.md, 2026-09-25):
schema v59 and every db.py helper the other groups call by name - the
telemetry switches' record and deletes (LG-1), the subject registry and its
coverage test (LG-2), erase and the completed delete (LG-3), report_via
(LG-4), the accepted licence (LG-5) and retention's overdue state (LG-17)."""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from pathlib import Path

import pytest

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import sessions

NOW = "2026-09-25T10:00:00+00:00"
REPO = Path(__file__).resolve().parents[2]


def _iso(seconds: float = 0.0) -> str:
    return (dt.datetime.fromisoformat(NOW) + dt.timedelta(seconds=seconds)).isoformat()


def _columns(conn, table):
    return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _machine(conn, editor="tchen", machine="TCHEN-RIG", **cols):
    dbmod.upsert_machine(conn, editor, machine, now=NOW)
    conn.execute(
        "INSERT OR IGNORE INTO machine_state (editor_username, machine, reported_at) "
        "VALUES (?, ?, ?)", (editor, machine, NOW))
    for key, value in cols.items():
        conn.execute(f"UPDATE machine_state SET {key}=? WHERE editor_username=? AND machine=?",
                     (value, editor, machine))
    conn.commit()


def _media(conn, editor="tchen", machine="TCHEN-RIG", slug="ff5"):
    conn.execute(
        "INSERT INTO editor_media_project (editor_username, machine, project_slug, reported_at)"
        " VALUES (?,?,?,?)", (editor, machine, slug, NOW))
    conn.execute(
        "INSERT INTO editor_media (editor_username, machine, project_slug, rel_path, kind,"
        " refreshed_at) VALUES (?,?,?,?,?,?)",
        (editor, machine, slug, "Footage/A001.mov", "original", NOW))
    conn.execute(
        "INSERT INTO media_tree_clips (editor_username, machine, project_slug, bin_path,"
        " clip_name, refreshed_at) VALUES (?,?,?,?,?,?)",
        (editor, machine, slug, "Master/Day 1", "A001.mov", NOW))


def _diag(conn, editor="tchen", machine="TCHEN-RIG"):
    dbmod.record_diagnostics(conn, editor=editor, machine=machine, machine_id="m1",
                             trigger="manual", at=NOW, received_at=NOW,
                             text="log line naming ProjectX")


def _count(conn, table, **where):
    clause = " AND ".join(f"{k}=?" for k in where) or "1=1"
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {clause}",
                        tuple(where.values())).fetchone()[0]


# ---------------------------------------------------------------- schema v59

V59 = {"report_optouts", "report_optouts_local", "report_via", "eula_json"}


def test_v59_is_the_head_and_the_list_stays_gapless():
    numbers = [n for n, _ in dbmod._MIGRATION_STEPS]
    assert numbers == list(range(1, dbmod.SCHEMA_VERSION + 1))
    assert dbmod.SCHEMA_VERSION == 59
    assert dict(dbmod._MIGRATION_STEPS)[59] is dbmod.SCHEMA_V59


def test_v59_on_a_fresh_database(conn):
    assert V59 <= _columns(conn, "machine_state")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 59


def test_v59_on_a_v58_database_reaches_the_same_shape_and_backfills_nothing(tmp_path):
    old = dbmod.connect(tmp_path / "v58.db")
    dbmod.migrate(old, [s for s in dbmod._MIGRATION_STEPS if s[0] <= 58])
    old.execute("INSERT INTO machine_state (editor_username, machine, reported_at)"
                " VALUES ('a', 'M', ?)", (NOW,))
    old.commit()
    dbmod.migrate(old)
    assert old.execute("PRAGMA user_version").fetchone()[0] == 59
    row = old.execute("SELECT report_optouts, report_optouts_local, report_via, eula_json"
                      " FROM machine_state").fetchone()
    assert tuple(row) == (None, None, None, None)
    fresh = sqlite3.connect(":memory:")
    dbmod.migrate(fresh)
    assert _columns(old, "machine_state") == _columns(fresh, "machine_state")
    dbmod.migrate(old)                       # twice is a no-op
    assert old.execute("PRAGMA user_version").fetchone()[0] == 59
    old.close()


def test_v59_interrupted_between_two_add_columns_replays(tmp_path):
    c = dbmod.connect(tmp_path / "partial.db")
    dbmod.migrate(c, [s for s in dbmod._MIGRATION_STEPS if s[0] <= 58])
    c.execute("ALTER TABLE machine_state ADD COLUMN report_optouts TEXT")
    c.commit()
    dbmod.migrate(c)
    assert V59 <= _columns(c, "machine_state")
    c.close()


def test_an_older_image_refuses_a_v59_database(tmp_path):
    c = dbmod.connect(tmp_path / "new.db")
    dbmod.migrate(c)
    with pytest.raises(RuntimeError, match="newer than this build"):
        dbmod.migrate(c, [s for s in dbmod._MIGRATION_STEPS if s[0] <= 58])
    c.close()


# ---------------------------------------------------------------- LG-1

def _held(conn):
    _machine(conn, resolve_project="ProjectX", cap_resolve_project="ProjectX",
             cap_idle_seconds=42.0, sync_conflicts=3,
             resolve_journals=json.dumps([{"id": "j1", "project": "ProjectX"}]))
    _media(conn)
    dbmod.meta_set_json(conn, "resolve_health:tchen/TCHEN-RIG",
                        {"connected": True, "project_open": True,
                         "missing_clips": ["P:/x.mov"], "non_canonical_refused": ["F:/y"]})
    _diag(conn)
    conn.commit()


def test_clean_report_categories_drops_unknown_and_implies_media_tree():
    assert dbmod.clean_report_categories(["resolve_project", "bogus", 7]) == [
        "media_tree", "resolve_project"]
    assert dbmod.clean_report_categories("resolve_project") == []
    assert dbmod.clean_report_categories(None) == []


def test_withholding_the_project_name_clears_it_everywhere(conn):
    _held(conn)
    out = dbmod.apply_report_optouts(conn, "tchen", "TCHEN-RIG",
                                     ["resolve_project"], ["resolve_project"])
    row = conn.execute("SELECT * FROM machine_state").fetchone()
    assert row["resolve_project"] is None and row["cap_resolve_project"] is None
    assert json.loads(row["report_optouts"]) == ["media_tree", "resolve_project"]
    assert json.loads(row["report_optouts_local"]) == ["media_tree", "resolve_project"]
    assert dbmod.meta_get(conn, "resolve_health:tchen/TCHEN-RIG") is None
    # The id is masked too (final review 2026-09-25): it carries the project
    # slug, and the report path masks it the same way (note J).
    assert dbmod.machine_resolve_journals(conn, "tchen", "TCHEN-RIG") == [
        {"id": "withheld:project/j1", "project": ""}]
    assert _count(conn, "media_tree_clips") == 0          # implied media_tree
    assert _count(conn, "editor_media") == 1              # file list not withheld
    assert row["cap_idle_seconds"] == 42.0
    assert _count(conn, "diagnostics") == 0               # newly withheld
    assert out["newly"] == ["media_tree", "resolve_project"]


def test_withholding_the_file_list_keeps_counts_and_strips_paths(conn):
    _held(conn)
    dbmod.apply_report_optouts(conn, "tchen", "TCHEN-RIG", ["local_manifest"], ["local_manifest"])
    assert _count(conn, "editor_media") == 0
    assert _count(conn, "editor_media_project") == 0
    assert _count(conn, "media_tree_clips") == 1
    detail = dbmod.resolve_health_detail(conn, "tchen", "TCHEN-RIG")
    assert detail == {"connected": True, "project_open": True}
    row = conn.execute("SELECT * FROM machine_state").fetchone()
    assert row["sync_conflicts"] == 3 and row["resolve_project"] == "ProjectX"


def test_withholding_idle_nulls_it_and_keeps_diagnostics(conn):
    _held(conn)
    dbmod.apply_report_optouts(conn, "tchen", "TCHEN-RIG", ["input_idle"], ["input_idle"])
    row = conn.execute("SELECT * FROM machine_state").fetchone()
    assert row["cap_idle_seconds"] is None
    assert _count(conn, "diagnostics") == 1


def test_diagnostics_are_deleted_only_on_a_new_withhold(conn):
    _held(conn)
    dbmod.apply_report_optouts(conn, "tchen", "TCHEN-RIG", ["media_tree"], ["media_tree"])
    assert _count(conn, "diagnostics") == 0
    _diag(conn)
    out = dbmod.apply_report_optouts(conn, "tchen", "TCHEN-RIG", ["media_tree"], ["media_tree"])
    assert out["newly"] == []
    assert _count(conn, "diagnostics") == 1


def test_an_absent_section_under_no_site_policy_changes_nothing(conn):
    _held(conn)
    out = dbmod.apply_report_optouts(conn, "tchen", "TCHEN-RIG", [], None)
    row = conn.execute("SELECT * FROM machine_state").fetchone()
    assert row["report_optouts"] is None and row["report_optouts_local"] is None
    assert row["resolve_project"] == "ProjectX" and row["cap_idle_seconds"] == 42.0
    assert _count(conn, "editor_media") == 1 and _count(conn, "diagnostics") == 1
    assert out["deleted"] == {}
    assert dbmod.withheld(conn, "tchen", "TCHEN-RIG") == set()


def test_an_empty_list_is_nothing_withheld_not_old_build(conn):
    _held(conn)
    dbmod.apply_report_optouts(conn, "tchen", "TCHEN-RIG", [], [])
    row = conn.execute("SELECT * FROM machine_state").fetchone()
    assert row["report_optouts"] == "[]" and row["report_optouts_local"] == "[]"


def test_an_old_build_under_a_site_switch_is_recorded_and_cleared(conn):
    _held(conn)
    dbmod.apply_report_optouts(conn, "tchen", "TCHEN-RIG", ["local_manifest", "bogus"], None)
    row = conn.execute("SELECT * FROM machine_state").fetchone()
    assert json.loads(row["report_optouts"]) == ["local_manifest"]
    assert row["report_optouts_local"] is None
    assert _count(conn, "editor_media") == 0


def test_site_switch_clears_every_machine_at_once_including_offline(conn):
    _held(conn)
    _machine(conn, "rk", "RK-PC", cap_idle_seconds=9.0)
    # A machine whose state row aged out still owns media rows.
    _media(conn, "gone", "OLD-PC")
    conn.execute("UPDATE machine_state SET report_optouts_local=? WHERE editor_username='rk'",
                 (json.dumps(["input_idle"]),))
    out = dbmod.apply_site_optouts(conn, ["local_manifest"])
    assert _count(conn, "editor_media") == 0 and _count(conn, "editor_media_project") == 0
    assert _count(conn, "diagnostics") == 0
    assert dbmod.withheld(conn, "tchen", "TCHEN-RIG") == {"local_manifest"}
    assert dbmod.withheld(conn, "rk", "RK-PC") == {"local_manifest", "input_idle"}
    assert out["newly"] == ["local_manifest"]
    # Switching back on restores nothing and keeps the machine's own list.
    dbmod.apply_site_optouts(conn, [])
    assert dbmod.withheld(conn, "tchen", "TCHEN-RIG") == set()
    assert dbmod.withheld(conn, "rk", "RK-PC") == {"input_idle"}
    assert conn.execute("SELECT report_optouts FROM machine_state WHERE editor_username="
                        "'tchen'").fetchone()[0] is None


def test_withheld_map_and_machines_withholding(conn):
    _machine(conn)
    _machine(conn, "rk", "RK-PC")
    dbmod.apply_report_optouts(conn, "rk", "RK-PC", ["local_manifest"], ["local_manifest"])
    assert dbmod.withheld_map(conn) == {("rk", "RK-PC"): {"local_manifest"}}
    assert dbmod.machines_withholding(conn, "local_manifest") == {("rk", "RK-PC")}
    conn.execute("UPDATE machine_state SET report_optouts='not json' WHERE editor_username='rk'")
    assert dbmod.withheld(conn, "rk", "RK-PC") == set()


def _project(conn, slug="ff5", active=True):
    dbmod.upsert_project(conn, slug, slug.upper(), f"/p/{slug}", NOW)
    if not active:
        conn.execute("UPDATE projects SET active=0 WHERE slug=?", (slug,))


def test_file_move_targets_an_opted_out_machine_in_every_active_project(conn):
    _project(conn, "ff5")
    _project(conn, "old", active=False)
    _machine(conn, "tchen", "TCHEN-RIG")
    _machine(conn, "rk", "RK-PC")
    _machine(conn, "alex", "BASE", mode="base")
    for editor, machine in (("rk", "RK-PC"), ("alex", "BASE")):
        dbmod.apply_report_optouts(conn, editor, machine, ["local_manifest"], ["local_manifest"])
    # Nobody ticks ff5; the opted-out editing machine is still told.
    assert dbmod.file_move_target_machines(conn, "ff5", "Footage/A001.mov") == [
        ("rk", "RK-PC")]
    assert dbmod.file_move_target_machines(conn, "old", "Footage/A001.mov") == []


def test_backlog_not_reported_is_never_zero(conn):
    _project(conn, "ff5")
    _machine(conn, "rk", "RK-PC")
    dbmod.add_selection(conn, "rk", "ff5", "rk", NOW, machine="RK-PC")
    dbmod.apply_report_optouts(conn, "rk", "RK-PC", ["local_manifest"], ["local_manifest"])
    rows = dbmod.fetch_sync_backlog(conn)
    assert len(rows) == 1
    assert rows[0]["not_reported"] is True and rows[0]["uncertain"] is True
    # The uncertain-upload shape every reader already handles (review round).
    assert (rows[0]["lane"], rows[0]["direction"], rows[0]["kind"]) == ("a", "up", "original")
    assert rows[0]["n_files"] == 0 and rows[0]["bytes"] == 0
    assert dbmod.fetch_sync_backlog(conn, editor="tchen") == []


# ---------------------------------------------------------------- LG-4 / LG-5

def test_report_via_is_written_only_on_change_and_only_known_values(conn):
    _machine(conn)
    assert dbmod.set_machine_report_via(conn, "tchen", "TCHEN-RIG", "http_local") is True
    assert dbmod.set_machine_report_via(conn, "tchen", "TCHEN-RIG", "http_local") is False
    assert dbmod.set_machine_report_via(conn, "tchen", "TCHEN-RIG", "gopher") is False
    assert dbmod.set_machine_report_via(conn, "tchen", "TCHEN-RIG", "https") is True
    assert dbmod.report_via_map(conn) == {("tchen", "TCHEN-RIG"): "https"}


def test_eula_block_is_stored_and_absent_leaves_it(conn):
    _machine(conn)
    assert dbmod.machine_eula_map(conn) == {}
    dbmod.set_machine_eula(conn, "tchen", "TCHEN-RIG",
                           {"version": "1.1", "accepted_at": NOW, "eula_sha256": "ab" * 32,
                            "path": "C:/Users/x/eula.txt"})
    got = dbmod.machine_eula_map(conn)[("tchen", "TCHEN-RIG")]
    assert got == {"version": "1.1", "accepted_at": NOW, "eula_sha256": "ab" * 32}
    dbmod.set_machine_eula(conn, "tchen", "TCHEN-RIG", None)
    dbmod.set_machine_eula(conn, "tchen", "TCHEN-RIG", {"accepted_at": NOW})
    assert dbmod.machine_eula_map(conn)[("tchen", "TCHEN-RIG")]["version"] == "1.1"


# ---------------------------------------------------------------- LG-2 coverage

PERSON_COLUMN = re.compile(
    r"(editor|user)|_by$|^(actor|subject|holder|owner|sender|from_addr|contractor)$")


def _live_columns(conn) -> dict[str, list[str]]:
    return {
        t: [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')]
        for (t,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    }


def _parse_schema(texts: list[str]) -> dict[str, list[str]]:
    """Every CREATE TABLE (virtual tables excepted) and ADD COLUMN in `texts`,
    replayed into a scratch database so sqlite parses the column lists."""
    scratch = sqlite3.connect(":memory:")
    for text in texts:
        for m in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`]?(\w+)[\"`]?\s*\(",
                             text, re.I):
            depth, end = 0, m.end() - 1
            for j in range(m.end() - 1, len(text)):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
            body = re.sub(r"--[^\n]*", "", text[m.end():end])
            scratch.execute(f'CREATE TABLE IF NOT EXISTS "{m.group(1)}" ({body})')
        for m in re.finditer(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+(?:COLUMN\s+)?(\w+)", text, re.I):
            try:
                scratch.execute(f'ALTER TABLE "{m.group(1)}" ADD COLUMN "{m.group(2)}"')
            except sqlite3.OperationalError:
                pass                    # a rebuild migration re-adding a column
    return _live_columns(scratch)


def _store_files(base: str) -> list[str]:
    root = REPO / base
    return [(root / "schema.sql").read_text(encoding="utf-8")] + [
        p.read_text(encoding="utf-8") for p in sorted((root / "migrations").glob("*.sql"))]


def _all_stores(dashboard_conn) -> dict[str, dict[str, list[str]]]:
    sess = sqlite3.connect(":memory:")
    sess.executescript(sessions.SCHEMA)
    return {
        "dashboard": _live_columns(dashboard_conn),
        "sessions": _live_columns(sess),
        "ytdl": _parse_schema(_store_files("ytdl/web")),
        "broll": _parse_schema(_store_files("broll/web")),
        "music": _parse_schema(_store_files("music/web")),
        "client_shares": _parse_schema(
            [(REPO / "broll/web/app/client_folders.py").read_text(encoding="utf-8")]),
    }


def _uncovered(stores) -> list[str]:
    registered = {e.table for e in dbmod.SUBJECT_TABLES}
    bad = []
    for store, tables in stores.items():
        for table, cols in tables.items():
            hits = [c for c in cols if PERSON_COLUMN.search(c)]
            if not hits:
                continue
            if store == "dashboard":
                if table in registered or table in dbmod.NOT_SUBJECT_TABLES:
                    continue
            elif (table in dbmod.OTHER_STORE_SUBJECT_TABLES.get(store, {})
                  or table in dbmod.NOT_SUBJECT_TABLES_OTHER_STORES.get(store, {})):
                continue
            bad.append(f"{store}.{table} {hits}")
    return bad


def test_every_table_that_names_a_person_is_registered(conn):
    stores = _all_stores(conn)
    assert stores["ytdl"] and stores["broll"] and stores["music"] and stores["client_shares"]
    assert _uncovered(stores) == [], (
        "a table names a person but is in neither db.SUBJECT_TABLES (or the other "
        "stores' registry) nor NOT_SUBJECT_TABLES with a reason: add it, so export "
        "and delete cannot miss it")


def test_a_planted_person_column_fails_the_coverage_check(conn):
    conn.execute("ALTER TABLE poll_runs ADD COLUMN editor_username TEXT")
    stores = _all_stores(conn)
    assert _uncovered(stores) == ["dashboard.poll_runs ['editor_username']"]


def test_every_registry_row_names_a_real_table_and_a_known_kind(conn):
    tables = _tables(conn)
    kinds = {dbmod.SUBJECT_HISTORY, dbmod.SUBJECT_CURRENT, dbmod.SUBJECT_IDENTITY,
             dbmod.SUBJECT_EVIDENCE}
    for entry in dbmod.SUBJECT_TABLES:
        assert entry.table in tables, entry.table
        assert entry.kind in kinds
        assert set(entry.columns_excluded) <= _columns(conn, entry.table)
    for reason in dbmod.NOT_SUBJECT_TABLES.values():
        assert len(reason) > 40


def test_export_rows_carry_no_secret_column(conn):
    conn.execute("INSERT INTO users (username, password_hash, role, created_at)"
                 " VALUES ('tchen', 'pbkdf2$secret', 'editor', ?)", (NOW,))
    dbmod.create_editor_report_token(conn, "tchen", "admin", now=NOW)
    _machine(conn)
    rows = dbmod.fetch_subject_rows(conn, "TChen")
    assert set(rows) == {e.table for e in dbmod.SUBJECT_TABLES}
    assert rows["users"] and "password_hash" not in rows["users"][0]
    assert rows["editor_report_tokens"] and "token_hash" not in rows["editor_report_tokens"][0]
    assert rows["machine_state"][0]["machine"] == "TCHEN-RIG"


def test_notice_subject_match_is_not_a_like_wildcard(conn):
    dbmod.notice(conn, "k", "warn", "t_chen/PC", body="x", now=NOW)
    dbmod.notice(conn, "k", "warn", "tXchen/PC", body="x", now=NOW)
    rows = dbmod.fetch_subject_rows(conn, "t_chen")["notices"]
    assert [r["subject"] for r in rows] == ["t_chen/PC"]


# ---------------------------------------------------------------- LG-3

def test_erase_history_keeps_every_current_column_and_the_media(conn):
    _machine(conn, mode="base", guard_at=NOW, breaker_tripped=1, halt_active=1,
             verified=1, cfg_accepts='["x"]', cfg_at=NOW)
    _media(conn)
    _diag(conn)
    conn.execute("INSERT INTO lane_report_history (editor_username, machine, lane, state, ts)"
                 " VALUES ('tchen', 'TCHEN-RIG', 'a', 'idle', ?)", (NOW,))
    conn.execute("INSERT INTO transfer_history (editor_username, machine, lane, name,"
                 " direction, completed_at, received_at) VALUES"
                 " ('tchen','TCHEN-RIG','a','A001.mov','up',?,?)", (NOW, NOW))
    before = dict(conn.execute("SELECT * FROM machine_state").fetchone())
    counts = dbmod.purge_subject_history(conn, "tchen")
    assert counts["lane_report_history"] == 1 and counts["transfer_history"] == 1
    assert counts["diagnostics"] == 1
    assert dict(conn.execute("SELECT * FROM machine_state").fetchone()) == before
    assert _count(conn, "editor_media") == 1 and _count(conn, "machines") == 1


def test_the_pseudonym_is_stable_and_not_the_session_secret(conn):
    first = dbmod.pseudonym(conn, "Alice")
    assert re.fullmatch(r"deleted-user-[0-9a-f]{10}", first)
    dbmod.meta_set(conn, "session_secrets_previous", '["rotated"]')
    assert dbmod.pseudonym(conn, "alice") == first
    assert dbmod.machine_pseudonym(conn, "PC").startswith("deleted-machine-")
    assert dbmod.pseudonym(conn, "bob") != first


def test_whole_word_pseudonymising_leaves_alice2_alone(conn):
    dbmod.audit(conn, "admin", "plan.tick", "alice/ALICE-PC",
                {"note": "alice and alice2 and ALICE-PC"}, now=NOW)
    dbmod.audit(conn, "admin", "plan.tick", "alice2", {"who": "alice2"}, now=NOW)
    dbmod.record_alert(conn, "k", "alice", "ops@x", True, detail="alice's laptop", now=NOW)
    dbmod.pseudonymise_subject(conn, "alice", ["ALICE-PC"])
    stand_in = dbmod.pseudonym(conn, "alice")
    m = dbmod.machine_pseudonym(conn, "ALICE-PC")
    rows = conn.execute("SELECT subject, detail_json FROM fleet_audit ORDER BY id").fetchall()
    assert rows[0]["subject"] == f"{stand_in}/{m}"
    assert json.loads(rows[0]["detail_json"]) == {"note": f"{stand_in} and alice2 and {m}"}
    assert rows[1]["subject"] == "alice2" and "alice2" in rows[1]["detail_json"]
    alert = conn.execute("SELECT subject, detail FROM alert_log").fetchone()
    assert alert["subject"] == stand_in and alert["detail"] == f"{stand_in}'s laptop"


def test_a_machine_name_another_person_uses_is_not_rewritten(conn):
    _machine(conn, "bob", "DESKTOP")
    dbmod.notice(conn, "k", "warn", "DESKTOP", body="DESKTOP is late", now=NOW)
    dbmod.pseudonymise_subject(conn, "alice", ["DESKTOP"])
    assert conn.execute("SELECT subject FROM notices").fetchone()[0] == "DESKTOP"


def test_a_notices_collision_keeps_the_newer_row(conn):
    stand_in = dbmod.pseudonym(conn, "alice")
    dbmod.notice(conn, "k", "warn", stand_in, body="new", now=_iso(60))
    dbmod.notice(conn, "k", "warn", "alice", body="old", now=NOW)
    dbmod.notice(conn, "j", "warn", "alice", body="only", now=NOW)
    dbmod.pseudonymise_subject(conn, "alice")
    rows = {(r["kind"], r["body"]) for r in conn.execute("SELECT kind, body FROM notices")}
    assert rows == {("k", "new"), ("j", "only")}
    assert {r[0] for r in conn.execute("SELECT subject FROM notices")} == {stand_in}


def test_forget_editor_completes_the_delete(conn):
    _machine(conn, "alice", "ALICE-PC")
    _diag(conn, "alice", "ALICE-PC")
    conn.execute("INSERT INTO lane_report_history (editor_username, machine, lane, state, ts)"
                 " VALUES ('alice', 'ALICE-PC', 'a', 'idle', ?)", (NOW,))
    dbmod.audit(conn, "alice", "plan.tick", "alice/ALICE-PC", {}, now=NOW)
    dbmod.audit(conn, "admin", "user.suspend", "alice", {}, now=NOW)
    conn.execute("INSERT INTO jobs (kind, created_at, created_by, inputs_json, requires_json,"
                 " state, claimed_by, claimed_machine, updated_at)"
                 " VALUES ('whisper', ?, 'alice', '{}', '{}', 'done', 'alice', 'ALICE-PC', ?)",
                 (NOW, NOW))
    out = dbmod.forget_editor(conn, "alice", was_admin=False)
    stand_in = dbmod.pseudonym(conn, "alice")
    assert out["pseudonym"] == stand_in
    assert _count(conn, "lane_report_history") == 0 and _count(conn, "diagnostics") == 0
    audit = conn.execute("SELECT actor, subject FROM fleet_audit ORDER BY id").fetchall()
    assert audit[0]["actor"] == stand_in and audit[0]["subject"].startswith(stand_in + "/")
    assert audit[1]["actor"] == "admin" and audit[1]["subject"] == stand_in
    job = conn.execute("SELECT created_by, claimed_by, claimed_machine FROM jobs").fetchone()
    assert job["created_by"] == stand_in and job["claimed_by"] == stand_in
    assert job["claimed_machine"].startswith("deleted-machine-")
    assert "alice" not in json.dumps(
        [dict(r) for r in conn.execute("SELECT * FROM fleet_audit")])


def test_an_admins_actor_name_is_kept_until_the_audit_prune(conn):
    conn.execute("INSERT INTO users (username, password_hash, role, created_at)"
                 " VALUES ('boss', 'x', 'admin', ?)", (NOW,))
    dbmod.audit(conn, "boss", "user.delete", "someone", {}, now=NOW)
    dbmod.forget_editor(conn, "boss")
    assert conn.execute("SELECT actor FROM fleet_audit").fetchone()[0] == "boss"


def test_revoked_tokens_are_deleted_after_revocation_and_pruned_at_180_days(conn):
    _t1, live = dbmod.create_editor_report_token(conn, "alice", "admin", now=NOW)
    _t2, dead = dbmod.create_editor_report_token(conn, "alice", "admin", now=NOW)
    dbmod.revoke_editor_report_token(conn, dead["token_id"], "admin", now=NOW)
    assert dbmod.delete_revoked_report_tokens(conn, "alice") == 1
    assert _count(conn, "editor_report_tokens") == 1
    _t3, old = dbmod.create_editor_report_token(conn, "bob", "admin", now=NOW)
    dbmod.revoke_editor_report_token(conn, old["token_id"], "admin", now=NOW)
    dbmod.prune(conn, _iso(179 * 86400))
    assert _count(conn, "editor_report_tokens") == 2
    dbmod.prune(conn, _iso(181 * 86400))
    assert _count(conn, "editor_report_tokens") == 1
    assert conn.execute("SELECT token_id FROM editor_report_tokens").fetchone()[0] == \
        live["token_id"]


# ---------------------------------------------------------------- LG-17

def _runs(conn, kind, starts, ok=True, error=None):
    for s in starts:
        dbmod.record_poll_run(conn, kind, s, s, ok, error)
    conn.commit()


def _kind(health, name):
    return next(k for k in health["kinds"] if k["kind"] == name)


def test_retention_overdue_just_past_the_bound_and_ok_just_inside(conn):
    _runs(conn, "prune", [_iso(0), _iso(3600)])
    bound = dbmod.collector_kind_overdue_after("prune", 3600.0)
    assert bound == 7200.0
    # A live collector: a faster kind keeps starting, so collector_stale is
    # false and prune's own lateness is what is judged (review round: a
    # stale collector suppresses per-kind overdue).
    _runs(conn, "alerts", [_iso(3600 + bound - 600), _iso(3600 + bound)])
    inside = dbmod.collector_health(conn, now=_iso(3600 + bound - 1))
    assert _kind(inside, "prune")["status"] == "green"
    assert _kind(inside, "prune")["overdue"] is False
    assert inside["retention_last_ran"] == _iso(3600)
    past = dbmod.collector_health(conn, now=_iso(3600 + bound + 1))
    row = _kind(past, "prune")
    assert row["status"] == "amber" and row["note"] == "overdue" and row["overdue"] is True


def test_an_unscheduled_kind_is_never_overdue(conn):
    _runs(conn, "enforce", [_iso(0), _iso(60)])
    health = dbmod.collector_health(conn, now=_iso(86400))
    assert _kind(health, "enforce")["overdue"] is False
    assert _kind(health, "enforce")["status"] == "green"

    class _NoSyncthing:
        syncthing_url = ""
        projects_dir = ""
    assert dbmod.collector_kind_scheduled("enforce", _NoSyncthing()) is False
    assert dbmod.collector_kind_scheduled("prune", _NoSyncthing()) is True

    class _Full(_NoSyncthing):
        syncthing_url = "http://st:8384"
    assert dbmod.collector_kind_scheduled("enforce", _Full()) is True
    assert dbmod.collector_kind_scheduled("inventory", _Full()) is False


def test_a_failed_kind_stays_red_not_overdue(conn):
    _runs(conn, "prune", [_iso(0)], ok=False, error="disk full")
    row = _kind(dbmod.collector_health(conn, now=_iso(86400)), "prune")
    assert row["status"] == "red" and row["overdue"] is False and row["note"] == "disk full"


def test_retention_never_ran_is_none(conn):
    assert dbmod.collector_health(conn, now=NOW)["retention_last_ran"] is None


# ---------------------------------------------------------------- review round
# The adversarial review of G0 (2026-09-25). Each test below fails on the
# first build.

def test_deleting_alice_leaves_alice_b_and_alice_smith_alone_and_their_notice_clears(conn):
    dbmod.notice(conn, "k", "warn", "alice-b/LAPTOP", body="alice-b's LAPTOP is late", now=NOW)
    dbmod.audit(conn, "admin", "plan.undo", "ff5", {"editor": "alice.smith"}, now=NOW)
    dbmod.record_alert(conn, "k", "alice-b/LAPTOP", "ops@x", True,
                       detail="alice-b and Alice", now=NOW)
    dbmod.pseudonymise_subject(conn, "alice", ["ALICE-PC"])
    assert conn.execute("SELECT subject, body FROM notices").fetchone()[:] == (
        "alice-b/LAPTOP", "alice-b's LAPTOP is late")
    assert json.loads(conn.execute("SELECT detail_json FROM fleet_audit").fetchone()[0]) == {
        "editor": "alice.smith"}
    assert conn.execute("SELECT subject, detail FROM alert_log").fetchone()[:] == (
        "alice-b/LAPTOP", "alice-b and Alice")
    assert dbmod.clear_notice(conn, "k", "alice-b/LAPTOP", now=NOW) is True


def test_a_common_word_username_does_not_rewrite_site_copy(conn):
    dbmod.notice(conn, "alerts_delivery_slow", "warn", "delivery",
                 body="Send a test email", fix="Press the Test button, then test again",
                 now=NOW)
    dbmod.audit(conn, "admin", "site.settings_save", "site",
                {"note": "the test button"}, now=NOW)
    dbmod.notice(conn, "k", "warn", "test/PC", body="test's PC is late", now=NOW)
    dbmod.pseudonymise_subject(conn, "test")
    stand_in = dbmod.pseudonym(conn, "test")
    site = conn.execute("SELECT body, fix FROM notices WHERE subject='delivery'").fetchone()
    assert site[:] == ("Send a test email", "Press the Test button, then test again")
    assert "the test button" in conn.execute("SELECT detail_json FROM fleet_audit").fetchone()[0]
    # Their own notice is still pseudonymised, prose included.
    own = conn.execute("SELECT subject, body FROM notices WHERE subject<>'delivery'").fetchone()
    assert own[:] == (f"{stand_in}/PC", f"{stand_in}'s PC is late")


def test_a_deleted_persons_machine_named_like_a_system_key_leaves_that_notice(conn):
    _machine(conn, "alice", "server")
    dbmod.notice(conn, "syncthing_unreachable", "error", "server", body="x", now=NOW)
    dbmod.audit(conn, "admin", "machine.forget", "server",
                {"editor": "alice", "machine": "server"}, now=NOW)
    dbmod.pseudonymise_subject(conn, "alice", ["server"])
    assert conn.execute("SELECT subject FROM notices").fetchone()[0] == "server"
    assert dbmod.clear_notice(conn, "syncthing_unreachable", "server", now=NOW) is True
    # The audit row IS tied to alice by its detail, so its bare machine goes.
    row = conn.execute("SELECT subject, detail_json FROM fleet_audit").fetchone()
    m = dbmod.machine_pseudonym(conn, "server")
    assert row["subject"] == m
    assert json.loads(row["detail_json"]) == {
        "editor": dbmod.pseudonym(conn, "alice"), "machine": m}


def test_an_export_never_carries_another_owner_of_the_same_hostname(conn):
    _machine(conn, "alice", "MacBook-Pro")
    _machine(conn, "bob", "MacBook-Pro")
    _machine(conn, "alice", "ALICE-ONLY")
    dbmod.notice(conn, "k", "warn", "MacBook-Pro",
                 body="bob's MacBook-Pro tripped: /Users/bob/secret-project", now=NOW)
    dbmod.notice(conn, "k", "warn", "ALICE-ONLY", body="alice's", now=NOW)
    dbmod.audit(conn, "admin", "machine.forget", "MacBook-Pro",
                {"editor": "bob", "machine": "MacBook-Pro"}, now=NOW)
    dbmod.audit(conn, "admin", "machine.update_push", "MacBook-Pro",
                {"editor": "alice", "machine": "MacBook-Pro"}, now=NOW)
    conn.execute("INSERT INTO fleet_audit (at, actor, action, subject, detail_json)"
                 " VALUES (?, 'admin', 'x', 'MacBook-Pro', 'not json')", (NOW,))
    rows = dbmod.fetch_subject_rows(conn, "alice")
    assert [r["subject"] for r in rows["notices"]] == ["ALICE-ONLY"]
    audit = [json.loads(r["detail_json"]) for r in rows["fleet_audit"]]
    assert audit == [{"editor": "alice", "machine": "MacBook-Pro"}]


def test_a_report_without_the_key_keeps_the_machines_own_list(conn):
    _held(conn)
    dbmod.apply_report_optouts(conn, "tchen", "TCHEN-RIG", ["media_tree"], ["media_tree"])
    _diag(conn)
    out = dbmod.apply_report_optouts(conn, "tchen", "TCHEN-RIG", [], None)
    row = conn.execute("SELECT * FROM machine_state").fetchone()
    assert json.loads(row["report_optouts_local"]) == ["media_tree"]
    assert dbmod.withheld(conn, "tchen", "TCHEN-RIG") == {"media_tree"}
    assert out["newly"] == []
    # The next well-formed report is not "newly withheld": diagnostics stay.
    out = dbmod.apply_report_optouts(conn, "tchen", "TCHEN-RIG", ["media_tree"], ["media_tree"])
    assert out["newly"] == [] and _count(conn, "diagnostics") == 1
    # An explicit empty list still switches it back on.
    dbmod.apply_report_optouts(conn, "tchen", "TCHEN-RIG", [], [])
    assert dbmod.withheld(conn, "tchen", "TCHEN-RIG") == set()


def test_a_not_reported_machine_is_never_safe_to_close(conn):
    from ccsync_dashboard import api, ui
    _project(conn, "ff5")
    _machine(conn, "rk", "RK-PC")
    dbmod.add_selection(conn, "rk", "ff5", "rk", NOW, machine="RK-PC")
    dbmod.apply_report_optouts(conn, "rk", "RK-PC", ["local_manifest"], ["local_manifest"])
    conn.commit()
    view = api.build_transfers_view(conn, now=NOW, editor="rk")
    assert [q.get("not_reported") for q in view["queues"]] == [True]
    verdict = ui.safe_to_close(view, "rk")
    assert verdict["safe"] is False and verdict["sentence"].startswith("Cannot tell yet")


def test_slow_cycle_does_not_make_a_fast_kind_overdue(conn):
    # One cycle: inventory for 240 s, then connections (15 s cadence).
    conn.execute("INSERT INTO poll_runs (kind, started_at, finished_at, ok)"
                 " VALUES ('inventory', ?, ?, 1)", (_iso(0), _iso(240)))
    _runs(conn, "connections", [_iso(-15), _iso(0)])
    _runs(conn, "alerts", [_iso(200), _iso(240)])
    assert dbmod.collector_cycle_seconds(conn) == 240.0

    class _Full:
        syncthing_url = "http://st:8384"
        projects_dir = "/p"
    health = dbmod.collector_health(conn, now=_iso(241), settings=_Full())
    assert _kind(health, "connections")["overdue"] is False


def test_a_stopped_collector_is_stale_not_overdue_per_kind(conn):
    _runs(conn, "prune", [_iso(0), _iso(3600)])
    _runs(conn, "alerts", [_iso(3000), _iso(3600)])
    health = dbmod.collector_health(conn, now=_iso(86400))
    assert health["collector_stale"] is True
    assert not any(k["overdue"] for k in health["kinds"])
