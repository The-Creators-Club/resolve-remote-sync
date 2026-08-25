"""The pipeline: one daemon thread that walks a job through its phases.

Why a thread and not a queue/subprocess/celery: the dashboard runs
**uvicorn with workers=1, and that is load-bearing** (SPEC). One process means
one worker thread is genuinely a singleton, an in-memory download-percentage
map is genuinely shared with the request handlers, and there is no broker to
deploy. It also means the request handlers must stay sync-and-SQLite-only --
anything that blocks in here blocks nothing, anything that blocks in a handler
blocks the dashboard.

Serial by design: one job at a time, one term at a time, one video at a time,
3 seconds apart. Not a throughput decision -- bulk anonymous requests out of a
single NAS IP is exactly what gets a datacentre IP bot-checked by YouTube.

**Every phase transition and every counter bump is a committed UPDATE.** The
SPA polls the job row 1500 ms apart and there is no SSE in this codebase, so
progress that lives in memory is progress that vanishes on restart and lies in
between. The single exception is the per-video download percentage, which
changes several times a second and is merged into the poll response from the
in-memory map below -- writing that to SQLite would be thousands of writes per
job for a number nobody reads twice.
"""
import logging
import os
import re
import threading
import time
from pathlib import Path

from ytdlweb import claude_cli, config, db, ytdl_common
from ytdlweb.vendor import downloader, ytsearch
# The naming/fallback contract BOTH executors run under, moved out of this file
# on 2026-08-14 so the companion can vendor it (docs/YTDL_LOCAL_DOWNLOAD.md §5).
# Re-imported under the names this module has always used, so the worker's own
# behaviour -- and everything that reads these -- is unchanged by the move.
from ytdlweb.ytdl_common import (BEST_FALLBACK_QUALITY,  # noqa: F401
                                 TRUNCATED_NOTE)
from ytdlweb.ytdl_common import TRUNCATION_MARKERS as _TRUNCATION_MARKERS  # noqa: F401
from ytdlweb.ytdl_common import stream_truncated as _stream_truncated

log = logging.getLogger(__name__)

_thread = None
_thread_lock = threading.Lock()
_nudge = threading.Event()

# Indirected so a test can assert the search phase PACED without waiting out a
# real 48 seconds (ytsearch.enrich takes its sleeper as an argument for the
# same reason; this loop has no such seam because ytsearch.search is one call
# per term, not a pool).
_sleep = time.sleep

# {job_id: {video_id: {'percent': float, 'speed': str, 'status': str}}}. Poll
# reads it, the download hook writes it; a dict assignment is atomic enough for
# both under the GIL and a torn read here costs a wrong percentage for 1.5 s.
_progress = {}

# How long the loop sleeps when there is nothing to do. Short enough that a
# missed nudge (there is no such path today, but there is also no way to prove
# it forever) costs seconds rather than forever.
IDLE_WAIT = 5.0

# How long a RED AI-health cache is left alone before the idle loop probes
# again (ytdl-web-4, 2026-08-21). Minutes, not seconds: the failure this
# recovers from is a container that booted before the NAS had a WAN uplink, and
# a provider that is wedged for an hour must not cost a probe every idle tick.
# claude_cli._MIN_PROBE_INTERVAL is the floor underneath this, not a substitute
# for it -- nothing was asking for a re-probe at all.
UNHEALTHY_RECHECK = 300.0

# Leftovers older than this in a folder we own get swept. yt-dlp resumes its
# own .part within a run; a day-old one belongs to a container that is gone.
STALE_AFTER = 24 * 3600


class BotCheckError(RuntimeError):
    """YouTube is bot-checking this IP. Nothing here can retry its way out."""


# YTDL-21 (2026-08-11): the phrase yt-dlp surfaces when the NAS's datacentre IP
# is challenged. Both apostrophes, because yt-dlp passes YouTube's own text
# through and it has arrived either way -- the curly one as an escape so this
# file stays pure ASCII. Deliberately NOT the bare "sign in to confirm":
# "Sign in to confirm your age" is one dead video, not a challenged IP, and
# failing a whole job over an age-gated clip would be worse than the bug.
_BOT_CHECK_MARKERS = ("confirm you're not a bot",
                      "confirm you\u2019re not a bot")

BOT_CHECK_NOTE = (
    'YouTube is asking this server to sign in to confirm it is not a bot, so '
    'nothing can be searched or downloaded from it right now. An admin has to '
    'export a cookies.txt from a signed-in browser and point YTDL_COOKIES_FILE '
    'at it (ytdl/web/DEPLOY.md, "cookies.txt escape hatch").')


def _bot_checked(text):
    """Is this yt-dlp message a bot check?

    Treated as fatal to the PHASE rather than to the video: an IP that is being
    challenged is challenged for every video, so the alternative is burning the
    full retry budget forty times over and ending `done` with forty opaque
    per-row errors that name no fix.
    """
    low = str(text or '').lower()
    return any(m in low for m in _BOT_CHECK_MARKERS)


def ensure_started():
    """Start the worker if it is not already running. -> did we end up with one.

    Idempotent because it is called from BOTH mount time
    (ccsync_dashboard.ytdl._init_ytdl_storage -- Starlette does not run a
    mounted sub-app's lifespan, the trap music.py documents) and the standalone
    dev lifespan. Whichever runs first wins and the other is a no-op.

    `YTDL_WORKER=0` disables it outright. The tests set it: a phase machine
    that starts itself on import would race every fixture in the suite, and the
    dashboard's mount tests import a fake `ytdlweb` that must not spawn
    anything at all.
    """
    if os.environ.get('YTDL_WORKER') == '0':
        log.info('ytdl worker disabled by YTDL_WORKER=0')
        return False
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return True
        _thread = threading.Thread(target=_run, name='ytdl-worker', daemon=True)
        _thread.start()
    return True


def is_alive():
    """For api/health. A dead worker means jobs queue up and nothing moves."""
    return bool(_thread is not None and _thread.is_alive())


def nudge():
    """Wake the loop now rather than at the next idle timeout."""
    _nudge.set()


# ------------------------------------------------------------ progress map

def job_progress(job_id):
    """{video_id: {...}} for the poll response. Never touches the database."""
    return dict(_progress.get(job_id) or {})


def _set_progress(job_id, video_id, data):
    _progress.setdefault(job_id, {})[video_id] = data


def _clear_progress(job_id, video_id=None):
    if video_id is None:
        _progress.pop(job_id, None)
    else:
        _progress.get(job_id, {}).pop(video_id, None)


# ------------------------------------------------------------------- loop

def _boot_recovery(c):
    try:
        restarted, resumed = db.reset_stale_jobs(c)
        if restarted or resumed:
            log.info('boot recovery: %d job(s) restarted from scratch, %d '
                     'in-flight download(s) put back to pending', restarted, resumed)
    except Exception:  # noqa: BLE001 - a broken sweep must not cost us the worker
        log.exception('boot recovery failed; continuing')


