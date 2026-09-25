"""The 2026-09-24 hunt, wave 2 (mediums and lows), release-tools group.

logic-release-2  a --retract of the build `current` points at left the pair
                 with no pointer, and a dashboard with no pointer takes the
                 highest version, so a newer STAGED build became what every
                 `policy = current` site took, on the command meant to roll
                 the fleet BACK.
logic-release-6  "re-run with --make-current" answered "nothing to do": the
                 already-published skip ignored the flag and the pointer
                 never moved.
logic-release-7  nothing could move the pointer alone, so the vendor feed
                 could not be rolled back to a build it still carried;
                 RELEASE.md called --allow-older the rollback.
logic-release-5  publish_latest's SYS-7 gate judged a requires_dashboard the
                 signer drops (kind extras off), and the NOTE saying so went
                 to a stderr that was discarded on success.
bug-ops-3        the recall line publish_latest printed did not parse.
bug-ops-2        ship.cmd -Resume past the publish died on the "already
                 published" probe and told the owner to bump the version.

Nothing here touches the network, `gh`, the real release key or the live
dashboard: publish_feed runs against a tmp feed dir and a tmp key, and
publish_latest's subprocess seam (`run`) is replaced.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "companion" / "src"))

import publish_feed as pf  # noqa: E402
import publish_latest as pl  # noqa: E402
import release_key as release_key_mod  # noqa: E402

BASE_URL = "https://releases.example.test/v1"


@pytest.fixture
def key(tmp_path, monkeypatch):
    path = tmp_path / "release.key"
    monkeypatch.setenv("CCSYNC_RELEASE_KEY", str(path))
    assert release_key_mod.main(["new"]) == 0
    return path


def _record(kind, platform, version, *, sha="0" * 64):
    filename = f"ccsync-{kind}-{version}-{platform}.bin"
    return {"kind": kind, "platform": platform, "version": version, "filename": filename,
            "sha256": sha, "size_bytes": 1, "min_version": "0.0.0",
            "signed_binary": False, "published_at": "2026-09-01T00:00:00Z",
            "url": f"{BASE_URL}/{platform}/{filename}", "signature": "x", "pubkey_id": "y"}


def _feed(tmp_path, versions, current, *, retracted=()):
    """A local feed dir whose channel.json carries companion/windows
    `versions` with `current` pointing at `current` (None: no pointer)."""
    feed = tmp_path / "feed"
    feed.mkdir(parents=True, exist_ok=True)
    channel = {"schema": pf.SCHEMA, "channel": "stable", "generated_at": "",
               "pubkey_id": "", "dashboard_image": {"tag": "", "digest": ""},
               "packages": [_record("companion", "windows", v) for v in versions]}
    if current:
        channel["current"] = {"companion/windows": current}
    if retracted:
        channel["retracted"] = [{"kind": "companion", "platform": "windows", "version": v,
                                 "reason": "bad", "at": "2026-09-01T00:00:00Z"}
                                for v in retracted]
    (feed / pf.CHANNEL_FILENAME).write_text(json.dumps(channel), encoding="utf-8")
    return feed


def _channel(feed):
    return json.loads((feed / pf.CHANNEL_FILENAME).read_text(encoding="utf-8"))


def _offered(channel):
    """What a customer dashboard on `policy = current` would select, by the
    dashboard's own function when it imports here, else its documented rule."""
    try:
        sys.path.insert(0, str(REPO / "dashboard" / "src"))
        from ccsync_dashboard import release_feed  # noqa: WPS433
        chosen = release_feed.select_offered_records(channel["packages"], channel)
        rec = chosen.get(("companion", "windows"))
        return rec["version"] if rec else None
    except Exception:  # pragma: no cover - a venv without the dashboard deps
        named = (channel.get("current") or {}).get("companion/windows")
        versions = [p["version"] for p in channel["packages"]]
        if named is not None:
            return named if named in versions else None
        return max(versions, key=pl.version_tuple) if versions else None


# --- logic-release-2: a retract of the current build must name its successor --


