"""The PWA surfaces: manifest, icons, service worker, offline page, pwa.js.

MOBILE_PLAN.md 4 M4, 2026-08-30. Two properties carry the weight here and the
rest are spelling:

  * all three routes answer with NO SESSION. A phone fetches the manifest and
    registers the worker from the login page; a 303 to /login there installs
    nothing and explains nothing.
  * the worker never caches anything that depends on who is asking. A cached
    page or /partials/ fragment served to a signed-out (or halted) fleet is
    the dashboard lying about whether footage is syncing, which is the one
    thing it may never do. That is asserted as TEXT, on the source, because
    the failure mode is somebody adding a path to the wrong list.
"""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import VERSION
from ccsync_dashboard.app import create_app, _OPEN_EXACT
from ccsync_dashboard.settings import Settings

DASHBOARD_ROOT = Path(__file__).resolve().parents[1]
STATIC = DASHBOARD_ROOT / "static"
ICONS = STATIC / "icons"

# What each committed PNG must actually be, read out of its IHDR. The manifest
# claims these sizes to Chrome; a 512 file that is really 192 gives a blurry
# splash screen and no error anywhere.
PINNED = {
    "icon-180.png": (180, 180),
    "icon-192.png": (192, 192),
    "icon-512.png": (512, 512),
    "icon-192-maskable.png": (192, 192),
    "icon-512-maskable.png": (512, 512),
}

# The prefixes sw.js must hand straight to the network.
NEVER_CACHED = ("/api/", "/partials/", "/cards/", "/broll/", "/music/",
                "/ytdl/", "/login", "/logout", "/.well-known/")


@pytest.fixture()
def client(tmp_path):
    settings = Settings(db_path=str(tmp_path / "pwa.db"), session_secret="test-secret")
    with TestClient(create_app(settings)) as c:
        yield c


def png_size(path: Path) -> tuple[int, int]:
    """Width and height from the PNG IHDR -- stdlib only (there is no PIL in
    this venv, which is also why tools/make_icons.js draws them)."""
    raw = path.read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    assert raw[12:16] == b"IHDR", f"{path.name} does not start with IHDR"
    return struct.unpack(">II", raw[16:24])


# -- the manifest ----------------------------------------------------------


def test_the_manifest_is_readable_without_a_session(client):
    res = client.get("/manifest.webmanifest")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/manifest+json")
    data = res.json()
    assert data["id"] == "/"
    assert data["start_url"] == "/"
    assert data["scope"] == "/"
    assert data["display"] == "standalone"
    assert data["background_color"] == "#0a0a0d"
    assert data["theme_color"] == "#0a0a0d"
    assert data["lang"] == "en"


def test_the_manifest_route_is_in_open_exact():
    assert {"/manifest.webmanifest", "/sw.js", "/offline"} <= _OPEN_EXACT


def test_the_manifest_carries_this_site_s_product_name(tmp_path):
    """The name under the icon is the same brand _render puts in the topbar
    (COMMERCIAL_READINESS.md item 10: no customer's name in code)."""
    settings = Settings(db_path=str(tmp_path / "b.db"), session_secret="test-secret",
                        site_product_name="Reel Sync")
    with TestClient(create_app(settings)) as c:
        data = c.get("/manifest.webmanifest").json()
    assert data["name"] == "Reel Sync"
    assert data["short_name"] == "Reel Sync"


