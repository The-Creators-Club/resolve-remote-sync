from __future__ import annotations

from pathlib import Path

import yaml

from broll_index.cli import build_parser, main
from broll_index.storage.sqlite_backend import SqliteBackend


def _write_config(tmp_path: Path, share_root: Path) -> Path:
    cfg = {
        "shares": {"broll": {"root": str(share_root)}},
        "data_root": str(tmp_path / "data"),
        "db": {"mode": "sqlite", "path": str(tmp_path / "broll.db")},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_duplicates_subcommand_parses():
    parser = build_parser()
    args = parser.parse_args(["--config", "config.yaml", "duplicates"])
    assert args.command == "duplicates"
    assert args.verify is True  # verify on by default
    assert args.apply is False


def test_duplicates_no_verify_flag_parses():
    parser = build_parser()
    args = parser.parse_args(["--config", "config.yaml", "duplicates", "--no-verify"])
    assert args.verify is False


def test_cli_duplicates_dry_run_writes_report(tmp_path, capsys):
    share_root = tmp_path / "broll_root"
    share_root.mkdir()
    (share_root / "a.mov").write_bytes(b"same content")
    (share_root / "b.mov").write_bytes(b"same content")

    config_path = _write_config(tmp_path, share_root)
    db = SqliteBackend(tmp_path / "broll.db")
    db.upsert_video("broll", "a.mov", hash="h1", status="probed")
    db.upsert_video("broll", "b.mov", hash="h1", status="indexed")
    db.close()

    out_path = tmp_path / "dup_report.md"
    rc = main(["--config", str(config_path), "duplicates", "--out", str(out_path)])
    assert rc == 0

    out = capsys.readouterr().out
    assert "duplicate(s) to mark" in out
    assert "DRY RUN" in out
    assert out_path.exists()

    # dry run: nothing written to the DB
    db2 = SqliteBackend(tmp_path / "broll.db")
    rows = db2.all_videos()
    db2.close()
    assert all(r["duplicate_of"] is None for r in rows)


def test_cli_duplicates_apply_marks_and_is_idempotent(tmp_path, capsys):
    share_root = tmp_path / "broll_root"
    share_root.mkdir()
    (share_root / "a.mov").write_bytes(b"same content")
    (share_root / "b.mov").write_bytes(b"same content")

    config_path = _write_config(tmp_path, share_root)
    db = SqliteBackend(tmp_path / "broll.db")
    v1 = db.upsert_video("broll", "a.mov", hash="h1", status="probed")
    v2 = db.upsert_video("broll", "b.mov", hash="h1", status="indexed")
    db.close()

    out_path = tmp_path / "dup_report.md"
    rc = main(["--config", str(config_path), "duplicates", "--apply", "--out", str(out_path)])
    assert rc == 0

    db2 = SqliteBackend(tmp_path / "broll.db")
    row1 = db2.get_video(v1)
    row2 = db2.get_video(v2)
    db2.close()
    assert row1["duplicate_of"] == v2
    assert row2["duplicate_of"] is None

    # re-run: idempotent, nothing left to mark
    rc2 = main(["--config", str(config_path), "duplicates", "--apply", "--out", str(out_path)])
    assert rc2 == 0
    out2 = capsys.readouterr().out
    assert "0 duplicate(s) to mark" in out2

    db3 = SqliteBackend(tmp_path / "broll.db")
    row1_after = db3.get_video(v1)
    row2_after = db3.get_video(v2)
    db3.close()
    assert row1_after == row1
    assert row2_after == row2


def test_cli_duplicates_no_verify_prints_warning(tmp_path, capsys):
    share_root = tmp_path / "broll_root"
    share_root.mkdir()

    config_path = _write_config(tmp_path, share_root)
    db = SqliteBackend(tmp_path / "broll.db")
    db.upsert_video("broll", "a.mov", hash="h1", status="probed")
    db.upsert_video("broll", "b.mov", hash="h1", status="indexed")
    db.close()

    out_path = tmp_path / "dup_report.md"
    rc = main(["--config", str(config_path), "duplicates", "--no-verify", "--out", str(out_path)])
    assert rc == 0

    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "--no-verify" in err
    assert "data" in err.lower() or "loss" in err.lower() or "lose" in err.lower()
