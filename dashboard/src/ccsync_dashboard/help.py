"""The documentation browser, served from the dashboard (UX-3 / SYS-21a).

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

EVERY DOCUMENT, NOT ONE (Alex, 2026-09-04). The page started as a single
rendered guide; the owner asked to see every markdown file the repository
carries and to read them in this same viewer. So the three shipping routes
(the image's COPY, the OTA bundle's TREES, install_dashboard_app's bind-mode
copy) now carry the whole `docs/` tree plus the four top-level documents
(README / KNOWN_BUGS / SPEC / CLAUDE) under `docs/_root/`, and this module
grew an INDEX (`document_root`, `document_groups`) and a per-file route
(`resolve_document`).

WHAT MAY BE SERVED, exactly: a `.md` file underneath the docs root this
server found, reached by a relative path with no `..` segment, no drive
letter, no leading slash, and whose realpath is still inside that root (a
symlink pointing out is refused by the same test). The one deliberate
exception is `_root/<NAME>` for the four allow-listed top-level documents,
which in a dev checkout live beside `docs/` rather than inside it. Nothing
here takes a path from the document tree itself, and nothing writes.
"""
from __future__ import annotations

import html
import logging
import os
import posixpath
import re
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger("ccsync.dashboard.help")

DOC_NAME = "HOW_IT_WORKS.md"

# Where the repository's top-level documents land inside the shipped docs
# tree, and which ones travel. An allow-list rather than "every .md beside
# docs/", because on a deployed server that directory is the application root.
ROOT_DIR_NAME = "_root"
ROOT_FILES = ("README.md", "SPEC.md", "KNOWN_BUGS.md", "CLAUDE.md")

# The deployed app root: .../app on the NAS, .../dashboard in a checkout.
_APP_ROOT = Path(__file__).resolve().parents[2]

# The sentence an admin sees when no copy of the documents exists on this
# server. It names the tree, because the person who can fix it is the person
# who deployed the server.
NOT_INSTALLED = (
    "Help is not installed on this server. The documents ship as the "
    f"docs/ tree (the guide itself is docs/{DOC_NAME}); ask whoever "
    "deployed this dashboard to put a copy beside the application."
)

