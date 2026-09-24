"""CR-317 (2026-09-24): an original that is not here, playing its proxy that
IS here, is not a clip "Resolve cannot find".

Seen live on ruskin's DESKTOP-LQQ41TC ("Reproductive Rights Fight", timeline
"Ordered V7"): the fleet grid said "57 clips Resolve cannot find". Every one
was a camera or YouTube original on P:\\Projects\\... that a remote editor by
design never holds (lane B brings proxies only, lane C excludes video), and
every one had its proxy attached, playing, and on disk at the NAS size. The
watcher asked only whether the ORIGINAL existed; audit F4's proxy-aware
exemption was the b-roll archive's alone. The rule now: MISSING is counted
and listed only when neither the original nor a usable proxy is here.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from ccsync_companion import broll_standins, canon, paths, proxy_relink
from ccsync_companion import watcher as watcher_mod
from ccsync_companion.paths import MISSING, classify_path
from ccsync_companion.watcher import TimelineWatcher

from conftest import make_timeline_item

CAMERA = r"P:\Projects\Reproductive Rights Fight\Footage\A004\A004C001.braw"
CAMERA_PROXY = r"P:\Projects\Reproductive Rights Fight\Footage\A004\Proxy\A004C001.mov"
YOUTUBE = r"P:\Projects\Reproductive Rights Fight\Youtube\interview.mp4"
YOUTUBE_PROXY = r"P:\Projects\Reproductive Rights Fight\Youtube\Proxy\interview.mov"
NOTHING = r"P:\Projects\Reproductive Rights Fight\Footage\A005\A005C002.braw"
ARCHIVE_CLIP = r"P:\Assets\B-roll Archive\cc\ff5\clip.mov"


@pytest.fixture(autouse=True)
def _fresh_state(tmp_path):
    paths.clear_prefix_cache()
    proxy_relink.reset_refusals()
    led = broll_standins.configure(tmp_path / "state" / "broll_standins.json")
    yield led
    broll_standins.configure(broll_standins.default_state_path())
    proxy_relink.reset_refusals()
    paths.clear_prefix_cache()


@pytest.fixture
def mapped(tmp_path, monkeypatch):
    """A healthy P:\\ -> tmp_path mapping whose canonical clips are absent.

    The seam test_watcher_broll_archive.py uses: on Windows classify_path
    probes the literal "P:\\..." string (always absent here), on posix the
    local twin under tmp_path.
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
                        else os.path.realpath(p))
    return tmp_path


def _place(tmp_path, canonical: str) -> Path:
    local = Path(canon.canonical_to_local(canonical, str(tmp_path), "P:\\"))
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(b"proxy bytes")
    return local


def _watcher(tmp_path, *items, **kw):
    return TimelineWatcher(
        local_root=str(tmp_path),
        canonical_prefix="P:\\",
        get_timeline_items=lambda: {"ok": True, "message": "",
                                    "items": list(items), "project_name": ""},
        **kw,
    )


def test_an_original_that_is_absent_with_its_proxy_present_is_not_missing(
        tmp_path, mapped):
    """The pair is the contract, as with the archive: the classification is
    untouched (the original really is not here) and the count is zero."""
    _place(tmp_path, CAMERA_PROXY)

    assert classify_path(CAMERA, str(tmp_path), "P:\\") == MISSING

    watcher = _watcher(tmp_path, make_timeline_item(CAMERA))
    summary = watcher.poll_once()

    assert summary["missing"] == 0
    assert watcher.missing_clips() == []
    assert watcher.last_counts["missing"] == 0


def test_an_original_and_proxy_both_absent_is_still_missing_and_listed(
        tmp_path, mapped):
    """Nothing to play is exactly what the count exists for."""
    watcher = _watcher(tmp_path, make_timeline_item(NOTHING, clip_name="A005C002"))

    summary = watcher.poll_once()

    assert summary["missing"] == 1
    assert watcher.missing_clips() == [{"name": "A005C002", "path": NOTHING}]


def test_ruskins_timeline_shape_lists_only_the_clip_with_nothing_to_play(
        tmp_path, mapped):
    """Camera and YouTube originals with proxies, plus one with neither: the
    one that is actually broken is the only one left, where before it was
    one line among fifty-seven that were fine."""
    _place(tmp_path, CAMERA_PROXY)
    _place(tmp_path, YOUTUBE_PROXY)
    watcher = _watcher(
        tmp_path,
        make_timeline_item(CAMERA),
        # Video and audio of the same clip: asked once, counted once.
        make_timeline_item(CAMERA, track_type="audio"),
        make_timeline_item(YOUTUBE),
        make_timeline_item(NOTHING),
    )

    summary = watcher.poll_once()

    assert summary["missing"] == 1
    assert [c["path"] for c in watcher.missing_clips()] == [NOTHING]


