"""Which MACHINE credential the b-roll fleet routes accept (CR-55, 2026-08-21).

Two of them reach these routes, not one. The shared DASH_REPORT_TOKEN is the
one every companion holds today and the only one this app can check by itself.
The other is a per-editor `cce1.<id>.<secret>` minted on Admin > Users, stored
HASHED in the dashboard's database -- which this separately deployed tree never
sees, so it could not verify one if it tried. The dashboard's mount resolves it
and stamps the answer into `X-CCSync-Fleet-Auth`.

The bug this file pins: an editor whose admin had minted them a cce1 token sent
it on every claim/heartbeat/result/uploaded (the companion's IdentityManager
writes preferred_report_token into `dashboard_token`, and a per-editor token
outranks the shared one there). The dashboard's own gate accepted it; this app
then answered 403 one layer down, so that editor's drag-and-drop ingest never
started -- and the migration the dashboard's boot log asks for (mint per-editor
tokens, then retire the shared one) would have stopped it fleet-wide. Music and
ytdl were fixed on 2026-08-21; b-roll was nobody's territory that day (CR-67
item 2).

The stamp is only ever believed when the mount installed the trust, because
only a mount strips a forged copy on the way in.
"""
from __future__ import annotations

import pytest

from app import fleet_auth
from tests.conftest import SESSION_SECRET
from tests.test_fleet_ingest import BASE, _queue

CCE1 = "cce1." + "0" * 16 + "." + "9" * 48
OTHER = "kchen"


def _identity(editor="jsmith"):
    from app import identity

    return identity.make_identity_token(SESSION_SECRET, editor)


@pytest.fixture()
def mounted(monkeypatch):
    """A tree behind a dashboard mount that has installed the stamp trust.

    DASH_REPORT_TOKEN is DELETED on purpose: that is the deployment the
    dashboard's boot warning asks for (per-editor tokens minted, the shared one
    retired), and it is the state in which the old code refused every fleet
    call.
    """
    monkeypatch.delenv("DASH_REPORT_TOKEN", raising=False)
    monkeypatch.setattr(fleet_auth, "_trust_stamp", False)
    fleet_auth.trust_gate_stamp(True)
    yield
    fleet_auth.trust_gate_stamp(False)


def _claim(client, uid, **headers):
    return client.post(f"{BASE}/{uid}/claim",
                       json={"machine": "EDIT-01", "companion_version": "0.9.4"},
                       headers=headers)


def test_a_per_editor_token_the_dashboard_vouched_for_is_accepted(client, conn,
                                                                  mounted):
    """THE DEFECT. A cce1 token, a shared secret that is gone, and a claim that
    has to work anyway -- otherwise that editor's dropped clips sit in `queued`
    with nothing but a 403 in a log nobody reads."""
    uid = _queue(client)
    r = _claim(client, uid, **{"X-CCSync-Token": CCE1,
                               "X-CCSync-Fleet-Auth": "editor:jsmith",
                               "X-CCSync-Identity": _identity()})
    assert r.status_code == 200, r.text
    assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1


def test_the_shared_token_is_accepted_through_the_stamp_as_well(client, mounted):
    """The gate resolves BOTH credentials, so a fleet still on the shared token
    arrives stamped `shared` and must be as welcome as it ever was."""
    uid = _queue(client)
    r = _claim(client, uid, **{"X-CCSync-Token": "whatever-the-gate-checked",
                               "X-CCSync-Fleet-Auth": "shared",
                               "X-CCSync-Identity": _identity()})
    assert r.status_code == 200, r.text


def test_a_stamp_bound_to_another_editor_cannot_act_as_this_one(client, conn,
                                                                mounted):
    """A bound token proves WHICH machine's editor is calling and the signed
    identity proves whose name the call acts under. Disagreement is a refusal,
    or the move to bound tokens would be weaker than the check it replaced."""
    uid = _queue(client, editor="jsmith")
    r = _claim(client, uid, **{"X-CCSync-Token": CCE1,
                               "X-CCSync-Fleet-Auth": f"editor:{OTHER}",
                               "X-CCSync-Identity": _identity("jsmith")})
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "identity_mismatch"
    assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0


def test_the_stamp_decides_nothing_unless_a_mount_installed_it(client, conn,
                                                               monkeypatch):
    """Standalone -- the dev server, this suite -- nothing strips an inbound
    copy of the header, so nothing may believe one. The shared-token compare is
    the whole gate there, and it still fails closed."""
    uid = _queue(client)
    monkeypatch.setattr(fleet_auth, "_trust_stamp", False)
    monkeypatch.delenv("DASH_REPORT_TOKEN", raising=False)
    r = _claim(client, uid, **{"X-CCSync-Token": CCE1,
                               "X-CCSync-Fleet-Auth": "editor:jsmith",
                               "X-CCSync-Identity": _identity()})
    assert r.status_code == 403
    assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0


@pytest.mark.parametrize("value", ["", "editor:", "whatever", "admin"])
def test_an_unparseable_stamp_falls_back_to_the_token_and_fails_closed(
        client, mounted, value):
    """A stamp this build does not understand is never an opening: it falls
    through to the shared-token comparison, which is unconfigured here."""
    uid = _queue(client)
    r = _claim(client, uid, **{"X-CCSync-Token": CCE1,
                               "X-CCSync-Fleet-Auth": value,
                               "X-CCSync-Identity": _identity()})
    assert r.status_code == 403, value


def test_a_stamped_call_still_needs_a_signed_identity(client, mounted):
    """The stamp says WHICH credential; it is never WHO. The name still comes
    from the dashboard's signed identity token, verified here."""
    uid = _queue(client)
    r = _claim(client, uid, **{"X-CCSync-Token": CCE1,
                               "X-CCSync-Fleet-Auth": "editor:jsmith"})
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "identity"


def test_every_fleet_route_takes_the_stamp_not_just_the_claim(client, mounted,
                                                              data_root):
    """The shapes travel together: a companion that could claim but not post a
    result would index clips nothing recorded."""
    from tests.test_fleet_ingest import _result_body, _stage

    uid = _queue(client)
    stamp = {"X-CCSync-Token": CCE1, "X-CCSync-Fleet-Auth": "editor:jsmith",
             "X-CCSync-Identity": _identity()}
    manifest = _claim(client, uid, **stamp).json()["items"][0]
    item = manifest["uid"]
    assert client.post(f"{BASE}/{uid}/heartbeat", json={},
                       headers=stamp).status_code == 200
    assert client.post(f"{BASE}/{uid}/items/{item}/status",
                       json={"state": "proxying", "stage_percent": 10},
                       headers=stamp).status_code == 200
    assert client.post(f"{BASE}/{uid}/items/{item}/result", json=_result_body(),
                       headers=stamp).status_code == 200
    proxy = "Creators_Club/E2E/Proxy/A000.mp4"
    _stage(data_root, proxy, 100)
    assert client.post(f"{BASE}/{uid}/items/{item}/uploaded",
                       json={"files": [{"rel": proxy, "size": 100}]},
                       headers=stamp).status_code == 200
    assert client.post(f"{BASE}/{uid}/release", json={"state": "done"},
                       headers=stamp).status_code == 200