def _run():
    """The thread body. Never returns; never lets an exception out."""
    # One probe at start so the SPA can warn about a logged-out claude before
    # anyone submits a job. On the worker thread on purpose: it costs a second
    # or two and must never be paid on a request.
    try:
        claude_cli.refresh_health(force=True)
    except Exception:  # noqa: BLE001
        log.exception('claude health probe failed')

    # YTDL-19 (2026-08-11): the connection is acquired INSIDE the loop and
    # re-acquired after a failure. It used to be opened before the try, so a
    # database locked at boot (or a data root not yet writable after a NAS
    # remount) killed this thread for the life of the container -- ensure_started
    # runs only at mount, nothing ever restarts it, and the only symptom is
    # `worker_alive:false` in a poll response nothing reads.
    c = None
    booted = False
    while True:
        worked = False
        try:
            if c is None:
                c = db.con()
            if not booted:
                _boot_recovery(c)
                booted = True
            worked = _tick(c)
        except Exception:  # noqa: BLE001
            log.exception('worker tick failed')
            c = None
        if not worked:
            recheck_health()
            _nudge.wait(IDLE_WAIT)
            _nudge.clear()


def recheck_health():
    """Probe the AI backend again while the cache is RED and we are idle.
    -> whether a probe was run.

    ytdl-web-4 (2026-08-21). refresh_health(force=True) at thread start was the
    only probe anything in this tree ever ran, and the worker starts at MOUNT
    time -- on a NAS reboot that is routinely before the uplink is up. The boot
    probe then failed with "could not reach the Anthropic API from this
    container", every editor's /ytdl page showed the red pip, and nothing
    re-checked: the only way back to green was somebody ignoring the warning
    and submitting a job, which succeeded and let _note_ok flip it. That is the
    self-healing YTDL-5 asked for, arriving hours late.

    Only while red, only when there is no job to run, and no more often than
    UNHEALTHY_RECHECK -- a probe is a real (tiny) billed call, and on a site
    with the CLI providers on it can be a slow one.
    """
    try:
        cached = claude_cli.health()
        if cached.get('claude') == 'ok':
            return False
        last = cached.get('checked_at')
        if last and (time.time() - last) < UNHEALTHY_RECHECK:
            return False
        state = claude_cli.refresh_health()
        if state.get('claude') == 'ok':
            log.info('the AI backend answered again (%s); the health pip is '
                     'green without a restart', state.get('provider') or 'no provider')
        return True
    except Exception:  # noqa: BLE001 - a probe must never kill the worker
        log.exception('AI health re-probe failed')
        return False


def _tick(c):
    """Advance one job, if there is one. -> whether anything was done."""
    job = db.claim_next_job(c)
    if job is None:
        return False
    run_job(c, job['id'])
    return True


# The phase machine. A phase with no handler is one the worker does not own:
# `ready_for_review` is waiting for the editor, the three terminal phases are
# over. Ordering is the dict's, but nothing reads it in order -- each handler
# names its own successor, which is what makes a half-finished job resumable.
def _handlers():
    return {
        'queued': _phase_start,
        'generating_terms': _phase_generate_terms,
        'searching': _phase_search,
        'enriching': _phase_enrich,
        'filtering': _phase_filter,
        'downloading': _phase_download,
    }


def run_job(c, job_id):
    """Walk one job as far as it can go, then return.

    Called by the loop, and directly by the tests -- which is why it takes a
    connection and does its own phase lookup rather than closing over either.
    """
    handlers = _handlers()
    while True:
        job = db.get_job(c, job_id)
        if job is None:
            return
        if job['cancel_requested'] and job['phase'] not in db.TERMINAL:
            _clear_progress(job_id)
            db.set_phase(c, job_id, 'cancelled')
            return
        # A job an editor's companion is downloading RIGHT NOW is not ours
        # (docs/YTDL_LOCAL_DOWNLOAD.md §3). db.claim_next_job already hides a
        # leased job from the loop; this is the same rule at the other door,
        # because the API and the tests call run_job directly. RETURN, never
        # "skip and carry on": nothing in here would change the phase, so a
        # continue would spin on this row until the lease expired.
        if db.lease_active(job):
            return
        handler = handlers.get(job['phase'])
        if handler is None:
            return
        try:
            handler(c, job)
        except BotCheckError as exc:
            # Carries its own ops instruction; the generic handler below would
            # bury it behind a type name.
            log.warning('job %s: bot-checked in phase %s', job_id, job['phase'])
            _clear_progress(job_id)
            db.set_phase(c, job_id, 'failed', str(exc)[:500])
            return
        except claude_cli.ClaudeError as exc:
            # Already classified and already carrying its prefix; the SPA turns
            # that into the right ops instruction.
            claude_cli.note_failure(exc)
            log.warning('job %s failed on claude: %s', job_id, exc)
            _clear_progress(job_id)
            db.set_phase(c, job_id, 'failed', str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - one job must not kill the worker
            log.exception('job %s failed in phase %s', job_id, job['phase'])
            _clear_progress(job_id)
            db.set_phase(c, job_id, 'failed', f'{type(exc).__name__}: {exc}'[:500])
            return


def _cancelled(c, job_id):
    """Re-read the flag from the database between units of work."""
    return db.is_cancelled(c, job_id)


# ------------------------------------------------------------- 1. the terms

# CJK Unified Ideographs and its extension A, as codepoint ranges so this
# source file stays pure ASCII. Only used to label the EDITOR's own term,
# which they may well have typed in Chinese; Claude labels the ones it
# generates itself.
_CJK_RANGES = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF))


def _looks_chinese(text):
    return any(lo <= ord(ch) <= hi for ch in str(text) for lo, hi in _CJK_RANGES)


def _phase_start(c, job):
    """queued -> the first phase THIS KIND of job has.

    A url job's videos were written by the API from the links the editor
    pasted, so it has nothing to generate, search, enrich or filter: it starts
    where the download phase starts. Branching here rather than creating the
    job at `downloading` keeps every job's life identical everywhere else --
    one row shape, one claim_next_job, one boot recovery, one cancel.
    """
    db.set_phase(c, job['id'],
                 'downloading' if job['kind'] == db.KIND_URLS else 'generating_terms')


def _phase_generate_terms(c, job):
    """Claude call #1: one topic in, EN + ZH search queries out.

    The editor's own term goes in FIRST and unconditionally (source='user'), so
    a job whose expansion is thin still searches what was actually asked for --
    and under the `exact` scope it is the ONLY term: no model call at all,
    which also means an exact search runs with the AI provider down.
    """
    job_id = job['id']
    db.add_term(c, job_id, job['term'],
                'zh' if _looks_chinese(job['term']) else 'en', 'user')

    # The mode, the shot types and the scope come off the JOB ROW, not from a
    # default here: a job that sat queued over a restart must be expanded
    # under the rubric the editor chose and with the boxes they ticked when
    # they submitted it.
    scope = db.term_scope_of(job)
    if scope == claude_cli.SCOPE_EXACT:
        db.set_job(c, job_id, terms_total=1)
        db.set_phase(c, job_id, 'searching')
        return

    generated = claude_cli.generate_terms(
        job['term'], shot_types=db.shot_types_of(job), mode=db.mode_of(job),
        term_scope=scope)
    for item in generated:
        if len(db.terms(c, job_id)) >= config.MAX_TERMS:
            # A ceiling, not a target. 24 terms x 15 results is already a
            # 5-minute search phase.
            log.info('job %s: term cap %d reached, dropping the rest',
                     job_id, config.MAX_TERMS)
            break
        db.add_term(c, job_id, item['q'], item['lang'], 'claude',
                    item.get('english_gloss'))

    db.set_job(c, job_id, terms_total=len(db.terms(c, job_id)))
    db.set_phase(c, job_id, 'searching')


