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

# For SHOT_TYPES / DEFAULT_SHOT_TYPES only, and deliberately from there rather
# than a copy here: a shot type IS its two prompt fragments, so the module that
# owns the fragments owns the key list. claude_cli imports config alone, so
# there is no cycle to fall into.
from ytdlweb import claude_cli, config

# Highest schema version this codebase knows how to run against. Bump it, add
# the file to _MIGRATIONS, and give it a predicate.
CURRENT_SCHEMA_VERSION = 6

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
    5: ('005_jobs_shot_types.sql',
        lambda con: 'shot_types' in _columns(con, 'jobs')),
    6: ('006_jobs_max_candidates.sql',
        lambda con: 'max_candidates' in _columns(con, 'jobs')),
}

# What made a job. 'search' is a topic Claude expands and the editor reviews;
# 'urls' is "download exactly these links", which has no search, claude or
# filter phase and therefore starts where the download phase starts. The
# column is deliberately NOT in _JOB_COLS: how a job was made is not something
# a later UPDATE gets to change.
KIND_SEARCH = 'search'
KIND_URLS = 'urls'
KINDS = (KIND_SEARCH, KIND_URLS)

# The shot types the editor ticked for a search, stored as a comma-separated
# list of claude_cli.SHOT_TYPES keys. Not JSON, because the values are
# `[a-z]+` and this column is read by eye in sqlite3 more often than by code.
#
# NULL and '' are DIFFERENT and both are load-bearing: NULL is "this row
# predates the column" and reads as the defaults (the behaviour every existing
# job actually ran with), '' is the editor deliberately ticking nothing, which
# means a neutral, unbiased search. A column default that collapsed the two
# would silently re-bias every old row -- so migration 005 backfills the
# literal default list rather than leaving NULLs behind.
SHOT_TYPES = claude_cli.SHOT_TYPES
DEFAULT_SHOT_TYPES = claude_cli.DEFAULT_SHOT_TYPES


def encode_shot_types(shot_types):
    """A selection -> the column value. None means the defaults."""
    return ','.join(claude_cli.normalise_shot_types(shot_types))


def shot_types_of(row_or_value):
    """A jobs row (or the raw column, or a list) -> the selection.

    Takes the ROW because every caller has one -- and because a row read from a
    database the migration has not reached, or by a SELECT that did not ask for
    the column, has no such key at all: that reads as the defaults, which is
    the search those rows actually ran.
    """
    _SEQ = (list, tuple, set, frozenset)
    value = row_or_value
    if value is not None and not isinstance(value, (str, bytes) + _SEQ):
        try:
            value = row_or_value['shot_types']
        except (IndexError, KeyError, TypeError):
            value = None
    if value is None:
        return DEFAULT_SHOT_TYPES
    # A job_dict has already turned the column into a list; a row has the
    # stored string. Both are answers, and neither may be str()'d blindly.
    if isinstance(value, _SEQ):
        return claude_cli.normalise_shot_types(value)
    if isinstance(value, bytes):
        value = value.decode('utf-8', 'replace')
    return claude_cli.normalise_shot_types(str(value).split(','))


# The candidate ceiling, as the API validates it and the search phase enforces
# it. The allowed set lives in config beside the SPA's dropdown and migration
# 006's SQL default; here is only "what does this row mean".
CANDIDATE_CAPS = config.CANDIDATE_CAPS
DEFAULT_MAX_CANDIDATES = config.DEFAULT_MAX_CANDIDATES
# Nothing read out of this column may exceed the biggest choice on the menu,
# whatever wrote it. The menu itself is the API's business (routes_api refuses
# an unlisted number rather than clamping it, so the editor is never told they
# searched wider than they did); this ceiling is the fleet's.
MAX_CANDIDATE_CAP = max(CANDIDATE_CAPS)


