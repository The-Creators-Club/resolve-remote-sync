"""Grading frames, the fetch: request inbox, frame set, transport, refusals, balloons, Settings.

docs/GRADING_FRAMES.md phases 3 and 4 (2026-11-22). Every "server" file is a synthetic BRAW
built in the test (hollow_fixtures.py); the transport is either a fake that reads it locally, or
the real rclone binary reading it through rclone's own `:local` backend (doc 2.3: a ranged read
through a real remote could not be tried from this machine, so the argv is proved here instead).
Never P:\\, never the real ~/.ccsync, never Resolve.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

from ccsync_companion import grading_frames as gf
from ccsync_companion import hollow
from ccsync_companion.sync import rclone_lane

import hollow_fixtures as hf

EM_DASH = "\u2014"
PROJECT = "2026/Talk UA"
CLIP_REL = "BMCC/G011_10211743_C075.braw"


# =============================================================================================
# Fixtures: a tree, a "server", a fake transport
# =============================================================================================

@pytest.fixture
def led(tmp_path):
    return hollow.configure(tmp_path / "state" / hollow.STATE_FILENAME)


@pytest.fixture
def small_whole(monkeypatch):
    """The synthetic clips are ~10 MB; real ones are GBs. The 64 MB whole-file floor is scaled
    down so the hollow path is what these tests exercise (the rule itself has its own test)."""
    monkeypatch.setattr(gf, "WHOLE_FILE_BELOW", 1 << 20)


def _item(rel=PROJECT, slug="talk-ua", mode="full"):
    return {"slug": slug, "rel_path": rel, "position": 0, "sync_mode": mode}


class World:
    def __init__(self, tmp_path: Path, **braw) -> None:
        self.root = tmp_path / "root"
        self.nas = tmp_path / "nas"
        self.cfg = {"local_root": str(self.root), "remote": "nas", "remote_root": "/mnt/tank/tree",
                    "rclone_path": "rclone"}
        self.tree_rel = f"Projects/{PROJECT}/{CLIP_REL}"
        self.local = self.root.joinpath(*self.tree_rel.split("/"))
        (self.root / "Projects" / "2026" / "Talk UA").mkdir(parents=True)
        self.server_file, self.frames = hf.write_braw(self.nas.joinpath(*self.tree_rel.split("/")),
                                                      **braw)
        self.mtime = "2026-11-20T10:00:00Z"
        self.transport = FakeTransport(self)

    def clip(self, frames=(), uses=(), **over) -> dict:
        clip = {"file_path": str(self.local), "unique_id": "u1", "name": "G011", "frames": list(frames),
                "uses": [tuple(u) for u in uses], "clip_fps": 29.97, "timeline_fps": 29.97,
                "exact": True, "timecode": "01:00:14;29", "angle_timeline": "", "angle_timecode": ""}
        clip.update(over)
        return clip

    def fetch(self, selection=None, halted=False, platform="win32", refusal=None, led=None):
        return gf.ClipFetch(self.cfg, self.transport,
                            [_item()] if selection is None else selection, halted,
                            platform=platform, fetch_refusal=lambda cfg, dest: refusal, led=led)


class FakeTransport(gf.Transport):
    """The server file read locally: the same three calls the real transport makes."""

    def __init__(self, world: World) -> None:
        super().__init__(world.cfg)
        self.world = world
        self.reads: list[tuple[int, int]] = []
        self.wholes = 0
        self.fail = False

    def _path(self, tree_rel: str) -> Path:
        return self.world.nas.joinpath(*tree_rel.split("/"))

    def stat(self, tree_rel):
        if self.fail:
            raise gf.TransportError("rclone exited 1: connection refused")
        path = self._path(tree_rel)
        return (path.stat().st_size, self.world.mtime) if path.is_file() else None

    def read_range(self, tree_rel, offset, count):
        self.reads.append((offset, count))
        with open(self._path(tree_rel), "rb") as fh:
            fh.seek(offset)
            return fh.read(count)

    def fetch_whole(self, tree_rel, dest):
        self.wholes += 1
        shutil.copyfile(self._path(tree_rel), dest)


# =============================================================================================
# The request file
# =============================================================================================

def _request(**over) -> dict:
    body = {"v": 1, "source": "playhead", "project": "Talk UA", "timeline": "Cut",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "clips": [{"file_path": "P:\\Projects\\x.braw", "unique_id": "u", "name": "x",
                       "frames": [4184], "uses": [[4147, 4746]], "clip_fps": 29.97,
                       "timeline_fps": 29.97, "exact": True, "timecode": "01:00:01;07",
                       "angle_timeline": None, "angle_timecode": None}],
            "refused": []}
    body.update(over)
    return body


def test_a_well_formed_request_parses():
    got = gf.parse_request(json.dumps(_request()).encode())
    clip = got["clips"][0]
    assert clip["frames"] == [4184] and clip["uses"] == [(4147, 4746)]
    assert clip["exact"] is True and clip["clip_fps"] == 29.97 and clip["angle_timeline"] == ""


@pytest.mark.parametrize("change", [
    {"v": 2}, {"v": True}, {"source": "everything"}, {"clips": "x"}, {"clips": [], "refused": []},
    {"created_at": 5},
    {"clips": [{**_request()["clips"][0], "frames": [True]}]},
    {"clips": [{**_request()["clips"][0], "frames": [1.5]}]},
    {"clips": [{**_request()["clips"][0], "frames": list(range(100))}]},
    {"clips": [{**_request()["clips"][0], "uses": [[1, 2, 3]]}]},
    {"clips": [{**_request()["clips"][0], "exact": "yes"}]},
    {"clips": [{**_request()["clips"][0], "clip_fps": 0}]},
    {"clips": [{**_request()["clips"][0], "file_path": "P:\\a\x00.braw"}]},
    {"clips": [{**_request()["clips"][0], "file_path": None}]},
])
def test_a_malformed_request_is_refused(change):
    with pytest.raises(gf.RequestError):
        gf.parse_request(json.dumps(_request(**change)).encode())


def test_a_request_that_is_too_big_or_not_json_is_refused():
    with pytest.raises(gf.RequestError):
        gf.parse_request(b"{" * (gf.MAX_REQUEST_BYTES + 1))
    with pytest.raises(gf.RequestError):
        gf.parse_request(b"\xff\xfe")


def test_one_clip_cut_in_three_times_is_one_fetch():
    a = {"file_path": "P:\\A.braw", "frames": [5], "uses": [(0, 9)], "exact": True, "timecode": "",
         "angle_timeline": "", "angle_timecode": ""}
    b = {**a, "file_path": "p:\\a.BRAW", "frames": [5, 7], "uses": [(20, 29)], "exact": False}
    merged = gf.merge_clips([a, b])
    assert len(merged) == 1
    assert merged[0]["frames"] == [5, 7] and merged[0]["uses"] == [(0, 9), (20, 29)]
    assert merged[0]["exact"] is False


# =============================================================================================
# Which frames (D1, D2)
# =============================================================================================

def test_the_playhead_frame_and_the_uses_first_and_middle_each_with_neighbours():
    assert gf.frame_set([20], [(10, 30)], 40) == [9, 10, 11, 19, 20, 21]


def test_a_neighbour_outside_the_clip_is_quietly_left_out():
    assert gf.frame_set([0], [], 40) == [0, 1]
    assert gf.frame_set([39], [(39, 39)], 40) == [38, 39]


def test_a_frame_asked_for_outside_the_clip_is_refused_never_clamped():
    with pytest.raises(gf.Refused) as caught:
        gf.frame_set([40], [], 40)
    assert "frame 40 is outside the clip (it has 40 frames)" in str(caught.value)
    with pytest.raises(gf.Refused):
        gf.frame_set([-1], [], 40)


def test_a_use_is_kept_inside_the_clip_and_one_wholly_outside_is_dropped():
    assert gf.frame_set([], [(35, 60)], 40) == [34, 35, 36, 37, 38]
    assert gf.frame_set([5], [(50, 60)], 40) == [4, 5, 6]


def test_a_media_pool_clip_gets_the_first_and_middle_of_the_whole_clip():
    assert gf.frame_set([], [], 40) == [0, 1, 18, 19, 20]


# =============================================================================================
# The transport: the exact argv, and one real rclone run against a local file
# =============================================================================================

def test_the_argv_uses_the_down_route_and_bring_originals_flags():
    cfg = {"remote": "nas", "remote_root": "/mnt/tank/tree", "rclone_path": "rclone"}
    t = gf.Transport(cfg)
    flags = [*rclone_lane.RcloneTuning.from_cfg(cfg).flags(rclone_lane.DIRECTION_DOWN),
             *rclone_lane._transport_flags()]
    src = "nas:/mnt/tank/tree/Projects/2026/X/A.braw"
    assert t.read_argv("Projects/2026/X/A.braw", 4100, 3000000) == [
        "rclone", "cat", src, "--offset", "4100", "--count", "3000000", *flags]
    assert t.stat_argv("Projects/2026/X/A.braw") == ["rclone", "lsjson", src, *flags]
    assert t.whole_argv("Projects/2026/X/A.braw", Path("D:/x/A.braw"))[:5] == [
        "rclone", "copyto", src, str(Path("D:/x/A.braw")), "--ignore-existing"]


def test_a_tunnel_route_applies_to_the_fetch_too(monkeypatch):
    monkeypatch.setattr(rclone_lane, "route_refusal", lambda *a, **k: "")
    cfg = {"remote": "nas", "remote_root": "/mnt/tank/tree", "remote_down": "tunnel",
           "remote_down_root": "/", "rclone_path": "rclone"}
    argv = gf.Transport(cfg).read_argv("Projects/A.braw", 0, 10)
    # The same join Bring originals uses (rclone_lane._join_remote_path): a tunnel serving the
    # tree as its root ("/") reads it relative to that root.
    assert argv[2] == f"tunnel:{rclone_lane._join_remote_path('/', 'Projects/A.braw')}"
    for flag in rclone_lane.REMOTE_DOWN_FLAGS:
        assert flag in argv


def _real_rclone() -> str:
    path = shutil.which("rclone")
    if not path:
        pytest.skip("NO RCLONE BINARY ON PATH: the real ranged read (rclone cat --offset --count) "
                    "is NOT TESTED on this machine")
    return path


def test_the_exact_argv_runs_against_a_real_rclone_reading_a_local_file(tmp_path, led, small_whole):
    """doc 2.3: `rclone cat --offset --count` through a real remote could not be timed from this
    machine. This runs the very argv the fetch builds, with rclone's `:local` backend standing in
    for the editor's remote, and builds a hollow copy from it end to end."""
    hf.need_sparse(tmp_path)
    world = World(tmp_path)
    world.cfg.update({"remote": ":local", "remote_root": world.nas.as_posix(),
                      "rclone_path": _real_rclone()})
    transport = gf.Transport(world.cfg)
    size, mtime = transport.stat(world.tree_rel)
    assert size == world.server_file.stat().st_size and mtime
    off, ln = world.frames[7]
    assert transport.read_range(world.tree_rel, off, ln) == world.server_file.read_bytes()[off:off + ln]
    assert transport.stat("Projects/nope.braw") is None
    fetch = gf.ClipFetch(world.cfg, transport, [_item()], False,
                         fetch_refusal=lambda cfg, dest: None)
    out = fetch.run(world.clip(frames=[20]))
    assert out.kind == "made", out.sentence
    data_o, data_h = world.server_file.read_bytes(), world.local.read_bytes()
    for n in (0, 19, 20, 21):
        o, n_len = world.frames[n]
        assert data_h[o:o + n_len] == data_o[o:o + n_len]
    assert hollow.may_delete(world.local)[0]


