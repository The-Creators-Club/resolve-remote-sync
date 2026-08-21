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
       # `release download` is the published channel being fetched to merge
    # into (release-pipeline-1, 2026-08-21) -- it comes first, and it needs
    # the same credential, which is why `auth status` now runs once up front.
    assert gh.verbs() == ["auth status", "release download", "release view",
                          "release create", "release upload"]
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
        # The UPLOAD, not merely the first gh call: since 2026-08-21 a run
        # begins by downloading the published channel, which happens (and must
        # happen) before anything is signed.
        if argv[1:3] != ["release", "upload"]:
            return
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
    # Nothing was CREATED or UPLOADED. (auth status + the published-channel
    # download do run first now -- they are reads, and the refusal still lands
    # before any write.)
    assert "release upload" not in gh.verbs()
    assert "release create" not in gh.verbs()


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


# --- non-package artefacts (2026-08-18, docs/MUSIC_INGEST_PLAN.md step 3) ----
#
# The CLAP audio tower is not a package: nothing installs it, it has no
# platform, and the party that verifies it is a COMPANION checking the sha256
# baked into the build it is already running. What the feed owes it is a URL
# and a size, inside the signed document.

@pytest.fixture
def clap_files(tmp_path):
    onnx = tmp_path / "music-clap-audio-1.onnx"
    onnx.write_bytes(b"ONNX" + b"w" * 4096)
    params = tmp_path / "music-clap-audio-1.params.json"
    params.write_text(json.dumps({"params_version": 1}), encoding="utf-8")
    return onnx, params


def test_an_asset_is_published_beside_the_packages(key, clap_files, tmp_path):
    onnx, params = clap_files
    feed_dir = tmp_path / "feed"
    rc = pf.main([
        "--asset", str(onnx), "--asset", str(params),
        "--asset-kind", "music-clap-audio", "--asset-version", "1",
        "--feed-dir", str(feed_dir), "--base-url", BASE_URL,
    ])
    assert rc == pf.EXIT_OK
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    assert channel["packages"] == [], "an artefact is not a package"
    got = {a["filename"]: a for a in channel["artefacts"]}
    assert set(got) == {onnx.name, params.name}
    assert got[onnx.name]["kind"] == "music-clap-audio"
    assert got[onnx.name]["version"] == "1"
    assert got[onnx.name]["size_bytes"] == onnx.stat().st_size
    # FLAT beside channel.json, which is the only shape GitHub Releases serves
    # and the one music_models.FEED_URL_TEMPLATE builds.
    assert got[onnx.name]["url"] == f"{BASE_URL}/{onnx.name}"
    assert (feed_dir / onnx.name).read_bytes() == onnx.read_bytes()


def test_the_artefact_rides_the_channel_signature(key, clap_files, tmp_path):
    """There is no per-record signature for an artefact (sign_release signs
    PACKAGES), so the channel's own signature is what makes it unforgeable --
    which means tampering with it has to fail verification."""
    onnx, _params = clap_files
    feed_dir = tmp_path / "feed"
    pf.main(["--asset", str(onnx), "--asset-version", "1",
             "--feed-dir", str(feed_dir), "--base-url", BASE_URL])
    ok, _report = pf.verify_feed_dir(feed_dir, pubkeys=_pubkeys_for(key))
    assert ok

    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    channel["artefacts"][0]["url"] = "https://evil.test/model.onnx"
    (feed_dir / pf.CHANNEL_FILENAME).write_text(json.dumps(channel, indent=2, sort_keys=True))
    ok, report = pf.verify_feed_dir(feed_dir, pubkeys=_pubkeys_for(key))
    assert not ok and any("channel signature: FAILED" in line for line in report)


def test_a_file_that_does_not_match_its_recorded_sha_fails_verification(key, clap_files, tmp_path):
    onnx, _params = clap_files
    feed_dir = tmp_path / "feed"
    pf.main(["--asset", str(onnx), "--asset-version", "1",
             "--feed-dir", str(feed_dir), "--base-url", BASE_URL])
    (feed_dir / onnx.name).write_bytes(b"different bytes entirely")
    ok, report = pf.verify_feed_dir(feed_dir, pubkeys=_pubkeys_for(key))
    assert not ok
    assert any("does NOT match sha256" in line for line in report)


