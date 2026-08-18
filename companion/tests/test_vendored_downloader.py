"""The vendored downloader as the TRAY runs it: several connections, a stall
that reconnects, a resume, and the rate the progress window quotes.

The transport itself is pinned in the indexer's own suite
(broll/indexer/tests/test_download_parallel.py) and this file is its copy's
half: the module here is imported as `ccsync_companion.broll_vlm.local_runtime`
-- the frozen build's path -- and both sidecars that fetch through it
(b-roll's weights, music's CLAP artefacts) are checked to publish the rate and
the time left that `broll_ingest.progress_model` puts in the headline.

Nothing leaves the machine: the server is stdlib `ThreadingHTTPServer` on
127.0.0.1:0.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ccsync_companion import broll_vlm_sidecar as sc
from ccsync_companion import music_clap_sidecar as music_sc
from ccsync_companion.broll_vlm import local_runtime

PAYLOAD_SIZE = 6 * 1024 * 1024


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def payload() -> bytes:
    return os.urandom(PAYLOAD_SIZE)


class _Server:
    """A one-file HTTP server with Range support, and a `behaviour` hook the
    test uses to make one connection go quiet."""

    def __init__(self, payload: bytes, *, behaviour=None, stall_seconds: float = 2.0):
        self.payload = payload
        self.behaviour = behaviour or (lambda start, end, attempt: "ok")
        self.stall_seconds = stall_seconds
        self.requests: list[tuple[int, int]] = []
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's spelling
                outer._serve(self)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url(self, name: str = "model.bin") -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/{name}"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=10)

    def starts(self) -> list[int]:
        with self._lock:
            return [start for start, _end in self.requests]

    def _serve(self, handler: BaseHTTPRequestHandler) -> None:
        total = len(self.payload)
        match = re.match(r"bytes=(\d+)-(\d*)", handler.headers.get("Range") or "")
        partial = bool(match)
        start = int(match.group(1)) if partial else 0
        end = int(match.group(2)) if (partial and match.group(2)) else total - 1
        with self._lock:
            attempt = sum(1 for s, _e in self.requests if s == start)
            self.requests.append((start, end))
        mode = self.behaviour(start, end, attempt)
        body = self.payload[start:end + 1]
        handler.send_response(206 if partial else 200)
        handler.send_header("Content-Type", "application/octet-stream")
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Content-Length", str(len(body)))
        if partial:
            handler.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        handler.end_headers()
        if mode == "stall":
            handler.wfile.write(body[:len(body) // 8])
            handler.wfile.flush()
            time.sleep(self.stall_seconds)
            handler.close_connection = True
            return
        handler.wfile.write(body)


@pytest.fixture
def small_slices(monkeypatch):
    monkeypatch.setattr(local_runtime, "MIN_SLICE_BYTES", 128 * 1024)


@pytest.fixture(autouse=True)
def _forget_caches():
    sc.reset_caches()
    music_sc.reset_caches()
    yield
    sc.reset_caches()
    music_sc.reset_caches()


# ---------------------------------------------------------------------------
# the transport, through the copy the tray imports
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("streams", ["1", "6"])
def test_the_tray_copy_downloads_byte_identically_at_one_and_six_streams(
        tmp_path, payload, monkeypatch, small_slices, streams):
    monkeypatch.setenv(local_runtime.STREAMS_ENV, streams)
    server = _Server(payload)
    try:
        got = local_runtime.download_verified(
            server.url(), tmp_path / "model.bin", sha256=_sha256(payload),
            size_bytes=len(payload))
    finally:
        server.stop()
    assert got.read_bytes() == payload
    assert len(server.requests) == (1 if streams == "1" else 6)


def test_a_stalled_connection_is_reopened_rather_than_waited_on(
        tmp_path, payload, monkeypatch, small_slices):
    """The measured cause of the 2 MB/s crawl (2026-08-18): one connection
    parked on a slow CDN edge. A new connection is the cure, so the fetcher
    takes one."""
    monkeypatch.setenv(local_runtime.STREAMS_ENV, "3")
    monkeypatch.setattr(local_runtime, "STALL_WINDOW_SECONDS", 0.5)
    monkeypatch.setattr(local_runtime, "STALL_MIN_BYTES", 64)
    size = -(-len(payload) // 3)

    def behaviour(start, end, attempt):
        return "stall" if start == size and attempt == 0 else "ok"

    server = _Server(payload, behaviour=behaviour, stall_seconds=2.0)
    try:
        got = local_runtime.download_verified(server.url(), tmp_path / "model.bin",
                                              sha256=_sha256(payload))
    finally:
        server.stop()
    assert got.read_bytes() == payload
    assert [s for s in server.starts() if size < s <= size * 2], "no reconnect happened"


def test_a_killed_download_resumes_from_its_sidecar(tmp_path, payload, monkeypatch,
                                                    small_slices):
    monkeypatch.setenv(local_runtime.STREAMS_ENV, "2")
    total = len(payload)
    half = total // 2
    part = tmp_path / "model.bin.part"
    with open(part, "wb") as f:
        f.truncate(total)
        f.write(payload[:1000])
    server = _Server(payload)
    try:
        (tmp_path / "model.bin.part.json").write_text(json.dumps({
            "version": local_runtime.SIDECAR_VERSION, "url": server.url(),
            "sha256": _sha256(payload), "total": total,
            "slices": [{"start": 0, "end": half - 1, "done": 1000},
                       {"start": half, "end": total - 1, "done": 0}],
        }), encoding="utf-8")
        got = local_runtime.download_verified(server.url(), tmp_path / "model.bin",
                                              sha256=_sha256(payload))
    finally:
        server.stop()
    assert got.read_bytes() == payload
    assert sorted(server.starts()) == [1000, half]  # only what was missing
    assert not (tmp_path / "model.bin.part.json").exists()


# ---------------------------------------------------------------------------
# what the tray shows while it runs
# ---------------------------------------------------------------------------

def test_the_broll_sidecar_publishes_the_rate_and_the_time_left(monkeypatch):
    """`progress(written, total)` cannot carry a rate -- its signature is the
    indexer's -- so the fetcher publishes one and the sidecar reads it."""
    monkeypatch.setattr(local_runtime.download_verified, "last_rate_bytes_per_s",
                        20e6, raising=False)
    sc._note_download("Qwen3-VL 4B", 40_000_000, 100_000_000)
    downloading = sc.status()["downloading"]
    assert downloading["percent"] == 40
    assert downloading["rate_bytes_per_s"] == 20e6
    assert downloading["eta_seconds"] == pytest.approx(3.0)


