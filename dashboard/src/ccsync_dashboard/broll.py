"""Serve the b-roll search UI from inside the dashboard, at /broll.

The b-roll app lives in this repo at broll/web (folded in from the standalone
broll-platform repo on 2026-08-10). Nothing about the deployment changed with
it: install_dashboard_app.py still ships that tree to <host-root>/broll-web,
the container still mounts it read-only at /broll-app, run.sh still puts it on
PYTHONPATH, and it is still imported as top-level `app`.

Editors get one URL and one login instead of a second service to find and sign
in to. Both apps are FastAPI, so this is a real in-process mount rather than a
proxy tier -- which matters more than it sounds: the b-roll media routes serve
video with HTTP Range requests, and putting a reverse proxy in front of them
reintroduces exactly the "make sure it passes Range headers through unmodified"
problem that broll's own DEPLOY.md warns about. Mounted in-process, uvicorn
serves those 206 responses directly.

The mount also inherits the dashboard's `login_gate` middleware for free, since
Starlette middleware wraps the whole ASGI app including mounts. The b-roll app
therefore needs no auth code of its own -- see app.py's login_gate for the two
adjustments that makes necessary.

EVERYTHING ABOUT THE IMPORT IS BEST-EFFORT. A missing or broken b-roll checkout
must leave the fleet dashboard completely functional: it is what tells everyone
whether their footage is syncing, and it cannot be taken down by an optional
feature. What is NOT best-effort is the ingest credential: mount_broll refuses
to run without one (app.py checks it before we get here) and every request to
the sub-app's write routes is re-checked here, so the upstream "no token
configured = dev mode, ingest is open" branch can never be reached in this
deployment even for a logged-in editor.

AND SINCE 2026-08-18, NOR IS WHO THE CALLER IS. The b-roll ingest panel
(docs/BROLL_INGEST_PLAN.md §4.3) makes per-user decisions with real
consequences -- whose batches these are, and who may cancel another machine's
work -- and the sub-app learns the answer from headers this gate mints from the
session cookie. BrollGate therefore STRIPS every inbound `X-CCSync-User` and
`X-CCSync-Admin` before appending its own, exactly as YtdlGate does: the
headers must only ever be server-minted, or any logged-in editor could cancel
the whole fleet's ingests by adding one line to a fetch().
"""

from __future__ import annotations

import hmac
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI

from . import auth
from .settings import Settings

log = logging.getLogger(__name__)

MOUNT_PATH = "/broll"

# mount_broll's tri-state. "absent" and "degraded" are both "do not advertise
# it in the nav" (ui.py), but they are different operator problems: absent =
# the code is not there, degraded = the code is there and its data root is not
# usable, so every request would 500 with "unable to open database file".
MOUNTED = "mounted"
ABSENT = "absent"
DEGRADED = "degraded"

# Paths INSIDE the mounted sub-app. Starlette has changed how it hands a mount
# its path more than once (it used to rewrite scope["path"] to the remainder;
# current versions leave the full path and set root_path to the mount prefix),
# so the gate below matches on BOTH forms rather than pinning a version. Getting
# this wrong silently unguards the ingest routes, which is exactly the class of
# bug this module exists to prevent.
INGEST_PREFIX = "/api/ingest/"
# The ingest PANEL's own routes (docs/BROLL_INGEST_PLAN.md §4.3). Note the
# absence of a trailing slash: the collection routes are `/api/ingest-batches`
# and `/api/ingest-batches/`, and a prefix with a slash on the end would miss
# the first of them -- so the create and list calls would reach the sub-app
# with no identity and be answered 401 for every editor.
#
# It does NOT overlap INGEST_PREFIX above ("/api/ingest/" vs
# "/api/ingest-batches"), which is deliberate and slightly fragile: these
# routes are session-authorised, and demanding the indexer's X-Ingest-Token on
# them would lock every editor out of their own drops. Renaming either prefix
# means re-reading both constants.
BATCHES_PREFIX = "/api/ingest-batches"
# The two headers the sub-app trusts, lowercase bytes because that is how they
# appear in an ASGI scope.
IDENTITY_HEADER = b"x-ccsync-user"
ADMIN_HEADER = b"x-ccsync-admin"
# Mounting a second FastAPI() brings its default interactive docs along, and
# they would be reachable by every editor with a session. The dashboard does
# not publish an API explorer; neither does its mount.
BLOCKED_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})

