"""Storage layer: schema/migration runner, the phase machine's writes, and the
two guards that live in SQL rather than in a handler."""
import sqlite3
import threading

import pytest

from tests.conftest import PROJECTS, USER, OTHER_USER
from ytdlweb import config, db


def test_schema_is_idempotent(con):
    """ensure_schema runs on every connection; it must survive being re-run."""
    db.ensure_schema(con)
    db.ensure_schema(con)
    assert con.execute('PRAGMA user_version').fetchone()[0] == db.CURRENT_SCHEMA_VERSION
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'jobs', 'job_terms', 'job_videos', 'job_video_terms',
            'downloads'} <= tables


def test_a_newer_database_is_refused(tmp_path):
    """A database written by a future version must not be silently downgraded."""
    con = db.connect(tmp_path / 'future.db')
    db.init(con)
    con.execute(f'PRAGMA user_version = {db.CURRENT_SCHEMA_VERSION + 5}')
    con.commit()
    with pytest.raises(RuntimeError, match='newer than this app supports'):
        db.ensure_schema(con)
    con.close()


# The tables the migrations touch, exactly as schema.sql v1 created them.
# Written out rather than derived from schema.sql: the point of the test is a
# database that predates the migrations, and a copy that follows the current
# file around would stop being one. job_videos is here because 007 alters it
# too -- and because a fixture that omits a table schema.sql has always created
# would make an ALTER fail here that cannot fail on the fleet's database.
_V1_DDL = """
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY, created_by TEXT NOT NULL, term TEXT NOT NULL,
    term_dir TEXT NOT NULL, project_slug TEXT NOT NULL,
    project_label TEXT NOT NULL, quality TEXT NOT NULL DEFAULT '1080p',
    period TEXT, max_per_term INTEGER NOT NULL DEFAULT 15,
    phase TEXT NOT NULL DEFAULT 'queued', error TEXT,
    terms_total INTEGER DEFAULT 0, terms_done INTEGER DEFAULT 0,
    candidates INTEGER DEFAULT 0, enrich_total INTEGER DEFAULT 0,
    enrich_done INTEGER DEFAULT 0, dl_total INTEGER DEFAULT 0,
    dl_done INTEGER DEFAULT 0, dl_failed INTEGER DEFAULT 0,
    cancel_requested INTEGER DEFAULT 0, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL);
CREATE TABLE downloads (
    video_id TEXT PRIMARY KEY, title TEXT, channel TEXT,
    project_slug TEXT NOT NULL, project_label TEXT NOT NULL, term TEXT NOT NULL,
    rel_path TEXT NOT NULL, job_id INTEGER, downloaded_by TEXT,
    downloaded_at TEXT NOT NULL);
CREATE TABLE job_videos (
    id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL, url TEXT NOT NULL, title TEXT, channel TEXT,
    duration REAL, upload_date TEXT, view_count INTEGER, thumbnail TEXT,
    meta_error TEXT, relevant INTEGER DEFAULT 1, relevance_note TEXT,
    duplicate INTEGER DEFAULT 0, duplicate_of TEXT, selected INTEGER DEFAULT 1,
    dl_state TEXT DEFAULT 'none', dl_error TEXT, filepath TEXT,
    UNIQUE(job_id, video_id));
"""


def test_a_v1_database_is_migrated_and_its_duplicate_active_jobs_retired(tmp_path):
    """The migration runner, on the database shape the fleet actually has.

    The index (YTDL-25) is the dangerous half: a live ytdl.db may already hold
    the duplicate active jobs an unguarded create_job wrote, and a CREATE
    UNIQUE INDEX that raises there takes every /ytdl request down. The
    migration retires the orphans first -- the NEWEST job is the one the
    editor's page is attached to, so that is the one that survives.
    """
    con = db.connect(tmp_path / 'v1.db')
    con.executescript(_V1_DDL)
    for phase in ('ready_for_review', 'queued'):
        con.execute("INSERT INTO jobs(created_by,term,term_dir,project_slug,"
                    "project_label,phase,created_at,updated_at) "
                    "VALUES(?,'reef','reef','s','2026/FF5/Energy',?,'x','x')",
                    (USER, phase))
    con.execute("INSERT INTO jobs(created_by,term,term_dir,project_slug,"
                "project_label,phase,created_at,updated_at) "
                "VALUES(?,'wind','wind','s','2025/FF4/Nuclear','done','x','x')",
                (OTHER_USER,))
    con.execute("INSERT INTO downloads(video_id,title,channel,project_slug,"
                "project_label,term,rel_path,downloaded_at) VALUES('vid00000001',"
                "'t','c','s','2026/FF5/Energy','reef','Youtube/reef/x.mp4','x')")
    con.execute('PRAGMA user_version = 1')
    con.commit()

    db.ensure_schema(con)

    assert con.execute('PRAGMA user_version').fetchone()[0] == db.CURRENT_SCHEMA_VERSION
    assert 'term_dir' in db._columns(con, 'downloads')
    assert db._index_exists(con, 'idx_jobs_one_active')
    # v4: every row that predates the paste-links box is a search, which is the
    # column's default -- so the ADD COLUMN needs no backfill.
    assert 'kind' in db._columns(con, 'jobs')
    assert {r[0] for r in con.execute('SELECT DISTINCT kind FROM jobs')} == {'search'}
    # v5: every row that predates the checkboxes ran under the fixed visual
    # bias, which is what the six default ticks mean -- so those rows must read
    # as the defaults and NOT as "the editor ticked nothing".
    assert 'shot_types' in db._columns(con, 'jobs')
    for row in con.execute('SELECT * FROM jobs'):
        assert db.shot_types_of(row) == db.DEFAULT_SHOT_TYPES
    rows = con.execute('SELECT id, phase, error FROM jobs WHERE created_by=? '
                       'ORDER BY id', (USER,)).fetchall()
    assert [r['phase'] for r in rows] == ['cancelled', 'queued']
    assert 'YTDL-25' in rows[0]['error']
    # ...and the index now refuses what the migration just cleaned up
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO jobs(created_by,term,term_dir,project_slug,"
                    "project_label,phase,created_at,updated_at) "
                    "VALUES(?,'more','more','s','2026/FF5/Energy','queued','x','x')",
                    (USER,))
    con.rollback()
    con.close()


