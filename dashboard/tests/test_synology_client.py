"""The DSM client itself (SYNOLOGY_PORT_PLAN.md WP2), against an HTTP fake of
the DSM web API built from `docs/synology-spikes-2026-08-17.md`.

test_nas_backend.py pins that the admin call sites work through ANY backend.
This file pins the things that are true of DSM specifically -- and every one
of them is a trap that was measured on real hardware, not a hypothetical:
login version 7, JSON booleans, a group-add that lies, and an SSH command that
must never chmod a home or anything under a shared folder.
"""
from __future__ import annotations

import logging

import pytest
import requests

from ccsync_dashboard.nas import NasError
from ccsync_dashboard.nas import synology as syn
from ccsync_dashboard.nas.synology import SynologyClient

from fake_synology import FakeDSM, unwrap_sudo_sh

GOOD_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIexample newbie@laptop"


@pytest.fixture
def dsm():
    fake = FakeDSM().start()
    yield fake
    fake.stop()


def client_for(fake, **kwargs) -> SynologyClient:
    return SynologyClient("dsm.example", "ccsync", "fake-pw", False,
                          base_url=fake.base_url, ssh_runner=fake.ssh, **kwargs)


def logins(fake) -> list[dict]:
    return [r["params"] for r in fake.state["requests"]
            if r["params"].get("api") == "SYNO.API.Auth"
            and r["params"].get("method") == "login"]


def calls(fake, api: str, method: str) -> list[dict]:
    return [r["params"] for r in fake.state["requests"]
            if r["params"].get("api") == api and r["params"].get("method") == method]


# ------------------------------------------------------------------ the session


def test_login_uses_version_7_and_a_named_session(dsm):
    with client_for(dsm) as client:
        client.ping()
    sent = logins(dsm)[0]
    assert sent["version"] == "7"
    assert sent["session"] == "ccsync"
    assert sent["format"] == "sid"
    # posted, not in a query string: DSM logs request lines for GETs
    assert all(r["post"] for r in dsm.state["requests"]
               if r["params"].get("method") == "login")


def test_a_dsm_whose_auth_tops_out_at_6_is_refused_before_anything_is_created(dsm):
    """Spike 3.1: a v6 sid reads fine and is refused on every mutation with
    105, so a box like this would produce accounts that exist, are in no group
    and have no key. Refuse it at the shape check instead."""
    dsm.state["auth_max_version"] = 6
    with pytest.raises(NasError) as exc:
        client_for(dsm).create_or_update_editor("newbie", GOOD_KEY)
    assert "SYNO.API.Auth" in str(exc.value) and "version 7" in str(exc.value)
    assert dsm.state["users"] == [u for u in dsm.state["users"] if u["name"] != "newbie"]
    assert not logins(dsm)


def test_a_v6_login_would_get_105_and_the_message_says_why(dsm, monkeypatch):
    """The trap itself, reproduced end to end: with the login version forced
    down, the fake DSM hands out a sid that lists users happily and refuses
    every mutation -- and the error a future maintainer sees names the cause."""
    monkeypatch.setattr(syn, "LOGIN_VERSION", 6)
    client = client_for(dsm)
    assert client.find_user("Cablewrap") is not None          # reads work at v6
    with pytest.raises(NasError) as exc:
        client.ensure_editors_group()                          # mutations do not
    assert "105" in str(exc.value)
    assert "SYNO.API.Auth" in str(exc.value)


def test_a_missing_api_is_named_rather_than_guessed_at(dsm):
    dsm.state["hide_apis"] = {"SYNO.Core.Group.Member"}
    with pytest.raises(NasError) as exc:
        client_for(dsm).list_editors()
    assert "SYNO.Core.Group.Member" in str(exc.value)
    assert "not offered" in str(exc.value)


def test_an_expired_sid_is_retried_once_not_reported(dsm):
    """119 is normal: DSM ages sessions out. The dashboard must not show an
    admin a "session expired" banner for it."""
    client = client_for(dsm)
    client.ping()
    dsm.state["sids"].clear()                                  # DSM aged it out
    assert client.find_group("administrators")["gid"] == 101
    assert len(logins(dsm)) == 2


def test_close_logs_the_session_out(dsm):
    client = client_for(dsm)
    client.ping()
    assert dsm.state["sids"]
    client.close()
    assert dsm.state["sids"] == {}


