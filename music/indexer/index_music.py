"""Index the music library: decode -> CLAP embed -> DSP features -> tag -> SQLite.

    python index_music.py                 # index new/changed files, then tag
    python index_music.py --retag         # re-score from stored embeddings only
    python index_music.py --force         # re-analyse everything
    python index_music.py --limit 20      # try a handful first
    python index_music.py --no-prune      # keep rows whose file has gone
    python index_music.py --queue         # analyse what the web app queued
    python index_music.py --queue-status  # what is waiting, and what failed
    python index_music.py --db <path>     # work on another copy of the index

Resumable: interrupt it and re-run; completed tracks are skipped by hash.

A full sweep also PRUNES: a row whose file is no longer under the root is
deleted, because a renamed cue otherwise survives as a ghost that ranks in
search, previews correctly off its id-keyed proxy, skews every other track's
percentile, and only fails at the very end when the companion cannot find the
old name on P: (MUSIC-3, 2026-08-14). It refuses to prune in bulk unless told
to -- see --prune / --no-prune.

`--queue` is the base-rig end of port step 7: a web app with no GPU accepts a
drag-and-drop upload, lands the file in the share and writes a `pending` row,
and this drains it. It is the same analysis a full sweep does, just driven off
the queue instead of a directory walk, so the two never disagree.

Those `pending` rows are written into the NAS's copy of the index, not this
one, so a drain that means anything is `--db <a copy pulled down from the NAS>`
followed by pushing it back: `music/web/DEPLOY.md`, "Draining the NAS ingest
queue".
"""
import argparse
import collections
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# music_index must come first: importing it is what puts the shared web tree
# (musicweb.db, web/schema.sql) on sys.path.
from music_index import audio, config, features, tagging, vocab
from musicweb import db


def iter_files(root: Path):
    for p in sorted(root.rglob('*')):
        if not p.is_file():
            continue
        if p.suffix.lower() not in config.AUDIO_EXTS:
            continue
        rel = p.relative_to(root)
        if any(part in config.EXCLUDE_DIRS for part in rel.parts[:-1]):
            continue
        yield p, rel.as_posix()


def file_hash(p: Path):
    st = p.stat()
    return f'{st.st_size}-{int(st.st_mtime)}'


def analyse_one(path, clap):
    """-> (track_fields, window_list) or (None, None) if unusable."""
    meta = audio.probe(path)
    y = audio.decode(path)
    if y.size == 0:
        return None, None

    wins = audio.windows(y)
    if not wins:
        return None, None

    chunks = [w[0] for w in wins]
    emb = clap.embed_audio(chunks)                     # (W, D) unit vectors
    track_vec = emb.mean(axis=0)
    track_vec = track_vec / max(np.linalg.norm(track_vec), 1e-8)

    feat = features.extract(y)
    fields = dict(meta)
    fields.update(feat)
    # free here: the signal is already decoded and in memory
    fields['peaks'] = audio.peaks(y)
    fields['embedding'] = db.to_blob(track_vec)
    fields['dim'] = int(track_vec.size)
    # Duration comes from the DECODED sample count, not from ffprobe.
    #
    # ffprobe derives a raw-ADTS .aac duration from bitrate x filesize rather
    # than from decoded frames, and it is wrong in both directions: measured
    # 0.89x on three library files, and 2.14x (260.8s probed / 121.9s real) on
    # another. 89 of 376 tracks here are .aac.
    #
    # That is not cosmetic. The re-encode duplicate check matches on
    # normalised filename + duration within 2s, so a bogus duration lets an
    # .ogg re-encode of a track already held sail straight past it -- the
    # exact defence that check exists to provide.
    #
    # The signal is already fully decoded in `y`, so ground truth is free.
    fields['duration'] = float(y.size) / config.SAMPLE_RATE

    windows = [(i, float(w[1]), float(w[2]), db.to_blob(emb[i]))
               for i, w in enumerate(wins)]
    return fields, windows


