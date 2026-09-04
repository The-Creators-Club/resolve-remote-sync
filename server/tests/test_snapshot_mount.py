"""The snapshot mount the RECOVERY page reads, and the deploy's floor warning.

OPS-3 and OPS-9 (usability + resilience sweep 2026-09-03, built 2026-09-04).

OPS-3: docs/BACKUP_RESTORE.md opens with "start at the dashboard, not at this
document -- Settings -> RECOVERY is the primary route", and that page needs
DASH_SNAPSHOT_DIR to browse or restore anything. `DASH_SNAPSHOT_DIR` had zero
hits in server/, INSTALL.md and SERVER.md, so every install that followed the
documentation ended with a recovery page that could only print commands, and
the owner found that out during an incident.

OPS-9: INSTALL.md Step 4 runs setup_snapshots.py --apply and stops. On this
fleet's own box `/mnt/tank/apps` is a plain directory, so the apps target is
REFUSED and dashboard.db has never had a scheduled snapshot behind it -- under
a green transcript. The deploy asks the same question now and says so.

Offline, like the rest of this suite; run from GIT BASH (see CLAUDE.md).

    cd E:\\Projects\\resolve-remote-sync\\server
    ../dashboard/.venv/Scripts/python.exe -m pytest tests/test_snapshot_mount.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import install_dashboard_app as ida  # noqa: E402

HOST_ROOT = "/mnt/tank/apps/ccsync-dashboard"
TREE_ROOT = "/mnt/tank/TheCreatorsPool/Creators_Club"


def _no_site_keys(monkeypatch):
    """A manifest that names no snapshot directory -- the shipped state."""
    monkeypatch.setattr(ida, "site_value", lambda s, k, d="": "")


def _dirs(monkeypatch, present=True):
    monkeypatch.setattr(ida, "remote_dir_exists", lambda path, dry_run=False: present)


# --------------------------------------------------------------------------
# where the snapshots are
# --------------------------------------------------------------------------

def test_the_deploy_derives_the_mount_and_the_offset_into_it(monkeypatch):
    """The tree root is a FOLDER inside the dataset here, so a snapshot's root
    is two levels above Projects -- which is the offset the page needs and the
    reason the subpath is computed rather than guessed."""
    _no_site_keys(monkeypatch)
    _dirs(monkeypatch)
    monkeypatch.setattr(ida, "probe_dataset", lambda path, dry_run=False: "tank")
    host, sub = ida.snapshot_source(TREE_ROOT, probe=True)
    assert host == "/mnt/tank/.zfs/snapshot"
    assert sub == "TheCreatorsPool/Creators_Club/Projects"


def test_a_tree_that_is_its_own_dataset_has_projects_at_the_top(monkeypatch):
    _no_site_keys(monkeypatch)
    _dirs(monkeypatch)
    monkeypatch.setattr(ida, "probe_dataset",
                        lambda path, dry_run=False: "tank/TheCreatorsPool/Creators_Club")
    host, sub = ida.snapshot_source(TREE_ROOT, probe=True)
    assert host == "/mnt/tank/TheCreatorsPool/Creators_Club/.zfs/snapshot"
    assert sub == "Projects"


def test_the_site_manifest_wins(monkeypatch):
    """The way in for a Synology, whose share snapshots live under
    /volume<N>/@sharesnap and cannot be derived from any path here."""
    named = {("tree", "snapshot_dir"): "/volume1/@sharesnap/creators",
             ("tree", "snapshot_projects_subpath"): "/Projects/"}
    monkeypatch.setattr(ida, "site_value", lambda s, k, d="": named.get((s, k), d))
    monkeypatch.setattr(ida, "probe_dataset",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("a named directory must not be probed")))
    assert ida.snapshot_source(TREE_ROOT, probe=True) == (
        "/volume1/@sharesnap/creators", "Projects")


# --------------------------------------------------------------------------
# ...and every way of not knowing is blank, never a guess
# --------------------------------------------------------------------------

def test_nothing_is_asked_of_the_nas_unless_the_caller_says_so(monkeypatch):
    _no_site_keys(monkeypatch)
    monkeypatch.setattr(ida, "probe_dataset",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("no probe without probe=True")))
    assert ida.snapshot_source(TREE_ROOT) == ("", "")


def test_a_directory_the_nas_does_not_have_is_never_mounted(monkeypatch):
    """docker CREATES a missing bind source. Inventing a `.zfs` directory
    inside a customer's footage tree is not a thing a deploy may do."""
    _no_site_keys(monkeypatch)
    _dirs(monkeypatch, present=False)
    monkeypatch.setattr(ida, "probe_dataset", lambda path, dry_run=False: "tank")
    assert ida.snapshot_source(TREE_ROOT, probe=True) == ("", "")
    assert ida.snapshot_volumes(("", "")) == []


def test_a_dataset_the_tree_is_not_under_is_not_second_guessed(monkeypatch):
    _no_site_keys(monkeypatch)
    _dirs(monkeypatch)
    monkeypatch.setattr(ida, "probe_dataset", lambda path, dry_run=False: "other")
    assert ida.snapshot_source(TREE_ROOT, probe=True) == ("", "")


