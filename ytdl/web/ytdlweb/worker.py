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
import threading
import time
from pathlib import Path

from ytdlweb import claude_cli, config, db
from ytdlweb.vendor import downloader, ytsearch

log = logging.getLogger(__name__)

_thread = None
_thread_lock = threading.Lock()
_nudge = threading.Event()

# {job_id: {video_id: {'percent': float, 'speed': str, 'status': str}}}. Poll
# reads it, the download hook writes it; a dict assignment is atomic enough for
# both under the GIL and a torn read here costs a wrong percentage for 1.5 s.
_progress = {}

# How long the loop sleeps when there is nothing to do. Short enough that a
# missed nudge (there is no such path today, but there is also no way to prove
# it forever) costs seconds rather than forever.
IDLE_WAIT = 5.0

# Leftovers older than this in a folder we own get swept. yt-dlp resumes its
# own .part within a run; a day-old one belongs to a container that is gone.
STALE_AFTER = 24 * 3600


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

def _run():
    """The thread body. Never returns; never lets an exception out."""
    c = db.con()
    try:
        restarted, resumed = db.reset_stale_jobs(c)
        if restarted or resumed:
            log.info('boot recovery: %d job(s) restarted from scratch, %d '
                     'in-flight download(s) put back to pending', restarted, resumed)
    except Exception:  # noqa: BLE001 - a broken sweep must not cost us the worker
        log.exception('boot recovery failed; continuing')

    # One probe at start so the SPA can warn about a logged-out claude before
    # anyone submits a job. On the worker thread on purpose: it costs a second
    # or two and must never be paid on a request.
    try:
        claude_cli.refresh_health(force=True)
    except Exception:  # noqa: BLE001
        log.exception('claude health probe failed')

    while True:
        worked = False
        try:
            worked = _tick(c)
        except Exception:  # noqa: BLE001
            log.exception('worker tick failed')
        if not worked:
            _nudge.wait(IDLE_WAIT)
            _nudge.clear()


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
        handler = handlers.get(job['phase'])
        if handler is None:
            return
        try:
            handler(c, job)
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
    db.set_phase(c, job['id'], 'generating_terms')


