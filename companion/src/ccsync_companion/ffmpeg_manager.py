"""The ffmpeg sidecar: a pinned static ffmpeg + ffprobe the companion installs
into the same `tools` dir yt-dlp lives in.

WHY IT EXISTS (2026-08-16). Requester-first YouTube downloads shipped in 0.7.8
and never engaged on a single editor machine: every rung the local executor
runs is a `bestvideo+bestaudio` merge, ffmpeg does the merge, and no editor
has ffmpeg -- nothing ever put one there. The proxy generator was written with
ffmpeg as an OPTIONAL dependency (`winget install Gyan.FFmpeg` if you want
proxies), which is fine for a base-rig feature and fatal for a fleet feature:
ruskin's `/ytdl/capabilities` answered `ok:false -- ffmpeg is not installed`
(COMP-BROLL-5 refusing the claim, correctly), so every job took the server
path, the NAS downloaded, and lane B carried the originals back down. The
whole point of the feature, undone by one absent binary.

WHY PINNED, NOT "LATEST" (unlike ytdlp_manager). yt-dlp has to track the
newest release because YouTube breaks it on purpose; ffmpeg has no such
adversary -- a 6.x merges an mp4 today exactly as it did last year. So the
release is pinned by tag and each asset by sha256, both hardcoded here: no
GitHub API call, no checksum file to fetch, and an artifact that does not
match the pin is not installed. Bumping the pin is a code change with a
review, which is what "the fleet now runs a different encoder" deserves.

WHY THIS SOURCE. eugeneware/ffmpeg-static republishes gyan.dev's Windows and
evermeet's macOS static builds as ONE FILE PER PLATFORM (`ffmpeg-win32-x64.gz`
etc.), which is the shape ytdlp_manager already downloads and verifies --
no zip walking, no `bin/` layout guessing, and it covers darwin-arm64, which
yt-dlp's own FFmpeg-Builds do not. Measured 2026-08-16: the win32-x64 asset
inflates to an 82.8 MB `ffmpeg version 6.1.1-essentials_build` that runs
(libx264/x265 + NVENC, so the proxy generator gets to use it too).

    Windows:  %LOCALAPPDATA%\\ccsync\\tools\\ffmpeg.exe (+ ffprobe.exe)
    macOS:    ~/Library/Application Support/ccsync/tools/ffmpeg (+ ffprobe)

ffprobe rides along because ffmpeg_tools.ffprobe_for() looks for it BESIDE
ffmpeg and the proxy generator's probe/verify passes need it; yt-dlp uses it
when present. Same dir, same pin, same verification.

Everything here is BEST-EFFORT and quiet, on ytdlp_manager's exact terms: a
missing or unverifiable download is a log line, capabilities() keeps
answering "no ffmpeg" and the server downloads instead. Nothing here may raise
into the tray or hold up startup. It runs on the yt-dlp manager's own daily
thread (YtDlpManager._loop), so there is no second thread and no second
opt-out: `ytdl_local_downloads = false` switches this off too.
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import os
import platform
import shutil
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from . import upgrade as upgrade_mod
from . import ytdlp_manager

log = logging.getLogger("ccsync.ffmpeg")

HttpOpenFn = ytdlp_manager.HttpOpenFn

# The pin. Bump BOTH the tag and every digest together, and re-verify each
# digest against a real download (curl + sha256sum), never against the GitHub
# API's word alone -- the 2026-08-16 pin was checked that way.
RELEASE_TAG = "b6.1.1"
RELEASE_BASE_URL = f"https://github.com/eugeneware/ffmpeg-static/releases/download/{RELEASE_TAG}"

# (sys.platform, arch) -> tool -> (asset name, sha256 of the .gz AS DOWNLOADED).
# The digest is of the compressed bytes: that is what the release vouches for,
# and verifying before gunzip means a bad download never gets inflated onto
# the disk at all. No linux entry on purpose -- the container is not an editor
# machine and installs its own ffmpeg; no winarm64 because the source ships
# none (a Windows-on-ARM editor simply keeps the server path).
PINNED_ASSETS: dict[tuple[str, str], dict[str, tuple[str, str]]] = {
    ("win32", "x64"): {
        "ffmpeg": ("ffmpeg-win32-x64.gz",
                   "8883a3dffbd0a16cf4ef95206ea05283f78908dbfb118f73c83f4951dcc06d77"),
        "ffprobe": ("ffprobe-win32-x64.gz",
                    "f309e6223ad89d2fe54bccd420a7709b66fd27540674e92309578ed491a43c8d"),
    },
    ("darwin", "arm64"): {
        "ffmpeg": ("ffmpeg-darwin-arm64.gz",
                   "8923876afa8db5585022d7860ec7e589af192f441c56793971276d450ed3bbfa"),
        "ffprobe": ("ffprobe-darwin-arm64.gz",
                    "d986a8ec7b030899fe66a8a288ed809a3543338705a3ce178cfb85869c5d80be"),
    },
    ("darwin", "x64"): {
        "ffmpeg": ("ffmpeg-darwin-x64.gz",
                   "929b375c1182d956c51f7ac25e0b2b0411fb01f6f407aa15c9758efeb4242106"),
        "ffprobe": ("ffprobe-darwin-x64.gz",
                    "d4da574d6e2e197bd259b47d69cf262df9e312af24ad960444f6d806d3d4c186"),
    },
}
TOOLS = ("ffmpeg", "ffprobe")

# The .gz assets are 19-30 MB; the ceiling is for a broken or hostile response,
# same reasoning as ytdlp_manager.MAX_DOWNLOAD_BYTES. The inflated binaries are
# 45-83 MB each, so the free-space pre-flight assumes both plus margin.
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
NOMINAL_INSTALLED_BYTES = 2 * 100 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = ytdlp_manager.DOWNLOAD_TIMEOUT_SECONDS

# ensure()'s `action`, ytdlp_manager's vocabulary.
ACTION_DISABLED = ytdlp_manager.ACTION_DISABLED
ACTION_NONE = ytdlp_manager.ACTION_NONE
ACTION_INSTALLED = ytdlp_manager.ACTION_INSTALLED
ACTION_FAILED = ytdlp_manager.ACTION_FAILED
ACTION_UNSUPPORTED = "unsupported"   # no pinned asset for this platform/arch

_work_lock = threading.Lock()


# ---------------------------------------------------------------------------
# where it lives
# ---------------------------------------------------------------------------


def binary_name(tool: str, plat: Optional[str] = None) -> str:
    p = plat if plat is not None else sys.platform
    return f"{tool}.exe" if p.startswith("win") else tool


def managed_path(tool: str = "ffmpeg") -> Path:
    """Where the managed `tool` is (or would be). Existence is not checked.

    ytdlp_manager.tools_dir() and nothing else: one platform-paths scheme."""
    return ytdlp_manager.tools_dir() / binary_name(tool)


def arch_key(machine: Optional[str] = None) -> Optional[str]:
    """platform.machine() -> "x64" | "arm64" | None (nothing pinned for it)."""
    m = (machine if machine is not None else platform.machine()).strip().lower()
    if m in ("amd64", "x86_64", "x64"):
        return "x64"
    if m in ("arm64", "aarch64"):
        return "arm64"
    return None


def pinned_assets(plat: Optional[str] = None,
                  machine: Optional[str] = None) -> Optional[dict[str, tuple[str, str]]]:
    """The tool->(asset, sha256) table for this machine, or None."""
    p = plat if plat is not None else sys.platform
    key = "win32" if p.startswith("win") else p
    arch = arch_key(machine)
    if arch is None:
        return None
    return PINNED_ASSETS.get((key, arch))


def is_installed(tool: str = "ffmpeg") -> bool:
    try:
        return managed_path(tool).is_file()
    except OSError:
        return False


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------


def _free_space_ok(directory: Path) -> bool:
    """ytdlp_manager._free_space_ok's check, sized for two inflated binaries."""
    try:
        free = shutil.disk_usage(str(directory)).free
    except Exception:
        log.debug("ffmpeg: free-space check failed; continuing", exc_info=True)
        return True
    needed = ytdlp_manager.MIN_FREE_BYTES_MARGIN + NOMINAL_INSTALLED_BYTES
    if free < needed:
        log.warning(
            "ffmpeg: %.0f MB free at %s but ffmpeg+ffprobe need about %.0f MB (+ margin) "
            "-- not downloading them. Local YouTube downloads stay off on this machine.",
            free / 1_000_000, directory, needed / 1_000_000,
        )
        return False
    return True


