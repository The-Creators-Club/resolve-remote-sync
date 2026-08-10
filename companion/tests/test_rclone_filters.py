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
import re
import subprocess
import time
from pathlib import Path

import pytest

from ccsync_companion.sync.rclone_lane import (
    APPLEDOUBLE_EXCLUDE_RULE,
    LANE_B_MIN_AGE_SECONDS,
    ExpressListError,
    RcloneTuning,
    build_down_command,
    build_express_command,
    build_filter_rules_down,
    build_filter_rules_up,
    build_up_command,
    parse_json_log,
    rclone_available,
    reset_rclone_available_cache,
    write_files_from_list,
    write_filter_file,
)


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    """rclone_available() caches successful probes process-wide now; no test
    may inherit another's cached answer."""
    reset_rclone_available_cache()
    yield
    reset_rclone_available_cache()

# -- pure content assertions ------------------------------------------------


def test_filter_rules_up_excludes_proxy_first():
    rules = build_filter_rules_up()
    # The AppleDouble exclude is ahead of it now (see the sidecar tests
    # below); the Proxy excludes still precede every `+ *<ext>` include.
    assert rules[0] == APPLEDOUBLE_EXCLUDE_RULE
    assert rules[1] == "- **/Proxy/**"
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
    # The trash exclude must come FIRST (rclone is first-match-wins): the
    # backup dir mirrors the source layout, so `.ccsync-trash/<ts>/Sub/
    # Proxy/x.mov` matches `**/Proxy/**` and would otherwise be re-deleted
    # every pass -- and rclone rejects a --backup-dir that overlaps the
    # destination unless the filter excludes it (AUDIT_2 DEL-2).
    # The in-progress excludes sit between the two for the same
    # first-match-wins reason: they must beat `+ **/Proxy/**`, or Resolve's
    # `.<name>.tmp` / `.<name>.lock` render sidecars get pulled down (and
    # re-pulled every pass, since the .tmp changes between them).
    assert rules == [
        "- ._*",
        "- /.ccsync-trash/**",
        "- *.tmp", "- *.lock", "- *.partial",
        "+ /Proxy/", "+ /Proxy/**",
        "+ **/Proxy/", "+ **/Proxy/**",
        "- **",
    ]
    assert rules.index("- *.tmp") < rules.index("+ **/Proxy/**")


def test_filter_rules_up_excludes_root_level_proxy():
    rules = build_filter_rules_up()
    assert "- /Proxy/**" in rules
    assert rules.index("- /Proxy/**") < rules.index("- **")


def test_both_lanes_exclude_appledouble_sidecars_before_anything_else():
    """KNOWN_BUGS 12: `._A001.mov` keeps the original's extension, so lane A's
    `+ *.mov` matched it and lane B's `+ **/Proxy/**` matched the proxy-side
    one. Both rule lists must refuse it, and the rule must be FIRST -- rclone
    is first-match-wins, so an include placed above it wins and the sidecar
    ships."""
    for rules in (build_filter_rules_up(), build_filter_rules_down()):
        assert rules[0] == APPLEDOUBLE_EXCLUDE_RULE == "- ._*"
        # No `+` rule may precede it. (Redundant with index 0 today; this is
        # what actually has to hold if the head of either list ever grows.)
        includes = [i for i, rule in enumerate(rules) if rule.startswith("+ ")]
        assert min(includes) > rules.index(APPLEDOUBLE_EXCLUDE_RULE)


def test_appledouble_exclude_stays_first_when_express_paths_are_excluded():
    """The express in-flight excludes used to own the head of lane A's list.
    They are still ahead of every include; the sidecar rule is ahead of them.
    (Order between two `-` rules is free -- both verdicts are "skip" -- so
    this pins the documented shape, not a behavioural difference.)"""
    rules = build_filter_rules_up(["B-roll/a.mov"])
    assert rules[0] == APPLEDOUBLE_EXCLUDE_RULE
    assert rules[1] == "- /B-roll/a.mov"


def test_appledouble_rule_carries_no_slash_so_it_matches_at_any_depth():
    """A pattern with no `/` matches the BASENAME anywhere in the tree (the
    same property IN_PROGRESS_EXCLUDE_RULES relies on), which is why one rule
    replaces both a root-level and a `**/` form. Proven against the real
    binary in test_*_appledouble_* below; asserted here so the shape cannot
    quietly change into an anchored pattern."""
    assert "/" not in APPLEDOUBLE_EXCLUDE_RULE


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
    # rclone filters are case-sensitive by default: without this, uppercase
    # camera extensions (CLIP.MOV) and a lowercase-cased "proxy/" dir slip
    # past build_filter_rules_up() entirely (verified live against a real
    # rclone binary -- see the integration tests below).
    assert "--ignore-case" in cmd
    # 120s, not 30s: mtime-preserving copies (Windows CopyFile, Explorer,
    # every card-ingest tool) satisfy --min-age 30s the instant the file
    # appears, so a 40 GB .braw gets read mid-write (AUDIT_2 L-14).
    assert "--min-age" in cmd and "120s" in cmd
    assert "--transfers" in cmd and "8" in cmd
    assert "--use-json-log" in cmd
    assert "--verbose" in cmd
    # Bounds on a peer that ACKs and then stalls (AUDIT_2 L-12).
    assert "--timeout" in cmd and "--contimeout" in cmd and "--retries-sleep" in cmd
    # No budget passed -> no --max-duration.
    assert "--max-duration" not in cmd


def test_build_down_command_shape(tmp_path):
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    cmd = build_down_command("rclone", "C:\\root", "nas", "Creators_Club", filter_file, transfers=2)
    assert cmd[1] == "sync"
    assert cmd[2] == "nas:Creators_Club"
    assert cmd[3] == "C:\\root"
    assert "--ignore-existing" not in cmd  # lane B is server-authoritative, no skip-if-exists
    assert "--ignore-case" in cmd  # same case-sensitivity gap as lane A
    # Blast-radius bound on the one verb in this system that removes local
    # files (AUDIT_2 §4.2 safety row).
    assert cmd[cmd.index("--max-delete") + 1] == "100"
    assert cmd[cmd.index("--max-delete-size") + 1] == "20G"
    # backup_dir is opt-in so consolidate.py's --dry-run keeps reporting
    # "Skipped delete" (not "Skipped move into backup dir") per object.
    assert "--backup-dir" not in cmd
    # Stability gate, on by default -- see LANE_B_MIN_AGE_SECONDS.
    assert cmd[cmd.index("--min-age") + 1] == "120s"


def test_lane_b_min_age_keeps_a_proxy_still_being_written_out_of_the_run(tmp_path):
    """The Blackmagic Proxy Generator writes each proxy AT ITS FINAL NAME and
    grows it in place (measured: 933 s for a 203 MB proxy). Lane B is a 120 s
    periodic sync, so without a gate it shipped the same growing file
    truncated ~7 times, re-downloading it from byte 0 each pass and sweeping
    every superseded partial into .ccsync-trash via --backup-dir."""
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("+ **/Proxy/**\n- **\n")
    cmd = build_down_command("rclone", "C:\\root", "nas", "Creators_Club", filter_file)

    assert "--min-age" in cmd
    # Must be a real gate, not a token one: lane B's own pass interval is
    # 120 s, so anything shorter still catches files mid-write.
    seconds = int(cmd[cmd.index("--min-age") + 1].rstrip("s"))
    assert seconds >= 120


