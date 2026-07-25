"""FastAPI app factory and uvicorn entry point.

The collector runs as an in-process daemon thread started by the lifespan
handler -- one container, one process, one worker (the SQLite concurrency
model depends on workers=1; see db.py).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import api, auth, db, ui
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
_BODY_LIMITS = {"/api/v1/report": ("POST", MAX_REPORT_BODY_BYTES)}
# (path prefix, method, limit) -- the packages route has the platform and
# version in its path, so it can't be matched exactly.
_BODY_LIMIT_PREFIXES = (
    ("/api/v1/admin/packages/", "PUT", MAX_PACKAGE_BODY_BYTES),
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

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

    @app.middleware("http")
    async def body_size_gate(request, call_next):
        limit = None
        exact = _BODY_LIMITS.get(request.url.path)
        if exact is not None and request.method == exact[0]:
            limit = exact[1]
        else:
            for prefix, method, value in _BODY_LIMIT_PREFIXES:
                if request.method == method and request.url.path.startswith(prefix):
                    limit = value
                    break
        if limit is not None:
            declared = request.headers.get("content-length")
            if declared is not None:
                try:
                    too_big = int(declared) > limit
                except ValueError:
                    too_big = True
                if too_big:
                    return JSONResponse(
                        {"detail": f"request body too large (max {limit} bytes)"},
                        status_code=413,
                    )
        return await call_next(request)

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
        ):
            return await call_next(request)
        if auth.get_session_user(request) is None:
            if path.startswith("/api/"):
                return JSONResponse({"detail": "login required"}, status_code=401)
            # Preserve the destination through login (e.g. the companion's
            # /project-setup deep link) -- ui.py's _safe_next re-validates it.
            from urllib.parse import quote

            target = path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)
        return await call_next(request)

    app.include_router(api.router)
    app.include_router(ui.router)
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


def run() -> None:
    import uvicorn

    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.port, workers=1)


if __name__ == "__main__":
    run()
