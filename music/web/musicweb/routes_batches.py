"""The music ingest panel's own API: what the BROWSER may do to a batch.

docs/MUSIC_INGEST_PLAN.md step 2, 2026-08-18, and the same six routes b-roll's
`routes_batches.py` has: pre-check a drop, create a batch, list, read, cancel,
pause uploads. The work itself is dispatched over the loopback to the editor's
companion and executed against the FLEET routes next door
(`routes_fleet.py`) -- nothing here does anything slow, because the dashboard
runs uvicorn with workers=1 and a handler that blocks blocks the fleet status
page.

**IDENTITY COMES FROM A HEADER THIS APP DOES NOT MINT.** `X-CCSync-User` (and
`X-CCSync-Admin`) are stamped by `ccsync_dashboard.music.MusicGate` from the
session cookie, which it decodes with the dashboard's own secret; the gate
STRIPS any inbound copy first. That is the contract /broll and /ytdl already
run on, and it exists because this app has no session code and must not grow
any: a second implementation of "who is logged in" is a second thing to get
wrong. A request that arrives with no header is answered 401 here -- if
login_gate somehow let it through, the sub-app still refuses.

`scope=all` additionally needs `X-CCSync-Admin: 1`. An editor may see and stop
their own batches; seeing which machine every other editor is sitting at, and
stopping their work, is an admin's business.
"""
import logging

from fastapi import APIRouter, Header, HTTPException, Query

from musicweb import config, ingest_batches
from musicweb.db import con
from musicweb.schemas import (IngestBatchCreateIn, IngestPrecheckIn,
                              UploadPausedIn)

log = logging.getLogger(__name__)

router = APIRouter(prefix='/api/ingest-batches')


def require_user(x_ccsync_user):
    """The signed-in editor, per the gate's stamp. 401 with no stamp.

    Fails closed on an EMPTY header too: the gate withholds it entirely for a
    name it cannot carry through a latin-1 header round trip (a CJK username --
    YTDL-29's lesson), and "" must not become an editor whose batches everyone
    with an unusable name shares.
    """
    user = (x_ccsync_user or '').strip()
    if not user:
        raise HTTPException(401, 'not signed in')
    return user


def is_admin(x_ccsync_admin):
    """Stamped alongside the identity, and stripped inbound the same way."""
    return (x_ccsync_admin or '').strip() == '1'


def _visible_or_404(conn, uid, user, admin):
    """404, not 403, for another editor's batch.

    Telling a caller "that exists but is not yours" is telling them a uid they
    were not given, and uids are the only thing standing between an editor and
    another editor's batch on the loopback.
    """
    batch = ingest_batches.get_batch(conn, uid)
    if batch is None or (not admin and batch['editor'] != user):
        raise HTTPException(404, 'no such batch')
    return batch


# Every handler below is a plain `def`, not `async def`, and that is
# load-bearing here for MUSIC-2's reason: Starlette runs an `async def` ON THE
# EVENT LOOP, and these touch SQLite. A plain def is dispatched to the
# threadpool, where blocking is what the threads are for.

@router.post('/precheck')
def precheck(body: IngestPrecheckIn, x_ccsync_user: str = Header(default=None)):
    """Per track: already in the library? and what will it be called?

    Runs while the editor is still ticking boxes, so it reserves NOTHING -- the
    names come back as a preview and the real allocation happens at `result`.
    A name reserved here would be a name leaked by every abandoned drop.
    """
    require_user(x_ccsync_user)
    return {'items': ingest_batches.precheck(con(), body.items)}


@router.post('')
@router.post('/')
def create(body: IngestBatchCreateIn, x_ccsync_user: str = Header(default=None)):
    """Queue a batch. The SPA then hands the uid to the local companion.

    Returns only the uid: everything else the companion needs comes from the
    claim, under the fleet token, because the browser must never be the source
    of a work order (the /music/send principle extended).
    """
    user = require_user(x_ccsync_user)
    settings = ingest_batches.validate_settings(body.settings)
    uid = ingest_batches.create_batch(con(), editor=user, settings=settings,
                                      items=body.items)
    return {'uid': uid, 'state': 'queued', 'n_items': len(body.items)}


