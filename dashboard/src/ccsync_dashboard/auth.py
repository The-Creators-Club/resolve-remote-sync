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

2026-08-17 (COMMERCIAL_READINESS.md items 6/H1, 12 and 15) the cookie stopped
being the whole story. It is still the token above, but a session now also has
a SERVER-SIDE row (sessions.py) keyed by HMAC(secret, cookie), and a cookie
with no row is not a session -- which is what makes logout, "log out
everywhere" and an admin's revoke button mean anything at all. Three more
things landed with it, and they are all in this module: X-Forwarded-Proto is
believed only from a configured proxy (it used to be believed from anyone, so
any host on the tailnet decided whether the Secure flag went on); the login
throttle moved into SQLite with an IP budget beside the username one; and the
boot-time secret floor reuses broll.check_ingest_token, so a weak
DASH_SESSION_SECRET -- a forgeable ADMIN cookie -- refuses to serve. The CSRF
synchroniser token is derived here too, from the session id, so it needs no
storage and cannot be minted without the secret.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import logging
import threading
import time
import uuid

from fastapi import Request, Response

from . import broll, sessions
from .settings import Settings

log = logging.getLogger("ccsync.dashboard.auth")

COOKIE_NAME = "ccsync_session"
SESSION_TTL_SECONDS = 7 * 24 * 3600
IDENTITY_TTL_SECONDS = 30 * 24 * 3600   # companion machine-identity token
LOGIN_FAILURE_LIMIT = sessions.LOGIN_FAILURE_LIMIT   # kept as the public name

_TOKEN_VERSION = "v2"
PURPOSE_SESSION = "session"
PURPOSE_IDENTITY = "identity"

# Minimum length for a password this dashboard SETS on the NAS. Enforced on
# set/change only (COMMERCIAL_READINESS.md item 15's "admin password min
# length 1", 2026-08-17): raising the floor must never lock an existing editor
# out of a fleet that is mid-shoot, so accounts already below it keep working
# and are named -- without their passwords -- in one WARNING at boot.
MIN_PASSWORD_CHARS = 12

# Concurrency cap on the blocking SMB probe. /login and /api/v1/verify are both
# unauthenticated and both spend up to 10s inside smbprotocol; without a cap,
# 60 concurrent requests against a blackholing SMB host consume every anyio
# worker and queue every other route (including companions' reports) behind
# them. The per-username throttle bounds RATE, not concurrency, and is trivially
# bypassed by rotating usernames.
MAX_CONCURRENT_SMB_PROBES = 4
SMB_PROBE_QUEUE_SECONDS = 2.0
_probe_slots = threading.Semaphore(MAX_CONCURRENT_SMB_PROBES)


class CredentialProbeBusy(Exception):
    """Too many credential probes in flight; the caller should answer 503."""


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
            # smbprotocol does NOT reject a session the server mapped to guest
            # or to anonymous/null. If the NAS's SMB service ever maps bad
            # passwords to guest, every password would otherwise authenticate
            # for every username -- including anyone in DASH_ADMIN_USERS.
            # SMB2_SESSION_FLAG_IS_GUEST = 0x0001, IS_NULL = 0x0002.
            flags = int(getattr(session, "session_flags", 0) or 0)
            if flags != 0:
                log.error(
                    "REJECTING smb auth for %s: server returned session_flags=0x%04x "
                    "(guest/null-mapped session -- not a real credential check)",
                    username, flags)
                return False
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
    # "oidc" verifies passwords the same way: the local password form is the
    # BREAK-GLASS path (/login?local=1) for when the IdP is unreachable, and
    # SMB is still the only thing that can check a NAS password. ui.py is what
    # limits that path to DASH_ADMIN_USERS when OIDC is the configured method.
    if settings.auth_method in ("smb", "oidc"):
        if not _probe_slots.acquire(timeout=SMB_PROBE_QUEUE_SECONDS):
            raise CredentialProbeBusy(
                f"more than {MAX_CONCURRENT_SMB_PROBES} credential checks already in flight"
            )
        try:
            return _verify_smb(settings.smb_host, username, password)
        finally:
            _probe_slots.release()
    log.error("unknown DASH_AUTH_METHOD %r -- rejecting all logins", settings.auth_method)
    return False


