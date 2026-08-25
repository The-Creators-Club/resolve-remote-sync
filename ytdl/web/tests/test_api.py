"""The JSON API: identity, the ticked-projects gate, and every refusal.

The refusals are the interesting half. This app writes into the Projects tree,
so "409 because you already have a job" and "400 because that is not a project
you sync" are the actual product, not error handling.
"""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import MACHINE, OTHER_PROJECT, OTHER_USER, PROJECTS, USER
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


def test_an_editor_with_two_machines_sees_each_project_once(client):
    """ytdl-web-2 (2026-08-21). A sync plan belongs to a COMPUTER since
    dashboard schema v24, so `selections` holds one row per (editor, machine,
    project) and the v24 migration fanned every pre-existing row out to one per
    machine the editor owns. The picker asks as a PERSON -- no machine in the
    request -- and CLAUDE.md's answer to that is "the union to read", a union
    and not a multiset. Without the grouping every editor with a laptop and a
    desktop saw every project in the dropdown twice.
    """
    import sqlite3

    from ytdlweb import config

    con = sqlite3.connect(config.DASH_DB)
    try:
        for slug, _label, pos in PROJECTS:
            con.execute('INSERT OR IGNORE INTO selections VALUES(?,?,?,?,?,?)',
                        (USER, 'owen-laptop', slug, pos, '2026-08-19', 'seed'))
        con.commit()
        r = client.get('/api/projects').json()
    finally:
        # The dashboard fixture database is session-scoped and shared, so the
        # second machine goes away again with this test.
        con.execute("DELETE FROM selections WHERE machine='owen-laptop'")
        con.commit()
        con.close()

    assert [p['slug'] for p in r['projects']] == [p[0] for p in PROJECTS]


