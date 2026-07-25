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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = db.connect(settings.db_path)
        db.migrate(conn)
        conn.close()
        collector = None
        if settings.syncthing_url:
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
    async def login_gate(request, call_next):
        path = request.url.path
        if (
            path in _OPEN_EXACT
            or path.startswith("/static/")
            # companion reads its selection with the shared token
            or (path.startswith("/api/v1/selection/")
                and request.headers.get("x-ccsync-token")
                and settings.report_token
                and request.headers["x-ccsync-token"] == settings.report_token)
            # companion downloads published upgrade packages the same way
            or (path.startswith("/api/v1/companion/package/")
                and request.headers.get("x-ccsync-token")
                and settings.report_token
                and request.headers["x-ccsync-token"] == settings.report_token)
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
