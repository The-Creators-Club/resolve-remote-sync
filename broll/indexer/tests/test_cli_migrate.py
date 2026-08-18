from __future__ import annotations

import sqlite3

import pytest
import yaml

from broll_index.cli import build_parser, main
from broll_index.migrate import LATEST_VERSION
from test_migrate import V1_SCHEMA


def _write_config(tmp_path, **db_overrides):
    db = {"mode": "sqlite", "path": str(tmp_path / "broll.db")}
    db.update(db_overrides)
    cfg = {
        "shares": {"broll": {"root": str(tmp_path / "broll_root")}},
        "data_root": str(tmp_path / "data"),
        "db": db,
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_migrate_subcommand_parses():
    parser = build_parser()
    args = parser.parse_args(["--config", "config.yaml", "migrate"])
    assert args.command == "migrate"


def test_cli_migrate_upgrades_v1_db(tmp_path, capsys):
    db_path = tmp_path / "broll.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(V1_SCHEMA)
    conn.commit()
    conn.close()

    config_path = _write_config(tmp_path)
    rc = main(["--config", str(config_path), "migrate"])
    assert rc == 0

    out = capsys.readouterr().out
    assert "applied" in out

    conn = sqlite3.connect(str(db_path))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST_VERSION
    finally:
        conn.close()


def test_cli_migrate_refuses_api_mode(tmp_path, capsys):
    config_path = _write_config(tmp_path, mode="api", url="http://example.local/api", token="t")
    rc = main(["--config", str(config_path), "migrate"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "sqlite" in err.lower()