def test_retracting_the_current_build_with_a_newer_staged_one_is_refused(key, tmp_path, capsys):
    feed = _feed(tmp_path, ["0.9.77", "0.9.78", "0.9.79"], "0.9.78")
    before = (feed / pf.CHANNEL_FILENAME).read_bytes()
    rc = pf.main(["--retract", "companion/windows/0.9.78", "--reason", "it eats proxies",
                  "--feed-dir", str(feed)])
    assert rc == pf.EXIT_USAGE
    err = capsys.readouterr().err
    # It names what customers would have received, and the rollback it means.
    assert "0.9.79" in err and "NEWER" in err
    assert "--set-current companion/windows/0.9.77" in err
    # Nothing was written: the refusal precedes the signed write.
    assert (feed / pf.CHANNEL_FILENAME).read_bytes() == before


def test_retract_with_set_current_rolls_the_fleet_back(key, tmp_path):
    feed = _feed(tmp_path, ["0.9.77", "0.9.78", "0.9.79"], "0.9.78")
    rc = pf.main(["--retract", "companion/windows/0.9.78", "--reason", "it eats proxies",
                  "--set-current", "companion/windows/0.9.77", "--feed-dir", str(feed)])
    assert rc == pf.EXIT_OK
    channel = _channel(feed)
    assert channel["current"] == {"companion/windows": "0.9.77"}
    assert _offered(channel) == "0.9.77"


def test_allow_no_current_keeps_the_old_highest_wins_on_purpose(key, tmp_path):
    feed = _feed(tmp_path, ["0.9.77", "0.9.78", "0.9.79"], "0.9.78")
    rc = pf.main(["--retract", "companion/windows/0.9.78", "--reason", "it eats proxies",
                  "--allow-no-current", "--feed-dir", str(feed)])
    assert rc == pf.EXIT_OK
    assert "companion/windows" not in (_channel(feed).get("current") or {})


def test_retracting_a_build_that_is_not_current_needs_nothing_more(key, tmp_path):
    feed = _feed(tmp_path, ["0.9.77", "0.9.78", "0.9.79"], "0.9.78")
    rc = pf.main(["--retract", "companion/windows/0.9.79", "--reason", "never mind",
                  "--feed-dir", str(feed)])
    assert rc == pf.EXIT_OK
    assert _channel(feed)["current"] == {"companion/windows": "0.9.78"}


def test_retracting_the_only_build_of_a_pair_needs_nothing_more(key, tmp_path):
    feed = _feed(tmp_path, ["0.9.78"], "0.9.78")
    rc = pf.main(["--retract", "companion/windows/0.9.78", "--reason", "bad",
                  "--feed-dir", str(feed)])
    assert rc == pf.EXIT_OK


# --- logic-release-7 / -6: the pointer moves alone -----------------------------


def test_set_current_alone_makes_a_staged_record_current(key, tmp_path, capsys):
    feed = _feed(tmp_path, ["0.9.78", "0.9.79"], "0.9.78")
    rc = pf.main(["--set-current", "companion/windows/0.9.79", "--feed-dir", str(feed)])
    assert rc == pf.EXIT_OK
    channel = _channel(feed)
    assert channel["current"] == {"companion/windows": "0.9.79"}
    assert len(channel["packages"]) == 2
    assert "pointer only" in capsys.readouterr().out


def test_set_current_rolls_back_to_an_older_record(key, tmp_path):
    feed = _feed(tmp_path, ["0.9.77", "0.9.78"], "0.9.78")
    assert pf.main(["--set-current", "companion/windows/0.9.77",
                    "--feed-dir", str(feed)]) == pf.EXIT_OK
    assert _offered(_channel(feed)) == "0.9.77"


def test_set_current_refuses_a_version_the_channel_does_not_carry(key, tmp_path, capsys):
    feed = _feed(tmp_path, ["0.9.78"], "0.9.78")
    assert pf.main(["--set-current", "companion/windows/0.9.99",
                    "--feed-dir", str(feed)]) == pf.EXIT_USAGE
    assert "carries no such record" in capsys.readouterr().err
    assert _channel(feed)["current"] == {"companion/windows": "0.9.78"}


def test_set_current_refuses_a_recalled_build(key, tmp_path, capsys):
    feed = _feed(tmp_path, ["0.9.77", "0.9.78"], "0.9.78", retracted=["0.9.77"])
    assert pf.main(["--set-current", "companion/windows/0.9.77",
                    "--feed-dir", str(feed)]) == pf.EXIT_USAGE
    assert "RECALL" in capsys.readouterr().err


