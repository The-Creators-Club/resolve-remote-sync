# B-roll ingest from the dashboard — drag-and-drop → local indexing → NAS

Written 2026-08-18. Design for the feature the product owner described:

> For b-roll ingest it should be drag and drop to the dashboard b-roll
> section. You can drag clips in, and you can drag folders in. This shows a
> preview of all the clips about to be processed, lets the user pick the
> settings — which model to use, etc — and clicking Run prompts the user's
> local companion to start crunching through the clips: ffmpeg first, then
> indexing. Progress is visible in the companion (tray) and in the dashboard
> b-roll section; admins see which computers are indexing and their progress.
> After indexing, the clips are synced to Assets/B-roll Archive on the NAS
> and the clips and database are updated automatically.

Decisions taken with the owner (2026-08-18): **intake = both** drag-and-drop
(the page streams dropped files to the companion — browsers expose no local
paths) **and** a "Choose from this computer…" native picker (real paths,
index in place); **upload to the NAS is automatic per clip** (records +
poster/sprite/proxy first, original behind, pause toggle); **transcription is
phase 2** (whisper.cpp sidecar later; v1 = visuals + on-screen text via the
local Qwen backend); **scheduling is idle-only like the proxy generator**
("Run" queues; runs when the editor is away; "start now, don't wait"
override; pauses when the editor returns). Models = the local Qwen3-VL tiers
**Good** (4B, 8 GB VRAM) / **Best** (8B, 12 GB VRAM) —
`broll/docs/indexing-local.md`, chosen per site in Settings and published as
`indexer.model_tier` in `GET /api/v1/site`.

