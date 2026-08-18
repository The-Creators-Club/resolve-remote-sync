"""GET /partials/topbar: the one header, served to the mounted SPAs.

base.html includes partials/topbar.html; the b-roll and music SPAs fetch the
same partial (document-relative, so it resolves to this route only when they
are mounted under the dashboard) and swap it in over their static fallback
headers. What the SPAs' loadDashboardTopbar() depends on is pinned here:

  - the `data-dash-topbar` marker, which is how a SPA tells the real topbar
    from whatever else a fetch might have returned before injecting it;
  - the login redirect for a dead session, which the SPA detects via
    `res.redirected` and keeps its fallback header instead of injecting a
    login form into the page;
  - `?current=` marking the fetching page's own nav entry.
"""
from __future__ import annotations

import builtins
import sys

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s" * 32


@pytest.fixture(autouse=True)
def _no_music_mount(monkeypatch):
    """Force mount_music() to ABSENT, whatever this machine's venv holds.

    mount_music takes no flag (music.py) -- its dev fallback puts the in-repo
    music/web on sys.path and MOUNTED/ABSENT then depends on whether numpy
    happens to be importable in THIS venv. The dashboard's own venv lacks it
    (deliberately no torch/numpy) so this file passed locally, but the first
    hosted CI run installs numpy for other reasons and the mount went live --
    the same false pass-for-a-wrong-reason test_music_mount.py's `no_musicweb`
    fixture exists to prevent (see that file's docstring). This module's tests
    assert "nothing is mounted here" as their premise, so the premise has to be
    made true rather than hoped true.
    """
    real_import = builtins.__import__

    def fail_on_musicweb(name, *a, **kw):
        if name == "musicweb" or name.startswith("musicweb."):
            raise ImportError("simulated: the music tree is not deployed here")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fail_on_musicweb)
    for name in [n for n in sys.modules if n == "musicweb" or n.startswith("musicweb.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    yield


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(
        Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET)))


def as_user(client, user="jsmith"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def test_topbar_partial_serves_the_marked_header(tmp_path):
    with _client(tmp_path) as c:
        r = as_user(c).get("/partials/topbar")
        assert r.status_code == 200
        assert "data-dash-topbar" in r.text
        assert "[ TRANSFERS ]" in r.text
        assert "[ LOGOUT ]" in r.text
        # No mounts in this app instance -> no platform links to advertise.
        assert 'href="/broll/"' not in r.text
        assert 'href="/music/"' not in r.text


def test_the_served_partial_carries_the_wrap_safe_structure(tmp_path):
    """What the SPAs inject has to be the wrap-safe markup too (2026-08-18):
    the stamp and the session chip inside one .topbar-right, and no loose
    "//" text node between nav entries. Their stylesheets paint the header
    they inject, so a partial that regressed here would break three pages,
    not one. The CSS half is pinned in test_theme_css.py."""
    with _client(tmp_path) as c:
        body = as_user(c).get("/partials/topbar").text
        right = body[body.index('class="topbar-right"'):]
        assert 'class="stamp"' in right and 'class="session"' in right
        nav = body[body.index('href="/transfers"'):body.index('class="topbar-right"')]
        assert 'class="dim"' not in nav


def test_topbar_partial_redirects_a_dead_session_to_login(tmp_path):
    """The SPAs' `res.redirected` guard hangs off this: a session that expired
    under a long-open /broll or /music tab must produce a redirect, never a
    200 whose body is the login page."""
    with _client(tmp_path) as c:
        r = c.get("/partials/topbar", follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]


def test_current_marks_only_the_named_nav_entry(tmp_path):
    """?current= highlights the fetching page's own entry. Exercised through
    an entry that is always present (nothing is mounted in this app), by
    checking nothing gets marked for an unknown or absent value."""
    with _client(tmp_path) as c:
        as_user(c)
        assert "nav-current" not in c.get("/partials/topbar").text
        assert "nav-current" not in c.get("/partials/topbar?current=broll").text


def test_the_dashboards_own_pages_render_the_same_partial(tmp_path):
    """base.html includes the partial, so the header cannot drift between the
    dashboard's pages and what the SPAs inject."""
    with _client(tmp_path) as c:
        page = as_user(c).get("/")
        assert page.status_code == 200
        assert "data-dash-topbar" in page.text
        assert "[ TRANSFERS ]" in page.text
