"""The session half of dashboard music ingest: /api/ingest-batches.

docs/MUSIC_INGEST_PLAN.md step 2. Every route's happy path and every refusal,
plus the two things that are easy to get wrong and impossible to see later: the
name allocation (two files called the same thing must not both be promised one
slot) and the duplicate defences (the re-encode one is the whole reason a
content hash is not enough).

Identity here is a HEADER, because in production it is one: the dashboard's
MusicGate stamps X-CCSync-User from the session and strips any inbound copy.
The tests send it directly, which is exactly what the sub-app sees.
"""
import sqlite3

import pytest

from musicweb import config, db, ingest_batches

EDITOR = {'X-CCSync-User': 'jsmith'}
OTHER = {'X-CCSync-User': 'rlee'}
ADMIN = {'X-CCSync-User': 'boss', 'X-CCSync-Admin': '1'}


def _item(name='New Cue.wav', **kw):
    out = {'local_id': name, 'name': name, 'size': 1024, 'duration': 60.0}
    out.update(kw)
    return out


@pytest.fixture()
def clean_batches(client):
    """No batches from another test. The database is session-scoped, and a
    list route that returned somebody else's row would pass or fail by
    ordering."""
    conn = db.con()
    conn.execute('DELETE FROM ingest_items')
    conn.execute('DELETE FROM ingest_batches')
    conn.commit()
    yield client
    conn.execute('DELETE FROM ingest_items')
    conn.execute('DELETE FROM ingest_batches')
    conn.commit()


# --- the gate -----------------------------------------------------------------

@pytest.mark.parametrize('method,path', [
    ('post', '/api/ingest-batches/precheck'),
    ('post', '/api/ingest-batches'),
    ('get', '/api/ingest-batches'),
    ('get', '/api/ingest-batches/limits'),
    ('get', '/api/ingest-batches/deadbeef'),
    ('post', '/api/ingest-batches/deadbeef/cancel'),
    ('post', '/api/ingest-batches/deadbeef/upload-paused'),
])
def test_every_route_refuses_a_request_with_no_identity(client, method, path):
    kwargs = {} if method == 'get' else {'json': {'items': [], 'paused': True}}
    r = getattr(client, method)(path, **kwargs)
    assert r.status_code == 401, path


def test_an_empty_identity_header_is_not_an_editor(client):
    """The gate WITHHOLDS the header for a name it cannot carry through a
    latin-1 round trip (YTDL-29). '' must not become a shared identity."""
    r = client.post('/api/ingest-batches', json={'items': [_item()]},
                    headers={'X-CCSync-User': '   '})
    assert r.status_code == 401


def test_scope_all_needs_an_admin(clean_batches):
    assert clean_batches.get('/api/ingest-batches?scope=all',
                             headers=EDITOR).status_code == 403
    r = clean_batches.get('/api/ingest-batches?scope=all', headers=ADMIN)
    assert r.status_code == 200 and r.json()['admin'] is True


def test_an_unknown_scope_is_refused(clean_batches):
    assert clean_batches.get('/api/ingest-batches?scope=everyone',
                             headers=EDITOR).status_code == 422


# --- create -------------------------------------------------------------------

def test_create_and_read_back_a_batch(clean_batches):
    r = clean_batches.post('/api/ingest-batches',
                           json={'items': [_item(), _item('Second.mp3')],
                                 'settings': {'run_mode': 'foreground'}},
                           headers=EDITOR)
    assert r.status_code == 200
    uid = r.json()['uid']
    assert len(uid) == 32 and int(uid, 16) >= 0      # the shape the regex pins

    got = clean_batches.get(f'/api/ingest-batches/{uid}', headers=EDITOR).json()
    assert got['batch']['state'] == 'queued'
    assert got['batch']['editor'] == 'jsmith'
    assert got['batch']['settings'] == {'run_mode': 'foreground'}
    assert [i['orig_name'] for i in got['items']] == ['New Cue.wav', 'Second.mp3']
    assert [i['state'] for i in got['items']] == ['pending', 'pending']
    # Nothing is in the library yet: a batch nobody claims must leave no trace
    # in `tracks` (which has no status column to hide behind).
    assert all(i['track_id'] is None and i['dest_name'] is None
               for i in got['items'])


def test_an_empty_batch_is_refused(clean_batches):
    r = clean_batches.post('/api/ingest-batches', json={'items': []},
                           headers=EDITOR)
    assert r.status_code == 422


def test_a_non_audio_file_is_named_not_silently_dropped(clean_batches):
    r = clean_batches.post('/api/ingest-batches',
                           json={'items': [_item(), _item('notes.txt')]},
                           headers=EDITOR)
    assert r.status_code == 422
    assert r.json()['detail']['reason'] == 'not_audio'
    assert r.json()['detail']['names'] == ['notes.txt']


