"""The companion's half of b-roll ingest: claim, lease, checkpoints, results.

docs/BROLL_INGEST_PLAN.md §4.2, 2026-08-18. Machine-to-machine, token-authed,
never a browser -- these calls happen with no page open, while an editor is
away from their desk and their companion crunches clips for an hour.

Three rules, all copied from ytdl's routes_fleet because the shape of the
problem is identical (docs/YTDL_LOCAL_DOWNLOAD.md §4) and one of them was
learned the hard way there:

  - **THE FLEET TOKEN, NOT THE SESSION**, and it FAILS CLOSED (fleet_auth).
  - **THE TOKEN IS NOT AN IDENTITY.** Every companion holds the same one, so
    the editor's name arrives as the dashboard's signed identity token and is
    verified before the batch's `editor` column is compared against it (H5,
    COMMERCIAL_READINESS.md item 7). Since CR-55 (2026-08-21) that token may
    also be a per-editor `cce1.` one, resolved for us by the dashboard's mount;
    when it is, the editor it is BOUND to must equal the signed identity, which
    is why both gates are now one dependency (fleet_auth.require_fleet_caller).
  - **THE BROWSER CONTRIBUTES A BATCH UID AND NOTHING ELSE.** Archive paths,
    names, the taxonomy, the settings -- all of it comes back from `claim`
    under the token. The page never learns a path and never dictates one; that
    is /music/send's principle applied to a work order.

**`X-CCSync-Machine` on every call after the claim.** The plan's bodies for
heartbeat/status/result/uploaded/release carry no machine name, so it rides a
header instead of being bolted onto five request models: it is what proves the
caller is still THIS editor's leaseholding machine rather than another of their
companions waking up with a stale state file. Absent, that one check is skipped
and the editor/lease/cancel checks still run -- an older companion degrades to
the pre-2026-08-18 guarantee rather than being locked out.

410, NOT 403, for every way a claim can end. The lease expired and the server
reclaimed the batch, the editor cancelled it, another of their machines took
it, the batch finished -- the companion's answer to all of them is the same
one, stop quietly, and a 403 would read as "fix your credentials" and be
retried forever. 403 is reserved for the two things that really are credential
problems: an unverifiable identity, and a claim on somebody else's batch.

Every handler is sync, SQLite-only and finishes in milliseconds: the dashboard
runs uvicorn with workers=1, so a handler that blocks blocks the page that
tells the whole fleet whether their footage is syncing.
"""
from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, Header, HTTPException

from app import ingest_batches
from app.db import get_db
from app.fleet_auth import require_fleet_caller
from app.schemas import (ClaimIn, HeartbeatIn, ItemResultIn, ItemStatusIn,
                         ItemUploadedIn, ReleaseIn)

log = logging.getLogger("broll.fleet")

# The path shape the dashboard's login_gate carve-out regex pins
# (app.py `_broll_fleet_re`). Changing this prefix, or the 32-hex uid shape,
# means changing that regex in the same commit -- otherwise every one of these
# calls is answered with a 303 to an HTML login page that no companion can
# follow, and b-roll ingest stops fleet-wide with nothing in this app's log.
router = APIRouter(prefix="/api/fleet/ingest")


def _batch_or_404(conn: sqlite3.Connection, uid: str) -> sqlite3.Row:
    batch = ingest_batches.get_batch(conn, uid)
    if batch is None:
        raise HTTPException(404, "no such batch")
    return batch


def _leaseholder_or_410(conn: sqlite3.Connection, uid: str, editor: str,
                        machine: str | None = None) -> sqlite3.Row:
    """The batch, if this VERIFIED editor on THIS machine still holds its lease.

    Four ways to fail and one answer to all of them, for the reason in the
    module docstring. A pending CANCEL is checked FIRST and separately from the
    lease even though the cancel route expires the lease too: they are two
    commits, and a status post landing between them must not be the one write
    that records a clip the editor cancelled (YTDL-WEB-1's lesson, 2026-08-14).

    `machine` is checked when the caller declares one. A companion always does;
    the parameter is optional so a call that has not been given a machine name
    still gets the editor/lease/cancel checks rather than skipping the guard
    entirely.
    """
    batch = _batch_or_404(conn, uid)
    if batch["cancel_requested"] and batch["state"] not in ingest_batches.BATCH_TERMINAL:
        raise HTTPException(410, {"detail": "this batch has been cancelled",
                                  "batch_uid": uid, "reason": "cancelled",
                                  "cancel_by": batch["cancel_by"]})
    if batch["state"] in ingest_batches.BATCH_TERMINAL:
        raise HTTPException(410, {"detail": f"this batch is {batch['state']}",
                                  "batch_uid": uid, "reason": "finished",
                                  "state": batch["state"]})
    if batch["editor"] != editor:
        raise HTTPException(410, {"detail": "this batch is no longer yours to index",
                                  "batch_uid": uid, "reason": "other_editor"})
    if machine and batch["machine"] != machine:
        raise HTTPException(410, {"detail": f"{batch['machine'] or 'another machine'} "
                                            "holds this batch now",
                                  "batch_uid": uid, "reason": "other_machine",
                                  "machine": batch["machine"]})
    if not ingest_batches.lease_live(batch):
        raise HTTPException(410, {"detail": "this batch's lease has expired and the "
                                            "server has taken it back",
                                  "batch_uid": uid, "reason": "lease_expired",
                                  "state": batch["state"]})
    return batch


