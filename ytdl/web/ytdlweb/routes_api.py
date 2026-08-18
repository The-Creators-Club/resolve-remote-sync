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
import re
import shutil
import sqlite3
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ytdlweb import attestation, claude_cli, config, db, projects, worker
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


def _require_attestation(c, user):
    """403 unless `user` has accepted the CURRENT rights/ToS wording.

    Enforced on every route that can cause a download to happen, not only on
    the one the SPA happens to call first: the notice is what records that a
    human took responsibility for the material, and an API caller who skipped
    the page must not be able to skip that (COMMERCIAL_READINESS.md item 2,
    2026-08-17; docs/legal/YOUTUBE_FEATURE_NOTICE.md).

    403 with a machine-readable `reason` so the SPA can re-open the notice
    rather than showing a bare error -- an editor whose acceptance predates a
    re-wording is not doing anything wrong, they just have not read the new
    text yet.
    """
    if db.attestation_of(c, user, attestation.TEXT_VERSION) is None:
        raise HTTPException(403, {'detail': attestation.REFUSAL,
                                  'reason': 'attestation',
                                  'version': attestation.TEXT_VERSION})


@router.get('/api/attestation')
def get_attestation(request: Request):
    """The notice text plus whether THIS editor has accepted it.

    One shape either way (attestation.payload): the copyright notice and the
    rate disclaimer are shown on the page whatever the answer is, and only the
    download gate depends on `accepted`.
    """
    user = current_user(request)
    c = con()
    return attestation.payload(db.attestation_of(c, user, attestation.TEXT_VERSION))


class AcceptAttestation(BaseModel):
    # The version the browser actually displayed. Sent back so a page left
    # open across a deploy that re-worded the notice cannot record acceptance
    # of text the editor never saw.
    version: str = ''


@router.post('/api/attestation')
def accept_attestation(req: AcceptAttestation, request: Request):
    user = current_user(request)
    version = str(req.version or '').strip()
    if version != attestation.TEXT_VERSION:
        raise HTTPException(409, {
            'detail': ('the terms were updated while this page was open -- '
                       'reload and read the new wording before accepting'),
            'reason': 'stale_version',
            'version': attestation.TEXT_VERSION})
    c = con()
    row = db.record_attestation(c, user, attestation.TEXT_VERSION,
                                attestation.text_sha256())
    log.info('attestation %s accepted by %s', attestation.TEXT_VERSION, user)
    return attestation.payload(row)


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
        # WHICH backend that verdict is about (2026-08-18): one of
        # ai_backend.PROVIDER_ORDER, or '' before any call has resolved one.
        # The key is `ai_provider` rather than a rename of `claude` because an
        # editor's cached SPA bundle still reads the old names, and the health
        # pip going blank is a worse failure than an unlabelled one.
        'ai_provider': cached.get('provider', ''),
        'yt_dlp': _yt_dlp_state(),
        'js_runtime': _js_runtime_state(),
        'worker_alive': worker.is_alive(),
        'cookies': bool(config.COOKIES_FILE),
        # Whether this dashboard wants the SPA to offer the requester's own
        # machine the download (docs/YTDL_LOCAL_DOWNLOAD.md §10). The page
        # already asks for health on every load, so gating the loopback probe on
        # it costs no extra round trip -- and with the flag down the probe never
        # happens, which is what makes phase 1 deployable with no behaviour
        # change at all. Not a promise that a companion can do it: that is the
        # probe's answer, and a 404 from an old tray falls back silently.
        'local_download': config.LOCAL_DOWNLOAD,
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
    # The ticked shot-type boxes. OMITTED is not the same as EMPTY: absent
    # means "this client does not know about shot types" and gets the
    # defaults, [] means the editor deliberately ticked nothing and gets an
    # unbiased search. A client that predates the checkboxes therefore keeps
    # the behaviour it has always had.
    shot_types: list[str] | None = None
    # The candidate ceiling, one of config.CANDIDATE_CAPS. OMITTED (an old
    # client, or a caller with no opinion) is the DEFAULT and never "no limit":
    # no limit is what reached 336 candidates and got the NAS's IP bot-checked
    # partway through the metadata pass (2026-08-11).
    max_candidates: int | None = None


