"""A folder's badge is a promise about what clicking it returns.

get_tree's own docstring makes that the rule ("a tree that promises 218 and
delivers 190 is worse than no count at all"), and two paths broke it:

  * the Downloads ROOT counted `status='indexed'` only, while clicking it goes
    through browse, which drops only skipped/excluded/duplicates -- so the root
    read N and returned N plus every discovered/probed/proxied/error row
    (BROLL-10);
  * the Creators_Club shoot nodes count by exact rel_path components while
    clicking sent a `LIKE 'A%B%C%'` contains-in-order match, which is a
    different set in both directions (BROLL-9).
"""
from __future__ import annotations

import pytest

from app import config
from app.search import build_shoot_clause
from tests.factories import insert_video


@pytest.fixture()
def creators(monkeypatch):
    monkeypatch.setenv("BROLL_CREATORS_SHARES", "ff4")


def _root(body, collection):
    return next(r for r in body if r["collection"] == collection)


# ---------------------------------------------------------------------------
# BROLL-10 — the Downloads root total
# ---------------------------------------------------------------------------

def test_the_downloads_root_counts_what_clicking_it_returns(client, conn, creators):
    insert_video(conn, share="dl", rel_path="a.mov", status="indexed", category="energy")
    insert_video(conn, share="dl", rel_path="b.mov", status="proxied")
    insert_video(conn, share="dl", rel_path="c.mov", status="discovered")
    insert_video(conn, share="dl", rel_path="d.mov", status="error")

    total = _root(client.get("/api/tree").json(), "downloads")["total"]
    clicked = client.get("/api/search", params={"collection": "downloads"}).json()

    assert total == clicked["total"] == 4


def test_the_downloads_root_still_excludes_what_browse_excludes(client, conn, creators):
    insert_video(conn, share="dl", rel_path="a.mov", status="indexed", category="energy")
    insert_video(conn, share="dl", rel_path="proxy/a.mov", status="skipped")
    insert_video(conn, share="dl", rel_path="cam/a.mov", status="excluded")
    canonical = insert_video(conn, share="dl", rel_path="orig.mov", status="indexed")
    insert_video(conn, share="dl", rel_path="dupe.mov", status="indexed",
                 duplicate_of=canonical)

    total = _root(client.get("/api/tree").json(), "downloads")["total"]
    clicked = client.get("/api/search", params={"collection": "downloads"}).json()

    assert total == clicked["total"] == 2


def test_own_footage_is_not_counted_under_downloads(client, conn, creators):
    insert_video(conn, share="dl", rel_path="a.mov", status="indexed", category="energy")
    insert_video(conn, share="ff4", rel_path="Day 1/own.mov", status="proxied")

    body = client.get("/api/tree").json()
    assert _root(body, "downloads")["total"] == 1
    assert _root(body, config.COLLECTION_CREATORS)["total"] == 1


# ---------------------------------------------------------------------------
# BROLL-9 — the shoot clause matches folders, not word sequences
# ---------------------------------------------------------------------------

def _shoot(client, slug):
    body = client.get("/api/search",
                      params={"collection": config.COLLECTION_CREATORS, "shoot": slug}).json()
    return {r["video"]["rel_path"] for r in body["results"]}


def test_a_shoot_node_returns_exactly_what_it_counted(client, conn, creators):
    insert_video(conn, share="ff4", rel_path="Whisky/Interviews/Proxy/a.mov")
    insert_video(conn, share="ff4", rel_path="Whisky/Interviews/Proxy/b.mov")
    insert_video(conn, share="ff4", rel_path="Whisky/B-roll/Proxy/c.mov")

    groups = _root(client.get("/api/tree").json(), config.COLLECTION_CREATORS)["groups"]
    share_node = next(n for n in groups if n["slug"] == "ff4")
    whisky = next(c for c in share_node["children"] if c["label"] == "Whisky")
    interviews = next(c for c in whisky["children"] if c["label"] == "Interviews")
    assert interviews["count"] == len(_shoot(client, interviews["slug"])) == 2


def test_a_sibling_with_a_longer_name_is_not_dragged_in(client, conn, creators):
    """`Day 1` must not mean `Day 10`, and `B-roll` must not mean
    `B-roll Archive` -- the boundary build_path_clause already enforced."""
    insert_video(conn, share="ff4", rel_path="Day 1/Proxy/a.mov")
    insert_video(conn, share="ff4", rel_path="Day 10/Proxy/b.mov")

    assert _shoot(client, "ff4::Day 1") == {"Day 1/Proxy/a.mov"}


def test_the_components_are_not_matched_as_a_loose_sequence(client, conn, creators):
    """The old `LIKE 'A%B%'` matched any path merely CONTAINING the parts in
    order, at any depth and mid-name -- which is not a folder."""
    insert_video(conn, share="ff4", rel_path="Whisky/Interviews/Proxy/a.mov")
    insert_video(conn, share="ff4", rel_path="Whisky Bar/Old Interviews/b.mov")

    assert _shoot(client, "ff4::Whisky / Interviews") == {"Whisky/Interviews/Proxy/a.mov"}


def test_the_folded_proxy_component_is_still_found_wherever_it_sat(client, conn, creators):
    """_shoot_tree drops a `Proxy` component from the label wherever it appears,
    so the clause has to allow it back at any position -- not just the usual
    trailing one."""
    insert_video(conn, share="ff4", rel_path="Whisky/Proxy/Interviews/a.mov")
    insert_video(conn, share="ff4", rel_path="Proxy/Whisky/Interviews/b.mov")
    insert_video(conn, share="ff4", rel_path="Whisky/Interviews/Proxy/c.mov")

    assert _shoot(client, "ff4::Whisky / Interviews") == {
        "Whisky/Proxy/Interviews/a.mov",
        "Proxy/Whisky/Interviews/b.mov",
        "Whisky/Interviews/Proxy/c.mov",
    }


def test_a_wildcard_in_a_folder_name_is_escaped(client, conn, creators):
    """`_` is a single-character LIKE wildcard and this archive's folders are
    full of them; only `%` was escaped before."""
    insert_video(conn, share="ff4", rel_path="Day_1/Proxy/a.mov")
    insert_video(conn, share="ff4", rel_path="DayX1/Proxy/b.mov")

    assert _shoot(client, "ff4::Day_1") == {"Day_1/Proxy/a.mov"}


def test_a_bare_share_still_selects_the_whole_share():
    clause, params = build_shoot_clause("ff4")
    assert clause == " AND v.share = ?"
    assert params == ["ff4"]
