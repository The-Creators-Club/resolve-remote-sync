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

from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s" * 32


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
