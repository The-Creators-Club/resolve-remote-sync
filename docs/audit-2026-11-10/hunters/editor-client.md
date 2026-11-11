# editor-client - the rebuilt Timeline Cards editor: client/ and audio/ (branch standalone-editor, read-only)
Tree: `C:\Users\alex\AppData\Local\Temp\claude\tc-standalone\Resolve\MulticamPipeline\editor` (files read 2026-11-10 23:59 to 2026-11-11 00:40).
Files read (approximate coverage): PERF.md (all); audio/engine.ts, cache.ts, graph.ts, http.ts (all); client/state/store.ts, boot.ts, undo.ts, timeline.ts, sync.ts (most); client/shell.ts, features.ts (tipHeader), fontWarm.ts; client/views/app.ts (lines 150-930, 1700-2050), cards.ts (60-110, 200-525), ui.ts, peaks.ts, chrome.ts (transport/playbar/status), videoTab.ts (130-280), laneBar.ts (455-500), laneWords.ts, laneText.ts caches, model.ts viewModel; client/device/audio.ts, decode.ts; client/input/pad.ts (mount loop); core/src/hash.ts; dist/ sizes. lane.ts only by grep and spot reads (2080-2185, 2725-2985). Every addEventListener / observer / rAF / setInterval in client/ listed by grep and checked for its removal.
Probes run: `resampleAt` from client/device/decode.ts copied verbatim into the scratch folder and timed under node (V8): one 5 s window 48 kHz -> 44.1 kHz = 24.8 ms median; 48 kHz unaligned = 24.9 ms; the aligned 48 kHz copy path = 3.1 ms. dist/ byte counts (du / wc). No browser, no npm, nothing run in the tree.

## Findings

### editor-client-1 - On a phone or a landscape phone every playback frame is a FULL render
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: client/views/app.ts:467 (`#canFast`), render() 616-636, #renderEditor 672-749, #renderToasts 842-848
- What: `#canFast` returns null whenever `this.phone || this.landscape`, so on the devices with the weakest CPU the store's per-frame playhead tick never takes the fast or cut tier of PERF.md rule 1: every animation frame while playing runs header, rail, chips, `cards.update` (a signature string for every card), renderShelf, rows.update, inspector, lane, transport, play bar, status, tab bar, toasts and menu. The transport, play bar and status line are written with `setHtml` (innerHTML replace) there, not `patchHtml`, so the play bar (`Pause mm:ss`) and the status line (`x.x s of y s`) re-create their nodes every time the text changes, which PERF.md rule 5 measured at 2-3 ms of style+layout a time. While a toast is up, #renderToasts reads two getBoundingClientRect right after those writes (a forced layout per frame).
- Cost / failure scenario: 60 frames/s for the whole of playback on every phone session. app.ts's own comment measured the full render at 6-30 ms a frame on a 1,000-cut list on the desk; a phone is 3-5x slower (estimated 20-100 ms a frame), i.e. dropped frames and stutter in exactly the playback the Android app and the phone pages exist for. PERF.md's "0 frames over 10 ms" is a desk measurement and does not hold here.
- Evidence: app.ts:467 `if (b.view.mode === 'edit' || this.phone || this.landscape) return null;`; render() has no tiering; #renderEditor 740-745 use setHtml for transport/playbar/status; chrome.ts:90/94 put the running time into the play bar label.
- Ledger: new (PERF.md does not cover the phone path)
- Suggested change: let the phone take the same fast/cut tiers, adding what a phone tab draws from the head (play bar label, mini lane) to #renderFast, and use patchHtml for the transport/playbar/status in the full render too. Keep the full render for tab changes and edits.
- Effort / risk: M effort; medium risk (phone tab layouts must still update on cut change)