def test_set_current_to_the_build_the_same_run_retracts_is_refused(key, tmp_path):
    feed = _feed(tmp_path, ["0.9.77", "0.9.78"], "0.9.78")
    assert pf.main(["--retract", "companion/windows/0.9.78", "--reason", "bad",
                    "--set-current", "companion/windows/0.9.78",
                    "--feed-dir", str(feed)]) == pf.EXIT_USAGE


def test_set_current_applies_the_key_rotation_check(key, tmp_path, capsys):
    feed = _feed(tmp_path, ["0.9.78", "0.9.79"], "0.9.78")
    channel = _channel(feed)
    channel["packages"][0]["baked_pubkey_ids"] = ["oldkey"]
    channel["packages"][1]["pubkey_id"] = "newkey"
    (feed / pf.CHANNEL_FILENAME).write_text(json.dumps(channel), encoding="utf-8")
    assert pf.main(["--set-current", "companion/windows/0.9.79",
                    "--feed-dir", str(feed)]) == pf.EXIT_USAGE
    assert "WILL REFUSE" in capsys.readouterr().err


def test_set_current_is_a_malformed_value_refusal(key, tmp_path):
    feed = _feed(tmp_path, ["0.9.78"], "0.9.78")
    assert pf.main(["--set-current", "companion/windows",
                    "--feed-dir", str(feed)]) == pf.EXIT_USAGE


def test_release_md_no_longer_calls_allow_older_the_rollback():
    text = (REPO / "docs" / "RELEASE.md").read_text(encoding="utf-8")
    assert "(`--allow-older` for a deliberate rollback)" not in text
    assert "--set-current companion/windows/" in text


# --- publish_latest, driven end to end through its subprocess seam ------------


class Harness:
    """Stands in for gh, git and publish_feed: every subprocess publish_latest
    starts goes through pl.run, which this replaces."""

    def __init__(self, tmp_path, monkeypatch, *, channel, version="0.9.79",
                 requires_dashboard="", payload=b"MZ-build-bytes"):
        self.calls: list[list[str]] = []
        self.version = version
        self.payload = payload
        self.requires_dashboard = requires_dashboard
        monkeypatch.setattr(pl, "preflight", lambda: None)
        monkeypatch.setattr(pl, "release_branch_tip", lambda: "a" * 40)
        monkeypatch.setattr(pl, "published_channel", lambda: channel)
        monkeypatch.setattr(pl, "latest_green_run", lambda wf: {
            "databaseId": 7, "headSha": "b" * 40, "createdAt": "2026-09-25T00:00:00Z",
            "displayTitle": "t"})
        monkeypatch.setattr(pl, "commit_is_on_main", lambda sha, tip="": True)
        monkeypatch.setattr(pl, "run", self)

    @property
    def sha(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()

    def __call__(self, cmd, **kw):
        cmd = [str(c) for c in cmd]
        self.calls.append(cmd)
        if cmd[:3] == ["gh", "run", "download"]:
            dest = Path(cmd[cmd.index("--dir") + 1])
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "ccsync-companion.exe").write_bytes(self.payload)
            meta = {"artifact": "ccsync-companion.exe", "sha256": self.sha,
                    "size_bytes": len(self.payload), "version": self.version,
                    "platform": "windows", "tests_run": True, "git_dirty": False}
            if self.requires_dashboard:
                meta["requires_dashboard"] = self.requires_dashboard
            (dest / "ccsync-release.json").write_text(json.dumps(meta), encoding="utf-8")
            return 0, "", ""
        if len(cmd) > 1 and cmd[1].endswith("publish_feed.py"):
            return 0, "[publish-feed] ok\n", "NOTE: from-the-signer\n"
        return 0, "", ""

    def feed_calls(self) -> list[list[str]]:
        return [c for c in self.calls if len(c) > 1 and c[1].endswith("publish_feed.py")]


def _run_latest(monkeypatch, *argv) -> int:
    monkeypatch.setattr(sys, "argv", ["publish_latest.py", "--kind", "companion",
                                      "--platform", "windows", *argv])
    return pl.main()


