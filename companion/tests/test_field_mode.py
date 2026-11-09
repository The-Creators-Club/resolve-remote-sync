"""The field backup rules: what is tracked, what counts, the card's verdict, the folder a card
lands in, the quick verify, and the two small files.

The verdict is the October ledger's (razer laptop lib/ledger.js + cloud/ledger/src/index.js
`verdict()`), so each case here is a sentence Alex said about it: two copies that count, or one at
home; client drives and cards never count; a laptop-only result is flagged.
"""
from __future__ import annotations

import json
import os
import struct
from datetime import datetime
from pathlib import Path

import pytest

from ccsync_companion import field_mode as fm

MIB = 1 << 20


# ----------------------------------------------------------------------------------- tracked
@pytest.mark.parametrize("rel,tracked", [
    ("PRIVATE/M4ROOT/CLIP/C0001.MP4", True),
    ("A001_C003.braw", True),
    ("DCIM/100MEDIA/DJI_0001.MOV", True),
    ("260101_001.WAV", True),
    ("PRIVATE/M4ROOT/CLIP/C0001M01.XML", False),             # camera XML is not footage
    ("PRIVATE/M4ROOT/SUB/C0001S03.MP4", False),              # a Sony proxy
    ("Footage/Proxy/A001.mov", False),
    ("Footage/Proxies/A001.mov", False),
    ("clip.tmp.mp4", False),                                 # a copier's temp file
    ("clip.mp4.partial", False),
    ("._A001.mov", False),                                   # a macOS twin
    ("notes.txt", False),
    ("DCIM/THMBNL/x.jpg", False),
])
def test_what_the_ledger_tracks_on_a_card(rel, tracked):
    assert fm.is_tracked(rel) is tracked


def test_a_proxy_video_is_recordable_but_not_what_safe_to_format_waits_for():
    assert fm.is_recordable("Footage/Proxy/A001.mov") and not fm.is_tracked("Footage/Proxy/A001.mov")
    assert not fm.is_recordable("PRIVATE/M4ROOT/CLIP/C0001M01.XML")


# ------------------------------------------------------------------------------------ naming
def test_a_card_lands_in_day_and_label_as_the_october_loose_cards_did():
    assert fm.card_folder_name("A001", "1038701C", "2026-10-20") == "2026-10-20 A001"


@pytest.mark.parametrize("label", ["", "NO NAME", "EOS_DIGITAL", "  untitled "])
def test_a_label_that_says_nothing_is_replaced_by_the_serial(label):
    assert fm.card_folder_name(label, "F614401B", "2026-10-20") == "2026-10-20 F614401B"


def test_a_label_with_characters_windows_refuses_is_cleaned():
    assert fm.card_folder_name('SD:3/"x"', "1", "2026-10-20") == "2026-10-20 SD_3_x_"


def test_the_day_is_the_newest_file_on_the_card_so_a_second_run_finds_the_first():
    t1 = datetime(2026, 10, 19, 12, 0).timestamp() * 1000
    t2 = datetime(2026, 10, 20, 9, 30).timestamp() * 1000
    assert fm.card_day([["a", 1, t1], ["b", 1, t2]]) == "2026-10-20"
    assert fm.card_day([]) == datetime.now().strftime("%Y-%m-%d")


# ------------------------------------------------------------------------------------ kinds
@pytest.mark.parametrize("kwargs,kind", [
    ({"label": "CIB_D1"}, "ours"), ({"label": "cib_d12"}, "ours"),
    ({"label": "WD-3"}, "client"), ({"label": "My Passport"}, "client"),
    ({"label": "SD", "removable": True}, "card"),
    ({"label": "Whatever"}, "unknown"),
    ({"label": "Local", "folder": True}, "laptop"),
    ({"pool": True}, "nas"),
    ({"label": "OS", "system": True}, "laptop"),
])
def test_what_a_drive_is_guessed_to_be(kwargs, kind):
    assert fm.guess_kind(**kwargs) == kind


def test_a_persons_choice_beats_the_ledger_beats_the_guess():
    overrides, info, guesses = {}, {"vol:A": {"label": "CIB_D1", "kind": "ours"}}, {"vol:A": "unknown", "vol:B": "client"}
    r = fm.KindResolver(lambda: overrides, lambda: info, lambda: guesses)
    assert r.kind("vol:A") == "ours" and r.kind("vol:B") == "client"
    overrides["vol:A"] = "client"
    assert r.kind("vol:A") == "client"
    assert r.kind("vol:Z") == "unknown" and r.kind("nas:pool") == "nas"
    assert r.label("vol:A") == "CIB_D1" and r.label("vol:Z", "E:") == "E:"


