"""The JSON API: identity, the ticked-projects gate, and every refusal.

The refusals are the interesting half. This app writes into the Projects tree,
so "409 because you already have a job" and "400 because that is not a project
you sync" are the actual product, not error handling.
"""
from fastapi.testclient import TestClient

from tests.conftest import OTHER_USER, PROJECTS, USER
from ytdlweb import db, routes_api
from ytdlweb.main import app


def _headers(user):
    return {'x-ccsync-user': user}


def test_me_reads_the_gate_injected_header(client):
    assert client.get('/api/me').json() == {'user': USER}


def test_no_header_and_no_dev_user_is_a_401(con):
    """A deployed host whose gate stopped injecting the header must fail loudly
    rather than pool every editor's jobs under one anonymous name."""
    with TestClient(app) as c:
        r = c.get('/api/me')
    assert r.status_code == 401
    assert 'not signed in' in r.json()['detail']


def test_projects_are_the_editors_ticked_ones_in_sync_order(client):
    r = client.get('/api/projects').json()
    assert r['projects_available'] is True
    assert [p['slug'] for p in r['projects']] == [p[0] for p in PROJECTS]
    assert [p['label'] for p in r['projects']] == [p[1] for p in PROJECTS]


def test_an_inactive_project_is_not_offered(client):
    """A selections row survives a folder disappearing from syncthing; the
    projects.active=1 join is what stops it being offered as a destination."""
    slugs = [p['slug'] for p in client.get('/api/projects').json()['projects']]
    assert '2024-old' not in slugs


def test_another_editors_projects_are_not_visible(client):
    r = client.get('/api/projects', headers=_headers(OTHER_USER)).json()
    assert [p['slug'] for p in r['projects']] == ['2025-ff4-nuclear']


def test_no_dashboard_database_reports_unavailable_not_empty(client, monkeypatch):
    """"this app cannot read the project list" and "you have ticked nothing"
    are opposite messages to an editor, so the flag is about the DATABASE."""
    from ytdlweb import config, projects
    monkeypatch.setattr(config, 'DASH_DB', '')
    monkeypatch.setattr(config, 'DEV_PROJECTS', '')
    r = client.get('/api/projects').json()
    assert r['projects_available'] is False
    assert r['projects'] == []
    assert 'YTDL_DASH_DB' in r['error']
    assert projects.resolve_project(USER, PROJECTS[0][0]) is None


def test_the_dev_project_fallback_keeps_the_app_runnable_standalone(monkeypatch):
    """`uvicorn ytdlweb.main:app` on a dev box has no dashboard database."""
    from ytdlweb import config, projects
    monkeypatch.setattr(config, 'DASH_DB', '')
    monkeypatch.setattr(config, 'DEV_PROJECTS', 'slug-a=2026/A,slug-b')
    r = projects.ticked_projects(USER)
    assert r['available'] is False
    assert r['projects'] == [{'slug': 'slug-a', 'label': '2026/A'},
                             {'slug': 'slug-b', 'label': 'slug-b'}]
    assert projects.resolve_project(USER, 'slug-a')['label'] == '2026/A'


def test_a_missing_dashboard_database_is_reported_not_raised(client, monkeypatch):
    from ytdlweb import config
    monkeypatch.setattr(config, 'DASH_DB', str(config.DATA_ROOT / 'nope.db'))
    r = client.get('/api/projects').json()
    assert r['projects_available'] is False and 'does not exist' in r['error']


def test_health_is_served_from_the_cache_not_a_probe(client, monkeypatch):
    """api/health must never shell out: it is hit on every page load, and
    `claude -p` is a second or two each time."""
    from ytdlweb import claude_cli
    calls = []
    monkeypatch.setattr(claude_cli, '_invoke',
                        lambda *a, **k: calls.append(a) or 'nope')
    h = client.get('/api/health').json()
    assert set(h) >= {'claude', 'yt_dlp', 'worker_alive'}
    assert calls == []


