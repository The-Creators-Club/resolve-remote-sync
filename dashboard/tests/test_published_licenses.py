"""LG-12: the licence TEXTS every binary carries are readable in /help too
(docs/LEGAL_GAP_FEATURES_PLAN.md §5, 2026-09-25).

`published_docs` published markdown only, so "one line" was never enough:
the audience rule, the resolver, the index walk, the link rewriter and the
page renderer all assumed `.md`. These pin the widening at exactly one
subtree, `legal/licenses/`, and nowhere else: a `.txt` elsewhere in docs/
stays unpublished for an editor AND unreadable for an admin.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, help as help_page, published_docs
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-value-licences-1234567890"


@pytest.mark.parametrize("rel", [
    "legal/licenses/companion/requests-2.32.3.txt",
    "legal/licenses/THIRD_PARTY_LICENSES.txt",
    "/legal/licenses/x.txt",
    "legal\\licenses\\x.txt",
])
def test_a_licence_text_under_legal_licenses_is_published(rel):
    assert published_docs.is_licence_text(rel)
    assert published_docs.is_published(rel)


@pytest.mark.parametrize("rel", [
    "legal/x.txt",                       # the legal tree, but not the licences
    "x.txt",
    "spikes/notes.txt",
    "legal/licenses/../x.txt",           # climbs out of the subtree
    "legal/licenses/../../secret.txt",
    "legal/licenses/x.txt.log",
    "legal/licensesX/x.txt",
    "",
])
def test_no_other_text_file_is_published(rel):
    assert not published_docs.is_licence_text(rel)
    assert not published_docs.is_published(rel)


def test_markdown_publishing_is_unchanged():
    assert published_docs.is_published("legal/EULA.md")
    assert published_docs.is_published("HOW_IT_WORKS.md")
    assert not published_docs.is_published("GOTCHAS.md")


@pytest.fixture
def docs(tmp_path, monkeypatch):
    root = tmp_path / "app" / "docs"
    (root / "legal" / "licenses" / "companion").mkdir(parents=True)
    (root / "spikes").mkdir()
    (root / "HOW_IT_WORKS.md").write_text("# How it works\n\ntext\n", encoding="utf-8")
    (root / "legal" / "THIRD_PARTY_NOTICES.md").write_text(
        "# Notices\n\nSee [the text](licenses/companion/demo-1.0.txt) and\n"
        "[a stray](../spikes/notes.txt).\n", encoding="utf-8")
    (root / "legal" / "licenses" / "companion" / "demo-1.0.txt").write_text(
        "# Copyright <demo> & *authors*\n\n    indented_line_kept\n",
        encoding="utf-8")
    (root / "legal" / "stray.txt").write_text("not a licence\n", encoding="utf-8")
    (root / "spikes" / "notes.txt").write_text("private\n", encoding="utf-8")
    monkeypatch.setattr(help_page, "_root_candidates", lambda: [root])
    monkeypatch.setattr(help_page, "_candidates", lambda: [root / "HOW_IT_WORKS.md"])
    help_page.invalidate_index()
    yield root
    help_page.invalidate_index()


def test_the_resolver_serves_the_licence_text_to_an_editor(docs):
    path = help_page.resolve_document("legal/licenses/companion/demo-1.0.txt")
    assert path is not None and path.name == "demo-1.0.txt"


@pytest.mark.parametrize("is_admin", [False, True])
def test_a_text_outside_the_licences_is_refused_even_for_an_admin(docs, is_admin):
    assert help_page.resolve_document("legal/stray.txt", is_admin) is None
    assert help_page.resolve_document("spikes/notes.txt", is_admin) is None


def test_the_index_lists_the_licence_text_and_nothing_else_new(docs):
    rels = {e["rel"] for g in help_page.document_groups(False) for e in g["entries"]}
    assert "legal/licenses/companion/demo-1.0.txt" in rels
    assert "legal/stray.txt" not in rels
    assert "spikes/notes.txt" not in rels
    entry = next(e for g in help_page.document_groups(False) for e in g["entries"]
                 if e["rel"].endswith("demo-1.0.txt"))
    # A `# ...` line inside a licence is prose, not a title.
    assert entry["title"] == "demo-1.0.txt"


def test_a_licence_text_renders_verbatim_and_escaped(docs):
    ctx = help_page.page_context("legal/licenses/companion/demo-1.0.txt")
    assert not ctx["help_not_found"]
    body = ctx["help_html"]
    assert body.startswith('<pre class="licence-text">')
    assert "&lt;demo&gt; &amp; *authors*" in body       # no markdown, no raw html
    assert "    indented_line_kept" in body
    assert "<h1" not in body and "<em>" not in body
    assert ctx["help_doc_title"] == "demo-1.0.txt"


def test_a_link_to_a_licence_text_becomes_a_help_link_and_a_stray_does_not(docs):
    ctx = help_page.page_context("legal/THIRD_PARTY_NOTICES.md")
    assert 'href="/help/legal/licenses/companion/demo-1.0.txt"' in ctx["help_html"]
    assert "/help/spikes/notes.txt" not in ctx["help_html"]


def test_the_route_serves_it_behind_the_login(docs, tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                              admin_users=frozenset({"owen"})))
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
        ok = client.get("/help/legal/licenses/companion/demo-1.0.txt")
        assert ok.status_code == 200
        assert "indented_line_kept" in ok.text
        assert client.get("/help/legal/stray.txt").status_code == 404
