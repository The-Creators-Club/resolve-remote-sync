"""CR-371 (2026-10-07): GL-24 (one gated customer release), GL-25 (no
ungated image / bundle / publish), GL-25b (downgrade floor), GL-50 (customers
pinned by digest).

Nothing here touches the network, `gh` or a real key: every subprocess goes
through publish_latest.run, which the tests replace, and the signing tests use
a throwaway key like test_publish_feed.py does.
"""
from __future__ import annotations

import io
import json
import re
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "companion" / "src"))

import check_feed_freshness as cff  # noqa: E402
import pin_compose_images as pin  # noqa: E402
import publish_feed as pf  # noqa: E402
import publish_latest as pl  # noqa: E402
import release_customers as rc  # noqa: E402
import release_key as release_key_mod  # noqa: E402
import sign_release  # noqa: E402

SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64
SFTP_DIGEST = "sha256:" + "c" * 64


# ----------------------------------------------------------------- GL-25b: floor


class TestTrackedFloor:
    def test_the_real_file_names_every_platform_with_a_rankable_floor(self):
        data = json.loads((TOOLS / "release_floor.json").read_text(encoding="utf-8"))
        for kind in sign_release.FLOOR_KINDS:
            for platform in ("windows", "macos"):
                value = data[kind][platform]
                assert sign_release.version_tuple(value) > (0, 0, 0), (kind, platform)

    def test_the_real_companion_floor_is_not_above_the_companion_build(self):
        """A floor above the build being shipped refuses the build, every earlier
        one and the corrected republish (CR-52)."""
        text = (REPO / "companion" / "src" / "ccsync_companion" / "config.py").read_text(
            encoding="utf-8")
        version = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.M).group(1)
        data = json.loads((TOOLS / "release_floor.json").read_text(encoding="utf-8"))
        for platform in ("windows", "macos"):
            assert not sign_release.min_version_exceeds_version(
                version, data["companion"][platform])

    def test_unset_resolves_to_the_tracked_floor(self, tmp_path, monkeypatch):
        f = tmp_path / "floor.json"
        f.write_text(json.dumps({"companion": {"windows": "0.9.75"}}), encoding="utf-8")
        monkeypatch.setenv("CCSYNC_RELEASE_FLOOR_FILE", str(f))
        assert sign_release.resolve_min_version("companion", "windows", None) == "0.9.75"
        assert sign_release.resolve_min_version("companion", "windows", "0.9.80") == "0.9.80"

    def test_a_floorless_companion_record_is_refused_unless_asked_for(self, tmp_path, monkeypatch):
        f = tmp_path / "floor.json"
        f.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("CCSYNC_RELEASE_FLOOR_FILE", str(f))
        with pytest.raises(SystemExit) as exc:
            sign_release.resolve_min_version("companion", "macos", None)
        assert "NO downgrade floor" in str(exc.value)
        with pytest.raises(SystemExit):
            sign_release.resolve_min_version("onboard", "windows", "0.0.0")
        assert sign_release.resolve_min_version(
            "companion", "macos", "0.0.0", allow_no_floor=True) == "0.0.0"
        # a dashboard bundle has no floor to speak of
        assert sign_release.resolve_min_version("dashboard", "linux", None) == "0.0.0"

    def test_every_signing_script_stops_defaulting_to_zero(self):
        for rel in ("tools/release_macos.sh", "tools/build_onboard_macos.sh"):
            text = (REPO / rel).read_text(encoding="utf-8")
            assert "CCSYNC_MIN_VERSION:-0.0.0" not in text, rel
        ps = (REPO / "installer" / "build_editor_package.ps1").read_text(encoding="utf-8")
        assert '$minVersion = "0.0.0"' not in ps
        assert 'default="0.0.0"' not in (TOOLS / "publish_feed.py").read_text(encoding="utf-8").split(
            '"--min-version"')[1][:60]


@pytest.fixture
def key(tmp_path, monkeypatch):
    path = tmp_path / "release.key"
    monkeypatch.setenv("CCSYNC_RELEASE_KEY", str(path))
    assert release_key_mod.main(["new"]) == 0
    return path


@pytest.fixture
def artifact(tmp_path):
    p = tmp_path / "ccsync-companion.exe"
    p.write_bytes(b"MZ" + b"x" * 5000)
    return p


def _pf(feed, art, version, *extra):
    return pf.main(["--artifact", str(art), "--platform", "windows", "--version", version,
                    "--feed-dir", str(feed), "--base-url", "https://releases.example.test/v1",
                    *extra])


