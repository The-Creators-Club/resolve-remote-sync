"""The queue drain handoff, without a lost-write window.

2026-08-17, COMMERCIAL_READINESS.md item 14. The NAS container has no GPU, so a
drag-and-drop upload lands in the share and gets a `pending` journal row; a base
rig with the RTX card does the analysis. Until now the two met by copying the
whole `music.db` to the base rig, draining it there, and copying the file back
(`music/web/DEPLOY.md`, "Draining the NAS ingest queue"). A file copy has no
merge, so every upload an editor queued while the operator held the copy was
overwritten by the push -- minutes to hours of lost writes per drain, invisible
afterwards, with the only surviving evidence in `music.db.old.<ts>`.

Nothing is pushed as a file any more. The base rig exports the ANALYSED RESULTS
of the rows it drained -- embeddings, windows, tags, axes, peaks -- into a small
bundle, and `apply_bundle` merges that into the live index in place, naming only
the journal rows it drained. A row queued during the drain is not named, is not
touched, and is still `pending` when the next drain looks. That is the whole
property: **the set of rows a drain can affect is fixed at the moment it starts,
and is a set of ids, not "the file".**

Three things make it safe rather than merely append-only:

  identity   `ingest_queue.uid` (migrations/003), minted per accepted upload and
             re-minted when a row is reset to pending. `id` is a per-database
             rowid and means nothing in the other copy; `rel_path` is reused.

  agreement  a row is only closed if the live journal still says the same
             rel_path and the same content_hash. If the file at that path
             changed between the pull and the push, the embedding in the bundle
             describes different audio, and attaching it would be a silent
             mis-index -- worse than the upload staying pending.

  atomicity  one transaction for the whole bundle, and each row's journal entry
             is marked `done` only after its track row has been written AND read
             back. A failure anywhere rolls the lot back, and the bundle can
             simply be applied again: every write is keyed and idempotent.

The bundle is itself a SQLite file. It carries float32 BLOBs (a 512-d embedding
per track, twelve per-window vectors, a waveform), which JSON would base64 and
inflate, and it can be inspected with the same tooling as the index. Applying it
needs nothing but the standard library -- no numpy, no torch -- so it can run
inside the dashboard container, on the NAS host, or against a pulled-down copy.

    # base rig, after `index_music.py --queue --db <pulled copy>`
    python index_music.py --queue --db nas-index/music.db --export-drain drain.db

    # wherever the LIVE index is
    python -m musicweb.drain apply drain.db --db /path/to/music.db
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BUNDLE_VERSION = 1

# Every tracks column except `id`, which is a per-database rowid and is exactly
# what must NOT travel: the same track is a different id in the two copies.
TRACK_COLS = (
    'share', 'rel_path', 'filename', 'ext', 'bytes', 'duration', 'samplerate',
    'channels', 'codec', 'bpm', 'music_key', 'key_conf', 'lufs', 'peak_db',
    'embedding', 'dim', 'file_hash', 'model', 'analyzed_at',
)

PENDING, DONE, FAILED = 'pending', 'done', 'failed'

_BUNDLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS bundle_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
-- One row per journal entry this drain analysed. `uid` is the key the live
-- index is matched on; `content_hash` is copied from the journal row so the
-- apply side can refuse a path whose bytes have changed since the pull.
CREATE TABLE IF NOT EXISTS bundle_tracks (
    uid          TEXT PRIMARY KEY,
    content_hash TEXT,
    %s
);
-- Everything below is keyed by rel_path, not by track id, for the same reason
-- TRACK_COLS omits it.
CREATE TABLE IF NOT EXISTS bundle_windows (
    rel_path  TEXT NOT NULL,
    idx       INTEGER NOT NULL,
    t0        REAL,
    t1        REAL,
    embedding BLOB,
    PRIMARY KEY (rel_path, idx)
);
CREATE TABLE IF NOT EXISTS bundle_tags (
    rel_path TEXT NOT NULL,
    category TEXT NOT NULL,
    label    TEXT NOT NULL,
    score    REAL,
    pct      REAL,
    rank     INTEGER,
    PRIMARY KEY (rel_path, category, label)
);
CREATE TABLE IF NOT EXISTS bundle_axes (
    rel_path TEXT NOT NULL,
    axis     TEXT NOT NULL,
    raw      REAL,
    pct      REAL,
    PRIMARY KEY (rel_path, axis)
);
CREATE TABLE IF NOT EXISTS bundle_peaks (
    rel_path TEXT PRIMARY KEY,
    n        INTEGER,
    data     BLOB
);
CREATE TABLE IF NOT EXISTS bundle_debias (
    idx INTEGER PRIMARY KEY,
    vec BLOB
);
-- One row per journal entry this drain PARKED (music-3, 2026-08-21). The
-- failure used to exist only in the pulled copy, so on the live index the row
-- stayed `pending` forever: the editor's panel showed it waiting, the
-- duplicate defences went on treating the file as held (so a fixed re-export
-- was refused as a duplicate), and every subsequent drain decoded the same
-- broken file again. `error` is what index_music wrote there, carried across
-- verbatim so the reason is readable where the editor is looking.
CREATE TABLE IF NOT EXISTS bundle_failures (
    uid          TEXT PRIMARY KEY,
    content_hash TEXT,
    rel_path     TEXT,
    error        TEXT
);
""" % ',\n    '.join(TRACK_COLS)
# The track columns above are declared with NO TYPE on purpose. A transport
# table must hand back exactly what it was given, and SQLite type affinity is a
# conversion, not a check: declaring `duration TEXT` would store 120.0 as the
# string '120.0'. No declared type means BLOB affinity -- values are stored as
# they arrive, integers as integers and NULLs as NULLs.


