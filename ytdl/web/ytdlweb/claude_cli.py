"""Headless `claude -p` wrapper: the two AI calls, and how they fail.

Claude Code runs on the server under the operator's own account (a one-time
`/login` writes credentials into the claude-home volume -- DEPLOY.md). This
module is the only thing that shells out to it.

Three decisions worth keeping:

**HOME/CLAUDE_CONFIG_DIR are set in the SUBPROCESS ENV ONLY.** uid 3000 has no
passwd entry in the slim image, so `claude` cannot find a home to read its
credentials from and refuses to start. Exporting HOME globally in run.sh would
fix that and break everything else in the container that reads it (the
dashboard's own data paths, ffmpeg's cache). `cwd` is the ytdl data root for
the same reason: claude writes project state next to where it is run, and that
is the one directory this app owns.

**`--disallowed-tools "*"`.** These prompts want text back, nothing else. The
container has the Projects tree mounted rw; an agent that decided to be helpful
with a Bash tool call in there is not a risk worth carrying for a translation.

**Errors are classified, not stringified.** `jobs.error` carries one of four
machine-readable prefixes (claude_auth:, claude_missing:, claude_timeout:,
claude_output:) that the SPA maps to ops hint text -- "an admin must run the
one-time login" is a completely different call to action from "the model
returned something unparseable", and an editor staring at a raw stderr dump
cannot tell them apart.
"""
import json
import logging
import os
import re
import subprocess
import threading
import time

from ytdlweb import config

log = logging.getLogger(__name__)

# The four prefixes. They are part of the contract with the SPA (app.js
# HINTS) -- change one and the hint text stops appearing.
ERR_AUTH = 'claude_auth:'
ERR_MISSING = 'claude_missing:'
ERR_TIMEOUT = 'claude_timeout:'
ERR_OUTPUT = 'claude_output:'

# What a not-logged-in claude says, in the shapes it has said it. Matched
# case-insensitively against stderr AND the result text, because the CLI
# reports an expired OAuth token on stdout inside a success-shaped envelope
# often enough that only checking the exit code would call it a parse failure.
_AUTH_RE = re.compile(
    r'(?:/login|please log ?in|not logged ?in|log in to|unauthori[sz]ed|'
    r'authentication|invalid api key|oauth|credentials? (?:not )?found|'
    r'no valid credentials|session (?:has )?expired)', re.I)


class ClaudeError(RuntimeError):
    """A failed claude call, already classified.

    `str(exc)` is written straight into jobs.error and shown verbatim in the
    UI, so it always starts with one of the four prefixes above.
    """

    def __init__(self, prefix, detail):
        self.prefix = prefix
        self.detail = str(detail)[:600]
        super().__init__(f'{prefix} {self.detail}')


def _env():
    """The subprocess environment. See the module docstring for why it is here
    and not in run.sh."""
    env = dict(os.environ)
    home = config.CLAUDE_HOME
    if home:
        env['HOME'] = home
        env['CLAUDE_CONFIG_DIR'] = os.path.join(home, '.claude')
    return env


def _cwd():
    """Run claude in the one directory this app owns and can write."""
    root = config.DATA_ROOT
    return str(root) if root.is_dir() else None


def _strip_fences(text):
    """Pull the JSON out of a ```json fenced block if the model used one.

    It is told not to, and it usually does not, but "usually" is not a contract
    and re-prompting costs 30 seconds.
    """
    t = (text or '').strip()
    if t.startswith('```'):
        t = re.sub(r'^```[a-zA-Z]*\s*', '', t)
        t = re.sub(r'\s*```$', '', t).strip()
    # Some replies wrap the object in a sentence; take the outermost braces.
    if not t.startswith('{'):
        i, j = t.find('{'), t.rfind('}')
        if i != -1 and j > i:
            t = t[i:j + 1]
    return t


