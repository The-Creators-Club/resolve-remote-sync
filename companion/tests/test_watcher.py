"""TimelineWatcher tests — resolve_bridge is mocked via an injected
get_timeline_items callable, never touching a real Resolve instance."""

from __future__ import annotations

import pytest

from ccsync_companion import paths
from ccsync_companion.fixer import IgnoreTracker
from ccsync_companion.watcher import TimelineWatcher

from conftest import make_timeline_item


@pytest.fixture(autouse=True)
def _fresh_prefix_cache():
    paths.clear_prefix_cache()
    yield
    paths.clear_prefix_cache()


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


def _subst(monkeypatch, prefix, target):
    """Pretend `subst <prefix> <target>` is (or isn't) in place, by way of the
    realpath() call paths.classify_path makes on the PREFIX."""
    def fake_realpath(p):
        p = str(p)
        if p.upper().startswith(prefix.upper()):
            return target + p[len(prefix):] if target else p
        return p
    monkeypatch.setattr(paths.os.path, "realpath", fake_realpath)
    paths.clear_prefix_cache()


def test_poll_once_canonical_prefix_missing_locally_does_not_warn(tmp_path, monkeypatch):
    # THE designed steady state on a remote editor rig (lane A is
    # upload-only, so a video original legitimately lives only on the NAS
    # and was never downloaded here) must NOT fire a mapping-health
    # notification -- see AUDIT.md §5's BAD_PREFIX-storm finding. This used
    # to assert the opposite (a bug the audit flagged this exact test for
    # enshrining). The mapping is in place here; only the file is absent.
    _subst(monkeypatch, "P:\\", str(tmp_path) + "\\")
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
    assert warnings == []


def test_poll_once_warns_when_the_subst_never_ran(tmp_path, monkeypatch):
    """AUDIT_2 L-15: the PRIMARY mapping failure -- `subst P:` didn't run at
    login, so P:\\ resolves to itself -- produced zero warnings, because the
    classifier keyed on the missing FILE rather than the prefix."""
    _subst(monkeypatch, "P:\\", "")  # P:\ resolves to P:\, i.e. nowhere useful
    item = make_timeline_item(r"P:\Projects\clip.mov")

    warnings = []
    watcher = TimelineWatcher(
        local_root=str(tmp_path),
        canonical_prefix="P:\\",
        on_mapping_warning=lambda i: warnings.append(i["file_path"]),
        get_timeline_items=lambda: _ok_result(item),
    )
    watcher.poll_once()
    watcher.poll_once()
    assert warnings == [r"P:\Projects\clip.mov"]  # warned, and debounced


def test_mapping_warning_re_arms_after_the_mapping_is_fixed(tmp_path, monkeypatch):
    """AUDIT_2 L-17: _warned_mapping warned once per PROCESS lifetime, so a
    break -> fix -> break cycle (reboot without the login subst, fix it, it
    breaks again next week) was silent the second time."""
    item = make_timeline_item(r"P:\Projects\clip.mov")
    warnings = []
    watcher = TimelineWatcher(
        local_root=str(tmp_path),
        canonical_prefix="P:\\",
        on_mapping_warning=lambda i: warnings.append(i["file_path"]),
        get_timeline_items=lambda: _ok_result(item),
    )

    _subst(monkeypatch, "P:\\", "")            # broken
    watcher.poll_once()
    assert len(warnings) == 1

    _subst(monkeypatch, "P:\\", str(tmp_path) + "\\")  # editor fixes it
    watcher.poll_once()
    assert watcher._warned_mapping == set()

    _subst(monkeypatch, "P:\\", "")            # and it breaks again
    watcher.poll_once()
    assert len(warnings) == 2


def test_poll_once_mapping_warning_fires_once_per_genuinely_broken_mapping(tmp_path):
    # A canonical-prefix path that DOES exist on disk but resolves outside
    # local_root is a genuine mapping break (subst/mount pointing at the
    # wrong target) and must still warn, debounced to once per path.
    canon_dir = tmp_path / "canon"
    canon_dir.mkdir()
    clip_path = canon_dir / "clip.mov"
    clip_path.touch()
    item = make_timeline_item(str(clip_path))

    warnings = []
    watcher = TimelineWatcher(
        local_root=str(tmp_path / "root"),
        canonical_prefix=str(canon_dir),
        on_mapping_warning=lambda item: warnings.append(item["file_path"]),
        get_timeline_items=lambda: _ok_result(item),
    )
    watcher.poll_once()
    watcher.poll_once()
    watcher.poll_once()
    assert warnings == [str(clip_path)]


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


