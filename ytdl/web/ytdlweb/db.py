"""SQLite access. ALL SQL in this app lives here.

Schema handling follows musicweb/db.py, which follows broll/web/app/db.py:
schema.sql is the source of truth and is safe to re-run (CREATE ... IF NOT
EXISTS throughout), anything it cannot express -- an ALTER -- is a numbered file
in migrations/ applied in order, tracked with PRAGMA user_version, and carrying
an already-applied PREDICATE that, not the recorded version, decides whether it
runs. There are no migrations yet; the runner exists so the first one is a
two-line change rather than a design decision made under pressure.

Two callers share this module and they are not symmetrical: the API handlers
are sync FastAPI endpoints on the threadpool, and the pipeline worker is one
long-lived daemon thread. con() gives each its own connection because a sqlite3
connection may only be used on the thread that created it. Every write the
worker makes is committed as it happens -- the SPA polls the job row 1500 ms
apart, so an uncommitted counter is a counter that lies.
"""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from ytdlweb import config

# Highest schema version this codebase knows how to run against. Bump it, add
# the file to _MIGRATIONS, and give it a predicate.
CURRENT_SCHEMA_VERSION = 4

# "the version this migration produces" -> (filename, already-applied predicate).
# The predicate must answer "is this migration's effect already in the database?"
# without consulting user_version. Ordered by key. v1 is what schema.sql
# creates; everything after it is an ALTER or an index schema.sql cannot add to
# a table that already exists.
_MIGRATIONS = {
    2: ('002_downloads_term_dir.sql',
        lambda con: 'term_dir' in _columns(con, 'downloads')),
    3: ('003_one_active_job_per_editor.sql',
        lambda con: _index_exists(con, 'idx_jobs_one_active')),
    4: ('004_jobs_kind.sql',
        lambda con: 'kind' in _columns(con, 'jobs')),
}

# What made a job. 'search' is a topic Claude expands and the editor reviews;
# 'urls' is "download exactly these links", which has no search, claude or
# filter phase and therefore starts where the download phase starts. The
# column is deliberately NOT in _JOB_COLS: how a job was made is not something
# a later UPDATE gets to change.
KIND_SEARCH = 'search'
KIND_URLS = 'urls'
KINDS = (KIND_SEARCH, KIND_URLS)

# The phase machine, in order. Anything not terminal is "the worker owns this
# job"; ready_for_review is the one non-terminal phase the worker is NOT
# working on -- it is waiting for the editor.
PHASES = ('queued', 'generating_terms', 'searching', 'enriching', 'filtering',
          'ready_for_review', 'downloading', 'done', 'failed', 'cancelled')
TERMINAL = ('done', 'failed', 'cancelled')
# Phases whose work is mid-flight and must be restarted after a container
# restart. `downloading` is deliberately absent: it is resumed, not restarted.
RESUMABLE = ('generating_terms', 'searching', 'enriching', 'filtering')

# Columns the worker and the API are allowed to write through _update(). A
# whitelist because the column name is interpolated into the SQL string --
# values are always parameters, names never can be.
_JOB_COLS = frozenset({
    'phase', 'error', 'terms_total', 'terms_done', 'candidates',
    'enrich_total', 'enrich_done', 'dl_total', 'dl_done', 'dl_failed',
    'cancel_requested', 'quality', 'period', 'max_per_term'})
_VIDEO_COLS = frozenset({
    'url', 'title', 'channel', 'duration', 'upload_date', 'view_count',
    'thumbnail', 'meta_error', 'relevant', 'relevance_note', 'duplicate',
    'duplicate_of', 'selected', 'dl_state', 'dl_error', 'filepath'})


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def connect(path=None):
    p = Path(path or config.DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=30)
    con.row_factory = sqlite3.Row
    # job_terms/job_videos/job_video_terms all cascade from jobs; without this
    # pragma (which is per-connection, not per-database) a deleted job would
    # leave its rows behind.
    con.execute('PRAGMA foreign_keys=ON')
    return con


