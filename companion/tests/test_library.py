"""Library-walk reader tests.

The fixture builds a SQLite Project.db with the EXACT mixed-case, quoted
column names the live PostgreSQL library uses, and its Clip blobs are real
Resolve framing (header + zstd frame) around a real protobuf. Anything less
would let a typo'd identifier or a mis-parsed varint pass here and fail only
on the editor's machine, where the whole point is that the failure is
invisible (the bridge falls back to the API and nobody notices the walk
stopped working).

Column list and shapes measured against the fleet's FF5 library on
2026-08-26; see docs/LIBRARY_WALK_PLAN.md.
"""

from __future__ import annotations

import os
import socket
import sqlite3
import uuid

import pytest

from ccsync_companion import library


# --------------------------------------------------------------------------
# blob helpers
# --------------------------------------------------------------------------

def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def make_clip_blob(directory: str, name: str, date: str = "Mon Aug 25 10:00:00 2026") -> bytes:
    """A Resolve Clip blob: <header><zstd frame of the protobuf>.

    Field 1 = directory, field 2 = file name, field 3 = a date string that
    the parser must stop at rather than mistake for more of the path.
    """
    import zstandard

    payload = bytearray()
    for tag, text in ((0x0A, directory), (0x12, name), (0x1A, date)):
        encoded = text.encode("utf-8")
        payload.append(tag)
        payload += _varint(len(encoded))
        payload += encoded
    frame = zstandard.ZstdCompressor().compress(bytes(payload))
    # Resolve's header is not a fixed width; decompress_blob finds the
    # frame rather than skipping N, so any plausible prefix exercises it.
    return b"\x01\x00\x00\x00\x09\x00\x00\x00\x00" + frame


DDL = """
CREATE TABLE "SM_Project" (
    "SM_Project_id" TEXT, "ProjectName" TEXT, "MediaPool" TEXT,
    "LastModTimeInSecs" INTEGER, "UpToDate" INTEGER);
CREATE TABLE "Sm2MpFolder" (
    "Sm2MpFolder_id" TEXT, "Name" TEXT, "Sm2MpFolder_Owner_id" TEXT,
    "Sm2MediaPool_id" TEXT, "DbSavedTime" INTEGER);
CREATE TABLE "Sm2MpFolder_Sm2MpMedia" (
    "DbOwner" TEXT, "DbAssociate" TEXT, "DbPropertyName" TEXT, "DbIndex" INTEGER);
CREATE TABLE "Sm2MpMedia" (
    "Sm2MpMedia_id" TEXT, "Name" TEXT, "Sm2MpFolder_id" TEXT, "FieldsBlob" BLOB);
CREATE TABLE "Sm2Timeline" (
    "Sm2Timeline_id" TEXT, "Name" TEXT, "SM_Project_id" TEXT,
    "Sequence" TEXT, "Sm2MpMedia_id" TEXT, "ModTimeInSecs" INTEGER);
CREATE TABLE "SM_Project_Sm2Timeline" (
    "DbOwner" TEXT, "DbAssociate" TEXT, "DbPropertyName" TEXT, "DbIndex" INTEGER);
CREATE TABLE "Sm2Sequence" (
    "Sm2Sequence_id" TEXT, "Sm2Timeline_id" TEXT, "Sm2MpMedia_id" TEXT,
    "LastChangedTime" INTEGER, "DbSavedTime" INTEGER);
CREATE TABLE "Sm2SequenceContainer" (
    "Sm2SequenceContainer_id" TEXT, "Sm2Sequence_id" TEXT, "DbSavedTime" INTEGER);
CREATE TABLE "Sm2SequenceContainer_Sm2TiTrack" (
    "DbOwner" TEXT, "DbAssociate" TEXT, "DbPropertyName" TEXT, "DbIndex" INTEGER);
CREATE TABLE "Sm2TiTrack" (
    "Sm2TiTrack_id" TEXT, "Type" INTEGER, "SubType" INTEGER,
    "UserDefinedName" TEXT, "Sm2Sequence_id" TEXT, "Sm2SequenceContainer_id" TEXT);
CREATE TABLE "Sm2TiItem" (
    "Sm2TiItem_id" TEXT, "Name" TEXT, "Start" TEXT, "Duration" TEXT,
    "MediaRef" TEXT, "MediaFilePath" TEXT, "Sm2TiTrack_id" TEXT);
CREATE TABLE "BtVideoInfo" (
    "BtVideoInfo_id" TEXT, "Clip" BLOB, "Proxy" BLOB, "Sm2MpMedia_id" TEXT);
CREATE TABLE "BtAudioInfo" (
    "BtAudioInfo_id" TEXT, "Clip" BLOB, "Sm2MpMedia_id" TEXT, "Sm2Timeline_id" TEXT);
"""


