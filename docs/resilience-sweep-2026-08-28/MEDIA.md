# B-roll and Music platforms (MEDIA)

## Summary
The companion-side ingest orchestrator is among the most carefully built things in this repo - checkpointed to disk at every stage, idempotent re-claim, per-item and per-upload attempt caps, an origin allow-list, a root guard before every write - and CR-54 already closed six of its worst paths. What is missing is the *end* of the lifecycle: nothing anywhere deletes a staging directory, so a feature whose plan promises "staging retained 7 days" retains it for ever inside the archive until its own free-space floor refuses the next drop; and `stop()`'s promise to kill the ffmpeg child is not implemented at all (`self._child` is never assigned). The most serious single defect is public: `client_folders.resolve_items` keeps a by-id row when the identity check fails, so an index rebuild can serve a client a clip nobody curated - the fourth site of CR-63/broll-1. The cheapest high-value win is publishing the loopback origin allow-list in `GET /status`: it is computed once at tray start and never again, so a dashboard URL change 403s every Send-to-Resolve in the fleet with a message that names nothing.

## Findings

### MEDIA-1: a rebuilt index can serve a client an uncurated clip
- **Lens:** pitfall
- **Where:** `broll/web/app/client_folders.py:530-543` (vs the fixed `member_video_id:472-497`), `broll/web/app/routes_share.py:104`
- **Scenario:** the index is rebuilt (rebuilds reuse low ids - the suite asserts this) and a clip that was curated into a client folder has since left the archive, so its old id names a different clip.
- **Today:** `resolve_items` reads by id, tries `by_name` when the identity differs, and **keeps the by-id row anyway when `by_name` is None**. `public_video_ids:571-576` is built from that and `_member_id` authorises on it, so the client's page draws and `/share/<token>/media/proxy/<id>.mp4` streams footage nobody shared. `test_client_folders.py:256-299` covers only the case where the curated clip survives, so the suite is green.
- **Proposed:** when `by_name` is None and the by-id identity disagrees, drop the item / report `missing` - the verdict `member_video_id` already gives. Add the "curated clip deleted, id reused" test.
- **Effort:** S   **Severity:** critical   **Confidence:** high
- **Related:** CR-63 (broll-1) fixed three of four sites.

### MEDIA-2: `stop()` cannot kill the ffmpeg child, because there has never been one
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/broll_ingest.py:609` (`self._child = None`), `:2553-2561` (`_kill_child`), `:1587-1594` (`stop()`'s docstring: "setting this is what kills the ffmpeg child"), `:1600-1606` (`join(timeout=5)` gives up), `app.py:6491-6502` (same claim). Verified: no code path anywhere in the package assigns a Popen to `_child`.
- **Scenario:** an editor drops a 90-minute mix (or a 40 GB original), then quits the tray four minutes into the decode; or an admin cancels the batch from the dashboard.
- **Today:** ffmpeg runs under `subprocess.run(timeout=...)` on a daemon thread (`music_clap_sidecar.py:630-640` 900 s; `broll_ingest_media.RUN_TIMEOUT_SECONDS` for b-roll). `_kill_child` is a no-op, `join` abandons the thread after 5 s, and an orphaned `ffmpeg.exe` keeps running past tray exit holding a handle on the staged file (which then blocks any later staging cleanup on Windows). Cancel is equally inert: the UI says "cancelling" for up to fifteen minutes.
- **Proposed:** have the media runner publish its Popen back to the orchestrator through a `child_sink` callback (the pattern `bpg.py:665-770` already uses) so `_kill_child` is real; keep the existing `stop_event` check. Fix the two docstrings that assert the current behaviour.
- **Effort:** M   **Severity:** high   **Confidence:** high

### MEDIA-3: staging is never cleaned up, and the plan says it is
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/broll_server.py:796-813`, `broll_ingest.py:1246-1330` (dirs created), `:2622-2633` (`_space_refusal`); no `rmtree` of a staging dir exists in the companion (grep). `docs/BROLL_INGEST_PLAN.md:219,259` promise "keep staged outputs (7 days)" / "staging retained 7 days after live".
- **Scenario:** an editor drops 40 clips a week for a month.
- **Today:** every batch leaves `<local_root>/Assets/B-roll Archive/.ingest/<staging_id>/` holding uploaded originals, proxies, posters, sprites and frame sheets, for ever, and `_staging` keeps every entry in the state file across restarts. When free space drops below the 20 GB floor, `prepare` 507s and the gate blocks with "Not enough space where the clips would be staged ... Free some space and it will continue" - naming a dot-folder the editor has no UI to see or clear. The feature fills its own disk and blames the editor.
- **Proposed:** implement the documented retention - each tick, delete staging dirs whose batch ended more than N days ago (`<kind>_ingest_staging_retention_days`, default 7) and prune their `_staging` entries; report `staging_bytes` in the ingest report section; make the space refusal say how much of the shortfall is `.ingest` and offer a "clear finished staging" action.
- **Effort:** M   **Severity:** high   **Confidence:** high