# --- ingest-token policy ------------------------------------------------------
# The ingest routes are an unauthenticated-by-design write path for the indexer
# (it is not a browser and has no session). That makes this token the only
# thing between the public internet-facing-ish tailnet and "repoint every clip's
# archive path". It gets treated like a credential, not like a setting.
MIN_INGEST_TOKEN_CHARS = 24
_PLACEHOLDER_TOKENS = frozenset({
    "replace_me", "replaceme", "replace-me", "change_me", "changeme", "change-me",
    "changethis", "todo", "tbd", "secret", "password", "token", "test", "example",
    "your-token-here", "xxx", "none", "null",
})


def check_ingest_token(token: str) -> str | None:
    """None if `token` is fit to guard the ingest write path, else the reason.

    Deliberately strict, and deliberately NOT "empty means open": an empty
    BROLL_INGEST_TOKEN used to mean the b-roll app's own guard fell back to
    dev mode, which made ingest reachable with nothing but a session cookie.
    Callers refuse to start rather than mount with a token that fails here.
    """
    token = (token or "").strip()
    if not token:
        return "is not set"
    if token.lower() in _PLACEHOLDER_TOKENS:
        return f"is the placeholder {token!r} (a value that is in the public repo)"
    if len(token) < MIN_INGEST_TOKEN_CHARS:
        return (f"is only {len(token)} characters; at least {MIN_INGEST_TOKEN_CHARS} "
                f"are required")
    if len(set(token)) < 8:
        return "has too little variety to be a random secret"
    return None


class BrollGate:
    """ASGI wrapper around the b-roll sub-app. Three jobs, all fail-closed.

    1. `/api/ingest/*` demands a matching X-Ingest-Token, ALWAYS. The b-roll
       app's own verify_ingest_token opens ingest to everyone when no token is
       configured (a dev convenience in its own repo); mounted here that would
       be an unauthenticated write path on the origin the whole fleet trusts,
       and even WITH a token configured upstream, a logged-in editor sails past
       the dashboard's login_gate and would meet nothing else. This check is
       ours, it does not consult the environment, and it does not depend on any
       upstream behaviour.
    2. The sub-app's default interactive docs are 404'd.
    3. `/api/ingest-batches*` is re-stamped with the session's identity: any
       inbound `X-CCSync-User`/`X-CCSync-Admin` is REMOVED, and the real pair
       -- decoded from the ccsync_session cookie with the dashboard's own
       secret -- is appended when, and only when, that cookie is valid
       (2026-08-18, docs/BROLL_INGEST_PLAN.md §4.3). A request with no valid
       session reaches the sub-app carrying NO identity at all, so it answers
       its own 401 even in the impossible case that something let it past
       login_gate.

       Strip-then-append rather than "append if absent", for YtdlGate's reason:
       an editor who is genuinely logged in sails through login_gate, and
       without the strip their own `fetch(url, {headers: {'X-CCSync-Admin':
       '1'}})` would be the whole authorisation story for "may I see and cancel
       every other machine's ingest".

       The strip runs on EVERY request, not only the batch ones. Scoping it to
       the paths that read the headers today would mean a route added upstream
       tomorrow inherits a forgeable identity, and the cost is two list
       comprehensions over ~8 headers.

    A plain ASGI wrapper rather than BaseHTTPMiddleware or add_middleware:
    nothing is re-wrapped or buffered on the way through, so the media routes'
    Range/206 streaming responses are untouched, and no upstream global is
    mutated by importing us.
    """

    def __init__(self, app: Any, token: str, settings: Settings | None = None) -> None:
        self.app = app
        self._token = token or ""
        # Optional so an older caller (or a merge that has not caught up) gets
        # a mount with no identity stamping rather than a TypeError at boot --
        # the b-roll mount fails ABSENT, never fatal, and the ingest panel
        # 401ing is a smaller failure than the dashboard not starting.
        self._settings = settings
        self._secret = getattr(settings, "session_secret", "") or ""

    def _identified_scope(self, scope: dict) -> dict:
        """A copy of `scope` whose headers carry our identity pair and no other.

        The original is left alone: it belongs to the server, and a mounted app
        is not the only thing that ever reads it.
        """
        headers = [(k, v) for k, v in scope.get("headers", ())
                   if k.lower() not in (IDENTITY_HEADER, ADMIN_HEADER)]
        username = (auth.read_session_cookie(self._secret, _session_cookie(headers))
                    if self._secret else None)
        if username:
            encoded = _header_value(username)
            if encoded is None:
                # Fail closed: no header at all, so the sub-app answers its own
                # 401 rather than authorising a name that is not this editor's.
                log.warning("b-roll identity header not minted for %r: the name "
                            "cannot survive a latin-1 header round trip", username)
            else:
                headers.append((IDENTITY_HEADER, encoded))
                if self._settings is not None and auth.is_admin(self._settings, username):
                    headers.append((ADMIN_HEADER, b"1"))
        new_scope = dict(scope)
        new_scope["headers"] = headers
        return new_scope

    def _token_ok(self, scope: dict) -> bool:
        if not self._token:
            return False
        # Compared as raw header BYTES, never as a decoded str:
        # hmac.compare_digest raises TypeError on a str with any character
        # above U+007F, so one non-ASCII byte in X-Ingest-Token answered a
        # refusal with a 500 and a traceback (KNOWN_BUGS DASH-5, 2026-08-11).
        supplied = b""
        for key, value in scope.get("headers", ()):
            if key == b"x-ingest-token":
                supplied = value
                break
        return hmac.compare_digest(self._token.encode("utf-8", "surrogateescape"), supplied)

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "http":
            paths = sub_paths(scope)
            if any(p in BLOCKED_PATHS for p in paths):
                await _json_response(send, 404, {"detail": "Not Found"})
                return
            if any(p.startswith(INGEST_PREFIX) for p in paths) and not self._token_ok(scope):
                log.warning("b-roll ingest refused (%s): missing or invalid X-Ingest-Token",
                            scope.get("path", ""))
                await _json_response(
                    send, 401, {"detail": "missing or invalid X-Ingest-Token"})
                return
            scope = self._identified_scope(scope)
        await self.app(scope, receive, send)