# A topic, not a document. The cap is a fleet-availability guard as much as a
# UI one (YTDL-7, 2026-08-11): the term is one argv element of the `claude -p`
# call, Linux caps a single argument at 128 KiB, and the resulting OSError was
# classified as "the claude CLI is not installed" -- pinning that false banner
# on every editor's page until the container restarted.
MAX_TERM_CHARS = 400

# There are nine boxes, so anything longer is repeats or junk. Capped BEFORE
# the keys are looked at, for the same reason MAX_TERM_CHARS is: a request body
# is not a place to do unbounded work, and the 400 that names the cap is more
# use than a 400 listing four thousand unknown keys (YTDL-7's shape).
MAX_SHOT_TYPES = len(claude_cli.SHOT_TYPES)


def _validated_shot_types(raw):
    """The request's shot types -> what db.create_job wants, or HTTPException.

    None (the field was not sent) passes straight through as None, which is
    "the defaults" everywhere downstream. Unknown keys are REFUSED rather than
    dropped: a typo that silently searched with a different bias would be
    invisible to the editor and unexplainable afterwards.
    """
    if raw is None:
        return None
    if len(raw) > MAX_SHOT_TYPES:
        raise HTTPException(
            400, f'that is {len(raw)} shot types; there are only '
                 f'{MAX_SHOT_TYPES}')
    unknown = [k for k in raw if str(k) not in claude_cli.SHOT_TYPES]
    if unknown:
        raise HTTPException(
            400, f'unknown shot type(s): {", ".join(str(k) for k in unknown[:5])}. '
                 f'Known: {", ".join(claude_cli.SHOT_TYPES)}')
    # Order and duplicates are the client's problem to have; normalise_shot_types
    # settles both, so two clients ticking the same boxes store the same row.
    return list(claude_cli.normalise_shot_types(raw))


def _validated_max_candidates(raw):
    """The request's candidate ceiling -> what db.create_job wants, or a 400.

    None (the field was not sent) passes through as None, which is the default
    everywhere downstream -- an old client gets the safe number rather than the
    unbounded search it used to get.

    An unlisted number is REFUSED rather than clamped. The set is a menu the
    SPA renders, not a range: silently turning 5000 into 400 would tell an
    editor their thin-topic search covered everything it could when it did not,
    and silently turning 3 into 50 would spend forty metadata calls nobody
    asked for.
    """
    if raw is None:
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = None
    if n not in config.CANDIDATE_CAPS:
        raise HTTPException(
            400, f'{raw!r} is not one of the candidate limits: '
                 f'{", ".join(str(x) for x in config.CANDIDATE_CAPS)}')
    return n


@router.post('/api/jobs')
def create_job(req: NewJob, request: Request):
    user = current_user(request)
    _require_attestation(con(), user)
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
    shot_types = _validated_shot_types(req.shot_types)
    max_candidates = _validated_max_candidates(req.max_candidates)

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
            max_per_term=max(1, min(50, int(req.max_per_term))),
            shot_types=shot_types, max_candidates=max_candidates)
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


# --------------------------------------------------------- pasted-link jobs
# "Download exactly these": no topic, no Claude, no review grid. Everything
# downstream of the job row is shared with a search job on purpose -- same
# outtmpl, same edit-ready conversion, same ledger, same folder layout -- so
# the only new logic is turning a paste into video ids.

# The 11-char YouTube id. It is the key EVERYTHING here turns on: the ledger is
# keyed on it, yt-dlp writes it into every filename as `[id]`, and both halves
# of the dedupe read it back out. So a link is accepted only if an id can be
# read out of it WITHOUT asking the network -- a handler that resolved URLs
# would block the dashboard's single uvicorn worker for as long as YouTube felt
# like taking.
_VIDEO_ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')

# Matched after 'www.'/'m.' are stripped, and by EQUALITY: `youtube.com.evil.net`
# and `notyoutube.com` both have to fail, which a substring test does not do.
_YT_HOSTS = frozenset({'youtube.com', 'music.youtube.com',
                       'youtube-nocookie.com', 'youtu.be'})

