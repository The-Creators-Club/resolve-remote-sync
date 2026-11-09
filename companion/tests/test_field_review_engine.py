"""Adversarial checks on the copy engine and recording. A FAIL is a confirmed bug. Temp folders and a
fake TeraCopy only (the companion's conftest blocks the real one)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

import test_field_copy as tfc
from ccsync_companion import card_copy, field_copy, field_mode, sorter_cards
from test_card_copy import FakeTeraCopy
from test_field_copy import MIB, SERIAL, T0, World, lane_of

pytestmark = pytest.mark.skipif(os.name != "nt", reason="TeraCopy path is Windows-only")


def _flip_middle(p: Path) -> None:
    with open(p, "r+b") as fh:
        n = os.fstat(fh.fileno()).st_size
        fh.seek(n // 2)
        b = fh.read(1)
        fh.seek(n // 2)
        fh.write(bytes([b[0] ^ 0xFF]))


class CorruptingTeraCopy(FakeTeraCopy):
    """Copies, then a bit in the MIDDLE of each copy is wrong (a bad cable, a flaky reader). The
    copy keeps the card's size and mtime, as TeraCopy leaves a file whose verify failed."""

    def copy_group(self, files, dest, switch, tag="", on_tick=None, expect_verify=True, should_stop=None):
        out = super().copy_group(files, dest, switch, tag, on_tick, expect_verify, should_stop)
        for f in files:
            t = Path(dest) / Path(f).name
            st = os.stat(f)
            _flip_middle(t)
            os.utime(t, ns=(st.st_atime_ns, st.st_mtime_ns))
        return out


SIZES = {"PRIVATE/M4ROOT/CLIP/C0001.MP4": 5 * MIB, "PRIVATE/M4ROOT/CLIP/C0002.MP4": 4 * MIB}


def _recorded(w):
    return [(d.id, e["name"], e["verified"]) for d, es in w.recorded for e in es if field_mode.is_tracked(e["rel"])]


# E1. TeraCopy finished its verify and did NOT pass the file (result 1 = "copied, not verified"):
#     the lane rescues it with the quick compare (first/last MiB) and records it. A middle-of-file
#     difference passes the quick compare.
def test_a_copy_teracopy_did_not_verify_and_that_differs_mid_file_is_not_recorded(tmp_path):
    w = World(tmp_path, sizes=SIZES)
    _, run = w.run([w.dest("A")], teracopy_fn=lambda: (CorruptingTeraCopy(result=1), ""))
    a = lane_of(run, "vol:AAAA")
    assert a.counts["unverified"] == 3 and a.state == "attention"   # two clips and the XML
    assert not _recorded(w), "a copy that differs from the card was recorded as a good copy"
    for rel in SIZES:                                       # the bad copy is set aside, not left in place
        assert not w.at("A", rel).exists()
        assert w.at("A", rel).with_name(w.at("A", rel).name + ".failed").read_bytes() != w.data[rel]


# E2. TeraCopy says verify FAILED (any non-1 result). The file stays at the destination (same size
#     and mtime). Running the card again -- "the way to check it" -- plans it as `there`, quick-checks
#     it and records it.
def test_running_the_card_again_does_not_launder_a_copy_that_failed_verify(tmp_path):
    w = World(tmp_path, sizes=SIZES)
    _, run = w.run([w.dest("A")], teracopy_fn=lambda: (CorruptingTeraCopy(result=4), ""))
    a = lane_of(run, "vol:AAAA")
    assert a.counts["failed"] == 3 and not _recorded(w)
    for rel in SIZES:
        assert w.at("A", rel).with_name(w.at("A", rel).name + ".failed").exists()
    # run it again: the files are copied afresh and verified; nothing the bad copy left is believed
    _, run2 = w.run([w.dest("A")], teracopy_fn=lambda: (FakeTeraCopy(), ""))
    assert lane_of(run2, "vol:AAAA").state == "done"
    for rel in SIZES:
        assert w.at("A", rel).read_bytes() == w.data[rel]
    assert {lvl for _, _, lvl in _recorded(w)} == {"full"} and len(_recorded(w)) == 2


