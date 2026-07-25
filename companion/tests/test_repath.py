"""ProjectRepather tests -- the editor-side half of server-side project
moves. Injected fake SyncthingAdmin + move recorder; real dirs in tmp_path."""
from __future__ import annotations

from pathlib import Path

from ccsync_companion.sync.repath import ProjectRepather


class FakeAdmin:
    def __init__(self, folders):
        self.folders = folders          # id -> path
        self.calls: list[tuple] = []
        self.fail_pause: set[str] = set()

    def get_config(self):
        return {"folders": [{"id": fid, "path": p} for fid, p in self.folders.items()]}

    def set_folder_paused(self, folder_id, paused):
        if paused and folder_id in self.fail_pause:
            raise OSError("pause failed")
        self.calls.append(("paused", folder_id, paused))

    def set_folder_path(self, folder_id, path, label=None):
        self.calls.append(("path", folder_id, path, label))
        self.folders[folder_id] = path


def _sel(slug, rel):
    return {"slug": slug, "rel_path": rel, "position": 0, "active": True}


def test_matching_path_is_noop(tmp_path):
    expected = tmp_path / "Projects" / "2026" / "CCT" / "Season 1"
    admin = FakeAdmin({"s1": str(expected)})
    r = ProjectRepather(admin, str(tmp_path))
    assert r.reconcile([_sel("s1", "2026/CCT/Season 1")]) == []
    assert admin.calls == []


def test_moved_project_is_moved_and_repointed(tmp_path):
    old = tmp_path / "Projects" / "2026" / "Season 1"
    old.mkdir(parents=True)
    (old / "file.txt").write_text("x")
    admin = FakeAdmin({"s1": str(old)})
    r = ProjectRepather(admin, str(tmp_path))

    repathed = r.reconcile([_sel("s1", "2026/CCT/Season 1")])
    assert repathed == ["s1"]
    new = tmp_path / "Projects" / "2026" / "CCT" / "Season 1"
    assert (new / "file.txt").is_file()
    assert not old.exists()
    # pause -> path -> unpause ordering
    kinds = [c[0] for c in admin.calls]
    assert kinds == ["paused", "path", "paused"]
    assert admin.calls[0][2] is True and admin.calls[2][2] is False
    assert admin.calls[1][2] == str(new)
    assert admin.calls[1][3] == "2026/CCT/Season 1"


def test_missing_source_repoints_only(tmp_path):
    old = tmp_path / "Projects" / "2026" / "Gone"
    admin = FakeAdmin({"s1": str(old)})
    r = ProjectRepather(admin, str(tmp_path))
    assert r.reconcile([_sel("s1", "2026/CCT/Season 1")]) == ["s1"]
    assert ("path", "s1", str(tmp_path / "Projects" / "2026" / "CCT" / "Season 1"),
            "2026/CCT/Season 1") in admin.calls


def test_target_exists_conflict_skips_move_but_repoints(tmp_path):
    old = tmp_path / "Projects" / "2026" / "Season 1"
    old.mkdir(parents=True)
    (old / "keep.txt").write_text("old")
    new = tmp_path / "Projects" / "2026" / "CCT" / "Season 1"
    new.mkdir(parents=True)
    admin = FakeAdmin({"s1": str(old)})
    r = ProjectRepather(admin, str(tmp_path))
    assert r.reconcile([_sel("s1", "2026/CCT/Season 1")]) == ["s1"]
    assert (old / "keep.txt").is_file()          # old dir left for the human
    assert ("path", "s1", str(new), "2026/CCT/Season 1") in admin.calls


def test_pause_failure_skips_project_entirely(tmp_path):
    old = tmp_path / "Projects" / "2026" / "Season 1"
    old.mkdir(parents=True)
    admin = FakeAdmin({"s1": str(old)})
    admin.fail_pause.add("s1")
    r = ProjectRepather(admin, str(tmp_path))
    assert r.reconcile([_sel("s1", "2026/CCT/Season 1")]) == []
    assert old.is_dir()  # untouched
    assert not any(c[0] == "path" for c in admin.calls)


