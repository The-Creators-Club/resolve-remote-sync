"""The runtime NAS seam (SYNOLOGY_PORT_PLAN.md WP1).

Two things are pinned here. First, that the admin-user call sites are
BACKEND-AGNOSTIC: the same requests run against every backend the dashboard
can be configured with (the `nas_case` fixture in conftest.py), and a backend
that cannot do the job answers with a banner or a 502 -- never a traceback,
never a silent success. Second, the settings contract WP0 step 1 introduced:
no tenant's addresses as defaults, and the TRUENAS_* env names still honoured
for one release.
"""
from __future__ import annotations

import ast
import logging
import sys
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard.app import create_app
from ccsync_dashboard.nas import (
    NasBackend, NasError, SynologyClient, TrueNASClient, make_nas_client, nas_configured,
)
from ccsync_dashboard.nas import factory as nas_factory
from ccsync_dashboard.settings import Settings

from fake_syncthing import FakeSyncthing
from fake_synology import FakeDSM, FakeSynology

SECRET = "test-secret"
GOOD_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA newbie@laptop"


@pytest.fixture
def syncthing():
    fake = FakeSyncthing().start()
    yield fake
    fake.stop()


def client_for(tmp_path, nas_case, syncthing=None, **extra):
    kwargs = dict(nas_case.kwargs)
    kwargs.update(extra)
    settings = Settings(
        db_path=str(tmp_path / f"{nas_case.kind}.db"),
        session_secret=SECRET,
        admin_users=frozenset({"alex"}),
        syncthing_url=syncthing.url if syncthing else "",
        syncthing_api_key="fake-key" if syncthing else "",
        **kwargs,
    )
    return create_app(settings)


def as_admin(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "alex"))
    return client


# ----------------------------------------------------- every backend, same calls


def test_admin_users_view_over_every_backend(tmp_path, nas_case, syncthing):
    """A backend that cannot list accounts must not take the device-approval
    half of the panel down with it -- the DASH-7 rule, now per backend."""
    new_id = "NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1"
    syncthing.state["pending_devices"] = {new_id: {"name": "", "address": "100.9.9.9:22000"}}
    with TestClient(client_for(tmp_path, nas_case, syncthing)) as client:
        as_admin(client)
        body = client.get("/api/v1/admin/users").json()

    assert body["truenas_configured"] is True
    assert body["syncthing_error"] is None
    assert new_id in {d["device_id"] for d in body["pending_devices"]}
    if nas_case.provisions:
        assert body["truenas_error"] is None
    else:
        assert nas_case.error_fragment in body["truenas_error"]
        assert body["editors"] == []


def test_the_service_account_never_lists_as_an_editor(tmp_path, nas_case, syncthing):
    """The stack's own NAS account (site.toml [stack] owner -> DASH_NAS_SERVICE_USER)
    is plumbing; on the first Synology bring-up it appeared on the Users page as
    an editor with a MISSING ssh key (2026-08-17)."""
    if not nas_case.provisions:
        pytest.skip("listing needs a provisioning backend")
    nas_case.seed_editor("jsmith", 3010)
    nas_case.seed_editor("ccsync-svc", 3011)
    with TestClient(client_for(tmp_path, nas_case, syncthing,
                               nas_service_user="ccsync-svc")) as client:
        as_admin(client)
        body = client.get("/api/v1/admin/users").json()
    names = {e["username"] for e in body["editors"]}
    assert "jsmith" in names and "ccsync-svc" not in names


def test_create_editor_over_every_backend(tmp_path, nas_case, syncthing):
    with TestClient(client_for(tmp_path, nas_case, syncthing)) as client:
        as_admin(client)
        resp = client.post("/api/v1/admin/users", json={
            "username": "newbie", "ssh_pubkey": GOOD_KEY, "full_name": "New Editor",
        })

    if nas_case.provisions:
        assert resp.status_code == 200, resp.text
        assert resp.json()["result"]["created"] is True
    else:
        # 502, i.e. "the upstream NAS would not do this" -- and the reason
        # says which work package owes the operator the feature.
        assert resp.status_code == 502, resp.text
        assert nas_case.error_fragment in resp.json()["detail"]