def upsert(con, rel_path, path, fields, windows, model, share=config.SHARE):
    # (share, rel_path), never an absolute path: the row has to mean the same
    # thing on the base rig (W:) and on an editor machine (P:). rel_path stays
    # forward-slash relative to the share root.
    con.execute("""
        INSERT INTO tracks(share,rel_path,filename,ext,bytes,duration,samplerate,
                           channels,codec,bpm,music_key,key_conf,lufs,peak_db,
                           embedding,dim,file_hash,model,analyzed_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(rel_path) DO UPDATE SET
            share=excluded.share,
            filename=excluded.filename, ext=excluded.ext, bytes=excluded.bytes,
            duration=excluded.duration, samplerate=excluded.samplerate,
            channels=excluded.channels, codec=excluded.codec, bpm=excluded.bpm,
            music_key=excluded.music_key, key_conf=excluded.key_conf,
            lufs=excluded.lufs, peak_db=excluded.peak_db,
            embedding=excluded.embedding, dim=excluded.dim,
            file_hash=excluded.file_hash, model=excluded.model,
            analyzed_at=excluded.analyzed_at
    """, (share, rel_path, path.name, path.suffix.lower(), path.stat().st_size,
          fields.get('duration'), fields.get('samplerate'), fields.get('channels'),
          fields.get('codec'), fields.get('bpm'), fields.get('music_key'),
          fields.get('key_conf'), fields.get('lufs'), fields.get('peak_db'),
          fields['embedding'], fields['dim'], file_hash(path), model,
          datetime.now(timezone.utc).isoformat(timespec='seconds')))
    tid = con.execute('SELECT id FROM tracks WHERE rel_path=?', (rel_path,)).fetchone()['id']
    con.execute('DELETE FROM windows WHERE track_id=?', (tid,))
    con.executemany('INSERT INTO windows(track_id,idx,t0,t1,embedding) VALUES(?,?,?,?,?)',
                    [(tid, i, t0, t1, blob) for i, t0, t1, blob in windows])
    pk = fields.get('peaks')
    if pk:
        con.execute('INSERT OR REPLACE INTO peaks(track_id,n,data) VALUES(?,?,?)',
                    (tid, len(pk), pk))
    con.commit()
    return tid


def retag(con, clap):
    ids, mat = db.load_matrix(con)
    if not ids:
        print('nothing to tag'); return

    # recompute the source-bias axes: they depend on the library's composition,
    # so they must be refreshed whenever it changes
    from music_index import debias
    names = [r['filename'] for r in con.execute(
        'SELECT filename FROM tracks WHERE embedding IS NOT NULL ORDER BY id')]
    dirs = debias.compute_directions(mat, names)
    db.save_debias(con, dirs)
    print(f'  source-bias axes: {dirs.shape[0]} of {mat.shape[1]} dims erased')

    print(f'tagging {len(ids)} tracks against '
          f'{sum(len(v) for v in vocab.CATEGORIES.values())} labels '
          f'+ {len(vocab.AXES)} axes...')
    cats, axes = tagging.build_label_space(clap)
    tags, axvals = tagging.score_all(mat, cats, axes)
    tagging.write_scores(con, ids, tags, axvals)
    db.set_meta(con, 'vocab_hash', vocab.vocab_hash())
    db.set_meta(con, 'tagged_at', datetime.now(timezone.utc).isoformat(timespec='seconds'))
    con.commit()
    print('  tags written')


# ------------------------------------------------------------- ingest queue
# The other end of the queued handoff in musicweb/routes_ingest.py: that half
# validates, de-duplicates, transcodes and lands the file because it can, and
# stops at the point where a GPU is needed. Everything from there on is here.


def print_queue(con):
    """The queue's state, failures spelled out. Needs no CLAP, so it is cheap."""
    counts = db.queue_counts(con)
    print(f'ingest queue: {counts["pending"]} pending, '
          f'{counts["done"]} done, {counts["failed"]} failed')
    for r in db.queue_rows(con, db.PENDING):
        print(f'  pending #{r["id"]} {r["rel_path"]}  (queued {r["queued_at"]})')
    failed = db.queue_rows(con, db.FAILED)
    for r in failed:
        print(f'  FAILED  #{r["id"]} {r["rel_path"]}  '
              f'({r["attempts"]} attempt(s), last {r["updated_at"]})')
        print(f'          {r["error"]}')
    if failed:
        # loud on purpose: nothing picks these up again on its own, which is
        # the point -- a file that cannot be analysed must not be retried by
        # every run forever with the reason going unread. The file is still in
        # the library where it landed; delete it, or fix it and re-run with
        # --retry-failed.
        print(f'  -> {len(failed)} row(s) are parked and will NOT be retried. '
              'Re-run with --queue --retry-failed once the cause is fixed.')
    return counts


