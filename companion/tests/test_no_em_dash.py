"""No em dash (U+2014) in anything an editor reads.

The owner's house rule, 2026-08-18: the product's copy uses a spaced hyphen, a
colon, a comma, parentheses or two sentences, never an em dash. The dashboard
(`dashboard/tests/test_no_em_dash.py`) and the b-roll web UI
(`broll/web/tests/test_no_em_dashes.py`) already pin their halves; this is the
companion's, and it is the half with the widest surface: tray menu items and
status lines, balloon notices, popup and wizard copy, messagebox text, the
JSON `message`/`error` strings the 8899 loopback hands back to a browser, and
the VRAM/download sentences the b-roll indexing sidecar writes into the
progress window.

Comments and docstrings are deliberately OUT of scope: they are not product
copy, and this file must not be the reason someone rewrites a comment. That is
why this walks the AST rather than the raw bytes (`ast` never sees a comment,
and docstring nodes are subtracted explicitly).

`log.*`/`logger.*` arguments are out of scope for the same reason. ~/.ccsync's
log is a diagnostic file, not a surface, and it is written in the same voice as
the comments around it.

The four spellings all count: the character itself, the escape a raw string
would use to smuggle it past a byte scan, and both HTML entities, since a
future error page that ships `&mdash;` paints exactly the same glyph.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "ccsync_companion"

FORMS = ("—", "\\u2014", "&mdash;", "&#8212;")

# What this package calls its loggers. `log` in all but three modules, which
# use `logger`; the rest are here so a module that renames one does not go
# quietly unscanned in the other direction either.
LOGGERS = {"log", "logger", "_log", "LOG", "logging"}

# The ONE em dash that is not copy: `broll_vlm/compact_format.py`'s
# `_NONE_WORDS` is the set of tokens the VISION MODEL emits to mean "nothing
# here", and Qwen writes an em dash for that as readily as a hyphen. It is
# input the parser recognises, not output an editor reads, and the file is
# vendored byte-for-byte from broll/indexer/broll_index/ anyway (the release
# gate refuses to build on drift), so it could not be reworded here even if it
# were copy. Keyed by exact value so a real sentence in that same file still
# fails.
ALLOWED = {("broll_vlm/compact_format.py", "—")}


def _py_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """The Constant nodes that are docstrings, by id().

    A docstring is the first statement of a module/class/function and reaches
    no editor, so it is not product copy.
    """
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


def _log_argument_nodes(tree: ast.AST) -> set[int]:
    """The Constant nodes that are arguments of a `log.<level>(...)` call.

    Only the call's OWN arguments (including the pieces of an f-string one),
    never the constants inside a nested call: `log.info("%s", label(...))`
    passes label()'s arguments to something that may well be a surface.
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                and func.value.id in LOGGERS):
            continue
        for arg in [*node.args, *(kw.value for kw in node.keywords)]:
            if isinstance(arg, ast.Constant):
                out.add(id(arg))
            elif isinstance(arg, ast.JoinedStr):
                for piece in ast.walk(arg):
                    if isinstance(piece, ast.Constant):
                        out.add(id(piece))
    return out


def _offenders(source: str, filename: str, rel: str = "") -> list[str]:
    tree = ast.parse(source, filename=filename)
    skip = _docstring_nodes(tree) | _log_argument_nodes(tree)
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in skip
        and any(form in node.value for form in FORMS)
        and (rel, node.value) not in ALLOWED
    ]


@pytest.mark.parametrize("path", _py_files(), ids=lambda p: p.name)
def test_no_em_dash_in_a_string_literal(path: Path) -> None:
    rel = path.relative_to(SRC).as_posix()
    bad = _offenders(path.read_text(encoding="utf-8"), str(path), rel)
    assert not bad, (
        f"em dash in a {rel} string literal (house style 2026-08-18): {bad}")


def test_the_scan_actually_covers_something() -> None:
    """A guard against the glob going quiet after a package move."""
    assert len(_py_files()) > 40


def test_the_scan_would_catch_a_regression() -> None:
    """The detector itself, proved on each spelling and each exemption."""
    for form in FORMS:
        assert _offenders(f'x = "halted {form} nothing is syncing"', "<x>")
    assert not _offenders('x = "halted - nothing is syncing"', "<x>")
    # Docstrings, comments and the log are not copy.
    assert not _offenders('"""halted — nothing is syncing"""', "<x>")
    assert not _offenders('x = 1  # halted — nothing is syncing', "<x>")
    assert not _offenders('log.warning("halted — nothing is syncing")', "<x>")
    assert not _offenders('log.warning(f"halted — {name}")', "<x>")
    assert not _offenders('logger.info("halted — nothing", extra="a — b")', "<x>")
    # ...but a surface called from inside a log line still is.
    assert _offenders('log.warning("%s", banner("halted — stopped"))', "<x>")
    # The allow-list is exact: same file, different sentence, still fails.
    assert not _offenders('x = "—"', "<x>", "broll_vlm/compact_format.py")
    assert _offenders('x = "halted — stopped"', "<x>", "broll_vlm/compact_format.py")
    assert _offenders('x = "—"', "<x>", "tray.py")