# ----------------------------------------------------------- 2. the search

def _phase_search(c, job):
    """One flat search per term; merge by video id, attribute every hit.

    A term that fails is logged and marked searched with 0 hits rather than
    failing the job: YouTube rate-limiting one query out of twenty is normal,
    and nineteen terms' worth of manifest is worth having.

    THIS is where the editor's candidate ceiling is enforced -- at the point
    candidates are accumulated, not on the finished manifest. A cap applied
    afterwards would trim the grid and change nothing about the thing that
    actually got the NAS's IP bot-checked: one metadata call per candidate row,
    336 of them, 112 in before YouTube stopped answering (2026-08-11).

    Terms found AFTER the ceiling is reached are still searched and still
    attributed to videos already on the job -- the chips and terms_done are the
    manifest's account of what was looked for. What stops is new rows.

    PACED, like the enrich phase (config.SEARCH_PAUSE). This docstring used to
    claim "24 flat searches is not the volume in question"; that was wrong, and
    it cost a second bot check on the same day. With enrichment paced and the
    ceiling in force, a full search STILL tripped it while a pasted link
    downloaded fine -- because a paste is one request and this loop was ~24
    back to back, in a couple of seconds, against YouTube's search endpoint.
    The delay goes BEFORE each search after the first: pausing after the last
    one would only make cancelling slower.
    """
    job_id = job['id']
    cap = db.max_candidates_of(job)
    # Under `exact` there is exactly one term, so the per-term count is the
    # whole ceiling: the editor chose 100 (or 400) candidates, and a single
    # search returning 15 of them would be a search they did not ask for. One
    # flat search paginates at YouTube's own 20 per page, with no per-page
    # pause -- but a 400-row ytsearch is still one search endpoint call chain
    # against the 24 back-to-back ones the pause below exists for, and the
    # metadata pass behind it is what the cap was sized for (2026-08-11).
    per_term = (cap if db.term_scope_of(job) == claude_cli.SCOPE_EXACT
                else job['max_per_term'])
    # Loaded once and kept in memory: the alternative is a SELECT per search
    # hit, and this loop already runs 24 x 15 times on a big job. A resumed job
    # starts from the rows it already has, so its ceiling is absolute rather
    # than per-run.
    have = {v['video_id'] for v in db.videos(c, job_id)}
    capped = False

    first = True
    for term in db.unsearched_terms(c, job_id):
        if _cancelled(c, job_id):
            return
        if not first and config.SEARCH_PAUSE > 0:
            # Checked for cancellation on the way out of the sleep as well: a
            # 24-term job now spends ~48 s in here, and an editor who pressed
            # CANCEL must not wait it out.
            _sleep(config.SEARCH_PAUSE)
            if _cancelled(c, job_id):
                return
        first = False
        try:
            entries = ytsearch.search(term['term'], per_term, job['period'])
        except Exception as exc:  # noqa: BLE001
            if _bot_checked(exc):
                raise BotCheckError(BOT_CHECK_NOTE) from exc
            log.warning('job %s: search failed for %r (%s)', job_id, term['term'], exc)
            entries = []

        new = 0
        for e in entries:
            vid = e.get('id')
            if not vid:
                continue
            if vid not in have:
                if len(have) >= cap:
                    # Not added and NOT linked: a term_id pointing at a video
                    # with no row would inflate the chip counts over a grid
                    # that cannot show it (YTDL-38's shape).
                    capped = True
                    continue
                url = e.get('url') or f'https://www.youtube.com/watch?v={vid}'
                if db.add_video(c, job_id, vid, url, e.get('title')):
                    new += 1
                have.add(vid)
            # Linked for every term that returned it, seen before or not --
            # that is what the manifest's term chips filter on.
            db.link_term(c, job_id, vid, term['id'])
        c.commit()

        # The RAW hit count, capped or not: it is what the term found, and the
        # chip tooltip subtracts the visible ones from it.
        db.mark_term_searched(c, term['id'], len(entries))
        db.bump(c, job_id, 'terms_done')
        if new:
            db.bump(c, job_id, 'candidates', new)

    if capped:
        log.info('job %s: candidate cap %d reached; later hits are attributed '
                 'but not added', job_id, cap)
    db.set_phase(c, job_id, 'enriching')


# --------------------------------------------------------- 3. the metadata

# Parallelism and pacing for the metadata fetch both live in config now
# (YTDL_ENRICH_WORKERS / YTDL_ENRICH_PAUSE). They used to be a bare `4` here
# with no delay at all, which is how 112 metadata calls went out fast enough
# for YouTube to stop answering the NAS entirely (2026-08-11): the download
# phase paced itself and this one, the busier of the two, did not.


def _phase_enrich(c, job):
    """Full metadata for every candidate: real durations, dates, thumbnails.

    One call per candidate row, so the SIZE of this phase is bounded by the
    job's candidate ceiling back in _phase_search and its RATE by
    config.ENRICH_PAUSE. Nothing is re-capped here: these rows are the search's
    output and dropping some now would leave a manifest full of videos with no
    metadata, which the filter phase then reads as "live or no duration".
    """
    job_id = job['id']
    todo = [v for v in db.videos(c, job_id)
            if v['duration'] is None and not v['meta_error']]
    db.set_job(c, job_id, enrich_total=len(todo), enrich_done=0)
    if not todo:
        db.set_phase(c, job_id, 'filtering')
        return

    entries = [{'id': v['video_id'], 'url': v['url']} for v in todo]
    seen = {'done': 0}

    def _seen(done, _total):
        # Called from a pool thread, so it touches memory ONLY: a sqlite3
        # connection may not be used off the thread that made it, and four
        # writers for one counter is not worth a second connection. The
        # database catches up on the worker thread after each chunk below.
        seen['done'] = done

    # Chunked so `enrich_done` reaches the database (and the poll response)
    # several times during a long metadata phase instead of once at the end.
    # It is also how a cancel is honoured mid-phase: at 0.75 s a request a
    # 400-candidate job is five minutes long, and the flag is read between
    # chunks, never inside the pool.
    CHUNK = max(4, config.ENRICH_WORKERS * 4)
    for start in range(0, len(entries), CHUNK):
        if _cancelled(c, job_id):
            return
        chunk = entries[start:start + CHUNK]
        results = ytsearch.enrich(chunk, jobs=config.ENRICH_WORKERS,
                                  progress=_seen, pause=config.ENRICH_PAUSE)
        for r in results:
            if _bot_checked(r.get('error')):
                # Not a dead video: the whole IP is challenged, and every
                # remaining entry would fail the same way.
                raise BotCheckError(BOT_CHECK_NOTE)
            if r.get('error'):
                # Unavailable/private/geo-blocked. Kept as a row so the editor
                # can see the search found something they cannot have, rather
                # than a candidate count that silently shrinks.
                db.set_video(c, job_id, r['id'], meta_error=r['error'][:300],
                             relevant=0, selected=0,
                             relevance_note='unavailable')
                continue
            db.set_video(c, job_id, r['id'],
                         url=r.get('url'), title=r.get('title'),
                         channel=r.get('channel'), duration=r.get('duration'),
                         upload_date=r.get('upload_date'),
                         view_count=r.get('view_count'),
                         thumbnail=r.get('thumbnail'))
        db.set_job(c, job_id, enrich_done=min(start + seen['done'], len(entries)))

    db.set_phase(c, job_id, 'filtering')