def test_health_reports_a_missing_js_runtime(client, monkeypatch):
    """YTDL-24: without deno/node every video fails with "Requested format is
    not available", which reads as YouTube flakiness -- while health said
    all-ok and nothing anywhere named the real cause."""
    from ytdlweb import routes_api
    monkeypatch.setattr(routes_api.shutil, 'which', lambda name: None)
    assert client.get('/api/health').json()['js_runtime'] == 'missing'
    monkeypatch.setattr(routes_api.shutil, 'which',
                        lambda name: '/opt/deno/deno' if name == 'deno' else None)
    assert client.get('/api/health').json()['js_runtime'] == 'ok'


def test_creating_a_job_validates_the_project_server_side(client):
    """The picker in the browser is a convenience; this is the check. Without
    it an editor could drop 40 videos into a project they do not sync."""
    r = client.post('/api/jobs', json={'term': 'reef', 'project_slug': '2025-ff4-nuclear'})
    assert r.status_code == 400
    assert 'not one you are syncing' in r.json()['detail']


def test_creating_a_job_queues_it(client, con):
    r = client.post('/api/jobs', json={'term': 'algal reef', 'project_slug': PROJECTS[0][0],
                                       'period': 'month'})
    assert r.status_code == 200
    job = db.get_job(con, r.json()['job_id'])
    assert job['phase'] == 'queued'
    assert job['created_by'] == USER
    assert job['term_dir'] == 'algal reef'
    assert job['project_label'] == PROJECTS[0][1]
    assert job['period'] == 'month'


def test_a_second_job_is_refused_while_one_is_running(client):
    first = client.post('/api/jobs', json={'term': 'a', 'project_slug': PROJECTS[0][0]})
    assert first.status_code == 200
    second = client.post('/api/jobs', json={'term': 'b', 'project_slug': PROJECTS[0][0]})
    assert second.status_code == 409
    assert second.json()['detail']['job_id'] == first.json()['job_id']


def test_a_double_click_cannot_create_two_active_jobs(client, con, monkeypatch):
    """YTDL-25: the one-job check is read-then-insert, and a double-clicked
    SEARCH lands between the two -- the second job then orphans the first,
    which is the one active_job hands to every later 409."""
    from ytdlweb import db as dbmod

    real, seen = dbmod.active_job, []

    def blind(c, user):
        # the first two calls are the read checks, which see nothing (the race);
        # anything after that is the recovery path and gets the truth
        seen.append(user)
        return None if len(seen) <= 2 else real(c, user)

    monkeypatch.setattr(dbmod, 'active_job', blind)
    first = client.post('/api/jobs', json={'term': 'a', 'project_slug': PROJECTS[0][0]})
    second = client.post('/api/jobs', json={'term': 'b', 'project_slug': PROJECTS[0][0]})
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()['detail']['job_id'] == first.json()['job_id']
    assert len(db.recent_jobs(con, USER)) == 1


def test_an_enormous_topic_is_refused_rather_than_handed_to_claude(client):
    """YTDL-7: the term is one argv element of `claude -p`, and Linux caps a
    single argument at 128 KiB -- the OSError came back classified as "the
    claude CLI is not installed" and pinned that banner on everyone."""
    r = client.post('/api/jobs', json={'term': 'x' * 401,
                                       'project_slug': PROJECTS[0][0]})
    assert r.status_code == 400
    assert '400 characters' in r.json()['detail']
    assert client.post('/api/jobs', json={'term': 'x' * 400,
                                          'project_slug': PROJECTS[0][0]}).status_code == 200


def test_bad_period_and_quality_are_refused(client):
    for body in ({'term': 'a', 'project_slug': PROJECTS[0][0], 'period': 'fortnight'},
                 {'term': 'a', 'project_slug': PROJECTS[0][0], 'quality': '8k'}):
        assert client.post('/api/jobs', json=body).status_code == 400
    assert client.post('/api/jobs', json={'term': '  ',
                                          'project_slug': PROJECTS[0][0]}).status_code == 400


