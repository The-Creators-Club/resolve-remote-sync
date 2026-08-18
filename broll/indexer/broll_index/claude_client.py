"""Anthropic Messages API calls, JSON contract parsing, prompt building, and
frame-window merging.

`invoke_claude` is the single network boundary per SPEC's requirement that it be
"easy to mock" — every other function here is pure and takes/returns plain data so
it's trivially testable without touching the API.

2026-08-17, COMMERCIAL_READINESS.md item 1: this module used to shell out to the
`claude -p` CLI against the operator's personal Claude Code subscription. That is
not something a customer can be sold — it needs a claude.ai login on the indexing
machine, its session limits are per-person, and the Anthropic Consumer Terms do not
cover reselling it. The indexer now calls the Messages API through the official
`anthropic` SDK with a customer-supplied `ANTHROPIC_API_KEY`. There is no
subscription path left and no `claude` binary is required.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import random
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Sequence

# The contract helpers moved to contract.py on 2026-08-18 (plan §3.4) so the
# local backend's modules could be vendored into the companion without the
# Anthropic SDK riding along. Re-exported here, unchanged, because every
# existing caller and test imports them from THIS module and there is no
# reason to make them all move.
from .contract import (  # noqa: F401
    NO_VISUAL_LABELS,
    QUALITY_FLAG_VOCAB,
    _normalize_onscreen_text,
    canonicalize_no_visual_label,
    merge_index_results,
    validate_contract,
)

logger = logging.getLogger(__name__)

# Short names an operator types in config.yaml / `--model`, mapped to the API
# model ids. An id that is not a key here is passed through untouched, so a
# config can pin an exact model the map has not caught up with.
MODEL_MAP = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-5",
    "fable": "claude-fable-5",
}

# USD per million tokens (input, output) — used only to write an estimated
# `total_cost_usd` into usage.jsonl, which is how a full-archive run is
# forecast. The CLI used to report a real figure; the API does not, so this is
# a local estimate and is deliberately labelled as one wherever it surfaces.
# Cache reads are billed at ~0.1x input and cache writes at ~1.25x.
PRICE_PER_MTOK = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-fable-5": (10.00, 50.00),
}


def resolve_model(model: str) -> str:
    """Short name -> API model id; anything unknown passes through unchanged."""
    return MODEL_MAP.get(model, model)

# v2 contract: on-screen text capture (see SPEC.md "Claude indexing output contract" and
# docs/indexing-findings.md). index_clip.md (v1) is kept on disk for reference only — it
# is not loaded by build_index_prompt.
_PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "index_clip_v6.md"

InvokeFn = Callable[[str, str], str]


# ---------------------------------------------------------------------------
# error classification (shared by the API boundary and the pipeline)
# ---------------------------------------------------------------------------

class ClaudeCallError(RuntimeError):
    """An API-level failure (as opposed to bad model output).

    Distinguished from a parse/validation error because these are usually
    environmental — exhausted credit, rate limit, bad auth — and affect EVERY
    subsequent call. A queue that treats them as per-video failures will march
    through the whole archive marking everything 'error'.
    """


class MissingApiKeyError(ClaudeCallError):
    """No API key could be resolved — the run cannot place a single call.

    A subclass of ClaudeCallError, and its message carries `authentication_error`
    on purpose, so `is_fatal_api_error` treats it as account-wide: a missing key
    fails every video identically, and marking thousands of clips 'error' over a
    key that takes ten seconds to set would be a far worse outcome than stopping
    with the queue intact.
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
    "usage limit",
    "quota exceeded",
    "too many requests",
    # 529 overloaded_error: not a limit on this account, but it is upstream and
    # affects every worker at once, so it wants the same treatment — wait it out
    # and resume rather than marking each clip 'error'.
    "overloaded",
)