# =============================================================================================
# One clip: made, added, stale, whole
# =============================================================================================

def test_a_first_request_makes_a_hollow_copy_with_the_frame_set(tmp_path, led, small_whole):
    hf.need_sparse(tmp_path)
    world = World(tmp_path)
    out = world.fetch(led=led).run(world.clip(frames=[20], uses=[(10, 30)]))
    assert out.kind == "made", out.sentence
    assert out.frames == [9, 10, 11, 19, 20, 21]
    assert hollow.read_marker(world.local)["frames"] == [0, 9, 10, 11, 19, 20, 21]
    entry = led.get(world.local)
    assert entry["nas_size"] == world.server_file.stat().st_size and entry["nas_mtime"] == world.mtime
    assert gf.balloon([out]) == (
        "Grading frame ready: G011_10211743_C075 at 01:00:14;29. Switch to another timeline and "
        "back to load it, and set Playback > Proxy Handling to Prefer Camera Originals to see it.")


def test_neighbouring_frames_are_read_in_one_go(tmp_path, led, small_whole):
    hf.need_sparse(tmp_path)
    world = World(tmp_path)
    world.fetch(led=led).run(world.clip(frames=[20]))
    # head, index, frame 0 and its neighbour, frames 19-21 and 18 (the middle's set): the frames
    # are coalesced, so far fewer reads than frames.
    assert len(world.transport.reads) <= 5


