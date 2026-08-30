"""The admin pages at 390 px (MOBILE_PLAN.md M3, 2026-08-30).

Nothing here renders a browser: what a phone layout is made of, on this side,
is markup -- the class vocabulary of MOBILE_PLAN.md §3.2 (`.stack` with a
`data-label` per cell where a row is a record, `.scroll-x` where the columns
ARE the data, `.tap` on the controls an admin reaches for one-handed), the
htmx visibility filter on every poll, no box-drawing rules, and confirms that
fit a phone's dialog. M0's sweep is what looks at pixels; these are the
properties that make the sweep's result reproducible, and the ones that break
silently when somebody adds a row to a table a year from now.

Every page is rendered as an admin against seeded data, because an empty
table renders `no rows yet` and would pass any assertion about its cells.
"""
from __future__ import annotations

import html as htmllib
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
DASHBOARD_ROOT = Path(__file__).resolve().parents[1]

# Every admin page M3 owns. /setup is excluded by the plan; /admin/alerts/preview
# is plain text, not a page.
ADMIN_PAGES = (
    "/admin/settings",
    "/admin/users",
    "/admin/assignments",
    "/admin/packages",
    "/admin/jobs",
    "/admin/audit",
    "/admin/alerts",
    "/admin/invariants",
    "/admin/protection",
    "/admin/recovery",
)

# The partials that carry the tables, fetched on their own the way htmx fetches
# them (some of them are loaded by their own trigger and never appear in the
# page's first response).
ADMIN_PARTIALS = (
    "/partials/admin/users",
    "/partials/admin/sessions",
    "/partials/admin/report-tokens",
    "/partials/admin/packages",
    "/partials/admin/dashboard-update",
    "/partials/admin/jobs",
    "/partials/admin/audit",
)

# The confirms that are longer than a phone dialog wants and stay that way.
# Each one is CONSEQUENCE COPY from the 2026-08-28 UX sweep, pinned
# byte-for-byte by a test M3 does not own -- shortening them would either
# break that test or (worse) move the consequence out of the dialog and into
# a hover title no phone has. Named here so the exception is visible rather
# than a hole in the rule; the orchestrator decides whether they shrink.
ALLOWED_LONG_CONFIRMS = (
    "Sign yourself out of every browser",              # C-9, test_sessions.py
    "out of every browser? They will need to log in",  # C-9's other-row twin
    "report token? Their companion stops reporting",   # C-8, test_report_tokens.py
    "This build has no release signature.",            # C-4, test_packages.py
    "These are the bytes a rollback to that version",  # C-5, test_packages.py
)

# The one phone-visible property this file measures in characters. 90 is the
# plan's number: Chrome's dialog on a 390 px screen shows about that much
# before the reader has to scroll a modal to find the verb.
CONFIRM_MAX = 90

VISIBILITY_FILTER = "[document.visibilityState === 'visible']"

# Templates M3 owns, for the source-level pins.
OWNED_TEMPLATES = sorted(
    list((DASHBOARD_ROOT / "templates").glob("admin_*.html"))
    + list((DASHBOARD_ROOT / "templates" / "partials").glob("admin_*.html"))
    + [DASHBOARD_ROOT / "templates" / "partials" / "recovery.html"]
)