def test_lane_b_min_age_is_configurable_and_can_be_disabled(tmp_path):
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")

    raised = build_down_command(
        "rclone", "C:\\root", "nas", "Creators_Club", filter_file, min_age_seconds=300,
    )
    assert raised[raised.index("--min-age") + 1] == "300s"

    off = build_down_command(
        "rclone", "C:\\root", "nas", "Creators_Club", filter_file, min_age_seconds=0,
    )
    assert "--min-age" not in off


def test_lane_b_min_age_seconds_reads_config():
    from ccsync_companion.sync.rclone_lane import LANE_B_MIN_AGE_SECONDS, lane_b_min_age_seconds

    assert lane_b_min_age_seconds(None) == LANE_B_MIN_AGE_SECONDS
    assert lane_b_min_age_seconds({}) == LANE_B_MIN_AGE_SECONDS
    assert lane_b_min_age_seconds({"lane_b_min_age_seconds": 300}) == 300
    assert lane_b_min_age_seconds({"lane_b_min_age_seconds": 0}) == 0
    # Garbage falls back to the default rather than disabling the gate, and a
    # negative value can never become an "everything is old enough" -0s.
    assert lane_b_min_age_seconds({"lane_b_min_age_seconds": "nonsense"}) == LANE_B_MIN_AGE_SECONDS
    assert lane_b_min_age_seconds({"lane_b_min_age_seconds": -5}) == 0


def test_lane_b_run_passes_the_configured_min_age(tmp_path):
    """The flag has to survive the RcloneLane -> build_down_command hop; the
    unit above would pass with the lane never wiring cfg through."""
    from ccsync_companion.sync.rclone_lane import DIRECTION_DOWN, RcloneLane

    lane = RcloneLane(
        DIRECTION_DOWN, str(tmp_path / "root"), "nas", "Creators_Club",
        state_dir=tmp_path / "state", cfg={"lane_b_min_age_seconds": 240},
    )
    cmd = lane._build_command()
    assert cmd[cmd.index("--min-age") + 1] == "240s"