def test_create_editor_partial_over_every_backend(tmp_path, nas_case, syncthing):
    """The htmx form path renders the refusal into the page instead of
    500ing, for every backend."""
    with TestClient(client_for(tmp_path, nas_case, syncthing)) as client:
        as_admin(client)
        resp = client.post("/partials/admin/users/create", data={
            "username": "newbie", "ssh_pubkey": GOOD_KEY,
        })

    assert resp.status_code == 200
    if nas_case.provisions:
        assert "newbie" in resp.text
    else:
        assert nas_case.error_fragment in resp.text


def test_set_password_over_every_backend(tmp_path, nas_case, syncthing):
    if nas_case.provisions:
        nas_case.seed_editor("jsmith")
    with TestClient(client_for(tmp_path, nas_case, syncthing)) as client:
        as_admin(client)
        resp = client.post("/api/v1/admin/users/jsmith/password",
                           json={"password": "knownpw123"})

    if nas_case.provisions:
        assert resp.status_code == 200, resp.text
    else:
        assert resp.status_code == 502
        assert nas_case.error_fragment in resp.json()["detail"]


def test_fleet_membership_check_over_every_backend(tmp_path, nas_case):
    """/api/v1/verify fails CLOSED but retryable when the backend cannot
    answer -- the same posture for a DSM stub as for an unreachable TrueNAS
    (a backend that cannot be asked must never mint an identity)."""
    if nas_case.provisions:
        nas_case.seed_editor("jsmith")
    app = client_for(tmp_path, nas_case, report_token="tok")
    app.state.credential_verifier = lambda s, u, p: True
    with TestClient(app) as client:
        resp = client.post("/api/v1/verify", json={"username": "jsmith", "password": "pw"})

    if nas_case.provisions:
        assert resp.status_code == 200, resp.text
    else:
        assert resp.status_code == 503
        assert "try again" in resp.json()["detail"]
        assert "report_token" not in resp.text


# ----------------------------------------------------------------- the factory


def test_factory_builds_the_backend_named_by_nas_kind():
    truenas = make_nas_client(Settings(nas_kind="truenas", nas_host="nas.example",
                                       nas_user="admin", nas_pw="pw"))
    assert isinstance(truenas, TrueNASClient)
    synology = make_nas_client(Settings(nas_kind="synology", nas_host="dsm.example",
                                        nas_user="admin", nas_pw="pw"))
    assert isinstance(synology, SynologyClient)
    assert synology.port == 5001


def test_factory_refuses_an_unknown_kind_rather_than_guessing():
    """A typo'd DASH_NAS_KIND must not quietly provision accounts on a NAS the
    operator did not name."""
    with pytest.raises(NasError) as exc:
        make_nas_client(Settings(nas_kind="qnap", nas_host="x", nas_user="u", nas_pw="p"))
    assert "truenas" in str(exc.value) and "synology" in str(exc.value)


def test_unknown_kind_is_a_503_not_a_500(tmp_path, syncthing):
    settings = Settings(db_path=str(tmp_path / "k.db"), session_secret=SECRET,
                        admin_users=frozenset({"alex"}), nas_kind="qnap",
                        nas_host="nas.example", nas_user="admin", nas_pw="pw",
                        syncthing_url=syncthing.url, syncthing_api_key="fake-key")
    with TestClient(create_app(settings)) as client:
        as_admin(client)
        resp = client.post("/api/v1/admin/users",
                           json={"username": "newbie", "ssh_pubkey": GOOD_KEY})
        assert resp.status_code == 503
        assert "DASH_NAS_KIND" in resp.json()["detail"]
        # the read-only view degrades to a banner, as it does for any backend
        # failure -- the page still renders
        assert client.get("/api/v1/admin/users").status_code == 200