# A bare "429" used to sit in the list above, and it matched ANY error text that
# merely contained those three digits (BROLL-IDX-1, 2026-08-14). The archive is
# full of them: `ffprobe failed on C0429.MP4`, an ffmpeg stderr carrying
# .../sheets/4291/frames/frame_0003.jpg, a JSONDecodeError rendering
# "(char 429)". Each of those was then reclassified as an account-wide limit —
# the run aborted with "rate limit reached", and because that path deliberately
# leaves the clip's status alone so it can be retried, every subsequent run died
# on exactly the same clip and the queue never advanced. Anchor the status code
# to the shapes the CLI and the API actually emit ("API error 429: ...",
# "status 429", "HTTP 429", "429 Too Many Requests") instead.
_RATE_LIMIT_PATTERNS = (
    re.compile(r"\berror[:\s]\s*429\b"),
    re.compile(r"\bstatus(?:\s*code)?[:\s]\s*429\b"),
    re.compile(r"\bhttp[/\s]?[\d.]*\s*429\b"),
    re.compile(r"\b429[:\s]\s*too many requests\b"),
)


def is_rate_limited(message: str) -> bool:
    lowered = message.lower()
    if any(marker in lowered for marker in _RATE_LIMIT_MARKERS):
        return True
    return any(p.search(lowered) for p in _RATE_LIMIT_PATTERNS)


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


# ---------------------------------------------------------------------------
# API boundary — the only code in this package that touches the network
# ---------------------------------------------------------------------------

DEFAULT_API_KEY_ENV = "ANTHROPIC_API_KEY"
DEFAULT_MAX_CONCURRENCY = 4


def _api_settings(settings: Any = None) -> Any:
    """The caller's AnthropicConfig, or the defaults. Imported lazily to keep
    this module importable on its own (config.py never imports back)."""
    if settings is not None:
        return settings
    from .config import AnthropicConfig

    return AnthropicConfig()


def resolve_api_key(settings: Any = None, env: "dict[str, str] | None" = None) -> str:
    """The customer's API key, from the environment or a keyfile.

    Never from config.yaml: that file is copied between machines, pasted into
    support threads and (in this repo) committed, so a key living in it is a key
    that leaks. `api_key_env` names the variable and `api_key_file` points at a
    file — the value itself only ever lives outside the config.

    Raises MissingApiKeyError with an actionable message rather than letting the
    SDK fail per call: without a key not one clip can be indexed, and the run
    must say so once instead of failing 2,000 videos one at a time.
    """
    settings = _api_settings(settings)
    env = os.environ if env is None else env
    name = getattr(settings, "api_key_env", None) or DEFAULT_API_KEY_ENV

    key = (env.get(name) or "").strip()
    if key:
        return key

    key_file = getattr(settings, "api_key_file", None)
    if key_file:
        path = Path(key_file).expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            raise MissingApiKeyError(
                f"authentication_error: cannot read anthropic.api_key_file {path}: {e}"
            ) from e
        # First non-blank, non-comment line, so an operator can annotate the file.
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
        raise MissingApiKeyError(
            f"authentication_error: anthropic.api_key_file {path} contains no key")

    raise MissingApiKeyError(
        f"authentication_error: no Anthropic API key. Set {name} in the environment, "
        f"or set anthropic.api_key_file in config.yaml to a file holding one. "
        f"The key itself must never be written into config.yaml.")


def build_client(settings: Any = None, api_key: str | None = None) -> Any:
    """An `anthropic.Anthropic` client configured for this workload."""
    settings = _api_settings(settings)
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover - dependency is declared in pyproject
        raise ClaudeCallError(
            "the `anthropic` SDK is not installed — `pip install anthropic`") from e

    return anthropic.Anthropic(
        api_key=api_key or resolve_api_key(settings),
        # Retries live in _call_with_retry, not in the SDK. A silent SDK retry
        # cannot log what it is waiting on, cannot honour a reset hint, and —
        # once the budget is spent — cannot report the failure as the
        # account-wide one that stops the run with the queue intact.
        max_retries=0,
        timeout=getattr(settings, "timeout_s", 600.0),
    )


# ---- vision input ---------------------------------------------------------

