# idx - b-roll indexer (broll/indexer) and music indexer (music/indexer): throughput, cost, resumability
Files read (approximate coverage): broll_index/pipeline.py (all), claude_client.py (all), ffmpeg_tools.py (all), local_vlm.py (all), scanner.py, hashing.py, storage/sqlite_backend.py (videos/write paths), config.py (sampling/indexer/anthropic defaults), parallel_claude.py (worker + main), parallel_local.py (skim), run_queue.py (head + loop skim), duplicates.py (hash reuse), prompts/index_clip_v6.md (structure); music/indexer/index_music.py (all), music_index/audio.py, features.py, clap_model.py, config.py constants. Docs: INDEXERS.md (skim), broll/docs/indexing-api.md, indexing-local.md section on frames, local-indexing-options-2026-08-17.md section 2. Ledgers grepped: KNOWN_BUGS.md (CR-286B, broll-indexer-1), docs/bug-hunt-2026-08-14.md (per-frame spawn finding).
Probes run (all under scratchpad\idx\, CPU only, no model, no API call):
- `probe_frames.py`: synthetic 60 s 1920x1080 file; extract_frames per-process 1.06 s for 16 frames at 99 KiB/frame vs 31 KiB/frame scaled to 960 wide; bare ffmpeg spawn 17 ms; scene detect 0.48 s; sprite 0.42 s.
- ffmpeg 8.1 `-loglevel verbose` encode of the same file: the summary prints `Input stream #0:0 (video): 1800 packets read ...; 1800 frames decoded; 0 decode errors`, equal to `ffprobe -count_packets` (`nb_read_packets: 1800`).
- `probe_scan.py`: 5,000-row SqliteBackend in WAL; an unchanged rescan costs 1.12 ms/file in get+UPDATE+commit.
- Read-only look at the live data root E:\broll-queue: usage.jsonl (12,705 rows, one torn), local_vlm_server.log (n_ctx_slot = 16384, --image-min-tokens 1024), frame/proxy dimensions of video 25438 (frames 960x540 at 13:18 on 2026-09-17, proxy re-encoded 1920x1080 at 16:26), 401,155 frame JPEGs under sheets\ with nothing that prunes them.

## Findings

### idx-1 - Frames now come from the 1080p proxy at full size: about twice the local VLM's image tokens, and 8- and 9-frame windows go past the 16k context
- Category: bug
- Severity: high
- Confidence: PLAUSIBLE
- Where: broll/indexer/broll_index/ffmpeg_tools.py:821 (extract_frames, no scale), pipeline.py:211 (_frames_source prefers the proxy), ffmpeg_tools.py:312 (PROXY_HEIGHT = 1080 since 2026-09-17), local_vlm.py:46-47 (DEFAULT_CTX 16384, image_min_tokens 1024), config.py:255 (indexer.frames_per_call = 9)
- What: The local backend (the default for a new install) was designed and measured on 960x540 frames: at about 500 tokens each, raised to the 1024 minimum, nine frames come to about 9.5k tokens per call (indexing-local.md, local-indexing-options section 2). Since 2026-09-17 the proxy is 1080p. `_frames_source` reads frames from that proxy and `extract_frames` writes them at native size, so every frame is now 1920x1080. Qwen3-VL uses one token per 32x32 px, so that is 60x34 = about 2,040 tokens per frame. A window of 8 or 9 frames is then about 16.3k-18.4k image tokens plus about 1k of prompt text, which is over the server's 16,384-token slot. Windows of 7 still fit the prompt but leave about 1k for a 1,050-token answer.
- Cost / failure scenario: balanced_windows(per=9) gives 8-9-frame windows to every clip with 8-9 or 15-18 frames, and similar sizes further up (at max_gap_s 4 s that includes any clip of about 30-36 s or 60-72 s). llama-server rejects the request (HTTP 400, exceeds context). urlopen raises HTTPError, which becomes LocalVlmError "llama-server call failed: HTTP Error 400". That message matches none of `_FATAL_MARKERS`, so `_process_video` marks the clip `error` and moves on to the next. That repeats for a large share of every new clip, across the queue. If llama.cpp caps the image below 2,040 tokens, nothing overflows, but image encode still doubles: measured encode_ms is about 2.7 s per 7-frame window at about 1,058 tokens/frame (usage.jsonl), so about 5.4 s+ per window. Separately, each frame JPEG is 3.2x the bytes (99 vs 31 KiB, probe), and all 401,155 frames already on disk are kept forever.
- Evidence: the live usage.jsonl shows 7 frames = 8,473 input tokens and 8 = 9,531 (about 1,058/frame at 960x540). local_vlm_server.log shows `n_ctx_slot = 16384` and `--image-min-tokens 1024`. Video 25438's frames are 960x540 (extracted 13:18 on 2026-09-17), while its proxy and the three newest proxies are 1920x1080 (re-encoded 16:26). The last local describe was at 15:18 the same day, so no local run has seen a 1080p frame yet. Per the brief I did not load the model to confirm the 400.
- Ledger: new (a consequence of the BROLL_PROXY_TIERS 1080p change, 2026-09-17)
- Suggested change: scale the frames to the size the model was tuned on, inside `extract_frames` (`-vf scale='min(960,iw)':-2` on the same seek), so the frame stage and the eval agree whatever the proxy height. Contact sheets re-scale to 384 px anyway and are unaffected. Keep the (timestamp, path) pairing and the "only keep frames ffmpeg produced" guard. Optionally add "exceeds the available context" as a per-config fatal marker so a mis-sized window stops the run with the queue intact instead of erroring clips.
- Effort / risk: S effort; low risk

