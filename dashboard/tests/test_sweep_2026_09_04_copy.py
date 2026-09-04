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
    # DUI-8 (wave 5, 2026-09-04): a repo script and a file on an editor's own
    # computer, in copy an appliance customer reads. Neither exists for a
    # customer with no checkout, and device approval has been a button on
    # Settings, USERS since long before this copy was written.
    ("accept_device.py", "DUI-8", "Approve it on Settings, then USERS"),
    ("~/.ccsync/config.toml", "DUI-8",
     "who to send it to; nothing on that computer offers a box to paste it into"),
    ("DASH_RELEASE_FEED_URL", "DUI-8",
     "ask whoever installed this server: it is a container setting"),
    ("DASH_SHARED_REPORT_TOKEN_ENABLED", "DUI-8",
     "ask whoever installed this server: it is a container setting"),
    ("DASH_ENFORCE_MAX_REMOVALS", "DUI-8",
     "ask whoever installed this server: it is a container setting"),
    ("server/setup_tree.py", "DUI-8",
     "ask whoever installed this server: it is a container setting"),
    ("server/install_dashboard_app.py", "DUI-8",
     "ask whoever installed this server to move it onto the update channel"),
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


# ------------------------------------------- CR-181: one vocabulary, in Python
#
# Wave 4 of the same sweep (2026-09-04, USABILITY_RESILIENCE_SWEEP section 4).
# The phrase list above catches a sentence somebody already wrote; this catches
# the NEXT one. Every word below was in this dashboard's copy on 2026-09-03 and
# has one replacement:
#
#   lane            -> upload / proxy download / folder sync
#   machine, rig    -> computer ("device" only for a Syncthing identity)
#   halted, parked  -> paused (you did it) / stopped by your admin (a fleet
#   breaker            halt) / stopped itself (the proxy-download brake, the
#                      disk floor)
#   selection       -> tick (the verb), sync plan (the set for one computer)
#   assignment
#
# THE CODE KEEPS ITS NAMES. `selections` is still the table, `machine` is still
# the column, the route segment and the form field, `fleet_halt` / `disk_park`
# / `breaker_tripped` are still the kind ids, and `lane_report_current` is
# still where a transfer's state is read from. So this scan looks only at
# strings that reach a person: SQL, log and `execute` arguments, docstrings,
# route paths and single-word constants (a key, a column, a state) are all out
# of scope, and everything else that is left is listed with its reason.
VOCABULARY_FILES: tuple[str, ...] = (
    "alerts.py", "api.py", "collector.py", "db.py", "health.py",
    "invariants.py", "jobs.py", "notices.py", "protection.py",
    "setup_engine.py", "setup_routes.py",
    # CR-179 (wave 4): ui.py is where the chip explanations and every htmx
    # refusal live, so it belongs in the same scan as the modules above.
    "ui.py",
)

RETIRED_WORDS: dict[str, str] = {
    "lane": "upload / proxy download / folder sync",
    "lanes": "upload / proxy download / folder sync",
    "machine": "computer",
    "machines": "computers",
    "machine's": "computer's",
    "rig": "computer",
    "rigs": "computers",
    "halt": "stop",
    "halts": "stops",
    "halted": "stopped by your admin (a fleet halt) or stopped itself",
    "park": "stop",
    "parked": "stopped itself",
    "breaker": "proxy download stopped itself",
    "breakers": "brakes that stopped themselves",
    "selection": "tick",
    "selections": "sync plan",
    "assignment": "sync plan",
    "assignments": "sync plans",
}

