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
import os
import re
import shutil
import threading
import time
import urllib.request
from datetime import date
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ytdlweb import (attestation, claude_cli, config, db, projects, worker,
                     ytdl_canary, ytdl_evidence)
from ytdlweb.db import con
from ytdlweb.session import current_user
from ytdlweb.vendor import downloader, ytsearch

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

    2026-08-26 (plan WP5): the keys below `local_download` are EVIDENCE, not
    configuration. `cookies: bool(COOKIES_FILE)` stayed true right through
    CR-80 while every single download failed, because a path being set says
    nothing about whether the session behind it still works. Every old key is
    kept regardless of that -- an editor's cached SPA bundle reads them, and a
    health pip going blank is a worse failure than a stale one.

    Still cheap: no subprocess, no database, and the only network call is the
    PO-token probe, which is cached for a minute.
    """
    current_user(request)
    cached = claude_cli.health()
    paths = ytdl_evidence.snapshot()
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

        # ------------------------------------------------ evidence (WP5)
        # WHICH yt-dlp this container is on. Answering that during CR-80 took
        # a `docker exec`, and it was half the diagnosis: 2026.07.04 had no
        # working anonymous client left.
        'yt_dlp_version': _yt_dlp_version(),
        # HOW OLD that yt-dlp is, in days, and whether that is past the shelf
        # life (YT-1, 2026-08-28). yt-dlp's versions are release dates, so this
        # costs nothing, and it is the one signal that would have shown CR-80
        # and CR-83 coming: in both, a weeks-old yt-dlp was reported by an
        # editor who could not download, never by this page. None means the
        # version string could not be ranked as a date, which is NOT the same
        # as fresh -- `yt_dlp_stale` stays false and the detail line says so.
        'yt_dlp_age_days': _yt_dlp_age_days(),
        'yt_dlp_stale': _yt_dlp_is_stale(),
        'yt_dlp_age_detail': _yt_dlp_age_detail(),
        # 'none' | 'empty' | 'present' -- what the jar HOLDS, next to the old
        # boolean that only says a path is configured. CR-80's fix parked the
        # flagged jar as its two header lines with the path still set.
        'cookies_state': ytdl_evidence.cookie_jar_state(config.COOKIES_FILE),
        # 'unconfigured' | 'ok' | 'unreachable'. CR-73 sat undetected for days
        # behind a sidecar that was configured and not answering.
        'pot_provider': _pot_provider_state(),
        # {'anonymous'|'cookies': {ok, error, at, video_id, source}}. A key is
        # present only once that path has actually been tried.
        'paths': paths,
        'last_download': _last_download(paths),
        'canary': {'enabled': ytdl_canary.enabled(),
                   'last': _last_canary(paths)},
    }


def _yt_dlp_version():
    """The running yt-dlp's version string, or '' when it is not installed."""
    try:
        import yt_dlp.version

        return str(yt_dlp.version.__version__ or '')
    except Exception:  # noqa: BLE001
        return ''


def _yt_dlp_age_days():
    """Days since the running yt-dlp's release, or None.

    Its version IS the release date (YYYY.MM.DD, occasionally with a same-day
    `.1`), so no network call and no GitHub API are involved. None for a
    version that cannot be read or ranked, and for one dated in the FUTURE: a
    container with a wrong clock must not be told its yt-dlp is old, because
    "we cannot tell" and "it is stale" are different answers.
    """
    parts = str(_yt_dlp_version() or '').strip().split('.')
    if len(parts) < 3:
        return None
    try:
        released = date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None
    age = (date.today() - released).days
    return age if age >= 0 else None


def _yt_dlp_is_stale():
    """Is the running yt-dlp past config.YTDLP_MAX_AGE_DAYS?

    False when the age is unknown or the rule is switched off (a limit of 0 or
    less). The unknown case is carried by `yt_dlp_age_detail` instead: a flag
    that goes true on "could not tell" would be an amber pip nobody can clear.
    """
    limit = config.YTDLP_MAX_AGE_DAYS
    if limit <= 0:
        return False
    age = _yt_dlp_age_days()
    return age is not None and age > limit


