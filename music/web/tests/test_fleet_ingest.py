"""The companion half of dashboard music ingest: /api/fleet/ingest/...

docs/MUSIC_INGEST_PLAN.md step 2. These calls carry no session -- the fleet
token plus a SIGNED identity is the whole credential -- so the tests here are
mostly about refusals: an unconfigured token, a forged identity, a lost lease,
another machine, an illegal transition, an upload that did not land.

The one long happy path (`test_a_result_creates_a_searchable_tagged_track`) is
the point of the whole feature: an embedding computed on an editor's machine
becomes a track row with tags and axes, scored by the CLAP TEXT tower this
container already runs, with no torch anywhere.
"""
import base64

import numpy as np
import pytest

from musicweb import config, db, identity, ingest_batches, rescore, search

SECRET = 's' * 40
TOKEN = 'fleet-token-for-the-music-tests-0123456789'
MACHINE = 'EDIT-RIG-1'
DIM = 8                                       # tests/conftest.py's library width


@pytest.fixture()
def fleet(client, monkeypatch):
    """A configured fleet posture: a token, a session secret, and headers that
    carry a REAL signed identity (the verifier is the vendored one, so a hand
    written token would not do)."""
    monkeypatch.setenv('DASH_REPORT_TOKEN', TOKEN)
    monkeypatch.setenv('DASH_SESSION_SECRET', SECRET)
    conn = db.con()
    conn.execute('DELETE FROM ingest_items')
    conn.execute('DELETE FROM ingest_batches')
    conn.commit()
    yield client
    conn.execute('DELETE FROM ingest_items')
    conn.execute('DELETE FROM ingest_batches')
    conn.commit()
    # The search Index is a PROCESS-wide singleton and `result` refreshes it
    # (that is the feature -- a new track has to be findable). A test that
    # added a track and then deleted its row would otherwise leave the next
    # test searching a matrix with a row the database no longer has, which is
    # MUSIC-10's shape in miniature.
    search.refresh(conn)


def headers(editor='jsmith', machine=MACHINE, token=TOKEN):
    out = {'X-CCSync-Token': token,
           'X-CCSync-Identity': identity.make_identity_token(SECRET, editor)}
    if machine:
        out['X-CCSync-Machine'] = machine
    return out


def make_batch(client, editor='jsmith', names=('Fleet Cue.wav',)):
    r = client.post('/api/ingest-batches',
                    json={'items': [{'local_id': n, 'name': n, 'size': 2048,
                                     'duration': 42.0} for n in names]},
                    headers={'X-CCSync-User': editor})
    assert r.status_code == 200, r.text
    return r.json()['uid']


def claim(client, uid, editor='jsmith', machine=MACHINE):
    return client.post(f'/api/fleet/ingest/batches/{uid}/claim',
                       json={'machine': machine, 'companion_version': '0.9.0'},
                       headers=headers(editor, machine))


def _b64(vec):
    return base64.b64encode(np.asarray(vec, dtype='<f4').tobytes()).decode()


def result_body(seed=7, **kw):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=DIM).astype(np.float32)
    body = {
        'embedding': _b64(v / np.linalg.norm(v)),
        'dim': DIM,
        'model': 'laion/larger_clap_music_and_speech',
        'duration': 42.0,
        'size_bytes': 2048,
        'content_hash': 'abc123',
        'bpm': 96.0,
        'music_key': 'F minor',
        'peaks': base64.b64encode(bytes([0, 90, 200, 30])).decode(),
        'probe': {'samplerate': 48000, 'channels': 2, 'codec': 'pcm_s16le'},
        'windows': [{'idx': 0, 't0': 0.0, 't1': 10.0, 'vector': _b64(v)}],
    }
    body.update(kw)
    return body


class FakeEncoder:
    """`embed_text` and nothing else -- the one method rescore needs, which is
    the whole reason the ONNX tower and the full CLAP are interchangeable."""

    def embed_text(self, texts):
        out = []
        for t in texts:
            rng = np.random.default_rng(abs(hash(t)) % (2 ** 32))
            v = rng.normal(size=DIM).astype(np.float32)
            out.append(v / np.linalg.norm(v))
        return np.stack(out)


@pytest.fixture()
def fake_encoder(monkeypatch):
    """No torch and no 500 MB artefact in this suite: rescore is handed a
    deterministic stand-in. It exercises every line of the real path except
    what the vectors mean."""
    enc = FakeEncoder()
    monkeypatch.setattr(search, 'shared_encoder', lambda: enc)
    monkeypatch.setattr(rescore, '_label_space', None, raising=False)
    monkeypatch.setattr(rescore, '_label_space_key', None, raising=False)
    return enc


