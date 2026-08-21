"""CR-69: a non-ASCII watch folder must reach BPG in Qt's own INI escaping.

BPG (Qt 5, Latin-1 ini codec) showed the base rig a garbled folder
(`ç¬¬ä¸‰å±†...`) for a CJK shoot name on 2026-08-21, watched nothing, and
rewrote the entry as `\\xe7\\xac\\xac...` on exit -- which the next launch
saw as uncovered and appended again.
"""

from __future__ import annotations

import pytest

from ccsync_companion import bpg

CJK = "P:\\Projects\\2026\\Base Drone\\B-roll\\第三屆台灣教育科技盃"


def _garbled(path_prefix: str, name: str) -> str:
    """What BPG wrote back: backslashes doubled, each UTF-8 BYTE as \\xHH."""
    return path_prefix.replace("\\", "\\\\") + "".join(
        "\\x%x" % b for b in name.encode("utf-8"))


def test_non_latin1_characters_are_written_as_qt_utf16_escapes():
    assert bpg._escape_watch_folder("P:\\x\\第三") == "P:\\\\x\\\\\\x7b2c\\x4e09"


def test_a_hex_digit_after_an_escape_is_escaped_too():
    """Qt's reader is greedy after \\x: a following hex digit would be
    swallowed into the code point."""
    assert bpg._qt_escape_text("第a") == "\\x7b2c\\x61"
    assert bpg._qt_escape_text("第g") == "\\x7b2cg"


def test_astral_characters_become_surrogate_pairs():
    assert bpg._qt_escape_text("\U0001F600") == "\\xd83d\\xde00"


def test_plain_ascii_is_untouched():
    """The spelling verified against a live BPG on 2026-08-13 must not move."""
    assert bpg._escape_watch_folder("P:\\Projects\\2026\\Some Shoot") == (
        "P:\\\\Projects\\\\2026\\\\Some Shoot")


@pytest.mark.parametrize("path", [CJK, "P:\\Ünïcode\\é", "P:\\a\\b c", "P:\\x\\😀 clip", "P:\\第a\\1"])
def test_escape_and_parse_round_trip(path):
    assert bpg.parse_watch_folders(bpg._escape_watch_folder(path)) == [path]
    both = bpg._escape_watch_folder(path) + ", " + bpg._escape_watch_folder("P:\\other")
    assert bpg.parse_watch_folders(both) == [path, "P:\\other"]


def test_the_garbled_entry_bpg_wrote_back_is_recognised_as_ours():
    [entry] = bpg.parse_watch_folders(
        _garbled("P:\\Projects\\2026\\Base Drone\\B-roll\\", "第三屆台灣教育科技盃"))
    assert entry != CJK
    assert bpg._mojibake_of(entry, [CJK])
    assert not bpg._mojibake_of(entry, ["P:\\elsewhere"])
    assert not bpg._mojibake_of(CJK, [CJK])
    assert not bpg._mojibake_of("P:\\plain", ["P:\\plain"])


def test_ensure_watch_folders_writes_cjk_readably_and_drops_the_garbled_copies(tmp_path):
    garbled = _garbled("P:\\Projects\\2026\\Base Drone\\B-roll\\", "第三屆台灣教育科技盃")
    ini = tmp_path / "ProxyGeneratorSettings.ini"
    ini.write_text(
        "[General]\nwatchFolderList=P:\\\\Keep, %s, %s\ncodecType=2\n" % (garbled, garbled),
        encoding="utf-8",
    )
    result = bpg.ensure_watch_folders([CJK], path=str(ini))
    assert result["ok"] and result["added"] == [CJK]
    text = ini.read_text(encoding="utf-8")
    line = [ln for ln in text.splitlines() if ln.startswith("watchFolderList=")][0]
    assert "\\xe7" not in line, line
    line.encode("ascii")  # a Latin-1 reader sees exactly what we meant
    assert bpg.parse_watch_folders(line.split("=", 1)[1]) == ["P:\\Keep", CJK]
    assert "codecType=2" in text
    # Second pass: covered, nothing rewritten.
    before = ini.read_text(encoding="utf-8")
    assert bpg.ensure_watch_folders([CJK], path=str(ini)) == {"ok": True, "added": [], "reason": ""}
    assert ini.read_text(encoding="utf-8") == before


def test_garbled_entries_are_dropped_even_when_the_real_one_is_already_there(tmp_path):
    garbled = _garbled("P:\\Projects\\2026\\Base Drone\\B-roll\\", "第三屆台灣教育科技盃")
    ini = tmp_path / "ProxyGeneratorSettings.ini"
    ini.write_text(
        "[General]\nwatchFolderList=%s, %s\n" % (garbled, bpg._escape_watch_folder(CJK)),
        encoding="utf-8",
    )
    result = bpg.ensure_watch_folders([CJK], path=str(ini))
    assert result == {"ok": True, "added": [], "reason": ""}
    line = [ln for ln in ini.read_text(encoding="utf-8").splitlines()
            if ln.startswith("watchFolderList=")][0]
    assert bpg.parse_watch_folders(line.split("=", 1)[1]) == [CJK]


def test_someone_elses_latin1_entry_is_left_alone(tmp_path):
    """An editor's own `P:\\Café` is Latin-1-representable and NOT the
    UTF-8-misread of anything we want: never touched."""
    ini = tmp_path / "ProxyGeneratorSettings.ini"
    ini.write_text("[General]\nwatchFolderList=P:\\\\Caf\\xe9\n", encoding="utf-8")
    assert bpg.ensure_watch_folders(["P:\\New"], path=str(ini))["added"] == ["P:\\New"]
    line = [ln for ln in ini.read_text(encoding="utf-8").splitlines()
            if ln.startswith("watchFolderList=")][0]
    assert line == "watchFolderList=P:\\\\Caf\\xe9, P:\\\\New"
