"""The admin pages at 390 px (MOBILE_PLAN.md M3, 2026-08-30).

Nothing here renders a browser: what a phone layout is made of, on this side,
is markup -- the class vocabulary of MOBILE_PLAN.md §3.2 (a stacking table
with a `data-label` per cell where a row is a record, `.scroll-x` where the
columns ARE the data, a tap-sized hit box on the controls an admin reaches
for one-handed), the htmx visibility filter on every poll, no box-drawing
rules, and confirms that fit a phone's dialog.

The terminal look is the only look since 2026-09-25 (docs/UI_PORT_LEDGER/
C-collapse.md): the classic vocabulary (`table.editors.stack`, `.btn.tap`,
`static/mobile.css`) is gone, and every pin below reads the terminal one
(`table.tbl.stack-sm`, `.key` under `(pointer: coarse)`, `static/cc/phone.css`)
for the SAME property the classic pin guarded. M0's sweep is what looks at pixels; these are the
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
PHONE_CSS = DASHBOARD_ROOT / "static" / "cc" / "phone.css"
COMPONENTS_CSS = DASHBOARD_ROOT / "static" / "cc" / "components.css"
TERMINAL_CSS = DASHBOARD_ROOT / "static" / "cc" / "terminal.css"

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
    "out of every browser? They will need to sign in",  # C-9's other-row twin (ui-copy-7: was "log in")
    "report token? Their companion stops reporting",   # C-8, test_report_tokens.py
    "This build has no release signature.",            # C-4, test_packages.py
    # C-5, test_packages.py. The terminal port (P4a) made it true: a delete
    # goes to the trash for 30 days first (api._trash_package_file).
    "It goes to the trash on this server for 30 days.",
)

# The one phone-visible property this file measures in characters. 90 is the
# plan's number: Chrome's dialog on a 390 px screen shows about that much
# before the reader has to scroll a modal to find the verb.
CONFIRM_MAX = 90

VISIBILITY_FILTER = "[document.visibilityState === 'visible']"

# Templates M3 owns, for the source-level pins. The last three came over in
# round 2 of the sweep (2026-08-30): they are the BODIES of admin pages M3
# owns, they were nobody's in §3.3, and they were the widest thing in the
# product at 390 px (admin-protection was 1683 px).
OWNED_TEMPLATES = sorted(
    list((DASHBOARD_ROOT / "templates").glob("admin_*.html"))
    + list((DASHBOARD_ROOT / "templates" / "partials").glob("admin_*.html"))
    + [DASHBOARD_ROOT / "templates" / "partials" / "recovery.html",
       DASHBOARD_ROOT / "templates" / "partials" / "invariant_checks.html",
       DASHBOARD_ROOT / "templates" / "partials" / "protection.html",
       # collector_health.html's terminal successor (the Health tab's
       # collector window; the classic partial is gone).
       DASHBOARD_ROOT / "templates" / "partials" / "health_collector.html"]
)

# A box-drawing RULE: a run of these glyphs, literal or as an entity. The
# terminal window bar's corner ornaments are three fixed glyphs (aria-hidden);
# a rule is what grows with the text, so four or more in a row, or a Jinja
# multiplication of one, is what is refused.
_BOX = r"(?:[\u2500-\u257f]|&#(?:94[7-9][0-9]|95[0-9][0-9]);|&#x25[0-7][0-9a-fA-F];)"
BOX_RULE = re.compile(_BOX + r"{4,}|[\"'][\u2500-\u257f][\"']\s*\*")


def css_rule(css: str, selector: str) -> str:
    """Every declaration block whose selector list carries EXACTLY this
    selector, joined (comments stripped first)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    blocks = [m.group(2) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
              if any(p.strip() == selector for p in m.group(1).split(","))]
    assert blocks, f"no rule for {selector}"
    return "\n".join(blocks)


