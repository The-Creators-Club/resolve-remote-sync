"""The companion's front door to the vendored local-VLM backend: where the
model cache lives, whether this machine can run a tier at all, fetching the
runtime and weights with progress, and the llama-server's lifecycle.

Everything that TALKS to Qwen3-VL is `broll_vlm/` -- vendored verbatim from the
indexer, not to be edited here (see that package's __init__). This module is
the part that is the COMPANION's: the tools dir the rest of the app already
uses, the free-space floor the upgrade path already agreed on, the
window-suppressed subprocess spawn every other companion probe uses, a
zero-I/O `status()` the tray and the reporter can call on every tick, and the
refusals in the words an editor reads.

Three rules this module exists to enforce (docs/BROLL_INGEST_PLAN.md §3.3, §6):

  * **Never CPU inference.** llama.cpp will happily run a 4B model on a CPU at
    a fraction of a token per second; a batch of 200 clips would then take
    weeks while looking like it was working. No GPU -> `server()` refuses and
    `fits()` says why, in the page and in the tray.
  * **Never a surprise 3.9 GB download.** `ensure()` checks free space FIRST
    (the archive, the extracted tree, both GGUFs, plus upgrade's own margin),
    then that every URL the vendored catalogue builds is on the allow-list
    below, and only then fetches. A sha256 mismatch deletes the file -- the
    fetcher's own rule, restated here because the deletion is the difference
    between "retry fixes it" and "every retry fails identically".
  * **Never write to stderr.** The tray is a windowed PyInstaller build where
    `sys.stderr` is None. `ensure()` always passes a progress callback, which
    is what silences the indexer's own prints (local_runtime.ProgressFn).

Nothing here is imported at tray start: the vendored modules are imported
lazily inside the functions that need them, so a machine that never indexes
anything never pays for them.
"""

from __future__ import annotations

import fnmatch
import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from . import config as config_mod
from . import upgrade as upgrade_mod
from . import ytdlp_manager
# CREATE_NO_WINDOW, borrowed rather than copied a fifth time: the GPU probe is
# the same kind of spawn as ffmpeg_tools' own (short, unattended, one per
# tick's worth of work), and this module already depends on nothing that
# ffmpeg_tools does not.
from .ffmpeg_tools import _win_creationflags

log = logging.getLogger("ccsync.brollvlm")

# Where the runtime and weights land: a sibling of the yt-dlp/ffmpeg tools dir,
# NOT the indexer's `%LOCALAPPDATA%\\ccsync\\indexer`. Same reasoning
# sidecar_tools gives for using ytdlp_manager.tools_dir() -- one platform-paths
# scheme in the companion, and exactly one place an operator has to look (or
# delete) when a machine is being reclaimed. A base rig that ALSO runs the
# indexer therefore keeps two copies of the weights; that is 3-6 GB on one
# machine, against a companion that would otherwise have to learn the
# indexer's per-OS cache scheme and stay in step with it.
CACHE_DIR_NAME = "broll-vlm"

# Hosts the fetch is allowed to reach, checked against every URL
# `broll_vlm/local_models.py` builds before a single byte is requested.
# github.com serves the llama.cpp release (it 302s to objects.githubusercontent
# .com, which urlopen follows); huggingface.co serves the GGUFs and 302s to a
# cdn-lfs* host. A pin that is edited to point somewhere else -- or a future
# release asset that moves -- is a refusal here, not a download.
ALLOWED_HOSTS = (
    "github.com",
    "objects.githubusercontent.com",
    "huggingface.co",
    "cdn-lfs.huggingface.co",
    "cdn-lfs-us-1.huggingface.co",
    "cdn-lfs-eu-1.huggingface.co",
)
# Wildcards for the CDN hosts Hugging Face rotates through
# (cdn-lfs-us-1, cdn-lfs-eu-1, ...). Matched with fnmatch, never with a bare
# `endswith`: "evil-huggingface.co" ends with the suffix too.
ALLOWED_HOST_PATTERNS = ("cdn-lfs*.huggingface.co",)