def test_a_second_request_adds_frames_and_says_to_reopen(tmp_path, led, small_whole):
    hf.need_sparse(tmp_path)
    world = World(tmp_path)
    world.fetch(led=led).run(world.clip(frames=[20]))
    out = world.fetch(led=led).run(world.clip(frames=[30]))
    assert out.kind == "added", out.sentence
    assert 30 in hollow.read_marker(world.local)["frames"] and 20 in hollow.read_marker(world.local)["frames"]
    assert gf.balloon([out]) == ("Added to G011_10211743_C075. Close and reopen the project to "
                                 "see the new frames.")


def test_a_multicam_balloon_names_the_angle_timeline(tmp_path, led, small_whole):
    hf.need_sparse(tmp_path)
    world = World(tmp_path)
    out = world.fetch(led=led).run(world.clip(frames=[20], angle_timeline="Talk UA \u2014 ANGLE 1 (BMCC)",
                                              angle_timecode="01:01:49;12"))
    text = gf.balloon([out])
    assert text.endswith("Its raw settings are in the angle timeline Talk UA \u2014 ANGLE 1 (BMCC) "
                         "at 01:01:49;12 (Scripts > CC Sync > Go to grading frame).")


def test_a_copy_whose_server_file_changed_is_dropped_and_made_afresh(tmp_path, led, small_whole):
    hf.need_sparse(tmp_path)
    world = World(tmp_path)
    world.fetch(led=led).run(world.clip(frames=[20]))
    world.mtime = "2026-11-21T09:00:00Z"            # re-exported on the server since
    out = world.fetch(led=led).run(world.clip(frames=[30]))
    assert out.kind == "made", out.sentence
    assert 20 not in hollow.read_marker(world.local)["frames"]
    assert led.get(world.local)["nas_mtime"] == "2026-11-21T09:00:00Z"