def _phase_generate_terms(c, job):
    """Claude call #1: one topic in, EN + ZH search queries out.

    The editor's own term goes in FIRST and unconditionally (source='user'), so
    a job whose expansion is thin still searches what was actually asked for.
    """
    job_id = job['id']
    db.add_term(c, job_id, job['term'],
                'zh' if _looks_chinese(job['term']) else 'en', 'user')

    generated = claude_cli.generate_terms(job['term'])
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
    """
    job_id = job['id']
    for term in db.unsearched_terms(c, job_id):
        if _cancelled(c, job_id):
            return
        try:
            entries = ytsearch.search(term['term'], job['max_per_term'], job['period'])
        except Exception as exc:  # noqa: BLE001
            log.warning('job %s: search failed for %r (%s)', job_id, term['term'], exc)
            entries = []

        new = 0
        for e in entries:
            vid = e.get('id')
            if not vid:
                continue
            url = e.get('url') or f'https://www.youtube.com/watch?v={vid}'
            if db.add_video(c, job_id, vid, url, e.get('title')):
                new += 1
            # Linked for every term that returned it, seen before or not --
            # that is what the manifest's term chips filter on.
            db.link_term(c, job_id, vid, term['id'])
        c.commit()

        db.mark_term_searched(c, term['id'], len(entries))
        db.bump(c, job_id, 'terms_done')
        if new:
            db.bump(c, job_id, 'candidates', new)

    db.set_phase(c, job_id, 'enriching')


# --------------------------------------------------------- 3. the metadata

# Parallelism for the metadata fetch. batch_dl defaults to 8; 4 here, because
# this runs from a datacentre IP against an account-less YouTube and the whole
# job is throttle-shaped rather than CPU-shaped.
ENRICH_JOBS = 4


def _phase_enrich(c, job):
    """Full metadata for every candidate: real durations, dates, thumbnails."""
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
    CHUNK = ENRICH_JOBS * 4
    for start in range(0, len(entries), CHUNK):
        if _cancelled(c, job_id):
            return
        chunk = entries[start:start + CHUNK]
        results = ytsearch.enrich(chunk, jobs=ENRICH_JOBS, progress=_seen)
        for r in results:
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

    # (a) mechanical. A live stream has no fixed duration and cannot be cut
    # with; a missing duration means the metadata fetch got nothing usable.
    for v in rows:
        if v['meta_error']:
            continue
        if not v['duration']:
            db.set_video(c, job_id, v['video_id'], relevant=0, selected=0,
                         relevance_note='live or no duration')

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
            verdicts = claude_cli.filter_relevance(job['term'], payload)
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


def _sweep_stale(outdir):
    """Remove day-old .part / .editready leftovers in a folder we own.

    Only in the term folder this job writes to, and only by age: a .part from
    THIS run is yt-dlp's resume state and deleting it costs the download.
    """
    cutoff = time.time() - STALE_AFTER
    try:
        for p in Path(outdir).glob('*'):
            if not p.is_file():
                continue
            if '.part' not in p.name and '.editready' not in p.name:
                continue
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                continue
    except OSError as exc:  # noqa: BLE001
        log.warning('could not sweep %s (%s)', outdir, exc)


def _phase_download(c, job):
    """Fetch the editor's selection into <project>/Youtube/<term>/."""
    job_id = job['id']
    outdir = config.safe_join(config.PROJECTS_ROOT, job['project_label'],
                              'Youtube', job['term_dir'])
    ensure_outdir(outdir)
    _sweep_stale(outdir)

    pending = db.pending_videos(c, job_id)
    if not job['dl_total']:
        # Normally the API sets this when the editor presses DOWNLOAD; a job
        # resumed after a restart has to recount.
        db.set_job(c, job_id, dl_total=len(pending))

    for i, v in enumerate(pending):
        if _cancelled(c, job_id):
            _clear_progress(job_id)
            return
        vid = v['video_id']

        # Re-check the dedupe immediately before spending bandwidth. Between
        # review and download another editor's job may have fetched the same
        # clip, and a job resumed after a restart may have finished this one
        # already -- its .part turned into a real file that no row knows about.
        held = db.ledger_get(c, vid)
        where = None
        if held is not None:
            where = f"{held['project_label']}/{held['term']}"
        elif vid in ytsearch.existing_ids(outdir):
            where = f"{job['project_label']}/{job['term_dir']}"
        if where:
            db.set_video(c, job_id, vid, dl_state='skipped', duplicate=1,
                         selected=0, duplicate_of=where)
            continue

        db.set_video(c, job_id, vid, dl_state='downloading', dl_error=None)

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

        try:
            res = downloader.download(
                v['url'], str(outdir), quality=job['quality'],
                progress_hook=hook, write_sidecar=True, edit_codec='h264',
                ffmpeg_location=config.FFMPEG_DIR or None,
                cookies_file=config.COOKIES_FILE or None,
                on_status=status)
        except Exception as exc:  # noqa: BLE001 - one dead video, not one dead job
            log.warning('job %s: download failed for %s (%s)', job_id, vid, exc)
            db.set_video(c, job_id, vid, dl_state='failed', dl_error=str(exc)[:500])
            db.bump(c, job_id, 'dl_failed')
            _clear_progress(job_id, vid)
            continue

        filepath = res.get('filepath')
        if filepath:
            _chmod(filepath, 0o664)
            # The sidecar is what the Resolve credits script reads; a 0600 one
            # is as invisible to the editor as an unreadable video.
            sidecar = res.get('sidecar')
            if sidecar:
                _chmod(sidecar, 0o664)
        rel = ('Youtube/' + job['term_dir'] + '/' + os.path.basename(filepath)
               if filepath else '')

        db.set_video(c, job_id, vid, dl_state='done', filepath=filepath,
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


def write_manifest(c, job_id, outdir):
    """Drop a provenance manifest.json (0664) beside the clips.

    Same shape batch_dl.py writes, because that convention already exists and
    the companion, the editors and a future re-run all read the folder rather
    than this database. It is also the only record of WHY a clip is in that
    folder that survives ytdl.db being lost.
    """
    job = db.get_job(c, job_id)
    if job is None:
        return None
    path = Path(outdir) / 'manifest.json'
    try:
        path.write_text(db.dumps(db.manifest_json(c, job)), encoding='utf-8')
    except OSError as exc:  # noqa: BLE001 - provenance is not worth failing a job
        log.warning('could not write %s (%s)', path, exc)
        return None
    _chmod(path, 0o664)
    return path
