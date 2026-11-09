"""The rest of the review round (2026-11-10): units for the rules the verdict stands on, and the
smaller engine cases. Temp folders only."""
from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from ccsync_companion import card_copy, field_copy, field_mode, field_service
from test_field_copy import MIB, T0, World as CopyWorld, lane_of
from test_field_service import SERIAL, World, card_of


# ---------------------------------------------------------------- the physical disk
def test_two_volumes_on_one_physical_disk_count_once():
    rows = [{"volume_id": "vol:A"}, {"volume_id": "vol:B"}]
    kinds = {"vol:A": "ours", "vol:B": "ours"}.get
    same = field_mode.file_verdict(rows, kinds, phys_of=lambda v: "disk:3")
    apart = field_mode.file_verdict(rows, kinds, phys_of=lambda v: {"vol:A": "disk:3", "vol:B": "disk:4"}[v])
    assert (same["safe"], same["counted"]) == (False, 1) and apart["safe"] is True
    assert field_mode.file_verdict([{"volume_id": "vol:A", "phys": "disk:3"}, {"volume_id": "vol:B", "phys": "disk:3"}],
                                   kinds)["safe"] is False                # a row's own key wins


def test_a_copy_made_here_remembers_its_card_its_path_on_it_and_its_disk(tmp_path):
    w = World(tmp_path)
    w.svc = w.build(physical_fn=lambda root: "disk:9" if root == str(w.drives["A"]) else "")
    w.finish(w.svc.start_copy(SERIAL, ["vol:AAAA0001"]))
    row = w.svc.local.matching("C0001.MP4", 300_000)[0]
    assert (row["card"], row["rel"], row["phys"]) == (SERIAL, "PRIVATE/M4ROOT/CLIP/C0001.MP4", "disk:9")


# ----------------------------------------------------- another card's file of the same name
def test_a_copy_must_be_this_cards_file():
    rel = "PRIVATE/M4ROOT/CLIP/C0001.MP4"
    folders = field_mode.folder_variants("2026-11-09 A001", "CARD0001")
    here = {"path": "FieldBackup/2026-11-09 A001/" + rel, "card": "CARD0001"}
    assert field_mode.row_is_this_file(here, rel, "CARD0001", folders)
    assert not field_mode.row_is_this_file(dict(here, card="CARD0002"), rel, "CARD0001", folders)   # another card's
    assert field_mode.row_is_this_file({"path": "Trip/" + rel}, rel, "CARD0001", folders)          # the ledger: by path
    assert not field_mode.row_is_this_file({"path": "Trip/C0001.MP4"}, rel, "CARD0001", folders)
    # a file at the card's top level has no path to match: it must sit in this card's own folder
    assert field_mode.row_is_this_file({"path": "FieldBackup/2026-11-09 A001/Z1.WAV"}, "Z1.WAV", "CARD0001", folders)
    assert not field_mode.row_is_this_file({"path": "FieldBackup/2026-11-09 B/Z1.WAV"}, "Z1.WAV", "CARD0001", folders)
    assert not field_mode.row_is_this_file({"path": "Z1.WAV"}, "Z1.WAV", "CARD0001", folders)


def test_the_second_cards_clip_is_not_covered_by_the_firsts_copy(tmp_path):
    w = World(tmp_path)
    w.finish(w.svc.start_copy(SERIAL, ["vol:AAAA0001", "vol:BBBB0001"]))
    w.svc.set_kind("vol:BBBB0001", "ours")
    assert card_of(w.svc.state(refresh=True))["verdict"]["safeToFormat"]
    # another card whose files carry the same names, sizes and times
    rows = w.svc.local._all()
    for r in rows:
        r["card"] = "CARD0002"                           # as if these copies had come from another card
    w.svc.invalidate()
    assert card_of(w.svc.state(refresh=True))["verdict"]["safeToFormat"] is False


