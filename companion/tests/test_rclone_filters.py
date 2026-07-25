"""rclone filter-rule tests.

Two layers, per the task brief:
  1. Pure content assertions on the generated filter rule lists/files —
     always run, no rclone binary needed.
  2. Integration tests that actually invoke rclone (--dry-run and for-real)
     against local temp dirs (local->local "remotes", i.e. plain paths) to
     prove: Lane A picks video files outside Proxy/ only and respects
     --ignore-existing; Lane B pulls only Proxy/ contents (including
     nested ones) and propagates a rename via `rclone sync`. These are
     skipped (not failed) if rclone truly isn't available — see
     conftest.rclone_binary, which checks PATH first, then falls back to
     the test-only portable binary at companion/.tools/rclone.exe.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from ccsync_companion.sync.rclone_lane import (
    build_down_command,
    build_filter_rules_down,
    build_filter_rules_up,
    build_up_command,
    parse_json_log,
    rclone_available,
    write_filter_file,
)

# -- pure content assertions ------------------------------------------------


def test_filter_rules_up_excludes_proxy_first():
    rules = build_filter_rules_up()
    assert rules[0] == "- **/Proxy/**"
    assert rules[-1] == "- **"


def test_filter_rules_up_includes_every_video_ext():
    rules = build_filter_rules_up()
    for ext in [
        ".braw", ".mov", ".mp4", ".mxf", ".avi", ".mts", ".m2ts", ".mkv",
        ".r3d", ".crm", ".mpg", ".mpeg", ".wmv", ".webm", ".insv", ".360",
    ]:
        assert f"+ *{ext}" in rules


def test_filter_rules_down_allows_proxy_dir_and_contents_then_excludes_rest():
    rules = build_filter_rules_down()
    # Root-level (/Proxy/...) and nested (**/Proxy/...) forms are both
    # required: rclone's `**/` needs at least one leading path component,
    # so the nested rules alone miss a Proxy/ dir at the tree root.
    assert rules == [
        "+ /Proxy/", "+ /Proxy/**",
        "+ **/Proxy/", "+ **/Proxy/**",
        "- **",
    ]


def test_filter_rules_up_excludes_root_level_proxy():
    rules = build_filter_rules_up()
    assert "- /Proxy/**" in rules
    assert rules.index("- /Proxy/**") < rules.index("- **")


def test_write_filter_file_writes_one_rule_per_line(tmp_path):
    path = write_filter_file(["+ *.mov", "- **"], tmp_path / "filter.txt")
    assert path.read_text(encoding="utf-8") == "+ *.mov\n- **\n"


def test_build_up_command_shape(tmp_path):
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    cmd = build_up_command("rclone", "C:\\root", "nas", "Creators_Club", filter_file, transfers=8)
    assert cmd[0] == "rclone"
    assert cmd[1] == "copy"
    assert cmd[2] == "C:\\root"
    assert cmd[3] == "nas:Creators_Club"
    assert "--ignore-existing" in cmd
    assert "--min-age" in cmd and "30s" in cmd
    assert "--transfers" in cmd and "8" in cmd
    assert "--use-json-log" in cmd
    assert "--verbose" in cmd


def test_build_down_command_shape(tmp_path):
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    cmd = build_down_command("rclone", "C:\\root", "nas", "Creators_Club", filter_file, transfers=2)
    assert cmd[1] == "sync"
    assert cmd[2] == "nas:Creators_Club"
    assert cmd[3] == "C:\\root"
    assert "--ignore-existing" not in cmd  # lane B is server-authoritative, no skip-if-exists


# -- subpath (per-project) + --stats command building, pure -----------------


def test_build_up_command_with_subpath_joins_both_endpoints(tmp_path):
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    cmd = build_up_command(
        "rclone", "C:\\root", "nas", "Creators_Club", filter_file,
        subpath="Projects/2026/FF5/Energy Transition",
    )
    assert cmd[2] == str(Path("C:\\root") / "Projects/2026/FF5/Energy Transition")
    assert cmd[3] == "nas:Creators_Club/Projects/2026/FF5/Energy Transition"


def test_build_down_command_with_subpath_joins_both_endpoints(tmp_path):
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    cmd = build_down_command(
        "rclone", "C:\\root", "nas", "Creators_Club", filter_file,
        subpath="Projects/2026/FF5/Energy Transition",
    )
    assert cmd[2] == "nas:Creators_Club/Projects/2026/FF5/Energy Transition"
    assert cmd[3] == str(Path("C:\\root") / "Projects/2026/FF5/Energy Transition")


def test_build_up_command_subpath_no_double_slash_with_trailing_slash_root(tmp_path):
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    cmd = build_up_command(
        "rclone", "C:\\root", "nas", "Creators_Club/", filter_file,
        subpath="/Projects/2026/FF5/Energy Transition/",
    )
    assert cmd[3] == "nas:Creators_Club/Projects/2026/FF5/Energy Transition"
    assert "//" not in cmd[3].split(":", 1)[1]


def test_build_up_command_stats_interval_appends_flags(tmp_path):
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    cmd = build_up_command(
        "rclone", "C:\\root", "nas", "Creators_Club", filter_file, stats_interval="10s",
    )
    assert cmd[-4:] == ["--stats", "10s", "--stats-log-level", "NOTICE"]


def test_build_down_command_stats_interval_appends_flags(tmp_path):
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    cmd = build_down_command(
        "rclone", "C:\\root", "nas", "Creators_Club", filter_file, stats_interval="10s",
    )
    assert cmd[-4:] == ["--stats", "10s", "--stats-log-level", "NOTICE"]


def test_build_up_command_omitted_subpath_and_stats_unchanged(tmp_path):
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    old = build_up_command("rclone", "C:\\root", "nas", "Creators_Club", filter_file, transfers=8)
    new = build_up_command(
        "rclone", "C:\\root", "nas", "Creators_Club", filter_file, transfers=8,
        subpath=None, stats_interval=None,
    )
    assert old == new


def test_build_down_command_omitted_subpath_and_stats_unchanged(tmp_path):
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    old = build_down_command("rclone", "C:\\root", "nas", "Creators_Club", filter_file, transfers=2)
    new = build_down_command(
        "rclone", "C:\\root", "nas", "Creators_Club", filter_file, transfers=2,
        subpath=None, stats_interval=None,
    )
    assert old == new


def test_parse_json_log_counts_transfers_and_errors():
    text = (
        '{"level":"info","msg":"clip.mov: Copied (new)"}\n'
        '{"level":"error","msg":"something went wrong"}\n'
        "not json, should be skipped\n"
        '{"level":"info","msg":"unrelated notice"}\n'
    )
    result = parse_json_log(text)
    assert result.transferred == 1
    assert result.errors == ["something went wrong"]
    assert result.ok is False


def test_parse_json_log_ok_when_no_errors():
    text = '{"level":"info","msg":"clip.mov: Copied (new)"}\n'
    result = parse_json_log(text)
    assert result.ok is True


def test_rclone_available_missing_binary():
    available, msg = rclone_available("definitely-not-a-real-rclone-binary-xyz")
    assert available is False
    assert "not found" in msg


# -- integration: real rclone against local fixture dirs -------------------


@pytest.fixture
def fixture_tree(tmp_path):
    """A small project tree with video in and out of Proxy/, at multiple
    depths, plus a non-video file and a decoy top-level "Proxy-like" name
    that is NOT actually inside a Proxy dir."""
    src = tmp_path / "src"
    (src / "B-roll" / "Proxy").mkdir(parents=True)
    (src / "B-roll" / "Editor Added" / "alex").mkdir(parents=True)
    (src / "Interviewees" / "Jane" / "Proxy" / "Nested").mkdir(parents=True)
    (src / "Audio" / "Music").mkdir(parents=True)

    (src / "B-roll" / "Proxy" / "clip1.mov").write_text("proxy1")
    (src / "Interviewees" / "Jane" / "Proxy" / "Nested" / "clip2.mov").write_text("proxy2-nested")
    (src / "B-roll" / "Editor Added" / "alex" / "clip3.mov").write_text("original")
    (src / "Audio" / "Music" / "track.wav").write_text("music")
    (src / "Proxynotreal.mov").write_text("root file, name resembles Proxy but isn't inside one")
    (src / "B-roll" / "Editor Added" / "alex" / "notes.txt").write_text("not a video")
    # Root-level Proxy dir: rclone's `**/` does not match zero components,
    # so this case needs the explicit /Proxy/ rules.
    (src / "Proxy").mkdir()
    (src / "Proxy" / "clip_root.mov").write_text("proxy-at-root")

    # Lane A's real command uses --min-age 30s (file-stability wait) — back-
    # date every fixture file so freshly-created test files aren't skipped.
    old_time = time.time() - 3600
    for f in src.rglob("*"):
        if f.is_file():
            os.utime(f, (old_time, old_time))

    return src


def _run_dry(rclone_binary, cmd_extra):
    proc = subprocess.run(
        [rclone_binary] + cmd_extra + ["--dry-run", "--use-json-log"],
        capture_output=True, text=True, timeout=30,
    )
    return proc


def test_lane_a_dry_run_picks_only_video_outside_proxy(rclone_binary, fixture_tree, tmp_path):
    filter_file = write_filter_file(build_filter_rules_up(), tmp_path / "filter_up.txt")
    dst = tmp_path / "dst_up"
    cmd = build_up_command(rclone_binary, str(fixture_tree), None, str(dst), filter_file)
    # local->local: use a plain path instead of "remote:root" for the dest.
    cmd[3] = str(dst)
    proc = subprocess.run(cmd + ["--dry-run"], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr

    log_text = proc.stderr
    assert "clip3.mov" in log_text
    assert "Proxynotreal.mov" in log_text
    assert "clip1.mov" not in log_text
    assert "clip2.mov" not in log_text
    assert "clip_root.mov" not in log_text  # root-level Proxy/ must not upload
    assert "notes.txt" not in log_text


def test_lane_a_ignore_existing_never_clobbers(rclone_binary, fixture_tree, tmp_path):
    filter_file = write_filter_file(build_filter_rules_up(), tmp_path / "filter_up.txt")
    dst = tmp_path / "dst_up"
    cmd = build_up_command(rclone_binary, str(fixture_tree), None, str(dst), filter_file)
    cmd[3] = str(dst)

    # First real copy.
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    dest_file = dst / "B-roll" / "Editor Added" / "alex" / "clip3.mov"
    assert dest_file.read_text() == "original"

    # Modify the source (and backdate it past --min-age so this actually
    # exercises --ignore-existing rather than incidentally being skipped for
    # being "too new"), then copy again.
    modified_src = fixture_tree / "B-roll" / "Editor Added" / "alex" / "clip3.mov"
    modified_src.write_text("modified")
    old_time = time.time() - 3600
    os.utime(modified_src, (old_time, old_time))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert dest_file.read_text() == "original", "--ignore-existing must not clobber the NAS copy"


def test_lane_b_sync_pulls_only_proxy_contents_including_nested(rclone_binary, fixture_tree, tmp_path):
    filter_file = write_filter_file(build_filter_rules_down(), tmp_path / "filter_down.txt")
    dst = tmp_path / "dst_down"
    cmd = build_down_command(rclone_binary, str(dst), None, str(fixture_tree), filter_file)
    cmd[2] = str(fixture_tree)  # "remote" side (source) is a plain local path here
    cmd[3] = str(dst)

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr

    copied = sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file())
    assert copied == [
        "B-roll/Proxy/clip1.mov",
        "Interviewees/Jane/Proxy/Nested/clip2.mov",
        "Proxy/clip_root.mov",
    ]


def test_lane_b_sync_propagates_rename(rclone_binary, fixture_tree, tmp_path):
    filter_file = write_filter_file(build_filter_rules_down(), tmp_path / "filter_down.txt")
    dst = tmp_path / "dst_down"
    cmd = build_down_command(rclone_binary, str(dst), None, str(fixture_tree), filter_file)
    cmd[2] = str(fixture_tree)
    cmd[3] = str(dst)

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert (dst / "B-roll" / "Proxy" / "clip1.mov").is_file()

    # Server (source, since this is Lane B: NAS -> editor) renames the proxy.
    (fixture_tree / "B-roll" / "Proxy" / "clip1.mov").rename(
        fixture_tree / "B-roll" / "Proxy" / "clip1_renamed.mov"
    )

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert not (dst / "B-roll" / "Proxy" / "clip1.mov").exists(), "old name must be deleted locally"
    assert (dst / "B-roll" / "Proxy" / "clip1_renamed.mov").is_file(), "new name must appear locally"


# -- integration: per-project (subpath) selection + --stats JSON shape ------


@pytest.fixture
def two_project_tree(tmp_path):
    """Two project subtrees under Projects/, each with a video file outside
    Proxy/, so a subpath-scoped run can be proven to touch only one of
    them."""
    src = tmp_path / "src"
    proj1 = src / "Projects" / "2026" / "FF5" / "Energy Transition"
    proj2 = src / "Projects" / "2026" / "FF5" / "Other Project"
    proj1.mkdir(parents=True)
    proj2.mkdir(parents=True)
    (proj1 / "clip_proj1.mov").write_text("project one footage")
    (proj2 / "clip_proj2.mov").write_text("project two footage")

    old_time = time.time() - 3600
    for f in src.rglob("*"):
        if f.is_file():
            os.utime(f, (old_time, old_time))

    return src


def test_lane_a_dry_run_with_subpath_selects_only_that_project(rclone_binary, two_project_tree, tmp_path):
    filter_file = write_filter_file(build_filter_rules_up(), tmp_path / "filter_up.txt")
    dst = tmp_path / "dst_up"
    cmd = build_up_command(
        rclone_binary, str(two_project_tree), None, str(dst), filter_file,
        subpath="Projects/2026/FF5/Energy Transition",
    )
    # local->local: use a plain path instead of "remote:root" for the dest.
    cmd[3] = str(dst)
    proc = subprocess.run(cmd + ["--dry-run"], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr

    log_text = proc.stderr
    assert "clip_proj1.mov" in log_text
    assert "clip_proj2.mov" not in log_text


def test_rclone_json_log_stats_has_bytes_and_speed(rclone_binary, tmp_path):
    """Gate test for the --use-json-log stats shape a live-stats reader
    (RcloneLane's Popen-based runner) depends on: periodic "stats" records
    on stderr with numeric "bytes"/"speed" fields."""
    src = tmp_path / "src"
    src.mkdir()
    big_file = src / "big.bin"
    big_file.write_bytes(os.urandom(8 * 1024 * 1024))  # ~8 MB
    dst = tmp_path / "dst"

    cmd = [
        rclone_binary, "copy", str(src), str(dst),
        "--use-json-log", "--verbose",
        "--stats", "200ms", "--stats-log-level", "NOTICE",
        "--bwlimit", "10M",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr

    stats_records = []
    for line in proc.stderr.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        stats = record.get("stats")
        if isinstance(stats, dict):
            stats_records.append(stats)

    assert len(stats_records) >= 1, proc.stderr
    assert "bytes" in stats_records[0]
    assert "speed" in stats_records[0]