def _invoke(prompt, timeout=None):
    """Run `claude -p` once. -> the model's TEXT. Raises ClaudeError.

    The envelope (`--output-format json`) is the CLI's own wrapper, not the
    model's answer: it carries is_error/subtype/cost and the answer in
    `result`. A CLI old enough not to produce one still works -- stdout is then
    treated as the text itself.
    """
    cmd = [config.CLAUDE_BIN, '-p', prompt,
           '--output-format', 'json',
           '--model', config.CLAUDE_MODEL,
           # No shell here, so the quotes around * in the docs are the shell's
           # job and must NOT be part of the argument.
           '--disallowed-tools', '*']
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding='utf-8', errors='replace',
                              timeout=timeout or config.CLAUDE_TIMEOUT,
                              env=_env(), cwd=_cwd())
    except FileNotFoundError:
        raise ClaudeError(ERR_MISSING,
                          f'the `{config.CLAUDE_BIN}` CLI is not on PATH in this '
                          'container. See ytdl/web/DEPLOY.md.') from None
    except subprocess.TimeoutExpired:
        raise ClaudeError(ERR_TIMEOUT,
                          f'claude did not answer within '
                          f'{timeout or config.CLAUDE_TIMEOUT}s.') from None
    except OSError as exc:
        raise ClaudeError(ERR_MISSING, f'could not run claude: {exc}') from None

    out = (proc.stdout or '').strip()
    err = (proc.stderr or '').strip()

    if proc.returncode != 0:
        blob = f'{err}\n{out}'
        if _AUTH_RE.search(blob):
            raise ClaudeError(ERR_AUTH, _auth_detail(err or out))
        raise ClaudeError(ERR_OUTPUT,
                          f'claude exited {proc.returncode}: {(err or out)[:300]}')

    text = out
    try:
        envelope = json.loads(out)
    except ValueError:
        envelope = None
    if isinstance(envelope, dict) and 'result' in envelope:
        text = envelope.get('result') or ''
        if envelope.get('is_error'):
            if _AUTH_RE.search(f'{text} {err}'):
                raise ClaudeError(ERR_AUTH, _auth_detail(text or err))
            raise ClaudeError(ERR_OUTPUT, f'claude reported an error: {text[:300]}')

    if not text.strip():
        raise ClaudeError(ERR_OUTPUT, 'claude returned an empty response')
    # A logged-out CLI can answer 0 with prose telling you to log in.
    if _AUTH_RE.search(text) and '{' not in text:
        raise ClaudeError(ERR_AUTH, _auth_detail(text))
    return text


def _auth_detail(raw):
    return ('claude is not logged in on the server. An admin must run the '
            'one-time login (ytdl/web/DEPLOY.md) -- until then no job can '
            'generate search terms. [' + ' '.join(str(raw).split())[:160] + ']')


def ask_json(prompt, timeout=None, retries=1):
    """`claude -p` -> a parsed JSON object. One retry on unusable output.

    The retry is for the output shape only. An auth failure, a missing binary
    or a timeout are all re-tried into the same answer 180 seconds later, so
    they are raised immediately.
    """
    last = None
    for attempt in range(retries + 1):
        text = _invoke(prompt, timeout)
        try:
            data = json.loads(_strip_fences(text))
        except ValueError as exc:
            last = ClaudeError(ERR_OUTPUT,
                               f'could not parse the reply as JSON ({exc}): '
                               f'{text[:200]}')
            log.warning('claude returned unparseable JSON (attempt %d): %s',
                        attempt + 1, text[:200])
            continue
        if not isinstance(data, dict):
            last = ClaudeError(ERR_OUTPUT,
                               f'expected a JSON object, got {type(data).__name__}')
            continue
        return data
    raise last


# ------------------------------------------------------------- call #1: terms

_TERM_PROMPT = """\
You are helping a documentary editor find archive/b-roll footage on YouTube.

TOPIC: {topic}

Write YouTube search queries that would surface footage about this topic:
news reports, on-the-ground footage, press conferences, explainers, protest
and location footage. Include synonyms, the names of the people, places,
organisations and events involved, and closely related events.

Requirements:
- 8 to 12 queries in English.
- 8 to 12 queries in Traditional Chinese as used in TAIWAN (not Simplified,
  not mainland terminology).
- Every Chinese query MUST carry "english_gloss": a literal English
  translation of that query, for an editor who does not read Chinese.
- Queries are search box input: 2-6 words, no quotes, no boolean operators.

Reply with ONLY this JSON object and nothing else -- no prose, no code fence:
{{"terms": [
  {{"q": "an english query", "lang": "en"}},
  {{"q": "中文查詢", "lang": "zh", "english_gloss": "chinese query"}}
]}}
"""


def generate_terms(topic, timeout=None):
    """-> [{'q','lang','english_gloss'}]. Raises ClaudeError.

    The gloss requirement is validated here rather than trusted, because the
    manifest's whole readability for a non-Chinese-reading editor (REQ 5) rests
    on it and a missing gloss is exactly the kind of thing a retry fixes.
    """
    data = ask_json(_TERM_PROMPT.format(topic=topic), timeout)
    raw = data.get('terms')
    if not isinstance(raw, list) or not raw:
        raise ClaudeError(ERR_OUTPUT, f'no "terms" array in the reply: {str(data)[:200]}')

    out, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        q = str(item.get('q') or '').strip()
        lang = str(item.get('lang') or '').strip().lower()
        if not q or lang not in ('en', 'zh'):
            continue
        gloss = str(item.get('english_gloss') or item.get('gloss') or '').strip()
        if lang == 'zh' and not gloss:
            raise ClaudeError(ERR_OUTPUT,
                              f'the Chinese query {q!r} came back without the '
                              'required english_gloss')
        key = q.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append({'q': q, 'lang': lang, 'english_gloss': gloss or None})
    if not out:
        raise ClaudeError(ERR_OUTPUT, 'the reply contained no usable queries')
    return out


# --------------------------------------------------------- call #2: relevance

