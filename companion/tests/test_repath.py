"""ProjectRepather tests -- the editor-side half of server-side project
moves. Injected fake SyncthingAdmin + move recorder; real dirs in tmp_path."""
from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

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


def test_missing_source_repoints_only_when_the_target_already_holds_the_content(tmp_path):
    old = tmp_path / "Projects" / "2026" / "Gone"
    new = tmp_path / "Projects" / "2026" / "CCT" / "Season 1"
    new.mkdir(parents=True)  # the structure clone (or a hand move) got there first
    admin = FakeAdmin({"s1": str(old)})
    r = ProjectRepather(admin, str(tmp_path))
    assert r.reconcile([_sel("s1", "2026/CCT/Season 1")]) == ["s1"]
    assert ("path", "s1", str(new), "2026/CCT/Season 1") in admin.calls


def test_missing_source_and_missing_target_does_not_repoint(tmp_path):
    """AUDIT_2 DEL-5: with content at neither path, re-pointing hands
    Syncthing an empty directory to reconcile against its index -- i.e. it
    marks the whole project deleted and propagates that to the NAS and every
    other editor. The next pass's structure clone creates the target, and
    the pass after that re-points safely."""
    old = tmp_path / "Projects" / "2026" / "Gone"
    admin = FakeAdmin({"s1": str(old)})
    r = ProjectRepather(admin, str(tmp_path))
    assert r.reconcile([_sel("s1", "2026/CCT/Season 1")]) == []
    assert not any(c[0] == "path" for c in admin.calls)
    # Left paused for a human, deliberately -- never re-pointed-and-unpaused.
    assert ("paused", "s1", False) not in admin.calls


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


def test_failed_move_leaves_the_folder_paused_and_pointed_at_the_old_dir(tmp_path):
    """AUDIT_2 DEL-5/L-8: os.rename failing is ROUTINE on Windows -- Resolve,
    Explorer or AV holding a handle inside the project dir gives a sharing
    violation. Re-pointing anyway aims Syncthing at a directory that doesn't
    hold the content; the structure clone then creates it, Syncthing sees the
    whole indexed project as deleted, and propagates that everywhere."""
    old = tmp_path / "Projects" / "2026" / "Season 1"
    old.mkdir(parents=True)
    (old / "cut.drp").write_text("irreplaceable")

    def refuse(src, dst):
        raise PermissionError("the process cannot access the file: in use")

    admin = FakeAdmin({"s1": str(old)})
    r = ProjectRepather(admin, str(tmp_path), move_fn=refuse)

    assert r.reconcile([_sel("s1", "2026/CCT/Season 1")]) == []
    # Never re-pointed...
    assert not any(c[0] == "path" for c in admin.calls)
    # ...and left PAUSED (paused True was issued, False never was).
    assert ("paused", "s1", True) in admin.calls
    assert ("paused", "s1", False) not in admin.calls
    # The editor's files are exactly where they were.
    assert (old / "cut.drp").read_text() == "irreplaceable"


def test_cross_volume_move_falls_back_to_copy_and_remove(tmp_path):
    """os.rename raises EXDEV across volumes -- a `subst P:` whose target is
    on another drive, or a reconfigured local_root, makes that routine."""
    import errno

    old = tmp_path / "Projects" / "2026" / "Season 1"
    old.mkdir(parents=True)
    (old / "file.txt").write_text("x")
    admin = FakeAdmin({"s1": str(old)})

    real_rename = os.rename
    calls = {"n": 0}

    def exdev_once(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real_rename(src, dst)

    r = ProjectRepather(admin, str(tmp_path))
    with mock.patch("ccsync_companion.sync.repath.os.rename", side_effect=exdev_once):
        assert r.reconcile([_sel("s1", "2026/CCT/Season 1")]) == ["s1"]

    new = tmp_path / "Projects" / "2026" / "CCT" / "Season 1"
    assert (new / "file.txt").read_text() == "x"
    assert not old.exists()


# -- rel_path containment (AUDIT_2 L-7) -------------------------------------


@pytest.mark.parametrize(
    "rel",
    [
        "../../../Windows/Temp/x",   # -> C:\Windows\Temp\x  [measured]
        "2026/../../../evil",        # -> C:\evil            [measured]
        "\\evil",                    # -> C:\evil            [measured]
        # A leading FORWARD slash used to be absent from this list: reconcile
        # stripped it before validating, so "/evil" normalised to a contained
        # "evil" HERE while the sequencer refused the same item -- the
        # project was moved and re-pointed but never synced (AUDIT_3 L-11).
        # Both halves now go through repath.normalized_safe_rel and refuse.
        "/evil",
        "2026\\..\\..\\evil",
        "C:/evil",
        "2026/C:/evil",
        "2026//Season 1",            # empty segment
        "./2026/Season 1",
        "..",
    ],
)
def test_escaping_rel_paths_are_refused(tmp_path, rel):
    old = tmp_path / "Projects" / "2026" / "Season 1"
    old.mkdir(parents=True)
    (old / "file.txt").write_text("x")
    admin = FakeAdmin({"s1": str(old)})
    r = ProjectRepather(admin, str(tmp_path))

    assert r.reconcile([{"slug": "s1", "rel_path": rel, "active": True}]) == []
    assert admin.calls == []            # not even paused
    assert (old / "file.txt").is_file()  # nothing moved anywhere


def test_ordinary_rel_paths_still_pass_the_containment_check():
    from ccsync_companion.sync.repath import rel_path_is_safe

    for rel in ("2026/CCT/Season 1", "2026", "2025/FF4/Nuclear/Sub Project"):
        assert rel_path_is_safe(rel)


def test_syncthing_unreachable_never_raises(tmp_path):
    class DeadAdmin:
        def get_config(self):
            raise OSError("connection refused")

    r = ProjectRepather(DeadAdmin(), str(tmp_path))
    assert r.reconcile([_sel("s1", "2026/CCT/Season 1")]) == []


# -- shared normalize-then-validate helper (AUDIT_3 L-11) -------------------


def test_normalized_safe_rel_normalizes_trailing_separators_only():
    from ccsync_companion.sync.repath import normalized_safe_rel

    assert normalized_safe_rel("  2026/CCT/Season 1  ") == "2026/CCT/Season 1"
    assert normalized_safe_rel("2026/CCT/Season 1/") == "2026/CCT/Season 1"
    # A LEADING separator is not normalised away -- it re-roots the join.
    assert normalized_safe_rel("/2026/CCT/Season 1") is None
    assert normalized_safe_rel("\\2026") is None
    assert normalized_safe_rel("") is None
    assert normalized_safe_rel(None) is None
    assert normalized_safe_rel(5) is None


def test_repath_and_the_sequencer_agree_on_every_rel_path():
    """THE finding: repath stripped a leading "/" before validating and the
    sequencer did not, so "/2026/CCT/Show" was repathed (local directory
    moved, Syncthing folder re-pointed) and then skipped by lanes A and B
    forever, silently. One helper, one answer, for every shape."""
    from ccsync_companion.sync import sequencer as sequencer_mod
    from ccsync_companion.sync import repath as repath_mod

    shapes = [
        "2026/CCT/Season 1", "2026/CCT/Season 1/", " 2026/CCT/Season 1 ",
        "/2026/CCT/Season 1", "\\2026", "../../evil", "2026/../../evil",
        "C:/evil", "..", "", None, 5, "2026//Season 1",
    ]
    for rel in shapes:
        item = {"slug": "s1", "rel_path": rel, "active": True}
        assert sequencer_mod._item_is_valid(item) == repath_mod._item_is_valid(item), rel
