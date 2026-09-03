"""The editor's four pages on a phone (MOBILE_PLAN.md M2, 2026-08-30).

`/`, `/project/<slug>`, `/transfers` and `/installer` are what an editor or an
owner opens away from the desk, and every one of them was built for a 1280 px
window: a six-column table of chips, a move form written as a sentence with
three text inputs in it, and 100 box-drawing characters used as a horizontal
rule. At 390 px each of those is horizontal page scroll, which is the one
failure the phone port must not ship (goal 1).

What is pinned here is the MARKUP contract, not the pixels: the vocabulary
classes style.css (M1) hangs the phone layout off, a `data-label` on every
stacked cell so a row still says which number is which, and the htmx
visibility filter on every poll these pages own. The pixels are M0's sweep,
which runs against the merged branch and can see a screen.

The three properties are each checked twice where it is cheap: once on the
rendered page (so a template that stops being included stops passing) and once
on the template source (so a page whose fixture happens not to reach a branch
still cannot lose the class).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

DASHBOARD_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = DASHBOARD_ROOT / "templates"
MOBILE_CSS = DASHBOARD_ROOT / "static" / "mobile.css"

SECRET = "s" * 32
FF5 = "2026-ff5-elections"
LONG_NAME = "2026/FF5/Elections/Interviewees/Pangolin/A001_05122026_C012.braw"

# Every template MOBILE_PLAN.md §3.3 gives M2. The plan names three files by
# the role they play rather than by their path (the fleet page is
# templates/fleet.html, the bins partial is partials/bins.html, and the sync
# queue's markup is partials/my_queue.html behind the two-include
# partials/queue_section.html) -- these are those files.
OWNED = [
    "fleet.html", "project.html", "transfers.html", "installer.html",
    "project_setup.html",
    "partials/fleet_grid.html", "partials/transfers.html",
    "partials/project_detail.html", "partials/bins.html",
    "partials/notices.html", "partials/queue_section.html",
    "partials/my_queue.html", "partials/project_setup_panel.html",
]

# Every template that renders a <table> on one of M2's five pages, including
# the four partials that were unowned until the round-2 sweep found their
# tables scrolling the page at 768 (collector health, the notice checks, the
# plan-changes ledger and the project roots box, all of which land on `/`).
WITH_TABLES = [
    "partials/fleet_grid.html", "partials/transfers.html",
    "partials/project_detail.html", "partials/my_queue.html",
    "partials/project_setup_panel.html", "partials/collector_health.html",
    "partials/notice_checks.html", "partials/plan_changes.html",
    "partials/project_roots.html",
]

VISIBLE = "[document.visibilityState === 'visible']"


@pytest.fixture
def env(tmp_path):
    """A fleet with something on every panel: a project ticked by the owner, a
    machine that has reported, and a file in flight with a real path in its
    name (the string these pages crop first)."""
    app = create_app(Settings(
        db_path=str(tmp_path / "d.db"), session_secret=SECRET,
        report_token="sekrit", admin_users=frozenset({"owen"}),
    ))
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "d.db")
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, FF5, "2026/FF5/Elections", f"/data/{FF5}", now)
        dbmod.add_selection(conn, "owen", FF5, created_by="owen", now=now)
        conn.commit()

        resp = client.post("/api/v1/report", json={
            "editor_name": "owen",
            "machine": "EDIT-PC",
            "companion_version": "0.9.0",
            "reported_at": now,
            "lanes": [
                {"name": "lane_a_originals_up", "state": "syncing", "queued": 3,
                 "transferring": 1, "last_error": None, "last_sync": None},
                {"name": "lane_b_proxy_down", "state": "idle", "queued": 0,
                 "transferring": 0, "last_error": None, "last_sync": None},
            ],
        }, headers={"X-CCSync-Token": "sekrit",
                    "X-CCSync-Identity": auth.make_identity_token(SECRET, "owen")})
        assert resp.status_code == 200, resp.text

        dbmod.replace_active_transfers(conn, "owen", "EDIT-PC", [{
            "lane": "lane_a_originals_up", "name": LONG_NAME, "direction": "up",
            "bytes_done": 4_000_000, "bytes_total": 8_000_000, "percentage": 50.0,
            "speed_bps": 12_000_000, "eta_seconds": 42, "project_slug": FF5,
        }], now)
        conn.commit()
        yield client, conn
        conn.close()


def as_owner(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    return client


def page(client, url: str) -> str:
    resp = as_owner(client).get(url)
    assert resp.status_code == 200, resp.text
    return resp.text


def cells(html: str, table_start: str) -> list[str]:
    """Every `<td ...>` opening tag of the first table at or after a marker."""
    table = html[html.index(table_start):]
    table = table[:table.index("</table>")]
    return re.findall(r"<td\b[^>]*>", table)


# ----------------------------------------------------- the fleet grid, on `/`


def test_the_machine_table_stacks(env):
    client, _ = env
    body = page(client, "/")
    assert '<table class="editors stack">' in body
    # ...and it is the machine table that stacks, not some other table that
    # happens to carry the class.
    assert "EDIT-PC" in body


def test_every_stacked_cell_says_which_column_it_is(env):
    """A stacked row is a card: without data-label, "0.9.0" and "4 minutes
    ago" are two bare lines with nothing saying which is the build."""
    client, _ = env
    body = page(client, "/")
    tds = cells(body, '<table class="editors stack">')
    assert tds, "the machine table rendered no cells"
    bare = [td for td in tds if "data-label=" not in td]
    assert not bare, f"cells with no data-label: {bare}"
    # UX-16 (2026-09-03): the column is COMPUTER now.
    for label in ("STATUS", "EDITOR", "COMPUTER", "LANES", "VERSION", "LAST REPORT"):
        assert f'data-label="{label}"' in body


