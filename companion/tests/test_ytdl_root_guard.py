"""comp-ytdl-1 / comp-ytdl-5 (2026-08-21): the local YouTube executor and the
disk it writes to.

  * it never asked the root guard. Every lane, the youtube importer, the proxy
    generator and the on-demand b-roll fetch do (COMMERCIAL_READINESS item 5
    closed exactly this gap for broll_fetch); this one creates its own
    destination directories, and on macOS an absent /Volumes/<Name> is not an
    error -- mkdir creates it on the boot volume, GBs land on the internal
    disk, and the next replug mounts the real drive at "/Volumes/<Name> 1".
    free_bytes cannot catch it: free_bytes_at walks up to the first EXISTING
    ancestor, so it answers for the boot volume and passes.
  * the base rig's project probe stat'd a CASEFOLDED path, which is a
    different directory on a case-sensitive volume.

Fixtures and fakes come from test_ytdl_executor (same suite, not a package).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ccsync_companion import root_guard  # noqa: E402
from ccsync_companion import ytdl_executor as ex  # noqa: E402
from test_ytdl_executor import (  # noqa: E402  (sibling test module)
    LABEL, REL_DIR, VID1, FakeFleet, make_cfg, make_deps, manifest_for, run_job,
    watch,
)


def _absent_deps(tmp_path, fleet=None, state=root_guard.ROOT_ABSENT):
    deps = make_deps(tmp_path, fleet=fleet)
    # The two seams app.py fills in: the guard's cached verdict for the fast
    # path, the full probe for the write path.
    deps._root_present_fn = lambda: False
    deps._root_probe_fn = lambda root: state
    return deps


def test_capabilities_refuse_while_the_tree_is_not_mounted(tmp_path):
    result = ex.capabilities(_absent_deps(tmp_path))
    assert result["ok"] is False
    assert result["reason"] == ex.REASON_TREE_ABSENT


def test_capabilities_still_pass_when_the_probe_cannot_tell(tmp_path):
    """root_guard's contract: "can't tell" is never a reason to stop an
    editor working. An app that never wired the seam behaves as before."""
    deps = make_deps(tmp_path)
    assert deps.tree_is_absent() is False
    assert ex.capabilities(deps)["ok"] is True

    exploding = make_deps(tmp_path)

    def _raise():
        raise OSError("the guard thread is gone")

    exploding._root_present_fn = _raise
    assert exploding.tree_is_absent() is False


def test_a_job_creates_no_directory_when_the_tree_is_gone(tmp_path):
    """The SSD was ejected between the capability probe and the manifest: two
    round trips later, the mkdir would build a fake tree on the boot disk."""
    fleet = FakeFleet(manifest_for(clips=[
        {"video_id": VID1, "url": watch(VID1), "title": "A clip", "thumbnail": None}]))
    deps = _absent_deps(tmp_path, fleet=fleet)

    run_job(deps)

    outdir = Path(ex.destination_for(deps.cfg, REL_DIR))
    assert not outdir.exists()
    # Nothing is failed either: the lease simply expires and the server
    # downloads it, which is what every other refusal on this path does.
    assert fleet.statuses == []


def test_a_misplaced_volume_is_refused_like_an_absent_one(tmp_path):
    fleet = FakeFleet(manifest_for())
    deps = _absent_deps(tmp_path, fleet=fleet, state=root_guard.ROOT_MISPLACED)
    run_job(deps)
    assert not Path(ex.destination_for(deps.cfg, REL_DIR)).exists()


def test_an_unknown_probe_lets_the_job_run(tmp_path):
    deps = make_deps(tmp_path)
    deps._root_probe_fn = lambda root: root_guard.ROOT_UNKNOWN
    assert deps.tree_is_misplaced() is False


# -- comp-ytdl-5 ------------------------------------------------------------


def test_the_base_rig_probes_the_labels_own_spelling(tmp_path):
    """On a case-sensitive volume the casefolded spelling is a different
    directory, so every label with an upper-case letter was refused and the
    lease left to expire."""
    cfg = make_cfg(tmp_path, mode="base")
    deps = make_deps(tmp_path, cfg=cfg)
    job = ex.DownloadJob(7, deps)

    here = Path(ex.projects_root(cfg)) / Path(*LABEL.split("/"))
    here.mkdir(parents=True, exist_ok=True)

    probed: list[str] = []
    real_is_dir = Path.is_dir

    def _recording_is_dir(self):
        probed.append(str(self))
        return real_is_dir(self)

    ex_path = ex.Path
    assert ex_path is Path
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "is_dir", _recording_is_dir)
        assert job._label_is_ours(LABEL) is True
    assert probed and probed[-1].endswith(str(Path(*LABEL.split("/"))))
    assert "ff5" not in probed[-1]      # the casefolded spelling, not the real one


def test_the_base_rig_still_refuses_a_label_that_names_nothing(tmp_path):
    cfg = make_cfg(tmp_path, mode="base")
    deps = make_deps(tmp_path, cfg=cfg)
    job = ex.DownloadJob(7, deps)
    assert job._label_is_ours("2026/FF5/Not A Real Project") is False
