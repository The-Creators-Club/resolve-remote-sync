"""Unit tests for onboarding/steps.py -- the pure/injectable orchestration
logic behind the onboard.py wizard. No tkinter, no real network calls, no
winget/tailscale/powershell processes: everything network- or process-shaped
is injected as a fake. See onboarding/tests/conftest.py for how `steps` and
`ccsync_companion` get onto sys.path.

This file covers the WINDOWS branches (test_macos_steps.py covers darwin's).
Anything that asserts a Windows shape -- PowerShell argv, a drive letter, a
UNC path, a .exe name -- pins `platform="win32"` through steps.py's seam so
it runs and passes on every host, exactly as the darwin file pins
`platform="darwin"`. The one test that cannot be pinned (it reaches past the
seam for a build artifact only a Windows dev tree has) carries a skipif
naming exactly what is Windows-only about it. Nothing
here may pass VACUOUSLY on a Mac -- 91% silently green is the defect this
convention exists to prevent."""

from __future__ import annotations

import json
import subprocess
import sys
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


# -- ensure_ssh_key: INST-22 (returncode + missing .pub + missing ssh-keygen) --


def test_ensure_ssh_key_raises_when_ssh_keygen_missing(tmp_path):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("ssh-keygen")

    with pytest.raises(steps.SshKeyError) as exc:
        steps.ensure_ssh_key(tmp_path, run=fake_run)
    assert "OpenSSH" in str(exc.value)


def test_ensure_ssh_key_raises_on_nonzero_returncode(tmp_path):
    def fake_run(cmd, **kwargs):
        return _FakeResult(returncode=1, stderr="Saving key failed: Permission denied\n")

    with pytest.raises(steps.SshKeyError) as exc:
        steps.ensure_ssh_key(tmp_path, run=fake_run)
    assert "Permission denied" in str(exc.value)


def test_ensure_ssh_key_raises_when_keygen_lies_about_success(tmp_path):
    # Exit 0 but no .pub on disk -- the old code returned that path anyway and
    # the Finish page said DONE next to a file that does not exist.
    def fake_run(cmd, **kwargs):
        return _FakeResult(returncode=0)

    with pytest.raises(steps.SshKeyError):
        steps.ensure_ssh_key(tmp_path, run=fake_run)


def test_ensure_ssh_key_derives_pub_from_existing_private_key(tmp_path):
    # INST-22: existing private key + missing .pub must NOT re-run
    # `ssh-keygen -f <key>` (which prompts "Overwrite (y/n)?" against closed
    # stdin, and would destroy a key the admin already installed on the NAS).
    (tmp_path / "ccsync_ed25519").write_text("existing-private-key")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeResult(returncode=0, stdout="ssh-ed25519 AAAAC3Nz derived\n")

    pub_path = steps.ensure_ssh_key(tmp_path, run=fake_run)
    assert len(calls) == 1
    assert calls[0][:2] == ["ssh-keygen", "-y"]
    assert "-N" not in calls[0]  # not a generate call
    assert pub_path.read_text().strip() == "ssh-ed25519 AAAAC3Nz derived"


def test_ensure_ssh_key_raises_when_derivation_produces_garbage(tmp_path):
    (tmp_path / "ccsync_ed25519").write_text("not-really-a-key")

    def fake_run(cmd, **kwargs):
        return _FakeResult(returncode=0, stdout="")

    with pytest.raises(steps.SshKeyError):
        steps.ensure_ssh_key(tmp_path, run=fake_run)


# -- S-6: every subprocess capture must decode explicitly ---------------------


def _captured_kwargs(fn, *args, **kwargs):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        seen["cmd"] = cmd
        return _FakeResult(returncode=0, stdout="")

    fn(*args, run=fake_run, **kwargs)
    return seen


def test_tailscale_up_decodes_explicitly():
    kwargs = _captured_kwargs(steps.tailscale_up)
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"


def test_ensure_ssh_key_decodes_explicitly(tmp_path):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        key_path = Path(cmd[cmd.index("-f") + 1])
        key_path.write_text("private")
        key_path.with_suffix(key_path.suffix + ".pub").write_text("ssh-ed25519 AAAA x")
        return _FakeResult(returncode=0)

    steps.ensure_ssh_key(tmp_path, run=fake_run)
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"


