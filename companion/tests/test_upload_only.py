"""The upload-only tick, companion side (docs/UPLOAD_ONLY_TICK.md).

A selection item carrying `sync_mode: "upload_only"` runs lane A alone:
no lane B, no borrowed-folder runs, no lane C turn, and it is not one of
the folders lane C expects. An unknown mode is not synced at all.
"""
from __future__ import annotations

from test_sequencer import (FakeAdmin, FakeSelectionClient, _build, _item,
                            _wait_until)

from ccsync_companion.sync.sequencer import STATE_RUNNING


def _up_item(slug, rel_path, position):
    item = _item(slug, rel_path, position)
    item["sync_mode"] = "upload_only"
    return item


def _pass_done(seq):
    return _wait_until(lambda: seq.state in ("between_passes", "no_selection"))


def test_an_upload_only_project_runs_lane_a_and_nothing_else():
    selection = FakeSelectionClient([
        _up_item("up", "2026/FF5/Backed Up Shoot", 1),
        _item("full", "2026/FF5/Energy Transition", 2),
    ])
    admin = FakeAdmin()
    admin.pending = {"up": {"offeredBy": {"SERVER": {}}},
                     "full": {"offeredBy": {"SERVER": {}}}}
    seq, lane_a, lane_b, events = _build(selection, admin)
    seq.start()
    assert _wait_until(lambda: lane_a.calls.count("Projects/2026/FF5/Energy Transition") >= 1)
    assert _pass_done(seq)
    seq.stop()

    assert "Projects/2026/FF5/Backed Up Shoot" in lane_a.calls
    assert "Projects/2026/FF5/Backed Up Shoot" not in lane_b.calls
    assert "Projects/2026/FF5/Energy Transition" in lane_b.calls
    # No lane C turn for it: never accepted, never paused or released.
    touched = {e[1] for e in events if e[0] in ("accept", "pause", "ignores", "get_ignores")}
    assert "up" not in touched
    assert "full" in touched


def test_lane_c_never_expects_an_upload_only_folder():
    selection = FakeSelectionClient([
        _up_item("up", "2026/FF5/Backed Up Shoot", 1),
        _item("full", "2026/FF5/Energy Transition", 2),
    ])
    seq, *_ = _build(selection, FakeAdmin())
    seq._update_known_selection(selection.selection)
    assert seq.expected_folder_slugs() == ["full"]
    assert seq.upload_only_slugs() == {"up"}
    # ...but lane A's watchdog and the manifest still know the project.
    assert "2026/FF5/Backed Up Shoot" in seq.known_rels()


def test_a_mode_flip_counts_as_a_selection_change():
    """full -> upload-only must stop lane B on the next pass without waiting
    out the idle backoff, and the reverse must start it."""
    selection = FakeSelectionClient([_item("p", "2026/FF5/Show", 1)])
    seq, *_ = _build(selection, FakeAdmin())
    seq._update_known_selection(selection.selection)
    woke = []
    seq._wake_up_now = lambda: woke.append(True)
    seq._update_known_selection([_up_item("p", "2026/FF5/Show", 1)])
    assert woke and seq.expected_folder_slugs() == []
    seq._update_known_selection([_item("p", "2026/FF5/Show", 1)])
    assert seq.expected_folder_slugs() == ["p"]


def test_an_unknown_mode_is_not_synced_at_all():
    """Fail closed: a mode this build has never heard of is neither guessed
    as full (which could start a download the tick meant to prevent) nor as
    upload-only (which could silently stop a project syncing)."""
    item = _item("odd", "2026/FF5/Odd", 1)
    item["sync_mode"] = "download_only"
    selection = FakeSelectionClient([item, _item("ok", "2026/FF5/Ok", 2)])
    seq, lane_a, lane_b, _events = _build(selection, FakeAdmin())
    seq.start()
    assert _wait_until(lambda: "Projects/2026/FF5/Ok" in lane_a.calls)
    assert _pass_done(seq)
    seq.stop()
    assert "Projects/2026/FF5/Odd" not in lane_a.calls
    assert "Projects/2026/FF5/Odd" not in lane_b.calls
    assert seq.expected_folder_slugs() == ["ok"]


def test_a_blank_or_missing_mode_is_full():
    """What every item meant before the key existed, and what a cached
    selection.json from an older companion still carries."""
    blank = _item("blank", "2026/FF5/Blank", 1)
    blank["sync_mode"] = ""
    selection = FakeSelectionClient([blank, _item("none", "2026/FF5/None", 2)])
    seq, *_ = _build(selection, FakeAdmin())
    seq._update_known_selection(selection.selection)
    assert seq.expected_folder_slugs() == ["blank", "none"]
    assert seq.upload_only_slugs() == set()


def test_the_status_line_says_uploading_for_an_upload_only_project():
    selection = FakeSelectionClient([_up_item("up", "2026/FF5/Backed Up Shoot", 1)])
    seq, *_ = _build(selection, FakeAdmin())
    seq._update_known_selection(selection.selection)
    with seq._lock:
        seq._state = STATE_RUNNING
        seq._current_slug = "up"
        seq._current_position = 1
        seq._current_total = 1
    assert seq.status_detail() == "uploading 2026/FF5/Backed Up Shoot (1/1)"


def test_startup_verification_skips_an_upload_only_project():
    """No folder of ours to verify or release: the server does not share it
    with this machine, and a folder left over from an earlier full tick
    stays exactly as it is."""
    selection = FakeSelectionClient([_up_item("up", "2026/FF5/Backed Up Shoot", 1)])
    admin = FakeAdmin()
    admin.folder_ignores["up"] = None      # would latch a full tick
    admin.paused_state["up"] = True        # would be released for a full tick
    seq, *_ = _build(selection, admin)
    seq._verify_startup_ignores(selection.selection)
    seq._unpause_all(selection.selection)
    assert admin.get_ignores_calls == []
    assert admin.pause_calls == []
