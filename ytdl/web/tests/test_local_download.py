"""Requester-first downloads, server half (docs/YTDL_LOCAL_DOWNLOAD.md phase 1).

The claim/lease/manifest/status endpoints the companion speaks to, and what the
worker does about a job that is (or was) somebody else's to download.

Two properties are worth more than the rest of this file put together:

  - **with no 0.8.0 companion in the fleet, nothing here fires.** Every job is
    born download_mode='server' and the worker behaves exactly as it did
    before; that is what makes phase 1 safe to deploy on the live dashboard
    (plan §10) and it is why the flag ships off.
  - **a lost holder costs at most one lease.** The laptop closes, the tray
    upgrades mid-job, the companion is killed -- and three minutes later the
    server has the job back and downloads only what is missing (§3, §11).
"""
from pathlib import Path

import pytest

from tests.conftest import PROJECTS, USER
from ytdlweb import config, db, identity, worker, ytdl_common

TOKEN = 'a-fleet-token'
OTHER = 'sam'

# The dashboard's session/identity signing secret. Since H5 (2026-08-17) the
# fleet routes VERIFY X-CCSync-Identity against this, so the shared fleet token
# no longer decides WHOSE job a caller may claim -- see ytdlweb/identity.py.
SECRET = 'a-session-secret'


def _identity_header(user=USER):
    """A genuine identity token for `user`, as the dashboard's /api/v1/verify
    would have minted it."""
    return {'x-ccsync-identity': identity.make_identity_token(SECRET, user)}

# yt-dlp's own YYYY.MM.DD, comfortably newer than the shipped floor. Raised
# from 2026.08.10 when CR-80 raised that floor to 2026.08.19 (2026-08-26): the
# fleet minimum is the one number in this file the product moves under it.
FRESH_YTDLP = '2026.08.20'


@pytest.fixture()
def fleet(client, monkeypatch):
    """The client with a CONFIGURED fleet token, sending it on every call.

    config.REPORT_TOKEN is read from the environment at import (conftest pins it
    empty on purpose), so a test that wants the gate to open says so here.

    ...and the same for DASH_SESSION_SECRET plus a VALID identity token for
    USER, because since H5 both gates have to open (2026-08-17): the token says
    "a fleet machine", the identity token says which editor's. A test that
    wants somebody else's identity overrides the header per call
    (`_identity_header(OTHER)`).
    """
    monkeypatch.setattr(config, 'REPORT_TOKEN', TOKEN)
    monkeypatch.setattr(config, 'SESSION_SECRET', SECRET)
    client.headers.update({'x-ccsync-token': TOKEN, **_identity_header(USER)})
    return client


def _job(con, ids=('aaaaaaaaaaa', 'bbbbbbbbbbb'), quality='1080p'):
    """A job sitting in `downloading` with `ids` queued -- the state the SPA
    dispatches from (plan §2 step 1)."""
    slug, label, _ = PROJECTS[0]
    job_id = db.create_job(con, USER, 'reef', 'reef', slug, label, quality=quality)
    for vid in ids:
        db.add_video(con, job_id, vid, f'https://www.youtube.com/watch?v={vid}',
                     f'{vid} title')
    con.commit()
    db.mark_pending(con, job_id)
    db.set_job(con, job_id, dl_total=len(ids))
    db.set_phase(con, job_id, 'downloading')
    return db.get_job(con, job_id)


def _claim_body(editor=USER, **over):
    """What companion 0.8.0 sends. The naming halves and the scope are declared
    together because the server answers all three before it grants a lease."""
    body = {'editor': editor, 'ytdlp_version': FRESH_YTDLP,
            'template_version': ytdl_common.TEMPLATE_VERSION,
            'sidecar_version': ytdl_common.SIDECAR_VERSION,
            'scope_qualities': ['480p', '720p', '1080p'],
            'free_bytes': 500 * 1024 ** 3}
    body.update(over)
    return body


def _expire_lease(con, job_id):
    """Wind the lease back to a time that has passed -- the laptop-closed case,
    without waiting three minutes for it."""
    con.execute("UPDATE jobs SET lease_expires_at='2020-01-01T00:00:00+00:00' "
                'WHERE id=?', (job_id,))
    con.commit()


# ------------------------------------------------------------- the token gate

def test_the_fleet_endpoints_fail_closed_with_no_token_configured(client, con):
    """An unconfigured DASH_REPORT_TOKEN means 403 to everything, INCLUDING a
    caller presenting a token -- there is nothing to match it against, and
    "no secret configured" must never mean "no secret required".

    These endpoints hand a machine on the internet a list of URLs to fetch and
    a folder in the canonical tree to write them into; b-roll's ingest gate is
    allowed a dev mode, this one is not."""
    job = _job(con)
    for path, payload in (
            (f'/api/jobs/{job["id"]}/claim', _claim_body()),
            (f'/api/jobs/{job["id"]}/heartbeat', {'editor': USER}),
            (f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status', {'state': 'done'})):
        r = client.post(path, json=payload, headers={'x-ccsync-token': 'anything'})
        assert r.status_code == 403, path
    assert client.get(f'/api/jobs/{job["id"]}/download-manifest',
                      headers={'x-ccsync-token': 'anything'}).status_code == 403
    # ...and the job is untouched: no lease, no mode change
    assert db.get_job(con, job['id'])['download_mode'] == db.MODE_SERVER


def test_a_wrong_token_is_refused_and_a_right_one_is_not(fleet, con):
    job = _job(con)
    bad = fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body(),
                     headers={'x-ccsync-token': TOKEN + 'x'})
    assert bad.status_code == 403
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body()).status_code == 200


def test_the_client_config_needs_no_token_at_all(con):
    """A companion reads it BEFORE it has anything to claim, and it is how the
    fleet is forced onto a newer yt-dlp the day YouTube breaks the old one."""
    from fastapi.testclient import TestClient

    from ytdlweb.main import app
    with TestClient(app) as bare:
        r = bare.get('/api/config/ytdl-client')
    assert r.status_code == 200
    body = r.json()
    assert body['min_ytdlp_version'] == config.MIN_YTDLP_VERSION
    assert body['download_pause_seconds'] == config.DOWNLOAD_PAUSE
    assert body['template_version'] == ytdl_common.TEMPLATE_VERSION


# ------------------------------------------------------------------- claiming

def test_a_claim_takes_the_lease_and_says_how_to_keep_it(fleet, con):
    job = _job(con)
    r = fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    assert r.status_code == 200
    body = r.json()
    assert body['lease_seconds'] == config.LEASE_SECONDS
    assert body['heartbeat_seconds'] == config.HEARTBEAT_SECONDS
    assert body['download_pause_seconds'] == config.DOWNLOAD_PAUSE

    fresh = db.get_job(con, job['id'])
    assert fresh['download_mode'] == db.MODE_LOCAL
    assert fresh['claimed_by'] == USER
    assert db.lease_active(fresh)


def test_the_same_editor_reclaiming_refreshes_rather_than_conflicts(fleet, con):
    """One companion, restarted (or one editor with two tabs behind one tray),
    is not a second holder -- and a 409 there would strand the job until the
    lease expired for no reason."""
    job = _job(con)
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body()).status_code == 200
    first = db.get_job(con, job['id'])['lease_expires_at']
    _expire_lease(con, job['id'])
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body()).status_code == 200
    assert db.get_job(con, job['id'])['lease_expires_at'] >= first


def test_a_second_editor_gets_409_while_the_lease_is_live(fleet, con):
    """Single holder per job (§3). Two browser tabs, two editors, or one editor
    on two machines all end up here."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    r = fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body(editor=OTHER),
                   headers=_identity_header(OTHER))
    assert r.status_code == 409
    assert r.json()['detail']['claimed_by'] == USER
    assert db.get_job(con, job['id'])['claimed_by'] == USER


def test_a_second_editor_may_claim_once_the_lease_has_run_out(fleet, con):
    """Expiry is what makes a vanished holder recoverable; until the SERVER has
    taken the job back (which locks it), a live companion may pick it up."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    _expire_lease(con, job['id'])
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body(editor=OTHER),
                      headers=_identity_header(OTHER)).status_code == 200
    assert db.get_job(con, job['id'])['claimed_by'] == OTHER


# ------------------------------------- one editor, two computers (data-model-7)
# CR-66/CR-67, 2026-08-21. The lease was keyed on the editor NAME and a name is
# a PERSON, so the desktop's claim and the laptop's claim both passed the CAS
# as the documented refresh: two executors on one job, two trees, and each
# posting terminal statuses for the other's clips. The key is now
# (editor, machine_id), and that id is the one the companion mints in
# ~/.ccsync/machine.json.

