"""broll_ingest_media.py: the ffmpeg work an editor's machine does before the
local model sees a clip, and the xxh64 fingerprint the archive dedupes on.

The point of this file is PARITY. A clip indexed here and a clip indexed on the
base rig land in one search database and are served by one web UI, so the
sprite geometry, the sampled frame times, the frames.json shape and the hash
have to be the indexer's, not merely "equivalent". Where the b-roll tree is
present the indexer's own module is loaded BY PATH and the two are compared
argv for argv; where it is not (a bare companion checkout), those tests skip
and the literal assertions still hold the shape.

No ffmpeg is run: every builder is pure, and `run_ffmpeg` is exercised against
a fake subprocess.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ccsync_companion import broll_ingest_media as bim
from ccsync_companion import ffmpeg_tools as ft

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEXER_FFMPEG_TOOLS = REPO_ROOT / "broll" / "indexer" / "broll_index" / "ffmpeg_tools.py"


def _load_indexer_ffmpeg_tools():
    """Import the indexer's ffmpeg_tools WITHOUT putting broll/indexer on
    sys.path -- the same by-path trick server/tests/test_cross_component.py
    uses, and for the same reason: two `tests` packages and two `config`
    modules would collide. It imports only the stdlib, so it needs no package
    around it."""
    if not INDEXER_FFMPEG_TOOLS.is_file():
        return None
    spec = importlib.util.spec_from_file_location(
        "broll_index_ffmpeg_tools_under_test", INDEXER_FFMPEG_TOOLS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


indexer_ffmpeg = _load_indexer_ffmpeg_tools()
needs_indexer = pytest.mark.skipif(
    indexer_ffmpeg is None,
    reason="broll/indexer is not in this checkout; the literal assertions still run")


def _after(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def _sub(cmd, sequence):
    n = len(sequence)
    return any(cmd[i:i + n] == sequence for i in range(len(cmd) - n + 1))


def _strip_binary_and_dest(cmd):
    """argv minus the binary and the destination -- the two things that
    legitimately differ between the indexer (bare "ffmpeg", its own data_root)
    and the companion (a configured path, the staging dir)."""
    return cmd[1:-1]


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ---------------------------------------------------------------------------
# the hash
# ---------------------------------------------------------------------------

def test_hash_partial_matches_the_indexers_digest_byte_for_byte(tmp_path):
    """`videos.hash` on 12,000 existing rows. Same file, same digest, or every
    clip an editor drops looks new to the dedupe."""
    xxhash = pytest.importorskip("xxhash")
    hashing_py = REPO_ROOT / "broll" / "indexer" / "broll_index" / "hashing.py"
    if not hashing_py.is_file():
        pytest.skip("broll/indexer is not in this checkout")
    spec = importlib.util.spec_from_file_location("broll_index_hashing_under_test", hashing_py)
    hashing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hashing)

    for size in (0, 1024, bim.HASH_CHUNK_SIZE - 1, bim.HASH_CHUNK_SIZE,
                 bim.HASH_CHUNK_SIZE + 1, bim.HASH_CHUNK_SIZE * 2 + 7):
        path = tmp_path / f"clip_{size}.mp4"
        path.write_bytes(bytes((i * 7 + 3) % 256 for i in range(size)))
        assert bim.hash_partial(path) == hashing.hash_file_partial(path), size
    assert xxhash  # the deferred import really is available


def test_hash_partial_mixes_the_size_in_as_its_decimal_string(tmp_path):
    """Two files that share head and tail but not length must not collide --
    which is the whole reason the size is in the digest at all."""
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    a.write_bytes(b"x" * 100)
    b.write_bytes(b"x" * 101)
    assert bim.hash_partial(a) != bim.hash_partial(b)


def test_hash_partial_reads_only_the_two_ends_of_a_big_file(tmp_path):
    """A 40 GB camera master must not be streamed end to end -- that is the
    difference between a fingerprint and a full read on every drop."""
    big = tmp_path / "big.mp4"
    with open(big, "wb") as fh:
        fh.write(b"head" * 16)
        fh.truncate(bim.HASH_CHUNK_SIZE * 3)
        fh.seek(bim.HASH_CHUNK_SIZE * 3 - 4)
        fh.write(b"tail")

    reads = []
    real_open = open

    class _CountingFile:
        def __init__(self, fh):
            self._fh = fh

        def read(self, n=-1):
            data = self._fh.read(n)
            reads.append(len(data))
            return data

        def __getattr__(self, name):
            return getattr(self._fh, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self._fh.close()

    import builtins
    builtins.open = lambda *a, **kw: _CountingFile(real_open(*a, **kw))
    try:
        bim.hash_partial(big)
    finally:
        builtins.open = real_open

    assert sum(reads) <= bim.HASH_CHUNK_SIZE * 2


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------

def test_probe_is_ffmpeg_tools_probe_and_carries_shot_date(monkeypatch):
    payload = json.dumps({
        "format": {"duration": "12.5", "tags": {"creation_time": "2026-08-14T09:12:33.000000Z"}},
        "streams": [{"codec_type": "video", "width": 3840, "height": 2160,
                     "codec_name": "hevc", "avg_frame_rate": "24000/1001"}],
    })
    monkeypatch.setattr(ft.subprocess, "run",
                        lambda cmd, **kw: _FakeCompleted(stdout=payload))
    info = bim.probe("ffmpeg", "A001.mov")
    assert info["shot_date"] == "2026-08-14"
    assert info["duration_s"] == pytest.approx(12.5)
    assert info["width"] == 3840


def test_probe_shot_date_is_none_when_the_file_has_no_creation_time(monkeypatch):
    payload = json.dumps({"format": {"duration": "3"},
                          "streams": [{"codec_type": "video", "width": 1920, "height": 1080}]})
    monkeypatch.setattr(ft.subprocess, "run",
                        lambda cmd, **kw: _FakeCompleted(stdout=payload))
    assert bim.probe("ffmpeg", "x.mp4")["shot_date"] is None


@needs_indexer
def test_probe_agrees_with_the_indexer_on_the_same_ffprobe_output(monkeypatch):
    payload = json.dumps({
        "format": {"duration": "61.2", "tags": {"creation_time": "2026-01-02T03:04:05Z"}},
        "streams": [{"codec_type": "video", "width": 1920, "height": 1080,
                     "codec_name": "h264", "avg_frame_rate": "30000/1001"}],
    })
    monkeypatch.setattr(ft.subprocess, "run", lambda cmd, **kw: _FakeCompleted(stdout=payload))
    monkeypatch.setattr(indexer_ffmpeg.subprocess, "run",
                        lambda cmd, **kw: _FakeCompleted(stdout=payload))

    ours = bim.probe("ffmpeg", "x.mp4")
    theirs = indexer_ffmpeg.probe_video("x.mp4")
    for key in ("duration_s", "fps", "width", "height", "codec", "shot_date"):
        assert ours[key] == theirs[key], key


# ---------------------------------------------------------------------------
# proxy
# ---------------------------------------------------------------------------

def test_the_proxy_is_ffmpeg_tools_own_builder():
    ours = bim.preview_proxy_cmd("ffmpeg", "in.mov", "out.mp4", nvenc=True)
    assert ours == ft.preview_proxy_cmd("ffmpeg", "in.mov", "out.mp4", nvenc=True)
    assert _sub(ours, ["-pix_fmt", "yuv420p"])


def test_the_ingest_proxy_carries_the_source_timecode():
    cmd = bim.preview_proxy_cmd("ffmpeg", "in.mov", "out.mp4", nvenc=False,
                                timecode="03:40:27;12")
    assert _sub(cmd, ["-timecode", "03:40:27;12"])


# ---------------------------------------------------------------------------
# sprite geometry + argv
# ---------------------------------------------------------------------------

def test_sprite_geometry_at_the_shipped_defaults():
    geo = bim.sprite_geometry(60.0)
    assert geo["sprite_interval_s"] == 2.0
    assert geo["sprite_cells"] == 31          # 60 // 2 + 1
    assert geo["sprite_cols"] == 10
    assert geo["sprite_rows"] == 4


def test_a_long_clip_widens_the_interval_instead_of_growing_the_sheet():
    """At 2 s a 16-minute clip wants ~490 cells (2400 x 6615 px), which failed
    outright on the real archive. Coarser scrubbing beats no sprite."""
    geo = bim.sprite_geometry(16 * 60)
    assert geo["sprite_cells"] == bim.SPRITE_MAX_CELLS
    assert geo["sprite_interval_s"] == pytest.approx(4.0)
    assert geo["sprite_rows"] == 24


def test_a_zero_length_clip_still_gets_one_cell():
    geo = bim.sprite_geometry(0)
    assert geo["sprite_cells"] == 1
    assert geo["sprite_rows"] == 1


@needs_indexer
@pytest.mark.parametrize("duration", [0.0, 5.0, 60.0, 480.0, 16 * 60, 3 * 3600])
def test_sprite_geometry_and_argv_match_the_indexers(monkeypatch, tmp_path, duration):
    """The browser reads `sprite_cols`/`sprite_cells`/`sprite_interval_s` off
    the row to place the hover overlay. Two producers, one column."""
    captured = {}
    monkeypatch.setattr(indexer_ffmpeg.subprocess, "run",
                        lambda cmd, **kw: captured.setdefault("cmd", cmd))
    monkeypatch.setattr(indexer_ffmpeg, "probe_image_size", lambda p: None)

    theirs = indexer_ffmpeg.build_sprite("in.mp4", tmp_path / "s.jpg", duration)
    geo = bim.sprite_geometry(duration)

    assert geo["sprite_cols"] == theirs["sprite_cols"]
    assert geo["sprite_cells"] == theirs["sprite_cells"]
    assert geo["sprite_interval_s"] == pytest.approx(theirs["sprite_interval_s"])

    ours = bim.sprite_cmd("ffmpeg", "in.mp4", tmp_path / "s.jpg", geo)
    assert _strip_binary_and_dest(ours) == _strip_binary_and_dest(captured["cmd"])


def test_sprite_argv_shape():
    geo = bim.sprite_geometry(60.0)
    cmd = bim.sprite_cmd("/opt/ffmpeg", "in.mp4", "sheet.jpg", geo)
    assert cmd[0] == "/opt/ffmpeg"
    assert _after(cmd, "-vf") == "fps=1/2.0,scale=240:-2,tile=10x4"
    assert _sub(cmd, ["-frames:v", "1"])
    assert cmd[-1] == "sheet.jpg"


# ---------------------------------------------------------------------------
# poster / thumb
# ---------------------------------------------------------------------------

@needs_indexer
@pytest.mark.parametrize("duration", [0.0, 10.0, 900.0])
def test_poster_argv_matches_the_indexers(monkeypatch, tmp_path, duration):
    captured = {}
    monkeypatch.setattr(indexer_ffmpeg.subprocess, "run",
                        lambda cmd, **kw: captured.setdefault("cmd", cmd))
    indexer_ffmpeg.build_poster("in.mp4", tmp_path / "p.jpg", duration)
    ours = bim.poster_cmd("ffmpeg", "in.mp4", tmp_path / "p.jpg", duration)
    assert _strip_binary_and_dest(ours) == _strip_binary_and_dest(captured["cmd"])


def test_poster_seeks_ten_percent_in():
    cmd = bim.poster_cmd("ffmpeg", "in.mp4", "p.jpg", 100.0)
    assert _after(cmd, "-ss") == "10.000"
    assert _after(cmd, "-vf") == "scale=640:-2"
    # An accurate seek: -ss BEFORE -i.
    assert cmd.index("-ss") < cmd.index("-i")


def test_thumb_is_a_160px_poster():
    cmd = bim.thumb_cmd("ffmpeg", "in.mp4", "t.jpg", 100.0)
    assert _after(cmd, "-vf") == "scale=160:-2"
    assert _after(cmd, "-ss") == "10.000"


# ---------------------------------------------------------------------------
# scene detection, gap filling, frames
# ---------------------------------------------------------------------------

@needs_indexer
def test_scene_detect_argv_matches_the_indexers(monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _FakeCompleted(stderr="")

    monkeypatch.setattr(indexer_ffmpeg.subprocess, "run", fake_run)
    indexer_ffmpeg.detect_scene_timestamps("in.mp4", 0.3)
    ours = bim.scene_detect_cmd("ffmpeg", "in.mp4", 0.3)
    # `-f null -` IS the destination here, so only the binary is dropped.
    assert ours[1:] == captured["cmd"][1:]


def test_parse_scene_timestamps_reads_showinfo_and_dedupes():
    stderr = (
        "[Parsed_showinfo_1 @ 0x1] n:0 pts:0 pts_time:0.000 pos:48\n"
        "[Parsed_showinfo_1 @ 0x1] n:1 pts:100 pts_time:4.200 pos:900\n"
        "[Parsed_showinfo_1 @ 0x1] n:2 pts:200 pts_time:4.200 pos:901\n"
        "frame= 3 fps=0.0 q=-0.0 Lsize=N/A\n"
    )
    assert bim.parse_scene_timestamps(stderr) == [0.0, 4.2]


def test_parse_scene_timestamps_of_a_single_shot_clip_is_empty():
    assert bim.parse_scene_timestamps("") == []
    assert bim.parse_scene_timestamps(None) == []


@needs_indexer
@pytest.mark.parametrize("timestamps,duration", [
    ([], 30.0),
    ([0.0], 30.0),
    ([5.0, 6.0, 25.0], 30.0),
    ([12.0], 12.5),
    ([1.0, 2.0, 3.0], 0.0),
    ([0.0, 100.0], 100.0),
])
def test_fill_gaps_matches_the_indexer_exactly(timestamps, duration):
    """These timestamps ARE what the model is shown. A copy that drifted means
    a clip sampled differently depending on which machine ingested it."""
    assert bim.fill_gaps(timestamps, duration) == indexer_ffmpeg.fill_gaps(
        list(timestamps), duration)


def test_fill_gaps_never_leaves_a_hole_bigger_than_the_max():
    points = bim.fill_gaps([0.0], 30.0, max_gap_s=4.0)
    assert points[0] == 0.0
    assert max(b - a for a, b in zip(points, points[1:])) <= 4.0 + 1e-6
    assert points[-1] == pytest.approx(30.0)


@needs_indexer
@pytest.mark.parametrize("ts,duration", [(0.0, 10.0), (9.999, 10.0), (4.5, None)])
def test_extract_frame_argv_matches_the_indexers(monkeypatch, tmp_path, ts, duration):
    captured = []
    monkeypatch.setattr(indexer_ffmpeg.subprocess, "run",
                        lambda cmd, **kw: captured.append(cmd))
    indexer_ffmpeg.extract_frames("in.mp4", [ts], tmp_path / "frames", duration_s=duration)
    ours = bim.extract_frame_cmd("ffmpeg", "in.mp4", ts,
                                 bim.frame_path(tmp_path / "frames", 0), duration_s=duration)
    assert _strip_binary_and_dest(ours) == _strip_binary_and_dest(captured[0])
    assert str(ours[-1]) == str(captured[0][-1])


def test_extract_frame_clamps_to_just_before_the_end():
    cmd = bim.extract_frame_cmd("ffmpeg", "in.mp4", 10.0, "f.jpg", duration_s=10.0)
    assert _after(cmd, "-ss") == "9.950"


def test_frame_path_is_the_name_load_frame_list_reconstructs():
    assert bim.frame_path("/frames", 0).name == "frame_0000.jpg"
    assert bim.frame_path("/frames", 42).name == "frame_0042.jpg"


def test_write_frames_json_is_the_shape_the_vendored_reader_parses(tmp_path):
    """load_frame_list pairs timestamps[i] with frames/frame_{i:04d}.jpg, so
    the file must carry the timestamps ACTUALLY SAMPLED, in request order."""
    from ccsync_companion.broll_vlm import local_vlm

    sheets_dir = tmp_path / "sheets" / "9"
    frames_dir = sheets_dir / "frames"
    frames_dir.mkdir(parents=True)
    timestamps = [0.0, 4.0, 8.0]
    for i, _t in enumerate(timestamps):
        bim.frame_path(frames_dir, i).write_bytes(b"jpeg")

    path = bim.write_frames_json(sheets_dir, timestamps)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "timestamps": [0.0, 4.0, 8.0], "sheets": []}

    frames = local_vlm.load_frame_list(sheets_dir)
    assert [f["t"] for f in frames] == timestamps
    assert frames[2]["path"] == bim.frame_path(frames_dir, 2)
    assert frames[0]["tc"] == "00:00:00"


def test_write_frames_json_keeps_the_holes(tmp_path):
    """A frame ffmpeg failed to produce must not shift every later timecode --
    the reader skips a missing file, which only works if the positions stay
    put."""
    from ccsync_companion.broll_vlm import local_vlm

    sheets_dir = tmp_path / "sheets" / "9"
    frames_dir = sheets_dir / "frames"
    frames_dir.mkdir(parents=True)
    bim.frame_path(frames_dir, 0).write_bytes(b"jpeg")
    bim.frame_path(frames_dir, 2).write_bytes(b"jpeg")   # 1 is missing

    bim.write_frames_json(sheets_dir, [0.0, 4.0, 8.0])
    frames = local_vlm.load_frame_list(sheets_dir)
    assert [f["t"] for f in frames] == [0.0, 8.0]


# ---------------------------------------------------------------------------
# running one
# ---------------------------------------------------------------------------

def test_run_ffmpeg_suppresses_the_console_window_and_drains_stderr(monkeypatch):
    """The companion is a windowed build and this runs hundreds of times per
    batch, unattended: an unflagged spawn would be a strobe light. stderr is
    read, not discarded -- for scene detection it IS the result, and left on a
    full pipe ffmpeg blocks for ever."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured.update(kwargs)
        return _FakeCompleted(returncode=0, stderr="pts_time:1.5")

    monkeypatch.setattr(bim.subprocess, "run", fake_run)
    code, stderr = bim.run_ffmpeg(["ffmpeg", "-i", "x"])

    assert (code, stderr) == (0, "pts_time:1.5")
    assert captured["capture_output"] is True
    assert "creationflags" in captured
    assert captured["encoding"] == "utf-8"