### idx-2 - The packet count that costs a second full NAS read of every original is already printed by the proxy encode
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: broll/indexer/broll_index/ffmpeg_tools.py:586 (encode at `-loglevel error`), :606 (verify_decodes, a full decode of the proxy), :622-625 (count_frames on the proxy, then count_frames_cached on the SOURCE), :629-630 (probe_video of src and dest)
- What: `_bad()` runs `ffprobe -count_packets` against the original. That demuxes the whole file over SMB, and the per-process memo almost never hits because each worker sees each original once. KNOWN_BUGS CR-286B/broll-indexer-1 accepted this cost and said "the answer is a count carried FORWARD from a read the pipeline already does". That read already exists: the encode demuxes every source packet, and at `-loglevel verbose` ffmpeg's end-of-run summary prints `Input stream #0:0 (video): N packets read`, the same number as `nb_read_packets`. The verify decode of the proxy prints `N packets read; N frames decoded; K decode errors` for the destination in the same way. So both counts and the decode-error tally fall out of the two passes that already run, and the ffprobe demux of the proxy goes too. The original is also ffprobed three times per clip (stage_probe, build_proxy, `_bad`'s probe_video). Its duration is already in the row.
- Cost / failure scenario: once per clip on every proxy build. The archive's mean clip is 222 s at 6.5-8.3 Mbps, about 200 MB, so about 4.3 s of extra read at the measured 46 MB/s. Across today's about 5,000-7,000-clip archive that is about 6-8 h of NAS read time per back-catalogue pass (estimated). Six parallel_local workers share the same link, so this adds directly to wall time. At 50k clips it is about 60 h. When the libx264 fallback re-verifies, the source is read once more unless the memo hits.
- Evidence: probe: `ffmpeg -loglevel verbose -i src.mp4 ... out.mp4` printed `Input stream #0:0 (video): 1800 packets read (118278221 bytes); 1800 frames decoded; 0 decode errors`, and `ffprobe -count_packets` on the same file printed `nb_read_packets: 1800`.
- Ledger: related to CR-286B / broll-indexer-1 (fixed; that entry names this as the way to bring the cost back down)
- Suggested change: run the encode at `-v verbose` (stderr capture is already in place), parse the first `(video)` input-stream summary line as src_frames, and do the same for the verify decode (dst_frames plus decode errors), keeping `frames_match` exact and "both known or skip". This changes argv that the companion parity tests pin, so the companion's twin and the parity tests must change in the same commit (the owner's one-rule-for-three-producers invariant). Keep `count_frames_cmd` as the fallback when the line is absent (an older ffmpeg).
- Effort / risk: M effort; medium risk (parity with the companion)

