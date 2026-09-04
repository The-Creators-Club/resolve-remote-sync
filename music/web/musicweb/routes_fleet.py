"""The companion's half of music ingest: claim, lease, checkpoints, results.

docs/MUSIC_INGEST_PLAN.md step 2, 2026-08-18. Machine-to-machine, token-authed,
never a browser -- these calls happen with no page open, while an editor's
companion embeds a dropped album with the CLAP audio tower.

Three rules, all copied from b-roll's `routes_fleet.py`, which copied them from
ytdl's, because the shape of the problem is identical and one of them was
learned the hard way there:

  - **THE FLEET TOKEN, NOT THE SESSION**, and it FAILS CLOSED (fleet_auth).
  - **THE TOKEN IS NOT AN IDENTITY.** Every companion holds the same one, so
    the editor's name arrives as the dashboard's signed identity token and is
    verified before the batch's `editor` column is compared against it (H5,
    COMMERCIAL_READINESS.md item 7).
  - **THE BROWSER CONTRIBUTES A BATCH UID AND NOTHING ELSE.** The names, the
    settings, where the library lives on the remote -- all of it comes back
    from `claim` under the token. The page never learns a path and never
    dictates one; that is /music/send's own principle applied to a work order.

**`X-CCSync-Machine` on every call after the claim.** The bodies for
heartbeat/status/result/uploaded/release carry no machine name, so it rides a
header instead of being bolted onto five request models: it is what proves the
caller is still THIS editor's leaseholding machine rather than another of their
companions waking up with a stale state file. Absent, that one check is skipped
and the editor/lease/cancel checks still run -- an older companion degrades
rather than being locked out.

410, NOT 403, for every way a claim can end. The lease expired and the server
reclaimed the batch, the editor cancelled it, another of their machines took
it, the batch finished -- the companion's answer to all of them is the same
one, stop quietly, and a 403 would read as "fix your credentials" and be
retried forever. 403 is reserved for the two things that really are credential
problems: an unverifiable identity, and a claim on somebody else's batch.

Every handler is a plain `def`: SQLite-only, milliseconds, and dispatched to
the threadpool rather than run on the event loop (MUSIC-2). The one exception
in cost is `result`, which re-scores the library -- still well under a second
on this library, and it is a threadpool call, not an event-loop one.
"""
import logging

from fastapi import APIRouter, Depends, Header, HTTPException

from musicweb import ingest_batches, rescore
from musicweb.db import con
from musicweb.fleet_auth import require_fleet_token, require_identity
from musicweb.schemas import (ClaimIn, HeartbeatIn, ItemResultIn, ItemStatusIn,
                              ItemUploadedIn, ReleaseIn)

log = logging.getLogger(__name__)

# The path shape the dashboard's login_gate carve-out regex pins
# (app.py `_music_fleet_re`). Changing this prefix, or the 32-hex uid shape,
# means changing that regex in the same commit -- otherwise every one of these
# calls is answered with a 303 to an HTML login page that no companion can
# follow, and music ingest stops fleet-wide with nothing in this app's log.
router = APIRouter(prefix='/api/fleet/ingest')


def _batch_or_404(conn, uid):
    batch = ingest_batches.get_batch(conn, uid)
    if batch is None:
        raise HTTPException(404, 'no such batch')
    return batch


def _leaseholder_or_410(conn, uid, editor, machine=None):
    """The batch, if this VERIFIED editor on THIS machine still holds its lease.

    Four ways to fail and one answer to all of them, for the reason in the
    module docstring. A pending CANCEL is checked FIRST and separately from the
    lease even though the cancel route expires the lease too: they are two
    commits, and a status post landing between them must not be the one write
    that records a track the editor cancelled (YTDL-WEB-1's lesson,
    2026-08-14).
    """
    batch = _batch_or_404(conn, uid)
    if batch['cancel_requested'] and batch['state'] not in ingest_batches.BATCH_TERMINAL:
        raise HTTPException(410, {'detail': 'this batch has been cancelled',
                                  'batch_uid': uid, 'reason': 'cancelled',
                                  'cancel_by': batch['cancel_by']})
    if batch['state'] in ingest_batches.BATCH_TERMINAL:
        raise HTTPException(410, {'detail': f'this batch is {batch["state"]}',
                                  'batch_uid': uid, 'reason': 'finished',
                                  'state': batch['state']})
    if batch['editor'] != editor:
        raise HTTPException(410, {'detail': 'this batch is no longer yours to index',
                                  'batch_uid': uid, 'reason': 'other_editor'})
    if machine and batch['machine'] != machine:
        raise HTTPException(410, {
            'detail': f'{batch["machine"] or "another computer"} holds this batch now',
            'batch_uid': uid, 'reason': 'other_machine', 'machine': batch['machine']})
    if not ingest_batches.lease_live(batch):
        raise HTTPException(410, {'detail': "this batch's lease has expired and the "
                                            'server has taken it back',
                                  'batch_uid': uid, 'reason': 'lease_expired',
                                  'state': batch['state']})
    return batch


