"""The editor's half of client folders: /api/client-folders (session-shaped).

docs/CLIENT_FOLDERS.md, 2026-08-18. Curate a folder, get its link, see who
looked. Every route needs the dashboard gate's `X-CCSync-User` stamp
(routes_batches.require_user -- same contract, same reason: this app has no
session code and must not grow any). Any signed-in editor may create, edit and
revoke ANY folder: a client folder belongs to the studio, and "the one we sent
to X" has to be findable and fixable by whoever is at the desk. The public
base URL is the exception -- it is site configuration, and only an admin
(`X-CCSync-Admin: 1`) may set it.

Nothing here serves media or is reachable without a session; the public,
token-only, read-only door is routes_share.py.
"""
from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from app import client_folders as cf
from app import config
from app.db import get_db
from app.routes_batches import is_admin, require_user
from app.schemas import (
    ClientFolderCreateIn,
    ClientFolderItemsIn,
    ClientFolderNoteIn,
    ClientFolderOrderIn,
    ClientFolderUpdateIn,
    ClientShareSettingsIn,
)

log = logging.getLogger("broll.client_folders")

router = APIRouter(prefix="/api/client-folders")

# Where the public routes live, relative to this app's root. The SPA joins
# `public_base + <mount prefix> + SHARE_PATH + token + "/"`; the mount prefix
# is the SPA's to know (it is document-relative everywhere else too), so the
# API hands back only the origin and this suffix.
SHARE_PATH = "/share/"


def _folder_or_404(conn: sqlite3.Connection, folder_id: int) -> sqlite3.Row:
    folder = cf.get_folder(conn, folder_id)
    if folder is None:
        raise HTTPException(404, "no such client folder")
    return folder


def _bad_request(e: cf.ClientFolderError) -> HTTPException:
    return HTTPException(422, str(e))


def _summary(folder, n_items: int | None = None) -> dict:
    d = cf.folder_dict(folder) if not isinstance(folder, dict) else dict(folder)
    if n_items is not None:
        d["n_items"] = n_items
    d["share_path"] = f"{SHARE_PATH}{d['token']}/"
    return d


@router.get("")
@router.get("/")
def list_folders(
    video_id: int | None = Query(default=None),
    conn: sqlite3.Connection = Depends(cf.get_shares_db),
    user: str = Depends(require_user),
    admin: bool = Depends(is_admin),
) -> dict:
    """Every folder, plus the site's public base and, when `video_id` is
    given, which folders already hold that clip (the card popover's ticks)."""
    folders = [_summary(f) for f in cf.list_folders(conn)]
    if video_id is not None:
        holding = {r["folder_id"] for r in conn.execute(
            "SELECT folder_id FROM client_folder_items WHERE video_id = ?", (video_id,))}
        for f in folders:
            f["contains"] = f["id"] in holding
    return {
        "folders": folders,
        "public_base_url": cf.get_setting(conn, cf.SETTING_PUBLIC_BASE),
        "share_path": SHARE_PATH,
        "org": config.get_org_name(),
        "user": user,
        "is_admin": admin,
    }


@router.post("", status_code=201)
@router.post("/", status_code=201)
def create_folder(
    body: ClientFolderCreateIn,
    conn: sqlite3.Connection = Depends(cf.get_shares_db),
    user: str = Depends(require_user),
) -> dict:
    try:
        folder = cf.create_folder(conn, title=body.title, created_by=user,
                                  description=body.description, contact=body.contact,
                                  expires_at=body.expires_at)
    except cf.ClientFolderError as e:
        raise _bad_request(e) from e
    log.info("client folder %s created by %s: %r", folder["id"], user, folder["title"])
    return _summary(folder, n_items=0)


@router.get("/settings")
def get_settings(
    conn: sqlite3.Connection = Depends(cf.get_shares_db),
    _user: str = Depends(require_user),
) -> dict:
    return {"public_base_url": cf.get_setting(conn, cf.SETTING_PUBLIC_BASE)}


@router.put("/settings")
def put_settings(
    body: ClientShareSettingsIn,
    conn: sqlite3.Connection = Depends(cf.get_shares_db),
    user: str = Depends(require_user),
    admin: bool = Depends(is_admin),
) -> dict:
    """The public origin every link is minted against. Admin only: it is site
    configuration, and a wrong value silently breaks every link the studio
    has already sent out."""
    if not admin:
        raise HTTPException(403, "only an admin can change the public link base")
    try:
        base = cf.clean_public_base(body.public_base_url)
    except cf.ClientFolderError as e:
        raise _bad_request(e) from e
    cf.set_setting(conn, cf.SETTING_PUBLIC_BASE, base)
    log.info("client folder public base set to %r by %s", base, user)
    return {"public_base_url": base}


