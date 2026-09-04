"""Read-only JSON API: stats, facets, browse, text search, similarity."""
from fastapi import APIRouter
from pydantic import BaseModel

from musicweb import config, db, rescore
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
            # When set, the tags are behind the tracks: a rescore was deferred
            # (MUSIC-5) or failed (MUSIC-1). Log-only was the old answer, and
            # the editor's version of it was "my drop has no tags and nothing
            # says why". 2026-09-04.
            'scores_stale': rescore.scores_stale(c),
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
    # MUSIC-14 (2026-09-04): a track ingested through the companion has no bpm
    # and no duration of its own (KNOWN_BUGS MUSIC-ING-1: no librosa on an
    # editor's machine), and `t.bpm >= 90` is never true of NULL. The counts go
    # out with the facets so the rail can say how many tracks a tempo or length
    # filter would drop, instead of the fleet's uploads vanishing in silence.
    u = con().execute(
        'SELECT SUM(bpm IS NULL) b, SUM(duration IS NULL) d FROM tracks').fetchone()
    out['_unknown'] = {'bpm': u['b'] or 0, 'duration': u['d'] or 0}
    return out


# ---------------------------------------------------------------- filtering
# One filter builder for browse AND for text search (MUSIC-4, 2026-09-04). The
# rail used to apply to `/api/tracks` only, so typing a description threw away
# the mood chip, the axis slider and the BPM boxes while still showing them lit
# -- the page asserted filters that were not in the query. Both callers now
# build the same JOINs and the same WHERE from this one place.
def _range(col, lo, hi, include_unknown):
    """`col` between lo and hi, either bound optional. Returns (sql, params).

    `include_unknown` widens the clause to `OR col IS NULL` rather than
    dropping it: an editor who asks for the unknowns still wants the range
    honoured for the tracks that HAVE a value.
    """
    parts, params = [], []
    if lo:
        parts.append(f'{col} >= ?'); params.append(lo)
    if hi:
        parts.append(f'{col} <= ?'); params.append(hi)
    if not parts:
        return '', []
    sql = ' AND '.join(parts)
    if include_unknown:
        return f'(({sql}) OR {col} IS NULL)', params
    return (f'({sql})' if len(parts) > 1 else sql), params


def _filters(category='', label='', axis='', axis_min=0, axis_max=100,
             bpm_min=0, bpm_max=0, dur_min=0, dur_max=0, include_unknown=False):
    """(join, where, params, unknown_cols) for the tracks table aliased `t`.

    `unknown_cols` names the columns a range filter is active on, which is what
    the "N tracks have no BPM" count is asked about.
    """
    join, where, params, unknown_cols = '', [], [], []
    if category and label:
        join = 'JOIN tags g ON g.track_id = t.id AND g.category=? AND g.label=?'
        params += [category, label]
    if axis:
        join += ' JOIN axes x ON x.track_id = t.id AND x.axis=?'
        params.append(axis)
        where.append('x.pct BETWEEN ? AND ?')
        params += [axis_min, axis_max]
    for col, lo, hi in (('t.bpm', bpm_min, bpm_max),
                        ('t.duration', dur_min, dur_max)):
        sql, ps = _range(col, lo, hi, include_unknown)
        if sql:
            where.append(sql)
            params += ps
            unknown_cols.append(col)
    return join, where, params, unknown_cols


def _unknown_hidden(join, category, label, axis, axis_min, axis_max,
                    unknown_cols, ids=None):
    """How many tracks a tempo/length filter is dropping only for a NULL.

    Counted against the rest of the filter (and, for a search, against that
    search's own hits), so the number is about the list the editor is looking
    at and not about the whole library (MUSIC-14).
    """
    if not unknown_cols:
        return 0
    where, params = [], []
    if category and label:
        params += [category, label]
    if axis:
        params.append(axis)
        where.append('x.pct BETWEEN ? AND ?')
        params += [axis_min, axis_max]
    where.append('(' + ' OR '.join(f'{c} IS NULL' for c in unknown_cols) + ')')
    if ids is not None:
        where.append('t.id IN (%s)' % ','.join('?' * len(ids)))
        params += list(ids)
    sql = f'SELECT COUNT(*) v FROM tracks t {join} WHERE ' + ' AND '.join(where)
    return con().execute(sql, params).fetchone()['v']