def test_another_editors_job_is_a_404_not_a_403(client, job):
    """404, because "there is no such job" is all another editor is entitled
    to know about it."""
    for path in ('', '/manifest'):
        r = client.get(f'/api/jobs/{job["id"]}{path}', headers=_headers(OTHER_USER))
        assert r.status_code == 404
    r = client.post(f'/api/jobs/{job["id"]}/cancel', headers=_headers(OTHER_USER))
    assert r.status_code == 404


def test_poll_returns_counters_terms_and_the_progress_map(client, con, job):
    db.add_term(con, job['id'], 'reef', 'en', 'user')
    tid = db.add_term(con, job['id'], '藻礎', 'zh', 'claude', 'algal reef')
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.link_term(con, job['id'], 'vid00000001', tid)
    con.commit()
    db.set_job(con, job['id'], terms_total=2, terms_done=1, candidates=1)

    r = client.get(f'/api/jobs/{job["id"]}').json()
    assert r['job']['terms_done'] == 1
    assert r['job']['terminal'] is False
    zh = [t for t in r['terms'] if t['lang'] == 'zh'][0]
    assert zh['english_gloss'] == 'algal reef'
    assert zh['videos'] == 1
    assert r['progress'] == {}


def test_manifest_carries_term_ids_for_the_chip_filter(client, con, job):
    t1 = db.add_term(con, job['id'], 'one', 'en', 'user')
    t2 = db.add_term(con, job['id'], 'two', 'en', 'claude')
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.link_term(con, job['id'], 'vid00000001', t1)
    db.link_term(con, job['id'], 'vid00000001', t2)
    con.commit()
    m = client.get(f'/api/jobs/{job["id"]}/manifest').json()
    assert m['videos'][0]['term_ids'] == [t1, t2]
    assert m['counts']['total'] == 1


def test_selecting_a_duplicate_is_a_409(client, con, job):
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.set_video(con, job['id'], 'vid00000001', duplicate=1, selected=0,
                 duplicate_of='2025/FF4/Nuclear/reef')
    r = client.post(f'/api/jobs/{job["id"]}/videos/vid00000001/select',
                    json={'selected': True})
    assert r.status_code == 409
    assert r.json()['detail']['duplicate_of'] == '2025/FF4/Nuclear/reef'
    assert db.get_video(con, job['id'], 'vid00000001')['selected'] == 0


def test_select_toggle_and_bulk(client, con, job):
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.add_video(con, job['id'], 'vid00000002', 'u')
    # as the filter phase leaves a dropped video: not relevant, not selected
    db.set_video(con, job['id'], 'vid00000002', relevant=0, selected=0)

    r = client.post(f'/api/jobs/{job["id"]}/videos/vid00000001/select',
                    json={'selected': False})
    assert r.status_code == 200 and r.json()['selected'] is False

    client.post(f'/api/jobs/{job["id"]}/select', json={'selected': True, 'scope': 'relevant'})
    assert db.get_video(con, job['id'], 'vid00000001')['selected'] == 1
    assert db.get_video(con, job['id'], 'vid00000002')['selected'] == 0

    client.post(f'/api/jobs/{job["id"]}/select', json={'selected': True, 'scope': 'all'})
    assert db.get_video(con, job['id'], 'vid00000002')['selected'] == 1


def test_download_is_refused_unless_ready_for_review(client, con, job):
    db.add_video(con, job['id'], 'vid00000001', 'u')
    r = client.post(f'/api/jobs/{job["id"]}/download')
    assert r.status_code == 409
    assert r.json()['detail']['phase'] == 'queued'

    db.set_phase(con, job['id'], 'ready_for_review')
    r = client.post(f'/api/jobs/{job["id"]}/download')
    assert r.status_code == 200 and r.json()['queued'] == 1
    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'downloading' and fresh['dl_total'] == 1


