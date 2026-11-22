"""Hollow copies: the BRAW index parser, the sparse writer, the marker, the ledger, the predicate.

docs/GRADING_FRAMES.md phase 1 (2026-11-22). Every fixture is a synthetic QuickTime file built in
the test (hollow_fixtures.py); no camera footage, no P:\\, no real ~/.ccsync. The writer's tests
skip LOUDLY, naming the filesystem, where the temp dir cannot hold sparse files.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import unicodedata
from pathlib import Path

import pytest

from ccsync_companion import config as config_mod
from ccsync_companion import hollow

import hollow_fixtures as hf

EM_DASH = "\u2014"


@pytest.fixture
def led(tmp_path):
    """A ledger of this test's own (the process ledger is a singleton)."""
    return hollow.configure(tmp_path / "state" / hollow.STATE_FILENAME)


@pytest.fixture
def sparse_tmp(tmp_path):
    hf.need_sparse(tmp_path)
    return tmp_path


def _refusal(fn, *args, **kwargs) -> str:
    with pytest.raises((hollow.LayoutRefused, hollow.HollowRefused)) as caught:
        fn(*args, **kwargs)
    text = str(caught.value)
    assert EM_DASH not in text, "an editor reads this sentence: no em dashes"
    return text


def _parse(data: bytes) -> hollow.BrawIndex:
    head = data[:hollow.HEAD_BYTES]
    off, length, _ = hollow.locate_index(head, len(data))
    return hollow.parse_index(head, data[off:off + length], len(data))


# =============================================================================================
# The parser
# =============================================================================================

def test_the_parser_finds_every_frame_the_builder_put_there():
    data, frames = hf.make_braw()
    idx = _parse(data)
    assert idx.frames == tuple(frames)
    assert idx.head_length == 4100, "the first frame is at byte 4,100 on every clip swept"
    assert idx.codec == "brlt"
    assert idx.moov_offset + idx.moov_length == len(data)
    for off, length in idx.frames:
        assert data[off:off + 8] == hollow.FRAME_MAGIC


@pytest.mark.parametrize("kwargs", [{"large_mdat": False}, {"co64": False}, {"codec": b"brxq"},
                                    {"audio_every": 0}, {"terminator": True}])
def test_the_layouts_seen_in_the_sweep_all_parse(kwargs):
    """32-bit and 64-bit mdat headers, 32-bit chunk offsets, the other codec variants, a clip
    with no sound, and a sample table ending in QuickTime's 32-bit zero terminator."""
    data, frames = hf.make_braw(**kwargs)
    assert _parse(data).frames == tuple(frames)


@pytest.mark.parametrize("kwargs,words", [
    ({"moov_first": True}, "start of the file"),
    ({"trailing": hf.box(b"free", b"x" * 20)}, "not the last"),
    ({"per_chunk": 2}, "more than one frame per chunk"),
    ({"stss": True}, "sync-sample table"),
    ({"ctts": True}, "out of display order"),
    ({"offsets_table": False}, "neither 64-bit nor 32-bit"),
    ({"codec": b"avc1"}, "not Blackmagic RAW"),
    ({"first_frame_at": hollow.HEAD_BYTES + 100}, "past the 64 KB head"),
    ({"two_video": True}, "more than one picture track"),
])
def test_every_layout_the_doc_says_to_refuse_is_refused_with_a_sentence(kwargs, words):
    data, _ = hf.make_braw(**kwargs)
    text = _refusal(_parse, data)
    assert words in text


def test_an_interrupted_recording_with_no_index_is_refused():
    data, _ = hf.make_braw()
    idx = _parse(data)
    cut = data[:idx.moov_offset]
    assert "no index" in _refusal(hollow.locate_index, cut[:hollow.HEAD_BYTES], len(cut))


def test_an_index_read_that_is_short_is_refused():
    data, _ = hf.make_braw()
    head = data[:hollow.HEAD_BYTES]
    off, length, _ = hollow.locate_index(head, len(data))
    assert "bytes where the clip says" in _refusal(hollow.parse_index, head, data[off:off + length - 1], len(data))


def test_a_fetched_frame_must_start_with_the_braw_magic_and_be_its_length():
    good = hf.frame_bytes(3, 1024)
    hollow.check_frame(good, 3, 1024)
    assert "does not start" in _refusal(hollow.check_frame, b"\0" * 1024, 3, 1024)
    assert "1000 bytes long" in _refusal(hollow.check_frame, good[:1000], 3, 1024)


def test_the_parser_shares_field_modes_box_walker(monkeypatch):
    """One ISO-BMFF walker in the companion: the quick verify's (field_mode.walk_boxes)."""
    from ccsync_companion import field_mode

    calls = []
    real = field_mode.walk_boxes
    monkeypatch.setattr(field_mode, "walk_boxes", lambda fh, size: calls.append(size) or real(fh, size))
    _parse(hf.make_braw()[0])
    assert calls


# =============================================================================================
# The marker
# =============================================================================================