# --- the credentials ----------------------------------------------------------

def test_an_unconfigured_fleet_token_refuses_everything(fleet, monkeypatch):
    """FAIL CLOSED. What is behind these routes is INSERT INTO tracks."""
    monkeypatch.delenv('DASH_REPORT_TOKEN', raising=False)
    uid = make_batch(fleet)
    r = claim(fleet, uid)
    assert r.status_code == 403
    assert 'X-CCSync-Token' in r.json()['detail']


def test_a_wrong_token_is_refused(fleet):
    uid = make_batch(fleet)
    bad = dict(headers(), **{'X-CCSync-Token': 'not-the-fleet-token'})
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/claim',
                   json={'machine': MACHINE}, headers=bad)
    assert r.status_code == 403


def test_a_per_editor_token_the_mount_verified_is_accepted(fleet, monkeypatch):
    """music-1, 2026-08-21. The companion PREFERS the per-editor `cce1.` token
    an admin minted for that editor (identity.preferred_report_token,
    2026-08-17), and this app cannot verify one -- that needs the dashboard's
    database. Mounted, the gate resolves it and says so; without accepting that
    stamp, every migrated editor's dropped album sat in `queued` forever."""
    monkeypatch.setattr(config, '_LOGIN_GATED', True, raising=False)
    uid = make_batch(fleet)
    cce1 = dict(headers(token='cce1.0123456789abcdef.' + 's' * 43),
                **{'X-CCSync-Fleet-Auth': 'editor:jsmith'})
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/claim',
                   json={'machine': MACHINE, 'companion_version': '0.9.0'},
                   headers=cce1)
    assert r.status_code == 200, r.text


def test_a_fleet_auth_stamp_is_worthless_standalone(fleet, monkeypatch):
    """Standalone there is no gate stripping inbound copies of it, so the
    header on the wire proves nothing and the shared secret is the only
    credential (music-1, 2026-08-21)."""
    monkeypatch.setattr(config, '_LOGIN_GATED', False, raising=False)
    uid = make_batch(fleet)
    forged = dict(headers(token='cce1.0123456789abcdef.' + 's' * 43),
                  **{'X-CCSync-Fleet-Auth': 'editor:jsmith'})
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/claim',
                   json={'machine': MACHINE}, headers=forged)
    assert r.status_code == 403


@pytest.mark.parametrize('stamp', ['', 'editor:', 'admin', 'shared please',
                                   'editor:' + 'x' * 80])
def test_a_stamp_of_the_wrong_shape_is_not_a_credential(fleet, monkeypatch, stamp):
    monkeypatch.setattr(config, '_LOGIN_GATED', True, raising=False)
    uid = make_batch(fleet)
    bad = dict(headers(token='cce1.0123456789abcdef.' + 's' * 43),
               **{'X-CCSync-Fleet-Auth': stamp})
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/claim',
                   json={'machine': MACHINE}, headers=bad)
    assert r.status_code == 403


def test_the_token_alone_is_not_an_identity(fleet):
    """H5: every companion in the fleet holds the same token, so it proves
    "a fleet machine" and nothing about which editor."""
    uid = make_batch(fleet)
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/claim',
                   json={'machine': MACHINE},
                   headers={'X-CCSync-Token': TOKEN})
    assert r.status_code == 403
    assert r.json()['detail']['reason'] == 'identity'


def test_a_forged_identity_is_refused(fleet):
    uid = make_batch(fleet)
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/claim',
                   json={'machine': MACHINE},
                   headers={'X-CCSync-Token': TOKEN,
                            'X-CCSync-Identity': 'v1.jsmith.9999999999.deadbeef'})
    assert r.status_code == 403


def test_no_session_secret_means_no_identity_can_be_verified(fleet, monkeypatch):
    monkeypatch.delenv('DASH_SESSION_SECRET', raising=False)
    uid = make_batch(fleet)
    r = claim(fleet, uid)
    assert r.status_code == 403
    assert r.json()['detail']['reason'] == 'identity_unconfigured'


def test_another_editors_batch_cannot_be_claimed(fleet):
    """403, not 410: this one really is "wrong credentials"."""
    uid = make_batch(fleet, editor='jsmith')
    r = claim(fleet, uid, editor='rlee')
    assert r.status_code == 403
    assert r.json()['detail']['reason'] == 'identity'


