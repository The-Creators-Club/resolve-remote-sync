# cards-page-a - Timeline Cards live page: state/render, markers, lane, keys, trim, places/poll, edit view, look, cards.html/css
Files read (approximate coverage): MulticamPipeline CLAUDE.md, GOTCHAS.md (all), docs/LANE-ZOOM-PERF-INVESTIGATION.md (takes four and five). Page: 08-places.js poll loop (230-354, full), 01-state.js applyDelta / takeState / sendEdit / render / cardItems / patchList / paintList (3340-4290), 02-markers.js followBump / flip / hilite / cardWordTick / list handlers (600-900), 03-lane.js normWire / normShareSrc (950-1040), laneModel (1586-1614), laneDraw head (2013-2120), audio pool / laneDrop / laneTrim / laneEl / lanePlay / laneTick (2395-2953), 05-keys.js selCard / cardEl, 06-trim.js markSel / stagedOrder, 09-edit.js edvBuild / edvRowHtml (99-211), cards.css greps for filters, backdrop-filter, will-change, infinite animations, content-visibility. Listener inventory by grep over all nine JS files. Roughly 25% of the territory's lines read in full; the rest by targeted grep.
Probes run: the page assembled by `page.render_page('')` into my scratch folder, loaded from file:// in headless Chrome (`--headless=new --mute-audio --remote-debugging-port=0`, no server, no fixed port) with a fetch stub serving a synthetic 500-card state (7 multicams) and an "unchanged" answer when `v` matches. Measured: DOM size, `hilite()` cost, idle `laneDraw` count over 5 s, a one-card version bump (render time + MutationObserver count), event listeners on document/window/#list/lane canvas before and after 30 version bumps + 10 lane toggles + 10 edit-view toggles, JS heap across 200 version bumps, live audio objects (Runtime.queryObjects after GC) after 80 `laneEl` calls over 40 multicams, and with the edit view open: rows/nodes/canvases and render cost across 10 version bumps. Scripts: `scratchpad\cards-page-a\probe.js`, `probe2.js`; outputs `probe-out-500.json`, `probe2-out-500.json`. Desktop CPU, unthrottled; phone numbers below are estimated by the 4-6x factor the repo's own CPU x4 runs use.

## Findings

