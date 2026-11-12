# Footage Sorter: every page, screen and control

Terms used throughout:
- **Clip**: one recording as the sorter sees it (a video, a still, an image sequence, an audio file, or "other"), possibly made of several files.
- **Destination**: a folder in the studio's final folder tree that a clip is assigned to.
- **Assignment**: the person's decision that a clip goes to a destination. **Suggestion**: the sorter's guess at a destination (from the calendar, a bound folder, or the audio).
- **Card**: a camera memory card plugged into a machine. **Session**: one card's ingest (copy-off) run.
- **Ledger**: the server's record of every copy of every clip on every drive.
- **Desktop layout** and **phone layout**: see "Layout: desktop or phone".

## Page shell and first load (source: index.html)

- The main page is titled "Footage Sorter". It uses a tiny inline square icon (dark ground, a red bar and a cyan bar). Theme colour is near-black.
- All its fonts (IBM Plex Sans, JetBrains Mono, Orbitron) are shipped with the page; nothing is fetched from outside.
- Every URL the page uses is relative to the page, because the page is served both on its own and under `/sorter/` inside the CC Sync dashboard.
- Before any script has loaded, the page starts five requests at once so the first screen fills sooner: the lean state summary (`api/state/meta?lean=1`), the slim list of source-side clips, meaning cards and source folders (`api/clips?location=source&slim=1`), the destination tree (`api/desttree`), the ingest sessions (`api/ingest/sessions`) and the ledger's drives (`api/ledger/volumes`). A failure of any of them is swallowed and the later code asks again. None of these is made when the URL carries `?mock=`.
- Until the state has arrived, the centre shows a spinner with "Loading your clips" and "One moment." (never "No clips match the current filters" during the first load).
- With `?mock=` in the URL the page loads a development mock in place of the server (see "Development mock"). `DEV ONLY`.

## Layout: desktop or phone (source: phone.js, style.css)

- The page decides "phone" before first paint, so a phone never flashes the desktop layout.
- Rule: if the person forced a layout, use it. Otherwise it is a phone when the pointer is coarse and cannot hover AND the smaller of screen width and window width is under 1024 px, OR whenever the window is narrower than 720 px. The browser's "Desktop site" request does not override this.
- `?layout=phone`, `?layout=desktop` or `?layout=auto` in the URL forces the layout and is remembered in the browser (local storage key `fs.layout`) for later visits until another `?layout=` changes it. If local storage is blocked it falls back to automatic.
- The layout is re-decided 120 ms after any window resize stops.
- Desktop layout: three panes side by side (Source, Clips, and a right panel with tabs), a header bar, a toolbar and a status line at the bottom.
- Phone layout: one view at a time out of three, named in a bottom navigation bar that is always in the same place: **Source**, **Clips** (with the current clip count read off the Clips pane header, digits and commas only), **Folders** (the right panel: the Destinations tree and the other five tabs). The view shown on arrival is Clips. The active button is highlighted.
  - Tapping Source or Folders shows that view. Leaving Clips adds one browser history entry; switching between Source and Folders replaces it rather than adding another.
  - Tapping Clips, or using the phone's back gesture/button, returns to Clips (it goes back through the history entry if there is one).
  - Tapping a folder row in the Source tree or the Destinations tree filters the grid and then jumps to Clips automatically. Tapping the expand arrow, a button inside a row, a rename box or a "pill" in a row does not jump.
  - A **Filters** button appears in the toolbar only on the phone. It opens and closes the extra filters that do not fit (it toggles an "open" state on the toolbar and shows itself pressed).
  - When at least one clip is selected, the Assign and Unassign controls are brought up (the page tracks "has a selection" from the selection counter).
- The page exposes "set view", "back to Clips" and "is phone" for the other scripts.

## Shared building blocks: messages, dialogs, folder picker (source: util.js)

- **Toasts** (short messages in a corner): plain, success, warning or error. They fade after 3.2 seconds, or 6.5 seconds for an error, unless a caller sets another time. A toast may carry one action button (for example a card-detected toast that can take you to the card); pressing it closes the toast and runs the action.
- **Dialogs**: a title bar with a close cross, a body and a row of buttons (default one "Close" button). Escape closes the topmost dialog; a mouse press on the dark backdrop outside the box closes it; the cross closes it. The first input, list or button in the dialog gets the keyboard focus unless the caller says not to.
- **Choose destination folder** dialog (used wherever a destination is picked): a search box ("Type to filter folders…") over a list of every destination folder plus every "planned" folder (one that does not exist yet but is part of the plan), each shown as parent path in a dim style plus folder name, with a "planned" tag where it applies. Typing filters by any part of the path, case-insensitive. At most 400 rows are drawn. Up and Down arrows move the highlight, Enter picks the highlighted folder, a click picks a folder, moving the mouse over a row highlights it. Arrow and Enter keys are ignored while an input method (Chinese, Japanese, Korean typing) is composing. "No matching folder." when the filter matches nothing. Buttons: **Clear** (only where clearing is allowed: returns "no destination") and **Cancel**. Closing in any other way is a cancel.
- Number formats used everywhere: sizes in B, KB, MB (whole numbers), GB and TB (two decimals under 10, one decimal at 10 and over); counts with thousands commas; durations as m:ss or h:mm:ss (nothing shown for zero or unknown); a day as `YYYY-MM-DD · Wkd`, "No date" when there is none; a clip's time as HH:MM read straight from its recorded timestamp (the camera's local clock, no time-zone conversion), "--:--" when unknown.
- Every destination gets its own colour (a hue worked out from its path, the same every time); it is drawn as a coloured rail on that destination's tags.

## The clip grid (source: grid.js)

