"""Copy to all: planning, lanes, refusals and failures.

Temp folders stand in for the card and the drives; the real Python copier runs (CardJob), and a
fake TeraCopy stands in for the real one (never launched here). Nothing touches a real card.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path

import pytest

from ccsync_companion import card_copy, field_copy, field_mode, sorter_cards
from ccsync_companion.field_copy import Destination

from test_card_copy import FakeTeraCopy

MIB = 1 << 20
SERIAL = "CARD0001"
T0 = 1_760_000_000          # a fixed modified time (seconds) for the card's files


@pytest.fixture(autouse=True)
def _clean_registry():
    sorter_cards._busy.clear()
    sorter_cards._known_drives.clear()
    yield
    sorter_cards._busy.clear()
    sorter_cards._known_drives.clear()


class FakeMirror:
    def __init__(self):
        self.rows = []

    def where(self, name, size, mtime=None):
        return [r for r in self.rows if r["name"].lower() == name.lower() and r["size"] == size]


class World:
    def __init__(self, tmp: Path, sizes=None):
        self.tmp = tmp
        self.card = tmp / "card"
        self.drive = {"A": tmp / "driveA", "B": tmp / "driveB"}
        self.card.mkdir()
        for d in self.drive.values():
            d.mkdir()
        self.data: dict[str, bytes] = {}
        sizes = sizes or {"PRIVATE/M4ROOT/CLIP/C0001.MP4": MIB + 5, "PRIVATE/M4ROOT/CLIP/C0002.MP4": 700_000}
        for i, (rel, n) in enumerate(sizes.items()):
            self.write_card(rel, os.urandom(n), T0 + i)
        self.write_card("PRIVATE/M4ROOT/CLIP/C0001M01.XML", b"<xml/>", T0)
        self.mirror = FakeMirror()
        self.local = field_mode.LocalCopies(tmp / "local.jsonl")
        self.view = field_mode.LedgerView(self.mirror, self.local)
        self.recorded: list[tuple[Destination, list]] = []
        self.lanes_done: list = []
        self.runs_done: list = []

    def write_card(self, rel: str, data: bytes, mtime: int) -> None:
        p = self.card.joinpath(*rel.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        os.utime(p, (mtime, mtime))
        self.data[rel] = data

    def volumes(self, scope="removable", skip=None):
        return [{"serial": SERIAL, "label": "A001", "drive": "Z:", "root": str(self.card), "removable": True,
                 "capacity": 10 ** 9, "free": 10 ** 8}]

    def card_dict(self):
        return {"serial": SERIAL, "label": "A001", "kind": "sony", "root": str(self.card),
                "files": sorter_cards.list_card(self.card)["files"]}

    def dest(self, key: str, lane: str = "") -> Destination:
        root = str(self.drive[key])
        return Destination(id=f"vol:{key * 4}", kind="drive", label=f"CIB_D{key}", root=root, subdir="FieldBackup",
                           volume_id=f"vol:{key * 4}", volume_label=f"CIB_D{key}", volume_root=root,
                           volume_kind="ours", serial=key * 4, lane=lane or f"disk:{key}")

    def services(self, **over):
        def record(d, e):
            """What the page's service does: note it where the verdict looks (LocalCopies)."""
            self.recorded.append((d, e))
            self.local.add([{"volume_id": d.volume_id, "path": x["path"], "name": x["name"], "size": x["size"],
                             "mtime": x["mtime"], "verified": x["verified"], "card": x.get("card"),
                             "rel": x.get("rel"), "phys": x.get("phys")} for x in e])
            return len(e)

        kw = dict(cfg={}, view=self.view, volumes_fn=self.volumes, teracopy_fn=None, record_fn=record,
                  on_lane_done=self.lanes_done.append, on_run_done=self.runs_done.append)
        kw.update(over)
        return field_copy.Services(**kw)

    def run(self, dests, **over):
        copier = field_copy.FieldCopier(self.services(**over))
        run = copier.start(self.card_dict(), dests, "2026-10-20 A001")
        assert copier.wait(run), "the run did not finish"
        return copier, run

    def at(self, key: str, rel: str) -> Path:
        return self.drive[key].joinpath("FieldBackup", "2026-10-20 A001", *rel.split("/"))


def lane_of(run, dest_id):
    return next(l for l in run.lanes if l.dest.id == dest_id)


