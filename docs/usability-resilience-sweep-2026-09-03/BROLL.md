# B-roll platform: search web UI + API, ingest batches, client folders/share links, indexer pipeline, eval

## Summary
The b-roll *web* surfaces are among the most considered in the repo: the search
UI's copy names causes and next actions, the ingest drawer confirms a big drop
with bytes and hours before committing a GPU night, and the client share page is
a finished public artefact (contact sentence on a dead link, `no-cache` so revoke
bites, `noindex`). The *indexer* is the opposite: a serial run prints nothing at
all for six hours, every config mistake is a raw traceback, and there is no
`status` and no cost command. The biggest risk is a data-loss one nobody has
written down: `publish_db.py --which broll` swaps the file that holds every
fleet-ingested clip *and* the whole `ingest_batches` table, past a 10% shrink
check a 200-clip ingest into a 15k archive sails through - the hazard the music
spec reasons about and b-roll's does not. Second: the platform is invisible to
the wave-4 self-diagnosis machinery (forty alert kinds, none about b-roll; a
`DEGRADED` mount is a log line and a hidden nav link). The cheapest high-value
win is a retry on a failed upload - the companion already answers 409 for bytes
it holds and its comment says "the SPA retries a dropped file after a
reconnect", and the SPA does not.

Findings marked (IX) came from a delegated read of `broll/indexer/`.

## Findings

### BROLL-1: publishing broll.db destroys every fleet-ingested clip and every live ingest batch
- **Lens:** resilience · **Who:** owner
- **Where:** `server/publish_db.py:88-101` (`SPECS["broll"]`), `:110` (`DEFAULT_SHRINK_PCT = 10.0`), `:313`; `broll/web/migrations/011_ingest_batches.sql`; `server/install_dashboard_app.py:1755,1969` (`/broll-data`, mounted `:rw`); `docs/BACKCATALOGUE_INGEST.md:376-382`
- **Today:** the dashboard's b-roll app WRITES the live `broll.db`: `claim` mints `videos` rows, `write_item_result` writes segments, `mark_uploaded` flips them live, and `ingest_batches`/`ingest_items` are tables *inside that file*. `publish_db --which broll --apply` renames the base rig's copy over it. The music entry reasons about exactly this (`:84-88`: "`ingest_queue` holds rows that exist ONLY on the NAS ... drained ... BEFORE a publish"); the b-roll entry has no drain, no precondition, and no mention in `BACKCATALOGUE_INGEST.md`, which ends with the bare command. The only guard is a row-count shrink test over `videos, segments, embeddings` at 10%: 200 ingested clips against 15,000 is 1.3%, so it passes. Every fleet-ingested clip, its segments and embeddings, every batch's state and per-item progress are gone; the media stays on disk with nothing pointing at it, and a running companion keeps POSTing results into a database that no longer has its batch.
- **Proposed:** (a) preflight for `--which broll`: read the live copy for any non-terminal `ingest_batches` row and any `videos` row (by `share, rel_path`) the candidate lacks, and REFUSE - `there are 3 ingest batches running on the server and 212 clips in the live index that this copy does not have. Publishing now would delete them.` plus `--allow-loss`. (b) the real fix, the music one: `--export-drain` / apply for the NAS-only rows and the batch tables. (c) name the precondition in `BACKCATALOGUE_INGEST.md`'s "Afterwards".
- **Effort:** S (a) / M (b) · **Value:** critical · **Confidence:** high
- **Related:** MEDIA-4 is this shape for music and is BUILT there.

### BROLL-2: the whole b-roll platform is invisible to the server's self-diagnosis
- **Lens:** resilience · **Who:** admin, owner
- **Where:** `dashboard/src/ccsync_dashboard/alerts.py:1425-1512` (40 `AlertKind` rows, none about b-roll); `broll.py:452-456`; `app.py:1209-1212`
- **Today:** wave 4 built PROBLEMS THE SERVER FOUND and a forty-kind registry; b-roll appears in one row, `ingest_staging`, which is about the *sync* drop folder. A `DEGRADED` mount ("every /broll request will fail until the data root is writable") is a `log.warning` and a hidden nav link; `broll_status` sits on `app.state` and is read by nothing but a boolean in `ui.py`. A batch stuck `queued` for a week, a share link expiring tomorrow, an index that has not grown in months: no check, so `NOTICE_CHECKS_META` cannot even render `[ NOT CHECKED ]`. Timeline Cards keeps a `cards_detail` string (`app.py:1241-1244`) precisely for this; b-roll and music keep none, so no diagnostic route could say *why*.
- **Proposed:** return `(status, detail)` from `mount_broll` as `mount_cards` does, and register four kinds with their writers: `broll_mount` (ERROR, next action = the detail), `broll_batch_stuck` (WARN, non-terminal batch > 24 h with no heartbeat: "Ask <editor> to reopen the b-roll ingest panel on <machine>, or cancel the batch"), `broll_share_expiring` (WARN, live links inside 7 days), `broll_index_stale`. Adding a check is adding a registry row, which is that design's whole point.
- **Effort:** M · **Value:** high · **Confidence:** high