class TestFloorAgainstTheCurrentBuild:
    def test_a_floor_above_the_current_build_is_refused(self, key, artifact, tmp_path, capsys):
        feed = tmp_path / "feed"
        assert _pf(feed, artifact, "0.9.50", "--min-version", "0.9.40", "--make-current") == pf.EXIT_OK
        other = tmp_path / "next.exe"
        other.write_bytes(b"MZ" + b"y" * 5000)
        rc_ = _pf(feed, other, "0.9.51", "--min-version", "0.9.51")
        assert rc_ == pf.EXIT_USAGE
        err = capsys.readouterr().err
        assert "ABOVE 0.9.50" in err and "rollback" in err
        channel = json.loads((feed / pf.CHANNEL_FILENAME).read_text())
        assert [p["version"] for p in channel["packages"]] == ["0.9.50"]   # nothing published

    def test_a_floor_at_the_current_build_is_allowed(self, key, artifact, tmp_path):
        feed = tmp_path / "feed"
        assert _pf(feed, artifact, "0.9.50", "--min-version", "0.9.40", "--make-current") == pf.EXIT_OK
        other = tmp_path / "next.exe"
        other.write_bytes(b"MZ" + b"y" * 5000)
        assert _pf(feed, other, "0.9.51", "--min-version", "0.9.50") == pf.EXIT_OK

    def test_the_override_exists_for_when_the_current_build_is_the_hole(self, key, artifact, tmp_path):
        feed = tmp_path / "feed"
        assert _pf(feed, artifact, "0.9.50", "--min-version", "0.9.40", "--make-current") == pf.EXIT_OK
        other = tmp_path / "next.exe"
        other.write_bytes(b"MZ" + b"y" * 5000)
        assert _pf(feed, other, "0.9.51", "--min-version", "0.9.51",
                   "--allow-floor-above-current") == pf.EXIT_OK

    def test_publishing_with_no_floor_anywhere_is_refused(self, key, artifact, tmp_path,
                                                          monkeypatch, capsys):
        empty = tmp_path / "floor.json"
        empty.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("CCSYNC_RELEASE_FLOOR_FILE", str(empty))
        assert _pf(tmp_path / "feed", artifact, "0.9.50") == pf.EXIT_USAGE
        assert "NO downgrade floor" in capsys.readouterr().err

    def test_the_tracked_floor_is_what_gets_signed(self, key, artifact, tmp_path):
        feed = tmp_path / "feed"
        assert _pf(feed, artifact, "0.9.50") == pf.EXIT_OK   # conftest floor, 0.0.1
        channel = json.loads((feed / pf.CHANNEL_FILENAME).read_text())
        assert channel["packages"][0]["min_version"] == "0.0.1"


# ----------------------------------------------------- GL-25: publish_latest's CI gate


class Fake:
    """gh / git / publish_feed, answered by argv. `ci` is whether ci.yml is green."""

    def __init__(self, monkeypatch, *, ci=True, ci_rc=0):
        self.calls: list[list[str]] = []
        self.ci, self.ci_rc = ci, ci_rc
        monkeypatch.setattr(pl, "run", self)

    def __call__(self, cmd, **kw):
        cmd = [str(c) for c in cmd]
        self.calls.append(cmd)
        if cmd[:3] == ["gh", "run", "list"] and "ci.yml" in cmd:
            if self.ci_rc:
                return self.ci_rc, "", "boom"
            return 0, json.dumps([{"databaseId": 1, "headSha": SHA}] if self.ci else []), ""
        return 0, "", ""


