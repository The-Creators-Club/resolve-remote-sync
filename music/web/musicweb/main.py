"""FastAPI app: search API + audio streaming + the single-page UI.

    cd music/web && .venv\\Scripts\\python.exe -m uvicorn musicweb.main:app

The FastAPI instance is `app` because that is what gets mounted; the PACKAGE is
`musicweb`. broll/web is deployed by putting its tree on PYTHONPATH and
importing it as the top-level package `app`, so a second package of that name
would collide in sys.modules and one of the two would silently win.
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response

from musicweb import config
from musicweb.routes_api import router as api_router
from musicweb.routes_batches import router as batches_router
from musicweb.routes_fleet import router as fleet_router
from musicweb.routes_ingest import router as ingest_router
from musicweb.routes_media import router as media_router

app = FastAPI(title='Music Tagger')

app.include_router(api_router)
app.include_router(media_router)
app.include_router(ingest_router)
# Dashboard music ingest (docs/MUSIC_INGEST_PLAN.md step 2, 2026-08-18). Two
# doors onto the same ledger and they authenticate completely differently:
# `routes_batches` is the SPA's, identified by the X-CCSync-User the
# dashboard's MusicGate stamps from the session; `routes_fleet` is the
# companion's, with no session at all -- the shared fleet token plus a SIGNED
# identity. The fleet prefix is carved out of the dashboard's login_gate by
# `_music_fleet_re` in app.py, per suffix, never per prefix.
app.include_router(batches_router)
app.include_router(fleet_router)


# The frontend asks for these DOCUMENT-relative ('app.js', 'style.css',
# 'api/...'), so the browser resolves them against the directory of the page it
# is on: /app.js standalone, /music/app.js once the dashboard mounts this app at
# /music. Nothing in static/ may carry a leading slash -- that resolves against
# the origin root and lands on the dashboard. tests/test_mounted_prefix.py pins
# it. The page must therefore be served with a trailing slash when mounted;
# Starlette's mount redirects /music -> /music/ for that.
#
# They stay two explicit sibling routes rather than a /static mount because
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
    # The product mark, same file as broll/web's -- the tab icon is part
    # of looking like one product (2026-08-10 restyle).
    return Response((config.STATIC_DIR / 'favicon.svg').read_bytes(),
                    media_type='image/svg+xml')


if __name__ == '__main__':
    import uvicorn
    print(f'  http://{config.HOST}:{config.PORT}')
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level='warning')
