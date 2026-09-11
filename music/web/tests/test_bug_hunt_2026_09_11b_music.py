"""The second hunt of 2026-09-11: what the morning's music fixes left open.

Every test here fails at f1eeb42 and passes after the fix beside it. The ids
are the hunt's (`docs/bug-hunt-2026-09-11b/hunters/music.md`), and each one is
cited at its code site so `grep -rn music-1` finds both halves.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import sqlite3

from musicweb import config, db, fleet_auth, ingest_batches, rescore
from tests.test_fleet_ingest import (MACHINE, FakeEncoder, fleet,  # noqa: F401
                                     claim, fake_encoder, headers, make_batch,
                                     result_body)

EDITOR = {'X-CCSync-User': 'jsmith'}


def _fail_one_item_live(uid):
    """One failed track inside a batch a machine is STILL holding.

    Unlike `_fail_one_item` in the first hunt's file, the batch is left
    `running` with its lease intact: that is the state music-1 is about.
    """
    conn = db.con()
    item = conn.execute('SELECT uid FROM ingest_items WHERE batch_uid = ? '
                        'ORDER BY ord LIMIT 1', (uid,)).fetchone()
    conn.execute("UPDATE ingest_items SET state = 'failed', error = 'the library "
                 "would not take this track' WHERE uid = ?", (item['uid'],))
    conn.execute("UPDATE ingest_batches SET state = 'running', n_failed = 1 "
                 'WHERE uid = ?', (uid,))
    conn.commit()
    return item['uid']


# --------------------------------------------------------------------------
# music-1: retry-failed must not take a live batch away from its machine
# --------------------------------------------------------------------------

def test_a_batch_a_machine_is_still_holding_is_not_retried(fleet):
    uid = make_batch(fleet, names=('One.wav', 'Two.wav'))
    assert claim(fleet, uid).status_code == 200
    item_uid = _fail_one_item_live(uid)

    r = fleet.post(f'/api/ingest-batches/{uid}/retry-failed', headers=EDITOR)

    assert r.status_code == 409, r.text
    detail = r.json()['detail']
    assert detail['reason'] == 'held' and detail['machine'] == MACHINE
    conn = db.con()
    batch = conn.execute('SELECT state, lease_expires_at, machine FROM '
                         'ingest_batches WHERE uid = ?', (uid,)).fetchone()
    assert batch['state'] == 'running', 'possession was taken away'
    assert batch['lease_expires_at'], 'the leaseholder would be 410d on its next POST'
    item = conn.execute('SELECT state FROM ingest_items WHERE uid = ?',
                        (item_uid,)).fetchone()
    assert item['state'] == 'failed'


def test_a_batch_whose_lease_has_run_out_is_still_retryable(fleet):
    """The orphaned batch is what the button exists for: a machine that went
    away holds nothing, and the guard must not close that door."""
    uid = make_batch(fleet, names=('One.wav',))
    assert claim(fleet, uid).status_code == 200
    item_uid = _fail_one_item_live(uid)
    conn = db.con()
    conn.execute("UPDATE ingest_batches SET lease_expires_at = "
                 "'2026-09-10T00:00:00+00:00' WHERE uid = ?", (uid,))
    conn.commit()

    r = fleet.post(f'/api/ingest-batches/{uid}/retry-failed', headers=EDITOR)

    assert r.status_code == 200, r.text
    assert r.json()['items'] == [item_uid]


# --------------------------------------------------------------------------
# music-2 / music-3: the browser half
# --------------------------------------------------------------------------

def _ingest_js():
    return (Path(config.STATIC_DIR) / 'ingest.js').read_text(encoding='utf-8')


def _function(body, name):
    fn = body[body.index(f'async function {name}('):]
    cut = fn.index('\nasync function ')
    return fn[:cut]


def test_the_retry_button_is_drawn_only_on_the_editors_own_finished_batches():
    """music-2: ported without b-roll's two conditions, it sat next to
    `cancel` on a running batch and in the admin's `all machines` scope, which
    is the click that reaches music-1."""
    body = _ingest_js()
    render = body[body.index('function miRenderBatches('):]
    render = render[:render.index('\n/** Put a batch')]
    guard = re.search(r"if \(([^)]*batch\.n_failed > 0[^)]*)\)", render)
    assert guard, 'the retry button lost its guard entirely'
    condition = guard.group(1)
    assert 'MI_TERMINAL_STATES' in condition, (
        'drawn on a claimed/running batch, which is music-1 one click away')
    assert "mi.scope" in condition, (
        "drawn over another editor's machine in the admin scope")


def test_the_retry_dispatch_does_not_depend_on_what_this_page_remembers():
    """music-3: `mi.stagingId` lives in memory and dies with the page, so the
    normal case - come back after lunch, press the button - re-queued the
    batch and told the editor to press a Run button that makes a NEW batch.
    The companion's run() accepts an empty staging id: the items come back
    from the server's claim."""
    fn = _function(_ingest_js(), 'miRetryFailed')
    assert "'/music/ingest/retry'" in fn
    assert not re.search(r'if \([^)]*mi\.stagingId[^)]*\)\s*\{', fn), (
        'the dispatch is still behind "this page staged it"')
    assert 'mi.batchUid === uid' in fn, (
        'the staging id is still passed when this page does have it')


