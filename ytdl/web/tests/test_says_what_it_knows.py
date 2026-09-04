"""What the server MEASURES and now SAYS (wave 3, 2026-09-04).

The YTWEB sweep's shape was "the server measures more than the page shows":
`js_runtime` computed and rendered nowhere, the degraded-filter note composed
and thrown away, the companion's free-space report written into a log line, and
a queue whose only number was counted per editor while the worker is serial
across the whole site. This file pins the server halves of the five that landed
here: YTWEB-1 (what a queued job waits on), YTWEB-3 (the JS runtime in a note
that could name it), YTWEB-8/13 (what is moving beats what is parked, and the
parked ones are listed), YTWEB-9 (free space), YTWEB-11 (a manifest row knows
its own folder).
"""
import pytest

from ytdlweb import config, db, routes_api, worker

from .conftest import OTHER_USER, PROJECTS, USER


def _job_for(con, user, term='a', phase='queued'):
    slug, label, _ = PROJECTS[0]
    job_id = db.create_job(con, user, term, config.safe_term_dirname(term),
                           slug, label, quality='1080p', max_per_term=5,
                           auto_terms=True)
    if phase != 'queued':
        db.set_phase(con, job_id, phase)
    return job_id


# ------------------------------------------------------------------ YTWEB-1

def test_a_queued_job_counts_the_jobs_of_other_editors_ahead_of_it(con):
    """The worker is fleet-serial, and every number this app had was counted
    per editor -- so the commonest queue there is (one editor behind another)
    reported `queued_behind: 0` and the page said nothing at all."""
    theirs = _job_for(con, OTHER_USER, 'theirs', phase='enriching')
    mine = _job_for(con, USER, 'mine')
    assert db.fleet_ahead(con, mine) == 1

    # ...and when that job finishes, this one is next and says so.
    db.set_phase(con, theirs, 'done')
    assert db.fleet_ahead(con, mine) == 0


def test_an_editors_own_jobs_are_not_counted_twice(con):
    """`queued_behind` already counts those. fleet_ahead is the other half of
    the sentence, not a total: adding them here would print an editor's own
    running job twice."""
    _job_for(con, USER, 'busy', phase='searching')
    mine = _job_for(con, USER, 'mine')
    assert db.fleet_ahead(con, mine) == 0


def test_a_job_that_cannot_start_yet_is_behind_the_whole_fleet(con):
    """Not startable (its own editor has something busy) means it is behind
    every candidate, not ahead of the ones that sort after it."""
    _job_for(con, USER, 'busy', phase='searching')
    _job_for(con, OTHER_USER, 'theirs', phase='queued')
    mine = _job_for(con, USER, 'mine')
    assert db.fleet_ahead(con, mine) == 1


def test_the_create_answer_carries_the_fleet_count_and_the_worker(client, con):
    _job_for(con, OTHER_USER, 'theirs', phase='enriching')
    r = client.post('/api/jobs', json={'term': 'reef',
                                       'project_slug': PROJECTS[0][0]})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body['fleet_ahead'] == 1, body
    assert 'worker_alive' in body, body


def test_the_poll_says_what_a_queued_job_is_waiting_on(client, con, job):
    """On the POLL and not only on the create answer: a toast is gone in seven
    seconds, and a page reloaded onto a job still at `queued` has to be able to
    say the same sentence."""
    _job_for(con, OTHER_USER, 'theirs', phase='enriching')
    r = client.get(f'/api/jobs/{job["id"]}').json()
    assert r['job']['phase'] == 'queued'
    assert r['queued_behind'] == 0 and r['fleet_ahead'] == 1

    # Every other phase has counters of its own and nothing to add.
    db.set_phase(con, job['id'], 'searching')
    r = client.get(f'/api/jobs/{job["id"]}').json()
    assert 'fleet_ahead' not in r and 'queued_behind' not in r


# --------------------------------------------------------------- YTWEB-8/13

def test_what_is_moving_beats_what_is_parked(con):
    """The queue deliberately lets a second search start while an older one
    sits at ready_for_review. On a reload the page attached to the week-old
    parked review and the job actually downloading appeared nowhere."""
    parked = _job_for(con, USER, 'old', phase='ready_for_review')
    running = _job_for(con, USER, 'new', phase='downloading')
    assert db.active_job(con, USER)['id'] == running

    db.set_phase(con, running, 'done')
    assert db.active_job(con, USER)['id'] == parked


def test_the_newest_parked_review_is_the_one_the_page_is_about(con):
    older = _job_for(con, USER, 'older', phase='ready_for_review')
    newer = _job_for(con, USER, 'newer', phase='terms_review')
    assert db.active_job(con, USER)['id'] == newer
    assert [j['id'] for j in db.parked_jobs(con, USER)] == [older, newer]


