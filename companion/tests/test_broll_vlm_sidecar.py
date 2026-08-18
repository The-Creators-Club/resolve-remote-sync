"""broll_vlm_sidecar.py: the companion's gates around the vendored local-VLM
backend -- GPU fit, free space, the download host allow-list, progress
reporting, and the refusal to ever run the model on a CPU.

Nothing here downloads anything or touches a GPU: `probe_gpu`'s runner is a
fake, the tier catalogue is replaced with byte-sized stand-ins, and the
"downloads" are payloads built in the test. LOCALAPPDATA is redirected so the
cache dir can never be the developer's real one (test_sidecar_tools' rule).
"""

from __future__ import annotations

import hashlib
import io
import threading
import zipfile
from pathlib import Path

import pytest

from ccsync_companion import broll_vlm_sidecar as sc
from ccsync_companion.broll_vlm import local_models, local_runtime


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    sc.reset_caches()
    yield
    sc.reset_caches()


def _gpu(present=True, vram=8.0, apple=False, detail="nvidia-smi", name="RTX 3080"):
    return {"present": present, "vram_gb": vram, "detail": detail,
            "apple_silicon": apple, "name": name}


def _fake_nvidia_smi(vram_mb: int, name: str = "NVIDIA GeForce RTX 3080"):
    """A `runner` shaped like subprocess.run's return, for probe_gpu."""
    class _Result:
        returncode = 0
        stdout = f"{name}, {vram_mb}\n"
        stderr = ""

    def runner(args, **kwargs):
        assert args[0] == "nvidia-smi"
        return _Result()

    return runner


# ---------------------------------------------------------------------------
# the GPU probe goes through the vendored code with OUR subprocess flags
# ---------------------------------------------------------------------------

def test_gpu_probe_uses_the_companions_window_suppressed_runner(monkeypatch):
    """An unflagged spawn flashes a console on the editor's desktop; this one
    runs every ten minutes, unattended, for the life of the tray."""
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["creationflags"] = kwargs.get("creationflags")

        class _R:
            returncode = 0
            stdout = "NVIDIA GeForce RTX 3080, 10240\n"
            stderr = ""
        return _R()

    monkeypatch.setattr(sc.subprocess, "run", fake_run)
    # The probe branches on the OS before it spawns anything; pin it so this
    # asserts the same thing on a Mac runner as it does here.
    monkeypatch.setattr(local_runtime.platform, "system", lambda: "Windows")
    info = sc.gpu(force=True)
    assert info["present"] is True
    assert info["vram_gb"] == 10.0
    assert "creationflags" in seen  # always passed, 0 off Windows


def test_gpu_probe_never_raises(monkeypatch):
    monkeypatch.setattr(sc, "_runtime", lambda: (_ for _ in ()).throw(OSError("boom")))
    info = sc.gpu(force=True)
    assert info["present"] is False
    assert "boom" in info["detail"]


def test_gpu_probe_is_cached(monkeypatch):
    calls = []

    def fake_probe(runner=None):
        calls.append(1)
        return local_runtime.GpuInfo(present=True, vram_gb=12.0, name="x", detail="d")

    monkeypatch.setattr(local_runtime, "probe_gpu", fake_probe)
    sc.gpu(force=True)
    sc.gpu()
    sc.gpu()
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# fits(): the refusal an editor actually reads
# ---------------------------------------------------------------------------

def test_best_on_an_8gb_card_is_the_plans_exact_sentence():
    """docs/BROLL_INGEST_PLAN.md's owner review fixes this wording, and the
    tray balloon, the tray menu line and the page all print it verbatim. It is
    pinned here character for character on purpose -- an em dash that became a
    hyphen is a different sentence in three places at once."""
    ok, message = sc.fits("best", _gpu(vram=8.0))
    assert ok is False
    assert message == ("Can't index b-roll: Best needs 12 GB VRAM, this GPU has 8 GB "
                       "- choose Good")


def test_good_on_a_small_card_does_not_offer_good_as_the_alternative():
    ok, message = sc.fits("good", _gpu(vram=4.0))
    assert ok is False
    assert "Good needs 8 GB VRAM, this GPU has 4 GB" in message
    assert "choose Good" not in message
    assert "bigger GPU" in message


def test_apple_silicon_is_told_about_unified_memory_not_vram():
    ok, message = sc.fits("best", _gpu(vram=16.0, apple=True, detail="sysctl hw.memsize",
                                       name="Apple Silicon (unified memory)"))
    assert ok is False
    assert message == ("Can't index b-roll: Best needs 24 GB unified memory, this Mac "
                       "has 16 GB - choose Good")