def drain_queue(con, clap, retry_failed=False, limit=0):
    """Analyse every queued upload. -> (done, failed).

    Each row is finished one way or the other before the next is started, so an
    interrupted drain leaves the rest pending rather than half-applied -- the
    same resumability the directory sweep has.
    """
    closed = db.queue_reconcile(con)
    if closed:
        print(f'{closed} queued file(s) had already been indexed by a sweep')

    rows = db.queue_pending(con, limit=limit, include_failed=retry_failed)
    if not rows:
        print('ingest queue: nothing to analyse')
        return 0, 0

    print(f'draining {len(rows)} queued upload(s)...')
    done = failed = 0
    for i, r in enumerate(rows, 1):
        rel, qid = r['rel_path'], r['id']
        try:
            # (share, rel_path) -> this host's path. The row was written by the
            # web app, possibly on another machine and another mount, so the
            # pair is translated here and never joined by hand.
            path = config.resolve_path(r['share'] or config.SHARE, rel)
        except Exception as e:                                  # noqa: BLE001
            db.queue_mark_failed(con, qid, f'unusable (share, rel_path): {e}')
            failed += 1
            print(f'  [{i}/{len(rows)}] FAIL {rel}: {e}', flush=True)
            continue
        if not path.is_file():
            db.queue_mark_failed(con, qid, f'file is not at {path}')
            failed += 1
            print(f'  [{i}/{len(rows)}] FAIL {rel}: file is not at {path}', flush=True)
            continue
        try:
            fields, windows = analyse_one(path, clap)
            if fields is None:
                raise RuntimeError('no decodable audio')
            tid = upsert(con, rel, path, fields, windows, clap.name,
                         share=r['share'] or config.SHARE)
            db.queue_mark_done(con, qid, tid)
            done += 1
            print(f'  [{i}/{len(rows)}] {rel[:58]:60s} '
                  f'{fields.get("duration", 0)/60:4.1f}m '
                  f'{str(fields.get("bpm") or "-"):>5s}bpm '
                  f'{str(fields.get("music_key") or "-"):>8s}  -> track {tid}',
                  flush=True)
        except Exception as e:                                  # noqa: BLE001
            db.queue_mark_failed(con, qid, f'{type(e).__name__}: {e}')
            failed += 1
            print(f'  [{i}/{len(rows)}] FAIL {rel}: {type(e).__name__}: {e}',
                  flush=True)
    return done, failed


def backfill_peaks(con, root: Path):
    """Add waveform overviews to tracks indexed before peaks existed.

    Decodes at 8 kHz only, so it is far cheaper than a re-index and never
    touches the embeddings.
    """
    rows = con.execute(
        'SELECT t.id, t.rel_path FROM tracks t '
        'LEFT JOIN peaks p ON p.track_id = t.id '
        'WHERE p.track_id IS NULL ORDER BY t.id').fetchall()
    if not rows:
        print('every track already has a waveform')
        return
    print(f'building waveforms for {len(rows)} tracks...')
    done = failed = 0
    for i, r in enumerate(rows, 1):
        try:
            # --root is a CLI argument, so the join goes through safe_join
            # rather than share_root's mapping; the validation is the same.
            path = config.safe_join(root, r['rel_path'])
            pk = audio.peaks_from_file(path)
            if not pk:
                raise RuntimeError('no audio')
            con.execute('INSERT OR REPLACE INTO peaks(track_id,n,data) VALUES(?,?,?)',
                        (r['id'], len(pk), pk))
            done += 1
        except Exception as e:
            failed += 1
            print(f'  FAIL {r["rel_path"]}: {e}')
        if i % 50 == 0:
            con.commit()
            print(f'  {i}/{len(rows)}', flush=True)
    con.commit()
    print(f'waveforms: {done} built, {failed} failed')