def test_the_marker_round_trips_from_the_tail_and_is_falsifiable():
    atom = hollow.marker_bytes(1000, [5, 0, 5, 3], "2026-11-22 10:00:00")
    doc = hollow.parse_marker_tail(b"x" * 50 + atom, 1000 + len(atom))
    assert doc["ccsync"] == "hollow" and doc["frames"] == [0, 3, 5] and doc["real_size"] == 1000
    # It must start exactly at the original's length.
    assert hollow.parse_marker_tail(b"x" * 50 + atom, 999 + len(atom)) is None


def test_a_free_atom_at_the_end_of_some_real_file_is_not_our_marker(tmp_path):
    body = json.dumps({"something": "else"}).encode()
    path = tmp_path / "other.mov"
    path.write_bytes(b"\x05" * 5000 + hf.box(b"free", body))
    assert hollow.read_marker(path) is None


def test_read_marker_reads_only_the_tail(tmp_path, monkeypatch):
    path = tmp_path / "x.braw"
    atom = hollow.marker_bytes(200_000, [0])
    path.write_bytes(b"\x07" * 200_000 + atom)
    reads = []
    real_open = open

    class Spy:
        def __init__(self, fh):
            self._fh = fh

        def __getattr__(self, name):
            return getattr(self._fh, name)

        def read(self, n=-1):
            reads.append(n)
            return self._fh.read(n)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._fh.close()

    monkeypatch.setattr("builtins.open", lambda p, mode="r", *a, **k: Spy(real_open(p, mode, *a, **k)))
    assert hollow.read_marker(path)["real_size"] == 200_000
    assert reads and all(0 < n <= hollow.MARKER_MAX_BYTES for n in reads)


# =============================================================================================
# The filesystem
# =============================================================================================

def test_the_drive_check_names_the_filesystem(tmp_path):
    able, name = hollow.can_hold_sparse(tmp_path)
    if os.name == "nt":
        assert name, "Windows always names the volume's filesystem"
    assert able in (True, False, None)


def test_a_drive_that_cannot_hold_sparse_files_is_refused_naming_its_format(tmp_path, monkeypatch, led):
    """D3: exFAT and FAT32 are refused with a sentence naming the format, and nothing is written."""
    original, _ = hf.write_braw(tmp_path / "nas" / "A001.braw")
    monkeypatch.setattr(hollow, "can_hold_sparse", lambda folder: (False, "exFAT"))
    dest = tmp_path / "tree" / "A001.braw"
    dest.parent.mkdir()
    text = _refusal(hollow.build_hollow, dest, hf.index_of(original), [5], hf.reader_of(original), led=led)
    assert "exFAT" in text
    assert list(dest.parent.iterdir()) == []
    assert led.entries() == []


def test_what_this_filesystem_does_with_a_hole_is_on_record(tmp_path):
    """Doc section 6 item 1 asks what APFS does with a sparse file, and the first Mac CI run
    (2026-11-22) answered for small files: the runner kept none of the fixtures' holes. This
    measures holes of three sizes the way the writer writes them and puts the numbers in the
    run's warnings summary, on every platform, so the answer for each runner is in its log.
    It asserts nothing about the filesystem: the writer's own check (`_check_allocation`) is
    what refuses a copy that did not come out hollow."""
    import warnings

    able, name = hollow.can_hold_sparse(tmp_path)
    if able is False:
        pytest.skip(f"SPARSE FILES UNAVAILABLE HERE: {tmp_path} is on {name}, which cannot hold "
                    "them; nothing to measure without writing the holes out in full")
    found = []
    for mib in (4, 32, 128):
        length, allocated = hf.measure_hole(tmp_path, mib << 20)
        kept = allocated < length * hollow.SPARSE_ALLOCATED_FRACTION
        found.append(f"{mib} MiB hole {'KEPT' if kept else 'FILLED IN'} ({allocated} of {length} bytes on disk)")
    warnings.warn(f"HOLES ON {name or 'this filesystem'} ({sys.platform}): " + "; ".join(found),
                  stacklevel=1)


def test_a_copy_that_did_not_come_out_hollow_is_never_placed(tmp_path, led, monkeypatch):
    """The first Mac CI run, 2026-11-22: the drive kept no hole of a 10 MB clip and the megabytes
    of slack in the allocation check let the copy through. A copy the filesystem sign cannot see
    is never placed, on any drive."""
    original, _ = hf.write_braw(tmp_path / "nas" / "A001.braw")
    dest = tmp_path / "tree" / "A001.braw"
    dest.parent.mkdir()
    size = original.stat().st_size
    monkeypatch.setattr(hollow, "sparse_refusal", lambda folder: None)
    monkeypatch.setattr(hollow, "_set_sparse", lambda fh: None)
    monkeypatch.setattr(hollow, "allocated_bytes", lambda p, st=None: size)     # every hole filled in
    text = _refusal(hollow.build_hollow, dest, hf.index_of(original), [20], hf.reader_of(original),
                    led=led)
    assert "filled in the empty parts" in text
    assert not dest.exists() and list(dest.parent.iterdir()) == [] and led.entries() == []


