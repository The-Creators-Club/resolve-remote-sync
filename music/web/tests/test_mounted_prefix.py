"""The app must work mounted under a prefix, not just at the origin root.

It is being mounted into the cc_sync dashboard at /music so editors get one URL
and one login (SPEC port step 4). Mounting is the easy half; the trap is the
frontend, which had fifteen hard-coded root-relative URLs (`/api/stats`,
`/api/audio/1`, `/app.js`, `/style.css`, ...). Those resolve against the
dashboard's origin root when mounted, so the page loads and then every request
404s.

The fix is document-relative URLs, which work at BOTH `/` and `/music/` with no
build step and no injected base tag -- the same mechanism broll/web uses
(`broll/web/tests/test_mounted_prefix.py`). Their one requirement is that the
PAGE carries a trailing slash when mounted, so that `api/stats` resolves to
`/music/api/stats` and not `/api/stats`; Starlette's mount redirects
`/music` -> `/music/` for exactly that reason, and that redirect is pinned
below too.

These tests pin all of it: the same app object, mounted, answers on the prefix,
and no asset shipped to the browser reaches back to the origin root.
"""
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from musicweb.main import app as music_app

STATIC = Path(__file__).resolve().parent.parent / 'static'

# A quoted (or url()-wrapped) leading slash onto one of this app's own paths.
# `/api/...` is the API; the named files are the assets served beside the index
# (ingest.js added bug-hunt-2026-09-03 music-4 -- it is the biggest of them and
# the one most likely to grow a fetch()).
ROOT_RELATIVE = re.compile(
    r"""["'`(]/(?:api|media|static)/|["'`(]/(?:app\.js|ingest\.js|style\.css)""")

# Driven off the directory, not off a list (music-4): the guard must cover the
# fourth asset the day it is written, not the day someone remembers this file.
SHIPPED_ASSETS = sorted(
    [p.name for p in STATIC.rglob('*.js')] + ['index.html', 'style.css'])


@pytest.fixture()
def mounted_client(seeded_db):
    """The real app, mounted under /music exactly as the dashboard will."""
    parent = FastAPI()
    parent.mount('/music', music_app)
    with TestClient(parent) as c:
        yield c


def test_index_is_served_under_the_prefix(mounted_client):
    r = mounted_client.get('/music/')
    assert r.status_code == 200
    assert '<title>' in r.text


def test_the_prefix_without_a_trailing_slash_redirects_to_one(mounted_client):
    """Document-relative URLs are resolved against the page's DIRECTORY. At
    `/music` (no slash) that directory is the origin root, so `api/stats` would
    resolve to `/api/stats` -- the dashboard. The mount's 307 to `/music/` is
    what makes the relative URLs correct, so it is load-bearing, not cosmetic."""
    r = mounted_client.get('/music', follow_redirects=False)
    assert r.status_code in (301, 307, 308), r.status_code
    assert r.headers['location'].endswith('/music/')

    followed = mounted_client.get('/music')      # TestClient follows by default
    assert followed.status_code == 200
    assert str(followed.url).endswith('/music/')


def test_api_routes_answer_under_the_prefix(mounted_client):
    # No /api/resolve/* here: those shell out to a Resolve worker subprocess
    # with a 90s timeout. Prefix-safety is a routing property and stats/facets/
    # tracks prove it without waking DaVinci Resolve up.
    for path in ('/music/api/stats', '/music/api/facets', '/music/api/tracks',
                 '/music/api/tracks?limit=2'):
        r = mounted_client.get(path)
        assert r.status_code == 200, f'{path} -> {r.status_code}'


def test_media_routes_answer_under_the_prefix(mounted_client):
    for path in ('/music/api/audio/1', '/music/api/peaks/1'):
        r = mounted_client.get(path)
        assert r.status_code == 200, f'{path} -> {r.status_code}'
    assert mounted_client.get('/music/api/peaks/1').content


def test_static_assets_are_served_under_the_prefix(mounted_client):
    for path in ['/music/style.css'] + [
            '/music/' + n for n in SHIPPED_ASSETS if n.endswith('.js')]:
        assert mounted_client.get(path).status_code == 200, path


