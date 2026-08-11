"""Headless `claude -p` wrapper: the two AI calls, and how they fail.

Claude Code runs on the server under the operator's own account (a one-time
`/login` writes credentials into the claude-home volume -- DEPLOY.md). This
module is the only thing that shells out to it.

Four decisions worth keeping:

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

**Both prompts are biased by the SHOT TYPES the editor ticked, from one place.**
The tunable text lives in the SHOT_TYPES table below -- one fragment per
checkbox per stage -- rather than dissolved into the prose of the two prompts,
which take it as `{bias}` (2026-08-11).
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
    # A call that worked IS the probe, and it is the only thing that ever
    # writes `ok` back: without it one transient timeout showed red on every
    # editor's page until the container was restarted, including after an admin
    # had followed DEPLOY.md and verified the login by hand (YTDL-5,
    # 2026-08-11).
    _note_ok()
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


# ------------------------------------------------------- the shot-type bias
# 2026-08-11 (morning): both calls used to optimise for "is this ABOUT the
# topic", which is what a news desk wants and the opposite of what an editor
# cutting b-roll wants. A search for `taiwan presidential palace` generated 24
# terms and 336 candidates dominated by news packages, studio segments,
# political commentary and panel shows -- clips about the building, not one shot
# OF it. That was fixed with two hardcoded fragments (VISUAL_TERM_BIAS /
# VISUAL_FILTER_BIAS).
#
# 2026-08-11 (afternoon): fixed policy is the wrong shape -- "just make it a
# series of check boxes so the user can decide and tweak it". So the same text
# is now split PER SHOT TYPE, and the editor's ticks decide which fragments are
# composed into the two prompts. The six footage types below are ticked by
# default, the three coverage types are not, and that default selection
# reproduces the morning's behaviour word for word.
#
# Both languages are first-class in every fragment: this fleet searches en+zh
# and a Taiwanese footage idiom is not a translation of an English one (空拍 is
# the drone search; 完整版 is what an unedited full-length ceremony is filed
# under). The Chinese is written literally, as the _TERM_PROMPT example already
# is -- unlike worker.py, this file is not ASCII-only.
#
# Each entry carries four fragments and they are NOT symmetrical:
#   seek  -- the search phrasings to generate       (used when TICKED)
#   keep  -- the relevance filter's keep guidance   (used when TICKED)
#   avoid -- search phrasings to steer away from    (used when UNTICKED)
#   drop  -- the relevance filter's drop guidance   (used when UNTICKED)
# Only the three COVERAGE types carry avoid/drop. An unticked footage type is
# simply not sought -- an editor who wants aerials has not thereby banned
# timelapses -- whereas an unticked coverage type must be actively pushed away
# from, because interviews, news packages and reaction videos are what YouTube
# returns for a topic by default and they crowd everything else off the
# manifest. That asymmetry is the whole point of the feature.

SHOT_TYPES = {
    'aerial': {
        'label': 'Aerial / drone',
        'default': True,
        'group': 'footage',
        'seek': ('aerial, aerial view, drone footage, drone shot, flyover, '
                 'from above; 空拍, 空拍機, 空拍畫面, 鳥瞰, 高空'),
        'keep': 'aerials, drone shots and flyovers of the subject',
    },
    'establishing': {
        'label': 'Establishing / exteriors',
        'default': True,
        'group': 'footage',
        'seek': ('establishing shot, exterior, exteriors, wide shot, skyline, '
                 'cityscape, landmark, night view; 外觀, 實景, 全景, 夜景, 地標'),
        'keep': ('establishing shots, exteriors, interiors, streets and '
                 'landmarks -- the place itself, held on screen'),
    },
    'walkthrough': {
        'label': 'Walk-through / POV / street',
        'default': True,
        'group': 'footage',
        'seek': ('walking tour, walkthrough, POV, first person, street view, '
                 'driving tour; 徒步, 漫步, 導覽, 街景, 第一人稱'),
        'keep': 'walking tours, POV walkthroughs, street-level and driving takes',
    },
    'timelapse': {
        'label': 'Timelapse',
        'default': True,
        'group': 'footage',
        'seek': ('timelapse, time lapse, hyperlapse, day to night; '
                 '縮時, 縮時攝影, 縮時影片'),
        'keep': 'timelapses and hyperlapses',
    },
    'event': {
        'label': 'Ceremonies / events / protests',
        'default': True,
        'group': 'footage',
        'seek': ('ceremony, full ceremony, parade, protest, rally, press '
                 'conference, live from the scene; 典禮, 儀式, 遊行, 抗議, '
                 '記者會, 現場, 全程'),
        'keep': ('ceremonies, parades, protests, press events and other events '
                 'shot on location, especially the raw or full-length versions'),
    },
    'raw': {
        'label': 'Raw / uncut / no commentary',
        'default': True,
        'group': 'footage',
        'seek': ('raw footage, unedited, uncut, no commentary, full version, '
                 'ambient, 4K, stock footage, b-roll; 完整版, 未剪輯, 原始畫面, '
                 '無旁白, 無解說, 環境音, 4K'),
        'keep': ('raw, uncut and full-length takes, ambient no-narration '
                 'material, and anything filed as b-roll or stock footage'),
    },
    'interview': {
        'label': 'Interviews / talking heads',
        'default': False,
        'group': 'coverage',
        'seek': ('interview, sit-down interview, talking head, in depth '
                 'interview; 專訪, 訪談, 對談'),
        'keep': ('interviews, talking heads and panel discussions -- the '
                 'editor asked for these'),
        'avoid': 'interview, sit-down interview, talking head; 專訪, 訪談',
        'drop': 'interviews and talk/panel shows: 專訪, 訪談, 政論節目, 名嘴',
    },
    'news': {
        'label': 'News reports',
        'default': False,
        'group': 'coverage',
        'seek': ('news report, news package, news coverage, breaking news; '
                 '新聞, 新聞報導, 快訊, 播報'),
        'keep': ('news reports and packages, studio-led ones included -- the '
                 'editor asked for these'),
        'avoid': 'breaking news, news update, news report; 快訊, 新聞, 新聞報導',
        # The field-report carve-out is deliberate and predates the checkboxes:
        # a report whose PICTURES carry it is footage with a voice over it.
        'drop': ('studio segments, news anchors and desk reads, pieces to '
                 'camera -- but a field report where the shots of the subject '
                 'clearly carry the video is footage, so keep that one'),
    },
    'commentary': {
        'label': 'Commentary / analysis / reaction',
        'default': False,
        'group': 'coverage',
        'seek': ('commentary, analysis, explainer, reaction, review, podcast; '
                 '評論, 分析, 解析, 政論, 懶人包'),
        'keep': ('commentary, analysis, explainers and reaction videos -- the '
                 'editor asked for these'),
        'avoid': ('analysis, commentary, explainer, debate, reaction, podcast, '
                  'top 10; 分析, 評論, 辯論, 政論, 名嘴, 懶人包'),
        'drop': ('commentary, analysis, explainers, reaction videos, podcasts, '
                 'vlogs about it'),
    },
}

# The ticks a page load starts with, and what an old job row (or a caller that
# passes nothing) means. In SHOT_TYPES order, always.
DEFAULT_SHOT_TYPES = tuple(k for k, v in SHOT_TYPES.items() if v['default'])

# "footage of the subject" vs "somebody talking about the subject". The split
# decides three things: only coverage types are steered away from when unticked
# (see the note above), the PRIORITISE VISUALS framing is only asserted when at
# least one footage type is ticked -- an editor who asked for nothing but
# interviews must not be told to prefer pictures over talking -- and it is how
# the SPA groups the nine boxes so they do not read as a wall.
FOOTAGE_KEYS = tuple(k for k, v in SHOT_TYPES.items() if v['group'] == 'footage')
COVERAGE_KEYS = tuple(k for k, v in SHOT_TYPES.items() if v['group'] == 'coverage')

# Both degenerate selections mean the same thing and are handled here rather
# than left to emerge from the loops: EVERYTHING ticked composes a filter that
# is told to keep every kind of material and drop none, NOTHING ticked composes
# one told to drop every kind and keep none. The first is a no-op dressed up as
# an instruction and the second is incoherent -- an editor who ticks all nine
# boxes plainly wants the search left alone, and one who ticks none has not
# asked for an empty manifest. Both get a neutral, topic-only search.
_NEUTRAL_TERM_BIAS = """\
NO SHOT-TYPE PREFERENCE: the editor ticked either every kind of material or
none, which mean the same thing here -- search the topic broadly and do not
steer the queries towards or away from any particular kind of video. Cover the
places, the people, the organisations and the events from as many angles as the
topic has.
"""

_NEUTRAL_FILTER_BIAS = """\
NO SHOT-TYPE PREFERENCE: the editor ticked either every kind of material or
none, which mean the same thing here -- judge on the TOPIC alone. A studio
interview, a drone shot and a raw ceremony are all equally welcome.

