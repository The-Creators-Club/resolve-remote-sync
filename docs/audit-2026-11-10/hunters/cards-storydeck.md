# cards-storydeck - Story Deck, the native app wrappers, deploy/ and root files of MulticamPipeline
Files read (approximate coverage): MulticamPipeline CLAUDE.md (all), GOTCHAS.md section 5 + headings, README headings; storydeck/agents.py (all), model.py (Deck save/log/replay), routes_play.py (dispatch, play_state, _mutate, page_proposals), handler.py (all), server.py (top), stages.py (header), workfolder.py (header), view.py (header); apps/android MainActivity.java (all), LocalServer.java (lines 1-500, 590-660, 760-870), apps/windows/src/main.js (lifecycle, webPrefs, onUpdate), proxy.js (update + agents), apps/publish.ps1, app.config.json, package.json; cards page 08-places.js poll loop, 01-state.js REMOTE; ccsync dashboard cards.py imports, cards_app.py, server/install_dashboard_app.py exclude lists, docs/CARDS_DEPLOY.md "What gets copied". git ls-files / cat-file size census of the subtree.
Probes run: (1) size census of the tracked subtree vs what the Cards deploy ships (git ls-files + the real CARDS_EXCLUDE_DIRS rule); (2) Story Deck save cost and board composition on the real Disaster Preparedness board (copied in memory, nothing written to the work folder); (3) board_view timing/size; (4) a capture runner fed to `Agents` on that board to count the calls and estimated tokens of the joins / splices / chunked-sequence fan-outs (no AI provider called); (5) git history blob census for docs/ui.

What is live: the dashboard's /cards mount imports only `multicam_pipeline.cards.handler` and `.project_agent` (+ `.models`); nothing under `storydeck/` is imported by it or by any cards module. Story Deck is a standalone loopback app (`storydeck_web.py`, 8823) used for real on 2026-09-29 and 2026-10-01 (Disaster Preparedness work folders) and edited in today's checkpoint commit - live as a local tool, not as part of /cards. The native apps are live: the dashboard serves their updates at /cards/app/ (cards_app.py), current 1.0.6. `deploy/` is the retired standalone NAS app (timeline-cards Custom App, GOTCHAS section 5); it is excluded from the Cards deploy and nothing in ccsync calls it.

## Findings

