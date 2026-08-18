"""local_runtime.py: sha256-verified/resumable download, refusal on a bad
hash, GPU probing, and tier recommendation/refusal — all against fakes, no
real network or GPU."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from broll_index import local_runtime
from broll_index.local_models import ModelFile


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _FakeResponse:
    """Minimal context-manager stand-in for `urlopen`'s return value."""

    def __init__(self, data: bytes, status: int = 200):
        self._buf = io.BytesIO(data)
        self.status = status

    def read(self, n=-1):
        return self._buf.read(n)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_opener(payload: bytes, status: int = 200):
    calls = []

    def opener(req):
        calls.append(req)
        return _FakeResponse(payload, status=status)

    opener.calls = calls
    return opener


# ---------------------------------------------------------------------------
# download_verified
# ---------------------------------------------------------------------------

def test_download_verified_writes_the_file_when_hash_matches(tmp_path):
    payload = b"hello world" * 100
    dest = tmp_path / "out.bin"
    opener = _fake_opener(payload)
    got = local_runtime.download_verified(
        "http://example.invalid/f", dest, sha256=_sha256(payload), opener=opener)
    assert got == dest
    assert dest.read_bytes() == payload
    assert len(opener.calls) == 1


def test_download_verified_skips_an_already_correct_file(tmp_path):
    payload = b"already here"
    dest = tmp_path / "out.bin"
    dest.write_bytes(payload)
    opener = _fake_opener(b"should not be fetched")
    got = local_runtime.download_verified(
        "http://example.invalid/f", dest, sha256=_sha256(payload), opener=opener)
    assert got == dest
    assert dest.read_bytes() == payload
    assert opener.calls == []  # no network call at all


def test_download_verified_refuses_and_deletes_on_sha256_mismatch(tmp_path):
    payload = b"tampered content"
    dest = tmp_path / "out.bin"
    opener = _fake_opener(payload)
    with pytest.raises(local_runtime.LocalRuntimeError, match="sha256 mismatch"):
        local_runtime.download_verified(
            "http://example.invalid/f", dest, sha256="0" * 64, opener=opener)
    assert not dest.exists()
    assert not dest.with_suffix(dest.suffix + ".part").exists()


def test_download_verified_re_fetches_a_stale_wrong_hash_file(tmp_path):
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"stale wrong content")
    payload = b"the real content"
    opener = _fake_opener(payload)
    got = local_runtime.download_verified(
        "http://example.invalid/f", dest, sha256=_sha256(payload), opener=opener)
    assert got.read_bytes() == payload
    assert len(opener.calls) == 1


def test_download_verified_wraps_network_errors(tmp_path):
    from urllib.error import URLError

    def opener(req):
        raise URLError("no route to host")

    with pytest.raises(local_runtime.LocalRuntimeError, match="could not download"):
        local_runtime.download_verified(
            "http://example.invalid/f", tmp_path / "out.bin", sha256="0" * 64, opener=opener)


# ---------------------------------------------------------------------------
# ensure_model
# ---------------------------------------------------------------------------

def test_ensure_model_fetches_both_files_for_a_tier(tmp_path, monkeypatch):
    from broll_index import local_models

    weights_payload = b"weights" * 10
    mmproj_payload = b"mmproj" * 10
    fake_tier = local_models.ModelTier(
        key="good", label="Good", description="d", vram_note="n", vram_gb=8, apple_unified_gb=16,
        weights=ModelFile(repo="r", revision="rev", filename="w.gguf",
                          sha256=_sha256(weights_payload), size_bytes=len(weights_payload)),
        mmproj=ModelFile(repo="r", revision="rev", filename="m.gguf",
                         sha256=_sha256(mmproj_payload), size_bytes=len(mmproj_payload)),
        model_label="fake",
    )
    monkeypatch.setattr(local_models, "TIERS", {"good": fake_tier})

    responses = {"w.gguf": weights_payload, "m.gguf": mmproj_payload}

    def opener(req):
        name = req.full_url.rsplit("/", 1)[-1]
        return _FakeResponse(responses[name])

    real_download_verified = local_runtime.download_verified
    monkeypatch.setattr(
        local_runtime, "download_verified",
        lambda url, dest, **kw: real_download_verified(
            url, dest, sha256=kw["sha256"], size_bytes=kw.get("size_bytes"), opener=opener))

    weights_path, mmproj_path = local_runtime.ensure_model(tmp_path, "good", quiet=True)
    assert weights_path.read_bytes() == weights_payload
    assert mmproj_path.read_bytes() == mmproj_payload


def test_ensure_model_unknown_tier_raises():
    with pytest.raises(ValueError, match="unknown model tier"):
        from broll_index import local_models
        local_models.tier("ultra")


# ---------------------------------------------------------------------------
# GPU probe / tier recommendation
# ---------------------------------------------------------------------------

def _run_result(stdout: str, returncode: int = 0):
    return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