def fix_durations(con, tolerance=0.5):
    """Recompute stored durations from a decode, repairing bad ffprobe values.

    Decodes at 8 kHz -- the sample count is exact at any rate, and a low rate
    makes this a couple of minutes over the whole library rather than the nine
    a re-index would cost. Touches nothing but `duration`: no embeddings, no
    tags, no waveforms.
    """
    rows = con.execute('SELECT id, share, rel_path, filename, ext, duration '
                       'FROM tracks ORDER BY id').fetchall()
    print(f'checking {len(rows)} durations...')
    fixed = failed = 0
    worst = []
    for i, r in enumerate(rows, 1):
        try:
            path = config.resolve_path(r['share'], r['rel_path'])
            y = audio.decode(path, sr=8000)
            if y.size == 0:
                raise RuntimeError('no audio')
            real = y.size / 8000.0
            old = r['duration'] or 0.0
            if abs(real - old) > tolerance:
                con.execute('UPDATE tracks SET duration=? WHERE id=?', (real, r['id']))
                fixed += 1
                worst.append((abs(real - old), r['ext'], r['filename'], old, real))
        except Exception as e:
            failed += 1
            print(f'  FAIL {r["filename"][:50]}: {e}')
        if i % 100 == 0:
            con.commit()
            print(f'  {i}/{len(rows)}', flush=True)
    con.commit()

    worst.sort(reverse=True)
    print(f'\ncorrected {fixed}, unchanged {len(rows)-fixed-failed}, failed {failed}')
    for d, ext, name, old, real in worst[:8]:
        print(f'  {ext:6s} {old:7.1f}s -> {real:7.1f}s  ({d:+6.1f}s)  {name[:44]}')
    by_ext = collections.Counter(w[1] for w in worst)
    if by_ext:
        print('  by extension:', dict(by_ext))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fix-durations', action='store_true',
                    help='recompute every duration from a decode (repairs .aac)')
    ap.add_argument('--peaks', action='store_true', help='backfill waveform overviews')
    ap.add_argument('--retag', action='store_true', help='re-score from stored embeddings')
    ap.add_argument('--force', action='store_true', help='re-analyse every file')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--queue', action='store_true',
                    help='analyse the uploads the web app queued, then retag')
    ap.add_argument('--queue-status', action='store_true',
                    help='print the ingest queue (and its failures) and exit')
    ap.add_argument('--retry-failed', action='store_true',
                    help='with --queue: re-attempt rows parked as failed')
    # A full sweep is the only thing that knows what the library actually
    # contains, so it is the only thing that can drop a row whose file has
    # gone (MUSIC-3, 2026-08-14). --prune forces the delete through the "too
    # much of the library is missing" guard; --no-prune skips the sweep
    # entirely, for a run against a root that is only partly there.
    ap.add_argument('--prune', action='store_true',
                    help='delete rows for missing files even in bulk '
                         '(a rename leaves a ghost row that previews fine and '
                         'only fails at "send to Resolve")')
    ap.add_argument('--no-prune', action='store_true',
                    help='keep rows whose file is no longer in the library')
    ap.add_argument('--root', default=str(config.share_root()))
    # The queue is written on the NAS and drained here, and the two halves had
    # no way to meet until this existed (MUSIC-3, 2026-08-11): --queue always
    # opened config.DB_PATH, the base rig's in-repo index, so an editor's
    # queued cue sat `pending` on the NAS forever. Point this at a copy pulled
    # down from the NAS, drain it, push it back -- web/DEPLOY.md, "Draining the
    # NAS ingest queue", has the loop and the hazards.
    ap.add_argument('--db', default='',
                    help='SQLite index to work on (default: %s)' % config.DB_PATH)
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        sys.exit(f'music root not found: {root}')

    db_path = Path(args.db) if args.db else Path(config.DB_PATH)
    # connect() would happily CREATE one, and an empty database answers
    # --queue with "nothing to analyse" -- indistinguishable from a drained
    # queue, which is the one thing this flag must not be able to look like.
    if args.db and not db_path.is_file():
        sys.exit(f'--db: no database at {db_path}')

    con = db.connect(db_path)
    db.init(con)

    if args.queue_status:
        print_queue(con)
        return

    if args.fix_durations:
        fix_durations(con)
        return

    if args.peaks:
        backfill_peaks(con, root)
        return

    from music_index.clap_model import Clap
    print('loading CLAP...')
    clap = Clap()
    print(f'  {clap.name} dim={clap.dim} device={clap.device}')
    db.set_meta(con, 'model', clap.name)

    if args.retag:
        retag(con, clap)
        return

    if args.queue:
        done, failed = drain_queue(con, clap, retry_failed=args.retry_failed,
                                   limit=args.limit)
        if done:
            # percentiles are library-relative, so the whole library is
            # re-scored once anything new lands -- seconds, from the stored
            # embeddings. Skipped when nothing was added: retag also recomputes
            # the source-bias axes, and there is no reason to churn them.
            retag(con, clap)
        print(f'\nqueue: {done} indexed, {failed} failed')
        print_queue(con)
        n = con.execute('SELECT COUNT(*) c FROM tracks').fetchone()['c']
        print(f'DB: {n} tracks -> {db_path}')
        # a non-zero exit is what makes a scheduled drain visible as a failure
        sys.exit(1 if failed else 0)

    known = {r['rel_path']: r['file_hash']
             for r in con.execute('SELECT rel_path,file_hash FROM tracks')}
    files = list(iter_files(root))
    if args.limit:
        files = files[:args.limit]

    todo = [(p, rel) for p, rel in files
            if args.force or known.get(rel) != file_hash(p)]
    print(f'{len(files)} audio files under {root}')
    print(f'{len(todo)} to analyse ({len(files)-len(todo)} unchanged)\n')

    t0 = time.time()
    ok = failed = 0
    for i, (p, rel) in enumerate(todo, 1):
        try:
            fields, windows = analyse_one(p, clap)
            if fields is None:
                print(f'  [{i}/{len(todo)}] SKIP (no audio) {rel}')
                failed += 1
                continue
            upsert(con, rel, p, fields, windows, clap.name)
            ok += 1
            el = time.time() - t0
            eta = (len(todo) - i) * el / i
            print(f'  [{i}/{len(todo)}] {rel[:58]:60s} '
                  f'{fields.get("duration",0)/60:4.1f}m '
                  f'{str(fields.get("bpm") or "-"):>5s}bpm '
                  f'{str(fields.get("music_key") or "-"):>8s}  ETA {eta/60:.1f}m',
                  flush=True)
        except Exception as e:
            failed += 1
            print(f'  [{i}/{len(todo)}] FAIL {rel}: {type(e).__name__}: {e}', flush=True)

    print(f'\nanalysed {ok}, failed {failed}, {(time.time()-t0)/60:.1f} min')

    # Only a full, unlimited sweep has seen the whole library, so only a full
    # sweep may delete (MUSIC-3, 2026-08-14). Under --limit the file list is
    # truncated by construction and every row it did not reach would look
    # missing, and under --db the rows came from ANOTHER machine's copy of the
    # index -- neither is evidence that a file is gone. prune_missing itself
    # then refuses a scan that lost more than a fifth of the library, which is
    # what a half-mounted W: looks like.
    if args.limit or args.no_prune or (args.db and not args.prune):
        print('skipping the prune pass (rows for files that have gone are kept)')
    else:
        try:
            gone = db.prune_missing(con, [rel for _, rel in files],
                                    force=args.prune)
        except db.PruneRefused as e:
            print(f'  ! {e}')
        else:
            if gone:
                print(f'pruned {len(gone)} track(s) whose file is no longer '
                      f'under {root}:')
                for rel in gone[:20]:
                    print(f'    - {rel}')
                if len(gone) > 20:
                    print(f'    ... and {len(gone) - 20} more')
                print('  their proxies are now orphaned: '
                      'python make_proxies.py --prune')

    # A queued upload lives in the library like any other file, so this sweep
    # has just indexed it without ever reading the queue -- close those rows
    # rather than leave them claiming `pending` about a searchable track.
    closed = db.queue_reconcile(con)
    if closed:
        print(f'ingest queue: {closed} row(s) closed by this sweep')
    retag(con, clap)

    n = con.execute('SELECT COUNT(*) c FROM tracks').fetchone()['c']
    w = con.execute('SELECT COUNT(*) c FROM windows').fetchone()['c']
    print(f'\nDB: {n} tracks, {w} windows -> {db_path}')


if __name__ == '__main__':
    main()
