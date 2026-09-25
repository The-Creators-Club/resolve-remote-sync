"""One person's records in ytdl.db: export, erase history, delete (LG-2/LG-3).

docs/LEGAL_GAP_FEATURES_PLAN.md §4.2-4.3 (2026-09-25). The properties pinned
here are the ones a wrong order or a wide WHERE would break silently:
  - a delete releases a live lease BEFORE the name is replaced, so the worker's
    reclaim credits the stand-in and the other editor's job carries on;
  - erase touches only FINISHED jobs the person created, never the dedupe
    ledger or the attestations;
  - after a delete the real name is nowhere in the store, and a second call
    is a no-op;
  - the dashboard side finds the file, never creates one, answers the plan's
    bare shapes (and RAISES on a store it cannot read), and uses the
    dashboard's own stand-in so one person stays one person.
The "review round" block at the end pins the eight findings of G4's
adversarial review (2026-09-25); each of those tests fails on the first build.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from ytdlweb import config, db

from .conftest import OTHER_USER, USER

STAND_IN = 'deleted-user-0123456789'


def _iso(seconds=0):
    return (datetime.now(timezone.utc)
            + timedelta(seconds=seconds)).isoformat(timespec='seconds')


def _job(c, created_by, phase='done', **cols):
    base = {'created_by': created_by, 'term': 'taipei skyline',
            'term_dir': 'taipei skyline', 'project_slug': '2026-ff5-energy',
            'project_label': '2026/FF5/Energy Transition', 'phase': phase,
            'created_at': _iso(), 'updated_at': _iso()}
    base.update(cols)
    keys = ','.join(base)
    cur = c.execute(f'INSERT INTO jobs({keys}) VALUES({",".join("?" * len(base))})',
                    list(base.values()))
    job_id = cur.lastrowid
    t = c.execute("INSERT INTO job_terms(job_id,term,lang,source) VALUES(?,?,'en','user')",
                  (job_id, base['term'])).lastrowid
    c.execute('INSERT INTO job_videos(job_id,video_id,url,download_host) VALUES(?,?,?,?)',
              (job_id, f'v{job_id}', f'https://youtu.be/v{job_id}',
               cols.get('claimed_by') or 'server'))
    c.execute('INSERT INTO job_video_terms(job_id,video_id,term_id) VALUES(?,?,?)',
              (job_id, f'v{job_id}', t))
    c.commit()
    return job_id


def _ledger(c, video_id, by):
    db.ledger_add(c, video_id, 'title', 'chan', '2026-ff5-energy',
                  '2026/FF5/Energy Transition', 'taipei skyline',
                  'Youtube/taipei skyline/x.mp4', None, by)


def _attest(c, user, version='v1'):
    db.record_attestation(c, user, version, 'sha')


def _every_text(c):
    out = []
    for (table,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' "
                              "AND name NOT LIKE 'sqlite_%'"):
        for row in c.execute(f'SELECT * FROM {table}'):
            out.extend(str(v) for v in tuple(row) if isinstance(v, str))
    return out


# ------------------------------------------------------------ subject_rows

def test_subject_rows_finds_every_place_a_person_appears(con):
    mine = _job(con, USER)
    theirs_i_fetched = _job(con, OTHER_USER, claimed_by=USER, download_mode='local')
    _job(con, OTHER_USER)
    _ledger(con, 'a1', USER)
    _ledger(con, 'a2', OTHER_USER)
    _attest(con, USER)
    _attest(con, OTHER_USER)

    rows = db.subject_rows(con, USER)

    assert {r['id'] for r in rows['jobs']} == {mine, theirs_i_fetched}
    assert [r['job_id'] for r in rows['job_terms']] == [mine]
    assert [r['job_id'] for r in rows['job_videos']] == [theirs_i_fetched]
    assert [r['video_id'] for r in rows['downloads']] == ['a1']
    assert [r['username'] for r in rows['attestations']] == [USER]


def test_subject_rows_matches_case_insensitively_and_never_the_server_mark(con):
    _job(con, USER.upper())
    assert len(db.subject_rows(con, USER)['jobs']) == 1
    # A person named `server` must not be handed the NAS worker's clips.
    _job(con, 'server')
    assert db.subject_rows(con, 'server')['job_videos'] == []


def test_a_blank_name_is_refused_everywhere(con):
    for call in (lambda: db.subject_rows(con, ' '),
                 lambda: db.forget_history(con, ''),
                 lambda: db.forget_requester(con, None, STAND_IN)):
        with pytest.raises(ValueError):
            call()
    with pytest.raises(ValueError):
        db.forget_requester(con, USER, '  ')


# ---------------------------------------------------------- forget_history

def test_forget_history_deletes_only_finished_jobs_the_person_created(con):
    done = _job(con, USER, 'done')
    failed = _job(con, USER, 'failed')
    running = _job(con, USER, 'downloading')
    parked = _job(con, USER, 'ready_for_review')
    fetched_for_other = _job(con, OTHER_USER, 'done', claimed_by=USER)
    _ledger(con, 'kept', USER)
    _attest(con, USER)

    counts = db.forget_history(con, USER)

    left = {r['id'] for r in con.execute('SELECT id FROM jobs')}
    assert left == {running, parked, fetched_for_other}
    assert counts == {'jobs': 2, 'job_terms': 2, 'job_videos': 2, 'job_video_terms': 2}
    for table in ('job_terms', 'job_videos', 'job_video_terms'):
        ids = {r[0] for r in con.execute(f'SELECT job_id FROM {table}')}
        assert done not in ids and failed not in ids
    assert db.ledger_get(con, 'kept') is not None
    assert db.attestation_of(con, USER, 'v1') is not None
    assert db.forget_history(con, USER)['jobs'] == 0


def test_forget_history_does_not_rely_on_the_foreign_keys_pragma(con, tmp_path):
    bare = sqlite3.connect(config.DB_PATH)
    bare.row_factory = sqlite3.Row
    try:
        assert bare.execute('PRAGMA foreign_keys').fetchone()[0] == 0
        _job(con, USER, 'done')
        db.forget_history(bare, USER)
    finally:
        bare.close()
    for table in ('jobs', 'job_terms', 'job_videos', 'job_video_terms'):
        assert con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0


# -------------------------------------------------------- forget_requester

def test_a_live_lease_is_released_first_and_the_other_editors_job_carries_on(con):
    other = _job(con, OTHER_USER, 'downloading', download_mode='local',
                 claimed_by=USER, claimed_machine='m-1',
                 lease_expires_at=_iso(300))

    counts = db.forget_requester(con, USER, STAND_IN)

    job = db.get_job(con, other)
    assert counts['leases_released'] == 1
    assert not db.lease_active(job)            # the companion gets 410 next call
    assert job['phase'] == 'downloading'       # nobody cancelled their job
    assert not job['cancel_requested']
    assert job['created_by'] == OTHER_USER
    # Renamed AFTER the release: the worker's reclaim credits claimed_by.
    assert job['claimed_by'] == STAND_IN
    # ...and the worker can now see the job again.
    assert db.claim_next_job(con)['id'] == other


def test_their_own_unfinished_jobs_are_cancelled_the_way_the_cancel_button_does(con):
    queued = _job(con, USER, 'queued')
    parked = _job(con, USER, 'ready_for_review')
    local = _job(con, USER, 'downloading', download_mode='local', claimed_by=USER,
                 lease_expires_at=_iso(300))
    server = _job(con, USER, 'searching')

    counts = db.forget_requester(con, USER, STAND_IN)

    assert db.get_job(con, queued)['phase'] == 'cancelled'
    assert db.get_job(con, parked)['phase'] == 'cancelled'
    for job_id in (local, server):
        job = db.get_job(con, job_id)
        assert job['cancel_requested'] == db.FORGOTTEN_CANCEL
        assert not db.lease_active(job)
    assert counts['jobs_cancelled'] == 2
    assert counts['jobs_stopping'] == 2
    # A job still winding down keeps its terms until it stops.
    assert con.execute('SELECT COUNT(*) FROM job_terms WHERE job_id IN (?,?)',
                       (local, server)).fetchone()[0] == 2


def test_after_a_delete_the_real_name_is_nowhere_and_the_ledger_is_kept(con):
    done = _job(con, USER, 'done', claimed_by=USER, created_machine='owen-desktop')
    _job(con, OTHER_USER, 'done', claimed_by=USER)
    _ledger(con, 'a1', USER)
    _attest(con, USER, 'v1')
    _attest(con, USER, 'v2')
    _attest(con, OTHER_USER)

    counts = db.forget_requester(
        con, USER, STAND_IN, machine_stand_in=lambda m: 'deleted-machine-' + m[-2:])

    assert not [v for v in _every_text(con) if USER in v.lower()]
    assert 'owen-desktop' not in _every_text(con)
    assert db.get_job(con, done)['created_machine'] == 'deleted-machine-op'
    assert db.ledger_get(con, 'a1')['downloaded_by'] == STAND_IN
    assert {r['version'] for r in con.execute(
        'SELECT version FROM attestations WHERE username=?', (STAND_IN,))} == {'v1', 'v2'}
    assert db.attestation_of(con, OTHER_USER, 'v1') is not None
    assert con.execute('SELECT COUNT(*) FROM job_terms WHERE job_id=?',
                       (done,)).fetchone()[0] == 0
    # The finished job itself stays (the ledger's job_id points at it).
    assert db.get_job(con, done)['created_by'] == STAND_IN
    assert counts['downloads'] == 1 and counts['attestations'] == 2


def test_without_a_machine_stand_in_the_hostname_is_blanked(con):
    job = _job(con, USER, 'done', created_machine='owen-desktop')
    db.forget_requester(con, USER, STAND_IN)
    assert db.get_job(con, job)['created_machine'] is None


def test_a_second_delete_is_a_no_op_and_an_attestation_collision_keeps_one_row(con):
    _job(con, USER, 'done')
    _attest(con, USER, 'v1')
    db.forget_requester(con, USER, STAND_IN)
    # The same person seen again under another spelling, after the first pass.
    _attest(con, USER.upper(), 'v1')

    again = db.forget_requester(con, USER, STAND_IN)

    assert again['leases_released'] == again['jobs_cancelled'] == 0
    assert again['jobs_created'] == 0
    assert con.execute('SELECT COUNT(*) FROM attestations').fetchone()[0] == 1
    assert db.attestation_of(con, STAND_IN, 'v1') is not None


def test_the_nas_workers_own_mark_is_never_renamed(con):
    job = _job(con, 'server', 'done')
    db.forget_requester(con, 'server', STAND_IN)
    assert con.execute('SELECT download_host FROM job_videos WHERE job_id=?',
                       (job,)).fetchone()[0] == 'server'


# ------------------------------------------- the dashboard side (ytdl.py)

@pytest.fixture()
def dash():
    return pytest.importorskip('ccsync_dashboard.ytdl')


@pytest.fixture()
def dash_conn(tmp_path):
    dbmod = pytest.importorskip('ccsync_dashboard.db')
    c = dbmod.connect(tmp_path / 'dashboard.db')
    dbmod.migrate(c)
    yield c
    c.close()




def test_dashboard_side_never_creates_a_store(dash, tmp_path):
    missing = tmp_path / 'nope' / 'ytdl.db'
    assert dash.subject_rows(USER, db_path=missing) == {}
    assert dash.forget_history(USER, db_path=missing) == {}
    out = dash.forget_requester(USER, pseudonym=STAND_IN, db_path=missing)
    assert out['status'] == 'absent'
    assert not missing.exists()


def test_dashboard_delete_uses_the_dashboards_own_stand_ins(con, dash, dash_conn):
    dbmod = pytest.importorskip('ccsync_dashboard.db')
    job = _job(con, USER, 'done', created_machine='owen-desktop')

    out = dash.forget_requester(USER, dash_conn, db_path=config.DB_PATH)

    assert out['status'] == 'ok'
    assert out['pseudonym'] == dbmod.pseudonym(dash_conn, USER)
    row = db.get_job(con, job)
    assert row['created_by'] == dbmod.pseudonym(dash_conn, USER)
    assert row['created_machine'] == dbmod.machine_pseudonym(dash_conn, 'owen-desktop')


def test_dashboard_erase_history_answers_bare_counts(con, dash):
    _job(con, USER, 'done')
    _job(con, USER, 'queued')
    out = dash.forget_history(USER, db_path=config.DB_PATH)
    assert out['jobs'] == 1


def test_dashboard_side_raises_on_a_broken_store(dash, tmp_path):
    bad = tmp_path / 'ytdl.db'
    bad.write_bytes(b'this is not a database')
    for call in (lambda: dash.subject_rows(USER, db_path=bad),
                 lambda: dash.forget_history(USER, db_path=bad),
                 lambda: dash.forget_requester(USER, pseudonym=STAND_IN, db_path=bad)):
        with pytest.raises(dash.YtdlStoreError) as err:
            call()
        assert chr(0x2014) not in str(err.value)


# ----------------------------------- review round (G4 adversarial, 2026-09-25)

def test_review_1_the_export_carries_the_youtube_tables(con, dash, dash_conn):
    # The first build answered {"status", "detail", "tables"}; subject_data
    # filed "status" as a table, raised, and the export held no YouTube rows.
    sd = pytest.importorskip('ccsync_dashboard.subject_data')
    _job(con, USER)
    _ledger(con, 'a1', USER)
    _attest(con, USER)

    export = sd.collect(dash_conn, USER)

    assert len(export['tables']['ytdl.jobs']) == 1
    assert len(export['tables']['ytdl.downloads']) == 1
    assert len(export['tables']['ytdl.attestations']) == 1
    assert not [m for m in export['not_included'] if m.startswith('YouTube')]


def test_review_1_an_unreadable_store_is_named_in_the_export(dash, dash_conn,
                                                             tmp_path, monkeypatch):
    sd = pytest.importorskip('ccsync_dashboard.subject_data')
    bad = tmp_path / 'broken.db'
    bad.write_bytes(b'this is not a database')
    monkeypatch.setattr(config, 'DB_PATH', bad)
    export = sd.collect(dash_conn, USER)
    assert [m for m in export['not_included'] if m.startswith('YouTube')]


def test_review_2_a_one_argument_delete_uses_the_mounted_dashboard_db(
        con, dash, dash_conn, tmp_path, monkeypatch):
    # api._forget_elsewhere calls func(username). The first build answered
    # {"status": "error"} without raising, so nothing was renamed and the
    # delete read as done.
    dbmod = pytest.importorskip('ccsync_dashboard.db')
    api = pytest.importorskip('ccsync_dashboard.api')
    from types import SimpleNamespace
    dash_conn.commit()
    monkeypatch.setattr(dash, '_DASHBOARD_DB_PATH', str(tmp_path / 'dashboard.db'))
    local = _job(con, USER, 'downloading', download_mode='local', claimed_by=USER,
                 lease_expires_at=_iso(300))

    result = {}
    api._forget_elsewhere(SimpleNamespace(app=None), dash_conn, USER, result)

    assert result['ytdl_forgotten']['status'] == 'ok'
    row = db.get_job(con, local)
    assert row['created_by'] == dbmod.pseudonym(dash_conn, USER)
    assert not db.lease_active(row)
    assert not [w for w in result['warnings'] if 'YouTube' in w]


def test_review_2_a_delete_uses_the_connection_in_hand_and_warns_on_a_store_failure(
        con, dash, dash_conn, monkeypatch):
    dbmod = pytest.importorskip('ccsync_dashboard.db')
    api = pytest.importorskip('ccsync_dashboard.api')
    from types import SimpleNamespace
    monkeypatch.setattr(dash, '_DASHBOARD_DB_PATH', None)
    monkeypatch.delenv('DASH_DB_PATH', raising=False)
    job = _job(con, USER, 'done')
    with pytest.raises(dash.YtdlStoreError):
        dash.forget_requester(USER)
    # api._forget_elsewhere hands over the dashboard connection and the
    # stand-in it minted (G2a review round point 1), so the recorded path is
    # not needed there and the delete goes through with no warning ...
    result = {}
    api._forget_elsewhere(SimpleNamespace(app=None), dash_conn, USER, result)
    assert not [w for w in result['warnings'] if 'YouTube' in w]
    assert db.get_job(con, job)['created_by'] == dbmod.pseudonym(dash_conn, USER)
    # ... and a store that cannot be updated is a warning the admin reads,
    # never a finished delete that kept the name (final review 2026-09-25).
    job2 = _job(con, USER, 'done')
    def refuse(*a, **k):
        raise dash.YtdlStoreError('the store is locked')
    monkeypatch.setattr(dash, 'forget_requester', refuse)
    result = {}
    api._forget_elsewhere(SimpleNamespace(app=None), dash_conn, USER, result)
    assert [w for w in result['warnings'] if 'YouTube' in w]
    assert db.get_job(con, job2)['created_by'] == USER


def test_review_3_erase_history_counts_reach_the_audit_shape(con, dash):
    sda = pytest.importorskip('ccsync_dashboard.subject_data_api')
    _job(con, USER, 'done')
    removed = {}
    sda._add_counts(removed, 'ytdl', dash.forget_history(USER))
    assert removed['ytdl.jobs'] == 1 and removed['ytdl.job_terms'] == 1
    assert 'ytdl.detail' not in removed


def test_review_4_a_stopping_jobs_terms_go_when_it_stops(con):
    from ytdlweb import worker
    job = _job(con, USER, 'searching')
    db.forget_requester(con, USER, STAND_IN)
    # Still inside a phase: its worker may be reading them.
    assert con.execute('SELECT COUNT(*) FROM job_terms WHERE job_id=?',
                       (job,)).fetchone()[0] == 1

    worker.run_job(con, job)                  # sees the flag, writes cancelled

    assert db.get_job(con, job)['phase'] == 'cancelled'
    for table in ('job_terms', 'job_video_terms'):
        assert con.execute(f'SELECT COUNT(*) FROM {table} WHERE job_id=?',
                           (job,)).fetchone()[0] == 0


def test_review_4_an_ordinary_cancel_keeps_the_terms(con):
    from ytdlweb import worker
    job = _job(con, USER, 'searching')
    db.request_cancel(con, job)
    worker.run_job(con, job)
    assert db.get_job(con, job)['phase'] == 'cancelled'
    assert con.execute('SELECT COUNT(*) FROM job_terms WHERE job_id=?',
                       (job,)).fetchone()[0] == 1


class _Watched:
    """A connection whose every commit is followed by a look from outside,
    the way the worker thread's own connection would see the store."""

    def __init__(self, c, look):
        self._c, self._look = c, look

    def execute(self, *a, **k):
        return self._c.execute(*a, **k)

    def commit(self):
        self._c.commit()
        self._look()

    def rollback(self):
        self._c.rollback()


