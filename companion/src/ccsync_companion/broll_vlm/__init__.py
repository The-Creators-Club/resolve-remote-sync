"""The local-VLM backend, VENDORED VERBATIM from the b-roll indexer.

The companion indexes b-roll on the editor's own GPU now (drag-and-drop on the
dashboard's b-roll page -> this machine crunches -> the clips and their index
go up to the NAS; docs/BROLL_INGEST_PLAN.md). The describing half of that is
`broll/indexer/broll_index/`'s local backend -- Qwen3-VL through a pinned
llama.cpp `llama-server` -- and it runs HERE unmodified:

    local_models.py    the tier catalogue (which GGUFs, which llama.cpp build,
                       how much VRAM each needs) -- every file pinned by sha256
    local_runtime.py   the sha256-verified, resumable fetcher + the GPU probe
    local_vlm.py       llama-server lifecycle, one HTTP call per window of
                       frames, the segment-merge post-process
    compact_format.py  the v7 compact prompt/grammar/parser, category
                       assignment, pixel-stat quality flags
    contract.py        the index contract every backend must produce

**These five files are copies and must not be edited here.** Each carries a
header ending in `# --- vendored content below, byte-identical ---`, and
everything under that line is the indexer's bytes. `tools/release.ps1` refuses
to build on drift and `server/tests/test_cross_component.py` pins the same
comparison in the suites, exactly as they already do for `ytdl_common.py`.
Fix a bug in `broll/indexer/broll_index/`, then re-copy the file in below the
marker.

Why copies and not an import: `broll_index` brings anthropic, xxhash, pyyaml,
requests and jieba with it -- ~50 MB and a licence surface inside a frozen
single-file exe on every editor machine -- for five modules that between them
need nothing but the stdlib and Pillow (already in the `tray` extra). The
module names are unchanged so their relative imports resolve inside this
sub-package.

`prompts/index_clip_v7_compact.md` is the ONE file here with no vendored
header: it is not code, it is the prompt text `compact_format.build_compact_prompt`
reads and sends to the model verbatim. A header would be part of what Qwen3-VL
receives, and it would differ between the indexer's calls and the companion's
-- the exact drift this vendoring exists to prevent. It is therefore an exact
whole-file copy, and its parity check compares the whole file (a strictly
stronger test than the marker one). The same two gates enforce it.

Nothing in this package is imported at tray start: `broll_vlm_sidecar.py` is
the companion's own front door to it (cache dir, free-space and GPU gates,
download progress, server lifecycle), and the sidecar imports these lazily so
a machine that never indexes anything never pays for them.
"""