# The v4 shape: v1 plus everything 002/003/004 added, and nothing 005 does.
# Written out for the same reason _V1_DDL is -- a copy that followed schema.sql
# around would stop being the shape the fleet's database is actually in.
_V4_DDL = """
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY, created_by TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'search', term TEXT NOT NULL,
    term_dir TEXT NOT NULL, project_slug TEXT NOT NULL,
    project_label TEXT NOT NULL, quality TEXT NOT NULL DEFAULT '1080p',
    period TEXT, max_per_term INTEGER NOT NULL DEFAULT 15,
    phase TEXT NOT NULL DEFAULT 'queued', error TEXT,
    terms_total INTEGER DEFAULT 0, terms_done INTEGER DEFAULT 0,
    candidates INTEGER DEFAULT 0, enrich_total INTEGER DEFAULT 0,
    enrich_done INTEGER DEFAULT 0, dl_total INTEGER DEFAULT 0,
    dl_done INTEGER DEFAULT 0, dl_failed INTEGER DEFAULT 0,
    cancel_requested INTEGER DEFAULT 0, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL);
CREATE TABLE downloads (
    video_id TEXT PRIMARY KEY, title TEXT, channel TEXT,
    project_slug TEXT NOT NULL, project_label TEXT NOT NULL, term TEXT NOT NULL,
    term_dir TEXT, rel_path TEXT NOT NULL, job_id INTEGER, downloaded_by TEXT,
    downloaded_at TEXT NOT NULL);
CREATE TABLE job_videos (
    id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL, url TEXT NOT NULL, title TEXT, channel TEXT,
    duration REAL, upload_date TEXT, view_count INTEGER, thumbnail TEXT,
    meta_error TEXT, relevant INTEGER DEFAULT 1, relevance_note TEXT,
    duplicate INTEGER DEFAULT 0, duplicate_of TEXT, selected INTEGER DEFAULT 1,
    dl_state TEXT DEFAULT 'none', dl_error TEXT, filepath TEXT,
    UNIQUE(job_id, video_id));
CREATE UNIQUE INDEX idx_jobs_one_active ON jobs(created_by)
    WHERE phase NOT IN ('done', 'failed', 'cancelled');
"""


def test_a_v4_database_gains_shot_types_and_its_old_rows_read_as_the_defaults(
        tmp_path):
    """005. Every job written before the checkboxes ran under the fixed
    "prioritise visuals" bias, and the six default ticks ARE that bias -- so an
    old row must come back as the defaults. Reading them as "the editor ticked
    nothing" would silently rewrite the history of every search the fleet has
    ever run into an unbiased one."""
    con = db.connect(tmp_path / 'v4.db')
    con.executescript(_V4_DDL)
    con.execute("INSERT INTO jobs(created_by,term,term_dir,project_slug,"
                "project_label,phase,created_at,updated_at) "
                "VALUES(?,'reef','reef','s','2026/FF5/Energy','done','x','x')",
                (USER,))
    con.execute('PRAGMA user_version = 4')
    con.commit()

    db.ensure_schema(con)

    assert con.execute('PRAGMA user_version').fetchone()[0] == db.CURRENT_SCHEMA_VERSION
    old = con.execute('SELECT * FROM jobs').fetchone()
    assert db.shot_types_of(old) == db.DEFAULT_SHOT_TYPES
    assert db.job_dict(old)['shot_types'] == list(db.DEFAULT_SHOT_TYPES)
    # and a job created after the migration can still say "nothing ticked"
    new = db.create_job(con, OTHER_USER, 'wind', 'wind', 's', '2026/FF5/Water',
                        shot_types=[])
    assert db.shot_types_of(db.get_job(con, new)) == ()
    con.close()


def test_the_migrations_default_is_the_pythons_default(tmp_path):
    """SQL cannot import Python, so the list is written twice -- here is where
    they are held together. A drift would migrate the fleet's history to a
    selection this build does not agree with."""
    sql = (config.MIGRATIONS_DIR / '005_jobs_shot_types.sql').read_text(
        encoding='utf-8')
    assert f"DEFAULT '{db.encode_shot_types(None)}'" in sql
    schema = config.SCHEMA_PATH.read_text(encoding='utf-8')
    assert f"DEFAULT '{db.encode_shot_types(None)}'" in schema
    # ...and the pair is the version this app runs at
    assert db._MIGRATIONS[5][0] == '005_jobs_shot_types.sql'
    assert max(db._MIGRATIONS) == db.CURRENT_SCHEMA_VERSION


