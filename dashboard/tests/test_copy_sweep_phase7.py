"""UI port phase 7, the copy sweep (docs/UI_REDESIGN_PORT_PLAN.md 2.6, D8, R12).

Copy that names a control no longer wears the classic key's brackets: it is
the key's label in sentence case, in double quotes (`press "Resume"`), which
reads the same next to a classic `[ RESUME ]` key, a terminal key (uppercased
by CSS), an email and a webhook. The copy lives in Python and is shared by
both variants, so it has to be variant-neutral.

Four checks:
  * the Python bracket scan: no string that reaches a person in any module
    under src/ccsync_dashboard names a control as `[ LABEL ]` (the allow-list
    is empty and may not grow);
  * every control the rewritten copy names is a real key on the classic page
    it is drawn on (`[ LABEL ]` there), so a relabel cannot orphan a sentence;
  * NOTICE_KINDS holds plain labels and each classic template wraps them;
  * the two docs the image ships and /help renders carry no bracket controls
    and no page-region words the terminal variant moves (R13).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from ccsync_dashboard import db as dbmod

DASH = Path(__file__).resolve().parents[1]
SRC = DASH / "src" / "ccsync_dashboard"
TEMPLATES = DASH / "templates"
DOCS = DASH.parent / "docs"

# `[ LABEL ]` with the space the product's bracket style always has; a
# selector (`[data-tip]`) or a subscript never has it.
BRACKET = re.compile(r"\[ [A-Za-z{]")

# (module, fragment): a string that is allowed to keep a bracket. Empty since
# phase 7 and it may not grow (R12). The weekly protection report's state
# words became `PROTECTED:` prefixes rather than an entry here (D8).
ALLOWED: tuple[tuple[str, str], ...] = ()
ALLOWED_COUNT = 0


def _py_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _docstring_ids(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def _sql(value: str) -> bool:
    upper = value.upper()
    return any(w in upper for w in ("INSERT INTO", "SELECT ", "CREATE TABLE",
                                    "UPDATE ", "DELETE FROM", "ALTER TABLE"))


def _strings(source: str):
    """(line, text) of every string literal that could reach a person: each
    constant that is not a docstring, and each f-string with its literal
    parts joined (`f"[ {label} ]"` is `[ \\x00 ]`, still a bracket)."""
    tree = ast.parse(source)
    skip = _docstring_ids(tree)
    inside_f: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                inside_f.add(id(v))
                parts.append(v.value if isinstance(v, ast.Constant) else "{x}")
            yield node.lineno, "".join(str(p) for p in parts)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in skip and id(node) not in inside_f):
            yield node.lineno, node.value


def _hits(path: Path) -> list[tuple[int, str]]:
    out = []
    for line, text in _strings(path.read_text(encoding="utf-8")):
        if BRACKET.search(text) and not _sql(text):
            if any(path.name == f and frag in text for f, frag in ALLOWED):
                continue
            out.append((line, text[:120]))
    return out


def test_the_allow_list_may_not_grow():
    assert len(ALLOWED) == ALLOWED_COUNT == 0


def test_no_python_copy_names_a_control_in_brackets():
    found = {f"{p.name}:{line}": text for p in _py_files() for line, text in _hits(p)}
    assert not found, ("copy naming a control is its label in double quotes "
                       "(D8), never [ LABEL ]: " + repr(found))


def test_the_scan_reads_the_modules_the_old_vocabulary_scan_missed():
    names = {p.name for p in _py_files()}
    for name in ("cards_pool.py", "recovery.py", "release_feed.py"):
        assert name in names


def test_the_scan_catches_the_shapes_it_is_for(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text(
        '"""A docstring may say [ OPEN ]."""\n'
        'A = "Press [ OPEN ] to try again."\n'
        'B = f"  [ {label} ] {title}"\n'
        'C = "[document.visibilityState === \'visible\']"\n'
        'D = "INSERT INTO t VALUES (?) -- [ QUEUED ]"\n',
        encoding="utf-8")
    lines = sorted(line for line, _t in _hits(bad))
    assert lines == [2, 3]


# ----------------------------------------------- the labels are real keys

def _code(module: str) -> str:
    """Runtime-ish text of a module: comment lines dropped, adjacent literals
    joined, escaped quotes unescaped."""
    lines = [ln for ln in (SRC / module).read_text(encoding="utf-8").splitlines()
             if not ln.strip().startswith("#")]
    return re.sub(r'"\s*\n\s*f?"', "", "\n".join(lines)).replace('\\"', '"')


# (module whose copy names it, the D8 label, the classic template drawing it).
D8_LABELS = (
    ("alerts.py", "Resume", "partials/fleet_grid.html"),
    ("alerts.py", "Start syncing again", "partials/fleet_halt.html"),
    ("alerts.py", "Keep it stopped", "partials/fleet_halt.html"),
    ("alerts.py", "Forget", "partials/fleet_grid.html"),
    ("alerts.py", "Check now", "partials/admin_packages.html"),
    ("alerts.py", "Update now", "partials/admin_packages.html"),
    ("alerts.py", "Send a test", "partials/admin_alerts.html"),
    ("alerts.py", "Show finished", "partials/admin_jobs.html"),
    ("alerts.py", "Try again", "partials/admin_jobs.html"),
    ("alerts.py", "Cancel", "partials/admin_jobs.html"),
    ("alerts.py", "Ask this computer why", "partials/fleet_grid.html"),
    ("notices.py", "Update now", "partials/admin_dashboard_update.html"),
    ("notices.py", "Forget", "partials/fleet_grid.html"),
    ("notices.py", "Send a test", "partials/admin_alerts.html"),
    ("notices.py", "Download crash reports", "partials/admin_diagnostics.html"),
    ("notices.py", "Check now", "partials/admin_packages.html"),
    ("notices.py", "Installer", "partials/topbar.html"),
    ("invariants.py", "Update now", "partials/admin_packages.html"),
    ("invariants.py", "Send a test", "partials/admin_alerts.html"),
    ("protection.py", "I have backed it up", "partials/protection.html"),
    ("protection.py", "Record a restore", "partials/protection.html"),
    ("protection.py", "Resume", "partials/fleet_grid.html"),
    ("recovery.py", "Stop all syncing", "partials/fleet_halt.html"),
    ("recovery.py", "Create & link", "partials/project_setup_panel.html"),
    ("recovery.py", "Undo this change", "partials/recovery.html"),
    ("cards_pool.py", "Open", "cards_landing.html"),
    ("cards_pool.py", "Close", "cards_landing.html"),
    ("api.py", "Unarchive", "admin_assignments.html"),
    ("api.py", "Use this folder", "partials/project_setup_panel.html"),
    ("api.py", "Forget", "partials/fleet_grid.html"),
    ("ui.py", "Start syncing again", "partials/fleet_halt.html"),
    ("ui.py", "Resume", "partials/fleet_grid.html"),
    ("release_feed.py", "Update now", "partials/admin_dashboard_update.html"),
    ("setup_engine.py", "Available from the vendor", "partials/admin_packages.html"),
)


@pytest.mark.parametrize("module,label,template", D8_LABELS,
                         ids=[f"{m}:{lab}" for m, lab, _t in D8_LABELS])
def test_each_quoted_label_is_a_key_on_its_classic_page(module, label, template):
    assert f'"{label}"' in _code(module), f"{module} no longer names {label!r}"
    html = (TEMPLATES / template).read_text(encoding="utf-8")
    key = f"[ {label.upper()} ]"
    assert key in html or key.replace("&", "&amp;") in html, (
        f"{template} draws no {key}: the copy in {module} names a key that "
        "is not there")
    cc = TEMPLATES / "cc" / template
    if not cc.is_file():   # the terminal twin arrives with its page's phase
        return
    corpus = "\n".join(p.read_text(encoding="utf-8")
                       for p in (TEMPLATES / "cc").rglob("*.html")).lower()
    found = any(form.lower() in corpus
                for form in (label, label.replace("&", "&amp;")))
    if not found and (module, label) in TERMINAL_GAPS:
        pytest.skip(f"hand-off: {TERMINAL_GAPS[(module, label)]}")
    assert found, f"no cc/ template carries a {label!r} key"


# A terminal page built in parallel with this sweep that does not (yet) carry
# a label the shared copy names. Each is a hand-off in
# docs/UI_PORT_LEDGER/P7-copy.md; delete the entry when the key lands.
TERMINAL_GAPS: dict[tuple[str, str], str] = {
    # Emptied by the integrator (2026-09-25): every terminal key now carries
    # its D8 label. Add an entry only for a page still being built.
}


def test_the_file_move_key_is_named_in_the_vocabulary_word():
    """R12's decision: 'Move on the server and on every computer'. The
    classic key keeps its old text until phase 8, so only the copy is
    checked here."""
    for module in ("alerts.py", "notices.py"):
        code = _code(module)
        assert '"Move on the server and on every computer"' in code
        assert "EVERY MACHINE" not in code


# ------------------------------------------------ NOTICE_KINDS labels

def test_notice_kinds_hold_plain_labels():
    for spec in dbmod.notice_kinds():
        href, label = dbmod.notice_href(spec["kind"], "")
        if href:
            assert "[" not in label and "]" not in label, (spec["kind"], label)
            assert label[:1].isupper() and not label.isupper(), label
    assert dbmod.notice_href("server_crash_report")[1] == "Download crash reports"


@pytest.mark.parametrize("template,expr", [
    ("partials/notices.html", "[ {{ n.href_label | upper }} ]"),
    ("admin_health.html", "[ {{ row.href_label | upper }} ]"),
    ("admin_health.html", "[ {{ row.detail_label | upper }} ]"),
])
def test_the_classic_templates_wrap_the_plain_label(template, expr):
    assert expr in (TEMPLATES / template).read_text(encoding="utf-8")


# The rendered classic button ("[ TAKE ME THERE ]" from the plain label) is
# pinned by test_notices_sweep_wave2.py on /partials/notices.


# ------------------------------------------------------------ the docs

@pytest.mark.parametrize("name", ["HOW_IT_WORKS.md", "EDITOR_SETUP.md"])
def test_the_shipped_docs_name_controls_without_brackets(name):
    text = (DOCS / name).read_text(encoding="utf-8")
    hits = [ln for ln in text.splitlines() if BRACKET.search(ln)]
    assert not hits, hits


@pytest.mark.parametrize("name", ["HOW_IT_WORKS.md", "EDITOR_SETUP.md"])
def test_the_shipped_docs_name_no_region_the_terminal_look_moves(name):
    """R13 / wave 3: /help serves one file to both populations, so a
    sentence names a destination, never a sidebar or 'above the grid'."""
    text = (DOCS / name).read_text(encoding="utf-8").lower()
    for region in ("sidebar", "above the grid", "fleet grid", "three bars",
                   "top left"):
        assert region not in text, region