@router.get('/api/tracks')
def tracks(category: str = '', label: str = '', bpm_min: float = 0,
           bpm_max: float = 0, dur_min: float = 0, dur_max: float = 0,
           axis: str = '', axis_min: float = 0, axis_max: float = 100,
           sort: str = 'filename', limit: int = 500,
           include_unknown: bool = False):
    join, where, params, unknown_cols = _filters(
        category, label, axis, axis_min, axis_max,
        bpm_min, bpm_max, dur_min, dur_max, include_unknown)

    order = {'filename': 't.filename', 'bpm': 't.bpm', 'duration': 't.duration',
             'newest': 't.analyzed_at DESC'}.get(sort, 't.filename')
    if category and label and sort == 'filename':
        order = 'g.pct DESC'

    sql = f'SELECT {TRACK_COLS_T} FROM tracks t {join}'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += f' ORDER BY {order} LIMIT ?'
    rows = con().execute(sql, params + [limit]).fetchall()
    hidden = 0 if include_unknown else _unknown_hidden(
        join, category, label, axis, axis_min, axis_max, unknown_cols)
    return {'tracks': hydrate(rows),
            # The rail renders these two, so a filter never hides work the
            # fleet did without saying so (MUSIC-14).
            'unknown_hidden': hidden,
            'unknown_fields': [c.split('.')[-1] for c in unknown_cols]}


class SearchReq(BaseModel):
    query: str
    k: int = 60
    pool: str = 'max'          # 'max' = any moment, 'mean' = whole track
    # The left rail, carried into the search (MUSIC-4). Same names and same
    # defaults as /api/tracks' query parameters: one contract, two verbs.
    category: str = ''
    label: str = ''
    axis: str = ''
    axis_min: float = 0
    axis_max: float = 100
    bpm_min: float = 0
    bpm_max: float = 0
    dur_min: float = 0
    dur_max: float = 0
    include_unknown: bool = False


@router.post('/api/search')
def search(req: SearchReq):
    q = (req.query or '').strip()
    if not q:
        return {'tracks': []}
    hits = index().text_search(q, k=req.k, pool=req.pool)
    if not hits:
        return {'tracks': []}
    by = {h['id']: h for h in hits}
    join, where, params, unknown_cols = _filters(
        req.category, req.label, req.axis, req.axis_min, req.axis_max,
        req.bpm_min, req.bpm_max, req.dur_min, req.dur_max, req.include_unknown)
    ph = ','.join('?' * len(by))
    # The hits are already an id set, so the rail is one more clause on the
    # hydrate query rather than a second ranking pass: CLAP decides the order,
    # the filters decide the membership. The id set goes LAST because the
    # placeholders bind in text order and the JOINs carry their own.
    sql = f'SELECT {TRACK_COLS_T} FROM tracks t {join} WHERE '
    sql += ' AND '.join(where + [f't.id IN ({ph})'])
    rows = hydrate(con().execute(sql, params + list(by)).fetchall())
    for r in rows:
        r['match'] = by[r['id']]['match']
    rows.sort(key=lambda r: -r['match'])
    hidden = 0 if req.include_unknown else _unknown_hidden(
        join, req.category, req.label, req.axis, req.axis_min, req.axis_max,
        unknown_cols, ids=list(by))
    return {'tracks': rows, 'query': q,
            'unknown_hidden': hidden,
            'unknown_fields': [c.split('.')[-1] for c in unknown_cols]}


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