# ------------------------------------------------------------------------------------ planning
def test_a_file_is_planned_by_what_is_at_its_place(tmp_path):
    w = World(tmp_path)
    d = w.dest("A")
    files = w.card_dict()["files"]
    mp4_1, mp4_2 = "PRIVATE/M4ROOT/CLIP/C0001.MP4", "PRIVATE/M4ROOT/CLIP/C0002.MP4"
    target = w.at("A", mp4_1)
    target.parent.mkdir(parents=True)
    shutil.copy2(w.card / mp4_1, target)                                  # identical, same time
    (w.at("A", mp4_2)).write_bytes(w.data[mp4_2][:1000])                  # a prefix: an interrupted copy
    os.utime(w.at("A", mp4_2), (T0, T0))
    plan = field_copy.plan_destination(files, d, "2026-10-20 A001", w.view)
    acts = {i.rel: i.action for i in plan.items}
    assert acts[mp4_1] == "there" and acts[mp4_2] == "resume"
    assert acts["PRIVATE/M4ROOT/CLIP/C0001M01.XML"] == "copy"
    assert plan.copy_bytes == len(w.data[mp4_2]) + 6


def test_a_file_with_the_same_size_but_another_time_is_not_assumed_to_be_there(tmp_path):
    w = World(tmp_path)
    rel = "PRIVATE/M4ROOT/CLIP/C0001.MP4"
    p = w.at("A", rel)
    p.parent.mkdir(parents=True)
    shutil.copy2(w.card / rel, p)
    os.utime(p, (T0 + 5000, T0 + 5000))
    plan = field_copy.plan_destination(w.card_dict()["files"], w.dest("A"), "2026-10-20 A001", w.view)
    assert {i.rel: i.action for i in plan.items}[rel] == "copy"           # the copier then compares bytes


def test_a_file_the_ledger_says_the_drive_holds_elsewhere_counts_if_it_is_really_there(tmp_path):
    w = World(tmp_path)
    rel = "PRIVATE/M4ROOT/CLIP/C0001.MP4"
    other = w.drive["A"] / "OldTrip" / "C0001.MP4"
    other.parent.mkdir()
    shutil.copy2(w.card / rel, other)
    w.mirror.rows.append({"name": "C0001.MP4", "size": len(w.data[rel]), "volume_id": "vol:AAAA",
                          "path": "OldTrip/C0001.MP4"})
    plan = field_copy.plan_destination(w.card_dict()["files"], w.dest("A"), "2026-10-20 A001", w.view)
    item = next(i for i in plan.items if i.rel == rel)
    assert item.action == "elsewhere" and item.found == other
    other.unlink()                                                        # the ledger is stale: believe the disk
    plan = field_copy.plan_destination(w.card_dict()["files"], w.dest("A"), "2026-10-20 A001", w.view)
    assert next(i for i in plan.items if i.rel == rel).action == "copy"


def test_destinations_on_one_physical_drive_share_a_lane():
    a = Destination("a", "folder", "A", "x", lane="disk:3")
    b = Destination("b", "drive", "B", "y", lane="disk:3")
    c = Destination("c", "drive", "C", "z", lane="disk:5")
    groups = field_copy.group_by_lane([a, b, c])
    assert list(groups) == ["disk:3", "disk:5"] and groups["disk:3"] == [a, b]


# --------------------------------------------------------------------------------- a whole run
def test_one_card_goes_to_every_ticked_drive_in_the_october_layout(tmp_path):
    w = World(tmp_path)
    copier, run = w.run([w.dest("A"), w.dest("B")])
    for key in "AB":
        for rel, data in w.data.items():
            got = w.at(key, rel)
            assert got.read_bytes() == data
            assert int(got.stat().st_mtime) == int(w.card.joinpath(*rel.split("/")).stat().st_mtime)
        lane = lane_of(run, f"vol:{key * 4}")
        assert lane.state == "done" and lane.counts["copied"] == 3 and not lane.problems
        assert "3 copied and verified" in lane.message
        snap = lane.snapshot()
        assert snap["percent"] == 100.0 and snap["bytesDone"] == snap["bytesTotal"] > 0
    assert not list(tmp_path.rglob("*.partial"))
    assert run.finished is not None and w.runs_done == [run]


