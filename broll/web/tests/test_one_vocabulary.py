"""One vocabulary: the retired words never come back into b-roll's copy.

Section 4 of `docs/USABILITY_RESILIENCE_SWEEP_2026-09-03.md` (UX-4/UX-5, wave
4, 2026-09-04). The journey agent found the same concept wearing five names
across the tray, the dashboard and the three SPAs, so the owner fixed one word
per concept for everything an editor READS:

    tick / sync plan       never "selection", never "assignment"
    computer               never "machine", "rig", "base rig", and never
                           "companion" as a noun for the box on the desk
    the CC Sync tray       the program that runs on that computer
    paused                 you did it
    stopped by your admin  a fleet halt
    stopped itself         a breaker or a disk floor
    upload / proxy download / folder sync    never "lane"

Code identifiers, DOM ids, CSS classes, routes, query parameters, DB columns
and log lines keep their names on purpose: `machine` is the wire field and the
`machines` table, and renaming those would be a data change wearing a copy
change. So this scan reads only the places the product SPEAKS:

  * every string literal in `static/*.js`, with comments removed (a comment is
    for us, and `test_no_em_dashes.py` is the whole-file scan);
  * the text nodes and the human-facing attributes (`title`, `placeholder`,
    `aria-label`, `alt`) of `static/*.html`;
  * the `detail` / `message` / `error` values in `app/*.py`, which are the
    sentences a refusal carries to the page and to the tray.

Interpolations are removed before matching: `${batch.machine}` is code and
`{machine}` is a template token filled with a hostname, neither is a word an
editor reads. A JS or Python candidate must contain a space, because a
one-word literal there is a selector, an enum or a banner key; HTML text has
no such let-out, since a bare word in a text node is a label.

Every allowed hit carries its reason in ALLOWED. Add a word to the copy, not
an entry to that list.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent
STATIC = WEB / "static"
APP = WEB / "app"

RETIRED = re.compile(
    r"(?i)\b(lanes?|machines?|rigs?|halted|parked|breakers?|selections?"
    r"|assignments?|companions?)\b")

# Substring -> why a string carrying it is not the bug this test looks for.
# One entry per REASON, never a blanket "this file is fine".
ALLOWED: dict[str, str] = {
    "~/.broll-companion.json":
        "a filename on the editor's own disk, printed so they can find it; "
        "renaming a path is not a copy change",
    "BRoll Companion":
        "the proper name of the retired standalone program an editor may "
        "still have in their tray, and naming it is the whole point of the "
        "sentence (it holds port 8899)",
}

COPY_KEYS = {"detail", "message", "error"}

_BS = chr(92)
# `${...}` is code and `{machine}` is a token filled with a hostname. The
# third alternative is a DANGLING `${`: a template literal that nests
# another one ends the naive lexer above early, so what is left of the
# tail is JS, not copy.
_INTERP = re.compile(r"\$\{[^}]*\}|\{[A-Za-z_][A-Za-z_0-9]*\}|\$\{[^}]*$")
_TAG = re.compile(r"<[^>]*>", re.S)
_ATTR = re.compile(r'\b(?:title|placeholder|aria-label|alt)\s*=\s*"([^"]*)"')


def _blank(match: re.Match) -> str:
    """Replace a span with spaces, keeping every newline so lines still count."""
    return re.sub(r"[^\n]", " ", match.group(0))


def js_strings(text: str) -> list[tuple[int, str]]:
    """(line, literal) for every JS string/template literal outside a comment."""
    out: list[tuple[int, str]] = []
    i, n, line = 0, len(text), 1
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j == -1 else j
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            line += text.count("\n", i, j)
            i = j
        elif c in "\"'`":
            quote, j, start = c, i + 1, line
            while j < n:
                if text[j] == _BS:
                    j += 2
                    continue
                if text[j] == quote:
                    j += 1
                    break
                if text[j] == "\n":
                    if quote != "`":
                        break
                    line += 1
                j += 1
            out.append((start, text[i:j]))
            i = j
        else:
            i += 1
    return out


def html_copy(text: str) -> list[tuple[int, str]]:
    text = re.sub(r"<!--.*?-->", _blank, text, flags=re.S)
    text = re.sub(r"(?s)<(script|style)\b.*?</\1>", _blank, text)
    out: list[tuple[int, str]] = []
    for i, raw in enumerate(text.split("\n"), 1):
        for m in _ATTR.finditer(raw):
            out.append((i, m.group(1)))
        words = _TAG.sub(" ", raw).strip()
        if words:
            out.append((i, words))
    return out


def _literal_text(node: ast.AST) -> list[tuple[int, str]]:
    """The written-out halves of a copy expression. An f-string contributes its
    literal parts only: `{batch['machine']}` is a lookup, not a word."""
    out: list[tuple[int, str]] = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        out.append((node.lineno, node.value))
    elif isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append((node.lineno, part.value))
    elif isinstance(node, ast.BinOp):
        out += _literal_text(node.left) + _literal_text(node.right)
    elif isinstance(node, (ast.BoolOp, ast.IfExp, ast.Tuple, ast.List)):
        for child in ast.iter_child_nodes(node):
            out += _literal_text(child)
    return out


def py_copy(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value in COPY_KEYS:
                    out += _literal_text(value)
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in COPY_KEYS:
                    out += _literal_text(kw.value)
    return out


def _offending(candidate: str) -> bool:
    if any(fragment in candidate for fragment in ALLOWED):
        return False
    return bool(RETIRED.search(_INTERP.sub(" ", candidate)))


def _scan() -> list[str]:
    hits: list[str] = []
    for path in sorted(STATIC.glob("*.js")):
        for line, literal in js_strings(path.read_text(encoding="utf-8")):
            body = _INTERP.sub(" ", literal)
            if " " not in body.strip("\"'`"):
                continue
            if _offending(literal):
                hits.append(f"{path.name}:{line}: {literal[:120]}")
    for path in sorted(STATIC.glob("*.html")):
        for line, words in html_copy(path.read_text(encoding="utf-8")):
            if _offending(words):
                hits.append(f"{path.name}:{line}: {words[:120]}")
    for path in sorted(APP.glob("*.py")):
        for line, words in py_copy(path):
            if " " not in words.strip():
                continue
            if _offending(words):
                hits.append(f"{path.name}:{line}: {words[:120]}")
    return hits


def test_no_retired_word_reaches_an_editor() -> None:
    hits = _scan()
    assert not hits, (
        "section 4 of the 2026-09-03 sweep fixed one word per concept. These "
        "strings use a retired one:\n  " + "\n  ".join(hits) +
        "\nUse: computer / the CC Sync tray / tick / sync plan / upload / "
        "proxy download / folder sync / paused / stopped by your admin / "
        "stopped itself.")


def test_the_allow_list_is_still_earned() -> None:
    """An allow-list entry nobody matches is a stale excuse, and the next
    reader treats it as permission."""
    everything = "\n".join(
        p.read_text(encoding="utf-8") for p in
        sorted(STATIC.glob("*.js")) + sorted(STATIC.glob("*.html")))
    unused = [k for k in ALLOWED if k not in everything]
    assert not unused, f"ALLOWED entries that match nothing any more: {unused}"


def test_the_tray_is_named_the_same_way_everywhere() -> None:
    """"the CC Sync tray" is the one name for the program (section 4). A page
    that says "the companion app" and one that says "the tray app" read as two
    products, which is how this test's subject started."""
    for path in sorted(STATIC.glob("*.js")) + sorted(STATIC.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        for line, literal in (js_strings(text) if path.suffix == ".js"
                              else html_copy(text)):
            for banned in ("companion app", "tray app", "ccsync companion"):
                assert banned not in literal.lower(), (
                    f"{path.name}:{line}: {banned!r} - the program is "
                    '"the CC Sync tray"')


def test_send_to_resolve_still_names_the_self_test() -> None:
    """The rewrite must not lose the one thing an editor can act on: a blocked
    fetch and a stopped tray look identical, and /status in a tab is what
    tells them apart (2026-08-12)."""
    for name in ("app.js", "ingest.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert "http://127.0.0.1:8899/status" in text, name