def test_a_bad_copy_that_could_not_be_renamed_is_still_not_believed_on_a_quick_check(tmp_path, monkeypatch):
    """Even if the set-aside fails, nothing vouches for the file, so the next run compares it in full."""
    w = World(tmp_path, sizes=SIZES)
    monkeypatch.setattr(field_copy.FieldCopier, "_set_aside", staticmethod(lambda path, item: None))
    w.run([w.dest("A")], teracopy_fn=lambda: (CorruptingTeraCopy(result=4), ""))
    assert not _recorded(w)
    _, run2 = w.run([w.dest("A")], teracopy_fn=lambda: (FakeTeraCopy(), ""))
    a2 = lane_of(run2, "vol:AAAA")
    assert a2.counts["there"] == 0 and a2.counts["conflicts"] >= 1      # compared in full, found different
    assert not _recorded(w)


# E3. Two cards with the same label shot the same day share one folder; the second card's clips
#     (same camera numbering) can then never be copied to that drive.
def test_two_cards_with_one_label_on_one_day_do_not_share_a_folder(tmp_path):
    w = World(tmp_path, sizes={"DCIM/100GOPRO/GX010001.MP4": 300_000})
    _, run = w.run([w.dest("A")])
    l1 = lane_of(run, "vol:AAAA")
    assert l1.state == "done" and l1.folder == "2026-10-20 A001"
    # the second GoPro card: same label, same day, its own GX010001.MP4
    shutil.rmtree(w.card)
    w.card.mkdir()
    other = os.urandom(310_000)
    w.write_card("DCIM/100GOPRO/GX010001.MP4", other, T0 + 50)
    card2 = w.card_dict()
    card2["serial"] = "CARD0002"
    copier = field_copy.FieldCopier(w.services(volumes_fn=lambda *a, **k: [
        {"serial": "CARD0002", "label": "GOPRO", "drive": "Z:", "root": str(w.card), "removable": True}]))
    run2 = copier.start(card2, [w.dest("A")], "2026-10-20 A001")      # the same folder name as card 1's
    assert copier.wait(run2)
    l2 = lane_of(run2, "vol:AAAA")
    assert l2.state == "done" and l2.folder == "2026-10-20 A001 CARD0002"
    first = w.drive["A"] / "FieldBackup" / "2026-10-20 A001" / "DCIM" / "100GOPRO" / "GX010001.MP4"
    second = w.drive["A"] / "FieldBackup" / "2026-10-20 A001 CARD0002" / "DCIM" / "100GOPRO" / "GX010001.MP4"
    assert first.read_bytes() != other and second.read_bytes() == other   # neither card's clip replaced the other
    # and card 1 again goes to ITS folder, not the suffixed one
    assert field_mode.pick_card_folder(w.drive["A"] / "FieldBackup", "2026-10-20 A001", SERIAL) == "2026-10-20 A001"


# E4. The page's card list says a card is not copying while a newer run of it is.
def test_the_card_copying_flag_follows_the_newest_run(tmp_path, monkeypatch):
    import threading
    import test_field_service as tfs
    w = tfs.World(tmp_path)
    gate = threading.Event()
    real = card_copy.copy_file

    def slow(*a, **k):
        gate.wait(10)
        return real(*a, **k)

    fid = w.add_folder()
    snap1 = w.svc.start_copy(tfs.SERIAL, [fid])
    gate.set()
    w.finish(snap1)
    monkeypatch.setattr(card_copy, "copy_file", slow)
    gate.clear()
    for p in (w.drives["L"] / "FieldBackup").rglob("*.MP4"):
        p.unlink()
    import time
    time.sleep(1.1)
    snap2 = w.svc.start_copy(tfs.SERIAL, ["vol:AAAA0001"])
    st = w.svc.state()
    c = tfs.card_of(st)
    print("runs", [(r["id"], r["running"]) for r in st["runs"]], "copying flag:", c["copying"])
    gate.set()
    w.finish(snap2)
    assert c["copying"] is True, "a card that is being copied shows as not copying"