# The path shapes that carry the id in the next segment. /watch?v= is handled
# separately because its id is in the query string.
_ID_PATHS = ('shorts', 'embed', 'live', 'v')


def video_id_of(text):
    """The video id in one pasted entry, or None. Pure; never touches the net.

    Accepts what editors actually paste: a watch URL with any amount of
    tracking on it (`&t=`, `?si=`, `&list=`), a youtu.be short link, a
    /shorts//live//embed//v/ link, a scheme-less `youtu.be/...`, and a bare
    11-char id (which is what the ledger, the filenames and the dedupe all
    speak, and what an editor copies out of an ALREADY IN badge).
    """
    s = str(text or '').strip().strip('<>')
    if not s:
        return None
    if _VIDEO_ID_RE.match(s):
        return s
    if '//' not in s:
        # 'youtu.be/xxxx' pasted out of a chat window has no scheme, and
        # urlparse would read the whole thing as a path with no host at all.
        s = 'https://' + s
    try:
        u = urlparse(s)
    except ValueError:
        return None
    if u.scheme not in ('http', 'https'):
        return None
    host = (u.hostname or '').lower()
    for prefix in ('www.', 'm.'):
        if host.startswith(prefix):
            host = host[len(prefix):]
    if host not in _YT_HOSTS:
        return None

    segs = [p for p in u.path.split('/') if p]
    if host == 'youtu.be':
        candidate = segs[0] if segs else ''
    elif len(segs) == 1 and segs[0] == 'watch':
        candidate = (parse_qs(u.query).get('v') or [''])[0]
    elif len(segs) >= 2 and segs[0] in _ID_PATHS:
        candidate = segs[1]
    else:
        # /playlist, /@channel, /results, /feed/... -- a YouTube URL that names
        # no single video. Refused loudly rather than guessed at: a playlist
        # link silently downloading one video would be worse than a 400.
        candidate = ''
    return candidate if _VIDEO_ID_RE.match(candidate) else None


def watch_url(video_id):
    """The canonical form every row stores. One shape in the database means the
    ledger, the manifest and the retry path cannot disagree about a video."""
    return f'https://www.youtube.com/watch?v={video_id}'


def parse_url_list(raw):
    """-> ([{'video_id','url'}, ...], [rejected entry, ...]), in paste order.

    Split on whitespace AND commas, because a paste is as likely to be one
    comma-separated line as it is a column. Duplicates inside one paste collapse
    to their first occurrence: two rows for one video would double the
    counters and race each other into the same file.
    """
    videos, rejects, seen = [], [], set()
    for chunk in re.split(r'[\s,]+', str(raw or '')):
        if not chunk:
            continue
        vid = video_id_of(chunk)
        if vid is None:
            rejects.append(chunk)
            continue
        if vid in seen:
            continue
        seen.add(vid)
        videos.append({'video_id': vid, 'url': watch_url(vid)})
    return videos, rejects


class NewUrlJob(BaseModel):
    urls: str | list[str] = ''
    project_slug: str
    quality: str = '1080p'
    # ACCEPTED AND IGNORED, like shot_types and max_candidates below. The box it
    # came from is gone and so is the destination it named (owner, 2026-08-11:
    # "the direct download link does not need a separate folder, it just uses
    # the same folder as the search" -> "individual downloads should just go
    # into the /youtube root for the project folder actually, I realised the
    # problem with there being no term to sort the clips into subfolders").
    # Kept in the model rather than dropped so a browser holding the previous
    # app.js in cache -- or an admin's curl -- does not get a 400 for a field
    # that no longer changes anything; pydantic would drop it silently anyway,
    # and this is the note saying that is deliberate.
    folder: str = ''
    # Deliberately NO shot_types and NO max_candidates: a url job does no
    # searching at all, so there is nothing for a bias to bias and nothing to
    # accumulate a ceiling against -- its videos are exactly the links pasted,
    # already capped by MAX_URLS. The SPA posts the same form for both boxes,
    # so one arriving here is ignored (pydantic drops unknown fields) rather
    # than refused -- a 400 over a field that changes nothing would be a paste
    # that mysteriously fails while the search beside it works.


