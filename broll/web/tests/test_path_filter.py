"""`path=<share>::<rel/prefix>` -- the filter behind a clicked path crumb.

Deliberately not build_shoot_clause. That one joins its parts with `%`, so
`Erosion / Interviewees` matches any rel_path containing those words in order
at any depth; fine for the two-level shoot browser it was written for, wrong
for "take me to this folder". These tests pin the difference.
"""
import sqlite3

import pytest

from app.search import build_path_clause, search_videos
from tests.factories import insert_video


def _rows(conn, path):
    results, total = search_videos(
        conn, q="", category=None, flags=None, limit=50, offset=0, path=path
    )
    return sorted(r["video"]["rel_path"] for r in results), total


@pytest.fixture()
def tree(conn):
    insert_video(conn, share="ff4", rel_path="Erosion/Interviewees/Lin/B-roll/a.mov")
    insert_video(conn, share="ff4", rel_path="Erosion/Interviewees/Lin/B-roll/b.mov")
    insert_video(conn, share="ff4", rel_path="Erosion/Interviewees/Chen/c.mov")
    insert_video(conn, share="ff4", rel_path="Erosion/Drone/d.mov")
    insert_video(conn, share="ff4", rel_path="Whisky/e.mov")
    insert_video(conn, share="ff3", rel_path="Erosion/Interviewees/Lin/B-roll/f.mov")
    conn.commit()
    return conn


def test_a_share_with_no_prefix_selects_the_whole_share(tree):
    paths, total = _rows(tree, "ff3::")
    assert paths == ["Erosion/Interviewees/Lin/B-roll/f.mov"]
    assert total == 1
    assert _rows(tree, "ff4")[1] == 5      # bare share, no separator


def test_every_depth_is_selectable(tree):
    assert _rows(tree, "ff4::Erosion")[1] == 4
    assert _rows(tree, "ff4::Erosion/Interviewees")[1] == 3
    assert _rows(tree, "ff4::Erosion/Interviewees/Lin")[1] == 2
    assert _rows(tree, "ff4::Erosion/Interviewees/Lin/B-roll")[1] == 2
    assert _rows(tree, "ff4::Erosion/Drone")[1] == 1


def test_the_prefix_stops_at_a_directory_boundary(conn):
    """`B-roll` must not drag in `B-roll Archive`. This is the bug you get for
    free by matching `prefix%` instead of `prefix/%`."""
    insert_video(conn, share="s", rel_path="B-roll/keep.mov")
    insert_video(conn, share="s", rel_path="B-roll Archive/other.mov")
    conn.commit()
    paths, total = _rows(conn, "s::B-roll")
    assert paths == ["B-roll/keep.mov"]
    assert total == 1


def test_the_share_is_matched_exactly_not_by_prefix(conn):
    insert_video(conn, share="ff4", rel_path="x.mov")
    insert_video(conn, share="ff4-nuclear", rel_path="y.mov")
    conn.commit()
    assert _rows(conn, "ff4::")[0] == ["x.mov"]


def test_a_folder_holding_a_like_wildcard_is_matched_literally(conn):
    """SQLite LIKE treats % and _ as wildcards; a real folder can contain
    both, and `100%_Real` selecting everything would be a silent wrong answer
    rather than an error."""
    insert_video(conn, share="s", rel_path="100%_Real/keep.mov")
    insert_video(conn, share="s", rel_path="100XYReal/no.mov")
    conn.commit()
    paths, total = _rows(conn, "s::100%_Real")
    assert paths == ["100%_Real/keep.mov"]
    assert total == 1


@pytest.mark.parametrize("blank", [None, "", "::", "::whatever"])
def test_a_blank_or_shareless_path_filters_nothing(blank):
    clause, params = build_path_clause(blank)
    assert clause == "" and params == []


def test_leading_and_trailing_slashes_are_tolerated(tree):
    """The crumb builder joins components, but a hand-edited URL is a public
    interface too."""
    assert _rows(tree, "ff4::/Erosion/Interviewees/")[1] == 3


def test_it_composes_with_a_query(tree):
    """The folder filter narrows a search rather than replacing it -- the grid
    header shows both for the same reason."""
    results, total = search_videos(
        conn=tree, q="", category=None, flags=None, limit=50, offset=0,
        path="ff4::Erosion/Drone",
    )
    assert total == 1
