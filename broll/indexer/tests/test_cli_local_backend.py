"""CLI surface for the local backend: `doctor`, `models pull`, and `run
--tier`'s precedence wiring (CLI > config.yaml > dashboard manifest >
default) — all against fakes, no real GPU/network/model download."""
from __future__ import annotations

import yaml

from broll_index import cli, local_runtime
from broll_index.cli import build_parser, main


def _write_config(tmp_path, extra: str = "") -> str:
    cfg = {
        "shares": {"broll": {"root": str(tmp_path / "root")}},
        "data_root": str(tmp_path / "data"),
        "db": {"mode": "sqlite", "path": str(tmp_path / "broll.db")},
        "indexer": {"backend": "local", "local_cache_dir": str(tmp_path / "cache")},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg) + extra, encoding="utf-8")
    return str(path)


def test_run_parser_accepts_tier_flag():
    parser = build_parser()
    args = parser.parse_args(["--config", "config.yaml", "run", "--tier", "best"])
    assert args.tier == "best"


def test_run_parser_rejects_an_unknown_tier():
    import pytest

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--config", "config.yaml", "run", "--tier", "ultra"])


def test_models_pull_parser_has_tier_and_force():
    parser = build_parser()
    args = parser.parse_args(["--config", "config.yaml", "models", "pull", "--tier", "good", "--force"])
    assert args.models_command == "pull"
    assert args.tier == "good"
    assert args.force is True


def test_doctor_reports_gpu_tier_and_missing_runtime(tmp_path, monkeypatch, capsys):
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(
        local_runtime, "probe_gpu",
        lambda: local_runtime.GpuInfo(present=True, vram_gb=10.0, name="RTX 3080", detail="nvidia-smi"))

    rc = main(["--config", config_path, "doctor"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "backend configured: local" in out
    assert "RTX 3080" in out and "10.0 GB VRAM" in out
    assert "recommended tier: good" in out
    assert "NOT downloaded yet" in out  # nothing pulled in this tmp cache dir


def test_doctor_reports_no_gpu(tmp_path, monkeypatch, capsys):
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(
        local_runtime, "probe_gpu",
        lambda: local_runtime.GpuInfo(present=False, vram_gb=None, detail="nvidia-smi not found"))

    rc = main(["--config", config_path, "doctor"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "GPU: none detected" in out
    assert "recommended tier: none" in out


def test_models_pull_refuses_when_gpu_too_small_without_force(tmp_path, monkeypatch, capsys):
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(
        local_runtime, "probe_gpu",
        lambda: local_runtime.GpuInfo(present=True, vram_gb=6.0, name="tiny gpu"))

    def boom(*a, **k):
        raise AssertionError("must not attempt a download when the tier is refused")

    monkeypatch.setattr(local_runtime, "ensure_runtime", boom)
    monkeypatch.setattr(local_runtime, "ensure_model", boom)

    rc = main(["--config", config_path, "models", "pull", "--tier", "good"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "8 GB" in err


def test_models_pull_force_bypasses_the_refusal_and_calls_the_fetcher(tmp_path, monkeypatch, capsys):
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(
        local_runtime, "probe_gpu",
        lambda: local_runtime.GpuInfo(present=False, vram_gb=None))

    calls = []
    monkeypatch.setattr(local_runtime, "ensure_runtime",
                        lambda cache_dir, **k: (calls.append("runtime"), tmp_path / "llama-server.exe")[1])
    monkeypatch.setattr(local_runtime, "ensure_model",
                        lambda cache_dir, tier, **k: (calls.append("model"), (tmp_path / "w.gguf", tmp_path / "m.gguf"))[1])

    rc = main(["--config", config_path, "models", "pull", "--tier", "good", "--force"])
    assert rc == 0
    assert calls == ["runtime", "model"]
    out = capsys.readouterr().out
    assert "models pull: runtime" in out


def test_run_resolves_tier_via_cli_flag_before_run_pipeline(tmp_path, monkeypatch, capsys):
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(cli, "run_pipeline", lambda cfg, storage, **k: 0)
    rc = main(["--config", config_path, "run", "--tier", "best"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "backend: local" in out
    assert "Best" in out or "8B" in out.lower() or "12 GB" in out