class BundleError(RuntimeError):
    """The bundle, or the index it is being applied to, is not what it claims."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _connect(path):
    con = sqlite3.connect(str(path), timeout=30)
    con.row_factory = sqlite3.Row
    return con


def _has_journal(con):
    """True if this database's ingest_queue carries `uid` (migrations/003)."""
    try:
        cols = {r[1] for r in con.execute('PRAGMA table_info(ingest_queue)')}
    except sqlite3.DatabaseError:
        return False
    return 'uid' in cols


def _require_journal(con, what):
    if not _has_journal(con):
        version = con.execute('PRAGMA user_version').fetchone()[0]
        raise BundleError(
            f'{what} has no ingest_queue.uid column (user_version={version}). '
            'It predates the ingest journal (music/web/migrations/003). Start '
            'the app against it once -- ensure_schema applies migrations on '
            'every connection -- or deploy the dashboard before draining.')


# --------------------------------------------------------------------- export


def export_bundle(con, uids, out_path, include_rescore=True, source=None,
                  failures=()):
    """Write the analysis of `uids` to a bundle file. -> a summary dict.

    `uids` is what the drain actually closed, in order. A uid whose track row is
    missing or has no embedding is REPORTED, not written: the point of the
    bundle is that everything in it is finished work, so that the apply side can
    treat a present row as authoritative.

    `failures` is the other half of the same fact: (uid, error) pairs for the
    rows this drain PARKED (music-3, 2026-08-21). They carry no analysis by
    definition, so they travel in their own table and close the live journal
    row as `failed` rather than `done`. Optional, and the table is read with
    "if it is there" on the apply side, so a bundle written by an older base rig
    still applies -- which is why BUNDLE_VERSION is unchanged: this is purely
    additive in both directions.

    `include_rescore` carries the tags and axes of the WHOLE library plus the
    source-bias axes, because both are library-relative: `index_music.retag`
    re-scores every track whenever one is added, and dropping that would leave
    the live index's percentiles describing a library one track smaller. It is
    small -- a few hundred rows per track, no blobs except the debias vectors.
    """
    out_path = Path(out_path)
    if out_path.exists():
        # Never append to an existing bundle: it would carry a previous drain's
        # uids, which the apply side would then try (and correctly refuse) to
        # close a second time, hiding this drain's real result in the noise.
        raise BundleError(f'{out_path} already exists; refusing to overwrite a bundle')

    _require_journal(con, 'the index being drained')
    out = _connect(out_path)
    try:
        out.executescript(_BUNDLE_SCHEMA)
        written, missing = [], []
        cols = ','.join(TRACK_COLS)
        for uid in uids:
            q = con.execute(
                'SELECT uid, rel_path, content_hash FROM ingest_queue WHERE uid=?',
                (uid,)).fetchone()
            if q is None:
                missing.append((uid, 'no journal row'))
                continue
            t = con.execute(
                f'SELECT id,{cols} FROM tracks WHERE rel_path=?',
                (q['rel_path'],)).fetchone()
            if t is None or t['embedding'] is None:
                missing.append((uid, 'not analysed'))
                continue
            out.execute(
                'INSERT INTO bundle_tracks(uid,content_hash,%s) VALUES(%s)'
                % (cols, ','.join('?' * (len(TRACK_COLS) + 2))),
                (uid, q['content_hash']) + tuple(t[c] for c in TRACK_COLS))
            _copy_children(con, out, t['id'], t['rel_path'])
            written.append(uid)

        parked = _copy_failures(con, out, failures)

        if include_rescore:
            _copy_rescore(con, out)

        out.executemany('INSERT OR REPLACE INTO bundle_meta(key,value) VALUES(?,?)', [
            ('bundle_version', str(BUNDLE_VERSION)),
            ('created_at', _now()),
            ('source', str(source or '')),
            ('tracks', str(len(written))),
            ('failures', str(len(parked))),
            ('rescore', '1' if include_rescore else '0'),
        ])
        out.commit()
    except Exception:
        out.close()
        # A half-written bundle is worse than none: it looks applicable.
        out_path.unlink(missing_ok=True)
        raise
    out.close()
    return {'path': str(out_path), 'tracks': len(written), 'uids': written,
            'skipped': missing, 'failures': parked,
            'rescore': bool(include_rescore)}