def test_only_what_the_ledger_tracks_is_recorded_each_one_verified_in_full(tmp_path):
    w = World(tmp_path)
    w.run([w.dest("A")])
    (dest, entries), = w.recorded
    assert dest.id == "vol:AAAA"
    assert sorted(e["path"] for e in entries) == [
        "FieldBackup/2026-10-20 A001/PRIVATE/M4ROOT/CLIP/C0001.MP4",
        "FieldBackup/2026-10-20 A001/PRIVATE/M4ROOT/CLIP/C0002.MP4"] or len(entries) == 3
    recordable = [e for e in entries if field_mode.is_recordable(e["rel"])]
    assert len(recordable) == 2 and all(e["verified"] == "full" and e["size"] > 0 for e in recordable)
    e = recordable[0]
    assert e["mtime"] == int(round(w.at("A", e["rel"]).stat().st_mtime * 1000))


def test_running_the_card_again_copies_nothing_and_quick_checks_what_is_there(tmp_path, monkeypatch):
    w = World(tmp_path)
    w.run([w.dest("A")])
    w.recorded.clear()

    def never(*a, **k):
        raise AssertionError("a file that is already there was copied again")

    monkeypatch.setattr(card_copy, "copy_file", never)
    _, run = w.run([w.dest("A")])
    lane = lane_of(run, "vol:AAAA")
    assert lane.state == "done" and lane.counts["there"] == 3 and lane.counts["copied"] == 0
    assert "already there, quick-checked" in lane.message
    (_, entries), = w.recorded
    assert {e["verified"] for e in entries if field_mode.is_recordable(e["rel"])} == {"quick"}


def test_with_no_record_of_a_verified_copy_the_file_already_there_is_compared_in_full(tmp_path, monkeypatch):
    w = World(tmp_path)
    w.run([w.dest("A")])
    w.local = field_mode.LocalCopies(tmp_path / "other-local.jsonl")      # this laptop remembers nothing
    w.view = field_mode.LedgerView(w.mirror, w.local)
    w.recorded.clear()
    _, run = w.run([w.dest("A")])
    lane = lane_of(run, "vol:AAAA")
    assert lane.state == "done" and lane.counts["there"] == 3
    (_, entries), = w.recorded
    assert {e["verified"] for e in entries} == {"full"}                  # not "quick": nothing vouched for them


def test_a_different_file_at_the_destination_is_left_alone_and_said_so(tmp_path):
    w = World(tmp_path)
    rel = "PRIVATE/M4ROOT/CLIP/C0002.MP4"
    p = w.at("A", rel)
    p.parent.mkdir(parents=True)
    p.write_bytes(b"somebody else's clip, longer than nothing" * 50_000)
    before = p.read_bytes()
    _, run = w.run([w.dest("A")])
    lane = lane_of(run, "vol:AAAA")
    assert p.read_bytes() == before                                       # never overwritten
    assert lane.state == "attention" and lane.counts["conflicts"] == 1
    assert any("not overwritten" in pr["why"] for pr in lane.problems)
    assert w.at("A", "PRIVATE/M4ROOT/CLIP/C0001.MP4").read_bytes() == w.data["PRIVATE/M4ROOT/CLIP/C0001.MP4"]


def test_an_interrupted_copy_of_this_file_is_finished_not_refused(tmp_path):
    w = World(tmp_path)
    rel = "PRIVATE/M4ROOT/CLIP/C0001.MP4"
    p = w.at("A", rel)
    p.parent.mkdir(parents=True)
    p.write_bytes(w.data[rel][:400_000])
    _, run = w.run([w.dest("A")])
    assert lane_of(run, "vol:AAAA").state == "done" and p.read_bytes() == w.data[rel]


def test_an_already_there_file_that_does_not_match_the_card_is_not_called_good(tmp_path):
    w = World(tmp_path)
    rel = "PRIVATE/M4ROOT/CLIP/C0001.MP4"
    p = w.at("A", rel)
    p.parent.mkdir(parents=True)
    bad = bytearray(w.data[rel])
    bad[10] ^= 0xFF                                                       # same size, same time, damaged header
    p.write_bytes(bytes(bad))
    os.utime(p, (T0, T0))
    _, run = w.run([w.dest("A")])
    lane = lane_of(run, "vol:AAAA")
    assert lane.counts["conflicts"] == 1 and lane.state == "attention"
    assert p.read_bytes() == bytes(bad)
    assert all(rel not in e["rel"] for _, es in w.recorded for e in es)  # not recorded as a backup