def test_bad_credentials_are_a_clear_refusal(dsm):
    client = SynologyClient("dsm.example", "ccsync", "wrong-pw", False, base_url=dsm.base_url)
    with pytest.raises(NasError) as exc:
        client.ping()
    assert "invalid account or password" in str(exc.value)


# -------------------------------------------------------------- serialisation


def test_python_bools_never_reach_dsm_as_True(dsm):
    """Error 3103, and the reason `_param` exists: requests renders a Python
    bool as "True", DSM's parser wants JSON, and the error names no parameter.
    """
    assert (syn._param(True), syn._param(False)) == ("true", "false")
    assert syn._param(["a", "b"]) == '["a", "b"]'
    assert syn._param(7) == "7"

    client_for(dsm).create_or_update_editor("newbie", GOOD_KEY, "New Editor")
    created = calls(dsm, "SYNO.Core.User", "create")[0]
    assert created["cannot_chg_passwd"] == "false"
    assert created["password_never_expire"] == "true"
    assert "True" not in created.values() and "False" not in created.values()


def test_the_fake_dsm_rejects_a_python_bool_the_way_dsm_does(dsm):
    """Guards the guard: if the fake ever stopped reproducing 3103, the test
    above would pass against a client that had regressed."""
    resp = requests.get(f"{dsm.base_url}/entry.cgi", params={
        "api": "SYNO.Core.User", "method": "list", "version": 1, "type": "local",
        "notify_by_email": "True"}).json()
    assert resp == {"error": {"code": 3103}, "success": False}


# -------------------------------------------------------------- groups + users


def test_the_editors_group_is_created_with_dsms_gid_and_read_back(dsm):
    client = client_for(dsm)
    assert client.find_group("editors") is None
    assert client.ensure_editors_group() == (65536, 65536)     # DSM starts local gids at 65536
    assert client.ensure_editors_group() == (65536, 65536)     # idempotent
    assert len(calls(dsm, "SYNO.Core.Group", "create")) == 1


def test_find_group_uses_get_because_list_carries_no_gid(dsm):
    """Measured 2026-08-17: SYNO.Core.Group list returns name+description only,
    with or without `additional`. A client that read gids off `list` would
    silently see None."""
    client = client_for(dsm)
    assert client.find_group("administrators") == {
        "id": 101, "gid": 101, "group": "administrators", "description": ""}
    assert calls(dsm, "SYNO.Core.Group", "get")
    assert not calls(dsm, "SYNO.Core.Group", "list")


def test_creating_an_editor_creates_the_account_the_group_and_the_key(dsm):
    client = client_for(dsm)
    result = client.create_or_update_editor("newbie", GOOD_KEY, "New Editor")

    assert result["created"] is True
    assert result["username"] == "newbie" and result["home_ok"] is True
    assert result["warnings"] == []
    assert result["uid"] == 1030                               # DSM's next local uid
    assert dsm.state["members"]["editors"] == ["newbie"]
    assert dsm.state["authorized_keys"]["newbie"] == GOOD_KEY
    # the account is nologin and its primary group is `users`: DSM's defaults,
    # and the two things WP2 relies on rather than sets
    assert "newbie" in dsm.state["members"]["users"]

    again = client.create_or_update_editor("newbie", GOOD_KEY, "New Editor")
    assert again["created"] is False and again["warnings"] == []
    assert len(calls(dsm, "SYNO.Core.User", "create")) == 1


def test_group_membership_is_read_back_and_a_silent_no_op_becomes_a_warning(dsm):
    """SYNO.Core.Group.Member add answers success:true whatever you send it.
    The read-back is the only evidence it did anything -- without it the
    dashboard would report a fleet member who is in no group and can reach
    nothing."""
    dsm.state["member_add_param"] = "members"                  # DSM ignoring our `name`
    result = client_for(dsm).create_or_update_editor("newbie", GOOD_KEY)
    assert result["created"] is True
    assert "user is not a member of group 'editors'" in result["warnings"]
    assert dsm.state["members"].get("editors") == []
    # and the client did send the parameter DSM actually reads
    assert calls(dsm, "SYNO.Core.Group.Member", "add")[0]["name"] == '["newbie"]'