class TestCiGate:
    def test_green_ci_for_exactly_that_commit(self, monkeypatch):
        f = Fake(monkeypatch)
        assert pl.ci_green_for(SHA) is True
        argv = f.calls[0]
        assert argv[argv.index("--commit") + 1] == SHA
        assert argv[argv.index("--workflow") + 1] == "ci.yml"

    def test_no_run_a_failed_ask_and_a_blank_sha_all_count_as_not_green(self, monkeypatch):
        Fake(monkeypatch, ci=False)
        assert pl.ci_green_for(SHA) is False
        Fake(monkeypatch, ci_rc=1)
        assert pl.ci_green_for(SHA) is False
        assert pl.ci_green_for("") is False

    def test_a_run_for_a_different_sha_does_not_count(self, monkeypatch):
        monkeypatch.setattr(pl, "run", lambda cmd, **kw: (
            0, json.dumps([{"databaseId": 1, "headSha": "f" * 40}]), ""))
        assert pl.ci_green_for(SHA) is False

    def test_latest_green_run_can_be_pinned_to_a_commit(self, monkeypatch):
        f = Fake(monkeypatch)
        pl.latest_green_run("release-windows.yml", SHA)
        argv = f.calls[0]
        assert argv[argv.index("--commit") + 1] == SHA

    def _drive(self, monkeypatch, tmp_path, *argv, ci=True):
        payload = b"MZ-bytes"
        import hashlib
        sha = hashlib.sha256(payload).hexdigest()
        calls = []

        def fake_run(cmd, **kw):
            cmd = [str(c) for c in cmd]
            calls.append(cmd)
            if cmd[:3] == ["gh", "run", "download"]:
                dest = Path(cmd[cmd.index("--dir") + 1])
                dest.mkdir(parents=True, exist_ok=True)
                (dest / "x.exe").write_bytes(payload)
                (dest / "ccsync-release.json").write_text(json.dumps({
                    "artifact": "x.exe", "sha256": sha, "size_bytes": len(payload),
                    "version": "0.9.90", "platform": "windows", "tests_run": True,
                    "git_dirty": False}), encoding="utf-8")
                return 0, "", ""
            if cmd[:3] == ["gh", "run", "list"] and "ci.yml" in cmd:
                return 0, json.dumps([{"databaseId": 1, "headSha": SHA}] if ci else []), ""
            if len(cmd) > 1 and cmd[1].endswith("publish_feed.py"):
                return 0, "", ""
            return 0, "", ""

        monkeypatch.setattr(pl, "preflight", lambda: None)
        monkeypatch.setattr(pl, "release_branch_tip", lambda: "d" * 40)
        monkeypatch.setattr(pl, "published_channel", lambda: {})
        monkeypatch.setattr(pl, "latest_green_run", lambda wf, sha="": {
            "databaseId": 7, "headSha": SHA, "createdAt": "now", "displayTitle": "t"})
        monkeypatch.setattr(pl, "commit_is_on_main", lambda sha, tip="": True)
        monkeypatch.setattr(pl, "run", fake_run)
        monkeypatch.setattr(sys, "argv", ["publish_latest.py", "--kind", "companion",
                                          "--platform", "windows", *argv])
        return pl.main(), calls

    def test_a_red_ci_commit_is_not_signed(self, monkeypatch, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            self._drive(monkeypatch, tmp_path, ci=False)
        assert exc.value.code == 1
        assert "no successful ci.yml run" in capsys.readouterr().out

    def test_the_override_publishes_and_says_so(self, monkeypatch, tmp_path, capsys):
        rc_, calls = self._drive(monkeypatch, tmp_path, "--allow-red-ci", ci=False)
        assert rc_ == 0
        assert any(len(c) > 1 and c[1].endswith("publish_feed.py") for c in calls)
        assert "--allow-red-ci" in capsys.readouterr().out

    def test_a_green_commit_publishes_without_the_override(self, monkeypatch, tmp_path):
        rc_, calls = self._drive(monkeypatch, tmp_path)
        assert rc_ == 0

    def test_floor_flags_reach_publish_feed(self, monkeypatch, tmp_path):
        _rc, calls = self._drive(monkeypatch, tmp_path, "--allow-no-floor",
                                 "--allow-floor-above-current")
        feed = next(c for c in calls if len(c) > 1 and c[1].endswith("publish_feed.py"))
        assert "--allow-no-floor" in feed and "--allow-floor-above-current" in feed


# ------------------------------------------------------------- GL-24: release command


def _bundle(tmp_path, *, commit=SHA, version="0.7.74", dirty=False) -> Path:
    path = tmp_path / f"ccsync-dashboard-{version}.tar.gz"
    manifest = json.dumps({"kind": "dashboard", "version": version, "git_commit": commit,
                           "git_dirty": dirty, "runtime_id": "r"}).encode()
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest)
        tar.addfile(info, io.BytesIO(manifest))
    return path


class ReleaseFake:
    """The gh/git/publish world for release_customers, answered by argv, with
    an ordered log so a test can assert WHAT HAPPENED BEFORE WHAT."""

    def __init__(self, monkeypatch, tmp_path, *, ci=True, runs=("release-dashboard.yml",
                 "release-windows.yml", "release-macos.yml"), tag_out="", bundle=None,
                 image_conclusion="success", reviewers=True, soak=""):
        self.log: list[list[str]] = []
        self.reviewers = reviewers
        monkeypatch.setattr(rc, "soak_check", lambda *a, **k: soak)
        self.ci, self.runs, self.tag_out = ci, set(runs), tag_out
        self.bundle = bundle or _bundle(tmp_path)
        self.image_conclusion = image_conclusion
        monkeypatch.setattr(pl, "preflight", lambda: None)
        monkeypatch.setattr(pl, "release_branch_tip", lambda: SHA)
        monkeypatch.setattr(pl, "published_channel", lambda: {})
        monkeypatch.setattr(pl, "commit_is_on_main", lambda sha, tip="": True)
        monkeypatch.setattr(pl, "run", self)
        monkeypatch.setattr(rc, "FEED_DIR", tmp_path / "feed")
        compose = tmp_path / "compose.yaml"
        compose.write_text(
            'services:\n  a:\n    image: "${CCSYNC_IMAGE:-ghcr.io/x/ccsync}:1"\n'
            '  b:\n    image: "${CCSYNC_SFTP_IMAGE:-ghcr.io/x/ccsync-sftp}:1"\n', encoding="utf-8")
        monkeypatch.setattr(pin, "COMPOSE", compose)
        self.compose = compose

    def mutations(self):
        return [c for c in self.log
                if (c[:2] == ["git", "-C"] and c[3] in ("tag", "push"))
                or (len(c) > 1 and (c[1].endswith("publish_feed.py")
                                    or (c[1].endswith("publish_latest.py") and "--dry-run" not in c)))]

    def __call__(self, cmd, **kw):
        cmd = [str(c) for c in cmd]
        self.log.append(cmd)
        if cmd[:2] == ["gh", "api"]:
            if self.reviewers is None:
                return 1, "", "HTTP 404"
            rules = ([{"type": "required_reviewers", "reviewers": [{"id": 1}]}]
                     if self.reviewers else [{"type": "wait_timer"}])
            return 0, json.dumps({"protection_rules": rules}), ""
        if cmd[0] == "git" and "show" in cmd:
            return 0, 'VERSION = "0.7.74"\n', ""
        if cmd[0] == "git" and "ls-remote" in cmd:
            return 0, self.tag_out, ""
        if cmd[:3] == ["gh", "run", "list"]:
            if "ci.yml" in cmd:
                return 0, json.dumps([{"databaseId": 1, "headSha": SHA}] if self.ci else []), ""
            wf = cmd[cmd.index("--workflow") + 1]
            if wf == rc.IMAGE_WORKFLOW:
                return 0, json.dumps([{"databaseId": 9, "status": "completed",
                                       "conclusion": self.image_conclusion}]), ""
            if wf in self.runs:
                return 0, json.dumps([{"databaseId": 5, "headSha": SHA, "displayTitle": "t",
                                       "createdAt": "now"}]), ""
            return 0, "[]", ""
        if cmd[:3] == ["gh", "run", "download"]:
            dest = Path(cmd[cmd.index("--dir") + 1])
            dest.mkdir(parents=True, exist_ok=True)
            if "-n" in cmd and cmd[cmd.index("-n") + 1] == rc.DASHBOARD_ARTIFACT:
                (dest / self.bundle.name).write_bytes(self.bundle.read_bytes())
            else:
                (dest / "digests.json").write_text(json.dumps({
                    "version": "0.7.74", "image": "ghcr.io/x/ccsync", "digest": DIGEST,
                    "sftp_image": "ghcr.io/x/ccsync-sftp", "sftp_digest": SFTP_DIGEST}),
                    encoding="utf-8")
            return 0, "", ""
        return 0, "", ""


