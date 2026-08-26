"""RETRY: a job parked at `failed` in the download phase is re-queueable.

docs/YTDL_RESILIENCE_PLAN.md WP6 (2026-08-26). The CR-80 recovery was one
`POST /ytdl/api/jobs/28/download`, which re-queued exactly the 29 failed rows
-- that only worked because the job had ended `done`. The circuit breaker added
the same day parks a job at `failed` instead, and a `failed` job used to answer
409 to the one call that would fix it.

The distinction this file exists to pin: `failed` is accepted only when the job
has download rows. A job that died in search or enrich has nothing to re-queue,
and walking it back through a phase it never left would be a button that
silently does nothing.
"""
from tests.conftest import USER
from ytdlweb import db


def _rows(con, job_id, states):
    for vid, state in states.items():
        db.add_video(con, job_id, vid, f'https://www.youtube.com/watch?v={vid}')
        db.set_video(con, job_id, vid, dl_state=state)


def test_a_job_the_breaker_parked_is_re_queued_by_the_same_call(client, con, job):
    """The breaker leaves failed rows `failed` and the rows it never reached
    `pending`; both belong in the retry."""
    _rows(con, job['id'], {'vid00000001': 'done', 'vid00000002': 'failed',
                           'vid00000003': 'pending'})
    db.set_phase(con, job['id'], 'failed',
                 '3 clips in a row came back with no usable format.')

    r = client.post(f'/api/jobs/{job["id"]}/download')
    assert r.status_code == 200 and r.json()['queued'] == 2
    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'downloading' and fresh['dl_total'] == 2
    assert [v['video_id'] for v in db.pending_videos(con, job['id'])] == \
        ['vid00000002', 'vid00000003']
    assert db.get_video(con, job['id'], 'vid00000001')['dl_state'] == 'done'


def test_the_retry_clears_the_note_the_failure_left(client, con, job):
    """db.set_phase only ever WRITES `error`, so without this the breaker's
    note is painted as a banner over a run that is going fine (app.js reads
    `job.error` as the banner's whole condition)."""
    _rows(con, job['id'], {'vid00000001': 'failed'})
    db.set_phase(con, job['id'], 'failed', 'HTTP Error 403 on 3 clips in a row.')
    assert db.get_job(con, job['id'])['error']

    assert client.post(f'/api/jobs/{job["id"]}/download').status_code == 200
    assert not db.get_job(con, job['id'])['error']


def test_a_job_that_died_before_the_download_phase_keeps_its_409(client, con, job):
    """A bot check in the search phase leaves a job with candidate rows and no
    download state. There is nothing to re-queue and the fix is a new search,
    so the button must not pretend otherwise."""
    db.add_video(con, job['id'], 'vid00000001', 'u')          # dl_state 'none'
    db.set_phase(con, job['id'], 'failed', 'YouTube is asking this server...')

    r = client.post(f'/api/jobs/{job["id"]}/download')
    assert r.status_code == 409
    detail = r.json()['detail']
    assert detail['phase'] == 'failed'
    assert 'nothing to retry' in detail['detail']
    assert db.get_job(con, job['id'])['phase'] == 'failed'


def test_a_job_with_no_rows_at_all_keeps_its_409(client, con, job):
    """The Claude-failed shape: the job never got as far as a candidate."""
    db.set_phase(con, job['id'], 'failed', 'claude_auth: no provider')
    r = client.post(f'/api/jobs/{job["id"]}/download')
    assert r.status_code == 409
    assert 'nothing to retry' in r.json()['detail']['detail']


def test_the_retry_is_still_one_job_per_editor(client, con, job):
    """Reviving a terminal job makes it active again, and YTDL-25's rule is
    unchanged by which terminal phase it was in."""
    _rows(con, job['id'], {'vid00000001': 'failed'})
    db.set_phase(con, job['id'], 'failed', 'stopped')
    other = db.create_job(con, USER, 'second topic', 'second-topic',
                          job['project_slug'], job['project_label'])

    r = client.post(f'/api/jobs/{job["id"]}/download')
    assert r.status_code == 409
    assert r.json()['detail']['job_id'] == other
    assert db.get_job(con, job['id'])['phase'] == 'failed'


def test_the_retry_forgives_the_last_runs_executor_pin(client, con, job):
    """Same as the `done` branch (YTDL-WEB-7 / CR-37): this is a fresh human
    request, and a pin that survived it would refuse the editor's own machine
    for reasons belonging to the run that ended."""
    _rows(con, job['id'], {'vid00000001': 'failed'})
    db.lock_mode(con, job['id'], db.MODE_SERVER)
    db.set_phase(con, job['id'], 'failed', 'stopped')

    assert client.post(f'/api/jobs/{job["id"]}/download').status_code == 200
    assert not db.get_job(con, job['id'])['mode_lock']
