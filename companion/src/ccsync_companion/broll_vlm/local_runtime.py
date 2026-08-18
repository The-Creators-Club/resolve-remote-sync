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
import http.client
import inspect
import io
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from . import local_models
from .local_models import ModelFile, ModelTier, RuntimeAsset, RuntimeBuild

logger = logging.getLogger(__name__)

CHUNK = 1024 * 1024  # 1 MiB

# --- parallel download tuning (2026-08-18, BROLL-ING-4) -------------------
# Measured on the base rig: ONE long-lived HTTPS connection to Hugging Face
# crawled at ~2 MB/s for thirty minutes while FRESH connections from the same
# machine at the same moment got 13 MB/s single-stream and ~45 MB/s over four
# parallel range requests. py-spy had our thread parked in `ssl.read`, so the
# slow party was the CDN edge we were stuck to, not us. Hence both halves of
# the fix: several connections at once, and a stall rule that DROPS an edge
# that has gone quiet rather than waiting on it forever.
DEFAULT_STREAMS = 6
MAX_STREAMS = 16
STREAMS_ENV = "CCSYNC_DOWNLOAD_STREAMS"
# Below this a slice costs more connections than it saves seconds, so a small
# file stays a single stream however many streams were asked for.
MIN_SLICE_BYTES = 8 * 1024 * 1024
# A stream that moves less than STALL_MIN_BYTES in STALL_WINDOW_SECONDS is
# treated as dead: closed and reopened on its remaining range, which lands on
# a different edge. Also the socket timeout, so a stream that sends NOTHING is
# caught by the same rule instead of blocking in `ssl.read` until the heat
# death of the universe.
STALL_WINDOW_SECONDS = 20.0
STALL_MIN_BYTES = 256 * 1024
MAX_STALLS_PER_SLICE = 5
# Attempts per slice before the whole download fails (which KEEPS the partial
# and its sidecar, so the next run resumes rather than restarts).
SLICE_ATTEMPTS = 3
PROGRESS_INTERVAL_SECONDS = 0.25
RATE_WINDOW_SECONDS = 5.0
SIDECAR_VERSION = 1


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


class _Aborted(Exception):
    """Internal: another slice failed, or the caller's progress callback
    raised, so this worker should put its tools down and leave the partial
    exactly where it is."""


@dataclass
class _Slice:
    """One contiguous byte range of the file, and how much of it is on disk.

    `end` is INCLUSIVE (that is what an HTTP Range header means) and is None
    only for the single-stream case against a server that never told us how
    big the body is: there the body's EOF is the end.
    """

    index: int
    start: int
    end: int | None = None
    done: int = 0
    # False once we know this connection cannot be resumed (the server ignored
    # Range and sent 200): a retry has to start the whole body again.
    resumable: bool = True

    @property
    def length(self) -> int | None:
        return None if self.end is None else self.end - self.start + 1

    @property
    def complete(self) -> bool:
        return self.end is not None and self.start + self.done > self.end


def _stream_count() -> int:
    """How many connections to split a ranged download across.

    `CCSYNC_DOWNLOAD_STREAMS` clamps to 1..16; 1 means today's single stream.
    A junk value is a warning and the default, never a crash in the middle of
    a 4 GB fetch.
    """
    raw = (os.environ.get(STREAMS_ENV) or "").strip()
    if not raw:
        return DEFAULT_STREAMS
    try:
        want = int(raw)
    except ValueError:
        logger.warning("local_runtime: %s=%r is not a number; using %d streams",
                       STREAMS_ENV, raw, DEFAULT_STREAMS)
        return DEFAULT_STREAMS
    return max(1, min(MAX_STREAMS, want))


def _opener_takes_timeout(opener: Callable[..., Any]) -> bool:
    """Does this opener accept `timeout=`? `urlopen` does; the test seams that
    stand in for it are usually a bare `def opener(req)`, and passing a keyword
    they do not take would turn every download into a TypeError."""
    try:
        params = inspect.signature(opener).parameters
    except (TypeError, ValueError):  # a builtin or C callable we cannot read
        return False
    if "timeout" in params:
        return True
    return any(p.kind is p.VAR_KEYWORD for p in params.values())