### BROLL-3 (IX): `broll-index run` prints nothing at all for six hours
- **Lens:** usability · **Who:** owner
- **Where:** `broll/indexer/broll_index/cli.py:471-474` (`main` never calls `logging.basicConfig`; only `run_queue.py:198` does), `cli.py:86`; `tools/run_backcatalogue.sh:71`
- **Today:** the root logger drops every `logger.info` in the pipeline - per-clip progress, `"claude: video %s sheets capped %d -> %d"` (`pipeline.py:296`), `"transcribe: video %s skipped (over the duration cap...)"` (`:589`), `"local vlm: video %s merged %d over-segmented pair(s)"` (`local_vlm.py:520`). Between start and finish the owner gets one line: `run: processed 412 video(s)`. The documented owner path is `run --stages claude >>"$LOG" 2>&1` at ~20 s/clip, i.e. a log file that stays empty for six hours. `parallel_local.py:167` and `parallel_claude.py:256` do print `[i/n] rate/min eta Xh ok= err= skip=`; the serial CLI has no equivalent.
- **Proposed:** `logging.basicConfig(level=INFO, stream=sys.stdout, format="%(asctime)s %(message)s")` in `main()` with `-q/--quiet`, plus a per-clip line from `_process_video` in the same `[i/n] rate eta ok/err` shape the two parallel drivers already print.
- **Effort:** S · **Value:** high · **Confidence:** high

### BROLL-4 (IX): a share root that is not mounted scans silently to zero
- **Lens:** both · **Who:** owner
- **Where:** `broll/indexer/broll_index/scanner.py:88` (bare `os.walk(root)`); `docs/BACKCATALOGUE_INGEST.md:41`
- **Today:** `Path(root).resolve()` on a missing path does not raise, so `scan_share('Z:/not-mapped')` returns `[]` and `cmd_scan` prints `scan: upserted 0 video(s) from Z:/... (share=ff2)` and exits 0. The shares live on mapped network drives (`Q:\FF2`, `R:\Project Backups\...`), so "the drive was not mapped when the scheduled task ran" is the routine failure. The doc names this exact shape as a hazard for a different cause - *"the scan would report zero rows and look like a config error"* - and nothing checks.
- **Proposed:** `do_scan` refuses when `root` is not an existing directory, naming the share and its configured root; and when a share that already has rows scans to zero files, say so loudly rather than printing `0`.
- **Effort:** S · **Value:** high · **Confidence:** high

### BROLL-5: a failed upload is permanent, and the retry the companion was built for was never written
- **Lens:** both · **Who:** editor
- **Where:** `broll/web/static/ingest.js:756-796`, `:745-754` (the pump skips `item.error`); `companion/src/ccsync_companion/broll_ingest.py:1417-1421`; `broll_server.py:1511-1518`
- **Today:** `xhr.onerror = () => done(false, "upload failed. Is the companion still running?")` sets `item.error` for the life of the page and the pump never attempts that clip again. No `xhr.timeout`, no backoff, and no `[ retry ]` control in the failed row. A hotel-wifi blip at 95% of a 4 GB file, or a laptop that slept, permanently fails one clip of a 200-clip drop; the only route back is clearing and re-dropping everything. The companion was built for the opposite: `upload_slot` answers 409 with "the SPA retries a dropped file after a reconnect and must not re-send 40 GB it already sent", and `_stream_body_to` writes `<dest>.partial` and renames only on a complete body - so a retry is completely safe.
- **Proposed:** on a network-level failure (`onerror`/`ontimeout`, not a 4xx) retry after `2^n` seconds up to 3 attempts with the row reading `upload interrupted, retrying (2 of 3)…`; only then set `item.error` and render a `[ retry ]` link that clears it and calls `ingestPumpUploads()`. Add `xhr.timeout` so a black-holed connection fails in minutes rather than never.
- **Effort:** S · **Value:** high · **Confidence:** high

### BROLL-6 (IX): every indexer config mistake is a raw Python traceback
- **Lens:** usability · **Who:** owner
- **Where:** `broll/indexer/broll_index/cli.py:471-474` (nothing caught), `:346`, `config.py:485-489`; contrast `cli.py:96-107,169-174`
- **Today:** `broll-index run` with no config prints an eight-frame traceback ending `FileNotFoundError: ... 'config.yaml'`. Every carefully-worded `ConfigError` meets the owner under `Traceback (most recent call last)` - including `"data_root is required (or set BROLL_DATA_ROOT). It is where frames, proxies, posters, sprites and transcripts are written - tens of GB, so it is never guessed."` `LocalRuntimeError`, `LocalVlmError` and `FatalRunError` escape the same way; only `models pull` and `transcribe` catch cleanly. Compounding it, `--config` defaults to the cwd-relative `"config.yaml"` while every sibling script uses `site_data.DEFAULT_QUEUE_CONFIG` resolved from `__file__`, for the reason given at `site_data.py:9-14`.
- **Proposed:** wrap `args.func(args)` in `except (ConfigError, LocalRuntimeError, LocalVlmError, FatalRunError, FileNotFoundError) as e: print(f"broll-index: {e}", file=sys.stderr); return 2`. Default `--config` to `DEFAULT_QUEUE_CONFIG`, or refuse with "pass --config".
- **Effort:** S · **Value:** high · **Confidence:** high

