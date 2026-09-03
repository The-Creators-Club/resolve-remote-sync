"""local_vlm.py against a REAL (but fake) llama-server: a tiny stdlib HTTP
server that answers /health and /v1/chat/completions with scripted content,
the same OpenAI-compatible shape the real llama-server speaks. No model, no
GPU, no network beyond localhost. Covers run_window/call_local_with_retry's
HTTP client, get_server's attach-to-server_url path, and an end-to-end
stage_describe(local)/describe_video pass over two synthetic clips.
"""
from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import pytest
from PIL import Image

from broll_index import local_vlm
from broll_index.config import Config, DbConfig, EmbeddingConfig, IndexerConfig, SamplingConfig, ShareConfig


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401 - silence stdlib's default access log
        pass

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        script = self.server.script  # type: ignore[attr-defined]
        calls = self.server.calls  # type: ignore[attr-defined]
        calls.append(body)
        idx = min(len(calls) - 1, len(script) - 1)
        text = script[idx]
        n_images = sum(1 for c in body["messages"][0]["content"] if c.get("type") == "image_url")
        payload = {
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100 * max(1, n_images), "completion_tokens": len(text.split())},
            "timings": {"prompt_ms": 50.0, "predicted_ms": 25.0},
        }
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def fake_server():
    """A real localhost HTTP server; `.script` is the ordered list of raw model
    texts to answer successive calls with (the last entry repeats)."""
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    httpd.script = ["S F1 | ok shot | thing | - // -\nT theme\n"]
    httpd.calls = []
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        t.join(timeout=5)


def _frames(n: int, tmp_path: Path) -> list[dict]:
    out = []
    for i in range(n):
        p = tmp_path / f"frame_{i:04d}.jpg"
        Image.new("RGB", (16, 9), color=(100, 100, 100)).save(p, "JPEG")
        out.append({"i": i, "t": float(i * 4), "tc": local_vlm.seconds_to_tc(i * 4), "path": p})
    return out


# ---------------------------------------------------------------------------
# get_server: attach to an already-healthy server
# ---------------------------------------------------------------------------

def test_get_server_attaches_to_a_healthy_server_url(fake_server):
    handle = local_vlm.get_server(server_url=f"http://127.0.0.1:{fake_server.server_port}")
    assert handle.url == f"http://127.0.0.1:{fake_server.server_port}"
    assert handle.proc is None


def test_get_server_refuses_an_unhealthy_server_url():
    with pytest.raises(local_vlm.LocalVlmError, match="not healthy"):
        local_vlm.get_server(server_url="http://127.0.0.1:1")  # nothing listening


# ---------------------------------------------------------------------------
# run_window / call_local_with_retry
# ---------------------------------------------------------------------------

def test_run_window_sends_frames_as_image_blocks_and_returns_the_envelope(fake_server, tmp_path):
    handle = local_vlm.ServerHandle(url=f"http://127.0.0.1:{fake_server.server_port}")
    frames = _frames(2, tmp_path)
    envelope = local_vlm.run_window(handle, frames, grammar=True)
    assert envelope["result"] == fake_server.script[0]
    assert envelope["usage"]["input_tokens"] == 200
    assert envelope["duration_ms"] >= 0
    body = fake_server.calls[0]
    content = body["messages"][0]["content"]
    assert sum(1 for c in content if c["type"] == "image_url") == 2
    assert "grammar" in body


def test_run_window_no_grammar_flag_omits_grammar_field(fake_server, tmp_path):
    handle = local_vlm.ServerHandle(url=f"http://127.0.0.1:{fake_server.server_port}")
    local_vlm.run_window(handle, _frames(1, tmp_path), grammar=False)
    assert "grammar" not in fake_server.calls[0]


def test_call_local_with_retry_parses_into_the_contract_shape(fake_server, tmp_path):
    handle = local_vlm.ServerHandle(url=f"http://127.0.0.1:{fake_server.server_port}")
    frames = _frames(1, tmp_path)
    parsed, usage = local_vlm.call_local_with_retry(handle, frames)
    assert len(parsed["segments"]) == 1
    assert parsed["segments"][0]["t_start"] == frames[0]["t"]
    assert usage["backend"] == "local"
    assert usage["total_cost_usd"] == 0.0


def test_call_local_with_retry_retries_once_on_unparseable_output(tmp_path):
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    httpd.script = ["complete garbage, no S lines here", "S F1 | ok | thing | - // -\nT x\n"]
    httpd.calls = []
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        handle = local_vlm.ServerHandle(url=f"http://127.0.0.1:{httpd.server_port}")
        parsed, _usage = local_vlm.call_local_with_retry(handle, _frames(1, tmp_path))
        assert len(parsed["segments"]) == 1
        assert len(httpd.calls) == 2
    finally:
        httpd.shutdown()
        t.join(timeout=5)


