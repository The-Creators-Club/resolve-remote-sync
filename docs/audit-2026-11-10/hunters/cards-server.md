# cards-server - Timeline Cards server (MulticamPipeline `multicam_pipeline/cards/` handler + AI modules, transcripts/)
Files read (approximate coverage): cards/handler.py (all), page.py (all), page/sw.js (fetch arms), page/08-places.js (poll loop), page/06-trim.js (vgt), page/17-windows.js (panel boot), claude.py (all), claude_session.py (all), transcript_search.py (lines 1-1000), chat_edit.py (digest, sidecar, ask/_turn/turn_json/lean_json), shorten.py (turn record writes, scores), translate.py (all), corpus.py (all), offline.py (words/manifest caching), gap_notes.py (header), models.py (cache shape), server.py (threads), library_engine.py `_run_claude_json`/`tick`/`gz_cached`, project_engine.py `tick`/`projects_state`/`_gt_landed`, transcripts/whisper_corpus.py (run + scratch), ccsync cards.py (a2wsgi workers=24), cards_wsgi.py (streams, does not buffer), cards_ai.py (breakpoints, session store).
Probes run (all under scratchpad\cards-server\): (1) `render_page` + gzip timing of the assembled page; (2) `probe_tsearch.py` - syscall count of one `/api/search/scopes` body on a synthetic 15-person / 200-clip episode; (3) `probe_digest.py` - chat digest size at 500 cards, full and compact.

## Findings

