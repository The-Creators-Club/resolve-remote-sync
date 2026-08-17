"""Credentials, host-key trust, editor accounts and per-project ACLs.

docs/COMMERCIAL_READINESS.md items 6 (findings H2/H3) and 7 (H4), implemented
2026-08-17. What these tests hold, in the order it would cost you:

  1. **An unknown SSH host key is a REFUSAL.** That channel carries the NAS
     admin password on its stdin and runs `sudo -S` with it, so "accept
     whatever answered on port 22" is a credential handed to the network. A
     pin, or a key recorded on a deliberate first use, or nothing happens.
  2. **A key that CHANGED is a refusal too**, with both fingerprints named --
     the one state where carrying on is never right.
  3. **The container gets a scoped API key, not the admin password.** The
     dashboard is reachable by every editor and mounts three other apps
     in-process; `docker inspect` on it used to hand over a root-equivalent
     NAS login.
  4. **Editors are SFTP-only by default, and the manifest agrees.** A nologin
     account cannot run md5sum, so a manifest still saying `shell_type = unix`
     is a fleet whose every checksum fails -- the two must never be able to
     disagree.
  5. **Per-project mode protects the PARENT.** Deleting a directory needs
     write on the directory above it, so per-project groups without the sticky
     bit on the containers would change nothing about the finding they exist
     for.

The site fixture (tests/fixtures/site.toml) deliberately pins
`editor_shell = "shell"`: it stands in for THIS fleet, which still has bash
editors. The default is "sftp-only", exercised here by reloading with a site
that does not say.
"""
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
import install_dashboard_app as ida  # noqa: E402
import setup_tree  # noqa: E402
from backends.truenas import TrueNASBackend  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# A real ed25519 host key, in the two forms this code has to accept.
SAMPLE_KEYTYPE = "ssh-ed25519"


def _sample_key(seed: int = 1):
    """A deterministic paramiko Ed25519 host key, without touching the network."""
    import paramiko
    from cryptography.hazmat.primitives.asymmetric import ed25519

    private = ed25519.Ed25519PrivateKey.from_private_bytes(bytes([seed]) * 32)
    key = paramiko.Ed25519Key.from_private_key(_pem(private))
    return key


def _pem(private):
    import io

    from cryptography.hazmat.primitives import serialization

    data = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return io.StringIO(data.decode())


@pytest.fixture
def isolated_trust(monkeypatch, tmp_path):
    """A clean host-key world: no pin, no TOFU, an empty known_hosts."""
    monkeypatch.setattr(common, "_HOST_KEY_PIN", "", raising=False)
    monkeypatch.setattr(common, "_TRUST_ON_FIRST_USE", False, raising=False)
    monkeypatch.delenv("CCSYNC_SSH_HOSTKEY", raising=False)
    monkeypatch.delenv(common.TOFU_ENV, raising=False)
    monkeypatch.setenv(common.KNOWN_HOSTS_ENV, str(tmp_path / "known_hosts"))
    monkeypatch.setattr(sys, "argv", ["pytest"])
    return tmp_path / "known_hosts"


# ---------------------------------------------------------------------------
# 1-2. SSH host-key trust (item 6, finding H2)
# ---------------------------------------------------------------------------

def test_an_unknown_host_key_is_refused_and_says_how_to_fix_it(isolated_trust):
    with pytest.raises(common.EnvError) as excinfo:
        common.ssh_client("nas.example", "admin", "pw")
    message = str(excinfo.value)
    assert "ssh-keyscan" in message, "the refusal must give the command that fixes it"
    assert "ssh_hostkey" in message
    assert "--trust-host-key-on-first-use" in message
    assert str(isolated_trust) in message


def test_the_refusal_happens_before_anything_connects(isolated_trust, monkeypatch):
    """No socket, no password: the refusal is a configuration answer."""
    import paramiko

    def explode(*a, **kw):
        raise AssertionError("connect() must not be reached for an untrusted host")

    monkeypatch.setattr(paramiko.SSHClient, "connect", explode)
    with pytest.raises(common.EnvError):
        common.ssh_client("nas.example", "admin", "pw")