def test_too_many_items_is_refused(clean_batches, monkeypatch):
    monkeypatch.setattr(config, 'MAX_BATCH_ITEMS', 2)
    r = clean_batches.post(
        '/api/ingest-batches',
        json={'items': [_item(f'{i}.wav') for i in range(3)]}, headers=EDITOR)
    assert r.status_code == 422
    assert 'at most 2' in r.json()['detail']


def test_an_unknown_run_mode_is_refused(clean_batches):
    r = clean_batches.post('/api/ingest-batches',
                           json={'items': [_item()],
                                 'settings': {'run_mode': 'whenever'}},
                           headers=EDITOR)
    assert r.status_code == 422


# --- precheck -----------------------------------------------------------------

def test_precheck_reserves_nothing(clean_batches):
    r = clean_batches.post('/api/ingest-batches/precheck',
                           json={'items': [_item('Preview.wav')]}, headers=EDITOR)
    assert r.status_code == 200
    assert r.json()['items'][0]['final_name'] == 'Preview.wav'
    conn = db.con()
    assert conn.execute('SELECT COUNT(*) c FROM ingest_items').fetchone()['c'] == 0
    # ... and asking twice gives the same answer, because nothing was taken
    again = clean_batches.post('/api/ingest-batches/precheck',
                               json={'items': [_item('Preview.wav')]},
                               headers=EDITOR)
    assert again.json()['items'][0]['final_name'] == 'Preview.wav'


def test_precheck_sees_a_reencode_that_hashing_cannot(clean_batches):
    """The seeded library holds 'ES_Tense Pulse.wav' at 120 s. A 320k mp3 of
    it has a different byte for byte, so only the normalised-stem + duration
    defence can catch it -- which is why db.find_reencode exists."""
    r = clean_batches.post(
        '/api/ingest-batches/precheck',
        json={'items': [_item('ES_Tense Pulse.mp3', duration=120.4,
                              content_hash='ffff')]},
        headers=EDITOR)
    row = r.json()['items'][0]
    assert row['duplicate_of'] == 1
    assert row['duplicate_name'] == 'ES_Tense Pulse.wav'


@pytest.fixture()
def unique_library_track():
    """A library file whose bytes nothing else in the fixture shares.

    The seeded tracks all hold the SAME bytes (the fixture writes one
    constant into every file), so a content-hash test against one of them
    would pass on any of the four and prove nothing about which row was
    matched."""
    conn = db.con()
    name = 'Unique Content.wav'
    path = config.share_root() / name
    path.write_bytes(b'unique-bytes-for-the-content-hash-test' * 7)
    conn.execute('INSERT INTO tracks(id, rel_path, filename, ext, bytes, '
                 'duration) VALUES(?,?,?,?,?,?)',
                 (900, name, name, '.wav', path.stat().st_size, 33.0))
    conn.commit()
    yield name, db.content_hash(path), path.stat().st_size
    conn.execute('DELETE FROM tracks WHERE id = 900')
    conn.commit()
    path.unlink(missing_ok=True)


def test_precheck_sees_byte_identical_content_under_another_name(
        clean_batches, unique_library_track):
    """The other defence: same bytes, unrelated name, no duration match. The
    digest is computed where the file is (the editor's machine) and checked
    against library rows whose byte count already agrees."""
    name, digest, size = unique_library_track
    r = clean_batches.post(
        '/api/ingest-batches/precheck',
        json={'items': [_item('completely-different.wav', duration=999.0,
                              size=size, content_hash=digest)]},
        headers=EDITOR)
    row = r.json()['items'][0]
    assert row['duplicate_name'] == name
    assert row['duplicate_of'] == 900


def test_a_clean_file_is_not_a_duplicate(clean_batches):
    r = clean_batches.post(
        '/api/ingest-batches/precheck',
        json={'items': [_item('Nothing Like It.wav', duration=17.0,
                              content_hash='0' * 32)]},
        headers=EDITOR)
    assert r.json()['items'][0]['duplicate_of'] is None


def test_precheck_reports_an_unsupported_extension(clean_batches):
    r = clean_batches.post('/api/ingest-batches/precheck',
                           json={'items': [_item('cover.jpg')]}, headers=EDITOR)
    assert r.json()['items'][0]['unsupported'] is True


# --- names --------------------------------------------------------------------

def test_two_files_of_one_drop_do_not_get_the_same_name(clean_batches):
    """Both would be `theme.wav` on disk, and the second upload would land on
    the first. build_archive's BROLL-IDX-5 lesson, one library over."""
    r = clean_batches.post(
        '/api/ingest-batches/precheck',
        json={'items': [_item('theme.wav'), _item('theme.wav')]}, headers=EDITOR)
    names = [i['final_name'] for i in r.json()['items']]
    assert names == ['theme.wav', 'theme (2).wav']