def _yt_dlp_age_detail():
    """One line for the health strip's tooltip. No em dashes (house rule)."""
    version = str(_yt_dlp_version() or '').strip()
    if not version:
        return 'no yt-dlp is installed on this server'
    age = _yt_dlp_age_days()
    if age is None:
        return (f'the running yt-dlp is {version}, whose version is not a date '
                f'this can age, so nothing here can tell you whether it is stale')
    limit = config.YTDLP_MAX_AGE_DAYS
    line = f'the running yt-dlp is {age} days old ({version})'
    if limit > 0 and age > limit:
        return (line + f', past the {limit} day limit. YouTube breaks yt-dlp '
                'deliberately, so update the copy on this server before '
                'downloads start failing.')
    return line


def _newest(paths, source):
    """The most recent evidence entry from `source`, with its `path` key.

    The SPA shows one line ("last download: anonymous, ok, 3 minutes ago"), so
    the path has to travel WITH the entry -- health's `paths` map is keyed by
    it, and a caller that had to hold both would drift.
    """
    best = None
    for name, entry in (paths or {}).items():
        if not isinstance(entry, dict) or entry.get('source') != source:
            continue
        if best is None or (entry.get('at') or 0) > (best.get('at') or 0):
            best = dict(entry, path=name)
    return best


def _last_download(paths):
    """The last REAL download attempt, either path, or None."""
    return _newest(paths, 'download')


def _last_canary(paths):
    """The last canary extraction, either path, or None."""
    return _newest(paths, ytdl_canary.SOURCE)