def _uid(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


class Builder:
    """Rows for one library, in the shapes the live schema actually has."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def project(self, name: str, pool: str) -> str:
        pid = _uid("project/" + name)
        self.conn.execute(
            'INSERT INTO "SM_Project" ("SM_Project_id","ProjectName","MediaPool",'
            '"LastModTimeInSecs","UpToDate") VALUES (?,?,?,?,?)',
            (pid, name, pool, 1787708979, 0))
        return pid

    def folder(self, key: str, name: str, owner: str = "", media_pool: str = "") -> str:
        fid = _uid("folder/" + key)
        self.conn.execute(
            'INSERT INTO "Sm2MpFolder" ("Sm2MpFolder_id","Name",'
            '"Sm2MpFolder_Owner_id","Sm2MediaPool_id","DbSavedTime") VALUES (?,?,?,?,?)',
            (fid, name, owner or None, media_pool or None, 100))
        return fid

    def clip(self, key: str, name: str, folder: str, directory: str = "",
             file_name: str = "", audio_only: bool = False) -> str:
        cid = _uid("clip/" + key)
        self.conn.execute(
            'INSERT INTO "Sm2MpMedia" ("Sm2MpMedia_id","Name","Sm2MpFolder_id","FieldsBlob") '
            'VALUES (?,?,?,?)', (cid, name, folder, None))
        # The association carries the same fact as the column; the live
        # library has 4,005 rows in each and zero disagreements.
        self.conn.execute(
            'INSERT INTO "Sm2MpFolder_Sm2MpMedia" ("DbOwner","DbAssociate",'
            '"DbPropertyName","DbIndex") VALUES (?,?,?,?)', (folder, cid, "MediaVec", 0))
        if directory:
            blob = make_clip_blob(directory, file_name or name)
            table = "BtAudioInfo" if audio_only else "BtVideoInfo"
            if audio_only:
                self.conn.execute(
                    'INSERT INTO "BtAudioInfo" ("BtAudioInfo_id","Clip","Sm2MpMedia_id",'
                    '"Sm2Timeline_id") VALUES (?,?,?,?)', (_uid("a/" + key), blob, cid, None))
            else:
                self.conn.execute(
                    'INSERT INTO "%s" ("BtVideoInfo_id","Clip","Proxy","Sm2MpMedia_id") '
                    'VALUES (?,?,?,?)' % table,
                    (_uid("v/" + key), blob, b"\x00" * 197, cid))
        return cid

    def timeline(self, project: str, key: str, name: str, index: int = 0,
                 pool_clip: str = "") -> tuple[str, str]:
        tid, sid = _uid("tl/" + key), _uid("seq/" + key)
        self.conn.execute(
            'INSERT INTO "Sm2Timeline" ("Sm2Timeline_id","Name","SM_Project_id",'
            '"Sequence","Sm2MpMedia_id","ModTimeInSecs") VALUES (?,?,?,?,?,?)',
            # SM_Project_id is NULL for every row in the live library.
            (tid, name, None, sid, pool_clip or None, 1787637675))
        self.conn.execute(
            'INSERT INTO "SM_Project_Sm2Timeline" ("DbOwner","DbAssociate",'
            '"DbPropertyName","DbIndex") VALUES (?,?,?,?)',
            (project, tid, "TimelineVec", index))
        self._sequence(sid, tid, "")
        return tid, sid

    def clip_sequence(self, key: str, pool_clip: str) -> str:
        """The sequence a multicam / compound pool clip owns."""
        sid = _uid("seq/" + key)
        self._sequence(sid, "", pool_clip)
        return sid

    def _sequence(self, sid: str, timeline: str, pool_clip: str) -> None:
        self.conn.execute(
            'INSERT INTO "Sm2Sequence" ("Sm2Sequence_id","Sm2Timeline_id",'
            '"Sm2MpMedia_id","LastChangedTime","DbSavedTime") VALUES (?,?,?,?,?)',
            (sid, timeline or None, pool_clip or None, 0, 8188))
        self.conn.execute(
            'INSERT INTO "Sm2SequenceContainer" ("Sm2SequenceContainer_id",'
            '"Sm2Sequence_id","DbSavedTime") VALUES (?,?,?)',
            (_uid("cont/" + sid), sid, 8188))

    def track(self, sequence: str, key: str, kind: int, index: int,
              name: str = "") -> str:
        tid = _uid("track/" + key)
        self.conn.execute(
            'INSERT INTO "Sm2TiTrack" ("Sm2TiTrack_id","Type","SubType",'
            '"UserDefinedName","Sm2Sequence_id","Sm2SequenceContainer_id") '
            # Sm2Sequence_id is NULL live; SubType is uninitialised memory.
            'VALUES (?,?,?,?,?,?)',
            (tid, kind, 538976288, name or None, None, _uid("cont/" + sequence)))
        self.conn.execute(
            'INSERT INTO "Sm2SequenceContainer_Sm2TiTrack" ("DbOwner","DbAssociate",'
            '"DbPropertyName","DbIndex") VALUES (?,?,?,?)',
            (_uid("cont/" + sequence), tid, "TrackVec", index))
        return tid

    def item(self, track: str, key: str, name: str, start: int,
             media: str = "", stale_path: str = "") -> str:
        iid = _uid("item/" + key)
        self.conn.execute(
            'INSERT INTO "Sm2TiItem" ("Sm2TiItem_id","Name","Start","Duration",'
            '"MediaRef","MediaFilePath","Sm2TiTrack_id") VALUES (?,?,?,?,?,?,?)',
            # Start/Duration are varchar decimal frame counts, not integers.
            (iid, name, str(start), "100", media or None, stale_path or None, track))
        return iid


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "Project.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(DDL)
    yield conn, path
    conn.close()


def open_library(path, project="Show") -> library.ProjectLibrary:
    info = library.LibraryInfo(kind="Disk", name="Local", sqlite_path=str(path))
    return library.ProjectLibrary(info, project)


# --------------------------------------------------------------------------
# blob decoding
# --------------------------------------------------------------------------

def test_clip_path_joins_with_the_directorys_own_separator():
    windows = make_clip_blob(r"P:\Projects\2026\FF5", "A001.braw")
    assert library.clip_path(library.decompress_blob(windows)) == r"P:\Projects\2026\FF5\A001.braw"

    unc = make_clip_blob(r"\\truenas\media\FF5\B-roll", "clip.mov")
    assert library.clip_path(library.decompress_blob(unc)) == r"\\truenas\media\FF5\B-roll\clip.mov"

    # A Mac's library stores a POSIX path; joining with os.sep would produce
    # /Volumes/Media\clip.mov on a Windows companion reading the same
    # library over the tailnet.
    posix = make_clip_blob("/Volumes/Media/FF5/B-roll", "clip.mov")
    assert library.clip_path(library.decompress_blob(posix)) == "/Volumes/Media/FF5/B-roll/clip.mov"


def test_clip_path_survives_cjk_and_names_over_127_bytes():
    directory = r"P:\Projects\2026\FF5\Civil Defence\B-roll\【真和平，要國防！523遊行】"
    name = "公視新聞網 - " + "長" * 60 + " [2wU3EcIfgcc].mp4"
    assert len(name.encode("utf-8")) > 127
    blob = make_clip_blob(directory, name)
    assert library.clip_path(library.decompress_blob(blob)) == directory + "\\" + name


def test_clip_path_does_not_care_which_order_the_fields_arrive_in():
    """Protobuf does not promise field order, and the parser used to stop
    dead the moment field 2 arrived -- so a name-first blob lost its whole
    directory (library walk review, 2026-08-26)."""
    import zstandard

    payload = bytearray()
    for tag, text in ((0x12, "A001.braw"), (0x0A, r"P:\Media\FF5"),
                      (0x1A, "Mon Aug 25 10:00:00 2026")):
        encoded = text.encode("utf-8")
        payload.append(tag)
        payload += _varint(len(encoded))
        payload += encoded
    blob = b"\x01\x00\x00\x00\x09\x00\x00\x00\x00" + zstandard.ZstdCompressor().compress(
        bytes(payload))
    assert library.clip_path(library.decompress_blob(blob)) == r"P:\Media\FF5\A001.braw"


def test_decompress_blob_is_quiet_about_rubbish():
    assert library.decompress_blob(None) is None
    assert library.decompress_blob(b"not a blob at all") is None
    assert library.clip_path(None) == ""
    assert library.clip_path(b"") == ""


# --------------------------------------------------------------------------
# timeline items
# --------------------------------------------------------------------------

def _simple_project(conn):
    b = Builder(conn)
    pool = _uid("pool/Show")
    project = b.project("Show", pool)
    root = b.folder("root", "Master", media_pool=pool)
    return b, project, root


def test_timeline_items_are_in_track_then_start_order(db):
    conn, path = db
    b, project, root = _simple_project(conn)
    one = b.clip("one", "one.mov", root, r"P:\Media", "one.mov")
    two = b.clip("two", "two.mov", root, r"P:\Media", "two.mov")
    three = b.clip("three", "three.wav", root, r"P:\Media", "three.wav", audio_only=True)
    _tl, seq = b.timeline(project, "e1", "Show - E1")
    v1 = b.track(seq, "v1", 0, 0)
    v2 = b.track(seq, "v2", 0, 1)
    a1 = b.track(seq, "a1", 1, 0)
    # Deliberately inserted out of order, and with Starts that only sort
    # correctly as integers (1000 < 9000 but "1000" > "09000" is the trap).
    b.item(v1, "i2", "two", 9000, two)
    b.item(v1, "i1", "one", 1000, one)
    b.item(v2, "i3", "one again", 500, one)
    b.item(a1, "i4", "three", 20, three)
    conn.commit()

    lib = open_library(path)
    items = lib.timeline_items(_uid("tl/e1"))
    assert [(i["track_type"], i["track_index"], i["item_index"], i["clip_name"])
            for i in items] == [
        ("video", 1, 0, "one"),
        ("video", 1, 1, "two"),
        ("video", 2, 0, "one again"),
        ("audio", 1, 0, "three"),
    ]
    assert items[0]["file_path"] == r"P:\Media\one.mov"
    assert items[0]["source"] == "library"
    assert items[0]["media_pool_item"] is None
    assert items[0]["media_pool_uid"] == one
    assert items[0]["via_multicam"] is None
    # The audio-only clip is reachable only through BtAudioInfo.
    assert items[3]["file_path"] == r"P:\Media\three.wav"
    lib.close()


def test_items_without_a_mediaref_are_skipped(db):
    conn, path = db
    b, project, root = _simple_project(conn)
    one = b.clip("one", "one.mov", root, r"P:\Media", "one.mov")
    _tl, seq = b.timeline(project, "e1", "Show - E1")
    v1 = b.track(seq, "v1", 0, 0)
    b.item(v1, "i1", "one", 0, one)
    b.item(v1, "gen", "Solid Color", 100)          # a generator: no media
    b.item(v1, "title", "Text+", 200)
    conn.commit()

    lib = open_library(path)
    items = lib.timeline_items(_uid("tl/e1"))
    assert [i["clip_name"] for i in items] == ["one"]
    lib.close()


def test_stale_mediafilepath_is_never_used(db):
    """Sm2TiItem.MediaFilePath is a placement-time snapshot. The pool wins."""
    conn, path = db
    b, project, root = _simple_project(conn)
    one = b.clip("one", "one.mov", root, r"W:\Creators_Club\FF5", "one.mov")
    _tl, seq = b.timeline(project, "e1", "Show - E1")
    v1 = b.track(seq, "v1", 0, 0)
    b.item(v1, "i1", "one", 0, one, stale_path=r"P:\Projects\gone\one.mov")
    conn.commit()

    lib = open_library(path)
    (item,) = lib.timeline_items(_uid("tl/e1"))
    assert item["file_path"] == r"W:\Creators_Club\FF5\one.mov"
    lib.close()


def test_multicam_expands_to_its_angles_once(db):
    conn, path = db
    b, project, root = _simple_project(conn)
    angle_a = b.clip("a", "camA.mov", root, r"P:\Media", "camA.mov")
    angle_b = b.clip("b", "camB.mov", root, r"P:\Media", "camB.mov")
    multicam = b.clip("mc", "Interview Multicam", root)     # no Clip blob
    mc_seq = b.clip_sequence("mc", multicam)
    mc_v1 = b.track(mc_seq, "mcv1", 0, 0, "Angle 1")
    mc_v2 = b.track(mc_seq, "mcv2", 0, 1, "Angle 2")
    b.item(mc_v1, "mca", "camA", 0, angle_a)
    b.item(mc_v2, "mcb", "camB", 0, angle_b)

    _tl, seq = b.timeline(project, "e1", "Show - E1")
    v1 = b.track(seq, "v1", 0, 0)
    b.item(v1, "cut1", "Interview Multicam", 0, multicam)
    b.item(v1, "cut2", "Interview Multicam", 100, multicam)
    b.item(v1, "cut3", "Interview Multicam", 200, multicam)
    conn.commit()

    lib = open_library(path)
    items = lib.timeline_items(_uid("tl/e1"))
    angles = [i for i in items if i["via_multicam"]]
    assert [i["file_path"] for i in angles] == [r"P:\Media\camA.mov", r"P:\Media\camB.mov"]
    assert {i["via_multicam"] for i in angles} == {multicam}
    # Every cut carries the SAME MediaRef; the angles appear once, and the
    # later cuts come back as the multicam itself (pathless, as the API
    # reports it) so no timeline item vanishes from the walk.
    rest = [i for i in items if not i["via_multicam"]]
    assert len(rest) == 2
    assert all(i["file_path"] == "" and i["media_pool_uid"] == multicam for i in rest)
    lib.close()


def test_a_compound_inside_a_multicam_recurses(db):
    conn, path = db
    b, project, root = _simple_project(conn)
    inner = b.clip("inner", "inner.mov", root, r"P:\Media", "inner.mov")
    compound = b.clip("cmp", "Compound", root)
    cmp_seq = b.clip_sequence("cmp", compound)
    cmp_v1 = b.track(cmp_seq, "cmpv1", 0, 0)
    b.item(cmp_v1, "cmpi", "inner", 0, inner)

    plain = b.clip("plain", "plain.mov", root, r"P:\Media", "plain.mov")
    multicam = b.clip("mc", "Multicam", root)
    mc_seq = b.clip_sequence("mc", multicam)
    mc_v1 = b.track(mc_seq, "mcv1", 0, 0, "Angle 1")
    mc_v2 = b.track(mc_seq, "mcv2", 0, 1, "Angle 2")
    b.item(mc_v1, "mc1", "plain", 0, plain)
    b.item(mc_v2, "mc2", "Compound", 0, compound)

    _tl, seq = b.timeline(project, "e1", "Show - E1")
    v1 = b.track(seq, "v1", 0, 0)
    b.item(v1, "cut1", "Multicam", 0, multicam)
    conn.commit()

    lib = open_library(path)
    items = lib.timeline_items(_uid("tl/e1"))
    assert [i["file_path"] for i in items] == [r"P:\Media\plain.mov", r"P:\Media\inner.mov"]
    # via_multicam names the clip THAT level was reached through, so the
    # nested item reports the compound, which is the object a caller can
    # actually act on.
    assert items[0]["via_multicam"] == multicam
    assert items[1]["via_multicam"] == compound
    lib.close()


def test_a_cyclic_multicam_terminates(db):
    """A library that refers to itself must not hang the watcher."""
    conn, path = db
    b, project, root = _simple_project(conn)
    leaf = b.clip("leaf", "leaf.mov", root, r"P:\Media", "leaf.mov")
    outer = b.clip("outer", "Outer", root)
    outer_seq = b.clip_sequence("outer", outer)
    outer_v1 = b.track(outer_seq, "ov1", 0, 0)
    b.item(outer_v1, "oi", "Outer again", 0, outer)      # points at itself
    b.item(outer_v1, "oleaf", "leaf", 100, leaf)

    _tl, seq = b.timeline(project, "e1", "Show - E1")
    v1 = b.track(seq, "v1", 0, 0)
    b.item(v1, "cut1", "Outer", 0, outer)
    conn.commit()

    lib = open_library(path)
    items = lib.timeline_items(_uid("tl/e1"))
    # The self-reference stops at the seen-set and comes back as ITSELF,
    # pathless, rather than as nothing: dropping it would take a real clip
    # out of the walk, which is what a caller checking for offline media
    # would then never hear about (library walk review, 2026-08-26).
    assert [(i["media_pool_uid"], i["file_path"]) for i in items] == [
        (outer, ""),
        (leaf, r"P:\Media\leaf.mov"),
    ]
    lib.close()


def test_the_depth_cap_returns_the_clip_rather_than_dropping_it(db, monkeypatch):
    """A chain deeper than MAX_EXPAND_DEPTH keeps its last clip."""
    conn, path = db
    b, project, root = _simple_project(conn)
    monkeypatch.setattr(library, "MAX_EXPAND_DEPTH", 2)
    inner = b.clip("inner", "inner.mov", root, r"P:\Media", "inner.mov")
    previous = inner
    for level in range(3):
        wrapper = b.clip("w%d" % level, "Compound %d" % level, root)
        wseq = b.clip_sequence("w%d" % level, wrapper)
        wtrack = b.track(wseq, "wt%d" % level, 0, 0)
        b.item(wtrack, "wi%d" % level, "inner", 0, previous)
        previous = wrapper

    _tl, seq = b.timeline(project, "e1", "Show - E1")
    v1 = b.track(seq, "v1", 0, 0)
    b.item(v1, "cut1", "Compound 2", 0, previous)
    conn.commit()

    lib = open_library(path)
    items = lib.timeline_items(_uid("tl/e1"))
    assert len(items) == 1
    # The cap bit one level above `inner`, so what comes back is the
    # compound at that level -- pathless, but present.
    assert items[0]["media_pool_uid"] == _uid("clip/w0")
    assert items[0]["file_path"] == ""
    lib.close()


def test_subtitle_tracks_are_not_walked_as_video(db):
    """Sm2TiTrack.Type 2 is subtitles, and its DbIndex restarts at 0 like
    every other kind's -- so reporting it as video makes subtitle track 1
    and V1 claim the same (track_type, track_index). Live FF5 has 6 such
    tracks carrying 3360 items."""
    conn, path = db
    b, project, root = _simple_project(conn)
    one = b.clip("one", "one.mov", root, r"P:\Media", "one.mov")
    caption = b.clip("cap", "caption.srt", root, r"P:\Media", "caption.srt")
    _tl, seq = b.timeline(project, "e1", "Show - E1")
    v1 = b.track(seq, "v1", 0, 0)
    st1 = b.track(seq, "st1", 2, 0, "Subtitle 1")
    b.item(v1, "i1", "one", 0, one)
    # A subtitle item WITH a MediaRef: live they are all NULL, which is
    # luck rather than a guarantee, and luck is not what the filter rests on.
    b.item(st1, "s1", "caption", 0, caption)
    conn.commit()

    lib = open_library(path)
    items = lib.timeline_items(_uid("tl/e1"))
    assert [(i["track_type"], i["track_index"], i["clip_name"]) for i in items] == [
        ("video", 1, "one")]
    lib.close()


def test_item_index_counts_timeline_items_not_emitted_dicts(db):
    """Angles share the index of the multicam item they were expanded from,
    so an index still names a place in the track the API agrees about."""
    conn, path = db
    b, project, root = _simple_project(conn)
    angle_a = b.clip("a", "camA.mov", root, r"P:\Media", "camA.mov")
    angle_b = b.clip("b", "camB.mov", root, r"P:\Media", "camB.mov")
    after = b.clip("after", "after.mov", root, r"P:\Media", "after.mov")
    multicam = b.clip("mc", "Multicam", root)
    mc_seq = b.clip_sequence("mc", multicam)
    b.item(b.track(mc_seq, "mcv1", 0, 0, "Angle 1"), "mca", "camA", 0, angle_a)
    b.item(b.track(mc_seq, "mcv2", 0, 1, "Angle 2"), "mcb", "camB", 0, angle_b)

    _tl, seq = b.timeline(project, "e1", "Show - E1")
    v1 = b.track(seq, "v1", 0, 0)
    b.item(v1, "cut1", "Multicam", 0, multicam)
    b.item(v1, "next", "after", 100, after)
    conn.commit()

    lib = open_library(path)
    items = lib.timeline_items(_uid("tl/e1"))
    assert [(i["clip_name"], i["item_index"]) for i in items] == [
        ("camA", 0), ("camB", 0), ("after", 1)]
    lib.close()


def test_an_unknown_timeline_is_unavailable_not_empty(db):
    """Empty would look like "this timeline has no media" and stop the
    fallback; the caller must be told the library could not answer."""
    conn, path = db
    b, project, root = _simple_project(conn)
    b.timeline(project, "e1", "Show - E1")
    conn.commit()

    lib = open_library(path)
    with pytest.raises(library.LibraryUnavailable):
        lib.timeline_items(_uid("tl/does-not-exist"))
    lib.close()


# --------------------------------------------------------------------------
# media pool
# --------------------------------------------------------------------------

def test_pool_is_scoped_to_this_projects_folder_tree_with_bin_paths(db):
    conn, path = db
    b = Builder(conn)
    pool = _uid("pool/Show")
    b.project("Show", pool)
    root = b.folder("root", "Master", media_pool=pool)
    interviewees = b.folder("iv", "Interviewees", owner=root)
    person = b.folder("person", "林飛帆", owner=interviewees)
    b.clip("m1", "master.mov", root, r"P:\Media", "master.mov")
    b.clip("m2", "iv.mov", interviewees, r"P:\Media", "iv.mov")
    b.clip("m3", "deep.mov", person, r"P:\Media", "deep.mov")

    # A second project in the SAME library, which must not leak in.
    other_pool = _uid("pool/Other")
    b.project("Other", other_pool)
    other_root = b.folder("oroot", "Master", media_pool=other_pool)
    b.clip("o1", "other.mov", other_root, r"P:\Other", "other.mov")
    conn.commit()

    lib = open_library(path)
    items = lib.pool_items()
    assert sorted((i["clip_name"], i["bin_path"]) for i in items) == [
        ("deep.mov", "Interviewees/林飛帆"),
        ("iv.mov", "Interviewees"),
        ("master.mov", ""),
    ]
    assert {i["resolve_project_name"] for i in items} == {"Show"}
    assert {i["source"] for i in items} == {"library"}
    # Open question 1: BtVideoInfo.Proxy is a reference stub with no path
    # and no state, so the library reports neither.
    assert {i["proxy_path"] for i in items} == {""}
    assert {i["proxy_state"] for i in items} == {""}
    lib.close()


def test_pool_paths_are_cached_until_the_library_moves(db):
    conn, path = db
    b, project, root = _simple_project(conn)
    one = b.clip("one", "one.mov", root, r"P:\Media", "one.mov")
    conn.commit()

    lib = open_library(path)
    assert lib.pool_paths()[one] == r"P:\Media\one.mov"

    conn.execute('UPDATE "BtVideoInfo" SET "Clip" = ?',
                 (make_clip_blob(r"W:\Relinked", "one.mov"),))
    conn.commit()
    assert lib.pool_paths()[one] == r"P:\Media\one.mov"       # still cached

    assert lib.changed() is True                              # first call: baseline
    assert lib.changed() is False
    conn.execute('UPDATE "SM_Project" SET "LastModTimeInSecs" = 1787999999')
    conn.commit()
    assert lib.changed() is True
    assert lib.pool_paths()[one] == r"W:\Relinked\one.mov"
    lib.close()


def test_a_missing_project_is_unavailable(db):
    conn, path = db
    b, _project, _root = _simple_project(conn)
    conn.commit()
    with pytest.raises(library.LibraryUnavailable):
        open_library(path, project="Not This One")


def test_a_missing_project_db_is_unavailable(tmp_path):
    info = library.LibraryInfo(kind="Disk", name="Local",
                               sqlite_path=str(tmp_path / "nope" / "Project.db"))
    with pytest.raises(library.LibraryUnavailable):
        library.ProjectLibrary(info, "Show")


def test_a_dead_postgres_host_is_unavailable():
    """No live Resolve, no live library: the reader must fail in the one way
    the bridge knows how to fall back from, and must do it inside the
    connect timeout rather than hanging the watcher."""
    info = library.LibraryInfo(kind="PostgreSQL", name="FF5",
                               host="127.0.0.1", port=1, password="DaVinci")
    with pytest.raises(library.LibraryUnavailable):
        library.ProjectLibrary(info, "Show")


def test_an_unknown_library_kind_is_unavailable():
    with pytest.raises(library.LibraryUnavailable):
        library.ProjectLibrary(library.LibraryInfo(kind="", name=""), "Show")


def test_a_non_numeric_start_is_logged_once_not_silently_zero(db, caplog):
    conn, path = db
    b, project, root = _simple_project(conn)
    one = b.clip("one", "one.mov", root, r"P:\Media", "one.mov")
    two = b.clip("two", "two.mov", root, r"P:\Media", "two.mov")
    _tl, seq = b.timeline(project, "e1", "Show - E1")
    v1 = b.track(seq, "v1", 0, 0)
    b.item(v1, "i1", "one", 100, one)
    b.item(v1, "i2", "two", 200, two)
    # Not an integer, but a number: '355231.0' used to raise out of int().
    conn.execute('UPDATE "Sm2TiItem" SET "Start" = ? WHERE "Name" = ?', ("300.0", "one"))
    conn.execute('UPDATE "Sm2TiItem" SET "Start" = ? WHERE "Name" = ?', ("later", "two"))
    conn.commit()

    library._WARNED_START = False
    with caplog.at_level("WARNING", logger="ccsync.library"):
        lib = open_library(path)
        items = lib.timeline_items(_uid("tl/e1"))
    # 'two' is unreadable, so it collapses to 0 and sorts first -- but loudly.
    assert [i["clip_name"] for i in items] == ["two", "one"]
    assert sum(1 for r in caplog.records if "Start" in r.getMessage()) == 1
    lib.close()


# --------------------------------------------------------------------------
# connection lifecycle
# --------------------------------------------------------------------------

class _FakeBackend(library._Backend):
    """A backend that connects fine and then fails every query."""

    opened: list = []

    def __init__(self, info):
        self.opened.append(self)
        self.closed = False

    def query(self, sql, **params):
        raise library.LibraryUnavailable("query failed: connection reset")

    def close(self):
        self.closed = True


def test_a_failed_project_lookup_closes_the_backend(monkeypatch):
    """__init__ used to leak the session it had just opened.

    _find_project_id raising left self._backend holding a live postgres
    connection that nobody outside could reach to close: 8 failed
    constructions measured 8 extra server sessions until gc. At a 3 s
    watcher poll and max_connections=100 that is the fleet locked out of
    the library in minutes (library walk review, 2026-08-26).
    """
    monkeypatch.setattr(_FakeBackend, "opened", [], raising=False)
    monkeypatch.setattr(library, "_PostgresBackend", _FakeBackend)
    info = library.LibraryInfo(kind="PostgreSQL", name="FF5", host="10.0.0.1")
    for _ in range(8):
        with pytest.raises(library.LibraryUnavailable):
            library.ProjectLibrary(info, "Show")
    assert len(_FakeBackend.opened) == 8
    assert all(backend.closed for backend in _FakeBackend.opened)


def test_a_failed_construction_leaves_no_open_socket(monkeypatch):
    """The same thing again, but proved at the socket rather than a flag."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    address = server.getsockname()

    class SocketBackend(library._Backend):
        def __init__(self, info):
            self.sock = socket.create_connection(address, timeout=5)

        def query(self, sql, **params):
            raise library.LibraryUnavailable("no such project")

        def close(self):
            self.sock.close()

    monkeypatch.setattr(library, "_PostgresBackend", SocketBackend)
    try:
        with pytest.raises(library.LibraryUnavailable):
            library.ProjectLibrary(
                library.LibraryInfo(kind="PostgreSQL", name="FF5", host="10.0.0.1"), "Show")
        accepted, _peer = server.accept()
        accepted.settimeout(5)
        # EOF rather than a timeout: the client end really is gone, not
        # merely unreferenced and waiting on the garbage collector.
        assert accepted.recv(1) == b""
        accepted.close()
    finally:
        server.close()


def test_queries_refuse_to_run_without_a_project_id(db, monkeypatch):
    """_project_id == "" bound NULL and matched NOTHING, quietly.

    changed() then answered False forever (so pool_paths served a frozen
    cache), timeline_items came back empty -- which reads as "this timeline
    has no media" and stops the bridge falling back -- and _folder_tree
    blamed the project for having no media pool.
    """
    conn, path = db
    b, project, root = _simple_project(conn)
    b.timeline(project, "e1", "Show - E1")
    conn.commit()

    lib = open_library(path)
    lib._project_id = ""
    # A reconnect would repair it, which is right in production and useless
    # for a test, so keep this one wedged.
    monkeypatch.setattr(lib, "_connect", lambda: None)
    for call in (lambda: lib.timeline_items(_uid("tl/e1")),
                 lib.pool_items, lib.pool_paths, lib.changed):
        with pytest.raises(library.LibraryUnavailable) as raised:
            call()
        assert "project id unknown" in str(raised.value)
    lib.close()


# --------------------------------------------------------------------------
# the PostgreSQL dialect
# --------------------------------------------------------------------------

def test_postgres_uid_binds_a_uuid_object():
    """pg8000 sends a str as text and postgres will not compare text to uuid.

    Every other SQL test in this file runs on SQLite, whose uid columns are
    TEXT and whose backend hands the string straight through -- so this
    conversion was the one piece of the reader that only ever ran on the
    editor's machine (library walk review, 2026-08-26).
    """
    backend = library._PostgresBackend.__new__(library._PostgresBackend)
    bound = backend.uid("232A7D03-5213-48E3-824E-229CF3B0B6BD")
    assert isinstance(bound, uuid.UUID)
    assert str(bound) == "232a7d03-5213-48e3-824e-229cf3b0b6bd"


def test_postgres_uid_refuses_a_malformed_uid():
    """It used to return None, which binds NULL: `IN (NULL)` matches nothing
    and the walk came back empty instead of unavailable, so the bridge never
    fell back to the API."""
    backend = library._PostgresBackend.__new__(library._PostgresBackend)
    for bad in ("", "not-a-uuid", "tl/does-not-exist", None):
        with pytest.raises(library.LibraryUnavailable):
            backend.uid(bad)


PG_ENV = "CCSYNC_LIBRARY_PG"


@pytest.mark.skipif(not os.environ.get(PG_ENV),
                    reason="set %s=host:port:db:user:password for the live "
                           "PostgreSQL dialect smoke test" % PG_ENV)
def test_postgres_dialect_against_a_live_library():
    """Read-only smoke test of the dialect path against a real library.

    Skipped by default: it needs a postgres project library on the network.
    Run on the base rig 2026-08-26 with
    CCSYNC_LIBRARY_PG=100.71.216.3:5432:FF5:postgres:DaVinci and
    CCSYNC_LIBRARY_PG_PROJECT="Civil Defence". Every statement it issues is
    a SELECT; it never opens Resolve and never touches the scripting API.
    """
    host, port, name, user, password = os.environ[PG_ENV].split(":", 4)
    project = os.environ.get("CCSYNC_LIBRARY_PG_PROJECT", "Civil Defence")
    info = library.LibraryInfo(kind="PostgreSQL", name=name, host=host,
                               port=int(port), user=user, password=password)
    lib = library.ProjectLibrary(info, project)
    try:
        pool = lib.pool_items()
        assert pool, "the project's bins came back empty"
        assert any(item["file_path"] for item in pool)

        rows = lib._query(
            'SELECT a."DbAssociate" FROM "SM_Project" p '
            'JOIN "SM_Project_Sm2Timeline" a ON a."DbOwner" = p."SM_Project_id" '
            'WHERE p."ProjectName" = :n', n=project)
        assert rows, "the project has no timelines"
        items = []
        for (timeline_uid,) in rows:
            items = lib.timeline_items(str(timeline_uid))
            if items:
                break
        assert items, "no timeline of %r had a single item" % project
        for item in items:
            assert item["source"] == "library"
            assert item["track_type"] in ("video", "audio")
            assert item["track_index"] >= 1
            assert isinstance(item["media_pool_uid"], str) and item["media_pool_uid"]
    finally:
        lib.close()


# --------------------------------------------------------------------------
# locate()
# --------------------------------------------------------------------------

WINDOWS_LOG = (
    "[0x000012a4] 25.08 09:00:01.100 | postgres project library FF5 at 100.71.216.3 "
    "version 13.23 (ok)\n"
    "[0x000012a4] 25.08 09:00:02.200 | Current project pointer changed to (Elections) "
    "from project library (FF5 : Network)\n"
    "[0x000012a4] 25.08 09:03:04.500 | Current project pointer changed to (Civil Defence) "
    "from project library (FF5 : Network)\n"
)

MACOS_LOG = (
    "[0x7000098] 25.08 09:00:01.100 | Current project pointer changed to (Reef) "
    "from project library (Local Database : Disk)\n"
)


@pytest.fixture()
def fake_log(tmp_path, monkeypatch):
    def install(text: str):
        support = tmp_path / "Support"
        logs = support / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        path = logs / "davinci_resolve.log"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setattr(library.luts, "resolve_log_path", lambda: path)
        return support
    return install


def test_locate_reads_the_windows_log_when_the_api_says_nothing(fake_log):
    fake_log(WINDOWS_LOG)
    info = library.locate(None, "Civil Defence", {})
    assert info is not None
    assert (info.kind, info.name, info.host) == ("PostgreSQL", "FF5", "100.71.216.3")


def test_locate_takes_the_last_pointer_line_for_the_named_project(fake_log):
    fake_log(WINDOWS_LOG)
    # The log is append-only across a session; asking for the other project
    # in it must still resolve, and to the same library.
    info = library.locate(None, "Elections", {})
    assert info is not None and info.name == "FF5"


def test_locate_reads_a_macos_disk_library_and_finds_its_project_db(fake_log, tmp_path):
    support = fake_log(MACOS_LOG)
    project_db = (support / "Resolve Project Library" / "Resolve Projects"
                  / "Users" / "guest" / "Projects" / "Reef" / "Project.db")
    project_db.parent.mkdir(parents=True)
    project_db.write_bytes(b"")
    info = library.locate(None, "Reef", {})
    assert info is not None
    assert info.kind == "Disk"
    assert info.sqlite_path == str(project_db)


def test_locate_prefers_the_api_when_it_answers(fake_log):
    fake_log(WINDOWS_LOG)

    class Manager:
        def GetCurrentDatabase(self):
            return {"DbType": "PostgreSQL", "DbName": "FF4", "IpAddress": "10.0.0.9"}

    class Resolve:
        def GetProjectManager(self):
            return Manager()

    info = library.locate(Resolve(), "Civil Defence", {})
    assert (info.name, info.host) == ("FF4", "10.0.0.9")


def test_locate_falls_back_to_the_log_when_resolve_21_returns_none(fake_log):
    fake_log(WINDOWS_LOG)

    class Manager:
        def GetCurrentDatabase(self):
            return None            # Resolve 21.0.1, every time

    class Resolve:
        def GetProjectManager(self):
            return Manager()

    info = library.locate(Resolve(), "Civil Defence", {})
    assert (info.name, info.host) == ("FF5", "100.71.216.3")


def test_database_info_is_the_only_api_call_locate_makes(fake_log):
    """A caller that serialises its Resolve calls behind a lock makes this
    one under the lock and hands the answer to locate(), leaving the log
    read and the disk-library walk outside it (library walk review 2,
    2026-08-26)."""
    fake_log(WINDOWS_LOG)

    class Manager:
        def GetCurrentDatabase(self):
            return {"DbType": "PostgreSQL", "DbName": "FF4", "IpAddress": "10.0.0.9"}

    class Resolve:
        def GetProjectManager(self):
            return Manager()

    info = library.database_info(Resolve())
    assert (info.kind, info.name, info.host) == ("PostgreSQL", "FF4", "10.0.0.9")
    assert library.database_info(None) is None


def test_locate_uses_the_api_answer_it_is_handed_and_asks_nothing(fake_log):
    fake_log(WINDOWS_LOG)

    class Exploding:
        def GetProjectManager(self):
            raise AssertionError("locate() asked Resolve after being handed an answer")

    handed = library.LibraryInfo(kind="PostgreSQL", name="FF4", host="10.0.0.9")
    info = library.locate(Exploding(), "Civil Defence", {}, api_info=handed)
    assert (info.name, info.host) == ("FF4", "10.0.0.9")

    # api_info=None means "the API had nothing", not "go and ask": the log
    # answers, exactly as it does for a Resolve 21 that returns None.
    info = library.locate(Exploding(), "Civil Defence", {}, api_info=None)
    assert (info.name, info.host) == ("FF5", "100.71.216.3")


def test_locate_overrides_win_over_both(fake_log):
    fake_log(WINDOWS_LOG)
    info = library.locate(None, "Civil Defence", {
        "library_db_host": "10.1.1.1",
        "library_db_port": "6543",
        "library_db_name": "FF6",
        "library_db_user": "editor",
        "library_db_password": "hunter2",
    })
    assert (info.kind, info.name, info.host, info.port, info.user, info.password) == (
        "PostgreSQL", "FF6", "10.1.1.1", 6543, "editor", "hunter2")


def test_locate_returns_none_when_nothing_knows(tmp_path, monkeypatch):
    monkeypatch.setattr(library.luts, "resolve_log_path", lambda: tmp_path / "nope.log")
    assert library.locate(None, "Civil Defence", {}) is None


def test_locate_never_raises(monkeypatch):
    def boom():
        raise OSError("no log for you")
    monkeypatch.setattr(library.luts, "resolve_log_path", boom)

    class Resolve:
        def GetProjectManager(self):
            raise RuntimeError("Resolve went away mid-call")

    assert library.locate(Resolve(), "Civil Defence", {}) is None


def test_locate_accepts_a_host_override_with_no_log_at_all(tmp_path, monkeypatch):
    monkeypatch.setattr(library.luts, "resolve_log_path", lambda: tmp_path / "nope.log")
    info = library.locate(None, "Civil Defence", {"library_db_host": "10.1.1.1",
                                                  "library_db_name": "FF5"})
    assert (info.kind, info.host, info.name) == ("PostgreSQL", "10.1.1.1", "FF5")