# The v5 shape: v1 plus everything 002/003/004/005 added, and nothing 006 does
# -- the shape the fleet's ytdl.db is actually in as of this change. Written
# out for the same reason _V1_DDL and _V4_DDL are.
_V5_DDL = """
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY, created_by TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'search', term TEXT NOT NULL,
    term_dir TEXT NOT NULL, project_slug TEXT NOT NULL,
    project_label TEXT NOT NULL, quality TEXT NOT NULL DEFAULT '1080p',
    period TEXT, max_per_term INTEGER NOT NULL DEFAULT 15,
    shot_types TEXT NOT NULL
        DEFAULT 'aerial,establishing,walkthrough,timelapse,event,raw',
    phase TEXT NOT NULL DEFAULT 'queued', error TEXT,
    terms_total INTEGER DEFAULT 0, terms_done INTEGER DEFAULT 0,
    candidates INTEGER DEFAULT 0, enrich_total INTEGER DEFAULT 0,
    enrich_done INTEGER DEFAULT 0, dl_total INTEGER DEFAULT 0,
    dl_done INTEGER DEFAULT 0, dl_failed INTEGER DEFAULT 0,
    cancel_requested INTEGER DEFAULT 0, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL);
CREATE TABLE downloads (
    video_id TEXT PRIMARY KEY, title TEXT, channel TEXT,
    project_slug TEXT NOT NULL, project_label TEXT NOT NULL, term TEXT NOT NULL,
    term_dir TEXT, rel_path TEXT NOT NULL, job_id INTEGER, downloaded_by TEXT,
    downloaded_at TEXT NOT NULL);
CREATE TABLE job_videos (
    id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL, url TEXT NOT NULL, title TEXT, channel TEXT,
    duration REAL, upload_date TEXT, view_count INTEGER, thumbnail TEXT,
    meta_error TEXT, relevant INTEGER DEFAULT 1, relevance_note TEXT,
    duplicate INTEGER DEFAULT 0, duplicate_of TEXT, selected INTEGER DEFAULT 1,
    dl_state TEXT DEFAULT 'none', dl_error TEXT, filepath TEXT,
    UNIQUE(job_id, video_id));
CREATE UNIQUE INDEX idx_jobs_one_active ON jobs(created_by)
    WHERE phase NOT IN ('done', 'failed', 'cancelled');
"""


def test_a_v5_database_gains_max_candidates_and_its_old_rows_read_as_the_default(
        tmp_path):
    """006. Unlike shot_types, the default here is NOT what those rows ran
    with: every job written before the ceiling existed ran unbounded, and
    unbounded is the thing that reached 336 candidates and got the NAS's IP
    refused at 112 metadata calls. The only rows the backfill can still affect
    are ones boot recovery re-runs, so they re-run bounded on purpose."""
    con = db.connect(tmp_path / 'v5.db')
    con.executescript(_V5_DDL)
    con.execute("INSERT INTO jobs(created_by,term,term_dir,project_slug,"
                "project_label,phase,created_at,updated_at) "
                "VALUES(?,'reef','reef','s','2026/FF5/Energy','done','x','x')",
                (USER,))
    con.execute('PRAGMA user_version = 5')
    con.commit()

    db.ensure_schema(con)

    assert con.execute('PRAGMA user_version').fetchone()[0] == db.CURRENT_SCHEMA_VERSION
    assert 'max_candidates' in db._columns(con, 'jobs')
    old = con.execute('SELECT * FROM jobs').fetchone()
    assert old['max_candidates'] == db.DEFAULT_MAX_CANDIDATES
    assert db.max_candidates_of(old) == db.DEFAULT_MAX_CANDIDATES
    assert db.job_dict(old)['max_candidates'] == db.DEFAULT_MAX_CANDIDATES
    # ...and the shot types 005 wrote are untouched by the second migration
    assert db.shot_types_of(old) == db.DEFAULT_SHOT_TYPES
    con.close()


def test_the_migrations_candidate_default_is_the_pythons_default(tmp_path):
    """SQL cannot import Python, so the number is written three times -- config,
    the migration, schema.sql. A drift would let a job be created with a
    ceiling the API refuses, or migrate the fleet's rows to one."""
    sql = (config.MIGRATIONS_DIR / '006_jobs_max_candidates.sql').read_text(
        encoding='utf-8')
    assert f'DEFAULT {db.DEFAULT_MAX_CANDIDATES};' in sql
    schema = config.SCHEMA_PATH.read_text(encoding='utf-8')
    assert f'max_candidates   INTEGER NOT NULL DEFAULT {db.DEFAULT_MAX_CANDIDATES}' \
        in schema
    # ...the default is one of the choices, and the pair is this app's version
    assert db.DEFAULT_MAX_CANDIDATES in db.CANDIDATE_CAPS
    assert db._MIGRATIONS[6][0] == '006_jobs_max_candidates.sql'
    assert max(db._MIGRATIONS) == db.CURRENT_SCHEMA_VERSION


def test_the_candidate_ceiling_survives_the_round_trip(con):
    """Stored on the job, because the SEARCH phase reads it off the row --
    including after a container restart re-runs the job from `queued`."""
    slug, label, _ = PROJECTS[0]
    job_id = db.create_job(con, USER, 'reef', 'reef', slug, label,
                           max_candidates=400)
    row = db.get_job(con, job_id)
    assert row['max_candidates'] == 400
    assert db.max_candidates_of(row) == 400
    assert db.job_dict(row)['max_candidates'] == 400


def test_no_ceiling_asked_for_stores_the_default_not_unbounded(con):
    """None is "nobody said" -- an old client, an internal caller. It is the
    one case that must NOT mean "as many as the search finds": that is the
    behaviour the cap exists because of."""
    slug, label, _ = PROJECTS[0]
    job_id = db.create_job(con, USER, 'reef', 'reef', slug, label)
    assert db.get_job(con, job_id)['max_candidates'] == db.DEFAULT_MAX_CANDIDATES


def test_a_nonsensical_ceiling_reads_as_the_default_and_a_huge_one_is_clamped(
        con, job):
    """The API refuses an unlisted number, so the only way to hold one is a row
    written by another build or by hand. Two invariants survive that: there is
    always a number (never "unbounded"), and it is never bigger than the
    biggest choice on the menu -- which is what stops the 336-candidate pass
    being re-createable from the database."""
    for stored in (0, -1):
        con.execute('UPDATE jobs SET max_candidates=? WHERE id=?',
                    (stored, job['id']))
        con.commit()
        assert db.max_candidates_of(db.get_job(con, job['id'])) == \
            db.DEFAULT_MAX_CANDIDATES

    con.execute('UPDATE jobs SET max_candidates=5000 WHERE id=?', (job['id'],))
    con.commit()
    assert db.max_candidates_of(db.get_job(con, job['id'])) == \
        db.MAX_CANDIDATE_CAP == max(db.CANDIDATE_CAPS)

    # a smaller off-menu number is honoured as it stands: bounded is the
    # property that matters, and rounding 137 up would spend 63 metadata calls
    con.execute('UPDATE jobs SET max_candidates=137 WHERE id=?', (job['id'],))
    con.commit()
    assert db.max_candidates_of(db.get_job(con, job['id'])) == 137
    # ...and a bare number is answered as itself, so the worker can be told one
    assert db.max_candidates_of(50) == 50
    assert db.max_candidates_of('200') == 200
    assert db.max_candidates_of('not a number') == db.DEFAULT_MAX_CANDIDATES


