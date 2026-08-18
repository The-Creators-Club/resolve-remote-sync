"""No em dash (U+2014) in anything an editor reads.

House rule, owner's call 2026-08-18: user-visible text uses a spaced hyphen, a
colon, a comma, parentheses or two sentences, never an em dash. The wizard is
the very first thing a new editor reads, so its step titles, labels, button
captions and error text are pinned here.

Two exemptions, both deliberate:

  * **comments and docstrings.** They are for us, not for editors, and several
    of them quote history that reads better with the dash. The scan below drops
    COMMENT tokens outright and treats a string that opens a logical line as a
    docstring.
  * **log lines.** Same audience (us, in the wizard's log), so a `logger.*`
    call is skipped by the line it sits on.

There was nothing to fix here on the day the rule landed. This test is what
keeps that true.
"""

from __future__ import annotations

import io
import tokenize
from pathlib import Path

import pytest

ONBOARDING = Path(__file__).resolve().parent.parent

EM_DASH = "—"
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


def _py_files() -> list[Path]:
    """The wizard itself: onboard.py and steps.py, not the venv or the tests."""
    return sorted(p for p in ONBOARDING.glob("*.py"))


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


@pytest.mark.parametrize("path", _py_files(), ids=lambda p: p.name)
def test_no_em_dash_in_visible_python_strings(path: Path) -> None:
    hits = _offending_strings(path)
    assert not hits, (
        "an em dash in text the wizard shows (a step title, a label, a button "
        "caption, an error):\n  " + "\n  ".join(hits)
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