def test_list_editors_returns_the_rows_the_admin_page_renders(dsm):
    client = client_for(dsm)
    client.create_or_update_editor("newbie", GOOD_KEY, "New Editor")
    client.create_or_update_editor("second", GOOD_KEY)
    rows = client.list_editors()

    assert {r["username"] for r in rows} == {"newbie", "second"}
    row = next(r for r in rows if r["username"] == "newbie")
    # exactly the keys api.build_admin_users_view reads off a TrueNAS row
    assert set(row) >= {"username", "uid", "full_name", "smb", "sshpubkey", "home", "locked"}
    assert row["full_name"] == "New Editor"
    assert row["home"] == "/var/services/homes/newbie"
    assert row["locked"] is False and row["smb"] is True
    assert row["sshpubkey"]                                    # a key IS installed
    assert row["groups"] == ["editors"]


def test_list_editors_reports_no_key_when_ssh_is_unavailable_but_still_lists(dsm):
    """An admin page that 500s because the container has no SSH credentials
    would be a worse trade than one that cannot say whether a key is there."""
    client = client_for(dsm)
    client.create_or_update_editor("newbie", GOOD_KEY)
    dsm.state["ssh_available"] = False
    rows = client_for(dsm).list_editors()
    assert [r["username"] for r in rows] == ["newbie"]
    assert rows[0]["sshpubkey"] is None


def test_list_editors_is_empty_not_an_error_before_the_group_exists(dsm):
    assert client_for(dsm).list_editors() == []


def test_is_editor_answers_from_the_users_group_list(dsm):
    client = client_for(dsm)
    client.create_or_update_editor("newbie", GOOD_KEY)
    assert client.is_editor("newbie") is True
    assert client.is_editor("cablewrap") is False              # exists, not an editor
    assert client.is_editor("nosuchuser") is False
    assert client.is_editor("admin") is False                  # built-in, never
    assert client.is_editor("Robert'); DROP TABLE--") is False  # charset gate


def test_an_unreachable_dsm_raises_rather_than_answering_not_an_editor(dsm):
    """/api/v1/verify must fail closed BUT retryable: "we could not ask" is
    never "no"."""
    client = client_for(dsm)
    client.ping()
    dsm.stop()
    with pytest.raises(NasError):
        client.is_editor("newbie")


# ------------------------------------------------------------------- refusals


@pytest.mark.parametrize("username, fragment", [
    ("admin", "built-in"),
    ("guest", "built-in"),
    ("root", "built-in"),
    ("sc-jellyfin", "package account"),
    ("Cablewrap", "must start with a letter"),   # charset gate catches the capital
])
def test_create_refuses_builtin_and_package_accounts(dsm, username, fragment):
    with pytest.raises(NasError) as exc:
        client_for(dsm).create_or_update_editor(username, GOOD_KEY)
    assert fragment in str(exc.value)
    assert not calls(dsm, "SYNO.Core.User", "create")


def test_create_refuses_to_adopt_an_existing_non_editor(dsm):
    dsm.state["users"].append({"name": "bookkeeper", "uid": 1040, "description": "",
                               "email": "", "expired": "normal"})
    with pytest.raises(NasError) as exc:
        client_for(dsm).create_or_update_editor("bookkeeper", GOOD_KEY)
    assert "not in the 'editors' group" in str(exc.value)
    assert not calls(dsm, "SYNO.Core.Group.Member", "add")


def test_create_refuses_a_uid_outside_dsms_local_range(dsm):
    """Below 1024 is a system account; 170000+ is a package's (spike 7).
    Neither is ever an editor, whatever group it happens to be in."""
    dsm.state["groups"].append({"name": "editors", "gid": 65536})
    for uid in (0, 1023, 187774):
        name = f"weird{uid}"
        dsm.state["users"].append({"name": name, "uid": uid, "description": "",
                                   "email": "", "expired": "normal"})
        dsm.state["members"].setdefault("editors", []).append(name)
        with pytest.raises(NasError) as exc:
            client_for(dsm).create_or_update_editor(name, GOOD_KEY)
        assert "system or package account" in str(exc.value)