def _chan(records, current=None):
    c = {"packages": records}
    if current:
        c["current"] = {"companion/windows": current}
    return c


def test_make_current_on_a_staged_same_bytes_version_moves_the_pointer(
        tmp_path, monkeypatch, capsys):
    h = Harness(tmp_path, monkeypatch, channel={})
    staged = _record("companion", "windows", "0.9.79", sha=h.sha)
    monkeypatch.setattr(pl, "published_channel", lambda: _chan(
        [_record("companion", "windows", "0.9.78"), staged], "0.9.78"))
    assert _run_latest(monkeypatch, "--make-current") == 0
    calls = h.feed_calls()
    assert len(calls) == 1, calls
    assert calls[0][calls[0].index("--set-current") + 1] == "companion/windows/0.9.79"
    assert "--artifact" not in calls[0]  # a pointer move re-uploads no bytes
    out = capsys.readouterr().out
    assert "nothing to do" not in out


def test_pointer_move_forwards_allow_key_rotation(tmp_path, monkeypatch, capsys):
    # logic-release-6 review round (2026-09-25): publish_feed --set-current
    # runs the REL-7 key check and asks for --allow-key-rotation; the pointer
    # move must pass on the one publish_latest was given, or the operator
    # loops on the same refusal.
    h = Harness(tmp_path, monkeypatch, channel={})
    staged = _record("companion", "windows", "0.9.79", sha=h.sha)
    monkeypatch.setattr(pl, "published_channel", lambda: _chan(
        [_record("companion", "windows", "0.9.78"), staged], "0.9.78"))
    assert _run_latest(monkeypatch, "--make-current", "--allow-key-rotation") == 0
    calls = h.feed_calls()
    assert len(calls) == 1 and "--set-current" in calls[0]
    assert "--allow-key-rotation" in calls[0]
    args = pf.parse_args(calls[0][calls[0].index("--set-current"):])
    assert args.allow_key_rotation


def test_pointer_move_without_the_flag_does_not_add_it(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, channel={})
    staged = _record("companion", "windows", "0.9.79", sha=h.sha)
    monkeypatch.setattr(pl, "published_channel", lambda: _chan(
        [_record("companion", "windows", "0.9.78"), staged], "0.9.78"))
    assert _run_latest(monkeypatch, "--make-current") == 0
    assert "--allow-key-rotation" not in h.feed_calls()[0]


def test_pointer_move_names_the_flags_it_cannot_apply(tmp_path, monkeypatch, capsys):
    h = Harness(tmp_path, monkeypatch, channel={})
    staged = _record("companion", "windows", "0.9.79", sha=h.sha)
    monkeypatch.setattr(pl, "published_channel", lambda: _chan(
        [_record("companion", "windows", "0.9.78"), staged], "0.9.78"))
    assert _run_latest(monkeypatch, "--make-current", "--min-version", "0.9.70",
                       "--notes", "fixes the thing") == 0
    out = capsys.readouterr().out
    assert "--min-version and --notes NOT applied" in out
    call = h.feed_calls()[0]
    assert "--min-version" not in call and "--notes" not in call


def test_different_bytes_guidance_carries_allow_key_rotation(tmp_path, monkeypatch, capsys):
    h = Harness(tmp_path, monkeypatch, channel={})
    monkeypatch.setattr(pl, "published_channel", lambda: _chan(
        [_record("companion", "windows", "0.9.78"),
         _record("companion", "windows", "0.9.79", sha="f" * 64)], "0.9.78"))
    assert _run_latest(monkeypatch, "--make-current", "--allow-key-rotation") == 0
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if "publish_feed.py --set-current" in ln)
    assert pf.parse_args(shlex.split(line.split("publish_feed.py", 1)[1])).allow_key_rotation


def test_make_current_on_a_version_already_current_is_nothing_to_do(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, channel={})
    monkeypatch.setattr(pl, "published_channel", lambda: _chan(
        [_record("companion", "windows", "0.9.79", sha=h.sha)], "0.9.79"))
    assert _run_latest(monkeypatch, "--make-current") == 0
    assert h.feed_calls() == []