def media_block(css: str, query: str) -> str:
    """The bodies of every `@media <query>` block, joined (one level of
    nesting, which is all these sheets use)."""
    out, i = [], 0
    while True:
        i = css.find("@media " + query, i)
        if i < 0:
            return "\n".join(out)
        j = css.index("{", i) + 1
        depth, k = 1, j
        while depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        out.append(css[j:k - 1])
        i = k


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

    Partials, not pages, as before: the shell's own chrome is M1's."""
    body = client.get(url).text
    hit = BOX_RULE.search(body)
    assert hit is None, hit and hit.group(0)
    assert "━" not in body


def test_no_box_drawing_rule_is_left_in_a_template_m3_owns():
    """The source twin of the test above, so a partial that renders empty on
    this fixture's data cannot hide one."""
    for path in OWNED_TEMPLATES:
        hit = BOX_RULE.search(path.read_text(encoding="utf-8"))
        assert hit is None, (path.name, hit and hit.group(0))


def test_every_poll_m3_owns_stops_while_the_page_is_hidden():
    """A phone in a pocket holding a 30 s poll is a connection the base rig's
    editors share, against --workers 1. htmx 1.9's trigger filter is the cheap
    half of the fix (M4's pwa.js is the belt).

    Read from the source rather than a render because these live on the page
    templates' own wrapper divs, and because the count of them is the number
    that has to stay right. Six since the terminal look became the only one
    (2026-09-25): eleven of the classic seventeen were the 30 s sidebar poll
    each classic admin page carried, and the terminal pages have no sidebar
    (D17). What is left: the packages panel, the users page's four panels
    and the jobs queue."""
    seen = 0
    for path in OWNED_TEMPLATES:
        for trigger in polls(path.read_text(encoding="utf-8")):
            seen += 1
            assert VISIBILITY_FILTER in trigger, (path.name, trigger)
    assert seen == 6, seen


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


# The terminal look's labels are lower case (the phone sheet upper-cases them
# with text-transform). The jobs table's WHY is its own full-width row under
# the job (`tr.why-row`, `data-label=""`, pinned below) rather than a cell.
STACKED = {
    "/partials/admin/jobs": ("job", "kind", "state", "where", "progress", "age"),
    "/partials/admin/users": ("username", "role", "status", "ssh keys",
                              "editor", "computer", "platform", "last report"),  # UX-16
    "/partials/admin/sessions": ("username", "signed in", "last seen", "from"),
    "/partials/admin/report-tokens": ("editor", "label", "created", "last used"),
    # KIND and PLATFORM are HEADINGS on this panel since 2026-09-11, not
    # columns: the page groups companion/onboard and windows/macos rather
    # than repeating both on every row. What is left is the row itself, plus
    # the out-of-date computers table below it.
    "/partials/admin/packages": ("version", "published", "size"),
    "/partials/admin/audit": ("when", "who", "action", "subject", "detail"),
}


@pytest.mark.parametrize("url", sorted(STACKED))
def test_the_record_tables_stack_with_a_label_on_every_cell(client, url):
    """`.stack-sm` turns a `tr` into a block and a `td` into a labelled line,
    so a row that is one job / one computer / one build reads down the phone
    instead of off the side of it. A cell with no `data-label` renders bare,
    which is why the labels are pinned per table rather than counted."""
    body = client.get(url).text
    # A pattern, not the whole attribute: some tables carry a role class
    # (.jobs, .pkg, .ood) between `tbl` and `stack-sm`.
    assert re.search(r'<table class="tbl[^"]*\bstack-sm\b', body), url
    for label in STACKED[url]:
        assert f'data-label="{label}"' in body, (url, label)
    if url == "/partials/admin/jobs":
        assert '<tr class="why-row"><td colspan="7" data-label="">' in body
    # ...and the phone sheet is what turns the attribute into a label.
    phone = media_block(PHONE_CSS.read_text(encoding="utf-8"), "(max-width: 760px)")
    assert ".tbl.stack-sm thead { display: none; }" in phone
    assert "content: attr(data-label)" in phone


def test_every_editors_table_m3_owns_stacks(client):
    """The pin that catches the table added next year. `table class="tbl"`
    with no `stack-sm` is a nine-column grid at 390 px.

    The one table that is not a `.tbl` is the assignments matrix (`.mx`),
    which scrolls sideways on purpose (pinned below); every other table in
    these templates must be a stacking `.tbl`."""
    plain = []
    for path in OWNED_TEMPLATES:
        body = path.read_text(encoding="utf-8")
        for tag in re.findall(r'<table\b[^>]*>', body):
            if 'class="mx assign-grid"' in tag:
                continue
            if not re.search(r'class="tbl\b[^"]*\bstack-sm\b', tag):
                plain.append((path.name, tag))
    assert plain == [], plain


