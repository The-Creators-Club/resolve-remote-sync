"""Drive a llama-server over the selected clips and record one JSONL line per clip.

Arms:
  A  frames (native 960x540, 9 per call) + v7 compact format + GBNF grammar   <- the design under test
  B  same, no grammar (what the sampler alone does)
  C  the OLD path for reference: contact sheets + index_clip_v6 JSON prompt,
     parsed by claude_client.parse_claude_response (the earlier prototype's
     run_llamacpp.py path, 4 sheets per call, temperature 0)

Platform-neutral: the llama-server binary, model, mmproj, port and server args
come from `--config config.<host>.json` and/or CLI flags. Resumable: clips
already present in results/<arm>.jsonl are skipped. Never touches the indexer's
config, DB or archive — clips.json (from select_clips.py / make_bundle.py) is
the only input.

usage (base rig):
  python run_eval.py --arm A --config config.base-rig.json
  python run_eval.py --arm C --config config.base-rig.json --limit 25
usage (Mac, from run_mac.sh):
  python3 run_eval.py --arm A --config config.mac.json --model ~/.cache/ccsync-eval/... \
      --mmproj ... --model-label Qwen3-VL-8B-Instruct-Q8_0 --results-dir results-mac/qwen3-vl-8b-q8_0
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import platform
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from common import (COMPACT_SAMPLER, DEFAULT_CLIPS, FRAMES_PER_CALL, HERE, MAX_SHEETS_PER_CLIP,
                    SHEETS_PER_CALL, TOKENS_PER_FRAME_BUDGET, V6_SAMPLER, append_jsonl,
                    data_url, frame_abs, host_label, load_clips, load_host_config, read_jsonl)
from format import (CategoryAssigner, build_compact_prompt, build_grammar, clip_text_for_category,
                    parse_compact, pixel_quality_flags)
from broll_index.claude_client import (build_index_prompt, cap_sheets, chunk_sheets,  # noqa: E402
                                       merge_index_results, parse_claude_response)

ARMS = {
    "A": {"input": "frames", "format": "compact", "grammar": True},
    "B": {"input": "frames", "format": "compact", "grammar": False},
    "C": {"input": "sheets", "format": "v6json", "grammar": False},
}


# ---------------------------------------------------------------------------
# llama-server lifecycle
# ---------------------------------------------------------------------------

class Server:
    def __init__(self, url: str, proc: subprocess.Popen | None, log: Path | None):
        self.url = url.rstrip("/")
        self.proc = proc
        self.log = log
        self.load_s: float | None = None

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    def stop(self) -> None:
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _health(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=3) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def start_server(cfg: dict[str, Any], args: argparse.Namespace, results_dir: Path) -> Server:
    if args.server_url:
        s = Server(args.server_url, None, None)
        if not _health(s.url):
            raise SystemExit(f"--server-url {s.url} is not healthy")
        return s
    exe = args.llama_server or cfg.get("llama_server")
    model = args.model or cfg.get("model")
    mmproj = args.mmproj or cfg.get("mmproj")
    for k, v in (("llama-server", exe), ("model", model), ("mmproj", mmproj)):
        if not v:
            raise SystemExit(f"missing --{k} (or '{k.replace('-', '_')}' in the config)")
        if not Path(os.path.expanduser(v)).exists():
            raise SystemExit(f"{k} not found: {v}")
    port = int(args.port or cfg.get("port") or 8931)
    ctx = int(args.ctx or cfg.get("ctx") or 16384)
    imt = int(args.image_min_tokens if args.image_min_tokens is not None else cfg.get("image_min_tokens", 1024))
    cmd = [os.path.expanduser(exe), "-m", os.path.expanduser(model), "--mmproj", os.path.expanduser(mmproj),
           "--host", "127.0.0.1", "--port", str(port), "-c", str(ctx), "-ngl", str(cfg.get("ngl", 99)),
           "-np", "1", "--no-warmup"]
    if imt > 0:
        cmd += ["--image-min-tokens", str(imt)]
    cmd += [str(x) for x in (cfg.get("server_args") or [])]
    cmd += list(args.server_arg or [])
    results_dir.mkdir(parents=True, exist_ok=True)
    global _GPU_BASELINE_MB
    _GPU_BASELINE_MB = gpu_used_mb() if os.name == "nt" else None
    log = results_dir / f"llama-server.{args.arm}.log"
    env = dict(os.environ)
    print("starting:", " ".join(cmd), flush=True)
    logf = open(log, "a", encoding="utf-8")
    logf.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(cmd)}\n")
    logf.flush()
    creation = {}
    if os.name == "nt":
        creation["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP: our Ctrl-C does not hit it first
    proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, env=env, **creation)
    s = Server(f"http://127.0.0.1:{port}", proc, log)
    t0 = time.time()
    while time.time() - t0 < args.load_timeout:
        if proc.poll() is not None:
            raise SystemExit(f"llama-server exited early with code {proc.returncode}; see {log}")
        if _health(s.url):
            s.load_s = time.time() - t0
            print(f"llama-server ready in {s.load_s:.0f}s (pid {proc.pid})", flush=True)
            return s
        time.sleep(2)
    s.stop()
    raise SystemExit(f"llama-server did not become healthy within {args.load_timeout}s; see {log}")


_GPU_BASELINE_MB: float | None = None


def gpu_used_mb() -> float | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return float(out.strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return None


def proc_memory_mb(pid: int | None) -> float | None:
    """Memory the server is holding.

    NVIDIA: per-process figures are not exposed under Windows WDDM (nvidia-smi
    prints 'N/A' / nothing for --query-compute-apps), so this reports the
    card's total used memory minus what was used before the server started
    (`_GPU_BASELINE_MB`, sampled in start_server). Apple Silicon: RSS via ps —
    unified memory, so that is what Activity Monitor calls 'Memory' and it
    covers the Metal buffers.
    """
    if not pid:
        return None
    if os.name != "nt":
        try:
            out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout
            if out.strip():
                return float(out.strip()) / 1024.0
        except Exception:  # noqa: BLE001
            pass
    used = gpu_used_mb()
    if used is not None:
        return max(0.0, used - (_GPU_BASELINE_MB or 0.0))
    return None


# ---------------------------------------------------------------------------
# one call
# ---------------------------------------------------------------------------

def chat(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(f"{url}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def balanced_windows(items: list, per: int) -> list[list]:
    """ceil(n/per) windows of near-equal size (no orphan 1-frame last window)."""
    n = len(items)
    if n == 0:
        return []
    k = -(-n // per)
    base, extra = divmod(n, k)
    out, i = [], 0
    for w in range(k):
        size = base + (1 if w < extra else 0)
        out.append(items[i:i + size])
        i += size
    return out


def compact_content(prompt_static: str, table_tail: str, frames: list[dict], doc: dict) -> list[dict]:
    """[static instructions][frame table][F1 (tc):][img]...[Fn (tc):][img][answer cue].
    Static text first so llama-server's prompt cache reuses that prefix."""
    content = [{"type": "text", "text": prompt_static}, {"type": "text", "text": table_tail}]
    for i, f in enumerate(frames):
        content.append({"type": "text", "text": f"\nF{i + 1} ({f['tc']}):"})
        content.append({"type": "image_url", "image_url": {"url": data_url(frame_abs(doc, f["path"]))}})
    content.append({"type": "text", "text": "\nAnswer now: the S lines, then the T line."})
    return content


