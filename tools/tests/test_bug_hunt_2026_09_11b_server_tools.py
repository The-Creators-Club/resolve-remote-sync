"""Regression tests for the 2026-09-11b bug hunt, server-tools territory
(CR-264): the release tooling under tools/.

Like the 2026-09-11 file beside it, the decision halves are exercised by
RUNNING the PowerShell, not by reading it: they live in tools/ship_gates.ps1
so a real `powershell -NoProfile` can dot-source them and feed them facts.

  * server-tools-b-2: `rollout_platforms` buckets a NULL machine_state.platform
    as `unknown` while db.rollout_status buckets the same row as `windows`, so
    -EmitKindExtras was refused for ever on a platform that does not exist.
  * server-tools-b-1 / -b-3 / -b-4: what the drift doctor may say about /cards
    - an uncommitted checkout is not OK, a directory override is NOT CHECKED
    rather than an old commit, and a site with no Timeline Cards is not asked
    about them at all.
  * tests-2: the local gate's installer row must enumerate installer/tests,
    the way CI already does.
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
DRIFT = (TOOLS / "check_deploy_drift.ps1").read_text(encoding="utf-8")
RUN_ALL = (TOOLS / "run_all_tests.ps1").read_text(encoding="utf-8")
INSTALLER_TESTS = TOOLS.parent / "installer" / "tests"

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
needs_powershell = pytest.mark.skipif(
    POWERSHELL is None, reason="no PowerShell on this host")


def _run(script: str, **params) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "runner.ps1").write_text(script, encoding="utf-8")
        args = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(d / "runner.ps1"), "-Gates", str(GATES)]
        for key, value in params.items():
            if isinstance(value, (dict, list)):
                path = d / f"{key}.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                value = str(path)
            args += [f"-{key}", str(value)]
        proc = subprocess.run(args, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


EXTRAS_RUNNER = r"""
param([string]$Gates, [string]$Body)
. $Gates
$health = (Get-Content -Raw -LiteralPath $Body | ConvertFrom-Json)
$v = Get-KindExtrasVerdict -Health $health -Floor "0.9.55"
[pscustomobject]@{
    readable   = [bool]$v.Readable
    count      = @($v.Stragglers).Count
    stragglers = (@($v.Stragglers) -join " || ")
} | ConvertTo-Json -Compress
"""

CARDS_RUNNER = r"""
param([string]$Gates, [string]$Body)
. $Gates
$in = (Get-Content -Raw -LiteralPath $Body | ConvertFrom-Json)
$record = $in.record
if ("$($in.no_record)" -eq "True") { $record = $null }
$v = Get-CardsDeployVerdict -Record $record -Head "$($in.head)" `
        -Dirty ([int]$in.dirty) -SiteHasCards ([bool]::Parse("$($in.site)")) `
        -RecordPath "$($in.path)"
