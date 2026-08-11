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


# The two tables the v2/v3 migrations touch, exactly as schema.sql v1 created
# them. Written out rather than derived from schema.sql: the point of the test
# is a database that predates both migrations, and a copy that follows the
# current file around would stop being one.
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


def test_a_ledger_row_written_before_term_dir_existed_still_reads(con, job):
    """NULL term_dir is every row the migration found: fall back to the raw
    term, exactly as the badge did before."""
    con.execute("INSERT INTO downloads(video_id,title,channel,project_slug,"
                "project_label,term,rel_path,downloaded_at) "
                "VALUES('vid00000002','t','c',?,?,'reef','Youtube/reef/x.mp4','x')",
                (PROJECTS[0][0], PROJECTS[0][1]))
    con.commit()
    assert db.ledger_map(con)['vid00000002'] == f'{PROJECTS[0][1]}/reef'


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
