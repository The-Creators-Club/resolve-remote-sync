"""The JSON API: identity, the ticked-projects gate, and every refusal.

The refusals are the interesting half. This app writes into the Projects tree,
so "409 because you already have a job" and "400 because that is not a project
you sync" are the actual product, not error handling.
"""
from fastapi.testclient import TestClient

from tests.conftest import OTHER_USER, PROJECTS, USER
from ytdlweb import db
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


def test_cancel_sets_the_flag_rather_than_killing_anything(client, con, job):
    db.set_phase(con, job['id'], 'searching')
    assert client.post(f'/api/jobs/{job["id"]}/cancel').json()['ok'] is True
    assert db.is_cancelled(con, job['id']) is True


def test_recent_jobs_are_the_callers_own(client, con, job):
    db.create_job(con, OTHER_USER, 'theirs', 'theirs', '2025-ff4-nuclear', '2025/FF4/Nuclear')
    ids = [j['id'] for j in client.get('/api/jobs?limit=20').json()['jobs']]
    assert ids == [job['id']]


def test_ui_is_served(client):
    assert '<title>CC SYNC // YOUTUBE</title>' in client.get('/').text
    assert client.get('/app.js').headers['content-type'].startswith('application/javascript')
    assert client.get('/style.css').headers['content-type'].startswith('text/css')
    assert client.get('/favicon.svg').headers['content-type'].startswith('image/svg')
