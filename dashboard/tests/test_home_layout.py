"""The home page's layout: the owner's 2026-08-18 redesign of `/`.

Four things were asked for, and each one has a way of quietly coming undone,
so each one is pinned here. Rewritten 2026-09-25 against the terminal look
(the only look since the classic one was deleted); every behaviour is the
same, only the markup it is read off changed:

  1. The computers window (the fleet overview) first, the sync queue second.
     The order is the page's whole argument -- "is everyone's footage where
     it should be" before "what is mine doing" -- and a template reshuffle
     would not fail any other test.
  2. A windowed live-transfers view in a panel exactly 35vh tall that
     scrolls inside itself. The height is in cc/home.css and the class is in
     the template, so both halves are checked: a panel with no height is an
     unbounded list that pushes the queue off the screen and shifts the page
     on every 2 s poll, which is the thing the window exists to prevent (the
     terminal port lost it; restored 2026-09-25).
  3. No tick control in the queue window. Ticking lives in the projects
     tree; a second control that starts a real sync is exactly the sort of
     thing that grows back.
  4. FIX DESTINATION ROOT is its own sub-section below the queue table, not a
     row inside it, and it rides the queue's poll and its untick answer.

/transfers stays a page of its own throughout (test_the_transfers_page_is_
still_a_page): the window is an addition, not a move.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

from conftest import HX

SECRET = "s" * 32
HOME_CSS = Path(__file__).resolve().parents[1] / "static" / "cc" / "home.css"

FF5 = "2026-ff5-elections"


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                              admin_users=frozenset({"owen"})))
    with TestClient(app) as c:
        # One real project, so the queue panel and the sidebar tree both render
        # something rather than their empty states.
        conn = dbmod.connect(tmp_path / "d.db")
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, FF5, "2026/FF5/Elections", f"/data/{FF5}", now)
        dbmod.add_selection(conn, "jsmith", FF5, created_by="jsmith", now=now)
        conn.commit()
        yield c
        conn.close()


def as_user(client, user="jsmith"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def home(client, user="jsmith") -> str:
    page = as_user(client, user).get("/")
    assert page.status_code == 200, page.text
    return page.text


# ------------------------------------------------------------ 1. order


def test_fleet_overview_comes_before_the_sync_queue(client):
    """The owner's order, 2026-08-18. Read off the page itself rather than the
    template, so a change to which partial renders which window cannot slip
    past by keeping the template's line order."""
    body = home(client)
    assert 'id="win-computers"' in body and 'id="win-queue"' in body
    assert body.index('id="win-computers"') < body.index('id="win-queue"')
    # ...and the queue is jsmith's own.
    queue = body[body.index('id="win-queue"'):]
    assert "For <b>jsmith</b>" in queue


def test_the_live_window_sits_between_the_grid_and_the_queue(client):
    """"At the top of the sync/transfers area": below the fleet grid, above
    the queue it shares the area with."""
    body = home(client)
    assert (body.index('id="win-computers"')
            < body.index("live-transfers-window")
            < body.index('id="win-queue"'))


# --------------------------------------------- 2. the live-transfers window


def test_the_home_page_carries_the_live_transfers_panel(client):
    """What is moving, server-rendered on first paint so the window is never a
    blank hole while the first poll flies. The queued and history halves are
    one link away on /transfers (the window bar's "all transfers")."""
    body = home(client)
    assert 'class="body flush live-transfers-window"' in body
    win = body[body.index('id="win-transfers"'):body.index('id="win-queue"')]
    assert 'href="/transfers"' in win
    # First paint drew the body, not a loading placeholder.
    assert "Nothing is moving right now." in win
    assert "Safe to close" in win


def test_the_window_is_exactly_35vh_and_scrolls_inside_itself(client):
    """The number is the owner's and it lives in one place. A `max-height`
    would let the panel shrink to nothing when nothing is transferring and the
    page below it would jump every 2s, so `height` is load-bearing too."""
    css = HOME_CSS.read_text(encoding="utf-8")
    rule = css[css.index(".home-page .live-transfers-window {"):]
    rule = rule[:rule.index("}")]
    assert "height: 35vh" in rule
    assert "max-height" not in rule
    assert "overflow: auto" in rule


