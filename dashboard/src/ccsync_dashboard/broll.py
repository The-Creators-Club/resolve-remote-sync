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
"""

from __future__ import annotations

import hmac
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI

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
    """ASGI wrapper around the b-roll sub-app. Two jobs, both fail-closed.

    1. `/api/ingest/*` demands a matching X-Ingest-Token, ALWAYS. The b-roll
       app's own verify_ingest_token opens ingest to everyone when no token is
       configured (a dev convenience in its own repo); mounted here that would
       be an unauthenticated write path on the origin the whole fleet trusts,
       and even WITH a token configured upstream, a logged-in editor sails past
       the dashboard's login_gate and would meet nothing else. This check is
       ours, it does not consult the environment, and it does not depend on any
       upstream behaviour.
    2. The sub-app's default interactive docs are 404'd.

    A plain ASGI wrapper rather than BaseHTTPMiddleware or add_middleware:
    nothing is re-wrapped or buffered on the way through, so the media routes'
    Range/206 streaming responses are untouched, and no upstream global is
    mutated by importing us.
    """

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self._token = token or ""

    def _token_ok(self, scope: dict) -> bool:
        if not self._token:
            return False
        supplied = ""
        for key, value in scope.get("headers", ()):
            if key == b"x-ingest-token":
                supplied = value.decode("latin-1")
                break
        return hmac.compare_digest(self._token, supplied)

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
        await self.app(scope, receive, send)


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


def mount_broll(app: FastAPI, ingest_token: str) -> str:
    """Mount the b-roll app at /broll. Returns MOUNTED / ABSENT / DEGRADED.

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

    gated = BrollGate(broll_app, ingest_token)

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
