"""First-admin bootstrap for local accounts (WP C, docs/ZERO_TOUCH_PLAN.md
§3.3 step 2 / §3.5 step 2, 2026-08-17).

Two routes, both in app.py's `_OPEN_EXACT`, because nobody has a session yet
-- that is the whole point of a first-run wizard. Leaving `/api/v1/setup/admin`
open is still safe: the ONLY thing it can ever do is create the very FIRST
local admin account, and it refuses (409) the instant one exists --
local_users.any_users_exist is checked inside an explicit transaction so two
concurrent submits cannot both win. This is the exact contract agent D's
Setup wizard calls (docs/ZERO_TOUCH_PLAN.md §4 row D); do not change the
path or the body shape without updating that wizard.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import auth, local_users
from .db import connect as db_connect

log = logging.getLogger("ccsync.dashboard.setup_api")

router = APIRouter(prefix="/api/v1/setup")


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = db_connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def _auth_method(settings) -> str:
    return str(getattr(settings, "auth_method", "") or "smb").strip().lower()


@router.get("/status")
def setup_status(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    """Whether the wizard should show the "create your admin account" step.
    Open (app.py's _OPEN_EXACT) on the same terms as /api/v1/site: no secret
    in the answer, and the wizard needs it before anyone has signed in."""
    settings = request.app.state.settings
    method = _auth_method(settings)
    return {
        "auth_method": method,
        # Non-local methods never need this step; reporting True keeps a
        # wizard that asks blindly from ever offering to create a local
        # admin under smb/oidc, where DASH_ADMIN_USERS is the real answer.
        "users_exist": local_users.any_users_exist(conn) if method == "local" else True,
    }


class SetupAdminIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=256)


@router.post("/admin")
def setup_admin(
    payload: SetupAdminIn, request: Request, response: Response,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    settings = request.app.state.settings
    method = _auth_method(settings)
    if method != "local":
        raise HTTPException(
            status_code=403,
            detail="first-admin setup only applies when DASH_AUTH_METHOD=local",
        )
    username = payload.username.strip().lower()
    # BEGIN IMMEDIATE takes the write lock before the check, so two browsers
    # racing this route (a wizard reload, or two tabs) cannot both observe
    # "no users yet" and both create an admin -- the second one blocks on the
    # first's lock and then sees the first's row.
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if local_users.any_users_exist(conn):
            conn.rollback()
            raise HTTPException(status_code=409, detail="an admin account already exists")
        try:
            local_users.create_user(conn, username, payload.password, "admin",
                                    created_by="setup")
        except local_users.LocalUserError as exc:
            conn.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    log.info("first local admin %r created via setup wizard from %s",
             username, auth.client_ip(request))
    # Same cookie path as /login (auth.start_session): the wizard continues
    # logged in as the admin it just created, no second prompt
    # (ZERO_TOUCH_PLAN.md §3.5 step 2).
    auth.start_session(request, response, username)
    return {"ok": True, "user": username, "is_admin": True}
