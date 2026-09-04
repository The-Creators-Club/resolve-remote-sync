"""youtube_import tests: the state machine, with no Resolve and no threads.

Every collaborator that touches the world is a constructor seam, so these
tests drive the importer one tick and one scan at a time -- `tick()` and
`scan_once()` exist for exactly this. What is NOT faked is the filesystem:
the settle rules and the sidecar/temp-file exclusions are the parts that have
to agree with a real term folder, so they run against real tmp_path trees in
test_proxy_gen.py's style.

The properties under most of this file: nothing half-delivered is ever handed
to Resolve, no clip is imported twice, and `status()` -- which the tray and
the reporter call on their own threads -- touches nothing at all.
"""

from __future__ import annotations

import os
import time

import pytest
from conftest import write_project_marker

from ccsync_companion import youtube_import
from ccsync_companion.youtube_import import YoutubeImporter

# Comfortably older than the 120 s settle window.
SETTLED = 3600.0

PROJECT = "Energy Transition"
PROJECT_REL = "Projects/2026/FF5/Energy Transition"
TERM = "algal reef"


class _Clock:
    """A monotonic clock the test moves by hand -- the scan cadence is the
    only thing that reads it, and no test may wait 60 real seconds for it."""

    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Import:
    """Stands in for resolve_bridge.import_files_to_bin_path -- the ONE seam
    every Resolve call goes through. Records what it was asked to do and
    answers in the bridge's shape."""

    def __init__(self):
        self.calls: list[dict] = []
        self.fail_paths: set[str] = set()
        self.already: set[str] = set()
        # A whole-batch refusal (the bridge's "project changed" /
        # "Resolve isn't running"), which blames no individual file.
        self.refusal: dict | None = None

    def __call__(self, paths, bin_segments, expected_project_name="",
                 path_alias_fn=None, canonical_fn=None):
        self.calls.append({
            "paths": list(paths),
            "bin": tuple(bin_segments),
            "project": expected_project_name,
            "alias_fn": path_alias_fn,
            "canonical_fn": canonical_fn,
        })
        if self.refusal is not None:
            return dict(self.refusal, imported=[], skipped_existing=[], failed=[])
        failed = [p for p in paths if p in self.fail_paths]
        skipped = [p for p in paths if p in self.already and p not in failed]
        imported = [p for p in paths if p not in failed and p not in skipped]
        return {
            "ok": not failed,
            "message": "" if not failed else f"Resolve refused {len(failed)} file(s)",
            "imported": imported,
            "skipped_existing": skipped,
            "failed": failed,
        }


class _CountingIO:
    """listdir/stat/isdir behind a counter -- how "status() does no I/O" is
    asserted without trusting a docstring."""

    def __init__(self):
        self.calls = 0

    def listdir(self, path):
        self.calls += 1
        return os.listdir(path)

    def stat(self, path):
        self.calls += 1
        return os.stat(path)

    def isdir(self, path):
        self.calls += 1
        return os.path.isdir(path)


def _cfg(tmp_path, **overrides):
    cfg = {
        "local_root": str(tmp_path),
        "youtube_import_enabled": True,
        "youtube_import_scan_interval": 60,
        "youtube_import_min_age_seconds": 120,
        "youtube_import_batch_limit": 20,
        "youtube_import_max_failures": 3,
    }
    cfg.update(overrides)
    return cfg


def _make(tmp_path, cfg=None, **kwargs):
    kwargs.setdefault("get_resolve_project", lambda: PROJECT)
    kwargs.setdefault("get_project_roots", lambda: ({PROJECT.lower(): PROJECT_REL}, "live"))
    kwargs.setdefault("import_fn", _Import())
    kwargs.setdefault("clock", _Clock())
    return YoutubeImporter(cfg or _cfg(tmp_path), **kwargs)


def _project_dir(tmp_path):
    return os.path.join(tmp_path, *PROJECT_REL.split("/"))


def _drop(tmp_path, names=("a.mp4",), term=TERM, age=SETTLED, size=1000):
    """Put files in <project>/Youtube/<term>/, aged past the settle window."""
    folder = os.path.join(_project_dir(tmp_path), "Youtube", term)
    os.makedirs(folder, exist_ok=True)
    paths = []
    for name in names:
        path = os.path.join(folder, name)
        with open(path, "wb") as handle:
            handle.write(b"x" * size)
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        paths.append(path)
    return paths


def _drop_loose(tmp_path, names=("one off.mp4",), age=SETTLED, size=1000):
    """Put files in <project>/Youtube/ ITSELF -- where a URL download lands,
    because a pasted link has no search term to sort it under."""
    return _drop(tmp_path, names, term="", age=age, size=size)


def _settled(importer, tmp_path):
    """Two scans, which is what "size-stable across two consecutive scans"
    means. Returns the state of the SECOND one -- the one that imports."""
    importer.scan_once(PROJECT, _project_dir(tmp_path))
    return importer.scan_once(PROJECT, _project_dir(tmp_path))


# -- the gate, in order -------------------------------------------------------


def test_the_gate_says_disabled_when_the_feature_is_off(tmp_path):
    importer = _make(tmp_path, _cfg(tmp_path, youtube_import_enabled=False))
    assert importer._gate(PROJECT) == youtube_import.STATE_DISABLED


