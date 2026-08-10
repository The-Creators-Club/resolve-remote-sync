"""Reject hallucinated transcripts before they reach the index.

Whisper fed near-silence or steady noise does not return nothing — it emits
plausible-looking text drawn from its training data. Measured on the FF2 corpus:
both long dashcam recordings (road noise, no speech) produced garbage, while the
15 clips with real speech were clean.

  video 13 (38 min dashcam) -> "字幕志愿者 李宗盛" x6   (subtitle-credit artifact)
  video 12 (22 min dashcam) -> "Não sei se"            (wrong language entirely)

Unfiltered, that footage becomes findable under a famous singer's name, or under
stray Portuguese. Bad search results are worse than absent ones: an editor who
gets nothing searches differently, while an editor who gets a confidently wrong
hit wastes time and loses trust in the tool.

The heuristics below are deliberately conservative — they reject whole
transcripts only on strong evidence, because discarding a real transcript costs
more than letting a marginal one through.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

# Artifacts Whisper emits on silence: subtitle credits, channel sign-offs, and
# fansub boilerplate that appear verbatim in its training data.
KNOWN_ARTIFACTS = (
    "字幕志愿者", "字幕志願者", "字幕由", "请不吝点赞", "請不吝點贊",
    "订阅", "訂閱", "打赏", "打賞", "转载请注明", "轉載請註明",
    "明镜与点点栏目", "amara.org", "subtitles by", "subtitled by",
    "thanks for watching", "thank you for watching", "please subscribe",
)


@dataclass(frozen=True)
class QualityVerdict:
    ok: bool
    reason: str

    def __bool__(self) -> bool:
        return self.ok


def contains_known_artifact(text: str) -> str | None:
    """Return the matched artifact, or None. Case-insensitive for latin text."""
    lowered = text.lower()
    for artifact in KNOWN_ARTIFACTS:
        if artifact in text or artifact.lower() in lowered:
            return artifact
    return None


def assess(
    texts: list[str],
    *,
    duration_s: float | None = None,
    # Calibrated for CJK, which is far denser than latin script: "警方展開了第一
    # 波攻堅行動 雙方爆發了激烈的槍戰" is two full sentences in 23 characters, so an
    # English-tuned floor (~24) would discard real transcripts. 12 still rejects
    # the observed "Não sei se" hallucination (10 chars).
    min_chars: int = 12,
    repetition_share: float = 0.6,
    min_lines_for_repetition: float = 3,
    min_chars_per_minute: float = 8.0,
) -> QualityVerdict:
    """Decide whether a transcript is trustworthy enough to index.

    Rejects on:
      - a known hallucination artifact anywhere in the text
      - near-total repetition (one line dominating a multi-line transcript)
      - too little total content to be meaningful
      - implausibly sparse output for the clip's duration (a 38-minute file
        yielding one sentence is noise, not speech)
    """
    lines = [t.strip() for t in texts if t and t.strip()]
    if not lines:
        return QualityVerdict(False, "empty transcript (no speech detected)")

    joined = " ".join(lines)

    artifact = contains_known_artifact(joined)
    if artifact:
        return QualityVerdict(False, f"hallucination artifact present: {artifact!r}")

    counts = Counter(lines)
    top_line, top_n = counts.most_common(1)[0]
    if len(lines) >= min_lines_for_repetition and top_n / len(lines) >= repetition_share:
        return QualityVerdict(
            False, f"repetition loop: {top_n}/{len(lines)} lines are {top_line[:30]!r}"
        )

    if len(joined) < min_chars:
        return QualityVerdict(False, f"too little content ({len(joined)} chars)")

    if duration_s and duration_s > 120:
        # Only applied to longer clips: a 20-second clip with one line is fine,
        # a 38-minute one is not.
        per_minute = len(joined) / (duration_s / 60)
        if per_minute < min_chars_per_minute:
            return QualityVerdict(
                False,
                f"implausibly sparse for {duration_s/60:.0f} min "
                f"({per_minute:.1f} chars/min) — likely noise, not speech",
            )

    return QualityVerdict(True, "ok")


def drop_artifact_lines(texts: list[str]) -> list[str]:
    """Remove individual artifact lines from an otherwise-good transcript.

    Whisper sometimes appends a sign-off artifact to a real transcript; that
    should cost the stray line, not the whole clip.
    """
    return [t for t in texts if not contains_known_artifact(t)]
