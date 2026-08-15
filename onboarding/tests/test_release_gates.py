"""Source-level guards on the scripts that BUILD AND PUBLISH onboard.exe and
its macOS twin -- the artifacts this suite exists to protect (tools/ship.ps1
step 0b: "onboarding/ guards the OTHER artifact step 2 publishes").

None of those scripts has a suite of its own: they are PowerShell and bash that
talk to PyInstaller, a share on the NAS and the dashboard's upgrade channel, so
the only thing that can be asserted on any host is their source text. Same
approach, and the same reason, as TestShWizardContract in test_macos_steps.py.

Every assertion here is a defect the 2026-08-14 bug hunt found live:

  SHIP-1  a failed -RebuildOnboard PyInstaller run still published YESTERDAY'S
          onboard.exe under the NEW installer version (the OPS-7 fix had only
          ever been applied to the companion half)
  SHIP-8  the CR byte-scan on macos_bootstrap.sh ran only under -Publish, while
          the file is copied onto the share on EVERY run
  SHIP-12 the macOS wizard publish asked the server nothing until the PUT --
          after PyInstaller, two codesign passes, a zip and a password prompt
  SHIP-3  the macOS release had no vendored-ytdl_common parity gate
  SHIP-11 the Windows release accepted a VERSION the dashboard would 422

They are ordering/presence assertions on purpose: rewording a message must not
fail them, removing the gate must.
"""

from __future__ import annotations

from pathlib import Path

import steps

REPO_ROOT = Path(steps.__file__).resolve().parent.parent

BUILD_PKG = (REPO_ROOT / "installer" / "build_editor_package.ps1").read_text(encoding="utf-8")
WIZARD_SH = (REPO_ROOT / "tools" / "build_onboard_macos.sh").read_text(encoding="utf-8")
RELEASE_PS1 = (REPO_ROOT / "tools" / "release.ps1").read_text(encoding="utf-8")
RELEASE_SH = (REPO_ROOT / "tools" / "release_macos.sh").read_text(encoding="utf-8")

SEMVER_GATE = r"^[0-9]+\.[0-9]+\.[0-9]+$"


def _occurrences(text: str, needle: str) -> list[int]:
    out: list[int] = []
    start = text.find(needle)
    while start >= 0:
        out.append(start)
        start = text.find(needle, start + 1)
    return out


class TestFailedOnboardBuildCannotBePublished:
    """SHIP-1. The mtime test that was the only thing in the way is satisfied
    whenever the companion exe was NOT rebuilt in the same run -- which is
    exactly the R13 recovery invocation (-RebuildOnboard -Publish -MakeCurrent,
    no -RebuildExe)."""

    def test_the_onboard_pyinstaller_exit_code_is_kept(self):
        assert "$script:OnboardPyInstallerExit = $LASTEXITCODE" in BUILD_PKG

    def test_a_failed_onboard_build_fails_the_run(self):
        # Somewhere the exit code must reach Set-Failed -- warning about it and
        # carrying on (which is all it used to do) leaves ship's $LASTEXITCODE
        # gate reading success.
        guards = _occurrences(BUILD_PKG, "if ($script:OnboardPyInstallerExit -ne 0)")
        assert guards, "the onboard build's exit code is not tested at all"
        assert any("Set-Failed" in BUILD_PKG[g:g + 400] for g in guards)

    def test_the_publish_chain_consults_it_before_any_staleness_heuristic(self):
        chain = BUILD_PKG.index("$onboardSkipReason = ")
        exit_test = BUILD_PKG.index("$script:OnboardPyInstallerExit -ne 0", chain - 400)
        mtime_test = BUILD_PKG.index("is OLDER than the companion exe")
        assert exit_test < mtime_test


class TestTheMacBootstrapIsCrScannedOnEveryRun:
    """SHIP-8. macos_bootstrap.sh is $Files entry 6 and lands on P:\\ whether or
    not the run publishes; a CR makes a Mac's bash die on line 1 ("set -eu" ->
    "Illegal option -")."""

    def test_the_scan_happens_before_the_copy_loop(self):
        scan = BUILD_PKG.index("Test-FileHasCr -Path $bootstrapSh")
        copy_loop = BUILD_PKG.index("foreach ($f in $Files)")
        assert scan < copy_loop

    def test_the_scan_is_not_inside_the_publish_block(self):
        scan = BUILD_PKG.index("Test-FileHasCr -Path $bootstrapSh")
        publish_block = BUILD_PKG.index("if ($Publish) {")
        assert scan < publish_block

    def test_a_dirty_script_fails_the_run(self):
        scan = BUILD_PKG.index("Test-FileHasCr -Path $bootstrapSh")
        assert "Set-Failed" in BUILD_PKG[scan:scan + 400]


class TestTheWizardPublishAsksBeforeItBuilds:
    """SHIP-12. release_macos.sh's own words: "discovering that after a
    password prompt wastes the run"."""

    def test_the_already_published_probe_precedes_pyinstaller(self):
        probe = WIZARD_SH.index("/api/v1/companion/package/macos/$ONBOARD_VERSION?kind=onboard")
        build = WIZARD_SH.index("-m PyInstaller build_onboard_macos.spec")
        assert probe < build

    def test_the_probe_keeps_the_token_off_the_command_line(self):
        probe = WIZARD_SH.index("/api/v1/companion/package/macos/$ONBOARD_VERSION?kind=onboard")
        window = WIZARD_SH[probe - 600:probe]
        assert "-K -" in window  # curl reads the header from stdin
        assert "-r 0-0" in window  # one byte, not the whole package

    def test_a_409_distinguishes_identical_bytes_from_different_ones(self):
        branch = WIZARD_SH.index('if [ "$PUT_CODE" = "409" ]')
        window = WIZARD_SH[branch:branch + 1600]
        assert "x-ccsync-sha256" in window.lower()
        assert "$ZIP_SHA" in window


class TestTheTwoReleaseScriptsStayTwins:
    """SHIP-3 / SHIP-11. Each script had a gate the other lacked, and the Mac
    cannot run the suite (server/) that pins the vendored pair."""

    def test_both_refuse_a_version_the_dashboard_would_422(self):
        assert SEMVER_GATE in RELEASE_PS1
        assert SEMVER_GATE in RELEASE_SH

    def test_both_refuse_a_drifted_vendored_ytdl_common(self):
        for text in (RELEASE_PS1, RELEASE_SH):
            assert "ytdl_common.py" in text
            assert "# --- vendored content below, byte-identical ---" in text

    def test_the_mac_vendor_gate_fails_safe_on_a_missing_file(self):
        fn = RELEASE_SH.index("vendor_parity_problem() {")
        window = RELEASE_SH[fn:fn + 1800]
        assert "refusing rather than skipping the check" in window
        assert "cmp -s" in window