DESKTOP = 'a1b2c3d4e5f60718293a4b5c6d7e8f90'
LAPTOP = '0f1e2d3c4b5a69788796a5b4c3d2e1f0'

# The dashboard's registry (its schema v23), verbatim enough for
# projects.machine_label. Deliberately NOT in conftest's fixture dashboard
# database: an older dashboard has no such table, and the 409 has to be a
# sentence either way.
_MACHINES_DDL = """
CREATE TABLE machines (
  editor_username     TEXT NOT NULL,
  machine             TEXT NOT NULL,
  machine_id          TEXT,
  platform            TEXT,
  syncthing_device_id TEXT,
  first_seen          TEXT NOT NULL,
  last_seen           TEXT NOT NULL,
  PRIMARY KEY (editor_username, machine)
);
"""


@pytest.fixture()
def dash_machines():
    """USER's two computers, registered the way the dashboard registers them.

    Dropped again at the end: the table's ABSENCE is what the test below this
    one asserts against, and a fixture that left it behind would decide that
    test on collection order.
    """
    import sqlite3

    from ytdlweb import config as cfg

    con = sqlite3.connect(cfg.DASH_DB)
    con.executescript(_MACHINES_DDL)
    for name, mid in (('owen-desktop', DESKTOP), ('owen-laptop', LAPTOP)):
        con.execute('INSERT INTO machines(editor_username,machine,machine_id,'
                    'first_seen,last_seen) VALUES(?,?,?,?,?)',
                    (USER, name, mid, '2026-08-21', '2026-08-21'))
    con.commit()
    try:
        yield con
    finally:
        con.execute('DROP TABLE machines')
        con.commit()
        con.close()


def test_the_same_machine_claiming_again_refreshes_and_is_recorded(fleet, con):
    """The documented refresh, now per COMPUTER: one companion restarting is
    not a second holder, and a 409 there would strand the job until the lease
    expired for no reason."""
    job = _job(con)
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body(machine_id=DESKTOP)).status_code == 200
    assert db.claimed_machine_of(db.get_job(con, job['id'])) == DESKTOP

    _expire_lease(con, job['id'])
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body(machine_id=DESKTOP)).status_code == 200
    fresh = db.get_job(con, job['id'])
    assert db.lease_active(fresh)
    assert db.claimed_machine_of(fresh) == DESKTOP


def test_the_same_editors_other_computer_gets_409_not_the_lease(fleet, con):
    """THE defect (data-model-7). Same person, same identity token, a different
    computer: before this it read as a refresh and both machines downloaded the
    same clips."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body(machine_id=DESKTOP))

    r = fleet.post(f'/api/jobs/{job["id"]}/claim',
                   json=_claim_body(machine_id=LAPTOP))
    assert r.status_code == 409
    detail = r.json()['detail']
    assert detail['claimed_by'] == USER
    assert detail['claimed_machine'] == DESKTOP
    # the holder is untouched: a refused claim never moves a live lease
    fresh = db.get_job(con, job['id'])
    assert db.claimed_machine_of(fresh) == DESKTOP
    assert db.lease_active(fresh)


def test_the_409_names_the_computer_the_dashboard_knows(fleet, con, dash_machines):
    """"owen is already downloading this job" reads as a bug to the person
    whose own name that is, so the detail names the machine. Resolved from the
    dashboard's registry, never echoed back out of a request body."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body(machine_id=DESKTOP))
    r = fleet.post(f'/api/jobs/{job["id"]}/claim',
                   json=_claim_body(machine_id=LAPTOP))
    assert r.status_code == 409
    assert r.json()['detail']['detail'] == (
        f'{USER} is already downloading this job on owen-desktop')


def test_an_unnameable_machine_still_makes_a_sentence(fleet, con):
    """No `machines` table (an older dashboard), no row for the id, no
    dashboard database at all: the id is worse than a hostname and better than
    nothing, because it is what the other machine's companion log prints."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body(machine_id=DESKTOP))
    r = fleet.post(f'/api/jobs/{job["id"]}/claim',
                   json=_claim_body(machine_id=LAPTOP))
    assert r.status_code == 409
    assert r.json()['detail']['detail'] == (
        f'{USER} is already downloading this job on machine {DESKTOP}')


def test_a_companion_that_sends_no_machine_id_behaves_exactly_as_before(fleet, con):
    """What lets the server half ship before the companion half: a body with no
    machine_id is answered per EDITOR, which is the pre-2026-08-21 rule."""
    job = _job(con)
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body()).status_code == 200
    assert db.claimed_machine_of(db.get_job(con, job['id'])) is None
    # the same editor, still not saying which machine: a refresh, as before
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body()).status_code == 200
    # ...and another editor is still refused, machine ids or no machine ids
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body(editor=OTHER),
                      headers=_identity_header(OTHER)).status_code == 409


def test_an_upgraded_companion_may_still_refresh_a_lease_it_took_before(fleet, con):
    """A NULL claimed_machine is "the holder did not say", not "another
    machine". Refusing it would strand a job the moment the companion holding
    it upgraded mid-download, which is a lease this feature exists to survive
    (plan 11)."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    assert db.claimed_machine_of(db.get_job(con, job['id'])) is None
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body(machine_id=DESKTOP)).status_code == 200
    assert db.claimed_machine_of(db.get_job(con, job['id'])) == DESKTOP


def test_a_reclaim_forgets_which_computer_held_it(fleet, con):
    """claimed_by and claimed_machine are one fact: an id left behind on a job
    the server has taken back would name a holder that no longer exists, and
    the next claim would compare itself against it."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body(machine_id=DESKTOP))
    db.reclaim_download(con, job['id'])
    fresh = db.get_job(con, job['id'])
    assert fresh['claimed_by'] is None
    assert db.claimed_machine_of(fresh) is None


def test_the_hand_back_keeps_the_record_of_which_computer_fetched_them(fleet, con):
    """end_lease is the ORDERLY close-out, and there `claimed_by` deliberately
    stays as the record of who fetched the clips. Which computer fetched them
    is the same kind of record, and worth as much when the question is "whose
    disk are these on"."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body(machine_id=DESKTOP))
    db.end_lease(con, job['id'], USER)
    fresh = db.get_job(con, job['id'])
    assert fresh['claimed_by'] == USER
    assert db.claimed_machine_of(fresh) == DESKTOP
    assert not db.lease_active(fresh)


@pytest.mark.parametrize('version', ['2026.01.01', '', '2025.12.31'])
def test_a_stale_yt_dlp_is_refused_with_the_number_it_needs(fleet, con, version):
    """yt-dlp rots (plan §6). A companion whose binary is older than the fleet
    minimum downloads nothing -- it falls back to the server and self-updates
    for next time, which is why the answer carries the number."""
    job = _job(con)
    r = fleet.post(f'/api/jobs/{job["id"]}/claim',
                   json=_claim_body(ytdlp_version=version))
    assert r.status_code == 403
    assert r.json()['detail']['min_ytdlp_version'] == config.MIN_YTDLP_VERSION
    assert db.get_job(con, job['id'])['download_mode'] == db.MODE_SERVER


@pytest.mark.parametrize('floor,reported,ok', [
    # the case that killed it: an operator's unpadded floor sorts ABOVE every
    # real release as a string, so every claim in the fleet 403'd while every
    # companion (ranking numerically) saw nothing to update
    ('2026.8.4', '2026.08.10', True),
    ('2026.8.4', '2026.08.04', True),
    ('2026.8.4', '2026.08.03', False),
    ('2026.08.04', '2026.8.4', True),
    ('2026.08.04', '2026.8.3', False),
    # yt-dlp's own zero-padded output, which the string rule got right and this
    # one must not get wrong
    ('2026.07.04', '2026.07.04', True),
    ('2026.07.04', '2026.12.01', True),
    ('2026.07.04', '2026.06.30', False),
    # a nightly ranks after the release it follows (longer tuple, equal prefix)
    ('2026.07.04', '2026.07.04.123456', True),
    ('2026.07.04.123456', '2026.07.04', False),
    # an unrankable REPORTED version is stale: a companion that cannot say what
    # it is running does not get to download for the fleet
    ('2026.07.04', '', False),
    ('2026.07.04', 'nightly', False),
    ('2026.07.04', '2026.07.04-hotfix', False),
])
def test_the_yt_dlp_floor_is_ranked_numerically(floor, reported, ok):
    """COMP-BROLL-9 (2026-08-14). Lexicographic order is release order for
    yt-dlp's OWN zero-padded output and for nothing else -- and the other
    operand is free text an operator types into YTDL_MIN_YTDLP_VERSION."""
    from ytdlweb.routes_fleet import _version_at_least
    assert _version_at_least(reported, floor) is ok


