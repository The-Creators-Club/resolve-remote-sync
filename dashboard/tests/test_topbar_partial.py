"""GET /partials/topbar: the one header, served to the mounted SPAs.

shell.html includes partials/topbar.html (the HUD); the b-roll and music SPAs fetch the
same partial (document-relative, so it resolves to this route only when they
are mounted under the dashboard) and swap it in over their static fallback
headers. What the SPAs' loadDashboardTopbar() depends on is pinned here:

  - the `data-dash-topbar` marker, which is how a SPA tells the real topbar
    from whatever else a fetch might have returned before injecting it;
  - the login redirect for a dead session, which the SPA detects via
    `res.redirected` and keeps its fallback header instead of injecting a
    login form into the page;
  - `?current=` marking the fetching page's own nav entry.

Since the terminal look replaced the classic one (2026-09-25) the header is
the HUD: a short nav in the bar, and everything it has no room for in two
popovers (the account menu #hud-user and the "more" sheet #hud-more) plus a
phone dock, all opened by the HTML popover API with NO script -- the only
mechanism that can work here, because the SPAs inject this markup with
innerHTML and innerHTML never runs a <script> it carries. (The 2026-08-18
left drawer these tests first pinned was the classic header's version of the
same rule; test names that say "drawer" keep their history.)
"""
from __future__ import annotations

import builtins
import sys

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, ui
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


def _between(body: str, start: str, end: str) -> str:
    i = body.index(start)
    return body[i:body.index(end, i)]


def _user_menu(body: str) -> str:
    return _between(body, 'id="hud-user"', "</div>")


def _more_sheet(body: str) -> str:
    return _between(body, 'id="hud-more"', 'id="install-slot"')


def test_topbar_partial_serves_the_marked_header(tmp_path):
    with _client(tmp_path) as c:
        r = as_user(c).get("/partials/topbar")
        assert r.status_code == 200
        assert "data-dash-topbar" in r.text
        assert 'class="hud"' in r.text
        assert 'href="/transfers"' in r.text
        assert 'action="/logout"' in r.text and ">sign out</button>" in r.text
        # No mounts in this app instance -> no platform links to advertise.
        assert 'href="/broll/"' not in r.text
        assert 'href="/music/"' not in r.text


def test_the_served_partial_carries_the_wrap_safe_structure(tmp_path):
    """What the SPAs inject has to be the wrap-safe markup too (2026-08-18):
    the stamp and the session chip travel as ONE item (.hud-meta, the
    terminal's .topbar-right), so a narrow window can never strand "updated
    4s ago" on one row and the user on the next. Their stylesheets paint the
    header they inject, so a partial that regressed here would break three
    pages, not one. The CSS half is pinned in test_theme_css.py."""
    with _client(tmp_path) as c:
        body = as_user(c).get("/partials/topbar").text
        meta = _between(body, 'class="hud-meta"', 'id="hud-user"')
        assert 'id="topbar-stamp"' in meta and 'class="hud-user' in meta
        # The spacer, not the meta row, takes the free width: the meta row is
        # pushed right as one unit.
        assert body.index('class="hud-spacer"') < body.index('class="hud-meta"')


def test_the_drawer_needs_no_javascript(tmp_path):
    """The mechanism, pinned. The SPAs inject this markup with innerHTML,
    which never executes a <script> that came with it, so a menu that needed
    one would be dead on /broll, /music and /ytdl. The popover attribute pair
    is the whole implementation: the button names the panel, the panel
    declares itself a popover, and the browser supplies Esc, click-outside
    and the backdrop. Two panels now: the account menu and the "more"
    sheet."""
    with _client(tmp_path) as c:
        body = as_user(c).get("/partials/topbar").text
        assert 'popovertarget="hud-user"' in body
        assert 'id="hud-user" popover' in body
        assert 'aria-label="account menu"' in body
        assert 'popovertarget="hud-more"' in body
        assert 'id="hud-more" popover' in body
        assert "<script" not in body


def test_every_destination_is_reachable_from_the_phone_dock_and_sheet(tmp_path):
    """Was test_the_bar_holds_no_module_links_and_the_drawer_holds_them_all.
    Changed on purpose by the terminal look: the bar carries a short nav
    again (the HUD's "> sync  > transfers"), and what the classic drawer held
    is split between that nav, the account menu and the phone's dock + "more"
    sheet. What survives of the 2026-08-18 rule: every destination is
    reachable on a phone (where the nav is hidden) through the dock and the
    sheet, and none of it is the old bracketed nav-link vocabulary."""
    with _client(tmp_path) as c:
        body = as_user(c).get("/partials/topbar").text
        nav = _between(body, 'class="hud-nav"', "</nav>")
        assert 'href="/"' in nav and 'href="/transfers"' in nav
        dock = _between(body, 'class="hud-dock"', "</nav>")
        assert 'href="/"' in dock and 'href="/transfers"' in dock
        assert 'popovertarget="hud-more"' in dock
        sheet = _more_sheet(body)
        for href in ('href="/download"', 'href="/help"', 'href="/account"',
                     'action="/logout"', 'action="/logout-everywhere"'):
            assert href in sheet, href
        assert "nav-link" not in body
        assert "[ " not in body


