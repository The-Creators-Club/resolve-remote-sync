"""SQLite access. Embeddings are stored as raw float32 BLOBs.

Shared by both halves: the indexer (base rig) writes this database and the web
app reads it, so there is exactly one storage layer. `music_index` puts this
tree on sys.path for that reason -- a drift between writer and reader would be
silent.

Schema handling follows broll/web/app/db.py: schema.sql is the source of truth
and is safe to re-run (CREATE ... IF NOT EXISTS throughout), anything it cannot
express -- an ALTER -- is a numbered file in migrations/ applied in order and
tracked with PRAGMA user_version.

It differs from broll's runner in one way, and the reason is worth keeping:
this database predates user_version entirely. The live 376-track index sat at
user_version=0 with no marker of any kind, so a recorded version cannot be
trusted to describe what a database actually contains -- on 2026-08-10 a stray
application of schema.sql stamped that index to 1 without adding the column
version 1 is defined by. So each migration also carries a predicate saying
whether its effect is already present, and THAT decides whether it runs.
user_version is the fast, honest record; the predicate is the truth.

It also holds the ingest queue and the two duplicate defences that guard it.
Those are not "SQLite access" in the narrow sense, but ingest exists in two
shapes -- the base rig analyses an upload inside the request
(`music_index/ingest.py`), a host with no GPU can only park it
(`musicweb/routes_ingest.py`) -- and the two must reject the same duplicates
and land files under the same kind of name. This module is the only one both
shapes can import: the queued half must work with no indexer on the tree at
all, and the indexer half must not drag in fastapi. Only the ffmpeg shelling
stays per-half, because tool discovery differs between the two hosts.
"""
import hashlib
import logging
import os
import re
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from musicweb import config

log = logging.getLogger(__name__)

# Highest schema version this codebase knows how to run against. Bump it, add
# the file to _MIGRATIONS, and give it a predicate.
CURRENT_SCHEMA_VERSION = 4

# "the version this migration produces" -> (filename, already-applied predicate).
# The predicate must answer "is this migration's effect already in the
# database?" without consulting user_version. Ordered by key.
_MIGRATIONS = {
    1: ('001_track_share.sql', lambda c: 'share' in _columns(c, 'tracks')),
    2: ('002_ingest_queue.sql', lambda c: _table_exists(c, 'ingest_queue')),
    3: ('003_ingest_journal.sql', lambda c: 'uid' in _columns(c, 'ingest_queue')),
    4: ('004_ingest_batches.sql', lambda c: _table_exists(c, 'ingest_items')),
}


def connect(path=None):
    p = Path(path or config.DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con


def _columns(con, table):
    return {r[1] for r in con.execute(f'PRAGMA table_info({table})')}


def _table_exists(con, table):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                       (table,)).fetchone() is not None


def _apply_migration(con, filename):
    """Apply one migration inside an explicit transaction.

    These run against a database holding a real library, so a failure partway
    through must not leave the schema half-migrated. executescript() does not
    wrap the script for us (it commits anything pending first, then runs each
    statement largely as its own unit), so the BEGIN/COMMIT is ours.
    """
    path = config.MIGRATIONS_DIR / filename
    if not path.exists():
        raise RuntimeError(
            f'FATAL: migration {filename!r} not found at {path}. The web app '
            'cannot migrate its database without it -- if deploying music/web '
            'standalone, ship migrations/ with it.')
    try:
        con.executescript('BEGIN;\n' + path.read_text(encoding='utf-8') + '\nCOMMIT;\n')
    except Exception:
        con.rollback()
        raise