def test_a_row_with_no_max_candidates_column_at_all_reads_as_the_default(con, job):
    """A SELECT that did not ask for it, or a database the migration has not
    reached: the answer is the default, never "no ceiling"."""
    partial = con.execute('SELECT id, term FROM jobs WHERE id=?',
                          (job['id'],)).fetchone()
    assert db.max_candidates_of(partial) == db.DEFAULT_MAX_CANDIDATES
    assert db.max_candidates_of(None) == db.DEFAULT_MAX_CANDIDATES
    # a job_dict has already turned the column into a number; it reads as itself
    assert db.max_candidates_of(db.job_dict(db.get_job(con, job['id']))) == \
        db.DEFAULT_MAX_CANDIDATES


def test_the_ceiling_cannot_be_updated_after_the_fact(con, job):
    """Like `kind` and `shot_types`: an input to the search that already ran.
    An UPDATE here would leave a job row claiming a ceiling smaller than the
    manifest sitting under it."""
    with pytest.raises(ValueError):
        db.set_job(con, job['id'], max_candidates=400)


def test_a_url_job_takes_the_default_ceiling_and_never_uses_it(con):
    """A paste does no searching, so there is nothing to accumulate against --
    the row takes the column default and the SPA does not show it."""
    slug, label, _ = PROJECTS[0]
    job_id = db.create_url_job(con, OTHER_USER, '', '', slug, label,
                               _url_videos('vid00000001'))
    row = db.get_job(con, job_id)
    assert row['kind'] == db.KIND_URLS
    assert row['max_candidates'] == db.DEFAULT_MAX_CANDIDATES


def test_a_jobs_shot_types_survive_the_round_trip(con):
    """Stored on the job, because BOTH claude calls read them off the row --
    including after a container restart re-runs the job from `queued`."""
    slug, label, _ = PROJECTS[0]
    job_id = db.create_job(con, USER, 'reef', 'reef', slug, label,
                           shot_types=['interview', 'aerial'])
    row = db.get_job(con, job_id)
    # canonical order, whatever the caller passed
    assert row['shot_types'] == 'aerial,interview'
    assert db.shot_types_of(row) == ('aerial', 'interview')
    assert db.job_dict(row)['shot_types'] == ['aerial', 'interview']


def test_no_selection_stores_the_defaults_and_an_empty_one_stores_nothing(con):
    """The two are NOT the same fact: None is "nobody said" (an old row, an old
    client) and [] is "the editor deliberately ticked nothing", which means an
    unbiased search."""
    slug, label, _ = PROJECTS[0]
    a = db.create_job(con, USER, 'reef', 'reef', slug, label)
    assert db.shot_types_of(db.get_job(con, a)) == db.DEFAULT_SHOT_TYPES

    db.set_phase(con, a, 'done')
    b = db.create_job(con, USER, 'wind', 'wind', slug, label, shot_types=[])
    assert db.get_job(con, b)['shot_types'] == ''
    assert db.shot_types_of(db.get_job(con, b)) == ()


def test_a_url_job_carries_no_meaningful_selection_and_is_never_asked_for_one(con):
    """A paste is not searched or filtered, so there is nothing for a bias to
    bias -- the row takes the column default and the SPA ignores it."""
    slug, label, _ = PROJECTS[0]
    job_id = db.create_url_job(con, OTHER_USER, '', '', slug, label,
                               _url_videos('vid00000001'))
    row = db.get_job(con, job_id)
    assert row['kind'] == db.KIND_URLS
    assert db.shot_types_of(row) == db.DEFAULT_SHOT_TYPES


def test_the_selection_cannot_be_updated_after_the_fact(con, job):
    """Like `kind`: it is an input to the search that already ran, and a later
    UPDATE would make the job row describe a job nobody asked for."""
    with pytest.raises(ValueError):
        db.set_job(con, job['id'], shot_types='aerial')
    with pytest.raises(ValueError):
        db.set_job(con, job['id'], kind='urls')


def test_a_row_with_no_such_column_at_all_reads_as_the_defaults(con, job):
    """The NOT NULL column cannot be null, so the only way to have no answer is
    a row that predates it -- a SELECT that does not carry it, or a database
    the migration has not reached yet. That is a search that ran under the
    fixed visual bias, i.e. the defaults."""
    partial = con.execute('SELECT id, term FROM jobs WHERE id=?',
                          (job['id'],)).fetchone()
    assert db.shot_types_of(partial) == db.DEFAULT_SHOT_TYPES
    assert db.shot_types_of(None) == db.DEFAULT_SHOT_TYPES
    # a job_dict, whose shot_types is already a list, reads back as itself --
    # the same call must not answer "the defaults" for a job that ticked two
    assert db.shot_types_of(db.job_dict(db.get_job(con, job['id']))) == \
        db.DEFAULT_SHOT_TYPES
    assert db.shot_types_of(['raw', 'aerial']) == ('aerial', 'raw')
    assert db.shot_types_of([]) == ()


def test_an_unknown_key_in_the_column_costs_a_fragment_not_a_search(con, job):
    """A row written by another build must never break a job: the API refuses
    unknown keys, this layer merely ignores them."""
    con.execute("UPDATE jobs SET shot_types='aerial,klingon' WHERE id=?",
                (job['id'],))
    con.commit()
    assert db.shot_types_of(db.get_job(con, job['id'])) == ('aerial',)