def test_the_gate_says_drive_absent_before_anything_else(tmp_path):
    """An unplugged SSD outranks every other answer: the folder we would scan
    is not there, and saying "paused" would send the editor to the wrong menu
    item."""
    importer = _make(tmp_path, root_present_fn=lambda: False, paused_fn=lambda: True)
    assert importer._gate(PROJECT) == youtube_import.STATE_DRIVE_ABSENT


def test_pause_gates_importing(tmp_path):
    """Pause means "stop moving my media around", and an editor who pressed
    it does not expect clips to keep appearing in their bins."""
    importer = _make(tmp_path, paused_fn=lambda: True)
    assert importer._gate(PROJECT) == youtube_import.STATE_PAUSED


def test_no_project_open_is_resolve_closed(tmp_path):
    importer = _make(tmp_path, get_resolve_project=lambda: None)
    assert importer.tick() == youtube_import.STATE_RESOLVE_CLOSED


def test_a_disconnected_bridge_is_resolve_closed(tmp_path):
    """resolve_bridge.session_state() saying "not connected" stands the
    importer down entirely -- the watcher's own poll is what rediscovers
    Resolve, and hammering the scripting API behind it helps nobody."""
    importer = _make(
        tmp_path,
        session_state_fn=lambda: {"connected": False, "ever_connected": True,
                                  "reason": "DaVinci Resolve is not running"},
    )
    assert importer._gate(PROJECT) == youtube_import.STATE_RESOLVE_CLOSED


def test_a_bridge_that_has_not_been_asked_yet_is_not_closed(tmp_path):
    """`connected` is None until something has actually asked Resolve. "Not
    checked yet" reading as "closed" would make the first tick after start()
    always publish resolve-closed."""
    _drop(tmp_path)
    importer = _make(
        tmp_path,
        session_state_fn=lambda: {"connected": None, "ever_connected": False, "reason": ""},
    )
    assert importer._gate(PROJECT) == youtube_import.STATE_IDLE


def test_an_unmappable_project_says_so(tmp_path):
    """No dashboard mapping and nothing in the tree that matches: filing
    another project's clips into this one is far worse than doing nothing."""
    importer = _make(tmp_path, get_project_roots=lambda: ({}, "live"))
    assert importer.tick() == youtube_import.STATE_NO_PROJECT_MATCH


def test_the_gate_order_is_disabled_then_drive_then_pause_then_resolve(tmp_path):
    """All four true at once: the first answer wins, in the order an editor
    would ask the questions."""
    importer = _make(
        tmp_path, _cfg(tmp_path, youtube_import_enabled=False),
        root_present_fn=lambda: False, paused_fn=lambda: True,
        get_resolve_project=lambda: None,
    )
    assert importer._gate(None) == youtube_import.STATE_DISABLED
    importer.enabled = True
    assert importer._gate(None) == youtube_import.STATE_DRIVE_ABSENT
    importer._root_present_fn = lambda: True
    assert importer._gate(None) == youtube_import.STATE_PAUSED
    importer._paused_fn = lambda: False
    assert importer._gate(None) == youtube_import.STATE_RESOLVE_CLOSED


# -- what counts as a downloaded clip -----------------------------------------


def test_only_video_files_are_imported(tmp_path):
    """The downloader writes sidecars next to every video -- `.credits.json`
    (which the Resolve credits script reads) and `manifest.json`. Importing
    those as media is nonsense; the whitelist is what keeps them out."""
    _drop(tmp_path, ["a.mp4", "b.mov", "c.mkv", "d.webm", "e.m4v",
                     "a.credits.json", "manifest.json", "notes.txt"])
    importer = _make(tmp_path)

    _settled(importer, tmp_path)

    names = sorted(os.path.basename(p) for p in importer._import_fn.calls[0]["paths"])
    assert names == ["a.mp4", "b.mov", "c.mkv", "d.webm", "e.m4v"]


@pytest.mark.parametrize("name", [
    # rclone's in-flight name, and the same file mid-Syncthing.
    "clip.mp4.partial",
    "clip.mp4.tmp",
    "clip.mp4.lock",
    # Syncthing's own temp spelling, and macOS's resource fork -- both
    # dotfiles, both real things in a synced folder.
    ".syncthing.clip.mp4.tmp",
    "._clip.mp4",
    ".hidden.mp4",
])
def test_half_delivered_files_are_never_imported(tmp_path, name):
    _drop(tmp_path, [name])
    importer = _make(tmp_path)

    state = _settled(importer, tmp_path)

    assert importer._import_fn.calls == []
    assert state == youtube_import.STATE_NOTHING_TO_DO


