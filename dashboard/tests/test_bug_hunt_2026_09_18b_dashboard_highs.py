"""The 2026-09-18b fix pass, dashboard group: the three HIGH findings.

All three are about the morning's own fixes (CR-285AM / res-fleet-4 and
CR-285AL / dash-collector-alerts-1), so every test here fails on the tree as
that pass left it:

  * dash-db-1 (= res-fleet-1 = dash-api-1): the OFFER learned to look under a
    computer's former hostname and the ANSWER did not, so a command filed
    under the old name was executed and re-sent every thirty seconds until it
    expired as unanswered.
  * dash-db-2: "same machine_id" with no liveness test hands each twin of a
    CLONED DISK the other's file moves and Resolve undos - and SYS-18a keeps
    two live rows on one id on purpose.
  * dash-collector-alerts-1: a cross-cycle pair on (basename, size, mtime_ns)
    alone turns a COPY whose original is deleted a day later into a
    fleet-wide, unattended file move.
"""

from __future__ import annotations

import pytest

from ccsync_dashboard import api as api_mod
from ccsync_dashboard import collector as collector_mod
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.collector import InventoryWalk
from ccsync_dashboard.settings import Settings

NOW = "2026-09-18T12:00:00+00:00"
AN_HOUR_AGO = "2026-09-18T11:00:00+00:00"
HALF_A_MINUTE_AGO = "2026-09-18T11:59:30+00:00"

DRONE = "2026/Base Drone"
ANIMALS = "2026/FF5/Animals"
CIA = "2026/CIA City"
D_SLUG = "2026-base-drone"
A_SLUG = "2026-ff5-animals"
C_SLUG = "2026-cia-city"


@pytest.fixture
def conn(tmp_path):
    connection = dbmod.connect(tmp_path / "dash.db")
    dbmod.migrate(connection)
    yield connection
    connection.close()


def walk(slug, project_rel, old, new):
    return InventoryWalk(slug=slug, project_rel=project_rel, old=list(old), new=list(new))


def orig(rel, size=100, mtime=111):
    return (rel, "original", size, mtime)


def _a_move_for(conn, editor="ruskin", machine="OLD-PC"):
    move_id = dbmod.record_file_move(
        conn, from_slug=D_SLUG, from_project_rel=DRONE, from_rel="B-roll/A001.braw",
        to_slug=A_SLUG, to_project_rel=ANIMALS, to_rel="Interviewees/A001.braw",
        is_dir=False, proxies_moved=0, requested_by="owen", now=NOW,
        targets=[(editor, machine)], state=dbmod.FILE_MOVE_DONE)
    conn.commit()
    return move_id


def _renamed(conn, old_seen=AN_HOUR_AGO):
    """OLD-PC has been quiet since `old_seen`; NEW-PC is reporting now. One
    computer, one machine_id, two names - the window SYS-18a defers the
    adoption by (and, when the new name has a plan of its own, for ever)."""
    dbmod.upsert_machine(conn, "ruskin", "OLD-PC", machine_id="mid-1", now=old_seen)
    dbmod.upsert_machine(conn, "ruskin", "NEW-PC", machine_id="mid-1", now=NOW)
    conn.commit()


# ---------------------------------------------------------------------------
# dash-db-1 = res-fleet-1 = dash-api-1: the ANSWER half of res-fleet-4
# ---------------------------------------------------------------------------


def test_an_answer_retires_a_move_offered_under_a_former_hostname(conn):
    """The offer, the delivery stamp and the answer have to read one key. The
    answer matched the REPORTING hostname, so it updated zero rows: the same
    move was offered again on every report, the companion re-applied it every
    thirty seconds, and `expire_delivered_file_moves` finally raised a warn
    for a move that had been applied twice."""
    _renamed(conn)
    move_id = _a_move_for(conn)
    offered = dbmod.pending_file_moves(conn, "ruskin", "NEW-PC", NOW, machine_id="mid-1")
    assert [m["target_machine"] for m in offered] == ["OLD-PC"]

    assert dbmod.mark_file_move_applied(
        conn, move_id, "ruskin", "NEW-PC", True, None, NOW, state="done",
        machine_id="mid-1") is True
    conn.commit()
    row = conn.execute("SELECT * FROM file_move_targets WHERE move_id=?",
                       (move_id,)).fetchone()
    assert row["machine"] == "OLD-PC" and row["applied_at"] == NOW
    # ...and it is never offered again, which is the whole point.
    assert dbmod.pending_file_moves(conn, "ruskin", "NEW-PC", NOW,
                                    machine_id="mid-1") == []