def _copy_failures(con, out, failures):
    """Write the parked rows to the bundle. -> the uids written.

    The journal row is looked up so the apply side can make the SAME agreement
    checks a successful row gets: a path whose bytes changed since the pull has
    not been shown to be broken, and must stay pending for the next drain.
    """
    parked = []
    for uid, error in failures or ():
        q = con.execute('SELECT rel_path, content_hash FROM ingest_queue '
                        'WHERE uid=?', (uid,)).fetchone()
        if q is None:
            continue
        out.execute('INSERT OR REPLACE INTO bundle_failures'
                    '(uid,content_hash,rel_path,error) VALUES(?,?,?,?)',
                    (uid, q['content_hash'], q['rel_path'], str(error)[:2000]))
        parked.append(uid)
    return parked


def _copy_children(con, out, track_id, rel_path):
    out.executemany(
        'INSERT OR REPLACE INTO bundle_windows(rel_path,idx,t0,t1,embedding) '
        'VALUES(?,?,?,?,?)',
        [(rel_path, r['idx'], r['t0'], r['t1'], r['embedding'])
         for r in con.execute('SELECT idx,t0,t1,embedding FROM windows '
                              'WHERE track_id=?', (track_id,))])
    peak = con.execute('SELECT n,data FROM peaks WHERE track_id=?',
                       (track_id,)).fetchone()
    if peak is not None:
        out.execute('INSERT OR REPLACE INTO bundle_peaks(rel_path,n,data) '
                    'VALUES(?,?,?)', (rel_path, peak['n'], peak['data']))


