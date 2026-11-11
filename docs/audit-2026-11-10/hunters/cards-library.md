# cards-library - Timeline Cards library engine, media workers, stores, library reader/writer/edits (MulticamPipeline, the live /cards)

Files read (approximate coverage): `multicam_pipeline/cards/library_engine.py` (~45%: __init__, root switch, stop, tokens_for, build_state/card cache, group_and_note, fleet state, peaks, src/ogg/vid/lite workers, publish/ring/delta/gz), `cards/stores.py` (100%), `library/library_reader.py` (~60%: LibraryReader, timeline, fingerprint, clip facts), `library/library_writer.py` (~20%: LibraryWriter gates, conform, backup, restore), `library/library_edits.py` (~10%: apply, backup, undo), plus for the thread/engine questions `cards/agent.py` (lib worker, tokens worker, mirror, pick), `cards/project_agent.py` (init, start, stop, publish), `cards/project_engine.py` (start/load/edit worker), `cards/translate.py` (GoogleTranslator worker/stop), `page/03-lane.js` and `page/08-places.js` (the callers), ccsync `dashboard/.../cards.py` `build_engine` and `cards_pool.py` header. Not read: `config.py`, `media.py`, `make_lite_audio.py`, `fleet_jobs.py`, `roots.py` beyond greps.
Probes run (scratch `...\scratchpad\cards-library\probe.py`, `probe2.py`, system Python 3.12 + numpy 2.4, temp dirs only):
- `_peaks_make`'s exact numpy expression on a synthetic s16le buffer: 64 min = 61 MB stdout + 246 MB numpy transient; 120 min = 115 MB + 461 MB.
- `PlanStore.append` x400 insert ops on a temp Script Docs: history .jsonl 70.3 MB, plans file 340 KB, append 1.0 ms -> 3.2 ms.
- `PlaceStore.set` with 100 timelines x 24 devices x 50 marks: file 1.41 MB, 46.7 ms per save on local SSD.
- Publish ring: 32 versions x 1,522 card dicts shaped like `_card_body` + per-build fields: 57 MB (1.77 MB/version); one state JSON 2.02 MB.
- Token frames cache for a 15k-token interview: tokens 2.7 MB, `_frames_cache` copy 2.0 MB more; two `array('d')` would be 0.26 MB.

## Findings