def test_set_password_carries_the_same_refusals(dsm):
    """Without them, POST /admin/users/admin/password would set the DSM
    ADMINISTRATOR's password straight through this method."""
    client = client_for(dsm)
    with pytest.raises(NasError, match="built-in"):
        client.set_known_password("admin", "pwned12345")
    with pytest.raises(NasError, match="no such user"):
        client.set_known_password("nobody", "pwned12345")
    assert not calls(dsm, "SYNO.Core.User", "set")

    client.create_or_update_editor("newbie", GOOD_KEY)
    client.set_known_password("newbie", "hunter2horse")
    assert next(u for u in dsm.state["users"]
                if u["name"] == "newbie")["password"] == "hunter2horse"


def test_delete_user_is_guarded_to_ccsync_prefixed_test_accounts(dsm):
    client = client_for(dsm)
    client.create_or_update_editor("newbie", GOOD_KEY)
    with pytest.raises(NasError, match="ccsync_-prefixed"):
        client._delete_user("newbie")
    client.create_or_update_editor("ccsync_c", GOOD_KEY)
    client._delete_user("ccsync_c")
    assert client.find_user("ccsync_c") is None
    # a bare string is DSM error 3101 -- the array is not optional
    assert calls(dsm, "SYNO.Core.User", "delete")[0]["name"] == '["ccsync_c"]'


# ------------------------------------------------------------- the SSH half


def test_the_key_install_command_touches_only_dot_ssh(dsm):
    """Spike 1: chmod DELETES a Synology ACL, and DSM's sftp runs with umask
    000 -- so a chmod on a home or anywhere under a shared folder strips
    inheritance and leaves new files world-writable. This asserts the shape of
    the command, because by the time it has run on a customer's NAS it is too
    late."""
    client_for(dsm).create_or_update_editor("newbie", GOOD_KEY, "New Editor")
    command = dsm.state["ssh_commands"][-1]
    script = unwrap_sudo_sh(command)

    assert command.startswith("sudo -S -p '' /bin/sh -c ")   # password on stdin
    assert "export PATH=/usr/syno/bin:/usr/syno/sbin:/usr/local/bin:$PATH" in script
    for chmod in ('chmod 700 "$home/.ssh"', 'chmod 600 "$home/.ssh/authorized_keys"'):
        assert chmod in script
    # every chmod/chown in the script is scoped to .ssh, never the home itself
    for line in script.splitlines():
        if line.strip().startswith(("chmod", "chown")):
            assert ".ssh" in line, line
            assert not line.rstrip().endswith('"$home"'), line
    # nothing under a shared folder is touched at all -- that is where a chmod
    # would destroy an ACL (spike 1); homes are reached by their /var symlink
    assert "/volume" not in script
    assert script.count("/var/services/homes/newbie") >= 1
    # tmp+mv, so a half-written file is never what sshd reads
    assert ".authorized_keys.ccsync" in script and "mv -f" in script
    # and the verification is a read-back, not an exit code
    assert "stat -c '%a %U'" in script


def test_the_nas_password_goes_on_stdin_and_never_into_argv(dsm):
    client_for(dsm).create_or_update_editor("newbie", GOOD_KEY)
    assert all("fake-pw" not in c for c in dsm.state["ssh_commands"])
    assert dsm.state["ssh_stdin"][-1] == "fake-pw\n"


def test_a_home_sshd_will_refuse_is_reported_not_chmodded_away(dsm):
    """StrictModes refusals are logged NOWHERE by DSM (spike 2) -- the editor
    just sees "Authentication failed". So the client says so itself, and tells
    the operator to repair the ACL rather than chmod (which would make it
    worse)."""
    client = client_for(dsm)
    dsm.state["home_modes"]["newbie"] = "777"
    result = client.create_or_update_editor("newbie", GOOD_KEY)
    assert result["home_ok"] is False
    assert any("StrictModes" in w and "do NOT chmod" in w for w in result["warnings"])


def test_a_missing_home_names_the_user_home_service(dsm):
    client = client_for(dsm)
    dsm.state["missing_homes"] = {"newbie"}
    result = client.create_or_update_editor("newbie", GOOD_KEY)
    assert result["created"] is True and result["home_ok"] is False
    assert any("User Home service" in w for w in result["warnings"])


def test_an_ssh_failure_is_a_warning_not_a_lost_account(dsm):
    """The account exists and is in `editors` by then; failing the whole call
    would leave the dashboard's editors table and the NAS disagreeing."""
    dsm.state["ssh_available"] = False
    result = client_for(dsm).create_or_update_editor("newbie", GOOD_KEY)
    assert result["created"] is True and result["home_ok"] is False
    assert any("could not install the SSH key" in w for w in result["warnings"])
    assert dsm.state["members"]["editors"] == ["newbie"]


