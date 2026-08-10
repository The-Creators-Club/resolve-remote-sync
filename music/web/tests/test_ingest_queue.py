"""Queued ingest: what a host with no GPU does with a dropped file (port step 7).

The container is the case under test here -- no torch, no CLAP audio tower, and
`add_indexer_to_path()` finding nothing -- so every test forces the queued path
by making `_load_indexer()` answer None, which is exactly what that host does.
The last test goes the other way and pins that a host which *does* have the
indexer still ingests inline, because the base rig must not be quietly demoted
to queueing.

ffmpeg is the one native dependency the queued path has, and the two functions
that shell out to it (`_probe`, `_transcode_to_mp3`) are stubbed throughout so
the suite tests the ingest logic rather than this machine's ffmpeg build. The
real thing is exercised by hand against real audio; what is pinned here is the
part that would silently rot: which uploads are refused, what lands where, and
what the queue row says afterwards.
"""
import sqlite3

import pytest

from musicweb import config, db
from musicweb import routes_ingest
from tests.conftest import AUDIO_BYTES

MP3_BYTES = b'ID3\x03\x00' + bytes(range(200)) * 8


@pytest.fixture(autouse=True)
def queued_host(monkeypatch):
    """This host is the NAS container: no indexer, and ffmpeg is stubbed."""
    monkeypatch.setattr(routes_ingest, '_load_indexer', lambda: None)
    monkeypatch.setattr(routes_ingest, '_tool', lambda name: '/usr/bin/' + name)
    yield


@pytest.fixture(autouse=True)
def clean_library(seeded_db):
    """Leave the share root and the queue exactly as they were found.

    The seeded database is session-scoped and shared with every other module,
    so a file landed here (or a row left in the queue) is another test's
    surprise.
    """
    root = config.share_root()
    before = {p for p in root.iterdir()}
    yield
    for p in root.iterdir():
        if p not in before:
            p.unlink()
    c = db.connect()
    c.execute('DELETE FROM ingest_queue')
    c.commit()
    c.close()


def probing(duration, **extra):
    """A stub ffprobe that reports `duration` seconds of audio."""
    def _probe(path):
        return dict({'duration': duration, 'samplerate': 48000,
                     'channels': 2, 'codec': 'pcm_s16le'}, **extra)
    return _probe


@pytest.fixture()
def probe(monkeypatch):
    def use(duration, **extra):
        monkeypatch.setattr(routes_ingest, '_probe', probing(duration, **extra))
    return use


@pytest.fixture()
def transcode(monkeypatch):
    """Stand-in for ffmpeg. Records its calls; writes a real (fake) mp3."""
    calls = []

    def _transcode(src, dest_dir):
        calls.append(src.name)
        dest = dest_dir / (src.stem + '.mp3')
        dest.write_bytes(MP3_BYTES)
        return dest

    monkeypatch.setattr(routes_ingest, '_transcode_to_mp3', _transcode)
    return calls


def post(client, name, data=b'\x00new audio bytes' * 100):
    return client.post('/api/ingest', files={'files': (name, data, 'audio/wav')})


def queue_rows():
    c = db.connect()
    try:
        c.row_factory = sqlite3.Row
        return c.execute('SELECT * FROM ingest_queue ORDER BY id').fetchall()
    finally:
        c.close()


# ------------------------------------------------------- the container case
def test_an_upload_is_queued_not_analysed(client, probe):
    probe(93.5)
    r = post(client, 'Brand New Cue.wav')
    assert r.status_code == 200
    body = r.json()

    assert body['mode'] == 'queued'
    assert body['added'] == 0 and body['queued'] == 1
    got = body['results'][0]
    assert got['ok'] is True
    assert got['status'] == 'queued'
    assert got['state'] == 'pending'
    assert got['rel_path'] == 'Brand New Cue.wav'
    assert got['duration'] == 93.5
    # nothing here has decoded the file, so nothing here may claim to know
    assert 'bpm' not in got and 'key' not in got and 'id' not in got