def test_probe_gpu_nvidia_smi_reports_vram(monkeypatch):
    monkeypatch.setattr(local_runtime.platform, "system", lambda: "Windows")

    def runner(cmd, **kw):
        return _run_result("NVIDIA GeForce RTX 3080, 10240\n")

    gpu = local_runtime.probe_gpu(runner=runner)
    assert gpu.present
    assert gpu.vram_gb == 10.0
    assert "3080" in gpu.name
    assert not gpu.is_apple_silicon


def test_probe_gpu_no_nvidia_smi_reports_absent(monkeypatch):
    monkeypatch.setattr(local_runtime.platform, "system", lambda: "Windows")

    def runner(cmd, **kw):
        raise FileNotFoundError("nvidia-smi not found")

    gpu = local_runtime.probe_gpu(runner=runner)
    assert not gpu.present
    assert gpu.vram_gb is None


def test_probe_gpu_apple_silicon_uses_sysctl(monkeypatch):
    monkeypatch.setattr(local_runtime.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(local_runtime.platform, "machine", lambda: "arm64")

    def runner(cmd, **kw):
        return _run_result(str(32 * 1024 ** 3) + "\n")

    gpu = local_runtime.probe_gpu(runner=runner)
    assert gpu.present
    assert gpu.is_apple_silicon
    assert gpu.vram_gb == 32.0


def test_recommend_tier_picks_best_when_vram_is_enough():
    gpu = local_runtime.GpuInfo(present=True, vram_gb=16.0, name="4080")
    assert local_runtime.recommend_tier(gpu) == "best"


def test_recommend_tier_picks_good_for_a_10gb_card():
    gpu = local_runtime.GpuInfo(present=True, vram_gb=10.0, name="3080")
    assert local_runtime.recommend_tier(gpu) == "good"


def test_recommend_tier_none_for_a_small_or_absent_gpu():
    assert local_runtime.recommend_tier(local_runtime.GpuInfo(present=True, vram_gb=4.0)) is None
    assert local_runtime.recommend_tier(local_runtime.GpuInfo(present=False, vram_gb=None)) is None


def test_recommend_tier_apple_silicon_uses_the_higher_unified_memory_floor():
    # 10 GB unified memory would be "good" on a discrete GPU floor (8 GB) but
    # Apple Silicon's floor is 16 GB — shared with the OS.
    gpu = local_runtime.GpuInfo(present=True, vram_gb=10.0, is_apple_silicon=True)
    assert local_runtime.recommend_tier(gpu) is None


def test_refuse_if_tier_unfit_raises_the_documented_message():
    gpu = local_runtime.GpuInfo(present=True, vram_gb=10.0, name="3080")
    with pytest.raises(local_runtime.LocalRuntimeError, match="Best needs 12 GB VRAM"):
        local_runtime.refuse_if_tier_unfit("best", gpu)


def test_refuse_if_tier_unfit_suggests_good_as_the_alternative():
    gpu = local_runtime.GpuInfo(present=True, vram_gb=10.0)
    with pytest.raises(local_runtime.LocalRuntimeError, match="choose Good"):
        local_runtime.refuse_if_tier_unfit("best", gpu)


def test_refuse_if_tier_unfit_force_bypasses_the_check():
    gpu = local_runtime.GpuInfo(present=False, vram_gb=None)
    local_runtime.refuse_if_tier_unfit("best", gpu, force=True)  # must not raise


def test_refuse_if_tier_unfit_no_gpu_message_names_the_alternative():
    gpu = local_runtime.GpuInfo(present=False, vram_gb=None, detail="nvidia-smi not found")
    with pytest.raises(local_runtime.LocalRuntimeError, match="no GPU detected"):
        local_runtime.refuse_if_tier_unfit("good", gpu)


def test_refuse_if_tier_unfit_ok_when_gpu_is_large_enough():
    gpu = local_runtime.GpuInfo(present=True, vram_gb=24.0, name="4090")
    local_runtime.refuse_if_tier_unfit("best", gpu)  # must not raise


# ---------------------------------------------------------------------------
# default_cache_dir / platform_key
# ---------------------------------------------------------------------------

def test_default_cache_dir_windows(monkeypatch):
    monkeypatch.setattr(local_runtime.platform, "system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")
    p = local_runtime.default_cache_dir()
    assert p == Path(r"C:\Users\someone\AppData\Local") / "ccsync" / "indexer"


def test_default_cache_dir_macos(monkeypatch):
    monkeypatch.setattr(local_runtime.platform, "system", lambda: "Darwin")
    p = local_runtime.default_cache_dir()
    assert p == Path.home() / "Library" / "Application Support" / "ccsync" / "indexer"


def test_default_cache_dir_linux(monkeypatch):
    monkeypatch.setattr(local_runtime.platform, "system", lambda: "Linux")
    p = local_runtime.default_cache_dir()
    assert p == Path.home() / ".cache" / "ccsync" / "indexer"


def test_platform_key_unsupported_raises(monkeypatch):
    monkeypatch.setattr(local_runtime.platform, "system", lambda: "Plan9")
    with pytest.raises(local_runtime.LocalRuntimeError, match="unsupported platform"):
        local_runtime.platform_key()