# --------------------------------------------------------- login throttle
# The budgets themselves live in SQLite (sessions.SessionStore): an in-process
# dict lost every failure count on the container restart that each deploy
# performs, and counted usernames only -- so one host could spray one password
# across the whole fleet's usernames at full speed (COMMERCIAL_READINESS.md
# item 15, 2026-08-17). These wrappers are what the routes call; they take the
# Request because the IP budget needs the peer and the store lives on
# app.state.

def client_ip(request: Request | None) -> str:
    """The peer address, and deliberately NOT anything X-Forwarded-For says
    unless the peer is a proxy we configured. A spoofable IP budget is worse
    than none: it lets an attacker exhaust an innocent editor's budget."""
    if request is None:
        return ""
    peer = getattr(getattr(request, "client", None), "host", "") or ""
    if not peer or not trusted_proxy(_settings_of(request), peer):
        return peer
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return forwarded or peer


def login_throttled(request: Request | None, username: str,
                    now: str | None = None) -> float:
    """Seconds to wait before this (username, IP) may try again; 0.0 = clear."""
    store = session_store(request)
    if store is None:
        return 0.0
    return store.throttled(username, client_ip(request), now=now)


def record_login_failure(request: Request | None, username: str,
                         now: str | None = None) -> None:
    store = session_store(request)
    if store is None:
        return
    ip = client_ip(request)
    store.record_failure(username, ip, now=now)
    # Logged at WARNING, without the password and without the attempted
    # password's length: a failed sign-in is the event an operator greps for.
    log.warning("login failure for %r from %s", username, ip or "?")


def clear_login_failures(request: Request | None, username: str) -> None:
    store = session_store(request)
    if store is not None:
        store.clear_failures(username, client_ip(request))


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
                ttl: int = SESSION_TTL_SECONDS, nonce: str = "") -> str:
    expires = int((time.time() if now is None else now) + ttl)
    user_b64 = _b64u_encode(username)
    middle = f"{user_b64}.{nonce}" if nonce else user_b64
    payload = f"{_TOKEN_VERSION}.{purpose}.{middle}.{expires}"
    return f"{payload}.{_sign(secret, payload)}"


def make_session_cookie(secret: str, username: str, now: float | None = None,
                        ttl: int = SESSION_TTL_SECONDS, nonce: str | None = None) -> str:
    """A session cookie, unique per call.

    The nonce (2026-08-17) is what makes two browsers signing in as the same
    editor in the same SECOND two different sessions: without it the token is
    a pure function of (secret, username, expiry-in-whole-seconds), so both
    got byte-identical cookies -- and therefore one shared server-side session
    row, where revoking either would have revoked both. Identity tokens keep
    the five-field shape they always had; the companion parses those
    (identity.parse_token) and must not be asked to learn a sixth field."""
    if nonce is None:
        nonce = _b64u_encode(uuid.uuid4().hex[:12])
    return _make_token(secret, PURPOSE_SESSION, username, now=now, ttl=ttl, nonce=nonce)


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
    # Six fields = a session cookie with a per-login nonce (2026-08-17); five =
    # an identity token, or a session cookie minted before the nonce existed.
    # Both are accepted, and the signature covers whichever shape arrived.
    if len(parts) == 6 and purpose == PURPOSE_SESSION:
        version, tok_purpose, user_b64, nonce, expires_s, signature = parts
        middle = f"{user_b64}.{nonce}"
    elif len(parts) == 5:
        version, tok_purpose, user_b64, expires_s, signature = parts
        middle = user_b64
    else:
        return None
    if version != _TOKEN_VERSION or tok_purpose != purpose:
        return None
    payload = f"{version}.{tok_purpose}.{middle}.{expires_s}"
    try:
        if not hmac.compare_digest(signature, _sign(secret, payload)):
            return None
    except TypeError:
        # compare_digest refuses non-ASCII str, and a cookie is attacker-shaped
        # input decoded latin-1 -- one accented byte in ccsync_session used to
        # 500 with a traceback, pre-auth, on every gated path (DASH-5 twin,
        # YTDL-32, 2026-08-11). A garbage token is a 401, never a crash.
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

