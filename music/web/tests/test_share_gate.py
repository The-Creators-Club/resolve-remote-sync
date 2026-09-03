"""A write path may not run against a library this host cannot see.

bug-hunt-2026-09-03 music-1 and music-3. In every shipped deployment the
library is a BIND MOUNT (`{music_library_root}:/music-share`), and an unmounted
dataset does not present as an error: it presents as an ordinary EMPTY
DIRECTORY. Everything underneath then answers the wrong question in the
dangerous direction --

  * `db.unique_dest` sees no collisions, so the upload is moved into the
    mountpoint and the editor is told "queued" for bytes nothing will index;
  * `ingest_batches._taken_on_disk` calls every candidate free, so a name that
    belongs to an INDEXED track is handed out and `write_item_result` upserts
    ON CONFLICT(rel_path) over that track's embedding, windows and probe
    fields while its id -- and so its preview proxy -- stays.

`db.prune_missing` has refused an empty scan since MUSIC-3 for exactly this
reason ("that is a share that is not mounted, not an empty library"). These
tests pin the same refusal on the WRITE path, through the one helper both
callers use, and pin the two states it must NOT refuse: a brand-new empty
library, and the first ever upload on a fresh deployment.
"""
import sqlite3

import pytest
from fastapi import HTTPException

from musicweb import config, db, ingest_batches, routes_ingest

FILE = ('cue.wav', b'\x00fake audio' * 10, 'audio/wav')
EDITOR = {'X-CCSync-User': 'jsmith'}


@pytest.fixture()
def unmounted(tmp_path, monkeypatch):
    """The library root is gone: the mount did not come back after a reboot."""
    monkeypatch.setitem(config.SHARE_ROOTS, config.SHARE, tmp_path / 'not-mounted')
    return tmp_path / 'not-mounted'


@pytest.fixture()
def empty_mountpoint(tmp_path, monkeypatch):
    """The exact shipped shape: the path is there and the dataset is not."""
    root = tmp_path / 'music-share'
    root.mkdir()
    monkeypatch.setitem(config.SHARE_ROOTS, config.SHARE, root)
    return root


@pytest.fixture()
def _ffmpeg(monkeypatch):
    """ffmpeg is checked first, and this suite is about the check after it."""
    monkeypatch.setattr(routes_ingest, '_tool', lambda name: '/usr/bin/' + name)


def _blank_index():
    """A connection with an empty `tracks` table, and nothing else."""
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute('CREATE TABLE tracks (rel_path TEXT)')
    return con


# --- the helper both callers share --------------------------------------------

def test_a_mounted_library_is_ready(seeded_db):
    ok, why = config.share_root_ready(db.con())
    assert ok and why == ''


def test_an_absent_root_is_not_ready(unmounted, seeded_db):
    ok, why = config.share_root_ready(db.con())
    assert not ok
    assert 'not mounted' in why


def test_a_root_that_is_there_but_holds_none_of_the_indexed_tracks(empty_mountpoint,
                                                                   seeded_db):
    """The unmounted bind mount. An existence check cannot tell this from an
    empty library, so the INDEX is the evidence: it names four tracks and not
    one of them is visible here."""
    ok, why = config.share_root_ready(db.con())
    assert not ok
    assert 'not mounted' in why


def test_a_brand_new_empty_library_is_ready(empty_mountpoint):
    """A customer whose library has no cues yet must still be able to ingest,
    so emptiness alone is deliberately not the test."""
    ok, why = config.share_root_ready(_blank_index())
    assert ok and why == ''


def test_a_first_run_root_that_does_not_exist_yet_is_ready(unmounted):
    """Its parent is there and nothing is indexed: this is a fresh deployment,
    and the ingest path is allowed to create the root once."""
    ok, _ = config.share_root_ready(_blank_index())
    assert ok


def test_a_root_whose_parent_is_missing_too_is_not_ready(tmp_path, monkeypatch):
    """That is a misconfigured mount, not a first run."""
    monkeypatch.setitem(config.SHARE_ROOTS, config.SHARE,
                        tmp_path / 'nope' / 'music')
    ok, _ = config.share_root_ready(_blank_index())
    assert not ok


