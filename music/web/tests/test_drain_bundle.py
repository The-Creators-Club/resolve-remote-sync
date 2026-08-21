"""The drain handoff: what survives an upload arriving mid-drain.

The property under test is the one the pull-drain-push loop did not have
(2026-08-17, COMMERCIAL_READINESS.md item 14): a drain may only close the
journal rows it analysed. Everything here therefore works with TWO databases --
`nas`, which keeps receiving uploads, and `rig`, the copy pulled off it -- and
asserts about what is left in `nas` afterwards, because the lost write was only
ever visible there.

Deliberately no models and no ffmpeg: a "drained" track is written into the rig
copy by hand, exactly as `index_music.analyse_one` + `upsert` would leave it.
What matters to this module is the merge, not the embedding.
"""
import sqlite3

import pytest

from musicweb import db, drain

DIM = 4


def _vec(seed):
    """A deterministic float32 blob of DIM values, no numpy needed."""
    import struct
    return struct.pack('<%df' % DIM, *[float(seed + i) for i in range(DIM)])


def _fresh(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    db.ensure_schema(con)
    return con


def _queue(con, rel_path, digest='hash-%s'):
    """Land a journal row the way routes_ingest.queue_one does. -> (id, uid)."""
    qid = db.queue_add(con, rel_path, rel_path, bytes_=100, duration=60.0,
                       digest=digest % rel_path if '%s' in digest else digest)
    uid = con.execute('SELECT uid FROM ingest_queue WHERE id=?', (qid,)).fetchone()['uid']
    return qid, uid


def _analyse(con, rel_path, seed=1):
    """Write the result of a CLAP analysis for `rel_path`. -> the track id."""
    con.execute(
        'INSERT INTO tracks(rel_path,filename,ext,bytes,duration,samplerate,'
        'channels,codec,bpm,music_key,key_conf,lufs,peak_db,embedding,dim,'
        'file_hash,model,analyzed_at) '
        "VALUES(?,?,'.wav',100,60.0,48000,2,'pcm',120.0,'A minor',0.5,-14.0,"
        "-1.0,?,?,'h','test-model','2026-08-17T00:00:00+00:00')",
        (rel_path, rel_path, _vec(seed), DIM))
    tid = con.execute('SELECT id FROM tracks WHERE rel_path=?',
                      (rel_path,)).fetchone()['id']
    con.execute('INSERT INTO windows(track_id,idx,t0,t1,embedding) VALUES(?,0,0.0,10.0,?)',
                (tid, _vec(seed + 100)))
    con.execute('INSERT INTO peaks(track_id,n,data) VALUES(?,3,?)', (tid, b'\x01\x02\x03'))
    for cat, label in (('genre', 'ambient'), ('mood', 'calm')):
        con.execute('INSERT INTO tags(track_id,category,label,score,pct,rank) '
                    'VALUES(?,?,?,0.9,88.0,1)', (tid, cat, label))
    con.execute("INSERT INTO axes(track_id,axis,raw,pct) VALUES(?,'arousal',0.2,40.0)",
                (tid,))
    con.commit()
    return tid


@pytest.fixture
def nas_and_rig(tmp_path):
    """The NAS index with one queued upload, and the copy pulled off it.

    The copy is taken the way DEPLOY.md's step 1 takes it -- a file copy of a
    checkpointed database -- so the two share every id, which is precisely why
    ids cannot be the key the push is written against.
    """
    nas_path = tmp_path / 'nas' / 'music.db'
    nas_path.parent.mkdir()
    nas = _fresh(nas_path)
    _, uid = _queue(nas, 'first.wav')
    nas.commit()
    nas.close()

    rig_path = tmp_path / 'rig' / 'music.db'
    rig_path.parent.mkdir()
    rig_path.write_bytes(nas_path.read_bytes())

    nas = _fresh(nas_path)
    rig = _fresh(rig_path)
    yield nas, rig, uid, tmp_path
    nas.close()
    rig.close()


def _drain(rig, uid, rel_path, seed=1):
    """What index_music.drain_queue does to the pulled copy."""
    tid = _analyse(rig, rel_path, seed=seed)
    qid = rig.execute('SELECT id FROM ingest_queue WHERE uid=?', (uid,)).fetchone()['id']
    db.queue_mark_done(rig, qid, tid)
    return tid


def test_an_upload_queued_during_the_drain_survives_the_push(nas_and_rig):
    """The whole point. The old loop overwrote the NAS file and lost this row."""
    nas, rig, uid, tmp = nas_and_rig
    _drain(rig, uid, 'first.wav')

    # ... and meanwhile, an editor drops another cue on the NAS.
    _, late_uid = _queue(nas, 'late.wav')
    nas.commit()

    bundle = tmp / 'drain.db'
    drain.export_bundle(rig, [uid], bundle)
    report = drain.apply_bundle(nas, bundle)

    assert report['applied'] == [uid]
    states = dict(nas.execute('SELECT uid,state FROM ingest_queue'))
    assert states[uid] == db.DONE
    assert states[late_uid] == db.PENDING, 'the mid-drain upload was overwritten'
    assert nas.execute('SELECT COUNT(*) c FROM tracks').fetchone()['c'] == 1


def test_the_applied_track_arrives_whole(nas_and_rig):
    nas, rig, uid, tmp = nas_and_rig
    _drain(rig, uid, 'first.wav', seed=7)

    bundle = tmp / 'drain.db'
    drain.export_bundle(rig, [uid], bundle)
    drain.apply_bundle(nas, bundle)

    row = nas.execute('SELECT * FROM tracks WHERE rel_path=?', ('first.wav',)).fetchone()
    assert row['dim'] == DIM
    assert row['embedding'] == _vec(7)
    # affinity check: a transport table declaring TEXT would hand back '60.0'
    assert isinstance(row['duration'], float)
    assert isinstance(row['bytes'], int)
    assert nas.execute('SELECT COUNT(*) c FROM windows WHERE track_id=?',
                       (row['id'],)).fetchone()['c'] == 1
    assert nas.execute('SELECT data FROM peaks WHERE track_id=?',
                       (row['id'],)).fetchone()['data'] == b'\x01\x02\x03'
    assert nas.execute('SELECT COUNT(*) c FROM tags WHERE track_id=?',
                       (row['id'],)).fetchone()['c'] == 2
    # the journal row points at the LOCAL track id
    assert nas.execute('SELECT track_id FROM ingest_queue WHERE uid=?',
                       (uid,)).fetchone()['track_id'] == row['id']


def test_track_ids_need_not_agree_between_the_two_indexes(nas_and_rig):
    """The reason the bundle is keyed on uid and rel_path, never on `id`."""
    nas, rig, uid, tmp = nas_and_rig
    # the NAS indexed something else in the meantime, so its next id is taken
    _analyse(nas, 'unrelated.wav', seed=3)
    rig_tid = _drain(rig, uid, 'first.wav')

    bundle = tmp / 'drain.db'
    drain.export_bundle(rig, [uid], bundle)
    drain.apply_bundle(nas, bundle)

    nas_tid = nas.execute('SELECT id FROM tracks WHERE rel_path=?',
                          ('first.wav',)).fetchone()['id']
    assert nas_tid != rig_tid
    assert nas.execute('SELECT track_id FROM ingest_queue WHERE uid=?',
                       (uid,)).fetchone()['track_id'] == nas_tid
    assert nas.execute('SELECT COUNT(*) c FROM tracks').fetchone()['c'] == 2


def test_applying_twice_changes_nothing(nas_and_rig):
    """Idempotent, so a push interrupted by a dropped Tailscale link is re-run."""
    nas, rig, uid, tmp = nas_and_rig
    _drain(rig, uid, 'first.wav')
    bundle = tmp / 'drain.db'
    drain.export_bundle(rig, [uid], bundle)

    drain.apply_bundle(nas, bundle)
    before = nas.execute('SELECT COUNT(*) c FROM windows').fetchone()['c']
    second = drain.apply_bundle(nas, bundle)

    assert second['applied'] == []
    assert second['skipped'] == [(uid, 'already done')]
    assert nas.execute('SELECT COUNT(*) c FROM windows').fetchone()['c'] == before
    assert nas.execute('SELECT COUNT(*) c FROM tracks').fetchone()['c'] == 1


def test_a_row_whose_file_changed_since_the_pull_is_refused(nas_and_rig):
    """Same path, different bytes: the embedding describes audio that is gone."""
    nas, rig, uid, tmp = nas_and_rig
    _drain(rig, uid, 'first.wav')
    bundle = tmp / 'drain.db'
    drain.export_bundle(rig, [uid], bundle)

    nas.execute("UPDATE ingest_queue SET content_hash='something-else' WHERE uid=?",
                (uid,))
    nas.commit()
    report = drain.apply_bundle(nas, bundle)

    assert report['applied'] == []
    assert 'content_hash changed' in report['skipped'][0][1]
    assert nas.execute('SELECT COUNT(*) c FROM tracks').fetchone()['c'] == 0
    assert nas.execute('SELECT state FROM ingest_queue WHERE uid=?',
                       (uid,)).fetchone()['state'] == db.PENDING


def test_a_re_dropped_upload_gets_a_new_uid_and_is_not_closed_by_the_old_bundle(nas_and_rig):
    """queue_add re-mints uid, so a stale bundle cannot close a NEW upload.

    Without that, dropping the same filename again while a drain was out would
    attach the first upload's embedding to the second one's bytes and report it
    as indexed.
    """
    nas, rig, uid, tmp = nas_and_rig
    _drain(rig, uid, 'first.wav')
    bundle = tmp / 'drain.db'
    drain.export_bundle(rig, [uid], bundle)

    _, new_uid = _queue(nas, 'first.wav')       # same path, second upload
    nas.commit()
    assert new_uid != uid

    report = drain.apply_bundle(nas, bundle)
    assert report['applied'] == []
    assert 'no journal row with this uid' in report['skipped'][0][1]
    assert nas.execute('SELECT state FROM ingest_queue WHERE uid=?',
                       (new_uid,)).fetchone()['state'] == db.PENDING


def test_the_library_wide_rescore_travels_with_the_bundle(nas_and_rig):
    """Percentiles are library-relative, so retag's output has to come too."""
    nas, rig, uid, tmp = nas_and_rig
    _analyse(nas, 'old.wav', seed=5)
    _analyse(rig, 'old.wav', seed=5)
    _drain(rig, uid, 'first.wav')
    # the drain's retag re-scored the whole library in the pulled copy
    rig.execute("UPDATE tags SET pct=11.0 WHERE track_id=(SELECT id FROM tracks "
                "WHERE rel_path='old.wav')")
    rig.execute('INSERT INTO debias(idx,vec) VALUES(0,?)', (_vec(9),))
    rig.commit()

    bundle = tmp / 'drain.db'
    drain.export_bundle(rig, [uid], bundle)
    report = drain.apply_bundle(nas, bundle)

    assert report['rescored_tracks'] == 2
    pct = nas.execute(
        "SELECT pct FROM tags JOIN tracks ON tracks.id = tags.track_id "
        "WHERE tracks.rel_path='old.wav' LIMIT 1").fetchone()['pct']
    assert pct == 11.0
    assert nas.execute('SELECT vec FROM debias').fetchone()['vec'] == _vec(9)


def test_rescore_skips_tracks_this_index_no_longer_has(nas_and_rig):
    """A prune between pull and push is a deletion, not a row to resurrect."""
    nas, rig, uid, tmp = nas_and_rig
    _analyse(rig, 'gone.wav', seed=5)
    _drain(rig, uid, 'first.wav')

    bundle = tmp / 'drain.db'
    drain.export_bundle(rig, [uid], bundle)
    drain.apply_bundle(nas, bundle)

    assert nas.execute("SELECT COUNT(*) c FROM tracks WHERE rel_path='gone.wav'"
                       ).fetchone()['c'] == 0


def test_a_uid_that_was_never_analysed_is_reported_not_exported(nas_and_rig):
    nas, rig, uid, tmp = nas_and_rig
    bundle = tmp / 'drain.db'
    r = drain.export_bundle(rig, [uid], bundle)

    assert r['tracks'] == 0
    assert r['skipped'] == [(uid, 'not analysed')]
    assert drain.apply_bundle(nas, bundle)['applied'] == []


def test_export_refuses_to_overwrite_an_existing_bundle(nas_and_rig):
    nas, rig, uid, tmp = nas_and_rig
    _drain(rig, uid, 'first.wav')
    bundle = tmp / 'drain.db'
    drain.export_bundle(rig, [uid], bundle)
    with pytest.raises(drain.BundleError):
        drain.export_bundle(rig, [uid], bundle)


def test_apply_refuses_an_index_that_predates_the_journal(nas_and_rig):
    """A NAS still on the old container has no uid column to match on."""
    nas, rig, uid, tmp = nas_and_rig
    _drain(rig, uid, 'first.wav')
    bundle = tmp / 'drain.db'
    drain.export_bundle(rig, [uid], bundle)

    old_path = tmp / 'old.db'
    old = sqlite3.connect(old_path)
    old.row_factory = sqlite3.Row
    db.ensure_schema(old)
    old.execute('DROP INDEX idx_queue_uid')
    old.execute('ALTER TABLE ingest_queue DROP COLUMN uid')
    old.commit()
    with pytest.raises(drain.BundleError, match='ingest_queue.uid'):
        drain.apply_bundle(old, bundle)
    old.close()


def test_a_failed_apply_leaves_the_index_and_the_journal_untouched(nas_and_rig,
                                                                  monkeypatch):
    """One transaction: the journal is never ahead of the tracks it points at."""
    nas, rig, uid, tmp = nas_and_rig
    _drain(rig, uid, 'first.wav')
    bundle = tmp / 'drain.db'
    drain.export_bundle(rig, [uid], bundle)

    def boom(*a, **k):
        raise RuntimeError('link dropped mid-apply')
    monkeypatch.setattr(drain, '_apply_children', boom)

    with pytest.raises(RuntimeError):
        drain.apply_bundle(nas, bundle)

    assert nas.execute('SELECT COUNT(*) c FROM tracks').fetchone()['c'] == 0
    assert nas.execute('SELECT state FROM ingest_queue WHERE uid=?',
                       (uid,)).fetchone()['state'] == db.PENDING


def test_inspect_and_apply_from_the_command_line(nas_and_rig, capsys):
    nas, rig, uid, tmp = nas_and_rig
    _drain(rig, uid, 'first.wav')
    bundle = tmp / 'drain.db'
    drain.export_bundle(rig, [uid], bundle)
    nas.commit()
    nas.close()

    assert drain.main(['inspect', str(bundle)]) == 0
    assert 'first.wav' in capsys.readouterr().out

    nas_path = tmp / 'nas' / 'music.db'
    assert drain.main(['apply', str(bundle), '--db', str(nas_path)]) == 0
    assert 'applied 1 track(s)' in capsys.readouterr().out

    again = sqlite3.connect(nas_path)
    again.row_factory = sqlite3.Row
    assert again.execute('SELECT state FROM ingest_queue WHERE uid=?',
                         (uid,)).fetchone()['state'] == db.DONE
    again.close()


# --- music-3: the rows the drain could NOT analyse -----------------------------

def _park(rig, uid, error='RuntimeError: no decodable audio'):
    """What index_music._park does to the pulled copy."""
    qid = rig.execute('SELECT id FROM ingest_queue WHERE uid=?', (uid,)).fetchone()['id']
    db.queue_mark_failed(rig, qid, error)
    return [(uid, error)]


def test_a_failed_drain_row_is_parked_on_the_live_index_too(nas_and_rig):
    """music-3, 2026-08-21. The failure used to exist only in the pulled copy:
    on the NAS the row stayed `pending`, so the editor's panel counted it as
    waiting forever, the duplicate defences went on holding the file, and the
    next drain decoded the same broken file again."""
    nas, rig, uid, tmp = nas_and_rig
    failures = _park(rig, uid)

    bundle = tmp / 'drain.db'
    drain.export_bundle(rig, [], bundle, failures=failures)
    report = drain.apply_bundle(nas, bundle)

    assert report['failed'] == [uid]
    row = nas.execute('SELECT state,error,attempts FROM ingest_queue WHERE uid=?',
                      (uid,)).fetchone()
    assert row['state'] == db.FAILED
    assert 'no decodable audio' in row['error']
    assert row['attempts'] == 1


def test_a_failure_is_refused_when_the_file_has_changed_since_the_pull(nas_and_rig):
    """Same agreement rule a successful row gets: different bytes at that path
    means the thing that failed is not the thing sitting there now, so the row
    stays pending for the next drain to look at properly."""
    nas, rig, uid, tmp = nas_and_rig
    failures = _park(rig, uid)
    nas.execute("UPDATE ingest_queue SET content_hash='something-else' WHERE uid=?",
                (uid,))
    nas.commit()

    bundle = tmp / 'drain.db'
    drain.export_bundle(rig, [], bundle, failures=failures)
    report = drain.apply_bundle(nas, bundle)

    assert report['failed'] == []
    assert [uid for uid, _why in report['skipped']] == [uid]
    assert nas.execute('SELECT state FROM ingest_queue WHERE uid=?',
                       (uid,)).fetchone()['state'] == db.PENDING


def test_a_row_already_done_is_never_forced_back_to_failed(nas_and_rig):
    """A sweep on the NAS can have indexed the file in the meantime
    (queue_reconcile). A stale failure must not undo that."""
    nas, rig, uid, tmp = nas_and_rig
    failures = _park(rig, uid)
    tid = _analyse(nas, 'first.wav')
    qid = nas.execute('SELECT id FROM ingest_queue WHERE uid=?', (uid,)).fetchone()['id']
    db.queue_mark_done(nas, qid, tid)

    bundle = tmp / 'drain.db'
    drain.export_bundle(rig, [], bundle, failures=failures)
    report = drain.apply_bundle(nas, bundle)

    assert report['failed'] == []
    assert nas.execute('SELECT state FROM ingest_queue WHERE uid=?',
                       (uid,)).fetchone()['state'] == db.DONE


def test_a_bundle_without_the_failures_table_still_applies(nas_and_rig):
    """Additive in both directions, which is why BUNDLE_VERSION is unchanged:
    an older base rig's bundle has no such table and simply reports none."""
    nas, rig, uid, tmp = nas_and_rig
    _drain(rig, uid, 'first.wav')
    bundle = tmp / 'drain.db'
    drain.export_bundle(rig, [uid], bundle)

    old = sqlite3.connect(bundle)
    old.execute('DROP TABLE bundle_failures')
    old.commit()
    old.close()

    report = drain.apply_bundle(nas, bundle)
    assert report['applied'] == [uid]
    assert report['failed'] == []
