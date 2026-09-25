"""The 2026-09-24 hunt, wave 2 (mediums and lows), music's backend and page.

Every test here fails on HEAD 4462a2a and passes after the fix beside it. The
ids are the hunt's (`docs/bug-hunt-2026-09-24/hunters/*.md`) and each is cited
at its code site, so `grep -rn bug-music-ytdl-2` finds both halves.
"""
import io
import json
import re
import shutil
import sqlite3
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from musicweb import config, db, ingest_batches, routes_ingest
from tests.test_fleet_ingest import (fake_encoder, fleet,  # noqa: F401
                                     claim, headers, make_batch, result_body)

EDITOR = {'X-CCSync-User': 'jsmith'}
STATIC = Path(config.STATIC_DIR)


@pytest.fixture(autouse=True)
def _library_scores_restored(seeded_db):
    """A fleet `result` or a cancelled release re-scores the whole shared
    session library, and test_db pins the seeded `debias`/`tags`/`axes`. This
    file sorts before it, so it puts back what it found."""
    conn = db.con()
    saved = {t: [tuple(r) for r in conn.execute(f'SELECT * FROM {t}')]
             for t in ('debias', 'tags', 'axes', 'meta')}
    yield
    conn = db.con()
    with conn:
        for t, rows in saved.items():
            conn.execute(f'DELETE FROM {t}')
            if rows:
                marks = ','.join('?' for _ in rows[0])
                conn.executemany(f'INSERT OR REPLACE INTO {t} VALUES({marks})',
                                 rows)


# --------------------------------------------------------------------------
# bug-music-ytdl-2: a browser drop must not take a name a fleet item promised
# --------------------------------------------------------------------------

@pytest.fixture()
def queued_host(monkeypatch, seeded_db):
    """The NAS container: no indexer, ffprobe stubbed, and the library and
    ledger left exactly as they were found."""
    monkeypatch.setattr(routes_ingest, '_load_indexer', lambda: None)
    monkeypatch.setattr(routes_ingest, '_probe', lambda p: {
        'duration': 77.0, 'samplerate': 48000, 'channels': 2,
        'codec': 'pcm_s16le'})
    root = config.share_root()
    before = set(root.iterdir())
    conn = db.con()
    yield conn
    for p in root.iterdir():
        if p not in before:
            p.unlink()
    conn.execute('DELETE FROM ingest_queue')
    conn.execute('DELETE FROM ingest_items')
    conn.execute('DELETE FROM ingest_batches')
    conn.commit()


def _promise(conn, name, state='indexed'):
    """A fleet item that has been allocated `name` and not uploaded yet."""
    buid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO ingest_batches(uid, editor, settings_json, state, created_at) "
        "VALUES(?, 'rlee', '{}', 'running', '2026-09-25T00:00:00+00:00')", (buid,))
    conn.execute(
        'INSERT INTO ingest_items(uid, batch_uid, ord, orig_name, dest_name, state) '
        'VALUES(?, ?, 0, ?, ?, ?)', (uuid.uuid4().hex, buid, name, name, state))
    conn.commit()


def test_a_browser_drop_steps_around_a_name_a_fleet_item_holds(queued_host):
    """Editor A's companion was given `Promised Cue.wav` at `result` and its
    upload is still queued. Editor B drops a different recording of the same
    name in the browser. HEAD's unique_dest asked only the disk, so B's audio
    landed at A's name and A's rclone copyto then overwrote it."""
    _promise(queued_host, 'Promised Cue.wav')

    got = routes_ingest.queue_one('Promised Cue.wav',
                                  io.BytesIO(b'editor B audio' * 300), queued_host)

    assert got['status'] == 'queued', got
    assert got['rel_path'] == 'Promised Cue (2).wav', \
        'the browser drop took the name a fleet upload is about to write'
    assert not (config.share_root() / 'Promised Cue.wav').exists()


def test_a_released_promise_does_not_hold_the_name(queued_host):
    """The ledger rows that no longer promise anything (cancelled, failed,
    skipped, duplicate) are the ones reserved_names ignores too."""
    _promise(queued_host, 'Old Promise.wav', state='cancelled')

    got = routes_ingest.queue_one('Old Promise.wav',
                                  io.BytesIO(b'fresh' * 300), queued_host)

    assert got['rel_path'] == 'Old Promise.wav', got


def test_a_fleet_result_steps_around_a_browser_claim(queued_host):
    """The other direction: from the instant the browser path has chosen a
    name, the fleet's own disk check sees it as taken."""
    dest = db.claim_dest(queued_host, 'Race Cue.wav')
    try:
        assert dest.name == 'Race Cue.wav'
        assert ingest_batches.allocate_name(queued_host, 'Race Cue.wav') \
            == 'Race Cue (2).wav'
    finally:
        db.release_dest(dest)
    assert not dest.exists(), 'an unused claim left an empty file in the library'


def test_a_move_that_fails_leaves_no_empty_file_in_the_library(queued_host,
                                                              monkeypatch):
    def boom(src, dst):
        raise OSError('the share went away mid-copy')
    monkeypatch.setattr(routes_ingest.shutil, 'move', boom)

    got = routes_ingest.queue_one('Broken Move.wav',
                                  io.BytesIO(b'x' * 3000), queued_host)

    assert got['ok'] is False
    assert not (config.share_root() / 'Broken Move.wav').exists()