### cards-server-1 - Every warm edit-chat turn re-sends a ~46k-character digest of the whole cut list, and the conversation keeps every copy
- Category: perf
- Severity: medium
- Confidence: CONFIRMED (bytes measured; token counts estimated)
- Where: MulticamPipeline multicam_pipeline/cards/chat_edit.py:333 (`digest`), :427 (`_card_lines`), :1430 (`_turn`)
- What: a warm turn sends `CURRENT STATE` = `digest(engine, known)`, where a card already "known" still costs one line with its uid, person, duration and the first 60 characters of its words. At 500 cards that "compact" digest is 46,378 characters (104 KB UTF-8, mostly CJK), only 32% smaller than the full 67,750-character digest. Each turn's prompt is stored in the provider conversation, so turn N re-reads all N-1 earlier digests from cache as well.
- Cost / failure scenario: per chat message at 500 cards, roughly 35-45k fresh input tokens (estimated, CJK is close to one token per character) that are written to cache before the editor's sentence is even read, so a one-word request ("delete the selected card") pays a long prefill. A ten-turn hour adds about 400k tokens of history that every later turn reads back (cache-read price, still latency). The rest of the warm turn is a few hundred characters. On top of the corpus (~322k characters for a real episode, per the transcript_search docstring), five or six turns is enough to approach a 200k-token context window if the chosen model has one.
- Evidence: probe_digest.py, 500 synthetic cards of 40-160 CJK characters with 20 section markers: full 67,750 chars / 165,802 bytes; compact (every uid known) 46,378 chars / 104,286 bytes. `_turn` builds `digest(self.engine, None if cold else known)` on every turn (chat_edit.py:1430), and docs/CHAT-EDIT.md says "every later turn is the current state and the editor's sentence".
- Ledger: new (CR-229 describes the design, not its cost)
- Suggested change: send a known card as `[uid] person dur` with no words (the words are already in this conversation), or send only the cards whose uid, order, gap, colour or highlight changed since `rev_seen`, plus the order as a bare uid list. Keep the "a trim renames the uid, so it is re-sent whole" property. This must not drop highlights (`_hl_line`), which the docstring says change without a uid change.
- Effort / risk: S effort; medium risk (the model's grounding in the current order must be kept, so it needs a few live turns to check)

### cards-server-2 - The 1.67 MB page goes out in full on every load: no validator, and the gzip is redone for each request
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: MulticamPipeline multicam_pipeline/cards/handler.py:420-424 (`/` route), :144-174 (`_send`); page.py:179 (`render_page`)
- What: `render_page` caches the assembled text, but `_send` encodes it (1 ms) and `gzip.compress(data, 5)` runs on every request, and the response has no ETag, Last-Modified or Cache-Control, so the browser can never get a 304. The service worker's navigation arm is network-first (`shellAnswer`, sw.js:389) and never stores navigations, so it does not save the bytes either.
- Cost / failure scenario: each page load, reload, pop-out panel window (17-windows.js loads the whole page per panel) and phone open costs about 35 ms of dashboard CPU on a request thread and about 557 KB on the wire. On a phone over a mobile tailnet that is 1-3 s before the first byte of script runs, each time. At 20 machines with a few loads and pop-outs per editor per hour, that is tens of MB an hour that the server could answer with a 304 on an unchanged page.
- Evidence: measured on this rig: document 1,667,928 bytes (JS 1,419,468, CSS 223,568); cached `render_page` 0.52 ms; encode 1.07 ms; `_sig()` (24 stats) 0.52 ms; gzip level 5 32.7 ms giving 557,530 bytes (level 1: 17.8 ms, 655 KB). handler.py:420-424 sends only Content-Type and Content-Length.
- Ledger: new
- Suggested change: keep `(sig, theme) -> (bytes, gzip bytes, etag)` in page.py's `_CACHE` (etag = `page_version()`, which already exists for sw.js), send `ETag` + `Cache-Control: no-cache`, and answer a matching `If-None-Match` with 304. "no-cache" still means "ask every time", so a deploy is picked up on the next load exactly as now. This must not change the bytes (tests/test_page_golden.py).
- Effort / risk: S effort; low risk

### cards-server-3 - Every pop-out panel window runs its own state poll loop
- Category: idle
- Severity: low
- Confidence: CONFIRMED (by reading; request rate not measured live)
- Where: MulticamPipeline multicam_pipeline/cards/page/08-places.js:347, :354; page/17-windows.js:676-705
- What: `poll()` is started unconditionally at the bottom of 08-places.js, and a panel window (`?panel=lane` etc.) is the same document, so main window + N pop-outs = N+1 independent pollers at 600 ms (REMOTE, i.e. every dashboard user) or 250 ms (localhost). The windows already talk over a BroadcastChannel (`winPost`), but only for selection and playhead. Nothing gates polling on `document.visibilityState`, so a hidden window relies on browser throttling.
- Cost / failure scenario: an editor with the main window, two pop-outs and a phone is 4 pollers, about 6.7 requests/s around the clock while those windows are open. Each request goes through the dashboard login gate, an a2wsgi thread hop and `engine.tick()`. A version change makes every window fetch its own delta or full state.
- Evidence: 08-places.js:347 `PTMR=setTimeout(poll, ... REMOTE?600:250)`; :354 `poll();` at top level; 17-windows.js sets `PANEL` from the URL but never stops the loop.
- Ledger: new
- Suggested change: let panel windows take the state the main window already fetched over the existing channel, with their own poll kept as a fallback when no main window answers for a few seconds. Or, more simply, stretch the poll to several seconds while `document.visibilityState === 'hidden'`. This must not slow the confirmation of an edit made from a panel window (PENDING keeps its 80 ms poll in that window).
- Effort / risk: M effort; medium risk (the confirm logic in poll() is subtle)

### cards-server-4 - Every Claude JSON turn leaves a temp directory and answer file that nothing deletes
- Category: disk-growth
- Severity: low
- Confidence: CONFIRMED
- Where: MulticamPipeline multicam_pipeline/cards/chat_edit.py:1427, :1545, :1552; transcript_search.py:1315; montage.py:280; library_engine.py:4465, :4537 (each `tempfile.mkdtemp(prefix="timeline_cards_...")`); read by library_engine.py:1962 `_run_claude_json`, which never removes it
- What: each chat turn, each shorten pass-2/3 section call (`lean_json`, about fifty per pass according to its own docstring), each search, describe and semantic search makes a new `timeline_cards_*` directory in the OS temp folder and leaves the answer JSON in it. The mounted runner writes the file there (`cards_ai._land_json`), and no code in either repo removes it.
- Cost / failure scenario: on the NAS container this is /tmp in the container, so it lasts until the next recreate. On a standalone PC server it is %TEMP%, which lasts indefinitely. Per shortening pass, about 50-60 directories (estimated 2-20 KB each); per chat turn, one. The bytes are small, but it is unbounded, and if /tmp is RAM-backed it is memory.
- Evidence: grep for `mkdtemp` and `rmtree` across cards/*.py: seven mkdtemp sites and no rmtree; `_run_claude_json` (library_engine.py:1962-1993) opens `out`, parses it and returns.
- Ledger: new
- Suggested change: in `_run_claude_json`, `shutil.rmtree(os.path.dirname(out), ignore_errors=True)` in a `finally` after the parse, but only when the directory name starts with `timeline_cards_`, so a caller passing a vault path never loses it.
- Effort / risk: S effort; low risk

### cards-server-5 - The transcript-search corpus re-walks the episode tree six times to answer one /api/search/scopes
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: MulticamPipeline multicam_pipeline/cards/transcript_search.py:684 (`corpus`), :601-649 (`state`, `_expects`), :741 (`scopes`)
- What: `corpus()` checks freshness with `_transcript_files(root)` (a listdir of Interviewees and of every person and clip folder, plus `clip_files`' listdir/isfile per clip) and then `_signature` (a stat per transcript), on every call. One `/api/search/scopes` answer calls it through `scopes()`, `_pick`, `chars`, `all_chars` and twice in `_expects`, so six full walks. The search modal asks for it on every open and on every scope, model or mode change, and the chat panel's `_corpus_state` adds another walk.
- Cost / failure scenario: synthetic episode with 15 interviewees and 200 clips: one answer = 1,291 stats + 1,302 listdirs, 58 ms on local NTFS (one walk 9.4 ms / 215 stats). On the NAS's local ZFS that is tolerable. A standalone PC server whose vault is an SMB share pays about 0.5-1 ms per call, roughly 1-2.5 s per modal open, and the walk count scales linearly with clips (estimated 6x that at 1,000 clips).
- Evidence: probe_tsearch.py, counting via wrapped os.stat/os.listdir.
- Ledger: new
- Suggested change: memoise the signature for a short TTL (say 2 s) or compute it once per request and pass the corpus into `state`/`_expects`. A changed transcript would still invalidate within the TTL, and the corpus hash, which is what keeps a conversation honest, is unchanged.
- Effort / risk: S effort; low risk

### cards-server-6 - A failed whisper corpus run leaves its scratch folder in %TEMP%
- Category: disk-growth
- Severity: low
- Confidence: CONFIRMED
- Where: MulticamPipeline multicam_pipeline/transcripts/whisper_corpus.py:678 (`mkdtemp`), :794 (`rmtree`, success path only); `run_worker` raises at :554
- What: the scratch directory holds the worker's `run.json` and the diarizer's `.turns` file ("megabytes of intermediate JSON" per the comment at :674). It is removed only on the last line of the success path. A worker that exits non-zero (CUDA OOM, a killed job), or an exception in `build_sidecar`/`write_markdown`, skips the cleanup.
- Cost / failure scenario: each failed transcribe on an editor's GPU machine leaves a few MB to tens of MB in that machine's temp folder, which nothing prunes. Failed runs are not rare, because whisper jobs are retried by the fleet scheduler.
- Evidence: read; no try/finally around :678-794.
- Ledger: new
- Suggested change: wrap :678-794 in `try/finally: shutil.rmtree(scratch, ignore_errors=True)`.
- Effort / risk: S effort; low risk

### cards-server-7 - The two translation caches only ever grow, one entry per distinct text a cut has ever had
- Category: disk-growth
- Severity: low
- Confidence: PLAUSIBLE (growth rate estimated)
- Where: MulticamPipeline multicam_pipeline/cards/translate.py:144 (`key`), :154 (`put_many`), :356 (`GoogleTranslator._save`)
- What: both stores are keyed on the exact words of a cut, so every trim, split or extend that changes the text adds a new entry, and nothing ever removes the old one. `put_many` rewrites the whole file, and `GoogleTranslator._save` re-reads and merges the whole file every 25 fetches, on the shared vault file written by two processes.
- Cost / failure scenario: estimated at a few hundred bytes per entry and hundreds to low thousands of re-cuts per episode, so roughly 0.5-5 MB per episode file over a long edit. Each save becomes a whole-file parse and rewrite of that size (tens of ms), and so does every 1 s re-read when the other machine has written. This is not urgent at today's scale.
- Evidence: read; no pruning path in translate.py, and the file comment says "safe to delete entries".
- Ledger: new
- Suggested change: when a store is saved, drop entries whose `ts` is older than N months and whose key is not one of the current cards' keys (the sweep already computes those). The keys of live cards must never be dropped.
- Effort / risk: S effort; low risk

## What is already good
- `api/state`: deltas by apply_seq, a small "unchanged" answer, and a gzip cached per (version, tail) on the engine (`gz_cached`). At 500 cards the poll does not re-serialise the state. Leave it alone.
- Media: `_serve_range` streams 64 KB chunks with strong validators and handles client aborts, and ccsync's `cards_wsgi._Writer` streams them through without buffering the file. `/api/peaks` has an ETag and returns 304.
- `/api/pcm` scrub is already single-flight on the page and reads the m4a extraction first (GOTCHAS 4b). Offline words and manifest are cached per version (CR-351). `projects_state` is TTL-cached, and the Google translator's republish is debounced to the idle edit worker (12 s).
- The transcript-search corpus is cached against (path, mtime, size). Subsets are cut from parsed docs, and the runner's breakpoints now cover the first and last corpus part (the 139 s warm search fix holds: cards_ai `_for_send` and `_trimmed` keep every lead corpus turn).

## Coverage note
Not read: shorten.py passes 1-3 prompt bodies (beyond the turn-record writes and `lean_json`), montage.py, text.py beyond `transcript_pairs`, canvas/, pipeline_web.py and reorder_web.py (dev-only entry points), whisper_worker/diarize_worker model lifecycle, transcript_search lines 1000+ (result matching), and library_engine/project_engine/agent (another territory). The edit-chat context-window ceiling (finding 1) depends on the configured models' context sizes, which I did not check. The chat turn-record sidecar (`<name>.chat.json`, 50 turns, re-read twice and rewritten per shorten section write) was not sized against a real file because the vault is on the NAS. One small `_serve_range` edge: a suffix range (`bytes=-N`) is answered from offset 0, and an out-of-range start gets the last byte instead of a 416. No browser media element seen sends either.

## OUT OF TERRITORY
- ccsync dashboard/src/ccsync_dashboard/cards_ai.py: `<data>/cards_sessions/<id>.json` is never pruned. Every reset, cold re-open, session_lost or corpus change mints a new uuid (`ClaudeSession.reset`, `_reopen`), and each orphaned file holds the full corpus messages (hundreds of KB to MB).
- MulticamPipeline cards/text.py:40 `transcript_pairs(folder)` parses every transcript in a folder, and transcript_search `_blocks_of` calls it once per file. That is quadratic in transcripts per person folder (usually 1-2).