def test_every_table_m3_owns_is_wrapped_in_a_scroll_x(client):
    """768 px is not the phone query: `.stack` does not apply there and every
    one of these is a real table again, wider than the column it sits in. The
    wrapper is a DIV (M1's rule: `.scroll-x` never goes on the table itself),
    and the sweep exempts an element from "content scrolls sideways" only if
    it carries the class or is inside something that does."""
    unwrapped = []
    for path in OWNED_TEMPLATES:
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            at = line.find("<table")
            if at < 0:
                continue
            if "assign-grid" in line:              # its own wrapper, see below
                continue
            # The terminal templates put the wrapper on the same line
            # (`<div class="scroll-x"><table`) or the line above.
            before = line[:at] if line[:at].strip() else (lines[i - 1] if i else "")
            if not re.search(r'<div class="scroll-x">\s*$', before):
                unwrapped.append((path.name, line.strip()[:60]))
    assert unwrapped == [], unwrapped
    assert "overflow-x: auto" in css_rule(
        COMPONENTS_CSS.read_text(encoding="utf-8"), ".scroll-x")


def test_the_assignments_grid_keeps_its_own_wrapper(client):
    """The one table whose wrapper is not the one above: it has its own
    scroller (`.mx-wrap`, overflow on both axes, header and project column
    sticky), and a `.scroll-x` nested inside it would be a second
    scrollbar."""
    page = (DASHBOARD_ROOT / "templates" / "admin_assignments.html").read_text(
        encoding="utf-8")
    assert 'class="mx-wrap assign-scroll"' in page
    assert page.count('<table class="mx assign-grid"') == 1
    assert "overflow: auto" in css_rule(
        COMPONENTS_CSS.read_text(encoding="utf-8"), ".mx-wrap")


INHERITED = {
    "/admin/invariants": "invariant-table",
    "/admin/protection": "protection-table",
}


@pytest.mark.parametrize("url", sorted(INHERITED))
def test_the_two_bodies_m3_inherited_stack_too(client, url):
    """`invariant_checks.html` and `protection.html` are the lists these two
    pages ARE, and §3.3 gave them to nobody: at 390 px the classic tables were
    1347 px and 1683 px wide. The terminal look draws them as `.vd` verdict
    rows (a grid, not a table); on a phone the grid folds to one column with
    the verdict tag and its time on the first line and the title, detail and
    what-to-do below at full width."""
    body = client.get(url).text
    ident = INHERITED[url]
    assert f'id="{ident}"' in body
    assert "<table" not in body.split(f'id="{ident}"', 1)[1].split("</section>", 1)[0]
    assert '<div class="vd' in body
    phone = media_block(PHONE_CSS.read_text(encoding="utf-8"), "(max-width: 760px)")
    assert ".vd, .vd.no-when { grid-template-columns: minmax(0, 1fr) auto; }" in phone
    assert ".vd .ti, .vd .more { grid-column: 1 / -1; }" in phone


def test_the_rules_in_the_inherited_partials_are_elements_now(client):
    """`collector_health.html` and `admin_diagnostics.html` were the last two
    `{{ "-" * 100 }}` rules in the product (spelled with a box-drawing
    character). Their terminal successors, the Health tab's collector and
    diagnostics bodies, carry no rule of their own: each is drawn inside a
    window whose bar holds the rule as an element (`.bar-rule`)."""
    for name in ("health_collector.html", "health_diagnostics.html"):
        body = (DASHBOARD_ROOT / "templates" / "partials" / name).read_text(
            encoding="utf-8")
        assert BOX_RULE.search(body) is None, name
        assert "─" not in body, name
    health = (DASHBOARD_ROOT / "templates" / "admin_health.html").read_text(
        encoding="utf-8")
    for body_id in ("health-collector-body", "health-diagnostics-body"):
        bar = health.split(f'id="{body_id}"', 1)[0].rsplit('<div class="bar">', 1)[1]
        assert '<span class="bar-rule"></span>' in bar, body_id


