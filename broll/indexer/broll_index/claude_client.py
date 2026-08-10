"""Claude Code headless (`claude -p`) invocation, JSON contract parsing, prompt building,
and frame-window merging.

`invoke_claude` is the single isolated subprocess boundary per SPEC's requirement that it
be "easy to mock" — every other function here is pure and takes/returns plain data so it's
trivially testable without a real `claude` binary.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

MODEL_MAP = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-5",
    "fable": "claude-fable-5",
}

QUALITY_FLAG_VOCAB = {"shaky", "soft_focus", "overexposed", "underexposed", "noisy", "rolling_shutter"}

# Everything except Read, which the prompt needs to open the contact sheets.
# Tool definitions are part of the system prompt on every call, so dropping the
# unused ones is a direct token saving — measured 32% off each call.
DISALLOWED_TOOLS = ",".join([
    "Bash", "BashOutput", "KillShell", "Edit", "Write", "NotebookEdit",
    "Glob", "Grep", "WebFetch", "WebSearch", "Task", "TodoWrite",
    "SlashCommand", "ExitPlanMode", "AskUserQuestion", "Artifact",
    "ListMcpResourcesTool", "ReadMcpResourceTool",
])

# Canonical labels for shots with no searchable visual content (see the prompt's
# "Shots with no usable visuals" section). Their whole value is being exactly
# matchable — so an editor can find newsreader cutaways, and more usefully
# exclude them — which only works if the spelling is consistent. The model
# varies capitalization ("newsreader" vs "Newsreader") and occasionally
# punctuates, so normalize here rather than relying on it to comply.
NO_VISUAL_LABELS = ("newsreader", "title card", "black frame", "colour bars", "station ident")

# Tolerated variants that mean the same shot, mapped to the canonical label.
_LABEL_ALIASES = {
    "news reader": "newsreader",
    "news anchor": "newsreader",
    "anchor": "newsreader",
    "presenter": "newsreader",
    "talking head": "newsreader",
    "color bars": "colour bars",
    "test pattern": "colour bars",
    "titles": "title card",
    "title cards": "title card",
    "blank frame": "black frame",
    "channel ident": "station ident",
    "ident": "station ident",
}


def canonicalize_no_visual_label(description: str) -> str:
    """Return the canonical label if `description` is one, else the input unchanged."""
    stripped = (description or "").strip().strip(".").strip()
    key = stripped.lower()
    if key in NO_VISUAL_LABELS:
        return key
    return _LABEL_ALIASES.get(key, description)

# v2 contract: on-screen text capture (see SPEC.md "Claude indexing output contract" and
# docs/indexing-findings.md). index_clip.md (v1) is kept on disk for reference only — it
# is not loaded by build_index_prompt.
_PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "index_clip_v6.md"

InvokeFn = Callable[[str, str], str]


# ---------------------------------------------------------------------------
# subprocess boundary
# ---------------------------------------------------------------------------

def describe_auth(use_subscription: bool) -> str:
    """One line stating what will actually be billed, for the run banner.

    Worth surfacing loudly: the only signal that API credit is being spent
    instead of the subscription is a single stderr warning that is easy to miss,
    and the difference is invisible until the credit runs out mid-run.
    """
    import os

    key_present = "ANTHROPIC_API_KEY" in os.environ
    if use_subscription and key_present:
        return ("auth: Claude Code subscription (ANTHROPIC_API_KEY found in the "
                "environment and dropped for the claude subprocess)")
    if use_subscription:
        return "auth: Claude Code subscription (no ANTHROPIC_API_KEY set)"
    if key_present:
        return "auth: ANTHROPIC_API_KEY — billing pay-as-you-go API credit, NOT the subscription"
    return "auth: no ANTHROPIC_API_KEY set and use_subscription is false — the CLI will pick its own default"


def build_subprocess_env(use_subscription: bool) -> dict[str, str] | None:
    """Environment for the `claude` subprocess.

    `ANTHROPIC_API_KEY` takes precedence over the claude.ai login, so if it is set
    anywhere in the environment every call bills pay-as-you-go API credit instead
    of the Claude Code subscription — silently, apart from one warning line on
    stderr. This platform is specified to index against the subscription, so by
    default the key is dropped for the child process only. The parent
    environment is untouched (other tooling on the machine may need it).

    Returns None when there is nothing to change, so subprocess inherits normally.
    """
    if not use_subscription:
        return None
    import os

    if "ANTHROPIC_API_KEY" not in os.environ:
        return None
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def invoke_claude(
    prompt: str, model: str, cwd: str | None = None, use_subscription: bool = True
) -> str:
    """Call `claude -p <prompt> --output-format json --model <resolved-model>`.

    This is the ONLY function in this module that shells out. Mock this in tests.

    `cwd` must be the directory holding the contact sheets: headless `claude -p`
    auto-denies permission prompts, and reading files outside its working
    directory can trigger one — inside cwd it never does (verified empirically).
    """
    import subprocess

    resolved_model = MODEL_MAP.get(model, model)
    cmd = [
        "claude", "-p", prompt, "--output-format", "json", "--model", resolved_model,
        # Every tool definition sits in the system prompt of every call. This
        # task only ever needs Read (to open the contact sheets), and stripping
        # the rest measured 66,576 -> 45,590 input tokens per call — a 32% cut,
        # and faster (84s vs 108s). Across an archive that is tens of millions
        # of tokens, i.e. materially more indexing per session window.
        "--disallowedTools", DISALLOWED_TOOLS,
        # Without this the CLI loads the user's own MCP servers (Blender,
        # Google Sheets, DaVinci Resolve) on EVERY call — verified in the
        # process tree, each `claude -p` had uv/uvx server children. This task
        # never uses them. Their schemas are fetched on demand so the token cost
        # is small (~244/call measured), but booting two stdio servers per call
        # is pure latency across thousands of calls, and an indexing run has no
        # business starting Blender.
        "--strict-mcp-config",
    ]
    # UTF-8 rather than the system codepage: descriptions of non-English footage
    # come back with CJK text, which the Windows locale codec cannot decode.
    result = subprocess.run(
        cmd, capture_output=True, timeout=600, cwd=cwd,
        env=build_subprocess_env(use_subscription),
        text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude exited {result.returncode}: {_describe_cli_failure(result.stdout, result.stderr)}"
        )
    # A zero exit code is not success: the CLI reports API failures (credit
    # exhausted, rate limit, auth) as is_error in its stdout envelope.
    err = _envelope_error(result.stdout)
    if err:
        raise ClaudeCallError(err)
    return result.stdout


class ClaudeCallError(RuntimeError):
    """An API-level failure reported by the CLI (as opposed to bad model output).

    Distinguished from a parse/validation error because these are usually
    environmental — exhausted credit, rate limit, bad auth — and affect EVERY
    subsequent call. A queue that treats them as per-video failures will march
    through the whole archive marking everything 'error'.
    """


# Failures that will not fix themselves on the next call, and need a human.
_FATAL_MARKERS = (
    "credit balance is too low",
    "insufficient credit",
    "authentication_error",
    "invalid api key",
    "permission_error",
    "account is not authorized",
)

# Failures that WILL clear on their own, but not before the next video: a
# session/rate limit applies to the whole account, so every remaining call fails
# too. They are per-run fatal even though they are not permanent — marking each
# video 'error' would poison an entire archive queue over a limit that resets in
# an hour. Stop cleanly instead and resume afterwards.
_RATE_LIMIT_MARKERS = (
    "session limit",
    "rate_limit_error",
    "rate limit",
    "429",
    "usage limit",
    "quota exceeded",
    "too many requests",
)


def is_rate_limited(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _RATE_LIMIT_MARKERS)


def is_fatal_api_error(message: str) -> bool:
    """True when continuing the run is pointless — stop rather than fail each video.

    Covers both permanent problems (credit, auth) and account-wide temporary
    ones (rate/session limits). The distinction that matters here is not
    permanent-vs-temporary but per-video-vs-account-wide: anything account-wide
    will fail every remaining video identically, so the queue must be left
    untouched for a later resume.
    """
    lowered = message.lower()
    return any(marker in lowered for marker in _FATAL_MARKERS) or is_rate_limited(message)


def extract_reset_hint(message: str) -> str | None:
    """Pull the 'resets 10:10pm (Asia/Taipei)' hint out of a limit message, if present."""
    import re

    m = re.search(r"resets?\s+([^·\n]+)", message, re.IGNORECASE)
    return m.group(1).strip() if m else None


# A misparsed hint must not park the run for half a day. Anything beyond this
# falls back to the blind poll; real session windows are hours, not days.
MAX_RESET_WAIT_S = 6 * 3600
# The limit clears AT the stated minute, so retrying on the dot races it and
# spends a whole worker set on a 429 that would have succeeded a moment later.
RESET_MARGIN_S = 60


def seconds_until_reset(hint: str | None, now: "datetime | None" = None) -> float | None:
    """Seconds to wait for the window in `hint` ("4:30am (Asia/Taipei)") to reset.

    Returns None when the hint is absent or unparseable, so the caller can fall
    back to blind polling.

    Why this exists: run_queue.py polled every 15 minutes regardless, and each
    poll relaunches the API stage with N workers — ~26 real calls that all 429
    before the parent sees the failure and cancels the rest. On the night of
    2026-08-02 that was 21 retries against limits whose reset time was printed
    in the error message itself: ~546 calls spent learning nothing. The reset
    time was always right there in the string this parses.

    The clock time is read as LOCAL. The message does carry a zone in
    parentheses, but the machine indexing this archive runs in it, and honouring
    a foreign zone properly would mean a tz database dependency for a value we
    already bound and sanity-check. A wrong-zone hint simply lands outside
    MAX_RESET_WAIT_S or reads as "already passed" and falls back.
    """
    import re
    from datetime import datetime, timedelta

    if not hint:
        return None
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", hint, re.IGNORECASE)
    if not m:
        return None

    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridiem = (m.group(3) or "").lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    now = now or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        # Already gone today, so it is tomorrow's — a limit hit at 11pm that
        # resets "1am" is two hours away, not twenty-two hours ago.
        target += timedelta(days=1)

    # Bound the RAW distance, not the padded one: the cap is a plausibility
    # check on the reset time itself, and the margin is an implementation
    # detail that must not be what disqualifies an otherwise sane hint.
    delta = (target - now).total_seconds()
    if delta > MAX_RESET_WAIT_S:
        return None
    return delta + RESET_MARGIN_S


def _envelope_error(stdout: str) -> str | None:
    """Extract an API error the CLI reported in its JSON envelope, if any."""
    try:
        obj = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict) or not obj.get("is_error"):
        return None
    detail = obj.get("result") or obj.get("error") or "unknown error"
    status = obj.get("api_error_status")
    return f"API error{f' {status}' if status else ''}: {detail}"


def _describe_cli_failure(stdout: str, stderr: str) -> str:
    """Best available description of a non-zero exit.

    stderr often carries only an unrelated warning (e.g. the claude.ai connectors
    notice) while the real cause sits in the stdout envelope — reporting stderr
    alone sent a real debugging session chasing the wrong thing entirely.
    """
    envelope = _envelope_error(stdout)
    if envelope:
        return envelope
    err = (stderr or "").strip()
    out = (stdout or "").strip()
    if err and out:
        return f"{err} | stdout: {out[:300]}"
    return err or out[:300] or "no output"


# ---------------------------------------------------------------------------
# response parsing / validation
# ---------------------------------------------------------------------------

def extract_claude_text(raw: str) -> str:
    """Unwrap the `claude -p --output-format json` CLI envelope to the model's raw text.

    The CLI's own JSON envelope looks like `{"type": "result", "result": "<model text>", ...}`.
    If `raw` doesn't parse as JSON at all, or doesn't look like that envelope, it's returned
    unchanged (useful for tests that feed the contract JSON directly).
    """
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(obj, dict) and isinstance(obj.get("result"), str):
        return obj["result"]
    return raw


def extract_usage(raw: str) -> dict[str, Any]:
    """Pull token/cost accounting out of the `claude -p` envelope, if present.

    Returns {} when the envelope is absent (the CLI sometimes emits the model's
    text bare). Note `cache_creation_input_tokens` + `cache_read_input_tokens`
    are per-call context overhead that has nothing to do with the images sent —
    on small windows it dominates total cost, which is what makes packing more
    sheets into each call worthwhile.
    """
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(obj, dict):
        return {}
    usage = obj.get("usage")
    if not isinstance(usage, dict):
        # No accounting available — distinct from "a call that used zero
        # tokens", which would otherwise be logged as a real (free) call and
        # skew the cost-per-clip-minute figure.
        return {}
    return {
        "input_tokens": usage.get("input_tokens", 0),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "total_cost_usd": obj.get("total_cost_usd", 0.0),
        "duration_ms": obj.get("duration_ms", 0),
    }


def validate_contract(obj: Any) -> dict[str, Any]:
    """Raise ValueError if `obj` doesn't match the index_clip.md JSON contract."""
    if not isinstance(obj, dict):
        raise ValueError("claude response is not a JSON object")

    required = {"themes", "category_hint", "quality_flags", "segments"}
    missing = required - obj.keys()
    if missing:
        raise ValueError(f"claude response missing keys: {sorted(missing)}")

    if not isinstance(obj["themes"], list):
        raise ValueError("themes must be a list")
    if not isinstance(obj["quality_flags"], list):
        raise ValueError("quality_flags must be a list")
    if not isinstance(obj["segments"], list):
        raise ValueError("segments must be a list")

    # Drop out-of-vocabulary flags rather than failing the clip. The prompt asks
    # for a fixed vocabulary, but a model occasionally invents a plausible one
    # ('pixelated' was seen on the real archive) — and discarding an entire
    # video's index, after paying for every one of its contact-sheet calls, is a
    # far worse outcome than losing one advisory tag. The schema's CHECK
    # constraint would reject the unknown value at write time anyway.
    unknown = [f for f in obj["quality_flags"] if f not in QUALITY_FLAG_VOCAB]
    if unknown:
        obj = {**obj, "quality_flags": [f for f in obj["quality_flags"]
                                        if f in QUALITY_FLAG_VOCAB]}

    required_seg_keys = {"t_start", "t_end", "description", "objects", "setting", "motion"}
    for i, seg in enumerate(obj["segments"]):
        if not isinstance(seg, dict):
            raise ValueError(f"segment {i} is not an object")
        missing_seg = required_seg_keys - seg.keys()
        if missing_seg:
            raise ValueError(f"segment {i} missing keys: {sorted(missing_seg)}")

    # PRESENT-BUT-NULL is not the same as missing, and only the check above was
    # being made. A segment carrying `"t_end": null` or `"setting": null` passed
    # validation and then died at the INSERT on a NOT NULL column, which threw
    # away the whole clip's index after every one of its contact-sheet calls had
    # already been paid for. Three clips on the real archive failed exactly this
    # way (segments.t_end x2, segments.setting x1) and would have failed
    # identically on every future run.
    #
    # The two kinds of field need opposite treatment:
    #   - the text fields all have DEFAULT '' in the schema and mean "nothing
    #     found", so a null coerces to "" exactly like _normalize_onscreen_text
    #     already does one block below;
    #   - t_start/t_end cannot be invented. A segment with no time cannot be put
    #     on a timeline, so it is DROPPED and the rest of the clip is kept --
    #     the same trade already made for out-of-vocabulary quality flags above.
    # `objects` is a LIST in the contract (the writer ", "-joins it); the rest
    # are plain strings. Coercing it to "" would silently drop every object
    # keyword on the clip, which is most of what makes it findable.
    _STR_SEG_FIELDS = ("description", "setting", "motion")
    timed_segments = []
    dropped = 0
    for seg in obj["segments"]:
        if isinstance(seg.get("t_start"), bool) or isinstance(seg.get("t_end"), bool) \
                or not isinstance(seg.get("t_start"), (int, float)) \
                or not isinstance(seg.get("t_end"), (int, float)):
            dropped += 1
            continue
        timed_segments.append({
            **seg,
            **{k: (seg[k] if isinstance(seg.get(k), str) else "")
               for k in _STR_SEG_FIELDS},
            "objects": seg["objects"] if isinstance(seg.get("objects"), list) else [],
        })
    if dropped and not timed_segments:
        # Every segment was untimed: there is nothing to write, and silently
        # marking the clip indexed with zero segments would hide that.
        raise ValueError(
            f"all {dropped} segment(s) had a null or non-numeric t_start/t_end")
    if dropped:
        logger.warning("dropped %d segment(s) with no usable t_start/t_end; "
                       "keeping the remaining %d", dropped, len(timed_segments))
    obj = {**obj, "segments": timed_segments}

    # `onscreen_text`/`onscreen_text_en` are required keys per SPEC.md's v2 contract, but
    # they are deliberately NOT enforced as strictly as required_seg_keys above: failing
    # the whole segment (and burning the retry, and then the whole clip's index pass and
    # its token spend) over a model dropping an optional-feeling text field is a worse
    # outcome than just treating a missing value as "no on-screen text found". So we
    # default rather than raise, and normalize whatever shape comes back (including the
    # list-of-strings shape models sometimes use despite the prompt asking for a single
    # " | "-joined string). Built as a new list of new dicts rather than mutating `seg`
    # in place, so this function stays a pure transform of its input, like the rest of
    # this module.
    normalized_segments = [
        {
            **seg,
            "description": canonicalize_no_visual_label(seg.get("description", "")),
            "onscreen_text": _normalize_onscreen_text(seg.get("onscreen_text")),
            "onscreen_text_en": _normalize_onscreen_text(seg.get("onscreen_text_en")),
        }
        for seg in obj["segments"]
    ]

    return {**obj, "segments": normalized_segments}


