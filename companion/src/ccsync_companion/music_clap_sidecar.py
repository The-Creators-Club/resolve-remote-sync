"""The companion's front door to the CLAP AUDIO tower: where the artefact
lives, fetching it with progress, and turning one audio file into one
512-float embedding.

`music_clap/` is vendored verbatim from the indexer (the catalogue and the mel
front end, see that package's __init__). This module is the part that is the
COMPANION's: the tools dir the rest of the app already uses, the release-feed
host allow-list, the free-space floor the upgrade path already agreed on, the
window-suppressed ffmpeg spawn every other companion probe uses, a zero-I/O
`status()` the tray and the reporter can call on every tick, and the refusals
in the words an editor reads.

Four rules this module exists to enforce (docs/MUSIC_INGEST_PLAN.md §1, §3):

  * **CPU is fine here.** Unlike the b-roll VLM sidecar, there is no GPU
    refusal and no tier: the audio tower is ~90 M parameters and a 3-minute
    track is ~18 ten-second windows. onnxruntime picks the best execution
    provider it was BUILT with (CUDA or DirectML if that package happens to be
    installed, CPU otherwise) and CPU is never a reason to decline work.
  * **Never a surprise download from anywhere.** The two files are pinned by
    sha256 in the vendored catalogue and fetched only from the site's own
    release-feed host. An entry still carrying the catalogue's placeholder is
    refused rather than fetched: an unpinned model is an unverified download.
  * **Never a temp WAV.** ffmpeg writes raw f32le to a pipe and numpy reads
    the pipe. A 60 MB wav copied into staging per track would double the disk
    traffic of an ingest and leave debris behind a killed process.
  * **Never write to stderr.** The tray is a windowed PyInstaller build where
    `sys.stderr` is None, so every child is spawned with pipes and the
    progress callback is what the download reports through.

Nothing here is imported at tray start: numpy, onnxruntime and the vendored
package are imported lazily inside the functions that need them, so a machine
that never ingests music never pays for them.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from . import site as site_mod
from . import upgrade as upgrade_mod
from . import ytdlp_manager
from .ffmpeg_tools import _win_creationflags

log = logging.getLogger("ccsync.musicclap")

# A sibling of the b-roll model cache under the same tools dir, for the reason
# broll_vlm_sidecar gives: one platform-paths scheme in the companion, and
# exactly one place an operator has to look (or delete) when a machine is being
# reclaimed.
CACHE_DIR_NAME = "music-clap"

# How long the on-disk readiness answer is trusted. status() itself does NO
# I/O -- it returns this cache -- and refresh() is what stats the files.
STATUS_TTL_SECONDS = 60.0

# Decoding is bounded because the whole signal is held in memory to window it
# (the indexer does the same on a workstation; this runs on a laptop while
# somebody is editing). Two hours of 48 kHz mono float32 is ~1.4 GB, which is
# already past what an editor's machine should spend on one dropped file, and
# nothing in a music library is legitimately longer.
MAX_DECODE_SECONDS = 2 * 60 * 60

# ffmpeg/ffprobe timeouts. The indexer's own numbers (music_index.audio).
PROBE_TIMEOUT_SECONDS = 120
DECODE_TIMEOUT_SECONDS = 900
TRANSCODE_TIMEOUT_SECONDS = 900

# The mp3 an .ogg becomes on the way in. `routes_ingest.MP3_BITRATE`, and the
# same command: the rule has to be the byte-for-byte same one wherever it runs,
# or the same album ingested through two doors lands as two different files.
MP3_BITRATE = "320k"

# The waveform overview's bucket count -- music_index.audio.PEAK_BUCKETS. The
# server stores whatever length arrives, but the drawing code and every track
# already in the library assume this one.
PEAK_BUCKETS = 900

# Hosts the download is allowed to reach. Unlike the b-roll sidecar's fixed
# github/huggingface list, this one is DERIVED: the artefact is ours and is
# served from the site's own release feed, so the allow-list is exactly that
# feed's host plus the hosts a feed on GitHub Releases redirects to
# (release_feed.py follows those, https-only, for the same reason).
ALLOWED_HOST_PATTERNS = (
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "*.githubusercontent.com",
)


class SidecarError(RuntimeError):
    """This FILE could not be embedded on this machine. Carries the
    editor-facing sentence; `ensure()` returns it rather than raising, because
    its caller (the ingest tick) has a per-track failure path already.
    """


class ModelUnavailable(SidecarError):
    """The MODEL is not usable here -- as opposed to the file being unreadable.

    The distinction is what decides an item's fate (music_ingest.
    _crunch_item): a file this machine cannot decode has FAILED and retrying it
    elsewhere would only move the failure, while a machine that cannot load the
    model at all should still put the audio in the library and leave the
    analysis to the base rig (docs/MUSIC_INGEST_PLAN.md 1, the kept fallback).
    Both are SidecarError, so a caller that does not care catches one thing.
    """


_lock = threading.RLock()
_session: Any = None
_session_key: str = ""
_extractor: Any = None
_status_cache: dict[str, Any] = {
    "ready": False,
    "runtime_ready": None,       # None = onnxruntime has not been asked yet
    "providers": [],
    "downloading": None,
    "last_error": "",
    "at": 0.0,
}


# ---------------------------------------------------------------------------
# where it lives
# ---------------------------------------------------------------------------

def _models():
    from .music_clap import music_models
    return music_models


def _mel():
    from .music_clap import mel_numpy
    return mel_numpy


def cache_dir() -> Path:
    """`<tools dir>/music-clap`. Existence is not checked."""
    return ytdlp_manager.tools_dir() / CACHE_DIR_NAME


def artefact_paths(key: str = "") -> tuple[Path, Path]:
    """(onnx, params) under our cache dir. No I/O."""
    models = _models()
    onnx_name, params_name = models.filenames(key or models.DEFAULT_MODEL)
    directory = cache_dir()
    return directory / onnx_name, directory / params_name


def artefact_version(key: str = "") -> str:
    models = _models()
    return str(models.model(key or models.DEFAULT_MODEL).get("version") or "")


def model_id(key: str = "") -> str:
    """What goes in `tracks.model`.

    The checkpoint's own name FIRST, because that is what the embedding space
    is and every row already in the library says exactly that -- a track
    embedded here is comparable with one the base rig embedded, which is the
    whole premise. The artefact version is appended so a future re-embed sweep
    can find the rows a given export produced (plan §1: "embedding dim/model
    version is recorded per row").
    """
    models = _models()
    entry = models.model(key or models.DEFAULT_MODEL)
    return f"{entry['hf_model']}@onnx{entry['version']}"


def embedding_dim(key: str = "") -> int:
    models = _models()
    return int(models.model(key or models.DEFAULT_MODEL).get("dim") or 512)


# ---------------------------------------------------------------------------
# the feed
# ---------------------------------------------------------------------------

def feed_base(cfg: Optional[dict[str, Any]] = None,
              site: Optional[dict[str, Any]] = None) -> str:
    """Where this fleet's artefacts are published, or "".

    `music_clap_feed_base` in config.toml wins (a base rig or a dev loop
    pointing at a local directory server), then the cached site manifest's
    `release_feed_base` -- the dashboard's own `DASH_RELEASE_FEED_URL` minus
    `/channel.json`, published on /api/v1/site precisely so no vendor host is
    written down in this repo (CLAUDE.md: no customer's name in code; the same
    rule keeps ours out).

    "" is a complete answer and every caller reads it as "this fleet has no
    feed configured, so this machine cannot fetch the model" -- which is a
    refusal with a fix, not an error.
    """
    override = str((cfg or {}).get("music_clap_feed_base") or "").strip()
    if override:
        return override.rstrip("/")
    try:
        manifest = site if site is not None else site_mod.cached_site()
    except Exception:  # noqa: BLE001 - an unreadable cache is "not configured"
        log.debug("music clap: could not read the cached site manifest", exc_info=True)
        return ""
    base = str((manifest or {}).get("release_feed_base") or "").strip()
    return base.rstrip("/")


def host_allowed(url: str) -> bool:
    """Is `url` on the feed's host, or one it is allowed to redirect to?

    The feed's OWN host is trusted by definition -- it is the one the site
    manifest named -- and the rest of the list is the GitHub Releases redirect
    chain (docs/RELEASE_FEED.md §3.1). fnmatch, never a bare `endswith`:
    "evil-githubusercontent.com" ends with the suffix too.
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        return False
    host = (parts.hostname or "").lower()
    if not host:
        return False
    return any(fnmatch.fnmatch(host, pattern) for pattern in ALLOWED_HOST_PATTERNS)


def planned_urls(cfg: Optional[dict[str, Any]] = None,
                 site: Optional[dict[str, Any]] = None) -> dict[str, str]:
    """filename -> URL for both files. Raises ValueError with no feed base."""
    return _models().urls(feed_base(cfg, site))


def required_bytes(key: str = "") -> int:
    """Free space `ensure()` insists on before it starts. The two files'
    pinned sizes plus `upgrade.MIN_FREE_BYTES_MARGIN`, imported rather than
    re-typed for ytdlp_manager's reason: two numbers that both mean "don't be
    the thing that fills an editor's disk" would drift."""
    models = _models()
    entry = models.model(key or models.DEFAULT_MODEL)
    return int(sum(entry["size_bytes"].values())) + upgrade_mod.MIN_FREE_BYTES_MARGIN


def free_space_refusal(key: str = "", directory: Optional[Path] = None) -> Optional[str]:
    """Why there is not enough room, or None. Editor-facing.

    A disk we cannot measure is NOT a refusal -- sidecar_tools' rule: "I could
    not tell" must never read as "no".
    """
    directory = directory or cache_dir()
    needed = required_bytes(key)
    probe = directory
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        free = shutil.disk_usage(str(probe)).free
    except Exception:  # noqa: BLE001
        log.debug("music clap: free-space check failed at %s; continuing", probe,
                  exc_info=True)
        return None
    if free >= needed:
        return None
    return (f"Not enough disk space for the music indexing model: needs about "
            f"{needed / 1_000_000_000:.1f} GB free at {directory}, has "
            f"{free / 1_000_000_000:.1f} GB. Free some space and try again")


# ---------------------------------------------------------------------------
# what is on disk
# ---------------------------------------------------------------------------

def model_ready(key: str = "") -> bool:
    """Both files present at their pinned SIZE.

    Deliberately not a re-hash: a 280 MB sha256 on every tick would cost
    seconds of disk per minute, and the hash gate that matters already ran on
    the way in (`download_verified` refuses, and deletes, a file whose digest
    is wrong). A truncated file is caught by the size check.
    """
    try:
        models = _models()
        entry = models.model(key or models.DEFAULT_MODEL)
        for path in artefact_paths(key):
            expected = int(entry["size_bytes"].get(path.name) or 0)
            if not path.is_file() or path.stat().st_size != expected:
                return False
        return True
    except Exception:  # noqa: BLE001
        return False


def download_bytes(key: str = "") -> int:
    """How much a first run would fetch. 0 once it is cached."""
    if model_ready(key):
        return 0
    models = _models()
    return int(sum(models.model(key or models.DEFAULT_MODEL)["size_bytes"].values()))


def runtime_available() -> tuple[bool, str]:
    """Is onnxruntime importable in THIS build? -> (ok, refusal).

    A frozen build always has it (it is a hard dependency), so a False here is
    a dev checkout or a broken install, and the message says which.
    """
    try:
        import onnxruntime  # noqa: F401,PLC0415
    except Exception as exc:  # noqa: BLE001
        return False, ("this build cannot run the music indexing model "
                       f"(onnxruntime did not load: {exc})")
    return True, ""


def providers() -> list[str]:
    """The execution providers onnxruntime offers here. [] when it is absent.

    Informational only: the CPU provider is always present and is a perfectly
    good answer (~90 ms per 10 s window, measured), so nothing refuses work on
    the strength of this list.
    """
    try:
        import onnxruntime  # noqa: PLC0415

        return [str(p) for p in onnxruntime.get_available_providers()]
    except Exception:  # noqa: BLE001
        return []


def refresh(force: bool = False) -> dict[str, Any]:
    """Re-stat the cache if its answer is stale, and return the fresh
    snapshot. THIS is the function that touches the disk; `status()` never
    does."""
    with _lock:
        fresh = (time.monotonic() - float(_status_cache.get("at") or 0)) < STATUS_TTL_SECONDS
    if fresh and not force:
        return status()
    ready = model_ready()
    runtime_ok, _why = runtime_available()
    names = providers()
    with _lock:
        _status_cache["ready"] = ready
        _status_cache["runtime_ready"] = runtime_ok
        _status_cache["providers"] = names
        _status_cache["at"] = time.monotonic()
    return status()


def status() -> dict[str, Any]:
    """The cached snapshot -- ZERO I/O, safe from the tray's menu build, the
    reporter's tick and the loopback's capability route."""
    with _lock:
        return {
            "ready": bool(_status_cache["ready"]),
            "runtime_ready": _status_cache["runtime_ready"],
            "providers": list(_status_cache["providers"]),
            "downloading": (dict(_status_cache["downloading"])
                            if _status_cache["downloading"] else None),
            "last_error": _status_cache["last_error"],
        }


def reset_caches() -> None:
    """Forget the readiness snapshot and drop the loaded session (tests; an
    operator who has just deleted the cache dir)."""
    global _session, _session_key, _extractor
    with _lock:
        _status_cache["at"] = 0.0
        _session = None
        _session_key = ""
        _extractor = None


def _download_rate_and_eta(written: int, total: Optional[int]
                           ) -> tuple[Optional[float], Optional[float]]:
    """The fetcher's aggregate rate and the seconds left at it -- the same
    reading broll_vlm_sidecar takes, because this module fetches through the
    same vendored `download_verified` (which, since 2026-08-18, uses several
    connections; BROLL-ING-4). Never raises."""
    try:
        from .broll_vlm import local_runtime

        rate = float(local_runtime.download_verified.last_rate_bytes_per_s or 0.0)
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


class _Stopped(Exception):
    """The tray is shutting down (or the batch was cancelled) mid-download.
    Raised out of the progress callback, which is the only code of ours that
    runs during a 280 MB transfer; the `.part` file stays on disk and the next
    attempt resumes it with an HTTP Range request."""


def ensure(cfg: Optional[dict[str, Any]] = None,
           progress_cb: Optional[Callable[[str, int, Optional[int]], None]] = None,
           stop_event: Optional[threading.Event] = None,
           site: Optional[dict[str, Any]] = None,
           key: str = "") -> tuple[bool, str]:
    """Make the ONNX + params present and verified. -> (ok, message).

    NEVER raises: this runs on the ingest tick, and an exception here would
    take the orchestrator's thread down with the batch still queued.

    Order, and why:
      1. onnxruntime has to be there at all -- downloading 280 MB for a build
         that cannot execute it is 280 MB of an editor's bandwidth spent on
         nothing;
      2. the catalogue has to be PINNED (a placeholder sha256 is an artefact
         that was never exported, and an unverifiable download is not one this
         will make);
      3. a feed base, then free space, BEFORE a byte is requested;
      4. every URL on the allow-list;
      5. fetch, sha256-verified and resumable.
    """
    runtime_ok, why = runtime_available()
    if not runtime_ok:
        _clear_download(why)
        return False, why

    models = _models()
    if not models.is_pinned(key or models.DEFAULT_MODEL):
        message = ("this build has no verified music indexing model to "
                   "download yet: its checksum is still a placeholder")
        _clear_download(message)
        return False, message

    try:
        urls = planned_urls(cfg, site)
    except ValueError:
        message = ("this fleet has no release feed configured, so the music "
                   "indexing model cannot be downloaded. Set the dashboard's "
                   "release feed URL and the tray will fetch it")
        _clear_download(message)
        return False, message
    bad = [u for u in urls.values() if not host_allowed(u)]
    if bad:
        message = (f"refusing to download the music indexing model: "
                   f"{urlsplit(bad[0]).hostname} is not one of the hosts this "
                   "build is allowed to fetch from")
        log.warning("music clap: %s (urls: %s)", message, sorted(urls.values()))
        _clear_download(message)
        return False, message

    refusal = free_space_refusal(key)
    if refusal:
        _clear_download(refusal)
        return False, refusal

    # The vendored fetcher, not a second one: resumable, sha256-verified, and
    # it DELETES a file whose digest is wrong -- the difference between "retry
    # fixes it" and "every retry fails identically".
    from .broll_vlm import local_runtime

    directory = cache_dir()
    entry = models.model(key or models.DEFAULT_MODEL)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for name, url in urls.items():
            if stop_event is not None and stop_event.is_set():
                raise _Stopped()

            def _progress(written: int, total: Optional[int], _name: str = name) -> None:
                if stop_event is not None and stop_event.is_set():
                    raise _Stopped()
                _note_download(_name, written, total)
                if progress_cb is not None:
                    progress_cb(_name, written, total)

            local_runtime.download_verified(
                url, directory / name,
                sha256=entry["sha256"][name],
                size_bytes=entry["size_bytes"].get(name),
                progress=_progress)
    except _Stopped:
        _clear_download("")
        log.info("music clap: model download stopped; the partial file is kept "
                 "for resume")
        return False, "the download was stopped - it will resume where it left off"
    except local_runtime.LocalRuntimeError as exc:
        message = str(exc)
        if "sha256 mismatch" in message.lower():
            message = ("the music model download's checksum did not match - the "
                       "file was deleted and will be fetched again")
        log.warning("music clap: %s", message)
        _clear_download(message)
        return False, message
    except Exception as exc:  # noqa: BLE001 - see the docstring
        log.warning("music clap: model fetch failed (%s)", exc, exc_info=True)
        message = f"the music indexing model could not be downloaded: {exc}"
        _clear_download(message)
        return False, message

    _clear_download("")
    refresh(force=True)
    return True, "the music indexing model is ready"


# ---------------------------------------------------------------------------
# the session
# ---------------------------------------------------------------------------

def _providers_for_session() -> list[str]:
    """Best available execution provider first, CPU always last.

    CUDA/DirectML are used IF the onnxruntime package in this build happens to
    offer them and never required: the pip `onnxruntime` wheel this companion
    pins is CPU-only, and a machine that has the GPU package installed (a base
    rig that also runs the indexer) should not be held back to CPU for it.
    """
    available = providers()
    preferred = [p for p in ("CUDAExecutionProvider", "DmlExecutionProvider")
                 if p in available]
    return [*preferred, "CPUExecutionProvider"]


def session(key: str = ""):
    """A loaded InferenceSession for the artefact, cached for the process.

    Raises SidecarError when it cannot be loaded, because its caller (the
    ingest orchestrator) has a per-track failure path already.
    """
    global _session, _session_key
    onnx_path, params_path = artefact_paths(key)
    want = str(onnx_path)
    with _lock:
        if _session is not None and _session_key == want:
            return _session

    runtime_ok, why = runtime_available()
    if not runtime_ok:
        raise ModelUnavailable(why)
    if not model_ready(key):
        raise ModelUnavailable("the music indexing model is not downloaded on "
                               "this computer yet")
    if not params_path.is_file():
        raise ModelUnavailable("the music indexing model's settings file is "
                               "missing - it will be fetched again")
    import onnxruntime  # noqa: PLC0415

    options = onnxruntime.SessionOptions()
    # An editor is USING this machine. onnxruntime otherwise takes every core
    # for a job that has all evening, and the symptom is a laggy timeline
    # rather than a slow ingest -- which is the trade the idle gate already
    # made once and must not be undone here.
    options.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
    options.log_severity_level = 3
    try:
        loaded = onnxruntime.InferenceSession(
            want, sess_options=options, providers=_providers_for_session())
    except Exception as exc:  # noqa: BLE001
        raise ModelUnavailable("the music indexing model could not be loaded "
                               f"on this computer ({exc})") from exc
    with _lock:
        _session = loaded
        _session_key = want
    log.info("music clap: loaded %s on %s", onnx_path.name,
             ", ".join(loaded.get_providers()) or "an unknown provider")
    return loaded


def stop_server() -> None:
    """Drop the loaded session and its ~300 MB of weights.

    Named for the b-roll sidecar's function of the same job so the shared
    orchestrator can call it on either kind: there is no server here, but "the
    editor came back, give the machine's memory back" is the same event.
    """
    global _session, _session_key
    with _lock:
        had = _session is not None
        _session = None
        _session_key = ""
    if had:
        log.info("music clap: released the model session")


def extractor(key: str = ""):
    """The mel front end for this artefact's params, built once."""
    global _extractor
    _onnx, params_path = artefact_paths(key)
    with _lock:
        if _extractor is not None and getattr(_extractor, "_ccsync_key", "") == str(params_path):
            return _extractor
    mel = _mel()
    try:
        built = mel.MelExtractor.from_params_file(params_path)
    except mel.ParamsError as exc:
        raise ModelUnavailable("the music indexing model's settings could not "
                               f"be read ({exc})") from exc
    built._ccsync_key = str(params_path)
    with _lock:
        _extractor = built
    return built


# ---------------------------------------------------------------------------
# audio
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout: int, capture_stdout: bool = True,
         child_sink: Optional[Any] = None):
    """One child, windowless, with its output on pipes. Never inherits a
    console: the tray is a windowed build and a visible ffmpeg window on an
    editor's desktop is a support call.

    `child_sink` is MEDIA-2 (resilience sweep 2026-08-28): the ingest
    orchestrator's stop()/cancel() promised to kill this child and could not,
    because subprocess.run never hands one out. An editor who quits the tray
    four minutes into a 90-minute mix left a decode running past tray exit,
    holding a handle on the staged file. Popen, published, taken back on the
    way out; a sink that raises never fails the run.
    """
    if child_sink is None:
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=_win_creationflags(),
        )
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=_win_creationflags(),
    )
    _publish_child(child_sink, proc)
    try:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.communicate(timeout=10)
            except Exception:  # noqa: BLE001 - already failing
                pass
            raise
    finally:
        _publish_child(child_sink, None)
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def _sink_kwargs(child_sink: Optional[Any]) -> dict:
    """`{"child_sink": ...}` only when there is one.

    `_run` is a monkeypatch seam in this suite and its doubles take the
    arguments the call site passed before MEDIA-2; an unconditional keyword
    would break every one of them for a value they would ignore."""
    return {"child_sink": child_sink} if child_sink is not None else {}