def test_a_big_enough_gpu_fits_with_no_message():
    assert sc.fits("best", _gpu(vram=24.0)) == (True, "")
    assert sc.fits("good", _gpu(vram=8.0)) == (True, "")


def test_no_gpu_refuses_every_tier():
    no_gpu = _gpu(present=False, vram=None, detail="nvidia-smi not found or no GPU")
    for tier in ("good", "best"):
        ok, message = sc.fits(tier, no_gpu)
        assert ok is False
        assert "no usable GPU" in message
        assert "nvidia-smi not found" in message


def test_a_fractional_vram_reading_keeps_its_digit():
    ok, message = sc.fits("best", _gpu(vram=7.8))
    assert "this GPU has 7.8 GB" in message
    assert ok is False


def test_recommended_tier_maps_the_probe_onto_the_catalogue():
    assert sc.recommended_tier(_gpu(vram=24.0)) == "best"
    assert sc.recommended_tier(_gpu(vram=8.0)) == "good"
    assert sc.recommended_tier(_gpu(vram=4.0)) is None
    assert sc.recommended_tier(_gpu(present=False, vram=None)) is None


# ---------------------------------------------------------------------------
# the download host allow-list
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://github.com/ggml-org/llama.cpp/releases/download/b10470/llama.zip",
    "https://objects.githubusercontent.com/x/y",
    "https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF/resolve/rev/w.gguf",
    "https://cdn-lfs-us-1.huggingface.co/repos/aa/bb/w.gguf",
])
def test_the_hosts_the_pins_actually_use_are_allowed(url):
    assert sc.host_allowed(url) is True


@pytest.mark.parametrize("url", [
    "https://example.com/model.gguf",
    "https://evil-huggingface.co/w.gguf",          # a suffix test would pass this
    "https://huggingface.co.evil.test/w.gguf",
    "https://github.com.evil.test/llama.zip",
    "http://127.0.0.1:8080/w.gguf",
])
def test_a_lookalike_host_is_refused(url):
    assert sc.host_allowed(url) is False


def test_every_url_the_catalogue_builds_is_on_the_allow_list():
    """The pins themselves, not a hand-written list: if a bumped release moves
    to a host this build does not trust, the refusal has to surface here and
    not on an editor's machine at 2 a.m."""
    for tier in local_models.VALID_TIERS:
        urls = sc.planned_urls(tier)
        assert urls, tier
        for url in urls:
            assert sc.host_allowed(url), url


def test_ensure_refuses_a_pin_that_points_off_the_allow_list(monkeypatch, _fake_tier):
    monkeypatch.setattr(local_models, "TIERS", {"good": _fake_tier(
        weights_url="https://example.com/w.gguf")})
    monkeypatch.setattr(sc, "gpu", lambda force=False: _gpu(vram=24.0))
    ok, message = sc.ensure("good")
    assert ok is False
    assert "example.com" in message
    assert "not one of the hosts" in message


# ---------------------------------------------------------------------------
# free space
# ---------------------------------------------------------------------------

def test_required_bytes_counts_the_extraction_peak_and_the_upgrade_margin():
    from ccsync_companion import upgrade as upgrade_mod

    tier = local_models.TIERS["good"]
    needed = sc.required_bytes("good")
    assert needed > tier.weights.size_bytes + tier.mmproj.size_bytes
    assert needed > upgrade_mod.MIN_FREE_BYTES_MARGIN


def test_free_space_refusal_names_the_numbers(monkeypatch):
    monkeypatch.setattr(sc.shutil, "disk_usage",
                        lambda p: type("U", (), {"free": 3 * 1000 ** 3})())
    message = sc.free_space_refusal("good")
    assert message is not None
    assert "Not enough disk space" in message
    assert "3.0 GB" in message


def test_free_space_that_cannot_be_measured_is_not_a_refusal(monkeypatch):
    def boom(_p):
        raise OSError("no such device")

    monkeypatch.setattr(sc.shutil, "disk_usage", boom)
    assert sc.free_space_refusal("good") is None


def test_ensure_refuses_before_downloading_anything_when_the_disk_is_full(monkeypatch):
    monkeypatch.setattr(sc, "gpu", lambda force=False: _gpu(vram=24.0))
    monkeypatch.setattr(sc.shutil, "disk_usage",
                        lambda p: type("U", (), {"free": 1000 ** 3})())

    def never(*a, **kw):
        raise AssertionError("a download was started despite the free-space refusal")

    monkeypatch.setattr(local_runtime, "ensure_runtime", never)
    monkeypatch.setattr(local_runtime, "ensure_model", never)

    ok, message = sc.ensure("good")
    assert ok is False
    assert "Not enough disk space" in message
    assert sc.status()["last_error"] == message