# --- claim / lease ------------------------------------------------------------

def test_claim_hands_back_the_work_order_and_mints_no_tracks(fleet):
    before = db.con().execute('SELECT COUNT(*) c FROM tracks').fetchone()['c']
    uid = make_batch(fleet, names=('One.wav', 'Two.mp3'))
    r = claim(fleet, uid)
    assert r.status_code == 200
    got = r.json()
    assert got['batch']['state'] == 'claimed'
    assert got['batch']['machine'] == MACHINE
    assert got['lease_seconds'] == config.LEASE_SECONDS
    assert got['heartbeat_seconds'] == config.HEARTBEAT_SECONDS
    # A remote-relative path, never a local one: only the companion knows what
    # its rclone remote is mounted as.
    assert got['library_remote_rel'] == 'Assets/Music'
    assert [i['orig_name'] for i in got['items']] == ['One.wav', 'Two.mp3']
    assert all(i['track_id'] is None for i in got['items'])
    after = db.con().execute('SELECT COUNT(*) c FROM tracks').fetchone()['c']
    assert after == before


def test_claim_is_idempotent_for_the_same_machine(fleet):
    uid = make_batch(fleet)
    first = claim(fleet, uid).json()
    second = claim(fleet, uid).json()
    assert [i['uid'] for i in first['items']] == [i['uid'] for i in second['items']]
    assert second['batch']['state'] == 'claimed'


def test_a_second_machine_is_refused_while_the_lease_is_live(fleet):
    uid = make_batch(fleet)
    claim(fleet, uid)
    r = claim(fleet, uid, machine='LAPTOP-2')
    assert r.status_code == 409
    assert r.json()['detail']['machine'] == MACHINE


def test_a_second_machine_may_claim_once_the_lease_has_expired(fleet):
    uid = make_batch(fleet)
    claim(fleet, uid)
    conn = db.con()
    conn.execute("UPDATE ingest_batches SET lease_expires_at="
                 "'2000-01-01T00:00:00+00:00' WHERE uid=?", (uid,))
    conn.commit()
    assert claim(fleet, uid, machine='LAPTOP-2').status_code == 200


def test_a_cancelled_batch_answers_410_to_a_claim(fleet):
    uid = make_batch(fleet)
    fleet.post(f'/api/ingest-batches/{uid}/cancel',
               headers={'X-CCSync-User': 'jsmith'})
    r = claim(fleet, uid)
    assert r.status_code == 410 and r.json()['detail']['reason'] == 'cancelled'


def test_heartbeat_extends_the_lease_and_reports_the_flags(fleet):
    uid = make_batch(fleet)
    claim(fleet, uid)
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/heartbeat', json={},
                   headers=headers())
    assert r.status_code == 200
    assert r.json()['cancel_requested'] is False
    fleet.post(f'/api/ingest-batches/{uid}/upload-paused', json={'paused': True},
               headers={'X-CCSync-User': 'jsmith'})
    assert fleet.post(f'/api/fleet/ingest/batches/{uid}/heartbeat', json={},
                      headers=headers()).json()['upload_paused'] is True


@pytest.mark.parametrize('setup,reason', [
    ('expire', 'lease_expired'),
    ('cancel', 'cancelled'),
    ('finish', 'finished'),
    ('other_machine', 'other_machine'),
])
def test_every_way_a_claim_can_end_answers_410(fleet, setup, reason):
    """One answer to all of them: stop quietly. A 403 would read as "fix your
    credentials" and be retried forever."""
    uid = make_batch(fleet)
    claim(fleet, uid)
    conn = db.con()
    if setup == 'expire':
        conn.execute("UPDATE ingest_batches SET lease_expires_at="
                     "'2000-01-01T00:00:00+00:00' WHERE uid=?", (uid,))
    elif setup == 'cancel':
        conn.execute('UPDATE ingest_batches SET cancel_requested=1 WHERE uid=?',
                     (uid,))
    elif setup == 'finish':
        conn.execute("UPDATE ingest_batches SET state='done' WHERE uid=?", (uid,))
    else:
        conn.execute("UPDATE ingest_batches SET machine='SOMEONE-ELSE' "
                     'WHERE uid=?', (uid,))
    conn.commit()
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/heartbeat', json={},
                   headers=headers())
    assert r.status_code == 410
    assert r.json()['detail']['reason'] == reason


