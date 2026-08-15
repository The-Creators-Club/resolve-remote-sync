"""Pure-logic unit tests -- no network, no SSH, no NAS required.

Run with:
    cd E:\\Projects\\resolve-remote-sync\\server
    python -m pytest tests -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import (
    TEMPLATE_FOLDERS,
    VIDEO_EXTENSIONS,
    YTDL_IGNORE_LINES,
    build_stignore_lines,
    project_path,
    project_relative_dirs,
    shell_quote,
    slugify,
)


def test_template_folders_exact_list():
    assert TEMPLATE_FOLDERS == [
        "AE",
        "Audio/Music",
        "Audio/Voiceover",
        "B-roll",
        "Interviewees",
        "Render in Place",
        "Subs",
        "Youtube",
    ]


def test_template_folders_no_proxy_precreated():
    for folder in TEMPLATE_FOLDERS:
        assert "Proxy" not in folder


def test_project_relative_dirs_no_prefix():
    assert project_relative_dirs() == TEMPLATE_FOLDERS


def test_project_relative_dirs_with_prefix():
    dirs = project_relative_dirs("2025/FF4/Nuclear")
    assert dirs[0] == "2025/FF4/Nuclear/AE"
    assert "2025/FF4/Nuclear/Audio/Music" in dirs
    assert len(dirs) == len(TEMPLATE_FOLDERS)


def test_project_relative_dirs_strips_trailing_slash():
    a = project_relative_dirs("2025/FF4/Nuclear/")
    b = project_relative_dirs("2025/FF4/Nuclear")
    assert a == b


def test_project_path_basic():
    assert project_path("/mnt/tank/TheCreatorsPool/Creators_Club/Projects", "2025", "FF4", "Nuclear") == (
        "/mnt/tank/TheCreatorsPool/Creators_Club/Projects/2025/FF4/Nuclear"
    )


def test_project_path_strips_trailing_slash_on_root():
    a = project_path("/root/", "2025", "FF4", "Nuclear")
    b = project_path("/root", "2025", "FF4", "Nuclear")
    assert a == b


def test_project_path_rejects_path_separators():
    import pytest
    for bad in ("2025/06", "2025\\06", "../etc"):
        with pytest.raises(ValueError):
            project_path("/root", bad, "FF4", "Nuclear")


def test_slugify_basic():
    assert slugify("2025/FF4/Nuclear") == "2025-ff4-nuclear"


def test_slugify_handles_spaces_and_backslashes():
    assert slugify("2025\\FF4\\Nuclear My Cut") == "2025-ff4-nuclear-my-cut"


def test_slugify_handles_repeated_separators():
    assert slugify("2025//FF4///Nuclear") == "2025-ff4-nuclear"


def test_slugify_case_insensitive():
    assert slugify("2025/FF4/NUCLEAR") == slugify("2025/ff4/nuclear")


def test_slugify_handles_real_names_with_spaces():
    # Series and project names are free text and routinely contain spaces —
    # nothing here is specific to any one show.
    assert slugify("2026/Creator Profiles/Season 1") == "2026-creator-profiles-season-1"
    assert slugify("2027/Behind The Scenes/Ep 12 - Final Cut") == (
        "2027-behind-the-scenes-ep-12-final-cut"
    )


def test_project_path_preserves_spaces_verbatim():
    # The on-disk tree must mirror the source structure exactly; only the
    # Syncthing folder *id* is slugified, never the path itself.
    assert project_path(
        "/mnt/tank/TheCreatorsPool/Creators_Club/Projects",
        "2026", "Creator Profiles", "Season 1",
    ) == "/mnt/tank/TheCreatorsPool/Creators_Club/Projects/2026/Creator Profiles/Season 1"


def test_build_remote_script_quotes_paths_with_spaces():
    # A space in a series/project name must not split into two shell words.
    from setup_tree import build_remote_script  # noqa: PLC0415
    from tests.test_safety import unquoted_occurrences  # noqa: PLC0415

    base = "/mnt/tank/TheCreatorsPool/Creators_Club/Projects/2026/Creator Profiles/Season 1"
    script = build_remote_script(base, "broll", "editors")
    assert "'/mnt/tank/TheCreatorsPool/Creators_Club/Projects/2026/Creator Profiles/Season 1'" in script
    # and never outside single quotes, where it would word-split (the path also
    # appears inside the refusal messages, which are themselves single-quoted)
    assert unquoted_occurrences(script, base) == 0


def test_slugify_empty_raises():
    import pytest
    with pytest.raises(ValueError):
        slugify("///")


def test_build_stignore_lines_covers_every_video_extension():
    lines = build_stignore_lines()
    for ext in VIDEO_EXTENSIONS:
        assert f"(?i)*{ext}" in lines


def test_build_stignore_lines_ignores_proxy_dirs():
    lines = build_stignore_lines()
    assert any("Proxy" in line for line in lines)
    assert all(line.startswith("(?i)") for line in lines)


def test_build_stignore_lines_no_duplicates():
    lines = build_stignore_lines()
    assert len(lines) == len(set(lines))


def test_build_stignore_lines_ignores_ytdl_in_flight_files():
    """The NAS ytdl worker downloads into the shared Projects tree, so lane C
    used to replicate every growing `.part` to each editor with the project
    ticked -- and with ignoreDelete=True on editor folders (2026-08-11) the
    worker's completion rename/delete never follows, so the leftovers are
    permanent. 27 of them (~1.5 GB) on one editor's disk, 2026-08-13/14."""
    lines = build_stignore_lines()
    for pattern in YTDL_IGNORE_LINES:
        assert pattern in lines
    assert "(?i)*.part" in lines
    assert "(?i)*.ytdl" in lines