### BROLL-7 (IX): the local backend commits to a 20-minute wait before checking the GPU
- **Lens:** resilience · **Who:** owner
- **Where:** `broll/indexer/broll_index/local_runtime.py:979-1002` (`refuse_if_tier_unfit`, called only by `cli.py:104`), `:907` (`nvidia-smi memory.total`); `local_vlm.py:454-493`, `:48`, `:154`, `:63`
- **Today:** the good refusal - `"Best needs 12 GB VRAM; this machine reports 10 GB - choose Good or add --force"` - is wired to `models pull` and nothing else. `describe_video` goes straight to `get_server`. So (a) a box with no NVIDIA card downloads 640 MB of CUDA runtime plus 3.3 GB of weights before failing, and (b) the VRAM check compares **total**, not free. `BACKCATALOGUE_INGEST.md`'s "Keep Resolve closed" records the real number (Resolve 9.3 GB of a 10 GB card, llama-server needs ~5) as a **doc rule with no code behind it**. When it bites, `start_server` polls for `DEFAULT_LOAD_TIMEOUT_S = 1200.0` then raises "did not become healthy within 1200s", which `is_fatal_local_error` matches, so the whole run aborts: twenty silent minutes to learn the GPU was busy.
- **Proposed:** call `refuse_if_tier_unfit` once at the top of `cmd_run` when `backend == "local"`, before any download; add `memory.free` to the `nvidia-smi` query and refuse by name when free VRAM is under the tier floor ("DaVinci Resolve is using 9.3 GB of this card. Close it, or run with --force."); drop the load timeout to ~180 s with a progress line every 15 s.
- **Effort:** M · **Value:** high · **Confidence:** high

### BROLL-8: a batch whose machine went away cannot be picked up by anything, and the copy says it can
- **Lens:** both · **Who:** editor, admin
- **Where:** `broll/web/app/ingest_batches.py:531-562`; `app/routes_fleet.py:120-210` (six routes, all keyed by a uid the caller must already hold - no discovery route); `static/ingest.js:1211-1218`, `:1475-1487`
- **Today:** a lease expires, the batch returns to `queued` with its `videos` rows already minted at `status='ingesting'`. A companion only ever acts on a uid handed to its own loopback by the page; it never polls for work. So the same machine resumes only if its `~/.ccsync` staging record survives, and no other machine can *ever* take it - yet the 503 notice says `"...or another of your machines can pick it up."` The batch list offers `clips` and `cancel` and nothing else, so a batch orphaned by a wiped or reinstalled companion sits `queued` for ever holding name reservations and permanently-`ingesting` rows. `expire_stale_leases` runs only when a human opens the drawer (`routes_batches.py:145,159`).
- **Proposed:** (a) fix the copy now: `The batch is queued on the server: change the model and press Run again on this computer.` (b) add `[ run this batch here ]` to any `queued` batch, re-dispatching its uid to this machine's loopback (the claim route is already idempotent for the holder and 409s another machine). With (b) the original copy becomes true.
- **Effort:** S (a) / M (b) · **Value:** high · **Confidence:** high
- **Related:** MEDIA-30 is the other side of the same lease.

### BROLL-9: a search that finds nothing shows an empty page
- **Lens:** usability · **Who:** editor
- **Where:** `broll/web/static/app.js:633-668`, `:640-648` (`0-0 of 0`), `:1163-1185`; `app/search.py:69-71`
- **Today:** the grid empties, the meta line reads `search: "wedding ceremony"`, the pager reads `0-0 of 0`. Nothing says the archive was searched and has none, nothing offers a next move, and it is indistinguishable from a request that failed to paint. `search.py`'s docstring calls an empty result "the correct, honest answer to a query that matches nothing in the archive" - the whole keyword-first design exists to produce it - and the UI never says it.
- **Proposed:** in `renderGrid`, when `results.length === 0`, render `Nothing in the archive matches that.` plus the levers actually on this page, each wired to its control and shown only when that filter is on: `Try: Semantic search (finds meaning, not words) · clear the folder filter · stop hiding flagged clips · turn fuzzy back on`.
- **Effort:** S · **Value:** high · **Confidence:** high

