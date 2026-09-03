"""No drive letter and no Windows separator in anything an editor reads.

YTWEB-10 (usability + resilience sweep, 2026-09-03). Every no-companion dead
end used to end at *"The clip is in Projects\\Foo\\Youtube\\bar on your sync
drive (P: on Windows)"*, and the history row's subtitle rewrote the stored
path to backslashes unconditionally. Both are wrong twice over:

* the drive letter is SITE DATA (`canonical_prefix`, default `P:\\`), so a
  literal `P:` in code is the first customer's value shipped to the second
  (`CLAUDE.md`, COMMERCIAL_READINESS item 11); and
* half this fleet edits on a Mac, where the root is `/Volumes/<SSD>` and a
  backslash is a legal character in a filename rather than a separator.

This page is served from the NAS and genuinely cannot know either one, so it
prints the stored relative path exactly as stored - forward slashes, no root -
and says "under your sync drive" with no parenthetical.

Scope is what a browser paints: `static/*.html` and `static/*.js`, comments
subtracted (a comment that EXPLAINS why `P:` is absent has to be able to say
`P:`), plus the non-docstring string literals of `ytdlweb`. The comment
stripping mirrors `test_no_em_dash.py`, which is where these regexes come
from.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1]
STATIC = WEB / 'static'
PKG = WEB / 'ytdlweb'

_HTML_COMMENT = re.compile(r'<!--.*?-->', re.S)
_BLOCK_COMMENT = re.compile(r'/\*.*?\*/', re.S)
_LINE_COMMENT = re.compile(r'(?<!:)//[^\n]*')

# The retired copy, by its exact words: the parenthetical, and the two helpers
# that existed only to Windows-ify a path for display. Named rather than
# pattern-matched so a failure tells whoever hits it which sentence came back.
RETIRED = (
    'P: on Windows',
    'on your sync drive (',
    'winPath',
    'winParent',
)

# A drive letter root, in any string that reaches a browser. `P:\` and `P:/`
# both, because either spelling is the same claim about the editor's machine.
_DRIVE = re.compile(r'\b[A-Z]:[\\/]')

# A separator appended to an interpolated value: `${project_label}\Youtube`.
# This is the shape the finding is about - a path assembled with backslashes -
# and it is precise enough that a legitimate escape (`\n`, `\\.`) never trips
# it, because those never follow a closing brace.
_INTERPOLATED_BACKSLASH = re.compile(r'\}\\')


def _visible_js(path: Path) -> str:
    text = path.read_text(encoding='utf-8')
    return _LINE_COMMENT.sub('', _BLOCK_COMMENT.sub('', text))


def _visible_html(path: Path) -> str:
    return _HTML_COMMENT.sub('', path.read_text(encoding='utf-8'))


def _js_files() -> list[Path]:
    return sorted(STATIC.rglob('*.js'))


def _html_files() -> list[Path]:
    return sorted(STATIC.rglob('*.html'))


def _py_files() -> list[Path]:
    return sorted(p for p in PKG.rglob('*.py') if '__pycache__' not in p.parts)


def _lines(text: str, needle: str) -> list[str]:
    out = []
    lines = text.splitlines()
    for n, line in enumerate(lines, 1):
        if needle in line:
            out.append(f'{n}: {line.strip()}')
    return out


@pytest.mark.parametrize('path', _js_files() + _html_files(), ids=lambda p: p.name)
def test_the_retired_copy_is_gone(path: Path) -> None:
    text = _visible_js(path) if path.suffix == '.js' else _visible_html(path)
    for phrase in RETIRED:
        assert phrase not in text, (
            f'{path.name} still carries the retired YTWEB-10 copy {phrase!r}: '
            + '; '.join(_lines(text, phrase))
        )


@pytest.mark.parametrize('path', _js_files() + _html_files(), ids=lambda p: p.name)
def test_no_drive_letter_reaches_the_browser(path: Path) -> None:
    text = _visible_js(path) if path.suffix == '.js' else _visible_html(path)
    bad = [
        f'{text.count(chr(10), 0, m.start()) + 1}: {m.group(0)}'
        for m in _DRIVE.finditer(text)
    ]
    assert not bad, (
        f'{path.name} names a drive letter (YTWEB-10; the root is site data, '
        f'`canonical_prefix`, and is /Volumes/<SSD> on a Mac): ' + '; '.join(bad)
    )


@pytest.mark.parametrize('path', _js_files(), ids=lambda p: p.name)
def test_no_path_is_assembled_with_backslashes(path: Path) -> None:
    text = _visible_js(path)
    bad = [
        f'{text.count(chr(10), 0, m.start()) + 1}'
        for m in _INTERPOLATED_BACKSLASH.finditer(text)
    ]
    assert not bad, (
        f'{path.name} joins a stored path with a backslash (YTWEB-10): the '
        f'paths this page shows are relative and forward-slashed, lines '
        + ', '.join(bad)
    )


@pytest.mark.parametrize('path', _py_files(), ids=lambda p: p.name)
def test_python_string_literals_name_no_drive(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, 'body', None)
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)) or not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            docstrings.add(id(first.value))
    bad = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in docstrings and _DRIVE.search(node.value)
    ]
    assert not bad, (
        f'a {path.name} string literal names a drive letter (YTWEB-10): {bad}'
    )


def test_the_scan_actually_covers_something() -> None:
    """A guard against the globs going quiet after a directory move."""
    assert [p.name for p in _html_files()] == ['index.html']
    assert 'app.js' in [p.name for p in _js_files()]
    assert len(_py_files()) > 5