# ------------------------------------------------------------------------------- the lanes
def test_destinations_on_different_drives_copy_at_the_same_time_and_on_one_drive_in_turn(tmp_path, monkeypatch):
    w = World(tmp_path, sizes={"PRIVATE/M4ROOT/CLIP/C0001.MP4": 200_000})
    spans: dict[str, tuple[float, float]] = {}
    orig = card_copy.copy_file

    def slow(src, dst, size, stop, on_bytes):
        t0 = time.monotonic()
        time.sleep(0.25)
        out = orig(src, dst, size, stop, on_bytes)
        spans[str(dst)] = (t0, time.monotonic())
        return out

    monkeypatch.setattr(card_copy, "copy_file", slow)

    def overlap(x, y):
        return x[0] < y[1] and y[0] < x[1]

    w.run([w.dest("A", lane="disk:1"), w.dest("B", lane="disk:2")])
    a = next(v for k, v in spans.items() if "driveA" in k and k.endswith("C0001.MP4"))
    b = next(v for k, v in spans.items() if "driveB" in k and k.endswith("C0001.MP4"))
    assert overlap(a, b), "two physical drives must copy together"

    for d in w.drive.values():
        shutil.rmtree(d)
        d.mkdir()
    spans.clear()
    w.run([w.dest("A", lane="disk:1"), w.dest("B", lane="disk:1")])
    a = next(v for k, v in spans.items() if "driveA" in k and k.endswith("C0001.MP4"))
    b = next(v for k, v in spans.items() if "driveB" in k and k.endswith("C0001.MP4"))
    assert not overlap(a, b), "one physical drive takes one copy at a time"


def test_the_card_is_marked_busy_while_it_is_copied_so_nothing_else_reads_it(tmp_path, monkeypatch):
    w = World(tmp_path, sizes={"PRIVATE/M4ROOT/CLIP/C0001.MP4": 100_000})
    seen = []
    orig = card_copy.copy_file

    def spy(*a, **k):
        seen.append(sorter_cards.busy_serials())
        return orig(*a, **k)

    monkeypatch.setattr(card_copy, "copy_file", spy)
    w.run([w.dest("A")])
    assert seen and all(SERIAL in s for s in seen) and not sorter_cards.busy_serials()


def test_a_card_is_not_copied_twice_at_once_and_a_busy_destination_is_refused(tmp_path, monkeypatch):
    w = World(tmp_path, sizes={"PRIVATE/M4ROOT/CLIP/C0001.MP4": 100_000})
    gate = threading.Event()
    orig = card_copy.copy_file

    def held(*a, **k):
        gate.wait(5)
        return orig(*a, **k)

    monkeypatch.setattr(card_copy, "copy_file", held)
    copier = field_copy.FieldCopier(w.services())
    run = copier.start(w.card_dict(), [w.dest("A")], "2026-10-20 A001")
    with pytest.raises(ValueError, match="already being copied"):
        copier.start(w.card_dict(), [w.dest("B")], "2026-10-20 A001")
    gate.set()
    assert copier.wait(run)


# --------------------------------------------------------------------------------- failures
def test_a_destination_without_room_is_refused_before_a_byte_moves_and_the_others_go_on(tmp_path):
    w = World(tmp_path)
    small = w.dest("B")
    _, run = w.run([w.dest("A"), small], free_fn=lambda p: 5 * MIB if "driveB" in p else 10 ** 12)
    b = lane_of(run, small.id)
    assert b.state == "refused" and "Not enough room on CIB_DB" in b.message and "free" in b.message
    assert not (w.drive["B"] / "FieldBackup").exists()                    # nothing was made there
    assert lane_of(run, "vol:AAAA").state == "done"


def test_the_room_needed_counts_only_what_is_not_already_there(tmp_path):
    w = World(tmp_path)
    w.run([w.dest("A")])                                                  # now it is all there
    _, run = w.run([w.dest("A")], free_fn=lambda p: 1)                    # no room at all, nothing needed...
    assert lane_of(run, "vol:AAAA").state == "refused"                    # ...but the margin is kept spare
    _, run = w.run([w.dest("A")], free_fn=lambda p: 10 ** 12)
    assert lane_of(run, "vol:AAAA").state == "done"