def test_trust_on_first_use_records_the_key_and_prints_the_pin(isolated_trust,
                                                               monkeypatch, capsys):
    import paramiko

    key = _sample_key()

    def fake_connect(self, hostname, **kw):
        self._policy.missing_host_key(self, hostname, key)

    monkeypatch.setattr(paramiko.SSHClient, "connect", fake_connect)
    monkeypatch.setenv(common.TOFU_ENV, "1")
    common.ssh_client("nas.example", "admin", "pw")

    recorded = isolated_trust.read_text(encoding="utf-8")
    assert recorded.startswith("nas.example ssh-ed25519 ")
    err = capsys.readouterr().err
    assert "TRUSTED ON FIRST USE" in err
    assert 'ssh_hostkey = "ssh-ed25519 ' in err, (
        "the whole point of recording it is that the next run can be PINNED")


def test_a_recorded_key_is_enforced_not_re_trusted(isolated_trust, monkeypatch):
    """Second run: the policy must be RejectPolicy, not another blind add."""
    import paramiko

    key = _sample_key()
    isolated_trust.parent.mkdir(parents=True, exist_ok=True)
    isolated_trust.write_text(f"nas.example {key.get_name()} {key.get_base64()}\n",
                              encoding="utf-8")

    seen = {}

    def fake_connect(self, hostname, **kw):
        seen["policy"] = self._policy
        seen["known"] = self.get_host_keys().lookup(hostname)

    monkeypatch.setattr(paramiko.SSHClient, "connect", fake_connect)
    common.ssh_client("nas.example", "admin", "pw")
    assert isinstance(seen["policy"], paramiko.RejectPolicy)
    assert seen["known"] is not None


def test_a_changed_host_key_is_a_refusal_naming_both_fingerprints(isolated_trust,
                                                                  monkeypatch):
    import paramiko

    expected, offered = _sample_key(1), _sample_key(2)
    isolated_trust.write_text(
        f"nas.example {expected.get_name()} {expected.get_base64()}\n", encoding="utf-8")

    def fake_connect(self, hostname, **kw):
        raise paramiko.BadHostKeyException(hostname, offered, expected)

    monkeypatch.setattr(paramiko.SSHClient, "connect", fake_connect)
    with pytest.raises(common.EnvError) as excinfo:
        common.ssh_client("nas.example", "admin", "pw")
    message = str(excinfo.value)
    assert "CHANGED" in message
    assert common._fingerprint(expected) in message
    assert common._fingerprint(offered) in message
    assert "Nothing was sent" in message


def test_a_pin_still_wins_over_everything(isolated_trust, monkeypatch):
    import paramiko

    key = _sample_key()
    common.set_host_key_pin(f"{key.get_name()} {key.get_base64()}")
    try:
        seen = {}

        def fake_connect(self, hostname, **kw):
            seen["policy"] = self._policy

        monkeypatch.setattr(paramiko.SSHClient, "connect", fake_connect)
        common.ssh_client("nas.example", "admin", "pw")
        assert isinstance(seen["policy"], paramiko.RejectPolicy)
        assert not isolated_trust.exists(), "a pinned run must not write known_hosts"
    finally:
        common.set_host_key_pin("")


def test_the_pin_can_come_from_site_toml(monkeypatch):
    """[nas] ssh_hostkey, so a site configures it in the same file as the host."""
    monkeypatch.setattr(common, "_HOST_KEY_PIN", "", raising=False)
    monkeypatch.delenv("CCSYNC_SSH_HOSTKEY", raising=False)
    monkeypatch.setattr(common, "site_value",
                        lambda section, key, default="": (
                            "ssh-ed25519 AAAAC3PINNED" if (section, key) == ("nas", "ssh_hostkey")
                            else default))
    assert common.host_key_pin() == "ssh-ed25519 AAAAC3PINNED"