def test_trap_1_a_sparse_attribute_on_a_whole_file_is_not_a_sign(sparse_tmp, led):
    """rclone's multi-thread downloads leave a WHOLE original sparse on Windows (verified
    2026-11-22 with rclone v1.74.4: attributes 0x220, every byte allocated). Calling that hollow
    would keep a real original out of lane A and the manifest. Only allocation counts."""
    path = hf.plant_sparse_but_whole(sparse_tmp / "A002.braw")
    st = os.stat(path)
    if os.name == "nt":
        assert st.st_file_attributes & 0x200, "the fixture must really carry the sparse attribute"
    assert hollow.allocated_bytes(path, st) >= st.st_size
    assert hollow.filesystem_sign(path, st) is False
    assert hollow.is_hollow(path, st, deep=True) is False
    assert hollow.Pass("test").excluded(path, st) is False


def test_an_ntfs_compressed_file_that_is_not_sparse_is_not_a_sign(tmp_path, monkeypatch):
    """Allocated below its length for a reason that is not ours."""
    path = tmp_path / "c.braw"
    path.write_bytes(b"\0" * (4 << 20))
    st = os.stat(path)

    class Fake:
        st_mode, st_size = st.st_mode, st.st_size
        st_file_attributes = 0x800
        st_flags = 0x20
        st_blocks = 8

    monkeypatch.setattr(hollow, "allocated_bytes", lambda p, s=None: 4096)
    assert hollow.filesystem_sign(path, Fake()) is False


def test_a_small_file_is_never_the_filesystem_sign(tmp_path, monkeypatch):
    path = tmp_path / "s.braw"
    path.write_bytes(b"\1" * 1000)
    monkeypatch.setattr(hollow, "allocated_bytes", lambda p, s=None: 0)
    assert hollow.filesystem_sign(path) is False


# =============================================================================================
# The writer
# =============================================================================================

def test_the_writer_places_a_sparse_hollow_copy_with_the_frames_and_the_index(sparse_tmp, led):
    original, frames = hf.write_braw(sparse_tmp / "nas" / "A001.braw")
    idx = hf.index_of(original)
    dest = sparse_tmp / "tree" / "A001.braw"
    dest.parent.mkdir()
    entry = hollow.build_hollow(dest, idx, [20], hf.reader_of(original), nas_mtime="t", led=led)
    data_o, data_h = original.read_bytes(), dest.read_bytes()
    marker = hollow.marker_bytes(len(data_o), [0, 20], "t")
    assert len(data_h) > len(data_o), "the marker makes the length differ from the original's"
    assert data_h[:4100] == data_o[:4100]
    for n in (0, 20):
        off, ln = frames[n]
        assert data_h[off:off + ln] == data_o[off:off + ln]
    off, ln = frames[10]
    assert data_h[off:off + ln] == b"\0" * ln, "an unfetched frame is a hole"
    assert data_h[idx.moov_offset:len(data_o)] == data_o[idx.moov_offset:]
    assert hollow.read_marker(dest)["frames"] == [0, 20]
    assert len(data_h) == len(data_o) + len(marker)
    st = os.stat(dest)
    assert hollow.allocated_bytes(dest, st) < st.st_size // 4
    assert hollow.filesystem_sign(dest, st)
    assert entry["size"] == st.st_size and entry["nas_size"] == len(data_o)
    assert entry["frames"] == [0, 20]
    assert [p.name for p in dest.parent.iterdir()] == ["A001.braw"], "no temporary left behind"
    assert hollow.may_delete(dest)[0]


def test_the_writer_refuses_to_write_over_anything(sparse_tmp, led):
    original, _ = hf.write_braw(sparse_tmp / "nas" / "A001.braw")
    dest = sparse_tmp / "tree" / "A001.braw"
    dest.parent.mkdir()
    dest.write_bytes(b"the real original")
    _refusal(hollow.build_hollow, dest, hf.index_of(original), [3], hf.reader_of(original), led=led)
    assert dest.read_bytes() == b"the real original"


def test_a_real_original_landing_mid_build_is_never_overwritten(sparse_tmp, led):
    """The rename into place refuses an existing target: Bring originals can land the real file
    while a hollow copy is being built, and os.replace would put the hollow copy over it."""
    original, _ = hf.write_braw(sparse_tmp / "nas" / "A001.braw")
    dest = sparse_tmp / "tree" / "A001.braw"
    dest.parent.mkdir()
    base = hf.reader_of(original)

    def read(offset, length):
        if not dest.exists():
            dest.write_bytes(b"the real original")
        return base(offset, length)

    _refusal(hollow.build_hollow, dest, hf.index_of(original), [3], read, led=led)
    assert dest.read_bytes() == b"the real original"
    assert led.entries() == [], "the ledger row written before the rename is taken back"
    assert [p.name for p in dest.parent.iterdir()] == ["A001.braw"]


def test_a_frame_that_does_not_check_out_writes_nothing(sparse_tmp, led):
    original, frames = hf.write_braw(sparse_tmp / "nas" / "A001.braw")
    dest = sparse_tmp / "tree" / "A001.braw"
    dest.parent.mkdir()
    base = hf.reader_of(original)
    bad_at = frames[7][0]

    def read(offset, length):
        got = base(offset, length)
        return b"\xff" * len(got) if offset == bad_at else got

    assert "frame 7" in _refusal(hollow.build_hollow, dest, hf.index_of(original), [7], read, led=led)
    assert list(dest.parent.iterdir()) == []


