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
route: /api/ingest (drag-and-drop) is called by the SPA from a logged-in
browser and is fail-closed on its own account, and nothing about /music/* is
exempted from login_gate for a browser. The session IS the credential there.

THE DAY IT PREDICTED ARRIVED (2026-08-18, docs/MUSIC_INGEST_PLAN.md step 2),
and it took the OTHER half of the b-roll treatment rather than a token here:

  * `/music/api/fleet/ingest/...` is machine-to-machine -- an editor's
    companion, embedding a dropped album with the CLAP audio tower while
    nobody is at the browser -- so it is carved out of login_gate by
    `_music_fleet_re` in app.py, per suffix, and authenticates itself with a
    fleet token PLUS a signed identity (musicweb/fleet_auth.py). There is
    nothing for this module to make SAFER: unlike broll's ingest token, the
    music fleet routes have no "unconfigured = open" branch to reach -- they
    fail closed on their own. There is something only this module can make
    WORK, though (music-1, 2026-08-21): the fleet token a companion presents
    is not necessarily the shared DASH_REPORT_TOKEN. Since 2026-08-17 an
    editor's companion PREFERS the per-editor `cce1.<id>.<secret>` token an
    admin minted for them, and verifying one of those needs the dashboard's
    database -- which the music tree cannot see. So MusicGate resolves
    `X-CCSync-Token` here and stamps the answer as `X-CCSync-Fleet-Auth:
    shared|editor:<name>`, stripping any inbound copy first, and musicweb
    accepts that stamp only when it knows a login gate is wrapped around it.
  * `/music/api/ingest-batches*` is the SPA's half, and it makes per-user
    decisions with real consequences (whose batches these are, who may cancel
    another machine's work). So MusicGate now STAMPS the identity, exactly as
    BrollGate and YtdlGate do: every inbound `X-CCSync-User`/`X-CCSync-Admin`
    is stripped and the real pair -- decoded from the session cookie with the
    dashboard's own secret -- is appended when, and only when, that cookie is
    valid. Strip-then-append, never "append if absent": a logged-in editor
    sails through login_gate, and without the strip their own
    `fetch(url, {headers: {'X-CCSync-Admin': '1'}})` would be the whole
    authorisation story for "may I cancel every other machine's ingest".
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI

from . import api, auth, db
from .broll import _header_value, _session_cookie
from .settings import Settings

log = logging.getLogger(__name__)

MOUNT_PATH = "/music"

# The ingest PANEL's own routes (docs/MUSIC_INGEST_PLAN.md step 2). Note the
# absence of a trailing slash: the collection routes are `/api/ingest-batches`
# and `/api/ingest-batches/`, and a prefix with a slash on the end would miss
# the first of them -- so the create and list calls would reach the sub-app
# with no identity and be answered 401 for every editor.
BATCHES_PREFIX = "/api/ingest-batches"
# The headers the sub-app trusts, lowercase bytes because that is how they
# appear in an ASGI scope.
IDENTITY_HEADER = b"x-ccsync-user"
ADMIN_HEADER = b"x-ccsync-admin"
# What the FLEET routes trust about `X-CCSync-Token` (music-1, 2026-08-21).
# musicweb cannot verify a per-editor `cce1.<id>.<secret>` token -- that needs
# the dashboard's database, which the music tree cannot see -- so the mount
# resolves the credential and says so in one header the sub-app believes only
# when it knows a login gate is wrapped around it. Values: `shared`, or
# `editor:<name>`.
FLEET_AUTH_HEADER = b"x-ccsync-fleet-auth"
TOKEN_HEADER = b"x-ccsync-token"

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
    """ASGI wrapper around the music sub-app. Three jobs, all fail-closed.

    1. The sub-app's default interactive docs are 404'd.
    2. Every request is re-stamped with the session's identity: any inbound
       `X-CCSync-User`/`X-CCSync-Admin` is REMOVED, and the real pair --
       decoded from the ccsync_session cookie with the dashboard's own secret
       -- is appended when, and only when, that cookie is valid (2026-08-18,
       docs/MUSIC_INGEST_PLAN.md step 2). A request with no valid session
       reaches the sub-app carrying NO identity at all, so `/api/ingest-batches`
       answers its own 401 even in the impossible case that something let it
       past login_gate.

       The strip runs on EVERY request, not only the batch ones, for
       BrollGate's reason: scoping it to the paths that read the headers today
       would mean a route added upstream tomorrow inherits a forgeable
       identity, and the cost is two list comprehensions over ~8 headers.

    3. `X-CCSync-Fleet-Auth` gets the same strip-then-append treatment, for
       the companion's `X-CCSync-Token` (music-1, 2026-08-21). See
       `_fleet_stamp`: musicweb cannot verify a per-editor token, so the mount
       resolves it and the sub-app trusts the answer only when it knows it is
       login-gated -- i.e. only when this gate, which strips every inbound
       copy, is what put the header there.

    There is deliberately no token REFUSAL here, unlike BrollGate: the music
    FLEET routes fail closed on their own (musicweb/fleet_auth.py has no
    "unconfigured = open" branch to reach), and the panel routes are
    session-authorised. A token this gate could not resolve is simply not
    stamped, and the sub-app compares it against the shared secret as before.

    A plain ASGI wrapper rather than BaseHTTPMiddleware or add_middleware:
    nothing is re-wrapped or buffered on the way through, so /api/audio's
    Range/206 streaming responses are untouched, and no upstream global is
    mutated by importing us.
    """

    def __init__(self, app: Any, settings: Settings | None = None) -> None:
        self.app = app
        # Optional so an older caller (or a merge that has not caught up) gets
        # a mount with no identity stamping rather than a TypeError at boot --
        # the music mount fails ABSENT, never fatal, and the ingest panel
        # 401ing is a smaller failure than the dashboard not starting.
        self._settings = settings
        self._secret = getattr(settings, "session_secret", "") or ""

    def _fleet_stamp(self, headers: list[tuple[bytes, bytes]]) -> bytes | None:
        """What `X-CCSync-Token` on this request really is, or None.

        music-1, 2026-08-21. musicweb compared the header against the shared
        DASH_REPORT_TOKEN and nothing else, so the moment an admin minted an
        editor a per-editor `cce1.` token -- which the companion PREFERS over
        the shared one (identity.preferred_report_token, 2026-08-17) -- every
        one of that editor's music fleet calls was answered 403 and their
        dropped albums sat in `queued` forever. Only this side can tell: the
        per-editor token is verified against the dashboard's own database.

        Costs nothing on a browser request (no such header) and one regex on a
        shared-token one; a database connection is opened only for a token that
        already has the per-editor SHAPE, exactly as app.py's pre-body gate
        does. Any failure here is "no stamp", never "stamped anyway".
        """
        raw = _header_value_of(headers, TOKEN_HEADER)
        if not raw or self._settings is None:
            return None
        try:
            if db.looks_like_editor_report_token(raw):
                conn = db.connect(self._settings.db_path)
                try:
                    kind, editor = api.resolve_companion_credential(
                        self._settings, conn, raw)
                finally:
                    conn.close()
            else:
                kind, editor = api.resolve_companion_credential(
                    self._settings, None, raw)
        except Exception as e:  # noqa: BLE001 - an unopenable DB is not an auth pass
            log.warning("music fleet credential not resolved (%s: %s); the sub-app "
                        "falls back to its own shared-token comparison",
                        type(e).__name__, e)
            return None
        if kind == api.AUTH_SHARED:
            return b"shared"
        if kind == api.AUTH_EDITOR and editor:
            encoded = _header_value(f"editor:{editor}")
            if encoded is None:
                # Same fail-closed rule as the identity header: a name that
                # cannot survive a latin-1 round trip is withheld, not mangled.
                log.warning("music fleet stamp not minted for %r: the name cannot "
                            "survive a latin-1 header round trip", editor)
            return encoded
        return None

    def _identified_scope(self, scope: dict) -> dict:
        """A copy of `scope` whose headers carry our identity pair and no other.

        The original is left alone: it belongs to the server, and a mounted app
        is not the only thing that ever reads it.
        """
        headers = [(k, v) for k, v in scope.get("headers", ())
                   if k.lower() not in (IDENTITY_HEADER, ADMIN_HEADER,
                                        FLEET_AUTH_HEADER)]
        stamp = self._fleet_stamp(headers)
        if stamp is not None:
            headers.append((FLEET_AUTH_HEADER, stamp))
        username = (auth.read_session_cookie(self._secret, _session_cookie(headers))
                    if self._secret else None)
        if username:
            encoded = _header_value(username)
            if encoded is None:
                # Fail closed: no header at all, so the sub-app answers its own
                # 401 rather than authorising a name that is not this editor's.
                log.warning("music identity header not minted for %r: the name "
                            "cannot survive a latin-1 header round trip", username)
            else:
                headers.append((IDENTITY_HEADER, encoded))
                if self._settings is not None and auth.is_admin(self._settings, username):
                    headers.append((ADMIN_HEADER, b"1"))
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


def _header_value_of(headers: list[tuple[bytes, bytes]], name: bytes) -> str:
    """One raw ASGI header as a string, latin-1 the way Starlette decodes."""
    for k, v in headers:
        if k.lower() == name:
            return v.decode("latin-1", "replace").strip()
    return ""


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


def mount_music(app: FastAPI, settings: Settings | None = None) -> str:
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
    `settings` IS taken, since 2026-08-18: MusicGate mints the ingest
    panel's identity (X-CCSync-User/X-CCSync-Admin) from the session cookie
    with settings.session_secret, the way BrollGate and YtdlGate do. It
    stays optional so a caller that has not caught up gets a mount with no
    stamping rather than a dashboard that will not boot.
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

    gated = MusicGate(music_app, settings)

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
