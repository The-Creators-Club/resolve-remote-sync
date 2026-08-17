"""Prototype: run the b-roll indexer's index_clip_v6 prompt against a local VLM
(Qwen3-VL-4B-Instruct via transformers) on the SAME contact sheets the archive
was indexed with, and validate the answer with the indexer's own contract parser.

Read-only against the repo and the DB. Nothing here is product code.

usage: python run_local_vlm.py --ids 8724 13454 2555 5495 [--device cpu|cuda] [--max-sheets 3]
"""
from __future__ import annotations

import argparse, json, os, sqlite3, sys, time
from pathlib import Path

REPO = Path(r"E:/Projects/resolve-remote-sync")
sys.path.insert(0, str(REPO / "broll" / "indexer"))
from broll_index.claude_client import build_index_prompt, parse_claude_response  # noqa: E402

DATA_ROOT = Path(r"E:/broll-queue")
DB = DATA_ROOT / "broll.db"
MODEL_ID = os.environ.get("VLM_MODEL", "Qwen/Qwen3-VL-4B-Instruct")


def taxonomy_slugs() -> list[str]:
    c = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    return [r[0] for r in c.execute("select slug from categories order by slug")]


def sheets_for(vid: int, cap: int) -> list[Path]:
    meta = json.loads((DATA_ROOT / "sheets" / str(vid) / "frames.json").read_text(encoding="utf-8"))
    paths = [Path(p) for p in meta["sheets"]]
    return paths[:cap]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", type=int, nargs="+", required=True)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--max-sheets", type=int, default=3)
    ap.add_argument("--max-new-tokens", type=int, default=900)
    ap.add_argument("--out", default="local_vlm_results.json")
    args = ap.parse_args()

    import torch
    from PIL import Image
    from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() and torch.cuda.mem_get_info()[0] > 9 * 2**30 else "cpu"
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    torch.set_num_threads(max(os.cpu_count() - 2, 4))
    print(f"model={MODEL_ID} device={device} dtype={dtype} threads={torch.get_num_threads()}", flush=True)

    t0 = time.time()
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = Qwen3VLForConditionalGeneration.from_pretrained(MODEL_ID, dtype=dtype, device_map=device)
    model.eval()
    load_s = time.time() - t0
    print(f"loaded in {load_s:.0f}s", flush=True)

    tax = taxonomy_slugs()
    results = {"model": MODEL_ID, "device": device, "dtype": str(dtype), "load_s": load_s, "clips": {}}
    for vid in args.ids:
        sheets = sheets_for(vid, args.max_sheets)
        prompt = build_index_prompt(sheets, tax)
        images = [Image.open(p).convert("RGB") for p in sheets]
        content = [{"type": "image", "image": str(p)} for p in sheets] + [{"type": "text", "text": prompt}]
        messages = [{"role": "user", "content": content}]
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text], images=images, return_tensors="pt").to(device)
        n_in = int(inputs["input_ids"].shape[1])
        if device == "cuda":
            torch.cuda.reset_peak_memory_stats()
        t1 = time.time()
        with torch.inference_mode():
            out = model.generate(**inputs, max_new_tokens=args.max_new_tokens, do_sample=False)
        gen_s = time.time() - t1
        new_tokens = out[0, n_in:]
        raw = processor.batch_decode([new_tokens], skip_special_tokens=True)[0]
        n_out = int(new_tokens.shape[0])
        peak = torch.cuda.max_memory_allocated() / 2**30 if device == "cuda" else None
        try:
            parsed = parse_claude_response(raw)
            ok, err = True, ""
        except Exception as e:  # noqa: BLE001
            parsed, ok, err = None, False, str(e)
        rec = {
            "sheets": [str(p) for p in sheets], "n_sheets": len(sheets),
            "input_tokens": n_in, "output_tokens": n_out, "gen_s": round(gen_s, 1),
            "tok_per_s_out": round(n_out / gen_s, 2) if gen_s else None,
            "peak_vram_gb": peak, "valid_contract": ok, "contract_error": err,
            "raw": raw, "parsed": parsed,
        }
        results["clips"][vid] = rec
        print(f"video {vid}: {len(sheets)} sheets, in={n_in} out={n_out} tokens, {gen_s:.0f}s, "
              f"valid={ok} {err[:120]}", flush=True)
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