@pytest.mark.parametrize("name", [
    # yt-dlp's video-only and audio-only streams, before the merge. Both are
    # real names from a 1080p AVC download: f137 is the video, f140 the audio.
    "Cruz Yanez - Aerial View Rio Grande LNG [SAQBbd1Rxmo].f137.mp4",
    "Cruz Yanez - Aerial View Rio Grande LNG [SAQBbd1Rxmo].f299.webm",
    # ...and the merge target, mid-write.
    "Cruz Yanez - Aerial View Rio Grande LNG [SAQBbd1Rxmo].temp.mp4",
    # YT-6 (resilience sweep 2026-08-28): the conversion's half-written output
    # and the pre-conversion original that swap_in could not delete because
    # Resolve had the file open. Both end `.mp4`, both were imported as EXTRA
    # clips -- two clips per download in a shared project, one of them
    # undecodable or truncated, and nothing anywhere said why.
    "Cruz Yanez - Aerial View Rio Grande LNG [SAQBbd1Rxmo].editready.mp4",
    "Cruz Yanez - Aerial View Rio Grande LNG [SAQBbd1Rxmo].original.mp4",
])
def test_yt_dlp_intermediates_are_never_imported(tmp_path, name):
    """COMP-BROLL-4. Before companion 0.8.0 no yt-dlp ever ran on an editor
    rig -- lane B delivered finished files only -- but the local download
    executor runs it INSIDE `<project>/Youtube/<term>/`, which is the folder
    this scan walks. `[id].f137.mp4` has extension `.mp4` and passed the
    whitelist; its mtime stops advancing the instant the video stream is done,
    so it settles minutes before the audio and the merge are finished, gets
    imported under its canonical `P:\\` spelling, and is then DELETED by
    yt-dlp. What is left is a Media Offline clip in a shared project pointing
    at a path that exists on no machine in the fleet -- and decision 2 (no
    database) means nothing ever reaps it."""
    _drop(tmp_path, [name])
    importer = _make(tmp_path)

    state = _settled(importer, tmp_path)

    assert importer._import_fn.calls == []
    assert state == youtube_import.STATE_NOTHING_TO_DO


def test_the_merged_clip_itself_is_still_imported(tmp_path):
    """The rule is anchored on the stem, so the deliverable -- whose stem ends
    in `[id]` -- is untouched, and so is a title that merely mentions a format
    number."""
    _drop(tmp_path, [
        "Cruz Yanez - Aerial View Rio Grande LNG [SAQBbd1Rxmo].mp4",
        "Some Channel - Inside the f137 format [aaaaaaaaaaa].mp4",
        # and the fallback deliverable a locked conversion leaves (YT-6): the
        # marker is in front of the bracket precisely so this file is still
        # read as the clip
        "Cruz Yanez - Aerial View Rio Grande LNG.converted [bbbbbbbbbbb].mp4",
    ])
    importer = _make(tmp_path)

    _settled(importer, tmp_path)

    names = sorted(os.path.basename(p) for p in importer._import_fn.calls[0]["paths"])
    assert names == [
        "Cruz Yanez - Aerial View Rio Grande LNG [SAQBbd1Rxmo].mp4",
        "Cruz Yanez - Aerial View Rio Grande LNG.converted [bbbbbbbbbbb].mp4",
        "Some Channel - Inside the f137 format [aaaaaaaaaaa].mp4",
    ]


def test_a_freshly_written_file_waits_for_the_settle_window(tmp_path):
    """A file whose mtime is seconds old is still arriving, and half a video
    imports as an offline clip."""
    _drop(tmp_path, ["a.mp4"], age=5)
    importer = _make(tmp_path)

    state = _settled(importer, tmp_path)

    assert importer._import_fn.calls == []
    assert state == youtube_import.STATE_WAITING_SETTLE
    assert importer.status()["pending"] == 1


def test_a_file_that_grew_since_the_last_look_waits(tmp_path):
    """The mtime alone is not enough: a copy that preserves the source's
    timestamp is born looking old, so the size has to hold still too."""
    (path,) = _drop(tmp_path, ["a.mp4"], size=1000)
    importer = _make(tmp_path)

    importer.scan_once(PROJECT, _project_dir(tmp_path))
    with open(path, "ab") as handle:
        handle.write(b"y" * 500)
    stamp = time.time() - SETTLED
    os.utime(path, (stamp, stamp))
    state = importer.scan_once(PROJECT, _project_dir(tmp_path))

    assert importer._import_fn.calls == []
    assert state == youtube_import.STATE_WAITING_SETTLE
    # ...and once it stops growing, it goes.
    assert importer.scan_once(PROJECT, _project_dir(tmp_path)) == \
        youtube_import.STATE_NOTHING_TO_DO
    assert importer._import_fn.calls[0]["paths"] == [path]


def test_the_first_sighting_only_seeds_the_settle_check(tmp_path):
    _drop(tmp_path, ["a.mp4"])
    importer = _make(tmp_path)

    assert importer.scan_once(PROJECT, _project_dir(tmp_path)) == \
        youtube_import.STATE_WAITING_SETTLE
    assert importer._import_fn.calls == []


def test_a_settled_clip_is_filed_into_its_term_bin(tmp_path):
    (path,) = _drop(tmp_path, ["a.mp4"])
    importer = _make(tmp_path)

    state = _settled(importer, tmp_path)

    call = importer._import_fn.calls[0]
    assert call["paths"] == [path]
    assert call["bin"] == ("Youtube", TERM)
    # The project the SCAN was for, so the bridge can refuse if the editor
    # opened a different one in between.
    assert call["project"] == PROJECT
    assert state == youtube_import.STATE_NOTHING_TO_DO
    status = importer.status()
    assert status["imported_session"] == 1
    assert status["failed_session"] == 0
    assert status["last_bin"] == f"Youtube/{TERM}"
    assert status["last_import_at"]