def test_con_is_per_thread(con):
    """A sqlite3 connection may only be used on the thread that created it, and
    this app has two kinds of caller: the request threadpool and the worker."""
    got = {}

    def grab(key):
        got[key] = db.con()

    t1 = threading.Thread(target=grab, args=('a',))
    t2 = threading.Thread(target=grab, args=('b',))
    t1.start(); t1.join()
    t2.start(); t2.join()
    assert got['a'] is not got['b']
    assert db.con() is db.con()


def test_job_ownership_is_filtered_in_sql(con, job):
    assert db.get_job_for(con, job['id'], USER) is not None
    assert db.get_job_for(con, job['id'], OTHER_USER) is None


def test_active_job_counts_ready_for_review(con, job):
    """A manifest waiting for the editor is an active job: starting a second
    search would orphan it."""
    assert db.active_job(con, USER)['id'] == job['id']
    db.set_phase(con, job['id'], 'ready_for_review')
    assert db.active_job(con, USER)['id'] == job['id']
    db.set_phase(con, job['id'], 'done')
    assert db.active_job(con, USER) is None


def test_english_gloss_survives_the_round_trip(con, job):
    tid = db.add_term(con, job['id'], '藻礎', 'zh', 'claude', 'algal reef')
    row = db.terms(con, job['id'])[0]
    assert row['id'] == tid
    assert row['english_gloss'] == 'algal reef'


def test_add_term_is_idempotent_and_returns_the_same_id(con, job):
    """Claude regularly hands back the editor's own phrase as a variant."""
    a = db.add_term(con, job['id'], 'algal reef', 'en', 'user')
    b = db.add_term(con, job['id'], 'algal reef', 'en', 'claude')
    assert a == b
    assert len(db.terms(con, job['id'])) == 1


def test_every_term_that_surfaced_a_video_is_recorded(con, job):
    """The chips filter on this table, so the SECOND term to return a video
    must be recorded too -- that is the whole reason it is not a JSON column."""
    t1 = db.add_term(con, job['id'], 'one', 'en', 'claude')
    t2 = db.add_term(con, job['id'], 'two', 'en', 'claude')
    assert db.add_video(con, job['id'], 'vid00000001', 'u') is True
    db.link_term(con, job['id'], 'vid00000001', t1)
    assert db.add_video(con, job['id'], 'vid00000001', 'u') is False
    db.link_term(con, job['id'], 'vid00000001', t2)
    con.commit()
    assert db.term_ids_by_video(con, job['id'])['vid00000001'] == [t1, t2]
    assert db.term_hit_counts(con, job['id']) == {t1: 1, t2: 1}


def test_a_duplicate_can_never_be_selected(con, job):
    """REQ 6 is "never re-downloaded", so the refusal lives in the WHERE clause
    and not only in the handler that calls it."""
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.set_video(con, job['id'], 'vid00000001', duplicate=1, selected=0)
    assert db.select_video(con, job['id'], 'vid00000001', True) is False
    assert db.get_video(con, job['id'], 'vid00000001')['selected'] == 0

    db.bulk_select(con, job['id'], True, 'all')
    assert db.get_video(con, job['id'], 'vid00000001')['selected'] == 0


def test_mark_pending_skips_duplicates_and_finished_rows(con, job):
    for vid in ('vid00000001', 'vid00000002', 'vid00000003'):
        db.add_video(con, job['id'], vid, f'https://www.youtube.com/watch?v={vid}')
    db.set_video(con, job['id'], 'vid00000002', duplicate=1, selected=0)
    db.set_video(con, job['id'], 'vid00000003', dl_state='done')
    assert db.mark_pending(con, job['id']) == 1
    assert [r['video_id'] for r in db.pending_videos(con, job['id'])] == ['vid00000001']


def test_counts_include_the_selected_duration(con, job):
    """The review footer shows count AND total duration -- the only disk-space
    proxy an editor gets before committing to 40 downloads."""
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.add_video(con, job['id'], 'vid00000002', 'u')
    db.set_video(con, job['id'], 'vid00000001', duration=120.0)
    db.set_video(con, job['id'], 'vid00000002', duration=60.0, relevant=0, selected=0)
    c = db.counts(con, job['id'])
    assert c['total'] == 2 and c['relevant'] == 1 and c['irrelevant'] == 1
    assert c['selected'] == 1 and c['selected_seconds'] == 120.0


def test_reset_stale_jobs_restarts_mid_pipeline_and_resumes_downloads(con, job):
    """Boot recovery. A restarted job is wiped and re-run; a download job keeps
    everything it already fetched."""
    db.add_term(con, job['id'], 'x', 'en', 'claude')
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.set_phase(con, job['id'], 'searching')

    # ANOTHER editor's job: one active job per editor is a unique index now
    # (YTDL-25), so the two halves of boot recovery cannot both be alex's.
    slug, label, _ = PROJECTS[1]
    other = db.create_job(con, OTHER_USER, 'wind', 'wind', slug, label)
    db.add_video(con, other, 'vid00000002', 'u')
    db.set_video(con, other, 'vid00000002', dl_state='downloading')
    db.add_video(con, other, 'vid00000003', 'u')
    db.set_video(con, other, 'vid00000003', dl_state='done')
    db.set_phase(con, other, 'downloading')

    restarted, resumed = db.reset_stale_jobs(con)
    assert (restarted, resumed) == (1, 1)
    assert db.get_job(con, job['id'])['phase'] == 'queued'
    assert db.terms(con, job['id']) == [] and db.videos(con, job['id']) == []
    assert db.get_job(con, other)['phase'] == 'downloading'
    assert db.get_video(con, other, 'vid00000002')['dl_state'] == 'pending'
    assert db.get_video(con, other, 'vid00000003')['dl_state'] == 'done'


def test_ready_for_review_is_left_alone_by_boot_recovery(con, job):
    db.set_phase(con, job['id'], 'ready_for_review')
    db.reset_stale_jobs(con)
    assert db.get_job(con, job['id'])['phase'] == 'ready_for_review'


