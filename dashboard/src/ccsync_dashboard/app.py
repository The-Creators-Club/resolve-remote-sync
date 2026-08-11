"""FastAPI app factory and uvicorn entry point.

The collector runs as an in-process daemon thread started by the lifespan
handler -- one container, one process, one worker (the SQLite concurrency
model depends on workers=1; see db.py).
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import ClientDisconnect

from . import api, auth, broll, db, music, ui, ytdl
from .collector import Collector
from .settings import Settings

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"

# Paths reachable without a session. Everything else redirects to /login
# (pages) or 401s (JSON). The companion's token-authed endpoints and the
# login/health endpoints stay open.
_OPEN_EXACT = {
    "/login", "/api/v1/login", "/api/v1/logout", "/api/v1/me",
    "/api/v1/health", "/api/v1/report", "/api/v1/verify", "/favicon.ico",
}

# Hard ceiling on a companion report body, enforced from Content-Length BEFORE
# anything is parsed. Every field inside ReportIn is individually capped too;
# this is the belt to that pair of braces, and the one thing that stops a
# holder of the shared report token from OOMing the single-worker container
# with a multi-GB body (see the unbounded-report finding). A full report with
# the maximum permitted manifest is well under 8 MB.
MAX_REPORT_BODY_BYTES = 8 * 1024 * 1024
# Companion builds are single-file PyInstaller exes; the current one is ~40 MB
# and this is a deliberately generous ceiling on top of it. Without a cap the
# publish route streamed an unbounded body straight to the /data dataset (an
# admin session, but a filled dataset takes the SQLite DB down with it).
# api_publish_package also counts the bytes it actually receives, because
# Content-Length is advisory for a chunked request.
MAX_PACKAGE_BODY_BYTES = 200 * 1024 * 1024
# Routes whose body is BUFFERED IN MEMORY downstream (FastAPI reads the whole
# thing before the route function runs), so the gate counts the bytes itself
# and stops at the ceiling. Content-Length is advisory: a chunked request
# carries none at all, which is what made the cap bypassable (KNOWN_BUGS B15).
_BODY_LIMITS = {"/api/v1/report": ("POST", MAX_REPORT_BODY_BYTES)}
# (path prefix, method, limit) -- the packages route has the platform and
# version in its path, so it can't be matched exactly. These are declaration
# checks ONLY: api_publish_package streams its body to disk and counts the
# bytes as it goes (api.py), so buffering it here would turn a 200 MB upload
# into 200 MB of resident memory -- exactly what this middleware exists to
# prevent.
_BODY_LIMIT_PREFIXES = (
    ("/api/v1/admin/packages/", "PUT", MAX_PACKAGE_BODY_BYTES),
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    # The b-roll ingest routes are a WRITE path that no session protects (the
    # indexer is not a browser), so the token guarding them is a credential and
    # is validated before anything else happens. Refusing to start is the point:
    # a blank token used to fall through to the b-roll app's own dev mode, where
    # any logged-in editor -- or a stolen session cookie -- could repoint every
    # clip's archive path, and a placeholder token is a credential published in
    # this repo. Neither may be reachable by accident.
    broll_ingest_token = (settings.broll_ingest_token
                          or os.environ.get("BROLL_INGEST_TOKEN", "")).strip()
    if settings.broll_enabled:
        problem = broll.check_ingest_token(broll_ingest_token)
        if problem:
            raise RuntimeError(
                f"DASH_BROLL_ENABLED=1 but BROLL_INGEST_TOKEN {problem}. The b-roll "
                f"ingest endpoints are an unauthenticated write path for the indexer; "
                f"they are never served without a strong token. Set BROLL_INGEST_TOKEN "
                f"(e.g. `openssl rand -hex 24`) and redeploy, or set "
                f"DASH_BROLL_ENABLED=0 to run the dashboard without the b-roll UI."
            )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = db.connect(settings.db_path)
        db.migrate(conn)
        conn.close()
        # The collector runs even with no SYNCTHING_GUI_URL configured: it is
        # the only thing that ever calls db.prune, and eight tables grow
        # without bound on /data otherwise. run_cycle() skips every
        # Syncthing-backed kind in that configuration (see
        # collector.SYNCTHING_FREE_KINDS).
        collector = Collector(settings)
        collector.start()
        app.state.collector = collector
        try:
            yield
        finally:
            if collector is not None:
                collector.stop()

    app = FastAPI(title="Creators Club Sync Dashboard", lifespan=lifespan)
    app.state.settings = settings

    def _too_large(limit: int) -> JSONResponse:
        return JSONResponse(
            {"detail": f"request body too large (max {limit} bytes)"},
            status_code=413,
        )

    def _declared_too_large(request, limit: int) -> bool:
        """Content-Length says it is over the ceiling. A missing header is NOT
        a pass -- that is a chunked request, which _buffer_body handles. Only
        reading this header is what made the cap bypassable (B15)."""
        declared = request.headers.get("content-length")
        if declared is None:
            return False
        try:
            return int(declared) > limit
        except ValueError:
            return True   # unparseable length: refuse rather than guess

    def _report_auth_denial(request) -> JSONResponse | None:
        """The /api/v1/report token check, run BEFORE the body is read.

        /api/v1/report is in _OPEN_EXACT (the companion authenticates with
        X-CCSync-Token, not a session), and its route signature is
        `payload: ReportIn` -- so FastAPI used to read and pydantic-validate
        the entire body before api_report ever looked at the token. Any host
        on the LAN/tailnet could therefore spend the container's memory and
        CPU with no credentials at all (KNOWN_BUGS B15). api_report repeats
        this check verbatim: this is the belt, that is the braces, and a
        direct-to-route unit test must still 401.
        """
        if settings.report_token:
            if not api.token_ok(settings.report_token,
                                request.headers.get("x-ccsync-token", "")):
                return JSONResponse(
                    {"detail": "bad or missing X-CCSync-Token"}, status_code=401)
            return None
        if not settings.report_token_optional:
            return JSONResponse(
                {"detail": "report token not configured on server (set DASH_REPORT_TOKEN)"},
                status_code=401,
            )
        return None

    async def _buffer_body(request, limit: int) -> bool:
        """Read the body in chunks, stopping at `limit`, and re-arm the
        request so the route still sees it.

        Returns True when the ceiling was exceeded. Nothing downstream reads
        from the socket afterwards: the replayed receive channel hands over
        the bytes already buffered here, which is what bounds the memory a
        single request can cost regardless of what Content-Length claimed.
        """
        chunks: list[bytes] = []
        size = 0
        try:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    return True
                chunks.append(chunk)
        except ClientDisconnect:
            return False
        body = b"".join(chunks)

        async def replay():
            return {"type": "http.request", "body": body, "more_body": False}

        request._body = body
        request._receive = replay
        return False

    @app.middleware("http")
    async def body_size_gate(request, call_next):
        exact = _BODY_LIMITS.get(request.url.path)
        if exact is not None and request.method == exact[0]:
            limit = exact[1]
            if _declared_too_large(request, limit):
                return _too_large(limit)
            # Credentials first: never spend memory or a pydantic parse on an
            # unauthenticated body.
            if request.url.path == "/api/v1/report":
                denial = _report_auth_denial(request)
                if denial is not None:
                    return denial
            if await _buffer_body(request, limit):
                return _too_large(limit)
            return await call_next(request)
        for prefix, method, value in _BODY_LIMIT_PREFIXES:
            if request.method == method and request.url.path.startswith(prefix):
                if _declared_too_large(request, value):
                    return _too_large(value)
                break
        return await call_next(request)

    def _broll_ingest_token_ok(request) -> bool:
        """The indexer writing to /broll/api/ingest/* is not a browser.

        This only decides whether the request may SKIP the login gate; the
        mounted sub-app is wrapped in broll.BrollGate, which re-checks the same
        token on every ingest request and fails closed. So a session alone never
        reaches ingest, and neither does a deployment that somehow got here with
        no token (create_app refuses to build one, and the token validated there
        is the token captured here -- the environment is not re-read per
        request, where it could have been mutated).
        """
        if not broll_ingest_token:
            return False
        return api.token_ok(broll_ingest_token, request.headers.get("x-ingest-token", ""))

    def _companion_token_ok(request) -> bool:
        # api.token_ok is hmac.compare_digest: `==` on a shared secret leaks
        # its length and matching prefix through timing.
        return api.token_ok(settings.report_token, request.headers.get("x-ccsync-token", ""))

    @app.middleware("http")
    async def login_gate(request, call_next):
        path = request.url.path
        if (
            path in _OPEN_EXACT
            or path.startswith("/static/")
            # companion reads its selection with the shared token (the route
            # itself additionally demands a matching X-CCSync-Identity)
            or (path.startswith("/api/v1/selection/") and _companion_token_ok(request))
            # companion downloads published upgrade packages the same way
            or (path.startswith("/api/v1/companion/package/") and _companion_token_ok(request))
            # the indexer pushing into the mounted b-roll app, token-gated
            or (path.startswith("/broll/api/ingest/") and _broll_ingest_token_ok(request))
        ):
            return await call_next(request)
        if auth.get_session_user(request) is None:
            # /broll/api and /broll/media are fetched by JS and by <video>, which
            # cannot follow a 303 to an HTML login page -- the SPA would parse
            # the page as JSON and the player would fail opaquely. Answer them
            # the same way the dashboard's own API does. Same for /music/api,
            # which carries both the music SPA's fetches and its <audio> src
            # (musicweb serves audio from /api/audio/{id}, not a /media prefix).
            # /ytdl/api is the same story again, and worse if it is missed: the
            # downloader SPA POLLS api/jobs/{id} every 1.5s, so a session that
            # expired mid-pipeline would hand it a login page to JSON.parse
            # once per tick.
            if path.startswith(("/api/", "/broll/api/", "/broll/media/",
                                "/music/api/", "/ytdl/api/")):
                return JSONResponse({"detail": "login required"}, status_code=401)
            # Preserve the destination through login (e.g. the companion's
            # /project-setup deep link) -- ui.py's _safe_next re-validates it.
            from urllib.parse import quote

            target = path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)
        return await call_next(request)

    app.include_router(api.router)
    app.include_router(ui.router)

    # Mounted AFTER the routers so a b-roll route can never shadow a dashboard
    # one, and behind a flag so the fleet dashboard never depends on the b-roll
    # code being present. mount_broll() reports mounted/absent/degraded; only a
    # fully working mount is advertised in the nav (ui.py), because a link to a
    # page that 500s on every request is worse than no link.
    app.state.broll_status = (
        broll.mount_broll(app, broll_ingest_token) if settings.broll_enabled
        else broll.ABSENT
    )
    app.state.broll_mounted = app.state.broll_status == broll.MOUNTED

    # Same contract for the music platform, and mounted the same way: after the
    # routers, best-effort, tri-state, only advertised when it fully took. No
    # flag and no token, unlike b-roll -- musicweb has no route that bypasses
    # login_gate, so there is no credential to validate and nothing to refuse to
    # start over; whether the music tree is shipped to the host IS the switch,
    # and a host without it simply reports ABSENT. See music.py.
    app.state.music_status = music.mount_music(app)
    app.state.music_mounted = app.state.music_status == music.MOUNTED

    # And the YouTube downloader, on the same terms as music -- shipping the
    # tree is the switch, no flag and no token. It gets `settings` rather than
    # nothing because its gate mints the identity the sub-app authorises on
    # (which projects a job may download into), and that identity is decoded
    # from the session cookie with settings.session_secret. See ytdl.py.
    app.state.ytdl_status = ytdl.mount_ytdl(app, settings)
    app.state.ytdl_mounted = app.state.ytdl_status == ytdl.MOUNTED
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Browsers request /favicon.ico unprompted (the path is already in
    # _OPEN_EXACT); serve the Creators Club logo instead of a 404. The
    # <link rel="icon"> in base.html covers everything else.
    favicon_file = STATIC_DIR / "favicon.ico"
    if favicon_file.is_file():
        @app.get("/favicon.ico", include_in_schema=False)
        def favicon() -> FileResponse:
            return FileResponse(str(favicon_file), media_type="image/x-icon")

    return app


def run() -> None:
    import uvicorn

    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.port, workers=1)


if __name__ == "__main__":
    run()
