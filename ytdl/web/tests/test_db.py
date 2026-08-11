"""Storage layer: schema/migration runner, the phase machine's writes, and the
two guards that live in SQL rather than in a handler."""
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

    slug, label, _ = PROJECTS[1]
    other = db.create_job(con, USER, 'wind', 'wind', slug, label)
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
