"""The b-roll ingest panel's own API: what the BROWSER may do to a batch.

docs/BROLL_INGEST_PLAN.md §4.3, 2026-08-18. Six routes, all session-shaped, all
cheap: pre-check a drop, create a batch, list, read, cancel, pause uploads. The
work itself is dispatched over the loopback to the editor's companion and
executed against the FLEET routes next door (routes_fleet.py) -- nothing here
does anything slow, because the dashboard runs uvicorn with workers=1 and a
handler that blocks blocks the fleet status page.

**IDENTITY COMES FROM A HEADER THIS APP DOES NOT MINT.** `X-CCSync-User` (and
`X-CCSync-Admin`) are stamped by `ccsync_dashboard.broll.BrollGate` from the
session cookie, which it decodes with the dashboard's own secret; the gate
STRIPS any inbound copy first. That is the same contract /ytdl runs on, and it
exists because this app has no session code and must not grow any: a second
implementation of "who is logged in" is a second thing to get wrong. A request
that arrives with no header is answered 401 here -- if login_gate somehow let
it through, the sub-app still refuses.

`scope=all` additionally needs `X-CCSync-Admin: 1`. An editor may see and stop
their own batches; seeing which machine every other editor is sitting at, and
stopping their work, is an admin's business.
"""
from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app import config, ingest_batches
from app.archive_names import safe_name
from app.db import get_db
from app.schemas import IngestBatchCreateIn, IngestPrecheckIn, UploadPausedIn

log = logging.getLogger("broll.batches")

router = APIRouter(prefix="/api/ingest-batches")


def require_user(x_ccsync_user: str | None = Header(default=None)) -> str:
    """The signed-in editor, per the gate's stamp. 401 with no stamp.

    Fails closed on an EMPTY header too: the gate withholds it entirely for a
    name it cannot carry through a latin-1 header round trip (a CJK username --
    YTDL-29's lesson), and "" must not become an editor whose batches everyone
    with an unusable name shares.
    """
    user = (x_ccsync_user or "").strip()
    if not user:
        raise HTTPException(401, "not signed in")
    return user


def is_admin(x_ccsync_admin: str | None = Header(default=None)) -> bool:
    """Stamped alongside the identity, and stripped inbound the same way."""
    return (x_ccsync_admin or "").strip() == "1"


def _visible_or_404(conn: sqlite3.Connection, uid: str, user: str,
                    admin: bool) -> sqlite3.Row:
    """404, not 403, for another editor's batch.

    Telling a caller "that exists but is not yours" is telling them a uid they
    were not given, and uids are the only thing standing between an editor and
    another editor's batch on the loopback.
    """
    batch = ingest_batches.get_batch(conn, uid)
    if batch is None or (not admin and batch["editor"] != user):
        raise HTTPException(404, "no such batch")
    return batch


def _validated_share(raw: str) -> str:
    """The shoot folder name, or 422 naming what it should have been.

    Re-validated here even though the SPA sanitises the same way, because the
    SPA is not the only possible caller and this string becomes a directory in
    the shared archive. Refused rather than silently rewritten: an editor who
    typed `2026/07 shoot` should be told it will be `2026_07 shoot`, not
    discover it afterwards in a folder tree they cannot find their footage in.
    """
    share = (raw or "").strip()
    cleaned = safe_name(share.replace("/", "_").replace("\\", "_"))
    if not share or cleaned != share:
        raise HTTPException(422, {
            "detail": f"the shoot name must be {cleaned!r} (Windows forbids some "
                      f"characters, and the archive caps a name at "
                      f"{len(cleaned)} characters here)",
            "reason": "share_name", "suggestion": cleaned})
    return share