def test_a_fleet_result_takes_the_name_lock(fleet, fake_encoder, monkeypatch):
    """Between allocate_name and the commit the name is in neither `tracks`
    nor the ledger. The browser path checks under db.NAME_LOCK, so the fleet
    result has to hold the same lock across that gap."""
    entered = []

    class Recording:
        def __enter__(self):
            entered.append(True)

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(db, 'NAME_LOCK', Recording())
    uid = make_batch(fleet, names=('Locked Cue.wav',))
    item = claim(fleet, uid).json()['items'][0]['uid']
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/result',
                   json=result_body(), headers=headers())
    assert r.status_code == 200, r.text
    try:
        assert entered, 'write_item_result allocated a name outside NAME_LOCK'
    finally:
        conn = db.con()
        conn.execute('DELETE FROM tracks WHERE id = ?', (r.json()['track_id'],))
        conn.commit()


# --------------------------------------------------------------------------
# bug-music-ytdl-3: the first drop into an empty library refused itself
# --------------------------------------------------------------------------

@pytest.fixture()
def fresh_library(tmp_path, monkeypatch):
    root = tmp_path / 'music-share'
    root.mkdir()
    monkeypatch.setitem(config.SHARE_ROOTS, config.SHARE, root)
    config.forget_ready_cache()
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute('CREATE TABLE tracks (id INTEGER PRIMARY KEY, rel_path TEXT)')
    con.execute('CREATE TABLE ingest_items (uid TEXT, track_id INTEGER, '
                'state TEXT)')
    yield root, con
    config.forget_ready_cache()


def test_a_library_made_only_of_unlanded_rows_is_not_unmounted(fresh_library):
    """Item 1 of the first ever drop has its row and its upload is queued.
    HEAD sampled that row, found no file, and refused item 2 with a 503
    blaming the mount until item 1 landed, which with uploads paused is
    never."""
    root, con = fresh_library
    con.execute("INSERT INTO tracks(id, rel_path) VALUES(1, 'First.wav')")
    con.execute("INSERT INTO ingest_items VALUES('i1', 1, 'uploading')")

    ok, why = config.share_root_ready(con)

    assert ok, why


def test_a_landed_row_that_is_missing_still_says_not_mounted(fresh_library):
    """The guard itself is unchanged: a row whose upload was confirmed (or
    that no batch owns) and whose file is not visible is still evidence."""
    root, con = fresh_library
    con.execute("INSERT INTO tracks(id, rel_path) VALUES(1, 'Old.wav')")
    con.execute("INSERT INTO tracks(id, rel_path) VALUES(2, 'Landed.wav')")
    con.execute("INSERT INTO ingest_items VALUES('i2', 2, 'live')")

    ok, why = config.share_root_ready(con)

    assert not ok and 'not mounted' in why


def test_first_run_root_creation_ignores_unlanded_rows(tmp_path, monkeypatch,
                                                       fresh_library):
    """The same question when the root does not exist yet: rows whose audio
    has not landed do not contradict a first run, so a NAME may be allocated.
    Review round: the strict answer (any row at all) is still the default,
    because that is what guards the mkdir of the root (music-1)."""
    _root, con = fresh_library
    missing = tmp_path / 'not-yet'
    monkeypatch.setitem(config.SHARE_ROOTS, config.SHARE, missing)
    con.execute("INSERT INTO tracks(id, rel_path) VALUES(1, 'First.wav')")
    con.execute("INSERT INTO ingest_items VALUES('i1', 1, 'indexed')")

    assert config.library_has_tracks(con, count_unlanded=False) is False
    assert config.library_has_tracks(con) is True
    assert config.share_root_ready(con)[0] is True


@pytest.mark.parametrize('state', ['failed', 'pending', 'embedding'])
def test_a_failed_or_retried_upload_is_not_evidence_either(fresh_library,
                                                           state):
    """Review round (2026-09-25). retry_failed keeps a failed item's track_id
    and tracks row, and an item that failed after its result is an upload that
    never landed. With only indexed/uploading left out, a first drop whose
    item 1 upload failed refused every later result (and the next batch) with
    "not mounted" until somebody pressed retry; a retried item walks back
    through pending/transcoding/embedding with the same row."""
    root, con = fresh_library
    con.execute("INSERT INTO tracks(id, rel_path) VALUES(1, 'First.wav')")
    con.execute("INSERT INTO ingest_items VALUES('i1', 1, ?)", (state,))

    ok, why = config.share_root_ready(con)

    assert ok, why


def test_a_failed_row_beside_a_missing_landed_row_still_says_not_mounted(
        fresh_library):
    """Leaving the failed row out never hides the real evidence."""
    root, con = fresh_library
    con.execute("INSERT INTO tracks(id, rel_path) VALUES(1, 'Old.wav')")
    con.execute("INSERT INTO tracks(id, rel_path) VALUES(2, 'Failed.wav')")
    con.execute("INSERT INTO ingest_items VALUES('i2', 2, 'failed')")

    ok, why = config.share_root_ready(con)

    assert not ok and 'not mounted' in why