_IMAGE_MEDIA_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
}


def image_block(path: str | Path) -> dict[str, Any]:
    """One contact sheet as a base64 image content block."""
    p = Path(path)
    media_type = _IMAGE_MEDIA_TYPES.get(p.suffix.lower())
    if media_type is None:
        raise ValueError(f"unsupported contact-sheet image type: {p.name}")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(p.read_bytes()).decode("ascii"),
        },
    }


def build_message_content(prompt: str, images: Sequence[str | Path] = ()) -> list[dict[str, Any]]:
    """Contact sheets first, prompt text last.

    Images before text is what the vision docs specify, and it matters here for a
    second reason: the prompt lists the sheets in timecode order and the model has
    to line each instruction up with the sheet it describes.
    """
    blocks: list[dict[str, Any]] = [image_block(p) for p in images]
    blocks.append({"type": "text", "text": prompt})
    return blocks


# ---- concurrency ----------------------------------------------------------
#
# The stage is latency-bound, not usage-bound: measured at ~84 s per call and
# strictly serial it managed 20 videos/hour. parallel_claude.py runs N of these
# at once; this semaphore is the ceiling that N is checked against, so a caller
# that fans out wider than the account can take still cannot put more than
# `max_concurrency` requests in flight.

_concurrency_lock = threading.Lock()
_concurrency: threading.BoundedSemaphore | None = None
_concurrency_size = 0


def set_max_concurrency(n: int) -> None:
    """Set the in-flight ceiling. Call before dispatching work, not during it."""
    global _concurrency, _concurrency_size
    n = max(1, int(n))
    with _concurrency_lock:
        _concurrency = threading.BoundedSemaphore(n)
        _concurrency_size = n


def current_max_concurrency() -> int:
    return _concurrency_size


def _get_semaphore(default_n: int) -> threading.BoundedSemaphore:
    global _concurrency, _concurrency_size
    with _concurrency_lock:
        if _concurrency is None:
            n = max(1, int(default_n or DEFAULT_MAX_CONCURRENCY))
            _concurrency = threading.BoundedSemaphore(n)
            _concurrency_size = n
        return _concurrency


@contextmanager
def _concurrency_guard(default_n: int):
    sem = _get_semaphore(default_n)
    sem.acquire()
    try:
        yield
    finally:
        sem.release()


# ---- errors and retry -----------------------------------------------------

# 429 rate limit, 529 overloaded, and the transient 5xx family. 408/409 are what
# the SDK's own retry policy treats as retryable too.
_RETRYABLE_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504, 529}
_RETRYABLE_EXC_NAMES = ("APIConnectionError", "APITimeoutError", "ConnectionError", "Timeout")


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """Attribute or mapping key — so a fake SDK response can be a plain dict."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _status_code(exc: BaseException) -> int | None:
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    code = getattr(getattr(exc, "response", None), "status_code", None)
    return code if isinstance(code, int) else None


def _retry_after_s(exc: BaseException) -> float | None:
    """The server's own `retry-after`, when it sent one. Always beats our guess."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if not headers:
        return None
    try:
        value = headers.get("retry-after")
    except AttributeError:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_retryable_error(exc: BaseException) -> bool:
    status = _status_code(exc)
    if status is not None:
        return status in _RETRYABLE_STATUSES
    names = {type(exc).__name__, *(b.__name__ for b in type(exc).__mro__)}
    return bool(names & set(_RETRYABLE_EXC_NAMES))


def describe_api_error(exc: BaseException) -> str:
    """"API error 429: rate_limit_error: ..." — the shape is_rate_limited reads.

    Deliberately built from the API's own error body: the classifiers in this
    module (and run_queue.py's decision to wait out a limit rather than stop)
    all key off this text, so it must carry the status code and the error type.
    """
    status = _status_code(exc)
    detail = None
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            detail = ": ".join(str(v) for v in (err.get("type"), err.get("message")) if v)
    detail = detail or getattr(exc, "message", None) or str(exc) or type(exc).__name__
    return f"API error{f' {status}' if status else ''}: {detail}"