def test_run_ffmpeg_returns_a_failure_rather_than_raising(monkeypatch):
    monkeypatch.setattr(bim.subprocess, "run",
                        lambda cmd, **kw: _FakeCompleted(returncode=1, stderr="Invalid data"))
    code, stderr = bim.run_ffmpeg(["ffmpeg"])
    assert code == 1 and "Invalid data" in stderr


def test_run_ffmpeg_turns_a_missing_binary_into_unreadable_media(monkeypatch):
    def boom(cmd, **kw):
        raise OSError("no such file")

    monkeypatch.setattr(bim.subprocess, "run", boom)
    with pytest.raises(ft.UnreadableMediaError, match="could not be run"):
        bim.run_ffmpeg(["ffmpeg"])


def test_run_ffmpeg_turns_a_hang_into_unreadable_media(monkeypatch):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(bim.subprocess, "run", boom)
    with pytest.raises(ft.UnreadableMediaError, match="timed out"):
        bim.run_ffmpeg(["ffmpeg"], timeout=1)


# ---------------------------------------------------------------------------
# the constants themselves
# ---------------------------------------------------------------------------

@needs_indexer
def test_the_shared_constants_are_the_indexers():
    assert bim.SPRITE_MAX_CELLS == indexer_ffmpeg.SPRITE_MAX_CELLS
    assert bim.POSTER_WIDTH == 640          # build_poster's default
    assert (bim.SPRITE_COLUMNS, bim.SPRITE_CELL_WIDTH, bim.SPRITE_INTERVAL_S) == (10, 240, 2.0)


def test_the_hash_chunk_is_the_schemas():
    assert bim.HASH_CHUNK_SIZE == 8 * 1024 * 1024