# How long a GPU probe is trusted. nvidia-smi is a ~200 ms spawn and the
# answer changes only when hardware or a driver does, but the tray asks on
# every menu build and the capability endpoint on every page load.
GPU_PROBE_TTL_SECONDS = 600.0

# How long the on-disk readiness answer is trusted. status() itself does NO
# I/O -- it returns this cache -- and refresh() is what stats the files.
STATUS_TTL_SECONDS = 60.0

SERVER_LOG_NAME = "broll_vlm_server.log"


class SidecarError(RuntimeError):
    """The local model cannot be run on this machine right now. Carries the
    editor-facing sentence; `ensure()` returns it rather than raising, but
    `server()` raises because its caller (the ingest orchestrator) has a
    per-clip failure path already."""


_lock = threading.RLock()
_gpu_cache: Optional[tuple[float, dict[str, Any]]] = None
_status_cache: dict[str, Any] = {
    "runtime_ready": False,
    "model_ready": {"good": False, "best": False},
    "gpu": {"present": False, "vram_gb": None, "detail": "not probed yet",
            "apple_silicon": False, "name": ""},
    "downloading": None,
    "last_error": "",
    "at": 0.0,
}


# ---------------------------------------------------------------------------
# where it lives
# ---------------------------------------------------------------------------

def cache_dir() -> Path:
    """`<tools dir>/broll-vlm`. Existence is not checked."""
    return ytdlp_manager.tools_dir() / CACHE_DIR_NAME


def server_log_path(cfg: Optional[dict[str, Any]] = None) -> Path:
    """`~/.ccsync/state/broll_vlm_server.log` -- llama-server's own stdout and
    stderr. Derived exactly like the other state files (app.py's
    `resolved_log_path(cfg).parent / "state"`), because when the model dies
    mid-batch this path is what the tray line and the failure message name."""
    return config_mod.resolved_log_path(cfg or {}).parent / "state" / SERVER_LOG_NAME


def _models():
    from .broll_vlm import local_models
    return local_models


def _runtime():
    from .broll_vlm import local_runtime
    return local_runtime


# ---------------------------------------------------------------------------
# GPU
# ---------------------------------------------------------------------------

def _runner(args, **kwargs):
    """subprocess.run with the companion's flags. The vendored probe takes a
    `runner` for exactly this: the indexer runs in a console, we do not, and an
    unflagged nvidia-smi spawn flashes a black window on the editor's desktop
    every ten minutes."""
    return subprocess.run(args, creationflags=_win_creationflags(), **kwargs)


def gpu(force: bool = False) -> dict[str, Any]:
    """This machine's GPU as a plain dict, cached for GPU_PROBE_TTL_SECONDS.

    Never raises: an absent nvidia-smi, a driver mid-upgrade or a Mac that is
    not Apple Silicon all come back `present=False`, which every caller reads
    as "no local indexing here".
    """
    global _gpu_cache
    with _lock:
        cached = _gpu_cache
    if not force and cached is not None and (time.monotonic() - cached[0]) < GPU_PROBE_TTL_SECONDS:
        return dict(cached[1])

    try:
        info = _runtime().probe_gpu(runner=_runner)
        out = {
            "present": bool(info.present),
            "vram_gb": info.vram_gb,
            "detail": info.detail,
            "apple_silicon": bool(info.is_apple_silicon),
            "name": info.name,
        }
    except Exception as exc:  # noqa: BLE001 - a probe must never be fatal
        log.debug("broll vlm: GPU probe failed (%s)", exc, exc_info=True)
        out = {"present": False, "vram_gb": None, "detail": f"probe failed: {exc}",
               "apple_silicon": False, "name": ""}
    with _lock:
        _gpu_cache = (time.monotonic(), out)
        _status_cache["gpu"] = dict(out)
    return dict(out)


def reset_caches() -> None:
    """Forget the GPU probe and the readiness snapshot (tests; a config change;
    an operator who just installed a driver)."""
    global _gpu_cache
    with _lock:
        _gpu_cache = None
        _status_cache["at"] = 0.0


