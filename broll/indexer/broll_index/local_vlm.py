"""The local backend: llama-server lifecycle, one HTTP call per window of
frames, and the segment-merge post-process the eval flagged as the remaining
gap (`broll/docs/local-indexing-options-2026-08-17.md` §3,
`broll/eval/local_vlm/results/report.md`: 10.3 predicted segments/clip vs
Haiku's 4.3 — over-segmentation, not under).

This plugs into `pipeline.stage_describe` at the same seam `invoke_claude` used
to occupy (see claude_client.py's InvokeFn docstring): one call in, one JSON
envelope out, `_log_usage` and `usage.jsonl` unchanged in shape. The parser is
different (`compact_format.parse_compact`, which needs the frame table to look
up timecodes — the model is never trusted with them), so this module owns its
own retry loop (`call_local_with_retry`) rather than reusing
`claude_client.call_claude_with_retry`.
"""

from __future__ import annotations

import atexit
import base64
import difflib
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen

from . import local_models, local_runtime
from .contract import merge_index_results
from .compact_format import (
    CategoryAssigner, build_compact_prompt, build_grammar, clip_text_for_category,
    parse_compact, pixel_quality_flags, seconds_to_tc,
)

logger = logging.getLogger(__name__)

DEFAULT_SAMPLER = {"temperature": 0.1, "repeat_penalty": 1.15}
TOKENS_PER_FRAME_BUDGET = 150  # 120 hit finish=length on chyron-heavy windows in the eval smoke test
DEFAULT_CTX = 16384
DEFAULT_IMAGE_MIN_TOKENS = 1024
DEFAULT_LOAD_TIMEOUT_S = 1200.0
DEFAULT_CALL_TIMEOUT_S = 900.0


class LocalVlmError(RuntimeError):
    """An environmental failure talking to llama-server: refused to start, died
    mid-run, or never answered /health. Classified as fatal by
    `is_fatal_local_error` the same way `claude_client.is_fatal_api_error`
    treats an account-wide API failure — a dead server will fail every
    remaining clip identically, so the run should stop with the queue intact
    rather than mark them all 'error'."""


_FATAL_MARKERS = (
    "not healthy", "did not become healthy", "exited early",
    "connection refused", "econnrefused", "failed to start",
)


def is_fatal_local_error(message: str) -> bool:
    lowered = (message or "").lower()
    return any(m in lowered for m in _FATAL_MARKERS)


# ---------------------------------------------------------------------------
# llama-server lifecycle
# ---------------------------------------------------------------------------

@dataclass
class ServerHandle:
    url: str
    proc: "subprocess.Popen | None" = None

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        try:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        except Exception:  # noqa: BLE001 - best-effort shutdown
            pass


def _health(url: str, timeout: float = 3.0, opener: Callable[..., Any] = urlopen) -> bool:
    try:
        with opener(Request(f"{url.rstrip('/')}/health"), timeout=timeout) as r:
            return getattr(r, "status", 200) == 200
    except Exception:  # noqa: BLE001
        return False


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(
    exe: Path, model_path: Path, mmproj_path: Path, *,
    port: int | None = None, ctx: int = DEFAULT_CTX, gpu_layers: int = 99,
    image_min_tokens: int = DEFAULT_IMAGE_MIN_TOKENS,
    load_timeout: float = DEFAULT_LOAD_TIMEOUT_S, log_path: Path | None = None,
    extra_args: Sequence[str] = (),
) -> ServerHandle:
    """Launch `llama-server` and block until `/health` answers or `load_timeout`
    elapses. `-np 1`: one slot — this stage is one call at a time per server,
    matching the eval's config and llama-server's lack of continuous batching
    for mmproj image encode anyway."""
    port = port or _free_port()
    cmd = [str(exe), "-m", str(model_path), "--mmproj", str(mmproj_path),
           "--host", "127.0.0.1", "--port", str(port), "-c", str(ctx),
           "-ngl", str(gpu_layers), "-np", "1", "--no-warmup"]
    if image_min_tokens > 0:
        cmd += ["--image-min-tokens", str(image_min_tokens)]
    cmd += list(extra_args)

    logf = open(log_path, "a", encoding="utf-8") if log_path else subprocess.DEVNULL
    if log_path:
        logf.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(cmd)}\n")
        logf.flush()
    creation = {}
    if os.name == "nt":
        # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW. The group flag keeps a
        # Ctrl-C in the indexer's console from reaching llama-server; the
        # no-window flag (0x08000000, added 2026-08-18) is for the OTHER host
        # this module now runs in -- the companion is a windowed PyInstaller
        # build (build.spec, console=False), so an unflagged spawn flashes a
        # black console on the editor's desktop for the life of the server.
        # Harmless in the console case: llama-server's output goes to `logf`
        # either way, never to a window anyone was reading.
        creation["creationflags"] = 0x00000200 | 0x08000000
    proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, **creation)
    url = f"http://127.0.0.1:{port}"
    t0 = time.time()
    while time.time() - t0 < load_timeout:
        if proc.poll() is not None:
            raise LocalVlmError(
                f"llama-server exited early with code {proc.returncode}"
                + (f"; see {log_path}" if log_path else ""))
        if _health(url):
            return ServerHandle(url=url, proc=proc)
        time.sleep(1)
    proc.terminate()
    raise LocalVlmError(f"llama-server did not become healthy within {load_timeout:.0f}s"
                        + (f"; see {log_path}" if log_path else ""))


