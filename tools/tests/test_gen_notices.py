"""Tests for tools/gen_notices.py — the notices generator.

Run from the repo root with any interpreter that has pytest:

    dashboard\\.venv\\Scripts\\python.exe -m pytest tools/tests -q

Nothing here touches a venv, pip, or the network: `collect()` is the only
function that shells out and it is never called. What IS pinned is the
hand-maintained block's survival, because that block carries the ffmpeg
written offer and the "no licence grant" finding — losing it silently is the
one failure mode of this tool that matters (2026-08-17,
docs/COMMERCIAL_READINESS.md item 3).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gen_notices  # noqa: E402


PKG = {"Name": "somepkg", "Version": "1.0", "License": "MIT",
       "URL": "https://example.invalid", "LicenseText": "MIT License ..."}


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "THIRD_PARTY_NOTICES.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_hand_block_is_read_back_verbatim(tmp_path):
    path = _write(tmp_path, "\n".join([
        "# notices", "",
        gen_notices.BEGIN_SENTINEL,
        "## Non-pip components",
        "",
        "ffmpeg is GPLv3.",
        gen_notices.END_SENTINEL,
        "",
    ]))
    assert gen_notices.existing_hand_block(path) == (
        "## Non-pip components\n\nffmpeg is GPLv3.")


def test_sentinels_mentioned_in_prose_do_not_match():
    """The generated header EXPLAINS the sentinels, so it contains both
    strings mid-sentence. A substring search matched those and wiped the whole
    hand-maintained section on the first regeneration (2026-08-17) -- this is
    that bug."""
    rendered = gen_notices.render({"companion": [PKG]}, [], "KEEP ME")
    header_line = next(line for line in rendered.splitlines()
                       if gen_notices.BEGIN_SENTINEL in line
                       and line.strip() != gen_notices.BEGIN_SENTINEL)
    assert header_line  # the trap exists in the real output, not just in theory
    assert rendered.count(gen_notices.BEGIN_SENTINEL) >= 2


def test_render_round_trips_the_hand_block(tmp_path):
    path = _write(tmp_path, gen_notices.render(
        {"companion": [PKG]}, [], "## Non-pip components\n\nffmpeg is GPLv3."))
    assert gen_notices.existing_hand_block(path) == (
        "## Non-pip components\n\nffmpeg is GPLv3.")
    # ...and a second generation off that file keeps it.
    again = gen_notices.render({"companion": [PKG]}, [],
                               gen_notices.existing_hand_block(path))
    assert "ffmpeg is GPLv3." in again


def test_missing_file_yields_the_placeholder(tmp_path):
    assert gen_notices.existing_hand_block(
        tmp_path / "nope.md") == gen_notices.DEFAULT_HAND_BLOCK


def test_file_without_sentinels_yields_the_placeholder(tmp_path):
    path = _write(tmp_path, "# notices\n\nnothing here\n")
    assert gen_notices.existing_hand_block(path) == gen_notices.DEFAULT_HAND_BLOCK


def test_half_applied_sentinels_refuse_rather_than_wipe(tmp_path):
    path = _write(tmp_path, "\n".join([
        gen_notices.BEGIN_SENTINEL, "irreplaceable text", ""]))
    with pytest.raises(SystemExit):
        gen_notices.existing_hand_block(path)


def test_copyleft_is_flagged_and_permissive_is_not():
    rows = gen_notices.merged({
        "companion": [
            {**PKG, "Name": "pystray", "License": "GNU Lesser General Public "
                                                  "License v3 (LGPLv3)"},
            {**PKG, "Name": "certifi", "License": "Mozilla Public License 2.0 (MPL 2.0)"},
            {**PKG, "Name": "watchdog", "License": "Apache Software License"},
        ]})
    flagged = {row["Name"]: kind for row, kind in gen_notices.attention(rows)}
    assert flagged == {"pystray": "LGPL", "certifi": "MPL"}


def test_lgpl_is_not_reported_as_plain_gpl():
    """'GPL' is a substring of 'LGPL'; reporting an LGPL package as GPL would
    overstate the obligation, which is the opposite of useful in a document
    counsel reads."""
    rows = gen_notices.merged({"dashboard": [{**PKG, "Name": "paramiko",
                                              "License": "LGPL-2.1"}]})
    assert gen_notices.attention(rows)[0][1] == "LGPL"


def test_same_package_in_two_venvs_merges_but_two_versions_do_not():
    rows = gen_notices.merged({
        "dashboard": [{**PKG, "Name": "numpy", "Version": "2.5.2"}],
        "music/web": [{**PKG, "Name": "numpy", "Version": "2.5.2"},
                      {**PKG, "Name": "uvicorn", "Version": "0.52.1"}],
        "broll/web": [{**PKG, "Name": "uvicorn", "Version": "0.51.0"}],
    })
    by_key = {(r["Name"], r["Version"]): r["_components"] for r in rows}
    assert by_key[("numpy", "2.5.2")] == ["dashboard", "music/web"]
    # A licence can change between versions, so these must stay separate rows.
    assert by_key[("uvicorn", "0.52.1")] == ["music/web"]
    assert by_key[("uvicorn", "0.51.0")] == ["broll/web"]


def test_pipe_in_a_licence_string_cannot_open_a_table_column():
    rendered = gen_notices.render(
        {"companion": [{**PKG, "License": "MIT | Apache-2.0"}]}, [], "x")
    assert "MIT \\| Apache-2.0" in rendered


def test_scan_warnings_are_stated_in_the_document():
    """A component that could not be scanned must say so IN the notices file.
    A missing venv silently producing a shorter inventory is how a licence
    goes unlisted."""
    rendered = gen_notices.render({"companion": [PKG]}, ["ytdl/web: no venv"], "x")
    assert "## Scan warnings" in rendered
    assert "ytdl/web: no venv" in rendered