# ---------------------------------------------------------- 4. the filtering

# The banner an editor sees when the manifest could not be filtered. It is
# stored in jobs.error with the FAILING CALL'S prefix in front of it, on a
# job whose phase is not 'failed' -- which is exactly how the SPA tells a
# warning from a failure, and it keeps the ops instruction accurate (a
# logged-out CLI and an unparseable reply need different fixes).
DEGRADED_NOTE = 'relevance filter unavailable -- showing all results unfiltered'


def _phase_filter(c, job):
    """Mechanical drops, then Claude's verdicts, then the dedupe flags."""
    job_id = job['id']
    rows = db.videos(c, job_id)
    date_from, date_to = db.date_range_of(job)

    # (a) mechanical. A live stream has no fixed duration and cannot be cut
    # with; a missing duration means the metadata fetch got nothing usable.
    # Over-length videos (config.MAX_DURATION_SECONDS) are dropped the same
    # soft way, BEFORE the Claude judge sees them -- no tokens spent judging
    # a card the length cap already decided, and the editor can still
    # overrule from the manifest.
    for v in rows:
        if v['meta_error']:
            continue
        if not v['duration']:
            db.set_video(c, job_id, v['video_id'], relevant=0, selected=0,
                         relevance_note='live or no duration')
        elif v['duration'] > config.MAX_DURATION_SECONDS:
            db.set_video(c, job_id, v['video_id'], relevant=0, selected=0,
                         relevance_note='over %d minutes'
                                        % (config.MAX_DURATION_SECONDS // 60))
        elif _outside_dates(v, date_from, date_to):
            # The editor's upload-date range (2026-08-25). YouTube's search
            # cannot express one, so it is enforced here on the metadata, the
            # same soft way: the card stays, deselected, and the editor can
            # overrule from the manifest. No upload_date at all is KEPT --
            # "cannot tell" never drops anything in this phase.
            db.set_video(c, job_id, v['video_id'], relevant=0, selected=0,
                         relevance_note='uploaded %s, outside %s'
                                        % (_iso(v['upload_date']),
                                           _date_range_text(date_from, date_to)))

    # (b) Claude's relevance verdicts. DEGRADE, DO NOT FAIL: an editor with an
    # unfiltered manifest and a banner is fine; an editor with no manifest
    # because a CLI was logged out has lost the whole search.
    candidates = [dict(v) for v in db.videos(c, job_id)
                  if v['relevant'] and not v['meta_error']]
    if candidates:
        payload = [{'id': v['video_id'], 'title': v['title'],
                    'channel': v['channel'], 'duration': v['duration']}
                   for v in candidates]
        try:
            # The same mode and selection the terms were generated from --
            # a manifest filtered for footage after a search that asked for
            # interviews would drop most of what it just found, and one
            # filtered on the visuals rubric after a news-montage search would
            # throw away the reporting it went looking for.
            verdicts = claude_cli.filter_relevance(
                job['term'], payload, shot_types=db.shot_types_of(job),
                mode=db.mode_of(job), term_scope=db.term_scope_of(job))
        except claude_cli.ClaudeError as exc:
            claude_cli.note_failure(exc)
            log.warning('job %s: relevance filter unavailable (%s)', job_id, exc)
            # jobs.error with a NON-failed phase is the degraded banner. The
            # SPA renders `error` as a warning unless phase == 'failed'.
            db.set_job(c, job_id, error=f'{exc.prefix} {DEGRADED_NOTE}')
            verdicts = {}
        for vid, (keep, why) in verdicts.items():
            if keep:
                continue
            db.set_video(c, job_id, vid, relevant=0, selected=0,
                         relevance_note=why or 'not relevant to the topic')

    # (c) the dedupe flags (REQ 6). Two sources, unioned, because neither is
    # complete on its own: the ledger knows about downloads into OTHER
    # projects, and the filesystem knows about clips that predate the ledger or
    # were copied in by hand.
    mark_duplicates(c, job)

    db.set_phase(c, job_id, 'ready_for_review')


def _outside_dates(video, date_from, date_to):
    """True when the video's upload_date is KNOWN and outside [from, to].

    Both sides are YYYYMMDD strings (yt-dlp's shape, and what the API stores),
    so this is a string comparison on purpose: no parsing to get wrong, and a
    value that is not eight digits is "unknown", which never drops.
    """
    def _ymd(v):
        v = str(v or '').strip()
        return v if len(v) == 8 and v.isdigit() else None

    # The bounds are sanitised here too, not only in db.date_range_of: a row
    # written by hand with 'soon' in it must be no bound, never a string
    # comparison that drops every video ('19990101' < 'soon' is True).
    date_from, date_to = _ymd(date_from), _ymd(date_to)
    if not date_from and not date_to:
        return False
    d = _ymd(video['upload_date'])
    if d is None:
        return False
    if date_from and d < date_from:
        return True
    return bool(date_to and d > date_to)


def _iso(yyyymmdd):
    d = str(yyyymmdd or '')
    return f'{d[:4]}-{d[4:6]}-{d[6:]}' if len(d) == 8 else d


def _date_range_text(date_from, date_to):
    """The range as the relevance note says it: a hyphen, never an em dash
    (owner's rule, 2026-08-18) -- this string reaches the review grid."""
    if date_from and date_to:
        return f'{_iso(date_from)} to {_iso(date_to)}'
    if date_from:
        return f'{_iso(date_from)} onwards'
    return f'up to {_iso(date_to)}'


def mark_duplicates(c, job):
    """Flag+deselect every video the fleet already has. -> how many.

    Selection can never override this (db.select_video refuses duplicates, and
    the download phase re-checks anyway) -- REQ 6 is "never re-downloaded", not
    "shown differently".
    """
    job_id = job['id']
    ledger = db.ledger_map(c)
    try:
        youtube_root = config.safe_join(config.PROJECTS_ROOT,
                                        job['project_label'], 'Youtube')
        on_disk = ytsearch.existing_id_locations(youtube_root)
    except (config.PathTraversalError, OSError) as exc:
        log.warning('job %s: could not scan %s for existing ids (%s)',
                    job_id, job['project_label'], exc)
        on_disk = {}

    n = 0
    for v in db.videos(c, job_id):
        where = ledger.get(v['video_id'])
        if where is None and v['video_id'] in on_disk:
            where = f"{job['project_label']}/{on_disk[v['video_id']]}"
        if where is None:
            continue
        db.set_video(c, job_id, v['video_id'], duplicate=1, duplicate_of=where,
                     selected=0)
        n += 1
    return n


# ---------------------------------------------------------- 5. the download

def _chmod(path, mode):
    """Widen a mode so the fleet can actually see the file. Never fatal.

    The container runs `umask 077` (deploy/run.sh), so anything this process
    writes into /projects is 0600 owned by uid 3000 -- present on disk and
    **invisible over SMB to every editor**, which for a shared tree is the one
    unacceptable outcome. Widening here rather than loosening the umask is
    deliberate: umask is process-wide and 007 would hand group `editors` write
    access to dashboard.db in the same container. Copied from
    musicweb.routes_ingest._make_readable_to_the_fleet, including its no-op on
    Windows and its refusal to raise.
    """
    if os.name == 'nt':
        return
    try:
        os.chmod(path, mode)
    except OSError as exc:  # noqa: BLE001
        log.warning('could not chmod %s to %o (%s); editors may not see it over '
                    'SMB until it is fixed by hand', path, mode, exc)


def ensure_outdir(outdir):
    """makedirs + 2775 on everything this call actually created.

    setgid (2) on the directory so files land in the project's group the way
    the rest of the Projects tree does; the mode is only forced on directories
    we made, so an existing tree's ACLs are left alone.
    """
    outdir = Path(outdir)
    missing = []
    p = outdir
    while not p.exists() and p.parent != p:
        missing.append(p)
        p = p.parent
    os.makedirs(outdir, exist_ok=True)
    for d in reversed(missing):
        _chmod(d, 0o2775)
    return outdir


# YTDL-17 (2026-08-11): matched as a SUFFIX, and `.editready` is deliberately
# not here. `'.part' in p.name` also matched any title containing ".part", and
# `.editready` matched `<stem>.editready.mp4` -- which is not a leftover but
# _swap_in's fallback DELIVERABLE, ledgered under exactly that name: sweeping it
# left the ledger blocking a re-fetch fleet-wide and any Resolve project
# referencing it Media Offline.
_SWEEPABLE = ('.part', '.ytdl', '.temp')

# The other half of the same litter, by STEM (COMP-BROLL-3, 2026-08-14). A
# 1080p rung is `bestvideo+bestaudio`, so yt-dlp renames `... [id].f137.mp4.part`
# to `... [id].f137.mp4` the moment that stream completes and KEEPS it, for
# resume, if the audio or the merge then fails. Nothing deleted it: it is not a
# suffix above, _landed_file already refuses to read it as the clip, and it
# matches lane A's `+ *.mp4` include and no stignore line -- so one lid closed
# at clip 7 put a 1.4 GB video-only orphan in the canonical tree and on every
# editor with that project ticked, permanently. `.temp` is the same file half a
# second later (FFmpegMergerPP writes `... [id].temp.mp4`).
#
# A DELIVERABLE can never match: the outtmpl ends every finished name in
# `[id].<ext>`, so its stem ends in `[id]`. Identical to the local executor's
# ytdl_executor._INTERMEDIATE_STEM_RE, deliberately -- both executors write
# into one canonical tree and must leave the same things behind in it.
_INTERMEDIATE_STEM = re.compile(r'\.(f\d+|temp)$')


def _sweepable(name):
    path = Path(name)
    suffix = path.suffix
    if suffix in _SWEEPABLE or suffix.startswith('.part-Frag'):
        return True
    return bool(_INTERMEDIATE_STEM.search(path.stem))


def _sweep_stale(outdir):
    """Remove day-old yt-dlp fragments in a folder we own.

    Only in the term folder this job writes to, and only by age: a .part from
    THIS run is yt-dlp's resume state and deleting it costs the download.
    """
    cutoff = time.time() - STALE_AFTER
    try:
        for p in Path(outdir).glob('*'):
            if not p.is_file():
                continue
            if not _sweepable(p.name):
                continue
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                continue
    except OSError as exc:  # noqa: BLE001
        log.warning('could not sweep %s (%s)', outdir, exc)


# What _disown_output renames a leftover to. Not deleted: a half-converted VP9
# original is still footage somebody may want, and the disk cost is visible.
DISOWNED_SUFFIX = '.failed'


def _id_bearing_files(outdir, vid):
    """{name} of everything in outdir whose name carries `[vid]`.

    Matched by substring rather than by glob: a video id may contain any of
    `[]-_`, and one bad escape here silently matches nothing.
    """
    try:
        return {p.name for p in Path(outdir).iterdir()
                if p.is_file() and f'[{vid}]' in p.name}
    except OSError:
        return set()


def _clear_partials(outdir, vid):
    """Delete THIS clip's own in-progress leftovers. Never fatal.

    SAQBbd1Rxmo (2026-08-13): the give-up left a 10 MB
    `... [SAQBbd1Rxmo].f137.mp4.part` in the term folder forever. The lane
    filters exclude `*.part` so it never syncs anywhere, but it sits in the
    CANONICAL tree as a corpse -- and yt-dlp resumes a .part, so the next
    attempt starts from the poisoned bytes and dies the same way.

    Scoped to the `[id]` segment the outtmpl puts in every name, never a glob of
    the folder: the term folder is shared with every other clip of the search
    (and, for a paste, with the whole project's Youtube root), and a .part in
    there may well belong to a download that is still running. The age rule in
    _sweep_stale owns everything this does not.
    """
    for name in _id_bearing_files(outdir, vid):
        if not _sweepable(name):
            continue
        try:
            (Path(outdir) / name).unlink()
        except OSError as exc:  # noqa: BLE001
            log.warning('could not remove %s in %s (%s); a later retry may '
                        'resume from it', name, outdir, exc)


def _landed_file(outdir, vid):
    """The FINISHED file `vid` left in `outdir`, or None.

    Built on _id_bearing_files -- the same substring scan the corpse cleanup
    uses, and for the same reason: a video id may contain any of `[]-_` and one
    bad glob escape here silently matches nothing.

    What it then rejects is what "finished" excludes: yt-dlp's own in-flight
    litter (_sweepable), output a failed attempt disowned (DISOWNED_SUFFIX),
    and anything whose id is not the LAST thing in the stem -- which is the
    disk-scan dedupe's anchoring rule (ytsearch._ID_RE, YTDL-27) and is what
    keeps `... [id].credits.json` and `... [id].editready.mp4` from being read
    as the clip itself.
    """
    for name in sorted(_id_bearing_files(outdir, vid)):
        if _sweepable(name) or name.endswith(DISOWNED_SUFFIX):
            continue
        if Path(name).stem.endswith(f'[{vid}]'):
            return name
    return None


def _disown_output(outdir, vid, before):
    """Rename whatever this failed attempt left behind so dedupe ignores it.

    YTDL-3 (2026-08-11): a download that got as far as a real file and then died
    in ensure_edit_ready (ffmpeg error, full disk) left `... [id].mp4` in the
    term folder -- 0600, unledgered, undecodable by Resolve, and carrying the
    `[id]` the disk scan reads. Every later search marked the video "already in
    the fleet" and pointed the editor at a file they cannot even open over SMB,
    with no route back through the UI. Only files that were NOT there before
    this attempt are touched, and yt-dlp's resume state is left alone.
    """
    for name in _id_bearing_files(outdir, vid) - set(before):
        p = Path(outdir) / name
        if _sweepable(name):
            continue  # yt-dlp's own resume state; the next attempt wants it
        try:
            p.rename(p.with_name(name + DISOWNED_SUFFIX))
        except OSError as exc:  # noqa: BLE001
            log.warning('could not disown %s (%s); it may block re-downloading '
                        '%s until it is removed by hand', p, exc, vid)


# --------------------------------------------------- a truncated DASH stream

# The signature, the rung and the note all live in ytdl_common now (imported at
# the top of this file): the local executor has to make the SAME call from the
# same evidence, or the fleet ends up with one clip at 1080p on the NAS and the
# same clip at 720p on an editor's machine, or a failure on one side and a
# silent downgrade on the other. The reasoning that produced them -- and the
# 2026-08-13 incident it came from -- travels with them.


def _lower_quality(quality):
    """The rung below `quality`, or None when there is nothing below it.

    The rule is ytdl_common's (shared with the companion); the TABLE it is read
    out of stays downloader.QUALITY_HEIGHTS, because the format string the retry
    actually downloads with is built from that same dict and a second quality
    table would be a second thing to forget.
    """
    return ytdl_common.lower_quality(quality, downloader.QUALITY_HEIGHTS)


def _download_video(job_id, vid, url, outdir, quality, hook, status):
    """downloader.download(), with ONE lower rung tried on a truncated stream.

    -> (summary, note). `note` is None on the ordinary path and the downgrade
    line when the lower rung is what actually landed, so the clip row can say
    so. Anything else raises exactly what it always raised.

    ONE rung, not the whole ladder: 1080p -> 720p is what the incident needed,
    and walking a ladder blindly would turn a bad afternoon on YouTube's side
    into 480p footage in the canonical tree with nobody the wiser.
    """
    def attempt(q):
        return downloader.download(
            url, str(outdir), quality=q,
            progress_hook=hook, write_sidecar=True, edit_codec='h264',
            ffmpeg_location=config.FFMPEG_DIR or None,
            cookies_file=config.COOKIES_FILE or None,
            on_status=status)

    try:
        return attempt(quality), None
    except Exception as exc:  # noqa: BLE001 - re-raised unless it is THE case
        lower = _lower_quality(quality) if _stream_truncated(exc) else None
        if lower is None:
            raise
        log.warning('job %s: %s came back truncated at %s (%s); retrying at %s',
                    job_id, vid, quality, exc, lower)
        # The .part IS the truncated bytes, and yt-dlp resumes a .part -- the
        # retry has to start from nothing or it inherits the corpse.
        _clear_partials(outdir, vid)
        if status:
            status(f'{quality} stream truncated; retrying at {lower}')
        try:
            return attempt(lower), TRUNCATED_NOTE.format(q=quality, lower=lower)
        except Exception as exc2:  # noqa: BLE001
            # Wrapped rather than re-raised bare so the row says why it failed
            # twice. exc2's own text is carried through verbatim, which is what
            # the bot-check classifier at the call site reads.
            raise RuntimeError(
                f'{quality} stream truncated by YouTube and the {lower} '
                f'retry failed too: {exc2}') from exc2


def _record_failure(c, job_id, vid, outdir, before, error):
    """One dead video: disown what it landed, delete what it half-landed.

    The corpse cleanup is here rather than only on the truncation path because
    ANY final failure can leave a .part behind (SAQBbd1Rxmo, 2026-08-13), and a
    clip that has finished failing has no resume state worth keeping -- the row
    goes back to `pending` on a re-run and starts over.
    """
    _disown_output(outdir, vid, before)
    _clear_partials(outdir, vid)
    db.set_video(c, job_id, vid, dl_state='failed', dl_error=str(error)[:500])
    db.bump(c, job_id, 'dl_failed')
    _clear_progress(job_id, vid)


# ------------------------------------------------- the pre-download dedupe

def duplicate_location(c, job, vid, outdir, on_disk=None):
    """Where the fleet ALREADY has this clip, as the badge spells it, or None.

    REQ 6's last line of defence, made immediately before the bandwidth is
    spent: between review and download another editor's job may have fetched
    the same video, and a job resumed after a restart may have finished this one
    already -- its .part turned into a real file that no row knows about.

    Two sources, in cost order. The LEDGER answers through db.ledger_where --
    the two halves of the same "ALREADY IN" string must not disagree (YTDL-31,
    2026-08-11), and a paste's clip is in Youtube/ itself with no folder name of
    its own. The DISK answers with LOCATIONS, not just ids: for a paste `outdir`
    is the project's whole Youtube tree, so a clip that is really in a search's
    term folder must be named as being there rather than as being loose in the
    root.

    `on_disk` is the scan, hoisted out for a caller that has several clips to
    ask about (routes_fleet's manifest, YTDL-WEB-3): the worker leaves it None
    and scans per video on purpose -- the point of its check is that it is made
    immediately before the download, and its clips are 3 s apart anyway.
    """
    held = db.ledger_get(c, vid)
    if held is not None:
        return db.ledger_where(held)
    if on_disk is None:
        on_disk = ytsearch.existing_id_locations(outdir)
    if vid in on_disk:
        return f"{job['project_label']}/{on_disk[vid]}"
    return None


def mark_duplicate(c, job_id, vid, where):
    """One clip the fleet already has -> `skipped`, with where to find it.

    The row shape BOTH executors' paths write (worker._phase_download and the
    download-manifest's re-check, YTDL-WEB-3): deselected as well as skipped, so
    a later DOWNLOAD press does not queue it again.
    """
    db.set_video(c, job_id, vid, dl_state='skipped', duplicate=1, selected=0,
                 duplicate_of=where)


# ------------------------------------------- taking a job back from an editor

def _reclaim_local_job(c, job, outdir):
    """An editor's lease expired. Take the job back and re-queue only what is
    MISSING. -> (clips found already landed, clips queued for the server).

    The laptop closed, the tray upgraded mid-job, the companion was killed
    (docs/YTDL_LOCAL_DOWNLOAD.md §11). The lease is how that becomes
    recoverable rather than a job that hangs forever, and this is what happens
    when it runs out.

    MISSING is decided against the DISK, not just against the rows: a clip that
    finished on the editor's machine arrives on the NAS by lane A carrying the
    `[video_id]` in its name, and the status post that would have recorded it
    may be exactly what the closed laptop lost. Re-downloading it would spend
    the bandwidth twice and (worse) hand YouTube a second request for a video
    the fleet already has.

    A clip that IS on disk is recorded `done` with a ledger row rather than left
    to the pre-download dedupe's `skipped`: the ledger is what tells every other
    editor's search that the fleet already has this video, and a skipped row
    tells nobody anything.

    Everything else -- pending, half-downloaded, or failed on the editor's IP --
    goes back to `pending`, which is the second chance (§2 step 7) arriving
    through the reclaim path instead of through job close.
    """
    job_id = job['id']
    holder = job['claimed_by'] or 'an editor'
    log.warning('job %s: the local download lease held by %s expired; the '
                'server is taking the job back', job_id, holder)
    db.reclaim_download(c, job_id)

    landed = queued = refailed = 0
    for v in db.videos(c, job_id):
        if v['dl_state'] not in db.UNFINISHED_STATES + ('failed',):
            continue                    # done, skipped, or never selected
        vid = v['video_id']
        name = _landed_file(outdir, vid)
        if name is not None:
            rel = '/'.join(p for p in (db.YOUTUBE_DIR, job['term_dir'], name) if p)
            db.set_video(c, job_id, vid, dl_state='done',
                         filepath=str(Path(outdir) / name), dl_error=None,
                         download_host=v['download_host'] or holder)
            db.ledger_add(c, vid, v['title'], v['channel'], job['project_slug'],
                          job['project_label'], job['term'], rel, job_id,
                          job['created_by'])
            db.bump(c, job_id, 'dl_done')
            landed += 1
            continue
        if v['dl_state'] == 'failed':
            # The counter tracks clips that are failed RIGHT NOW; this one is
            # queued again, and the retry will bump it back if it fails again.
            refailed += 1
        db.set_video(c, job_id, vid, dl_state='pending', dl_error=None)
        queued += 1
    if refailed:
        db.bump(c, job_id, 'dl_failed', -refailed)

    log.info('job %s: reclaimed from %s -- %d clip(s) already landed, %d to '
             'download here', job_id, holder, landed, queued)
    return landed, queued


def _await_local_claim(c, job_id, sleep=time.sleep):
    """Give the requester's machine first refusal on this job. -> did it claim.

    CR-34 (2026-08-19), and it is a scheduling bug rather than a logic one:
    every guard around the two executors was correct and the outcome was still
    wrong. `start_download` writes the pending rows and nudges this worker in
    one request; the SPA then probes 127.0.0.1:8899 and the companion claims.
    Measured live: claim at T+161 ms, worker already holding the only row. The
    companion asked for its manifest, was told 0 clips -- truthfully, the row
    was `downloading` on the server by then -- logged "0 clip(s)" and stood
    down. The clip landed on the NAS, where lane B has not brought YouTube
    originals down since 2026-08-16. Nothing was corrupted; the editor simply
    never got their footage, on every selection small enough that the worker
    did not still have clips left to hand back.

    Polled rather than evented because the claim arrives on a request thread in
    this process today and might not tomorrow (the row in SQLite is the only
    thing both ends agree on), and because the poll is the honest expression of
    "wait for at most N seconds": it ends the instant a lease appears.
    """
    if not config.LOCAL_DOWNLOAD or config.LOCAL_CLAIM_GRACE_SECONDS <= 0:
        return False
    deadline = time.monotonic() + config.LOCAL_CLAIM_GRACE_SECONDS
    while time.monotonic() < deadline:
        if db.lease_active(db.get_job(c, job_id)):
            log.info('job %s: the requester claimed it during the grace '
                     'period; the server stands down', job_id)
            return True
        sleep(0.1)
    return False


def _phase_download(c, job):
    """Fetch the editor's selection into <project>/Youtube/<term_dir>/.

    Shared verbatim by both kinds of job: a url job arrives here with rows the
    API wrote instead of rows the review grid selected, and everything below --
    the outtmpl, the edit-ready conversion, the 0664/2775 widening, the ledger,
    the dedupe re-check, the manifest -- is the same code for the same reason.

    An EMPTY term_dir is a paste, and it lands in <project>/Youtube/ itself
    (owner, 2026-08-11: there is no term to sort individual downloads by, so a
    folder per paste was clutter with nothing in it). safe_join drops the empty
    segment, so this is one expression for both shapes. Neither goes deeper than
    one level under Youtube/, which is what the companion's youtube_import
    watcher walks -- it lists that level and files each folder into
    Master/Youtube/<folder>, and collects the loose clips in the root itself
    from companion 0.7.1.
    """
    job_id = job['id']
    outdir = config.safe_join(config.PROJECTS_ROOT, job['project_label'],
                              'Youtube', job['term_dir'])
    ensure_outdir(outdir)
    _sweep_stale(outdir)

    # Reached with download_mode='local' only when the lease has EXPIRED --
    # run_job returns early while it is live, and db.claim_next_job hides the
    # job from the loop entirely. So this is the reclaim, and it runs before the
    # pending list is read because it is what decides what is still pending.
    if job['download_mode'] == db.MODE_LOCAL:
        _reclaim_local_job(c, job, outdir)

    # Hold the door open for the requester's own machine (CR-34). See
    # config.LOCAL_CLAIM_GRACE_SECONDS: without this the worker takes the first
    # row ~160 ms before the browser's claim can land, and every one-or-two-clip
    # selection downloads onto the NAS instead of onto the editor's disk.
    #
    # Returning here rather than falling through to the loop (whose first
    # iteration would make the same check and the same exit) only because the
    # explicit version cannot be broken by a later edit to the loop. A claim
    # that arrives AFTER the grace is still handled exactly as before.
    if _await_local_claim(c, job_id):
        _clear_progress(job_id)
        return

    pending = db.pending_videos(c, job_id)
    if not job['dl_total']:
        # Normally the API sets this when the editor presses DOWNLOAD; a job
        # resumed after a restart has to recount.
        db.set_job(c, job_id, dl_total=len(pending))

    for i, v in enumerate(pending):
        if _cancelled(c, job_id):
            _clear_progress(job_id)
            return
        # ...and re-read the LEASE between clips, for the same reason the cancel
        # flag is re-read: it arrives on a request thread while this loop is
        # running. The race is not exotic, it is the NORMAL order of events once
        # companion 0.8.0 ships -- start_download nudges the worker in the same
        # millisecond the SPA starts probing the requester's loopback, so the
        # worker is usually a clip or two in by the time the claim lands. Both
        # executors downloading the same clips into one canonical tree is the
        # thing this whole feature exists to avoid, so the server steps back.
        #
        # Checked HERE, at the top of the iteration, so nothing is left mid
        # -flight: no row has been moved to `downloading` yet, so every clip
        # this loop has not reached is still `pending` and lands in the
        # manifest the companion is about to ask for.
        if db.lease_active(db.get_job(c, job_id)):
            log.info('job %s: claimed by an editor mid-phase; the server is '
                     'standing down after %d clip(s)', job_id, i)
            _clear_progress(job_id)
            return
        vid = v['video_id']

        # TAKE THE ROW FIRST, before the dedupe scan below spends up to a second
        # on an rglob (YTDL-WEB-4, 2026-08-14). The lease check above is a JOB
        # -level check made once per clip; a claim landing after it was invisible
        # to this iteration, and the clip -- still `pending` -- was still in the
        # manifest the companion asks for the moment its claim lands. Two yt-dlp
        # processes then wrote the same `[id]` fragments into one directory and
        # each one's give-up path deleted the other's resume state. The
        # compare-and-set is what makes the row, not the job, the boundary: from
        # here on the companion's manifest cannot list this clip.
        if not db.begin_download(c, job_id, vid):
            continue

        # Re-check the dedupe immediately before spending bandwidth.
        where = duplicate_location(c, job, vid, outdir)
        if where:
            mark_duplicate(c, job_id, vid, where)
            continue

        # download_host is written HERE, once, rather than on each outcome: from
        # this line on the clip belongs to the server's IP whatever happens to
        # it, and the history panel's "whose machine got this" must be right for
        # the failures too (docs/YTDL_LOCAL_DOWNLOAD.md §4).
        db.set_video(c, job_id, vid, dl_state='downloading', dl_error=None,
                     download_host=db.MODE_SERVER)

        def hook(d, _vid=vid, _job=job_id):
            # Several times a second: memory only, merged into the poll
            # response by routes_api. See the module docstring.
            if d.get('status') == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                got = d.get('downloaded_bytes') or 0
                _set_progress(_job, _vid, {
                    'percent': round(got * 100.0 / total, 1) if total else None,
                    'speed': (d.get('_speed_str') or '').strip(),
                    'status': 'downloading'})
            elif d.get('status') == 'finished':
                _set_progress(_job, _vid, {'percent': 100.0, 'speed': '',
                                           'status': 'merging'})

        def status(msg, _vid=vid, _job=job_id):
            # ensure_edit_ready's "converting to H.264 (was vp9)" -- minutes of
            # container CPU, and the one phase where silence looks like a hang.
            cur = dict(_progress.get(_job, {}).get(_vid) or {})
            cur['status'] = msg
            _set_progress(_job, _vid, cur)

        before = _id_bearing_files(outdir, vid)
        try:
            # `note` is the quality downgrade, when the clip only landed
            # because the rung below the editor's choice was tried.
            res, note = _download_video(job_id, vid, v['url'], outdir,
                                        job['quality'], hook, status)
        except Exception as exc:  # noqa: BLE001 - one dead video, not one dead job
            # exc_info since CR-33: the clip row shows the editor `str(exc)`,
            # which for that bug was "[Errno 13] Permission denied:
            # '/tmpf1m0z55x.tmp'" -- a path that appears nowhere in this repo,
            # from a frame nothing recorded. Diagnosing it needed the failure
            # reproduced by hand inside the container. The traceback costs a few
            # lines in the container log and is the difference between a bug
            # report and a bug hunt; the editor-facing text is unchanged.
            log.warning('job %s: download failed for %s (%s)', job_id, vid, exc,
                        exc_info=True)
            _record_failure(c, job_id, vid, outdir, before, exc)
            if _bot_checked(exc):
                raise BotCheckError(BOT_CHECK_NOTE) from exc
            continue

        filepath = res.get('filepath')
        if not filepath:
            # YTDL-15 (2026-08-11): no filepath means the download did not land,
            # whatever else the summary says. Recording it `done` wrote a ledger
            # row with an EMPTY rel_path -- a permanent "the fleet already has
            # this" pointing at nothing, and the ledger never cascades, so only
            # hand-editing ytdl.db could undo it.
            log.warning('job %s: download for %s returned no file', job_id, vid)
            _record_failure(c, job_id, vid, outdir, before,
                            'the downloader reported no output file')
            continue

        _chmod(filepath, 0o664)
        # The sidecar is what the Resolve credits script reads; a 0600 one
        # is as invisible to the editor as an unreadable video.
        sidecar = res.get('sidecar')
        if sidecar:
            _chmod(sidecar, 0o664)
        # 'Youtube/<term_dir>/<file>' for a search, 'Youtube/<file>' for a
        # paste. Joined by dropping the empty part rather than by string
        # concatenation: 'Youtube//x.mp4' would be a rel_path nothing downstream
        # could split back into a folder (db._term_dir_of, the badge, the
        # history panel's destination line).
        rel = '/'.join(p for p in (db.YOUTUBE_DIR, job['term_dir'],
                                   os.path.basename(filepath)) if p)

        # The title comes back from yt-dlp here, and for a url job it is the
        # FIRST time anything knows it: those rows are created from a pasted
        # link with no metadata fetch behind them, so without this the progress
        # list names every clip by its 11-char id forever.
        # dl_error on a DONE row is the downgrade note, not a failure: the clip
        # landed, just not at the rung that was asked for, and this row is the
        # only place that would ever say so (SAQBbd1Rxmo, 2026-08-13). It is
        # None on every ordinary download, which is what the row already holds.
        db.set_video(c, job_id, vid, dl_state='done', filepath=filepath,
                     dl_error=note,
                     title=res.get('title') or v['title'],
                     thumbnail=res.get('thumbnail') or v['thumbnail'])
        db.ledger_add(c, vid, res.get('title') or v['title'],
                      res.get('channel') or v['channel'],
                      job['project_slug'], job['project_label'], job['term'],
                      rel, job_id, job['created_by'])
        db.bump(c, job_id, 'dl_done')
        _clear_progress(job_id, vid)

        if config.DOWNLOAD_PAUSE and i < len(pending) - 1:
            time.sleep(config.DOWNLOAD_PAUSE)

    _clear_progress(job_id)
    write_manifest(c, job_id, outdir)
    # `done` even with per-video failures: those are visible per row, and a job
    # that fetched 38 of 41 clips is not a failed job. `failed` is reserved for
    # the pipeline itself dying.
    db.set_phase(c, job_id, 'done')


def manifest_name(job):
    """`manifest.json`, or `manifest.<job id>.json` in the Youtube root.

    A term folder belongs to ONE search, so the flat name batch_dl.py
    established is right there and a re-run of the same term is meant to replace
    it. The root belongs to every paste this project will ever receive, and
    those are different jobs by different editors on different days -- one
    filename there would mean each paste silently destroyed the provenance of
    the last (2026-08-11, when pasted links moved into the root).
    """
    return 'manifest.json' if job['term_dir'] else f"manifest.{job['id']}.json"


def write_manifest(c, job_id, outdir):
    """Drop a provenance manifest (0664) beside the clips.

    Same shape batch_dl.py writes, because that convention already exists and
    the companion, the editors and a future re-run all read the folder rather
    than this database. It is also the only record of WHY a clip is in that
    folder that survives ytdl.db being lost.
    """
    job = db.get_job(c, job_id)
    if job is None:
        return None
    path = Path(outdir) / manifest_name(job)
    try:
        path.write_text(db.dumps(db.manifest_json(c, job)), encoding='utf-8')
    except OSError as exc:  # noqa: BLE001 - provenance is not worth failing a job
        log.warning('could not write %s (%s)', path, exc)
        return None
    _chmod(path, 0o664)
    return path
