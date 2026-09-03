"""The retired words and wrong routes of the 2026-09-03 usability sweep.

Wave 0 was "the string day": no new mechanism, one commit, one scan test per
surface. This is the dashboard's scan. Every entry below is a phrase that WAS
in the product on 2026-09-03 and must not come back, with the finding id that
retired it, so a future edit that reintroduces one fails here rather than in
front of an admin:

  UX-5   every browser tab said "CC SYNC" even for a customer whose header
         said their own name
  UX-6   "Every check below ran" printed over a panel rendering [ NOT CHECKED ]
  UX-7 / REL-10  the setup wizard's next actions named pages that have not
         existed since the 2026-08-18 Settings redesign
  UX-8   two copies of the Settings page list, drifted apart by six pages
  UX-10  "(s)" in a sentence a person reads
  UX-16  four words for one thing: the product says "computer" to a person,
         and keeps "machine" for routes, form fields and the database
  UX-17  [ UP ] and [ UP ON ONE ], two of four spellings of upload-only
  DUI-7  the product's own deep links, at anchors that arrive after the scroll
  DUI-14 " -- ", the typewriter em dash the em-dash test could not see
  DUI-15 this studio's own tailnet id as a placeholder in the vendor build
  CR-88 route sweep: Copy diagnostics left the tray's right-click menu on
         2026-08-27 (KNOWN_BUGS CR-88, the ten-item layout) and lives in the
         companion's Settings window under HELP

Deliberately NOT covered: `machine` in a route, an hx-post target, a form
field, a database column or a comment. The sweep's terminology table keeps
that word exactly there.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from ccsync_dashboard import health, setup_engine, ui

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
SRC = ROOT / "src" / "ccsync_dashboard"

_JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.S)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"(?<!:)//[^\n]*")


def _visible(path: Path) -> str:
    """The file with its comments blanked, lines preserved.

    Comments are out of scope for the same reason test_no_em_dash.py puts them
    out of scope: this is a rule about PRODUCT COPY, and it must never be the
    reason someone rewrites a comment that records why the copy says what it
    says. Blanked rather than deleted so the line numbers in a failure still
    point at the file.
    """
    text = path.read_text(encoding="utf-8")

    def blank(m: re.Match) -> str:
        return "\n" * m.group(0).count("\n")

    text = _JINJA_COMMENT.sub(blank, text)
    text = _HTML_COMMENT.sub(blank, text)
    if path.suffix == ".js":
        text = _BLOCK_COMMENT.sub(blank, text)
        text = _LINE_COMMENT.sub("", text)
    return text


def _rendered_files() -> list[Path]:
    return sorted(TEMPLATES.rglob("*.html")) + sorted(STATIC.rglob("*.js"))


def _find(text: str, needle: str, source: str) -> list[str]:
    out = []
    start = 0
    while (i := text.find(needle, start)) != -1:
        line = text.count("\n", 0, i) + 1
        out.append(f"{source}:{line}")
        start = i + len(needle)
    return out


# (phrase, finding id, what to say instead). Matched case-sensitively against
# rendered template and JS copy.
RETIRED_IN_TEMPLATES: tuple[tuple[str, str, str], ...] = (
    ("{% block title %}CC SYNC", "UX-5",
     "{% block title %}{{ brand_org | upper }}"),
    ("Every check below ran", "UX-6",
     "count the checks that actually ran (_notices_context)"),
    ("[ UP ]", "UX-17", "[ UPLOAD ONLY ]"),
    ("[ UP ON ONE ]", "UX-17", "[ UPLOAD ONLY ON ONE COMPUTER ]"),
    ("tail26290e", "DUI-15", "a shape, not this studio's tailnet id"),
    ("Copy diagnostics on the tray", "CR-88",
     "{{ COMPANION_DIAGNOSTICS_PATH }}, from health.py"),
    ("Copy diagnostics\n  on their tray", "CR-88",
     "{{ COMPANION_DIAGNOSTICS_PATH }}, from health.py"),
    ("ask the editor for Copy diagnostics", "CR-88",
     "{{ COMPANION_DIAGNOSTICS_PATH }}, from health.py"),
    ("machine(s)", "UX-16 / UX-10", "computer, with the noun agreeing"),
    ("COMPUTER(S)", "UX-10", "COMPUTER{{ \"S\" if n != 1 }}"),
    ("[ ASK THIS MACHINE WHY ]", "UX-16", "[ ASK THIS COMPUTER WHY ]"),
    ("[ PUSH TO ONE MACHINE ]", "UX-16", "[ PUSH TO ONE COMPUTER ]"),
    ("[ OUT-OF-DATE MACHINES ]", "UX-16", "[ OUT-OF-DATE COMPUTERS ]"),
    ("pick a machine", "UX-16", "pick a computer"),
    ('data-label="MACHINE"', "UX-16", 'data-label="COMPUTER"'),
    ("<th>MACHINE</th>", "UX-16", "<th>COMPUTER</th>"),
    ("this machine's", "UX-16", "this computer's"),
    ("other machine(s)", "UX-16", "other computer(s), spelt out"),
)


@pytest.mark.parametrize("path", _rendered_files(), ids=lambda p: p.name)
def test_no_retired_phrase_in_rendered_copy(path: Path) -> None:
    text = _visible(path)
    hits = []
    for phrase, finding, instead in RETIRED_IN_TEMPLATES:
        for where in _find(text, phrase, path.name):
            hits.append(f"{where}: {finding} retired {phrase!r}; say {instead}")
    assert not hits, "; ".join(hits)


# The same rule for the Python that hands strings to a browser. Docstrings and
# comments are out of scope; ast never sees a comment, and the docstring nodes
# are subtracted the way test_no_em_dash.py subtracts them.
RETIRED_IN_PYTHON: tuple[tuple[str, str, str], ...] = (
    ("publish one on the Users page", "UX-7 / REL-10",
     "Settings, then PACKAGES"),
    ("page, under PUBLISHED PACKAGES", "UX-7 / REL-10",
     "the packages table is /admin/packages, not the Users page"),
    ("no editors yet: Users page", "UX-7", "Settings, then USERS"),
    ("on the Fleet page", "UX-7", "the nav calls it SYNC STATUS"),
    ("Copy diagnostics from the CC Sync tray", "CR-88",
     "health.COMPANION_DIAGNOSTICS_PATH"),
    ("shared folder(s)", "UX-10", "folder / folders, agreeing with the count"),
    ("restart CC Sync from the tray", "CR-88",
     "the ten-item menu has Quit, not Restart: quit and start it again"),
)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            out.add(id(first.value))
    return out


def _py_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


@pytest.mark.parametrize("path", _py_files(), ids=lambda p: p.name)
def test_no_retired_phrase_in_python_strings(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    skip = _docstring_nodes(tree)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skip:
            continue
        for phrase, finding, instead in RETIRED_IN_PYTHON:
            if phrase in node.value:
                hits.append(f"{path.name}:{node.lineno}: {finding} retired "
                            f"{phrase!r}; say {instead}")
    assert not hits, "; ".join(hits)


# DUI-14: the ASCII stand-in. The house rule (2026-08-18) is a spaced hyphen,
# a colon or two sentences; " -- " is none of those and renders to a reader as
# exactly the glyph the em-dash test bans.
@pytest.mark.parametrize("path", _rendered_files(), ids=lambda p: p.name)
def test_no_typewriter_em_dash_in_rendered_copy(path: Path) -> None:
    hits = _find(_visible(path), " -- ", path.name)
    assert not hits, (
        "DUI-14: ' -- ' is a typewriter em dash in copy a browser paints "
        "(house style 2026-08-18: a spaced hyphen, a colon, or two "
        "sentences): " + "; ".join(hits)
    )


def test_the_scan_would_catch_a_regression() -> None:
    """The detectors themselves, so a silent glob can never pass this file."""
    assert len(_rendered_files()) > 10
    assert len(_py_files()) > 10
    assert _find("no known editors yet -- one appears", " -- ", "x")
    assert not _find("no known editors yet: one appears", " -- ", "x")
    assert _find("{% block title %}CC SYNC: FLEET", "{% block title %}CC SYNC", "x")
    # A comment carrying a retired phrase is NOT a failure: the fix pass's own
    # comments quote what they retired.
    assert _visible(TEMPLATES / "partials" / "sidebar.html").count("[ UP ]") == 0


# ------------------------------------------------------- UX-8, one list only


def test_the_settings_pages_are_one_list() -> None:
    """UX-8: SETTINGS_PAGES is DERIVED, so a thirteenth page cannot drift.

    The drawer marked [ SETTINGS ] as current from its own six-entry copy of
    the keys while the strip rendered twelve, so six admin pages highlighted
    nothing at all in the phone drawer, under a comment asserting the two
    lists matched.
    """
    assert ui.SETTINGS_PAGES == tuple(key for key, _, _, _ in ui.SETTINGS_NAV)
    assert len(ui.SETTINGS_NAV) >= 12
    assert {"alerts", "jobs", "invariants", "protection", "recovery",
            "audit"} <= set(ui.SETTINGS_PAGES)
    assert ui.templates.env.globals["SETTINGS_NAV"] is ui.SETTINGS_NAV
    assert ui.templates.env.globals["SETTINGS_PAGES"] is ui.SETTINGS_PAGES
    # Neither template may carry a literal of its own again.
    nav = (TEMPLATES / "partials" / "settings_nav.html").read_text(encoding="utf-8")
    top = (TEMPLATES / "partials" / "topbar.html").read_text(encoding="utf-8")
    assert "{% set SETTINGS_NAV" not in nav
    assert "{% set SETTINGS_PAGES" not in top
    assert "SETTINGS_NAV" in nav and "SETTINGS_PAGES" in top


def test_every_settings_entry_names_a_route_that_exists() -> None:
    """REL-10's other half: a next action that names a page names a real one."""
    # Three routers hold these pages: ui.py, assignments.py (the matrix) and
    # setup_routes.py (the wizard). One list, so the strip cannot offer a page
    # nothing serves.
    from ccsync_dashboard import assignments as assignments_mod
    from ccsync_dashboard import setup_routes

    paths = {getattr(r, "path", None)
             for mod in (ui, assignments_mod, setup_routes)
             for r in mod.router.routes}
    for _key, _label, href, _admin in ui.SETTINGS_NAV:
        assert href in paths, f"{href} is in the Settings strip and in no route"