# ---------------------------------------------------------------------------
# never CPU inference
# ---------------------------------------------------------------------------

def test_ensure_will_not_fetch_a_model_this_gpu_could_never_run(monkeypatch):
    monkeypatch.setattr(sc, "gpu", lambda force=False: _gpu(vram=8.0))

    def never(*a, **kw):
        raise AssertionError("downloaded a model the GPU cannot run")

    monkeypatch.setattr(local_runtime, "ensure_runtime", never)
    ok, message = sc.ensure("best")
    assert ok is False
    assert message.startswith("Can't index b-roll: Best needs 12 GB VRAM")


def test_server_refuses_outright_when_there_is_no_gpu(monkeypatch):
    monkeypatch.setattr(sc, "gpu", lambda force=False: _gpu(present=False, vram=None))
    with pytest.raises(sc.SidecarError, match="no usable GPU"):
        sc.server("good")


def test_server_refuses_when_the_model_is_not_downloaded(monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "gpu", lambda force=False: _gpu(vram=24.0))
    monkeypatch.setattr(sc, "runtime_exe", lambda: tmp_path / "llama-server.exe")
    monkeypatch.setattr(sc, "model_ready", lambda tier: False)
    with pytest.raises(sc.SidecarError, match="not downloaded"):
        sc.server("good")


def test_server_refuses_when_the_runtime_is_not_installed(monkeypatch):
    monkeypatch.setattr(sc, "gpu", lambda force=False: _gpu(vram=24.0))
    monkeypatch.setattr(sc, "runtime_exe", lambda: None)
    with pytest.raises(sc.SidecarError, match="runtime is not installed"):
        sc.server("good")


# ---------------------------------------------------------------------------
# the fetch itself: progress, stderr, checksum, stop
# ---------------------------------------------------------------------------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip_bytes(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


class _FakeResponse:
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


@pytest.fixture
def _fake_tier():
    """A tier whose 'weights' are a handful of bytes."""
    def make(weights: bytes = b"w" * 2048, mmproj: bytes = b"m" * 1024,
             weights_url: str = "") -> local_models.ModelTier:
        w = local_models.ModelFile(
            repo="Qwen/fake", revision="rev", filename="w.gguf",
            sha256=_sha(weights), size_bytes=len(weights))
        if weights_url:
            w = _UrlOverride(w, weights_url)
        return local_models.ModelTier(
            key="good", label="Good", description="fake", vram_note="n",
            vram_gb=8, apple_unified_gb=16, weights=w,
            mmproj=local_models.ModelFile(
                repo="Qwen/fake", revision="rev", filename="m.gguf",
                sha256=_sha(mmproj), size_bytes=len(mmproj)),
            model_label="fake")
    return make


class _UrlOverride:
    """A ModelFile whose `url` points somewhere else -- how a moved pin, or a
    tampered catalogue, would look to the allow-list."""

    def __init__(self, inner, url):
        self._inner = inner
        self.url = url

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.fixture
def _fake_catalogue(monkeypatch, _fake_tier):
    """A whole catalogue -- tier + platform runtime -- made of tiny payloads,
    with download_verified routed through a fake opener that KEEPS the
    progress argument (that is what is under test)."""
    weights, mmproj = b"w" * 2048, b"m" * 1024
    archive = _zip_bytes({"llama-server.exe": b"binary"})
    tier = _fake_tier(weights, mmproj)
    build = local_models.RuntimeBuild(
        platform="windows", label="fake llama.cpp", backend="cuda",
        server_binary="llama-server.exe",
        archive=local_models.RuntimeAsset(
            name="llama.zip", sha256=_sha(archive), size_bytes=len(archive)),
    )
    monkeypatch.setattr(local_models, "TIERS", {"good": tier})
    monkeypatch.setattr(local_models, "RUNTIMES", {"windows": build})
    monkeypatch.setattr(local_runtime, "platform_key", lambda: "windows")
    monkeypatch.setattr(sc, "gpu", lambda force=False: _gpu(vram=24.0))

    payloads = {"llama.zip": archive, "w.gguf": weights, "m.gguf": mmproj}

    def opener(req):
        return _FakeResponse(payloads[req.full_url.rsplit("/", 1)[-1]])

    real = local_runtime.download_verified
    monkeypatch.setattr(
        local_runtime, "download_verified",
        lambda url, dest, **kw: real(url, dest, sha256=kw["sha256"],
                                     size_bytes=kw.get("size_bytes"),
                                     progress=kw.get("progress"), opener=opener))
    return {"payloads": payloads, "tier": tier, "build": build}


