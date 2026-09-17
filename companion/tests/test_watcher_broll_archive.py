"""An offline b-roll original with a proxy is not a problem to be counted.

Audit F4, docs/BROLL_PROXY_TIERS_PLAN.md section 6 (2026-09-17). Every
proxy-only b-roll insert leaves a clip whose File Path is `P:\\Assets\\B-roll
Archive\\...` and whose file is not on this machine. classify_path calls that
MISSING and always will -- it IS missing -- but since RES-12/RES-19 the count
and up to 50 paths ride every report as sync_guard.resolve_health and the
tray prints "N missing on disk". A number that goes up every time an editor
uses b-roll is a number nobody reads.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ccsync_companion import broll_standins, canon, paths
from ccsync_companion.paths import MISSING, classify_path
from ccsync_companion.watcher import TimelineWatcher

from conftest import make_timeline_item

ARCHIVE_CLIP = r"P:\Assets\B-roll Archive\cc\ff5\clip.mov"
PROJECT_CLIP = r"P:\Projects\Energy Transition\a.braw"


@pytest.fixture(autouse=True)
def _fresh_prefix_cache():
    paths.clear_prefix_cache()
    yield
    paths.clear_prefix_cache()


@pytest.fixture(autouse=True)
def ledger(tmp_path):
    led = broll_standins.configure(tmp_path / "state" / "broll_standins.json")
    yield led
    broll_standins.configure(broll_standins.default_state_path())


@pytest.fixture
def mapped(tmp_path, monkeypatch):
    """A healthy P:\\ -> tmp_path mapping whose canonical clips are absent.

    Same seam as test_watcher.py's `downloaded`: on Windows classify_path
    probes the literal "P:\\..." string, on posix it probes the local twin.
    """
    real_exists = os.path.exists

    def fake_exists(p):
        p = str(p)
        if p.upper().startswith("P:\\"):
            return False
        return real_exists(p)

    monkeypatch.setattr(paths.os.path, "exists", fake_exists)
    monkeypatch.setattr(paths.os.path, "realpath",
                        lambda p: str(tmp_path) + "\\" if str(p).upper().startswith("P:")
                        else real_exists and os.path.realpath(p))
    return tmp_path


def _local(tmp_path, canonical):
    return Path(canon.canonical_to_local(canonical, str(tmp_path), "P:\\"))


def _watcher(tmp_path, *items):
    return TimelineWatcher(
        local_root=str(tmp_path),
        canonical_prefix="P:\\",
        get_timeline_items=lambda: {"ok": True, "message": "",
                                    "items": list(items), "project_name": ""},
    )


def test_an_archive_original_with_a_proxy_is_missing_but_counted_nowhere(
        tmp_path, mapped):
    """Both halves in one test, because the pair IS the contract: the
    classification is unchanged and the count is zero."""
    proxy = _local(tmp_path, r"P:\Assets\B-roll Archive\cc\ff5\Proxy\clip.mov")
    proxy.parent.mkdir(parents=True, exist_ok=True)
    proxy.write_bytes(b"the editing proxy")

    assert classify_path(ARCHIVE_CLIP, str(tmp_path), "P:\\") == MISSING

    watcher = _watcher(tmp_path, make_timeline_item(ARCHIVE_CLIP))
    summary = watcher.poll_once()

    assert summary["missing"] == 0
    assert watcher.missing_clips() == []


def test_a_ledgered_stand_in_is_counted_nowhere_either(tmp_path, mapped):
    """The stand-in case: the file at that path is the preview's bytes, so
    the clip is playing and the editor has nothing to fix."""
    standin = _local(tmp_path, ARCHIVE_CLIP)
    standin.parent.mkdir(parents=True, exist_ok=True)
    standin.write_bytes(b"preview bytes")
    broll_standins.record(standin, share="broll", rel_path="cc/ff5/clip.mov")

    watcher = TimelineWatcher(
        local_root=str(tmp_path), canonical_prefix="P:\\",
        get_timeline_items=lambda: {"ok": True, "message": "", "project_name": "",
                                    "items": [make_timeline_item(ARCHIVE_CLIP)]},
        # The ledger is keyed by the LOCAL path this machine wrote; the
        # clip's stored path is the canonical one, which is the translation
        # the default exemption does through find_proxy_on_disk's twin.
        archive_exempt_fn=lambda path: broll_standins.is_standin(
            canon.canonical_to_local(path, str(tmp_path), "P:\\") or path),
    )
    summary = watcher.poll_once()

    assert summary["missing"] == 0


def test_an_archive_original_with_no_proxy_is_still_counted(tmp_path, mapped):
    """Nothing to play: that IS a problem, and the editor should see it."""
    watcher = _watcher(tmp_path, make_timeline_item(ARCHIVE_CLIP))

    summary = watcher.poll_once()

    assert summary["missing"] == 1
    assert [entry["path"] for entry in watcher.missing_clips()] == [ARCHIVE_CLIP]


def test_project_footage_is_counted_exactly_as_before(tmp_path, mapped):
    """The exemption is the ARCHIVE's alone: a project clip whose media has
    not synced down is the thing the count was added for."""
    proxy = _local(tmp_path, r"P:\Projects\Energy Transition\Proxy\a.mov")
    proxy.parent.mkdir(parents=True, exist_ok=True)
    proxy.write_bytes(b"proxy")

    watcher = _watcher(tmp_path, make_timeline_item(PROJECT_CLIP))
    summary = watcher.poll_once()

    assert summary["missing"] == 1


def test_an_exemption_that_raises_counts_the_clip(tmp_path, mapped):
    """A question that cannot be answered must not remove evidence."""
    def boom(_path):
        raise RuntimeError("no")

    watcher = TimelineWatcher(
        local_root=str(tmp_path), canonical_prefix="P:\\",
        get_timeline_items=lambda: {"ok": True, "message": "", "project_name": "",
                                    "items": [make_timeline_item(ARCHIVE_CLIP)]},
        archive_exempt_fn=boom,
    )

    assert watcher.poll_once()["missing"] == 1
