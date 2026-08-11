"""The JSON API. Every handler is sync, SQLite-only, and finishes in millisecs.

Nothing here does network I/O, shells out, or waits on anything: the dashboard
runs uvicorn with **workers=1**, so a handler that blocks blocks the fleet
status page too. All the slow work belongs to worker.py, and the only thing
these routes do about it is write a row and ring the bell (`worker.nudge()`).

Two rules that are not negotiable, both enforced in more than one place on
purpose:
  - **a job belongs to the editor who created it.** Every job route loads it
    through db.get_job_for(id, user), which filters in SQL -- an unowned job is
    404, not 403, because "there is no such job" is all another editor is
    entitled to know.
  - **the destination project is re-validated server-side** on every write.
    The picker in the browser is a convenience; projects.resolve_project() is
    the check. Without it an editor could post any slug and drop 40 videos into
    a project they do not sync.
"""
import logging
import shutil
import sqlite3

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ytdlweb import claude_cli, config, db, projects, worker
from ytdlweb.db import con
from ytdlweb.session import current_user
from ytdlweb.vendor import ytsearch

log = logging.getLogger(__name__)
router = APIRouter()


def _job_or_404(c, job_id, user):
    job = db.get_job_for(c, job_id, user)
    if job is None:
        raise HTTPException(404, 'no such job')
    return job


@router.get('/api/me')
def me(request: Request):
    return {'user': current_user(request)}


@router.get('/api/health')
def health(request: Request):
    """Is this thing usable, before anyone submits a job.

    The claude answer comes from claude_cli's CACHE, refreshed by the worker at
    start and whenever a live call fails -- never by probing here. `claude -p`
    costs a second or two and this endpoint is hit by every page load; a probe
    per request would turn an open tab into a subprocess factory.
    """
    current_user(request)
    cached = claude_cli.health()
    return {
        'claude': cached['claude'],            # ok|unauthenticated|missing|timeout|error|unknown
        'claude_detail': cached['detail'],
        'yt_dlp': _yt_dlp_state(),
        'js_runtime': _js_runtime_state(),
        'worker_alive': worker.is_alive(),
        'cookies': bool(config.COOKIES_FILE),
    }


def _yt_dlp_state():
    """'ok' | 'missing'. Import-only; yt-dlp is lazy everywhere else too."""
    try:
        import yt_dlp  # noqa: F401
    except Exception:  # noqa: BLE001
        return 'missing'
    return 'ok'


# yt-dlp runs YouTube's player JS to resolve formats and needs one of these on
# PATH; the container provisions deno (DEPLOY.md).
_JS_RUNTIMES = ('deno', 'node')


def _js_runtime_state():
    """'ok' | 'missing'. A PATH lookup, no subprocess.

    Without a JS runtime every video fails with "Requested format is not
    available" -- which reads as YouTube flakiness, per video, while health
    reported all-ok (YTDL-24, 2026-08-11). One `which` is the difference
    between an ops instruction and a week of misdiagnosis.
    """
    return 'ok' if any(shutil.which(b) for b in _JS_RUNTIMES) else 'missing'


@router.get('/api/projects')
def list_projects(request: Request):
    """The caller's ticked projects, straight from the dashboard database."""
    user = current_user(request)
    result = projects.ticked_projects(user)
    return {'projects': result['projects'],
            'projects_available': result['available'],
            'error': result['error']}


class NewJob(BaseModel):
    term: str
    project_slug: str
    quality: str = '1080p'
    period: str | None = None
    max_per_term: int = 15


# A topic, not a document. The cap is a fleet-availability guard as much as a
# UI one (YTDL-7, 2026-08-11): the term is one argv element of the `claude -p`
# call, Linux caps a single argument at 128 KiB, and the resulting OSError was
# classified as "the claude CLI is not installed" -- pinning that false banner
# on every editor's page until the container restarted.
MAX_TERM_CHARS = 400


