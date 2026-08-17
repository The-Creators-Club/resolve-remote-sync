from __future__ import annotations

import json
from pathlib import Path

import pytest

from broll_index.claude_client import (
    MODEL_MAP,
    build_index_prompt,
    call_claude_with_retry,
    chunk_sheets,
    extract_claude_text,
    merge_index_results,
    parse_claude_response,
    validate_contract,
)

VALID_CONTRACT = {
    "themes": ["naval exercise", "harbor"],
    "category_hint": "military/naval",
    "quality_flags": ["shaky"],
    "segments": [
        {
            "t_start": 0.0,
            "t_end": 8.5,
            "description": "Grey navy frigate moored at a pier",
            "objects": ["navy ship", "warship", "frigate"],
            "setting": "harbor, overcast daylight",
            "motion": "slow pan left",
        }
    ],
}


def _cli_envelope(payload_text: str) -> str:
    return json.dumps({"type": "result", "result": payload_text})


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

def test_extract_claude_text_unwraps_cli_envelope():
    raw = _cli_envelope("hello world")
    assert extract_claude_text(raw) == "hello world"


def test_extract_claude_text_passthrough_on_non_json():
    assert extract_claude_text("not json at all") == "not json at all"


def _with_default_onscreen_text(contract: dict) -> dict:
    """VALID_CONTRACT's segments have no onscreen_text/onscreen_text_en keys; validation
    defaults them to "" (see test_validate_contract_defaults_missing_onscreen_text_to_empty_string),
    so a round trip through parse_claude_response always adds them.
    """
    return {
        **contract,
        "segments": [{**seg, "onscreen_text": "", "onscreen_text_en": ""} for seg in contract["segments"]],
    }


def test_parse_claude_response_valid_contract():
    raw = _cli_envelope(json.dumps(VALID_CONTRACT))
    parsed = parse_claude_response(raw)
    assert parsed == _with_default_onscreen_text(VALID_CONTRACT)


def test_parse_claude_response_accepts_bare_contract_json():
    # useful for tests/mocks that skip the CLI envelope entirely
    raw = json.dumps(VALID_CONTRACT)
    assert parse_claude_response(raw) == _with_default_onscreen_text(VALID_CONTRACT)


def test_parse_claude_response_rejects_invalid_json():
    raw = _cli_envelope("this is { not valid json")
    with pytest.raises(ValueError):
        parse_claude_response(raw)


# ---------------------------------------------------------------------------
# trailing/leading prose around the contract
#
# `json.loads` is all-or-nothing, so a good object followed by a sentence of
# commentary raised "Extra data" and the whole call was discarded. On 2026-08-07
# that was 32 of 33 lost clips — a paid call plus its retry each, thrown away
# over text the contract never reads.
# ---------------------------------------------------------------------------

def test_parse_claude_response_ignores_trailing_prose():
    raw = _cli_envelope(json.dumps(VALID_CONTRACT) + "\n\nI hope this helps!")
    assert parse_claude_response(raw) == _with_default_onscreen_text(VALID_CONTRACT)


def test_parse_claude_response_ignores_trailing_second_object():
    """The exact shape of the real failure: "Extra data: line 18 column 1"."""
    raw = _cli_envelope(json.dumps(VALID_CONTRACT) + "\n" + json.dumps({"note": "extra"}))
    assert parse_claude_response(raw) == _with_default_onscreen_text(VALID_CONTRACT)


def test_parse_claude_response_ignores_leading_prose():
    raw = _cli_envelope("Here is the analysis:\n" + json.dumps(VALID_CONTRACT))
    assert parse_claude_response(raw) == _with_default_onscreen_text(VALID_CONTRACT)


def test_parse_claude_response_still_rejects_a_truncated_object():
    """Forgive padding, not a different answer: a cut-off object is unusable."""
    raw = _cli_envelope(json.dumps(VALID_CONTRACT)[:-20])
    with pytest.raises(ValueError):
        parse_claude_response(raw)


def test_parse_claude_response_still_rejects_prose_with_no_object():
    with pytest.raises(ValueError):
        parse_claude_response(_cli_envelope("I could not analyse these images."))


def test_parse_claude_response_still_validates_the_contract():
    """Recovering the object must not bypass validation."""
    raw = _cli_envelope(json.dumps({"themes": []}) + "\ntrailing")
    with pytest.raises(ValueError, match="missing keys"):
        parse_claude_response(raw)


def test_validate_contract_rejects_missing_keys():
    bad = {"themes": [], "segments": []}
    with pytest.raises(ValueError, match="missing keys"):
        validate_contract(bad)