def test_a_floor_nothing_can_rank_is_refused_at_import_not_enforced(caplog):
    """A floor that cannot be ranked cannot let anybody through, so it turns
    every editor's downloads back to the server and looks exactly like "the
    whole fleet is on old yt-dlp". The bad value is dropped for the shipped
    default, loudly -- and it is the shipped default that is then published to
    the fleet by /api/config/ytdl-client."""
    with caplog.at_level('ERROR'):
        assert config._validated_floor('2026.8.5 ') == '2026.8.5'
        assert not caplog.text
        assert config._validated_floor('latest') == config.DEFAULT_MIN_YTDLP_VERSION
    assert 'YTDL_MIN_YTDLP_VERSION' in caplog.text
    assert config.version_rank(config.MIN_YTDLP_VERSION) is not None, \
        'the floor this deployment is running with cannot be compared to anything'


def test_a_template_skew_declines_to_the_server_rather_than_diverging(fleet, con):
    """§5: server and companion must produce byte-identical artifacts. A
    companion whose vendored ytdl_common is a version behind is refused, and
    the job downloads server-side -- version skew degrades to server execution,
    never to two spellings of one clip in the tree."""
    job = _job(con)
    r = fleet.post(f'/api/jobs/{job["id"]}/claim',
                   json=_claim_body(template_version=ytdl_common.TEMPLATE_VERSION - 1))
    assert r.status_code == 410
    detail = r.json()['detail']
    assert detail['reason'] == 'template_version'
    assert detail['template_version'] == ytdl_common.TEMPLATE_VERSION
    assert db.get_job(con, job['id'])['download_mode'] == db.MODE_SERVER


def test_a_sidecar_skew_declines_to_the_server_just_as_a_template_skew_does(
        fleet, con):
    """COMP-BROLL-6 (2026-08-14): the OTHER half of the §5 handshake. The
    server advertised its sidecar version in the manifest and in the client
    config and compared it nowhere, so a server that grew a ninth credits field
    would have taken 8-field sidecars from every companion in the fleet without
    a word. Two numbers because they fail differently: a template skew puts two
    spellings of one clip in the tree, a sidecar skew puts two shapes of one
    credits file beside them."""
    job = _job(con)
    r = fleet.post(f'/api/jobs/{job["id"]}/claim',
                   json=_claim_body(sidecar_version=ytdl_common.SIDECAR_VERSION + 1))
    assert r.status_code == 410
    detail = r.json()['detail']
    assert detail['reason'] == 'sidecar_version'
    assert detail['sidecar_version'] == ytdl_common.SIDECAR_VERSION
    assert db.get_job(con, job['id'])['download_mode'] == db.MODE_SERVER


def test_a_claim_that_declares_neither_new_field_is_answered_as_before(fleet, con):
    """Both fields are ADDITIVE: a body that carries no sidecar version and no
    scope -- a 0.8.0-dev build, or anything hand-rolled -- is refused on
    nothing it did not say. The template gate is what refuses a companion that
    predates the contract, and it still does."""
    job = _job(con)
    body = _claim_body()
    del body['sidecar_version'], body['scope_qualities']
    assert fleet.post(f'/api/jobs/{job["id"]}/claim', json=body).status_code == 200
    assert db.get_job(con, job['id'])['download_mode'] == db.MODE_LOCAL


def test_a_quality_that_machine_does_not_run_is_refused_before_the_lease(
        fleet, con):
    """COMP-BROLL-10 (2026-08-14): the local executor runs only the rungs it
    can NAME correctly (480p/720p/1080p -- `best`/2160p/1440p/audio need the
    server's transcode, whose `.editready.mp4` name it cannot reproduce). It
    declares that here, so the answer is an immediate 410 instead of a lease
    the companion reads the manifest, declines and then has to let EXPIRE --
    three minutes of the job sitting still, per job, for nothing."""
    job = _job(con, quality='2160p')
    r = fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    assert r.status_code == 410
    detail = r.json()['detail']
    assert detail['reason'] == 'out_of_scope'
    assert detail['quality'] == '2160p'
    assert '2160p' in detail['detail']
    fresh = db.get_job(con, job['id'])
    assert fresh['download_mode'] == db.MODE_SERVER and fresh['claimed_by'] is None
    # ...and a companion that declares no scope is not second-guessed: it is
    # the manifest check on its own side that hands the job back
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body(scope_qualities=[])).status_code == 200


def test_a_job_pinned_to_the_server_cannot_be_claimed(fleet, con):
    job = _job(con)
    db.lock_mode(con, job['id'], db.MODE_SERVER)
    r = fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    assert r.status_code == 410
    assert r.json()['detail']['reason'] == 'mode_lock'


@pytest.mark.parametrize('phase', ['ready_for_review', 'done', 'cancelled'])
def test_a_job_that_is_not_downloading_is_not_claimable(fleet, con, phase):
    job = _job(con)
    db.set_phase(con, job['id'], phase)
    r = fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    assert r.status_code == 410
    assert r.json()['detail']['reason'] == 'phase'


def test_a_claim_needs_a_holder_and_a_job(fleet, con):
    """H5 (2026-08-17) changed the first half of this. A blank `editor` in the
    BODY used to be a 400 "a lease needs a holder"; the body no longer decides
    who the holder is, so a blank one is simply ignored and the verified
    identity is used. What is refused now is a claim with no verifiable
    identity at all -- see the identity-gate tests below."""
    job = _job(con)
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body(editor='  ')).status_code == 200
    assert db.get_job(con, job['id'])['claimed_by'] == USER
    assert fleet.post('/api/jobs/999999/claim',
                      json=_claim_body()).status_code == 404


# ---------------------------------------------------------- the identity gate
# H5 / COMMERCIAL_READINESS.md item 7 (2026-08-17). The shared fleet token is
# held by EVERY companion, so on its own it says "a fleet machine" and nothing
# about which. Before this, the editor name was self-asserted -- so any machine
# holding the token could claim a job as somebody else and then complete it,
# fail its clips, or take it away from the editor who was downloading it.

def test_a_fleet_call_without_a_verified_identity_is_refused(fleet, con):
    job = _job(con)
    for header in ({}, {'x-ccsync-identity': ''}, {'x-ccsync-identity': USER},
                   {'x-ccsync-identity': 'v2.identity.YWxleA.9999999999.deadbeef'}):
        r = fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body(),
                       headers={'x-ccsync-identity': ''} | header)
        assert r.status_code == 403, header
        assert r.json()['detail']['reason'] == 'identity'
    assert db.get_job(con, job['id'])['download_mode'] == db.MODE_SERVER


def test_a_session_cookie_cannot_be_replayed_as_a_machine_identity(fleet, con):
    """The dashboard signs sessions and identities with the same secret and
    tells them apart by a PURPOSE claim (its SEC-1). A browser cookie lifted
    off an editor must not become a fleet identity."""
    job = _job(con)
    session_shaped = identity.make_identity_token(SECRET, USER).replace(
        '.identity.', '.session.', 1)
    r = fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body(),
                   headers={'x-ccsync-identity': session_shaped})
    assert r.status_code == 403


def test_an_expired_identity_token_is_refused(fleet, con):
    job = _job(con)
    stale = identity.make_identity_token(SECRET, USER, ttl=-60)
    assert fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body(),
                      headers={'x-ccsync-identity': stale}).status_code == 403


def test_a_token_signed_with_another_secret_is_refused(fleet, con):
    job = _job(con)
    forged = identity.make_identity_token('not-this-fleets-secret', USER)
    assert fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body(),
                      headers={'x-ccsync-identity': forged}).status_code == 403


def test_the_body_cannot_claim_a_job_for_somebody_else(fleet, con):
    """The whole point of H5: `editor` in the body is ignored, and the lease
    lands on the name the SIGNATURE vouches for."""
    job = _job(con)
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body(editor=OTHER)).status_code == 200
    assert db.get_job(con, job['id'])['claimed_by'] == USER