def test_a_base_only_editor_is_offered_every_active_project(client):
    """CR-72 (2026-08-24). A wired machine works directly off the NAS tree and
    the dashboard 409s any tick on a base-only account (CR-28), so 'the
    projects you sync' is the empty set for that editor by construction -- and
    the picker they saw was permanently blank. Base-only means EVERY known
    machine reports mode 'base', with machine_state overriding a stale
    editor_media_project row for the same machine (the dashboard's
    machine_modes precedence)."""
    import sqlite3

    from ytdlweb import config, projects

    con = sqlite3.connect(config.DASH_DB)
    try:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS machine_state (
              editor_username TEXT NOT NULL,
              machine         TEXT NOT NULL,
              mode            TEXT
            );
            CREATE TABLE IF NOT EXISTS editor_media_project (
              editor_username TEXT NOT NULL,
              machine         TEXT NOT NULL,
              mode            TEXT
            );
        """)
        # The wired editor: one machine that once reported 'editor' pre-v22
        # and says 'base' in machine_state now -- machine_state must win.
        con.execute("INSERT INTO editor_media_project VALUES('alex','base-rig','editor')")
        con.execute("INSERT INTO machine_state VALUES('alex','base-rig','base')")
        con.commit()

        r = client.get('/api/projects', headers=_headers('alex')).json()
        assert r['projects_available'] is True
        # Every ACTIVE project, ordered by label; the inactive 2024-old stays out.
        assert [p['slug'] for p in r['projects']] == \
            ['2025-ff4-nuclear', '2026-ff5-energy', '2026-ff5-water']
        # The server-side destination check widens with the picker.
        assert projects.resolve_project('alex', '2025-ff4-nuclear') is not None
        assert projects.resolve_project('alex', '2024-old') is None

        # A person with one wired and one remote machine is NOT base-only:
        # they keep their ticked list (a job started from the remote machine
        # is claimed by that machine's companion).
        con.execute("INSERT INTO machine_state VALUES(?,?,?)", (USER, 'owen-rig', 'base'))
        con.execute("INSERT INTO machine_state VALUES(?,?,?)", (USER, MACHINE, 'editor'))
        con.commit()
        r = client.get('/api/projects').json()
        assert [p['slug'] for p in r['projects']] == [p[0] for p in PROJECTS]
    finally:
        con.execute('DROP TABLE machine_state')
        con.execute('DROP TABLE editor_media_project')
        con.commit()
        con.close()


def test_an_editor_with_no_known_machines_is_not_base_only(client):
    """An account with no machines is unknown, not 'cannot sync' -- the
    fixture database has no machine tables at all here, which is also what an
    older dashboard looks like: both must answer the pre-CR-72 ticked list."""
    r = client.get('/api/projects').json()
    assert [p['slug'] for p in r['projects']] == [p[0] for p in PROJECTS]


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


# ------------------------------------------------------------- shot types
# "just make it a series of check boxes so the user can decide and tweak it"
# (2026-08-11). The selection is per search, validated here and stored on the
# job row, because both Claude calls read it back off that row.

def _job_shots(client, con, **over):
    body = {'term': 'reef', 'project_slug': PROJECTS[0][0]}
    body.update(over)
    r = client.post('/api/jobs', json=body)
    return r, (db.get_job(con, r.json()['job_id']) if r.status_code == 200 else None)


def test_the_ticked_shot_types_are_stored_on_the_job(client, con):
    r, job = _job_shots(client, con, shot_types=['interview', 'aerial'])
    assert r.status_code == 200, r.text
    # normalised: table order, so two clients ticking the same boxes agree
    assert job['shot_types'] == 'aerial,interview'
    assert db.shot_types_of(job) == ('aerial', 'interview')


def test_omitting_the_field_is_the_defaults_and_sending_none_is_no_bias(client, con):
    """A client that predates the checkboxes keeps the behaviour it has always
    had; an editor who unticks everything gets an unbiased search. Those are
    different facts and the API must not collapse them."""
    r, job = _job_shots(client, con)
    assert r.status_code == 200
    assert db.shot_types_of(job) == db.DEFAULT_SHOT_TYPES

    client.post(f'/api/jobs/{job["id"]}/cancel')
    r, job = _job_shots(client, con, shot_types=[])
    assert r.status_code == 200
    assert job['shot_types'] == '' and db.shot_types_of(job) == ()


def test_an_unknown_shot_type_is_refused_rather_than_dropped(client, con):
    """Silently dropping it would run a search under a bias the editor did not
    choose and could not afterwards explain."""
    r = client.post('/api/jobs', json={'term': 'reef', 'project_slug': PROJECTS[0][0],
                                       'shot_types': ['aerial', 'helicopter']})
    assert r.status_code == 400
    assert 'helicopter' in r.json()['detail']
    assert 'aerial' in r.json()['detail']          # ...and what IS accepted
    assert db.active_job(con, USER) is None, 'the refused job was created anyway'


def test_an_absurd_shot_type_list_is_capped(client):
    """YTDL-7's shape: a request body is not a place to do unbounded work."""
    r = client.post('/api/jobs', json={'term': 'reef', 'project_slug': PROJECTS[0][0],
                                       'shot_types': ['aerial'] * 40})
    assert r.status_code == 400
    assert 'only 9' in r.json()['detail']


def test_every_known_key_is_accepted_and_all_of_them_is_legal(client, con):
    """All nine ticked is a degenerate selection, not an invalid one -- the
    prompt builder is where it turns into "no bias"."""
    from ytdlweb import claude_cli
    r, job = _job_shots(client, con, shot_types=list(claude_cli.SHOT_TYPES))
    assert r.status_code == 200, r.text
    assert db.shot_types_of(job) == tuple(claude_cli.SHOT_TYPES)


def test_the_poll_and_recent_views_report_the_selection_as_a_list(client, con):
    """The SPA shows what a job was RUN with, so a week-old manifest is still
    interpretable -- and it is a list, not the stored 'aerial,raw' string."""
    r, job = _job_shots(client, con, shot_types=['aerial', 'raw'])
    poll = client.get(f'/api/jobs/{job["id"]}').json()
    assert poll['job']['shot_types'] == ['aerial', 'raw']
    assert client.get(f'/api/jobs/{job["id"]}/manifest').json()['job']['shot_types'] \
        == ['aerial', 'raw']
    assert client.get('/api/jobs').json()['jobs'][0]['shot_types'] == ['aerial', 'raw']


