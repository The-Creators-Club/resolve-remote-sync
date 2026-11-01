"""CR-366 (prelaunch GL-12 / GL-13 / GL-14, 2026-10-07): "Remove from this
machine" must never delete a file that is not on the server.

Three holes in the old gate, all of them a permanent rmtree behind a dialog
that said nothing would be lost:
  GL-12  the dry run reused lane A's --min-age, so footage under two minutes
         old, or dated in the future by a camera clock, counted as "nothing
         pending";
  GL-13  an upload-only tick carried video only, and the gate checked nothing
         else (sound recordings, stills, documents were deleted);
  GL-14  a file whose name the NAS already holds at another size never
         uploads (--ignore-existing) and counted as uploaded.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from ccsync_companion import tray
from ccsync_companion.sync import rclone_lane as rl
from ccsync_companion.sync.rclone_lane import (
    DIRECTION_UP,
    RcloneLane,
    build_filter_rules_up,
    build_up_command,
    scan_edited_since_upload,
    scan_local_tree,
    scan_pending_uploads,
    scan_size_mismatches_strict,
)
from ccsync_companion.sync.sequencer import Sequencer


def _filter(tmp_path, carry_all=False) -> Path:
    path = tmp_path / ("fa.txt" if carry_all else "f.txt")
    rl.write_filter_file(build_filter_rules_up(carry_all=carry_all), path)
    return path


# -- GL-12: the dry run has no age floor --------------------------------------


def test_the_gate_dry_run_drops_min_age_and_keeps_min_size(tmp_path):
    seen = []

    def run(cmd, timeout):
        seen.append(cmd)
        return 0, ""

    scan_pending_uploads("rclone", str(tmp_path), "nas", "CC", _filter(tmp_path),
                         "Projects/X", run_fn=run)
    assert "--min-age" not in seen[0]
    assert "--min-size" in seen[0] and "--dry-run" in seen[0]


def test_a_run_that_moves_bytes_still_has_the_age_floor(tmp_path):
    cmd = build_up_command("rclone", str(tmp_path), "nas", "CC", _filter(tmp_path))
    assert "--min-age" in cmd and "--min-size" in cmd


def test_a_file_younger_than_the_age_floor_is_counted_pending_by_real_rclone(
        tmp_path, rclone_binary):
    local = tmp_path / "local"
    (local / "Projects" / "X").mkdir(parents=True)
    (tmp_path / "remote").mkdir()
    (local / "Projects" / "X" / "fresh.mov").write_bytes(b"x" * 64)  # mtime = now
    old = local / "Projects" / "X" / "old.mov"
    old.write_bytes(b"y" * 64)
    past = time.time() - 3600
    os.utime(old, (past, past))
    future = local / "Projects" / "X" / "clock.mov"
    future.write_bytes(b"z" * 64)
    ahead = time.time() + 86400
    os.utime(future, (ahead, ahead))
    # ":local:" as the remote so the real binary runs the real dry run.
    out = scan_pending_uploads(
        rclone_binary, str(local), ":local", str(tmp_path / "remote").replace("\\", "/"),
        _filter(tmp_path), "Projects/X",
    )
    assert out is not None
    names = sorted(out["samples"])
    assert names == ["clock.mov", "fresh.mov", "old.mov"], out


def test_future_dated_video_is_named_by_the_local_scan(tmp_path):
    proj = tmp_path / "P"
    proj.mkdir()
    clip = proj / "A001.mov"
    clip.write_bytes(b"x")
    ahead = time.time() + 15 * 3600
    os.utime(clip, (ahead, ahead))
    ok = proj / "B001.mov"
    ok.write_bytes(b"x")
    scan = scan_local_tree(str(tmp_path), "P", carry_all=False)
    assert scan["future"] == {"count": 1, "samples": ["A001.mov"]}
    assert scan["uncarried"]["count"] == 0


def test_a_clock_a_few_minutes_ahead_is_not_future_dated(tmp_path):
    proj = tmp_path / "P"
    proj.mkdir()
    clip = proj / "A001.mov"
    clip.write_bytes(b"x")
    ahead = time.time() + 60
    os.utime(clip, (ahead, ahead))
    assert scan_local_tree(str(tmp_path), "P", False)["future"]["count"] == 0


# -- GL-13: lane A carries every file of an upload-only project ---------------


def test_carry_all_rules_take_every_file_but_keep_the_safety_excludes():
    rules = build_filter_rules_up(carry_all=True)
    assert rules[-2:] == ["+ *", "- **"]
    assert not any(r.startswith("+ *.") for r in rules)
    for must in ("- ._*", "- **/Proxy/**", "- /Proxy/**", "- *.partial", "- *.tmp",
                 "- *.lock", "- *.part", "- *.ytdl"):
        assert must in rules
    # every exclude is ahead of the include: first match wins
    assert max(i for i, r in enumerate(rules) if r.startswith("- ") and r != "- **") \
        < rules.index("+ *")


def test_the_default_rules_are_still_video_only():
    rules = build_filter_rules_up()
    assert "+ *" not in rules and "+ *.mov" in rules


def test_real_rclone_carries_the_wav_for_upload_only_and_not_for_full(
        tmp_path, rclone_binary):
    src = tmp_path / "src"
    (src / "Audio").mkdir(parents=True)
    (src / "Proxy").mkdir()
    (src / "A.mov").write_bytes(b"v")
    (src / "Audio" / "take1.wav").write_bytes(b"w")
    (src / "shot.JPG").write_bytes(b"j")
    (src / "Proxy" / "p.mov").write_bytes(b"p")
    (src / "._A.mov").write_bytes(b"a")
    (src / "half.partial").write_bytes(b"h")
    (src / "x.tmp").write_bytes(b"t")

    def carried(carry_all):
        dst = tmp_path / ("dst_all" if carry_all else "dst_video")
        proc = subprocess.run(
            [rclone_binary, "copy", str(src), str(dst),
             "--filter-from", str(_filter(tmp_path, carry_all)), "--ignore-case"],
            capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
        return sorted(str(p.relative_to(dst)).replace("\\", "/")
                      for p in dst.rglob("*") if p.is_file())

    assert carried(False) == ["A.mov"]
    assert carried(True) == ["A.mov", "Audio/take1.wav", "shot.JPG"]


def _lane(tmp_path, carry):
    (tmp_path / "local").mkdir(exist_ok=True)
    return RcloneLane(
        direction=DIRECTION_UP, local_root=str(tmp_path / "local"), remote="nas",
        remote_root="CC", state_dir=tmp_path / "state",
        carry_all_fn=carry,
    )


def test_the_lane_writes_the_carry_all_rules_only_for_an_upload_only_subpath(tmp_path):
    lane = _lane(tmp_path, lambda sub: sub == "Projects/Up/Only")
    wide = lane._ensure_filter_file(subpath="Projects/Up/Only")
    narrow = lane._ensure_filter_file(subpath="Projects/Other")
    assert wide != narrow
    assert "+ *" in wide.read_text(encoding="utf-8").splitlines()
    assert "+ *" not in narrow.read_text(encoding="utf-8").splitlines()
    # the whole-tree run, and a lane with no question, are always video-only
    assert lane.carries_everything(None) is False
    assert _lane(tmp_path, None).carries_everything("Projects/Up/Only") is False


def test_a_failing_carry_all_question_reads_as_video_only(tmp_path):
    def boom(sub):
        raise RuntimeError("selection gone")

    assert _lane(tmp_path, boom).carries_everything("Projects/X") is False


def test_the_sequencer_knows_which_subpaths_are_upload_only():
    seq = Sequencer.__new__(Sequencer)
    seq._lock = threading.RLock()
    seq._slug_to_item = {
        "a": {"slug": "a", "rel_path": "2026/Series/Ingest Day", "sync_mode": "upload_only"},
        "b": {"slug": "b", "rel_path": "2026/Series/Full", "sync_mode": "full"},
    }
    seq._upload_only_slugs = {"a"}
    assert seq.is_upload_only_subpath("Projects/2026/Series/Ingest Day") is True
    assert seq.is_upload_only_subpath("projects\\2026\\series\\ingest day\\Audio") is True
    assert seq.is_upload_only_subpath("Projects/2026/Series/Full") is False
    assert seq.is_upload_only_subpath("Projects/2026/Series/Ingest Day 2") is False
    assert seq.is_upload_only_subpath("Projects/2026/Series") is False
    assert seq.is_upload_only_subpath(None) is False


def test_the_local_scan_names_a_file_even_the_wide_lane_refuses(tmp_path):
    proj = tmp_path / "P"
    (proj / "Proxy").mkdir(parents=True)
    (proj / "Audio").mkdir()
    (proj / "A.mov").write_bytes(b"v")
    (proj / "Audio" / "take1.wav").write_bytes(b"w")      # carried by the wide lane
    (proj / "Audio" / "edit.tmp").write_bytes(b"t")       # refused by name: named
    (proj / "Proxy" / "p.mov").write_bytes(b"p")          # lane B's: not counted
    (proj / ".DS_Store").write_bytes(b"d")                # litter: not counted
    (proj / "._A.mov").write_bytes(b"a")                  # AppleDouble: not counted
    (proj / "empty.wav").write_bytes(b"")                 # nothing to lose
    scan = scan_local_tree(str(tmp_path), "P", carry_all=True)
    assert scan["uncarried"] == {"count": 1, "samples": ["Audio/edit.tmp"]}


def test_a_full_tick_does_not_ask_the_local_scan_about_non_video(tmp_path):
    proj = tmp_path / "P"
    proj.mkdir()
    (proj / "take1.wav").write_bytes(b"w")  # lane C's job for a full tick
    assert scan_local_tree(str(tmp_path), "P", carry_all=False)["uncarried"]["count"] == 0


def test_a_missing_folder_scans_as_empty_and_a_read_error_raises(tmp_path, monkeypatch):
    assert scan_local_tree(str(tmp_path), "Nope", True)["uncarried"]["count"] == 0
    proj = tmp_path / "P"
    proj.mkdir()
    (proj / "a.wav").write_bytes(b"x")
    real = os.stat

    def deny(path, *a, **k):
        if str(path).endswith("a.wav"):
            raise PermissionError("locked")
        return real(path, *a, **k)

    monkeypatch.setattr(rl.os, "stat", deny)
    with pytest.raises(OSError):
        scan_local_tree(str(tmp_path), "P", True)


def test_the_lane_local_scan_is_none_when_the_disk_cannot_be_read(tmp_path, monkeypatch):
    lane = _lane(tmp_path, None)

    def boom(*a, **k):
        raise OSError("disk")

    monkeypatch.setattr(rl, "scan_local_tree", boom)
    assert lane.local_tree_scan("Projects/X") is None


# -- GL-13: the dialog claims only what was checked ---------------------------


def test_the_ready_dialog_does_not_overclaim_for_either_mode():
    full = tray.remove_ready_body("2026/S/P", upload_only=False)
    up = tray.remove_ready_body("2026/S/P", upload_only=True)
    assert "so nothing will be lost" not in full + up
    assert "video files and its shared" in full
    assert "every file in this project's folder" in up
    assert "Proxy" in full and "Proxy" in up
    assert "—" not in full + up  # no em dashes in user-visible text


# -- GL-14: the strict same-name check ----------------------------------------


def _strict(tmp_path, result):
    return scan_size_mismatches_strict(
        "rclone", str(tmp_path), "nas", "CC", _filter(tmp_path), "Projects/X",
        run_fn=lambda cmd, t: result)


def test_strict_check_reads_differ_lines_from_combined(tmp_path):
    out = _strict(tmp_path, (1, "= a.mov\n* b.wav\n+ sub/c.mov\n* d.mov\n",
        "2026/10/07 ERROR : b.wav: sizes differ\n"
        "2026/10/07 ERROR : sub/c.mov: file not in nas:CC\n"
        "2026/10/07 ERROR : d.mov: sizes differ\n"))
    assert out == {"count": 2, "samples": ["b.wav", "d.mov"]}


def test_strict_check_is_zero_only_when_it_demonstrably_ran(tmp_path):
    assert _strict(tmp_path, (0, "= a.mov\n", "")) == {"count": 0, "samples": []}


def test_strict_check_treats_a_missing_destination_dir_as_nothing_to_mismatch(tmp_path):
    out = _strict(tmp_path, (3, "", "2026/10/07 ERROR : nas:CC/Projects/X: error "
                                    "reading destination root directory: directory not found\n"))
    assert out == {"count": 0, "samples": []}


@pytest.mark.parametrize("result", [
    None,
    (1, "", "2026/10/07 CRITICAL: Failed to create file system: couldn't connect SSH\n"),
    (1, "", "2026/10/07 ERROR : x: some unknown failure\n"),
    (3, "", "2026/10/07 ERROR : /local/X: error reading source root directory: directory not found\n"),
    (3, "", ""),
    (2, "* a\n", ""),
    (7, "", ""),
])
def test_strict_check_fails_closed_on_anything_it_does_not_understand(tmp_path, result):
    assert _strict(tmp_path, result) is None


def test_strict_check_fails_closed_when_the_runner_raises(tmp_path):
    def run(cmd, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    assert scan_size_mismatches_strict(
        "rclone", str(tmp_path), "nas", "CC", _filter(tmp_path), "P", run_fn=run) is None


def test_strict_check_finds_a_real_same_name_different_size_file(tmp_path, rclone_binary):
    local = tmp_path / "local" / "P"
    remote = tmp_path / "remote" / "P"
    local.mkdir(parents=True)
    remote.mkdir(parents=True)
    (local / "C0001.MP4").write_bytes(b"x" * 10)
    (remote / "C0001.MP4").write_bytes(b"y" * 99)
    (local / "same.mov").write_bytes(b"s" * 5)
    (remote / "same.mov").write_bytes(b"s" * 5)
    (local / "new.mov").write_bytes(b"n")
    out = scan_size_mismatches_strict(
        rclone_binary, str(tmp_path / "local"), ":local",
        str(tmp_path / "remote").replace("\\", "/"), _filter(tmp_path), "P")
    assert out == {"count": 1, "samples": ["C0001.MP4"]}


def test_strict_check_covers_non_video_for_an_upload_only_filter(tmp_path, rclone_binary):
    local = tmp_path / "local" / "P"
    remote = tmp_path / "remote" / "P"
    local.mkdir(parents=True)
    remote.mkdir(parents=True)
    (local / "take1.wav").write_bytes(b"x" * 10)
    (remote / "take1.wav").write_bytes(b"y" * 99)
    out = scan_size_mismatches_strict(
        rclone_binary, str(tmp_path / "local"), ":local",
        str(tmp_path / "remote").replace("\\", "/"), _filter(tmp_path, True), "P")
    assert out == {"count": 1, "samples": ["take1.wav"]}


def test_the_lane_strict_probe_never_raises_and_says_none(tmp_path, monkeypatch):
    lane = _lane(tmp_path, None)

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(rl, "scan_size_mismatches_strict", boom)
    assert lane.strict_size_mismatches("Projects/X") is None


# -- round 2 (2026-10-07): litter, Syncthing state, full-tick refused names, edits


def _both_dirs(tmp_path):
    local = tmp_path / "local" / "P"
    remote = tmp_path / "remote" / "P"
    local.mkdir(parents=True)
    remote.mkdir(parents=True)
    return local, remote, str(tmp_path / "remote").replace("\\", "/")


def test_carry_all_rules_refuse_os_litter_and_syncthing_state():
    rules = build_filter_rules_up(carry_all=True)
    for must in ("- .DS_Store", "- Thumbs.db", "- desktop.ini", "- .stversions/**",
                 "- **/.stversions/**", "- .stfolder/**", "- **/.stfolder/**",
                 "- .stignore", "- *.ccsync-tmp"):
        assert must in rules
    assert max(i for i, r in enumerate(rules) if r.startswith("- ") and r != "- **") \
        < rules.index("+ *")


def test_real_rclone_never_uploads_litter_or_syncthing_state_and_never_flags_them(
        tmp_path, rclone_binary):
    local, remote, remote_root = _both_dirs(tmp_path)
    (local / ".DS_Store").write_bytes(b"x" * 50)
    (remote / ".DS_Store").write_bytes(b"y" * 20)
    (local / "Thumbs.db").write_bytes(b"x" * 50)
    (remote / "Thumbs.db").write_bytes(b"y" * 10)
    (local / ".stversions").mkdir()
    (local / ".stversions" / "edit~20260901-120000.drp").write_bytes(b"v")
    (local / ".stfolder").mkdir()
    (local / ".stfolder" / "marker.txt").write_bytes(b"m")
    (local / ".stignore").write_bytes(b"(?i)*.mov")
    (local / "sub" / ".stversions").mkdir(parents=True)
    (local / "sub" / ".stversions" / "old.wav").write_bytes(b"o")
    (local / "take1.wav").write_bytes(b"w")
    filt = _filter(tmp_path, True)
    pending = scan_pending_uploads(rclone_binary, str(tmp_path / "local"), ":local",
                                   remote_root, filt, "P")
    assert pending == {"count": 1, "samples": ["take1.wav"]}, pending
    strict = scan_size_mismatches_strict(rclone_binary, str(tmp_path / "local"), ":local",
                                         remote_root, filt, "P")
    assert strict == {"count": 0, "samples": []}, strict
    scan = scan_local_tree(str(tmp_path / "local"), "P", carry_all=True)
    assert scan["uncarried"]["count"] == 0


def test_a_full_tick_names_a_video_no_lane_carries(tmp_path):
    proj = tmp_path / "P"
    proj.mkdir()
    refused = ["Interview.original.mov", "Shot.temp.v2.mov", "x.f137.mp4",
               ".ccsync-move-12-Clip.mov", "dl.mp4.part", "dl.mp4.ytdl", "c.wav.ccsync-tmp",
               "dl.mp4.part-Frag3"]
    for name in refused:
        (proj / name).write_bytes(b"v")
    (proj / "fine.mov").write_bytes(b"v")          # lane A
    (proj / "take1.wav").write_bytes(b"w")         # lane C
    (proj / "._fine.mov").write_bytes(b"a")        # AppleDouble litter
    (proj / "x.partial").write_bytes(b"p")         # litter
    (proj / ".stversions").mkdir()
    (proj / ".stversions" / "old.mov").write_bytes(b"s")
    scan = scan_local_tree(str(tmp_path), "P", carry_all=False, max_samples=50)
    assert sorted(scan["uncarried"]["samples"]) == sorted(refused)


def test_the_carry_all_scan_also_names_ccsync_tmp_and_fragments(tmp_path):
    proj = tmp_path / "P"
    proj.mkdir()
    (proj / "c.wav.ccsync-tmp").write_bytes(b"v")
    (proj / "dl.mp4.part-Frag3").write_bytes(b"v")
    (proj / "ok.wav").write_bytes(b"w")
    scan = scan_local_tree(str(tmp_path), "P", carry_all=True)
    assert scan["uncarried"]["count"] == 2


def test_real_rclone_finds_a_same_size_edit_but_not_a_new_or_untouched_file(
        tmp_path, rclone_binary):
    local, remote, remote_root = _both_dirs(tmp_path)
    past = time.time() - 7200
    for name, mine, theirs in (("vo.wav", b"NEW!" * 25, b"OLD!" * 25),
                               ("same.wav", b"s" * 9, b"s" * 9)):
        (local / name).write_bytes(mine)
        (remote / name).write_bytes(theirs)
        os.utime(remote / name, (past, past))
    os.utime(local / "same.wav", (past, past))
    (local / "brand_new.wav").write_bytes(b"n")
    out = scan_edited_since_upload(rclone_binary, str(tmp_path / "local"), ":local",
                                   remote_root, _filter(tmp_path, True), "P")
    assert out == {"count": 1, "samples": ["vo.wav"]}, out


def test_the_edit_check_fails_closed(tmp_path):
    filt = _filter(tmp_path, True)

    def run(cmd, timeout):
        return 1, "boom"

    assert scan_edited_since_upload("rclone", str(tmp_path), "nas", "CC", filt, "P",
                                    run_fn=run) is None

    def boom(cmd, timeout):
        raise OSError("gone")

    assert scan_edited_since_upload("rclone", str(tmp_path), "nas", "CC", filt, "P",
                                    run_fn=boom) is None


def test_the_edit_check_runs_with_update_not_ignore_existing(tmp_path):
    seen = []

    def run(cmd, timeout):
        seen.append(cmd)
        return 0, ""

    out = scan_edited_since_upload("rclone", str(tmp_path), "nas", "CC",
                                   _filter(tmp_path, True), "P", run_fn=run)
    assert out == {"count": 0, "samples": []}
    assert "--update" in seen[0] and "--ignore-existing" not in seen[0]
    assert "--ignore-existing" in seen[1] and "--update" not in seen[1]
    assert all("--dry-run" in c and "--min-age" not in c for c in seen)


def test_the_lane_only_asks_the_edit_question_of_an_upload_only_project(tmp_path, monkeypatch):
    lane = _lane(tmp_path, lambda sub: sub == "Projects/Up")

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(rl, "scan_edited_since_upload", boom)
    assert lane.edited_since_upload("Projects/Full") == {"count": 0, "samples": []}
    assert lane.edited_since_upload("Projects/Up") is None


def test_future_dated_files_are_summed_across_projects_and_the_tray_names_one(tmp_path):
    lane = _lane(tmp_path, None)
    ahead = time.time() + 15 * 3600
    for proj in ("A", "B"):
        d = tmp_path / "local" / proj
        d.mkdir(parents=True)
        clip = d / f"{proj}001.mov"
        clip.write_bytes(b"x")
        os.utime(clip, (ahead, ahead))
    clean = tmp_path / "local" / "C"
    clean.mkdir()
    (clean / "ok.mov").write_bytes(b"x")
    for proj in ("A", "B", "C"):       # a clean project scanned last must not wipe it
        lane._refresh_future_dated(proj)
    report = lane.future_dated_report()
    assert report["count"] == 2 and sorted(report["samples"]) == ["A001.mov", "B001.mov"]
    line = tray._future_dated_line({"future_dated": report})
    assert "2 files are dated in the future" in line and "will NOT upload" in line
    assert "first:" in line and ", dated 20" in line
    assert "—" not in line
    assert tray._future_dated_line({}) is None
    assert tray._future_dated_line({"future_dated": {"count": 0}}) is None


def test_the_settings_advisories_carry_the_future_dated_line():
    from ccsync_companion import settings_window

    lines = settings_window._lane_advisories(
        {"future_dated": {"count": 1, "samples": ["A001.mov"], "first_mtime": time.time()}})
    assert any("dated in the future" in text for _sev, text in lines)


# -- round 2 (2026-10-07): the gate's own mode wins over a lagging sequencer --

def _stale_seq(known_as):
    """A Sequencer whose cached view of the project is `known_as` ('full' or
    None for never-started): it refreshes only between passes."""
    seq = Sequencer.__new__(Sequencer)
    seq._lock = threading.RLock()
    seq._slug_to_item = ({} if known_as is None else
                         {"p1": {"slug": "p1", "rel_path": "2026/CCT/Ingest",
                                 "sync_mode": known_as}})
    seq._upload_only_slugs = set()
    return seq


@pytest.mark.parametrize("known_as", ["full", None])
def test_gate_blocks_an_upload_only_project_the_sequencer_still_calls_full(
        tmp_path, rclone_binary, known_as):
    from test_sync_halt import _app

    app = _app(tmp_path)
    local_root = Path(app.config["local_root"])
    proj = local_root / "Projects" / "2026" / "CCT" / "Ingest"
    rproj = tmp_path / "remote" / "Projects" / "2026" / "CCT" / "Ingest"
    proj.mkdir(parents=True)
    rproj.mkdir(parents=True)
    (proj / "A.mov").write_bytes(b"v" * 10)
    (rproj / "A.mov").write_bytes(b"v" * 10)
    (proj / "Audio").mkdir()
    (proj / "Audio" / "take1.wav").write_bytes(b"w" * 10)    # the only copy
    seq = _stale_seq(known_as)
    app._lane_a = RcloneLane(
        direction=DIRECTION_UP, local_root=str(local_root), remote=":local",
        remote_root=str(tmp_path / "remote").replace("\\", "/"),
        state_dir=tmp_path / "state", rclone_path=rclone_binary,
        carry_all_fn=lambda sub: seq.is_upload_only_subpath(sub))
    app.syncthing_admin = None
    app.removable_projects = lambda: [
        {"slug": "p1", "rel": "2026/CCT/Ingest", "upload_only": True}]
    out = app.removal_blockers("p1")
    assert out["blocked"] is True
    assert out["pending_uploads"] == 1 and not out["unknown"]


def test_lane_questions_widen_on_an_explicit_carry_all(tmp_path):
    lane = _lane(tmp_path, None)        # no carry_all_fn: the narrow rules
    assert lane.carries_everything("Projects/X") is False
    sub = tmp_path / "local" / "Projects" / "X"
    sub.mkdir(parents=True)
    (sub / "notes.docx").write_bytes(b"d")
    assert lane.local_tree_scan("Projects/X")["uncarried"]["count"] == 0
    assert lane.local_tree_scan("Projects/X", carry_all=True)["uncarried"]["count"] == 0
    assert lane.edited_since_upload("Projects/X") == {"count": 0, "samples": []}


def test_future_dated_entry_is_dropped_when_unticked_or_folder_gone(tmp_path):
    lane = _lane(tmp_path, None)
    ahead = time.time() + 15 * 3600
    for proj in ("A", "B"):
        d = tmp_path / "local" / proj
        d.mkdir(parents=True)
        clip = d / f"{proj}001.mov"
        clip.write_bytes(b"x")
        os.utime(clip, (ahead, ahead))
        lane._refresh_future_dated(proj)
    assert lane.future_dated_report(["A", "B"])["count"] == 2
    assert lane.future_dated_report(["A"])["count"] == 1      # B unticked
    lane.forget_future_dated("A")
    assert lane.future_dated_report(["A", "B"]) is None
    import shutil
    shutil.rmtree(tmp_path / "local" / "B")
    assert lane.future_dated_report() is None                 # folder gone


def test_the_future_date_advice_no_longer_says_copy():
    line = tray._future_dated_line(
        {"future_dated": {"count": 1, "samples": ["A.mov"], "first_mtime": time.time()}})
    assert "re-import the card" not in line and "save it again" not in line
    assert "modified date reset to now" in line
    assert "only helps future recordings" in line