def run_window_compact(server: Server, doc: dict, frames: list[dict], args, sampler: dict) -> dict[str, Any]:
    prompt = build_compact_prompt(frames)
    static, _, tail = prompt.partition("## The frames for this call")
    tail = "## The frames for this call" + tail
    body = {
        "messages": [{"role": "user", "content": compact_content(static, tail, frames, doc)}],
        "max_tokens": TOKENS_PER_FRAME_BUDGET * len(frames),
        "cache_prompt": True,
        **sampler,
    }
    if args.grammar:
        body["grammar"] = build_grammar(len(frames))
    t0 = time.time()
    resp = chat(server.url, body, args.call_timeout)
    wall = time.time() - t0
    raw = resp["choices"][0]["message"]["content"] or ""
    rec = _call_record(resp, raw, wall, n_images=len(frames))
    try:
        parsed, problems = parse_compact(raw, frames)
        rec.update(parsed=parsed, problems=problems, valid=True, error="")
    except Exception as e:  # noqa: BLE001
        rec.update(parsed=None, problems=[], valid=False, error=str(e)[:300])
    return rec


def run_window_v6(server: Server, doc: dict, sheets: list[str], taxonomy_slugs: list[str], args, sampler: dict) -> dict[str, Any]:
    paths = [frame_abs(doc, s) for s in sheets]
    prompt = build_index_prompt(paths, taxonomy_slugs)
    content = [{"type": "image_url", "image_url": {"url": data_url(p)}} for p in paths]
    content.append({"type": "text", "text": prompt})
    body = {"messages": [{"role": "user", "content": content}],
            "max_tokens": 400 * len(paths), "cache_prompt": True, **sampler}
    t0 = time.time()
    resp = chat(server.url, body, args.call_timeout)
    wall = time.time() - t0
    raw = resp["choices"][0]["message"]["content"] or ""
    rec = _call_record(resp, raw, wall, n_images=len(paths))
    try:
        parsed = parse_claude_response(raw)
        rec.update(parsed=parsed, problems=[], valid=True, error="")
    except Exception as e:  # noqa: BLE001
        rec.update(parsed=None, problems=[], valid=False, error=str(e)[:300])
    return rec