### idx-3 - The API describe path never hits the prompt cache: the ~3k-token instruction block sits after the images, with the per-window sheet list near its top
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: broll/indexer/broll_index/claude_client.py:373-382 (images first, then the text), :636-640 (no `system`, no `cache_control`), :789-803 plus prompts/index_clip_v6.md:12 (`__SHEET_PATHS__` on line 12 of 226)
- What: every call sends `[4 images][prompt text]` in a single user turn. The images differ on every window and the sheet list differs at the top of the text, so no prefix is ever byte-stable and nothing is cached. The fixed part (the v6 instructions, 12.3 KB, about 3k tokens, plus the taxonomy, which is stable for a run) could go in a `system` block with a `cache_control` breakpoint, leaving only the images and the sheet-name list in the user turn.
- Cost / failure scenario: every API window, about 2 per clip, so about 10k calls for a 5,000-clip archive. About 2.7k of about 7k input tokens per call would be billed at 0.1x instead of 1x, roughly 35-40% of input spend (estimated). On the configured `sonnet` (claude-sonnet-5, $2/MTok input per the current price list) that is about $0.005/call, so about $50 per 10k calls, and more per customer archive at commercial scale. Caching only works above the model's minimum prefix: 1,024 tokens on claude-sonnet-5, but 4,096 on claude-haiku-4-5 (the `haiku` alias), so the bulk-backfill model would need the taxonomy and instructions to clear 4k, or a newer Haiku (512 minimum).
- Evidence: code read. No `cache_control` or `system` anywhere in broll/indexer. The SDK-era usage.jsonl has no rows yet; the CLI-era rows had cache reads only because of the CLI's own system prompt.
- Ledger: new
- Suggested change: move the fixed instructions and taxonomy into `system=[{"type":"text","text":..., "cache_control":{"type":"ephemeral"}}]`, keep the per-window sheet list after the images, and leave `estimate_cost_usd` as it is (it already prices cache reads). Check `cache_read_input_tokens > 0` on the second call of a run. It must not change the JSON contract or the "images before text" order of the per-window part.
- Effort / risk: S effort; low risk