### cards-page-a-1 - The edit view rebuilds every row by innerHTML on every new state version
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: MulticamPipeline multicam_pipeline/cards/page/09-edit.js:108-109 and :147-150 (edvBuild), reached from 01-state.js:4274 (paintList -> laneDraw(true) -> edvDraw -> edvBuild)
- What: edvBuild's cache key includes `CARDS` by identity, and render() assigns a fresh `CARDS=LIVE` array on every version, so any version bump (an edit confirm, every translate answer, a note, another device's edit) throws away all rows and rebuilds them with `EDLIST.innerHTML=rows.map(edvRowHtml).join('')`. The card list beside it got a keyed patch on 2026-09-03; the edit view never did.
- Cost / failure scenario: measured at 500 cards with the edit view open: 500 rows = 5,000 nodes including 1,000 `<canvas>` elements, rebuilt on 10 of 10 version bumps; render() goes from 5.7 ms (edit view shut, 3 DOM mutations for a one-card change) to 23.2 ms on the desktop. Estimated 90-140 ms per version on a phone at the repo's 4-6x CPU factor - and the edit view is the phone's main view (GOTCHAS section 22). A 91-card translate run republishes per answer, so that is ~91 full rebuilds; every edit costs one, on top of the waveform canvases each row must redraw.
- Evidence: probe2-out-500.json `edv` {rows 500, nodes 5000, canv 1000} and `edvBump` {rebuilds 10/10, rebuildMsAvg 4.6 (the innerHTML alone), renderMsAvg 23.2} vs probe-out-500.json `oneChange` {renderMs 5.7, mutations 3}.
- Ledger: new (LANE-ZOOM-PERF-INVESTIGATION section 10 fixed the shorten panel's forced `edvBuild(true)`, not this path)
- Suggested change: key edvBuild on what the rows DRAW (LSEG identity already changes only when laneModel rebuilds; or a per-row signature like cardItems' `stable` string) and patch rows by uid as patchList does, re-using each row's element and canvas; only `top`, number and the changed row need writing. Must keep EDKEY's existing invalidations (zoom, width, language, shorten removals) and the `cur` row bookkeeping (EDCUR reset).
- Effort / risk: M effort; medium risk (row elements are referenced by EDROWS[i].el and the loupe)

### cards-page-a-2 - An unchanged poll still repaints the whole lane canvas and walks every card row
- Category: idle
- Severity: low
- Confidence: CONFIRMED
- Where: MulticamPipeline multicam_pipeline/cards/page/08-places.js:319 and :347; 02-markers.js:790-818 (hilite)
- What: every poll whose version did not move calls hilite(), which unconditionally asks for a full `laneDraw` (and through it `edvDraw`) and removes/re-adds `.ph` on every child of #list, even when PH and PHUID are what they were last time. The poll runs every 600 ms on the NAS-served page (REMOTE) and keeps running in a hidden tab (no visibilitychange gate in 08-places.js; Chrome throttles it to 1/s, then 1/min after 5 minutes hidden).
- Cost / failure scenario: measured: 8 polls -> 8 full lane redraws in 5 s with nothing changing (1.6 Hz); hilite 0.19 ms over 500 rows, laneDraw 0.15 ms headless without peaks, ~1.2-1.4 ms with real peaks at 80 clips and 7-8 ms at CPU x4 (take five's table). Per open tab that is a full-canvas GPU raster + composite 1.6 times a second all day, on the machine whose Chrome shares an iGPU with Resolve; small per tick, but it is pure waste and it also keeps the GPU process from idling.
- Evidence: probe-out-500.json `idleDraws` {fullDrawsIn5s 8, pollsIn5s 8, REMOTE true}, `hiliteMs` 0.19.
- Ledger: new
- Suggested change: in hilite (or at the poll's `else` branch) skip when PH, PHUID and the list's version are unchanged since the last hilite, and keep a reference to the previous `.ph` element instead of sweeping all children. Optionally stretch the poll to a few seconds while `document.visibilityState==='hidden'` (15-offline.js already re-asks on visible). Must not break follow (laneFollowTick needs the call when FOLLOW is on and the card has drifted - keep that branch).
- Effort / risk: S effort; low risk

### cards-page-a-3 - The spoken-word highlight rewrites the playhead card's innerHTML on every poll
- Category: perf
- Severity: low
- Confidence: PLAUSIBLE
- Where: MulticamPipeline multicam_pipeline/cards/page/02-markers.js:824-855 (cardWordTick)
- What: each poll with a playhead clip and source time rebuilds the `.txt` (or `.en`) element's innerHTML with the current word wrapped, even when the word index is the same as last poll, and finds the card with `CARDS.find` (O(n)) each time.
- Cost / failure scenario: 1.6 times a second while Resolve's playhead is parked on a word: one text subtree replaced, its layout invalidated, its style recomputed, in a 500-card list. Estimated well under 1 ms a tick on a desktop; it is a re-layout nobody needs and it also defeats text selection inside that card.
- Evidence: read only; no `res` comparison against the last highlighted index before the innerHTML write (line 852).
- Ledger: new
- Suggested change: remember the last (uid, word index) and return early when unchanged; use `cardEl`'s element dataset or a uid->card map instead of `CARDS.find`.
- Effort / risk: S effort; low risk

### cards-page-a-4 - flip() interleaves layout reads with style writes over every card near the viewport
- Category: perf
- Severity: low
- Confidence: PLAUSIBLE
- Where: MulticamPipeline multicam_pipeline/cards/page/02-markers.js:662-673
- What: the loop reads `c.offsetTop` and `getBoundingClientRect()` for each card and, for a moved one, writes `style.transition` / `style.transform` before reading the next card, so each later read forces a style (and layout-validity) pass. A delete or a move near the top shifts every card below, so every card within three screens is written.
- Cost / failure scenario: per confirmed delete / move / insert: estimated 30-60 forced style passes (the number of cards in the 3-screen window), each small; at CPU x4 on a phone this is a few ms of the confirm's paint. The ripple-trim path that moves nothing pays nothing.
- Evidence: read only (my probe's one-card text change moved no card, so it did not exercise this).
- Ledger: related to the 2026-09-03 FLIP limit (FLIP_MS) - this is the remaining read/write interleave, not the old 373-card transition
- Suggested change: two passes - collect (card, dy, top) for all cards first, then write all transforms - same visual result.
- Effort / risk: S effort; low risk

## What is already good
- The card list's keyed patch works: one changed card on a 500-card state is 3 DOM mutations and 5.7 ms of render (probe), and `.card{content-visibility:auto}` keeps off-screen cards out of layout. Leave both alone.
- No listener growth: document 26 / window 56 / #list 24 / lane canvas 13 listeners before and after 30 version bumps, 10 lane toggles and 10 edit-view toggles; JS heap +0.3 MB over 200 version bumps after GC.
- The lane audio pool is bounded: 80 `laneEl` calls over 40 multicams (base + shadow) leave exactly 8 live HTMLAudioElement / MediaElementAudioSourceNode / DynamicsCompressorNode wrappers after GC (LAUD_KEEP), so dropped elements and their Web Audio nodes are collected.
- The waveform bitmap cache, outline path and arithmetic wrap (take five) and the rAF-coalesced `laneDraw()` are well bounded; the delta poll (`since`/`dp=1`) and the small "unchanged" answer keep the idle wire cost low.

## Coverage note
Not reached in the time box: 03-lane.js pointer/wheel/scrub handlers beyond the scrub/jump rules already in GOTCHAS 4b, 04-lane-keys.js, 05-keys.js (beyond selCard/cardEl), 06-trim.js vtext/vpatch (only as reported in LANE-ZOOM take one), 10-look.js, cards.html, most of cards.css (only the expensive-property greps; `#player` and the mobile lane bar carry `backdrop-filter: blur`, judged low because both are small and only shown on demand). No probe on a phone, an iGPU or with real peaks; the lane timings above are headless without peaks. Undo history / plan growth over an hour (QMOVES, QSTASH, VNOTES, WRAPC, the `wrapW` memo) were not measured.

## OUT OF TERRITORY
- multicam_pipeline/cards/handler.py:892: `/api/state` calls `engine.tick()` on every poll from every open page (1.6 Hz per tab on the NAS); worth a check by the server hunter that tick is cheap when nothing changed.
- The assembled page is 1.67 MB of inline HTML/CSS/JS per load (page.render_page); whether it is gzipped and cached is the server / sw.js hunter's question.