def test_validate_contract_drops_unknown_quality_flags():
    """Unknown flags are dropped, not fatal.

    This used to raise. On the real archive a model returned 'pixelated' and
    the whole clip's index was discarded AFTER its contact-sheet calls were
    paid for — a far worse outcome than losing one advisory tag. The schema's
    CHECK constraint would reject the unknown value at write time anyway.
    """
    out = validate_contract({**VALID_CONTRACT, "quality_flags": ["blurry_cam", "shaky"]})
    assert out["quality_flags"] == ["shaky"]

    # every flag unknown -> empty list, still not an error
    out = validate_contract({**VALID_CONTRACT, "quality_flags": ["blurry_cam"]})
    assert out["quality_flags"] == []


def test_validate_contract_rejects_segment_missing_fields():
    bad = {**VALID_CONTRACT, "segments": [{"t_start": 0.0, "t_end": 1.0}]}
    with pytest.raises(ValueError, match="segment 0 missing"):
        validate_contract(bad)


# ---------------------------------------------------------------------------
# v2 contract: onscreen_text / onscreen_text_en
# ---------------------------------------------------------------------------

def test_validate_contract_accepts_segments_with_onscreen_text():
    contract = {
        **VALID_CONTRACT,
        "segments": [
            {
                **VALID_CONTRACT["segments"][0],
                "onscreen_text": "華視新聞 | 警匪激烈槍戰 惡龍中彈落網",
                "onscreen_text_en": "CTS News | Fierce police shootout, suspect 'Evil Dragon' captured",
            }
        ],
    }
    validated = validate_contract(contract)
    seg = validated["segments"][0]
    assert seg["onscreen_text"] == "華視新聞 | 警匪激烈槍戰 惡龍中彈落網"
    assert seg["onscreen_text_en"] == "CTS News | Fierce police shootout, suspect 'Evil Dragon' captured"


def test_validate_contract_defaults_missing_onscreen_text_to_empty_string():
    # Missing onscreen_text/onscreen_text_en must NOT fail the segment (and burn the
    # whole clip's retry + token spend) — they default to "".
    validated = validate_contract(VALID_CONTRACT)  # VALID_CONTRACT has no onscreen_text keys
    seg = validated["segments"][0]
    assert seg["onscreen_text"] == ""
    assert seg["onscreen_text_en"] == ""


def test_validate_contract_coerces_non_string_onscreen_text_to_empty_string():
    contract = {
        **VALID_CONTRACT,
        "segments": [{**VALID_CONTRACT["segments"][0], "onscreen_text": None, "onscreen_text_en": 42}],
    }
    validated = validate_contract(contract)
    seg = validated["segments"][0]
    assert seg["onscreen_text"] == ""
    assert seg["onscreen_text_en"] == ""


def test_validate_contract_joins_list_valued_onscreen_text():
    # Some models return a list of strings (one per piece of on-screen text) despite the
    # prompt asking for a single " | "-joined string.
    contract = {
        **VALID_CONTRACT,
        "segments": [
            {
                **VALID_CONTRACT["segments"][0],
                "onscreen_text": ["華視新聞", "警匪激烈槍戰 惡龍中彈落網"],
                "onscreen_text_en": ["CTS News", "Fierce police shootout"],
            }
        ],
    }
    validated = validate_contract(contract)
    seg = validated["segments"][0]
    assert seg["onscreen_text"] == "華視新聞 | 警匪激烈槍戰 惡龍中彈落網"
    assert seg["onscreen_text_en"] == "CTS News | Fierce police shootout"


# ---------------------------------------------------------------------------
# retry logic (mock the subprocess boundary)
# ---------------------------------------------------------------------------

def test_call_claude_with_retry_succeeds_first_try():
    calls = []

    def fake_invoke(prompt, model):
        calls.append(model)
        return json.dumps(VALID_CONTRACT)

    result, usage = call_claude_with_retry("prompt", "sonnet", invoke=fake_invoke)
    assert result == _with_default_onscreen_text(VALID_CONTRACT)
    assert calls == ["sonnet"]
    assert usage == {}  # bare payload, no CLI envelope -> no accounting


def test_call_claude_with_retry_invalid_then_valid():
    responses = iter(["not json", json.dumps(VALID_CONTRACT)])

    def fake_invoke(prompt, model):
        return next(responses)

    result, _ = call_claude_with_retry("prompt", "sonnet", invoke=fake_invoke)
    assert result == _with_default_onscreen_text(VALID_CONTRACT)


def test_usage_is_extracted_from_the_cli_envelope():
    from broll_index.claude_client import extract_usage

    envelope = json.dumps(
        {
            "type": "result",
            "result": json.dumps(VALID_CONTRACT),
            "total_cost_usd": 0.0117,
            "duration_ms": 2043,
            "usage": {
                "input_tokens": 10,
                "cache_creation_input_tokens": 6893,
                "cache_read_input_tokens": 21545,
                "output_tokens": 61,
            },
        }
    )

    contract, usage = call_claude_with_retry("prompt", "haiku", invoke=lambda p, m: envelope)

    assert contract == _with_default_onscreen_text(VALID_CONTRACT)
    assert usage["cache_read_input_tokens"] == 21545
    assert usage["total_cost_usd"] == 0.0117


