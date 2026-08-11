"""Which clips the archive build ships, and what lands in their `Proxy/`.

Only a file under `Proxy/` becomes the row's `archive_path` -- what the web app
plays -- and only `**/Proxy/**` is what lane B syncs to editors. So "no preview
planned" is not a cosmetic shortfall: it is a clip the site cannot play and the
fleet never receives.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_archive import eligible, preview_source  # noqa: E402


def _db(tmp_path: Path, schema_path: Path, rows: list[dict]) -> str:
    path = tmp_path / "broll.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    for r in rows:
        cols = ", ".join(r)
        conn.execute(f"INSERT INTO videos ({cols}) VALUES ({', '.join('?' * len(r))})",
                     list(r.values()))
    conn.commit()
    conn.close()
    return str(path)


# ---------------------------------------------------------------------------
# BROLL-7 — a Downloads clip whose folder is about to change is not ready
# ---------------------------------------------------------------------------

def test_a_proxied_download_with_no_category_yet_waits_for_the_model(tmp_path, schema_path):
    """Its destination is `Downloads/<category>`, NULL until the model pass. Ship
    it now and it is filed under _uncategorised, filed AGAIN under its real
    subject next build, and the first copy is stranded -- this script never
    deletes."""
    db = _db(tmp_path, schema_path, [
        {"share": "ff4-lol", "rel_path": "a.mp4", "status": "proxied", "category": None},
    ])
    assert eligible(db, creators=set()) == []


def test_a_proxied_own_shoot_still_ships_immediately(tmp_path, schema_path):
    """The 2026-08-10 ff3 case, and why this is not just "exclude proxied": an
    own shoot files by its folders, which the model never touches, so its
    placement is already final."""
    db = _db(tmp_path, schema_path, [
        {"share": "ff3", "rel_path": "Day 1/Proxy/a.mov", "status": "proxied",
         "category": None},
    ])
    assert [v["rel_path"] for v in eligible(db, creators={"ff3"})] == ["Day 1/Proxy/a.mov"]


def test_an_indexed_download_with_no_subject_still_ships(tmp_path, schema_path):
    """NULL category at 'indexed' is a verdict, not a pending question: the model
    found no subject, and _uncategorised is where it belongs for good."""
    db = _db(tmp_path, schema_path, [
        {"share": "ff4-lol", "rel_path": "a.mp4", "status": "indexed", "category": None},
    ])
    assert len(eligible(db, creators=set())) == 1


def test_no_creators_set_means_no_filtering(tmp_path, schema_path):
    """For a caller with no config to hand -- the old behaviour, unchanged."""
    db = _db(tmp_path, schema_path, [
        {"share": "ff4-lol", "rel_path": "a.mp4", "status": "proxied", "category": None},
    ])
    assert len(eligible(db)) == 1


# ---------------------------------------------------------------------------
# BROLL-14 — audio-only clips are searchable, so they have to be playable
# ---------------------------------------------------------------------------

def test_an_audio_only_clip_is_eligible(tmp_path, schema_path):
    """probe parks it at 'skipped' because there is nothing to SEE. Its speech is
    transcribed and fully searchable, so search returns it -- and without its
    media in the archive the player 404s on the clip search just found."""
    db = _db(tmp_path, schema_path, [
        {"share": "ff4-lol", "rel_path": "talk.mp4", "status": "skipped",
         "codec": None, "duration_s": 640.0, "category": "politics"},
    ])
    assert [v["rel_path"] for v in eligible(db, creators=set())] == ["talk.mp4"]


def test_an_editor_proxy_folder_is_still_excluded(tmp_path, schema_path):
    """The scanner's own 'skipped': 2,100 files and 660 GB of redundant second
    encodes. Told apart by never having been probed -- no duration."""
    db = _db(tmp_path, schema_path, [
        {"share": "ff4-lol", "rel_path": "Proxy/a.mp4", "status": "skipped",
         "codec": None, "duration_s": None},
    ])
    assert eligible(db, creators=set()) == []


def test_an_over_length_clip_is_still_excluded(tmp_path, schema_path):
    """probe's other 'skipped'. It has a video codec, so it is not audio-only."""
    db = _db(tmp_path, schema_path, [
        {"share": "ff4-lol", "rel_path": "take.mp4", "status": "skipped",
         "codec": "h264", "duration_s": 10800.0},
    ])
    assert eligible(db, creators=set()) == []


# ---------------------------------------------------------------------------
# BROLL-6 / BROLL-14 — what goes in Proxy/
# ---------------------------------------------------------------------------

def test_the_generated_proxy_is_the_preview(tmp_path):
    proxies = tmp_path / "proxies"
    proxies.mkdir()
    (proxies / "7.mp4").write_bytes(b"x")
    assert preview_source({"id": 7, "status": "indexed"}, tmp_path / "orig.mkv",
                          proxies) == proxies / "7.mp4"


def test_the_preview_is_planned_even_when_it_is_also_the_top_slot(tmp_path):
    """A download with no resolved original_path falls back to the generated
    proxy for BOTH slots. Skipping the Proxy/ copy as redundant left the row
    with no archive_path and its only file outside what lane B syncs."""
    proxies = tmp_path / "proxies"
    proxies.mkdir()
    top = proxies / "7.mp4"
    top.write_bytes(b"x")
    assert preview_source({"id": 7, "status": "proxied"}, top, proxies) == top


def test_an_audio_only_clip_stands_in_as_its_own_preview(tmp_path):
    """No generated proxy exists -- stage_proxy never ran, there being no video
    stream to encode -- and the source is a small audio file."""
    proxies = tmp_path / "proxies"
    proxies.mkdir()
    top = tmp_path / "talk.mp4"
    top.write_bytes(b"x")
    assert preview_source({"id": 7, "status": "skipped"}, top, proxies) == top


def test_a_clip_with_neither_plans_no_preview(tmp_path):
    proxies = tmp_path / "proxies"
    proxies.mkdir()
    assert preview_source({"id": 7, "status": "indexed"}, None, proxies) is None
