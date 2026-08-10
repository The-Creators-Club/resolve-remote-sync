"""Unit tests for steps.py's darwin branches (the macOS onboarding wizard,
1.0.17). Same injected-fake style as test_steps.py: every test runs on any
host -- `platform="darwin"` is passed explicitly, launchctl/pgrep/bash are
fakes, and nothing touches the filesystem outside tmp_path. The bottom
section pins the machine-readable contract macos_bootstrap.sh must keep
(CAPABILITY MISSING: marker, exit 3 summary, RESOLVE-MAPPING-STATUS) at the
source-text level, the same way test_steps.py pins onboard.py's GUI-layer
decisions."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import steps


class _FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


REPO_ROOT = Path(steps.__file__).resolve().parent.parent


# -- platform selectors --------------------------------------------------------


class TestSelectors:
    def test_bootstrap_script_name(self):
        assert steps.bootstrap_script_name("darwin") == "macos_bootstrap.sh"
        assert steps.bootstrap_script_name("win32") == "windows_bootstrap.ps1"

    def test_companion_exe_name(self):
        assert steps.companion_exe_name("darwin") == "ccsync-companion"
        assert steps.companion_exe_name("win32") == "ccsync-companion.exe"

    def test_default_local_root(self):
        mac_root = steps.default_local_root("darwin")
        assert mac_root == str(Path.home() / "Creators_Club")
        assert steps.default_local_root("win32") == r"C:\Creators_Club"

    def test_default_base_local_root(self):
        # Windows base: P:\ IS the NAS share mapping. macOS base: the same
        # share mounted over SMB lands under /Volumes/<ShareName>, tree one
        # level in.
        assert steps.default_base_local_root("win32") == "P:\\"
        assert steps.default_base_local_root("darwin") == "/Volumes/TheCreatorsPool/Creators_Club"

    def test_companion_bin_dir(self):
        assert steps.companion_bin_dir("darwin") == Path.home() / ".local" / "ccsync" / "bin"
        assert steps.companion_bin_dir("win32") == steps.COMPANION_BIN_DIR

    def test_mac_default_matches_the_bootstraps_own_default(self):
        # macos_bootstrap.sh ships LOCAL_ROOT="$HOME/Creators_Club"; the two
        # must agree or a wizard install and a hand re-run of the script
        # would disagree about where the tree lives.
        sh = (REPO_ROOT / "installer" / "macos_bootstrap.sh").read_text(encoding="utf-8")
        assert 'LOCAL_ROOT="$HOME/Creators_Club"' in sh


# -- tailscale -----------------------------------------------------------------


class TestTailscaleMac:
    def test_installed_via_path(self):
        assert steps.tailscale_installed(
            platform="darwin",
            which=lambda name: "/usr/local/bin/tailscale",
            exists=lambda p: False,
        ) is True

    def test_installed_via_app_bundle(self):
        assert steps.tailscale_installed(
            platform="darwin",
            which=lambda name: None,
            exists=lambda p: p == steps.TAILSCALE_APP_MACOS,
        ) is True

    def test_not_installed(self):
        assert steps.tailscale_installed(
            platform="darwin", which=lambda name: None, exists=lambda p: False,
        ) is False

    def test_up_falls_back_to_the_app_cli(self):
        # `tailscale` is not on PATH on a stock Tailscale.app install; the
        # CLI inside the bundle is the real thing to ask.
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd[0])
            if cmd[0] == "tailscale":
                raise FileNotFoundError(cmd[0])
            return _FakeResult(returncode=0, stdout="100.66.62.41  mac  leso@ ...")

        assert steps.tailscale_up(run=fake_run, platform="darwin") is True
        assert calls == ["tailscale", steps.TAILSCALE_CLI_MACOS]

    def test_up_false_when_logged_out_via_app_cli(self):
        def fake_run(cmd, **kwargs):
            if cmd[0] == "tailscale":
                raise FileNotFoundError(cmd[0])
            return _FakeResult(returncode=0, stdout="Logged out.")

        assert steps.tailscale_up(run=fake_run, platform="darwin") is False

    def test_up_false_when_no_cli_anywhere(self):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError(cmd[0])

        assert steps.tailscale_up(run=fake_run, platform="darwin") is False

    def test_windows_behavior_unchanged_by_the_candidate_loop(self):
        def fake_run(cmd, **kwargs):
            assert cmd == ["tailscale", "status"]
            return _FakeResult(returncode=0, stdout="100.71.0.2 pc alex@ windows -")

        assert steps.tailscale_up(run=fake_run, platform="win32") is True


# -- find_* / run_bootstrap ----------------------------------------------------


def test_find_bootstrap_script_darwin_dev_tree_fallback():
    found = steps.find_bootstrap_script(platform="darwin")
    assert found.name == "macos_bootstrap.sh"
    assert found.exists()


def test_find_companion_exe_darwin_explicit(tmp_path):
    binary = tmp_path / "ccsync-companion"
    binary.write_bytes(b"\xcf\xfa\xed\xfe fake mach-o")
    assert steps.find_companion_exe(binary, platform="darwin") == binary


def test_find_companion_exe_darwin_error_names_the_mac_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(steps, "__file__", str(tmp_path / "nowhere" / "steps.py"))
    with pytest.raises(FileNotFoundError) as exc:
        steps.find_companion_exe(tmp_path / "missing", platform="darwin")
    assert "ccsync-companion " in str(exc.value) or str(exc.value).startswith("ccsync-companion")


class TestRunBootstrapMac:
    def _invoke(self, tmp_path, fake_run, **kwargs):
        script = tmp_path / "macos_bootstrap.sh"
        script.write_text("# fake")
        defaults = dict(
            editor_name="leso",
            dashboard_token="report-secret",
            tailnet_host="100.71.216.3",
            dashboard_url="http://100.71.216.3:8480",
            run=fake_run,
            script_path=script,
            platform="darwin",
        )
        defaults.update(kwargs)
        return steps.run_bootstrap(**defaults), script

    def test_builds_expected_bash_command(self, tmp_path):
        companion = tmp_path / "ccsync-companion"
        companion.write_text("fake")
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return _FakeResult(returncode=0, stdout="Bootstrap complete (installer 1.0.17).\n")

        (exit_code, output), script = self._invoke(
            tmp_path, fake_run,
            local_root="/Volumes/T7/Creators_Club",
            companion_exe_source=companion,
        )
        assert exit_code == 0
        cmd = captured["cmd"]
        assert cmd[0] == "bash" and str(script) in cmd
        assert "--tailnet-host" in cmd and "100.71.216.3" in cmd
        assert "--editor-name" in cmd and "leso" in cmd
        assert "--local-root" in cmd and "/Volumes/T7/Creators_Club" in cmd
        assert "--companion-file" in cmd and str(companion) in cmd
        # No PowerShell leakage.
        assert "powershell" not in cmd and "-File" not in cmd

    def test_token_and_url_travel_in_the_environment_not_argv(self, tmp_path):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return _FakeResult(returncode=0, stdout="")

        self._invoke(tmp_path, fake_run)
        assert not any("report-secret" in str(part) for part in captured["cmd"])
        env = captured["kwargs"]["env"]
        # macos_bootstrap.sh reads DASHBOARD_TOKEN / DASHBOARD_URL from env
        # (it has no flags for either) -- see its "Overridable from the
        # environment" block.
        assert env["DASHBOARD_TOKEN"] == "report-secret"
        assert env["DASHBOARD_URL"] == "http://100.71.216.3:8480"

    def test_omits_optional_flags_when_not_given(self, tmp_path):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return _FakeResult(returncode=0, stdout="")

        self._invoke(tmp_path, fake_run)
        assert "--local-root" not in captured["cmd"]
        assert "--companion-file" not in captured["cmd"]

    def test_exit_3_and_output_propagate(self, tmp_path):
        def fake_run(cmd, **kwargs):
            return _FakeResult(
                returncode=3,
                stdout="[ccsync] WARNING: CAPABILITY MISSING: rclone is NOT installed.\n")

        (exit_code, output), _ = self._invoke(tmp_path, fake_run)
        assert exit_code == 3
        problems = steps.bootstrap_capability_warnings(output)
        assert problems
        assert steps.bootstrap_hard_failure(exit_code, problems) is False

    def test_timeout_names_the_mac_script(self, tmp_path):
        import subprocess

        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout"),
                                             output="partial", stderr="")

        (exit_code, output), _ = self._invoke(tmp_path, fake_run)
        assert exit_code != 0
        assert "macos_bootstrap.sh" in output


# -- capability + resolve-mapping parsing --------------------------------------


class TestMacOutputParsing:
    def test_marker_lines_parse_exactly_like_windows(self):
        output = (
            "[ccsync] ccsync macOS bootstrap 1.0.17 -- editor 'leso'\n"
            "[ccsync] WARNING: CAPABILITY MISSING: rclone is NOT installed. Lanes A and B "
            "-- every video upload and every proxy download -- cannot run on this Mac.\n"
            "[ccsync] WARNING: CAPABILITY MISSING: Syncthing is NOT installed. Lane C will "
            "never sync on this Mac.\n"
        )
        problems = steps.bootstrap_capability_warnings(output)
        assert len(problems) == 2
        assert problems[0].startswith("rclone is NOT installed")

    def test_pre_1017_sh_phrasings_still_flagged(self):
        # A wizard paired with a stale macos_bootstrap.sh (no marker, exit 0)
        # must not silently report DONE -- same reasoning as the Windows
        # legacy phrases.
        legacy = (
            "[ccsync] WARNING: rclone is NOT installed. Lanes A and B -- every video "
            "upload and every proxy download -- cannot run on this Mac.\n"
            "[ccsync] WARNING: Syncthing was not installed, so no LaunchAgent was written "
            "(an agent with no program to run can never be repaired by a later run of this script).\n"
            "[ccsync] WARNING: could not determine the Syncthing device ID automatically.\n"
        )
        assert len(steps.bootstrap_capability_warnings(legacy)) == 3

    def test_resolve_mapping_ok_statuses_yield_no_warning(self):
        for status in ("ok", "dry-run", "skipped"):
            output = f"[ccsync] RESOLVE-MAPPING-STATUS: {status}\n"
            assert steps.resolve_mapping_warning(output) is None

    def test_resolve_mapping_running_warns_quit_resolve(self):
        output = "[ccsync] RESOLVE-MAPPING-STATUS: running\n"
        warning = steps.resolve_mapping_warning(output)
        assert warning and "Quit Resolve" in warning

    def test_resolve_mapping_never_launched_warns(self):
        output = "[ccsync] RESOLVE-MAPPING-STATUS: never-launched\n"
        warning = steps.resolve_mapping_warning(output)
        assert warning and "never been launched" in warning

    def test_resolve_mapping_last_marker_wins(self):
        # A re-run prints one marker per attempt; the final state is the one
        # that stands.
        output = (
            "[ccsync] RESOLVE-MAPPING-STATUS: running\n"
            "[ccsync] RESOLVE-MAPPING-STATUS: ok\n"
        )
        assert steps.resolve_mapping_warning(output) is None

    def test_resolve_mapping_unknown_status_is_reported_not_swallowed(self):
        output = "[ccsync] RESOLVE-MAPPING-STATUS: some-new-status\n"
        warning = steps.resolve_mapping_warning(output)
        assert warning and "some-new-status" in warning

    def test_windows_bootstrap_output_yields_no_mapping_warning(self):
        output = "[ccsync] Bootstrap complete.\n[ccsync] Your Syncthing device ID is:\n"
        assert steps.resolve_mapping_warning(output) is None

    def test_device_id_regex_matches_the_sh_output_shape(self):
        output = (
            " Your Syncthing device ID is:\n\n"
            "     ABCDEFG-HIJKLMN-OPQRSTU-VWXYZ23-ABCDEFG-HIJKLMN-OPQRSTU-VWXYZ23\n"
        )
        assert steps.parse_device_id(output) == (
            "ABCDEFG-HIJKLMN-OPQRSTU-VWXYZ23-ABCDEFG-HIJKLMN-OPQRSTU-VWXYZ23")


# -- base-mode install pieces, darwin ------------------------------------------


class TestBaseInstallMac:
    """A commercial deployment can run its base rig on a Mac, so the base
    role must produce a real install there: companion into the canonical bin
    dir, autostart via a LaunchAgent (there is no registry), NAS mounts
    untouched."""

    def test_install_companion_lands_in_the_mac_bin_dir_shape(self, tmp_path):
        src = tmp_path / "ccsync-companion"
        src.write_bytes(b"\xcf\xfa\xed\xfe fake mach-o")
        dest_dir = tmp_path / "bin"
        installed = steps.install_companion(dest_dir=dest_dir, src=src,
                                             platform="darwin")
        assert installed == dest_dir / "ccsync-companion"  # extensionless
        assert installed.read_bytes() == src.read_bytes()

    def test_install_companion_default_dest_is_the_platform_bin_dir(self):
        assert steps.companion_bin_dir("darwin") == Path.home() / ".local" / "ccsync" / "bin"

    def test_launch_agent_plist_matches_the_bootstraps_shape(self, tmp_path):
        exe = Path("/Users/leso/.local/ccsync/bin/ccsync-companion")
        plist = steps.write_companion_launch_agent(exe, agents_dir=tmp_path)
        assert plist.name == steps.COMPANION_PLIST_NAME
        text = plist.read_text(encoding="utf-8")
        assert f"<string>{exe}</string>" in text
        assert "<key>RunAtLoad</key>" in text
        assert "<key>AbandonProcessGroup</key>" in text
        # NO KeepAlive, deliberately: with it launchd restarts the process
        # the self-upgrade just replaced, and two companions fight over the
        # single-instance lock (same reasoning as macos_bootstrap.sh 6a).
        assert "KeepAlive" not in text

    def test_wizard_plist_is_byte_identical_to_the_bootstraps(self, tmp_path):
        # Both roles must end up with the IDENTICAL autostart shape; the
        # editor's plist comes from macos_bootstrap.sh, base's from here.
        sh = (REPO_ROOT / "installer" / "macos_bootstrap.sh").read_text(encoding="utf-8")
        for line in ("<string>com.creatorsclub.ccsync.companion</string>",
                     "<key>AbandonProcessGroup</key>"):
            assert line.strip() in [l.strip() for l in sh.splitlines()]
        assert "<key>RunAtLoad</key>" in steps.COMPANION_LAUNCH_AGENT_TEMPLATE

    def test_load_launch_agent_bootout_then_bootstrap(self, tmp_path):
        plist = tmp_path / steps.COMPANION_PLIST_NAME
        plist.write_text("<plist/>")
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd[:2])
            return _FakeResult(returncode=0)

        assert steps.load_launch_agent(plist, run=fake_run, getuid=lambda: 501) is True
        verbs = [c[1] for c in calls]
        # A rewritten plist must be booted out first or launchd keeps running
        # the OLD program (macos_bootstrap.sh's reload_agent, INST-8).
        assert verbs[:2] == ["bootout", "unload"]
        assert "bootstrap" in verbs

    def test_load_launch_agent_falls_back_to_legacy_load(self, tmp_path):
        plist = tmp_path / steps.COMPANION_PLIST_NAME
        plist.write_text("<plist/>")

        def fake_run(cmd, **kwargs):
            if cmd[1] == "bootstrap":
                return _FakeResult(returncode=5)
            return _FakeResult(returncode=0)

        assert steps.load_launch_agent(plist, run=fake_run, getuid=lambda: 501) is True

    def test_load_launch_agent_false_when_launchd_refuses_everything(self, tmp_path):
        plist = tmp_path / steps.COMPANION_PLIST_NAME
        plist.write_text("<plist/>")

        def fake_run(cmd, **kwargs):
            return _FakeResult(returncode=1)

        assert steps.load_launch_agent(plist, run=fake_run, getuid=lambda: 501) is False


# -- validate_local_root, darwin -----------------------------------------------


class TestValidateLocalRootMac:
    def _validate(self, value, mounted=True, is_mount=None, role="editor"):
        if is_mount is None:
            is_mount = lambda p: mounted  # noqa: E731
        return steps.validate_local_root(value, role, platform="darwin",
                                          is_mount=is_mount)

    def test_blank_and_whitespace(self):
        assert self._validate("") is not None
        assert self._validate("   ") is not None
        assert self._validate(" /Volumes/T7/CC") is not None  # leading space

    def test_tilde_is_rejected_with_guidance(self):
        problem = self._validate("~/Creators_Club")
        assert problem and str(Path.home()) in problem

    def test_relative_path_rejected(self):
        assert self._validate("Creators_Club") is not None

    def test_filesystem_root_and_bare_volumes_rejected(self):
        assert self._validate("/") is not None
        assert self._validate("/Volumes") is not None
        assert self._validate("/Volumes/") is not None

    def test_volume_root_rejected_for_editors_with_suggestion(self):
        problem = self._validate("/Volumes/T7")
        assert problem and "/Volumes/T7/Creators_Club" in problem
        assert self._validate("/Volumes/T7/") is not None

    def test_volume_root_allowed_for_base(self):
        # The macOS twin of Windows base's P:\ -- a NAS share whose mount IS
        # the tree (smb://nas/Creators_Club -> /Volumes/Creators_Club).
        assert self._validate("/Volumes/Creators_Club", role="base",
                              mounted=True) is None

    def test_base_unmounted_share_message_talks_about_the_nas(self):
        problem = self._validate("/Volumes/TheCreatorsPool/Creators_Club",
                                 role="base", mounted=False)
        assert problem and "NAS" in problem
        # ...and never tells a base rig to plug in an SSD.
        assert "SSD" not in problem

    def test_folder_on_mounted_volume_accepted(self):
        assert self._validate("/Volumes/T7/Creators_Club", mounted=True) is None

    def test_unmounted_volume_rejected(self):
        # Ghost directory or unplugged drive -- either way, installing now
        # would let clean-slate run and then hit the bootstrap's hard abort
        # (INST-21's exact shape, macOS edition).
        problem = self._validate("/Volumes/T7/Creators_Club", mounted=False)
        assert problem and "/Volumes/T7" in problem

    def test_home_folder_accepted_without_mount_probe(self):
        probed = []

        def probe(path):
            probed.append(path)
            return False

        assert self._validate("/Users/leso/Creators_Club", is_mount=probe) is None
        assert probed == []  # only /Volumes paths are probed

    def test_broken_probe_never_blocks(self):
        def probe(path):
            raise OSError("stat failed")

        assert self._validate("/Volumes/T7/Creators_Club", is_mount=probe) is None

    def test_windows_paths_still_validate_on_win32(self):
        assert steps.validate_local_root(r"D:\Creators_Club", "editor",
                                          drive_exists=lambda d: True,
                                          platform="win32") is None


# -- ensure_config, darwin -----------------------------------------------------


class TestEnsureConfigMac:
    def test_defaults_local_root_to_the_mac_default(self, tmp_path):
        path = tmp_path / "config.toml"
        steps.ensure_config(
            "editor", editor_name="leso", dashboard_url="http://x:8480",
            dashboard_token="tok", local_root=None, config_path=path,
            platform="darwin",
        )
        text = path.read_text(encoding="utf-8")
        expected = steps._toml_string(steps.default_local_root("darwin"))
        assert f"local_root = {expected}" in text

    def test_posix_local_root_written_verbatim_and_prefix_stays_canonical(self, tmp_path):
        path = tmp_path / "config.toml"
        steps.ensure_config(
            "editor", editor_name="leso", dashboard_url="http://x:8480",
            dashboard_token="tok", local_root="/Volumes/T7/Creators_Club",
            config_path=path, platform="darwin",
        )
        text = path.read_text(encoding="utf-8")
        assert 'local_root = "/Volumes/T7/Creators_Club"' in text
        # The canonical prefix is fleet-wide Windows form on every platform.
        assert 'canonical_prefix = "P:\\\\"' in text
        assert 'mode = "editor"' in text

    def test_base_mode_defaults_to_the_mac_nas_mount(self, tmp_path):
        path = tmp_path / "config.toml"
        steps.ensure_config(
            "base", editor_name="alex", dashboard_url="http://x:8480",
            dashboard_token="tok", local_root=None, config_path=path,
            platform="darwin",
        )
        text = path.read_text(encoding="utf-8")
        assert 'local_root = "/Volumes/TheCreatorsPool/Creators_Club"' in text
        # Base mode: everything on the volume outside the tree counts as
        # out-of-tree, so the prefix IS the root (same rule as Windows base).
        assert 'canonical_prefix = "/Volumes/TheCreatorsPool/Creators_Club"' in text
        assert 'mode = "base"' in text


# -- clean slate, macOS --------------------------------------------------------


HOME = Path("/Users/leso")
BIN = HOME / ".local" / "ccsync" / "bin"
AGENTS = HOME / "Library" / "LaunchAgents"


class TestBuildCleanupPlanMac:
    def _plan(self, existing=()):
        existing_set = {str(p) for p in existing}
        return steps.build_cleanup_plan_macos(
            exists=lambda p: str(p) in existing_set, home=HOME)

    def test_nothing_windows_shaped_in_the_plan(self):
        plan = self._plan()
        assert plan.unmount_p is False
        assert plan.run_values == []
        assert plan.scheduled_tasks == []
        assert plan.shim_paths == []
        assert plan.kill_pythonw_launcher is False

    def test_exe_paths_cover_upgrade_and_staging_siblings(self):
        files = [BIN / n for n in ("ccsync-companion", "ccsync-companion.old",
                                    "ccsync-companion.new", "ccsync-companion.ccsync-new")]
        plan = self._plan(existing=files)
        assert set(plan.exe_paths) == set(files)

    def test_preserved_tools_never_listed(self):
        plan = self._plan(existing=[BIN / "rclone", BIN / "syncthing"])
        assert plan.exe_paths == []

    def test_both_launch_agents_listed_when_present(self):
        plists = [AGENTS / steps.COMPANION_PLIST_NAME, AGENTS / steps.SYNCTHING_PLIST_NAME]
        plan = self._plan(existing=plists)
        assert plan.launch_agent_plists == plists

    def test_absent_launch_agents_not_listed(self):
        assert self._plan().launch_agent_plists == []

    def test_syncthing_managed_dirs_are_ours_only(self):
        plan = self._plan()
        assert HOME / ".local" / "ccsync" in plan.syncthing_managed_dirs
        assert HOME / ".ccsync" in plan.syncthing_managed_dirs
        assert all("ccsync" in str(d) for d in plan.syncthing_managed_dirs)


class TestExecuteCleanupMac:
    def _run(self, plan, processes=None, run_fails=False):
        """Drive execute_cleanup_macos with fakes; returns a dict of what
        happened."""
        happened = {"run": [], "killed": [], "deleted": [], "logs": []}
        processes = processes or {}

        def fake_run(cmd, **kwargs):
            happened["run"].append(cmd)
            if run_fails:
                raise OSError("launchctl exploded")
            return _FakeResult(returncode=0)

        warnings = steps.execute_cleanup_macos(
            plan,
            log=happened["logs"].append,
            run=fake_run,
            delete_file=lambda p: happened["deleted"].append(Path(p)),
            kill=lambda pid: happened["killed"].append(pid),
            getuid=lambda: 501,
            sleep=lambda s: None,
            list_processes=lambda name: processes.get(name, []),
        )
        happened["warnings"] = warnings
        return happened

    def _plan(self, **kwargs):
        defaults = dict(
            kill_process_names=["ccsync-companion", "ccsync-companion.new"],
            kill_pythonw_launcher=False,
            run_values=[], scheduled_tasks=[], exe_paths=[], shim_paths=[],
            unmount_p=False,
            syncthing_managed_dirs=[HOME / ".local" / "ccsync", HOME / ".ccsync"],
            launch_agent_plists=[],
        )
        defaults.update(kwargs)
        return steps.CleanupPlan(**defaults)

    def test_agents_booted_out_and_plists_deleted(self):
        plists = [AGENTS / steps.COMPANION_PLIST_NAME, AGENTS / steps.SYNCTHING_PLIST_NAME]
        happened = self._run(self._plan(launch_agent_plists=plists))
        bootouts = [c for c in happened["run"] if c[:2] == ["launchctl", "bootout"]]
        assert len(bootouts) == 2
        assert bootouts[0][2] == "gui/501"
        assert set(happened["deleted"]) == set(plists)

    def test_our_companion_killed_by_basename(self):
        happened = self._run(
            self._plan(),
            processes={"ccsync-companion": [("321", str(BIN / "ccsync-companion"))]},
        )
        assert happened["killed"] == ["321"]

    def test_lookalike_commandline_match_is_left_alone(self):
        # pgrep -f matches full command lines, so `tail -f companion.log`
        # shows up in the listing -- the executable is the filter.
        happened = self._run(
            self._plan(),
            processes={"ccsync-companion": [("777", "/usr/bin/tail")]},
        )
        assert happened["killed"] == []

    def test_foreign_syncthing_left_alone_with_warning(self):
        happened = self._run(
            self._plan(),
            processes={"syncthing": [("555", "/opt/homebrew/bin/syncthing")]},
        )
        assert happened["killed"] == []
        assert any("not ours" in w for w in happened["warnings"])

    def test_our_syncthing_killed(self):
        happened = self._run(
            self._plan(),
            processes={"syncthing": [("556", str(BIN / "syncthing"))]},
        )
        assert happened["killed"] == ["556"]

    def test_exe_paths_deleted(self):
        exes = [BIN / "ccsync-companion", BIN / "ccsync-companion.old"]
        happened = self._run(self._plan(exe_paths=exes))
        assert set(happened["deleted"]) == set(exes)

    def test_never_raises_when_launchctl_is_broken(self):
        plists = [AGENTS / steps.COMPANION_PLIST_NAME]
        happened = self._run(self._plan(launch_agent_plists=plists), run_fails=True)
        assert any("bootout" in w for w in happened["warnings"])
        # ...and the plist file itself was still removed.
        assert happened["deleted"] == plists


# -- the macos_bootstrap.sh contract, pinned at source level -------------------


SH_TEXT = (REPO_ROOT / "installer" / "macos_bootstrap.sh").read_text(encoding="utf-8")


class TestShWizardContract:
    """steps.py branches on three things macos_bootstrap.sh emits; a refactor
    that renames any of them silently breaks the wizard's INST-5 protection,
    so pin them here (the sh has no test suite of its own on Windows)."""

    def test_capability_marker_matches_steps(self):
        assert f"CAPABILITY MISSING: $1" in SH_TEXT
        assert steps.CAPABILITY_MARKER == "CAPABILITY MISSING:"

    def test_the_three_misses_go_through_capability_miss(self):
        assert SH_TEXT.count("capability_miss \"") >= 3
        assert "capability_miss \"rclone is NOT installed" in SH_TEXT
        assert "capability_miss \"Syncthing is NOT installed" in SH_TEXT
        assert "capability_miss \"the Syncthing device ID could NOT be determined" in SH_TEXT

    def test_exit_3_only_from_the_capability_summary(self):
        assert steps.BOOTSTRAP_CAPABILITY_EXIT_CODE == 3
        # Count actual `exit 3` statements (comments mention the number too).
        statements = re.findall(r"^\s*exit 3\s*$", SH_TEXT, re.M)
        assert len(statements) == 1
        # ...and it is guarded by the miss counter.
        summary = SH_TEXT[SH_TEXT.index('CAPABILITY_MISS_COUNT" -gt 0'):]
        assert "exit 3" in summary

    def test_resolve_mapping_status_marker_present_at_both_call_sites(self):
        marker_lines = [l for l in SH_TEXT.splitlines()
                        if "RESOLVE-MAPPING-STATUS: $RESOLVE_MAPPING_STATUS" in l]
        assert len(marker_lines) == 2
        assert steps.RESOLVE_MAPPING_MARKER == "RESOLVE-MAPPING-STATUS:"

    def test_sh_statuses_are_all_known_to_steps(self):
        statuses = set(re.findall(r'RESOLVE_MAPPING_STATUS="([a-z-]+)"', SH_TEXT))
        known = set(steps._RESOLVE_MAPPING_MESSAGES) | {
            s for s in steps._RESOLVE_MAPPING_OK_STATUSES if s}
        assert statuses <= known, f"unmapped statuses: {statuses - known}"

    def test_rclone_path_repair_present(self):
        # The wizard pre-creates config.toml, so the bootstrap's seeding is
        # always skipped there -- without this repair every wizard install
        # ships rclone_path = "rclone", which launchd can never resolve
        # (INST-7).
        assert "NEEDS_RCLONE_REPAIR" in SH_TEXT
        assert 'rclone_path = \\"%s\\"' in SH_TEXT or 'rclone_path = "%s"' in SH_TEXT


class TestInstallerVersionParity:
    """One installer number covers steps.py, both bootstrap scripts, and the
    mac bundle -- the release scripts refuse on drift, but that is discovered
    at ship time; fail here at test time instead."""

    def test_all_four_agree(self):
        ps1 = (REPO_ROOT / "installer" / "windows_bootstrap.ps1").read_text(encoding="utf-8")
        spec = (REPO_ROOT / "onboarding" / "build_onboard_macos.spec").read_text(encoding="utf-8")
        ps1_version = re.search(r'^\$InstallerVersion\s*=\s*"([^"]+)"', ps1, re.M).group(1)
        sh_version = re.search(r'^INSTALLER_VERSION="([^"]+)"', SH_TEXT, re.M).group(1)
        spec_version = re.search(r'"CFBundleShortVersionString":\s*"([^"]+)"', spec).group(1)
        assert ps1_version == steps.INSTALLER_VERSION
        assert sh_version == steps.INSTALLER_VERSION
        assert spec_version == steps.INSTALLER_VERSION


# -- the .app is a ONEDIR build (KNOWN_BUGS item 9) ----------------------------
#
# PyInstaller 6.21 only warns that a onefile .app "will become an error in
# v7.0"; the spec can only be built on a Mac, so a silent revert to onefile
# would be discovered as a broken release on the one path that has no
# fallback. These are AST guards, not regexes, so a reverted spec fails here
# on any host -- the same reasoning as companion/tests/
# test_tk_interpreter_hygiene.py.

SPEC_PATH = REPO_ROOT / "onboarding" / "build_onboard_macos.spec"


def _spec_tree():
    import ast

    return ast.parse(SPEC_PATH.read_text(encoding="utf-8"))


def _spec_calls(func_name):
    import ast

    return [node for node in ast.walk(_spec_tree())
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == func_name]


def _kwargs(call):
    return {kw.arg: kw.value for kw in call.keywords}


def _attr_args(call):
    """Positional args of the shape `a.binaries` / `a.datas`, as strings."""
    import ast

    return [f"{arg.value.id}.{arg.attr}" for arg in call.args
            if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name)]


class TestMacBundleIsOnedir:
    def test_exe_excludes_binaries(self):
        import ast

        calls = _spec_calls("EXE")
        assert len(calls) == 1
        exclude = _kwargs(calls[0]).get("exclude_binaries")
        assert isinstance(exclude, ast.Constant) and exclude.value is True, \
            "EXE(exclude_binaries=True) is what makes this a onedir build"

    def test_exe_is_not_handed_the_collected_files(self):
        # Passing a.binaries/a.datas to EXE is how a spec accidentally goes
        # back to onefile; in onedir they belong to COLLECT.
        assert _attr_args(_spec_calls("EXE")[0]) == ["a.scripts"]

    def test_exe_has_no_runtime_tmpdir(self):
        # Onefile-only setting: there is no extraction directory any more.
        assert "runtime_tmpdir" not in _kwargs(_spec_calls("EXE")[0])

    def test_collect_gathers_binaries_and_datas(self):
        calls = _spec_calls("COLLECT")
        assert len(calls) == 1, "onedir needs exactly one COLLECT step"
        assert _attr_args(calls[0]) == ["a.binaries", "a.datas"]

    def test_bundle_wraps_the_collect_not_the_exe(self):
        # BUNDLE(exe) with a onefile EXE is exactly what PyInstaller 6.21
        # deprecates and 7.0 rejects.
        import ast

        tree = _spec_tree()
        collect_target = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and getattr(node.value.func, "id", None) == "COLLECT"):
                collect_target = node.targets[0].id
        assert collect_target is not None

        bundles = _spec_calls("BUNDLE")
        assert len(bundles) == 1
        first = bundles[0].args[0]
        assert isinstance(first, ast.Name) and first.id == collect_target

    def test_bundle_keeps_its_identity(self):
        import ast

        kwargs = _kwargs(_spec_calls("BUNDLE")[0])
        assert kwargs["name"].value == "CCSync Onboarding.app"
        assert kwargs["bundle_identifier"].value == "com.creatorsclub.ccsync.onboard"
        plist = {k.value: v for k, v in zip(kwargs["info_plist"].keys, kwargs["info_plist"].values)}
        assert "CFBundleShortVersionString" in plist
        assert isinstance(plist["NSHighResolutionCapable"], ast.Constant)

    def test_build_script_verifies_the_nested_signatures(self):
        # onedir puts real nested code (the bundled companion, every dylib)
        # inside the bundle; `codesign -dv` alone would not notice a broken
        # one, and the editor's Gatekeeper would.
        build_sh = (REPO_ROOT / "tools" / "build_onboard_macos.sh").read_text(encoding="utf-8")
        assert build_sh.count("--verify --all-architectures --deep --strict") >= 2, \
            "verify the built bundle AND the zip that actually ships"


# -- onboard.py's GUI-layer decisions, pinned via source (same pattern as
# test_steps.py's _onboard_method_source) -------------------------------------


def _onboard_source(name: str) -> str:
    import ast

    path = Path(steps.__file__).resolve().parent / "onboard.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"onboard.py has no method named {name!r} any more")


def test_onboard_clean_slate_dispatches_on_platform():
    source = _onboard_source("_clean_slate")
    assert "build_cleanup_plan_macos" in source
    assert "execute_cleanup_macos" in source
    assert "IS_MACOS" in source


def test_onboard_asks_the_role_question_on_every_platform():
    # Commercial deployments can run a Mac as the base rig, so the role page
    # is never skipped -- Welcome always goes to Role.
    source = _onboard_source("show_welcome")
    assert "next_=self.show_role" in source
    assert "show_tailscale if IS_MACOS" not in source


def test_onboard_base_worker_uses_a_launch_agent_on_mac():
    source = _onboard_source("_worker_base")
    assert "write_companion_launch_agent" in source
    assert "load_launch_agent" in source
    # ...and the registry Run value stays Windows-only.
    assert "register_companion_autostart" in source


def test_onboard_surfaces_the_resolve_mapping_warning():
    source = _onboard_source("_worker_editor")
    assert "resolve_mapping_warning" in source