def test_a_queued_batch_can_be_taken_over_on_this_computer():
    """music-3's other half, b-roll's BROLL-8 button: without it a `queued`
    batch has nothing anywhere that can pick it up."""
    body = _ingest_js()
    assert 'miTakeOver' in body, 'no take-over control exists in the music SPA'
    fn = _function(body, 'miTakeOver')
    assert "'/music/ingest/run'" in fn
    render = body[body.index('function miRenderBatches('):]
    assert 'miTakeOver(' in render[:render.index('\n/** Put a batch')]


# --------------------------------------------------------------------------
# music-4 / regression-10: the readiness probe
# --------------------------------------------------------------------------

def _index(landed, unlanded=0):
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute('CREATE TABLE tracks (id INTEGER PRIMARY KEY, rel_path TEXT)')
    for i in range(1, landed + 1):
        con.execute('INSERT INTO tracks(id, rel_path) VALUES(?,?)',
                    (i, f'Old Cue {i}.wav'))
    for j in range(1, unlanded + 1):
        con.execute('INSERT INTO tracks(id, rel_path) VALUES(?,?)',
                    (landed + j, f'Dropping {j}.wav'))
    con.commit()
    return con


def test_a_mount_that_disappears_inside_the_cache_window_closes_the_gate(
        tmp_path, monkeypatch):
    """music-4: only the 50-stat sample may be cached. `share_root_ready` is
    the one thing between an unmounted bind mount and a write path that mints
    names and rows, and caching its whole answer left it open for 5 s after
    the mount went."""
    config.forget_ready_cache()
    root = tmp_path / 'music-share'
    root.mkdir()
    monkeypatch.setitem(config.SHARE_ROOTS, config.SHARE, root)
    con = _index(3)
    for i in range(1, 4):
        (root / f'Old Cue {i}.wav').write_bytes(b'x')
    assert config.share_root_ready(con)[0]

    for i in range(1, 4):
        (root / f'Old Cue {i}.wav').unlink()
    root.rmdir()

    ok, why = config.share_root_ready(con)
    config.forget_ready_cache()
    assert not ok and 'not mounted' in why


def test_a_live_drop_does_not_refuse_itself_once_fifty_rows_are_unlanded(
        tmp_path, monkeypatch):
    """regression-10: a fleet result writes the `tracks` row BEFORE the audio
    is uploaded, so from item ~51 of a big drop the newest fifty rel_paths are
    all files that are not there yet - and the probe blamed the mount."""
    config.forget_ready_cache()
    root = tmp_path / 'music-share'
    root.mkdir()
    monkeypatch.setitem(config.SHARE_ROOTS, config.SHARE, root)
    for i in range(1, 301):
        (root / f'Old Cue {i}.wav').write_bytes(b'x')

    ok, why = config.share_root_ready(_index(300, unlanded=50))

    config.forget_ready_cache()
    assert ok, why


