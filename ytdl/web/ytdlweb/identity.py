"""Verifying X-CCSync-Identity: WHICH editor's companion is calling.

H5, docs/COMMERCIAL_READINESS.md item 7 (2026-08-17). The fleet routes used to
authorise on the shared report token plus a self-asserted name -- the header
was documented, in this very tree, as "a MISTAKE-PREVENTER, not an
authorisation boundary". One token is held by every companion in the fleet, so
any machine holding it could claim a job in another editor's name and then
complete it, poison its clips with failures, or take it away from the editor
who was downloading it. The token proves "a fleet machine"; it proves nothing
about WHICH.

So the header now carries the dashboard's own versioned identity TOKEN -- the
one reporter.py and selection.py already send on every report -- and this
module verifies its signature before the name is believed.

    v2.identity.<username base64url, unpadded>.<expires epoch>.<hmac sha256 hex>

TWO PROPERTIES ARE COPIED FROM ccsync_dashboard.auth AND MUST NOT DRIFT:

  - the PURPOSE claim. Only "identity" is accepted here, so a browser session
    cookie -- which is the same scheme with purpose "session" -- can never be
    replayed as a machine identity (the dashboard's SEC-1).
  - the v1 rejection. Pre-2026-07-25 tokens carried a raw username and no
    purpose; they are refused outright rather than half-parsed.

COPIED, NOT IMPORTED, for the reason token_ok in routes_fleet is copied: this
app must run with no dashboard package in reach (a standalone
`uvicorn ytdlweb.main:app`, and the whole test suite). ytdl/web/tests pins the
two implementations against each other where a dashboard checkout is present.

FAILS CLOSED. No secret configured, no header, a bad signature, an expired
token, a session cookie in the identity slot -- all of them are None, and the
fleet routes answer 403. The cost of that is the NAS worker downloading
everything, which is the designed fallback (docs/YTDL_LOCAL_DOWNLOAD.md §10).
"""
import base64
import hashlib
import hmac
import logging
import time

log = logging.getLogger(__name__)

TOKEN_VERSION = 'v2'
PURPOSE_IDENTITY = 'identity'

# The header FastAPI derives from a `x_ccsync_identity` parameter, spelled out
# here so the docs and the tests have one name to quote.
HEADER = 'X-CCSync-Identity'


def _sign(secret, payload):
    return hmac.new(str(secret).encode(), payload.encode(), hashlib.sha256).hexdigest()


def _b64u_decode(value):
    try:
        padded = value + '=' * (-len(value) % 4)
        return base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8')
    except Exception:                              # noqa: BLE001 - never raises
        return None


def read_identity_token(secret, token, now=None):
    """-> the username the token names, or None. NEVER raises.

    None for everything: missing secret, missing token, the wrong number of
    fields, a v1 token, a session-purpose token, a bad signature, an expired
    one, an undecodable username. The caller has exactly one thing to do with
    any of them (403), so distinguishing them here would only invite a branch
    that gets one of them wrong.
    """
    if not secret or not token:
        return None
    parts = str(token).split('.')
    if len(parts) != 5:
        return None
    version, purpose, user_b64, expires_s, signature = parts
    if version != TOKEN_VERSION or purpose != PURPOSE_IDENTITY:
        return None
    payload = f'{version}.{purpose}.{user_b64}.{expires_s}'
    try:
        if not hmac.compare_digest(signature, _sign(secret, payload)):
            return None
    except (TypeError, ValueError, UnicodeError):
        # compare_digest refuses a str with any character above U+007F, and
        # this value came off the wire. The same one-byte-of-junk 500 that
        # DASH-5 was, and that routes_fleet.token_ok already guards against.
        return None
    try:
        if int(expires_s) < (time.time() if now is None else now):
            return None
    except (TypeError, ValueError):
        return None
    return _b64u_decode(user_b64) or None


def make_identity_token(secret, username, ttl=30 * 24 * 3600, now=None):
    """Mint one. TESTS ONLY -- the dashboard's /api/v1/verify issues the real
    ones, and this app has no business handing out identities. It exists so the
    suite can prove the verifier accepts a genuine token and refuses everything
    else without importing the dashboard.
    """
    expires = int((time.time() if now is None else now) + ttl)
    user_b64 = base64.urlsafe_b64encode(str(username).encode('utf-8')).rstrip(b'=').decode('ascii')
    payload = f'{TOKEN_VERSION}.{PURPOSE_IDENTITY}.{user_b64}.{expires}'
    return f'{payload}.{_sign(secret, payload)}'
