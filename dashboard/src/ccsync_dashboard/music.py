"""Serve the music search UI from inside the dashboard, at /music.

The music app lives in this repo at music/web (folded in from the standalone
music-tagger on 2026-08-10). It is deployed exactly the way broll/web is: the
tree is shipped to <host-root>/music-web, the container mounts it read-only,
run.sh puts it on PYTHONPATH, and it is imported from here. See
music/web/DEPLOY.md for the installer side.

The one deliberate difference from broll: the package is `musicweb`, NOT `app`.
broll/web is imported as the top-level package `app` (a generic name it kept
when it was folded in), so a second package called `app` on the same PYTHONPATH
would collide in sys.modules and one of the two would silently win. Do not
"tidy" musicweb into app.

Editors get one URL and one login instead of a third service to find and sign
in to. Both apps are FastAPI, so this is a real in-process mount rather than a
proxy tier -- which matters more than it sounds: /api/audio/{id} serves the
source file with HTTP Range requests and answers a real 206 so the player can
seek, and putting a reverse proxy in front of it reintroduces exactly the "make
sure it passes Range headers through unmodified" problem that broll's DEPLOY.md
warns about. Mounted in-process, uvicorn serves those 206 responses directly.

The mount also inherits the dashboard's `login_gate` middleware for free, since
Starlette middleware wraps the whole ASGI app including mounts. The music app
therefore needs no auth code of its own -- see app.py's login_gate, where
/music/api/ is listed alongside /broll/api/ so the SPA's fetch() calls and the
<audio> element get a 401 JSON body instead of a 303 to an HTML login page,
neither of which they can follow.

EVERYTHING ABOUT THE IMPORT IS BEST-EFFORT. A missing or broken music checkout
must leave the fleet dashboard completely functional: it is what tells everyone
whether their footage is syncing, and it cannot be taken down by an optional
feature.

WHY THERE IS NO INGEST-TOKEN GATE HERE, unlike broll.py. broll's ingest routes
are an unauthenticated-by-design write path for the indexer -- not a browser, no
session -- so they had to be allowed PAST login_gate, and once past it the only
thing left between the tailnet and "repoint every clip's archive path" was a
token that the upstream app treats as optional ("not configured = dev mode =
open"). mount_broll therefore re-checks that token itself. musicweb has no such
route: its write paths (/api/ingest drag-and-drop, /api/resolve* -- reveal
moved to the companion's 8899 loopback, MUSIC-6 2026-08-14, it drove Explorer
on the SERVER here) are all called by the SPA from a logged-in browser, and
nothing about /music/* is
exempted from login_gate, and there is no upstream dev-mode branch to reach. The
session IS the credential. The day music grows a machine-to-machine ingest for
the base rig, it gets the full broll treatment -- a mandatory token validated in
create_app and re-checked in MusicGate -- and not before.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI

log = logging.getLogger(__name__)

MOUNT_PATH = "/music"

# mount_music's tri-state. "absent" and "degraded" are both "do not advertise
# it in the nav" (ui.py), but they are different operator problems: absent =
# the code is not there, degraded = the code is there and its data root is not
# usable, so every request would 500 with "unable to open database file".
MOUNTED = "mounted"
ABSENT = "absent"
DEGRADED = "degraded"

# Mounting a second FastAPI() brings its default interactive docs along, and
# they would be reachable by every editor with a session. The dashboard does
# not publish an API explorer; neither does either of its mounts.
BLOCKED_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})


class MusicGate:
    """ASGI wrapper around the music sub-app: 404 its interactive docs.

    A plain ASGI wrapper rather than BaseHTTPMiddleware or add_middleware:
    nothing is re-wrapped or buffered on the way through, so /api/audio's
    Range/206 streaming responses are untouched, and no upstream global is
    mutated by importing us. It is also the seam to hang a write-path check on
    if musicweb ever grows one (see the module docstring).
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "http":
            if any(p in BLOCKED_PATHS for p in sub_paths(scope)):
                await _json_response(send, 404, {"detail": "Not Found"})
                return
        await self.app(scope, receive, send)


