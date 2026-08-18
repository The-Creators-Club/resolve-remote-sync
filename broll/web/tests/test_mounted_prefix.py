"""The app must work mounted under a prefix, not just at the origin root.

It is being mounted into the cc_sync dashboard at /broll so remote editors get
one URL and one login. Mounting is the easy half; the trap is the frontend,
which had eight hard-coded root-relative URLs (`/api/search`, `/media/poster/…`,
`/static/app.js`, …). Those resolve to the dashboard's root when mounted, so
the page loads and then every request 404s.

The fix is document-relative URLs, which work at BOTH `/` and `/broll/` with no
build step and no injected base tag. These tests pin that: the same app object,
mounted, answers on the prefix, and no asset shipped to the browser reaches
back to the origin root.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app as broll_app
from tests.factories import insert_segment, insert_video

STATIC = Path(__file__).resolve().parent.parent / "static"


@pytest.fixture()
def mounted_client(data_root, conn):
    """The real app, mounted under /broll exactly as the dashboard will."""
    parent = FastAPI()
    parent.mount("/broll", broll_app)
    with TestClient(parent) as c:
        yield c


def test_index_is_served_under_the_prefix(mounted_client):
    r = mounted_client.get("/broll/")
    assert r.status_code == 200
    assert "<title>" in r.text


def test_api_routes_answer_under_the_prefix(mounted_client, conn):
    insert_video(conn, share="broll", rel_path="a.mov")
    for path in ("/broll/api/search", "/broll/api/categories", "/broll/api/shares"):
        r = mounted_client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"


def test_media_routes_answer_under_the_prefix(mounted_client, conn, data_root):
    vid = insert_video(conn, share="broll", rel_path="a.mov")
    posters = data_root / "posters"
    posters.mkdir(parents=True, exist_ok=True)
    (posters / f"{vid}.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    r = mounted_client.get(f"/broll/media/poster/{vid}.jpg")
    assert r.status_code == 200
    assert r.content == b"\xff\xd8\xff\xd9"


def test_static_assets_are_served_under_the_prefix(mounted_client):
    for path in ("/broll/static/app.js", "/broll/static/style.css",
                 "/broll/static/ingest.js"):
        assert mounted_client.get(path).status_code == 200, path


def test_the_ingest_panels_session_routes_answer_under_the_prefix(mounted_client):
    """Every `api/ingest-batches…` URL ingest.js builds, mounted.

    The panel is the one part of the SPA that WRITES, and it writes with
    document-relative URLs like `api/ingest-batches/precheck` -- under /broll
    those resolve to the routes below, and at the origin root they resolve to
    the same app. A leading slash on any of them would post the drop at the
    dashboard (docs/BROLL_INGEST_PLAN.md 4.3).
    """
    headers = {"X-CCSync-User": "alex"}
    listed = mounted_client.get("/broll/api/ingest-batches?scope=mine", headers=headers)
    assert listed.status_code == 200, listed.text
    pre = mounted_client.post(
        "/broll/api/ingest-batches/precheck", headers=headers,
        json={"share": "2026-08-18 ingest", "keep_subfolders": True,
              "items": [{"local_id": "a", "name": "A001.MP4"}]})
    assert pre.status_code == 200, pre.text
    assert pre.json()["items"][0]["final_name"] == "A001.MP4"


def test_the_ingest_panel_is_in_the_shipped_page(mounted_client):
    """The drawer and its script ship with index.html, not from a build step."""
    body = mounted_client.get("/broll/").text
    assert 'id="ingest-panel"' in body
    assert 'src="static/ingest.js"' in body


def test_the_app_still_works_unmounted(client, conn):
    """Standalone `uvicorn app.main:app` stays the dev loop — the relative URLs
    must not have broken serving at the origin root."""
    insert_video(conn, share="broll", rel_path="a.mov")
    assert client.get("/").status_code == 200
    assert client.get("/api/search").status_code == 200
    assert client.get("/static/app.js").status_code == 200


# --- the actual regression: no asset may hard-code a root-relative app URL ----

def test_no_shipped_asset_uses_a_root_relative_app_url():
    """The bug this file exists for. `/api/…`, `/media/…` and `/static/…` with a
    leading slash resolve against the ORIGIN, so under /broll they hit the
    dashboard instead of this app.

    `http://127.0.0.1:8899` (the loopback Resolve companion) is deliberately
    absolute and must stay that way — it is a different process, not this app.
    """
    offenders = []
    for name in ("app.js", "index.html", "style.css", "ingest.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        for m in re.finditer(r"""["'`(]/(?:api|media|static)/""", text):
            line = text.count("\n", 0, m.start()) + 1
            offenders.append(f"{name}:{line} {m.group(0)}")
    assert not offenders, (
        "root-relative app URLs break the /broll mount: " + "; ".join(offenders)
    )


def test_the_companion_url_is_still_absolute():
    """Guards the opposite mistake: making the loopback companion relative would
    point it at the web server instead of the editor's local helper."""
    text = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "http://127.0.0.1:8899" in text


def test_no_shipped_asset_names_another_absolute_origin():
    """The loopback is the ONLY absolute origin any of these files may name.

    Both halves matter. A second host would be a page that phones somewhere off
    the box (there is no CDN here and there must not be one), and a loopback on
    any port but 8899 would be a second listener -- which is exactly what the
    retired BRoll Companion was, and why it had to go (CLAUDE.md).

    `www.w3.org` is exempt: it is the SVG namespace of the inline check-mark
    data URI in style.css, a string identifier that is never fetched.
    """
    allowed = ("http://127.0.0.1:8899", "http://www.w3.org")
    offenders = []
    for name in ("app.js", "index.html", "style.css", "ingest.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        for m in re.finditer(r"https?://[\w.:@-]+", text):
            url = m.group(0)
            if url == "http://" or any(url.startswith(a) for a in allowed):
                continue
            offenders.append(f"{name}:{text.count(chr(10), 0, m.start()) + 1} {url}")
    assert not offenders, "unexpected absolute origin: " + "; ".join(offenders)