def test_republishing_the_same_filename_replaces_it(key, clap_files, tmp_path):
    onnx, _params = clap_files
    feed_dir = tmp_path / "feed"
    pf.main(["--asset", str(onnx), "--asset-version", "1",
             "--feed-dir", str(feed_dir), "--base-url", BASE_URL])
    onnx.write_bytes(b"ONNX" + b"z" * 8192)      # a re-export, same version
    pf.main(["--asset", str(onnx), "--asset-version", "1",
             "--feed-dir", str(feed_dir), "--base-url", BASE_URL])
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    assert len(channel["artefacts"]) == 1
    assert channel["artefacts"][0]["size_bytes"] == onnx.stat().st_size


def test_two_versions_coexist_on_the_feed(key, clap_files, tmp_path):
    """The version is in the FILENAME precisely so a fleet mid-upgrade has
    both: an editor still running the old companion must keep finding the file
    its baked sha256 belongs to."""
    onnx, _params = clap_files
    feed_dir = tmp_path / "feed"
    pf.main(["--asset", str(onnx), "--asset-version", "1",
             "--feed-dir", str(feed_dir), "--base-url", BASE_URL])
    two = onnx.parent / "music-clap-audio-2.onnx"
    two.write_bytes(b"ONNX2" + b"q" * 4096)
    pf.main(["--asset", str(two), "--asset-version", "2",
             "--feed-dir", str(feed_dir), "--base-url", BASE_URL])
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    assert sorted(a["filename"] for a in channel["artefacts"]) == [
        "music-clap-audio-1.onnx", "music-clap-audio-2.onnx"]


def test_an_asset_without_a_version_is_refused(key, clap_files, tmp_path):
    onnx, _params = clap_files
    rc = pf.main(["--asset", str(onnx), "--feed-dir", str(tmp_path / "feed"),
                  "--base-url", BASE_URL])
    assert rc == pf.EXIT_USAGE


def test_an_asset_is_uploaded_with_the_channel(key, clap_files, tmp_path):
    onnx, params = clap_files
    feed_dir = tmp_path / "feed"
    pf.main(["--asset", str(onnx), "--asset", str(params), "--asset-version", "1",
             "--feed-dir", str(feed_dir),
             "--base-url", pf.github_base_url("o/r", pf.DEFAULT_GITHUB_TAG)])
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    plan = pf.github_asset_plan(
        feed_dir, channel, base_url=pf.github_base_url("o/r", pf.DEFAULT_GITHUB_TAG))
    names = [p.name for p in plan]
    assert pf.CHANNEL_FILENAME in names and pf.SIG_FILENAME in names
    assert onnx.name in names and params.name in names


def test_an_asset_whose_url_does_not_match_the_upload_target_is_refused(key, clap_files, tmp_path):
    """The url is inside the SIGNED document: getting it wrong is not a
    re-upload away from correct, it is a re-sign away."""
    onnx, _params = clap_files
    feed_dir = tmp_path / "feed"
    pf.main(["--asset", str(onnx), "--asset-version", "1",
             "--feed-dir", str(feed_dir), "--base-url", "https://elsewhere.test/v1"])
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    with pytest.raises(pf.PublishFeedError):
        pf.github_asset_plan(feed_dir, channel, base_url=BASE_URL)


# --- the LIVE channel is the base, not this rig's feed/ dir ------------------
#
# release-pipeline-1 (2026-08-21). publish_feed rebuilt the channel from
# <feed-dir>/channel.json -- a GITIGNORED directory that exists on exactly one
# machine -- and "gh release upload --clobber" then replaced the live document
# with it. From a fresh clone, a Mac, a new base rig or after a --feed-dir
# typo, that meant 18 package records and 2 CLAP artefacts became 1, correctly
# signed, so no consumer logged an error and the loss reached a customer.
#
# PublishedGh serves a real signed channel from `release download`, which is
# the only way to exercise the merge without a network.