def test_an_unconfigured_session_secret_fails_closed(client, con, monkeypatch):
    """No secret means no identity can be verified, so every fleet route is a
    403 -- the same posture require_fleet_token takes, and it costs only local
    downloads (the NAS worker downloads everything anyway)."""
    monkeypatch.setattr(config, 'REPORT_TOKEN', TOKEN)
    monkeypatch.setattr(config, 'SESSION_SECRET', '')
    job = _job(con)
    r = client.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body(),
                    headers={'x-ccsync-token': TOKEN,
                             **_identity_header(USER)})
    assert r.status_code == 403
    assert r.json()['detail']['reason'] == 'identity_unconfigured'


# ------------------------------------------------------- the rights gate (H5's
# neighbour: COMMERCIAL_READINESS.md item 2)

def test_a_claim_is_refused_until_that_editor_accepted_the_terms(fleet, con):
    """The companion path is machine-to-machine and has no browser to gate, so
    the attestation is checked HERE too. "The other client checks it" is not a
    check."""
    from ytdlweb import attestation

    con.execute('DELETE FROM attestations')
    con.commit()
    job = _job(con)
    r = fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    assert r.status_code == 403
    assert r.json()['detail']['reason'] == 'attestation'
    assert db.get_job(con, job['id'])['download_mode'] == db.MODE_SERVER

    db.record_attestation(con, USER, attestation.TEXT_VERSION,
                          attestation.text_sha256())
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body()).status_code == 200


def test_an_acceptance_of_an_older_wording_does_not_count(fleet, con):
    con.execute('DELETE FROM attestations')
    db.record_attestation(con, USER, '1999-01-01.1', 'whatever')
    con.commit()
    job = _job(con)
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body()).status_code == 403


# ------------------------------------------------------------------ heartbeat

def test_a_heartbeat_extends_the_lease(fleet, con):
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    _expire_lease(con, job['id'])
    # ...expired leases are NOT extended: by then the worker may already have
    # the job back, and two executors on one job is the thing the lease exists
    # to prevent.
    assert fleet.post(f'/api/jobs/{job["id"]}/heartbeat',
                      json={'editor': USER}).status_code == 410

    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    before = db.get_job(con, job['id'])['lease_expires_at']
    r = fleet.post(f'/api/jobs/{job["id"]}/heartbeat', json={'editor': USER})
    assert r.status_code == 200
    assert r.json()['lease_expires_at'] >= before
    assert db.lease_active(db.get_job(con, job['id']))


def test_a_heartbeat_after_the_server_reclaimed_is_410(fleet, con):
    """Reclaim is ONE-WAY (§3). The companion hears 410 and stops; it does not
    take the job back off the worker that is now downloading it."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    db.reclaim_download(con, job['id'])
    assert fleet.post(f'/api/jobs/{job["id"]}/heartbeat',
                      json={'editor': USER}).status_code == 410
    # ...and it cannot simply claim it again either
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body()).status_code == 410


def test_another_editors_heartbeat_does_not_hold_the_lease_open(fleet, con):
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    assert fleet.post(f'/api/jobs/{job["id"]}/heartbeat',
                      json={'editor': OTHER},
                      headers=_identity_header(OTHER)).status_code == 410


# ------------------------------------------------------------- the work order

def test_the_manifest_is_leaseholder_only(fleet, con):
    job = _job(con)
    url = f'/api/jobs/{job["id"]}/download-manifest'
    assert fleet.get(url).status_code == 410, 'nobody has claimed it'

    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    assert fleet.get(url).status_code == 200
    assert fleet.get(url, headers=_identity_header(OTHER)).status_code == 410

    db.reclaim_download(con, job['id'])
    assert fleet.get(url).status_code == 410


def test_the_manifest_carries_the_work_order_and_no_absolute_path(fleet, con):
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    m = fleet.get(f'/api/jobs/{job["id"]}/download-manifest').json()

    assert m['job_id'] == job['id']
    assert m['quality'] == '1080p'
    assert m['term_dir'] == 'reef'
    assert m['project_label'] == PROJECTS[0][1]
    # Relative to the PROJECTS ROOT, exactly as db.reveal_path speaks to the
    # companion: only the companion knows where that is on its own machine, and
    # the page must never learn a drive letter.
    assert m['project_rel_path'] == f'{PROJECTS[0][1]}/Youtube/reef'
    assert ':' not in m['project_rel_path'] and not m['project_rel_path'].startswith('/')
    assert m['template_version'] == ytdl_common.TEMPLATE_VERSION
    assert m['sidecar_version'] == ytdl_common.SIDECAR_VERSION
    assert m['download_pause_seconds'] == config.DOWNLOAD_PAUSE
    assert [c['video_id'] for c in m['clips']] == ['aaaaaaaaaaa', 'bbbbbbbbbbb']
    assert all(c['url'].endswith(c['video_id']) for c in m['clips'])


def test_the_manifest_lists_only_the_clips_still_owed(fleet, con):
    """The same selection query the worker's download phase reads
    (db.pending_videos), so the two executors cannot disagree about what is
    left -- including on a re-claim after a partial run."""
    job = _job(con, ids=('aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc'))
    db.set_video(con, job['id'], 'aaaaaaaaaaa', dl_state='done')
    db.set_video(con, job['id'], 'ccccccccccc', dl_state='skipped')
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    m = fleet.get(f'/api/jobs/{job["id"]}/download-manifest').json()
    assert [c['video_id'] for c in m['clips']] == ['bbbbbbbbbbb']


def test_the_manifest_re_checks_the_dedupe_the_worker_re_checks(fleet, con,
                                                                project_root):
    """YTDL-WEB-3 (2026-08-14): pending_videos is only HALF of what the worker
    does before it spends bandwidth.

    A manifest can sit at review for a week, and in that week another editor's
    job may have downloaded the same video. _phase_download re-checks both
    halves per clip -- the ledger and the destination folder -- and marks a hit
    `skipped, duplicate_of=...`; the local executor has no dedupe of its own, so
    a manifest that skipped the re-check had it fetch the clip again into a
    second project, and the ledger's UPSERT then MOVED the fleet's record of
    that clip, orphaning the first copy."""
    job = _job(con, ids=('aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc'))
    # the ledger half: another editor's job got it three days ago
    db.ledger_add(con, 'aaaaaaaaaaa', 'a title', 'A Channel', 'other-slug',
                  '2026/FF5/Water', 'wind', 'Youtube/wind/X [aaaaaaaaaaa].mp4')
    # the disk half: a file no row knows about (a restart lost the row, or an
    # editor copied it in by hand)
    outdir = project_root / 'reef'
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / 'Test Channel - b [bbbbbbbbbbb].mp4').write_bytes(b'video')

    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    m = fleet.get(f'/api/jobs/{job["id"]}/download-manifest').json()
    assert [c['video_id'] for c in m['clips']] == ['ccccccccccc']

    # ...and the rows say exactly what the worker's own re-check would have said
    for vid, where in (('aaaaaaaaaaa', '2026/FF5/Water/wind'),
                       ('bbbbbbbbbbb', f'{PROJECTS[0][1]}/reef')):
        v = db.get_video(con, job['id'], vid)
        assert (v['dl_state'], v['duplicate'], v['selected']) == ('skipped', 1, 0)
        assert v['duplicate_of'] == where, vid


def test_a_manifest_with_nothing_left_hands_the_job_straight_back(
        fleet, con, project_root, fake_downloader):
    """Every pending clip turned out to be a duplicate. There is nothing for
    the editor's machine to do and nothing to wait a lease out for, so the job
    is handed back on the spot and the worker closes it off."""
    job = _job(con, ids=('aaaaaaaaaaa',))
    db.ledger_add(con, 'aaaaaaaaaaa', 'a title', 'A Channel', 'other-slug',
                  '2026/FF5/Water', 'wind', 'Youtube/wind/X [aaaaaaaaaaa].mp4')
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    m = fleet.get(f'/api/jobs/{job["id"]}/download-manifest').json()
    assert m['clips'] == []
    assert not db.lease_active(db.get_job(con, job['id']))

    worker.run_job(con, job['id'])
    assert fake_downloader.calls == []
    assert db.get_job(con, job['id'])['phase'] == 'done'


def test_a_claim_landing_inside_the_dedupe_scan_cannot_double_download(
        fleet, con, project_root, monkeypatch):
    """YTDL-WEB-4 (2026-08-14): the row, not the job, is the boundary.

    The worker checked the LEASE at the top of the iteration but did not write
    `downloading` until after the dedupe scan -- for a paste, an rglob of the
    project's whole Youtube tree. A claim landing inside that window was
    invisible to the worker for the rest of the clip, and the clip was still
    `pending`, so the manifest the companion asks for the instant its claim
    lands still listed it. Two yt-dlp processes, one directory, one set of
    `[id]` fragments."""
    job = _job(con, ids=('aaaaaaaaaaa', 'bbbbbbbbbbb'))
    scans, calls, handed_out = [], [], []

    def scan(outdir):
        # the SPA's 1 s probe comes back and the companion claims WHILE the
        # worker is still deciding whether clip 1 is a duplicate -- then asks
        # for its work order, which is the whole of the race
        scans.append(str(outdir))
        if len(scans) == 1:
            assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                              json=_claim_body()).status_code == 200
            m = fleet.get(f'/api/jobs/{job["id"]}/download-manifest').json()
            handed_out.extend(c['video_id'] for c in m['clips'])
        return {}

    def download(url, outdir, quality='best', **_kw):
        vid = url.rsplit('=', 1)[-1]
        calls.append(vid)
        path = Path(outdir) / f'X [{vid}].mp4'
        path.write_bytes(b'v')
        return {'title': 't', 'channel': 'c', 'thumbnail': None,
                'filepath': str(path), 'sidecar': None}

    monkeypatch.setattr(worker.ytsearch, 'existing_id_locations', scan)
    monkeypatch.setattr(worker.downloader, 'download', download)
    worker.run_job(con, job['id'])

    assert calls == ['aaaaaaaaaaa'], 'one clip of overlap, not a whole job'
    assert handed_out == ['bbbbbbbbbbb'], \
        'the manifest handed out the clip the server had in flight'
    # ...and the one the server did finish is `done` from the server, once
    landed = db.get_video(con, job['id'], 'aaaaaaaaaaa')
    assert (landed['dl_state'], landed['download_host']) == ('done',
                                                             db.MODE_SERVER)


# ------------------------------------------------------------ status mirroring

def test_a_status_post_writes_exactly_what_the_worker_writes(fleet, con):
    """The SPA polls the same job row 1500 ms apart in both modes and must not
    be able to tell them apart (§2 step 6) -- same states, same counters, same
    ledger row, same downgrade-note convention. Plus download_host, which is
    the one thing that differs and the one thing history should say."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    url = f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status'

    assert fleet.post(url, json={'state': 'downloading'}).status_code == 200
    v = db.get_video(con, job['id'], 'aaaaaaaaaaa')
    assert (v['dl_state'], v['download_host']) == ('downloading', USER)

    note = ytdl_common.TRUNCATED_NOTE.format(q='1080p', lower='720p')
    r = fleet.post(url, json={
        'state': 'done', 'note': note, 'title': 'A real title',
        'thumbnail': 'https://i.ytimg.com/vi/aaaaaaaaaaa/hq.jpg',
        'filepath_rel': 'Test Channel - A real title [aaaaaaaaaaa].mp4'})
    assert r.status_code == 200

    v = db.get_video(con, job['id'], 'aaaaaaaaaaa')
    assert v['dl_state'] == 'done'
    assert v['title'] == 'A real title'
    assert v['download_host'] == USER
    # dl_error on a DONE row is the downgrade note, not a failure (2026-08-13)
    assert v['dl_error'] == note
    assert db.get_job(con, job['id'])['dl_done'] == 1

    led = db.ledger_get(con, 'aaaaaaaaaaa')
    assert led['rel_path'] == \
        'Youtube/reef/Test Channel - A real title [aaaaaaaaaaa].mp4'
    assert led['project_label'] == PROJECTS[0][1]
    assert led['downloaded_by'] == USER
    # ...and the server-side path is composed here, from the job's own label --
    # never from anything the caller sent
    assert v['filepath'].endswith('Test Channel - A real title [aaaaaaaaaaa].mp4')
    assert str(config.PROJECTS_ROOT) in v['filepath']


