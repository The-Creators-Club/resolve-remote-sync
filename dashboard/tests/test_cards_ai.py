"""`cards_ai.Runner`: one Claude session per montage, and the store it owns.

MONTAGE-BUILDER-PLAN.md §12 (2026-08-30) and
docs/TIMELINE-CARDS-INTO-CCSYNC.md §7d.1. Everything here runs against a FAKE
`anthropic` module put in `sys.modules` and a fake provider choice: no key, no
network, no subprocess, and every assertion is about the request this module
would have made.

The properties defended, each of them money or a montage:

  * NO SESSION IS BYTE FOR BYTE TODAY'S CALL. Translate, semantic search and
    summaries are three shipped features that never asked for a conversation,
    and §12 must not have changed a single field of the request they make.
  * THE CORPUS IS THE CACHED BLOCK, AND ONLY THE CORPUS. A cache breakpoint is
    billed per write; the instruction changes every turn and would invalidate
    what it is sitting on.
  * THE SPLIT IS A DOCUMENTED MARKER. The door hands the runner ONE string, so
    `---INSTRUCTIONS---` on a line of its own is the whole contract between
    the fork and this store, and a prompt without it must still work.
  * `session_lost` IS ONE WORD AND NO RETRY. Only the caller knows whether
    re-reading a corpus is worth the tokens.
  * THE HISTORY IS BOUNDED, AND THE CORPUS SURVIVES THE BOUND. A page left
    open for a week must not send a megabyte of history, and must not drop the
    one message every later turn depends on.
"""
from __future__ import annotations

import copy
import json
import types

import pytest

from ccsync_dashboard import ai_providers, cards_ai

CORPUS = "### pangolins [c1] FF5 -- the burrow (61.0s, speakers: A)\n0.0 3.2 hello"
MARKED = CORPUS + "\n\n" + cards_ai.INSTRUCTIONS_MARKER + "\n\ndescribe the montage"


class FakeSettings:
    def __init__(self, tmp_path):
        self.db_path = str(tmp_path / "dashboard.db")


class FakeSession:
    """The fork's `ClaudeSession`, duck-typed to the three fields §12.2 names."""

    def __init__(self, sid="1a2b-3c4d", turns=0, corpus_hash="sha-1"):
        self.id = sid
        self.turns = turns
        self.corpus_hash = corpus_hash


class FakeMessages:
    def __init__(self, calls, replies):
        self._calls = calls
        self._replies = replies

    def create(self, **kwargs):
        # A COPY: the real client serialises the messages here and now, and
        # this module appends the assistant's reply to the same list a moment
        # later. Recording the object would record the turn after this one.
        self._calls.append(copy.deepcopy(kwargs))
        text = self._replies.pop(0) if self._replies else "an answer"
        block = types.SimpleNamespace(text=text)
        return types.SimpleNamespace(content=[block])


class FakeClient:
    def __init__(self, calls, replies):
        self.messages = FakeMessages(calls, replies)

    def with_options(self, **kwargs):
        return self


@pytest.fixture
def sdk(tmp_path, monkeypatch):
    """A Runner whose provider is the API and whose SDK is a recorder.

    Returns `(runner, calls)`; `calls` is the kwargs of every
    `messages.create` this module made, in order.
    """
    calls: list[dict] = []
    replies: list[str] = []
    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda **kwargs: FakeClient(calls, replies)  # noqa: ARG005
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake)

    choice = ai_providers.ProviderChoice(name=ai_providers.ANTHROPIC_API,
                                         label="Anthropic API", reason="")
    monkeypatch.setattr(cards_ai.Runner, "_choice",
                        lambda self, probe=True: (choice, ""))
    monkeypatch.setattr(cards_ai.Runner, "_key",
                        lambda self: "sk-ant-not-a-real-key")
    # The detector is exercised on its own below; here the TTL is pinned so
    # every assertion is about the request this module builds.
    monkeypatch.setattr(cards_ai, "sdk_cache_ttl",
                        lambda: cards_ai.CACHE_TTL_HOUR)
    runner = cards_ai.Runner(FakeSettings(tmp_path))
    runner._replies = replies
    return runner, calls


def store_file(runner, sid="1a2b-3c4d"):
    return cards_ai._session_path(runner._settings, sid)


# -- the three shipped features are untouched --------------------------------

def test_no_session_is_todays_request(sdk):
    runner, calls = sdk
    out = runner.run("translate this", model="claude-haiku-4-5-20251001")

    assert out["ok"] is True
    assert calls == [{
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": cards_ai.MAX_TOKENS,
        "output_config": {"effort": "low"},
        "messages": [{"role": "user", "content": "translate this"}],
    }]


def test_no_session_writes_no_store(sdk, tmp_path):
    runner, _calls = sdk
    runner.run("translate this")
    assert not (tmp_path / "cards_sessions").exists()