def _publish_child(child_sink: Optional[Any], proc: Optional[Any]) -> None:
    """Hand the live child to the orchestrator (or take it back)."""
    if child_sink is None:
        return
    try:
        child_sink(proc)
    except Exception:  # noqa: BLE001
        log.debug("music clap: could not publish the ffmpeg child", exc_info=True)


def probe(ffmpeg_path: str, path: Any) -> dict[str, Any]:
    """ffprobe -> {duration, samplerate, channels, codec}.

    `music_index.audio.probe`'s answer, field for field, because it is what
    the fleet route stores on the item row. `duration` 0 means "not audio":
    a renamed .zip and a video-only container both land there.
    """
    import json  # noqa: PLC0415 - only the ingest path parses ffprobe JSON

    from . import ffmpeg_tools

    ffprobe = ffmpeg_tools.ffprobe_for(ffmpeg_path)
    empty = {"duration": 0.0, "samplerate": 0, "channels": 0, "codec": ""}
    try:
        out = _run([ffprobe, "-v", "quiet", "-print_format", "json",
                    "-show_format", "-show_streams", str(path)],
                   timeout=PROBE_TIMEOUT_SECONDS)
        parsed = json.loads((out.stdout or b"").decode("utf-8", errors="replace"))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        log.debug("music clap: could not probe %s (%s)", path, exc)
        return empty
    fmt = parsed.get("format") or {}
    stream = next((s for s in parsed.get("streams") or []
                   if s.get("codec_type") == "audio"), None)
    if stream is None:
        return empty
    try:
        duration = float(fmt.get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "duration": duration,
        "samplerate": int(stream.get("sample_rate", 0) or 0),
        "channels": int(stream.get("channels", 0) or 0),
        "codec": str(stream.get("codec_name", "") or ""),
    }