def test_a_pasted_link_ledgers_the_uploader_the_downloader_found(fleet, con):
    """YTDL-WEB-8 (2026-08-14): the ledger's channel column, for the one kind
    of job whose rows can never carry it.

    A url job's rows are written from a pasted link with no metadata call
    behind them (db.create_url_job), so yt-dlp is the first thing that learns
    the title and the uploader -- which is exactly what worker.py takes them
    from on the server path. The status post had no `channel` field at all, so
    an identical paste executed locally ledgered a blank uploader and the fleet
    history had a hole in it."""
    slug, label, _ = PROJECTS[0]
    job_id = db.create_url_job(
        con, USER, '', '', slug, label,
        [{'video_id': 'aaaaaaaaaaa',
          'url': 'https://www.youtube.com/watch?v=aaaaaaaaaaa'}])
    db.set_phase(con, job_id, 'downloading')
    assert db.get_video(con, job_id, 'aaaaaaaaaaa')['channel'] is None

    fleet.post(f'/api/jobs/{job_id}/claim', json=_claim_body())
    fleet.post(f'/api/jobs/{job_id}/clips/aaaaaaaaaaa/status',
               json={'state': 'done', 'title': 'A real title',
                     'channel': 'A Real Channel',
                     'filepath_rel': 'A Real Channel - A real title '
                                     '[aaaaaaaaaaa].mp4'})
    led = db.ledger_get(con, 'aaaaaaaaaaa')
    assert (led['title'], led['channel']) == ('A real title', 'A Real Channel')
    # a paste lands in Youtube/ itself, with no term folder to sort it into
    assert led['rel_path'] == \
        'Youtube/A Real Channel - A real title [aaaaaaaaaaa].mp4'


def test_a_status_post_without_a_channel_keeps_the_rows_own(fleet, con):
    """The shipped 0.8.0 companion sends neither title nor channel on a done
    post. A search job's row has both from the enrich phase, and the fallback
    is the same `or` worker.py writes -- so an older companion ledgers exactly
    what the server would have."""
    job = _job(con)
    db.set_video(con, job['id'], 'aaaaaaaaaaa', channel='Enriched Channel')
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    fleet.post(f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status',
               json={'state': 'done', 'filepath_rel': 'X [aaaaaaaaaaa].mp4'})
    led = db.ledger_get(con, 'aaaaaaaaaaa')
    assert (led['channel'], led['title']) == ('Enriched Channel',
                                              'aaaaaaaaaaa title')


def test_a_done_report_with_no_file_is_recorded_as_a_failure(fleet, con):
    """YTDL-15's rule, applied to the other executor: no file means the
    download did not land. A ledger row with an empty rel_path is a permanent
    "the fleet already has this" pointing at nothing, and the ledger never
    cascades -- only hand-editing ytdl.db could undo it."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    r = fleet.post(f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status',
                   json={'state': 'done'})
    assert r.status_code == 200 and r.json()['state'] == 'failed'
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['dl_state'] == 'failed'
    assert db.ledger_get(con, 'aaaaaaaaaaa') is None
    assert db.get_job(con, job['id'])['dl_failed'] == 1


def test_a_done_report_naming_a_directory_is_refused_not_recorded(fleet, con):
    """ytdl-web-3 (bug-hunt-2026-09-03). `filepath_rel` is reduced to its last
    segment, and two segments are not file names at all.

    '..' reached config.safe_join, whose PathTraversalError nothing catches: a
    500 and a traceback in the dashboard log. '.' was the worse half --
    safe_join SKIPS it, so the clip was recorded `done` with `filepath` at the
    TERM DIRECTORY and a ledger row ending in '/.', a permanent "the fleet
    already has this" pointing at a folder. Neither is a download that landed,
    so both are the caller's error to fix (YTDL-15's rule again).
    """
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    url = f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status'

    r = fleet.post(url, json={'state': 'done', 'filepath_rel': '../..'})
    assert r.status_code == 400, 'a traversal-shaped name is a refusal, not a 500'

    r = fleet.post(url, json={'state': 'done', 'filepath_rel': '.'})
    assert r.status_code == 400
    # ...and the ledger is what this protects: nothing was written for either.
    assert db.ledger_get(con, 'aaaaaaaaaaa') is None
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['dl_state'] == 'pending'
    assert db.get_job(con, job['id'])['dl_done'] == 0


def test_a_repeated_done_post_is_counted_once(fleet, con):
    """ytdl-web-3 (2026-08-21). Since CR-31 the companion's FleetClient
    re-sends any call that RAISED for up to 60 s, and a client-side timeout on
    a POST the server already committed is exactly such a failure. The second
    copy used to bump dl_done again, so a 22-clip job showed "23 of 22"."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    url = f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status'
    body = {'state': 'done', 'filepath_rel': 'X [aaaaaaaaaaa].mp4'}

    assert fleet.post(url, json=body).status_code == 200
    again = fleet.post(url, json=body)

    assert again.status_code == 200, 'a duplicate is not an error: the clip landed'
    assert again.json()['duplicate'] is True
    assert again.json()['state'] == 'done'
    assert db.get_job(con, job['id'])['dl_done'] == 1
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['dl_state'] == 'done'


