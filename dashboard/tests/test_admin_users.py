from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

from fake_syncthing import EDITOR2_ID, EDITOR_ID, FakeSyncthing
from fake_truenas import FakeTrueNAS

SECRET = "test-secret"


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def known_editors(client) -> set[str]:
    conn = dbmod.connect(client.app.state.settings.db_path)
    try:
        return {r[0] for r in conn.execute("SELECT editor_username FROM known_editors")}
    finally:
        conn.close()


@pytest.fixture
def truenas():
    fake = FakeTrueNAS().start()
    yield fake
    fake.stop()


@pytest.fixture
def syncthing():
    fake = FakeSyncthing().start()
    yield fake
    fake.stop()


@pytest.fixture
def env(tmp_path, truenas, syncthing):
    settings = Settings(
        db_path=str(tmp_path / "admin.db"),
        session_secret=SECRET,
        admin_users=frozenset({"owen"}),
        truenas_host="unused-in-tests",
        truenas_user="truenas_admin",
        truenas_pw="fake-pw",
        truenas_base_url=truenas.base_url,
        syncthing_url=syncthing.url,
        syncthing_api_key="fake-key",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, truenas, syncthing


def test_non_admin_cannot_see_or_use_admin_users(env):
    client, _truenas, _syncthing = env
    assert client.get("/api/v1/admin/users").status_code == 401
    as_user(client, "jsmith")
    assert client.get("/api/v1/admin/users").status_code == 403
    assert client.get("/admin/users").status_code == 403
    resp = client.post("/api/v1/admin/users", json={
        "username": "newbie", "ssh_pubkey": "ssh-ed25519 AAAA newbie@laptop",
    })
    assert resp.status_code == 403


def test_admin_sees_unmapped_and_pending_devices(env):
    client, _truenas, syncthing = env
    syncthing.state["pending_devices"] = {
        "NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1": {
            "name": "", "address": "100.9.9.9:22000",
        }
    }
    as_user(client, "owen")
    body = client.get("/api/v1/admin/users").json()
    statuses = {d["device_id"]: d["status"] for d in body["pending_devices"]}
    # EDITOR2_ID is configured but named after itself (never approved) -> unmapped
    assert statuses[EDITOR2_ID] == "unmapped"
    assert statuses["NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1"] == "pending"
    # EDITOR_ID is already named "jsmith" -- a real mapped editor, not listed
    assert EDITOR_ID not in statuses


def test_a_truenas_blip_does_not_hide_the_device_approval_half(env):
    """DASH-7: a TrueNASError returned early with pending_devices=[] too, so
    the panel an admin has open BECAUSE somebody just plugged a machine in --
    the Syncthing approval table, which has nothing to do with TrueNAS --
    disappeared behind a banner about the other backend."""
    client, truenas, syncthing = env
    new_id = "NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1-NEWDEV1"
    syncthing.state["pending_devices"] = {new_id: {"name": "", "address": "100.9.9.9:22000"}}
    truenas.stop()                      # the blip
    as_user(client, "owen")

    body = client.get("/api/v1/admin/users").json()
    assert body["truenas_error"] and "truenas:" in body["error"]
    assert body["syncthing_error"] is None
    assert body["editors"] == []
    assert new_id in {d["device_id"] for d in body["pending_devices"]}

    panel = client.get("/partials/admin/users")
    assert panel.status_code == 200
    assert new_id in panel.text and "[ APPROVE ]" in panel.text
    # ...and the missing half says so rather than claiming there are none
    assert "account list unavailable" in panel.text
    assert "no editor accounts yet" not in panel.text


def test_a_syncthing_blip_does_not_hide_the_account_half(env):
    client, _truenas, syncthing = env
    syncthing.stop()
    as_user(client, "owen")

    body = client.get("/api/v1/admin/users").json()
    assert body["syncthing_error"] and body["truenas_error"] is None
    panel = client.get("/partials/admin/users")
    assert "device list unavailable" in panel.text
    assert "none pending" not in panel.text
    assert "[ CREATE NEW EDITOR ACCOUNT ]" in panel.text


def test_create_editor_account_end_to_end(env):
    client, truenas, _syncthing = env
    as_user(client, "owen")
    resp = client.post("/api/v1/admin/users", json={
        "username": "newbie",
        "ssh_pubkey": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA newbie@laptop",
        "full_name": "New Editor",
        "password": "hunter2horse",
    })
    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    assert result["created"] is True
    assert result["home_ok"] is True
    assert result["warnings"] == []

    [user] = [u for u in truenas.state["users"] if u["username"] == "newbie"]
    assert user["home"] == "/mnt/tank/TheCreatorsPool/homes/newbie"
    assert user["sshpubkey"].startswith("ssh-ed25519")
    assert user["smb"] is True
    # password_disabled attempt hit the expected 422 (smb user) and was left False
    assert user["password_disabled"] is False

    editors = client.get("/api/v1/admin/users").json()["editors"]
    assert any(e["username"] == "newbie" and e["has_ssh_key"] for e in editors)


def test_create_editor_rejects_bad_username_and_bad_key(env):
    client, _truenas, _syncthing = env
    as_user(client, "owen")
    bad_name = client.post("/api/v1/admin/users", json={
        "username": "Not A Good Name!", "ssh_pubkey": "ssh-ed25519 AAAA x@y",
    })
    assert bad_name.status_code == 422

    bad_key = client.post("/api/v1/admin/users", json={
        "username": "newbie", "ssh_pubkey": "not a key at all",
    })
    assert bad_key.status_code == 422


def test_create_editor_surfaces_home_directory_trap(env):
    """Mirrors the real incident in server/README.md: an existing account
    whose home isn't writable rejects the sshpubkey PUT outright."""
    client, truenas, _syncthing = env
    truenas.state["groups"].append({"id": 111, "group": "editors", "gid": 3001})
    truenas.state["users"].append({
        # already an editor (group id 111) -- an in-place update we DO allow
        "id": 80, "uid": 3005, "username": "owen_laptop", "full_name": "owen_laptop",
        "home": "/var/empty", "group": {"id": 116}, "groups": [40, 91, 111],
        "sshpubkey": None, "smb": True, "locked": False, "password_disabled": False,
    })
    truenas.state["block_sshpubkey_usernames"].add("owen_laptop")

    as_user(client, "owen")
    resp = client.post("/api/v1/admin/users", json={
        "username": "owen_laptop", "ssh_pubkey": "ssh-ed25519 AAAA owen@laptop",
    })
    assert resp.status_code == 502
    assert "not writable" in resp.json()["detail"]


def test_create_editor_refuses_to_hijack_a_non_editor_account(env):
    """is_valid_username() only checks the charset, so typing an existing
    account's name here used to overwrite its sshpubkey, force-add it to
    `editors` and try to disable its password. Refuse unless the account is
    already an editor -- and never touch a system (uid < 1000) account."""
    client, truenas, _syncthing = env
    truenas.state["groups"].append({"id": 111, "group": "editors", "gid": 3001})
    truenas.state["users"].append({
        "id": 1, "uid": 950, "username": "truenas_admin", "full_name": "admin",
        "home": "/root", "group": {"id": 5}, "groups": [5],
        "sshpubkey": "ssh-ed25519 AAAA admin@nas", "smb": False, "locked": False,
        "password_disabled": False,
    })
    truenas.state["users"].append({
        "id": 2, "uid": 4000, "username": "bookkeeper", "full_name": "bookkeeper",
        "home": "/mnt/tank/home/bookkeeper", "group": {"id": 60}, "groups": [60],
        "sshpubkey": "ssh-ed25519 AAAA book@pc", "smb": True, "locked": False,
        "password_disabled": False,
    })
    as_user(client, "owen")

    resp = client.post("/api/v1/admin/users", json={
        "username": "truenas_admin", "ssh_pubkey": "ssh-ed25519 AAAA attacker@laptop",
    })
    assert resp.status_code == 502 and "system account" in resp.json()["detail"]

    resp = client.post("/api/v1/admin/users", json={
        "username": "bookkeeper", "ssh_pubkey": "ssh-ed25519 AAAA attacker@laptop",
    })
    assert resp.status_code == 502 and "not in the 'editors' group" in resp.json()["detail"]

    # Neither account was modified.
    by_name = {u["username"]: u for u in truenas.state["users"]}
    assert by_name["truenas_admin"]["sshpubkey"] == "ssh-ed25519 AAAA admin@nas"
    assert by_name["bookkeeper"]["sshpubkey"] == "ssh-ed25519 AAAA book@pc"
    assert 111 not in by_name["bookkeeper"]["groups"]


def test_approve_pending_device(env):
    client, _truenas, syncthing = env
    # A real Syncthing device ID is base32 minus 0/1/8/9 -- the approve route
    # now shape-checks it the same way accept_device.py always did.
    new_id = "NEWDEVX-NEWDEVX-NEWDEVX-NEWDEVX-NEWDEVX-NEWDEVX-NEWDEVX-NEWDEVX"
    syncthing.state["pending_devices"] = {new_id: {"name": "", "address": "100.9.9.9:22000"}}

    as_user(client, "owen")
    resp = client.post("/api/v1/admin/devices/approve", json={
        "device_id": new_id, "username": "newbie",
    })
    assert resp.status_code == 200, resp.text

    devices = syncthing.state["devices"]
    added = next(d for d in devices if d["deviceID"] == new_id)
    assert added["name"] == "newbie"
    # approving must never touch any folder's device list -- that's the
    # selections table + enforce cycle's job, not this endpoint's.
    assert all(new_id not in {dd["deviceID"] for dd in f.get("devices", [])} for f in devices
               if isinstance(f, dict) and "devices" in f)
    for folder in syncthing.state["folders"]:
        assert new_id not in {d["deviceID"] for d in folder.get("devices", [])}


def test_approve_renames_already_configured_unmapped_device(env):
    client, _truenas, syncthing = env
    as_user(client, "owen")
    resp = client.post("/api/v1/admin/devices/approve", json={
        "device_id": EDITOR2_ID, "username": "rsmith",
    })
    assert resp.status_code == 200, resp.text
    renamed = next(d for d in syncthing.state["devices"] if d["deviceID"] == EDITOR2_ID)
    assert renamed["name"] == "rsmith"


def test_set_known_password(env):
    client, truenas, _syncthing = env
    truenas.state["groups"].append({"id": 111, "group": "editors", "gid": 3001})
    truenas.state["users"].append({
        "id": 5, "uid": 3010, "username": "jsmith", "full_name": "jsmith",
        "home": "/mnt/tank/TheCreatorsPool/homes/jsmith", "group": {"id": 111}, "groups": [111],
        "sshpubkey": "ssh-ed25519 AAAA", "smb": True, "locked": False, "password_disabled": False,
    })
    as_user(client, "owen")
    resp = client.post("/api/v1/admin/users/jsmith/password", json={"password": "knownpw1234567"})
    assert resp.status_code == 200
    [user] = [u for u in truenas.state["users"] if u["username"] == "jsmith"]
    assert user["password"] == "knownpw1234567"


def _seed_editors_group_and_system_accounts(truenas):
    truenas.state["groups"].append({"id": 111, "group": "editors", "gid": 3001})
    truenas.state["users"].extend([
        {"id": 1, "uid": 0, "username": "root", "full_name": "root", "home": "/root",
         "group": {"id": 5}, "groups": [5], "sshpubkey": None, "smb": False,
         "locked": False, "password_disabled": False},
        {"id": 2, "uid": 950, "username": "truenas_admin", "full_name": "admin",
         "home": "/root", "group": {"id": 5}, "groups": [5], "sshpubkey": None,
         "smb": False, "locked": False, "password_disabled": False},
        {"id": 3, "uid": 4000, "username": "bookkeeper", "full_name": "bookkeeper",
         "home": "/mnt/tank/home/bookkeeper", "group": {"id": 60}, "groups": [60],
         "sshpubkey": None, "smb": True, "locked": False, "password_disabled": False},
        {"id": 5, "uid": 3010, "username": "jsmith", "full_name": "jsmith",
         "home": "/mnt/tank/TheCreatorsPool/homes/jsmith", "group": {"id": 111},
         "groups": [111], "sshpubkey": "ssh-ed25519 AAAA", "smb": True,
         "locked": False, "password_disabled": False},
    ])


def test_set_password_refuses_root_and_system_accounts(env):
    """POST /admin/users/<name>/password took a free-text username straight
    to TrueNAS: an admin session could set the NAS ROOT password (and any
    system account's), turning "admin on the dashboard" into "owns the NAS".
    set_known_password now carries create_or_update_editor's refusals."""
    client, truenas, _syncthing = env
    _seed_editors_group_and_system_accounts(truenas)
    as_user(client, "owen")

    for name in ("root", "truenas_admin"):
        resp = client.post(f"/api/v1/admin/users/{name}/password", json={"password": "pwned1234abcd"})
        assert resp.status_code == 502, name
        assert "system account" in resp.json()["detail"], name

    by_name = {u["username"]: u for u in truenas.state["users"]}
    assert "password" not in by_name["root"]
    assert "password" not in by_name["truenas_admin"]


def test_set_password_refuses_accounts_outside_the_editors_group(env):
    client, truenas, _syncthing = env
    _seed_editors_group_and_system_accounts(truenas)
    as_user(client, "owen")

    resp = client.post("/api/v1/admin/users/bookkeeper/password",
                       json={"password": "pwned1234abcd"})
    assert resp.status_code == 502
    assert "not in the 'editors' group" in resp.json()["detail"]
    by_name = {u["username"]: u for u in truenas.state["users"]}
    assert "password" not in by_name["bookkeeper"]

    # ...and a real editor still works
    resp = client.post("/api/v1/admin/users/jsmith/password", json={"password": "knownpw1234567"})
    assert resp.status_code == 200
    by_name = {u["username"]: u for u in truenas.state["users"]}
    assert by_name["jsmith"]["password"] == "knownpw1234567"


def test_set_password_rejects_a_bad_username_charset_before_touching_truenas(env):
    client, truenas, _syncthing = env
    _seed_editors_group_and_system_accounts(truenas)
    as_user(client, "owen")
    resp = client.post("/api/v1/admin/users/Not%20A%20Name!/password",
                       json={"password": "whatever12345"})
    assert resp.status_code == 422
    # the htmx form path validates too (see the ui.py call site)
    resp = client.post("/partials/admin/users/password",
                       data={"username": "root", "password": "pwned1234abcd"})
    assert resp.status_code == 200
    assert "system account" in resp.text
    resp = client.post("/partials/admin/users/password",
                       data={"username": "Not A Name!", "password": "pwned1234abcd"})
    assert resp.status_code == 200
    assert "username must start with a letter" in resp.text
    assert all("password" not in u for u in truenas.state["users"])


def test_admin_users_page_renders_for_admin(env):
    client, _truenas, _syncthing = env
    as_user(client, "owen")
    page = client.get("/admin/users")
    assert page.status_code == 200
    assert "[ USERS ]" in page.text
    assert "[ DEVICES AWAITING APPROVAL ]" in page.text


# -- htmx partials (ui.py) -- these wrap blocking TrueNAS/Syncthing calls in
# run_in_threadpool (see the ui.py blocking-handlers finding); these tests
# confirm that change didn't break the request/response contract.


def test_partial_create_user_end_to_end(env):
    client, truenas, _syncthing = env
    as_user(client, "owen")
    resp = client.post("/partials/admin/users/create", data={
        "username": "newbie",
        "ssh_pubkey": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA newbie@laptop",
        "full_name": "New Editor",
        "password": "hunter2horse",
    })
    assert resp.status_code == 200
    assert "newbie" in resp.text
    [user] = [u for u in truenas.state["users"] if u["username"] == "newbie"]
    assert user["sshpubkey"].startswith("ssh-ed25519")


def test_partial_create_user_requires_admin(env):
    client, _truenas, _syncthing = env
    as_user(client, "jsmith")
    resp = client.post("/partials/admin/users/create", data={
        "username": "newbie", "ssh_pubkey": "ssh-ed25519 AAAA newbie@laptop",
    })
    assert resp.status_code == 403


def test_partial_create_user_bad_key_shows_error(env):
    client, _truenas, _syncthing = env
    as_user(client, "owen")
    resp = client.post("/partials/admin/users/create", data={
        "username": "newbie", "ssh_pubkey": "not a key at all",
    })
    assert resp.status_code == 200
    assert "does not look like an OpenSSH public key" in resp.text


def test_partial_set_password_end_to_end(env):
    client, truenas, _syncthing = env
    truenas.state["groups"].append({"id": 111, "group": "editors", "gid": 3001})
    truenas.state["users"].append({
        "id": 5, "uid": 3010, "username": "jsmith", "full_name": "jsmith",
        "home": "/mnt/tank/TheCreatorsPool/homes/jsmith", "group": {"id": 111}, "groups": [111],
        "sshpubkey": "ssh-ed25519 AAAA", "smb": True, "locked": False, "password_disabled": False,
    })
    as_user(client, "owen")
    resp = client.post("/partials/admin/users/password",
                       data={"username": "jsmith", "password": "knownpw1234567"})
    assert resp.status_code == 200
    [user] = [u for u in truenas.state["users"] if u["username"] == "jsmith"]
    assert user["password"] == "knownpw1234567"


def test_partial_approve_device_end_to_end(env):
    client, _truenas, syncthing = env
    # A real device ID is base32 minus 0/1/8/9 -- the partial shape-checks it
    # the same way the JSON API twin does (DASH-1).
    new_id = "NEWDEVX-NEWDEVX-NEWDEVX-NEWDEVX-NEWDEVX-NEWDEVX-NEWDEVX-NEWDEVX"
    syncthing.state["pending_devices"] = {new_id: {"name": "", "address": "100.9.9.9:22000"}}
    as_user(client, "owen")
    resp = client.post("/partials/admin/users/approve",
                       data={"device_id": new_id, "username": "newbie"})
    assert resp.status_code == 200
    added = next(d for d in syncthing.state["devices"] if d["deviceID"] == new_id)
    assert added["name"] == "newbie"
    # An admin naming the device is the strongest evidence 'newbie' is a real
    # editor account; without the row enforce reads the device as UNMAPPED and
    # shares it nothing (B16 / DASH-2).
    assert "newbie" in known_editors(client)


def test_partial_approve_shape_checks_the_device_id(env):
    """DASH-1: the partial is the only approve path a human uses, and it passed
    the pasted ID straight through -- a truncated paste came back as a generic
    Syncthing 502, and a well-formed-but-lowercased one created a device that
    can never connect."""
    client, _truenas, syncthing = env
    as_user(client, "owen")
    before = list(syncthing.state["devices"])

    resp = client.post("/partials/admin/users/approve",
                       data={"device_id": "NEWDEVX-NEWDEVX", "username": "newbie"})
    assert resp.status_code == 200
    assert "is not a Syncthing device ID" in resp.text
    assert syncthing.state["devices"] == before          # nothing reached Syncthing
    assert "newbie" not in known_editors(client)

    # ...and a lowercased-but-valid paste is uppercased rather than refused,
    # exactly as normalize_device_id does for the JSON API.
    lower = "newdevx-newdevx-newdevx-newdevx-newdevx-newdevx-newdevx-newdevx"
    resp = client.post("/partials/admin/users/approve",
                       data={"device_id": lower, "username": "newbie"})
    assert resp.status_code == 200
    added = next(d for d in syncthing.state["devices"] if d["deviceID"] == lower.upper())
    assert added["name"] == "newbie"


def test_partial_create_user_records_the_known_editor(env):
    """DASH-2: the api.py twin has recorded the account since the B16 fix; the
    htmx partial the Users page actually posts to did not, so an editor created
    through the UI got no known_editors row and enforce never shared them
    anything."""
    client, truenas, _syncthing = env
    as_user(client, "owen")
    # (the live collector seeds its own known editors off the fake Syncthing
    # config in the background, so only 'newbie' is asserted on here)
    assert "newbie" not in known_editors(client)
    resp = client.post("/partials/admin/users/create", data={
        "username": "newbie",
        "ssh_pubkey": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA newbie@laptop",
    })
    assert resp.status_code == 200
    assert any(u["username"] == "newbie" for u in truenas.state["users"])
    assert "newbie" in known_editors(client)


def test_partial_create_user_records_nothing_when_truenas_refuses(env):
    client, _truenas, _syncthing = env
    as_user(client, "owen")
    resp = client.post("/partials/admin/users/create", data={
        "username": "newbie", "ssh_pubkey": "not a key at all",
    })
    assert resp.status_code == 200
    assert "newbie" not in known_editors(client)


def test_truenas_not_configured_is_read_only(tmp_path, syncthing):
    settings = Settings(
        db_path=str(tmp_path / "noadmin.db"),
        session_secret=SECRET,
        admin_users=frozenset({"owen"}),
        syncthing_url=syncthing.url,
        syncthing_api_key="fake-key",
        # truenas_pw left blank -- feature should degrade, not crash
    )
    with TestClient(create_app(settings)) as client:
        as_user(client, "owen")
        body = client.get("/api/v1/admin/users").json()
        assert body["truenas_configured"] is False
        assert body["editors"] == []