def sub_paths(scope: dict) -> tuple[str, ...]:
    """Every plausible reading of "the path within the music app".

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


def _add_in_repo_music_web() -> bool:
    """Put this repo's music/web on sys.path so `import musicweb` can find it.

    Dev convenience ONLY, for running the dashboard straight out of a checkout
    where nothing has set PYTHONPATH. In the container this file lives under
    /app/src/ccsync_dashboard/, so parents[3] is /, the candidate does not
    exist, and this is inert -- the deployed import goes on coming off the
    PYTHONPATH run.sh sets, which is why the entry is APPENDED: an explicitly
    configured path must keep winning over a guess made from __file__.
    """
    candidate = Path(__file__).resolve().parents[3] / "music" / "web"
    if not (candidate / "musicweb" / "main.py").is_file():
        return False
    entry = str(candidate)
    if entry not in sys.path:
        sys.path.append(entry)
    log.info("importing the music app from the in-repo checkout at %s "
             "(nothing put it on PYTHONPATH)", entry)
    return True


def mount_music(app: FastAPI) -> str:
    """Mount the music app at /music. Returns MOUNTED / ABSENT / DEGRADED.

    The import is guarded and the failure is logged rather than raised, so a
    deployment whose music tree is missing, stale or mid-upgrade -- or one whose
    dashboard venv simply does not have numpy -- starts normally with the
    feature absent.

    Tri-state on purpose: a mount whose data root could not be prepared answers
    every request with a 500, and reporting that as success is how the nav ends
    up advertising a link to a broken page (the operator sees a green
    healthcheck and a feature that does not work).

    Takes no token, unlike mount_broll; see the module docstring for why.
    """
    try:
        try:
            from musicweb.main import app as music_app  # type: ignore[import-not-found]
        except ImportError:
            # A `musicweb` already in sys.modules is somebody's deliberate
            # choice (the tests' fake, most of all) and its failure is theirs
            # to own.
            if "musicweb" in sys.modules or not _add_in_repo_music_web():
                raise
            from musicweb.main import app as music_app  # type: ignore[import-not-found]
    except Exception as e:  # noqa: BLE001 - see module docstring
        log.warning("music UI not mounted (%s: %s); dashboard continues without it",
                    type(e).__name__, e)
        return ABSENT

    _declare_login_gated()

    gated = MusicGate(music_app)

    try:
        _init_music_storage()
    except Exception as e:  # noqa: BLE001
        # Mounted, but NOT advertised: /music is reachable for anyone who types
        # it (and logs the real error) while the nav stays quiet. Overwhelmingly
        # this is DATA_ROOT -- a read-only bind mount, or a directory the
        # container's uid cannot write, so sqlite answers "unable to open
        # database file" on every request.
        log.error("music data root could not be prepared (%s: %s); mounting it "
                  "DEGRADED -- every /music request will fail until DATA_ROOT is "
                  "writable by this container's uid, and the nav link is hidden",
                  type(e).__name__, e)
        app.mount(MOUNT_PATH, gated)
        return DEGRADED

    app.mount(MOUNT_PATH, gated)
    log.info("music UI mounted at %s", MOUNT_PATH)
    return MOUNTED


def _declare_login_gated() -> None:
    """Tell musicweb that app.py's login_gate is wrapped around it.

    musicweb's drag-and-drop ingest is fail-closed since 2026-08-17
    (COMMERCIAL_READINESS.md item 15): standalone it demands MUSIC_INGEST_TOKEN
    and refuses without one. Mounted here the browser is already past the
    dashboard's login and cannot send a header the SPA does not know, so this
    is the declaration that turns the session into the credential -- and it is
    a CALL from the mount rather than an env var, because a host that merely
    has a variable set is not the same as a process with the middleware
    actually wrapped around it.

    Best-effort, like everything else about this mount: an older music
    checkout has no such function and must not stop the dashboard booting.
    """
    try:
        from musicweb import config as music_config  # type: ignore[import-not-found]

        music_config.set_login_gated(True)
    except Exception as e:  # noqa: BLE001 - see module docstring
        log.warning("could not declare the music mount login-gated (%s: %s); its "
                    "ingest route will refuse unless MUSIC_INGEST_TOKEN is set",
                    type(e).__name__, e)


def _init_music_storage() -> None:
    """Open the database and apply schema.sql, the way a lifespan would.

    Starlette does NOT run a mounted sub-app's lifespan -- only the outermost
    app's. musicweb has no lifespan today (musicweb.db.con() applies the schema
    on first use, per-thread), so strictly nothing HAS to be replicated. This
    runs anyway, and that is the point: it is the probe that tells MOUNTED from
    DEGRADED. Without it a data root the container cannot open is reported as a
    working mount and the nav offers a link to a page that 500s on every
    request. It is also idempotent -- schema.sql is CREATE TABLE IF NOT EXISTS
    throughout -- and it deliberately does not set musicweb.db._schema_ready, so
    no upstream global is mutated by mounting.
    """
    from musicweb import config as music_config  # type: ignore[import-not-found]
    from musicweb import db as music_db  # type: ignore[import-not-found]

    music_config.DATA_ROOT.mkdir(parents=True, exist_ok=True)
    con = music_db.connect()
    try:
        music_db.init(con)
    finally:
        con.close()