# One server per (binary, weights, mmproj, gpu_layers) is kept warm for the
# life of the process — a `broll-index run` over thousands of clips must not
# pay llama.cpp's ~50-60s model load per clip. atexit stops it on interpreter
# shutdown; nothing else in this module tears it down early.
_servers: dict[tuple, ServerHandle] = {}
_servers_lock = threading.Lock()


def get_server(
    *, exe: Path | None = None, model_path: Path | None = None, mmproj_path: Path | None = None,
    gpu_layers: int = 99, ctx: int = DEFAULT_CTX, image_min_tokens: int = DEFAULT_IMAGE_MIN_TOKENS,
    server_url: str | None = None, log_path: Path | None = None,
    load_timeout: float = DEFAULT_LOAD_TIMEOUT_S,
) -> ServerHandle:
    """A healthy llama-server: attach to `server_url` if given (also how tests
    point this at a fake HTTP server without spawning a process), else reuse an
    already-running one for this exact (binary, weights, mmproj, gpu_layers), or
    start a new one."""
    if server_url:
        handle = ServerHandle(url=server_url.rstrip("/"))
        if not _health(handle.url):
            raise LocalVlmError(f"--server-url {handle.url} is not healthy")
        return handle

    if exe is None or model_path is None or mmproj_path is None:
        raise LocalVlmError("get_server needs exe/model_path/mmproj_path, or server_url")

    key = (str(exe), str(model_path), str(mmproj_path), gpu_layers, ctx)
    with _servers_lock:
        existing = _servers.get(key)
        if existing is not None and existing.proc is not None and existing.proc.poll() is None \
                and _health(existing.url):
            return existing
        handle = start_server(
            exe, model_path, mmproj_path, gpu_layers=gpu_layers, ctx=ctx,
            image_min_tokens=image_min_tokens, load_timeout=load_timeout, log_path=log_path,
        )
        _servers[key] = handle
        atexit.register(handle.stop)
        return handle


def stop_all_servers() -> None:
    """Test/CLI hook: stop every server this process started and forget them."""
    with _servers_lock:
        for handle in _servers.values():
            handle.stop()
        _servers.clear()


# ---------------------------------------------------------------------------
# one window (one HTTP call)
# ---------------------------------------------------------------------------

