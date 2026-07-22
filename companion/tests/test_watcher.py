"""TimelineWatcher tests — resolve_bridge is mocked via an injected
get_timeline_items callable, never touching a real Resolve instance."""

from __future__ import annotations

from ccsync_companion.fixer import IgnoreTracker
from ccsync_companion.watcher import TimelineWatcher

from conftest import make_timeline_item


def _ok_result(*items):
    return {"ok": True, "message": "", "items": list(items)}


def test_poll_once_classifies_ok_and_ignores_it(tmp_path):
    local_root = str(tmp_path)
    item = make_timeline_item(str(tmp_path / "clip.mov"))
    (tmp_path / "clip.mov").touch()

    captured = []
    watcher = TimelineWatcher(
        local_root=local_root,
        canonical_prefix="P:\\",
        on_out_of_tree=lambda items: captured.append(items),
        get_timeline_items=lambda: _ok_result(item),
    )
    summary = watcher.poll_once()
    assert summary["ok"] is True
    assert summary["out_of_tree"] == 0
    assert captured == []


def test_poll_once_queues_out_of_tree(tmp_path):
    local_root = str(tmp_path / "root")
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    out_of_tree_file = other_dir / "clip.mov"
    out_of_tree_file.touch()
    item = make_timeline_item(str(out_of_tree_file))

    captured = []
    watcher = TimelineWatcher(
        local_root=local_root,
        canonical_prefix="P:\\",
        on_out_of_tree=lambda items: captured.append(items),
        get_timeline_items=lambda: _ok_result(item),
    )
    summary = watcher.poll_once()
    assert summary["out_of_tree"] == 1
    assert len(captured) == 1
    assert captured[0][0]["file_path"] == str(out_of_tree_file)


def test_poll_once_debounces_ignored_out_of_tree_paths(tmp_path):
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    out_of_tree_file = other_dir / "clip.mov"
    out_of_tree_file.touch()
    item = make_timeline_item(str(out_of_tree_file))

    tracker = IgnoreTracker()
    tracker.ignore(str(out_of_tree_file))

    captured = []
    watcher = TimelineWatcher(
        local_root=str(tmp_path / "root"),
        canonical_prefix="P:\\",
        on_out_of_tree=lambda items: captured.append(items),
        ignore_tracker=tracker,
        get_timeline_items=lambda: _ok_result(item),
    )
    watcher.poll_once()
    assert captured == []


def test_poll_once_mapping_warning_fires_once_per_path(tmp_path):
    item = make_timeline_item(r"P:\Projects\clip.mov")

    warnings = []
    watcher = TimelineWatcher(
        local_root=str(tmp_path),
        canonical_prefix="P:\\",
        on_mapping_warning=lambda item: warnings.append(item["file_path"]),
        get_timeline_items=lambda: _ok_result(item),
    )
    watcher.poll_once()
    watcher.poll_once()
    watcher.poll_once()
    assert warnings == [r"P:\Projects\clip.mov"]


def test_poll_once_handles_resolve_error_gracefully():
    watcher = TimelineWatcher(
        local_root=r"C:\Creators_Club",
        canonical_prefix="P:\\",
        get_timeline_items=lambda: {"ok": False, "message": "no timeline open", "items": []},
    )
    summary = watcher.poll_once()
    assert summary["ok"] is False
    assert summary["out_of_tree"] == 0


def test_poll_once_never_raises_when_callback_throws(tmp_path):
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    out_of_tree_file = other_dir / "clip.mov"
    out_of_tree_file.touch()
    item = make_timeline_item(str(out_of_tree_file))

    def boom(_items):
        raise RuntimeError("popup crashed")

    watcher = TimelineWatcher(
        local_root=str(tmp_path / "root"),
        canonical_prefix="P:\\",
        on_out_of_tree=boom,
        get_timeline_items=lambda: _ok_result(item),
    )
    # Should not raise.
    watcher.poll_once()


def test_poll_once_skips_empty_paths():
    item = make_timeline_item("clip.mov")
    item["file_path"] = ""
    captured = []
    watcher = TimelineWatcher(
        local_root=r"C:\Creators_Club",
        canonical_prefix="P:\\",
        on_out_of_tree=lambda items: captured.append(items),
        get_timeline_items=lambda: _ok_result(item),
    )
    watcher.poll_once()
    assert captured == []