def transcode_to_mp3(ffmpeg_path: str, src: Any, dest_dir: Any,
                     child_sink: Optional[Any] = None) -> Path:
    """`.ogg` -> 320k mp3, the container's command exactly.

    Raises RuntimeError if ffmpeg produced nothing usable, INCLUDING the case
    where it exited 0 and wrote a file with no audio: a transcode that dropped
    the audio is worse than no transcode, because it uploads happily.
    """
    from . import ffmpeg_tools

    src = Path(src)
    dest = Path(dest_dir) / (src.stem + ".mp3")
    binary = ffmpeg_tools._resolve_binary(ffmpeg_path) or ffmpeg_path
    try:
        proc = _run([binary, "-v", "error", "-y", "-i", str(src),
                     "-c:a", "libmp3lame", "-b:a", MP3_BITRATE,
                     "-map_metadata", "0", str(dest)],
                    timeout=TRANSCODE_TIMEOUT_SECONDS, capture_stdout=False,
                    **_sink_kwargs(child_sink))
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"transcode failed: {exc}") from exc
    if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError("transcode failed: "
                           + (err.splitlines()[-1] if err else "ffmpeg produced nothing"))
    if probe(ffmpeg_path, dest).get("duration", 0) <= 0:
        raise RuntimeError("transcode produced a file with no audio")
    return dest