DROP only what is not about this topic at all: unrelated results the search
dragged in, music, gaming, and AI-generated or still-image slideshow "footage".
When it is genuinely unclear, KEEP it -- a kept dud costs the editor one glance,
a wrong drop hides a clip they never learn existed.
"""

# Asserted only when a footage type is ticked; see FOOTAGE_KEYS.
_FOOTAGE_HEADER = """\
PRIORITISE VISUALS. The editor needs FOOTAGE OF this subject -- shots that can
be cut into a timeline -- not coverage ABOUT it.
"""

_PREFER_UNCUT = """\
All else equal prefer the LONGER, steadier, less-edited item: an unedited
12-minute walk-through beats a 90-second cut of the same place, and a 40-minute
full ceremony beats the news summary of it.
"""


def normalise_shot_types(shot_types):
    """-> a tuple of known keys in SHOT_TYPES order. None means the defaults.

    Tolerant on purpose: this is fed from a job row that may have been written
    by an older (or newer) build, and an unrecognised key must cost a fragment,
    never a search. The API is where an unknown key is refused.
    """
    if shot_types is None:
        return DEFAULT_SHOT_TYPES
    wanted = {str(k).strip().lower() for k in shot_types}
    return tuple(k for k in SHOT_TYPES if k in wanted)


def _is_neutral(selected):
    """All ticked and none ticked are the same instruction: no bias."""
    return not selected or len(selected) == len(SHOT_TYPES)


def term_bias(shot_types=None):
    """The {bias} block of the term prompt, composed from the ticked types."""
    selected = normalise_shot_types(shot_types)
    if _is_neutral(selected):
        return _NEUTRAL_TERM_BIAS

    out = []
    if any(k in FOOTAGE_KEYS for k in selected):
        out.append(_FOOTAGE_HEADER + '\n')
    out.append('The editor asked for these kinds of material. Bias the queries '
               'towards the\nphrasings that actually surface them on YouTube, '
               'in BOTH languages:\n')
    for key in selected:
        out.append(f"- {SHOT_TYPES[key]['label']}: {SHOT_TYPES[key]['seek']}.\n")
    out.append('At least two thirds of the queries in EACH language must carry '
               'one of those\nphrasings, combined with the names of the places, '
               'people, events and\nlandmarks involved.\n')

    avoid = [SHOT_TYPES[k]['avoid'] for k in SHOT_TYPES
             if k not in selected and SHOT_TYPES[k].get('avoid')]
    if avoid:
        out.append('\nAVOID the phrasings the editor did NOT ask for, in either '
                   'language:\n')
        out.extend(f'- {a}.\n' for a in avoid)
    return ''.join(out)


def filter_bias(shot_types=None):
    """The {bias} block of the relevance prompt, composed from the ticked types."""
    selected = normalise_shot_types(shot_types)
    if _is_neutral(selected):
        return _NEUTRAL_FILTER_BIAS

    drops = [SHOT_TYPES[k]['drop'] for k in SHOT_TYPES
             if k not in selected and SHOT_TYPES[k].get('drop')]
    out = ['DROP:\n']
    out.extend(f'- {d}\n' for d in drops)
    if any(k in FOOTAGE_KEYS for k in selected):
        out.append('- compilations and edits buried under heavy overlays -- '
                   'captions filling the\n  frame, zooms, memes, stock music, '
                   'a hard cut every two seconds\n')
    out.append('- unrelated results the search dragged in, music, gaming, and '
               'AI-generated or\n  still-image slideshow "footage"\n')

    out.append('\nKEEP, because this is what the editor ticked:\n')
    out.extend(f"- {SHOT_TYPES[k]['keep']}\n" for k in selected)
    out.append('- foreign-language material: narration the editor cannot use '
               'does not matter\n  when the pictures are the point\n')

    out.append('\n')
    if 'raw' in selected:
        out.append(_PREFER_UNCUT)
    out.append('When it is genuinely unclear whether an item is what the editor '
               'asked for,\nKEEP it -- a kept dud costs the editor one glance, a '
               'wrong drop hides a clip\nthey never learn existed.\n')
    return ''.join(out)


# ------------------------------------------------------------- call #1: terms

_TERM_PROMPT = """\
You are helping a documentary editor find archive/b-roll footage on YouTube.