def test_one_active_job_per_editor_is_enforced_by_the_database(con, job):
    """YTDL-25: the handler's check is read-then-insert, so the guarantee has
    to live where the race cannot get at it. Terminal jobs are exempt -- an
    editor's history is any number of rows."""
    slug, label, _ = PROJECTS[1]
    with pytest.raises(sqlite3.IntegrityError):
        db.create_job(con, USER, 'second', 'second', slug, label)
    db.set_phase(con, job['id'], 'cancelled')
    again = db.create_job(con, USER, 'second', 'second', slug, label)
    assert db.active_job(con, USER)['id'] == again


# ------------------------------------------------------- pasted-link jobs

def _url_videos(*ids):
    return [{'video_id': v, 'url': f'https://www.youtube.com/watch?v={v}'}
            for v in ids]


def test_create_url_job_writes_the_job_and_its_videos_together(con):
    """A url job has no search half to write the rows later, so a jobs row
    without them would be an ACTIVE job that can never finish -- and one active
    job per editor then locks that editor out with nothing to cancel."""
    slug, label, _ = PROJECTS[0]
    job_id = db.create_url_job(con, OTHER_USER, '', '', slug, label,
                               _url_videos('vid00000001', 'vid00000002'))
    row = db.get_job(con, job_id)
    assert row['kind'] == db.KIND_URLS
    assert row['phase'] == 'queued' and row['dl_total'] == 2
    # both EMPTY: nothing was searched for, and there is no subfolder under
    # Youtube/ for a paste to land in (2026-08-11)
    assert row['term'] == '' and row['term_dir'] == ''
    vids = db.videos(con, job_id)
    assert [v['video_id'] for v in vids] == ['vid00000001', 'vid00000002']
    assert all(v['dl_state'] == 'pending' and v['selected'] == 1
               and v['relevant'] == 1 for v in vids)


def test_a_search_job_is_still_kind_search(con, job):
    """The column defaults, so nothing that already exists changes meaning."""
    assert job['kind'] == db.KIND_SEARCH


def test_a_known_download_is_written_skipped_rather_than_queued(con):
    slug, label, _ = PROJECTS[0]
    videos = _url_videos('vid00000001', 'vid00000002')
    videos[0]['duplicate_of'] = '2025/FF4/Nuclear/other term'
    job_id = db.create_url_job(con, OTHER_USER, '', '', slug, label, videos)

    assert db.get_job(con, job_id)['dl_total'] == 1
    dup = db.get_video(con, job_id, 'vid00000001')
    assert dup['dl_state'] == 'skipped' and dup['duplicate'] == 1
    assert dup['selected'] == 0
    assert dup['duplicate_of'] == '2025/FF4/Nuclear/other term'
    assert [v['video_id'] for v in db.pending_videos(con, job_id)] == ['vid00000002']


def test_create_url_job_obeys_the_one_active_job_index_and_leaves_nothing_behind(
        con, job):
    """YTDL-25's index does not care what kind of job it is. The rollback
    matters as much as the raise: the videos are inserted in the same
    transaction, so a loser must leave no rows at all."""
    slug, label, _ = PROJECTS[1]
    with pytest.raises(sqlite3.IntegrityError):
        db.create_url_job(con, USER, '', '', slug, label,
                          _url_videos('vid00000001'))
    assert len(db.recent_jobs(con, USER)) == 1
    assert con.execute("SELECT COUNT(*) FROM job_videos WHERE video_id='vid00000001'"
                       ).fetchone()[0] == 0

    db.set_phase(con, job['id'], 'done')
    again = db.create_url_job(con, USER, '', '', slug, label,
                              _url_videos('vid00000001'))
    assert db.active_job(con, USER)['id'] == again


def test_boot_recovery_leaves_a_queued_url_jobs_videos_alone(con):
    """The wipe-and-restart half of reset_stale_jobs is for jobs whose rows can
    be regenerated by re-running a search. A url job's rows ARE the editor's
    input: deleting them would leave a job that downloads nothing."""
    slug, label, _ = PROJECTS[0]
    job_id = db.create_url_job(con, OTHER_USER, '', '', slug, label,
                               _url_videos('vid00000001'))
    restarted, resumed = db.reset_stale_jobs(con)
    assert (restarted, resumed) == (0, 0)
    assert db.get_job(con, job_id)['phase'] == 'queued'
    assert [v['video_id'] for v in db.pending_videos(con, job_id)] == ['vid00000001']


def test_a_restarted_url_download_is_resumed_not_wiped(con):
    """`downloading` is kept by boot recovery and its in-flight row put back to
    pending -- the same repair a search job's download phase gets."""
    slug, label, _ = PROJECTS[0]
    job_id = db.create_url_job(con, OTHER_USER, '', '', slug, label,
                               _url_videos('vid00000001', 'vid00000002'))
    db.set_phase(con, job_id, 'downloading')
    db.set_video(con, job_id, 'vid00000001', dl_state='downloading')

    restarted, resumed = db.reset_stale_jobs(con)
    assert (restarted, resumed) == (0, 1)
    assert db.get_job(con, job_id)['phase'] == 'downloading'
    assert len(db.videos(con, job_id)) == 2


def test_cancel_now_only_fires_when_no_phase_is_in_flight(con, job):
    """YTDL-1. `queued` and `ready_for_review` have no worker inside them, so
    they go terminal here; anything else must be left to the flag, because the
    worker owns the yt-dlp call it is in the middle of."""
    db.set_phase(con, job['id'], 'ready_for_review')
    assert db.cancel_now(con, job['id']) is True
    assert db.get_job(con, job['id'])['phase'] == 'cancelled'
    assert db.active_job(con, USER) is None

    slug, label, _ = PROJECTS[1]
    mid = db.create_job(con, USER, 'wind', 'wind', slug, label)
    db.set_phase(con, mid, 'downloading')
    assert db.cancel_now(con, mid) is False
    assert db.get_job(con, mid)['phase'] == 'downloading'


