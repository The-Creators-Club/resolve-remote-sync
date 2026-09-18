"""The 2026-09-18 hunt, server/ and tools/'s half (webapps-tools, CR-286).

Run from Git Bash with the dashboard venv, like the rest of this suite.
Nothing here touches the NAS: the backend is the same FakeBackend the drain
tests use, and every file is a temporary sqlite database.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import publish_db                                      # noqa: E402
import install_dashboard_app as ida                    # noqa: E402


# ------------------------------------------------------------------ broll-2

def _db_at(path: Path, version: int) -> Path:
    conn = sqlite3.connect(str(path))
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    conn.close()
    return path


def test_the_schema_version_of_a_local_index_is_read(tmp_path):
    assert publish_db.local_user_version(_db_at(tmp_path / "a.db", 12)) == 12


def test_an_unreadable_file_has_no_schema_version(tmp_path):
    (tmp_path / "junk.db").write_bytes(b"not a database at all")
    assert publish_db.local_user_version(tmp_path / "junk.db") in (None, 0)
    assert publish_db.local_user_version(tmp_path / "absent.db") is None


def test_publishing_a_newer_schema_than_the_deployed_app_is_refused():
    """A dashboard on 0.7.34..0.7.48 carries CURRENT_SCHEMA_VERSION = 11 and
    the app refuses a v12 file outright, which turns the whole /broll search
    UI off with the reason only in the container log."""
    why = publish_db.schema_refusal(12, 11, "broll")
    assert why
    assert "Deploy the dashboard first" in why


def test_publishing_an_older_schema_under_a_newer_container_is_refused():
    """ensure_schema runs at mount time, so a file dropped under a running
    container is never stepped: every ingest push 500s until a restart."""
    why = publish_db.schema_refusal(11, 12, "broll")
    assert why and "restart" in why


def test_a_version_either_side_cannot_read_never_refuses():
    assert publish_db.schema_refusal(None, 12, "broll") == ""
    assert publish_db.schema_refusal(12, None, "broll") == ""
    assert publish_db.schema_refusal(12, 12, "broll") == ""


def test_the_live_read_asks_for_the_schema_version_in_the_same_exec():
    """One container call, not two: this chain is driven by an ordered answer
    script and a new exec in the middle of it changes every caller."""
    src = Path(publish_db.__file__).read_text(encoding="utf-8")
    body = src[src.index("def read_live_counts("):]
    body = body[:body.index("\ndef ", 1)]
    assert "PRAGMA user_version" in body
    assert body.count("container_exec") == 1


# ------------------------------------------------------------ server-tools-2

def test_the_unmerged_drain_code_is_distinct_and_not_success():
    assert publish_db.RC_DRAIN_UNMERGED not in (0, 1)


# ------------------------------------------------------------ server-tools-5

def test_an_absent_guide_does_not_withhold_the_licence_agreement(tmp_path,
                                                                 monkeypatch,
                                                                 capsys):
    """dash-core-6 promoted EDITOR_SETUP.md into SHIPPED_DOCS and the refusal
    was all-or-nothing, so one missing guide cost the EULA the first-run
    wizard gates on."""
    docs = tmp_path / "docs"
    (docs / "legal").mkdir(parents=True)
    (docs / "legal" / "EULA.md").write_text("the licence", encoding="utf-8")
    (docs / "HOW_IT_WORKS.md").write_text("how", encoding="utf-8")
    # EDITOR_SETUP.md deliberately absent.
    monkeypatch.setattr(ida, "LOCAL_DOCS_DIR", docs)
    shipped = {}

    def fake_stage(staging):
        shipped["staged"] = True

    monkeypatch.setattr(ida, "_stage_docs_tree", fake_stage)
    monkeypatch.setattr(ida, "install_tree",
                        lambda *a, **k: True)

    ok = ida.ship_dashboard_docs("/mnt/apps/dash", True, "/tmp")

    assert ok is True, capsys.readouterr().err
    assert shipped.get("staged"), "nothing was shipped at all"
    err = capsys.readouterr().err
    assert "EDITOR_SETUP.md" in err
    assert "licence agreement, is being shipped" in err


def test_an_absent_legal_tree_is_still_fatal(tmp_path, monkeypatch, capsys):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "HOW_IT_WORKS.md").write_text("how", encoding="utf-8")
    (docs / "EDITOR_SETUP.md").write_text("setup", encoding="utf-8")
    monkeypatch.setattr(ida, "LOCAL_DOCS_DIR", docs)

    assert ida.ship_dashboard_docs("/mnt/apps/dash", True, "/tmp") is False
    assert "licence agreement" in capsys.readouterr().err


# ------------------------------------------------------------ server-tools-3

def test_the_tailscale_status_read_names_its_encoding():
    """A peer name is not ASCII; `text=True` with no encoding decodes with the
    process locale, and on this rig cp1252 RAISES on the fleet's own
    `母母女子`. The broad except then reports a check that did not run as a
    check that was skipped, and the run still exits 0."""
    src = (Path(publish_db.__file__).parent / "check_health.py").read_text(
        encoding="utf-8")
    call = src[src.index('[exe, "status", "--json"]'):]
    call = call[:call.index(")")]
    assert 'encoding="utf-8"' in call


# ------------------------------------------------------------ server-tools-4

@pytest.mark.parametrize("rel", [
    "bench/ccbench/runners/_rclone_common.py",
    "bench/ccbench/runners/base.py",
    "bench/ccbench/runners/syncthing.py",
    "bench/ccbench/runners/iperf3.py",
])
def test_every_bench_subprocess_read_declares_utf8(rel):
    repo = Path(publish_db.__file__).resolve().parents[1]
    src = (repo / rel).read_text(encoding="utf-8")
    for i, chunk in enumerate(src.split("capture_output=True")[1:]):
        # Past the comment block that explains why.
        head = chunk[:800]
        assert 'encoding="utf-8"' in head, f"{rel}: call {i} decodes by locale"


def test_the_rclone_listing_returns_none_on_a_decode_failure():
    """Its docstring promises None "if the listing failed"; a
    UnicodeDecodeError is a ValueError and escaped the except tuple."""
    repo = Path(publish_db.__file__).resolve().parents[1]
    src = (repo / "bench/ccbench/runners/_rclone_common.py").read_text(
        encoding="utf-8")
    body = src[src.index("def remote_listing("):]
    body = body[:body.index("\ndef ", 1)]
    guard = body[body.index("except ("):]
    assert "ValueError" in guard[:guard.index(")")]


# ----------------------------------------------- server-tools-2 (2026-09-18b)

def test_an_older_music_index_is_not_refused():
    """/music re-steps a file swapped under it: musicweb/db.py's con() checks
    the inode on every connection, invalidates its cached schema state and
    re-runs ensure_schema, which walks its migrations by an "already applied"
    predicate rather than by user_version. Refusing this direction for music
    sent the operator to --allow-schema-skew, which also disables the
    direction that IS fatal."""
    assert publish_db.schema_refusal(11, 12, "music") == ""


def test_a_newer_music_index_is_still_refused():
    why = publish_db.schema_refusal(13, 12, "music")
    assert why and "Deploy the dashboard first" in why


def test_the_property_belongs_to_the_app_not_the_publisher():
    assert publish_db.SPECS["music"]["resteps_after_swap"] is True
    assert publish_db.SPECS["broll"]["resteps_after_swap"] is False