def test_the_import_call_carries_a_canonical_alias_fold(tmp_path):
    """The bridge dedupes on File Path, and a clip the editor hand-imported
    through the P: drive sits in the pool under the CANONICAL spelling while
    this importer hands the bridge local_root paths. The alias fn is what
    folds those together -- without it, the first scan of a Youtube folder
    that predates this feature duplicates every clip already filed by hand."""
    from ccsync_companion import canon

    (path,) = _drop(tmp_path, ["a.mp4"])
    importer = _make(tmp_path, cfg=_cfg(tmp_path, canonical_prefix="P:\\"))

    _settled(importer, tmp_path)

    alias = importer._import_fn.calls[0]["alias_fn"]
    assert alias is not None
    canonical = "P:\\" + os.path.relpath(path, str(tmp_path)).replace(os.sep, "\\")
    translated = alias(canonical)
    assert translated is not None
    assert canon.norm(translated) == canon.norm(path)
    # A pool path that is not on the canonical prefix has no second spelling.
    assert alias("D:\\Somewhere\\else.mp4") is None


# -- clips loose in Youtube/ itself (the paste-a-URL case, 0.7.1) -------------
#
# A URL carries no search term, so the downloader writes those clips straight
# into `<project>/Youtube/`. The scan skipped every non-directory there, which
# made them invisible to Resolve forever. This is a widening by exactly one
# case: the root ITSELF, still not a recursive walk.


def test_a_loose_clip_in_the_youtube_root_is_filed_into_the_youtube_bin(tmp_path):
    (path,) = _drop_loose(tmp_path, ["one off [abc123].mp4"])
    importer = _make(tmp_path)

    state = _settled(importer, tmp_path)

    call = importer._import_fn.calls[0]
    assert call["paths"] == [path]
    assert call["bin"] == ("Youtube",), "Master/Youtube itself, not a sub-bin"
    assert call["project"] == PROJECT
    assert state == youtube_import.STATE_NOTHING_TO_DO
    status = importer.status()
    assert status["imported_session"] == 1
    assert status["last_bin"] == "Youtube"


def test_a_loose_clip_never_produces_an_empty_or_untitled_bin(tmp_path):
    """("Youtube", "") would come back from resolve_bridge._safe_bin_name as
    Master/Youtube/Untitled -- a bin nobody named, holding the one clip the
    editor is watching for."""
    _drop_loose(tmp_path, ["a.mp4"])
    importer = _make(tmp_path)

    _settled(importer, tmp_path)

    segments = importer._import_fn.calls[0]["bin"]
    assert "" not in segments and None not in segments
    assert "Untitled" not in segments
    assert importer.status()["last_bin"] == "Youtube"


def test_a_loose_clip_and_a_term_folder_are_both_handled_in_one_pass(tmp_path):
    """The term folders keep behaving exactly as they did -- this adds a
    second place to look, it does not move the first one."""
    (loose,) = _drop_loose(tmp_path, ["one off.mp4"])
    (in_term,) = _drop(tmp_path, ["a.mp4"], term=TERM)
    importer = _make(tmp_path)

    state = _settled(importer, tmp_path)

    calls = importer._import_fn.calls
    # The root first: a one-off URL download is the one an editor is waiting
    # on, and it must not queue behind every term folder's batch.
    assert [call["bin"] for call in calls] == [("Youtube",), ("Youtube", TERM)]
    assert calls[0]["paths"] == [loose]
    assert calls[1]["paths"] == [in_term]
    assert state == youtube_import.STATE_NOTHING_TO_DO
    assert importer.status()["imported_session"] == 2


def test_a_still_arriving_loose_clip_waits_like_any_other(tmp_path):
    """Half a video imports as an offline clip. The settle rules are the term
    folders' rules, unchanged -- not a second set for the root."""
    _drop_loose(tmp_path, ["a.mp4"], age=5)
    importer = _make(tmp_path)

    state = _settled(importer, tmp_path)

    assert importer._import_fn.calls == []
    assert state == youtube_import.STATE_WAITING_SETTLE
    assert importer.status()["pending"] == 1


def test_a_loose_file_that_grew_since_the_last_look_waits(tmp_path):
    (path,) = _drop_loose(tmp_path, ["a.mp4"], size=1000)
    importer = _make(tmp_path)

    importer.scan_once(PROJECT, _project_dir(tmp_path))
    with open(path, "ab") as handle:
        handle.write(b"y" * 500)
    stamp = time.time() - SETTLED
    os.utime(path, (stamp, stamp))

    assert importer.scan_once(PROJECT, _project_dir(tmp_path)) == \
        youtube_import.STATE_WAITING_SETTLE
    assert importer._import_fn.calls == []
    assert importer.scan_once(PROJECT, _project_dir(tmp_path)) == \
        youtube_import.STATE_NOTHING_TO_DO
    assert importer._import_fn.calls[0]["paths"] == [path]