def test_a_url_job_ignores_a_shot_type_selection_cleanly(client, con):
    """A paste is not searched or filtered, so there is nothing to bias -- and
    the SPA posts one form for both boxes, so an arriving field must be ignored
    rather than turned into a 400 the editor cannot act on."""
    r = client.post('/api/jobs/urls', json={
        'urls': 'https://youtu.be/' + VID, 'project_slug': PROJECTS[0][0],
        'shot_types': ['interview']})
    assert r.status_code == 200, r.text
    job = db.get_job(con, r.json()['job_id'])
    assert job['kind'] == 'urls'
    assert db.shot_types_of(job) == db.DEFAULT_SHOT_TYPES

    # ...including a selection that would be refused on a search job
    db.set_phase(con, job['id'], 'cancelled')
    assert client.post('/api/jobs/urls', json={
        'urls': 'https://youtu.be/' + VID, 'project_slug': PROJECTS[0][0],
        'shot_types': ['helicopter']}).status_code == 200


# ------------------------------------------------------------ search mode
# 2026-08-18: 'visuals' (b-roll to cut under something else) or 'news' (a
# montage made of the reporting). Validated here and stored on the job row,
# because both AI calls read the rubric back off that row -- including after a
# container restart re-runs the job from `queued`.


def test_the_search_mode_is_stored_on_the_job(client, con):
    r, job = _job_shots(client, con, mode='news')
    assert r.status_code == 200, r.text
    assert job['mode'] == 'news'
    assert db.mode_of(job) == 'news'


def test_omitting_the_mode_is_visuals(client, con):
    """A client that predates the toggle keeps exactly the search it has always
    run: `visuals` composes the old prompts byte for byte."""
    r, job = _job_shots(client, con)
    assert r.status_code == 200
    assert db.mode_of(job) == 'visuals'


def test_an_unknown_mode_is_refused_rather_than_defaulted(client, con):
    """Same rule as an unknown shot type: silently reading it as `visuals`
    would run the search under a rubric the editor did not choose and could not
    afterwards explain."""
    r = client.post('/api/jobs', json={'term': 'reef',
                                       'project_slug': PROJECTS[0][0],
                                       'mode': 'montage'})
    assert r.status_code == 400
    assert 'montage' in r.json()['detail']
    assert 'visuals' in r.json()['detail'] and 'news' in r.json()['detail']
    assert db.active_job(con, USER) is None, 'the refused job was created anyway'


def test_a_news_job_with_no_boxes_takes_the_news_preset(client, con):
    """The preset is what "this client sent no selection" means, per mode. An
    explicit selection still wins in either mode."""
    from ytdlweb import claude_cli

    r, job = _job_shots(client, con, mode='news')
    assert db.shot_types_of(job) == claude_cli.COVERAGE_KEYS

    client.post(f'/api/jobs/{job["id"]}/cancel')
    r, job = _job_shots(client, con, mode='news', shot_types=['aerial'])
    assert r.status_code == 200, r.text
    assert db.shot_types_of(job) == ('aerial',)


def test_the_poll_and_recent_views_report_the_mode(client, con):
    """The SPA labels the running job, the review header and every Recent
    searches row with it, so "why did that search find nothing but talking
    heads" is answerable a week later."""
    r, job = _job_shots(client, con, mode='news')
    assert client.get(f'/api/jobs/{job["id"]}').json()['job']['mode'] == 'news'
    assert client.get(f'/api/jobs/{job["id"]}/manifest').json()['job']['mode'] \
        == 'news'
    assert client.get('/api/jobs').json()['jobs'][0]['mode'] == 'news'


def test_a_url_job_ignores_a_mode_cleanly(client, con):
    """A paste is never searched, so there is no rubric to run it under -- and
    the SPA posts one form for both boxes, so the field must be ignored rather
    than turned into a 400 the editor cannot act on."""
    r = client.post('/api/jobs/urls', json={
        'urls': 'https://youtu.be/' + VID, 'project_slug': PROJECTS[0][0],
        'mode': 'news'})
    assert r.status_code == 200, r.text
    job = db.get_job(con, r.json()['job_id'])
    assert job['kind'] == 'urls'
    assert db.mode_of(job) == 'visuals'