def test_the_urls_the_index_asks_for_resolve_under_the_prefix(mounted_client):
    """Walk what the browser would actually do: read the asset URLs out of the
    served HTML, resolve them against the page URL, and fetch them."""
    from urllib.parse import urljoin

    page = mounted_client.get('/music/')
    refs = re.findall(r"""(?:src|href)=["']([^"']+)["']""", page.text)
    assert refs, 'index.html shipped no asset references'
    for ref in refs:
        if ref == '/':
            # The [ DASHBOARD ] fallback back-link: root-relative ON PURPOSE,
            # exactly like broll's -- mounted, it is the way out to the
            # dashboard at the origin root, not an asset of this app.
            continue
        resolved = urljoin(str(page.url), ref)
        r = mounted_client.get(resolved)
        assert r.status_code == 200, f'{ref} -> {resolved} -> {r.status_code}'
        assert '/music/' in resolved, f'{ref} escaped the mount: {resolved}'


def test_the_app_still_works_unmounted(client):
    """Standalone `uvicorn musicweb.main:app` stays the dev loop -- the relative
    URLs must not have broken serving at the origin root."""
    assert client.get('/').status_code == 200
    assert client.get('/api/stats').status_code == 200
    assert client.get('/api/tracks?limit=2').status_code == 200
    assert client.get('/app.js').status_code == 200
    assert client.get('/style.css').status_code == 200


# --- the actual regression: no asset may hard-code a root-relative app URL ----

def test_no_shipped_asset_uses_a_root_relative_app_url():
    """The bug this file exists for. A leading slash resolves against the
    ORIGIN, so under /music these hit the dashboard instead of this app."""
    offenders = []
    for name in SHIPPED_ASSETS:
        text = (STATIC / name).read_text(encoding='utf-8')
        for m in ROOT_RELATIVE.finditer(text):
            line = text.count('\n', 0, m.start()) + 1
            offenders.append(f'{name}:{line} {m.group(0)}')
    assert not offenders, (
        'root-relative app URLs break the /music mount: ' + '; '.join(offenders))


def test_the_scan_covers_every_javascript_file_that_is_shipped():
    """bug-hunt-2026-09-03 music-4. The scan above ran off a hand-written list
    of three names, and `ingest.js` -- 1108 lines, its own route, and the file
    most likely to grow a `fetch('/api/...')` -- was not one of them. The list
    comes off the directory now, so this only has to pin that the directory is
    what was read."""
    on_disk = {p.name for p in STATIC.rglob('*.js')}
    assert 'ingest.js' in on_disk, 'the ingest panel is no longer shipped?'
    assert on_disk <= set(SHIPPED_ASSETS)


def test_nothing_served_to_the_browser_contains_a_root_relative_app_url(mounted_client):
    """Same rule, enforced on the bytes that actually leave the server -- so a
    future templated or generated asset cannot slip past the file scan."""
    offenders = []
    for path in ['/music/', '/music/style.css'] + [
            '/music/' + n for n in SHIPPED_ASSETS if n.endswith('.js')]:
        body = mounted_client.get(path).text
        for m in ROOT_RELATIVE.finditer(body):
            offenders.append(f'{path} {m.group(0)}')
    assert not offenders, (
        'served asset reaches back to the origin root: ' + '; '.join(offenders))


def test_the_guard_would_catch_a_reintroduced_api_literal():
    """Proves the check above is not vacuous: it must fail on the exact edit
    someone is likely to make (`fetch('/api/stats')`)."""
    assert ROOT_RELATIVE.search("""const s = await api('/api/stats');""")
    assert ROOT_RELATIVE.search('<script src="/app.js"></script>')
    assert ROOT_RELATIVE.search("""await fetch('/api/ingest-batches/limits');""")
    assert ROOT_RELATIVE.search('<script src="/ingest.js"></script>')
    assert ROOT_RELATIVE.search('<link rel="stylesheet" href="/style.css">')
    assert not ROOT_RELATIVE.search("""const s = await api('api/stats');""")
    assert not ROOT_RELATIVE.search('<script src="app.js"></script>')