def test_a_ledger_that_says_unknown_does_not_hide_a_better_guess():
    r = fm.KindResolver(info=lambda: {"vol:A": {"kind": "unknown"}}, guesses=lambda: {"vol:A": "ours"})
    assert r.kind("vol:A") == "ours"


# ---------------------------------------------------------------------------------- verdicts
KINDS = {"vol:OURS1": "ours", "vol:OURS2": "ours", "vol:LAP": "laptop", "vol:LAP2": "laptop",
         "nas:pool": "nas", "vol:CLIENT": "client", "vol:CARD": "card", "vol:UNK": "unknown"}


def kind_of(vid):
    return KINDS.get(vid, "unknown")


def vols(*ids):
    return [{"volume_id": i, "path": "x"} for i in ids]


@pytest.mark.parametrize("held,safe,home,laptop_only", [
    ([], False, False, False),
    (["vol:OURS1"], False, False, False),                     # one copy is never enough
    (["vol:OURS1", "vol:OURS2"], True, False, False),         # two that count
    (["nas:pool"], True, True, False),                        # one at home
    (["vol:OURS1", "vol:CLIENT"], False, False, False),       # a client's drive does not count
    (["vol:OURS1", "vol:CARD"], False, False, False),         # nor does a card
    (["vol:OURS1", "vol:UNK"], False, False, False),          # nor a drive nobody has named
    (["vol:OURS1", "vol:LAP"], True, False, False),           # laptop + ours: safe, not flagged
    (["vol:LAP", "vol:LAP2"], True, False, True),             # laptops alone: safe but flagged
    (["vol:LAP"], False, False, True),                        # one laptop copy: not safe, and flagged
    (["vol:OURS1", "vol:OURS1"], False, False, False),        # one volume twice is one copy
])
def test_a_files_standing_follows_the_october_rules(held, safe, home, laptop_only):
    v = fm.file_verdict(vols(*held), kind_of)
    assert (v["safe"], v["home"], v["laptopOnly"]) == (safe, home, laptop_only)


def card(*names, size=10):
    return [[n, size, 1_000_000.0 + i] for i, n in enumerate(names)]


def lookup(table):
    return lambda name, size, mtime: vols(*table.get(name, []))


def test_a_card_is_safe_to_format_only_when_every_file_is_safe():
    files = card("A.braw", "B.braw", "C.braw")
    table = {"A.braw": ["vol:OURS1", "vol:OURS2"], "B.braw": ["nas:pool"], "C.braw": ["vol:OURS1"]}
    v = fm.card_verdict(files, lookup(table), kind_of)
    assert v["state"] == "unsafe" and not v["safeToFormat"]
    assert (v["tracked"], v["safe"], v["single"], v["none"]) == (3, 2, 1, 0)
    assert "1 of 3" in v["headline"] and v["atRisk"][0]["path"] == "C.braw"
    table["C.braw"] = ["vol:OURS2", "vol:LAP"]
    v = fm.card_verdict(files, lookup(table), kind_of)
    assert v["state"] == "safe" and v["safeToFormat"] and v["flags"] == []


def test_everything_at_home_reads_at_home():
    v = fm.card_verdict(card("A.braw", "B.braw"), lookup({"A.braw": ["nas:pool"], "B.braw": ["nas:pool"]}), kind_of)
    assert v["safeToFormat"] and "at home" in v["headline"]


def test_a_result_that_rests_on_laptop_copies_alone_is_flagged():
    v = fm.card_verdict(card("A.braw"), lookup({"A.braw": ["vol:LAP", "vol:LAP2"]}), kind_of)
    assert v["safeToFormat"] and v["flags"] == ["laptop-only"] and "laptop" in v["headline"]


def test_a_files_with_no_copy_are_counted_apart_from_those_with_one():
    v = fm.card_verdict(card("A.braw", "B.braw"), lookup({"A.braw": ["vol:OURS1"]}), kind_of)
    assert (v["none"], v["single"]) == (1, 1) and "no copy" in v["headline"]


def test_copies_on_drives_that_do_not_count_are_explained():
    v = fm.card_verdict(card("A.braw"), lookup({"A.braw": ["vol:OURS1", "vol:CLIENT"]}), kind_of)
    assert v["state"] == "unsafe" and any("do not count" in n for n in v["notes"])


def test_the_cards_own_volume_is_never_a_copy():
    v = fm.card_verdict(card("A.braw"), lookup({"A.braw": ["vol:OURS1", "vol:CARD"]}), kind_of,
                        exclude_volumes=["vol:CARD"])
    assert v["single"] == 1


def test_only_masters_and_audio_are_waited_for():
    files = card("PRIVATE/M4ROOT/CLIP/C1.MP4", "PRIVATE/M4ROOT/CLIP/C1M01.XML", "PRIVATE/M4ROOT/SUB/C1S03.MP4")
    v = fm.card_verdict(files, lookup({"C1.MP4": ["nas:pool"]}), kind_of)
    assert v["tracked"] == 1 and v["safeToFormat"]


