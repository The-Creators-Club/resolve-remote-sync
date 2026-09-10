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
  * A MULTI-PART CORPUS IS CACHED TO ITS END (decision 7, 2026-09-07). Caching
    is prefix-based, so a breakpoint on turn 0 alone left an episode's parts
    2-N uncached for ever; the request carries up to three, and the STORED
    conversation still carries exactly one.
"""
from __future__ import annotations

import copy
import json
import types

import pytest

from ccsync_dashboard import ai_providers, cards_ai

CORPUS = "### pangolins [c1] FF5 -- the burrow (61.0s, speakers: A)\n0.0 3.2 hello"
MARKED = CORPUS + "\n\n" + cards_ai.INSTRUCTIONS_MARKER + "\n\ndescribe the montage"

HOUR = {"type": "ephemeral", "ttl": "1h"}

# What the API reports back. The numbers are not the assertion (the shape and
# the log line are), but they are the four fields the 2026-09-07 warm-search
# investigation had no way to read.
FAKE_USAGE = types.SimpleNamespace(input_tokens=4120, output_tokens=310,
                                   cache_read_input_tokens=98000,
                                   cache_creation_input_tokens=7100)


def part(n):
    """Corpus part `n` as the transcript search sends it: one marked prompt
    per turn, each its own user message (four of them on the live episode)."""
    return f"{CORPUS} part {n}\n\n{cards_ai.INSTRUCTIONS_MARKER}\n\nnoted, part {n}"


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
        return types.SimpleNamespace(content=[block], usage=FAKE_USAGE)


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
    assert messages[0]["content"][0]["cache_control"] == HOUR
    assert messages[1] == {"role": "assistant", "content": "an answer"}
    assert messages[2] == {"role": "user", "content": [
        {"type": "text", "text": "more of the pangolins",
         "cache_control": HOUR}]}


def test_a_later_turn_is_stamped_for_this_request_only(sdk):
    """Was `test_a_later_turn_is_not_a_second_cache_breakpoint`, inverted on
    2026-09-07 (warm transcript search 139 s: only turn 0 was under a
    breakpoint). This turn's message IS stamped on the way out, so the NEXT
    turn reads the whole conversation from cache instead of re-processing
    every earlier answer; the STORE still holds the plain string, so the
    breakpoint does not accumulate down the history."""
    runner, calls = sdk
    runner.run(MARKED, session=FakeSession())
    runner.run("more of the pangolins", session=FakeSession(turns=1))

    sent = calls[1]["messages"][2]["content"]
    assert sent == [{"type": "text", "text": "more of the pangolins",
                     "cache_control": HOUR}]
    stored = json.loads(store_file(runner).read_text(encoding="utf-8"))
    assert stored["messages"][2]["content"] == "more of the pangolins"


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
    """One BLOCK is the property; the stamp on it arrived 2026-09-07 with
    decision 7, because this message is also the final message of the
    request and every request stamps that."""
    runner, calls = sdk
    runner.run(prompt, session=FakeSession())

    content = calls[0]["messages"][0]["content"]
    assert content == [{"type": "text", "text": prompt, "cache_control": HOUR}]
    stored = json.loads(store_file(runner).read_text(encoding="utf-8"))
    assert stored["messages"][0]["content"] == [{"type": "text", "text": prompt}]


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
    assert cards_ai._says_no_such_session(
        "Error: Session ID 1b01ec70-0f0e-4b7a-9d1e-2c1f3a4b5c6d is already in use.")
    assert not cards_ai._says_no_such_session("Invalid API key")
    assert not cards_ai._says_no_such_session("command not found")
    assert not cards_ai._says_no_such_session("port 8899 is already in use")


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


# -- three breakpoints at SEND time (decision 7, 2026-09-07) ------------------
# Measured on the live NAS: the stored conversation for one episode is four
# corpus parts (68k, 89k, 97k, 67k chars) and a breakpoint on turn 0 alone, so
# 79% of the corpus and every earlier answer were re-processed uncached on
# every warm turn. A warm person search took 139 s.

def stamped(content):
    """The indexes of the blocks of one sent message carrying a breakpoint."""
    if isinstance(content, str):
        return []
    return [i for i, b in enumerate(content) if "cache_control" in b]


def marks_of(messages):
    """(message index, block index) of every breakpoint in one request."""
    return [(i, b) for i, m in enumerate(messages)
            for b in stamped(m["content"])]


def test_a_multi_part_corpus_is_stamped_first_last_and_now(sdk):
    runner, calls = sdk
    runner.run(part(1), session=FakeSession())
    runner.run(part(2), session=FakeSession(turns=1))
    runner.run(part(3), session=FakeSession(turns=2))
    out = runner.run("who mentions the burrow?", session=FakeSession(turns=3))

    assert out["ok"] is True
    messages = calls[3]["messages"]
    # user, assistant, user, assistant, user, assistant, user
    assert len(messages) == 7
    # Part 1's corpus block, part 3's corpus block, and this turn's query.
    assert marks_of(messages) == [(0, 0), (4, 0), (6, 0)]
    assert all(m["cache_control"] == HOUR
               for i, b in marks_of(messages)
               for m in [messages[i]["content"][b]])
    assert messages[4]["content"][0]["text"] == f"{CORPUS} part 3"
    assert messages[6]["content"] == [
        {"type": "text", "text": "who mentions the burrow?",
         "cache_control": HOUR}]


def test_each_opening_turn_moves_the_last_breakpoint_forward(sdk):
    """Corpus parts arrive one per turn, so at open turn k the last part IS
    part k: a read of the prefix already cached plus a write of the delta."""
    runner, calls = sdk
    runner.run(part(1), session=FakeSession())
    runner.run(part(2), session=FakeSession(turns=1))
    runner.run(part(3), session=FakeSession(turns=2))

    assert marks_of(calls[0]["messages"]) == [(0, 0)]
    assert marks_of(calls[1]["messages"]) == [(0, 0), (2, 0)]
    assert marks_of(calls[2]["messages"]) == [(0, 0), (4, 0)]


def test_the_store_keeps_one_stamp_and_the_two_block_shape(sdk):
    """Compatibility with sessions already open in the field (decision 6): the
    persisted breakpoint is turn 0's and nothing else. Every corpus part is
    stored SPLIT, which is what lets a later request find the parts again."""
    runner, _calls = sdk
    runner.run(part(1), session=FakeSession())
    runner.run(part(2), session=FakeSession(turns=1))
    runner.run(part(3), session=FakeSession(turns=2))
    runner.run("who mentions the burrow?", session=FakeSession(turns=3))

    stored = json.loads(store_file(runner).read_text(encoding="utf-8"))
    messages = stored["messages"]
    assert marks_of(messages) == [(0, 0)]
    assert messages[0]["content"][0]["cache_control"] == HOUR
    for i, n in ((0, 1), (2, 2), (4, 3)):
        assert messages[i]["content"] == [
            {"type": "text", "text": f"{CORPUS} part {n}",
             **({"cache_control": HOUR} if i == 0 else {})},
            {"type": "text", "text": f"noted, part {n}"},
        ]
    assert messages[6]["content"] == "who mentions the burrow?"


def test_a_one_part_corpus_is_two_breakpoints(sdk):
    """First == last, so the corpus takes ONE stamp, not two on the same
    block; the query takes the other."""
    runner, calls = sdk
    runner.run(MARKED, session=FakeSession())
    runner.run("who mentions the burrow?", session=FakeSession(turns=1))

    messages = calls[1]["messages"]
    assert marks_of(messages) == [(0, 0), (2, 0)]


def test_turn_zero_is_a_single_breakpoint(sdk):
    """First corpus part, last corpus part and the final message are all the
    same message on the opening turn."""
    runner, calls = sdk
    runner.run(MARKED, session=FakeSession())

    assert marks_of(calls[0]["messages"]) == [(0, 0)]


def test_a_five_minute_session_stamps_all_three_at_five_minutes(sdk):
    """The convo's OWN ttl drives every send-time stamp, not today's."""
    runner, calls = sdk
    runner.run(part(1), session=FakeSession())
    path = store_file(runner)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["cache_ttl"] = "5m"
    stored["messages"][0]["content"][0]["cache_control"] = {"type": "ephemeral"}
    path.write_text(json.dumps(stored), encoding="utf-8")

    runner.run(part(2), session=FakeSession(turns=1))

    messages = calls[1]["messages"]
    assert marks_of(messages) == [(0, 0), (2, 0)]
    assert all(messages[i]["content"][b]["cache_control"] == {"type": "ephemeral"}
               for i, b in marks_of(messages))


def test_the_send_stamps_never_reach_the_next_request(sdk):
    """Stamps b and c are for ONE request. If `_for_send` mutated the stored
    blocks, every turn would leave a breakpoint behind and the fourth would be
    over the API's limit of four."""
    runner, calls = sdk
    runner.run(part(1), session=FakeSession())
    for turn in range(1, 8):
        runner.run(f"turn {turn}", session=FakeSession(turns=turn))

    for call in calls:
        assert len(marks_of(call["messages"])) <= 3
    stored = json.loads(store_file(runner).read_text(encoding="utf-8"))
    assert marks_of(stored["messages"]) == [(0, 0)]


