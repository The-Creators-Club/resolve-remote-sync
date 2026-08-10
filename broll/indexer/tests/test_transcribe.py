from __future__ import annotations

from pathlib import Path

import pytest

from broll_index.transcribe import (
    TranscriptCue,
    merge_cues,
    parse_srt,
    transcribe_file,
)

# Shape taken from real faster-whisper output on a Mandarin news clip.
SRT = """1
00:00:00,000 --> 00:00:02,480
清晨九點半

2
00:00:02,480 --> 00:00:05,120
警方展開了第一波攻堅行動

3
00:00:12,000 --> 00:00:15,300
行政局長侯友宜親自在現場
坐鎮指揮
"""


def test_parse_srt_basic():
    cues = parse_srt(SRT)
    assert len(cues) == 3
    assert cues[0].t_start == 0.0
    assert cues[0].t_end == pytest.approx(2.48)
    assert cues[0].text == "清晨九點半"


def test_parse_srt_joins_multiline_cue_text():
    cues = parse_srt(SRT)
    assert cues[2].text == "行政局長侯友宜親自在現場 坐鎮指揮"


def test_parse_srt_tolerates_bom_crlf_and_no_trailing_newline():
    content = "﻿" + SRT.replace("\n", "\r\n").rstrip()
    cues = parse_srt(content)
    assert len(cues) == 3
    assert cues[0].text == "清晨九點半"


def test_parse_srt_handles_dot_millisecond_separator():
    cues = parse_srt("1\n00:00:01.500 --> 00:00:02.750\nhello\n")
    assert cues[0].t_start == pytest.approx(1.5)
    assert cues[0].t_end == pytest.approx(2.75)


def test_parse_srt_empty_and_garbage_are_safe():
    assert parse_srt("") == []
    assert parse_srt("not an srt at all") == []
    # a cue with a timestamp but no text is dropped rather than stored blank
    assert parse_srt("1\n00:00:01,000 --> 00:00:02,000\n\n") == []


# ---------------------------------------------------------------------------
# merging
# ---------------------------------------------------------------------------

def test_merge_joins_adjacent_cues_and_breaks_on_a_real_pause():
    merged = merge_cues(parse_srt(SRT), max_gap_s=1.0)
    # cues 1+2 are adjacent (gap 0) -> joined; cue 3 is 6.9s later -> separate
    assert len(merged) == 2
    assert merged[0].text == "清晨九點半 警方展開了第一波攻堅行動"
    assert merged[0].t_start == 0.0
    assert merged[0].t_end == pytest.approx(5.12)
    assert merged[1].text.startswith("行政局長侯友宜")


def test_merge_respects_max_duration():
    cues = [TranscriptCue(i * 2.0, i * 2.0 + 2.0, f"line{i}") for i in range(20)]
    merged = merge_cues(cues, max_gap_s=1.0, max_duration_s=10.0)
    assert len(merged) > 1
    assert all(c.t_end - c.t_start <= 10.0 for c in merged)


def test_merge_empty():
    assert merge_cues([]) == []


# ---------------------------------------------------------------------------
# subprocess boundary is mocked — never invoke real whisper in tests
# ---------------------------------------------------------------------------

def test_transcribe_file_parses_and_merges_runner_output(tmp_path: Path):
    srt_path = tmp_path / "clip.srt"
    srt_path.write_text(SRT, encoding="utf-8")

    calls = []

    def fake_runner(src, out_dir, python_exe, script, model, language):
        calls.append({"src": src, "model": model, "language": language})
        return srt_path

    cues = transcribe_file(
        tmp_path / "clip.mp4", tmp_path, "py.exe", "transcribe.py",
        language="zh", runner=fake_runner,
    )

    assert calls[0]["language"] == "zh"
    assert calls[0]["model"] == "large-v3-turbo"
    assert len(cues) == 2
    assert "侯友宜" in cues[1].text