def test_a_repeated_failed_post_does_not_strand_the_failure_counter(fleet, con):
    """The same retry, on the worse half (ytdl-web-3).

    dl_failed counts clips that are failed RIGHT NOW, and the hand-back
    subtracts what requeue_failed put back -- a ROW count. Two bumps for one
    row therefore left the counter permanently at 1, so a job whose server-side
    retry succeeded still reported a failed clip in the SPA and in Recent
    searches, for ever."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    url = f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status'

    assert fleet.post(url, json={'state': 'failed', 'error': 'wifi'}).status_code == 200
    again = fleet.post(url, json={'state': 'failed', 'error': 'wifi'})
    assert again.status_code == 200 and again.json()['duplicate'] is True
    assert db.get_job(con, job['id'])['dl_failed'] == 1

    # ...and the hand-back's -n then lands on zero, as it does for a single post
    fleet.post(f'/api/jobs/{job["id"]}/clips/bbbbbbbbbbb/status',
               json={'state': 'done', 'filepath_rel': 'Y [bbbbbbbbbbb].mp4'})
    fresh = db.get_job(con, job['id'])
    assert fresh['dl_failed'] == 0
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['dl_state'] == 'pending'


def test_a_clip_the_server_already_downloaded_is_not_recounted(fleet, con):
    """The other way a terminal row can be there first: the worker downloaded
    the clip while the companion was still posting about it. Same compare-and-
    set, same answer -- the row keeps the verdict it has."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    db.finish_download(con, job['id'], 'aaaaaaaaaaa', 'done',
                       filepath='/somewhere/on/the/nas.mp4')
    db.bump(con, job['id'], 'dl_done')

    r = fleet.post(f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status',
                   json={'state': 'done', 'filepath_rel': 'X [aaaaaaaaaaa].mp4'})
    assert r.status_code == 200 and r.json()['duplicate'] is True
    assert db.get_job(con, job['id'])['dl_done'] == 1
    assert db.ledger_get(con, 'aaaaaaaaaaa') is None


def test_a_status_post_is_leaseholder_only_and_410s_after_a_reclaim(fleet, con):
    job = _job(con)
    url = f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status'
    assert fleet.post(url, json={'state': 'downloading'}).status_code == 410

    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    assert fleet.post(url, json={'state': 'downloading'},
                      headers=_identity_header(OTHER)).status_code == 410
    db.reclaim_download(con, job['id'])
    assert fleet.post(url, json={'state': 'downloading'}).status_code == 410
    assert fleet.post(f'/api/jobs/{job["id"]}/clips/zzzzzzzzzzz/status',
                      json={'state': 'done'}).status_code == 410


def test_an_unknown_state_is_refused(fleet, con):
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    assert fleet.post(f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status',
                      json={'state': 'finished'}).status_code == 400


# ------------------------------------------------- close-out + second chance

def test_the_last_clip_hands_the_job_back_and_the_worker_finishes_it(
        fleet, con, project_root, fake_downloader):
    """No new finaliser: the lease ends, and the worker runs the same
    _phase_download close-out it runs for every server-side job -- manifest,
    phase `done`. One code path for both executors."""
    job = _job(con, ids=('aaaaaaaaaaa',))
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    fleet.post(f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status',
               json={'state': 'done',
                     'filepath_rel': 'Test Channel - a [aaaaaaaaaaa].mp4'})

    handed_back = db.get_job(con, job['id'])
    assert handed_back['phase'] == 'downloading', 'the worker still owes it a close-out'
    assert not db.lease_active(handed_back)
    assert handed_back['mode_lock'] == db.MODE_SERVER, 'no re-claim, no ping-pong'
    assert handed_back['claimed_by'] == USER, 'who fetched it is still on the row'

    worker.run_job(con, job['id'])
    assert db.get_job(con, job['id'])['phase'] == 'done'
    assert fake_downloader.calls == [], 'nothing was re-downloaded here'
    assert (project_root / 'reef' / 'manifest.json').is_file()


def test_a_clip_that_failed_locally_is_retried_once_on_the_server(
        fleet, con, project_root, fake_downloader):
    """§2 step 7, the second-chance sweep. A bot check on ONE editor's IP is not
    a bot check on the NAS's, so final completeness is the max of both
    executors -- and the retry is once, because the hand-back pins the job to
    the server and the companion cannot drive this again."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    fleet.post(f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status',
               json={'state': 'done',
                     'filepath_rel': 'Test Channel - a [aaaaaaaaaaa].mp4'})
    r = fleet.post(f'/api/jobs/{job["id"]}/clips/bbbbbbbbbbb/status',
                   json={'state': 'failed', 'error': 'confirm you are not a bot'})
    assert r.json()['retrying_on_the_server'] == 1

    queued = db.get_job(con, job['id'])
    assert db.get_video(con, job['id'], 'bbbbbbbbbbb')['dl_state'] == 'pending'
    # the counter tracks what is failed RIGHT NOW, and this one is queued again
    assert (queued['dl_done'], queued['dl_failed']) == (1, 0)

    worker.run_job(con, job['id'])
    assert [c[0] for c in fake_downloader.calls] == ['bbbbbbbbbbb'], \
        'only the failed clip is re-fetched; the editor already has the other'
    done = db.get_job(con, job['id'])
    assert done['phase'] == 'done' and (done['dl_done'], done['dl_failed']) == (2, 0)
    assert db.get_video(con, job['id'], 'bbbbbbbbbbb')['download_host'] == db.MODE_SERVER
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['download_host'] == USER


def test_the_companion_is_told_to_stop_after_the_hand_back(fleet, con):
    job = _job(con, ids=('aaaaaaaaaaa',))
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    fleet.post(f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status',
               json={'state': 'done', 'filepath_rel': 'a [aaaaaaaaaaa].mp4'})
    assert fleet.post(f'/api/jobs/{job["id"]}/heartbeat',
                      json={'editor': USER}).status_code == 410


# ------------------------------------------------------------- the worker side

def test_the_worker_leaves_a_leased_job_alone(fleet, con, project_root,
                                              fake_downloader):
    """Two executors on one job is the thing the lease exists to prevent."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())

    assert db.claim_next_job(con) is None, 'the loop must not even see it'
    worker.run_job(con, job['id'])                 # the API and tests' door
    assert fake_downloader.calls == []
    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'downloading'
    assert {v['dl_state'] for v in db.videos(con, job['id'])} == {'pending'}


def test_a_claim_landing_mid_phase_makes_the_server_stand_down(
        fleet, con, project_root, monkeypatch):
    """NOT an exotic race: once 0.8.0 ships this is the normal order of events.
    start_download nudges the worker in the same millisecond the SPA starts
    probing the loopback, so the server is usually a clip or two in when the
    claim lands. It stops there, mid-phase, and leaves the rest -- still
    `pending`, so still in the manifest the companion is about to ask for."""
    job = _job(con, ids=('aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc'))
    calls = []

    def download(url, outdir, quality='best', **_kw):
        vid = url.rsplit('=', 1)[-1]
        calls.append(vid)
        if len(calls) == 1:                      # the editor's companion claims
            fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
        path = Path(outdir) / f'X [{vid}].mp4'
        path.write_bytes(b'v')
        return {'title': 't', 'channel': 'c', 'thumbnail': None,
                'filepath': str(path), 'sidecar': None}

    monkeypatch.setattr(worker.downloader, 'download', download)
    worker.run_job(con, job['id'])

    assert calls == ['aaaaaaaaaaa'], 'one clip of overlap, not a whole job'
    assert db.get_job(con, job['id'])['phase'] == 'downloading'
    left = {v['video_id']: v['dl_state'] for v in db.videos(con, job['id'])}
    assert left['bbbbbbbbbbb'] == 'pending' and left['ccccccccccc'] == 'pending'
    m = fleet.get(f'/api/jobs/{job["id"]}/download-manifest').json()
    assert [c['video_id'] for c in m['clips']] == ['bbbbbbbbbbb', 'ccccccccccc']


def test_a_leased_job_does_not_queue_the_rest_of_the_fleet_behind_it(fleet, con):
    """The exclusion is in SQL, so the NEXT job is still worked -- and the loop
    idles instead of spinning on a row it will not touch for three minutes."""
    leased = _job(con)
    fleet.post(f'/api/jobs/{leased["id"]}/claim', json=_claim_body())
    slug, label, _ = PROJECTS[0]
    other = db.create_job(con, OTHER, 'wind', 'wind', slug, label)
    assert db.claim_next_job(con)['id'] == other