def test_download_with_nothing_selected_is_a_400(client, con, job):
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.set_video(con, job['id'], 'vid00000001', selected=0)
    db.set_phase(con, job['id'], 'ready_for_review')
    assert client.post(f'/api/jobs/{job["id"]}/download').status_code == 400


def test_a_failed_download_is_retryable_without_a_whole_new_search(client, con, job):
    """YTDL-16: the download phase ends `done` even with per-video failures, so
    without this the only retry was another Claude spend and another twenty
    minutes of yt-dlp."""
    for vid in ('vid00000001', 'vid00000002'):
        db.add_video(con, job['id'], vid, 'u')
    db.set_video(con, job['id'], 'vid00000001', dl_state='done')
    db.set_video(con, job['id'], 'vid00000002', dl_state='failed',
                 dl_error='yt-dlp said no')
    db.set_phase(con, job['id'], 'done')

    r = client.post(f'/api/jobs/{job["id"]}/download')
    assert r.status_code == 200 and r.json()['queued'] == 1
    assert db.get_job(con, job['id'])['phase'] == 'downloading'
    assert [v['video_id'] for v in db.pending_videos(con, job['id'])] == ['vid00000002']


def test_a_finished_job_with_nothing_left_to_fetch_is_still_a_400(client, con, job):
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.set_video(con, job['id'], 'vid00000001', dl_state='done')
    db.set_phase(con, job['id'], 'done')
    assert client.post(f'/api/jobs/{job["id"]}/download').status_code == 400


def test_download_re_validates_the_destination_project(client, con, job, monkeypatch):
    """YTDL-30: a manifest can sit at review for a week -- long enough for the
    project to be unticked, after which nobody syncs the tree these clips would
    land in."""
    from ytdlweb import projects
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.set_phase(con, job['id'], 'ready_for_review')
    monkeypatch.setattr(projects, 'resolve_project', lambda user, slug: None)
    r = client.post(f'/api/jobs/{job["id"]}/download')
    assert r.status_code == 409
    assert 'no longer a project you sync' in r.json()['detail']['detail']
    assert db.get_job(con, job['id'])['phase'] == 'ready_for_review'


def test_cancel_sets_the_flag_rather_than_killing_anything(client, con, job):
    db.set_phase(con, job['id'], 'searching')
    assert client.post(f'/api/jobs/{job["id"]}/cancel').json()['ok'] is True
    assert db.is_cancelled(con, job['id']) is True


def test_cancelling_a_manifest_ends_the_job_and_unblocks_the_editor(client, con, job):
    """YTDL-1: the flag is only read inside run_job, which the worker never
    enters for ready_for_review -- so this cancel used to change nothing while
    answering {ok:true}, and every later search 409'd forever."""
    db.set_phase(con, job['id'], 'ready_for_review')
    r = client.post(f'/api/jobs/{job["id"]}/cancel')
    assert r.json() == {'ok': True, 'phase': 'cancelled'}
    assert db.get_job(con, job['id'])['phase'] == 'cancelled'
    assert db.active_job(con, USER) is None
    assert client.post('/api/jobs', json={'term': 'a fresh start',
                                          'project_slug': PROJECTS[0][0]}).status_code == 200


def test_cancelling_a_queued_job_ends_it_too(client, con, job):
    """Nothing has claimed it, so there is no phase to ask to stop."""
    assert client.post(f'/api/jobs/{job["id"]}/cancel').json()['phase'] == 'cancelled'
    assert db.get_job(con, job['id'])['phase'] == 'cancelled'


def test_download_clears_a_cancel_the_worker_never_honoured(client, con, job):
    """The side defect of YTDL-1: a leftover flag insta-cancels the run the
    editor is asking for."""
    db.add_video(con, job['id'], 'vid00000001', 'u')
    db.set_phase(con, job['id'], 'ready_for_review')
    db.request_cancel(con, job['id'])
    assert client.post(f'/api/jobs/{job["id"]}/download').status_code == 200
    assert db.is_cancelled(con, job['id']) is False