def test_a_blank_host_reads_as_not_configured(tmp_path):
    """WP0 blanked the hardcoded 192.168.0.102 default. A deployment that
    never set DASH_NAS_HOST must get the honest "not configured" 503, not a
    connection error against https:///api/v2.0."""
    assert nas_configured(Settings(nas_pw="pw")) is False
    assert nas_configured(Settings(nas_pw="pw", nas_host="nas.example")) is True
    settings = Settings(db_path=str(tmp_path / "b.db"), session_secret=SECRET,
                        admin_users=frozenset({"alex"}), nas_pw="pw")
    with TestClient(create_app(settings)) as client:
        as_admin(client)
        resp = client.post("/api/v1/admin/users",
                           json={"username": "newbie", "ssh_pubkey": GOOD_KEY})
        assert resp.status_code == 503
        assert client.get("/api/v1/admin/users").json()["truenas_configured"] is False


# ------------------------------------------------------------------- settings


def test_no_tenant_addresses_are_shipped_as_defaults():
    """The whole point of WP0 step 1: a second site must not inherit the
    first site's NAS by leaving an env var unset."""
    fresh = Settings.from_env({})
    assert fresh.smb_host == ""
    assert fresh.nas_host == "" and fresh.truenas_host == ""
    assert fresh.nas_user == "" and fresh.truenas_user == ""
    assert fresh.nas_kind == "truenas"


def test_truenas_env_names_still_work_and_the_neutral_ones_win():
    legacy = Settings.from_env({"TRUENAS_HOST": "old.example", "TRUENAS_USER": "truenas_admin",
                                "TRUENAS_PW": "pw", "TRUENAS_VERIFY_SSL": "1"})
    assert (legacy.nas_host, legacy.nas_user, legacy.nas_pw) == ("old.example", "truenas_admin", "pw")
    assert legacy.nas_verify_ssl is True and legacy.truenas_verify_ssl is True

    both = Settings.from_env({"TRUENAS_HOST": "old.example", "DASH_NAS_HOST": "dsm.example",
                              "DASH_NAS_KIND": "synology", "DASH_NAS_PW": "pw"})
    assert both.nas_host == "dsm.example" and both.truenas_host == "dsm.example"
    assert both.nas_kind == "synology"


def test_both_attribute_spellings_agree_however_the_object_was_built():
    """Constructed with the legacy names (as much of this suite still is), or
    the neutral ones -- either way both read the same."""
    legacy = Settings(truenas_host="nas.example", truenas_pw="pw")
    assert legacy.nas_host == "nas.example" and legacy.nas_pw == "pw"
    neutral = Settings(nas_host="dsm.example", nas_pw="pw")
    assert neutral.truenas_host == "dsm.example" and neutral.truenas_pw == "pw"


def test_unset_identity_warns_but_never_crashes(caplog):
    with caplog.at_level(logging.WARNING, logger="ccsync.dashboard.settings"):
        Settings.from_env({})
    warning = "\n".join(r.getMessage() for r in caplog.records)
    assert "DASH_SMB_HOST" in warning and "DASH_NAS_HOST" in warning

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="ccsync.dashboard.settings"):
        Settings.from_env({"DASH_SMB_HOST": "nas.example", "DASH_NAS_HOST": "nas.example",
                           "DASH_NAS_USER": "admin"})
    assert caplog.records == []


# ------------------------------------------------------- the Synology backend


def test_synology_unreachable_is_a_banner_not_a_traceback():
    """The WP2 backend talks to a real DSM now, so the thing worth pinning
    here is the failure mode the stub used to provide for free: a NAS that
    cannot be reached raises NasError (which every call site turns into a
    banner or a 502), never a bare requests exception."""
    client = SynologyClient("dsm.invalid", "admin", "pw", False, timeout=0.2)
    for call in (
        lambda: client.ping(),
        lambda: client.ensure_editors_group(),
        lambda: client.find_user("jsmith"),
        lambda: client.list_editors(),
        lambda: client.is_editor("jsmith"),
        lambda: client.create_or_update_editor("jsmith", GOOD_KEY),
        lambda: client.set_known_password("jsmith", "pw"),
    ):
        with pytest.raises(NasError) as exc:
            call()
        assert "dsm.invalid" in str(exc.value)


