"""The Messages API boundary in broll_index/claude_client.py.

2026-08-17, COMMERCIAL_READINESS.md item 1: the indexer used to shell out to the
`claude -p` CLI against a personal Claude Code subscription. It now calls the API
through the `anthropic` SDK with a customer-supplied key. Everything here runs
against a fake client — no network, no SDK import, no API key required, so the
suite stays runnable on a machine that has neither.
"""
from __future__ import annotations

import base64
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from broll_index.claude_client import (
    ClaudeCallError,
    MissingApiKeyError,
    build_message_content,
    describe_api_error,
    estimate_cost_usd,
    invoke_claude,
    is_fatal_api_error,
    is_rate_limited,
    parse_claude_response,
    resolve_api_key,
    resolve_model,
    set_max_concurrency,
)
from broll_index.config import AnthropicConfig

VALID_CONTRACT = {
    "themes": ["harbour"],
    "category_hint": "military/naval",
    "quality_flags": ["noisy"],
    "segments": [
        {
            "t_start": 0.0, "t_end": 4.0,
            "description": "Grey warship at anchor, overcast",
            "objects": ["warship", "harbour"],
            "setting": "harbour, daylight",
            "motion": "static",
        }
    ],
}


# ---------------------------------------------------------------------------
# the fake SDK client — the whole injectable surface is `.messages.create`
# ---------------------------------------------------------------------------