def _settings_of(request: Request | None) -> Settings | None:
    return getattr(getattr(getattr(request, "app", None), "state", None), "settings", None)


def session_store(request: Request | None) -> "sessions.SessionStore | None":
    """The app's session/throttle store. None only for a Request built without
    an app (unit tests of the pure token helpers)."""
    return getattr(getattr(getattr(request, "app", None), "state", None),
                   "session_store", None)


def dev_insecure(settings: Settings | None) -> bool:
    return bool(getattr(settings, "dev_insecure", False))


# ------------------------------------------------------- trusted proxies

def _parse_networks(spec: str) -> list[ipaddress._BaseNetwork]:
    nets: list[ipaddress._BaseNetwork] = []
    for raw in (spec or "").replace(";", ",").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            nets.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            log.error("DASH_TRUSTED_PROXIES entry %r is not an IP or CIDR -- ignored", raw)
    return nets


def trusted_proxy(settings: Settings | None, peer: str | None) -> bool:
    """Is `peer` a front-end whose X-Forwarded-* headers we believe?

    Before 2026-08-17 the answer was "everybody": any host that could reach the
    dashboard could claim `X-Forwarded-Proto: https` and decide whether the
    Secure flag went on the session cookie (COMMERCIAL_READINESS.md item 6 /
    H1). Tailscale Serve and a compose sidecar both connect over loopback,
    which is why loopback alone is the default."""
    if not peer:
        return False
    try:
        address = ipaddress.ip_address(peer.strip().strip("[]"))
    except ValueError:
        return False
    spec = str(getattr(settings, "trusted_proxies", "") or "")
    return any(address in net for net in _parse_networks(spec))


def request_is_https(settings: Settings | None, request: Request) -> bool:
    """The scheme as far as the BROWSER is concerned."""
    if (request.url.scheme or "").lower() == "https":
        return True
    peer = getattr(getattr(request, "client", None), "host", "") or ""
    if not trusted_proxy(settings, peer):
        return False
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return forwarded == "https"


def cookie_secure(settings: Settings, request: Request) -> bool:
    """Whether to set Secure on the session cookie.

    DASH_COOKIE_SECURE=auto (default) means "on for https, off for http": the
    fleet is served over plain http on the LAN/tailnet today, and a hardcoded
    secure=True there makes the browser silently drop the cookie -- an
    unloggable, total outage. Behind a TLS terminator the request scheme is
    https and the flag turns itself on. X-Forwarded-Proto is honoured only from
    a configured trusted proxy (see trusted_proxy). Force it with
    DASH_COOKIE_SECURE=1 (or 0)."""
    mode = str(getattr(settings, "cookie_secure", "auto") or "auto").strip().lower()
    if mode in ("1", "true", "yes", "on"):
        return True
    if mode in ("0", "false", "no", "off"):
        return False
    return request_is_https(settings, request)