# ------------------------------------------------------------------- the card's folder
def test_the_folder_is_the_octobers_unless_another_card_owns_it(tmp_path):
    assert field_mode.pick_card_folder(tmp_path, "2026-10-20 A001", "S1") == "2026-10-20 A001"
    field_mode.write_card_marker(tmp_path / "2026-10-20 A001", "s1", "A001")
    assert field_mode.pick_card_folder(tmp_path, "2026-10-20 A001", "S1") == "2026-10-20 A001"
    assert field_mode.pick_card_folder(tmp_path, "2026-10-20 A001", "S2") == "2026-10-20 A001 S2"
    field_mode.write_card_marker(tmp_path / "2026-10-20 A001 S2", "S2")
    assert field_mode.pick_card_folder(tmp_path, "2026-10-20 A001", "S2") == "2026-10-20 A001 S2"
    (tmp_path / "2026-10-21 old").mkdir()                    # made by the October tools: no marker
    assert field_mode.pick_card_folder(tmp_path, "2026-10-21 old", "S9") == "2026-10-21 old"


# --------------------------------------------------------- a copy that was deleted
def test_a_copy_on_a_drive_that_is_away_is_still_believed(tmp_path):
    w = World(tmp_path)
    w.finish(w.svc.start_copy(SERIAL, ["vol:AAAA0001", "vol:LLLL0001"]))
    w.svc.set_kind("vol:LLLL0001", "ours")
    assert card_of(w.svc.state(refresh=True))["verdict"]["safeToFormat"]
    w.svc = w.build(volumes_fn=lambda scope="removable", skip=None: [v for v in w.vols(scope, skip)
                                                                       if v["serial"] != "AAAA0001"])
    w.svc.set_kind("vol:AAAA0001", "ours")
    assert card_of(w.svc.state(refresh=True))["verdict"]["safeToFormat"]      # CIB_D1 is in the bag: believed


def test_a_copy_that_changed_on_an_attached_drive_is_not_believed(tmp_path):
    w = World(tmp_path)
    w.finish(w.svc.start_copy(SERIAL, ["vol:AAAA0001", "vol:LLLL0001"]))
    w.svc.set_kind("vol:LLLL0001", "ours")
    for p in (w.drives["A"] / "FieldBackup").rglob("C0001.MP4"):
        p.write_bytes(b"short")
    w.svc.invalidate()
    v = card_of(w.svc.state(refresh=True))["verdict"]
    assert v["safeToFormat"] is False and v["single"] == 1


# ------------------------------------------------------------------- small service bugs
def test_an_empty_local_copies_object_handed_in_is_the_one_used(tmp_path):
    w = World(tmp_path)
    local = field_mode.LocalCopies(tmp_path / "mine.jsonl")
    assert not local and len(local) == 0
    svc = w.build(local=local, store=field_mode.FieldStore(tmp_path / "mine.json"))
    assert svc.local is local and svc.view.local is local


def test_the_copying_flag_is_on_while_any_run_of_the_card_is(tmp_path, monkeypatch):
    w = World(tmp_path)
    w.finish(w.svc.start_copy(SERIAL, [w.add_folder()]))                   # an OLD finished run
    gate = threading.Event()
    real = card_copy.copy_file
    monkeypatch.setattr(card_copy, "copy_file", lambda *a, **k: (gate.wait(10), real(*a, **k))[1])
    for p in (w.drives["A"] / "FieldBackup").rglob("*"):
        pass
    snap = w.svc.start_copy(SERIAL, ["vol:AAAA0001"])
    try:
        assert card_of(w.svc.state())["copying"] is True
    finally:
        gate.set()
        w.finish(snap)
    assert card_of(w.svc.state())["copying"] is False


# ------------------------------------------------------------------------- the page script
def test_the_page_sends_only_ticks_that_are_present_and_not_busy():
    js = (Path(__file__).resolve().parents[1] / "src" / "ccsync_companion" / "assets" / "field" / "field.js").read_text("utf-8")
    assert "x.present && !x.busy" in js and "filter(function (id) { return usable[id]; })" in js
    assert "S.ticks.delete(id)" in js                                   # stale ticks are forgotten


# ------------------------------------------------------------------ the engine's smaller cases
def test_a_drive_and_a_folder_on_it_in_two_runs_are_one_physical_drive(tmp_path, monkeypatch):
    w = CopyWorld(tmp_path, sizes={"PRIVATE/M4ROOT/CLIP/C0001.MP4": 100_000})
    gate = threading.Event()
    real = card_copy.copy_file
    monkeypatch.setattr(card_copy, "copy_file", lambda *a, **k: (gate.wait(10), real(*a, **k))[1])
    copier = field_copy.FieldCopier(w.services())
    run = copier.start(w.card_dict(), [w.dest("A", lane="disk:7")], "2026-10-20 A001")
    folder = field_copy.Destination(id="folder:x", kind="folder", label="x", root=str(w.drive["A"]), lane="disk:7")
    other = dict(w.card_dict(), serial="CARD0002")
    try:
        with pytest.raises(ValueError, match="busy"):
            copier.start(other, [folder], "f")
    finally:
        gate.set()
    assert copier.wait(run)


