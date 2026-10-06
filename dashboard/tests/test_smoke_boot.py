"""Does the whole dashboard still start, with all four mounts in it?

docs/MODULAR_UPDATES.md A.2 (phase M1, 2026-10-06). A change-scoped gate
runs the tests that can see the change; this file is in the SMOKE SET that
runs whatever changed, and it is aimed at the seams a scoped run would
otherwise miss: a b-roll-only change that renames something the dashboard's
mount reaches for, or a core change that stops a sub-app's gate answering.

So it boots the REAL in-repo b-roll, music and ytdl trees, not the stand-ins
test_broll_mount.py / test_music_mount.py / test_ytdl_mount.py build (those
are about the mount's own branches and must not depend on a checkout; this
is about whether THIS checkout's two halves still fit). Timeline Cards is the
exception: its code is another repo, so its half comes from the same fake
checkout test_cards_mount.py builds, and what is pinned is the dashboard's side
of that seam (the landing page needs no engine, so nothing is opened).

What one boot must still do:
  * every mount reports MOUNTED, each in its own words, on /api/v1/health;
  * each mount root answers a signed-in GET;
  * /login answers with no session at all;
  * a gated page, and every mount root, sends a stranger to /login rather
    than serving them.

Kept to ONE create_app on purpose: the smoke set has a two-minute budget
(A.2, measured in M0) and this file is in every scoped run.
"""
from __future__ import annotations

import os
import sys
import threading

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, mount_status
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings
from test_cards_mount import fake_src, make_vault  # noqa: F401 - fake_src is a fixture

SECRET = "s" * 32
# The shape check_ingest_token demands (>= 24 chars, not a placeholder).
TOKEN = "5d0c7e21a9b84f36e1c2d7a09b3f58e46c1d2a7b9e0f3c48"

# Top-level package names the three in-repo sub-apps are imported as. `app`
# is b-roll's (a generic name kept since the 2026-08-10 fold, see broll.py).
_SUB_APP_PACKAGES = ("app", "musicweb", "ytdlweb")

MOUNTS = ("broll", "music", "ytdl", "cards")


def _ours(name: str) -> bool:
    return any(name == p or name.startswith(p + ".") for p in _SUB_APP_PACKAGES)


@pytest.fixture
def booted(tmp_path, fake_src, monkeypatch):  # noqa: F811 - the imported fixture
    """One dashboard with b-roll, music, ytdl and Cards all mounted.

    Leaves the process as it found it: the in-repo fallbacks APPEND each
    sub-app's tree to sys.path and the import stays in sys.modules, and a
    later test that installs a fake `app` with monkeypatch.setitem would
    restore OUR real one afterwards rather than an empty slot. Whatever this
    fixture added, it removes; whatever an earlier test left, it leaves.
    """
    modules_before = set(sys.modules)
    path_before = list(sys.path)
    threads_before = {t.ident for t in threading.enumerate()}

    # b-roll reads BROLL_DATA_ROOT at call time; music's DATA_ROOT and ytdl's
    # YTDL_DATA_ROOT / YTDL_WORKER=0 are read at IMPORT time and conftest's
    # session fixtures already point them out of the checkout.
    monkeypatch.setenv("BROLL_DATA_ROOT", str(tmp_path / "brolldata"))
    monkeypatch.setenv("BROLL_INGEST_TOKEN", TOKEN)
    monkeypatch.delenv("CARDS_SRC", raising=False)
    assert os.environ.get("YTDL_WORKER") == "0", (
        "conftest's ytdl guard is gone: a real ytdl mount here would start the "
        "download worker thread")

    vault, _roots, _audio = make_vault(tmp_path, "Civil Defence")
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        db_path=str(tmp_path / "dash.db"), session_secret=SECRET,
        admin_users=frozenset({"owen"}), projects_dir=str(projects),
        report_token="companion-token-not-a-real-one",
        broll_enabled=True, broll_ingest_token=TOKEN,
        site_feature_youtube_download=True,
        cards_enabled=True, cards_src=fake_src, cards_vault_root=str(vault),
        cards_token="cards-token-not-a-real-one")
    app = create_app(settings)
    try:
        with TestClient(app) as client:
            yield app, client
    finally:
        for name in [n for n in sys.modules if n not in modules_before and _ours(n)]:
            del sys.modules[name]
        sys.path[:] = path_before
        leaked = [t.name for t in threading.enumerate()
                  if t.ident not in threads_before and t.is_alive()
                  and t.name.lower().startswith("ytdl")]
        assert not leaked, f"the smoke boot left ytdl threads running: {leaked}"


def _sign_in(client, user="owen"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def test_every_mount_is_mounted_and_says_so_on_health(booted):
    app, client = booted
    for name in MOUNTS:
        status = getattr(app.state, f"{name}_status")
        detail = getattr(app.state, f"{name}_detail")
        assert status == "mounted", f"/{name} did not mount: {status}: {detail}"

    body = _sign_in(client).get("/api/v1/health").json()
    assert body["ok"] is True
    assert set(body["mounts"]) == set(mount_status.NAMES) == set(MOUNTS)
    for name in MOUNTS:
        assert body["mounts"][name]["status"] == "mounted", body["mounts"][name]
        assert body["mounts"][name]["detail"], f"{name} reported no sentence"


def test_each_mount_root_answers_a_signed_in_get(booted):
    _app, client = booted
    _sign_in(client)
    for name in MOUNTS:
        r = client.get(f"/{name}/")
        assert r.status_code == 200, f"/{name}/ answered {r.status_code}: {r.text[:300]}"
        assert "text/html" in r.headers.get("content-type", ""), name


def test_the_login_page_needs_no_session(booted):
    _app, client = booted
    r = client.get("/login")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


@pytest.mark.parametrize("path", ["/", "/fleet", "/broll/", "/music/", "/ytdl/", "/cards/"])
def test_a_stranger_is_sent_to_login_not_served(booted, path):
    _app, client = booted
    r = client.get(path, follow_redirects=False)
    assert r.status_code in (302, 303, 307), (
        f"{path} answered a stranger with {r.status_code}")
    assert "/login" in r.headers.get("location", ""), r.headers.get("location")