def test_the_fleet_halt_reason_box_fits_a_phone(client):
    """The last 8 px of overflow on /admin/users, and the one thing on it that
    no stylesheet could fix: an INLINE `min-width: 24rem` (384 px) on the
    input, which beats every rule in every file. The terminal box has no
    inline width at all; its sheet lets it grow from 28ch and shrink to
    nothing. partials/fleet_halt.html is not in §3.3's list either; it
    renders on an admin page M3 owns."""
    body = (DASHBOARD_ROOT / "templates" / "partials" / "fleet_halt.html"
            ).read_text(encoding="utf-8")
    tag = re.search(r'<input class="inp sp-halt-why"[^>]*>', body).group(0)
    assert "style=" not in tag
    assert "min-width:24rem" not in body
    css = (DASHBOARD_ROOT / "static" / "cc" / "settings_people.css").read_text(
        encoding="utf-8")
    assert "min-width: 0" in css_rule(css, ".sp-halt-why")


def test_the_jobs_cancel_and_the_session_revoke_are_tap_targets(client):
    """The two controls MOBILE_PLAN.md §4 M3 names: the ones an admin opens a
    phone FOR. In the terminal look every `.key` IS the hit box: under
    `(pointer: coarse)` it gets `min-height: var(--tap)` (44 px), so what is
    pinned is that both are real `.key` submit buttons, and that rule."""
    jobs = client.get("/partials/admin/jobs").text
    assert re.search(r'<button class="key sm w-9" type="submit"[^>]*>'
                     r'<span class="t">cancel</span>', jobs)
    sessions = client.get("/partials/admin/sessions").text
    assert ('<button class="key sm" type="submit"><span class="t">revoke all'
            '</span></button>') in sessions
    coarse = media_block(PHONE_CSS.read_text(encoding="utf-8"), "(pointer: coarse)")
    first = coarse.split("{", 1)[0]
    assert re.match(r"\s*\.key,", first)
    assert "min-height: var(--tap)" in coarse
    assert "--tap: 44px" in TERMINAL_CSS.read_text(encoding="utf-8")


# ------------------------------------------------------- the matrix, sideways


def test_the_assignments_matrix_scrolls_sideways_inside_itself(client):
    """The one admin surface that does NOT stack: one column per computer is
    what the page is for, and stacking it would lose the comparison. The
    wrapper keeps the scrolling inside the element, and the project name
    stays pinned to the left edge while it moves."""
    # With its two pickers answered (2026-09-11): the grid is per person and
    # per computer now, and the sideways scroll is what that grid still does.
    body = client.get("/admin/assignments?editor=jsmith&machine=EDIT-PC").text
    assert 'class="mx-wrap assign-scroll"' in body
    assert 'class="pcol assign-project"' in body          # the sticky column, per row
    assert 'class="pcol assign-project-head"' in body
    pcol = css_rule(COMPONENTS_CSS.read_text(encoding="utf-8"), ".mx .pcol")
    assert "position: sticky" in pcol and "left: 0" in pcol


def test_the_matrix_phone_rules_live_in_the_phone_sheet():
    """The phone override for the grid lives in the one phone sheet
    (cc/phone.css), under the same 760 px query as every other phone rule:
    the sticky project column narrows so a computer's column is still on
    screen beside it, the grid's small text is lifted to the 12 px floor,
    and the column tools (keys and the copy-from select) are thumb-sized on
    a coarse pointer."""
    css = PHONE_CSS.read_text(encoding="utf-8")
    phone = media_block(css, "(max-width: 760px)")
    assert ".mx .pcol { min-width: 132px; max-width: 150px; }" in phone
    assert ".mx .ch .tools .sel.sm { width: 100%; }" in phone
    floor = phone.split("the 12px floor", 1)[1]
    for sel in (".mx thead .pcol", ".mx .pname .sz", ".mx .ch .who", ".upm"):
        assert sel in floor, sel
    assert "font-size: 12px" in floor
    coarse = media_block(css, "(pointer: coarse)")
    # `.key` and `.sel` are the column tools (`.tools.assign-colbtns`).
    assert ".key," in coarse and ".sel" in coarse
    assert "min-height: var(--tap)" in coarse