def test_the_grids_buttons_are_thumb_sized(env):
    """[ ASK THIS COMPUTER WHY ] is a 12 px word between two chips. On a touch
    screen it is a control, so it carries .tap."""
    client, _ = env
    body = page(client, "/")
    grid = body[body.index('class="fleet-grid-wrap"'):body.index("live-transfers-window")]
    assert "[ ASK THIS COMPUTER WHY ]" in grid
    for btn in re.findall(r'<button class="btn[^"]*"', grid):
        assert "tap" in btn, btn


def test_the_home_page_still_polls_every_two_seconds_and_only_when_visible(env):
    """The rate is the desktop's and it does not change here (pwa.js slows it
    on a coarse pointer). What changes is that a page in a pocket stops
    asking at all."""
    client, _ = env
    body = page(client, "/")
    assert f"""hx-trigger="every 2s {VISIBLE}\"""" in body


# ------------------------------------------------------------- the transfers


def test_the_transfers_tables_stack_and_keep_the_whole_file_name(env):
    client, _ = env
    body = page(client, "/transfers")
    assert '<table class="editors stack">' in body
    for label in ("EDITOR", "DIRECTION", "FILE", "PROGRESS", "SPEED", "ETA"):
        assert f'data-label="{label}"' in body
    # The path wraps rather than scrolling the page, and the untruncated
    # value is still on the element for a pointer.
    assert f'class="mono-sm path" data-label="FILE" title="{LONG_NAME}"' in body


# ---------------------------------------------------------- the project page


def test_the_project_page_wraps_its_path_and_polls_politely(env):
    client, _ = env
    body = page(client, f"/project/{FF5}")
    assert f'class="muted mono-sm path" title="/data/{FF5}"' in body
    assert f"""hx-trigger="every 10s {VISIBLE}\"""" in body
    assert f"""hx-trigger="load, every 5s {VISIBLE}\"""" in body


def test_the_project_detail_table_stacks_with_labels():
    """The editors table needs a shared Syncthing folder to render a row, so
    the label set is pinned on the template: the class and every data-label
    the nine columns need."""
    src = (TEMPLATES / "partials" / "project_detail.html").read_text(encoding="utf-8")
    assert '<table class="editors stack">' in src
    for label in ("STATUS", "EDITOR", "SYNCED", "HAS", "MISSING", "MEDIA",
                  "LANES", "LAST SEEN"):
        assert f'data-label="{label}"' in src


# ------------------------------------------------------------- the installer