def data_url(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def _compact_content(prompt_static: str, table_tail: str, frames: Sequence[dict[str, Any]]) -> list[dict]:
    """[static instructions][frame table][F1 (tc):][img]...[Fn (tc):][img][answer cue].
    Static text first so llama-server's prompt cache reuses that prefix across
    windows of the same clip."""
    content: list[dict[str, Any]] = [
        {"type": "text", "text": prompt_static}, {"type": "text", "text": table_tail},
    ]
    for i, f in enumerate(frames):
        content.append({"type": "text", "text": f"\nF{i + 1} ({f['tc']}):"})
        content.append({"type": "image_url", "image_url": {"url": data_url(f["path"])}})
    content.append({"type": "text", "text": "\nAnswer now: the S lines, then the T line."})
    return content


def _chat(url: str, body: dict[str, Any], timeout: float, opener: Callable[..., Any] = urlopen) -> dict[str, Any]:
    req = Request(f"{url.rstrip('/')}/v1/chat/completions", data=json.dumps(body).encode(),
                  headers={"Content-Type": "application/json"})
    with opener(req, timeout=timeout) as r:
        return json.load(r)


def run_window(
    server: ServerHandle, frames: Sequence[dict[str, Any]], *,
    sampler: dict[str, Any] = None, grammar: bool = True,
    tokens_per_frame: int = TOKENS_PER_FRAME_BUDGET, timeout: float = DEFAULT_CALL_TIMEOUT_S,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """One llama-server call for one window of frames. Returns an envelope in
    the same shape claude_client._build_envelope uses (`result`/`usage`/
    `duration_ms`), plus llama-server's own `prompt_ms`/`predicted_ms` timings —
    additive fields, so anything reading the claude-shaped envelope still works.
    """
    prompt = build_compact_prompt(frames)
    static, _, tail = prompt.partition("## The frames for this call")
    tail = "## The frames for this call" + tail
    body: dict[str, Any] = {
        "messages": [{"role": "user", "content": _compact_content(static, tail, frames)}],
        "max_tokens": tokens_per_frame * max(1, len(frames)),
        "cache_prompt": True,
        **(sampler or DEFAULT_SAMPLER),
    }
    if grammar:
        body["grammar"] = build_grammar(len(frames))

    t0 = time.time()
    try:
        resp = _chat(server.url, body, timeout, opener=opener)
    except (URLError, OSError, TimeoutError) as e:
        raise LocalVlmError(f"llama-server call failed: {e}") from e
    wall_ms = int((time.time() - t0) * 1000)

    choices = resp.get("choices") or [{}]
    raw = ((choices[0].get("message") or {}).get("content")) or ""
    usage_raw = resp.get("usage") or {}
    timings = resp.get("timings") or {}
    return {
        "type": "result",
        "is_error": False,
        "result": raw,
        "finish_reason": choices[0].get("finish_reason"),
        "usage": {
            "input_tokens": usage_raw.get("prompt_tokens", 0) or 0,
            "output_tokens": usage_raw.get("completion_tokens", 0) or 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
        "total_cost_usd": 0.0,
        "duration_ms": wall_ms,
        "prompt_ms": timings.get("prompt_ms"),
        "predicted_ms": timings.get("predicted_ms"),
    }


def call_local_with_retry(
    server: ServerHandle, frames: Sequence[dict[str, Any]], *,
    sampler: dict[str, Any] = None, grammar: bool = True,
    tokens_per_frame: int = TOKENS_PER_FRAME_BUDGET, timeout: float = DEFAULT_CALL_TIMEOUT_S,
    opener: Callable[..., Any] = urlopen,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One retry on unparseable output, mirroring
    claude_client.call_claude_with_retry's contract. Returns (parsed_contract, usage)."""
    last_error: Exception | None = None
    for _attempt in range(2):
        envelope = run_window(server, frames, sampler=sampler, grammar=grammar,
                              tokens_per_frame=tokens_per_frame, timeout=timeout, opener=opener)
        try:
            parsed, problems = parse_compact(envelope["result"], frames)
        except ValueError as e:
            last_error = e
            continue
        if problems:
            logger.info("local vlm: window had %d tolerated parse issue(s), first: %s",
                        len(problems), problems[0])
        usage = {
            **envelope["usage"],
            "total_cost_usd": 0.0,
            "duration_ms": envelope["duration_ms"],
            "backend": "local",
            "encode_ms": envelope.get("prompt_ms"),
            "decode_ms": envelope.get("predicted_ms"),
            "wall_ms": envelope["duration_ms"],
        }
        return parsed, usage
    raise ValueError(f"local vlm returned unparseable output after one retry: {last_error}")


# ---------------------------------------------------------------------------
# windowing
# ---------------------------------------------------------------------------

def balanced_windows(items: Sequence[Any], per: int) -> list[list[Any]]:
    """ceil(n/per) windows of near-equal size — no orphan 1-item last window,
    same as the eval's run_eval.py."""
    n = len(items)
    if n == 0:
        return []
    per = max(1, int(per))
    k = -(-n // per)
    base, extra = divmod(n, k)
    out, i = [], 0
    for w in range(k):
        size = base + (1 if w < extra else 0)
        out.append(list(items[i:i + size]))
        i += size
    return out


def load_frame_list(sheets_dir: Path) -> list[dict[str, Any]]:
    """Reconstruct the per-frame list (index, timestamp, timecode, path) that
    `stage_frames` extracted, from `frames.json`'s `timestamps` array.

    `frames.json` records only timestamps + sheet paths (see pipeline.stage_frames);
    individual frame files are `frames/frame_{i:04d}.jpg`, where `i` is the
    position in ffmpeg_tools.extract_frames's ORIGINAL requested-timestamp list,
    not necessarily a dense 0..len(timestamps)-1 run (a frame ffmpeg failed to
    produce is simply absent). Assuming timestamps[i] <-> frame_{i:04d}.jpg is
    the same assumption `broll/eval/local_vlm/select_clips.py` makes, and the
    eval's 5,538-clip run found zero clips where it did not hold — a missing
    file here is silently skipped rather than raised, since a partial frame set
    is still worth describing.
    """
    meta_path = Path(sheets_dir) / "frames.json"
    if not meta_path.is_file():
        raise RuntimeError(f"no frames metadata found at {meta_path} - run the 'frames' stage first")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    frames_dir = Path(sheets_dir) / "frames"
    out = []
    for i, t in enumerate(meta.get("timestamps") or []):
        p = frames_dir / f"frame_{i:04d}.jpg"
        if not p.is_file():
            continue
        out.append({"i": i, "t": float(t), "tc": seconds_to_tc(float(t)), "path": p})
    return out


# ---------------------------------------------------------------------------
# segment-merge post-process (the eval's remaining known gap)
# ---------------------------------------------------------------------------

def _objects_set(seg: dict[str, Any]) -> set[str]:
    return {str(o).strip().lower() for o in (seg.get("objects") or []) if str(o).strip()}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _merge_text_field(a: str, b: str) -> str:
    a, b = (a or "").strip(), (b or "").strip()
    if not b:
        return a
    if not a:
        return b
    return a if b in a else f"{a} | {b}"


def _merge_objects(a: list[str], b: list[str]) -> list[str]:
    out, seen = [], set()
    for o in (a or []) + (b or []):
        key = str(o).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(o)
    return out


def merge_similar_segments(
    segments: Sequence[dict[str, Any]], *, jaccard_threshold: float = 0.6,
    text_ratio_threshold: float = 0.75,
) -> tuple[list[dict[str, Any]], int]:
    """Merge ADJACENT (by t_start) segments whose `objects` Jaccard similarity is
    >= `jaccard_threshold` AND whose `description`s are near-duplicates
    (difflib SequenceMatcher ratio >= `text_ratio_threshold`) — the compact
    format's over-segmentation, measured in the eval
    (`broll/eval/local_vlm/results/report.md`: ~10.3 predicted segments/clip vs
    Haiku's 4.3) as the same shot re-described almost identically across
    consecutive single-frame windows (see clip 5871/7272/8264 in that report's
    disagreement list).

    Kept: the earlier `t_start`, the later `t_end`, the union of `objects`
    (case-insensitive, order-preserving), and `onscreen_text`/`onscreen_text_en`
    concatenated when they differ. Only ADJACENT pairs are compared (a merge
    chain can span more than two segments), so two similar-looking shots that
    are not next to each other in time are never folded together.

    Returns (merged_segments, n_merges).
    """
    if not segments:
        return list(segments), 0
    ordered = sorted(segments, key=lambda s: (s.get("t_start", 0) or 0, s.get("t_end", 0) or 0))
    out: list[dict[str, Any]] = [dict(ordered[0])]
    n_merges = 0
    for seg in ordered[1:]:
        prev = out[-1]
        obj_j = _jaccard(_objects_set(prev), _objects_set(seg))
        desc_ratio = difflib.SequenceMatcher(
            None, (prev.get("description") or ""), (seg.get("description") or "")
        ).ratio()
        if obj_j >= jaccard_threshold and desc_ratio >= text_ratio_threshold:
            prev["t_end"] = max(prev.get("t_end", 0) or 0, seg.get("t_end", 0) or 0)
            prev["objects"] = _merge_objects(prev.get("objects"), seg.get("objects"))
            prev["onscreen_text"] = _merge_text_field(prev.get("onscreen_text", ""), seg.get("onscreen_text", ""))
            prev["onscreen_text_en"] = _merge_text_field(
                prev.get("onscreen_text_en", ""), seg.get("onscreen_text_en", ""))
            n_merges += 1
        else:
            out.append(dict(seg))
    return out, n_merges


# ---------------------------------------------------------------------------
# orchestration — the local-backend equivalent of the old stage_claude body
# ---------------------------------------------------------------------------

def describe_video(
    cfg: Any, storage: Any, video: dict[str, Any], *,
    log_usage: "Callable[[str, int, dict[str, Any]], None] | None" = None,
    server_url: str | None = None,
) -> dict[str, Any]:
    """Read `video`'s extracted frames, describe them with the configured local
    tier, and write the result — the local-backend counterpart of the Anthropic
    path's `stage_claude` body, called from `pipeline.stage_describe`.

    `log_usage` is injected rather than imported (pipeline._log_usage lives in
    pipeline.py, which imports this module — importing back would cycle);
    `server_url` lets a caller (a test, or an operator's already-running
    llama-server) skip runtime/model download and process spawn entirely.

    Returns the merged, post-merge-step result dict for callers that want it
    (tests); the DB write already happened by the time this returns.
    """
    sheets_dir = Path(cfg.data_root) / "sheets" / str(video["id"])
    frames = load_frame_list(sheets_dir)
    if not frames:
        raise RuntimeError("no usable frames found - run the 'frames' stage first")

    tier = local_models.tier(cfg.indexer.model_tier)
    model_label = f"local:{tier.model_label}"

    exe: Path | None = None
    weights_path: Path | None = None
    mmproj_path: Path | None = None
    if not server_url:
        cache_dir = Path(cfg.indexer.local_cache_dir) if cfg.indexer.local_cache_dir \
            else local_runtime.default_cache_dir()
        exe = Path(cfg.indexer.llama_server_path) if cfg.indexer.llama_server_path \
            else local_runtime.ensure_runtime(cache_dir, quiet=True)
        weights_path, mmproj_path = local_runtime.ensure_model(cache_dir, tier.key, quiet=True)

    server = get_server(
        exe=exe, model_path=weights_path, mmproj_path=mmproj_path,
        gpu_layers=cfg.indexer.gpu_layers, server_url=server_url,
        log_path=Path(cfg.data_root) / "local_vlm_server.log" if not server_url else None,
    )

    windows = balanced_windows(frames, max(1, int(cfg.indexer.frames_per_call)))
    results = []
    for window in windows:
        parsed, usage = call_local_with_retry(server, window)
        results.append(parsed)
        if log_usage is not None:
            log_usage(model_label, len(window), {**usage, "tier": tier.key})

    merged = merge_index_results(results)

    flags, _stats = pixel_quality_flags([f["path"] for f in frames])
    merged["quality_flags"] = list(dict.fromkeys([*merged.get("quality_flags", []), *flags]))

    taxonomy = storage.get_categories()
    assigner = CategoryAssigner(taxonomy, cache_dir=cfg.embedding.cache_dir)
    slug, score = assigner.assign(clip_text_for_category(merged))
    merged["category_hint"] = slug
    merged["category_score"] = round(score, 4)
    merged["category_method"] = assigner.method

    segments = merged["segments"]
    if cfg.indexer.merge_similar_segments:
        n_before = len(segments)
        segments, n_merges = merge_similar_segments(segments)
        if n_merges:
            logger.info("local vlm: video %s merged %d over-segmented pair(s) (%d -> %d segments)",
                        video["id"], n_merges, n_before, len(segments))

    storage.write_index_result(
        video["id"], themes=merged["themes"], quality_flags=merged["quality_flags"],
        category_hint=slug, segments=segments, model=model_label,
    )
    return {**merged, "segments": segments}
