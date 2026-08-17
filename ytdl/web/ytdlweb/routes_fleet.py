"""The companion's half of requester-first downloads: claim, lease, manifest,
per-clip status. Machine-to-machine, token-authed, never a browser.

docs/YTDL_LOCAL_DOWNLOAD.md is the design. The short version, from the
2026-08-13/14 incident: bulk anonymous downloads out of one datacentre IP is
exactly YouTube's bot-check profile (five clips failed outright on 2026-08-13,
and the fleet had already been cut off at 112 metadata calls on 2026-08-11),
while an editor fetching their own reviewed selections from a residential IP is
not. So from companion 0.8.0 the requester's own machine may execute the
download, and the NAS worker becomes the fallback executor.

Three rules govern this file and none is negotiable:

  - **THE FLEET TOKEN, NOT THE SESSION.** These calls happen when no browser is
    open (the SPA hands the companion a job id and walks away, plan §2). They
    authenticate with `X-CCSync-Token`, the shared secret every companion
    already holds -- and they FAIL CLOSED: a deployment with no
    DASH_REPORT_TOKEN answers 403 to every one of them rather than running open,
    which is the b-roll ingest gate's precedent.
  - **AND THE TOKEN IS NOT AN IDENTITY** (H5, COMMERCIAL_READINESS.md item 7,
    2026-08-17). Every companion in the fleet holds the same one, so it proves
    "a fleet machine" and nothing about WHICH. The editor's name therefore
    arrives as the dashboard's signed identity token in `X-CCSync-Identity`,
    verified here (identity.py) before it is believed. It used to be a bare
    self-asserted string, which meant any machine with the shared token could
    claim a job as somebody else and then complete it, fail its clips, or take
    it off the editor who was downloading it. Missing or unverifiable is 403,
    for the same fail-closed reason as the token.
  - **THE BROWSER CONTRIBUTES A JOB ID AND NOTHING ELSE.** Paths, URLs,
    quality, the naming template -- all of it comes from the server under the
    token (plan §8). This is /music/send's principle ("never trust the page
    with paths") extended to never trusting it with the work order either.

Like routes_api, every handler here is sync, SQLite-only and finishes in
milliseconds: the dashboard runs uvicorn with workers=1, so a handler that
blocks blocks the fleet status page. The one thing that would not be
millisecond work -- finishing a job off -- is deliberately handed back to the
worker rather than done here (see _hand_back_to_the_server).
"""
import hmac
import logging
import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from ytdlweb import attestation, config, db, identity, worker, ytdl_common
from ytdlweb.db import con
from ytdlweb.vendor import ytsearch

log = logging.getLogger(__name__)
router = APIRouter()

def token_ok(configured, presented):
    """Constant-time shared-secret comparison. Empty configured = never ok.

    Copied from ccsync_dashboard.api.token_ok rather than imported (this app
    must run with no dashboard package in reach), including the two lessons in
    it: `==` on a secret leaks its length and matching prefix through timing,
    and hmac.compare_digest raises TypeError on a str with any character above
    U+007F -- so a junk header with one non-ASCII byte turned a 401 into a 500
    and a traceback on the dashboard (DASH-5, 2026-08-11).
    """
    if not configured or not presented:
        return False
    try:
        return hmac.compare_digest(str(configured).encode('utf-8', 'surrogateescape'),
                                   str(presented).encode('utf-8', 'surrogateescape'))
    except (TypeError, ValueError, UnicodeError):
        return False


def require_fleet_token(x_ccsync_token: str | None = Header(default=None)) -> None:
    """FAIL CLOSED. An unconfigured token means 403, never "open in dev".

    The b-roll ingest gate allows an unset token as a dev mode; this one must
    not, and the difference is what the endpoints do: b-roll's ingest writes
    rows into an index, these hand a machine somewhere on the internet a list of
    URLs to fetch and a folder in the canonical project tree to write them to.
    A deployment that lost its DASH_REPORT_TOKEN should lose local downloads --
    which costs nothing, because the server worker downloads everything anyway.
    """
    if not token_ok(config.REPORT_TOKEN, x_ccsync_token or ''):
        raise HTTPException(403, 'missing or invalid X-CCSync-Token')


def _job_or_404(c, job_id):
    """The job row. Deliberately NOT db.get_job_for: there is no session here,
    and the companion acting for an editor is authorised by the token plus the
    lease, not by ownership of a row it cannot see."""
    job = db.get_job(c, job_id)
    if job is None:
        raise HTTPException(404, 'no such job')
    return job


