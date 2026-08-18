# VENDORED VERBATIM from broll/indexer/broll_index/local_runtime.py -- DO NOT EDIT HERE.
# Edit the indexer's copy and re-copy it in BELOW THE MARKER LINE at the end of
# this header; everything under that line is byte-identical to the source on
# purpose, so the two trees can be compared mechanically -- and they are:
# tools/release.ps1 strips this header, byte-compares the rest against the
# source and REFUSES to build on a mismatch, and
# server/tests/test_cross_component.py pins the same comparison in the suites.
# Same mechanism as ccsync_companion/ytdl_common.py (2026-08-14).
#
# Why a copy and not an import (docs/BROLL_INGEST_PLAN.md section 3.3): the
# companion is a frozen, windowed PyInstaller build, and importing
# `broll_index` would drag anthropic, xxhash, pyyaml, requests and jieba into
# every editor's tray app -- ~50 MB and a licence surface -- for five modules
# that between them need nothing but the stdlib and Pillow. The MODULE NAMES
# are deliberately unchanged so the relative imports inside them keep
# resolving inside this sub-package.
#
# What the indexer must therefore never do to these five: import
# claude_client (that is what contract.py exists to avoid), or add a
# third-party import. broll/indexer/tests/test_contract.py fails on either.
#
# The marker is the LAST line of this header and appears exactly once (both
# the gate and the test refuse an absent or ambiguous marker rather than
# skipping). Nothing but the source file's own bytes may follow it.
# --- vendored content below, byte-identical ---
"""Fetch and verify the local-VLM runtime (llama.cpp) and model weights, and
probe the GPU to recommend a tier. `broll-index models pull` / `broll-index
doctor` are the CLI surface (see cli.py); `local_vlm.py` calls `ensure_runtime`
/ `ensure_model` before it ever starts `llama-server`.

Every download is sha256-verified against `local_models.py`'s pins before
being trusted — a bad hash is a refusal, never a warning, per
`broll/docs/local-indexing-options-2026-08-17.md` §3.3 ("the downloader should
refuse a model id that is not on an allow-list"). Downloads are resumable
(HTTP Range) and progress goes to stderr, never stdout, so `doctor`'s and
`models pull`'s own prints stay readable.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from . import local_models
from .local_models import ModelFile, ModelTier, RuntimeAsset, RuntimeBuild

logger = logging.getLogger(__name__)

CHUNK = 1024 * 1024  # 1 MiB


class LocalRuntimeError(RuntimeError):
    """A refusal: bad hash, unsupported platform, missing hardware. Always
    carries an actionable message — see the docstrings below for the shape."""


# ---------------------------------------------------------------------------
# cache directory
# ---------------------------------------------------------------------------

def default_cache_dir() -> Path:
    """Per-OS default for `[indexer] local_cache_dir`, matching CLAUDE.md's task:
    Windows `%LOCALAPPDATA%\\ccsync\\indexer`, macOS
    `~/Library/Application Support/ccsync/indexer`, Linux `~/.cache/ccsync/indexer`.
    """
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ccsync" / "indexer"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "ccsync" / "indexer"
    return Path.home() / ".cache" / "ccsync" / "indexer"


def platform_key() -> str:
    system = platform.system()
    if system == "Windows":
        return "windows"
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        return "linux"
    raise LocalRuntimeError(f"unsupported platform for the local backend: {system!r}")


# ---------------------------------------------------------------------------
# sha256-verified, resumable download
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def download_verified(
    url: str,
    dest: Path,
    *,
    sha256: str,
    size_bytes: int | None = None,
    progress: Callable[[int, int | None], None] | None = None,
    opener: Callable[[Request], Any] = urlopen,
) -> Path:
    """Download `url` to `dest`, verifying sha256 before returning it.

    Resumable: a partial `dest` (from a previous run, or a killed download) is
    continued with an HTTP Range request. The final file is hashed and, on
    mismatch, DELETED and LocalRuntimeError is raised — a corrupt or
    tampered-with download must never be silently kept around to be reused by
    the next run.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    # Already complete and correct: nothing to do. Checked BEFORE opening a
    # connection so an offline re-run of an already-fetched model works.
    if dest.is_file() and dest.stat().st_size > 0:
        if _sha256_file(dest) == sha256:
            return dest
        logger.warning("local_runtime: %s failed re-verification, re-downloading", dest)
        dest.unlink()

    resume_from = tmp.stat().st_size if tmp.is_file() else 0
    headers = {}
    if resume_from:
        headers["Range"] = f"bytes={resume_from}-"

    req = Request(url, headers=headers)
    try:
        resp = opener(req)
    except (HTTPError, URLError) as e:
        raise LocalRuntimeError(f"could not download {url}: {e}") from e

    mode = "ab" if resume_from else "wb"
    # A server that ignores Range (no 206) restarts from zero rather than
    # silently corrupting the file with a duplicated prefix.
    status = getattr(resp, "status", 200) or 200
    if resume_from and status != 206:
        resume_from = 0
        mode = "wb"

    written = resume_from
    with open(tmp, mode) as f:
        while True:
            chunk = resp.read(CHUNK)
            if not chunk:
                break
            f.write(chunk)
            written += len(chunk)
            if progress is not None:
                progress(written, size_bytes)
    resp.close()

    got = _sha256_file(tmp)
    if got != sha256:
        tmp.unlink(missing_ok=True)
        raise LocalRuntimeError(
            f"sha256 mismatch downloading {url}: expected {sha256}, got {got} "
            "— refusing to use this file. Re-run to retry the download."
        )
    tmp.replace(dest)
    return dest


