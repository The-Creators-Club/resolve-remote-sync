"""The rights/ToS attestation, and the identity gate that was YTDL_DEV_USER.

docs/COMMERCIAL_READINESS.md items 2 and 15 (2026-08-17). Two things are being
held to here and they are not the same thing:

  - **no download happens until the editor has said, in a recorded way, that
    they have the right to the material.** Gated in the browser (routes_api),
    on the machine-to-machine path (routes_fleet, see test_local_download.py)
    and in the companion. Refusing is the DEFAULT state of a fresh deployment.
  - **nothing in the environment can turn the identity gate off.**
    `YTDL_DEV_USER` used to make every request on a deployed host arrive as one
    named editor -- their projects, their jobs, their history -- and the only
    thing standing between production and that was a comment.
"""
from tests.conftest import OTHER_USER, USER
from ytdlweb import attestation, config, db, session


def _accept(client, version=None):
    return client.post('/api/attestation',
                       json={'version': version or attestation.TEXT_VERSION})


# ------------------------------------------------------------ the wording

def test_the_notice_is_served_whole_with_the_standing_disclaimers(client):
    body = client.get('/api/attestation').json()
    assert body['version'] == attestation.TEXT_VERSION
    assert body['text'] == attestation.NOTICE_TEXT
    # The three things the notice has to say, in the editor's words.
    assert 'RIGHT TO USE THIS MATERIAL' in body['text']
    assert "YOUTUBE'S TERMS OF SERVICE" in body['text']
    assert 'GRANTS YOU NO RIGHTS' in body['text']
    # ...and the two that stay on the page whether or not it is accepted.
    assert body['copyright_notice'] and body['rate_disclaimer']
    assert 'not guaranteed to succeed' in body['rate_disclaimer']


def test_the_digest_moves_when_the_wording_does(monkeypatch):
    """The version is the contract; the digest is the evidence that the text
    behind a recorded acceptance had not been edited without a version bump."""
    before = attestation.text_sha256()
    monkeypatch.setattr(attestation, 'NOTICE_TEXT',
                        attestation.NOTICE_TEXT + '\nand one more thing')
    assert attestation.text_sha256() != before


# --------------------------------------------------------------- the gate

def test_a_fresh_deployment_refuses_every_download_path(unattested):
    """Nobody has accepted anything -- which is where every deployment starts."""
    client = unattested
    slug = 'the-project'
    for method, path, payload in (
            ('post', '/api/jobs', {'term': 'reef', 'project_slug': slug}),
            ('post', '/api/jobs/urls',
             {'urls': ['https://www.youtube.com/watch?v=aaaaaaaaaaa'],
              'project_slug': slug})):
        r = getattr(client, method)(path, json=payload)
        assert r.status_code == 403, path
        assert r.json()['detail']['reason'] == 'attestation'


def test_accepting_it_opens_the_gate_and_is_recorded(unattested, con):
    client = unattested
    assert client.get('/api/attestation').json()['accepted'] is False
    body = _accept(client).json()
    assert body['accepted'] is True and body['accepted_at']

    row = db.attestation_of(con, USER, attestation.TEXT_VERSION)
    assert row['text_sha256'] == attestation.text_sha256()
    assert row['accepted_at'] == body['accepted_at']
    # ...and the gate is open now
    assert client.get('/api/attestation').json()['accepted'] is True


def test_accepting_twice_keeps_the_first_timestamp(unattested, con):
    """"When did this editor agree to this wording" has one answer; a second
    click is not a new agreement."""
    client = unattested
    first = _accept(client).json()['accepted_at']
    con.execute("UPDATE attestations SET accepted_at='2099-01-01T00:00:00+00:00' "
                'WHERE username=?', (USER,))
    con.commit()
    assert _accept(client).json()['accepted_at'] == '2099-01-01T00:00:00+00:00'
    assert first  # ...and the second POST did not raise on the primary key


def test_one_editors_acceptance_is_not_anothers(unattested, con):
    client = unattested
    _accept(client)
    client.headers.update({'x-ccsync-user': OTHER_USER})
    assert client.get('/api/attestation').json()['accepted'] is False
    assert client.post('/api/jobs', json={'term': 'x', 'project_slug': 'y'}
                       ).status_code == 403


def test_a_re_worded_notice_re_prompts_everybody(unattested, con):
    """Bumping TEXT_VERSION is how counsel's next edit reaches the fleet: the
    old row stays (it is the record of what WAS agreed) and the editor is asked
    again."""
    client = unattested
    _accept(client)
    db.record_attestation(con, USER, '1999-01-01.1', 'old-digest')
    assert client.get('/api/attestation').json()['accepted'] is True

    con.execute('DELETE FROM attestations WHERE version=?',
                (attestation.TEXT_VERSION,))
    con.commit()
    assert client.get('/api/attestation').json()['accepted'] is False
    assert db.attestation_of(con, USER, '1999-01-01.1') is not None


def test_a_stale_page_cannot_accept_wording_it_never_showed(unattested):
    client = unattested
    r = _accept(client, version='1999-01-01.1')
    assert r.status_code == 409
    assert r.json()['detail']['reason'] == 'stale_version'
    assert client.get('/api/attestation').json()['accepted'] is False


def test_a_database_without_the_table_refuses_rather_than_allows(client, con):
    """Fail closed: a migration that has not landed must not open the gate."""
    con.execute('DROP TABLE IF EXISTS attestations')
    con.commit()
    try:
        assert db.attestation_of(con, USER, attestation.TEXT_VERSION) is None
        assert client.post('/api/jobs', json={'term': 'x', 'project_slug': 'y'}
                           ).status_code == 403
    finally:
        db.ensure_schema(con)


# ------------------------------------------------------ YTDL_DEV_USER is gone

def test_no_environment_variable_can_stand_in_for_a_session():
    """COMMERCIAL_READINESS.md item 15. `YTDL_DEV_USER` made every un-gated
    request arrive as one named editor, and it was one export away from doing
    that on a deployed host."""
    assert not hasattr(config, 'DEV_USER')
    src = config.__file__.replace('.pyc', '.py')
    with open(src, encoding='utf-8') as fh:
        body = fh.read()
    # Named only in the comment that explains the removal.
    assert "os.environ.get('YTDL_DEV_USER')" not in body


def test_an_un_gated_request_is_401_whatever_the_environment_says(monkeypatch):
    from fastapi.testclient import TestClient

    from ytdlweb.main import app

    monkeypatch.setenv('YTDL_DEV_USER', 'owen')
    with TestClient(app) as bare:
        assert bare.get('/api/me').status_code == 401


def test_the_test_hook_is_an_in_process_call_and_restores_cleanly():
    """What replaces it: reachable only by code that has already imported this
    package, so no value in any environment can turn the gate off."""
    from fastapi.testclient import TestClient

    from ytdlweb.main import app

    previous = session.set_test_user('someone')
    try:
        with TestClient(app) as bare:
            assert bare.get('/api/me').json() == {'user': 'someone'}
    finally:
        session.set_test_user(previous)
    with TestClient(app) as bare:
        assert bare.get('/api/me').status_code == 401
