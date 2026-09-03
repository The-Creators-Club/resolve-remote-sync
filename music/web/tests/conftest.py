"""Test fixtures for the music web app.

`musicweb.config` reads its paths at import time (as the standalone app always
did), so DATA_ROOT and MUSIC_ROOT are pointed at a throwaway directory BEFORE
anything imports the package. That also keeps the tests off the real 20 MB
index and the real music share.

Nothing here needs torch: the seeded embeddings are synthetic, and only
/api/search would load CLAP.
"""
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = Path(tempfile.mkdtemp(prefix='musicweb-tests-'))
_LIBRARY = _TMP / 'library'
_LIBRARY.mkdir(parents=True, exist_ok=True)
os.environ['DATA_ROOT'] = str(_TMP)
os.environ['MUSIC_ROOT'] = str(_LIBRARY)
# Ingest is fail-closed since 2026-08-17 (COMMERCIAL_READINESS.md item 15): a
# standalone musicweb -- which is exactly what this suite drives -- refuses the
# write path without MUSIC_INGEST_TOKEN. The suite therefore runs configured
# like a deployment, and the `client` fixture sends the matching header on every
# request. Tests about the gate itself clear one or the other.
INGEST_TOKEN = 'test-music-ingest-token-0123456789'
os.environ['MUSIC_INGEST_TOKEN'] = INGEST_TOKEN

from musicweb import db                          # noqa: E402
from musicweb.main import app                    # noqa: E402

# The one file /api/audio streams in the range test. Content is arbitrary --
# the route is a byte server and never decodes anything.
AUDIO_BYTES = bytes(range(256)) * 40             # 10240 bytes
DIM = 8

CATEGORIES = {
    'genre': ['ambient', 'orchestral'],
    'mood': ['tense', 'peaceful'],
    'instrument': ['piano'],
    'use_case': ['montage'],
    'texture': ['drone'],
}
AXES = ['arousal', 'valence', 'tension', 'organic']

TRACKS = [
    # (filename, duration, bpm, key, unit embedding seed)
    ('ES_Tense Pulse.wav', 120.0, 128.0, 'A minor', 0),
    ('01JBF47TBD7T37HMG3WXZ8HQTS.mp3', 200.0, 90.0, 'C major', 1),
    ('Winter Rain.flac', 240.0, 70.0, 'D minor', 2),
    ('12345_67.aac', 60.0, None, None, 3),
]


def _unit(seed):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=DIM).astype(np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture(scope='session', autouse=True)
def seeded_db():
    """One seeded database for the whole session.

    Session-scoped because both the connection (thread-local, see db.con) and
    the search Index are process-wide singletons, exactly as in production.
    """
    con = db.connect()
    db.init(con)

    for i, (name, dur, bpm, key, seed) in enumerate(TRACKS, start=1):
        vec = _unit(seed)
        path = _LIBRARY / name
        path.write_bytes(AUDIO_BYTES)
        con.execute(
            'INSERT INTO tracks(id,rel_path,filename,ext,bytes,duration,'
            'samplerate,channels,codec,bpm,music_key,key_conf,lufs,peak_db,'
            'embedding,dim,file_hash,model,analyzed_at) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (i, name, name, Path(name).suffix, len(AUDIO_BYTES), dur, 48000, 2,
             'pcm', bpm, key, 0.1, -14.0, -1.0, db.to_blob(vec), DIM,
             'h%d' % i, 'test-model', '2026-08-10T00:00:00+00:00'))
        # two windows per track, one of them the track vector itself
        for idx in range(2):
            con.execute('INSERT INTO windows(track_id,idx,t0,t1,embedding) '
                        'VALUES(?,?,?,?,?)',
                        (i, idx, idx * 10.0, idx * 10.0 + 10.0,
                         db.to_blob(_unit(seed * 10 + idx))))
        con.execute('INSERT INTO peaks(track_id,n,data) VALUES(?,?,?)',
                    (i, 4, bytes([0, 128, 255, 64])))
        for cat, labels in CATEGORIES.items():
            for rank, label in enumerate(labels, start=1):
                con.execute('INSERT INTO tags(track_id,category,label,score,pct,rank) '
                            'VALUES(?,?,?,?,?,?)',
                            (i, cat, label, 0.5 / rank, 90.0 - 10 * rank, rank))
        for a, axis in enumerate(AXES):
            con.execute('INSERT INTO axes(track_id,axis,raw,pct) VALUES(?,?,?,?)',
                        (i, axis, 0.1 * a, 25.0 * (a + 1)))

    dirs = np.stack([_unit(99)])
    db.save_debias(con, dirs)
    db.set_meta(con, 'model', 'test-model')
    db.set_meta(con, 'tagged_at', '2026-08-10T00:00:00+00:00')
    con.commit()
    con.close()
    return _TMP


@pytest.fixture()
def client(seeded_db):
    from fastapi.testclient import TestClient
    with TestClient(app, headers={'X-Ingest-Token': INGEST_TOKEN}) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_rescore_clock():
    """Every test gets its own rescore clock (MUSIC-5, 2026-09-04).

    `rescore` coalesces library rescores per PROCESS, which is what stops a
    200-track drop doing 200 full passes -- and a test suite is one process, so
    without this whichever test scored first would leave every later one
    `deferred`. The coalescer itself is exercised deliberately, in
    tests/test_rescore_transaction.py.
    """
    from musicweb import rescore
    rescore._last_rescore = None
    yield
    rescore._last_rescore = None