def _stderr_progress(label: str) -> Callable[[int, int | None], None]:
    def _p(written: int, total: int | None) -> None:
        if total:
            pct = written * 100 // total
            print(f"\r  {label}: {written/1e6:.0f}/{total/1e6:.0f} MB ({pct}%)",
                  end="", file=sys.stderr, flush=True)
        else:
            print(f"\r  {label}: {written/1e6:.0f} MB", end="", file=sys.stderr, flush=True)
    return _p


# (asset name, bytes written, total bytes or None) -> None. What a HOST
# APPLICATION passes to ensure_runtime/ensure_model instead of watching stderr.
# Added 2026-08-18 for the companion (docs/BROLL_INGEST_PLAN.md §3.4): the
# frozen tray app is a WINDOWED build, so `sys.stderr` is None there and every
# print below would raise on the first chunk of a 2.5 GB download. When a
# callback is given, nothing in this module touches stderr at all -- not the
# per-chunk line, not the "fetching ..." banner, not the trailing newline.
# That is the contract the companion's sidecar relies on, and what its test
# asserts by running the whole fetch with sys.stderr set to None.
ProgressFn = Callable[[str, int, "int | None"], None]


def _progress_for(label: str, progress: "ProgressFn | None", quiet: bool):
    """The per-chunk callback download_verified should use, or None.

    Precedence: an explicit `progress` beats `quiet`, because a caller that
    passed one is asking for the bytes, not for prints it cannot see.
    """
    if progress is not None:
        return lambda written, total: progress(label, written, total)
    return None if quiet else _stderr_progress(label)


def _say(message: str, *, quiet: bool, progress: "ProgressFn | None") -> None:
    """A banner line on stderr -- suppressed entirely when a callback is in
    play (see ProgressFn: stderr is None in a windowed exe)."""
    if quiet or progress is not None:
        return
    print(message, file=sys.stderr)


# ---------------------------------------------------------------------------
# model weights
# ---------------------------------------------------------------------------

def model_paths(cache_dir: Path, tier: ModelTier) -> tuple[Path, Path]:
    """(weights_path, mmproj_path) for `tier` under `cache_dir` — deterministic,
    so `local_vlm.py` can check for existence without re-deriving the tier's URLs."""
    models_dir = Path(cache_dir) / "models" / tier.key
    return models_dir / tier.weights.filename, models_dir / tier.mmproj.filename


