"""Cases taken from the real FF2 transcription run — see transcript_quality.py."""
from __future__ import annotations

from broll_index.transcript_quality import (
    assess,
    contains_known_artifact,
    drop_artifact_lines,
)

# Real output: 38-minute dashcam recording with no speech.
VIDEO_13 = ["字幕志愿者 李宗盛"] * 6
# Real output: 22-minute dashcam, hallucinated in the wrong language entirely.
VIDEO_12 = ["Não sei se"]
# Real output: Mandarin news package with genuine speech.
VIDEO_3 = [
    "清晨九點半",
    "警方展開了第一波攻堅行動",
    "行政局長侯友宜親自在現場坐鎮指揮",
    "雙方爆發了激烈的槍戰",
    "張啟民身中十多槍",
]


def test_rejects_subtitle_credit_hallucination():
    v = assess(VIDEO_13, duration_s=2316.0)
    assert not v
    assert "artifact" in v.reason


def test_rejects_wrong_language_sparse_hallucination():
    v = assess(VIDEO_12, duration_s=1350.0)
    assert not v
    # caught by either the length or the sparsity rule; both are correct
    assert "too little content" in v.reason or "sparse" in v.reason


def test_accepts_genuine_transcript():
    v = assess(VIDEO_3, duration_s=73.5)
    assert v
    assert v.reason == "ok"


def test_accepts_long_rich_transcript():
    texts = [f"這是第{i}句話，內容各不相同。" for i in range(200)]
    assert assess(texts, duration_s=1524.0)


def test_rejects_empty():
    assert not assess([])
    assert not assess(["", "   "])


def test_rejects_repetition_loop_without_known_artifact():
    # A repeated line that isn't in the blocklist must still be caught.
    v = assess(["謝謝觀看"] * 10, duration_s=600.0)
    assert not v
    assert "repetition" in v.reason


def test_sparsity_rule_does_not_punish_short_clips():
    # One line in a 20s clip is plausible; the sparsity rule must not fire.
    v = assess(["向左右兩側 一遙救護 謝謝 請向右下"], duration_s=20.0)
    assert v


def test_sparsity_rule_fires_on_long_clips():
    v = assess(["一句話而已，這麼長的片子只有這句。"], duration_s=2316.0)
    assert not v
    assert "sparse" in v.reason


def test_artifact_detection_is_case_insensitive_for_latin():
    assert contains_known_artifact("Subtitles By someone")
    assert contains_known_artifact("THANKS FOR WATCHING")
    assert contains_known_artifact("字幕志愿者 李宗盛")
    assert contains_known_artifact("警方展開了第一波攻堅行動") is None


def test_drop_artifact_lines_keeps_real_content():
    mixed = ["警方展開了第一波攻堅行動", "字幕志愿者 李宗盛", "雙方爆發了激烈的槍戰"]
    kept = drop_artifact_lines(mixed)
    assert kept == ["警方展開了第一波攻堅行動", "雙方爆發了激烈的槍戰"]
    # and the cleaned transcript should then pass
    assert assess(kept, duration_s=73.5)
