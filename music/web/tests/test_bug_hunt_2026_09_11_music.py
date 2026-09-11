"""Bug hunt 2026-09-11, the music territory (CR-246): music-1 .. music-7.

Every test here fails at 40f931a. The two that matter most cannot be written
as a plain call: music-1's defect is a LOOP, so the pre-fix behaviour is a
hang, not an exception. `_with_deadline` runs the call on a daemon thread and
turns "still running" into a failure, which is what makes the regression
visible in a test run rather than in a stuck worker.

    cd E:\\Projects\\resolve-remote-sync\\music\\web
    .venv\\Scripts\\python.exe -m pytest tests/test_bug_hunt_2026_09_11_music.py -q
"""
import re
import sqlite3
import sys
import threading
import types
from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException

from musicweb import config, db, ingest_batches, rescore, routes_media
from tests.test_fleet_ingest import (MACHINE, FakeEncoder, fleet,  # noqa: F401
                                     headers, make_batch)

EDITOR = {'X-CCSync-User': 'jsmith'}


def _with_deadline(fn, seconds=5.0):
    """Call `fn` on a daemon thread and fail if it has not returned in time.

    A loop with no ceiling does not raise: it holds a uvicorn threadpool thread
    at 100% CPU for ever. The thread stays daemon so a pre-fix run still exits.
    """
    box = {}

    def run():
        try:
            box['value'] = fn()
        except BaseException as exc:                            # noqa: BLE001
            box['error'] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        pytest.fail('the call never returned: it is the unbounded loop (music-1)')
    if 'error' in box:
        raise box['error']
    return box['value']


# --------------------------------------------------------------------------
# music-1: allocate_name has a ceiling, and "could not tell" is not "taken"
# --------------------------------------------------------------------------

class LockedConn:
    """A connection whose every query fails the way a locked or malformed
    music.db does. `share_root_ready` swallows this and fails open, which is
    exactly how the bad connection reached the collision loop."""

    def execute(self, *a, **kw):
        raise sqlite3.OperationalError('database is locked')


def test_a_database_that_cannot_answer_is_a_503_not_a_loop(seeded_db):
    config.forget_ready_cache()

    def call():
        return ingest_batches.allocate_name(LockedConn(), 'theme.wav')

    with pytest.raises(HTTPException) as exc:
        _with_deadline(call)
    assert exc.value.status_code == 503
    assert exc.value.detail['reason'] == 'library_unavailable'
    assert exc.value.detail['retry'] is True


def _blank_index():
    """An index with no tracks: a fresh customer deployment, which is the case
    `share_root_ready` deliberately lets through."""
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute('CREATE TABLE tracks (id INTEGER PRIMARY KEY, rel_path TEXT)')
    return con


def test_a_share_that_faults_on_stat_is_a_503_not_a_loop(seeded_db, monkeypatch):
    """The trigger that needs no database fault at all: a bind mount this uid
    can stat but not traverse, on a deployment whose index is still empty so
    the gate above passes. pathlib swallows ENOENT, not EACCES, so the error
    propagated out of exists() and `_taken_on_disk` called every candidate
    taken."""
    config.forget_ready_cache()
    conn = _blank_index()

    def faulting(*a, **kw):
        raise PermissionError(13, 'Permission denied')

    monkeypatch.setattr(ingest_batches.config, 'safe_join', faulting)

    def call():
        return ingest_batches.allocate_name(conn, 'theme.wav')

    with pytest.raises(HTTPException) as exc:
        _with_deadline(call)
    assert exc.value.status_code == 503
    assert exc.value.detail['reason'] == 'library_unavailable'
    assert 'PermissionError' in exc.value.detail['detail']


def test_the_collision_loop_has_a_ceiling(seeded_db, monkeypatch):
    """Every candidate genuinely taken is still not a reason to mint names for
    ever: a thousand is a broken library, not a drop."""
    config.forget_ready_cache()
    monkeypatch.setattr(ingest_batches, '_disk_state', lambda name: (True, None))

    def call():
        return ingest_batches.allocate_name(db.con(), 'theme.wav')

    with pytest.raises(HTTPException) as exc:
        _with_deadline(call, seconds=20.0)
    assert exc.value.status_code == 503
    assert exc.value.detail['reason'] == 'too_many_collisions'