def test_a_browser_drop_does_not_mkdir_a_root_only_unlanded_rows_vouch_for(
        tmp_path, monkeypatch, fresh_library):
    """Review round (2026-09-25): the gate now lets a missing root through
    when the index holds only unlanded rows, but the one place that CREATES
    the root keeps the strict test and says why in words."""
    _root, con = fresh_library
    missing = tmp_path / 'not-yet'
    monkeypatch.setitem(config.SHARE_ROOTS, config.SHARE, missing)
    con.execute("INSERT INTO tracks(id, rel_path) VALUES(1, 'First.wav')")
    con.execute("INSERT INTO ingest_items VALUES('i1', 1, 'uploading')")

    with pytest.raises(RuntimeError, match='not there yet'):
        routes_ingest._create_share_root_on_first_run(con)
    assert not missing.exists()


def test_a_truly_empty_index_still_creates_the_root(tmp_path, monkeypatch,
                                                    fresh_library):
    _root, con = fresh_library
    missing = tmp_path / 'not-yet'
    monkeypatch.setitem(config.SHARE_ROOTS, config.SHARE, missing)

    routes_ingest._create_share_root_on_first_run(con)

    assert missing.is_dir()


def test_a_pre_004_database_keeps_the_old_answer(fresh_library):
    root, con = fresh_library
    con.execute('DROP TABLE ingest_items')
    con.execute("INSERT INTO tracks(id, rel_path) VALUES(1, 'Gone.wav')")

    assert config.share_root_ready(con)[0] is False
    assert config.library_has_tracks(con) is True


# --------------------------------------------------------------------------
# bug-music-ytdl-4 / logic-broll-music-3: a cancelled batch strands its rows
# --------------------------------------------------------------------------

def _result(fleet, uid, item, seed=7):
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/result',
                   json=result_body(seed=seed), headers=headers())
    assert r.status_code == 200, r.text
    return r.json()


def test_cancelling_drops_the_rows_whose_audio_never_landed(fleet, fake_encoder):
    """Indexed, never uploaded, then cancelled. HEAD left the tracks row in
    search, similar, browse and every percentile with an audio route that
    404s, holding its name, in a state nothing can leave."""
    uid = make_batch(fleet, names=('Never Landed.wav',))
    item = claim(fleet, uid).json()['items'][0]['uid']
    track_id = _result(fleet, uid, item)['track_id']
    conn = db.con()

    fleet.post(f'/api/ingest-batches/{uid}/cancel', headers=EDITOR)
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/release',
                   json={'state': 'cancelled'}, headers=headers())

    assert r.status_code == 200, r.text
    assert conn.execute('SELECT 1 FROM tracks WHERE id = ?',
                        (track_id,)).fetchone() is None, \
        'a cancelled track with no audio is still in the library'
    assert conn.execute('SELECT COUNT(*) FROM windows WHERE track_id = ?',
                        (track_id,)).fetchone()[0] == 0
    row = conn.execute('SELECT state, track_id FROM ingest_items WHERE uid = ?',
                       (item,)).fetchone()
    assert row['state'] == 'cancelled' and row['track_id'] is None
    # and the name is free for the next drop
    assert ingest_batches.allocate_name(conn, 'Never Landed.wav') == \
        'Never Landed.wav'


def test_a_cancelled_row_whose_file_did_land_is_kept(fleet, fake_encoder):
    """The upload landed and `uploaded` never came: the file and its row are
    real, and deleting the row would orphan the audio."""
    uid = make_batch(fleet, names=('Did Land.wav',))
    item = claim(fleet, uid).json()['items'][0]['uid']
    got = _result(fleet, uid, item, seed=9)
    path = config.share_root() / got['rel_path']
    path.write_bytes(b'\x00' * 2048)
    try:
        fleet.post(f'/api/ingest-batches/{uid}/cancel', headers=EDITOR)
        r = fleet.post(f'/api/fleet/ingest/batches/{uid}/release',
                       json={'state': 'cancelled'}, headers=headers())
        assert r.status_code == 200, r.text
        conn = db.con()
        assert conn.execute('SELECT 1 FROM tracks WHERE id = ?',
                            (got['track_id'],)).fetchone() is not None
    finally:
        path.unlink(missing_ok=True)
        conn = db.con()
        conn.execute('DELETE FROM tracks WHERE id = ?', (got['track_id'],))
        conn.commit()


def test_a_share_this_host_cannot_see_keeps_every_row(fleet, fake_encoder,
                                                      monkeypatch):
    """"Not on disk" means nothing when the mount is gone, and this is the
    one path here that destroys embeddings."""
    uid = make_batch(fleet, names=('Blind Cancel.wav',))
    item = claim(fleet, uid).json()['items'][0]['uid']
    track_id = _result(fleet, uid, item, seed=11)['track_id']
    monkeypatch.setattr(config, 'share_root_ready',
                        lambda *a, **k: (False, 'not mounted'))
    try:
        fleet.post(f'/api/ingest-batches/{uid}/cancel', headers=EDITOR)
        fleet.post(f'/api/fleet/ingest/batches/{uid}/release',
                   json={'state': 'cancelled'}, headers=headers())
        conn = db.con()
        assert conn.execute('SELECT 1 FROM tracks WHERE id = ?',
                            (track_id,)).fetchone() is not None
    finally:
        conn = db.con()
        conn.execute('DELETE FROM tracks WHERE id = ?', (track_id,))
        conn.commit()


# --------------------------------------------------------------------------
# bug-broll-4, music twin (Fable round, 2026-09-25): a stale machine's
# cancelled release must not delete the new holder's rows
# --------------------------------------------------------------------------

