"""The editor's four pages on a phone (MOBILE_PLAN.md M2, 2026-08-30; moved
onto the terminal look 2026-09-25 when the classic look was deleted).

`/`, `/project/<slug>`, `/transfers` and `/installer` are what an editor or an
owner opens away from the desk, and every one of them was built for a 1280 px
window. At 390 px a table of chips, a move form written as a sentence or a
row of box-drawing characters is horizontal page scroll, which is the one
failure the phone port must not ship (goal 1).

What is pinned here is the MARKUP contract, not the pixels: the vocabulary
classes the terminal sheets hang the phone layout off (`.tbl.stack-sm`, the
`.pc` computer card, `.scroll-x`, `.phone-only`), a `data-label` on every
stacked cell so a row still says which number is which, and the htmx
visibility filter on every poll these pages own. The pixels are the sweep's.

The properties are each checked twice where it is cheap: once on the
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
CC = DASHBOARD_ROOT / "static" / "cc"

SECRET = "s" * 32
FF5 = "2026-ff5-elections"
LONG_NAME = "2026/FF5/Elections/Interviewees/Pangolin/A001_05122026_C012.braw"
BOX_RULE = "─"

# The templates of the four pages and every partial they draw. The classic
# queue (my_queue, queue_section) and notices partials are gone; home_queue,
# person_queue, home_problems and home_transfers are their terminal twins.
OWNED = [
    "fleet.html", "project.html", "transfers.html", "installer.html",
    "project_setup.html",
    "partials/fleet_grid.html", "partials/transfers.html",
    "partials/project_detail.html", "partials/bins.html",
    "partials/home_problems.html", "partials/home_queue.html",
    "partials/person_queue.html", "partials/home_transfers.html",
    "partials/projects_tree.html", "partials/project_setup_panel.html",
    "partials/plan_changes.html", "partials/project_roots.html",
]

# Every template that renders a <table> on one of those pages. The collector
# health and notice-check tables left `/` for Settings, then Health.
WITH_TABLES = [
    "partials/fleet_grid.html", "partials/transfers.html",
    "partials/project_detail.html", "partials/home_queue.html",
    "partials/person_queue.html", "partials/plan_changes.html",
    "partials/project_roots.html",
]

VISIBLE = "[document.visibilityState === 'visible']"


def _css(name: str) -> str:
    return re.sub(r"/\*.*?\*/", "", (CC / name).read_text(encoding="utf-8"), flags=re.S)


def _media(css: str, opening: str) -> str:
    """Every {...} body that follows `opening`, joined, brace-balanced."""
    out, pos = [], 0
    while (at := css.find(opening, pos)) >= 0:
        start = css.index("{", at + len(opening))
        depth = 0
        for i in range(start, len(css)):
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            if depth == 0:
                out.append(css[start + 1:i])
                pos = i
                break
    return "\n".join(out)


PHONE = _media(_css("phone.css"), "@media (max-width: 760px)")
NARROW = _media(_css("terminal.css"), "@media (max-width: 1100px)")


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


def _card(body: str) -> str:
    """The first computer card on the home page, through its details."""
    card = body[body.index('<div class="pc home-pc">'):]
    return card[:card.index("</details>")]


# ----------------------------------------------------- the fleet grid, on `/`


def test_the_machine_grid_reflows_into_one_card_per_computer(env):
    """The six-column computer grid is a card per computer below 1100 px:
    the header row goes (it would name columns that are no longer there) and
    the lanes and issues drop to their own rows under the name."""
    client, _ = env
    body = page(client, "/")
    assert "EDIT-PC" in _card(body)
    assert ".pc { grid-template-columns: 16px minmax(0, 1fr) auto; }" in NARROW
    assert ".pc.head-row { display: none; }" in NARROW
    assert ".pc .lanes-wrap { grid-column: 2 / -1; grid-row: 2; }" in NARROW


def test_every_value_on_a_card_says_what_it_is(env):
    """With the header row gone, a card is the only place a value can be
    named: each lane carries its own word, and the build sits in the details
    list under "version", so "0.9.0" is never a bare line."""
    client, _ = env
    card = _card(page(client, "/"))
    for word in ("upload", "proxy download", "folder sync"):
        assert f'<span class="k">{word}</span>' in card, word
    assert "<dt>version</dt><dd>windows, running 0.9.0</dd>" in card
    assert 'aria-label="issues on EDIT-PC"' in card


def test_the_grids_buttons_are_thumb_sized(env):
    """"Ask this computer why" is a small key inside a row's details. On a
    touch screen it is a control, so it is a .key, and the home sheet gives
    every key a 44 px target on a coarse pointer."""
    client, _ = env
    body = page(client, "/")
    grid = body[body.index('<div class="pc home-pc">'):body.index("live-transfers-window")]
    assert "Ask this computer why" in grid
    buttons = [b for b in re.findall(r"<button\b[^>]*>", grid) if 'class="fold"' not in b]
    assert buttons
    for btn in buttons:
        assert re.search(r'class="key\b', btn), btn
    touch = _media(_css("home.css"), "@media (pointer: coarse), (max-width: 760px)")
    assert ".home-page .key.sm, .home-page .key { min-height: var(--cc-tap, 44px); }" in touch


def test_the_home_page_still_polls_every_two_seconds_and_only_when_visible(env):
    """The rate is the desktop's and it does not change here (pwa.js slows it
    on a coarse pointer). What changes is that a page in a pocket stops
    asking at all."""
    client, _ = env
    body = page(client, "/")
    assert f"""hx-trigger="every 2s {VISIBLE}\"""" in body