def decode(ffmpeg_path: str, path: Any, sample_rate: int = 48000,
           max_seconds: Optional[int] = MAX_DECODE_SECONDS,
           child_sink: Optional[Any] = None):
    """Whole file -> mono float32 numpy array at `sample_rate`.

    Through a PIPE, never a temp WAV (module docstring). `music_index.audio.
    decode`'s command and its NaN guard: a damaged file that decodes to Inf
    poisons the embedding rather than failing, and a poisoned embedding is a
    plausible vector nothing downstream can detect.
    """
    import numpy as np  # noqa: PLC0415

    from . import ffmpeg_tools

    binary = ffmpeg_tools._resolve_binary(ffmpeg_path) or ffmpeg_path
    cmd = [binary, "-v", "quiet", "-i", str(path)]
    if max_seconds:
        cmd += ["-t", str(int(max_seconds))]
    cmd += ["-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1",
            "-ar", str(int(sample_rate)), "-"]
    try:
        out = _run(cmd, timeout=DECODE_TIMEOUT_SECONDS,
                   **_sink_kwargs(child_sink)).stdout or b""
    except (OSError, subprocess.SubprocessError) as exc:
        raise SidecarError(f"this file could not be decoded ({exc})") from exc
    samples = np.frombuffer(out, dtype=np.float32)
    return np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0).copy()


