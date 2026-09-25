"""The terminal /cards landing (UI redesign port, phase 6, group `apps`).

Terminal twins of test_cards_picker.py's page tests. Since 2026-09-25 the
terminal look is the only look (the switch and the classic landing are gone):
the page keeps every hook static/cards_landing.js reads, draws no
[ bracket ] label, folds every window and loads its own sheet on the cc
tokens.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, cards_pool
from ccsync_dashboard.app import create_app

from test_cards_mount import (SECRET, fake_src, make_settings,  # noqa: F401
                              open_episode)

ROOT = Path(__file__).resolve().parents[1]

# Every hook the shared script finds by selector (cards_landing.js).
SCRIPT_HOOKS = ('class="cl-tree', 'id="cl-tree"', 'id="cl-list"', 'id="cl-q"',
                'cl-clear', 'cl-search', 'cl-none', 'cl-count', 'cl-fold',
                'cl-chip', 'cl-ep', 'cl-folder', 'cl-fname',
                'cl-fcount', 'cl-fsize', 'cl-sum', 'cl-unfold', 'cl-refold',
                'cl-reset', 'cl-name-text', 'cl-kids', 'data-default-open=')


@pytest.fixture
def picker(tmp_path, fake_src, monkeypatch):
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault = tmp_path / "vault"
    roots = []
    for year, show, name in (("2026", "FF5", "Civil Defence"),
                             ("2026", "FF5", "Repro Rights"),
                             ("2025", "FF4", "Kinmen")):
        root = vault / "Vault" / year / show / name
        (root / "Interviewees").mkdir(parents=True)
        roots.append(root)
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault), cards_engines=2))
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME,
                           auth.make_session_cookie(SECRET, "owen"))
        yield client, app, roots


def test_the_landing_draws_the_terminal_page(picker):
    client, _, _ = picker
    page = client.get("/cards/").text
    # The same finder, folders, years and facts the classic page had.
    assert 'id="cl-q"' in page and "/static/cards_landing.js" in page
    assert 'data-key="2026/FF5"' in page and 'data-key="2025/FF4"' in page
    assert 'data-key="Vault"' not in page
    assert 'data-year="2026"' in page and 'data-year="2025"' in page
    assert "never opened" in page and "sizing" in page
    # cards_landing.js picks its "nothing shifts" branch on this attribute.
    assert 'data-ui="cc"' in page
    assert "[ TIMELINE CARDS ]" not in page
    assert "cc/cards_landing.css" in page
    assert "/static/cards_landing.css" not in page
    for hook in SCRIPT_HOOKS:
        assert hook in page, hook


def test_the_terminal_landing_has_no_bracket_labels_and_every_window_folds(
        picker):
    client, app, roots = picker
    entry = open_episode(app, roots[1])
    client.get(f"/cards/p/{entry.slug}/", headers={"Accept": "text/html"})
    page = client.get("/cards/").text
    main = page[page.index('<main'):page.index('</main>')]
    assert not re.search(r"\[ [A-Za-z]", main), "a [ bracket ] label"
    # The recent window is drawn, and every window has a fold button.
    assert 'data-win="recent"' in main
    wins = re.findall(r'<section class="win[^"]*" data-win="([^"]+)"', main)
    assert set(wins) == {"find", "recent", "episodes"}
    assert main.count('<button class="fold"') == len(wins)
    assert "you opened it just now" in main
    # A ready episode's key is still the one Enter presses.
    assert 'cl-btn-go' in main


def test_the_terminal_refusal_and_want_banner(picker):
    client, _, roots = picker
    slug = cards_pool.slug_for(str(roots[2]))
    page = client.get(f"/cards/?refused=two+are+open&want={slug}").text
    main = page[page.index('<main'):page.index('</main>')]
    assert "not opened" in main and "two are open" in main
    assert "Kinmen is not open." in main
    assert f'data-want="{slug}"' in main
    assert not re.search(r"\[ [A-Za-z]", main)


def test_the_close_confirm_stays_the_native_one():
    """Plan 1.4, wave 5: the landing is plain forms, so close keeps its
    onsubmit confirm in the terminal look too."""
    text = (ROOT / "templates/cards_landing.html").read_text(encoding="utf-8")
    assert "onsubmit='return confirm({{ ep.close_prompt | tojson }});'" in text


def test_the_terminal_sheet_reads_only_cc_tokens_and_says_no_long_dash():
    css = (ROOT / "static/cc/cards_landing.css").read_text(encoding="utf-8")
    tokens = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    root = (ROOT / "static/cc/terminal.css").read_text(encoding="utf-8")
    for token in tokens:
        assert re.search(re.escape(token) + r"\s*:", root), token
    for rel in ("templates/cards_landing.html", "static/cc/cards_landing.css",
                "static/cards_landing.js"):
        assert "—" not in (ROOT / rel).read_text(encoding="utf-8"), rel
    assert "infinite" not in css


def test_the_shared_script_dims_recent_while_searching():
    """Nothing shifts: the recent window stays while a search runs and only
    dims (the classic hide-on-search branch is dead with the classic page)."""
    js = (ROOT / "static/cards_landing.js").read_text(encoding="utf-8")
    assert "recent.hidden = any === 0;" in js
    assert "recent.classList.toggle('cl-dim', searching);" in js