def test_a_healthy_library_still_steps_around_a_collision(seeded_db):
    """The cap and the tri-state must not change the ordinary answer."""
    config.forget_ready_cache()
    theme = config.share_root() / 'theme.wav'
    theme.write_bytes(b'x')
    conn = db.con()
    conn.execute("INSERT INTO tracks(id, rel_path, filename, ext, bytes, dim) "
                 "VALUES(9101, 'theme (2).wav', 'theme (2).wav', '.wav', 1, 8)")
    conn.commit()
    try:
        assert ingest_batches.allocate_name(conn, 'theme.wav') == 'theme (3).wav'
    finally:
        theme.unlink()
        conn.execute('DELETE FROM tracks WHERE id = 9101')
        conn.commit()
        config.forget_ready_cache()


# --------------------------------------------------------------------------
# music-2: the refusals say they are worth retrying, and a failed track has a
# way back
# --------------------------------------------------------------------------

def test_the_share_not_ready_503_says_retry(seeded_db, tmp_path, monkeypatch):
    """The companion classifies on this: a bind mount that blips for thirty
    seconds used to kill every track of a fifteen-track drop."""
    config.forget_ready_cache()
    monkeypatch.setitem(config.SHARE_ROOTS, config.SHARE, tmp_path / 'not-mounted')
    with pytest.raises(HTTPException) as exc:
        ingest_batches.allocate_name(db.con(), 'theme.wav')
    assert exc.value.status_code == 503
    assert exc.value.detail['reason'] == 'share_not_ready'
    assert exc.value.detail['retry'] is True
    assert 'not mounted' in exc.value.detail['detail']


def _fail_one_item(uid):
    conn = db.con()
    item = conn.execute('SELECT uid FROM ingest_items WHERE batch_uid = ? '
                        'ORDER BY ord LIMIT 1', (uid,)).fetchone()
    conn.execute("UPDATE ingest_items SET state = 'failed', error = 'the library "
                 "would not take this track', stage_percent = 40 WHERE uid = ?",
                 (item['uid'],))
    conn.execute("UPDATE ingest_batches SET state = 'done_with_errors', "
                 "n_failed = 1, finished_at = '2026-09-11T00:00:00+00:00' "
                 'WHERE uid = ?', (uid,))
    conn.commit()
    return item['uid']


def test_a_failed_track_can_be_put_back_in_the_queue(fleet):
    """The music half of BROLL-18: without it, a drop that met a momentary
    refusal was dead with its audio still staged on the editor's machine."""
    uid = make_batch(fleet, names=('One.wav', 'Two.wav'))
    item_uid = _fail_one_item(uid)

    r = fleet.post(f'/api/ingest-batches/{uid}/retry-failed', headers=EDITOR)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body['retried'] == 1 and body['items'] == [item_uid]
    assert body['state'] == 'queued'
    conn = db.con()
    row = conn.execute('SELECT state, error, stage_percent FROM ingest_items '
                       'WHERE uid = ?', (item_uid,)).fetchone()
    assert row['state'] == 'pending' and row['error'] is None
    assert row['stage_percent'] is None
    batch = conn.execute('SELECT state, finished_at, n_failed FROM ingest_batches '
                         'WHERE uid = ?', (uid,)).fetchone()
    assert (batch['state'], batch['finished_at'], batch['n_failed']) == \
        ('queued', None, 0)


def test_retrying_a_batch_with_nothing_failed_is_answered_not_refused(fleet):
    uid = make_batch(fleet)
    r = fleet.post(f'/api/ingest-batches/{uid}/retry-failed', headers=EDITOR)
    assert r.status_code == 200, r.text
    assert r.json()['retried'] == 0


def test_the_page_only_says_running_when_the_companion_claimed_it():
    """The loopback half of music-2. `POST /music/ingest/retry` answers 202
    when the companion re-armed AND CLAIMED the batch on this machine; a
    companion published before that route answers 200 and claims nothing, so
    the batch is queued with no machine. Any non-202 success must therefore
    read as "queued again", never as "running here" - an editor told the work
    is running on a computer nothing claimed it on waits for ever."""
    body = (Path(config.STATIC_DIR) / 'ingest.js').read_text(encoding='utf-8')
    fn = body[body.index('async function miRetryFailed('):]
    fn = fn[:fn.index('\nasync function ')]
    assert "'/music/ingest/retry'" in fn, 'the old /music/ingest/run had no claim'
    assert 'batch_uid' in fn and 'staging_id' in fn
    assert 'status === 202' in fn, (
        'a 200 from an older companion is a success and not a claim')
    # music-3 (2026-09-11b): the fallback line used to say "press Run", which
    # submits the CURRENTLY staged selection as a brand new batch. It now
    # names the take-over button, which is the control that exists for this.
    assert 'take over on this computer' in fn