# --------------------------------------------------------- the candidate cap
# 2026-08-11: one search expanded to 24 terms -> 336 candidates, and YouTube
# began refusing the NAS's IP outright at 112 metadata calls -- which blocked
# extraction fleet-wide for hours. The editor picks the ceiling now; the API
# validates it against the menu and stores it on the job row, because the
# search phase reads it back off that row after a restart.

def test_the_chosen_candidate_ceiling_is_stored_on_the_job(client, con):
    for cap in (50, 100, 200, 400):
        r, job = _job_shots(client, con, max_candidates=cap)
        assert r.status_code == 200, r.text
        assert job['max_candidates'] == cap
        assert db.max_candidates_of(job) == cap
        client.post(f'/api/jobs/{job["id"]}/cancel')


def test_omitting_the_ceiling_is_the_default_not_an_unbounded_search(client, con):
    """A client that predates the dropdown gets the SAFE number, not the
    behaviour it used to have -- that behaviour is the incident."""
    r, job = _job_shots(client, con)
    assert r.status_code == 200
    assert job['max_candidates'] == 100
    from ytdlweb import config
    assert config.DEFAULT_MAX_CANDIDATES == 100


def test_a_ceiling_that_is_not_on_the_menu_is_refused_rather_than_clamped(
        client, con):
    """The set is a menu the SPA renders, not a range. Clamping 5000 to 400
    would tell an editor their thin-topic search covered everything it could
    when it did not; clamping 3 to 50 would spend metadata calls nobody asked
    for -- and calls are the whole subject."""
    for bad in (150, 0, -1, 5000, 99):
        r = client.post('/api/jobs', json={'term': 'reef',
                                           'project_slug': PROJECTS[0][0],
                                           'max_candidates': bad})
        assert r.status_code == 400, bad
        assert '50, 100, 200, 400' in r.json()['detail']
        assert db.active_job(con, USER) is None, 'the refused job was created anyway'


def test_the_poll_and_recent_views_report_the_ceiling(client, con):
    """The SPA shows what a job was RUN with, so "why did that search find so
    much more than this one" is answerable off a week-old manifest."""
    r, job = _job_shots(client, con, max_candidates=200)
    assert client.get(f'/api/jobs/{job["id"]}').json()['job']['max_candidates'] == 200
    assert client.get(f'/api/jobs/{job["id"]}/manifest').json()['job']['max_candidates'] \
        == 200
    assert client.get('/api/jobs').json()['jobs'][0]['max_candidates'] == 200


def test_a_url_job_ignores_a_candidate_ceiling_cleanly(client, con):
    """A paste does no searching, so there is nothing to accumulate against --
    and the SPA posts one form for both boxes, so an arriving field must be
    ignored rather than turned into a 400 the editor cannot act on."""
    r = client.post('/api/jobs/urls', json={
        'urls': 'https://youtu.be/' + VID, 'project_slug': PROJECTS[0][0],
        'max_candidates': 400})
    assert r.status_code == 200, r.text
    job = db.get_job(con, r.json()['job_id'])
    assert job['kind'] == 'urls'
    assert job['max_candidates'] == 100      # the column default, unused

    # ...including one that would be refused on a search job
    db.set_phase(con, job['id'], 'cancelled')
    assert client.post('/api/jobs/urls', json={
        'urls': 'https://youtu.be/' + VID, 'project_slug': PROJECTS[0][0],
        'max_candidates': 9999}).status_code == 200


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
                 'https://www.youtube.com/@somechannel',
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
    assert body['folder'] == 'Youtube' and body['term_dir'] == ''

    job = db.get_job(con, body['job_id'])
    assert job['kind'] == 'urls'
    assert job['phase'] == 'queued'
    assert job['created_by'] == USER
    # nothing was searched for and there is no subfolder: the clips go into the
    # project's Youtube root itself
    assert job['term'] == '' and job['term_dir'] == ''
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


