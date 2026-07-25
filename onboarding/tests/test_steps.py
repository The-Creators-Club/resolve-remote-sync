"""Unit tests for onboarding/steps.py -- the pure/injectable orchestration
logic behind the onboard.py wizard. No tkinter, no real network calls, no
winget/tailscale/powershell processes: everything network- or process-shaped
is injected as a fake. See onboarding/tests/conftest.py for how `steps` and
`ccsync_companion` get onto sys.path."""

from __future__ import annotations

import json
import subprocess
import urllib.error
from pathlib import Path

import pytest

import steps


class _FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, code, body=b""):
        super().__init__("http://x", code, "err", {}, None)
        self._body = body

    def read(self):
        return self._body


class _FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# -- verify_account ------------------------------------------------------


def test_verify_account_success_returns_username_token_report_token():
    def fake_post(url, data, headers, timeout):
        assert url == "http://dash.example.com/api/v1/verify"
        assert data == {"username": "jsmith", "password": "hunter2"}
        return {"ok": True, "username": "jsmith", "token": "v1.jsmith.999.abc", "report_token": "shared-secret"}

    result = steps.verify_account("http://dash.example.com", "jsmith", "hunter2", http_post=fake_post)
    assert result["ok"] is True
    assert result["username"] == "jsmith"
    assert result["token"] == "v1.jsmith.999.abc"
    assert result["report_token"] == "shared-secret"


def test_verify_account_returns_role_when_dashboard_sends_one():
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "alex", "token": "v1.alex.999.abc", "role": "base"}

    result = steps.verify_account("http://dash.example.com", "alex", "hunter2", http_post=fake_post)
    assert result["role"] == "base"


def test_verify_account_role_none_when_dashboard_omits_it():
    def fake_post(url, data, headers, timeout):
        return {"ok": True, "username": "jsmith", "token": "v1.jsmith.999.abc"}

    result = steps.verify_account("http://dash.example.com", "jsmith", "hunter2", http_post=fake_post)
    assert result["role"] is None


def test_verify_account_strips_trailing_slash_from_dashboard_url():
    seen = {}

    def fake_post(url, data, headers, timeout):
        seen["url"] = url
        return {"ok": True, "username": "jsmith", "token": "t", "report_token": ""}

    steps.verify_account("http://dash.example.com/", "jsmith", "x", http_post=fake_post)
    assert seen["url"] == "http://dash.example.com/api/v1/verify"


def test_verify_account_401_returns_ok_false():
    def fake_post(url, data, headers, timeout):
        raise _FakeHTTPError(401, json.dumps({"error": "bad username or password"}).encode())

    result = steps.verify_account("http://dash.example.com", "jsmith", "wrong", http_post=fake_post)
    assert result["ok"] is False
    assert "error" in result


def test_verify_account_429_throttled():
    def fake_post(url, data, headers, timeout):
        raise _FakeHTTPError(429, b"")

    result = steps.verify_account("http://dash.example.com", "jsmith", "x", http_post=fake_post)
    assert result["ok"] is False
    assert "throttled" in result["error"] or "too many" in result["error"]


def test_verify_account_503_not_configured():
    def fake_post(url, data, headers, timeout):
        raise _FakeHTTPError(503, b"")

    result = steps.verify_account("http://dash.example.com", "jsmith", "x", http_post=fake_post)
    assert result["ok"] is False
    assert "not available" in result["error"]


def test_verify_account_network_error_never_raises():
    def fake_post(url, data, headers, timeout):
        raise OSError("network unreachable")

    result = steps.verify_account("http://dash.example.com", "jsmith", "x", http_post=fake_post)
    assert result["ok"] is False
    assert "network unreachable" in result["error"]


def test_verify_account_blank_username_short_circuits_without_network_call():
    def fake_post(url, data, headers, timeout):
        raise AssertionError("must not be called for a blank username")

    result = steps.verify_account("http://dash.example.com", "", "x", http_post=fake_post)
    assert result["ok"] is False