def test_call_local_with_retry_raises_after_two_unparseable_responses(tmp_path):
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    httpd.script = ["garbage one", "garbage two"]
    httpd.calls = []
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        handle = local_vlm.ServerHandle(url=f"http://127.0.0.1:{httpd.server_port}")
        with pytest.raises(ValueError, match="unparseable"):
            local_vlm.call_local_with_retry(handle, _frames(1, tmp_path))
    finally:
        httpd.shutdown()
        t.join(timeout=5)


# ---------------------------------------------------------------------------
# windowing / frame-list reconstruction
# ---------------------------------------------------------------------------

def test_balanced_windows_no_orphan_last_window():
    windows = local_vlm.balanced_windows(list(range(10)), 9)
    assert [len(w) for w in windows] == [5, 5]


def test_balanced_windows_exact_multiple():
    windows = local_vlm.balanced_windows(list(range(18)), 9)
    assert [len(w) for w in windows] == [9, 9]


def test_load_frame_list_reconstructs_paths_from_frames_json(tmp_path):
    sheets_dir = tmp_path / "sheets" / "42"
    frames_dir = sheets_dir / "frames"
    frames_dir.mkdir(parents=True)
    for i in range(3):
        Image.new("RGB", (4, 4)).save(frames_dir / f"frame_{i:04d}.jpg", "JPEG")
    (sheets_dir / "frames.json").write_text(
        json.dumps({"timestamps": [0.0, 4.0, 8.0], "sheets": []}), encoding="utf-8")
    frames = local_vlm.load_frame_list(sheets_dir)
    assert [f["t"] for f in frames] == [0.0, 4.0, 8.0]
    assert frames[1]["path"] == frames_dir / "frame_0001.jpg"


def test_load_frame_list_skips_missing_files_without_raising(tmp_path):
    sheets_dir = tmp_path / "sheets" / "42"
    frames_dir = sheets_dir / "frames"
    frames_dir.mkdir(parents=True)
    Image.new("RGB", (4, 4)).save(frames_dir / "frame_0000.jpg", "JPEG")
    # frame_0001.jpg deliberately absent
    (sheets_dir / "frames.json").write_text(
        json.dumps({"timestamps": [0.0, 4.0], "sheets": []}), encoding="utf-8")
    frames = local_vlm.load_frame_list(sheets_dir)
    assert len(frames) == 1


def test_load_frame_list_raises_when_frames_json_absent(tmp_path):
    with pytest.raises(RuntimeError, match="frames"):
        local_vlm.load_frame_list(tmp_path / "sheets" / "1")


# ---------------------------------------------------------------------------
# end-to-end: describe_video over 2 synthetic clips against the fake server
# ---------------------------------------------------------------------------

class _StubStorage:
    def __init__(self, taxonomy):
        self._taxonomy = taxonomy
        self.written = {}

    def get_categories(self):
        return self._taxonomy

    def write_index_result(self, video_id, *, themes, quality_flags, category_hint, segments, model):
        self.written[video_id] = dict(themes=themes, quality_flags=quality_flags,
                                      category_hint=category_hint, segments=segments, model=model)


def _make_clip(data_root: Path, video_id: int, n_frames: int) -> None:
    sheets_dir = data_root / "sheets" / str(video_id)
    frames_dir = sheets_dir / "frames"
    frames_dir.mkdir(parents=True)
    timestamps = []
    for i in range(n_frames):
        t = float(i * 4)
        timestamps.append(t)
        Image.new("RGB", (32, 18), color=(80, 80, 80)).save(frames_dir / f"frame_{i:04d}.jpg", "JPEG")
    (sheets_dir / "frames.json").write_text(
        json.dumps({"timestamps": timestamps, "sheets": []}), encoding="utf-8")


