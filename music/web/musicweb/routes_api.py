"""Read-only JSON API: stats, facets, browse, text search, similarity."""
from fastapi import APIRouter
from pydantic import BaseModel

from musicweb import config, db
from musicweb.db import con
from musicweb.search import index, refresh

router = APIRouter()


# ---------------------------------------------------------------- serialising
# `share` and `rel_path` are in the payload because the browser posts that pair
# to the ccsync companion's loopback for "send to Resolve" -- the companion
# translates it to whatever the library is mounted at on THAT machine. An
# absolute path from this server would be meaningless on an editor's box.
_COLS = ['id', 'share', 'rel_path', 'filename', 'ext', 'duration', 'bpm',
         'music_key', 'key_conf', 'lufs', 'channels', 'samplerate', 'bytes']
TRACK_COLS = ', '.join(_COLS)              # unqualified, for single-table queries
TRACK_COLS_T = ', '.join(f't.{c}' for c in _COLS)   # qualified, for joins


def hydrate(rows):
    """Attach tags and axes to track rows in two queries, not N."""
    rows = [dict(r) for r in rows]
    if not rows:
        return rows
    ids = [r['id'] for r in rows]
    ph = ','.join('?' * len(ids))
    by = {r['id']: r for r in rows}
    for r in rows:
        r['tags'] = {}
        r['axes'] = {}
    for t in con().execute(
            f'SELECT track_id,category,label,score,pct FROM tags '
            f'WHERE track_id IN ({ph}) ORDER BY category, rank', ids):
        by[t['track_id']]['tags'].setdefault(t['category'], []).append(
            {'label': t['label'], 'score': round(t['score'], 4),
             'pct': round(t['pct'], 1)})
    for a in con().execute(
            f'SELECT track_id,axis,raw,pct FROM axes WHERE track_id IN ({ph})', ids):
        by[a['track_id']]['axes'][a['axis']] = round(a['pct'], 1)
    return rows


def _ordered(present, preferred):
    """`present` in `preferred` order; anything unlisted appended alphabetically.

    Keeps the sidebar in the vocabulary's order without the web app having to
    import vocab.py, which ships with the indexer and not with this tree.
    """
    return ([p for p in preferred if p in present]
            + sorted(n for n in present if n not in preferred))


# ---------------------------------------------------------------- endpoints
@router.get('/api/stats')
def stats():
    c = con()
    n = c.execute('SELECT COUNT(*) v FROM tracks').fetchone()['v']
    d = c.execute('SELECT COALESCE(SUM(duration),0) v FROM tracks').fetchone()['v']
    b = c.execute('SELECT COALESCE(SUM(bytes),0) v FROM tracks').fetchone()['v']
    return {'tracks': n, 'hours': round(d / 3600, 1), 'gb': round(b / 1e9, 2),
            'model': db.get_meta(c, 'model'), 'tagged_at': db.get_meta(c, 'tagged_at'),
            # `music_root` is this host's mount of the share, not something the
            # database knows -- it says W: on the base rig and P: on an editor
            # machine for the same 376 rows. The key name predates the share
            # model and the frontend reads it, so it stays.
            'share': config.SHARE,
            'music_root': str(config.share_root())}


@router.get('/api/facets')
def facets():
    out = {}
    cats = {r['category'] for r in con().execute('SELECT DISTINCT category FROM tags')}
    for cat in _ordered(cats, config.CATEGORY_ORDER):
        rows = con().execute(
            'SELECT label, COUNT(*) n FROM tags WHERE category=? '
            'GROUP BY label ORDER BY n DESC', (cat,)).fetchall()
        out[cat] = [{'label': r['label'], 'count': r['n']} for r in rows]
    axes = {r['axis'] for r in con().execute('SELECT DISTINCT axis FROM axes')}
    out['_axes'] = _ordered(axes, config.AXIS_ORDER)
    r = con().execute('SELECT MIN(bpm) lo, MAX(bpm) hi FROM tracks '
                      'WHERE bpm IS NOT NULL').fetchone()
    out['_bpm'] = {'min': r['lo'], 'max': r['hi']}
    return out


@router.get('/api/tracks')
def tracks(category: str = '', label: str = '', bpm_min: float = 0,
           bpm_max: float = 0, dur_min: float = 0, dur_max: float = 0,
           axis: str = '', axis_min: float = 0, axis_max: float = 100,
           sort: str = 'filename', limit: int = 500):
    where, params = [], []
    join = ''
    if category and label:
        join = 'JOIN tags g ON g.track_id = t.id AND g.category=? AND g.label=?'
        params += [category, label]
    if axis:
        join += ' JOIN axes x ON x.track_id = t.id AND x.axis=?'
        params.append(axis)
        where.append('x.pct BETWEEN ? AND ?')
        params += [axis_min, axis_max]
    if bpm_min:
        where.append('t.bpm >= ?'); params.append(bpm_min)
    if bpm_max:
        where.append('t.bpm <= ?'); params.append(bpm_max)
    if dur_min:
        where.append('t.duration >= ?'); params.append(dur_min)
    if dur_max:
        where.append('t.duration <= ?'); params.append(dur_max)

    order = {'filename': 't.filename', 'bpm': 't.bpm', 'duration': 't.duration',
             'newest': 't.analyzed_at DESC'}.get(sort, 't.filename')
    if category and label and sort == 'filename':
        order = 'g.pct DESC'

    sql = f'SELECT {TRACK_COLS_T} FROM tracks t {join}'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += f' ORDER BY {order} LIMIT ?'
    params.append(limit)
    return {'tracks': hydrate(con().execute(sql, params).fetchall())}


class SearchReq(BaseModel):
    query: str
    k: int = 60
    pool: str = 'max'          # 'max' = any moment, 'mean' = whole track


@router.post('/api/search')
def search(req: SearchReq):
    q = (req.query or '').strip()
    if not q:
        return {'tracks': []}
    hits = index().text_search(q, k=req.k, pool=req.pool)
    if not hits:
        return {'tracks': []}
    by = {h['id']: h for h in hits}
    ph = ','.join('?' * len(by))
    rows = hydrate(con().execute(
        f'SELECT {TRACK_COLS} FROM tracks WHERE id IN ({ph})', list(by)).fetchall())
    for r in rows:
        r['match'] = by[r['id']]['match']
    rows.sort(key=lambda r: -r['match'])
    return {'tracks': rows, 'query': q}


@router.get('/api/similar/{track_id}')
def similar(track_id: int, k: int = 20):
    hits = index().similar(track_id, k=k)
    if not hits:
        return {'tracks': []}
    by = {h['id']: h['score'] for h in hits}
    ph = ','.join('?' * len(by))
    rows = hydrate(con().execute(
        f'SELECT {TRACK_COLS} FROM tracks WHERE id IN ({ph})', list(by)).fetchall())
    for r in rows:
        r['match'] = round(by[r['id']] * 100, 1)
    rows.sort(key=lambda r: -r['match'])
    return {'tracks': rows}


@router.post('/api/reload')
def reload_index():
    """Pick up a fresh index without restarting the server.

    The invalidate() first is what makes that true of a REPLACED file (MUSIC-10,
    2026-08-14). con() hands back a connection cached for the life of its
    thread, and a sqlite3 connection is bound to an inode -- so after a deploy
    swaps music.db by rename, refresh() faithfully rebuilt the matrices from the
    unlinked old database and this route answered 200 with the old counts.
    Re-indexing in place (the base rig's own case) never needed it, which is why
    it survived this long.
    """
    db.invalidate()
    refresh(con())
    return stats()