def test_paramiko_is_not_a_core_dependency_of_the_dashboard():
    """WP2's SSH half needs paramiko, and it is an OPTIONAL extra: a TrueNAS
    site must be able to import this package without it, so the import lives
    inside _ssh_client()/_parse_host_key() and never at module scope. The
    dashboard's [project.dependencies] is unchanged by the Synology backend
    (deploy/requirements.txt gains it only on a DSM site)."""
    source = Path(__file__).resolve().parents[1] / "src" / (
        SynologyClient.__module__.replace(".", "/") + ".py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    module_level = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            module_level.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            module_level.add(node.module.split(".")[0])
    assert "paramiko" not in module_level, module_level
    assert module_level <= set(sys.stdlib_module_names) | {"requests"}, module_level

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8-sig"))
    assert not any(d.startswith("paramiko") for d in pyproject["project"]["dependencies"])
    assert any(d.startswith("paramiko")
               for d in pyproject["project"]["optional-dependencies"]["synology"])


def test_every_backend_and_fake_answers_the_whole_protocol():
    for backend in (TrueNASClient("h", "u", "p"), SynologyClient("h", "u", "p", False),
                    FakeSynology()):
        assert isinstance(backend, NasBackend), backend


def test_the_fake_synology_carries_the_same_refusals_as_truenas():
    """Not a fake's whim: "never a system account, never an account that
    isn't already an editor" is this dashboard's rule, and WP2's real backend
    has to carry it too (SYNOLOGY_PORT_PLAN WP2's third bullet)."""
    fake = FakeSynology()
    gid, _ = fake.ensure_editors_group()
    fake.state["users"].extend([
        {"id": 1, "uid": 1024, "username": "admin", "full_name": "admin",
         "home": "/var/services/homes/admin", "groups": [100], "sshpubkey": None,
         "smb": False, "locked": False},
        {"id": 2, "uid": 1040, "username": "bookkeeper", "full_name": "bookkeeper",
         "home": "/var/services/homes/bookkeeper", "groups": [100], "sshpubkey": None,
         "smb": True, "locked": False},
    ])
    with pytest.raises(NasError, match="system account"):
        fake.create_or_update_editor("admin", GOOD_KEY)
    with pytest.raises(NasError, match="not in the 'editors' group"):
        fake.create_or_update_editor("bookkeeper", GOOD_KEY)
    with pytest.raises(NasError, match="system account"):
        fake.set_known_password("admin", "pwned1234")

    result = fake.create_or_update_editor("newbie", GOOD_KEY, "New Editor")
    assert result == {"created": True, "username": "newbie", "home_ok": True, "warnings": []}
    assert fake.is_editor("newbie") and not fake.is_editor("bookkeeper")
    assert [u["username"] for u in fake.list_editors()] == ["newbie"]
    assert gid in fake.find_user("newbie")["groups"]


def test_the_admin_call_sites_provision_through_any_backend(tmp_path, syncthing, monkeypatch):
    """The mirror image of the stub tests: with a backend that CAN do the job,
    the same routes create the account and record the known editor without a
    line of TrueNAS-specific code in api.py or ui.py.

    Patching the factory (rather than a client class) is the check that both
    api.py and ui.py really go through the one seam.
    """
    fake = FakeSynology()
    monkeypatch.setattr(nas_factory, "make_nas_client", lambda settings: fake)
    settings = Settings(db_path=str(tmp_path / "s.db"), session_secret=SECRET,
                        admin_users=frozenset({"alex"}), nas_kind="synology",
                        nas_host="dsm.example", nas_user="ccsync", nas_pw="pw",
                        syncthing_url=syncthing.url, syncthing_api_key="fake-key")
    with TestClient(create_app(settings)) as client:
        as_admin(client)
        resp = client.post("/api/v1/admin/users", json={
            "username": "newbie", "ssh_pubkey": GOOD_KEY, "password": "hunter2horse",
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["result"]["created"] is True

        # ...and the htmx form path, which is what the Users page posts to
        resp = client.post("/partials/admin/users/create", data={
            "username": "second", "ssh_pubkey": GOOD_KEY,
        })
        assert resp.status_code == 200
        view = client.get("/api/v1/admin/users").json()

    assert fake.find_user("newbie")["password"] == "hunter2horse"
    assert {u["username"] for u in fake.list_editors()} == {"newbie", "second"}
    assert {e["username"] for e in view["editors"]} == {"newbie", "second"}
    assert all(e["has_ssh_key"] for e in view["editors"])
