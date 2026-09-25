"""The /cards picker: last opened, size, date, year, folders (2026-09-24).

Alex: "ordered by most recently opened instead of date, and the projects
should be filterable, by year, by last opened, by largest, by date,
alphabetically, and also searchable", laid out "like a folder structure
concertina". The ordering and filtering happen in `static/cards_landing.js`;
what is defended here is what the page is GIVEN to order by, and that the
page still draws when every one of those facts is missing:

  * LAST OPENED survives the engine and the container: it is a file, written
    when a person ENTERS an episode page (a navigation, not a media request)
    or presses [ OPEN ], and throttled so a reload loop is not a write loop.
  * SIZE is never measured in a request. The walker runs in a thread; the
    page says "sizing" until it has a number.
  * THE FOLDERS are the vault's own, less the levels every episode shares.
"""
from __future__ import annotations

import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, cards_catalog, cards_pool
from ccsync_dashboard.app import create_app

from test_cards_mount import (SECRET, fake_src, make_settings,  # noqa: F401
                              open_episode)


class _S:
    def __init__(self, tmp_path):
        self.db_path = str(tmp_path / "dash.db")


# ------------------------------------------------------------ last opened

def test_opening_is_remembered_per_person_and_for_anybody(tmp_path):
    s = _S(tmp_path)
    cards_catalog.note_opened(s, "ep-1", "Owen")
    cards_catalog.note_opened(s, "ep-2", "ruskin")
    anyone, mine = cards_catalog.opened(s, "owen")
    assert set(anyone) == {"ep-1", "ep-2"}
    assert anyone["ep-2"]["by"] == "ruskin"
    assert set(mine) == {"ep-1"}                       # case-folded identity


def test_a_reload_loop_is_not_a_write_loop(tmp_path, monkeypatch):
    """The clock is moved on between the two calls: on Windows two calls in
    a row share one `time.time()` tick, so a test that did not move it
    passed with the throttle switched off (Fable review, 2026-09-25)."""
    s = _S(tmp_path)
    clock = [1_000_000.0]
    monkeypatch.setattr(cards_catalog.time, "time", lambda: clock[0])
    cards_catalog.note_opened(s, "ep-throttle", "owen")
    clock[0] += 5
    cards_catalog.note_opened(s, "ep-throttle", "owen")
    assert cards_catalog.opened(s, "owen")[1]["ep-throttle"] == 1_000_000.0
    clock[0] += cards_catalog.OPENED_THROTTLE_SECONDS
    cards_catalog.note_opened(s, "ep-throttle", "owen")
    assert cards_catalog.opened(s, "owen")[1]["ep-throttle"] == clock[0]


def test_a_corrupt_file_is_an_empty_answer_and_is_rewritten(tmp_path):
    s = _S(tmp_path)
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / cards_catalog.OPENED_FILE).write_text("{not json",
                                                                encoding="utf-8")
    assert cards_catalog.opened(s, "owen") == ({}, {})
    cards_catalog.note_opened(s, "ep-corrupt", "owen")
    assert "ep-corrupt" in cards_catalog.opened(s, "owen")[1]


# ------------------------------------------------------------------- size

def test_the_walk_counts_every_file_and_the_newest_change(tmp_path):
    root = tmp_path / "ep"
    (root / "Interviewees" / "deep").mkdir(parents=True)
    (root / "Interviewees" / "a.bin").write_bytes(b"x" * 1000)
    (root / "Interviewees" / "deep" / "b.bin").write_bytes(b"x" * 24)
    got = cards_catalog.walk_size(str(root))
    assert got["bytes"] == 1024 and got["files"] == 2
    assert got["newest"] > 0 and got["partial"] is False


def test_a_root_that_is_gone_is_no_answer_not_zero(tmp_path):
    assert cards_catalog.walk_size(str(tmp_path / "nope")) is None


def test_sizes_arrive_from_the_walker_not_from_the_request(tmp_path):
    s = _S(tmp_path)
    root = tmp_path / "ep"
    (root / "Clips").mkdir(parents=True)
    (root / "Clips" / "c.bin").write_bytes(b"x" * 500)
    rows = [{"slug": "ep-size", "root": str(root)}]
    cards_catalog.sizes(s, rows)
    end = time.monotonic() + 5
    got = {}
    while time.monotonic() < end:
        got = cards_catalog.sizes(s, rows)
        if "bytes" in got.get("ep-size", {}):
            break
        time.sleep(0.02)
    assert got["ep-size"]["bytes"] == 500
    on_disk = json.loads((tmp_path / "cards" / cards_catalog.SIZES_FILE)
                         .read_text(encoding="utf-8"))
    assert on_disk["ep-size"]["bytes"] == 500


# ------------------------------------------------------------------ tree

def test_the_folders_every_episode_shares_are_not_drawn(tmp_path):
    vault = str(tmp_path)
    paths = [cards_catalog.folder_parts(vault, str(tmp_path / "Vault" / y / s / "ep"))
             for y, s in (("2026", "FF5"), ("2025", "FF4"))]
    assert paths[0] == ["Vault", "2026", "FF5"]
    assert cards_catalog.strip_common(paths) == 1     # `Vault` carries no choice