### editor-client-2 - Kept-clip audio windows are resampled on the main thread: 25 ms per 5 s window
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: client/device/decode.ts:95-121 (`resampleAt`), called by localWindow 229/245; engine pcmRate choice audio/engine.ts:162
- What: a kept (offline) clip's PCM window is decoded by WebCodecs off-thread but then resampled 48 kHz -> the context rate with a ~50-tap windowed sinc in plain JS on the page's thread. The engine fetches at `ctx.sampleRate` (44.1 kHz on many Mac, Bluetooth and Windows outputs), so every 5 s window takes the slow path. The same happens at 48 kHz for the WAV road whenever the window start is not on the source's sample grid.
- Cost / failure scenario: one window per 5 s of playback per playing clip, plus up to 8 s prefetch and the 3-4 windows a seek asks for. Measured 24.8 ms per window on this rig's V8 (a single long task), estimated 75-125 ms on a phone. At the PERF.md goal of no frame over 10 ms this is 2-3 dropped frames every 5 s of kept playback on the desk, and a visible hitch on a phone; a seek costs 4x that at once. PERF.md rule 12 ("anything that walks a whole file or sample buffer on the page needs" a Worker) is broken here.
- Evidence: scratch probe resample.mjs (verbatim copy): 44.1k 24.8 ms median, 48k unaligned 24.9 ms, 48k aligned copy 3.1 ms. CHUNK_S = 5 (audio/plan.ts:161); PCM_RATES includes 44100 (core/src/media.ts:30).
- Ledger: new
- Suggested change: run the resample in the existing stretch Worker (or a small one built the way hasher.ts builds its own), or fetch kept windows at 48 kHz and let the AudioBuffer be created at 48 kHz (Web Audio resamples a 48 kHz buffer for free in the render thread). Must keep the sample-exact length the server would answer.
- Effort / risk: S-M effort; low risk

