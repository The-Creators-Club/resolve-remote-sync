"""The pages say what happened, not what the enum is called.

MUSIC-12 and MUSIC-16 (usability + resilience sweep, 2026-09-03), pinned
against the source for the reason `test_ingest_ui.py` gives: the frontend is
vanilla JS with no build step and no test runner in this repo.

MUSIC-12: the ingest cards rendered the server's state machine straight, so a
batch header read `done_with_errors on DESKTOP-7K2` and a track read
`queued_for_base_rig`. That last one is the one an editor most needs a
sentence for - it means the audio never left their own computer and they must
drop it again (`musicweb/ingest_batches.py:86-100`, KNOWN_BUGS MUSIC-ING-2) -
and it was shown as a bare identifier. The words now come from two lookup
tables, which this file holds to the Python enums so a new state cannot ship
with no sentence, and the raw value stays in `title=` for support.

MUSIC-16: the header stats line ended with the raw Hugging Face checkpoint id,
the only place a third party's model name was shown to a customer; and one
empty-state sentence served all five callers, so a `similar` lookup with no
neighbours advised rewording a description that was never typed.

Each retired phrase is named by its exact words rather than matched by a
pattern, so a failure here tells whoever hits it which sentence came back.
"""
from __future__ import annotations

import re
from pathlib import Path

from musicweb.ingest_batches import BATCH_STATES, ITEM_STATES

STATIC = Path(__file__).resolve().parent.parent / 'static'
INGEST_JS = (STATIC / 'ingest.js').read_text(encoding='utf-8')
APP_JS = (STATIC / 'app.js').read_text(encoding='utf-8')
INDEX_HTML = (STATIC / 'index.html').read_text(encoding='utf-8')
STYLE_CSS = (STATIC / 'style.css').read_text(encoding='utf-8')


def _js_object(text: str, name: str) -> dict[str, str]:
    """The keys and string values of a top-level `const NAME = { ... };`."""
    start = text.index(f'const {name} = {{')
    end = text.index('};', start)
    body = text[start:end]
    out = {}
    for m in re.finditer(r"""(\w+):\s*(?:'([^']*)'|"([^"]*)")""", body):
        out[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
    return out


# --- MUSIC-12: the state machine speaks English -------------------------------

def test_every_batch_state_has_a_sentence() -> None:
    words = _js_object(INGEST_JS, 'MI_BATCH_WORDS')
    missing = [s for s in BATCH_STATES if s not in words]
    assert not missing, (
        'MUSIC-12: a batch state with no words renders as the raw enum on the '
        f'card: {missing}. Add it to MI_BATCH_WORDS in static/ingest.js.')


def test_every_item_state_has_a_sentence() -> None:
    words = _js_object(INGEST_JS, 'MI_ITEM_WORDS')
    missing = [s for s in ITEM_STATES if s not in words]
    assert not missing, (
        'MUSIC-12: a track state with no words renders as the raw enum in the '
        f'track list: {missing}. Add it to MI_ITEM_WORDS in static/ingest.js.')


def test_no_identifier_reaches_the_card() -> None:
    """A sentence that is just the identifier is the bug wearing a lookup.
    Only the multi-word states are checked: `cancelled` and `failed` ARE the
    English for themselves, and rewording them would be worse."""
    for name in ('MI_BATCH_WORDS', 'MI_ITEM_WORDS'):
        bad = [k for k, v in _js_object(INGEST_JS, name).items()
               if '_' in k and '_' in v]
        assert not bad, f'MUSIC-12: {name} still shows an identifier for {bad}'


def test_the_queued_for_base_rig_sentence_says_what_to_do() -> None:
    """The one state whose NAME is actively misleading: nothing is queued,
    the audio is still on the editor's own computer, and dropping it again is
    the only thing that moves it (MUSIC-ING-2)."""
    words = _js_object(INGEST_JS, 'MI_ITEM_WORDS')
    assert 'drop it again' in words['queued_for_base_rig']


def test_the_retired_ingest_copy_is_gone() -> None:
    retired = (
        # the live panel head and the two track lists, rendering the enum
        '${batch.state}${batch.machine',
        '${item.state} · ${item.orig_name}',
        # the batch card's state chip
        "'mi-batch-state', batch.state",
        # `live` is the item enum, not a word for a number of tracks
        '${batch.n_live} live',
    )
    for phrase in retired:
        assert phrase not in INGEST_JS, (
            f'MUSIC-12: static/ingest.js still renders the raw state - {phrase!r}')


def test_the_raw_state_is_still_available_to_support() -> None:
    """The words replace the enum on screen; they do not hide it."""
    assert '.title = batch.state' in INGEST_JS
    assert 'node.title = item.state' in INGEST_JS


def test_a_batch_card_carries_a_time() -> None:
    """Without one, yesterday's batch and this morning's look identical."""
    assert 'function miAgo(' in INGEST_JS
    assert 'miAgo(batch.updated_at || batch.created_at)' in INGEST_JS


# --- MUSIC-16: the search page ------------------------------------------------

def test_the_model_id_is_not_in_the_stats_line() -> None:
    """`laion/larger_clap_music_and_speech` means nothing to an editor and is
    the only place a third party's model name reached a customer."""
    assert '${s.gb} GB · ${s.model' not in APP_JS, (
        'MUSIC-16: the checkpoint id is back in the visible stats line')
    assert 'node.title = s && s.model' in APP_JS or 'search model:' in APP_JS, (
        'MUSIC-16: the model id belongs in the tooltip, not nowhere')


def test_the_empty_state_is_per_caller() -> None:
    """One sentence for five callers is a sentence that is wrong for four."""
    assert re.search(r'function render\(tracks, headline, showMatch,\s*\n\s*empty =',
                     APP_JS), 'MUSIC-16: render() takes no empty-state copy'
    assert APP_JS.count('Try a looser description') == 1, (
        'MUSIC-16: the search wording is the DEFAULT; a filter or a similar '
        'lookup must not advise rewording a description nobody typed')
    for copy in ('No tracks match these filters',
                 'Nothing in the library sounds like this one yet'):
        assert copy in APP_JS


def test_the_feel_sliders_say_they_are_exclusive() -> None:
    """The API takes ONE axis, so moving a second slider zeroes the first.
    Nothing said so, and the surprise was silent."""
    assert 'One at a time' in INDEX_HTML
    assert 'axis-hint' in INDEX_HTML and '.axis-hint' in STYLE_CSS


# --- house style --------------------------------------------------------------

def test_none_of_the_new_copy_uses_an_em_dash() -> None:
    """Covered by test_no_em_dashes.py for the files as a whole; asserted here
    too because every string this file pins is new user-visible copy."""
    for name in ('MI_BATCH_WORDS', 'MI_ITEM_WORDS'):
        for value in _js_object(INGEST_JS, name).values():
            assert '—' not in value