# --------------------------------------------------- UX-7 / REL-10, the tasks


def test_the_setup_tasks_name_pages_that_exist() -> None:
    labels = {label for _k, label, _h, _a in ui.SETTINGS_NAV}
    src = (Path(setup_engine.__file__)).read_text(encoding="utf-8")
    assert "publish one on the Users page" not in src
    assert "PACKAGES" in src and "PACKAGES" in labels
    assert "USERS" in labels


# --------------------------------------------------------------- UX-6 counts


def test_the_clean_notices_headline_counts_the_checks() -> None:
    html = (TEMPLATES / "partials" / "notices.html").read_text(encoding="utf-8")
    assert "notice_checks_ran" in html and "notice_checks_total" in html
    assert "notice_checks_never_ran" in html, (
        "UX-6: an unchecked kind has to be said out loud, not averaged away")


# ---------------------------------------------------------------- DUI-7 hash


def test_the_page_scrolls_to_a_fragment_that_arrives_late() -> None:
    """Both of the product's deep links target load-triggered panels."""
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "htmx:afterSwap" in base and "scrollIntoView" in base
    assert "location.hash" in base
    topbar = (TEMPLATES / "partials" / "topbar.html").read_text(encoding="utf-8")
    assert "/#server-notices" in topbar


# ------------------------------------------------------------ CR-88 constant


def test_the_diagnostics_path_is_one_constant() -> None:
    path = health.COMPANION_DIAGNOSTICS_PATH
    assert "Settings" in path and "Copy diagnostics" in path
    assert "tray" not in path.lower(), (
        "CR-88: the tray's right-click menu is ten items and this is not one "
        "of them")
    assert ui.templates.env.globals["COMPANION_DIAGNOSTICS_PATH"] == path
    for name in ("partials/admin_diagnostics.html", "partials/fleet_grid.html"):
        html = (TEMPLATES / name).read_text(encoding="utf-8")
        assert "COMPANION_DIAGNOSTICS_PATH" in html, name
    alerts_src = (SRC / "alerts.py").read_text(encoding="utf-8")
    assert "COMPANION_DIAGNOSTICS_PATH" in alerts_src


# ---------------------------------------------------------------- UX-10 "(s)"


def test_the_unfiltered_folders_sentence_agrees_with_its_count() -> None:
    one = health._why_sentence("folders_unfiltered", {"folders_unfiltered": 1})
    many = health._why_sentence("folders_unfiltered", {"folders_unfiltered": 3})
    assert "(s)" not in one and "(s)" not in many
    assert "1 shared folder on this computer has" in one
    assert "3 shared folders on this computer have" in many