def test_review_5_no_commit_shows_an_expired_lease_under_the_real_name(con):
    other = _job(con, OTHER_USER, 'downloading', download_mode='local',
                 claimed_by=USER, lease_expires_at=_iso(300))
    mine = _job(con, USER, 'downloading', download_mode='local',
                claimed_by=USER, lease_expires_at=_iso(300))
    seen = []

    def look():
        outside = sqlite3.connect(config.DB_PATH)
        outside.row_factory = sqlite3.Row
        try:
            for job in outside.execute('SELECT * FROM jobs WHERE id IN (?,?)',
                                       (other, mine)):
                # What claim_next_job would hand _reclaim_local_job, whose
                # download_host=holder write is how the name came back.
                if not db.lease_active(job) and job['claimed_by'] == USER:
                    seen.append(job['id'])
        finally:
            outside.close()

    db.forget_requester(_Watched(con, look), USER, STAND_IN)

    assert seen == []
    assert db.get_job(con, other)['claimed_by'] == STAND_IN


def test_review_6_a_clip_finished_after_the_delete_is_credited_to_the_stand_in(con):
    job = _job(con, USER, 'downloading')      # a server download, mid-clip
    stale_created_by = db.get_job(con, job)['created_by']
    db.forget_requester(con, USER, STAND_IN)

    # worker._phase_download's ledger_add, from the row it read before.
    db.ledger_add(con, 'late0000001', 't', 'c', '2026-ff5-energy',
                  '2026/FF5/Energy Transition', 'taipei skyline',
                  'Youtube/taipei skyline/late.mp4', job, stale_created_by)

    assert db.ledger_get(con, 'late0000001')['downloaded_by'] == STAND_IN
    # With no job row behind it the caller's name is still the credit.
    db.ledger_add(con, 'solo0000001', 't', 'c', 's', 'l', 'x', 'Youtube/x/y.mp4',
                  None, OTHER_USER)
    assert db.ledger_get(con, 'solo0000001')['downloaded_by'] == OTHER_USER


def test_review_8_an_export_carries_nothing_of_another_persons_search(con):
    theirs = _job(con, OTHER_USER, 'done', claimed_by=USER, download_mode='local',
                  term='a private topic', term_dir='a private topic')
    con.execute('UPDATE job_videos SET filepath=?, relevance_note=? WHERE job_id=?',
                ('/p/Youtube/a private topic/x.mp4', 'about a private topic', theirs))
    con.commit()
    mine = _job(con, USER, 'done')

    rows = db.subject_rows(con, USER)

    by_id = {r['id']: r for r in rows['jobs']}
    assert by_id[theirs]['claimed_by'] == USER
    assert 'created_by' not in by_id[theirs] and 'term' not in by_id[theirs]
    assert by_id[mine]['term'] == 'taipei skyline'      # their own is whole
    text = repr(rows)
    assert OTHER_USER not in text and 'private topic' not in text