**Owner review, 2026-08-18 (supersedes the older wording below where they
differ):** (a) **indexing takes precedence over proxy generation** — while a
batch is crunching, `ProxyGenerator` is *blocked* (its existing `blocked_fn`
seam; state "waiting: indexing b-roll first"), not the other way round;
(b) the batch settings form carries a **run mode** beside the model tier:
**Foreground** (runs now, ignores the idle and Resolve-open gates; free
space / drive / model gates still apply) or **Only when idle** (the proxy
generator's behaviour); "start now" becomes that choice; (c) if a batch is
run on a machine whose GPU cannot fit the chosen tier, the companion refuses
and **warns in the tray** (balloon + a menu line naming the VRAM: "Can't
index b-roll: Best needs 12 GB VRAM, this GPU has 8 GB — choose Good") as
well as in the page.

Related: `broll/SPEC.md` (data layout, ingest API), `docs/LOOPBACK_API.md`,
`docs/YTDL_LOCAL_DOWNLOAD.md` (the requester-first job model this copies),
`docs/INDEXERS.md`, `docs/ZERO_TOUCH_PLAN.md`.

## 0. Ground truths (verified in the tree, 2026-08-18)

- `broll/web/app/routes_ingest.py` accepts **records, not files** (`/api/ingest/{video,index,moved,shares}`, `X-Ingest-Token`, dashboard body cap 4 MiB). `/index` inserts segments with empty `search_norm` (`http_backend.py:163-166`: search_norm "is not supported over the ingest API"), so anything indexed over HTTP is keyword-searchable only after a base-rig `embed` pass — this plan fixes that class server-side.
- `videos.hash` = xxh64(first 8 MiB + last 8 MiB + size) (`broll_index/hashing.py`); dedupe against the index must produce **this** digest.
- Own-footage membership = `search.creators_shares()` = env `BROLL_CREATORS_SHARES` ∪ `share_roots.source='proxies'` — ingested camera originals are `source='originals'`, so `share_roots` needs a `collection` column or ingested shoots file under Downloads.
- `videos.archive_path` = `<folder>/Proxy/<stem>.mp4`; the original sits beside `Proxy/`; `routes_api._insert_target` finds it by stem; `routes_media` serves `<BROLL_DATA_ROOT>/<archive_path>` and `posters|sprites/{id}.jpg`. `BROLL_DATA_ROOT` **is** the NAS archive, so the server can verify uploads by `stat()`.
- Companion loopback (`broll_server.py`): Host + Origin vet → POST needs allowed Origin or `X-CCSync-Loopback` **and** JSON → `MAX_BODY_BYTES = 256 KiB`. `broll_fetch.py` = long-running action registry (UI re-POSTs every 1.5 s) using `rclone copyto` DOWN from `<remote>:<remote_root>/Assets/B-roll Archive/…`; no upload counterpart exists, but the companion has rclone + the SFTP remote and editors are in `editors` (2770 setgid on the archive dir).
- `proxy_gen.ProxyGenerator` = the idle-only local ffmpeg batch: 15 s tick, `_gate()` priority, `idle.py` ("None means not idle"), NVENC→one CPU retry, `.partial` first-writer-wins, free-space floor, `gap()` (tray, bool `encoding`, detail tooltip-only) / `coverage()` (reporter) / `block_reason()`; tray lines `tray.py:2337-2396`, `_proxy_fingerprint`, `_with_proxy_suffix`.
- `ytdl_executor.py` + `ytdl/web/ytdlweb/routes_fleet.py` = the dashboard-dispatched job model: browser passes only a job id to the loopback after a 1 s capability probe; companion claims on fleet routes (`X-CCSync-Token` + signed `X-CCSync-Identity`), heartbeats, `LeaseLost` on 410; dashboard `login_gate` carve-out regex `app.py:562-564`.
- Reporter sections ride every tick as cached zero-I/O getters; **`ReportIn` does not declare `proxy_coverage`/`youtube_import`, so pydantic drops them today** (fixed in passing). Fleet-grid surface = the `sync_guard` path (`SyncGuardIn` → `flatten` → `machine_state` columns → `fetch_*_map` → chip). The report **response** (`commands.halt`) is the server→companion push channel.
- Vendoring precedent: `companion/src/ccsync_companion/ytdl_common.py` (verbatim copy + marker, pinned by `tools/release.ps1` and `server/tests/test_cross_component.py`).
- Local VLM modules (`broll_index/{local_models,local_runtime,local_vlm,compact_format}.py`): `describe_video(cfg, storage, video, …)` reads `cfg.indexer.*`, `cfg.data_root`, `storage.get_categories()/write_index_result()`; needs `<data_root>/sheets/{id}/frames.json` + `frames/`; `ensure_runtime/ensure_model` print progress to **stderr** (None in the windowed exe); `start_server` lacks `CREATE_NO_WINDOW`; `probe_gpu(runner=)` is injectable.
- `sidecar_tools.ensure()` installs ffmpeg/ffprobe **only when `youtube_download` is on**; ingest needs ffmpeg regardless. Companion `ffmpeg_tools.preview_proxy_cmd` lacks the indexer's `-pix_fmt yuv420p` (10-bit FX3 sources) — real drift, fixed here.

## 1. Architecture and sequence

Three parties: **browser** (b-roll SPA under the dashboard) — **companion** (loopback 8899 + background orchestrator) — **dashboard / broll web** (session routes for the SPA, fleet routes for the companion). The browser only *dispatches*; work orders come from the server under the fleet token; the companion crunches locally and uploads with rclone; the server flips rows live only after it has stat'ed the files in `BROLL_DATA_ROOT`.

1. **Drop / pick.** Drop zone on the b-roll page (music `wireDropzone` pattern) traverses folders (`webkitGetAsEntry`), builds a preview list with canvas thumbnails; or "Choose from this computer…" → `POST 127.0.0.1:8899/broll/ingest/pick` → native picker → real paths (index in place).
2. **Prepare (companion).** `POST /broll/ingest/prepare` → staging dir inside `local_root` (`<local_root>/Assets/B-roll Archive/.ingest/<staging_id>/`, `loopback_guard.is_within` + `root_guard.probe_root`, free-space floor) → per-item upload slots. Dropped files stream to `PUT /broll/ingest/upload/{staging_id}/{item}` (octet-stream + `X-CCSync-Ingest` header ⇒ preflight ⇒ Origin allow-list; per-route cap = declared size; `.partial` → rename). A prepare thread ffprobes + xxh64-hashes every item; SPA polls `GET /broll/ingest/progress`.
3. **Pre-check (server).** `POST ../api/ingest-batches/precheck {name,size,hash}` → per item `duplicate_of` (by `videos.hash`) and the **final allocated name** in the target shoot folder (collision-safe, `_2` rule of `build_archive.claim_name`).
4. **Settings + Run.** Form: model tier (default from `../api/v1/site` `indexer.model_tier`; tiers the GPU cannot fit disabled with the reason), shoot name, keep sub-folders, upload originals (on), **run mode: Only when idle / Foreground** (default idle), transcription (disabled: phase 2). Run → `POST ../api/ingest-batches` (session; creates rows, state `queued`, returns `batch_uid`) → `POST /broll/ingest/run {batch_uid, staging_id, start_now}` → companion **claims** the batch on the fleet route, receives the manifest (video ids, share/rel_path, archive folder+stem, taxonomy, settings, lease), persists `~/.ccsync/state/broll_ingest.json`, answers 202. Run is also the consent moment: missing ffmpeg / llama-server / model → download starts (free-space checked, progress in tray + SPA; the SPA confirms the byte count first when a model must be fetched); the batch is `waiting-for-model` until verified.
5. **Gate.** 15 s tick; order mirrors `proxy_gen._gate`: disabled → drive absent → paused → misconfigured → no ffmpeg → no model → tier does not fit this GPU (tray warning) → nothing to do → [idle mode only: user active → Resolve open] → running. While running, the proxy generator is blocked (`blocked_fn`), never the reverse. Editor returns → llama-server stopped (VRAM freed), in-flight ffmpeg killed (`.partial` discarded), item back to its last checkpoint. Heartbeat every 30 s; 410 = stop quietly.
6. **Crunch per item** (checkpointed): proxy 540p (NVENC → CPU retry) → sprite + poster from the proxy → scene-detect + frames → describe (vendored `local_vlm.describe_video` against a companion-managed llama-server) → `POST …/items/{uid}/result` (server writes segments, computes `search_norm`, status `indexed`).
7. **Upload** (separate thread, starts as each item finishes; pause toggle): `rclone copyto` up: `posters/{id}.jpg`, `sprites/{id}.jpg`, `<folder>/Proxy/<stem>.mp4`, originals last; `--stats 1s` JSON progress; then `POST …/items/{uid}/uploaded` → server stats each file, sets `archive_path`, `original_path`, status → `live`, bumps search generation. The finished preview is also placed at the local mirror path (`<local_root>/Assets/B-roll Archive/<archive_path>`) so "Send to Resolve" needs no fetch on this machine.
8. **Live + visibility.** SPA Ingest panel polls `GET ../api/ingest-batches` (mine; all for admins); reporter section `broll_ingest` rides every tick → `machine_state` → fleet-grid chip; tray line + tooltip suffix + Advanced actions. Cancel/halt: dashboard `POST …/cancel` sets `cancel_requested` and expires the lease; the companion learns on its next heartbeat (410) or from `commands.broll_ingest` in the report reply.

Embeddings are **not** part of this loop: the container has no fastembed and the frozen companion will not get one. Ingested clips are searchable via FTS + server-computed `search_norm`; semantic vectors remain the base rig's optional sweep (`broll-index run --stages embed`).

## 2. Data model — `broll/web/migrations/011_ingest_batches.sql`

(Also `broll/schema.sql`, `broll/web/schema.sql`, `broll_index/migrate.py`, `app/db.py` `_MIGRATIONS[10]`, `CURRENT_SCHEMA_VERSION = 11`.)

```sql
CREATE TABLE ingest_batches (
    uid TEXT PRIMARY KEY,                    -- lower(hex(randomblob(16))), server-minted (music 003 precedent)
    editor TEXT NOT NULL, machine TEXT, companion_version TEXT,
    share TEXT NOT NULL, collection TEXT NOT NULL DEFAULT 'owned',
    settings_json TEXT NOT NULL,             -- {tier, upload_originals, keep_subfolders, start_now, transcribe:false}
    state TEXT NOT NULL DEFAULT 'queued'
      CHECK (state IN ('queued','claimed','running','done','done_with_errors','cancelled','failed')),
    n_items INTEGER NOT NULL DEFAULT 0, n_done INTEGER NOT NULL DEFAULT 0, n_failed INTEGER NOT NULL DEFAULT 0,
    n_live INTEGER NOT NULL DEFAULT 0, n_duplicate INTEGER NOT NULL DEFAULT 0,
    current_item_uid TEXT, lease_expires_at TEXT, last_heartbeat_at TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0, cancel_by TEXT, upload_paused INTEGER NOT NULL DEFAULT 0,
    error TEXT, created_at TEXT NOT NULL, claimed_at TEXT, started_at TEXT, finished_at TEXT, updated_at TEXT
);
CREATE INDEX idx_ingest_batches_editor ON ingest_batches(editor, created_at);
CREATE INDEX idx_ingest_batches_state  ON ingest_batches(state);

CREATE TABLE ingest_items (
    uid TEXT PRIMARY KEY, batch_uid TEXT NOT NULL REFERENCES ingest_batches(uid) ON DELETE CASCADE,
    ord INTEGER NOT NULL, orig_name TEXT NOT NULL, rel_dir TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER, hash TEXT, duration_s REAL, fps REAL, width INTEGER, height INTEGER, codec TEXT, shot_date TEXT,
    source TEXT NOT NULL CHECK (source IN ('upload','path')),
    video_id INTEGER REFERENCES videos(id) ON DELETE SET NULL,      -- minted at claim
    duplicate_of INTEGER REFERENCES videos(id) ON DELETE SET NULL,
    archive_dir TEXT, archive_stem TEXT,                            -- allocated at claim; archive_path = dir/Proxy/stem.mp4
    state TEXT NOT NULL DEFAULT 'pending'
      CHECK (state IN ('pending','duplicate','proxying','framing','describing','indexed','uploading','live','failed','cancelled','skipped')),
    stage_percent INTEGER, error TEXT, attempts INTEGER NOT NULL DEFAULT 0, original_uploaded INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);
CREATE INDEX idx_ingest_items_batch ON ingest_items(batch_uid, ord);
CREATE INDEX idx_ingest_items_video ON ingest_items(video_id);
ALTER TABLE share_roots ADD COLUMN collection TEXT;   -- NULL = derive from source (today's rule)
PRAGMA user_version = 11;
```

`videos` gains no columns; new `videos.status = 'ingesting'` (row exists, media not on the NAS yet — excluded from browse/tree/search like `skipped`); at claim a `share_roots` row `(share, root='ingest:<batch_uid>', source='originals', collection='owned', indexed=1)`; `search.creators_shares()` adds `OR collection = COLLECTION_CREATORS`.

**Batch:** `queued` →claim→ `claimed` →first item→ `running` → `done | done_with_errors | failed` (release) or `cancelled`. Lease expiry with items outstanding → back to `queued` (re-claimable by the same machine on restart; another machine of the same editor may claim after expiry).
**Item:** `pending` → (`duplicate` | `proxying` → `framing` → `describing` → `indexed` → `uploading` → `live`); any → `failed` (error, attempts); batch cancel → `cancelled`; `skipped` for user-unticked. Server enforces monotonic order except `failed`→retry.
**Companion state file** `~/.ccsync/state/broll_ingest.json` (atomic `.tmp` + `os.replace` on every transition; never in-memory-only): batch, staging dir, settings, forced/paused flags, lease, per-item `{uid, video_id, ord, source, local_path, hash, probe, archive_dir, archive_stem, stage, outputs, uploaded, error, attempts}`, model download state.

## 3. Files, by component

### 3.1 broll/web
| File | Responsibility |
|---|---|
| `migrations/011_ingest_batches.sql` (+ the three schema describers, `migrate.py`, `app/db.py`) | above |
| `app/config.py` | `get_fleet_token()` (`DASH_REPORT_TOKEN`), `get_session_secret()`, lease/heartbeat seconds (300/30), `ARCHIVE_INGEST_DIR = ".ingest"` |
| `app/fleet_auth.py` (new) + `app/identity.py` (vendored verbatim from `ytdl/web/ytdlweb/identity.py`) | `require_fleet_token`, `require_identity` — logic from `routes_fleet.py:54-89,105-140`; fail-closed |
| `app/ingest_batches.py` (new) | pure DB helpers: create, precheck (hash→id, name allocation), **claim** (one txn: mint `videos` rows status `ingesting`, allocate `archive_dir/stem` against existing `archive_path` stems ∪ this batch, insert `share_roots`, set lease), heartbeat, expire_lease, set_item_state, **write_item_result** (segments/themes/flags + `search_norm` + `bump_search_generation`, mirroring `ingest_index`), **mark_uploaded** (stat under `get_data_root()`, sizes match → `archive_path`, `original_path`, geometry, status `indexed`, item `live`), release, list (editor|all), cancel, upload_paused, `expire_stale_leases()` |
| `app/archive_names.py` (new) | `safe_name` + `claim_name` lifted from `build_archive.py:72-96, 301-340`, parity test |
| `app/normalize.py` (new, vendored verbatim from `broll_index/normalize.py`) | `searchable_blob` for server-side `search_norm` |
| `app/routes_batches.py` (new, `/api/ingest-batches`) | `POST /precheck`, `POST /`, `GET /?scope=mine|all` (`all` needs `X-CCSync-Admin`), `GET /{uid}`, `POST /{uid}/cancel`, `POST /{uid}/upload-paused`; identity from `X-CCSync-User` stamped by `BrollGate` |
| `app/routes_fleet.py` (new, `/api/fleet/ingest`) | `claim`, `heartbeat`, `release`, `items/{iuid}/status|result|uploaded` — all through `_leaseholder_or_410` (batch.editor == verified identity ∧ machine == batch.machine ∧ lease live ∧ not cancelled) |
| `app/schemas.py` | `IngestBatchCreateIn`, `IngestPrecheckIn`, `ClaimIn`, `ItemStatusIn`, `ItemResultIn` (reuses `SegmentIn` + geometry), `ItemUploadedIn`, `ReleaseIn`; caps (items ≤ 2000, names ≤ 255, segments ≤ 500) |
| `app/routes_ingest.py` | `/api/ingest/index` fills empty `search_norm` (closes the HttpBackend gap) |
| `app/search.py` | `creators_shares()` union `share_roots.collection`; exclude `status='ingesting'` in browse/tree/search |
| `pyproject.toml` + lock; `dashboard/deploy/requirements.txt` + lock | `jieba>=0.42` (MIT), `opencc-python-reimplemented>=0.1.7` (Apache-2.0); `tools/check_licenses.py` |
| tests | `test_ingest_batches.py`, `test_fleet_ingest.py`, `test_archive_names.py`, `test_normalize_parity.py`, migration 011, `test_mounted_prefix.py` |

### 3.2 dashboard
| File | Change |
|---|---|
| `app.py` | `_broll_fleet_re = ^/broll/api/fleet/ingest/batches/[0-9a-f]{32}/(claim|heartbeat|release|items/[0-9a-f]{32}/(status|result|uploaded))$` + `_companion_token_ok` in `login_gate` (beside `_ytdl_fleet_re`) |
| `broll.py` | `BrollGate` stamps `X-CCSync-User`/`X-CCSync-Admin` from the session for `/api/ingest-batches` (strip inbound; `_header_value` latin-1 rule from `ytdl.py:146-160`); `mount_broll` passes settings |
| `api.py` | `BrollIngestIn` (active, batch_uid, state, gate, done, failed, total, clip, percent, tier, uploading, upload_paused, model_download_percent, at); `ReportIn.broll_ingest`; **also declare `proxy_coverage`/`youtube_import`** (the drop bug); `flatten_broll_ingest`; `db.upsert_machine_state(..., ingest=)`; reply `commands["broll_ingest"] = {"cancel": [uids]}` (best-effort, never fails the report); fleet entries `entry["ingest"]` |
| `db.py` | `SCHEMA_V20`: `machine_state` + `ingest_active, ingest_batch, ingest_state, ingest_done, ingest_total, ingest_clip, ingest_at` (+ `proxy_missing, proxy_state`); `fetch_broll_ingest_map` |
| `templates/partials/fleet_grid.html` | chip `[ INDEXING B-ROLL: 12/40 ]` with tooltip (batch, clip, state, age) |
| tests | report section persisted + clears; identity stamping; carve-out regex; `commands.broll_ingest` |

### 3.3 companion
| File | Responsibility |
|---|---|
| `broll_vlm/` (new sub-package: `local_models.py`, `local_runtime.py`, `local_vlm.py`, `compact_format.py`, `contract.py`, `prompts/index_clip_v7_compact.md`) | **VENDORED VERBATIM** from `broll_index/` (same module names keep relative imports valid). Add pairs to `tools/release.ps1` and `test_cross_component.py`; prompt in PyInstaller data. Vendor, not import: the frozen build cannot carry `broll_index` (anthropic, xxhash, pyyaml, requests, jieba ≈ 50 MB + licence surface). |
| `broll_vlm_sidecar.py` (new) | cache `ytdlp_manager.tools_dir()/broll-vlm/`; cached zero-I/O `status()`; `gpu()` via `local_runtime.probe_gpu(runner=…)` (10 min cache); `fits(tier)`; `ensure(tier, progress_cb, stop_event)` = free-space (`upgrade_mod.MIN_FREE_BYTES_MARGIN`) → host allow-list (github.com/ggml-org, huggingface.co) → `ensure_runtime/ensure_model(progress=…)`; `server(tier)` → `local_vlm.get_server(...)` with a log file; `stop_server()`. Never CPU inference. |
| `broll_ingest_media.py` (new) | ffmpeg helpers on `ffmpeg_tools`: probe, xxh64 head+tail (algorithm from `hashing.py`), `preview_proxy_cmd` (**+ `-pix_fmt yuv420p`, timecode**), sprite (geometry math from `build_sprite`, `SPRITE_MAX_CELLS=240`, cell 240, cols 10), poster, scene detect + `fill_gaps`, frame extraction, `frames.json`, thumbs; spawns with `_win_creationflags()`; argv-parity tests against `broll_index.ffmpeg_tools` |
| `broll_upload.py` (new; sibling of `broll_fetch.py`) | `UploadJob`, `build_upload_command` = `rclone copyto <local> <remote>:<remote_root>/Assets/B-roll Archive/<rel>` + `RcloneTuning.flags(DIRECTION_UP)` + `--use-json-log --stats 1s`; `UploadQueue` (one rclone at a time; stills → proxy → original last; pause/resume; zero-I/O progress; `stop_all()`); prereqs via `broll_fetch.prereq_error`; verify size via `rclone lsjson` |
| `broll_ingest.py` (new; the orchestrator) | `BrollIngestor` mirroring `ProxyGenerator`'s surface: seams (`root_present_fn, paused_fn, blocked_fn, idle_probe, resolve_running_fn, gpu_busy_fn, deps`), `tick()`, own `_gate()` in proxy_gen's order (+ `STATE_NO_MODEL`, `STATE_GPU_BUSY`, `STATE_UPLOADING`), `status()`/`block_reason()`, `request_run()`, `pause/resume/cancel/pause_upload`, `prepare()`, `run()` (claim → state file → 202), `_drain()` with checkpoints; `IngestDeps` like `ytdl_executor.Deps`; `FleetClient` copy for `/broll/api/fleet/ingest` (`LeaseLost` on 410); `StorageShim`/`ConfigShim` so vendored `describe_video` runs unmodified; resume on construct. Not extracting a shared gate class from proxy_gen: its `_gate` reads instance state and is pinned by ~2300 lines of tests; the reusable part is 25 lines. GPU coupling expressed as `gpu_busy_fn` (ingest yields to proxy generation); `broll_ingest_skip_while_resolve` defaults **true**. |
| `broll_server.py` | routes below; `do_PUT` (vet → authorised → **route-specific** content-type rule) + `_stream_body_to(path, limit)` for the upload route only; hold `ingest_deps` like `ytdl_deps`; `stop()` also stops uploads/ingestor; CORS: `PUT` + `X-CCSync-Ingest` |
| `sidecar_tools.py` | `ensure_ffmpeg_pair(cfg, github_open)` factored out with no youtube gate; `ensure()` keeps its gates |
| `ffmpeg_tools.py` | `preview_proxy_cmd`: `-pix_fmt yuv420p` (+ timecode) |
| `app.py` | build `BrollIngestor` behind its own try (like proxy gen at 849-880); `_ingest_deps()`; `broll_server.start(..., ingest_deps=)`; reporter `get_broll_ingest`; `_on_report_response` → `note_report_response`; `_shutdown_block_reason` consults it; shutdown order: ingestor first; tray actions |
| `reporter.py` | `get_broll_ingest` → `payload["broll_ingest"]` (empty omitted; scalars only, exempt from shedding like `sync_guard`) |
| `tray.py` | `_get("broll_ingest")`; lines "Indexing b-roll… 12 of 40 (stops when you're back)", "B-roll indexing waits until you're away — 40 clips queued", "Downloading the b-roll indexing model… 43 %", "Uploading indexed b-roll… 3 clips left"; Advanced: "Index the b-roll batch now (don't wait until I'm away)" / Pause / Resume / "Cancel the b-roll batch…" (confirm); `_ingest_fingerprint` (state + bucketed counts, never percent) in `_menu_fingerprint`; `_with_ingest_suffix` tooltip |
| `config.py` | `broll_ingest_enabled=true`, `broll_ingest_idle_seconds` (= `proxy_gen_idle_seconds`), `broll_ingest_skip_while_resolve=true`, `broll_ingest_free_space_floor_gb=20`, `broll_ingest_max_concurrent_ffmpeg=2`, `broll_ingest_staging_dir` (override; base rig) |
| `pyproject.toml` / lock / spec | `xxhash>=3.4` (BSD-2); Pillow already in `tray`; `broll_vlm/prompts/*.md` data |
| tests | `test_broll_ingest.py` (gate order, checkpoints, resume, cancel mid-clip, LeaseLost, gpu-busy yield, model-not-ready), `test_broll_ingest_media.py` (argv/geometry/fill_gaps/hash parity), `test_broll_upload.py`, `test_broll_vlm_sidecar.py` (free-space refusal, tier fit, no CPU, host allow-list, progress cb, stderr untouched), `test_broll_vlm_vendored.py` (parity + `describe_video` smoke vs a fake llama-server), `test_broll_server.py` (PUT auth/415/cap/`.partial`/staging containment/CORS), `test_tray.py`, `test_reporter.py`, `test_app.py` |

### 3.4 indexer (small prep, additive)
`broll_index/contract.py` (new): move `validate_contract`, `merge_index_results`, `canonicalize_no_visual_label` out of `claude_client.py` (re-imported there); `compact_format`/`local_vlm` import from `.contract` — makes the vendored set anthropic-free. `local_runtime.ensure_runtime/ensure_model(progress=None)` (never touch stderr when a callback is given). `local_vlm.start_server`: `CREATE_NO_WINDOW` on nt. Tests.

## 4. API contracts

### 4.1 Loopback (127.0.0.1:8899) — Host + Origin vet; POST/PUT need allowed Origin or `X-CCSync-Loopback`
| Method / path | Body | Response | Cap |
|---|---|---|---|
| `GET /broll/ingest/capabilities` | — | 200 always `{ok, reasons[], version, ffmpeg, nvenc, rclone, gpu:{present,vram_gb,detail,apple_silicon}, tiers:{good:{fits,cached},best:{…}}, recommended_tier, runtime_cached, staging:{dir,free_bytes,floor_bytes}, busy:{batch_uid|null,state}, signed_in}` (zero I/O) | — |
| `POST /broll/ingest/pick` | `{kind:"files"|"folder"}` | `{ok, files:[{path,name,size,rel_dir}]}` / `{ok:false,message:"cancelled"}`; native dialog via `ui_dispatch`, ≤ 300 s | 256 KiB |
| `POST /broll/ingest/prepare` | `{items:[{local_id,name,size,source:"upload"|"path",path?,rel_dir?}], share_hint}` | 202 `{ok, staging_id, items:[{local_id, accepted, reason?, upload_url?}]}`; refusals: free space, path outside allowed roots / not a video, busy | 256 KiB, ≤ 2000 items |
| `PUT /broll/ingest/upload/{staging_id}/{local_id}` | `application/octet-stream` + **`X-CCSync-Ingest: 1`** (custom header ⇒ preflight) or the loopback token; streamed to `.partial`, renamed | 200 `{ok,size,hash,probe}`; 409 already; 413 over declared (+1 %); 507 free space | declared size |
| `GET /broll/ingest/progress?staging_id=` | — | `{staging:{items:[{local_id,state,hash,probe,error}]}, batch:{uid,state,gate,forced,upload_paused,done,failed,total,current:{item_uid,stage,percent},upload:{queued,active}, model:{tier,ready,downloading}}}` | — |
| `GET /broll/ingest/thumb?staging_id=&local_id=` | — | image/jpeg from inside staging only | — |
| `POST /broll/ingest/run` | `{batch_uid, staging_id, start_now}` (only these three fields read) | 202 `{ok,batch_uid,state:"claimed"|"waiting-for-model"}`; 409 busy; 503 capability gone | 256 KiB |
| `POST /broll/ingest/control` | `{action:"pause"|"resume"|"start_now"|"cancel"|"pause_upload"|"resume_upload"}` | `{ok,state}` | 256 KiB |

CSRF: octet-stream PUTs lacking `X-CCSync-Ingest` are refused (415/403) unless the loopback token is present — a hostile page can never stream bytes into staging. `OPTIONS` answers only allowed origins.

### 4.2 Fleet routes (broll/web at `/broll`) — `X-CCSync-Token` (shared `DASH_REPORT_TOKEN`, fail-closed) + signed `X-CCSync-Identity`; JSON; 4 MiB
| Route | Body | Response |
|---|---|---|
| `POST /api/fleet/ingest/batches/{uid}/claim` | `{machine, companion_version, tier, capabilities}` | 200 `{batch, lease_seconds, heartbeat_seconds, archive_remote_rel:"Assets/B-roll Archive", taxonomy, items:[{uid,ord,orig_name,rel_dir,size_bytes,hash,video_id,share,rel_path,archive_dir,archive_stem,state,duplicate_of}]}`; 403 identity ≠ editor; 409 another machine; 410 terminal |
| `…/heartbeat` | `{}` | `{ok, cancel_requested, upload_paused}` / 410 |
| `…/items/{iuid}/status` | `{state, stage_percent?, error?, attempts?, hash?, probe?}` | 200 / 400 illegal transition / 410 |
| `…/items/{iuid}/result` | `{segments, themes, quality_flags, category_hint, model, duration_s, fps, width, height, codec, shot_date, sprite_*}` | server replaces segments/themes/flags, computes `search_norm`, writes probe + geometry, item `indexed`, bumps generation |
| `…/items/{iuid}/uploaded` | `{files:[{rel,size}], original_uploaded}` | 200 `{ok,live:true}` after `stat()` matches; 409 `{missing[], size_mismatch[]}` (companion retries listed files) |
| `…/release` | `{state:"done"|"failed"|"cancelled", summary}` | finalises batch, clears lease |

### 4.3 Session routes (SPA)
`POST /api/ingest-batches/precheck` → `{items:[{local_id, duplicate_of, duplicate_name, final_name}]}`; `POST /api/ingest-batches` → `{uid}`; `GET /api/ingest-batches?scope=mine|all`; `GET /{uid}`; `POST /{uid}/cancel`; `POST /{uid}/upload-paused`. Auth = `X-CCSync-User` stamped by `BrollGate`; `scope=all` needs `X-CCSync-Admin: 1`.

## 5. Browser mechanics (`broll/web/static/app.js`, document-relative URLs only)
- `#ingest-panel` (header toggle; opened by a drop): drop zone / "Choose from this computer…" (files, folder) · preview grid · settings + Run · batch list (mine; "All machines" tab for admins when `scope=all` is not 403).
- Drop: window-level dragenter/over/leave/drop with a depth counter (music pattern); `webkitGetAsEntry`, directories via `reader.readEntries` looped until empty (Chrome ≤ 100 per call); `rel_dir` = `fullPath` minus top folder; filter by the shared video extension list; cap 2000.
- Thumbnails for dropped Files: `<video muted preload=metadata>` → seek to `min(1, duration*0.1)` → canvas 160×90 → dataURL; two decoders at a time; undecodable formats show "no preview" until the companion thumb arrives. Picker path: rows from `{path,name,size,rel_dir}`, thumbs from `/broll/ingest/thumb`.
- Prepare/upload: `PUT` two at a time via `XMLHttpRequest` (progress events); poll `progress` for hashes; then `precheck` → duplicates unticked by default ("already in the archive — clip #4127"), final names shown.
- Form: tier (default from manifest; unfit tiers disabled with the reason), shoot name (default = top folder or `YYYY-MM-DD ingest`, sanitised like `archive_names.safe_name`, re-validated server-side), keep sub-folders (on), upload originals (on), **run mode: Only when idle / Foreground** (default idle), transcription (disabled: phase 2). Summary line "N clips, X GB — will run when you're away". If the chosen tier's model is not cached, a confirmation shows the download size before Run.
- Run → create batch → `/broll/ingest/run` → live view polling `/broll/ingest/progress` (1.5 s) and `api/ingest-batches/{uid}` (5 s; the server view is the truth after reopening the page). Buttons: pause / resume / start now / pause upload / cancel.

## 6. Failure modes and safety gates
| Situation | Behaviour | Editor sees |
|---|---|---|
| Staging free space below floor | prepare/upload refuse 507 before accepting bytes; running batch pauses at next item | "Not enough space on P: (needs 20 GB free, has 6 GB) — free some space, it will continue" |
| Model/runtime download fails (offline, hash mismatch, disallowed host) | `waiting-for-model`, retried with backoff; mismatch deletes the file | "Downloading the Good model (3.9 GB)… failed: checksum did not match — retrying" |
| GPU too small / no GPU | `run` refuses 503; never CPU inference | tier disabled with reason; Run disabled |
| User returns mid-clip | gate → user-active; ffmpeg killed (`.partial` discarded), llama-server stopped, item back to checkpoint | "B-roll indexing paused — resumes when you're away" |
| Resolve open (idle mode) | gate → nothing runs; foreground mode ignores it | "waiting: DaVinci Resolve is open" |
| Proxy generator wants the GPU | proxy generation is *blocked* while a batch runs (`ProxyGenerator.blocked_fn`) | tray proxy line "waiting: indexing b-roll first" |
| Tier does not fit the GPU | `run` refuses 503; tray balloon once + a menu line until the batch is changed; never CPU inference | "Can't index b-roll: Best needs 12 GB VRAM, this GPU has 8 GB — choose Good" |
| Companion restart mid-batch | state file reloaded, staged files re-stat'ed, claim re-issued (idempotent), resume from checkpoint | batch continues |
| Lease expires (machine off) | batch back to `queued`; same editor's next companion re-claims | "waiting for <machine>" |
| Cancel (owner/admin) | `cancel_requested` + lease expired → 410 → kill child, keep staged outputs (7 days), release `cancelled`; `ingesting` rows without media deleted; `live` rows stay | "Cancelled by alex (12 of 40 clips are already in the archive)" |
| Fleet halt | uploads pause while halted; crunching (local only) continues | halt line + "uploads paused (halt)" |
| Duplicate clip | pre-check marks, default unticked; forced → `duplicate` terminal | "already in the archive — clip #4127" |
| Name collision | server allocates `<stem>_2` at claim (against claimed names, never disk) | final name in preview |
| Original moved/unplugged before upload (path source) | previews/index stay; item `live`, `original_uploaded=0`, error, retry button | "indexed and searchable; original not uploaded (drive unplugged) — retry" |
| Upload interrupted | rclone `.partial`; retried next tick; server verifies size before `live` | progress restarts |
| NAS unreachable | uploads queue; heartbeats fail; lease expires but local state persists; re-claim when back | "uploads waiting: NAS unreachable" |
| Corrupt proxy | verify decode (0.97 duration ratio) → CPU retry once → `failed` after 2 attempts | "clip failed: proxy did not decode" |
| llama-server dies | stop, `stalled`, retry after 60 s ×3, then `failed` with the log path | "the local model stopped — see broll_vlm_server.log" |
| Machine sleep | `block_reason()` keeps the keep-awake guard on while crunching | "still indexing b-roll (12 clips left)" |

Never-overwrite rules: staging `<local_id>.<ext>`; outputs `<video_id>.mp4/.jpg`; uploads to server-allocated paths, `copyto` target verified absent-or-same-size first.

## 7. Phasing (PRs, engineer-days; critical path A → E → H → J)
1. **A indexer prep** (0.5) — `contract.py`, progress callbacks, `CREATE_NO_WINDOW`.
2. **B server data model + session routes** (1.5) — migration 011, `ingest_batches.py`, `archive_names.py`, `routes_batches.py`, `creators_shares`, `ingesting` exclusion, `BrollGate` stamping.
3. **C fleet routes + auth + carve-out** (1.5).
4. **D server-side `search_norm`** (0.5) — vendored `normalize.py`, deps + locks, licence gate, `/api/ingest/index` fills it.
5. **E companion vendored `broll_vlm` + sidecar** (1.5).
6. **F companion media + upload** (1.5) — `broll_ingest_media.py`, pix_fmt fix, `broll_upload.py`, `ensure_ffmpeg_pair`, `xxhash`.
7. **G loopback routes** (2) — PUT/streaming/per-route cap, pick via `ui_dispatch`, prepare/progress/thumb/run/control, `docs/LOOPBACK_API.md`.
8. **H orchestrator + wiring + tray + reporter** (3).
9. **I dashboard reporting** (1) — `ReportIn.broll_ingest` (+ the `proxy_coverage`/`youtube_import` fix), `SCHEMA_V20`, grid chip, `commands.broll_ingest`. (Parallel with H.)
10. **J SPA** (2.5).
11. **K docs + ledger** (0.5) — `LOOPBACK_API.md`, `API.md`, `broll/SPEC.md`, `INDEXERS.md`, `ARCHITECTURE.md` §8/§11, `RELEASE.md` (vendored pairs), KNOWN_BUGS entries (ReportIn drop; preview_proxy pix_fmt), companion `VERSION` bump.
Total ≈ 16 days.

## 8. Verification
Unit per component (§3). Cross-component: `test_cross_component.py` gains the vendored pairs and an argv-parity module; `tools/release.ps1` refuses to build on drift; `tools/check_licenses.py --strict` after lock refresh.
End-to-end on the base rig against the live dashboard with three real clips (a 10-bit FX3 `.MP4`, a `.mov` in a sub-folder, an exact duplicate of an archived clip): capabilities → drop → thumbnails, duplicate flagged → shoot "E2E-<date>", Run (start now off) → `claimed`, tray "waits until you're away", grid chip `[ INDEXING B-ROLL: 0/2 ]` → walk away (or lower `broll_ingest_idle_seconds`) → model download progress (first time) → proxy → frames → describe; move the mouse mid-describe → pause + resume without duplicated segments → uploads land at `Assets/B-roll Archive/Creators_Club/E2E-…/…/Proxy/<stem>.mp4` + original + `posters/{id}.jpg` + `sprites/{id}.jpg` → `live` → clip in the tree under Our Footage and found by keyword search incl. a CJK on-screen-text term → "Send to Resolve" inserts the original. Cancel a second batch mid-clip as admin → stops within one heartbeat. Kill the companion mid-batch, restart → re-claims and finishes. Admin: grid chip + Ingest panel "All machines" + `machine_state.ingest_active` returns to 0 after release.

## 9. Decisions on the open questions (2026-08-18)
1. Own-footage collection only in v1 (Downloads/category allocation at `result` time is a follow-up).
2. Base rig staging: `broll_ingest_staging_dir` override (its `local_root` is the NAS share); default stays under `local_root`.
3. Fleet routes accept the shared `DASH_REPORT_TOKEN` (as ytdl's do); per-editor `cce1.` acceptance is a follow-up for both apps.
4. Upload verification = size via `rclone lsjson` + server `stat()`; use `--checksum` only where the SFTP remote exposes hashes.
5. Uploaded files carry the editor's uid, group `editors` (setgid 2770); confirm group-read for the container in the E2E; if not, a `server/` chmod step.
6. Model download consent = SPA confirmation with byte count before Run when the model is not cached.
7. ~~Proxy generation wins the GPU~~ Reversed by the owner: indexing wins; proxy generation is blocked while a batch runs.
8. Default 15 min per-clip cap with an override in the form.
9. Staging retained 7 days after `live`; the finished preview is placed at the local mirror path so "Send to Resolve" needs no fetch on the machine that indexed it.