def refuse_plaintext_login(settings: Settings, request: Request) -> bool:
    """DASH_COOKIE_SECURE=1 promises the browser that the cookie only ever
    travels over TLS. Serving the login form on a connection that is NOT https
    under that promise is the worst of both worlds: the password crosses in
    clear AND the browser then drops the Secure cookie, so the editor loops on
    the login page forever with no error anywhere. Refuse instead, loudly.

    The X-Forwarded-Proto header is honoured here WITHOUT the trusted-proxy
    check, unlike everywhere else, and the asymmetry is deliberate. Believing
    an untrusted header can only make this function refuse LESS, never set a
    Secure flag it should not; whereas demanding a trusted peer would refuse
    every login on a perfectly good deployment whose TLS terminator sits on
    the docker host and therefore arrives from the bridge gateway. Fail-open
    is the safe direction for a refusal and fail-closed is the safe direction
    for a flag."""
    mode = str(getattr(settings, "cookie_secure", "auto") or "auto").strip().lower()
    if mode not in ("1", "true", "yes", "on"):
        return False
    if (request.url.scheme or "").lower() == "https":
        return False
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return forwarded != "https"


# ---------------------------------------------------- server-side sessions

def session_id_for(secret: str, cookie: str) -> str:
    """The sessions-table key for a cookie: a keyed digest, never the cookie.

    Derived rather than embedded so the cookie's wire format (and therefore
    every companion, every open tab and every format test) is untouched by
    sessions becoming revocable -- see sessions.py."""
    return hmac.new(secret.encode(), b"sid|" + cookie.encode("utf-8", "replace"),
                    hashlib.sha256).hexdigest()


def _resolve_session(request: Request) -> tuple[str | None, str | None, bool]:
    """(username, sid, tracked) for this request's cookie.

    `tracked` = "this server minted this session and still has its row", which
    is every session in a deployment and none of the hand-signed cookies the
    suite mints. It is what the CSRF gate keys on, so the gate can be strict
    without 151 existing test call sites having to learn a token."""
    settings = _settings_of(request)
    secret = getattr(settings, "session_secret", "") or ""
    cookie = request.cookies.get(COOKIE_NAME)
    username = read_session_cookie(secret, cookie)
    if username is None or not cookie:
        return None, None, False
    sid = session_id_for(secret, cookie)
    store = session_store(request)
    if store is None:
        return username, sid, False
    live = store.validate(sid)
    if live is not None:
        return live, sid, True
    # No row: revoked, expired, or minted before this deployment (or by a test
    # that hand-signed a cookie). The cookie is cryptographically ours either
    # way, so this is a REVOCATION decision, not an authentication one -- and
    # the strict answer is the only one that makes "log out everywhere" mean
    # anything. dev_insecure keeps hand-minted cookies working in the suite.
    if dev_insecure(settings):
        return username, sid, False
    return None, None, False


def get_session_user(request: Request) -> str | None:
    """Cached per request: login_gate, _render, scope_for and _queue_editor all
    ask, and each answer is now a SQLite read."""
    cached = getattr(request.state, "ccsync_session", None)
    if cached is None:
        cached = _resolve_session(request)
        request.state.ccsync_session = cached
    return cached[0]


def get_session_id(request: Request) -> str | None:
    get_session_user(request)
    return request.state.ccsync_session[1]


def session_is_tracked(request: Request) -> bool:
    get_session_user(request)
    return bool(request.state.ccsync_session[2])


def start_session(request: Request, response: Response, username: str) -> str:
    """Mint the cookie, record the server-side session, set the cookie."""
    settings: Settings = request.app.state.settings
    # The token's own expiry is the absolute lifetime, so a site that RAISES
    # DASH_SESSION_ABSOLUTE_SECONDS does not find its sessions ending at the
    # module default seven days anyway.
    ttl = int(getattr(settings, "session_absolute_seconds", SESSION_TTL_SECONDS)
              or SESSION_TTL_SECONDS)
    cookie = make_session_cookie(settings.session_secret, username, ttl=ttl)
    sid = session_id_for(settings.session_secret, cookie)
    store = session_store(request)
    if store is not None:
        store.create(sid, username, sessions.summarize_client(
            client_ip(request), request.headers.get("user-agent")))
    response.set_cookie(
        COOKIE_NAME, cookie,
        # The browser-side expiry matches the ABSOLUTE server-side lifetime;
        # the idle lifetime is enforced server-side only, because a cookie
        # cannot express "and keep being used".
        max_age=ttl,
        httponly=True, samesite="lax",
        secure=cookie_secure(settings, request), path="/",
    )
    request.state.ccsync_session = (username, sid, store is not None)
    return sid


