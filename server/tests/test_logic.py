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