def test_a_name_the_library_already_holds_is_stepped_around(clean_batches):
    r = clean_batches.post('/api/ingest-batches/precheck',
                           json={'items': [_item('Winter Rain.flac')]},
                           headers=EDITOR)
    assert r.json()['items'][0]['final_name'] == 'Winter Rain (2).flac'


def test_an_ogg_is_named_as_the_mp3_it_will_become(clean_batches):
    r = clean_batches.post('/api/ingest-batches/precheck',
                           json={'items': [_item('Podcast Bed.ogg')]},
                           headers=EDITOR)
    assert r.json()['items'][0]['final_name'] == 'Podcast Bed.mp3'


def test_a_dropped_name_that_looks_like_a_path_cannot_escape():
    conn = db.con()
    name = ingest_batches.allocate_name(conn, '../../../etc/passwd.wav')
    assert '/' not in name and '\\' not in name and '..' not in name


# --- visibility ---------------------------------------------------------------

def test_another_editors_batch_is_404_not_403(clean_batches):
    uid = clean_batches.post('/api/ingest-batches', json={'items': [_item()]},
                             headers=EDITOR).json()['uid']
    assert clean_batches.get(f'/api/ingest-batches/{uid}',
                             headers=OTHER).status_code == 404
    assert clean_batches.post(f'/api/ingest-batches/{uid}/cancel',
                              headers=OTHER).status_code == 404
    # ... and an admin sees it
    assert clean_batches.get(f'/api/ingest-batches/{uid}',
                             headers=ADMIN).status_code == 200


def test_mine_lists_only_mine(clean_batches):
    clean_batches.post('/api/ingest-batches', json={'items': [_item('a.wav')]},
                       headers=EDITOR)
    clean_batches.post('/api/ingest-batches', json={'items': [_item('b.wav')]},
                       headers=OTHER)
    mine = clean_batches.get('/api/ingest-batches', headers=EDITOR).json()
    assert [b['editor'] for b in mine['batches']] == ['jsmith']
    every = clean_batches.get('/api/ingest-batches?scope=all', headers=ADMIN).json()
    assert sorted(b['editor'] for b in every['batches']) == ['jsmith', 'rlee']


# --- cancel / pause -----------------------------------------------------------

def test_cancel_is_a_request_and_takes_the_lease_away(clean_batches):
    uid = clean_batches.post('/api/ingest-batches', json={'items': [_item()]},
                             headers=EDITOR).json()['uid']
    conn = db.con()
    conn.execute("UPDATE ingest_batches SET state='running', machine='rig', "
                 "lease_expires_at='2099-01-01T00:00:00+00:00' WHERE uid=?", (uid,))
    conn.commit()

    r = clean_batches.post(f'/api/ingest-batches/{uid}/cancel', headers=EDITOR)
    assert r.status_code == 200 and r.json()['cancel_requested'] is True
    row = ingest_batches.get_batch(conn, uid)
    # a REQUEST: the state is untouched, so a companion mid-track is not
    # crunching a batch the server has already forgotten
    assert row['state'] == 'running'
    assert row['cancel_requested'] == 1
    assert row['lease_expires_at'] is None
    assert row['cancel_by'] == 'jsmith'


def test_cancelling_a_finished_batch_is_idempotent(clean_batches):
    uid = clean_batches.post('/api/ingest-batches', json={'items': [_item()]},
                             headers=EDITOR).json()['uid']
    conn = db.con()
    conn.execute("UPDATE ingest_batches SET state='done' WHERE uid=?", (uid,))
    conn.commit()
    r = clean_batches.post(f'/api/ingest-batches/{uid}/cancel', headers=EDITOR)
    assert r.status_code == 200 and r.json()['already_finished'] is True


def test_upload_paused_toggles(clean_batches):
    uid = clean_batches.post('/api/ingest-batches', json={'items': [_item()]},
                             headers=EDITOR).json()['uid']
    clean_batches.post(f'/api/ingest-batches/{uid}/upload-paused',
                       json={'paused': True}, headers=EDITOR)
    assert clean_batches.get(f'/api/ingest-batches/{uid}',
                             headers=EDITOR).json()['batch']['upload_paused'] is True
    clean_batches.post(f'/api/ingest-batches/{uid}/upload-paused',
                       json={'paused': False}, headers=EDITOR)
    assert clean_batches.get(f'/api/ingest-batches/{uid}',
                             headers=EDITOR).json()['batch']['upload_paused'] is False


# --- limits -------------------------------------------------------------------