### BROLL-10: Semantic mode can return nothing, for ever, and say nothing
- **Lens:** both · **Who:** editor, admin
- **Where:** `broll/web/app/semantic.py:10-23`, `:110`, `:47-54`; `routes_api.py:65-94` (the response is `{results, total}` and nothing else); `static/index.html:43-47` (the three mode buttons are always offered)
- **Today:** `fastembed` is optional and the query model must match the stored vectors' model; a missing package or a mismatch makes the count for this model zero. In every one of those cases `mode=semantic` returns an empty list on every query, permanently, and `hybrid` silently loses its booster. The editor sees BROLL-9's blank page and concludes the archive has nothing; the admin gets no signal, because the response carries no capability field and nothing writes a notice.
- **Proposed:** add `"semantic": {"available": bool, "reason": str}` to `/api/search` (from `available(conn)`); when false disable the Semantic button with `title="Meaning-based search is not available on this server"` and fall back to hybrid with one toast. Pair with a `broll_semantic_off` kind per BROLL-2.
- **Effort:** S · **Value:** high · **Confidence:** high

### BROLL-11 (IX): nothing tells the owner what a run will cost, or what it has cost
- **Lens:** usability · **Who:** owner
- **Where:** `broll/indexer/broll_index/pipeline.py:234-258` (`_log_usage` -> `DATA_ROOT/usage.jsonl`), `claude_client.py:62-67` (`PRICE_PER_MTOK`); `broll/indexer/tools/cost_report.py`; `broll/morning_report.py:20-21`
- **Today:** every call's estimated `total_cost_usd` is faithfully appended to `usage.jsonl` and nothing surfaces it: no running total during a run, no forecast before one, no `broll-index cost`. The report is `python tools/cost_report.py E:/broll-data --archive-hours 500`, a script named in no `--help` text; the other reader hardcodes `E:\broll-queue` paths, so it is not a tool a second site has.
- **Proposed:** fold it in as `broll-index cost [--forecast-hours N]` reading `cfg.data_root`; print a cumulative `$X.XX so far` on BROLL-3's progress line; print a forecast banner at the start of an `anthropic`-backend run.
- **Effort:** M · **Value:** high · **Confidence:** high
- **Related:** MEDIA-7 is the spend-*cap* half and is still open; this is the visibility half.

### BROLL-12 (IX): there is no way to ask "how far along is the archive?"
- **Lens:** usability · **Who:** owner
- **Where:** `broll/indexer/run_queue.py:114-120` (`counts`), `:123-131` (`remaining`) - module-private; `watchdog.ps1:74`; `tools/run_backcatalogue.sh:75-80`
- **Today:** the status breakdown exists and is reachable only as `python -c "import run_queue; print(run_queue.remaining('E:/broll-queue/broll.db'))"`, which is literally how the watchdog calls it. The CLI has `doctor` (GPU/runtime state) and no `status`. To answer "did last night work?" the owner runs sqlite by hand; `run_backcatalogue.sh` ends by inlining a `sqlite3.connect(...)` heredoc for exactly this, which is the evidence the command is missing.
- **Proposed:** `broll-index status [--share X]`: per-share counts by status, how many queued per stage, oldest/newest `indexed_at`, error count with the top three messages. Reuse `counts`/`remaining` so the definitions cannot drift.
- **Effort:** S · **Value:** high · **Confidence:** high

### BROLL-13: a half-indexed archive puts thousands of clips in no folder at all
- **Lens:** usability · **Who:** owner, editor
- **Where:** `broll/web/app/search.py:1010-1023` (`BROWSE_PREDICATE` excludes only `skipped`/`excluded`/`ingesting`/duplicates), `routes_api.py:285-289` (tree counts require `status='indexed'`), `:230-247`, `search.py:366-375`
- **Today:** while the indexer works - days, for a back-catalogue - rows sit at `discovered`/`probed`/`proxied`/`error`. They are browsable and searchable (correctly: some have posters) but have no category, so they are counted in the Downloads root total and in NO folder beneath it. `build_category_clause` is explicit that `_uncategorised` must not hold them ("'No subject was found in this clip' and 'this clip has not been described yet' are different facts and must not share a folder") and `_downloads_total` is explicit that inflating a subject folder "would be the same lie in the other direction" - both right, and the third fact has nowhere to live. The owner sees `Downloads 15,103`, folder counts summing to 4,000, no way to reach the rest, and no way to learn that 303 are at `status='error'`.
- **Proposed:** a third pseudo-folder beside `Uncategorised`, always last: `Not described yet (N)`, selecting `BROWSE_PREDICATE AND v.status NOT IN ('indexed','sorted')`, with its own clause in `build_category_clause`; and a coverage line in the results meta from one `GROUP BY status` - `11,103 clips waiting: 10,800 to describe, 303 the indexer could not read.` That is the only "how far has the indexer got" surface a browser has.
- **Effort:** M · **Value:** high · **Confidence:** high
- **Related:** `tests/test_tree_counts_match_clicks.py` is the rule this extends rather than breaks.