def _leaseholder_or_410(c, job_id, editor):
    """The job, if the VERIFIED `editor` still holds its lease.

    410 GONE and not 403: "your claim is over" is the answer to every way this
    can fail -- the lease expired and the server reclaimed the job (§3, one-way,
    no ping-pong), the job finished, another editor holds it -- and the
    companion's response to all of them is the same one: stop, quietly. A 403
    would read as "fix your credentials".

    A pending CANCEL is one of those ways (YTDL-WEB-1, 2026-08-14). The route
    that sets it also expires the lease, so this rarely decides anything on its
    own -- but the two are separate commits, and a status post landing between
    them must not be the one write that records a clip the editor cancelled.
    """
    job = _job_or_404(c, job_id)
    if job['cancel_requested'] and job['phase'] not in db.TERMINAL:
        raise HTTPException(410, {
            'detail': 'this job has been cancelled', 'job_id': job_id,
            'download_mode': job['download_mode'], 'phase': job['phase'],
            'reason': 'cancelled'})
    if not db.is_leaseholder(job, editor):
        raise HTTPException(410, {
            'detail': 'this job is no longer yours to download',
            'job_id': job_id, 'download_mode': job['download_mode'],
            'claimed_by': job['claimed_by'], 'phase': job['phase']})
    return job


def require_identity(x_ccsync_identity):
    """The VERIFIED editor behind `X-CCSync-Identity`. 403 if there isn't one.

    H5 (2026-08-17). This header used to be self-asserted -- documented here as
    a "mistake-preventer, not an authorisation boundary" -- and that was the
    hole: the shared fleet token is held by every companion, so a name nobody
    checked was the only thing deciding whose job a caller could claim,
    complete or poison. It now carries the dashboard's signed identity token
    (the one reporter.py already sends on every status report) and is verified
    against DASH_SESSION_SECRET before the name is used for anything.

    The BODY's `editor` field is no longer consulted for identity at all. It is
    still accepted on the wire so an older companion's request parses, but the
    only name that decides anything is the one the signature vouches for --
    two sources for one fact is how the wrong one ends up winning.

    Fails closed on an unconfigured secret, exactly as require_fleet_token
    does on an unconfigured token: local downloads stop and the NAS worker
    downloads everything, which is the designed fallback.
    """
    if not config.SESSION_SECRET:
        log.warning('a fleet download call arrived but DASH_SESSION_SECRET is '
                    'not set, so no identity can be verified -- refusing. The '
                    'server worker downloads these jobs instead.')
        raise HTTPException(403, {
            'detail': 'this dashboard cannot verify companion identities',
            'reason': 'identity_unconfigured'})
    editor = identity.read_identity_token(config.SESSION_SECRET, x_ccsync_identity)
    if not editor:
        raise HTTPException(403, {
            'detail': (f'a valid {identity.HEADER} is required: sign in again '
                       'from the companion tray'),
            'reason': 'identity'})
    return editor


# --------------------------------------------------------------- the client
# Unauthenticated on purpose: nothing here is secret, and it is what lets the
# fleet be forced onto a newer yt-dlp the day YouTube breaks the old one (plan
# §4). A companion reads it BEFORE it has anything to claim.

@router.get('/api/config/ytdl-client')
def client_config():
    return {
        'min_ytdlp_version': config.MIN_YTDLP_VERSION,
        # Residential pacing can be gentler than the NAS's, so the number the
        # local executor sleeps between clips is server-provided rather than a
        # companion constant (plan §7). Today they are the same value.
        'download_pause_seconds': config.DOWNLOAD_PAUSE,
        'template_version': ytdl_common.TEMPLATE_VERSION,
        'sidecar_version': ytdl_common.SIDECAR_VERSION,
        'lease_seconds': config.LEASE_SECONDS,
        'heartbeat_seconds': config.HEARTBEAT_SECONDS,
    }


# ------------------------------------------------------------- claim + lease

