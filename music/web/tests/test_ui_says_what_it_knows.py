"""What the music page must tell an editor, pinned against its own source.

Same method and the same reason as `test_ingest_ui.py` and
`test_plain_words.py`: the frontend is vanilla JS with no build step and no
test runner in this repo, so the intent is pinned here rather than not at all.

Wave 3 of the usability + resilience sweep, 2026-09-04:

  * **MUSIC-2** - none of the three query functions had a catch, and all three
    render into a list that is already showing render's empty state, so "the
    search model did not load", "your session expired", "the database is
    locked" and "nothing matches" were ONE screen, under advice ("try a looser
    description") that was wrong in three of the four cases.
  * **MUSIC-3** - the whole ingest feature was reachable only by dragging a
    file onto the page. Nothing said music could be added, and a batch started
    yesterday could not be read, cancelled or explained without dropping
    another file first.
  * **MUSIC-7** - `GET api/ingest/queue` returns the counts, the pending rows
    and every parked failure's reason, and nothing in the browser read it. A
    failed queue row is never retried, so its reason existed only in the log of
    whichever indexer run happened to hit it.
  * **MUSIC-9** - a batch reaching a terminal state left the results, the
    facets and the header exactly as they were, and there was no sort control
    at all, so a cue added a minute ago sat somewhere alphabetical.
  * **MUSIC-13** - a track with no stored waveform drew an empty strip and said
    nothing, and click-to-seek kept working over it, so it read as broken.
  * **MUSIC-14** - the BPM and length filters hid every fleet-ingested track
    (`bpm IS NULL`), silently.
  * **CMEDIA-7** - "this machine is already downloading as much as it will at
    once" is a WAIT, and this page's poll loop is the retry the companion's cap
    relies on. Both companion shapes are accepted, because an editor's tray app
    is upgraded on its own schedule.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / 'static'
APP_JS = (STATIC / 'app.js').read_text(encoding='utf-8')
INGEST_JS = (STATIC / 'ingest.js').read_text(encoding='utf-8')
INDEX_HTML = (STATIC / 'index.html').read_text(encoding='utf-8')
STYLE_CSS = (STATIC / 'style.css').read_text(encoding='utf-8')


def body(text: str, name: str) -> str:
    """The source of one top-level function, up to the next one."""
    start = re.search(rf'^(?:async )?function {re.escape(name)}\(', text, re.M)
    assert start, f'{name} is gone'
    rest = text[start.end():]
    nxt = re.search(r'^(?:async )?function ', rest, re.M)
    return rest[:nxt.start()] if nxt else rest


# --- MUSIC-2: a failure never wears the empty state's words -------------------

@pytest.mark.parametrize('name', ['loadTracks', 'runSearch', 'showSimilar'])
def test_every_query_function_catches(name):
    src = body(APP_JS, name)
    assert 'catch' in src, f'{name} discards its rejected promise'
    assert 'failureText(' in src, f'{name} must say what failed, not "no results"'


def test_the_status_travels_with_the_error():
    """A 401 is an expired dashboard session and needs different words from a
    503; `message` alone cannot tell them apart at the catch site."""
    src = body(APP_JS, 'api')
    assert 'err.status = r.status' in src


def test_the_failure_sentence_names_the_status_and_says_try_again():
    src = body(APP_JS, 'failureText')
    assert 'the server answered ${e.status}' in src
    assert 'Try again' in src
    assert 'your session expired' in src


def test_the_empty_state_advice_is_not_shown_for_a_failure():
    assert 'Try a looser description' in APP_JS      # still there for a real miss
    for name in ('loadTracks', 'runSearch', 'showSimilar'):
        assert 'Try a looser description' not in body(APP_JS, name)


# --- MUSIC-3: a door that is not a drag ---------------------------------------

def test_the_header_has_an_add_music_button():
    assert 'id="addMusic"' in INDEX_HTML
    assert '[ ADD MUSIC ]' in INDEX_HTML


def test_the_button_opens_the_ingest_panel():
    src = body(APP_JS, 'init')
    assert "$('#addMusic')" in src
    assert 'miOpen()' in src
    # ingest.js is a separate classic script: a stale index.html can leave it
    # out entirely, and a TypeError there would take the search page with it.
    assert "typeof miOpen === 'function'" in src


def test_the_empty_drop_zone_explains_itself():
    assert 'id="mi-drop-empty"' in INDEX_HTML
    assert 'Nothing staged yet' in INDEX_HTML
    assert "$('#mi-drop-empty')" in body(INGEST_JS, 'miRenderPreview')


# --- MUSIC-7: the queue, and why a row is parked ------------------------------

def test_the_panel_reads_the_queue_route():
    assert "miApi('api/ingest/queue')" in INGEST_JS
    assert 'id="mi-queue"' in INDEX_HTML


def test_the_queue_is_refreshed_while_the_panel_is_open():
    src = body(INGEST_JS, 'miStartPolling')
    assert 'miLoadQueue' in src
    assert 'MI_QUEUE_POLL_MS' in src
    assert 'queue' in body(INGEST_JS, 'miStopPolling') or 'mi.timers' in INGEST_JS


def test_the_queue_shows_counts_pending_and_the_parked_reason():
    src = body(INGEST_JS, 'miRenderQueue')
    assert 'counts.pending' in src and 'counts.failed' in src
    assert 'row.error' in src, 'the parked reason is the whole point of the route'
    assert 'Nothing retries these on their' in src
    assert 'innerHTML =' not in src.replace("body.innerHTML = ''", ''), \
        'server text goes through el()/textContent, never innerHTML (MUSIC-15)'


# --- MUSIC-9: the library catches up, and newest is offered -------------------

def test_a_finished_batch_refreshes_the_library():
    src = body(INGEST_JS, 'miAfterBatch')
    assert 'refreshLibrary(true)' in src
    assert "typeof refreshLibrary === 'function'" in src


def test_the_refresh_fires_on_the_transition_only():
    """A page opened on last week's finished batches must not re-render the
    list under the editor."""
    src = body(INGEST_JS, 'miNoteBatchState')
    assert 'mi.seenStates[batch.uid]' in src
    assert 'if (!was' in src
    assert 'MI_TERMINAL_STATES.includes(was)' in src


def test_refresh_library_repaints_the_head_and_the_rail():
    src = body(APP_JS, 'refreshLibrary')
    for call in ('api/stats', 'api/facets', 'paintFacets()', 'loadTracks()'):
        assert call in src
    assert "state.sort = 'newest'" in src


def test_the_sort_control_offers_newest():
    assert 'id="sort"' in INDEX_HTML
    assert '<option value="newest">newest</option>' in INDEX_HTML
    assert "p.set('sort', state.sort)" in body(APP_JS, 'filterParams')


# --- MUSIC-13: an empty waveform says why ------------------------------------

def test_a_missing_waveform_is_captioned():
    assert 'No waveform yet' in APP_JS
    assert 'the base rig has not' in APP_JS
    src = body(APP_JS, 'loadPeaks')
    assert 'note:' in src, 'loadPeaks returns the reason, not just the bytes'
    assert 'detail' in src, "the route's own 404 wording is kept for support"
    assert 'wavenote' in body(APP_JS, 'openPane')
    assert '.wavenote' in STYLE_CSS


def test_a_real_answer_is_still_the_only_thing_cached():
    """MUSIC-4 (2026-08-11): a 404 body is JSON, and caching it drawn as a
    waveform left the track with permanent garbage peaks until a reload."""
    src = body(APP_JS, 'loadPeaks')
    setter = src.index('state.peaks.set(id, buf)')
    assert src.index('if (!r.ok)') < setter


# --- MUSIC-14: unknown is not "no" -------------------------------------------

def test_the_rail_offers_the_unknown_bucket():
    assert 'id="includeUnknown"' in INDEX_HTML
    assert 'id="unknownCount"' in INDEX_HTML
    assert 'Include tracks with no BPM or length' in INDEX_HTML
    assert 'FACETS._unknown' in body(APP_JS, 'syncUnknownToggle')


def test_the_result_head_says_what_a_tempo_filter_hid():
    src = body(APP_JS, 'noteUnknownHidden')
    assert 'unknown_hidden' in src
    assert 'not shown' in src
    assert '[ include them ]' in src


def test_both_query_paths_send_the_filters():
    """MUSIC-4: one filter object, two verbs."""
    assert 'filterFields()' in body(APP_JS, 'filterParams')
    assert 'filterFields()' in body(APP_JS, 'runSearch')
    assert 'include_unknown' in body(APP_JS, 'filterFields')


# --- CMEDIA-7: "already downloading" is a wait -------------------------------

def test_the_send_loop_keeps_polling_on_busy():
    src = body(APP_JS, 'sendToResolve')
    assert "r.state === 'busy'" in src and "r.state === 'queued'" in src
    assert 'already downloading' in src, 'the older companion shape is a wait too'
    assert 'retry_after' in src


def test_the_send_loop_still_ends_on_a_real_answer():
    src = body(APP_JS, 'sendToResolve')
    assert 'break;' in src