def _item_or_404(conn, batch_uid, item_uid):
    item = ingest_batches.get_item(conn, batch_uid, item_uid)
    if item is None:
        raise HTTPException(404, 'no such item in this batch')
    return item


def _refresh_search(conn):
    """Rebuild the in-process search matrices. Best-effort, never fatal.

    `search.Index` is built once and cached (MUSIC-10 rebuilds a whole new one
    and swaps it), so a track written by this route is not findable until
    something refreshes -- exactly what the inline ingest path does after it
    adds a track. It costs one read of the embedding column.

    Non-fatal because the write has already happened: a track that is in the
    database and not yet in the cache appears at the next refresh or restart,
    which is a delay. Failing the fleet call instead would make the companion
    retry a result that is already applied.
    """
    try:
        from musicweb.search import refresh
        refresh(conn)
    except Exception as exc:                                    # noqa: BLE001
        log.warning('music ingest: could not refresh the search index (%s: %s); '
                    'the new track is in the database and will appear on the '
                    'next reload', type(exc).__name__, exc)


def _settle_scores(conn):
    """The unconditional rescore at the end of a batch. Never fatal.

    The other half of MUSIC-5 (2026-09-04): per-item rescoring is coalesced, so
    the last few tracks of a drop can be written and not yet tagged. A batch is
    finished exactly once, and this is the one place where paying for the full
    library pass is unambiguously worth it -- after it, `scores_stale` is clear
    and every track in the drop has its facets.

    Best-effort because the batch IS released: raising here would make the
    companion retry a release that already happened, and the marker plus the
    next result (or a base-rig --retag) still fix the scores.
    """
    if not rescore.scores_stale(conn):
        return
    try:
        rescore.rescore_library(conn)
        _refresh_search(conn)
    except Exception as exc:                                    # noqa: BLE001
        log.error('music ingest: the end-of-batch rescore failed (%s: %s); the '
                  'tracks are searchable by similarity and the library is '
                  'marked as needing a retag', type(exc).__name__, exc)


@router.post('/batches/{uid}/claim', dependencies=[Depends(require_fleet_token)])
def claim(uid: str, body: ClaimIn, editor: str = Depends(require_identity)):
    """Take the batch and receive the work order.

    Mints no `tracks` rows (see ingest_batches' docstring) -- what it settles
    is which machine owns the batch, until when, and what the items are.
    Idempotent for the machine that already holds it, because a companion
    restarting mid-batch re-issues exactly this call.
    """
    return ingest_batches.claim(
        con(), batch_uid=uid, editor=editor, machine=body.machine,
        companion_version=body.companion_version, capabilities=body.capabilities)


@router.post('/batches/{uid}/heartbeat', dependencies=[Depends(require_fleet_token)])
def heartbeat(uid: str, body: HeartbeatIn, editor: str = Depends(require_identity),
              x_ccsync_machine: str = Header(default=None)):
    """Keep the lease alive, and learn whether to stop.

    The reply carries `cancel_requested` and `upload_paused` rather than making
    the companion poll two more routes: this call already happens every 30 s,
    and a flag learned 30 s late is a flag acted on 30 s late, which is the
    whole budget for "cancel stops it within one heartbeat".
    """
    conn = con()
    batch = _leaseholder_or_410(conn, uid, editor, x_ccsync_machine)
    return ingest_batches.heartbeat(conn, batch)


