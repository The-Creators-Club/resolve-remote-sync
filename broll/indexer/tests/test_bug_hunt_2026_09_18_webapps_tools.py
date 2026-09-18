"""The 2026-09-18 hunt, the b-roll indexer's half (webapps-tools, CR-286).

No ffmpeg is run here: the encoder, the probes and the packet counts are the
module's own seams and are substituted, which is what lets these tests pin the
ORDER of the checks (broll-indexer-3 is entirely about which read is paid
for).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from broll_index import ffmpeg_tools

REPO = Path(__file__).resolve().parents[3]


# ------------------------------------------------------- broll-indexer-2

def test_a_frame_count_the_duration_contradicts_is_not_recorded():
    """`nb_frames` is what a killed encoder INTENDED to write, and this column
    decides an offline clip's length on every remote machine."""
    assert ffmpeg_tools._plausible_frames(1800, 60.0, 30.0) == 1800
    assert ffmpeg_tools._plausible_frames(5400, 60.0, 30.0) is None


def test_a_frame_count_nothing_can_check_is_left_alone():
    assert ffmpeg_tools._plausible_frames(1800, None, 30.0) == 1800
    assert ffmpeg_tools._plausible_frames(1800, 60.0, None) == 1800
    assert ffmpeg_tools._plausible_frames(None, 60.0, 30.0) is None


def test_probe_video_uses_the_checked_frame_count(monkeypatch):
    info = {
        "format": {"duration": "60.0"},
        "streams": [{"codec_type": "video", "codec_name": "h264",
                     "width": 1920, "height": 1080,
                     "avg_frame_rate": "30/1", "nb_frames": "9000"}],
    }
    monkeypatch.setattr(ffmpeg_tools, "run_ffprobe", lambda path: info)

    assert ffmpeg_tools.probe_video("x.mp4")["frames"] is None

    info["streams"][0]["nb_frames"] = "1800"
    assert ffmpeg_tools.probe_video("x.mp4")["frames"] == 1800


# ------------------------------------------------------- broll-indexer-3

class _Probe:
    """One ffprobe answer for a 60 s / 30 fps file."""

    INFO = {
        "format": {"duration": "60.0"},
        "streams": [{"codec_type": "video", "codec_name": "h264",
                     "width": 1920, "height": 1080,
                     "avg_frame_rate": "30/1"}],
    }


def _build(monkeypatch, tmp_path, counts):
    """Run build_proxy with every external read substituted.

    Returns the list of paths `count_frames` was asked about, which is the
    whole point: the SOURCE is on a 46 MB/s share and `-count_packets`
    demuxes the entire file.
    """
    asked = []

    def fake_count(path):
        asked.append(str(path))
        return counts.get("src" if str(path).endswith("src.mov") else "dest")

    class _Done:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(ffmpeg_tools, "run_ffprobe", lambda p: _Probe.INFO)
    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", lambda *a, **k: _Done())
    monkeypatch.setattr(ffmpeg_tools, "verify_decodes", lambda p: 0)
    monkeypatch.setattr(ffmpeg_tools, "count_frames", fake_count)
    monkeypatch.setattr(ffmpeg_tools, "probe_video",
                        lambda p: {"duration_s": 60.0})
    src = tmp_path / "src.mov"
    if not src.exists():
        # Not rewritten on a second call: the memo is keyed on (path, size,
        # mtime_ns), so re-writing the same bytes would look like a NEW file
        # and the "counted once" assertion below would pass or fail on the
        # clock's resolution.
        src.write_bytes(b"source")
    ffmpeg_tools.build_proxy(src, tmp_path / "out.mp4", use_nvenc=False)
    return asked