def test_the_forms_are_one_column_with_16px_inputs_on_a_phone():
    """16 px is the number below which Android and iOS zoom the page when a
    field takes focus, which leaves the reader scrolled sideways."""
    css = PHONE_CSS.read_text(encoding="utf-8")
    phone = media_block(css, "(max-width: 760px)")
    assert "font-size: 16px" in phone
    # It must be the LAST phone rule, so no smaller field rule beats it.
    assert css.replace("\r\n", "\n").rstrip().endswith("font-size: 16px; }\n}")
    # The AI key box (the provider wizard's `.ctl .inp`) has no min width to
    # push past a 390 px screen, and its select is released on a phone
    # (classic's `.ai-key input {min-width: 22rem}` was 352 px).
    comp = COMPONENTS_CSS.read_text(encoding="utf-8")
    assert "min-width" not in css_rule(comp, ".wz-body .ctl .inp")
    assert ".wz-body .ctl .sel { min-width: 0; width: 100%; }" in phone


def test_the_sentences_in_a_stacked_cell_may_wrap():
    """Round 2's single biggest finding: one unbreakable line of prose (a
    job's per-machine why, an invariant's detail, a protection line's WHAT TO
    DO) was what made five admin pages scroll sideways at 390 px. In the
    terminal sheets a stacked cell wraps, any table cell may break a long
    token, and the prose blocks carry no nowrap."""
    phone = media_block(PHONE_CSS.read_text(encoding="utf-8"), "(max-width: 760px)")
    assert ".tbl.stack-sm td { white-space: normal; }" in phone
    assert ".tbl td, .files li .nm, .xf .file { overflow-wrap: anywhere; }" in phone
    comp = COMPONENTS_CSS.read_text(encoding="utf-8")
    assert "overflow-wrap: anywhere" in css_rule(comp, ".vd .subj")
    for sel in (".vd .cq", ".vd .dt", ".vd .fix", ".job-why"):
        assert "nowrap" not in css_rule(comp, sel), sel
    people = (DASHBOARD_ROOT / "static" / "cc" / "settings_people.css").read_text(
        encoding="utf-8")
    assert "overflow-wrap: anywhere" in css_rule(people, ".sp-path")
    assert "overflow-wrap: anywhere" in css_rule(people, ".sp-why")


def test_the_site_settings_grid_is_one_column_on_a_phone():
    """Every site setting is a `.form-row`: 220 px of caption beside the field
    on a desktop, which is 493 px on a 390 px screen. Below 1100 px it is one
    column, caption above field."""
    page = (DASHBOARD_ROOT / "templates" / "admin_settings.html").read_text(
        encoding="utf-8")
    field = page.split("{% macro field(key) %}", 1)[1].split("{% endmacro %}", 1)[0]
    assert '<div class="form-row">' in field
    comp = COMPONENTS_CSS.read_text(encoding="utf-8")
    narrow = media_block(comp, "(max-width: 1100px)")
    assert ".form-row { grid-template-columns: minmax(0, 1fr); gap: 6px; }" in narrow


def test_the_upload_only_label_is_a_thumb_target():
    """The sweep measured the upload-only label at 20 px. It is a control (it
    writes upload-only for one project on one computer), and it is the LABEL
    that has to grow: the whole word is what a thumb lands on. The tick
    beside it is a `.check`, which the same rule already covers."""
    page = (DASHBOARD_ROOT / "templates" / "admin_assignments.html").read_text(
        encoding="utf-8")
    assert '<label class="assign-upmode upm' in page
    assert '<label class="check sp-tick">' in page
    coarse = media_block(PHONE_CSS.read_text(encoding="utf-8"), "(pointer: coarse)")
    assert "label.upm { min-height: var(--tap);" in coarse
    assert ".check," in coarse
    assert coarse.count("min-height: var(--tap)") >= 2


def test_no_em_dash_in_what_m3_wrote():
    """CLAUDE.md's rule, checked on M3's own files rather than waiting for
    test_no_em_dash.py to scan product copy."""
    for path in OWNED_TEMPLATES + [PHONE_CSS, Path(__file__)]:
        # chr(0x2014), spelled out so this file does not carry one either.
        assert chr(0x2014) not in path.read_text(encoding="utf-8"), path.name
