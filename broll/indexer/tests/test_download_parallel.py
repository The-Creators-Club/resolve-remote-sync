"""download_verified's parallel/ranged path, against a REAL localhost HTTP
server rather than a fake opener.

Why a real server (2026-08-18, BROLL-ING-4): the bug being fixed was a
transport bug -- one long-lived HTTPS connection to Hugging Face crawling at
~2 MB/s while fresh ones ran at 13-45 MB/s -- and every interesting behaviour
here (206 + Content-Range, several sockets writing into one preallocated file,
a stream that goes quiet, a server that never learned Range) lives in the
socket layer that a `_FakeResponse` replaces. The fakes in
test_local_runtime.py still pin the semantics; this file pins the plumbing.

The server is stdlib `ThreadingHTTPServer` on 127.0.0.1:0 -- no network, no
fixture beyond what the frozen companion already has (this module is vendored
into the tray app, so nothing here may need a third-party package).
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

from broll_index import local_runtime

PAYLOAD_SIZE = 12 * 1024 * 1024  # 12 MiB, big enough to slice several ways


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def payload() -> bytes:
    """Random bytes: an incorrectly assembled file (a duplicated prefix, two
    slices swapped) must not accidentally hash the same as a correct one."""
    return os.urandom(PAYLOAD_SIZE)


class _Server:
    """A one-file HTTP server whose Range behaviour the test dictates.

    `behaviour(start, end, attempt) -> "ok" | "stall" | "error"` is consulted
    per request, with `attempt` counting how many times THIS byte offset has
    been asked for -- which is how "the first connection for slice 1 goes
    quiet, the second one is fine" is expressed.
    """

    def __init__(self, payload: bytes, *, ranges: bool = True, behaviour=None,
                 stall_seconds: float = 2.0):
        self.payload = payload
        self.ranges = ranges
        self.behaviour = behaviour or (lambda start, end, attempt: "ok")
        self.stall_seconds = stall_seconds
        self.requests: list[tuple[int, int]] = []
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # noqa: A003 - silence the stderr spam
                pass

            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's spelling
                outer._serve(self)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/model.bin"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=10)

    def starts(self) -> list[int]:
        with self._lock:
            return [start for start, _end in self.requests]

    def _serve(self, handler: BaseHTTPRequestHandler) -> None:
        total = len(self.payload)
        raw_range = handler.headers.get("Range") or ""
        match = re.match(r"bytes=(\d+)-(\d*)", raw_range)
        partial = bool(match) and self.ranges
        start = int(match.group(1)) if partial else 0
        end = int(match.group(2)) if (partial and match.group(2)) else total - 1

        with self._lock:
            attempt = sum(1 for s, _e in self.requests if s == start)
            self.requests.append((start, end))

        mode = self.behaviour(start, end, attempt)
        if mode == "error":
            handler.send_response(500)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return

        body = self.payload[start:end + 1]
        handler.send_response(206 if partial else 200)
        handler.send_header("Content-Type", "application/octet-stream")
        handler.send_header("Accept-Ranges", "bytes" if self.ranges else "none")
        handler.send_header("Content-Length", str(len(body)))
        if partial:
            handler.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        handler.end_headers()
        if mode == "stall":
            # Send a little, then hold the connection open saying nothing. The
            # client's stall rule (not an EOF) is what has to notice.
            handler.wfile.write(body[:len(body) // 8])
            handler.wfile.flush()
            time.sleep(self.stall_seconds)
            handler.close_connection = True
            return
        handler.wfile.write(body)


@pytest.fixture
def small_slices(monkeypatch):
    """Slice a 12 MiB test file the way a 4 GB model gets sliced. Production's
    8 MiB floor would make every file here a single stream."""
    monkeypatch.setattr(local_runtime, "MIN_SLICE_BYTES", 256 * 1024)


@pytest.fixture
def impatient(monkeypatch):
    """The stall rule in test time: half a second of silence is dead."""
    monkeypatch.setattr(local_runtime, "STALL_WINDOW_SECONDS", 0.5)
    monkeypatch.setattr(local_runtime, "STALL_MIN_BYTES", 64)


# ---------------------------------------------------------------------------
# the happy paths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("streams", ["1", "6"])
def test_the_file_arrives_byte_identical_at_one_and_six_streams(
        tmp_path, payload, monkeypatch, small_slices, streams):
    monkeypatch.setenv(local_runtime.STREAMS_ENV, streams)
    server = _Server(payload)
    try:
        dest = tmp_path / "model.bin"
        got = local_runtime.download_verified(
            server.url, dest, sha256=_sha256(payload), size_bytes=len(payload))
    finally:
        server.stop()

    assert got.read_bytes() == payload
    assert not dest.with_suffix(".bin.part").exists()
    assert not (tmp_path / "model.bin.part.json").exists()
    # N=1 is one connection; N=6 is one per slice.
    assert len(server.requests) == (1 if streams == "1" else 6)


def test_six_streams_cover_the_file_exactly_once(tmp_path, payload, monkeypatch,
                                                 small_slices):
    monkeypatch.setenv(local_runtime.STREAMS_ENV, "6")
    server = _Server(payload)
    try:
        local_runtime.download_verified(server.url, tmp_path / "model.bin",
                                        sha256=_sha256(payload))
    finally:
        server.stop()
    planned = local_runtime._split(len(payload), 6)
    assert [s.start for s in planned] == sorted(server.starts())
    assert planned[-1].end == len(payload) - 1
    for before, after in zip(planned, planned[1:]):
        assert after.start == before.end + 1  # contiguous, no overlap, no gap
    # Slice 0 rides the connection that was opened to learn the size, so its
    # request is the open-ended "bytes=0-" one; the rest are bounded.
    ends = {start: end for start, end in server.requests}
    assert ends[0] == len(payload) - 1
    assert ends[planned[1].start] == planned[1].end


def test_a_server_without_range_support_falls_back_to_one_stream(
        tmp_path, payload, monkeypatch, small_slices):
    monkeypatch.setenv(local_runtime.STREAMS_ENV, "6")
    server = _Server(payload, ranges=False)
    try:
        got = local_runtime.download_verified(server.url, tmp_path / "model.bin",
                                              sha256=_sha256(payload))
    finally:
        server.stop()
    assert got.read_bytes() == payload
    assert len(server.requests) == 1  # asked for a range, got the whole body, kept it


def test_progress_reports_bytes_and_a_rate(tmp_path, payload, monkeypatch, small_slices):
    monkeypatch.setenv(local_runtime.STREAMS_ENV, "6")
    seen: list[tuple[int, int | None]] = []
    rates: list[float] = []
    server = _Server(payload)
    try:
        local_runtime.download_verified(
            server.url, tmp_path / "model.bin", sha256=_sha256(payload),
            size_bytes=len(payload), progress=lambda w, t: seen.append((w, t)),
            rate_cb=rates.append)
    finally:
        server.stop()
    assert seen[-1] == (len(payload), len(payload))
    assert all(t == len(payload) for _w, t in seen)
    assert [w for w, _t in seen] == sorted(w for w, _t in seen)  # never goes backwards
    assert rates  # a rate was published for the window's "N MB/s" line
    assert local_runtime.download_verified.last_rate_bytes_per_s > 0


# ---------------------------------------------------------------------------
# resume
# ---------------------------------------------------------------------------

def test_a_killed_parallel_download_resumes_each_slice_where_it_stopped(
        tmp_path, payload, monkeypatch, small_slices):
    """The `.part.json` sidecar IS the resume: a preallocated file plus per
    slice byte counts, so the second run asks only for what is missing."""
    monkeypatch.setenv(local_runtime.STREAMS_ENV, "4")
    total = len(payload)
    size = -(-total // 4)
    slices = []
    part = tmp_path / "model.bin.part"
    with open(part, "wb") as f:
        f.truncate(total)
        for i in range(4):
            start = i * size
            end = min(start + size, total) - 1
            done = (end - start + 1) // 3 if i % 2 == 0 else 0  # a lopsided kill
            f.seek(start)
            f.write(payload[start:start + done])
            slices.append({"start": start, "end": end, "done": done})
    (tmp_path / "model.bin.part.json").write_text(json.dumps({
        "version": local_runtime.SIDECAR_VERSION,
        "url": "PLACEHOLDER", "sha256": _sha256(payload),
        "total": total, "slices": slices,
    }), encoding="utf-8")

    server = _Server(payload)
    try:
        # The URL is part of the sidecar's identity, so it has to be the real
        # one -- rewrite it now that the port is known.
        data = json.loads((tmp_path / "model.bin.part.json").read_text(encoding="utf-8"))
        data["url"] = server.url
        (tmp_path / "model.bin.part.json").write_text(json.dumps(data), encoding="utf-8")
        got = local_runtime.download_verified(
            server.url, tmp_path / "model.bin", sha256=_sha256(payload))
    finally:
        server.stop()

    assert got.read_bytes() == payload
    assert not part.exists() and not (tmp_path / "model.bin.part.json").exists()
    # Every request started where its slice had stopped, never at the slice's
    # own start -- that is the difference between resuming and re-downloading.
    assert sorted(server.starts()) == sorted(s["start"] + s["done"] for s in slices)


def test_a_sidecar_that_does_not_match_the_part_starts_over(
        tmp_path, payload, monkeypatch, small_slices):
    monkeypatch.setenv(local_runtime.STREAMS_ENV, "2")
    # A sidecar means the `.part` was written in SLICES, so it has holes and
    # its length means nothing. One that does not describe the file beside it
    # takes that file with it rather than resuming from a meaningless offset.
    part = tmp_path / "model.bin.part"
    part.write_bytes(b"\0" * 1024)  # not `total` bytes: the plan cannot be trusted
    (tmp_path / "model.bin.part.json").write_text(json.dumps({
        "version": local_runtime.SIDECAR_VERSION, "url": "http://elsewhere/f",
        "sha256": "0" * 64, "total": len(payload),
        "slices": [{"start": 0, "end": len(payload) - 1, "done": 1024}],
    }), encoding="utf-8")

    server = _Server(payload)
    try:
        got = local_runtime.download_verified(server.url, tmp_path / "model.bin",
                                              sha256=_sha256(payload))
    finally:
        server.stop()
    assert got.read_bytes() == payload
    assert 0 in server.starts()


def test_a_part_without_a_sidecar_resumes_as_a_single_stream(
        tmp_path, payload, monkeypatch, small_slices):
    """A partial written by an older build (or by N=1) has no slice plan. It
    is still resumable -- from the end of the file, one connection, exactly as
    this function always did."""
    monkeypatch.setenv(local_runtime.STREAMS_ENV, "6")
    part = tmp_path / "model.bin.part"
    part.write_bytes(payload[:1_000_000])

    server = _Server(payload)
    try:
        got = local_runtime.download_verified(server.url, tmp_path / "model.bin",
                                              sha256=_sha256(payload))
    finally:
        server.stop()
    assert got.read_bytes() == payload
    assert server.starts() == [1_000_000]


# ---------------------------------------------------------------------------
# stalls and failures
# ---------------------------------------------------------------------------

def test_a_stalled_stream_is_reconnected_and_the_download_completes(
        tmp_path, payload, monkeypatch, small_slices, impatient):
    """The measured cure: a connection that has gone quiet is dropped and its
    remaining range reopened, which lands on a different CDN edge."""
    monkeypatch.setenv(local_runtime.STREAMS_ENV, "4")
    size = -(-len(payload) // 4)
    stalled_start = size  # slice 1

    def behaviour(start, end, attempt):
        return "stall" if start == stalled_start and attempt == 0 else "ok"

    server = _Server(payload, behaviour=behaviour, stall_seconds=2.0)
    try:
        got = local_runtime.download_verified(server.url, tmp_path / "model.bin",
                                              sha256=_sha256(payload))
    finally:
        server.stop()

    assert got.read_bytes() == payload
    # The reconnect asked for the REST of that slice, not the whole of it.
    resumed = [s for s in server.starts() if stalled_start < s <= stalled_start + size]
    assert resumed, f"no reconnect for the stalled slice: {sorted(server.starts())}"


def test_a_stream_that_never_recovers_fails_the_download_and_keeps_the_partial(
        tmp_path, payload, monkeypatch, small_slices):
    monkeypatch.setenv(local_runtime.STREAMS_ENV, "4")
    size = -(-len(payload) // 4)
    doomed = size * 2  # slice 2

    def behaviour(start, end, attempt):
        return "error" if start == doomed else "ok"

    server = _Server(payload, behaviour=behaviour)
    try:
        with pytest.raises(local_runtime.LocalRuntimeError, match="could not download"):
            local_runtime.download_verified(server.url, tmp_path / "model.bin",
                                            sha256=_sha256(payload))
    finally:
        server.stop()

    part = tmp_path / "model.bin.part"
    sidecar = tmp_path / "model.bin.part.json"
    assert part.is_file() and sidecar.is_file()  # kept, so the next run resumes
    assert not (tmp_path / "model.bin").exists()
    assert server.starts().count(doomed) == local_runtime.SLICE_ATTEMPTS
    plan = json.loads(sidecar.read_text(encoding="utf-8"))
    done = [s["done"] for s in plan["slices"]]
    assert done[2] == 0 and sum(done) > 0  # the others got their bytes down


def test_a_wrong_digest_deletes_the_file_and_the_sidecar(tmp_path, payload, monkeypatch,
                                                         small_slices):
    monkeypatch.setenv(local_runtime.STREAMS_ENV, "4")
    server = _Server(payload)
    try:
        with pytest.raises(local_runtime.LocalRuntimeError, match="sha256 mismatch"):
            local_runtime.download_verified(server.url, tmp_path / "model.bin",
                                            sha256="0" * 64)
    finally:
        server.stop()
    assert not (tmp_path / "model.bin").exists()
    assert not (tmp_path / "model.bin.part").exists()
    assert not (tmp_path / "model.bin.part.json").exists()


def test_the_caller_can_cancel_from_its_progress_callback(tmp_path, payload, monkeypatch,
                                                          small_slices):
    """The companion's stop path (broll_vlm_sidecar._Stopped): the exception is
    raised inside `progress` and must come back out of download_verified with
    the partial left on disk."""
    monkeypatch.setenv(local_runtime.STREAMS_ENV, "4")

    class _Stopped(Exception):
        pass

    def progress(written, total):
        if written:
            raise _Stopped()

    server = _Server(payload)
    try:
        with pytest.raises(_Stopped):
            local_runtime.download_verified(server.url, tmp_path / "model.bin",
                                            sha256=_sha256(payload), progress=progress)
    finally:
        server.stop()
    assert (tmp_path / "model.bin.part").is_file()
    assert (tmp_path / "model.bin.part.json").is_file()


# ---------------------------------------------------------------------------
# the knob
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("", local_runtime.DEFAULT_STREAMS),
    ("1", 1), ("6", 6), ("16", 16),
    ("0", 1), ("-3", 1), ("99", local_runtime.MAX_STREAMS),
    ("banana", local_runtime.DEFAULT_STREAMS),
])
def test_the_stream_count_env_var_is_clamped(monkeypatch, value, expected):
    monkeypatch.setenv(local_runtime.STREAMS_ENV, value)
    assert local_runtime._stream_count() == expected


def test_no_env_var_means_the_default(monkeypatch):
    monkeypatch.delenv(local_runtime.STREAMS_ENV, raising=False)
    assert local_runtime._stream_count() == local_runtime.DEFAULT_STREAMS