def test_a_stale_copy_that_cannot_be_dropped_is_kept_and_refused(tmp_path, led, small_whole):
    hf.need_sparse(tmp_path)
    world = World(tmp_path)
    world.fetch(led=led).run(world.clip(frames=[20]))
    entry = led.get(world.local)
    led.record(world.local, entry["size"], entry["nas_size"] + 1, entry["nas_mtime"], entry["frames"])
    before = world.local.read_bytes()
    out = world.fetch(led=led).run(world.clip(frames=[30]))
    assert out.kind == "refused" and "out of date" in out.sentence
    assert world.local.read_bytes() == before


def test_a_file_under_64_mb_comes_down_whole(tmp_path, led):
    world = World(tmp_path)
    out = world.fetch(led=led).run(world.clip(frames=[20]))
    assert out.kind == "whole" and world.transport.wholes == 1
    assert world.local.read_bytes() == world.server_file.read_bytes()
    assert led.get(world.local) is None and hollow.read_marker(world.local) is None
    assert gf.balloon([out]).startswith("G011_10211743_C075 is small, so its whole original came down")


def test_frames_that_would_be_over_a_third_of_the_clip_bring_the_whole_file(tmp_path, led, small_whole):
    """A hollow copy must show the filesystem sign when it is made, or may_delete can never remove
    it. 40 frames of which a dozen are asked for (with neighbours) is over a third."""
    world = World(tmp_path)
    out = world.fetch(led=led).run(world.clip(frames=[5, 10, 15, 25, 30, 35], uses=[(0, 39)]))
    assert out.kind == "whole" and world.transport.wholes == 1
    assert hollow.read_marker(world.local) is None


