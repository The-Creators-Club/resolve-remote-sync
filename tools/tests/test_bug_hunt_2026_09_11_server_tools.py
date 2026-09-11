"""Regression tests for the 2026-09-11 bug hunt, server-tools territory
(CR-247): the release tooling under tools/.

server-tools-1 is exercised by RUNNING the PowerShell, not by reading it: the
defect was `$null -eq @()` evaluating to $false, which no source-text
assertion can see. The decision half of the gate lives in tools/ship_gates.ps1
for exactly that reason, and these tests dot-source it in a real
`powershell -NoProfile` and feed it health bodies.

server-tools-5 is plain pytest against tools/jobs.py and tools/publish_package.py.
server-tools-6 is a source-text assertion on check_deploy_drift.ps1's watch
loop plus a PowerShell parse of the file.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
GATES = TOOLS / "ship_gates.ps1"
SHIP = (TOOLS / "ship.ps1").read_text(encoding="utf-8")
DRIFT = (TOOLS / "check_deploy_drift.ps1").read_text(encoding="utf-8")

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
needs_powershell = pytest.mark.skipif(
    POWERSHELL is None, reason="no PowerShell on this host")

RUNNER = r"""
param([string]$Gates, [string]$Body, [switch]$NoHealth)
. $Gates
$health = $null
if (-not $NoHealth) { $health = (Get-Content -Raw -LiteralPath $Body | ConvertFrom-Json) }
$v = Get-KindExtrasVerdict -Health $health -Floor "0.9.55"
$out = [pscustomobject]@{
    readable   = [bool]$v.Readable
    reason     = "$($v.Reason)"
    count      = @($v.Stragglers).Count
    stragglers = (@($v.Stragglers) -join " || ")
}
$out | ConvertTo-Json -Compress
"""


def _verdict(payload, *, no_health: bool = False) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "runner.ps1").write_text(RUNNER, encoding="utf-8")
        (d / "body.json").write_text(json.dumps(payload or {}), encoding="utf-8")
        args = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(d / "runner.ps1"),
                "-Gates", str(GATES), "-Body", str(d / "body.json")]
        if no_health:
            args.append("-NoHealth")
        proc = subprocess.run(args, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _channel(platform: str, version: str, behind: int = 0, total: int = 1) -> dict:
    return {"platform": platform, "current_version": version, "behind": behind,
            "refusing": 0, "machines_total": total,
            "machines_on_current": max(total - behind, 0),
            "made_current_at": "2026-09-01T00:00:00Z"}


@needs_powershell
class TestEmitKindExtrasFailsClosed:
    """server-tools-1. The gate that makes -EmitKindExtras impossible until
    the whole fleet is on 0.9.55+ answered "every reporting computer is on
    0.9.55 or newer" having examined nothing, on two different inputs. A
    record signed with the extra fields is refused permanently by a companion
    below the floor, and the recovery is a reinstall at that desk."""

    def test_an_empty_rollout_is_refused_not_waved_through(self):
        # api._rollout_block returns [] on ANY exception, with HTTP 200.
        v = _verdict({"version": "0.7.42", "rollout": []})
        assert v["readable"] is False
        assert "EMPTY" in v["reason"]

    def test_a_missing_rollout_is_refused(self):
        v = _verdict({"version": "0.7.42"})
        assert v["readable"] is False

    def test_a_null_rollout_is_refused(self):
        v = _verdict({"version": "0.7.42", "rollout": None})
        assert v["readable"] is False

    def test_no_health_at_all_is_refused(self):
        v = _verdict({}, no_health=True)
        assert v["readable"] is False

    def test_a_platform_with_computers_and_no_current_build_is_counted(self):
        # The leso-Mac-on-0.9.2 shape: two macOS computers report, no macOS
        # package is current, so db.rollout_status emits no macos channel.
        v = _verdict({
            "version": "0.7.42",
            "rollout": [_channel("windows", "0.9.70", behind=0, total=5)],
            "rollout_platforms": {"windows": 5, "macos": 2},
        })
        assert v["readable"] is True
        assert v["count"] == 1
        assert "macos" in v["stragglers"]
        assert "no current build" in v["stragglers"]

    def test_a_dashboard_that_cannot_count_computers_is_unreadable(self):
        v = _verdict({"version": "0.7.42",
                      "rollout": [_channel("windows", "0.9.70", total=5)]})
        assert v["readable"] is False
        assert "rollout_platforms" in v["reason"]

    def test_a_fleet_that_is_wholly_current_passes(self):
        v = _verdict({
            "version": "0.7.42",
            "rollout": [_channel("windows", "0.9.70", behind=0, total=5),
                        _channel("macos", "0.9.70", behind=0, total=2)],
            "rollout_platforms": {"windows": 5, "macos": 2},
        })
        assert v["readable"] is True
        assert v["count"] == 0, v["stragglers"]

    def test_a_platform_below_the_floor_is_a_straggler(self):
        v = _verdict({
            "version": "0.7.42",
            "rollout": [_channel("windows", "0.9.54", total=5)],
            "rollout_platforms": {"windows": 5},
        })
        assert v["count"] == 1
        assert "0.9.54" in v["stragglers"]

    def test_a_computer_behind_the_current_build_is_a_straggler(self):
        v = _verdict({
            "version": "0.7.42",
            "rollout": [_channel("windows", "0.9.70", behind=2, total=5)],
            "rollout_platforms": {"windows": 5},
        })
        assert v["count"] == 1
        assert "behind" in v["stragglers"]

    def test_a_platform_with_no_computers_needs_no_channel(self):
        v = _verdict({
            "version": "0.7.42",
            "rollout": [_channel("windows", "0.9.70", total=5)],
            "rollout_platforms": {"windows": 5, "macos": 0},
        })
        assert v["count"] == 0, v["stragglers"]


class TestShipUsesTheTestedGate:
    """The refusal messages and the exits stay in ship.ps1; only the verdict
    moved. If the gate is ever inlined again, this fails."""

    def test_ship_asks_the_helper(self):
        assert ". (Join-Path $PSScriptRoot \"ship_gates.ps1\")" in SHIP
        block = SHIP[SHIP.index("if ($EmitKindExtras) {"):]
        block = block[:block.index("# SYS-7")]
        assert "Get-KindExtrasVerdict" in block
        assert "could not read the fleet's versions" in block
        assert "exit 1" in block
        # The comparison that failed open is gone for good.
        assert "$null -eq $health.rollout" not in SHIP


@needs_powershell
class TestTheReleaseScriptsParse:
    @pytest.mark.parametrize("name", ["ship.ps1", "ship_gates.ps1",
                                      "check_deploy_drift.ps1"])
    def test_parses(self, name):
        script = (
            "$ErrorActionPreference='Stop';"
            "$t=$null;$e=$null;"
            f"[System.Management.Automation.Language.Parser]::ParseFile('{TOOLS / name}',"
            "[ref]$t,[ref]$e) | Out-Null;"
            "if ($e -and $e.Count) { $e | ForEach-Object { $_.Message }; exit 1 }"
        )
        proc = subprocess.run([POWERSHELL, "-NoProfile", "-Command", script],
                              capture_output=True, text=True, timeout=180)
        assert proc.returncode == 0, proc.stdout + proc.stderr


class TestUnreachableDashboardIsASentence:
    """server-tools-5. `Http.send` caught HTTPError only, so a dashboard that
    is rebooting (URLError, socket.timeout, a TLS failure) came back as an
    unhandled urllib traceback from a tool whose every other failure is a
    sentence naming the next action."""

    @staticmethod
    def _module(name):
        sys.path.insert(0, str(TOOLS))
        try:
            return __import__(name)
        finally:
            sys.path.pop(0)

    @staticmethod
    def _raising_opener(exc):
        class _Opener:
            def open(self, *a, **k):
                raise exc
        return _Opener()

    def test_jobs_cli_names_the_unreachable_url(self):
        import urllib.error

        jobs = self._module("jobs")
        http = jobs.Http()
        http.opener = self._raising_opener(
            urllib.error.URLError("Connection refused"))
        with pytest.raises(jobs.JobsError) as ei:
            http.send("GET", "https://nas.example.invalid:8765/api/v1/jobs")
        msg = str(ei.value)
        assert "nas.example.invalid" in msg
        assert "Connection refused" in msg
        assert ei.value.code == jobs.EXIT_CALL

    def test_jobs_cli_names_a_timeout(self):
        jobs = self._module("jobs")
        http = jobs.Http()
        http.opener = self._raising_opener(TimeoutError("timed out"))
        with pytest.raises(jobs.JobsError) as ei:
            http.send("GET", "http://d.invalid/api/v1/jobs")
        assert "d.invalid" in str(ei.value)

    def test_publish_package_names_the_unreachable_url(self):
        import urllib.error

        pp = self._module("publish_package")
        http = pp.Http()
        http.opener = self._raising_opener(
            urllib.error.URLError("getaddrinfo failed"))
        with pytest.raises(pp.PublishError) as ei:
            http.send("GET", "https://nas.example.invalid:8765/api/v1/admin/packages")
        msg = str(ei.value)
        assert "nas.example.invalid" in msg
        assert "Nothing was" in msg


class TestTheWatchLoopGivesUp:
    """server-tools-6. -Watch caught every failure of the admin packages GET,
    printed one line and slept 60 s for ever, with no ceiling and no way to
    say "your session expired" - which is guaranteed on a long rollout,
    because the session is minted once before the report."""

    def test_the_loop_counts_consecutive_failures(self):
        body = DRIFT[DRIFT.index("ROLLOUT WATCH"):]
        assert "$watchFailures" in body
        assert "WatchFailureCeiling" in body or "$watchFailureCeiling" in body

    def test_it_names_the_expired_session(self):
        body = DRIFT[DRIFT.index("ROLLOUT WATCH"):]
        assert "admin session" in body
        assert "-AdminUser" in body
