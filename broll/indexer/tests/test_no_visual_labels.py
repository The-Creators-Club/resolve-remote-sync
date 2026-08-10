"""Canonical labels for shots with no searchable visuals.

Their entire value is being EXACTLY matchable — an editor finds newsreader
cutaways with one term, and (more usefully) excludes them with one term. That
only works if the spelling is consistent, and the model does not reliably
comply: a real run produced both "newsreader" and "Newsreader" in the same clip.
Normalizing in code rather than trusting the prompt.
"""
from __future__ import annotations

import pytest

from broll_index.claude_client import (
    NO_VISUAL_LABELS,
    canonicalize_no_visual_label,
    validate_contract,
)


@pytest.mark.parametrize("label", NO_VISUAL_LABELS)
def test_canonical_labels_pass_through_unchanged(label):
    assert canonicalize_no_visual_label(label) == label


@pytest.mark.parametrize(
    "given,expected",
    [
        ("Newsreader", "newsreader"),          # seen in a real run
        ("NEWSREADER", "newsreader"),
        ("  newsreader  ", "newsreader"),
        ("newsreader.", "newsreader"),
        ("Black Frame", "black frame"),
        ("Colour Bars", "colour bars"),
        ("color bars", "colour bars"),          # US spelling
        ("test pattern", "colour bars"),
        ("news anchor", "newsreader"),
        ("talking head", "newsreader"),
        ("Ident", "station ident"),
    ],
)
def test_variants_normalize_to_the_canonical_label(given, expected):
    assert canonicalize_no_visual_label(given) == expected


@pytest.mark.parametrize(
    "description",
    [
        "Studio newsreader, city skyline background, inset window showing protest",
        "Elevated expressway, dashcam view, brake lights",
        "Harbour at dusk, fishing boats",
        "",
    ],
)
def test_real_descriptions_are_never_rewritten(description):
    """Only a bare label is canonicalized. A real description that merely mentions
    a newsreader must survive intact — the inset content is the searchable part."""
    assert canonicalize_no_visual_label(description) == description


def test_validate_contract_canonicalizes_descriptions():
    contract = {
        "themes": [],
        "category_hint": None,
        "quality_flags": [],
        "segments": [
            {
                "t_start": 0.0, "t_end": 4.0,
                "description": "Newsreader",
                "objects": ["newsreader", "news studio"],
                "setting": "studio", "motion": "static",
                "onscreen_text": "華視新聞", "onscreen_text_en": "CTS News",
            },
            {
                "t_start": 4.0, "t_end": 9.0,
                "description": "Harbour, fishing boats, overcast",
                "objects": ["harbour", "boats"],
                "setting": "harbour", "motion": "static",
                "onscreen_text": "", "onscreen_text_en": "",
            },
        ],
    }
    out = validate_contract(contract)
    assert out["segments"][0]["description"] == "newsreader"
    # A newsreader shot's chyron is often the best metadata in the clip — the
    # label must not cost us the text.
    assert out["segments"][0]["onscreen_text"] == "華視新聞"
    assert out["segments"][1]["description"] == "Harbour, fishing boats, overcast"