def test_the_file_lands_in_the_share_under_a_collision_free_name(client, probe):
    """Two different cues that happen to share a filename. The library is flat,
    so the second must not overwrite the first."""
    probe(93.5)
    post(client, 'Brand New Cue.wav', b'first' * 500)
    probe(210.0)
    post(client, 'Brand New Cue.wav', b'second' * 500)

    root = config.share_root()
    assert (root / 'Brand New Cue.wav').read_bytes() == b'first' * 500
    assert (root / 'Brand New Cue (2).wav').read_bytes() == b'second' * 500
    assert [r['rel_path'] for r in queue_rows()] == ['Brand New Cue.wav',
                                                     'Brand New Cue (2).wav']


def test_the_row_is_pending_and_says_where_the_file_went(client, probe):
    probe(93.5)
    post(client, 'Brand New Cue.wav', b'x' * 4096)

    row, = queue_rows()
    assert row['state'] == 'pending'
    assert (row['share'], row['rel_path']) == ('music', 'Brand New Cue.wav')
    assert row['orig_name'] == 'Brand New Cue.wav'
    assert row['bytes'] == 4096
    assert row['duration'] == 93.5
    assert row['content_hash'] and row['attempts'] == 0
    assert row['track_id'] is None and row['error'] is None
    assert row['queued_at']


def test_the_landed_path_is_relative_never_absolute(client, probe):
    """The row is written on the NAS and read on the base rig, so it carries
    (share, rel_path) like every other row -- W: there, P: on an editor."""
    probe(10.0)
    post(client, 'Brand New Cue.wav')
    row, = queue_rows()
    assert not row['rel_path'].startswith('/')
    assert ':' not in row['rel_path']
    assert config.resolve_path(row['share'], row['rel_path']).is_file()


@pytest.mark.parametrize('name, landed', [
    ('../../evil.wav', 'evil.wav'),
    (r'..\..\evil.wav', 'evil.wav'),
    (r'C:\Windows\evil.wav', 'evil.wav'),
    ('sub/dir/evil.wav', 'evil.wav'),
])
def test_a_dangerous_upload_name_cannot_escape_the_share(client, probe, name, landed):
    """The browser supplies this string. It is reduced to a basename, and the
    join is re-validated through safe_join regardless."""
    probe(10.0)
    got = post(client, name).json()['results'][0]
    assert got['status'] == 'queued'
    assert got['rel_path'] == landed
    assert (config.share_root() / landed).is_file()
    assert config.resolve_path('music', got['rel_path']).parent == config.share_root()


# --------------------------------------------------------------- the ogg case
def test_an_ogg_is_transcoded_to_mp3_before_it_is_queued(client, probe, transcode):
    probe(41.0)
    got = post(client, 'Dropped Preview.ogg', b'oggish' * 300).json()['results'][0]

    assert transcode == ['Dropped Preview.ogg']
    assert got['transcoded'] is True
    assert got['status'] == 'queued'
    assert got['name'] == 'Dropped Preview.mp3'

    root = config.share_root()
    assert (root / 'Dropped Preview.mp3').read_bytes() == MP3_BYTES
    assert not (root / 'Dropped Preview.ogg').exists()

    row, = queue_rows()
    assert row['rel_path'] == 'Dropped Preview.mp3'
    assert row['transcoded'] == 1
    assert row['orig_name'] == 'Dropped Preview.ogg'      # what was dropped
    assert row['bytes'] == len(MP3_BYTES)                 # what was kept


def test_a_wav_is_not_transcoded(client, probe, transcode):
    probe(41.0)
    got = post(client, 'Brand New Cue.wav').json()['results'][0]
    assert transcode == []
    assert 'transcoded' not in got


