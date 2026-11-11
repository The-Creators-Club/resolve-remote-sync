# editor-features-a - rebuilt Timeline Cards editor: transcripts, shelf, lane, markers, video, aids, align, looks, keep, gapnotes, montage (client + shared halves)
Files read (approximate coverage): PERF.md (all), ARCHITECTURE.md §14.1 (feature mount/dispose contract); features/align/shared.ts (lines 600-1197 in full, the rest by symbol); features/transcripts/client.ts (state, open/close, layout watchers, find, follow/paint marks, render/syncBody/blockHtml, destroy, platform feature: ~45%), transcripts/shared.ts (sliceWords, transcriptTokens, foldShift, spanChanged, cursor/find helpers: ~40%), transcripts/derive.ts (all), transcripts/service.ts (all), transcripts/player.ts (all), transcripts/library.ts (caches); features/shelf/client.ts (subscribe, render path ~25%); features/markers/client.ts (render, subscribe, destroy ~30%); features/video/slave.ts (pool, all of 150-313), video/client.ts (element creation); features/keep/client.ts (timers/dispose); listener/timer/observer census of every client file in the territory (grep counts).
Probes run (all in scratchpad `editor-features-a\`, plain node 24 against a COPY of align/shared.ts and verbatim copies of the loops; nothing run in the editor tree):
- `probe_align.mjs`: projectCut / englishOfSpan / overrunOf / bestEnglishOfCut on synthetic 3-hour Mandarin paragraph alignments (300 x 160 and 600 x 80 Han characters, phrases of 8 words).
- `probe_spans.mjs`: the transcript panel's `#blockHtml` `spans()` loop for every block x field, as `#syncBody` runs it with a cut shown.
- `probe_foldshift.mjs`: transcripts/shared.ts `foldShift` (+ core/src/text.ts `foldMap`) over 30k and 50k tokens.

## Findings

### editor-features-a-1 - Transcript panel scans the WHOLE word index once per paragraph per line on every redraw while a cut is shown (70-255 ms per keystroke / edit)
- Category: perf
- Severity: high
- Confidence: CONFIRMED
- Where: features/transcripts/client.ts:2702-2711 (`#blockHtml` -> `spans()`), called for every block from `#syncBody` (2662), which runs from `#renderFind` (1057, every find keystroke), `#render` -> `#renderDoc` (every edit while the panel is open: `#onState` 420, plus 36 other `#render()` calls: pick, clear, selection)
- What: when the panel is showing a cut (`#shown`, the usual way in: select a card -> `showCut`), `spans(field)` walks ALL of `d.words` (every timed word row of the transcript, both languages) to find the rows of ONE paragraph's ONE line. It runs twice per paragraph, so one `#syncBody` is blocks x 2 x words. The per-paragraph string diff that PERF.md rule 15 relies on only starts after this loop.
- Cost / failure scenario: measured on the verbatim loop: 267 paragraphs / 48k word rows (PERF.md's own reference interview size) = 69.7 ms per `#syncBody`; a 3-hour interview, 600 paragraphs / 72k rows = 255 ms. That is paid on every find keystroke, every edit anywhere in the cut list (incl. the words service's setText batches) and every pick, while a cut is shown. PERF.md rule 15 claims "typing p50 25-35 ms, no long task above 60 ms"; that only holds with no cut shown.
- Evidence: probe_spans.mjs output: `blocks=267 words=48060: 69.7 ms`, `blocks=600 words=72000: 255.2 ms`; grouping the rows by `ref|field` once (rebuilt each time even) = 2.6 / 3.9 ms.
- Ledger: new (PERF.md rule 15 claim not kept in this path)
- Suggested change: index `d.words` by `ref|field` once per document (a WeakMap on the `words` array, like `#fidx`), and have `spans()` walk only that paragraph's rows; optionally also cache the shown cut's span list per (doc, shown). Output is identical; the midpoint rule is unchanged.
- Effort / risk: S effort; low risk

### editor-features-a-2 - englishOfSpan / bestEnglishOfCut re-squeeze every paragraph of the clip on every call (5-7 ms per lookup at 600 paragraphs, on the edit frame)
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: features/align/shared.ts:728-748 (`wordsInCut` squeezes `al.orig` each call), 684-703 (`bestEnglishOfCut` calls it for EVERY stored alignment), 1097 (`englishOfSpan`), 1123/1172 (`overrunOf`, `underrunOf`); callers: features/translate/local.ts:56 (page, "synchronously, in the frame of the edit"), features/translate/server.ts:127/397
- What: to find which paragraphs hold a cut, each paragraph's original text is folded to letters (regex per code point) and `indexOf`-searched, for every paragraph, every call. `squeezedOf` (a WeakMap memo, line 957) already exists for spanParts but `wordsInCut` does not use it, and there is no "does this paragraph even contain the letters" prefilter.
- Cost / failure scenario: 3-hour interview clip, 300-600 stored paragraph alignments: englishOfSpan 4.3-7.0 ms per call, overrunOf 4.6-6.4 ms. translate/local.ts memoises by cut key, but a trim or split mints a new key, so each edit of an interview cut pays it inside the 10 ms frame budget (PERF.md goal); a list of hundreds of cuts loading or a whisper re-cut pays it once per cut (300 cuts x 5-7 ms = 1.5-2 s of main thread, estimated).
- Evidence: probe_align.mjs (P=600): `englishOfSpan (inside 1): 4.75 ms`, `bestEnglishOfCut: 4.98 ms`, `wordsInCut x P: 4.85 ms`; a prefilter on memoised letters (`cutLetters` per paragraph, then `includes(needle)`): 0.02 ms.
- Ledger: new
- Suggested change: memoise each alignment's squeezed letters + positions (extend `squeezedOf` to carry `at[]`) and use it in `wordsInCut`; in `bestEnglishOfCut` skip paragraphs whose memoised letters do not include the needle before calling `englishOfCutDetail`. Same answers, same tie-break order.
- Effort / risk: S effort; low risk

### editor-features-a-3 - projectCut costs 25-47 ms per call on the server event loop (quadratic edge search, nothing memoised), and one caller re-runs it on every request
- Category: perf
- Severity: medium
- Confidence: CONFIRMED (cost); PLAUSIBLE (call frequency of the aids caller)
- Where: features/align/shared.ts:809-935 (`projectCut`: 839-854 the per-paragraph search; 868 `squeeze(par.orig)` again for kept hits); callers features/align/server.ts:216-229 (`derived`, memoised, a MISS retried every 20 s) and features/aids/server.ts:416-424 (`derivedWords`, no memo, plus one sidecar read per paragraph, sequential awaits)
- What: for every paragraph of the clip that is not a whole containment, the head/tail overlap search loops `len = min(T,S)-1 .. 4` and builds two joined strings (`slice().join(SEP)`) per length, after joining both whole arrays for `idx()`; each paragraph is also re-squeezed per call. All synchronous on the Node server that also carries the sync WebSocket hub.
- Cost / failure scenario: 3-hour interview clip, 300 paragraphs x 160 letters: 24.6 ms per call; 600 x 80: 44-47 ms per call. A cut whose English is not the transcript's (a miss, null) is re-projected every 20 s per unit asked for; `derivedWords` re-projects on every word-links request for the lane's playhead word. With several cuts of a long interview on screen that is tens to hundreds of ms of blocked event loop per batch (estimated), during which every client's ops wait.
- Evidence: probe_align.mjs: `projectCut (cut spans 2 paragraphs): 24.62 ms/call (P=300)`, `43.96-46.72 ms/call (P=600)`.
- Ledger: new
- Suggested change: memoise per alignment object the squeezed letters (as in finding 2), find candidate paragraphs by `includes` on the joined letters (containment both ways) and compute the edge overlap with one KMP/`startsWith` pass over the cut's head/tail instead of rebuilding strings per length; memoise `derivedWords` by (project, al.key, words.length) like `derived`. Must keep the 0.9 coverage rule and the longest-hit-first selection.
- Effort / risk: M effort; low risk (pure function with tests)

### editor-features-a-4 - The words service folds the clip's whole token stream again for EVERY changed cut (foldShift), synchronously
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: features/transcripts/shared.ts:587-614 (`foldShift`: 594-599 walks and `foldMap`s every token of the clip, string-concatenating), called from `wordsFix` (566) inside the synchronous per-clip loop of features/transcripts/derive.ts:52 (`fixesFor`), which serves every span edit and the "Refresh all words" sweep (`sweep`, 209-221)
- What: the folded letter stream of a clip's tokens and its boundary set depend only on the tokens array (cached by file stat in service.ts), yet are rebuilt for each cut whose text changed; the loop over a clip's cuts has no await, so the whole batch blocks the server.
- Cost / failure scenario: 4.0 ms per changed cut at 30k tokens, 7.0 ms at 50k (a 3-hour interview). A single trim pays it once (fine); a sweep, a whisper re-run (the 707-cut re-cut cited in shared.ts 343) or an undo of a multi-cut edit pays it per cut: 700 x 5-7 ms = 3.5-5 s of blocked event loop on the dashboard-hosted editor server, during which sync, media and the WebSocket pings stall.
- Evidence: probe_foldshift.mjs: `foldShift over 30000 tokens: 4.0 ms/call`, `50000 tokens: 7.0 ms/call`.
- Ledger: new
- Suggested change: memoise `{ f, starts, boundary }` per tokens array in a WeakMap (the pattern `sortedCache` already uses at 506), and find `p` by bisect on token mids; optionally yield (`await` a macrotask) every N cuts in `fixesFor`. Results identical.
- Effort / risk: S effort; low risk

### editor-features-a-5 - The shelf replaces every staged card's DOM when any one changes
- Category: perf
- Severity: low
- Confidence: PLAUSIBLE
- Where: features/shelf/client.ts:585-619 (`#renderHost`: the signature includes the whole project `p`, then `setHtml(host, html)` = `innerHTML` of the full list)
- What: the cheap signature check correctly skips playhead ticks, but any project change rebuilds the full shelf string (shelfView + every card) and, if one staged card's markup differs (a colour, a gain, the words service's setText on a staged cut, the bench head moving to another card), replaces all of the list's nodes, which PERF.md rule 5 ("Patch, don't replace", `morphInto`) exists to avoid.
- Cost / failure scenario: on a 667-staged-card list (PERF.md's reference), every staged-card edit re-creates ~667 card subtrees and restyles them; estimated 10-30 ms per change (not measured: no browser run allowed in the tree), more during a words-service burst of setText batches (PERF.md 13: 8 batches).
- Evidence: code read; `setHtml` (client/views/ui.ts:163) is string-compare then `innerHTML`.
- Ledger: new
- Suggested change: draw the list with `morphInto`/`patchHtml` (as cards do) or key rows by cut id and replace only rows whose markup changed (the transcript panel's `#bodyList` diff is a ready pattern). Keep the content-visibility rule.
- Effort / risk: S-M effort; low risk

## What is already good
- video/slave.ts: `<video>` elements are POOLED (POOL_MAX, LRU eviction that spares the shown and protected slot), freed with `removeAttribute('src') + load()` so decoders go, only one decodes at a time, and held seeks are throttled to one per 200 ms. Leave it.
- transcripts: the playhead word is painted with the CSS Custom Highlight API only when the word index changes (`#follow` bisects a memoised `wordOrder`), layout watchers (resize, ResizeObserver, MutationObserver) live only while the panel is open, and `destroy()` releases timers, player, keys and observers. transcripts/player.ts reuses one `<audio>` element and one rAF loop.
- transcriptTokens (Needleman-Wunsch) is banded by paragraph +/- 2 s and capped at 4M cells, and cached per tokens/doc object in service.ts: the "30k x 30k DP" worry does not apply. Claude does the word alignment (MAX_WORDS 1500 per unit), not a local DP.
- keep/client.ts and markers/client.ts dispose every interval, timer, window listener and fetch controller they start; markers skips a playhead tick with a string signature and only moves the head marker.

## Coverage note
Not reached in the time box: transcripts/client.ts selection/act bar/intake/bins halves, transcripts/shared.ts FindIndex internals, shelf/ops.ts and words.ts, lane/client.ts, markers/fold.ts, video/client.ts (beyond element creation), panels/windows/popout, aids (client.ts, cache.ts, join.ts, lexicon), align/client.ts, looks, gapnotes, montage, keep/plan.ts. The listener census showed no obvious unpaired timers in those files (keep's 4 listeners sit on its own layer, removed with it), but they were not read line by line. No browser-side measurement was possible (no run in the tree), so finding 5 is estimated.

## OUT OF TERRITORY
- features/translate/local.ts:27: `#memo` (per cut key, every trim mints a new key) is cleared only on `reset()`; grows per edit for the session.
- features/aids/server.ts:416: `derivedWords` awaits one sidecar read per paragraph sequentially and has no memo (cost of the projectCut it calls is finding 3).
- features/transcripts/derive.ts:163: each words-service watcher keeps a full replica of the cut list and `spanChanged` rebuilds a Map of all cuts per log entry; fine today, worth noting at 16 open lists.
