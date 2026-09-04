"""sync/borrowed_folders: the lender folders a machine borrows from
(SHARED_FOLDERS_PLAN.md WP3).

The property these tests protect is one notch tighter than the shared-folder
version: a borrowed lender folder must never go online without its
RESTRICTED .stignore -- the plain project list would pull the lender's every
non-video file to a machine that never ticked it.
"""
from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

from ccsync_companion.sync import borrowed_folders, shared_folders
from ccsync_companion.sync.borrowed_folders import BorrowedFolderManager, local_path_for
from ccsync_companion.sync.syncthing_admin import (
    STIGNORE_LINES,
    escape_ignore_glob,
    is_restricted,
    restricted_ignore_lines,
)


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "nope", {}, None)


class FakeAdmin:
    def __init__(self, folder=None, ignores=None, pending=None):
        self.folder = folder
        self.ignores = ignores
        self.pending = pending or {}
        self.calls: list[tuple] = []
        self.removed: list[str] = []

    def get_folder(self, folder_id):
        if self.folder is None:
            raise _http_error(404)
        return dict(self.folder)

    def get_folders(self):
        return [dict(self.folder)] if self.folder is not None else []

    def get_ignores(self, folder_id):
        if self.ignores is None:
            return {"ignore": None}
        return {"ignore": list(self.ignores)}

    def set_ignores(self, folder_id, lines):
        self.calls.append(("set_ignores", folder_id, tuple(lines)))
        self.ignores = list(lines)

    def set_folder_paused(self, folder_id, paused):
        self.calls.append(("set_paused", folder_id, paused))
        if self.folder is not None:
            self.folder["paused"] = paused

    def set_folder_path(self, folder_id, path, label=None):
        self.calls.append(("set_path", folder_id, path))
        if self.folder is not None:
            self.folder["path"] = path

    def ensure_versioning(self, folder_id, folder=None):
        self.calls.append(("ensure_versioning", folder_id))
        return False

    def ensure_ignore_delete(self, folder_id, folder=None):
        self.calls.append(("ensure_ignore_delete", folder_id))
        return (folder or {}).get("ignoreDelete") is not True

    def pending_folders(self):
        return self.pending

    def accept_folder(self, folder_id, label, local_path, device_id, ignore_lines=None):
        self.calls.append(("accept", folder_id, local_path, device_id,
                           tuple(ignore_lines or ())))
        self.folder = {"id": folder_id, "path": local_path, "paused": False,
                       "ignoreDelete": True}
        self.ignores = list(ignore_lines or [])
        return {}

    def remove_folder(self, folder_id):
        self.removed.append(folder_id)
        self.folder = None

    def names(self):
        return [c[0] for c in self.calls]


LENDER = "2026/FF5/Civil Defence"
SUB = "Interviewees/Aha Chu"
SLUG = "2026-ff5-civil-defence"


def _lenders():
    return {SLUG: {"rel": LENDER, "subs": [SUB], "borrowers": ["2026-ff5-elections"]}}


def _manager(admin, tmp_path, lenders=None, halted=None, selected=("s-selected",)):
    return BorrowedFolderManager(
        admin, tmp_path, lenders_fn=(lenders if lenders is not None else _lenders),
        selected_slugs_fn=lambda: list(selected),
        halted=halted)


# ---------------------------------------------------------------- the lines

def test_restricted_ignore_lines_shape():
    lines = restricted_ignore_lines([SUB])
    # the exact STIGNORE_LINES prefix, byte-identical: the lane split
    # (video/Proxy stay out) applies inside the subtree too
    assert lines[: len(STIGNORE_LINES)] == list(STIGNORE_LINES)
    assert lines[len(STIGNORE_LINES):] == [
        f"!/{SUB}", f"!/{SUB}/**", "**"]
    assert is_restricted({"ignore": lines})


def test_restricted_ignore_lines_escapes_glob_specials():
    lines = restricted_ignore_lines(["Interviewees/What? [Take 2]"])
    assert "!/Interviewees/What\\? \\[Take 2\\]" in lines
    assert escape_ignore_glob("a*b") == "a\\*b"
    assert escape_ignore_glob("a\\b") == "a\\\\b"


