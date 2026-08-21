"""Source-level guards on the release SCRIPTS -- ship.ps1, release.ps1,
build_editor_package.ps1, check_deploy_drift.ps1 and the two release
workflows.

None of them has a suite of its own: they are PowerShell and YAML that drive
PyInstaller, signtool, a NAS and the dashboard's upgrade channel, so the only
thing that can be asserted on any host is their source text. Same approach,
and the same reason, as onboarding/tests/test_release_gates.py.

Every assertion is a defect the 2026-08-21 hunt found:

  installer-onboard-tools-1  onboard.exe -- the binary a FRESH INSTALL
                             double-clicks -- was the one artefact nothing
                             ever signed, and no gate or drift line said so
  installer-onboard-tools-2  release-windows.yml guarded a step on its OWN
                             step-level env, which a step `if` cannot see, so
                             the CI signing route was always skipped
  installer-onboard-tools-5  build_editor_package.ps1's package destination
                             was a hardcoded P:\\ path
  installer-onboard-tools-6  ship.ps1's "already published" probe downloaded
                             the whole exe with no timeout
  release-pipeline-3         ship.ps1 knew nothing about image mode: it
                             restarted the live dashboard for nothing and
                             could not pass its own health gate
  release-pipeline-4         the installer was never published through the
                             CI/feed path, so feed-only customers had none

Presence/ordering assertions on purpose: rewording a message must not fail
them, removing the gate must.
"""
from __future__ import annotations

import re
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent

SHIP = (TOOLS / "ship.ps1").read_text(encoding="utf-8")
RELEASE = (TOOLS / "release.ps1").read_text(encoding="utf-8")
SIGN = (TOOLS / "sign_windows_binary.ps1").read_text(encoding="utf-8")
DRIFT = (TOOLS / "check_deploy_drift.ps1").read_text(encoding="utf-8")
BUILD_PKG = (REPO / "installer" / "build_editor_package.ps1").read_text(encoding="utf-8")
WF_WINDOWS = (REPO / ".github" / "workflows" / "release-windows.yml").read_text(encoding="utf-8")
WF_MACOS = (REPO / ".github" / "workflows" / "release-macos.yml").read_text(encoding="utf-8")


class TestOnboardExeIsSigned:
    """installer-onboard-tools-1. tools/release.ps1 was the only signtool
    call site in the repo and it signed the companion exe only, so once a
    certificate existed every fresh install still met "Windows protected your
    PC" -- the exact outcome the certificate is bought to remove."""

    def test_there_is_one_shared_signing_script(self):
        assert "& $signtool @signArgs" in SIGN
        # ...and nobody else shells out to signtool directly any more. (The
        # ed25519 RECORD signing, $signPy, is a different signature entirely
        # -- see COMMERCIAL_READINESS.md item 4.)
        for name, text in (("release.ps1", RELEASE), ("build_editor_package.ps1", BUILD_PKG),
                           ("release-windows.yml", WF_WINDOWS)):
            code = "\n".join(line for line in text.splitlines()
                             if not line.strip().startswith("#"))
            assert "signtool.exe" not in code, f"{name} looks for signtool itself again"
            assert "@signtool" not in code and "& $signtool" not in code, \
                f"{name} has its own signtool call again"
            assert "sign_windows_binary.ps1" in text, f"{name} does not use the shared signer"

    def test_the_companion_build_still_signs(self):
        assert re.search(r"-File \$SignScript -Path \$ExePath", RELEASE)
        assert 'Join-Path $PSScriptRoot "sign_windows_binary.ps1"' in RELEASE

    def test_the_onboard_build_signs_the_exe_it_just_made(self):
        assert re.search(r"sign_windows_binary\.ps1['\"]?\)?\s*-Path\s+\$OnboardExePath", BUILD_PKG)

    def test_signing_is_never_fatal_merely_because_no_certificate_exists(self):
        # Refusing here would mean nobody can build anything until a
        # certificate is bought.
        assert "no CCSYNC_SIGN_THUMBPRINT and no CCSYNC_SIGN_PFX in the environment" in SIGN
        assert "exit 0" in SIGN.split("no CCSYNC_SIGN_THUMBPRINT")[1][:400]

    def test_make_current_refuses_an_unsigned_installer(self):
        gate = BUILD_PKG.index("$MakeCurrent -and -not $AllowUnsignedBinary")
        # ...and it refuses BEFORE the companion PUT, so a refused run leaves
        # the channel exactly as it was rather than half-published.
        assert gate < BUILD_PKG.index("Invoke-RestMethod -Method Put")
        assert "-AllowUnsignedBinary" in BUILD_PKG[gate:gate + 900]

    def test_ship_passes_its_own_override_through(self):
        assert '$pkgArgs += "-AllowUnsignedBinary"' in SHIP

    def test_the_drift_doctor_reports_the_installer_row(self):
        assert '$_.kind -eq "onboard" -and $_.is_current' in DRIFT
        assert "curOnboard.signed_binary" in DRIFT


