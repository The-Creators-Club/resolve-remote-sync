"""FastAPI app entrypoint. `uvicorn app.main:app`."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

from app import config
from app.db import ensure_schema
from app.routes_api import router as api_router
from app.routes_batches import router as batches_router
from app.routes_fleet import router as fleet_router
from app.routes_ingest import router as ingest_router
from app.routes_media import router as media_router


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


@app.get("/")
def index() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "index.html")


# Serve app.js/style.css/etc. Mounted last so API/media routes above take
# precedence over any same-named static path.
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