def test_is_restricted_shapes():
    assert not is_restricted({"ignore": list(STIGNORE_LINES)})
    assert not is_restricted({"ignore": None})
    assert not is_restricted({"ignore": ["!/x", "!/x/**"]})       # no trailing **
    assert is_restricted({"ignore": ["!/x", "!/x/**", "**"]})


# ---------------------------------------------------------------- accept

def test_accepts_the_offer_restricted(tmp_path):
    admin = FakeAdmin(pending={SLUG: {"offeredBy": {"DEV-SERVER": {}}}})
    mgr = _manager(admin, tmp_path)
    assert mgr.reconcile() == {SLUG: "accepted"}
    kind, slug, path, device, lines = admin.calls[-1]
    assert kind == "accept"
    assert slug == SLUG
    assert device == "DEV-SERVER"
    assert path == local_path_for(tmp_path, LENDER)
    assert Path(path).is_dir()                      # created before accept
    assert list(lines) == restricted_ignore_lines([SUB])


def test_no_offer_is_routine(tmp_path):
    admin = FakeAdmin()
    mgr = _manager(admin, tmp_path)
    assert mgr.reconcile() == {SLUG: "not-offered"}
    assert admin.calls == []


def test_halted_machine_leaves_the_offer_pending(tmp_path):
    admin = FakeAdmin(pending={SLUG: {"offeredBy": {"DEV-SERVER": {}}}})
    mgr = _manager(admin, tmp_path, halted=lambda: True)
    assert mgr.reconcile() == {SLUG: "not-offered"}
    assert "accept" not in admin.names()


# ---------------------------------------------------------------- steady state

def _healthy_admin(tmp_path):
    path = local_path_for(tmp_path, LENDER)
    return FakeAdmin(
        folder={"id": SLUG, "path": path, "paused": False, "ignoreDelete": True},
        ignores=restricted_ignore_lines([SUB]))


def test_steady_state_makes_no_config_writes(tmp_path):
    admin = _healthy_admin(tmp_path)
    mgr = _manager(admin, tmp_path)
    assert mgr.reconcile() == {SLUG: "ok"}
    assert "set_ignores" not in admin.names()
    assert "set_paused" not in admin.names()
    assert "set_path" not in admin.names()


def test_unrestricted_ignores_are_rewritten_before_any_unpause(tmp_path):
    # The dangerous state: the lender's folder exists here with the PLAIN
    # project list (hand-accepted, or a bug) -- online it would pull the
    # lender's whole non-video tree.
    path = local_path_for(tmp_path, LENDER)
    admin = FakeAdmin(
        folder={"id": SLUG, "path": path, "paused": True, "ignoreDelete": True},
        ignores=list(STIGNORE_LINES))
    mgr = _manager(admin, tmp_path)
    assert mgr.reconcile() == {SLUG: "repaired"}
    idx = admin.names().index("set_ignores")
    assert admin.ignores == restricted_ignore_lines([SUB])
    # unpause only AFTER the restricted list landed
    unpause = admin.calls.index(("set_paused", SLUG, False))
    assert idx < unpause


def test_unconfirmed_ignores_keep_the_folder_paused(tmp_path):
    path = local_path_for(tmp_path, LENDER)

    class Failing(FakeAdmin):
        def set_ignores(self, folder_id, lines):
            raise RuntimeError("config write timed out")

    admin = Failing(
        folder={"id": SLUG, "path": path, "paused": True, "ignoreDelete": True},
        ignores=list(STIGNORE_LINES))
    mgr = _manager(admin, tmp_path)
    mgr.reconcile()
    assert ("set_paused", SLUG, False) not in admin.calls


def test_halt_blocks_the_release(tmp_path):
    path = local_path_for(tmp_path, LENDER)
    admin = FakeAdmin(
        folder={"id": SLUG, "path": path, "paused": True, "ignoreDelete": True},
        ignores=restricted_ignore_lines([SUB]))
    mgr = _manager(admin, tmp_path, halted=lambda: True)
    mgr.reconcile()
    assert ("set_paused", SLUG, False) not in admin.calls


# ---------------------------------------------------------------- moves