def _copy_rescore(con, out):
    """Tags, axes and the source-bias directions for the whole library."""
    out.executemany(
        'INSERT OR REPLACE INTO bundle_tags(rel_path,category,label,score,pct,rank) '
        'VALUES(?,?,?,?,?,?)',
        [(r['rel_path'], r['category'], r['label'], r['score'], r['pct'], r['rank'])
         for r in con.execute(
             'SELECT t.rel_path, g.category, g.label, g.score, g.pct, g.rank '
             'FROM tags g JOIN tracks t ON t.id = g.track_id')])
    out.executemany(
        'INSERT OR REPLACE INTO bundle_axes(rel_path,axis,raw,pct) VALUES(?,?,?,?)',
        [(r['rel_path'], r['axis'], r['raw'], r['pct'])
         for r in con.execute(
             'SELECT t.rel_path, a.axis, a.raw, a.pct '
             'FROM axes a JOIN tracks t ON t.id = a.track_id')])
    out.executemany(
        'INSERT OR REPLACE INTO bundle_debias(idx,vec) VALUES(?,?)',
        [(r['idx'], r['vec'])
         for r in con.execute('SELECT idx,vec FROM debias ORDER BY idx')])


# ---------------------------------------------------------------------- apply


def read_meta(bundle_path):
    """The bundle's metadata as a dict. Raises if it is not a bundle at all."""
    b = _connect(bundle_path)
    try:
        rows = b.execute('SELECT key,value FROM bundle_meta').fetchall()
    except sqlite3.DatabaseError as exc:
        raise BundleError(f'{bundle_path} is not a drain bundle: {exc}') from None
    finally:
        b.close()
    meta = {r['key']: r['value'] for r in rows}
    if meta.get('bundle_version') != str(BUNDLE_VERSION):
        raise BundleError(
            f'{bundle_path} is bundle_version {meta.get("bundle_version")!r}, '
            f'this code writes and reads {BUNDLE_VERSION}')
    return meta


def apply_bundle(con, bundle_path, apply_rescore=True):
    """Merge a drain bundle into the live index. -> a report dict.

    ONE transaction. Every row is keyed and every write is an upsert, so a
    bundle can be applied twice with no second effect and a failed apply leaves
    the index exactly as it was -- including the journal, so the rows are still
    pending and the same bundle still closes them.

    Rows the live journal disagrees with are SKIPPED and named in the report;
    they are never forced, because every disagreement means the analysis in the
    bundle is about a different file than the one at that path now.
    """
    meta = read_meta(bundle_path)
    _require_journal(con, 'the index being written')

    b = _connect(bundle_path)
    report = {'applied': [], 'skipped': [], 'failed': [], 'rescored_tracks': 0,
              'bundle': dict(meta)}
    try:
        cols = ','.join(TRACK_COLS)
        placeholders = ','.join('?' * len(TRACK_COLS))
        updates = ','.join(f'{c}=excluded.{c}' for c in TRACK_COLS
                           if c != 'rel_path')
        created = []
        for row in b.execute(f'SELECT uid,content_hash,{cols} FROM bundle_tracks'):
            reason = _reject_reason(con, row)
            if reason:
                report['skipped'].append((row['uid'], reason))
                continue
            # A row created here takes max(rowid)+1 -- the id of the highest
            # track ever deleted from this index, whose preview proxy may still
            # be on disk (music-4, 2026-08-21). Collected now, dropped after
            # the commit: the filesystem has no part in this transaction.
            fresh = con.execute('SELECT id FROM tracks WHERE rel_path=?',
                                (row['rel_path'],)).fetchone() is None
            con.execute(
                f'INSERT INTO tracks({cols}) VALUES({placeholders}) '
                f'ON CONFLICT(rel_path) DO UPDATE SET {updates}',
                tuple(row[c] for c in TRACK_COLS))
            # Read back inside the transaction: the journal row is closed on the
            # strength of a track row that exists and carries an embedding of
            # the declared width, not on the strength of the INSERT returning.
            live = con.execute(
                'SELECT id,dim,length(embedding) len FROM tracks WHERE rel_path=?',
                (row['rel_path'],)).fetchone()
            if live is None or not live['dim'] or live['len'] != live['dim'] * 4:
                report['skipped'].append((row['uid'], 'write not verified'))
                continue
            _apply_children(con, b, live['id'], row['rel_path'])
            con.execute(
                'UPDATE ingest_queue SET state=?, error=NULL, track_id=?, '
                'attempts=attempts+1, updated_at=? WHERE uid=?',
                (DONE, live['id'], _now(), row['uid']))
            if fresh:
                created.append(live['id'])
            report['applied'].append(row['uid'])

        _apply_failures(con, b, report)

        if apply_rescore and meta.get('rescore') == '1':
            # Imported HERE, not at module scope, and that is load-bearing:
            # this module's whole point is that it can be run by whatever
            # python3 the NAS host happens to have (`music/web/DEPLOY.md`
            # applies a bundle over SSH), and `musicweb.rescore` imports numpy
            # for the half of it that COMPUTES scores -- which this path never
            # reaches. A top-level import would turn a stdlib-only apply into
            # one that needs numpy on the NAS host.
            from musicweb import rescore
            report['rescored_tracks'] = rescore.apply_bundle_rows(con, b)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        b.close()

    # After the commit, and never fatal (music-4, 2026-08-21). `config` is
    # stdlib-only -- paths and env vars -- so importing it here keeps this
    # module runnable by whatever python3 the NAS host happens to have, which
    # is the whole reason `rescore` is imported lazily above too.
    from musicweb import config
    for track_id in created:
        config.drop_proxy(track_id)
    return report


