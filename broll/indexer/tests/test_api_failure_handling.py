"""Regressions from the real FF2 run, where an exhausted API credit balance
marked five videos permanently 'error' while reporting an unrelated warning.
"""
from __future__ import annotations

import json

import pytest

from broll_index.claude_client import (
    ClaudeCallError,
    _describe_cli_failure,
    _envelope_error,
    invoke_claude,
    is_fatal_api_error,
)

# Verbatim stderr from the run: a warning with nothing to do with the failure.
REAL_STDERR = (
    "⚠ claude.ai connectors are disabled because ANTHROPIC_API_KEY or another auth "
    "source is set and takes precedence over your claude.ai login · Unset it to load "
    "your organization's connectors"
)
# The actual cause, which lived in stdout.
REAL_STDOUT = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "api_error_status": 400,
        "result": "Credit balance is too low",
    }
)


def test_the_real_error_is_reported_not_the_warning():
    described = _describe_cli_failure(REAL_STDOUT, REAL_STDERR)
    assert "Credit balance is too low" in described
    assert "400" in described


def test_envelope_error_ignores_successful_responses():
    ok = json.dumps({"type": "result", "is_error": False, "result": "{}"})
    assert _envelope_error(ok) is None
    assert _envelope_error("not json") is None
    assert _envelope_error("") is None


def test_zero_exit_with_is_error_still_raises(monkeypatch):
    """The CLI can report an API failure while exiting 0 — that is not success."""
    class FakeResult:
        returncode = 0
        stdout = REAL_STDOUT
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *a, **k: FakeResult())
    with pytest.raises(ClaudeCallError, match="Credit balance"):
        invoke_claude("prompt", "haiku")


def test_fallback_when_stdout_has_no_envelope():
    assert "boom" in _describe_cli_failure("", "boom")
    assert _describe_cli_failure("", "") == "no output"


@pytest.mark.parametrize(
    "message",
    [
        "API error 400: Credit balance is too low",
        "authentication_error: invalid x-api-key",
        "Invalid API key provided",
        "permission_error: account is not authorized",
    ],
)
def test_environmental_failures_are_fatal(message):
    assert is_fatal_api_error(message)


@pytest.mark.parametrize(
    "message",
    [
        "claude response is not valid JSON",
        "segment 0 missing keys: ['objects']",
        "no contact sheets found — run the 'frames' stage first",
    ],
)
def test_per_video_failures_are_not_fatal(message):
    """These are about ONE clip: mark it and carry on with the rest."""
    assert not is_fatal_api_error(message)


# Hit for real on the subscription mid-session:
#   "API error 429: You've hit your session limit · resets 10:10pm (Asia/Taipei)"
# A rate limit is account-wide, so every remaining video would fail identically.
# Marking each one 'error' would poison a whole archive queue over a limit that
# clears in an hour — it must stop the run instead, leaving the queue resumable.
@pytest.mark.parametrize(
    "message",
    [
        "API error 429: You've hit your session limit · resets 10:10pm (Asia/Taipei)",
        "rate_limit_error: too many requests",
        "usage limit reached",
        "quota exceeded",
    ],
)
def test_rate_limits_stop_the_run_rather_than_failing_each_video(message):
    from broll_index.claude_client import is_rate_limited

    assert is_rate_limited(message)
    assert is_fatal_api_error(message)


def test_reset_hint_is_extracted_for_the_operator():
    from broll_index.claude_client import extract_reset_hint

    msg = "API error 429: You've hit your session limit · resets 10:10pm (Asia/Taipei)"
    assert extract_reset_hint(msg) == "resets 10:10pm (Asia/Taipei)".replace("resets ", "")
    assert extract_reset_hint("something else entirely") is None


def test_rate_limit_via_nonzero_exit_aborts_the_run(tmp_path, schema_path, monkeypatch):
    """A 429 arrives two ways and BOTH must abort the run.

    Real failure: `_process_video` required isinstance(e, ClaudeCallError), but a
    non-zero CLI exit raises a plain RuntimeError. A session limit delivered that
    way slipped past the guard and marked 1,097 videos 'error' in one night —
    exactly what FatalRunError exists to prevent. Match on the message, not the
    exception class.
    """
    from broll_index import pipeline
    from broll_index.pipeline import FatalRunError, _process_video
    from broll_index.storage.sqlite_backend import SqliteBackend

    db = SqliteBackend(tmp_path / "b.db", schema_path=schema_path)
    vid = db.upsert_video("s", "clip.mp4", status="proxied", duration_s=10.0)

    def boom(*a, **kw):
        # plain RuntimeError, as invoke_claude raises on a non-zero exit
        raise RuntimeError(
            "claude exited 1: API error 429: You've hit your session limit "
            "· resets 3:50am (Asia/Taipei)"
        )

    monkeypatch.setattr(pipeline, "stage_claude", boom)

    cfg = type("C", (), {"shares": {"s": type("S", (), {"root": str(tmp_path)})()},
                         "data_root": tmp_path})()

    try:
        _process_video(cfg, db, db.get_video(vid), model="haiku",
                       requested_stages={"claude"})
        raised = False
    except FatalRunError:
        raised = True

    assert raised, "a 429 by non-zero exit must raise FatalRunError"
    # and crucially the video must NOT be marked failed
    assert db.get_video(vid)["status"] == "proxied"


def test_unknown_quality_flag_is_dropped_not_fatal():
    """A model inventing a flag outside the vocabulary ('pixelated' on the real
    archive) must not discard the whole clip's index after its calls are paid
    for — drop the tag, keep the video."""
    from broll_index.claude_client import validate_contract

    out = validate_contract({
        "themes": [], "category_hint": None,
        "quality_flags": ["noisy", "pixelated", "shaky"],
        "segments": [{"t_start": 0.0, "t_end": 1.0, "description": "x",
                      "objects": [], "setting": "", "motion": ""}],
    })
    assert out["quality_flags"] == ["noisy", "shaky"]