def _header(resp: Any, name: str) -> str:
    """A response header from whatever shape the opener returned. Test doubles
    have no `.headers`, and a missing header is never an error here."""
    getter = getattr(resp, "getheader", None)
    if callable(getter):
        try:
            return str(getter(name) or "")
        except Exception:  # noqa: BLE001 - a header read must not fail a fetch
            return ""
    headers = getattr(resp, "headers", None)
    if headers is None:
        return ""
    try:
        return str(headers.get(name) or "")
    except Exception:  # noqa: BLE001
        return ""


_CONTENT_RANGE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+)", re.I)


def _total_from(resp: Any, status: int) -> int | None:
    """The file's full size as the response states it: `Content-Range`'s
    denominator on a 206, else `Content-Length` on a 200 (which is the whole
    body only because we only ask when we are starting from zero)."""
    match = _CONTENT_RANGE.search(_header(resp, "Content-Range"))
    if match:
        try:
            return int(match.group(3))
        except ValueError:
            return None
    length = _header(resp, "Content-Length")
    if status == 200 and length.isdigit():
        return int(length)
    return None


def _final_url(resp: Any, fallback: str) -> str:
    """Where the response actually came from: Hugging Face 302s to a signed
    CDN URL, and pointing the other workers straight at it saves each of them
    a redirect. Retries fall back to the original URL, because a signed CDN
    URL can expire under a long download."""
    getter = getattr(resp, "geturl", None)
    if callable(getter):
        try:
            return str(getter() or fallback)
        except Exception:  # noqa: BLE001
            return fallback
    return fallback


