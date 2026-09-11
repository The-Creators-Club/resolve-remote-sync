"""Hand moves on the server, recognised by the inventory walk.

docs/HAND_MOVES_ON_THE_SERVER.md phase 1 (2026-09-11). Somebody moves a shoot
in Explorer on the NAS; the collector sees it as a (basename, size, mtime) that
vanished from one path and appeared at exactly one other, and writes the same
`file_moves` row the project page's button writes, with `source='detected'`.
From there the fleet follows it exactly as if the button had been pressed
(docs/FILE_MOVES.md).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import collector as collector_mod
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import provision
from ccsync_dashboard.app import create_app
from ccsync_dashboard.collector import Collector, DetectedMove, InventoryWalk, detect_moves
from ccsync_dashboard.settings import Settings

DRONE = "2026/Base Drone"
ANIMALS = "2026/FF5/Animals"
D_SLUG = "2026-base-drone"
A_SLUG = "2026-ff5-animals"
PREFIX = "/data/Projects"


# --------------------------------------------------------------- the matcher

def walk(slug, project_rel, old, new):
    """old/new as [(rel, kind, size, mtime_ns)]."""
    return InventoryWalk(slug=slug, project_rel=project_rel, old=list(old), new=list(new))


def orig(rel, size=100, mtime=111):
    return (rel, "original", size, mtime)


def proxy(rel, size=10, mtime=222):
    return (rel, "proxy", size, mtime)


def test_a_file_moved_inside_one_project_is_one_move_with_its_proxy():
    moves = detect_moves([walk(
        D_SLUG, DRONE,
        old=[orig("B-roll/A001.braw"), proxy("B-roll/Proxy/A001.mov"),
             orig("B-roll/A002.braw", size=200)],
        new=[orig("Interviews/A001.braw"), proxy("Interviews/Proxy/A001.mov"),
             orig("B-roll/A002.braw", size=200)],
    )])
    assert moves == [DetectedMove(
        from_slug=D_SLUG, from_project_rel=DRONE, from_rel="B-roll/A001.braw",
        to_slug=D_SLUG, to_project_rel=DRONE, to_rel="Interviews/A001.braw",
        is_dir=False, n_files=2, proxies_moved=1)]


def test_a_whole_folder_is_one_row_not_one_per_file():
    moves = detect_moves([walk(
        D_SLUG, DRONE,
        old=[orig("B-roll/A001.braw"), orig("B-roll/A002.braw", size=200),
             proxy("B-roll/Proxy/A001.mov")],
        new=[orig("Archive/B-roll/A001.braw"), orig("Archive/B-roll/A002.braw", size=200),
             proxy("Archive/B-roll/Proxy/A001.mov")],
    )])
    assert [(m.from_rel, m.to_rel, m.is_dir, m.n_files) for m in moves] == [
        ("B-roll", "Archive/B-roll", True, 3)]


def test_a_move_between_two_projects_is_matched_across_the_pass():
    """The half that made today's incident invisible: a shoot that left
    Creator Profiles for FF5 Talent Gap is a vanish in one walk and an
    appearance in another, so the match happens after every project in the
    pass has been walked."""
    moves = detect_moves([
        walk(D_SLUG, DRONE,
             old=[orig("B-roll/A001.braw")], new=[]),
        walk(A_SLUG, ANIMALS,
             old=[], new=[orig("Interviewees/Pangolin/A001.braw")]),
    ])
    assert [(m.from_slug, m.from_rel, m.to_slug, m.to_rel) for m in moves] == [
        (D_SLUG, "B-roll/A001.braw", A_SLUG, "Interviewees/Pangolin/A001.braw")]


def test_two_destinations_is_an_ambiguity_and_an_ambiguity_is_a_refusal():
    """A file copied twice and the original then deleted. Nothing is
    recorded: it stays a deletion for lane B, and the breaker keeps its say."""
    assert detect_moves([walk(
        D_SLUG, DRONE,
        old=[orig("B-roll/A001.braw")],
        new=[orig("Interviews/A001.braw"), orig("Archive/A001.braw")],
    )]) == []
    # ...and the same the other way round: two files gone, one arrival.
    assert detect_moves([walk(
        D_SLUG, DRONE,
        old=[orig("B-roll/A001.braw"), orig("Archive/A001.braw")],
        new=[orig("Interviews/A001.braw")],
    )]) == []


def test_a_deletion_is_not_a_move_and_nothing_here_touches_it():
    assert detect_moves([walk(
        D_SLUG, DRONE,
        old=[orig("B-roll/A001.braw"), orig("B-roll/A002.braw", size=200)],
        new=[orig("B-roll/A002.braw", size=200)],
    )]) == []


def test_a_proxy_folder_left_behind_is_not_a_move():
    """Today's Gold Card Meetup case: Explorer took the originals and one
    Proxy folder, and left a byte-identical Proxy folder at the old path. That
    is not one rename, so the folder is not recorded as a move; the originals
    that did go are recorded one by one and the leftovers stay a proxy_pairs
    finding."""
    moves = detect_moves([walk(
        D_SLUG, DRONE,
        old=[orig("Interviews/A001.braw"), orig("Interviews/A002.braw", size=200),
             proxy("Interviews/Proxy/A001.mov"),
             proxy("Interviews/Proxy/A002.mov", size=20)],
        new=[orig("Talent/Interviews/A001.braw"),
             orig("Talent/Interviews/A002.braw", size=200),
             # the leftover pair, still at the old path
             proxy("Interviews/Proxy/A001.mov"),
             proxy("Interviews/Proxy/A002.mov", size=20)],
    )])
    assert [(m.from_rel, m.is_dir, m.proxies_moved) for m in moves] == [
        ("Interviews/A001.braw", False, 0),
        ("Interviews/A002.braw", False, 0),
    ]
    assert not any(m.from_rel.lower().endswith("proxy") for m in moves)


def test_a_proxy_folder_moved_on_its_own_is_nobodys_move():
    """A proxy travels with its original: the button refuses a `Proxy` folder
    as either end, and a detected move may not do what the button refused."""
    assert detect_moves([walk(
        D_SLUG, DRONE,
        old=[proxy("B-roll/Proxy/A001.mov"), orig("B-roll/A001.braw")],
        new=[proxy("Archive/Proxy/A001.mov"), orig("B-roll/A001.braw")],
    )]) == []


def test_a_file_nothing_could_stat_matches_nothing():
    """Two NULLs are not evidence that two files are the same file."""
    assert detect_moves([walk(
        D_SLUG, DRONE,
        old=[("B-roll/A001.braw", "original", None, None)],
        new=[("Interviews/A001.braw", "original", None, None)],
    )]) == []


# ------------------------------------------------------------- the collector

@pytest.fixture
def env(conn, tmp_path):
    projects = tmp_path / "projects"
    for rel, slug in ((DRONE, D_SLUG), (ANIMALS, A_SLUG)):
        d = projects / rel
        d.mkdir(parents=True)
        provision.write_marker(d, slug)
        (d / ".stfolder").mkdir()
    broll = projects / DRONE / "B-roll"
    (broll / "Proxy").mkdir(parents=True)
    (broll / "A001_0512.braw").write_bytes(b"braw" * 10)
    (broll / "Proxy" / "A001_0512.mp4").write_bytes(b"proxy")
    # A second original that never moves: a project whose originals ALL leave
    # trips the collapse brake (DASH-5), which keeps the old inventory and so
    # has nothing to diff. That is the safe direction and it is deliberate,
    # but it is not the case under test here.
    (broll / "A002_0513.braw").write_bytes(b"braw2" * 10)
    (projects / ANIMALS / "Interviewees").mkdir(parents=True)

    settings = Settings(projects_dir=str(projects), db_path=str(tmp_path / "test.db"),
                        syncthing_data_prefix=PREFIX, inventory_projects_per_cycle=20)
    now = dbmod.utcnow_iso()
    for rel, slug in ((DRONE, D_SLUG), (ANIMALS, A_SLUG)):
        dbmod.upsert_project(conn, slug, rel, f"{PREFIX}/{rel}", now)
    conn.commit()
    # client=object(): the inventory cycle never touches Syncthing, and a
    # client that would is a second thing this test could fail on.
    return Collector(settings, client=object()), conn, projects


def moves_in(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM file_moves ORDER BY id")]


def test_a_hand_move_between_two_walks_becomes_a_detected_row_the_fleet_follows(env):
    collector, conn, projects = env
    now = dbmod.utcnow_iso()
    # One computer syncs the source project, a second only reported holding
    # the file: both have to be told (db.file_move_target_machines).
    dbmod.upsert_machine(conn, "leso", "LESO-PC", now)
    dbmod.upsert_machine(conn, "leso", "LESO-LAPTOP", now)
    dbmod.add_selection(conn, "leso", D_SLUG, "owen", now, machine="LESO-PC")
    dbmod.replace_editor_media(conn, "leso", "LESO-LAPTOP", D_SLUG,
                               [("B-roll/A001_0512.braw", "original", 40)], now)
    conn.commit()
    assert collector._run_inventory(conn) is None
    assert moves_in(conn) == []

    # The move somebody makes in Explorer, original and proxy together.
    dest = projects / ANIMALS / "Interviewees" / "Pangolin"
    (dest / "Proxy").mkdir(parents=True)
    (projects / DRONE / "B-roll" / "A001_0512.braw").rename(dest / "A001_0512.braw")
    (projects / DRONE / "B-roll" / "Proxy" / "A001_0512.mp4").rename(
        dest / "Proxy" / "A001_0512.mp4")

    note = collector._run_inventory(conn)
    assert note and "1 move(s) detected" in note
    (row,) = moves_in(conn)
    assert row["source"] == "detected"
    assert row["state"] == dbmod.FILE_MOVE_DONE          # the rename already happened
    assert row["from_slug"] == D_SLUG and row["from_rel"] == "B-roll/A001_0512.braw"
    assert row["to_slug"] == A_SLUG
    assert row["to_rel"] == "Interviewees/Pangolin/A001_0512.braw"
    assert row["from_project_rel"] == DRONE and row["to_project_rel"] == ANIMALS
    assert row["is_dir"] == 0 and row["proxies_moved"] == 1
    # Both computers are told, through the machinery FILE_MOVES.md describes.
    machines = sorted(r["machine"] for r in conn.execute(
        "SELECT machine FROM file_move_targets WHERE move_id=?", (row["id"],)))
    assert machines == ["LESO-LAPTOP", "LESO-PC"]
    offered = dbmod.pending_file_moves(conn, "leso", "LESO-PC", dbmod.utcnow_iso())
    assert [m["to_rel"] for m in offered] == ["Interviewees/Pangolin/A001_0512.braw"]

    # ...and the owner is told what happened, for information only.
    (notice,) = [dict(r) for r in conn.execute(
        "SELECT * FROM notices WHERE kind='file_move_detected'")]
    assert notice["severity"] == "info"
    assert notice["subject"] == f"{ANIMALS}/Interviewees/Pangolin/A001_0512.braw"
    assert "B-roll/A001_0512.braw" in notice["body"] and "2 computer(s)" in notice["body"]
    assert notice["fix"].startswith("Nothing to do")


def test_the_same_move_seen_twice_is_recorded_once(env):
    """The walk can race a long Explorer move, and a second row would mean a
    second command to every machine for a move it has already applied."""
    collector, conn, projects = env
    collector._run_inventory(conn)
    dest = projects / ANIMALS / "Interviewees"
    (projects / DRONE / "B-roll" / "A001_0512.braw").rename(dest / "A001_0512.braw")
    collector._run_inventory(conn)
    assert len(moves_in(conn)) == 1

    # The detection is handed the identical diff a second time (the shape a
    # walk that was refused, or a partner project walked late, produces).
    walks = [walk(D_SLUG, DRONE, old=[orig("B-roll/A001_0512.braw")], new=[]),
             walk(A_SLUG, ANIMALS, old=[], new=[orig("Interviewees/A001_0512.braw")])]
    assert collector._record_detected_moves(conn, walks, dbmod.utcnow_iso()) == 0
    assert len(moves_in(conn)) == 1


def test_detection_never_takes_the_inventory_walk_down_with_it(env, monkeypatch):
    """The walk is what tells every editor whether their footage is on the
    server. Recognising a hand move is a convenience on top of it."""
    collector, conn, projects = env
    monkeypatch.setattr(collector_mod, "detect_moves",
                        lambda walks: (_ for _ in ()).throw(RuntimeError("boom")))
    assert collector._run_inventory(conn) is None
    pid = conn.execute("SELECT id FROM projects WHERE slug=?", (D_SLUG,)).fetchone()["id"]
    assert dbmod.fetch_nas_media_summary(conn, pid)["n_originals"] == 2


def test_a_pass_records_at_most_the_cap(env, monkeypatch):
    collector, conn, projects = env
    monkeypatch.setattr(collector_mod, "DETECTED_MOVE_LIMIT", 2)
    walks = [walk(D_SLUG, DRONE,
                  old=[orig(f"B-roll/A{i:03d}.braw", size=100 + i) for i in range(5)],
                  new=[orig(f"Archive/A{i:03d}.braw", size=100 + i) for i in range(5)])]
    # Five separate files, each with its own key: five moves, two recorded.
    assert collector._record_detected_moves(conn, walks, dbmod.utcnow_iso()) == 2
    assert len(moves_in(conn)) == 2


def test_the_check_is_evidenced_even_on_a_pass_that_found_nothing(env):
    """A kind with no evidence renders [ NOT CHECKED ] on the checks panel,
    and a fleet that has never had a hand move must not read as unchecked."""
    collector, conn, projects = env
    collector._run_inventory(conn)
    assert "file_move_detected" in dbmod.notice_check_times(conn)
    assert "file_move_detected" in {k["kind"] for k in dbmod.notice_kinds()}


# ------------------------------------------------------- the button and the column

def test_the_migration_adds_the_column_and_every_existing_row_reads_admin(tmp_path):
    """v53. Every file_moves row that predates the column was an admin at the
    project page's button, which is exactly what the DEFAULT says."""
    path = tmp_path / "older.db"
    conn = dbmod.connect(path)
    older = [step for step in dbmod._MIGRATION_STEPS if step[0] <= 52]
    dbmod.migrate(conn, steps=older)
    assert "source" not in {r["name"] for r in conn.execute("PRAGMA table_info(file_moves)")}
    conn.execute(
        """INSERT INTO file_moves (from_slug, from_project_rel, from_rel, to_slug,
                                   to_project_rel, to_rel, is_dir, proxies_moved,
                                   requested_by, requested_at)
           VALUES ('a', 'A', 'x.braw', 'b', 'B', 'x.braw', 0, 0, 'owen',
                   '2026-09-10T00:00:00+00:00')""")
    conn.commit()

    dbmod.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == dbmod.SCHEMA_VERSION
    assert [r["source"] for r in conn.execute("SELECT source FROM file_moves")] == ["admin"]
    conn.close()