### BROLL-14: an NFD filename silently downgrades Send to Resolve to the 540p preview
- **Lens:** resilience · **Who:** editor
- **Where:** `broll/web/app/routes_api.py:44-64` (`_insert_target`: `os.listdir` then `os.path.splitext(e)[0] == preview.stem`); no `unicodedata` anywhere under `broll/web/app/`
- **Today:** the insert target is found by listing the archive top slot and matching the preview's stem **byte for byte**. `Matej Šimalčík.mov` written by a Mac decomposes to NFD on disk while the DB row holds NFC; `matches` is empty and the function silently falls back to `return ARCHIVE_SHARE, rel` - the Proxy preview. The editor gets a 540p clip on their timeline with no message; the docstring calls that fallback "degraded but present" and expects it only for 4 known stem-diverged clips. CJK names never warn you. Secondary: this `os.listdir` runs on every `/api/videos/{id}`, i.e. every detail open, against a NAS mount.
- **Proposed:** compare `unicodedata.normalize("NFC", …)` on both sides - safe under the repo rule, since the value RETURNED is the listed entry, i.e. the on-disk bytes. Log at INFO when the fallback fires, and add `"insert_is_preview": true` to the payload so the detail view can say `Only the preview is available for this clip on this machine.`
- **Effort:** S · **Value:** high · **Confidence:** high
- **Related:** CR-90, `docs/GOTCHAS.md` §17.

### BROLL-15 (IX): nothing stops two indexers running, and the browsing proxy is written non-atomically
- **Lens:** resilience · **Who:** developer
- **Where:** no lock anywhere in `broll/indexer` (no `flock`/`msvcrt`/lockfile); `parallel_claude.py:114-123`; `pipeline.py:167-168`, `:201-231` -> `ffmpeg_tools.py:229-230,271`; `watchdog.ps1:60-61`; contrast `build_archive.py:593-607`
- **Today:** `parallel_claude.eligible_ids` documents the collision and offers `--after-id` as a *manual* workaround - "both would dispatch those... anything mid-flight gets described twice and paid for twice" - while `parallel_local.py` and `broll-index run` have nothing, and the watchdog's guard only matches command lines containing `run_queue.py`. Two passes then write the same files: `stage_proxy` encodes straight to `proxies/{id}.mp4` with no `.partial` + `os.replace`, and `stage_frames` writes into shared `sheets/{id}/` before its `_complete` marker. The same repo does it right twice elsewhere ("an interrupted run must never leave a half-file that looks complete to the next pass", and the companion's proxy rule 2). A kill mid-encode leaves a truncated proxy at the path the web app serves as `/media/proxy/{id}.mp4` and that `_frames_source` (size > 0 only) would feed the model on a later `--stages frames`.
- **Proposed:** encode to `{id}.mp4.partial` and `os.replace` after the `_bad()` check; take an exclusive lock on `data_root/indexer.lock` in `run_pipeline`, `parallel_local` and `parallel_claude`, refusing with the holder's pid.
- **Effort:** M · **Value:** high · **Confidence:** high

### BROLL-16 (IX): in `db.mode: api`, one network blip drops a described clip and crashes the run
- **Lens:** resilience · **Who:** developer
- **Where:** `broll/indexer/broll_index/storage/http_backend.py:111-130` (`write_index_result`), `:89-99`; `pipeline.py:698` (`set_error` outside any try), `:752` (the loop catches only `FatalRunError`)
- **Today:** the local shadow is written first, then the POST to `/ingest/index` with `raise_for_status()`. On a 502 the shadow already says `status='indexed'` while the live index has nothing. The pipeline then calls `set_error`, which is a second POST that raises again - and it sits outside any `try`, so the exception leaves `_process_video` and the run dies with a traceback, leaving the clip at a status the queue never revisits. No reconciliation pass exists between shadow and remote.
- **Proposed:** POST first, write local only on success; retry the ingest POST on 5xx/timeout with `_call_with_retry`'s backoff; make `set_error` best-effort (never raise); add `broll-index resync` to replay shadow rows the remote does not have.
- **Effort:** M · **Value:** med-high · **Confidence:** high