def test_an_expired_lease_is_reclaimed_and_only_the_missing_clips_fetched(
        con, project_root, fake_downloader, caplog):
    """The laptop closed mid-job (§3, §11). A clip that finished on the editor's
    machine reaches the NAS by lane A with the `[video_id]` in its name, and the
    status post that would have recorded it is exactly what was lost -- so the
    disk, not just the rows, decides what is missing."""
    job = _job(con, ids=('aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc'))
    outdir = project_root / 'reef'
    outdir.mkdir(parents=True, exist_ok=True)
    # landed and synced up, never reported
    (outdir / 'Test Channel - a [aaaaaaaaaaa].mp4').write_bytes(b'video')
    (outdir / 'Test Channel - a [aaaaaaaaaaa].credits.json').write_text('{}',
                                                                       encoding='utf-8')
    # half-downloaded, then the lid closed: litter only, so this one is MISSING
    (outdir / 'Test Channel - b [bbbbbbbbbbb].f137.mp4.part').write_bytes(b'x')
    # a previous attempt's disowned corpse is not a clip either (YTDL-3)
    (outdir / 'Test Channel - c [ccccccccccc].mp4.failed').write_bytes(b'x')

    db.claim_download(con, job['id'], USER, config.LEASE_SECONDS)
    db.set_video(con, job['id'], 'bbbbbbbbbbb', dl_state='downloading',
                 download_host=USER)
    db.set_video(con, job['id'], 'ccccccccccc', dl_state='failed',
                 dl_error='wifi died', download_host=USER)
    db.bump(con, job['id'], 'dl_failed')
    _expire_lease(con, job['id'])

    worker.run_job(con, job['id'])

    assert sorted(c[0] for c in fake_downloader.calls) == ['bbbbbbbbbbb',
                                                           'ccccccccccc']
    fresh = db.get_job(con, job['id'])
    assert fresh['download_mode'] == db.MODE_SERVER      # the badge flips (§9)
    assert fresh['claimed_by'] is None
    assert fresh['mode_lock'] == db.MODE_SERVER          # one-way (§3)
    assert fresh['phase'] == 'done'
    assert (fresh['dl_done'], fresh['dl_failed']) == (3, 0)

    # the clip that was already there is DONE and LEDGERED -- a `skipped` row
    # would leave the fleet's dedupe blind to a video it actually has
    landed = db.get_video(con, job['id'], 'aaaaaaaaaaa')
    assert landed['dl_state'] == 'done' and landed['download_host'] == USER
    assert db.ledger_get(con, 'aaaaaaaaaaa')['rel_path'] == \
        'Youtube/reef/Test Channel - a [aaaaaaaaaaa].mp4'
    assert 'expired' in caplog.text


def test_a_sidecar_or_a_corpse_is_never_mistaken_for_the_clip(con, project_root):
    """The reclaim's "is it already here" test is the disk-scan dedupe's
    anchoring rule (YTDL-2/YTDL-27): the id has to be the LAST thing in the
    stem, so `[id].credits.json`, `[id].f137.mp4.part` and `[id].mp4.failed`
    are all not-the-clip."""
    outdir = project_root / 'reef'
    outdir.mkdir(parents=True, exist_ok=True)
    for name in ('X [aaaaaaaaaaa].credits.json', 'X [aaaaaaaaaaa].f137.mp4.part',
                 'X [aaaaaaaaaaa].mp4.failed', 'X [aaaaaaaaaaa].part-Frag7',
                 'X [aaaaaaaaaaa].editready.mp4'):
        (outdir / name).write_bytes(b'x')
    assert worker._landed_file(outdir, 'aaaaaaaaaaa') is None

    (outdir / 'X [aaaaaaaaaaa].mp4').write_bytes(b'x')
    assert worker._landed_file(outdir, 'aaaaaaaaaaa') == 'X [aaaaaaaaaaa].mp4'


# ------------------------------------------------------------- the mode lock

def test_an_editor_can_pin_their_job_to_the_server(client, con):
    """Plan §9's per-job escape hatch, on the BROWSER's session -- no fleet
    token, because this is a human deciding about their own job."""
    job = _job(con)
    r = client.post(f'/api/jobs/{job["id"]}/mode-lock', json={'mode': 'server'})
    assert r.status_code == 200 and r.json()['mode_lock'] == db.MODE_SERVER
    assert db.get_job(con, job['id'])['mode_lock'] == db.MODE_SERVER
    assert client.post(f'/api/jobs/{job["id"]}/mode-lock',
                       json={'mode': 'local'}).status_code == 400