def test_recent_jobs_are_the_callers_own(client, con, job):
    db.create_job(con, OTHER_USER, 'theirs', 'theirs', '2025-ff4-nuclear', '2025/FF4/Nuclear')
    ids = [j['id'] for j in client.get('/api/jobs?limit=20').json()['jobs']]
    assert ids == [job['id']]


# ----------------------------------------------- pasted links (kind='urls')
# "we should maintain the ability to download specific clips": a second box
# that takes YouTube links and downloads exactly those, through the SAME
# pipeline -- so the refusals below are the same refusals a search gets, plus
# the ones only a URL can earn.

VID = 'dQw4w9WgXcQ'
OTHER_VID = 'aaaaaaaaaaa'


def test_the_url_parser_takes_every_shape_an_editor_pastes():
    """All of these arrive in chat messages and browser address bars. Every one
    yields the same 11-char id, because that id -- not the URL -- is what the
    ledger, the `[id]` in the filename and both halves of the dedupe speak."""
    for text in ('https://www.youtube.com/watch?v=' + VID,
                 f'https://www.youtube.com/watch?v={VID}&t=42s',
                 f'https://youtube.com/watch?v={VID}&list=PL123&index=2',
                 'http://m.youtube.com/watch?v=' + VID,
                 f'https://music.youtube.com/watch?v={VID}&si=abcd',
                 'https://youtu.be/' + VID,
                 f'https://youtu.be/{VID}?si=abcdef',
                 'youtu.be/' + VID,                      # pasted with no scheme
                 'WWW.YouTube.com/watch?v=' + VID,       # and no case
                 'https://www.youtube.com/shorts/' + VID,
                 'https://www.youtube.com/live/' + VID,
                 'https://www.youtube.com/embed/' + VID,
                 'https://www.youtube-nocookie.com/embed/' + VID,
                 f'  <https://www.youtube.com/watch?v={VID}>  ',
                 VID):                                   # the bare id
        assert routes_api.video_id_of(text) == VID, text


def test_the_url_parser_refuses_anything_that_is_not_one_video():
    """A 400 naming the offending line, never a guess. The lookalike hosts are
    the ones that matter: an equality test on the host is what stops
    `youtube.com.evil.net` being read as YouTube."""
    for text in ('', '   ', 'algal reef controversy',
                 'https://vimeo.com/12345678901',
                 'https://www.youtube.com/playlist?list=PL123',
                 'https://www.youtube.com/@creatorsclub',
                 'https://www.youtube.com/results?search_query=reef',
                 f'https://youtube.com.evil.net/watch?v={VID}',
                 f'https://notyoutube.com/watch?v={VID}',
                 f'ftp://youtu.be/{VID}',
                 'javascript:alert(1)', 'file:///etc/passwd',
                 '../../etc/passwd',
                 'https://www.youtube.com/watch?v=short',
                 'https://youtu.be/'):
        assert routes_api.video_id_of(text) is None, text


def test_the_url_list_splits_on_newlines_and_commas_and_collapses_repeats():
    """Two rows for one video would double the counters and race each other
    into the same file."""
    videos, rejects = routes_api.parse_url_list(
        f'https://youtu.be/{VID},  {OTHER_VID}\nhttps://www.youtube.com/watch?v={VID}\nnope')
    assert [v['video_id'] for v in videos] == [VID, OTHER_VID]
    # canonicalised: one URL shape in the database, whatever was pasted
    assert videos[0]['url'] == f'https://www.youtube.com/watch?v={VID}'
    assert rejects == ['nope']


def _urls_job(client, urls=None, **over):
    body = {'urls': urls if urls is not None else 'https://youtu.be/' + VID,
            'project_slug': PROJECTS[0][0]}
    body.update(over)
    return client.post('/api/jobs/urls', json=body)