@pytest.mark.parametrize("name", [
    "manifest.json",
    "a.credits.json",
    "notes.txt",
    "clip.mp4.partial",
    "clip.mp4.tmp",
    ".syncthing.clip.mp4.tmp",
    "._clip.mp4",
])
def test_a_non_clip_in_the_youtube_root_is_still_ignored(tmp_path, name):
    """The root gets the SAME filter, not a looser one: the downloader writes
    its sidecars and its half-delivered files there too."""
    _drop_loose(tmp_path, [name])
    importer = _make(tmp_path)

    state = _settled(importer, tmp_path)

    assert importer._import_fn.calls == []
    assert state == youtube_import.STATE_NOTHING_TO_DO


def test_a_hidden_folder_in_the_root_is_left_alone(tmp_path):
    """`.ccsync-trash` and friends are legitimately in the tree, and nothing
    in them is a download."""
    _drop(tmp_path, ["a.mp4"], term=".ccsync-trash")
    importer = _make(tmp_path)

    state = _settled(importer, tmp_path)

    assert importer._import_fn.calls == []
    assert state == youtube_import.STATE_NOTHING_TO_DO


def test_a_term_folder_named_like_a_clip_is_not_imported_as_one(tmp_path):
    """Both loops read the root now, so a directory called "reef.mp4" passes
    the name filter -- and handing a directory to ImportMedia is not a thing
    to find out about in Resolve."""
    (inside,) = _drop(tmp_path, ["a.mp4"], term="reef.mp4")
    importer = _make(tmp_path)

    _settled(importer, tmp_path)

    calls = importer._import_fn.calls
    assert [call["bin"] for call in calls] == [("Youtube", "reef.mp4")]
    assert calls[0]["paths"] == [inside]


def test_the_widening_is_the_root_only_and_not_a_deeper_walk(tmp_path):
    """The docstring's rule still holds: one level of term folder, plus the
    root itself. Anything the editor has filed deeper stays theirs."""
    folder = os.path.join(_project_dir(tmp_path), "Youtube", TERM, "extras")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "deep.mp4")
    with open(path, "wb") as handle:
        handle.write(b"x" * 100)
    stamp = time.time() - SETTLED
    os.utime(path, (stamp, stamp))
    importer = _make(tmp_path)

    state = _settled(importer, tmp_path)

    assert importer._import_fn.calls == []
    assert state == youtube_import.STATE_NOTHING_TO_DO


def test_the_batch_cap_and_failure_cap_hold_for_loose_clips_too(tmp_path):
    """The per-path bookkeeping is keyed by path, not by term, and the batch
    cap applies to the rootless group like any other."""
    paths = _drop_loose(tmp_path, ["a.mp4", "b.mp4", "c.mp4"])
    importer = _make(tmp_path, _cfg(tmp_path, youtube_import_batch_limit=2))
    importer._import_fn.fail_paths = {paths[0]}

    state = _settled(importer, tmp_path)

    assert importer._import_fn.calls[0]["paths"] == paths[:2]
    assert state == youtube_import.STATE_IMPORTING, "one clip is still waiting"
    assert importer._failures[paths[0]] == 1

    # Three refusals and that file is left alone -- while the others still go.
    importer.scan_once(PROJECT, _project_dir(tmp_path))
    importer.scan_once(PROJECT, _project_dir(tmp_path))
    assert importer._is_capped(paths[0]) is True
    offered = [p for call in importer._import_fn.calls for p in call["paths"]]
    assert offered.count(paths[0]) == 3
    assert importer.status()["failed_session"] == 3


def test_a_loose_clip_is_never_offered_twice_in_one_session(tmp_path):
    (path,) = _drop_loose(tmp_path, ["a.mp4"])
    importer = _make(tmp_path)

    _settled(importer, tmp_path)
    importer.scan_once(PROJECT, _project_dir(tmp_path))

    assert len(importer._import_fn.calls) == 1
    assert path in importer._done


def test_a_disabled_importer_reports_disabled_before_any_tick(tmp_path):
    """start() returns without a thread when disabled, so no tick will ever
    publish a state. The constructor has to seed the truthful one, or the
    tray and the dashboard report would read "idle" about a feature that is
    switched off."""
    importer = _make(tmp_path, cfg=_cfg(tmp_path, youtube_import_enabled=False))

    assert importer.status()["state"] == youtube_import.STATE_DISABLED
    importer.start()
    assert importer._thread is None
    assert importer.status()["state"] == youtube_import.STATE_DISABLED


def test_a_clip_is_never_offered_twice_in_one_session(tmp_path):
    _drop(tmp_path, ["a.mp4"])
    importer = _make(tmp_path)
    _settled(importer, tmp_path)

    importer.scan_once(PROJECT, _project_dir(tmp_path))

    assert len(importer._import_fn.calls) == 1


def test_a_clip_already_in_the_pool_is_remembered_as_done(tmp_path):
    """The bridge answers "skipped_existing" for a clip the editor already
    has (in any bin). Asking again every minute for the rest of the day is
    pure noise."""
    (path,) = _drop(tmp_path, ["a.mp4"])
    importer = _make(tmp_path)
    importer._import_fn.already = {path}

    _settled(importer, tmp_path)
    importer.scan_once(PROJECT, _project_dir(tmp_path))

    assert len(importer._import_fn.calls) == 1
    assert importer.status()["imported_session"] == 0


