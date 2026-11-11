# editor-features-b - rebuilt Timeline Cards editor: shorten/search/chat/translate/resolve/projects + every feature's server half
Files read (approximate coverage): PERF.md (all), ARCHITECTURE.md §14 (feature platform, pybridge, AI runner); features/translate/server.ts (all), features/align/server.ts (all), features/aids/server.ts (all), features/chat/server.ts (all) + chat/client.ts (load, timers, listeners) + chat/store.ts (bounds), features/shorten/server.ts (all) + shorten/client.ts (cancel/fan-out grep), features/search/server.ts (all) + search/bridge.py (Episode, Bridge, find/doc/pin, ~400 lines) + search/client.ts (find, poll), module-level caches of every features/*/bridge.py, scripts/assist-links.ts (head), server/ai/runner.ts (slot/queue), server/pybridge/index.ts (pinning, grep). All paths below are in the tc-standalone tree `Resolve/MulticamPipeline/editor` unless named.
Probes run: (1) `find_probe.py` (scratch `editor-features-b\`): a stdlib copy of search/bridge.py `Episode.docs/entry/entry_for_path` + `_transcript_files` + `clip_files` over a synthetic episode on local NTFS SSD, n = 100 and n = 520 transcripts. (2) node: JSON.parse+stringify and stringify+gzip of an 875 KB synthetic alignment file. No AI provider called; nothing run inside the editor tree.

## Findings

### editor-features-b-1 - Find (exact words) is quadratic in the episode's transcripts: 0.5-18 s per keystroke, uncancelled, on the shared pinned Python worker
- Category: perf
- Severity: high
- Confidence: CONFIRMED
- Where: features/search/bridge.py:700-750 (`c_find`), :439-445 (`entry_for_path`), :410-433 (`Episode.docs`), :609-646 (`_decorate`); client features/search/client.ts:302-312, 851 (250 ms debounce)
- What: `Episode.docs()` re-walks the whole episode (listdir of Interviewees/*, listdir of Clips/ and of every clip folder, stat of every transcript) on EVERY call; its cache only skips rebuilding `_tokens`. `c_find` calls `entry_for_path` once per document, and that calls `docs()` and then loops all tokens doing `normcase(abspath())`: n walks + n^2 path normalisations. Each result row (up to 200) is then `_decorate`d, which calls `entry()` -> another full walk per row. Every find also re-reads and re-parses every transcript file (`transcript_pairs` is uncached) and rebuilds `zh_charmap`/`zh_pinyin` per doc.
- Cost / failure scenario: runs per keystroke in the Find box (250 ms debounce, `runFind`); the server has no AbortSignal on it, so a superseded find runs to the end while the next one starts. Measured on local SSD (Windows): n = 100 transcripts -> 477 ms for the entry_for_path loop + 976 ms for 200 decorated rows = ~1.5 s per query; n = 520 -> 17.7 s + 6.4 s = ~24 s per query. Over SMB (the Windows app on P:) every walk is network round trips, so far worse; on the NAS container (Linux, local ZFS) estimated 3-5x faster than measured, still seconds at n = 520. Five keystrokes stack five finds on the `search` pinned worker (perWorker 4), and because they are CPU-bound Python they hold the GIL of a worker that is also pinned to other features (translate/chat/aids share 2 workers by `pinCursor`): the cards' English lookups and chat corpus reads stall behind them.
- Evidence: probe output: `docs: 520 one docs() walk 30.5 ms / find's entry_for_path loop 17673 ms / 200 decorated rows 6360 ms`; n = 100: `5.6 ms / 477 ms / 976 ms`. Read: `docs()` builds `sig` from a fresh `_transcript_files(root)` + `_stat` of each file before comparing.
- Ledger: new
- Suggested change: make `docs()` cheap on a hit (re-walk at most once per call / per second, e.g. a 2 s TTL or the corpus signature already computed), build a `normcase(abspath(path)) -> uid` dict once per docs refresh so `entry_for_path` is O(1), and cache `transcript_pairs` per file on its stat (as `_ANY_CACHE` already does for the re-read case). Pass the request's AbortSignal for find (unlike `/api/search`, a superseded find has no reader) so a newer keystroke cancels the older. Must not break: the doc/uid mapping when transcripts are added mid-session (keep the stat check, just not per row).
- Effort / risk: S effort; low risk

### editor-features-b-2 - Search worker keeps every episode's word index forever
- Category: leak
- Severity: medium
- Confidence: PLAUSIBLE
- Where: features/search/bridge.py:586-606 (`Bridge.engines`, no bound), :407 and :524-525 (`Episode._timing`, no bound)
- What: one `BridgeEngine` + `Searcher` per episode root ever searched is kept in `Bridge.engines` with no cap (only the data-root map is capped at 8), and each episode's `_timing` keeps, per transcript opened by doc/pin/decorate, its blocks plus the full `word_index` list (a 7-field tuple per word) for the life of the pinned worker.
- Cost / failure scenario: a 90,000-character interview is ~30-60k words; at an estimated ~250 B per word tuple with its floats/strings that is ~8-15 MB per transcript, ~100 MB for an episode with 10 interviews opened. The worker lives as long as the dashboard's editor child (weeks); ~100 episodes today, 500 at commercial scale: hundreds of MB to GB in one Python process on the NAS that also runs the dashboard, with no eviction until the worker restarts.
- Evidence: read only (no vault data touched); sizes estimated from PERF.md's 90,000-character interview.
- Ledger: new
- Suggested change: LRU `Bridge.engines` to a few episodes (the pool already pins, so a later call rebuilds) and cap `_timing` per episode (e.g. 24 transcripts, as transcripts/bridge.py `MAX_ENTRIES` does). Must not drop a running search's engine: evict only engines with no job in flight.
- Effort / risk: S effort; low risk

### editor-features-b-3 - aids word-link sidecar is written whole from memory with no merge: the q3-k4 lost-paid-answers bug, unfixed here, and the pipeline writes the same file
- Category: bug
- Severity: medium
- Confidence: CONFIRMED
- Where: features/aids/server.ts:153-193 (`Sidecar.put/flush`), :387-392, :423-434; scripts/assist-links.ts:63,117
- What: `Sidecar` reads `words.json` / `joins.json` once, keeps it in memory forever, and `flush()` writes the whole in-memory copy over the file. `features/align/server.ts:248-276` was fixed for exactly this (q3-k4, 2026-10-30: re-read and merge per key, newer `at` wins); the aids sidecar was not. `scripts/assist-links.ts` (the multicam pipeline's last stage) runs its own `AidsService` with `cutListRoot: null, readOnlyVault: false`, so it writes `<episode>/Script Docs/Cuts/.tcards/@aids/words.json` - the same file a `--write` editor server (or two servers on one root) holds in memory.
- Cost / failure scenario: the pipeline's assist pass links every paragraph of an episode (up to 2000 Claude calls per run). If the editor server has that folder's `words.json` loaded and stores one word link afterwards, its 150 ms flush writes its older copy over the file and every link the pipeline added since is gone; they are asked (and paid for) again on the next run or on demand. Also: the editor never re-reads the file, so even when nothing is lost it never sees the pipeline's new links until the sidecar is evicted (64 folders) or the server restarts.
- Evidence: read; compare align `#store` (merge from disk) with aids `Sidecar.flush` (no read). `tests/attack/q3-k4-two-servers-align-sidecar.test.ts` covers only the align sidecar.
- Ledger: related to q3-k4 (fixed in align only)
- Suggested change: give `Sidecar.flush` the align store's merge (read the file, take per key the record with the newer `at`, then write), and re-read on `get` when the file's mtime/size changed. Must keep the 5000-record bound and the debounce.
- Effort / risk: S effort; low risk

### editor-features-b-4 - Stored alignments and word links from the vault are cached without a stat: new pipeline output is invisible until restart
- Category: bug
- Severity: low
- Confidence: CONFIRMED
- Where: features/align/server.ts:189-205 (`#loadClip`, 32-clip LRU, vault file merged in once); features/aids/server.ts:427-433 (`#vaultSide`, read once)
- What: both caches load the vault's `.tcards/@align/<clip>.json` and `@aids/words.json` once and never look at the file again. The translate lookup (trimmed-cut English), `derived` and `derivedWords` all read through them.
- Cost / failure scenario: the assist pass runs at the end of a multicam pipeline, usually while the editor is up (it runs for days under the dashboard). An episode with fewer than 32 clips keeps its pre-pipeline alignments forever: cards keep saying "transcript not phrase-aligned yet", and a `now` selection pays for a Claude alignment the vault already holds.
- Evidence: read.
- Ledger: new
- Suggested change: keep `(mtimeMs, size)` next to each cached file and re-read when it changed (one `stat` per lookup per clip, cheap next to the JSON parse it replaces).
- Effort / risk: S effort; low risk

### editor-features-b-5 - One FIFO queue of 4 Claude slots for interactive and background work; a shorten fan-out takes all four
- Category: concurrency
- Severity: medium
- Confidence: CONFIRMED
- Where: server/ai/runner.ts:266-327 (`slot`: `maxConcurrent` 4, FIFO `waiting`, `free()` = `waiting.shift()`); features/shorten/ops.ts:32 (`PARALLEL = 4`), shorten/client.ts:394-402; align `DEFAULT_CONCURRENCY` 2, aids words 2 + joins 1, translate `TX_PARALLEL`
- What: every Claude user shares one runner with no priority. Background queues (alignment batches, word links, joins: 5 slots wanted) and long jobs (shorten: 4 opus calls with thinking on per fan-out; translate: 3) compete FIFO with the interactive ones: a chat turn the editor is watching stream, and an alignment `now` with a spinner on screen.
- Cost / failure scenario: the editor starts a shorten (4 sections at once, opus, minutes each) and then selects English text: the `now` alignment queues behind the shorten calls and any background batches; its 180 s timeout counts the queue wait, so it comes back `timeout` and the selection is labelled approximate. A chat message sits at "thinking" for minutes without a token. With 32 queued, new asks are refused `busy`.
- Evidence: read; 4 + 2 + 2 + 1 + 3 = 12 concurrent wanters against 4 slots in normal use.
- Ledger: new
- Suggested change: a priority on `run()` (interactive / normal / background) and let background runs take at most N-1 slots, so one slot is always free for a chat turn or a `now`; or cap shorten's fan-out at `maxConcurrent - 1`. Must keep the global cap and the cost budget.
- Effort / risk: M effort; low risk

### editor-features-b-6 - Shorten's model calls cannot be cancelled: a closed tab keeps opus running for up to 15 minutes per call
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: features/shorten/server.ts:293-302 (`call`, no `signal`), :347-399, :426-504; no `/api/shorten/stop` route; shorten/client.ts has no abort
- What: every shorten pass (structure, words, readback, scores) calls the runner with no AbortSignal and the runner's default 900 s timeout. Nothing in the route watches `res.on('close')` (chat and align `now` do).
- Cost / failure scenario: a whole-cut shorten is ~2 opus calls (words + readback) per section, 4 sections at a time: 10-20 sections = 20-40 thinking opus calls. Reloading the page or navigating away leaves all of them running and paid for, occupying the shared runner's 4 slots (finding 5) for their duration; the results are written to the record nobody is reading.
- Evidence: read.
- Ledger: new
- Suggested change: an AbortController per request, aborted on `res.on('close')` when not `writableEnded` (the chat route's pattern), threaded into `call()`; the page's "close the review" can also post a stop. Must keep: a section that fails leaves its row untouched with its error (already the catch path).
- Effort / risk: S effort; low risk

### editor-features-b-7 - Pinned Python workers keep a per-episode corpus and translation stores with no bound
- Category: leak
- Severity: low
- Confidence: PLAUSIBLE
- Where: features/chat/bridge.py:207-238 (`CORPORA`, root -> whole corpus text + refs); features/translate/bridge.py:65-66 (`STORES`, `DRAFTS` per Script Docs dir); features/chat/server.ts:369-386
- What: `CORPORA` keeps every episode's full transcript corpus (all chunks, every block ref) for the worker's life; `STORES`/`DRAFTS` keep each episode's `card_translations.json` / `gt_translations.json` loaded. Separately, every `GET /api/chat/state` (each panel open, cut-list switch, model change) ships the whole corpus over the pipe and `JSON.parse`s it on the Node event loop only to report counts.
- Cost / failure scenario: estimated ~1M characters per episode corpus (10 interviews x 90k chars) -> ~2-3 MB of Python strings per episode in the chat worker; ~100 episodes visited over weeks = ~200-300 MB that only a worker restart frees. The state call costs a ~3 MB JSON parse (~10-20 ms estimated) per panel open.
- Evidence: read; `ENGINES` beside them are capped (`ENGINE_KEEP`, `ENGINE_MAX`), these are not.
- Ledger: new
- Suggested change: cap `CORPORA`, `STORES`, `DRAFTS` (e.g. 8 episodes, oldest out; a store reloads from its file). Add a `corpus_info` bridge command that returns the counts and hash without `chunks`, for `/api/chat/state`.
- Effort / risk: S effort; low risk

### editor-features-b-8 - Shorten's record cache grows per cut list
- Category: leak
- Severity: low
- Confidence: CONFIRMED
- Where: features/shorten/server.ts:154-196 (`Records.mem`, `Records.queue`)
- What: `mem` holds every cut list's record (up to 8 passes, each with suggestions carrying `source.words` arrays) and `queue` holds each key's last update promise (its resolved value included) for the server's life; the scores map beside it is capped at 32, these are not.
- Cost / failure scenario: estimated 100 KB-1 MB per shortened cut list; ~100s of cut lists over weeks = tens of MB. Small, but unbounded.
- Evidence: read.
- Ledger: new
- Suggested change: the same 32-entry LRU the scores use, and delete the `queue` entry when its promise is the last one (as align's `#writeClip` does).
- Effort / risk: S effort; low risk

### editor-features-b-9 - Every stored alignment re-reads, re-parses and rewrites the whole clip sidecar
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: features/align/server.ts:248-276 (`#store`)
- What: per record (not per batch): `readFile` + `JSON.parse` of the clip file for the q3-k4 merge, then `JSON.stringify` + atomic write of the whole file. A batch of 4 answers = 4 full read/parse/stringify/write cycles of the same file; all synchronous parse/stringify on the event loop that carries every user's WebSocket.
- Cost / failure scenario: measured ~10 ms parse+stringify for an 875 KB synthetic file (the translate route's comment puts real ones at 100-550 KB per interview, up to 5000 records); background alignment of an interview = hundreds of records = seconds of event-loop time in 10 ms pieces, plus one fsync'd rewrite each.
- Evidence: node probe `parse+stringify ms 9.9`.
- Ledger: related to q3-k4 (the merge is correct; only its granularity costs)
- Suggested change: store a run's records in one `#store` call per clip (merge once, write once). Keep the merge.
- Effort / risk: S effort; low risk

## What is already good
- translate: the lookup's landed-count re-read loop is bounded to 3 rounds; the Claude run is chunked with a fixed parallelism and aborts cleanly on stop/close; clip-english is gzipped (6 ms for 875 KB measured).
- align/aids queues: bounded (2000 jobs, 5000 records per file, 4000 derived memo, 32 clips, 3000 analyses), resumable, and a `now` withdraws on request close; the state write is debounced.
- chat: single flight per cut list, aborts on request close, history/known/spent ids trimmed in store.ts; client timers and listeners are released on dispose.
- search `/api/search` running to the end is a deliberate choice (status hands the answer over); its status poll is 2 s only while a job is open.

## Coverage note
Not reached in the time box: features/resolve (client 1,051 lines, server.ts, companion.ts process lifecycle on abort/SIGTERM), features/projects (server.ts, host.ts, offline store), the client halves of shorten/search/translate beyond the greps above, and the server.ts of transcripts, lane, markers, video, gapnotes, montage. server/platform/workqueue.ts and server/pybridge internals were read only where a feature depended on them.

## OUT OF TERRITORY
- server/ai/runner.ts: the FIFO slot queue itself (finding 5's fix lands there).
- MulticamPipeline/multicam_pipeline/cards/text.py `transcript_pairs`: no cache, re-reads every transcript per call (also used by the live /cards page).