TOPIC: {topic}

Write YouTube search queries that would surface footage OF this topic: the
places, the people, the events -- on-the-ground and location footage, aerials,
walk-throughs, ceremonies and press events as they happened. Include synonyms,
the names of the people, places, organisations and events involved, and closely
related events.

{bias}
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


def generate_terms(topic, shot_types=None, timeout=None):
    """-> [{'q','lang','english_gloss'}]. Raises ClaudeError.

    `shot_types` is the editor's ticked boxes (None = the defaults); it only
    ever changes the {bias} block, never the JSON contract below.

    The gloss requirement is validated here rather than trusted, because the
    manifest's whole readability for a non-Chinese-reading editor (REQ 5) rests
    on it.

    ONE missing gloss is not worth the job. ask_json's retry only covers
    unparseable output, so the promised "a retry fixes this" never happened and
    19 good terms plus one glossless Chinese query lost the whole search
    (YTDL-20, 2026-08-11). The whole reply is now asked for a second time --
    and if that one is short a gloss too, those queries are dropped and the
    rest of the search goes ahead.
    """
    prompt = _TERM_PROMPT.format(topic=topic, bias=term_bias(shot_types))
    out, missing = _usable_terms(ask_json(prompt, timeout))
    if missing:
        log.warning('claude returned %d query(ies) without english_gloss (%s); '
                    'asking once more', len(missing), ', '.join(missing)[:120])
        out, missing = _usable_terms(ask_json(prompt, timeout))
        if missing:
            log.warning('still no english_gloss for %s -- dropping those and '
                        'keeping the %d usable queries',
                        ', '.join(missing)[:120], len(out))
    if not out:
        raise ClaudeError(ERR_OUTPUT, 'the reply contained no usable queries')
    return out