# --- checkpoints --------------------------------------------------------------

def test_a_checkpoint_moves_the_item_and_the_batch(fleet):
    uid = make_batch(fleet)
    item = claim(fleet, uid).json()['items'][0]['uid']
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/status',
                   json={'state': 'embedding', 'stage_percent': 40,
                         'probe': {'samplerate': 44100, 'codec': 'flac'}},
                   headers=headers())
    assert r.status_code == 200 and r.json()['state'] == 'embedding'
    conn = db.con()
    assert ingest_batches.get_batch(conn, uid)['state'] == 'running'
    row = ingest_batches.get_item(conn, uid, item)
    assert row['stage_percent'] == 40 and row['samplerate'] == 44100


def test_going_backwards_is_refused(fleet):
    uid = make_batch(fleet)
    item = claim(fleet, uid).json()['items'][0]['uid']
    fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/status',
               json={'state': 'embedding'}, headers=headers())
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/status',
                   json={'state': 'transcoding'}, headers=headers())
    assert r.status_code == 400
    assert r.json()['detail']['reason'] == 'illegal_transition'


def test_the_base_rig_fallback_is_a_terminal_item_state(fleet):
    """A companion with no CLAP sidecar uploads and leaves the analysis to a
    base-rig drain -- the plan's kept fallback, and the ledger says so rather
    than calling it a failure."""
    uid = make_batch(fleet)
    item = claim(fleet, uid).json()['items'][0]['uid']
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/status',
                   json={'state': 'queued_for_base_rig'}, headers=headers())
    assert r.status_code == 200
    assert r.json()['n_done'] == 1 and r.json()['n_failed'] == 0


# --- the result ---------------------------------------------------------------

def test_a_result_creates_a_searchable_tagged_track(fleet, fake_encoder):
    uid = make_batch(fleet, names=('Fleet Cue.wav',))
    item = claim(fleet, uid).json()['items'][0]['uid']
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/result',
                   json=result_body(), headers=headers())
    assert r.status_code == 200, r.text
    got = r.json()
    assert got['state'] == 'indexed'
    assert got['rel_path'] == 'Fleet Cue.wav'
    track_id = got['track_id']

    conn = db.con()
    row = conn.execute('SELECT * FROM tracks WHERE id=?', (track_id,)).fetchone()
    assert row['rel_path'] == 'Fleet Cue.wav'
    assert row['duration'] == 42.0 and row['bpm'] == 96.0
    assert row['samplerate'] == 48000 and row['codec'] == 'pcm_s16le'
    assert row['dim'] == DIM
    # stored unit-length, whatever arrived
    vec = np.frombuffer(row['embedding'], dtype=np.float32)
    assert np.isclose(np.linalg.norm(vec), 1.0)
    assert conn.execute('SELECT COUNT(*) c FROM windows WHERE track_id=?',
                        (track_id,)).fetchone()['c'] == 1
    assert conn.execute('SELECT n FROM peaks WHERE track_id=?',
                        (track_id,)).fetchone()['n'] == 4

    # and it is TAGGED -- the whole point: the audio tower ran on the editor's
    # machine, the text tower scored it here.
    tags = conn.execute('SELECT category, label FROM tags WHERE track_id=?',
                        (track_id,)).fetchall()
    assert {t['category'] for t in tags} == set(config.CATEGORY_ORDER)
    axes = conn.execute('SELECT axis FROM axes WHERE track_id=?',
                        (track_id,)).fetchall()
    assert {a['axis'] for a in axes} == set(config.AXIS_ORDER)
    assert got['scores']['tracks'] >= 1

    # ... and the in-process search index knows about it
    assert track_id in search.index().pos

    conn.execute('DELETE FROM tracks WHERE id=?', (track_id,))
    conn.commit()


def test_a_result_is_refused_if_the_embedding_is_the_wrong_width(fleet, fake_encoder):
    """An embedding of another width is another MODEL's, and two models in one
    index makes every cosine in it meaningless."""
    uid = make_batch(fleet)
    item = claim(fleet, uid).json()['items'][0]['uid']
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/result',
                   json=result_body(embedding=_b64(np.ones(512, dtype=np.float32)),
                                    dim=512),
                   headers=headers())
    assert r.status_code == 409
    assert r.json()['detail']['reason'] == 'model_mismatch'
    assert r.json()['detail']['expected_dim'] == DIM