def _normalize_onscreen_text(value: Any) -> str:
    """Coerce a segment's onscreen_text/onscreen_text_en value into a plain string.

    - missing / None -> ""
    - a list of strings (models sometimes return one piece of on-screen text per list
      item despite the prompt asking for a single string) -> " | "-joined
    - any other non-string value -> "" (never fail the segment over this field)
    """
    if isinstance(value, list):
        return " | ".join(str(v) for v in value)
    if isinstance(value, str):
        return value
    return ""


def _strip_code_fences(text: str) -> str:
    """Drop a wrapping ```/```json fence if the model added one despite instructions."""
    t = text.strip()
    if not t.startswith("```"):
        return t
    t = t.split("\n", 1)[1] if "\n" in t else ""
    t = t.rstrip()
    if t.endswith("```"):
        t = t[:-3]
    return t.strip()


def _first_json_object(text: str) -> Any:
    """The first complete JSON value in `text`, ignoring anything around it.

    `json.loads` is all-or-nothing: a response that is a perfectly good object
    followed by a sentence of commentary fails with "Extra data", and the whole
    call is thrown away. Measured on 2026-08-07, that single failure mode
    accounted for 32 of 33 lost clips — each one a paid call plus its retry,
    discarded over trailing prose the contract does not even use.

    Deliberately narrow: the object still has to be the first thing after any
    code fence, and it is still handed to validate_contract afterwards. This
    forgives the model padding its answer, not returning a different one.
    """
    decoder = json.JSONDecoder()
    start = text.find("{")
    if start == -1:
        raise json.JSONDecodeError("no JSON object found", text, 0)
    obj, _end = decoder.raw_decode(text, start)
    return obj