@pytest.fixture
def local_cfg(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    return Config(
        shares={"broll": ShareConfig(root=str(tmp_path))},
        data_root=data_root,
        db=DbConfig(mode="sqlite", path=str(tmp_path / "b.db")),
        sampling=SamplingConfig(),
        embedding=EmbeddingConfig(cache_dir=""),
        indexer=IndexerConfig(backend="local", model_tier="good", frames_per_call=9,
                              merge_similar_segments=False),
    )


def test_describe_video_end_to_end_two_synthetic_clips(fake_server, local_cfg):
    fake_server.script = [
        "S F1-F2 | crowd interior, dim lighting | crowd;people | - // -\n"
        "S F3 | newsreader | newsreader | - // -\nT news;crowd\n"
    ]
    storage = _StubStorage(taxonomy=[
        {"slug": "general/public-life", "label": "Public life", "description": "crowds, gatherings, public spaces"},
    ])
    server_url = f"http://127.0.0.1:{fake_server.server_port}"

    for vid, n_frames in ((101, 3), (102, 5)):
        _make_clip(local_cfg.data_root, vid, n_frames)
        usage_calls = []
        result = local_vlm.describe_video(
            local_cfg, storage, {"id": vid},
            log_usage=lambda m, n, u: usage_calls.append((m, n, u)),
            server_url=server_url,
        )
        assert result["segments"], f"clip {vid} produced no segments"
        assert storage.written[vid]["model"] == "local:qwen3-vl-4b-q4_k_m"
        assert usage_calls, "usage was never logged"
        assert all(u["backend"] == "local" for _m, _n, u in usage_calls)

    # Two independent clips -> two write_index_result calls, both present.
    assert set(storage.written) == {101, 102}


def test_describe_video_raises_when_frames_stage_never_ran(fake_server, local_cfg):
    storage = _StubStorage(taxonomy=[])
    with pytest.raises(RuntimeError, match="frames"):
        local_vlm.describe_video(
            local_cfg, storage, {"id": 999},
            server_url=f"http://127.0.0.1:{fake_server.server_port}",
        )


# ---------------------------------------------------------------------------
# start_server's Windows creation flags (2026-08-18, plan §3.4)
# ---------------------------------------------------------------------------

class _FakeProc:
    """A llama-server that is alive and never exits."""

    returncode = None

    def poll(self):
        return None

    def terminate(self):
        pass


def test_start_server_spawns_with_create_no_window_on_windows(tmp_path, monkeypatch):
    """This module is VENDORED INTO THE COMPANION (docs/BROLL_INGEST_PLAN.md
    §3.3), a windowed PyInstaller build: without CREATE_NO_WINDOW (0x08000000)
    starting the model server flashes a black console on the editor's desktop
    and leaves it there for the life of the batch. CREATE_NEW_PROCESS_GROUP
    (0x00000200) stays, so a Ctrl-C in the indexer's own console still does not
    reach llama-server."""
    seen = {}

    def fake_popen(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return _FakeProc()

    monkeypatch.setattr(local_vlm.os, "name", "nt")
    monkeypatch.setattr(local_vlm.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(local_vlm, "_health", lambda url, *a, **kw: True)

    local_vlm.start_server(tmp_path / "llama-server.exe", tmp_path / "w.gguf",
                           tmp_path / "m.gguf", port=1234)

    flags = seen["kwargs"]["creationflags"]
    assert flags & 0x08000000, "CREATE_NO_WINDOW missing"
    assert flags & 0x00000200, "CREATE_NEW_PROCESS_GROUP missing"


def test_start_server_passes_no_creation_flags_off_windows(tmp_path, monkeypatch):
    seen = {}

    def fake_popen(cmd, **kwargs):
        seen["kwargs"] = kwargs
        return _FakeProc()

    monkeypatch.setattr(local_vlm.os, "name", "posix")
    monkeypatch.setattr(local_vlm.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(local_vlm, "_health", lambda url, *a, **kw: True)

    local_vlm.start_server(tmp_path / "llama-server", tmp_path / "w.gguf",
                           tmp_path / "m.gguf", port=1234)
    assert "creationflags" not in seen["kwargs"]


# ---------------------------------------------------------------------------
# the warm-server cache and the start path hold no orphans
# (bug-hunt-2026-09-03 broll-2 / broll-3)
# ---------------------------------------------------------------------------

class _RecordingProc:
    """A llama-server that records the shutdown it is given and honours it."""

    def __init__(self, *, ignores_terminate: bool = False):
        self.returncode = None
        self.calls: list[str] = []
        self._ignores_terminate = ignores_terminate

    def poll(self):
        return self.returncode

    def terminate(self):
        self.calls.append("terminate")
        if not self._ignores_terminate:
            self.returncode = -15

    def wait(self, timeout=None):
        if self.returncode is None:
            raise local_vlm.subprocess.TimeoutExpired("llama-server", timeout)
        return self.returncode

    def kill(self):
        self.calls.append("kill")
        self.returncode = -9


@pytest.fixture
def clean_server_cache():
    local_vlm._servers.clear()
    yield
    local_vlm._servers.clear()


def test_an_unhealthy_warm_server_is_stopped_before_its_replacement_starts(
        tmp_path, monkeypatch, clean_server_cache):
    """broll-2, 2026-09-03. The cache used to overwrite the entry and drop the
    old handle: a server that is alive but not answering /health kept a whole
    VLM in VRAM while a second copy loaded beside it, and stop_all_servers()
    could no longer see it to reap it (the sidecar's stop_server() is exactly
    that call)."""
    stale = _RecordingProc()
    stale_handle = local_vlm.ServerHandle(url="http://127.0.0.1:9999", proc=stale)
    key = (str(tmp_path / "llama-server"), str(tmp_path / "w.gguf"),
           str(tmp_path / "m.gguf"), 99, local_vlm.DEFAULT_CTX)
    local_vlm._servers[key] = stale_handle

    monkeypatch.setattr(local_vlm, "_health", lambda url, *a, **kw: False)
    fresh = local_vlm.ServerHandle(url="http://127.0.0.1:8888", proc=_RecordingProc())
    monkeypatch.setattr(local_vlm, "start_server", lambda *a, **kw: fresh)

    handle = local_vlm.get_server(exe=tmp_path / "llama-server", model_path=tmp_path / "w.gguf",
                                  mmproj_path=tmp_path / "m.gguf")

    assert handle is fresh
    assert stale.calls[0] == "terminate", "the stale server was left holding the GPU"
    assert stale.poll() is not None


def test_a_slow_warm_server_is_reused_rather_than_replaced(
        tmp_path, monkeypatch, clean_server_cache):
    """broll-2's second half: one missed 3 s probe (a resuming machine, GPU
    contention) must not cost a 10 GB model reload. The first attempt keeps its
    timeout; only a server that already failed once pays the longer one."""
    warm = local_vlm.ServerHandle(url="http://127.0.0.1:9999", proc=_RecordingProc())
    key = (str(tmp_path / "llama-server"), str(tmp_path / "w.gguf"),
           str(tmp_path / "m.gguf"), 99, local_vlm.DEFAULT_CTX)
    local_vlm._servers[key] = warm

    seen = []

    def flaky_health(url, timeout=3.0, **kw):
        seen.append(timeout)
        return timeout > 3.0

    monkeypatch.setattr(local_vlm, "_health", flaky_health)
    monkeypatch.setattr(local_vlm, "start_server", lambda *a, **kw: pytest.fail(
        "a slow but living server was replaced"))

    assert local_vlm.get_server(exe=tmp_path / "llama-server", model_path=tmp_path / "w.gguf",
                                mmproj_path=tmp_path / "m.gguf") is warm
    assert seen == [3.0, 15.0]


def test_a_server_that_never_loads_is_killed_and_its_log_closed(tmp_path, monkeypatch):
    """broll-3, 2026-09-03. The load-timeout path called a bare terminate()
    (a process still mmap-ing a 10 GB model ignores it and keeps the GPU) and
    leaked the log file object on every raise."""
    proc = _RecordingProc(ignores_terminate=True)
    monkeypatch.setattr(local_vlm.subprocess, "Popen", lambda cmd, **kw: proc)
    monkeypatch.setattr(local_vlm, "_health", lambda url, *a, **kw: False)
    opened = []
    real_open = open

    def spy_open(*args, **kwargs):
        f = real_open(*args, **kwargs)
        opened.append(f)
        return f

    monkeypatch.setattr("builtins.open", spy_open)
    log_path = tmp_path / "llama.log"

    with pytest.raises(local_vlm.LocalVlmError, match="did not become healthy"):
        local_vlm.start_server(tmp_path / "llama-server", tmp_path / "w.gguf",
                               tmp_path / "m.gguf", port=1234, load_timeout=0.01,
                               log_path=log_path)

    assert proc.calls == ["terminate", "kill"], proc.calls
    assert opened and all(f.closed for f in opened), "the log handle was leaked"


def test_a_server_that_exits_early_closes_its_log_too(tmp_path, monkeypatch):
    """The other raise in start_server: same leak, same finally."""
    proc = _RecordingProc()
    proc.returncode = 1
    monkeypatch.setattr(local_vlm.subprocess, "Popen", lambda cmd, **kw: proc)
    monkeypatch.setattr(local_vlm, "_health", lambda url, *a, **kw: False)
    opened = []
    real_open = open

    def spy_open(*args, **kwargs):
        f = real_open(*args, **kwargs)
        opened.append(f)
        return f

    monkeypatch.setattr("builtins.open", spy_open)

    with pytest.raises(local_vlm.LocalVlmError, match="exited early"):
        local_vlm.start_server(tmp_path / "llama-server", tmp_path / "w.gguf",
                               tmp_path / "m.gguf", port=1234,
                               log_path=tmp_path / "llama.log")
    assert opened and all(f.closed for f in opened)