def test_run_bootstrap_decodes_explicitly(tmp_path):
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return _FakeResult(returncode=0, stdout="")

    steps.run_bootstrap(editor_name="j", dashboard_token="t", tailnet_host="h",
                        run=fake_run, script_path=script)
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


def test_run_bootstrap_survives_non_ascii_output(tmp_path):
    # S-6: a `C:\Users\José` profile echoed back by the bootstrap used to
    # raise UnicodeDecodeError out of the wizard's worker thread -- AFTER
    # _clean_slate() had removed the working install.
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    noisy = "[ccsync] configuring for editor 'josé', local root 'C:\\Users\\José\\台北'\n"

    def fake_run(cmd, **kwargs):
        return _FakeResult(returncode=0, stdout=noisy)

    exit_code, output = steps.run_bootstrap(
        editor_name="josé", dashboard_token="t", tailnet_host="h",
        run=fake_run, script_path=script,
    )
    assert exit_code == 0
    assert "José" in output and "台北" in output


def test_run_bootstrap_uses_noprofile_noninteractive(tmp_path):
    # INST-23: a profile script that prompts hangs the install against this
    # process's closed stdin, and surfaces as an unrelated bootstrap error.
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeResult(returncode=0, stdout="")

    steps.run_bootstrap(editor_name="j", dashboard_token="t", tailnet_host="h",
                        run=fake_run, script_path=script, platform="win32")
    assert "-NoProfile" in captured["cmd"]
    assert "-NonInteractive" in captured["cmd"]
    # ...and before -File, so PowerShell parses them as its own switches.
    assert captured["cmd"].index("-NoProfile") < captured["cmd"].index("-File")


# -- bootstrap_capability_warnings (INST-5) -----------------------------------


class TestBootstrapCapabilityWarnings:
    def test_empty_output_is_clean(self):
        assert steps.bootstrap_capability_warnings("") == []
        assert steps.bootstrap_capability_warnings("[ccsync] Bootstrap complete.\n") == []

    def test_marker_lines_are_extracted_without_the_prefix(self):
        output = (
            "[ccsync] checking rclone...\n"
            "[ccsync] WARNING: CAPABILITY MISSING: rclone is NOT installed.\n"
            "[ccsync] WARNING: CAPABILITY MISSING: Syncthing is NOT installed.\n"
            "[ccsync] Bootstrap complete.\n"
        )
        found = steps.bootstrap_capability_warnings(output)
        assert found == ["rclone is NOT installed.", "Syncthing is NOT installed."]

    def test_ordinary_warnings_are_not_capability_misses(self):
        output = "[ccsync] WARNING: normalized -EditorName 'JSmith' -> 'jsmith'\n"
        assert steps.bootstrap_capability_warnings(output) == []

    def test_duplicates_collapse(self):
        line = "[ccsync] WARNING: CAPABILITY MISSING: rclone is NOT installed.\n"
        assert len(steps.bootstrap_capability_warnings(line * 3)) == 1

    def test_legacy_phrasing_still_flagged(self):
        # An onboard.exe paired with an older windows_bootstrap.ps1 must not
        # silently report DONE.
        output = "[ccsync] WARNING: could not determine a Syncthing download URL -- install manually\n"
        assert steps.bootstrap_capability_warnings(output)


# -- bootstrap_hard_failure (B7) ----------------------------------------------