class ClaimIn(BaseModel):
    # IGNORED SINCE H5 (2026-08-17): the lease holder is the name the verified
    # X-CCSync-Identity token carries, never this. Kept on the model so an
    # older companion's body still parses -- dropping the field would turn a
    # security fix into a 422 for every machine that has not upgraded.
    editor: str = ''
    # yt-dlp's own YYYY.MM.DD, straight out of `yt-dlp --version`. Compared as
    # a string (config.MIN_YTDLP_VERSION says why that is exact).
    ytdlp_version: str = ''
    # The vendored ytdl_common's TEMPLATE_VERSION. Absent (0) is a companion
    # that predates the contract, which is a skew like any other.
    template_version: int = 0
    # ...and its SIDECAR_VERSION. The two are separate numbers because they
    # fail differently -- a template skew puts two spellings of one clip in the
    # tree, a sidecar skew puts two shapes of one credits file beside them --
    # and the server advertised this one (in the manifest and in the client
    # config) while comparing it nowhere until COMP-BROLL-6/2026-08-14 made the
    # companion send it. Absent (0) is DECLARED-ONLY on purpose, unlike
    # template_version: every companion that predates the handshake is already
    # refused by the template branch, so the only body that can reach the
    # sidecar check without the field is a build that speaks one half of a
    # contract it half-vendors -- and refusing on a number nobody sent would
    # refuse today's fleet for a skew it does not have.
    sidecar_version: int = 0
    # The quality rungs THIS executor will actually run (the companion's
    # SCOPE_QUALITIES). Declared at claim time so an out-of-scope job is
    # refused here instead of leased, downloaded by nobody, and reclaimed a
    # lease later -- three minutes of a 2160p job sitting still, per job, for
    # nothing (COMP-BROLL-10). Empty = a companion that does not declare, which
    # is answered exactly as it was before this field existed.
    scope_qualities: list[str] = []
    # Recorded and logged, not enforced: the free-space decision belongs to the
    # machine that knows what a clip costs and what else is on that disk, and
    # the companion declines its own claim (plan §7, the 0.7.x free-space
    # lesson). Here it is evidence for "why did that editor stop claiming".
    free_bytes: int | None = None


def _version_at_least(reported, minimum):
    """Is `reported` at least `minimum`, on yt-dlp's YYYY.MM.DD scheme?

    NUMERIC RANKING, not the string comparison this shipped with (COMP-BROLL-9,
    2026-08-14). Lexicographic order is release order for yt-dlp's own
    zero-padded output and for nothing else -- and the other operand is
    `YTDL_MIN_YTDLP_VERSION`, free text an operator types. A single unpadded
    floor ('2026.8.5') sorted above every real release, so every claim in the
    fleet 403'd while every companion, ranking numerically, saw nothing to
    update. config.version_rank is the same rule the companion's
    upgrade.parse_version uses, so the two ends now agree by construction.

    An unrankable REPORTED version is STALE: a companion that cannot say what
    it is running does not get to download for the fleet. An unrankable MINIMUM
    cannot refuse anybody -- config._validated_floor has already replaced it
    with the shipped default and said so at ERROR, so this branch is reachable
    only by a direct caller, and "let the claim through" is the safe half of a
    rule nobody can evaluate.
    """
    theirs = config.version_rank(reported)
    if theirs is None:
        return False
    floor = config.version_rank(minimum)
    return floor is None or theirs >= floor


