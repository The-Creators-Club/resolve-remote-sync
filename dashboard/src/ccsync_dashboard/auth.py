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
import sqlite3
import threading
import time
import uuid
from typing import Sequence

from fastapi import Request, Response

from . import broll, db, local_users, sessions
from .settings import Settings

log = logging.getLogger("ccsync.dashboard.auth")

COOKIE_NAME = "ccsync_session"
SESSION_TTL_SECONDS = 7 * 24 * 3600
# A companion sign-in does NOT expire (CR-86, 2026-08-27). It used to hold
# for 30 days, and the day it lapsed the editor's companion stopped its
# sync lanes and vanished from the fleet grid behind one transient tray
# balloon -- an editor lost two days of syncing that way and nobody could
# see it from here. A machine identity is not a browser session: it is a
# claim about WHICH machine this is, it changes only when the editor signs
# in as somebody else, and there is no human at the keyboard to re-enter a
# password when it lapses. Kept as a TTL rather than a sentinel so the
# five-field wire shape is byte-for-byte what every deployed companion
# already parses (identity.parse_token) -- a build in the field accepts
# the new token with no upgrade. Browser SESSION cookies still expire
# (SESSION_TTL_SECONDS): there a human can just sign in again.
IDENTITY_TTL_SECONDS = 100 * 365 * 24 * 3600   # companion machine-identity token: never
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


# The sign-in methods verify_credentials below actually implements. Named
# once so check_boot_secrets refuses anything else at BOOT rather than at
# every login (bug-hunt-2026-09-03 dash-core-1); the values are compared
# against Settings.auth_method, which __post_init__ has stripped and
# lower-cased.
AUTH_METHODS = ("smb", "oidc", "local")


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
    if settings.auth_method == "local":
        # No NAS credential of any kind (WP C, docs/ZERO_TOUCH_PLAN.md §3.3,
        # 2026-08-17): the password check is a local scrypt compare against
        # local_users.py's own table, opened here rather than threaded in
        # because /login, /api/v1/verify and the login throttle all call this
        # with only a Settings in hand.
        conn = _open_local_conn(settings)
        if conn is None:
            return False
        try:
            return local_users.verify_password(conn, username, password)
        finally:
            conn.close()
    log.error("unknown DASH_AUTH_METHOD %r -- rejecting all logins", settings.auth_method)
    return False


def _open_local_conn(settings: Settings) -> sqlite3.Connection | None:
    """A short-lived connection for the local-accounts checks (verify_credentials,
    is_admin). There is no per-request connection to reuse at either call
    site: the login throttle path and /api/v1/verify both run before any
    route has opened one, and is_admin is called from ~15 places across
    api.py/ui.py that were never given one either (see is_admin's own note).
    Never raises -- a database that cannot be opened is a refusal, not a 500,
    on a path that is reachable by anyone with a guessed username."""
    try:
        return db.connect(settings.db_path)
    except Exception:  # noqa: BLE001
        log.exception("local accounts: could not open %s", settings.db_path)
        return None


# --------------------------------------------------------- login throttle
# The budgets themselves live in SQLite (sessions.SessionStore): an in-process
# dict lost every failure count on the container restart that each deploy
# performs, and counted usernames only -- so one host could spray one password
# across the whole fleet's usernames at full speed (COMMERCIAL_READINESS.md
# item 15, 2026-08-17). These wrappers are what the routes call; they take the
# Request because the IP budget needs the peer and the store lives on
# app.state.

# Peers we have already complained about for sending X-Forwarded-For without
# being in DASH_TRUSTED_PROXIES. Warn-once per process, like the collector's
# unknown-device warning: every request forever would be noise, and silence is
# what let the misconfiguration hide (trust-model-3, 2026-08-21).
_warned_forwarding_peers: set[str] = set()


def client_ip(request: Request | None) -> str:
    """The peer address, and deliberately NOT anything X-Forwarded-For says
    unless the peer is a proxy we configured. A spoofable IP budget is worse
    than none: it lets an attacker exhaust an innocent editor's budget."""
    if request is None:
        return ""
    settings = _settings_of(request)
    peer = getattr(getattr(request, "client", None), "host", "") or ""
    if not peer or not trusted_proxy(settings, peer):
        if peer and peer not in _warned_forwarding_peers and (
                request.headers.get("x-forwarded-for") or "").strip():
            # THE signature of the shipped TrueNAS shape: Tailscale Serve on
            # the docker host arrives from the bridge gateway (172.17.0.1),
            # which is not in the default trusted list, so every editor and
            # every companion shares one login-throttle bucket and the
            # sessions page shows one address for the whole fleet.
            _warned_forwarding_peers.add(peer)
            log.warning(
                "X-Forwarded-For from %s, which is not in DASH_TRUSTED_PROXIES (%s): "
                "the header is IGNORED, so every request through that proxy counts as "
                "one client. Add the proxy's address to DASH_TRUSTED_PROXIES.",
                peer, getattr(settings, "trusted_proxies", "?"))
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


