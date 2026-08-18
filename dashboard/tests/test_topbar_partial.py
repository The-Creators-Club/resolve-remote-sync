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

Since the 2026-08-18 redesign the bar itself holds no module links at all:
they are in a left drawer opened by the HTML popover API, with NO script --
which is the only mechanism that can work here, because the SPAs inject this
markup with innerHTML and innerHTML never runs a <script> it carries.
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


def _client(tmp_path, admins: frozenset[str] = frozenset()) -> TestClient:
    return TestClient(create_app(
        Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                 admin_users=admins)))


def _admin_client(tmp_path) -> TestClient:
    return _client(tmp_path, admins=frozenset({"owen"}))


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
    the stamp and the session chip inside one .topbar-right. Their stylesheets
    paint the header they inject, so a partial that regressed here would break
    three pages, not one. The CSS half is pinned in test_theme_css.py."""
    with _client(tmp_path) as c:
        body = as_user(c).get("/partials/topbar").text
        right = body[body.index('class="topbar-right"'):]
        assert 'class="stamp"' in right and 'class="session"' in right


def test_the_drawer_needs_no_javascript(tmp_path):
    """The mechanism, pinned. The SPAs inject this markup with innerHTML,
    which never executes a <script> that came with it, so a drawer that needed
    one would be dead on /broll, /music and /ytdl. The popover attribute pair
    is the whole implementation: the button names the panel, the panel
    declares itself a popover, and the browser supplies Esc, click-outside
    and the backdrop."""
    with _client(tmp_path) as c:
        body = as_user(c).get("/partials/topbar").text
        assert 'popovertarget="nav-drawer"' in body
        assert 'id="nav-drawer" popover' in body
        assert 'aria-label="menu"' in body
        assert "<script" not in body


def test_the_bar_holds_no_module_links_and_the_drawer_holds_them_all(tmp_path):
    """The redesign: the modules and the admin pages left the bar. Checked on
    the partial an editor gets, whose drawer names the two hub pages they are
    allowed to open."""
    with _client(tmp_path) as c:
        body = as_user(c).get("/partials/topbar").text
        drawer = body[body.index('id="nav-drawer"'):body.index("</nav>")]
        bar = body[:body.index('<div class="nav-drawer"')] \
            + body[body.index("</nav>"):]
        assert "[ SYNC STATUS ]" in drawer
        assert "[ TRANSFERS ]" in drawer and "[ INSTALLER ]" in drawer
        # ...and nowhere else. The bar is the menu button, the brand and who
        # you are.
        assert "[ TRANSFERS ]" not in bar
        assert "nav-link" not in body


def test_only_an_admin_gets_the_settings_gear_and_the_settings_entry(tmp_path):
    """The gear is the owner's own request (2026-08-18): a way into Settings
    from every page. /admin/settings 403s for an editor, so an editor gets
    neither the gear nor the drawer entry -- a control that always refuses is
    worse than no control."""
    with _admin_client(tmp_path) as c:
        admin_body = as_user(c, "owen").get("/partials/topbar").text
        assert 'class="gear-link" href="/admin/settings"' in admin_body
        assert "[ SETTINGS ]" in admin_body
        # LOGOUT ALL moved into the drawer's foot; it stays reachable.
        assert "[ LOGOUT ALL ]" in admin_body

        editor_body = as_user(c, "jsmith").get("/partials/topbar").text
        assert "gear-link" not in editor_body
        assert "[ SETTINGS ]" not in editor_body
        assert "[ LOGOUT ALL ]" in editor_body


def test_the_drawer_only_names_modules_that_are_mounted(tmp_path):
    """Same rule the bar always had: an absent or degraded mount gets no link
    at all, because a link into a 500 is worse than no link."""
    with _client(tmp_path) as c:
        body = as_user(c).get("/partials/topbar").text
        for absent in ('href="/broll/"', 'href="/music/"', 'href="/ytdl/"'):
            assert absent not in body
        assert "[ SYNC STATUS ]" in body


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
        assert "drawer-current" not in c.get("/partials/topbar").text
        assert "drawer-current" not in c.get("/partials/topbar?current=broll").text


def test_the_dashboards_own_pages_render_the_same_partial(tmp_path):
    """base.html includes the partial, so the header cannot drift between the
    dashboard's pages and what the SPAs inject."""
    with _client(tmp_path) as c:
        page = as_user(c).get("/")
        assert page.status_code == 200
        assert "data-dash-topbar" in page.text
        assert "[ TRANSFERS ]" in page.text