def end_session(request: Request, response: Response) -> None:
    """Log out: revoke the server-side record FIRST, then drop the cookie.
    Deleting the cookie alone (what logout used to do) left a stolen copy
    valid for the rest of its seven days."""
    sid = get_session_id(request)
    store = session_store(request)
    if sid and store is not None:
        store.revoke(sid, by="logout")
    response.delete_cookie(COOKIE_NAME, path="/")
    request.state.ccsync_session = (None, None, False)


# ------------------------------------------------------------------ CSRF

CSRF_HEADER = "x-csrf-token"
CSRF_FIELD = "csrf"


def csrf_token(request: Request) -> str:
    """A synchroniser token bound to the session, so it needs no storage and
    cannot be minted by anyone without the session secret. Anonymous requests
    get "" -- there is nothing to protect until there is a session."""
    settings = _settings_of(request)
    secret = getattr(settings, "session_secret", "") or ""
    sid = get_session_id(request)
    if not secret or not sid:
        return ""
    return hmac.new(secret.encode(), b"csrf|" + sid.encode(),
                    hashlib.sha256).hexdigest()


def csrf_ok(request: Request, presented: str | None) -> bool:
    expected = csrf_token(request)
    if not expected:
        return False
    try:
        return hmac.compare_digest(expected, (presented or "").strip())
    except TypeError:
        # A non-ASCII header value reaches compare_digest as non-ASCII str and
        # raises -- the DASH-5 shape. A garbage token is a refusal, never a 500.
        return False


# ------------------------------------------------------------- boot checks

def _placeholder_or_weak(name: str, value: str) -> str | None:
    """The ingest token's rule, reused verbatim (COMMERCIAL_READINESS.md item
    15): >= 24 chars, not a placeholder, enough variety to be random. A weak
    DASH_SESSION_SECRET is a forgeable admin cookie; a weak DASH_REPORT_TOKEN
    is fleet-wide write access."""
    problem = broll.check_ingest_token(value)
    return None if problem is None else f"{name} {problem}"


def check_boot_secrets(settings: Settings) -> list[str]:
    """Reasons this configuration must not serve, in operator language.

    Only secrets that are actually IN USE are checked: a deployment with no
    DASH_SESSION_SECRET has login switched off entirely (a documented lab
    shape), and one with no DASH_REPORT_TOKEN rejects every report already.
    What is refused is a secret that is present and weak."""
    problems: list[str] = []
    if settings.session_secret:
        problem = _placeholder_or_weak("DASH_SESSION_SECRET", settings.session_secret)
        if problem:
            problems.append(problem)
    if settings.report_token:
        problem = _placeholder_or_weak("DASH_REPORT_TOKEN", settings.report_token)
        if problem:
            problems.append(problem)
    mode = str(settings.cookie_secure or "auto").strip().lower()
    if mode in ("1", "true", "yes", "on") and not _tls_path_configured(settings):
        problems.append(
            "DASH_COOKIE_SECURE=1 promises the session cookie only travels over TLS, but "
            "no TLS path is configured: DASH_SITE_DASHBOARD_URL is not an https:// URL and "
            "DASH_TRUSTED_PROXIES names no front-end. Publish the dashboard through "
            "Tailscale Serve (docs/SERVER-SYNOLOGY.md) and set DASH_SITE_DASHBOARD_URL to "
            "its https URL, or leave DASH_COOKIE_SECURE=auto"
        )
    if str(settings.auth_method or "").strip().lower() == "oidc":
        problems.extend(check_oidc_settings(settings))
    return problems


