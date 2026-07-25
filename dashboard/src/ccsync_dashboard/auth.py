"""Login verification + HMAC-signed session cookies.

Editors sign in with their TrueNAS credentials. Phase-0 findings (2026-07-24,
live 25.10.4): the middleware refuses ALL auth for non-admin users -- REST
/auth/* endpoints are gone (404) and WebSocket auth.login_ex returns AUTH_ERR
even with correct credentials for a plain editor account. The one thing that
does verify an editor's TrueNAS password is SMB session setup on :445 (every
editor is an SMB user by construction -- setup_editor_account.py), so that is
the primary method. `DASH_AUTH_METHOD` keeps the seam pluggable.

Sessions: `v1.<user>.<expires_epoch>.<hmac_sha256 hex>` in an HttpOnly cookie,
stdlib only. Secret comes from DASH_SESSION_SECRET and must be stable across
redeploys (the install script requires it) or everyone gets logged out.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid

from fastapi import Request

from .settings import Settings

log = logging.getLogger("ccsync.dashboard.auth")

COOKIE_NAME = "ccsync_session"
SESSION_TTL_SECONDS = 7 * 24 * 3600
IDENTITY_TTL_SECONDS = 30 * 24 * 3600   # companion machine-identity token
LOGIN_FAILURE_LIMIT = 5          # per username
LOGIN_FAILURE_WINDOW = 60.0      # seconds

# In-process failure tracking -- valid because the app runs a single worker.
_failures: dict[str, list[float]] = {}


# ------------------------------------------------------------ verification

def _verify_smb(host: str, username: str, password: str, timeout: float = 10.0) -> bool:
    from smbprotocol.connection import Connection
    from smbprotocol.session import Session

    conn = Connection(uuid.uuid4(), host, 445)
    try:
        conn.connect(timeout=timeout)
        session = Session(conn, username, password, require_encryption=False)
        try:
            session.connect()
            return True
        finally:
            try:
                session.disconnect()
            except Exception:
                pass
    except Exception as exc:
        log.debug("smb auth failed for %s: %s", username, exc)
        return False
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass


def verify_credentials(settings: Settings, username: str, password: str) -> bool:
    if not username or not password:
        return False
    if settings.auth_method == "smb":
        return _verify_smb(settings.smb_host, username, password)
    log.error("unknown DASH_AUTH_METHOD %r -- rejecting all logins", settings.auth_method)
    return False


def login_throttled(username: str, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    recent = [t for t in _failures.get(username, []) if now - t < LOGIN_FAILURE_WINDOW]
    _failures[username] = recent
    return len(recent) >= LOGIN_FAILURE_LIMIT


def record_login_failure(username: str, now: float | None = None) -> None:
    _failures.setdefault(username, []).append(time.monotonic() if now is None else now)


def clear_login_failures(username: str) -> None:
    _failures.pop(username, None)


# ------------------------------------------------------------ sessions

def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session_cookie(secret: str, username: str, now: float | None = None,
                        ttl: int = SESSION_TTL_SECONDS) -> str:
    expires = int((time.time() if now is None else now) + ttl)
    payload = f"v1.{username}.{expires}"
    return f"{payload}.{_sign(secret, payload)}"


def make_identity_token(secret: str, username: str, now: float | None = None) -> str:
    """Long-lived signed token the companion stores to prove which editor's
    machine it is. Same verifiable format as the session cookie, so
    read_session_cookie validates it too."""
    return make_session_cookie(secret, username, now=now, ttl=IDENTITY_TTL_SECONDS)


def read_session_cookie(secret: str, cookie: str | None, now: float | None = None) -> str | None:
    """Returns the username, or None for missing/expired/tampered cookies."""
    if not cookie or not secret:
        return None
    parts = cookie.split(".")
    if len(parts) != 4 or parts[0] != "v1":
        return None
    version, username, expires_s, signature = parts
    payload = f"{version}.{username}.{expires_s}"
    if not hmac.compare_digest(signature, _sign(secret, payload)):
        return None
    try:
        if int(expires_s) < (time.time() if now is None else now):
            return None
    except ValueError:
        return None
    return username


# ------------------------------------------------------------ fastapi glue

def get_session_user(request: Request) -> str | None:
    settings: Settings = request.app.state.settings
    return read_session_cookie(settings.session_secret, request.cookies.get(COOKIE_NAME))


def is_admin(settings: Settings, username: str | None) -> bool:
    if not username:
        return False
    return username.lower() in settings.admin_users


def can_manage(settings: Settings, session_user: str | None, editor: str) -> bool:
    if session_user is None:
        return False
    return session_user.lower() == editor.lower() or is_admin(settings, session_user)


class Scope:
    """Who the current viewer is allowed to see. Non-admins are locked to
    their own editor identity; admins see the whole fleet and may focus a
    single editor via ?as=<editor>."""

    def __init__(self, user: str | None, admin: bool, focus: str | None = None):
        self.user = user
        self.admin = admin
        self.focus = focus

    @property
    def editor(self) -> str | None:
        """The single editor this view is limited to, or None = all (admin,
        unfocused). Non-admins are always limited to themselves."""
        if not self.admin:
            return self.user
        return self.focus  # admin: focused editor or None for fleet-wide

    def allows(self, editor: str) -> bool:
        return self.admin or (self.user is not None and self.user.lower() == editor.lower())


def scope_for(request: Request) -> Scope:
    settings: Settings = request.app.state.settings
    user = get_session_user(request)
    admin = is_admin(settings, user)
    focus = request.query_params.get("as", "").strip().lower() or None
    if not admin:
        focus = None
    return Scope(user=user, admin=admin, focus=focus)