def throttle_wait_phrase(seconds: float) -> str:
    """"a minute" / "6 minutes" / "about an hour" for a wait in seconds.

    DCORE-8 (usability sweep 2026-09-04): the backoff doubles from 60 s to an
    hour, and both sign-in routes threw the number away and answered "too
    many failed attempts; wait and retry". A person told to wait, with no
    idea whether it is one minute or sixty, retries -- which is the one thing
    that does not help, and on the IP budget it extends the lockout for
    everyone else behind the same address.

    Rounded UP to the whole minute: telling somebody 3 minutes when 3 min 40 s
    are left buys one more failed attempt and one more doubling."""
    remaining = max(0.0, float(seconds or 0.0))
    if remaining >= 45 * 60:
        return "about an hour"
    minutes = int(remaining // 60) + (1 if remaining % 60 else 0)
    if minutes <= 1:
        return "a minute"
    return f"{minutes} minutes"


def throttle_message(seconds: float) -> str:
    """The sentence every throttled sign-in surface says (DCORE-8)."""
    return f"Too many sign-in attempts. Try again in {throttle_wait_phrase(seconds)}."


def throttle_headers(seconds: float) -> dict[str, str]:
    """`Retry-After`, in whole seconds and never below 1: a client that reads
    the header must not be told to retry immediately while the budget still
    refuses it."""
    return {"Retry-After": str(max(1, int(float(seconds or 0.0) + 0.5)))}


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
    """Only the USERNAME budget is cleared by a successful sign-in.

    Clearing the IP row too let anyone who owns one valid account reset the
    spray budget at will: four failures against four usernames, log in as
    yourself, repeat (dash-core-4, 2026-08-21). The IP row is the second of
    the two budgets item 15 relies on, and it ages out on its own through
    LOGIN_FAILURE_WINDOW_SECONDS."""
    store = session_store(request)
    if store is not None:
        store.clear_failures(username)


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
    """Non-expiring signed token the companion stores to prove which editor's
    machine it is. Same HMAC scheme as the session cookie but signed with
    purpose="identity" -- read_session_cookie only accepts purpose="session"
    and read_identity_token only accepts purpose="identity", so this token
    can never be replayed as a browser session (see SEC-1).

    It does not expire -- see IDENTITY_TTL_SECONDS for why. Tokens minted
    before CR-86 still carry their old 30-day expiry and read_identity_token
    still rejects them once past it, so those editors sign in one last time.
    Revocation is unchanged, and a 30-day TTL was never much of one anyway.
    An identity token has no server-side row to revoke -- it proves WHICH
    machine, and a report also needs a report token, which is the credential
    disable/delete actually revoke (`_purge_user_credentials`, dash-core-3).
    Take an editor's access away by disabling or deleting the account, not by
    waiting a month."""
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


def _read_token_any(
    secret: str, previous: Sequence[str], token: str | None, purpose: str,
    now: float | None = None,
) -> tuple[str | None, str]:
    """(username, the secret that verified it), trying the CURRENT secret first
    and then each accept-only one from DASH_SESSION_SECRET_PREVIOUS.

    DASH-2 (resilience sweep 2026-08-28). Rotating DASH_SESSION_SECRET -- or
    restoring /data from a snapshot taken before <data>/secrets/
    dash_session_secret was generated, or moving the container to a host whose
    .env was regenerated -- 401s every companion in the fleet at once: the
    identity token is an HMAC over that secret and, since CR-86, never
    expires. The fleet grid then goes stale, and the halt / pushed-update /
    lane-B-resume / file-move command channel dies with it, until every editor
    clicks "Sign in..." at their own tray.

    The previous keys are ACCEPT-ONLY: nothing is ever minted with one, so the
    rotation still drains -- every editor who signs in again moves to the
    current key, and the caller counts who has not (see
    db.record_retired_key_identity), which is what makes the drain visible
    instead of a date the operator has to guess.
    """
    username = _read_token(secret, token, purpose, now=now)
    if username is not None:
        return username, secret
    for older in previous:
        if not older or older == secret:
            continue
        username = _read_token(older, token, purpose, now=now)
        if username is not None:
            return username, older
    return None, ""


def read_session_cookie(secret: str, cookie: str | None, now: float | None = None,
                        previous: Sequence[str] = ()) -> str | None:
    """Returns the username, or None for missing/expired/tampered cookies --
    or a cookie that is actually a valid IDENTITY token (see SEC-1)."""
    return _read_token_any(secret, previous, cookie, PURPOSE_SESSION, now=now)[0]


def read_identity_token(secret: str, token: str | None, now: float | None = None,
                        previous: Sequence[str] = ()) -> str | None:
    """Returns the username for a valid X-CCSync-Identity token, or None --
    including for a token that is actually a valid SESSION cookie."""
    return _read_token_any(secret, previous, token, PURPOSE_IDENTITY, now=now)[0]


def read_identity_token_ex(
    settings: Settings | None, token: str | None, now: float | None = None,
) -> tuple[str | None, bool]:
    """read_identity_token plus "and it was signed with a RETIRED key".

    The pair, because api_report has to do two different things with the two
    halves: accept the report, and count the machine as still owing its editor
    one "Sign in..." click (DASH-2)."""
    secret = getattr(settings, "session_secret", "") or ""
    username, used = _read_token_any(
        secret, previous_session_secrets(settings), token, PURPOSE_IDENTITY, now=now)
    return username, bool(username is not None and used != secret)


def previous_session_secrets(settings: Settings | None) -> tuple[str, ...]:
    return tuple(getattr(settings, "session_secrets_previous", ()) or ())


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
    # DASH-2: a browser session signed with the PREVIOUS secret is accepted
    # too, for the same reason a companion's identity is -- a rotation must
    # not sign every admin out in the middle of the incident that caused it.
    # The session id is still derived from the CURRENT secret, so the
    # server-side row is looked up (and revoked) under one key only.
    username, used = _read_token_any(
        secret, previous_session_secrets(settings), cookie, PURPOSE_SESSION)
    if username is None or not cookie:
        return None, None, False
    # The session id is derived with the secret that VERIFIED the cookie: the
    # server-side row was created under that key, and deriving it with the new
    # one would look up a row that cannot exist -- which is "no row", which is
    # a logout, which is the thing this accepts an old key to avoid.
    sid = session_id_for(used or secret, cookie)
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
    # DASH-2: not a refusal -- an accept-only key is a deliberate, temporary
    # state -- but it is announced at every boot, because a retired key left in
    # place for ever is a signing key nobody remembers is still trusted.
    previous = previous_session_secrets(settings)
    if previous:
        log.warning(
            "DASH_SESSION_SECRET_PREVIOUS carries %d retired key(s): companion "
            "identities and browser sessions signed with them are still ACCEPTED "
            "(nothing is minted with them). The fleet page counts the machines "
            "that have not signed in again -- remove this variable once that "
            "count reaches zero (docs/SECRETS.md).",
            len(previous))
        for older in previous:
            problem = _placeholder_or_weak("DASH_SESSION_SECRET_PREVIOUS", older)
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
    method = str(settings.auth_method or "").strip().lower()
    # bug-hunt-2026-09-03 dash-core-1: a method nobody implements used to boot
    # clean and then refuse every credential in verify_credentials, one ERROR
    # line per attempt, contradicted by the INFO line describe_auth wrote at
    # boot. Settings.__post_init__ now absorbs the case and whitespace
    # variants, so what reaches here is a genuine typo, and refusing to start
    # is the fail-closed answer this repo takes everywhere else.
    if method not in AUTH_METHODS:
        problems.append(
            f"DASH_AUTH_METHOD={settings.auth_method!r} is not a sign-in method this "
            f"dashboard has: it must be one of {', '.join(sorted(AUTH_METHODS))}. "
            "Left as it is, every password would be refused"
        )
    elif method == "oidc":
        problems.extend(check_oidc_settings(settings))
    elif method == "local":
        problems.extend(check_local_settings(settings))
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


def check_local_settings(settings: Settings) -> list[str]:
    """DASH_AUTH_METHOD=local needs nothing a fresh appliance doesn't already
    have -- no NAS credential, no issuer, not even DASH_ADMIN_USERS (the
    wizard's first-admin bootstrap, setup_api.setup_admin, is how the very
    first account gets in). The one thing it does need is the same secret
    every auth method needs to mint a session at all."""
    if not settings.session_secret:
        return ["DASH_AUTH_METHOD=local needs DASH_SESSION_SECRET (it signs the "
                "session cookie for local accounts the same as every other method)"]
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


def is_admin(settings: Settings, username: str | None,
            conn: sqlite3.Connection | None = None) -> bool:
    """DASH_ADMIN_USERS is checked FIRST and needs no database: it is the
    break-glass list on every auth method, smb/oidc/local alike, and must
    keep working even when the local-accounts table cannot be read.

    In DASH_AUTH_METHOD=local, a name NOT in that list may still be an admin
    -- role='admin' in the local `users` table (WP C, docs/ZERO_TOUCH_PLAN.md
    §3.3, 2026-08-17). `conn` is optional because most of this function's ~15
    call sites across api.py/ui.py were written for the settings-only smb/oidc
    world and were never handed one; when absent, a short-lived connection is
    opened here instead (see auth._open_local_conn) rather than pushing a
    conn parameter through every caller for a check that is a handful of
    milliseconds either way."""
    if not username:
        return False
    username = username.lower()
    if username in settings.admin_users:
        return True
    if str(getattr(settings, "auth_method", "") or "smb").strip().lower() != "local":
        return False
    if conn is not None:
        return local_users.is_local_admin(conn, username)
    opened = _open_local_conn(settings)
    if opened is None:
        return False
    try:
        return local_users.is_local_admin(opened, username)
    finally:
        opened.close()


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