def test_a_source_is_demuxed_once_however_many_proxies_it_feeds(
        monkeypatch, tmp_path):
    """What is left of CR-286B after broll-indexer-1 (2026-09-18b).

    The cheap `duration * fps` screen it introduced is gone - it could not see
    a one-frame-short proxy, which is the failure this check exists for - so
    the exact comparison always runs. The saving that survives is the memo: an
    original is demuxed once per version of itself, not once per verification
    pass, per encoder retry or per proxy cut from it.
    """
    ffmpeg_tools.clear_frame_count_cache()
    asked = _build(monkeypatch, tmp_path, {"dest": 1800, "src": 1800})
    asked += _build(monkeypatch, tmp_path, {"dest": 1800, "src": 1800})
    assert len([a for a in asked if a.endswith("src.mov")]) == 1, asked
    ffmpeg_tools.clear_frame_count_cache()


def test_a_suspect_proxy_still_pays_for_the_real_count(monkeypatch, tmp_path):
    ffmpeg_tools.clear_frame_count_cache()
    with pytest.raises(RuntimeError) as exc:
        _build(monkeypatch, tmp_path, {"dest": 1782, "src": 1800})
    assert "1782 frames of the source's 1800" in str(exc.value)


def test_the_expected_count_comes_from_the_probe_and_not_nb_frames():
    assert ffmpeg_tools.expected_frames(_Probe.INFO) == 1800
    assert ffmpeg_tools.expected_frames({"format": {}, "streams": []}) is None


# ------------------------------------------------------- broll-indexer-1

def test_make_own_proxies_checks_the_frame_count(monkeypatch, tmp_path):
    """Its output is an editor-grade Proxy/<stem>.mp4 that Resolve links
    directly, so it is squarely in the class the 2026-09-17 check exists for -
    and it is the one producer that never got it."""
    import tools.make_own_proxies as mop

    class _Done:
        returncode = 0
        stderr = ""

    src = tmp_path / "A001.mov"
    src.write_bytes(b"source")
    monkeypatch.setattr(mop.ffmpeg_tools, "probe_video",
                        lambda p: {"duration_s": 60.0, "fps": 30.0,
                                   "width": 1920, "height": 1080})
    monkeypatch.setattr(mop.ffmpeg_tools, "read_timecode_source",
                        lambda p: (None, False))
    monkeypatch.setattr(mop.ffmpeg_tools, "verify_decodes", lambda p: 0)
    monkeypatch.setattr(mop.subprocess, "run", lambda *a, **k: _Done())
    monkeypatch.setattr(
        mop.ffmpeg_tools, "count_frames",
        lambda p: 1782 if str(p).endswith(".partial") else 1800)

    rec = mop.encode_one(src, cap_s=0, nvenc=False, dry=False)

    assert rec["status"] == "bad-output", rec
    assert "1782 frames of the source's 1800" in rec["detail"]
    assert not (src.parent / "Proxy" / "A001.mp4").exists()


def test_a_good_proxy_still_lands(monkeypatch, tmp_path):
    import tools.make_own_proxies as mop

    class _Done:
        returncode = 0
        stderr = ""

    src = tmp_path / "A002.mov"
    src.write_bytes(b"source")
    monkeypatch.setattr(mop.ffmpeg_tools, "probe_video",
                        lambda p: {"duration_s": 60.0, "fps": 30.0,
                                   "width": 1920, "height": 1080})
    monkeypatch.setattr(mop.ffmpeg_tools, "read_timecode_source",
                        lambda p: (None, False))
    monkeypatch.setattr(mop.ffmpeg_tools, "verify_decodes", lambda p: 0)
    monkeypatch.setattr(mop.ffmpeg_tools, "count_frames", lambda p: 1800)

    def fake_run(cmd, *a, **k):
        # The encoder writes the .partial the verification then reads.
        Path(cmd[-1]).write_bytes(b"proxy")
        return _Done()

    monkeypatch.setattr(mop.subprocess, "run", fake_run)

    rec = mop.encode_one(src, cap_s=0, nvenc=False, dry=False)

    assert rec["status"] == "ok", rec


# ------------------------------------------------------- broll-indexer-5