def _gb(value: float) -> str:
    """A VRAM figure as an editor should read it: "8", not "8.0"; "7.8" when
    the extra digit is the whole point of the sentence."""
    if abs(value - round(value)) < 0.05:
        return f"{round(value):d}"
    return f"{value:.1f}"


def fits(tier_key: str, gpu_info: Optional[dict[str, Any]] = None) -> tuple[bool, str]:
    """Can this machine run `tier_key`? -> (fits, refusal message).

    The message shape is fixed by docs/BROLL_INGEST_PLAN.md's owner review
    (2026-08-18) and is used VERBATIM in three places -- the tray balloon, the
    tray menu line and the page:

        Can't index b-roll: Best needs 12 GB VRAM, this GPU has 8 GB — choose Good

    Apple Silicon says "unified memory" and "this Mac has", because its floor
    is the shared-memory one (16/24 GB) and quoting a Mac a VRAM number it
    does not have would send the editor looking for a graphics card.

    Returns ("", i.e. no message) when it fits: a caller that prints the second
    element unconditionally shows nothing rather than a stale refusal.
    """
    models = _models()
    try:
        tier = models.tier(tier_key)
    except ValueError as exc:
        return False, f"Can't index b-roll: {exc}"

    info = gpu_info if gpu_info is not None else gpu()
    if not info.get("present"):
        return False, (
            "Can't index b-roll: no usable GPU on this machine "
            f"({info.get('detail') or 'no GPU detected'}). Indexing needs an "
            "NVIDIA GPU or Apple Silicon")

    apple = bool(info.get("apple_silicon"))
    floor = tier.apple_unified_gb if apple else tier.vram_gb
    have = float(info.get("vram_gb") or 0)
    if have >= floor:
        return True, ""

    kind = "unified memory" if apple else "VRAM"
    whose = "this Mac has" if apple else "this GPU has"
    # Only "best" has something smaller to fall back to. For "good" there is
    # no smaller tier, and saying "choose Good" when Good is what was chosen
    # is how a support call starts.
    smaller = models.TIERS["good"] if tier_key == "best" else None
    tail = (f"choose {smaller.label}" if smaller is not None
            else "indexing needs a bigger GPU: this batch can run on another machine")
    return False, (f"Can't index b-roll: {tier.label} needs {floor} GB {kind}, "
                   f"{whose} {_gb(have)} GB - {tail}")