def peaks(samples, n: int = PEAK_BUCKETS) -> bytes:
    """Waveform overview as `n` uint8 values.

    PORTED, not imported: `music_index.audio.peaks` reaches
    `music_index.config` and through it the whole indexer. Peak (not RMS) per
    bucket so transients stay visible at overview scale, normalised to the
    track's own maximum so a quiet ambient bed draws a shape rather than a
    flat line. `tests/test_music_clap_sidecar.py` pins it against the
    indexer's own function value-for-value.
    """
    import numpy as np  # noqa: PLC0415

    if samples is None or samples.size == 0:
        return b""
    a = np.abs(samples)
    if a.size < n:
        a = np.pad(a, (0, n - a.size))
    per = a.size // n
    a = a[:per * n].reshape(n, per).max(axis=1)
    top = float(a.max())
    if top <= 0:
        return bytes(n)
    return (np.clip(a / top, 0, 1) * 255).astype(np.uint8).tobytes()


def windows(samples, sample_rate: int = 48000, window_sec: float = 10.0,
            max_windows: int = 12, trim_fraction: float = 0.02) -> list:
    """Evenly spaced analysis windows across the track -> [(chunk, t0, t1)].

    PORTED from `music_index.audio.windows` for peaks' reason, and pinned
    against it the same way. The numbers are the exporter's params JSON
    (`embedding.window_seconds` / `max_windows` / `window_trim_fraction`), so
    the artefact says how it was verified rather than this file remembering.

    The 2% trim at each end keeps fade-ins, count-ins and trailing silence out
    of the mean: a near-empty window drags a whole track toward "quiet".
    """
    import numpy as np  # noqa: PLC0415

    n = samples.size
    w = int(window_sec * sample_rate)
    if n == 0:
        return []
    if n <= w:
        padded = np.zeros(w, dtype=np.float32)
        padded[:n] = samples
        return [(padded, 0.0, n / sample_rate)]

    margin = int(n * trim_fraction)
    lo, hi = margin, n - margin - w
    if hi <= lo:
        lo, hi = 0, n - w

    count = int(min(max_windows, max(1, (hi - lo) // w + 1)))
    starts = (np.linspace(lo, hi, count).astype(int) if count > 1
              else np.array([(lo + hi) // 2], dtype=int))

    out = []
    for s in starts:
        chunk = samples[s:s + w]
        if chunk.size < w:                       # numerical edge case
            padded = np.zeros(w, dtype=np.float32)
            padded[:chunk.size] = chunk
            chunk = padded
        out.append((chunk, s / sample_rate, (s + w) / sample_rate))
    return out


def embed_windows(chunks, key: str = ""):
    """(W, D) unit vectors for W analysis windows. One forward pass.

    The graph's own output is already L2-normalised (the exporter baked
    `get_audio_features`' normalise into it), so nothing here re-normalises a
    window -- only the pooled track vector is normalised again, which is the
    `mean_then_l2` the params JSON records.
    """
    import numpy as np  # noqa: PLC0415

    mel = extractor(key)
    graph = session(key)
    feats = mel.input_features(chunks)
    if feats.shape[0] == 0:
        return np.zeros((0, embedding_dim(key)), dtype=np.float32)
    inputs = {}
    for spec in graph.get_inputs():
        if spec.name == "is_longer":
            inputs[spec.name] = mel.is_longer(feats.shape[0])
        else:
            inputs[spec.name] = feats
    out = graph.run(None, inputs)[0]
    return np.asarray(out, dtype=np.float32)


def embed_file(path: Any, ffmpeg_path: str = "ffmpeg", key: str = "",
               stop_event: Optional[threading.Event] = None,
               child_sink: Optional[Any] = None) -> dict[str, Any]:
    """One audio file -> everything the fleet `result` route wants.

    {embedding: [float]*dim, dim, duration, n_windows, peaks: bytes,
     windows: [{idx, t0, t1, vector}], samples}

    `duration` comes from the DECODED SAMPLE COUNT, never from ffprobe, and
    that is not a detail: ffprobe derives a raw-ADTS .aac duration from
    bitrate x filesize and it is wrong in both directions (measured 0.89x and
    2.14x on real library files). The re-encode duplicate defence matches on
    normalised name plus duration within 2 s, so a bogus duration lets a
    re-encode of a track already held sail straight past the one check that
    can see it (`index_music.analyse_one`'s note, same reasoning here).

    Raises SidecarError for anything that means "this file cannot be indexed
    on this machine"; the caller fails the item and moves on.
    """
    import numpy as np  # noqa: PLC0415

    params = extractor(key).p
    sample_rate = int(getattr(params, "sample_rate", 48000))
    embedding_params = (getattr(params, "raw", {}) or {}).get("embedding") or {}
    window_sec = float(embedding_params.get("window_seconds") or 10.0)
    max_windows = int(embedding_params.get("max_windows") or 12)
    trim = float(embedding_params.get("window_trim_fraction") or 0.02)

    samples = decode(ffmpeg_path, path, sample_rate, child_sink=child_sink)
    if samples.size == 0:
        raise SidecarError("this file has no audio this computer could decode")
    if stop_event is not None and stop_event.is_set():
        raise SidecarError("stopped")

    chunks = windows(samples, sample_rate, window_sec, max_windows, trim)
    if not chunks:
        raise SidecarError("this file is too short to analyse")

    vectors = embed_windows([c[0] for c in chunks], key)
    if vectors.shape[0] != len(chunks):
        raise SidecarError("the music model returned the wrong number of "
                           "vectors for this file")
    track = vectors.mean(axis=0)
    norm = float(np.linalg.norm(track))
    if not np.isfinite(norm) or norm <= 0:
        raise SidecarError("the music model produced an unusable vector for "
                           "this file")
    track = track / norm
    return {
        "embedding": np.asarray(track, dtype=np.float32),
        "dim": int(track.size),
        "duration": float(samples.size) / float(sample_rate),
        "n_windows": len(chunks),
        "peaks": peaks(samples),
        "windows": [{"idx": i, "t0": float(c[1]), "t1": float(c[2]),
                     "vector": np.asarray(vectors[i], dtype=np.float32)}
                    for i, c in enumerate(chunks)],
        "model": model_id(key),
    }


def content_hash(path: Any) -> str:
    """blake2b-16 over the whole file -- `musicweb.db.content_hash`'s digest.

    The container compares this against `tracks.file_hash` and the base-rig
    queue, so the digest, its size and its hex spelling are a wire contract,
    not an implementation choice. Read in 1 MiB blocks: a 500 MB wav must not
    be pulled into the tray's heap to be hashed.
    """
    import hashlib  # noqa: PLC0415

    digest = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def capabilities(cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """What `GET /music/ingest/capabilities` publishes about the model.

    ZERO I/O: the cached snapshot plus the vendored catalogue's pinned sizes,
    for the b-roll capability route's reason -- the page asks this before it
    renders the drop zone.
    """
    # refresh(), not status(): the snapshot starts empty at boot and only a
    # download filled it, so a machine that already HAD the model answered
    # "cached: False" for a whole session -- the panel asked to download
    # 280 MB again, and the ingest tick sat at "no-model" (owner, 2026-08-18).
    # refresh() is a few stat() calls behind a TTL, cheap enough for the
    # capability route; status() stays the zero-I/O read for the tray.
    snapshot = refresh()
    cached = bool(snapshot.get("ready"))
    try:
        pending = 0 if cached else int(
            sum(_models().model()["size_bytes"].values()))
    except Exception:  # noqa: BLE001
        pending = 0
    return {
        "cached": cached,
        "download_bytes": pending,
        "version": artefact_version(),
        "runtime": snapshot.get("runtime_ready"),
        "providers": snapshot.get("providers") or [],
        "feed": bool(feed_base(cfg)),
        "dim": embedding_dim(),
    }


def refusal(cfg: Optional[dict[str, Any]] = None) -> str:
    """Why this machine cannot embed music, in the editor's words, or "".

    The one sentence the tray balloon, the tray line and the page all show, so
    the three cannot disagree (b-roll's `fits()` contract, minus the GPU).
    """
    ok, why = runtime_available()
    if not ok:
        return why
    if not _models().is_pinned():
        return ("this build has no verified music indexing model yet: its "
                "checksum is still a placeholder")
    if not feed_base(cfg):
        return ("this fleet has no release feed configured, so the music "
                "indexing model cannot be downloaded")
    return ""


__all__ = [
    "SidecarError", "ModelUnavailable", "cache_dir", "artefact_paths", "artefact_version",
    "model_id", "embedding_dim", "feed_base", "host_allowed", "planned_urls",
    "required_bytes", "free_space_refusal", "model_ready", "download_bytes",
    "runtime_available", "providers", "refresh", "status", "reset_caches",
    "ensure", "session", "stop_server", "extractor", "probe",
    "transcode_to_mp3", "decode", "peaks", "windows", "embed_windows",
    "embed_file", "content_hash", "capabilities", "refusal",
    "MAX_DECODE_SECONDS", "MP3_BITRATE", "PEAK_BUCKETS",
]