def test_an_answer_retires_a_resolve_undo_offered_under_a_former_hostname(conn):
    """The same shape, and worse: an undo is REPLAYED against the editor's
    Resolve, so a dropped answer means the admin's undo is asked for again
    every thirty seconds."""
    _renamed(conn)
    request_id = dbmod.request_resolve_undo(
        conn, "ruskin", "OLD-PC", "j1", "FF5", "owen", NOW)
    conn.commit()
    assert [u["target_machine"] for u in dbmod.pending_resolve_undos(
        conn, "ruskin", "NEW-PC", machine_id="mid-1", now=NOW)] == ["OLD-PC"]

    assert dbmod.mark_resolve_undo_applied(
        conn, request_id, "ruskin", "NEW-PC", True, "", NOW, state="done",
        machine_id="mid-1") is True
    conn.commit()
    assert dbmod.pending_resolve_undos(
        conn, "ruskin", "NEW-PC", machine_id="mid-1", now=NOW) == []


def test_the_answer_de_dupe_reads_the_row_the_answer_is_written_to(conn):
    """comp-app-2's log de-dupe (`_file_move_answer`) read under the reporting
    hostname too, so for exactly the rows res-fleet-4 newly offers it always
    said "no previous answer" - a WARNING per move per report, which is the
    flood it was written to stop."""
    _renamed(conn)
    move_id = _a_move_for(conn)
    dbmod.mark_file_move_applied(
        conn, move_id, "ruskin", "NEW-PC", False, "Resolve has it open", NOW,
        state=dbmod.FILE_MOVE_TARGET_RETRYING, attempts=3, machine_id="mid-1")
    conn.commit()
    assert api_mod._file_move_answer(
        conn, move_id, "ruskin", "NEW-PC", "mid-1", NOW) == (
            dbmod.FILE_MOVE_TARGET_RETRYING, "Resolve has it open")


def test_a_live_twin_is_never_offered_the_other_computers_commands(conn):
    """dash-db-2. A cloned disk is two computers on one `machine_id`, and
    SYS-18a refuses the adoption for as long as both look live - by design,
    indefinitely. "Same identity" with no liveness test therefore hands each
    twin the other's file moves and the other's Resolve undos: an editor's
    Resolve mutated by a command addressed to a different computer. A former
    name is by definition quiet; a twin is not."""
    dbmod.upsert_machine(conn, "ruskin", "TWIN-A", machine_id="mid-1",
                         now=HALF_A_MINUTE_AGO)
    dbmod.upsert_machine(conn, "ruskin", "TWIN-B", machine_id="mid-1", now=NOW)
    move_id = _a_move_for(conn, machine="TWIN-A")
    dbmod.request_resolve_undo(conn, "ruskin", "TWIN-A", "j1", "FF5", "owen", NOW)
    conn.commit()

    assert dbmod.command_machine_names(
        conn, "ruskin", "TWIN-B", "mid-1", now=NOW) == ["TWIN-B"]
    assert dbmod.pending_file_moves(
        conn, "ruskin", "TWIN-B", NOW, machine_id="mid-1") == []
    assert dbmod.pending_resolve_undos(
        conn, "ruskin", "TWIN-B", machine_id="mid-1", now=NOW) == []
    # ...and an answer from the twin cannot retire the other computer's row
    # either: the command stays outstanding for the machine it names.
    assert dbmod.mark_file_move_applied(
        conn, move_id, "ruskin", "TWIN-B", True, None, NOW, state="done",
        machine_id="mid-1") is False
    # The computer it WAS addressed to still gets it.
    assert [m["id"] for m in dbmod.pending_file_moves(
        conn, "ruskin", "TWIN-A", NOW, machine_id="mid-1")] == [move_id]


# ---------------------------------------------------------------------------
# dash-collector-alerts-1: a cross-cycle pair has to be corroborated
# ---------------------------------------------------------------------------


def _project(conn, pid, slug, rel):
    conn.execute(
        "INSERT INTO projects (id, slug, label, path, active, first_seen, last_seen)"
        " VALUES (?,?,?,?,1,?,?)",
        (pid, slug, slug, f"/data/Projects/{rel}", NOW, NOW))


def _inventory(conn, pid, rel_path, size=100, mtime=111):
    conn.execute(
        "INSERT INTO nas_media (project_id, rel_path, kind, ext, size, mtime_ns,"
        " refreshed_at) VALUES (?,?,?,?,?,?,?)",
        (pid, rel_path, "original", ".mov", size, mtime, NOW))


