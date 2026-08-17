"""Prototype, runtime #2: the same index_clip_v6 prompt through llama.cpp's
OpenAI-compatible llama-server (what Ollama wraps), Qwen3-VL-4B Q4_K_M GGUF,
optionally with a JSON-schema constrained decode.

usage: python run_llamacpp.py --ids ... [--schema] [--ngl 0]
Assumes llama-server.exe is in ./llamacpp and the GGUFs are in HF_HOME.
"""
from __future__ import annotations

import argparse, base64, glob, json, os, sqlite3, subprocess, sys, time, urllib.request
from pathlib import Path

REPO = Path(r"E:/Projects/resolve-remote-sync")
sys.path.insert(0, str(REPO / "broll" / "indexer"))
from broll_index.claude_client import build_index_prompt, parse_claude_response, QUALITY_FLAG_VOCAB  # noqa: E402

DATA_ROOT = Path(r"E:/broll-queue")
DB = DATA_ROOT / "broll.db"
HERE = Path(__file__).parent
HF = Path(os.environ.get("HF_HOME", os.path.expandvars(r"%LOCALAPPDATA%\ccsync\hf-cache")))
PORT = 8931

# The contract in claude_client.validate_contract, as a JSON schema for the grammar.
SCHEMA = {
    "type": "object",
    "properties": {
        "themes": {"type": "array", "items": {"type": "string"}},
        "category_hint": {"type": ["string", "null"]},
        "quality_flags": {"type": "array", "items": {"type": "string", "enum": sorted(QUALITY_FLAG_VOCAB)}},
        "segments": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "t_start": {"type": "number"}, "t_end": {"type": "number"},
                "description": {"type": "string"},
                "objects": {"type": "array", "items": {"type": "string"}},
                "setting": {"type": "string"}, "motion": {"type": "string"},
                "onscreen_text": {"type": "string"}, "onscreen_text_en": {"type": "string"},
            },
            "required": ["t_start", "t_end", "description", "objects", "setting", "motion",
                         "onscreen_text", "onscreen_text_en"],
        }},
    },
    "required": ["themes", "category_hint", "quality_flags", "segments"],
}


def gguf(pattern: str) -> str:
    hits = glob.glob(str(HF / "hub" / "models--Qwen--Qwen3-VL-4B-Instruct-GGUF" / "snapshots" / "*" / pattern))
    if not hits:
        raise SystemExit(f"no gguf matching {pattern}")
    return hits[0]


def taxonomy_slugs() -> list[str]:
    c = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    return [r[0] for r in c.execute("select slug from categories order by slug")]


def sheets_for(vid: int, cap: int) -> list[Path]:
    meta = json.loads((DATA_ROOT / "sheets" / str(vid) / "frames.json").read_text(encoding="utf-8"))
    return [Path(p) for p in meta["sheets"]][:cap]


def data_url(p: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()


def wait_ready(timeout=600):
    t = time.time()
    while time.time() - t < timeout:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(2)
    raise SystemExit("llama-server did not become ready")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", type=int, nargs="+", required=True)
    ap.add_argument("--max-sheets", type=int, default=3)
    ap.add_argument("--schema", action="store_true")
    ap.add_argument("--ngl", type=int, default=0)
    ap.add_argument("--threads", type=int, default=max(os.cpu_count() - 2, 4))
    ap.add_argument("--out", default="results_llamacpp.json")
    args = ap.parse_args()

    model = gguf("Qwen3VL-4B-Instruct-Q4_K_M.gguf")
    mmproj = gguf("mmproj-*.gguf")
    cmd = [str(HERE / os.environ.get("LLAMA_DIR","llamacpp") / "llama-server.exe"), "-m", model, "--mmproj", mmproj,
           "--port", str(PORT), "-ngl", str(args.ngl), "-t", str(args.threads),
           "-c", "16384", "--no-warmup"]
    print(" ".join(cmd), flush=True)
    srv = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=open(HERE / "llama-server.log", "w"))
    try:
        t0 = time.time(); wait_ready(); load_s = time.time() - t0
        print(f"server ready in {load_s:.0f}s", flush=True)
        tax = taxonomy_slugs()
        results = {"runtime": "llama.cpp b10470 llama-server", "model": Path(model).name,
                   "mmproj": Path(mmproj).name, "ngl": args.ngl, "threads": args.threads,
                   "schema_constrained": args.schema, "load_s": load_s, "clips": {}}
        for vid in args.ids:
            sheets = sheets_for(vid, args.max_sheets)
            prompt = build_index_prompt(sheets, tax)
            content = [{"type": "image_url", "image_url": {"url": data_url(p)}} for p in sheets]
            content.append({"type": "text", "text": prompt})
            body = {"messages": [{"role": "user", "content": content}],
                    "temperature": 0, "max_tokens": 1200}
            if args.schema:
                body["response_format"] = {"type": "json_schema", "json_schema": {"schema": SCHEMA}}
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                         data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            t1 = time.time()
            with urllib.request.urlopen(req, timeout=3600) as r:
                resp = json.load(r)
            gen_s = time.time() - t1
            raw = resp["choices"][0]["message"]["content"]
            usage = resp.get("usage", {})
            timings = resp.get("timings", {})
            try:
                parsed = parse_claude_response(raw); ok, err = True, ""
            except Exception as e:  # noqa: BLE001
                parsed, ok, err = None, False, str(e)
            rec = {"sheets": [str(p) for p in sheets], "n_sheets": len(sheets),
                   "input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
                   "gen_s": round(gen_s, 1), "timings": timings,
                   "valid_contract": ok, "contract_error": err, "raw": raw, "parsed": parsed}
            results["clips"][vid] = rec
            print(f"video {vid}: {len(sheets)} sheets in={usage.get('prompt_tokens')} "
                  f"out={usage.get('completion_tokens')} {gen_s:.0f}s valid={ok} {err[:100]} "
                  f"pp={timings.get('prompt_per_second')} tg={timings.get('predicted_per_second')}", flush=True)
            Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    finally:
        srv.terminate()


if __name__ == "__main__":
    main()