# (file or "", fragment, why it is allowed). A fragment matches by substring,
# and "" matches any of the files above. EVERY entry is a place the retired
# word is NOT copy. Some fire only if the sentence around them is re-wrapped
# (a file name that shares a string literal with a space): they are here so
# that reflowing a paragraph is never what turns this scan red. An identifier
# needs no entry - `machine_state` and `lane_report_current` are one word to
# the matcher below, on purpose.
VOCABULARY_ALLOWED: tuple[tuple[str, str, str], ...] = (
    ("api.py", "machine must not be blank",
     "the validation message for the FORM FIELD named `machine`; the field, "
     "the route segment and the column all keep that name on purpose"),
    ("api.py", ".ccsync/machine.json",
     "a file name on the editor's disk: the bytes, not a word"),
    ("notices.py", ".ccsync/machine.json", "the same file name"),
    ("invariants.py", ".ccsync/machine.json", "the same file name"),
    ("alerts.py", "[ MOVE ON THE SERVER AND ON EVERY MACHINE ]",
     "quoting a button LABEL back to the reader; the label lives in the "
     "templates and is renamed there or nowhere"),
    ("notices.py", "[ MOVE ON THE SERVER AND ON EVERY MACHINE ]",
     "the same button label"),
    ("alerts.py", "[ RELEASE THE HALT ]", "the same: a button label, quoted"),
    ("ui.py", "{lane} on this computer made no progress",
     "the PLACEHOLDER is called lane; what is substituted into it is "
     "ui.lane_word(...), so the sentence a person reads begins "
     "'proxy download on this computer made no progress'"),
)


def _sql_like(value: str) -> bool:
    """SQL, including the FRAGMENTS the query builders concatenate.

    `" AND s.machine = ?"` carries no keyword this would recognise and is
    still not a sentence anybody reads, so a placeholder counts too.
    """
    upper = value.upper()
    if "?" in value and ("=?" in value.replace(" ", "") or " IN (" in upper):
        return True
    return any(word in upper for word in (
        "SELECT ", "INSERT ", "UPDATE ", "DELETE ", "CREATE TABLE",
        "CREATE INDEX", "ALTER TABLE", "GROUP BY", "ORDER BY", "WHERE ",
        " AND ", " JOIN "))