@router.post('/api/jobs/{job_id}/claim')
def claim(job_id: int, body: ClaimIn,
          x_ccsync_token: str | None = Header(default=None),
          x_ccsync_identity: str | None = Header(default=None)):
    """Take the lease on a job's downloads. The compare-and-set of plan §3.

    200 = it is yours, start downloading. Everything else is "do not", and the
    SPA never hears about it as an error: a declined claim means the server
    worker downloads exactly as it does today, which is the whole rollback
    story (§10).

      403  the caller's yt-dlp is older than the fleet minimum. The body
           carries the number so the companion can self-update and be right
           next time (§6).
      409  somebody else holds a live lease -- two tabs, two editors, or one
           editor on two machines.
      410  not claimable: the job is not in the download phase, the editor
           cancelled it, the editor (or a previous reclaim) pinned it to the
           server, the vendored naming/sidecar contract does not match this
           server's, or the job's quality is not one the caller runs. Version
           skew degrades to server-side execution, NEVER to divergent files
           (§5).
    """
    require_fleet_token(x_ccsync_token)
    # THE VERIFIED name, not body.editor (H5, 2026-08-17). The body field is
    # still accepted so an older companion's request parses; it decides
    # nothing, because a lease holder that a signature does not vouch for is
    # the hole this route had.
    editor = require_identity(x_ccsync_identity)

    c = con()
    job = _job_or_404(c, job_id)

    # The rights/ToS attestation, checked on the MACHINE path too and not only
    # in the browser (attestation.py, COMMERCIAL_READINESS.md item 2). A
    # companion is driven by a job id the SPA handed it, and the SPA is gated
    # -- but "the other client checks it" is not a check, and this is the
    # route that decides whose IP fetches the video.
    if db.attestation_of(c, editor, attestation.TEXT_VERSION) is None:
        raise HTTPException(403, {
            'detail': attestation.REFUSAL,
            'reason': 'attestation',
            'version': attestation.TEXT_VERSION})

    # Order matters only in what the caller is told first, and this order tells
    # it the most actionable thing: "there is nothing here to download" before
    # "and your yt-dlp is old".
    if job['phase'] != 'downloading':
        raise HTTPException(410, {
            'detail': f'this job is {job["phase"]}, not downloading',
            'phase': job['phase'], 'reason': 'phase'})
    if job['cancel_requested']:
        # The editor pressed CANCEL while the SPA was still probing their
        # loopback -- a second of overlap that would otherwise have started a
        # download nobody wants (YTDL-WEB-1, 2026-08-14). db.claim_download
        # refuses it too; this is here for the reason, which the companion logs.
        raise HTTPException(410, {
            'detail': 'this job has been cancelled',
            'phase': job['phase'], 'reason': 'cancelled'})
    if job['mode_lock'] == db.MODE_SERVER:
        # Either the editor asked for it (plan §9) or the server already
        # reclaimed this job once. Reclaim is one-way (§3): no ping-pong.
        raise HTTPException(410, {
            'detail': 'this job is pinned to the server',
            'phase': job['phase'], 'reason': 'mode_lock'})
    if body.template_version != ytdl_common.TEMPLATE_VERSION:
        raise HTTPException(410, {
            'detail': ('this companion builds filenames to template version '
                       f'{body.template_version}; this server is on '
                       f'{ytdl_common.TEMPLATE_VERSION}. Downloading here would '
                       'put two spellings of the same clip in the tree.'),
            'reason': 'template_version',
            'template_version': ytdl_common.TEMPLATE_VERSION,
            'sidecar_version': ytdl_common.SIDECAR_VERSION})
    if body.sidecar_version and body.sidecar_version != ytdl_common.SIDECAR_VERSION:
        raise HTTPException(410, {
            'detail': ('this companion writes credits sidecars to version '
                       f'{body.sidecar_version}; this server is on '
                       f'{ytdl_common.SIDECAR_VERSION}. The clips would land '
                       'with a different sidecar from every other machine\'s.'),
            'reason': 'sidecar_version',
            'template_version': ytdl_common.TEMPLATE_VERSION,
            'sidecar_version': ytdl_common.SIDECAR_VERSION})
    if body.scope_qualities and job['quality'] not in [
            str(q or '').strip() for q in body.scope_qualities]:
        # Answered BEFORE the lease, not by letting one expire: the executor
        # would have taken the job, read the quality out of the manifest, found
        # it out of scope and stopped -- and the job would then sit still for
        # the whole lease before the worker could have it (COMP-BROLL-10).
        raise HTTPException(410, {
            'detail': (f'this job is {job["quality"]}, which that machine does '
                       'not run'),
            'reason': 'out_of_scope', 'quality': job['quality']})
    if not _version_at_least(body.ytdlp_version, config.MIN_YTDLP_VERSION):
        raise HTTPException(403, {
            'detail': (f'yt-dlp {body.ytdlp_version or "(unknown)"} is older '
                       f'than the fleet minimum {config.MIN_YTDLP_VERSION}'),
            'reason': 'ytdlp_version',
            'min_ytdlp_version': config.MIN_YTDLP_VERSION})

    if not db.claim_download(c, job_id, editor, config.LEASE_SECONDS):
        # The CAS refused. Re-read rather than guess why: between the checks
        # above and the UPDATE, another companion's claim can land.
        fresh = db.get_job(c, job_id)
        if db.lease_active(fresh) and fresh['claimed_by'] != editor:
            raise HTTPException(409, {
                'detail': f'{fresh["claimed_by"]} is already downloading this job',
                'claimed_by': fresh['claimed_by'],
                'lease_expires_at': fresh['lease_expires_at']})
        raise HTTPException(410, {
            'detail': 'this job is no longer claimable',
            'phase': fresh['phase'] if fresh else None, 'reason': 'race'})

    log.info('job %s: claimed by %s (yt-dlp %s, %s free)', job_id, editor,
             body.ytdlp_version, body.free_bytes)
    return {
        'ok': True,
        'lease_seconds': config.LEASE_SECONDS,
        'heartbeat_seconds': config.HEARTBEAT_SECONDS,
        'download_pause_seconds': config.DOWNLOAD_PAUSE,
    }