def test_the_installer_tells_a_phone_what_the_download_is_for(env):
    """The companion cannot run on the phone that is reading this page. One
    sentence, shown only below the phone breakpoint."""
    client, _ = env
    body = page(client, "/installer")
    assert "installer-phone-note" in body
    note = body[body.index("installer-phone-note"):]
    note = note[:note.index("</div>")]
    assert "phone-only" in body[:body.index("installer-phone-note")][-60:]
    assert "editor's own computer" in note


def test_the_download_button_is_a_thumb_target():
    src = (TEMPLATES / "installer.html").read_text(encoding="utf-8")
    assert '<a class="btn tap" href="/download/{{ plat }}">' in src


# --------------------------------------------- properties of every template


@pytest.mark.parametrize("name", OWNED)
def test_no_box_drawing_rule_survives(name):
    """`{{ "-" * 100 }}` (with the box-drawing character) is 100 characters of
    horizontal overflow at 390 px. The rule is an element now, drawn by a
    border in style.css."""
    src = (TEMPLATES / name).read_text(encoding="utf-8")
    assert '"─" *' not in src
    assert "─" not in src


@pytest.mark.parametrize("name", OWNED)
def test_every_poll_waits_for_a_visible_page(name):
    """MOBILE_PLAN.md §3.4: a phone in a pocket holding a poll is a connection
    the fleet's editors share, against --workers 1."""
    src = (TEMPLATES / name).read_text(encoding="utf-8")
    for trigger in re.findall(r'hx-trigger="([^"]*)"', src):
        if "every " not in trigger:
            continue
        assert VISIBLE in trigger, f"{name}: {trigger}"


def test_the_fleet_section_of_mobile_css_is_phone_only():
    """These pages are unchanged on the desktop (goal 5): every rule M2 adds
    lives inside the phone query or the tablet query, and inside its own
    marked section. 900 px is where the nowrap sweep lives -- the sweep FAILs
    at 768 as well as at 390, and a 1500 px line of monospace is too wide for
    both."""
    css = MOBILE_CSS.read_text(encoding="utf-8")
    section = css[css.index("== fleet =="):css.index("== admin ==")]
    assert "@media (max-width: 600px)" in section
    assert "@media (max-width: 900px)" in section
    assert "@media (pointer: coarse)" in section
    # Nothing outside a media query: every `{` in the section belongs either
    # to one of the two queries or to a selector inside one.
    depth = 0
    for i, ch in enumerate(section):
        if ch == "{":
            if depth == 0:
                assert section[:i].rstrip().endswith(")"), \
                    f"a rule outside a media query at offset {i}"
            depth += 1
        elif ch == "}":
            depth -= 1
    assert depth == 0


@pytest.mark.parametrize("name", WITH_TABLES)
def test_every_table_sits_in_a_scroll_x_wrapper(name):
    """The phone layer stops at 600 px by design, so at 768 a table is still a
    table and takes the sideways scroll with it -- which the first sweep
    FAILed on every one of these pages. Inside a .scroll-x wrapper the scroll
    is the element's own, which §3.2 allows; below 600 the table stacks and
    the wrapper is inert. The class goes on the wrapper, never on the table
    (M1's rule)."""
    src = (TEMPLATES / name).read_text(encoding="utf-8")
    assert '<table class="scroll-x' not in src
    n = src.count("<table")
    assert n and src.count('<div class="scroll-x"><table') == n
    assert src.count("</table></div>") == n


def test_nothing_user_generated_is_nowrap_below_the_tablet_breakpoint():
    """The round-2 sweep's rule of thumb. `.mono`/`.mono-sm` are nowrap in
    style.css and these pages write whole sentences in them: the notice's
    WHAT TO DO line alone was 1517 px wide at 390. Pinned as the selectors
    that must be released, because each one is a page the sweep FAILed."""
    css = MOBILE_CSS.read_text(encoding="utf-8")
    section = css[css.index("== fleet =="):css.index("== admin ==")]
    block = section[section.index("@media (max-width: 900px)"):]
    block = block[:block.index("@media (max-width: 600px)")]
    for selector in ("#server-notices .mono-sm", ".queue-group summary",
                     ".clip-list .clip-name", "#project-detail .mono-sm",
                     ".fleet-grid-wrap .mono-sm", ".presence-box .mono-sm"):
        assert selector in block, selector
    assert block.count("white-space: normal") >= 2
    assert "overflow-wrap: anywhere" in block