def test_a_paste_lands_in_the_projects_youtube_root_with_no_subfolder(client, con):
    """Owner, 2026-08-11: "individual downloads should just go into the /youtube
    root for the project folder actually, I realised the problem with there
    being no term to sort the clips into subfolders". A search has a topic to
    name a folder after; a paste has nothing but the links, so both columns are
    EMPTY -- `term` because nothing was searched for, `term_dir` because there
    is no subfolder -- and the download phase reads that as the Youtube root."""
    r = client.post('/api/jobs/urls', json={'urls': 'https://youtu.be/' + VID,
                                            'project_slug': PROJECTS[0][0]})
    assert r.status_code == 200, r.text
    assert r.json()['term_dir'] == routes_api.URL_JOB_TERM_DIR == ''
    # ...and something a human can read, which a '' would not be
    assert r.json()['folder'] == 'Youtube'
    job = db.get_job(con, r.json()['job_id'])
    assert job['term'] == '' and job['term_dir'] == ''


def test_a_folder_from_an_older_client_is_accepted_and_ignored(client, con):
    """The field outlived its input box on purpose: a browser holding the
    previous app.js in cache still posts one, and a 400 there would be a paste
    that mysteriously fails while the search beside it works. It no longer
    NAMES anything, though -- there are no subfolders under Youtube/ for a
    paste to land in any more."""
    for folder in ('reef links', 'con', 'reef: the "third" terminal', '   '):
        r = _urls_job(client, folder=folder)
        assert r.status_code == 200, r.text
        job = db.get_job(con, r.json()['job_id'])
        assert job['term'] == '' and job['term_dir'] == '', folder
        db.set_phase(con, job['id'], 'cancelled')


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


# ------------------------------------------------------- the active job
# The SPA asks this on load, because a `#job=` hash can name a finished job
# while the editor's ACTIVE one -- which is what blocks every new search with a
# 409 -- sits unshown (found live, 2026-08-11).

def test_the_active_job_route_answers_the_callers_one_live_job(client, con, job):
    r = client.get('/api/jobs/active')
    assert r.status_code == 200
    assert r.json()['job']['id'] == job['id']
    # ...including at ready_for_review, which is the case that hurts: it is
    # active (it holds the 409) and it is waiting for the editor to look at it
    db.set_phase(con, job['id'], 'ready_for_review')
    assert client.get('/api/jobs/active').json()['job']['phase'] == 'ready_for_review'


def test_the_active_job_route_is_null_when_nothing_is_running(client, con, job):
    db.set_phase(con, job['id'], 'done')
    assert client.get('/api/jobs/active').json() == {'job': None}


def test_the_active_job_route_is_per_editor(client, con, job):
    """Another editor's running job is not this editor's business, and it is
    not what this page should attach to either."""
    assert client.get('/api/jobs/active',
                      headers=_headers(OTHER_USER)).json()['job'] is None


def test_the_active_job_route_is_not_shadowed_by_the_job_id_route(client, con):
    """/api/jobs/{job_id} takes an INT, so 'active' reaching it first is a 422
    rather than a fall-through -- the route order in routes_api is the fix and
    this is what would catch it being shuffled."""
    assert client.get('/api/jobs/active').status_code == 200


# --------------------------------------------------- the download history
# The permanent ledger, read back. FLEET-WIDE on purpose: it is the
# cross-project dedupe record, every editor already sees everyone's rows through
# the ALREADY IN badge, and a row is upserted on video_id -- so a per-caller
# filter would silently drop clips out of an editor's own history the moment
# somebody else re-downloaded one.

def _ledger(con, video_id, when, user=USER, project=None, term='reef'):
    slug, label = project or (PROJECTS[0][0], PROJECTS[0][1])
    db.ledger_add(con, video_id, f'{video_id} title', 'Test Channel', slug,
                  label, term, f'Youtube/{term}/Channel - t [{video_id}].mp4',
                  downloaded_by=user)
    # ledger_add stamps now(), and a batch of forty clips shares a second --
    # the ordering has to be set explicitly to be tested at all.
    con.execute('UPDATE downloads SET downloaded_at=? WHERE video_id=?',
                (when, video_id))
    con.commit()


def test_the_history_is_the_ledger_newest_first(client, con):
    _ledger(con, 'vid00000001', '2026-08-09T10:00:00+00:00')
    _ledger(con, 'vid00000002', '2026-08-11T10:00:00+00:00')
    _ledger(con, 'vid00000003', '2026-08-10T10:00:00+00:00')
    r = client.get('/api/downloads').json()
    assert [d['video_id'] for d in r['downloads']] == \
        ['vid00000002', 'vid00000003', 'vid00000001']
    assert r['total'] == 3 and r['has_more'] is False
    assert r['offset'] == 0 and r['limit'] == db.HISTORY_PAGE


