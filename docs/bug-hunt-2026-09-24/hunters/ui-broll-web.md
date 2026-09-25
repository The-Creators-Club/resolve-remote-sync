# ui-broll-web - b-roll web static UI: search SPA, ingest drawer, client-folder panel, public share page
Files read (approximate coverage): broll/web/static/share.html, share.js, share.css, share_gone.html, sprite.js, clientfolders.js (100%); index.html (100%); style.css (100%); app.js (~55%: init, fetchJson, history, header wiring, search/grid/empty state, buildCard, detail open/close, onKeydown, sendToResolve, settings panel); ingest.js (~30%: init, open/close, live panel, controls, batch list, state words). broll/web/app/routes_share.py (the folder/video payloads). dashboard/templates/partials/topbar.html (what gets injected into the header).
Tests/probes run: rendered the real static files in headless Chrome 153 from a scratch stub server (scratchpad/uiw/srv*.py: serves share.html / index.html plus a fake `api/folder` and `api/videos/N`), inside a 390 px iframe, measuring `scrollWidth` and every element whose right edge passes the viewport, plus screenshots. Measured `#app-header` height at 1920/1366 px windows. Counted media requests from the share grid (the sprite sheets are NOT fetched eagerly - a suspicion dropped). No repo file other than this report was written.

## Findings

### ui-broll-web-1 - Share page detail view overflows a phone horizontally when a clip has a long camera filename
- Severity: medium
- Confidence: CONFIRMED
- Where: broll/web/static/share.css:62-64 (`.share-layout { grid-template-columns: 1fr; }`), broll/web/static/share.js:283 (the filename rendered into `.video-meta .title`)
- What: under 860 px the detail layout collapses to one `1fr` column, and `1fr` is `minmax(auto, 1fr)`, so the column cannot get narrower than its min-content. The clip title is the raw filename with no `overflow-wrap`/`word-break`, and a camera name such as `DJI_20260503_142233_0042_D_aerial_over_the_harbour_at_dusk.MP4` has no break opportunity. The whole grid, player included, grows to fit it.
- Failure scenario: a client opens a folder link on a 390 px phone and taps a DJI clip. The page scrolls sideways (docW 463 px), the video player runs off the right edge (controls cut off), and the "clip could not be played" box and segment list are clipped too. A clip with a short name (`A004C012_260503_R1XK.mov`) lays out fine, so it depends on the clip.
- Evidence: headless Chrome in a 390 px iframe, `#v=1`: `docW=463`, overflowing elements `player-col, share-player, segments-col, share-meta, title, segment-item` all ending at 463. Same page with `#v=2` (short name): no overflow. Screenshot scratchpad/uiw/share_det.png shows the horizontal scrollbar and the clipped player.
- Ledger: new
- Suggested fix: `grid-template-columns: minmax(0, 1fr)` in the 860 px media rule, and `overflow-wrap: anywhere` on `.video-meta .title` (and `.share-caption-name`).

### ui-broll-web-2 - Share page: the brand line overflows a phone when the site's org name is long
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/static/share.html:27, share.js:174, style.css:168-171 (`.topbar > * { white-space: nowrap; flex: 0 0 auto }`)
- What: the header brand is the mark image plus `ORG // PREVIEW` in 14 px letter-spaced type, and the inherited `.topbar > *` rule makes it unbreakable and unshrinkable. `org` is site data (`config.get_org_name()`), and its length is not bounded.
- Failure scenario: a site whose `org_name` is "The Creators Club Documentary Studio" (36 chars). On a 390 px phone the brand is 505 px wide, so the whole public page scrolls sideways on every view, grid and detail alike.
- Evidence: 390 px iframe, grid view: `docW=505`, overflowing `brand:505, share-org:403`. The same page with org "Creators Club": `docW=380`, no overflow.
- Ledger: new
- Suggested fix: let `.share-header .brand` wrap (`white-space: normal; min-width: 0; flex: 1 1 auto`) or ellipsize `#share-org` with `max-width`.