def test_clear_cancel_forgets_an_unhonoured_request(con, job):
    db.request_cancel(con, job['id'])
    db.clear_cancel(con, job['id'])
    assert db.is_cancelled(con, job['id']) is False


def test_mark_pending_is_idempotent(con, job):
    """YTDL-18: start_download writes rows, counters and phase as three
    transactions; a container death between the first and the last used to
    leave rows already `pending` that this no longer matched, and every later
    DOWNLOAD press 400'd."""
    db.add_video(con, job['id'], 'vid00000001', 'u')
    assert db.mark_pending(con, job['id']) == 1
    assert db.mark_pending(con, job['id']) == 1


def test_select_none_deselects_what_the_filter_hid(con, job):
    """YTDL-26: app.js sends scope='relevant' whenever "show filtered" is off,
    so a hand-selected filtered-out video survived NONE behind a hidden card --
    and mark_pending, which has no relevance predicate, downloaded it."""
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.add_video(con, job['id'], 'vid00000002', 'u')
    db.set_video(con, job['id'], 'vid00000002', relevant=0, selected=1)

    db.bulk_select(con, job['id'], False, 'relevant')
    assert db.get_video(con, job['id'], 'vid00000002')['selected'] == 0
    assert db.mark_pending(con, job['id']) == 0

    # selecting still respects it: NONE means all, ALL does not.
    db.bulk_select(con, job['id'], True, 'relevant')
    assert db.get_video(con, job['id'], 'vid00000002')['selected'] == 0
    assert db.get_video(con, job['id'], 'vid00000001')['selected'] == 1


def test_the_ledger_badge_names_the_folder_that_exists_on_disk(con, job):
    """YTDL-31: the term is what the editor typed; the folder is
    safe_term_dirname(it). The badge is an instruction to go and look."""
    term = 'reef: the "third" LNG terminal'
    term_dir = config.safe_term_dirname(term)
    assert term_dir != term
    db.ledger_add(con, 'vid00000001', 't', 'c', PROJECTS[0][0], PROJECTS[0][1],
                  term, f'Youtube/{term_dir}/Channel - t [vid00000001].mp4')
    assert db.ledger_map(con)['vid00000001'] == f'{PROJECTS[0][1]}/{term_dir}'


def test_a_root_level_clip_names_the_youtube_folder_not_a_dangling_path(con):
    """A paste has no term and no subfolder (2026-08-11), so term_dir is EMPTY
    -- and '<label>/' with nothing after it is not a folder anybody can open.
    The badge, the API's duplicate answer and the worker's re-check all read it
    through the same helper for that reason."""
    db.ledger_add(con, 'vid00000001', 't', 'c', PROJECTS[0][0], PROJECTS[0][1],
                  '', 'Youtube/Channel - t [vid00000001].mp4')
    row = db.ledger_get(con, 'vid00000001')
    assert row['term_dir'] == '', 'the root must store empty, not NULL'
    assert db.ledger_where(row) == f'{PROJECTS[0][1]}/Youtube'
    assert db.ledger_map(con)['vid00000001'] == f'{PROJECTS[0][1]}/Youtube'
    assert db.folder_label('') == db.folder_label(None) == 'Youtube'
    assert db.folder_label('algal reef') == 'algal reef'

    d = db.download_dict(db.recent_downloads(con)[0])
    assert d['folder'] == 'Youtube' and d['folder_path'] == 'Youtube'
    assert d['reveal_path'] == \
        f'{PROJECTS[0][1]}/Youtube/Channel - t [vid00000001].mp4'


def test_the_stored_folder_comes_from_the_path_for_both_shapes(con):
    """_term_dir_of reads the folder back out of rel_path rather than
    re-deriving it from the term, so the ledger agrees with the disk. '' (the
    Youtube root) and None (no usable path at all) are different answers."""
    assert db._term_dir_of('Youtube/algal reef/x [aaaaaaaaaaa].mp4', 'algal reef') \
        == 'algal reef'
    assert db._term_dir_of('Youtube/x [aaaaaaaaaaa].mp4', '') == ''
    assert db._term_dir_of('', '') is None
    # backslashes survive a hand-written row, and so does a leading separator
    assert db._term_dir_of('Youtube\\algal reef\\x.mp4', '') == 'algal reef'


def test_a_ledger_row_written_before_term_dir_existed_still_reads(con, job):
    """NULL term_dir is every row the migration found: fall back to the raw
    term, exactly as the badge did before."""
    con.execute("INSERT INTO downloads(video_id,title,channel,project_slug,"
                "project_label,term,rel_path,downloaded_at) "
                "VALUES('vid00000002','t','c',?,?,'reef','Youtube/reef/x.mp4','x')",
                (PROJECTS[0][0], PROJECTS[0][1]))
    con.commit()
    assert db.ledger_map(con)['vid00000002'] == f'{PROJECTS[0][1]}/reef'


# --------------------------------------------------- the ledger as history
# The same rows the dedupe reads, in the order a human wants them. Nothing here
# filters by editor: the ledger is the FLEET's record (see routes_api's
# list_downloads for why), and every row carries downloaded_by so the panel can
# still say whose it was.

def _ledger_row(con, video_id, when, user=USER, term='reef', project=None):
    slug, label = project or (PROJECTS[0][0], PROJECTS[0][1])
    db.ledger_add(con, video_id, f'{video_id} title', 'ch', slug, label, term,
                  f'Youtube/{term}/Channel [{video_id}].mp4', downloaded_by=user)
    con.execute('UPDATE downloads SET downloaded_at=? WHERE video_id=?',
                (when, video_id))
    con.commit()


def test_recent_downloads_is_newest_first_and_paged(con):
    for i in range(4):
        _ledger_row(con, f'vid0000000{i}', f'2026-08-1{i}T09:00:00+00:00')
    assert db.count_downloads(con) == 4
    ids = [r['video_id'] for r in db.recent_downloads(con)]
    assert ids == ['vid00000003', 'vid00000002', 'vid00000001', 'vid00000000']
    assert [r['video_id'] for r in db.recent_downloads(con, limit=2)] == \
        ['vid00000003', 'vid00000002']
    assert [r['video_id'] for r in db.recent_downloads(con, limit=2, offset=2)] == \
        ['vid00000001', 'vid00000000']


