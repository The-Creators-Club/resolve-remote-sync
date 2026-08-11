"""The app must work mounted under a prefix, not just at the origin root.

Adapted from music/web/tests/test_mounted_prefix.py, which was adapted from
broll's, because all three sub-apps have exactly the same trap: the frontend.
A hard-coded root-relative URL (`/api/jobs`, `/app.js`) resolves against the
DASHBOARD's origin root once this app is mounted at /ytdl, so the page loads
and then every request 404s -- or worse, hits a dashboard route.

The fix is document-relative URLs, which work at BOTH `/` and `/ytdl/` with no
build step and no injected base tag. Their one requirement is that the PAGE
carries a trailing slash when mounted, so `api/jobs` resolves to
`/ytdl/api/jobs`; Starlette's mount redirects `/ytdl` -> `/ytdl/` for exactly
that reason, and that redirect is pinned below too.
"""
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import USER
from ytdlweb.main import app as ytdl_app

STATIC = Path(__file__).resolve().parent.parent / 'static'

# A quoted (or url()-wrapped) leading slash onto one of this app's own paths.
# `/api/...` is the API; `/app.js` and `/style.css` are the two assets served
# beside the index.
ROOT_RELATIVE = re.compile(r"""["'`(]/(?:api|media|static)/|["'`(]/(?:app\.js|style\.css)""")


@pytest.fixture()
def mounted_client(con):
    """The real app, mounted under /ytdl exactly as the dashboard will."""
    parent = FastAPI()
    parent.mount('/ytdl', ytdl_app)
    with TestClient(parent) as c:
        c.headers.update({'x-ccsync-user': USER})
        yield c


def test_index_is_served_under_the_prefix(mounted_client):
    r = mounted_client.get('/ytdl/')
    assert r.status_code == 200
    assert '<title>' in r.text


def test_the_prefix_without_a_trailing_slash_redirects_to_one(mounted_client):
    """Document-relative URLs are resolved against the page's DIRECTORY. At
    `/ytdl` (no slash) that directory is the origin root, so `api/jobs` would
    resolve to `/api/jobs` -- the dashboard. The mount's 307 to `/ytdl/` is
    what makes the relative URLs correct, so it is load-bearing, not
    cosmetic."""
    r = mounted_client.get('/ytdl', follow_redirects=False)
    assert r.status_code in (301, 307, 308), r.status_code
    assert r.headers['location'].endswith('/ytdl/')

    followed = mounted_client.get('/ytdl')       # TestClient follows by default
    assert followed.status_code == 200
    assert str(followed.url).endswith('/ytdl/')


def test_api_routes_answer_under_the_prefix(mounted_client):
    for path in ('/ytdl/api/me', '/ytdl/api/health', '/ytdl/api/projects',
                 '/ytdl/api/jobs', '/ytdl/api/jobs?limit=5'):
        r = mounted_client.get(path)
        assert r.status_code == 200, f'{path} -> {r.status_code}'


def test_static_assets_are_served_under_the_prefix(mounted_client):
    for path in ('/ytdl/app.js', '/ytdl/style.css', '/ytdl/favicon.svg'):
        assert mounted_client.get(path).status_code == 200, path


def test_the_urls_the_index_asks_for_resolve_under_the_prefix(mounted_client):
    """Walk what the browser would actually do: read the asset URLs out of the
    served HTML, resolve them against the page URL, and fetch them."""
    from urllib.parse import urljoin

    page = mounted_client.get('/ytdl/')
    refs = re.findall(r"""(?:src|href)=["']([^"']+)["']""", page.text)
    assert refs, 'index.html shipped no asset references'
    for ref in refs:
        if ref == '/':
            # The [ DASHBOARD ] fallback back-link: root-relative ON PURPOSE,
            # exactly like broll's and music's -- mounted, it is the way out to
            # the dashboard at the origin root, not an asset of this app.
            continue
        resolved = urljoin(str(page.url), ref)
        r = mounted_client.get(resolved)
        assert r.status_code == 200, f'{ref} -> {resolved} -> {r.status_code}'
        assert '/ytdl/' in resolved, f'{ref} escaped the mount: {resolved}'


def test_the_app_still_works_unmounted(client):
    """Standalone `uvicorn ytdlweb.main:app` stays the dev loop -- the relative
    URLs must not have broken serving at the origin root."""
    assert client.get('/').status_code == 200
    assert client.get('/api/me').status_code == 200
    assert client.get('/api/jobs').status_code == 200
    assert client.get('/app.js').status_code == 200
    assert client.get('/style.css').status_code == 200


# --- the actual regression: no asset may hard-code a root-relative app URL ----

def test_no_shipped_asset_uses_a_root_relative_app_url():
    """The bug this file exists for. A leading slash resolves against the
    ORIGIN, so under /ytdl these hit the dashboard instead of this app."""
    offenders = []
    for name in ('app.js', 'index.html', 'style.css'):
        text = (STATIC / name).read_text(encoding='utf-8')
        for m in ROOT_RELATIVE.finditer(text):
            line = text.count('\n', 0, m.start()) + 1
            offenders.append(f'{name}:{line} {m.group(0)}')
    assert not offenders, (
        'root-relative app URLs break the /ytdl mount: ' + '; '.join(offenders))


def test_nothing_served_to_the_browser_contains_a_root_relative_app_url(mounted_client):
    """Same rule, enforced on the bytes that actually leave the server -- so a
    future templated or generated asset cannot slip past the file scan."""
    offenders = []
    for path in ('/ytdl/', '/ytdl/app.js', '/ytdl/style.css'):
        body = mounted_client.get(path).text
        for m in ROOT_RELATIVE.finditer(body):
            offenders.append(f'{path} {m.group(0)}')
    assert not offenders, (
        'served asset reaches back to the origin root: ' + '; '.join(offenders))


def test_the_guard_would_catch_a_reintroduced_api_literal():
    """Proves the check above is not vacuous: it must fail on the exact edit
    someone is likely to make (`fetch('/api/jobs')`)."""
    assert ROOT_RELATIVE.search("""const s = await api('/api/jobs');""")
    assert ROOT_RELATIVE.search('<script src="/app.js"></script>')
    assert ROOT_RELATIVE.search('<link rel="stylesheet" href="/style.css">')
    assert not ROOT_RELATIVE.search("""const s = await api('api/jobs');""")
    assert not ROOT_RELATIVE.search('<script src="app.js"></script>')


def test_the_topbar_fetch_is_relative_and_asks_for_this_page():
    """`../partials/topbar?current=ytdl` is how this page gets the dashboard's
    real header (and its nav highlight). Root-relative it would work only at
    the origin; with the wrong `current` the nav would highlight b-roll."""
    js = (STATIC / 'app.js').read_text(encoding='utf-8')
    assert "'../partials/topbar?current=ytdl'" in js