def test_another_editors_batch_cannot_be_retried(fleet):
    uid = make_batch(fleet)
    _fail_one_item(uid)
    r = fleet.post(f'/api/ingest-batches/{uid}/retry-failed',
                   headers={'X-CCSync-User': 'someone-else'})
    assert r.status_code == 404


# --------------------------------------------------------------------------
# music-3: the rescore clears only the snapshot it scored
# --------------------------------------------------------------------------

DIM = 8


def _small_library(path):
    con = db.connect(path)
    db.init(con)
    for i in range(1, 4):
        rng = np.random.default_rng(i)
        v = rng.normal(size=DIM).astype(np.float32)
        con.execute(
            'INSERT INTO tracks(id, rel_path, filename, ext, bytes, duration, '
            'embedding, dim, model, analyzed_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (i, f'Cue {i}.wav', f'Cue {i}.wav', '.wav', 1000, 60.0,
             db.to_blob(v / np.linalg.norm(v)), DIM, 'test-model',
             '2026-09-11T00:00:00+00:00'))
    con.commit()
    return con


@pytest.fixture()
def encoder(monkeypatch):
    monkeypatch.setattr(rescore, '_label_space', None, raising=False)
    monkeypatch.setattr(rescore, '_label_space_key', None, raising=False)
    return FakeEncoder()


def test_a_track_written_during_the_pass_keeps_its_stale_marker(tmp_path, encoder,
                                                                monkeypatch):
    """Editor B's result lands while editor A's rescore is in numpy. The marker
    it wrote used to be deleted by a pass that never saw its track, and
    `_settle_scores` is gated on exactly that marker: the track stayed in the
    library with no tags, no axes and no facets, and /api/stats said there was
    nothing to catch up on."""
    con = _small_library(tmp_path / 'lib.db')
    real_score_all = rescore.score_all

    def score_all_then_a_concurrent_write(*a, **kw):
        out = real_score_all(*a, **kw)
        con.execute(
            'INSERT INTO tracks(id, rel_path, filename, ext, bytes, duration, '
            'embedding, dim, model, analyzed_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (99, 'Late Arrival.wav', 'Late Arrival.wav', '.wav', 1000, 60.0,
             db.to_blob(np.ones(DIM, dtype=np.float32) / np.sqrt(DIM)), DIM,
             'test-model', '2026-09-11T00:01:00+00:00'))
        con.commit()
        rescore.mark_scores_stale(con)
        return out

    monkeypatch.setattr(rescore, 'score_all', score_all_then_a_concurrent_write)
    rescore.rescore_library(con, encoder)

    assert rescore.scores_stale(con), (
        'the marker belongs to a track this pass never loaded, so the '
        'end-of-batch settle must still see it')


def test_a_rescore_that_covers_everything_still_clears_the_marker(tmp_path,
                                                                  encoder):
    con = _small_library(tmp_path / 'lib.db')
    rescore.mark_scores_stale(con)
    rescore.rescore_library(con, encoder)
    assert rescore.scores_stale(con) is None


# --------------------------------------------------------------------------
# music-4: the docstring and the code agree about `force`
# --------------------------------------------------------------------------

def test_the_force_docstring_describes_what_actually_settles_a_batch():
    doc = rescore.apply_for_track.__doc__ or ''
    pkg = Path(rescore.__file__).parent
    callers = sorted(p.name for p in pkg.glob('*.py')
                     if re.search(r'apply_for_track\([^)]*force=True',
                                  p.read_text(encoding='utf-8')))
    if callers:
        pytest.skip(f'a production caller exists now: {callers}')
    assert '`release` passes force=True' not in doc, (
        'no production code passes force=True; a reader reconciling the two '
        'trusts the docstring (music-4)')
    assert '_settle_scores' in doc


# --------------------------------------------------------------------------
# music-5: the readiness probe samples tracks that exist
# --------------------------------------------------------------------------