# How long a PO-token verdict is reused. A minute is the same window the bgutil
# provider plugin itself caches server availability for (its
# _check_server_availability), so health cannot be more pessimistic about the
# sidecar than yt-dlp is; and it bounds an open dashboard tab polling health to
# one probe a minute per worker rather than one per page load.
_POT_TTL = 60.0
_pot_lock = threading.Lock()
_pot_cache = {'at': 0.0, 'state': ''}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects. House rule (docs/GOTCHAS.md 12): no dashboard call
    follows one, and a sidecar that answers 302 is not a healthy sidecar."""

    def redirect_request(self, *args, **kwargs):
        return None


_pot_opener = urllib.request.build_opener(_NoRedirect)


def _probe_pot(base_url):
    """GET <base_url>/ping -> 'ok' | 'unreachable'. Never raises.

    `/ping` is the bgutil HTTP server's own health route: the provider plugin
    (yt_dlp_plugins/extractor/getpot_bgutil_http.py, bgutil-ytdlp-pot-provider
    1.3.1) calls exactly this before every token request and refuses the
    request when it does not answer with JSON.

    Deliberately does NOT parse the body or compare versions. The question this
    key answers is CR-73's -- is there anything listening at the address we
    configured -- and a stricter probe would be one more thing that can report
    red while downloads work fine. One second, because this runs on a request
    the browser is waiting on and uvicorn here is workers=1.
    """
    url = base_url.rstrip('/') + '/ping'
    try:
        with _pot_opener.open(url, timeout=1) as resp:
            resp.read(4096)
            return 'ok' if 200 <= int(getattr(resp, 'status', 0) or 0) < 300 else 'unreachable'
    except Exception as exc:  # noqa: BLE001 - health must never 500
        log.debug('pot provider probe failed for %s (%s: %s)', url,
                  type(exc).__name__, exc)
        return 'unreachable'


def _pot_provider_state():
    """'unconfigured' | 'ok' | 'unreachable', from a cached probe.

    Refreshed LAZILY on the request path, never on a timer: a dashboard nobody
    is looking at should not be probing anything, and the first page load after
    the cache goes stale pays one second at worst.
    """
    base_url = (os.environ.get(downloader.POT_BASE_URL_ENV) or '').strip()
    if not base_url:
        # Not an error: a deployment with an unblocked IP needs no provider at
        # all (downloader.pot_opts says the same).
        return 'unconfigured'
    now = time.monotonic()
    with _pot_lock:
        if _pot_cache['state'] and (now - _pot_cache['at']) < _POT_TTL:
            return _pot_cache['state']
    state = _probe_pot(base_url)
    with _pot_lock:
        _pot_cache['state'] = state
        _pot_cache['at'] = time.monotonic()
    return state


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
def list_projects(request: Request, machine: str | None = None, local: bool = True):
    """The caller's ticked projects, straight from the dashboard database.

    `machine` (a hostname) and `local` are the CR-72 follow-up (2026-08-30):
    the SPA's own signals for WHICH computer is asking and WHERE the download
    will run, so a wired machine or a server-side download sees every active
    project instead of just what this account has ticked. Both default to the
    pre-follow-up shape (no machine known, `local` true) for a client that
    predates them -- see projects.ticked_projects.
    """
    user = current_user(request)
    result = projects.ticked_projects(user, machine=machine, local=local)
    return {'projects': result['projects'],
            'projects_available': result['available'],
            'error': result['error']}


class NewJob(BaseModel):
    term: str
    project_slug: str
    quality: str = '1080p'
    period: str | None = None
    max_per_term: int = 15
    # WHAT THIS SEARCH IS FOR: 'visuals' or 'news' (claude_cli.MODES,
    # 2026-08-18). OMITTED is 'visuals' -- the only search this app ran before
    # the modes existed -- so a client that predates the toggle keeps exactly
    # the behaviour it has always had.
    mode: str | None = None
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
    # WHICH LANGUAGES the search runs in: 'both' | 'en' | 'zh' | 'exact'
    # (claude_cli.TERM_SCOPES, 2026-08-25). OMITTED is 'both', the only search
    # this app ran before the scopes existed, so an old client keeps it.
    term_scope: str | None = None
    # An upload-date range, ISO 'YYYY-MM-DD' (what <input type=date> emits) or
    # bare 'YYYYMMDD'. Either side may be omitted or ''. Enforced on the
    # metadata in the filter phase; see migrations/011.
    date_from: str | None = None
    date_to: str | None = None
    # SKIP THE TERM REVIEW (2026-08-30). The SPA never sends it: an editor who
    # asked for a search is exactly who should see the queries it is about to
    # run. It is here for the headless caller -- a script that posts a topic
    # and comes back for the manifest -- because a job parked at `terms_review`
    # waits for a person forever, and a script is not one. OMITTED is False,
    # so nothing that already calls this API is changed by it.
    auto_terms: bool = False
    # CR-72 follow-up (2026-08-30): the SAME two signals GET /api/projects
    # widens on, carried on the job so `projects.resolve_project` never
    # disagrees with what the picker that filled `project_slug` was shown.
    # OMITTED machine + local=True (the defaults) is the pre-follow-up shape.
    machine: str | None = None
    local: bool = True


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


def _validated_mode(raw):
    """The request's search mode -> what db.create_job wants, or a 400.

    None (the field was not sent) passes through as None, which is the default
    everywhere downstream. An unrecognised value is REFUSED rather than quietly
    read as the default: the mode decides which rubric both AI calls run under,
    and a typo that silently searched for the other thing would be invisible to
    the editor and unexplainable afterwards -- the same reason an unknown shot
    type is a 400.
    """
    if raw is None:
        return None
    if str(raw) not in claude_cli.MODES:
        raise HTTPException(
            400, f'unknown search mode {raw!r}. Known: '
                 f'{", ".join(claude_cli.MODES)}')
    return str(raw)


def _validated_term_scope(raw):
    """The request's language scope -> what db.create_job wants, or a 400.

    Same rule as the mode: None passes through as the default, an unknown value
    is REFUSED rather than read as 'both' -- an editor who asked for Chinese
    only and silently got both would not be able to tell from the manifest why.
    """
    if raw is None:
        return None
    if str(raw) not in claude_cli.TERM_SCOPES:
        raise HTTPException(
            400, f'unknown search scope {raw!r}. Known: '
                 f'{", ".join(claude_cli.TERM_SCOPES)}')
    return str(raw)


_DATE_RE = re.compile(r'^(\d{4})-?(\d{2})-?(\d{2})$')


def _validated_date(raw, which):
    """'YYYY-MM-DD' or 'YYYYMMDD' -> 'YYYYMMDD', '' / None -> None, else 400.

    A real calendar date, not just eight digits: 2026-02-30 stored as a bound
    would silently drop or keep every candidate around it.
    """
    s = str(raw or '').strip()
    if not s:
        return None
    m = _DATE_RE.match(s)
    if m:
        try:
            date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return ''.join(m.groups())
        except ValueError:
            pass
    raise HTTPException(
        400, f'{which} must be a date like 2026-01-31 (that was {s!r})')


def _validated_date_range(req):
    """-> (date_from, date_to) as YYYYMMDD or None, refusing a reversed pair:
    a range that can match nothing is a mistake, not a search."""
    lo = _validated_date(req.date_from, 'date_from')
    hi = _validated_date(req.date_to, 'date_to')
    if lo and hi and lo > hi:
        raise HTTPException(
            400, 'the date range is reversed: "from" is after "to"')
    return lo, hi


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

    project = projects.resolve_project(user, req.project_slug,
                                       machine=req.machine, local=req.local)
    if project is None:
        raise HTTPException(
            400, 'that project is not one you are syncing. Tick it on the '
                 'dashboard first -- downloads go into the projects you sync.')
    if req.period and req.period not in ytsearch.PERIOD_SP:
        raise HTTPException(400, f'unknown period {req.period!r}')
    if req.quality not in ('best', '2160p', '1440p', '1080p', '720p', '480p'):
        raise HTTPException(400, f'unknown quality {req.quality!r}')
    mode = _validated_mode(req.mode)
    shot_types = _validated_shot_types(req.shot_types)
    max_candidates = _validated_max_candidates(req.max_candidates)
    term_scope = _validated_term_scope(req.term_scope)
    date_from, date_to = _validated_date_range(req)

    c = con()
    # THE QUEUE (2026-08-30, the owner: "there should also be a queue so you
    # can queue up multiple searches"). This used to be a 409 -- one job per
    # editor, and every later search refused until the first was reviewed or
    # cancelled (YTDL-25). It is now a position in a list: the job is created
    # `queued` like every other job, and db.claim_next_job starts it when this
    # editor has nothing busy. Nothing here starts anything; a handler that
    # did would be a second scheduler racing the worker.
    job_id = db.create_job(
        c, user, term, config.safe_term_dirname(term), project['slug'],
        project['label'], quality=req.quality, period=req.period or None,
        max_per_term=max(1, min(50, int(req.max_per_term))),
        shot_types=shot_types, max_candidates=max_candidates,
        mode=mode, term_scope=term_scope, date_from=date_from,
        date_to=date_to, auto_terms=bool(req.auto_terms))
    worker.nudge()
    return _queued_answer(c, user, job_id)


def _queued_answer(c, user, job_id):
    """What a create returns now that a create can queue.

    `queued_behind` is what the search box prints, and it is counted rather
    than stored: the jobs ahead of this one are its editor's busy job (at most
    one) plus every queued job in front of it. 0 means it starts on the
    worker's next tick, which is the answer for the first search of the day and
    the one nothing needs to say anything about.
    """
    fresh = db.get_job(c, job_id)
    ahead = [j['id'] for j in db.queued_jobs(c, user)]
    behind = ahead.index(job_id) if job_id in ahead else 0
    if db.busy_job(c, user) is not None:
        behind += 1
    return {'job_id': job_id, 'phase': fresh['phase'],
            'queue_position': fresh['queue_position'],
            'queued_behind': behind}


def _one_job_409(running):
    """"you already have a job in progress" -- what is left of the one-job rule.

    NOT the create path any more: a second search queues (see create_job). What
    still raises this is reviving a FINISHED job while a busy one is running --
    pressing RETRY on last week's failures while today's search is downloading
    -- because that job goes straight to `downloading` with no queue entry to
    wait in, and two download phases for one editor is the one thing the queue
    is not.
    """
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
    # A manual folder/bin name for pasted links (2026-08-30, the owner: "there
    # should be a way to manually input the name of the folder/bin you want
    # links you are downloading to go into").
    #
    # Was ACCEPTED AND IGNORED from 2026-08-11 to 2026-08-30: the owner had
    # reversed himself twice in one conversation that day ("the direct
    # download link does not need a separate folder, it just uses the same
    # folder as the search" -> "individual downloads should just go into the
    # /youtube root for the project folder actually, I realised the problem
    # with there being no term to sort the clips into subfolders") and this
    # field was kept in the model, doing nothing, so a browser holding that
    # app.js in cache -- or an admin's curl -- would not get a 400 for a field
    # that changed nothing. He asked for it back on 2026-08-30: blank still
    # means today's behaviour (loose in <project>/Youtube), and a name given
    # becomes the job's term_dir through the SAME safe_term_dirname a search
    # job's folder goes through -- see create_url_job.
    folder: str = ''
    # Deliberately NO mode, NO shot_types and NO max_candidates: a url job
    # does no searching at all, so there is nothing to frame, nothing for a
    # bias to bias and nothing to accumulate a ceiling against -- its videos
    # are exactly the links pasted,
    # already capped by MAX_URLS. The SPA posts the same form for both boxes,
    # so one arriving here is ignored (pydantic drops unknown fields) rather
    # than refused -- a 400 over a field that changes nothing would be a paste
    # that mysteriously fails while the search beside it works.
    # machine/local: same CR-72 follow-up as NewJob, see there.
    machine: str | None = None
    local: bool = True


# A batch of links, not a bulk importer. The character cap is the same kind of
# guard as MAX_TERM_CHARS (YTDL-7) one layer under the dashboard's 4 MB body cap
# (DASH-3): this handler splits and regexes the whole string on the request
# thread, and the worker downloads the result one video at a time, three
# seconds apart, from one bot-checkable NAS IP.
MAX_URL_CHARS = 4000
MAX_URLS = 50

# Where pasted links land with no folder given: <project>/Youtube/ ITSELF, no
# subfolder at all (owner, 2026-08-11 -- "individual downloads should just go
# into the /youtube root for the project folder actually, I realised the
# problem with there being no term to sort the clips into subfolders"). That
# default still holds: `term` stays EMPTY for a url job, always -- a paste has
# no topic, whatever folder it lands in -- and `URL_JOB_TERM_DIR` is what an
# omitted or blank folder box resolves to.
#
# `req.folder`, when given, is reduced through the SAME safe_term_dirname a
# search job's topic goes through and becomes the job's term_dir instead
# (2026-08-30, the owner: "there should be a way to manually input the name of
# the folder/bin you want links you are downloading to go into" -- reversing
# the 2026-08-11 call above). Everything downstream already reads term_dir
# generically for EITHER kind of job -- the download phase's safe_join, the
# rel_path it writes, db.ledger_where's badge and the history panel's
# destination line all keyed off the column, never off `kind` -- so nothing
# else here changes. Clips in a folder reach Resolve from companion 0.7.1,
# which collects them alongside the one level of term folders its
# youtube_import watcher already walks (and the loose Youtube/ root the same
# way, unchanged).
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

    project = projects.resolve_project(user, req.project_slug,
                                       machine=req.machine, local=req.local)
    if project is None:
        raise HTTPException(
            400, 'that project is not one you are syncing. Tick it on the '
                 'dashboard first -- downloads go into the projects you sync.')
    if req.quality not in ('best', '2160p', '1440p', '1080p', '720p', '480p'):
        raise HTTPException(400, f'unknown quality {req.quality!r}')

    # Blank (the default) is URL_JOB_TERM_DIR, the Youtube root, exactly as
    # before 2026-08-30; a name given is made SMB-safe the same way a search's
    # topic is (config.safe_term_dirname, YTDL-28's traversal/Windows/length
    # rules) and becomes this job's folder under Youtube/.
    folder = (req.folder or '').strip()
    term_dir = config.safe_term_dirname(folder) if folder else URL_JOB_TERM_DIR
    c = con()
    # No one-job refusal here either (2026-08-30): a paste queues behind
    # whatever this editor has running, exactly as a search does.

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

    job_id = db.create_url_job(
        c, user, URL_JOB_TERM, term_dir, project['slug'],
        project['label'], videos, quality=req.quality)
    worker.nudge()
    # `folder` is the DESTINATION as a human reads it, not a directory name --
    # db.folder_label so it agrees with the badge and the history panel byte
    # for byte, 'Youtube' for a job with no folder and 'Youtube/<name>' for
    # one with it.
    #
    # `queued` here is the CLIP count and has nothing to do with the job queue;
    # it predates it by three weeks and the SPA prints it as "N links queued".
    # The queue's own two numbers ride alongside it (_queued_answer).
    return {**_queued_answer(c, user, job_id),
            'term_dir': term_dir,
            'folder': f'{db.YOUTUBE_DIR}/{term_dir}' if term_dir else db.YOUTUBE_DIR,
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
    `ready_for_review` is deliberately ACTIVE (db.active_job) and a page
    attached to a stale `#job=` hash shows the editor something else entirely
    while it sits there unlooked-at.

    ...AND THE QUEUE behind it (2026-08-30). One round trip, because the two
    are one question: "what is this editor's downloader doing". The queue is
    every job of theirs at `queued`, in the order it will run, numbered by that
    order rather than by the stored positions -- a queue with a cancellation in
    the middle of it must read 1, 2, 3 to the person looking at it.
    """
    user = current_user(request)
    c = con()
    row = db.active_job(c, user)
    queue = [db.queue_dict(j, i) for i, j in
             enumerate(db.queued_jobs(c, user), start=1)]
    # The running job is not also a queue entry. It only can be in the second
    # between "created" and "claimed", when active_job falls back to the head
    # of the queue -- and a page that showed the same job twice would offer
    # [ UP ] on the thing that is already running.
    if row is not None:
        queue = [q for q in queue if q['id'] != row['id']]
    return {'job': db.job_dict(row) if row is not None else None,
            'queue': queue}


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
        # Every term, ticked or not, with its bracketed translation: this is
        # what the term review renders, and it is the same list the ticker's
        # "N terms (x en / y zh)" has always been built from (db.term_dict).
        'terms': [db.term_dict(t, hits.get(t['id'], 0))
                  for t in db.terms(c, job_id)],
        'job': db.job_dict(job),
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
        'terms': [db.term_dict(t, hits.get(t['id'], 0))
                  for t in db.terms(c, job_id)],
        'counts': db.counts(c, job_id),
    }