def max_candidates_of(row_or_value):
    """A jobs row (or the raw column, or a number) -> the cap to search under.

    Takes the ROW like shot_types_of does, and for the same reason: a row read
    by a SELECT that did not ask for the column -- or from a database the
    migration has not reached -- has no such key at all.

    Two invariants, and neither is "the menu":
      - there is ALWAYS a number. Absent, unreadable or nonsensical (<= 0)
        reads as the default, never as "unbounded" -- unbounded is what reached
        336 candidates and bot-checked the fleet's IP (2026-08-11), and no job
        may be re-run into it;
      - it is never larger than MAX_CANDIDATE_CAP, so a row written by another
        build (or by hand) cannot re-create that pass either.
    A smaller number that is not on the menu is honoured as it stands: bounded
    is the property that matters, and rounding somebody's 137 up to 200 would
    spend 63 metadata calls nobody asked for.
    """
    value = row_or_value
    if value is not None and not isinstance(value, (int, float, str, bytes)):
        try:
            value = row_or_value['max_candidates']
        except (IndexError, KeyError, TypeError):
            value = None
    if value is None or isinstance(value, bool):
        return DEFAULT_MAX_CANDIDATES
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_CANDIDATES
    if n <= 0:
        return DEFAULT_MAX_CANDIDATES
    return min(n, MAX_CANDIDATE_CAP)


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
# values are always parameters, names never can be. `kind`, `shot_types` and
# `max_candidates` are absent on purpose: all three are inputs to the search
# that already ran, and a later UPDATE of one would make the job row describe a
# job nobody asked for -- including, for the cap, one whose manifest is bigger
# than the number it says it was searched under.
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
               quality='1080p', period=None, max_per_term=15, shot_types=None,
               max_candidates=None):
    """A kind='search' job. `shot_types=None` is the default selection, and
    `max_candidates=None` the default candidate ceiling.

    Both are written HERE and never again: the two Claude calls read the
    selection off the row and the search phase reads the ceiling off it, so a
    job that survives a container restart is re-run with the boxes the editor
    actually ticked and the number they submitted -- not with whatever the
    defaults have become since.
    """
    ts = now()
    try:
        cur = c.execute(
            'INSERT INTO jobs(created_by,term,term_dir,project_slug,project_label,'
            'quality,period,max_per_term,max_candidates,shot_types,phase,'
            'created_at,updated_at) '
            "VALUES(?,?,?,?,?,?,?,?,?,?,'queued',?,?)",
            (created_by, term, term_dir, project_slug, project_label, quality,
             period, max_per_term, max_candidates_of(max_candidates),
             encode_shot_types(shot_types), ts, ts))
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

    `term` and `term_dir` are both EMPTY for every job the API creates now
    (2026-08-11): a paste has no topic and no folder to sort by, and its clips
    land in the project's Youtube root. They stay in the signature because they
    are the same two columns a search job fills, and the download phase reads
    term_dir either way -- empty simply means "no subfolder".

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


# The folder every download lands under, inside the project. A SEARCH files its
# clips one level below it (`Youtube/<term_dir>/`); a PASTE has no term to sort
# by and lands in this folder itself (owner, 2026-08-11: "individual downloads
# should just go into the /youtube root for the project folder actually, I
# realised the problem with there being no term to sort the clips into
# subfolders"). An empty term_dir therefore means the root, not "unknown".
YOUTUBE_DIR = 'Youtube'


def folder_label(term_dir):
    """The folder to NAME for a stored term_dir. Empty is the Youtube root.

    Never an empty string back: '<project label>/' with nothing after it is the
    shape a badge must not have -- it reads as a broken path rather than as a
    real folder an editor can open over SMB.
    """
    return str(term_dir or '') or YOUTUBE_DIR


def ledger_where(row):
    """'<project label>/<folder>' -- what the ALREADY IN badge shows.

    The FOLDER, not the term: they differ for any term carrying <>:"/\\|?* or
    more than 80 UTF-8 bytes, and the badge is an instruction to go and look at
    a path over SMB (YTDL-31, 2026-08-11). Three cases, all of them live:
      - a search: term_dir is the folder under Youtube/;
      - a paste: term_dir is EMPTY, and the clip is in Youtube/ itself;
      - a row written before term_dir existed: NULL, falling back to the raw
        term exactly as the badge always did.
    """
    term_dir = row['term_dir']
    if term_dir is None:
        term_dir = row['term']
    return f"{row['project_label']}/{folder_label(term_dir)}"


def ledger_map(c):
    """{video_id: the ALREADY IN badge's text} for the whole ledger."""
    return {r['video_id']: ledger_where(r)
            for r in c.execute('SELECT video_id, project_label, term, term_dir '
                               'FROM downloads')}


def _term_dir_of(rel_path, term):
    """The folder a ledgered clip is actually in, relative to Youtube/.

    rel_path is written as 'Youtube/<term_dir>/<filename>' by a search's
    download and as 'Youtube/<filename>' by a paste's, so the truth is already
    in the argument list -- taking it from there rather than re-deriving
    safe_term_dirname(term) means the ledger agrees with the disk even if the
    naming rules change under it.

    '' (the Youtube root) and None (no usable path at all) are different
    answers: the first is a real location, the second is why ledger_where falls
    back to the term.
    """
    parts = [p for p in str(rel_path or '').replace('\\', '/').split('/') if p]
    if parts and parts[0] == YOUTUBE_DIR:
        return parts[1] if len(parts) >= 3 else ''
    return config.safe_term_dirname(term) if term else None


