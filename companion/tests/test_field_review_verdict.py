"""Adversarial checks on the field page's "safe to format" verdict. Each test asserts the CORRECT
behaviour, so a FAIL is a confirmed bug. Temp folders only."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

import test_field_service as tfs
from ccsync_companion import field_mode, sorter_cards
from test_field_service import SERIAL, T0, World, card_of


def _run(w, ids):
    snap = w.svc.start_copy(SERIAL, ids)
    run = w.finish(snap)
    for l in run.lanes:
        print("LANE", l.dest.id, l.state, l.message, l.problems)
    w.svc.invalidate()
    return run


# 1. Two partitions of ONE physical disk count as two copies.
def test_two_partitions_of_one_physical_disk_are_not_two_copies(tmp_path):
    w = World(tmp_path)
    part2 = tmp_path / "laptop-e"
    part2.mkdir()
    w.extra.append({"serial": "EEEE0001", "label": "Data2", "drive": "E:", "root": str(part2),
                    "removable": False, "capacity": 10 ** 12, "free": 10 ** 11, "fs": "NTFS",
                    "drive_type": "fixed", "system": False})
    same_disk = {str(w.drives["L"]): "disk:0", str(part2): "disk:0"}
    w.svc = w.build(physical_fn=lambda root: same_disk.get(str(root), ""))
    w.svc.add_folder(str(w.drives["L"] / "FieldBackup"))
    w.svc.add_folder(str(part2 / "FieldBackup"))
    st = w.svc.state(refresh=True)
    folders = [d for d in st["destinations"] if d["type"] == "folder"]
    assert len({d["lane"] for d in folders}) == 1, "the service itself knows they are one disk"
    _run(w, [d["id"] for d in folders])
    v = card_of(w.svc.state(refresh=True))["verdict"]
    print("VERDICT", v["state"], v["headline"])
    assert v["safeToFormat"] is False, "both copies are on ONE physical disk (the laptop's), yet 'safe to format'"


# 2. A folder on a removable volume (USB stick / another camera card) is turned into "laptop" and counts.
def test_a_folder_on_a_usb_stick_does_not_count_as_the_laptop(tmp_path):
    w = World(tmp_path)
    stick = tmp_path / "stick"
    stick.mkdir()
    w.extra.append({"serial": "57100001", "label": "KINGSTON", "drive": "G:", "root": str(stick),
                    "removable": True, "capacity": 64 * 10 ** 9, "free": 60 * 10 ** 9, "fs": "exFAT",
                    "drive_type": "removable", "system": False})
    w.svc = w.build()
    with pytest.raises(ValueError, match="card or a USB stick"):
        w.svc.add_folder(str(stick / "Backup"))
    # ...and one that arrives through the config file is not promoted to "laptop" either
    w.cfg["field_dest_folders"] = [str(stick / "Backup")]
    st = w.svc.state(refresh=True)
    f = next(d for d in st["destinations"] if d["type"] == "folder")
    assert f["kind"] != "laptop" and not f["counts"]
    _run(w, ["vol:AAAA0001", f["id"]])          # CIB_D1 + a folder on the USB stick
    v = card_of(w.svc.state(refresh=True))["verdict"]
    assert v["safeToFormat"] is False, "one real drive + a USB stick = safe"


def test_a_folder_on_another_camera_card_does_not_make_it_a_laptop_drive(tmp_path):
    w = World(tmp_path)
    other = tmp_path / "card2"
    (other / "PRIVATE" / "M4ROOT" / "CLIP").mkdir(parents=True)     # a second Sony card
    w.extra.append({"serial": "CARD0002", "label": "B001", "drive": "H:", "root": str(other),
                    "removable": True, "capacity": 64 * 10 ** 9, "free": 60 * 10 ** 9, "fs": "exFAT",
                    "drive_type": "removable", "system": False})
    w.svc = w.build()
    st = w.svc.state(refresh=True)
    assert {c["serial"] for c in st["cards"]} == {SERIAL, "CARD0002"}
    with pytest.raises(ValueError, match="card or a USB stick"):
        w.svc.add_folder(str(other / "backup"))
    w.cfg["field_dest_folders"] = [str(other / "backup")]
    st = w.svc.state(refresh=True)
    f = next(d for d in st["destinations"] if d["type"] == "folder")
    assert not f["counts"]
    _run(w, ["vol:AAAA0001", f["id"]])
    v = card_of(w.svc.state(refresh=True))["verdict"]
    assert v["safeToFormat"] is False, "a copy on another camera card made card 1 'safe to format'"


# 3. A copy deleted from a drive that is plugged in right now still counts.
def test_a_copy_deleted_from_an_attached_drive_does_not_keep_the_card_safe(tmp_path):
    w = World(tmp_path)
    fid = w.add_folder()
    _run(w, ["vol:AAAA0001", fid])
    v = card_of(w.svc.state(refresh=True))["verdict"]
    assert v["safeToFormat"], v["headline"]
    # make room on CIB_D1 in the field: its FieldBackup folder goes
    shutil.rmtree(w.drives["A"] / "FieldBackup")
    w.svc.invalidate()
    v = card_of(w.svc.state(refresh=True))["verdict"]
    print("VERDICT after deleting the CIB_D1 copy:", v["state"], v["headline"])
    assert v["safeToFormat"] is False, "the drive is attached and the copy is gone, yet 'safe to format'"


# 4. Untracked camera originals (stills, 360 masters, HEIF, other raws) never hold the verdict back.
def test_untracked_camera_originals_hold_the_verdict(tmp_path):
    w = World(tmp_path)
    w.svc.set_kind("vol:LLLL0001", "ours")
    _run(w, ["vol:AAAA0001", "vol:LLLL0001"])               # the video is safely on two drives...
    assert card_of(w.svc.state(refresh=True))["verdict"]["safeToFormat"]
    d = w.card / "DCIM" / "100MSDCF"                         # ...then the photographer's stills arrive
    d.mkdir(parents=True)
    for n in ("DSC00001.JPG", "DSC00002.HIF", "DSC00003.JPG"):
        (d / n).write_bytes(os.urandom(5000))
    w.svc._cards.clear()
    v = card_of(w.svc.state(refresh=True))["verdict"]
    assert v["safeToFormat"] is False, "photos with no copy anywhere, yet 'safe to format'"
    assert v["none"] == 3


def test_a_stills_only_card_is_not_called_nothing_to_back_up(tmp_path):
    w = World(tmp_path)
    shutil.rmtree(w.card / "PRIVATE")
    d = w.card / "DCIM" / "100MSDCF"
    d.mkdir(parents=True)
    for i in range(3):
        (d / f"DSC0000{i}.JPG").write_bytes(os.urandom(5000))
    (d / "DSC00009.XML").write_bytes(b"<x/>")          # a sidecar: not an original
    (d / "DSC00009.MP4").write_bytes(os.urandom(5000))   # so classify() calls it a card
    w.svc = w.build()
    c = card_of(w.svc.state(refresh=True))
    assert c["verdict"]["state"] == "unsafe" and c["verdict"]["tracked"] == 4, c["verdict"]["headline"]


def test_judging_covers_every_original_and_no_sidecar():
    for name in ("DSC1.JPG", "DSC1.HIF", "A.HEIC", "GS01.360", "DSCF1.RAF", "P1.RW2", "I.CR2", "c.mkv", "a.mp4",
                 "a.wav", "x.braw", "x.insv"):
        assert field_mode.is_judged("DCIM/100/" + name), name
    for name in ("C1M01.XML", "A.THM", "GH01.LRV", "DJI_1.LRF", "x.txt", "._DSC1.JPG", "x.tmp.mp4",
                 "x.mp4.partial", "x.mp4.failed", "Thumbs.db"):
        assert not field_mode.is_judged("DCIM/100/" + name), name
    assert not field_mode.is_judged("PRIVATE/M4ROOT/SUB/C1S03.MP4")
    assert not field_mode.is_judged("PRIVATE/M4ROOT/THMBNL/C1T01.JPG")


# 5. Two files with the same name+size+mtime from two recorders (CBR audio, linked start/stop).
def test_another_recorders_identical_named_take_does_not_make_this_card_safe(tmp_path):
    w = World(tmp_path)
    # recorder B's card holds ZOOM0001.WAV; recorder A's ZOOM0001.WAV (same length, same format, same
    # start/stop) is already on two of our drives
    shutil.rmtree(w.card / "PRIVATE")
    (w.card / "PRIVATE" / "M4ROOT" / "CLIP").mkdir(parents=True)   # keep it a card
    wav = w.card / "ZOOM0001.WAV"
    wav.write_bytes(b"RIFF" + os.urandom(48_000 * 6 - 4))
    os.utime(wav, (T0, T0))
    w.svc.local.add([{"volume_id": vid, "path": "2026-11-09 A/ZOOM0001.WAV", "name": "ZOOM0001.WAV",
                      "size": 48_000 * 6, "mtime": T0 * 1000 + 1500, "verified": "full"}
                     for vid in ("vol:AAAA0001", "vol:CCCC0001")])
    w.svc.store.set_kind("vol:CCCC0001", "ours")
    v = card_of(w.svc.state(refresh=True))["verdict"]
    print("VERDICT", v["state"], v["headline"])
    assert v["safeToFormat"] is False
