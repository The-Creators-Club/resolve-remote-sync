# VENDORED VERBATIM from broll/indexer/broll_index/local_models.py -- DO NOT EDIT HERE.
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
"""The local-VLM tier catalogue: which GGUFs, which llama.cpp build, which
hardware each needs — one place, so `local_runtime.py`'s fetcher, `cli.py`'s
`doctor`/`models pull`, and the dashboard's "Good/Best" picker all read the
same facts instead of three copies drifting apart (the dashboard agent copies
the label/description/vram_note strings verbatim — see CLAUDE.md and
`broll/docs/local-indexing-options-2026-08-17.md` §3).

Chosen and measured in that doc's eval (`broll/eval/local_vlm/`,
`results/report.md`, scored 2026-08-18): Qwen3-VL, Apache-2.0, via llama.cpp
GGUF quants. Q4_K_M only — the eval's own §3.1 found no quality gain from
Q8_0 worth the extra ~4 GB, and Q4_K_M is what was actually measured (6.1 GB
peak VRAM at 16k context on the 3080). Every file below is pinned by exact
sha256 read off the Hugging Face API's `lfs.oid` (which IS the sha256, not a
separate digest) and, for the 4B, cross-checked against the copies already on
this machine (`%LOCALAPPDATA%\\ccsync\\hf-cache\\hub\\...`, left by the
2026-08-17 prototype). The 8B was NOT downloaded here (COMMERCIAL_READINESS
says do not spend 6 GB proving a hash the API already gives byte-for-byte);
its sha256 is the HF API's own `lfs.oid` for
`Qwen/Qwen3-VL-8B-Instruct-GGUF@f982a07559d4a2f6c8744d840bf6fccab30eea96`,
fetched 2026-08-18 and not independently re-verified by download.

llama.cpp release **b10470** (pinned — matches the eval, so a customer's
numbers are the eval's numbers, not some other build's). Asset names and
sha256 are GitHub's own release digests
(`api.github.com/repos/ggml-org/llama.cpp/releases/tags/b10470`), fetched
2026-08-18. There is no CUDA build of b10470 for Linux x64 (the release has
win-cuda-12.4/13.3, but only `ubuntu-vulkan-x64` / `ubuntu-x64` (CPU) /
`ubuntu-sycl-*` for Linux) — Vulkan is pinned as the Linux GPU runtime
instead; it runs on NVIDIA (and AMD/Intel) GPUs through the Vulkan backend,
just not benchmarked here. `ensure_runtime` refuses a platform this table has
no entry for rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# model tiers
# ---------------------------------------------------------------------------

VALID_TIERS = ("good", "best")
DEFAULT_TIER = "good"


@dataclass(frozen=True)
class ModelFile:
    repo: str
    revision: str
    filename: str
    sha256: str
    size_bytes: int

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.filename}"


@dataclass(frozen=True)
class ModelTier:
    key: str
    label: str
    description: str
    vram_note: str
    # VRAM/unified-memory floor, GB — what recommend_tier() and doctor compare
    # a probed GPU against. Apple Silicon shares memory with the OS, so its
    # floor is higher than the discrete-GPU floor for the same tier.
    vram_gb: int
    apple_unified_gb: int
    weights: ModelFile
    mmproj: ModelFile
    model_label: str  # recorded in videos.model as f"local:{model_label}"


# Label/description/vram_note text is BY DESIGN the exact strings CLAUDE.md's
# task quoted — the dashboard agent copies them verbatim, so a wording change
# here is a wording change there too. Do not soften or lengthen them without
# updating both places, and say so in the commit.
TIERS: dict[str, ModelTier] = {
    "good": ModelTier(
        key="good",
        label="Good",
        description="Qwen3-VL 4B",
        vram_note=(
            "Qwen3-VL 4B — needs an NVIDIA GPU with 8 GB VRAM (or Apple "
            "Silicon with 16 GB); ~20 s per clip on an RTX 3080"
        ),
        vram_gb=8,
        apple_unified_gb=16,
        weights=ModelFile(
            repo="Qwen/Qwen3-VL-4B-Instruct-GGUF",
            revision="1cd86afb9a95c410a6038ab3b40d8b578c892266",
            filename="Qwen3VL-4B-Instruct-Q4_K_M.gguf",
            sha256="66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a",
            size_bytes=2_497_281_664,
        ),
        mmproj=ModelFile(
            repo="Qwen/Qwen3-VL-4B-Instruct-GGUF",
            revision="1cd86afb9a95c410a6038ab3b40d8b578c892266",
            filename="mmproj-Qwen3VL-4B-Instruct-F16.gguf",
            sha256="256f3a43bd4205ffef48d6b92715e1e70b5b0e9aef06522584967513a9985331",
            size_bytes=836_180_256,
        ),
        model_label="qwen3-vl-4b-q4_k_m",
    ),
    "best": ModelTier(
        key="best",
        label="Best",
        description="Qwen3-VL 8B",
        vram_note=(
            "Qwen3-VL 8B — needs 12 GB VRAM (or Apple Silicon with 24 GB); "
            "a little sharper on on-screen text and vocabulary, ~2× slower"
        ),
        vram_gb=12,
        apple_unified_gb=24,
        weights=ModelFile(
            repo="Qwen/Qwen3-VL-8B-Instruct-GGUF",
            revision="f982a07559d4a2f6c8744d840bf6fccab30eea96",
            filename="Qwen3VL-8B-Instruct-Q4_K_M.gguf",
            sha256="67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2",
            size_bytes=5_027_784_800,
        ),
        mmproj=ModelFile(
            repo="Qwen/Qwen3-VL-8B-Instruct-GGUF",
            revision="f982a07559d4a2f6c8744d840bf6fccab30eea96",
            filename="mmproj-Qwen3VL-8B-Instruct-F16.gguf",
            sha256="ca524100ebf825c9a870db1c580d03879e0da0ab2541697e2458e64891cf9d38",
            size_bytes=1_159_029_824,
        ),
        model_label="qwen3-vl-8b-q4_k_m",
    ),
}


def tier(key: str) -> ModelTier:
    key = (key or DEFAULT_TIER).strip().lower()
    if key not in TIERS:
        raise ValueError(
            f"unknown model tier {key!r} — expected one of {', '.join(VALID_TIERS)}"
        )
    return TIERS[key]


# ---------------------------------------------------------------------------
# runtime (llama.cpp) — one pinned release, per-platform assets
# ---------------------------------------------------------------------------

LLAMA_CPP_TAG = "b10470"
_RELEASE_BASE = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_CPP_TAG}"


@dataclass(frozen=True)
class RuntimeAsset:
    name: str
    sha256: str
    size_bytes: int

    @property
    def url(self) -> str:
        return f"{_RELEASE_BASE}/{self.name}"


@dataclass(frozen=True)
class RuntimeBuild:
    platform: str          # "windows" | "macos" | "linux"
    label: str
    backend: str            # "cuda" | "vulkan" | "metal" (informational)
    server_binary: str       # relative path to llama-server inside the extracted tree
    archive: RuntimeAsset
    # A second archive (Windows CUDA ships the CUDA runtime DLLs separately)
    # that must also be extracted into the same directory. Empty for builds
    # that are self-contained.
    extra_archives: tuple[RuntimeAsset, ...] = field(default_factory=tuple)


RUNTIMES: dict[str, RuntimeBuild] = {
    "windows": RuntimeBuild(
        platform="windows",
        label=f"llama.cpp {LLAMA_CPP_TAG} (CUDA 12.4, Windows x64)",
        backend="cuda",
        server_binary="llama-server.exe",
        archive=RuntimeAsset(
            name="llama-b10470-bin-win-cuda-12.4-x64.zip",
            sha256="e6f3fa9790ab7684ded44ade774dc94742ddb99e4b0abaf1603dab4f3d0803d3",
            size_bytes=250_799_028,
        ),
        extra_archives=(
            RuntimeAsset(
                name="cudart-llama-bin-win-cuda-12.4-x64.zip",
                sha256="8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
                size_bytes=391_443_627,
            ),
        ),
    ),
    "macos": RuntimeBuild(
        platform="macos",
        label=f"llama.cpp {LLAMA_CPP_TAG} (Metal, macOS arm64)",
        backend="metal",
        server_binary="llama-server",
        archive=RuntimeAsset(
            name="llama-b10470-bin-macos-arm64.tar.gz",
            sha256="75c29cd80a67a8388b8ed08ea4a87531269a737c18945bdf3c3db6d5858024a9",
            size_bytes=11_079_764,
        ),
    ),
    # No CUDA build of this release exists for Linux x64 (checked against the
    # b10470 release asset list 2026-08-18: win-cuda-12.4/13.3 exist,
    # ubuntu-cuda does not). Vulkan runs on NVIDIA/AMD/Intel GPUs through
    # llama.cpp's Vulkan backend; it was not benchmarked in the eval, so
    # `doctor` should say so rather than imply parity with the Windows numbers.
    "linux": RuntimeBuild(
        platform="linux",
        label=f"llama.cpp {LLAMA_CPP_TAG} (Vulkan, Linux x64 — not benchmarked, no CUDA build in this release)",
        backend="vulkan",
        server_binary="llama-server",
        archive=RuntimeAsset(
            name="llama-b10470-bin-ubuntu-vulkan-x64.tar.gz",
            sha256="21f765c89d87c9a7822cde1af199face8b927b099d28a853c53fb01604fcff6b",
            size_bytes=33_272_659,
        ),
    ),
}


def runtime_for_platform(platform_key: str) -> RuntimeBuild:
    build = RUNTIMES.get(platform_key)
    if build is None:
        raise ValueError(
            f"no llama.cpp {LLAMA_CPP_TAG} build pinned for platform {platform_key!r} "
            f"— expected one of {', '.join(RUNTIMES)}"
        )
    return build