# A batch of links, not a bulk importer. The character cap is the same kind of
# guard as MAX_TERM_CHARS (YTDL-7) one layer under the dashboard's 4 MB body cap
# (DASH-3): this handler splits and regexes the whole string on the request
# thread, and the worker downloads the result one video at a time, three
# seconds apart, from one bot-checkable NAS IP.
MAX_URL_CHARS = 4000
MAX_URLS = 50

# Where pasted links land: <project>/Youtube/ ITSELF, with no subfolder at all
# (owner, 2026-08-11 -- "individual downloads should just go into the /youtube
# root for the project folder actually, I realised the problem with there being
# no term to sort the clips into subfolders"). A search has a topic to name a
# folder after; a paste has nothing but the links, so a folder invented for it
# was a bin in Resolve with no meaning and a level of clicking for the editor.
#
# Both columns are EMPTY, and both deliberately: `term` because nothing was
# searched for, `term_dir` because there is no subfolder. Everything downstream
# reads an empty term_dir as "the Youtube root" -- the download phase's
# safe_join, the rel_path it writes, db.ledger_where's badge and the history
# panel's destination line. Loose clips in that root reach Resolve from
# companion 0.7.1, which collects them alongside the one level of term folders
# its youtube_import watcher already walks.
URL_JOB_TERM = ''
URL_JOB_TERM_DIR = ''


@router.post('/api/jobs/urls')
def create_url_job(req: NewUrlJob, request: Request):
    """Download exactly these videos into <project>/Youtube/.

    The same pipeline as a search job's download phase, entered directly: the
    rows this writes are the rows the review grid would have written, so the
    worker, the ledger, the dedupe, the chmod contract and the companion's
    youtube_import watcher all see something they already understand.
    """
    user = current_user(request)
    _require_attestation(con(), user)
    raw = '\n'.join(req.urls) if isinstance(req.urls, list) else (req.urls or '')
    if len(raw) > MAX_URL_CHARS:
        raise HTTPException(
            400, f'that is {len(raw)} characters of links; paste at most '
                 f'{MAX_URL_CHARS}')

    videos, rejects = parse_url_list(raw)
    if rejects:
        shown = ', '.join(rejects[:3]) + ('...' if len(rejects) > 3 else '')
        raise HTTPException(
            400, f'{len(rejects)} of those are not YouTube video links: {shown}. '
                 'Paste watch/youtu.be/shorts links (or bare 11-character video '
                 'ids), one per line.')
    if not videos:
        raise HTTPException(400, 'paste at least one YouTube link')
    if len(videos) > MAX_URLS:
        raise HTTPException(
            400, f'that is {len(videos)} links; {MAX_URLS} is the most one job '
                 'may take. Split them into two.')

    project = projects.resolve_project(user, req.project_slug)
    if project is None:
        raise HTTPException(
            400, 'that project is not one you are syncing. Tick it on the '
                 'dashboard first -- downloads go into the projects you sync.')
    if req.quality not in ('best', '2160p', '1440p', '1080p', '720p', '480p'):
        raise HTTPException(400, f'unknown quality {req.quality!r}')

    # No folder is read, validated or invented: `req.folder` is accepted and
    # ignored (see NewUrlJob). There is therefore nothing here for
    # safe_term_dirname to make SMB-safe either -- the only directory this job
    # can create is `Youtube`, which already exists in every project the
    # downloader has ever written to.
    c = con()
    running = db.active_job(c, user)
    if running is not None:
        raise _one_job_409(running)

    # The ledger half of the dedupe, before any bandwidth is planned. The DISK
    # half stays where it is (the worker's pre-download re-check): scanning a
    # project's whole Youtube tree is an rglob over the NAS, and this handler
    # runs on the dashboard's single uvicorn worker.
    for v in videos:
        held = db.ledger_get(c, v['video_id'])
        if held is not None:
            # db.ledger_where, never a second copy of the format string: the
            # badge, the worker's re-check and this must not disagree about
            # where a clip is (YTDL-31), least of all now that a folder name
            # can be empty.
            v['duplicate_of'] = db.ledger_where(held)
    skipped = [{'video_id': v['video_id'], 'duplicate_of': v['duplicate_of']}
               for v in videos if v.get('duplicate_of')]
    if len(skipped) == len(videos):
        # Creating the job anyway would burn the editor's one active job on
        # something that downloads nothing (REQ 6: never re-downloaded).
        raise HTTPException(409, {
            'detail': 'the fleet already has ' + ('that video' if len(videos) == 1
                                                  else 'all of those videos'),
            'duplicates': skipped})

    try:
        job_id = db.create_url_job(
            c, user, URL_JOB_TERM, URL_JOB_TERM_DIR, project['slug'],
            project['label'], videos, quality=req.quality)
    except sqlite3.IntegrityError:
        # The partial unique index on jobs(created_by) (YTDL-25). Same window
        # as create_job's, same answer: one editor, one job.
        running = db.active_job(c, user)
        if running is None:
            raise
        raise _one_job_409(running) from None
    worker.nudge()
    # `folder` is the DESTINATION as a human reads it, not a directory name --
    # 'Youtube' for a paste, and the only thing in this response that says where
    # the clips are going. `term_dir` stays for anything that already reads it,
    # empty because that is what the row holds.
    return {'job_id': job_id, 'phase': 'queued',
            'term_dir': URL_JOB_TERM_DIR, 'folder': db.YOUTUBE_DIR,
            'queued': len(videos) - len(skipped), 'skipped': skipped}