[pscustomobject]@{ kind = "$($v.Kind)"; text = "$($v.Text)" } | ConvertTo-Json -Compress
"""


def _channel(platform: str, version: str, behind: int = 0, total: int = 1) -> dict:
    return {"platform": platform, "current_version": version, "behind": behind,
            "refusing": 0, "machines_total": total,
            "machines_on_current": max(total - behind, 0),
            "made_current_at": "2026-09-01T00:00:00Z"}


# --------------------------------------------------------------------------
# server-tools-b-2
# --------------------------------------------------------------------------

@needs_powershell
class TestTheTwoRolloutBlocksAgreeOnANullPlatform:
    def test_an_unknown_bucket_is_not_a_phantom_straggler(self):
        body = {"rollout": [_channel("windows", "0.9.60", total=3),
                            _channel("darwin", "0.9.60")],
                "rollout_platforms": {"windows": 3, "darwin": 1, "unknown": 1}}
        v = _run(EXTRAS_RUNNER, Body=body)
        assert v["readable"] is True
        assert "unknown" not in v["stragglers"]
        assert v["count"] == 0, v["stragglers"]

    def test_an_empty_platform_name_is_not_one_either(self):
        body = {"rollout": [_channel("windows", "0.9.60", total=3)],
                "rollout_platforms": {"windows": 3, "": 2}}
        v = _run(EXTRAS_RUNNER, Body=body)
        assert v["count"] == 0, v["stragglers"]

    def test_a_real_uncovered_platform_is_still_a_straggler(self):
        """The control: the whole point of the block is a platform with
        computers and no current build."""
        body = {"rollout": [_channel("windows", "0.9.60", total=3)],
                "rollout_platforms": {"windows": 3, "darwin": 2}}
        v = _run(EXTRAS_RUNNER, Body=body)
        assert v["count"] == 1
        assert "darwin" in v["stragglers"]


# --------------------------------------------------------------------------
# server-tools-b-1 / -b-3 / -b-4, the drift doctor's /cards verdict
# --------------------------------------------------------------------------

@needs_powershell
class TestTheCardsVerdict:
    def _v(self, **kw):
        payload = {"record": kw.get("record"), "no_record": str(kw.get("record") is None),
                   "head": kw.get("head", ""), "dirty": kw.get("dirty", 0),
                   "site": str(kw.get("site", True)), "path": kw.get("path", "r.json")}
        return _run(CARDS_RUNNER, Body=payload)

    def _record(self, **kw):
        rec = {"commit": "a" * 40, "short": "a" * 12, "ref": "main",
               "repo": "E:\\Projects\\Editing", "subtree": "Resolve/MulticamPipeline"}
        rec.update(kw)
        return rec

    def test_a_shipped_head_with_no_edits_is_ok(self):
        v = self._v(record=self._record(), head="a" * 40, dirty=0)
        assert v["kind"] == "ok"

    def test_an_uncommitted_checkout_is_not_ok(self):
        """server-tools-b-1. head == commit is exactly the state an
        uncommitted wave produces, and it used to read as OK."""
        v = self._v(record=self._record(), head="a" * 40, dirty=4)
        assert v["kind"] == "drift"
        assert "4" in v["text"]
        assert "commit" in v["text"].lower()

    def test_a_directory_override_is_not_checked(self):
        """server-tools-b-3. An absent commit must not be readable as an old
        commit."""
        v = self._v(record={"commit": "", "override": "E:\\Projects\\Editing\\x",
                            "exported": "2026-09-11T20:00:00+0100"},
                    head="a" * 40)
        assert v["kind"] == "unknown"
        assert "NOT CHECKED" in v["text"]
        assert "E:\\Projects\\Editing\\x" in v["text"]

    def test_a_site_without_timeline_cards_is_not_asked(self):
        """server-tools-b-4. Every customer who did not buy Cards used to get
        a permanent '? NOT CHECKED, not OK' pointing at an internal runbook."""
        v = self._v(record=None, site=False)
        assert v["kind"] == "skip"

    def test_a_site_with_cards_and_no_record_is_still_not_checked(self):
        v = self._v(record=None, site=True)
        assert v["kind"] == "unknown"
        assert "NOT CHECKED" in v["text"]

    def test_a_moved_head_is_still_drift(self):
        v = self._v(record=self._record(), head="b" * 40, dirty=0)
        assert v["kind"] == "drift"


def test_the_doctor_asks_the_site_before_it_talks_about_cards():
    """The wiring half of server-tools-b-4: the section is reached through the
    verdict function above, with the site manifest as one of its inputs."""
    assert "Get-CardsDeployVerdict" in DRIFT
    assert 'Section "timeline_cards"' in DRIFT


# --------------------------------------------------------------------------
# tests-2
# --------------------------------------------------------------------------

def test_the_installer_row_enumerates_its_directory():
    """tests-2. The row hand-listed seven scripts; installer/tests holds eight
    since 2026-09-11, and Test-BinDirLeftovers.ps1 was in none of them - the
    local gate the owner runs before a ship never executed it. CI enumerates
    the directory (.github/workflows/ci.yml); this does now too, so the row
    cannot drift again."""
    row = RUN_ALL.split("=== installer (")[1].split("=== installer/macos")[0]
    assert "Get-ChildItem" in row and "installer\\tests" in row
    assert "Test-*.ps1" in row
    # comments may name a script (the one this finding is about does); what
    # must not name one is the CODE.
    code = "\n".join(line for line in row.splitlines()
                     if not line.lstrip().startswith("#"))
    named = sorted(p.name for p in INSTALLER_TESTS.glob("Test-*.ps1"))
    assert named, "installer/tests holds no table tests"
    for name in named:
        assert name not in code, (
            f"{name} is named one by one in run_all_tests.ps1: the row has to "
            f"enumerate the directory, or the next new script is missed again")


# --------------------------------------------------------------------------
# Hand-off wave: install-onboard-1 - the onboarding suite on a Mac
# --------------------------------------------------------------------------

def _ci_job(name: str) -> str:
    """The block of ci.yml belonging to one job, by indentation.

    Read as text on purpose: the tools suite is stdlib-only by design (no
    PyYAML in the dashboard venv), and what is being pinned is a step that
    must be IN that job, which a line scan can answer.
    """
    text = (TOOLS.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith(f"  {name}:"):
            inside = True
            continue
        if inside and line[:3].strip() and not line.startswith("   "):
            break
        if inside:
            out.append(line)
    assert out, f"no {name} job in ci.yml"
    return "\n".join(out)


def test_the_macos_job_runs_the_onboarding_suite():
    """install-onboard-1. The onboarding suite is the only suite whose subject
    is macOS-only behaviour and it ran on no Mac anywhere: os.path is ntpath on
    the Windows runners, whose ismount never reads a mount table, so the
    firmlink tests SKIPPED. Its own skip reason names this gap."""
    job = _ci_job("macos")
    assert "onboarding -- pytest" in job
    assert "-m pytest tests" in job
    # a Mac runner has no .venv/Scripts
    onboarding = job.split("onboarding -- install")[1]
    assert ".venv/bin/python" in onboarding and "Scripts" not in onboarding
    assert "--require-hashes -r onboarding/requirements.lock" in job


def test_the_two_onboarding_junit_files_do_not_collide():
    """Both jobs upload into one artefact namespace; the windows job's file is
    junit-onboarding.xml, so the macOS one has to be its own name."""
    assert "junit-onboarding.xml" in _ci_job("windows")
    assert "junit-onboarding-macos.xml" in _ci_job("macos")


# --------------------------------------------------------------------------
# Hand-off wave: dash-release-jobs - a manifest platform is not validated
# --------------------------------------------------------------------------

def test_a_manifest_platform_is_folded_and_re_validated(tmp_path, monkeypatch):
    """argparse's choices= guards --platform and nothing else, so a manifest
    was the one way a non-canonical platform ("Windows", "osx") reached a
    SIGNED record - published, verifiable, and claimed by no machine, because
    every reader matches the string exactly (CR-260d's shape)."""
    sys.path.insert(0, str(TOOLS))
    import publish_feed as pf  # noqa: PLC0415

    def _apply(platform: str):
        args = pf.parse_args(["--feed-dir", str(tmp_path / "feed")])
        pf._apply_manifest(args, {"version": "0.9.72", "platform": platform},
                           tmp_path)
        return args.platform

    assert _apply("Windows") == "windows"
    assert _apply(" macOS ") == "macos"
    assert _apply("") == ""

    with pytest.raises(pf.PublishFeedError) as caught:
        _apply("osx")
    assert "osx" in str(caught.value)
    assert caught.value.code == pf.EXIT_CONDEMNED