### cards-storydeck-1 - The Windows app installs an unsigned .exe from a vault folder any editor can write
- Category: security
- Severity: high
- Confidence: CONFIRMED (by reading both sides; not exercised)
- Where: MulticamPipeline apps/windows/src/proxy.js:452-472, apps/windows/src/main.js:158-161, apps/publish.ps1; ccsync dashboard/src/ccsync_dashboard/cards_app.py
- What: [ CHECK FOR UPDATE ] downloads the file `latest.json` names from `<vault>/Apps/Timeline Cards/` (served by cards_app.py) and runs it with `spawn(file, ['/S', '--force-run'])`. The only check is a sha256 that comes from the SAME latest.json, and it is optional (`if (mine.sha256 && ...)`; Android likewise skips an empty one). There is no Authenticode check and no signature over latest.json.
- Cost / failure scenario: anyone who can write that vault folder (every editing PC maps the vault as X:, and the dashboard container holds it rw) replaces the exe and latest.json; the next editor to press INSTALL silently runs that binary with their own rights. CC Sync's own upgrade channel was made signed on 2026-08-17 for exactly this reason; this is a second, unsigned channel beside it. Android is protected by the platform's same-signing-key rule, Windows is not.
- Evidence: proxy.js:466 `if (mine.sha256 && sha !== ...)`; main.js:160 spawns the downloaded file silently; publish.ps1 writes sha256 into the same latest.json beside the binary; cards_app.py serves any .exe/.apk latest.json names.
- Ledger: new
- Suggested change: sign latest.json with an offline key (reuse the shape of ccsync's release_key.py) and bake the public key into the app; refuse an entry with no sha256 or a bad signature. Must not break the Android path, which can keep relying on the APK signature as well.
- Effort / risk: M effort; low risk

### cards-storydeck-2 - Inside both native apps the page polls the NAS 4 times a second (and the Windows window keeps doing it when minimised)
- Category: idle
- Severity: medium
- Confidence: CONFIRMED (by reading; cadence not measured on a device)
- Where: MulticamPipeline multicam_pipeline/cards/page/01-state.js:436, 08-places.js:347; apps/windows/src/main.js:60-61
- What: `REMOTE` is decided by the page's hostname, and in both apps the page is served from `127.0.0.1:47823`, so `REMOTE=false` and the poll runs every 250 ms instead of 600 ms. Every one of those polls is relayed by the app's local server to the NAS over Tailscale - the exact case the comment says to avoid ("a phone's radio need not wake 4x a second"). The Electron window also sets `backgroundThrottling: false`, so Chromium does not slow the timers when the window is hidden or minimised.
- Cost / failure scenario: 14,400 state requests per hour per open app instead of 6,000 (2.4x), forever while it is open, including minimised on an editor's PC beside Resolve. On a phone it keeps the cellular radio awake. At 20 machines it is 80 requests/s of dashboard load from idle apps.
- Evidence: 01-state.js:436 regex treats 127.x as local; 08-places.js:347 `REMOTE?600:250`; main.js:61 `backgroundThrottling: false`.
- Ledger: new
- Suggested change: let the app's local server mark itself (it already sends `X-Cards-App-Local`, or inject a flag like the Android HOOK does) and treat that as REMOTE; drop `backgroundThrottling: false` unless audio playback needs it (if so, turn it on only while playing). Must not slow the 80 ms "edit in flight" poll.
- Effort / risk: S effort; low risk

### cards-storydeck-3 - The Android app opens a new TCP + TLS connection for every request; the Windows app re-uses them (the two have drifted)
- Category: perf
- Severity: medium
- Confidence: CONFIRMED (by reading)
- Where: MulticamPipeline apps/android/app/src/main/java/com/cablewrap/timelinecards/LocalServer.java:25-28, 596; apps/windows/src/proxy.js:286-292
- What: LocalServer.java sends `Connection: close` upstream and calls `open(t)` (DNS + connect + TLS handshake + hostname check) for every request. proxy.js, the Windows copy of the same server, uses a keep-alive `https.Agent` and says why: "a TLS handshake per poll is the alternative".
- Cost / failure scenario: with finding 2, 4 full TLS handshakes per second to the NAS through Tailscale on the phone: about 1-3 extra round trips per poll (estimated 100-300 ms on mobile), CPU and battery for the crypto, and a fresh socket per request on the NAS side. The 4 s connect budget also applies to each poll, so a slow network shows up as a slow edit confirm.
- Evidence: LocalServer.java header comment and line 596; proxy.js lines 287-291.
- Ledger: new
- Suggested change: a small pool of keep-alive upstream sockets in LocalServer (idle timeout under uvicorn's 5 s, as proxy.js does), keeping `Connection: close` towards the WebView so the raw relay stays simple. Or at minimum fix finding 2 first, which cuts the handshakes by 2.4x.
- Effort / risk: M effort; medium risk (the relay reads by framing; a re-used socket needs the response fully consumed)

### cards-storydeck-4 - Android keeps probing a down server every 5 s with the app in the background, and the page's timers are never paused
- Category: idle
- Severity: medium
- Confidence: PLAUSIBLE (mechanism read; how long Android lets the process run in the background was not measured)
- Where: MulticamPipeline apps/android/.../LocalServer.java:380-396 (recheck), MainActivity.java:237-241 (onPause/onResume)
- What: when the server is unreachable `setUp(false)` schedules `probe()` every 5 s on a process-level executor; nothing cancels it when the activity pauses. `onPause` calls `web.onPause()`, which by Android's own documentation does not pause JavaScript; `WebView.pauseTimers()` is never called, so the page's own pollers (finding 2) and offline probes keep running too.
- Cost / failure scenario: a phone off the tailnet (the normal state outside the studio, which is what offline mode is for) with the app in the background: 720 connect+TLS attempts per hour, each up to 4 s, until the OS freezes the process. Battery and radio cost with no one looking at the page.
- Evidence: LocalServer.java:390 `scheduleWithFixedDelay(... probe ..., recheckMs, recheckMs)`; MainActivity.java:241 `web.onPause()` only.
- Ledger: new
- Suggested change: in onPause call `web.pauseTimers()` and stop the recheck; in onResume `resumeTimers()` and one immediate probe. Must not pause audio that is meant to keep playing (check the lane's background-play expectation first).
- Effort / risk: S effort; low risk

### cards-storydeck-5 - Story Deck's fan-out stages resend a ~23k-token preamble on every call, uncached through the CLI door
- Category: perf
- Severity: medium
- Confidence: CONFIRMED for the call counts and sizes (probe); PLAUSIBLE for the cache miss
- Where: MulticamPipeline multicam_pipeline/storydeck/agents.py:607-613 (_fanout), 25-29 (docstring), 947-1000 (joins, splices); cards/library_engine.py:1918-1960
- What: every fan-out call is `preamble + "---INSTRUCTIONS---" + body` as ONE stdin text block to `claude -p`. Story Deck only runs standalone, so it always takes the CLI door; the marker is a breakpoint only for the dashboard's runner. A prompt cache matches at block boundaries, so the shared preamble inside one text block is not reused across calls, and the first 6 calls start at once anyway (MAX_WORKERS=6), before any cache could exist. The docstring says "the provider's prompt cache serves it". Also, `joins()` re-grades every join of every lane each time the stage is run, with no skip for joins already judged (splices do skip).
- Cost / failure scenario: on the real Disaster Preparedness board (666 cards, 52 lanes, 30 KB notes, 29 KB brief + sequence) the preamble is 68.5k chars, about 22.8k tokens (estimated). Joins = 19 calls, about 578k input tokens of which 434k (75%) is the identical preamble; splices for about 170 cards = 34 calls, 921k of which 777k is preamble; chunked sequence = 12 calls, 274k of 394k. With the preamble cached, each stage's input would drop by roughly 65-70%. Paid in subscription limits or API dollars every time a stage runs, and every re-run of joins pays it in full again.
- Evidence: probe4 (capture runner on a copy of the board): joins 19 calls / 577,746 est. tokens / 434,093 preamble; splices 34 / 921,005 / 776,798; sequence chunks 12 / 394,001 / 274,164. library_engine.py:1949 passes the prompt as `input=`.
- Ledger: new
- Suggested change: make the preamble a real conversation turn: one serial turn 0 writes the preamble into a session, and the fan-outs resume it with a forked session (check that `claude -p --resume <id> --fork-session` is supported by the pinned CLI) so the preamble is an earlier, cached message; or start one call, wait for it, then release the rest. Let joins skip lanes whose order has not changed since their last judged run. Must keep "two concurrent --resume of one conversation corrupt it" true: fork, never share.
- Effort / risk: M effort; medium risk

### cards-storydeck-6 - Story Deck keeps every proposal forever and rewrites the whole board on every event
- Category: disk-growth
- Severity: low
- Confidence: CONFIRMED (probe)
- Where: MulticamPipeline multicam_pipeline/storydeck/model.py:643-647, 673-676, 722-732; routes_play.py:82-88, 323-334, 366-374
- What: `Deck._log` appends the event AND rewrites `board.json` in full (indent=1) on every op, undo and redo; `board.proposals` is never pruned (taken, declined and superseded stay); and every move's answer carries `play_state()`, which includes up to 400 proposals plus every pending one.
- Cost / failure scenario: after three days of real use the board is 1.44 MB, of which proposals are 678 KB (1,204 proposals: 890 taken, 82 superseded, 33 declined, 199 pending). One save costs about 20 ms measured; each move response carries about 600 proposals (estimated 300 KB) over loopback. Grows linearly with every agent run; harmless today, slow over a season of episodes.
- Evidence: probe1 on a copy of storydeck-2026-09-29/board.json: save 19.7 ms, 1,437,787 bytes, proposals 677,938 bytes.
- Ledger: new
- Suggested change: move settled proposals (taken/declined/superseded older than the newest lock) into a side file, or out of `board.json` into the event log they already appear in; send the proposals in `play` only when they changed. Must keep everything the undo stack and the contest tray need.
- Effort / risk: S effort; low risk

### cards-storydeck-7 - The Cards deploy ships 3.7 MB of files the /cards mount never imports, and CARDS_DEPLOY.md misstates what ships
- Category: deploy
- Severity: low
- Confidence: CONFIRMED (census against the real exclude rule)
- Where: ccsync server/install_dashboard_app.py:285, 539-544; docs/CARDS_DEPLOY.md:145-151; MulticamPipeline work/, apps/, legacy/, multicam_pipeline/storydeck/
- What: the exclude set is matched against every path part, and it does not name `work`, `apps`, `legacy` or `storydeck`. So the snapshot ships 256 `work/` files (episode plans and scripts, 2.45 MB), the app sources (40 files, 0.43 MB, including the gradle jar and icons), the Story Deck package (0.86 MB, imported by nothing in the mount) and the root entry scripts. CARDS_DEPLOY.md says "`tests/` goes to the NAS ... Do not add `tests` to that list", but `tests` is already in BROLL_EXCLUDE_DIRS, so tests do NOT ship and the golden page is not on the NAS.
- Cost / failure scenario: 479 files / 8.6 MB per Cards deploy over paramiko SFTP, of which about 300 files / 3.7 MB are unused (estimated 40% of the upload's file count, which is what SFTP pays for). `work/` also carries episode plans to a server that does not need them. The doc error misleads anyone diffing a served page against the golden.
- Evidence: census output: multicam_pipeline 156 files 5.42 MB, work 256 / 2.45 MB, apps 40 / 0.43 MB, root 26 / 0.30 MB, legacy 1; tests 175 files 0 shipped.
- Ledger: new
- Suggested change: add `work`, `apps`, `legacy`, `storydeck` to CARDS_EXCLUDE_DIRS after confirming no cards module reads `paths.ROOT/work` at runtime on the NAS (CLAUDE.md says work/ is resolved through paths.ROOT - check those readers first); correct the CARDS_DEPLOY.md paragraph.
- Effort / risk: S effort; low risk (medium if a cards module does read work/)

### cards-storydeck-8 - Story Deck screenshots: 46 MB in the tree, 78 MB in history
- Category: streamline
- Severity: low
- Confidence: CONFIRMED
- Where: MulticamPipeline docs/ui/storydeck-*.png (38 files)
- What: full-page PNG screenshots of about 1.5 MB each, regenerated by tools/storydeck_*shots.js; every regeneration adds new blobs.
- Cost / failure scenario: 46.3 MB of the 52.8 MB docs/ui folder; 78 MB of the E:\Projects\Editing pack (480 MB) is docs/ui history. Every clone and backup carries it. Not deployed.
- Evidence: `git ls-files docs/ui | du` and a cat-file census of all blobs.
- Ledger: new
- Suggested change: save the shots as WebP/JPEG at 1x (a tenth of the size) and stop committing intermediate rounds; no history rewrite needed.
- Effort / risk: S effort; low risk

### cards-storydeck-9 - The Android release build always enables WebView remote debugging
- Category: security
- Severity: low
- Confidence: CONFIRMED (by reading)
- Where: MulticamPipeline apps/android/.../MainActivity.java:138
- What: `WebView.setWebContentsDebuggingEnabled(true)` is unconditional, so every editor's installed APK lets anything with adb access read the page, its storage and the dashboard session cookie through chrome://inspect.
- Cost / failure scenario: a phone with USB debugging on, plugged into any authorised computer, hands over a signed-in dashboard session. Needs physical/adb access, hence low.
- Evidence: line 138, comment "on Alex's own phone".
- Ledger: new
- Suggested change: gate it on `BuildConfig.DEBUG` (or a hidden setting on the /__app/ page).
- Effort / risk: S effort; low risk

## What is already good
- Story Deck's server is loopback only, checks Host and Origin and requires a JSON content type on POST; the event log plus snapshot replay handles a crash between log line and save.
- The whole-canvas deal/sequence turns run in one session and send the 240k-char corpus once per conversation (`_corpus_sent`), with a token budget deciding when to fall back to chunks - leave that.
- `board_view` is cheap (2.5 ms for a 666-card board) and moves answer with a slice, not the whole board.
- Android updates rely on the platform's same-signing-key rule and a .partial-then-rename for kept clips; the Windows proxy already uses keep-alive upstream and rotates its log at 2 MB.
- Root logs/state (`*.log`, cards_ui.json, req.json, cards_agent.json, en_index/, scratch/) are gitignored and are small and stale (largest 170 KB, last written August/September) - not growing.

## Coverage note
Not reached: storydeck ops.py, stages.py bodies, build.py, quests.py, routes_notes.py, the Story Deck page JS and lab/ (fx-lab.html); LocalServer.java 500-590 and 870-1153 (the page copy Store and its pruning); proxy.js forwarding body; e2e_offline.py, make_icons.py; deploy/install_nas.py vs ccsync's installer (deploy/ is retired from use, so duplication was not measured); the root scripts (pipeline.py, build_canvas.py and the shims) - I did not build the per-file "reachable from nothing" table, so no retire-to-legacy recommendation is made beyond noting deploy/ is unused by the current deploy recipe. Whether the projects folder on the phone/PC (kept clips) is ever pruned was not checked.

## OUT OF TERRITORY
- E:\Projects\Editing history: `Resolve/MulticamPipeline/editor/dist/main.js.map` has been committed at least 12 times at 1.7 MB each (39 MB of pack) on the editor branch; the map should not be tracked.
- multicam_pipeline/cards/library_engine.py:1907: `CLAUDE_EFFORT=low` is set for EVERY CLI call ("translation needs no deliberation"), including Story Deck's and chat-edit's reasoning turns that pass think=True - check whether that env var lowers their quality.