class HeartbeatIn(BaseModel):
    editor: str = ''


@router.post('/api/jobs/{job_id}/heartbeat')
def heartbeat(job_id: int, body: HeartbeatIn,
              x_ccsync_token: str | None = Header(default=None),
              x_ccsync_identity: str | None = Header(default=None)):
    """Keep the lease alive. Every YTDL_HEARTBEAT_SECONDS while downloading.

    410 means the lease is gone and the server has (or is about to have) the
    job back -- the companion stops there rather than finishing a download
    nobody will record (§3).
    """
    require_fleet_token(x_ccsync_token)
    editor = require_identity(x_ccsync_identity)
    c = con()
    job = _leaseholder_or_410(c, job_id, editor)
    if not db.heartbeat_download(c, job_id, job['claimed_by'], config.LEASE_SECONDS):
        # Lost between the read and the write -- the expiry landed in that
        # window. Same answer as any other lost lease.
        raise HTTPException(410, {'detail': 'this job is no longer yours to '
                                            'download', 'job_id': job_id})
    fresh = db.get_job(c, job_id)
    return {'ok': True, 'lease_seconds': config.LEASE_SECONDS,
            'lease_expires_at': fresh['lease_expires_at']}


# ---------------------------------------------------------------- the work

@router.get('/api/jobs/{job_id}/download-manifest')
def download_manifest(job_id: int,
                      x_ccsync_token: str | None = Header(default=None),
                      x_ccsync_identity: str | None = Header(default=None)):
    """The work order: what to download, where it goes, under which contract.

    Leaseholder only. Everything the local executor acts on is in here and
    nothing came from the browser (§8): the URLs are the rows the review grid
    selected, and the destination is expressed as a path RELATIVE TO THE
    PROJECTS ROOT -- the same contract db.reveal_path already speaks to the
    companion, because only the companion knows where that root is on the
    machine it is running on (P:\\Projects on an editor, the NAS itself on the
    base rig) and the page must never learn a drive letter.

    The clip list is db.pending_videos PLUS the same pre-download dedupe
    re-check the worker makes -- both halves, ledger and disk (YTDL-WEB-3,
    2026-08-14). The selection query alone was only half of what
    _phase_download does, and the half it left out is the one that matters
    here: a manifest can sit at review for a week (routes_api.start_download
    says so), and in that week another editor's job may have downloaded the
    same video. The worker would have marked it `skipped, duplicate_of=...` and
    spent no bandwidth; the local executor, which has no dedupe of its own,
    fetched it again into a second project and _record_done's ledger UPSERT
    then MOVED the fleet's record of the clip to the new one, orphaning the
    first copy. Same rows from both executors is this endpoint's stated
    contract, so the re-check belongs on both sides of it.

    A GET that writes, therefore -- exactly the rows the worker would have
    written. And one rglob of the term folder, not one per clip: this handler
    shares a process with the fleet status page, and unlike the worker (whose
    clips are 3 s apart anyway) it has the whole list in hand at once.
    """
    require_fleet_token(x_ccsync_token)
    c = con()
    job = _leaseholder_or_410(c, job_id, require_identity(x_ccsync_identity))
    rel_dir = '/'.join(p for p in (job['project_label'], db.YOUTUBE_DIR,
                                   job['term_dir']) if p)
    clips = _still_owed(c, job)
    if not clips and db.unfinished_downloads(c, job_id) == 0:
        # Everything left was already somewhere in the tree. Nothing to hand
        # out, and nothing to wait a lease out for: end it here so the worker
        # closes the job off on this nudge (the same close-out the last clip's
        # status post triggers) instead of the job sitting still for three
        # minutes with no executor. The counter, not `clips`, decides -- an
        # empty list with a row still `downloading` means the SERVER has that
        # row in flight (YTDL-WEB-4's race, from the other side), and it is
        # mid-way through its own close-out.
        _hand_back_to_the_server(c, job)
    return {
        'job_id': job_id,
        # Sent separately as well as inside project_rel_path: the companion
        # validates the label against its OWN selection and declines a project
        # it does not sync, which is what protects an editor's disk from a
        # server bug pointing it somewhere else (plan §7).
        'project_label': job['project_label'],
        'project_rel_path': rel_dir,
        'term_dir': job['term_dir'],
        'quality': job['quality'],
        'template_version': ytdl_common.TEMPLATE_VERSION,
        'sidecar_version': ytdl_common.SIDECAR_VERSION,
        'download_pause_seconds': config.DOWNLOAD_PAUSE,
        'clips': clips,
    }