def test_every_hollow_copy_the_fetch_makes_shows_the_filesystem_sign(tmp_path, led, small_whole):
    hf.need_sparse(tmp_path)
    world = World(tmp_path)
    out = world.fetch(led=led).run(world.clip(frames=[20], uses=[(10, 30)]))
    assert out.kind == "made"
    assert hollow.filesystem_sign(world.local)
    assert hollow.may_delete(world.local)[0]


# =============================================================================================
# Every refusal of doc 3.4, each a sentence naming the cause
# =============================================================================================

def _refused(out: gf.Outcome) -> str:
    assert out.kind == "refused", out
    assert EM_DASH not in out.sentence
    assert not out.sentence.endswith(".")
    text = gf.balloon([out])
    assert text.startswith("No grading frame for ") and EM_DASH not in text
    return out.sentence


def test_refused_not_a_braw(tmp_path, led):
    world = World(tmp_path)
    sentence = _refused(world.fetch(led=led).run(world.clip(file_path=str(world.local.with_suffix(".mov")))))
    assert sentence == ("it is not a Blackmagic RAW (.braw) clip, and grading frames are only fetched "
                        "for those for now")


def test_refused_outside_the_tree(tmp_path, led):
    world = World(tmp_path)
    sentence = _refused(world.fetch(led=led).run(world.clip(file_path=str(tmp_path / "elsewhere" / "A.braw"))))
    assert sentence == "it is not in this computer's tree"


def test_refused_a_project_not_ticked_here(tmp_path, led):
    world = World(tmp_path)
    sentence = _refused(world.fetch(selection=[_item(rel="2026/Other")], led=led).run(world.clip()))
    assert sentence == "its project is not ticked on this computer"


def test_refused_an_upload_only_tick(tmp_path, led):
    world = World(tmp_path)
    sentence = _refused(world.fetch(selection=[_item(mode="upload_only")], led=led).run(world.clip()))
    assert sentence == ("its project is ticked upload-only on this computer, so nothing comes down "
                        "for it. Tick it in full on the dashboard first")


def test_refused_a_sync_halt(tmp_path, led):
    world = World(tmp_path)
    sentence = _refused(world.fetch(halted=True, led=led).run(world.clip()))
    assert sentence == "syncing is stopped on this computer (a sync halt), so nothing is brought down"


def test_refused_a_tree_that_is_not_mounted(tmp_path, led):
    world = World(tmp_path)
    why = ("this computer's tree isn't mounted right now, so nothing can be downloaded into it -- "
           "reconnect the drive and try again")
    sentence = _refused(world.fetch(refusal=why, led=led).run(world.clip()))
    assert sentence == ("this computer's tree isn't mounted right now, so nothing can be downloaded "
                        "into it, reconnect the drive and try again")


def test_refused_a_drive_that_cannot_hold_sparse_files_names_its_format(tmp_path, led, monkeypatch):
    world = World(tmp_path)
    monkeypatch.setattr(hollow, "can_hold_sparse", lambda folder: (False, "exFAT"))
    sentence = _refused(world.fetch(led=led).run(world.clip()))
    assert sentence.startswith("the sync drive's format (exFAT) cannot keep the empty parts")
    assert world.transport.reads == [] and not world.local.exists()


def test_refused_the_real_original_already_here(tmp_path, led):
    world = World(tmp_path)
    world.local.parent.mkdir(parents=True)
    shutil.copyfile(world.server_file, world.local)
    sentence = _refused(world.fetch(led=led).run(world.clip()))
    assert sentence == "its real original is already on this computer, so there is nothing to fetch"


def test_refused_something_we_did_not_make_at_the_path(tmp_path, led):
    world = World(tmp_path)
    hf.plant_holes_only(world.local)
    sentence = _refused(world.fetch(led=led).run(world.clip()))
    assert sentence.startswith("something CC Sync did not make is already at its path")