def test_pasted_links_become_a_job_that_starts_at_the_download_phase(client, con):
    """No search, no claude, no review: the rows the review grid would have
    written are written here, and the job enters the phase machine at `queued`
    like any other -- _phase_start is what routes it to `downloading`."""
    r = _urls_job(client, f'https://youtu.be/{VID}\nhttps://youtu.be/{OTHER_VID}')
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['queued'] == 2 and body['skipped'] == []
    assert body['term_dir'] == 'links'

    job = db.get_job(con, body['job_id'])
    assert job['kind'] == 'urls'
    assert job['phase'] == 'queued'
    assert job['created_by'] == USER
    assert job['term'] == 'links' and job['term_dir'] == 'links'
    assert job['project_label'] == PROJECTS[0][1]
    assert job['dl_total'] == 2

    rows = db.videos(con, job['id'])
    assert [v['video_id'] for v in rows] == [VID, OTHER_VID]
    assert all(v['dl_state'] == 'pending' and v['selected'] for v in rows)
    assert [v['url'] for v in rows] == [f'https://www.youtube.com/watch?v={VID}',
                                        f'https://www.youtube.com/watch?v={OTHER_VID}']


def test_a_url_job_is_the_callers_own_like_any_other(client, con):
    job_id = _urls_job(client).json()['job_id']
    assert client.get(f'/api/jobs/{job_id}',
                      headers=_headers(OTHER_USER)).status_code == 404
    assert [j['id'] for j in client.get('/api/jobs').json()['jobs']] == [job_id]


def test_the_folder_is_the_editors_and_is_made_safe_for_smb(client, con):
    """YTDL-28's device names and the rest: safe_term_dirname is reused, never
    re-implemented, because this folder is created on the NAS and then opened
    over SMB by every Windows editor."""
    job = db.get_job(con, _urls_job(client, folder='con').json()['job_id'])
    assert job['term'] == 'con' and job['term_dir'] == 'con_'

    db.set_phase(con, job['id'], 'cancelled')
    job = db.get_job(con, _urls_job(
        client, folder='reef: the "third" terminal').json()['job_id'])
    assert job['term_dir'] == 'reef the third terminal'


def test_a_blank_folder_falls_back_to_the_links_bucket(client, con):
    job = db.get_job(con, _urls_job(client, folder='   ').json()['job_id'])
    assert job['term_dir'] == routes_api.DEFAULT_URL_FOLDER


def test_a_link_that_is_not_a_youtube_video_is_a_400_that_names_it(client):
    r = _urls_job(client, f'https://youtu.be/{VID}\nhttps://vimeo.com/12345')
    assert r.status_code == 400
    assert 'https://vimeo.com/12345' in r.json()['detail']
    assert _urls_job(client, '   ').status_code == 400


def test_the_url_list_is_capped_like_the_search_term_is(client):
    """YTDL-7's shape one layer under DASH-3's 4 MB body cap: this handler
    splits and regexes the whole string on the request thread, and the worker
    then downloads the result one video at a time from one NAS IP."""
    assert _urls_job(client, 'x' * 4001).status_code == 400
    many = '\n'.join(f'https://youtu.be/{i:011d}' for i in range(51))
    r = _urls_job(client, many)
    assert r.status_code == 400 and '50 is the most' in r.json()['detail']


def test_a_url_job_validates_the_project_and_quality_server_side(client):
    assert _urls_job(client, project_slug='2025-ff4-nuclear').status_code == 400
    assert _urls_job(client, quality='8k').status_code == 400


