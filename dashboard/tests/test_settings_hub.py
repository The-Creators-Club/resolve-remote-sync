"""The Settings hub: one strip, seven pages, and /admin/packages.

The 2026-08-18 nav redesign. The bar used to carry eight bracketed links and
the packages/vendor-feed/dashboard-update panels were the bottom third of the
Users page, where the owner went looking for "how do I update the dashboard"
and did not find them. Now: Users, Assignments, Transfers, Setup, Installer
and Packages all hang off Settings, every one of them renders the same strip
(partials/settings_nav.html) with its own entry marked, and every one keeps
the route it always had -- this is a strip, not a router.

What is pinned here is what an admin can actually reach, because the failure
mode of a nav redesign is a page that still exists and nothing links to.
"""
from __future__ import annotations

import builtins
import sys

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s" * 32

# key -> (url, label). The order is the strip's own.
HUB = {
    "site": ("/admin/settings", "[ SITE ]"),
    "users": ("/admin/users", "[ USERS ]"),
    "assignments": ("/admin/assignments", "[ ASSIGNMENTS ]"),
    "transfers": ("/transfers", "[ TRANSFERS ]"),
    "setup": ("/setup", "[ SETUP ]"),
    "installer": ("/installer", "[ INSTALLER ]"),
    "packages": ("/admin/packages", "[ PACKAGES ]"),
}
# The two an editor may open. The rest 403 or redirect for them, so the strip
# must not offer them (see test_the_strip_offers_an_editor_only_their_pages).
EDITOR_PAGES = ("transfers", "installer")


@pytest.fixture(autouse=True)
def _no_music_mount(monkeypatch):
    """Force mount_music() to ABSENT whatever this machine's venv holds, for
    the reason test_topbar_partial.py's copy of this fixture spells out: the
    dev fallback puts the in-repo music/web on sys.path and the mount then
    depends on whether numpy happens to be importable here."""
    real_import = builtins.__import__

    def fail_on_musicweb(name, *a, **kw):
        if name == "musicweb" or name.startswith("musicweb."):
            raise ImportError("simulated: the music tree is not deployed here")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fail_on_musicweb)
    for name in [n for n in sys.modules if n == "musicweb" or n.startswith("musicweb.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    yield


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                              admin_users=frozenset({"owen"})))
    with TestClient(app) as c:
        yield c


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


# ------------------------------------------------------------ the strip


@pytest.mark.parametrize("key", sorted(HUB))
def test_every_hub_page_renders_the_strip_with_itself_marked(client, key):
    url, label = HUB[key]
    page = as_user(client, "owen").get(url)
    assert page.status_code == 200, page.text
    assert 'class="settings-nav"' in page.text
    # Its own entry is the current one...
    assert f'settings-nav-current" href="{url}"' in page.text
    assert page.text.count("settings-nav-current") == 1
    # ...and every other entry is offered as a plain link.
    for other, (other_url, other_label) in HUB.items():
        assert other_label in page.text, f"{key} page does not offer {other_label}"


@pytest.mark.parametrize("key", sorted(HUB))
def test_the_drawer_keeps_settings_lit_on_every_hub_page(client, key):
    """One `nav_current` drives both strips: the entry in the Settings strip
    and the [ SETTINGS ] line in the drawer, so an admin four pages deep still
    sees where they are in the menu."""
    url, _label = HUB[key]
    body = as_user(client, "owen").get(url).text
    assert 'drawer-current" href="/admin/settings"' in body


def test_an_editor_on_transfers_sees_it_lit_in_the_drawer(client):
    """An editor has no Settings hub to enter, so their drawer names Transfers
    itself -- and marks it."""
    body = as_user(client, "jsmith").get("/transfers").text
    assert 'drawer-current" href="/transfers"' in body
    assert "[ SETTINGS ]" not in body


def test_the_strip_offers_an_editor_only_their_pages(client):
    """Transfers is editor-visible and always was; the installer download is
    too. The other five 403 or bounce, so an editor standing on Transfers is
    shown two entries rather than five refusals."""
    page = as_user(client, "jsmith").get("/transfers")
    assert page.status_code == 200
    for key, (_url, label) in HUB.items():
        if key in EDITOR_PAGES:
            assert label in page.text
        else:
            assert label not in page.text