@pytest.fixture
def client(tmp_path):
    """An admin, a fleet with something in every table, and local accounts on
    (the appliance's own shape: no NAS credential)."""
    settings = Settings(db_path=str(tmp_path / "m3.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}), auth_method="local")
    app = create_app(settings)
    with TestClient(app) as c:
        conn = dbmod.connect(settings.db_path)
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, "2026-ff5", "2026/FF5", "/data/2026-ff5", now)
        dbmod.upsert_project(conn, "2026-drone", "2026/Drone", "/data/2026-drone", now)
        for name in ("jsmith", "editor1"):
            dbmod.record_known_editor(conn, name, source="admin", now=now)
        dbmod.upsert_machine(conn, "jsmith", "EDIT-PC", now, platform="windows")
        dbmod.upsert_machine(conn, "editor1", "LAPTOP", now, platform="macos")
        dbmod.insert_companion_package(
            conn, version="1.0.30", platform="windows",
            filename="ccsync-companion-1.0.30.exe", sha256="a" * 64,
            size_bytes=1234, published_by="owen", now=now, kind="companion")
        dbmod.create_job(conn, "peaks", {"root": "projects", "rel": "a.mov"}, {})
        dbmod.audit(conn, "owen", "plan.tick", "2026-ff5", {"editor": "jsmith"})
        dbmod.record_alert(conn, "test", "a test alert", "nobody", False, "no sink")
        dbmod.create_editor_report_token(conn, "jsmith", "owen", label="laptop")
        conn.commit()
        # A signed-in browser that is not this test's own hand-minted cookie,
        # so the sessions panel has a row to stack.
        c.app.state.session_store.create("sid-jsmith", "jsmith",
                                         client="10.0.0.9 Firefox")
        as_admin(c)
        # A local account, through the route that makes one: the page's own
        # writer, so the row is shaped the way the panel renders it.
        c.post("/api/v1/admin/users", json={"username": "newbie",
                                            "password": "correct-horse-battery"})
        yield c
        conn.close()


def as_admin(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    return client


def polls(body: str) -> list[str]:
    return [t for t in re.findall(r'hx-trigger="([^"]*)"', body) if "every" in t]


def confirms(body: str) -> list[str]:
    return [htmllib.unescape(c) for c in re.findall(r'hx-confirm="([^"]*)"', body)]


# --------------------------------------------------------------- the pages


@pytest.mark.parametrize("url", ADMIN_PAGES)
def test_every_admin_page_still_renders_for_an_admin(client, url):
    """The floor under everything below: a phone layout that 500s is not a
    layout. Rendered against seeded data, so the tables have rows."""
    resp = client.get(url)
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("url", ADMIN_PARTIALS)
def test_no_box_drawing_rule_survives_on_an_admin_partial(client, url):
    """`{{ "─" * 100 }}` is 100 glyphs wide whatever the viewport: at 390 px it
    is the single line that makes the whole document scroll sideways. The
    vocabulary's `.rule` element replaces it (MOBILE_PLAN.md §3.2).

    Partials, not pages: base.html carries a rule of its own and is M1's."""
    body = client.get(url).text
    assert "─" not in body
    assert "━" not in body


def test_no_box_drawing_rule_is_left_in_a_template_m3_owns():
    """The source twin of the test above, so a partial that renders empty on
    this fixture's data cannot hide one."""
    for path in OWNED_TEMPLATES:
        assert "─" not in path.read_text(encoding="utf-8"), path.name


def test_every_poll_m3_owns_stops_while_the_page_is_hidden():
    """A phone in a pocket holding a 30 s poll is a connection the base rig's
    editors share, against --workers 1. htmx 1.9's trigger filter is the cheap
    half of the fix (M4's pwa.js is the belt).

    Read from the source rather than a render because these live on the page
    templates' own `<aside>` and wrapper divs, and because the sixteen of them
    is the number that has to stay right."""
    seen = 0
    for path in OWNED_TEMPLATES:
        for trigger in polls(path.read_text(encoding="utf-8")):
            seen += 1
            assert VISIBILITY_FILTER in trigger, (path.name, trigger)
    assert seen == 16, seen


@pytest.mark.parametrize("url", ADMIN_PARTIALS)
def test_every_poll_a_partial_renders_carries_the_filter(client, url):
    body = client.get(url).text
    for trigger in polls(body):
        assert VISIBILITY_FILTER in trigger, (url, trigger)


@pytest.mark.parametrize("url", ADMIN_PAGES + ADMIN_PARTIALS)
def test_confirms_fit_a_phone_dialog(client, url):
    """A 300-character confirm on a phone is a confirm nobody reads, which is
    the same as no confirm at all. The consequence copy the sweep wrote is
    kept -- as the button's title, or (for the five named above) as itself."""
    for text in confirms(client.get(url).text):
        if any(text.startswith(a) or a in text for a in ALLOWED_LONG_CONFIRMS):
            continue
        assert len(text) <= CONFIRM_MAX, (url, len(text), text)


@pytest.mark.parametrize("url", ADMIN_PAGES + ADMIN_PARTIALS)
def test_no_confirm_was_emptied_instead_of_shortened(client, url):
    """The lazy way to pass the test above. A confirm that lost its question
    is a worse regression than a long one."""
    for text in confirms(client.get(url).text):
        assert len(text) >= 20, (url, text)
        assert "?" in text, (url, text)


# --------------------------------------------------- .stack and data-label


STACKED = {
    "/partials/admin/jobs": ("JOB", "KIND", "STATE", "WHERE", "PROGRESS", "AGE", "WHY"),
    "/partials/admin/users": ("USERNAME", "ROLE", "STATUS", "SSH KEYS",
                              "EDITOR", "MACHINE", "PLATFORM", "LAST REPORT"),
    "/partials/admin/sessions": ("USERNAME", "SIGNED IN", "LAST SEEN", "FROM"),
    "/partials/admin/report-tokens": ("EDITOR", "LABEL", "CREATED", "LAST USED"),
    "/partials/admin/packages": ("KIND", "VERSION", "PLATFORM", "SIZE", "SHA256",
                                 "PUBLISHED", "BY"),
    "/partials/admin/audit": ("WHEN", "WHO", "ACTION", "SUBJECT", "DETAIL"),
}


@pytest.mark.parametrize("url", sorted(STACKED))
def test_the_record_tables_stack_with_a_label_on_every_cell(client, url):
    """`.stack` turns a `tr` into a block and a `td` into a labelled line, so
    a row that is one job / one computer / one build reads down the phone
    instead of off the side of it. A cell with no `data-label` renders bare,
    which is why the labels are pinned per table rather than counted."""
    body = client.get(url).text
    assert 'class="editors stack"' in body, url
    for label in STACKED[url]:
        assert f'data-label="{label}"' in body, (url, label)


def test_every_editors_table_m3_owns_is_stacked_or_deliberately_not(client):
    """The pin that catches the table added next year. `table class="editors"`
    with no `stack` is a nine-column grid at 390 px; the two exceptions are
    recovery's label/prose pairs, which are already what `.stack` would make
    of them."""
    plain = []
    for path in OWNED_TEMPLATES:
        text = path.read_text(encoding="utf-8")
        for tag in re.findall(r'<table class="editors[^"]*"', text):
            if "stack" not in tag:
                plain.append(path.name)
    assert plain == ["recovery.html", "recovery.html"], plain


def test_the_jobs_cancel_and_the_session_revoke_are_tap_targets(client):
    """The two controls MOBILE_PLAN.md §4 M3 names: the ones an admin opens a
    phone FOR. `.tap` is the vocabulary's explicit hit box; `.btn` gets one
    automatically under `(pointer: coarse)`, so this is belt and braces on
    the two that matter."""
    jobs = client.get("/partials/admin/jobs").text
    assert '<button class="btn tap" type="submit"' in jobs
    assert "[ CANCEL ]" in jobs
    sessions = client.get("/partials/admin/sessions").text
    assert '<button class="btn tap" type="submit">[ REVOKE ALL ]</button>' in sessions


# ------------------------------------------------------- the matrix, sideways


def test_the_assignments_matrix_scrolls_sideways_inside_itself(client):
    """The one admin surface that does NOT stack: one column per computer is
    what the page is for, and stacking it would lose the comparison. `.scroll-x`
    keeps the scrolling inside the element, and the project name stays pinned
    to the left edge while it moves."""
    body = client.get("/admin/assignments").text
    assert 'class="assign-scroll scroll-x"' in body
    assert 'class="assign-project"' in body          # the sticky column, per row
    assert 'class="assign-project-head"' in body


def test_the_matrix_phone_rules_live_in_m3s_own_css_section():
    """style.css is M1's file, so the phone override for a grid whose desktop
    rules live there is written here instead, with a more specific selector."""
    css = (DASHBOARD_ROOT / "static" / "mobile.css").read_text(encoding="utf-8")
    admin = css.split("== admin ==")[1]
    assert ".assign-scroll table.assign-grid td.assign-project" in admin
    assert ".assign-colbtns" in admin
    # 10px was the smallest hit box in the product, on the densest grid in it.
    assert "font-size: 12px" in admin
    assert "min-height: var(--tap)" in admin


def test_the_forms_are_one_column_with_16px_inputs_on_a_phone():
    """16 px is the number below which Android and iOS zoom the page when a
    field takes focus, which leaves the reader scrolled sideways."""
    css = (DASHBOARD_ROOT / "static" / "mobile.css").read_text(encoding="utf-8")
    admin = css.split("== admin ==")[1].split("== end ==")[0]
    assert "@media (max-width: 600px)" in admin
    assert "font-size: 16px" in admin
    # .ai-key input {min-width: 22rem} is 352px inside a 390px screen.
    assert ".ai-key input { min-width: 0; width: 100%; }" in admin


def test_m3_wrote_only_in_its_own_section_of_mobile_css():
    """The file has two owners and no merge tool; the marker is the contract."""
    css = (DASHBOARD_ROOT / "static" / "mobile.css").read_text(encoding="utf-8")
    fleet = css.split("== fleet ==")[1].split("== admin ==")[0]
    assert "assign" not in fleet
    assert "ai-key" not in fleet


def test_no_em_dash_in_what_m3_wrote():
    """CLAUDE.md's rule, checked on M3's own files rather than waiting for
    test_no_em_dash.py to scan product copy."""
    for path in OWNED_TEMPLATES + [DASHBOARD_ROOT / "static" / "mobile.css",
                                   Path(__file__)]:
        # chr(0x2014), spelled out so this file does not carry one either.
        assert chr(0x2014) not in path.read_text(encoding="utf-8"), path.name