def test_a_session_free_call_still_carries_no_breakpoint(sdk):
    """Translate, search and summaries without a session are one plain string.
    `_for_send` is only reached with a conversation."""
    runner, calls = sdk
    runner.run(MARKED, model="claude-haiku-4-5-20251001")
    assert calls[0]["messages"] == [{"role": "user", "content": MARKED}]


# -- what the call cost (2026-09-07) -----------------------------------------
# `_sdk` threw `response.usage` away, so the 139 s warm search could not be
# told from a cold one anywhere but the bill.

def test_the_usage_is_logged_and_returned(sdk, caplog):
    runner, _calls = sdk
    with caplog.at_level("INFO", logger="ccsync.dashboard.cards"):
        out = runner.run(MARKED, model="claude-sonnet-5", session=FakeSession())

    assert out["usage"] == {"input_tokens": 4120, "output_tokens": 310,
                            "cache_read_input_tokens": 98000,
                            "cache_creation_input_tokens": 7100}
    lines = [r.getMessage() for r in caplog.records
             if r.getMessage().startswith("Timeline Cards AI:")]
    assert len(lines) == 1
    assert "model=claude-sonnet-5" in lines[0]
    assert "in=4120 cache_read=98000 cache_write=7100 out=310" in lines[0]


def test_a_response_without_usage_reads_as_zeros(sdk, monkeypatch):
    """A stub, an older SDK or a streamed shape must not raise on the way back
    from a call that already succeeded."""
    assert cards_ai._usage_of(types.SimpleNamespace()) == {
        "input_tokens": 0, "output_tokens": 0,
        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


def test_the_cli_path_reports_no_usage(sdk, monkeypatch):
    """Only the SDK path can count tokens; the CLI answers with text alone."""
    runner, _calls = sdk
    choice = ai_providers.ProviderChoice(name=ai_providers.CLAUDE_CODE,
                                         label="Claude Code", reason="")
    monkeypatch.setattr(cards_ai.Runner, "_choice",
                        lambda self, probe=True: (choice, ""))
    monkeypatch.setattr(
        cards_ai.Runner, "_cli",
        # `model=` since 2026-09-10: `run()` passes it on this path too.
        lambda self, prompt, timeout, session=None, model="": "an answer")

    out = runner.run("translate this")
    assert out["ok"] is True
    assert out["usage"] == {}


# -- the CLI argv (2026-09-10) ------------------------------------------------
# The chat asks for `claude-fable-5-1`, and until this date `_cli` built its
# argv out of the flags and the session alone: on the studio's Claude Code
# provider every Timeline Cards feature silently ran on the CLI's default
# model. These pin the flag's presence, its POSITION and its absence.

class FakeProc:
    def __init__(self, stdout="an answer"):
        self.returncode = 0
        self.stdout = stdout
        self.stderr = ""


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """A Runner whose provider is Claude Code and whose subprocess is a
    recorder. Returns `(runner, argvs)`."""
    argvs: list[list[str]] = []

    def fake_run(argv, **kwargs):
        argvs.append(list(argv))
        return FakeProc()

    choice = ai_providers.ProviderChoice(name=ai_providers.CLAUDE_CODE,
                                         label="Claude Code", reason="")
    monkeypatch.setattr(cards_ai.Runner, "_choice",
                        lambda self, probe=True: (choice, ""))
    monkeypatch.setattr(cards_ai.Runner, "_cli_path",
                        lambda self: "/data/tools/claude-code/bin/claude")
    monkeypatch.setattr(cards_ai.cli_tools, "cli_env",
                        lambda settings, name: {"HOME": "/data/tools/x/home"})
    monkeypatch.setattr(cards_ai.subprocess, "run", fake_run)
    monkeypatch.delenv("YTDL_CLAUDE_CODE_ARGS", raising=False)
    return cards_ai.Runner(FakeSettings(tmp_path)), argvs


def test_the_cli_is_told_which_model(cli):
    runner, argvs = cli
    out = runner.run("stage the pangolin cards", model="claude-fable-5-1")
    assert out["ok"] is True
    assert argvs[0] == ["/data/tools/claude-code/bin/claude", "-p",
                        "--output-format", "text",
                        "--model", "claude-fable-5-1"]


def test_the_model_follows_the_flags_and_precedes_the_session(cli):
    """Position, not just presence: `--session-id` takes the id after it, so a
    `--model` wedged between the two would hand the CLI the wrong value."""
    runner, argvs = cli
    runner.run(MARKED, model="claude-fable-5-1", session=FakeSession())
    argv = argvs[0]
    assert argv[argv.index("--output-format") + 1] == "text"
    assert argv[argv.index("--model") + 1] == "claude-fable-5-1"
    assert argv.index("--model") < argv.index("--session-id")
    assert argv[argv.index("--session-id") + 1] == "1a2b-3c4d"


def test_a_warm_session_keeps_the_model_before_resume(cli):
    runner, argvs = cli
    # Turn 0 first: a `turns > 0` id this store has never seen is
    # `session_lost` and never reaches an argv at all (decision 5).
    session = FakeSession()
    runner.run(MARKED, model="claude-opus-5", session=session)
    session.turns = 4
    runner.run("and again", model="claude-opus-5", session=session)
    argv = argvs[-1]
    assert argv.index("--model") < argv.index("--resume")
    assert argv[-2:] == ["--resume", "1a2b-3c4d"]


def test_no_model_is_the_clis_own_default(cli):
    """Translate, search and summaries called this door for a year without a
    model on the CLI path. An empty name must stay "whatever the CLI is signed
    in to run", never a name this module invents."""
    runner, argvs = cli
    runner.run("summarise this section")
    assert "--model" not in argvs[0]
    assert argvs[0] == ["/data/tools/claude-code/bin/claude", "-p",
                        "--output-format", "text"]


def test_the_sdk_path_is_unchanged_by_the_model_flag(sdk):
    """The API door already honoured `model`, and nothing about 2026-09-10
    touched it: the model is a field of the request, not an argv."""
    runner, calls = sdk
    runner.run("stage the pangolin cards", model="claude-fable-5-1")
    assert calls[0]["model"] == "claude-fable-5-1"
    assert calls[0]["messages"] == [{"role": "user",
                                     "content": "stage the pangolin cards"}]


# -- a consumed id is a lost session (CR-230, 2026-09-10) ---------------------
# The live shape: turn 0 under a fresh `--session-id` failed for an unrelated
# reason (a CLI too old for `--model`) and the id was consumed anyway, so every
# later turn came back "Session ID ... is already in use" and the chat, the
# transcript search and the montage never re-opened.

def fails_with(monkeypatch, stderr, code=1):
    def fake_run(argv, **kwargs):
        return types.SimpleNamespace(returncode=code, stdout="", stderr=stderr)

    monkeypatch.setattr(cards_ai.subprocess, "run", fake_run)


def test_an_id_already_in_use_is_session_lost(cli, monkeypatch):
    runner, _ = cli
    fails_with(monkeypatch, "Error: Session ID 1b01ec70-0f0e-4b7a-9d1e-2c1f "
                            "is already in use.")

    out = runner.run(MARKED, session=FakeSession())

    assert out["ok"] is False
    assert out["error"] == cards_ai.SESSION_LOST


def test_an_unrelated_cli_failure_keeps_its_own_words(cli, monkeypatch):
    """The narrowness is the point: `session_lost` makes the caller re-send a
    whole corpus, so anything that is not "that id is no good" must arrive as
    itself."""
    runner, _ = cli
    fails_with(monkeypatch, "error: unknown option '--model'")

    out = runner.run(MARKED, session=FakeSession())

    assert out["ok"] is False
    assert out["error"] != cards_ai.SESSION_LOST
    assert "--model" in out["error"]
