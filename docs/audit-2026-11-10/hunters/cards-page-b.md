# cards-page-b - Timeline Cards page: offline layer (15-offline.js, sw.js, offline.py), windows, search, chat, shorten, pad, seqs, conform
Files read (approximate coverage): MulticamPipeline `multicam_pipeline/cards/page/15-offline.js` (~45%: header, IDB layer, verdict/seam, track, download, auto keep, media check, refresh/remove, snapshot, boot), `sw.js` (100%), `cards/offline.py` (100%), `17-windows.js` (100%), `19-pad.js` (loop, connect, tick ~25%), `14-search.js` (cache, history, wait timers ~25%), `18-shorten.js` (suggestion lookups, duck, paint ~20%), `16-chat.js` (grep), `20-seqs.js` / `07-conform.js` (their timers); ccsync `dashboard/src/ccsync_dashboard/cards_landing.py` (CARDS_SW); `page.py` render_sw; `docs/NATIVE-APPS.md` section 4c.
Probes run (scratch `...\scratchpad\cards-page-b\`): `autoon_probe.js` (vm-evaluates the two real `oflAutoOn` declarations plus `oflInApp`/`oflIsIOS` in one script, desktop Chrome UA on the dashboard origin); `queue_probe.js` (v8.serialize of the offline queue at 71/300/600 edits, the shape of the 2026-09-12 queue); `clone_probe.js` (structured clone of a 520-card state: 1.07 ms, too small to report).

## Findings

### cards-page-b-1 - Two `function oflAutoOn()` in one script: the app-only "keep what is open" runs in every desktop and Android browser
- Category: bug
- Severity: high
- Confidence: CONFIRMED
- Where: MulticamPipeline `multicam_pipeline/cards/page/15-offline.js:2741` (apps' keep) and `:3237` (snapshot autosave toggle); caller `:2746`
- What: The page is one classic `<script>` (golden page.html: one `<script>` at 3954, closing at 32311), so the second declaration of `oflAutoOn` (the CR-211 snapshot toggle: true on every non-iOS browser) replaces the first (`oflInApp() && cards_auto_keep !== 'off'`). `oflAutoKeep` therefore runs in every Chrome/Edge/Firefox/Android browser on the dashboard: 4 s after boot it probes, fetches the manifest, ticks EVERY referenced clip's audio (and, on a non-touch screen, every video proxy via `oflManifest`'s default) and calls `oflDownload({auto:true})`, then repeats every 10 minutes. Inside the app, the settings switch `cards_auto_keep = 'off'` is ignored.
- Cost / failure scenario: An editor opens a cut list in desktop Chrome, never asks for offline: the tab silently downloads the whole cut list's audio + 480p proxies into Cache Storage (hundreds of MB to several GB per episode, estimated: Opus ~29 MB/h, WAV ~345 MB/h mono, proxies ~0.5 GB/h), creates an offline copy nobody asked for (so the seam, `oflTimed`, verdict flips and tracking - the CR-194/CR-206 machinery - become live on that desktop), calls `navigator.storage.persist()` (Firefox shows a permission prompt), and every 10 min re-pulls state + words + every vault transcript (estimated 3-5 MB per tab per cycle). Each new cut list opened adds a copy that is never removed (see -4). Disk fill on a laptop over weeks; NAS egress per open tab.
- Evidence: `autoon_probe.js`: desktop browser on the dashboard `oflInApp()=false`, `oflAutoOn()=true`; in the app with `cards_auto_keep=off`, `oflAutoOn()=true` (expected false). Both declarations are in `tests/golden/page.html:24735` and `:25231`. Keep landed 2026-10-22..28 (8fdc887), after the snapshot toggle (2026-09-06), so it has shipped broken since.
- Ledger: new
- Suggested change: rename the keep's predicate (`oflKeepOn`) and its caller; add a unit assertion that the page has no duplicate top-level function names (a regex over the assembled page in `test_page_golden.py`). Must not change the snapshot toggle's behaviour.
- Effort / risk: S effort; low risk

### cards-page-b-2 - The automatic keep re-downloads every video proxy every ten minutes
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: MulticamPipeline `multicam_pipeline/cards/page/15-offline.js:2693`
- What: In `oflDownload`, peaks and audio are skipped when `held(...)` (same identity already in hand, auto mode); the video line has no `held` check, and `oflStore` fetches with `cache:'reload'` + `X-Cards-Fresh`, bypassing both the HTTP cache and the worker.
- Cost / failure scenario: Every 10 min, per open page with a copy and proxies picked (default on any non-touch screen; in every desktop browser because of -1; in the Windows app always), every proxy is re-fetched whole from the NAS and re-put into Cache Storage (and, in the app, re-written to `Documents\Timeline Cards\...\Video`). A montage of 24 clips at ~20 MB each = ~480 MB per 10 min = ~2.9 GB/hour per tab (estimated).
- Evidence: read: `if(c.video&&OFLPICKV[c.mp])jobs.push(...)` vs `if(c.audio&&OFLPICK[c.mp]&&!held('audio',c,c.audio))`.
- Ledger: new
- Suggested change: add `&&!held('video',c,c.video)` (OFLMEDIX already records `video/<mp>` identities in `oflStore`).
- Effort / risk: S effort; low risk

### cards-page-b-3 - Updating one episode's worker deletes every other episode's offline shell
- Category: bug
- Severity: medium
- Confidence: CONFIRMED
- Where: MulticamPipeline `multicam_pipeline/cards/page/sw.js:37,75-80`; `multicam_pipeline/cards/page.py:166-172`
- What: Each episode registers its own worker (scope `/cards/p/<slug>/`) but the shell cache name is `cards-shell-<VER>` with VER = the page code hash, identical for every episode, so all episodes' shells share one cache. On a deploy, the first episode opened online installs the new worker, whose `activate` deletes every `cards-shell-*` but its own - including the old-VER cache holding every other episode's shell. Those episodes' (still old) workers then find nothing in `cachedShell()`, and the dashboard's `CARDS_SW.savedEpisodes()` stops listing them.
- Cost / failure scenario: Every Cards deploy (several a week historically). Phone holds offline copies of episodes A and B; after a deploy the editor opens A once online, boards a plane, launches B: no shell, navigation fails, and the landing's "Episodes this phone can open offline" omits B. This is exactly the 2026-10-11 ask ("you should be able to launch any project file which has been downloaded"). The queue survives in IndexedDB, so no data loss.
- Evidence: read; `render_sw` substitutes `page_version()` with no scope; activate filter is `n.indexOf('cards-shell-')===0 && n!==SHELL`.
- Ledger: related to the 2026-10-11 offline front door (cards_landing.py CARDS_SW)
- Suggested change: name the cache per scope (`'cards-shell-' + VER + '-' + <hash of registration.scope>`) and on activate delete only caches with this scope's suffix; keep the `cards-shell-` prefix so `savedEpisodes()` still finds them.
- Effort / risk: S effort; low risk

### cards-page-b-4 - Downloaded media is never evicted: [ REMOVE ] orphans it while any other copy exists, and old copies pile up
- Category: disk-growth
- Severity: medium
- Confidence: CONFIRMED
- Where: MulticamPipeline `multicam_pipeline/cards/page/15-offline.js:3023-3047`, `:2838-2884`
- What: IndexedDB `cards-offline` and Cache `cards-media` are per ORIGIN, shared by every episode under `/cards/p/*`. `oflRemove` deletes a copy's IDB rows but deletes media only when `OFLIX` becomes empty ("the media goes when the last copy does"), so removing episode A while episode B has a copy leaves all of A's audio and proxies in the cache with nothing pointing at them. `oflMediaCheck` only walks the current copy's `OFLMEDIX`, so a clip cut out of the list also stays. Copies themselves are never aged out (state ~600 KB + words + every vault transcript each).
- Cost / failure scenario: one episode's media is hundreds of MB to GBs (estimated above); each removal-with-others-present strands all of it, invisibly (the panel's sizes come from the index row, so the "used" figure the editor sees does not show it except via `storage.estimate`). With -1, every cut list opened in a desktop browser becomes such a copy.
- Evidence: read; comment at 3037 states the rule; media keys are `scope + offline-media/<kind>/<mp>`.
- Ledger: new
- Suggested change: on remove, delete the media keys this copy's `media` row names unless another copy's `media` row names the same key (reference count over the index's rows), and in `oflMediaCheck` drop cached keys under this scope that no copy references. Must keep "two cut lists of one episode share one copy of the audio".
- Effort / risk: M effort; low risk

### cards-page-b-5 - A quota failure while queuing an offline edit is swallowed and the edit is reported as made
- Category: resilience
- Severity: medium
- Confidence: CONFIRMED
- Where: MulticamPipeline `multicam_pipeline/cards/page/15-offline.js:396-420`, `:2092`
- What: `oflSaveQueue` ends in `.catch(()=>null)`, `oflSaveState` likewise, and `oflQueueEdit` chains `.catch(()=>null)` before answering `{ok:true}` with the applied state. A `QuotaExceededError` (or any IDB failure) leaves the edit only in memory; nothing tells the editor, and the badge counts it.
- Cost / failure scenario: phone near its quota (the download refuses only when the pick exceeds free space, so a copy can leave very little headroom; media written by -1/-2 consumes it) -> offline edits all "work" -> tab reload or OS killing the PWA loses every one of them. The CR-211 rescue file is the only belt, and it is off by default on iOS.
- Evidence: read.
- Ledger: new
- Suggested change: let `oflSaveQueue` reject, and in `oflQueueEdit` on rejection take the edit back off `OFLQ`/`OFLSTATE` and answer `{ok:false,error:'this device is out of room: ...'}`; also say it in the panel.
- Effort / risk: S effort; low risk

### cards-page-b-6 - Search answer cache in localStorage is per episode root and never pruned across roots, on the dashboard's shared origin
- Category: disk-growth
- Severity: medium
- Confidence: PLAUSIBLE
- Where: MulticamPipeline `multicam_pipeline/cards/page/14-search.js:150-183`
- What: `cards_tsans:<ROOT>` keeps up to 24 answers of up to 160,000 chars each (3.84 M chars, ~7.7 MB of UTF-16) per root, and the root set only grows. localStorage is ~5 M chars per origin, and the origin is the whole CC Sync dashboard. The retry on a quota error only trims this root's own rows; every other writer (`cards_windows` registry every 2 s, `cards_force_offline`, `cards_session_expires`, `cards_offline_last`, the dashboard's own keys) fails silently once the origin is full. Each save also parses and re-stringifies the whole row set synchronously.
- Cost / failure scenario: two or three episodes with a few dozen large searches each -> origin full -> pop-out claims (17-windows.js) stop working, the offline-by-choice switch does not persist, the sign-in expiry warning loses its value.
- Evidence: read; answer sizes not measured (no live server), so the time to full is estimated.
- Ledger: new
- Suggested change: one global LRU across roots (cap total chars, e.g. 1 M), or move the answers to the existing IndexedDB store.
- Effort / risk: S effort; low risk

### cards-page-b-7 - Every offline edit rewrites the whole queue and the whole state
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: MulticamPipeline `multicam_pipeline/cards/page/15-offline.js:396-420`, `:2092`; the replay calls `oflSaveQueue` per landed edit (`:2365`, `:2399`)
- What: the queue (reorders carry the whole uid list twice) is written whole per edit, and the ~600 KB state beside it, so a day offline is O(n^2) bytes into IndexedDB.
- Cost / failure scenario: measured serialisation of the queue: 407 KB at 71 edits, 1.77 MB at 300, 3.5 MB at 600; cumulative bytes written by the queue alone 258 MB (300 edits) / 1.04 GB (600 edits), plus 600 KB of state per edit (180-360 MB). Serialise CPU is small (1 s total at 600); the cost is phone flash writes and IDB commit latency per edit.
- Evidence: `queue_probe.js` (v8.serialize, the IDB serializer).
- Ledger: related to CR-211 / CR-274 (snapshot packing solved the same lists for the file, not for IDB)
- Suggested change: store one row per edit (`q:<id>`) plus an order row, or reuse `oflSnapPack`'s list table in the stored form; write the state on the existing 2 s trailing timer rather than per edit.
- Effort / risk: M effort; medium risk (the replay's idempotency rests on the queue row)

### cards-page-b-8 - In the apps every kept clip is stored twice on the device
- Category: streamline
- Severity: low
- Confidence: CONFIRMED
- Where: MulticamPipeline `multicam_pipeline/cards/page/15-offline.js:2783-2815`; `docs/NATIVE-APPS.md` 4c ("a kept clip is on disk twice")
- What: in the Windows/Android app the local server already writes the clip to the projects folder and answers it "before the network and whatever the verdict", yet `oflStore` also puts the full blob in Cache Storage (after materialising it with `answer.blob()`).
- Cost / failure scenario: doubles on-device media (hundreds of MB to GBs per episode, estimated); on Android that is the scarce resource.
- Evidence: doc says so; code read.
- Ledger: new (documented trade-off, cheaper way to keep the same guarantee)
- Suggested change: when `oflInApp()` and the keep header was sent, record identity in `OFLMEDIX` without `cache.put`, and have `oflMediaCheck` ask the local server whether it holds the file instead of `cache.match`. Elsewhere, `cache.put(key, new Response(answer.body, {headers}))` streams instead of holding the whole file as a Blob.
- Effort / risk: M effort; medium risk

### cards-page-b-9 - The shortening duck stacks `timeupdate` listeners and cuts the next duck short
- Category: bug
- Severity: low
- Confidence: CONFIRMED
- Where: MulticamPipeline `multicam_pipeline/cards/page/18-shorten.js:2111-2134`
- What: each `shDuck` adds a `timeupdate` listener on the one shared `SHDUCK` element, removed only when `currentTime >= stop`. A second seam crossed before the first duck ends (different `in_s`, often a different clip) leaves the first listener live; if the new start is at or past the old `stop`, the old listener pauses the new duck on its first `timeupdate`. A duck that never reaches its stop (paused by `winApplyPlaying`, a failed play) leaves its listener for ever.
- Cost / failure scenario: scrubbing across two seams within half a second: the second removed block is barely heard. Listener count grows by one per interrupted duck for the page's life.
- Evidence: read.
- Ledger: new
- Suggested change: keep the tick in a module variable and remove the previous one before adding a new one.
- Effort / risk: S effort; low risk

## What is already good
- The gamepad loop (19-pad.js) starts on `gamepadconnected` and cancels its rAF on disconnect; with no pad nothing polls, and rAF does not run in a hidden tab.
- Snapshot cadence (CR-211/CR-274): now one silent overwrite a minute at most on the File System Access road, one download every ten minutes on the anchor road, 5 s trailing debounce, packed lists; object URLs revoked after 30 s. Leave it.
- `offline.py` manifest: words serialised once per version (CR-351), audio/video lookups never start an extraction; `replay_plan` is pure.
- sw.js deletes old shell caches on activate (the per-scope problem in -3 aside), serves cached media cache-first with Range from one blob per clip+identity, and the search/chat/seqs/conform timers (`tsWaitTimers`, `CHATTICK`, `SEQPLAY`, menu poll) all stop on their own.
- 17-windows.js state broadcast costs ~1 ms per state (measured structured clone of a 520-card state); the heartbeat is a 2 s localStorage read/write. Not worth changing.

## Coverage note
Not reached: 15-offline.js `oflApply`/`oflRipple`/`oflSync` bodies (lines ~1290-2560) beyond the call sites, the panel painting, and the restore path; 12-cats.js, 11-montage.js, 13-paste.js, 21-clip.js; the "shadow element + 4 ms ramp" splice audio path (it lives in 03-lane.js, cards-page-a's territory); AudioContext count (none in my slices). No headless-browser probe of the page was run (time); findings -1..-5 rest on reading plus the vm probe.

## OUT OF TERRITORY
- ccsync `dashboard/src/ccsync_dashboard/cards_landing.py` CARDS_SW `savedEpisodes()`: lists episodes from `cards-shell-*` caches, so it inherits -3 (no change needed there if -3 keeps the prefix).
