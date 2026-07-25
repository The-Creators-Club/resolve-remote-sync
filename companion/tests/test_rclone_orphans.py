"""Orphan-leftover REPORTING for lane A (AUDIT_2 P8/P15, C-7).

rclone's default --inplace=false writes "<name>.partial" and renames on
completion, so every killed lane A run leaves one on the NAS -- and lane A
never deletes, so they accumulate forever. C-7 is explicit that the answer
is to REPORT them, not delete them: cleaning up would be the one performance
suggestion that adds a delete-on-NAS path, and the never-delete requirement
outranks the disk-hygiene gain. These tests pin that down: the scanner
counts and never removes.
"""

from __future__ import annotations

from ccsync_companion.sync.rclone_lane import (
    DIRECTION_DOWN,
    DIRECTION_UP,
    RcloneLane,
    scan_orphan_partials,
    scan_trash_dir,
)


def _scan(listing, **kwargs):
    calls = []

    def fake_run(cmd, timeout):
        calls.append(cmd)
        return listing

    result = scan_orphan_partials(
        rclone_path="rclone",
        remote=kwargs.pop("remote", "creators_club_sftp"),
        remote_root=kwargs.pop("remote_root", "/mnt/tank/Creators_Club"),
        subpath=kwargs.pop("subpath", "Projects/2026/FF5/Alpha"),
        run_fn=fake_run,
        **kwargs,
    )
    return result, calls


def test_counts_and_sizes_orphan_partials():
    listing = (
        "42949672960;B-roll/A001.braw.partial\n"
        "1048576;Interviewees/Jane/take2.mov.partial\n"
    )
    result, calls = _scan(listing)
    assert result["count"] == 2
    assert result["bytes"] == 42949672960 + 1048576
    assert result["samples"][0]["name"] == "B-roll/A001.braw.partial"


def test_scan_is_files_only_and_prunes_the_dot_trees():
    """A recursive listing that walked .stversions would cost real time over
    SFTP for entries that are none of our business.

    Uses --filter rather than --include + --exclude: measured against the
    bundled rclone 1.74.4, mixing those two makes rclone warn that "the
    order they are parsed in is indeterminate"."""
    _result, calls = _scan("")
    cmd = calls[0]
    assert "--files-only" in cmd
    assert "--include" not in cmd and "--exclude" not in cmd
    filters = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--filter"]
    assert filters == ["- .stversions/**", "- .stfolder/**", "+ *.partial", "- **"]
    assert "creators_club_sftp:/mnt/tank/Creators_Club/Projects/2026/FF5/Alpha" in cmd


def test_scan_never_issues_a_delete():
    """The whole point of C-7. No verb in this command may remove anything."""
    _result, calls = _scan("10;x.mov.partial\n")
    cmd = calls[0]
    assert cmd[1] == "lsf"
    for forbidden in ("delete", "deletefile", "purge", "rmdir", "rmdirs", "sync", "move"):
        assert forbidden not in cmd


def test_scan_tolerates_a_failed_listing():
    def failing(cmd, timeout):
        raise RuntimeError("remote unreachable")

    assert scan_orphan_partials("rclone", "r", "/root", run_fn=failing) is None
    assert scan_orphan_partials("rclone", "r", "/root", run_fn=lambda c, t: None) is None


def test_scan_needs_a_configured_remote():
    assert scan_orphan_partials("rclone", "", "/root") is None
    assert scan_orphan_partials("rclone", "remote", "") is None


def test_scan_survives_a_junk_size_column():
    result, _calls = _scan("notanumber;weird.partial\n\n;\n")
    assert result["count"] == 1
    assert result["bytes"] == 0


def test_samples_are_bounded():
    listing = "".join(f"10;f{i}.mov.partial\n" for i in range(100))
    result, _calls = _scan(listing, max_samples=5)
    assert result["count"] == 100
    assert len(result["samples"]) == 5


# -- local .ccsync-trash (lane B's recovery copies) -------------------------