def test_the_transfers_poll_cannot_eat_the_strip(client):
    """The 2s refresh had to move off <main> onto an inner wrapper: it is an
    innerHTML swap, so anything rendered beside the partial inside the polled
    element would vanish two seconds after the page painted."""
    body = as_user(client, "owen").get("/transfers").text
    polled = body[body.index('hx-get="/partials/transfers"'):]
    assert 'class="settings-nav"' not in polled


# ------------------------------------------------------- /admin/packages


def test_packages_has_its_own_page_and_the_users_page_no_longer_carries_it(client):
    """The move itself. Three panels that were below four NAS-backed panels
    about editor accounts are a page of their own now."""
    packages = as_user(client, "owen").get("/admin/packages")
    assert packages.status_code == 200
    assert "[ PUBLISHED PACKAGES ]" in packages.text
    assert "[ AVAILABLE FROM THE VENDOR ]" in packages.text
    # The dashboard's own update panel loads itself on this page.
    assert 'hx-get="/partials/admin/dashboard-update"' in packages.text

    users = client.get("/admin/users")
    assert users.status_code == 200
    assert "[ PUBLISHED PACKAGES ]" not in users.text
    assert "/partials/admin/packages" not in users.text
    assert "/partials/admin/dashboard-update" not in users.text
    # Nothing may point at the old anchor either.
    assert "/admin/users#packages" not in packages.text


def test_the_packages_page_is_admin_only(client):
    assert as_user(client, "jsmith").get("/admin/packages").status_code == 403


@pytest.mark.parametrize("route,data", [
    ("/partials/admin/packages", None),
    ("/partials/admin/dashboard-update", None),
    ("/partials/admin/feed/check", {}),
    ("/partials/admin/feed/policy", {"policy": "manual"}),
    ("/partials/admin/feed/publish", {"kind": "companion", "platform": "windows",
                                      "version": "9.9.9"}),
    ("/partials/admin/packages/current", {"platform": "windows", "version": "9.9.9"}),
    ("/partials/admin/packages/delete", {"platform": "windows", "version": "9.9.9"}),
])
def test_every_packages_route_still_answers_with_the_panel(client, route, data):
    """These are htmx swaps, not redirects, which is why the move cost them
    nothing: each one re-renders the same partial into whatever page it is
    standing on. The pin is that none of them started answering with a page
    or a redirect back to the old /admin/users#packages home."""
    as_user(client, "owen")
    resp = client.get(route) if data is None else client.post(route, data=data)
    assert resp.status_code == 200, resp.text
    assert "<!doctype html" not in resp.text.lower()
    assert "/admin/users" not in resp.text


# --------------------------------------------------------- the installer


def test_the_installer_page_offers_both_platforms(client, tmp_path):
    """/download still guesses this browser's platform and always will -- the
    docs and every editor's bookmark say so. The page exists because a hub
    entry has to be a page, and because the guess is wrong for the admin
    setting up somebody else's Mac from a Windows machine."""
    as_user(client, "jsmith")
    # Nothing published yet: two platform cards, no download, and NOT an error
    # banner -- a fleet with no Mac package is a normal state.
    page = client.get("/installer")
    assert page.status_code == 200
    assert page.text.count("nothing published for this platform yet") == 2
    assert "/download/" not in page.text

    settings = client.app.state.settings
    with db.connect(settings.db_path) as conn:
        db.insert_companion_package(
            conn, version="1.0.30", platform="windows", filename="onboard-1.0.30.exe",
            sha256="a" * 64, size_bytes=1234, published_by="owen",
            now=db.utcnow_iso(), kind="onboard")
        db.set_current_package(conn, "windows", "1.0.30", "onboard")
        conn.commit()

    page = client.get("/installer")
    assert 'href="/download/windows"' in page.text
    assert "1.0.30" in page.text
    # The Mac half is still honestly empty, and /download keeps guessing.
    assert page.text.count("nothing published for this platform yet") == 1
    assert client.get("/download", follow_redirects=False).status_code == 303