### idx-4 - Offline backfill pays full price: the Message Batches API (half price) is not used
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: broll/indexer/parallel_claude.py:154 (thread pool of synchronous `messages.create`), run_queue.py (waits out rate limits in a loop)
- What: the API stage is an overnight, latency-insensitive bulk job. Its whole machinery (N workers, a semaphore, retry-after handling, reset-hint parsing, run_queue's sleep-and-relaunch loop) exists to push synchronous calls past rate limits. The Message Batches API takes the same requests asynchronously at 50% of the token price, under its own limits.
- Cost / failure scenario: this applies only to the `anthropic` backend (opt-in per site). It halves input and output spend for every backfill: about $0.02-0.03 saved per call (estimated at claude-sonnet-5 rates with ~7k input and ~1-2k output), so about $200-300 per 10k calls, and it stacks with idx-3's caching. Interactive and new-ingest indexing can stay synchronous.
- Evidence: code read; no `batches` in broll/indexer.
- Ledger: new
- Suggested change: a `--batch` mode for parallel_claude: build one request per window keyed `custom_id = f"{video_id}:{window_index}"` (results arrive in any order), submit, poll, then merge per video and `write_index_result` exactly as now. Clips stay `proxied` until their whole set returns, which keeps resumability. Keep the synchronous path as the default for small runs.
- Effort / risk: M effort; low risk

### idx-5 - `anthropic.max_tokens` 8000 sits below a third of the archive's historical outputs; a truncated answer costs two paid calls and then marks the clip `error`
- Category: bug
- Severity: medium
- Confidence: PLAUSIBLE
- Where: broll/indexer/broll_index/claude_client.py:638 (`max_tokens` default 8000), :591-593 (only a warning on max_tokens), :767-782 (one retry on invalid JSON, then ValueError)
- What: on `stop_reason == "max_tokens"` the code logs a warning and passes the truncated JSON on. Parsing fails, the window is called again (paid twice), and the clip is then marked `error`. indexing-api.md says "too high is free - you are billed for what is produced", so the low default only costs money.
- Cost / failure scenario: the 8,996 API rows in the live usage.jsonl (CLI era, haiku) have median 5,961 output tokens, p90 12,783, p99 20,313; 2,915 rows (32%) exceed 8,000. If those counts are visible JSON rather than CLI-side thinking (which I cannot tell from the log), about a third of windows would truncate under the SDK default: each one a doubled call plus a lost clip.
- Evidence: distribution computed from E:\broll-queue\usage.jsonl. The 8000 default is in claude_client and in the docs table.
- Ledger: new
- Suggested change: raise the default to 16000 (non-streaming stays within SDK timeouts), and on `max_tokens` retry once with double the ceiling instead of re-asking at the same one. It must not change the per-video vs account-wide classification.
- Effort / risk: S effort; low risk

### idx-6 - The cost estimate and alias table lag the price list: sonnet-5 is costed 50% high
- Category: streamline
- Severity: low
- Confidence: CONFIRMED
- Where: broll/indexer/broll_index/claude_client.py:50-67, broll/docs/indexing-api.md:52-57
- What: `PRICE_PER_MTOK["claude-sonnet-5"] = (3.00, 15.00)`, but the current price is $2/$10. `usage.jsonl` forecasts, which the docs tell the operator to use for sizing an archive run, therefore overstate the default model's cost by 50%. The alias table also has no current-generation entries, so an operator choosing on price sees stale options.
- Cost / failure scenario: once per forecast; this is a planning error, not a billing one.
- Evidence: code read against the current model/price table (2026-11-03).
- Ledger: new
- Suggested change: correct the sonnet-5 row and add the current models to MODEL_MAP/PRICE_PER_MTOK. Doc table in the same change.
- Effort / risk: S effort; low risk

### idx-7 - usage.jsonl takes concurrent appends without a lock; the live file has a torn line, and the documented forecast snippet crashes on it
- Category: bug
- Severity: low
- Confidence: CONFIRMED
- Where: broll/indexer/broll_index/pipeline.py:257-281 (`_log_usage`, open-append per call from N worker threads and, with `--after-id`, a second process); broll/docs/indexing-api.md:97-103 (forecast snippet)
- What: two writers appending at once can interleave a line on Windows. Line 8716 of the live file is the fragment `n_ms": 25423}`. The doc's snippet does `json.loads` on every line and raises `JSONDecodeError` on that one, so the very forecast the doc recommends fails on the studio's own file.
- Cost / failure scenario: 1 torn line in 12,705 today. Every forecast run fails until someone edits the file by hand.
- Evidence: my parse of E:\broll-queue\usage.jsonl failed at exactly that line.
- Ledger: new
- Suggested change: write each record with one `os.write` on an `O_APPEND` fd under a module-level lock (threads), and make the doc snippet skip unparseable lines.
- Effort / risk: S effort; low risk

### idx-8 - An account-wide stop in the middle of a clip throws away the windows already paid for
- Category: resilience
- Severity: low
- Confidence: CONFIRMED
- Where: broll/indexer/broll_index/pipeline.py:334-353 (results only in memory until the final write_index_result), local_vlm.py:529-534 (same shape)
- What: windows run in sequence and are merged only at the end. A FatalRunError (rate limit, overloaded) on window k of n drops windows 1..k-1. The clip stays `proxied` and the next run pays for them again.
- Cost / failure scenario: one rate-limit stop with 4 workers mid-clip wastes up to (windows-1) calls per in-flight clip, a few calls per stop. run_queue's own history records 21 stops in a night, so tens of paid calls per night of limits (estimated). This is small next to idx-3/idx-4, but free to fix.
- Evidence: code read.
- Ledger: new
- Suggested change: cache each parsed window as `sheets/<id>/window_<k>.json` (keyed by the window's sheet names and the model) and reuse it on rerun; delete it after the write. The resting status and contract are unchanged.
- Effort / risk: S effort; low risk

### idx-9 - A rescan writes and commits every unchanged file
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: broll/indexer/broll_index/scanner.py:211-226, storage/sqlite_backend.py:70-81 and :136-142
- What: for a known file of the same size, do_scan still calls `upsert_video` with the same hash/size/in_inbox. That re-selects the row (a second lookup) and runs an UPDATE plus a commit, one fsync per file, even though nothing changed.
- Cost / failure scenario: measured at 1.12 ms/file. A 4,482-file share costs about 5 s per rescan, and 500k files about 9 min of pure commits on top of the SMB walk.
- Evidence: probe_scan.py, 5,000 rows, WAL.
- Ledger: related to BROLL-IDX-6 (the hash reuse, fixed); the write half was left
- Suggested change: skip the upsert when hash, size_bytes and in_inbox already match, and batch the remaining writes in one transaction per directory or per 500 rows.
- Effort / risk: S effort; low risk

### idx-10 - A music sweep with nothing changed still loads CLAP onto the GPU and re-scores the whole library
- Category: idle
- Severity: low
- Confidence: CONFIRMED
- Where: music/indexer/index_music.py:453-457 (Clap() before the file walk), :562 (retag always)
- What: the `--queue` path skips retag when nothing was added (its comment explains the debias axes would churn), but the full sweep loads the 194M model and retags even when `todo` is empty.
- Cost / failure scenario: per manual sweep: a CLAP load (seconds plus about 1 GB of VRAM beside Resolve on the base rig) and a whole-library rescore, all for zero changed files.
- Evidence: code read.
- Ledger: new
- Suggested change: compute `todo` before loading CLAP. With no todo, no prune and no queue rows closed, print "nothing changed" and exit. Same rule as the queue path.
- Effort / risk: S effort; low risk

## What is already good
- The vendored local backend in the companion (`companion/src/ccsync_companion/broll_vlm/*`) differs from broll_index only by its header, and test_broll_vlm_vendored.py pins it byte-for-byte, so no drift.
- Scan hashing reuses the stored digest when the size is unchanged (BROLL-IDX-6), and duplicates.py caches `full_hash`, so no whole-file rehash on rerun. The music index skips by size-mtime.
- stage_embed batches search_norm and embedding writes per video (BROLL-IDX-8). write_index_result is one transaction per clip.
- Music analysis decodes each file exactly once at 48 kHz (peaks, duration, DSP and windows all come from the same `y`), and embeds in batches of 16 windows.
- llama-server is kept warm per process with a single slot, and the static prompt goes first so its own prompt cache reuses the prefix across windows.

## Coverage note
Not read in depth: build_archive.py, taxonomy.py, sorter.py, rebase.py, inplace_fixes.py, the tools/ and fix_* one-off scripts, transcribe.py/batch_transcribe.py (the whisper path), music export_*_encoder.py, mel_numpy.py, proxies.py, tagging/debias. I did not diff broll_index/ffmpeg_tools.py against companion/ffmpeg_tools.py function by function (only the parity-pinned count/proxy helpers were checked through their docstrings). Per-frame ffmpeg spawns in extract_frames are already in bug-hunt-2026-08-14 (verified, open); I measured them at about 66 ms/frame here and did not re-report them.

## OUT OF TERRITORY
- companion/src/ccsync_companion/broll_vlm (vendored local_vlm): if the companion's ingest feeds it frames cut from the new 1080p preview, idx-1's context overflow applies there too; worth one check by the companion hunter.