def _apply_failures(con, b, report):
    """Park on the LIVE journal the rows this drain could not analyse.

    music-3, 2026-08-21. Without this the failure existed only in the pulled
    copy: the live row stayed `pending`, so the ingest panel showed it waiting
    forever, `find_reencode`/`find_content_duplicate_by_digest` went on treating
    the file as a held track (a fixed re-export of it was refused as a
    duplicate), and every later drain decoded the same broken file again.

    Same agreement checks as a successful row, and one more: a row that is
    already `done` is never forced back to failed. Older bundles have no such
    table and simply have no failures to apply.
    """
    try:
        rows = b.execute('SELECT uid,content_hash,rel_path,error '
                         'FROM bundle_failures').fetchall()
    except sqlite3.DatabaseError:
        return                       # a bundle written before music-3
    for row in rows:
        reason = _reject_reason(con, row)
        if reason:
            report['skipped'].append((row['uid'], reason))
            continue
        con.execute(
            'UPDATE ingest_queue SET state=?, error=?, attempts=attempts+1, '
            'updated_at=? WHERE uid=?',
            (FAILED, str(row['error'] or 'the drain could not analyse this '
                         'file')[:2000], _now(), row['uid']))
        report['failed'].append(row['uid'])


def _reject_reason(con, row):
    """Why this bundle row must not be applied, or None.

    The live journal is the authority on all three questions -- it is the copy
    editors have been writing to while the drain ran.
    """
    q = con.execute('SELECT uid,rel_path,content_hash,state FROM ingest_queue '
                    'WHERE uid=?', (row['uid'],)).fetchone()
    if q is None:
        return 'no journal row with this uid (wrong index, or the row was reset)'
    if q['state'] == DONE:
        return 'already done'
    if q['rel_path'] != row['rel_path']:
        return f'journal now says {q["rel_path"]!r}, bundle says {row["rel_path"]!r}'
    if q['content_hash'] and row['content_hash'] and q['content_hash'] != row['content_hash']:
        return 'content_hash changed since the drain -- the file at this path is not what was analysed'
    return None


def _apply_children(con, b, track_id, rel_path):
    # DELETE-then-INSERT rather than upsert: the window count depends on the
    # track's duration, so a re-analysis with fewer windows must not leave the
    # tail of the previous one behind ranking in search.
    con.execute('DELETE FROM windows WHERE track_id=?', (track_id,))
    con.executemany(
        'INSERT INTO windows(track_id,idx,t0,t1,embedding) VALUES(?,?,?,?,?)',
        [(track_id, r['idx'], r['t0'], r['t1'], r['embedding'])
         for r in b.execute('SELECT idx,t0,t1,embedding FROM bundle_windows '
                            'WHERE rel_path=? ORDER BY idx', (rel_path,))])
    peak = b.execute('SELECT n,data FROM bundle_peaks WHERE rel_path=?',
                     (rel_path,)).fetchone()
    if peak is not None:
        con.execute('INSERT OR REPLACE INTO peaks(track_id,n,data) VALUES(?,?,?)',
                    (track_id, peak['n'], peak['data']))