@pytest.mark.parametrize(
    "name",
    ["New Doc 1", "New Doc 2", "new doc 17", "New Doc (3)", "  New   Doc 4 ",
     "Untitled Project 2"],
)
def test_ignored_projects_cover_resolve_numbered_duplicates(tmp_path, name):
    """The Blackmagic Proxy Generator's helper project comes back as "New
    Doc 1", "New Doc 2", ... The exact-match list let every new number
    through and the "set this project up on the server" prompt returned
    (seen live 2026-07-25)."""
    from ccsync_companion.watcher import TimelineWatcher

    changed = []
    w = TimelineWatcher(
        local_root=str(tmp_path), canonical_prefix="P:\\",
        get_timeline_items=lambda: {"ok": True, "project_name": name, "items": []},
        on_project_changed=changed.append,
        ignored_projects=["Untitled Project", "New Doc"],
    )
    assert w.poll_once()["ok"] is True
    assert w.last_resolve_project is None
    assert changed == []


@pytest.mark.parametrize("name", ["New Doc Final", "New Documentary", "New Docs 2026"])
def test_a_real_project_that_merely_starts_the_same_is_not_ignored(tmp_path, name):
    from ccsync_companion.watcher import TimelineWatcher

    w = TimelineWatcher(
        local_root=str(tmp_path), canonical_prefix="P:\\",
        get_timeline_items=lambda: {"ok": True, "project_name": name, "items": []},
        ignored_projects=["Untitled Project", "New Doc"],
    )
    w.poll_once()
    assert w.last_resolve_project == name


# -- the sync drive is out (root_guard.py) ----------------------------------


def test_the_poll_stands_down_while_the_root_is_absent():
    """A macOS editor's tree lives on an external SSD that gets unplugged.
    While it is out EVERY clip misclassifies: the ones on the canonical
    prefix as BAD_PREFIX (one mapping-health warning per clip, none of which
    names the real problem) and the rest as OUT_OF_TREE (a popup offering to
    copy media into a directory that does not exist)."""
    calls: list[str] = []
    warnings: list[dict] = []
    watcher = TimelineWatcher(
        local_root="/Volumes/T7/Creators_Club",
        canonical_prefix="P:\\",
        get_timeline_items=lambda: calls.append("poll") or {
            "ok": True, "project_name": "Doc", "items": []},
        on_mapping_warning=warnings.append,
        root_present_fn=lambda: False,
    )

    result = watcher.poll_once()

    assert calls == [], "Resolve was polled with no tree to classify against"
    assert result["ok"] is False
    assert "drive disconnected" in result["message"]
    assert warnings == []


def test_the_gate_leaves_the_open_project_alone():
    """Resolve is still open with the project the editor is working on -- it
    is the MEDIA that is unreachable, not the app -- so the dashboard must
    keep showing the truth while the drive is out."""
    present = {"value": True}
    watcher = TimelineWatcher(
        local_root="/Volumes/T7/Creators_Club",
        canonical_prefix="P:\\",
        get_timeline_items=lambda: {"ok": True, "project_name": "Doc", "items": []},
        root_present_fn=lambda: present["value"],
    )
    watcher.poll_once()
    assert watcher.last_resolve_project == "Doc"

    present["value"] = False
    watcher.poll_once()
    assert watcher.last_resolve_project == "Doc"


def test_a_raising_gate_polls_anyway():
    """Fail open: a broken gate costs a few misclassified clips, never the
    whole watcher."""
    calls: list[str] = []

    def _boom():
        raise RuntimeError("no")

    watcher = TimelineWatcher(
        local_root="/Volumes/T7/Creators_Club",
        canonical_prefix="P:\\",
        get_timeline_items=lambda: calls.append("poll") or {
            "ok": True, "project_name": "Doc", "items": []},
        root_present_fn=_boom,
    )
    assert watcher.poll_once()["ok"] is True
    assert calls == ["poll"]


def test_no_gate_means_the_old_behaviour():
    calls: list[str] = []
    watcher = TimelineWatcher(
        local_root="/Volumes/T7/Creators_Club",
        canonical_prefix="P:\\",
        get_timeline_items=lambda: calls.append("poll") or {
            "ok": True, "project_name": "Doc", "items": []},
    )
    assert watcher.poll_once()["ok"] is True
    assert calls == ["poll"]