def _ensure_file(f: ModelFile, dest: Path, *, quiet: bool,
                 progress: "ProgressFn | None" = None) -> Path:
    if dest.is_file() and dest.stat().st_size == f.size_bytes and _sha256_file(dest) == f.sha256:
        return dest
    _say(f"fetching {f.filename} ({f.size_bytes/1e9:.1f} GB) from {f.url}",
         quiet=quiet, progress=progress)
    return download_verified(
        f.url, dest, sha256=f.sha256, size_bytes=f.size_bytes,
        progress=_progress_for(f.filename, progress, quiet),
    )


def ensure_model(cache_dir: Path, tier_key: str, *, quiet: bool = False,
                 progress: "ProgressFn | None" = None) -> tuple[Path, Path]:
    """Download (if absent or hash-mismatched) tier's weights + mmproj GGUFs.

    Returns (weights_path, mmproj_path), both hash-verified. Never re-downloads
    a file that is already present and correct.

    `progress` (2026-08-18) is the host-application seam -- see ProgressFn.
    Passing one silences stderr completely, whatever `quiet` says.
    """
    t = local_models.tier(tier_key)
    weights_dest, mmproj_dest = model_paths(cache_dir, t)
    _ensure_file(t.weights, weights_dest, quiet=quiet, progress=progress)
    _say("", quiet=quiet, progress=progress)
    _ensure_file(t.mmproj, mmproj_dest, quiet=quiet, progress=progress)
    _say("", quiet=quiet, progress=progress)
    return weights_dest, mmproj_dest


# ---------------------------------------------------------------------------
# llama.cpp runtime
# ---------------------------------------------------------------------------

def runtime_dir(cache_dir: Path, build: RuntimeBuild) -> Path:
    return Path(cache_dir) / "runtime" / f"llamacpp-{local_models.LLAMA_CPP_TAG}-{build.platform}"


def server_path(cache_dir: Path, build: RuntimeBuild | None = None) -> Path:
    build = build or local_models.runtime_for_platform(platform_key())
    return runtime_dir(cache_dir, build) / build.server_binary


