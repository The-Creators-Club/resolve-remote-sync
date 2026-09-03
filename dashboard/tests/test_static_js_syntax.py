"""Every hand-written file in static/ must PARSE.

bug-hunt-2026-09-03 dash-mounts-ui-1: `assignments.js` carried two raw
newlines inside a double-quoted string literal from 2026-08-28 (55fdfa7)
through dashboard 0.7.27, i.e. through every build that reached the fleet.
JavaScript forbids an unescaped line terminator in a quoted literal, so the
file did not parse; each of these files is one IIFE, so a parse error
unregisters EVERY listener in it and the admin assignment matrix became a
page where a tick flips the box, writes nothing and says nothing. The suite
had no JavaScript coverage at all, which is why nothing caught it.

Two checks, deliberately:
  * `node --check` when node is on PATH - the honest answer, but node is not
    a dependency of this venv or of CI's python job, so it SKIPS when absent.
  * a dependency-free scan for a quoted literal spanning a newline, which
    runs everywhere. It would have caught this defect on its own, and it is
    the one that has to be green on the machine that has no node.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"

# htmx is vendored and minified: not ours to fix, and its own tooling parsed
# it. Same exclusion the em-dash scan makes.
VENDORED = {"htmx.min.js"}


def js_files() -> list[Path]:
    return sorted(p for p in STATIC.glob("*.js") if p.name not in VENDORED)


def test_there_are_files_to_check():
    """A glob that matches nothing is a green suite that checks nothing."""
    assert len(js_files()) >= 5


def unterminated_string_lines(src: str) -> list[tuple[int, str]]:
    """Line numbers where a ' or " string literal runs past end of line.

    A small scanner rather than a regex: it has to know what is inside a
    comment and inside a template literal (backticks MAY span lines, and
    several of these files use them). Regex literals are recognised by the
    usual "what came before" heuristic so that a `/'/` cannot open a string.
    """
    bad: list[tuple[int, str]] = []
    i, line, n = 0, 1, len(src)
    prev_significant = ""
    while i < n:
        ch = src[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch in " \t\r":
            i += 1
            continue
        two = src[i:i + 2]
        if two == "//":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if two == "/*":
            i += 2
            while i < n and src[i:i + 2] != "*/":
                if src[i] == "\n":
                    line += 1
                i += 1
            i += 2
            continue
        if ch in "\"'":
            quote, start_line = ch, line
            i += 1
            while i < n:
                c = src[i]
                if c == "\\":
                    i += 2
                    continue
                if c == "\n":
                    bad.append((start_line, quote))
                    line += 1
                    i += 1
                    break
                if c == quote:
                    i += 1
                    break
                i += 1
            prev_significant = quote
            continue
        if ch == "`":
            i += 1
            while i < n:
                c = src[i]
                if c == "\\":
                    i += 2
                    continue
                if c == "\n":
                    line += 1
                elif c == "`":
                    i += 1
                    break
                i += 1
            prev_significant = "`"
            continue
        if ch == "/" and (prev_significant == "" or prev_significant in "(,=:[!&|?{};+-*%~^<>"):
            i += 1
            in_class = False
            while i < n:
                c = src[i]
                if c == "\\":
                    i += 2
                    continue
                if c == "\n":  # not a regex after all; let the next pass see it
                    break
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    i += 1
                    break
                i += 1
            prev_significant = "/"
            continue
        prev_significant = ch
        i += 1
    return bad


@pytest.mark.parametrize("path", js_files(), ids=lambda p: p.name)
def test_no_quoted_string_literal_spans_a_newline(path: Path):
    bad = unterminated_string_lines(path.read_text(encoding="utf-8"))
    assert not bad, (
        f"{path.name}: a {bad[0][1]} string literal runs past the end of line "
        f"{bad[0][0]}. JavaScript forbids that, so the whole file fails to "
        f"parse and every listener in it is dead. Escape it as \\n.")


@pytest.mark.parametrize("path", js_files(), ids=lambda p: p.name)
def test_node_check_parses_the_file(path: Path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the newline scan above is the gate here")
    proc = subprocess.run([node, "--check", str(path)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"{path.name} does not parse:\n{proc.stderr}"
