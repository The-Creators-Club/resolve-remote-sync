"""The pinned sidecar tools: a static ffmpeg + ffprobe and a deno, installed
by the companion into the same `tools` dir yt-dlp lives in.

WHY IT EXISTS (2026-08-16). Requester-first YouTube downloads shipped in 0.7.8
and never engaged on a single editor machine. One reason was this: every rung
the local executor runs is a `bestvideo+bestaudio` merge, ffmpeg does the
merge, and no editor has ffmpeg -- nothing ever put one there. The proxy
generator was written with ffmpeg as an OPTIONAL dependency (`winget install
Gyan.FFmpeg` if you want proxies), which is fine for a base-rig feature and
fatal for a fleet feature: an editor's `/ytdl/capabilities` answered `ok:false
-- ffmpeg is not installed` (COMP-BROLL-5 refusing the claim, correctly), so
every job took the server path, the NAS downloaded, and lane B carried the
originals back down.

deno joined the same day, for signed-in downloads. Measured on the base rig
with the fleet's yt-dlp 2026.07.04: with NO JavaScript runtime an anonymous
download still gets 1080p (yt-dlp's deprecated no-runtime path), but the
moment cookies are supplied every format vanishes -- "n challenge solving
failed ... Only images are available" -- because the signed-in web client
demands the JS challenge be solved. With a runtime, cookies pass the age gate
(`age_limit=18`, formats returned) and 1080p comes back, no PO-token sidecar
needed on a residential IP. yt-dlp enables only deno by default (node needs
`--js-runtimes node`), the official yt-dlp.exe does not bundle one, and no
editor has one: so the companion installs it and hands yt-dlp the path
(`--js-runtimes deno:<path>`, ytdl_executor.build_argv).

WHY PINNED, NOT "LATEST" (unlike ytdlp_manager). yt-dlp has to track the
newest release because YouTube breaks it on purpose; ffmpeg and deno have no
such adversary. So each release is pinned by tag and each asset by sha256,
both hardcoded here: no GitHub API call, no checksum file to fetch, and an
artifact that does not match the pin is not installed. Bumping a pin is a
code change with a review, which is what "the fleet now runs a different
binary" deserves. Every digest below was checked against a real download
(curl + sha256sum), never against the GitHub API's word alone.

WHY THESE SOURCES. eugeneware/ffmpeg-static republishes gyan.dev's Windows and
evermeet's macOS static builds as ONE FILE PER PLATFORM (`ffmpeg-win32-x64.gz`
etc.), which is the shape ytdlp_manager already downloads and verifies -- no
zip walking, no `bin/` layout guessing, and it covers darwin-arm64, which
yt-dlp's own FFmpeg-Builds do not. Measured 2026-08-16: the win32-x64 asset
inflates to an 82.8 MB `ffmpeg version 6.1.1-essentials_build` that runs
(libx264/x265 + NVENC, so the proxy generator gets to use it too). deno's own
GitHub release is a zip holding exactly one file (`deno.exe` / `deno`),
97 MB inflated; `deno --version` on it reads 2.9.5.

    Windows:  %LOCALAPPDATA%\\ccsync\\tools\\{ffmpeg,ffprobe,deno}.exe
    macOS:    ~/Library/Application Support/ccsync/tools/{ffmpeg,ffprobe,deno}

ffprobe rides along because ffmpeg_tools.ffprobe_for() looks for it BESIDE
ffmpeg and the proxy generator's probe/verify passes need it; yt-dlp uses it
when present. Same dir, same pin, same verification.

Everything here is BEST-EFFORT and quiet, on ytdlp_manager's exact terms: a
missing or unverifiable download is a log line, capabilities() keeps
answering "no ffmpeg" (or "not signed in") and the server downloads instead.
Nothing here may raise into the tray or hold up startup. It runs on the
yt-dlp manager's own daily thread (YtDlpManager._loop), so there is no second
thread and no second opt-out: `ytdl_local_downloads = false` switches this
off too.

TWO GATES SINCE 2026-08-17 (docs/COMMERCIAL_READINESS.md items 2 + 3). The
whole module is inert unless the customer's site manifest says
`youtube_download`; and **deno alone additionally needs `youtube_unblock`**,
because a JS runtime here is not a codec, it is the thing that answers
YouTube's anti-automation challenge. The vendor build therefore installs
ffmpeg/ffprobe and no challenge solver; a customer entitled to one turns it on
in their own site.toml. Nothing is stripped -- the pins and the installer stay
here, dormant -- so enabling it is a config change, never a second binary.
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
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional

from . import upgrade as upgrade_mod
from . import ytdlp_manager

log = logging.getLogger("ccsync.sidecar")

HttpOpenFn = ytdlp_manager.HttpOpenFn

# The pins. Bump a tag and every digest under it together, and re-verify each
# digest against a real download.
FFMPEG_RELEASE_TAG = "b6.1.1"
FFMPEG_BASE_URL = f"https://github.com/eugeneware/ffmpeg-static/releases/download/{FFMPEG_RELEASE_TAG}"
DENO_RELEASE_TAG = "v2.9.5"
DENO_BASE_URL = f"https://github.com/denoland/deno/releases/download/{DENO_RELEASE_TAG}"

# How an asset unpacks: "gz" is one gzip'd binary; "zip" is an archive whose
# ONE member named binary_name(tool) is the binary (deno's release layout).
KIND_GZ = "gz"
KIND_ZIP = "zip"

# (sys.platform, arch) -> tool -> (asset URL, sha256 of the asset AS
# DOWNLOADED, kind). The digest is of the downloaded bytes: that is what the
# release vouches for, and verifying before unpacking means a bad download
# never gets inflated onto the disk at all. No linux entry on purpose -- the
# container is not an editor machine and installs its own; no winarm64
# because the ffmpeg source ships none (a Windows-on-ARM editor simply keeps
# the server path).
PINNED_ASSETS: dict[tuple[str, str], dict[str, tuple[str, str, str]]] = {
    ("win32", "x64"): {
        "ffmpeg": (f"{FFMPEG_BASE_URL}/ffmpeg-win32-x64.gz",
                   "8883a3dffbd0a16cf4ef95206ea05283f78908dbfb118f73c83f4951dcc06d77", KIND_GZ),
        "ffprobe": (f"{FFMPEG_BASE_URL}/ffprobe-win32-x64.gz",
                    "f309e6223ad89d2fe54bccd420a7709b66fd27540674e92309578ed491a43c8d", KIND_GZ),
        "deno": (f"{DENO_BASE_URL}/deno-x86_64-pc-windows-msvc.zip",
                 "171efab55ac6b9881fd53ee4c20f8bf3bb1340ffc618483746909014db12216a", KIND_ZIP),
    },
    ("darwin", "arm64"): {
        "ffmpeg": (f"{FFMPEG_BASE_URL}/ffmpeg-darwin-arm64.gz",
                   "8923876afa8db5585022d7860ec7e589af192f441c56793971276d450ed3bbfa", KIND_GZ),
        "ffprobe": (f"{FFMPEG_BASE_URL}/ffprobe-darwin-arm64.gz",
                    "d986a8ec7b030899fe66a8a288ed809a3543338705a3ce178cfb85869c5d80be", KIND_GZ),
        "deno": (f"{DENO_BASE_URL}/deno-aarch64-apple-darwin.zip",
                 "b796aadd131f6930560c1ee040cf0d6f53933fbb987464e9ff46bd7ea4830615", KIND_ZIP),
    },
    ("darwin", "x64"): {
        "ffmpeg": (f"{FFMPEG_BASE_URL}/ffmpeg-darwin-x64.gz",
                   "929b375c1182d956c51f7ac25e0b2b0411fb01f6f407aa15c9758efeb4242106", KIND_GZ),
        "ffprobe": (f"{FFMPEG_BASE_URL}/ffprobe-darwin-x64.gz",
                    "d4da574d6e2e197bd259b47d69cf262df9e312af24ad960444f6d806d3d4c186", KIND_GZ),
        "deno": (f"{DENO_BASE_URL}/deno-x86_64-apple-darwin.zip",
                 "c1b8b89a81e91b2a8b3f96def3195d08cfe3a105651da7908d53061f7140510d", KIND_ZIP),
    },
}
TOOLS = ("ffmpeg", "ffprobe", "deno")

# The assets are 19-43 MB; the ceiling is for a broken or hostile response,
# same reasoning as ytdlp_manager.MAX_DOWNLOAD_BYTES. Inflated, the three
# weigh ~45-100 MB each, so the free-space pre-flight assumes all plus margin.
MAX_DOWNLOAD_BYTES = 96 * 1024 * 1024
NOMINAL_INSTALLED_BYTES = 3 * 100 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = ytdlp_manager.DOWNLOAD_TIMEOUT_SECONDS

# ensure()'s `action`, ytdlp_manager's vocabulary.
ACTION_DISABLED = ytdlp_manager.ACTION_DISABLED
ACTION_NONE = ytdlp_manager.ACTION_NONE
ACTION_INSTALLED = ytdlp_manager.ACTION_INSTALLED
ACTION_FAILED = ytdlp_manager.ACTION_FAILED
ACTION_UNSUPPORTED = "unsupported"   # no pinned asset for this platform/arch

# RLock, not Lock (2026-08-18): `ensure()` holds it and calls
# `ensure_ffmpeg_pair()`, which takes it too. Same thread, one install at a
# time -- a plain Lock would deadlock the yt-dlp manager's daily thread on the
# first pass and take the tray's tools maintenance with it.
_work_lock = threading.RLock()

# comp-ytdl-jobs-3 (2026-09-11): WHY the last install failed, per tool, and how
# many passes in a row have failed. Until this existed the cause ("certificate
# verify failed" on a Mac whose Python has no CA bundle -- a live field
# problem) went into one log line, at DEBUG on the vendor default, and the only
# fleet-visible consequence was capabilities.ffmpeg=false: a machine silently
# ineligible for every media job kind, reading as "never set up" rather than
# "cannot reach GitHub". In memory: the disk is not the problem here, and the
# count only has to survive the daily thread, not a restart.
_failure_causes: dict[str, str] = {}
_consecutive_failures = 0


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
                  machine: Optional[str] = None) -> Optional[dict[str, tuple[str, str, str]]]:
    """The tool->(url, sha256, kind) table for this machine, or None."""
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


def _unblock_enabled() -> bool:
    """Has the customer's site turned the unblock components on? Fails closed.

    A thin wrapper so the two callers below read the same answer and tests have
    one thing to patch. See ytdlp_manager.unblock_enabled for the reasoning.
    """
    try:
        return ytdlp_manager.unblock_enabled()
    except Exception:                          # noqa: BLE001 - never raises
        log.debug("sidecar: unblock flag unreadable; treating it as off",
                  exc_info=True)
        return False


def managed_deno() -> Optional[str]:
    """The managed deno's path, or None. What ytdl_executor hands yt-dlp.

    None when the site has not enabled `youtube_unblock`, EVEN IF the binary
    is on disk from before the flag existed (2026-08-17): the switch has to
    stop yt-dlp being handed a challenge solver, not merely stop a download.
    Deleting the file is the operator's call, not this function's.
    """
    if not _unblock_enabled():
        return None
    return str(managed_path("deno")) if is_installed("deno") else None


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------


def _free_space_ok(directory: Path) -> bool:
    """ytdlp_manager._free_space_ok's check, sized for the inflated binaries."""
    try:
        free = shutil.disk_usage(str(directory)).free
    except Exception:
        log.debug("sidecar: free-space check failed; continuing", exc_info=True)
        return True
    needed = ytdlp_manager.MIN_FREE_BYTES_MARGIN + NOMINAL_INSTALLED_BYTES
    if free < needed:
        log.warning(
            "sidecar: %.0f MB free at %s but ffmpeg+ffprobe+deno need about %.0f MB "
            "(+ margin) -- not downloading them. Local YouTube downloads stay off "
            "on this machine.", free / 1_000_000, directory, needed / 1_000_000,
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
        log.warning("sidecar: could not set the execute bit on %s (%s)", path, exc)


def _unpack(kind: str, archive: Path, member: str, dest: Path) -> None:
    """Inflate one binary out of `archive` into `dest`. Raises on anything."""
    if kind == KIND_GZ:
        with gzip.open(archive, "rb") as src, dest.open("wb") as out:
            shutil.copyfileobj(src, out, 1024 * 1024)
        return
    if kind == KIND_ZIP:
        with zipfile.ZipFile(archive) as zf:
            # Exactly the named member, never zf.extractall(): a zip that
            # decided to carry ../ paths must not get to write them.
            with zf.open(member) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
        return
    raise ValueError(f"unknown asset kind {kind!r}")


def install_tool(tool: str, url: str, expected_sha256: str, kind: str, directory: Path,
                 github_open: Optional[HttpOpenFn] = None) -> bool:
    """Download one pinned asset, verify it, unpack it beside its destination,
    and rename it into place. False on every failure, never an exception.

    Order is load-bearing, exactly as ytdlp_manager.install(): the asset
    streams to a `.new` in the tools dir with its digest computed as it lands;
    a digest that is not the pin deletes it unread; only a verified archive is
    unpacked, to `<binary>.new` in the same dir, and os.replace() is the one
    visible moment. A killed process leaves `.new` files the next run
    truncates and nothing an editor has to clean up."""
    opener = github_open or ytdlp_manager.default_github_open
    asset = url.rsplit("/", 1)[-1]
    archive_tmp = directory / (asset + ".new")
    bin_tmp = directory / (binary_name(tool) + ".new")
    digest = hashlib.sha256()
    written = 0
    try:
        with opener(url, {}, DOWNLOAD_TIMEOUT_SECONDS) as resp:
            status = upgrade_mod.redirect_status(resp)
            if status is not None:
                raise ValueError(f"{asset} download answered HTTP {status}")
            with archive_tmp.open("wb") as fh:
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
        # comp-ytdl-jobs-3: the cause is kept, not just logged. It is the
        # difference between "this machine cannot reach GitHub" and "this
        # machine was never set up", and only one of them has an action.
        _note_cause(tool, str(exc))
        log.info("sidecar: %s download failed (%s)", asset, exc)
        _unlink_quietly(archive_tmp)
        return False

    if digest.hexdigest() != expected_sha256.lower():
        _note_cause(tool, f"sha256 mismatch on {asset} (got "
                          f"{digest.hexdigest()[:12]}, pinned {expected_sha256[:12]})")
        log.warning(
            "sidecar: sha256 mismatch on the downloaded %s (got %s, pinned %s) -- "
            "discarding it, nothing installed", asset, digest.hexdigest()[:12],
            expected_sha256[:12],
        )
        _unlink_quietly(archive_tmp)
        return False

    try:
        _unpack(kind, archive_tmp, binary_name(tool), bin_tmp)
    except Exception as exc:
        _note_cause(tool, f"could not unpack {asset}: {exc}")
        log.warning("sidecar: could not unpack %s (%s)", asset, exc)
        _unlink_quietly(archive_tmp)
        _unlink_quietly(bin_tmp)
        return False
    _unlink_quietly(archive_tmp)

    _make_executable(bin_tmp)
    try:
        os.replace(bin_tmp, directory / binary_name(tool))
    except Exception as exc:
        _note_cause(tool, f"could not move the verified {tool} into place: {exc}")
        log.warning("sidecar: could not move the verified %s into place (%s)", tool, exc)
        _unlink_quietly(bin_tmp)
        return False
    _failure_causes.pop(tool, None)
    log.info("sidecar: installed %s", directory / binary_name(tool))
    return True


def _note_cause(tool: str, cause: str) -> None:
    """Remember WHY `tool` could not be installed (comp-ytdl-jobs-3). Never
    raises: it is bookkeeping on a best-effort path."""
    try:
        _failure_causes[str(tool)] = str(cause or "").strip()[:200]
    except Exception:                                           # pragma: no cover
        pass


def failure_cause(tools: Optional[list[str]] = None) -> str:
    """The last recorded cause across `tools` (or all of them), or ""."""
    names = list(tools) if tools else list(_failure_causes)
    for name in names:
        cause = _failure_causes.get(str(name))
        if cause:
            return cause
    return ""


def consecutive_failures() -> int:
    """How many install passes in a row have failed (comp-ytdl-jobs-3)."""
    return _consecutive_failures


def reset_failures() -> None:
    """Test hook and the clean-pass reset."""
    global _consecutive_failures
    _consecutive_failures = 0
    _failure_causes.clear()


def _note_pass(failed: bool, failed_tools: Optional[list[str]] = None) -> int:
    """Count one install pass and log a REPEAT at WARNING (comp-ytdl-jobs-3).

    WARNING here rather than in ytdlp_manager._loop's log.log, because that
    line is demoted to DEBUG when the YouTube downloader is off -- the vendor
    default -- and the ffmpeg pair stopped being a YouTube entitlement in
    comp-ytdl-2. The first failure is allowed to be quiet: GitHub blips.
    """
    global _consecutive_failures
    if not failed:
        reset_failures()
        return 0
    _consecutive_failures += 1
    if _consecutive_failures >= 2:
        log.warning("sidecar: %s could not be installed on %s consecutive "
                    "passes (%s) -- this machine will not be offered proxy, "
                    "audio or peaks work",
                    ", ".join(failed_tools or ["ffmpeg"]), _consecutive_failures,
                    failure_cause(failed_tools) or "no cause recorded")
    return _consecutive_failures


def ensure_ffmpeg_pair(cfg: Optional[dict[str, Any]] = None,
                       github_open: Optional[HttpOpenFn] = None,
                       available_fn: Optional[Callable[[str], bool]] = None) -> dict[str, Any]:
    """Make the managed ffmpeg + ffprobe present, if they should be. Never
    raises. **No YouTube gate.**

    Factored out of ensure() 2026-08-18 (docs/BROLL_INGEST_PLAN.md §3.3): the
    ffmpeg pair was installed only where the site's manifest turned
    `youtube_download` on, because until now that was the only feature that
    needed one. B-roll ingest needs ffmpeg on the editor's machine regardless
    -- proxy, sprite, poster, scene detection and frame extraction are ALL
    ffmpeg -- and the proxy generator has always wanted one too (it degrades to
    notifier-only without). A codec is not an entitlement; deno still is, and
    `ensure()` above keeps both of its gates for it.

        no pinned asset for this platform/arch -> nothing, action=unsupported
        editor's own ffmpeg_path resolves       -> nothing, action=none (theirs)
        both already installed                  -> nothing, action=none
        either missing                          -> install what is missing

    `available_fn` answers "does the configured ffmpeg_path already resolve to
    something OUTSIDE the tools dir?" -- ffmpeg_tools._resolve_binary by
    default. An editor with `winget install Gyan.FFmpeg` on PATH, or an
    explicit ffmpeg_path, keeps theirs and we download nothing.
    """
    with _work_lock:
        table = pinned_assets()
        if table is None:
            return {"ok": False, "action": ACTION_UNSUPPORTED,
                    "message": f"no pinned ffmpeg for {sys.platform}/{platform.machine()} "
                               f"-- this machine cannot make proxies or index b-roll"}

        try:
            own_ffmpeg = _editor_has_own_ffmpeg(cfg, available_fn)
        except Exception:
            log.debug("sidecar: own-ffmpeg check failed; continuing", exc_info=True)
            own_ffmpeg = False
        if own_ffmpeg:
            _note_pass(False)
            return {"ok": True, "action": ACTION_NONE, "own_ffmpeg": True,
                    "installed": [], "failed": [],
                    "message": "using the ffmpeg already on this machine"}

        missing = [tool for tool in ("ffmpeg", "ffprobe") if not is_installed(tool)]
        if not missing:
            _note_pass(False)
            return {"ok": True, "action": ACTION_NONE, "own_ffmpeg": False,
                    "installed": [], "failed": [],
                    "message": f"ffmpeg {FFMPEG_RELEASE_TAG} is installed"}

        directory = ytdlp_manager.ensure_tools_dir()
        if directory is None or not _free_space_ok(directory):
            _note_cause("ffmpeg", "no tools dir, or not enough free space for it")
            failures = _note_pass(True, list(missing))
            return {"ok": False, "action": ACTION_FAILED, "own_ffmpeg": False,
                    "installed": [], "failed": list(missing), "no_room": True,
                    "cause": failure_cause(list(missing)),
                    "consecutive_failures": failures,
                    "message": "ffmpeg could not be installed (tools dir or free space)"}

        installed, failed = [], []
        for tool in missing:
            url, sha, kind = table[tool]
            if install_tool(tool, url, sha, kind, directory, github_open):
                installed.append(tool)
            else:
                failed.append(tool)
        if failed:
            # comp-ytdl-jobs-3: the CAUSE rides the message. "could not
            # install ffmpeg" with no reason is the line that reached an
            # admin for a year and told them nothing they could act on.
            cause = failure_cause(failed)
            failures = _note_pass(True, failed)
            return {"ok": False, "action": ACTION_FAILED, "own_ffmpeg": False,
                    "installed": installed, "failed": failed,
                    "cause": cause, "consecutive_failures": failures,
                    "message": (f"could not install {', '.join(failed)}"
                                + (f": {cause}" if cause else ""))}
        _note_pass(False)
        return {"ok": True, "action": ACTION_INSTALLED, "own_ffmpeg": False,
                "installed": installed, "failed": [],
                "message": f"installed {', '.join(installed)} into {directory}"}


def ensure(cfg: Optional[dict[str, Any]] = None,
           github_open: Optional[HttpOpenFn] = None,
           available_fn: Optional[Callable[[str], bool]] = None) -> dict[str, Any]:
    """Make the managed ffmpeg + ffprobe + deno present, if they should be.
    Never raises.

        opt-out (ytdl_local_downloads=false)   -> nothing, action=disabled
        no pinned asset for this platform/arch -> nothing, action=unsupported
        editor's own ffmpeg_path resolves       -> ffmpeg pair skipped (theirs)
        deno already on PATH                    -> deno skipped (yt-dlp finds it)
        everything wanted is present            -> nothing, action=none
        anything wanted is missing              -> install what is missing

    A binary that is present is trusted as-is; there is no version floor
    to chase (see the module docstring). Deleting the file is the reset.

    `available_fn` answers "does the configured ffmpeg_path already resolve
    to something OUTSIDE the tools dir?" -- ffmpeg_tools._resolve_binary by
    default. An editor with `winget install Gyan.FFmpeg` on PATH, or an
    explicit ffmpeg_path, keeps theirs and we download nothing for it.
    """
    if not ytdlp_manager.youtube_enabled(cfg):
        # Either the site never turned the downloader on (2026-08-17 --
        # COMMERCIAL_READINESS.md item 2, the default) or this editor opted
        # their machine out. Same answer: nothing is downloaded onto the disk.
        #
        # NB since 2026-08-18 this gate covers DENO ONLY in practice: the
        # ffmpeg pair is installed by ensure_ffmpeg_pair(), which the sidecar
        # thread calls directly whenever the downloader is off
        # (ytdlp_manager._loop, docs/BROLL_INGEST_PLAN.md §3.3) because
        # b-roll ingest and proxy generation need a merger whatever the site
        # says about YouTube. That wiring did not exist until comp-ytdl-2
        # (2026-08-21): this early return was the only path, so a vendor-build
        # machine reached ensure_ffmpeg_pair never and had no ffmpeg at all.
        # What this branch still guarantees is what it always meant here: with
        # the downloader off, THIS function downloads nothing at all.
        return {"ok": False, "action": ACTION_DISABLED,
                "message": "the YouTube downloader is off for this site or "
                           "switched off in config"}

    # The ffmpeg half, with no gate of its own -- the yt-dlp merge needs it,
    # and so do proxies and b-roll ingest.
    pair = ensure_ffmpeg_pair(cfg, github_open, available_fn)
    if pair["action"] == ACTION_UNSUPPORTED:
        return {"ok": False, "action": ACTION_UNSUPPORTED,
                "message": f"no pinned ffmpeg/deno for {sys.platform}/{platform.machine()} "
                           f"-- YouTube downloads stay on the server"}
    own_ffmpeg = bool(pair.get("own_ffmpeg"))
    installed = list(pair.get("installed") or [])
    failed = list(pair.get("failed") or [])
    no_room = bool(pair.get("no_room"))

    with _work_lock:
        table = pinned_assets()
        if table is None:  # pragma: no cover - ensure_ffmpeg_pair already said so
            return {"ok": False, "action": ACTION_UNSUPPORTED,
                    "message": f"no pinned ffmpeg/deno for {sys.platform}/{platform.machine()} "
                               f"-- YouTube downloads stay on the server"}

        # deno IS the n-challenge solver: its only job here is to answer the
        # JavaScript challenge YouTube serves signed-in clients, which is an
        # anti-anti-automation component and therefore not part of the vendor
        # build's default install (COMMERCIAL_READINESS.md item 3,
        # docs/legal/YOUTUBE_FEATURE_NOTICE.md). It is downloaded only where
        # the customer's site manifest says `youtube_unblock`. The code stays
        # exactly as it was -- dormant, not deleted -- so turning the flag on
        # is a config change and never a different binary.
        wants_deno = _unblock_enabled() and not _editor_has_own_deno()
        if wants_deno and not is_installed("deno"):
            directory = ytdlp_manager.ensure_tools_dir()
            if directory is None or not _free_space_ok(directory):
                _note_cause("deno", "no tools dir, or not enough free space for it")
                failed.append("deno")
                no_room = True
            else:
                url, sha, kind = table["deno"]
                if install_tool("deno", url, sha, kind, directory, github_open):
                    installed.append("deno")
                else:
                    failed.append("deno")

        # comp-ytdl-jobs-2 (2026-09-11b): ONE PASS IS COUNTED ONCE, whichever
        # entry point ran. `ensure_ffmpeg_pair` above counts its own verdict,
        # so a failure it already recorded must not be counted a second time
        # here (that would fire the two-pass warning on pass one), and a
        # failure only this function can see -- deno, or the tools dir going
        # away between the two calls -- must be counted at all. `pair_failed`
        # is exactly "the pair already took this pass".
        pair_failed = bool(pair.get("failed"))
        if (no_room or failed) and not pair_failed:
            failures = _note_pass(True, list(failed) or ["ffmpeg"])
        else:
            failures = consecutive_failures()
        if no_room:
            # CR-237 attached the cause and the counter to ensure_ffmpeg_pair's
            # returns only, and these two are the returns a machine with the
            # downloader ON actually reaches (ytdlp_manager._loop calls
            # ensure() there and ensure_ffmpeg_pair() only when it is off).
            # Without them `sidecar_warning_line` returns "" for ever and
            # `sync_guard.ytdlp.sidecar` says nothing, so a machine that has
            # silently stopped being offered proxy/audio/peaks work has no
            # sentence anywhere a person looks -- which is the state the
            # finding was raised about.
            return {"ok": False, "action": ACTION_FAILED,
                    "failed": list(failed) or ["ffmpeg", "ffprobe"],
                    "cause": failure_cause(list(failed) or None),
                    "consecutive_failures": failures,
                    "message": "sidecar tools could not be installed (tools dir or free space) "
                               "-- YouTube downloads stay on the server"}
        if failed:
            cause = failure_cause(failed)
            return {"ok": False, "action": ACTION_FAILED,
                    "failed": list(failed), "cause": cause,
                    "consecutive_failures": failures,
                    "message": f"could not install {', '.join(failed)} -- "
                               + ("YouTube downloads stay on the server"
                                  if "ffmpeg" in failed else
                                  "signed-in YouTube downloads stay off on this machine")
                               + (f" ({cause})" if cause else "")}
        if installed:
            return {"ok": True, "action": ACTION_INSTALLED,
                    "message": f"installed {', '.join(installed)} into "
                               f"{ytdlp_manager.tools_dir()}"}

        parts = ["using the ffmpeg already on this machine" if own_ffmpeg
                 else f"ffmpeg {FFMPEG_RELEASE_TAG} is installed"]
        parts.append(f"deno {DENO_RELEASE_TAG} is installed"
                     if wants_deno or is_installed("deno")
                     else "no JS runtime (this site has not enabled "
                          "youtube_unblock)")
        return {"ok": True, "action": ACTION_NONE, "message": "; ".join(parts)}


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


def _editor_has_own_deno() -> bool:
    """yt-dlp finds a PATH deno by itself; ours would be 97 MB of duplicate."""
    try:
        return shutil.which("deno") is not None
    except Exception:
        return False


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