def test_the_poll_swaps_the_wrapper_inside_the_panel_never_the_panel(client):
    """The scroll position lives on the panel. The 2s refresh is an innerHTML
    swap of a wrapper INSIDE it, so a reader mid-list keeps their place; a
    poll on the panel itself would yank them to the top twice a second."""
    body = home(client)
    panel = body[body.index('class="body flush live-transfers-window"'):]
    panel_open_tag = panel[:panel.index(">")]
    assert "hx-get" not in panel_open_tag
    inner = panel[panel.index(">"):panel.index("Nothing is moving right now.")]
    assert 'hx-get="/partials/home-transfers"' in inner
    # The rate is still 2s (MOBILE_PLAN.md M2, 2026-08-30). The trigger also
    # carries the visibility filter, so a phone in a pocket stops asking.
    assert "hx-trigger=\"every 2s [document.visibilityState === 'visible']\"" in inner
    assert 'hx-swap="innerHTML"' in inner
    # ...and the fold bar is outside every swap target (the port's 3.1 rule).
    win = body[body.index('id="win-transfers"'):]
    bar = win[:win.index("live-transfers-window")]
    assert "hx-get" not in bar


def test_the_transfers_page_is_still_a_page(client):
    """The window is an addition. Bookmarks, the drawer entry an editor gets
    and the Settings strip all still open the full page."""
    page = as_user(client).get("/transfers")
    assert page.status_code == 200
    assert 'hx-get="/partials/transfers"' in page.text
    # ...and the page is NOT windowed: it is the full-height view.
    assert "live-transfers-window" not in page.text


# ------------------------------------------------------- 3. the sync queue


def _queue_window(body: str) -> str:
    return body[body.index('id="win-queue"'):body.index('<h3 class="sec">fix destination root</h3>')]


def test_the_queue_panel_has_no_add_to_queue_control(client):
    """Read and untick, nothing else. Ticking is the projects tree's job -- one
    control, next to the project it applies to, with a tree and a scroll of
    its own."""
    body = home(client)
    queue = _queue_window(body)
    assert "proj-check" not in queue
    assert "mode=on" not in queue
    assert ">Tick<" not in queue and "Add to queue" not in queue
    assert "Add to queue" not in body
    # The projects tree still carries the real ticking control.
    tree = body[body.index('id="win-projects"'):body.index('id="win-computers"')]
    assert 'class="proj-check' in tree


def test_the_queue_panel_still_unticks(client):
    """What the panel IS for. The toggle answers with the queue body alone
    (swapped innerHTML into `closest .queue-box`), carrying the fix-root
    section once, so an untick never paints a second copy of it or nests a
    second queue box."""
    body = home(client)
    assert f"/partials/selection/jsmith/{FF5}/toggle?view=home-queue&amp;mode=off" in body \
        or f"/partials/selection/jsmith/{FF5}/toggle?view=home-queue&mode=off" in body
    assert '<span class="t">Untick</span>' in _queue_window(body)
    resp = as_user(client).post(
        f"/partials/selection/jsmith/{FF5}/toggle?view=home-queue&mode=off", headers=HX)
    assert resp.status_code == 200
    assert "queue-box" not in resp.text
    assert resp.text.count("fix destination root") == 1
    assert "Nothing ticked" in resp.text
    assert "proj-check" not in resp.text and "mode=on" not in resp.text
    # Nothing ticked is never an error or a warning (the owner's rule).
    at = resp.text.index("Nothing ticked")
    empty = resp.text[resp.text.rindex("<div", 0, at):at]
    assert "led off" in empty and "err" not in empty and "warn" not in empty


# ------------------------------------------------ 4. fix destination root


def test_fix_destination_root_is_its_own_section_below_the_queue(client):
    body = home(client)
    assert '<div class="fix-root">' in body
    assert '<h3 class="sec">fix destination root</h3>' in body
    # Below the queue table...
    q = body.index('class="body queue-box"')
    assert q < body.index("</table>", q) < body.index('<div class="fix-root">')
    # ...and OUTSIDE it: the table closes before the root section opens.
    table = body[q:body.index("</table>", q)]
    assert "fix destination root" not in table


def test_the_queue_poll_carries_both_panels(client):
    """One route, one build_queue_view, two sections. The 10s poll has to
    bring the root section back with the queue or the section it swaps over
    would vanish ten seconds after the page painted -- the failure the
    /transfers strip already taught us (test_settings_hub.py)."""
    as_user(client)
    frag = client.get("/partials/home-queue", headers=HX)
    assert frag.status_code == 200
    assert "For <b>jsmith</b>" in frag.text
    assert '<span class="t">Untick</span>' in frag.text
    assert "fix destination root" in frag.text
    assert "<!doctype html" not in frag.text.lower()


def test_the_root_section_reports_the_honest_empty_state(client):
    """Behaviour unchanged by the move, including the state every fresh fleet
    starts in: no companion has reported an open Resolve project yet, so the
    section says so rather than showing a stale or invented root."""
    body = home(client)
    section = body[body.index('<div class="fix-root">'):]
    assert "no Resolve project reported yet" in section