_RELEVANCE_PROMPT = """\
A documentary editor searched YouTube for b-roll about this topic.

TOPIC: {topic}

Below are {n} results, numbered. Decide which are actually about the topic and
usable as footage. Drop: unrelated results the search dragged in, reaction and
commentary videos with no footage of their own, music, gaming, and clickbait
compilations. Keep anything that plausibly contains footage of the subject,
including foreign-language coverage of it.

{listing}

Reply with ONLY this JSON object -- indices only, no titles, no prose:
{{"keep": [0, 3, 4], "drop": [{{"i": 1, "why": "reason, 10 words max"}}]}}
Every index from 0 to {last} must appear exactly once, in keep or in drop.
"""

# Batch size for the relevance call. ~40 titles is a couple of thousand tokens
# and comes back well inside the timeout; the whole point of batching is that a
# 200-candidate job does not hang on one enormous prompt.
RELEVANCE_BATCH = 40


def filter_relevance(topic, videos, batch=RELEVANCE_BATCH, timeout=None):
    """-> {video_id: (relevant: bool, why: str)} for everything it judged.

    Raises ClaudeError; the caller DEGRADES on that rather than failing the job
    (an unfiltered manifest with a banner beats no manifest at all).

    Videos the model failed to mention in either list are simply absent from
    the result, and the caller leaves those relevant -- an omission must never
    silently hide a video from the editor.
    """
    verdicts = {}
    for start in range(0, len(videos), batch):
        chunk = videos[start:start + batch]
        listing = '\n'.join(
            '{}. {} | {} | {}'.format(
                i, (v.get('title') or '?')[:120], (v.get('channel') or '?')[:60],
                _mmss(v.get('duration')))
            for i, v in enumerate(chunk))
        data = ask_json(_RELEVANCE_PROMPT.format(
            topic=topic, n=len(chunk), listing=listing, last=len(chunk) - 1), timeout)

        keep = {int(i) for i in data.get('keep', []) if _is_index(i, len(chunk))}
        for i in keep:
            verdicts[chunk[i]['id']] = (True, '')
        for item in data.get('drop', []) or []:
            if isinstance(item, dict):
                i, why = item.get('i'), str(item.get('why') or '')[:80]
            else:
                i, why = item, ''
            if _is_index(i, len(chunk)) and int(i) not in keep:
                verdicts[chunk[int(i)]['id']] = (False, why)
    return verdicts


def _is_index(i, n):
    try:
        return 0 <= int(i) < n
    except (TypeError, ValueError):
        return False


def _mmss(sec):
    if not sec:
        return '?'
    sec = int(sec)
    return f'{sec // 60}:{sec % 60:02d}'


# ---------------------------------------------------------------- health probe
# The SPA warns about a logged-out claude BEFORE an editor submits a job, which
# means something has to answer "is claude usable" on page load. That must not
# be a subprocess per request: `claude -p "ok"` is a second or two and every
# open tab would pay it. So the answer is cached, refreshed by the worker (at
# start, and whenever a call fails), and served from memory.

_health = {'claude': 'unknown', 'checked_at': None, 'detail': ''}
_health_lock = threading.Lock()

# Don't re-probe more often than this. The worker calls refresh() on every
# failure, and a wedged claude that fails 40 videos in a row must not turn into
# 40 subprocesses.
_MIN_PROBE_INTERVAL = 60.0


def health():
    """The cached answer. Never runs anything -- safe on a request thread."""
    with _health_lock:
        return dict(_health)


def refresh_health(force=False):
    """Probe claude and update the cache. -> the cache dict. WORKER THREAD ONLY.

    `claude -p "say ok"` is the same command DEPLOY.md tells an admin to verify
    the login with, so a green health line here means the thing the ops
    procedure checks is actually true.
    """
    with _health_lock:
        last = _health['checked_at']
        if not force and last and (time.time() - last) < _MIN_PROBE_INTERVAL:
            return dict(_health)

    state, detail = 'ok', ''
    try:
        _invoke('say ok', timeout=min(60, config.CLAUDE_TIMEOUT))
    except ClaudeError as exc:
        detail = exc.detail
        state = {ERR_AUTH: 'unauthenticated',
                 ERR_MISSING: 'missing',
                 ERR_TIMEOUT: 'timeout'}.get(exc.prefix, 'error')
    except Exception as exc:  # noqa: BLE001 - a probe must never kill the worker
        state, detail = 'error', str(exc)[:200]

    with _health_lock:
        _health.update({'claude': state, 'checked_at': time.time(), 'detail': detail})
        return dict(_health)


def note_failure(exc):
    """Fold a live call's failure into the cache without running a probe.

    A job that just died on claude_auth: already IS the probe -- and it is more
    current than anything a subprocess could tell us a second later.
    """
    state = {ERR_AUTH: 'unauthenticated', ERR_MISSING: 'missing',
             ERR_TIMEOUT: 'timeout'}.get(getattr(exc, 'prefix', ''), 'error')
    with _health_lock:
        _health.update({'claude': state, 'checked_at': time.time(),
                        'detail': getattr(exc, 'detail', str(exc))[:200]})