@pytest.fixture
def button(tmp_path):
    """The project page's MOVE button, over the same two projects."""
    projects = tmp_path / "button-projects"
    for rel, slug in ((DRONE, D_SLUG), (ANIMALS, A_SLUG)):
        d = projects / rel
        d.mkdir(parents=True)
        provision.write_marker(d, slug)
    (projects / DRONE / "B-roll").mkdir()
    (projects / DRONE / "B-roll" / "A001_0512.braw").write_bytes(b"braw")
    (projects / ANIMALS / "Interviewees").mkdir()
    settings = Settings(db_path=str(tmp_path / "button.db"), session_secret="test-secret",
                        report_token="companion-token", admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    app = create_app(settings)
    with TestClient(app) as client:
        client.app.state.collector.stop()
        conn = dbmod.connect(tmp_path / "button.db")
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, D_SLUG, DRONE, f"/data/{D_SLUG}", now)
        dbmod.upsert_project(conn, A_SLUG, ANIMALS, f"/data/{A_SLUG}", now)
        conn.commit()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie("test-secret", "owen"))
        yield client, conn
        conn.close()


def test_the_button_still_records_an_admin_move(button):
    client, conn = button
    r = client.post(f"/api/v1/projects/{D_SLUG}/move", json={
        "path": "B-roll/A001_0512.braw", "to_slug": A_SLUG, "to_path": "Interviewees"})
    assert r.status_code == 200, r.text
    (row,) = moves_in(conn)
    assert row["source"] == "admin" and row["requested_by"] == "owen"