def ensure_schema(con):
    """Bring an open connection's database up to CURRENT_SCHEMA_VERSION.

    Idempotent: safe to call on every startup and on every connection, which is
    exactly what con() does.

    A brand-new database gets schema.sql in full -- it already carries every
    migration's end state -- and is stamped current. An existing one walks
    migrations/ in order, applying each whose effect is missing, and only then
    is re-run through schema.sql, which is what picks up purely additive tables
    (that is how peaks and debias landed on the live index).
    """
    schema_sql = config.SCHEMA_PATH.read_text(encoding='utf-8')

    if not _table_exists(con, 'tracks'):
        con.executescript(schema_sql)
        con.execute(f'PRAGMA user_version = {CURRENT_SCHEMA_VERSION}')
        con.commit()
        return

    version = con.execute('PRAGMA user_version').fetchone()[0]
    if version > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f'FATAL: database at {config.DB_PATH} has user_version={version}, '
            f'newer than this app supports (max {CURRENT_SCHEMA_VERSION}). '
            'Upgrade the web app before pointing it at this database.')

    for target in sorted(_MIGRATIONS):
        name, already_applied = _MIGRATIONS[target]
        if not already_applied(con):
            _apply_migration(con, name)
        if not already_applied(con):
            raise RuntimeError(
                f'FATAL: migration {name} ran but its effect is still absent '
                'from the database -- refusing to record it as applied.')

    con.executescript(schema_sql)
    con.execute(f'PRAGMA user_version = {CURRENT_SCHEMA_VERSION}')
    con.commit()


def init(con):
    """Historical name for ensure_schema; the indexer and tests call this."""
    ensure_schema(con)


_local = threading.local()
_schema_lock = threading.Lock()
_schema_ready = False

# Bumped by invalidate(). A sqlite3 connection is bound to an INODE, not to a
# path, so every cached connection keeps reading the file it opened even after
# that file has been renamed away and replaced -- which is exactly how a new
# index ships (install_music_db renames the live music.db to
# music.db.old.<ts> and moves the staged copy in). Without this, /api/reload
# rebuilt the matrices from the unlinked old database and answered 200 with the
# old numbers (MUSIC-10, 2026-08-14).
_generation = 0


def invalidate():
    """Drop every thread's cached connection, so the next con() reopens by PATH.

    Each thread closes its OWN connection, on its next call -- nothing here
    touches a connection another thread may be using. The schema flag is reset
    with it: a file that was swapped underneath us is a different database and
    may be at a different schema version.
    """
    global _generation, _schema_ready
    with _schema_lock:
        _generation += 1
        _schema_ready = False


def generation():
    """Which set of cached connections is current. Bumped by invalidate().

    Read by search.Index, which holds matrices built from a connection and has
    to know when that connection's FILE stopped being the live one.
    """
    return _generation


# (path, dev, inode) as last seen by _check_swapped. `None` until the first
# successful stat, which is never a swap. The PATH is part of it because a swap
# is "this path now names a different file": a run that repoints DB_PATH
# altogether (the eval sweep, the tests) has changed database, not had one
# swapped underneath it, and must not invalidate connections it does not own.
_open_identity = None


def _file_identity(path=None):
    """(st_dev, st_ino) of the database file, or None if it cannot be stat'd.

    Identity, not content: a rename-swap replaces the file the PATH points at
    while every open connection goes on reading the unlinked old inode.
    """
    try:
        st = os.stat(path or config.DB_PATH)
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


def file_state(path=None):
    """A cheap fingerprint of the database AND its -wal: identity plus size and
    mtime of both, or None.

    What it is for (music-2, 2026-08-21): the derived search matrices are built
    once per process and only refresh() replaces them, so a change made by
    ANOTHER process -- `python -m musicweb.drain apply` on the NAS, or a
    publish that renames a new music.db into place -- was invisible to text
    search and /api/similar until somebody POSTed /api/reload, which no runbook
    told anyone to do. The -wal half matters because an in-place apply commits
    there first: on a busy container the main file may not be checkpointed for
    a long time.

    Deliberately not `PRAGMA data_version`: that counter is per CONNECTION, and
    this app has one per thread, so two threads comparing their own counters
    against one shared Index would rebuild it on every alternating request.
    """
    p = Path(path or config.DB_PATH)
    try:
        st = os.stat(p)
    except OSError:
        return None
    out = [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns]
    try:
        wal = os.stat(str(p) + '-wal')
        out += [wal.st_size, wal.st_mtime_ns]
    except OSError:
        out += [0, 0]                 # no -wal: not a WAL database, or idle
    return tuple(out)