def test_no_measured_rate_yet_is_no_rate_at_all_not_a_zero(monkeypatch):
    """A "0 MB/s, about 0 sec left" headline in the first second of a 4 GB
    download is worse than no headline detail at all."""
    monkeypatch.setattr(local_runtime.download_verified, "last_rate_bytes_per_s",
                        0.0, raising=False)
    sc._note_download("Qwen3-VL 4B", 0, 100)
    downloading = sc.status()["downloading"]
    assert downloading["rate_bytes_per_s"] is None
    assert downloading["eta_seconds"] is None


def test_the_music_sidecar_reads_the_same_measurement(monkeypatch):
    monkeypatch.setattr(local_runtime.download_verified, "last_rate_bytes_per_s",
                        5e6, raising=False)
    music_sc._note_download("music-clap-audio-1.onnx", 100_000_000, 280_000_000)
    downloading = music_sc.status()["downloading"]
    assert downloading["rate_bytes_per_s"] == 5e6
    assert downloading["eta_seconds"] == pytest.approx(36.0)


# ---------------------------------------------------------------------------
# the music artefact rides the same fetcher
# ---------------------------------------------------------------------------

def test_the_music_artefact_is_fetched_in_parallel_too(tmp_path, payload, monkeypatch,
                                                       small_slices):
    """music_clap_sidecar deliberately has no downloader of its own -- it calls
    the vendored `download_verified`, so it inherited the parallel fetch on the
    day b-roll did (2026-08-18). This is that claim, end to end."""
    monkeypatch.setenv(local_runtime.STREAMS_ENV, "4")
    server = _Server(payload)
    name = "music-clap-audio-1.onnx"

    class _Models:
        DEFAULT_MODEL = "clap-1"

        @staticmethod
        def is_pinned(key):
            return True

        @staticmethod
        def model(key):
            return {"sha256": {name: _sha256(payload)},
                    "size_bytes": {name: len(payload)}}

    monkeypatch.setattr(music_sc, "runtime_available", lambda: (True, ""))
    monkeypatch.setattr(music_sc, "_models", lambda: _Models)
    monkeypatch.setattr(music_sc, "planned_urls", lambda *a, **k: {name: server.url(name)})
    monkeypatch.setattr(music_sc, "host_allowed", lambda url: True)
    monkeypatch.setattr(music_sc, "free_space_refusal", lambda *a, **k: None)
    monkeypatch.setattr(music_sc, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(music_sc, "refresh", lambda force=False: {})

    seen: list[dict] = []
    try:
        ok, message = music_sc.ensure(
            {}, progress_cb=lambda *a: seen.append(music_sc.status()["downloading"]))
    finally:
        server.stop()

    assert ok is True, message
    assert (tmp_path / name).read_bytes() == payload
    assert len(server.requests) == 4  # one connection per slice
    assert seen and seen[-1]["name"] == name
    assert music_sc.status()["downloading"] is None
