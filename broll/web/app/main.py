"""FastAPI app entrypoint. `uvicorn app.main:app`."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

from app import client_folders, config
from app.db import ensure_schema
from app.routes_api import router as api_router
from app.routes_batches import router as batches_router
from app.routes_client_folders import router as client_folders_router
from app.routes_fleet import router as fleet_router
from app.routes_ingest import router as ingest_router
from app.routes_media import router as media_router
from app.routes_share import router as share_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    for d in (
        config.get_data_root(),
        config.get_proxies_dir(),
        config.get_sprites_dir(),
        config.get_posters_dir(),
        config.get_sheets_dir(),
    ):
        d.mkdir(parents=True, exist_ok=True)
    ensure_schema(config.get_db_path())
    # Client folders live in their OWN file beside broll.db (see
    # app/client_folders.py for why an index publish must not be able to
    # take them with it). Mounted under the dashboard this lifespan never
    # runs -- ccsync_dashboard.broll._init_broll_storage does the same two
    # calls, and get_shares_db ensures it again on first use regardless.
    client_folders.ensure_schema()
    yield


app = FastAPI(title="B-Roll Platform", lifespan=lifespan)

app.include_router(api_router)
app.include_router(media_router)
app.include_router(ingest_router)
# Dashboard b-roll ingest (docs/BROLL_INGEST_PLAN.md, 2026-08-18). Two doors on
# one ledger, deliberately in separate modules because they authenticate
# differently and must never learn each other's habits: routes_batches is the
# browser's (identity stamped by the dashboard's BrollGate from a session
# cookie), routes_fleet is the companion's (shared fleet token PLUS a signed
# identity, no session anywhere in sight).
app.include_router(batches_router)
app.include_router(fleet_router)
# Client folders (docs/CLIENT_FOLDERS.md, 2026-08-18): the editor's curation
# API (session-stamped identity, like routes_batches) and the PUBLIC viewer
# under /share/{token}/ -- the one part of this app answered with no session
# at all, on the token alone, read-only. The dashboard's login_gate opens
# `/broll/share/` for exactly that prefix.
app.include_router(client_folders_router)
# The viewer page's assets, reachable under the same public prefix so a
# Funnel/proxy that publishes only `/broll/share` carries the whole page.
# Declared BEFORE share_router so `/share/assets/...` is never read as a
# token (client_folders.TOKEN_RE would refuse "assets" anyway; this is the
# belt to that brace).
app.mount("/share/assets", StaticFiles(directory=config.STATIC_DIR), name="share-assets")
app.include_router(share_router)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "index.html")


# Serve app.js/style.css/etc. Mounted last so API/media routes above take
# precedence over any same-named static path.
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