### editor-client-3 - Peaks fetched and parsed twice per clip, and the lane's level target drifts from what the engine plays
- Category: bug
- Severity: medium
- Confidence: CONFIRMED
- Where: client/views/peaks.ts:68-81 (`PeaksCache.gain`), audio/engine.ts:269-296 (`recomputeTarget`, `loadPeaks`), client/state/boot.ts:150, client/device/audio.ts:96-104
- What: (a) the engine (`opts.source.peaks`) and the views' PeaksCache (`source.peaks` passed in by boot) each fetch and parse every clip's .peaks; the source has no memo, so each clip costs two requests, two parses and two ClipLevels in memory. (b) The engine's auto-level target is the median of the clips IN THE CUT now (q1-k5, 2026-10-30, "a clip whose last cut went kept pulling the median"); PeaksCache's target is the median of every clip it has ever loaded and is only recomputed when a new clip arrives. After a clip's last cut is deleted (or for clips the rows panel loaded), the lane draws every waveform at a different auto-gain from the one the engine plays and the export bakes: exactly the q1-k5 mismatch, back in the drawing.
- Cost / failure scenario: (a) peaks are 200 B/s, so a list over 50 one-hour interviews is ~36 MB fetched twice on open (72 MB, estimated) and held twice. (b) delete the last cut of a loud clip: the engine re-levels at once, the lane keeps the old median until another clip loads; every waveform height is wrong by the difference (several dB on a wide-crest list).
- Evidence: peaks.ts:74-78 median over `this.#slots.values()`, `#target = null` only in the fetch callback; engine.ts:273-276 filters by `inUse`; keptAudioSource.peaks and httpAudioSource.peaks keep nothing.
- Ledger: related to q1-k5 (the engine's fix was not carried to peaks.ts)
- Suggested change: one peaks memo in the source (a Map of promises per clip, cleared with the project), used by both; give PeaksCache the target from the engine (or compute it from the clips of the current project and reset it on project change).
- Effort / risk: S effort; low risk

### editor-client-4 - The Video tab runs a frame loop for as long as it is showing, paused or not, and rewrites the DOM every frame in a gap
- Category: idle
- Severity: low
- Confidence: CONFIRMED
- Where: client/views/videoTab.ts:238-261 (#tick), 231-236 (#show)
- What: while the tab is visible, #tick reschedules itself every frame whatever the store is doing; on a paused, still head it still builds the URL (two encodeURIComponent), reads state and calls #show. With the head in a gap, on a clip with no preview, or with no list open, #show sets `msg.textContent` to the same non-empty sentence every frame, which replaces the text node (a childList mutation, a style/layout invalidation, and a wake of the root-wide MutationObserver of editor-client-5).
- Cost / failure scenario: 60-144 wakeups/s for as long as an editor leaves the Video tab up and walks away (hours), on a page that otherwise idles at zero; in a gap that is also 60-144 DOM mutations + layouts + MO callbacks a second. Estimated well under 1 ms a frame, but it keeps the CPU out of its idle states on a laptop beside Resolve.
- Evidence: line 239 reschedules unconditionally; line 232 writes textContent unconditionally.
- Ledger: new (PERF.md rule 10 covers the hidden tab only)
- Suggested change: run the loop only while playing (or while a seek is settling) and redraw on store changes otherwise; `setText` instead of a bare textContent write.
- Effort / risk: S effort; low risk

### editor-client-5 - Two MutationObservers watch the whole editor (or the whole body) for one header and one panel
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: client/features.ts:201-206 (tipHeader, `observe(root, {childList, subtree})`, disposer dropped at shell.ts:134); client/views/workspace.ts:376-381 (`#findObs` on `document.body` subtree)
- What: tipHeader only patches buttons in `.L-editor > .top`, but observes every childList change in #app: every card reconcile, every lit-word `q.innerHTML` (cards.ts:357/364, several a second while playing), every setHtml. Each batch queues records and an rAF that runs two querySelectorAll over the header. The workspace's #findObs watches the whole body until the transcripts panel appears; if the transcripts feature is off or fails to mount it never disconnects and runs `panel('transcript')` (a document querySelector) on every mutation batch for the life of the page.
- Cost / failure scenario: a few to 60 callbacks/s during playback (every frame on a phone, editor-client-1); MutationRecord allocation proportional to nodes touched on each edit (hundreds on a cards reconcile). Estimated tens to hundreds of microseconds a frame; not large, but pure waste inside the 10 ms budget.
- Evidence: the two observe() calls above.
- Ledger: new
- Suggested change: observe the header element only (`.L-editor > .top`), and let the transcripts feature announce its panel (an event, like tc:panel-shown) instead of a body-wide observer.
- Effort / risk: S effort; low risk

### editor-client-6 - Card drag does an O(n) layout walk per pointermove, with scroll writes before the reads
- Category: perf
- Severity: low
- Confidence: PLAUSIBLE
- Where: client/views/app.ts:1971-2017 (onMove), 1912-1950 (landing), 2006 (marquee)
- What: each move of a card drag runs `cardEls()` (querySelectorAll of every card), getBoundingClientRect on cards until the landing is found (every card for the marquee), `firstInSec` querySelectorAll per section, and `order()` which rebuilds `ctx()` (a new Set and section lookup) plus three O(n) arrays to test "same order". Near an edge it first writes `cardsEl.scrollTop` and then reads rects: a forced synchronous layout per move. Auto-scroll also only happens on a move, so a pointer held still at the edge does not scroll.
- Cost / failure scenario: once per frame of a drag (Chrome aligns pointermove to frames); n = 316-1,000 cards. Estimated 1-5 ms per move with a forced layout near the edges; a marquee over a 1,000-card list reads 1,000 rects a move.
- Evidence: code read; not measured (no browser run allowed in the tree).
- Ledger: new
- Suggested change: snapshot card rects once at drag start (and on scroll), binary-search them per move; coalesce into one rAF; drive edge auto-scroll from an rAF while the pointer is in the edge band.
- Effort / risk: M effort; low risk

### editor-client-7 - One 1.29 MB bundle with every feature imported eagerly; dist ships 11.6 MB nobody downloads
- Category: deploy
- Severity: low
- Confidence: CONFIRMED
- Where: client/platform/features.gen.ts (17 static `import { feature }`), dist/main.js, dist/assets, client/fontWarm.ts
- What: every feature's client (chat, shorten, montage, align, resolve, video, transcripts ...) is statically imported into main.js (1,292,588 bytes minified), so every page load parses and compiles all of it, including features the server turns off (`serverFeatures` / `locallyOff`). dist/ is 19 MB: 216 .woff files (5,899,260 bytes) duplicating the .woff2 faces every supported browser uses, plus main.js.map (4.9 MB) and main.css.map (0.8 MB). The desktop font warm-up (fontWarm.ts, PERF rule 8) loads EVERY unloaded face, including Cyrillic, Cyrillic-ext, Vietnamese and the italic/600 Plex cuts the editor's Mandarin/English text never shows (242 woff2, 4.98 MB total, of which 4.6 MB is Noto TC).
- Cost / failure scenario: startup parse/compile of ~1.3 MB on every open (estimated 50-100 ms desk, 200-400 ms phone); 11.6 MB of dead bytes in every deploy/package of the editor (61% of dist).
- Evidence: byte counts from dist/ (read only); features.gen.ts header.
- Ledger: new
- Suggested change: esbuild `splitting: true` with `import()` per feature behind the server's feature list; drop the .woff fallbacks and ship the maps separately (or not at all) in the deploy; give warmFonts a filter to the Noto TC and Latin faces. Must keep the editor working offline (the service worker must precache the chunks).
- Effort / risk: M effort; medium risk (offline precache list)

### editor-client-8 - The whole undo history is structured-cloned to IndexedDB after every edit
- Category: perf
- Severity: low
- Confidence: PLAUSIBLE
- Where: client/state/store.ts:259-268 (undoChanged / writeUndo), client/state/undo.ts:18, core/src/guard.ts:102-113 (expectOf adds the full `order` for layout ops)
- What: 250 ms after any edit the store writes `{undo: [...200 steps], redo: [...]}` to IndexedDB. A step that re-arranges carries `expect.order` (every row id) and a restore inverse, so the record grows with list size x depth.
- Cost / failure scenario: per edit (debounced 250 ms). At 200 steps on a 500-row list with mostly moves, estimated ~1-2 MB structured-cloned on the main thread per write (a few ms) and rewritten whole each time; a trim session of hundreds of nudges rewrites it hundreds of times.
- Evidence: code read; size estimated from the step shape, not measured.
- Ledger: new
- Suggested change: store steps under per-step keys (append/delete) or write only the changed tail; keep the 200 cap.
- Effort / risk: M effort; low risk

### editor-client-9 - A store listener runs `root.querySelector('.lane')` on every store change
- Category: perf
- Severity: low
- Confidence: PLAUSIBLE
- Where: client/state/boot.ts:159-167 (bindLane)
- What: to rebind input when the lane element is redrawn, boot subscribes `bindLane` to the store; every set() (every frame while playing, every scroll/zoom dispatch) runs `root.querySelector('.lane')`. The dock comes after the cards list in document order, so the walk crosses the whole list (~20 nodes a card).
- Cost / failure scenario: 60-144 calls/s while playing, n = 6,000-20,000 nodes at 316-1,000 cards; estimated 50-200 us each. Small, but inside every playback frame.
- Evidence: code read; the lane element is created once by `new Lane(...)` in App's constructor (app.ts:174-175), so the lookup almost never finds anything new.
- Ledger: new
- Suggested change: have the views tell boot when the lane element changes (or compare `state.view.mode` and only look then).
- Effort / risk: S effort; low risk

### editor-client-10 - viewModel builds its own timeline instead of the store's cached one
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: client/views/model.ts:62 (`timeline(project)`) vs client/state/timeline.ts:17 (`timelineOf`, WeakMap)
- What: every new Project (every edit, local or remote) has its timeline computed by the store's `timelineOf` and again, separately, by `viewModel`; the two objects are equal but distinct, so per-project memos keyed on one miss for the other.
- Cost / failure scenario: one extra O(rows) timeline per edit (316-1,000 rows), estimated well under 1 ms; plus a second copy of entries/items in memory per live project.
- Evidence: model.ts:62.
- Ledger: new
- Suggested change: `const tl = timelineOf(project)` in viewModel.
- Effort / risk: S effort; low risk

## What is already good
- audio/: the PCM window cache is byte-capped (64 MB) with an in-flight limit, soonest-first queue and failure backoff; the scheduler interval and the onTime rAF run only while playing; voices and scrub grains disconnect their nodes; one AudioContext per engine, closed on dispose; keep-awake removes its document listeners. Leave it alone.
- client/state/timeline.ts (WeakMap per Project, binary search for the head) and views/model.ts's viewModel memo make the per-frame playhead path cheap on the desk.
- Bounded caches everywhere they were checked: laneWords (48-clip LRU, 3 in flight), laneText's wrap/width/ink memos, cards/lane `#found` (8), engine chainEnd (4,096), undo (200), notices (50).
- Every listener / observer / rAF in views (App `#off`, Lane, LaneBar, RowsView, Workspace), input (pointer, keyboard, pad) and sync.ts has a matching removal; the gamepad poll runs only while a pad is connected.

## Coverage note
Not reached: lane.ts's draw/overlay internals beyond grep (PERF.md measures them; I did not look for regressions line by line), rows.ts, laneBar.ts beyond the observers, laneWords/laneText algorithms, input/pointer.ts and keyboard.ts bodies, device/ (opfs, fsstore, hasher, answer), audio/stretch.ts and levels.ts, replica.ts. No browser measurement was possible (read-only tree), so editor-client-1/6/8/9 costs are estimated from the code's own measurements and shapes. Memory after an hour of editing was not measured.

## OUT OF TERRITORY
- server/ (media routes): whether /media/peaks and /media/pcm send cache headers decides whether editor-client-3's double fetch reaches the network.
- client/sw.js precache list must change if editor-client-7's code splitting is done.