def recommended_tier(gpu_info: Optional[dict[str, Any]] = None) -> Optional[str]:
    """The best tier this machine can run, or None. The vendored
    `recommend_tier`, given the probe we already have."""
    info = gpu_info if gpu_info is not None else gpu()
    runtime = _runtime()
    probe = runtime.GpuInfo(
        present=bool(info.get("present")), vram_gb=info.get("vram_gb"),
        name=info.get("name") or "", is_apple_silicon=bool(info.get("apple_silicon")),
        detail=info.get("detail") or "",
    )
    try:
        return runtime.recommend_tier(probe)
    except Exception:  # noqa: BLE001
        log.debug("broll vlm: recommend_tier failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# what is on disk
# ---------------------------------------------------------------------------

def runtime_exe() -> Optional[Path]:
    """The extracted llama-server for this platform, or None if it is not
    there (or this platform has no pinned build at all)."""
    runtime = _runtime()
    try:
        build = _models().runtime_for_platform(runtime.platform_key())
        exe = runtime.server_path(cache_dir(), build)
    except Exception:  # noqa: BLE001 - unsupported platform is "not ready"
        return None
    try:
        return exe if exe.is_file() else None
    except OSError:
        return None


def model_files(tier_key: str) -> tuple[Path, Path]:
    """(weights, mmproj) paths for a tier under our cache dir. No I/O."""
    return _runtime().model_paths(cache_dir(), _models().tier(tier_key))


def model_ready(tier_key: str) -> bool:
    """Both GGUFs present at their pinned SIZE. Deliberately not a re-hash: a
    2.5 GB sha256 on every tick would cost seconds of disk per minute, and the
    hash gate that matters already ran on the way in (download_verified
    refuses, and deletes, a file whose digest is wrong). A truncated file is
    caught by the size check; a corrupted-in-place one is caught by
    ensure()'s own re-verification before the next download."""
    try:
        tier = _models().tier(tier_key)
        weights, mmproj = model_files(tier_key)
        return (weights.is_file() and weights.stat().st_size == tier.weights.size_bytes
                and mmproj.is_file() and mmproj.stat().st_size == tier.mmproj.size_bytes)
    except Exception:  # noqa: BLE001
        return False


def refresh(force: bool = False) -> dict[str, Any]:
    """Re-stat the cache and re-probe the GPU if their caches are stale, and
    return the fresh snapshot. THIS is the function that touches the disk; the
    tick calls it, `status()` never does."""
    with _lock:
        fresh = (time.monotonic() - float(_status_cache.get("at") or 0)) < STATUS_TTL_SECONDS
    if fresh and not force:
        return status()

    info = gpu(force=force)
    ready = {key: model_ready(key) for key in _models().VALID_TIERS}
    runtime_ok = runtime_exe() is not None
    with _lock:
        _status_cache["runtime_ready"] = runtime_ok
        _status_cache["model_ready"] = ready
        _status_cache["gpu"] = dict(info)
        _status_cache["at"] = time.monotonic()
    return status()


def status() -> dict[str, Any]:
    """The cached snapshot -- ZERO I/O, safe to call from the tray's menu
    build, the reporter's tick and the loopback's capability route.

    {runtime_ready, model_ready: {good, best}, gpu: {...}, downloading:
    {name, written, total, percent} | None, last_error}
    """
    with _lock:
        snap = {
            "runtime_ready": bool(_status_cache["runtime_ready"]),
            "model_ready": dict(_status_cache["model_ready"]),
            "gpu": dict(_status_cache["gpu"]),
            "downloading": (dict(_status_cache["downloading"])
                            if _status_cache["downloading"] else None),
            "last_error": _status_cache["last_error"],
        }
    return snap


def _download_rate_and_eta(written: int, total: Optional[int]
                           ) -> tuple[Optional[float], Optional[float]]:
    """The fetcher's own aggregate rate, and the seconds left at it.

    The rate is measured across every connection of a parallel download
    (2026-08-18, BROLL-ING-4) and published by the vendored module as a plain
    attribute, because the progress callback's signature is fixed by the
    indexer's own use of it. Never raises: a missing attribute (an older
    vendored copy) just means the window says a percentage and no speed.
    """
    try:
        rate = float(_runtime().download_verified.last_rate_bytes_per_s or 0.0)
    except Exception:  # noqa: BLE001 - a speed reading may not fail a download
        return None, None
    if rate <= 0:
        return None, None
    eta = None
    if total and total > written:
        eta = (total - written) / rate
    return rate, eta


def _note_download(name: str, written: int, total: Optional[int]) -> None:
    percent = None
    if total:
        percent = max(0, min(100, int(written * 100 / total)))
    rate, eta = _download_rate_and_eta(written, total)
    with _lock:
        _status_cache["downloading"] = {"name": name, "written": written,
                                        "total": total, "percent": percent,
                                        "rate_bytes_per_s": rate,
                                        "eta_seconds": eta}


def _clear_download(error: str = "") -> None:
    with _lock:
        _status_cache["downloading"] = None
        _status_cache["last_error"] = error


# ---------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------

class _Stopped(Exception):
    """The editor came back (or cancelled) mid-download. Raised out of the
    progress callback, which is the only code of ours that runs during a
    multi-GB transfer; the `.part` file stays on disk and the next attempt
    resumes it with an HTTP Range request."""


def host_allowed(url: str) -> bool:
    """Is `url`'s host on the allow-list? Exact match or an explicit wildcard;
    never a suffix test."""
    host = (urlsplit(url).hostname or "").lower()
    if host in ALLOWED_HOSTS:
        return True
    return any(fnmatch.fnmatch(host, pattern) for pattern in ALLOWED_HOST_PATTERNS)


def planned_urls(tier_key: str) -> list[str]:
    """Every URL the vendored fetcher would open for this tier: the llama.cpp
    release archive (plus Windows' separate CUDA-runtime zip) and the two
    GGUFs. Built from the same catalogue objects `ensure_runtime`/`ensure_model`
    read, so a pin that moves cannot be validated here and fetched from
    somewhere else."""
    models = _models()
    tier = models.tier(tier_key)
    urls = [tier.weights.url, tier.mmproj.url]
    try:
        build = models.runtime_for_platform(_runtime().platform_key())
    except Exception:  # noqa: BLE001 - platform with no pinned build
        return urls
    return [asset.url for asset in (build.archive, *build.extra_archives)] + urls


def required_bytes(tier_key: str) -> int:
    """How much free space `ensure()` insists on before it starts.

    The archives are counted TWICE: the downloaded zip stays in `downloads/`
    while its contents are extracted beside it (the fetcher does not delete
    it -- that is what makes a re-run cheap), so at the peak both exist. The
    GGUFs are counted once. `upgrade.MIN_FREE_BYTES_MARGIN` on top, imported
    rather than re-typed for the reason ytdlp_manager gives: two numbers that
    both mean "don't be the thing that fills an editor's disk" would drift.
    """
    models = _models()
    tier = models.tier(tier_key)
    total = tier.weights.size_bytes + tier.mmproj.size_bytes
    try:
        build = models.runtime_for_platform(_runtime().platform_key())
        total += sum(asset.size_bytes * 2 for asset in (build.archive, *build.extra_archives))
    except Exception:  # noqa: BLE001
        pass
    return total + upgrade_mod.MIN_FREE_BYTES_MARGIN


def free_space_refusal(tier_key: str, directory: Optional[Path] = None) -> Optional[str]:
    """Why there is not enough room for `tier_key`, or None. Editor-facing.

    A disk we cannot measure is NOT a refusal -- same rule as
    sidecar_tools._free_space_ok and upgrade's own check: "I could not tell"
    must never read as "no".
    """
    directory = directory or cache_dir()
    needed = required_bytes(tier_key)
    probe = directory
    # The cache dir may not exist yet; measure the nearest parent that does.
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        free = shutil.disk_usage(str(probe)).free
    except Exception:  # noqa: BLE001
        log.debug("broll vlm: free-space check failed at %s; continuing", probe, exc_info=True)
        return None
    if free >= needed:
        return None
    return (f"Not enough disk space for the {_models().tier(tier_key).label} model: "
            f"needs about {needed / 1_000_000_000:.1f} GB free at {directory}, "
            f"has {free / 1_000_000_000:.1f} GB - free some space and try again")


def ensure(
    tier_key: str,
    progress_cb: Optional[Callable[[str, int, Optional[int]], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> tuple[bool, str]:
    """Make the runtime and `tier_key`'s weights present and verified.

    -> (ok, message). NEVER raises: this runs on the ingest tick, and an
    exception here would take the orchestrator's thread down with the batch
    still queued.

    Order, and why (plan §6):
      1. the tier has to FIT this GPU -- there is no point spending 3.9 GB of
         an editor's bandwidth on a model that will never be allowed to run
         (`server()` refuses CPU inference);
      2. free space, BEFORE a byte is requested, counting the extraction peak;
      3. every URL the catalogue builds is on the allow-list;
      4. fetch, with `progress_cb` -- which also silences the vendored
         fetcher's stderr prints (None in a windowed exe).

    A sha256 mismatch deletes the file and says so: the fetcher already
    discards its `.part`, and this additionally removes a previously-good
    destination file that has since rotted, so the retry is a fresh download
    rather than the same failure forever.
    """
    ok_fit, why = fits(tier_key)
    if not ok_fit:
        _clear_download(why)
        return False, why

    refusal = free_space_refusal(tier_key)
    if refusal:
        _clear_download(refusal)
        return False, refusal

    try:
        urls = planned_urls(tier_key)
    except ValueError as exc:
        _clear_download(str(exc))
        return False, f"Can't index b-roll: {exc}"
    bad = [u for u in urls if not host_allowed(u)]
    if bad:
        message = (f"refusing to download the b-roll model: {urlsplit(bad[0]).hostname} "
                   "is not one of the hosts this build is allowed to fetch from")
        log.warning("broll vlm: %s (urls: %s)", message, bad)
        _clear_download(message)
        return False, message

    def _progress(name: str, written: int, total: Optional[int]) -> None:
        if stop_event is not None and stop_event.is_set():
            raise _Stopped()
        _note_download(name, written, total)
        if progress_cb is not None:
            progress_cb(name, written, total)

    runtime = _runtime()
    directory = cache_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if stop_event is not None and stop_event.is_set():
            raise _Stopped()
        runtime.ensure_runtime(directory, quiet=True, progress=_progress)
        if stop_event is not None and stop_event.is_set():
            raise _Stopped()
        runtime.ensure_model(directory, tier_key, quiet=True, progress=_progress)
    except _Stopped:
        _clear_download("")
        log.info("broll vlm: model download stopped; the partial file is kept for resume")
        return False, "the download was stopped - it will resume where it left off"
    except runtime.LocalRuntimeError as exc:
        message = str(exc)
        if "sha256 mismatch" in message.lower():
            _delete_tier_files(tier_key)
            message = ("the model download's checksum did not match. The file was "
                       "deleted and will be fetched again")
        log.warning("broll vlm: %s", message)
        _clear_download(message)
        return False, message
    except Exception as exc:  # noqa: BLE001 - see the docstring
        log.warning("broll vlm: model/runtime fetch failed (%s)", exc, exc_info=True)
        _clear_download(f"the b-roll model could not be downloaded: {exc}")
        return False, f"the b-roll model could not be downloaded: {exc}"

    _clear_download("")
    refresh(force=True)
    return True, f"{_models().tier(tier_key).label} is ready"


def _delete_tier_files(tier_key: str) -> None:
    """Remove a tier's GGUFs after a failed verification. Never raises."""
    try:
        for path in model_files(tier_key):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("broll vlm: could not delete %s (%s)", path, exc)
    except Exception:  # noqa: BLE001
        log.debug("broll vlm: could not resolve the tier's files to delete", exc_info=True)


# ---------------------------------------------------------------------------
# the model server
# ---------------------------------------------------------------------------

def server(tier_key: str, cfg: Optional[dict[str, Any]] = None, *, gpu_layers: int = 99):
    """A healthy llama-server for `tier_key`, started if necessary.

    Raises SidecarError when this machine must not run it -- no GPU, a tier
    that does not fit, or a runtime/weights that are not on disk yet. The
    no-GPU refusal is the load-bearing one: llama.cpp would otherwise run the
    model on the CPU at a small fraction of a token per second, so a batch
    would appear to be working and finish some time next month.

    The vendored `get_server` keeps one server per (binary, weights, mmproj)
    warm for the life of the process and stops it at exit; `stop_server()`
    below is how the orchestrator frees the VRAM the moment the editor comes
    back.
    """
    from .broll_vlm import local_vlm

    ok, why = fits(tier_key)
    if not ok:
        raise SidecarError(why)

    exe = runtime_exe()
    if exe is None:
        raise SidecarError("the b-roll indexing runtime is not installed on this machine yet")
    if not model_ready(tier_key):
        raise SidecarError(
            f"the {_models().tier(tier_key).label} model is not downloaded on this machine yet")

    weights, mmproj = model_files(tier_key)
    log_path = server_log_path(cfg)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # A log we cannot write is not a reason to refuse to index; the server
        # is started without one and the failure path says so.
        log.warning("broll vlm: cannot create %s (%s) -- starting without a server log",
                    log_path.parent, exc)
        log_path = None

    return local_vlm.get_server(exe=exe, model_path=weights, mmproj_path=mmproj,
                                gpu_layers=gpu_layers, log_path=log_path)


def stop_server() -> None:
    """Stop every llama-server this process started and free its VRAM. Never
    raises -- it is called from the gate the moment the editor's mouse moves,
    and from shutdown."""
    try:
        from .broll_vlm import local_vlm
        local_vlm.stop_all_servers()
    except Exception:  # noqa: BLE001
        log.debug("broll vlm: stop_all_servers failed", exc_info=True)
