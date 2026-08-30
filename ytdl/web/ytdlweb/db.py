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
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

# For SHOT_TYPES / DEFAULT_SHOT_TYPES only, and deliberately from there rather
# than a copy here: a shot type IS its two prompt fragments, so the module that
# owns the fragments owns the key list. claude_cli imports config alone, so
# there is no cycle to fall into.
from ytdlweb import claude_cli, config

log = logging.getLogger(__name__)

# Highest schema version this codebase knows how to run against. Bump it, add
# the file to _MIGRATIONS, and give it a predicate.
CURRENT_SCHEMA_VERSION = 12

# "the version this migration produces" -> (filename, already-applied predicate).
# The predicate must answer "is this migration's effect already in the database?"
# without consulting user_version. Ordered by key. v1 is what schema.sql
# creates; everything after it is an ALTER or an index schema.sql cannot add to
# a table that already exists.
_MIGRATIONS = {
    2: ('002_downloads_term_dir.sql',
        lambda con: 'term_dir' in _columns(con, 'downloads')),
    # The index this one creates is DROPPED again by 012 (the queue), so "is
    # the index there" stopped being an honest already-applied test on
    # 2026-08-30: on every database past v12 it answers no, 003 re-creates the
    # index, and 012 -- whose own predicate then reads "not applied" -- re-runs
    # its ALTERs and dies on `duplicate column name`. The second clause is what
    # says "this database is past the point where that index existed at all".
    # The first is still the whole answer for anything between v3 and v11.
    3: ('003_one_active_job_per_editor.sql',
        lambda con: (_index_exists(con, 'idx_jobs_one_active')
                     or 'queue_position' in _columns(con, 'jobs'))),
    4: ('004_jobs_kind.sql',
        lambda con: 'kind' in _columns(con, 'jobs')),
    5: ('005_jobs_shot_types.sql',
        lambda con: 'shot_types' in _columns(con, 'jobs')),
    6: ('006_jobs_max_candidates.sql',
        lambda con: 'max_candidates' in _columns(con, 'jobs')),
    # Two tables in one file, so the predicate asks about BOTH. _apply_migration
    # wraps the script in its own transaction and sqlite's DDL is transactional,
    # so a half-applied 007 should be impossible -- but the predicate, not the
    # recorded version, is what decides here (migrations/README.md), and a
    # predicate that only looked at `jobs` would call a database with no
    # job_videos.download_host migrated and let every status post die on
    # "no such column".
    7: ('007_local_download.sql',
        lambda con: ('download_mode' in _columns(con, 'jobs')
                     and 'download_host' in _columns(con, 'job_videos'))),
    # The rights/ToS attestation record (attestation.py, COMMERCIAL_READINESS
    # item 2). A whole new table, so the predicate is simply "is it there".
    8: ('008_attestations.sql',
        lambda con: _table_exists(con, 'attestations')),
    # The search mode (visuals | news montage, 2026-08-18). One column, so the
    # predicate is the same shape 005's and 006's are.
    9: ('009_jobs_mode.sql',
        lambda con: 'mode' in _columns(con, 'jobs')),
    # WHICH of the leaseholder's computers holds the download lease
    # (data-model-7, CR-66/CR-67, 2026-08-21). One column, so the predicate is
    # the same shape 005's, 006's and 009's are, and it is inert until a
    # companion sends a machine_id.
    10: ('010_jobs_claimed_machine.sql',
         lambda con: 'claimed_machine' in _columns(con, 'jobs')),
    # The language scope and the upload-date range (2026-08-25). Three columns
    # in one file, so the predicate asks about ALL of them, the way 007's does:
    # a half-applied 011 should be impossible, but the predicate is what
    # decides (migrations/README.md).
    11: ('011_jobs_term_scope_dates.sql',
         lambda con: {'term_scope', 'date_from', 'date_to'}
         <= set(_columns(con, 'jobs'))),
    # The term review and the queue (2026-08-30). FOUR columns across two
    # tables AND a dropped index, so the predicate asks about all five: this is
    # the first migration that REMOVES something, and an "already applied" that
    # only looked at the columns would leave idx_jobs_one_active in place on a
    # database whose ALTERs had landed -- which is the one state where a second
    # queued job raises IntegrityError and the queue silently holds one thing.
    12: ('012_terms_review_and_queue.sql',
         lambda con: ({'translation', 'enabled'} <= set(_columns(con, 'job_terms'))
                      and {'queue_position', 'auto_terms'} <= set(_columns(con, 'jobs'))
                      and not _index_exists(con, 'idx_jobs_one_active'))),
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

# WHAT THE SEARCH IS FOR (2026-08-18): 'visuals' is b-roll to cut under
# something else, 'news' is a montage made OF the reporting, where the clip's
# own audio is what gets used. It chooses the framing of both AI calls; the
# rubrics and the reason they differ are in claude_cli.MODES.
#
# Stored per job like shot_types is, and read back the same tolerant way: an old
# row (or a row from a database this migration has not reached) is 'visuals',
# which is the only search this app ran before the modes existed.
#
# Nothing to do with `download_mode` / `mode_lock`, which are about which
# machine fetches the clips.
MODES = claude_cli.MODES
DEFAULT_MODE = claude_cli.DEFAULT_MODE

# WHICH LANGUAGES THE SEARCH RUNS IN (2026-08-25): 'both' | 'en' | 'zh' |
# 'exact'. Orthogonal to the mode; the table and what each value does to the
# two AI calls are in claude_cli.TERM_SCOPES. Read back the same tolerant way
# the mode is: an old row is 'both', the only search before the scopes existed.
TERM_SCOPES = claude_cli.TERM_SCOPES
DEFAULT_TERM_SCOPE = claude_cli.DEFAULT_TERM_SCOPE


def encode_shot_types(shot_types, mode=None):
    """A selection -> the column value. None means the MODE's preset.

    `mode` matters only for None (a caller with no opinion, or a client that
    predates the boxes): a news job nobody sent a selection for is stored with
    the coverage preset, not the footage one.
    """
    return ','.join(claude_cli.normalise_shot_types(shot_types, mode))


def mode_of(row_or_value):
    """A jobs row (or the raw column, or a string) -> 'visuals' | 'news'.

    Takes the ROW for the same reason shot_types_of does: a row read from a
    database the migration has not reached, or by a SELECT that did not ask for
    the column, has no such key at all -- and that reads as 'visuals', which is
    the search those rows actually ran.
    """
    value = row_or_value
    if value is not None and not isinstance(value, (str, bytes)):
        try:
            value = row_or_value['mode']
        except (IndexError, KeyError, TypeError):
            value = None
    if isinstance(value, bytes):
        value = value.decode('utf-8', 'replace')
    return claude_cli.normalise_mode(value)


def term_scope_of(row_or_value):
    """A jobs row (or the raw column, or a string) -> one of TERM_SCOPES.

    Takes the ROW for the reason mode_of does: a row from a database the
    migration has not reached, or from a SELECT that did not ask for the
    column, has no such key -- and that reads as 'both', which is the search
    those rows actually ran.
    """
    value = row_or_value
    if value is not None and not isinstance(value, (str, bytes)):
        try:
            value = row_or_value['term_scope']
        except (IndexError, KeyError, TypeError):
            value = None
    if isinstance(value, bytes):
        value = value.decode('utf-8', 'replace')
    return claude_cli.normalise_term_scope(value)


def _column(row, key):
    """row[key] or None, for a row that may predate the column."""
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def auto_terms_of(row):
    """A jobs row -> does this job SKIP the term review.

    Tolerant like every other reader here: a row from a database the migration
    has not reached, or from a SELECT that did not ask for the column, has no
    such key -- and that reads as False, the reviewed path, which is the safe
    direction. A job that stops for a person can always be sent on by that
    person; one that skipped the stop has already spent the search.
    """
    return bool(_column(row, 'auto_terms'))


def date_range_of(row):
    """A jobs row -> (date_from, date_to) as YYYYMMDD strings or None each.

    Tolerant like the other readers: a row without the columns, or one holding
    something that is not eight digits, has no bound on that side. The API is
    where a malformed date is refused; here it must never fail a job.
    """
    out = []
    for key in ('date_from', 'date_to'):
        v = _column(row, key)
        if isinstance(v, bytes):
            v = v.decode('utf-8', 'replace')
        v = str(v or '').strip()
        out.append(v if len(v) == 8 and v.isdigit() else None)
    return tuple(out)


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
PHASES = ('queued', 'generating_terms', 'terms_review', 'searching',
          'enriching', 'filtering', 'ready_for_review', 'downloading',
          'done', 'failed', 'cancelled')
TERMINAL = ('done', 'failed', 'cancelled')
# Phases whose work is mid-flight and must be restarted after a container
# restart. `downloading` is deliberately absent: it is resumed, not restarted.
RESUMABLE = ('generating_terms', 'searching', 'enriching', 'filtering')

# THE PHASES A WORKER IS ACTUALLY INSIDE (2026-08-30), and so the ones that
# make an editor's queue wait. `queued` is not here (it is the waiting), and
# neither are the two phases that are waiting for a PERSON -- `terms_review`
# and `ready_for_review`. That is the whole point of the queue: a manifest an
# editor has not looked at for a week used to block every later search
# (YTDL-25's 409), and a job parked for a human is not work in flight, so the
# next search may as well be running while they get to it.
BUSY = ('generating_terms', 'searching', 'enriching', 'filtering', 'downloading')

# Columns the worker and the API are allowed to write through _update(). A
# whitelist because the column name is interpolated into the SQL string --
# values are always parameters, names never can be. `kind`, `mode`,
# `shot_types` and `max_candidates` are absent on purpose: all four are inputs
# to the search that already ran, and a later UPDATE of one would make the job
# row describe a job nobody asked for -- including, for the cap, one whose
# manifest is bigger than the number it says it was searched under.
_JOB_COLS = frozenset({
    'phase', 'error', 'terms_total', 'terms_done', 'candidates',
    'enrich_total', 'enrich_done', 'dl_total', 'dl_done', 'dl_failed',
    'cancel_requested', 'quality', 'period', 'max_per_term'})
_VIDEO_COLS = frozenset({
    'url', 'title', 'channel', 'duration', 'upload_date', 'view_count',
    'thumbnail', 'meta_error', 'relevant', 'relevance_note', 'duplicate',
    'duplicate_of', 'selected', 'dl_state', 'dl_error', 'filepath',
    'download_host'})

# The claim/lease columns are deliberately NOT in _JOB_COLS. Every one of them
# is written by a compare-and-set below (claim_download / heartbeat_download /
# end_lease / reclaim_download / lock_mode), because "who holds this job" is
# decided by a WHERE clause and not by a caller that read the row a moment ago
# -- a set_job() path would be a second way to take a lease, with no CAS in it
# (docs/YTDL_LOCAL_DOWNLOAD.md §3).
MODE_SERVER = 'server'
MODE_LOCAL = 'local'

# `queue_position` and `auto_terms` are not in _JOB_COLS either, for two
# different reasons. auto_terms is an INPUT to the job, like kind and mode: a
# later UPDATE of it would make the row describe a job nobody asked for.
# queue_position is written by move_in_queue below, which renumbers a whole
# queue in one transaction -- a set_job() path would be a second way to write
# one job's number without touching the others, which is how two jobs end up
# sharing a position and the [ UP ] button starts doing nothing.


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

def next_queue_position(c, created_by):
    """The number the editor's NEXT job goes to the back of the queue with.

    1-based, and derived from the queued rows rather than counted: a queue that
    has had jobs cancelled out of the middle of it still has to hand the next
    arrival a number behind everything in it. move_in_queue renumbers 1..n, so
    the max is the length in practice -- this is what keeps it true when it is
    not.
    """
    row = c.execute("SELECT MAX(queue_position) AS m FROM jobs "
                    "WHERE created_by=? AND phase='queued'",
                    (created_by,)).fetchone()
    return int((row and row['m']) or 0) + 1


def busy_job(c, user):
    """The editor's job that is actually being WORKED ON, or None (BUSY).

    This is what the queue waits behind, and what the API asks before it tells
    a new job it is queued behind something. Deliberately not active_job: a job
    parked at terms_review or ready_for_review is waiting for the person, and a
    person is not a worker.
    """
    ph = ','.join('?' * len(BUSY))
    return c.execute(f'SELECT * FROM jobs WHERE created_by=? AND phase IN ({ph}) '
                     'ORDER BY id LIMIT 1', (user, *BUSY)).fetchone()


def queued_jobs(c, user):
    """The editor's waiting jobs, in the order they will run.

    queue_position first and the id only as a tie-break, so a queue written by
    a build that had no positions (or one renumbered mid-write) still comes
    back oldest-first rather than in whatever order SQLite felt like.
    """
    return c.execute("SELECT * FROM jobs WHERE created_by=? AND phase='queued' "
                     'ORDER BY queue_position, id', (user,)).fetchall()


def move_in_queue(c, user, job_id, position):
    """Move one of the editor's queued jobs to `position` (1-based). -> the
    new order, or None when that job is not in the queue.

    The WHOLE queue is renumbered 1..n in one transaction rather than the one
    row being written: positions arrive from a database that has had jobs
    cancelled out of it and from clients that may both be pressing [ UP ], and
    a scheme that only rewrites the moved row leaves duplicates behind, which
    read as an arbitrary order the next time anything sorts by them.

    Out-of-range positions are CLAMPED, not refused: [ UP ] on the first row is
    a no-op an editor will press, not an error worth a toast.
    """
    order = [r['id'] for r in queued_jobs(c, user)]
    if job_id not in order:
        return None
    order.remove(job_id)
    where = max(0, min(len(order), int(position) - 1))
    order.insert(where, job_id)
    ts = now()
    for i, jid in enumerate(order, start=1):
        c.execute('UPDATE jobs SET queue_position=?, updated_at=? WHERE id=?',
                  (i, ts, jid))
    c.commit()
    return order


def create_job(c, created_by, term, term_dir, project_slug, project_label,
               quality='1080p', period=None, max_per_term=15, shot_types=None,
               max_candidates=None, mode=None, term_scope=None, date_from=None,
               date_to=None, auto_terms=False):
    """A kind='search' job. `shot_types=None` is the mode's preset selection,
    `max_candidates=None` the default candidate ceiling, `mode=None` the
    default search mode ('visuals'), `term_scope=None` the default language
    scope ('both'), and a None date is no bound on that side.

    All three are written HERE and never again: the two Claude calls read the
    mode and the selection off the row and the search phase reads the ceiling
    off it, so a job that survives a container restart is re-run with the rubric
    the editor chose, the boxes they actually ticked and the number they
    submitted -- not with whatever the defaults have become since.

    `auto_terms` (2026-08-30) is the same kind of input and is stored for the
    same reason: True skips the term review and searches everything, which is
    the headless path a script takes and never what the SPA sends.

    ALWAYS `queued`, whether the editor is busy or not: `queued` is where the
    queue waits, and claim_next_job is the one place that decides whose turn it
    is. A handler that started a job itself when the editor looked idle would
    be a second scheduler, racing the worker with a read-then-write.
    """
    ts = now()
    try:
        cur = c.execute(
            'INSERT INTO jobs(created_by,term,term_dir,project_slug,project_label,'
            'quality,period,max_per_term,max_candidates,mode,shot_types,'
            'term_scope,date_from,date_to,auto_terms,queue_position,phase,'
            'created_at,updated_at) '
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'queued',?,?)",
            (created_by, term, term_dir, project_slug, project_label, quality,
             period, max_per_term, max_candidates_of(max_candidates),
             claude_cli.normalise_mode(mode),
             encode_shot_types(shot_types, mode),
             claude_cli.normalise_term_scope(term_scope),
             date_from or None, date_to or None, 1 if auto_terms else 0,
             next_queue_position(c, created_by), ts, ts))
    except sqlite3.IntegrityError:
        # Nothing in the schema refuses a second job any more (migrations/012
        # dropped idx_jobs_one_active), so reaching this is a genuine
        # constraint failure rather than the YTDL-25 race. The rollback stays,
        # and it is not decoration: a failed INSERT leaves this connection's
        # implicit transaction OPEN, holding a write lock. Connections here are
        # per-thread and live forever, so an un-rolled-back one would block
        # every later write on the request threadpool ("database is locked",
        # 30 s at a time).
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
    later: a jobs row with no videos would be a job that can never finish, and
    before the queue (YTDL-25's one-active-job rule) that locked the editor out
    of the whole app with nothing to cancel from the UI. It queues rather than
    blocks now, but a queue entry that downloads nothing is still a queue entry
    somebody has to notice and cancel.

    It takes a queue_position exactly as a search job does: a paste is a job
    like any other and waits its turn behind whatever the editor has running.
    """
    ts = now()
    pending = [v for v in videos if not v.get('duplicate_of')]
    try:
        cur = c.execute(
            'INSERT INTO jobs(created_by,kind,term,term_dir,project_slug,'
            'project_label,quality,dl_total,queue_position,phase,created_at,'
            'updated_at) '
            "VALUES(?,?,?,?,?,?,?,?,?,'queued',?,?)",
            (created_by, KIND_URLS, term, term_dir, project_slug,
             project_label, quality, len(pending),
             next_queue_position(c, created_by), ts, ts))
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
    """The job this editor's page should be attached to, or None.

    Their oldest non-terminal job that is NOT waiting in the queue -- the one
    being worked on, or parked at terms_review / ready_for_review for them to
    look at. Both of those count as active: each holds something the editor has
    not dealt with yet, and a page that showed them nothing is a page that lost
    their search.

    The head of the queue is the fallback, so a page that loads in the second
    between "the job was created" and "the worker claimed it" still attaches to
    something. It is deliberately the LAST resort: a queued job has nothing to
    show yet, and the running one does.

    Before 2026-08-30 this was "the caller's one non-terminal job" and its
    answer was what every second search was refused with (YTDL-25's 409). The
    refusal is gone; the question -- what is this editor's page about -- is
    still the same one.
    """
    ph = ','.join('?' * len(TERMINAL))
    row = c.execute(
        f"SELECT * FROM jobs WHERE created_by=? AND phase NOT IN ({ph}) "
        "AND phase != 'queued' ORDER BY id LIMIT 1", (user, *TERMINAL)).fetchone()
    if row is not None:
        return row
    return c.execute("SELECT * FROM jobs WHERE created_by=? AND phase='queued' "
                     'ORDER BY queue_position, id LIMIT 1', (user,)).fetchone()


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


# The phases no worker is inside: `queued` has not been claimed, and
# `terms_review` / `ready_for_review` are waiting for a human. Anything else is
# mid-phase and the flag is the only safe way to stop it.
#
# terms_review joined them 2026-08-30 and it had to: it is a job parked in
# front of a person, exactly like ready_for_review, and YTDL-1 is what happens
# when cancel is a no-op on one of those -- {ok:true}, nothing changes, and the
# editor is left with a job they cannot get rid of.
IDLE = ('queued', 'terms_review', 'ready_for_review')


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

    A job an editor's companion is downloading right now (an unexpired lease,
    docs/YTDL_LOCAL_DOWNLOAD.md §3) is INVISIBLE here rather than skipped by the
    caller. Two reasons, and the second is the one that bites: a skip decided
    after the row is handed over makes _tick report "I did work", and the loop
    then re-ticks immediately -- a three-minute lease would be three minutes of
    a spinning CPU inside the dashboard's single uvicorn process. Filtering in
    SQL also lets the NEXT job through, which is what "one at a time" should
    have meant all along: an editor downloading locally does not queue the
    fleet behind them.

    THE QUEUE (2026-08-30) is the NOT EXISTS below, and it is the only place
    that decides whose turn it is. A `queued` job is startable when its own
    editor has no BUSY job -- nothing else about it matters, and in particular
    another editor's running job never holds it back. `terms_review` and
    `ready_for_review` are not busy (BUSY says why), so a search parked in
    front of a person lets that person's next search start.
    """
    busy = ','.join('?' * len(BUSY))
    return c.execute(
        f'SELECT * FROM jobs AS j WHERE (j.phase IN ({busy}) OR '
        "  (j.phase='queued' AND NOT EXISTS ("
        '     SELECT 1 FROM jobs AS b WHERE b.created_by=j.created_by '
        f'       AND b.phase IN ({busy})))) '
        "AND NOT (j.download_mode='local' AND j.lease_expires_at IS NOT NULL "
        '          AND j.lease_expires_at > ?) '
        # Work already in flight before work not yet started, then the editor's
        # own queue order, then oldest first. The last two used to be one
        # `ORDER BY id`, and for a single job they still are.
        "ORDER BY (CASE WHEN j.phase='queued' THEN 1 ELSE 0 END), "
        "         (CASE WHEN j.phase='queued' THEN j.queue_position ELSE 0 END), "
        '         j.id LIMIT 1', (*BUSY, *BUSY, now())).fetchone()


# ----------------------------------------- the claim/lease (requester-first)
# docs/YTDL_LOCAL_DOWNLOAD.md §3. One holder per job; the holder can vanish
# without telling anyone, so possession EXPIRES rather than being released.
# Every write below is a compare-and-set with the whole rule in its WHERE
# clause -- read-then-write would be a race between two browser tabs, and
# "which machine is downloading these clips" is not a question two answers can
# be given to.

def _future(seconds):
    """now() + seconds, in the exact shape now() produces.

    Both halves of every lease comparison come from here or from now(), which
    is why comparing these timestamps as STRINGS is sound: same producer, same
    '+00:00' offset, same second resolution, so lexicographic order is
    chronological order.
    """
    return (datetime.now(timezone.utc)
            + timedelta(seconds=max(0, int(seconds)))).isoformat(timespec='seconds')


def _column(row, key):
    """row[key], or None if this row does not carry the column at all.

    Same defensive read shot_types_of makes, for the same two cases: a partial
    SELECT, and a database the migration has not reached yet (in which case
    there is no lease, which is the correct answer).
    """
    if row is None:
        return None
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def lease_active(job, at=None):
    """Is a LOCAL executor holding this job right this second?

    The one question the worker asks before touching a `downloading` job, and
    the one the fleet endpoints ask before believing a status post.
    """
    if _column(job, 'download_mode') != MODE_LOCAL:
        return False
    expires = _column(job, 'lease_expires_at')
    return bool(expires and str(expires) > (at or now()))


def claimed_machine_of(job):
    """The machine_id the leaseholder announced itself with, or None.

    None is "the holder did not say" (data-model-7, CR-66, 2026-08-21): a row
    written before migration 010, or a claim from a companion that predates the
    field. It is deliberately NOT "some other machine" -- see lease_held_by.
    """
    value = str(_column(job, 'claimed_machine') or '').strip()
    return value or None


def lease_held_by(job, editor, machine=None):
    """Is (editor, machine) the holder recorded on this row? Ignores expiry.

    THE (editor, machine_id) KEY (data-model-7, CR-66, 2026-08-21). The lease
    used to be keyed on the editor's NAME, and a name is a person: CLAUDE.md's
    rule that a sync plan belongs to a COMPUTER applies here too, because one
    editor's laptop and desktop are two executors, and both used to read as
    "the same holder refreshing" -- so both downloaded the same clips into two
    trees and each posted terminal statuses for the other's work.

    Two Nones, and they mean different things on purpose:
      - `machine` None is a CALLER that does not say which machine it is (any
        companion older than this change). It keeps the old per-editor answer,
        which is the whole reason this can ship before the companion half.
      - a NULL `claimed_machine` is a HOLDER that did not say. Same reasoning
        in the other direction: refusing it would strand a live lease taken by
        an older build the moment its own companion upgraded mid-job.
    """
    name = str(editor or '').strip()
    if not name or str(_column(job, 'claimed_by') or '') != name:
        return False
    held = claimed_machine_of(job)
    return machine is None or held is None or held == str(machine).strip()


def is_leaseholder(job, editor, at=None):
    """Is `editor` the live leaseholder of this job?

    `editor` IS REQUIRED (H5, 2026-08-17). It used to accept None as "somebody
    holds it and the caller did not say who", because the identity a companion
    sent was self-asserted and the shared fleet token was the whole trust
    boundary -- which meant a name was never the thing deciding anything.
    routes_fleet now verifies a signed identity token before it calls this, so
    a blank name here is a caller bug, and answering True to it would hand any
    token-holding machine somebody else's job.

    Per-EDITOR on purpose, unlike a claim (data-model-7, CR-66, 2026-08-21):
    the manifest and the per-clip status posts carry no machine_id, and the
    machine that could not claim never gets a job id to post about, so the
    (editor, machine) key is enforced at the one door that hands the lease out.
    """
    return lease_active(job, at) and lease_held_by(job, editor)


def claim_download(c, job_id, editor, lease_seconds, at=None, machine=None):
    """Take (or refresh) the lease. -> did it happen.

    THE compare-and-set. Everything that decides the answer is in the WHERE
    clause:
      - the job must still be in the download phase. A finished, failed or
        cancelled job has nothing to fetch, and a job at ready_for_review has
        not been asked for yet;
      - mode_lock='server' pins it to the NAS worker -- set by the editor (plan
        §9) or by a reclaim, which is what makes a reclaim one-way (§3);
      - a pending cancel means nobody downloads it, here or on the NAS
        (YTDL-WEB-1, 2026-08-14): the flag is honoured by run_job, which the
        worker cannot reach while a companion holds the lease, so a job handed
        out with a cancel already on it downloads to completion and is
        cancelled afterwards;
      - and it must be free: not local at all, or leased to THIS (editor,
        machine) -- a refresh, because the companion re-announcing itself after
        a restart is not a second holder -- or leased to somebody whose lease
        has run out.

    `machine` is the companion-minted machine_id (data-model-7, CR-66,
    2026-08-21). Passing it narrows the refresh from the editor to the
    COMPUTER, which is what stops one person's laptop and desktop both reading
    as the same holder and downloading the same clips into two trees. Omitting
    it is the pre-2026-08-21 behaviour exactly, so an older companion is not
    refused, and lease_held_by says why an unknown holder is treated the same
    way.

    A won claim WRITES `machine` as given, NULL included: the column records
    what the current holder said it is, and a claim that cannot say leaves
    "unknown" behind rather than a stale id belonging to somebody else's run.
    """
    at = at or now()
    machine = str(machine or '').strip() or None
    # Built here rather than as one SQL string with an `IS NULL` test on a
    # bound parameter: the two cases are different RULES (per-computer against
    # per-person), and reading which one a call gets should not require
    # evaluating three-valued logic in your head.
    if machine is None:
        refresh, refresh_args = 'claimed_by=?', [editor]
    else:
        refresh = '(claimed_by=? AND (claimed_machine IS NULL OR claimed_machine=?))'
        refresh_args = [editor, machine]
    cur = c.execute(
        f"UPDATE jobs SET download_mode='{MODE_LOCAL}', claimed_by=?, "
        'claimed_machine=?, lease_expires_at=?, updated_at=? '
        "WHERE id=? AND phase='downloading' "
        f"AND (mode_lock IS NULL OR mode_lock<>'{MODE_SERVER}') "
        'AND COALESCE(cancel_requested,0)=0 '
        f"AND (download_mode<>'{MODE_LOCAL}' OR {refresh} "
        '     OR lease_expires_at IS NULL OR lease_expires_at<=?)',
        [editor, machine, _future(lease_seconds), at, job_id, *refresh_args, at])
    c.commit()
    return bool(cur.rowcount)


def heartbeat_download(c, job_id, editor, lease_seconds, at=None):
    """Extend a live lease. -> did it happen.

    Deliberately NOT a re-claim: an expired lease is not extended here, because
    by then the worker may already have taken the job back and started
    downloading it (§3, no ping-pong). The companion is told 410 and stops.
    """
    at = at or now()
    cur = c.execute(
        'UPDATE jobs SET lease_expires_at=?, updated_at=? '
        f"WHERE id=? AND download_mode='{MODE_LOCAL}' AND claimed_by=? "
        'AND lease_expires_at>?',
        (_future(lease_seconds), at, job_id, editor, at))
    c.commit()
    return bool(cur.rowcount)


def expire_lease(c, job_id, at=None):
    """Wind a live lease back to NOW. -> did anything change.

    THE STOP SIGNAL, and deliberately the only one (YTDL-WEB-1/-2,
    2026-08-14). Two things end a local download from the server side -- the
    editor cancelling the job, and the editor pinning it to the server -- and
    both used to be silent: `cancel_requested` is read inside run_job, which
    the worker cannot reach while a lease is live (claim_next_job hides the
    job), and `mode_lock` was read only by claim_download, which a companion
    already heartbeating never calls again. Either way the executor renewed its
    lease every 30 s and downloaded all 41 clips onto a machine whose owner had
    asked it to stop.

    Expiring rather than reclaiming, and expiring rather than adding predicates
    to heartbeat_download, because expiry is the path the whole feature is
    already built around: the companion's next call finds it is no longer the
    leaseholder and stops (routes_fleet answers 410 to every way a lease can
    end, and ytdl_executor stops on nothing else), claim_next_job stops hiding
    the job, and _phase_download runs the SAME _reclaim_local_job it runs for a
    laptop that closed -- which is what credits the clips that did land and
    re-queues the ones that did not. One reclaim path, not three.
    """
    at = at or now()
    cur = c.execute(
        'UPDATE jobs SET lease_expires_at=?, updated_at=? '
        f"WHERE id=? AND download_mode='{MODE_LOCAL}' "
        'AND lease_expires_at IS NOT NULL AND lease_expires_at>?',
        (at, at, job_id, at))
    c.commit()
    return bool(cur.rowcount)


def end_lease(c, job_id, editor=None, at=None):
    """The local executor is finished with this job. -> did it happen.

    What is left of the job is the SERVER's: the manifest, the `done` phase,
    and one retry of anything that failed on the editor's machine (§2 step 7).
    So the mode goes back to 'server' -- honestly, because that is where the
    remaining work runs -- while `claimed_by` STAYS as the record of who
    fetched the clips, and every clip row keeps its own `download_host`.

    mode_lock is set at the same time so nothing can re-claim a job whose
    close-out the worker is now performing, and so the worker's own
    reclaim-on-expiry path (which only looks at download_mode='local') does not
    mistake an orderly hand-back for an abandoned laptop.
    """
    args = [at or now(), job_id]
    sql = (f"UPDATE jobs SET download_mode='{MODE_SERVER}', "
           'lease_expires_at=NULL, '
           f"mode_lock='{MODE_SERVER}', updated_at=? "
           f"WHERE id=? AND download_mode='{MODE_LOCAL}'")
    if editor is not None:
        sql += ' AND claimed_by=?'
        args.append(editor)
    cur = c.execute(sql, args)
    c.commit()
    return bool(cur.rowcount)


def reclaim_download(c, job_id, at=None):
    """The server takes an abandoned job back. -> did anything change.

    One-way (§3): mode_lock='server' means the companion that went away cannot
    take it again when the laptop wakes up and finds a stale job id in its
    queue, and the badge flips to "downloading on the server" because a silent
    executor swap is how editors conclude features are broken (§9).
    """
    # claimed_machine goes with claimed_by (data-model-7, CR-66, 2026-08-21):
    # the two are one fact, and a machine id left behind on a job the server
    # has taken back would name a holder that no longer exists.
    cur = c.execute(
        f"UPDATE jobs SET download_mode='{MODE_SERVER}', claimed_by=NULL, "
        'claimed_machine=NULL, '
        f"lease_expires_at=NULL, mode_lock='{MODE_SERVER}', updated_at=? "
        'WHERE id=?', (at or now(), job_id))
    c.commit()
    return bool(cur.rowcount)


def lock_mode(c, job_id, mode=MODE_SERVER):
    """Pin a job to an executor, and end the run it is pinned away from.

    "Download on the server instead" (plan §9) is the escape hatch for an
    editor on hotel wifi with 9 GB left to fetch, so the pin ALONE was the
    whole feature missing (YTDL-WEB-2, 2026-08-14): mode_lock is read by
    claim_download and by nothing else, and a companion that is already
    heartbeating never claims again -- so the click set a column, the toast
    promised a hand-back, and all 86 clips carried on over the hotel
    connection with the badge still reading "downloading on your machine". The
    only state the lock took effect in was the one where the job was on the
    server already.

    This version had a reason, and it is worth keeping the answer to it: the
    original refused to yank "every clip in flight, and the .part litter to
    prove it". The executor is strictly sequential, so exactly ONE clip is ever
    in flight, and the companion's own 410 path kills it and clears that clip's
    id-scoped litter before it stops -- which the server's reclaim then
    re-queues. One partly-fetched clip is what the hand-back costs, and an
    editor who asked to stop using their connection has already priced it.

    Only a lock TO the server ends a lease; there is no lock to local (the
    local executor is an offer the requester's machine makes, not something
    the server can compel), so nothing here can take a job off the worker.
    """
    c.execute('UPDATE jobs SET mode_lock=?, updated_at=? WHERE id=?',
              (mode, now(), job_id))
    c.commit()
    if mode == MODE_SERVER:
        expire_lease(c, job_id)


def clear_mode_lock(c, job_id):
    """Forget a per-run pin. Called when the editor asks for work again.

    end_lease pins a job to the server on the ORDINARY close-out as well as on
    a reclaim, and nothing ever cleared it -- so a job that ran locally once
    could never run locally again, and the YTDL-16 retry path (press DOWNLOAD
    on a `done` job to re-fetch the clips that failed) silently ran from the
    NAS's IP: the exact IP whose bot-checks the failed clips are most likely to
    have come from (YTDL-WEB-7, 2026-08-14).

    Safe precisely because start_download is the only caller and it accepts
    only `ready_for_review` and `done`: there is no run in flight for this to
    unpin, so neither the close-out pin nor the reclaim pin is undermined --
    both are about the run that just ended, and this is the next one.

    It clears the whole of the last run's EXECUTOR STATE, not just the pin
    (CR-37, 2026-08-19). Clearing the pin alone lasted two milliseconds:

        06:10:15.477  POST /jobs/50/download  200      <- pin cleared here
        06:10:15.479  job 50: the local download lease held by ruskin expired;
                      the server is taking the job back
        06:10:15.592  POST /jobs/50/claim     410 "pinned to the server"

    `download_mode` stayed `local` from a run that had ended half an hour
    earlier -- a job that finishes while local keeps the value, and a `done`
    job is never picked up again for the worker to reclaim it. So the nudge
    this same request sends took `_phase_download` down the reclaim path for a
    dead run, and `reclaim_download` re-pinned the job to the server (correctly:
    reclaim is one-way WITHIN a run). The editor's machine then had its claim
    refused on every retry, for good.

    Resetting all of them is safe for the same reason clearing the pin is:
    the accepted phases mean the previous run is OVER, so there is no lease to
    preserve and nothing in flight to credit. The reclaim's accounting is not
    lost either -- that run's clips are already `done` or `failed` on their
    rows, and mark_pending (which start_download calls next) re-queues exactly
    the ones that failed or were never fetched, which is the same set the
    reclaim would have produced.
    """
    # ...five columns since 2026-08-21: claimed_machine is half of "who held
    # the last run" (data-model-7, CR-66) and clearing one without the other
    # would leave the next claim comparing against a dead run's machine id.
    c.execute("UPDATE jobs SET mode_lock=NULL, download_mode=?, claimed_by=NULL, "
              'claimed_machine=NULL, lease_expires_at=NULL, updated_at=? '
              'WHERE id=?',
              (MODE_SERVER, now(), job_id))
    c.commit()


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

def add_term(c, job_id, term, lang, source, english_gloss=None,
             translation=None):
    """-> term id. Returns the existing id if the term is already on the job.

    Duplicates are expected, not exceptional: Claude regularly hands back the
    editor's own phrase as one of its English variants.

    `translation` (2026-08-30) is what the term review prints in brackets. It
    defaults to the gloss because for a Chinese query they are the same
    sentence and asking the model twice for it would be a second AI turn; the
    editor's own term is the case where they differ, because nothing ever
    glossed that one.

    Every term arrives ENABLED (the column's default): the review is an
    unticking exercise, and a job whose terms all arrived unticked would search
    nothing at all if the editor simply pressed on.
    """
    if translation is None:
        translation = english_gloss
    c.execute('INSERT OR IGNORE INTO job_terms(job_id,term,lang,english_gloss,'
              'translation,source) VALUES(?,?,?,?,?,?)',
              (job_id, term, lang, english_gloss, translation or None, source))
    c.commit()
    # Re-read rather than trust lastrowid: after an IGNOREd insert it still
    # holds whatever this connection wrote last, which would silently attribute
    # every hit of a repeated term to some other term's id.
    return c.execute('SELECT id FROM job_terms WHERE job_id=? AND term=?',
                     (job_id, term)).fetchone()['id']


def set_translation(c, term_id, translation):
    """Fill in a term's bracketed gloss after the fact. -> did it change one.

    For the EDITOR'S OWN term (worker._phase_generate_terms): it is written
    first and unconditionally, before the model has been asked anything, so its
    translation can only arrive once the reply is in. Only ever fills a BLANK
    one -- a gloss that is already there was written by the call that made the
    term, and this is a best-effort match on the same text.
    """
    translation = str(translation or '').strip()
    if not translation:
        return False
    cur = c.execute('UPDATE job_terms SET translation=? WHERE id=? AND '
                    "(translation IS NULL OR translation='')",
                    (translation, term_id))
    c.commit()
    return bool(cur.rowcount)


def terms(c, job_id):
    return c.execute('SELECT * FROM job_terms WHERE job_id=? ORDER BY id',
                     (job_id,)).fetchall()


def enabled_terms(c, job_id):
    """The terms the editor left ticked at the review. What gets searched."""
    return c.execute('SELECT * FROM job_terms WHERE job_id=? AND enabled=1 '
                     'ORDER BY id', (job_id,)).fetchall()


def set_terms_enabled(c, job_id, wanted):
    """Tick exactly `wanted` and untick the rest. -> how many are ticked.

    `wanted` is term ids or term TEXT, mixed, because both are things a caller
    legitimately has: the SPA holds the ids the poll gave it, and a script
    driving this by hand has the queries it read. Anything unrecognised is
    ignored rather than refused -- the answer says how many ended up ticked,
    which is the number that matters and the one the caller checks.

    ONE statement per column value, not one per term: this is the whole of what
    the review writes and it must not half-apply.
    """
    ids, texts = set(), set()
    for w in wanted or ():
        if isinstance(w, bool):
            continue
        if isinstance(w, int):
            ids.add(w)
            continue
        s = str(w).strip()
        if not s:
            continue
        if s.isdigit():
            ids.add(int(s))
        texts.add(s)
    on = [t['id'] for t in terms(c, job_id)
          if t['id'] in ids or t['term'] in texts]
    if on:
        ph = ','.join('?' * len(on))
        c.execute(f'UPDATE job_terms SET enabled=1 WHERE job_id=? AND id IN ({ph})',
                  (job_id, *on))
        c.execute(f'UPDATE job_terms SET enabled=0 WHERE job_id=? AND id NOT IN ({ph})',
                  (job_id, *on))
    else:
        c.execute('UPDATE job_terms SET enabled=0 WHERE job_id=?', (job_id,))
    c.commit()
    return len(on)


def unsearched_terms(c, job_id):
    """The ticked terms this job has not searched yet.

    `enabled=1` since 2026-08-30: the search phase reads this and nothing else,
    so an unticked term is not "skipped later", it is never looked at. A job
    that never stopped at the review has every term ticked, which is the
    column's default and what every job before the review ran as.
    """
    return c.execute('SELECT * FROM job_terms WHERE job_id=? AND searched=0 '
                     'AND enabled=1 ORDER BY id', (job_id,)).fetchall()


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


def begin_download(c, job_id, video_id):
    """Take ONE clip: pending -> downloading, compare-and-set. -> is it ours.

    The row is the boundary between the two executors, and it was being taken
    too late (YTDL-WEB-4, 2026-08-14). The worker checked the job's LEASE at the
    top of each iteration but did not write `downloading` until after the dedupe
    re-check -- which for a paste is an rglob of the project's whole Youtube
    tree, ~1 s on the NAS mount. A claim landing inside that window is invisible
    to the worker for the rest of the clip, and pending_videos (which the
    manifest the companion immediately asks for is built from) still lists it:
    two yt-dlp processes writing the same `[id]` fragments into one directory,
    each one's give-up path deleting the other's resume state.

    False means somebody else has it -- the companion's `downloading` status
    post, or a second pass of this loop -- and the caller skips the clip. A row
    left `downloading` by a crash is put back by reset_stale_jobs on boot, the
    same repair it has always had.
    """
    cur = c.execute("UPDATE job_videos SET dl_state='downloading' "
                    "WHERE job_id=? AND video_id=? AND dl_state='pending'",
                    (job_id, video_id))
    c.commit()
    return bool(cur.rowcount)


# What "this job's downloads are still going" means, in one place. Both states
# count: `pending` is not started, `downloading` is in flight, and the fleet
# status route asks "was that the last clip?" after every post.
UNFINISHED_STATES = ('pending', 'downloading')


def unfinished_downloads(c, job_id):
    """How many clips are still pending or in flight."""
    ph = ','.join('?' * len(UNFINISHED_STATES))
    return c.execute(f'SELECT COUNT(*) n FROM job_videos WHERE job_id=? AND '
                     f'dl_state IN ({ph})',
                     (job_id, *UNFINISHED_STATES)).fetchone()['n']


def finish_download(c, job_id, video_id, state, **cols):
    """CAS one clip to a TERMINAL dl_state. -> did THIS call move the row.

    begin_download's twin, at the other end of a clip (ytdl-web-3,
    2026-08-21). The worker's own terminal writes are reached once per clip by
    construction; the companion's are an HTTP POST, and since CR-31 its
    FleetClient re-sends any call that RAISED -- a client-side timeout on a
    request the server already committed included. Without the compare-and-set
    the retry bumped dl_done a second time ("23 of 22" in the SPA) and, worse,
    dl_failed twice for one clip: the hand-back's requeue_failed counts ROWS,
    so its `bump(dl_failed, -n)` left the counter permanently one above zero
    and a job whose server-side retry succeeded still reported a failure in
    Recent searches.

    False is not an error and the caller answers 200: the row already holds
    somebody's terminal verdict (the same POST a moment ago, or the server
    worker's own), and the second report has nothing to add.
    """
    if state in UNFINISHED_STATES:
        raise ValueError(f'{state!r} is not a terminal download state')
    ph = ','.join('?' * len(UNFINISHED_STATES))
    n = _update(c, 'job_videos',
                f'job_id=? AND video_id=? AND dl_state IN ({ph})',
                (job_id, video_id, *UNFINISHED_STATES),
                _VIDEO_COLS, {'dl_state': state, **cols})
    c.commit()
    return bool(n)


def failed_videos(c, job_id):
    return c.execute("SELECT * FROM job_videos WHERE job_id=? AND dl_state='failed' "
                     'ORDER BY id', (job_id,)).fetchall()


def requeue_failed(c, job_id):
    """Put every failed clip back to `pending`. -> how many.

    The SECOND-CHANCE SWEEP (docs/YTDL_LOCAL_DOWNLOAD.md §2 step 7): a clip
    that failed on the editor's machine -- their IP bot-checked, their wifi
    dropped -- is retried once by the NAS worker, whose failure modes are
    different ones. Final completeness is the max of both executors.

    dl_error is cleared exactly as mark_pending clears it; the worker overwrites
    it on the first line of the next attempt anyway, and a stale "yt-dlp said
    no" on a row that is queued again reads as a failure that is not happening.
    """
    cur = c.execute("UPDATE job_videos SET dl_state='pending', dl_error=NULL "
                    "WHERE job_id=? AND dl_state='failed'", (job_id,))
    c.commit()
    return cur.rowcount


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
    # 'visuals' | 'news'. Always one of the two, even for a row that came back
    # without the column -- the SPA labels the running job, the review header
    # and every Recent searches row with it, and "which rubric was this searched
    # under" has to be answerable a week later.
    d['mode'] = mode_of(row)
    # Always a number the SPA can render, even for a row that came back without
    # the column (a database the migration has not reached, a partial SELECT) --
    # the same rule shot_types is read under.
    d['max_candidates'] = max_candidates_of(row)
    # 'both' | 'en' | 'zh' | 'exact', and the upload-date bounds (or None):
    # the SPA labels every view of a job with them, under the rule mode is.
    d['term_scope'] = term_scope_of(row)
    d['date_from'], d['date_to'] = date_range_of(row)
    return d


def term_dict(row, videos=0):
    """A job_terms row as every JSON answer carries it.

    ONE shape, built here rather than spelled out in each handler: the poll
    response, the manifest and the term review all print the same row, and
    before this the two that existed had already drifted apart by a field.

    `translation` and `enabled` ride on every one of them (2026-08-30). A row
    from a database the migration has not reached has neither key, and reads as
    "nothing to print in brackets" and "ticked" -- which is what every term
    written before the review actually was.
    """
    return {'id': row['id'], 'term': row['term'], 'lang': row['lang'],
            'english_gloss': row['english_gloss'],
            'translation': _column(row, 'translation'),
            'enabled': bool(_column(row, 'enabled') is None
                            or _column(row, 'enabled')),
            'source': row['source'], 'searched': row['searched'],
            'hits': row['hits'], 'videos': videos}


def queue_dict(row, position):
    """A waiting job as the SPA's QUEUE list reads it.

    Deliberately NOT job_dict: a queued job has no counters worth printing and
    the list is a name, a destination and two buttons. `position` is passed in
    rather than read off the row so the list is numbered by its ORDER -- a
    queue that has had a job cancelled out of the middle of it must read 1, 2,
    3 to the person looking at it, whatever the stored numbers say.
    """
    return {'id': row['id'], 'term': row['term'], 'kind': row['kind'],
            'project_label': row['project_label'], 'phase': row['phase'],
            'position': position, 'created_at': row['created_at']}


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
        # 'visuals' | 'news' -- which rubric the two AI calls ran under. In the
        # folder beside the clips because it is half the answer to "why is this
        # folder full of press conferences", and this file outlives the database.
        'mode': mode_of(job),
        'created': now(),
        'created_by': job['created_by'],
        'project': job['project_label'],
        'quality': job['quality'],
        # `enabled` is in the folder beside the clips for the reason `mode` is:
        # this file outlives the database, and "why did this search not cover
        # X" is answered by the term the editor unticked at the review, which
        # nothing else would ever record (2026-08-30).
        'terms': [{'q': t['term'], 'lang': t['lang'],
                   'english_gloss': t['english_gloss'],
                   'translation': _column(t, 'translation'),
                   'enabled': bool(_column(t, 'enabled') is None
                                   or _column(t, 'enabled')),
                   'source': t['source'],
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


# --------------------------------------------------------------- attestations
# The rights/ToS record (attestation.py, COMMERCIAL_READINESS.md item 2,
# 2026-08-17). Two functions and no cache: this is read once per job creation
# and once per claim, which is nowhere near the poll endpoint's rate, and a
# cached "yes" that outlived a wording change is exactly the failure the
# version column exists to prevent.


def attestation_of(c, username, version):
    """The row recording `username` accepting `version`, or None.

    Tolerates the table being absent -- a database that predates migration 008
    (or one whose migration is mid-flight) answers "not accepted", which
    refuses downloads rather than allowing them. Failing closed is the whole
    point of the gate.
    """
    try:
        return c.execute(
            'SELECT username, version, text_sha256, accepted_at FROM attestations '
            'WHERE username=? AND version=?', (str(username or ''), str(version))
        ).fetchone()
    except sqlite3.Error:
        log.warning('attestations table unreadable; treating every editor as '
                    'not having accepted', exc_info=True)
        return None


def record_attestation(c, username, version, text_sha256):
    """Record an acceptance. Idempotent -- pressing Accept twice is one row.

    The timestamp of the FIRST acceptance is kept on a repeat (DO NOTHING, not
    DO UPDATE): "when did this editor agree to this wording" has one answer and
    a second click is not a new agreement.
    """
    c.execute(
        'INSERT INTO attestations(username,version,text_sha256,accepted_at) '
        'VALUES(?,?,?,?) ON CONFLICT(username,version) DO NOTHING',
        (str(username or ''), str(version), str(text_sha256), now()))
    c.commit()
    return attestation_of(c, username, version)
