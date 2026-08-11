"""The SPA's four filter axes (`q`, `category`, `collection`, `path`) are ANDed
together in runSearch, and only some of the controls that set one reset the
others. That is how a user reaches a state the UI itself cannot describe or
escape:

  * clicking a tree folder left the detail panel's `path` crumb filter in place,
    so `collection=downloads AND path=ff4::Erosion` returned nothing and the
    tree's own "clear" button could not undo it (BROLL-3);
  * the line above the grid named `q` and `path` but never `category` or
    `collection`, so a category crumb filtered the grid while it read "browsing
    all videos" (BROLL-11);
  * that same category crumb kept the previous query, intersecting the two into
    a near-empty grid with no cue why (BROLL-12);
  * and a slow semantic response could overwrite a newer one, painting
    unfiltered results while the sidebar highlighted a folder (BROLL-8).

Asserted against the source text: the frontend is vanilla JS with no build step
and no test runner in this repo, and pinning the intent here beats not pinning
it at all -- the same posture as test_mounted_prefix.py and
test_sprite_geometry.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parent.parent / "static" / "app.js"


@pytest.fixture(scope="module")
def js() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _function(js: str, name: str) -> str:
    start = js.index(f"function {name}(")
    return js[start:js.index("\n}", start)]


def _arrow_handler(js: str, anchor: str) -> str:
    """The body of the inline handler introduced by `anchor`."""
    start = js.index(anchor)
    return js[start:js.index("\n  });", start)]


# ---------------------------------------------------------------------------
# BROLL-3
# ---------------------------------------------------------------------------

def test_picking_a_tree_folder_clears_the_crumb_path(js):
    body = _function(js, "selectFolder")
    assert 'state.path = ""' in body, (
        "selectFolder must drop the detail-panel crumb filter; leaving it ANDed "
        "under the tree's own selection is a zero-result dead end with no way out"
    )


def test_the_category_dropdown_clears_it_too(js):
    body = _arrow_handler(js, '$("#category-select").addEventListener("change"')
    assert 'state.path = ""' in body


def test_the_tree_clear_button_goes_through_selectfolder(js):
    """So it inherits the reset above rather than needing its own copy."""
    assert 'selectFolder("", "")' in _function(js, "wireFolderClear")


# ---------------------------------------------------------------------------
# BROLL-8
# ---------------------------------------------------------------------------

def test_runsearch_drops_a_superseded_response(js):
    body = _function(js, "runSearch")
    assert "++searchToken" in body, "runSearch must claim a request token"
    assert body.count("token !== searchToken") >= 2, (
        "both the success and the failure path have to check it -- a stale error "
        "toast is as wrong as a stale grid"
    )
    # The guard has to sit between the await and the paint.
    assert body.index("await fetchJson") < body.index("token !== searchToken")
    assert body.index("token !== searchToken") < body.index("renderGrid")


# ---------------------------------------------------------------------------
# BROLL-11
# ---------------------------------------------------------------------------

def test_the_results_line_names_the_category_and_collection(js):
    body = _function(js, "renderResultsMeta")
    assert "state.collection" in body and "state.category" in body
    # Still names the two it always did.
    assert "state.q" in body and "state.path" in body


# ---------------------------------------------------------------------------
# BROLL-12
# ---------------------------------------------------------------------------

def test_the_category_crumb_clears_the_query_like_its_siblings(js):
    """The path and theme crumbs in the same function both reset state.q; the
    category one did not, so "show me this category" silently meant "this
    category, still filtered by whatever I last searched"."""
    body = _function(js, "renderVideoMeta")
    category_closure = body[body.index("state.category = category;"):]
    assert 'state.q = ""' in category_closure
    assert '$("#q-input").value = "";' in category_closure
