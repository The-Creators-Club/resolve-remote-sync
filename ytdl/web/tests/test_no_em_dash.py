"""No em dash (U+2014) in anything an editor reads.

The owner's house rule, 2026-08-18, and the same test the dashboard suite
carries (`dashboard/tests/test_no_em_dash.py`) -- duplicated rather than
shared because these are two suites with two interpreters and no common
package. The copy on this page uses a spaced hyphen, a colon, a comma,
parentheses or two sentences, never an em dash.

Scope is the surfaces a browser paints: `static/index.html`, the SPA's own
`static/app.js` (which writes every toast, banner and status cell), and the
non-docstring string literals of `ytdlweb` -- including `vendor/downloader.py`,
whose `on_status()` strings land in the downloads list.

Comments and docstrings are out of scope on purpose: `static/style.css`'s
theme header and the vendored file's history notes keep theirs. That is why
the Python half walks the AST -- `ast` never sees a comment, and docstring
nodes are subtracted explicitly.

All three spellings count: the character, the HTML entities (`&mdash;`,
`&#8212;`) and the escape `\\u2014`, because a page that ships the entity
paints the same glyph.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1]
STATIC = WEB / 'static'
PKG = WEB / 'ytdlweb'

FORMS = ('—', '&mdash;', '&#8212;', '\\u2014')

_HTML_COMMENT = re.compile(r'<!--.*?-->', re.S)
_BLOCK_COMMENT = re.compile(r'/\*.*?\*/', re.S)
# `//` that is not the tail of a URL. Every `//` inside a string literal in
# app.js is `://` (checked 2026-08-18); anything else is a comment.
_LINE_COMMENT = re.compile(r'(?<!:)//[^\n]*')


def _hits(text: str, source: str) -> list[str]:
    out = []
    for form in FORMS:
        start = 0
        while (i := text.find(form, start)) != -1:
            line = text.count('\n', 0, i) + 1
            out.append(f'{source}:{line}: {text.splitlines()[line - 1].strip()}')
            start = i + len(form)
    return out


def _html_files() -> list[Path]:
    return sorted(STATIC.rglob('*.html'))


def _js_files() -> list[Path]:
    return sorted(STATIC.rglob('*.js'))


def _py_files() -> list[Path]:
    return sorted(p for p in PKG.rglob('*.py') if '__pycache__' not in p.parts)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """The Constant nodes that are docstrings, by id(): not product copy."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, 'body', None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            out.add(id(first.value))
    return out


@pytest.mark.parametrize('path', _html_files(), ids=lambda p: p.name)
def test_page_markup_has_no_em_dash(path: Path) -> None:
    text = _HTML_COMMENT.sub('', path.read_text(encoding='utf-8'))
    assert not _hits(text, path.name), (
        'em dash in page copy (house style 2026-08-18): '
        + '; '.join(_hits(text, path.name))
    )


@pytest.mark.parametrize('path', _js_files(), ids=lambda p: p.name)
def test_app_js_has_no_em_dash(path: Path) -> None:
    text = path.read_text(encoding='utf-8')
    text = _LINE_COMMENT.sub('', _BLOCK_COMMENT.sub('', text))
    assert not _hits(text, path.name), (
        'em dash in JS that paints text (house style 2026-08-18): '
        + '; '.join(_hits(text, path.name))
    )


@pytest.mark.parametrize('path', _py_files(), ids=lambda p: p.name)
def test_python_string_literals_have_no_em_dash(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    skip = _docstring_nodes(tree)
    bad = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in skip
        and any(form in node.value for form in FORMS)
    ]
    assert not bad, (
        f'em dash in a {path.name} string literal (house style 2026-08-18): {bad}'
    )


def test_the_scan_actually_covers_something() -> None:
    """A guard against the globs going quiet after a directory move."""
    assert [p.name for p in _html_files()] == ['index.html']
    assert 'app.js' in [p.name for p in _js_files()]
    assert 'downloader.py' in [p.name for p in _py_files()]


def test_the_scan_would_catch_a_regression() -> None:
    """The detector itself, proved on each spelling."""
    for form in FORMS:
        assert _hits(f'failed {form} see the server log', 'x')
    assert not _hits('failed: see the server log', 'x')
