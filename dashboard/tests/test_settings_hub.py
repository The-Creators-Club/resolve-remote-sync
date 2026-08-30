"""The Settings hub: one strip, seven pages, and /admin/packages.

The 2026-08-18 nav redesign. The bar used to carry eight bracketed links and
the packages/vendor-feed/dashboard-update panels were the bottom third of the
Users page, where the owner went looking for "how do I update the dashboard"
and did not find them. Now: Users, Assignments, Transfers, Setup and Packages
all hang off Settings, every one of them renders the same strip
(partials/settings_nav.html) with its own entry marked, and every one keeps
the route it always had -- this is a strip, not a router.

The INSTALLER entry was in this strip for part of that same day and is not any
more: it is a download, not a page. The drawer takes [ INSTALLER ] straight to
/download; what remains here is the pin that the strip does NOT offer it (see
test_the_strip_does_not_offer_the_installer) and the /installer chooser's own
tests at the foot of the file.

What is pinned here is what an admin can actually reach, because the failure
mode of a nav redesign is a page that still exists and nothing links to.
"""
from __future__ import annotations

import builtins
import re
import sys

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s" * 32

# The strip's opening tag, whatever else is in its class list. It used to be
# pinned as the exact string `class="settings-nav"`, which stopped being a
# statement about the strip the day the phone layout wanted `scroll-x` on it
# as well (MOBILE_PLAN.md M1 round 2, 2026-08-30): the sweep exempts an
# element from "content scrolls sideways" only if it CARRIES that class, so
# the class has to be in the markup and this file was the thing in the way.
# What these tests are about is the strip being on the page, not the order of
# words in its attribute.
NAV_OPEN = re.compile(r'<nav[^>]*\sclass="([^"]*)"[^>]*>')


def _strip_match(body: str):
    """The first <nav> whose class list carries settings-nav as a WHOLE token.

    Whole token, not a substring: `settings-nav-item` is the class on every
    link inside the strip, so a substring test would still find the strip in
    a page that had lost it and kept one link.
    """
    for match in NAV_OPEN.finditer(body):
        if "settings-nav" in match.group(1).split():
            return match
    return None


def has_strip(body: str) -> bool:
    return _strip_match(body) is not None


def strip_at(body: str) -> int:
    """Where the strip's opening tag starts. Raises like str.index did."""
    match = _strip_match(body)
    if match is None:
        raise ValueError("no settings-nav in this page")
    return match.start()


# key -> (url, label). The order is the strip's own.
HUB = {
    "site": ("/admin/settings", "[ SITE ]"),
    "users": ("/admin/users", "[ USERS ]"),
    "assignments": ("/admin/assignments", "[ ASSIGNMENTS ]"),
    "transfers": ("/transfers", "[ TRANSFERS ]"),
    "setup": ("/setup", "[ SETUP ]"),
    "packages": ("/admin/packages", "[ PACKAGES ]"),
}
# The one an editor may open. The rest 403 or redirect for them, so the strip
# must not offer them (see test_the_strip_offers_an_editor_only_their_pages).
EDITOR_PAGES = ("transfers",)


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
    assert has_strip(page.text)
    # Its own entry is the current one...
    assert f'settings-nav-current" href="{url}"' in page.text
    assert page.text.count("settings-nav-current") == 1
    # ...and every other entry is offered as a plain link.
    for other, (other_url, other_label) in HUB.items():
        assert other_label in page.text, f"{key} page does not offer {other_label}"


def test_the_strip_is_found_whatever_else_is_in_its_class_list():
    """What the relaxation above is FOR (MOBILE_PLAN.md M1 round 2,
    2026-08-30): below the phone breakpoint the strip is a row that scrolls
    sideways inside itself, and the sweep only exempts an element from
    "content scrolls sideways" if it CARRIES `.scroll-x`. This file pinned
    the exact attribute and was the reason the class could not be added."""
    assert has_strip('<nav class="settings-nav" aria-label="settings">')
    assert has_strip('<nav class="settings-nav scroll-x" aria-label="settings">')
    assert has_strip('<nav aria-label="settings" class="scroll-x settings-nav">')
    # ...and it is still a statement about THIS strip, not any nav.
    assert not has_strip('<nav class="drawer-nav">')
    assert not has_strip('<nav class="settings-nav-item">')


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
    """Transfers is editor-visible and always was. The other five 403 or
    bounce, so an editor standing on Transfers is shown one entry rather than
    five refusals."""
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
    assert not has_strip(polled)


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
#
# It left the hub on 2026-08-18 (owner: "it must NOT be a sub-page under
# Settings/Transfers"). The click is the download now: the drawer's
# [ INSTALLER ] is /download, which 303s to this browser's own package. The
# chooser page survives one rung down, as what /download paints when the
# User-Agent names neither platform, and as the "other platform" link for the
# admin setting a Mac up from a Windows browser.

WINDOWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
MACOS_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
# A UA that names neither. Not exotic: TestClient's own default is one, and so
# is a Linux browser or anything with a trimmed User-Agent.
UNKNOWN_UA = "Mozilla/5.0 (X11; Linux x86_64)"


def test_the_strip_does_not_offer_the_installer(client):
    """The removal itself, checked on every page that renders the strip: a hub
    entry that comes back would put the download two clicks and one page
    behind where it belongs."""
    for url, _label in HUB.values():
        body = as_user(client, "owen").get(url).text
        assert "[ INSTALLER ]" not in body[strip_at(body):body.index("</nav>")]


def test_download_303s_to_the_browsers_own_package(client):
    """Windows and macOS, the two platforms the fleet runs on."""
    as_user(client, "jsmith")
    for ua, plat in ((WINDOWS_UA, "windows"), (MACOS_UA, "macos")):
        resp = client.get("/download", follow_redirects=False,
                          headers={"User-Agent": ua})
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/download/{plat}"


def test_an_unknown_user_agent_gets_the_chooser_not_a_guess(client):
    """The old code answered anything it did not recognise with the Windows
    exe. A Linux admin, or a browser with a trimmed UA, then downloaded the
    wrong installer with no page to go back to. Now the guess only fires when
    the UA actually said something, and everyone else is ASKED."""
    as_user(client, "jsmith")
    resp = client.get("/download", follow_redirects=False,
                      headers={"User-Agent": UNKNOWN_UA})
    assert resp.status_code == 200
    assert "[ INSTALLER ]" in resp.text
    assert "[ WINDOWS ]" in resp.text and "[ MACOS ]" in resp.text
    # Neither card claims to be this computer, because nothing said so.
    assert "installer-pick-detected" not in resp.text


def test_the_installer_page_offers_both_platforms(client, tmp_path):
    """The chooser, on its own URL. It exists because a User-Agent guess can
    never serve the admin who is standing at a Windows machine setting up
    somebody else's Mac -- and because /download needs somewhere to land when
    the UA names neither platform."""
    as_user(client, "jsmith")
    # Nothing published yet: two platform cards, no download, and NOT an error
    # banner -- a fleet with no Mac package is a normal state.
    page = client.get("/installer")
    assert page.status_code == 200
    assert page.text.count("nothing published for this platform yet") == 2
    assert "/download/" not in page.text
    # No Settings strip: it is not a hub page any more.
    assert not has_strip(page.text)

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
    # The Mac half is still honestly empty.
    assert page.text.count("nothing published for this platform yet") == 1
    # ...and a Windows browser is told which card is its own.
    page = client.get("/installer", headers={"User-Agent": WINDOWS_UA})
    assert "installer-pick-detected" in page.text