def _usable_terms(data):
    """-> ([{'q','lang','english_gloss'}], [glossless zh queries]).

    The glossless ones are reported rather than returned: a Chinese query with
    no translation is unreadable in the manifest, so it is only ever kept after
    a second reply has failed to supply one.
    """
    raw = data.get('terms')
    if not isinstance(raw, list) or not raw:
        raise ClaudeError(ERR_OUTPUT, f'no "terms" array in the reply: {str(data)[:200]}')

    out, seen, missing = [], set(), []
    for item in raw:
        if not isinstance(item, dict):
            continue
        q = str(item.get('q') or '').strip()
        lang = str(item.get('lang') or '').strip().lower()
        if not q or lang not in ('en', 'zh'):
            continue
        gloss = str(item.get('english_gloss') or item.get('gloss') or '').strip()
        key = q.casefold()
        if key in seen:
            continue
        seen.add(key)
        if lang == 'zh' and not gloss:
            missing.append(q)
            continue
        out.append({'q': q, 'lang': lang, 'english_gloss': gloss or None})
    return out, missing


# --------------------------------------------------------- call #2: relevance

_RELEVANCE_PROMPT = """\
A documentary editor searched YouTube for b-roll about this topic.

TOPIC: {topic}

Below are {n} results, numbered, as "index. title | channel | duration". Judge
each one on whether it is FOOTAGE OF the subject that can be cut into a
timeline, not coverage ABOUT the subject.

{bias}
{listing}

Reply with ONLY this JSON object -- indices only, no titles, no prose:
{{"keep": [0, 3, 4], "drop": [{{"i": 1, "why": "reason, 10 words max"}}]}}
Every index from 0 to {last} must appear exactly once, in keep or in drop.
"""