def test_a_re_downloaded_clip_moves_to_the_top_rather_than_keeping_its_place(con):
    """The ledger UPSERTS on video_id, so a re-download keeps the ROWID it was
    first written with -- ordering by that would file today's download under
    last month. downloaded_at is the order; rowid is only the tie-break for the
    forty clips of one job that share a second."""
    _ledger_row(con, 'vid00000001', '2026-08-01T09:00:00+00:00')
    _ledger_row(con, 'vid00000002', '2026-08-05T09:00:00+00:00')
    _ledger_row(con, 'vid00000001', '2026-08-11T09:00:00+00:00', user=OTHER_USER,
                project=('2025-ff4-nuclear', '2025/FF4/Nuclear'))
    rows = db.recent_downloads(con)
    assert [r['video_id'] for r in rows] == ['vid00000001', 'vid00000002']
    assert db.count_downloads(con) == 2, 'the upsert wrote a second row'
    assert rows[0]['downloaded_by'] == OTHER_USER
    assert rows[0]['project_label'] == '2025/FF4/Nuclear'


def test_recent_downloads_is_bounded_whatever_it_is_asked_for(con):
    """The ledger outlives every job in it and nothing prunes it, so the bound
    lives here as well as in the handler -- a future caller must not be able to
    ask for all of it."""
    for i in range(3):
        _ledger_row(con, f'vid0000000{i}', f'2026-08-1{i}T09:00:00+00:00')
    assert len(db.recent_downloads(con, limit=10 ** 6)) == 3
    assert len(db.recent_downloads(con, limit=0)) == 1        # clamped up to 1
    assert len(db.recent_downloads(con, offset=-4)) == 3      # clamped to 0


def test_a_history_row_derives_the_folder_and_the_projects_root_path(con):
    """YTDL-31 again: `term` is what the editor typed and `term_dir` is what
    exists on disk. The path handed to the companion is relative to the PROJECTS
    ROOT -- <project label>/<rel_path> -- because rel_path is stored relative to
    the project and only the companion knows where the tree is mounted."""
    term = 'reef: the "third" LNG terminal'
    term_dir = config.safe_term_dirname(term)
    db.ledger_add(con, 'vid00000001', 'a title', 'ch', PROJECTS[0][0],
                  PROJECTS[0][1], term,
                  f'Youtube/{term_dir}/Channel [vid00000001].mp4',
                  downloaded_by=USER)
    d = db.download_dict(db.recent_downloads(con)[0])
    assert d['folder'] == term_dir != term
    assert d['reveal_path'] == \
        f'{PROJECTS[0][1]}/Youtube/{term_dir}/Channel [vid00000001].mp4'
    assert 'rowid' not in d, 'the paging tie-break leaked into the contract'


def test_a_history_row_with_no_path_recorded_still_reads(con):
    """A row written before YTDL-15 was fixed can have an empty rel_path. It is
    still history -- there is simply no folder to offer to open, and the panel
    must get None rather than a path that means the project root."""
    con.execute("INSERT INTO downloads(video_id,title,channel,project_slug,"
                "project_label,term,rel_path,downloaded_at) "
                "VALUES('vid00000009','t','c',?,?,'reef','','2026-08-11T09:00:00')",
                (PROJECTS[0][0], PROJECTS[0][1]))
    con.commit()
    d = db.download_dict(db.recent_downloads(con)[0])
    assert d['reveal_path'] is None
    assert d['folder'] == 'reef'          # the pre-term_dir fallback, as ever


def test_only_whitelisted_columns_can_be_written(con, job):
    with pytest.raises(ValueError):
        db.set_job(con, job['id'], created_by='someone else')
    with pytest.raises(ValueError):
        db.set_video(con, job['id'], 'vid00000001', id=99)


def test_safe_term_dirname_strips_what_smb_cannot_take():
    assert config.safe_term_dirname('../../etc/passwd') == 'etc passwd'
    assert config.safe_term_dirname('a<b>c:d"e|f?g*h') == 'a b c d e f g h'
    assert config.safe_term_dirname('trailing dot.') == 'trailing dot'
    assert config.safe_term_dirname('   ') == 'search'
    assert config.safe_term_dirname('..') == 'search'


def test_safe_term_dirname_defuses_windows_device_names():
    """YTDL-28: the NAS creates `con/` happily, and every Windows editor then
    carries a per-item sync error on that project until it is renamed there."""
    for reserved in ('con', 'CON', 'Nul', 'com1', 'LPT9', 'aux'):
        assert config.safe_term_dirname(reserved) == reserved + '_'
    # the reservation is on the stem, before any dot
    assert config.safe_term_dirname('nul.txt') == 'nul_.txt'
    # ...and only on the whole stem: these are ordinary names
    for ok in ('console', 'com10', 'my con', 'conx'):
        assert config.safe_term_dirname(ok) == ok


def test_safe_term_dirname_caps_at_80_utf8_bytes():
    """CJK is 3 bytes a character and NFS/SMB cap a NAME at 255 bytes, so the
    cap has to be counted in bytes and cut on a character boundary."""
    long_zh = '藻礎' * 40
    out = config.safe_term_dirname(long_zh)
    assert len(out.encode('utf-8')) <= 80
    assert out == '藻礎' * 13          # 78 bytes, no broken character


def test_safe_join_refuses_to_leave_the_root(tmp_path):
    assert config.safe_join(tmp_path, '2026/FF5/Energy', 'Youtube', 'reef')
    for bad in ('..', '../elsewhere', '/etc', 'C:'):
        with pytest.raises(config.PathTraversalError):
            config.safe_join(tmp_path, bad)