def _columns(con, table):
    return {r[1] for r in con.execute(f'PRAGMA table_info({table})')}


def _table_exists(con, table):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                       (table,)).fetchone() is not None


def _index_exists(con, name):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
                       (name,)).fetchone() is not None


def _apply_migration(con, filename):
    """Apply one migration inside an explicit transaction.

    executescript() does not wrap the script for us (it commits anything
    pending first, then runs each statement largely as its own unit), so the
    BEGIN/COMMIT is ours -- a failure partway through must not leave the schema
    half-migrated.
    """
    path = config.MIGRATIONS_DIR / filename
    if not path.exists():
        raise RuntimeError(
            f'FATAL: migration {filename!r} not found at {path}. The app cannot '
            'migrate its database without it -- if deploying ytdl/web '
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
    """
    schema_sql = config.SCHEMA_PATH.read_text(encoding='utf-8')

    if not _table_exists(con, 'jobs'):
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

    # Re-running schema.sql is what picks up purely additive tables and indexes
    # on a database that already exists.
    con.executescript(schema_sql)
    con.execute(f'PRAGMA user_version = {CURRENT_SCHEMA_VERSION}')
    con.commit()


def init(con):
    """Historical name for ensure_schema; the mount probe and tests call this."""
    ensure_schema(con)


_local = threading.local()
_schema_ready = False


def con():
    """One SQLite connection per thread.

    FastAPI dispatches sync endpoints across a threadpool and the pipeline
    worker is a thread of its own; a sqlite3 connection may only be used on the
    thread that created it. WAL makes concurrent readers cheap, so per-thread
    connections cost nothing.
    """
    global _schema_ready
    c = getattr(_local, 'con', None)
    if c is None:
        c = connect()
        if not _schema_ready:
            init(c)
            _schema_ready = True
        _local.con = c
    return c


def _update(c, table, where_sql, where_args, allowed, cols):
    """UPDATE with a whitelisted column set. Returns rowcount."""
    bad = set(cols) - allowed
    if bad:
        raise ValueError(f'not an updatable column: {sorted(bad)}')
    if not cols:
        return 0
    sets = ', '.join(f'{k}=?' for k in cols)
    args = list(cols.values()) + list(where_args)
    cur = c.execute(f'UPDATE {table} SET {sets} WHERE {where_sql}', args)
    return cur.rowcount


# ------------------------------------------------------------------- jobs

def create_job(c, created_by, term, term_dir, project_slug, project_label,
               quality='1080p', period=None, max_per_term=15):
    ts = now()
    try:
        cur = c.execute(
            'INSERT INTO jobs(created_by,term,term_dir,project_slug,project_label,'
            'quality,period,max_per_term,phase,created_at,updated_at) '
            "VALUES(?,?,?,?,?,?,?,?,'queued',?,?)",
            (created_by, term, term_dir, project_slug, project_label, quality,
             period, max_per_term, ts, ts))
    except sqlite3.IntegrityError:
        # The one-active-job index refused it (YTDL-25) -- and a failed INSERT
        # leaves this connection's implicit transaction OPEN, holding a write
        # lock. Connections here are per-thread and live forever, so an
        # un-rolled-back loser of that race would block every later write on
        # the request threadpool ("database is locked", 30 s at a time).
        c.rollback()
        raise
    c.commit()
    return cur.lastrowid


def create_url_job(c, created_by, term, term_dir, project_slug, project_label,
                   videos, quality='1080p'):
    """A kind='urls' job AND its videos, in one transaction. -> job id.

    `videos` is [{'video_id', 'url', 'title'?, 'duplicate_of'?}] in the order
    the editor pasted them. An entry carrying `duplicate_of` is written
    skipped/deselected -- the same shape the download phase writes when its own
    ledger re-check finds one -- so the fleet's "never re-downloaded" rule
    (REQ 6) is applied before any bandwidth is planned, not only after.

    One transaction because a url job has no search half to write the rows
    later: a jobs row with no videos would be an ACTIVE job that can never
    finish, and one active job per editor (YTDL-25) then locks that editor out
    of the whole app with nothing to cancel from the UI.
    """
    ts = now()
    pending = [v for v in videos if not v.get('duplicate_of')]
    try:
        cur = c.execute(
            'INSERT INTO jobs(created_by,kind,term,term_dir,project_slug,'
            'project_label,quality,dl_total,phase,created_at,updated_at) '
            "VALUES(?,?,?,?,?,?,?,?,'queued',?,?)",
            (created_by, KIND_URLS, term, term_dir, project_slug,
             project_label, quality, len(pending), ts, ts))
        job_id = cur.lastrowid
        for v in videos:
            dup = v.get('duplicate_of')
            c.execute(
                'INSERT INTO job_videos(job_id,video_id,url,title,selected,'
                'duplicate,duplicate_of,dl_state) VALUES(?,?,?,?,?,?,?,?)',
                (job_id, v['video_id'], v['url'], v.get('title'),
                 0 if dup else 1, 1 if dup else 0, dup,
                 'skipped' if dup else 'pending'))
    except sqlite3.IntegrityError:
        # Same reason create_job rolls back: a failed INSERT leaves this
        # connection's implicit transaction open, holding a write lock that
        # every later request on this thread would then wait 30 s for.
        c.rollback()
        raise
    c.commit()
    return job_id


def get_job(c, job_id):
    return c.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()


def get_job_for(c, job_id, user):
    """A job the caller owns, or None.

    Ownership is checked in SQL rather than after the fetch so there is no path
    where a handler reads another editor's job row and then forgets to compare.
    """
    return c.execute('SELECT * FROM jobs WHERE id=? AND created_by=?',
                     (job_id, user)).fetchone()


def recent_jobs(c, user, limit=20):
    return c.execute('SELECT * FROM jobs WHERE created_by=? ORDER BY id DESC '
                     'LIMIT ?', (user, int(limit))).fetchall()


def active_job(c, user):
    """The caller's non-terminal job, or None. One at a time, per editor.

    ready_for_review counts as active: it holds a manifest the editor has not
    dealt with yet, and starting a second search would silently orphan it.
    """
    ph = ','.join('?' * len(TERMINAL))
    return c.execute(f'SELECT * FROM jobs WHERE created_by=? AND phase NOT IN ({ph}) '
                     'ORDER BY id LIMIT 1', (user, *TERMINAL)).fetchone()


def set_job(c, job_id, **cols):
    """Write job columns and touch updated_at. Commits -- polling reads this."""
    bad = set(cols) - _JOB_COLS
    if bad:
        raise ValueError(f'not an updatable job column: {sorted(bad)}')
    sets = ''.join(f'{k}=?, ' for k in cols)
    c.execute(f'UPDATE jobs SET {sets}updated_at=? WHERE id=?',
              [*cols.values(), now(), job_id])
    c.commit()


def set_phase(c, job_id, phase, error=None):
    """Move a job to `phase`. `error` is only written when one is given.

    Deliberately NOT `error=error`: the filtering phase records a degraded
    banner (Claude was unreachable, the manifest is unfiltered) and then
    transitions to ready_for_review, and clearing the message on the way would
    hand the editor an unfiltered manifest with nothing saying so.
    """
    if phase not in PHASES:
        raise ValueError(f'unknown phase {phase!r}')
    if error is None:
        set_job(c, job_id, phase=phase)
    else:
        set_job(c, job_id, phase=phase, error=error)


def bump(c, job_id, column, n=1):
    """counter += n, committed. The SPA's progress bar is built from these."""
    if column not in _JOB_COLS:
        raise ValueError(f'not a counter column: {column!r}')
    c.execute(f'UPDATE jobs SET {column}={column}+?, updated_at=? WHERE id=?',
              (n, now(), job_id))
    c.commit()


def request_cancel(c, job_id):
    c.execute('UPDATE jobs SET cancel_requested=1, updated_at=? WHERE id=?',
              (now(), job_id))
    c.commit()


# The phases no worker is inside: `queued` has not been claimed and
# `ready_for_review` is waiting for a human. Anything else is mid-phase and the
# flag is the only safe way to stop it.
IDLE = ('queued', 'ready_for_review')


def cancel_now(c, job_id):
    """Cancel a job outright if no phase is in flight. -> True if it moved.

    YTDL-1 (2026-08-11): the flag alone is honoured only inside run_job, which
    the worker never enters for `ready_for_review` -- so cancelling a manifest
    was a silent no-op that left the editor with a permanently active job and a
    409 on every new search. The phase is part of the WHERE clause because the
    worker may have claimed a `queued` job between the caller's read and this
    write: it then does not match, and the caller falls back to the flag.

    cancel_requested is set as well as the phase, so a worker already inside
    the job sees the request on its next loop rather than writing the next
    phase over `cancelled`.
    """
    ph = ','.join('?' * len(IDLE))
    cur = c.execute(
        f"UPDATE jobs SET phase='cancelled', cancel_requested=1, updated_at=? "
        f'WHERE id=? AND phase IN ({ph})', (now(), job_id, *IDLE))
    c.commit()
    return bool(cur.rowcount)


def clear_cancel(c, job_id):
    """Forget an unhonoured cancel request. Called when the editor asks for
    work again (start_download): a flag left set from a cancel that no phase
    was in flight for would insta-cancel the job the worker then claims."""
    c.execute('UPDATE jobs SET cancel_requested=0, updated_at=? WHERE id=?',
              (now(), job_id))
    c.commit()


def is_cancelled(c, job_id):
    """Re-read from the database, never from the job row the worker is holding.

    The cancel arrives on a request thread while the worker is mid-phase; a
    cached row would only notice it when the phase ends, which for a 40-video
    download is minutes away.
    """
    r = c.execute('SELECT cancel_requested FROM jobs WHERE id=?', (job_id,)).fetchone()
    return bool(r and r['cancel_requested'])


def claim_next_job(c):
    """The next job the worker should work on, or None.

    Serial by design: one job at a time, oldest first, and `downloading` is in
    the set because the download phase is entered by the API (the editor
    pressing DOWNLOAD), not by the phase before it.
    """
    return c.execute(
        "SELECT * FROM jobs WHERE phase IN ('queued','generating_terms',"
        "'searching','enriching','filtering','downloading') ORDER BY id "
        'LIMIT 1').fetchone()


def reset_stale_jobs(c):
    """Boot recovery. -> (restarted, resumed) counts.

    A container restart kills the worker thread mid-phase, and the phase column
    then describes work that nothing is doing. Two different repairs:

      generating_terms|searching|enriching|filtering -> back to `queued`, with
        that job's terms and videos wiped. Re-running is cheap (a few minutes
        of yt-dlp) and idempotent, and it is the only way to be sure the
        counters and the rows agree.

      downloading -> KEPT, with any `downloading` video back to `pending`.
        Restarting a download job would re-fetch gigabytes; yt-dlp resumes its
        own .part file, and anything that actually finished is caught by the
        dedupe re-check before the next attempt starts.

    ready_for_review is untouched: it is a manifest waiting for a human.
    """
    ph = ','.join('?' * len(RESUMABLE))
    stale = c.execute(f'SELECT id FROM jobs WHERE phase IN ({ph})', RESUMABLE).fetchall()
    for r in stale:
        c.execute('DELETE FROM job_video_terms WHERE job_id=?', (r['id'],))
        c.execute('DELETE FROM job_videos WHERE job_id=?', (r['id'],))
        c.execute('DELETE FROM job_terms WHERE job_id=?', (r['id'],))
        c.execute("UPDATE jobs SET phase='queued', error=NULL, terms_total=0, "
                  'terms_done=0, candidates=0, enrich_total=0, enrich_done=0, '
                  'updated_at=? WHERE id=?', (now(), r['id']))
    resumed = c.execute(
        "UPDATE job_videos SET dl_state='pending' WHERE dl_state='downloading'")
    c.commit()
    return len(stale), resumed.rowcount


# ------------------------------------------------------------------ terms

def add_term(c, job_id, term, lang, source, english_gloss=None):
    """-> term id. Returns the existing id if the term is already on the job.

    Duplicates are expected, not exceptional: Claude regularly hands back the
    editor's own phrase as one of its English variants.
    """
    c.execute('INSERT OR IGNORE INTO job_terms(job_id,term,lang,english_gloss,source) '
              'VALUES(?,?,?,?,?)', (job_id, term, lang, english_gloss, source))
    c.commit()
    # Re-read rather than trust lastrowid: after an IGNOREd insert it still
    # holds whatever this connection wrote last, which would silently attribute
    # every hit of a repeated term to some other term's id.
    return c.execute('SELECT id FROM job_terms WHERE job_id=? AND term=?',
                     (job_id, term)).fetchone()['id']


def terms(c, job_id):
    return c.execute('SELECT * FROM job_terms WHERE job_id=? ORDER BY id',
                     (job_id,)).fetchall()


def unsearched_terms(c, job_id):
    return c.execute('SELECT * FROM job_terms WHERE job_id=? AND searched=0 '
                     'ORDER BY id', (job_id,)).fetchall()


def mark_term_searched(c, term_id, hits):
    c.execute('UPDATE job_terms SET searched=1, hits=? WHERE id=?', (hits, term_id))
    c.commit()


# ----------------------------------------------------------------- videos

def add_video(c, job_id, video_id, url, title=None):
    """-> True if this video is new to the job.

    The caller uses the answer for the `candidates` counter; the term link is
    recorded either way (see link_term).
    """
    cur = c.execute(
        'INSERT OR IGNORE INTO job_videos(job_id,video_id,url,title) '
        'VALUES(?,?,?,?)', (job_id, video_id, url, title))
    return bool(cur.rowcount)


def link_term(c, job_id, video_id, term_id):
    """Record that this term surfaced this video. Idempotent.

    Called for EVERY hit, including videos the job has already seen -- that is
    the whole point of the join table: the chip for a term must filter to
    everything that term found, not to what it found first.
    """
    c.execute('INSERT OR IGNORE INTO job_video_terms(job_id,video_id,term_id) '
              'VALUES(?,?,?)', (job_id, video_id, term_id))


def videos(c, job_id):
    return c.execute('SELECT * FROM job_videos WHERE job_id=? ORDER BY id',
                     (job_id,)).fetchall()


def get_video(c, job_id, video_id):
    return c.execute('SELECT * FROM job_videos WHERE job_id=? AND video_id=?',
                     (job_id, video_id)).fetchone()


def set_video(c, job_id, video_id, **cols):
    n = _update(c, 'job_videos', 'job_id=? AND video_id=?', (job_id, video_id),
                _VIDEO_COLS, cols)
    c.commit()
    return n


def term_ids_by_video(c, job_id):
    """{video_id: [term_id, ...]} -- what the manifest's chips filter on."""
    out = {}
    for r in c.execute('SELECT video_id, term_id FROM job_video_terms WHERE '
                       'job_id=? ORDER BY term_id', (job_id,)):
        out.setdefault(r['video_id'], []).append(r['term_id'])
    return out


def term_hit_counts(c, job_id):
    """{term_id: videos it surfaced} from the join table, not from job_terms.

    job_terms.hits counts raw search results; this counts distinct videos still
    on the manifest, which is the number the chip shows.
    """
    return {r['term_id']: r['n'] for r in c.execute(
        'SELECT term_id, COUNT(*) n FROM job_video_terms WHERE job_id=? '
        'GROUP BY term_id', (job_id,))}


def select_video(c, job_id, video_id, selected):
    """Toggle one video. Duplicates are refused in SQL, not just in the handler.

    Selection can never override dedupe (REQ 6): the guard lives here so no
    future caller can route around it.
    """
    cur = c.execute('UPDATE job_videos SET selected=? WHERE job_id=? AND '
                    'video_id=? AND duplicate=0', (1 if selected else 0, job_id, video_id))
    c.commit()
    return bool(cur.rowcount)


def bulk_select(c, job_id, selected, scope='relevant'):
    """Select-all / select-none. Duplicates are always excluded.

    scope='relevant' leaves the filtered-out cards alone; scope='all' includes
    them, which is how an editor overrules Claude wholesale.

    DESELECTING ignores the scope entirely (YTDL-26, 2026-08-11): the SPA sends
    scope='relevant' whenever "show filtered" is off, so a filtered-out video
    the editor had hand-selected stayed selected behind a hidden card -- and
    mark_pending, which has no relevance predicate, downloaded it. NONE means
    none.
    """
    sql = ('UPDATE job_videos SET selected=? WHERE job_id=? AND duplicate=0 '
           'AND meta_error IS NULL')
    args = [1 if selected else 0, job_id]
    if scope != 'all' and selected:
        sql += ' AND relevant=1'
    cur = c.execute(sql, args)
    c.commit()
    return cur.rowcount


def mark_pending(c, job_id):
    """Queue the editor's selection for download. -> how many rows.

    Deliberately narrow: selected AND relevant-or-explicitly-selected AND not a
    duplicate AND not already done. `dl_state='done'` rows are skipped so a
    second DOWNLOAD press on a partly-finished job does not re-fetch them.

    `pending` is in the list to make this idempotent (YTDL-18, 2026-08-11): the
    route writes rows, counters and phase as three transactions, and a
    container death between the first and the last used to leave a
    ready_for_review job whose rows were already pending -- which this no
    longer matched, so every later DOWNLOAD press 400'd with "nothing is
    selected" and no in-band recovery existed.
    """
    cur = c.execute(
        "UPDATE job_videos SET dl_state='pending', dl_error=NULL WHERE job_id=? "
        "AND selected=1 AND duplicate=0 AND meta_error IS NULL "
        "AND dl_state IN ('none','failed','skipped','pending')", (job_id,))
    c.commit()
    return cur.rowcount


def pending_videos(c, job_id):
    return c.execute("SELECT * FROM job_videos WHERE job_id=? AND dl_state='pending' "
                     'ORDER BY id', (job_id,)).fetchall()


def counts(c, job_id):
    """The manifest header's numbers, in one query."""
    r = c.execute(
        'SELECT COUNT(*) total, '
        'SUM(CASE WHEN relevant=1 AND duplicate=0 AND meta_error IS NULL THEN 1 ELSE 0 END) relevant, '
        'SUM(CASE WHEN relevant=0 OR meta_error IS NOT NULL THEN 1 ELSE 0 END) irrelevant, '
        'SUM(CASE WHEN duplicate=1 THEN 1 ELSE 0 END) duplicates, '
        'SUM(CASE WHEN selected=1 AND duplicate=0 THEN 1 ELSE 0 END) selected, '
        'SUM(CASE WHEN selected=1 AND duplicate=0 THEN COALESCE(duration,0) ELSE 0 END) selected_seconds '
        'FROM job_videos WHERE job_id=?', (job_id,)).fetchone()
    return {k: (r[k] or 0) for k in
            ('total', 'relevant', 'irrelevant', 'duplicates', 'selected',
             'selected_seconds')}


# ------------------------------------------------------------------ ledger

def ledger_get(c, video_id):
    return c.execute('SELECT * FROM downloads WHERE video_id=?', (video_id,)).fetchone()


def ledger_ids(c):
    return {r['video_id'] for r in c.execute('SELECT video_id FROM downloads')}


def ledger_map(c):
    """{video_id: '<project label>/<folder>'} -- what the ALREADY IN badge shows.

    The FOLDER, not the term: they differ for any term carrying <>:"/\\|?* or
    more than 80 UTF-8 bytes, and the badge is an instruction to go and look at
    a path over SMB (YTDL-31, 2026-08-11). term_dir is NULL on rows written
    before it existed, and those fall back to the raw term as they always did.
    """
    return {r['video_id']: f"{r['project_label']}/{r['term_dir'] or r['term']}"
            for r in c.execute('SELECT video_id, project_label, term, term_dir '
                               'FROM downloads')}


def _term_dir_of(rel_path, term):
    """The folder a ledgered clip is actually in.

    rel_path is written as 'Youtube/<term_dir>/<filename>' by the download
    phase, so the truth is already in the argument list -- taking it from there
    rather than re-deriving safe_term_dirname(term) means the ledger agrees
    with the disk even if the naming rules change under it.
    """
    parts = [p for p in str(rel_path or '').replace('\\', '/').split('/') if p]
    if len(parts) >= 3 and parts[0] == 'Youtube':
        return parts[1]
    return config.safe_term_dirname(term) if term else None


def ledger_add(c, video_id, title, channel, project_slug, project_label, term,
               rel_path, job_id=None, downloaded_by=None):
    """Record a landed download. Upserts: re-downloading into another project
    moves the record rather than raising on the primary key."""
    c.execute(
        'INSERT INTO downloads(video_id,title,channel,project_slug,project_label,'
        'term,term_dir,rel_path,job_id,downloaded_by,downloaded_at) '
        'VALUES(?,?,?,?,?,?,?,?,?,?,?) '
        'ON CONFLICT(video_id) DO UPDATE SET title=excluded.title, '
        'channel=excluded.channel, project_slug=excluded.project_slug, '
        'project_label=excluded.project_label, term=excluded.term, '
        'term_dir=excluded.term_dir, '
        'rel_path=excluded.rel_path, job_id=excluded.job_id, '
        'downloaded_by=excluded.downloaded_by, downloaded_at=excluded.downloaded_at',
        (video_id, title, channel, project_slug, project_label, term,
         _term_dir_of(rel_path, term), rel_path, job_id, downloaded_by, now()))
    c.commit()


# --------------------------------------------------------------- serialising

def job_dict(row):
    """A job row as JSON. The SPA's poll response is built on this."""
    d = dict(row)
    d['terminal'] = d['phase'] in TERMINAL
    return d


def video_dict(row, term_ids=None):
    d = dict(row)
    d['term_ids'] = term_ids or []
    return d


def manifest_json(c, job):
    """The human-readable provenance file written into the download folder.

    Deliberately the shape batch_dl.py already writes (queries/created/videos),
    extended with the terms and their glosses: the standalone utility, the
    companion and any editor poking around in the folder can all read it, and
    it is the only record of WHY a clip is in that folder that survives the
    database being lost.
    """
    tid_map = term_ids_by_video(c, job['id'])
    term_rows = {t['id']: t for t in terms(c, job['id'])}
    return {
        'query': job['term'],
        # 'search' | 'urls'. For a url job `query` is the folder the editor
        # filed the links under rather than something that was searched for,
        # and this is what says so to anyone reading the folder later.
        'kind': job['kind'],
        'created': now(),
        'created_by': job['created_by'],
        'project': job['project_label'],
        'quality': job['quality'],
        'terms': [{'q': t['term'], 'lang': t['lang'],
                   'english_gloss': t['english_gloss'], 'source': t['source'],
                   'hits': t['hits']} for t in term_rows.values()],
        'videos': [{
            'id': v['video_id'], 'url': v['url'], 'title': v['title'],
            'channel': v['channel'], 'duration': v['duration'],
            'upload_date': v['upload_date'], 'filepath': v['filepath'],
            'state': v['dl_state'],
            'found_by': [term_rows[t]['term'] for t in tid_map.get(v['video_id'], [])
                         if t in term_rows],
        } for v in videos(c, job['id']) if v['dl_state'] in ('done', 'skipped')],
    }


def dumps(obj):
    """JSON as this app writes it to disk: readable, and never \\uXXXX for CJK."""
    return json.dumps(obj, indent=2, ensure_ascii=False)