- The centre pane is a grid of clip cards. Only the rows on screen (plus two rows above and below) exist at any time, so tens of thousands of clips scroll smoothly.
- Card width fills the pane: at least 168 px and at most 262 px at normal size, as many columns as fit. Card height follows the stylesheet.
- **Thumbnail size** has six steps (0.78x, 1x, 1.3x, 1.7x, 2.2x, 2.9x of the base widths); the default is 1x. The chosen step is remembered in the browser (`fs.zoom`). After a size change or a window resize the grid keeps roughly the same clip at the top.
- **What a card shows**:
  - The thumbnail, or until it loads a placeholder glyph for the kind (video, still, sequence, audio, other).
  - Chips on the picture: camera name ("other" when unknown), kind (blank for video, otherwise the kind's name), duration (hidden when unknown).
  - A location dot coloured by where the footage physically is (card, staging, final or elsewhere), marked whether it is backed up, and, when the clip has a planned move, the plan's state.
  - A duplicate badge when another clip has the same file name: an "S" badge on the copy that is the smaller (or otherwise not-kept) one, a plain badge on the copy worth keeping. Its tooltip names the rule that decided: larger size; already sorted into the destination; more recent recording; or identical (same size and time, kept by a fixed tie-break so the answer does not move between redraws). Exact tooltip texts, for the "smaller" copy: "A smaller copy of “<name>” - another clip has the same name and more of it", "Same size as the copy of “<name>” already sorted into the destination - that one is kept", "Same size as another copy of “<name>”, but recorded earlier - that one is kept", "Identical to another copy of “<name>” (same size, same time) - that one is kept; either would do"; for the kept copy: "Duplicated: another clip has this name, and this is the larger copy to keep", "...this one is already sorted into the destination, so it is kept", "...this is the more recent recording", "...this one is kept so the answer does not move between renders".
  - A health badge: "⚠ DAMAGED" or "⚠ CHECK" when the camera never closed the clip properly, or "⚠ BAD COPY" when the check after copying found the copy broken. Its tooltip is the ingest explanation (see the Ingest section).
  - Below the picture: the clip's name ("(unnamed)" when it has none), the recording time, the ledger's copy-count badge when the server sent one, the last part of its source folder, and its size.
  - The foot: either a destination tag (when assigned) or a suggestion badge (when only suggested), never both.
    - Destination tag: the last two segments of the destination path ("(root)" for the root), coloured with the destination's hue, with a ✕ button. Tooltip "In place: <dest>" when the clip is already where it is assigned, otherwise "Assigned to <dest> · <structure>" (structure is "convention" by default).
    - Suggestion badge: the suggestion's summary (or the folder name), prefixed "♪ " when it came from the audio, with a "＋". Styled dimmer when confidence is low, differently when inferred from an event title, differently when heard in the audio, and marked as a clash when there are alternatives. Tooltip: "Suggested (<confidence>, heard in the audio | , inferred from the event title | , from a folder you bound): <dest>", then the reason, then one line per alternative "also possible: <dest>  (<summary>, <n> min off)", then "Click to accept".
  - The card is highlighted when selected, styled as assigned or suggested, and marked **staged** when the grid is filtered to a destination folder and this clip is assigned there but is not physically in it yet (on a card, in staging, elsewhere, or filed into a different final folder). A clip assigned "in place" is never staged.
  - The card's hover tooltip is built when the pointer arrives: name, source folder ("(root)"), file count and size, the recorded timestamp, the health explanation, then where it is ("On card <drive>", "Staging", "Final" or "Elsewhere") and "backed up" (with " to <backup>", or " (the ledger: copies elsewhere)" when only the ledger says it is safe, plus " (matched as a twin of a copy already filed)" when that applies) or "not backed up", plus " · destination: <plan state>" when the clip has a planned move.
- **Mouse on a card**:
  - Click on the ✕ of the destination tag: unassigns that one clip.
  - Click on the suggestion badge: accepts that clip's suggestion.
  - Click elsewhere: selects (plain click selects only it; Ctrl/Cmd-click toggles it; Shift-click selects a range; see "Selection" in the main app section).
  - Double-click: opens the clip's details in the Info tab.
  - Drag: if the card is not already selected it becomes the only selection, then all selected clips are dragged together, in grid order. The drag image reads "<n> clip(s) · <total size>". Drop it on a destination folder to assign (see the Destinations tree). While dragging, the dragged cards are dimmed and the page is in drag mode.
- **Rubber-band selection**: press the left button on empty grid space (not on a card, not on the scrollbar) and drag to draw a box; every clip the box touches is selected, including ones scrolled out of view. Without a modifier the existing selection is cleared at the press; with Ctrl, Cmd or Shift the box adds to the existing selection. A box needs more than 3 px of movement before it counts. Holding the pointer within 34 px of the top or bottom edge scrolls the grid, faster the further past the edge.
- **Thumbnails**: one picture per recording, fetched from `api/thumb/<key>`; cards narrower than 200 px ask for the small (160 px) version. The browser's normal cache keeps them; the page stores no image data itself. Audio and "other" clips never ask for a picture. A clip still on a card has no picture until the server says one exists (the picture comes from the companion at that card); once it does, an earlier "no picture" is forgotten. A failed picture is remembered as "no picture" for that recording for the rest of the visit.
- **Scroll-aware picture loading**: while the grid scrolls faster than 1,600 px per second, cards show their placeholder and ask for nothing. 90 ms after the scroll stops (checked again after the next frame on slow devices), the on-screen rows are fetched, nearest the middle first, at high priority. 220 ms after the scroll stops, the overscan rows are fetched too, at low priority. Two slow scroll events in a row are needed before a fast scroll counts as slowed.
- **Hover preview (scrub)**:
  - Hovering a card for 300 ms starts a preview; leaving the card stops it. No preview starts during a rubber-band drag or a card drag, or for a clip whose preview already failed this visit.
  - For a video with Sound off: a filmstrip (12 to 50 frames tiled in one picture, from `api/strip/<key>`) is shown and the frame follows the pointer's horizontal position across the picture; a thin bar under the picture shows the position. After the pointer has stayed 90 ms the filmstrip is fetched ahead of time, unless Sound is on, the clip is known to have no filmstrip, or the browser asks to save data.
  - For a video with no filmstrip, for an audio clip, or with Sound on: the clip's proxy is streamed from `api/proxy/<id>`. With Sound off it is muted and the pointer position seeks it. With Sound on it plays with sound, starting at the pointer's position (useful for hour-long recorder files); if the browser refuses autoplay nothing more happens. An audio clip shows as an audio-only preview.
  - If the preview reports a duration and the clip had none, the duration chip is filled in for display.
  - A proxy that fails is remembered as "no preview" for the visit.

## Loading the library, who is asking, and keeping it fresh (source: app.js)

- **Who is asking**: on load the page asks `api/whoami` (never cached). Run on its own the answer is a local administrator with no token; inside the CC Sync dashboard the dashboard answers with the signed-in user and a cross-site-request token. Every write (any request that is not GET or HEAD) carries that token in an `X-CSRF-Token` header when one was given. If `whoami` fails the page acts as the local administrator.
- **Error messages from the server**: a failed request shows the server's `error` text, or the first 200 characters of a plain-text answer, or "<status> <status text>".
- **Two-part state**: the page loads the library in two parts, each re-asked with the copy it holds so an unchanged part costs nothing ("not modified" answer): the summary state (`api/state/meta?lean=1`: settings, assignments, suggestions, calendar events, sessions and so on) and the clip rows (`api/clips?location=source&slim=1`). If the server lacks those routes (a "not found" answer), the page falls back to one combined request, `api/state`, for the rest of the visit. Any other error is shown (see "Start view").
- **Lean start**: when the server sends the lean summary, the page holds only the clips on the SOURCE side (cards and source folders). The clips already filed in the destination (the large majority) are fetched only when a view needs them (`api/clips?location=final&slim=1` plus `api/dest/detail` for their assignments and heard names). Until then the destination's numbers come from a server-side summary. Once fetched they are kept for the visit and re-asked conditionally on every refresh.
  - If the destination clips fail to load: error toast "Could not load the destination clips: <reason>".
  - The rows arrive without their full file lists; the full list for one clip is fetched (`api/clip/<id>`) when its info pane or dialog needs it and the clip has more than one file. If that route does not exist the page stops asking.
- **Calendar events fallback**: if the state carried no events, the page asks `api/events` once; a failure is ignored (the calendar is optional).
- **"In place" clips**: a clip that already sits under the destination root and has no assignment counts as assigned to the folder it is in, everywhere the page counts, filters or badges. Nothing is written for it, the server never moves it, and Unassign has nothing to remove. A clip still on a card is never "in place".
- **Destination tree**: fetched from `api/desttree`. If it fails: error toast "Destination tree unavailable: <reason>".
- **Background refresh every 15 seconds** (only while the browser tab is visible, and not while a rescan is running, and not while a rename or new-folder box is open in the Destinations tree):
  - The clip rows are re-asked conditionally. If new clips arrived, success toast "<n> new clip(s) arrived" for 4 seconds, and the grid and info pane are redrawn.
  - The destination tree is re-read; it is redrawn only if its folder list actually changed (so folders made in Explorer appear on their own). A failure here is silent.
- **Folders the tree shows that are not on disk**: every planned folder, every assigned destination, every folder an event is bound to, every folder a suggestion points at (for unassigned clips), and every folder the server's summary says holds clips. These are added to the Destinations tree as "planned" nodes. Matching is case-insensitive and keeps the spelling of an existing folder (typing "b-roll" beside an on-disk "B-roll" does not make a second node). Folder names sort naturally (numbers in order, case ignored).

## The start view in the centre (source: app.js)

- With a lean server, the centre does not open on every clip. It shows a prompt until something narrows the view: a source folder or card, a destination folder, an event, a search, any filter, or "All clips" chosen on purpose.
- States of the centre message (shown instead of the grid):
  - **Loading** (first load): spinner, "Loading your clips", "One moment."
  - **Failed** (the first load failed): "The clips did not load", the error, and a **Try again** button that repeats the whole first load (state, destination tree, trees, events, Missing tab).
  - **Listing a drive**: spinner, "Listing the clips on <drive>", "One moment." while the ledger fetches a drive's clip list for the "On a drive / Not on a drive" filter.
  - **Loading the destination**: spinner, "Loading the destination’s clips", then "About <n> clips · they are fetched once, then kept for this visit." (or "One moment." without a summary). Shown whenever the view needs the whole library: "All clips", or any filter that is not inside one source folder, or a source folder that is the destination root itself.
  - **Destination failed**: "The destination’s clips did not load" and **Try again**.
  - **Prompt**: "Choose where to look", "Pick a source folder, a card or a drive on the left, and its clips appear here.", then "<n> clip(s) in your source folders · <n> card(s) in a reader. The destination’s clips are not loaded until you ask for them." Buttons: **Open Source** (phone only, switches to the Source view) and **All clips (<total>)** (tooltip "Load every clip, the destination’s too"), which clears any source folder pick, loads the destination's clips and shows everything.
- When the grid shows and nothing matches: "No clips match the current filters.", or "No clips scanned yet - press Rescan." when there are no clips at all. Never shown before the first load finishes.
- The Clips pane header shows "<n> clips" or "<n> of <total> clips" ("–" while the prompt is up).

## Header bar (source: index.html, app.js)

- **FOOTAGE SORTER** brand with the Creators Club mark: a link back to the CC Sync dashboard (the page one level up). A second, compact back link "‹ CC Sync" does the same (styled for the phone).
- **Totals**: number of clips in the whole library (including destination clips counted by the server and not yet loaded); number assigned (in-place clips count; all destination clips count as filed); number suggested but not assigned (hidden when the window is 1,500 px wide or less); total size of assigned clips; total size of everything (dim, also hidden at 1,500 px or less).
- **Not at home** chip and **Backups** chip: hidden until the server has a ledger (see the Ledger section).
- **Scanning…** indicator with a spinner, shown while a scan runs.
- **Settings** gear button (tooltip "Settings: drives, scans, backups"): hidden until the ledger is present; opens the Settings sheet.
- **Calendar chip** (starts as "Connect Google Calendar"): see the Calendar section.
- **Rescan** button: see "Rescan".
- **Move…** button, the main action (tooltip "Plan, dry-run and carry out the moves on the server"): opens the Move dialog.

## Toolbar: search, filters, sort and bulk actions (source: index.html, app.js)

- **Search box** ("Search stem, folder, camera, destination, event…"; Ctrl+F focuses it). Matches, case-insensitively, any part of: the clip name, its source folder, camera, kind, its assigned destination, its suggestion's summary and destination, and the summaries and destinations of the suggestion's alternatives (so a shoot's name finds every clip it was in contention for). When an event is picked as a filter, the typed text is not applied to the clips (the event is the search).
- **Camera** list ("All cameras" plus every camera with its clip count, "other" for unknown). **Date** list ("All dates" plus every recording date with its count, "(no date)" for clips without one). **Kind** list ("All kinds" plus each kind with its count). The lists are rebuilt from the loaded clips; a chosen value that no longer exists falls back to "All".
- **Pick a day** calendar button (tooltip "Pick a day from a calendar, with what was scheduled on it"): opens the "Pick a day" dialog.
- **Status** segmented buttons: **All**, **Unsorted** (no assignment), **Suggested** (no assignment, has a suggestion), **Assigned**, **Not backed up** (tooltip "Clips that exist in only one place": clips not safe anywhere a card wipe cannot reach).
- **Location** list: All locations, Card, Staging, Final (where the footage physically is).
- **Where** list and **drive** list: hidden until a ledger exists (see the Ledger section).
- **Sort by**: Time (default), Length, Size, Name, and "Fewest copies" (hidden until the ledger exists). The **↑ / ↓** button reverses the direction (tooltip "Reverse the sort").
  - Every sort puts "work" first and "finished" last regardless of direction: a clip the current move plan will skip or that already survives elsewhere (or, with no plan, a clip already backed up) sinks to the bottom.
  - Clips whose value is unknown (no time, no length, no size, no copy count) sink to the bottom in either direction. Ties are broken by name in natural order.
  - Sorting by length uses durations learned while hovering, so it is recomputed each time.
- **Clear filters** button: resets every filter.
- **Thumbnail size** − and + buttons (tooltip "Thumbnail size (Ctrl+– / Ctrl+=)").
- **Sound** toggle (tooltip "Play sound while previewing (hover a clip)"): off by default; with it on, hover previews play the proxy with sound rather than scrubbing a silent filmstrip.
- **Selection counter**: "0 selected", or "<n> selected · <size>".
- **Structure** list (tooltip "Folder structure used for new assignments"): **Convention** (default) or **Preserve** (keep the source sub-folders under the destination). It is stored with every assignment made after it is changed.
- **Accept suggestions** button (amber):
  - Works on the selection if there is one, otherwise on every suggested, unassigned clip in the current view.
  - Clips that are already backed up are left out of a bulk accept (they would be duplicate copies); they can still be assigned by hand.
  - Label: "Accept <n> suggestion(s)" plus " (view)" when it is working on the view rather than a selection; "All backed up already" when every candidate is already backed up; otherwise "Accept suggestions" (disabled). Tooltip when some were left out: "<n> suggested clip(s) are already backed up and left out - assign those by hand if you want a second copy."
  - Opens the "Accept suggestions" review dialog (below).
- **Suggestions ▾** button (enabled when any selected clip has a suggestion; tooltip mentions [ and ]): opens a menu under the button. Its heading: "<n> of <m> selected clip(s) has/have suggestions". Then one item per destination that is the suggestion or an alternative for any selected clip, most clips first: the folder name, with a hint "<event summary> · <n> of <m> clips (<k> as first choice)". Choosing an item assigns only the selected clips that have that destination among their own choices, then toast "Assigned <n> clip(s) to <folder> · skipped <k> without that suggestion" for 12 seconds with an **Undo** action that puts every clip back exactly as it was (unassigned or its old destination and structure). Each item also has a "go" action that reveals the folder in the Destinations tree. If none has it: warning "None of these clips has <folder> as a suggestion." With no suggestions at all: "The selected clips have no suggestions."
- **Assign to…** (enabled with a selection): opens the destination picker (see "Assigning").
- **Unassign** (enabled with a selection): removes the selected clips' assignments.
- On the phone the toolbar keeps the search and the Filters button; the remaining filters open behind Filters, and Assign/Unassign come up when there is a selection.

## Search hit cards above the grid (source: app.js)

- While text is typed in the search box, up to 12 cards appear above the grid naming the events and folders that match, events first (by start time), then folders (by path). More than 12: "+<n> more - narrow the search".
- **Event card**: "Event", the day and time range (no time for an all-day event), the title ("(no title)"), the place, and the folder it feeds: the bound folder (tooltip "Bound to <dest>"), a folder read from its title (tooltip "Read from the title: <dest>") or "no folder bound" (tooltip "Bind it on the Events tab"). Counts: "<n> assigned", "<n> suggested", and "not counting the destination" when destination clips are not loaded (tooltip "The destination's clips are not loaded: open All clips to count them too"). An event matches on its title, its place or its folder.
  - A clip belongs to an event if the event is its suggestion or one of its alternatives, or if it is assigned to the event's folder (or below it) and was recorded within the event window. The window is from 1 hour before the start to 2 hours after the end, or the whole day for an all-day event. An event with no folder claims assigned clips by the window alone.
  - Clicking the card filters the grid to that event (and clears any destination folder filter); clicking it again removes the event filter. The active card is highlighted.
- **Folder card**: "Folder", the span of recording dates of its clips ("no dates", one day, or "<first> → <last> · <n> days"), the folder name and full path, the first event that feeds it plus "+<n>" more (tooltip lists each with date, time and whether it is bound or only at the same time), and "<n> clip(s)" including destination clips not yet loaded, with "dates need the destination loaded" when some are not. A folder matches only on its own last name (so "Interviewees" does not return every interviewee).
  - Clicking filters the grid to clips headed for that folder or below it (assigned or suggested), clearing any event filter; clicking again clears it.

## Selection (source: app.js, grid.js)

- Plain click selects one clip and makes it the anchor. Ctrl/Cmd-click adds or removes one clip and moves the anchor. Shift-click selects every clip between the anchor and the clicked one in the current view (replacing the selection; with Ctrl/Cmd also held, adding to it).
- A click (not a box drag) also reveals the clip's destination in the Destinations tree.
- The selection survives filtering: clips selected and then filtered out stay selected and are still acted on (they come after the visible ones).
- Changing the selection updates the toolbar, the Info tab and the Audio tab.

## Assigning, unassigning and accepting suggestions (source: app.js)

- Every assignment change is shown at once and then sent to the server (`api/assign` with the clip ids, destination and structure; `api/unassign` with the clip ids). The server's answer (the manifest, suggestions and implied time folders) replaces what the page holds. If the request fails, the change is undone on screen and an error toast says "Assign failed: <reason>" or "Unassign failed: <reason>".
- Unassign only touches clips that have a real assignment (in-place clips have nothing to remove).
- **Accept one suggestion**: clicking a card's suggestion badge assigns that clip to its suggestion immediately.
- **Accept suggestions review dialog** ("Accept suggestions", 760 px wide): heading "<n> clip(s) · <size> into <n> folder(s)", then notes: "<n> already backed up - left out", "<n> low confidence (same day only)", "<n> with another event in contention", or "every one is a high-confidence match". One row per destination, most clips first, each with:
  - a tick box (on by default; clicking anywhere on the row's head toggles it, and an unticked row is dimmed), the destination path, and "<n> · <size>";
  - the evidence: up to three sources ("← <event summary> ×<n>", or "← ♪ <name>" for audio), "… and <n> more", and "<n> matched on the day only, not the hour" for low-confidence ones;
  - when some of its clips have alternatives: a segmented choice between the group's own suggestion and each alternative ("<folder> · <n>" or "<folder> · <n> of <m>"), with a line saying "All <n> go to their own suggestion" or "<n> go to <folder> · <m> stay on <folder>". Picking an alternative sends only the clips that have that alternative; the rest stay on their own suggestion. Nothing is written until Accept.
  - **Show these**: selects that group's clips, closes the dialog and scrolls to the first.
  - Buttons: **Cancel**, **Accept checked** (nothing ticked: warning "Nothing checked." and the dialog stays). Accepting assigns group by group and then shows "Accepted <n> suggestion(s) into <n> folder(s)".
  - No suggestions at all: warning "No suggestions to accept here."
- **[ and ] keys** (with clips selected): move each selected clip to the previous or next of its own choices (its suggestion, then each alternative, wrapping round). A clip not yet assigned to one of its choices goes to the first choice with ], or the last with [. Then toast "Next|Previous suggestion for <n> clip(s) · <k> have none" for 12 seconds with **Undo**. Nothing to do: warning "No suggestion to move to."

## Missing tab (source: app.js)

- A right-panel tab, "Missing", with a badge counting everything listed below that is still open (hidden at zero). While the destination's clips are not loaded the count reads "<n>+" (tooltip "At least this many: open the tab to load the destination and check the rest") and the badge stays visible.
- Header: "<n> to look at" ("<n>+" when partial).
- When the destination's clips are not loaded: a banner "These checks need the destination's clips, which are not loaded." with **Load them**, or "Loading the destination's clips to finish these checks…" while they load.
- **Interviews missing coverage (<n>)**: only folders under an "Interviewees" folder are checked. A folder is short if it has no video ("no video"), fewer than two distinct camera bodies ("no a second camera"), or no audio clip ("no sound"). Folders that also hold destination clips not yet loaded are never flagged. Camera bodies are told apart by the model in the file's metadata, then by a Blackmagic RAW file, then by a camera label of BMCC/FX3/DRONE, and otherwise by the card folder path with dates, offload time ranges (like "15.56-17.17") and the camera's own card structure folders removed. Each row: folder name (tooltip the full path), one tag per gap, "<n> clips · <n> camera(s) (<bodies>) · <n> sound" or "· no sound", and **Show** (filters the grid to that folder). Empty: "Every interview folder has A-CAM, B-CAM and sound."
- **Shoots with no footage (<n>)**: timed calendar events (not all-day) with no clip recorded from 30 minutes before the start to 30 minutes after the end, and not covered by destination clips the server summarised. Newest first. Each row: title ("(untitled)"), a "no footage" tag, start "YYYY-MM-DD  HH:MM", "→ <folder>" when bound or inferred, and **Dismiss** (tooltip "I know about this one - stop listing it"; saved on the server with `api/dismiss-event`). Empty: "Every scheduled shoot has footage against it." Failure: error toast with the reason or "Could not save that".
- **Same file twice in one folder (<n>)**: assigned clips with the same name heading for the same destination under the Convention structure (Preserve assignments never collide). Groups where one copy is a different size come first. Lead line "<n> clips · export would refuse these as collisions · <n> where one copy is shorter than the other". Up to 40 groups, each: the name, "one copy is short" or "<n> identical", "→ <dest>", one line per copy with size, duration and source folder, and **Show these** (shows exactly those clips, titled "<name> - duplicate copies"). More: "… and <n> more". Empty: "No destination has two clips sharing a filename."
- **Interviewees not shot yet (<n>)**: people on the episode roster (loaded on the server from the production sheet) whose Chinese name, or full English name of 5 or more characters, appears in no assigned, summarised or suggested destination path. Grouped by episode, most missing first: "<episode>", "<n> not shot", then each name. A name the audio tool heard on some clips is marked "♪" with the tooltip "Heard on <n> clip(s) by the audio tool - the interview exists, it is just not filed". No roster: "No roster loaded - build it with  npm run roster -- "…FF5 - FF5.csv"". Nobody missing: "Everyone on the FF5 sheet has footage."
- **Dismissed (<n>)**: each dismissed event with **Restore**.

## Pick a day dialog (source: app.js)

- Opens on the month of the current date filter, or the month of the last day with footage, or today. "Nothing scanned yet." warning when there is no footage and no events at all.
- Header: ‹ and › change month; **Latest shoot** jumps to the month of the last day with footage.
- A Monday-first month grid. A day with footage shows the clip count and total size and can be clicked. A day with calendar events but no footage shows "no footage". Up to three event titles per day, then "+<n>". Tooltip: the date, "<n> clips · <size>" and the cameras, or "no footage", then each event's time and title. The current date filter is highlighted. Destination clips not yet loaded are counted from the server's summary.
- Clicking a day sets the Date filter, closes the dialog and shows "<n> clip(s) on <date> · <event titles>".
- Footer: "<n> day(s) shot this month · <n> clips" and **All dates** (clears the date filter and closes). **Close** button.

## Add a source folder dialog (source: app.js)

- Opened by the "+ folder" button in the Source pane header (tooltip "Sort footage from another folder").
- Text: "Sort footage that never passed through the staging folder. Paste the folder path - from Explorer, Shift+right-click the folder and choose “Copy as path” - or drag it in from the address bar."
- A drop zone, "Drop a folder path here, or paste it below": accepts a dragged path as text or a `file://` link (converted to a Windows path, surrounding quotes removed). Dropping a real file from Explorer gives "Windows does not hand a browser the path of “<name>”. Paste it instead - Shift+right-click the folder in Explorer, “Copy as path”." Anything else: "Nothing usable in that drop."
- A path box (placeholder `P:\Assets\B-roll Archive\…`) and a list "Sorting from:" of the current source folders.
- **Add and rescan**: empty box gives "Give a folder path first."; otherwise sends `api/source-roots` with the path; on success closes, shows "Added <path> - rescanning" and starts a rescan; on failure shows the server's reason in the dialog (or "Could not add that folder") and stays open. **Cancel**.

## Source pane (source: app.js, index.html)

- Header: "Source", a label naming every computer in the panel ("creator-1 · razer · NAS"), the **+ folder** button (Add a source folder dialog) and a **‹** button that hides the Source pane (tooltip "Hide the Source panel (the clips get its space)"). When hidden, the Clips pane header shows **› Source** to bring it back. Whether it is hidden is remembered in the browser (`fs.srcHidden`).
- The pane is one closed-by-default dropdown per **computer**: the computers the server lists, plus any computer a source folder or a card names, plus "Unknown computer" for any that the server did not name. Computer names are matched loosely (case, spaces and underscores ignored: "Creator_1" is "creator-1"). "No computers yet." when there are none.
  - A computer row: its name, a green "<n> card(s)" pill when cards are in its readers, and its clip counts. Tooltip "<name>: <n> tracked folder(s) · <n> card(s)". Clicking opens or closes it.
  - Inside: each tracked source folder on that computer (as a folder tree), then a **Cards** dropdown when it has cards in a reader or closed cards still in a reader, with "<n>" or "<n> + <k> closed". Inside Cards: each live card and each closed card (drawn by the Ingest part, see "Cards in the Source pane"). With nothing at all: "No tracked folders".
  - When a new card arrives, its computer and its Cards dropdown open on their own.
- Folder rows show the folder name and counts: "<assigned>/<total>" (assigned in green), or "<suggested>/<total>" (amber) when nothing is assigned, or just the total. Tooltip on the counts: "<n> clips · <n> assigned · <n> suggested"; tooltip on the row: "<computer>: <full path>".
- Clips on a card and clips already in the destination are never listed under source folders.
- The expand arrow opens or closes a folder without filtering. Clicking the row filters the grid to that folder and everything under it; clicking the active row again clears the folder filter. The active row is highlighted.

## Destinations tab (source: app.js)

- First tab of the right panel. Header: "Destinations", a label "<destination root path>  ·  <n> clips · <size>", and a **+ folder** button (tooltip "New folder at destination root") that opens a new-folder box under the root.
- The root row is always open; other folders open with their arrow. Counts on each folder include every subfolder: "<assigned>" (green) "+<suggested>" (amber) " · <size>". Tooltip: "<n> assigned directly here, <n> including subfolders" or "nothing assigned yet", plus "<n> suggested (not accepted)". Destination clips not yet loaded are counted from the server's summary. Matching is case-insensitive.
- Folder kinds, each with its own icon and tooltip suffix on the full path:
  - On disk: plain.
  - **Planned** (✚, name styled as planned): "(planned - created by mover)".
  - **Suggested only** (◇): a folder that exists only because suggestions point at it: "(suggested only - nothing is committed here yet; accept the suggestions to make it real)". It cannot be renamed, moved or removed.
  - **Placeholder** (waiting): a folder kept for someone not filmed yet, shown but not created on disk until a clip lands in it: "(no footage yet - held for them, and not created on disk until a clip lands here)". Once a clip is assigned or suggested to it, it reads normally.
  - **Mirrored**: a placeholder whose person's footage is filed in another folder with the same last name: it shows "→ filed in <episode>" (click it to jump to that folder) and the tooltip "(their footage is filed under <dest> - <n> clips. Nothing is created here.)".
- A ⚠ flag on an interview folder short of coverage (tooltip "Missing <a second camera, sound…> - see the Missing tab").
- Below an open folder, the time folders a card copy would create are shown as "ghost" leaves (drawn by the Ingest part).
- **Row controls** (on "real" folders: on disk, planned, or with something assigned or bound):
  - ✎ **Rename** (tooltip "Rename <name>  (F2, or double-click the name)"); double-clicking the name also renames; F2 renames the last-clicked (active) folder. The name turns into a box with the name selected; Enter or leaving the box saves, Escape cancels; Enter is not taken while an input method is composing. Sends `api/folders/move` with the new name. Success: "Renamed to <name>  (<n> clip(s) followed it)"; when the old folder was already on disk and empty: warning "The empty folder is still under its old name on disk - nothing was renamed there: <path>". Failure: the server's reason, or "Could not rename that folder". A destination filter on the folder follows it.
  - ＋ **New folder inside** (tooltip "New folder inside <folder>"; on every row including the root): a "New folder name…" box under the row; Enter or leaving the box creates, Escape cancels. Rules: no `\ / : * ? " < > |` (error "Folder name cannot contain \ / : * ? " < > |"); no reserved Windows names CON, PRN, AUX, NUL, COM1-9, LPT1-9 (error "“<name>” is a reserved Windows name and cannot be a folder."); trailing dots and spaces are removed with the warning "Trailing dots/spaces removed - Windows would drop them anyway." (only dots and spaces: "That folder name is only dots and spaces."); an existing folder of that name (any case): warning "That folder already exists.". Otherwise it is added as a planned folder at once and sent to `api/folders`: "Planned folder: <path>"; failure "Could not create folder: <reason>" and the tree is reloaded. Nothing is made on disk at this point.
  - ✕ **Remove** (tooltip "Remove this folder from the tree (nothing on disk is touched)"): first asks the server what removing would take (`api/folders/remove` with `preview`). If nothing would change: "“<dest>” only exists on disk. This app never deletes inside your projects - remove it in Explorer, then reload." or "Nothing to remove here.". Otherwise a "Remove folder" dialog lists: "<n> planned folder(s) dropped from the plan", "<n> clip(s) unassigned - back to unsorted. The footage itself is not touched.", "<n> calendar binding(s) cleared", and, if the folder is on disk, "This folder also exists on disk and holds <n> file(s)" (or ", empty") with "It stays where it is - this app never deletes inside your projects. Remove it in Explorer if you want it gone." Buttons **Cancel** and **Remove**. After removal: "Removed <dest> - <n> clip(s) unassigned, <n> binding(s) cleared" and, if on disk, "The folder is still on disk - nothing was deleted there.". Failure: "Could not remove folder: <reason>" (or "Could not check that folder" at the preview step).
- **Click a row**: filters the grid to clips assigned or suggested to that folder or any folder beneath it, and opens it if it has subfolders; clicking again clears. Clicking the root row clears the destination filter.
- **Double-click a row** (not its name) with clips selected: assigns the selection there; toast "<n> clip(s) → <dest>".
- **Drop clips on a row** (dragged from the grid): assigns them there with the same toast. The row under the pointer is highlighted. The root row is not a target for clips.
- **Drag a folder onto another folder** (real folders only): moves it (with everything assigned into it) under the target; the root is a valid target. Not allowed into itself, into its own subfolder, or where it already is. Sends `api/folders/move`. Success: "<name> → <target or destination root>  (<n> clip(s) and <n> subfolder(s) followed it)"; when the folder was already on disk and empty: "The empty folder is still at the old place on disk - nothing was deleted. Remove it yourself if you want it gone: <path>". Failure: the reason or "Could not move that folder".
- **Drop files from Explorer on a row**: see "Dropping files from Explorer".
- **Reveal**: other parts of the page can open the Destinations tab, expand every parent of a folder, scroll it to the middle and flash it for 1.2 seconds. If the folder is not in the tree: "That folder is not in the tree - rescan the destinations?" (silent when it is done automatically on a click).
- **Following the selection**: clicking a single clip switches to the Destinations tab and reveals its assigned (or suggested) folder; with several selected it only switches to Destinations. It does not switch away while the Info or Audio tab is showing. A single audio clip with transcript results opens the Audio tab instead.

## Events tab (source: app.js)

- Tab "Events" with a badge counting all calendar events (hidden at zero). Header "Calendar events", a ↻ button (tooltip "Refresh the calendar now"; see the Calendar section), and "<n> bound / <total>".
- A filter box ("Filter events…", applied 120 ms after typing stops) matching title, place, bound folder and start time.
- Events listed by start time under day headings ("YYYY-MM-DD · Wkd"). Each: the time range or "all day", title ("(no title)"), place.
- **Bind button**: shows the bound folder, or the folder read from the title (styled as a guess), or "Bind folder…". Tooltips: "Bound to <dest> - click to change"; "Read from the title: <reason> / Already suggesting clips. Click to change, or ✓ to lock it in."; "Bind this event to a destination folder to generate suggestions". Clicking opens the folder picker titled "Bind “<title>” to folder" (with **Clear** when already bound). Choosing a folder binds it; Clear unbinds. Sent to `api/bindings`; then suggestions are re-read (`api/state/meta?lean=1`) if the answer did not carry them. Failures: "Binding failed: <reason>", "Could not refresh suggestions: <reason>".
- **✓** next to a guessed folder (tooltip "Confirm <dest> as a real binding"): binds it.
- "<n> suggested" link (tooltip "Select the <n> suggested clips"): clears the text, camera, date, kind, status, source folder and event filters, selects the event's unassigned suggested clips, scrolls to the first and says "<n> clips selected - drag them onto a folder, or press Accept suggestions."
- Empty: "No events match the filter." or "No calendar events loaded."

## Info tab and the clip details dialog (source: app.js)

- Tab "Info", header "Clip info" (with "<n> selected" when several). Redrawn when opened, because it goes stale while hidden.
- Nothing selected: "Select a clip to see its details."
- Several selected: Selected (<n> clips), Total size, Assigned (<n> of <m>), Kinds ("video × 3, audio × 1").
- One selected:
  - Stem, Kind, Camera, Recorded ("unknown"), Duration, Size and file count.
  - "Where it is": Root, Folder ("(root)"), the main file's full path, and buttons **Show in source**, **Show in destinations** (when assigned or suggested; tooltip the folder, "(suggested)" when only suggested) and **Open in Explorer**.
  - The ledger's copies (see Ledger) and the ingest copies (see Ingest).
  - A coverage warning when its assigned interview folder is short: "⚠ <folder> has no <gaps>" with clip, camera and sound counts.
  - "Sorting": Assignment ("unassigned", "in place - <folder>", or the folder), Structure, Suggestion ("<dest> (<confidence>)", "none" when also unassigned), "From event" or "Heard" (the summary), Timing ("recorded during the event" or "<n> min outside it", not for audio suggestions), Why.
  - "Also possible": each alternative's folder, "<summary> · also within the hour window | same day · <n> min off", and **Use this instead** (assigns the clip there).
  - "Heard on the audio": each recognised name with its episodes, "(two episodes - not guessed)", "(part of the name only)", and a quote with its second; up to four self-introductions ("said: <name>" with the quote); then "Scanned <n> of <m> min."
  - "Media": "Reading…" then the server's technical read (`api/mediainfo/<id>`, kept for the visit): Container, Duration, Bit rate (kbps), Video codec and profile, Resolution, Frame rate (and average when different), Pixel format and bit depth, Colour (space, transfer, primaries), Frames, Audio codec, channels and layout, Sample rate and bit depth; "no media streams"; or the error text. An answer for a clip no longer shown is discarded.
  - "Files" (when the clip has more than one file): each file's role, path and size; the full list is fetched if the page only had the main file.
- **Clip details dialog** (double-click a card, or "Clip info" in the right-click menu), titled with the clip name: Stem, Kind / camera, Recorded, Duration, Size, Source (root\folder), Assignment ("unassigned", "in place (<folder>)", or "<dest>  (<structure>)"), Suggestion ("<summary> → <dest> (<confidence>)" or "none"), Clip id, the sequence folder when it is an image sequence, the files list (completed from the server), the ledger's copies, and **Close**.

## Right-click menu on a clip (source: app.js)

- Right-clicking a card selects it (if it was not selected) and opens a menu at the pointer, pulled back inside the window. Right-clicking anywhere else in the page keeps the browser's own menu.
- The menu closes on any mouse press outside it, on any scroll, on window resize, on the window losing focus, and on Escape.
- Items:
  - **Show in source** (hint: its source folder): opens the Source tree down to the clip's folder, filters to that folder, keeps the clip selected, scrolls to it, flashes the row, and says "<n> clip(s) in <folder>". For a clip in the destination: warning "That clip is in the destination, not a source folder." and its folder is shown in Destinations. A side button ↗ opens the folder in Explorer.
  - **Show in destinations** (hint: the assigned folder, or "<folder>  (already there)" for a card clip the destination already holds, or "<folder>  (suggested)", or "nowhere yet" and disabled).
  - "Also suggested": **Assign to <folder>** for each alternative (hint "<dest>  ·  <summary>, <n> min off"), with a ⇥ side button that shows that folder in Destinations.
  - "Rolling at the same time": up to six source folders where another camera (or the same camera on another card) recorded within this clip's span widened by 30 minutes at each end. Other cameras first, then the biggest. Each: "<camera> · <n> clip(s)  HH:MM–HH:MM", hint "<folder>  ·  <n> already placed in <folder>" or "none placed yet". Choosing it shows and selects exactly those clips ("<camera> at the same time"); ↗ opens the folder in Explorer.
  - **Transcript & who is talking** (audio clips only): opens the Audio tab. Hint: "looks like <name> (<confidence>)", "sounds like …" when the evidence disagrees, "transcribed, nobody recognised" or "not transcribed yet".
  - **Open in Explorer** ("Reveal this file on disk"): sends `api/reveal`; "Opened in Explorer" when the server says it did; failure "Could not open it: <reason>". This opens Explorer on the server's computer.
  - **Clip info**: the clip details dialog.
- "Showing" a set of clips (here and elsewhere) clears every filter, selects them, scrolls to the first and toasts "<n> clip(s) selected - <label>".

## Move dialog: planning, dry run and moving on the server (source: app.js)

- **Move…** in the header. With clips selected, it plans only the selected clips that have an assignment; if none of them has one: warning "None of the selected clips has a destination" and nothing else. With nothing selected it plans every assigned clip. The button is disabled while the plan is being made.
- Sends `api/moves/plan`. Failure: "Export failed: <reason>".
- Dialog title "Move <n> selected clip(s)" or "Move every assigned clip", 680 px. Shows: Entries (files/folders to move), Folders to create, Total bytes, Destination root.
- Warnings shown when present:
  - "⚠ <n> assigned clip(s) are no longer in the scan and were LEFT OUT of the plan. Rescan, then re-assign them." with up to 200 "name → dest" lines.
  - "ℹ <n> already at the destination, identical · <n> staged twice - left out of the plan, nothing to move. The source copies are redundant; delete them when you are ready." with up to 200 "source = destination" lines each.
  - "⚠ <n> collision(s): these destinations already exist. The mover treats collisions as failures - resolve them before executing." with up to 500 paths.
  - Otherwise, if the dry run is clean: "✓ Dry run clean: every source is where the plan says, at the size it says, and no destination is taken."
  - "⚠ The dry run found <n> problem(s). Nothing can be moved until they are fixed." with up to 300 problems.
- Buttons: **Close** and **Move <size>**. Move is enabled only when the dry run is clean, there is at least one file to move or folder to create, and the person is a dashboard administrator; otherwise, when there is something to move, the dialog says "Moving footage needs a dashboard admin."
- Pressing Move: the button disables, a progress bar and "Moving…" appear; the page starts the move (`api/moves/<id>/execute`) and asks for progress every 700 ms (`api/moves/<id>`), showing "<done> of <total> · <size>". When done: "✓ Moved <n> item(s), <size> · <n> source folder(s) now empty (left in place). Verified at the destination. A rescan is running." plus a toast "Moved <n> item(s)", and the whole library, the trees and the grid are reloaded. Otherwise: "⚠ <refusal, reason, first verify problem, or state> - nothing was deleted or overwritten." Errors are shown the same way.

## Rescan (source: app.js)

- **Rescan** in the header (ignored while one is running; disabled during it). Shows "Scanning…" in the header, starts `api/scan`, then every 700 ms asks `api/scan/status` and shows "Scanning… <n> clips" until it stops running (or the status cannot be read, or one hour has passed).
- Afterwards it reloads the library and the destination tree and says "Scan complete - <n> clips · <size>". If the scan adopted footage moved outside the app (re-keyed, adopted, fulfilled or folder moves): warning "Moved outside the app: <server's text>". Failure: "Scan failed: <reason>".

## Settings sheet (source: app.js, index.html)

- A side sheet titled "Settings" with a ✕ close button, over a dimmed backdrop. Opened by the header's gear (which toggles it). Closed by ✕, by clicking the backdrop, or by Escape when no dialog is open. Focus returns to whatever had it before.
- Its only section is **Drives** (see the Ledger section). Hidden entirely until the server has a ledger.

## Dropping files from Explorer (source: app.js)

- Dragging real files from the operating system over the page highlights the page as a drop target (not while dragging clips or folders inside the page, and dialogs handle their own drops).
- On drop, the page first makes sure the destination's clips are loaded, then matches each dropped file against the library by file name (case-insensitive, and the folder name of an image sequence), using the exact byte size to decide when the name appears more than once.
  - Dropped on a Destinations folder: the matched clips are assigned there ("<n> clip(s) → <dest>") and selected.
  - Dropped anywhere else: the matched clips are shown and selected ("<n> clip(s) selected - dropped from Explorer" or "<n> files dropped from Explorer").
  - A name that matches several clips with none of the same size: warning "“<name>” matches <n> clips and none is the same size - showing all of them."
  - Not found: "“<name>” is not in the library." or "<n> of those files are not in the library." followed by "Add the folder they live in with ＋ folder in the Source pane, then Rescan."

## Panes, tabs and what the browser remembers (source: app.js)

- **Splitters** between the panes (tooltip "Drag to resize"): the Source pane between 150 and 560 px, the right panel between 200 and 640 px; defaults 270 and 320 px from the stylesheet. Widths are remembered (`fs.panes`). When the Source pane is hidden the Clips pane takes its column.
- **Right panel tabs**: Destinations, Events, Info, Audio, Missing, Cards. The last tab opened is remembered (`fs.tab`) and reopened on the next visit (Destinations is the default). Opening Missing loads the destination's clips if needed; opening Cards loads the card tracker; opening Audio activates it.
- Remembered in the browser: layout (`fs.layout`), thumbnail size (`fs.zoom`), sort field (`fs.sortBy`, the direction is not remembered), Sound (`fs.sound`), last tab, pane widths, Source pane hidden. Filters, selection and the search are not remembered.

## Keyboard and mouse shortcuts (source: app.js, grid.js, util.js, index.html)

- **Ctrl/Cmd+F**: focus and select the search box (anywhere, even while typing).
- **Ctrl/Cmd+= or +**: bigger thumbnails; **Ctrl/Cmd+- or _**: smaller (anywhere, overriding the browser zoom).
- The following only when not typing in a box and no dialog is open:
  - **Ctrl/Cmd+A**: select every clip in the current view.
  - **F2**: rename the active Destinations folder (if it is a real folder).
  - **Escape**: clear the selection and stop any preview. In the card (ingest) view with nothing selected, Escape leaves the card view instead.
  - **[** / **]** (no modifiers, with a selection): previous / next suggestion for the selected clips.
  - **Delete** or **Backspace** (with a selection): unassign the selected clips.
- **Escape** also closes the topmost dialog, the right-click menu and the Settings sheet.
- The status line at the bottom (desktop only) reads "> SORT" (or "> COPY", in cyan, while the open card view's banner shows a copy running; a copy running with the card view closed still reads SORT) with a blinking caret, "click · ctrl+click · shift+click · drag box", "drag onto a destination folder to assign", and "[ ] suggestion  Ctrl F search  Ctrl + Ctrl − size".
- **Clear filters** resets: search, camera, date, kind, status, location, Where and drive, source folder, destination folder, event, and "All clips"; the trees and grid are redrawn.

## Errors at start-up (source: app.js)

- If the first load fails: an error toast "The clips did not load: <reason>" for 20 seconds, and the centre shows the failed state with Try again.
- After the grid is drawn and painted, the page loads the destination tree, draws both trees, the Events and Missing tabs, then starts the Ingest part (card polling and `#ingest/<id>` links), the Ledger part, the card tracker and the Audio tab, and finally the 15-second refresh.

## Cards in readers: where a clip is, and whether it is backed up (source: ingest.js)

- **Location** of a clip: "card" whenever it belongs to a live card, otherwise what the server says: "staging", "final" or "other" (shown as "Elsewhere").
- **Backed up** means a second copy exists somewhere that survives a card wipe:
  - a clip already in the final destination is its own backup;
  - a clip on a card is backed up if a copy is in staging or in the final destination (verified or not), or if the ledger's verdict says it is safe (a numeric copy count above zero, state "ok", and not "only on the card" or "only on a laptop");
  - a clip in staging is backed up only if a copy is in the final destination.
- The **Location** filter list shows counts: "Card (<n>)", "Staging (<n>)", "Final (<n>)".

## Cards in the Source pane (source: ingest.js, app.js)

- Each live card (not dismissed) is a row under its computer's Cards dropdown: 💾, "<drive> · <card name or volume label> · <camera or kind>" (the computer name is left off because the dropdown names it), a state pill, counts "<n> · <size>", and a ✕ button.
- State pills: "detected" and "scanning…" (waiting), "ready" (also for planned), "done ✓", "error", "ejected", "dismissed", and while copying "copying <n>% · verify" with a mini progress bar and the speed ("<n> MB/s", one decimal under 10 MB/s).
- A health pill when the card has problems: "⚠ <n> damaged · <n> bad copies" (red) or "⚠ <n> to check" (amber), with a tooltip explaining each: "Clips on this card are damaged. Image the whole card before you format it.", "Copies came out damaged although the card is fine. Copy them again before you format the card.", "Clips on this card were not closed normally by the camera. Check them before you format the card."
- A "which card?" pill (tooltip "Formatted since it was last named: open it and say which card it is") on a card whose serial nobody has named since its last format, unless it is ejected or was marked "Not one of ours".
- Row tooltip: drive, label, "serial <serial>", "<kind> · <n> clips · <size>", and the error if any.
- Clicking the row opens the card view (below). ✕ (tooltip "Take this card off the list (nothing is copied or deleted)") dismisses it.
- **Closed cards** (dismissed but still in a reader) are listed dimmed with a "closed" pill and **Show again** (tooltip "Put this card back on the list. Its clips come back unassigned."), which sends `api/ingest/restore`, re-reads the card list and the library; failure "Could not bring that card back".

## The card view and its banner (source: ingest.js)

- Opening a card: filters the grid to that card's clips, clears the status, search, destination and location filters, sets the address to `#ingest/<card id>`, and shows a banner above the grid. Opening `#ingest/<id>` directly (or going back/forward to it) opens that card; an address without it leaves the card view. Leaving clears the card filter and the address.
- **Banner** heading: "💾 Ingest · <computer> · <drive> · <card> · <camera>", with ✎ (tooltip "Not <card>? Say which card it is") when the card was named by a guess. Then "<n> clips · <size> · <n> backed up · <n> not backed up (amber when any) · <n> suggested · <n> assigned · <n> unassigned".
- Banner styling: copying, error, or done.
- The latest error (from the run or the card) is shown in red.
- Buttons:
  - **Retry** (only after a failed copy): plans again in the same mode; the fresh plan only carries what is still missing.
  - **Copy to destinations…**: opens the copy review for a copy into the final folders. Disabled while copying or scanning.
  - **Stage only…** (tooltip "Copy the card into the staging folder and sort it later"): the review for a copy into staging. Disabled while copying or scanning.
  - **Rescan**: re-reads the card (`api/ingest/rescan`), "Rescanning the card…"; disabled while copying; failure "Could not rescan that card".
  - **Dismiss** (tooltip "Take this card off the list (nothing is copied or deleted)").
  - **✕** (tooltip "Leave the ingest view").
- **Which card is this?** block (for a card needing a name, or when ✎ was pressed): "Which card is this?" (or "Which card is this, if not <card>?") and a reason: "Probably <card>: the crew recorded it on the day this footage was shot.", "Formatted since it was last named. <n> card(s) fit(s) its type and size.", or "None of the cards it could be is free; pick from the rest." One button per likely card (the probable one highlighted, the current one disabled; tooltip the reasons or "no record of it on these days"), and a list "another…" / "pick a card…" of the unlikely cards (tooltip "Cards it is unlikely to be: the wrong type or size, or already in a reader"). Choosing one sends `api/cards/serial` and says "<drive> is <card> until its next format" (failure "Could not name the card: <reason>"). **Not one of ours** (tooltip "A borrowed card: stop asking for this insertion") stops asking for this insertion (remembered only for this page visit), or **Cancel** when renaming.
- **Health blocks**:
  - Copies damaged though the card is fine: "⚠ <n> copy/copies came out damaged|wrong although the card is fine. Do not format the card." with "The post-copy check read the copies back and found damage the card does not have. Delete those copies and copy them again; they do not count as backed up."
  - Damaged clips on the card: "⚠ <n> damaged clip(s) on this card. Do not format it." with "Copying and verifying will not fix these: the copy will match the card exactly. While the card is unformatted the footage is usually still on it, so take a raw image of the whole card first, then recover from the image." When the card has a drive letter, a command line "Image the card (elevated PowerShell, in the footage-sorter folder): `powershell -ExecutionPolicy Bypass -File tools\image-card.ps1 -Drive <X:>`" with **Copy** (copies it to the clipboard: "Copied. Paste it into an elevated PowerShell in the footage-sorter folder"; if the clipboard is refused the command is shown in a warning toast for 15 seconds).
  - Clips not closed normally: "⚠ <n> clip(s) the camera did not close normally" with "Probably fine, but open them before you format the card."
  - Each block lists up to 8 clips (damaged first, then by name) with their problems, "…and <n> more", and **Select them** (selects those clips).
  - A clip's health tooltip lists each problem as "• <text>" and each copy problem as "• Copy: <text>".
- **Progress row** while copying or after an error: a bar (by bytes when known, else by clips) and "<n>% · copying|verifying · <n> MB/s · <time> left · <done>/<total> clips · <size> of <size> · verified <n> · <current file> · TeraCopy|built-in copier · TeraCopy <state>", a **Details** button and a **Cancel** button.
- **Copy progress dialog** (Details): the live bar and line, "Copying|Verifying <file>", "Copier: TeraCopy|built-in (Python)", then one row per destination folder with its own bar, "<done>/<total> · verified <n>" and "<n> failed", then each error "<clip> - <message>". Buttons **Close** and **Cancel copy**. The live part keeps updating while it is open.
- **Cancel** sends `api/ingest/cancel`: "Cancelling - the file being copied finishes first"; failure "Could not cancel".

## Copy review dialog (source: ingest.js)

- Opened by Copy to destinations… or Stage only…; first asks the server for a plan (`api/ingest/plan` with the card and the mode). Failure: "Could not plan the copy: <reason>". The button is disabled while planning.
- Title "Copy card <drive> (<kind> <camera>) to destinations" or "Stage card <drive> (…)". 820 px wide.
- Lead: "<n> clips · <size> → <n> folders on <drive>". Space line: "Needs <size> · <free> free on <drive>", "free space unknown on <drive>", or "… - not enough room, free some space first" (red).
- Copy to destinations only:
  - "<n> clip(s) is/are already backed up elsewhere - no destination needed, nothing to copy."
  - "⚠ <n> clip(s) has/have no destination and is/are not backed up anywhere" / "Wipe the card without dealing with it/them and the footage is gone." with a choice: **Stage them to <staging folder>** (default) or **Skip them - leave them on the card**, and **Go back and assign** (closes, opens the card view filtered to Unsorted and selects those clips).
- One row per destination folder: a tick box, the destination plus the time folder the copy will create (in bold), "(merges into <folder>)" when it joins an existing one, "<n> clips · <size>", and coloured dots counting each clip state: "new", "partial", "present (skip)", "already elsewhere (off)", "differs".
  - By default only "new" and "partial" clips are ticked; a folder's box is ticked if any of its clips is. Ticking a folder ticks its new and partial clips only (never what is already there); unticking clears all of them and dims the row.
  - **clips ▸** expands the clip list, by default showing only new and partial clips; a toggle switches between **Missing only** and **All**. Each clip line: tick box, name, size, state, size difference ("+<size>" or "−<size>", the negative in red), " clock?" when the timestamp looks wrong, "⚠ damaged" / "⚠ check" with the health tooltip.
  - **Link folder instead** on a clip "already elsewhere" that is final inside another CC Sync project (tooltip "ccsync will share <path> into this project at its original path - no second copy, no relink."): sends `api/ingest/link-folder`; the button becomes "Linked ✓" or "Already linked ✓" and "Folder linked: <path> now shares into this project."; failure "Could not link: <reason>".
  - Row warnings "⚠ <text>".
- Plan warnings: "⚠ <n> warning(s)" with up to 12 lines; "⚠ <n> name collision(s) - TeraCopy will rename or skip" with up to 60 names.
- **Back up proxies too** tick box: off unless the plan says otherwise.
- Buttons: **Cancel**, and **Copy <n> clip(s) · <size>** (counts the ticked clips; disabled when there is not enough room or nothing is ticked).
- Pressing Copy sends `api/ingest/run` (plan id, ticked clips, what to do with unassigned clips, proxies). A refusal shows the server's message and closes; if the server says the plan is out of date (409), a fresh review opens. On success the dialog closes, the plan's per-clip verdicts are remembered for the grid cards and the Info tab, the banner shows "queued" progress, and status polling starts.

## Card polling and notifications (source: ingest.js)

- **Card list** is fetched every 5 seconds (`api/ingest/sessions`) while the tab is visible. The rows are redrawn only when the list changed; the library is reloaded when a card finishes scanning, finishes or fails a copy, is ejected or dismissed, disappears, or when new thumbnails arrived for its clips from the companion.
- **Copy status** for the open card is fetched every 1 second while it is queued, copying or verifying (`api/ingest/status`), one request at a time; old or stray answers are ignored. It stops when the copy ends.
- **Toasts**, once per card per state (cards the first load already showed are not announced):
  - New card: "Card <drive> detected - <n> clips" for 8 seconds with **Go** (opens the card view); its computer and Cards dropdown open.
  - Card became ready: "Card <drive> - <n> clips · <size>" with **Go**.
  - Card error: "Card <drive> - <error or 'could not be read'>".
  - Card removed: "Card <drive> was removed".
  - A copy finished: "<drive> - <n> clip(s) copied and verified", "<drive> - <n> clips copied, <n> unverified", "<drive> - copy cancelled", or "<drive> - <error or 'the copy failed'>"; when the card was not on screen and no status is available, "<drive> - copy finished". Each finished copy is announced once, and the library is reloaded.
- **Push channel**: the page keeps a server-sent event stream open (`api/ingest/events`; the browser reconnects on its own). This is what tells the server that a sorter tab is already open, so the tray does not open another one. When the server says "open" for a card: the card list is fetched, the card's computer opens, and the page opens that card's view; if another card's view is already open it stays there and shows the "Card <drive> detected" toast with **Go** instead.
- **Dismissing a card** asks the browser's own confirm box first when: a copy is running ("A copy is running on <drive>. Dismiss anyway?"); copies came out damaged ("<n> copies from <drive> came out damaged although the card is fine. The card is the only good copy: copy again before you format it. Dismiss it from the list anyway?"); clips are damaged ("<n> clip(s) on <drive> is/are damaged, and so is/are its/their copy/copies. Do not format this card until you have taken a raw image of it (or you have decided those clips are lost). Dismiss it from the list anyway?"). Sends `api/ingest/dismiss`; the card moves to the closed list at once; failure "Could not dismiss that card".
- **Copies section** in the Info tab (for every clip): where it is ("Card", "Staging", "Final", "Elsewhere") and "backed up (<backup>)", "backed up (the ledger: copies elsewhere)" or "not backed up"; the last copy plan's verdict ("Destination check: <state> · <time folder> · ±<size>", tooltip the existing path); then the catalog's record of every copy (`api/catalog/<key>`, kept for the visit): path, "present" or "absent", "✓ verified <date>" or "unverified", tooltip the root, how it got there and when it was last seen. Messages: "Not in the catalog yet - it gets a key when it is copied.", "Reading the catalog…", "not in the catalog", "catalog unavailable", "No copies recorded."
- **Ghost leaves** in the Destinations tree (drawn by the card part): under an open folder, the time folders that the current assignments imply, with "<n> clips · <size>", "(existing, will merge)" for one that already exists, and a tooltip with the path, "merges into <folder>", camera and day, and "not created yet - the copy makes it". Clicking one selects its clips ("<n> clip(s) heading for <name>"). Nothing can be dropped on a ghost leaf.

## The ledger: when it is there, and when it is not (source: ledger.js)

- On start (after `whoami`), the page asks the server for the ledger's drives (`api/ledger/volumes`). If the server answers "not found", "method not allowed" or "not implemented", or gives no usable answer, the ledger is **absent** and every ledger control stays hidden: the Settings gear, the Where filter and its drive list, the "Fewest copies" sort, the Not-at-home and Backups chips, the missing-folders banner and the Backups panel. If the person had "Fewest copies" remembered as their sort, it falls back to Time and any Where filter is cleared.
- With the ledger present, all of the above appear. The "Copies on drives" section appears in the Info tab and in the clip details dialog.
- Background work (only while the tab is visible): a tick every 30 seconds, or every 2 seconds while the Backups panel is open. Each tick reads the running activity (`api/ledger/activity`); re-reads the drives when the Settings sheet is open and they are more than about 30 seconds old; re-reads the missing-folder questions about every 60 seconds and the not-at-home digest about every 5 minutes. If the drives never loaded, each tick tries again. When the tab becomes visible again, the activity is read at once.
- **Ledger changes**: the server sends a version number with the activity and the drives. When it changes (or, with no version, when running work drops to nothing), the page drops everything it cached from the ledger (per-clip copies, per-drive clip lists), re-reads the drives, questions and not-at-home digest, re-reads the clip rows conditionally, redraws the Info tab and re-applies a Where filter. Without a version, the clip rows are re-checked conditionally every 30 seconds instead.
- The Backups chip is also redrawn every 4 seconds from the card copies the page already knows about.

## Copy-count badge on each clip (source: ledger.js, grid.js)

- When a clip row carries the ledger's copy summary, the card shows "<n>×" (number of drives holding the main file), coloured by state:
  - **bad**: only on a laptop, or only on a card;
  - **warn**: the server marks it not backed up (or, for older servers without the numeric verdict, it is not at home, not marked backed up and has fewer than 2 copies);
  - otherwise **ok**.
- Tooltip: "<n> copy/copies · home · cloud proxy · only on a laptop | only on a card | not backed up".
- A row without the summary shows no badge.

## Where filter and Fewest-copies sort (source: ledger.js, index.html)

- **Where** list ("Copies anywhere" by default):
  - **On a drive…** / **Not on a drive…**: a second list appears, "Choose a drive…", listing every tracked drive as "<name> · <kind>". With no drive chosen nothing is filtered. The chosen drive's clip list is fetched in pages of 5,000 (at most 60 pages) from `api/ledger/volume/<id>/clips`; while it loads nothing matches and the centre says "Listing the clips on <drive>"; when the ledger changes, the old list keeps being used until the new one arrives. Failure: "Could not list the clips on <drive>: <reason>".
  - **2 or more copies**, **3 or more copies**, **4 or more copies**.
  - **Only on a laptop**.
  - **Not at home** (not on the home NAS).
  - **No cloud proxy**: clips whose proxy is not in the cloud (from the server's verdict, or, for older servers, by comparing with the cloud drive's own clip list).
  - Clips without a copy summary never match any Where filter except "Not on a drive".
- **Fewest copies** sort: by copy count, unknown counts last.

## Not at home chip and dialog (source: ledger.js)

- Header chip, shown when the digest (`api/ledger/not-home`) counts any clip not on the home NAS: "⌂ <n> not at home", or, when some live only on a laptop, a warning-styled "⚠ <n> only on a laptop". Tooltip: "<n> clips exist only on a laptop. <n> clips are not on the home NAS. Click for the list." (On the phone only the glyph and number show.)
- Clicking re-reads the digest and opens "Not at home": "<n> clips are not on the home NAS · <size>." then groups "Only on a laptop · <n>" (warning), "On our drives, not on the NAS · <n>", "On other people's drives · <n>", and any other category the server names. Each row: the folder ("(root)"), "at <where> · <n> file(s) · <size>". Empty: the server's text or "Everything is at home." Buttons **Drives…** (opens the Settings sheet at Drives) and **Close**.

## "Where did these go?" banner (source: ledger.js)

- Above the grid, when the ledger has open questions about folders that vanished from a drive: "<n> folder(s) went missing", "Where did these go?", and **Answer** / **Hide** to expand or collapse the list.
- Each question: the folder ("(the drive root)"), "on <drive> · <n> file(s) · <size> · gone since <date>".
- Administrators only, the answers:
  - "Moved to…" list of the other drives (the server's suggestion preselected and marked "(suggested)") and **Moved there** (no drive chosen: "Choose where it went first.");
  - **Moved within this drive**;
  - **Deleted on purpose** (after the browser confirm "Mark <n> file(s) in <folder> as deleted on purpose? They stop counting as copies.");
  - **Plug it in and rescan** (tooltip "Leave it open until the drive is scanned again").
  - Each sends `api/ledger/questions/<id>`. Success toast: "<what> - thanks." or "<what> - recorded; the rest waits for the next scan."; then the ledger is treated as changed. Failure: "Could not record that: <reason>".
- Non-administrators see the questions without the answer controls.

## Backups chip and panel (source: ledger.js)

- Header chip with a spinner, shown while anything is running: "<n> backup(s)" and the combined speed. It counts card copies the page knows (queued, copying, verifying), every running item the server reports, and the cloud upload when running. Tooltip lists their titles. Clicking toggles the **Backups in progress** panel; the Settings sheet's **Backups** button also toggles it (closing the sheet first).
- The panel closes with its ✕, a click anywhere outside it (dialogs excepted), or Escape when no dialog is open. While open it refreshes every 2 seconds (it does not redraw while a time is being typed in it).
- Each running item: a kind chip ("card copy", or the server's job kind), a title ("<drive> · <card>" for card copies), a percentage, a bar (an animated "busy" bar when no percentage is known), and "<phase> · <speed> · <eta> left · <done>/<total> files · <size> of <size>", plus the file in hand. Times over a day and a half read "<n.n> days".
- **Cloud upload · Hetzner** block, when the server has a cloud backup configured: a state chip ("running", or the last state: failed/error in red, ok/done in green), progress while running, "last snapshot <ago>", "<n> files, <size> · <size> added last run", "box <used> of <total> used", "kept: <n> hourly, <n> daily, <n> weekly, <n> monthly", "<n> errors", "last error: <text>", followed by the cloud controls (below).
- "Nothing is running." when nothing is; "No card, drive or scan copies are running." when only the cloud block shows.

## Cloud backup controls (source: ledger.js)

- Shown in the Backups panel and in Settings > Drives under "Cloud" as "Nightly cloud backup".
- Status lines: "Running (<reason>) since <date time>"; or "Last run: <reason> · started <date time> · took <duration> · OK|FAIL · <text>"; or "Last status: <state> · <time> · <text>"; or "No run recorded yet." Then "Nightly backup is off." or "Next run: <date time>". Then "Ledger backup: <date time> · OK|FAIL · <error>|unknown" or "Ledger backup: none yet". Lines containing FAIL are red.
- Schedule, for administrators when the sorter has a backup folder configured: a **Nightly at** switch and a time box (default 04:15), and **Save** (enabled only when something changed). Unsaved edits survive the 2-second redraw. Sends `api/ledger/cloud/schedule`: "Nightly cloud backup at <time>." or "Nightly cloud backup is off."; failure "Could not save the schedule: <reason>". Others read "Schedule: every night at <time>" or "off", and an administrator without a configured backup folder also reads "(the sorter has no backup folder configured, so it cannot change this)".
- **Run now** (administrators): disabled while running, already requested, or with no backup folder configured; tooltips "A backup is running already", "Already requested", "Ask the NAS to start a cloud backup now". Sends `api/ledger/cloud/run`: "Cloud backup requested. The NAS starts it within 10 minutes." and a chip "Starting within 10 minutes"; a conflict answer is a warning, other failures an error ("The cloud backup could not be started." by default).

## Settings > Drives (source: ledger.js, index.html)

- Header: "Drives", an amber badge counting new untracked drives (tooltip "New drives nobody has said are ours or not"), "<n> drive(s)", a sort list (Name, Last seen, Size, Files; remembered as `fs.driveSort`), **Backups** (toggles the Backups panel) and **↻** (tooltip "Ask the ledger again": re-reads drives, questions and the not-at-home digest).
- Opening the sheet reads the activity and the drives. "Loading…" until the ledger answers. "No drives reported yet." when there are none.
- **New drives · <n>** ("Plugged in somewhere and reported, but not tracked yet."), most recently seen first: name, "plugged in · <computer>" unless known to be unplugged, "<size> · on <computer> · seen <ago>", and for administrators **Track…**.
- Tracked drives grouped under "Home NAS", "Our drives", "Laptops", "Cloud", "Client drives", "Cards", "Unknown", each "· <n>". Each drive row:
  - a kind chip (NAS, ours, laptop, cloud, client, card, unknown), the name, "plugged in · <computer>", "not tracked" (except NAS and cloud), "scanning" or "scan <state>", "auto backup";
  - "<free> free of <size>"; "<n> masters · <n> proxies · <n> audio" or "<n> files";
  - "seen on <computer> <ago> · scanned <ago>" or "never scanned" · owner;
  - "<n> file(s) not found by the last scan"; "<n> open question(s)" (warning);
  - for auto-backup drives, what the automatic backup last did: "Backs up to the NAS by itself when plugged in at home" (nothing yet), "Backing up to the NAS: <n> files · <size> (more after this)", "Backed up <n> files · <size> <ago>", "Everything on it is at home", "Waiting: this computer is away from home", "Backs up when it is plugged in at home", "Automatic backup failed: <reason>".
  - Tooltip: the drive id, "roots: <folders or (whole drive)>", "Click to show the clips with a copy here".
  - Clicking the row, Enter or Space on it, or **Show clips** sets the Where filter to "On a drive" for it (a second click clears it, and the button reads "Showing" while active), toasts "Clips with a copy on <drive>" for 2.2 seconds, closes the sheet, and on a phone goes to Clips.
  - Administrators: **Scan** (tooltip "Rescan this drive now"; `api/ledger/volumes/<id>/scan`; "Scan of <drive> queued." or "started."; failure "Could not scan <drive>: <reason>" for 8 seconds) and, except for NAS and cloud drives, **Edit**.
- Under Cloud, the "Nightly cloud backup" controls when a cloud backup is configured (even with no cloud drive listed).
- **Watched folders · <n>**, with **＋ Watch a folder** for administrators. Empty hint: "A watched folder is rescanned whenever its drive is visible, for example the field backup on a laptop." Each: its name or folder ("(whole drive)"), "visible now" / "not visible", "<drive> / <folder> · <computer>", "every <n> min · last scan <ago>" or "not scanned yet", and the automatic-backup line. Administrators: **Auto backup: on|off** (tooltip "Copy what is in this folder and not on the NAS yet into the NAS staging folder, by itself, when this computer is at home"; `api/ledger/watch/<id>/auto`; "<folder> now backs up to the NAS by itself, at home." or "<folder>: automatic backup off."; failure "Could not change it: <reason>"), **Scan now** (`api/ledger/watch/<id>/scan`; "Scan of <folder> queued."), **Remove** (browser confirm "Stop watching <folder>? Its copies stay in the ledger."; `DELETE api/ledger/watch/<id>`; "No longer watching <folder>."; failure "Could not remove it: <reason>").
- Time-ago wording everywhere here: "just now" under a minute, "<n> min ago" under an hour, "<n> h ago" under 48 hours, then "<n> d ago".
- The automatic-backup lines come from `api/ledger/auto-backup` (none when the server lacks it).

## Track / Edit a drive dialog (source: ledger.js)

- Title "Track <drive>" or "Edit <drive>", 460 px. A line with the drive id, computer and size. Fields: **Name** ("a name you will recognise"), **Kind** (Ours (counts as a backup), Client drive, Laptop, Card, Other), **Owner** ("whose is it?"), **Folders to scan** ("blank = the whole drive; one folder per line"; backslashes become slashes, leading and trailing slashes removed), **Notes**, and **Back up to the NAS automatically (when plugged in at home)**.
- Buttons: **Cancel**; when editing, **Untrack** (browser confirm "Stop tracking <drive>? Its recorded copies stay in the ledger."); **Track and scan** (new) or **Save** (editing). Sent as `PUT api/ledger/volumes/<id>`. Toasts: "<drive> is tracked now.", "<drive> saved.", "<drive> is no longer tracked (its history stays)."; a new drive is then scanned unless the server already queued it. Failure "Could not save: <reason>" for 8 seconds. Automatic backup is only kept on while the drive is tracked.

## Watch a folder dialog (source: ledger.js)

- Title "Watch a folder", 460 px. **Machine** ("Choose a machine…", every computer that reported a drive), **Drive** (that computer's drives with sizes), **Folder** ("folder on that drive, e.g. FieldBackup"; a drive letter and slashes are stripped), **Name** (optional), **Rescan every (minutes)** (default 60, at least 5). "No machine has reported a drive yet." when none.
- **Watch it**: no drive chosen gives "Choose the drive first."; sends `api/ledger/watch`; "Watching <name or folder or 'the whole drive'>."; failure "Could not add the folder: <reason>". **Cancel**.

## Copies on drives section (source: ledger.js)

- In the Info tab and the clip details dialog, when the ledger is present: "Copies on drives", a summary badge "<n>×" with its description, "Reading the ledger…", then the server's answer for that clip (`api/ledger/clip/<id>`, kept until the clip rows change).
- Grouped as "Masters · <n>", "Proxies · <n>", "Audio · <n>". Each copy: kind chip, drive name, a chip "missing since <date>" (red), "plugged in · <computer>" (green), or "last seen <ago> · <computer>" / "not plugged in" (not for cloud), the path, and "verified in full" / "verified quickly" / the verification text, "recorded <date>", and "a question is open: where did it go?" for a missing copy with an open question.
- Messages: "The ledger has not seen this clip.", "Ledger: <error>", "No copies recorded yet."

## Calendar chip and Calendar dialog (source: calendar.js)

- The header chip is redrawn on every state load and every 60 seconds (the 60-second redraw only updates the "ago" text; it fetches nothing). States:
  - Google connected and healthy: green "● Google · synced <n> min ago" ("synced just now", "<n> h ago", "<n> d ago", "never synced"). Tooltip: the account, "<n> events · every <n> min" (default 15), "Click for calendar settings".
  - Google revoked or failing: red "● Google · reconnect". Tooltip: the error or "Google revoked the connection", "Click to reconnect". Each distinct failure also shows once an error toast "Calendar: <error>" for 9 seconds with a **Fix** button that opens the Calendar dialog.
  - Reading a downloaded .ics export: "○ iCal export (manual)". Tooltip: "Reading the .ics export you downloaded. Connect Google Calendar to have it refresh itself."
  - Nothing: "Connect Google Calendar". Tooltip: "No calendar - suggestions have nothing to go on. Click to connect."
- Clicking the chip opens the **Calendar** dialog (620 px):
  - **Not configured on the server**: "Not configured", "Google Calendar is not set up on this machine yet. It takes one file:" `data\google-oauth.json`, then three steps (Google Cloud Console → APIs & Services → Credentials → Create OAuth client ID → Desktop app; enable the Google Calendar API for that project; download the JSON and save it as data\google-oauth.json, then reload this page). Only **Close**.
  - Otherwise a status line: "Connected as <account> · synced <ago> · <n> events", "Reading the iCal export - not connected to Google", or "Not connected", with " · <error>" in red when there is one.
  - **Calendars**: when connected, "Reading your calendars…" then a tick box per calendar on the account (`api/google/calendars`), the primary one marked "primary" and ticked by default when none was chosen before. "Not connected yet - press Connect." on an authorisation failure; the error text or "Could not list the calendars" otherwise; "No calendars on that account."; when not connected "Press Connect to sign in with Google."
  - **Sync**: "Refresh every" 5, 15, 30 or 60 minutes (default 15), and "From date" (tooltip "Ignore anything scheduled before this day").
  - Buttons:
    - **Close**.
    - **Disconnect**: a confirmation dialog "Disconnect Google Calendar" ("The sorter will stop refreshing events. Bindings and assignments are untouched.") with **Cancel** / **Disconnect**; sends `api/google/disconnect`; failure "Could not disconnect".
    - **Sync now**: `api/google/sync`, "Synced - <n> events", then the whole library is reloaded; failure shown in the dialog ("Sync failed").
    - **Connect**: checks `api/google/status` (not configured: "data\google-oauth.json is missing - see the setup note."), opens `api/google/auth` in a new browser tab for the Google sign-in, says "Waiting for Google in the other tab…", and checks every 2 seconds for up to 3 minutes. Connected: "Connected to Google Calendar as <account>" and the calendar list loads. Timeout: "Gave up waiting. If the tab is still open, finish there and press Connect again." A second press while waiting does nothing.
    - **Save**: sends the ticked calendars, the refresh interval and the from-date to `api/settings`, then forces a calendar refresh (`api/events?refresh=1`), reloads the library and says "Calendar settings saved - <n> events". The dialog stays open. Failure shown in the dialog ("Could not save that").
- **Events tab ↻**: if Google is connected it syncs Google, otherwise it forces a refresh of the events; then reloads the library and says "Calendar refreshed - <n> events"; failure "Could not refresh the calendar". Disabled while working.

## Cards tab: the crew's card tracker (source: cards.js)

- Tab "Cards" (tooltip "Which cards the crew used on which day (thecreatorsclub.co/cards)") with a red badge counting cards marked not backed up (hidden at zero). Header "Card use", a ↻ button (tooltip "Pull the crew's records from thecreatorsclub.co/cards now"; asks `api/cards?refresh=1`), and "synced <ago>" or "not configured" (tooltip: the tracker's address).
- Loaded once at start and each time the tab is opened (`api/cards`). "Loading…" the first time; "Could not load: <error>"; "Nothing loaded yet."
- **Not configured** note: "settings.cards.url is empty." when a token exists, otherwise "No token: put the CARDS_TOKEN of the Pages project in data/cards-token.json as {"token":"…"} (or set FS_CARDS_TOKEN).", plus "The card list still shows; usage days need the token."
- **Sync error** note: "Sync: <error>" and "Showing the copy from <ago>."
- **The fleet strip**: one chip per active card, "<card> ✓" (green, backed up), "✗" (red, not backed up) or "?" (unknown). Tooltip: "<card>: backed up | NOT backed up | state unknown", "last used <day>", "changed <ago> by <who>", "serial <serials>", "Click to mark it used|backed up". Clicking asks the browser confirm "Mark <card> as backed up|used (not backed up) on thecreatorsclub.co/cards?", then sends `api/cards/backup`: "<card> marked <state>."; failure "Could not flip <card>: <reason>" for 9 seconds. "No cards known yet - sync once the tracker is live." Hint: "Click a card to flip it. Red = footage on it is not backed up yet; a finished card copy flips it green by itself once its serial is mapped."
- **Card serials seen by ingest, not yet mapped**: each serial with label, kind, "<n> clips" and "shot <days>", and a list "which <kind> card?" / "which card?" of every card (cards of another kind are dimmed). Choosing one sends `api/cards/serial`: "<serial> is <card> from now on." (or "<serial> unmapped."); failure "Could not map <serial>: <reason>".
- **Footage ingested with no card record**: up to 40 rows of day, card, "<n> clips → <folders>", then "… and <n> more".
- **Recorded card use**, one block per day ("Nothing recorded yet." or "Usage needs the token." when empty): the cards used that day (not clickable; tooltip "<card> recorded <local date time> by <who>" and "backed up since" / "still not backed up" / "state unknown"), each with "<n> clips ingested → <folders>" or " (staging)"; then that day's calendar events (only the main ones; others summarised as "+ <n> all-day / recurring event(s)" with their titles in the tooltip), each with its time, title (click to filter the grid to that event; click again to clear), "★ likely" (tooltip "The only shoot on the calendar that day with a known destination") or "☆ likely" (tooltip "The only timed event that day - no destination known for it"), and its folder (bound, or read from the title). "Nothing on the calendar that day."

## Audio tab: whose interview is on each recording (source: audio.js)

- Tab "Audio" (tooltip "Whose interview is on each recording: transcript, evidence, assign") with a badge counting recordings filed where the audio disagrees plus unfiled recordings that have a likely match (red when any disagree; hidden at zero). Header "Audio", ↻ (tooltip "Re-read the transcripts and re-score": reloads the library and the audio report), and a sub-line.
- Opening the tab reads the audio report (`api/audio`, reused for 15 seconds); while the tab is visible it is re-read every 30 seconds. Failure: "Audio report unavailable: <reason>" for 6 seconds.
- **Worklist** (nothing selected, or several selected: then only the selected audio clips): sub-line "<n> of <m> audio clips heard · <n> Vault transcripts". Sections, each "· <n>":
  - "Filed where the audio disagrees" ("The folder each of these sits in is contradicted by an identical filed copy or by the transcript itself.");
  - "Not filed yet";
  - "Filed, nothing contradicts it".
  - Within each: highest-scoring match first, then by name. Each row: name, duration, "transcribing…" / "names only" / "<n>% heard", "Filed in <folder>" or "Assigned to <folder>", and "Sounds like" (disagreeing) or "Looks like" <name> with a confidence chip and the evidence types joined by " + ", or "No match in the Vault, no name heard". Clicking a row shows and selects that clip and shows the detail.
  - Empty: "Nothing needs a look." or "No transcripts yet. Run  python tools\whisper-names.py --full  and they appear here." Footer "Last transcriber write: <time> (<model>)".
- **Detail** (one audio clip selected; fetched from `api/audio/<id>` and re-fetched when its summary changes): "Reading…", then:
  - Clip ("<name> · <duration> · <size>"), Heard ("<scanned> of <duration> · <language> · <model>", "names only (no full transcript yet)", "not yet"), Assigned / Filed in ("unassigned · suggested <folder>").
  - An audio player of the clip's proxy (loads only when played; its position and play state survive a redraw of the same clip).
  - Buttons: **Assign to…** (folder picker), **Unassign** (when really assigned), **Show in destinations** (when assigned or suggested), **Open in Explorer**.
  - A warning when it disagrees: "⚠ Filed under <folder>, but this sounds like <name>" / "From: <evidence>. Assign it below to queue the re-file."
  - "Who this could be": each candidate with a colour swatch, its name, confidence, evidence types, its folder, and **Assign** (or "✓ here", disabled, tooltip "Already the assignment"), or **Pick folder…** when no folder carries the name (tooltip "No folder on P: carries this name - choose one"). Each piece of evidence is quoted with a "▶ <time>" button that plays the recording from there. Empty: "Nothing matched: no Vault transcript, no roster name, nobody introduced themselves. Read the transcript below." or "Waiting for the transcript."
  - "Who talks when" (when there are at least two five-minute windows and some have a match): a strip of cells sized by length, coloured by the best match (stronger match, more opaque), tooltip "<from>–<to>: <name> (<n>%)" or "no match"; clicking a cell plays from there; a legend of names.
  - "Transcript": a "Find in transcript…" box (applied 120 ms after typing stops; the text is kept between clips) and every line with its time button (click to play from there). Lines that evidence points at are highlighted; matches are marked. At most 4,000 lines are drawn. Messages: "No transcript for this clip yet.", "Nothing in the transcript says that.", "The transcript is empty - silence, or room tone.", "Transcribed up to <time> of <time> so far."
  - "Could not read this clip: <reason>".
- Nothing here assigns on its own.

## Download selected clips to this computer (source: download.js, share/dl.js, download.css)

- A **Download…** button is added to the toolbar after Assign to… (tooltip "Download the selected clips into a folder on this computer"), enabled whenever clips are selected. Available to everyone who can open the page.
- If a download is already running: warning "A download is already running. Wait for it to finish, or cancel it first."
- The **Download <n> clip(s)** dialog (560 px): "Working out what to download…", then the server's plan (`api/download/plan` with the clip ids and whether to include proxies): "<n> file(s), <size>, from <n> clip(s)." and "Left out: <n> clip(s) is/are still on a card in a reader, not on the server; <n> file(s) is/are no longer on the server; <n> clip(s) could not be found." Failure: "The download could not be planned: <reason>".
  - **Also download the proxies** tick box (off by default); changing it re-plans.
  - In a browser with a folder picker (Chrome or Edge on a computer): "You will be asked for a folder on this computer. Choose or make a folder INSIDE Documents, Downloads or a drive: the browser refuses those themselves (it says the folder contains system files). The files are saved into it with their folders kept. Keep this tab open while it runs. Files already in the folder are not downloaded again." and **Choose a folder and download** (disabled until the plan arrives and while it has no files).
  - Without a folder picker (phones, other browsers): "This browser cannot save into a folder you pick: use Chrome or Edge on a computer for that. Here, click each file to download it." and up to 500 plain download links "<path>  (<size>)"; the folder button is hidden.
  - **Cancel**.
- Choosing a folder: the picker opens in Downloads (it remembers the last folder chosen for this purpose). Closing it does nothing; an error gives "The folder could not be opened: <reason>". Then the dialog closes and a **download panel** stays in the bottom-right corner:
  - "Downloading to <folder>", a bar, "<done> of <total> files, <size> of <size>, <speed>/s, <eta>" ("Paused. " in front while paused), and the names of the files in hand or "Connection lost, trying again". **Pause** / **Resume** and **Cancel**.
  - When it ends: "Done. All <n> files are in <folder> (<n> were already there)." (green), or "<n> of <m> files are in <folder>. <k> could not be downloaded:" with up to 50 "<path>: <reason>" lines, or "Your sign-in ran out. Sign in again in another tab, then download again into the same folder to carry on.", or "Stopped. Download again into the same folder to carry on from here." A ✕ then removes the panel.
- How the download behaves (same engine as the public link page):
  - Three files at a time. Each file's folder structure is kept; characters Windows forbids in a name (`< > : " \ | ? *` and control characters) become "_", and trailing dots and spaces are removed.
  - A file already in the folder at the full size is left alone and counted as "already there". A different file of the same name (without the marker below) is never touched: that file fails with "A different file with this name is already in the folder. It was left alone."
  - While a file downloads, a `<name>.downloading` marker file sits beside it. A file with a marker is continued from where it stopped on the next run, using a byte-range request; if the server sends the whole file instead, that file starts over. The marker is deleted when the file is complete; nothing else is ever deleted.
  - Data is written to disk in pieces of 4 MB; what arrived before a fault is kept.
  - A dropped connection is retried after 2, 5, 10, 20, 30, 60, 60 and 60 seconds while nothing new arrives (any progress resets the count); after that the file fails with "The connection kept dropping. Run the download again to carry on from here." A stream that keeps ending early fails with "The server kept ending the file early."
  - The server answering "unauthorised" stops the whole run as "sign-in ran out". "Forbidden", "not found", "conflict" or "gone" fail that one file with the server's message or "The server no longer has this file." Other errors: "the server answered <status>" (retried).
  - While running, closing or leaving the tab asks the browser's "leave this page?" question, and the screen is kept awake where the browser allows it.
  - Speed is measured over the last 10 seconds and the panel updates every half second. Time left reads "<n> s left" under 90 seconds, "<n> min left" under 90 minutes, then "<h> h <m> min left".
  - Only one download runs at a time per page.

## Share folder links (source: download.js)

- A **Share folder…** button (tooltip "Make a link for a folder that anyone you send it to can download from") is added after Download…, visible only to administrators.
- The folder it shares: the active (clicked) folder in the Destinations tree if any, otherwise the source folder picked in the Source tree (not a whole source root, not a card). Right-clicking a Destinations folder (administrators only) opens the dialog for that folder directly, instead of the browser's menu.
- **Share a folder** dialog (720 px):
  - With a folder: "A link for <folder>", "Anyone who has the link can download everything in this folder, without an account, until it runs out or you switch it off.", a name box ("Name shown to the person (optional)", at most 120 characters), a validity list (7, 14 (default), 30, 90 days, or No end date) and **Make the link** (sends `api/shares`; failure "The link could not be made: <reason>").
  - Without a folder: "To make a link, click a folder in the Source or Destinations tree first, then press Share folder. Right-clicking a destination folder works too."
  - A made link is shown as copyable rows: "For anyone" (the public address, when the server has a public base address) and "On the team network" (or just "Link" when there is no public address, with the note "This address only opens for people on the team network (Tailscale). A public address has not been set up on this server."). Each has **Copy** ("Link copied"; falls back to selecting the text and the old copy command). Clicking the box selects its text.
  - **Links**: every link ever made (`api/shares`): its name or folder, "<folder>  ·  by <who>  ·  opened <n> time(s)  ·  until <date>" / "no end date", or "switched off" / "ran out" (dimmed). Active links have **Show link** (shows its addresses above) and **Switch off** (`api/shares/<id>/revoke`: "Link switched off"; failure "Could not switch it off: <reason>"). "Loading…", "No links yet.", "The links could not be loaded: <reason>".
  - **Close**.

## The public link page (source: share/index.html, share/share.js, share/dl.js, share/share.css, share/gone.html)

- The page someone opens from a share link, at `share/<token>/`, with no sign-in. It loads only files under `share/` (its own stylesheet with system fonts, the download engine and its script). Search engines are told not to index it and no referrer is sent.
- A link that is unknown, switched off or expired gets a separate page titled "Link not available": "This link is not available" / "It may have been switched off or have run out. Ask whoever sent it to you for a new one."
- Layout: "Footage shared with you", the title (the link's name, or "Footage"; also the tab title), and "<n> file(s), <size>. This link works until <long date>. Only the first <n> files are shown" (the last part when the server truncated the list).
- If the list fails: "This link is not available" with the same advice (when the server says not found), or "The folder could not be loaded" with "<reason>. Reload the page to try again."
- Files are grouped by folder ("Top folder" for loose files) in collapsible groups showing "<n> file(s), <size>". Groups are open unless there are more than 12 groups or the group has more than 60 files. Each group has a tick box that ticks or unticks all its files; each file has a tick box, a direct download link (its name) and its size. **Any folder named "proxy" (at any depth) starts unticked; everything else starts ticked.**
- "<n> of <m> files ticked, <size>".
- **Download into a folder…** (only where the browser has a folder picker; disabled when nothing is ticked or while running) with the hint: "Download into a folder: pick a folder on your computer and the ticked files are saved into it, keeping their folders. Choose or make a folder inside Documents, Downloads or a drive: the browser refuses those themselves (it says the folder contains system files). Keep this tab open until it finishes. If it stops, press the button again and pick the same folder: only what is missing is fetched. Proxy folders start unticked." It uses the same download engine as the sorter page (three at a time, resume, markers, retries).
- **Download everything as one zip**: always shown, a plain download of `zip` (all files, regardless of the ticks). Without a folder picker the hint reads "This browser cannot save into a folder you pick. Open this link in Chrome or Edge on a computer for that. Here you can click a file to download it, or take everything as one zip (best for smaller folders)."
- Progress block: bar, "<done> of <total> files, <size> of <size>, <speed>/s, <eta>" ("Paused. " first while paused), the files in hand or "Connection lost, trying again", **Pause**/**Resume** and **Cancel** while running. Endings: "Done. All <n> files are in the folder (<n> were already there)." (green), "<n> of <m> files are in the folder. <k> could not be downloaded:" plus each failure, "This link stopped working during the download. Ask whoever sent it for a new one, then pick the same folder to carry on.", "Stopped. Press Download into a folder and pick the same folder to carry on from here." A folder-picker error: "The folder could not be opened: <reason>".
- Sizes on this page use one decimal under 100 (for example "4.2 GB"), unlike the sorter page.

## Phone layout: what is shown, hidden and enlarged (source: style.css, phone.js)

- Header: only the mark (the "FOOTAGE SORTER" word is hidden), the back link as "‹" only, the clip-count total only (its "clips" label also disappears when a Not-at-home or Backups chip is showing), the Not-at-home and Backups chips with their long labels and speed dropped, the Settings gear, and **Move…**. The Calendar chip and **Rescan** are hidden on the phone.
- Toolbar: the search box, **Filters**, and the Status buttons are always there. Behind Filters: Camera, Date, Pick a day, Kind, Location, Where, drive, Sort by, sort direction, Clear filters, thumbnail size and Structure (the open toolbar scrolls when taller than 52% of the screen). **Accept suggestions** shows (full width) only when it is enabled. With a selection, the selection counter, **Assign to…** and **Unassign** appear.
- **Not available on the phone** (hidden by the layout, with no other way to reach them there): the Sound toggle, the **Suggestions ▾** menu, **Download…**, **Share folder…**, the status line, Rescan, the Calendar chip and dialog, the Ctrl-key hints.
- One pane at a time (Source, Clips, or the right panel as "Folders", which still carries all six tabs), edge to edge, no splitters; the Source hide/show buttons are hidden.
- Touch sizes: buttons, list rows and tabs 44 px tall (small buttons 36 px), form fields 16 px text so the phone does not zoom. Any coarse pointer (also a touch laptop) gets 44 px controls and hides key hints on buttons.
- In the trees, the ＋, ✕ and ✎ row buttons are always visible on the phone (on the desktop ＋ and ✕ appear only while the pointer is over the row, and ✎ fades in on hover).
- Dialogs fill the width (up to 88% of the height); the Settings sheet is full-screen; toasts stretch across the bottom above the navigation bar; the Backups panel sits under the header across the width; the card banner and the missing-folders banner scroll within 40% / 55% of the screen.
- Gestures that rely on a mouse (hover preview, rubber-band selection, drag to assign, right-click menu, double-click) are not adapted for touch in the page's own code.

## How states are shown by colour and shape (source: style.css)

- Colours: red is the brand, the one main action (Move…), danger and panel titles; cyan is selection, focus, "live" and "go"; gold is a suggestion, a warning or a count wanting a look; green means synced or backed up and nothing else; purple marks what the audio tool heard.
- Clip card: a 4 px rail down the left edge, grey (unassigned), gold (suggested) or cyan (assigned); a cyan frame and glow when selected; half-transparent while dragged; a dashed gold outline at 55% opacity for a staged move. Camera chips have fixed colours for BMCC, A-CAM, B-CAM and FX3, cream for any other.
- Location dot on a card: red (on a card), gold (staging), green (final), grey (elsewhere); a green ring means a second copy exists; after a copy plan it takes the plan's state colour (present and elsewhere green, partial gold, differs purple).
- Suggestion badge: gold; dashed border when low confidence or when other events are in contention, dotted when inferred from an event title; purple when heard in the audio. Destination tag: a left border in the destination's own hue.
- Duplicate badge: solid red (the copy to keep) or an outlined "S" (the smaller copy). Health badge: red (damaged or bad copy) or gold (check). Copy-count badge: outline when fine, gold fill for "warn", red fill for "bad".
- Trees: the folder the grid is filtered to is cyan-tinted with a cyan edge; a drop target gets a cyan outline; a planned folder name is cyan italic; a suggestion-only folder gold italic; a placeholder folder dim italic; a mirrored folder dimmed; a card row has a cyan edge; ghost leaves are italic at 70%; a revealed folder flashes cyan for 1.2 seconds.
- Toasts have a coloured edge: cyan (success), gold (warning), red (error).
- Dropping files from Explorer covers the page with a cyan wash reading "Drop to find these clips in the library".
- With the operating system's "reduce motion" setting, animations and transitions are switched off.

## Development mock (source: dev-mock.js, index.html)

- `DEV ONLY`. Loaded only when the page URL contains `?mock=` (any value), and active only when it is exactly `?mock=1`. With any other value the early requests are skipped but nothing is mocked, so the page loads normally afterwards.
- It replaces every `api/...` request with made-up data: `&n=<count>` clips (default 3,000, between 10 and 40,000), `&lat=<ms>` fake delay per request (default 12 ms). It includes a card in a reader with 12 clips, a destination tree with Chinese and English names, 10 or so calendar events, two bound events driving suggestions (half the clips with an alternative), five drives, a new drive, a watched folder, a missing-folder question, a not-at-home digest, two running copies and a running cloud upload, a clean move plan, a scan that runs in about three seconds, a copy run that advances two clips per status poll and ends "done" with 1 unverified, and a connected Google calendar.
- The tab title becomes "Footage Sorter [MOCK <n>]" and a gold "MOCK data" total is added to the header.
- Proxies always answer "not found" in the mock, so hover previews fall back to filmstrips (which the mock does not serve either).

## Looks redundant or overlapping

- Two "copies" sections in the Info tab for the same clip: "Copies" (the catalog, `api/catalog/<key>`, from the card part) and "Copies on drives" (the ledger, `api/ledger/clip/<id>`). The clip dialog shows only the ledger one. Two separate verdicts of "backed up" feed them (the clip's `backup` field versus the ledger's flags), merged by the "ledger says safe" rule.
- The Info tab and the clip details dialog show largely the same facts in two layouts.
- Naming a card from its serial exists twice: the "Which card is this?" block in the card banner and the "Card serials seen by ingest, not yet mapped" list in the Cards tab, both sending `api/cards/serial`.
- Duplicate filenames are reported in three places: the duplicate badge on each card, the Missing tab's "Same file twice in one folder", and the Move dialog's collisions and "staged twice" notes.
- Calendar events are listed in four places: the Events tab, search hit cards, the Cards tab's days, and the Pick a day dialog (plus "Shoots with no footage" in Missing). Filtering the grid to an event is possible from hit cards and from the Cards tab, but not from the Events tab, which instead offers "<n> suggested" to select.
- Card-copy progress is shown in four places: the mini bar on the card's Source row, the card banner's progress row, the Copy progress dialog, and the Backups panel.
- Ways to assign: drag onto a folder, double-click a folder, Assign to… picker, the suggestion badge, Accept suggestions, the Suggestions ▾ menu, [ / ], the right-click "Assign to <alternative>", Info tab "Use this instead", Audio tab "Assign" / "Pick folder…" / "Assign to…", dropping Explorer files on a folder.
- Many independent timers: 15 s rows and destination tree, 5 s card list, 1 s copy status, 30 s (or 2 s) ledger tick that can also re-read the rows, 4 s Backups chip redraw, 30 s audio report, 60 s calendar chip, 700 ms scan and move polls. The rows can be re-read by the 15 s poll, the ledger tick, ledger version changes, card state changes and scans.
- Three "time ago" helpers (calendar.js and cards.js carry identical copies, ledger.js its own wording) and two size formatters with different rounding (util.js and share/dl.js).
- Two-part loading (meta plus rows, each with "not modified" checks), a lean source-only start with a lazily fetched destination, and a fallback to the single `api/state`: three loading paths for one library.
- The development mock answers routes the page never calls (`api/export-moveplan`, `api/ingest/stage`, `api/ingest/sessions/<id>`, `api/catalog`) and serves "202 then 200" thumbnails that the grid can no longer receive (pictures load through plain image tags, which the mock cannot intercept).
- Some style rules have no element that uses them (for example `.loc-tag`, `.count`, `.btn-lg`, `.dos`, `.bar-title`).
- Customer-specific strings in the page: "FF5 sheet", "npm run roster -- "…FF5 - FF5.csv"", "Cloud upload · Hetzner", "thecreatorsclub.co/cards", "P:" in hints and placeholders.

## Claims the code does not back

- grid.js's opening comment describes a "thumbnail queue with 202 retry/backoff"; the code loads each picture with a plain image tag and has no 202 handling (its own later comment says "there is no 202 polling").
- dev-mock.js says it fabricates "202-then-200 thumbnail behaviour"; the grid never fetches pictures through `fetch`, so that behaviour is never seen in the page.
- dev-mock.js says it is active "ONLY when the page URL contains ?mock=1"; index.html also skips the early requests and loads the mock script for any `?mock=` value (the mock itself then stays inactive).
- index.html's comment speaks of "the two big requests" before "the nine scripts"; it starts five requests, and ten scripts follow (eleven with phone.js).
- download.js's header says Share folder works for "the folder that is selected in either tree"; in the Source tree it only works for a folder below a source root, not for a source root itself or a card.

## Could not determine

- Whether a long press on a phone opens the page's right-click menu (the page listens for the browser's context-menu event, which some phone browsers fire on long press), and whether drag-to-assign and double-tap work on touch browsers.
- What the server's small thumbnail (`?s=s`) actually is; the code comment says 160 px.
- Whether the Cards tab's hint is true that "a finished card copy flips it green by itself once its serial is mapped" (that happens on the server, outside this part).
- Whether the server refuses non-administrators for the routes the page hides from them (Move, Share folder, drive tracking, cloud schedule, question answers); the page only hides or disables the controls.
- Exactly which share links the server serves "Link not available" for (unknown, switched off or expired); the page itself cannot tell them apart.
- Whether the browser's "leave this page?" prompt during a download appears in every browser; the code asks for it in the standard way.