### MEDIA-4: `publish_db --which music` still clobbers the live queue and every fleet-ingested track
- **Lens:** safeguard
- **Where:** `server/publish_db.py:84-105`, `:111`, `:313-329`; the rule it breaks is stated in `music/web/musicweb/drain.py:1-18` and `docs/INDEXERS.md:229-251`
- **Scenario:** the operator re-indexes on the base rig and runs `publish_db.py --which music --apply`.
- **Today:** the swap renames the uploaded file over the live one. The only content check is `shrink_refusals` over `tracks/windows/tags` at a 10% floor; `ingest_queue` is deliberately excluded (correctly - it would false-positive). So every `pending`/`failed` journal row an editor queued, and every track the companion fleet-ingest wrote into the live DB since the base rig's copy diverged, is destroyed silently as long as under 10% of tracks are lost. The "never push a drained music.db back over the live one" rule exists only in prose.
- **Proposed:** in `read_live_counts` also read `count(*) FROM ingest_queue WHERE state='pending'` and `MAX(analyzed_at)`; refuse the music swap when the live DB holds pending rows or tracks newer than the candidate's newest, with `--allow-clobber-queue` as the deliberate escape.
- **Effort:** S   **Severity:** high   **Confidence:** high
- **Related:** CR-20, `drain.py` (the merge path that exists but is not the enforced one).

### MEDIA-5: a transient Hugging Face failure silently swaps the CLAP checkpoint
- **Lens:** pitfall
- **Where:** `music/indexer/music_index/clap_model.py:16-27`, `config.py:72-73`, `index_music.py:457`; and the un-checked twin, `music/web/musicweb/ingest_batches.py:727-731,764-772`
- **Scenario:** a drain runs while HF is rate-limiting or the cache dir is full, so `ClapModel.from_pretrained('laion/larger_clap_music_and_speech')` raises.
- **Today:** `except Exception` falls back to `laion/clap-htsat-unfused`, prints one line and carries on. Both are 512-d, so nothing downstream can see it: the fallback's vectors are upserted, `db.set_meta(con,'model', ...)` rewrites the library's declared model, and `retag()` re-scores the whole library with the wrong text tower. `music_clap/music_models.py:41-47` says outright that nothing can detect this. The fleet `result` route has the same hole from the other side: `_library_dim` compares width only and `body.model` is stored but never compared, so a companion carrying new weights at the same dim mixes two embedding spaces into one index.
- **Proposed:** refuse rather than fall back when the DB already declares a different model (keep the fallback for an empty index, behind `--allow-model-fallback`); and in `result`, compare `body.model` with the library's dominant `tracks.model` and 409 `reason:'model_mismatch'` - which the companion already treats as non-transient (`music_ingest.py:414-418`).
- **Effort:** S   **Severity:** high   **Confidence:** high

### MEDIA-6: the loopback origin allow-list is frozen at tray start
- **Lens:** pitfall / user-error
- **Where:** `companion/src/ccsync_companion/broll_server.py:1975-1989` (computed once in the constructor), `app.py:5602-5626` (started once, with a config snapshot), `loopback_guard.py:224-242`, refusal text `:111-112`
- **Scenario A:** the dashboard moves to a new Tailscale name and `dashboard_url` changes. **Scenario B:** a fresh install's tray starts before sign-in, so `dashboard_url` is blank and no manifest is cached yet.
- **Today:** nothing recomputes the list. Every browser POST then 403s with "this request was refused by the CC Sync companion - see its log", for the whole session, on every machine, until each editor restarts their tray. The log line at `:2100-2106` has the exact diagnosis ("browser origins allowed: NONE -- dashboard_url is blank") and no editor will read it.
- **Proposed:** recompute per request from the live config plus cached manifest (mtime-cached); publish the allow-list and `dashboard_url` in `GET /status`, which needs no Origin and is already the SPAs' self-test, so the page can say "your companion trusts https://a, you are browsing https://b"; log a WARNING every tick while the list is empty and surface it in the report health section.
- **Effort:** S   **Severity:** high   **Confidence:** high
- **Related:** `docs/LOOPBACK_API.md`, CR-54 trust-model-9.