def test_missing_paramiko_names_the_extra_to_install(dsm, monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "paramiko", None)
    client = SynologyClient("dsm.example", "ccsync", "fake-pw", False, base_url=dsm.base_url)
    result = client.create_or_update_editor("newbie", GOOD_KEY)
    assert result["created"] is True
    assert any("paramiko" in w and "synology" in w for w in result["warnings"])


# --------------------------------------------------------------- host keys


def test_a_pinned_host_key_is_required_to_match(dsm, monkeypatch):
    paramiko = pytest.importorskip("paramiko")
    key = paramiko.RSAKey.generate(2048)
    line = f"{key.get_name()} {key.get_base64()} nas"
    monkeypatch.setenv("DASH_NAS_SSH_HOSTKEY", line)

    seen = {}
    monkeypatch.setattr(paramiko.SSHClient, "connect",
                        lambda self, **kw: seen.update(kw) or None)
    client = SynologyClient("dsm.example", "ccsync", "fake-pw", False, base_url=dsm.base_url)
    ssh = client._ssh_client()

    assert isinstance(ssh._policy, paramiko.RejectPolicy)
    assert ssh.get_host_keys().lookup("dsm.example")[key.get_name()] == key
    assert seen["port"] == 22 and seen["look_for_keys"] is False
    # bare base64 (no type prefix) is accepted too -- that is what
    # `ssh-keyscan | awk '{print $3}'` hands an operator
    monkeypatch.setenv("DASH_NAS_SSH_HOSTKEY", key.get_base64())
    assert syn._parse_host_key(key.get_base64()) == key


def test_an_unpinned_host_key_is_trust_on_first_use_and_says_so(dsm, monkeypatch, caplog):
    paramiko = pytest.importorskip("paramiko")
    monkeypatch.delenv("DASH_NAS_SSH_HOSTKEY", raising=False)
    monkeypatch.setattr(paramiko.SSHClient, "connect", lambda self, **kw: None)
    client = SynologyClient("dsm.example", "ccsync", "fake-pw", False, base_url=dsm.base_url)
    with caplog.at_level(logging.WARNING, logger="ccsync.dashboard.nas.synology"):
        ssh = client._ssh_client()
    assert isinstance(ssh._policy, paramiko.AutoAddPolicy)
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "not pinned" in logged.lower() and "DASH_NAS_SSH_HOSTKEY" in logged


def test_a_junk_host_key_pin_is_refused_before_connecting(dsm, monkeypatch):
    pytest.importorskip("paramiko")
    monkeypatch.setenv("DASH_NAS_SSH_HOSTKEY", "not-base64-at-all!!")
    client = SynologyClient("dsm.example", "ccsync", "fake-pw", False, base_url=dsm.base_url)
    with pytest.raises(NasError, match="DASH_NAS_SSH_HOSTKEY"):
        client._ssh_client()


def test_a_non_default_ssh_port_is_spelled_the_known_hosts_way():
    assert syn._hostkey_name("nas", 22) == "nas"
    assert syn._hostkey_name("nas", 2222) == "[nas]:2222"


def test_the_ssh_port_comes_from_the_environment(monkeypatch):
    """Not from Settings: the factory builds every backend from the same five
    values, and a DSM on a non-22 SSH port must not need a new one."""
    monkeypatch.setenv("DASH_NAS_SSH_PORT", "2222")
    assert SynologyClient("h", "u", "p", False).ssh_port == 2222
    monkeypatch.setenv("DASH_NAS_SSH_PORT", "nonsense")
    assert SynologyClient("h", "u", "p", False).ssh_port == 22


# ------------------------------------------------------------------- services


def test_sftp_enabled_reads_the_service_state(dsm):
    """With SFTP off, key auth SUCCEEDS and the channel is then closed with no
    server-side log at all -- indistinguishable from a denied SYNO.SFTP
    privilege (spike 2). Worth a checklist item, hence a method."""
    client = client_for(dsm)
    assert client.sftp_enabled() is True
    dsm.state["sftp"]["enable"] = False
    assert client.sftp_enabled() is False