def test_a_single_year_still_folds(tmp_path):
    paths = [["Vault", "2026", "FF5"], ["Vault", "2026", "FF5"]]
    # Everything shared, but the last level is kept so there is a folder.
    assert cards_catalog.strip_common(paths) == 2


def test_the_year_comes_from_the_folder_before_the_clock():
    assert cards_catalog.year_of(["2025", "FF4"], time.time()) == "2025"
    assert cards_catalog.year_of(["Shorts"], 0) == ""


def test_the_tree_nests_and_counts():
    rows = [{"name": "B", "parts": ["2026", "FF5"], "slug": "b"},
            {"name": "A", "parts": ["2026", "FF5"], "slug": "a", "state": "ready"},
            {"name": "C", "parts": ["2025"], "slug": "c"}]
    tree = cards_catalog.build_tree(rows)
    assert [n["name"] for n in tree] == ["2025", "2026"]
    ff5 = tree[1]["children"][0]
    assert ff5["name"] == "FF5" and ff5["count"] == 2 and ff5["key"] == "2026/FF5"
    assert [r["name"] for r in ff5["children"]] == ["A", "B"]
    assert tree[1]["hot"] is True and tree[0]["hot"] is False


# ----------------------------------------------------------- the page

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


def test_the_page_draws_the_folders_the_finder_and_the_years(picker):
    client, _, _ = picker
    page = client.get("/cards/").text
    assert 'id="cl-q"' in page and "/static/cards_landing.js" in page
    assert 'data-key="2026/FF5"' in page and 'data-key="2025/FF4"' in page
    assert 'data-key="Vault"' not in page
    assert 'data-year="2026"' in page and 'data-year="2025"' in page
    assert "never opened" in page and "sizing" in page


def test_entering_an_episode_page_makes_it_recent(picker):
    client, app, roots = picker
    entry = open_episode(app, roots[1])
    # A fetch inside the page is "still here", not "opened".
    client.get(f"/cards/p/{entry.slug}/api/state",
               headers={"Accept": "application/json"})
    settings = app.state.settings
    assert cards_catalog.opened(settings, "owen")[1] == {}
    client.get(f"/cards/p/{entry.slug}/", headers={"Accept": "text/html"})
    assert entry.slug in cards_catalog.opened(settings, "owen")[1]
    page = client.get("/cards/").text
    assert "[ YOUR RECENT ]" in page
    assert "you opened it just now" in page


def test_pressing_open_counts_as_opening(picker):
    client, app, roots = picker
    slug = cards_pool.slug_for(str(roots[2]))
    client.post("/cards/open", data={"slug": slug}, follow_redirects=False)
    assert slug in cards_catalog.opened(app.state.settings, "owen")[1]


def test_a_broken_catalogue_still_draws_the_page(picker, monkeypatch):
    client, _, _ = picker

    def boom(*a, **kw):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(cards_catalog, "opened", boom)
    page = client.get("/cards/")
    assert page.status_code == 200
    assert "Civil Defence" in page.text


def test_no_em_dash_in_what_the_picker_says():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for rel in ("templates/cards_landing.html", "static/cards_landing.js",
                "static/cards_landing.css"):
        assert "—" not in (root / rel).read_text(encoding="utf-8"), rel


def test_one_year_folder_still_gives_the_year(tmp_path, fake_src, monkeypatch):
    """The live shape is /vault/Vault/2026/FF5/<episode>: every episode shares
    the year folder, strip_common removes it from the DRAWN path, and the
    year must still come from it, not from the folder's mtime (Fable review,
    2026-09-25)."""
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault = tmp_path / "vault"
    old = 1_718_000_000                          # June 2024: not the folder's year
    for show, name in (("FF5", "Civil Defence"), ("FF6", "Repro Rights")):
        ep = vault / "Vault" / "2026" / show / name
        (ep / "Interviewees").mkdir(parents=True)
        os.utime(ep / "Interviewees", (old, old))
        os.utime(ep, (old, old))
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault), cards_engines=2))
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME,
                           auth.make_session_cookie(SECRET, "owen"))
        page = client.get("/cards/").text
    assert 'data-year="2026"' in page and 'data-year="2024"' not in page
    assert 'data-key="FF5"' in page            # the shared levels are not drawn


def test_one_bad_mtime_does_not_strip_the_rows_after_it(picker, monkeypatch):
    client, app, roots = picker
    real = cards_catalog.sizes

    def bad(settings, rows):
        got = dict(real(settings, rows))
        first = sorted(r["slug"] for r in rows)[0]
        got[first] = {"bytes": 1, "newest": 1e18, "at": time.time()}
        return got

    monkeypatch.setattr(cards_catalog, "sizes", bad)
    page = client.get("/cards/")
    assert page.status_code == 200
    # Every row still carries its year, so none fell out of the tree.
    assert page.text.count('class="cl-ep"') == 3
    import re
    years = re.findall(r'data-year="(\d*)"\s+data-opened=', page.text)
    assert sorted(years) == ["2025", "2026", "2026"]
