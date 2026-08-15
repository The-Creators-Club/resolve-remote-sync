"""Two ways the detail view and the folder rail told the editor something the
state did not say:

  * openDetail armed a one-shot `loadedmetadata` seek on the single, persistent
    #player. `{once:true}` only detaches a listener once it has FIRED, so a clip
    whose proxy 404s -- or that the editor left before metadata arrived -- kept
    it, and closeDetail's removeAttribute("src") + load() fires `emptied`, not
    `loadedmetadata`. It then fired against the NEXT clip and opened it at the
    previous clip's timecode, silently, with the seekbar showing no bands to
    explain why (BROLL-WEB-4);
  * selectFolder assigned the category <select> a Creators_Club shoot slug
    (`ff4::Whisky / Interviews`), which is never one of its options -- a <select>
    given a value no option carries goes to selectedIndex -1 and renders blank.
    Its two sibling writers guarded against exactly that, so the same folder
    rendered differently depending on whether it was reached by click or by
    Back (BROLL-WEB-8).

Asserted against the source text for the same reason test_filter_state.py is:
the frontend is vanilla JS with no build step and no test runner in this repo,
and pinning the intent here beats not pinning it at all.
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


# ---------------------------------------------------------------------------
# BROLL-WEB-4
# ---------------------------------------------------------------------------

def test_opendetail_arms_no_per_clip_seek_listener(js):
    body = _function(js, "openDetail")
    assert "addEventListener" not in body, (
        "a listener added here outlives the clip whenever it does not fire -- "
        "the seek belongs to state.detailSeekTo and the permanent handler"
    )
    assert "state.detailSeekTo = seekToSeconds" in body


def test_the_seek_runs_off_the_permanent_loadedmetadata_handler(js):
    assert 'player.addEventListener("loadedmetadata", applyPendingSeek)' in js, (
        "applyPendingSeek has to be wired once, alongside updatePlayhead and "
        "renderSeekMarkers, not armed per openDetail"
    )
    body = _function(js, "applyPendingSeek")
    assert "state.detailSeekTo == null" in body, "no pending seek -> do nothing"
    assert "state.detailSeekTo = null" in body, (
        "it must consume the pending seek, so a later metadata event for the "
        "same clip (a re-load, a source swap) cannot yank the playhead back"
    )


def test_closedetail_clears_the_pending_seek(js):
    """Leaving a clip before its metadata arrived must not leave the seek armed
    for whatever is opened next -- the BROLL-WEB-4 scenario exactly."""
    assert "state.detailSeekTo = null" in _function(js, "closeDetail")


# ---------------------------------------------------------------------------
# BROLL-WEB-8
# ---------------------------------------------------------------------------

def test_every_writer_of_the_category_select_goes_through_one_helper(js):
    """Three call sites wrote this control and only two guarded it. One helper
    means the next one cannot diverge again."""
    assert js.count("function syncCategorySelect(") == 1
    for name in ("selectFolder", "applyHistoryState", "jumpToSearch"):
        assert "syncCategorySelect()" in _function(js, name), (
            f"{name} must sync the category <select> through the helper"
        )


def test_the_helper_never_assigns_a_shoot_slug_to_the_select(js):
    body = _function(js, "syncCategorySelect")
    assert 'state.collection === "creators_club" ? "" : state.category' in body, (
        "a Creators_Club slug is a shoot path, never an <option> value -- "
        "assigning it blanks the control instead of reading 'All categories'"
    )


def test_no_call_site_still_assigns_the_select_directly(js):
    """The whole point of the helper is that it is the only writer."""
    assert js.count("select.value =") == 1, (
        "exactly one assignment, the one inside syncCategorySelect"
    )