def test_refused_a_layout_the_parser_refuses(tmp_path, led, small_whole):
    hf.need_sparse(tmp_path)
    world = World(tmp_path, moov_first=True)
    sentence = _refused(world.fetch(led=led).run(world.clip()))
    assert "index is at the start of the file" in sentence
    assert not world.local.exists()


def test_refused_not_on_the_server(tmp_path, led):
    world = World(tmp_path)
    world.server_file.unlink()
    assert _refused(world.fetch(led=led).run(world.clip())) == "it is not on the server at that path"


def test_refused_on_a_mac_behind_one_constant(tmp_path, led, monkeypatch):
    world = World(tmp_path)
    sentence = _refused(world.fetch(platform="darwin", led=led).run(world.clip()))
    assert sentence == ("grading frames are not available on a Mac yet, because they have not been "
                        "tested there. Bring originals still works")
    assert world.transport.reads == []
    monkeypatch.setattr(gf, "FETCH_ENABLED_ON_MACOS", True)
    assert world.fetch(platform="darwin", led=led).run(world.clip()).kind != "refused"


def test_refused_a_frame_asked_for_outside_the_clip(tmp_path, led, small_whole):
    hf.need_sparse(tmp_path)
    world = World(tmp_path)
    sentence = _refused(world.fetch(led=led).run(world.clip(frames=[hf.N_FRAMES + 3])))
    assert sentence == (f"frame {hf.N_FRAMES + 3} is outside the clip (it has {hf.N_FRAMES} frames), "
                        "so nothing was fetched for it")
    assert not world.local.exists()


def test_refused_when_the_server_cannot_be_read(tmp_path, led):
    world = World(tmp_path)
    world.transport.fail = True
    assert _refused(world.fetch(led=led).run(world.clip())) == (
        "the server could not be read just now, so nothing was fetched. Try again in a minute")


def test_every_refusal_sentence_in_the_module_is_free_of_em_dashes():
    assert EM_DASH not in Path(gf.__file__).read_text(encoding="utf-8")


# =============================================================================================
# Balloons for a batch, the inbox, the tray line, housekeeping
# =============================================================================================

def test_a_batch_balloon_counts_and_carries_the_first_refusal():
    outs = [gf.Outcome("A001", "made"), gf.Outcome("A002", "whole"), gf.Outcome("A003", "added"),
            gf.Outcome("A004", "refused", "its project is not ticked on this computer")]
    assert gf.balloon(outs, ["Multicam 2 has no file of its own (a multicam or compound clip). "
                             "Select its angle clips instead."]) == (
        "Grading frames ready for 2 clips. Switch to another timeline and back to load them, and "
        "set Playback > Proxy Handling to Prefer Camera Originals to see them. Added to 1 clip that "
        "already had grading frames. Close and reopen the project to see the new frames. Not "
        "fetched, 2 clips. A004: its project is not ticked on this computer. (1 more in the log.)")


def test_a_batch_where_nothing_came_says_so():
    text = gf.balloon([gf.Outcome("A1", "refused", "it is not on the server at that path"),
                       gf.Outcome("A2", "refused", "x")])
    assert text == ("No grading frame for 2 clips. A1: it is not on the server at that path. "
                    "(1 more in the log.)")


def _service(world: World, notes: list, **kw) -> gf.GradingFrames:
    return gf.GradingFrames(world.cfg, selection_fn=lambda: [_item()], notify_fn=notes.append,
                            transport=world.transport, fetch_refusal=lambda cfg, dest: None, **kw)


def _drop(inbox: Path, body: dict, name: str = "1-000001000001.json") -> Path:
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_the_inbox_answers_a_request_once_and_deletes_it(tmp_path, led, small_whole):
    hf.need_sparse(tmp_path)
    world = World(tmp_path)
    notes: list = []
    service = _service(world, notes)
    req = _request(clips=[{**_request()["clips"][0], "file_path": str(world.local), "frames": [20],
                           "uses": [], "timecode": ""}])
    path = _drop(gf.request_dir(), req)
    assert service.poll_once() == 1
    assert not path.exists() and service.poll_once() == 0
    assert notes == [gf.balloon([gf.Outcome("G011_10211743_C075", "made")])]
    assert hollow.read_marker(world.local) is not None