# What a link to a document this server does not carry says. Not a 500, and
# not a blank page: the reader followed a link inside a document we rendered.
NOT_FOUND = (
    "That document is not on this server. It may be one this build does not "
    "ship, or the link inside the document you came from may be stale."
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


# ------------------------------------------------------------------- the tree


def document_root() -> Path | None:
    """The docs directory this server can read, or None.

    Same search order as `_candidates` one level up: an explicit override
    first, then the deployed `<app>/docs`, then the repo checkout beside the
    package. Never raises, for the reason `document_path` does not.
    """
    for candidate in _root_candidates():
        try:
            if candidate.is_dir():
                return candidate
        except OSError:  # noqa: PERF203 - a candidate on a dead mount
            continue
    return None


def _root_candidates() -> list[Path]:
    out: list[Path] = []
    # DASH_HELP_DOCS_ROOT names the TREE; DASH_HELP_DOC (older, kept because a
    # site may already set it) names one file, and its directory is a
    # perfectly good root.
    tree = os.environ.get("DASH_HELP_DOCS_ROOT", "").strip()
    if tree:
        out.append(Path(tree))
    override = os.environ.get("DASH_HELP_DOC", "").strip()
    if override:
        out.append(Path(override).parent)
    out.extend([
        _APP_ROOT / "docs",
        _APP_ROOT.parent / "docs",
    ])
    return out


def _title_of(path: Path) -> str:
    """A document's first `# ` heading, or "" if it has none.

    Reads the head of the file only: the index lists ~120 documents and one
    of them is 950 KB, so this must not be "read it all and regex it".
    """
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for _ in range(60):
                line = fh.readline()
                if not line:
                    break
                m = _HEADING.match(line.rstrip("\n"))
                if m and len(m.group(1)) == 1:
                    return re.sub(r"[`*]", "", m.group(2)).strip()
    except OSError:
        return ""
    return ""


def _iter_markdown(root: Path) -> list[str]:
    """Every `.md` under `root`, as posix paths relative to it. Sorted."""
    out: list[str] = []
    try:
        for path in root.rglob("*.md"):
            try:
                if not path.is_file() or path.is_symlink():
                    continue
            except OSError:
                continue
            out.append(path.relative_to(root).as_posix())
    except OSError:
        log.exception("could not walk the docs tree at %s", root)
    return sorted(out)


def document_groups() -> list[dict]:
    """The index: [{label, entries: [{rel, name, title, note}]}].

    Grouped by the folder a document lives in, because 120 files in one list
    is not a browser. The guide comes first and is labelled, since it is the
    one document written for a customer rather than for us.
    """
    root = document_root()
    if root is None:
        return []
    rels = _iter_markdown(root)
    for name in ROOT_FILES:
        rel = f"{ROOT_DIR_NAME}/{name}"
        if rel not in rels and resolve_document(rel) is not None:
            # The dev-checkout half: the top-level documents are beside the
            # tree, not in it, so the walk above never sees them.
            rels.append(rel)
    groups: dict[str, list[dict]] = {}
    for rel in rels:
        folder = posixpath.dirname(rel)
        entry = {"rel": rel, "name": posixpath.basename(rel),
                 "title": "", "note": ""}
        path = resolve_document(rel)
        if path is None:
            continue
        entry["title"] = _title_of(path) or entry["name"]
        if rel == DOC_NAME:
            entry["note"] = "the customer explainer"
        groups.setdefault(folder, []).append(entry)
    out: list[dict] = []
    for folder in sorted(groups, key=_group_order):
        entries = sorted(groups[folder], key=lambda e: (e["rel"] != DOC_NAME,
                                                        e["name"].lower()))
        out.append({"label": _group_label(folder), "folder": folder,
                    "entries": entries})
    return out


def _group_order(folder: str) -> tuple:
    # docs/ itself first, the repository's own top-level documents next, then
    # the subfolders alphabetically.
    if folder == "":
        return (0, "")
    if folder == ROOT_DIR_NAME:
        return (1, "")
    return (2, folder.lower())


def _group_label(folder: str) -> str:
    if folder == "":
        return "docs/"
    if folder == ROOT_DIR_NAME:
        return "top level"
    return f"docs/{folder}/"


def resolve_document(rel: str) -> Path | None:
    """The file `rel` names inside the docs tree, or None if it may not be
    served. Every refusal is a None: the caller renders one sentence.

    THE RULES (Alex, 2026-09-04). A path from a URL reaches this function, so
    the checks are stated once, here, and the route has none of its own:
    markdown only, no absolute path, no drive letter, no `..` segment, and
    the realpath must still be inside the root - which is also what refuses a
    symlink that points out of the tree.
    """
    root = document_root()
    if root is None:
        return None
    rel = (rel or "").strip().replace("\\", "/")
    if not rel or not rel.lower().endswith(".md"):
        return None
    if rel.startswith("/") or ":" in rel or "\x00" in rel:
        return None
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    try:
        root_real = root.resolve()
    except OSError:
        return None
    if parts[0] == ROOT_DIR_NAME:
        # `_root/KNOWN_BUGS.md`: shipped INTO the tree by every deploy path,
        # and beside it in a dev checkout. The allow-list is what keeps the
        # second case from being "serve anything next to the application".
        if len(parts) != 2 or parts[1] not in ROOT_FILES:
            return None
        shipped = root_real / ROOT_DIR_NAME / parts[1]
        checkout = root_real.parent / parts[1]
        for candidate in (shipped, checkout):
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
        return None
    candidate = root_real.joinpath(*parts)
    try:
        real = candidate.resolve()
        if not real.is_relative_to(root_real):
            return None
        if not real.is_file():
            return None
    except OSError:
        return None
    return real


def read_rel(rel: str) -> str | None:
    path = resolve_document(rel)
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        log.exception("could not read the document at %s", path)
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
# Any other scheme (`javascript:`, `data:`, `file:`). Matched BEFORE the
# document-relative pass, which would otherwise read "javascript:x.md" as a
# path.
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def slugify(text: str) -> str:
    """A heading's anchor id. Deterministic, ASCII, and numbering-free."""
    text = _LEAD_NUMBER.sub("", text.strip())
    text = re.sub(r"[`*_]", "", text)
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text or "section"


def _inline(text: str, base: str = "") -> str:
    """One line of markdown to HTML. Escaped first, marked up after.

    The order matters: code spans are extracted BEFORE the emphasis passes,
    so `**` inside a path or a shell line is never read as bold.

    `base` is the rel path of the document being rendered, which is what a
    relative link inside it is resolved against.
    """
    text = html.escape(text, quote=False)
    spans: list[str] = []

    def keep(m: re.Match) -> str:
        spans.append(m.group(1))
        return f"\x00{len(spans) - 1}\x00"

    text = _INLINE_CODE.sub(keep, text)
    text = _LINK.sub(lambda m: _link_html(m, base), text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)

    def restore(m: re.Match) -> str:
        return f"<code>{spans[int(m.group(1))]}</code>"

    return re.sub(r"\x00(\d+)\x00", restore, text)


def _link_html(m: re.Match, base: str = "") -> str:
    label, href = m.group(1), m.group(2)
    if _SAFE_HREF.match(href):
        return f'<a href="{html.escape(href, quote=True)}">{label}</a>'
    # A scheme we do not serve is rendered as TEXT: `javascript:` and `data:`
    # have no business in a rendered document.
    if _SCHEME.match(href):
        return html.escape(label, quote=False)
    target = help_href(href, base)
    if target:
        return f'<a href="{html.escape(target, quote=True)}">{label}</a>'
    # A relative link to something that is not a document we serve (a script,
    # an image, a path outside the tree). It stays TEXT, but it carries the
    # path: the reader is being told where the thing is on disk, which is the
    # only useful answer we have (Alex, 2026-09-04).
    return html.escape(f"{label} ({href})", quote=False)


def help_href(href: str, base: str) -> str:
    """The `/help/...` URL a document-relative link points at, or "".

    Documents cross-reference each other constantly (`[x](GOTCHAS.md#s)`,
    `../KNOWN_BUGS.md`), and the tree they were written for has `docs/` one
    level under the repository root. So a link is resolved in the REPOSITORY's
    coordinates and mapped back: `docs/X.md` is the browser's `X.md`, and a
    top-level document is the browser's `_root/X.md`. Anything that lands
    outside those two shapes gets no link at all.
    """
    path, _, fragment = href.partition("#")
    if not path:
        return ""
    if not path.lower().endswith(".md"):
        return ""
    here = _virtual(base)
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(here), path))
    rel = _from_virtual(resolved)
    if rel is None:
        return ""
    url = "/help/" + quote(rel)
    return f"{url}#{quote(fragment, safe='')}" if fragment else url


