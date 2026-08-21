"""What a drain reports about the rows it could NOT analyse (music-3).

2026-08-21. `drain_queue` parked a failure in the PULLED copy and told nobody
else: the bundle carried only the uids it closed, so on the live NAS index the
row stayed `pending` for good. The editor's ingest panel counted it as waiting,
the duplicate defences went on treating the file as a held track, and the next
drain decoded the same broken file again.

Torch-free, like the rest of this suite: nothing here decodes anything. The
failure under test is "the file named by the journal row is not there", which
`drain_queue` answers before it ever reaches CLAP.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import index_music                                               # noqa: E402
from musicweb import db                                          # noqa: E402


@pytest.fixture
def index(tmp_path, monkeypatch):
    """A journal with one queued upload whose file is not on this host."""
    monkeypatch.setattr(index_music.config, 'MUSIC_ROOT', tmp_path / 'library')
    (tmp_path / 'library').mkdir()
    con = sqlite3.connect(tmp_path / 'music.db')
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    db.ensure_schema(con)
    db.queue_add(con, 'ghost.wav', 'ghost.wav', bytes_=100, duration=60.0,
                 digest='deadbeef')
    con.commit()
    uid = con.execute('SELECT uid FROM ingest_queue').fetchone()['uid']
    yield con, uid
    con.close()


def test_a_parked_row_is_reported_for_the_bundle(index):
    con, uid = index
    done, failed, drained, parked = index_music.drain_queue(con, clap=None)

    assert (done, failed, drained) == (0, 1, [])
    assert [u for u, _error in parked] == [uid]
    assert 'ghost.wav' in parked[0][1] or 'is not at' in parked[0][1]
    # ...and it is parked HERE too, exactly as before
    assert con.execute('SELECT state FROM ingest_queue WHERE uid=?',
                       (uid,)).fetchone()['state'] == db.FAILED


def test_an_empty_queue_still_returns_four_values(index):
    con, uid = index
    qid = con.execute('SELECT id FROM ingest_queue WHERE uid=?', (uid,)).fetchone()['id']
    db.queue_mark_done(con, qid, None)

    assert index_music.drain_queue(con, clap=None) == (0, 0, [], [])