def test_the_ytdl_patterns_match_yt_dlp_s_real_in_flight_names():
    """Real names taken from ytdl/web's own sweeper tests. A pattern with no
    '/' matches the base name at any depth in Syncthing, which is what
    fnmatch models here. `.part-Frag84` is the one that does NOT end in
    `.part`, so it needs its own pattern rather than riding along."""
    import fnmatch  # noqa: PLC0415

    globs = [line[len("(?i)"):] for line in build_stignore_lines()
             if line.startswith("(?i)") and "/" not in line[len("(?i)"):]]
    names = [
        "Chan - T [abcdefghijk].f616.mp4.part",
        "Chan - T [abcdefghijk].f616.mp4.ytdl",
        "Chan - T [abcdefghijk].part",
        "Chan - T [abcdefghijk].part-Frag12",
        "X.f137.mp4.part-Frag84.part",
    ]
    for name in names:
        assert any(fnmatch.fnmatch(name.lower(), g.lower()) for g in globs), (
            f"{name} matches no ignore pattern")


def test_the_ytdl_patterns_do_not_swallow_a_finished_download():
    """yt-dlp renames the `.part` away on completion and the worker's
    `.editready` fallback IS the deliverable (YTDL-17) -- ignoring either
    would mean the clip never reaches an editor at all, since Youtube/ mp4s
    ride lane B and everything else in the folder rides lane C."""
    import fnmatch  # noqa: PLC0415

    globs = [line[len("(?i)"):] for line in YTDL_IGNORE_LINES]
    for name in ("Chan - T [abcdefghijk].mp4", "Chan - T [abcdefghijk].editready.mp4",
                 "The .part standard explained [ccccccccccc].mp4", "manifest.json",
                 "Timeline.drp", "notes.txt"):
        assert not any(fnmatch.fnmatch(name.lower(), g.lower()) for g in globs), (
            f"{name} was matched by a ytdl in-flight pattern")


def test_the_ytdl_patterns_are_not_in_the_asset_stignore():
    """The LUT library has no ytdl worker writing into it, and its list is
    pinned byte-identical across server/dashboard/companion -- an extra line
    here makes the collector and the companion rewrite the file at each
    other every cycle."""
    from common import build_asset_stignore_lines  # noqa: PLC0415

    asset = build_asset_stignore_lines()
    for pattern in YTDL_IGNORE_LINES:
        assert pattern not in asset


def test_shell_quote_wraps_simple_value():
    assert shell_quote("hello") == "'hello'"


def test_shell_quote_escapes_single_quote():
    assert shell_quote("it's") == "'it'\\''s'"


def test_project_path_rel_any_depth():
    from common import project_path_rel

    assert project_path_rel("/root", "2026/CCT/Creator Profiles/Season 1") == \
        "/root/2026/CCT/Creator Profiles/Season 1"
    assert project_path_rel("/root/", "OneOffs") == "/root/OneOffs"


def test_project_path_rel_rejects_bad_segments():
    import pytest
    from common import project_path_rel

    for bad in ("", "a/../b", "a/.hidden", "a\\b", "a//b"):
        with pytest.raises(ValueError):
            project_path_rel("/root", bad)


def test_build_marker_write_cmd_quoting():
    from common import MARKER_FILENAME, build_marker_write_cmd

    cmd = build_marker_write_cmd("/root/2026/CCT/Event 1.exe Videos", "the-slug")
    assert MARKER_FILENAME in cmd
    assert '"slug": "the-slug"' in cmd
    assert "sudo -S" in cmd
    # path with spaces stays inside single quotes
    assert "Event 1.exe Videos/.ccsync-project" in cmd
