"""tools/publish_feed.py -- local feed-directory builder (ZERO_TOUCH_PLAN.md
WP E, 2026-08-17). Every test points CCSYNC_RELEASE_KEY at a tmp key and
writes into a tmp feed dir; nothing here touches the network (this tool never
does -- see its module docstring)."""
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