def test_a_deleted_file_falls_out_of_the_settle_bookkeeping(tmp_path):
    (path,) = _drop(tmp_path, ["a.mp4"])
    importer = _make(tmp_path)
    importer.scan_once(PROJECT, _project_dir(tmp_path))
    assert path in importer._seen

    os.remove(path)
    importer.scan_once(PROJECT, _project_dir(tmp_path))

    assert importer._seen == {}


def test_a_project_with_no_youtube_folder_has_nothing_to_do(tmp_path):
    os.makedirs(_project_dir(tmp_path), exist_ok=True)
    importer = _make(tmp_path)

    assert importer.tick() == youtube_import.STATE_NOTHING_TO_DO
    assert importer._import_fn.calls == []


# -- which folder on disk is this project? ------------------------------------


def test_the_dashboard_mapping_wins(tmp_path):
    _drop(tmp_path)
    importer = _make(tmp_path)

    assert importer._resolve_project_dir(PROJECT) == _project_dir(tmp_path)


def test_the_mapping_is_matched_case_insensitively(tmp_path):
    """project_roots is keyed on the lowercased Resolve project name
    (selection._parse_project_roots), and Resolve's own casing is whatever
    the editor typed."""
    _drop(tmp_path)
    importer = _make(tmp_path)

    assert importer._resolve_project_dir("ENERGY TRANSITION") == _project_dir(tmp_path)


def test_the_local_path_is_built_with_the_hosts_own_separator(tmp_path):
    """`Projects/<rel>` joined with os.path.join, never a `P:\\...` string:
    the tree is at local_root on this machine, which on a Mac has no drive
    namespace at all."""
    importer = _make(tmp_path)

    assert importer._local_dir(PROJECT_REL) == os.path.join(
        str(tmp_path), "Projects", "2026", "FF5", "Energy Transition")


def test_the_token_match_is_the_fallback_when_the_dashboard_has_nothing(tmp_path):
    """Unmanaged mode, or a project the admin never mapped: fixer's
    token-overlap match is the same guess the popup fixer makes."""
    _drop(tmp_path)
    write_project_marker(_project_dir(tmp_path))
    importer = _make(tmp_path, get_project_roots=None)

    assert importer._resolve_project_dir(PROJECT) == _project_dir(tmp_path)


def test_the_token_match_is_refused_without_a_youtube_folder(tmp_path):
    """The guess is only ever acted on when `<guess>/Youtube` exists -- a
    fact, rather than a hunch, and the difference between filing clips in the
    right project and filing them in a same-named wrong one."""
    write_project_marker(_project_dir(tmp_path))
    importer = _make(tmp_path, get_project_roots=lambda: ({}, "unreachable"))

    assert importer._resolve_project_dir(PROJECT) is None


def test_the_mapping_is_memoised_for_a_scan_interval(tmp_path):
    """The fallback walks the Projects tree looking for markers. Doing that
    every 15 s tick is a tree walk a minute for nothing."""
    _drop(tmp_path)
    write_project_marker(_project_dir(tmp_path))
    roots_calls: list[int] = []
    importer = _make(
        tmp_path,
        get_project_roots=lambda: roots_calls.append(1) or ({}, "live"),
    )

    for _ in range(4):
        importer._resolve_project_dir(PROJECT)

    assert len(roots_calls) == 1


def test_opening_another_project_rescans_at_once(tmp_path):
    """The editor who just opened a project is the one waiting for its clips
    -- a 60 s wait to find out is 60 s of them wondering if it works."""
    _drop(tmp_path)
    clock = _Clock()
    open_project = [PROJECT]
    importer = _make(tmp_path, clock=clock, get_resolve_project=lambda: open_project[0])
    importer.tick()
    importer.tick()          # nothing due yet, and nothing scanned
    scans = len(importer._seen)
    assert scans and importer._import_fn.calls == []

    open_project[0] = "Something Else"
    importer.tick()          # no mapping for that one
    open_project[0] = PROJECT
    state = importer.tick()  # ...and back, which must scan immediately

    assert state != youtube_import.STATE_NO_PROJECT_MATCH
    assert importer._import_fn.calls, "a project change must not wait for the cadence"


# -- batching -----------------------------------------------------------------


def test_each_term_folder_is_one_call_and_the_remainder_waits(tmp_path):
    """The batch cap is what bounds how long the Resolve lock is held -- the
    watcher polls every 3 s behind it -- so a big drop arrives over a few
    cycles instead of freezing the tray for one long one."""
    first = _drop(tmp_path, ["a.mp4", "b.mp4", "c.mp4"], term="algal reef")
    second = _drop(tmp_path, ["d.mp4"], term="taiwan drone")
    importer = _make(tmp_path, _cfg(tmp_path, youtube_import_batch_limit=2))

    state = _settled(importer, tmp_path)

    calls = importer._import_fn.calls
    assert [call["bin"] for call in calls] == [
        ("Youtube", "algal reef"), ("Youtube", "taiwan drone")]
    assert calls[0]["paths"] == first[:2]
    assert calls[1]["paths"] == second
    assert state == youtube_import.STATE_IMPORTING, "there is still work to do"

    # ...and the remainder goes on the very next TICK, not the next scan.
    assert importer._scan_due() is True
    importer.scan_once(PROJECT, _project_dir(tmp_path))
    assert importer._import_fn.calls[2]["paths"] == first[2:]
    assert importer._scan_due() is False