# --------------------------------------------------------------------------
# music-5: a database that cannot answer must not raise out of the guard
# --------------------------------------------------------------------------

class _NoMeta:
    """A connection whose `meta` table cannot be read - a locked or malformed
    database, which is exactly what `_snapshot_token` claims to survive."""

    def execute(self, sql, *args):
        if 'meta' in sql:
            raise sqlite3.OperationalError('database is locked')
        return sqlite3.connect(':memory:').execute('SELECT NULL')


def test_a_database_that_cannot_answer_yields_a_token_not_an_exception():
    token = rescore._snapshot_token(_NoMeta())
    assert not isinstance(token, tuple)
    assert token != rescore._snapshot_token(_NoMeta()), (
        'a "cannot tell" token must never compare equal')


def test_a_result_whose_rescore_and_marker_both_fail_is_still_a_200(
        fleet, fake_encoder, monkeypatch):
    """The consequence: `write_item_result`'s own handler called
    `scores_stale` again and raised out of the except block, turning a
    degraded database into a 500 - which the companion reads as a permanent
    failure for that track."""
    uid = make_batch(fleet, names=('One.wav',))
    r = claim(fleet, uid)
    item_uid = r.json()['items'][0]['uid']

    def boom(*a, **kw):
        raise sqlite3.OperationalError('database is locked')

    monkeypatch.setattr(rescore, 'apply_for_track', boom)
    monkeypatch.setattr(rescore, 'scores_stale', boom)

    posted = fleet.post(
        f'/api/fleet/ingest/batches/{uid}/items/{item_uid}/result',
        json=result_body(), headers=headers())

    assert posted.status_code == 200, posted.text
    assert posted.json()['state'] == 'indexed'
    # The result landed a real track in the session-wide seeded database (and
    # `result` refreshed the process-wide search Index with it): take it out
    # again, the way test_fleet_ingest.py does, or every later test that
    # counts rows or searches the matrix sees a fifth track (gate 2026-09-11b:
    # test_db.py::test_load_matrix_shapes and test_search_filters went red).
    conn = db.con()
    conn.execute('DELETE FROM tracks WHERE id=?', (posted.json()['track_id'],))
    conn.commit()
    from musicweb import search
    search.refresh(conn)


# --------------------------------------------------------------------------
# music-6: an editor name with a space is still an editor
# --------------------------------------------------------------------------

@pytest.mark.parametrize('name', ['Jane Smith', 'a' * 80, 'jsmith'])
def test_a_stamp_the_mount_can_produce_is_parsed(monkeypatch, name):
    """The dashboard's MusicGate stamps `editor:{account name}` whatever that
    name is; refusing one here fell through to the SHARED token comparison,
    which a per-editor `cce1.` token cannot satisfy - so the editor was told
    their X-CCSync-Token was wrong."""
    monkeypatch.setattr(config, '_LOGIN_GATED', True, raising=False)
    assert fleet_auth.gate_stamp(f'editor:{name}') == ('editor', name)


@pytest.mark.parametrize('stamp', ['', 'editor:', 'editor:   ', 'admin',
                                   'shared please'])
def test_an_unparseable_stamp_is_still_not_a_credential(monkeypatch, stamp):
    monkeypatch.setattr(config, '_LOGIN_GATED', True, raising=False)
    assert fleet_auth.gate_stamp(stamp) == (None, None)


# --------------------------------------------------------------------------
# security-3: the gate stamp is believed on a CALL, never on the environment
# --------------------------------------------------------------------------

def test_an_environment_variable_does_not_make_this_app_login_gated():
    """The comment above the flag has always said so; the line under it read
    the variable anyway. b-roll and ytdl can only be told by their mount, and
    the stamp is the credential that SKIPS the fleet-token comparison."""
    env = dict(os.environ, MUSIC_LOGIN_GATED='1')
    out = subprocess.run(
        [sys.executable, '-c',
         'from musicweb import config; print(config.login_gated())'],
        cwd=str(Path(__file__).resolve().parents[1]), env=env,
        capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == 'False', out.stdout