@router.post('/api/jobs')
def create_job(req: NewJob, request: Request):
    user = current_user(request)
    term = (req.term or '').strip()
    if not term:
        raise HTTPException(400, 'a search topic is required')
    if len(term) > MAX_TERM_CHARS:
        raise HTTPException(
            400, f'a search topic must be {MAX_TERM_CHARS} characters or fewer '
                 f'(that one is {len(term)})')

    project = projects.resolve_project(user, req.project_slug)
    if project is None:
        raise HTTPException(
            400, 'that project is not one you are syncing. Tick it on the '
                 'dashboard first -- downloads go into the projects you sync.')
    if req.period and req.period not in ytsearch.PERIOD_SP:
        raise HTTPException(400, f'unknown period {req.period!r}')
    if req.quality not in ('best', '2160p', '1440p', '1080p', '720p', '480p'):
        raise HTTPException(400, f'unknown quality {req.quality!r}')

    c = con()
    # One job per editor at a time. Not a resource limit -- the worker is
    # serial anyway -- but a UI one: two jobs would share the progress bar and
    # the second manifest would silently replace the first.
    running = db.active_job(c, user)
    if running is not None:
        raise _one_job_409(running)

    try:
        job_id = db.create_job(
            c, user, term, config.safe_term_dirname(term), project['slug'],
            project['label'], quality=req.quality, period=req.period or None,
            max_per_term=max(1, min(50, int(req.max_per_term))))
    except sqlite3.IntegrityError:
        # The read above and this INSERT are not one transaction, and a
        # double-clicked SEARCH lands squarely between them; the partial unique
        # index on jobs(created_by) is what makes the loser an error rather
        # than a second active job that orphans the first (YTDL-25,
        # 2026-08-11). Same answer either way -- one editor, one job.
        running = db.active_job(c, user)
        if running is None:
            raise
        raise _one_job_409(running) from None
    worker.nudge()
    return {'job_id': job_id, 'phase': 'queued'}


def _one_job_409(running):
    return HTTPException(409, {
        'detail': 'you already have a job in progress',
        'job_id': running['id'], 'phase': running['phase']})


@router.get('/api/jobs')
def list_jobs(request: Request, limit: int = 20):
    user = current_user(request)
    return {'jobs': [db.job_dict(r) for r in
                     db.recent_jobs(con(), user, max(1, min(100, limit)))]}


@router.get('/api/jobs/{job_id}')
def get_job(job_id: int, request: Request):
    """THE poll endpoint. Called every 1500 ms while a job is running.

    Everything the progress bar and the ticker need in one round trip: the job
    row (all counters), the terms with their glosses and hit counts, and the
    in-memory download percentages merged in from the worker.
    """
    user = current_user(request)
    c = con()
    job = _job_or_404(c, job_id, user)
    hits = db.term_hit_counts(c, job_id)
    return {
        'job': db.job_dict(job),
        'terms': [{'id': t['id'], 'term': t['term'], 'lang': t['lang'],
                   'english_gloss': t['english_gloss'], 'source': t['source'],
                   'searched': t['searched'], 'hits': t['hits'],
                   'videos': hits.get(t['id'], 0)}
                  for t in db.terms(c, job_id)],
        'counts': db.counts(c, job_id),
        'progress': worker.job_progress(job_id),
        'worker_alive': worker.is_alive(),
    }


@router.get('/api/jobs/{job_id}/manifest')
def manifest(job_id: int, request: Request):
    """The review grid's dataset: every video, every term, the header counts."""
    user = current_user(request)
    c = con()
    job = _job_or_404(c, job_id, user)
    tids = db.term_ids_by_video(c, job_id)
    hits = db.term_hit_counts(c, job_id)
    return {
        'job': db.job_dict(job),
        'videos': [db.video_dict(v, tids.get(v['video_id'])) for v in db.videos(c, job_id)],
        'terms': [{'id': t['id'], 'term': t['term'], 'lang': t['lang'],
                   'english_gloss': t['english_gloss'], 'source': t['source'],
                   'hits': t['hits'], 'videos': hits.get(t['id'], 0)}
                  for t in db.terms(c, job_id)],
        'counts': db.counts(c, job_id),
    }


class Toggle(BaseModel):
    selected: bool = True


