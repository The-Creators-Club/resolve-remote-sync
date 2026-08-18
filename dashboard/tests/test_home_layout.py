"""The home page's layout: the owner's 2026-08-18 redesign of `/`.

Four things were asked for, and each one has a way of quietly coming undone,
so each one is pinned here:

  1. FLEET OVERVIEW first, SYNC QUEUE second. The order is the page's whole
     argument -- "is everyone's footage where it should be" before "what is
     mine doing" -- and a template reshuffle would not fail any other test.
  2. A windowed live-transfers view, the /transfers content in a panel exactly
     35vh tall that scrolls inside itself. The height is in style.css and the
     class is in the template, so both halves are checked: a panel with no
     height is an unbounded list that pushes the queue off the screen, which
     is the thing the window exists to prevent.
  3. No [ ADD TO QUEUE ] in the queue panel. Ticking lives in the sidebar
     tree; a second control that starts a real sync is exactly the sort of
     thing that grows back.
  4. [ FIX DESTINATION ROOT ] is its own sub-section below the queue, not a
     block inside the queue box.

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

SECRET = "s" * 32
STYLE_CSS = Path(__file__).resolve().parents[1] / "static" / "style.css"

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
    template, so a change to which partial renders which heading cannot slip
    past by keeping the template's line order."""
    body = home(client)
    assert "FLEET OVERVIEW" in body and "[ SYNC QUEUE: JSMITH ]" in body
    assert body.index("FLEET OVERVIEW") < body.index("[ SYNC QUEUE: JSMITH ]")


def test_the_live_window_sits_between_the_grid_and_the_queue(client):
    """"At the top of the sync/transfers area": below the fleet grid, above
    the queue it shares the area with."""
    body = home(client)
    assert (body.index("FLEET OVERVIEW")
            < body.index("live-transfers-window")
            < body.index("[ SYNC QUEUE: JSMITH ]"))


# --------------------------------------------- 2. the live-transfers window


def test_the_home_page_carries_the_live_transfers_panel(client):
    """The same content /transfers shows, server-rendered on first paint so
    the window is never a blank hole while the first poll flies."""
    body = home(client)
    assert 'class="live-transfers-window"' in body
    assert "LIVE TRANSFERS" in body
    assert "[ QUEUED ]" in body and "[ HISTORY ]" in body


def test_the_window_is_exactly_35vh_and_scrolls_inside_itself(client):
    """The number is the owner's and it lives in one place. A `max-height`
    would let the panel shrink to nothing when nothing is transferring and the
    page below it would jump every 2s, so `height` is load-bearing too."""
    css = STYLE_CSS.read_text(encoding="utf-8")
    rule = css[css.index(".live-transfers-window {"):]
    rule = rule[:rule.index("}")]
    assert "height: 35vh" in rule
    assert "max-height" not in rule
    assert "overflow: auto" in rule


def test_the_poll_swaps_the_wrapper_inside_the_panel_never_the_panel(client):
    """The scroll position lives on the panel. The 2s refresh is an innerHTML
    swap of a wrapper INSIDE it, so a reader mid-list keeps their place; a
    poll on the panel itself would yank them to the top twice a second."""
    body = home(client)
    panel = body[body.index('class="live-transfers-window"'):]
    panel_open_tag = panel[:panel.index(">")]
    assert "hx-get" not in panel_open_tag
    inner = panel[panel.index(">"):panel.index("LIVE TRANSFERS")]
    assert 'hx-get="/partials/transfers"' in inner
    assert 'hx-trigger="every 2s"' in inner
    assert 'hx-swap="innerHTML"' in inner


def test_the_transfers_page_is_still_a_page(client):
    """The window is an addition. Bookmarks, the drawer entry an editor gets
    and the Settings strip all still open the full page."""
    page = as_user(client).get("/transfers")
    assert page.status_code == 200
    assert "LIVE TRANSFERS" in page.text
    # ...and the page is NOT windowed: it is the full-height view.
    assert "live-transfers-window" not in page.text


# ------------------------------------------------------- 3. the sync queue


def test_the_queue_panel_has_no_add_to_queue_control(client):
    """Read and untick, nothing else. Ticking is the sidebar tree's job -- one
    control, next to the project it applies to, with a tree and a scroll of
    its own."""
    body = home(client)
    queue = body[body.index('class="queue-box"'):body.index("fix-root-box")]
    assert "[ ADD TO QUEUE ]" not in queue
    assert "[ TICK ]" not in queue
    assert "[ ADD TO QUEUE ]" not in body
    # The sidebar still carries the real ticking control.
    assert 'class="proj-check"' in body


def test_the_queue_panel_still_unticks(client):
    """What the panel IS for. The toggle answers with the queue box alone, so
    the fix-root section standing beside it survives an untick."""
    assert "[ UNTICK ]" in home(client)
    resp = as_user(client).post(f"/partials/selection/jsmith/{FF5}/toggle")
    assert resp.status_code == 200
    assert 'class="queue-box"' in resp.text
    # ...the queue box ALONE: it is swapped over `closest .queue-box`, so a
    # fragment that also carried the root panel would paint a second copy of
    # it on every untick.
    assert "fix-root-box" not in resp.text
    assert "Nothing ticked" in resp.text
    assert "[ ADD TO QUEUE ]" not in resp.text and "[ TICK ]" not in resp.text


# ------------------------------------------------ 4. fix destination root


def test_fix_destination_root_is_its_own_section_below_the_queue(client):
    body = home(client)
    assert "[ FIX DESTINATION ROOT ]" in body
    assert 'class="fix-root-box"' in body
    # Below the queue...
    assert body.index('class="queue-box"') < body.index('class="fix-root-box"')
    # ...and OUTSIDE it: the queue box closes before the root panel opens.
    queue = body[body.index('class="queue-box"'):body.index('class="fix-root-box"')]
    assert "[ FIX DESTINATION ROOT ]" not in queue


def test_the_queue_poll_carries_both_panels(client):
    """One route, one build_queue_view, two panels. The 10s poll has to bring
    the root section back with the queue or the section it swaps over would
    vanish ten seconds after the page painted -- the failure the /transfers
    strip already taught us (test_settings_hub.py)."""
    as_user(client)
    frag = client.get("/partials/queue")
    assert frag.status_code == 200
    assert "[ SYNC QUEUE: JSMITH ]" in frag.text
    assert "[ FIX DESTINATION ROOT ]" in frag.text
    assert "<!doctype html" not in frag.text.lower()


def test_the_root_section_reports_the_honest_empty_state(client):
    """Behaviour unchanged by the move, including the state every fresh fleet
    starts in: no companion has reported an open Resolve project yet, so the
    panel says so rather than showing a stale or invented root."""
    body = home(client)
    section = body[body.index('class="fix-root-box"'):]
    assert "no Resolve project reported yet" in section