# Batch size for the relevance call. ~40 titles is a couple of thousand tokens
# and comes back well inside the timeout; the whole point of batching is that a
# 200-candidate job does not hang on one enormous prompt.
RELEVANCE_BATCH = 40


def filter_relevance(topic, videos, shot_types=None, batch=RELEVANCE_BATCH,
                     timeout=None):
    """-> {video_id: (relevant: bool, why: str)} for everything it judged.

    `shot_types` is the editor's ticked boxes (None = the defaults) and reaches
    the model as the {bias} block only -- the indices-in, indices-out contract
    below is the same whatever is ticked.

    Raises ClaudeError; the caller DEGRADES on that rather than failing the job
    (an unfiltered manifest with a banner beats no manifest at all).

    Videos the model failed to mention in either list are simply absent from
    the result, and the caller leaves those relevant -- an omission must never
    silently hide a video from the editor.
    """
    verdicts = {}
    # Composed once: the selection cannot change between batches of one job,
    # and a 200-candidate job is five calls.
    bias = filter_bias(shot_types)
    for start in range(0, len(videos), batch):
        chunk = videos[start:start + batch]
        listing = '\n'.join(
            '{}. {} | {} | {}'.format(
                i, (v.get('title') or '?')[:120], (v.get('channel') or '?')[:60],
                _mmss(v.get('duration')))
            for i, v in enumerate(chunk))
        data = ask_json(_RELEVANCE_PROMPT.format(
            topic=topic, n=len(chunk), listing=listing, last=len(chunk) - 1,
            bias=bias), timeout)

        # `or []` and the list check on BOTH: a reply that kept nothing comes
        # back as {"keep": null, ...} often enough, and the TypeError that used
        # to raise escaped the caller's ClaudeError-only except -- failing a
        # twenty-minute job at `filtering` where the design says degrade to an
        # unfiltered manifest with a banner (YTDL-13, 2026-08-11).
        keep = {int(i) for i in _as_list(data.get('keep')) if _is_index(i, len(chunk))}
        for i in keep:
            verdicts[chunk[i]['id']] = (True, '')
        for item in _as_list(data.get('drop')):
            if isinstance(item, dict):
                i, why = item.get('i'), str(item.get('why') or '')[:80]
            else:
                i, why = item, ''
            if _is_index(i, len(chunk)) and int(i) not in keep:
                verdicts[chunk[int(i)]['id']] = (False, why)
    return verdicts


def _as_list(value):
    """A JSON field that should have been an array, as one. Anything else --
    null, a number, an object -- reads as "the model said nothing here"."""
    return value if isinstance(value, (list, tuple)) else []


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
# open tab would pay it. So the answer is cached, refreshed by the worker at
# start, and written by every live call as it happens -- _note_ok() on success
# and note_failure() on a classified failure. The cache MUST be able to recover
# on its own (YTDL-5): the only other way back to green is a container restart,
# which takes the fleet status page down with it.

_health = {'claude': 'unknown', 'checked_at': None, 'detail': ''}
_health_lock = threading.Lock()

# Don't re-probe more often than this. A wedged claude that fails 40 videos in
# a row must not turn into 40 subprocesses.
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


def _note_ok():
    """Record that a live call just worked. Called from _invoke, any thread."""
    with _health_lock:
        _health.update({'claude': 'ok', 'checked_at': time.time(), 'detail': ''})


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