def test_unpause_always_happens_even_when_repoint_fails(tmp_path):
    old = tmp_path / "Projects" / "2026" / "Season 1"
    old.mkdir(parents=True)

    class BrokenPathAdmin(FakeAdmin):
        def set_folder_path(self, folder_id, path, label=None):
            raise OSError("patch failed")

    admin = BrokenPathAdmin({"s1": str(old)})
    r = ProjectRepather(admin, str(tmp_path))
    assert r.reconcile([_sel("s1", "2026/CCT/Season 1")]) == []
    assert ("paused", "s1", False) in admin.calls  # unpaused in finally


def test_move_out_of_nested_tree_leaves_local_root_and_projects_dir_intact(tmp_path):
    """Regression (AUDIT D-3): the default move_fn used to be os.renames,
    which prunes every now-empty parent of the SOURCE all the way up. Moving
    the only project out of "2026" (leaving it empty) must NOT cascade into
    deleting Projects/ or local_root itself (the `subst P:` target)."""
    old = tmp_path / "Projects" / "2026" / "Season 1"
    old.mkdir(parents=True)
    (old / "file.txt").write_text("x")
    admin = FakeAdmin({"s1": str(old)})
    r = ProjectRepather(admin, str(tmp_path))

    repathed = r.reconcile([_sel("s1", "2027/CCT/Season 1")])
    assert repathed == ["s1"]

    new = tmp_path / "Projects" / "2027" / "CCT" / "Season 1"
    assert (new / "file.txt").is_file()
    assert not old.exists()
    # "2026" is now empty -- os.renames would have pruned it, then
    # Projects/, then local_root itself. None of that may happen.
    assert (tmp_path / "Projects" / "2026").is_dir()
    assert (tmp_path / "Projects").is_dir()
    assert tmp_path.is_dir()


def test_null_rel_path_is_skipped_not_literal_none(tmp_path):
    """AUDIT D-4: a dashboard row whose rel_path is None (e.g. an orphaned
    selection) must never reach the path join, where str(None) == "None"
    would become a literal "...\\Projects\\None" move target."""
    admin = FakeAdmin({"s1": str(tmp_path / "Projects" / "Somewhere")})
    r = ProjectRepather(admin, str(tmp_path))
    item = {"slug": "s1", "rel_path": None, "active": True}
    assert r.reconcile([item]) == []
    assert admin.calls == []


def test_non_str_rel_path_is_skipped(tmp_path):
    admin = FakeAdmin({"s1": str(tmp_path / "Projects" / "Somewhere")})
    r = ProjectRepather(admin, str(tmp_path))
    item = {"slug": "s1", "rel_path": 123, "active": True}
    assert r.reconcile([item]) == []
    assert admin.calls == []


def test_inactive_item_is_skipped(tmp_path):
    old = tmp_path / "Projects" / "2026" / "Season 1"
    old.mkdir(parents=True)
    admin = FakeAdmin({"s1": str(old)})
    r = ProjectRepather(admin, str(tmp_path))
    item = {"slug": "s1", "rel_path": "2026/CCT/Season 1", "active": False}
    assert r.reconcile([item]) == []
    assert admin.calls == []


def test_unaccepted_or_unknown_folders_skipped(tmp_path):
    admin = FakeAdmin({})
    r = ProjectRepather(admin, str(tmp_path))
    assert r.reconcile([_sel("s1", "2026/CCT/Season 1"), {"slug": None}]) == []
    assert admin.calls == []


def test_syncthing_unreachable_never_raises(tmp_path):
    class DeadAdmin:
        def get_config(self):
            raise OSError("connection refused")

    r = ProjectRepather(DeadAdmin(), str(tmp_path))
    assert r.reconcile([_sel("s1", "2026/CCT/Season 1")]) == []