def test_make_current_with_different_bytes_says_how_and_moves_nothing(
        tmp_path, monkeypatch, capsys):
    h = Harness(tmp_path, monkeypatch, channel={})
    monkeypatch.setattr(pl, "published_channel", lambda: _chan(
        [_record("companion", "windows", "0.9.78"),
         _record("companion", "windows", "0.9.79", sha="f" * 64)], "0.9.78"))
    assert _run_latest(monkeypatch, "--make-current") == 0
    assert h.feed_calls() == []
    out = capsys.readouterr().out
    assert "NOT made current" in out
    line = next(ln for ln in out.splitlines() if "publish_feed.py --set-current" in ln)
    args = pf.parse_args(shlex.split(line.split("publish_feed.py", 1)[1]))
    assert args.set_current == "companion/windows/0.9.79"
    assert args.github_upload and args.github_repo == pl.FEED_REPO and args.feed_dir


def test_make_current_never_moves_the_pointer_backwards(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, channel={}, version="0.9.78")
    monkeypatch.setattr(pl, "published_channel", lambda: _chan(
        [_record("companion", "windows", "0.9.78", sha=h.sha),
         _record("companion", "windows", "0.9.79")], "0.9.79"))
    assert _run_latest(monkeypatch, "--make-current", "--allow-older") == 0
    assert h.feed_calls() == []


def _recall_line(out: str) -> list[str]:
    line = next(ln for ln in out.splitlines() if "Recall it:" in ln)
    return shlex.split(line.split("publish_feed.py", 1)[1])


def test_the_printed_recall_line_parses_and_rolls_back(tmp_path, monkeypatch, capsys, key):
    h = Harness(tmp_path, monkeypatch, channel=_chan(
        [_record("companion", "windows", "0.9.78")], "0.9.78"))
    assert _run_latest(monkeypatch, "--make-current") == 0
    assert len(h.feed_calls()) == 1 and "--artifact" in h.feed_calls()[0]
    argv = _recall_line(capsys.readouterr().out)
    args = pf.parse_args(argv)
    assert args.retract == "companion/windows/0.9.79"
    assert args.set_current == "companion/windows/0.9.78"
    assert args.reason.strip()
    assert args.feed_dir and args.github_repo == pl.FEED_REPO and args.github_upload

    # And it RUNS: against a local feed holding the state this publish left
    # (0.9.79 current), minus the upload.
    feed = _feed(tmp_path, ["0.9.78", "0.9.79"], "0.9.79")
    local = [a for a in argv if a != "--github-upload"]
    local[local.index("--feed-dir") + 1] = str(feed)
    assert pf.main(local) == pf.EXIT_OK
    assert _channel(feed)["current"] == {"companion/windows": "0.9.78"}


def test_a_staged_publish_recall_line_needs_no_successor(tmp_path, monkeypatch, capsys):
    Harness(tmp_path, monkeypatch, channel=_chan(
        [_record("companion", "windows", "0.9.78")], "0.9.78"))
    assert _run_latest(monkeypatch) == 0
    args = pf.parse_args(_recall_line(capsys.readouterr().out))
    assert args.retract == "companion/windows/0.9.79"
    assert not args.set_current and not args.allow_no_current


# --- logic-release-5: the ordering gate judges only a field that is signed ------