@pytest.mark.parametrize('payload,reason', [
    ({'embedding': ''}, 'embedding'),
    ({'embedding': 'not base64!!'}, 'encoding'),
    ({'embedding': _b64(np.zeros(DIM, dtype=np.float32))}, 'embedding'),
])
def test_a_broken_embedding_is_a_422_not_a_500(fleet, fake_encoder, payload, reason):
    uid = make_batch(fleet)
    item = claim(fleet, uid).json()['items'][0]['uid']
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/result',
                   json=result_body(**payload), headers=headers())
    assert r.status_code == 422
    assert r.json()['detail']['reason'] == reason


def test_a_second_result_updates_the_same_track(fleet, fake_encoder):
    """A retry after a lost response must not allocate a second name for the
    same audio."""
    uid = make_batch(fleet)
    item = claim(fleet, uid).json()['items'][0]['uid']
    first = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/result',
                       json=result_body(), headers=headers()).json()
    second = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/result',
                        json=result_body(seed=9), headers=headers()).json()
    assert second['track_id'] == first['track_id']
    assert second['rel_path'] == first['rel_path']
    conn = db.con()
    conn.execute('DELETE FROM tracks WHERE id=?', (first['track_id'],))
    conn.commit()


def test_a_name_the_library_holds_is_stepped_around_at_result(fleet, fake_encoder):
    uid = make_batch(fleet, names=('Winter Rain.flac',))
    item = claim(fleet, uid).json()['items'][0]['uid']
    got = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/result',
                     json=result_body(), headers=headers()).json()
    assert got['rel_path'] == 'Winter Rain (2).flac'
    conn = db.con()
    conn.execute('DELETE FROM tracks WHERE id=?', (got['track_id'],))
    conn.commit()


# --- uploaded -----------------------------------------------------------------

def test_uploaded_refuses_until_the_file_is_really_there(fleet, fake_encoder):
    uid = make_batch(fleet)
    item = claim(fleet, uid).json()['items'][0]['uid']
    got = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/result',
                     json=result_body(), headers=headers()).json()
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/uploaded',
                   json={'size': 2048}, headers=headers())
    assert r.status_code == 409
    assert r.json()['detail']['reason'] == 'not_uploaded'

    path = config.share_root() / got['rel_path']
    path.write_bytes(b'x' * 2048)
    try:
        # a size that disagrees is also a refusal: the bytes on the NAS are
        # the answer, not the companion's claim about them
        bad = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/uploaded',
                         json={'size': 99}, headers=headers())
        assert bad.status_code == 409
        assert bad.json()['detail']['reason'] == 'size_mismatch'

        ok = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/uploaded',
                        json={'size': 2048}, headers=headers())
        assert ok.status_code == 200
        assert ok.json()['live'] is True and ok.json()['n_live'] == 1
        conn = db.con()
        assert conn.execute('SELECT bytes FROM tracks WHERE id=?',
                            (got['track_id'],)).fetchone()['bytes'] == 2048
    finally:
        path.unlink(missing_ok=True)
        conn = db.con()
        conn.execute('DELETE FROM tracks WHERE id=?', (got['track_id'],))
        conn.commit()


def test_uploaded_before_a_result_is_refused(fleet):
    uid = make_batch(fleet)
    item = claim(fleet, uid).json()['items'][0]['uid']
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/uploaded',
                   json={'size': 1}, headers=headers())
    assert r.status_code == 409
    assert r.json()['detail']['reason'] == 'unindexed'


# --- release ------------------------------------------------------------------

def test_release_calls_a_batch_with_failures_done_with_errors(fleet):
    uid = make_batch(fleet, names=('a.wav', 'b.wav'))
    items = [i['uid'] for i in claim(fleet, uid).json()['items']]
    fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{items[0]}/status',
               json={'state': 'failed', 'error': 'no decodable audio'},
               headers=headers())
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/release',
                   json={'state': 'done', 'summary': 'one bad file'},
                   headers=headers())
    assert r.status_code == 200
    assert r.json()['state'] == 'done_with_errors'
    batch = ingest_batches.get_batch(db.con(), uid)
    assert batch['lease_expires_at'] is None
    assert batch['error'] == 'one bad file'


def test_a_cancelled_release_is_accepted_without_a_lease(fleet):
    """Cancelling is exactly the case where the dashboard has already expired
    the lease; refusing the release would strand the batch in `running`."""
    uid = make_batch(fleet)
    claim(fleet, uid)
    fleet.post(f'/api/ingest-batches/{uid}/cancel',
               headers={'X-CCSync-User': 'jsmith'})
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/release',
                   json={'state': 'cancelled'}, headers=headers())
    assert r.status_code == 200 and r.json()['state'] == 'cancelled'
    items = ingest_batches.list_items(db.con(), uid)
    assert all(i['state'] == 'cancelled' for i in items)