# ------------------------------------------------------------ the term review
# The owner, 2026-08-30: "youtube downloader should show a list of the search
# terms it is going to use (for chinese ones, it should show a translation in
# brackets). They begin all ticked and then you can untick individual ones or
# untick all, or tick all."
#
# TWO routes and not one, deliberately. Ticking is a decision about the job;
# continuing is a decision to spend twenty minutes of YouTube requests. Folding
# them together would mean either a page that posts every tick (a round trip
# per checkbox, on a handler that shares its process with the fleet status
# page) or a single call whose failure leaves nobody able to say whether the
# ticks landed. The SPA ticks in the browser, posts the set ONCE, and only then
# asks for the search.

class TermSelection(BaseModel):
    # Term ids, or the query text itself. Both, because both are things a
    # caller genuinely has: the SPA holds the ids its last poll gave it, and a
    # script driving this by hand has the strings it just read.
    enabled: list[str | int] = []


def _reviewing_or_409(c, job_id, user):
    """The job, if it is parked at the term review. Else 409.

    The phase is the permission: before it the terms do not exist yet, and
    after it the search has already run on them, so a tick arriving late would
    describe a job that is not the one that ran.
    """
    job = _job_or_404(c, job_id, user)
    if job['phase'] != 'terms_review':
        raise HTTPException(409, {
            'detail': f'this job is {job["phase"]}, not waiting for you to '
                      f'pick its search terms',
            'phase': job['phase']})
    return job