def test_verify_account_blank_dashboard_url_short_circuits():
    def fake_post(url, data, headers, timeout):
        raise AssertionError("must not be called with no dashboard url")

    result = steps.verify_account("", "jsmith", "x", http_post=fake_post)
    assert result["ok"] is False


# -- tailscale_up ------------------------------------------------------


def test_tailscale_up_true_when_joined():
    def fake_run(cmd, **kwargs):
        assert cmd == ["tailscale", "status"]
        return _FakeResult(returncode=0, stdout="100.71.216.5   my-machine   user@   windows   -\n")

    assert steps.tailscale_up(run=fake_run) is True


def test_tailscale_up_false_when_logged_out():
    def fake_run(cmd, **kwargs):
        return _FakeResult(returncode=1, stdout="Logged out.\n")

    assert steps.tailscale_up(run=fake_run) is False


def test_tailscale_up_false_when_stopped():
    def fake_run(cmd, **kwargs):
        return _FakeResult(returncode=0, stdout="Tailscale is stopped.\n")

    assert steps.tailscale_up(run=fake_run) is False


def test_tailscale_up_false_on_exception():
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("tailscale.exe not found")

    assert steps.tailscale_up(run=fake_run) is False


# -- dashboard_reachable ------------------------------------------------------


def test_dashboard_reachable_true_on_success():
    def fake_get(url, timeout):
        assert url == "http://dash.example.com/api/v1/health"
        return {"syncthing_reachable": True, "version": "0.1.0"}

    assert steps.dashboard_reachable("http://dash.example.com", http_get=fake_get) is True


def test_dashboard_reachable_false_on_exception():
    def fake_get(url, timeout):
        raise OSError("timed out")

    assert steps.dashboard_reachable("http://dash.example.com", http_get=fake_get) is False


def test_dashboard_reachable_false_when_blank_url():
    def fake_get(url, timeout):
        raise AssertionError("must not be called with a blank url")

    assert steps.dashboard_reachable("", http_get=fake_get) is False


# -- dashboard_host ------------------------------------------------------


def test_dashboard_host_strips_scheme_and_port():
    assert steps.dashboard_host("http://100.71.216.3:8480") == "100.71.216.3"


def test_dashboard_host_https_no_port():
    assert steps.dashboard_host("https://dash.tailnet.ts.net") == "dash.tailnet.ts.net"


def test_dashboard_host_bare_hostname_fallback():
    assert steps.dashboard_host("100.71.216.3") == "100.71.216.3"


# -- parse_device_id ------------------------------------------------------


def test_parse_device_id_finds_valid_id():
    output = (
        "[ccsync] Bootstrap complete.\n\n"
        " Your Syncthing device ID is:\n\n"
        "     ABCDEFG-HIJKLMN-OPQRSTU-VWXYZ12-ABCDEFG-HIJKLMN-OPQRSTU-VWXYZ12\n"
    )
    device_id = steps.parse_device_id(output)
    assert device_id == "ABCDEFG-HIJKLMN-OPQRSTU-VWXYZ12-ABCDEFG-HIJKLMN-OPQRSTU-VWXYZ12"


def test_parse_device_id_none_when_absent():
    assert steps.parse_device_id("[ccsync] Bootstrap complete.\n") is None


def test_parse_device_id_none_for_empty_output():
    assert steps.parse_device_id("") is None


# -- ensure_ssh_key ------------------------------------------------------