# -- turn 0 ------------------------------------------------------------------

def test_turn_zero_caches_the_corpus_block(sdk):
    runner, calls = sdk
    out = runner.run(MARKED, model="claude-sonnet-5", session=FakeSession())

    assert out["ok"] is True
    assert len(calls) == 1
    messages = calls[0]["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == [
        {"type": "text", "text": CORPUS,
         "cache_control": {"type": "ephemeral", "ttl": "1h"}},
        {"type": "text", "text": "describe the montage"},
    ]


def test_turn_zero_stores_the_conversation(sdk):
    runner, _calls = sdk
    runner.run(MARKED, session=FakeSession())

    stored = json.loads(store_file(runner).read_text(encoding="utf-8"))
    assert stored["id"] == "1a2b-3c4d"
    assert stored["turns"] == 1
    assert stored["corpus_hash"] == "sha-1"
    assert stored["cache_ttl"] == "1h"
    assert stored["created"]
    assert [m["role"] for m in stored["messages"]] == ["user", "assistant"]
    assert stored["messages"][1]["content"] == "an answer"


def test_turn_zero_replaces_an_id_that_is_already_there(sdk):
    runner, calls = sdk
    runner.run(MARKED, session=FakeSession())
    runner.run(MARKED, session=FakeSession(turns=0))

    assert len(calls[1]["messages"]) == 1
    stored = json.loads(store_file(runner).read_text(encoding="utf-8"))
    assert stored["turns"] == 1


# -- later turns -------------------------------------------------------------

def test_turn_one_sends_the_history(sdk):
    runner, calls = sdk
    runner.run(MARKED, session=FakeSession())
    out = runner.run("more of the pangolins", session=FakeSession(turns=1))

    assert out["ok"] is True
    messages = calls[1]["messages"]
    assert len(messages) == 3
    assert messages[0]["content"][0]["cache_control"] == {"type": "ephemeral",
                                                          "ttl": "1h"}
    assert messages[1] == {"role": "assistant", "content": "an answer"}
    assert messages[2] == {"role": "user", "content": "more of the pangolins"}


def test_a_later_turn_is_not_a_second_cache_breakpoint(sdk):
    runner, calls = sdk
    runner.run(MARKED, session=FakeSession())
    runner.run("more of the pangolins", session=FakeSession(turns=1))

    later = calls[1]["messages"][2]
    assert isinstance(later["content"], str)


def test_an_unknown_id_is_session_lost_and_no_call(sdk):
    runner, calls = sdk
    out = runner.run("more of the pangolins",
                     session=FakeSession(sid="never-opened", turns=3))

    assert out["ok"] is False
    assert out["error"] == "session_lost"
    assert calls == []


def test_a_session_with_no_id_is_refused(sdk):
    runner, calls = sdk
    out = runner.run("hello", session=FakeSession(sid="", turns=0))

    assert out["ok"] is False
    assert "no id" in out["error"]
    assert calls == []


def test_a_failed_turn_leaves_the_stored_history_alone(sdk, monkeypatch):
    runner, _calls = sdk
    runner.run(MARKED, session=FakeSession())
    before = store_file(runner).read_text(encoding="utf-8")

    def boom(self, prompt, model, timeout, messages=None):
        raise cards_ai.ClaudeError("Claude did not answer in time")

    monkeypatch.setattr(cards_ai.Runner, "_sdk", boom)
    out = runner.run("more", session=FakeSession(turns=1))

    assert out["ok"] is False
    assert store_file(runner).read_text(encoding="utf-8") == before


# -- the bound ---------------------------------------------------------------

def test_the_store_trims_to_forty_turns_and_keeps_the_corpus(sdk):
    runner, _calls = sdk
    runner.run(MARKED, session=FakeSession())
    for turn in range(1, 60):
        runner.run(f"turn {turn}", session=FakeSession(turns=turn))

    stored = json.loads(store_file(runner).read_text(encoding="utf-8"))
    messages = stored["messages"]
    assert len(messages) == cards_ai.MAX_TURNS * 2
    assert messages[0]["content"][0]["text"] == CORPUS
    assert messages[1]["content"] == "an answer"
    assert messages[2]["content"] == "turn 21"
    assert [m["role"] for m in messages[::2]] == ["user"] * cards_ai.MAX_TURNS
    assert stored["turns"] == 60


# -- the marker rule ---------------------------------------------------------

def test_split_prompt_takes_the_last_marker():
    corpus, instruction = cards_ai.split_prompt(
        "a\n---INSTRUCTIONS---\nb\n---INSTRUCTIONS---\nc")
    assert corpus == "a\n---INSTRUCTIONS---\nb"
    assert instruction == "c"