def _call_record(resp: dict, raw: str, wall: float, n_images: int) -> dict[str, Any]:
    usage = resp.get("usage") or {}
    t = resp.get("timings") or {}
    return {
        "n_images": n_images,
        "raw": raw,
        "finish_reason": (resp.get("choices") or [{}])[0].get("finish_reason"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "wall_s": round(wall, 2),
        # llama-server timings: prompt_ms is prompt processing INCLUDING the
        # mmproj image encode; predicted_ms is the decode.
        "prompt_ms": t.get("prompt_ms"), "predicted_ms": t.get("predicted_ms"),
        "prompt_n": t.get("prompt_n"), "predicted_n": t.get("predicted_n"),
        "prompt_per_second": t.get("prompt_per_second"),
        "predicted_per_second": t.get("predicted_per_second"),
        "cache_n": t.get("cache_n"),
    }


# ---------------------------------------------------------------------------
# main loop
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", required=True, choices=sorted(ARMS))
    ap.add_argument("--clips", type=Path, default=DEFAULT_CLIPS)
    ap.add_argument("--results-dir", type=Path, default=HERE / "results")
    ap.add_argument("--config", type=Path, default=None, help="config.<host>.json")
    ap.add_argument("--llama-server"); ap.add_argument("--model"); ap.add_argument("--mmproj")
    ap.add_argument("--model-label", help="e.g. Qwen3-VL-4B-Instruct-Q4_K_M (defaults to the GGUF stem)")
    ap.add_argument("--port", type=int); ap.add_argument("--ctx", type=int)
    ap.add_argument("--image-min-tokens", type=int, default=None, help="0 disables the flag")
    ap.add_argument("--server-arg", action="append", help="extra llama-server arg (repeatable)")
    ap.add_argument("--server-url", help="attach to a running llama-server instead of starting one")
    ap.add_argument("--load-timeout", type=float, default=1200)
    ap.add_argument("--call-timeout", type=float, default=900)
    ap.add_argument("--clip-time-cap", type=float, default=0,
                    help="seconds; when exceeded the remaining windows of the clip are skipped "
                         "and the clip is recorded as partial (for the slow 32B)")
    ap.add_argument("--frames-per-call", type=int, default=FRAMES_PER_CALL)
    ap.add_argument("--sheets-per-call", type=int, default=SHEETS_PER_CALL)
    ap.add_argument("--no-grammar", action="store_true", help="force the grammar off (arm A becomes B-like)")
    ap.add_argument("--limit", type=int, default=0, help="first N clips of clips.json (0 = all)")
    ap.add_argument("--ids", type=int, nargs="*", help="only these clip ids")
    ap.add_argument("--retry-errors", action="store_true", help="re-run clips recorded with status=error")
    ap.add_argument("--temperature", type=float); ap.add_argument("--repeat-penalty", type=float)
    ap.add_argument("--category", choices=["auto", "fastembed", "tfidf", "none"], default="auto")
    args = ap.parse_args()

    arm = ARMS[args.arm]
    args.grammar = arm["grammar"] and not args.no_grammar
    cfg = load_host_config(args.config)
    doc = load_clips(args.clips)
    clips = doc["clips"]
    if args.ids:
        want = set(args.ids)
        clips = [c for c in clips if c["id"] in want]
    if args.limit:
        clips = clips[:args.limit]

    results_dir = args.results_dir
    out_path = results_dir / f"{args.arm}.jsonl"
    done = {r["id"]: r for r in read_jsonl(out_path)}
    if args.retry_errors:
        done = {k: v for k, v in done.items() if v.get("status") != "error"}
    todo = [c for c in clips if c["id"] not in done]
    print(f"arm {args.arm}: {len(clips)} clips requested, {len(done)} already in {out_path.name}, {len(todo)} to run",
          flush=True)

    sampler = dict(V6_SAMPLER if arm["format"] == "v6json" else COMPACT_SAMPLER)
    if args.temperature is not None:
        sampler["temperature"] = args.temperature
    if args.repeat_penalty is not None:
        sampler["repeat_penalty"] = args.repeat_penalty

    model_path = args.model or cfg.get("model") or ""
    model_label = args.model_label or cfg.get("model_label") or Path(model_path).stem
    meta = {
        "arm": args.arm, **arm, "grammar_used": args.grammar,
        "host": host_label(), "host_label": cfg.get("host_label", ""), "platform": platform.platform(),
        "runtime_label": cfg.get("runtime_label", "llama.cpp llama-server"),
        "model_label": model_label, "model": model_path, "mmproj": args.mmproj or cfg.get("mmproj"),
        "ctx": args.ctx or cfg.get("ctx", 16384), "image_min_tokens": args.image_min_tokens if args.image_min_tokens is not None else cfg.get("image_min_tokens", 1024),
        "frames_per_call": args.frames_per_call, "sheets_per_call": args.sheets_per_call,
        "sampler": sampler, "clips_json": str(args.clips), "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / f"{args.arm}.meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")

    if not todo:
        print("nothing to do")
        return

    taxonomy = doc.get("taxonomy") or []
    slugs = [t["slug"] for t in taxonomy]
    assigner = None
    if args.category != "none" and arm["format"] == "compact":
        assigner = CategoryAssigner(taxonomy, prefer=args.category)
        print(f"category assigner: {assigner.method}"
              + (f" (fastembed unavailable: {assigner.fastembed_error})" if assigner.fastembed_error else ""),
              flush=True)

    server = start_server(cfg, args, results_dir)
    atexit.register(server.stop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: (server.stop(), sys.exit(130)))
        except Exception:  # noqa: BLE001
            pass
    meta["load_s"] = server.load_s
    (results_dir / f"{args.arm}.meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")

    peak_mem = 0.0
    t_run0 = time.time()
    for n, clip in enumerate(todo, 1):
        cid = clip["id"]
        t_clip0 = time.time()
        calls: list[dict[str, Any]] = []
        status = "ok"
        err = ""
        try:
            if arm["input"] == "frames":
                windows = balanced_windows(clip["frames"], args.frames_per_call)
            else:
                sheets = cap_sheets(list(clip["sheets"]), MAX_SHEETS_PER_CLIP)
                windows = chunk_sheets(sheets, args.sheets_per_call)
            for wi, window in enumerate(windows):
                if args.clip_time_cap and wi > 0 and (time.time() - t_clip0) > args.clip_time_cap:
                    status = "partial"
                    err = f"clip time cap {args.clip_time_cap}s hit after {wi}/{len(windows)} windows"
                    break
                if arm["input"] == "frames":
                    rec = run_window_compact(server, doc, window, args, sampler)
                    rec["frame_idx"] = [f["i"] for f in window]
                else:
                    rec = run_window_v6(server, doc, window, slugs, args, sampler)
                    rec["sheets"] = list(window)
                rec["window"] = wi
                calls.append(rec)
                m = proc_memory_mb(server.pid)
                if m:
                    peak_mem = max(peak_mem, m)
        except urllib.error.URLError as e:
            status, err = "error", f"server call failed: {e}"[:300]
        except Exception as e:  # noqa: BLE001
            status, err = "error", f"{type(e).__name__}: {e}"[:300]

        valid_calls = [c for c in calls if c.get("valid")]
        merged = merge_index_results([c["parsed"] for c in valid_calls]) if valid_calls else None
        if merged is not None and arm["format"] == "compact":
            flags, fstats = pixel_quality_flags([frame_abs(doc, f["path"]) for f in clip["frames"]])
            merged["quality_flags"] = flags
            merged["frame_stats"] = fstats
            if assigner is not None:
                slug, score = assigner.assign(clip_text_for_category(merged))
                merged["category_hint"] = slug
                merged["category_score"] = round(score, 4)
                merged["category_method"] = assigner.method
        if status == "ok" and calls and not valid_calls:
            status = "invalid"
        elif status == "ok" and calls and len(valid_calls) < len(calls):
            status = "partial_invalid"

        wall = time.time() - t_clip0
        out = {
            "id": cid, "stratum": clip.get("stratum"), "arm": args.arm, "model_label": model_label,
            "status": status, "error": err,
            "n_frames": len(clip["frames"]), "n_windows": len(calls),
            "n_valid_windows": len(valid_calls),
            "wall_s": round(wall, 2),
            "prompt_tokens": sum(c.get("prompt_tokens") or 0 for c in calls),
            "completion_tokens": sum(c.get("completion_tokens") or 0 for c in calls),
            "prompt_ms": sum(c.get("prompt_ms") or 0 for c in calls),
            "predicted_ms": sum(c.get("predicted_ms") or 0 for c in calls),
            "peak_mem_mb": round(peak_mem) if peak_mem else None,
            "result": merged,
            "calls": calls,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        append_jsonl(out_path, out)
        elapsed = time.time() - t_run0
        eta = elapsed / n * (len(todo) - n)
        nseg = len(merged["segments"]) if merged else 0
        tg = [c.get("predicted_per_second") for c in calls if c.get("predicted_per_second")]
        tg_s = f"{sum(tg)/len(tg):.0f}" if tg else "-"
        print(f"[{args.arm}] {n}/{len(todo)} clip {cid} ({clip.get('stratum')}): {status} "
              f"{len(calls)} calls, {nseg} segs, {wall:.0f}s, in={out['prompt_tokens']} "
              f"out={out['completion_tokens']} tg={tg_s} tok/s | mem={peak_mem:.0f}MB "
              f"eta={eta/60:.0f}min {err[:80]}", flush=True)

    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    meta["peak_mem_mb"] = round(peak_mem) if peak_mem else None
    meta["run_wall_s"] = round(time.time() - t_run0)
    (results_dir / f"{args.arm}.meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    server.stop()
    print(f"arm {args.arm} done: {len(todo)} clips in {(time.time()-t_run0)/60:.1f} min, peak mem {peak_mem:.0f} MB")


if __name__ == "__main__":
    main()
