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
    for key in ("duration_s", "fps", "width", "height", "codec", "shot_date",
                "frames", "start_tc", "bitrate"):
        assert ours[key] == theirs[key], key


# ---------------------------------------------------------------------------
# the drop-frame rule (audit F6, 2026-09-17)
# ---------------------------------------------------------------------------
#
# A tmcd track carries the drop-frame BIT and ffprobe prints it as the
# separator, so a colon out of a tmcd file is a real non-drop timecode; a Sony
# body's rtmd data stream prints colons whatever the camera counted. Getting
# that wrong is R17's tenth case: 231 of the Johnny Harris shoot's 377 proxies
# are 29.97 NDF with a tmcd track, and every preview of them carried a
# semicolon the source never had, which Resolve refuses. Both pipelines have
# to answer identically or the same clip gets a linkable proxy on the base rig
# and an unlinkable one on an editor's machine.

_NTSC = "30000/1001"


def _probe_payload(*, rate=_NTSC, fmt_timecode=None, streams=()):
    fmt = {"duration": "10.0"}
    if fmt_timecode:
        fmt["tags"] = {"timecode": fmt_timecode}
    video = {"codec_type": "video", "codec_tag_string": "avc1", "width": 1920,
             "height": 1080, "codec_name": "h264", "avg_frame_rate": rate,
             "r_frame_rate": rate}
    return json.dumps({"format": fmt, "streams": [video, *streams]})


def _tmcd_stream(timecode, tag="tmcd"):
    return {"codec_type": "data", "codec_tag_string": tag,
            "tags": {"timecode": timecode}}


# (name, payload, what BOTH sides must answer)
_DROPFRAME_CASES = [
    # The Johnny Harris case, verified on cam-1-050.mov 2026-09-17: a tmcd
    # stream printing colons at 29.97 is genuinely non-drop. Untouched.
    ("tmcd colon at 29.97",
     _probe_payload(streams=[_tmcd_stream("13:53:30:02")]), "13:53:30:02"),
    # The Sony case the 2026-08-12 measurement was made on: the tag alone, no
    # tmcd stream anywhere. Still rewritten.
    ("tag-only colon at 29.97",
     _probe_payload(fmt_timecode="03:40:27:12"), "03:40:27;12"),
    # An rtmd data stream is NOT a tmcd stream: same Sony verdict.
    ("rtmd stream colon at 29.97",
     _probe_payload(streams=[_tmcd_stream("03:40:27:12", tag="rtmd")]),
     "03:40:27;12"),
    # Already drop-form: nothing to do, from either source.
    ("tmcd semicolon",
     _probe_payload(streams=[_tmcd_stream("13:53:30;02")]), "13:53:30;02"),
    # 23.976 is fractional but has no drop-frame variant, and integer rates
    # never drop -- neither is ever rewritten, tmcd or not.
    ("23.976 colon",
     _probe_payload(rate="24000/1001", fmt_timecode="03:40:27:12"),
     "03:40:27:12"),
    ("integer 30 colon",
     _probe_payload(rate="30/1", fmt_timecode="03:40:27:12"), "03:40:27:12"),
]


@needs_indexer
@pytest.mark.parametrize("name, payload, expected",
                         _DROPFRAME_CASES, ids=[c[0] for c in _DROPFRAME_CASES])
def test_the_drop_frame_rule_is_the_same_on_both_sides(monkeypatch, name,
                                                       payload, expected):
    monkeypatch.setattr(ft.subprocess, "run", lambda cmd, **kw: _FakeCompleted(stdout=payload))
    monkeypatch.setattr(indexer_ffmpeg.subprocess, "run",
                        lambda cmd, **kw: _FakeCompleted(stdout=payload))

    ours = bim.probe("ffmpeg", "clip.mov")["timecode"]

    info = json.loads(payload)
    tc, from_tmcd = indexer_ffmpeg.timecode_from_probe(info)
    theirs = indexer_ffmpeg.dropframe_normalized(
        tc, indexer_ffmpeg.video_fps(info), from_tmcd)

    assert ours == theirs == expected


@needs_indexer
def test_both_sides_report_the_untouched_timecode_as_start_tc(monkeypatch):
    """`videos.start_tc` describes the SOURCE (migration 012), so it is what
    the file prints -- the normalisation belongs to the proxy written against
    it, not to the column."""
    payload = _probe_payload(fmt_timecode="03:40:27:12")
    monkeypatch.setattr(ft.subprocess, "run", lambda cmd, **kw: _FakeCompleted(stdout=payload))
    monkeypatch.setattr(indexer_ffmpeg.subprocess, "run",
                        lambda cmd, **kw: _FakeCompleted(stdout=payload))

    assert bim.probe("ffmpeg", "clip.mov")["start_tc"] == "03:40:27:12"
    assert indexer_ffmpeg.probe_video("clip.mov")["start_tc"] == "03:40:27:12"
    # ...and the proxy still gets the drop-frame form for this source.
    assert bim.probe("ffmpeg", "clip.mov")["timecode"] == "03:40:27;12"


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


# The ONE thing that legitimately differs between the two proxy argvs, and at
# the default container it changes no output byte: the indexer writes straight
# to `<name>.mp4`, this pipeline writes `<name>.<ext>.partial`, and ffmpeg
# cannot pick a muxer from ".partial" (EINVAL at init, the whole 1040-clip
# base-rig queue overnight 2026-08-11).
_MUXER_DIVERGENCE = ["-f", "mp4"]