def test_a_history_row_carries_what_the_panel_draws(client, con):
    """Thumbnail (the id is enough -- ytimg's fallback needs nothing else),
    title, where it went, when, and the path the companion is handed to open
    the folder."""
    _ledger(con, 'vid00000001', '2026-08-11T10:00:00+00:00', term='algal reef')
    d = client.get('/api/downloads').json()['downloads'][0]
    assert d['video_id'] == 'vid00000001'
    assert d['title'] == 'vid00000001 title' and d['channel'] == 'Test Channel'
    assert d['project_label'] == PROJECTS[0][1] and d['folder'] == 'algal reef'
    assert d['downloaded_by'] == USER
    assert d['downloaded_at'] == '2026-08-11T10:00:00+00:00'
    # relative to the PROJECTS ROOT, never absolute: the page is served from the
    # NAS and only the companion knows where that tree is on this machine
    assert d['reveal_path'] == \
        f'{PROJECTS[0][1]}/Youtube/algal reef/Channel - t [vid00000001].mp4'
    assert not d['reveal_path'].startswith('/')


def test_the_history_shows_the_whole_fleets_downloads_and_says_whose(client, con):
    """The ledger is the CROSS-PROJECT dedupe record: the ALREADY IN badge
    already tells this editor where a colleague's clip landed, so a history
    that hid it would contradict a badge on the same page -- and an upsert on
    video_id would silently move rows out of a per-caller view."""
    _ledger(con, 'vid00000001', '2026-08-11T10:00:00+00:00', user=USER)
    _ledger(con, 'vid00000002', '2026-08-11T11:00:00+00:00', user=OTHER_USER,
            project=OTHER_PROJECT)
    rows = client.get('/api/downloads').json()['downloads']
    assert [d['video_id'] for d in rows] == ['vid00000002', 'vid00000001']
    assert [d['downloaded_by'] for d in rows] == [OTHER_USER, USER]
    # ...and the other editor sees exactly the same two
    theirs = client.get('/api/downloads', headers=_headers(OTHER_USER)).json()
    assert [d['video_id'] for d in theirs['downloads']] == \
        ['vid00000002', 'vid00000001']


def test_the_history_is_paged_and_never_dumps_the_whole_ledger(client, con):
    for i in range(5):
        _ledger(con, f'vid0000000{i}', f'2026-08-1{i}T10:00:00+00:00')
    first = client.get('/api/downloads?limit=2').json()
    assert [d['video_id'] for d in first['downloads']] == ['vid00000004', 'vid00000003']
    assert first['has_more'] is True and first['total'] == 5

    second = client.get('/api/downloads?limit=2&offset=2').json()
    assert [d['video_id'] for d in second['downloads']] == ['vid00000002', 'vid00000001']
    assert second['has_more'] is True and second['offset'] == 2

    last = client.get('/api/downloads?limit=2&offset=4').json()
    assert [d['video_id'] for d in last['downloads']] == ['vid00000000']
    assert last['has_more'] is False

    past_the_end = client.get('/api/downloads?limit=2&offset=99').json()
    assert past_the_end['downloads'] == [] and past_the_end['has_more'] is False


def test_the_history_limit_is_capped_rather_than_trusted(client, con):
    """A permanent table and a limit off the query string: the cap is the
    difference between a page and "select everything the fleet has ever
    downloaded", on the dashboard's single uvicorn worker."""
    _ledger(con, 'vid00000001', '2026-08-11T10:00:00+00:00')
    r = client.get('/api/downloads?limit=100000').json()
    assert r['limit'] == db.MAX_HISTORY_LIMIT == 100
    for junk in ('?limit=0', '?limit=-5', '?offset=-1'):
        assert client.get('/api/downloads' + junk).status_code == 200


def test_the_history_needs_a_signed_in_caller(con):
    """Fleet-wide is not public: the dashboard's gate injects the header, and a
    request without one is refused like every other route here."""
    with TestClient(app) as c:
        assert c.get('/api/downloads').status_code == 401
        assert c.get('/api/jobs/active').status_code == 401