def test_usage_extraction_never_raises_on_bare_or_junk_output():
    from broll_index.claude_client import extract_usage

    assert extract_usage("not json at all") == {}
    assert extract_usage(json.dumps([1, 2, 3])) == {}
    # A bare contract carries no accounting; that must not be logged as a
    # real zero-token call, which would skew cost-per-clip-minute downward.
    assert extract_usage(json.dumps(VALID_CONTRACT)) == {}


def test_call_claude_with_retry_gives_up_after_one_retry():
    call_count = {"n": 0}

    def fake_invoke(prompt, model):
        call_count["n"] += 1
        return "still not json"

    with pytest.raises(ValueError, match="invalid JSON after one retry"):
        call_claude_with_retry("prompt", "sonnet", invoke=fake_invoke)
    assert call_count["n"] == 2  # exactly one retry, no more


def test_model_aliases_resolve_to_current_api_model_ids():
    """The aliases are what an operator types; these are what the API answers to.
    Bare ids (no date suffix) — a date-suffixed variant 404s (2026-08-17)."""
    assert MODEL_MAP == {
        "haiku": "claude-haiku-4-5",
        "sonnet": "claude-sonnet-5",
        "opus": "claude-opus-5",
        "fable": "claude-fable-5",
    }


def test_an_unmapped_model_is_passed_through_so_a_config_can_pin_one():
    from broll_index.claude_client import resolve_model

    assert resolve_model("claude-sonnet-4-6") == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# prompt building
# ---------------------------------------------------------------------------

def test_build_index_prompt_injects_sheet_paths_and_taxonomy():
    sheet = Path("sheet_0001.jpg").resolve()
    prompt = build_index_prompt([sheet], ["military/naval", "nature/wildlife"])
    assert "sheet_0001.jpg" in prompt
    assert "military/naval" in prompt
    assert "nature/wildlife" in prompt
    assert "shaky" in prompt  # fixed quality-flag vocabulary present
    assert "synonym" in prompt.lower() or "hypernym" in prompt.lower()
    assert "STRICT JSON" in prompt


def test_build_index_prompt_empty_taxonomy():
    prompt = build_index_prompt([Path("/tmp/s.jpg")], [])
    assert "no taxonomy defined yet" in prompt


def test_build_index_prompt_loads_the_current_template():
    """Guard against silently reverting to an older prompt.

    Each version fixed a measured failure, so a revert loses real quality:
    v2 added on-screen text capture; v3 added the describe-don't-narrate rule
    after brake lights were indexed as "emergency response ... responding to an
    incident ahead", which made that clip the top hit for "emergency vehicle";
    v4 made descriptions terse noun phrases rather than prose; v5 labels
    no-visual shots (newsreader, title card) and stops road-infrastructure lamps
    being read as emergency vehicles; v6 requires one segment per distinct shot
    after a measured batch averaged 2.1 segments per 48-second clip, collapsing
    visibly different cells into broad summaries an editor cannot jump to.
    """
    from broll_index import claude_client

    assert claude_client._PROMPT_TEMPLATE_PATH.name == "index_clip_v6.md"
    prompt = build_index_prompt([Path("/tmp/s.jpg")], [])

    # v2 behaviour still present
    assert "onscreen_text" in prompt
    assert "onscreen_text_en" in prompt
    assert "on-screen" in prompt.lower()

    # v3 behaviour
    assert "brake lights" in prompt.lower()
    assert "not sentences" in prompt.lower()  # v4: terse noun phrases, not prose
    assert "do not infer" in prompt.lower() or "do not narrate" in prompt.lower()

    # v6: split per shot rather than summarising a whole contact sheet
    assert "one segment per distinct shot" in prompt.lower()
    assert "when in doubt, split" in prompt.lower()
    # Hedging must remain explicitly allowed — it is honest, not a defect. Checked
    # by intent rather than exact phrasing so a prompt reword doesn't fail here
    # spuriously; what matters is that uncertainty is still sanctioned somewhere.
    lowered = prompt.lower()
    assert "uncertainty is fine" in lowered
    assert any(h in lowered for h in ("possibly", "apparently", "appears to be"))


# ---------------------------------------------------------------------------
# windowing / merge (36 frames == 4 sheets per call)
# ---------------------------------------------------------------------------

def test_chunk_sheets_groups_into_windows_of_four():
    sheets = [Path(f"sheet_{i:04d}.jpg") for i in range(1, 11)]  # 10 sheets = 90 frames
    chunks = chunk_sheets(sheets, sheets_per_call=4)
    assert [len(c) for c in chunks] == [4, 4, 2]
    assert chunks[0] == sheets[0:4]
    assert chunks[-1] == sheets[8:10]