def _expire_lease(uid):
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    conn = db.con()
    conn.execute('UPDATE ingest_batches SET lease_expires_at = ? WHERE uid = ?',
                 (past, uid))
    conn.commit()


def test_a_stale_machine_cannot_cancel_a_batch_another_machine_took_over(
        fleet, fake_encoder):
    """Fable's probe: EDIT-01 claims, its lease expires, EDIT-02 takes over
    and posts a result, then EDIT-01 posts cancelled. The working tree before
    this fix answered 200 and deleted EDIT-02's tracks row."""
    uid = make_batch(fleet, names=('Taken Over.wav',))
    assert claim(fleet, uid, machine='EDIT-01').status_code == 200
    _expire_lease(uid)
    r = claim(fleet, uid, machine='EDIT-02')
    assert r.status_code == 200, r.text
    item = r.json()['items'][0]['uid']
    got = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/result',
                     json=result_body(seed=13), headers=headers(machine='EDIT-02'))
    assert got.status_code == 200, got.text
    track_id = got.json()['track_id']
    try:
        r = fleet.post(f'/api/fleet/ingest/batches/{uid}/release',
                       json={'state': 'cancelled'},
                       headers=headers(machine='EDIT-01'))
        assert r.status_code == 410, r.text
        assert r.json()['detail']['reason'] == 'other_machine'
        conn = db.con()
        assert ingest_batches.get_batch(conn, uid)['state'] \
            not in ingest_batches.BATCH_TERMINAL
        assert conn.execute('SELECT 1 FROM tracks WHERE id = ?',
                            (track_id,)).fetchone() is not None, \
            "the stale machine's cancel deleted the holder's track"
        assert conn.execute('SELECT track_id FROM ingest_items WHERE uid = ?',
                            (item,)).fetchone()['track_id'] == track_id
    finally:
        conn = db.con()
        conn.execute('DELETE FROM tracks WHERE id = ?', (track_id,))
        conn.commit()


def test_the_holder_and_an_expired_lease_can_still_cancel(fleet, fake_encoder):
    uid = make_batch(fleet, names=('Expired Only.wav',))
    assert claim(fleet, uid, machine='EDIT-01').status_code == 200
    _expire_lease(uid)
    # Nobody took it over: the relaxation this route exists for.
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/release',
                   json={'state': 'cancelled'}, headers=headers(machine='EDIT-01'))
    assert r.status_code == 200, r.text
    assert ingest_batches.get_batch(db.con(), uid)['state'] == 'cancelled'


# --------------------------------------------------------------------------
# ui-music-ytdl-web-4: the player pane clipped its own buttons and messages
# --------------------------------------------------------------------------

def _css_rule(css, selector):
    m = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', css)
    assert m, selector
    return m.group(1)


def test_the_open_pane_is_as_tall_as_what_it_holds():
    """HEAD: `.pane.open { height: 150px }` over content measured at 161 px
    on a desktop (a fleet track's no-waveform caption plus the Resolve error
    line) and 237 px on a phone, clipped with no scroll."""
    css = (STATIC / 'style.css').read_text(encoding='utf-8')
    opened = _css_rule(css, '.pane.open')
    assert 'height' not in opened.replace('grid-template-rows', ''), opened
    assert 'grid-template-rows: 1fr' in opened
    assert 'grid-template-rows: 0fr' in _css_rule(css, '.pane')
    inner = _css_rule(css, '.paneinner')
    assert 'min-height: 0' in inner and 'overflow: hidden' in inner
    # a 0fr row still shows the item's padding and border: closed must be 0
    closed = _css_rule(css, '.pane:not(.open) .paneinner')
    assert 'padding-top: 0' in closed and 'border-bottom-width: 0' in closed


# --------------------------------------------------------------------------
# ui-music-ytdl-web-5: a rail control threw the typed search away
# --------------------------------------------------------------------------

NODE = shutil.which('node')


def _js_function(body, name):
    start = body.index(f'function {name}(')
    end = body.index('\n}\n', start) + 3
    return body[start:end].replace('\r\n', '\n')