### MEDIA-7: no spend cap on the Claude indexer, and the one documented lever ships off
- **Lens:** user-error
- **Where:** `broll/indexer/broll_index/config.py:126` (`max_sheets_per_video: int = 0`), `broll/indexer/config.example.yaml:90-93`, `broll/docs/indexing-api.md:81-85`
- **Today:** no `max_cost` / `budget` / `max_calls` exists; accounting is post-hoc (`usage.jsonl` → `tools/cost_report.py`). The docs call capping sheets "the single biggest lever on total spend" (9% of videos = 36% of calls) and the default is off, absent from the example `sampling:` block. A `--model opus` typo on a 2,000-clip queue meets nothing. CR-1 moved billing to an org key; it added no ceiling.
- **Proposed:** default `max_sheets_per_video: 24` in both files; print an estimate from `usage.jsonl` and confirm before dispatch; `--max-spend-usd` that halts the pool with the queue resumable.
- **Effort:** M   **Severity:** high   **Confidence:** high

### MEDIA-8: every live client-share token is written to the container's access log
- **Lens:** pitfall
- **Where:** the token is a path segment (`broll/web/app/routes_share.py:119,135,145,209`); `server/install_dashboard_app.py:1000-1016` runs uvicorn with the access log ON, five 20 MB files
- **Today:** every page load and every sprite/poster/range request logs the full token, so `docker logs` or any support bundle harvests every live link. `docs/CLIENT_FOLDERS.md:229-236` models the exposure as "a copy of `client_shares.db` is a copy of every live link" and never mentions the log, which is the same thing with weaker permissions.
- **Proposed:** an access-log filter rewriting `/broll/share/<token>` to `/broll/share/<redacted>`; document it in CLIENT_FOLDERS §4.
- **Effort:** S   **Severity:** high   **Confidence:** high

### MEDIA-9: an orphaned llama-server keeps 4-12 GB of VRAM after a hard kill
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/broll_vlm/local_vlm.py:160-186` (spawn, no job object), `:187-200` (atexit only), `broll_vlm_sidecar.py:616-625`; the graceful path (`app.py:6491-6502`, `broll_server.py:2128-2142`) is thorough
- **Scenario:** the editor ends the tray from Task Manager because "it was using the GPU", or it crashes.
- **Today:** llama-server survives holding the model. Nothing records its pid or port and nothing scans for a stray one at boot - the next start calls `_free_port()` and launches a *second* server. The editor sees Resolve refusing playback on a GPU with no visible owner, and the process that could explain it is the one they killed.
- **Proposed:** write `{pid, port, started_at, model}` to `~/.ccsync/state/broll_vlm_server.json` at spawn (deleted on clean stop) and kill any recorded pid whose image still matches at every companion start; on Windows put the child in a Job Object with `KILL_ON_JOB_CLOSE`.
- **Effort:** M   **Severity:** high   **Confidence:** high

### MEDIA-10: a batch that finishes during a dashboard blip is re-claimed and fails entirely
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/broll_ingest.py:2460-2486` (`_maybe_finish` clears `_batch` unconditionally), `:391-402` (`release` swallows every transport error)
- **Scenario:** a three-hour 40-clip batch finishes as the tailnet flaps or the container restarts.
- **Today:** `release()` logs "could not release batch X" and returns; `_maybe_finish` forgets the batch. The server holds it as `indexing` until the 300 s lease lapses, then requeues it; a re-claim finds a batch whose staging this side has forgotten, and on any other machine the sources do not exist at all, so `_crunch_item:1893-1896` fails every item with "the source file is not on this machine any more". Three hours of GPU becomes 40 failures.
- **Proposed:** persist `pending_release: {uid, state, summary}` in the state file, retry it each tick until accepted or 410, and only then clear `_batch`. The module's own docstring already states the rule: a latch that lives only in memory is not a latch.
- **Effort:** S   **Severity:** high   **Confidence:** high