def parse_claude_response(raw: str) -> dict[str, Any]:
    """Parse+validate a `claude -p` stdout blob into the index_clip.md contract dict."""
    text = _strip_code_fences(extract_claude_text(raw))
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        # Retry as "first object, ignore the rest" before giving up: a retry
        # costs a whole extra call, and this recovers the common case without
        # one. If this fails too the response is genuinely unusable.
        try:
            obj = _first_json_object(text)
        except (json.JSONDecodeError, ValueError):
            raise ValueError(f"claude response is not valid JSON: {e}") from e
    return validate_contract(obj)


def call_claude_with_retry(
    prompt: str, model: str, invoke: InvokeFn = invoke_claude
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One retry on invalid JSON, per SPEC's Claude indexing output contract.

    Returns (parsed_contract, usage). Usage is {} if the CLI gave no envelope.
    """
    last_error: Exception | None = None
    for _attempt in range(2):
        raw = invoke(prompt, model)
        try:
            return parse_claude_response(raw), extract_usage(raw)
        except ValueError as e:
            last_error = e
            continue
    raise ValueError(f"claude returned invalid JSON after one retry: {last_error}")


# ---------------------------------------------------------------------------
# prompt building
# ---------------------------------------------------------------------------

def build_index_prompt(sheet_paths: list[Path], taxonomy: list[str]) -> str:
    template = _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    sheet_list = "\n".join(f"- {p}" for p in sheet_paths)
    taxonomy_list = "\n".join(f"- {slug}" for slug in taxonomy) if taxonomy else "(no taxonomy defined yet)"
    prompt = template.replace("__SHEET_PATHS__", sheet_list)
    prompt = prompt.replace("__TAXONOMY_LIST__", taxonomy_list)
    return prompt


# ---------------------------------------------------------------------------
# windowing / merge (pure — no I/O, no subprocess)
# ---------------------------------------------------------------------------

def chunk_sheets(sheet_paths: list[Path], sheets_per_call: int = 4) -> list[list[Path]]:
    """Group contact sheets into windows of `sheets_per_call` (default 4 sheets = 36 frames)."""
    if sheets_per_call < 1:
        raise ValueError("sheets_per_call must be >= 1")
    return [sheet_paths[i:i + sheets_per_call] for i in range(0, len(sheet_paths), sheets_per_call)]


def cap_sheets(sheet_paths: list[Path], max_sheets: int) -> list[Path]:
    """Evenly subsample `sheet_paths` down to at most `max_sheets`, preserving order.

    The sheets are ordered by timecode, so an even stride keeps coverage spanning
    the whole clip rather than truncating to its first N sheets — a 16-minute clip
    capped to 24 sheets still samples start to end, just more coarsely. Always
    keeps the first and last sheet so the clip's full span is represented.

    max_sheets <= 0 means no cap. Fewer sheets than the cap are returned unchanged.
    """
    n = len(sheet_paths)
    if max_sheets <= 0 or n <= max_sheets:
        return sheet_paths
    if max_sheets == 1:
        return [sheet_paths[0]]
    # Even stride across the full index range, endpoints included. Rounding can
    # collide on adjacent indices for aggressive caps; dedupe while preserving order.
    idx = sorted({round(i * (n - 1) / (max_sheets - 1)) for i in range(max_sheets)})
    return [sheet_paths[i] for i in idx]


def merge_index_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge per-window claude results into one: union themes/flags, concat segments,
    first non-null category_hint wins.
    """
    themes: list[str] = []
    seen_themes: set[str] = set()
    flags: list[str] = []
    seen_flags: set[str] = set()
    segments: list[dict[str, Any]] = []
    category_hint = None

    for result in results:
        for t in result.get("themes", []):
            if t not in seen_themes:
                seen_themes.add(t)
                themes.append(t)
        for f in result.get("quality_flags", []):
            if f not in seen_flags:
                seen_flags.add(f)
                flags.append(f)
        segments.extend(result.get("segments", []))
        if category_hint is None and result.get("category_hint"):
            category_hint = result["category_hint"]

    return {
        "themes": themes,
        "quality_flags": flags,
        "category_hint": category_hint,
        "segments": segments,
    }