def test_an_unsigned_requires_dashboard_is_a_note_not_a_refusal(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CCSYNC_EMIT_KIND_EXTRAS", raising=False)
    h = Harness(tmp_path, monkeypatch, requires_dashboard="0.9.0", channel=_chan(
        [_record("dashboard", "linux", "0.7.44")]))
    assert _run_latest(monkeypatch) == 0
    out, err = capsys.readouterr()
    assert "NOT signed into the record" in out
    assert len(h.feed_calls()) == 1
    # publish_feed's stderr (sign_release's own NOTE) is shown on success too.
    assert "from-the-signer" in err


def test_a_signed_requires_dashboard_still_refuses(tmp_path, monkeypatch):
    monkeypatch.setenv("CCSYNC_EMIT_KIND_EXTRAS", "1")
    h = Harness(tmp_path, monkeypatch, requires_dashboard="0.9.0", channel=_chan(
        [_record("dashboard", "linux", "0.7.44")]))
    with pytest.raises(SystemExit):
        _run_latest(monkeypatch)
    assert h.feed_calls() == []


# --- bug-ops-2: ship.cmd -Resume past the publish ------------------------------

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


def _ship_probe_block() -> str:
    src = (TOOLS / "ship.ps1").read_text(encoding="utf-8-sig")
    start = src.index("# --- where did the last ship get to? (REL-15)")
    end = src.index("# --- will step 2b's Authenticode gate refuse?")
    steps = next(ln for ln in src.splitlines() if ln.startswith("$ShipSteps = "))
    fn_start = src.index("function Test-StepDone {")
    fn_end = src.index("\n}\n", fn_start) + 3
    # The block ends inside `if (-not $DashboardOnly) {`, so close it.
    return steps + "\n" + src[fn_start:fn_end] + "\n" + src[start:end] + "\n}\n"


def _repo_installer_version() -> str:
    src = (REPO / "installer" / "windows_bootstrap.ps1").read_text(encoding="utf-8-sig")
    return re.search(r'^\$InstallerVersion\s*=\s*"([^"]+)"', src, re.M).group(1)


def _run_probe_block(tmp_path, journal_step, journal_iv):
    prelude = f"""
$ErrorActionPreference = 'Stop'
function Write-Step {{ param([string]$m) Write-Host "[ship] $m" }}
function Write-Fail {{ param([string]$m) Write-Host "[ship] FAILED: $m" }}
function Get-ShipState {{
    return [pscustomobject]@{{ step = '{journal_step}'; version = '0.9.78';
                              installer_version = '{journal_iv}';
                              timestamp = 'x'; made_current = @() }}
}}
function Invoke-CurlWithToken {{ param($Uri, $Token, $ExtraArgs) Write-Host "PROBED $Uri"; return "200" }}
$Resume = $true
$DashboardOnly = $false
$CompanionVersion = '0.9.78'
$DashboardUrl = 'http://dash.invalid'
$ShipStatePath = 'journal.json'
$script:ShipMadeCurrent = @()
"""
    script = tmp_path / "probe.ps1"
    script.write_text(prelude + _ship_probe_block()
                      + '\nWrite-Host "REACHED-END past=$($script:ResumedPastPublish)"\nexit 0\n',
                      encoding="utf-8-sig")
    p = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(script)], cwd=str(REPO), capture_output=True, text=True,
                       timeout=120)
    return p.returncode, p.stdout + p.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="needs powershell")
@pytest.mark.parametrize("journal_step,expect_reached", [
    ("publish", True),   # soak refusal (exit 3): -Resume must get past step 0
    ("current", True),   # local upgrade failed: likewise
    ("build", False),    # nothing published by this ship: a collision is real
])
def test_resume_after_the_publish_is_not_a_version_collision(
        tmp_path, journal_step, expect_reached):
    rc, out = _run_probe_block(tmp_path, journal_step, _repo_installer_version())
    if expect_reached:
        assert rc == 0, out
        assert "REACHED-END past=True" in out and "PROBED" not in out, out
        assert "bump VERSION" not in out
    else:
        assert rc == 1, out
        assert "ALREADY published" in out


@pytest.mark.skipif(POWERSHELL is None, reason="needs powershell")
@pytest.mark.parametrize("journal_step", ["publish", "current"])
def test_resume_after_an_installer_bump_probes_again(tmp_path, journal_step):
    # bug-ops-2 review round (2026-09-25): installer 409 -> bump
    # $InstallerVersion -> -Resume is the path build_editor_package.ps1 itself
    # prescribes. The journal's installer version is no longer the tree's, so
    # nothing may be skipped on the strength of it.
    rc, out = _run_probe_block(tmp_path, journal_step, "0.0.1-not-this-one")
    assert "PROBED" in out, out
    assert "REACHED-END past=True" not in out, out
    assert "probing as a new ship" in out


def _ship_function(name: str) -> str:
    src = (TOOLS / "ship.ps1").read_text(encoding="utf-8-sig")
    start = src.index(f"function {name} {{")
    return src[start:src.index("\n}\n", start) + 3]