# The history panel's page size, and its ceiling. The ledger is PERMANENT and
# fleet-wide -- one row per clip the fleet has ever downloaded, never cascaded,
# never pruned -- so "show me the downloads" is a query that grows for the life
# of the product. It is read on the request thread like everything else here,
# so it is paged at the source rather than trimmed in the browser (YTDL-7's
# rule, applied to a read instead of a write).
HISTORY_PAGE = 24
MAX_HISTORY_LIMIT = 100


def recent_downloads(c, limit=HISTORY_PAGE, offset=0):
    """One page of the ledger, newest first. Bounded here, not by the caller.

    Ordered by downloaded_at and NOT by rowid: the ledger upserts on video_id,
    so a clip re-downloaded into another project keeps the rowid it was first
    written with -- ordering by that would file today's download under last
    month. rowid is the tie-break only, because downloaded_at has one-second
    resolution and a batch of forty clips can share a timestamp.
    """
    limit = max(1, min(MAX_HISTORY_LIMIT, int(limit)))
    offset = max(0, int(offset))
    return c.execute('SELECT rowid, * FROM downloads '
                     'ORDER BY downloaded_at DESC, rowid DESC LIMIT ? OFFSET ?',
                     (limit, offset)).fetchall()


def count_downloads(c):
    """How many clips the fleet has. One row per video id, so this is also the
    number the "showing N of M" line reports."""
    return c.execute('SELECT COUNT(*) n FROM downloads').fetchone()['n']


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
    # A LIST, not the stored string: the SPA renders the ticked shot types on
    # the job and in Recent searches so a week-old search is still readable,
    # and 'aerial,raw' is not something to make a browser parse. A url job
    # carries whatever the column default is and the SPA ignores it -- nothing
    # was searched for, so no selection was ever applied.
    d['shot_types'] = list(shot_types_of(row))
    # Always a number the SPA can render, even for a row that came back without
    # the column (a database the migration has not reached, a partial SELECT) --
    # the same rule shot_types is read under.
    d['max_candidates'] = max_candidates_of(row)
    return d


def video_dict(row, term_ids=None):
    d = dict(row)
    d['term_ids'] = term_ids or []
    return d


def reveal_path(row):
    """A ledger row -> the clip's path UNDER THE PROJECTS ROOT, or None.

    `rel_path` is stored relative to the project ('Youtube/<term_dir>/<file>')
    because that is what the download phase writes and what the manifest and
    the badge speak. The companion's `POST /ytdl/reveal` takes a path relative
    to the Projects root instead -- the directory that holds the project labels,
    `P:\\Projects` on a Windows editor -- because only the companion knows where
    that is on the machine it is running on, and the page (served from the NAS)
    must never learn a drive letter.

    Joined HERE rather than in app.js: the join rule is a property of how this
    app stores paths, and a browser deriving it would be a second place to get
    it wrong. Forward slashes throughout; the companion splits and rejoins.
    """
    rel = str(row['rel_path'] or '').replace('\\', '/').strip('/')
    label = str(row['project_label'] or '').replace('\\', '/').strip('/')
    if not rel or not label:
        # A row from a build that wrote no path (YTDL-15's shape) still belongs
        # in the history -- it just has no folder to offer to open.
        return None
    return f'{label}/{rel}'


def download_dict(row):
    """A ledger row as the history panel reads it.

    Everything derived is derived HERE, for the same reason ledger_where is:
    term is what the editor typed and term_dir is what exists on disk, and the
    two differ for any term carrying <>:"/\\|?* or more than 80 UTF-8 bytes
    (YTDL-31). `folder_path` is what the panel prints as the destination and it
    is honest about both shapes -- 'Youtube/<term>' for a search, plain
    'Youtube' for a paste, never a trailing separator with nothing after it.
    """
    d = dict(row)
    d.pop('rowid', None)          # a paging tie-break, not part of the contract
    term_dir = d.get('term_dir')
    if term_dir is None:
        # A row written before the column existed: read the folder back out of
        # the path, which is what ledger_add would fill the column with today.
        term_dir = _term_dir_of(d.get('rel_path'), d.get('term'))
    d['folder'] = folder_label(term_dir)
    d['folder_path'] = (f'{YOUTUBE_DIR}/{term_dir}' if term_dir else YOUTUBE_DIR)
    d['reveal_path'] = reveal_path(row)
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