def _backoff_delay(attempt: int, settings: Any, retry_after: float | None) -> float:
    max_delay = float(getattr(settings, "retry_max_delay_s", 60.0))
    if retry_after is not None:
        return min(max(retry_after, 0.0), max_delay)
    base = float(getattr(settings, "retry_base_delay_s", 2.0))
    delay = min(base * (2 ** attempt), max_delay)
    # Jitter: N workers hitting the same limit at the same instant would
    # otherwise wake together and hit it again in lockstep.
    return delay * (0.5 + random.random() / 2)


def _call_with_retry(client: Any, kwargs: dict[str, Any], settings: Any,
                     sleep: "Callable[[float], None] | None" = None) -> Any:
    """`client.messages.create(**kwargs)` with backoff on 429/5xx/overloaded."""
    max_retries = int(getattr(settings, "max_retries", 5))
    last: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            return client.messages.create(**kwargs)
        except Exception as e:  # noqa: BLE001 - re-raised below, classified first
            if not is_retryable_error(e):
                # 400/401/403 and friends: retrying changes nothing. Raise with
                # the API's own wording so is_fatal_api_error can see auth and
                # credit failures for what they are.
                raise ClaudeCallError(describe_api_error(e)) from e
            last = e
            if attempt >= max_retries:
                break
            delay = _backoff_delay(attempt, settings, _retry_after_s(e))
            logger.warning("claude: %s — retry %d/%d in %.1fs",
                           describe_api_error(e), attempt + 1, max_retries, delay)
            # Resolved per call, not bound as a default argument, so a test can
            # monkeypatch time.sleep and not wait out a real backoff.
            (sleep or time.sleep)(delay)
    # Out of retries on a retryable failure. This is account-wide by nature (a
    # rate limit or an overloaded API applies to every remaining video), so the
    # message must classify as fatal: the run stops and the queue is resumable,
    # rather than 2,000 clips being marked 'error' over a limit that clears.
    raise ClaudeCallError(
        f"{describe_api_error(last) if last else 'API error: unknown'} "
        f"(gave up after {max_retries} retries)")


def _thinking_param(settings: Any) -> dict[str, str] | None:
    mode = (getattr(settings, "thinking", "disabled") or "disabled").lower()
    if mode in ("adaptive", "on", "true"):
        return {"type": "adaptive"}
    if mode in ("disabled", "off", "false", "none"):
        return {"type": "disabled"}
    raise ValueError(f"anthropic.thinking must be 'adaptive' or 'disabled', got {mode!r}")


def estimate_cost_usd(model: str, usage: dict[str, Any]) -> float:
    """Local estimate of one call's cost — the API returns tokens, not dollars."""
    prices = PRICE_PER_MTOK.get(model)
    if not prices:
        return 0.0
    in_price, out_price = prices
    billed_in = (
        float(usage.get("input_tokens") or 0)
        + float(usage.get("cache_creation_input_tokens") or 0) * 1.25
        + float(usage.get("cache_read_input_tokens") or 0) * 0.1
    )
    return round(billed_in / 1e6 * in_price
                 + float(usage.get("output_tokens") or 0) / 1e6 * out_price, 6)