def _split(total: int, streams: int) -> list[_Slice]:
    """Contiguous, equal-sized slices covering [0, total), never smaller than
    MIN_SLICE_BYTES and never more than `streams` of them."""
    count = max(1, min(streams, -(-total // MIN_SLICE_BYTES)))
    size = -(-total // count)
    out: list[_Slice] = []
    for i in range(count):
        start = i * size
        if start >= total:
            break
        out.append(_Slice(index=len(out), start=start, end=min(start + size, total) - 1))
    return out


def _sidecar_path(tmp: Path) -> Path:
    return tmp.with_name(tmp.name + ".json")


def _preallocate(tmp: Path, total: int) -> None:
    """Make `.part` exactly `total` bytes so every worker can seek into its own
    offset. Cheap on NTFS/APFS (sparse) and it is what makes the sidecar's
    offsets mean anything after a kill."""
    with open(tmp, "r+b" if tmp.is_file() else "wb") as f:
        f.truncate(total)


class _Download:
    """The shared state of one download: byte counter, progress reporting,
    rate, the abort flag and the resume sidecar.

    The progress callback is only ever called from the thread that called
    `download_verified` -- the workers just add bytes. That is deliberate: the
    companion raises out of its progress callback to stop a fetch (see
    broll_vlm_sidecar._Stopped), and an exception crossing a worker thread
    boundary would be swallowed instead of stopping anything.
    """

    def __init__(self, url: str, tmp: Path, *, sha256: str,
                 size_bytes: int | None,
                 progress: Callable[[int, int | None], None] | None,
                 rate_cb: Callable[[float], None] | None,
                 opener: Callable[..., Any]):
        self.url = url
        self.fetch_url = url
        self.tmp = tmp
        self.sidecar = _sidecar_path(tmp)
        self.sha256 = sha256
        self.size_bytes = size_bytes
        self.total: int | None = size_bytes
        self.slices: list[_Slice] = []
        self._progress = progress
        self._rate_cb = rate_cb
        self._opener = opener
        self._takes_timeout = _opener_takes_timeout(opener)
        self._lock = threading.Lock()
        self.abort = threading.Event()
        self.written = 0
        self.error: BaseException | None = None
        self.inline = False
        # Seeded so the FIRST report already has a rate: a small artefact can
        # be down before the second tick, and "0 MB/s" on a finished download
        # is the kind of number that makes an editor doubt the whole window.
        self._samples: deque[tuple[float, int]] = deque([(time.monotonic(), 0)])
        self._last_report = 0.0
        self._last_written = -1
        self._last_saved = 0.0
        self.rate = 0.0

    # -- connections -------------------------------------------------------
    def open(self, req: Request) -> Any:
        if self._takes_timeout:
            return self._opener(req, timeout=STALL_WINDOW_SECONDS)
        return self._opener(req)

    # -- bytes -------------------------------------------------------------
    def add(self, count: int) -> None:
        with self._lock:
            self.written += count
        if self.inline:
            self.report()

    def rewind(self, sl: _Slice) -> None:
        """A slice that has to start over (a server that ignored Range) gives
        back the bytes it had counted, so the percentage never goes backwards
        by more than it really did."""
        with self._lock:
            self.written -= sl.done
        sl.done = 0

    def report(self, force: bool = False) -> None:
        """Call the caller's progress callback, at most ~4x a second.

        Raises whatever the callback raises -- that is the cancel path.
        """
        now = time.monotonic()
        if not force and (now - self._last_report) < PROGRESS_INTERVAL_SECONDS:
            return
        with self._lock:
            written = self.written
        # The final forced tick is skipped when nothing moved since the last
        # one: callers count progress calls (and print them), and a duplicate
        # 100% line is a bug report. A PERIODIC tick still fires with no new
        # bytes -- that is what lets a caller cancel out of its own callback
        # while a stream is stalled.
        if force and written == self._last_written:
            return
        self._last_report = now
        self._last_written = written
        self._samples.append((now, written))
        while len(self._samples) > 2 and self._samples[0][0] < now - RATE_WINDOW_SECONDS:
            self._samples.popleft()
        if len(self._samples) >= 2:
            (t0, b0), (t1, b1) = self._samples[0], self._samples[-1]
            if t1 > t0 and b1 >= b0:
                self.rate = (b1 - b0) / (t1 - t0)
        download_verified.last_rate_bytes_per_s = self.rate
        if self._rate_cb is not None:
            self._rate_cb(self.rate)
        if self._progress is not None:
            self._progress(written, self.size_bytes if self.size_bytes is not None else self.total)

    # -- failure -----------------------------------------------------------
    def fail(self, exc: BaseException) -> None:
        with self._lock:
            if self.error is None:
                self.error = exc
        self.abort.set()

    # -- resume sidecar ----------------------------------------------------
    def save_sidecar(self, force: bool = True) -> None:
        """Write `.part.json`: which slices exist and how far each got.

        Only for a MULTI-slice download. A single-stream `.part` deliberately
        has no sidecar, which is exactly how a partial written by an older
        build (or by N=1) is recognised on the next run.
        """
        if len(self.slices) < 2 or self.total is None:
            return
        now = time.monotonic()
        if not force and (now - self._last_saved) < 2.0:
            return
        self._last_saved = now
        payload = {
            "version": SIDECAR_VERSION,
            "url": self.url,
            "sha256": self.sha256,
            "total": int(self.total),
            "slices": [{"start": s.start, "end": s.end, "done": s.done} for s in self.slices],
        }
        tmp_json = self.sidecar.with_name(self.sidecar.name + ".tmp")
        try:
            tmp_json.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp_json, self.sidecar)
        except OSError as exc:  # a sidecar we cannot write costs a resume, not the download
            logger.warning("local_runtime: could not write %s (%s)", self.sidecar, exc)


def _load_sidecar(path: Path, tmp: Path, *, url: str, sha256: str
                  ) -> tuple[int, list[_Slice]] | None:
    """The slice plan a killed run left behind, or None if there is not a
    coherent one. Every field is re-checked (same URL, same digest, same total,
    contiguous cover, nothing past the end): a sidecar that does not describe
    the `.part` next to it must start the download over, never write into the
    wrong offsets of somebody else's file."""
    if not path.is_file() or not tmp.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if int(data.get("version") or 0) != SIDECAR_VERSION:
            return None
        if data.get("url") != url or data.get("sha256") != sha256:
            return None
        total = int(data.get("total") or 0)
        if total <= 0 or tmp.stat().st_size != total:
            return None
        slices = []
        for raw in data.get("slices") or []:
            start, end, done = int(raw["start"]), int(raw["end"]), int(raw.get("done") or 0)
            if start < 0 or end < start or end >= total or not 0 <= done <= end - start + 1:
                return None
            slices.append(_Slice(index=len(slices), start=start, end=end, done=done))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
    if len(slices) < 2 or slices[0].start != 0 or slices[-1].end != total - 1:
        return None
    for before, after in zip(slices, slices[1:]):
        if after.start != before.end + 1:
            return None
    return total, slices


def _pump(resp: Any, fh: Any, sl: _Slice, dl: _Download) -> bool:
    """Copy this connection's body into `fh`. True if it STALLED (reconnect),
    False if the body ended or the slice is full.

    The write is flushed every chunk so the sidecar's byte counts stay true to
    what is on disk: a resume that trusts counts the OS never saw would fail
    the final sha256 and throw away gigabytes.
    """
    window_start = time.monotonic()
    window_bytes = 0
    while True:
        if dl.abort.is_set():
            raise _Aborted()
        try:
            chunk = resp.read(CHUNK)
        except TimeoutError:
            logger.info("local_runtime: slice %d sent nothing for %.0fs; reconnecting",
                        sl.index, STALL_WINDOW_SECONDS)
            return True
        if not chunk:
            return False
        if sl.end is not None:
            allowed = sl.end - (sl.start + sl.done) + 1
            if allowed <= 0:
                return False
            if len(chunk) > allowed:  # a server that ignored our range's end
                chunk = chunk[:allowed]
        fh.write(chunk)
        fh.flush()
        sl.done += len(chunk)
        dl.add(len(chunk))
        window_bytes += len(chunk)
        if sl.complete:
            return False
        now = time.monotonic()
        elapsed = now - window_start
        if elapsed >= STALL_WINDOW_SECONDS:
            if window_bytes < STALL_MIN_BYTES:
                logger.info(
                    "local_runtime: slice %d moved %.0f KiB in %.0fs (%.2f MB/s); "
                    "dropping this connection and reopening the range",
                    sl.index, window_bytes / 1024, elapsed, window_bytes / elapsed / 1e6)
                return True
            window_start, window_bytes = now, 0


def _fetch_slice(dl: _Download, sl: _Slice, url: str, preopened: Any = None) -> None:
    """One slice, across as many connections as its stalls need."""
    stalls = 0
    resp = preopened
    with open(dl.tmp, "r+b") as fh:
        while True:
            if dl.abort.is_set():
                raise _Aborted()
            if sl.complete:
                return
            if resp is None:
                headers = {}
                if sl.resumable:
                    tail = "" if sl.end is None else str(sl.end)
                    headers["Range"] = f"bytes={sl.start + sl.done}-{tail}"
                resp = dl.open(Request(url, headers=headers))
                status = getattr(resp, "status", 200) or 200
                if sl.resumable and status != 206:
                    # It honoured Range a moment ago and does not now: writing
                    # a whole body into a slice's offset would corrupt the file.
                    raise LocalRuntimeError(
                        f"{url} stopped honouring Range mid-download (HTTP {status})")
            try:
                fh.seek(sl.start + sl.done)
                stalled = _pump(resp, fh, sl, dl)
            finally:
                try:
                    resp.close()
                except Exception:  # noqa: BLE001
                    pass
                resp = None
            if not stalled:
                if sl.end is not None and not sl.complete:
                    raise http.client.IncompleteRead(b"", (sl.length or 0) - sl.done)
                return
            stalls += 1
            if stalls > MAX_STALLS_PER_SLICE:
                raise LocalRuntimeError(
                    f"slice {sl.index} of {url} stalled {stalls} times in a row")
            if not sl.resumable:  # cannot continue it: start the body again
                dl.rewind(sl)


# Errors worth another connection. A progress callback's own exception is NOT
# in here on purpose: that is the companion cancelling, and retrying it three
# times with backoff would ignore an editor who asked us to stop.
_RETRYABLE = (OSError, http.client.HTTPException, LocalRuntimeError)


def _slice_worker(dl: _Download, sl: _Slice, preopened: Any = None) -> None:
    delay = 0.5
    for attempt in range(1, SLICE_ATTEMPTS + 1):
        # Attempt 1 uses the redirect-resolved URL; later ones go back to the
        # original, because an expired signed CDN URL is exactly the kind of
        # thing that makes attempt 1 fail.
        url = dl.fetch_url if attempt == 1 else dl.url
        try:
            _fetch_slice(dl, sl, url, preopened if attempt == 1 else None)
            return
        except _Aborted:
            return
        except _RETRYABLE as exc:
            if attempt >= SLICE_ATTEMPTS or dl.abort.is_set():
                dl.fail(LocalRuntimeError(f"could not download {dl.url}: {exc}"))
                return
            logger.info("local_runtime: slice %d failed (%s); retrying (%d of %d)",
                        sl.index, exc, attempt + 1, SLICE_ATTEMPTS)
            if not sl.resumable:
                dl.rewind(sl)
            time.sleep(delay)
            delay = min(delay * 2, 4.0)
        except BaseException as exc:  # noqa: BLE001 - the caller's callback said stop
            dl.fail(exc)
            return


def _run_parallel(dl: _Download, preopened: Any = None) -> None:
    """Start a thread per unfinished slice and report progress from HERE.

    `preopened` is the connection the caller already opened to learn the file's
    size; it is handed to the first unfinished slice rather than closed, so a
    fresh parallel download costs exactly N connections and not N+1.
    """
    pending = [sl for sl in dl.slices if not sl.complete]
    threads = [threading.Thread(target=_slice_worker,
                                args=(dl, sl, preopened if i == 0 else None),
                                name=f"ccsync-dl-{sl.index}", daemon=True)
               for i, sl in enumerate(pending)]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.05)
            dl.report()
            dl.save_sidecar(force=False)
    except BaseException:
        # The progress callback said stop (or Ctrl-C). Park the workers, write
        # down where every slice got to, and let the caller see its own
        # exception -- the partial and its sidecar stay for the next run.
        dl.abort.set()
        for t in threads:
            t.join(timeout=30)
        dl.save_sidecar()
        raise
    for t in threads:
        t.join()
    dl.save_sidecar()
    if dl.error is not None:
        raise dl.error
    missing = [s.index for s in dl.slices if not s.complete]
    if missing:
        raise LocalRuntimeError(
            f"could not download {dl.url}: slices {missing} did not finish")


def download_verified(
    url: str,
    dest: Path,
    *,
    sha256: str,
    size_bytes: int | None = None,
    progress: Callable[[int, int | None], None] | None = None,
    opener: Callable[..., Any] = urlopen,
    rate_cb: Callable[[float], None] | None = None,
) -> Path:
    """Download `url` to `dest`, verifying sha256 before returning it.

    Parallel when the server allows it (2026-08-18): if the first GET answers
    206 with a total size, the file is split into up to `CCSYNC_DOWNLOAD_STREAMS`
    (default 6) contiguous slices, each fetched on its own connection into a
    preallocated `.part`, with a `.part.json` sidecar recording how far each
    slice got. A server without Range support, a resume of a `.part` that has
    no sidecar, or `CCSYNC_DOWNLOAD_STREAMS=1` all fall back to one stream,
    which is what this function always did.

    Resumable: a partial `dest` (from a previous run, or a killed download) is
    continued -- per slice when there is a sidecar, from the end of the file
    when there is not. The final file is hashed and, on mismatch, DELETED and
    LocalRuntimeError is raised — a corrupt or tampered-with download must
    never be silently kept around to be reused by the next run.

    `progress(written, total)` keeps its meaning and is called at most ~4x a
    second, always on the CALLING thread. The aggregate rate is published as
    `download_verified.last_rate_bytes_per_s` and, if given, to `rate_cb`.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    sidecar = _sidecar_path(tmp)

    # Already complete and correct: nothing to do. Checked BEFORE opening a
    # connection so an offline re-run of an already-fetched model works.
    if dest.is_file() and dest.stat().st_size > 0:
        if _sha256_file(dest) == sha256:
            return dest
        logger.warning("local_runtime: %s failed re-verification, re-downloading", dest)
        dest.unlink()

    dl = _Download(url, tmp, sha256=sha256, size_bytes=size_bytes,
                   progress=progress, rate_cb=rate_cb, opener=opener)
    resumed = _load_sidecar(sidecar, tmp, url=url, sha256=sha256)
    if resumed is not None:
        dl.total, dl.slices = resumed
        dl.written = sum(s.done for s in dl.slices)
        logger.info("local_runtime: resuming %s across %d slices (%.0f of %.0f MB done)",
                    tmp.name, len(dl.slices), dl.written / 1e6, dl.total / 1e6)
        _run_parallel(dl)
    else:
        if sidecar.is_file():
            # A sidecar that does not describe the `.part` beside it makes that
            # `.part` unreadable: it was written in slices, so it has holes and
            # its LENGTH means nothing. Resuming from its end would assemble a
            # plausible-looking file that fails the digest an hour later, so
            # both go and the download starts over.
            logger.warning("local_runtime: %s does not match %s; starting over",
                           sidecar.name, tmp.name)
            sidecar.unlink(missing_ok=True)
            tmp.unlink(missing_ok=True)
        _download_fresh(dl, streams=_stream_count())

    dl.report(force=True)
    got = _sha256_file(tmp)
    if got != sha256:
        tmp.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)
        raise LocalRuntimeError(
            f"sha256 mismatch downloading {url}: expected {sha256}, got {got}. "
            "Refusing to use this file. Re-run to retry the download."
        )
    tmp.replace(dest)
    sidecar.unlink(missing_ok=True)
    return dest


def _download_fresh(dl: _Download, *, streams: int) -> None:
    """No usable sidecar: open the first connection and decide from its answer
    whether this is a parallel download or a single stream.

    The first GET is the REAL one, not a probe -- a server with no Range
    support is already sending us the file we want, and an extra HEAD would be
    a round trip (and a second entry in every test's call log) for nothing.
    """
    legacy_partial = dl.tmp.stat().st_size if dl.tmp.is_file() else 0
    headers = {}
    if streams > 1 or legacy_partial:
        headers["Range"] = f"bytes={legacy_partial}-"
    try:
        resp = dl.open(Request(dl.url, headers=headers))
    except (HTTPError, URLError, OSError) as e:
        raise LocalRuntimeError(f"could not download {dl.url}: {e}") from e

    status = getattr(resp, "status", 200) or 200
    total = _total_from(resp, status) or dl.size_bytes
    dl.total = total
    dl.fetch_url = _final_url(resp, dl.url)

    if (status == 206 and not legacy_partial and streams > 1
            and total is not None and total >= 2 * MIN_SLICE_BYTES):
        dl.slices = _split(total, streams)
        _preallocate(dl.tmp, total)
        dl.save_sidecar()
        logger.info("local_runtime: fetching %s in %d parallel streams",
                    dl.tmp.name, len(dl.slices))
        # This connection becomes slice 0's: it is already sending byte 0.
        _run_parallel(dl, preopened=resp)
        return

    # One stream: a server that ignored Range (200 restarts from zero rather
    # than silently corrupting the file with a duplicated prefix), a resume of
    # a sidecar-less `.part`, or CCSYNC_DOWNLOAD_STREAMS=1.
    if status != 206:
        legacy_partial = 0
    sl = _Slice(index=0, start=legacy_partial,
                end=(total - 1) if (status == 206 and total is not None) else None,
                resumable=(status == 206))
    with open(dl.tmp, "r+b" if dl.tmp.is_file() else "wb") as f:
        f.truncate(legacy_partial)
    dl.slices = [sl]
    dl.written = legacy_partial
    dl.inline = True  # progress on this thread, exactly as it always was
    _slice_worker(dl, sl, preopened=resp)
    if dl.error is not None:
        raise dl.error


# The aggregate rate of the download in flight (or the last one), for a host
# application that wants "38 MB/s, about 1 min left" in a window it is already
# drawing. A plain attribute because only one model download runs at a time.
download_verified.last_rate_bytes_per_s = 0.0


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
            f"({exe}) - the release asset's internal layout may have changed"
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
    message verbatim: "Best needs 12 GB VRAM; this machine reports 10 GB -
    choose Good or add --force"."""
    if force:
        return
    t = local_models.tier(tier_key)
    gpu = gpu if gpu is not None else probe_gpu()
    if not gpu.present:
        raise LocalRuntimeError(
            f"no GPU detected ({gpu.detail}). The local backend needs an NVIDIA GPU "
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
            f"- {suggestion}"
        )