def _log_call_constants(tree: ast.AST) -> set[int]:
    """Constants inside a log or a database call. Out of scope by the same
    rule as a comment: these are for us, not for the person the sweep is
    about."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name in {"debug", "info", "warning", "warn", "error", "exception",
                    "critical", "execute", "executemany", "executescript"}:
            for child in ast.walk(node):
                if isinstance(child, ast.Constant):
                    out.add(id(child))
    return out


# `_` is part of a word here on purpose: `machine_state` and
# `lane_report_current` are identifiers a sentence may name, and only the bare
# word is the copy problem.
_WORD = re.compile(r"[A-Za-z][A-Za-z_']*")


def _retired_words_in(value: str) -> list[str]:
    return sorted({w.lower() for w in _WORD.findall(value)
                   if w.lower() in RETIRED_WORDS})


def _allowed(name: str, value: str) -> bool:
    return any((not where or where == name) and fragment in value
               for where, fragment, _why in VOCABULARY_ALLOWED)


@pytest.mark.parametrize("name", VOCABULARY_FILES)
def test_no_retired_word_in_python_copy(name: str) -> None:
    path = SRC / name
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    skip = _docstring_nodes(tree) | _log_call_constants(tree)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skip:
            continue
        value = node.value
        # A key, a column, a state, a route: not a sentence.
        if " " not in value.strip() or value.startswith("/"):
            continue
        if _sql_like(value) or _allowed(name, value):
            continue
        for word in _retired_words_in(value):
            hits.append(f"{name}:{node.lineno}: CR-181 retired {word!r} "
                        f"(say {RETIRED_WORDS[word]}) in {value[:80]!r}")
    assert not hits, "; ".join(hits)


def test_the_vocabulary_scan_would_catch_a_regression() -> None:
    """The detector itself, so a silent glob can never pass this file."""
    assert _retired_words_in("this machine is halted") == ["halted", "machine"]
    assert _retired_words_in("this computer stopped itself") == []
    # A word inside a longer one is not a hit: `machine_state` and
    # `lane_report_current` are table names and must stay sayable.
    assert _retired_words_in("the machine_state row") == []
    assert _sql_like("SELECT machine FROM machines")
    assert _sql_like(" AND s.machine = ?")
    assert not _sql_like("this computer is busy indexing b-roll")
    assert _allowed("api.py", "machine must not be blank")
    assert not _allowed("jobs.py", "this machine is cooling down")


# --------------------------- CR-179: one vocabulary, in the templates and JS
#
# The other half of CR-181's scan (wave 4, USABILITY_RESILIENCE_SWEEP section
# 4). Same word list, same rule -- the code keeps its names -- applied to what
# a browser paints. It is deliberately narrow about what "visible" means,
# because the terminology table's whole point is that `machine` stays exactly
# where it is in routes, form fields, hx-post targets, data- attributes, CSS
# classes and Jinja expressions:
#
#   * text OUTSIDE any tag, with {{ ... }} and {% ... %} removed first
#     (a Jinja expression is code, and `assignments.columns` is a view model);
#   * the values of the attributes a person actually reads -- title,
#     placeholder, aria-label, alt, hx-confirm, and nothing else;
#   * every string literal in our own JS.
#
# So `data-machine="{{ c.machine }}"` is invisible to this scan and
# `title="pick a machine"` is not, which is the line the sweep drew.
VISIBLE_ATTRS = ("title", "placeholder", "aria-label", "alt", "hx-confirm")

_JINJA_EXPR = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
_TAG = re.compile(r"<[^>]*>", re.S)
# An inline <script> or <style> in a template is CODE, and its `//`
# comments are not HTML comments, so _visible cannot blank them. Our own
# JS files are scanned as JS below; the inline blocks are behaviour.
_INLINE_CODE_BLOCK = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)

_ATTR = re.compile(
    r"\b(" + "|".join(VISIBLE_ATTRS) + r")\s*=\s*(\"([^\"]*)\"|'([^']*)')", re.S)
_JS_STRING = re.compile("\"([^\"\\\\\\n]*(?:\\\\.[^\"\\\\\\n]*)*)\""
                        "|'([^'\\\\\\n]*(?:\\\\.[^'\\\\\\n]*)*)'"
                        "|`([^`\\\\]*(?:\\\\.[^`\\\\]*)*)`", re.S)

# Vendored, and not ours to rewrite.
VENDORED_JS = ("htmx.min.js",)


def _visible_strings(path: Path) -> list[tuple[int, str]]:
    """(line, text) for everything on this page a person reads."""
    text = _visible(path)
    out: list[tuple[int, str]] = []
    if path.suffix == ".js":
        for m in _JS_STRING.finditer(text):
            value = m.group(1) or m.group(2) or m.group(3) or ""
            if value:
                out.append((text.count("\n", 0, m.start()) + 1, value))
        return out
    text = _INLINE_CODE_BLOCK.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    text = _JINJA_EXPR.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    for m in _TAG.finditer(text):
        for attr in _ATTR.finditer(m.group(0)):
            value = attr.group(3) if attr.group(3) is not None else attr.group(4)
            if value:
                out.append((text.count("\n", 0, m.start()) + 1, value))
    pos = 0
    for m in _TAG.finditer(text):
        chunk = text[pos:m.start()]
        if chunk.strip():
            out.append((text.count("\n", 0, pos) + 1, chunk))
        pos = m.end()
    if text[pos:].strip():
        out.append((text.count("\n", 0, pos) + 1, text[pos:]))
    return out


# (file or "", fragment, why it is allowed). Same shape as
# VOCABULARY_ALLOWED, and every entry is a place a retired word is not copy.
TEMPLATE_VOCABULARY_ALLOWED: tuple[tuple[str, str, str], ...] = (
    ("admin_users.html", "a device, a plan or a report",
     "`device` for a SYNCTHING IDENTITY is the one use the terminology table "
     "keeps: this line is about a Syncthing device with no account behind it"),
    ("admin_users.html", "no Syncthing device reported", "the same identity"),
    ("admin_users.html", "device list unavailable", "the same identity"),
    ("admin_users.html", "its Syncthing device", "the same identity"),
    ("fleet_grid.html", "no Syncthing device ever reported", "the same identity"),
    ("fleet_grid.html", "its Syncthing device go", "the same identity"),
    ("project_detail.html", "this computer's sync identity is not named after an editor",
     "`device`/`sync identity` for a SYNCTHING IDENTITY is the one use the "
     "terminology table keeps (DUI-8 rewrote this line, 2026-09-04)"),
    ("project_detail.html", "no Syncthing device on this computer",
     "the same identity"),
    ("base.html", "width=device-width",
     "the viewport meta: a CSS keyword, not a word anybody reads"),
    ("", "MOVE ON THE SERVER AND ON EVERY MACHINE",
     "the button's own label, which the file-move flow owns "
     "(docs/FILE_MOVES.md); renamed there or nowhere"),
    ("", "unused placeholder fragment",
     "kept so the list is never empty"),
)


def _template_allowed(name: str, value: str) -> bool:
    return any((not where or where == name) and fragment in value
               for where, fragment, _why in TEMPLATE_VOCABULARY_ALLOWED)


@pytest.mark.parametrize("path", _rendered_files(), ids=lambda p: p.name)
def test_no_retired_word_in_rendered_copy(path: Path) -> None:
    if path.name in VENDORED_JS:
        pytest.skip("vendored library, not our copy")
    hits = []
    for line, value in _visible_strings(path):
        # The same rule the Python half applies: a string with no space in
        # it is a key, a route, an attribute name or a query fragment, not
        # a sentence. `/api/v1/selection/`, `data-col-machine` and
        # `machine=` are exactly what the terminology table leaves alone.
        if " " not in value.strip() or value.startswith("/"):
            continue
        if _template_allowed(path.name, value):
            continue
        for word in _retired_words_in(value):
            hits.append(f"{path.name}:{line}: CR-179 retired {word!r} "
                        f"(say {RETIRED_WORDS[word]}) in {value.strip()[:90]!r}")
    assert not hits, "; ".join(hits)


def test_the_template_vocabulary_scan_would_catch_a_regression() -> None:
    """The extractor itself: what it sees, and what it must not see."""
    import tempfile

    sample = ('<div data-machine="{{ c.machine }}" class="chip lane"\n'
              '     hx-post="/partials/admin/machines/forget"\n'
              '     title="pick a machine">the lane is halted</div>\n'
              '{# a comment naming the breaker #}\n')
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "sample.html"
        p.write_text(sample, encoding="utf-8")
        seen = [v for _line, v in _visible_strings(p)]
        assert any("pick a machine" in v for v in seen)
        assert any("the lane is halted" in v for v in seen)
        # ...and NOT the route, the data- attribute or the CSS class.
        assert not any("forget" in v for v in seen)
        assert not any("chip lane" in v for v in seen)
        assert not any("c.machine" in v for v in seen)
        # A single token is a key or a route, never a sentence.
        assert " " not in "data-col-machine"
        assert "/api/v1/selection/".startswith("/")
        # A comment is out of scope, here as everywhere in this file.
        assert not any("breaker" in v for v in seen)
        assert _retired_words_in("pick a machine") == ["machine"]
        js = Path(tmp) / "sample.js"
        js.write_text('const u = "/api/v1/selection/" + e;\n'
                      '// a comment about the breaker\n'
                      'alert("this machine is halted");\n', encoding="utf-8")
        js_seen = [v for _line, v in _visible_strings(js)]
        assert "this machine is halted" in js_seen
        assert not any("breaker" in v for v in js_seen)


def test_the_settings_strip_is_three_labelled_runs() -> None:
    """SYS-6: the groups ARE the list, so a page cannot be in one and not the
    other, and every entry keeps a route that exists."""
    flat = tuple(e for _g, entries in ui.SETTINGS_NAV_GROUPS for e in entries)
    assert ui.SETTINGS_NAV == flat
    assert [g for g, _e in ui.SETTINGS_NAV_GROUPS] == [
        "Run the fleet", "Is it healthy", "When it breaks"]
    labels = {label for _k, label, _h, _a in ui.SETTINGS_NAV}
    assert {"SYNC PLANS", "HISTORY", "HEALTH", "HELP"} <= labels
    # ...and the words they replaced are gone from the strip for good.
    assert "ASSIGNMENTS" not in labels and "TIMELINE" not in labels
    nav = (TEMPLATES / "partials" / "settings_nav.html").read_text(encoding="utf-8")
    assert "SETTINGS_NAV_GROUPS" in nav
    assert ui.SETTINGS_LANDING == "/admin/health"