def test_a_whole_batch_refusal_stops_the_cycle(tmp_path):
    """"You opened a different project" gets the same answer for every
    remaining term folder, and importing them anyway would file clips into
    whatever is open NOW."""
    _drop(tmp_path, ["a.mp4"], term="algal reef")
    _drop(tmp_path, ["b.mp4"], term="taiwan drone")
    importer = _make(tmp_path)
    importer._import_fn.refusal = {"ok": False, "message": "project changed"}

    state = _settled(importer, tmp_path)

    assert len(importer._import_fn.calls) == 1
    assert state == youtube_import.STATE_IMPORTING
    assert importer.status()["last_error"] == "project changed"
    # Nothing was blamed on the files: they are retried on the next tick.
    assert importer.status()["failed_session"] == 0
    assert importer._failures == {}


# -- failures -----------------------------------------------------------------


def test_a_file_resolve_keeps_refusing_is_left_alone_after_three_goes(tmp_path):
    """In-memory only, exactly like proxy_gen's counters: a refusal
    remembered on disk turns one bad evening into a file that never imports
    again."""
    (path,) = _drop(tmp_path, ["a.mp4"])
    importer = _make(tmp_path)
    importer._import_fn.fail_paths = {path}

    _settled(importer, tmp_path)
    for _ in range(4):
        importer.scan_once(PROJECT, _project_dir(tmp_path))

    assert len(importer._import_fn.calls) == 3, "three attempts, then silence"
    assert importer.status()["failed_session"] == 3
    assert importer.status()["last_error"]


def test_an_import_seam_that_raises_costs_one_cycle_and_no_more(tmp_path):
    """Belt and braces on top of the bridge's own never-raise contract."""
    _drop(tmp_path)

    def _boom(paths, bin_segments, expected_project_name=""):
        raise RuntimeError("fusionscript fell over")

    importer = _make(tmp_path, import_fn=_boom)

    state = _settled(importer, tmp_path)

    assert state == youtube_import.STATE_IMPORTING
    assert importer.status()["last_error"]


def test_one_bad_tick_never_ends_the_worker(tmp_path, caplog):
    """The loop's contract: this feature's whole value is that it keeps
    trying, and the next tick recomputes everything from the disk anyway."""
    def _explode():
        raise RuntimeError("no Resolve here")

    importer = _make(tmp_path, get_resolve_project=_explode)
    with caplog.at_level("DEBUG", logger="ccsync.youtube_import"):
        assert importer.tick() == youtube_import.STATE_RESOLVE_CLOSED


# -- the zero-I/O reader ------------------------------------------------------


def test_status_touches_no_filesystem(tmp_path):
    """The rule proxy_gen.gap() documents (proxy_gen.py:510-516): the tray
    calls this on its refresh thread, where a getter that walked anything is
    how the right-click freeze of 2026-07-26 happened. Asserted through the
    seams, not by inspection."""
    _drop(tmp_path)
    io = _CountingIO()
    importer = _make(tmp_path, listdir_fn=io.listdir, stat_fn=io.stat, isdir_fn=io.isdir)
    _settled(importer, tmp_path)
    assert io.calls > 0, "the scan really does use these seams"

    io.calls = 0
    for _ in range(5):
        importer.status()

    assert io.calls == 0


def test_status_reports_the_published_state(tmp_path):
    importer = _make(tmp_path, _cfg(tmp_path, youtube_import_enabled=False))

    importer.tick()

    assert importer.status() == {
        "state": youtube_import.STATE_DISABLED,
        "pending": 0,
        "imported_session": 0,
        "failed_session": 0,
        "last_import_at": None,
        "last_bin": "",
        "last_error": "",
        # CYT-3: the two fields the tray, the Settings window and
        # sync_guard.youtube_import render. `reason` is the state as a
        # sentence, and it is what nobody had before this.
        "given_up": 0,
        "reason": youtube_import.state_reason(youtube_import.STATE_DISABLED),
    }


def test_the_state_between_scans_is_the_last_scans_answer(tmp_path):
    """Publishing "idle" for 45 s while an import is queued would make the
    tray lie about what the importer is doing."""
    _drop(tmp_path, ["a.mp4", "b.mp4"], age=5)
    clock = _Clock()
    importer = _make(tmp_path, clock=clock)

    importer.tick()
    assert importer.status()["state"] == youtube_import.STATE_WAITING_SETTLE
    assert importer.tick() == youtube_import.STATE_WAITING_SETTLE   # not due yet
    assert importer.status()["state"] == youtube_import.STATE_WAITING_SETTLE


# -- lifecycle ----------------------------------------------------------------


def test_start_does_nothing_at_all_when_disabled(tmp_path):
    importer = _make(tmp_path, _cfg(tmp_path, youtube_import_enabled=False))

    importer.start()

    assert importer._thread is None
    importer.stop()
    importer.join(timeout=0.1)


