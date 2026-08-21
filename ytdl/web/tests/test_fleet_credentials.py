"""Which MACHINE credential the fleet routes accept (ytdl-web-1, 2026-08-21).

Two of them reach these routes, not one. The shared DASH_REPORT_TOKEN is the
one every companion holds today and the only one this app can check by itself.
The other is a per-editor `cce1.<id>.<secret>` minted on Admin > Users, stored
HASHED in the dashboard's database -- which this app opens read-only and only
for selections, so it could never verify one. The dashboard's mount resolves it
and stamps the answer into X-CCSync-Fleet-Auth.

The bug this file pins: an editor whose admin had minted them a cce1 token sent
it on every claim/heartbeat/status POST (the companion's IdentityManager writes
preferred_report_token into `dashboard_token`, and a per-editor token outranks
the shared one there). The dashboard's own gate accepted it; this app then
answered 403 one layer down, so requester-first downloads stopped for that
editor with nothing but a stand-down line to say so -- and the migration the
dashboard's boot log asks for (mint per-editor tokens, then
DASH_SHARED_REPORT_TOKEN_ENABLED=0) would have stopped them for the whole
fleet.

The stamp is only ever believed when the mount installed the trust, because
only a mount strips a forged copy on the way in.
"""
import pytest

from tests.conftest import USER
from tests.test_local_download import (SECRET, TOKEN, _claim_body,
                                       _identity_header, _job)
from ytdlweb import config, db, routes_fleet

OTHER = 'sam'


@pytest.fixture()
def mounted(client, monkeypatch):
    """A client behind a dashboard mount that has installed the stamp trust.

    REPORT_TOKEN is left EMPTY on purpose: that is the deployment the boot
    warning asks for (per-editor tokens minted, the shared one retired), and it
    is the state in which the old code refused every fleet call.
    """
    monkeypatch.setattr(config, 'REPORT_TOKEN', '')
    monkeypatch.setattr(config, 'SESSION_SECRET', SECRET)
    monkeypatch.setattr(routes_fleet, '_trust_stamp', False)
    routes_fleet.trust_gate_stamp(True)
    client.headers.update(_identity_header(USER))
    return client


def _claim(client, job, **headers):
    return client.post(f'/api/jobs/{job["id"]}/claim', json=_claim_body(),
                       headers=headers)


def test_a_per_editor_token_the_dashboard_vouched_for_is_accepted(mounted, con):
    """THE DEFECT. A cce1 token, a shared secret that is gone, and a claim that
    has to work anyway -- because since 2026-08-16 lane B does not bring
    YouTube originals down, so this route is the only way an editor's own clips
    reach them."""
    job = _job(con)
    r = _claim(mounted, job, **{'x-ccsync-token': 'cce1.abcdef.0123456789',
                                'x-ccsync-fleet-auth': f'editor:{USER}'})
    assert r.status_code == 200, r.text
    fresh = db.get_job(con, job['id'])
    assert fresh['download_mode'] == db.MODE_LOCAL
    assert fresh['claimed_by'] == USER


def test_the_shared_token_is_accepted_through_the_stamp_as_well(mounted, con):
    """The gate resolves BOTH credentials, so a fleet still on the shared token
    arrives stamped `shared` and must be as welcome as it ever was."""
    job = _job(con)
    r = _claim(mounted, job, **{'x-ccsync-token': TOKEN,
                                'x-ccsync-fleet-auth': 'shared'})
    assert r.status_code == 200, r.text


def test_a_stamp_bound_to_another_editor_cannot_act_as_this_one(mounted, con):
    """A bound token proves WHICH machine's editor is calling and the signed
    identity header proves whose name the call acts under. Disagreement is a
    refusal, or the move to bound tokens would be weaker than the check it
    replaced."""
    job = _job(con)
    r = _claim(mounted, job, **{'x-ccsync-token': f'cce1.abcdef.{OTHER}',
                                'x-ccsync-fleet-auth': f'editor:{OTHER}'})
    assert r.status_code == 403
    assert r.json()['detail']['reason'] == 'identity_mismatch'
    assert db.get_job(con, job['id'])['download_mode'] == db.MODE_SERVER


def test_the_stamp_decides_nothing_unless_a_mount_installed_it(client, con,
                                                               monkeypatch):
    """Standalone -- the dev server, this suite -- nothing strips an inbound
    copy of the header, so nothing may believe one. The shared-token compare is
    the whole gate there, and it still fails closed."""
    monkeypatch.setattr(config, 'REPORT_TOKEN', '')
    monkeypatch.setattr(config, 'SESSION_SECRET', SECRET)
    monkeypatch.setattr(routes_fleet, '_trust_stamp', False)
    client.headers.update(_identity_header(USER))
    job = _job(con)
    r = _claim(client, job, **{'x-ccsync-token': 'cce1.abcdef.0123456789',
                               'x-ccsync-fleet-auth': f'editor:{USER}'})
    assert r.status_code == 403
    assert db.get_job(con, job['id'])['download_mode'] == db.MODE_SERVER


def test_an_unparseable_stamp_falls_back_to_the_token_and_fails_closed(mounted,
                                                                       con):
    """A stamp this build does not understand is never an opening: it falls
    through to the shared-token comparison, which is unconfigured here."""
    job = _job(con)
    for value in ('', 'editor:', 'whatever', 'admin'):
        r = _claim(mounted, job, **{'x-ccsync-token': 'cce1.abcdef.0123456789',
                                    'x-ccsync-fleet-auth': value})
        assert r.status_code == 403, value


def test_every_fleet_route_takes_the_stamp_not_just_the_claim(mounted, con):
    """The four shapes travel together: a companion that could claim but not
    post a status would download clips nothing recorded."""
    job = _job(con)
    stamp = {'x-ccsync-token': 'cce1.abcdef.0123456789',
             'x-ccsync-fleet-auth': f'editor:{USER}'}
    assert _claim(mounted, job, **stamp).status_code == 200
    jid = job['id']
    assert mounted.post(f'/api/jobs/{jid}/heartbeat', json={},
                        headers=stamp).status_code == 200
    assert mounted.get(f'/api/jobs/{jid}/download-manifest',
                       headers=stamp).status_code == 200
    assert mounted.post(f'/api/jobs/{jid}/clips/aaaaaaaaaaa/status',
                        json={'state': 'downloading'},
                        headers=stamp).status_code == 200
