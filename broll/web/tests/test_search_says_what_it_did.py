"""A search that finds nothing says so, and a mode that cannot answer says why.

BROLL-9 / BROLL-10 / BROLL-23 of the usability + resilience sweep (2026-09-03),
built 2026-09-04.

  * **an empty grid is the same picture as a page that failed to paint.**
    `search.py`'s docstring calls an empty result "the correct, honest answer
    to a query that matches nothing in the archive" - the whole keyword-first
    design exists to produce it, and the UI never said it. So the response
    carries the SIZE of what was searched and the page says the sentence.
  * **`mode=semantic` can return nothing for ever and say nothing.** fastembed
    is optional and the query model must match the stored vectors' model; a
    missing package or a mismatch makes every semantic query empty,
    permanently, with no signal to the editor or the admin.
  * **nothing said a search was in flight**, while a semantic query costs a
    model load plus a scan over Tailscale.

The JS half is pinned against the source text for the reason
`tests/test_filter_state.py` gives: vanilla JS, no build step, no test runner,
and pinning the intent beats not pinning it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import semantic
from tests.factories import insert_segment, insert_video

STATIC = Path(__file__).resolve().parents[1] / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
STYLE_CSS = (STATIC / "style.css").read_text(encoding="utf-8")


def _seed(conn, description: str = "a boat at sunset") -> int:
    vid = insert_video(conn, share="broll", rel_path="a.mov", status="indexed")
    insert_segment(conn, vid, description=description)
    return vid


# --- BROLL-9: the counts that were searched -----------------------------------

def test_a_query_that_matches_nothing_says_how_much_was_searched(client, conn):
    for i in range(3):
        vid = insert_video(conn, share="broll", rel_path=f"c{i}.mov", status="indexed")
        insert_segment(conn, vid, description="a boat at sunset")

    body = client.get("/api/search?q=helicopter").json()
    assert body["results"] == []
    assert body["scope_total"] == 3, "the size of what was searched, not of the hit list"


def test_the_scope_count_respects_the_filters_the_search_ran_under(client, conn):
    """A folder filter narrows what was searched, so it must narrow the number
    the page prints - otherwise "40,000 clips were searched" is a lie told
    inside a folder holding eleven."""
    a = insert_video(conn, share="broll", rel_path="a.mov", status="indexed",
                     category="aerial")
    insert_segment(conn, a, description="a boat")
    b = insert_video(conn, share="broll", rel_path="b.mov", status="indexed",
                     category="food")
    insert_segment(conn, b, description="a boat")

    body = client.get("/api/search?q=helicopter&category=aerial").json()
    assert body["scope_total"] == 1


def test_a_search_that_found_something_pays_for_no_count(client, conn):
    _seed(conn)
    body = client.get("/api/search?q=boat").json()
    assert body["results"], "the query matches"
    assert "scope_total" not in body


def test_browsing_with_no_query_asks_for_no_count(client, conn):
    body = client.get("/api/search").json()
    assert "scope_total" not in body


# --- BROLL-10: what each mode can do here -------------------------------------

def test_every_search_says_what_the_three_modes_can_do(client, conn):
    _seed(conn)
    modes = client.get("/api/search?q=boat").json()["mode_available"]
    assert set(modes) == {"keyword", "semantic", "hybrid"}
    assert modes["keyword"]["available"] is True
    assert modes["hybrid"]["available"] is True, (
        "hybrid is keyword plus a booster: disabling the page's default mode "
        "when the booster is off would leave an editor with no mode at all")


def test_an_archive_with_no_vectors_names_that_as_the_reason(client, conn,
                                                             monkeypatch):
    monkeypatch.setattr(semantic, "encoder_installed", lambda: True)
    _seed(conn)
    modes = client.get("/api/search?q=boat").json()["mode_available"]
    assert modes["semantic"] == {"available": False,
                                 "reason": semantic.REASON_NO_VECTORS}
    assert modes["hybrid"]["reason"] == semantic.NOTE_HYBRID_DEGRADED


def test_a_server_without_the_query_model_says_that_instead(client, conn,
                                                            monkeypatch):
    """Two different problems with two different owners: an archive nobody has
    embedded yet, and a deployment missing the package."""
    monkeypatch.setattr(semantic, "encoder_installed", lambda: False)
    semantic.get_semantic_search().reset()
    _seed(conn)
    modes = client.get("/api/search?q=boat").json()["mode_available"]
    assert modes["semantic"]["available"] is False
    assert modes["semantic"]["reason"] == semantic.REASON_NO_ENCODER


def test_the_availability_probe_never_imports_the_model(monkeypatch):
    """It is asked on every search response, and constructing the encoder is a
    ~10 s ONNX load. find_spec, never an import."""
    def boom(name):  # pragma: no cover -- the assertion is that it is not called
        raise AssertionError("the availability probe must not build an encoder")

    monkeypatch.setattr(semantic, "_load_fastembed_encoder", boom)
    semantic.get_semantic_search().reset()
    assert semantic.encoder_installed() in (True, False)


def test_a_probe_that_raises_does_not_take_the_search_route_with_it(conn,
                                                                    monkeypatch):
    def boom(self, conn_):
        raise RuntimeError("no")

    monkeypatch.setattr(semantic.SemanticSearch, "availability", boom)
    modes = semantic.mode_availability(conn)
    assert modes["semantic"]["available"] is False
    assert modes["keyword"]["available"] is True


def test_no_reason_is_an_em_dash_or_a_package_name_the_editor_cannot_act_on():
    for reason in (semantic.REASON_NO_NUMPY, semantic.REASON_NO_ENCODER,
                   semantic.REASON_NO_VECTORS, semantic.NOTE_HYBRID_DEGRADED):
        assert "—" not in reason
        assert reason.endswith(".")


# --- the page ------------------------------------------------------------------

def test_the_grid_renders_an_empty_state_instead_of_nothing():
    body = APP_JS[APP_JS.index("function renderGrid"):]
    body = body[:body.index("\n}\n")]
    assert "buildEmptyState()" in body
    empty = APP_JS[APP_JS.index("function buildEmptyState"):]
    empty = empty[:empty.index("\n}\n")]
    assert 'Nothing matched "${state.q}" in ${scopeLabel()}' in empty
    assert "clips were searched" in empty
    assert "switch to Semantic search" in empty


@pytest.mark.parametrize("lever, guard", [
    ("switch to Semantic search", 'state.mode !== "semantic"'),
    ("clear the folder filter", "state.collection || state.category || state.path"),
    ("stop hiding flagged clips", "state.hiddenFlags.size"),
    ("turn fuzzy matching back on", "!state.fuzzy"),
])
def test_each_lever_is_offered_only_when_that_filter_is_on(lever, guard):
    """A list that suggests turning off a filter that is already off reads as
    noise, and teaches an editor to stop reading it."""
    empty = APP_JS[APP_JS.index("function buildEmptyState"):]
    empty = empty[:empty.index("\n}\n")]
    assert lever in empty
    assert guard in empty


def test_the_mode_buttons_disable_with_the_servers_reason_as_their_title():
    body = APP_JS[APP_JS.index("function applyModeAvailability"):]
    body = body[:body.index("\n}\n")]
    assert "btn.disabled = info.available === false" in body
    assert "btn.title = info.reason" in body
    assert 'state.mode = "hybrid"' in body, "a mode that cannot answer falls back"


def test_a_search_in_flight_is_visible_and_cleared_by_the_winning_token():
    run = APP_JS[APP_JS.index("async function runSearch"):]
    run = run[:run.index("\n}\n")]
    assert run.count("setSearching(true)") == 1
    assert run.count("setSearching(false)") == 2, (
        "cleared on BOTH outcomes, and only after the token check, so a "
        "superseded response cannot switch the indicator off under a live search")
    assert run.index("if (token !== searchToken) return; //") < run.rindex("setSearching(false)")

    setter = APP_JS[APP_JS.index("function setSearching"):]
    setter = setter[:setter.index("\n}\n")]
    assert 'classList.toggle("searching"' in setter
    assert 'setAttribute("aria-busy"' in setter
    assert "Searching..." in setter


def test_the_searching_paint_exists_in_the_stylesheet():
    assert ".results-grid.searching" in STYLE_CSS
    assert ".results-empty" in STYLE_CSS
    assert ".mode-btn:disabled" in STYLE_CSS