class TestBootstrapHardFailure:
    """A hard bootstrap abort must never be reported to the editor as a
    successful install just because a capability warning also fired."""

    RCLONE_MISS = ["rclone is NOT installed."]

    def test_clean_exit_is_not_a_failure(self):
        assert steps.bootstrap_hard_failure(0, []) is False
        assert steps.bootstrap_hard_failure(0, self.RCLONE_MISS) is False

    def test_capability_exit_code_is_not_a_failure(self):
        # exit 3 = windows_bootstrap.ps1's capability summary; the script ran
        # to the end. The Finish page shows "NOT ready yet", not RETRY.
        assert steps.BOOTSTRAP_CAPABILITY_EXIT_CODE == 3
        assert steps.bootstrap_hard_failure(3, self.RCLONE_MISS) is False

    def test_hard_abort_with_a_capability_warning_is_still_a_failure(self):
        # THE regression. $ErrorActionPreference="Stop":
        # Add-CapabilityMiss "rclone is NOT installed" fires at line ~558, the
        # P: mapping block then throws and the script exits 1 -- before the
        # companion install and before the capability summary. P: was
        # unmounted and never recreated. The old check
        # (`exit_code != 0 and not capability_problems`) said "fine".
        assert steps.bootstrap_hard_failure(1, self.RCLONE_MISS) is True

    def test_hard_abort_without_capability_warnings_is_a_failure(self):
        assert steps.bootstrap_hard_failure(1, []) is True
        assert steps.bootstrap_hard_failure(255, []) is True

    def test_bare_exit_3_with_nothing_parsed_is_a_failure(self):
        # Without the CAPABILITY MISSING lines the Finish page has nothing to
        # show and would render a green DONE -- exactly INST-5.
        assert steps.bootstrap_hard_failure(3, []) is True

    def test_unparsable_exit_code_is_a_failure(self):
        assert steps.bootstrap_hard_failure(None, self.RCLONE_MISS) is True
        assert steps.bootstrap_hard_failure("boom", []) is True

    def test_end_to_end_against_the_real_bootstrap_output_shape(self):
        # The exact stdout of the failing run: a capability miss, then a
        # terminating error out of the P: section.
        output = (
            f"[ccsync] installer v{steps.INSTALLER_VERSION} -- configuring for editor 'jsmith'\n"
            "[ccsync] WARNING: CAPABILITY MISSING: rclone is NOT installed. "
            "Lanes A and B cannot run at all on this machine.\n"
            "[ccsync] unmounting P:...\n"
            "New-SmbShare : The network path was not found.\n"
        )
        problems = steps.bootstrap_capability_warnings(output)
        assert problems  # the warning really is there...
        assert steps.bootstrap_hard_failure(1, problems) is True  # ...and it still failed


# -- effective_install_role (B20) ---------------------------------------------


class TestEffectiveInstallRole:
    """Which install actually runs. Only one of the two roles is destructive:
    the editor flow does `subst P: /D` + `net use P: /delete /y` and remaps P:
    at a loopback share of a LOCAL folder. On the base rig P: IS the NAS share
    every P:\\Projects\\... path in the Resolve database resolves through."""

    def test_verified_role_beats_the_radio(self):
        # The default radio is "editor"; re-running on the base rig used to
        # dispatch on it and destroy the NAS mapping.
        assert steps.effective_install_role("editor", "base") == "base"
        assert steps.effective_install_role("base", "editor") == "editor"

    def test_matching_roles_pass_through(self):
        assert steps.effective_install_role("editor", "editor") == "editor"
        assert steps.effective_install_role("base", "base") == "base"

    def test_falls_back_to_the_radio_when_the_dashboard_sends_no_role(self):
        # Older dashboards omit "role" entirely (see verify_account).
        assert steps.effective_install_role("editor", None) == "editor"
        assert steps.effective_install_role("base", "") == "base"
        assert steps.effective_install_role("editor", "   ") == "editor"

    def test_unrecognised_verified_role_falls_back_to_the_radio(self):
        assert steps.effective_install_role("editor", "admin") == "editor"

    def test_case_and_whitespace_are_tolerated(self):
        assert steps.effective_install_role("editor", " BASE ") == "base"
        assert steps.effective_install_role(" Editor ", None) == "editor"

    def test_two_unknowns_land_on_the_non_destructive_role(self):
        # "base" never touches a drive mapping, so it is the only safe
        # default when nothing is usable.
        assert steps.effective_install_role(None, None) == "base"
        assert steps.effective_install_role("nonsense", "nonsense") == "base"


def _onboard_method_source(name: str) -> str:
    """The body of one OnboardWizard method, straight out of the source file.
    onboard.py builds a Tk root in __init__ and has no display in CI, so the
    handful of decisions that live in the GUI layer are pinned this way."""
    import ast

    path = Path(steps.__file__).resolve().parent / "onboard.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"onboard.py has no method named {name!r} any more")