def test_limits_names_what_the_server_enforces(clean_batches):
    got = clean_batches.get('/api/ingest-batches/limits', headers=EDITOR).json()
    assert got['max_items'] == config.MAX_BATCH_ITEMS
    assert '.wav' in got['audio_exts'] and '.ogg' in got['transcode_exts']
    assert got['run_modes'] == ['idle', 'foreground']


# --- leases -------------------------------------------------------------------

def test_listing_hands_back_a_batch_whose_machine_went_quiet(clean_batches):
    """There is no timer in this app: the list is what notices."""
    uid = clean_batches.post('/api/ingest-batches', json={'items': [_item()]},
                             headers=EDITOR).json()['uid']
    conn = db.con()
    conn.execute("UPDATE ingest_batches SET state='running', machine='rig', "
                 "lease_expires_at='2000-01-01T00:00:00+00:00' WHERE uid=?", (uid,))
    conn.commit()
    listed = clean_batches.get('/api/ingest-batches', headers=EDITOR).json()
    batch = [b for b in listed['batches'] if b['uid'] == uid][0]
    assert batch['state'] == 'queued'
    assert batch['lease_expires_at'] is None
    # the machine name STAYS, so the SPA can still say "waiting for rig"
    assert batch['machine'] == 'rig'


def test_a_live_lease_is_left_alone(clean_batches):
    uid = clean_batches.post('/api/ingest-batches', json={'items': [_item()]},
                             headers=EDITOR).json()['uid']
    conn = db.con()
    conn.execute("UPDATE ingest_batches SET state='running', machine='rig', "
                 "lease_expires_at='2099-01-01T00:00:00+00:00' WHERE uid=?", (uid,))
    conn.commit()
    clean_batches.get('/api/ingest-batches', headers=EDITOR)
    assert ingest_batches.get_batch(conn, uid)['state'] == 'running'


# --- the ledger's own rules ---------------------------------------------------

def test_the_item_state_machine_is_monotonic_except_for_a_retry():
    check = ingest_batches._check_transition
    check('pending', 'transcoding')
    check('embedding', 'indexed')
    check('indexed', 'indexed')                  # re-posting progress
    check('failed', 'embedding')                 # the one way back
    for old, new in (('indexed', 'embedding'), ('live', 'uploading'),
                     ('cancelled', 'embedding'), ('duplicate', 'indexed')):
        with pytest.raises(Exception) as exc:
            check(old, new)
        assert exc.value.status_code == 400
    with pytest.raises(Exception) as exc:
        check('pending', 'teleporting')
    assert exc.value.status_code == 400


def test_deleting_a_batch_takes_its_items_with_it():
    """ON DELETE CASCADE, which needs PRAGMA foreign_keys -- db.connect sets
    it, and a ledger of orphan items is a ledger nothing can recount."""
    conn = db.con()
    uid = ingest_batches.new_uid(conn)
    conn.execute("INSERT INTO ingest_batches(uid, editor, settings_json, "
                 "created_at) VALUES(?,?,'{}',?)",
                 (uid, 'jsmith', ingest_batches.now_iso()))
    conn.execute("INSERT INTO ingest_items(uid, batch_uid, ord, orig_name, "
                 "source, updated_at) VALUES(?,?,0,'x.wav','upload',?)",
                 (ingest_batches.new_uid(conn), uid, ingest_batches.now_iso()))
    conn.commit()
    conn.execute('DELETE FROM ingest_batches WHERE uid=?', (uid,))
    conn.commit()
    assert conn.execute('SELECT COUNT(*) c FROM ingest_items WHERE batch_uid=?',
                        (uid,)).fetchone()['c'] == 0


def test_the_item_state_check_constraint_is_the_state_list():
    """The CHECK in the migration and ITEM_STATES must not drift: a state the
    code can write and the table refuses is a 500 in a fleet call."""
    conn = db.con()
    uid = ingest_batches.new_uid(conn)
    conn.execute("INSERT INTO ingest_batches(uid, editor, settings_json, "
                 "created_at) VALUES(?,?,'{}',?)",
                 (uid, 'jsmith', ingest_batches.now_iso()))
    for state in ingest_batches.ITEM_STATES:
        conn.execute(
            'INSERT INTO ingest_items(uid, batch_uid, ord, orig_name, source, '
            'state, updated_at) VALUES(?,?,0,?,?,?,?)',
            (ingest_batches.new_uid(conn), uid, 'x.wav', 'upload', state,
             ingest_batches.now_iso()))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            'INSERT INTO ingest_items(uid, batch_uid, ord, orig_name, source, '
            'state, updated_at) VALUES(?,?,0,?,?,?,?)',
            (ingest_batches.new_uid(conn), uid, 'x.wav', 'upload', 'nonsense',
             ingest_batches.now_iso()))
    conn.execute('DELETE FROM ingest_batches WHERE uid=?', (uid,))
    conn.commit()
