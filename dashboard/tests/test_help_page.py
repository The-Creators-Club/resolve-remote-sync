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


def _no_docs(monkeypatch):
    """A server that received no documents at all. Both search orders have to
    be blanked: one finds the guide, the other finds the tree."""
    monkeypatch.setattr(help_page, "_candidates", lambda: [Path("/nowhere/x.md")])
    monkeypatch.setattr(help_page, "_root_candidates", lambda: [Path("/nowhere/docs")])


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
    _no_docs(monkeypatch)
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
    _no_docs(monkeypatch)
    page = as_user(client).get("/help")
    assert page.status_code == 200
    assert "not installed on this server" in page.text


def test_the_title_carries_the_brand(client):
    page = as_user(client).get("/help")
    assert re.search(r"<title>[^<]*HELP</title>", page.text)
    assert "<title>CC SYNC: HELP</title>" in page.text


# --------------------------------------------------------------- the browser
#
# Every document in the repository, browsable, and rendered by this same
# viewer (Alex, 2026-09-04). The tests below build a FAKE docs tree rather
# than leaning on the checkout: what is being pinned is the layout rule (what
# is listed, what may be served, how a link between two documents resolves),
# and a test written against the real tree would change every time somebody
# added a runbook.


@pytest.fixture
def docs(tmp_path, monkeypatch):
    root = tmp_path / "app" / "docs"
    (root / "legal").mkdir(parents=True)
    (root / "spikes").mkdir()
    (root / "_root").mkdir()
    (root / "HOW_IT_WORKS.md").write_text(
        "# How CC Sync works\n\nSee [the gotchas](GOTCHAS.md#section-15) and\n"
        "[the ledger](../KNOWN_BUGS.md) and [the script](../tools/ship.cmd).\n",
        encoding="utf-8")
    (root / "GOTCHAS.md").write_text("# Gotchas\n\n## 15. Resolve\n\ntext\n",
                                     encoding="utf-8")
    (root / "legal" / "EULA.md").write_text("# Licence\n\nterms\n", encoding="utf-8")
    (root / "spikes" / "s1.md").write_text("no heading here\n", encoding="utf-8")
    (root / "_root" / "KNOWN_BUGS.md").write_text(
        "# Known bugs\n\nBack to [the guide](docs/HOW_IT_WORKS.md).\n",
        encoding="utf-8")
    # The things that must NOT be listed or served.
    (root / "mobile.png").write_bytes(b"\x89PNG\r\n")
    (tmp_path / "secret.md").write_text("# Secret\n\nnot in the tree\n",
                                        encoding="utf-8")
    monkeypatch.setattr(help_page, "_root_candidates", lambda: [root])
    monkeypatch.setattr(help_page, "_candidates",
                        lambda: [root / "HOW_IT_WORKS.md"])
    return root


def test_the_index_lists_the_shipped_tree_grouped_and_titled(docs):
    groups = help_page.document_groups()
    labels = [g["label"] for g in groups]
    assert labels == ["docs/", "top level", "docs/legal/", "docs/spikes/"]
    first = groups[0]["entries"][0]
    # The guide leads, and says what it is: it is the one document written
    # for a customer rather than for us.
    assert first["rel"] == "HOW_IT_WORKS.md"
    assert first["title"] == "How CC Sync works"
    assert first["note"] == "the customer explainer"
    assert groups[0]["entries"][1]["title"] == "Gotchas"
    # A document with no heading is listed under its filename rather than
    # under a blank.
    assert groups[3]["entries"][0]["title"] == "s1.md"
    # Nothing that is not markdown, in any group.
    assert all(e["rel"].endswith(".md") for g in groups for e in g["entries"])


def test_a_document_from_the_tree_renders_in_the_same_viewer(docs):
    context = help_page.page_context("legal/EULA.md")
    assert context["help_current"] == "legal/EULA.md"
    assert context["help_doc_title"] == "Licence"
    assert "<p>terms</p>" in context["help_html"]
    assert context["help_missing"] == "" and not context["help_not_found"]


def test_a_heading_in_any_document_keeps_the_stable_anchor_ids(docs):
    context = help_page.page_context("GOTCHAS.md")
    assert '<h2 id="resolve">' in context["help_html"]


def test_a_link_between_two_documents_becomes_a_help_route(docs):
    body = help_page.page_context("HOW_IT_WORKS.md")["help_html"]
    # A sibling, with its anchor kept: the fragment is the half of a
    # cross-reference that is silently wrong when it is dropped.
    assert '<a href="/help/GOTCHAS.md#section-15">the gotchas</a>' in body
    # `../KNOWN_BUGS.md` is written from docs/, and the browser keeps the
    # top-level documents under _root/.
    assert '<a href="/help/_root/KNOWN_BUGS.md">the ledger</a>' in body
    # A link to something that is not a document we serve stays TEXT, and
    # carries the path so the reader is told where it is.
    assert "the script (../tools/ship.cmd)" in body
    assert 'ship.cmd">' not in body


def test_a_link_from_a_top_level_document_resolves_the_other_way(docs):
    body = help_page.page_context("_root/KNOWN_BUGS.md")["help_html"]
    assert '<a href="/help/HOW_IT_WORKS.md">the guide</a>' in body