@router.post('/api/jobs/{job_id}/terms')
def set_terms(job_id: int, req: TermSelection, request: Request):
    """Tick exactly these terms and untick the rest.

    The WHOLE set every time, never a delta: the page knows what it is showing
    and one post that says so cannot half-apply. UNTICK ALL is the empty list,
    which is accepted here (it is a legal thing to be looking at) and refused by
    the continue below, where it would mean a search of nothing.
    """
    user = current_user(request)
    c = con()
    _reviewing_or_409(c, job_id, user)
    n = db.set_terms_enabled(c, job_id, req.enabled)
    return {'ok': True, 'enabled': n,
            'total': len(db.terms(c, job_id))}


@router.post('/api/jobs/{job_id}/terms/continue')
def continue_terms(job_id: int, request: Request):
    """SEARCH WITH THESE: leave the review and start searching.

    terms_total is rewritten here as well as in the search phase, so the
    progress bar is right on the very first poll after the button rather than
    counting up to a total that includes terms nobody is going to search.
    """
    user = current_user(request)
    c = con()
    _reviewing_or_409(c, job_id, user)
    enabled = db.enabled_terms(c, job_id)
    if not enabled:
        raise HTTPException(400, 'tick at least one search term: a search with '
                                 'none of them would find nothing')
    db.set_job(c, job_id, terms_total=len(enabled))
    db.set_phase(c, job_id, 'searching')
    worker.nudge()
    return {'ok': True, 'phase': 'searching', 'terms': len(enabled)}