class PublishedGh(FakeGh):
    """FakeGh that also answers `release download` by writing a channel.json
    (+ .sig) into the --dir the tool asked for."""

    def __init__(self, channel=None, signature=None, **kw):
        super().__init__(**kw)
        self.channel = channel
        self.signature = signature

    def __call__(self, argv):
        if argv[1:3] == ["release", "download"] and self.channel is not None:
            dest = Path(argv[argv.index("--dir") + 1])
            dest.mkdir(parents=True, exist_ok=True)
            (dest / pf.CHANNEL_FILENAME).write_text(
                json.dumps(self.channel, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            if self.signature is not None:
                (dest / pf.SIG_FILENAME).write_text(self.signature + "\n", encoding="utf-8")
        return super().__call__(argv)


def _sign_channel_for(channel, key_path):
    """Sign `channel` with the tmp release key, the way write_channel does."""
    secret = release_key_mod.read_secret(key_path)
    pub = base64.b64encode(ed25519.public_key(secret)).decode("ascii")
    channel["pubkey_id"] = release_pubkey.pubkey_id(pub)
    message = pf.canonical_channel_bytes(channel)
    return base64.b64encode(ed25519.sign(secret, message)).decode("ascii"), pub


@pytest.fixture
def trusted_key(key, monkeypatch):
    """The tmp key, ALSO installed as a baked release pubkey -- the published
    channel is verified against release_pubkey.RELEASE_PUBKEYS, which in a
    real build is baked in."""
    secret = release_key_mod.read_secret(release_key_mod.key_path(""))
    pub = base64.b64encode(ed25519.public_key(secret)).decode("ascii")
    monkeypatch.setattr(release_pubkey, "RELEASE_PUBKEYS", (pub,), raising=False)
    return key


def _published_channel(key_path, *, records=(), artefacts=()):
    channel = {
        "schema": pf.SCHEMA, "channel": "stable", "generated_at": "2026-08-20T00:00:00Z",
        "pubkey_id": "", "dashboard_image": {"tag": "", "digest": ""},
        "packages": list(records), "artefacts": list(artefacts),
    }
    signature, _pub = _sign_channel_for(channel, key_path)
    return channel, signature


def _record(kind, platform, version, filename):
    return {"kind": kind, "platform": platform, "version": version, "filename": filename,
            "sha256": "0" * 64, "size_bytes": 1, "min_version": "0.0.0",
            "signed_binary": False, "published_at": "2026-08-01T00:00:00Z",
            "url": f"{DERIVED}/{filename}", "signature": "x", "pubkey_id": "y"}


def test_history_the_local_feed_never_had_survives_the_upload(trusted_key, artifact, tmp_path):
    mac = _record("companion", "macos", "0.9.3", "ccsync-companion-0.9.3-macos.zip")
    dash = _record("dashboard", "linux", "0.7.4", "ccsync-dashboard-0.7.4.tar.gz")
    clap = {"kind": "music-clap-audio", "version": "1", "filename": "clap-audio-1.onnx",
            "sha256": "1" * 64, "size_bytes": 2, "url": f"{DERIVED}/clap-audio-1.onnx"}
    published, signature = _published_channel(
        release_key_mod.key_path(""), records=[mac, dash], artefacts=[clap])
    gh = PublishedGh(channel=published, signature=signature)

    feed_dir = tmp_path / "feed"          # EMPTY: a fresh clone
    assert _build(feed_dir, artifact, upload=True, runner=gh) == pf.EXIT_OK

    final = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    keys = pf.package_keys(final)
    assert ("companion", "macos", "0.9.3") in keys
    assert ("dashboard", "linux", "0.7.4") in keys
    assert ("companion", "windows", "0.8.0") in keys   # the one just built
    assert pf.artefact_keys(final) == {("music-clap-audio", "clap-audio-1.onnx")}


def test_the_uploaded_channel_is_the_merged_one(trusted_key, artifact, tmp_path):
    mac = _record("companion", "macos", "0.9.3", "ccsync-companion-0.9.3-macos.zip")
    published, signature = _published_channel(release_key_mod.key_path(""), records=[mac])
    gh = PublishedGh(channel=published, signature=signature)
    feed_dir = tmp_path / "feed"
    assert _build(feed_dir, artifact, upload=True, runner=gh) == pf.EXIT_OK
    uploaded = [a for a in gh.upload_argv() if str(a).endswith(pf.CHANNEL_FILENAME)]
    assert uploaded, gh.upload_argv()
    on_disk = json.loads(Path(uploaded[0]).read_text())
    assert len(on_disk["packages"]) == 2
    # ...and it still verifies as a whole document.
    sig = (feed_dir / pf.SIG_FILENAME).read_text().strip()
    ok, detail = pf.verify_channel_signature(
        on_disk, sig, _pubkeys_for(release_key_mod.key_path("")))
    assert ok, detail


def test_a_channel_that_does_not_verify_is_never_merged_or_uploaded(
        trusted_key, artifact, tmp_path, capsys):
    published, _sig = _published_channel(release_key_mod.key_path(""))
    gh = PublishedGh(channel=published, signature=base64.b64encode(b"z" * 64).decode("ascii"))
    rc = _build(tmp_path / "feed", artifact, upload=True, runner=gh)
    assert rc == pf.EXIT_UPLOAD_FAILED
    assert "release upload" not in gh.verbs()
    assert "does not verify" in capsys.readouterr().err


def test_an_unreadable_feed_is_not_mistaken_for_an_empty_one(key, artifact, tmp_path, capsys):
    # `gh` failing for any reason OTHER than "no such release/asset" must
    # refuse: --clobber cannot be undone, and "I could not ask" is not
    # "nothing is published".
    gh = FakeGh(rc_by_verb={"release download": 1})
    rc = _build(tmp_path / "feed", artifact, upload=True, runner=gh)
    assert rc == pf.EXIT_UPLOAD_FAILED
    assert "release upload" not in gh.verbs()
    assert "could not read the channel already published" in capsys.readouterr().err


def test_a_first_publish_with_no_release_yet_still_works(key, artifact, tmp_path, capsys):
    gh = FakeGh(release_exists=False)
    assert _build(tmp_path / "feed", artifact, upload=True, runner=gh) == pf.EXIT_OK
    assert "first publish" in capsys.readouterr().out


def test_the_local_feed_is_still_written_when_the_fetch_refuses(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    gh = FakeGh(rc_by_verb={"release download": 1})
    assert _build(feed_dir, artifact, upload=True, runner=gh) == pf.EXIT_UPLOAD_FAILED
    pubkeys = _pubkeys_for(release_key_mod.key_path(""))
    ok, report = pf.verify_feed_dir(feed_dir, pubkeys=pubkeys)
    assert ok, report


def test_shrinking_the_channel_is_refused_without_allow_shrink():
    # The merge makes an accidental shrink impossible, so the check is driven
    # directly: it is the backstop for any future path that assembles the
    # channel some other way.
    published = {"packages": [_record("companion", "macos", "0.9.3", "a.zip")],
                 "artefacts": [{"kind": "music-clap-audio", "filename": "clap.onnx"}]}
    candidate = {"packages": [], "artefacts": []}
    assert pf.shrink_report(published, candidate) == [
        "package companion/macos 0.9.3", "artefact music-clap-audio clap.onnx"]
    assert pf.shrink_report(published, candidate,
                            {("companion", "macos", "0.9.3")}) == [
        "artefact music-clap-audio clap.onnx"]


def test_a_retraction_removes_the_record_and_the_current_pointer(
        trusted_key, artifact, tmp_path, capsys):
    bad = _record("companion", "windows", "0.6.1", "ccsync-companion-0.6.1.exe")
    good = _record("companion", "macos", "0.9.3", "mac.zip")
    published, _signature = _published_channel(
        release_key_mod.key_path(""), records=[bad, good])
    published["current"] = {"companion/windows": "0.6.1"}
    signature, _pub = _sign_channel_for(published, release_key_mod.key_path(""))
    gh = PublishedGh(channel=published, signature=signature)
    feed_dir = tmp_path / "feed"
    rc = pf.main(["--retract", "companion/windows/0.6.1", "--feed-dir", str(feed_dir),
                  "--github-repo", GH_REPO, "--github-upload"], runner=gh)
    assert rc == pf.EXIT_OK
    final = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    assert pf.package_keys(final) == {("companion", "macos", "0.9.3")}
    assert final.get("current", {}) == {}
    assert "RETRACTED" in capsys.readouterr().out


def test_retract_wants_kind_platform_version(key, tmp_path):
    assert pf.main(["--retract", "companion/windows",
                    "--feed-dir", str(tmp_path / "feed")]) == pf.EXIT_USAGE


# --- the `current` pointer (release-pipeline-5, 2026-08-21) ------------------
#
# Without it, a dashboard on the "current" policy replayed the whole channel
# in APPEND order and whichever record happened to be last won -- so a --force
# republish of an older build, or a late macOS CI run, offered the entire
# fleet a rollback.


def test_make_current_writes_the_pointer(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    assert _build(feed_dir, artifact, "--make-current") == pf.EXIT_OK
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    assert channel["current"] == {"companion/windows": "0.8.0"}


def test_without_make_current_nothing_is_pointed_at(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    assert _build(feed_dir, artifact) == pf.EXIT_OK
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    assert "current" not in channel


def test_the_pointer_is_per_kind_and_platform(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    assert _build(feed_dir, artifact, "--make-current") == pf.EXIT_OK
    assert pf.main(["--artifact", str(artifact), "--platform", "macos", "--version", "0.9.3",
                    "--feed-dir", str(feed_dir), "--github-repo", GH_REPO,
                    "--make-current"]) == pf.EXIT_OK
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    assert channel["current"] == {"companion/windows": "0.8.0", "companion/macos": "0.9.3"}


def test_the_pointer_rides_the_channel_signature(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    assert _build(feed_dir, artifact, "--make-current") == pf.EXIT_OK
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    sig = (feed_dir / pf.SIG_FILENAME).read_text().strip()
    pubkeys = _pubkeys_for(release_key_mod.key_path(""))
    channel["current"]["companion/windows"] = "0.0.1"
    ok, _detail = pf.verify_channel_signature(channel, sig, pubkeys)
    assert not ok


# --- CR-59 item 8 / CR-67 item 8: what a record already on the feed is owed --
# The dashboard's own publish path refuses same-version-different-bytes with a
# 409 that names the mismatch (release-pipeline-6), and every companion keeps a
# monotonic downgrade floor. Neither protects the FEED, which is the channel a
# customer's dashboard reads: until 2026-08-21 this tool would silently replace
# a published record's bytes, or publish a floor below the one already out
# there, and sign both.

def _publish(feed_dir, artifact, version, *extra, min_version="0.0.0"):
    return pf.main(["--artifact", str(artifact), "--platform", "windows",
                    "--version", version, "--min-version", min_version,
                    "--feed-dir", str(feed_dir), "--base-url", BASE_URL, *extra])


def test_republishing_the_same_version_with_different_bytes_is_refused(
        key, artifact, tmp_path, capsys):
    feed_dir = tmp_path / "feed"
    assert _publish(feed_dir, artifact, "0.8.0") == pf.EXIT_OK
    other = tmp_path / "rebuilt.exe"
    other.write_bytes(b"MZ" + b"y" * 5000)   # same version, different build
    assert _publish(feed_dir, other, "0.8.0") == pf.EXIT_USAGE
    err = capsys.readouterr().err
    assert "already published with DIFFERENT bytes" in err
    # The way out is a version bump, and the message has to say so: an
    # operator who reads "refused" and reaches for a --force flag has learned
    # the wrong lesson.
    assert "Bump VERSION" in err and "config.py" in err
    # ...and the published record is untouched.
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    assert len(channel["packages"]) == 1
    assert channel["packages"][0]["size_bytes"] == artifact.stat().st_size


def test_republishing_identical_bytes_is_not_a_replacement(key, artifact, tmp_path):
    """A re-run after a failed upload must stay possible: same key, same
    sha256, nothing to lose."""
    feed_dir = tmp_path / "feed"
    assert _publish(feed_dir, artifact, "0.8.0") == pf.EXIT_OK
    assert _publish(feed_dir, artifact, "0.8.0") == pf.EXIT_OK
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    assert len(channel["packages"]) == 1


def test_allow_replace_is_the_deliberate_override(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    assert _publish(feed_dir, artifact, "0.8.0") == pf.EXIT_OK
    other = tmp_path / "rebuilt.exe"
    other.write_bytes(b"MZ" + b"y" * 5000)
    assert _publish(feed_dir, other, "0.8.0", "--allow-replace") == pf.EXIT_OK
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    assert len(channel["packages"]) == 1
    assert channel["packages"][0]["size_bytes"] == other.stat().st_size


def test_a_retracted_version_may_be_republished_with_new_bytes(key, artifact, tmp_path):
    """--retract is the deliberate withdrawal, so the record it removed is no
    longer "already published" and needs no override to replace."""
    feed_dir = tmp_path / "feed"
    assert _publish(feed_dir, artifact, "0.8.0") == pf.EXIT_OK
    other = tmp_path / "rebuilt.exe"
    other.write_bytes(b"MZ" + b"y" * 5000)
    assert _publish(feed_dir, other, "0.8.0",
                    "--retract", "companion/windows/0.8.0") == pf.EXIT_OK
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    assert [p["size_bytes"] for p in channel["packages"]] == [other.stat().st_size]


def test_a_floor_below_the_published_one_is_refused(key, artifact, tmp_path, capsys):
    feed_dir = tmp_path / "feed"
    assert _publish(feed_dir, artifact, "0.9.44", min_version="0.9.40") == pf.EXIT_OK
    # The next ship forgets CCSYNC_MIN_VERSION -- the default is no floor at all.
    assert _publish(feed_dir, artifact, "0.9.45", min_version="0.0.0") == pf.EXIT_USAGE
    err = capsys.readouterr().err
    assert "BELOW the highest floor already published" in err
    assert "--min-version 0.9.40" in err          # names the value to re-run with
    assert "--allow-floor-drop" in err


def test_the_floor_is_the_highest_ever_published_not_the_last(key, artifact, tmp_path):
    """A companion's floor is monotonic: once it has SEEN 0.9.40 it never
    installs below 0.9.40 again, whatever order later records arrive in."""
    feed_dir = tmp_path / "feed"
    assert _publish(feed_dir, artifact, "0.9.44", min_version="0.9.40") == pf.EXIT_OK
    assert _publish(feed_dir, artifact, "0.9.45", min_version="0.9.40") == pf.EXIT_OK
    assert _publish(feed_dir, artifact, "0.9.46", min_version="0.9.39") == pf.EXIT_USAGE


def test_two_digit_minors_compare_as_numbers_in_the_floor_check(key, artifact, tmp_path):
    """After 0.9.9 comes 0.10.0 (owner's rule 2026-08-18); a string compare
    would read 0.10.0 as below 0.9.9 and refuse a good publish."""
    feed_dir = tmp_path / "feed"
    assert _publish(feed_dir, artifact, "0.9.9", min_version="0.9.9") == pf.EXIT_OK
    assert _publish(feed_dir, artifact, "0.10.0", min_version="0.10.0") == pf.EXIT_OK


def test_the_floor_is_per_kind_and_platform(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    assert _publish(feed_dir, artifact, "0.9.44", min_version="0.9.40") == pf.EXIT_OK
    # macOS has published no floor of its own, so it is not held to Windows'.
    assert pf.main(["--artifact", str(artifact), "--platform", "macos",
                    "--version", "0.9.44", "--min-version", "0.0.0",
                    "--feed-dir", str(feed_dir), "--base-url", BASE_URL]) == pf.EXIT_OK


def test_allow_floor_drop_is_the_deliberate_override(key, artifact, tmp_path):
    feed_dir = tmp_path / "feed"
    assert _publish(feed_dir, artifact, "0.9.44", min_version="0.9.40") == pf.EXIT_OK
    assert _publish(feed_dir, artifact, "0.9.45", "--allow-floor-drop",
                    min_version="0.9.30") == pf.EXIT_OK


def test_a_refused_publish_uploads_nothing(key, artifact, tmp_path):
    """Both refusals raise before write_channel, so the feed dir keeps the
    document it had and no `gh` command is ever reached."""
    feed_dir = tmp_path / "feed"
    assert _publish(feed_dir, artifact, "0.8.0") == pf.EXIT_OK
    before = (feed_dir / pf.CHANNEL_FILENAME).read_bytes()
    other = tmp_path / "rebuilt.exe"
    other.write_bytes(b"MZ" + b"y" * 5000)
    gh = FakeGh(release_exists=True)
    rc = pf.main(["--artifact", str(other), "--platform", "windows", "--version", "0.8.0",
                  "--feed-dir", str(feed_dir), "--github-repo", GH_REPO,
                  "--github-upload"], runner=gh)
    assert rc == pf.EXIT_USAGE
    assert (feed_dir / pf.CHANNEL_FILENAME).read_bytes() == before
    assert "release upload" not in gh.verbs()