### ui-broll-web-3 - Detail-view hotkeys hijack Enter/Space on every focused button, including buttons in drawers open over the detail view
- Severity: medium
- Confidence: CONFIRMED (Enter), PLAUSIBLE (Space on a button)
- Where: broll/web/static/app.js:1528-1586 (`onKeydown`), registered on `document` at app.js:962
- What: while a clip detail is open, `onKeydown` exempts only INPUT/SELECT/TEXTAREA targets. It does not exempt BUTTON/A, and it does not check whether the client-folder panel, the ingest drawer or the settings panel is open over the page. So Enter calls `preventDefault()` (which cancels the focused button's activation) and then `sendToResolve(...)`. Space/K toggles playback instead of pressing the button.
- Failure scenario: an editor has I/O set on a clip, opens the client-folder panel from the header, and Tab-es to "Save details" or "Copy" and presses Enter. The button does not activate and the clip is appended to the Resolve timeline instead. Without I/O set, they get a red "Set both an in point..." toast. With the detail open, no drawer button (close, Run, Revoke link, New link, recheck) can be operated from the keyboard.
- Evidence: code read. The only guard is `tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA"`. The Enter branch calls `e.preventDefault(); sendToResolve(...)` unconditionally. The ingest.js:221-225 comment says the shortcuts "cannot collide", but that only covers the Escape key.
- Ledger: new
- Suggested fix: return early when `e.target.closest("button, a, [role=menu], #ingest-panel, #cf-panel, #settings-panel")` matches, or when any drawer is open.

### ui-broll-web-4 - Folder rail parks under the sticky header: `--header-h` is a constant 88 px, but the real header is 98-230 px
- Severity: medium
- Confidence: CONFIRMED
- Where: broll/web/static/style.css:42 (`--header-h: 88px`), style.css:1012-1026 (`.folder-tree { position: sticky; top: var(--header-h); max-height: calc(100vh - var(--header-h)) }`)
- What: nothing ever measures the header and updates `--header-h` (grep: no writer in app.js/ingest.js/clientfolders.js). The header is the injected dashboard topbar, the rule and the wrapping `.header-controls` row. It is taller than 88 px at every width measured, and `#app-header` (z-index 10) paints over the rail.
- Failure scenario: an editor on a 1366 px laptop scrolls the results. The rail sticks 44 px too high, so its "BROWSE / clear" head and the first folder row sit hidden under the header, and "clear" cannot be reached until they scroll back to the top. At 1920 the overlap is 10 px. With the real topbar (chips, session) or more header wrapping, it gets worse.
- Evidence: headless Chrome with the real index.html/style.css (fallback topbar, flag toggles built by app.js): `#app-header` height 98 px at a 1920 window, 132 px at 1366, 233 px at 500.
- Ledger: new
- Suggested fix: set `--header-h` from `#app-header.offsetHeight` through a ResizeObserver, or make the header non-sticky and the rail `top: 0` inside a scrolling grid column.

### ui-broll-web-5 - "Add to folder" from the popover's "+ new folder" shows success even when the add fails
- Severity: medium
- Confidence: CONFIRMED
- Where: broll/web/static/clientfolders.js:205-224 (`cfCreateFlow`), 588-600 (the popover's `+ new folder...` handler)
- What: `cfCreateFlow` toasts `Created "X"` and then returns `afterCreate(folder)` with no try/catch. The afterCreate callback's `POST .../items` can reject, and the click handler awaits it with no catch either, so the rejection is unhandled. The popover is never re-rendered, so the new folder does not appear in it.
- Failure scenario: an editor makes a new folder from a card's "+". The item POST fails (for example a 409 or 5xx from the add route, or the session expired between the prompt and the call). They see a green "Created" toast and nothing else. The folder exists but is empty, the popover still lists the old folders without the new one, and there is no error. The client link they then send shows "This folder is empty."
- Evidence: code read. There is no catch between `afterCreate(folder)` and the `newBtn` click listener, and `cfRenderPopover()` runs only on the success path inside the callback.
- Ledger: new
- Suggested fix: wrap the callback in try/catch with `toast("Folder created but the clip was not added: ...", "error")`, and re-render the popover in `finally`.

### ui-broll-web-6 - A send to Resolve keeps running across clip changes: the next clip shows the old clip's "SYNCING n%" and locked buttons
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/static/app.js:1666-1818 (`sendToResolve`), app.js:1120-1175 (`openDetail`), 1183-1199 (`closeDetail`)
- What: the send loop polls every 1.5 s for up to 15 minutes. It writes `SYNCING n%` / `WAITING...` into the shared `#send-resolve-btn`/`#place-resolve-btn` and holds both disabled. Neither `closeDetail` nor `openDetail` cancels the loop or resets those buttons.
- Failure scenario: an editor presses Append on clip A (not on this computer yet, so it syncs), goes back and opens clip B. Clip B's transport reads "SYNCING 40%" with both buttons greyed out, so it looks as if B is syncing and B cannot be sent. Minutes later a "Sent to Resolve" toast arrives while B is on screen, and it was clip A that went into the timeline.
- Evidence: code read. `btn`/`otherBtn` are captured once, and only the loop's `finally` restores them.
- Ledger: new
- Suggested fix: name the clip in the label or toast ("Syncing <name>..."), and reset the button labels/disabled state in `openDetail` for a clip that is not the one in flight (keep the loop, change what is shown).

### ui-broll-web-7 - Share page tells a phone user to "Hover a thumbnail to scrub", and scrubbing is mouse-only
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/static/share.html:36 and 63-65 (keyhelp: space / arrows / Esc), sprite.js:101-107 (`wireSpriteScrub`: `mousemove` only)
- What: the share page is written for an outside client "viewed on a phone", but its only instructions are hover and keyboard ones. The scrub listens for `mousemove` alone (no pointer/touch handling). On a phone, a tap opens the clip at once, so hover-scrub cannot happen at all, and the keyboard hint under the player refers to keys a phone does not have.
- Failure scenario: a client on a phone reads "Hover a thumbnail to scrub through the clip", has nothing to hover with, and gets a player whose help line is about a keyboard.
- Evidence: code read, plus the 390 px render (scratchpad/uiw/share_grid.png).
- Ledger: new
- Suggested fix: word the intro for both inputs ("Tap a clip to play it; on a computer, hover to scrub"), hide `.keyhelp` under `@media (hover: none)`, and optionally scrub on `pointermove` with `pointerType === "touch"`.

### ui-broll-web-8 - Share page grid captions clip long filenames mid-word and cut a third line in half
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/static/share.css:37-45 (`.share-caption { max-height: 3.9em; overflow: hidden }`, no `overflow-wrap`)
- What: the caption is a 240 px box. An unbroken filename overflows it sideways and is cut by the card's `overflow: hidden`. `max-height: 3.9em` with `line-height: 1.4` is 2.79 lines, so a longer note shows the top part of a sliced third line.
- Failure scenario: the client sees `DJI_20260503_142233_0042_D_aerial_ove` with the rest missing, and the caption's third line is visibly cut through the letters. The card's `title` tooltip holds the full text, but a phone never shows it.
- Evidence: screenshot scratchpad/uiw/share_grid.png (first card). The measurement put `share-caption-name` at right=420 in a 390 px viewport.
- Ledger: new
- Suggested fix: `overflow-wrap: anywhere` on the caption, and `max-height: 4.2em` (3 x 1.4) or `-webkit-line-clamp: 3`.

### ui-broll-web-9 - Share page prev/next look enabled at the first/last clip (no disabled style for `.text-btn`)
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/static/share.js:273-274, style.css:503-512 (`.text-btn` has no `:disabled` rule; the only one is scoped to `.cf-item-ctl`, style.css:1689)
- What: `#share-prev`/`#share-next` are disabled at the ends, but they keep the same bright red and the same hover glow, so they look pressable and do nothing.
- Failure scenario: on clip 1 of 3 the client taps "prev" and nothing happens, with nothing on screen to say why.
- Evidence: screenshot scratchpad/uiw/share_det.png at "1 / 3": "prev" is drawn exactly like "next".
- Ledger: new
- Suggested fix: a global `.text-btn:disabled { color: var(--muted); cursor: default; text-shadow: none; }`.

### ui-broll-web-10 - Share page: a transient server error is headed "This link is not available"
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/static/share.js:160-167
- What: every failure of `api/folder`, including a 502 from the Funnel or a network blip, sets the H1 to "This link is not available". Only the sentence under it changes ("Could not load the folder (HTTP 502). Please try again in a moment."), and it includes a raw `HTTP 502` / `Failed to fetch`. The intro "Hover a thumbnail..." stays on screen above an empty page.
- Failure scenario: the NAS container restarts while a prospective licensee opens the link. They read a headline saying the link is dead and do not retry, although the link is fine.
- Evidence: code read. The title assignment is outside the `e.status === 404` branch.
- Ledger: new
- Suggested fix: use "This link is not available" only for a 404. Otherwise use "The preview could not load just now" with a Retry button, and drop the raw status text.

### ui-broll-web-11 - Client-folder popover and panel: stale counts, off-screen placement, invisible "+" for keyboard and touch
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/static/clientfolders.js:556-586 (checkbox change updates `folder.n_items` but not the rendered count span), 607-615 (`cfPlacePopover`: `top = anchor.bottom + 4`, no vertical clamp; `.cf-popover` has no max-height, style.css:1692-1705), style.css:1562-1576 (`.cf-card-add { opacity: 0 }`, shown only on `.card:hover`)
- What: (a) ticking or unticking a folder leaves its clip count in the popover at the old number. (b) The popover is `position: fixed` under its anchor with no clamp and no scrolling. A card near the bottom of the window, or the detail view's "+ client folder" button under a 62vh player, pushes the folder list below the fold, where scrolling cannot reach it because it is fixed. (c) The card's "+" stays at opacity 0 when it has keyboard focus (opacity hides the focus ring too), and on touch it is an invisible target.
- Failure scenario: an editor with 10 folders presses "+ client folder" under the player on a 900 px-tall screen, and the bottom folders and "manage folders" are off-screen and unreachable. Ticking a folder shows "3" beside it when it now holds 4.
- Evidence: code and CSS read.
- Ledger: new
- Suggested fix: re-render the row count after a toggle. Flip the popover above the anchor when `r.bottom + height > innerHeight`, and add `max-height: 60vh; overflow-y: auto`. Add `.cf-card-add:focus-visible { opacity: 1 }` and `@media (hover: none) { .cf-card-add { opacity: 1 } }`.

### ui-broll-web-12 - Caption edits appear reverted when the editor reorders straight after typing, and saving a caption gives no feedback
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/static/clientfolders.js:410-423 (caption `change` handler sets `item.note` only after the PUT resolves), 450-455 (`cfMove` swaps and re-renders synchronously)
- What: clicking ▲/▼ blurs the caption field, which fires `change` and starts the PUT, and then the click re-renders every row from `cf.current.items` straight away, before `item.note` is updated. The redrawn field shows the OLD caption, although the server stores the new one. A successful save shows nothing (no toast, no tick). Only a failure is reported.
- Failure scenario: an editor types "Harbour at dusk" into clip 2's caption and immediately moves clip 3 up. Clip 2's field goes back to empty, so they retype it or conclude captions do not save. The client page does show the new caption.
- Evidence: code read. The ordering is the standard blur (on mousedown), then change, then click.
- Ledger: new
- Suggested fix: set `item.note = note.value` before awaiting the PUT (revert it on failure), and flash a small "saved" beside the field.

### ui-broll-web-13 - Two hamburgers and two gears in the b-roll header, meaning different things
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/static/index.html:68-69 (`#cf-btn` is U+2630 ☰, `#settings-btn` is ⚙), dashboard/templates/partials/topbar.html:27-29 (injected three-bar `menu-btn`) and :223 (`gear-link` to /admin/settings)
- What: once app.js injects the dashboard topbar, the page carries the dashboard's three-bar menu (the nav drawer) and its gear (dashboard Settings). The b-roll control row below then adds another ☰, which opens *client folders*, and another ⚙, which opens b-roll's own read-only share/tray panel. The universal "menu" icon is used for a feature that is not a menu.
- Failure scenario: an editor looking for client folders has no reason to press a hamburger. An admin who presses the lower ⚙ expecting Settings gets a panel about `~/.broll-companion.json`.
- Evidence: code read of both templates.
- Ledger: new
- Suggested fix: give client folders a labelled button (`[ CLIENT FOLDERS ]`, the house bracket idiom) and label the b-roll settings "tray / shares" instead of a gear.

### ui-broll-web-14 - The ingest "Running" list prints raw state tokens (`proxies_live`), which the batch list translates
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/static/ingest.js:1453 (`item.state.padEnd(10, " ")`), compared with ingest.js:1669 (`ingestItemStateText(item.state)`)
- What: wire-1 (2026-09-18b) added `ingestItemStateText` so that `proxies_live` reads "original still owed", and the expanded batch card uses it. The live panel for the batch that is running on this computer still prints `item.state` raw. The same clip therefore reads "proxies_live" in one box and "original still owed" in the other.
- Failure scenario: an editor watching their own ingest sees `proxies_live  Taipei/A001.mov`, which is exactly the token the fix was meant to hide.
- Evidence: code read, both call sites.
- Ledger: related to wire-1 (docs/bug-hunt-2026-09-18b), missed call site
- Suggested fix: use `ingestItemStateText(item.state)` at line 1453.

### ui-broll-web-15 - Ingest live controls: Pause, Resume and Start now are all offered at once, whatever the state
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/static/index.html:253-257, ingest.js:1463-1468 (buttons are disabled only when the batch is over; never hidden or toggled by state), ingest.js:1470-1477 (`toast("CC Sync tray: <raw state>.")`)
- What: the running batch shows "Pause" and "Resume" side by side, both enabled, plus "Start now" while it is already indexing. The only confirmation is a toast carrying the companion's raw state token (for example "CC Sync tray: running."). "Pause uploads" does toggle its own label, so the two pause controls behave inconsistently.
- Failure scenario: an editor cannot tell from the buttons whether indexing is paused, presses Resume on a running batch, and gets "CC Sync tray: running." with no change on screen.
- Evidence: code read.
- Ledger: new
- Suggested fix: show one Pause/Resume toggle driven by `lb.gate === "paused"` (as Pause uploads already does), hide "Start now" unless the gate is `user-active`, and put the toast through `ingGateLabel`.

### ui-broll-web-16 - Mode fallback toast says "Searching by keyword instead" while it switches to Hybrid
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/static/app.js:709-719 (`applyModeAvailability`)
- What: when the chosen mode cannot run, the code sets `state.mode = "hybrid"` and highlights the Hybrid button, but the toast tells the editor it is "Searching by keyword instead."
- Failure scenario: semantic search is unavailable (model not loaded). The editor reads "keyword", sees "Hybrid" highlighted, and cannot tell which mode the results came from.
- Evidence: code read.
- Ledger: new
- Suggested fix: "... Searching in Hybrid mode instead." (or switch to keyword if that is what is meant).

### ui-broll-web-17 - Long error toasts disappear after 5 s, including the one that tells the editor which URL to open
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/static/app.js:154-159 (`toast`: fixed 5000 ms, no dismiss, not selectable in time), app.js:1735-1742 (the ~330-char "Couldn't reach the CC Sync tray ... open http://127.0.0.1:8899/status ..." toast)
- What: every toast lives exactly 5 s, whatever its length or kind. The tray-unreachable error is a paragraph that includes a self-test URL to type, and it cannot be read or copied before it goes. The toast container is 50vw wide, so on a laptop it runs to 8-10 lines.
- Failure scenario: Append to Timeline fails because Chrome blocked the local network. The editor sees a red block of text for 5 s and loses the only instruction for telling "tray down" apart from "browser blocked".
- Evidence: code read.
- Ledger: new
- Suggested fix: keep `error` toasts on screen until dismissed (or scale the duration with length), or route this one into the persistent settings-panel status line.

### ui-broll-web-18 - The b-roll SPA has no narrow layout: at 390 px the page is 718 px wide and the grid has no room for a card
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/static/style.css (no `@media` rule at all; `.flag-toggles { white-space: nowrap }` at 468-476, `.folder-tree { flex: 0 0 210px }` at 1013, `.results-grid` columns fixed at 240 px at 542-546, `.detail-layout` second column `minmax(260px, 1fr)` at 705)
- What: the header's flag row is unbreakable (718 px), the rail keeps 210 px of a 390 px screen, and that leaves about 170 px for 240 px cards. The pager labels wrap onto two lines.
- Failure scenario: an editor opens /broll on a phone to find a shot for a client folder. The page scrolls sideways, and the rail and grid cannot both be seen.
- Evidence: 390 px iframe render, `docW=718`, overflow `flag-toggles:718`. Screenshot scratchpad/uiw/idx390.png.
- Ledger: new
- Suggested fix: an `@media (max-width: 700px)` block that lets `.flag-toggles` wrap, stacks the rail above the grid (or collapses it), and uses `repeat(auto-fill, minmax(160px, 1fr))` with `width: 100%` thumbs.

## Coverage note
Not read closely: app.js's segment/transcript list rendering, renderVideoMeta, the seek/scrub/shuttle internals (~40% of app.js); ingest.js's drop/collect/prepare/upload/precheck/take-over/retry halves (~70% of it). The ingest drawer was not rendered with realistic data. The detail view of index.html was not rendered at all (it needs a live proxy). Space-on-a-focused-button activation under a keydown `preventDefault` was reasoned, not driven with real key events (no CDP driver available). The real injected dashboard topbar was not rendered into the b-roll header (the measurements used the fallback header, which is shorter), so the finding 4 overlaps are lower bounds.

## OUT OF TERRITORY
- dashboard/templates/partials/topbar.html:40: the injected brand link reads "<ORG> // SYNC STATUS" on the /broll page. Whether `?current=broll` changes that label was not verified.