def test_the_home_transfer_keeps_the_whole_file_name(env):
    client, _ = env
    body = page(client, "/")
    assert f'<span class="file" title="{LONG_NAME}">{LONG_NAME}' in body
    assert ".tbl td, .files li .nm, .xf .file { overflow-wrap: anywhere; }" in PHONE


# ------------------------------------------------------------- the transfers


def test_the_transfers_tables_stack_and_keep_the_whole_file_name(env):
    client, _ = env
    body = page(client, "/transfers")
    # CR-312 (2026-09-24): the FILE cell is scoped by the table's own class
    # (`xft`), so its wrap rule cannot leak into another table.
    assert '<table class="tbl stack-sm fixed xft">' in body
    for label in ("editor", "file", "progress", "speed", "eta"):
        assert f'data-label="{label}"' in body
    # The direction cell is an arrow with a hidden word; it opts out of a
    # heading rather than printing "DIRECTION" above one glyph.
    assert 'class="dir up c-dir" data-label=""' in body
    # The path wraps rather than scrolling the page, and the untruncated
    # value is still on the element for a pointer.
    assert (f'class="file c-file" data-label="file" title="{LONG_NAME}">'
            f'{LONG_NAME}</td>') in body
    assert (".tbl td.file { max-width: none; white-space: normal; "
            "overflow-wrap: anywhere; }") in PHONE


# ---------------------------------------------------------- the project page


def test_the_project_page_wraps_its_path_and_polls_politely(env):
    client, _ = env
    body = page(client, f"/project/{FF5}")
    assert f'<div class="sub"><span class="num" title="/data/{FF5}">/data/{FF5}</span>' in body
    # A server path has no break opportunity; the sub line breaks anywhere.
    head_sub = re.search(r"\.head \.sub \{([^}]*)\}", _css("terminal.css"))
    assert head_sub and "overflow-wrap: anywhere" in head_sub.group(1)
    assert f"""hx-trigger="every 10s {VISIBLE}, cc-plan-changed from:body\"""" in body
    assert f"""hx-trigger="load, every 5s {VISIBLE}\"""" in body


def test_the_project_detail_table_stacks_with_labels():
    """The editors table needs a shared Syncthing folder to render a row, so
    the label set is pinned on the template: the class and every data-label
    the nine columns need."""
    src = (TEMPLATES / "partials" / "project_detail.html").read_text(encoding="utf-8")
    assert '<table class="tbl stack-sm">' in src
    for label in ("status", "editor", "synced", "has", "missing", "media",
                  "sync", "last seen"):
        assert f'data-label="{label}"' in src
    # Every <td> in it says which column it is (the actions cell and the
    # drawer row say so with an empty label).
    table = src[src.index("<table"):src.index("</table>")]
    bare = [td for td in re.findall(r"<td\b[^>]*>", table) if "data-label=" not in td]
    assert not bare, bare


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
    assert '<a class="key primary" href="/download/{{ plat }}"' in src
    touch = _media(_css("phone.css"), "@media (pointer: coarse)")
    assert ".key," in touch and "min-height: var(--tap)" in touch


# --------------------------------------------- properties of every template


@pytest.mark.parametrize("name", OWNED)
def test_no_box_drawing_rule_survives(name):
    """A row of box-drawing characters used as a rule is 100 characters of
    horizontal overflow at 390 px. A rule is a border now."""
    src = (TEMPLATES / name).read_text(encoding="utf-8")
    assert BOX_RULE not in src


@pytest.mark.parametrize("name", OWNED)
def test_every_poll_waits_for_a_visible_page(name):
    """MOBILE_PLAN.md 3.4: a phone in a pocket holding a poll is a connection
    the fleet's editors share, against --workers 1."""
    src = (TEMPLATES / name).read_text(encoding="utf-8")
    for trigger in re.findall(r'hx-trigger="([^"]*)"', src):
        if "every " not in trigger:
            continue
        assert VISIBLE in trigger, f"{name}: {trigger}"


@pytest.mark.parametrize("name", WITH_TABLES)
def test_no_table_can_scroll_the_page_sideways(name):
    """Between the stack (760 px) and a desktop a table is still a table, and
    an auto-layout one grows with its longest cell and takes the page with
    it, which the first sweep FAILed on every one of these pages. Each table
    either sits directly inside a .scroll-x wrapper (the scroll is the
    element's own, which 3.2 allows) or is fixed-layout (`.tbl.fixed`, which
    cannot be wider than its window). The class goes on the wrapper, never on
    the table."""
    src = (TEMPLATES / name).read_text(encoding="utf-8")
    assert '<table class="scroll-x' not in src
    tables = list(re.finditer(r"<table\b[^>]*>", src))
    assert tables
    for m in tables:
        tag = m.group(0)
        before = src[:m.start()].rstrip()
        opener = before[before.rfind("<"):]
        wrapped = opener.startswith("<div") and re.search(
            r'class="[^"]*\bscroll-x\b', opener)
        fixed = re.search(r'class="[^"]*\bfixed\b', tag)
        assert wrapped or fixed, f"{name}: {tag} can scroll the page"
    assert ".tbl.fixed { table-layout: fixed; }" in _css("components.css")


def test_nothing_user_generated_is_nowrap_on_a_phone():
    """The round-2 sweep's rule of thumb: names and paths wrap on a phone.
    The notice's WHAT TO DO line alone was 1517 px wide at 390. Pinned as the
    selectors that must be released, because each one is text an editor or
    a camera wrote."""
    assert ".tree .row .nm { white-space: normal; overflow-wrap: anywhere; }" in PHONE
    assert ".tbl td, .files li .nm, .xf .file { overflow-wrap: anywhere; }" in PHONE
    assert ".tbl.stack-sm td { white-space: normal; }" in PHONE
    assert ".home-page .clip-name { overflow-wrap: anywhere; }" in _css("home.css")