def _main(*argv):
    return rc.main(list(argv))


class TestReleaseCustomers:
    def test_the_whole_order_and_one_channel_write_for_current_and_image(
            self, monkeypatch, tmp_path):
        f = ReleaseFake(monkeypatch, tmp_path)
        assert _main("--poll", "0") == 0
        kinds = []
        for c in f.log:
            if c[0] == "git" and "tag" in c[:5]:
                kinds.append("tag")
            elif c[0] == "git" and "push" in c:
                kinds.append("push")
            elif len(c) > 1 and c[1].endswith("publish_feed.py"):
                kinds.append("dashboard-publish")
            elif len(c) > 1 and c[1].endswith("publish_latest.py"):
                kinds.append("clients")
        assert kinds == ["tag", "push", "dashboard-publish", "clients"]
        feed = next(c for c in f.log if len(c) > 1 and c[1].endswith("publish_feed.py"))
        # ONE invocation carries the bundle, the pointer move and the image pin.
        assert "--make-current" in feed and "--artifact" in feed
        assert feed[feed.index("--set-image") + 1] == f"0.7.74@{DIGEST}"
        assert feed[feed.index("--kind") + 1] == "dashboard"
        clients = next(c for c in f.log if len(c) > 1 and c[1].endswith("publish_latest.py"))
        assert clients[clients.index("--sha") + 1] == SHA and "--make-current" in clients
        text = f.compose.read_text(encoding="utf-8")
        assert f":0.7.74@{DIGEST}" in text and f":0.7.74@{SFTP_DIGEST}" in text

    def test_dry_run_changes_nothing(self, monkeypatch, tmp_path, capsys):
        f = ReleaseFake(monkeypatch, tmp_path)
        before = f.compose.read_text(encoding="utf-8")
        assert _main("--dry-run") == 0
        assert f.mutations() == []
        assert f.compose.read_text(encoding="utf-8") == before
        assert "DRY RUN" in capsys.readouterr().out

    def test_red_ci_is_refused_before_anything_moves(self, monkeypatch, tmp_path, capsys):
        f = ReleaseFake(monkeypatch, tmp_path, ci=False)
        assert _main() == 1
        assert f.mutations() == []
        assert "no successful ci.yml run" in capsys.readouterr().err

    def test_a_missing_release_run_for_that_commit_is_refused(self, monkeypatch, tmp_path, capsys):
        f = ReleaseFake(monkeypatch, tmp_path, runs=("release-dashboard.yml", "release-windows.yml"))
        assert _main() == 1
        assert f.mutations() == []
        assert "release-macos.yml has no successful run" in capsys.readouterr().err

    def test_a_tag_on_another_commit_is_never_moved(self, monkeypatch, tmp_path, capsys):
        f = ReleaseFake(monkeypatch, tmp_path, tag_out=f"{'e' * 40}\trefs/tags/v0.7.74\n")
        assert _main() == 1
        assert f.mutations() == []
        assert "DIFFERENT commit" in capsys.readouterr().err

    def test_an_existing_tag_on_this_commit_is_reused_not_repushed(self, monkeypatch, tmp_path):
        f = ReleaseFake(monkeypatch, tmp_path, tag_out=f"{SHA}\trefs/tags/v0.7.74\n")
        assert _main("--poll", "0") == 0
        assert not any(c[0] == "git" and ("tag" in c[:5] or "push" in c) for c in f.log)

    @pytest.mark.parametrize("kw,needle", [
        (dict(commit="9" * 40), "was built from 9999999"),
        (dict(dirty=True), "DIRTY"),
        (dict(version="0.7.70"), "is version 0.7.70"),
    ])
    def test_a_bundle_that_is_not_this_commit_clean_and_this_version_is_refused(
            self, monkeypatch, tmp_path, capsys, kw, needle):
        f = ReleaseFake(monkeypatch, tmp_path, bundle=_bundle(tmp_path, **kw))
        assert _main() == 1
        assert f.mutations() == []
        assert needle in capsys.readouterr().err

    def test_a_failed_image_run_publishes_nothing(self, monkeypatch, tmp_path, capsys):
        f = ReleaseFake(monkeypatch, tmp_path, image_conclusion="failure")
        assert _main("--poll", "0") == 1
        assert not any(len(c) > 1 and c[1].endswith(("publish_feed.py", "publish_latest.py"))
                       for c in f.log)
        assert "ended failure" in capsys.readouterr().err

    def test_an_image_run_still_waiting_for_approval_times_out_with_the_reason(
            self, monkeypatch):
        monkeypatch.setattr(pl, "run", lambda cmd, **kw: (
            0, json.dumps([{"databaseId": 9, "status": "waiting", "conclusion": ""}]), ""))
        with pytest.raises(rc.ReleaseError) as exc:
            rc.wait_for_image("v0.7.74", SHA, timeout=0, poll=0, sleep=lambda s: None)
        assert "customer-release" in str(exc.value)

    def test_an_older_dashboard_than_the_channel_is_a_rollback_not_a_release(
            self, monkeypatch, tmp_path, capsys):
        f = ReleaseFake(monkeypatch, tmp_path)
        monkeypatch.setattr(pl, "published_channel", lambda: {"packages": [
            {"kind": "dashboard", "platform": "linux", "version": "0.7.80"}]})
        assert _main() == 1
        assert f.mutations() == []
        assert "rollback" in capsys.readouterr().err