def test_lender_moved_on_the_nas_re_points_and_moves_the_partial_dir(tmp_path):
    old_rel = "2026/FF5/Old Name"
    old_path = local_path_for(tmp_path, old_rel)
    Path(old_path, SUB).mkdir(parents=True)
    Path(old_path, SUB, "note.txt").write_text("borrowed file")
    admin = FakeAdmin(
        folder={"id": SLUG, "path": old_path, "paused": False, "ignoreDelete": True},
        ignores=restricted_ignore_lines([SUB]))
    moves: list[tuple] = []

    def move(src, dst):
        moves.append((src, dst))
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(src).rename(dst)

    mgr = BorrowedFolderManager(admin, tmp_path, lenders_fn=_lenders, move_dir=move)
    assert mgr.reconcile() == {SLUG: "repaired"}
    new_path = local_path_for(tmp_path, LENDER)
    assert admin.folder["path"] == new_path
    assert moves == [(old_path, new_path)]
    assert Path(new_path, SUB, "note.txt").read_text() == "borrowed file"


# ---------------------------------------------------------------- drop

def test_last_borrower_unticked_removes_config_but_keeps_files(tmp_path):
    admin = FakeAdmin(pending={SLUG: {"offeredBy": {"DEV-SERVER": {}}}})
    lenders = {"value": _lenders()}
    mgr = _manager(admin, tmp_path, lenders=lambda: lenders["value"])
    mgr.reconcile()                                  # accepts
    marker = Path(local_path_for(tmp_path, LENDER), SUB)
    marker.mkdir(parents=True, exist_ok=True)

    lenders["value"] = {}                            # borrower unticked
    mgr.reconcile()
    assert admin.removed == [SLUG]
    assert marker.is_dir()                           # files stay on disk


def test_drop_survives_a_tray_restart(tmp_path):
    # The restricted .stignore, not an in-memory accepted set, identifies
    # the folder -- a FRESH manager (post-restart) still drops it.
    path = local_path_for(tmp_path, LENDER)
    admin = FakeAdmin(
        folder={"id": SLUG, "path": path, "paused": False, "ignoreDelete": True},
        ignores=restricted_ignore_lines([SUB]))
    mgr = _manager(admin, tmp_path, lenders=lambda: {})
    mgr.reconcile()
    assert admin.removed == [SLUG]


def test_a_lender_that_became_selected_is_left_alone(tmp_path):
    # A ticked lender belongs to the sequencer now, whatever its ignores
    # still say -- the sequencer's restriction check rewrites them.
    path = local_path_for(tmp_path, LENDER)
    admin = FakeAdmin(
        folder={"id": SLUG, "path": path, "paused": False, "ignoreDelete": True},
        ignores=restricted_ignore_lines([SUB]))
    mgr = _manager(admin, tmp_path, lenders=lambda: {}, selected=(SLUG,))
    mgr.reconcile()
    assert admin.removed == []


def test_unrestricted_folders_and_empty_selections_drop_nothing(tmp_path):
    # A folder on the full project list is not this feature's; and an empty
    # selection is no information (a dashboard blip must not deconfigure
    # every borrowed folder).
    path = local_path_for(tmp_path, LENDER)
    admin = FakeAdmin(
        folder={"id": SLUG, "path": path, "paused": False, "ignoreDelete": True},
        ignores=list(STIGNORE_LINES))
    mgr = _manager(admin, tmp_path, lenders=lambda: {})
    mgr.reconcile()
    assert admin.removed == []

    admin2 = FakeAdmin(
        folder={"id": SLUG, "path": path, "paused": False, "ignoreDelete": True},
        ignores=restricted_ignore_lines([SUB]))
    mgr2 = _manager(admin2, tmp_path, lenders=lambda: {}, selected=())
    mgr2.reconcile()
    assert admin2.removed == []


# ---------------------------------------------------------------- fault isolation

def test_one_broken_lender_does_not_stop_the_rest(tmp_path):
    class Broken(FakeAdmin):
        def get_folder(self, folder_id):
            if folder_id == "bad-lender":
                raise RuntimeError("boom")
            return super().get_folder(folder_id)

    admin = Broken(pending={SLUG: {"offeredBy": {"DEV-SERVER": {}}}})

    def lenders():
        return {
            "bad-lender": {"rel": "2026/Bad", "subs": ["X"], "borrowers": ["b"]},
            SLUG: _lenders()[SLUG],
        }

    mgr = _manager(admin, tmp_path, lenders=lenders)
    results = mgr.reconcile()
    assert results["bad-lender"] == "error"
    assert results[SLUG] == "accepted"