def test_a_copy_whose_original_is_deleted_later_is_not_a_move(conn):
    """The act that fakes a cross-cycle move. An editor copies a clip into a
    second project (size and mtime survive the copy) and the original is
    deleted a day later; the two halves pair on (basename, size, mtime_ns)
    alone and the server tells every machine holding the original to move its
    own copy and relink Resolve, unattended and unconfirmed.

    What tells the two acts apart exists only while both copies are on the
    NAS, which is why the corroboration is asked at the moment each half is
    SEEN and not when they are paired."""
    _project(conn, 1, D_SLUG, DRONE)
    _project(conn, 2, A_SLUG, ANIMALS)
    _inventory(conn, 1, "B-roll/a.mov")          # the original, still there
    _inventory(conn, 2, "Footage/a.mov")         # the copy, just walked
    conn.commit()
    collector = collector_mod.Collector(Settings(db_path=":memory:"))

    # Pass one: project B is walked and the copy appears.
    assert collector._record_detected_moves(conn, [walk(
        A_SLUG, ANIMALS, old=[], new=[orig("Footage/a.mov")])], NOW) == 0
    assert dbmod.pending_move_halves(conn, NOW) == [], \
        "an appearance whose file is also elsewhere is a copy, not half a move"

    # Pass two, a day later: the original is deleted on the NAS.
    conn.execute("DELETE FROM nas_media WHERE project_id=1")
    conn.commit()
    assert collector._record_detected_moves(conn, [walk(
        D_SLUG, DRONE, old=[orig("B-roll/a.mov")], new=[])], NOW) == 0
    assert conn.execute("SELECT COUNT(*) FROM file_moves").fetchone()[0] == 0


def test_a_real_move_between_two_projects_is_still_paired_across_cycles(conn):
    """The guard on the fix above: CR-285AL's own case, with a real inventory
    underneath it. The file is in ONE place at every moment, which is what
    makes it a move."""
    _project(conn, 1, D_SLUG, DRONE)
    _project(conn, 2, A_SLUG, ANIMALS)
    conn.commit()
    collector = collector_mod.Collector(Settings(db_path=":memory:"))

    # Pass one: the source project is walked; its row has already gone.
    assert collector._record_detected_moves(conn, [walk(
        D_SLUG, DRONE, old=[orig("B-roll/a.mov")], new=[])], NOW) == 0
    assert [r["half"] for r in dbmod.pending_move_halves(conn, NOW)] == [
        dbmod.HALF_VANISHED]

    # Pass two: the destination is walked, so its own row is in the inventory.
    _inventory(conn, 2, "Footage/a.mov")
    conn.commit()
    assert collector._record_detected_moves(conn, [walk(
        A_SLUG, ANIMALS, old=[], new=[orig("Footage/a.mov")])], NOW) == 1
    row = conn.execute("SELECT * FROM file_moves").fetchone()
    assert (row["from_slug"], row["to_slug"]) == (D_SLUG, A_SLUG)
    assert dbmod.pending_move_halves(conn, NOW) == []


def test_a_third_copy_in_the_tree_refuses_the_pair(conn):
    """Corroboration at pairing time as well: a file that is in three places
    was never moved out of one of them. Asked of `pair_across_cycles`
    directly, because this is the seam the collector hands its database to -
    the two halves themselves look exactly like a move."""
    _project(conn, 1, D_SLUG, DRONE)
    _project(conn, 2, A_SLUG, ANIMALS)
    _project(conn, 3, C_SLUG, CIA)
    _inventory(conn, 2, "Footage/a.mov")
    _inventory(conn, 3, "Archive/a.mov")
    conn.commit()
    source = collector_mod._Half(
        dbmod.HALF_VANISHED, "a.mov", 100, 111, D_SLUG, DRONE,
        "B-roll/a.mov", "B-roll/a.mov", NOW)
    destination = collector_mod._Half(
        dbmod.HALF_APPEARED, "a.mov", 100, 111, A_SLUG, ANIMALS,
        "Footage/a.mov", "Footage/a.mov")

    paired, _plan = collector_mod.pair_across_cycles([source], [destination])
    assert len(paired) == 1, "the two halves are a move by the pairing rules alone"
    moves, plan = collector_mod.pair_across_cycles(
        [source], [destination],
        corroborate=lambda s, d: collector_mod._one_copy_in_the_tree(conn, s, d))
    assert moves == []
    # Both halves are consumed: evidence the tree contradicts does not get
    # better by being kept for another two days.
    assert plan.persist == [] and plan.delete == [source]


def test_a_half_whose_corroboration_cannot_be_read_is_dropped(conn):
    """"Cannot tell" is not corroboration. A read that fails records no move,
    which is the behaviour this product had before the feature existed."""
    _project(conn, 1, D_SLUG, DRONE)
    conn.commit()
    collector = collector_mod.Collector(Settings(db_path=":memory:"))
    conn.execute("DROP TABLE nas_media")
    conn.commit()
    assert collector._record_detected_moves(conn, [walk(
        D_SLUG, DRONE, old=[orig("B-roll/a.mov")], new=[])], NOW) == 0
    assert dbmod.pending_move_halves(conn, NOW) == []