def test_locking_a_running_download_actually_ends_it(fleet, con, project_root,
                                                     fake_downloader):
    """YTDL-WEB-2 (2026-08-14): the lock ends the lease it is clicked on.

    The link is offered by the SPA only while the badge says "downloading on
    your machine" -- i.e. only once a claim has landed -- so a lock that waited
    for the NEXT claim was inert in the only state an editor could ask for it,
    and the toast's promise ("it picks up whatever your machine has not
    finished") could not happen: the companion heartbeats every 30 s and the
    lease never expired while it lived. The editor on hotel wifi watched all 86
    clips carry on regardless."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    fleet.post(f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status',
               json={'state': 'done',
                     'filepath_rel': 'Test Channel - a [aaaaaaaaaaa].mp4'})

    r = fleet.post(f'/api/jobs/{job["id"]}/mode-lock', json={'mode': 'server'})
    assert r.status_code == 200 and r.json()['lease_active'] is False

    # the companion is told to stop at its next call, whichever it makes first
    assert fleet.post(f'/api/jobs/{job["id"]}/heartbeat',
                      json={'editor': USER}).status_code == 410
    assert fleet.get(f'/api/jobs/{job["id"]}/download-manifest').status_code == 410
    # ...and nobody may claim it back
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body()).status_code == 410

    # ...while the server picks up exactly what the editor's machine did not
    # finish -- the ordinary reclaim, not a second path (§3)
    worker.run_job(con, job['id'])
    assert [c[0] for c in fake_downloader.calls] == ['bbbbbbbbbbb']
    done = db.get_job(con, job['id'])
    assert done['phase'] == 'done' and done['download_mode'] == db.MODE_SERVER
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['download_host'] == USER


def test_a_download_press_forgives_the_last_runs_pin(client, con, fleet):
    """YTDL-WEB-7 (2026-08-14): the close-out pin is per RUN, not per job.

    end_lease pins a job to the server on the ordinary, successful hand-back --
    the same one-way pin a reclaim uses -- and nothing ever cleared it. So the
    YTDL-16 retry path (press DOWNLOAD on a `done` job to re-fetch the clips
    that failed) was permanently refused to the editor's own machine and ran
    from the NAS's IP: the very IP whose bot-check is the likeliest reason
    those clips failed."""
    job = _job(con, ids=('aaaaaaaaaaa',))
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    fleet.post(f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status',
               json={'state': 'failed', 'error': 'confirm you are not a bot'})
    assert db.get_job(con, job['id'])['mode_lock'] == db.MODE_SERVER
    db.set_phase(con, job['id'], 'done')

    assert client.post(f'/api/jobs/{job["id"]}/download').status_code == 200
    assert db.get_job(con, job['id'])['mode_lock'] is None
    assert fleet.post(f'/api/jobs/{job["id"]}/claim',
                      json=_claim_body()).status_code == 200


def test_another_editors_job_cannot_be_locked(client, con):
    """The browser routes are owned per editor, in SQL (routes_api's rule):
    an unowned job is 404, because "there is no such job" is all another editor
    is entitled to know."""
    slug, label, _ = PROJECTS[0]
    theirs = db.create_job(con, OTHER, 'wind', 'wind', slug, label)
    assert client.post(f'/api/jobs/{theirs}/mode-lock',
                       json={'mode': 'server'}).status_code == 404


# ------------------------------------------------------------------ cancelling

def test_a_cancel_stops_a_local_download(fleet, con, project_root,
                                         fake_downloader):
    """YTDL-WEB-1 (2026-08-14): CANCEL was a no-op for the whole of a local run.

    `cancel_requested` is honoured inside run_job, and claim_next_job hides a
    leased job from the worker -- so with a companion heartbeating every 30 s
    the flag was read by nobody until the last clip handed the job back. The
    editor who realised two clips in that they had picked the wrong project
    watched all 41 land on their disk, go up lane A into the wrong project's
    canonical tree, and be ledgered fleet-wide as `done`."""
    job = _job(con)
    fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())

    r = fleet.post(f'/api/jobs/{job["id"]}/cancel')
    assert r.status_code == 200 and r.json()['stopped_local_download'] is True

    # the companion hears it at its next call, whichever that is
    assert fleet.post(f'/api/jobs/{job["id"]}/heartbeat',
                      json={'editor': USER}).status_code == 410
    assert fleet.get(f'/api/jobs/{job["id"]}/download-manifest').status_code == 410
    late = fleet.post(f'/api/jobs/{job["id"]}/clips/aaaaaaaaaaa/status',
                      json={'state': 'done',
                            'filepath_rel': 'Test Channel - a [aaaaaaaaaaa].mp4'})
    assert late.status_code == 410
    assert db.ledger_get(con, 'aaaaaaaaaaa') is None, \
        'a cancelled clip was recorded as the fleet having it'

    # ...and the worker has the job back NOW rather than a lease from now
    assert db.claim_next_job(con)['id'] == job['id']
    worker.run_job(con, job['id'])
    assert db.get_job(con, job['id'])['phase'] == 'cancelled'
    assert fake_downloader.calls == [], 'the server picked the cancelled job up'


def test_a_job_with_a_pending_cancel_is_never_handed_out(fleet, con):
    """The other end of the same second: the editor pressed CANCEL while the
    SPA was still probing their loopback. The claim that arrives a moment later
    must not start the download they just stopped."""
    job = _job(con)
    db.request_cancel(con, job['id'])
    r = fleet.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body())
    assert r.status_code == 410
    assert r.json()['detail']['reason'] == 'cancelled'
    assert db.get_job(con, job['id'])['download_mode'] == db.MODE_SERVER
    # ...and the CAS refuses it even without the route's own pre-check
    assert db.claim_download(con, job['id'], USER, config.LEASE_SECONDS) is False


# ------------------------------------------------------------------- the flag

def test_the_feature_ships_off_and_nothing_else_changes(client, con,
                                                        project_root,
                                                        fake_downloader):
    """Phase 1 deploys with YTDL_LOCAL_DOWNLOAD unset, and then the SPA never
    probes the loopback -- so the fleet's behaviour is byte-for-byte what it
    was (§10). That is the whole rollback story, and it is one boolean."""
    assert config.LOCAL_DOWNLOAD is False
    assert client.get('/api/health').json()['local_download'] is False

    job = _job(con, ids=('aaaaaaaaaaa',))
    worker.run_job(con, job['id'])
    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'done'
    assert fresh['download_mode'] == db.MODE_SERVER
    assert [c[0] for c in fake_downloader.calls] == ['aaaaaaaaaaa']
    assert db.get_video(con, job['id'],
                        'aaaaaaaaaaa')['download_host'] == db.MODE_SERVER


def test_the_flag_is_reported_when_it_is_on(client, monkeypatch):
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', True)
    assert client.get('/api/health').json()['local_download'] is True


# ------------------------------------------ CR-34: who gets to the row first

def test_the_worker_holds_the_door_open_for_the_requesters_machine(
        con, monkeypatch, fake_downloader):
    """CR-34 (2026-08-19). Every guard between the two executors was correct
    and the outcome was still wrong: `start_download` writes the pending rows
    and nudges the worker in ONE request, and the worker took the only row
    ~160 ms before the browser's claim could land. The companion then asked for
    its manifest, was told 0 clips (truthfully -- the row was `downloading` on
    the server), logged "job 50 -- 0 clip(s)" and stood down. The clip landed
    on the NAS, which no lane brings back down.

    Measured on the live fleet, not imagined: job 50, one clip, /download at
    T+0.000 and the claim at T+0.161.
    """
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', True)
    monkeypatch.setattr(config, 'LOCAL_CLAIM_GRACE_SECONDS', 5.0)
    job = _job(con, ids=('aaaaaaaaaaa',))

    # The claim lands DURING the grace, exactly as the companion's does.
    ticks = {'n': 0}

    def sleep(_seconds):
        ticks['n'] += 1
        if ticks['n'] == 2:
            db.claim_download(con, job['id'], USER, config.LEASE_SECONDS)

    assert worker._await_local_claim(con, job['id'], sleep=sleep) is True

    worker.run_job(con, job['id'])
    # Not one byte fetched by the server, and the row is still the companion's
    # to take: `pending`, which is what its manifest is built from.
    assert fake_downloader.calls == []
    assert db.get_video(con, job['id'], 'aaaaaaaaaaa')['dl_state'] == 'pending'


def test_the_grace_ends_and_the_server_downloads_when_nobody_claims(
        con, monkeypatch, fake_downloader):
    """The other half, and the one that must not regress: a fleet with no
    companion able to take the job waits a couple of seconds ONCE and then
    behaves exactly as it always did. The wait is bounded by the clock, not by
    an answer that may never come."""
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', True)
    monkeypatch.setattr(config, 'LOCAL_CLAIM_GRACE_SECONDS', 0.3)
    job = _job(con, ids=('aaaaaaaaaaa',))

    assert worker._await_local_claim(con, job['id'], sleep=lambda _s: None) is False

    worker.run_job(con, job['id'])
    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'done'
    assert [c[0] for c in fake_downloader.calls] == ['aaaaaaaaaaa']


def test_no_grace_at_all_when_the_feature_is_off(con, monkeypatch):
    """LOCAL_DOWNLOAD off is the rollback switch (§10), and it has to mean
    byte-for-byte the old behaviour -- including not making every job on every
    fleet that never enabled this wait for a claim that cannot come."""
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', False)
    monkeypatch.setattr(config, 'LOCAL_CLAIM_GRACE_SECONDS', 60.0)
    job = _job(con, ids=('aaaaaaaaaaa',))

    def never(_seconds):
        raise AssertionError('it waited for a claim with the feature off')

    assert worker._await_local_claim(con, job['id'], sleep=never) is False


# --------------------------- CR-37: a dead run must not pin the next one

def test_a_new_run_forgets_the_last_ones_executor_entirely(con, monkeypatch):
    """CR-37 (2026-08-19). Measured on the live fleet, job 50:

        06:10:15.477  POST /jobs/50/download  200      <- pin cleared here
        06:10:15.479  job 50: the local download lease held by ruskin expired;
                      the server is taking the job back
        06:10:15.592  POST /jobs/50/claim     410 "pinned to the server"

    `download_mode` stayed `local` from a run that had ended half an hour
    earlier -- a job that finishes while local keeps the value, and a `done`
    job is never picked up again for the worker to reclaim it. So this
    endpoint's own nudge sent _phase_download down the reclaim path for a dead
    run, reclaim_download re-pinned the job (correctly: reclaim is one-way
    WITHIN a run), and the editor's machine was refused on every retry after.
    """
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', True)
    job = _job(con, ids=('aaaaaaaaaaa',))
    job_id = job['id']

    # The state a finished local run leaves behind.
    db.claim_download(con, job_id, USER, config.LEASE_SECONDS)
    db.set_phase(con, job_id, 'done')
    stale = db.get_job(con, job_id)
    assert stale['download_mode'] == db.MODE_LOCAL

    db.clear_mode_lock(con, job_id)

    fresh = db.get_job(con, job_id)
    assert fresh['mode_lock'] in (None, '')
    # ALL FOUR, not just the pin: any one of them left behind is a reclaim
    # waiting to re-pin the job the moment the worker looks at it.
    assert fresh['download_mode'] == db.MODE_SERVER
    assert not fresh['claimed_by']
    assert not fresh['lease_expires_at']
    assert not db.lease_active(fresh)


def test_the_editors_machine_can_claim_a_revived_job(client, con, monkeypatch):
    """The end-to-end shape of CR-37, through the API the SPA actually uses:
    press DOWNLOAD on a finished job that once ran locally, and the claim that
    follows must be granted rather than answered 410."""
    monkeypatch.setattr(config, 'LOCAL_DOWNLOAD', True)
    job = _job(con, ids=('aaaaaaaaaaa',))
    job_id = job['id']
    db.claim_download(con, job_id, USER, config.LEASE_SECONDS)
    db.set_video(con, job_id, 'aaaaaaaaaaa', dl_state='failed',
                 dl_error='bot check')
    db.set_phase(con, job_id, 'done')

    r = client.post(f'/api/jobs/{job_id}/download')
    assert r.status_code == 200, r.text
    assert db.claim_download(con, job_id, USER, config.LEASE_SECONDS) is True