# --- music-1: the upload routes -----------------------------------------------

def test_an_upload_to_an_absent_share_is_refused(client, unmounted, _ffmpeg,
                                                 monkeypatch):
    monkeypatch.setattr(routes_ingest, '_load_indexer', lambda: None)
    before = db.con().execute('SELECT COUNT(*) c FROM ingest_queue').fetchone()['c']

    r = client.post('/api/ingest', files={'files': FILE})

    assert r.status_code == 503, r.text
    assert 'not mounted' in r.json()['detail']
    assert not unmounted.exists(), 'the refused ingest created the mountpoint'
    assert db.con().execute(
        'SELECT COUNT(*) c FROM ingest_queue').fetchone()['c'] == before


def test_an_upload_to_an_unmounted_mountpoint_is_refused(client, empty_mountpoint,
                                                         _ffmpeg, monkeypatch):
    """The one that answered `{"status": "queued"}` and moved the file into the
    container's view of an unmounted dataset."""
    monkeypatch.setattr(routes_ingest, '_load_indexer', lambda: None)

    r = client.post('/api/ingest', files={'files': FILE})

    assert r.status_code == 503, r.text
    assert list(empty_mountpoint.iterdir()) == [], 'bytes landed under the mountpoint'


def test_the_inline_half_is_refused_too(client, unmounted, _ffmpeg, monkeypatch):
    """The base rig mounts the library over SMB and loses it the same way. The
    refusal comes before the CLAP model is touched, which is why this test can
    hand _load_indexer two stubs."""
    monkeypatch.setattr(routes_ingest, '_load_indexer', lambda: (object(), object()))

    r = client.post('/api/ingest', files={'files': FILE})

    assert r.status_code == 503, r.text
    assert 'not mounted' in r.json()['detail']


def test_the_first_ever_upload_may_still_create_the_root(unmounted):
    """The mkdir that queue_one kept: parent there, nothing indexed."""
    unmounted.parent.mkdir(parents=True, exist_ok=True)
    routes_ingest._create_share_root_on_first_run(_blank_index())
    assert unmounted.is_dir()


def test_the_mkdir_does_not_run_for_a_library_that_has_tracks(unmounted, seeded_db):
    """The line this fix removed: an unconditional mkdir is what turned an
    absent mount into a directory the upload was moved into."""
    routes_ingest._create_share_root_on_first_run(db.con())
    assert not unmounted.exists()


# --- music-3: allocate_name ---------------------------------------------------

@pytest.fixture()
def ghost_track(seeded_db):
    """A `tracks` row whose file is not on disk: removed by hand, or a share
    that is only half there."""
    conn = db.con()
    conn.execute("INSERT INTO tracks(id, rel_path, filename, ext, bytes, dim) "
                 "VALUES(901, 'Ghost Cue.wav', 'Ghost Cue.wav', '.wav', 1, 8)")
    conn.commit()
    yield 'Ghost Cue.wav'
    conn.execute('DELETE FROM tracks WHERE id = 901')
    conn.commit()


def test_a_name_an_indexed_track_holds_is_not_handed_out(ghost_track):
    """It was, and `write_item_result` upserts ON CONFLICT(rel_path): the old
    cue's embedding, windows and probe fields were replaced in place under the
    same id, so its preview proxy went on playing the old audio."""
    name = ingest_batches.allocate_name(db.con(), ghost_track)
    assert name == 'Ghost Cue (2).wav'


def test_the_precheck_steps_around_it_too(client, ghost_track):
    r = client.post('/api/ingest-batches/precheck',
                    json={'items': [{'local_id': 'a', 'name': ghost_track,
                                     'size': 1024, 'duration': 60.0}]},
                    headers=EDITOR)
    assert r.status_code == 200, r.text
    assert r.json()['items'][0]['final_name'] == 'Ghost Cue (2).wav'


def test_allocate_name_refuses_a_share_it_cannot_see(unmounted, seeded_db):
    """Not an empty answer: on an unreadable share every candidate looks free,
    which is the state that hands out a live track's name."""
    with pytest.raises(HTTPException) as exc:
        ingest_batches.allocate_name(db.con(), 'theme.wav')
    assert exc.value.status_code == 503