def _message(text: str, *, stop_reason: str = "end_turn", output_tokens: int = 120):
    """A stand-in for anthropic.types.Message. Attribute access, like the real one."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=4000,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            output_tokens=output_tokens,
        ),
    )


class FakeApiError(Exception):
    """Shaped like anthropic.APIStatusError: status_code, body, response.headers."""

    def __init__(self, status_code: int, err_type: str, message: str,
                 retry_after: str | None = None):
        super().__init__(f"{status_code}: {message}")
        self.status_code = status_code
        self.body = {"type": "error", "error": {"type": err_type, "message": message}}
        headers = {"retry-after": retry_after} if retry_after else {}
        self.response = SimpleNamespace(status_code=status_code, headers=headers)


class FakeMessages:
    def __init__(self, outcomes):
        # Each outcome is a Message to return or an Exception to raise.
        self._outcomes = list(outcomes)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0) if self._outcomes else _message(json.dumps(VALID_CONTRACT))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, *outcomes):
        self.messages = FakeMessages(outcomes)


def _settings(**kw) -> AnthropicConfig:
    kw.setdefault("max_retries", 2)
    kw.setdefault("retry_base_delay_s", 0.0)
    kw.setdefault("retry_max_delay_s", 0.0)
    return AnthropicConfig(**kw)


# ---------------------------------------------------------------------------
# no key = refuse loudly, once, and let the run stop with the queue intact
# ---------------------------------------------------------------------------

def test_no_key_anywhere_raises_a_named_error_naming_the_env_var():
    with pytest.raises(MissingApiKeyError) as exc:
        resolve_api_key(AnthropicConfig(api_key_env="BROLL_TEST_KEY"), env={})
    assert "BROLL_TEST_KEY" in str(exc.value)
    # and it must never suggest putting the key in config.yaml
    assert "must never be written into config.yaml" in str(exc.value)


def test_a_missing_key_is_account_wide_not_a_per_clip_failure():
    """The pipeline branches on the MESSAGE, not the class (see is_fatal_api_error).
    A missing key fails every video identically, so the run must stop with the
    queue untouched rather than marking thousands of clips 'error'."""
    try:
        resolve_api_key(AnthropicConfig(), env={})
    except MissingApiKeyError as e:
        assert is_fatal_api_error(str(e))
    else:  # pragma: no cover
        pytest.fail("expected MissingApiKeyError")


def test_key_comes_from_the_named_env_var():
    settings = AnthropicConfig(api_key_env="BROLL_TEST_KEY")
    assert resolve_api_key(settings, env={"BROLL_TEST_KEY": "  sk-ant-xyz  "}) == "sk-ant-xyz"


def test_key_can_come_from_a_keyfile_with_comments(tmp_path):
    key_file = tmp_path / "anthropic.key"
    key_file.write_text("# customer key, rotated 2026-08-17\n\nsk-ant-fromfile\n", encoding="utf-8")
    settings = AnthropicConfig(api_key_env="BROLL_TEST_KEY", api_key_file=str(key_file))
    assert resolve_api_key(settings, env={}) == "sk-ant-fromfile"


def test_the_env_var_wins_over_the_keyfile(tmp_path):
    key_file = tmp_path / "anthropic.key"
    key_file.write_text("sk-ant-fromfile\n", encoding="utf-8")
    settings = AnthropicConfig(api_key_env="BROLL_TEST_KEY", api_key_file=str(key_file))
    assert resolve_api_key(settings, env={"BROLL_TEST_KEY": "sk-ant-fromenv"}) == "sk-ant-fromenv"


# ---------------------------------------------------------------------------
# vision: the contact sheets travel with the request
# ---------------------------------------------------------------------------

def _png(path: Path) -> Path:
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fake sheet bytes")
    return path


def test_image_blocks_are_assembled_before_the_prompt_text(tmp_path):
    sheets = [_png(tmp_path / "sheet_0001.png"), _png(tmp_path / "sheet_0002.png")]
    blocks = build_message_content("describe these", sheets)

    assert [b["type"] for b in blocks] == ["image", "image", "text"]
    assert blocks[-1]["text"] == "describe these"
    for block, sheet in zip(blocks[:2], sheets):
        assert block["source"]["type"] == "base64"
        assert block["source"]["media_type"] == "image/png"
        assert base64.standard_b64decode(block["source"]["data"]) == sheet.read_bytes()


def test_jpeg_sheets_get_the_jpeg_media_type(tmp_path):
    sheet = tmp_path / "sheet_0001.jpg"
    sheet.write_bytes(b"\xff\xd8\xff fake jpeg")
    assert build_message_content("x", [sheet])[0]["source"]["media_type"] == "image/jpeg"


def test_an_unsupported_sheet_type_is_rejected_rather_than_sent(tmp_path):
    bad = tmp_path / "sheet_0001.tiff"
    bad.write_bytes(b"II*\x00")
    with pytest.raises(ValueError, match="unsupported"):
        build_message_content("x", [bad])


def test_invoke_sends_the_images_and_the_resolved_model(tmp_path):
    sheets = [_png(tmp_path / "sheet_0001.png")]
    client = FakeClient(_message(json.dumps(VALID_CONTRACT)))

    invoke_claude("prompt text", "haiku", images=sheets, settings=_settings(), client=client)

    sent = client.messages.calls[0]
    assert sent["model"] == resolve_model("haiku") == "claude-haiku-4-5"
    assert sent["max_tokens"] == AnthropicConfig().max_tokens
    content = sent["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "text"]
    # Indexing a contact sheet is extraction, not reasoning: thinking tokens on
    # every one of tens of thousands of calls are pure cost, so off by default.
    assert sent["thinking"] == {"type": "disabled"}


def test_thinking_can_be_turned_on_for_an_archive_that_wants_it(tmp_path):
    client = FakeClient(_message(json.dumps(VALID_CONTRACT)))
    invoke_claude("p", "sonnet", settings=_settings(thinking="adaptive"), client=client)
    assert client.messages.calls[0]["thinking"] == {"type": "adaptive"}


# ---------------------------------------------------------------------------
# the response: same envelope the pipeline has always parsed
# ---------------------------------------------------------------------------

def test_a_normal_reply_parses_into_the_contract():
    client = FakeClient(_message(json.dumps(VALID_CONTRACT)))
    raw = invoke_claude("p", "sonnet", settings=_settings(), client=client)

    parsed = parse_claude_response(raw)
    assert parsed["themes"] == ["harbour"]
    assert parsed["segments"][0]["description"].startswith("Grey warship")

    envelope = json.loads(raw)
    assert envelope["usage"]["input_tokens"] == 4000
    assert envelope["usage"]["output_tokens"] == 120
    assert envelope["model"] == "claude-sonnet-5"
    # An estimate, not a billed figure — the API returns tokens, not dollars.
    assert envelope["total_cost_usd"] == pytest.approx(
        estimate_cost_usd("claude-sonnet-5", envelope["usage"]))
    assert envelope["total_cost_usd"] > 0


def test_a_fenced_reply_still_parses():
    client = FakeClient(_message("```json\n" + json.dumps(VALID_CONTRACT) + "\n```"))
    raw = invoke_claude("p", "sonnet", settings=_settings(), client=client)
    assert parse_claude_response(raw)["category_hint"] == "military/naval"


def test_a_refusal_is_this_clip_s_problem_not_the_account_s():
    client = FakeClient(_message("", stop_reason="refusal"))
    with pytest.raises(ValueError, match="refusal"):
        invoke_claude("p", "sonnet", settings=_settings(), client=client)


def test_a_dict_shaped_response_works_too():
    """The fake surface must not depend on SDK objects — a plain dict is enough."""
    client = FakeClient({
        "content": [{"type": "text", "text": json.dumps(VALID_CONTRACT)}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 20},
    })
    raw = invoke_claude("p", "haiku", settings=_settings(), client=client)
    assert parse_claude_response(raw)["themes"] == ["harbour"]


# ---------------------------------------------------------------------------
# retry / backoff
# ---------------------------------------------------------------------------

def test_a_429_is_retried_and_then_succeeds(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)

    client = FakeClient(
        FakeApiError(429, "rate_limit_error", "Number of requests has exceeded your limit"),
        _message(json.dumps(VALID_CONTRACT)),
    )
    raw = invoke_claude("p", "haiku", settings=_settings(max_retries=3, retry_base_delay_s=1.0,
                                                        retry_max_delay_s=4.0),
                        client=client)

    assert parse_claude_response(raw)["themes"] == ["harbour"]
    assert len(client.messages.calls) == 2
    assert len(slept) == 1 and 0 < slept[0] <= 4.0


def test_the_server_s_retry_after_beats_our_own_backoff(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)

    client = FakeClient(
        FakeApiError(429, "rate_limit_error", "slow down", retry_after="7"),
        _message(json.dumps(VALID_CONTRACT)),
    )
    invoke_claude("p", "haiku",
                  settings=_settings(max_retries=3, retry_base_delay_s=1.0, retry_max_delay_s=60.0),
                  client=client)
    assert slept == [7.0]


def test_a_529_overloaded_is_retried_too(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    client = FakeClient(
        FakeApiError(529, "overloaded_error", "Overloaded"),
        _message(json.dumps(VALID_CONTRACT)),
    )
    invoke_claude("p", "haiku", settings=_settings(max_retries=2), client=client)
    assert len(client.messages.calls) == 2


def test_exhausted_retries_report_an_account_wide_failure(monkeypatch):
    """The run must STOP with the queue resumable, not mark every clip 'error'."""
    monkeypatch.setattr(time, "sleep", lambda s: None)
    client = FakeClient(*[FakeApiError(429, "rate_limit_error", "Too Many Requests")] * 4)

    with pytest.raises(ClaudeCallError) as exc:
        invoke_claude("p", "haiku", settings=_settings(max_retries=3), client=client)

    assert len(client.messages.calls) == 4  # first attempt + 3 retries
    assert is_rate_limited(str(exc.value))
    assert is_fatal_api_error(str(exc.value))


def test_auth_and_credit_failures_are_not_retried(monkeypatch):
    """Retrying a bad key or an empty balance just burns time — and both are
    account-wide, so they must stop the run rather than fail one clip."""
    monkeypatch.setattr(time, "sleep", lambda s: None)
    for status, err_type, message in (
        (401, "authentication_error", "invalid x-api-key"),
        (400, "invalid_request_error", "Your credit balance is too low to access the API"),
        (403, "permission_error", "account is not authorized"),
    ):
        client = FakeClient(FakeApiError(status, err_type, message))
        with pytest.raises(ClaudeCallError) as exc:
            invoke_claude("p", "haiku", settings=_settings(max_retries=3), client=client)
        assert len(client.messages.calls) == 1, f"{err_type} must not be retried"
        assert is_fatal_api_error(str(exc.value)), exc.value


def test_a_connection_error_is_retried(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)

    class APIConnectionError(Exception):
        pass

    client = FakeClient(APIConnectionError("connection reset"),
                        _message(json.dumps(VALID_CONTRACT)))
    invoke_claude("p", "haiku", settings=_settings(max_retries=2), client=client)
    assert len(client.messages.calls) == 2


def test_describe_api_error_carries_the_status_and_the_api_s_own_wording():
    described = describe_api_error(
        FakeApiError(429, "rate_limit_error", "You've hit your rate limit"))
    assert "429" in described and "rate_limit_error" in described
    # is_rate_limited reads exactly this string in the pipeline.
    assert is_rate_limited(described)


# ---------------------------------------------------------------------------
# concurrency cap
# ---------------------------------------------------------------------------

def test_the_concurrency_cap_is_respected():
    """The cap replaces the old `--workers` fan-out of `claude -p` subprocesses.
    Exceeding it does not merely waste money — every request in flight when a
    rate limit lands is a wasted call."""
    cap = 3
    set_max_concurrency(cap)

    in_flight = 0
    peak = 0
    lock = threading.Lock()
    release = threading.Event()

    class SlowMessages:
        def create(self, **kwargs):
            nonlocal in_flight, peak
            with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            release.wait(2.0)
            with lock:
                in_flight -= 1
            return _message(json.dumps(VALID_CONTRACT))

    client = SimpleNamespace(messages=SlowMessages())
    settings = _settings(max_concurrency=cap)

    threads = [threading.Thread(
        target=invoke_claude, args=("p", "haiku"),
        kwargs={"settings": settings, "client": client}) for _ in range(12)]
    for t in threads:
        t.start()
    # Give the first wave time to pile up against the semaphore before letting go.
    time.sleep(0.2)
    observed_peak = peak
    release.set()
    for t in threads:
        t.join(5.0)

    assert observed_peak == cap, f"expected {cap} calls in flight, saw {observed_peak}"
    assert peak <= cap


# ---------------------------------------------------------------------------
# config: the key never lives in config.yaml
# ---------------------------------------------------------------------------

def _write_config(tmp_path: Path, extra: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        f"shares:\n  broll: \"{tmp_path.as_posix()}\"\n"
        f"data_root: \"{tmp_path.as_posix()}\"\n"
        f"db:\n  mode: sqlite\n  path: \"{(tmp_path / 'b.db').as_posix()}\"\n"
        + extra,
        encoding="utf-8",
    )
    return path


def test_config_defaults_when_no_anthropic_section(tmp_path):
    from broll_index.config import load_config

    cfg = load_config(_write_config(tmp_path, ""))
    assert cfg.anthropic.api_key_env == "ANTHROPIC_API_KEY"
    assert cfg.anthropic.max_concurrency == 4
    assert cfg.anthropic.thinking == "disabled"
    assert not hasattr(cfg, "use_subscription"), \
        "the Claude Code subscription path is gone; nothing may re-introduce it"


def test_config_reads_the_anthropic_section(tmp_path):
    from broll_index.config import load_config

    cfg = load_config(_write_config(tmp_path, (
        "anthropic:\n"
        "  api_key_env: CUSTOMER_KEY\n"
        "  api_key_file: /etc/ccsync/anthropic.key\n"
        "  max_tokens: 4096\n"
        "  max_retries: 9\n"
        "  max_concurrency: 12\n"
        "  thinking: adaptive\n"
    )))
    assert cfg.anthropic.api_key_env == "CUSTOMER_KEY"
    assert cfg.anthropic.api_key_file == "/etc/ccsync/anthropic.key"
    assert cfg.anthropic.max_tokens == 4096
    assert cfg.anthropic.max_retries == 9
    assert cfg.anthropic.max_concurrency == 12
    assert cfg.anthropic.thinking == "adaptive"


@pytest.mark.parametrize("key", ["api_key", "key", "token"])
def test_a_key_written_into_config_yaml_is_refused(tmp_path, key):
    """config.yaml is copied between machines, pasted into support threads and
    committed to this repo. Refusing costs a minute; a leaked key costs the
    account, and silently honouring it would make the leak the easy path."""
    from broll_index.config import load_config

    with pytest.raises(ValueError, match="must not be set in config.yaml"):
        load_config(_write_config(tmp_path, f"anthropic:\n  {key}: sk-ant-secret\n"))


def test_an_unknown_thinking_mode_is_refused(tmp_path):
    from broll_index.config import load_config

    with pytest.raises(ValueError, match="anthropic.thinking"):
        load_config(_write_config(tmp_path, "anthropic:\n  thinking: sometimes\n"))


# ---------------------------------------------------------------------------
# pipeline wiring: the sheets actually reach the request
# ---------------------------------------------------------------------------

def test_stage_claude_sends_the_contact_sheets_as_image_blocks(
    tmp_path, sqlite_storage, monkeypatch
):
    """The wiring the CLI used to get by pinning its working directory to the
    sheets dir: the images now travel inside the request, so if stage_claude
    stopped passing them the model would be describing nothing at all — and
    would still return plausible-looking JSON."""
    from broll_index import pipeline
    from broll_index.config import Config, DbConfig, IndexerConfig, SamplingConfig, ShareConfig

    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="proxied", duration_s=8.0)
    sheets_dir = tmp_path / "_data" / "sheets" / str(vid)
    sheets_dir.mkdir(parents=True)
    sheets = [_png(sheets_dir / f"sheet_{i:04d}.png") for i in range(1, 3)]
    (sheets_dir / "frames.json").write_text(
        json.dumps({"sheets": [str(p) for p in sheets]}), encoding="utf-8")

    client = FakeClient(_message(json.dumps(VALID_CONTRACT)))
    monkeypatch.setattr(pipeline, "build_client", lambda settings: client)

    cfg = Config(
        shares={"broll": ShareConfig(root=str(tmp_path))},
        data_root=tmp_path / "_data",
        db=DbConfig(mode="sqlite", path=str(tmp_path / "b.db")),
        sampling=SamplingConfig(),
        indexer=IndexerConfig(backend="anthropic"),
    )
    pipeline.stage_describe(cfg, sqlite_storage, sqlite_storage.get_video(vid), model="haiku")

    assert len(client.messages.calls) == 1, "2 sheets is one 4-sheet window"
    content = client.messages.calls[0]["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "image", "text"]
    sent = [base64.standard_b64decode(b["source"]["data"]) for b in content[:2]]
    assert sent == [p.read_bytes() for p in sheets]
    # The prompt names the sheets in order so the model can map a frame back to
    # an absolute timecode — by NAME, since a path means nothing to it now.
    assert "sheet_0001.png" in content[-1]["text"]
    assert str(sheets[0]) not in content[-1]["text"]

    row = sqlite_storage.get_video(vid)
    assert row["status"] == "indexed"
    assert row["model"] == "claude-haiku-4-5"
