"""/help: the customer guide, served (UX-3 / SYS-21a, wave 4, 2026-09-04).

Nothing in the product linked to any documentation before this. `/help`
renders the deployed `docs/HOW_IT_WORKS.md` behind the login gate, with a
stable anchor per heading and per glossary term, because four surfaces deep-
link into it and a silently broken anchor reads exactly like a working one.

The renderer is stdlib-only on purpose (`markdown` is not in
requirements.lock), so it carries its own tests: a hand-written renderer that
nobody tests is a page that renders a table as one long paragraph the first
time somebody adds a column.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, help as help_page
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-value-help-1234567890"
REPO_DOC = Path(__file__).resolve().parents[2] / "docs" / "HOW_IT_WORKS.md"


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                              admin_users=frozenset({"owen"})))
    with TestClient(app) as c:
        yield c


def as_user(client, user="jsmith"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


# ------------------------------------------------------------- the document


def test_the_guide_is_found_beside_the_package():
    """The deployed shape first, the checkout last. `install_dashboard_app.py`
    ships the `dashboard/` tree as `app` and nothing else, so on a server
    today the answer comes from the last candidate or from DASH_HELP_DOC."""
    names = [str(p) for p in help_page._candidates()]
    assert names[0].endswith(str(Path("docs") / "HOW_IT_WORKS.md"))
    assert any(str(REPO_DOC) == n for n in names)
    assert help_page.document_path() is not None


def test_a_server_without_the_guide_says_so_rather_than_500ing(monkeypatch):
    monkeypatch.setattr(help_page, "_candidates", lambda: [Path("/nowhere/x.md")])
    context = help_page.page_context()
    assert context["help_html"] == ""
    assert "not installed on this server" in context["help_missing"]


def test_an_override_wins(monkeypatch, tmp_path):
    doc = tmp_path / "guide.md"
    doc.write_text("# Hi\n\nthere\n", encoding="utf-8")
    monkeypatch.setenv("DASH_HELP_DOC", str(doc))
    assert help_page.document_path() == doc


# -------------------------------------------------------------- the renderer


def test_headings_get_stable_numbering_free_ids():
    body, toc = help_page.render_markdown(
        "# Title\n\n## 4. The three ways files move\n\n### 4.1 Your sync plan\n")
    assert '<h2 id="the-three-ways-files-move">' in body
    assert '<h3 id="your-sync-plan">' in body
    # The contents list is built from the same headings, so a new section
    # cannot appear on the page and not in the list.
    assert [e["id"] for e in toc] == ["the-three-ways-files-move", "your-sync-plan"]


def test_a_repeated_heading_still_gets_two_ids():
    body, _toc = help_page.render_markdown("## Proxies\n\ntext\n\n## Proxies\n\nmore\n")
    assert '<h2 id="proxies">' in body and '<h2 id="proxies-2">' in body


def test_lists_tables_code_and_inline_marks():
    body, _ = help_page.render_markdown(
        "- one\n- two\n\n1. first\n2. second\n\n"
        "| A | B |\n|---|---|\n| x | y |\n\n"
        "```\nsome code\n```\n\n"
        "A **bold** word, a `path/here` and a [link](https://example.com).\n")
    assert "<ul>\n<li>one</li>\n<li>two</li>\n</ul>" in body
    assert "<ol>" in body and "<li>first</li>" in body
    assert "<th>A</th>" in body and "<td>y</td>" in body
    assert "<pre><code>some code</code></pre>" in body
    assert "<strong>bold</strong>" in body
    assert "<code>path/here</code>" in body
    assert '<a href="https://example.com">link</a>' in body


def test_a_nested_bullet_under_a_numbered_step_survives():
    body, _ = help_page.render_markdown(
        "1. **The wizard.** Four steps:\n\n"
        "   - *Step 1.* How is this computer connected.\n"
        "   - *Step 2.* Join the network.\n\n"
        "2. Sign in at the tray.\n")
    assert body.count("<li>") >= 4
    assert "Step 1." in body and "Sign in at the tray." in body


def test_the_document_is_escaped_and_carries_no_html_through():
    """The guide is prose, and a renderer that trusted it would be an
    injection surface the moment somebody pasted an error message in."""
    body, _ = help_page.render_markdown(
        '## X\n\nA <script>alert(1)</script> and a "quote".\n\n'
        "| If you see | It means |\n|---|---|\n"
        '| "Sync engine will not start: <why>" | it did not |\n')
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "&lt;why&gt;" in body


def test_an_unsafe_link_is_rendered_as_text():
    body, _ = help_page.render_markdown("See [this](javascript:alert(1)).\n")
    assert "javascript:" not in body
    assert "this" in body


# --------------------------------------------------------------- the anchors


def test_every_glossary_row_is_its_own_anchor():
    body, _ = help_page.render_markdown(REPO_DOC.read_text(encoding="utf-8"))
    assert f'id="{help_page.GLOSSARY_ID}"' in body
    for term in ("sync plan", "tick", "computer", "wired", "remote", "upload",
                 "proxy download", "folder sync", "upload only", "paused",
                 "stopped by your admin", "stopped itself", "sync status",
                 "copy diagnostics"):
        anchor = help_page.TERM_PREFIX + help_page.slugify(term)
        assert f'id="{anchor}"' in body, f"{term} has no glossary row"


def test_the_four_surfaces_deep_link_into_the_glossary():
    """UX-3 named four places the vocabulary appears. Each has to point at a
    target that exists, which is the half a rename breaks silently."""
    from ccsync_dashboard import ui

    templates = Path(__file__).resolve().parents[1] / "templates"
    body, _ = help_page.render_markdown(REPO_DOC.read_text(encoding="utf-8"))
    for name in ("partials/fleet_grid.html", "partials/project_detail.html",
                 "partials/sidebar.html", "partials/topbar.html",
                 "admin_assignments.html"):
        text = (templates / name).read_text(encoding="utf-8")
        assert ("GLOSSARY_HREF" in text or "term_href" in text
                or 'href="/help"' in text), name
    assert ui.GLOSSARY_HREF == "/help#glossary"
    assert ui.term_href("Upload only") == "/help#term-upload-only"
    assert f'id="{ui.term_href("Upload only").split("#")[1]}"' in body


# ------------------------------------------------------------------ the page


def test_the_page_needs_a_session(client):
    resp = client.get("/help", follow_redirects=False)
    assert resp.status_code in (302, 303, 401, 403)


def test_an_editor_can_read_it(client):
    page = as_user(client).get("/help")
    assert page.status_code == 200
    assert "[ HELP ]" in page.text
    assert "How CC Sync works" in page.text
    assert 'id="glossary"' in page.text
    # The strip is admin furniture; an editor gets the document.
    assert "settings-nav" not in page.text


def test_an_admin_gets_the_strip_with_help_marked(client):
    page = as_user(client, "owen").get("/help")
    assert page.status_code == 200
    assert 'settings-nav-current" href="/help"' in page.text


def test_a_missing_document_renders_a_sentence_not_a_stack_trace(client, monkeypatch):
    monkeypatch.setattr(help_page, "_candidates", lambda: [Path("/nowhere/x.md")])
    page = as_user(client).get("/help")
    assert page.status_code == 200
    assert "not installed on this server" in page.text


def test_the_title_carries_the_brand(client):
    page = as_user(client).get("/help")
    assert re.search(r"<title>[^<]*HELP</title>", page.text)
    assert "<title>CC SYNC: HELP</title>" in page.text
