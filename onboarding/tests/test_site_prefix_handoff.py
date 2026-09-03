"""The tree drive letter must survive ONE failed manifest fetch
(bug-hunt-2026-09-03 install-onboard-1 and -2).

`fetch_site` returns {} on ANY error by contract, and the wizard and
windows_bootstrap.ps1 fetched the manifest separately: whichever half's fetch
failed fell back to a literal "P:\\", while the other half used the site's
real answer. The two failure shapes are symmetrical and both leave a machine
nothing later reconciles -- config.toml naming one drive, the mapping, the
logon task, the loopback share and the uninstaller's cleanup list naming
another.

Nothing here may depend on the developer's own ~/.ccsync: every site value is
passed or stubbed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import steps
from ccsync_companion import site as site_mod


REPO_ROOT = Path(steps.__file__).resolve().parent.parent
BOOTSTRAP_PS1 = REPO_ROOT / "installer" / "windows_bootstrap.ps1"
BOOTSTRAP_SH = REPO_ROOT / "installer" / "macos_bootstrap.sh"

Q_CACHE = {"tree_name": "Creators_Club", "canonical_prefix": "Q:\\"}


class _FakeResult:
    returncode = 0
    stdout = ""
    stderr = ""


# -- install-onboard-1: the wizard's own write ---------------------------------

class TestEnsureConfigResolvesThePrefixLikeEverySibling:
    @pytest.fixture(autouse=True)
    def _cached_q_site(self, monkeypatch):
        monkeypatch.setattr(site_mod, "cached_site", lambda: dict(Q_CACHE))

    def _write(self, tmp_path, site, role="editor"):
        path = tmp_path / "config.toml"
        steps.ensure_config(role, editor_name="jane",
                            dashboard_url="http://dash.example:8480",
                            dashboard_token="tok", config_path=path,
                            site=site, platform="win32")
        return path.read_text(encoding="utf-8")

    def test_an_empty_manifest_falls_back_to_the_cache(self, tmp_path):
        # The verifier's repro: the cache says Q:, the fetch returned {}.
        text = self._write(tmp_path, {})
        assert 'canonical_prefix = "Q:\\\\"' in text
        assert 'canonical_prefix = "P:' not in text

    def test_no_manifest_at_all_falls_back_to_the_cache(self, tmp_path):
        text = self._write(tmp_path, None)
        assert 'canonical_prefix = "Q:\\\\"' in text

    def test_a_fetched_manifest_still_wins_over_the_cache(self, tmp_path):
        text = self._write(tmp_path, {"canonical_prefix": "R:\\"})
        assert 'canonical_prefix = "R:\\\\"' in text

    def test_the_default_survives_when_nothing_knows(self, tmp_path, monkeypatch):
        monkeypatch.setattr(site_mod, "cached_site", lambda: {})
        text = self._write(tmp_path, {})
        assert 'canonical_prefix = "P:\\\\"' in text

    def test_a_base_rig_still_stores_its_local_root(self, tmp_path):
        """canon.py's base-rig identity case: everything on that drive
        outside the tree is out-of-tree, so the prefix IS the local root and
        the site's letter has nothing to do with it."""
        path = tmp_path / "config.toml"
        steps.ensure_config("base", editor_name="jane",
                            dashboard_url="http://dash.example:8480",
                            dashboard_token="tok", local_root="E:\\Tree",
                            config_path=path, site={}, platform="win32")
        text = path.read_text(encoding="utf-8")
        assert 'canonical_prefix = "E:\\\\Tree"' in text


class TestSiteCanonicalPrefix:
    def test_it_normalises_to_the_bootstraps_shape(self):
        assert steps.site_canonical_prefix({"canonical_prefix": "q:/"}) == "Q:\\"

    def test_a_prefix_windows_cannot_mount_degrades_like_the_letter_does(self):
        for prefix in (r"\\nas\share", "/Volumes/Media", "P:\\Projects", ""):
            assert steps.site_canonical_prefix({"canonical_prefix": prefix}) == "P:\\"

    def test_it_agrees_with_site_drive_letter(self, monkeypatch):
        monkeypatch.setattr(site_mod, "cached_site", lambda: dict(Q_CACHE))
        assert steps.site_canonical_prefix() == f"{steps.site_drive_letter()}:\\"


# -- install-onboard-2: the handoff to the bootstrap --------------------------

def _run_bootstrap(tmp_path, platform, site, name):
    script = tmp_path / name
    script.write_text("# fake")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeResult()

    steps.run_bootstrap(
        editor_name="jsmith", dashboard_token="tok", tailnet_host="dash.example",
        dashboard_url="http://dash.example:8480", run=fake_run,
        script_path=script, platform=platform, site=site,
    )
    return captured


class TestTheBootstrapIsToldTheLetterTheWizardUsed:
    def test_windows_gets_both_keys(self, tmp_path):
        cmd = _run_bootstrap(
            tmp_path, "win32",
            {"canonical_prefix": "Q:\\", "tree_name": "Creators_Club"},
            "windows_bootstrap.ps1")["cmd"]
        assert cmd[cmd.index("-CanonicalPrefix") + 1] == "Q:\\"
        assert cmd[cmd.index("-TreeName") + 1] == "Creators_Club"

    def test_macos_gets_both_keys_in_the_environment(self, tmp_path):
        env = _run_bootstrap(
            tmp_path, "darwin",
            {"canonical_prefix": "Q:\\", "tree_name": "Creators_Club"},
            "macos_bootstrap.sh")["kwargs"]["env"]
        assert env["CCSYNC_CANONICAL_PREFIX"] == "Q:\\"
        assert env["CCSYNC_TREE_NAME"] == "Creators_Club"

    def test_nothing_is_invented_when_the_wizard_has_no_manifest(self, tmp_path):
        """The 404 case: the scripts' own fetch-then-fall-back must decide.
        Passing OUR fallback would beat their fetch and defeat the point."""
        captured = _run_bootstrap(tmp_path, "win32", None, "windows_bootstrap.ps1")
        assert "-CanonicalPrefix" not in captured["cmd"]
        assert "-TreeName" not in captured["cmd"]
        env = _run_bootstrap(tmp_path, "darwin", None, "macos_bootstrap.sh")["kwargs"]["env"]
        assert "CCSYNC_CANONICAL_PREFIX" not in env
        assert "CCSYNC_TREE_NAME" not in env