@pytest.mark.skipif(POWERSHELL is None, reason="needs powershell")
@pytest.mark.parametrize("newer_input,expect", [
    (None, True),                       # built after every input: reuse
    ("companion", False),               # companion rebuilt since
    ("steps.py", False),                # INSTALLER_VERSION bumped in steps.py
    ("bootstrap", False),               # $InstallerVersion bumped in the bootstrap
])
def test_onboard_reuse_needs_an_exe_newer_than_every_input(tmp_path, newer_input, expect):
    ob_dir = tmp_path / "onboarding"
    (ob_dir / "dist").mkdir(parents=True)
    files = {"companion": tmp_path / "ccsync-companion.exe",
             "steps.py": ob_dir / "steps.py",
             "bootstrap": tmp_path / "windows_bootstrap.ps1"}
    onboard = ob_dir / "dist" / "onboard.exe"
    for f in [*files.values(), onboard]:
        f.write_bytes(b"x")
    base = time.time() - 1000
    for f in files.values():
        os.utime(f, (base, base))
    os.utime(onboard, (base + 100, base + 100))
    if newer_input:
        os.utime(files[newer_input], (base + 200, base + 200))
    script = tmp_path / "reuse.ps1"
    script.write_text(_ship_function("Test-OnboardReusable") + f"""
$r = Test-OnboardReusable -OnboardExe '{onboard}' -CompanionExe '{files["companion"]}' `
    -OnboardingDir '{ob_dir}' -BootstrapPs1 '{files["bootstrap"]}'
Write-Host "REUSE=$r"
""", encoding="utf-8-sig")
    p = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(script)], capture_output=True, text=True, timeout=120)
    assert f"REUSE={expect}" in p.stdout, p.stdout + p.stderr


def test_a_failed_step_2b_does_not_advance_the_journal_to_publish():
    # bug-ops-2 review round: the journal was written before $pkgRc was read.
    src = (TOOLS / "ship.ps1").read_text(encoding="utf-8-sig")
    block = src[src.index("$pkgRc = $LASTEXITCODE"):src.index("if ($pkgRc -ne 0) {")]
    guard = block.index("if ($pkgRc -eq 0 -or $pkgRc -eq 3) {")
    assert block.index('Save-ShipStep -Step "publish"') > guard


def test_a_resumed_publish_reuses_the_onboard_exe_it_published():
    src = (TOOLS / "ship.ps1").read_text(encoding="utf-8-sig")
    block = src[src.index("$rebuildOnboard = $true"):src.index("if ($AllowUnsignedBinary) { $pkgArgs")]
    assert "if ($rebuildOnboard) { $pkgArgs += \"-RebuildOnboard\" }" in block
    # The timing rule itself is executed by
    # test_onboard_reuse_needs_an_exe_newer_than_every_input; this pins that
    # the reuse is gated on it AND on a resume past the publish.
    assert "$script:ResumedPastPublish -and" in block
    assert "Test-OnboardReusable" in block
    for arg in ("-CompanionExe $builtExe", "-OnboardingDir", "-BootstrapPs1"):
        assert arg in block


# --- owed round: bug-ops-4 / ui-onboarding-11 (2026-09-25) --------------------
# Both gates named ONE bash table test, so the two the onboarding builders
# added (test_macos_uninstall_profile.sh, test_macos_first_steps.sh) gated
# nothing. Both now enumerate installer/tests/test_*.sh. These tests EXECUTE
# the enumerating code against a scratch tree: a failing file anywhere in the
# list must fail the row, every file must run, and an empty directory must
# not read as green.

def _find_bash():
    for cand in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        shutil.which("bash"),
    ):
        if cand and Path(cand).is_file():
            return cand
    return None


BASH = _find_bash()


def _sh_tree(tmp_path, scripts):
    tests = tmp_path / "installer" / "tests"
    tests.mkdir(parents=True)
    for name, body in scripts.items():
        (tests / name).write_bytes(body.encode())
    return tests


def _three_tests(tmp_path):
    # a fails-last-alphabetically case: HEAD ran only test_macos_site_values.sh
    return _sh_tree(tmp_path, {
        "test_macos_site_values.sh": "echo ran-site >> ran.log\nexit 0\n",
        "test_macos_uninstall_profile.sh": "echo ran-uninstall >> ran.log\nexit 3\n",
        "test_macos_first_steps.sh": "echo ran-first >> ran.log\nexit 0\n",
        "not_a_test.sh": "echo ran-other >> ran.log\nexit 9\n",
    })