### cards-library-1 - Waveform peaks: one unbounded thread + ffmpeg per clip, each buffering the whole decoded clip (~300-575 MB transient per hour-long clip) inside the dashboard process
- Category: perf
- Severity: high
- Confidence: CONFIRMED (mechanism and per-clip memory measured; concurrency read from code and page)
- Where: MulticamPipeline `multicam_pipeline/cards/library_engine.py:3249-3298` (`peaks_state` starts `threading.Thread(target=self._peaks_make)` per clip, no queue, no cap), `:3319-3349` (`_ff_run` -> `communicate()` holds all of ffmpeg's s16le stdout, then `np.abs(a.astype("int32"))`), `page/03-lane.js:746-765` (`lanePeaks` fetches `api/peaks` for every clip the lane draws, retrying 2,4,8,16... s up to 120 s)
- What: The dashboard mount never sets `engine.fleet` (ccsync `dashboard/src/ccsync_dashboard/cards.py:306-353`), so every peaks request takes the local path, which is a thread per distinct clip with no concurrency limit - unlike `src_state` (one worker + one helper) and `lite_sweep` (one worker), whose own comments say "the NAS must never run dozens of ffmpegs because a lane opened". Each thread decodes the whole clip to 8 kHz s16le in memory and widens it to int32. A peaks failure leaves no record, so the page's ~10 retries over 120 s each start a fresh full decode.
- Cost / failure scenario: Opening the lane on a cut drawn from N clips that have no `.peaks` yet starts N ffmpegs at once in the dashboard container. Measured per clip: 64 min -> ~307 MB peak (61 MB buffered stdout + 246 MB numpy), 120 min -> ~576 MB. A Framing Formosa-sized episode (12 multicams at 1-2 h) is 4-7 GB at once, in the same uvicorn process that serves fleet sync status, plus N parallel decodes reading over the media mount. This happens on every first open of an episode, after any re-render (mtime newer), and after the 2026-08-28 rate change remade every file. At 20 studios it is a regular OOM risk for "the dashboard is what tells everyone whether their footage is syncing".
- Evidence: probe numbers above; code read (no `fleet` assignment in `build_engine`; FLEET.md section 12 confirms "the page's own peaks path is untouched", that is, thread-per-file).
- Ledger: new
- Suggested change: Put peaks on the existing `_lite_q` worker (or `_src_q`, as pinned peaks already do), and stream the decode: read ffmpeg stdout in fixed chunks (e.g. 40 x 8000 samples) and max-pool each chunk, so memory is O(chunk) not O(clip). Record a failure per (wav, mtime) so retries do not re-decode. Must keep: first-writer-wins, the PK header/rate check, the 304/ETag path.
- Effort / risk: S effort; low risk

### cards-library-2 - Every ProjectAgentEngine runs LibraryEngine.__init__ twice: one orphan GoogleTranslator thread + its loaded cache per engine, and every Script Docs store read twice at build
- Category: leak
- Severity: medium
- Confidence: CONFIRMED (code read)
- Where: MulticamPipeline `cards/project_agent.py:115-121` (`AgentLink.__init__` then `ProjectEngine.__init__`), `cards/agent.py:66` and `cards/project_engine.py:~139` (both call `LibraryEngine.__init__`), `cards/library_engine.py:419-423, 535-536`, `cards/translate.py:199-225` (constructor loads `gt_translations.json` and starts a daemon worker)
- What: The diamond construction runs `LibraryEngine.__init__` once through each parent. The second run replaces `self.gt`, `self.store`, `self._plans`, `self._place`, `self._notes`, `self._bins`, `self._colors`, but the FIRST GoogleTranslator's worker thread is already started and blocks on its Event forever, keeping that translator and its whole parsed cache alive. Nothing can ever stop it (no reference is kept to call `stop()`).
- Cost / failure scenario: Per engine built (2 at a time today, more with every pool close/open per PL-RES-77): +1 thread and +1 in-memory copy of the episode's google cache (size scales with translated segments; estimated a few MB on a translated interview episode), plus double the build-time reads of `timeline_plans.json` (3.4 MB on Civil Defence per the store's own comment), `gt_translations.json`, notes, place and colours over the vault mount - on the path the pool runs in a background thread while the landing page says "loading". One of the "15 threads per engine" the owner measured.
- Evidence: read; `translate.py:225` `threading.Thread(target=self._worker, daemon=True).start()` inside `__init__`.
- Ledger: related to PL-RES-77 / bug-dash-jobs-cards-4 (open) - this part is new and leaks even without eviction
- Suggested change: Guard `LibraryEngine.__init__` against re-entry (`if getattr(self, "_lib_inited", False): return` after the attributes `ProjectEngine` needs are reset), or have `ProjectEngine.__init__` stop the first translator (`self.gt.stop()`) before re-running. Must keep the attribute resets `ProjectAgentEngine.__init__` currently relies on (`write_allow`, `media_map`).
- Effort / risk: S effort; medium risk (MRO-sensitive; pin with a thread-count test)

### cards-library-3 - A cooperative stop is cheap: ProjectAgentEngine.stop never reaches LibraryEngine.stop, and the library sweep loop has no exit
- Category: leak
- Severity: medium
- Confidence: CONFIRMED (code read)
- Where: MulticamPipeline `cards/project_agent.py:686-687` (`stop` sets `_stop` only), `cards/library_engine.py:665-695` (`stop` exists: stops the translator, drains clip queues, but is not called), `cards/agent.py:1020-1029` (`_lib_worker` is `while True`, waking every `LIB_POLL_S` = 2 s), `library/library_reader.py:394-444` (`LibraryReader.close()` exists, never called on a dropped engine)
- What: Answers the brief's question "is a cheap stop possible". Of the long-lived threads, only two ignore stop: the library sweep (`_lib_worker`) and the translator (because the subclass `stop` skips `LibraryEngine.stop`). Everything else is already either flag-aware (`_edit_worker` reads `_stop`), queue-drained-and-exits (`_tokens_worker`, `_src_worker`, `_lite_worker`, mirror writer), or one-shot (peaks, lite, tx, sem, summaries).
- Cost / failure scenario: Today the pool refuses a third engine (owner decision, not a finding); the leak per dropped engine is PL-RES-77. What this adds: the fix is about 10 lines - `ProjectAgentEngine.stop(): self._stop = True; LibraryEngine.stop(self); self._lib_wake.set(); reader.close()` plus `while not self._stop` in `_lib_worker` - plus finding 2's orphan. With that, the pool could evict instead of refuse.
- Evidence: read; `LibraryEngine.stop` docstring itself says "`ProjectAgentEngine.stop` is still its own flag and does NOT reach here".
- Ledger: related to PL-RES-77 / bug-dash-jobs-cards-4 (open)
- Suggested change: as above; also drop `_ring`, `_gz_cache`, `_tokens`, `_frames_cache` on stop so a held reference frees the bulk. Must keep: pinned jobs still run to completion (already handled in `_src_worker`).
- Effort / risk: S effort; low risk