def test_the_active_route_lists_the_parked_reviews_without_the_attached_one(
        client, con):
    first = _job_for(con, USER, 'first', phase='ready_for_review')
    second = _job_for(con, USER, 'second', phase='ready_for_review')
    running = _job_for(con, USER, 'running', phase='downloading')
    r = client.get('/api/jobs/active').json()
    assert r['job']['id'] == running
    assert [w['id'] for w in r['waiting']] == [first, second]
    assert [w['position'] for w in r['waiting']] == [1, 2]

    # The attached job is never also in the list: one job on screen twice,
    # offering to open what is already open.
    db.set_phase(con, running, 'cancelled')
    r = client.get('/api/jobs/active').json()
    assert r['job']['id'] == second
    assert [w['id'] for w in r['waiting']] == [first]


def test_the_parked_list_is_per_editor(client, con):
    _job_for(con, OTHER_USER, 'theirs', phase='ready_for_review')
    assert client.get('/api/jobs/active').json()['waiting'] == []


# ------------------------------------------------------------------ YTWEB-9

def test_the_estimate_is_the_duration_times_the_rung(con, job):
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.set_video(con, job['id'], 'vid00000001', duration=600)
    rows = db.videos(con, job['id'])
    assert routes_api.estimated_bytes(rows, '1080p') == 600 * 1_000_000
    assert routes_api.estimated_bytes(rows, '2160p') == 600 * 4_400_000
    # An unknown rung reads as 1080p rather than as zero: an estimate of
    # nothing is the one that lets a full disk through.
    assert routes_api.estimated_bytes(rows, 'wat') == 600 * 1_000_000
    # ...and a manifest with no durations (every paste) cannot be sized.
    db.set_video(con, job['id'], 'vid00000001', duration=0)
    assert routes_api.estimated_bytes(db.videos(con, job['id']), '1080p') == 0


def test_a_full_disk_refuses_the_download_and_names_the_number(
        client, con, job, monkeypatch):
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.set_video(con, job['id'], 'vid00000001', duration=3600)  # ~3.6 GB
    db.set_phase(con, job['id'], 'ready_for_review')
    monkeypatch.setattr(routes_api, 'free_bytes_at', lambda p, now=None: 4 * 10 ** 9)

    r = client.post(f'/api/jobs/{job["id"]}/download')
    assert r.status_code == 409, r.json()
    detail = r.json()['detail']
    assert detail['reason'] == 'disk_full'
    assert '4.0 GB free' in detail['detail'], detail
    assert '3.6 GB' in detail['detail'], detail   # what it needs, named
    assert job['project_label'] in detail['detail'], detail
    # Nothing was started and nothing was written: the check runs BEFORE
    # mark_pending, so the job is exactly as it was found.
    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'ready_for_review'
    assert db.get_video(con, job['id'], 'vid00000001')['dl_state'] == 'none'


def test_room_enough_downloads_exactly_as_before(client, con, job, monkeypatch):
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.set_video(con, job['id'], 'vid00000001', duration=3600)
    db.set_phase(con, job['id'], 'ready_for_review')
    monkeypatch.setattr(routes_api, 'free_bytes_at', lambda p, now=None: 500 * 10 ** 9)
    assert client.post(f'/api/jobs/{job["id"]}/download').status_code == 200


def test_a_disk_that_cannot_be_read_fails_open(client, con, job, monkeypatch):
    """A check that cannot see the disk must not be the thing that refuses a
    download: the point is to turn N opaque per-clip errors into one sentence,
    not to become a new way for a download to be impossible."""
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.set_video(con, job['id'], 'vid00000001', duration=3600)
    db.set_phase(con, job['id'], 'ready_for_review')
    monkeypatch.setattr(routes_api, 'free_bytes_at', lambda p, now=None: None)
    assert client.post(f'/api/jobs/{job["id"]}/download').status_code == 200


def test_an_unsizeable_selection_still_needs_two_gigabytes(
        client, con, job, monkeypatch):
    """A paste has no durations at all, so there is nothing to size -- but a
    disk with less than the floor on it is not one to start writing to."""
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.set_phase(con, job['id'], 'ready_for_review')
    monkeypatch.setattr(routes_api, 'free_bytes_at', lambda p, now=None: 10 ** 9)
    r = client.post(f'/api/jobs/{job["id"]}/download')
    assert r.status_code == 409
    assert 'room to work in' in r.json()['detail']['detail']

    monkeypatch.setattr(routes_api, 'free_bytes_at', lambda p, now=None: 9 * 10 ** 9)
    assert client.post(f'/api/jobs/{job["id"]}/download').status_code == 200


def test_free_space_is_read_from_the_nearest_real_directory_and_cached(tmp_path):
    """The destination is created by the download phase, so at the moment of
    the check it usually does not exist yet -- and the filesystem being asked
    about is the same one either way."""
    routes_api._free_cache.clear()
    missing = tmp_path / 'Youtube' / 'algal reef'
    free = routes_api.free_bytes_at(missing)
    assert free is not None and free > 0

    calls = []
    real = routes_api.shutil.disk_usage

    def counting(path):
        calls.append(path)
        return real(path)

    routes_api.shutil.disk_usage = counting
    try:
        assert routes_api.free_bytes_at(missing) == free
        assert calls == [], 'the 60 s cache was not consulted'
        # ...and it does expire.
        assert routes_api.free_bytes_at(missing, now=routes_api.time.time() + 61)
        assert calls, 'the cache never expires'
    finally:
        routes_api.shutil.disk_usage = real