def _check_swapped():
    """Notice a database file that was REPLACED, and drop the stale handles.

    MUSIC-10 (2026-08-14) fixed this for /api/reload, which calls invalidate()
    by hand. Nothing else did -- so after `publish_db.py --which music --apply`
    renamed a fresh index into place, every long-lived worker thread went on
    answering browse, facets, audio lookups and search from the deleted inode,
    indefinitely, because anyio reuses the most recently idle thread and the
    dashboard is polled every 2 s (music-2, 2026-08-21). One os.stat per con().
    """
    global _open_identity
    ident = _file_identity()
    if ident is None:
        return
    ident = (str(config.DB_PATH),) + ident
    with _schema_lock:
        previous, _open_identity = _open_identity, ident
    if previous is not None and previous[0] == ident[0] and previous != ident:
        log.warning('the music index at %s has been replaced (a publish, or a '
                    'restore): dropping every cached connection so the next '
                    'read opens the new file', config.DB_PATH)
        invalidate()


def con():
    """One SQLite connection per thread.

    FastAPI dispatches sync endpoints across a threadpool, and a sqlite3
    connection may only be used on the thread that created it -- sharing one
    raises "SQLite objects created in a thread can only be used in that same
    thread" as soon as two requests land on different workers. WAL mode makes
    concurrent readers cheap, so per-thread connections cost nothing.
    """
    global _schema_ready
    _check_swapped()
    c = getattr(_local, 'con', None)
    if c is not None and getattr(_local, 'generation', None) != _generation:
        try:
            c.close()
        except sqlite3.Error:                  # already closed, or mid-failure
            pass
        c = None
    if c is None:
        c = connect()
        # The check and the set are one critical section (MUSIC-11,
        # 2026-08-11): _schema_ready was an unlocked global, so two threads
        # arriving first both ran the migrations and, on the request that
        # upgrades a live database, the loser 500'd with "duplicate column
        # name". The lock is held across init() so the second thread waits for
        # the first to finish rather than racing it.
        with _schema_lock:
            if not _schema_ready:
                init(c)
                _schema_ready = True
        _local.con = c
        _local.generation = _generation
    return c