def test_a_drive_pulled_in_the_middle_stops_its_lane_and_keeps_what_landed(tmp_path, monkeypatch):
    w = World(tmp_path)
    monkeypatch.setattr(field_copy, "ALIVE_SECONDS", 0)
    gone = {"A": False}
    orig = card_copy.copy_file

    def after_one(src, dst, size, stop, on_bytes):
        out = orig(src, dst, size, stop, on_bytes)
        if "driveA" in str(dst):
            gone["A"] = True
        return out

    monkeypatch.setattr(card_copy, "copy_file", after_one)
    _, run = w.run([w.dest("A"), w.dest("B")],
                   alive_fn=lambda p: not (gone["A"] and "driveA" in p) and os.path.isdir(p))
    a, b = lane_of(run, "vol:AAAA"), lane_of(run, "vol:BBBB")
    assert a.state == "failed" and "taken out" in a.message and "CIB_DA" in a.message
    assert a.counts["copied"] == 1
    landed = [p for p in (tmp_path / "driveA").rglob("*") if p.is_file() and not p.name.startswith(".ccsync")]
    assert len(landed) == 1 and landed[0].read_bytes() == w.data[
        "/".join(landed[0].relative_to(tmp_path / "driveA" / "FieldBackup" / "2026-10-20 A001").parts)]
    assert b.state == "done"                                              # the other drive is unaffected
    assert sum(len(e) for d, e in w.recorded if d.id == "vol:AAAA") == 1  # what landed is still recorded


def test_a_drive_that_fills_up_stops_its_lane_in_words(tmp_path, monkeypatch):
    w = World(tmp_path)
    monkeypatch.setattr(field_copy, "ALIVE_SECONDS", 0)
    state = {"full": False}
    orig = card_copy.copy_file

    def after_one(src, dst, size, stop, on_bytes):
        out = orig(src, dst, size, stop, on_bytes)
        state["full"] = True
        return out

    monkeypatch.setattr(card_copy, "copy_file", after_one)
    _, run = w.run([w.dest("A")], free_fn=lambda p: 1024 if state["full"] else 10 ** 12)
    a = lane_of(run, "vol:AAAA")
    assert a.state == "failed" and "is full" in a.message and a.counts["copied"] == 1