def test_the_inbox_lives_under_the_redirected_home():
    from conftest import REAL_CCSYNC_HOME

    assert not str(gf.request_dir()).startswith(str(REAL_CCSYNC_HOME))
    assert gf.request_dir().parts[-2:] == ("requests", "frames")


def test_a_malformed_or_old_request_is_deleted_unanswered(tmp_path):
    world = World(tmp_path)
    notes: list = []
    service = _service(world, notes)
    bad = _drop(gf.request_dir(), {"v": 9}, "1-a.json")
    old = _drop(gf.request_dir(), _request(created_at="2020-01-01T00:00:00Z"), "2-b.json")
    assert service.poll_once() == 2
    assert not bad.exists() and not old.exists() and notes == []


def test_the_script_s_own_refusals_reach_the_balloon(tmp_path):
    world = World(tmp_path)
    notes: list = []
    service = _service(world, notes)
    _drop(gf.request_dir(), _request(clips=[], refused=["Multicam 2 is a multicam this script cannot follow."]))
    service.poll_once()
    assert notes == ["No grading frame for 1 clip. Multicam 2 is a multicam this script cannot follow."]


def test_one_tray_line_while_a_batch_runs(tmp_path, led, small_whole):
    hf.need_sparse(tmp_path)
    world = World(tmp_path)
    seen: list = []
    service = _service(world, [])
    real = world.transport.read_range

    def spy(tree_rel, offset, count):
        seen.append(service.tray_line())
        return real(tree_rel, offset, count)

    world.transport.read_range = spy
    assert service.tray_line() is None
    service.answer({"clips": [world.clip(frames=[20])], "refused": []})
    assert seen and all(line == "Fetching a grading frame" for line in seen)
    assert service.tray_line() is None


def test_two_clips_at_a_time_never_more(tmp_path, led, small_whole, monkeypatch):
    world = World(tmp_path)
    inside, peak, lock = [0], [0], threading.Lock()

    def slow_run(self, clip):
        with lock:
            inside[0] += 1
            peak[0] = max(peak[0], inside[0])
        time.sleep(0.05)
        with lock:
            inside[0] -= 1
        return gf.Outcome(clip["name"], "refused", "x")

    monkeypatch.setattr(gf.ClipFetch, "run", slow_run)
    clips = [world.clip(file_path=str(world.local.with_name(f"C{i}.braw")), name=f"C{i}") for i in range(6)]
    _service(world, []).answer({"clips": clips, "refused": []})
    assert peak[0] == gf.CLIPS_AT_A_TIME


def test_housekeeping_prunes_rows_whose_file_is_gone_only_while_the_folder_is_there(tmp_path, led,
                                                                                    monkeypatch):
    here = tmp_path / "tree" / "A.braw"
    here.parent.mkdir(parents=True)
    led.record(here, 10, 9, "", [0])                                 # folder there, file gone
    led.record(tmp_path / "unplugged" / "B.braw", 10, 9, "", [0])    # whole drive away
    # A row this young may be one rename away from having its file (written BEFORE the rename,
    # and Bring originals does that on another thread): never pruned.
    assert gf.prune_ledger(led) == 0 and led.get(here) is not None
    monkeypatch.setattr(gf, "PRUNE_MIN_AGE_SECONDS", 0.0)
    assert gf.prune_ledger(led) == 1
    assert led.get(here) is None and led.get(tmp_path / "unplugged" / "B.braw") is not None


def test_housekeeping_sweeps_the_asides(tmp_path, led, monkeypatch):
    called = []
    monkeypatch.setattr(hollow, "sweep_asides", lambda *a, **k: called.append(1) or 0)
    _service(World(tmp_path), []).housekeeping()
    assert called == [1]


# =============================================================================================
# Settings > THIS COMPUTER
# =============================================================================================

