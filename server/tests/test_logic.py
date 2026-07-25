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