### cards-library-4 - The publish ring keeps 32 full copies of every card dict: ~57 MB per engine on a 1,522-card cut, the largest single item in the "+128 MB per engine"
- Category: perf
- Severity: medium
- Confidence: CONFIRMED (measured on synthetic cards shaped like `_card_body`)
- Where: MulticamPipeline `cards/library_engine.py:5012-5039` (`RING_KEEP = 32`, entry holds `{uid: card}`), `:1512` (`card = dict(body)`: every build makes new dicts, so ring entries share nothing but strings), `:1265-1290` (`_frames_cache` duplicates every token list)
- What: Every version bump pushes a dict-of-all-cards into the ring. Because `build_state` makes a fresh dict per card per build (and `group_and_note` adds `stack` dicts), 32 versions are 32 full card sets. Separately, `_frames_cache` stores a second converted copy of each clip's tokens (tuples), about 0.75x the size of the tokens again.
- Cost / failure scenario: Measured 1.77 MB per version at 1,522 cards -> 57 MB once 32 edits/pushes have happened (normal within minutes of editing or with a live agent pushing). Token frames: 2.0 MB extra per hour-long interview (15k tokens), 9 interviews about 18 MB. With `_gz_cache` (16 x ~0.4 MB) and the 2 MB `state_json` that accounts for most of the measured +128 MB.
- Evidence: probe.py ring section; probe2.py frames section.
- Ledger: new
- Suggested change: Store a per-card fingerprint in the ring (e.g. the card's `json.dumps` or a hash of it, plus position) instead of the dict, and build deltas against the current dicts; or keep only the last 8 versions (a page more than 8 versions behind already gets a full state). For `_frames_cache`, keep `starts`/`ends_max` as `array('d')` and index into `entry["tokens"]` (0.26 MB vs 2.0 MB measured). Must keep `state_delta`'s patch semantics and `first_of_seq`.
- Effort / risk: M effort; medium risk (delta correctness is pinned by tests)

### cards-library-5 - timeline_plans.history.jsonl rewrites the whole op list on every staged op, grows quadratically, and is never pruned or read
- Category: disk-growth
- Severity: medium
- Confidence: CONFIRMED (measured)
- Where: MulticamPipeline `cards/stores.py:338-352` (`_put` appends `{"ops": entry["ops"]}` - all ops - per rev)
- What: Each append/undo/mode change appends a line containing the entire current op list. A draft built one op at a time costs sum(1..n) op copies. Its own docs (PROJECT-FORMAT-PLAN.md table row 5) note "every revision of every draft, for ever, with no reader".
- Cost / failure scenario: Measured: one 400-op draft of insert ops = 70.3 MB of history (plans file itself 340 KB). Trims/moves are smaller (estimated 10-15 MB per 400 ops). It lives in the vault's Script Docs, per episode, forever; at a studio running drafts daily that is GBs per year per episode root on the NAS, and every vault backup/snapshot carries it.
- Evidence: probe.py plan section.
- Ledger: related to PROJECT-FORMAT-PLAN.md row 5 (documented, no fix recorded)
- Suggested change: Append only the delta (the op added, or "undo" / "set n=k"), which still lets a recovery replay a draft, and rotate the file at a size cap (e.g. keep the last 5 MB + one gz). Must keep the "42 ops -> 0" forensic value: log full op lists only when ops shrink.
- Effort / risk: S effort; low risk

### cards-library-6 - timeline_place.json is rewritten whole, indented, about once a second per device while the lane plays
- Category: perf
- Severity: low
- Confidence: CONFIRMED (cadence read; cost measured at an upper-bound size)
- Where: MulticamPipeline `cards/page/08-places.js:134-162` (`placeTouch` arms a 1 s save whenever the lane head moved >0.05 s), `cards/stores.py:647-682` (`PlaceStore.set` dumps the whole store with `indent=1`)
- What: During playback the lane head always moves, so each playing device POSTs a place every ~1 s and the server rewrites the entire file (every timeline ever opened, up to 24 devices each, 50 marks) - nothing evicts timelines.
- Cost / failure scenario: Measured 1.41 MB / 46.7 ms per save at 100 timelines x 24 devices (upper bound); realistic today estimated 50-300 KB, a few ms, on the NAS dataset. Two people playing = 2 vault writes/s for hours, plus ZFS snapshot churn on Script Docs.
- Evidence: probe.py place section; page code.
- Ledger: new
- Suggested change: Do not send `head` changes during playback (save on pause/stop, or every 15 s while playing), write compact JSON, and cap stored timelines (drop ones untouched for 90 days). Must keep per-device places and shared marks.
- Effort / risk: S effort; low risk

### cards-library-7 - NoteStore and BinStore have no lock and share one fixed .tmp: concurrent saves can raise or corrupt the notes file, and a corrupt file loads as empty
- Category: concurrency
- Severity: low
- Confidence: PLAUSIBLE (race needs two saves overlapping)
- Where: MulticamPipeline `cards/stores.py:745-800` (NoteStore: `set` from HTTP threads, `heal` from the publish/edit-worker thread, both `json.dump(self.data)` to `path + ".tmp"`), `:685-742` (BinStore, same shape), `:752-758` (load: `ValueError` -> `{}`)
- What: PlanStore and PlaceStore take `self.lock`; NoteStore and BinStore do not. A note set on one HTTP thread while `heal()` saves on the sweep/edit thread can raise `RuntimeError: dictionary changed size during iteration` (not caught - only `OSError` is) or interleave two writers on the same `.tmp` inode, leaving invalid JSON that the next engine build reads as `{}` and the next save makes permanent.
- Cost / failure scenario: Rare (notes are typed by hand), but the outcome is every note, stack mark and collapsed state of the episode silently lost.
- Evidence: read.
- Ledger: new
- Suggested change: Add a `threading.Lock` around mutate+save in both stores (copy under the lock, write outside it is fine) and a unique tmp name (`.tmp.<pid>.<thread>`); on a load ValueError, keep the bad file aside rather than overwrite it. Must keep the heal semantics.
- Effort / risk: S effort; low risk

### cards-library-8 - An extraction or proxy failure is remembered for the life of the engine, even across a root switch
- Category: resilience
- Severity: low
- Confidence: CONFIRMED (code read)
- Where: MulticamPipeline `cards/library_engine.py:3790-3792, 3949-3959` (`_src_fail` / `_vid_fail` set on any failure), `:805-839` (`_apply_root` does not clear them)
- What: Any failure - including transient ones (NAS read error mid-copy, the 1800/3600 s timeout, ffmpeg killed by a container restart signal) - makes `src_state` answer `failed` for that media file until the engine is rebuilt, i.e. until the dashboard container restarts (weeks).
- Cost / failure scenario: A montage clip whose extraction hit one SMB/NFS hiccup stays dark on the lane for every editor for weeks; the only cure is a deploy/restart.
- Evidence: read; no other writer clears these dicts.
- Ledger: new
- Suggested change: Store `(why, time, src mtime)` and retry after e.g. 10 minutes or when the source mtime changes; keep permanent causes ("no audio track") sticky.
- Effort / risk: S effort; low risk

### cards-library-9 - The library sweep polls Postgres every 2 s forever, 4 round trips per tick, whether or not any page is open
- Category: idle
- Severity: low
- Confidence: CONFIRMED (code read; per-query cost from the code's own comment)
- Where: MulticamPipeline `cards/agent.py:1020-1044` (`_lib_worker`, `LIB_POLL_S = 2.0` in `cards/config.py:155`), `library/library_reader.py:803-826` (`fingerprint` = `_sequence_of` + head join + `v1_track` + count: 4 queries)
- What: In live mode on the library source each engine runs the fingerprint every 2 s for the life of the container, with no viewer check; in file mode the loop still wakes every 2 s and calls `source_wanted()` (which may run `_library_default`'s 2+ queries every 30 s on a miss).
- Cost / failure scenario: 2 queries/s per engine = ~173k queries/day per engine against Resolve's project library server, all night. Small per query (~2 ms), but at 20 studios it is pure idle load and keeps the PG connection hot.
- Evidence: read.
- Ledger: new
- Suggested change: Fold the fingerprint into one query (one SELECT with the joins), and back off to 30 s when no `api/state` has been served in the last 2 minutes (`_pump_at`/`tick` already records page activity); `_lib_wake.set()` on the next poll restores 2 s at once.
- Effort / risk: S effort; low risk

### cards-library-10 - Undo of an in-place library edit is two transactions; a failure between them leaves the timeline half-restored
- Category: resilience
- Severity: low
- Confidence: CONFIRMED (code read)
- Where: MulticamPipeline `library/library_writer.py:1858-1916` (`restore`: `_delete_rows` commits on its own connection, then re-inserts/updates commit on a second), `library/library_edits.py:1393-1433` (`undo` says "the restore itself has already committed by then")
- What: The created rows are deleted and committed first; if the second transaction then fails (a PK collision of the kind the 2026-08-28 comment describes, a dropped connection, the NAS sleeping), the timeline has lost the edit's new items without getting the removed ones back.
- Cost / failure scenario: Lower today because `REAL_LIBRARIES` refuses edits outside lab libraries since 2026-09-29, but undo is the recovery path, and a re-run is the only cure. Also: every apply and every dry run writes a backup JSON (bytea as hex) into `backup_dir` and nothing prunes it.
- Evidence: read.
- Ledger: related to REPRO-RIGHTS-V7-DAMAGE.md (documented gate)
- Suggested change: Run delete + re-insert + update in ONE transaction on one connection (`_delete_rows` taking a cursor); prune backups older than N days except the latest per timeline.
- Effort / risk: S effort; low risk

### cards-library-11 - The remote_audio caches are never pruned, and crashed encodes leave .tmp files behind
- Category: disk-growth
- Severity: low
- Confidence: CONFIRMED (code read; sizes estimated)
- Where: MulticamPipeline `cards/library_engine.py:4240` (`lite_dir` = `<root>/Script Docs/remote_audio`), `:3700` (`source/`), `:4182-4230` (480p x264 proxies, CRF 26), `:3351, 3990, 4011, 4032, 4200` (`.tmp`, `.tmp.m4a`, `.tmp.ogg`, `.tmp.mp4`)
- What: Opus copies, source extractions, `.peaks` and 480p proxies accumulate per clip name forever; a renamed or re-rendered clip leaves its old files; a process killed mid-encode (container restart, deploy) leaves its `.tmp*`, which only the same clip's next successful run overwrites.
- Cost / failure scenario: Estimated ~0.5-0.7 GB per hour of footage for 480p proxies once the video window is used, ~20-30 MB/h for audio. Bounded by the vault's footage, but nothing tells anyone and nothing reclaims dead clips.
- Evidence: read; no remove/prune outside the per-job tmp cleanup.
- Ledger: new
- Suggested change: A sweep at engine start (it already walks per episode) that deletes `*.tmp*` older than a day and reports remote_audio size on the health line; optional age-based eviction of proxies not served in 60 days.
- Effort / risk: S effort; low risk

## What is already good
- `src_state`'s queue: deduped by normcased source path, one worker + one audio-only helper, audio before proxies, drained-and-exits, honours `_lib_stopping`, and `_ff_run` kills and reaps on timeout/cancel.
- `build_state`'s card cache keyed by span + token-entry identity, and `_slice_words`' bisect + bounded memo (50k entries) and `_frames_cache` (64 entries): edits do not re-slice unchanged cards.
- Publishing: `_publish_key` keeps the version still when nothing visible changed, gzip once per (version, tail), JSON dump outside `self.lock`.
- `PlanStore`'s per-timeline JSON fragments (only the changed entry is re-serialised) and dropping dead `base` snapshots on load.
- `LibraryReader` keeps one connection per DB and reconnects once on error; `LibraryWriter` refuses before any write and verifies before commit.

## Coverage note
Not reached: `config.py`, `media.py` (ffprobe helpers), `make_lite_audio.py`, `fleet_jobs.py`, `roots.py`; most of `library_writer.py` (`_write_conform`, `_verify_conform`, `delete_timeline`) and `library_edits.py` (`_plan_rows`, `_write`, `_verify`); `library_engine.py`'s translation / semantic search / corpus / summaries / intake / pin paths (2,000+ lines). Did not measure real vault file sizes (vault is on the NAS, out of bounds) - place/plans sizes are synthetic. Per-engine memory split is estimated from the ring/frames probes, not measured on a live engine.

## OUT OF TERRITORY
- `cards/project_engine.py:1862-1880`: `_edit_worker` wakes every 1 s while idle per engine (cheap, but could wait on the Condition with the 12 s drain deadline instead).
- `cards/agent.py:874-910`: `_library_default`'s positive answer is cached until a root switch, so a library-sourced engine never follows Resolve's "current timeline" moving.
- `cards/handler.py:542-557`: `api/wavs` runs `_kind` (several stats + possible extraction queueing) for EVERY clip in `_mp_names`, which only grows within a root, every 4 s while any clip is `srcwait`.