def _without_muxer(cmd):
    out = list(cmd)
    for i in range(len(out) - 1):
        if out[i:i + 2] == _MUXER_DIVERGENCE:
            del out[i:i + 2]
            break
    return out


def _indexer_encode_argv(monkeypatch, payload, *, nvenc, dest):
    """The argv the indexer's build_proxy would actually run, captured.

    The point of going through build_proxy rather than re-listing its flags:
    a hand copy of the indexer's spec fails nothing when the indexer alone
    changes, which is what let the two pipelines drift before (audit F8,
    2026-09-17). The probe it does on the way (timecode, frame rate) is
    answered from `payload`, and `verify=False` keeps the post-encode checks
    out of the capture.
    """
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        return _FakeCompleted(stdout=payload)

    monkeypatch.setattr(indexer_ffmpeg.subprocess, "run", fake_run)
    indexer_ffmpeg.build_proxy("in.mov", dest, use_nvenc=nvenc, verify=False)
    encodes = [c for c in calls if "-c:v" in c]
    assert len(encodes) == 1, calls
    return encodes[0]


@needs_indexer
@pytest.mark.parametrize("nvenc", [True, False])
@pytest.mark.parametrize("payload", [
    _probe_payload(streams=[_tmcd_stream("13:53:30:02")]),
    _probe_payload(fmt_timecode="03:40:27:12"),
    _probe_payload(rate="24000/1001"),
], ids=["tmcd-timecode", "tag-timecode", "no-timecode"])
def test_the_preview_argv_is_the_indexers_flag_for_flag(monkeypatch, tmp_path,
                                                        nvenc, payload):
    """Both pipelines' previews land in ONE archive and are served by one web
    UI, and since phase 3 one of them is the first proxy Resolve links -- two
    specs would mean the same clip is linkable on the base rig and refused on
    an editor's machine. Imported, not copied (audit F8)."""
    dest = tmp_path / "proxy.mp4"
    theirs = _indexer_encode_argv(monkeypatch, payload, nvenc=nvenc, dest=dest)

    monkeypatch.setattr(ft.subprocess, "run", lambda cmd, **kw: _FakeCompleted(stdout=payload))
    probe = bim.probe("ffmpeg", "in.mov")
    ours = bim.preview_proxy_cmd("ffmpeg", "in.mov", dest, nvenc=nvenc,
                                 timecode=probe["timecode"], fps=probe["fps"])

    assert _strip_binary_and_dest(_without_muxer(ours)) == _strip_binary_and_dest(theirs)
    # The divergence is the only one, and it is where it has to be: an OUTPUT
    # option, immediately before the destination.
    assert ours[-3:] == [*_MUXER_DIVERGENCE, str(dest)]


@needs_indexer
def test_the_preview_spec_constants_are_the_indexers():
    assert (ft.PROXY_HEIGHT, ft.PROXY_CQ, ft.PROXY_CRF, ft.PROXY_AUDIO_BITRATE) == (
        indexer_ffmpeg.PROXY_HEIGHT, indexer_ffmpeg.PROXY_CQ,
        indexer_ffmpeg.PROXY_CRF, indexer_ffmpeg.PROXY_AUDIO_BITRATE)


# ---------------------------------------------------------------------------
# the post-encode frame check (plan section 4)
# ---------------------------------------------------------------------------

@needs_indexer
def test_the_frame_count_argv_is_the_same_on_both_sides():
    assert (ft.count_frames_cmd("ffprobe", "x.mp4")
            == indexer_ffmpeg.count_frames_cmd("ffprobe", "x.mp4"))
    assert _sub(ft.count_frames_cmd("ffprobe", "x.mp4"),
                ["-count_packets", "-select_streams", "v:0"])


@needs_indexer
@pytest.mark.parametrize("stdout, expected", [
    ('{"streams": [{"nb_read_packets": "1674"}]}', 1674),
    ('{"streams": [{"nb_read_packets": 1674}]}', 1674),
    # Every shape of "could not tell" is None, never 0: the caller SKIPS the
    # comparison on None, and a 0 would condemn every proxy on a machine whose
    # ffprobe printed something unexpected.
    ('{"streams": []}', None),
    ('{"streams": [{}]}', None),
    ("", None),
    ("not json", None),
    (None, None),
])
def test_the_frame_count_is_parsed_the_same_on_both_sides(stdout, expected):
    assert ft.parse_frame_count(stdout) == expected
    assert indexer_ffmpeg.parse_frame_count(stdout) == expected


def test_count_frames_returns_none_when_ffprobe_refuses(monkeypatch):
    monkeypatch.setattr(ft.subprocess, "run",
                        lambda cmd, **kw: _FakeCompleted(returncode=1, stderr="nope"))
    assert bim.count_frames("ffmpeg", "x.mp4") is None


def test_count_frames_reads_the_packet_count(monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _FakeCompleted(stdout='{"streams": [{"nb_read_packets": "42"}]}')

    monkeypatch.setattr(ft.subprocess, "run", fake_run)

    assert bim.count_frames("ffmpeg", "x.mp4") == 42
    assert "-count_packets" in captured["cmd"]


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