def _index_with_old_and_new(newest_name):
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute('CREATE TABLE tracks (id INTEGER PRIMARY KEY, rel_path TEXT)')
    for i in range(1, 61):
        con.execute('INSERT INTO tracks(id, rel_path) VALUES(?,?)',
                    (i, f'Old Cue {i}.wav'))
    con.execute('INSERT INTO tracks(id, rel_path) VALUES(?,?)', (61, newest_name))
    con.commit()
    return con


def test_a_library_whose_oldest_files_were_tidied_away_is_still_ready(tmp_path,
                                                                      monkeypatch):
    """Sampling the fifty LOWEST ids closed the whole write path on a share
    that was mounted and full, with a message blaming the mount."""
    config.forget_ready_cache()
    root = tmp_path / 'music-share'
    root.mkdir()
    (root / 'Newest Cue.wav').write_bytes(b'x')
    monkeypatch.setitem(config.SHARE_ROOTS, config.SHARE, root)

    ok, why = config.share_root_ready(_index_with_old_and_new('Newest Cue.wav'))

    assert ok, why


def test_a_share_with_none_of_the_newest_tracks_is_still_refused(tmp_path,
                                                                 monkeypatch):
    """The refusal this probe exists for is unchanged: an unmounted bind mount
    presents as an ordinary empty directory."""
    config.forget_ready_cache()
    root = tmp_path / 'music-share'
    root.mkdir()
    monkeypatch.setitem(config.SHARE_ROOTS, config.SHARE, root)

    ok, why = config.share_root_ready(_index_with_old_and_new('Newest Cue.wav'))

    assert not ok and 'not mounted' in why


def test_a_positive_answer_is_not_re_probed_per_item(tmp_path, monkeypatch):
    """Up to fifty stat()s over SMB per allocate_name, i.e. per item of every
    drop. Only the positive answer is cached; a share that looks wrong is
    asked again every time."""
    config.forget_ready_cache()
    root = tmp_path / 'music-share'
    root.mkdir()
    (root / 'Newest Cue.wav').write_bytes(b'x')
    monkeypatch.setitem(config.SHARE_ROOTS, config.SHARE, root)
    con = _index_with_old_and_new('Newest Cue.wav')
    assert config.share_root_ready(con)[0]

    calls = []
    real_join = config.safe_join

    def counted(*a, **kw):
        calls.append(a)
        return real_join(*a, **kw)

    monkeypatch.setattr(config, 'safe_join', counted)
    assert config.share_root_ready(con)[0]
    assert calls == []
    config.forget_ready_cache()
    assert config.share_root_ready(con)[0]
    assert calls, 'and the cache is a few seconds, not for ever'


# --------------------------------------------------------------------------
# music-6: HEAD /api/audio
# --------------------------------------------------------------------------

def test_head_on_audio_answers_the_headers_a_player_probes_with(client):
    r = client.head('/api/audio/1')
    assert r.status_code == 200, r.text
    assert r.headers['accept-ranges'] == 'bytes'
    assert int(r.headers['content-length']) == 10240
    assert r.content == b''


def test_head_with_a_range_answers_206_and_no_body(client):
    r = client.head('/api/audio/1', headers={'Range': 'bytes=0-9'})
    assert r.status_code == 206, r.text
    assert r.headers['content-range'] == 'bytes 0-9/10240'
    assert r.headers['content-length'] == '10'
    assert r.content == b''


def test_head_on_an_unknown_track_is_still_a_404(client):
    assert client.head('/api/audio/99999').status_code == 404


def test_get_is_untouched_by_the_head_registration(client):
    r = client.get('/api/audio/1', headers={'Range': 'bytes=0-9'})
    assert r.status_code == 206
    assert len(r.content) == 10


# --------------------------------------------------------------------------
# music-7: the on-demand waveform fallback
# --------------------------------------------------------------------------

@pytest.fixture()
def peakless_track(seeded_db):
    """A track with a real file and no stored peaks, so /api/peaks falls
    through to the indexer."""
    conn = db.con()
    name = 'Peakless Cue.wav'
    path = config.share_root() / name
    path.write_bytes(b'not really audio')
    conn.execute('INSERT INTO tracks(id, rel_path, filename, ext, bytes, dim) '
                 'VALUES(9201, ?, ?, ?, 1, 8)', (name, name, '.wav'))
    conn.commit()
    yield 9201
    path.unlink()
    conn.execute('DELETE FROM tracks WHERE id = 9201')
    conn.execute('DELETE FROM peaks WHERE track_id = 9201')
    conn.commit()