@router.post('/batches/{uid}/items/{item_uid}/status',
             dependencies=[Depends(require_fleet_token)])
def item_status(uid: str, item_uid: str, body: ItemStatusIn,
                editor: str = Depends(require_identity),
                x_ccsync_machine: str = Header(default=None)):
    """One checkpoint. 400 on an illegal transition, 410 on a lost lease.

    Checkpoints are what make a companion restart cheap: the track comes back
    at the stage the server last heard about, not at zero.
    """
    conn = con()
    batch = _leaseholder_or_410(conn, uid, editor, x_ccsync_machine)
    item = _item_or_404(conn, uid, item_uid)
    return ingest_batches.set_item_state(
        conn, batch, item, state=body.state, stage_percent=body.stage_percent,
        error=body.error, attempts=body.attempts, content_hash=body.content_hash,
        transcoded=body.transcoded, probe=body.probe)


@router.post('/batches/{uid}/items/{item_uid}/result',
             dependencies=[Depends(require_fleet_token)])
def item_result(uid: str, item_uid: str, body: ItemResultIn,
                editor: str = Depends(require_identity),
                x_ccsync_machine: str = Header(default=None)):
    """The embedding the editor's machine computed, turned into a track.

    This is the route the whole design exists for: the audio tower ran where
    the audio is, and the SERVER -- which has the library, the text tower and
    everybody else's embeddings -- turns that vector into a row with tags and
    axes. Nothing here needs torch, and nothing here needs the file yet.
    """
    conn = con()
    batch = _leaseholder_or_410(conn, uid, editor, x_ccsync_machine)
    item = _item_or_404(conn, uid, item_uid)
    result = ingest_batches.write_item_result(conn, batch, item, body)
    # Only when the scores actually landed (MUSIC-5, 2026-09-04). A full
    # `search.Index` rebuild is a load_matrix + load_window_matrix +
    # projection.apply, and doing one per item made a 200-track album drop 200
    # complete rebuilds on the container's single worker. A deferred result is
    # still picked up: `search._looks_stale` re-stats the database (and its
    # -wal) every couple of seconds and rebuilds when it has moved, and
    # `release` forces both halves at the end of the batch.
    if not (result.get('scores') or {}).get('deferred'):
        _refresh_search(conn)
    return result


@router.post('/batches/{uid}/items/{item_uid}/uploaded',
             dependencies=[Depends(require_fleet_token)])
def item_uploaded(uid: str, item_uid: str, body: ItemUploadedIn,
                  editor: str = Depends(require_identity),
                  x_ccsync_machine: str = Header(default=None)):
    """Go live -- once the server has stat'ed the file itself.

    409 says whether it is absent or the wrong size, so an interrupted rclone
    retries the upload rather than the whole track.
    """
    conn = con()
    batch = _leaseholder_or_410(conn, uid, editor, x_ccsync_machine)
    item = _item_or_404(conn, uid, item_uid)
    return ingest_batches.mark_uploaded(conn, batch, item, size=body.size)


@router.post('/batches/{uid}/release', dependencies=[Depends(require_fleet_token)])
def release(uid: str, body: ReleaseIn, editor: str = Depends(require_identity),
            x_ccsync_machine: str = Header(default=None)):
    """Finish the batch and drop the lease.

    A CANCELLED release is accepted from a companion whose lease this route
    would otherwise have 410'd -- cancelling is exactly the case where the
    lease has already been expired by the dashboard, and refusing the release
    would leave the batch stuck in `running` with no machine behind it. So the
    lease check is relaxed to "this editor's batch" for that one state.
    """
    conn = con()
    if body.state == 'cancelled':
        batch = _batch_or_404(conn, uid)
        if batch['editor'] != editor:
            raise HTTPException(410, {'detail': 'this batch is not yours',
                                      'batch_uid': uid, 'reason': 'other_editor'})
        if batch['state'] in ingest_batches.BATCH_TERMINAL:
            return {'ok': True, 'state': batch['state'], 'already_finished': True}
    else:
        batch = _leaseholder_or_410(conn, uid, editor, x_ccsync_machine)
    out = ingest_batches.release(conn, batch, state=body.state,
                                 summary=body.summary)
    _settle_scores(conn)
    return out