def _header_value(username: str) -> bytes | None:
    """The identity header's bytes, or None if this name cannot be carried.

    LATIN-1, not UTF-8 (YTDL-29, 2026-08-11, and the same rule ytdl.py's copy
    of this function carries). Starlette decodes header bytes as latin-1, so a
    UTF-8-encoded `josé` reached the sub-app as `josÃ©` -- deterministically,
    so that editor's own batches matched nothing. Encoding the way the reader
    decodes covers every name up to U+00FF; beyond that (a CJK username) there
    is no lossless answer and a lossy one could collide two editors into one
    identity, so the header is withheld and the sub-app 401s -- broken, but
    loudly and for one person, rather than quietly authorising the wrong name.
    """
    try:
        return username.encode("latin-1")
    except UnicodeEncodeError:
        return None


def _session_cookie(headers: list[tuple[bytes, bytes]]) -> str | None:
    """The ccsync_session value out of raw ASGI headers, or None.

    Hand-parsed rather than via Starlette's Request: building one here would
    mean constructing a request object (and its receive channel) for every
    media byte-range and every poll. Split on the FIRST "=" only -- the token
    is `v2.session.<b64url>.<expires>.<hmac>` and base64url padding is
    stripped, but a cookie parser that loses everything after a second "=" is a
    bug waiting for the day that changes.
    """
    for key, value in headers:
        if key.lower() != b"cookie":
            continue
        for part in value.decode("latin-1").split(";"):
            name, sep, raw = part.strip().partition("=")
            if sep and name == auth.COOKIE_NAME:
                return raw.strip()
    return None


def sub_paths(scope: dict) -> tuple[str, ...]:
    """Every plausible reading of "the path within the b-roll app".

    Both are checked and the strictest answer wins, because the alternative is
    a version-dependent hole: under a Starlette that strips the mount prefix
    the raw path is already the sub-path, and under one that does not, it still
    carries /broll. Cheap; two string comparisons per request.
    """
    path = scope.get("path", "")
    candidates = [path]
    root = scope.get("root_path", "")
    if root and path.startswith(root):
        candidates.append(path[len(root):] or "/")
    if path.startswith(MOUNT_PATH):
        candidates.append(path[len(MOUNT_PATH):] or "/")
    return tuple(dict.fromkeys(candidates))


async def _json_response(send: Callable, status: int, body: dict) -> None:
    payload = json.dumps(body).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode())],
    })
    await send({"type": "http.response.body", "body": payload})


