"""FastAPI app: the JSON API plus the single-page UI.

    cd ytdl/web && .venv\\Scripts\\python.exe -m uvicorn ytdlweb.main:app

The FastAPI instance is `app` because that is what gets mounted; the PACKAGE is
`ytdlweb`. broll/web is deployed by putting its tree on PYTHONPATH and
importing it as the top-level package `app`, so a second package of that name
would collide in sys.modules and one of the two would silently win -- the same
rule music/web follows with `musicweb`.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response

from ytdlweb import config, db, worker, ytdl_canary
from ytdlweb.routes_api import router as api_router
from ytdlweb.routes_fleet import router as fleet_router


@asynccontextmanager
async def lifespan(_app):
    """Standalone dev only -- Starlette does NOT run a mounted sub-app's
    lifespan, only the outermost app's. Mounted, the identical work is done by
    ccsync_dashboard.ytdl._init_ytdl_storage() at mount time, where it doubles
    as the probe that tells MOUNTED from DEGRADED. Both paths call
    worker.ensure_started(), which is idempotent for exactly that reason."""
    config.ensure_data_root()
    con = db.connect()
    try:
        db.init(con)
    finally:
        con.close()
    worker.ensure_started()
    # Beside the worker and idempotent for the same reason (plan WP5,
    # 2026-08-26). A no-op unless YTDL_CANARY_INTERVAL_SECONDS is set, which
    # ships unset.
    ytdl_canary.ensure_started()
    yield


app = FastAPI(title='CC Sync YouTube', lifespan=lifespan)
app.include_router(api_router)
# The companion's claim/lease/manifest/status routes. A SEPARATE router because
# they are authenticated differently -- the fleet token, not the browser session
# (docs/YTDL_LOCAL_DOWNLOAD.md §8) -- and mixing the two in one module is how a
# session-only assumption gets applied to a machine-to-machine route by
# accident. Included second: its paths are all longer than routes_api's, so
# nothing shadows anything either way.
app.include_router(fleet_router)


# The frontend asks for these DOCUMENT-relative ('app.js', 'style.css',
# 'api/...'), so the browser resolves them against the directory of the page it
# is on: /app.js standalone, /ytdl/app.js once the dashboard mounts this app at
# /ytdl. Nothing in static/ may carry a leading slash -- that resolves against
# the origin root and lands on the dashboard. tests/test_mounted_prefix.py pins
# it. The page must therefore be served with a trailing slash when mounted;
# Starlette's mount redirects /ytdl -> /ytdl/ for that.
#
# They stay four explicit sibling routes rather than a /static mount because
# relative URLs make a subdirectory unnecessary, and tests/test_api.py pins the
# content types served here.
@app.get('/', response_class=HTMLResponse)
def home():
    return (config.STATIC_DIR / 'index.html').read_text(encoding='utf-8')


@app.get('/app.js')
def appjs():
    return Response((config.STATIC_DIR / 'app.js').read_text(encoding='utf-8'),
                    media_type='application/javascript')


@app.get('/style.css')
def css():
    return Response((config.STATIC_DIR / 'style.css').read_text(encoding='utf-8'),
                    media_type='text/css')


@app.get('/favicon.svg')
def favicon():
    # The product mark, the same file b-roll and music serve -- the tab
    # icon is part of looking like one product.
    return Response((config.STATIC_DIR / 'favicon.svg').read_bytes(),
                    media_type='image/svg+xml')


if __name__ == '__main__':
    import uvicorn
    print(f'  http://{config.HOST}:{config.PORT}')
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level='warning')