class TestEveryManifestKeyRunBootstrapHoldsCanBePassedOn:
    """The test that would have caught install-onboard-2: run_bootstrap read
    six manifest keys and could only pass four on, so the other two were
    fetched a second time by the script -- with a different answer whenever
    one of the two fetches failed."""

    # manifest key -> how it reaches windows_bootstrap.ps1 / macos_bootstrap.sh
    HANDOFF = {
        "remote_root": ("-RemoteRoot", "--remote-root"),
        "nas_syncthing_id": ("-NasSyncthingId", "CCSYNC_NAS_SYNCTHING_ID"),
        "sftp_host": ("-TailnetHost", "--tailnet-host"),
        "sftp_port": ("-SftpPort", "--sftp-port"),
        "canonical_prefix": ("-CanonicalPrefix", "CCSYNC_CANONICAL_PREFIX"),
        "tree_name": ("-TreeName", "CCSYNC_TREE_NAME"),
    }

    def _run_bootstrap_source(self) -> str:
        source = Path(steps.__file__).read_text(encoding="utf-8")
        start = source.index("def run_bootstrap(")
        end = source.index("\ndef parse_device_id(", start)
        return source[start:end]

    def test_the_table_is_the_whole_set_of_keys_it_reads(self):
        keys = set(re.findall(r'site\.get\("([a-z_]+)"', self._run_bootstrap_source()))
        assert keys == set(self.HANDOFF), (
            "a manifest key run_bootstrap reads with no way to hand it to the "
            "bootstrap is install-onboard-2 again")

    def test_the_windows_bootstrap_declares_every_flag(self):
        text = BOOTSTRAP_PS1.read_text(encoding="utf-8")
        params = text[text.index("\nparam("):text.index("\n)\n", text.index("\nparam("))]
        for key, (flag, _mac) in self.HANDOFF.items():
            assert re.search(r"\$" + flag[1:] + r"\b", params), f"{key}: no {flag}"

    def test_the_macos_bootstrap_reads_every_flag_or_env_var(self):
        text = BOOTSTRAP_SH.read_text(encoding="utf-8")
        for key, (_win, mac) in self.HANDOFF.items():
            assert mac in text, f"{key}: macos_bootstrap.sh never reads {mac}"

    def test_the_wizard_passes_the_manifest_and_not_config_toml(self):
        """A base rig stores its LOCAL ROOT in canonical_prefix, which both
        bootstraps refuse as not-a-drive-letter. Only the fetched manifest may
        reach the flag."""
        body = self._run_bootstrap_source()
        assert 'canonical_prefix = str(site.get("canonical_prefix")' in body


# -- install-onboard-4: the guard exists on macOS too --------------------------

class TestForbiddenDriveOnMacOS:
    @pytest.fixture(autouse=True)
    def _frozen(self, monkeypatch):
        monkeypatch.setattr(steps.sys, "frozen", True, raising=False)

    def test_running_from_a_mounted_volume_is_refused(self, monkeypatch):
        monkeypatch.setattr(
            steps.sys, "executable",
            "/Volumes/TheCreatorsPool/Assets/Software/onboard.app/Contents/MacOS/onboard")
        assert steps.installer_on_forbidden_drive(
            platform="darwin", is_mount=lambda p: False) is True

    def test_any_other_mount_point_is_refused_too(self, monkeypatch):
        # An external SSD mounted somewhere other than /Volumes: the install
        # is about to write a whole tree onto it.
        monkeypatch.setattr(steps.sys, "executable", "/mnt/t7/software/onboard")
        assert steps.installer_on_forbidden_drive(
            platform="darwin", is_mount=lambda p: p == "/mnt/t7") is True

    def test_the_boot_volume_is_fine(self, monkeypatch):
        monkeypatch.setattr(steps.sys, "executable", "/Users/leso/Desktop/onboard")
        assert steps.installer_on_forbidden_drive(
            platform="darwin", is_mount=lambda p: False) is False

    def test_an_unreadable_mount_table_never_refuses(self, monkeypatch):
        def boom(path):
            raise OSError("no")
        monkeypatch.setattr(steps.sys, "executable", "/Users/leso/Desktop/onboard")
        assert steps.installer_on_forbidden_drive(
            platform="darwin", is_mount=boom) is False

    def test_an_unfrozen_wizard_is_never_refused(self, monkeypatch):
        monkeypatch.setattr(steps.sys, "frozen", False, raising=False)
        monkeypatch.setattr(steps.sys, "executable", "/Volumes/Pool/onboard")
        assert steps.installer_on_forbidden_drive(
            platform="darwin", is_mount=lambda p: True) is False

    def test_the_windows_rule_is_unchanged(self, monkeypatch):
        monkeypatch.setattr(steps.sys, "executable", r"Q:\Assets\Software\onboard.exe")
        assert steps.installer_on_forbidden_drive(
            {"canonical_prefix": "Q:\\"}, platform="win32") is True
        monkeypatch.setattr(steps.sys, "executable", r"C:\Users\me\Desktop\onboard.exe")
        assert steps.installer_on_forbidden_drive(
            {"canonical_prefix": "Q:\\"}, platform="win32") is False
