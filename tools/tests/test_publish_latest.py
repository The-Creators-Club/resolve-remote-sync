"""tools/publish_latest.py -- the command that actually ships a CI build.

Three defects from the 2026-08-21 hunt are pinned here:

  release-pipeline-1  "already published" was read from the LOCAL, gitignored
                      feed/ dir, so on any machine without this rig's copy the
                      answer was "nothing" -- about a feed carrying the whole
                      fleet's history.
  release-pipeline-4  the installer (kind=onboard) was never publishable
                      through the feed at all, so a feed-only customer's
                      [ INSTALLER ] page was empty.
  release-pipeline-7  the newest green run of ANY branch was signed and
                      published, with no version-monotonicity check.

Nothing here touches the network or needs `gh`: every subprocess goes through
publish_latest.run, which the tests replace.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "companion" / "src"))

import publish_latest as pl  # noqa: E402
import publish_feed as pf  # noqa: E402


class TestSources:
    def test_the_installer_is_publishable_through_the_feed(self):
        kinds = {(s["kind"], s["platform"]) for s in pl.SOURCES}
        assert ("onboard", "windows") in kinds
        assert ("onboard", "macos") in kinds

    def test_every_source_names_the_manifest_it_reads(self):
        for src in pl.SOURCES:
            assert src["manifest"].endswith(".json"), src
        onboard = [s for s in pl.SOURCES if s["kind"] == "onboard"]
        assert all(s["manifest"] == "ccsync-onboard.json" for s in onboard)


class TestVersionOrdering:
    def test_two_digit_minors_compare_as_numbers(self):
        # After 0.9.9 comes 0.10.0, never 1.0 (owner's rule 2026-08-18).
        assert pl.version_tuple("0.10.0") > pl.version_tuple("0.9.9")
        assert pl.version_tuple("0.9.41") > pl.version_tuple("0.9.4")

    def test_newest_published_is_by_version_not_by_position(self):
        channel = {"packages": [
            {"kind": "companion", "platform": "windows", "version": "0.9.41"},
            {"kind": "companion", "platform": "windows", "version": "0.9.4"},
            {"kind": "companion", "platform": "macos", "version": "0.10.0"},
        ]}
        assert pl.newest_published(channel, "companion", "windows") == "0.9.41"
        assert pl.newest_published(channel, "companion", "macos") == "0.10.0"
        assert pl.newest_published(channel, "onboard", "windows") == ""


class TestRunSelection:
    def test_only_runs_from_the_release_branch_are_considered(self, monkeypatch):
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return 0, json.dumps([{"databaseId": 1, "headSha": "a" * 40,
                                   "displayTitle": "x", "createdAt": "now"}]), ""

        monkeypatch.setattr(pl, "run", fake_run)
        info = pl.latest_green_run("release-windows.yml")
        assert info["databaseId"] == 1
        assert "--branch" in seen["cmd"]
        assert seen["cmd"][seen["cmd"].index("--branch") + 1] == pl.RELEASE_BRANCH

    def test_a_commit_not_on_main_is_not_trusted(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return 1, "", "not an ancestor"

        monkeypatch.setattr(pl, "run", fake_run)
        assert pl.commit_is_on_main("b" * 40) is False
        assert "merge-base" in calls[0] and "--is-ancestor" in calls[0]

    def test_an_ancestor_is_trusted(self, monkeypatch):
        monkeypatch.setattr(pl, "run", lambda cmd, **kw: (0, "", ""))
        assert pl.commit_is_on_main("b" * 40) is True


class TestPublishedChannelComesFromTheFeedNotTheDisk:
    def test_the_published_channel_is_fetched_not_read_from_feed_dir(self, monkeypatch):
        asked = {}

        def fake_fetch(repo, tag, *, runner, dest, out):
            asked["repo"] = repo
            channel = {"packages": [{"kind": "companion", "platform": "macos",
                                     "version": "0.9.3"}]}
            return channel, "sig", "ok"

        monkeypatch.setattr(pf, "fetch_published_channel", fake_fetch)
        monkeypatch.setattr(pf, "verify_channel_signature", lambda *a, **k: (True, "ok"))
        channel = pl.published_channel()
        assert asked["repo"] == pl.FEED_REPO
        assert pl.newest_published(channel, "companion", "macos") == "0.9.3"

    def test_an_empty_feed_is_a_first_run_not_an_error(self, monkeypatch):
        monkeypatch.setattr(pf, "fetch_published_channel",
                            lambda *a, **k: (None, "", "absent"))
        assert pl.published_channel() == {}

    def test_a_feed_that_cannot_be_read_is_fatal(self, monkeypatch):
        # "I could not ask" must never be reported as "nothing is published":
        # that is what makes a republish (or a missed rollback) possible.
        monkeypatch.setattr(pf, "fetch_published_channel",
                            lambda *a, **k: (None, "", "gh exploded"))
        with pytest.raises(SystemExit):
            pl.published_channel()

    def test_a_channel_that_does_not_verify_is_fatal(self, monkeypatch):
        monkeypatch.setattr(pf, "fetch_published_channel",
                            lambda *a, **k: ({"packages": []}, "sig", "ok"))
        monkeypatch.setattr(pf, "verify_channel_signature",
                            lambda *a, **k: (False, "no key verifies this"))
        with pytest.raises(SystemExit):
            pl.published_channel()


class TestFindManifest:
    def test_the_manifest_name_is_per_source(self, tmp_path):
        (tmp_path / "companion" / "dist").mkdir(parents=True)
        (tmp_path / "onboarding" / "dist").mkdir(parents=True)
        (tmp_path / "companion" / "dist" / "ccsync-release.json").write_text("{}")
        (tmp_path / "onboarding" / "dist" / "ccsync-onboard.json").write_text("{}")
        assert pl.find_manifest(tmp_path, "ccsync-onboard.json").name == "ccsync-onboard.json"
        assert pl.find_manifest(tmp_path, "ccsync-release.json").name == "ccsync-release.json"
        assert pl.find_manifest(tmp_path, "nothing.json") is None