def test_trash_scan_counts_without_removing(tmp_path):
    trash = tmp_path / ".ccsync-trash" / "20260725-120000" / "Sub" / "Proxy"
    trash.mkdir(parents=True)
    (trash / "recovered.mov").write_bytes(b"x" * 2048)

    result = scan_trash_dir(str(tmp_path))
    assert result == {"count": 1, "bytes": 2048, "truncated": False}
    # Nothing ever prunes it: deleting the recovery copy defeats its purpose.
    assert (trash / "recovered.mov").exists()


def test_trash_scan_on_a_clean_tree(tmp_path):
    assert scan_trash_dir(str(tmp_path)) == {"count": 0, "bytes": 0, "truncated": False}


def test_trash_scan_is_bounded(tmp_path):
    trash = tmp_path / ".ccsync-trash"
    trash.mkdir()
    for i in range(10):
        (trash / f"f{i}.mov").write_bytes(b"x")
    result = scan_trash_dir(str(tmp_path), max_entries=4)
    assert result["count"] == 4
    assert result["truncated"] is True


# -- the lane's public surface ---------------------------------------------


def test_lane_a_publishes_an_orphan_report(monkeypatch, tmp_path):
    lane = RcloneLane(
        direction=DIRECTION_UP,
        local_root=str(tmp_path),
        remote="creators_club_sftp",
        remote_root="/mnt/tank/Creators_Club",
    )
    assert lane.orphan_report() is None

    monkeypatch.setattr(
        "ccsync_companion.sync.rclone_lane.scan_orphan_partials",
        lambda *a, **kw: {"count": 2, "bytes": 99, "samples": []},
    )
    report = lane.refresh_orphan_report("Projects/2026/FF5/Alpha")

    assert report["partials"]["count"] == 2
    assert report["subpath"] == "Projects/2026/FF5/Alpha"
    assert lane.orphan_report()["partials"]["bytes"] == 99


def test_lane_b_has_no_orphan_report():
    """Lane B is the download direction; `.partial` files on the NAS are
    lane A's leftovers."""
    lane = RcloneLane(
        direction=DIRECTION_DOWN, local_root="C:\\root",
        remote="r", remote_root="/root",
    )
    assert lane.refresh_orphan_report("Projects/x") is None


def test_real_rclone_lists_partials_without_touching_them(rclone_binary, tmp_path):
    """Measured, not assumed: the exact argv this ships, run against the
    bundled binary on a scratch tree.

    Also proves the .stversions prune is real -- that tree is a deep mirror
    of every deleted file's directory structure and holds partials of its
    own, which are emphatically not ours to report or act on."""
    remote_root = tmp_path / "nas"
    (remote_root / "B-roll").mkdir(parents=True)
    (remote_root / ".stversions" / "deep").mkdir(parents=True)
    (remote_root / "B-roll" / "A001.braw.partial").write_bytes(b"0" * 4096)
    (remote_root / "B-roll" / "finished.mov").write_bytes(b"1" * 16)
    (remote_root / ".stversions" / "deep" / "old.mov.partial").write_bytes(b"2" * 8)

    assert scan_orphan_partials(rclone_binary, "", str(remote_root)) is None

    # local->local: the fixture path IS the "remote", so drop the "remote:"
    # prefix the real SFTP backend needs.
    from ccsync_companion.sync import rclone_lane as rl

    def local_run(cmd, timeout):
        cmd = [c[len("local:"):] if c.startswith("local:") else c for c in cmd]
        return rl._run_lsf(cmd, timeout)

    result = scan_orphan_partials(
        rclone_binary, "local", str(remote_root), subpath=None, run_fn=local_run
    )
    assert result["count"] == 1
    assert result["bytes"] == 4096
    assert result["samples"][0]["name"].endswith("A001.braw.partial")
    # Nothing was removed -- not the orphan, not the finished file, not the
    # versioned trash.
    assert (remote_root / "B-roll" / "A001.braw.partial").exists()
    assert (remote_root / "B-roll" / "finished.mov").exists()
    assert (remote_root / ".stversions" / "deep" / "old.mov.partial").exists()