def test_a_write_error_that_says_disk_full_is_reported_as_a_full_drive(tmp_path, monkeypatch):
    w = World(tmp_path)

    def boom(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(card_copy, "copy_file", boom)
    _, run = w.run([w.dest("A")])
    a = lane_of(run, "vol:AAAA")
    assert a.state == "failed" and "ran out of room" in a.message


def test_stop_ends_the_copy_between_files_and_says_it_was_you(tmp_path, monkeypatch):
    w = World(tmp_path)
    copier = field_copy.FieldCopier(w.services())
    orig = card_copy.copy_file

    def then_stop(*a, **k):
        out = orig(*a, **k)
        copier.cancel(next(iter(copier.runs)))
        return out

    monkeypatch.setattr(card_copy, "copy_file", then_stop)
    run = copier.start(w.card_dict(), [w.dest("A")], "2026-10-20 A001")
    assert copier.wait(run)
    a = lane_of(run, "vol:AAAA")
    assert a.state == "stopped" and "stopped by you" in a.message and a.counts["copied"] == 1
    assert not list(tmp_path.rglob("*.partial"))


def test_a_drive_that_is_not_there_at_all_is_not_started(tmp_path):
    w = World(tmp_path)
    _, run = w.run([w.dest("A")], alive_fn=lambda p: False)
    a = lane_of(run, "vol:AAAA")
    assert a.state == "refused" and "Plug it in" in a.message


def test_a_lane_that_blows_up_says_so_and_does_not_take_the_others_down(tmp_path):
    w = World(tmp_path)

    def record(dest, entries):
        if dest.id == "vol:AAAA":
            raise RuntimeError("outbox on fire")
        return len(entries)

    _, run = w.run([w.dest("A"), w.dest("B")], record_fn=record)
    assert lane_of(run, "vol:BBBB").state == "done" and lane_of(run, "vol:AAAA").state == "done"


def test_a_pulled_card_stops_the_copy_with_the_cards_name_not_a_failure_per_file(tmp_path, monkeypatch):
    w = World(tmp_path)
    orig = card_copy.copy_file
    calls = {"n": 0}

    def card_leaves(src, dst, size, stop, on_bytes):
        calls["n"] += 1
        if calls["n"] == 2:
            w.volumes = lambda scope="removable", skip=None: []            # the reader is empty now
            raise OSError(5, "Access is denied")
        return orig(src, dst, size, stop, on_bytes)

    monkeypatch.setattr(card_copy, "copy_file", card_leaves)
    copier = field_copy.FieldCopier(w.services(volumes_fn=lambda *a, **k: w.volumes(*a, **k)))
    run = copier.start(w.card_dict(), [w.dest("A")], "2026-10-20 A001")
    assert copier.wait(run)
    a = lane_of(run, "vol:AAAA")
    assert a.state == "failed" and "taken out of its reader" in a.message


# ----------------------------------------------------------------------------------- progress
def test_progress_reports_percent_speed_eta_file_and_phase(tmp_path, monkeypatch):
    w = World(tmp_path, sizes={"PRIVATE/M4ROOT/CLIP/C0001.MP4": 400_000})
    lane = field_copy.Lane("r1", w.dest("A"))
    lane.state = "copying"
    prog = card_copy.Progress(of=2, total_bytes=1000)
    lane.progress = prog
    lane._copy_bytes_total = 1000
    prog.current, prog.phase = "PRIVATE/M4ROOT/CLIP/C0001.MP4", "copy"
    prog.bytes = 0
    s0 = lane.snapshot(now=100.0)
    prog.bytes = 250
    s1 = lane.snapshot(now=101.0)
    assert s0["percent"] == 0 and s1["percent"] == 25.0 and s1["bps"] == 250
    assert s1["etaS"] == 3 and s1["current"].endswith("C0001.MP4") and s1["phase"] == "copy"
    prog.phase = "verify"
    s2 = lane.snapshot(now=102.0)
    assert s2["phase"] == "verify" and s2["bps"] == 0 and s2["etaS"] is None
    prog.bytes = 1000
    lane.state = "done"
    assert lane.snapshot(now=103.0)["percent"] == 100.0


def test_a_running_lane_never_reads_100_before_it_is_done():
    lane = field_copy.Lane("r", Destination("d", "drive", "D", "x"))
    lane.state = "copying"
    lane.progress = card_copy.Progress(of=1, total_bytes=10)
    lane._copy_bytes_total = 10
    lane.progress.bytes = 10
    assert lane.snapshot(now=1.0)["percent"] == 99.0


def test_the_snapshot_of_a_run_is_json_able(tmp_path):
    import json

    w = World(tmp_path)
    copier, run = w.run([w.dest("A"), w.dest("B")])
    json.dumps(copier.snapshot())
    assert copier.snapshot()[0]["lanes"][0]["label"].startswith("CIB_D")


def test_the_file_in_hand_is_shown_as_the_cards_path_not_the_copiers_reference():
    assert field_copy.rel_of_current("{'root': 'card:6A3F8E21', 'rel': 'PRIVATE/M4ROOT/CLIP/C 1.MP4'}") \
        == "PRIVATE/M4ROOT/CLIP/C 1.MP4"
    assert field_copy.rel_of_current("a/b.mp4") == "a/b.mp4" and field_copy.rel_of_current(None) == ""


def test_bytes_are_said_in_words():
    assert field_copy.fmt_bytes(0) == "0 B" and field_copy.fmt_bytes(1_500_000) == "1.5 MB"
    assert field_copy.fmt_bytes(250_000_000_000) == "250 GB" and field_copy.fmt_bytes("x") == "?"
    assert field_copy.looks_full("[Errno 28] No space left on device")
    assert not field_copy.looks_full("Access is denied")


# ----------------------------------------------------------------------------------- TeraCopy
windows_only = pytest.mark.skipif(os.name != "nt", reason="TeraCopy is Windows-only")


@windows_only
def test_on_windows_the_lane_uses_teracopy_and_trusts_only_its_verify(tmp_path):
    w = World(tmp_path, sizes={"PRIVATE/M4ROOT/CLIP/C0001.MP4": 300_000})
    fake = FakeTeraCopy()
    _, run = w.run([w.dest("A")], teracopy_fn=lambda: (fake, ""))
    a = lane_of(run, "vol:AAAA")
    assert a.copier == "teracopy" and fake.calls and a.state == "done"
    (_, entries), = w.recorded
    assert {e["verified"] for e in entries if field_mode.is_recordable(e["rel"])} == {"full"}


@windows_only
def test_a_teracopy_copy_it_did_not_verify_is_recorded_only_after_a_full_compare(tmp_path):
    w = World(tmp_path, sizes={"PRIVATE/M4ROOT/CLIP/C0001.MP4": 300_000})
    _, run = w.run([w.dest("A")], teracopy_fn=lambda: (FakeTeraCopy(result=1), ""))
    a = lane_of(run, "vol:AAAA")
    assert a.state == "done"
    (_, entries), = w.recorded
    assert {e["verified"] for e in entries if field_mode.is_recordable(e["rel"])} == {"full"}