def _build_envelope(message: Any, model: str, duration_ms: int) -> dict[str, Any]:
    """The Messages API response, flattened to the envelope this module parses.

    The shape (`{"result": <text>, "usage": {...}, "total_cost_usd": ...}`) is
    inherited from the `claude -p` CLI that used to sit here. Keeping it means
    extract_claude_text / extract_usage / _log_usage / usage.jsonl and every
    test fixture built on them survived the move to the SDK untouched.
    """
    stop_reason = _attr(message, "stop_reason")
    blocks = _attr(message, "content", []) or []
    text = "".join(_attr(b, "text", "") or "" for b in blocks if _attr(b, "type") == "text")

    if stop_reason == "refusal":
        # A content outcome for THIS clip, not an account problem: raise the
        # per-video error so the clip is marked and the queue carries on.
        raise ValueError("claude declined this clip (stop_reason=refusal)")
    if stop_reason == "max_tokens":
        logger.warning("claude: response hit max_tokens — the JSON is probably "
                       "truncated; raise anthropic.max_tokens if this repeats")

    raw_usage = _attr(message, "usage") or {}
    usage = {
        "input_tokens": _attr(raw_usage, "input_tokens", 0) or 0,
        "cache_creation_input_tokens": _attr(raw_usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": _attr(raw_usage, "cache_read_input_tokens", 0) or 0,
        "output_tokens": _attr(raw_usage, "output_tokens", 0) or 0,
    }
    return {
        "type": "result",
        "is_error": False,
        "result": text,
        "model": model,
        "stop_reason": stop_reason,
        "usage": usage,
        # Estimated, not billed — see PRICE_PER_MTOK.
        "total_cost_usd": estimate_cost_usd(model, usage),
        "duration_ms": duration_ms,
    }


def invoke_claude(
    prompt: str,
    model: str,
    *,
    images: Sequence[str | Path] = (),
    settings: Any = None,
    client: Any = None,
) -> str:
    """One Messages API call. THE network boundary — mock this, or pass `client`.

    Returns the response as a JSON envelope string (see _build_envelope), which
    parse_claude_response / extract_usage consume.

    `client` takes anything with a `.messages.create(**kwargs)` method, which is
    the whole injectable surface the tests need — no network, no SDK import.
    """
    settings = _api_settings(settings)
    if client is None:
        client = build_client(settings)

    resolved_model = resolve_model(model)
    kwargs: dict[str, Any] = {
        "model": resolved_model,
        "max_tokens": int(getattr(settings, "max_tokens", 8000)),
        "messages": [{"role": "user", "content": build_message_content(prompt, images)}],
    }
    thinking = _thinking_param(settings)
    if thinking is not None:
        kwargs["thinking"] = thinking

    started = time.monotonic()
    with _concurrency_guard(getattr(settings, "max_concurrency", DEFAULT_MAX_CONCURRENCY)):
        message = _call_with_retry(client, kwargs, settings)
    duration_ms = int((time.monotonic() - started) * 1000)
    return json.dumps(_build_envelope(message, resolved_model, duration_ms),
                      ensure_ascii=False)


def describe_auth(settings: Any = None) -> str:
    """One line for the run banner stating what will be billed, and from where."""
    settings = _api_settings(settings)
    name = getattr(settings, "api_key_env", None) or DEFAULT_API_KEY_ENV
    try:
        resolve_api_key(settings)
    except MissingApiKeyError as e:
        return f"auth: NO API KEY — {e}"
    source = f"${name}" if (os.environ.get(name) or "").strip() else \
        f"anthropic.api_key_file ({getattr(settings, 'api_key_file', None)})"
    return (f"auth: Anthropic API key from {source} — billing this "
            f"organisation's API credit")


# ---------------------------------------------------------------------------
# response parsing / validation
# ---------------------------------------------------------------------------

def extract_claude_text(raw: str) -> str:
    """Unwrap the invoke envelope (see _build_envelope) to the model's raw text.

    The envelope looks like `{"type": "result", "result": "<model text>", ...}`.
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
    """Pull token/cost accounting out of the invoke envelope, if present.

    Returns {} when the envelope is absent (a mocked invoke may emit the model's
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
    """Parse+validate an invoke envelope (or bare model text) into the contract dict."""
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
    """The prompt text for one window of contact sheets.

    The sheets are listed by NAME, not by absolute path: they are attached to the
    same message as image blocks (build_message_content), so a path would be a
    filesystem detail the model cannot act on. The list still earns its place —
    it tells the model how many images to expect and in what order, which is what
    lets it map a frame back to an absolute timecode.
    """
    template = _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    sheet_list = "\n".join(f"- {Path(p).name}" for p in sheet_paths)
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