@router.get('/api/jobs')
def list_jobs(request: Request, limit: int = 20):
    user = current_user(request)
    return {'jobs': [db.job_dict(r) for r in
                     db.recent_jobs(con(), user, max(1, min(100, limit)))]}


@router.get('/api/jobs/active')
def active_job(request: Request):
    """The caller's one non-terminal job, or None. **Declared before
    /api/jobs/{job_id}** -- that route takes an int, so 'active' reaching it
    first would be a 422 rather than a fall-through.

    It exists because the SPA cannot infer this from the recent list: a job at
    `ready_for_review` is deliberately ACTIVE (db.active_job), it is the one
    that blocks every new search with a 409 (YTDL-25), and a page attached to a
    stale `#job=` hash shows the editor something else entirely while that
    happens. One row, one query, the same one the 409 path already reads.
    """
    user = current_user(request)
    row = db.active_job(con(), user)
    return {'job': db.job_dict(row) if row is not None else None}


# --------------------------------------------------------- download history
# The permanent ledger, read back as history. FLEET-WIDE and not per-editor, on
# purpose (owner's request, 2026-08-11):
#   - the ledger IS the cross-project dedupe record. Every editor already sees
#     everyone else's rows through the ALREADY IN badge, naming the project and
#     folder a clip landed in -- a history that hid them would contradict a
#     badge on the same page;
#   - rows are UPSERTED on video_id, so a re-download by another editor moves
#     the row and rewrites downloaded_by. A per-caller filter would silently
#     lose clips out of an editor's own history when someone else fetched them
#     again, which is a history that cannot be trusted;
#   - "who already has this and where" is the question this table is for, and
#     an editor whose colleague downloaded the clip is exactly who needs it.
# `downloaded_by` rides along on every row, so the panel can still say whose it
# was. What it is NOT is public: current_user() gates it like every other route.