# ------------------------------------------------------------------ the queue

class QueueMove(BaseModel):
    position: int = 1


@router.post('/api/jobs/{job_id}/queue/move')
def move_queued_job(job_id: int, req: QueueMove, request: Request):
    """[ UP ] / [ DOWN ] on the QUEUE list: put this job at `position`.

    1-based, clamped rather than validated -- [ UP ] on the first row is a
    no-op an editor will press, not an error worth a toast. A job that is not
    in the queue any more (the worker started it while the page was deciding)
    is a 409 with its phase in it, so the SPA can re-render instead of guessing.

    Cancelling a queued job is not here: POST /api/jobs/{id}/cancel already
    does it, and `queued` is one of db.IDLE, so it ends outright.
    """
    user = current_user(request)
    c = con()
    job = _job_or_404(c, job_id, user)
    order = db.move_in_queue(c, user, job_id, req.position)
    if order is None:
        raise HTTPException(409, {
            'detail': f'this job is {job["phase"]}, not waiting in the queue',
            'phase': job['phase']})
    return {'ok': True, 'queue': [db.queue_dict(j, i) for i, j in
                                  enumerate(db.queued_jobs(c, user), start=1)]}


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

    `failed` joins them 2026-08-26 (docs/YTDL_RESILIENCE_PLAN.md WP6), but only
    for a job that failed IN or AFTER the download phase: that is what the
    circuit breaker now parks a job as, and the CR-80 recovery was exactly this
    call. A job that died in search or enrich has no download rows and nothing
    to re-queue, so it keeps its 409 - the fix there is a new search, not a
    button that would walk it back through a phase it never left.
    """
    user = current_user(request)
    c = con()
    # Re-checked HERE and not only at create: a manifest can sit at review for
    # a week (see below), which is long enough for the wording to have been
    # re-versioned since the search was submitted.
    _require_attestation(c, user)
    job = _job_or_404(c, job_id, user)
    if job['phase'] not in ('ready_for_review', 'done', 'failed'):
        raise HTTPException(409, {
            'detail': f'this job is {job["phase"]}, not ready for review',
            'phase': job['phase']})
    # "It failed in or after the download phase" spelled as "it has download
    # rows", out of the two helpers that already exist rather than a third
    # query: failed_videos is the rows the run killed, unfinished_downloads is
    # the ones it never reached (the breaker leaves them `pending`).
    if job['phase'] == 'failed' and not (db.failed_videos(c, job_id)
                                         or db.unfinished_downloads(c, job_id)):
        raise HTTPException(409, {
            'detail': 'this job failed before any clips were queued, so there '
                      'is nothing to retry. Start a new search.',
            'phase': job['phase']})
    if job['phase'] in ('done', 'failed'):
        # Reviving a finished job puts it straight into `downloading` with no
        # queue entry to wait in, so it is the one path where the old one-job
        # rule still has to hold -- but against a BUSY job only (2026-08-30). A
        # search of this editor's parked at terms_review or ready_for_review is
        # waiting for them, not running, and refusing a retry because of it
        # would be the YTDL-25 block back again in the one place it was never
        # about.
        running = db.busy_job(c, user)
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
    # belonged to the run that ended -- and since CR-37 (2026-08-19) so does the
    # rest of that run's executor state, because clearing the pin alone was
    # undone by the reclaim this function's own nudge triggers, two
    # milliseconds later, for a run that ended half an hour ago.
    db.clear_mode_lock(c, job_id)
    # ...and neither may the note the failure left on the job row (WP6,
    # 2026-08-26). db.set_phase only ever WRITES `error`, so a job parked by
    # the circuit breaker would carry "3 clips in a row failed the same way"
    # into the run being started right now, where the SPA paints it as a banner
    # over a download that is going fine. NULL is what the banner reads as
    # nothing (app.js: `job.error ? hintFor(job.error) : null`).
    db.set_job(c, job_id, dl_total=n, dl_done=0, dl_failed=0, error=None)
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