### MEDIA-11: `mark_uploaded` answering anything but 200/409 loops for ever
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/broll_ingest.py:2393-2395` (the `else` branch: one log line, no counter) vs the capped 409 branch `:2374-2392` and the capped rclone-failure branch `:2332-2357`
- **Scenario:** the dashboard is redeployed to a version whose fleet route 500s, a proxy answers 502, or the identity token expires into a 401.
- **Today:** every tick re-posts and does nothing else. The item stays at `uploading`; `_next_item:1868` skips `uploading`; `_maybe_finish` never fires; the heartbeat holds the lease - and per CR-54's own note, every later drop on that machine is refused with "already indexing another batch".
- **Proposed:** count these with the existing `upload_attempts`, fail at the cap with the status in the message, log at WARNING with the body. Three lines.
- **Effort:** S   **Severity:** high   **Confidence:** high
- **Related:** CR-54 (comp-loopback-3) capped the two neighbouring branches and missed this one.

### MEDIA-12: pulling the card out fails every remaining clip and burns its attempts
- **Lens:** user-error
- **Where:** `companion/src/ccsync_companion/broll_ingest.py:1893-1896`, `MAX_ITEM_ATTEMPTS = 2` at `:113-118`, gate `:837-851` (`_root_present` checks the TREE, never the source), picked roots `:1178-1226`
- **Scenario:** an editor picks 400 clips off an SD card or portable SSD and unplugs it (or the drive sleeps, or the hub drops) - the likeliest physical event in this feature.
- **Today:** each item fails "the source file is not on this machine any more", two attempts each, so the whole batch is failed and released within a couple of ticks. Re-plugging does nothing; they must drop all 400 again.
- **Proposed:** before failing on a missing source, ask whether its *picked root* is still present (`_picked_roots` holds it). If the root is gone, fail nothing: publish a `source-absent` gate state ("waiting: the drive you picked these clips from is disconnected"), leave items at their checkpoints, keep heartbeating. This is CR-44's lesson (a whole-scope disappearance is not N deletions) applied to ingest.
- **Effort:** M   **Severity:** high   **Confidence:** high

### MEDIA-13: a music track row whose audio never lands is permanent, and blocks its own re-ingest
- **Lens:** pitfall
- **Where:** `music/web/musicweb/ingest_batches.py:741-746,995-1002`; `music/web/musicweb/db.py:529-553`; `companion/src/ccsync_companion/music_ingest.py:253-256`
- **Scenario:** `result` lands (row written, name allocated, searchable), then the editor unplugs the drive or the tray dies before the rclone upload.
- **Today:** `release()` deliberately keeps the `tracks` row. The track is searchable, `/api/audio` 404s (`routes_media.py:98-99`) and `/music/send` dead-ends. Re-dropping the same file then hits `find_reencode` (`db.py:549-553`), which matches stem+duration with **no `is_file()` check** (unlike its digest sibling at `:607`), so the editor is told it is already in the library: a phantom that cannot be fixed from any UI.
- **Proposed:** give `find_reencode` the same `resolve_path(...).is_file()` filter, and surface "indexed, audio missing" in the ingest panel (the `ingest_items` state already says `indexed`).
- **Effort:** S   **Severity:** high   **Confidence:** high
- **Related:** new angle on the MUSIC-ING family; not in the ledger.

### MEDIA-14: an unrate-limited share link can starve the single-worker dashboard
- **Lens:** pitfall
- **Where:** `broll/web/app/routes_share.py:209-238` (sync `def`), `broll/web/app/media.py:20-29,75-80` (`StreamingResponse` over a sync generator), `dashboard/src/ccsync_dashboard/app.py:1030` (`workers=1`)
- **Today:** each in-flight byte-range holds an anyio worker thread (limiter 40) in the same process that serves fleet reports and the transfers poll. `docs/CLIENT_FOLDERS.md:248-251` dismisses this as a bandwidth question; it is a liveness risk for "the thing that tells everyone whether their footage is syncing", triggerable from the open internet by one forwarded link.
- **Proposed:** async routes with an async file iterator, or a dedicated `CapacityLimiter`, plus a per-token concurrency cap (~8). Cheap version: the limiter alone.
- **Effort:** M   **Severity:** high   **Confidence:** high

### MEDIA-15: a publish swaps `broll.db` but never the id-keyed sprites and posters
- **Lens:** pitfall
- **Where:** `server/publish_db.py:82-100` (`SPECS` = the `.db` only), `broll/web/app/routes_media.py:50-58`, `routes_share.py:225,236`
- **Today:** proxies resolve by `archive_path` and survive a renumbering; sprites and posters resolve by `<id>.jpg` alone, so every thumbnail and hover-scrub silently points at a different clip, on the search UI and on public client links. Nothing pushes or checks those directories, and the shrink guard compares row counts, which look normal.
- **Proposed:** store a per-row relative sidecar path (the `archive_path` treatment), or add a `--with-media` stage that ships sprites/posters in the same atomic swap and REFUSES a publish whose `max(videos.id)` moved without them.
- **Effort:** M   **Severity:** high   **Confidence:** high
- **Related:** CR-10 - the DB publish chain itself (checkpoint, `sqlite3.backup()`, `quick_check`, shrink guard, atomic rename) is sound.

### MEDIA-16: the indexer watchdog cannot see an orphaned worker, so a restart re-bills the clips in flight
- **Lens:** pitfall
- **Where:** `broll/indexer/watchdog.ps1:60-61,102-108` (liveness = `CommandLine -like '*run_queue.py*'`), `run_queue.py:142-153` (bare `Popen`), `parallel_claude.py:116-123`
- **Today:** if `run_queue.py` dies while `parallel_claude.py` holds up to 12 API calls, the watchdog sees "no run_queue" and starts a second run; the docstring names the cost - "anything mid-flight gets described twice and paid for twice".
- **Proposed:** widen the probe to `run_queue.py|parallel_claude.py|parallel_local.py`, or write a pidfile. BROLL-IDX-2 hardened *which tree* runs, not whether a run is alive.
- **Effort:** S   **Severity:** high   **Confidence:** high

### MEDIA-17: on a base rig, staging lands inside the live library and the music sweep indexes it
- **Lens:** user-error
- **Where:** `companion/src/ccsync_companion/broll_server.py:796-813` and `config.py:472-477,1104-1108` ("THE BASE RIG NEEDS THIS SET"); `ingest_kinds.py:145-151`; `music/indexer/music_index/config.py:62` (`EXCLUDE_DIRS = {'_stems'}`), `index_music.py:54-62`
- **Scenario:** the owner (or a new customer's base rig) drags clips onto the b-roll or music page from the machine whose `local_root` IS the NAS share.
- **Today:** with `<kind>_ingest_staging_dir` blank, staging is `<share>/Assets/{B-roll Archive,Music}/.ingest`, i.e. on the NAS: every original crosses SMB twice, the free-space floor measures the NAS, and (with MEDIA-3) it accumulates on the shared dataset. Worse for music, `EXCLUDE_DIRS` has no dot-directory rule, so a later `index_music.py` sweep indexes every staged copy as a library track at `.ingest/<staging-id>/foo.wav` - a duplicate row at a path that is orphaned the moment staging is cleaned. The requirement exists only as a config comment; nothing checks it.
- **Proposed:** skip any path component beginning with `.` in `iter_files` / `music_index/ingest.py:60`; and in `build_ingest_capabilities`, refuse with a `reasons` string (the page already renders them) when the staging root resolves onto a network path or under the share root on a base rig - better, default to `%LOCALAPPDATA%\ccsync\ingest` when the tree is remote and keep the key as the override.
- **Effort:** S   **Severity:** med-high   **Confidence:** high

### MEDIA-18: a reused `videos.id` plus never-deleted artefacts = a clip described from a deleted clip's frames
- **Lens:** pitfall
- **Where:** `broll/schema.sql:5` (no `AUTOINCREMENT`), `broll/indexer/broll_index/storage/sqlite_backend.py:124-133` (`delete_video` removes rows only), `pipeline.py:208-211,284-291` (`sheets/<id>/_complete` short-circuit)
- **Today:** pruning the highest ids and re-scanning hands a new clip an old id; the `_complete` marker makes `stage_describe` bill a full describe of the *previous* clip's contact sheets, and the wrong description reaches the DB that gets published.
- **Proposed:** `delete_video` unlinks `proxies/`, `sprites/`, `posters/`, `sheets/<id>/`; write `(share, rel_path)` into `frames.json` and invalidate the marker on disagreement.
- **Effort:** M   **Severity:** high   **Confidence:** med-high
- **Related:** R2 (same root cause, different artefact).

### MEDIA-19: a CUDA OOM parks a good track as `failed` on the live index
- **Lens:** pitfall
- **Where:** `music/indexer/index_music.py:265-270,275-288`; `music/web/musicweb/drain.py:414-430`
- **Scenario:** someone starts a render (or the b-roll Qwen indexer) on the base rig while a drain runs, and `clap.embed_audio` OOMs on track 40.
- **Today:** the bare `except Exception` treats it exactly like a corrupt file - `_park()` marks the row failed, and `bundle_failures` carries that verdict onto the live index (the CR-64 fix), so the editor sees "failed" for a perfectly good file and only `--retry-failed` undoes it. An OOM is environmental and usually affects every remaining row.
- **Proposed:** classify the exception - on `torch.cuda.OutOfMemoryError` / `RuntimeError('CUDA out of memory')`, abort the drain leaving rows `pending`; at minimum never export an OOM verdict into `bundle_failures`.
- **Effort:** S   **Severity:** med-high   **Confidence:** high

### MEDIA-20: `SqliteBackend` sets no `busy_timeout`, and a lock discards paid-for API work
- **Lens:** pitfall
- **Where:** `broll/indexer/broll_index/storage/sqlite_backend.py:53` (Python's 5 s default) vs `embed_transcripts.py:42` and `normalize_search.py:44-45` (60-120 s)
- **Today:** 6 processes plus 12 threads write against long transactions. On timeout `write_index_result` raises "database is locked", `parallel_claude._process_one:95` records `crash:`, the row stays `proxied` - and every API call already paid for that clip is thrown away.
- **Proposed:** `PRAGMA busy_timeout = 120000` in `__init__`. The same gap with no money attached exists at `broll/web/app/db.py:238-247` and `client_folders.py:162-166`.
- **Effort:** S   **Severity:** med-high   **Confidence:** high

### MEDIA-21: a Mac editor's NFD filename is never normalised in the music ingest path
- **Lens:** pitfall
- **Where:** `music/web/musicweb/db.py:483-502` (`safe_upload_name`), `:521-526` (`norm_stem`), `ingest_batches.py:189-202,229-239,925-931`. No `unicodedata.normalize` exists anywhere in `musicweb` or the companion's music modules (grep).
- **Today:** a Mac drops `Matej Šimalčík - Theme.wav`; the NFD spelling is reserved by `allocate_name`, `_taken_on_disk` compares NFD against an NFC library, `norm_stem` derives a different key so the re-encode defence misses, and `mark_uploaded`'s `path.stat()` tests the NFD path against what rclone actually wrote - a 409 `not_uploaded` loop on a file that is on the disk.
- **Proposed:** NFC-normalise inside `safe_upload_name` and `norm_stem` (both are compare/store values, never a path something opens - CR-90's rule exactly).
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** CR-90, `docs/GOTCHAS.md` §17.

### MEDIA-22: revoking a share link does not stop playback for an hour
- **Lens:** pitfall
- **Where:** `broll/web/app/routes_share.py:206` (`_MEDIA_CACHE = "private, max-age=3600"`) vs the promise at `:35-38` and `docs/CLIENT_FOLDERS.md:237-241`
- **Today:** the page JSON is `no-store`, but proxies, sprites and posters carry an hour of private cache, so a client mid-session keeps playing and the browser may not re-ask at all. Revoke is the control the design leans on for "the link got away".
- **Proposed:** `max-age=60`, or `no-cache` + ETag (keeps the bandwidth win, re-validates); correct both docstrings.
- **Effort:** S   **Severity:** med   **Confidence:** high

### MEDIA-23: `remove_item` still matches on the raw stored id
- **Lens:** pitfall
- **Where:** `broll/web/app/client_folders.py:436-444` (and `set_note:448-454`), `routes_client_folders.py:237-245`, `static/clientfolders.js:569`
- **Today:** the card popover sends the current index id, so after a renumbering rebuild the tick correctly shows the clip as held, the editor clicks to pull it out of a live client folder, and gets `404 "that clip is not in this folder"` while the client keeps seeing it.
- **Proposed:** match `video_id = ? OR (share = ? AND rel_path = ?)`, resolving identity the way `routes_client_folders.py:82-88` already does.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** CR-63 fixed "all three sites"; these were the fourth and fifth.

### MEDIA-24: a project built from on-demand fetched archive clips is not portable
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/broll_server.py:721-765`, `broll_fetch.py:1-31` (deliberately not a lane, nothing recorded); no archive awareness in `fixer.py` (grep)
- **Scenario:** editor A inserts three archive clips into a shared timeline; editor B opens the project.
- **Today:** the clips live under `Assets/B-roll Archive`, which no lane syncs, so for B they are simply offline media with no hint that one command could fetch them - and if A ever clears their archive folder to reclaim disk, they go offline for A too. Nothing records which clips a machine fetched.
- **Proposed:** record each successful fetch in `~/.ccsync/state/broll_fetched.json`; teach the fixer that an offline path under `Assets/B-roll Archive` is *fetchable*, not broken - one `broll_fetch.poll_fetch` per missing clip within the existing concurrency cap, reported in the popup as "fetching 3 b-roll clips this project uses". Turns the commonest "my timeline is offline" call into a self-heal.
- **Effort:** M   **Severity:** med   **Confidence:** med-high