# -- SYNC-6: the drive is out --------------------------------------------------


def test_reconcile_does_nothing_at_all_while_the_tree_is_absent(tmp_path):
    """SYNC-6 (resilience sweep 2026-08-28): called from the sequencer's loop
    head, before any root check. Both _accept and _repoint end in a
    mkdir(parents=True) that would build the lender's path on the boot disk
    while the external SSD is out, and then point a Syncthing folder at it."""
    admin = FakeAdmin(pending={SLUG: {"offeredBy": {"DEVICE-1": {}}}})
    gone = tmp_path / "Volumes" / "SAMDISK"  # never created
    mgr = BorrowedFolderManager(admin, gone, lenders_fn=_lenders,
                                selected_slugs_fn=lambda: [])
    assert mgr.reconcile() == {}
    assert admin.calls == [] and admin.removed == []
    assert not gone.exists()


def test_an_unanswerable_root_probe_counts_as_absent(tmp_path):
    admin = FakeAdmin(pending={SLUG: {"offeredBy": {"DEVICE-1": {}}}})

    def _boom():
        raise RuntimeError("the volume did not answer")

    mgr = BorrowedFolderManager(admin, tmp_path, lenders_fn=_lenders,
                                selected_slugs_fn=lambda: [],
                                root_present_fn=_boom)
    assert mgr.reconcile() == {}
    assert admin.calls == []


def test_accept_refuses_the_mkdir_if_the_drive_goes_out_mid_reconcile(tmp_path):
    admin = FakeAdmin(pending={SLUG: {"offeredBy": {"DEVICE-1": {}}}})
    gone = tmp_path / "Volumes" / "SAMDISK"
    mgr = BorrowedFolderManager(admin, gone, lenders_fn=_lenders,
                                selected_slugs_fn=lambda: [],
                                root_present_fn=lambda: True)
    assert mgr.reconcile()[SLUG] == "error"
    assert "accept" not in admin.names()
    assert not gone.exists()


def test_repoint_leaves_the_folder_where_it_is_when_the_drive_is_out(tmp_path):
    """A re-point at a path we cannot create is worse than a stale one: the
    folder would be pointed at a ghost directory on the boot disk."""
    gone = tmp_path / "Volumes" / "SAMDISK"
    admin = FakeAdmin(
        folder={"id": SLUG, "paused": False, "path": str(tmp_path / "old"),
                "ignoreDelete": True},
        ignores=list(restricted_ignore_lines([SUB])),
    )
    mgr = BorrowedFolderManager(admin, gone, lenders_fn=_lenders,
                                selected_slugs_fn=lambda: [],
                                root_present_fn=lambda: True)
    mgr.reconcile()
    assert "set_path" not in admin.names()
    assert not gone.exists()


# -- comp-sync-4: the re-point pauses, so the same pass must release it --------


def _running_folder_at(tmp_path, old_path):
    return FakeAdmin(
        folder={"id": SLUG, "paused": False, "path": str(old_path),
                "ignoreDelete": True},
        ignores=list(restricted_ignore_lines([SUB])),
    )


def test_a_repointed_folder_is_released_in_the_same_pass(tmp_path):
    """bug-hunt-2026-09-03 comp-sync-4: _repoint pauses the folder, and the
    unpause branches used to read the dict fetched BEFORE it -- so a lender
    that had been running was seen as unpaused and left paused until the next
    pass noticed. A borrowed subtree stopped syncing for a whole rotation with
    no line saying why (repath.py unpauses in the same function, deliberately)."""
    old = tmp_path / "Projects" / "2026" / "FF5" / "Old Name"
    old.mkdir(parents=True)
    admin = _running_folder_at(tmp_path, old)
    mgr = _manager(admin, tmp_path)
    assert mgr.reconcile() == {SLUG: "repaired"}
    assert admin.folder["path"] == local_path_for(tmp_path, LENDER)
    # Paused for the move, then released -- in that order, and after the path.
    paused = admin.calls.index(("set_paused", SLUG, True))
    repointed = admin.calls.index(("set_path", SLUG, local_path_for(tmp_path, LENDER)))
    released = admin.calls.index(("set_paused", SLUG, False))
    assert paused < repointed < released
    assert admin.folder["paused"] is False