def _still_owed(c, job):
    """The pending clips this machine should actually fetch. -> the manifest's
    `clips`, with every duplicate marked `skipped` on the way past."""
    job_id = job['id']
    pending = db.pending_videos(c, job_id)
    if not pending:
        return []
    outdir = config.safe_join(config.PROJECTS_ROOT, job['project_label'],
                              db.YOUTUBE_DIR, job['term_dir'])
    on_disk = ytsearch.existing_id_locations(outdir)
    clips = []
    for v in pending:
        where = worker.duplicate_location(c, job, v['video_id'], outdir, on_disk)
        if where:
            log.info('job %s: %s is already in %s -- not sending it to %s',
                     job_id, v['video_id'], where, job['claimed_by'])
            worker.mark_duplicate(c, job_id, v['video_id'], where)
            continue
        clips.append({'video_id': v['video_id'], 'url': v['url'],
                      'title': v['title'], 'thumbnail': v['thumbnail']})
    return clips


class ClipStatusIn(BaseModel):
    state: str = ''                       # downloading | done | failed
    error: str | None = None
    # The quality downgrade, when the clip only landed because the rung below
    # the editor's choice was tried (ytdl_common.TRUNCATED_NOTE). Recorded in
    # dl_error on a DONE row -- see _record_done.
    note: str | None = None
    title: str | None = None
    thumbnail: str | None = None
    # The uploader, for the ledger's history row. Only the downloader ever
    # learns it for a PASTED link -- create_url_job writes video_id/url/title
    # and makes no metadata call -- so without it every locally-executed paste
    # ledgered a NULL channel while the identical paste on the NAS filled it in
    # (YTDL-WEB-8, 2026-08-14). worker.py takes it from yt-dlp's own info dict
    # the same way; this is the other executor's copy of that line.
    channel: str | None = None
    # The clip's NAME, as the shared outtmpl spelled it. A path relative to the
    # term folder is accepted and reduced to its last segment: the server
    # composes the rel_path itself (below), because the ledger's shape is the
    # server's business and a machine-supplied path is not something to store.
    filepath_rel: str | None = None


@router.post('/api/jobs/{job_id}/clips/{video_id}/status')
def clip_status(job_id: int, video_id: str, body: ClipStatusIn,
                x_ccsync_token: str | None = Header(default=None),
                x_ccsync_identity: str | None = Header(default=None)):
    """Mirror one clip's outcome into the job rows.

    THE POINT OF THIS ENDPOINT IS THAT THE SPA CANNOT TELL THE MODES APART
    (plan §2 step 6): it polls the same job row 1500 ms apart either way, so
    every write below is the write worker._phase_download makes for the same
    outcome -- the same states, the same counters, the same ledger row, the
    same downgrade-note-in-dl_error convention -- plus `download_host`, which
    is the one thing that differs and the one thing the history should say.
    """
    require_fleet_token(x_ccsync_token)
    c = con()
    job = _leaseholder_or_410(c, job_id, require_identity(x_ccsync_identity))
    row = db.get_video(c, job_id, video_id)
    if row is None:
        raise HTTPException(404, 'no such video on this job')
    host = job['claimed_by']
    state = str(body.state or '').strip()

    if state == 'downloading':
        db.set_video(c, job_id, video_id, dl_state='downloading', dl_error=None,
                     download_host=host)
        return {'ok': True, 'state': 'downloading'}

    if state == 'done':
        name = os.path.basename(str(body.filepath_rel or '').replace('\\', '/')
                                .rstrip('/'))
        if not name:
            # YTDL-15's rule, applied to the other executor: no file means the
            # download did not land, whatever else the report says. Recording
            # it `done` would write a ledger row with an empty rel_path -- a
            # permanent "the fleet already has this" pointing at nothing, and
            # the ledger never cascades.
            state, body.error = 'failed', ('the downloader reported no output '
                                           'file')
        else:
            _record_done(c, job, row, name, body, host)
            return _after_terminal(c, job, video_id, 'done')

    if state == 'failed':
        db.set_video(c, job_id, video_id, dl_state='failed',
                     dl_error=str(body.error or 'the download failed')[:500],
                     download_host=host)
        db.bump(c, job_id, 'dl_failed')
        return _after_terminal(c, job, video_id, 'failed')

    raise HTTPException(400, f'unknown state {body.state!r}: expected '
                             'downloading, done or failed')