def test_a_release_of_someone_elses_batch_is_refused(fleet):
    uid = make_batch(fleet, editor='jsmith')
    claim(fleet, uid)
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/release',
                   json={'state': 'cancelled'}, headers=headers(editor='rlee'))
    assert r.status_code == 410


def test_a_track_created_at_a_reused_id_does_not_inherit_a_proxy(fleet, fake_encoder):
    """music-4, 2026-08-21. `tracks.id` is INTEGER PRIMARY KEY without
    AUTOINCREMENT, so a created row takes max(rowid)+1 -- the id of the highest
    track ever deleted -- and the 128k preview proxy is chosen on existence
    alone. Since 2026-08-18 rows are created HERE, on the host that holds the
    proxies, so every editor previewing the new cue heard the deleted one while
    the waveform, the tags, `?original=1` and Resolve were all correct."""
    conn = db.con()
    next_id = (conn.execute('SELECT MAX(id) m FROM tracks').fetchone()['m'] or 0) + 1
    config.ensure_proxies_dir()
    stale = config.proxy_path(next_id)
    stale.write_bytes(b'ID3\x03\x00\x00\x00' + b'the deleted cue')

    uid = make_batch(fleet, names=('Reused Id.wav',))
    item = claim(fleet, uid).json()['items'][0]['uid']
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/result',
                   json=result_body(), headers=headers())
    assert r.status_code == 200, r.text
    assert r.json()['track_id'] == next_id, 'the test did not exercise a reused id'

    try:
        assert not stale.exists(), "the new track inherited another one's audio"
        audio = fleet.get(f'/api/audio/{next_id}')
        # No proxy and no file on the share yet (`uploaded` is what lands it),
        # so the only honest answer is the 404 -- never other audio at 200.
        assert audio.status_code == 404
    finally:
        stale.unlink(missing_ok=True)
        conn.execute('DELETE FROM tracks WHERE id=?', (next_id,))
        conn.commit()


@pytest.mark.parametrize('n_bytes', [1, 5, 2049])
def test_an_embedding_that_is_not_float32_is_refused_not_a_500(fleet, n_bytes):
    """music-5, 2026-08-21. np.frombuffer raises ValueError on a byte count
    that is not a multiple of 4, and nothing mapped it to a refusal: the route
    answered 500 with a traceback and the companion, reading that as transient,
    retried the same body until its attempt budget ran out."""
    uid = make_batch(fleet, names=('Truncated.wav',))
    item = claim(fleet, uid).json()['items'][0]['uid']
    body = result_body(embedding=base64.b64encode(b'\x01' * n_bytes).decode())
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/result',
                   json=body, headers=headers())
    assert r.status_code == 422, r.text
    assert r.json()['detail']['reason'] == 'embedding'
    # and nothing was written: the refusal happens before the transaction
    assert db.con().execute('SELECT COUNT(*) c FROM tracks WHERE rel_path=?',
                            ('Truncated.wav',)).fetchone()['c'] == 0


def test_a_truncated_window_vector_drops_the_window_not_the_track(fleet, fake_encoder):
    """Windows are optional by design, and this one runs inside the item
    transaction -- where the uncaught ValueError aborted the block after the
    track INSERT and the companion saw a 500 (music-5, 2026-08-21)."""
    conn = db.con()
    uid = make_batch(fleet, names=('Half A Window.wav',))
    item = claim(fleet, uid).json()['items'][0]['uid']
    body = result_body(windows=[{'idx': 0, 't0': 0.0, 't1': 10.0,
                                 'vector': base64.b64encode(b'\x01' * 13).decode()}])
    r = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item}/result',
                   json=body, headers=headers())
    assert r.status_code == 200, r.text
    track_id = r.json()['track_id']
    try:
        assert conn.execute('SELECT COUNT(*) c FROM windows WHERE track_id=?',
                            (track_id,)).fetchone()['c'] == 0
        assert conn.execute('SELECT dim FROM tracks WHERE id=?',
                            (track_id,)).fetchone()['dim'] == DIM
    finally:
        conn.execute('DELETE FROM tracks WHERE id=?', (track_id,))
        conn.commit()