def test_a_repointed_folder_stays_paused_while_the_machine_is_halted(tmp_path):
    """A halt is a stop, not pacing: the release comp-sync-4 adds must not
    become a way round it."""
    old = tmp_path / "Projects" / "2026" / "FF5" / "Old Name"
    old.mkdir(parents=True)
    admin = _running_folder_at(tmp_path, old)
    mgr = _manager(admin, tmp_path, halted=lambda: True)
    mgr.reconcile()
    assert ("set_paused", SLUG, False) not in admin.calls
    assert admin.folder["paused"] is True


def test_a_repointed_folder_stays_paused_when_its_ignores_are_unconfirmed(tmp_path):
    """The tighter rule this module exists for: a lender folder must never go
    online on the plain project list, re-point or no re-point."""
    old = tmp_path / "Projects" / "2026" / "FF5" / "Old Name"
    old.mkdir(parents=True)
    admin = _running_folder_at(tmp_path, old)
    def _boom(folder_id):
        raise RuntimeError("syncthing did not answer")

    admin.get_ignores = _boom
    mgr = _manager(admin, tmp_path)
    mgr.reconcile()
    assert ("set_paused", SLUG, False) not in admin.calls


# -- SYNC-101: the borrowed half of "kept, not logged once" -----------------

def test_a_lender_the_server_never_shared_is_kept_as_a_problem(tmp_path):
    """The borrowed subtree that never appears is the same silence the LUT
    library had (SYNC-101, sweep 2026-09-03)."""
    admin = FakeAdmin(pending={})
    mgr = _manager(admin, tmp_path)
    assert mgr.reconcile() == {SLUG: "not-offered"}
    problems = mgr.problems()
    assert len(problems) == 1
    assert LENDER in problems[0] and "Ask your admin" in problems[0]
    assert "—" not in problems[0]


def test_a_borrowed_problem_backs_off_and_clears(tmp_path):
    ticks = [1000.0]

    def now():
        return ticks[0]

    admin = FakeAdmin(pending={})
    mgr = BorrowedFolderManager(
        admin, tmp_path, lenders_fn=_lenders,
        selected_slugs_fn=lambda: ["s-selected"], now=now)
    assert mgr.reconcile() == {SLUG: "not-offered"}
    calls = len(admin.calls)
    assert mgr.reconcile() == {SLUG: "not-offered"}     # backing off
    assert len(admin.calls) == calls

    ticks[0] += shared_folders.PROBLEM_RETRY_FIRST_SECONDS + 1
    admin.pending = {SLUG: {"offeredBy": {"DEVICE-1": {}}}}
    assert mgr.reconcile() == {SLUG: "accepted"}
    assert mgr.problems() == []


def test_a_lender_nobody_borrows_any_more_stops_being_a_problem(tmp_path):
    admin = FakeAdmin(pending={})
    lenders = {"live": dict(_lenders())}

    mgr = BorrowedFolderManager(
        admin, tmp_path, lenders_fn=lambda: lenders["live"],
        selected_slugs_fn=lambda: ["s-selected"])
    mgr.reconcile()
    assert mgr.problems()
    lenders["live"] = {}
    mgr.reconcile()
    assert mgr.problems() == []


def test_a_repointed_lender_that_stays_paused_is_a_problem(tmp_path):
    """Fail-closed is right and was invisible: the subtree is not syncing."""
    old = tmp_path / "Projects" / "2026" / "FF5" / "Old Name"
    old.mkdir(parents=True)
    admin = _running_folder_at(tmp_path, old)

    def _boom(folder_id):
        raise RuntimeError("syncthing did not answer")

    admin.get_ignores = _boom
    mgr = _manager(admin, tmp_path)
    assert mgr.reconcile() == {SLUG: "unfiltered"}
    assert "filter list" in mgr.problems()[0]