@router.post("/precheck")
def precheck(body: IngestPrecheckIn, user: str = Depends(require_user),
             conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Per clip: already in the archive? and what will it be called?

    Runs while the editor is still ticking boxes, so it reserves NOTHING -- the
    names come back as a preview and the real allocation happens inside the
    claim transaction. A name reserved here would be a name leaked by every
    abandoned drop.
    """
    share = _validated_share(body.share)
    return {"items": ingest_batches.precheck(
        conn, share=share, keep_subfolders=body.keep_subfolders, items=body.items)}


@router.post("")
@router.post("/")
def create(body: IngestBatchCreateIn, user: str = Depends(require_user),
           conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Queue a batch. The SPA then hands the uid to the local companion.

    Returns only the uid: everything else the companion needs comes from the
    claim, under the fleet token, because the browser must never be the source
    of a work order (the /music/send principle extended -- plan §1).
    """
    share = _validated_share(body.share)
    settings = ingest_batches.validate_settings(body.settings)
    collection = (body.collection or "").strip() or config.COLLECTION_CREATORS
    uid = ingest_batches.create_batch(
        conn, editor=user, share=share, collection=collection,
        settings=settings, items=body.items)
    return {"uid": uid, "state": "queued", "n_items": len(body.items)}


@router.get("")
@router.get("/")
def list_batches(scope: str = Query(default="mine"),
                 user: str = Depends(require_user),
                 admin: bool = Depends(is_admin),
                 conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """This editor's batches, or the whole fleet's for an admin.

    Expires stale leases on the way past. There is no timer in this app (see
    expire_stale_leases), and the list is the one call that happens whenever
    anybody is looking -- so a batch whose machine was switched off is back in
    `queued` by the time the page renders it.
    """
    if scope not in ("mine", "all"):
        raise HTTPException(422, "scope must be 'mine' or 'all'")
    if scope == "all" and not admin:
        raise HTTPException(403, {"detail": "only an admin can see every machine's "
                                            "batches", "reason": "admin_only"})
    ingest_batches.expire_stale_leases(conn)
    return {"scope": scope, "admin": admin,
            "batches": ingest_batches.list_batches(
                conn, editor=None if scope == "all" else user)}


@router.get("/{uid}")
def get_one(uid: str, user: str = Depends(require_user),
            admin: bool = Depends(is_admin),
            conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """One batch with its items -- the view the SPA falls back to when the
    loopback is unreachable or the page was reopened on another machine. The
    server's view is the truth after a reload; the companion's progress poll is
    only ever the faster one."""
    ingest_batches.expire_stale_leases(conn)
    batch = _visible_or_404(conn, uid, user, admin)
    return {"batch": ingest_batches.batch_public(batch),
            "items": [ingest_batches.item_public(i)
                      for i in ingest_batches.list_items(conn, uid)]}


@router.post("/{uid}/cancel")
def cancel(uid: str, user: str = Depends(require_user),
           admin: bool = Depends(is_admin),
           conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Ask the machine to stop. Owner or admin.

    Not a kill: this sets the flag and expires the lease, and the companion
    learns about it on its next heartbeat (410) or from the report reply. Clips
    already `live` stay -- their media is on the NAS and somebody may have cut
    with it.
    """
    batch = _visible_or_404(conn, uid, user, admin)
    if batch["state"] in ingest_batches.BATCH_TERMINAL:
        # Idempotent, not an error: two clicks, or a click on a batch that
        # finished while the page was stale, must not raise at an editor.
        return {"ok": True, "state": batch["state"], "already_finished": True}
    ingest_batches.cancel(conn, uid, user)
    return {"ok": True, "state": batch["state"], "cancel_requested": True}


@router.post("/{uid}/upload-paused")
def upload_paused(uid: str, body: UploadPausedIn, user: str = Depends(require_user),
                  admin: bool = Depends(is_admin),
                  conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Hold the uploads while the crunching continues.

    Separate from cancel because they are separate problems: an editor on a
    metered connection wants the indexing to go on and the bytes to wait, and
    the fleet halt does the same thing to the same queue.
    """
    batch = _visible_or_404(conn, uid, user, admin)
    ingest_batches.set_upload_paused(conn, uid, body.paused)
    return {"ok": True, "uid": batch["uid"], "upload_paused": body.paused}