def test_pasted_links_obey_one_active_job_per_editor_in_both_directions(client):
    """The partial unique index (YTDL-25) does not care which kind of job it
    is, so neither may the handler -- an unhandled IntegrityError here would be
    a 500 in place of the 409 the SPA re-attaches on."""
    search = client.post('/api/jobs', json={'term': 'a', 'project_slug': PROJECTS[0][0]})
    refused = _urls_job(client)
    assert refused.status_code == 409
    assert refused.json()['detail']['job_id'] == search.json()['job_id']

    client.post(f'/api/jobs/{search.json()["job_id"]}/cancel')
    links = _urls_job(client)
    assert links.status_code == 200
    second = client.post('/api/jobs', json={'term': 'b', 'project_slug': PROJECTS[0][0]})
    assert second.status_code == 409
    assert second.json()['detail']['job_id'] == links.json()['job_id']
    assert _urls_job(client).status_code == 409


def test_a_double_clicked_paste_cannot_create_two_active_jobs(client, con, monkeypatch):
    """The same read-then-insert window create_job has, closed the same way:
    the index refuses the loser and the handler turns that into the 409."""
    from ytdlweb import db as dbmod

    real, seen = dbmod.active_job, []

    def blind(c, user):
        seen.append(user)
        return None if len(seen) <= 2 else real(c, user)

    monkeypatch.setattr(dbmod, 'active_job', blind)
    first = _urls_job(client)
    second = _urls_job(client)
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()['detail']['job_id'] == first.json()['job_id']
    assert len(db.recent_jobs(con, USER)) == 1
    # ...and the loser left no orphaned video rows behind
    assert len(db.videos(con, first.json()['job_id'])) == 1


def test_a_link_the_fleet_already_has_is_recorded_skipped_not_queued(client, con):
    """REQ 6 reaches the paste box too. The row is kept and marked, so the
    editor sees WHERE it already is rather than a link that silently did
    nothing."""
    db.ledger_add(con, VID, 't', 'c', '2025-ff4-nuclear', '2025/FF4/Nuclear',
                  'other term', 'Youtube/other term/x.mp4')
    r = _urls_job(client, f'https://youtu.be/{VID}\nhttps://youtu.be/{OTHER_VID}')
    assert r.status_code == 200
    assert r.json()['queued'] == 1
    assert r.json()['skipped'] == [{'video_id': VID,
                                    'duplicate_of': '2025/FF4/Nuclear/other term'}]

    job_id = r.json()['job_id']
    assert db.get_job(con, job_id)['dl_total'] == 1
    dup = db.get_video(con, job_id, VID)
    assert dup['dl_state'] == 'skipped' and dup['duplicate'] == 1 and dup['selected'] == 0
    assert [v['video_id'] for v in db.pending_videos(con, job_id)] == [OTHER_VID]


def test_a_paste_of_nothing_but_duplicates_is_refused_outright(client, con):
    """Creating it would burn the editor's one active job on a job that
    downloads nothing."""
    db.ledger_add(con, VID, 't', 'c', PROJECTS[0][0], PROJECTS[0][1], 'reef',
                  'Youtube/reef/x.mp4')
    r = _urls_job(client, 'https://youtu.be/' + VID)
    assert r.status_code == 409
    assert 'already has' in r.json()['detail']['detail']
    assert r.json()['detail']['duplicates'][0]['duplicate_of'] == \
        f'{PROJECTS[0][1]}/reef'
    assert db.active_job(con, USER) is None


def test_a_url_job_can_be_cancelled_before_the_worker_claims_it(client, con):
    """`queued` has no phase in flight, so cancel_now ends it -- and the editor
    is not locked out of their next job (YTDL-1)."""
    job_id = _urls_job(client).json()['job_id']
    assert client.post(f'/api/jobs/{job_id}/cancel').json()['phase'] == 'cancelled'
    assert db.active_job(con, USER) is None


def test_ui_is_served(client):
    assert '<title>CC SYNC // YOUTUBE</title>' in client.get('/').text
    assert client.get('/app.js').headers['content-type'].startswith('application/javascript')
    assert client.get('/style.css').headers['content-type'].startswith('text/css')
    assert client.get('/favicon.svg').headers['content-type'].startswith('image/svg')
