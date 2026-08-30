"""Timeline Cards' three Claude features, run through `ai_providers`.

docs/TIMELINE-CARDS-INTO-CCSYNC.md decision 7.6 and §7d (2026-08-30). The
features are the exact `->EN` translations, the transcript's semantic search
and the overview's section summaries. In the standalone container each is a
`claude -p` SUBPROCESS of the server, with node 22 and a pinned
`@anthropic-ai/claude-code` baked into the image and a `CARDS_CLAUDE_OAUTH_TOKEN`
to sign it in (its `deploy/Dockerfile`). THIS container bundles neither, on
purpose: `dashboard/deploy/run.sh` removed `/opt/claude` because "the AI calls
use the anthropic SDK with the customer's ANTHROPIC_API_KEY, so there is no
subprocess, no binary to put on PATH, and no need for a writable HOME"
(COMMERCIAL_READINESS.md item 1).

So the mount injects `engine.claude_runner`, and this is what it injects: one
object with `run()` and `status()`, over the same chain the YouTube
downloader's two AI calls use -- the site's `ANTHROPIC_API_KEY` through the
SDK, or the customer's own Claude Code CLI when `[features] ai_cli_providers`
is on and `cli_tools` has fetched one.

FIVE DECISIONS, each of which is a whole class of bug or a policy:

1. **Claude, or nothing.** The chain can resolve to Codex, OpenAI or
   DeepSeek. Timeline Cards passes MODEL NAMES (`claude-haiku-4-5-20251001`,
   `claude-sonnet-5`) and prompts written against them, so a resolved
   provider that is not one of the two Claude ones is refused with a sentence
   naming what the site chose -- not silently answered by a model nobody
   picked for this.
2. **THE MODEL NEVER GETS FILE TOOLS.** `_run_claude_json` on the other side
   is an "agentic run expected to write JSON to `out`". Here the JSON comes
   back as the REPLY and THIS process writes the file. An agent binary with
   filesystem tools inside a container that mounts the vault read-write and
   the whole Projects tree is exactly what item 1 took out of this image, and
   nothing about a translation needs it back. A CLI that wrote the file
   anyway is still honoured, because it costs one `os.path.exists`.
3. **The prompt gets one added line when `json_out` is set** -- see
   `JSON_REPLY_NOTE`. The caller cannot know which provider it got, and the
   provider decides whether "write the file" is even possible.
4. **Failures are a shape, never an exception across the seam.** `run()`
   returns `{ok: False, error: "<sentence>"}` and the engine raises its own
   `RuntimeError` from it, so the page shows the same error line it always
   has. A traceback from a dashboard module inside a Timeline Cards worker
   thread would land in the shared error line as a class name.
5. **A montage is ONE conversation, and this side owns the store.**
   MONTAGE-BUILDER-PLAN.md §12 (2026-08-30): describe, revise and search all
   read the same corpus digest, and re-sending it per call was minutes and
   dollars per montage. With `session=` the runner keeps the messages under
   `<data>/cards_sessions/<id>.json` and puts a `cache_control` breakpoint on
   the corpus block, so turn 2 onward is a cache HIT rather than a re-read.
   The caller owns the id and the turn count; this owns the transcript. A
   `turns > 0` whose id this store has never seen (a moved or cleared data
   dir, a sidecar carried to another machine, a session the CLI door opened
   on the PC) is `session_lost`, once, with no retry: only the caller knows
   whether re-reading the corpus is worth it.

   `session is None` is byte for byte the call this module made before §12,
   because that is what the three original features (translate, search,
   summaries) still make.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from . import ai_providers, cli_tools

log = logging.getLogger("ccsync.dashboard.cards")

# The two providers whose model names Timeline Cards speaks.
CLAUDE_PROVIDERS = (ai_providers.CLAUDE_CODE, ai_providers.ANTHROPIC_API)

# Generous, and a ceiling rather than a target: one translation chunk is
# fifty captions of bilingual JSON, and a truncated answer is unparseable
# JSON, which reads to the page as "the translator returned no JSON".
MAX_TOKENS = 16000
# What the standalone server's `_run_claude` defaults to.
DEFAULT_TIMEOUT = 900.0

JSON_REPLY_NOTE = (
    "\n\nOUTPUT: reply with the JSON object alone -- no prose before or "
    "after it, no code fence. (If you have file tools you may also write it "
    "to {path}; the reply is what is read.)\n"
)

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)

# -- the session store -------------------------------------------------------
#
# THE MARKER IS THE CONTRACT (§12, 2026-08-30). The door hands this runner one
# prompt string, and a cache breakpoint needs two blocks: what is worth caching
# (the corpus digest, tens of thousands of tokens, identical on every turn of a
# montage) and what is not (this turn's instruction). So turn 0's prompt is
# split at the LAST line that is exactly `---INSTRUCTIONS---`: everything
# before it is the cached block, everything after it is the instruction. No
# marker means one uncached block, which is every caller that predates §12.
INSTRUCTIONS_MARKER = "---INSTRUCTIONS---"
_MARKER_RE = re.compile(r"^" + re.escape(INSTRUCTIONS_MARKER) + r"[ \t]*$", re.M)

# The one error string every caller matches on (§12.2). Never a sentence: the
# CALLER decides what to say and whether to re-open with the corpus.
SESSION_LOST = "session_lost"

# How much of a conversation is kept. A montage is a handful of describes and
# a dozen searches; a page left open for a week is not a reason to send a
# megabyte of history. The first turn is NEVER trimmed -- it is the corpus,
# and it is the cached block, so dropping it would cost both the context and
# the cache hit.
MAX_TURNS = 40


class ClaudeError(RuntimeError):
    """Never crosses the seam; `run()` turns it into `{ok: False, error}`."""


class Runner:
    """`engine.claude_runner`: the object the cards engine calls.

    Callable as well as `.run(...)`, because the smallest possible seam on
    the other side is `self.claude_runner(prompt, model=...)` and the
    smallest possible seam is what a repo boundary should ask for.
    """

    def __init__(self, settings: Any) -> None:
        self._settings = settings

    # -- what Timeline Cards calls ----------------------------------------

    def run(self, prompt: str, model: str = "", timeout: float = DEFAULT_TIMEOUT,
            think: bool = True, json_out: str = "",
            session: Any = None) -> dict[str, Any]:
        """One call. -> {ok, text, data, provider, error}.

        `think` is accepted and ignored on the API path (the SDK call is made
        with `effort: low`, which is what `MAX_THINKING_TOKENS=0` was buying
        on the other side) and passed to nothing on the CLI path. It is in
        the signature so the caller's two call sites do not have to know
        which provider answered.

        With `json_out`, `data` is the parsed object AND the file has been
        written -- both, so `_run_claude_json`'s callers can keep reading the
        file and the caller that wants the object does not have to re-read it.

        `session` is duck-typed (`id`, `turns`, `corpus_hash`) so this module
        never imports the fork. `turns == 0` opens a conversation under
        `session.id`, `turns > 0` appends to it, and an id this store does not
        have is `{"ok": False, "error": "session_lost"}` -- see decision 5.
        The caller owns `turns`; nothing here writes back to the object.
        """
        try:
            choice, conn_detail = self._choice()
        except Exception as e:  # noqa: BLE001
            return _fail(f"the dashboard could not resolve an AI provider "
                         f"({type(e).__name__}: {e})")
        if not choice.ok:
            return _fail(choice.reason or conn_detail)
        if choice.name not in CLAUDE_PROVIDERS:
            return _fail(
                f"this site's AI provider is {choice.label}, and Timeline "
                f"Cards' translate, semantic search and summaries are written "
                f"for Claude. Set an ANTHROPIC_API_KEY (Settings -> AI "
                f"providers), or pin Claude.")
        text = ""
        if json_out:
            prompt = prompt + JSON_REPLY_NOTE.format(path=json_out)
        convo = None
        if session is not None:
            sid = str(getattr(session, "id", "") or "")
            try:
                turns = int(getattr(session, "turns", 0) or 0)
            except (TypeError, ValueError):
                turns = 0
            if not sid:
                return _fail("this montage session has no id", provider=choice.name)
            convo = self._open_convo(sid, turns, getattr(session, "corpus_hash", ""))
            if convo is None:
                return _fail(SESSION_LOST, provider=choice.name)
            convo["messages"].append(_user_message(prompt, first=turns == 0))
        try:
            if choice.name == ai_providers.ANTHROPIC_API:
                text = self._sdk(prompt, model, timeout,
                                 messages=None if convo is None else convo["messages"])
            else:
                text = self._cli(prompt, timeout, session=session)
        except ClaudeError as e:
            return _fail(str(e), provider=choice.name)
        except Exception as e:  # noqa: BLE001 - never a traceback across the seam
            log.exception("the Timeline Cards AI call failed")
            return _fail(f"{type(e).__name__}: {e}", provider=choice.name)
        if convo is not None:
            # After the answer, never before: a call that failed must leave
            # the stored conversation exactly as the caller can retry against,
            # not holding a user message Claude never saw.
            convo["messages"].append({"role": "assistant", "content": text})
            convo["turns"] = int(convo.get("turns") or 0) + 1
            self._save_convo(convo)
        out: dict[str, Any] = {"ok": True, "text": text, "data": None,
                               "provider": choice.name, "error": ""}
        if json_out:
            try:
                out["data"] = self._land_json(text, json_out)
            except ClaudeError as e:
                return _fail(str(e), provider=choice.name)
        return out

    __call__ = run

    def status(self) -> dict[str, Any]:
        """`{"ok": bool, "why": str}` -- the shape `claude_status()` has, so
        the page's dimmed buttons and their tooltip need no change at all.

        NEVER PROBES. This is read on every state publish and the CLI probe
        is a real one-token call behind a 600 s cache; a page poll must not
        be the thing that spends a subscription.
        """
        try:
            choice, detail = self._choice(probe=False)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "why": f"the dashboard could not resolve an AI "
                                        f"provider ({type(e).__name__}: {e})"}
        if not choice.ok:
            return {"ok": False, "why": choice.reason or detail}
        if choice.name not in CLAUDE_PROVIDERS:
            return {"ok": False, "why": f"this site's AI provider is "
                                        f"{choice.label}, not Claude"}
        return {"ok": True, "why": ""}

    # -- the two backends --------------------------------------------------

    def _choice(self, probe: bool = True):
        from . import db as dbmod

        conn = dbmod.connect(self._settings.db_path)
        try:
            return (ai_providers.resolved(conn, self._settings, probe=probe),
                    "no provider has a working credential")
        finally:
            conn.close()

    def _sdk(self, prompt: str, model: str, timeout: float,
             messages: list[dict[str, Any]] | None = None) -> str:
        key = self._key()
        if not key:
            raise ClaudeError("no ANTHROPIC_API_KEY is set for this site "
                              "(Settings -> AI providers)")
        try:
            import anthropic
        except ImportError as e:
            raise ClaudeError(f"the `anthropic` SDK is not installed in this "
                              f"container ({e})") from None
        client = anthropic.Anthropic(api_key=key)
        try:
            response = client.with_options(timeout=float(timeout)).messages.create(
                model=model or "",
                max_tokens=MAX_TOKENS,
                # As the ytdl app's two calls do, and for the same reason:
                # these are structured judgements over a list, not reasoning
                # problems, and a customer pays per token for them. It is
                # also what `MAX_THINKING_TOKENS=0` bought Timeline Cards --
                # measured there at 54.0 s/$0.048 against 7.0 s/$0.019 on one
                # translation chunk.
                output_config={"effort": "low"},
                messages=(messages if messages is not None
                          else [{"role": "user", "content": prompt}]),
            )
        except Exception as e:  # noqa: BLE001 - classified by its message
            raise ClaudeError(_sdk_detail(e, model)) from None
        return _text_of(response)

    def _cli(self, prompt: str, timeout: float, session: Any = None) -> str:
        path = self._cli_path()
        if not path:
            raise ClaudeError("Claude Code is the site's provider but this "
                              "container has no such executable")
        env = cli_tools.cli_env(self._settings, ai_providers.CLAUDE_CODE)
        # The CLI keeps its OWN conversation store, keyed by the id we hand
        # it, so a session on this path is `--session-id` then `--resume`
        # (§12.2) and never our transcript re-sent as text. Our store is
        # still what answers "has this id ever existed", because the CLI's
        # lives in a HOME this container may not even have.
        argv = [path] + _cli_args() + _cli_session_args(session)
        try:
            proc = subprocess.run(  # noqa: S603 - argv, never a shell
                argv, input=prompt, capture_output=True, text=True,
                timeout=float(timeout), env=env,
                # The data root, never the vault: whatever the CLI decides to
                # read or write relative to its working directory must not
                # land in somebody's episode.
                cwd=str(_scratch_dir(self._settings)),
            )
        except subprocess.TimeoutExpired:
            raise ClaudeError(f"Claude Code did not answer within "
                              f"{float(timeout):.0f}s") from None
        except (OSError, ValueError) as e:
            raise ClaudeError(f"could not run Claude Code ({type(e).__name__}: "
                              f"{str(e)[:160]})") from None
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:300]
            if session is not None and _says_no_such_session(detail):
                raise ClaudeError(SESSION_LOST)
            raise ClaudeError(f"Claude Code exited {proc.returncode}: {detail}")
        return proc.stdout or ""

    def _cli_path(self) -> str:
        """Where the CLI is, by `ai_providers`' own three-step answer: the
        path an admin typed, then the one the SET UP wizard installed, then
        PATH. Its own connection, opened and closed here: this runs on a
        Timeline Cards WORKER THREAD, which has no request and therefore no
        `Depends(get_conn)` -- and a connection shared with that thread is
        how a "database is locked" appears under a translation."""
        from . import db as dbmod

        conn = dbmod.connect(self._settings.db_path)
        try:
            return ai_providers.cli_path(conn, ai_providers.CLAUDE_CODE,
                                         self._settings)
        finally:
            conn.close()

    def _key(self) -> str:
        return ai_providers.read_key(self._settings, ai_providers.ANTHROPIC_API)[0]

    # -- the conversation store --------------------------------------------

    def _open_convo(self, sid: str, turns: int,
                    corpus_hash: Any) -> dict[str, Any] | None:
        """The stored conversation to append this turn to, or None -> lost.

        `turns == 0` is "open a montage": it REPLACES whatever is under that
        id, because the caller is about to send the corpus again and a half
        conversation under a re-used id would be sent as history nobody
        asked for.
        """
        if turns <= 0:
            return {"id": sid, "created": _now_iso(), "turns": 0,
                    "corpus_hash": str(corpus_hash or ""), "messages": []}
        convo = _read_convo(_session_path(self._settings, sid))
        if convo is None:
            log.info("the Timeline Cards montage session %s is not in this "
                     "store; answering session_lost", sid)
            return None
        if corpus_hash:
            convo["corpus_hash"] = str(corpus_hash)
        return convo

    def _save_convo(self, convo: dict[str, Any]) -> None:
        convo["messages"] = _trimmed(convo.get("messages") or [])
        path = _session_path(self._settings, str(convo.get("id") or ""))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(str(path) + ".partial")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(convo, fh, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as e:
            # NEVER fatal: the model answered, and the answer is what the
            # page is waiting for. The next turn will be a session_lost the
            # caller already knows how to recover from.
            log.warning("the Timeline Cards montage session %s could not be "
                        "written (%s)", convo.get("id"), e)

    # -- the JSON contract -------------------------------------------------

    def _land_json(self, text: str, path: str) -> Any:
        """The object, and the file on disk. See decision 2.

        A file the CLI wrote itself wins, because it is the one the model
        meant; anything else comes out of the reply. `utf-8-sig` on the read
        for the same reason `_run_claude_json` uses it -- a BOM is what a
        Windows-side tool leaves behind.
        """
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8-sig") as fh:
                    return json.load(fh)
            except (OSError, ValueError):
                pass
        match = _JSON_BLOCK.search(text or "")
        if not match:
            raise ClaudeError("the model returned no JSON: "
                              + (text or "").strip()[-300:])
        try:
            data = json.loads(match.group(0))
        except ValueError:
            raise ClaudeError("the model returned unparsable JSON: "
                              + match.group(0)[-300:]) from None
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp = path + ".partial"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as e:
            raise ClaudeError(f"the model's answer could not be written to "
                              f"{path} ({e})") from None
        return data


# ------------------------------------------------------------------ helpers

def _fail(why: str, provider: str = "") -> dict[str, Any]:
    return {"ok": False, "text": "", "data": None, "provider": provider,
            "error": str(why)}


def _cli_args() -> list[str]:
    """The non-interactive flags, from the same env var the ytdl app and the
    Settings probe read -- one correction fixes all three."""
    import shlex

    raw = os.environ.get("YTDL_CLAUDE_CODE_ARGS", "").strip()
    return shlex.split(raw) if raw else ["-p", "--output-format", "text"]


def _cli_session_args(session: Any) -> list[str]:
    sid = str(getattr(session, "id", "") or "") if session is not None else ""
    if not sid:
        return []
    try:
        turns = int(getattr(session, "turns", 0) or 0)
    except (TypeError, ValueError):
        turns = 0
    return ["--resume", sid] if turns > 0 else ["--session-id", sid]


def _says_no_such_session(detail: str) -> bool:
    """Is this CLI failure "I have never heard of that session"?

    Narrow on purpose: `session_lost` makes the caller re-send a corpus, and
    a timeout or a signed-out CLI misread as one would do that on every turn
    for ever. Anything not matched keeps its own stderr in the error line.
    """
    low = (detail or "").lower()
    return ("session" in low
            and ("no conversation found" in low or "not found" in low
                 or "does not exist" in low or "no such session" in low))


def _user_message(prompt: str, first: bool) -> dict[str, Any]:
    """This turn's user message. Turn 0 is the only one that is worth caching.

    A cache breakpoint is billed per write, so it goes on the corpus and
    nowhere else; every later turn is a sentence.
    """
    if not first:
        return {"role": "user", "content": prompt}
    corpus, instruction = split_prompt(prompt)
    if not corpus:
        return {"role": "user", "content": [{"type": "text", "text": prompt}]}
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": corpus,
         "cache_control": {"type": "ephemeral"}},
    ]
    if instruction:
        blocks.append({"type": "text", "text": instruction})
    return {"role": "user", "content": blocks}


def split_prompt(prompt: str) -> tuple[str, str]:
    """(cacheable corpus, this turn's instruction) at `---INSTRUCTIONS---`.

    ("", prompt) when the marker is absent, so a caller that predates §12 is
    one uncached block. The LAST marker wins: a corpus digest is transcript
    text and may well contain the line itself.
    """
    matches = list(_MARKER_RE.finditer(prompt or ""))
    if not matches:
        return "", prompt or ""
    last = matches[-1]
    corpus = (prompt[:last.start()]).rstrip("\n")
    instruction = (prompt[last.end():]).lstrip("\n")
    if not corpus.strip() or not instruction.strip():
        return "", prompt or ""
    return corpus, instruction


def _trimmed(messages: list[Any]) -> list[Any]:
    """The first turn plus the last MAX_TURNS - 1, in whole turns.

    Whole PAIRS, so the history stays user/assistant/user/assistant: the
    first turn (the corpus and its reply) is kept, and the cut is made after
    it. Slicing by message would sooner or later leave two user messages
    against each other.
    """
    if len(messages) <= MAX_TURNS * 2:
        return list(messages)
    keep = (MAX_TURNS - 1) * 2
    return list(messages[:2]) + list(messages[-keep:])


def _session_path(settings: Any, sid: str) -> Path:
    return _sessions_dir(settings) / (_safe_id(sid) + ".json")


def _sessions_dir(settings: Any) -> Path:
    return Path(str(getattr(settings, "db_path", "") or ".")).parent / "cards_sessions"


def _safe_id(sid: str) -> str:
    """A file name, never a path. The id is a uuid from the fork's sidecar,
    which is a file anyone with the vault can edit."""
    clean = re.sub(r"[^A-Za-z0-9_-]", "-", str(sid or ""))[:80]
    return clean or "unnamed"


def _read_convo(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        return None
    return data


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _scratch_dir(settings: Any):
    root = Path(str(getattr(settings, "db_path", "") or ".")).parent / "cards"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return Path(".")
    return root


def _text_of(response: Any) -> str:
    out = []
    for block in getattr(response, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            out.append(str(text))
    return "".join(out)


def _sdk_detail(exc: Exception, model: str) -> str:
    """One sentence an admin can act on, with the MODEL in it.

    Timeline Cards names its own models (`claude-haiku-4-5-20251001`,
    `claude-sonnet-5`); a key that may not call one of them, or a name this
    API does not know, is otherwise a bare `NotFoundError` in a worker thread.
    """
    name = type(exc).__name__
    body = str(exc)[:300]
    if "Authentication" in name or "PermissionDenied" in name:
        return (f"the site's ANTHROPIC_API_KEY was refused for model "
                f"{model or '(unset)'}: {body}")
    if "NotFound" in name:
        return f"this API does not know the model {model or '(unset)'}: {body}"
    if "Timeout" in name:
        return "Claude did not answer in time"
    return f"{name}: {body}"


def make_runner(settings: Any) -> Runner:
    """What `cards.build_engine` injects. Cheap: it opens nothing."""
    return Runner(settings)


def status(settings: Any) -> dict[str, Any]:
    """The health line's `claude` block. Never raises, never probes."""
    try:
        return make_runner(settings).status()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "why": f"{type(e).__name__}: {e}"}