def _extract_archive(archive_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(dest_dir)
    else:  # .tar.gz / .tgz
        with tarfile.open(archive_path) as tf:
            tf.extractall(dest_dir)  # noqa: S202 - our own pinned, hash-verified archive


def ensure_runtime(cache_dir: Path, *, quiet: bool = False,
                    build: RuntimeBuild | None = None,
                    progress: "ProgressFn | None" = None) -> Path:
    """Download + extract the pinned llama.cpp build for this platform.

    Returns the path to `llama-server`(.exe). Idempotent: does nothing once the
    binary is already on disk (extraction is not re-verified byte-for-byte
    every run — the archive's own sha256 gate is what protects it on the way
    in; re-hashing every DLL on every run would cost real time for no benefit).

    `progress` (2026-08-18) is the host-application seam -- see ProgressFn.
    Passing one silences stderr completely, whatever `quiet` says.
    """
    build = build or local_models.runtime_for_platform(platform_key())
    out_dir = runtime_dir(cache_dir, build)
    exe = out_dir / build.server_binary
    if exe.is_file():
        return exe

    downloads_dir = Path(cache_dir) / "downloads"
    for asset in (build.archive, *build.extra_archives):
        _say(f"fetching {asset.name} ({asset.size_bytes/1e6:.0f} MB) from {asset.url}",
             quiet=quiet, progress=progress)
        archive_path = download_verified(
            asset.url, downloads_dir / asset.name, sha256=asset.sha256,
            size_bytes=asset.size_bytes,
            progress=_progress_for(asset.name, progress, quiet),
        )
        _say("", quiet=quiet, progress=progress)
        _extract_archive(archive_path, out_dir)

    if not exe.is_file():
        raise LocalRuntimeError(
            f"extracted {build.label} but {build.server_binary} is not where expected "
            f"({exe}) — the release asset's internal layout may have changed"
        )
    if platform.system() != "Windows":
        exe.chmod(exe.stat().st_mode | 0o111)
    return exe


def llama_server_version(exe: Path, runner=subprocess.run) -> str | None:
    """Best-effort `llama-server --version` (or `--help`'s first banner line,
    since not every build prints a clean version to `--version`) — for
    `broll-index doctor`. Never raises: an unreadable binary just reports
    unknown rather than failing the whole doctor command."""
    for args in (["--version"], ["--help"]):
        try:
            out = runner([str(exe), *args], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        text = (out.stdout or out.stderr or "").strip()
        if text:
            return text.splitlines()[0][:200]
    return None


# ---------------------------------------------------------------------------
# GPU probe / tier recommendation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GpuInfo:
    present: bool
    vram_gb: float | None
    name: str = ""
    is_apple_silicon: bool = False
    detail: str = ""


def _nvidia_smi(runner=subprocess.run) -> GpuInfo | None:
    try:
        out = runner(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    line = out.stdout.strip().splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 2:
        return None
    name = parts[0]
    try:
        vram_mb = float(parts[1])
    except ValueError:
        return None
    return GpuInfo(present=True, vram_gb=round(vram_mb / 1024, 1), name=name,
                  detail="nvidia-smi")


def _apple_unified_memory(runner=subprocess.run) -> GpuInfo | None:
    try:
        out = runner(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    try:
        total_bytes = int(out.stdout.strip())
    except ValueError:
        return None
    gb = round(total_bytes / (1024 ** 3), 1)
    return GpuInfo(present=True, vram_gb=gb, name="Apple Silicon (unified memory)",
                  is_apple_silicon=True, detail="sysctl hw.memsize")


def probe_gpu(runner=subprocess.run) -> GpuInfo:
    """Best-effort GPU/unified-memory probe. Never raises — an unreadable or
    absent GPU is reported as `present=False`, which `recommend_tier` reads as
    "search-only, no local indexing tier fits"."""
    system = platform.system()
    if system == "Darwin" and platform.machine() in ("arm64", "aarch64"):
        info = _apple_unified_memory(runner)
        if info is not None:
            return info
        return GpuInfo(present=False, vram_gb=None, detail="sysctl probe failed")
    info = _nvidia_smi(runner)
    if info is not None:
        return info
    return GpuInfo(present=False, vram_gb=None, detail="nvidia-smi not found or no GPU")


def recommend_tier(gpu: GpuInfo | None = None) -> str | None:
    """Best tier this machine's hardware can run, or None (search-only).

    Apple Silicon compares unified memory against `apple_unified_gb`, a
    discrete GPU against `vram_gb` — see local_models.ModelTier's fields for
    why they differ (the eval's §3.2 hardware table).
    """
    gpu = gpu if gpu is not None else probe_gpu()
    if not gpu.present or not gpu.vram_gb:
        return None
    best = local_models.TIERS["best"]
    good = local_models.TIERS["good"]
    floor = (lambda t: t.apple_unified_gb) if gpu.is_apple_silicon else (lambda t: t.vram_gb)
    if gpu.vram_gb >= floor(best):
        return "best"
    if gpu.vram_gb >= floor(good):
        return "good"
    return None


def refuse_if_tier_unfit(tier_key: str, gpu: GpuInfo | None = None, *, force: bool = False) -> None:
    """Raise LocalRuntimeError with an actionable message when `tier_key` does
    not fit this machine's GPU, unless `force`. Mirrors the eval doc's example
    message verbatim: "Best needs 12 GB VRAM; this machine reports 10 GB —
    choose Good or add --force"."""
    if force:
        return
    t = local_models.tier(tier_key)
    gpu = gpu if gpu is not None else probe_gpu()
    if not gpu.present:
        raise LocalRuntimeError(
            f"no GPU detected ({gpu.detail}) — the local backend needs an NVIDIA GPU "
            f"(or Apple Silicon); use backend: anthropic, or add --force to try anyway"
        )
    floor = t.apple_unified_gb if gpu.is_apple_silicon else t.vram_gb
    have = gpu.vram_gb or 0
    if have < floor:
        kind = "unified memory" if gpu.is_apple_silicon else "VRAM"
        other = "good" if tier_key == "best" else None
        suggestion = f"choose {local_models.TIERS[other].label} or add --force" if other else "add --force"
        raise LocalRuntimeError(
            f"{t.label} needs {floor} GB {kind}; this machine reports {have:.0f} GB "
            f"— {suggestion}"
        )