def test_the_settings_lines():
    assert gf.settings_lines(12) == [
        "Grading frames: 12 clips",
        "This computer cannot render the final picture from these clips: a render stops at the "
        "first frame that was not fetched."]
    assert gf.settings_lines(1)[0] == "Grading frames: 1 clip"


def test_remove_all_removes_what_it_can_and_says_what_it_kept(tmp_path, led, small_whole):
    hf.need_sparse(tmp_path)
    world = World(tmp_path)
    world.fetch(led=led).run(world.clip(frames=[20]))
    other = World(tmp_path / "second")
    other.fetch(led=led).run(other.clip(frames=[20]))
    assert gf.GradingFrames.count() == 2
    entry = led.get(other.local)
    led.record(other.local, entry["size"], entry["nas_size"] + 1, "", entry["frames"])   # doubt
    text = gf.remove_all(led)
    assert text.startswith("Removed the grading frames of 1 clip. Reopen the project in Resolve to "
                           "see the proxies again. Kept 1 clip: G011_10211743_C075, because "
                           "its marker and the ledger disagree")
    assert not world.local.exists() and other.local.exists()
    assert gf.remove_all(hollow.HollowLedger(tmp_path / "empty.json")) == (
        "There are no grading frames on this computer.")


def test_settings_shows_the_line_and_the_button_through_the_shared_action(monkeypatch):
    from types import SimpleNamespace

    from ccsync_companion import settings_window as sw

    calls = []
    app = SimpleNamespace(grading_frames_count=lambda: 3,
                          remove_grading_frames=lambda: calls.append("removed") or "done")
    items = sw._grading_frames_items(app)
    texts = [getattr(i, "text", getattr(i, "label", "")) for i in items]
    assert texts[0] == "Grading frames: 3 clips"
    assert "cannot render the final picture" in texts[1]
    assert texts[2] == "REMOVE GRADING FRAMES"
    spawned = []
    monkeypatch.setattr(sw.tray_mod, "_spawn", lambda app, what, fn: spawned.append(what) or fn())
    monkeypatch.setattr(sw.tray_mod, "_notify", lambda app, msg: calls.append(msg))
    items[2].on_click()
    assert spawned == ["Remove grading frames"] and calls == ["removed", "done"]
    assert [getattr(i, "text", "") for i in sw._grading_frames_items(
        SimpleNamespace(grading_frames_count=lambda: 0))] == ["Grading frames: 0 clips"]


# -- review, 2026-11-22 ---------------------------------------------------------------------------

def test_an_inexact_frame_gets_a_wider_margin():
    """A frame the script could not map exactly (another frame rate, a retimed item) was two
    frames off on a live timeline; one neighbour either side would have missed it."""
    assert gf.frame_set([100], [], 1000) == [99, 100, 101]
    assert gf.frame_set([100], [], 1000, margin=gf.MARGIN_INEXACT) == [98, 99, 100, 101, 102]
    assert gf.frame_set([0], [], 3, margin=gf.MARGIN_INEXACT) == [0, 1, 2]


def test_the_fetch_widens_the_margin_for_a_clip_marked_inexact(tmp_path, led, small_whole):
    hf.need_sparse(tmp_path)
    world = World(tmp_path)
    out = world.fetch(led=led).run(world.clip(frames=[20], exact=False))
    assert out.kind == "made", out
    assert out.frames == [18, 19, 20, 21, 22]


def test_a_changed_time_is_compared_as_a_time_not_as_text():
    """The same instant through two routes: another time zone, another precision. Compared as
    text, every hollow copy would be stale (and deleted) the day the route changed."""
    same = [("2026-10-21T17:43:10+08:00", "2026-10-21T09:43:10Z"),
            ("2026-10-21T17:43:10.123456789+08:00", "2026-10-21T17:43:10+08:00"),
            ("2026-10-21T17:43:10+08:00", "2026-10-21T17:43:11+08:00"),
            ("", "2026-10-21T17:43:10+08:00"),
            ("not a time", "2026-10-21T17:43:10+08:00")]
    for then, now in same:
        assert gf._times_differ(then, now) is False, (then, now)
    assert gf._times_differ("2026-10-21T17:43:10+08:00", "2026-10-21T17:45:00+08:00") is True