class TestCiSigningRouteIsReachable:
    """installer-onboard-tools-2. A step's own `env:` block is applied AFTER
    its `if:` is evaluated, so `if: ${{ env.PFX_B64 != '' }}` beside
    `env: PFX_B64: ...` is always false and the step is always skipped."""

    def test_the_secret_is_lifted_to_job_level(self):
        job = WF_WINDOWS.split("jobs:", 1)[1].split("steps:", 1)[0]
        assert "PFX_B64: ${{ secrets.CCSYNC_SIGN_PFX_BASE64 }}" in job

    def test_no_step_guards_itself_on_its_own_env(self):
        assert "if: ${{ env.PFX_B64" not in WF_WINDOWS

    def test_the_decision_reaches_the_run_summary(self):
        materialise = WF_WINDOWS.split("materialise the signing certificate", 1)[1][:1200]
        assert "GITHUB_STEP_SUMMARY" in materialise
        assert "IsNullOrWhiteSpace($env:PFX_B64)" in materialise


class TestTheInstallerIsPublishableThroughTheFeed:
    """release-pipeline-4. No manifest beside onboard.exe meant
    tools/publish_latest.py had nothing to verify or sign, so a customer
    dashboard fed only from the vendor channel had an EMPTY installer page."""

    def test_windows_writes_and_uploads_an_onboard_manifest(self):
        assert "ccsync-onboard.json" in WF_WINDOWS
        upload = WF_WINDOWS.split("upload the build", 1)[1]
        assert "onboarding/dist/ccsync-onboard.json" in upload

    def test_macos_writes_one_too(self):
        assert "ccsync-onboard.json" in WF_MACOS

    def test_the_manifest_records_whether_tests_actually_ran(self):
        # publish_feed.py refuses a manifest that says tests_run=false
        # (OPS-1), so it must never say true on trust.
        assert "$testsRun = ($LASTEXITCODE -eq 0)" in WF_WINDOWS
        assert "tests_run     = $testsRun" in WF_WINDOWS
        assert 'tests=true' in WF_MACOS


class TestShipProbesAreCheap:
    """installer-onboard-tools-6. The companion probe pulled the WHOLE exe
    over the tailnet to learn "200", with no deadline at all."""

    def test_the_companion_probe_asks_for_one_byte_with_a_deadline(self):
        block = SHIP.split("companion/package/windows/$CompanionVersion", 1)[1][:400]
        assert '"-r", "0-0"' in block
        assert '"--max-time", "20"' in block

    def test_a_partial_response_counts_as_published(self):
        assert '$pubCode -eq "200" -or $pubCode -eq "206"' in SHIP