@pytest.mark.parametrize("prompt", [
    "no marker at all",
    "---INSTRUCTIONS---\nnothing before it",
    "nothing after it\n---INSTRUCTIONS---\n",
    "an indented  ---INSTRUCTIONS---  marker does not count",
])
def test_prompts_without_a_usable_marker_are_one_block(sdk, prompt):
    runner, calls = sdk
    runner.run(prompt, session=FakeSession())

    content = calls[0]["messages"][0]["content"]
    assert content == [{"type": "text", "text": prompt}]


def test_a_marker_with_trailing_spaces_still_splits(sdk):
    runner, calls = sdk
    runner.run("corpus\n---INSTRUCTIONS---  \ndo it", session=FakeSession())

    content = calls[0]["messages"][0]["content"]
    assert content[0]["text"] == "corpus"
    assert content[1]["text"] == "do it"


# -- json_out, unchanged -----------------------------------------------------

def test_json_out_still_writes_the_file_in_a_session(sdk, tmp_path):
    runner, calls = sdk
    runner._replies.append('here you go {"sections": []}')
    out_path = tmp_path / "cut" / "answer.json"

    out = runner.run(MARKED, json_out=str(out_path), session=FakeSession())

    assert out["data"] == {"sections": []}
    assert json.loads(out_path.read_text(encoding="utf-8")) == {"sections": []}
    # The OUTPUT note lands in the instruction block, never in the cached one.
    content = calls[0]["messages"][0]["content"]
    assert content[0]["text"] == CORPUS
    assert "OUTPUT: reply with the JSON object alone" in content[1]["text"]


# -- the file name -----------------------------------------------------------

def test_the_id_can_never_leave_the_store_directory(tmp_path):
    settings = FakeSettings(tmp_path)
    path = cards_ai._session_path(settings, "../../etc/passwd")
    assert path.parent == tmp_path / "cards_sessions"
    assert path.name == "------etc-passwd.json"


# -- the CLI path ------------------------------------------------------------

def test_the_cli_resumes_by_id():
    assert cards_ai._cli_session_args(None) == []
    assert cards_ai._cli_session_args(FakeSession()) == ["--session-id", "1a2b-3c4d"]
    assert cards_ai._cli_session_args(FakeSession(turns=2)) == ["--resume", "1a2b-3c4d"]


def test_the_cli_id_is_stable_across_an_hour_of_calls():
    """The warm corpus on this path is Claude Code's own conversation, so the
    only thing this module owes it is the SAME id, turn after turn (decision
    6, Alex 2026-09-04). A second `--session-id` on turn 7, or a drifting id,
    would open a new conversation and re-read the corpus at full price."""
    session = FakeSession(sid="search-9f8e7d")
    assert cards_ai._cli_session_args(session) == ["--session-id", "search-9f8e7d"]
    for turn in range(1, 40):
        session.turns = turn
        assert cards_ai._cli_session_args(session) == ["--resume", "search-9f8e7d"]


def test_only_an_unknown_session_reads_as_session_lost():
    assert cards_ai._says_no_such_session("No conversation found with session ID abc")
    assert not cards_ai._says_no_such_session("Invalid API key")
    assert not cards_ai._says_no_such_session("command not found")


# -- status(): unknown is not "no" (CR-121, 2026-09-03) -----------------------
# Every `start_*` in the cards engine refuses up front on this dict, and the
# page prints `why` verbatim in the dimmed button's tooltip. The end-to-end
# cases (a real db, the wizard's snapshot, a stale probe) live in
# tests/test_ai_providers.py; these two are about the sentence.

@pytest.fixture
def no_db(monkeypatch):
    """`_unresolved_why` opens its own connection. Nothing here needs a real
    one: `provider_states` is the seam being stubbed."""
    from ccsync_dashboard import db as dbmod

    monkeypatch.setattr(dbmod, "connect",
                        lambda path: types.SimpleNamespace(close=lambda: None))


def refused(monkeypatch, reason="no provider has a working credential"):
    choice = ai_providers.ProviderChoice(name="", label="", reason=reason)
    monkeypatch.setattr(cards_ai.Runner, "_choice",
                        lambda self, probe=True: (choice, reason))


def rows_as(monkeypatch, status):
    monkeypatch.setattr(
        cards_ai.ai_providers, "provider_states",
        lambda conn, settings, **kw: [{"name": ai_providers.CLAUDE_CODE,
                                       "status": status}])


def test_an_unchecked_cli_is_not_reported_as_unavailable(tmp_path, monkeypatch, no_db):
    refused(monkeypatch)
    rows_as(monkeypatch, ai_providers.ST_UNKNOWN)
    out = cards_ai.Runner(FakeSettings(tmp_path)).status()
    assert out["ok"] is False
    assert "not been checked" in out["why"]
    assert "Settings -> AI providers" in out["why"]