@router.post('/api/jobs/{job_id}/videos/{video_id}/select')
def select_one(job_id: int, video_id: str, req: Toggle, request: Request):
    user = current_user(request)
    c = con()
    _job_or_404(c, job_id, user)
    row = db.get_video(c, job_id, video_id)
    if row is None:
        raise HTTPException(404, 'no such video on this job')
    if row['duplicate']:
        # REQ 6 is "never re-downloaded", not "shown differently" -- so the
        # refusal is here AND in db.select_video's WHERE clause.
        raise HTTPException(409, {
            'detail': 'already downloaded, so it cannot be selected',
            'duplicate_of': row['duplicate_of']})
    db.select_video(c, job_id, video_id, req.selected)
    return {'ok': True, 'selected': bool(req.selected), 'counts': db.counts(c, job_id)}


class BulkSelect(BaseModel):
    selected: bool = True
    scope: str = 'relevant'          # 'relevant' | 'all'


@router.post('/api/jobs/{job_id}/select')
def select_bulk(job_id: int, req: BulkSelect, request: Request):
    user = current_user(request)
    c = con()
    _job_or_404(c, job_id, user)
    n = db.bulk_select(c, job_id, req.selected,
                       'all' if req.scope == 'all' else 'relevant')
    return {'ok': True, 'changed': n, 'counts': db.counts(c, job_id)}


@router.post('/api/jobs/{job_id}/download')
def start_download(job_id: int, request: Request):
    """Hand the editor's selection to the worker.

    `done` is accepted as well as `ready_for_review` (YTDL-16, 2026-08-11): the
    download phase ends `done` even when three of forty-one clips failed on a
    throttle, and without this the only retry was a whole new search -- another
    Claude spend and another twenty minutes of yt-dlp. Nothing else changes:
    mark_pending re-queues exactly the rows that failed or were never fetched,
    and answers 400 when there are none.
    """
    user = current_user(request)
    c = con()
    job = _job_or_404(c, job_id, user)
    if job['phase'] not in ('ready_for_review', 'done'):
        raise HTTPException(409, {
            'detail': f'this job is {job["phase"]}, not ready for review',
            'phase': job['phase']})
    if job['phase'] == 'done':
        # Reviving a finished job makes it active again, and one editor gets
        # one active job -- in the database as well as here (YTDL-25).
        running = db.active_job(c, user)
        if running is not None:
            raise _one_job_409(running)

    # The destination is re-validated on every write, and a manifest can sit at
    # review for a week -- long enough for the project to be unticked or
    # retired, after which nobody syncs or watches the tree these clips would
    # land in (YTDL-30, 2026-08-11).
    if projects.resolve_project(user, job['project_slug']) is None:
        raise HTTPException(409, {
            'detail': f'{job["project_label"]} is no longer a project you sync, '
                      'so nothing can be downloaded into it. Tick it on the '
                      'dashboard again, or start a new search.',
            'phase': job['phase']})

    n = db.mark_pending(c, job_id)
    if not n:
        raise HTTPException(400, 'nothing is selected that has not already '
                                 'been downloaded')
    # A cancel the worker never got to honour must not survive into the run the
    # editor is asking for right now (YTDL-1).
    db.clear_cancel(c, job_id)
    db.set_job(c, job_id, dl_total=n, dl_done=0, dl_failed=0)
    db.set_phase(c, job_id, 'downloading')
    worker.nudge()
    return {'ok': True, 'queued': n}


@router.post('/api/jobs/{job_id}/cancel')
def cancel(job_id: int, request: Request):
    """Ask for a stop. Honoured between terms and between videos, never mid-file.

    A flag rather than a kill: the worker owns the yt-dlp call and tearing that
    down from another thread is how a half-merged mp4 ends up in a project.

    THE FLAG IS NOT ENOUGH ON ITS OWN. It is read inside run_job, and the
    worker never enters run_job for a job that is `queued`-but-unclaimed or
    sitting at `ready_for_review` -- so cancelling a manifest used to answer
    {ok:true} and change nothing, leaving an active job that 409'd every later
    search with no way out but editing ytdl.db by hand (YTDL-1, 2026-08-11).
    Those two phases have no phase in flight, so they are cancelled outright.
    """
    user = current_user(request)
    c = con()
    job = _job_or_404(c, job_id, user)
    if job['phase'] in db.TERMINAL:
        return {'ok': True, 'phase': job['phase'], 'note': 'already finished'}
    if db.cancel_now(c, job_id):
        return {'ok': True, 'phase': 'cancelled'}
    db.request_cancel(c, job_id)
    worker.nudge()
    return {'ok': True, 'phase': job['phase']}