class TestShipKnowsAboutImageMode:
    """release-pipeline-3. In image mode install_dashboard_app.py pushes no
    code -- it only restarts the live container -- and ship's health gate
    (live == repo) then failed every ship after a dashboard VERSION bump,
    before the companion was built or published."""

    def test_it_reads_the_stack_mode(self):
        assert 'Get-SiteScalar -Path $SitePath -Section "stack" -Key "mode"' in SHIP
        assert '$ImageMode = ($StackMode -eq "image")' in SHIP

    def test_image_mode_does_not_deploy_or_restart(self):
        deploy = SHIP.index("python server\\install_dashboard_app.py @deployArgs")
        guard = SHIP.rindex("if ($ImageMode ", 0, deploy)
        assert "else {" in SHIP[guard:deploy]
        # ...except when -Recreate names a compose-level change, which image
        # mode does not make somebody else's job.
        assert "$ImageMode -and -not $Recreate" in SHIP

    def test_the_gate_becomes_live_at_least_repo(self):
        assert "Compare-Version $live $DashVersion) -ge 0" in SHIP

    def test_a_repo_ahead_of_the_container_says_how_to_ship_it(self):
        assert "publish_feed.py" in SHIP and "Settings > Packages > check" in SHIP

    def test_two_digit_minors_compare_as_numbers(self):
        # After 0.9.9 comes 0.10.0 (owner's rule 2026-08-18) and "0.10.0" is
        # LESS than "0.9.9" as a string, which would fail a good ship.
        assert "[int]$_" in SHIP.split("function Compare-Version", 1)[1][:800]


class TestPackageDestinationIsSiteData:
    """installer-onboard-tools-5. The one script tools\\ship.cmd calls with no
    -Destination had P:\\Assets\\Software\\CC_Sync baked into its param
    block."""

    def test_no_hardcoded_drive_in_the_default(self):
        param_block = BUILD_PKG.split("param(", 1)[1].split(")\n", 1)[0]
        assert 'P:\\Assets\\Software' not in param_block
        assert '[string]$Destination = ""' in param_block

    def test_it_is_derived_from_canonical_prefix(self):
        assert "function Get-CanonicalPrefix" in BUILD_PKG
        assert "canonical_prefix" in BUILD_PKG
        assert 'Join-Path $prefix "Assets\\Software\\CC_Sync"' in BUILD_PKG

    def test_a_missing_drive_is_named_before_anything_is_built(self):
        check = BUILD_PKG.index("does not exist on this machine")
        assert check < BUILD_PKG.index("rebuilding onboard.exe")


class TestTheDowngradeFloorMayNotExceedTheBuild:
    """CR-52 / CR-67 item 3. A stale CCSYNC_MIN_VERSION in the build
    environment produced a signed record saying "do not install below 0.9.54"
    over a 0.9.44 build. Every companion raises that floor the moment it SEES
    the offer and never lowers it, so one typo here refused the build, every
    earlier build and the corrected republish, on every machine in the fleet.
    tools/sign_release.py refuses to make one now; this script must not reach
    it in the first place."""

    def test_the_comparison_is_numeric_and_strict(self):
        assert "function Test-MinVersionAboveVersion" in BUILD_PKG
        parts = BUILD_PKG.split("function Get-DottedVersionParts", 1)[1][:900]
        # Two-digit minors compare as numbers (0.10.0 > 0.9.9, owner's rule
        # 2026-08-18), and a version we cannot fully rank is not ranked.
        assert "[int]$_" in parts
        assert r"'^[0-9]+(\.[0-9]+)*$'" in parts

    def test_it_refuses_before_pyinstaller_runs(self):
        """A build takes minutes; a typo should cost seconds."""
        preflight = BUILD_PKG.index("CCSYNC_MIN_VERSION is $preflightMin")
        assert preflight < BUILD_PKG.index("rebuilding companion exe with PyInstaller")

    def test_it_also_stands_between_a_bad_floor_and_a_signed_record(self):
        """The preflight can be skipped (the env var set after it, a
        -Destination-only run); the gate that matters is the one immediately
        before sign_release.py, and it covers the onboard publish too, which
        reuses $minVersion."""
        gate = BUILD_PKG.index("min_version $minVersion is ABOVE the version being packaged")
        assert gate < BUILD_PKG.index(r"tools\sign_release.py")

    def test_the_refusal_names_the_way_out(self):
        assert "Set CCSYNC_MIN_VERSION to $version or lower" in BUILD_PKG
        assert "CR-52" in BUILD_PKG