@router.get('')
@router.get('/')
def list_batches(scope: str = Query(default='mine'),
                 x_ccsync_user: str = Header(default=None),
                 x_ccsync_admin: str = Header(default=None)):
    """This editor's batches, or the whole fleet's for an admin.

    Expires stale leases on the way past. There is no timer in this app (see
    expire_stale_leases), and the list is the one call that happens whenever
    anybody is looking -- so a batch whose machine was switched off is back in
    `queued` by the time the page renders it.
    """
    user = require_user(x_ccsync_user)
    admin = is_admin(x_ccsync_admin)
    if scope not in ('mine', 'all'):
        raise HTTPException(422, "scope must be 'mine' or 'all'")
    if scope == 'all' and not admin:
        raise HTTPException(403, {'detail': 'only an admin can see every '
                                            "machine's batches",
                                  'reason': 'admin_only'})
    conn = con()
    ingest_batches.expire_stale_leases(conn)
    return {'scope': scope, 'admin': admin,
            'batches': ingest_batches.list_batches(
                conn, editor=None if scope == 'all' else user)}


@router.get('/limits')
def limits(x_ccsync_user: str = Header(default=None)):
    """What the SPA must not exceed, said by the server that enforces it.

    The panel needs the extension list and the per-batch cap to refuse a drop
    before it streams a gigabyte to the companion, and hardcoding them in
    app.js is how the two drift.

    Declared BEFORE `/{uid}`: FastAPI matches routes in declaration order, so a
    literal path that lives under a path-parameter route is a path the
    parameter swallows.
    """
    require_user(x_ccsync_user)
    return {'max_items': config.MAX_BATCH_ITEMS,
            'audio_exts': sorted(ingest_batches.AUDIO_EXTS),
            'transcode_exts': sorted(ingest_batches.TRANSCODE_EXTS),
            'run_modes': list(ingest_batches.RUN_MODES)}


@router.get('/{uid}')
def get_one(uid: str, x_ccsync_user: str = Header(default=None),
            x_ccsync_admin: str = Header(default=None)):
    """One batch with its items -- the view the SPA falls back to when the
    loopback is unreachable or the page was reopened on another machine. The
    server's view is the truth after a reload; the companion's progress poll is
    only ever the faster one."""
    user = require_user(x_ccsync_user)
    admin = is_admin(x_ccsync_admin)
    conn = con()
    ingest_batches.expire_stale_leases(conn)
    batch = _visible_or_404(conn, uid, user, admin)
    return {'batch': ingest_batches.batch_public(batch),
            'items': [ingest_batches.item_public(i)
                      for i in ingest_batches.list_items(conn, uid)]}


@router.post('/{uid}/cancel')
def cancel(uid: str, x_ccsync_user: str = Header(default=None),
           x_ccsync_admin: str = Header(default=None)):
    """Ask the machine to stop. Owner or admin.

    Not a kill: this sets the flag and expires the lease, and the companion
    learns about it on its next heartbeat (410) or from the report reply.
    Tracks already `live` stay -- their audio is in the library and somebody
    may already have cut with it.
    """
    user = require_user(x_ccsync_user)
    admin = is_admin(x_ccsync_admin)
    conn = con()
    batch = _visible_or_404(conn, uid, user, admin)
    if batch['state'] in ingest_batches.BATCH_TERMINAL:
        # Idempotent, not an error: two clicks, or a click on a batch that
        # finished while the page was stale, must not raise at an editor.
        return {'ok': True, 'state': batch['state'], 'already_finished': True}
    ingest_batches.cancel(conn, uid, user)
    return {'ok': True, 'state': batch['state'], 'cancel_requested': True}


@router.post('/{uid}/upload-paused')
def upload_paused(uid: str, body: UploadPausedIn,
                  x_ccsync_user: str = Header(default=None),
                  x_ccsync_admin: str = Header(default=None)):
    """Hold the uploads while the embedding continues.

    Separate from cancel because they are separate problems: an editor on a
    metered connection wants the indexing to go on and the bytes to wait.
    """
    user = require_user(x_ccsync_user)
    admin = is_admin(x_ccsync_admin)
    conn = con()
    batch = _visible_or_404(conn, uid, user, admin)
    ingest_batches.set_upload_paused(conn, uid, body.paused)
    return {'ok': True, 'uid': batch['uid'], 'upload_paused': body.paused}