### BROLL-17: the Send-to-Resolve sync poll has no timeout, no cancel, and a silent dead end
- **Lens:** both · **Who:** editor
- **Where:** `broll/web/static/app.js:1472,1482,1519-1590`
- **Today:** while the companion reports `state: "downloading"` the `for (;;)` loop polls every 1.5 s for ever, with no attempt cap and no wall clock. If lane B is paused by the circuit breaker, or the NAS is unreachable, the button reads `SYNCING…` indefinitely. Both buttons stay disabled, and because the guard is `if (!state.detail || sendInFlight) return;` every further click does *nothing at all* - no toast, no explanation. Closing the detail view does not clear it.
- **Proposed:** cap at 15 minutes and at 20 polls with no `progress.percent` change; on either, `toast("The clip is still syncing down and has not moved for a while. Check the CC Sync tray: downloads may be paused.", "warn")` and release the buttons. Label the button `Cancel sync` while polling (a second click abandons the wait; the companion's fetch continues, which is right). Make the blocked click say `A send is already in progress.`
- **Effort:** S · **Value:** med · **Confidence:** high

### BROLL-18: a batch that finishes with failures offers no way to try them again
- **Lens:** usability · **Who:** editor
- **Where:** `broll/web/static/ingest.js:1464-1487` (`n_failed`, then only `clips` and `cancel`), `:1489-1499`
- **Today:** `done_with_errors · 180/200 done · 12 failed`, and the only affordance is `clips`, which prints twelve lines of `failed · Day2/A001_C012.MP4 - ffmpeg exited 1`. No re-run, no per-item retry, no selection. The editor must transcribe twelve names, find those files, and re-drop them - which, because the first attempt minted `videos` rows, may then read as duplicates.
- **Proposed:** `[ retry the 12 that failed ]` on any terminal batch with `n_failed > 0`: reset those items to `pending`, the batch to `queued`, and dispatch as BROLL-8(b) does. Nothing needs re-uploading while staging survives; when it does not, say so per item (`the copy of this clip on this computer is gone - drop it again`).
- **Effort:** M · **Value:** med-high · **Confidence:** high

### BROLL-19: a client folder is created by a browser prompt with no contact, and the dead-link contact sentence is hollow without it
- **Lens:** usability · **Who:** editor, client
- **Where:** `broll/web/static/clientfolders.js:205-221` (`window.prompt`, body is `{title}` only), `:318-340`; `app/client_folders.py:221-246` (`contact: str = ""`); `app/routes_share.py:112-142`
- **Today:** creating a folder is `window.prompt("Name for the new client folder (the client sees this):")` - an OS dialog in a product whose every other control is a `[ ]` button - posting the title alone. Contact, description and expiry default to empty/never and are reachable only by opening the folder afterwards. So the common path ships a live public link with no contact line at all, and the whole UX-19 fix from 08-28 (name the editor on a dead link so the client "can ask for a new link" rather than "holding the only page they have with nobody on it") degrades to the generic page, because the field it reads was never filled.
- **Proposed:** replace the prompt with the panel's own form: `Folder name` (required), `Contact for licensing` (prefilled from the signed-in editor), `Link expires` defaulting to 90 days (the option exists). If contact is blank when `[ Copy ]` is pressed, warn once: `This link has no contact on it. If it stops working, the client will have nobody to ask. Add one?`
- **Effort:** S · **Value:** high · **Confidence:** high
- **Related:** UX-19; MEDIA-32 (never-expires default) folded in here.

### BROLL-20: the editor can copy a link their client cannot open, and is told only "Link copied"
- **Lens:** usability · **Who:** editor, client
- **Where:** `broll/web/static/clientfolders.js:75-86`, `:293-294`, `:130-141` (the base field is admin-only)
- **Today:** with no public link base set, links are minted against the dashboard's own address, which works only for people already on the tailnet. The panel says so in muted small text the editor cannot act on, and `[ Copy ]` then reports unqualified success. It surfaces days later as a client saying the link is dead.
- **Proposed:** when `!cf.publicBase`, make the toast a warning carrying the next action: `Link copied. It only works for people on the tailnet: ask an admin to set the public link base in this panel before you send it.` Same string on `[ open ]`'s title, and "N client folders exist and no public link base is set" as a notice per BROLL-2.
- **Effort:** S · **Value:** med-high · **Confidence:** high

### BROLL-21 (IX): a truncated or foreign `.srt` becomes a clip's permanent transcript
- **Lens:** resilience · **Who:** developer
- **Where:** `broll/indexer/broll_index/pipeline.py:334-348` (`_find_existing_srt`), `:379-380,453` (`transcribed_at`), `:441`; `tools/whisper_transcribe.py:147`; `transcribe.py:122,132-136`
- **Today:** the helper looks for `{stem}.srt` and otherwise takes *the newest `.srt` in the directory* ("in case the naming convention ever drifts"). Whatever it finds is ingested and `transcribed_at` is set, which closes the door for ever - the row is skipped on every future run. The writer is non-atomic (`dest.write_text(...)`, no `.partial`) and `run_whisper` has a 2-hour timeout after which `subprocess.run` kills the child mid-write. So an interrupted batch transcription can leave a truncated `.srt` silently adopted as that clip's speech index. `transcript_quality.assess` catches invented text, not truncation.
- **Proposed:** the helper writes `{stem}.srt.partial` and `os.replace`s it; drop the newest-file fallback, or log loudly when it fires; record the srt's mtime/size beside `transcribed_at` so a re-run can detect a replaced file.
- **Effort:** S · **Value:** med · **Confidence:** high

### BROLL-22: batch state is shown as the database's word, and an abandoned batch reads as a running one
- **Lens:** usability · **Who:** editor, admin
- **Where:** `broll/web/static/ingest.js:1451-1463`; `app/ingest_batches.py:53-56`, `:536-538`
- **Today:** the card shows the raw enum - `queued`, `claimed`, `running`, `done_with_errors` - beside the machine and `heartbeat 40 minutes ago`. `expire_stale_leases`'s docstring says `machine` is "deliberately LEFT in place so the SPA can still say 'waiting for <machine>'"; the SPA never says it, so a batch whose machine was switched off renders as `queued · creator-2 · heartbeat 3 hours ago`, which reads as progress. `n_live` is index jargon for "in the archive and searchable".
- **Proposed:** map states to sentences - stale-heartbeat `queued` -> `waiting: creator-2 stopped answering 3 hours ago`; no machine -> `waiting to start`; `claimed` -> `starting on creator-2`; `running` -> `indexing on creator-2`; `done_with_errors` -> `finished, 12 could not be indexed`. Counters: `180 of 200 indexed · 168 searchable · 12 failed · 20 already in the archive`.
- **Effort:** S · **Value:** med · **Confidence:** high

### BROLL-23: nothing on the page says a search is in flight
- **Lens:** usability · **Who:** editor
- **Where:** `broll/web/static/app.js:603-637`; no loading state anywhere in `app.js`/`style.css`
- **Today:** the grid keeps showing the previous query's results until the new ones land. A semantic query costs a model load (~10 s the first time, `semantic.py:25-28`) plus a brute-force scan over Tailscale; for those seconds the editor looks at the wrong footage with no indication, and retypes or re-clicks.
- **Proposed:** set `aria-busy` and a `.searching` class on `#results-grid` at the top of `runSearch`, cleared by the winning token only; 50% opacity plus `searching…` in `#results-meta`.
- **Effort:** S · **Value:** med · **Confidence:** high

### BROLL-24: the client page tells a phone user to hover, and hover is the only way to scrub
- **Lens:** usability · **Who:** client
- **Where:** `broll/web/static/sprite.js:101-107` (`mousemove`, the only listener); `static/share.html:34-38`
- **Today:** the sprite-sheet scrub - the feature the intro copy leads with and the reason the sheets are shipped - is wired to `mousemove` alone. A client opening the link on a phone, the stated primary case, can neither hover nor drag-scrub, and the first instruction on the page is an action they cannot perform: `Hover a thumbnail to scrub through the clip.`
- **Proposed:** add `pointermove` alongside `mousemove` with `touch-action: pan-y` on `.card-thumb` so a horizontal drag scrubs and a vertical drag still scrolls; under `(pointer: coarse)` swap the copy to `Drag across a thumbnail to scrub through the clip. Tap it to play the preview and see what is in it.` `wireSpriteScrub` is shared, so the editor grid gets it too.
- **Effort:** S · **Value:** med-high · **Confidence:** high

### BROLL-25: no query help, no way to exclude a term, and the browser's own history is switched off
- **Lens:** usability · **Who:** editor
- **Where:** `broll/web/app/search.py:271-274`, `:276-300`; `static/index.html:35` (`autocomplete="off"`); no `localStorage` in `app.js`
- **Today:** terms are ANDed, `"quotes"` make a phrase, everything else is a literal. There is no OR and no exclusion - `boat -sunset` searches for the literal term `-sunset` and returns nothing, with BROLL-9's blank page as the only feedback. The only documentation is the input placeholder. `autocomplete="off"` also removes the browser's own recall, so an editor running fifty searches a day retypes every one; there is no recent-searches list and nothing in `localStorage`.
- **Proposed:** (a) support a leading `-term` as an FTS `NOT` - one branch in `_terms_to_fts_query`, the sanitiser already makes the rest inert. (b) a `?` beside the mode toggles: `two words = both must appear · "in quotes" = that exact phrase · -word = leave it out`. (c) drop `autocomplete="off"` (nothing here is sensitive), or keep the last 10 queries in `localStorage` as a datalist.
- **Effort:** S (b,c) / M (a) · **Value:** med · **Confidence:** high

### BROLL-26 (IX): the unattended restart path is backend-blind and hardcoded to one machine
- **Lens:** resilience · **Who:** owner, developer
- **Where:** `broll/indexer/watchdog.ps1:102-108`, `:30,41,106-107`; `run_queue.py:163-171`; `parallel_claude.py:176,180`; `local_vlm.py:122`; `config.py:245`
- **Today:** the watchdog restarts with `--model haiku --api-workers 12`, and `stage_cmd` routes to `parallel_claude.py` whenever `api_workers > 1`. On the shipped default (`indexer.backend: local`) the overnight log's first line is therefore `auth: NO API KEY - authentication_error: no Anthropic API key...` for a run that will bill nothing, and 12 threads (an Anthropic-only ceiling) drive a llama-server started with `-np 1`. The script also still hardcodes `E:\broll-queue\watchdog.log`, the db path and both redirects, despite `-Python` having been de-hardcoded for COMMERCIAL_READINESS item 10.
- **Proposed:** have `run_queue`/`parallel_claude` read `cfg.indexer.backend`: print the local banner, cap workers at the server's slot count, skip `describe_auth` entirely. Read the watchdog's paths from `data_root`/`db.path` rather than the literals.
- **Effort:** M · **Value:** med-high · **Confidence:** high

### BROLL-27 (IX): the local category assigner is rebuilt per clip, degrades silently, and its score is thrown away
- **Lens:** both · **Who:** developer
- **Where:** `broll/indexer/broll_index/local_vlm.py:509` (`CategoryAssigner(...)` inside the per-video path), `:511-513`; `compact_format.py:257-262` (`self.fastembed_error`, read by nothing); `storage/sqlite_backend.py:147-193`; `eval/local_vlm/score.py:504-506`
- **Today:** fastembed's `TextEmbedding` is loaded and the whole taxonomy re-embedded for every clip in a multi-thousand-clip queue. The constructor's `except Exception` falls back to TF-IDF and stores the reason in a field nothing reads, so a transient first-run download failure files one clip by keyword match while its neighbours were filed by embedding, silently. And the evidence is discarded: `category_score`/`category_method` are computed and dropped, because no column exists - the eval harness scores exactly these fields and production keeps none of it.
- **Proposed:** build the assigner once per run (module-level cache keyed on the taxonomy) and pass it in; log `fastembed_error` once at WARNING; add `category_score`/`category_method` columns so a weak assignment is auditable.
- **Effort:** M · **Value:** med · **Confidence:** high

### BROLL-28: four smaller ones, same shape (state or config that nothing surfaces)
- **Lens:** usability · **Who:** owner, editor
- **`BROLL_CREATORS_SHARES` unset files the customer's own shoots as "Downloads"** - `broll/web/app/config.py:157-166`, `routes_api.py:262-266`. The default is deliberate and its reasoning is sound, but the failure is silent in the other direction and is the first screen a second customer sees. Fix: a `hint` on `/api/tree` when the set is empty and `videos` holds more than one share, rendered for admins: `Every share is filed under Downloads. Set BROLL_CREATORS_SHARES to the shares this customer shot themselves.` **S / med / high.**
- **"already in the archive: clip #4821" is a number the editor cannot use** - `static/ingest.js:1049-1055`. The row is unticked for them, which is right, and to check the call they must close the drawer and search by hand. Fix: link the name to `#v=4821` and drop the id: `already in the archive as [ A001_C003.MP4 ] - tick it to add this copy anyway`. **S / med / high.**
- **Mount paths are only reachable by hand-editing a JSON file** - `static/index.html:316-323`, `broll_server.py:219`. Settings names `~/.broll-companion.json` with no example of its shape and no absolute path an editor could find. Fix: show each share's resolved mount from `/status` beside its row (`ff3 -> not mapped on this computer`) and a copyable two-line sample with the real path filled in; longer term this is a tray Settings row (CR-88). **S / low-med / high.**
- **(IX) three indexer paper cuts** - `run --help` still says "drain the job queue through probe/proxy/frames/**claude**" and offers `--model {haiku,sonnet,fable}` on a build whose default backend is local and whose `MODEL_MAP` also has opus (`cli.py:358-361`, `claude_client.py:50-55`); `seconds_until_reset` parses the reset hint against local `datetime.now()` (`claude_client.py:252`), so a skewed clock makes `run_queue` sleep the wrong amount, bounded but silently; `_ensure_schema` applies `schema.sql` only when `user_version == 0` (`sqlite_backend.py:58-63`), so a DB one migration behind is caught later by `bump_search_generation` raising mid-run - a startup `PRAGMA user_version` check naming `broll-index migrate` is cheaper. **S / low-med / high.**

## Still open from 08-28
- MEDIA-1 (rebuilt index serves an uncurated clip): BUILT - `member_video_id` and `_member_id`/`share_video` re-check by `(share, rel_path)`.
- MEDIA-3 (staging never cleaned up): not built - nothing under `broll_ingest.py` deletes a staging directory.
- MEDIA-7 (no spend cap on the Claude indexer): not built. BROLL-11 is the visibility half.
- MEDIA-31 (`view_count` unthrottled): not built. The same counter is also inflated by the editor's own `[ open ]` (`clientfolders.js:285`), which is the signal they read to know whether the client looked; a "preview as the client sees it" route that does not `record_view` fixes that half.
- MEDIA-32 (share links default to never-expires): not built - folded into BROLL-19's proposal.

## Cross-cutting notes
- **SERVER/deploy agent:** BROLL-1 is a `publish_db.py` change, not a b-roll one; the music half of that file already models the fix. Its broll branch also still prints "restart the dashboard container if the app does not pick it up" - b-roll has no equivalent of musicweb's `db._check_swapped` (CR-67 seam 11).
- **DASHBOARD agent:** `broll_status`/`music_status` are computed then read by nothing but a boolean in `ui.py` (`app.py:1209-1224`); Timeline Cards keeps a `_detail` string and the other three do not. One "mounted apps" panel on Settings plus BROLL-2's registry rows covers b-roll, music and ytdl at once.
- **COMPANION agent:** `broll_ingest.upload_slot`'s 409 comment describes a client-side retry that does not exist (BROLL-5); worth checking whether `music_ingest` assumes the same of `music.js`.
- **Whoever owns CR-90:** there is no `unicodedata` call anywhere under `broll/web/app/`. BROLL-14 is the one verified, but `ingest_batches._taken_names`/`_allocate` and `client_folders`' `(share, rel_path)` fallback compare filenames the same way.