def test_a_site_with_cli_providers_off_keeps_the_resolvers_reason(tmp_path, monkeypatch,
                                                                  no_db):
    """"Not checked yet" would be a lie about a site that turned the whole CLI
    half off: there is nothing to check and the answer is the chain's own."""
    refused(monkeypatch)
    rows_as(monkeypatch, ai_providers.ST_DISABLED)
    out = cards_ai.Runner(FakeSettings(tmp_path)).status()
    assert out["ok"] is False
    assert out["why"] == "no provider has a working credential"


# -- the one hour TTL (decision 6, Alex 2026-09-04) ---------------------------
# The corpus block is what an afternoon of semantic searches keeps hitting,
# and the API's default breakpoint is gone in five minutes.

def test_the_pinned_sdk_takes_an_extended_ttl():
    """`anthropic==0.122.0` carries `ttl` on the STABLE cache_control param,
    so no beta header and no `client.beta.*` call. The day a lockfile bump
    moves it, this says so rather than the bill doing."""
    param = pytest.importorskip(
        "anthropic.types.cache_control_ephemeral_param").CacheControlEphemeralParam
    assert "ttl" in getattr(param, "__annotations__", {})


def test_the_detector_downgrades_an_sdk_without_the_field(monkeypatch):
    class OldParam:
        __annotations__ = {"type": str}

    fake = types.ModuleType("anthropic.types.cache_control_ephemeral_param")
    fake.CacheControlEphemeralParam = OldParam
    anthropic_types = pytest.importorskip("anthropic.types")
    monkeypatch.setattr(anthropic_types, "cache_control_ephemeral_param", fake)
    cards_ai.sdk_cache_ttl.cache_clear()
    try:
        assert cards_ai.sdk_cache_ttl() == "5m"
    finally:
        cards_ai.sdk_cache_ttl.cache_clear()


def test_an_sdk_that_cannot_be_read_keeps_the_hour(monkeypatch):
    """Cannot tell is not "not supported": the field is passed through to an
    API that has had it for months, and a silent downgrade is money."""
    real_import = __import__("builtins").__import__

    def boom(name, *args, **kwargs):
        if "cache_control_ephemeral_param" in name:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", boom)
    cards_ai.sdk_cache_ttl.cache_clear()
    try:
        assert cards_ai.sdk_cache_ttl() == "1h"
    finally:
        cards_ai.sdk_cache_ttl.cache_clear()


def test_a_five_minute_fallback_is_todays_breakpoint_exactly():
    assert cards_ai._cache_control("5m") == {"type": "ephemeral"}
    assert cards_ai._cache_control("") == {"type": "ephemeral"}
    assert cards_ai._cache_control("1h") == {"type": "ephemeral", "ttl": "1h"}


def test_a_session_opened_under_five_minutes_is_not_mixed(sdk):
    """A conversation keeps the TTL it was opened under. The stored first
    message IS the breakpoint, so re-stamping it half way through would be a
    second cache write and a cold read of the corpus it replaced."""
    runner, calls = sdk
    runner.run(MARKED, session=FakeSession())
    path = store_file(runner)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["cache_ttl"] = "5m"
    stored["messages"][0]["content"][0]["cache_control"] = {"type": "ephemeral"}
    path.write_text(json.dumps(stored), encoding="utf-8")

    runner.run("more of the pangolins", session=FakeSession(turns=1))

    sent = calls[1]["messages"][0]["content"][0]
    assert sent["cache_control"] == {"type": "ephemeral"}
    assert json.loads(path.read_text(encoding="utf-8"))["cache_ttl"] == "5m"


def test_no_session_still_carries_no_breakpoint(sdk):
    """Translate, search and summaries without a session are one plain string
    -- an hour of caching is not a reason to start caching a one-shot call."""
    runner, calls = sdk
    runner.run("translate this", model="claude-haiku-4-5-20251001")
    assert calls[0]["messages"] == [{"role": "user", "content": "translate this"}]


def test_status_says_which_ttl_it_got(tmp_path, monkeypatch):
    choice = ai_providers.ProviderChoice(name=ai_providers.ANTHROPIC_API,
                                         label="Anthropic API", reason="")
    monkeypatch.setattr(cards_ai.Runner, "_choice",
                        lambda self, probe=True: (choice, ""))
    out = cards_ai.Runner(FakeSettings(tmp_path)).status()
    assert out["ok"] is True
    assert out["session_cache_ttl"] in ("1h", "5m")


def test_a_refused_status_still_names_the_ttl(tmp_path, monkeypatch, no_db):
    refused(monkeypatch)
    rows_as(monkeypatch, ai_providers.ST_DISABLED)
    out = cards_ai.Runner(FakeSettings(tmp_path)).status()
    assert out["ok"] is False
    assert out["session_cache_ttl"] in ("1h", "5m")
