"""Model catalogue + memory-fit picker for the Mac leg of the eval (run_mac.sh).

Sizes are the published GGUF sizes (HF API, 2026-08-18). The official Qwen
repos ship only Q4_K_M / Q8_0 (+F16); the intermediate quants (Q5_K_M, Q6_K)
come from unsloth's repos — `source` in the pick says which, and the report
records it.

Fit rule (GB, decimal): model + mmproj + KV(ctx) + OVERHEAD <= budget, where
budget is Metal's recommendedMaxWorkingSetSize (what llama.cpp will actually
get without `sudo sysctl iogpu.wired_limit_mb`, which needs a password on the
Mac) minus a small margin. KV per token is f16 K+V over all layers
(layers * kv_heads * head_dim * 2 * 2 bytes). OVERHEAD covers the compute
buffers, the mmproj vision tower's activations for 9 images at ~1024 tokens
each, and llama-server itself.

usage:
  python3 mac_models.py pick --model 8b|30b|32b --budget-gb 28.5 [--ctx 16384] [--prefer q8|q4]
  python3 mac_models.py list
"""
from __future__ import annotations

import argparse
import json

OVERHEAD_GB = 2.5

# KV bytes/token: layers * kv_heads * head_dim * 2 (K,V) * 2 (f16)
KV_PER_TOKEN = {
    "8b": 36 * 8 * 128 * 4,        # 147 KB
    "30b": 48 * 4 * 128 * 4,       # 98 KB (MoE, 3B active — KV is small)
    "32b": 64 * 8 * 128 * 4,       # 262 KB
}

MMPROJ = {
    "8b": {"repo": "Qwen/Qwen3-VL-8B-Instruct-GGUF", "file": "mmproj-Qwen3VL-8B-Instruct-F16.gguf", "gb": 1.16},
    "30b": {"repo": "Qwen/Qwen3-VL-30B-A3B-Instruct-GGUF", "file": "mmproj-Qwen3VL-30B-A3B-Instruct-F16.gguf", "gb": 1.08},
    "32b": {"repo": "Qwen/Qwen3-VL-32B-Instruct-GGUF", "file": "mmproj-Qwen3VL-32B-Instruct-F16.gguf", "gb": 1.20},
}

# an unsloth quant is paired with unsloth's own mmproj (same conversion, but
# keep the pair from one repo rather than mixing repos)
UNSLOTH_MMPROJ_30B = {"repo": "unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF", "file": "mmproj-F16.gguf", "gb": 1.08}
UNSLOTH_MMPROJ_32B = {"repo": "unsloth/Qwen3-VL-32B-Instruct-GGUF", "file": "mmproj-F16.gguf", "gb": 1.20}

# best quant first; the picker walks down until one fits
CANDIDATES = {
    "8b": [
        {"quant": "Q8_0", "repo": "Qwen/Qwen3-VL-8B-Instruct-GGUF", "file": "Qwen3VL-8B-Instruct-Q8_0.gguf", "gb": 8.71, "source": "official"},
        {"quant": "Q4_K_M", "repo": "Qwen/Qwen3-VL-8B-Instruct-GGUF", "file": "Qwen3VL-8B-Instruct-Q4_K_M.gguf", "gb": 5.03, "source": "official"},
    ],
    "30b": [
        {"quant": "Q8_0", "repo": "Qwen/Qwen3-VL-30B-A3B-Instruct-GGUF", "file": "Qwen3VL-30B-A3B-Instruct-Q8_0.gguf", "gb": 32.48, "source": "official"},
        {"quant": "Q6_K", "repo": "unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF", "file": "Qwen3-VL-30B-A3B-Instruct-Q6_K.gguf", "gb": 25.09, "source": "unsloth", "mmproj": UNSLOTH_MMPROJ_30B},
        {"quant": "Q5_K_M", "repo": "unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF", "file": "Qwen3-VL-30B-A3B-Instruct-Q5_K_M.gguf", "gb": 21.73, "source": "unsloth", "mmproj": UNSLOTH_MMPROJ_30B},
        {"quant": "Q4_K_M", "repo": "Qwen/Qwen3-VL-30B-A3B-Instruct-GGUF", "file": "Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf", "gb": 18.56, "source": "official"},
    ],
    "32b": [
        {"quant": "Q6_K", "repo": "unsloth/Qwen3-VL-32B-Instruct-GGUF", "file": "Qwen3-VL-32B-Instruct-Q6_K.gguf", "gb": 26.88, "source": "unsloth", "mmproj": UNSLOTH_MMPROJ_32B},
        {"quant": "Q5_K_M", "repo": "unsloth/Qwen3-VL-32B-Instruct-GGUF", "file": "Qwen3-VL-32B-Instruct-Q5_K_M.gguf", "gb": 23.21, "source": "unsloth", "mmproj": UNSLOTH_MMPROJ_32B},
        {"quant": "Q4_K_M", "repo": "Qwen/Qwen3-VL-32B-Instruct-GGUF", "file": "Qwen3VL-32B-Instruct-Q4_K_M.gguf", "gb": 19.76, "source": "official"},
    ],
}