def backup_to(con, dest):
    """Write a consistent copy of an open database to `dest`. -> Path(dest).

    sqlite3's online backup rather than shutil.copy2, because this database
    runs in WAL mode (schema.sql): a plain file copy taken before a checkpoint
    silently leaves everything committed since it in the -wal file it did not
    copy. Used by anything that wants to SCRIBBLE on the index without touching
    the one that ships -- eval.py --sweep (MUSIC-4, 2026-08-14).
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = sqlite3.connect(dest)
    try:
        con.backup(out)
    finally:
        out.close()
    return dest


def to_blob(vec):
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_blob(blob, dim=None):
    a = np.frombuffer(blob, dtype=np.float32)
    return a.reshape(-1, dim) if dim and a.size != dim else a


def get_meta(con, key, default=None):
    r = con.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
    return r['value'] if r else default


def set_meta(con, key, value):
    con.execute('INSERT INTO meta(key,value) VALUES(?,?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                (key, str(value)))


def load_matrix(con):
    """All track embeddings as (ids, NxD float32 matrix)."""
    rows = con.execute(
        'SELECT id, embedding FROM tracks WHERE embedding IS NOT NULL ORDER BY id'
    ).fetchall()
    if not rows:
        return [], np.zeros((0, 0), dtype=np.float32)
    ids = [r['id'] for r in rows]
    mat = np.stack([np.frombuffer(r['embedding'], dtype=np.float32) for r in rows])
    return ids, mat


def load_window_matrix(con):
    """All window embeddings as (track_ids, NxD matrix) for max-over-windows search."""
    rows = con.execute(
        'SELECT track_id, embedding FROM windows ORDER BY track_id, idx'
    ).fetchall()
    if not rows:
        return np.zeros(0, dtype=np.int64), np.zeros((0, 0), dtype=np.float32)
    tids = np.array([r['track_id'] for r in rows], dtype=np.int64)
    mat = np.stack([np.frombuffer(r['embedding'], dtype=np.float32) for r in rows])
    return tids, mat


def load_debias(con):
    """Source-bias axes as a (k, D) float32 matrix; empty if none stored."""
    rows = con.execute('SELECT vec FROM debias ORDER BY idx').fetchall()
    if not rows:
        return np.zeros((0, 0), dtype=np.float32)
    return np.stack([np.frombuffer(r['vec'], dtype=np.float32) for r in rows])


class PruneRefused(RuntimeError):
    """Too much of the library appears to have vanished to believe the scan."""


def prune_missing(con, present, force=False, max_share=0.2, floor=5):
    """Delete tracks rows whose file is no longer in the library. -> rel_paths.

    Nothing used to remove a row (MUSIC-3, 2026-08-14): `upsert` is keyed
    ON CONFLICT(rel_path), so renaming a cue -- which SPEC.md says is expected,
    a third of the library is named by numeric id or UUID -- indexed the new
    name and left the old row forever. The ghost is not inert: it is in
    load_matrix, so it ranks in search and /api/similar; retag re-scores over
    it, skewing every other track's percentile; and proxies are keyed by id, so
    it even previews correctly. The ONLY place it fails is the last one, the
    companion's "file not found at P:\\Assets\\Music\\... -- is the share
    mounted?", which sends an editor to debug a mount that is fine.

    `present` is every rel_path a FULL sweep saw. windows/tags/axes/peaks go
    with the row (ON DELETE CASCADE in schema.sql) and an ingest_queue row's
    track_id is set NULL, so this is the whole deletion.

    It refuses rather than deletes when the scan looks wrong: an empty scan, or
    more than `max_share` of the library missing at once, is a half-mounted W:
    far more often than it is a real purge, and this is the one operation here
    that destroys embeddings. `force=True` (index_music.py --prune) is the
    override for a genuine bulk removal.

    It lives in the storage layer rather than in index_music.py because the
    indexer is unimportable without torch, and a DELETE that cascades across
    five tables is exactly the thing that needs a test.
    """
    if not con.execute('PRAGMA foreign_keys').fetchone()[0]:
        # without the cascade this would orphan windows/tags/axes/peaks
        raise PruneRefused('refusing to prune with foreign keys disabled')

    present = {str(p) for p in present}
    by_rel = {r['rel_path']: r['id']
              for r in con.execute('SELECT id,rel_path FROM tracks')}
    rows = list(by_rel)
    gone = sorted(r for r in rows if r not in present)
    if not gone:
        return []
    if not present:
        raise PruneRefused(
            'the scan found no audio files at all -- that is a share that is '
            'not mounted, not an empty library. Nothing pruned.')
    if not force and len(gone) > max(floor, int(len(rows) * max_share)):
        raise PruneRefused(
            f'{len(gone)} of {len(rows)} tracks are missing from the scan. '
            'That is usually a partly-mounted share, not a deletion -- check '
            'the root, then re-run with --prune if it really is one.')
    con.executemany('DELETE FROM tracks WHERE rel_path=?', [(g,) for g in gone])
    con.commit()
    # The id is now free, and SQLite hands the next insert max(rowid)+1: leaving
    # the proxy behind is how an editor ends up previewing a deleted cue under
    # a new track's name (music-4, 2026-08-21). Deletion is what frees the id,
    # so deletion is what removes the file.
    for rel in gone:
        config.drop_proxy(by_rel[rel])
    return gone


def save_debias(con, dirs):
    con.execute('DELETE FROM debias')
    if dirs is not None and dirs.size:
        con.executemany('INSERT INTO debias(idx,vec) VALUES(?,?)',
                        [(i, to_blob(d)) for i, d in enumerate(dirs)])
    con.commit()


# ------------------------------------------------------------------ ingest
# Everything below is shared by the inline (base rig) and queued (no GPU)
# ingest paths -- see the module docstring for why it lives here.

PENDING, DONE, FAILED = 'pending', 'done', 'failed'
QUEUE_STATES = (PENDING, DONE, FAILED)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def content_hash(path, chunk=1 << 20):
    h = hashlib.blake2b(digest_size=16)
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def stream_to(src, dest, chunk=1 << 20):
    """Copy an upload's file object into `dest` in chunks. -> Path(dest).

    Both ingest halves land a file this way (MUSIC-9, 2026-08-14) instead of
    reading the upload into a `bytes` first: Starlette has already spooled
    anything over 1 MB to disk, so `await up.read()` bought a second full copy
    of a 60 MB wav in the heap of the process that also serves the fleet
    dashboard, and a third pass over the file.

    seek(0) because a spooled temp file that was just written sits at its end;
    a reader without one (a test stub) is taken as already positioned.
    """
    try:
        src.seek(0)
    except (AttributeError, OSError, ValueError):
        pass
    dest = Path(dest)
    with open(dest, 'wb') as fh:
        shutil.copyfileobj(src, fh, chunk)
    return dest


def safe_upload_name(name):
    """A browser-supplied filename reduced to something safe to write.

    Basename only, and every character Windows forbids in a name replaced --
    including the separators, so nothing that arrives here can still be read as
    a path. `unique_dest` re-validates through safe_join regardless.

    The basename split is done on BOTH separators regardless of host OS, not
    with os.path.basename: this app is mounted in the dashboard's Linux
    container, but the browser supplying the filename is very often on
    Windows (CLAUDE.md: "POSIX behaviour is the deployed reality"), so a
    dropped '..\\..\\evil.wav' has no '/' in it at all -- os.path.basename on
    POSIX does not treat backslash as a separator and returns the string
    unchanged, and the char-replace below then turned each backslash into an
    underscore ('.._.._evil.wav') instead of stripping the traversal like it
    does on Windows.
    """
    name = re.split(r'[\\/]+', str(name or 'untitled'))[-1]
    name = ''.join('_' if c in '<>:"/\\|?*' else c for c in name).strip()
    return name or 'untitled'


def unique_dest(name, root=None):
    """Collision-free path directly under the share root (the library is flat).

    Joined through safe_join, not '/', so an upload filename that survived
    safe_upload_name and still looks like a path ("..", "C:") cannot land the
    file outside the library.
    """
    root = config.share_root() if root is None else root
    stem, ext = os.path.splitext(name)
    cand, i = name, 2
    while config.safe_join(root, cand).exists():
        cand = f'{stem} ({i}){ext}'
        i += 1
    return config.safe_join(root, cand)


def norm_stem(name):
    stem = os.path.splitext(os.path.basename(name))[0].lower()
    stem = re.sub(r'^es[_ ]', '', stem)
    stem = re.sub(r'[\(\[]\d+[\)\]]', ' ', stem)          # (2)
    stem = re.sub(r'[^a-z0-9]+', '', stem)
    return stem


def find_reencode(con, name, duration, tol=2.0):
    """A track already held that is the same recording as this file, or None.

    Content hashing cannot see this: transcoding an .ogg to mp3 changes every
    byte, so a re-encode of a track already held sails past the hash check.
    Matching the normalised filename plus a near-identical duration catches it,
    which matters because .ogg previews sitting beside their masters are
    exactly what gets dragged in by accident.

    Queued-but-not-yet-analysed uploads are checked too, or dropping the same
    file twice in a row would queue it twice -- there is no `tracks` row to
    match against until an indexer run has been past. Rows in state `failed`
    are deliberately NOT matched: their file is still sitting in the library,
    and re-dropping it is the obvious way an operator retries.
    """
    if not duration:
        return None
    key = norm_stem(name)
    if not key:
        return None
    for r in con.execute(
            'SELECT rel_path, filename, duration FROM tracks '
            'WHERE duration BETWEEN ? AND ?', (duration - tol, duration + tol)):
        if norm_stem(r['filename']) == key:
            return r['rel_path']
    if not _table_exists(con, 'ingest_queue'):
        return None
    for r in con.execute(
            'SELECT rel_path, orig_name FROM ingest_queue '
            'WHERE state IN (?,?) AND duration BETWEEN ? AND ?',
            (PENDING, DONE, duration - tol, duration + tol)):
        if norm_stem(r['orig_name']) == key or norm_stem(r['rel_path']) == key:
            return r['rel_path']
    return None


def find_content_duplicate(con, path, digest=None):
    """rel_path of a library file with byte-identical content, or None.

    Identical content implies an identical byte count, so only the rows whose
    `bytes` already match are opened -- one or two file reads instead of 376,
    backed by idx_tracks_bytes.

    BOTH halves use this now (MUSIC-7, 2026-08-14). The base rig used to hash
    every file under the share root instead (`music_index.ingest.
    library_hashes`), on the premise that W: is local: it is not, it is an SMB
    mount of the same NAS, so the base rig was paying the 9.5 GB read this
    exists to avoid -- on every dropped file, before ffprobe was even consulted.

    Files sitting in the library that no row knows about are therefore missed
    here, and caught by the sweep that indexes them.
    """
    path = Path(path)
    return find_content_duplicate_by_digest(
        con, digest or content_hash(path), path.stat().st_size)


def find_content_duplicate_by_digest(con, digest, size):
    """The same defence, for a file this host does not have (2026-08-18).

    Dashboard music ingest hashes on the EDITOR'S machine and sends the digest
    ahead of the bytes -- the pre-check has to answer "already in the library?"
    while the file is still on a laptop. The digest is the same blake2b-16
    `content_hash` computes, and the candidate set is the same one:
    rows whose byte count already matches, which the server can still open
    because the share is mounted here for /api/audio.

    Split out of find_content_duplicate rather than reimplemented, so the two
    entry points cannot drift into two answers about the same file.
    """
    if not digest or not size:
        return None
    for r in con.execute('SELECT share, rel_path FROM tracks WHERE bytes=?', (size,)):
        try:
            other = config.resolve_path(r['share'] or config.SHARE, r['rel_path'])
        except (config.PathTraversalError, config.UnknownShareError):
            continue
        try:
            if other.is_file() and content_hash(other) == digest:
                return r['rel_path']
        except OSError:
            continue
    if not _table_exists(con, 'ingest_queue'):
        return None
    # an upload already queued has no tracks row yet, and its file is real
    r = con.execute('SELECT rel_path FROM ingest_queue WHERE content_hash=? '
                    'AND state IN (?,?)', (digest, PENDING, DONE)).fetchone()
    return r['rel_path'] if r else None


def queue_add(con, rel_path, orig_name, share=config.SHARE, bytes_=None,
              duration=None, digest=None, transcoded=False):
    """Record a landed upload as `pending`. -> the queue row id.

    Upserts on rel_path so re-using a name whose previous row failed (the file
    was removed by hand, the operator dropped it again) resets that row to
    pending rather than raising on the UNIQUE.

    `uid` is re-minted by that upsert, deliberately (migrations/003): the reset
    row is a DIFFERENT upload, and a result bundle drained from the previous one
    must not be able to close it -- it would attach some other file's embedding
    to these bytes and report the upload as indexed.
    """
    con.execute("""
        INSERT INTO ingest_queue(uid,share,rel_path,orig_name,bytes,duration,
                                 content_hash,transcoded,state,error,attempts,
                                 track_id,queued_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,NULL,0,NULL,?,?)
        ON CONFLICT(rel_path) DO UPDATE SET
            uid=excluded.uid,
            share=excluded.share, orig_name=excluded.orig_name,
            bytes=excluded.bytes, duration=excluded.duration,
            content_hash=excluded.content_hash,
            transcoded=excluded.transcoded,
            state=excluded.state, error=NULL, attempts=0, track_id=NULL,
            queued_at=excluded.queued_at, updated_at=excluded.updated_at
    """, (uuid.uuid4().hex, share, rel_path, orig_name, bytes_, duration, digest,
          1 if transcoded else 0, PENDING, _now(), _now()))
    con.commit()
    return con.execute('SELECT id FROM ingest_queue WHERE rel_path=?',
                       (rel_path,)).fetchone()['id']


def queue_pending(con, limit=0, include_failed=False):
    """Rows for an indexer run to work through, oldest first.

    `failed` is opt-in (`--retry-failed`): a file that cannot be analysed would
    otherwise be re-attempted by every run forever and the reason never read.
    """
    states = (PENDING, FAILED) if include_failed else (PENDING,)
    ph = ','.join('?' * len(states))
    sql = (f'SELECT * FROM ingest_queue WHERE state IN ({ph}) ORDER BY id')
    if limit:
        sql += ' LIMIT %d' % int(limit)
    return con.execute(sql, states).fetchall()


def queue_mark_done(con, queue_id, track_id):
    con.execute('UPDATE ingest_queue SET state=?, error=NULL, track_id=?, '
                'attempts=attempts+1, updated_at=? WHERE id=?',
                (DONE, track_id, _now(), queue_id))
    con.commit()


def queue_mark_failed(con, queue_id, error):
    """Park a row with the reason. Nothing retries it without being asked to."""
    con.execute('UPDATE ingest_queue SET state=?, error=?, attempts=attempts+1, '
                'updated_at=? WHERE id=?', (FAILED, str(error)[:2000], _now(), queue_id))
    con.commit()


def queue_counts(con):
    """{'pending': n, 'done': n, 'failed': n} -- every key present."""
    out = {s: 0 for s in QUEUE_STATES}
    if not _table_exists(con, 'ingest_queue'):
        return out
    for r in con.execute('SELECT state, COUNT(*) c FROM ingest_queue GROUP BY state'):
        out[r['state']] = r['c']
    return out


def queue_rows(con, state=None, limit=50):
    if not _table_exists(con, 'ingest_queue'):
        return []
    if state:
        return con.execute('SELECT * FROM ingest_queue WHERE state=? '
                           'ORDER BY id DESC LIMIT ?', (state, limit)).fetchall()
    return con.execute('SELECT * FROM ingest_queue ORDER BY id DESC LIMIT ?',
                       (limit,)).fetchall()


def queue_reconcile(con):
    """Close pending rows whose file has since been indexed by some other run.

    A queued file lives in the library like any other, so a plain
    `index_music.py` sweep picks it up by rglob and indexes it without ever
    looking at this table -- leaving a row that says `pending` about a track
    that is already searchable. Called at the top of a drain and at the end of
    a full run. -> how many rows it closed.
    """
    if not _table_exists(con, 'ingest_queue'):
        return 0
    rows = con.execute(
        'SELECT q.id, t.id tid FROM ingest_queue q JOIN tracks t '
        'ON t.rel_path = q.rel_path AND t.embedding IS NOT NULL '
        'WHERE q.state=?', (PENDING,)).fetchall()
    for r in rows:
        queue_mark_done(con, r['id'], r['tid'])
    return len(rows)


def percentile_ranks(values):
    """Percentile rank in [0,100] of each value within the array.

    Ties get the same rank. Used because raw CLAP similarities are poorly
    calibrated in absolute terms but reliably ordered within a library.
    """
    v = np.asarray(values, dtype=np.float64)
    n = v.size
    if n == 0:
        return np.zeros(0)
    if n == 1:
        return np.array([50.0])
    order = v.argsort()
    ranks = np.empty(n, dtype=np.float64)
    ranks[order] = np.arange(n, dtype=np.float64)
    # average ranks across ties so identical scores get identical percentiles
    uniq, inv, counts = np.unique(v, return_inverse=True, return_counts=True)
    sums = np.zeros(uniq.size)
    np.add.at(sums, inv, ranks)
    ranks = (sums / counts)[inv]
    return ranks / (n - 1) * 100.0
