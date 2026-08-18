"""tools/publish_feed.py -- feed-directory builder and its GitHub Releases
publisher (ZERO_TOUCH_PLAN.md WP E, 2026-08-17; upload added 2026-08-18).
Every test points CCSYNC_RELEASE_KEY at a tmp key and writes into a tmp feed
dir. Nothing here touches the network or needs `gh` installed: the upload
tests inject FakeGh as the tool's runner and assert on argv."""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "companion" / "src"))

import publish_feed as pf  # noqa: E402
import release_key as release_key_mod  # noqa: E402
from ccsync_companion import ed25519, release_pubkey  # noqa: E402

BASE_URL = "https://releases.example.test/v1"


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


def _pubkeys_for(key_path) -> list[str]:
    secret = release_key_mod.read_secret(key_path)
    return [base64.b64encode(ed25519.public_key(secret)).decode("ascii")]


def test_publish_writes_channel_and_artifact(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    rc = pf.main([
        "--artifact", str(artifact), "--kind", "companion", "--platform", "windows",
        "--version", "0.8.0", "--min-version", "0.7.12", "--signed-binary",
        "--notes", "first build", "--feed-dir", str(feed_dir), "--base-url", BASE_URL,
    ])
    assert rc == pf.EXIT_OK
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    assert channel["schema"] == 1
    assert channel["channel"] == "stable"
    assert len(channel["packages"]) == 1
    record = channel["packages"][0]
    assert record["kind"] == "companion" and record["platform"] == "windows"
    assert record["version"] == "0.8.0"
    assert record["url"] == f"{BASE_URL}/windows/{record['filename']}"
    assert record["notes"] == "first build"
    assert record["min_version"] == "0.7.12"
    assert record["signed_binary"] is True
    assert (feed_dir / "windows" / record["filename"]).read_bytes() == artifact.read_bytes()
    assert (feed_dir / pf.SIG_FILENAME).is_file()

    # The record itself verifies with release_pubkey.verify_record, exactly
    # as a dashboard verifies a package row.
    pubkeys = _pubkeys_for(release_key_mod.key_path(""))
    ok, detail = release_pubkey.verify_record(record, record["signature"], pubkeys=pubkeys)
    assert ok, detail

    # And the channel-level detached signature verifies too.
    sig = (feed_dir / pf.SIG_FILENAME).read_text().strip()
    ok, detail = pf.verify_channel_signature(channel, sig, pubkeys)
    assert ok, detail


def test_verify_offline_reports_ok(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    assert pf.main(["--artifact", str(artifact), "--platform", "windows", "--version", "0.8.0",
                    "--feed-dir", str(feed_dir), "--base-url", BASE_URL]) == pf.EXIT_OK
    pubkeys = _pubkeys_for(release_key_mod.key_path(""))
    ok, report = pf.verify_feed_dir(feed_dir, pubkeys=pubkeys)
    assert ok, report
    assert any("channel signature: OK" in line for line in report)
    assert any("record companion/windows 0.8.0: OK" in line for line in report)


def test_tampering_with_the_channel_fails_verification(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    assert pf.main(["--artifact", str(artifact), "--platform", "windows", "--version", "0.8.0",
                    "--feed-dir", str(feed_dir), "--base-url", BASE_URL]) == pf.EXIT_OK
    path = feed_dir / pf.CHANNEL_FILENAME
    channel = json.loads(path.read_text())
    channel["packages"][0]["version"] = "9.9.9"   # relabel after signing
    path.write_text(json.dumps(channel, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    pubkeys = _pubkeys_for(release_key_mod.key_path(""))
    ok, report = pf.verify_feed_dir(feed_dir, pubkeys=pubkeys)
    assert not ok
    assert any("channel signature: FAILED" in line for line in report)


def test_tampering_with_one_record_fails_only_that_record(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    assert pf.main(["--artifact", str(artifact), "--platform", "windows", "--version", "0.8.0",
                    "--feed-dir", str(feed_dir), "--base-url", BASE_URL]) == pf.EXIT_OK
    path = feed_dir / pf.CHANNEL_FILENAME
    channel = json.loads(path.read_text())
    channel["packages"][0]["sha256"] = "0" * 64
    path.write_text(json.dumps(channel, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # sha256 is covered by BOTH the record's own signature and the enclosing
    # channel's -- tampering it on disk (without re-signing, which needs the
    # private key an attacker does not have) fails verification at the
    # record level, which is the check that matters for what a dashboard
    # would refuse to install.
    pubkeys = _pubkeys_for(release_key_mod.key_path(""))
    ok, report = pf.verify_feed_dir(feed_dir, pubkeys=pubkeys)
    assert not ok
    assert any("FAILED" in line and "record" in line for line in report)


def test_verify_a_directory_with_no_channel(tmp_path):
    ok, report = pf.verify_feed_dir(tmp_path / "nope")
    assert not ok
    assert report and "no" in report[0]


def test_second_publish_replaces_the_same_kind_platform_version(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    assert pf.main(["--artifact", str(artifact), "--platform", "windows", "--version", "0.8.0",
                    "--feed-dir", str(feed_dir), "--base-url", BASE_URL, "--notes", "first"]) == pf.EXIT_OK
    assert pf.main(["--artifact", str(artifact), "--platform", "windows", "--version", "0.8.0",
                    "--feed-dir", str(feed_dir), "--base-url", BASE_URL, "--notes", "second",
                    "--min-version", "0.8.0"]) == pf.EXIT_OK
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    assert len(channel["packages"]) == 1
    assert channel["packages"][0]["notes"] == "second"
    assert channel["packages"][0]["min_version"] == "0.8.0"


def test_a_second_platform_adds_a_second_record(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    assert pf.main(["--artifact", str(artifact), "--platform", "windows", "--version", "0.8.0",
                    "--feed-dir", str(feed_dir), "--base-url", BASE_URL]) == pf.EXIT_OK
    mac = tmp_path / "ccsync-companion"
    mac.write_bytes(b"\xcf\xfa\xed\xfe" + b"y" * 5000)
    assert pf.main(["--artifact", str(mac), "--platform", "macos", "--version", "0.8.0",
                    "--feed-dir", str(feed_dir), "--base-url", BASE_URL]) == pf.EXIT_OK
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    assert len(channel["packages"]) == 2
    platforms = {r["platform"] for r in channel["packages"]}
    assert platforms == {"windows", "macos"}


def test_set_image_alone_writes_a_signed_channel(key, tmp_path):
    feed_dir = tmp_path / "feed"
    rc = pf.main(["--set-image", "1.2.3@sha256:" + "a" * 64, "--feed-dir", str(feed_dir)])
    assert rc == pf.EXIT_OK
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    assert channel["dashboard_image"] == {"tag": "1.2.3", "digest": "sha256:" + "a" * 64}
    pubkeys = _pubkeys_for(release_key_mod.key_path(""))
    ok, _report = pf.verify_feed_dir(feed_dir, pubkeys=pubkeys)
    assert ok


def test_set_image_bad_shape_is_refused(key, tmp_path):
    rc = pf.main(["--set-image", "no-at-sign-here", "--feed-dir", str(tmp_path / "feed")])
    assert rc == pf.EXIT_USAGE


def test_manifest_refuses_dirty_or_untested_unless_overridden(key, tmp_path, artifact):
    man = artifact.parent / "ccsync-release.json"
    base = {"version": "0.8.0", "platform": "windows", "artifact": artifact.name,
            "signed_binary": False, "git_dirty": False, "tests_run": True}
    feed_dir = tmp_path / "feed"
    common = ["--manifest", str(man), "--feed-dir", str(feed_dir), "--base-url", BASE_URL]

    man.write_text(json.dumps({**base, "git_dirty": True}), encoding="utf-8")
    assert pf.main(common) == pf.EXIT_CONDEMNED
    assert pf.main(common + ["--allow-dirty"]) == pf.EXIT_OK

    man.write_text(json.dumps({**base, "tests_run": False}), encoding="utf-8")
    assert pf.main(common) == pf.EXIT_CONDEMNED
    assert pf.main(common + ["--allow-untested"]) == pf.EXIT_OK


def test_dry_run_writes_nothing(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    rc = pf.main(["--artifact", str(artifact), "--platform", "windows", "--version", "0.8.0",
                  "--feed-dir", str(feed_dir), "--base-url", BASE_URL, "--dry-run"])
    assert rc == pf.EXIT_OK
    assert not feed_dir.exists()


def test_nothing_to_do_is_a_usage_error(key, tmp_path):
    rc = pf.main(["--feed-dir", str(tmp_path / "feed")])
    assert rc == pf.EXIT_USAGE


def test_missing_key_is_a_message_not_a_partial_write(artifact, monkeypatch, tmp_path):
    monkeypatch.setenv("CCSYNC_RELEASE_KEY", str(tmp_path / "absent.key"))
    feed_dir = tmp_path / "feed"
    rc = pf.main(["--artifact", str(artifact), "--platform", "windows", "--version", "0.8.0",
                  "--feed-dir", str(feed_dir), "--base-url", BASE_URL])
    assert rc == pf.EXIT_USAGE
    assert not feed_dir.exists()


# --------------------------------------------------------------------------
# GitHub Releases publishing (2026-08-18)
# --------------------------------------------------------------------------

GH_REPO = "ccsync/ccsync-releases"
GH_TAG = pf.DEFAULT_GITHUB_TAG
DERIVED = f"https://github.com/{GH_REPO}/releases/download/{GH_TAG}"


class FakeGh:
    """Stands in for the real `gh`. Records every argv, answers
    `release view` from `release_exists` and everything else from
    `rc_by_verb` (default 0). `on_call` fires before the answer, which is how
    the sign-before-upload ordering is observed."""

    def __init__(self, *, release_exists=True, rc_by_verb=None, on_call=None):
        self.calls: list[list[str]] = []
        self.release_exists = release_exists
        self.rc_by_verb = dict(rc_by_verb or {})
        self.on_call = on_call

    def __call__(self, argv):
        self.calls.append(list(argv))
        if self.on_call is not None:
            self.on_call(list(argv))
        verb = " ".join(argv[1:3])
        if verb == "release view":
            return (0, "", "") if self.release_exists else (1, "", "release not found")
        rc = self.rc_by_verb.get(verb, 0)
        return rc, "", ("gh says no" if rc else "")

    def verbs(self) -> list[str]:
        return [" ".join(c[1:3]) for c in self.calls]

    def upload_argv(self) -> list[str]:
        uploads = [c for c in self.calls if c[1:3] == ["release", "upload"]]
        assert len(uploads) == 1, self.calls
        return uploads[0]


def _build(feed_dir, artifact, *extra, upload=False, runner=None):
    argv = ["--artifact", str(artifact), "--platform", "windows", "--version", "0.8.0",
            "--feed-dir", str(feed_dir), "--github-repo", GH_REPO, *extra]
    if upload:
        argv.append("--github-upload")
    return pf.main(argv, runner=runner) if runner is not None else pf.main(argv)


def test_github_repo_derives_the_base_url(key, artifact, tmp_path, capsys):
    feed_dir = tmp_path / "feed"
    assert _build(feed_dir, artifact) == pf.EXIT_OK
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    record = channel["packages"][0]
    # Flat, no <platform>/ segment: that is exactly where a GitHub release
    # asset is served from, and the url is inside the signed document.
    assert record["url"] == f"{DERIVED}/{record['filename']}"
    assert "base URL derived" in capsys.readouterr().out


def test_a_custom_github_tag_moves_the_derived_url(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    assert _build(feed_dir, artifact, "--github-tag", "ccsync-releases-beta") == pf.EXIT_OK
    record = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())["packages"][0]
    assert record["url"].startswith(
        f"https://github.com/{GH_REPO}/releases/download/ccsync-releases-beta/")


def test_a_base_url_contradicting_the_derived_one_is_refused(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    rc = _build(feed_dir, artifact, "--base-url", "https://releases.example.test/v1")
    assert rc == pf.EXIT_USAGE
    assert not feed_dir.exists()


def test_a_base_url_agreeing_with_the_derived_one_is_fine(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    assert _build(feed_dir, artifact, "--base-url", DERIVED + "/") == pf.EXIT_OK


def test_github_repo_without_upload_runs_no_gh_command(key, artifact, tmp_path, capsys):
    feed_dir = tmp_path / "feed"
    gh = FakeGh()
    assert _build(feed_dir, artifact, runner=gh) == pf.EXIT_OK
    assert gh.calls == []
    assert (feed_dir / pf.SIG_FILENAME).is_file()
    assert "--github-upload" in capsys.readouterr().out


def test_github_upload_without_a_repo_is_a_usage_error(key, artifact, tmp_path):
    rc = pf.main(["--artifact", str(artifact), "--platform", "windows", "--version", "0.8.0",
                  "--feed-dir", str(tmp_path / "feed"), "--base-url", BASE_URL, "--github-upload"])
    assert rc == pf.EXIT_USAGE


def test_upload_argv_has_clobber_the_channel_the_sig_and_every_artifact(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    assert _build(feed_dir, artifact) == pf.EXIT_OK
    mac = tmp_path / "ccsync-companion"
    mac.write_bytes(b"\xcf\xfa\xed\xfe" + b"y" * 5000)
    gh = FakeGh()
    rc = pf.main(["--artifact", str(mac), "--platform", "macos", "--version", "0.8.0",
                  "--feed-dir", str(feed_dir), "--github-repo", GH_REPO, "--github-upload"],
                 runner=gh)
    assert rc == pf.EXIT_OK
    argv = gh.upload_argv()
    assert argv[:4] == ["gh", "release", "upload", GH_TAG]
    assert argv[-3:] == ["--clobber", "-R", GH_REPO]
    assert [Path(a).name for a in argv[4:-3]] == [
        pf.CHANNEL_FILENAME, pf.SIG_FILENAME,
        "ccsync-companion-0.8.0.exe", "ccsync-companion-0.8.0",
    ]
    # Every uploaded path really is a file we just wrote.
    assert all(Path(a).is_file() for a in argv[4:-3])
    # ... and each asset name is exactly the last segment of the matching
    # signed url, which is the whole reason the plan is asserted before the push.
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    for record in channel["packages"]:
        assert record["url"].rsplit("/", 1)[-1] == record["filename"]


def test_release_is_created_when_absent_and_the_run_still_succeeds(key, artifact, tmp_path):
    gh = FakeGh(release_exists=False)
    assert _build(tmp_path / "feed", artifact, upload=True, runner=gh) == pf.EXIT_OK
    assert gh.verbs() == ["auth status", "release view", "release create", "release upload"]
    create = [c for c in gh.calls if c[1:3] == ["release", "create"]][0]
    assert create[3] == GH_TAG and "-R" in create and GH_REPO in create


def test_a_release_that_already_exists_is_not_created_twice(key, artifact, tmp_path):
    gh = FakeGh(release_exists=True)
    assert _build(tmp_path / "feed", artifact, upload=True, runner=gh) == pf.EXIT_OK
    assert "release create" not in gh.verbs()


def test_a_create_that_races_another_ship_is_not_fatal(key, artifact, tmp_path):
    class Racy(FakeGh):
        def __call__(self, argv):
            rc, stdout, stderr = super().__call__(argv)
            if argv[1:3] == ["release", "create"]:
                return 1, "", "a release with tag already exists"
            return rc, stdout, stderr

    gh = Racy(release_exists=False)
    assert _build(tmp_path / "feed", artifact, upload=True, runner=gh) == pf.EXIT_OK
    assert "release upload" in gh.verbs()


def test_missing_gh_is_a_clear_error_and_claims_nothing_uploaded(key, artifact, tmp_path, capsys):
    feed_dir = tmp_path / "feed"

    def no_gh(argv):
        return pf.GH_NOT_FOUND, "", "gh not found on PATH"

    rc = _build(feed_dir, artifact, upload=True, runner=no_gh)
    assert rc == pf.EXIT_UPLOAD_FAILED
    captured = capsys.readouterr()
    assert "not on PATH" in captured.err and "gh auth login" in captured.err
    assert "uploaded" not in captured.out
    # The local feed is still whole and still verifies -- the failure is the
    # upload, and it says so rather than leaving a half-truth behind.
    pubkeys = _pubkeys_for(release_key_mod.key_path(""))
    ok, report = pf.verify_feed_dir(feed_dir, pubkeys=pubkeys)
    assert ok, report


def test_unauthenticated_gh_is_refused_before_any_release_command(key, artifact, tmp_path, capsys):
    gh = FakeGh(rc_by_verb={"auth status": 1})
    rc = _build(tmp_path / "feed", artifact, upload=True, runner=gh)
    assert rc == pf.EXIT_UPLOAD_FAILED
    assert gh.verbs() == ["auth status"]
    assert "gh auth login" in capsys.readouterr().err


def test_a_failing_upload_is_a_non_zero_exit_not_a_success(key, artifact, tmp_path, capsys):
    gh = FakeGh(rc_by_verb={"release upload": 1})
    rc = _build(tmp_path / "feed", artifact, upload=True, runner=gh)
    assert rc == pf.EXIT_UPLOAD_FAILED
    captured = capsys.readouterr()
    assert "uploaded" not in captured.out
    assert "--clobber" in captured.err     # names the idempotent retry


def test_signing_happens_before_any_upload(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    observed: dict = {}

    def on_call(argv):
        observed.setdefault("first_verb", " ".join(argv[1:3]))
        observed.setdefault("channel", (feed_dir / pf.CHANNEL_FILENAME).is_file())
        observed.setdefault("sig", (feed_dir / pf.SIG_FILENAME).is_file())
        if "channel_bytes" not in observed and (feed_dir / pf.CHANNEL_FILENAME).is_file():
            observed["channel_bytes"] = (feed_dir / pf.CHANNEL_FILENAME).read_bytes()

    gh = FakeGh(on_call=on_call)
    assert _build(feed_dir, artifact, upload=True, runner=gh) == pf.EXIT_OK
    assert observed["channel"] is True and observed["sig"] is True
    # Not merely written -- SIGNED and self-verified: the bytes on disk when
    # gh was first invoked are the bytes that were uploaded, unchanged.
    assert observed["channel_bytes"] == (feed_dir / pf.CHANNEL_FILENAME).read_bytes()
    pubkeys = _pubkeys_for(release_key_mod.key_path(""))
    ok, report = pf.verify_feed_dir(feed_dir, pubkeys=pubkeys)
    assert ok, report


def test_a_record_pointing_somewhere_else_is_refused_before_any_gh_call(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    # Built for a non-GitHub host first, then someone tries to push it to a
    # release: every record's signed url names the old host.
    assert pf.main(["--artifact", str(artifact), "--platform", "windows", "--version", "0.8.0",
                    "--feed-dir", str(feed_dir), "--base-url", BASE_URL]) == pf.EXIT_OK
    gh = FakeGh()
    rc = pf.main(["--set-image", "1.2.3@sha256:" + "a" * 64, "--feed-dir", str(feed_dir),
                  "--github-repo", GH_REPO, "--github-upload"], runner=gh)
    assert rc == pf.EXIT_USAGE
    assert gh.calls == []


def test_asset_plan_refuses_two_records_sharing_one_asset_name(tmp_path):
    channel = {"packages": [
        {"kind": "companion", "platform": "windows", "version": "0.8.0",
         "filename": "same.exe", "url": f"{DERIVED}/same.exe"},
        {"kind": "onboard", "platform": "windows", "version": "0.8.0",
         "filename": "same.exe", "url": f"{DERIVED}/same.exe"},
    ]}
    with pytest.raises(pf.PublishFeedError) as exc:
        pf.github_asset_plan(tmp_path, channel, base_url=DERIVED)
    assert exc.value.code == pf.EXIT_USAGE


def test_an_artifact_missing_locally_is_a_note_not_a_failure(key, artifact, tmp_path, capsys):
    feed_dir = tmp_path / "feed"
    assert _build(feed_dir, artifact) == pf.EXIT_OK
    (feed_dir / "windows" / "ccsync-companion-0.8.0.exe").unlink()
    gh = FakeGh()
    rc = pf.main(["--set-image", "1.2.3@sha256:" + "a" * 64, "--feed-dir", str(feed_dir),
                  "--github-repo", GH_REPO, "--github-upload"], runner=gh)
    assert rc == pf.EXIT_OK
    assert "already carries it" in capsys.readouterr().out
    assert [Path(a).name for a in gh.upload_argv()[4:-3]] == [pf.CHANNEL_FILENAME, pf.SIG_FILENAME]


def test_republishing_the_same_feed_is_idempotent(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    first, second = FakeGh(release_exists=False), FakeGh(release_exists=True)
    assert _build(feed_dir, artifact, upload=True, runner=first) == pf.EXIT_OK
    assert _build(feed_dir, artifact, upload=True, runner=second) == pf.EXIT_OK
    assert first.upload_argv()[3:] == second.upload_argv()[3:]
    assert "--clobber" in second.upload_argv()