def test_a_proxy_resolve_refused_does_not_count_as_one(tmp_path, mapped):
    """The relink pass remembers a proxy Resolve would not attach (a
    timecode or frame-count mismatch: ruskin's short A004 proxies on
    2026-09-17). Such a clip is Media Offline with its proxy on disk, and it
    must stay in the count."""
    _place(tmp_path, CAMERA_PROXY)
    proxy_relink.note_refusal({"file_path": CAMERA, "new_proxy": CAMERA_PROXY})

    watcher = _watcher(tmp_path, make_timeline_item(CAMERA))

    assert watcher.poll_once()["missing"] == 1
    assert [c["path"] for c in watcher.missing_clips()] == [CAMERA]


def test_the_archive_is_still_judged_by_its_own_rule(tmp_path, mapped):
    """The proxy rule does not look at the b-roll archive: there
    `Proxy/<stem>.mp4` is the browser preview, and the archive's own
    exemption (stand-ins included) decides. An archive clip that rule counts
    stays counted even with a file in its Proxy folder."""
    _place(tmp_path, r"P:\Assets\B-roll Archive\cc\ff5\Proxy\clip.mp4")
    watcher = _watcher(tmp_path, make_timeline_item(ARCHIVE_CLIP),
                       archive_exempt_fn=lambda _path: False)

    assert watcher.poll_once()["missing"] == 1


def test_the_archive_rule_is_unchanged_for_an_archive_clip_with_a_proxy(
        tmp_path, mapped):
    _place(tmp_path, r"P:\Assets\B-roll Archive\cc\ff5\Proxy\clip.mov")
    watcher = _watcher(tmp_path, make_timeline_item(ARCHIVE_CLIP))

    assert watcher.poll_once()["missing"] == 0


def test_a_proxy_question_that_raises_counts_the_clip(tmp_path, mapped):
    """A question that cannot be answered must not remove evidence."""
    def boom(_path):
        raise RuntimeError("no")

    _place(tmp_path, CAMERA_PROXY)
    watcher = _watcher(tmp_path, make_timeline_item(CAMERA), proxy_held_fn=boom)

    assert watcher.poll_once()["missing"] == 1


def test_the_proxy_answer_is_remembered_and_expires(monkeypatch):
    """Same TTL as the archive answer (comp-resolve-7): a 3 s poll asks the
    filesystem once a minute, and a proxy landing or being deleted still
    shows up while the editor remembers doing it."""
    asked: list = []
    w = watcher_mod.TimelineWatcher.__new__(watcher_mod.TimelineWatcher)
    w.local_root = "P:\\"
    w.canonical_prefix = "P:\\"
    w._proxy_held_fn = lambda path: asked.append(path) or True
    w._proxy_memo = {}
    now = [1000.0]
    monkeypatch.setattr(watcher_mod.time, "monotonic", lambda: now[0])

    for _ in range(5):                       # five polls, five fresh caches
        assert w._proxy_held(CAMERA, {}) is True
    assert len(asked) == 1

    now[0] += watcher_mod.EXEMPT_TTL_SECONDS + 1
    w._proxy_held(CAMERA, {})
    assert len(asked) == 2


def test_the_log_line_says_what_is_true(tmp_path, mapped, caplog):
    """The MISSING line said "not under local_root/prefix", the opposite of
    the class (MISSING means the prefix DOES resolve and the file is absent),
    and never said whether a proxy was here. A clip playing its proxy logs
    nothing, like an archive clip."""
    _place(tmp_path, CAMERA_PROXY)
    watcher = _watcher(tmp_path, make_timeline_item(CAMERA),
                       make_timeline_item(NOTHING))

    with caplog.at_level(logging.DEBUG, logger="ccsync.watcher"):
        watcher.poll_once()

    messages = [r.getMessage() for r in caplog.records]
    assert ("clip's original is not on this computer and no usable proxy "
            f"for it is either: {NOTHING}") in messages
    assert not any(CAMERA in m for m in messages)
    assert not any("not under local_root" in m for m in messages)