def test_the_remux_verifies_the_value_it_decided_on(monkeypatch, tmp_path):
    """A colon and a semicolon at the same numbers are different absolute
    frames; the guard only asserted that SOME timecode survived."""
    import fix_proxy_timecode as fpt

    class _Done:
        returncode = 0
        stderr = ""

    preview = tmp_path / "clip.mp4"
    preview.write_bytes(b"preview")

    def fake_run(cmd, *a, **k):
        Path(cmd[-1]).write_bytes(b"remuxed")
        return _Done()

    monkeypatch.setattr(fpt.subprocess, "run", fake_run)
    monkeypatch.setattr(fpt.ffmpeg_tools, "read_timecode",
                        lambda p: "01:00:00:00")

    why = fpt.remux(preview, "01;00;00;00")

    assert why and "01:00:00:00" in why, why
    assert "not 01;00;00;00" in why


def test_a_remux_that_kept_the_value_is_not_an_error(monkeypatch, tmp_path):
    import fix_proxy_timecode as fpt

    class _Done:
        returncode = 0
        stderr = ""

    preview = tmp_path / "clip2.mp4"
    preview.write_bytes(b"preview")
    monkeypatch.setattr(fpt.subprocess, "run",
                        lambda cmd, *a, **k: (Path(cmd[-1]).write_bytes(b"x"),
                                              _Done())[1])
    monkeypatch.setattr(fpt.ffmpeg_tools, "read_timecode",
                        lambda p: "01;00;00;00")

    assert fpt.remux(preview, "01;00;00;00") is None


# ------------------------------------------------------- broll-indexer-4

def test_a_clip_with_no_duration_is_parked_rather_than_crashing(monkeypatch,
                                                                tmp_path):
    from broll_index import pipeline

    updates = {}

    class _Storage:
        def update_video(self, vid, **fields):
            updates.update(fields)

    monkeypatch.setattr(pipeline.ffmpeg_tools, "probe_video",
                        lambda p: {"codec": "h264", "duration_s": None,
                                   "width": 1920, "height": 1080})

    class _Cfg:
        shares = {}

    pipeline.stage_probe(_Cfg(), _Storage(), {"id": 1, "share": "ff5"},
                         tmp_path / "x.ts")

    assert updates["status"] == "skipped"
    assert "no duration" in updates["error"]


def test_the_parked_row_is_not_mistaken_for_an_over_length_clip():
    from broll_index import pipeline

    assert pipeline.skipped_for_length(
        {"status": "skipped", "codec": "h264", "duration_s": None}) is False
    assert pipeline.skipped_for_length(
        {"status": "skipped", "codec": "h264", "duration_s": 900.0}) is True


# --------------------------------------------------------------- tests-6

MIGRATION_DIRS = [
    REPO / "broll" / "migrations",
    REPO / "broll" / "web" / "migrations",
    REPO / "broll" / "indexer" / "broll_index" / "migrations",
]
SCHEMAS = [REPO / "broll" / "schema.sql", REPO / "broll" / "web" / "schema.sql"]


def _sql_only(text: str) -> str:
    """The statements, without comments or blank lines.

    The bundled copies carry a five-line "kept in sync here" header, so a
    byte comparison fails on day one and would have to be disabled - which is
    how three copies of a schema stay unwatched (tests-6, 2026-09-18).
    """
    out = []
    for line in text.splitlines():
        line = re.sub(r"--.*$", "", line).strip()
        if line:
            out.append(line)
    return "\n".join(out)


def _digest(path: Path) -> str:
    return hashlib.sha256(
        _sql_only(path.read_text(encoding="utf-8")).encode("utf-8")).hexdigest()


def test_the_three_migration_copies_hold_the_same_sql():
    names = {p.name for d in MIGRATION_DIRS for p in d.glob("*.sql")}
    assert names, "no migrations found at all"
    for name in sorted(names):
        present = [d / name for d in MIGRATION_DIRS if (d / name).is_file()]
        assert len(present) == len(MIGRATION_DIRS), \
            f"{name} is missing from {[str(d) for d in MIGRATION_DIRS if not (d / name).is_file()]}"
        digests = {_digest(p) for p in present}
        assert len(digests) == 1, f"{name} has drifted between its copies"


def test_the_two_schema_copies_hold_the_same_sql():
    assert len({_digest(p) for p in SCHEMAS}) == 1, \
        "broll/schema.sql and broll/web/schema.sql have drifted"
