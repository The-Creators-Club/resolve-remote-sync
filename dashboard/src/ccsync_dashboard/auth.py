"""Login verification + HMAC-signed session cookies.

Editors sign in with their TrueNAS credentials. Phase-0 findings (2026-07-24,
live 25.10.4): the middleware refuses ALL auth for non-admin users -- REST
/auth/* endpoints are gone (404) and WebSocket auth.login_ex returns AUTH_ERR
even with correct credentials for a plain editor account. The one thing that
does verify an editor's TrueNAS password is SMB session setup on :445 (every
editor is an SMB user by construction -- setup_editor_account.py), so that is
the primary method. `DASH_AUTH_METHOD` keeps the seam pluggable.

Tokens: `v2.<purpose>.<user_b64url>.<expires_epoch>.<hmac_sha256 hex>` in an
HttpOnly cookie (session) or the X-CCSync-Identity header (identity),
stdlib only. `purpose` is "session" or "identity" -- read_session_cookie
only ever accepts "session" and read_identity_token only ever accepts
"identity", so one can never be replayed as the other (see SEC-1). The
username is base64url-encoded (no padding) so a dot in a username (a valid
character per db.py's `_USERNAME_RE`) can never be confused with a field
separator (see S-9). Secret comes from DASH_SESSION_SECRET and must be
stable across redeploys (the install script requires it) or everyone gets
logged out.

v1 tokens (pre-2026-07-25) are rejected outright -- this is a hard cutover,
not a compatibility shim. Every editor and every companion re-authenticates
once after a deploy of this change.
"""
from __future__ import annotations

import base64
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

_TOKEN_VERSION = "v2"
PURPOSE_SESSION = "session"
PURPOSE_IDENTITY = "identity"

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


def _evict_expired_failures(now: float) -> None:
    """Sweep every username's failure list, dropping expired timestamps and
    the whole entry once it's empty. Called on every login attempt (cheap at
    fleet scale) so failed logins against throwaway/random usernames don't
    grow the dict forever (see SEC-12)."""
    for username in list(_failures.keys()):
        recent = [t for t in _failures[username] if now - t < LOGIN_FAILURE_WINDOW]
        if recent:
            _failures[username] = recent
        else:
            _failures.pop(username, None)


def login_throttled(username: str, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    _evict_expired_failures(now)
    recent = _failures.get(username, [])
    return len(recent) >= LOGIN_FAILURE_LIMIT


def record_login_failure(username: str, now: float | None = None) -> None:
    _failures.setdefault(username, []).append(time.monotonic() if now is None else now)


def clear_login_failures(username: str) -> None:
    _failures.pop(username, None)


# ------------------------------------------------------------ sessions

def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _b64u_encode(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).rstrip(b"=").decode("ascii")


def _b64u_decode(value: str) -> str | None:
    try:
        padded = value + "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception:
        return None


def _make_token(secret: str, purpose: str, username: str, now: float | None = None,
                ttl: int = SESSION_TTL_SECONDS) -> str:
    expires = int((time.time() if now is None else now) + ttl)
    user_b64 = _b64u_encode(username)
    payload = f"{_TOKEN_VERSION}.{purpose}.{user_b64}.{expires}"
    return f"{payload}.{_sign(secret, payload)}"


def make_session_cookie(secret: str, username: str, now: float | None = None,
                        ttl: int = SESSION_TTL_SECONDS) -> str:
    return _make_token(secret, PURPOSE_SESSION, username, now=now, ttl=ttl)


def make_identity_token(secret: str, username: str, now: float | None = None) -> str:
    """Long-lived signed token the companion stores to prove which editor's
    machine it is. Same HMAC scheme as the session cookie but signed with
    purpose="identity" -- read_session_cookie only accepts purpose="session"
    and read_identity_token only accepts purpose="identity", so this token
    can never be replayed as a browser session (see SEC-1)."""
    return _make_token(secret, PURPOSE_IDENTITY, username, now=now, ttl=IDENTITY_TTL_SECONDS)


def _read_token(secret: str, token: str | None, purpose: str, now: float | None = None) -> str | None:
    """Returns the username, or None for missing/expired/tampered/wrong-purpose
    tokens. v1 tokens (no purpose claim, raw username) are rejected outright --
    hard cutover, see module docstring."""
    if not token or not secret:
        return None
    parts = token.split(".")
    if len(parts) != 5:
        return None
    version, tok_purpose, user_b64, expires_s, signature = parts
    if version != _TOKEN_VERSION or tok_purpose != purpose:
        return None
    payload = f"{version}.{tok_purpose}.{user_b64}.{expires_s}"
    if not hmac.compare_digest(signature, _sign(secret, payload)):
        return None
    try:
        if int(expires_s) < (time.time() if now is None else now):
            return None
    except ValueError:
        return None
    username = _b64u_decode(user_b64)
    if not username:
        return None
    return username


def read_session_cookie(secret: str, cookie: str | None, now: float | None = None) -> str | None:
    """Returns the username, or None for missing/expired/tampered cookies --
    or a cookie that is actually a valid IDENTITY token (see SEC-1)."""
    return _read_token(secret, cookie, PURPOSE_SESSION, now=now)


def read_identity_token(secret: str, token: str | None, now: float | None = None) -> str | None:
    """Returns the username for a valid X-CCSync-Identity token, or None --
    including for a token that is actually a valid SESSION cookie."""
    return _read_token(secret, token, PURPOSE_IDENTITY, now=now)


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