def test_ensure_ssh_key_generates_when_missing(tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        # Simulate ssh-keygen actually writing the files.
        key_path = Path(cmd[cmd.index("-f") + 1])
        key_path.write_text("private-key-bytes")
        key_path.with_suffix(key_path.suffix + ".pub").write_text("ssh-ed25519 AAAA... onboarding")
        return _FakeResult(returncode=0)

    pub_path = steps.ensure_ssh_key(tmp_path, run=fake_run)
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == "ssh-keygen"
    assert "-t" in cmd and "ed25519" in cmd
    assert pub_path == tmp_path / "ccsync_ed25519.pub"
    assert pub_path.exists()


def test_ensure_ssh_key_skips_generation_when_present(tmp_path):
    (tmp_path / "ccsync_ed25519").write_text("existing-private-key")
    (tmp_path / "ccsync_ed25519.pub").write_text("ssh-ed25519 AAAA... existing")

    def fake_run(cmd, **kwargs):
        raise AssertionError("must not regenerate an existing key")

    pub_path = steps.ensure_ssh_key(tmp_path, run=fake_run)
    assert pub_path == tmp_path / "ccsync_ed25519.pub"
    assert pub_path.read_text() == "ssh-ed25519 AAAA... existing"


# -- read_pubkey ------------------------------------------------------


def test_read_pubkey_reads_and_strips(tmp_path):
    pub = tmp_path / "k.pub"
    pub.write_text("ssh-ed25519 AAAA...  \n")
    assert steps.read_pubkey(pub) == "ssh-ed25519 AAAA..."


def test_read_pubkey_missing_file_returns_empty_string(tmp_path):
    assert steps.read_pubkey(tmp_path / "nope.pub") == ""


# -- find_bootstrap_script / run_bootstrap ------------------------------------------------------


def test_find_bootstrap_script_dev_tree_fallback():
    # onboarding/../installer/windows_bootstrap.ps1 should exist in this repo.
    found = steps.find_bootstrap_script()
    assert found.name == "windows_bootstrap.ps1"
    assert found.exists()


def test_find_bootstrap_script_explicit_override(tmp_path):
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    assert steps.find_bootstrap_script(script) == script


def test_find_bootstrap_script_raises_when_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(steps, "__file__", str(tmp_path / "nowhere" / "steps.py"))
    with pytest.raises(FileNotFoundError):
        steps.find_bootstrap_script(tmp_path / "does-not-exist.ps1")


def test_run_bootstrap_builds_expected_powershell_command(tmp_path):
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeResult(returncode=0, stdout="[ccsync] Bootstrap complete.\n")

    exit_code, output = steps.run_bootstrap(
        editor_name="jsmith",
        dashboard_token="report-secret",
        tailnet_host="100.71.216.3",
        local_root=r"F:\Creators_Club",
        dashboard_url="http://100.71.216.3:8480",
        run=fake_run,
        script_path=script,
    )

    assert exit_code == 0
    assert "Bootstrap complete" in output
    cmd = captured["cmd"]
    assert cmd[0] == "powershell"
    assert "-ExecutionPolicy" in cmd and "Bypass" in cmd
    assert "-File" in cmd and str(script) in cmd
    assert "-TailnetHost" in cmd and "100.71.216.3" in cmd
    assert "-EditorName" in cmd and "jsmith" in cmd
    assert "-DashboardUrl" in cmd and "http://100.71.216.3:8480" in cmd
    assert "-DashboardToken" in cmd and "report-secret" in cmd
    assert "-LocalRoot" in cmd and r"F:\Creators_Club" in cmd


def test_run_bootstrap_omits_local_root_when_not_given(tmp_path):
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeResult(returncode=0, stdout="")

    steps.run_bootstrap(
        editor_name="jsmith",
        dashboard_token="report-secret",
        tailnet_host="100.71.216.3",
        run=fake_run,
        script_path=script,
    )
    assert "-LocalRoot" not in captured["cmd"]


def test_run_bootstrap_passes_companion_exe_source_when_given(tmp_path):
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    companion = tmp_path / "ccsync-companion.exe"
    companion.write_text("fake exe")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeResult(returncode=0, stdout="")

    steps.run_bootstrap(
        editor_name="jsmith",
        dashboard_token="report-secret",
        tailnet_host="100.71.216.3",
        companion_exe_source=companion,
        run=fake_run,
        script_path=script,
    )
    assert "-CompanionExeSource" in captured["cmd"] and str(companion) in captured["cmd"]


def test_run_bootstrap_omits_companion_exe_source_when_not_given(tmp_path):
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeResult(returncode=0, stdout="")

    steps.run_bootstrap(
        editor_name="jsmith", dashboard_token="x", tailnet_host="100.71.216.3",
        run=fake_run, script_path=script,
    )
    assert "-CompanionExeSource" not in captured["cmd"]


def test_run_bootstrap_propagates_nonzero_exit_code(tmp_path):
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")

    def fake_run(cmd, **kwargs):
        return _FakeResult(returncode=1, stdout="", stderr="something broke")

    exit_code, output = steps.run_bootstrap(
        editor_name="jsmith",
        dashboard_token="x",
        tailnet_host="100.71.216.3",
        run=fake_run,
        script_path=script,
    )
    assert exit_code == 1
    assert "something broke" in output


# -- write_identity / finalize_config_identity ------------------------------------------------------


def test_write_identity_writes_identity_json(tmp_path, monkeypatch):
    from ccsync_companion import config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    steps.write_identity("jsmith", "v1.jsmith.9999999999.deadbeef")

    identity_path = tmp_path / "identity.json"
    assert identity_path.exists()
    data = json.loads(identity_path.read_text())
    assert data["username"] == "jsmith"
    assert data["token"] == "v1.jsmith.9999999999.deadbeef"


def test_write_identity_persists_role(tmp_path, monkeypatch):
    from ccsync_companion import config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    steps.write_identity("alex", "v1.alex.9999999999.deadbeef", role="base")

    data = json.loads((tmp_path / "identity.json").read_text())
    assert data["role"] == "base"


def test_finalize_config_identity_rewrites_mismatched_editor_name(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'editor_name = "someoneelse"\n'
        'local_root = ""\n'
        'remote = "creators_club_sftp"\n'
        'remote_root = ""\n'
    )
    steps.finalize_config_identity("jsmith", config_path=config_path)
    text = config_path.read_text()
    assert 'editor_name = "jsmith"' in text


def test_finalize_config_identity_noop_when_already_matching(tmp_path):
    config_path = tmp_path / "config.toml"
    original = (
        'editor_name = "jsmith"\n'
        'local_root = ""\n'
        'remote = "creators_club_sftp"\n'
        'remote_root = ""\n'
    )
    config_path.write_text(original)
    steps.finalize_config_identity("jsmith", config_path=config_path)
    assert config_path.read_text() == original


def test_finalize_config_identity_tolerant_of_missing_file(tmp_path):
    # Must not raise even though the file doesn't exist.
    steps.finalize_config_identity("jsmith", config_path=tmp_path / "nope.toml")


# -- companion bundling -------------------------------------------------------

def test_find_companion_exe_explicit(tmp_path):
    exe = tmp_path / "ccsync-companion.exe"
    exe.write_bytes(b"MZ")
    assert steps.find_companion_exe(exe) == exe


def test_find_companion_exe_falls_back_to_dev_dist():
    # In the dev tree the built companion exe lives at companion/dist/;
    # find_companion_exe should locate it when no explicit path is given.
    found = steps.find_companion_exe()
    assert found.name == "ccsync-companion.exe" and found.exists()


def test_install_companion_copies_into_bin(tmp_path):
    src = tmp_path / "ccsync-companion.exe"
    src.write_bytes(b"MZ-companion")
    dest_dir = tmp_path / "bin"
    calls = []
    dest = steps.install_companion(dest_dir=dest_dir, src=src,
                                   copy=lambda s, d: calls.append((s, d)) or d)
    assert dest == dest_dir / "ccsync-companion.exe"
    assert dest_dir.is_dir()               # created
    assert calls and calls[0][0] == src    # copied from the bundled source
