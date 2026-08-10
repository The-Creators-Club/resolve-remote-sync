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


def test_export_manifest_subcommand_parses():
    parser = build_parser()
    args = parser.parse_args(["--config", "config.yaml", "export-manifest", "--out", "m.txt"])
    assert args.command == "export-manifest"
    assert args.format == "list"


def _seed_db(tmp_path, share_root):
    config_path = _write_config(tmp_path, share_root)
    db = SqliteBackend(tmp_path / "broll.db")
    keep = db.upsert_video("broll", "military/clip1.mov", status="indexed", size_bytes=1000)
    dup = db.upsert_video("broll", "military/clip1_copy.mov", status="probed", size_bytes=1000)
    other = db.upsert_video("broll", "news/clip2.mov", status="indexed", size_bytes=500)
    db.update_video(dup, duplicate_of=keep)
    db.close()
    return config_path, keep, dup, other


def test_cli_export_manifest_list_format(tmp_path, capsys):
    share_root = tmp_path / "broll_root"
    share_root.mkdir()
    config_path, keep, dup, other = _seed_db(tmp_path, share_root)

    out_path = tmp_path / "manifest.txt"
    rc = main(["--config", str(config_path), "export-manifest", "--out", str(out_path), "--format", "list"])
    assert rc == 0

    out = capsys.readouterr().out
    assert "2 file(s) to copy" in out
    assert "1 duplicate(s) skipped" in out
    assert "1000 byte(s) saved" in out

    content = out_path.read_text(encoding="utf-8")
    assert "clip1_copy.mov" not in content
    assert "clip1.mov" in content
    assert "clip2.mov" in content


def test_cli_export_manifest_robocopy_format(tmp_path):
    share_root = tmp_path / "broll_root"
    share_root.mkdir()
    config_path, keep, dup, other = _seed_db(tmp_path, share_root)

    out_path = tmp_path / "manifest.bat"
    rc = main(["--config", str(config_path), "export-manifest", "--out", str(out_path), "--format", "robocopy"])
    assert rc == 0

    content = out_path.read_text(encoding="utf-8")
    assert content.startswith("@echo off")
    assert "robocopy" in content
    assert "clip1_copy.mov" not in content


def test_cli_export_manifest_rsync_format(tmp_path):
    share_root = tmp_path / "broll_root"
    share_root.mkdir()
    config_path, keep, dup, other = _seed_db(tmp_path, share_root)

    out_path = tmp_path / "manifest.files"
    rc = main(["--config", str(config_path), "export-manifest", "--out", str(out_path), "--format", "rsync"])
    assert rc == 0

    lines = [ln for ln in out_path.read_text(encoding="utf-8").splitlines() if ln]
    assert "broll/military/clip1.mov" in lines
    assert "broll/news/clip2.mov" in lines
    assert not any("clip1_copy" in ln for ln in lines)


def test_cli_export_manifest_cjk_paths_round_trip_utf8(tmp_path):
    share_root = tmp_path / "broll_root"
    share_root.mkdir()
    config_path = _write_config(tmp_path, share_root)
    db = SqliteBackend(tmp_path / "broll.db")
    db.upsert_video("broll", "軍事/演習畫面.mov", status="indexed", size_bytes=10)
    db.close()

    out_path = tmp_path / "manifest.txt"
    rc = main(["--config", str(config_path), "export-manifest", "--out", str(out_path)])
    assert rc == 0

    content = out_path.read_text(encoding="utf-8")
    assert "演習畫面.mov" in content