def test_a_link_that_leaves_the_tree_is_not_a_link():
    assert help_page.help_href("../../../etc/passwd.md", "HOW_IT_WORKS.md") == ""
    assert help_page.help_href("../secret.md", "HOW_IT_WORKS.md") == ""
    assert help_page.help_href("logo.png", "HOW_IT_WORKS.md") == ""


@pytest.mark.parametrize("rel", [
    "../secret.md",
    "legal/../../secret.md",
    "/etc/passwd.md",
    "C:/Windows/win.ini.md",
    "..\\secret.md",
    "GOTCHAS.txt",
    "_root/../../secret.md",
    "_root/site.toml.md",
])
def test_a_path_that_leaves_the_docs_root_is_refused(docs, rel):
    """One place decides what may be served, so this is the whole check for
    the route as well: markdown only, inside the root, no dot-dot."""
    assert help_page.resolve_document(rel) is None


def test_a_symlink_out_of_the_tree_is_refused(docs, tmp_path):
    link = docs / "escape.md"
    try:
        link.symlink_to(tmp_path / "secret.md")
    except (OSError, NotImplementedError):  # Windows without the privilege
        pytest.skip("this account cannot create symlinks")
    assert help_page.resolve_document("escape.md") is None
    assert all(e["rel"] != "escape.md"
               for g in help_page.document_groups() for e in g["entries"])


def test_a_top_level_document_is_only_reachable_by_the_allow_list(docs):
    assert help_page.resolve_document("_root/KNOWN_BUGS.md") is not None
    (docs / "_root" / "notes.md").write_text("# Notes\n", encoding="utf-8")
    assert help_page.resolve_document("_root/notes.md") is None


def test_a_server_with_no_docs_tree_says_so_rather_than_500ing(monkeypatch):
    _no_docs(monkeypatch)
    context = help_page.page_context()
    assert context["help_groups"] == []
    assert "not installed on this server" in context["help_missing"]


def test_a_document_this_server_does_not_carry_says_so_with_the_index(docs):
    context = help_page.page_context("NOPE.md")
    assert context["help_not_found"] is True
    assert "not on this server" in context["help_missing"]
    # ...and the list is still there, because the reader followed a link.
    assert context["help_groups"]


def test_a_thirteen_thousand_line_document_renders_in_reasonable_time(docs):
    """KNOWN_BUGS.md is ~14,000 lines and ~950 KB, and it is now one click
    from every page. Measured at ~30 ms on the base rig, 2026-09-04; the
    bound here is loose enough to survive a slow CI box and tight enough to
    catch a renderer that went quadratic."""
    import time

    block = ("### CR-{n} - a defect - FIXED\n\n"
             "Some prose with a [link](GOTCHAS.md#x) and **bold**.\n\n"
             "- a bullet\n- another\n\n"
             "| A | B |\n|---|---|\n| x | y |\n\n")
    text = "# Known bugs\n\n" + "".join(block.format(n=i) for i in range(1300))
    assert text.count("\n") >= 13000
    (docs / "_root" / "KNOWN_BUGS.md").write_text(text, encoding="utf-8")
    started = time.perf_counter()
    context = help_page.page_context("_root/KNOWN_BUGS.md")
    elapsed = time.perf_counter() - started
    assert 'id="cr-0-a-defect-fixed"' in context["help_html"]
    assert elapsed < 2.0, f"rendering took {elapsed:.2f}s"


# ------------------------------------------------------------- the two routes


def test_the_bare_help_url_is_still_the_guide(client):
    """The topbar's help link, the Settings strip and every /help#term-...
    deep link in the product point at /help, and they must keep landing on
    the same document with the same anchors."""
    page = as_user(client).get("/help")
    assert page.status_code == 200
    assert "How CC Sync works" in page.text
    assert 'id="glossary"' in page.text
    assert 'id="term-upload-only"' in page.text


def test_the_page_lists_the_documents_and_lights_the_current_one(client, docs):
    page = as_user(client).get("/help/GOTCHAS.md")
    assert page.status_code == 200
    assert "[ DOCUMENTS ]" in page.text
    assert 'href="/help/legal/EULA.md"' in page.text
    assert 'class="help-file help-file-current"' in page.text
    assert "Gotchas" in page.text


def test_a_document_route_needs_a_session(client):
    resp = client.get("/help/GOTCHAS.md", follow_redirects=False)
    assert resp.status_code in (302, 303, 401, 403)


def test_a_traversal_over_the_route_is_a_404_with_the_index(client, docs):
    """Percent-encoded, because an http client normalises a literal `../` out
    of the URL before it is sent and the interesting case is the one the
    server actually receives."""
    for path in ("/help/%2e%2e/secret.md", "/help/..%2f..%2fsecret.md",
                 "/help//etc/passwd.md", "/help/C:/Windows/win.ini.md"):
        resp = as_user(client).get(path)
        assert resp.status_code == 404, path
        assert "not on this server" in resp.text, path
        assert "not in the tree" not in resp.text, path