def test_ui_is_served(client):
    assert '<title>CC SYNC // YOUTUBE</title>' in client.get('/').text
    assert client.get('/app.js').headers['content-type'].startswith('application/javascript')
    assert client.get('/style.css').headers['content-type'].startswith('text/css')
    assert client.get('/favicon.svg').headers['content-type'].startswith('image/svg')


# ------------------------------------------------ the term scope + dates
# 2026-08-25: which languages the search runs in ('both' | 'en' | 'zh' |
# 'exact'), and an upload-date range. Both are validated here and stored on the
# job row, because the worker reads them back off that row -- including after
# a container restart re-runs the job from `queued`.


def test_the_term_scope_is_stored_on_the_job(client, con):
    r, job = _job_shots(client, con, term_scope='zh')
    assert r.status_code == 200, r.text
    assert job['term_scope'] == 'zh'
    assert db.term_scope_of(job) == 'zh'


def test_omitting_the_scope_is_both(client, con):
    """A client that predates the toggle keeps exactly the search it has
    always run."""
    r, job = _job_shots(client, con)
    assert r.status_code == 200
    assert db.term_scope_of(job) == 'both'
    assert db.date_range_of(job) == (None, None)


def test_an_unknown_scope_is_refused_rather_than_defaulted(client, con):
    r = client.post('/api/jobs', json={'term': 'reef',
                                       'project_slug': PROJECTS[0][0],
                                       'term_scope': 'english'})
    assert r.status_code == 400
    assert 'english' in r.json()['detail']
    for known in ('both', 'en', 'zh', 'exact'):
        assert known in r.json()['detail']
    assert db.active_job(con, USER) is None, 'the refused job was created anyway'


def test_the_date_range_is_stored_as_yyyymmdd(client, con):
    """ISO in (what <input type=date> emits), yt-dlp's shape out, so the
    worker compares it to upload_date as a string."""
    r, job = _job_shots(client, con, date_from='2019-01-01', date_to='2019-12-31')
    assert r.status_code == 200, r.text
    assert (job['date_from'], job['date_to']) == ('20190101', '20191231')
    assert db.date_range_of(job) == ('20190101', '20191231')
    # ...and the poll reports it, so the SPA can label the job
    j = client.get(f'/api/jobs/{job["id"]}').json()['job']
    assert (j['date_from'], j['date_to']) == ('20190101', '20191231')
    assert j['term_scope'] == 'both'


def test_one_sided_and_empty_dates_are_fine(client, con):
    r, job = _job_shots(client, con, date_from='20200229', date_to='')
    assert r.status_code == 200, r.text
    assert db.date_range_of(job) == ('20200229', None)


@pytest.mark.parametrize('bad', ['2026-02-30', 'yesterday', '2026/01/01', '202601'])
def test_a_malformed_date_is_refused(client, con, bad):
    r = client.post('/api/jobs', json={'term': 'reef',
                                       'project_slug': PROJECTS[0][0],
                                       'date_to': bad})
    assert r.status_code == 400, r.text
    assert bad in r.json()['detail'] and 'date_to' in r.json()['detail']
    assert db.active_job(con, USER) is None


def test_a_reversed_range_is_refused(client, con):
    """A range that can match nothing is a mistake, not a search."""
    r = client.post('/api/jobs', json={'term': 'reef',
                                       'project_slug': PROJECTS[0][0],
                                       'date_from': '2020-01-01',
                                       'date_to': '2019-01-01'})
    assert r.status_code == 400
    assert 'reversed' in r.json()['detail']
    assert db.active_job(con, USER) is None


def test_a_url_job_ignores_a_scope_and_dates_cleanly(client, con):
    r = client.post('/api/jobs/urls', json={
        'urls': 'https://youtu.be/aaaaaaaaaaa',
        'project_slug': PROJECTS[0][0],
        'term_scope': 'nonsense', 'date_from': 'nonsense'})
    assert r.status_code == 200, r.text
    job = db.get_job(con, r.json()['job_id'])
    assert db.term_scope_of(job) == 'both'
    assert db.date_range_of(job) == (None, None)
