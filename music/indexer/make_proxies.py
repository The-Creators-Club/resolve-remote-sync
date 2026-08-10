"""Generate 128k mp3 preview proxies for the indexed library -- port step 6.

    python make_proxies.py             # build what is missing or stale
    python make_proxies.py --force     # re-encode everything (except pointless ones)
    python make_proxies.py --limit 20  # try a handful first
    python make_proxies.py --prune     # delete proxies for tracks no longer indexed
    python make_proxies.py --dry-run   # say what would happen, encode nothing

Resumable and idempotent, the same way index_music.py is: re-running costs one
stat() per finished track. Base rig only -- it needs ffmpeg and the library on a
local mount. The output lands in DATA_ROOT/proxies, which ships to the NAS with
the rest of the data root; the web app then serves those instead of the wavs
and falls back to the original for any track that has none.
"""
import argparse
import sys
import time
from pathlib import Path

# music_index first: importing it is what puts the shared web tree
# (musicweb.db, musicweb.config) on sys.path.
from music_index import config, proxies
from musicweb import db


def track_rows(con, limit=0):
    rows = con.execute(
        'SELECT id, share, rel_path FROM tracks ORDER BY id').fetchall()
    return rows[:limit] if limit else rows


def items_for(rows, root=None):
    """(track_id, absolute path) pairs.

    Never joins root to rel_path by hand: rel_path comes out of the database,
    and safe_join is the only thing between a bad row and ffmpeg reading a file
    from outside the library.
    """
    out = []
    for r in rows:
        try:
            path = (config.safe_join(root, r['rel_path']) if root
                    else config.resolve_path(r['share'], r['rel_path']))
        except config.PathTraversalError as exc:
            print(f'  SKIP {r["rel_path"]}: {exc}')
            continue
        out.append((r['id'], path))
    return out


def prune(con, dry_run=False):
    ids = [r['id'] for r in con.execute('SELECT id FROM tracks')]
    stale = proxies.orphans(ids)
    if not stale:
        print('no orphaned proxies')
        return 0
    freed = 0
    for p in stale:
        freed += p.stat().st_size
        print(f'  {"would remove" if dry_run else "removing"} {p.name}')
        if not dry_run:
            p.unlink(missing_ok=True)
    print(f'{len(stale)} orphaned proxies, {freed/1e6:.1f} MB')
    return len(stale)


def report(summary, elapsed):
    before, after = summary['before_bytes'], summary['after_bytes']
    print(f'\n{summary["total"]} tracks in {elapsed/60:.1f} min')
    print(f'  generated          {summary[proxies.BUILT]}')
    print(f'  already up to date {summary[proxies.FRESH]}')
    # These are not failures. A source already at or below the proxy bitrate
    # cannot be made smaller by re-encoding it -- measured on this library, an
    # .ogg went 4.6 -> 6.7 MB before the check existed -- and for mp3 it would
    # also stack a second lossy generation on the first.
    codecs = ', '.join(f'{c or "?"} {n}' for c, n
                       in sorted(summary['skipped_codecs'].items(),
                                 key=lambda kv: -kv[1]))
    print(f'  skipped (already <= {proxies.PROXY_KBPS}k) '
          f'{summary[proxies.ALREADY_SMALL]}' + (f'   [{codecs}]' if codecs else ''))
    print(f'  source missing     {summary[proxies.MISSING]}')
    print(f'  failed             {summary[proxies.FAILED]}')
    for tid, path, err in summary['failures']:
        print(f'    {tid} {Path(path).name}: {err}')
    # "before" is what a remote editor used to pull to preview the library;
    # "after" is what they pull now, counting the skipped mp3s at their own
    # size because those are still served from the original.
    print(f'\n  preview bytes before {before/1e9:.2f} GB')
    print(f'  preview bytes after  {after/1e9:.2f} GB')
    if after:
        print(f'  ratio                {before/after:.2f}x '
              f'({(1 - after/before) * 100:.1f}% less)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true',
                    help='re-encode even if a proxy is present and current')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--jobs', type=int, default=4,
                    help='concurrent ffmpeg encodes')
    ap.add_argument('--kbps', type=int, default=proxies.PROXY_KBPS)
    ap.add_argument('--prune', action='store_true',
                    help='delete proxies whose track id is no longer indexed')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--root', default='', help='override the share root')
    args = ap.parse_args()

    root = Path(args.root) if args.root else None
    if root and not root.exists():
        sys.exit(f'music root not found: {root}')

    con = db.connect()
    db.init(con)

    if args.prune:
        prune(con, dry_run=args.dry_run)
        return

    items = items_for(track_rows(con, args.limit), root)
    print(f'{len(items)} indexed tracks -> {proxies.PROXIES_DIR}')
    print(f'  {args.kbps}k mp3, {args.jobs} concurrent encodes\n')

    if args.dry_run:
        summary = proxies.new_summary()
        summary['total'] = len(items)
        for tid, src in items:
            if not Path(src).is_file():
                summary[proxies.MISSING] += 1
                continue
            before = Path(src).stat().st_size
            summary['before_bytes'] += before
            if not args.force and proxies.is_fresh(Path(src), proxies.proxy_path(tid)):
                summary[proxies.FRESH] += 1
                summary['after_bytes'] += proxies.proxy_path(tid).stat().st_size
                continue
            info = proxies.source_info(src)
            if proxies.is_pointless(info, args.kbps):
                summary[proxies.ALREADY_SMALL] += 1
                summary['after_bytes'] += before
                codec = info.get('codec', '')
                summary['skipped_codecs'][codec] = \
                    summary['skipped_codecs'].get(codec, 0) + 1
            else:
                summary[proxies.BUILT] += 1
                # nothing encoded yet, so the only honest "after" is the
                # bitrate times the duration
                summary['after_bytes'] += int(info.get('duration', 0)
                                              * args.kbps * 1000 / 8)
        report(summary, 0.0)
        return

    t0 = time.time()
    summary = proxies.build_all(items, kbps=args.kbps, force=args.force,
                                jobs=args.jobs)
    report(summary, time.time() - t0)


if __name__ == '__main__':
    main()