def test_ensure_downloads_and_reports_progress(_fake_catalogue):
    seen = []
    ok, message = sc.ensure("good", progress_cb=lambda *a: seen.append(a))
    assert ok is True, message
    names = [name for name, _w, _t in seen]
    assert names == ["llama.zip", "w.gguf", "m.gguf"]
    assert seen[-1][1] == seen[-1][2]  # finished: written == total
    assert sc.status()["downloading"] is None
    assert sc.status()["model_ready"]["good"] is True
    assert sc.status()["runtime_ready"] is True


def test_ensure_writes_nothing_to_stderr(monkeypatch, _fake_catalogue):
    """The tray is a WINDOWED build: sys.stderr is None there, so any print
    left in the vendored fetcher's path raises on the first chunk of a 2.5 GB
    download. Setting it to None here is that machine."""
    monkeypatch.setattr(local_runtime.sys, "stderr", None)
    ok, message = sc.ensure("good")
    assert ok is True, message


def test_status_reports_the_download_in_flight(_fake_catalogue):
    snapshots = []

    def cb(name, written, total):
        snapshots.append(sc.status()["downloading"])

    sc.ensure("good", progress_cb=cb)
    assert snapshots
    first = snapshots[0]
    assert first["name"] == "llama.zip"
    assert first["percent"] == 100  # the fake payload arrives in one chunk


def test_a_checksum_mismatch_deletes_the_file_and_says_so(monkeypatch, _fake_catalogue):
    """A rotten download must not be kept: the retry would fail identically
    forever, and the message has to tell the editor which of the two it is."""
    good = local_models.TIERS["good"]
    monkeypatch.setattr(local_models, "TIERS", {"good": local_models.ModelTier(
        key="good", label="Good", description="fake", vram_note="n", vram_gb=8,
        apple_unified_gb=16,
        weights=local_models.ModelFile(repo="r", revision="rev", filename="w.gguf",
                                       sha256="00" * 32, size_bytes=good.weights.size_bytes),
        mmproj=good.mmproj, model_label="fake")})

    ok, message = sc.ensure("good")
    assert ok is False
    assert "checksum did not match" in message
    weights, _mmproj = sc.model_files("good")
    assert not weights.exists()
    assert sc.status()["last_error"] == message


def test_a_stop_event_aborts_the_download_and_keeps_the_partial(_fake_catalogue):
    stop = threading.Event()
    stop.set()
    ok, message = sc.ensure("good", stop_event=stop)
    assert ok is False
    assert "stopped" in message
    assert sc.status()["downloading"] is None


def test_ensure_never_raises_when_the_fetch_blows_up(monkeypatch):
    monkeypatch.setattr(sc, "gpu", lambda force=False: _gpu(vram=24.0))
    monkeypatch.setattr(sc, "free_space_refusal", lambda *a, **kw: None)
    monkeypatch.setattr(local_runtime, "ensure_runtime",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("disk on fire")))
    ok, message = sc.ensure("good")
    assert ok is False
    assert "disk on fire" in message


# ---------------------------------------------------------------------------
# status() is zero-I/O
# ---------------------------------------------------------------------------

def test_status_touches_no_disk_and_spawns_nothing(monkeypatch):
    """It rides the reporter's tick and every tray menu build. refresh() is
    the half that is allowed to stat."""
    def boom(*a, **kw):
        raise AssertionError("status() did I/O")

    monkeypatch.setattr(sc.subprocess, "run", boom)
    monkeypatch.setattr(sc.Path, "is_file", boom)
    monkeypatch.setattr(sc.shutil, "disk_usage", boom)
    snap = sc.status()
    assert set(snap) == {"runtime_ready", "model_ready", "gpu", "downloading", "last_error"}
    assert set(snap["model_ready"]) == {"good", "best"}


def test_refresh_fills_the_snapshot_from_disk(monkeypatch, _fake_catalogue):
    sc.ensure("good")
    sc.reset_caches()
    snap = sc.refresh(force=True)
    assert snap["runtime_ready"] is True
    assert snap["model_ready"]["good"] is True
    assert snap["gpu"]["present"] is True


def test_cache_dir_is_under_the_companions_tools_dir():
    assert sc.cache_dir().name == "broll-vlm"
    assert sc.cache_dir().parent.name == "tools"


def test_the_server_log_lives_in_the_state_dir():
    path = sc.server_log_path({})
    assert path.name == "broll_vlm_server.log"
    assert path.parent.name == "state"
    assert path.parent.parent == Path("~/.ccsync").expanduser()