@router.get("/{folder_id}")
def get_folder(
    folder_id: int,
    conn: sqlite3.Connection = Depends(cf.get_shares_db),
    index: sqlite3.Connection = Depends(get_db),
    _user: str = Depends(require_user),
) -> dict:
    folder = _folder_or_404(conn, folder_id)
    items = cf.resolve_items(conn, index, folder_id, public=False)
    out = _summary(folder, n_items=len(items))
    out["items"] = items
    return out


@router.patch("/{folder_id}")
def update_folder(
    folder_id: int,
    body: ClientFolderUpdateIn,
    conn: sqlite3.Connection = Depends(cf.get_shares_db),
    _user: str = Depends(require_user),
) -> dict:
    _folder_or_404(conn, folder_id)
    # `"expires_at": null` in the body means "never expires"; a body without
    # the key means "leave it". Pydantic can only tell the two apart through
    # model_fields_set, so the distinction is made here, once.
    clear_expiry = "expires_at" in body.model_fields_set and body.expires_at is None
    try:
        folder = cf.update_folder(conn, folder_id, title=body.title,
                                  description=body.description, contact=body.contact,
                                  expires_at=body.expires_at, clear_expiry=clear_expiry)
    except cf.ClientFolderError as e:
        raise _bad_request(e) from e
    return _summary(folder)


@router.delete("/{folder_id}", status_code=204)
def delete_folder(
    folder_id: int,
    conn: sqlite3.Connection = Depends(cf.get_shares_db),
    user: str = Depends(require_user),
) -> None:
    folder = _folder_or_404(conn, folder_id)
    cf.delete_folder(conn, folder_id)
    log.info("client folder %s (%r) deleted by %s", folder_id, folder["title"], user)


@router.post("/{folder_id}/revoke")
def revoke(folder_id: int, conn: sqlite3.Connection = Depends(cf.get_shares_db),
           user: str = Depends(require_user)) -> dict:
    _folder_or_404(conn, folder_id)
    log.info("client folder %s link revoked by %s", folder_id, user)
    return _summary(cf.set_revoked(conn, folder_id, True))


@router.post("/{folder_id}/reactivate")
def reactivate(folder_id: int, conn: sqlite3.Connection = Depends(cf.get_shares_db),
               user: str = Depends(require_user)) -> dict:
    _folder_or_404(conn, folder_id)
    log.info("client folder %s link reactivated by %s", folder_id, user)
    return _summary(cf.set_revoked(conn, folder_id, False))


@router.post("/{folder_id}/rotate")
def rotate(folder_id: int, conn: sqlite3.Connection = Depends(cf.get_shares_db),
           user: str = Depends(require_user)) -> dict:
    """A fresh link; the old one is dead the moment this returns."""
    _folder_or_404(conn, folder_id)
    log.info("client folder %s link rotated by %s", folder_id, user)
    return _summary(cf.rotate_token(conn, folder_id))


@router.post("/{folder_id}/items")
def add_items(
    folder_id: int,
    body: ClientFolderItemsIn,
    conn: sqlite3.Connection = Depends(cf.get_shares_db),
    index: sqlite3.Connection = Depends(get_db),
    user: str = Depends(require_user),
) -> dict:
    _folder_or_404(conn, folder_id)
    try:
        result = cf.add_items(conn, index, folder_id, body.video_ids, added_by=user)
    except cf.ClientFolderError as e:
        raise _bad_request(e) from e
    result["n_items"] = conn.execute(
        "SELECT COUNT(*) FROM client_folder_items WHERE folder_id = ?", (folder_id,)
    ).fetchone()[0]
    return result


@router.delete("/{folder_id}/items/{video_id}", status_code=204)
def remove_item(
    folder_id: int, video_id: int,
    conn: sqlite3.Connection = Depends(cf.get_shares_db),
    _user: str = Depends(require_user),
) -> None:
    _folder_or_404(conn, folder_id)
    if not cf.remove_item(conn, folder_id, video_id):
        raise HTTPException(404, "that clip is not in this folder")


@router.put("/{folder_id}/items/{video_id}/note")
def set_note(
    folder_id: int, video_id: int,
    body: ClientFolderNoteIn,
    conn: sqlite3.Connection = Depends(cf.get_shares_db),
    _user: str = Depends(require_user),
) -> dict:
    _folder_or_404(conn, folder_id)
    try:
        ok = cf.set_note(conn, folder_id, video_id, body.note)
    except cf.ClientFolderError as e:
        raise _bad_request(e) from e
    if not ok:
        raise HTTPException(404, "that clip is not in this folder")
    return {"ok": True}


@router.put("/{folder_id}/order")
def set_order(
    folder_id: int,
    body: ClientFolderOrderIn,
    conn: sqlite3.Connection = Depends(cf.get_shares_db),
    _user: str = Depends(require_user),
) -> dict:
    _folder_or_404(conn, folder_id)
    cf.reorder(conn, folder_id, body.video_ids)
    return {"ok": True}
