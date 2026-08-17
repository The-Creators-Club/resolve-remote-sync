"""Internal SFTP identity endpoints (WP C, docs/ZERO_TOUCH_PLAN.md §3.3 /
§4 row C, 2026-08-17): what the sftp sidecar's `AuthorizedKeysCommand` and
user-listing step call to find out who may connect and which keys are
theirs.

NOT under `/api/v1` and NOT behind the session -- the sidecar is a separate
container with no cookie jar and no browser (docs/ZERO_TOUCH_PLAN.md §3.1's
compose shape). The gate is a bearer token instead, read from
`CCSYNC_INTERNAL_TOKEN` or the file agent D's SetupEngine generates at
`<data dir>/secrets/internal_token` (this module only ever READS that file).
A deployment with neither configured answers 503 on both routes -- an
internal endpoint that authenticates everyone when unconfigured is worse
than one that refuses outright.

Contract for the sidecar (see docs/API.md):
  GET  /internal/sftp/users        -> {"users": [{"username","uid","gid"}, ...]}
  GET  /internal/sftp/keys/<user>  -> text/plain authorized_keys lines, or 404
Both: `Authorization: Bearer <token>`.
"""
from __future__ import annotations

import hmac
import logging
import os
import sqlite3
from typing import Iterator

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse

from . import local_users
from .db import connect as db_connect

log = logging.getLogger("ccsync.dashboard.internal_sftp")

router = APIRouter(prefix="/internal/sftp")


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = db_connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def _configured_token(settings) -> str | None:
    """The bearer token this deployment accepts, or None when nothing is
    configured. CCSYNC_INTERNAL_TOKEN wins when set; otherwise the file agent
    D's SetupEngine writes at first boot -- this module reads it fresh on
    every call (not cached) so a rotated secret takes effect without a
    restart, which the sidecar itself will need on the same schedule."""
    token = (getattr(settings, "internal_token", "") or "").strip()
    if token:
        return token
    path = settings.secrets_path("internal_token")
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def _require_internal_token(request: Request, authorization: str | None) -> None:
    settings = request.app.state.settings
    expected = _configured_token(settings)
    if not expected:
        raise HTTPException(status_code=503, detail="internal token not configured")
    presented = authorization or ""
    if presented.lower().startswith("bearer "):
        presented = presented[len("bearer "):]
    presented = presented.strip()
    ok = bool(presented) and hmac.compare_digest(presented, expected)
    if not ok:
        peer = getattr(getattr(request, "client", None), "host", "") or "?"
        log.warning("internal/sftp: refused %s %s from %s (bad or missing bearer token)",
                    request.method, request.url.path, peer)
        raise HTTPException(status_code=401, detail="bad or missing bearer token")


def _uid_gid() -> tuple[int, int]:
    """The uid/gid every local account's files land owned by -- SFTP is a
    SINGLE service account in this design (ZERO_TOUCH_PLAN.md §5: "no
    per-editor NAS accounts"), so every user in the answer gets the same
    pair: this process's own ids. APP_UID/APP_GID override them when set
    (the sftp sidecar's own compose entry may know its uid before this
    process does); Windows dev (no os.getuid) falls back to a fixed pair so
    the dashboard suite runs unprivileged on a dev machine."""
    app_uid = os.environ.get("APP_UID", "").strip()
    app_gid = os.environ.get("APP_GID", "").strip()
    if app_uid and app_gid:
        try:
            return int(app_uid), int(app_gid)
        except ValueError:
            log.warning("APP_UID/APP_GID are set but not integers (%r/%r) -- ignored",
                        app_uid, app_gid)
    if hasattr(os, "getuid"):
        return os.getuid(), os.getgid()  # type: ignore[attr-defined]
    return 3000, 3001


@router.get("/users")
def internal_sftp_users(
    request: Request, conn: sqlite3.Connection = Depends(get_conn),
    authorization: str | None = Header(default=None),
) -> dict:
    _require_internal_token(request, authorization)
    uid, gid = _uid_gid()
    users = [
        {"username": u["username"], "uid": uid, "gid": gid}
        for u in local_users.list_users(conn)
        if not u["disabled"] and u["role"] in ("admin", "editor") and u["ssh_keys"]
    ]
    return {"users": users}


@router.get("/keys/{username}", response_class=PlainTextResponse)
def internal_sftp_keys(
    username: str, request: Request, conn: sqlite3.Connection = Depends(get_conn),
    authorization: str | None = Header(default=None),
) -> str:
    _require_internal_token(request, authorization)
    username = (username or "").strip().lower()
    user = local_users.get_user(conn, username)
    if user is None or user["disabled"]:
        raise HTTPException(status_code=404, detail="unknown or disabled user")
    keys = local_users.keys_for(conn, username)
    # sshd's own `Match Group` / chroot block is what restricts the session
    # (docs/ZERO_TOUCH_PLAN.md §3.1); no `restrict,`/`command=` prefix is
    # added here, since that would be this dashboard silently overriding the
    # sidecar's own sshd_config rather than the sidecar owning its policy.
    return "".join(f"{k['key_text']}\n" for k in keys)