def _ci_step_script():
    text = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    m = re.search(
        r"- name: installer -- macOS bootstrap[^\n]*\n(?:[^\n]*\n)*?\s+run: \|\n((?:          [^\n]*\n|\s*\n)+)",
        text,
    )
    assert m, "the installer bash-tests step is gone from ci.yml"
    return "\n".join(line[10:] for line in m.group(1).splitlines()) + "\n"


def test_ci_step_names_no_single_bash_test():
    text = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "run: bash installer/tests/test_macos_site_values.sh" not in text
    assert "installer/tests/test_*.sh" in _ci_step_script()


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_ci_step_runs_every_bash_test_and_fails_on_any(tmp_path):
    _three_tests(tmp_path)
    script = tmp_path / "step.sh"
    script.write_bytes(_ci_step_script().encode())
    # GitHub's `shell: bash` is `bash --noprofile --norc -eo pipefail {0}`
    r = subprocess.run([BASH, "--noprofile", "--norc", "-eo", "pipefail", "step.sh"],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode != 0
    ran = (tmp_path / "ran.log").read_text().split()
    assert sorted(ran) == ["ran-first", "ran-site", "ran-uninstall"]


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_ci_step_with_no_bash_tests_is_a_failure(tmp_path):
    _sh_tree(tmp_path, {})
    script = tmp_path / "step.sh"
    script.write_bytes(_ci_step_script().encode())
    r = subprocess.run([BASH, "--noprofile", "--norc", "-eo", "pipefail", "step.sh"],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode != 0
    assert "no installer/tests/test_*.sh found" in r.stdout


def _macos_row():
    text = (TOOLS / "run_all_tests.ps1").read_text(encoding="utf-8")
    start = text.index('Write-Host "`n=== installer/macos')
    end = text.index('Write-Host ""', start)
    return text[start:end]


def _run_macos_row(tmp_path):
    ps = tmp_path / "row.ps1"
    ps.write_text(
        "$ErrorActionPreference = 'Continue'\n"
        f"$repo = '{tmp_path}'\n"
        f"$bashExe = '{BASH}'\n"
        "$results = @()\n"
        + _macos_row()
        + "\nforeach ($r in $results) { Write-Output (\"ROW \" + $r.Name + \" \" + $r.Outcome) }\n",
        encoding="utf-8",
    )
    r = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)],
                       capture_output=True, text=True)
    rows = [ln for ln in r.stdout.splitlines() if ln.startswith("ROW ")]
    assert len(rows) == 1, r.stdout + r.stderr
    return rows[0]


def test_run_all_tests_names_no_single_bash_test():
    row = _macos_row()
    assert "bash installer/tests/test_macos_site_values.sh" not in row
    assert '-Filter "test_*.sh"' in row


@pytest.mark.skipif(POWERSHELL is None or BASH is None, reason="needs powershell and bash")
def test_run_all_tests_macos_row_runs_every_bash_test_and_fails_on_any(tmp_path):
    _three_tests(tmp_path)
    row = _run_macos_row(tmp_path)
    assert row == "ROW installer/macos FAIL (exit 3)"
    ran = (tmp_path / "ran.log").read_text().split()
    assert sorted(ran) == ["ran-first", "ran-site", "ran-uninstall"]


@pytest.mark.skipif(POWERSHELL is None or BASH is None, reason="needs powershell and bash")
def test_run_all_tests_macos_row_passes_when_all_pass(tmp_path):
    _sh_tree(tmp_path, {
        "test_a.sh": "exit 0\n",
        "test_b.sh": "exit 0\n",
    })
    assert _run_macos_row(tmp_path) == "ROW installer/macos PASS"


@pytest.mark.skipif(POWERSHELL is None or BASH is None, reason="needs powershell and bash")
def test_run_all_tests_macos_row_with_no_bash_tests_is_a_failure(tmp_path):
    _sh_tree(tmp_path, {})
    assert _run_macos_row(tmp_path).startswith("ROW installer/macos FAIL")
