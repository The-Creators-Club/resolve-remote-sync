"""No em dash (U+2014) in anything an editor or an admin reads.

The owner's house rule, 2026-08-18: the product's copy uses a spaced hyphen, a
colon, a comma, parentheses or two sentences -- never an em dash. It is a
typography rule about the PRODUCT, so it binds the surfaces a browser paints
and nothing else: templates, the static JS that writes text into the DOM, and
the string literals this package hands back (page context, HTTP `detail`,
banner and notice copy).

Comments and docstrings are deliberately OUT of scope, because they are not
product copy -- `static/style.css`'s theme header keeps its em dash on purpose,
and this file must not be the reason someone rewrites a comment. That is why
the Python half walks the AST rather than the raw bytes: `ast` never sees a
comment, and the docstring nodes are subtracted explicitly.

The three spellings all count: the character itself, the HTML entities
(`&mdash;`, `&#8212;`) and the JS/Python escape `\\u2014`, since a template
that ships `&mdash;` paints exactly the same glyph.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
SRC = ROOT / "src" / "ccsync_dashboard"

# The character, both HTML entities, and the escape a .js or .py file would
# use to smuggle it past a byte scan.
FORMS = ("—", "&mdash;", "&#8212;", "\\u2014")

_JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.S)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
# `//` that is not the tail of a URL. Every `//` inside a string literal in
# these files is `://` (checked 2026-08-18); anything else is a comment.
_LINE_COMMENT = re.compile(r"(?<!:)//[^\n]*")


def _hits(text: str, source: str) -> list[str]:
    out = []
    for form in FORMS:
        start = 0
        while (i := text.find(form, start)) != -1:
            line = text.count("\n", 0, i) + 1
            out.append(f"{source}:{line}: {text.splitlines()[line - 1].strip()}")
            start = i + len(form)
    return out


def _template_files() -> list[Path]:
    return sorted(TEMPLATES.rglob("*.html"))


def _js_files() -> list[Path]:
    return sorted(STATIC.rglob("*.js"))


def _py_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """The Constant nodes that are docstrings, by id().

    A docstring is the first statement of a module/class/function and reaches
    no user, so it is not product copy.
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


@pytest.mark.parametrize("path", _template_files(), ids=lambda p: p.name)
def test_templates_have_no_em_dash(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = _HTML_COMMENT.sub("", _JINJA_COMMENT.sub("", text))
    assert not _hits(text, path.name), (
        "em dash in rendered template copy (house style 2026-08-18): "
        + "; ".join(_hits(text, path.name))
    )


@pytest.mark.parametrize("path", _js_files(), ids=lambda p: p.name)
def test_static_js_has_no_em_dash(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))
    assert not _hits(text, path.name), (
        "em dash in JS that paints text (house style 2026-08-18): "
        + "; ".join(_hits(text, path.name))
    )


@pytest.mark.parametrize("path", _py_files(), ids=lambda p: p.name)
def test_python_string_literals_have_no_em_dash(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    skip = _docstring_nodes(tree)
    bad = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in skip
        and any(form in node.value for form in FORMS)
    ]
    assert not bad, (
        f"em dash in a {path.name} string literal (house style 2026-08-18): {bad}"
    )


def test_the_scan_actually_covers_something() -> None:
    """A guard against the globs going quiet after a directory move."""
    assert len(_template_files()) > 10
    assert len(_js_files()) >= 1
    assert len(_py_files()) > 10


def test_the_scan_would_catch_a_regression() -> None:
    """The detector itself, proved on each spelling."""
    for form in FORMS:
        assert _hits(f"halted {form} nothing is syncing", "x")
    assert not _hits("halted - nothing is syncing", "x")
