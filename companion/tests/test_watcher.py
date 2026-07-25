"""TimelineWatcher tests — resolve_bridge is mocked via an injected
get_timeline_items callable, never touching a real Resolve instance."""

from __future__ import annotations

from ccsync_companion.fixer import IgnoreTracker
from ccsync_companion.watcher import TimelineWatcher

from conftest import make_timeline_item


def _ok_result(*items, project_name=""):
    return {"ok": True, "message": "", "items": list(items), "project_name": project_name}


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


def test_poll_once_attaches_resolve_project_name_to_out_of_tree_items(tmp_path):
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
        get_timeline_items=lambda: _ok_result(item, project_name="CCT Creator Profiles"),
    )
    watcher.poll_once()
    assert captured[0][0]["resolve_project_name"] == "CCT Creator Profiles"


def test_poll_once_out_of_tree_item_defaults_to_blank_project_name_when_absent(tmp_path):
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
        get_timeline_items=lambda: {"ok": True, "message": "", "items": [item]},  # no project_name key
    )
    watcher.poll_once()
    assert captured[0][0]["resolve_project_name"] == ""


def test_poll_once_tracks_last_resolve_project(tmp_path):
    watcher = TimelineWatcher(
        local_root=str(tmp_path),
        canonical_prefix="P:\\",
        get_timeline_items=lambda: _ok_result(project_name="CCT Creator Profiles"),
    )
    watcher.poll_once()
    assert watcher.last_resolve_project == "CCT Creator Profiles"


def test_poll_once_last_resolve_project_updates_across_polls(tmp_path):
    names = iter(["Project A", "Project B"])
    watcher = TimelineWatcher(
        local_root=str(tmp_path),
        canonical_prefix="P:\\",
        get_timeline_items=lambda: _ok_result(project_name=next(names)),
    )
    watcher.poll_once()
    assert watcher.last_resolve_project == "Project A"
    watcher.poll_once()
    assert watcher.last_resolve_project == "Project B"


def test_last_resolve_project_defaults_to_none_before_first_poll(tmp_path):
    watcher = TimelineWatcher(
        local_root=str(tmp_path),
        canonical_prefix="P:\\",
        get_timeline_items=lambda: _ok_result(),
    )
    assert watcher.last_resolve_project is None


def test_poll_once_last_resolve_project_none_when_bridge_lacks_it(tmp_path):
    watcher = TimelineWatcher(
        local_root=str(tmp_path),
        canonical_prefix="P:\\",
        get_timeline_items=lambda: {"ok": True, "message": "", "items": []},  # no project_name key
    )
    watcher.poll_once()
    assert watcher.last_resolve_project is None


def test_poll_once_last_resolve_project_none_when_project_name_blank(tmp_path):
    watcher = TimelineWatcher(
        local_root=str(tmp_path),
        canonical_prefix="P:\\",
        get_timeline_items=lambda: _ok_result(project_name=""),
    )
    watcher.poll_once()
    assert watcher.last_resolve_project is None


def test_poll_once_last_resolve_project_none_when_bridge_raises(tmp_path):
    def boom():
        raise RuntimeError("resolve bridge died")

    watcher = TimelineWatcher(
        local_root=str(tmp_path),
        canonical_prefix="P:\\",
        get_timeline_items=boom,
    )
    watcher.last_resolve_project = "Stale Project"
    watcher.poll_once()
    assert watcher.last_resolve_project is None


def test_poll_once_last_resolve_project_updates_even_on_resolve_error(tmp_path):
    watcher = TimelineWatcher(
        local_root=str(tmp_path),
        canonical_prefix="P:\\",
        get_timeline_items=lambda: {
            "ok": False, "message": "no timeline open", "items": [], "project_name": "Open But No Timeline",
        },
    )
    watcher.poll_once()
    assert watcher.last_resolve_project == "Open But No Timeline"


def test_poll_once_does_not_mutate_caller_item_dict(tmp_path):
    local_root = str(tmp_path / "root")
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    out_of_tree_file = other_dir / "clip.mov"
    out_of_tree_file.touch()
    item = make_timeline_item(str(out_of_tree_file))

    watcher = TimelineWatcher(
        local_root=local_root,
        canonical_prefix="P:\\",
        get_timeline_items=lambda: _ok_result(item, project_name="Some Project"),
    )
    watcher.poll_once()
    assert "resolve_project_name" not in item


# -- on_project_changed (new-project onboarding hook) ------------------------


def _watcher_with_project_stream(tmp_path, names, changed):
    from ccsync_companion.watcher import TimelineWatcher

    stream = iter(names)

    def fake_items():
        name = next(stream)
        if name is _RAISE:
            raise OSError("bridge down")
        return {"ok": True, "items": [], "project_name": name}

    return TimelineWatcher(
        local_root=str(tmp_path),
        canonical_prefix="P:\\",
        get_timeline_items=fake_items,
        on_project_changed=changed.append,
    )


_RAISE = object()


def test_project_changed_fires_on_new_names(tmp_path):
    changed = []
    w = _watcher_with_project_stream(tmp_path, ["Doc A", "Doc A", "Doc B"], changed)
    w.poll_once(); w.poll_once(); w.poll_once()
    assert changed == ["Doc A", "Doc B"]


def test_project_changed_no_refire_on_bridge_flap(tmp_path):
    changed = []
    w = _watcher_with_project_stream(
        tmp_path, ["Doc A", _RAISE, None, "Doc A"], changed)
    for _ in range(4):
        w.poll_once()
    assert changed == ["Doc A"]  # name -> down -> no-name -> same name: once


def test_project_changed_callback_exception_swallowed(tmp_path):
    from ccsync_companion.watcher import TimelineWatcher

    def boom(name):
        raise RuntimeError("boom")

    w = TimelineWatcher(
        local_root=str(tmp_path), canonical_prefix="P:\\",
        get_timeline_items=lambda: {"ok": True, "items": [], "project_name": "Doc"},
        on_project_changed=boom,
    )
    result = w.poll_once()  # must not raise
    assert result["ok"] is True


def test_ignored_projects_are_invisible(tmp_path):
    """A scratch/BPG project in ignored_resolve_projects: not tracked as
    last_resolve_project (so never reported/prompted), items never popped,
    on_project_changed never fired."""
    from ccsync_companion.watcher import TimelineWatcher

    changed = []
    popped = []
    w = TimelineWatcher(
        local_root=str(tmp_path),
        canonical_prefix="P:\\",
        get_timeline_items=lambda: {
            "ok": True,
            "project_name": "New Doc",
            "items": [{"file_path": str(tmp_path.parent / "outside.mov"),
                       "media_pool_item": object(), "clip_name": "outside"}],
        },
        on_out_of_tree=popped.append,
        on_project_changed=changed.append,
        ignored_projects=["Untitled Project", "new doc"],
    )
    result = w.poll_once()
    assert result["ok"] is True
    assert result["out_of_tree"] == 0
    assert w.last_resolve_project is None
    assert changed == []
    assert popped == []


def test_non_ignored_project_still_tracked(tmp_path):
    from ccsync_companion.watcher import TimelineWatcher

    w = TimelineWatcher(
        local_root=str(tmp_path), canonical_prefix="P:\\",
        get_timeline_items=lambda: {"ok": True, "project_name": "Real Doc", "items": []},
        ignored_projects=["Untitled Project", "New Doc"],
    )
    w.poll_once()
    assert w.last_resolve_project == "Real Doc"