def _item_or_404(conn: sqlite3.Connection, batch_uid: str, item_uid: str) -> sqlite3.Row:
    item = ingest_batches.get_item(conn, batch_uid, item_uid)
    if item is None:
        raise HTTPException(404, "no such item in this batch")
    return item


@router.post("/batches/{uid}/claim")
def claim(uid: str, body: ClaimIn,
          editor: str = Depends(require_fleet_caller),
          conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Take the batch and receive the whole work order.

    One transaction mints the `videos` rows (status `ingesting`, invisible to
    browse/tree/search), allocates every archive name against what is already
    published in that folder, records the share, and sets the lease. Idempotent
    for the machine that already holds it, because a companion restarting
    mid-batch re-issues exactly this call.
    """
    return ingest_batches.claim(
        conn, batch_uid=uid, editor=editor, machine=body.machine,
        companion_version=body.companion_version, tier=body.tier,
        capabilities=body.capabilities)


@router.post("/batches/{uid}/heartbeat")
def heartbeat(uid: str, body: HeartbeatIn,
              editor: str = Depends(require_fleet_caller),
              x_ccsync_machine: str | None = Header(default=None),
              conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Keep the lease alive, and learn whether to stop.

    The reply carries `cancel_requested` and `upload_paused` rather than making
    the companion poll two more routes: this call already happens every 30 s,
    and a flag the companion learns 30 s late is a flag it acts on 30 s late,
    which is the whole budget for "cancel stops it within one heartbeat".
    """
    batch = _leaseholder_or_410(conn, uid, editor, x_ccsync_machine)
    return ingest_batches.heartbeat(conn, batch)


@router.post("/batches/{uid}/items/{item_uid}/status")
def item_status(uid: str, item_uid: str, body: ItemStatusIn,
                editor: str = Depends(require_fleet_caller),
                x_ccsync_machine: str | None = Header(default=None),
                conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """One checkpoint. 400 on an illegal transition, 410 on a lost lease.

    Checkpoints are what make a companion restart cheap: the item comes back at
    the stage the server last heard about, not at zero.
    """
    batch = _leaseholder_or_410(conn, uid, editor, x_ccsync_machine)
    item = _item_or_404(conn, uid, item_uid)
    return ingest_batches.set_item_state(
        conn, batch, item, state=body.state, stage_percent=body.stage_percent,
        error=body.error, attempts=body.attempts, hash=body.hash, probe=body.probe)


@router.post("/batches/{uid}/items/{item_uid}/result")
def item_result(uid: str, item_uid: str, body: ItemResultIn,
                editor: str = Depends(require_fleet_caller),
                x_ccsync_machine: str | None = Header(default=None),
                conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """What the local model saw. The server writes it AND computes search_norm.

    That last part is the whole point of PR-D: `/api/ingest/index` used to
    insert segments with an empty `search_norm`, so anything indexed over HTTP
    was keyword-searchable only after a base-rig embed pass -- and dashboard
    ingest has no base rig behind it. A CJK on-screen-text term would simply
    never be found (see app/normalize.py's header).
    """
    batch = _leaseholder_or_410(conn, uid, editor, x_ccsync_machine)
    item = _item_or_404(conn, uid, item_uid)
    return ingest_batches.write_item_result(conn, batch, item, body)


@router.post("/batches/{uid}/items/{item_uid}/uploaded")
def item_uploaded(uid: str, item_uid: str, body: ItemUploadedIn,
                  editor: str = Depends(require_fleet_caller),
                  x_ccsync_machine: str | None = Header(default=None),
                  conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Go live -- once the server has stat'ed the files itself.

    409 lists exactly which files are missing or the wrong size, so an
    interrupted rclone retries those and not the clip.
    """
    batch = _leaseholder_or_410(conn, uid, editor, x_ccsync_machine)
    item = _item_or_404(conn, uid, item_uid)
    return ingest_batches.mark_uploaded(
        conn, batch, item, files=body.files, original_uploaded=body.original_uploaded)


@router.post("/batches/{uid}/release")
def release(uid: str, body: ReleaseIn,
            editor: str = Depends(require_fleet_caller),
            x_ccsync_machine: str | None = Header(default=None),
            conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Finish the batch and drop the lease.

    A CANCELLED release is accepted from a companion whose lease this route
    would otherwise have 410'd -- cancelling is exactly the case where the
    lease has already been expired by the dashboard, and refusing the release
    would leave the batch stuck in `running` with no machine behind it. So the
    lease check is relaxed to "this editor's batch" for that one state.
    """
    if body.state == "cancelled":
        batch = _batch_or_404(conn, uid)
        if batch["editor"] != editor:
            raise HTTPException(410, {"detail": "this batch is not yours",
                                      "batch_uid": uid, "reason": "other_editor"})
        if batch["state"] in ingest_batches.BATCH_TERMINAL:
            return {"ok": True, "state": batch["state"], "already_finished": True}
    else:
        batch = _leaseholder_or_410(conn, uid, editor, x_ccsync_machine)
    return ingest_batches.release(conn, batch, state=body.state, summary=body.summary)