LABEL = {"8b": "Qwen3-VL-8B-Instruct", "30b": "Qwen3-VL-30B-A3B-Instruct", "32b": "Qwen3-VL-32B-Instruct"}
DIRNAME = {"8b": "qwen3-vl-8b", "30b": "qwen3-vl-30b-a3b", "32b": "qwen3-vl-32b"}


def kv_gb(model: str, ctx: int) -> float:
    return KV_PER_TOKEN[model] * ctx / 1e9


def mmproj_of(model: str, cand: dict) -> dict:
    return cand.get("mmproj") or MMPROJ[model]


def need_gb(model: str, cand: dict, ctx: int) -> float:
    return cand["gb"] + mmproj_of(model, cand)["gb"] + kv_gb(model, ctx) + OVERHEAD_GB


def pick(model: str, budget_gb: float, ctx: int, prefer: str = "") -> dict | None:
    cands = CANDIDATES[model]
    if prefer == "q4":
        cands = [c for c in cands if c["quant"].startswith("Q4")] or cands
    for c in cands:
        for try_ctx in ([ctx] if ctx <= 8192 else [ctx, 8192]):
            need = need_gb(model, c, try_ctx)
            if need <= budget_gb:
                return {**c, "ctx": try_ctx, "est_gb": round(need, 1), "mmproj": mmproj_of(model, c),
                        "label": f"{LABEL[model]}-{c['quant']}", "dir": f"{DIRNAME[model]}-{c['quant'].lower()}",
                        "model_key": model, "kv_gb": round(kv_gb(model, try_ctx), 2)}
    return None


def pick_or_force(model: str, budget_gb: float, ctx: int, prefer: str = "") -> dict:
    """pick(), or — when nothing fits — the smallest quant at 8k context flagged
    over_budget: Metal will still allocate past recommendedMaxWorkingSetSize
    (with a warning, and paging), so trying beats skipping the model."""
    got = pick(model, budget_gb, ctx, prefer)
    if got is not None:
        return {**got, "over_budget": False}
    c = CANDIDATES[model][-1]
    return {**c, "ctx": 8192, "est_gb": round(need_gb(model, c, 8192), 1), "mmproj": mmproj_of(model, c),
            "label": f"{LABEL[model]}-{c['quant']}", "dir": f"{DIRNAME[model]}-{c['quant'].lower()}",
            "model_key": model, "kv_gb": round(kv_gb(model, 8192), 2), "over_budget": True}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick")
    p.add_argument("--model", required=True, choices=sorted(CANDIDATES))
    p.add_argument("--budget-gb", type=float, required=True)
    p.add_argument("--ctx", type=int, default=16384)
    p.add_argument("--prefer", default="", choices=["", "q8", "q4"])
    p.add_argument("--force", action="store_true", help="never fail: smallest quant at 8k when nothing fits")
    sub.add_parser("list")
    args = ap.parse_args()
    if args.cmd == "list":
        for m, cs in CANDIDATES.items():
            for c in cs:
                print(f"{m:4s} {c['quant']:7s} {c['gb']:6.2f} GB  {c['source']:9s} {c['repo']}/{c['file']}  "
                      f"need@16k={need_gb(m, c, 16384):.1f}  need@8k={need_gb(m, c, 8192):.1f}")
        return
    got = pick_or_force(args.model, args.budget_gb, args.ctx, args.prefer) if args.force else         pick(args.model, args.budget_gb, args.ctx, args.prefer)
    if got is None:
        raise SystemExit(f"no {args.model} quant fits a {args.budget_gb} GB budget")
    print(json.dumps(got))


if __name__ == "__main__":
    main()