def test_a_dry_run_probes_nothing(monkeypatch):
    _no_site_keys(monkeypatch)
    monkeypatch.setattr(ida, "probe_dataset", lambda path, dry_run=False: "tank")
    assert ida.remote_dir_exists("/mnt/tank/.zfs/snapshot", dry_run=True) is False
    assert ida.snapshot_source(TREE_ROOT, probe=True, dry_run=True) == ("", "")


# --------------------------------------------------------------------------
# what the container is told
# --------------------------------------------------------------------------

def test_the_compose_body_carries_the_mount_and_both_variables():
    body = ida.compose_config(
        8480, HOST_ROOT, "http://gui:8384", "k", "t",
        snapshot=("/mnt/tank/.zfs/snapshot", "Creators_Club/Projects"),
    )["services"]["dashboard"]
    assert body["environment"]["DASH_SNAPSHOT_DIR"] == ida.SNAPSHOT_MOUNT
    assert body["environment"]["DASH_SNAPSHOT_PROJECTS_SUBPATH"] == \
        "Creators_Club/Projects"
    # READ-ONLY: `.zfs/snapshot` is the one directory on the NAS where a write
    # is a rollback of somebody's footage.
    assert f"/mnt/tank/.zfs/snapshot:{ida.SNAPSHOT_MOUNT}:ro" in body["volumes"]


def test_without_a_snapshot_source_the_page_is_told_nothing_rather_than_a_lie():
    """Blank is what recovery.py renders as "this deployment was never given a
    snapshot mount" -- it is never read as "there are no snapshots"."""
    body = ida.compose_config(8480, HOST_ROOT, "http://gui:8384", "k", "t"
                              )["services"]["dashboard"]
    assert body["environment"]["DASH_SNAPSHOT_DIR"] == ""
    assert body["environment"]["DASH_SNAPSHOT_PROJECTS_SUBPATH"] == ""
    assert not [v for v in body["volumes"] if v.endswith(ida.SNAPSHOT_MOUNT + ":ro")]


def test_the_compose_file_and_the_posted_dict_agree():
    """The Synology path uploads a FILE and the TrueNAS path POSTs a DICT.
    They describe one container, so both take the deploy's own answer."""
    rendered = ida.render_compose_yaml(ida.compose_variables(
        host_root=HOST_ROOT, tree_root=TREE_ROOT,
        snapshot=("/mnt/tank/.zfs/snapshot", "Creators_Club/Projects")))
    assert 'DASH_SNAPSHOT_DIR: "/snapshots"' in rendered
    assert 'DASH_SNAPSHOT_PROJECTS_SUBPATH: "Creators_Club/Projects"' in rendered


# --------------------------------------------------------------------------
# OPS-9: the deploy says when a target has no floor under it
# --------------------------------------------------------------------------

class _Backend:
    """A backend that refuses the apps root exactly as truenas.py does when
    the path is a plain directory in the pool."""

    def __init__(self, refuse=("/mnt/tank/apps/ccsync-dashboard",)):
        self.refuse = refuse
        self.asked = []
        self.policies = []

    def ensure_snapshot_schedule(self, path, schedules, dry_run):
        self.asked.append(path)
        self.policies.append(schedules)
        if path in self.refuse:
            return [("failed", f"refusing to schedule snapshots on 'tank': {path} is "
                               f"a plain directory in it")]
        return []


def test_the_deploy_warns_about_a_target_that_is_not_a_dataset(monkeypatch):
    b = _Backend()
    monkeypatch.setattr(ida, "backend", lambda: b)
    lines = ida.snapshot_schedule_warning(TREE_ROOT, HOST_ROOT)
    assert len(lines) == 1
    assert "this dashboard's own data" in lines[0]
    assert b.asked == [TREE_ROOT, HOST_ROOT]
    # NOTHING IS APPLIED: an empty policy is the read-only question
    # setup_snapshots.py --list asks.
    assert b.policies == [[], []]


def test_a_site_with_both_targets_covered_says_nothing(monkeypatch):
    monkeypatch.setattr(ida, "backend", lambda: _Backend(refuse=()))
    assert ida.snapshot_schedule_warning(TREE_ROOT, HOST_ROOT) == []


def test_a_backend_that_raises_never_fails_the_deploy(monkeypatch):
    class Angry:
        def ensure_snapshot_schedule(self, path, schedules, dry_run):
            raise OSError("no route to host")

    monkeypatch.setattr(ida, "backend", Angry)
    lines = ida.snapshot_schedule_warning(TREE_ROOT, HOST_ROOT)
    assert len(lines) == 2 and all("could not be checked" in line for line in lines)


def test_a_dry_run_asks_nothing(monkeypatch):
    monkeypatch.setattr(ida, "backend",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("a dry run must ask the NAS nothing")))
    assert ida.snapshot_schedule_warning(TREE_ROOT, HOST_ROOT, dry_run=True) == []