class TestOverseerRound2:
    """CR-371 overseer round 2 (2026-10-07): environment gate, studio soak,
    publish_feed's own CI gate, generated_at monotonic, image update hint."""

    def test_an_environment_without_required_reviewers_is_refused_before_the_tag(
            self, monkeypatch, tmp_path, capsys):
        f = ReleaseFake(monkeypatch, tmp_path, reviewers=False)
        assert _main("--poll", "0") == 1
        assert f.mutations() == []
        assert "no required reviewers" in capsys.readouterr().err

    def test_a_missing_environment_is_refused(self, monkeypatch, tmp_path, capsys):
        f = ReleaseFake(monkeypatch, tmp_path, reviewers=None)
        assert _main("--poll", "0") == 1
        assert f.mutations() == []
        assert "customer-release" in capsys.readouterr().err

    def test_the_soak_refuses_and_allow_no_soak_overrides(self, monkeypatch, tmp_path, capsys):
        f = ReleaseFake(monkeypatch, tmp_path, soak="the studio has run it for 1.0 h")
        assert _main("--poll", "0") == 1
        assert f.mutations() == []
        assert "studio has run" in capsys.readouterr().err
        assert _main("--poll", "0", "--allow-no-soak") == 0

    def test_soak_logic_commit_version_and_clock(self):
        health = {"version": "0.7.74", "code": {"commit": SHA}}
        why, upd = rc.soak_refusal(health, SHA, "0.7.74", hours=24, now=1000.0, ledger={})
        assert "starts now" in why and upd == {f"0.7.74@{SHA[:12]}": 1000.0}
        why, _ = rc.soak_refusal(health, SHA, "0.7.74", hours=24, now=1000.0 + 3600,
                                 ledger=upd)
        assert "1.0 h of the 24 h" in why
        assert rc.soak_refusal(health, SHA, "0.7.74", hours=24, now=1000.0 + 25 * 3600,
                               ledger=upd)[0] == ""
        assert "not 0.7.74" in rc.soak_refusal({"version": "0.7.70", "code": {}}, SHA, "0.7.74",
                                               hours=24, now=1.0, ledger={})[0]
        assert "not " + SHA[:7] in rc.soak_refusal(
            {"version": "0.7.74", "code": {"commit": "f" * 40}}, SHA, "0.7.74",
            hours=24, now=1.0, ledger={})[0]
        assert "cannot say" in rc.soak_refusal(
            {"version": "0.7.74", "code": {"commit": None}}, SHA, "0.7.74",
            hours=24, now=1.0, ledger={})[0]

    def test_soak_check_needs_a_studio_and_persists_the_clock(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CCSYNC_STUDIO_URL", raising=False)
        assert "CCSYNC_STUDIO_URL" in rc.soak_check(SHA, "0.7.74", hours=24, dry_run=False)
        monkeypatch.setenv("CCSYNC_STUDIO_URL", "http://studio")
        monkeypatch.setenv("DASH_REPORT_TOKEN", "t" * 30)
        ledger = tmp_path / "soak.json"
        monkeypatch.setenv("CCSYNC_SOAK_LEDGER", str(ledger))
        monkeypatch.setattr(rc, "fetch_studio_health",
                            lambda u, t: {"version": "0.7.74", "code": {"commit": SHA}})
        assert "starts now" in rc.soak_check(SHA, "0.7.74", hours=24, dry_run=True, now=5.0)
        assert not ledger.exists()                       # a dry run starts no clock
        assert "starts now" in rc.soak_check(SHA, "0.7.74", hours=24, dry_run=False, now=5.0)
        assert json.loads(ledger.read_text())[f"0.7.74@{SHA[:12]}"] == 5.0
        assert rc.soak_check(SHA, "0.7.74", hours=24, dry_run=False, now=5.0 + 90000) == ""

    def test_publish_feed_refuses_make_current_without_green_ci(self, monkeypatch):
        import argparse
        a = argparse.Namespace(github_upload=True, make_current=True, artifact="x",
                               git_sha=SHA, git_dirty="0", allow_red_ci=False)
        monkeypatch.setattr(pl, "ci_green_for", lambda sha: False)
        assert "no successful ci.yml" in pf._ci_gate_impl(a)
        monkeypatch.setattr(pl, "ci_green_for", lambda sha: True)
        monkeypatch.setattr(pl, "remote_head_sha", lambda: SHA)
        monkeypatch.setattr(pl, "commit_is_on_main", lambda sha, tip="": False)
        assert "not an ancestor" in pf._ci_gate_impl(a)
        monkeypatch.setattr(pl, "commit_is_on_main", lambda sha, tip="": True)
        assert pf._ci_gate_impl(a) == ""
        a.git_dirty = "1"
        assert "no clean git commit" in pf._ci_gate_impl(a)
        a.git_dirty, a.git_sha = "0", ""
        assert "no clean git commit" in pf._ci_gate_impl(a)
        a.allow_red_ci = True
        assert pf._ci_gate_impl(a) == ""
        a.allow_red_ci, a.make_current = False, False       # pointer not moved: not gated
        assert pf._ci_gate_impl(a) == ""

    def test_short_manifest_sha_passes_the_real_gate(self, monkeypatch):
        """CR-371 round 2: client manifests carry `rev-parse --short`; only gh
        and git are faked, ci_green_for / commit_is_on_main run for real."""
        import argparse
        import json as _json
        full = "0123456789abcdef0123456789abcdef01234567"

        def fake_run(cmd, **kw):
            if cmd[:2] == ["gh", "run"]:
                return 0, _json.dumps([{"databaseId": 1, "headSha": full}]), ""
            if "rev-parse" in cmd:
                return (0, full + "\n", "") if cmd[-1].startswith(full[:7]) else (1, "", "bad")
            if "ls-remote" in cmd:
                return 0, f"{full}\trefs/heads/{pl.RELEASE_BRANCH}\n", ""
            if "merge-base" in cmd:
                return 0, "", ""
            return 1, "", "unexpected"
        monkeypatch.setattr(pl, "run", fake_run)
        a = argparse.Namespace(github_upload=True, make_current=True, artifact="x",
                               git_sha=full[:7], git_dirty="0", allow_red_ci=False)
        assert pf._ci_gate_impl(a) == ""
        a.git_sha = "deadbee"
        assert "can resolve" in pf._ci_gate_impl(a)

    def test_short_sha_from_a_manifest_reaches_the_real_gate(self, monkeypatch, tmp_path):
        """CR-371 round 2: the sha enters via _apply_manifest (manifest
        git_commit -> args.git_sha), the path publish_latest/ship.cmd take."""
        import argparse
        import json as _json
        full = "0123456789abcdef0123456789abcdef01234567"

        def fake_run(cmd, **kw):
            if cmd[:2] == ["gh", "run"]:
                return 0, _json.dumps([{"databaseId": 1, "headSha": full}]), ""
            if "rev-parse" in cmd:
                return (0, full + "\n", "") if cmd[-1].startswith(full[:7]) else (1, "", "bad")
            if "ls-remote" in cmd:
                return 0, f"{full}\trefs/heads/{pl.RELEASE_BRANCH}\n", ""
            if "merge-base" in cmd:
                return 0, "", ""
            return 1, "", "unexpected"
        monkeypatch.setattr(pl, "run", fake_run)
        a = argparse.Namespace(
            github_upload=True, make_current=True, artifact="x", git_sha="",
            git_dirty="", allow_red_ci=False, allow_dirty=False, allow_untested=False,
            version="1", platform="windows", kind="companion", arch="", min_version="",
            runtime_id="", signed_binary=None, requires_dashboard="", notes="",
            published_at="", baked_pubkey_ids="")
        pf._apply_manifest(a, {"git_commit": full[:7], "version": "1",
                               "platform": "windows"}, tmp_path)
        assert a.git_sha == full[:7]
        assert pf._ci_gate_impl(a) == ""

    def test_generated_at_is_always_after_the_channel_it_replaces(self):
        now = "2026-10-08T10:00:00Z"
        assert pf.stamp_generated_at("2026-10-08T09:00:00Z", now) == (now, "")
        stamped, warn = pf.stamp_generated_at("2026-10-08T10:05:00Z", now)
        assert stamped == "2026-10-08T10:05:01Z" and "AHEAD" in warn
        stamped, warn = pf.stamp_generated_at("2026-10-08T10:00:00Z", now)
        assert stamped == "2026-10-08T10:00:01Z" and warn == ""
        assert pf.stamp_generated_at("", now) == (now, "")

    def test_the_release_command_passes_the_sftp_digest_and_commit_to_the_feed(
            self, monkeypatch, tmp_path):
        f = ReleaseFake(monkeypatch, tmp_path)
        assert _main("--poll", "0") == 0
        feed = next(c for c in f.log if len(c) > 1 and c[1].endswith("publish_feed.py"))
        assert feed[feed.index("--set-sftp-digest") + 1] == SFTP_DIGEST
        assert feed[feed.index("--git-sha") + 1] == SHA

    def test_ship_publish_feed_names_a_commit_for_the_wizard(self):
        text = (TOOLS / "ship.ps1").read_text(encoding="utf-8")
        assert '"--git-sha", $headSha' in text


# ------------------------------------------------------------- GL-50: digest pinning


REAL_COMPOSE = REPO / "dashboard" / "deploy" / "compose.appliance.yaml"


class TestPinCompose:
    def test_pins_both_vendor_images_and_leaves_the_rest(self):
        text = REAL_COMPOSE.read_text(encoding="utf-8")
        out = pin.pin(text, version="0.7.74", dashboard_digest=DIGEST, sftp_digest=SFTP_DIGEST)
        assert out.count(f":0.7.74@{DIGEST}") == 2          # secrets-init + dashboard
        assert out.count(f":0.7.74@{SFTP_DIGEST}") == 1
        assert pin.unpinned(out) == []
        assert "syncthing/syncthing:1.30.0" in out
        assert re.search(r"tailscale/tailscale:v[\d.]+@sha256:[0-9a-f]{64}", out)

    def test_pinning_twice_replaces_the_old_digest(self):
        text = REAL_COMPOSE.read_text(encoding="utf-8")
        once = pin.pin(text, version="0.7.74", dashboard_digest=DIGEST, sftp_digest=SFTP_DIGEST)
        newer = "sha256:" + "d" * 64
        twice = pin.pin(once, version="0.7.75", dashboard_digest=newer, sftp_digest=SFTP_DIGEST)
        assert DIGEST not in twice and f":0.7.75@{newer}" in twice

    def test_the_floating_tag_is_reported_until_a_release_pins_it(self):
        assert pin.unpinned('image: "${CCSYNC_IMAGE:-ghcr.io/x/ccsync}:1"') == ["CCSYNC_IMAGE:1"]

    @pytest.mark.parametrize("version,dash,sftp", [
        ("1", DIGEST, SFTP_DIGEST), ("0.7.74", "sha256:abc", SFTP_DIGEST),
        ("0.7.74", DIGEST, "latest")])
    def test_a_malformed_version_or_digest_is_refused(self, version, dash, sftp):
        with pytest.raises(pin.PinError):
            pin.pin(REAL_COMPOSE.read_text(encoding="utf-8"), version=version,
                    dashboard_digest=dash, sftp_digest=sftp)

    def test_the_cli_check_flags_an_unpinned_file(self, tmp_path, capsys):
        f = tmp_path / "c.yaml"
        f.write_text('image: "${CCSYNC_IMAGE:-ghcr.io/x/ccsync}:1"\n', encoding="utf-8")
        assert pin.main(["--compose", str(f), "--check"]) == 1


# --------------------------------------------------------------- GL-24: freshness check


NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)