def test_onboard_dispatches_the_install_on_the_effective_role():
    """The B20 defect in one line: _on_begin_install picked its worker from
    self.role_var (the radio button), so a base-rig re-run with the default
    "editor" selection ran _clean_slate("editor") -> unmount_p=True."""
    body = _onboard_method_source("_on_begin_install")
    assert "_worker_base" in body and "_worker_editor" in body
    assert "_effective_role()" in body
    assert "role_var" not in body, "the install dispatch still keys on the radio button"


def test_onboard_treats_a_hard_bootstrap_abort_as_a_failure():
    """B7: the editor worker must branch on the exit code, not merely on
    whether any capability warning was parsed out of the output."""
    body = _onboard_method_source("_worker_editor")
    assert "bootstrap_hard_failure" in body
    assert "and not capability_problems" not in body


def test_onboard_base_worker_preflights_the_companion_exe():
    """B22: _clean_slate("base") taskkills the companion, deletes every
    autostart entry and unlinks the binary. find_companion_exe must be checked
    BEFORE that, or a package with no bundled exe leaves the machine with
    nothing and RETRY fails identically forever."""
    code = "\n".join(line for line in _onboard_method_source("_worker_base").splitlines()
                     if not line.lstrip().startswith("#"))
    assert "find_companion_exe" in code
    assert code.index("find_companion_exe") < code.index("_clean_slate")


# -- validate_local_root (INST-21) --------------------------------------------


class TestValidateLocalRoot:
    """The Windows half of validate_local_root -- drive letters, UNC paths,
    `subst`-hostile quotes. `platform="win32"` is pinned through the seam so
    every case below runs on a Mac too; without it validate_local_root
    dispatches to _validate_local_root_macos, which rejects `C:\\...` for
    having no leading slash and every "rejects X for reason Y" assertion
    passes or fails for the wrong reason. TestValidateLocalRootMac in
    test_macos_steps.py is the mirror image."""

    def _ok(self, value, role="editor", drives=("C", "D")):
        return steps.validate_local_root(
            value, role, drive_exists=lambda letter: letter in drives,
            platform="win32")

    def test_accepts_a_normal_path(self):
        assert self._ok(r"C:\Creators_Club") is None
        assert self._ok(r"D:\Video\Creators_Club") is None

    def test_rejects_blank(self):
        assert self._ok("") is not None
        assert self._ok("   ") is not None

    def test_rejects_trailing_whitespace(self):
        problem = self._ok("C:\\Creators_Club ")
        assert problem is not None and "space" in problem

    def test_rejects_relative_and_bare_names(self):
        assert self._ok("Creators_Club") is not None
        assert self._ok(r"\Creators_Club") is not None

    def test_rejects_unc_path_with_a_specific_reason(self):
        problem = self._ok(r"\\nas\share\Creators_Club")
        assert problem is not None and "network path" in problem

    def test_rejects_a_double_quote(self):
        # Breaks `cmd /c subst P: "<root>"` irrecoverably (INST-2).
        problem = self._ok('C:\\Creat"ors')
        assert problem is not None and "double-quote" in problem

    def test_rejects_a_drive_that_does_not_exist(self):
        problem = self._ok(r"Z:\Creators_Club")
        assert problem is not None and "Z:" in problem

    def test_rejects_p_drive_for_an_editor(self):
        # The install unmounts P: and remaps it AT this folder; Ensure-Dir
        # then runs against a drive that no longer exists, mid-install.
        problem = self._ok(r"P:\Creators_Club", drives=("C", "P"))
        assert problem is not None and "P:" in problem
        assert self._ok(r"p:\Creators_Club", drives=("C", "P")) is not None

    def test_allows_p_drive_for_the_base_rig(self):
        # The base flow never touches drive mappings.
        assert self._ok(r"P:\Creators_Club", role="base", drives=("C", "P")) is None

    def test_rejects_a_bare_volume_root_for_an_editor(self):
        # windows_bootstrap.ps1 hands local_root to `New-SmbShare -FullAccess`
        # and then maps P: at it: "D:\" publishes the ENTIRE volume read/write
        # over the loopback share.
        for value in ("D:\\", "D:/", "d:\\", "D:\\\\"):
            problem = self._ok(value)
            assert problem is not None, value
            assert "whole volume" in problem

    def test_allows_a_bare_volume_root_for_the_base_rig(self):
        # DEFAULT_BASE_LOCAL_ROOT is exactly "P:\\" -- the NAS share mapping.
        assert self._ok(steps.DEFAULT_BASE_LOCAL_ROOT, role="base",
                        drives=("C", "P")) is None

    def test_a_broken_drive_probe_never_blocks_the_install(self):
        def exploding(letter):
            raise OSError("probe blew up")

        assert steps.validate_local_root(r"C:\Creators_Club", "editor",
                                          drive_exists=exploding,
                                          platform="win32") is None


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
    # Both scripts are checked in, so pinning the platform makes this the
    # exact twin of test_find_bootstrap_script_darwin_dev_tree_fallback and it
    # passes on either host.
    found = steps.find_bootstrap_script(platform="win32")
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
        platform="win32",
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
    assert "-LocalRoot" in cmd and r"F:\Creators_Club" in cmd
    # The fleet token travels in the environment, NEVER on argv: a native
    # process's command line is readable by any unprivileged process via
    # Get-CimInstance Win32_Process (AUDIT SEC-2).
    assert "-DashboardToken" not in cmd
    assert "report-secret" not in cmd
    assert captured["kwargs"]["env"]["CCSYNC_DASHBOARD_TOKEN"] == "report-secret"