def _make_executable(path: Path) -> None:
    """After verification only, POSIX only -- ytdlp_manager's rule."""
    if sys.platform == "win32":
        return
    try:
        os.chmod(path, 0o755)
    except OSError as exc:
        log.warning("ffmpeg: could not set the execute bit on %s (%s)", path, exc)


def install_tool(tool: str, asset: str, expected_sha256: str, directory: Path,
                 github_open: Optional[HttpOpenFn] = None) -> bool:
    """Download one pinned .gz, verify it, inflate it beside its destination,
    and rename it into place. False on every failure, never an exception.

    Order is load-bearing, exactly as ytdlp_manager.install(): the .gz streams
    to a `.gz.new` in the tools dir with its digest computed as it lands; a
    digest that is not the pin deletes it unread; only a verified archive is
    inflated, to `<binary>.new` in the same dir, and os.replace() is the one
    visible moment. A killed process leaves `.new` files the next run
    truncates and nothing an editor has to clean up."""
    opener = github_open or ytdlp_manager.default_github_open
    url = f"{RELEASE_BASE_URL}/{asset}"
    gz_tmp = directory / (asset + ".new")
    bin_tmp = directory / (binary_name(tool) + ".new")
    digest = hashlib.sha256()
    written = 0
    try:
        with opener(url, {}, DOWNLOAD_TIMEOUT_SECONDS) as resp:
            status = upgrade_mod.redirect_status(resp)
            if status is not None:
                raise ValueError(f"{asset} download answered HTTP {status}")
            with gz_tmp.open("wb") as fh:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        raise ValueError(
                            f"{asset} exceeded the {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB ceiling"
                        )
                    fh.write(chunk)
                    digest.update(chunk)
    except Exception as exc:
        log.info("ffmpeg: %s download failed (%s)", asset, exc)
        _unlink_quietly(gz_tmp)
        return False

    if digest.hexdigest() != expected_sha256.lower():
        log.warning(
            "ffmpeg: sha256 mismatch on the downloaded %s (got %s, pinned %s) -- "
            "discarding it, nothing installed", asset, digest.hexdigest()[:12],
            expected_sha256[:12],
        )
        _unlink_quietly(gz_tmp)
        return False

    try:
        with gzip.open(gz_tmp, "rb") as src, bin_tmp.open("wb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
    except Exception as exc:
        log.warning("ffmpeg: could not inflate %s (%s)", asset, exc)
        _unlink_quietly(gz_tmp)
        _unlink_quietly(bin_tmp)
        return False
    _unlink_quietly(gz_tmp)

    _make_executable(bin_tmp)
    try:
        os.replace(bin_tmp, directory / binary_name(tool))
    except Exception as exc:
        log.warning("ffmpeg: could not move the verified %s into place (%s)", tool, exc)
        _unlink_quietly(bin_tmp)
        return False
    log.info("ffmpeg: installed %s", directory / binary_name(tool))
    return True


def ensure(cfg: Optional[dict[str, Any]] = None,
           github_open: Optional[HttpOpenFn] = None,
           available_fn: Optional[Callable[[str], bool]] = None) -> dict[str, Any]:
    """Make the managed ffmpeg + ffprobe present, if they should be. Never raises.

        opt-out (ytdl_local_downloads=false)   -> nothing, action=disabled
        editor's own ffmpeg_path resolves       -> nothing, action=none
                                                   (their install, never ours)
        no pinned asset for this platform/arch -> nothing, action=unsupported
        both present in the tools dir          -> nothing, action=none
        any missing                            -> install what is missing

    A binary that is present is trusted as-is; there is no version floor
    to chase (see the module docstring). Deleting the file is the reset.

    `available_fn` answers "does the configured ffmpeg_path already resolve
    to something OUTSIDE the tools dir?" -- ffmpeg_tools._resolve_binary by
    default. An editor with `winget install Gyan.FFmpeg` on PATH, or an
    explicit ffmpeg_path, keeps theirs and we download nothing.
    """
    if not ytdlp_manager.local_downloads_enabled(cfg):
        return {"ok": False, "action": ACTION_DISABLED,
                "message": "local YouTube downloads are switched off in config"}

    with _work_lock:
        try:
            if _editor_has_own_ffmpeg(cfg, available_fn):
                return {"ok": True, "action": ACTION_NONE,
                        "message": "using the ffmpeg already on this machine"}
        except Exception:
            log.debug("ffmpeg: own-ffmpeg check failed; continuing", exc_info=True)

        table = pinned_assets()
        if table is None:
            return {"ok": False, "action": ACTION_UNSUPPORTED,
                    "message": f"no pinned ffmpeg for {sys.platform}/{platform.machine()} "
                               f"-- YouTube downloads stay on the server"}

        missing = [tool for tool in TOOLS if not is_installed(tool)]
        if not missing:
            return {"ok": True, "action": ACTION_NONE,
                    "message": f"ffmpeg {RELEASE_TAG} is installed"}

        directory = ytdlp_manager.ensure_tools_dir()
        if directory is None or not _free_space_ok(directory):
            return {"ok": False, "action": ACTION_FAILED,
                    "message": "ffmpeg could not be installed (tools dir or free space) "
                               "-- YouTube downloads stay on the server"}

        failed = []
        for tool in missing:
            asset, sha = table[tool]
            if not install_tool(tool, asset, sha, directory, github_open):
                failed.append(tool)
        if failed:
            return {"ok": False, "action": ACTION_FAILED,
                    "message": f"could not install {', '.join(failed)} -- YouTube "
                               f"downloads stay on the server"}
        return {"ok": True, "action": ACTION_INSTALLED,
                "message": f"installed ffmpeg {RELEASE_TAG} ({', '.join(missing)}) into {directory}"}


def _editor_has_own_ffmpeg(cfg: Optional[dict[str, Any]],
                           available_fn: Optional[Callable[[str], bool]]) -> bool:
    """True when `ffmpeg_path` resolves to something that is NOT ours.

    Deferred import: ffmpeg_tools' fallback lookup imports THIS module's
    location helper, and a top-level import each way would be a cycle."""
    from . import config as config_mod
    from . import ffmpeg_tools

    configured = str((cfg or {}).get(
        "ffmpeg_path", config_mod.DEFAULTS.get("ffmpeg_path", "ffmpeg")) or "").strip()
    if not configured:
        return False
    if available_fn is not None:
        return bool(available_fn(configured))
    if os.path.isabs(configured) or os.path.dirname(configured):
        # An explicit path is the editor's decision either way: present, it
        # is theirs; absent, installing OUR copy somewhere the bare-name
        # fallback never looks would download 160 MB nothing can use, and
        # the honest answer is capabilities()' "ffmpeg is not installed"
        # against the path they wrote.
        return True
    resolved = ffmpeg_tools._resolve_binary(configured, managed_fallback=False)
    return bool(resolved)


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