def _stub_indexer(monkeypatch, peaks_from_file):
    pkg = types.ModuleType('music_index')
    audio = types.ModuleType('music_index.audio')
    audio.peaks_from_file = peaks_from_file
    pkg.audio = audio
    monkeypatch.setitem(sys.modules, 'music_index', pkg)
    monkeypatch.setitem(sys.modules, 'music_index.audio', audio)
    monkeypatch.setattr(routes_media.config, 'add_indexer_to_path', lambda: None)


def test_a_file_ffmpeg_cannot_decode_is_named_not_a_traceback(client, monkeypatch,
                                                              peakless_track):
    def boom(path):
        raise RuntimeError('ffmpeg exited 1: Invalid data found')

    _stub_indexer(monkeypatch, boom)
    r = client.get(f'/api/peaks/{peakless_track}')
    assert r.status_code == 503, r.text
    assert 'Invalid data found' in r.json()['detail']


def test_an_empty_decode_is_a_404_not_bytes_of_none(client, monkeypatch,
                                                    peakless_track):
    _stub_indexer(monkeypatch, lambda path: None)
    r = client.get(f'/api/peaks/{peakless_track}')
    assert r.status_code == 404, r.text


def test_a_waveform_that_builds_is_stored_and_served(client, monkeypatch,
                                                     peakless_track):
    _stub_indexer(monkeypatch, lambda path: bytes([1, 2, 3, 4]))
    r = client.get(f'/api/peaks/{peakless_track}')
    assert r.status_code == 200
    assert r.content == bytes([1, 2, 3, 4])
    assert db.con().execute('SELECT n FROM peaks WHERE track_id = ?',
                            (peakless_track,)).fetchone()['n'] == 4


# --------------------------------------------------------------------------
# CR-55 in music: a bound token and the identity it carries must agree
# (raised out of territory by the comp-broll-music hunter, 2026-09-11)
# --------------------------------------------------------------------------

CCE1 = 'cce1.0123456789abcdef.' + 's' * 43


def test_a_bound_token_may_not_carry_another_editors_name(fleet, monkeypatch):
    """ytdl and b-roll bind the two credentials (CR-55, 2026-08-21); music
    accepted the mount's `editor:` stamp and then believed whatever identity
    the request claimed, so the migration to per-editor tokens was a WEAKER
    check than the shared-token-plus-identity one it replaced."""
    monkeypatch.setattr(config, '_LOGIN_GATED', True, raising=False)
    # The batch belongs to the editor the IDENTITY names, so nothing further
    # down the route refuses this: at 40f931a the claim SUCCEEDED on a machine
    # whose only verified credential was bound to somebody else.
    uid = make_batch(fleet, editor='someone-else')
    mixed = dict(headers(editor='someone-else', token=CCE1),
                 **{'X-CCSync-Fleet-Auth': 'editor:jsmith'})

    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/claim',
                   json={'machine': MACHINE, 'companion_version': '0.9.0'},
                   headers=mixed)

    assert r.status_code == 403, r.text
    assert r.json()['detail']['reason'] == 'identity_mismatch'


def test_a_bound_token_carrying_its_own_editor_still_works(fleet, monkeypatch):
    monkeypatch.setattr(config, '_LOGIN_GATED', True, raising=False)
    uid = make_batch(fleet, editor='jsmith')
    matched = dict(headers(editor='jsmith', token=CCE1),
                   **{'X-CCSync-Fleet-Auth': 'editor:jsmith'})

    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/claim',
                   json={'machine': MACHINE, 'companion_version': '0.9.0'},
                   headers=matched)

    assert r.status_code == 200, r.text


def test_the_shared_migration_token_keeps_todays_behaviour(fleet):
    """It is bound to NOBODY - every companion in the fleet holds it - so
    there is nothing to compare and the ownership check below is still what
    refuses another editor's batch."""
    uid = make_batch(fleet, editor='jsmith')
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/claim',
                   json={'machine': MACHINE, 'companion_version': '0.9.0'},
                   headers=headers(editor='someone-else'))
    body = r.json()
    detail = body.get('detail')
    assert not (isinstance(detail, dict)
                and detail.get('reason') == 'identity_mismatch')
    assert r.status_code != 200, 'and it is still not this editor to claim'