@router.get('/api/downloads')
def list_downloads(request: Request, limit: int = db.HISTORY_PAGE,
                   offset: int = 0):
    """One page of the ledger, newest first. Never the whole thing.

    offset/limit rather than a since-cursor because the ordering key
    (downloaded_at, one-second resolution) is not unique -- a cursor on it
    would either skip or repeat rows inside a batch that landed in the same
    second, and forty clips of one job routinely do.
    """
    current_user(request)
    c = con()
    limit = max(1, min(db.MAX_HISTORY_LIMIT, int(limit)))
    offset = max(0, int(offset))
    rows = db.recent_downloads(c, limit, offset)
    total = db.count_downloads(c)
    return {'downloads': [db.download_dict(r) for r in rows],
            'total': total, 'limit': limit, 'offset': offset,
            'has_more': offset + len(rows) < total}


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
    # Re-checked HERE and not only at create: a manifest can sit at review for
    # a week (see below), which is long enough for the wording to have been
    # re-versioned since the search was submitted.
    _require_attestation(c, user)
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
    # ...nor may the last run's executor pin (YTDL-WEB-7, 2026-08-14). end_lease
    # sets mode_lock='server' on the ORDINARY close-out as well as on a reclaim,
    # and nothing cleared it -- so this retry, the one YTDL-16 exists for and
    # the one the plan's second-chance sweep expects to be used for clips that
    # failed on an editor's IP, was permanently refused to that editor's machine
    # and ran from the NAS's IP instead. This is a fresh human request; the pin
    # belonged to the run that ended.
    db.clear_mode_lock(c, job_id)
    db.set_job(c, job_id, dl_total=n, dl_done=0, dl_failed=0)
    db.set_phase(c, job_id, 'downloading')
    worker.nudge()
    return {'ok': True, 'queued': n}


class ModeLock(BaseModel):
    mode: str = 'server'


@router.post('/api/jobs/{job_id}/mode-lock')
def mode_lock(job_id: int, req: ModeLock, request: Request):
    """"Download on the server instead" -- the per-job escape hatch (plan §9).

    A BROWSER route, session-authed like every other route in this file and
    deliberately NOT token-authed: this is a human decision about their own job
    (they are tethered, on hotel wifi, or about to close the laptop), and the
    fleet token belongs to machines. It is per-job and not a global toggle
    because per-job is enough and self-documenting.

    A lease that is already running ENDS (db.lock_mode, YTDL-WEB-2,
    2026-08-14): it is expired on the spot, the companion's next call answers
    410 and it stops, and the worker's ordinary reclaim credits what landed and
    fetches the rest -- which is exactly what the SPA's toast has always
    promised. The previous version pinned the column and left the lease alone,
    which meant the click did nothing in the only state the SPA offers it in.

    Only 'server' is accepted. There is no lock TO local: the local executor is
    an offer the requester's machine makes, not something the server can compel.
    """
    user = current_user(request)
    c = con()
    job = _job_or_404(c, job_id, user)
    if req.mode != db.MODE_SERVER:
        raise HTTPException(400, f'unknown mode {req.mode!r}: only '
                                 f'{db.MODE_SERVER!r} can be locked')
    db.lock_mode(c, job_id, db.MODE_SERVER)
    # The reclaim itself is the worker's, not this thread's: it re-queues rows
    # and rglobs the term folder, and this handler shares its process with the
    # fleet status page. Nudged rather than waited for -- the SPA finds out from
    # the next poll, exactly as it finds out about a reclaim it did not ask for.
    worker.nudge()
    fresh = db.get_job(c, job_id)
    return {'ok': True, 'mode_lock': db.MODE_SERVER,
            # What the badge should say NOW. It still comes off the row rather
            # than being asserted here: the worker has not run yet, so this is
            # 'local' with a dead lease until it does.
            'download_mode': fresh['download_mode'],
            'lease_active': db.lease_active(fresh),
            'phase': job['phase']}


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

    A LOCAL download is the third door onto the same room (YTDL-WEB-1,
    2026-08-14) and it was open for the whole of a 41-clip job: the flag is read
    inside run_job, and claim_next_job deliberately hides a leased job from the
    worker, so with a companion heartbeating every 30 s the worker never saw the
    request until the editor's machine had downloaded, and lane A had uploaded,
    every byte they cancelled. Ending the lease is what closes it -- the
    companion is told 410 at its next call and stops, and the worker has the job
    back on this nudge rather than three minutes later.
    """
    user = current_user(request)
    c = con()
    job = _job_or_404(c, job_id, user)
    if job['phase'] in db.TERMINAL:
        return {'ok': True, 'phase': job['phase'], 'note': 'already finished'}
    if db.cancel_now(c, job_id):
        return {'ok': True, 'phase': 'cancelled'}
    db.request_cancel(c, job_id)
    stopped = db.expire_lease(c, job_id)
    worker.nudge()
    return {'ok': True, 'phase': job['phase'], 'stopped_local_download': stopped}