@pytest.mark.skipif(NODE is None, reason='node is not installed')
def test_include_them_under_a_search_re_runs_the_search(tmp_path):
    """The `[ include them ]` offer runSearch itself draws. HEAD's button
    called loadTracks(), replacing the ranked results with the whole library
    under "All tracks" while the box still held the query."""
    body = (STATIC / 'app.js').read_text(encoding='utf-8')
    script = r"""
const calls = [];
const state = {includeUnknown: false};
const nodes = {'#q': {value: 'tense driving synth'},
               '#resulthead': {kids: [], appendChild(c) { this.kids.push(c); }}};
const $ = s => nodes[s];
function el(tag, cls, text) { return {tag, cls, text}; }
function syncUnknownToggle() {}
function runSearch(q) { calls.push(['search', q]); }
function loadTracks() { calls.push(['browse']); }
""" + _js_function(body, 'noteUnknownHidden') + r"""
""" + (_js_function(body, 'refreshResults') if 'function refreshResults(' in body
       else '') + r"""
noteUnknownHidden({unknown_hidden: 3, unknown_fields: ['bpm']});
const btn = nodes['#resulthead'].kids.filter(k => k.tag === 'button')[0];
btn.onclick();
nodes['#q'].value = '';
btn.onclick();
console.log(JSON.stringify(calls));
"""
    f = tmp_path / 'case.js'
    f.write_text(script, encoding='utf-8')
    out = subprocess.run([NODE, str(f)], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    calls = json.loads(out.stdout.strip().splitlines()[-1])
    assert calls[0] == ['search', 'tense driving synth'], calls
    assert calls[1] == ['browse'], 'an empty box still means browse'


@pytest.mark.parametrize('anchor', [
    "unknown.onchange = () =>",
    "$('#applyRange').onclick = () =>",
    "state.axis = r.value === '0' ? null",
])
def test_no_rail_control_goes_straight_to_the_browse_route(anchor):
    body = (STATIC / 'app.js').read_text(encoding='utf-8').replace('\r\n', '\n')
    at = body.index(anchor)
    handler = body[at:re.compile(r'\n\s*\};\n').search(body, at).end()]
    assert 'loadTracks()' not in handler, handler
    assert 'refreshResults()' in handler, handler


# ui-music-ytdl-web-5 review round (2026-09-25): the sort under a ranked answer.

@pytest.mark.skipif(NODE is None, reason='node is not installed')
def test_the_sort_is_switched_off_while_a_ranked_answer_shows(tmp_path):
    """/api/search and /api/similar rank by match and take no sort, so after
    the first fix the control re-ran the search and gave back the same order.
    It is disabled, and says why, whenever a search or a similar list is
    showing or on its way, and a browse list turns it back on."""
    body = (STATIC / 'app.js').read_text(encoding='utf-8')
    script = r"""
const state = {seq: 0, bpm: {}, dur: {}, sort: 'filename'};
const nodes = {'#q': {value: ''}, '#pool': {value: 'mean'},
               '#sort': {disabled: false, title: ''},
               '#sortnote': {hidden: true}};
const $ = s => nodes[s];
function render() {}
function noteUnknownHidden() {}
function failureText() { return ''; }
function filterFields() { return {}; }
function filterParams() { return new URLSearchParams(); }
async function api(url) { return {tracks: []}; }
""" + _js_function(body, 'sortApplies') + ''.join(
        'async ' + _js_function(body, n)
        for n in ('loadTracks', 'runSearch', 'showSimilar')) + r"""
const seen = [];
const snap = tag => seen.push([tag, nodes['#sort'].disabled, nodes['#sortnote'].hidden]);
(async () => {
  await runSearch('tense synth'); snap('search');
  await loadTracks(); snap('browse');
  await showSimilar({id: 1, filename: 'a.wav'}); snap('similar');
  await runSearch(''); snap('empty search browses');
  console.log(JSON.stringify(seen));
})();
"""
    f = tmp_path / 'sort.js'
    f.write_text(script, encoding='utf-8')
    out = subprocess.run([NODE, str(f)], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    seen = json.loads(out.stdout.strip().splitlines()[-1])
    assert seen == [['search', True, False], ['browse', False, True],
                    ['similar', True, False],
                    ['empty search browses', False, True]], seen


def test_the_sort_handler_reorders_the_browse_list():
    """Reachable only while browsing, so it browses: a query typed and not
    yet searched is not sent (and paid for) by a sort change."""
    body = (STATIC / 'app.js').read_text(encoding='utf-8')
    at = body.index('sort.onchange = () =>')
    handler = body[at:body.index('};', at) + 2]
    assert 'loadTracks()' in handler and 'runSearch' not in handler, handler


def test_the_page_says_why_the_sort_is_off():
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    note = re.search(r'<span id="sortnote"[^>]*\bhidden\b[^>]*>([^<]+)<', html)
    assert note and 'match' in note.group(1), 'no visible reason beside the sort'


# --------------------------------------------------------------------------
# chunk 2 of the wave: ui-music-ytdl-web-6..9 (static files, driven in node)
# --------------------------------------------------------------------------

def _run_node(tmp_path, script, name='case.js'):
    f = tmp_path / name
    f.write_text(script, encoding='utf-8')
    out = subprocess.run([NODE, str(f)], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _app_js():
    return (STATIC / 'app.js').read_text(encoding='utf-8')


def _ingest_js():
    return (STATIC / 'ingest.js').read_text(encoding='utf-8')


# ui-music-ytdl-web-6: a length filter that matches nothing is not "empty"

@pytest.mark.skipif(NODE is None, reason='node is not installed')
def test_a_length_filter_is_named_in_the_headline(tmp_path):
    """HEAD built the headline from facet, axis and BPM only, so Secs min 900
    over a 397-track library read "All tracks" and "The library is empty"."""
    got = _run_node(tmp_path, r"""
const state = {seq: 0, facet: null, axis: null, bpm: {min: null, max: null},
               dur: {min: 900, max: null}};
let seen = null;
function render(tracks, headline, showMatch, empty) { seen = {headline, empty}; }
function sortApplies() {}
function noteUnknownHidden() {}
function failureText() { return ''; }
function filterParams() { return new URLSearchParams(); }
async function api() { return {tracks: []}; }
async """ + _js_function(_app_js(), 'loadTracks') + r"""
loadTracks().then(() => console.log(JSON.stringify(seen)));
""")
    assert '900' in got['headline'] and got['headline'] != 'All tracks', got
    assert 'library is empty' not in got['empty'], got
    assert 'No tracks match these filters' in got['empty'], got


# ui-music-ytdl-web-7: a failed stats/facets call no longer kills the page

@pytest.mark.skipif(NODE is None, reason='node is not installed')
def test_a_failed_stats_call_leaves_a_working_page(tmp_path):
    """HEAD awaited api/stats and api/facets before wiring anything: one 401
    left SEARCH, clear and ADD MUSIC dead over `Failed to load: api/stats ->
    401`. The handlers are wired first and the list still loads."""
    body = _app_js()
    extra = ''
    if 'function trackHeaderHeight(' in body:
        extra += _js_function(body, 'trackHeaderHeight')
    if 'function loadLibraryMeta(' in body:
        extra += 'async ' + _js_function(body, 'loadLibraryMeta')
    got = _run_node(tmp_path, r"""
const nodes = {};
function mk() {
  return {value: '', textContent: '', title: '', checked: false, style: {},
          classList: {add() {}, remove() {}, toggle() {}},
          addEventListener() {}, appendChild() {}, querySelector() { return null; }};
}
const $ = s => nodes[s] || (nodes[s] = mk());
global.document = {getElementById: () => null, querySelector: s => $(s),
                   querySelectorAll: () => [],
                   documentElement: {style: {setProperty() {}}}};
global.fetch = async url => ({ok: false, status: 401, json: async () => ({})});
const EXAMPLES = ['a'];
let FACETS = {};
const calls = [];
function el() { return mk(); }
function loadDashboardTopbar() {}
function paintFacets() { calls.push('facets'); }
function paintAxes() {}
function syncUnknownToggle() {}
function runSearch() {}
function refreshResults() {}
function toast() {}
function audio() { return {addEventListener() {}}; }
function wireDropzone() { calls.push('dropzone'); }
function refreshResolveStatus() {}
global.setInterval = () => 0;
async function loadTracks() { calls.push('tracks'); }
""" + _js_function(body, 'api').replace('function api', 'async function api')
      + _js_function(body, 'failureText') + _js_function(body, 'statsLine')
      + _js_function(body, 'paintStats') + extra
      + 'async ' + _js_function(body, 'init') + r"""
init().then(() => 'ok', e => String(e && e.message)).then(outcome => {
  console.log(JSON.stringify({outcome, calls,
    go: typeof $('#go').onclick, clear: typeof $('#clear').onclick,
    stats: $('#stats').textContent, statsTitle: $('#stats').title}));
});
""")
    assert got['outcome'] == 'ok', got
    assert got['go'] == 'function' and got['clear'] == 'function', got
    assert 'tracks' in got['calls'] and 'dropzone' in got['calls'], got
    assert 'session expired' in got['statsTitle'], got


def test_a_page_that_still_fails_to_start_says_so_in_words():
    body = _app_js().replace('\r\n', '\n')
    tail = body[body.rindex('init().catch('):]
    assert "failureText('Loading the page', e)" in tail, tail
    assert "'Failed to load: '" not in tail


# ui-music-ytdl-web-8: the header's height is measured, and a phone's scrolls

@pytest.mark.skipif(NODE is None, reason='node is not installed')
def test_the_rail_offset_is_the_headers_measured_height(tmp_path):
    body = _app_js()
    assert 'trackHeaderHeight();' in _js_function(body, 'init')
    got = _run_node(tmp_path, r"""
const props = {};
let observer = null;
const header = {h: 150, getBoundingClientRect() { return {height: this.h}; }};
global.document = {getElementById: id => id === 'app-header' ? header : null,
                   documentElement: {style: {setProperty(k, v) { props[k] = v; }}}};
global.ResizeObserver = class { constructor(fn) { observer = fn; }
                                observe() {} };
""" + _js_function(body, 'trackHeaderHeight') + r"""
trackHeaderHeight();
const first = props['--header-h'];
header.h = 212.4; observer();
console.log(JSON.stringify([first, props['--header-h']]));
""")
    assert got == ['150px', '213px'], got


def test_a_narrow_screen_does_not_pin_the_header():
    """HEAD: the header stayed sticky below 900 px and wrapped to 263 px, a
    third of a 390x844 phone."""
    css = (STATIC / 'style.css').read_text(encoding='utf-8').replace('\r\n', '\n')
    blocks = re.findall(r'@media \(max-width: 900px\) \{(.*?)\n\}', css, re.S)
    assert any(re.search(r'#app-header \{[^}]*position: static', b)
               for b in blocks), blocks


# ui-music-ytdl-web-9: a finished batch stops offering to run its tracks again

def _poll_script(running, items, ran_uid=None, ran_ids=None):
    """miPollServer seeing batch b1 turn `done`, from the given page state.
    `ran_uid`/`ran_ids` are what miRun records for this page's own run."""
    body = _ingest_js()
    ran = ('null' if ran_ids is None
           else 'new Set(' + json.dumps(ran_ids) + ')')
    return r"""
const MI_TERMINAL_STATES = ['done', 'done_with_errors', 'cancelled', 'failed'];
const mi = {open: true, batchUid: 'b1', running: """ + ('true' if running else 'false') + r""",
            items: """ + json.dumps(
        [{'local_id': i, 'include': True} for i in items]) + r""",
            staged: true, precheckKey: 'k',
            stagingId: 's1', batch: null, batchItems: [],
            ranBatchUid: """ + json.dumps(ran_uid) + ', ranIds: ' + ran + r"""};
let prepared = 0;
async function miApi() { return {batch: {uid: 'b1', state: 'done'}, items: []}; }
function miNoteBatchState() {}
function miRenderLive() {}
function miRenderPreview() {}
function miRenderSummary() {}
function miSchedulePrepare() { prepared += 1; }
""" + _js_function(body, 'miForgetRunDrop') + 'async ' +         _js_function(body, 'miPollServer') + r"""
miPollServer().then(() => console.log(JSON.stringify(
  {items: mi.items.map(i => i.local_id), staged: mi.staged, running: mi.running,
   stagingId: mi.stagingId, ranBatchUid: mi.ranBatchUid, prepared})));
"""


@pytest.mark.skipif(NODE is None, reason='node is not installed')
def test_the_run_drop_is_cleared_when_its_batch_ends(tmp_path):
    """HEAD left the 20 staged tracks ticked under an enabled Run button, and
    pressing it minted a second batch of the same files."""
    got = _run_node(tmp_path, _poll_script(True, ['a', 'b'], 'b1', ['a', 'b']))
    assert got['items'] == [] and got['staged'] is False, got
    assert got['running'] is False
    assert got['ranBatchUid'] is None and got['prepared'] == 0, got
    # kept for miTakeOver / miRetryFailed on the batch this page ran
    assert got['stagingId'] == 's1', got


@pytest.mark.skipif(NODE is None, reason='node is not installed')
def test_a_drop_made_during_the_run_survives_its_end(tmp_path):
    """Review round: tracks dropped while this page's batch ran are not the
    batch's, and round 1 emptied them with it. Only the ran ids go, and the
    rest are staged (prepare held off during the run)."""
    got = _run_node(tmp_path,
                    _poll_script(True, ['a', 'new'], 'b1', ['a']))
    assert got['items'] == ['new'] and got['staged'] is False, got
    assert got['prepared'] == 1, got


@pytest.mark.skipif(NODE is None, reason='node is not installed')
def test_a_reattached_batch_does_not_clear_a_new_drop(tmp_path):
    """Review round: the list poll's re-attach after a reload (and
    miTakeOver) set `running = true` with no run of this page's behind it.
    That is the real state here: running, an item dropped since, no record."""
    got = _run_node(tmp_path, _poll_script(True, ['new']))
    assert got['items'] == ['new'] and got['staged'] is True, got
    assert got['running'] is False and got['prepared'] == 0, got


@pytest.mark.skipif(NODE is None, reason='node is not installed')
def test_a_taken_over_batch_does_not_clear_this_pages_older_run(tmp_path):
    """A record for a different batch (this page ran b0, then took over b1)
    does not let b1's end remove b0's items."""
    got = _run_node(tmp_path, _poll_script(True, ['a'], 'b0', ['a']))
    assert got['items'] == ['a'] and got['staged'] is True, got


def test_mirun_records_the_batch_and_its_items():
    body = _js_function(_ingest_js(), 'miRun')
    assert 'mi.ranBatchUid = created.uid' in body
    assert 'mi.ranIds = new Set(chosen.map(' in body
    # recorded only once the companion took it, beside `running = true`
    assert body.index('mi.ranIds') > body.index("'/music/ingest/run'")


@pytest.mark.skipif(NODE is None, reason='node is not installed')
def test_the_live_section_stops_saying_running(tmp_path):
    body = _ingest_js()
    got = _run_node(tmp_path, r"""
const MI_TERMINAL_STATES = ['done', 'done_with_errors', 'cancelled', 'failed'];
const MI_COMPANION_HINT = '';
function mk() { return {textContent: '', disabled: false, innerHTML: '', title: '',
                        classList: {add() {}, remove() {}},
                        appendChild() {}, querySelector() { return null; }}; }
const h3 = mk(); h3.textContent = 'Running';
const live = mk(); live.querySelector = s => s === 'h3' ? h3 : null;
const nodes = {'#mi-live': live};
const $ = s => nodes[s] || (nodes[s] = mk());
function el() { return mk(); }
function miWords(t, s) { return s; }
function miItemLine() { return mk(); }
const MI_BATCH_WORDS = {};
const mi = {batchUid: 'b1', batch: {state: 'done', n_done: 1, n_items: 1, n_live: 1,
            n_failed: 0, n_duplicate: 0}, loopback: null, running: false,
            batchItems: []};
""" + _js_function(body, 'miRenderLive') + r"""
miRenderLive();
const over = h3.textContent;
mi.batch.state = 'running';
miRenderLive();
console.log(JSON.stringify([over, h3.textContent]));
""")
    assert got == ['Last batch', 'Running'], got


# --------------------------------------------------------------------------
# Owed round (2026-09-25)
# --------------------------------------------------------------------------
# bug-wire-2: an identity signed with a retired dashboard key is accepted
# --------------------------------------------------------------------------

from fastapi import HTTPException  # noqa: E402

from musicweb import fleet_auth, identity  # noqa: E402

OLD_SECRET = 'a-retired-session-secret-0123456789'


def test_an_identity_signed_with_a_retired_key_is_accepted(monkeypatch):
    """The dashboard keeps accepting a retired key for the whole rotation
    drain; HEAD refused it here with 403 "sign in again" on every claim,
    heartbeat and result."""
    monkeypatch.setenv('DASH_SESSION_SECRET', 'the-current-session-secret-0123')
    monkeypatch.setenv('DASH_SESSION_SECRET_PREVIOUS',
                       f' , {OLD_SECRET} ,another-old-one-0123456789')
    token = identity.make_identity_token(OLD_SECRET, 'jsmith')
    assert fleet_auth.require_identity(token) == 'jsmith'


def test_previous_secrets_parse_like_the_dashboards(monkeypatch):
    monkeypatch.setenv('DASH_SESSION_SECRET_PREVIOUS', ' a , ,b,, ')
    assert config.previous_session_secrets() == ('a', 'b')
    monkeypatch.delenv('DASH_SESSION_SECRET_PREVIOUS', raising=False)
    assert config.previous_session_secrets() == ()


def test_a_key_that_was_never_ours_is_still_refused(monkeypatch):
    monkeypatch.setenv('DASH_SESSION_SECRET', 'the-current-session-secret-0123')
    monkeypatch.setenv('DASH_SESSION_SECRET_PREVIOUS', OLD_SECRET)
    token = identity.make_identity_token('somebody-elses-secret-0123456', 'jsmith')
    with pytest.raises(HTTPException) as exc:
        fleet_auth.require_identity(token)
    assert exc.value.status_code == 403
    assert exc.value.detail['reason'] == 'identity'


def test_a_retired_key_does_not_stand_in_for_an_unset_current_one(monkeypatch):
    """Accept-only: the retired keys never make an unconfigured server open."""
    monkeypatch.delenv('DASH_SESSION_SECRET', raising=False)
    monkeypatch.setenv('DASH_SESSION_SECRET_PREVIOUS', OLD_SECRET)
    with pytest.raises(HTTPException) as exc:
        fleet_auth.require_identity(identity.make_identity_token(OLD_SECRET, 'jsmith'))
    assert exc.value.detail['reason'] == 'identity_unconfigured'


# --------------------------------------------------------------------------
# bug-wire-7: a CJK-named machine's percent-encoded header gets the check back
# --------------------------------------------------------------------------

CJK = '剪輯-PC'


def _pct_headers(machine):
    from urllib.parse import quote
    out = headers(machine=None)
    out['X-CCSync-Machine-Pct'] = quote(machine, safe='')
    return out


def test_the_pct_header_names_the_holder(fleet, fake_encoder):
    uid = make_batch(fleet)
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/claim',
                   json={'machine': CJK, 'companion_version': '0.9.79'},
                   headers=_pct_headers(CJK))
    assert r.status_code == 200, r.text
    ok = fleet.post(f'/api/fleet/ingest/batches/{uid}/heartbeat', json={},
                    headers=_pct_headers(CJK))
    assert ok.status_code == 200, ok.text


def test_another_machine_is_refused_through_the_pct_header(fleet, fake_encoder):
    """HEAD read only X-CCSync-Machine, so a CJK-named machine sent none and
    the machine check was skipped: a second computer of the same editor could
    heartbeat (and post results into) a batch the first one holds."""
    uid = make_batch(fleet)
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/claim',
                   json={'machine': CJK, 'companion_version': '0.9.79'},
                   headers=_pct_headers(CJK))
    assert r.status_code == 200, r.text
    other = fleet.post(f'/api/fleet/ingest/batches/{uid}/heartbeat', json={},
                       headers=_pct_headers('編集-MAC'))
    assert other.status_code == 410, other.text
    assert other.json()['detail']['reason'] == 'other_machine'


def test_the_plain_header_wins_and_a_bad_escape_names_nobody():
    from musicweb import routes_fleet
    assert routes_fleet._declared_machine('EDIT-01', '%E5%89%AA') == 'EDIT-01'
    assert routes_fleet._declared_machine(None, None) is None
    assert routes_fleet._declared_machine(None, '%E5%89%AA%E8%BC%AF-PC') == CJK
    assert routes_fleet._declared_machine(None, '%ZZ%E5') not in (None, CJK)


# --------------------------------------------------------------------------
# ui-copy-5 and the ui-dash-static-5 parity
# --------------------------------------------------------------------------

def test_the_refused_send_names_the_trays_real_route():
    body = (STATIC / 'app.js').read_text(encoding='utf-8')
    assert 'Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN' in body
    assert 'Settings > Help > Copy diagnostics' not in body


def _hex_lum(h):
    h = h.lstrip('#')
    def ch(v):
        v = int(v, 16) / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(h[i:i + 2]) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_muted_text_meets_aa_on_every_surface():
    css = (STATIC / 'style.css').read_text(encoding='utf-8')
    tok = dict(re.findall(r'--(bg|panel|field|muted):\s*(#[0-9a-fA-F]{6})', css))
    fg = _hex_lum(tok['muted'])
    for surface in ('bg', 'panel', 'field'):
        bg = _hex_lum(tok[surface])
        assert (fg + 0.05) / (bg + 0.05) >= 4.5, surface


def test_the_drawer_close_control_meets_aa_on_the_drawer_panel():
    # ui-dash-static owed round 2 (2026-09-25): was var(--red-dim), 1.78:1.
    css = (STATIC / 'style.css').read_text(encoding='utf-8')
    tok = dict(re.findall(r'--([a-z-]+):\s*(#[0-9a-fA-F]{6})', css))
    m = re.search(r'\.drawer-close\s*\{[^}]*?color:\s*var\(--([a-z-]+)\)', css)
    assert m, 'no .drawer-close colour'
    fg, bg = _hex_lum(tok[m.group(1)]), _hex_lum(tok['panel'])
    assert (max(fg, bg) + 0.05) / (min(fg, bg) + 0.05) >= 4.5, m.group(1)