def test_chunk_sheets_default_is_four_sheets_36_frames():
    sheets = [Path(f"sheet_{i:04d}.jpg") for i in range(1, 5)]
    chunks = chunk_sheets(sheets)
    assert chunks == [sheets]  # exactly one window of 4 sheets == 36 frames


def test_chunk_sheets_rejects_invalid_size():
    with pytest.raises(ValueError):
        chunk_sheets([Path("a.jpg")], sheets_per_call=0)


def test_merge_index_results_unions_themes_and_flags_concats_segments():
    window_a = {
        "themes": ["harbor", "overcast"],
        "quality_flags": ["shaky"],
        "category_hint": None,
        "segments": [{"t_start": 0.0, "t_end": 8.0, "description": "a", "objects": [], "setting": "", "motion": ""}],
    }
    window_b = {
        "themes": ["overcast", "naval exercise"],
        "quality_flags": ["shaky", "noisy"],
        "category_hint": "military/naval",
        "segments": [{"t_start": 8.0, "t_end": 16.0, "description": "b", "objects": [], "setting": "", "motion": ""}],
    }
    merged = merge_index_results([window_a, window_b])

    assert merged["themes"] == ["harbor", "overcast", "naval exercise"]  # de-duped, order preserved
    assert merged["quality_flags"] == ["shaky", "noisy"]
    assert merged["category_hint"] == "military/naval"  # first non-null wins
    assert len(merged["segments"]) == 2
    assert merged["segments"][0]["t_start"] == 0.0
    assert merged["segments"][1]["t_start"] == 8.0


def test_merge_index_results_first_non_null_category_hint():
    a = {"themes": [], "quality_flags": [], "category_hint": "cat/a", "segments": []}
    b = {"themes": [], "quality_flags": [], "category_hint": "cat/b", "segments": []}
    merged = merge_index_results([a, b])
    assert merged["category_hint"] == "cat/a"


def test_merge_index_results_empty_list():
    merged = merge_index_results([])
    assert merged == {"themes": [], "quality_flags": [], "category_hint": None, "segments": []}


def test_merge_index_results_preserves_onscreen_text_across_windows():
    window_a = {
        "themes": [],
        "quality_flags": [],
        "category_hint": None,
        "segments": [
            {
                "t_start": 0.0, "t_end": 8.0, "description": "a", "objects": [], "setting": "", "motion": "",
                "onscreen_text": "華視新聞", "onscreen_text_en": "CTS News",
            }
        ],
    }
    window_b = {
        "themes": [],
        "quality_flags": [],
        "category_hint": None,
        "segments": [
            {
                "t_start": 8.0, "t_end": 16.0, "description": "b", "objects": [], "setting": "", "motion": "",
                "onscreen_text": "", "onscreen_text_en": "",
            }
        ],
    }
    merged = merge_index_results([window_a, window_b])
    assert merged["segments"][0]["onscreen_text"] == "華視新聞"
    assert merged["segments"][0]["onscreen_text_en"] == "CTS News"
    assert merged["segments"][1]["onscreen_text"] == ""
    assert merged["segments"][1]["onscreen_text_en"] == ""


# ---------------------------------------------------------------------------
# orchestrator additions: fence-stripping fallback
# ---------------------------------------------------------------------------

def test_parse_strips_markdown_fences() -> None:
    fenced = "```json\n" + json.dumps(VALID_CONTRACT) + "\n```"
    assert parse_claude_response(fenced) == _with_default_onscreen_text(VALID_CONTRACT)


def test_parse_strips_fences_inside_cli_envelope() -> None:
    fenced = "```\n" + json.dumps(VALID_CONTRACT) + "\n```"
    assert parse_claude_response(_cli_envelope(fenced)) == _with_default_onscreen_text(VALID_CONTRACT)


def test_no_module_shells_out_to_the_claude_cli():
    """2026-08-17, COMMERCIAL_READINESS.md item 1. The old test here pinned the
    `--disallowedTools` argv of `claude -p`, which existed to strip tool
    definitions out of every call's system prompt (measured 66,576 -> 45,590
    input tokens). The API sends no tool definitions at all, so that saving is
    now structural. What must not come back is the CLI: a customer install has
    no `claude` binary and no claude.ai login, so any subprocess call here would
    fail on their machine and nowhere on ours.
    """
    from pathlib import Path

    from broll_index import claude_client

    source = Path(claude_client.__file__).read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "claude\", \"-p\"" not in source
    # And nothing else in the package may invoke the binary either.
    pkg = Path(claude_client.__file__).parent
    for py in pkg.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "claude\", \"-p\"" not in text, py
        assert "\"claude\", \"--\"" not in text, py