def test_a_card_with_nothing_to_back_up_is_not_called_safe():
    v = fm.card_verdict(card("notes.txt"), lookup({}), kind_of)
    assert v["state"] == "empty" and not v["safeToFormat"]


def test_what_each_destination_already_holds_is_counted():
    files = card("A.braw", "B.braw", "C.braw")
    table = {"A.braw": ["vol:OURS1"], "B.braw": ["vol:OURS1", "vol:OURS2"]}
    v = fm.card_verdict(files, lookup(table), kind_of, dest_volumes={"d1": "vol:OURS1", "d2": "vol:OURS2"})
    assert v["perDest"] == {"d1": {"have": 2, "of": 3}, "d2": {"have": 1, "of": 3}}


# ----------------------------------------------------------------------------- quick verify
def put(path: Path, data: bytes, mtime=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", 8 + len(body)) + kind + body


def mp4(media=5000, moov=b"M" * 300) -> bytes:
    return box(b"ftyp", b"isom0000") + box(b"mdat", os.urandom(media)) + box(b"moov", moov)


def test_a_faithful_copy_passes_the_quick_check(tmp_path):
    data = os.urandom(3 * MIB + 17)
    a, b = put(tmp_path / "a.braw", data), put(tmp_path / "b.braw", data)
    r = fm.quick_compare(a, b)
    assert r["ok"] and r["checked"] == ["size", "head", "tail"]


def test_a_copy_of_the_wrong_size_fails(tmp_path):
    a, b = put(tmp_path / "a.mov", b"x" * 100), put(tmp_path / "b.mov", b"x" * 99)
    r = fm.quick_compare(a, b)
    assert not r["ok"] and "99 bytes" in r["error"]


def test_a_copy_that_differs_in_its_first_or_last_mebibyte_fails(tmp_path):
    data = bytearray(os.urandom(4 * MIB))
    a = put(tmp_path / "a.braw", bytes(data))
    for where, what in ((10, "first"), (4 * MIB - 10, "last")):
        bad = bytearray(data)
        bad[where] ^= 0xFF
        b = put(tmp_path / f"b{what}.braw", bytes(bad))
        r = fm.quick_compare(a, b)
        assert not r["ok"] and what in r["error"]


def test_a_quicktime_file_is_checked_through_its_moov(tmp_path):
    data = mp4()
    a, b = put(tmp_path / "a.mp4", data), put(tmp_path / "b.mp4", data)
    r = fm.quick_compare(a, b)
    assert r["ok"] and r["checked"][-1] == "moov"


def test_damage_in_the_middle_of_the_moov_is_caught_though_head_and_tail_are_fine(tmp_path):
    # Sony and BMCC write the index AFTER the media; a flipped byte in the middle of a 3 MiB moov is
    # outside the first and last MiB of the file, so only the moov check can see it
    data = bytearray(mp4(media=1000, moov=os.urandom(3 * MIB)))
    a = put(tmp_path / "a.mp4", bytes(data))
    data[len(data) - 3 * MIB // 2] ^= 0xFF
    b = put(tmp_path / "b.mp4", bytes(data))
    r = fm.quick_compare(a, b)
    assert not r["ok"] and "moov" in r["error"] and r["checked"] == ["size", "head", "tail"]


def test_a_source_with_no_moov_is_a_warning_and_not_a_failed_copy(tmp_path):
    data = box(b"ftyp", b"isom0000") + box(b"mdat", b"x" * 200)
    a, b = put(tmp_path / "a.mp4", data), put(tmp_path / "b.mp4", data)
    r = fm.quick_compare(a, b)
    assert r["ok"] and "no moov" in r["warning"]


def test_an_unreadable_file_is_reported_not_raised(tmp_path):
    r = fm.quick_compare(tmp_path / "gone.mov", tmp_path / "also-gone.mov")
    assert not r["ok"] and r["unreadable"]


def test_mtime_slack_is_exfats_two_seconds():
    assert fm.same_mtime(1_000_000, 1_001_900) and not fm.same_mtime(1_000_000, 1_004_000)
    assert not fm.same_mtime(None, 5)


# -------------------------------------------------------------------------------- the files
def test_the_store_remembers_destinations_folders_and_kinds(tmp_path):
    s = fm.FieldStore(tmp_path / "state.json")
    assert s.last_dests() == [] and s.folders() == [] and s.kinds() == {}
    s.remember_dests(["vol:A", "pool"])
    s.add_folder("D:\\FieldBackup")
    s.add_folder("d:\\fieldbackup")                            # the same folder, spelled differently
    s.set_kind("vol:A", "ours")
    s2 = fm.FieldStore(tmp_path / "state.json")
    assert s2.last_dests() == ["vol:A", "pool"] and s2.folders() == ["D:\\FieldBackup"]
    assert s2.kinds() == {"vol:A": "ours"}
    s2.set_kind("vol:A", "unknown")
    s2.remove_folder("D:\\FIELDBACKUP")
    assert fm.FieldStore(tmp_path / "state.json").kinds() == {} and s2.folders() == []


def test_a_torn_state_file_reads_as_empty(tmp_path):
    (tmp_path / "state.json").write_text('{"last_dests": ["vol:A"', encoding="utf-8")
    s = fm.FieldStore(tmp_path / "state.json")
    assert s.last_dests() == []
    s.remember_dests(["x"])
    assert s.last_dests() == ["x"]


def local_row(**over):
    row = {"volume_id": "vol:A", "label": "CIB_D1", "kind": "ours", "path": "FieldBackup/d/A.braw",
           "name": "A.braw", "size": 10, "mtime": 1000, "verified": "full"}
    row.update(over)
    return row


def test_local_copies_match_by_name_size_and_a_three_second_window(tmp_path):
    lc = fm.LocalCopies(tmp_path / "c.jsonl")
    assert lc.add([local_row()]) == 1
    assert len(lc.matching("a.BRAW", 10, 1000)) == 1
    assert len(lc.matching("A.braw", 10, 3500)) == 1
    assert lc.matching("A.braw", 10, 9000) == [] and lc.matching("A.braw", 11, 1000) == []
    assert len(lc.matching("A.braw", 10)) == 1                # no mtime on the asker's side


def test_local_copies_survive_a_restart_and_a_torn_line(tmp_path):
    p = tmp_path / "c.jsonl"
    fm.LocalCopies(p).add([local_row()])
    with open(p, "a", encoding="utf-8") as fh:
        fh.write('{"volume_id": "vol:A", "na')                 # power cut mid-write
    assert len(fm.LocalCopies(p)) == 1


def test_an_old_local_copy_expires(tmp_path):
    p = tmp_path / "c.jsonl"
    now = datetime(2026, 11, 9).timestamp()
    fm.LocalCopies(p, clock=lambda: now).add([local_row(at="2026-09-01T00:00:00Z"),
                                              local_row(path="FieldBackup/d/B.braw", name="B.braw",
                                                        at="2026-11-08T00:00:00Z")])
    assert [r["name"] for r in fm.LocalCopies(p, clock=lambda: now)._all()] == ["B.braw"]


def test_a_copy_noted_twice_is_one_row(tmp_path):
    lc = fm.LocalCopies(tmp_path / "c.jsonl")
    lc.add([local_row()])
    lc.add([local_row(verified="quick")])
    assert len(lc) == 1 and lc.matching("A.braw", 10)[0]["verified"] == "quick"


class FakeMirror:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def where(self, name, size, mtime=None):
        return [r for r in self.rows if r["name"].lower() == name.lower() and r["size"] == size]


def test_the_view_counts_a_copy_made_here_before_the_ledger_has_heard(tmp_path):
    lc = fm.LocalCopies(tmp_path / "c.jsonl")
    lc.add([local_row()])
    view = fm.LedgerView(FakeMirror(), lc)
    got = view.copies("A.braw", 10, 1000)
    assert [(c["volume_id"], c["source"]) for c in got] == [("vol:A", "local")]


def test_once_the_mirror_has_it_the_local_row_is_dropped_so_it_is_not_said_twice(tmp_path):
    lc = fm.LocalCopies(tmp_path / "c.jsonl")
    lc.add([local_row(), local_row(volume_id="vol:B", path="FieldBackup/d/A.braw")])
    mirror = FakeMirror([{"name": "A.braw", "size": 10, "volume_id": "vol:A", "path": "FieldBackup/d/A.braw"}])
    view = fm.LedgerView(mirror, lc)
    got = view.copies("A.braw", 10, 1000)
    assert sorted((c["volume_id"], c["source"]) for c in got) == [("vol:A", "mirror"), ("vol:B", "local")]
    assert len(lc) == 1 and fm.LocalCopies(tmp_path / "c.jsonl").matching("A.braw", 10)[0]["volume_id"] == "vol:B"


def test_a_broken_mirror_does_not_break_the_verdict(tmp_path):
    class Broken:
        def where(self, *a, **k):
            raise RuntimeError("sqlite is unhappy")

    lc = fm.LocalCopies(tmp_path / "c.jsonl")
    lc.add([local_row()])
    assert len(fm.LedgerView(Broken(), lc).copies("A.braw", 10, 1000)) == 1
