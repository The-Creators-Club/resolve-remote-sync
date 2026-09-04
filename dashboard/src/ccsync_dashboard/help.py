"""The customer explainer, served from the dashboard (UX-3 / SYS-21a).

`docs/HOW_IT_WORKS.md` is 788 lines of prose written for producers and
editors, and until this module nothing in the product linked to any document
at all: the only way to read it was to have the repository. The sweep's
answer was one route, one nav entry and one glossary the four surfaces that
use the vocabulary deep-link into.

WHERE THE DOCUMENT IS. `server/install_dashboard_app.py` ships the whole
`dashboard/` tree as the container's `app` and nothing else, so the repo's
`docs/` directory is NOT on a deployed server today. The search order below
starts with the two places a deploy could put it (an explicit
`DASH_HELP_DOC`, then `<app>/docs/`) and ends at the repo checkout beside the
package, which is what makes this work on a dev box. When none of them
answers, the route says so in one sentence rather than 500ing: a help page
that raises is worse than a help page that admits it is not installed.

THE ROUTE ITSELF is `ui.page_help`, not a router here. FastAPI mounts an
`include_router` lazily as an `_IncludedRouter` with no `.path`, so a route
added that way is invisible to every "does this route exist" check in the
suite (the Settings strip's own test is one). This module owns the document,
the renderer and the page's context; ui.py owns the two lines that publish
them, next to every other page.

NO NEW DEPENDENCY. `markdown` is not in dashboard/requirements.lock and this
is not worth adding one for, so `render_markdown` below is a small renderer
for the subset HOW_IT_WORKS.md actually uses: setext-free headings with
stable ids, paragraphs, bullet and numbered lists with one level of nesting,
fenced code, pipe tables, horizontal rules, and inline code / bold / italic /
links. Everything is escaped on the way in; no HTML in the document is passed
through, because the document is prose and a renderer that trusted it would
be an injection surface the moment someone pasted a customer's error message
into it.
"""
from __future__ import annotations

import html
import logging
import os
import re
from pathlib import Path

log = logging.getLogger("ccsync.dashboard.help")

DOC_NAME = "HOW_IT_WORKS.md"

# The deployed app root: .../app on the NAS, .../dashboard in a checkout.
_APP_ROOT = Path(__file__).resolve().parents[2]

# The sentence an admin sees when no copy of the document exists on this
# server. It names the file, because the person who can fix it is the person
# who deployed the server.
NOT_INSTALLED = (
    "Help is not installed on this server. The guide ships as "
    f"docs/{DOC_NAME}; ask whoever deployed this dashboard to put a copy "
    "beside the application."
)

# The glossary's own heading id, and the prefix each term row is anchored
# with. Four surfaces link in here (the sync line and the status chips on
# SYNC STATUS, the tick modes on SYNC PLANS, and the topbar's [ ? ]), so
# these two strings are load-bearing: a heading rename that changed the slug
# would break every one of those links silently.
GLOSSARY_ID = "glossary"
TERM_PREFIX = "term-"


def document_path() -> Path | None:
    """The first copy of the guide this server can read, or None.

    Never raises: an unreadable path is one candidate skipped, not a 500 on
    the page an admin opened because something else was already wrong.
    """
    for candidate in _candidates():
        try:
            if candidate.is_file():
                return candidate
        except OSError:  # noqa: PERF203 - a candidate on a dead mount
            continue
    return None


def _candidates() -> list[Path]:
    out: list[Path] = []
    # An explicit override first, for a deploy that puts the docs somewhere
    # of its own. Read from the environment rather than Settings because a
    # site that never sets it must cost nothing.
    override = os.environ.get("DASH_HELP_DOC", "").strip()
    if override:
        out.append(Path(override))
    out.extend([
        _APP_ROOT / "docs" / DOC_NAME,
        _APP_ROOT / DOC_NAME,
        # The repo checkout beside the package: dashboard/../docs.
        _APP_ROOT.parent / "docs" / DOC_NAME,
    ])
    return out


def read_document() -> str | None:
    path = document_path()
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        log.exception("could not read the help document at %s", path)
        return None


# ---------------------------------------------------------------- rendering

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^```+\s*([A-Za-z0-9_+-]*)\s*$")
_HRULE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})\s*$")
_BULLET = re.compile(r"^(\s*)[-*]\s+(.*)$")
_NUMBER = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
# The leading section number in a heading ("4.1 Your sync plan..."), dropped
# from the id so a renumbering of the document does not break a deep link.
_LEAD_NUMBER = re.compile(r"^\d+(?:\.\d+)*\.?\s+")

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_SAFE_HREF = re.compile(r"^(https?://|mailto:|/|#)")


def slugify(text: str) -> str:
    """A heading's anchor id. Deterministic, ASCII, and numbering-free."""
    text = _LEAD_NUMBER.sub("", text.strip())
    text = re.sub(r"[`*_]", "", text)
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text or "section"


def _inline(text: str) -> str:
    """One line of markdown to HTML. Escaped first, marked up after.

    The order matters: code spans are extracted BEFORE the emphasis passes,
    so `**` inside a path or a shell line is never read as bold.
    """
    text = html.escape(text, quote=False)
    spans: list[str] = []

    def keep(m: re.Match) -> str:
        spans.append(m.group(1))
        return f"\x00{len(spans) - 1}\x00"

    text = _INLINE_CODE.sub(keep, text)
    text = _LINK.sub(_link_html, text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)

    def restore(m: re.Match) -> str:
        return f"<code>{spans[int(m.group(1))]}</code>"

    return re.sub(r"\x00(\d+)\x00", restore, text)