def _virtual(rel: str) -> str:
    """A browser rel path in the repository's own coordinates."""
    if rel.startswith(ROOT_DIR_NAME + "/"):
        return rel[len(ROOT_DIR_NAME) + 1:]
    return posixpath.join("docs", rel) if rel else "docs/"


def _from_virtual(path: str) -> str | None:
    if path.startswith("docs/"):
        return path[len("docs/"):]
    if "/" not in path and path in ROOT_FILES:
        return f"{ROOT_DIR_NAME}/{path}"
    return None


def render_markdown(text: str, base: str = "") -> tuple[str, list[dict[str, str]]]:
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
            out.append(f'<h{level} id="{slug}">{_inline(title, base)}</h{level}>')
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
            i = _table(lines, i, out, section, base)
            continue
        if _BULLET.match(line) or _NUMBER.match(line):
            i = _list(lines, i, out, base)
            continue
        i = _paragraph(lines, i, out, base)
    return "\n".join(out), toc


def _cells(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def _table(lines: list[str], i: int, out: list[str], section: str,
           base: str = "") -> int:
    header = _cells(lines[i])
    i += 2
    out.append('<div class="scroll-x"><table class="help-table">')
    out.append("<thead><tr>"
               + "".join(f"<th>{_inline(c, base)}</th>" for c in header)
               + "</tr></thead><tbody>")
    while i < len(lines) and lines[i].strip() and "|" in lines[i]:
        cells = _cells(lines[i])
        anchor = ""
        if section == GLOSSARY_ID and cells:
            anchor = f' id="{TERM_PREFIX}{slugify(cells[0])}"'
        out.append(f"<tr{anchor}>"
                   + "".join(f"<td>{_inline(c, base)}</td>" for c in cells)
                   + "</tr>")
        i += 1
    out.append("</tbody></table></div>")
    return i


def _list(lines: list[str], i: int, out: list[str], base: str = "") -> int:
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
        html_item = _inline(body, base)
        if nested:
            html_item += ("<ul>"
                          + "".join(f"<li>{_inline(x, base)}</li>" for x in nested)
                          + "</ul>")
        out.append(f"<li>{html_item}</li>")
    out.append(f"</{tag}>")
    return i


def _paragraph(lines: list[str], i: int, out: list[str], base: str = "") -> int:
    body: list[str] = []
    while i < len(lines) and lines[i].strip():
        line = lines[i]
        if (_HEADING.match(line) or _FENCE.match(line) or _HRULE.match(line)
                or _BULLET.match(line) or _NUMBER.match(line)):
            break
        body.append(line.strip())
        i += 1
    if body:
        out.append(f"<p>{_inline(' '.join(body), base)}</p>")
    return i


def page_context(rel: str = "") -> dict:
    """What the /help template needs: the index, one rendered document, or
    the refusal.

    `rel` empty means the guide, so `/help` (and every `/help#term-...` deep
    link in the product) still lands on HOW_IT_WORKS.md with its anchors
    intact. `help_not_found` is what the route turns into a 404 status; the
    page itself still renders, with the index, because the reader got here by
    following a link and a bare 404 tells them nothing.
    """
    groups = document_groups()
    rel = (rel or "").strip("/") or DOC_NAME
    base = {"help_groups": groups, "help_current": rel, "help_doc_title": "",
            "help_html": "", "help_toc": [], "help_missing": "",
            "help_not_found": False}
    if not groups and document_path() is None:
        base["help_missing"] = NOT_INSTALLED
        return base
    text = read_rel(rel)
    if text is None and rel == DOC_NAME:
        # The pre-browser search order still answers on a server that got the
        # single document and not the tree (an older bundle, DASH_HELP_DOC).
        text = read_document()
    if text is None:
        base["help_missing"] = NOT_FOUND
        base["help_not_found"] = True
        return base
    body, toc = render_markdown(text, rel)
    base["help_html"] = body
    base["help_toc"] = toc
    base["help_doc_title"] = _first_heading(text) or rel
    return base


def _first_heading(text: str) -> str:
    for line in text.split("\n", 60)[:60]:
        m = _HEADING.match(line.rstrip())
        if m and len(m.group(1)) == 1:
            return re.sub(r"[`*]", "", m.group(2)).strip()
    return ""