def _channel(dash="0.7.73", image=DIGEST, generated="2026-10-06T00:00:00Z", **extra):
    c = {"generated_at": generated, "current": {"dashboard/linux": dash},
         "dashboard_image": {"tag": dash, "digest": image}, "packages": []}
    c.update(extra)
    return c


class TestFeedFreshness:
    def test_fresh(self):
        assert cff.judge(_channel(), "0.7.74", max_behind=3, max_age_days=45, now=NOW) == []

    def test_the_month_stale_channel_the_review_found(self):
        out = cff.judge(_channel(dash="0.7.44", generated="2026-09-26T00:00:00Z"), "0.7.73",
                        max_behind=3, max_age_days=45, now=NOW)
        assert any("29 releases behind" in p for p in out)

    def test_a_different_minor_is_always_far_behind(self):
        out = cff.judge(_channel(dash="0.7.73"), "0.8.0", max_behind=3, max_age_days=45, now=NOW)
        assert any("different minor release" in p for p in out)

    def test_a_missing_image_digest_means_nothing_to_pin(self):
        out = cff.judge(_channel(image=""), "0.7.73", max_behind=3, max_age_days=45, now=NOW)
        assert any("dashboard_image digest" in p for p in out)

    def test_a_companion_newer_than_the_dashboard_is_flagged(self):
        c = _channel(current={"dashboard/linux": "0.7.44", "companion/windows": "0.9.82"},
                     packages=[{"kind": "companion", "platform": "windows",
                                "version": "0.9.82", "requires_dashboard": "0.7.60"}])
        out = cff.judge(c, "0.7.44", max_behind=3, max_age_days=45, now=NOW)
        assert any("needs dashboard 0.7.60" in p for p in out)

    def test_an_old_channel_behind_a_quiet_repo_is_not_an_alarm(self):
        c = _channel(generated="2026-01-01T00:00:00Z")
        assert cff.judge(c, "0.7.73", max_behind=3, max_age_days=45, now=NOW) == []

    def test_no_current_dashboard_at_all_fails(self):
        out = cff.judge({"current": {}, "packages": []}, "0.7.73", max_behind=3,
                        max_age_days=45, now=NOW)
        assert out and "no current dashboard" in out[0]

    def test_an_unreadable_feed_is_not_checked_never_ok(self, monkeypatch):
        monkeypatch.setattr(pf, "fetch_published_channel", lambda *a, **k: (None, "", "boom"))
        assert cff.main([]) == cff.EXIT_UNCHECKED