### MEDIA-25: one fetch concurrency cap is shared by archive, music and ytdl pulls, with no cancel
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/broll_fetch.py:50-60` (`MAX_CONCURRENT_FETCHES = 2`, one registry for three callers), `:361-385`
- **Today:** two 40 GB originals in flight make every music/ytdl/b-roll click for the next hour answer "this machine is already downloading as much as it will at once - try again when the clip in progress has finished", and no UI can cancel a running fetch (only `stop_all()` at shutdown). rclone's `--timeout 5m` bounds a stalled peer, not a slow legitimate one.
- **Proposed:** make the cap size-aware - reserve one slot for files under ~200 MB so a music cue is never stuck behind a camera original - and add `POST /broll/cancel_fetch` plus a cancel affordance in the toast (`FetchJob.cancel()` already exists and is safe: rclone writes `.partial`).
- **Effort:** S   **Severity:** med   **Confidence:** high

### MEDIA-26: music ingest runs CLAP inference inside the tray process
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/music_clap_sidecar.py:568-588,804-826`, providers at `:532-543`; contrast `broll_vlm_sidecar.py:612-624` (a separate, killable process)
- **Today:** `onnxruntime.InferenceSession(...).run()` runs inline on the ingest thread, so a native fault - an onnxruntime assert, an unsupported ISA path, a native allocation failure - takes down the whole companion: lanes A/B/C, the Resolve watcher and the loopback, for a music drop. `stop_server()` only drops a Python reference. `_providers_for_session` will also pick CUDA/DirectML with no VRAM check and no coordination with the b-roll VLM server (music's kind is `blocks_proxies=False`), so on a GPU base rig the two contend.
- **Proposed:** run `embed_windows` in the one-shot child pattern `music_worker` / `music_server.call` already use (re-enter the frozen exe with a `--music-embed` flag) - which also makes MEDIA-2's kill real for music.
- **Effort:** L   **Severity:** med   **Confidence:** med-high

### MEDIA-27: the two doors disagree about long files, and one fabricates a duration
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/music_clap_sidecar.py:66-71,829-886` vs `music/indexer/music_index/audio.py:31-41` (`max_seconds=None`)
- **Today:** the companion truncates at `MAX_DECODE_SECONDS` and then reports `samples/sample_rate` - exactly `7200.0` for anything longer - as the row's duration, while the base rig records the true length. Duration is one of the two duplicate-defence keys (`find_reencode`, ±2 s), so every over-2 h file ingested by a companion collides with every other one whose stem normalises alike. The decode also buffers the whole signal (~2.8 GB peak for 2 h) in the tray process.
- **Proposed:** give both paths the same cap; when it bites, refuse the file ("longer than the indexer will analyse") rather than recording a fabricated duration; stream the decode in blocks.
- **Effort:** S (parity) / M (streaming)   **Severity:** med   **Confidence:** high

### MEDIA-28: `UploadQueue._loop` can wedge on an unexpected exception
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/broll_upload.py:424-472` (no outer try/except; only the `cfg_fn` read is guarded), `_active` cleared only in `_finish:412-422`
- **Today:** `run_upload` never raises, but `build_upload_command` → `RcloneTuning.from_cfg` runs on a hand-editable config and `verify_upload`'s runner is a seam. Any exception between `_next_job` and `_finish` kills the thread with `_active` still set, after which `_ensure_thread` restarts a loop that can never pick a job. Uploads stop silently and the batch parks at `uploading` for ever.
- **Proposed:** wrap the loop body so an exception calls `_finish(job, False, str(exc))`; have `_ensure_thread` clear a stale `_active` whose thread is dead. The lanes and the ingest tick already carry exactly this guard.
- **Effort:** S   **Severity:** med   **Confidence:** med-high

### MEDIA-29: the music library's location is server-supplied on upload and hardcoded on fetch
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/music_ingest.py:62,168-169` (server-supplied `library_remote_rel`) vs `music_server.py:55` and `broll_fetch.py:69` (`"Assets/Music"` literals), against `music/web/musicweb/config.py:76-96` (`MUSIC_LIBRARY_ROOT`, free-form)
- **Today:** for a customer whose `MUSIC_LIBRARY_ROOT` is not `<tree>/Assets/Music`, uploads still land (the server names the destination) but "+ Resolve" resolves the wrong local path and the on-demand fetch pulls the wrong remote path: "file not found - is the share mounted?" or an endless "syncing the track to this machine".
- **Proposed:** publish the library's tree-relative path on `/api/v1/site` (or persist the claim response's `library_remote_rel`) and have `default_music_mount` / `build_send_response` read it, falling back to the literal.
- **Effort:** M   **Severity:** med   **Confidence:** high
- **Related:** `docs/TREE_LAYOUT_AGNOSTICISM.md` - a concrete instance.

### MEDIA-30: a heartbeat outage lets a machine keep crunching a batch it has lost
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/broll_ingest.py:2511-2540` (a failed heartbeat is debug-logged and the loop continues), lease 300 s
- **Today:** "a NAS blip is not a stop" is right for a blip, but nothing counts consecutive failures: during a 40-minute outage the machine pins the GPU and keeps uploading against a lease the server has expired and possibly reassigned, so two machines can write the same archive rel paths.
- **Proposed:** after `lease_seconds` of consecutive failures, stand down - stop the model server, pause uploads, publish "waiting: cannot reach the dashboard" - and resume only after a successful `_reclaim` (already idempotent).
- **Effort:** S   **Severity:** med   **Confidence:** high

### MEDIA-31: three smaller ones, same shape (state that outlives what it describes)
- **Lens:** pitfall / safeguard
- **`full_hash` is never invalidated** - `broll/indexer/broll_index/scanner.py:209-221` refreshes `hash`/`size_bytes` on a size change but never clears `full_hash`, so `duplicates.py:126-135` verifies a re-encoded file against a digest of content that no longer exists. `duplicates.py:5-9` notes the false-positive direction *loses footage*. Fix: `full_hash=None` in the `fields` dict when `reusable` is false. **S / med / high.**
- **The ingest picked-root allow-list never expires** - `broll_ingest.py:1178-1243`. CR-54 (comp-loopback-6) built it so only picker-chosen paths can be ingested, but entries persist for the machine's life: an editor who once picked `E:\` permanently authorises the *next* card at E: too, which combined with trust-model-9 is a standing write channel into the shared archive. Fix: timestamp roots, expire after 24 h, record the volume serial. **S / low-med / high.**
- **The only public write is unbounded** - `routes_share.py:153` → `client_folders.py:579-583` increments `view_count` per request with no throttle, so one leaked link is an unbounded write stream into `client_shares.db` (the file holding every customer's live links) and any mail scanner inflates the "did the client look?" signal. Fix: one increment per token per N minutes via `last_viewed_at`. **S / med / high.**

### MEDIA-32: two publish/expiry defaults that age badly
- **Lens:** user-error
- **Every share link defaults to "never expires"** - `broll/web/app/client_folders.py:221-247` (`expires_at=None`), `static/clientfolders.js:328-331` (first option is "keep"). `docs/CLIENT_FOLDERS.md:293-295` says expiry and revoke are the controls, but the create path has no expiry field at all. After a year: a pile of permanent public links to 540p masters nobody remembers making. Fix: default 90 days (the option exists), show it on the create step, and put "N links live over 180 days" in the panel header. **S / med / high.**
- **No free-space precheck before a multi-GB publish** - `server/publish_db.py:595-660` (no `df`/`statvfs` anywhere); the target is the tree share, the same dataset as the b-roll footage and `client_shares.db`, and each publish keeps the old copy as `.prev-<ts>` for ever (a deliberate decision, `docs/BACKUP_RESTORE.md:386,467`). Filling it takes lane A, Syncthing and the app's own SQLite writes with it - the reasoning `dashboard/.../app.py:122-128` already applies to package publishes. Fix: one `df -k`, refuse below 2x the file size (`--allow-tight`), print the `.prev-*` total. **S / med / high.**

## Verified sound (so nobody re-checks them)
The b-roll ingest-token gate is fail-closed at all three layers (`routes_ingest.py:30-53` → 503, `dashboard/.../broll.py:280-292,300-305` → 401, `mount_broll:417-421` refuses to mount). `SHARE_ASSETS` allow-listing, `PUBLIC_VIDEO_COLUMNS` (no outward `SELECT *`), the uniform 404 for revoked/expired/never-existed tokens, `share.js`'s `textContent`-only rendering, and `publish_db.py`'s checkpoint → `sqlite3.backup()` → `quick_check` → shrink-guard → atomic-rename chain (CR-10) all hold. Semantic/fuzzy cache keys include generation + counts read per request, so a rename-swap self-invalidates. Both sidecar model downloads are sha256-pinned, host-allow-listed, resumable, delete on mismatch and pre-check free space. The Range/206 route handles suffix ranges and 416. On the companion side, `loopback_guard` (exact-match origins, Host rebinding defence, JSON-only POSTs, realpath containment), `broll_fetch.fetch_refusal` (root guard before any rclone), the `.partial`-then-rename discipline, state-file atomicity, and `_reclaim` / `_requeue_after_restart` are correct as written.

## Cross-cutting notes
- **Dashboard agent:** `dashboard/.../app.py:1030` runs `workers=1` and the public `/broll/share` media routes are sync `def`s streaming from that same process (MEDIA-14). Anything else adding a slow sync route shares that 40-thread pool with fleet report ingest.
- **Resolve/watcher agent:** `companion/.../library.py` reads Resolve's private project-library schema directly (`Sm2TiItem`, zstd `BtVideoInfo.Clip` blobs). Well guarded with `LibraryUnavailable`, but it is unversioned private API - worth confirming a Resolve upgrade degrades to the API walk rather than silently returning zero clips (CR-81).
- **Release agent:** `broll/web` still borrows the retired standalone repo's venv; `run_all_tests.ps1` falls back to the dashboard venv, so a machine without `E:\Projects\broll-platform` runs that suite on a different interpreter than CI.
- **Sync agent:** MEDIA-17's dot-directory hole is a general one - `.ingest` sits inside the archive and nothing in the lane filters or the indexer sweeps excludes dot-directories by rule.