def _record_done(c, job, row, name, body, host):
    """The `done` half of worker._phase_download, written for a clip that
    landed on somebody else's disk.

    `filepath` is the path the file will have ON THE NAS once lane A carries it
    up (on the base rig it is where it already is), composed through safe_join
    from the job's own project label and term dir -- never from anything the
    caller sent. rel_path is joined by dropping the empty part exactly as the
    worker joins it: 'Youtube//x.mp4' would be a path nothing downstream could
    split back into a folder (db._term_dir_of, the badge, the history panel).
    """
    job_id = job['id']
    vid = row['video_id']
    path = config.safe_join(config.PROJECTS_ROOT, job['project_label'],
                            db.YOUTUBE_DIR, job['term_dir'], name)
    rel = '/'.join(p for p in (db.YOUTUBE_DIR, job['term_dir'], name) if p)
    # dl_error on a DONE row is the downgrade note, not a failure: the clip
    # landed, just not at the rung that was asked for, and this row is the only
    # place that would ever say so (SAQBbd1Rxmo, 2026-08-13).
    db.set_video(c, job_id, vid, dl_state='done', filepath=str(path),
                 dl_error=body.note or None,
                 title=body.title or row['title'],
                 thumbnail=body.thumbnail or row['thumbnail'],
                 download_host=host)
    # `body.channel or row['channel']`, mirroring worker.py's
    # `res.get('channel') or v['channel']`: for a pasted-link job the row has no
    # channel and never will (YTDL-WEB-8), and for a search job the row's is the
    # enrich phase's, which is the better answer if the executor sent none.
    db.ledger_add(c, vid, body.title or row['title'],
                  body.channel or row['channel'],
                  job['project_slug'], job['project_label'], job['term'], rel,
                  job_id, job['created_by'])
    db.bump(c, job_id, 'dl_done')


def _after_terminal(c, job, video_id, state):
    """One clip finished. If it was the LAST one, hand the job back."""
    remaining = db.unfinished_downloads(c, job['id'])
    requeued = _hand_back_to_the_server(c, job) if remaining == 0 else 0
    return {'ok': True, 'state': state, 'remaining': remaining,
            'retrying_on_the_server': requeued}


def _hand_back_to_the_server(c, job):
    """The last clip went terminal on the editor's machine. -> clips re-queued.

    THE SECOND-CHANCE SWEEP, and the job's close-out, both by ending the lease
    and letting the worker do what it always does (plan §2 step 7).

    Nothing is finished here on purpose. Writing manifest.json is a filesystem
    write to the NAS mount and a retry is a DOWNLOAD -- neither belongs on a
    request thread in a process that serves the fleet status page with one
    uvicorn worker. So: any clip that failed on the editor's IP goes back to
    `pending`, the lease ends (which is what lets db.claim_next_job see the job
    again), and the worker runs the same _phase_download close-out it runs for
    every server-side job -- retry those clips once, write the manifest, set the
    phase to `done`. One lease ending; no new phase, no second finaliser to keep
    in step with the first.

    The retry is once, not a loop: end_lease pins the job to the server, so the
    companion cannot re-claim it and drive this again.
    """
    n = db.requeue_failed(c, job['id'])
    if n:
        # dl_failed counts clips that are failed RIGHT NOW. These are queued
        # again, and the worker bumps it back for any that fail a second time.
        db.bump(c, job['id'], 'dl_failed', -n)
        log.info('job %s: %d clip(s) failed on %s; the server will retry them '
                 'once', job['id'], n, job['claimed_by'])
    db.end_lease(c, job['id'], job['claimed_by'])
    worker.nudge()
    return n