def test_a_short_read_writes_nothing(sparse_tmp, led):
    original, _ = hf.write_braw(sparse_tmp / "nas" / "A001.braw")
    dest = sparse_tmp / "tree" / "A001.braw"
    dest.parent.mkdir()
    base = hf.reader_of(original)
    _refusal(hollow.build_hollow, dest, hf.index_of(original), [7],
             lambda o, n: base(o, n)[:-1], led=led)
    assert list(dest.parent.iterdir()) == []


def test_a_frame_outside_the_clip_is_refused_never_clamped(sparse_tmp, led):
    original, _ = hf.write_braw(sparse_tmp / "nas" / "A001.braw")
    dest = sparse_tmp / "tree" / "A001.braw"
    dest.parent.mkdir()
    text = _refusal(hollow.build_hollow, dest, hf.index_of(original), [hf.N_FRAMES],
                    hf.reader_of(original), led=led)
    assert "outside the clip" in text


def test_a_drive_that_fills_the_holes_in_is_caught_before_the_rename(sparse_tmp, led, monkeypatch):
    original, _ = hf.write_braw(sparse_tmp / "nas" / "A001.braw")
    dest = sparse_tmp / "tree" / "A001.braw"
    dest.parent.mkdir()
    monkeypatch.setattr(hollow, "allocated_bytes", lambda p, s=None: 10 ** 12)
    assert "filled in" in _refusal(hollow.build_hollow, dest, hf.index_of(original), [3],
                                   hf.reader_of(original), led=led)
    assert list(dest.parent.iterdir()) == []


