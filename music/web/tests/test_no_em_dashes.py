"""No em dash (U+2014) in anything an editor reads.

House rule, owner's call 2026-08-18: user-visible text uses a spaced hyphen, a
colon, a comma, parentheses or two sentences, never an em dash. The rule is
about the product's voice, so it is pinned where the product speaks: every file
served to the browser, and every Python string that is not documentation.

Two exemptions, both deliberate:

  * **comments and docstrings.** They are for us, not for editors, and several
    of them quote history that reads better with the dash. The scan below drops
    COMMENT tokens outright and treats a string that opens a logical line as a
    docstring.
  * **log lines.** Same audience (us, in ccsync.log), so a `logger.*` call is
    skipped by the line it sits on.

Static files get no such carve-out: a .js comment ships to the browser, and a
whole-file scan is the only check that cannot be argued with later.
"""

from __future__ import annotations

import io
import tokenize
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent
STATIC = WEB / "static"
APP = WEB / "musicweb"

EM_DASH = "—"
# The same character wearing HTML/JS clothes. b-roll's index.html reached the fleet
# with `&mdash;` in it, so entity spellings are checked too, not just the raw
# codepoint.
DISGUISES = ("&mdash;", "&#8212;", "&#x2014;", "\\u2014")

STATIC_SUFFIXES = {".js", ".html", ".css", ".svg"}

# A string on one of these lines is talking to ccsync.log, not to an editor.
LOG_CALL = ("logger.", "log.debug", "log.info", "log.warning", "log.error",
            "log.exception", "log.critical", "warnings.warn")

# tokenize types that can only precede the first token of a logical line, so a
# STRING right after one of them is a docstring (module, class or function).
LINE_STARTERS = {
    tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT,
    tokenize.ENCODING, tokenize.COMMENT,
}

# PEP 701 (Python 3.12) tokenizes f-strings into FSTRING_* parts rather than one
# STRING token; without this an f-string's text would never be scanned.
FSTRING_MIDDLE = getattr(tokenize, "FSTRING_MIDDLE", -1)


def _static_files() -> list[Path]:
    return sorted(p for p in STATIC.rglob("*") if p.suffix in STATIC_SUFFIXES)


def _py_files() -> list[Path]:
    return sorted(p for p in APP.rglob("*.py") if "__pycache__" not in p.parts)


def _offending_strings(path: Path) -> list[str]:
    """Every non-docstring, non-log string token in `path` holding an em dash."""
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    hits: list[str] = []
    prev = tokenize.ENCODING
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.STRING, FSTRING_MIDDLE) and EM_DASH in tok.string:
            line = lines[tok.start[0] - 1]
            docstring = tok.type == tokenize.STRING and prev in LINE_STARTERS
            if not docstring and not any(call in line for call in LOG_CALL):
                hits.append(f"{path.name}:{tok.start[0]}: {line.strip()}")
        prev = tok.type
    return hits


@pytest.mark.parametrize("path", _static_files(), ids=lambda p: p.name)
def test_no_em_dash_in_static(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    bad = [d for d in (EM_DASH, *DISGUISES) if d in text]
    assert not bad, (
        f"{path.name} contains {bad}: the browser gets this file verbatim. "
        "Use ' - ', a colon, a comma, or two sentences."
    )


@pytest.mark.parametrize("path", _py_files(), ids=lambda p: p.name)
def test_no_em_dash_in_visible_python_strings(path: Path) -> None:
    hits = _offending_strings(path)
    assert not hits, (
        "an em dash in a string an editor can see (HTTP detail, reason, "
        "suggestion, a name in the UI):\n  " + "\n  ".join(hits)
    )


def test_the_scanner_can_tell_a_docstring_from_a_message(tmp_path: Path) -> None:
    """The exemptions are the whole risk here: a scanner that skips too much
    passes for the wrong reason, and one that skips too little gets muted."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        f'"""A docstring {EM_DASH} exempt."""\n'
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        f'# a comment {EM_DASH} exempt\n'
        f'logger.warning("log line {EM_DASH} exempt")\n'
        f'def f(x):\n'
        f'    """Function docstring {EM_DASH} exempt."""\n'
        f'    raise ValueError("visible {EM_DASH} caught")\n'
        f'    return f"f-string {EM_DASH} caught {{x}}"\n',
        encoding="utf-8",
    )
    hits = _offending_strings(sample)
    assert len(hits) == 2, hits
    assert any("visible" in h for h in hits)
    assert any("f-string" in h for h in hits)
