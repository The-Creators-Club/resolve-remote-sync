from __future__ import annotations

import yaml

from broll_index.cli import build_parser, main
from broll_index.storage.sqlite_backend import SqliteBackend


def _write_config(tmp_path):
    cfg = {
        "shares": {"broll": {"root": str(tmp_path / "broll_root")}},
        "data_root": str(tmp_path / "data"),
        "db": {"mode": "sqlite", "path": str(tmp_path / "broll.db")},
        # Disabled so this test never risks touching a real whisper install even
        # if one happens to exist on the machine running it — see broll_index.pipeline
        # .stage_transcribe's cfg.whisper.enabled guard.
        "whisper": {"enabled": False},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_transcribe_subcommand_parses():
    parser = build_parser()
    args = parser.parse_args(["--config", "config.yaml", "transcribe", "--limit", "5"])
    assert args.command == "transcribe"
    assert args.limit == 5


def test_cli_transcribe_runs_transcribe_stage_only(tmp_path, capsys):
    config_path = _write_config(tmp_path)
    backend = SqliteBackend(tmp_path / "broll.db")
    (tmp_path / "broll_root").mkdir(parents=True)
    (tmp_path / "broll_root" / "clip.mov").write_bytes(b"x")
    vid = backend.upsert_video("broll", "clip.mov", status="proxied")
    backend.close()

    rc = main(["--config", str(config_path), "transcribe"])
    assert rc == 0

    out = capsys.readouterr().out
    assert "transcribe: processed 1 video(s)" in out

    backend = SqliteBackend(tmp_path / "broll.db")
    row = backend.get_video(vid)
    # whisper.enabled: false -> stage_transcribe skips cleanly, never touches status
    assert row["status"] == "proxied"
    assert row["transcribed_at"] is None
    backend.close()