def _tls_path_configured(settings: Settings) -> bool:
    """"Something in front of us terminates TLS." Either the site says so
    (its published URL is https) or a proxy is trusted to say so per request."""
    if str(getattr(settings, "site_dashboard_url", "") or "").lower().startswith("https://"):
        return True
    return bool(_parse_networks(str(getattr(settings, "trusted_proxies", "") or "")))


def _issuer_transport_ok(issuer: str) -> bool:
    """https, or http to LOOPBACK.

    The loopback carve-out is not a dev convenience: an IdP running as a
    sidecar in the same compose stack is reached over the container network
    with no certificate to present, and this is exactly the shape the trusted-
    proxy default already assumes. Anything else must be https -- the client
    secret and the id_token both cross that connection."""
    issuer = str(issuer or "").lower()
    if issuer.startswith("https://"):
        return True
    if not issuer.startswith("http://"):
        return False
    host = issuer[len("http://"):].split("/")[0].split(":")[0].strip("[]")
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_oidc_settings(settings: Settings) -> list[str]:
    missing = [
        name for name, value in (
            ("DASH_OIDC_ISSUER", settings.oidc_issuer),
            ("DASH_OIDC_CLIENT_ID", settings.oidc_client_id),
        ) if not value
    ]
    if missing:
        return [f"DASH_AUTH_METHOD=oidc but {', '.join(missing)} is not set"]
    if not _issuer_transport_ok(settings.oidc_issuer):
        return [f"DASH_OIDC_ISSUER must be an https:// URL (got {settings.oidc_issuer!r}); "
                f"the id_token and the client secret both cross this connection"]
    if not settings.session_secret:
        return ["DASH_AUTH_METHOD=oidc needs DASH_SESSION_SECRET (it signs the "
                "state/nonce/PKCE cookie as well as the session)"]
    return []


def check_password(password: str) -> str | None:
    """None if this password may be SET, else why not. Set/change only."""
    if len(password or "") < MIN_PASSWORD_CHARS:
        return f"password must be at least {MIN_PASSWORD_CHARS} characters"
    return None


def warn_about_password_floor(settings: Settings) -> None:
    """One boot line about the floor, and about what it deliberately does NOT
    do.

    The plan asked for a boot warning listing accounts below the floor. The
    dashboard cannot produce that list and should not pretend to: it never
    stores a password and neither TrueNAS nor DSM will tell it how long an
    existing one is -- the only password it ever holds is the one an admin is
    typing into Admin > Users at that moment. So the floor is enforced where
    it can be (on set/change) and nobody is locked out of a fleet mid-shoot,
    which is the outcome that mattered."""
    if settings.session_secret:
        log.info(
            "password floor: %d characters, enforced when this dashboard SETS a password. "
            "Existing NAS passwords are not visible to it, so none are checked or "
            "invalidated -- re-set short ones from Admin > Users.",
            MIN_PASSWORD_CHARS,
        )


def describe_auth(settings: Settings) -> str:
    """The one line every boot logs, so "which auth is this box running" is
    answerable from the container log alone."""
    method = str(settings.auth_method or "").strip().lower() or "smb"
    mode = str(settings.cookie_secure or "auto").strip().lower()
    cookie = {"1": "Secure forced on", "0": "Secure forced off"}.get(
        mode, "Secure follows the request scheme")
    extra = ""
    if method == "oidc":
        extra = f", issuer={settings.oidc_issuer}, admin claim={settings.oidc_admin_claim or '-'}"
    return (f"auth method={method}{extra}; session cookie: {cookie}, HttpOnly, SameSite=Lax; "
            f"sessions revocable server-side (idle {int(settings.session_idle_seconds)}s, "
            f"absolute {int(settings.session_absolute_seconds)}s); "
            f"trusted proxies={settings.trusted_proxies or '-'}")


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