def test_the_writer_never_shells_out_and_never_truncates():
    """Doc section 2.2: `truncate()` zero-fills on Windows (1.9 GB allocated for a 3 GB clip) and
    `fsutil` is a child process per clip. The sparse flag is set with DeviceIoControl."""
    source = Path(hollow.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assert "subprocess" not in code
    assert not re.search(r"\.truncate\(", code)
    assert "DeviceIoControl" in code


def test_adding_frames_builds_a_new_file_and_removes_the_old_one(sparse_tmp, led):
    original, frames = hf.write_braw(sparse_tmp / "nas" / "A001.braw")
    dest = sparse_tmp / "tree" / "A001.braw"
    dest.parent.mkdir()
    hollow.build_hollow(dest, hf.index_of(original), [20], hf.reader_of(original), led=led)
    fetched = []
    base = hf.reader_of(original)

    def read(offset, length):
        fetched.append(offset)
        return base(offset, length)

    entry = hollow.add_frames(dest, [30], read, nas_size=original.stat().st_size, led=led)
    assert fetched == [frames[30][0]], "only the NEW frame comes from the server"
    assert entry["frames"] == [0, 20, 30]
    assert hollow.read_marker(dest)["frames"] == [0, 20, 30]
    data_o, data_h = original.read_bytes(), dest.read_bytes()
    for n in (0, 20, 30):
        off, ln = frames[n]
        assert data_h[off:off + ln] == data_o[off:off + ln]
    assert [p.name for p in dest.parent.iterdir()] == ["A001.braw"], "the old copy is gone"
    assert [e["local_path"] for e in led.entries()] == [str(dest)]


def test_adding_frames_never_writes_into_the_old_file(sparse_tmp, led):
    """Resolve holds the file open without write sharing (doc section 2.4 row i). The old file's
    identity (inode / file id) must not be the new file's."""
    original, _ = hf.write_braw(sparse_tmp / "nas" / "A001.braw")
    dest = sparse_tmp / "tree" / "A001.braw"
    dest.parent.mkdir()
    hollow.build_hollow(dest, hf.index_of(original), [20], hf.reader_of(original), led=led)
    before = os.stat(dest).st_ino
    hollow.add_frames(dest, [31], hf.reader_of(original), nas_size=original.stat().st_size, led=led)
    assert os.stat(dest).st_ino != before


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing modes")
def test_an_old_copy_that_cannot_be_moved_aside_is_left_exactly_as_it_was(sparse_tmp, led):
    original, _ = hf.write_braw(sparse_tmp / "nas" / "A001.braw")
    dest = sparse_tmp / "tree" / "A001.braw"
    dest.parent.mkdir()
    hollow.build_hollow(dest, hf.index_of(original), [20], hf.reader_of(original), led=led)
    before = dest.read_bytes()
    with open(dest, "rb"):          # the CRT opens without delete sharing: a rename is refused
        _refusal(hollow.add_frames, dest, [30], hf.reader_of(original),
                 nas_size=original.stat().st_size, led=led)
    assert dest.read_bytes() == before
    assert [p.name for p in dest.parent.iterdir()] == ["A001.braw"]
    assert led.get(dest)["frames"] == [0, 20]


def test_adding_frames_to_a_clip_that_changed_on_the_server_is_refused(sparse_tmp, led):
    original, _ = hf.write_braw(sparse_tmp / "nas" / "A001.braw")
    dest = sparse_tmp / "tree" / "A001.braw"
    dest.parent.mkdir()
    hollow.build_hollow(dest, hf.index_of(original), [20], hf.reader_of(original), led=led)
    assert "changed" in _refusal(hollow.add_frames, dest, [30], hf.reader_of(original),
                                 nas_size=original.stat().st_size + 1, led=led)


def test_adding_frames_to_a_real_file_is_refused(tmp_path, led):
    original, _ = hf.write_braw(tmp_path / "A001.braw")
    assert "not a grading-frame copy" in _refusal(
        hollow.add_frames, original, [3], hf.reader_of(original),
        nas_size=original.stat().st_size, led=led)


# =============================================================================================
# The ledger
# =============================================================================================

def test_the_ledger_lives_in_the_redirected_state_dir_never_the_real_home():
    from conftest import REAL_CCSYNC_HOME

    path = hollow.default_state_path()
    assert path.name == hollow.STATE_FILENAME and path.parent.name == "state"
    assert not str(path).startswith(str(REAL_CCSYNC_HOME))
    assert hollow.ledger().path == path


def test_an_entry_is_falsified_by_a_file_of_another_size(tmp_path, led):
    path = tmp_path / "A001.braw"
    path.write_bytes(b"x" * 100)
    led.record(path, 100, 90, "", [0])
    assert hollow.signs(path, marker=False).ledger
    path.write_bytes(b"x" * 101)            # the real original arrived by some other route
    assert not hollow.signs(path, marker=False).ledger
    assert not hollow.is_hollow(path)


def test_the_key_folds_case_and_unicode_form_but_the_stored_path_keeps_its_bytes(tmp_path, led):
    nfd = unicodedata.normalize("NFD", "Šimalčík")
    nfc = unicodedata.normalize("NFC", "Šimalčík")
    raw = str(tmp_path / nfd / "A001.braw")
    led.record(raw, 10, 9, "", [0])
    # The Unicode form folds everywhere (CR-90). Case folds where the path's own spelling says
    # it does: a Windows path, here or as a canonical `P:\\...` string on a Mac (canon.norm). A
    # real posix path keeps its case, which is what the first Mac CI run said of this test.
    assert led.get(str(tmp_path / nfc / "A001.braw")) is not None
    if os.name == "nt":
        assert led.get(str(tmp_path / nfc / "A001.BRAW")) is not None
    assert led.entries()[0]["local_path"] == raw


def test_an_extended_length_windows_path_finds_the_same_row(tmp_path, led):
    path = str(tmp_path / "A001.braw")
    led.record(path, 10, 9, "", [0])
    if os.name == "nt":
        assert led.get("\\\\?\\" + path) is not None


def test_a_corrupt_ledger_is_empty_and_warns_once(tmp_path, caplog):
    path = tmp_path / "state" / hollow.STATE_FILENAME
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    led = hollow.HollowLedger(path)
    with caplog.at_level(logging.WARNING, logger="ccsync.hollow"):
        assert led.entries() == [] and led.entries() == []
    assert len([r for r in caplog.records if "not readable JSON" in r.getMessage()]) == 1


def test_the_ledger_survives_a_restart(tmp_path, led):
    led.record(tmp_path / "a.braw", 5, 4, "m", [0, 2])
    again = hollow.HollowLedger(led.path)
    assert again.get(tmp_path / "a.braw")["frames"] == [0, 2]
    doc = json.loads(led.path.read_text(encoding="utf-8"))
    assert doc["version"] == 1 and len(doc["hollow"]) == 1


def test_a_moved_folder_carries_its_rows(tmp_path, led):
    old = tmp_path / "Projects" / "A" / "Footage"
    led.record(old / "x.braw", 5, 4, "", [0])
    led.record(tmp_path / "Projects" / "A" / "Other" / "y.braw", 5, 4, "", [0])
    assert led.relocated(old, tmp_path / "Projects" / "B" / "Footage") == 1
    assert led.get(tmp_path / "Projects" / "B" / "Footage" / "x.braw") is not None
    assert led.get(old / "x.braw") is None


# =============================================================================================
# The predicate: any sign keeps it out; only all three delete it
# =============================================================================================

def test_any_single_sign_means_not_footage(tmp_path, led, sparse_tmp):
    by_ledger = tmp_path / "ledger.braw"
    by_ledger.write_bytes(b"x" * 64)
    led.record(by_ledger, 64, 50, "", [0])
    assert hollow.is_hollow(by_ledger)

    by_marker = tmp_path / "marker.braw"
    by_marker.write_bytes(b"\x03" * 5000 + hollow.marker_bytes(5000, [0]))
    assert hollow.is_hollow(by_marker) is False, "cheap mode does not open the file"
    assert hollow.is_hollow(by_marker, deep=True)

    by_fs = hf.plant_holes_only(sparse_tmp / "fs.braw")
    assert hollow.is_hollow(by_fs)

    plain = tmp_path / "real.braw"
    plain.write_bytes(b"\x04" * 5000)
    assert hollow.is_hollow(plain, deep=True) is False
    assert hollow.is_hollow(tmp_path / "absent.braw") is False


@pytest.mark.parametrize("drop", ["ledger", "marker", "filesystem"])
def test_a_delete_needs_all_three_signs_and_doubt_keeps_the_file(sparse_tmp, led, drop, caplog, monkeypatch):
    dest, _original = hf.plant_hollow(sparse_tmp / "tree" / "A001.braw", led=led)
    if drop == "ledger":
        led.forget(dest)
    elif drop == "marker":
        monkeypatch.setattr(hollow, "read_marker", lambda path, st=None: None)
    else:
        monkeypatch.setattr(hollow, "filesystem_sign", lambda path, st=None: False)
    ok, why = hollow.may_delete(dest)
    assert not ok and f"{drop} no" in why
    with caplog.at_level(logging.WARNING, logger="ccsync.hollow"):
        assert hollow.remove_hollow(dest, led) == (False, why)
    assert dest.exists()
    assert any("kept" in r.getMessage() and str(dest) in r.getMessage() for r in caplog.records)


def test_a_delete_with_all_three_signs_removes_the_file_and_its_row(sparse_tmp, led):
    dest, _ = hf.plant_hollow(sparse_tmp / "tree" / "A001.braw", led=led)
    assert hollow.remove_hollow(dest, led)[0]
    assert not dest.exists()
    assert led.get(dest) is None


def test_a_marker_that_disagrees_with_the_ledger_is_doubt(sparse_tmp, led):
    dest, _ = hf.plant_hollow(sparse_tmp / "tree" / "A001.braw", led=led)
    entry = led.get(dest)
    led.record(dest, entry["size"], entry["nas_size"] + 1, "", entry["frames"])
    ok, why = hollow.may_delete(dest)
    assert not ok and "disagree" in why


def test_trap_2_a_file_kept_out_on_the_filesystem_sign_alone_is_named_once_per_pass(sparse_tmp, led, caplog):
    stranger = hf.plant_holes_only(sparse_tmp / "Cloud.braw")
    ours, _ = hf.plant_hollow(sparse_tmp / "tree" / "A001.braw", led=led)
    led.forget(ours)                          # ours by its marker only: not a stranger
    with caplog.at_level(logging.WARNING, logger="ccsync.hollow"):
        first = hollow.Pass("manifest")
        assert first.excluded(stranger) and first.excluded(stranger)
        assert first.excluded(ours)
        second = hollow.Pass("manifest")
        assert second.excluded(stranger)
    lines = [r.getMessage() for r in caplog.records if "not treating" in r.getMessage()]
    assert len(lines) == 2, "one line per pass, not per call and not silence"
    assert all(str(stranger) in line and "no grading-frame marker" in line for line in lines)
    assert first.unexplained == [str(stranger)]


def test_a_walk_that_may_not_open_files_still_names_the_file(sparse_tmp, led, caplog):
    stranger = hf.plant_holes_only(sparse_tmp / "Cloud.braw")
    with caplog.at_level(logging.WARNING, logger="ccsync.hollow"):
        assert hollow.Pass("ledger scan", read_marker=False).excluded(stranger)
    assert any("was not opened" in r.getMessage() for r in caplog.records)


# =============================================================================================
# Lane A's list, moving aside, sweeping
# =============================================================================================

def test_lane_a_excludes_name_ledger_rows_and_filesystem_finds_relative_to_the_run(sparse_tmp, led):
    root = sparse_tmp / "root"
    project = root / "Projects" / "2026" / "Show"
    name = unicodedata.normalize("NFC", "Šimalčík A001.braw")
    hf.plant_hollow(project / "Footage" / name, led=led)
    hf.plant_holes_only(project / "Footage" / "cloud.mov")
    hf.plant_holes_only(project / "Footage" / "Proxy" / "cloud.mov")   # lane A never carries Proxy/
    (project / "Footage" / "real.braw").write_bytes(b"\x05" * 5000)
    got = hollow.lane_a_excludes(str(root), "Projects/2026/Show")
    assert f"Footage/{name}" in got
    assert unicodedata.normalize("NFD", f"Footage/{name}") in got
    assert "Footage/cloud.mov" in got
    assert not any("real.braw" in g or "Proxy" in g for g in got)
    whole = hollow.lane_a_excludes(str(root), None)
    assert f"Projects/2026/Show/Footage/{name}" in whole
    assert hollow.lane_a_excludes(str(root), "Projects/2026/Other") == []


def _copied_elsewhere(hollow_copy: Path, to: Path) -> Path:
    """The hollow copy as Explorer or Finder leaves it after a copy: every hole filled in, at a
    path the ledger has never heard of. Only the marker is left."""
    to.parent.mkdir(parents=True, exist_ok=True)
    to.write_bytes(hollow_copy.read_bytes())
    return to


def test_lane_a_leaves_out_a_copied_hollow_copy_that_only_its_marker_names(sparse_tmp, led, caplog,
                                                                             monkeypatch):
    """Review, 2026-11-22. A sync tree moved to a new drive by hand, or a project folder
    duplicated, copies a hollow copy with its holes FILLED IN to a path with no ledger row: two
    signs gone at once, and the file is a clip-sized run of zeros under the original's name.
    Lane A's periodic pass is `copy --ignore-existing`, so it must still be left out, by the
    marker; and the marker is read once per file, not once per pass."""
    root = sparse_tmp / "root"
    project = root / "Projects" / "2026" / "Show"
    planted, _ = hf.plant_hollow(sparse_tmp / "elsewhere" / "A001.braw", led=led)
    copy = _copied_elsewhere(planted, project / "Footage copy" / "A001.braw")
    (project / "Footage copy" / "real.braw").write_bytes(b"\x05" * (2 << 20))
    assert hollow.filesystem_sign(copy) is False and led.get(copy) is None
    assert hollow.is_hollow(copy) is False, "the cheap signs cannot see it: that is the gap"

    opened = []
    real_read = hollow.read_marker
    monkeypatch.setattr(hollow, "read_marker",
                        lambda p, st=None: opened.append(str(p)) or real_read(p, st))
    with caplog.at_level(logging.WARNING, logger="ccsync.hollow"):
        got = hollow.lane_a_excludes(str(root), "Projects/2026/Show")
    assert got == ["Footage copy/A001.braw"]
    assert any("carries the grading-frame marker" in r.getMessage() for r in caplog.records)
    first = len(opened)
    assert first >= 2, "every original in the walk is asked once"
    assert hollow.lane_a_excludes(str(root), "Projects/2026/Show") == got
    assert len(opened) == first, "a second pass reads no marker again: the verdict is remembered"
    # ...until the file changes: the real original replacing it is footage again.
    copy.write_bytes(b"\x07" * (3 << 20))
    assert hollow.lane_a_excludes(str(root), "Projects/2026/Show") == []


def test_a_walk_that_is_not_deep_reads_no_marker_of_an_ordinary_file(tmp_path, led, monkeypatch):
    """The manifest and the proxy scan walk every project every few minutes; only lane A pays
    for the marker of a file no cheap sign names."""
    path = tmp_path / "real.braw"
    path.write_bytes(b"\x05" * (2 << 20))
    monkeypatch.setattr(hollow, "read_marker", lambda *a, **k: pytest.fail("opened a file"))
    assert hollow.Pass("media manifest").excluded(path) is False


def test_a_filesystem_that_reports_no_blocks_at_all_is_cannot_tell_not_hollow(tmp_path, monkeypatch):
    """Review, 2026-11-22. Some network and FUSE mounts answer st_blocks = 0 for every file. A
    hollow copy always has its head and index on the disk, so zero is never ours; believing it
    would keep every original on such a drive out of lane A and the manifest."""
    path = tmp_path / "A001.braw"
    path.write_bytes(b"\x05" * 4096)
    mode = os.stat(path).st_mode

    class NoBlocks:
        st_mode, st_size, st_flags, st_blocks = mode, 5 << 30, 0, 0

    class MostlyHoles(NoBlocks):
        st_blocks = 20000          # about 10 MB of a 5 GB clip

    class Dataless(NoBlocks):
        st_flags = 0x40000000      # an iCloud placeholder says so itself

    with monkeypatch.context() as m:
        m.setattr(hollow.os, "name", "posix")
        verdicts = [hollow.filesystem_sign(path, st()) for st in (NoBlocks, MostlyHoles, Dataless)]
    assert verdicts == [False, True, True]


def test_lane_a_excludes_never_raise(monkeypatch, tmp_path):
    monkeypatch.setattr(hollow, "ledger", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert hollow.lane_a_excludes(str(tmp_path), "Projects/x") == []


def test_move_aside_and_back(sparse_tmp, led):
    dest, _ = hf.plant_hollow(sparse_tmp / "tree" / "A001.braw", led=led)
    aside = hollow.move_aside(dest, hollow.ASIDE_ORIGINALS, led)
    assert aside and not dest.exists() and Path(aside).exists()
    assert aside.endswith(hollow.TEMP_SUFFIX)
    assert led.get(aside)["aside_of"] == str(dest) and led.get(dest) is None
    assert hollow.restore_aside(aside, led=led)
    assert dest.exists() and led.get(dest) is not None and led.get(aside) is None


def test_a_file_only_the_filesystem_calls_hollow_is_never_moved(sparse_tmp, led):
    stranger = hf.plant_holes_only(sparse_tmp / "Cloud.braw")
    assert hollow.move_aside(stranger, hollow.ASIDE_ORIGINALS, led) is None
    assert stranger.exists()


def test_sweep_removes_an_added_frames_aside_once_it_can(sparse_tmp, led):
    dest, _ = hf.plant_hollow(sparse_tmp / "tree" / "A001.braw", led=led)
    aside = hollow.move_aside(dest, hollow.ASIDE_ADDED_FRAMES, led)
    assert hollow.sweep_asides(led) == 1
    assert not Path(aside).exists()


def test_no_sentence_an_editor_can_read_carries_an_em_dash():
    source = Path(hollow.__file__).read_text(encoding="utf-8")
    assert EM_DASH not in source


def test_nothing_in_the_running_app_calls_the_writer():
    """Companion release A (doc section 7, D5): the build that knows what a hollow copy is ships
    before any build that can make one. Until phase 3 only tests call the writer."""
    src = Path(hollow.__file__).parent
    writers = ("build_hollow(", "add_frames(", "_write_ranges(", "_set_sparse(")
    offenders = []
    for path in src.rglob("*.py"):
        if path.name == "hollow.py":
            continue
        text = path.read_text(encoding="utf-8")
        offenders += [f"{path.name}: {w}" for w in writers if w in text]
    assert offenders == []


# =============================================================================================
# Cross-cutting: every reader of "what is a video file" goes through the predicate
# =============================================================================================

# Every place in the companion that decides "this is a video file" from `VIDEO_EXTS` (rclone_lane's,
# originals_lane's copy, and the two modules' own lists of the same name), by enclosing function.
# ASKS: the function itself asks the hollow predicate (its source must say `hollow`).
# Anything else carries the reason it does not need to, written down here, where a reviewer
# reads it (docs/GRADING_FRAMES.md section 4, "one cross-cutting test", 2026-11-22). The test
# fails both ways: a NEW caller that is not on this list, and an entry that no longer exists.
ASKS = "asks the predicate"
VIDEO_EXTS_READERS = {
    ("manifest.py", "scan_local_manifest"): ASKS,
    ("proxy_scan.py", "scan_project"): ASKS,
    ("hollow.py", "_walk_video_files"):
        "the predicate's own walk for lane A's exclusions; every file it yields is judged by Pass",
    ("sync/rclone_lane.py", "<module>"): "the definition of the list itself",
    ("sync/rclone_lane.py", "build_filter_rules_up"):
        "lane A's filter: the hollow copies reach it as exclude_paths through extra_excludes_fn "
        "(app._lane_a_extra_excludes -> hollow.lane_a_excludes), ahead of these includes",
    ("sync/rclone_lane.py", "path_matches_lane_a_filter"):
        "a pure name rule, equivalent to the filter file; express's other gate, "
        "RcloneLane._express_partition, asks the predicate (deep) for every file it would send",
    ("sync/rclone_lane.py", "scan_local_tree"):
        "the removal gate's count of names NO lane carries and of future-dated files; a hollow "
        "copy is neither, and the doc keeps the removal gate unchanged (section 4 table)",
    ("sync/originals_lane.py", "<module>"): "a copy of the definition",
    ("sync/originals_lane.py", "list_rule_reason"):
        "a rule on NAS names before the list is built; the local copy is judged by "
        "_absent_or_hollow and plan_project(hollow_fn=is_our_hollow_copy)",
    ("sync/syncthing_admin.py", "<module>"):
        "lane C's ignore lines: Syncthing never carries a video file in either direction",
    ("app.py", "CompanionApp._classify_media_kind"):
        "names a Resolve media-pool path's KIND for the media-tree report, reading no file; the "
        "clip of a hollow copy is the original's clip, and nothing here counts it as held",
    ("youtube_import.py", "<module>"): "its own list of downloaded-programme extensions",
    ("youtube_import.py", "YoutubeImporter._is_clip_name"):
        "YouTube downloads in Youtube/ folders: never a camera original, never a hollow copy",
}


def _video_exts_readers() -> dict[tuple[str, str], str]:
    import ast

    root = Path(hollow.__file__).parent
    found: dict[tuple[str, str], str] = {}
    for path in sorted(root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")

        def visit(node, scope, body_src):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    inner = (ast.get_source_segment(source, child) or ""
                             if not isinstance(child, ast.ClassDef) else body_src)
                    visit(child, scope + [child.name], inner)
                    continue
                name = (child.id if isinstance(child, ast.Name)
                        else child.attr if isinstance(child, ast.Attribute) else None)
                if name in ("VIDEO_EXTS", "_VIDEO_EXTS"):
                    found[(path.relative_to(root).as_posix(), ".".join(scope) or "<module>")] = body_src
                visit(child, scope, body_src)

        visit(ast.parse(source), [], "")
    return found


def test_every_reader_of_video_exts_asks_the_predicate_or_says_why_not():
    found = _video_exts_readers()
    new = sorted(set(found) - set(VIDEO_EXTS_READERS))
    gone = sorted(set(VIDEO_EXTS_READERS) - set(found))
    assert not new, (f"new reader(s) of VIDEO_EXTS: {new}. A file a reader counts as footage must "
                     "not be a grading-frame copy: ask hollow.is_hollow / hollow.Pass in it, or "
                     "add it to VIDEO_EXTS_READERS with the reason it does not need to")
    assert not gone, f"VIDEO_EXTS_READERS names readers that no longer exist: {gone}"
    for key, why in VIDEO_EXTS_READERS.items():
        if why == ASKS:
            assert "hollow" in found[key], f"{key} is listed as asking the predicate and does not"
        else:
            assert len(why) > 20, f"{key}: the reason it does not ask must be written down"


def test_the_readers_the_doc_names_that_do_not_use_video_exts_ask_too():
    """Section 4's table names readers that decide by other lists (ledger_scan.Rules, field_mode,
    file_moves, originals_lane's plan, express). The scan above cannot see them; this can."""
    from ccsync_companion import field_mode, file_moves, ledger_scan
    from ccsync_companion.sync import originals_lane, rclone_lane
    import inspect

    must_ask = [ledger_scan.walk, field_mode.row_is_this_file, field_mode.quick_compare,
                field_mode.LedgerView._present, file_moves.apply_move,
                originals_lane.OriginalsDownLane._clear_hollow_copies,
                originals_lane._absent_or_hollow, rclone_lane.RcloneLane._express_partition]
    for fn in must_ask:
        assert "hollow" in inspect.getsource(fn), f"{fn.__qualname__} no longer asks the predicate"