def test_run_bootstrap_keeps_the_fleet_token_off_the_command_line(tmp_path):
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeResult(returncode=0, stdout="")

    steps.run_bootstrap(
        editor_name="jsmith", dashboard_token="5f0c7dd7ab03435090",
        tailnet_host="h", run=fake_run, script_path=script, platform="win32",
    )
    assert not any("5f0c7dd7ab03435090" in str(part) for part in captured["cmd"])
    # ...and the rest of the parent environment is still handed down, so the
    # bootstrap keeps seeing PATH/LOCALAPPDATA/TEMP.
    env = captured["kwargs"]["env"]
    assert env["CCSYNC_DASHBOARD_TOKEN"] == "5f0c7dd7ab03435090"
    assert "PATH" in env or "Path" in env


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
        platform="win32",
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
        platform="win32",
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
        run=fake_run, script_path=script, platform="win32",
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


def test_run_bootstrap_passes_timeout_to_run(tmp_path):
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["kwargs"] = kwargs
        return _FakeResult(returncode=0, stdout="")

    steps.run_bootstrap(
        editor_name="jsmith", dashboard_token="x", tailnet_host="100.71.216.3",
        run=fake_run, script_path=script,
    )
    assert captured["kwargs"]["timeout"] == steps.BOOTSTRAP_TIMEOUT_SECONDS


def test_run_bootstrap_timeout_becomes_failed_install_result(tmp_path):
    script = tmp_path / "windows_bootstrap.ps1"
    script.write_text("# fake")

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout"),
                                         output="partial output so far", stderr="")

    exit_code, output = steps.run_bootstrap(
        editor_name="jsmith", dashboard_token="x", tailnet_host="100.71.216.3",
        run=fake_run, script_path=script,
    )
    assert exit_code != 0
    assert "partial output so far" in output
    assert "timed out" in output


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


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="the dev-tree fallback resolves to companion/dist/, whose contents "
           "are host-built: only a Windows dev box has ccsync-companion.exe "
           "there (a Mac's dist/ holds the extensionless darwin binary, and "
           "only after tools/release_macos.sh has run). Pinning platform= "
           "would just assert a file that cannot exist on the other host -- "
           "the darwin side is covered by test_find_companion_exe_darwin_* "
           "in test_macos_steps.py, which uses tmp_path instead.",
)
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
                                   copy=lambda s, d: calls.append((s, d)) or d,
                                   platform="win32")
    assert dest == dest_dir / "ccsync-companion.exe"
    assert dest_dir.is_dir()               # created
    assert calls and calls[0][0] == src    # copied from the bundled source
