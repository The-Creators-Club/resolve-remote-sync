"""Serve the YouTube downloader UI from inside the dashboard, at /ytdl.

The app lives in this repo at ytdl/web and is deployed exactly the way
broll/web and music/web are: the tree is shipped to <host-root>/ytdl-web, the
container mounts it read-only at /ytdl-app, run.sh puts it on PYTHONPATH, and
it is imported from here. See ytdl/web/DEPLOY.md for the installer side.

The package is `ytdlweb`, NOT `app` and NOT `ytdl` -- same rule as musicweb.
broll/web is imported as the top-level package `app`, so a second package of
that name on the same PYTHONPATH would collide in sys.modules and one of the
two would silently win; and `ytdl` would collide with THIS module's name in a
checkout. Do not "tidy" it.

Editors get one URL and one login instead of a fourth service to find and sign
in to. Both apps are FastAPI, so this is a real in-process mount rather than a
proxy tier: the SPA polls api/jobs/{id} every 1.5s while a pipeline runs, and
every one of those polls would otherwise cross a proxy hop for nothing.

The mount inherits the dashboard's `login_gate` middleware for free, since
Starlette middleware wraps the whole ASGI app including mounts -- see app.py,
where /ytdl/api/ is listed alongside /broll/api/ and /music/api/ so the SPA's
fetch() calls get a 401 JSON body instead of a 303 to an HTML login page,
which they cannot follow.

EVERYTHING ABOUT THE IMPORT IS BEST-EFFORT. A missing or broken ytdl checkout
must leave the fleet dashboard completely functional: it is what tells everyone
whether their footage is syncing, and it cannot be taken down by an optional
feature.

WHAT IS NOT BEST-EFFORT IS WHO THE CALLER IS. Unlike music, this sub-app makes
per-user decisions with real consequences -- which projects a job may download
into (the caller's ticked selections), and whose jobs a manifest may be read
from -- and it learns the answer from a header this gate mints. YtdlGate
therefore STRIPS every inbound X-CCSync-User before appending its own: the
header must only ever be server-minted, or any logged-in editor could download
into another editor's projects by adding one line to a fetch(). The session
cookie is the credential; the header is only its transcription for a sub-app
that has no session code of its own.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI

from . import auth
from .settings import Settings

log = logging.getLogger(__name__)

MOUNT_PATH = "/ytdl"

# mount_ytdl's tri-state. "absent" and "degraded" are both "do not advertise
# it in the nav" (ui.py), but they are different operator problems: absent =
# the code is not there, degraded = the code is there and its data root is not
# usable, so every request would 500 with "unable to open database file".
MOUNTED = "mounted"
ABSENT = "absent"
DEGRADED = "degraded"

# Mounting a third FastAPI() brings its default interactive docs along, and
# they would be reachable by every editor with a session. The dashboard does
# not publish an API explorer; neither does any of its mounts.
BLOCKED_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})

# The one header the sub-app trusts (ytdlweb.session.current_user). Lowercase
# bytes because that is how it appears in an ASGI scope -- HTTP/2 requires
# lowercase field names and uvicorn lowercases HTTP/1.1's for us, but the
# comparison is done on our own lowercased copy either way.
IDENTITY_HEADER = b"x-ccsync-user"


class YtdlGate:
    """ASGI wrapper around the ytdl sub-app. Two jobs, both fail-closed.

    1. The sub-app's default interactive docs are 404'd (as for /broll, /music).
    2. Every request is re-stamped with the session's identity: any inbound
       X-CCSync-User is REMOVED, and the real one -- decoded from the
       ccsync_session cookie with the dashboard's own secret -- is appended
       when, and only when, that cookie is valid. A request with no valid
       session reaches the sub-app carrying NO identity header at all, so
       ytdlweb answers its own 401 even in the impossible case that something
       let it past login_gate.

       Strip-then-append rather than "append if absent": an editor who is
       genuinely logged in sails through login_gate, and without the strip
       their own `fetch(url, {headers: {'X-CCSync-User': 'someone-else'}})`
       would be the whole authorisation story for "which projects may I
       download into".

    A plain ASGI wrapper rather than BaseHTTPMiddleware or add_middleware:
    nothing is re-wrapped or buffered on the way through (the manifest
    endpoints are ordinary JSON, but the poll endpoint is called every 1.5s
    per open tab and pays for any per-request machinery), and no upstream
    global is mutated by importing us.
    """

    def __init__(self, app: Any, session_secret: str) -> None:
        self.app = app
        self._secret = session_secret or ""

    def _identified_scope(self, scope: dict) -> dict:
        """A copy of `scope` whose headers carry our identity header and no
        other. The original is left alone: it belongs to the server, and a
        mounted app is not the only thing that ever reads it."""
        headers = [(k, v) for k, v in scope.get("headers", ())
                   if k.lower() != IDENTITY_HEADER]
        username = auth.read_session_cookie(self._secret, _session_cookie(headers))
        if username:
            encoded = _header_value(username)
            if encoded is None:
                # Fail closed: no header at all, so the sub-app answers its own
                # 401 rather than authorising a name that is not this editor's.
                log.warning("ytdl identity header not minted for %r: the name "
                            "cannot survive a latin-1 header round trip",
                            username)
            else:
                headers.append((IDENTITY_HEADER, encoded))
        new_scope = dict(scope)
        new_scope["headers"] = headers
        return new_scope

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "http":
            if any(p in BLOCKED_PATHS for p in sub_paths(scope)):
                await _json_response(send, 404, {"detail": "Not Found"})
                return
            scope = self._identified_scope(scope)
        await self.app(scope, receive, send)


def _header_value(username: str) -> bytes | None:
    """The identity header's bytes, or None if this name cannot be carried.

    LATIN-1, not UTF-8 (YTDL-29, 2026-08-11). Starlette decodes header bytes as
    latin-1, so a UTF-8-encoded `josé` reached the sub-app as `josÃ©` --
    deterministically, so that editor's ticked projects matched nothing and
    /ytdl was unusable for them. Encoding the way the reader decodes covers
    every name up to U+00FF; beyond that (a CJK username) there is no lossless
    answer and a lossy one could collide two editors into one identity, so the
    header is withheld and the sub-app 401s -- broken, but loudly and for one
    person, rather than quietly authorising the wrong name.
    """
    try:
        return username.encode("latin-1")
    except UnicodeEncodeError:
        return None


def _session_cookie(headers: list[tuple[bytes, bytes]]) -> str | None:
    """The ccsync_session value out of raw ASGI headers, or None.

    Hand-parsed rather than via Starlette's Request: building one here would
    mean constructing a request object (and its receive channel) for every
    poll, and this needs exactly one cookie by name. Split on the FIRST "="
    only -- the token is `v2.session.<b64url>.<expires>.<hmac>` and base64url
    padding is stripped, but a cookie parser that loses everything after a
    second "=" is a bug waiting for the day that changes.
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
    """Every plausible reading of "the path within the ytdl app".

    Starlette has changed how it hands a mount its path more than once (it used
    to rewrite scope["path"] to the remainder; current versions leave the full
    path and set root_path to the mount prefix), so both are checked and the
    strictest answer wins rather than pinning a version. Cheap; two string
    comparisons per request.
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


def _add_in_repo_ytdl_web() -> bool:
    """Put this repo's ytdl/web on sys.path so `import ytdlweb` can find it.

    Dev convenience ONLY, for running the dashboard straight out of a checkout
    where nothing has set PYTHONPATH. In the container this file lives under
    /app/src/ccsync_dashboard/, so parents[3] is /, the candidate does not
    exist, and this is inert -- the deployed import goes on coming off the
    PYTHONPATH run.sh sets, which is why the entry is APPENDED: an explicitly
    configured path must keep winning over a guess made from __file__.
    """
    candidate = Path(__file__).resolve().parents[3] / "ytdl" / "web"
    if not (candidate / "ytdlweb" / "main.py").is_file():
        return False
    entry = str(candidate)
    if entry not in sys.path:
        sys.path.append(entry)
    log.info("importing the ytdl app from the in-repo checkout at %s "
             "(nothing put it on PYTHONPATH)", entry)
    return True


def mount_ytdl(app: FastAPI, settings: Settings) -> str:
    """Mount the ytdl app at /ytdl. Returns MOUNTED / ABSENT / DEGRADED.

    The import is guarded and the failure is logged rather than raised, so a
    deployment whose ytdl tree is missing, stale or mid-upgrade -- or one whose
    dashboard venv simply does not have yt-dlp -- starts normally with the
    feature absent.

    Tri-state on purpose: a mount whose data root could not be prepared answers
    every request with a 500, and reporting that as success is how the nav ends
    up advertising a link to a broken page (the operator sees a green
    healthcheck and a feature that does not work).

    Takes `settings` rather than a token, unlike mount_broll: what it needs is
    the session secret, because this gate mints the identity the sub-app
    authorises on (see YtdlGate). A blank secret is not refused here -- the
    dashboard already cannot log anyone in without one, so every request would
    arrive with no session at all and the sub-app would 401 by itself.
    """
    try:
        try:
            from ytdlweb.main import app as ytdl_app  # type: ignore[import-not-found]
        except ImportError:
            # A `ytdlweb` already in sys.modules is somebody's deliberate
            # choice (the tests' fake, most of all) and its failure is theirs
            # to own.
            if "ytdlweb" in sys.modules or not _add_in_repo_ytdl_web():
                raise
            from ytdlweb.main import app as ytdl_app  # type: ignore[import-not-found]
    except Exception as e:  # noqa: BLE001 - see module docstring
        log.warning("ytdl UI not mounted (%s: %s); dashboard continues without it",
                    type(e).__name__, e)
        return ABSENT

    gated = YtdlGate(ytdl_app, settings.session_secret)

    try:
        _init_ytdl_storage()
    except Exception as e:  # noqa: BLE001
        # Mounted, but NOT advertised: /ytdl is reachable for anyone who types
        # it (and logs the real error) while the nav stays quiet. Overwhelmingly
        # this is YTDL_DATA_ROOT -- a read-only bind mount, or a directory the
        # container's uid cannot write, so sqlite answers "unable to open
        # database file" on every request.
        log.error("ytdl data root could not be prepared (%s: %s); mounting it "
                  "DEGRADED -- every /ytdl request will fail until YTDL_DATA_ROOT "
                  "is writable by this container's uid, and the nav link is hidden",
                  type(e).__name__, e)
        app.mount(MOUNT_PATH, gated)
        return DEGRADED

    app.mount(MOUNT_PATH, gated)
    log.info("ytdl UI mounted at %s", MOUNT_PATH)
    return MOUNTED


def _init_ytdl_storage() -> None:
    """Run what the ytdl app's own lifespan would have run.

    STARLETTE DOES NOT RUN A MOUNTED SUB-APP'S LIFESPAN -- only the outermost
    app's. That is not a detail here the way it is for music (whose db applies
    its schema lazily on first use): ytdlweb's pipeline runs on a singleton
    daemon thread started by ensure_started(), and without this call there is
    no thread, so every job sits in `queued` forever while the UI cheerfully
    polls it. Mounted, the lifespan never fires; this IS the lifespan.

    It doubles as the probe that tells MOUNTED from DEGRADED. Without it a data
    root the container cannot open is reported as a working mount and the nav
    offers a link to a page that 500s on every request. Idempotent throughout
    -- the schema is CREATE TABLE IF NOT EXISTS and ensure_started() is a
    no-op once the thread is alive -- and it opens and closes its own
    connection rather than priming any upstream global.
    """
    from ytdlweb import config as ytdl_config  # type: ignore[import-not-found]
    from ytdlweb import db as ytdl_db  # type: ignore[import-not-found]
    from ytdlweb import worker as ytdl_worker  # type: ignore[import-not-found]

    # The sub-app's own config is the source of truth (it resolves
    # YTDL_DATA_ROOT at import time, as musicweb.config does); the environment
    # is the fallback so a rename upstream degrades the mount's tidiness, not
    # the mount.
    root = getattr(ytdl_config, "DATA_ROOT", "") or os.environ.get(
        "YTDL_DATA_ROOT", "./data")
    Path(root).mkdir(parents=True, exist_ok=True)

    con = ytdl_db.connect()
    try:
        ytdl_db.init(con)
    finally:
        con.close()

    # After the schema, never before: the worker's first act is to recover
    # jobs left mid-pipeline by a restart, and it cannot query tables that do
    # not exist yet.
    ytdl_worker.ensure_started()
