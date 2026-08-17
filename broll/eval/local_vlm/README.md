# Local VLM indexing eval (`broll/eval/local_vlm/`)

The ~100-clip eval that `broll/docs/local-indexing-options-2026-08-17.md` §3
step 1 asked for: can a local Qwen3-VL through llama.cpp replace the Haiku
`claude` stage? Runs on the base rig (RTX 3080, 4B Q4) and on an Apple
Silicon Mac (8B / 30B-A3B / 32B) against the SAME clips and the SAME Haiku
baseline. Nothing here touches the indexer's code, config, DB or the archive:
`select_clips.py` reads `broll.db` read-only and the frames under
`E:\broll-queue\sheets\<id>\frames\` are only ever read.

| file | role |
|---|---|
| `select_clips.py` | picks ~100 clips (25 with on-screen text, 25 multi-shot ≥5 segments, 25 simple ≤2, 25 random; ≤45 frames each), verifies frames on disk, writes `clips.json` with the Haiku baseline and the taxonomy |
| `prompt_v7_compact.md` | the compact prompt: frames labelled F1..Fn with timecodes in the text; output `S <F-range> \| desc \| obj;obj \| text // english` lines + one `T theme;theme` line |
| `format.py` | `build_grammar` (GBNF: F ids limited to the window, ≤ n S lines, one T line, bounded fields, then EOS), `parse_compact` (tolerant → the v6 contract dict, run through `claude_client.validate_contract`), `CategoryAssigner` (nearest neighbour: fastembed MiniLM when importable, else TF-IDF), `pixel_quality_flags` (Pillow exposure stats) |
| `run_eval.py` | drives llama-server; arms **A** frames+compact+grammar, **B** no grammar, **C** old sheets+v6 JSON; resumable JSONL per arm; records raw text, tokens, encode/decode timings, memory |
| `score.py` | agreement with Haiku: segment IoU-F1, coverage, objects Jaccard + head-noun recall, OCR similarity, category, themes, speed, validity; `report.md` + `summary.json`, 20 largest disagreements with frame paths |
| `compare.py` | arm-A metrics side by side across hosts/models |
| `make_bundle.py` | portable input bundle (frames + sheets + clips.json, ~110 MB zip) for the Mac |
| `mac_models.py` | model catalogue + memory-fit quant picker for the Mac |
| `run_overnight.ps1` / `status.ps1` | Windows detached launcher (waits for Resolve to close and ≥6 GB free) / progress |
| `run_mac.sh` / `status_mac.sh` | Mac launcher (installs llama.cpp b10470, downloads GGUFs into `~/.cache/ccsync-eval`, runs 8B → 30B-A3B → 32B) / progress |
| `config.base-rig.json`, `config.mac.json` | host-level knobs (binary, port, ctx, image-min-tokens) |

Outputs (`results/`, `results-mac/`, `bundle*`) are git-ignored; copy a
finished `report.md` into `broll/docs/` when it is worth keeping.

## Windows

```powershell
cd broll\eval\local_vlm
python select_clips.py                       # -> clips.json (needs E:\broll-queue\broll.db, or --db / BROLL_DB_PATH)
powershell -NoProfile -ExecutionPolicy Bypass -File run_overnight.ps1     # detached; waits for the GPU
powershell -NoProfile -ExecutionPolicy Bypass -File status.ps1            # progress
python score.py --results-dir results        # re-score by hand
```

## Mac

```bash
python make_bundle.py                        # on the base rig -> bundle.zip; copy it to the Mac
cd ~/resolve-remote-sync/broll/eval/local_vlm && mkdir -p results-mac
caffeinate -i nohup nice -n 10 ./run_mac.sh --bundle ~/ccsync-eval-bundle.zip > results-mac/run.log 2>&1 &
./status_mac.sh
```

Then, back on the base rig (fastembed category assignment for both):

```powershell
python score.py --results-dir results-mac\qwen3-vl-8b-q8_0 --clips bundle\clips.json --recategorize
python compare.py results results-mac\qwen3-vl-8b-q8_0 results-mac\qwen3-vl-30b-a3b-q5_k_m results-mac\qwen3-vl-32b-q4_k_m
```