def test_a_card_pulled_while_teracopy_works_stops_the_lane(tmp_path):
    if os.name != "nt":
        pytest.skip("TeraCopy is Windows-only")
    from test_card_copy import FakeTeraCopy
    w = CopyWorld(tmp_path, sizes={"PRIVATE/M4ROOT/CLIP/C0001.MP4": 100_000})
    state = {"pulled": False}

    class Slow(FakeTeraCopy):
        def copy_group(self, files, dest, switch, tag="", on_tick=None, expect_verify=True, should_stop=None):
            state["pulled"] = True                                  # the card leaves during TeraCopy's job
            import time
            time.sleep(0.05)
            reason = ""
            for _ in range(40):
                reason = should_stop() if should_stop else ""
                if reason:
                    break
                time.sleep(0.1)
            return {"code": 13, "status": {"stopped": reason}, "receipts": [], "stopped": reason,
                    "list_file": "x", "since": 1}

    volumes = lambda *a, **k: [] if state["pulled"] else w.volumes()          # noqa: E731
    import ccsync_companion.field_copy as fc
    old = fc.ALIVE_SECONDS
    fc.ALIVE_SECONDS = 0
    try:
        _, run = w.run([w.dest("A")], teracopy_fn=lambda: (Slow(), ""), volumes_fn=volumes)
    finally:
        fc.ALIVE_SECONDS = old
    lane = lane_of(run, "vol:AAAA")
    assert lane.state == "failed" and "card was taken out" in lane.message


def test_a_drive_whose_letter_changed_hands_mid_run_records_nothing(tmp_path):
    w = CopyWorld(tmp_path)
    _, run = w.run([w.dest("A")], same_drive_fn=lambda d: False)
    lane = lane_of(run, "vol:AAAA")
    assert lane.state == "failed" and "different drive" in lane.message
    assert w.recorded == [] and len(w.local) == 0


def test_the_service_notices_a_letter_that_changed_hands(tmp_path):
    w = World(tmp_path)
    dest = next(d for d in w.svc.destinations() if d.id == "vol:AAAA0001")
    assert w.svc._same_drive(dest) is True
    swapped = [dict(v, serial="ZZZZ9999") if v["serial"] == "AAAA0001" else v for v in w.vols("all")]
    w.svc._volumes = lambda scope="all", skip=None: swapped
    assert w.svc._same_drive(dest) is False


# ---------------------------------------------------------------------- the pool is the pool
def test_a_mapped_letter_is_the_pool_only_if_it_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    local = lambda letter: ""                                                      # noqa: E731
    assert field_service.pool_identity(str(tmp_path), unc_fn=local)[0] is False    # a local disk, no marker
    (tmp_path / field_service.POOL_MARKER).write_text("")
    assert field_service.pool_identity(str(tmp_path), unc_fn=local)[0] is True     # the marker says so
    other = tmp_path / "other"
    other.mkdir()
    nas = lambda letter: r"\\nas\TheCreatorsPool"                                  # noqa: E731
    assert field_service.pool_identity(str(other), unc_fn=nas)[0] is True          # any network drive, if none named
    assert field_service.pool_identity(str(other), r"\\nas\TheCreatorsPool", unc_fn=nas)[0] is True
    ok, why = field_service.pool_identity(str(other), r"\\nas\TheCreatorsPool", unc_fn=lambda l: r"\\other\share")
    assert ok is False and "not the NAS pool" in why


def test_a_pool_letter_that_is_not_the_pool_is_not_offered(tmp_path):
    w = World(tmp_path)
    w.pool.mkdir()
    w.cfg["jobs_pool_root"] = str(w.pool)
    w.svc = w.build(pool_check_fn=lambda root: (False, "That drive is a local disk, not the NAS pool"))
    p = next(d for d in w.svc.state()["destinations"] if d["id"] == "pool")
    assert p["present"] is False and "not the NAS pool" in p["why"]
    with pytest.raises(ValueError, match="not the NAS pool"):
        w.svc.start_copy(SERIAL, ["pool"])