def test_the_static_fallback_manifest_is_valid_json_on_its_own():
    """The route substitutes the brand INTO this file, so it has to stay plain
    JSON: it is what a site whose manifest cannot be read still gets."""
    data = json.loads((STATIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert data["name"] == "CC Sync"


def test_every_icon_the_manifest_names_exists_at_the_size_it_claims(client):
    icons = client.get("/manifest.webmanifest").json()["icons"]
    assert len(icons) == 5
    seen = set()
    for icon in icons:
        src = icon["src"]
        assert src.startswith("/static/icons/")
        name = src.rsplit("/", 1)[-1]
        seen.add(name)
        path = ICONS / name
        assert path.is_file(), f"{src} is in the manifest but not on disk"
        # ...and reachable with no session (it is under /static/, which the
        # login gate lets through, but the install prompt depends on it).
        assert client.get(src).status_code == 200
        if name.endswith(".png"):
            want = tuple(int(n) for n in icon["sizes"].split("x"))
            assert png_size(path) == want, f"{name} is not {icon['sizes']}"
    assert seen == (set(PINNED) - {"icon-180.png"}) | {"icon.svg"}
    # The apple-touch-icon is not in the manifest (base.html links it by
    # contract, MOBILE_PLAN.md 3.3), so it is checked separately.
    assert png_size(ICONS / "icon-180.png") == (180, 180)


@pytest.mark.parametrize("name,size", sorted(PINNED.items()))
def test_the_committed_pngs_are_the_pinned_sizes(name, size):
    assert png_size(ICONS / name) == size


def test_the_maskable_icons_are_a_separate_pair(client):
    icons = client.get("/manifest.webmanifest").json()["icons"]
    maskable = [i for i in icons if i.get("purpose") == "maskable"]
    assert sorted(i["sizes"] for i in maskable) == ["192x192", "512x512"]
    # A single icon marked "any maskable" would be cropped as a maskable AND
    # shown unpadded as an any: two files, two purposes.
    assert all(i["purpose"] in ("any", "maskable") for i in icons)


# -- the service worker ----------------------------------------------------


def test_sw_js_is_served_at_the_root_with_its_scope_header(client):
    res = client.get("/sw.js")
    assert res.status_code == 200
    assert res.headers["service-worker-allowed"] == "/"
    assert res.headers["cache-control"] == "no-cache"
    assert "javascript" in res.headers["content-type"]
    assert VERSION in res.text
    assert "__VERSION__" not in res.text


def test_the_workers_precache_holds_nothing_session_specific():
    """The text assertion MOBILE_PLAN.md 6 asks for: a live path in the
    precache list is a phone showing yesterday's fleet."""
    src = (STATIC / "sw.js").read_text(encoding="utf-8")
    block = re.search(r"const PRECACHE = \[(.*?)\];", src, re.S)
    assert block, "sw.js no longer has a PRECACHE list to check"
    for prefix in NEVER_CACHED:
        assert prefix not in block.group(1), (
            f"{prefix} is in sw.js's PRECACHE list; it may never be cached")
    assert "/offline" in block.group(1)


def test_the_worker_passes_every_live_prefix_through():
    src = (STATIC / "sw.js").read_text(encoding="utf-8")
    block = re.search(r"const PASS_THROUGH = \[(.*?)\];", src, re.S)
    assert block, "sw.js no longer has a PASS_THROUGH list"
    listed = set(re.findall(r"'([^']+)'", block.group(1)))
    assert set(NEVER_CACHED) <= listed


def test_the_worker_takes_over_and_claims_its_clients():
    src = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert "skipWaiting" in src
    assert "clients.claim" in src
    # Navigations network-first with the offline page behind them.
    assert "req.mode === 'navigate'" in src
    assert "caches.match(OFFLINE_URL)" in src


# -- the offline page ------------------------------------------------------


def test_offline_renders_without_a_session(client):
    res = client.get("/offline")
    assert res.status_code == 200
    assert "[ OFFLINE ]" in res.text
    assert "[ RETRY ]" in res.text


def test_offline_says_nothing_about_this_fleet(client):
    """It is precached: anything live in it would be frozen at install time."""
    res = client.get("/offline")
    for word in ("syncing", "transfer", "machine"):
        assert word not in res.text.lower().split("</header>")[-1]


# -- pwa.js ----------------------------------------------------------------


def test_pwa_js_slows_exactly_the_two_intervals():
    """2s -> 10s and 5s -> 15s on a coarse pointer, and nothing else: 15s and
    30s are already cheap enough, and a fourth entry here would be a poll
    somebody silently turned off."""
    src = (STATIC / "pwa.js").read_text(encoding="utf-8")
    table = re.search(r"var SLOWER = \{(.*?)\};", src, re.S)
    assert table, "pwa.js no longer has the SLOWER table"
    pairs = dict(re.findall(r"'(\d+m?s)':\s*'(\d+m?s)'", table.group(1)))
    assert pairs == {"2s": "10s", "5s": "15s"}


def test_pwa_js_only_slows_on_a_coarse_pointer():
    src = (STATIC / "pwa.js").read_text(encoding="utf-8")
    assert "(pointer: coarse)" in src
    assert "if (!COARSE" in src


def test_pwa_js_rewrites_before_htmx_reads_the_trigger():
    """htmx 1.9.12 fires htmx:beforeProcessNode before it reads the trigger
    specs; htmx:load is after, and re-processing a node double-binds its
    poll."""
    src = (STATIC / "pwa.js").read_text(encoding="utf-8")
    assert "htmx:beforeProcessNode" in src
    assert "htmx.process" not in src


def test_pwa_js_registers_the_worker_only_on_a_secure_origin():
    src = (STATIC / "pwa.js").read_text(encoding="utf-8")
    assert "isSecureContext" in src
    assert "navigator.serviceWorker.register('/sw.js'" in src


def test_pwa_js_aborts_polls_when_the_page_is_hidden():
    src = (STATIC / "pwa.js").read_text(encoding="utf-8")
    assert "visibilitychange" in src
    assert "'htmx:abort'" in src


def test_pwa_js_offers_the_install_chip_in_m1_s_slot():
    src = (STATIC / "pwa.js").read_text(encoding="utf-8")
    assert "beforeinstallprompt" in src
    assert "install-slot" in src
    assert "[ INSTALL ]" in src
    assert "(display-mode: standalone)" in src


# -- the Timeline Cards page's own manifest (2026-09-02) --------------------
#
# /cards/ links `manifest.webmanifest` document-relative and Chrome fetches a
# manifest without the session cookie. Behind the login gate that fetch was a
# 303 to /login, so the page was judged not installable and "Install" on a
# phone made a shortcut that opens with the URL bar. The two files the cards
# handler serves before its own gate must be open at this gate too.


def test_the_cards_install_files_are_in_open_exact():
    assert {"/cards/manifest.webmanifest", "/cards/icon.svg"} <= _OPEN_EXACT


def test_the_cards_manifest_is_never_redirected_to_login(client):
    # The cards mount is absent in this suite (no checkout, no vault), so the
    # answer is a 404 -- what matters is that it is not the gate's 303.
    for path in ("/cards/manifest.webmanifest", "/cards/icon.svg"):
        res = client.get(path, follow_redirects=False)
        assert res.status_code != 303, path
        assert "/login" not in res.headers.get("location", ""), path