def test_the_claiming_machines_free_space_lands_on_the_job(con, job):
    """It was a log line and nothing else. The page prints it as the only
    disk-space signal an editor pressing DOWNLOAD has ever had."""
    db.set_phase(con, job['id'], 'downloading')
    assert db.claim_download(con, job['id'], USER, 300, machine='m1',
                             free_bytes=123 * 10 ** 9)
    assert db.get_job(con, job['id'])['claim_free_bytes'] == 123 * 10 ** 9
    assert db.job_dict(db.get_job(con, job['id']))['claim_free_bytes'] \
        == 123 * 10 ** 9

    # A refresh from a companion that does not send the field keeps the last
    # answer rather than blanking it.
    assert db.claim_download(con, job['id'], USER, 300, machine='m1')
    assert db.get_job(con, job['id'])['claim_free_bytes'] == 123 * 10 ** 9

    # ...and nonsense is a note nobody is refused over.
    assert db.claim_download(con, job['id'], USER, 300, machine='m1',
                             free_bytes='plenty')
    assert db.get_job(con, job['id'])['claim_free_bytes'] == 123 * 10 ** 9


# ----------------------------------------------------------------- YTWEB-11

def test_a_landed_manifest_row_knows_its_folder(client, con, job):
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.set_video(con, job['id'], 'vid00000001', dl_state='done',
                 filepath='/srv/whatever/Channel [vid00000001].mp4')
    db.add_video(con, job['id'], 'vid00000002', 'u')
    con.commit()                      # the route reads its own connection
    m = client.get(f'/api/jobs/{job["id"]}/manifest').json()
    paths = {v['video_id']: v['reveal_path'] for v in m['videos']}
    assert paths['vid00000001'] == (
        f'{job["project_label"]}/Youtube/{job["term_dir"]}/'
        'Channel [vid00000001].mp4')
    # A row with no file has no folder to offer: pending, failed, or skipped
    # as a duplicate.
    assert paths['vid00000002'] is None


def test_a_windows_filepath_is_read_by_its_own_separator(con, job):
    """The path was written on some OTHER machine, so this one's rules are the
    wrong ones to read it with."""
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.set_video(con, job['id'], 'vid00000001', dl_state='done',
                 filepath=r'P:\Projects\X\Youtube\t\Channel [vid00000001].mp4')
    v = db.get_video(con, job['id'], 'vid00000001')
    assert db.video_reveal_path(job, v).endswith('/Channel [vid00000001].mp4')
    assert '\\' not in db.video_reveal_path(job, v)


def test_a_paste_reveals_into_the_youtube_root(con):
    """A url job has no term_dir: its clips land in Youtube/ itself, and the
    path must not carry an empty segment nothing downstream can split."""
    slug, label, _ = PROJECTS[0]
    job_id = db.create_url_job(
        con, USER, '', '', slug, label,
        [{'video_id': 'vid00000001', 'url': 'https://youtu.be/vid00000001'}])
    job = db.get_job(con, job_id)
    db.set_video(con, job_id, 'vid00000001', dl_state='done',
                 filepath='/x/Channel [vid00000001].mp4')
    v = db.get_video(con, job_id, 'vid00000001')
    assert db.video_reveal_path(job, v) == \
        f'{label}/Youtube/Channel [vid00000001].mp4'


# ------------------------------------------------------------------ YTWEB-3/7

def test_the_no_format_note_names_the_missing_js_runtime(monkeypatch):
    """YTDL-24 cost a week: without deno or node every clip fails "Requested
    format is not available", and the note that reached the editor sent them to
    a yt-dlp update that would have changed nothing."""
    monkeypatch.setattr(routes_api, '_js_runtime_state', lambda: 'missing')
    note = worker.identical_failure_note(3, 'ERROR: Requested format is not available')
    assert 'JavaScript runtime' in note and 'deno' in note
    assert 'check for a yt-dlp update' not in note

    monkeypatch.setattr(routes_api, '_js_runtime_state', lambda: 'ok')
    note = worker.identical_failure_note(3, 'ERROR: Requested format is not available')
    assert 'JavaScript runtime' not in note
    assert 'yt-dlp update' in note


def test_the_degraded_note_says_what_it_means_for_the_manifest():
    """The editor was shown the generic AI-provider hint and never told that
    the manifest below them is UNFILTERED, which is the fact that changes what
    they do next."""
    assert 'unfiltered' in worker.DEGRADED_NOTE
    assert '--' not in worker.DEGRADED_NOTE, 'a double hyphen in visible copy'


@pytest.mark.parametrize('key', ['js_runtime'])
def test_the_health_body_still_carries_what_the_strip_now_reads(client, key):
    assert key in client.get('/api/health').json()