def test_the_worker_starts_and_stops(tmp_path):
    importer = _make(tmp_path)

    importer.start()
    try:
        assert importer._thread is not None and importer._thread.is_alive()
    finally:
        importer.stop()
        importer.join(timeout=5.0)
    assert not importer._thread.is_alive()


def test_a_hand_edited_interval_never_raises_at_construction(tmp_path):
    """CompanionApp builds this in __init__, where a raise means the windowed
    exe exits with no tray and no log line (AUDIT_2 CORE-M4's family)."""
    importer = _make(
        tmp_path,
        _cfg(tmp_path, youtube_import_scan_interval="1m",
             youtube_import_batch_limit="lots", youtube_import_max_failures=None),
    )

    assert importer.scan_interval == 60
    assert importer.batch_limit == 20
    assert importer.max_failures == 3


# -- the Proxy store is not a term folder, and imports store canonically ------


def test_a_root_level_proxy_dir_is_not_a_term_folder(tmp_path):
    """`Youtube/Proxy/` holds the generated previews for pasted-URL root
    clips (and lane B delivers it to editors). Treating it as a term folder
    imported 540p previews into a bin literally named "Proxy"."""
    _drop(tmp_path, ["real.mp4"])
    _drop(tmp_path, ["preview.mp4"], term="Proxy")

    importer = _make(tmp_path)
    _settled(importer, tmp_path)

    imported = [p for call in importer._import_fn.calls for p in call["paths"]]
    assert any(p.endswith("real.mp4") for p in imported)
    assert not any(p.endswith("preview.mp4") for p in imported)
    assert all(call["bin"] != ("Youtube", "Proxy") for call in importer._import_fn.calls)


def test_the_import_is_handed_a_canonical_spelling_fn(tmp_path):
    r"""The 2026-08-12 Energy Transition incident: imports stored local_root
    spellings (`F:\Creators_Club\...`) in the SHARED project, which are
    offline on every other machine. The importer must hand the bridge a
    canonical_fn that answers the `P:\` spelling to store instead."""
    paths = _drop(tmp_path, ["a.mp4"])
    importer = _make(tmp_path, _cfg(tmp_path, canonical_prefix="P:\\"))
    _settled(importer, tmp_path)

    call = importer._import_fn.calls[0]
    canonical_fn = call["canonical_fn"]
    assert canonical_fn is not None
    spelled = canonical_fn(paths[0])
    assert spelled is not None
    assert spelled.startswith("P:\\")
    assert spelled == "P:\\" + os.path.relpath(paths[0], str(tmp_path)).replace("/", "\\")


def test_the_canonical_spelling_fn_is_harmless_with_no_prefix_configured(tmp_path):
    paths = _drop(tmp_path, ["a.mp4"])
    importer = _make(tmp_path)  # _cfg sets no canonical_prefix
    _settled(importer, tmp_path)

    canonical_fn = importer._import_fn.calls[0]["canonical_fn"]
    # No prefix -> the physical path comes back unchanged (the bridge's
    # norm-equality check then makes the ReplaceClip a no-op).
    assert canonical_fn(paths[0]) == paths[0]


# -- CYT-3: the state as a SENTENCE -------------------------------------------
#
# The importer computed a full verdict (state, pending, failed_session,
# last_error, last_bin) and it reached nobody: the tray and the Settings
# window contain no reference to this module, and the dashboard declared the
# section, validated it and then read nothing. "The download worked, the clips
# are in Youtube/<term>/, they are not in my media pool" was invisible on both
# ends.


def test_a_state_nothing_is_wrong_in_has_no_reason(tmp_path):
    importer = _make(tmp_path)
    assert youtube_import.state_reason(youtube_import.STATE_IDLE) == ""
    assert youtube_import.state_reason(youtube_import.STATE_IMPORTING) == ""
    assert importer.status()["reason"] == ""


def test_the_gate_states_an_editor_can_act_on_get_a_sentence(tmp_path):
    for state in (youtube_import.STATE_DISABLED, youtube_import.STATE_DRIVE_ABSENT,
                  youtube_import.STATE_PAUSED, youtube_import.STATE_RESOLVE_CLOSED,
                  youtube_import.STATE_NO_PROJECT_MATCH):
        assert youtube_import.state_reason(state), f"{state} says nothing"
    waiting = youtube_import.state_reason(
        youtube_import.STATE_RESOLVE_CLOSED, pending=8)
    assert waiting.startswith("8 downloaded clips are waiting.")


def test_the_give_up_is_counted_and_it_wins_the_sentence(tmp_path):
    """A clip dropped after youtube_import_max_failures tries is the one
    shape here that stays broken with the gate wide open, and it had one
    WARNING in a rotating log behind it."""
    (path,) = _drop(tmp_path, ["a.mp4"])
    importer = _make(tmp_path)
    importer._import_fn.fail_paths = {path}

    _settled(importer, tmp_path)
    for _ in range(4):
        importer.scan_once(PROJECT, _project_dir(tmp_path))

    status = importer.status()
    assert status["given_up"] == 1, "counted once, at the transition"
    assert status["reason"].startswith("1 downloaded clip could not be filed")
    assert "tries them again the next time it starts" in status["reason"]