# -------------------------------------------------------- the duplicate cases
def test_a_byte_identical_upload_is_rejected_without_queueing(client, probe):
    """Defence 1: content hash. The seeded library files all hold AUDIO_BYTES."""
    probe(999.0)                       # nothing like it by name+duration
    got = post(client, 'Some Other Name.wav', AUDIO_BYTES).json()['results'][0]

    assert got['ok'] is False and got['duplicate'] is True
    assert got['status'] == 'error'
    assert 'already in the library as' in got['error']
    assert queue_rows() == []
    assert not (config.share_root() / 'Some Other Name.wav').exists()


def test_a_re_encode_is_rejected_by_name_and_duration(client, probe, transcode):
    """Defence 2: hashing cannot see this one -- a transcode changes every byte.

    'ES_Tense Pulse.wav' is in the seeded library at 120s; the .ogg preview
    beside it is the thing that actually gets dragged in by accident.
    """
    probe(120.4)
    got = post(client, 'ES_Tense Pulse.ogg', b'entirely different bytes'
               ).json()['results'][0]

    assert got['ok'] is False and got['duplicate'] is True
    assert 'ES_Tense Pulse.wav' in got['error']
    assert queue_rows() == []
    # and it cost no ffmpeg time: the check runs BEFORE the transcode
    assert transcode == []


def test_a_re_encode_far_enough_off_in_duration_is_a_different_cue(client, probe,
                                                                  transcode):
    probe(140.0)                       # 20s off the seeded 120s
    got = post(client, 'ES_Tense Pulse.ogg', b'entirely different bytes'
               ).json()['results'][0]
    assert got['status'] == 'queued'


def test_dropping_the_same_file_twice_only_queues_it_once(client, probe):
    """There is no `tracks` row to match against until an indexer has been
    past, so the queue itself has to be part of both defences."""
    probe(77.0)
    first = post(client, 'Twice Over.wav', b'same bytes' * 300).json()['results'][0]
    second = post(client, 'Twice Over.wav', b'same bytes' * 300).json()['results'][0]

    assert first['status'] == 'queued'
    assert second['ok'] is False and second['duplicate'] is True
    assert len(queue_rows()) == 1


def test_a_re_encode_of_something_already_queued_is_caught(client, probe, transcode):
    probe(77.0)
    post(client, 'Twice Over.wav', b'original bytes' * 300)
    got = post(client, 'Twice Over.ogg', b'different bytes' * 300).json()['results'][0]

    assert got['duplicate'] is True
    assert transcode == []
    assert len(queue_rows()) == 1


# ----------------------------------------------------------- what is refused
def test_a_non_audio_extension_is_refused(client, probe):
    probe(12.0)
    got = post(client, 'notes.txt', b'hello').json()['results'][0]
    assert got['ok'] is False and got['status'] == 'error'
    assert 'not an audio file' in got['error']
    assert queue_rows() == []


def test_a_renamed_non_audio_file_is_refused_by_ffprobe(client, probe):
    """The extension is the browser's claim; ffprobe is the only evidence."""
    probe(0.0)
    got = post(client, 'actually a zip.mp3', b'PK\x03\x04nope').json()['results'][0]
    assert got['ok'] is False
    assert got['error'] == 'no decodable audio stream'
    assert queue_rows() == []
    assert not (config.share_root() / 'actually a zip.mp3').exists()


def test_without_ffmpeg_the_whole_request_is_refused(client, probe, monkeypatch):
    """Half-ingesting is worse than refusing: without ffprobe there is no way to
    tell audio from a renamed .zip, and an .ogg cannot be transcoded at all."""
    probe(93.5)
    monkeypatch.setattr(routes_ingest, '_tool', lambda name: None)

    r = post(client, 'Brand New Cue.wav')

    assert r.status_code == 503
    detail = r.json()['detail']
    assert 'ffmpeg' in detail and 'ffprobe' in detail
    assert queue_rows() == []
    assert not (config.share_root() / 'Brand New Cue.wav').exists()


def test_a_half_present_ffmpeg_is_still_refused(client, probe, monkeypatch):
    probe(93.5)
    monkeypatch.setattr(routes_ingest, '_tool',
                        lambda name: None if name == 'ffprobe' else '/usr/bin/ffmpeg')
    r = post(client, 'Brand New Cue.wav')
    assert r.status_code == 503
    assert 'ffprobe' in r.json()['detail']