def test_the_tofu_flag_is_read_from_argv_too(monkeypatch):
    """Not every script routes its parsed args back into common; a flag that is
    honoured on one script and ignored on another is worse than no flag."""
    monkeypatch.setattr(common, "_TRUST_ON_FIRST_USE", False, raising=False)
    monkeypatch.delenv(common.TOFU_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", ["setup_tree.py", "--trust-host-key-on-first-use"])
    assert common.trust_on_first_use() is True


def test_every_script_with_host_key_also_offers_the_tofu_flag():
    import argparse

    ap = argparse.ArgumentParser()
    common.add_host_key_arg(ap)
    parsed = ap.parse_args(["--trust-host-key-on-first-use"])
    assert parsed.trust_host_key_on_first_use is True


# ---------------------------------------------------------------------------
# 3. TLS + scoped credentials (item 6, findings H2/H3)
# ---------------------------------------------------------------------------

def test_tls_off_is_allowed_but_never_silent(monkeypatch, capsys):
    monkeypatch.setattr(common, "_TLS_WARNED", set(), raising=False)
    monkeypatch.setenv("TRUENAS_VERIFY_SSL", "0")
    assert common.truenas_verify_ssl() is False
    err = capsys.readouterr().err
    assert "TLS certificate verification is OFF" in err
    assert "TRUENAS_VERIFY_SSL" in err


def test_a_ca_bundle_path_is_passed_through(monkeypatch):
    monkeypatch.setenv("TRUENAS_VERIFY_SSL", "/certs/nas-ca.pem")
    assert common.truenas_verify_ssl() == "/certs/nas-ca.pem"
    monkeypatch.setenv("TRUENAS_VERIFY_SSL", "1")
    assert common.truenas_verify_ssl() is True


def test_the_synology_tls_path_warns_the_same_way(monkeypatch, capsys):
    monkeypatch.setattr(common, "_TLS_WARNED", set(), raising=False)
    monkeypatch.delenv("SYNO_VERIFY_SSL", raising=False)
    monkeypatch.setenv("TRUENAS_VERIFY_SSL", "0")
    assert common.synology_verify_ssl() is False
    assert "DSM" in capsys.readouterr().err


def test_sudo_can_have_its_own_password(monkeypatch):
    monkeypatch.setenv("TRUENAS_PW", "login-pw")
    monkeypatch.delenv("TRUENAS_SUDO_PW", raising=False)
    assert common.nas_sudo_password(kind="truenas") == "login-pw"
    monkeypatch.setenv("TRUENAS_SUDO_PW", "sudo-pw")
    assert common.nas_sudo_password(kind="truenas") == "sudo-pw"


def test_the_rest_api_uses_a_bearer_key_when_one_is_configured(monkeypatch):
    calls = {}

    class FakeResp:
        status_code = 200

    def fake_request(method, url, **kw):
        calls.update(kw)
        calls["url"] = url
        return FakeResp()

    import requests

    monkeypatch.setattr(requests, "request", fake_request)
    monkeypatch.setenv("TRUENAS_API_KEY", "1-abcdef")
    monkeypatch.setenv("TRUENAS_VERIFY_SSL", "1")
    common.truenas_api("GET", "/user")
    assert calls["headers"] == {"Authorization": "Bearer 1-abcdef"}
    assert calls["auth"] is None, (
        "sending basic auth alongside the bearer makes a 401 ambiguous")
    assert calls["verify"] is True


def test_without_a_key_the_rest_api_still_uses_basic_auth(monkeypatch):
    calls = {}

    class FakeResp:
        status_code = 200

    import requests

    monkeypatch.setattr(requests, "request",
                        lambda method, url, **kw: (calls.update(kw), FakeResp())[1])
    monkeypatch.delenv("TRUENAS_API_KEY", raising=False)
    monkeypatch.setenv("TRUENAS_PW", "pw")
    common.truenas_api("GET", "/user")
    assert calls["headers"] is None
    assert calls["auth"] == ("truenas_admin", "pw")


def test_the_api_key_never_appears_in_the_printed_compose_body():
    """--dry-run prints the whole body on purpose; the key is a bearer
    credential and must be masked exactly as the password is."""
    assert "TRUENAS_API_KEY" in ida.SECRET_ENV_VARS
    body = ida.compose_config(
        8480, "/mnt/tank/apps/ccsync-dashboard", "http://gui:8384", "k", "t",
        truenas_api_key="1-secret")["services"]["dashboard"]["environment"]
    # compose_config itself is given whatever main() decided to pass; what this
    # pins is that BOTH names carry one value, so masking it once is enough.
    assert body["TRUENAS_API_KEY"] == body["DASH_NAS_API_KEY"] == "1-secret"


def test_the_scoped_key_allowlist_covers_exactly_what_the_dashboard_calls():
    import create_api_key

    resources = {(e["method"], e["resource"]) for e in create_api_key.ALLOWLIST}
    for wanted in (("GET", "/user"), ("POST", "/user"), ("PUT", "/user"),
                   ("GET", "/group"), ("POST", "/group"),
                   ("POST", "/filesystem/setperm"), ("GET", "/core/get_jobs")):
        assert wanted in resources
    # Nothing that could touch a pool, an app or the system.
    assert not any(r.startswith(("/pool", "/app", "/system", "/service"))
                   for _m, r in resources)


# ---------------------------------------------------------------------------
# 4. Editor accounts (item 7, finding H4)
# ---------------------------------------------------------------------------

@pytest.fixture
def sftp_only_site(monkeypatch):
    """common + install_dashboard_app as a site that took the default."""
    monkeypatch.setattr(common, "site_value", _site_override({("stack", "editor_shell"): ""}))
    return common


def _site_override(overrides):
    real = common.site_value

    def fake(section, key, default=""):
        if (section, key) in overrides:
            return overrides[(section, key)]
        return real(section, key, default)

    return fake


def test_the_default_editor_is_sftp_only(monkeypatch):
    monkeypatch.setattr(common, "site_value", _site_override({("stack", "editor_shell"): ""}))
    assert common.editor_shell_mode() == "sftp-only"
    assert common.editor_shell_is_sftp_only() is True


def test_this_fleets_fixture_still_says_shell():
    """The fixture stands in for a site that has not migrated; if this flips
    without a migration the fleet's checksums break on the next deploy."""
    assert common.editor_shell_mode() == "shell"


def test_an_unknown_editor_shell_mode_is_refused(monkeypatch):
    monkeypatch.setattr(common, "site_value",
                        _site_override({("stack", "editor_shell"): "sudo"}))
    with pytest.raises(common.EnvError) as excinfo:
        common.editor_shell_mode()
    assert "sftp-only" in str(excinfo.value)


def test_a_new_editor_gets_nologin_by_default(monkeypatch):
    monkeypatch.setattr(common, "site_value", _site_override({("stack", "editor_shell"): ""}))
    assert TrueNASBackend().editor_shell() == "/usr/sbin/nologin"


def test_a_site_that_asks_for_a_shell_still_gets_bash():
    assert TrueNASBackend().editor_shell() == "/usr/bin/bash"


def test_the_sshd_block_removes_the_login_without_chrooting():
    block = TrueNASBackend().sshd_editor_policy("editors")
    assert "Match Group editors" in block
    assert "ForceCommand internal-sftp" in block
    assert "PasswordAuthentication no" in block
    # Deliberate: sshd wants every chroot component root-owned and not
    # group-writable, and the tree root is <owner>:editors 2770 by design.
    assert "ChrootDirectory" not in block
    assert block.startswith(TrueNASBackend.SSHD_POLICY_BEGIN)
    assert block.endswith(TrueNASBackend.SSHD_POLICY_END)


def test_the_sshd_block_is_idempotent_and_keeps_other_auxiliary_parameters():
    backend = TrueNASBackend()
    seen = {}

    class Calls:
        def api(self, method, path, json_body=None, params=None, dry_run=False):
            seen.setdefault("methods", []).append((method, path))
            if method == "GET":
                return _Resp(200, {"options": seen.get("options", "ClientAliveInterval 30")})
            seen["options"] = json_body["options"]
            return _Resp(200, {})

        def ok(self, resp):
            return 200 <= resp.status_code < 300

    backend.calls = Calls()
    state, _ = backend.ensure_sshd_editor_policy("editors")
    assert state == "ok"
    assert "ClientAliveInterval 30" in seen["options"], (
        "an operator's own auxiliary parameters live in the same box")
    assert "Match Group editors" in seen["options"]
    # A second run must not append a second copy.
    state, _ = backend.ensure_sshd_editor_policy("editors")
    assert state == "unchanged"
    assert seen["options"].count("Match Group editors") == 1


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def test_the_manifest_publishes_none_when_editors_have_no_shell(monkeypatch):
    """The consequence is WIRED: a nologin editor cannot run md5sum, and a
    manifest still saying `unix` is a fleet whose every checksum fails."""
    monkeypatch.setattr(ida, "editor_shell_is_sftp_only", lambda: True)
    env = ida.site_env(8480, "/mnt/tank/pool/Creators_Club", "nas", "http://nas:8480")
    assert env["DASH_SITE_SFTP_SHELL_TYPE"] == "none"


def test_the_manifest_still_honours_the_site_when_editors_keep_a_shell(monkeypatch):
    monkeypatch.setattr(ida, "editor_shell_is_sftp_only", lambda: False)
    env = ida.site_env(8480, "/mnt/tank/pool/Creators_Club", "nas", "http://nas:8480")
    assert env["DASH_SITE_SFTP_SHELL_TYPE"] == "unix"


def test_the_printed_rclone_stanza_agrees_with_the_account(monkeypatch):
    import setup_editor_account as sea

    monkeypatch.setattr(sea, "editor_shell_is_sftp_only", lambda: True)
    assert "shell_type = none" in sea._rclone_stanza("jsmith", "nas.ts.net")
    monkeypatch.setattr(sea, "editor_shell_is_sftp_only", lambda: False)
    assert "shell_type = unix" in sea._rclone_stanza("jsmith", "nas.ts.net")


def test_a_key_can_be_taken_away_again():
    """Passphrase-less editor keys are only defensible if they are revocable."""
    backend = TrueNASBackend()
    sent = {}

    class Calls:
        def api(self, method, path, json_body=None, params=None, dry_run=False):
            sent["method"], sent["path"], sent["body"] = method, path, json_body
            return _Resp(200, {})

        def ok(self, resp):
            return True

    backend.calls = Calls()
    assert backend.revoke_editor_key(7, lock=True) == (True, "")
    assert sent == {"method": "PUT", "path": "/user/id/7",
                    "body": {"sshpubkey": "", "locked": True}}


# ---------------------------------------------------------------------------
# 5. Per-project ACLs (item 7, docs/TENANCY.md)
# ---------------------------------------------------------------------------

def test_shared_is_still_the_default():
    assert common.project_acl_mode() == "shared"


def test_a_project_group_name_is_derived_and_never_collides():
    assert common.project_group_name("2026-ff4-nuclear") == "proj-2026-ff4-nuclear"
    long_a = "a" * 40 + "-one"
    long_b = "a" * 40 + "-two"
    name_a, name_b = common.project_group_name(long_a), common.project_group_name(long_b)
    assert len(name_a) <= common.PROJECT_GROUP_MAXLEN
    assert name_a != name_b, (
        "two long slugs sharing a prefix must not land in one group -- that would "
        "silently re-share a project with the wrong people")
    assert common.project_group_name(long_a) == name_a, "and it must be stable"


def test_per_project_mode_owns_the_subtree_and_sticks_the_containers():
    lines = "\n".join(TrueNASBackend().set_tree_acl(
        "/mnt/tank/pool/Creators_Club/Projects/2026/FF4/Nuclear", "broll", "editors",
        project_group="proj-2026-ff4-nuclear",
        container_dirs=["/mnt/tank/pool/Creators_Club/Projects",
                        "/mnt/tank/pool/Creators_Club/Projects/2026"]))
    assert "chown -R 'broll:proj-2026-ff4-nuclear'" in lines
    assert "chmod 3770 '/mnt/tank/pool/Creators_Club/Projects'" in lines
    assert "chmod 3770 '/mnt/tank/pool/Creators_Club/Projects/2026'" in lines
    # The project itself stays 2770: editors on it must still be able to delete
    # each other's files INSIDE the project (that is what a shared cut is).
    assert "chmod 2770" in lines


def test_shared_mode_is_byte_for_byte_what_it_always_was():
    before = TrueNASBackend().set_tree_acl("/mnt/tank/pool/Creators_Club/Projects/x",
                                            "broll", "editors")
    assert any("chown -R 'broll:editors'" in line for line in before)
    assert not any("3770" in line for line in before)


def test_setup_tree_passes_the_containers_it_created(monkeypatch):
    script = setup_tree.build_remote_script(
        "/p/2026/FF4/Nuclear", "broll", "editors", slug="2026-ff4-nuclear",
        projects_root="/p", backend=TrueNASBackend(),
        project_group="proj-2026-ff4-nuclear")
    assert "chmod 3770 '/p'" in script
    assert "chmod 3770 '/p/2026'" in script
    assert "chmod 3770 '/p/2026/FF4'" in script
    assert "chown -R 'broll:proj-2026-ff4-nuclear'" in script


def test_without_a_project_group_setup_tree_is_unchanged():
    script = setup_tree.build_remote_script(
        "/p/2026/FF4/Nuclear", "broll", "editors", slug="2026-ff4-nuclear",
        projects_root="/p", backend=TrueNASBackend())
    assert "3770" not in script


# ---------------------------------------------------------------------------
# site.example.toml documents every new key (it is the file a customer edits)
# ---------------------------------------------------------------------------

def test_the_example_manifest_documents_the_new_keys():
    text = (Path(__file__).resolve().parents[2] / "site.example.toml").read_text(
        encoding="utf-8")
    for key in ("editor_shell", "project_acl", "gui_bind", "ssh_hostkey",
                "TRUENAS_API_KEY"):
        assert key in text, f"site.example.toml never mentions {key}"