def test_the_installer_entry_is_the_download_itself(tmp_path):
    """The installer entry points at /download, not at a page about a
    download (2026-08-18, owner: the installer "must NOT be a sub-page under
    Settings/Transfers"). /download 303s to the current package for this
    browser's User-Agent, so the click IS the download.

    Everyone gets it, admin or not: the entry left the Settings strip the same
    day, and admins install editor machines too. Both the account menu
    (desktop) and the "more" sheet (phone) carry it."""
    with _admin_client(tmp_path) as c:
        for user in ("owen", "jsmith"):
            body = as_user(c, user).get("/partials/topbar").text
            assert 'href="/download">installer' in _user_menu(body)
            assert 'href="/download">installer' in _more_sheet(body)
            # Nothing points at the chooser page any more; it is the fallback
            # /download itself paints for an unknown User-Agent.
            assert 'href="/installer"' not in body


def test_only_an_admin_gets_the_settings_gear_and_the_settings_entry(tmp_path):
    """A way into Settings from every page is the owner's own request
    (2026-08-18; the classic gear, the HUD's "settings" nav entry now).
    /admin/settings 403s for an editor, so an editor gets no settings entry
    anywhere -- a control that always refuses is worse than no control."""
    with _admin_client(tmp_path) as c:
        admin_body = as_user(c, "owen").get("/partials/topbar").text
        # SYS-6 (wave 4, 2026-09-04): the entry lands on HEALTH, the page that
        # composes all four "is my fleet all right" lists, not on the site form.
        nav = _between(admin_body, 'class="hud-nav"', "</nav>")
        assert f'href="{ui.SETTINGS_LANDING}"' in nav and ">settings</a>" in nav
        assert f'href="{ui.SETTINGS_LANDING}">settings' in _more_sheet(admin_body)
        # UX-3: the guide is one click from every page, for everyone.
        assert 'href="/help"' in _user_menu(admin_body)
        # Sign out everywhere stays reachable.
        assert ">sign out everywhere</button>" in admin_body

        editor_body = as_user(c, "jsmith").get("/partials/topbar").text
        assert f'href="{ui.SETTINGS_LANDING}"' not in editor_body
        assert ">settings" not in editor_body
        # ...but HELP is not admin-only: an editor needs it most.
        assert 'href="/help"' in editor_body
        assert ">sign out everywhere</button>" in editor_body


def test_the_drawer_only_names_modules_that_are_mounted(tmp_path):
    """Same rule the bar always had: an absent or degraded mount gets no link
    at all, because a link into a 500 is worse than no link."""
    with _client(tmp_path) as c:
        body = as_user(c).get("/partials/topbar").text
        for absent in ('href="/broll/"', 'href="/music/"', 'href="/ytdl/"',
                       'href="/cards/"'):
            assert absent not in body
        assert 'href="/"><span class="hud-slash"' in body


def test_topbar_partial_redirects_a_dead_session_to_login(tmp_path):
    """The SPAs' `res.redirected` guard hangs off this: a session that expired
    under a long-open /broll or /music tab must produce a redirect, never a
    200 whose body is the login page."""
    with _client(tmp_path) as c:
        r = c.get("/partials/topbar", follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]


def test_current_marks_only_the_named_nav_entry(tmp_path):
    """?current= highlights the fetching page's own entry. Nothing gets marked
    for a missing value or for a module that is not mounted here; a present
    entry (transfers) is marked in the bar and in the dock, and nowhere
    else."""
    with _client(tmp_path) as c:
        as_user(c)
        assert "aria-current" not in c.get("/partials/topbar").text
        assert "aria-current" not in c.get("/partials/topbar?current=broll").text
        body = c.get("/partials/topbar?current=transfers").text
        assert body.count('aria-current="page"') == 2
        assert body.count('href="/transfers" aria-current="page"') == 2


def test_the_dashboards_own_pages_render_the_same_partial(tmp_path):
    """shell.html includes the partial, so the header cannot drift between the
    dashboard's pages and what the SPAs inject."""
    with _client(tmp_path) as c:
        page = as_user(c).get("/")
        assert page.status_code == 200
        assert "data-dash-topbar" in page.text
        assert 'class="hud"' in page.text
        assert 'href="/transfers"><span class="hud-slash"' in page.text