def _link_html(m: re.Match) -> str:
    label, href = m.group(1), m.group(2)
    # A link the document offers that is not http(s), a page-relative path or
    # a fragment is rendered as TEXT, not a link: `javascript:` and `data:`
    # have no business in a rendered document, and neither does a relative
    # `docs/SERVER.md` that would 404 on this server.
    if not _SAFE_HREF.match(href):
        return html.escape(label, quote=False)
    return f'<a href="{html.escape(href, quote=True)}">{label}</a>'


def render_markdown(text: str) -> tuple[str, list[dict[str, str]]]:
    """(html, table of contents). The TOC carries every h2 and h3.

    Glossary term rows get `id="term-<slug>"` on the <tr> (see GLOSSARY_ID):
    the vocabulary the sweep settled on is a table, and the four surfaces
    that link a word to its meaning need a per-term target rather than a
    scroll to the top of a fifteen-row table.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    toc: list[dict[str, str]] = []
    seen: dict[str, int] = {}
    section = ""
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        fence = _FENCE.match(line)
        if fence:
            i += 1
            body: list[str] = []
            while i < n and not _FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1  # the closing fence
            out.append("<pre><code>"
                       + html.escape("\n".join(body), quote=False)
                       + "</code></pre>")
            continue
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2)
            slug = slugify(title)
            if slug in seen:
                seen[slug] += 1
                slug = f"{slug}-{seen[slug]}"
            else:
                seen[slug] = 1
            section = slug
            out.append(f'<h{level} id="{slug}">{_inline(title)}</h{level}>')
            if level in (2, 3):
                toc.append({"id": slug, "level": str(level),
                            "text": re.sub(r"[`*]", "", title)})
            i += 1
            continue
        if _HRULE.match(line) and not _BULLET.match(line):
            out.append("<hr>")
            i += 1
            continue
        if not line.strip():
            i += 1
            continue
        if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
            i = _table(lines, i, out, section)
            continue
        if _BULLET.match(line) or _NUMBER.match(line):
            i = _list(lines, i, out)
            continue
        i = _paragraph(lines, i, out)
    return "\n".join(out), toc


def _cells(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def _table(lines: list[str], i: int, out: list[str], section: str) -> int:
    header = _cells(lines[i])
    i += 2
    out.append('<div class="scroll-x"><table class="help-table">')
    out.append("<thead><tr>"
               + "".join(f"<th>{_inline(c)}</th>" for c in header)
               + "</tr></thead><tbody>")
    while i < len(lines) and lines[i].strip() and "|" in lines[i]:
        cells = _cells(lines[i])
        anchor = ""
        if section == GLOSSARY_ID and cells:
            anchor = f' id="{TERM_PREFIX}{slugify(cells[0])}"'
        out.append(f"<tr{anchor}>"
                   + "".join(f"<td>{_inline(c)}</td>" for c in cells)
                   + "</tr>")
        i += 1
    out.append("</tbody></table></div>")
    return i


def _list(lines: list[str], i: int, out: list[str]) -> int:
    ordered = _NUMBER.match(lines[i]) is not None
    tag = "ol" if ordered else "ul"
    out.append(f"<{tag}>")
    items: list[list[str]] = []
    base_indent: int | None = None
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            # A blank line inside a list only ends it when the next non-blank
            # line is not a continuation: HOW_IT_WORKS.md's numbered steps are
            # separated by blank lines and are still one list.
            nxt = i + 1
            while nxt < len(lines) and not lines[nxt].strip():
                nxt += 1
            if nxt >= len(lines):
                i = nxt
                break
            follow = lines[nxt]
            if not (_BULLET.match(follow) or _NUMBER.match(follow)
                    or (follow.startswith(" ") and items)):
                i = nxt
                break
            i = nxt
            continue
        m_b, m_n = _BULLET.match(line), _NUMBER.match(line)
        m = m_n or m_b
        if m is None:
            if not items or not line.startswith(" "):
                break
            items[-1].append(line.strip())
            i += 1
            continue
        indent = len(m.group(1))
        if base_indent is None:
            base_indent = indent
        text = m.group(3) if m is m_n else m.group(2)
        if indent > base_indent and items:
            items[-1].append("\x01" + text)
        else:
            if (m_n is not None) != ordered and indent == base_indent:
                break
            items.append([text])
        i += 1
    for item in items:
        nested = [p[1:] for p in item if p.startswith("\x01")]
        body = " ".join(p for p in item if not p.startswith("\x01"))
        html_item = _inline(body)
        if nested:
            html_item += ("<ul>"
                          + "".join(f"<li>{_inline(x)}</li>" for x in nested)
                          + "</ul>")
        out.append(f"<li>{html_item}</li>")
    out.append(f"</{tag}>")
    return i


def _paragraph(lines: list[str], i: int, out: list[str]) -> int:
    body: list[str] = []
    while i < len(lines) and lines[i].strip():
        line = lines[i]
        if (_HEADING.match(line) or _FENCE.match(line) or _HRULE.match(line)
                or _BULLET.match(line) or _NUMBER.match(line)):
            break
        body.append(line.strip())
        i += 1
    if body:
        out.append(f"<p>{_inline(' '.join(body))}</p>")
    return i


def page_context() -> dict:
    """What the /help template needs: the rendered guide, or the refusal."""
    text = read_document()
    if text is None:
        return {"help_html": "", "help_toc": [], "help_missing": NOT_INSTALLED}
    body, toc = render_markdown(text)
    return {"help_html": body, "help_toc": toc, "help_missing": ""}