# ------------------------------------------------- GL-25: the workflows, as text


WORKFLOWS = REPO / ".github" / "workflows"


class TestWorkflows:
    def test_every_action_is_pinned_to_a_commit_sha(self):
        for wf in sorted(WORKFLOWS.glob("*.yml")):
            for n, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
                m = re.match(r"^\s*(?:-\s*)?uses:\s*(\S+)", line)
                if m and not m.group(1).startswith("./"):
                    assert re.search(r"@[0-9a-f]{40}$", m.group(1)), f"{wf.name}:{n} {line.strip()}"

    def test_the_image_build_cannot_start_before_the_tag_gate(self):
        text = (WORKFLOWS / "image.yml").read_text(encoding="utf-8")
        assert re.search(r"^  gate:", text, re.M)
        build = text.split("\n  build:")[1].split("\n  promote:")[0]
        assert "needs: gate" in build
        for needle in ("is not an ancestor of origin/main", "is not the newest v* tag",
                       "--workflow ci.yml", 'if [ "$TAG" != "v$version" ]'):
            assert needle in text, needle

    def test_the_build_job_never_pushes_version_or_one(self):
        text = (WORKFLOWS / "image.yml").read_text(encoding="utf-8")
        build = text.split("\n  build:")[1].split("\n  promote:")[0]
        assert "$image:$version" not in build and "$image:1" not in build
        assert "refs/heads/main" in build           # :edge only from main
        assert "refuse to overwrite an existing :<VERSION>" in build

    def test_the_image_is_booted_before_it_is_promoted(self):
        text = (WORKFLOWS / "image.yml").read_text(encoding="utf-8")
        assert text.index("smoke test - boot the pushed digest") < text.index("\n  promote:")
        assert "/api/v1/health" in text and "/setup" in text

    def test_promotion_waits_for_the_reviewer_environment_and_publishes_digests(self):
        text = (WORKFLOWS / "image.yml").read_text(encoding="utf-8")
        promote = text.split("\n  promote:")[1]
        assert "environment: customer-release" in promote
        assert "needs: build" in promote
        assert "name: image-digests" in promote and "digests.json" in promote
        assert rc.DIGEST_ARTIFACT == "image-digests"

    def test_no_wildcard_cosign_identity_is_published_anywhere(self):
        for rel in ("docs/DOCKER.md", ".github/workflows/image.yml"):
            text = (REPO / rel).read_text(encoding="utf-8")
            assert "certificate-identity-regexp '.*'" not in text, rel

    def test_ci_runs_nightly_and_the_freshness_check_is_scheduled(self):
        assert "schedule:" in (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        fresh = (WORKFLOWS / "feed-freshness.yml").read_text(encoding="utf-8")
        assert "check_feed_freshness.py" in fresh and "schedule:" in fresh

    def test_the_dashboard_suite_runs_before_ship_deploys_it(self):
        text = (TOOLS / "ship.ps1").read_text(encoding="utf-8")
        assert text.index("step 0c: dashboard tests") < text.index("# --- 1. dashboard ---")


def test_bundle_channel_refusal_names_different_bytes_before_tagging(tmp_path):
    """GL-24 route a (CR-371 round 3, 2026-10-07): a staged build of this version
    with other bytes must be refused by release_customers, not by publish_feed
    after the tag is pushed."""
    import hashlib
    bundle = tmp_path / "ccsync-dashboard-1.2.3.tar.gz"
    bundle.write_bytes(b"ci build")
    good = hashlib.sha256(b"ci build").hexdigest()
    rec = lambda sha: {"packages": [{"kind": "dashboard", "platform": "linux",
                                     "version": "1.2.3", "sha256": sha}]}
    assert rc.bundle_channel_refusal(bundle, {}, "1.2.3") == ""
    assert rc.bundle_channel_refusal(bundle, rec(good), "1.2.3") == ""
    msg = rc.bundle_channel_refusal(bundle, rec("0" * 64), "1.2.3")
    assert "DIFFERENT bytes" in msg and "gh run download" in msg
    assert rc.bundle_channel_refusal(bundle, rec("0" * 64), "1.2.4") == ""
    assert "retire" not in msg.split("Bump")[1].split("(")[0]


def test_bundle_channel_refusal_names_a_recalled_version(tmp_path):
    """A version only on the signed `retracted` list passes every sha check but
    publish_feed refuses it at step 4 (CR-371 round 3, 2026-10-07)."""
    bundle = tmp_path / "ccsync-dashboard-1.2.3.tar.gz"
    bundle.write_bytes(b"ci build")
    chan = {"packages": [], "retracted": [{"kind": "dashboard", "platform": "linux",
                                           "version": "1.2.3"}]}
    assert "RECALL" in rc.bundle_channel_refusal(bundle, chan, "1.2.3")
    assert rc.bundle_channel_refusal(bundle, chan, "1.2.4") == ""