# ------------------------------------------------------------ the queue's states
def test_the_states_are_pending_done_failed():
    assert db.QUEUE_STATES == ('pending', 'done', 'failed')


def test_a_failed_row_is_not_handed_out_again_unless_asked(client, probe):
    """Otherwise every indexer run re-attempts a file that cannot be analysed,
    forever, and nobody ever reads the reason."""
    probe(50.0)
    post(client, 'Bad Cue.wav')
    c = db.connect()
    try:
        row, = db.queue_pending(c)
        db.queue_mark_failed(c, row['id'], 'RuntimeError: no decodable audio')

        assert db.queue_pending(c) == []
        assert [r['id'] for r in db.queue_pending(c, include_failed=True)] == [row['id']]

        parked, = db.queue_rows(c, db.FAILED)
        assert parked['state'] == 'failed'
        assert parked['error'] == 'RuntimeError: no decodable audio'
        assert parked['attempts'] == 1
        assert db.queue_counts(c) == {'pending': 0, 'done': 0, 'failed': 1}
    finally:
        c.close()


def test_marking_done_records_the_track_it_became(client, probe):
    probe(50.0)
    post(client, 'Good Cue.wav')
    c = db.connect()
    try:
        row, = db.queue_pending(c)
        db.queue_mark_done(c, row['id'], 3)
        after, = db.queue_rows(c, db.DONE)
        assert (after['state'], after['track_id'], after['error']) == ('done', 3, None)
        assert db.queue_pending(c) == []
    finally:
        c.close()


def test_a_sweep_that_indexed_a_queued_file_closes_its_row(client, probe):
    """A queued file sits in the library like any other, so a plain
    `index_music.py` run indexes it without ever reading this table."""
    probe(50.0)
    post(client, 'Swept Up.wav')
    c = db.connect()
    try:
        row, = db.queue_pending(c)
        c.execute('INSERT INTO tracks(id,rel_path,filename,embedding) '
                  'VALUES(?,?,?,?)', (901, 'Swept Up.wav', 'Swept Up.wav',
                                      db.to_blob([0.0] * 8)))
        c.commit()

        assert db.queue_reconcile(c) == 1
        after = c.execute('SELECT state, track_id FROM ingest_queue WHERE id=?',
                          (row['id'],)).fetchone()
        assert (after['state'], after['track_id']) == ('done', 901)
    finally:
        c.execute('DELETE FROM tracks WHERE id=901')
        c.commit()
        c.close()


def test_a_row_still_pending_is_left_alone_by_reconcile(client, probe):
    probe(50.0)
    post(client, 'Not Swept.wav')
    c = db.connect()
    try:
        assert db.queue_reconcile(c) == 0
        assert len(db.queue_pending(c)) == 1
    finally:
        c.close()


def test_the_queue_endpoint_surfaces_every_failure(client, probe):
    probe(50.0)
    post(client, 'Bad Cue.wav')
    c = db.connect()
    try:
        row, = db.queue_pending(c)
        db.queue_mark_failed(c, row['id'], 'RuntimeError: no decodable audio')
    finally:
        c.close()

    body = client.get('/api/ingest/queue').json()
    assert body['counts'] == {'pending': 0, 'done': 0, 'failed': 1}
    assert body['pending'] == []
    failed, = body['failed']
    assert failed['rel_path'] == 'Bad Cue.wav'
    assert failed['error'] == 'RuntimeError: no decodable audio'


def test_the_queue_endpoint_is_empty_and_honest_when_nothing_is_queued(client):
    body = client.get('/api/ingest/queue').json()
    assert body == {'counts': {'pending': 0, 'done': 0, 'failed': 0},
                    'failed': [], 'pending': []}


