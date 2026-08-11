r"""`/api/reveal` must not hand a library path to a shell.

MUSIC-2 (2026-08-11): it used to `os.spawnl` COMSPEC with `/c explorer
/select,<path>`, and cmd.exe re-parses what it is given. `db.safe_upload_name`
strips `<>:"/\|?*` but NOT `&`, so a file called `x&calc.mp3` -- a legal
Windows filename an editor can drop into the library over SMB -- turned a
logged-in user's reveal click into local command execution, and an innocent
`rock&roll.mp3` just opened Explorer somewhere else.

The route only ever spawns on Windows; on the NAS container it answers
`ok: False` and touches nothing.
"""
import os

import pytest

from musicweb import routes_ingest
from musicweb.db import connect

pytestmark = pytest.mark.skipif(os.name != 'nt',
                                reason='the reveal route only spawns on Windows')

NASTY = 'rock&roll & calc.mp3'


@pytest.fixture()
def rows(client, seeded_db):
    """Two extra tracks -- one with a real file, one without.

    Removed again afterwards: the seeded database is session-scoped and other
    tests count its rows.
    """
    path = seeded_db / 'library' / NASTY
    path.write_bytes(b'0' * 16)
    con = connect()
    for tid, rel in ((90, NASTY), (91, 'gone.mp3')):
        con.execute('INSERT OR REPLACE INTO tracks(id,rel_path,filename,ext,'
                    'bytes,duration,embedding,dim,file_hash,model) '
                    "VALUES(?,?,?,'.mp3',16,10.0,NULL,8,'h','test-model')",
                    (tid, rel, rel))
    con.commit()
    yield 90, 91
    con.execute('DELETE FROM tracks WHERE id IN (90,91)')
    con.commit()
    con.close()
    path.unlink(missing_ok=True)


@pytest.fixture()
def spawned(monkeypatch):
    calls = []

    class FakePopen:
        def __init__(self, args, *a, **kw):
            calls.append((args, kw))

    monkeypatch.setattr(routes_ingest.subprocess, 'Popen', FakePopen)
    # anything reaching for a shell is the bug itself
    monkeypatch.setattr(routes_ingest.os, 'spawnl',
                        lambda *a, **kw: pytest.fail('reveal shelled out: %r' % (a,)))
    return calls


def test_reveal_spawns_explorer_directly_with_no_shell(client, rows, spawned):
    present, _ = rows
    r = client.get(f'/api/reveal/{present}')
    assert r.status_code == 200 and r.json()['ok'] is True

    (args, kw), = spawned
    assert isinstance(args, list), 'the argv must be a list, not a command string'
    assert args[0] == 'explorer'
    assert len(args) == 2 and args[1].startswith('/select,')
    # the whole path travels as ONE argument, metacharacters and all
    assert args[1].endswith(NASTY)
    assert not kw.get('shell')


def test_reveal_of_an_unknown_track_is_404(client, spawned):
    assert client.get('/api/reveal/999').status_code == 404
    assert spawned == []


def test_reveal_of_a_missing_file_spawns_nothing(client, rows, spawned):
    _, missing = rows
    assert client.get(f'/api/reveal/{missing}').json()['ok'] is False
    assert spawned == []