def test_build_down_command_backup_dir_makes_deletes_recoverable(tmp_path):
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- /.ccsync-trash/**\n+ **/Proxy/**\n- **\n")
    cmd = build_down_command(
        "rclone", "C:\\root", "nas", "Creators_Club", filter_file,
        backup_dir="C:\\root\\.ccsync-trash\\20260725-120000",
    )
    assert cmd[cmd.index("--backup-dir") + 1] == "C:\\root\\.ccsync-trash\\20260725-120000"


def test_build_commands_add_max_duration_budget_with_soft_cutoff(tmp_path):
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    for build in (build_up_command, build_down_command):
        cmd = build(
            "rclone", "C:\\root", "nas", "Creators_Club", filter_file,
            max_duration_seconds=600,
        )
        assert cmd[cmd.index("--max-duration") + 1] == "600s"
        # SOFT, not the HARD default: SFTP uploads don't resume, so killing
        # a 40 GB original at 39 GB restarts it from byte 0 next pass.
        assert cmd[cmd.index("--cutoff-mode") + 1] == "SOFT"


# -- transport tuning (AUDIT_2 P1/P2/§4.2) ----------------------------------


def _flag_value(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def test_lane_a_carries_the_sftp_window_flags_by_default(tmp_path):
    """P1, the headline finding: rclone has no multi-thread UPLOAD for sftp,
    so one file rides one stream whose in-flight window is
    chunk_size x concurrency. The unset default is 32Ki x 64 = 2 MiB, i.e.
    ~14 MB/s at 150 ms RTT -- the ~60 mb/s class this project exists to
    beat. --transfers multiplies across FILES and cannot help the single
    40 GB BRAW that is lane A's whole purpose."""
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    cmd = build_up_command("rclone", "C:\\root", "nas", "Creators_Club", filter_file)

    assert _flag_value(cmd, "--sftp-chunk-size") == "255Ki"
    # 64, not 256: memory is chunk x concurrency x streams.
    assert _flag_value(cmd, "--sftp-concurrency") == "64"
    # Caps rclone's SSH pool so wide checkers can't trip sshd MaxStartups.
    assert _flag_value(cmd, "--sftp-connections") == "16"
    assert _flag_value(cmd, "--checkers") == "16"


def test_both_lanes_skip_the_post_copy_hash_reread(tmp_path):
    """P2: with shell_type=unix the SFTP backend gets MD5 by shelling
    `md5sum <path>` on the NAS, so the NAS re-reads every file it just
    received. --ignore-checksum (NOT --sftp-disable-hashcheck) removes the
    re-read while keeping hash-based comparison available."""
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    for build in (build_up_command, build_down_command):
        cmd = build("rclone", "C:\\root", "nas", "Creators_Club", filter_file)
        assert "--ignore-checksum" in cmd
        assert "--sftp-disable-hashcheck" not in cmd


def test_lane_order_by_puts_newest_up_and_smallest_down(tmp_path):
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    up = build_up_command("rclone", "C:\\root", "nas", "Creators_Club", filter_file)
    down = build_down_command("rclone", "C:\\root", "nas", "Creators_Club", filter_file)
    # The clip the team is waiting on goes before the archive backlog...
    assert _flag_value(up, "--order-by") == "modtime,descending"
    # ...and a cold project yields many usable proxies sooner.
    assert _flag_value(down, "--order-by") == "size,ascending"


def test_measured_no_ops_and_pessimisations_are_never_added(tmp_path):
    """§4.2 measured these against the bundled binary: --fast-list and
    --use-server-modtime are no-ops for SFTP, and --no-traverse UNPAIRED is
    a pessimisation on a full pass (61 dir-modtime setstats vs 2)."""
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    for build in (build_up_command, build_down_command):
        cmd = build("rclone", "C:\\root", "nas", "Creators_Club", filter_file)
        assert "--fast-list" not in cmd
        assert "--use-server-modtime" not in cmd
        assert "--no-traverse" not in cmd


def test_every_tuning_flag_can_be_turned_off_from_config(tmp_path):
    """C-5: bench results have to be applyable, and every knob has to be
    revertible without a code change."""
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    tuning = RcloneTuning.from_cfg({
        "sftp_chunk_size": "",
        "sftp_concurrency": 0,
        "sftp_connections": 0,
        "checkers": 0,
        "rclone_ignore_checksum": False,
        "order_by_up": "",
        "order_by_down": "",
    })
    for build in (build_up_command, build_down_command):
        cmd = build(
            "rclone", "C:\\root", "nas", "Creators_Club", filter_file, tuning=tuning
        )
        for flag in (
            "--sftp-chunk-size", "--sftp-concurrency", "--sftp-connections",
            "--checkers", "--ignore-checksum", "--order-by",
        ):
            assert flag not in cmd, flag
        # ...and the safety flags are untouched by any of it.
        assert "--ignore-existing" in cmd or build is build_down_command


def test_tuning_from_cfg_overrides_individual_values(tmp_path):
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    tuning = RcloneTuning.from_cfg({"sftp_chunk_size": "128Ki", "checkers": 8})
    cmd = build_up_command(
        "rclone", "C:\\root", "nas", "Creators_Club", filter_file, tuning=tuning
    )
    # §4.2's documented fallback if a server errors on 255Ki.
    assert _flag_value(cmd, "--sftp-chunk-size") == "128Ki"
    assert _flag_value(cmd, "--checkers") == "8"
    # Untouched keys keep their defaults.
    assert _flag_value(cmd, "--sftp-concurrency") == "64"


def test_tuning_from_cfg_survives_a_junk_value(tmp_path):
    tuning = RcloneTuning.from_cfg({"checkers": "lots", "sftp_concurrency": None})
    assert tuning.checkers == 16
    assert tuning.sftp_concurrency == 64


def test_ignore_existing_is_never_dropped_for_speed(tmp_path):
    """Standing rule for the whole tier: no speed change may widen a
    deletion window. --ignore-existing is what keeps lane A from ever
    rewriting a NAS-side file, so no tuning path may remove it."""
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    for tuning in (None, RcloneTuning.from_cfg({"rclone_ignore_checksum": False})):
        cmd = build_up_command(
            "rclone", "C:\\root", "nas", "Creators_Club", filter_file, tuning=tuning
        )
        assert "--ignore-existing" in cmd


# -- filter-file integrity (AUDIT_2 DEL-2) ----------------------------------


def test_write_filter_file_is_atomic_and_leaves_no_temp_file(tmp_path):
    from ccsync_companion.sync.rclone_lane import build_filter_rules_down

    path = tmp_path / "state" / "filter_down.txt"
    write_filter_file(build_filter_rules_down(), path)
    write_filter_file(build_filter_rules_down(), path)  # rewrite, as every run does

    # Path.write_text truncates first, leaving a 0-byte window another
    # process's rclone could read as "no filter" -- os.replace has no such
    # window, and must not leave the tmp file behind either.
    assert path.read_text(encoding="utf-8").splitlines()[-1] == "- **"
    assert [p.name for p in path.parent.iterdir()] == ["filter_down.txt"]


def test_build_commands_refuse_an_empty_filter_file(tmp_path):
    from ccsync_companion.sync.rclone_lane import FilterFileError

    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    for build in (build_up_command, build_down_command):
        with pytest.raises(FilterFileError):
            build("rclone", "C:\\root", "nas", "Creators_Club", empty)


def test_build_commands_refuse_a_truncated_filter_file(tmp_path):
    """A half-written filter (the cross-process race in DEL-2) whose final
    `- **` never landed would let lane B sync -- and therefore delete --
    far outside the Proxy set."""
    from ccsync_companion.sync.rclone_lane import FilterFileError

    truncated = tmp_path / "half.txt"
    truncated.write_text("- /.ccsync-trash/**\n+ /Proxy/\n", encoding="utf-8")
    with pytest.raises(FilterFileError):
        build_down_command("rclone", "C:\\root", "nas", "Creators_Club", truncated)


def test_build_commands_refuse_a_missing_filter_file(tmp_path):
    from ccsync_companion.sync.rclone_lane import FilterFileError

    with pytest.raises(FilterFileError):
        build_down_command("rclone", "C:\\root", "nas", "Creators_Club", tmp_path / "gone.txt")


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
    # A leading "/" on subpath must NOT discard local_root: pathlib treats a
    # rooted component as absolute, so an unstripped join would silently
    # collapse to just the subpath (reachable via consolidate.py, not the
    # sequencer's own PROJECTS_PREFIX-guaranteed inputs).
    assert cmd[2] == str(Path("C:\\root") / "Projects/2026/FF5/Energy Transition")
    assert cmd[2] != "/Projects/2026/FF5/Energy Transition/"


def test_build_down_command_subpath_no_double_slash_with_trailing_slash_root(tmp_path):
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    cmd = build_down_command(
        "rclone", "C:\\root", "nas", "Creators_Club/", filter_file,
        subpath="/Projects/2026/FF5/Energy Transition/",
    )
    assert cmd[2] == "nas:Creators_Club/Projects/2026/FF5/Energy Transition"
    assert "//" not in cmd[2].split(":", 1)[1]
    assert cmd[3] == str(Path("C:\\root") / "Projects/2026/FF5/Energy Transition")
    assert cmd[3] != "/Projects/2026/FF5/Energy Transition/"


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


class _FakeCompletedProcess:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def test_rclone_available_uses_utf8_replace_decoding_and_no_console_window(monkeypatch, tmp_path):
    """rclone logs UTF-8; the default cp1252 `text=True` decoding raises on
    non-ASCII bytes (S-6). Also asserts CREATE_NO_WINDOW is passed on
    Windows so a windowed build doesn't flash a console per probe."""
    from ccsync_companion.sync import rclone_lane as rl

    fake_exe = tmp_path / "rclone.exe"
    fake_exe.write_text("stub")

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(rl.subprocess, "run", fake_run)

    available, _msg = rl.rclone_available(str(fake_exe))

    assert available is True
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    if rl.sys.platform == "win32":
        assert captured["creationflags"] == rl.subprocess.CREATE_NO_WINDOW
    else:
        assert captured["creationflags"] == 0


def test_run_lsf_uses_utf8_replace_decoding_and_no_console_window(monkeypatch):
    from ccsync_companion.sync import rclone_lane as rl

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(rl.subprocess, "run", fake_run)

    rl._run_lsf(["rclone", "lsf"], timeout=5.0)

    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    if rl.sys.platform == "win32":
        assert captured["creationflags"] == rl.subprocess.CREATE_NO_WINDOW
    else:
        assert captured["creationflags"] == 0


# -- what an rclone failure looks like in the log (KNOWN_BUGS 14) ----------

# Verbatim shape, captured from the bundled rclone 1.74.4 by pointing it at an
# SFTP host that refuses the key. The NOTICE is unconditional on every SFTP
# remote and ~260 characters once the remote's real name is in it -- so the
# old `stderr[:300]` spent almost its whole budget on the one line that says
# nothing, and cut the CRITICAL off before its reason. Live cost 2026-08-05:
# lanes A and B were both stopped and the log said only "Failed to create file
# system for".
_SFTP_NOTICE = (
    "2026/08/05 12:00:00 NOTICE: creators_club_sftp{a1B2c}: No host key "
    "validation is being performed. Set known_hosts_file to enable it. "
    "See: https://rclone.org/sftp/#host-key-validation"
)
_SFTP_CRITICAL = (
    '2026/08/05 12:00:11 CRITICAL: Failed to create file system for '
    '"creators_club_sftp:/mnt/pool/Creators_Club/Projects": NewFs: couldn\'t '
    "connect SSH: ssh: handshake failed: ssh: unable to authenticate, "
    "attempted methods [none publickey], no supported methods remain"
)


def test_stderr_for_log_keeps_the_real_error_not_the_host_key_notice():
    from ccsync_companion.sync.rclone_lane import _stderr_for_log

    logged = _stderr_for_log(f"{_SFTP_NOTICE}\n{_SFTP_CRITICAL}\n")

    # The reason, not just the headline -- both halves of the sentence.
    assert "unable to authenticate" in logged
    assert "creators_club_sftp:/mnt/pool/Creators_Club/Projects" in logged
    assert "No host key validation" not in logged
    # The regression this replaces: the head of the raw stream is the notice.
    assert "unable to authenticate" not in f"{_SFTP_NOTICE}\n{_SFTP_CRITICAL}"[:300]


def test_stderr_for_log_takes_the_tail_when_the_error_is_long():
    from ccsync_companion.sync.rclone_lane import _stderr_for_log

    logged = _stderr_for_log("x" * 500 + "the actual reason")

    assert len(logged) == 300
    assert logged.endswith("the actual reason")


def test_stderr_for_log_falls_back_to_the_notices_rather_than_logging_nothing():
    """A stream that is ALL notices must not log an empty string -- "the run
    failed, no text" is the state this fix exists to end."""
    from ccsync_companion.sync.rclone_lane import _stderr_for_log

    logged = _stderr_for_log(_SFTP_NOTICE)

    assert "No host key validation" in logged


def test_stderr_for_log_handles_empty_and_none():
    from ccsync_companion.sync.rclone_lane import _stderr_for_log

    assert _stderr_for_log(None) == ""
    assert _stderr_for_log("") == ""
    assert _stderr_for_log("   \n  ") == ""


def test_run_lsf_logs_the_real_error_when_rclone_exits_nonzero(monkeypatch, caplog):
    """End of the wire: the log line at the lsf call site, which is where the
    truncation was found."""
    from ccsync_companion.sync import rclone_lane as rl

    proc = _FakeCompletedProcess(1)
    proc.stderr = f"{_SFTP_NOTICE}\n{_SFTP_CRITICAL}\n"
    monkeypatch.setattr(rl.subprocess, "run", lambda cmd, **kwargs: proc)

    with caplog.at_level("WARNING", logger="ccsync"):
        assert rl._run_lsf(["rclone", "lsf", "remote:"], timeout=5.0) is None

    text = caplog.text
    assert "unable to authenticate" in text, (
        "rclone's real error did not reach the log"
    )
    assert "No host key validation" not in text


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


def _age_past_the_lane_b_gate(*roots: Path) -> None:
    """Backdate every file under `roots` past lane B's --min-age.

    The end-to-end tests below build the REAL lane B argv, which carries
    --min-age (LANE_B_MIN_AGE_SECONDS). A fixture written a millisecond ago
    is precisely what that flag exists to skip, so without this the run
    becomes a no-op and the assertions below would pass vacuously -- or, for
    the delete/trash tests, fail outright."""
    old = time.time() - (LANE_B_MIN_AGE_SECONDS * 2)
    for root in roots:
        for path in root.rglob("*"):
            if path.is_file():
                os.utime(path, (old, old))


def test_lane_b_backup_dir_makes_every_delete_recoverable(rclone_binary, tmp_path):
    """AUDIT_2 DEL-2, against the real binary.

    Lane B is `rclone sync`: any local proxy the NAS has never seen is
    deleted, and the directories that held it are pruned. With --backup-dir
    every one of those becomes a MOVE into <local_root>/.ccsync-trash/<ts>.

    This also proves the trash exclude in build_filter_rules_down() is
    load-bearing rather than decorative: the backup dir sits INSIDE the sync
    destination (it has to, to stay on the same filesystem), and rclone
    refuses an overlapping --backup-dir unless the filter excludes it.
    """
    src = tmp_path / "nas"
    dst = tmp_path / "local"
    (src / "Sub" / "Proxy").mkdir(parents=True)
    (src / "Sub" / "Proxy" / "shared.mov").write_text("on the nas")
    (dst / "Sub" / "Proxy").mkdir(parents=True)
    (dst / "Sub" / "Proxy" / "shared.mov").write_text("on the nas")
    (dst / "Sub" / "Proxy" / "locally_rendered.mov").write_text("hours of BPG GPU time")
    (dst / "Local" / "Proxy").mkdir(parents=True)
    (dst / "Local" / "Proxy" / "orphan.mov").write_text("also local-only")
    (dst / "original_master.braw").write_text("camera original, not yet uploaded")

    _age_past_the_lane_b_gate(src, dst)

    filter_file = write_filter_file(build_filter_rules_down(), tmp_path / "filter_down.txt")
    trash = dst / ".ccsync-trash" / "20260725-120000"
    cmd = build_down_command(
        rclone_binary, str(dst), None, str(src), filter_file, backup_dir=str(trash),
    )
    cmd[2] = str(src)
    cmd[3] = str(dst)

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr

    # Neither local-only proxy is gone -- both are recoverable, at the same
    # relative path, byte-identical.
    assert (trash / "Sub" / "Proxy" / "locally_rendered.mov").read_text() == (
        "hours of BPG GPU time"
    )
    assert (trash / "Local" / "Proxy" / "orphan.mov").read_text() == "also local-only"
    assert not (dst / "Sub" / "Proxy" / "locally_rendered.mov").exists()
    # Lane B's containment is unchanged: non-proxy media is never touched.
    assert (dst / "original_master.braw").read_text() == "camera original, not yet uploaded"
    assert (dst / "Sub" / "Proxy" / "shared.mov").is_file()


def test_lane_b_does_not_ship_a_proxy_that_is_still_being_written(rclone_binary, tmp_path):
    """The actual regression, against real rclone rather than the argv.

    Simulates what the Blackmagic Proxy Generator leaves on the NAS: a file
    at its FINAL name, currently a fraction of its eventual size. The pass
    must skip it entirely (an editor with no proxy is strictly better off
    than one holding a truncated .mov whose moov index doesn't exist yet),
    and must copy it once it stops changing."""
    src = tmp_path / "nas"
    dst = tmp_path / "local"
    (src / "Sub" / "Proxy").mkdir(parents=True)
    dst.mkdir()
    growing = src / "Sub" / "Proxy" / "half_written.mov"
    growing.write_text("ftyp...mdat...")  # no moov yet -- BPG writes it last

    filter_file = write_filter_file(build_filter_rules_down(), tmp_path / "filter_down.txt")

    def _run() -> None:
        cmd = build_down_command(rclone_binary, str(dst), None, str(src), filter_file)
        cmd[2] = str(src)
        cmd[3] = str(dst)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr

    _run()
    assert not (dst / "Sub" / "Proxy" / "half_written.mov").exists(), (
        "lane B downloaded a proxy that was still being written"
    )

    # Generation finishes: the file stops changing and ages past the gate.
    growing.write_text("ftyp...mdat...moov")
    _age_past_the_lane_b_gate(src)
    _run()
    assert (dst / "Sub" / "Proxy" / "half_written.mov").read_text() == "ftyp...mdat...moov"


def test_lane_b_never_pulls_resolves_in_progress_proxy_sidecars(rclone_binary, tmp_path):
    """Resolve's proxy-generation temporaries must not cross the wire.

    While generating a proxy, Resolve writes `.<name>.tmp` (the growing
    output) and a 0-byte `.<name>.lock` beside the finished files. Lane B's
    include is `**/Proxy/**` -- every byte under the directory -- so both
    matched, and because the .tmp changes between passes it was re-fetched
    every single time. Seen live on 2026-08-04: a 2.3 GB `.Z6B_4317-004.tmp`
    downloaded to an editor on three consecutive passes. Resolve renames it
    away on completion, so none of those bytes could ever be used.
    """
    src = tmp_path / "nas"
    dst = tmp_path / "local"
    proxy = src / "Sub" / "Proxy"
    proxy.mkdir(parents=True)
    dst.mkdir()

    (proxy / "finished.mov").write_text("a real proxy")
    (proxy / ".Z6B_4317-004.tmp").write_text("2.3 GB of in-flight render, pretend")
    (proxy / ".Z6B_4317-004.lock").write_text("")
    (proxy / "half.partial").write_text("rclone's own half-written marker")
    _age_past_the_lane_b_gate(src)

    filter_file = write_filter_file(build_filter_rules_down(), tmp_path / "filter_down.txt")
    cmd = build_down_command(rclone_binary, str(dst), None, str(src), filter_file)
    cmd[2] = str(src)
    cmd[3] = str(dst)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr

    landed = sorted(p.name for p in (dst / "Sub" / "Proxy").iterdir())
    assert landed == ["finished.mov"], f"lane B pulled in-progress sidecars: {landed}"


def test_lane_a_never_uploads_a_macos_appledouble_sidecar(rclone_binary, tmp_path):
    """KNOWN_BUGS 12, against the real binary rather than the rule list.

    On exFAT/FAT32/SMB -- every external SSD this deployment runs on -- macOS
    writes `._<original>` beside each file to hold the xattrs the filesystem
    cannot. The sidecar KEEPS the extension, so `+ *.mov` matched it and a Mac
    editor published a junk file beside every clip into the shared tree.
    Sidecars at the root and at depth, since one no-slash rule covers both.
    """
    src = tmp_path / "local"
    dst = tmp_path / "nas"
    (src / "B-roll").mkdir(parents=True)
    (src / "A001.mov").write_text("camera original")
    (src / "._A001.mov").write_text("resource fork junk")
    (src / "B-roll" / "b.mov").write_text("nested original")
    (src / "B-roll" / "._b.mov").write_text("nested resource fork junk")
    # Lane A carries --min-age (LANE_A_MIN_AGE) -- backdate or the run is a
    # no-op and the assertion below passes vacuously.
    old = time.time() - 3600
    for path in src.rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))

    filter_file = write_filter_file(build_filter_rules_up(), tmp_path / "filter_up.txt")
    cmd = build_up_command(rclone_binary, str(src), None, str(dst), filter_file)
    cmd[3] = str(dst)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr

    landed = sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file())
    assert landed == ["A001.mov", "B-roll/b.mov"], (
        f"lane A uploaded AppleDouble sidecars: {landed}"
    )


def test_lane_b_never_downloads_a_macos_appledouble_sidecar(rclone_binary, tmp_path):
    """The other direction, and the worse one: lane B's include is
    `**/Proxy/**` -- every byte under the directory -- so a sidecar the NAS
    already holds was redistributed to EVERY editor, Windows ones included."""
    src = tmp_path / "nas"
    dst = tmp_path / "local"
    proxy = src / "Sub" / "Proxy"
    proxy.mkdir(parents=True)
    dst.mkdir()
    (proxy / "p.mov").write_text("a real proxy")
    (proxy / "._p.mov").write_text("resource fork junk")
    # Root-level Proxy/ too: it is matched by a different include rule.
    (src / "Proxy").mkdir()
    (src / "Proxy" / "root.mov").write_text("a real root proxy")
    (src / "Proxy" / "._root.mov").write_text("resource fork junk")
    _age_past_the_lane_b_gate(src)

    filter_file = write_filter_file(build_filter_rules_down(), tmp_path / "filter_down.txt")
    cmd = build_down_command(rclone_binary, str(dst), None, str(src), filter_file)
    cmd[2] = str(src)
    cmd[3] = str(dst)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr

    landed = sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file())
    assert landed == ["Proxy/root.mov", "Sub/Proxy/p.mov"], (
        f"lane B downloaded AppleDouble sidecars: {landed}"
    )


def test_lane_b_second_pass_does_not_re_delete_the_trash(rclone_binary, tmp_path):
    """The backup dir mirrors the source layout, so `.ccsync-trash/<ts>/Sub/
    Proxy/x.mov` matches `**/Proxy/**`. Without the exclude rule the next
    pass would delete the trash it just made (or rclone would refuse the run
    outright on the overlap check)."""
    src = tmp_path / "nas"
    dst = tmp_path / "local"
    src.mkdir()
    (dst / "Sub" / "Proxy").mkdir(parents=True)
    (dst / "Sub" / "Proxy" / "doomed.mov").write_text("local only")
    _age_past_the_lane_b_gate(src, dst)

    filter_file = write_filter_file(build_filter_rules_down(), tmp_path / "filter_down.txt")
    for stamp in ("20260725-120000", "20260725-121000"):
        cmd = build_down_command(
            rclone_binary, str(dst), None, str(src), filter_file,
            backup_dir=str(dst / ".ccsync-trash" / stamp),
        )
        cmd[2] = str(src)
        cmd[3] = str(dst)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr

    recovered = dst / ".ccsync-trash" / "20260725-120000" / "Sub" / "Proxy" / "doomed.mov"
    assert recovered.read_text() == "local only", "the trash must survive later passes"


def test_rclone_lane_run_once_puts_deletes_in_the_trash_end_to_end(rclone_binary, tmp_path):
    """The whole DEL-2 chain through RcloneLane itself, against real rclone:
    _ensure_filter_file -> validate -> _backup_dir -> build_down_command ->
    Popen. Proves the wiring, not just the argv builder."""
    from ccsync_companion.sync.rclone_lane import DIRECTION_DOWN, RcloneLane

    local_root = tmp_path / "local"
    nas = tmp_path / "nas"
    subpath = "Projects/2026/CCT/Season 1"
    (nas / subpath / "Proxy").mkdir(parents=True)
    (local_root / subpath / "Proxy").mkdir(parents=True)
    (local_root / subpath / "Proxy" / "local_only.mov").write_text("hours of GPU time")
    (local_root / subpath / "master.braw").write_text("camera original")
    _age_past_the_lane_b_gate(local_root, nas)

    lane = RcloneLane(
        direction=DIRECTION_DOWN,
        local_root=str(local_root),
        remote="nas",
        remote_root=str(nas),
        rclone_path=rclone_binary,
        state_dir=tmp_path / "state",
    )
    _make_source_a_plain_local_path(lane)
    status = lane.run_once(subpath=subpath)
    assert status.state == "idle", status.last_error
    # UX-14: the lane must not keep wearing the project after the run.
    assert status.current_project is None

    trash_roots = sorted((local_root / ".ccsync-trash").iterdir())
    assert len(trash_roots) == 1, "one timestamped trash dir per run"
    recovered = trash_roots[0] / subpath / "Proxy" / "local_only.mov"
    assert recovered.read_text() == "hours of GPU time"
    assert not (local_root / subpath / "Proxy" / "local_only.mov").exists()
    assert (local_root / subpath / "master.braw").read_text() == "camera original"


def test_rclone_lane_refuses_to_run_with_a_truncated_filter_file(rclone_binary, tmp_path):
    """The cross-process race in DEL-2: another companion truncated the
    shared filter file. Running anyway is `rclone sync` with no filter, which
    deletes every local file the NAS lacks -- including camera originals
    still queued for lane A."""
    from ccsync_companion.sync.rclone_lane import DIRECTION_DOWN, RcloneLane

    local_root = tmp_path / "local"
    nas = tmp_path / "nas"
    nas.mkdir()
    (local_root / "Proxy").mkdir(parents=True)
    (local_root / "Proxy" / "keep.mov").write_text("still here")
    (local_root / "master.braw").write_text("camera original")

    lane = RcloneLane(
        direction=DIRECTION_DOWN,
        local_root=str(local_root),
        remote="nas",
        remote_root=str(nas),
        rclone_path=rclone_binary,
        state_dir=tmp_path / "state",
    )
    # Truncate the filter file after _ensure_filter_file would write it, the
    # way another process's non-atomic write_text used to.
    lane._ensure_filter_file = lambda: _truncated(lane._filter_file)

    status = lane.run_once()
    assert status.state == "error"
    assert "filter file is empty" in status.last_error
    # Nothing ran, so nothing was deleted.
    assert (local_root / "Proxy" / "keep.mov").is_file()
    assert (local_root / "master.braw").is_file()


def _truncated(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def _make_source_a_plain_local_path(lane) -> None:
    """local->local stand-in for the SFTP remote: strip the "nas:" prefix off
    the lane's source argument, exactly as the argv-level tests above do."""
    original = lane._build_command

    def patched(*args, **kwargs):
        cmd = original(*args, **kwargs)
        cmd[2] = cmd[2].split(":", 1)[1]
        return cmd

    lane._build_command = patched


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


# -- integration: the real binary accepts (and honours) the tuning ----------


def test_real_rclone_accepts_the_full_tuned_lane_argv(rclone_binary, fixture_tree, tmp_path):
    """Flags are only worth adding if the shipped binary takes them. Runs
    both lanes' complete production argv, tuning included, against local
    fixture dirs (backend flags are registered globally, so an unknown or
    mis-typed one fails here regardless of backend)."""
    up_filter = write_filter_file(build_filter_rules_up(), tmp_path / "filter_up.txt")
    dst = tmp_path / "dst_up"
    cmd = build_up_command(rclone_binary, str(fixture_tree), None, str(dst), up_filter)
    cmd[3] = str(dst)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "Unknown flag" not in proc.stderr and "unknown flag" not in proc.stderr

    down_filter = write_filter_file(build_filter_rules_down(), tmp_path / "filter_down.txt")
    down_dst = tmp_path / "dst_down"
    cmd = build_down_command(rclone_binary, str(down_dst), None, str(fixture_tree), down_filter)
    cmd[2] = str(fixture_tree)
    cmd[3] = str(down_dst)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "unknown flag" not in proc.stderr


def test_ignore_checksum_really_removes_the_post_copy_hash_pass(rclone_binary, tmp_path):
    """P2's mechanism, measured rather than read: rclone verifies size AND
    hash after every transfer when a common hash exists, and logs
    `<file>: md5 = ... OK`. Over SFTP with shell_type=unix that hash is a
    `md5sum <path>` on the NAS -- a full re-read of the file it just
    received. --ignore-checksum makes the line, and the re-read, disappear."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "big.mov").write_bytes(os.urandom(256 * 1024))

    baseline = subprocess.run(
        [rclone_binary, "copy", str(src), str(tmp_path / "d1"), "-vv"],
        capture_output=True, text=True, timeout=60,
    )
    assert baseline.returncode == 0, baseline.stderr
    assert "md5 = " in baseline.stderr, "fixture invalid: no hash pass to remove"

    tuned = subprocess.run(
        [rclone_binary, "copy", str(src), str(tmp_path / "d2"), "-vv", "--ignore-checksum"],
        capture_output=True, text=True, timeout=60,
    )
    assert tuned.returncode == 0, tuned.stderr
    assert "md5 = " not in tuned.stderr


def test_rclone_available_caches_successful_probes(monkeypatch, tmp_path):
    """§4.2's last row: run_once() spawned `rclone version` on EVERY call --
    ~2N process spawns per pass to re-learn that the binary that was there
    200 ms ago is still there."""
    from ccsync_companion.sync import rclone_lane as rl

    fake_exe = tmp_path / "rclone.exe"
    fake_exe.write_text("stub")
    spawns = []

    def fake_run(cmd, **kwargs):
        spawns.append(cmd)
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(rl.subprocess, "run", fake_run)

    for _ in range(5):
        available, msg = rl.rclone_available(str(fake_exe))
        assert available is True
    assert len(spawns) == 1

    # use_cache=False is the escape hatch, and reset re-arms the probe.
    rl.rclone_available(str(fake_exe), use_cache=False)
    assert len(spawns) == 2
    rl.reset_rclone_available_cache()
    rl.rclone_available(str(fake_exe))
    assert len(spawns) == 3


def test_rclone_available_never_caches_a_failure(monkeypatch, tmp_path):
    """A missing or broken binary must be re-probed every time, so the lane
    recovers the instant it is installed/repaired instead of staying red for
    the cache TTL."""
    from ccsync_companion.sync import rclone_lane as rl

    missing = tmp_path / "not-there.exe"
    for _ in range(3):
        available, msg = rl.rclone_available(str(missing))
        assert available is False and "not found" in msg


# -- integration: the EXPRESS argv against the real binary (AUDIT_2 C-2) ----
#
# These pin down the three things measured against the bundled rclone 1.74.4
# that shaped build_express_command: filter flags are rejected outright with
# --files-from-raw, a blank list line is read as the root directory, and a
# backslash-separated entry is a silent no-op.


def _express_cmd(rclone_binary, src: Path, dst: Path, list_file: Path) -> list[str]:
    cmd = build_express_command(rclone_binary, str(src), None, str(dst), list_file)
    cmd[3] = str(dst)  # local->local: plain path instead of "remote:root"
    return cmd


def test_express_uploads_only_the_listed_paths_including_non_ascii(
    rclone_binary, fixture_tree, tmp_path
):
    """1 stat + 1 upload instead of a full-tree traverse -- and a non-ASCII
    filename has to survive, since the audit's worst finding was a
    non-ASCII decode bug."""
    non_ascii = "café 日本語.braw"
    target = fixture_tree / "B-roll" / "Editor Added" / "alex" / non_ascii
    target.write_bytes(b"c" * 2048)
    old = time.time() - 3600
    os.utime(target, (old, old))

    list_file = write_files_from_list(
        [
            f"B-roll/Editor Added/alex/{non_ascii}",
            "B-roll/Editor Added/alex/clip3.mov",
            "B-roll/Editor Added/alex/DELETED-BEFORE-THE-RUN.mov",  # no longer exists
        ],
        tmp_path / "state" / "express.txt",
    )
    dst = tmp_path / "dst_express"
    proc = subprocess.run(
        _express_cmd(rclone_binary, fixture_tree, dst, list_file),
        capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace",
    )
    # A path that vanished between the watchdog event and the run is NOT an
    # error: rclone ignores it and still exits 0 (measured).
    assert proc.returncode == 0, proc.stderr

    assert (dst / "B-roll" / "Editor Added" / "alex" / non_ascii).read_bytes() == b"c" * 2048
    assert (dst / "B-roll" / "Editor Added" / "alex" / "clip3.mov").exists()
    # Nothing else came along for the ride -- that is the whole point.
    assert not (dst / "Proxynotreal.mov").exists()
    assert not (dst / "Audio").exists()
    # ...and --no-update-dir-modtime kept it off the destination's dirs
    # (unpaired --no-traverse touched all 61 in the audit's fixture).
    assert "set directory modification time" not in proc.stderr


def test_express_ignore_existing_never_clobbers_the_nas_copy(
    rclone_binary, fixture_tree, tmp_path
):
    list_file = write_files_from_list(
        ["B-roll/Editor Added/alex/clip3.mov"], tmp_path / "state" / "express.txt"
    )
    dst = tmp_path / "dst_express"
    cmd = _express_cmd(rclone_binary, fixture_tree, dst, list_file)
    assert subprocess.run(cmd, capture_output=True, text=True, timeout=60).returncode == 0
    dest_file = dst / "B-roll" / "Editor Added" / "alex" / "clip3.mov"
    assert dest_file.read_text() == "original"

    src_file = fixture_tree / "B-roll" / "Editor Added" / "alex" / "clip3.mov"
    src_file.write_text("modified")
    old = time.time() - 3600
    os.utime(src_file, (old, old))
    assert subprocess.run(cmd, capture_output=True, text=True, timeout=60).returncode == 0
    assert dest_file.read_text() == "original"


def test_express_never_deletes_anything_on_either_side(
    rclone_binary, fixture_tree, tmp_path
):
    """The standing rule: no speed change may widen a deletion window."""
    dst = tmp_path / "dst_express"
    (dst / "B-roll").mkdir(parents=True)
    stranger = dst / "B-roll" / "only-on-the-nas.mov"
    stranger.write_text("must survive")
    partial = dst / "B-roll" / "big.mov.partial"
    partial.write_text("an orphan partial rclone must not touch")

    list_file = write_files_from_list(
        ["B-roll/Editor Added/alex/clip3.mov"], tmp_path / "state" / "express.txt"
    )
    proc = subprocess.run(
        _express_cmd(rclone_binary, fixture_tree, dst, list_file),
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert stranger.read_text() == "must survive"
    assert partial.read_text() == "an orphan partial rclone must not touch"
    assert "Deleted" not in proc.stderr


def test_express_temp_files_cannot_collide_with_the_periodic_pass(
    rclone_binary, fixture_tree, tmp_path
):
    """rclone's partial token is DERIVED FROM THE FILE, not random per run:
    two separate runs both produced `clip1.mov.42048420.partial`. So an
    express run and a periodic pass uploading the same new file at the same
    moment would share one temp path and interleave. --partial-suffix gives
    them disjoint names; this proves the flag actually takes effect."""
    list_file = write_files_from_list(
        ["B-roll/Editor Added/alex/clip3.mov"], tmp_path / "state" / "express.txt"
    )
    proc = subprocess.run(
        _express_cmd(rclone_binary, fixture_tree, tmp_path / "dst_ps", list_file) + ["-vv"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr

    def _temp_names(stderr: str) -> set[str]:
        return {
            m.group(0)
            for line in stderr.splitlines()
            if "starting with parameters" not in line
            for m in [re.search(r"clip3\.mov\.[^:\s]*partial", line)]
            if m
        }

    express_temps = _temp_names(proc.stderr)
    assert express_temps, proc.stderr[-500:]
    assert all(name.endswith(".exp.partial") for name in express_temps)

    # Same file through the ordinary lane A argv: the default suffix, i.e. a
    # different temp path from the express one above -- which is the whole
    # point, since the token in the middle is identical for a given file.
    filter_file = write_filter_file(build_filter_rules_up(), tmp_path / "filter_up.txt")
    full = build_up_command(rclone_binary, str(fixture_tree), None, str(tmp_path / "dst_ps2"), filter_file)
    full[3] = str(tmp_path / "dst_ps2")
    full_proc = subprocess.run(full + ["-vv"], capture_output=True, text=True, timeout=60)
    assert full_proc.returncode == 0, full_proc.stderr
    full_temps = _temp_names(full_proc.stderr)
    assert full_temps, full_proc.stderr[-500:]
    assert all(name.endswith(".partial") and not name.endswith(".exp.partial") for name in full_temps)
    assert express_temps.isdisjoint(full_temps)
    # The derived token really is the same for the same file -- that is the
    # collision this flag prevents.
    assert {n[: -len(".exp.partial")] for n in express_temps} == {
        n[: -len(".partial")] for n in full_temps
    }


def test_rclone_refuses_files_from_raw_together_with_any_filter(
    rclone_binary, fixture_tree, tmp_path
):
    """Why build_express_command carries no --min-age/--filter-from, and why
    both gates are enforced in Python instead. If a future rclone allows the
    combination this test fails loudly and the flags can come back."""
    list_file = write_files_from_list(
        ["B-roll/Editor Added/alex/clip3.mov"], tmp_path / "state" / "express.txt"
    )
    filter_file = write_filter_file(build_filter_rules_up(), tmp_path / "filter_up.txt")
    base = _express_cmd(rclone_binary, fixture_tree, tmp_path / "dst_x", list_file)
    for extra in (["--min-age", "120s"], ["--filter-from", str(filter_file)]):
        proc = subprocess.run(base + extra, capture_output=True, text=True, timeout=60)
        assert proc.returncode != 0
        assert "overrides all other filters" in proc.stderr


def test_a_blank_list_line_is_read_as_the_root_dir(rclone_binary, fixture_tree, tmp_path):
    """Measured: rclone reads a blank raw-list line as the root directory and
    fails the run. write_files_from_list refuses to emit one -- this proves
    the hazard is real, by writing the bad file by hand."""
    bad = tmp_path / "bad.txt"
    with open(bad, "w", encoding="utf-8", newline="") as fh:
        fh.write("B-roll/Editor Added/alex/clip3.mov\n\n")
    proc = subprocess.run(
        _express_cmd(rclone_binary, fixture_tree, tmp_path / "dst_blank", bad),
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0
    assert "is a directory not a file" in proc.stderr
    with pytest.raises(ExpressListError):
        write_files_from_list(["B-roll/Editor Added/alex/clip3.mov", ""], tmp_path / "ok.txt")


def test_a_backslash_list_entry_silently_transfers_nothing(
    rclone_binary, fixture_tree, tmp_path
):
    """The worst failure mode of the three: exit 0, zero bytes moved, no
    error line. write_files_from_list normalises separators for exactly
    this reason."""
    bad = tmp_path / "bad.txt"
    with open(bad, "w", encoding="utf-8", newline="") as fh:
        fh.write("B-roll\\Editor Added\\alex\\clip3.mov\n")
    dst = tmp_path / "dst_bs"
    proc = subprocess.run(
        _express_cmd(rclone_binary, fixture_tree, dst, bad),
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0
    assert not (dst / "B-roll").exists()

    good = write_files_from_list(
        ["B-roll\\Editor Added\\alex\\clip3.mov"], tmp_path / "good.txt"
    )
    assert good.read_text(encoding="utf-8") == "B-roll/Editor Added/alex/clip3.mov\n"
    proc = subprocess.run(
        _express_cmd(rclone_binary, fixture_tree, dst, good),
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert (dst / "B-roll" / "Editor Added" / "alex" / "clip3.mov").exists()


def test_express_lists_far_fewer_objects_than_a_full_pass(
    rclone_binary, fixture_tree, tmp_path
):
    """C-2's payoff, measured rather than asserted by hand-wave: the express
    run stats a single object where the full pass walks the tree."""
    dst = tmp_path / "dst_cmp"
    filter_file = write_filter_file(build_filter_rules_up(), tmp_path / "filter_up.txt")
    full = build_up_command(
        rclone_binary, str(fixture_tree), None, str(dst), filter_file, stats_interval="1000h"
    )
    full[3] = str(dst)
    full_proc = subprocess.run(full, capture_output=True, text=True, timeout=60)
    assert full_proc.returncode == 0, full_proc.stderr

    list_file = write_files_from_list(
        ["B-roll/Editor Added/alex/clip3.mov"], tmp_path / "state" / "express.txt"
    )
    express = build_express_command(
        rclone_binary, str(fixture_tree), None, str(tmp_path / "dst_cmp2"), list_file,
        stats_interval="1000h",
    )
    express[3] = str(tmp_path / "dst_cmp2")
    express_proc = subprocess.run(express, capture_output=True, text=True, timeout=60)
    assert express_proc.returncode == 0, express_proc.stderr

    def _listed(stderr: str) -> int:
        best = None
        for line in stderr.splitlines():
            if '"listed"' in line:
                best = json.loads(line)["stats"]["listed"]
        if best is None:
            raise AssertionError(f"no stats line in {stderr[-500:]!r}")
        return best

    assert _listed(express_proc.stderr) < _listed(full_proc.stderr)


def test_all_transfer_commands_pin_the_local_encoding(tmp_path):
    """The proxy-relink incident (2026-07-26): rclone's default Windows
    local encoding writes a name containing fullwidth punctuation with a
    U+201B quote prefix, so the downloaded proxy's basename no longer
    matches its Resolve clip. Every transfer command must pin the encoding
    that round-trips fullwidth names verbatim."""
    from ccsync_companion.sync.rclone_lane import (
        LOCAL_ENCODING,
        build_down_command,
        build_express_command,
        build_up_command,
    )

    filter_file = tmp_path / "f.txt"
    filter_file.write_text("+ **/Proxy/**\n- **\n", encoding="utf-8")
    files_from = tmp_path / "files.txt"
    files_from.write_text("x.mp4\n", encoding="utf-8")

    up = build_up_command("rclone", r"C:\root", "nas", "CC", filter_file)
    down = build_down_command("rclone", r"C:\root", "nas", "CC", filter_file)
    express = build_express_command("rclone", r"C:\root", "nas", "CC", files_from)
    for cmd in (up, down, express):
        i = cmd.index("--local-encoding")
        assert cmd[i + 1] == LOCAL_ENCODING
    # the punctuation mappings must be OUT (they cause the quoting) and the
    # structural ones IN (path separators and control chars stay mapped)
    for gone in ("Question", "Colon", "DoubleQuote", "LtGt", "Asterisk", "Pipe"):
        assert gone not in LOCAL_ENCODING
    for kept in ("Slash", "BackSlash", "Ctl", "InvalidUtf8"):
        assert kept in LOCAL_ENCODING


# ===========================================================================
# Express/periodic overlap: the periodic pass must not re-upload what the
# express run already has in flight (2026-08-02 -- measured on an editor's
# machine, the same .mov climbing on two concurrent connections while the
# uplink was already saturated).
# ===========================================================================


def test_escape_filter_pattern_quotes_every_glob_metacharacter():
    from ccsync_companion.sync.rclone_lane import escape_filter_pattern

    assert escape_filter_pattern("plain.mov") == "plain.mov"
    assert escape_filter_pattern("[BM Cloud]/a.mov") == r"\[BM Cloud\]/a.mov"
    assert escape_filter_pattern("a{1,2}?.mov") == r"a\{1,2\}\?.mov"
    assert escape_filter_pattern("star*.mov") == r"star\*.mov"
    # The backslash is the escape character itself -- it must be escaped
    # first, or every other escape it introduces would be double-escaped.
    assert escape_filter_pattern("back" + chr(92) + "slash.mov") == "back" + chr(92) * 2 + "slash.mov"


def test_exclude_rules_come_first_and_the_terminator_survives():
    """First-match-wins: an exclude after `+ *.mov` would never fire, and
    validate_filter_file still demands `- **` last."""
    rules = build_filter_rules_up(["B-roll/a.mov", "Interviews/b.braw"])
    # rules[0] is the AppleDouble exclude (KNOWN_BUGS 12) -- also an exclude,
    # so the property under test is unchanged: both express paths are ahead
    # of every include, in order.
    assert rules[1] == "- /B-roll/a.mov"
    assert rules[2] == "- /Interviews/b.braw"
    assert rules.index("- /B-roll/a.mov") < rules.index("+ *.mov")
    assert rules[-1] == "- **"


def test_no_excludes_is_byte_identical_to_the_old_rule_list():
    """The overlap fix must be inert when express isn't running."""
    assert build_filter_rules_up() == build_filter_rules_up([])


def test_relativize_express_path_against_the_runs_subpath():
    from ccsync_companion.sync.rclone_lane import RcloneLane as L

    r = L._relativize_to_subpath
    assert r("Projects/2026/P/B-roll/a.mov", "Projects/2026/P") == "B-roll/a.mov"
    assert r("Projects/2026/P/B-roll/a.mov", None) == "Projects/2026/P/B-roll/a.mov"
    # --ignore-case is on, so casing drift in a shared parent must still match
    assert r("Projects/2026/p/B-roll/a.mov", "Projects/2026/P") == "B-roll/a.mov"
    # A different project's file would never be seen by this run anyway
    assert r("Projects/2026/OTHER/a.mov", "Projects/2026/P") is None
    assert r("Projects/2026/P", "Projects/2026/P") is None
    assert r("", "Projects/2026/P") is None
    bs = chr(92)  # a Windows-style rel, as the watcher can hand it over
    assert r(bs.join(["", "Projects", "2026", "P", "B-roll", "a.mov"]),
             "Projects/2026/P") == "B-roll/a.mov"


def test_lane_a_dry_run_skips_an_in_flight_express_path(rclone_binary, fixture_tree, tmp_path):
    """Against the REAL binary: the excluded file is skipped, its siblings
    are not."""
    filter_file = write_filter_file(
        build_filter_rules_up(["B-roll/Editor Added/alex/clip3.mov"]),
        tmp_path / "filter_up.txt",
    )
    dst = tmp_path / "dst_up"
    cmd = build_up_command(rclone_binary, str(fixture_tree), None, str(dst), filter_file)
    cmd[3] = str(dst)
    proc = subprocess.run(cmd + ["--dry-run"], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr

    assert "clip3.mov" not in proc.stderr      # express owns it right now
    assert "Proxynotreal.mov" in proc.stderr   # everything else still uploads


def test_escaped_metacharacters_exclude_only_the_literal_file(rclone_binary, tmp_path):
    """An unescaped `[ab]` would be a character class and would wrongly
    exclude `a.mov`/`b.mov` too. Proven against the real binary."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "[ab].mov").write_text("literal brackets")
    (src / "a.mov").write_text("must still upload")
    old = time.time() - 3600
    for f in src.rglob("*"):
        os.utime(f, (old, old))

    filter_file = write_filter_file(build_filter_rules_up(["[ab].mov"]), tmp_path / "f.txt")
    dst = tmp_path / "dst"
    cmd = build_up_command(rclone_binary, str(src), None, str(dst), filter_file)
    cmd[3] = str(dst)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr

    assert not (dst / "[ab].mov").exists()  # excluded, literally
    assert (dst / "a.mov").exists()         # NOT caught by a stray class


def test_a_proxy_being_encoded_crosses_no_lane_in_either_direction(rclone_binary, tmp_path):
    """The write-discipline invariant the companion's proxy generator rests
    on (proxy_gen.py, 2026-08-10), proven against the real binary rather than
    the rule list.

    The generator encodes to `Proxy/<stem>.mp4.partial` and os.replace()s it
    into place, and the ONLY thing that makes that safe is that a half-made
    proxy cannot leave the machine: lane A would publish a truncated file to
    the NAS under a name lane B then fans out to every editor, and lane B
    would pull one down onto an editor whose Resolve would happily attach it.
    Both directions, because the two filters are built separately and only
    lane B's `**/Proxy/**` include even reaches inside a Proxy dir.
    """
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    proxy = src / "Sub" / "Proxy"
    proxy.mkdir(parents=True)
    dst.mkdir()
    (proxy / "A001.mp4.partial").write_bytes(b"ftyp...mdat... (still encoding)")
    (proxy / "A001.mov").write_bytes(b"a finished proxy")
    (src / "Sub" / "A001.mp4").write_bytes(b"the original")
    old = time.time() - (LANE_B_MIN_AGE_SECONDS * 2)
    for path in src.rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))

    # UP (lane A: editor -> NAS). Its include is video outside Proxy/, so the
    # original goes and nothing under Proxy/ does.
    filter_file = write_filter_file(build_filter_rules_up(), tmp_path / "filter_up.txt")
    cmd = build_up_command(rclone_binary, str(src), None, str(dst), filter_file)
    cmd[3] = str(dst)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    landed = sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file())
    assert landed == ["Sub/A001.mp4"], f"lane A carried a half-made proxy: {landed}"

    # DOWN (lane B: NAS -> editor). Its include IS `**/Proxy/**` -- every byte
    # under the directory -- so this is the direction that has to exclude it
    # explicitly (IN_PROGRESS_EXCLUDE_RULES).
    down = tmp_path / "down"
    down.mkdir()
    filter_file = write_filter_file(build_filter_rules_down(), tmp_path / "filter_down.txt")
    cmd = build_down_command(rclone_binary, str(down), None, str(src), filter_file)
    cmd[2] = str(src)
    cmd[3] = str(down)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    landed = sorted(p.relative_to(down).as_posix() for p in down.rglob("*") if p.is_file())
    assert landed == ["Sub/Proxy/A001.mov"], (
        f"lane B pulled a proxy that was still being encoded: {landed}"
    )