# The library-wide tags/axes/debias a bundle carries are applied by
# `rescore.apply_bundle_rows` (moved there 2026-08-18, MUSIC_INGEST_PLAN.md
# step 2, unchanged). It sits beside the code that COMPUTES the same rows now
# that the container can: this file is about moving finished work between two
# copies of the index, and that is the one thing both paths share.


# ------------------------------------------------------------------------ cli


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='python -m musicweb.drain',
        description='Apply or inspect an ingest drain bundle (see the module '
                    'docstring and music/web/DEPLOY.md).')
    sub = ap.add_subparsers(dest='command', required=True)

    p_apply = sub.add_parser('apply', help='merge a bundle into a live index')
    p_apply.add_argument('bundle')
    p_apply.add_argument('--db', default='', help='the index to write '
                         '(default: MUSIC_DB_PATH, then the packaged data root)')
    p_apply.add_argument('--no-rescore', action='store_true',
                         help='keep the existing library-wide tags/axes')

    p_show = sub.add_parser('inspect', help='what a bundle contains')
    p_show.add_argument('bundle')

    args = ap.parse_args(argv)

    if args.command == 'inspect':
        meta = read_meta(args.bundle)
        b = _connect(args.bundle)
        n = b.execute('SELECT COUNT(*) c FROM bundle_tracks').fetchone()['c']
        rows = b.execute('SELECT uid,rel_path FROM bundle_tracks ORDER BY rel_path').fetchall()
        b.close()
        for key in sorted(meta):
            print(f'{key}: {meta[key]}')
        print(f'{n} track(s):')
        for r in rows:
            print(f'  {r["uid"]}  {r["rel_path"]}')
        return 0

    db_path = args.db or os.environ.get('MUSIC_DB_PATH')
    if not db_path:
        # Deliberately no fall-through to a packaged default: applying a bundle
        # to the wrong index closes journal rows that live somewhere else.
        from musicweb import config
        db_path = str(config.DB_PATH)
    if not Path(db_path).is_file():
        print(f'no index at {db_path}', file=sys.stderr)
        return 2

    con = _connect(db_path)
    con.execute('PRAGMA foreign_keys=ON')
    try:
        report = apply_bundle(con, args.bundle, apply_rescore=not args.no_rescore)
    except BundleError as exc:
        print(f'drain apply: {exc}', file=sys.stderr)
        return 2
    finally:
        con.close()

    print(f'applied {len(report["applied"])} track(s) to {db_path}')
    if report['rescored_tracks']:
        print(f'  re-scored {report["rescored_tracks"]} track(s) library-wide')
    if report['failed']:
        # music-3, 2026-08-21: these are the rows the base rig could not
        # analyse. They are now parked HERE too, which is what stops the
        # editor's panel counting them as still waiting.
        print(f'  parked {len(report["failed"])} row(s) as failed; the ingest '
              'panel shows the reason. Nothing retries them on their own.')
    for uid, reason in report['skipped']:
        print(f'  SKIPPED {uid}: {reason}')
    if report['applied'] or report['failed']:
        # music-2, 2026-08-21: this process writes the file directly, so the
        # app's cached connections and its search matrices are what have to
        # notice. They do, within a couple of seconds, since musicweb watches
        # the file. An older deployment does not: say so rather than leaving
        # the operator wondering why the new cues are unsearchable.
        print('  the live app picks this up on its next search. If it is '
              'running a musicweb older than 2026-08-21, POST '
              '/music/api/reload or restart the dashboard container.')
    # Non-zero when anything was refused: a scheduled apply must be visibly
    # partial rather than quietly so.
    return 1 if report['skipped'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
