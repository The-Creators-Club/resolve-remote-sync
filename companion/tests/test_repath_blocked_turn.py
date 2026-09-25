"""bug-comp-rclone-1 (2026-09-24): a project whose repath is blocked gets no
turn at the NEW path. The structure clone and lane B used to create
local_root/Projects/<new rel> right after the failed move, and the next pass
took that directory for the project and re-pointed Syncthing at it.

A real Sequencer and a real ProjectRepather over tmp_path, a fake
SyncthingAdmin, lanes that write what lane B writes. No thread is started.
"""

from __future__ import annotations

from pathlib import Path

from ccsync_companion.sync.repath import ProjectRepather
from ccsync_companion.sync.sequencer import Sequencer


class _Admin:
    def __init__(self, folders):
        self.folders = folders
        self.calls: list[tuple] = []

    def get_config(self):
        return {"folders": [{"id": f, "path": p, "paused": False}
                            for f, p in self.folders.items()]}

    def get_folders(self):
        return self.get_config()["folders"]

    def set_folder_paused(self, folder_id, paused):
        self.calls.append(("paused", folder_id, paused))

    def set_folder_path(self, folder_id, path, label=None):
        self.calls.append(("path", folder_id, path))
        self.folders[folder_id] = path


class _LaneB:
    """Writes a proxy under the subpath it is given, as rclone sync would."""

    name = "lane_b"

    def __init__(self, root: Path):
        self.root = root
        self.calls: list[str] = []

    def run_once(self, subpath=None):
        self.calls.append(subpath)
        proxy = self.root / Path(*str(subpath).split("/")) / "Proxy"
        proxy.mkdir(parents=True, exist_ok=True)
        (proxy / "a.mov").write_text("proxy")


class _LaneA:
    name = "lane_a"

    def __init__(self):
        self.calls: list[str] = []

    def run_once(self, subpath=None):
        self.calls.append(subpath)


class _NoShared:
    def folder_ids(self):
        return []

    def reconcile(self, *a, **kw):
        return None


class _Selection:
    enabled = True

    def __init__(self, items):
        self.items = items

    def get(self):
        return self.items, "live"

    def load_cached(self):
        return list(self.items)


def test_a_blocked_move_is_not_finished_by_the_lanes_next_pass(tmp_path):
    old = tmp_path / "Projects" / "2026" / "Old"
    (old / ".stfolder").mkdir(parents=True)
    (old / "Assets.wav").write_text("the real project")
    new = tmp_path / "Projects" / "2026" / "New"
    admin = _Admin({"slug1": str(old)})

    def held_by_resolve(src, dst):
        raise PermissionError(13, "The process cannot access the file")

    repather = ProjectRepather(admin, str(tmp_path), move_fn=held_by_resolve)
    clones: list[str] = []
    lane_a, lane_b = _LaneA(), _LaneB(tmp_path)
    item = {"slug": "slug1", "label": "New", "rel_path": "2026/New", "position": 0,
            "active": True}
    seq = Sequencer(
        lane_a, lane_b, admin, _Selection([item]),
        {"local_root": str(tmp_path), "remote": "", "lane_b_enabled": True},
        clone_tree_fn=lambda *a, **kw: clones.append("clone"),
        repather=repather, shared_folders=_NoShared(),
    )
    seq._resume_event.set()

    # Pass 1: the move fails (Resolve holds a handle).
    seq._process_project(item, [item])
    assert repather.ledger.blocked("slug1")
    assert lane_b.calls == [] and lane_a.calls == [] and clones == []
    assert not new.exists(), "nothing may be created at the new path before the move"

    # Pass 2: still held. Must stay blocked, pointed at the old path, paused.
    admin.calls.clear()
    seq._process_project(item, [item])
    assert not any(c[0] == "path" for c in admin.calls)
    assert ("paused", "slug1", False) not in admin.calls
    assert admin.folders["slug1"] == str(old)
    notes = [e["note"] for e in repather.ledger.events()]
    assert not any("moved your copy" in n for n in notes)

    # Pass 3: Resolve let go. The move happens and the turn runs at the new path.
    repather._move = lambda src, dst: Path(src).rename(dst)
    seq._process_project(item, [item])
    assert admin.folders["slug1"] == str(new)
    assert (new / "Assets.wav").read_text() == "the real project"
    assert lane_b.calls == ["Projects/2026/New"]


def test_a_blocked_event_for_a_folder_no_longer_here_does_not_hold_the_turn(tmp_path):
    """The accept of a re-offered folder happens inside the project's turn,
    so a blocked event outliving its folder must not skip that turn."""
    admin = _Admin({})
    repather = ProjectRepather(admin, str(tmp_path))
    repather.ledger.record("slug1", "old", "new", "blocked", relinked=None, moved=False)
    assert repather.ledger.blocked("slug1")
    item = {"slug": "slug1", "label": "New", "rel_path": "2026/New", "position": 0,
            "active": True}
    assert repather.reconcile([item]) == []
    assert not repather.ledger.blocked("slug1")