# ------------------------------------------------------------------- schema
def _v1_database(path):
    """A database with everything except the queue, stamped v1."""
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    db.ensure_schema(con)
    con.execute('DROP TABLE ingest_queue')
    con.execute('PRAGMA user_version = 1')
    con.commit()
    return con


def test_a_v1_database_gains_the_queue(tmp_path):
    con = _v1_database(tmp_path / 'music.db')
    try:
        con.execute("INSERT INTO tracks(rel_path,filename) VALUES('a.wav','a.wav')")
        con.commit()

        db.ensure_schema(con)

        assert db._table_exists(con, 'ingest_queue')
        assert con.execute('PRAGMA user_version').fetchone()[0] == 2
        assert con.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 1
    finally:
        con.close()


def test_a_database_stamped_v2_without_the_queue_is_repaired(tmp_path):
    """The 2026-08-10 incident's shape: schema.sql is re-applied to existing
    databases, so a stamp can run ahead of the schema. The already-applied
    predicate, not the version, decides."""
    con = _v1_database(tmp_path / 'music.db')
    try:
        con.execute('PRAGMA user_version = 2')
        con.commit()

        db.ensure_schema(con)

        assert db._table_exists(con, 'ingest_queue')
    finally:
        con.close()


def test_the_queue_migration_is_idempotent(tmp_path):
    con = _v1_database(tmp_path / 'music.db')
    try:
        db.ensure_schema(con)
        db.ensure_schema(con)
        db.ensure_schema(con)
        assert db.queue_counts(con) == {'pending': 0, 'done': 0, 'failed': 0}
    finally:
        con.close()


def test_the_state_column_refuses_a_state_nobody_handles(tmp_path):
    con = _v1_database(tmp_path / 'music.db')
    try:
        db.ensure_schema(con)
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO ingest_queue(rel_path,orig_name,state,"
                        "queued_at) VALUES('a.wav','a.wav','running','now')")
    finally:
        con.close()


def test_the_two_halves_agree_on_what_an_audio_file_is():
    """The queued path cannot import music_index (that is the whole point), so
    its extension list is a copy. A file the web half accepts and a library
    sweep then ignores would sit in the share unindexed forever."""
    if not config.add_indexer_to_path():
        pytest.skip('no indexer checked out here')
    try:
        from music_index import config as icfg
    except ImportError:
        pytest.skip('indexer not importable here')
    assert routes_ingest.AUDIO_EXTS == icfg.AUDIO_EXTS
    assert routes_ingest.TRANSCODE_EXTS == {'.ogg'}


# --------------------------------------------------------- the base rig case
def test_a_host_with_the_indexer_still_ingests_inline(client, monkeypatch):
    """The base rig must not be quietly demoted to queueing: when the indexer
    imports, the track is analysed, tagged and searchable in the response."""
    calls = []

    class FakeIngest:
        @staticmethod
        def library_hashes():
            calls.append('hashes')
            return {}

        @staticmethod
        def ingest_one(name, data, clap, con, known):
            calls.append('ingest_one')
            return {'name': name, 'ok': True, 'id': 1, 'rel_path': name,
                    'duration': 120.0, 'bpm': 128.0, 'key': 'A minor'}

    class FakeIndexMusic:
        @staticmethod
        def retag(con, clap):
            calls.append('retag')

    class FakeIndex:
        clap = object()

        def reload(self, con):
            calls.append('reload')

    monkeypatch.setattr(routes_ingest, '_load_indexer',
                        lambda: (FakeIngest, FakeIndexMusic))
    monkeypatch.setattr(routes_ingest, 'index', lambda: FakeIndex())

    body = post(client, 'Inline Cue.wav').json()

    assert body['mode'] == 'inline'
    assert body['added'] == 1 and body['queued'] == 0
    got = body['results'][0]
    assert got['status'] == 'added'
    assert got['bpm'] == 128.0
    assert got['track']['id'] == 1              # hydrated from the tracks row
    assert calls == ['hashes', 'ingest_one', 'retag', 'reload']
    assert queue_rows() == []                   # nothing queued on this host