def _add_in_repo_broll_web() -> bool:
    """Put this repo's broll/web on sys.path so `import app` can find it.

    Dev convenience ONLY, for running the dashboard straight out of a checkout
    where nothing has set PYTHONPATH. In the container this file lives under
    /app/src/ccsync_dashboard/, so parents[3] is /, the candidate does not
    exist, and this is inert -- the deployed import goes on coming off the
    PYTHONPATH run.sh sets, which is why the entry is APPENDED: an explicitly
    configured path must keep winning over a guess made from __file__.
    """
    candidate = Path(__file__).resolve().parents[3] / "broll" / "web"
    if not (candidate / "app" / "main.py").is_file():
        return False
    entry = str(candidate)
    if entry not in sys.path:
        sys.path.append(entry)
    log.info("importing the b-roll app from the in-repo checkout at %s "
             "(nothing put it on PYTHONPATH)", entry)
    return True


def mount_broll(app: FastAPI, ingest_token: str,
                settings: Settings | None = None) -> str:
    """Mount the b-roll app at /broll. Returns MOUNTED / ABSENT / DEGRADED.

    `settings` is what BrollGate mints the ingest panel's identity from (the
    session secret, and whether that editor is an admin). It defaults to None
    so a caller that has not been updated still gets a working search UI with
    the ingest panel 401ing, rather than a dashboard that will not boot -- the
    b-roll mount fails absent, never fatal.

    The import is guarded and the failure is logged rather than raised, so a
    deployment whose /broll-app volume is missing, stale or mid-upgrade starts
    normally with the feature simply absent.

    Tri-state on purpose: a mount whose data root could not be prepared answers
    every request with a 500, and reporting that as success is how the nav ends
    up advertising a link to a broken page (the operator sees a green
    healthcheck and a feature that does not work).
    """
    if check_ingest_token(ingest_token) is not None:
        # app.py refuses to build the app at all in this case; this is the
        # belt to that brace, so no other caller can mount without a token.
        log.error("b-roll UI NOT mounted: no usable BROLL_INGEST_TOKEN")
        return ABSENT
    try:
        # The b-roll package is imported as top-level `app` -- a generic name it
        # kept when broll/web was folded into this repo. Safe here only because
        # the container puts /broll-app on PYTHONPATH explicitly and nothing
        # else exports `app`. Renaming it to `broll_web` would be tidier;
        # noted, not done.
        try:
            from app.main import app as broll_app  # type: ignore[import-not-found]
        except ImportError:
            # An `app` already in sys.modules is somebody's deliberate choice
            # (the tests' fake, most of all) and its failure is theirs to own.
            if "app" in sys.modules or not _add_in_repo_broll_web():
                raise
            from app.main import app as broll_app  # type: ignore[import-not-found]
    except Exception as e:  # noqa: BLE001 - see module docstring
        log.warning("b-roll UI not mounted (%s: %s); dashboard continues without it",
                    type(e).__name__, e)
        return ABSENT

    gated = BrollGate(broll_app, ingest_token, settings)

    try:
        _init_broll_storage()
    except Exception as e:  # noqa: BLE001
        # Mounted, but NOT advertised: /broll is reachable for anyone who types
        # it (and logs the real error) while the nav stays quiet. Overwhelmingly
        # this is the bind mount's ownership -- the container is uid 3000 and
        # the archive root was created by something else.
        log.error("b-roll data root could not be prepared (%s: %s); mounting it "
                  "DEGRADED -- every /broll request will fail until the data root "
                  "is writable by this container's uid, and the nav link is hidden",
                  type(e).__name__, e)
        app.mount(MOUNT_PATH, gated)
        return DEGRADED

    app.mount(MOUNT_PATH, gated)
    log.info("b-roll UI mounted at %s", MOUNT_PATH)
    return MOUNTED


def _init_broll_storage() -> None:
    """Run what the b-roll app's own lifespan would have run.

    Starlette does NOT run a mounted sub-app's lifespan -- only the outermost
    app's. Without this the data directories are never created and the SQLite
    schema is never applied, so the first request fails against a database that
    does not exist. This is the single most surprising part of mounting, and
    the reason it is a named function rather than an inline call.
    """
    from app import config as broll_config  # type: ignore[import-not-found]
    from app.db import ensure_schema  # type: ignore[import-not-found]

    for d in (
        broll_config.get_data_root(),
        broll_config.get_proxies_dir(),
        broll_config.get_sprites_dir(),
        broll_config.get_posters_dir(),
        broll_config.get_sheets_dir(),
    ):
        d.mkdir(parents=True, exist_ok=True)
    ensure_schema(broll_config.get_db_path())
