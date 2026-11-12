# Timeline Cards editor: every screen, panel, control and setting; playback; what works offline

Terms used throughout:
- **Cut list**: the edit being worked on (a "project" on the server), an ordered list of items.
- **Card / cut**: one item of the cut list, a stretch (in point to out point) of one interview clip, with its transcript words.
- **Gap**: a stretch of black/silence on the timeline, treated as its own item.
- **Lane**: the horizontal timeline strip along the bottom on desktop.
- **Shelf / staged**: a holding area of cards not yet on the timeline.
- **Section**: a run of cards under a `§` heading marker; **note**: a free-text marker row.
- **Playhead / head**: the current timeline position.
- **Pad**: a game controller.

## Page shell and start-up
(source: index.html, main.ts, shell.ts)

- The page title is "Timeline Cards"; theme colour `#070403`; dark colour scheme only (the page declares `color-scheme: dark`).
- Before the script runs, the page already draws a placeholder of the app: a header with the CC mark and "TIMELINE CARDS" (a link to `./`), a breadcrumb reading "Opening the cut list", an empty side rail, a "Cards" panel with the message "Opening the editor" / "Reading the cut list saved on this device, then the server's.", an empty inspector, an empty dock and a status line reading "> LOADING" with a blinking caret. It is replaced when the views mount.
- With JavaScript off the page says "The editor needs JavaScript to run."
- On start the editor boots its store, audio engine and service worker, mounts the views, then the keyboard/pad/pointer input, then (with features) the feature platform.
- If start-up fails: it first asks `GET /api/session`; on a 401 it navigates to `/login?next=<current path and query>` (so a LAN server that wants a login sends the person there and back). Otherwise it shows an alert paragraph "The editor could not start: <error>".
- If the feature platform fails to start: a warning toast "The features did not start. The editor still edits." The editor itself still works.
- If the projects feature fails to mount: a warning toast "Not available in this window: projects. The editor still edits."
- One broken feature never stops the others or the editor; each failure is recorded by name and reported.
- Keyboard: **Ctrl+K / Cmd+K** (no Alt, no Shift) puts the caret in the transcript search box and selects its text, but only when that box exists and is visible.
- Feature keys answered by the shell (the bindings themselves live in the input layer, outside this part): "search every transcript" opens search; "ask Claude" toggles the chat; "Send to Resolve" sends. When the feature has not started each says so in a warning toast: "Search did not start: <reason>" / "Search is not ready yet.", "The chat did not start: <reason>" / "The chat is not ready yet.", "Resolve did not start: <reason>" / "Send to Resolve is not ready yet."; a Send that fails toasts its error message.
- The pad's "LT + Menu" toggles the video window when the video feature is mounted; otherwise the views say there is none.
- Opening a cut's transcript (Q / Enter on a card) goes to the transcripts feature's "show this cut".
- When a workspace tab becomes visible and it is the staged (shelf) tab, the shelf redraws then (it skips drawing while hidden).
- Key hints drawn on buttons come only from the real keyboard binding table: Play, Split, Delete (remove), Note, Undo, Redo, previous/next edit point, zoom in/out, Escape; Search always shows "Ctrl K"; Shortcuts shows "?". Stage, More, Edit, Zoom-to-cut, Place, In edge, Out edge, Join, Not needed, Open and Done show no key hint (because the real keys differ from the original design's).
- The shortcuts sheet's list is updated whenever a feature registers or removes a key, so every bound key is listed.
- **Font warming (desktop only)**: 4 seconds after start, when the browser is idle (idle callback with a 2 s timeout, or a 200 ms timer fallback), every not-yet-loaded web font subset (Noto Sans TC ships as about 200 subsets) is loaded in one batch, so a card with new Chinese characters does not stutter later. On a touch device (coarse pointer) nothing is preloaded; fonts load on demand to save data.

## Header tools group
(source: features.ts)

- The header holds a "Tools" group where features draw their launcher buttons, placed before the Undo button (or before Send if there is no Undo).
- A "Tools" icon-only button (grip icon) sits in front of it. On a phone the group is a drop-down under that button: pressing toggles it open and focuses the first tool; choosing an item, tapping outside, or Esc closes it (Esc returns focus to the Tools button). The drop-down opens 4 px below the header.
- The header's red "Send to Resolve" button opens the Resolve feature's Send flow; if that feature is not available it fails with the feature's failure reason or "the Resolve panel is not available yet".
- Every compacted header launcher (transcripts, chat, tools, gap notes, Send, the search opener) gets a hover tip below it with its name and key (Send's tip is end-aligned). Tips are re-added whenever a feature redraws its button.

## What works offline (the service worker)
(source: sw.js)

- Caches: "tc-shell-v2" (app shell) and "tc-data-v1" (last project data). On install it pre-caches `./`, `./index.html`, `./main.js`, `./styles/main.css` (fetched bypassing the HTTP cache; one missing file does not stop the rest) and takes over immediately.
- On activation it deletes every other cache except ones whose name starts with `tc-keep` (cut lists kept on the device are never cleared by a new worker), and takes control of open pages.
- Network timeout: 4 seconds. A request that has not answered in 4 s is treated as offline and served from the cache.
- Never handled (always go to the network, never cached): any non-GET request, any other origin, the `/sync` socket, `/media/audio*` and `/media/pcm*`.
- `GET /api/project*`, `/media/sources*`, `/media/peaks*`: network first, the last good answer kept; offline, the last kept answer for that exact URL is served. (This is a fallback; the main offline copy and pending edits are kept on the device in the browser database, outside this part.)
- Any other `/api/*` or `/media/*` request: not cached, so it fails offline.
- Page navigations: network first, the last good page kept; offline, the cached page, or the cached `index.html` for any page address.
- `/assets/*` (fonts and hashed files): cache first, fetched and kept on a miss.
- Everything else (scripts, stylesheet): network first with cache fallback, so a new build is picked up at once.
- A redirect (for example to the login page) or a non-OK answer is never cached.

## Screen layout and modes
(source: views/app.ts, views/ctx.ts, views/index.ts)

- The views draw two screens: the **editor screen** (header, section chips, main panels, dock with the lane, status line, phone tab bar, menu host) and the **edit view** (a full screen for trimming one cut). Exactly one is visible: the edit view shows when the view mode is "edit" and a cut is selected.
- Form factors, decided by media queries and re-rendered when they change:
  - **Phone**: width at most 700 px.
  - **Landscape phone**: height at most 500 px and width at least 701 px. Treated like a phone for tabs, menus and the back gesture.
  - **Desk**: everything else.
- On the desk every panel shows at once; on a phone and a landscape phone one tab shows at a time (Cards, Lane, Edit, Staged, Find).
- On the desk only, the transport (play controls, timecode, zoom) sits inside the lane's bar row to save height (switched by the workspace media query, see "Workspace"); on phones it stays at the foot below the lane.
- Renders are batched to one per animation frame. While only the playhead or the lane's scroll/zoom changed (desk only, not in the edit view), a reduced redraw updates just the lane, transport, play bar, status line and the playing card's lit word; when the playhead crosses into another cut, the cards list, sections rail and chips update one frame later.
- At the first idle moment after a cut list is drawn (idle callback with a 3 s timeout, or 500 ms), the playing-state drawing is rehearsed off screen once so the first Play does not stutter. Nothing visible changes.
- **Android app shell**: when playback starts or stops, the page tells the native shell (`CardsNative.duck(true/false)`) so other audio is ducked during playback. Without the shell nothing happens.

## Header (editor screen)
(source: views/app.ts, views/chrome.ts)

- **Brand**: the CC mark and "TIMELINE CARDS"; clicking it switches the view mode back to Cards (it does not navigate).
- **Breadcrumb**: the episode name (from an option, else the first segment of the cut list key), "/", then the cut list's title. The title is the list's project name, else its title, else the key's last segment without `.cut.md`, else "No cut list open". A leading episode name is dropped, a trailing " (Claude)" is dropped, " - " shows as " – ". The full title is the hover text.
- **Search box** (desk only): placeholder "Search the cards", key hint "Ctrl K". Typing filters live (see "Find"). Esc in a non-empty box clears it.
- **Undo / Redo** icon buttons (desk only), disabled when there is nothing to undo/redo.
- **Send to Resolve** (desk only): a red primary "Send to Resolve" when a cut list is open and the Resolve hook exists; "Sending" with a spinner while it runs; a second press meanwhile is ignored. Without the hook (list open) a quiet label "Resolve: not connected" whose hover says "Send to Resolve: not in this build". With no list open nothing is drawn.
  - Success toast "Sent to Resolve."; failure (error level) "Send to Resolve failed: <message>"; closing the Resolve panel without sending reports nothing.
- **Sync pill** (marked phone-only in the markup, but the desk stylesheet shows it too, in place of the hidden status line; hidden with no list open): dot + short label, long label as hover/accessible name:
  - offline: "Offline" / "Offline, N queued"; short "Offline" / "Offline N"; gold.
  - connecting with edits queued: shown as offline (gold).
  - connecting with nothing queued: "Connecting"; cyan.
  - syncing: "Sending N" or "Syncing"; short "N queued" or "Syncing"; cyan.
  - signed out: "Signed out[, N queued]: sign in again"; short "Signed out"; gold.
  - other error: "Not saved" ("Error" with no message); red.
  - live: "Saving N" (short "N queued", cyan) or "Saved".
  - The short count is capped at "99+".
- **Phone header buttons**: Undo (icon) and More (opens the header More sheet).

## Status line (bottom of the editor screen)
(source: views/chrome.ts)

- A prompt "> MODE" with a blinking caret. Modes: EDIT (live), SYNC (connecting/syncing), OFFLINE, ERROR, TRIM (edge drag), PLACE (holding a staged card), PLAY (playing).
- Context text, first match wins:
  - Edge drag: "<speaker> ^ref, in/out edge ±N.NN s", "Snapped to a frame", "Release to trim, Esc cancels".
  - Holding a staged card: "Holding <speaker>, N.N s", "Drop between two cuts, Esc cancels".
  - Offline (or connecting with edits queued): "Edits are kept on this device".
  - Connecting: "Connecting to the server"; syncing: "Sending offline edits".
  - Error: the error sentence, else "The server refused an edit".
  - Playing: "<speaker> ^ref, X s of Y s", "Space pauses, J K L shuttle".
  - Gap selected: "Gap selected, N s[, M items in all]", "Drag an edge to size it, Del takes it out".
  - Cut selected: "<speaker> ^ref selected, N s[, M cuts in all]".
  - No list: "No cut list open".
- Right side: "rev N" (the server's confirmed version; hover "The server's confirmed version of this cut list"), a dot with "Synced, nothing queued" (live, nothing pending) or the long sync label, and a "Shortcuts" button (only when a shortcuts sheet exists).
- It stops announcing to screen readers while playing.
- On the desk the stylesheet folds the status line away and the transport carries the Shortcuts button instead (see "Styles").

## Empty, loading and error states
(source: views/chrome.ts, views/app.ts)

- **No list open** (panel "Empty", aside "no cut list open"): "Open a cut list to start editing" / "Pick a .cut.md from an episode's Script Docs/Cuts folder, or build one from an ordered canvas." (+ " Recent lists:").
  - "Open cut list" (primary): the open hook; disabled with tip "Opening is not wired in this build" when absent.
  - "New from canvas": the hook; disabled with tip "Not wired in this build" when absent.
  - Recent lists: one button each (title, "rev N" when known); pressing opens it.
- **Loading** (a key is set, no project yet, not offline/error): "Opening <name>", cyan chip "connecting", "Reading the cut list and the edits kept on this device. Nothing you made offline is lost while this loads.", a disabled busy "Opening" button.
- No project while offline: the empty state.
- **Error**: with no project it replaces the screen; with a project it is an overlay over the cards (never a blank screen) until "Keep working" hides it for that message (a different message shows it again).
  - Signed out: "Your sign-in has expired.", gold chip "N edit(s) waiting" / "Nothing waiting", "Nothing is lost. Your N edits are kept on this device and sent once you are signed in. Sign in again, and the editor comes back here." Buttons "Sign in again" (to `/login?next=<this page>`) and "Keep working".
  - Not found (text contains "no cut list", "not found" or "no such"): red chip "Not found", "Check the name, or open another cut list. Nothing has been changed."
  - Otherwise: red chip "N edit(s) not saved" / "Not saved", "Nothing is lost. Your N edits are kept on this device. Try again, or keep working: edits are queued until the server answers." Buttons "Retry now" (disabled with tip "Reconnect is not wired in this build" without the hook) and "Keep working".
  - Messages from other layers get a capital first letter, " -- " becomes a dash, "no cut list X" becomes "no cut list called X".
- **Offline** is a standing warning toast, not a panel: "You are offline. Keep editing: N edit(s) is/are kept on this device." with "Retry now" (when the hook exists) and "Hide". Hidden stays hidden until the connection is no longer offline.
- An "Offline" panel builder ("You are offline. Keep editing.") exists. UNREACHABLE: nothing draws it.

## Toasts
(source: views/app.ts)

- One at a time; a new one replaces the old. Info (check icon for a successful edit, info icon for a neutral note), warn and error (alert icon).
- Lifetimes: with an action 9 s; a neutral info note of 48 characters or fewer 2.5 s; anything else 5 s; store notices of warn/error level 12 s.
- Every toast has Dismiss (x); dismissing a store notice dismisses it in the store. An action button runs and clears the toast.
- A successful edit started from the views shows a toast with an "Undo" action.
- The newest unseen store notice becomes the toast.
- On a portrait phone on the Cards tab the toast sits over the mini lane, not over the selected card's actions.

## Sections rail and section chips
(source: views/chrome.ts, views/app.ts, views/model.ts)

- **Sections rail** (desk, left, "Sections" with the count): one row per section with colour swatch, number ("1.1"; "§" for an unnumbered section heading; "◆" for a note heading; empty for the body before the first heading), name, length m:ss. The current section is marked.
- **Section chips** (a strip, used on phones): the same.
- Number and name come from a heading "1.1 - Name"; the body before any heading is named by the list title, else "Opening". Colour: the marker colour (16 names), Blue when absent or unknown.
- Pressing a section: selects its first cut, scrolls the lane to 1 s before it, scrolls the cards so the section is on top, closes the phone Find tab.
- "Current section": the selected item's, else the last pressed, else the one under the playhead, else the first.

## Cards panel (the cut as a reading surface)
(source: views/cards.ts, views/app.ts)

- Bar "Cards" (desk) with an aside: "placing ^ref", "playing <speaker> ^ref", "N in § 1.1, M in the cut", or "M in the cut".
- One group per section, with a sticky head: tag, name, "N cut(s), m:ss"; a real heading's head has hover "Drag onto another card to move this marker".
- Note rows in place: flag icon, "Section note." (the first note before a section's first cut, markdown and the "⚑ TRANSITION / FLAG 1.1 - TITLE" lead-in removed; hover "Click to read the whole note"), "Unmatched.", or "Note.". Clicking toggles the whole text.
- No sections: "This cut list has no cuts yet. Place a staged card, or add cuts from a transcript."
- **A cut's card**: speaker (person, else clip), "in → out" (m:ss.cc), gold chips for gain ("+2.0 dB"), "Fade in N.NN s", "Fade out N.NN s", a red "Delete again: N" countdown while armed, and the length (cyan while an edge drag changes it).
  - The words: the line in the interview's own script (any non-Latin script) leads; Latin lines beside it show under it as the English gloss. "No words yet" when empty. `==highlighted==` phrases are marked.
  - Colour = speaker colour: the written Resolve colour (15 names; "Brown" means Chocolate); a cut with none takes the colour most of that person's cuts carry; else a stable colour hashed from person or clip.
  - A note under the cut (flag); clicking it opens the note editor.
  - While playing, the word being spoken is underlined cyan from the clip's word timings (nothing between words); without timings a 6-character phrase steps through by proportion.
  - The **primary selected card** shows actions: "Play"/"Pause", "Split", "Stage", "Edges" (phone only, edit view), "More actions".
  - W opens/closes a card's full text.
- **A gap's card**: hatched, "Gap", "silence", length. Selected and primary: "Shorter" / "Longer" (0.5 s; Shift 5 s; tips "Half a second shorter (Shift: five)") and "Remove". Never below one frame.
- Only a changed item's card is redrawn.
- **Scrolling rules**:
  - Selection moved (not by click): scroll just enough to show the card and its action row.
  - A click selects without jumping, but brings the new action row into view.
  - Playback: when the head enters another card and playback follow is on, smooth-scroll to it just after the frame paints.
  - **Follow mode** (F held): the card being heard stays centred, playing or not; toasts "Follow on. The card being heard stays centred." / "Follow off." Off at the start of every session; never saved.
  - **Go to head** (F tap): centre the head's card once (smooth, corrected up to 5 times every 250 ms from 450 ms). "There is no playhead card to go to." when none.
  - Cards are kept clear of the pinned section head (its height + 28 px).

### Mouse and keyboard on the cards
(source: views/app.ts)

- Click: selects alone and, when not playing, moves the playhead to the cut's start; Shift+click range; Ctrl/Cmd+click toggle. The card takes keyboard focus.
- Double-click with a mouse (not a gap, not a button): the edit view.
- Mouse/pen drag (6 px threshold): re-order; a selected card carries the selection. A line shows the landing; the list auto-scrolls 14 px per move within 40 px of its edges. A drop above a section heading goes to the end of the previous section. A no-change drop does nothing. Release = one move (Undo toast). Esc cancels.
- Shift+drag: box select (label "N card(s)[ added]"); Ctrl/Cmd+Shift adds.
- Drag a section head or a note row onto a card: moves the marker in front of it (never after the last card); the lane shows the same landing. Toast "Moved <title>." / "Moved The note." with Undo. The body before the first heading cannot move.
- Drag a staged card over the list: a drop slot showing it appears in front of the card under the pointer (or at the end); dropping places it. Toast "Placed <speaker> ^ref in the cut." with Undo; it becomes selected.
- Focused card keys (no modifiers, not a gap): Enter or Q select and open its transcript; W full text; B selects and opens the edit view.
- Enter on a focused staged card: shows it in the inspector.
- Tab / Shift+Tab: walk the keyboard ports cards, lane, transcript panel when the focus is on a port or nowhere (on-screen ports only); inside a panel's controls Tab is the browser's.
- "?" toggles the shortcuts sheet from anywhere except text fields (editor screen).

### Touch on the cards (phone)
(source: views/app.ts)

- Two taps on one card within 450 ms lift it (with the selection if it is selected): 15 ms vibration, the cards marked, toast "Moving cut N[ and M more]. Scroll, then tap where it goes: the top half of a card puts it before, the bottom half after. Tap it again to cancel." with Cancel. A gap lifts the same way ("Moving the gap").
- While lifted, tapping a card's top half puts them before it, bottom half after; a tap between cards puts them before the next card down (or after the last). Tapping a lifted card cancels ("Move cancelled."); Esc cancels. Toast "Moved the cut." / "Moved the gap." / "Moved N cuts." with Undo; they become selected.
- A finger held still 550 ms on a card (not a control, not a gap): selects it and opens its transcript (12 ms vibration); more than 10 px movement or scroll cancels. The browser's long-press menu is suppressed on cards.
- On touch, two taps are never a double click (no edit view, no transcript).

### Notes under a cut
(source: views/app.ts, views/cards.ts)

- Opened by N, the menu's "Add a note"/"Edit the note", or clicking an existing note. Target: the given cut, else the selected, else the one under the head; none: "Select a cut to put a note under. Shift+N notes the gap before it." Selects it, brings a phone back to Cards, scrolls it into view.
- Box placeholder "A note under this cut. Enter saves, Esc cancels, empty removes it." Enter saves, Shift+Enter new line, Esc cancels, clicking away saves. A changed text toasts "Note saved." / "Note removed." with Undo. Typed text survives a redraw.

### Delete arming
(source: views/app.ts)

- First Delete (from the input layer) arms the selection for N seconds: toast "Press Delete again within N s to delete this cut / these N cuts [and a gap / M gaps]. It goes to the shelf; Ctrl+Z puts it back." Each armed card counts "Delete again: N" down each second.

## More menus
(source: views/chrome.ts, views/app.ts)

- From a card's "More actions" and the phone header's More. A bottom sheet with grab handle and scrim; first enabled item focused. Closed by Close (Esc hint), Esc, the scrim, a click outside, any item run, or the back gesture.
- Gap: "Move this gap" (lift), "Remove the gap".
- Cut: "Edit edges", "Add a note"/"Edit the note", "Zoom to cut", "Move this cut" (lift), "Add a 1 s gap before" or "Remove the gap before" (toasts "A 1 s gap went in. Drag its edge to size it." / "Gap removed. Undo puts it back."), "Remove from cut".
- Header extras: "Redo", "Send to Resolve" (or a quiet row with reason "Not in this build" / "Open a cut list first"), "Shortcuts" (hidden on touch screens).
- On touch, tapping a disabled control that has a reason toasts the reason.

## Shortcuts sheet
(source: views/chrome.ts, views/app.ts, shell.ts)

- Dialog "Shortcuts", "N actions"; rows of key caps and labels grouped by where they apply ("Anywhere" first for ungrouped; group headings only when there is more than "Anywhere"). The controller's map is appended as "Game controller" only after a controller has been seen in this window. Close button.
- Opened by "?", the Shortcuts buttons, the pad's Menu (toggles). With no rows, no Shortcuts button is drawn.

## Inspector (desk, "Selected cut" panel)
(source: views/inspector.ts, views/app.ts)

- Nothing selected: "Select a card to see its edges, gain and fades here. Drag an edge in the lane to trim it."
- **A cut**: "Selected cut" with ^ref (or id); speaker; clip (ellipsised, full on hover) "· § 1.1".
  - "Source in" / "Source out" steppers: one frame a press, Shift ten; typed as m:ss.cc, seconds or h:mm:ss (comma accepted as the decimal point); refused "That is not a time (m:ss.cc)."; cyan with delta while dragging.
  - "Length" (cyan while dragging; "+N.NN s new material" chip while extending).
  - "Gain": 0.5 dB a press, Shift 5 dB; typed "+2", "−1.5 dB"; refused "That is not a gain in dB.".
  - "Fade in" / "Fade out": 0.1 s a press, Shift 1 s, not below 0, not longer than the cut; typed "0.5", "0.5 s", "Off"; refused "That is not a fade in seconds.".
  - Field keys: Enter commits, Esc restores, Up/Down step (Shift ten); leaving a changed field commits. A redraw never discards a half-typed value.
  - Word preview; during a trim drag the words that would go are struck by proportion (Latin snaps to a space).
  - Buttons: "Zoom to cut", "Edit view", "Stage", "Remove".
- **A gap**: "Selected gap", "Silence at m:ss.cc · § N", "Length" stepper (0.5 s, Shift 5 s, at least one frame; refused "That is not a gap in seconds."), the hint "A gap plays as silence and exports as black. Drag it to move it; drag either edge to size it. It stays where you put it when the clips beside it move.", "Remove".
- **A staged card**: "Staged card", speaker, clip · in → out · category, words.
  - Interviewer question: "An interviewer question: reference only. Questions never go in the cut." No actions.
  - Otherwise: "Places after the selected cut, or drag it into the lane or the list.", "Place in cut", "Not needed" (filed under the "Not needed" category; "Filed under Not needed."), "Back to cut".
- **Zoom to cut**: the cut fills about 60% of the lane width, centred.

## Staged shelf (rail on the desk, Staged tab on a phone)
(source: views/shelf.ts, views/model.ts, views/app.ts)

- Shows the staged category named after the current section's heading ("Staged in 1.1"), else the plain shelf ("Staged"). A deleted cut is filed under its section's category.
- Each card: grip, words (or clip), short speaker name (the Chinese part of "許耿福 HSU, KENG-FU", else up to the first comma), length, ^ref, and "Place" (floating on hover, focus or selection).
- Empty: "Nothing staged[ for this section]. Stage a card to keep it to hand."
- **Interviewer questions are locked**: "Interviewer questions: reference only, not placeable", up to 3 locked cards with a "Question" chip (no grip, no Place), "and N more". Placing one: "Interviewer questions are reference only: they never go in the cut."
- Bar count: placeable items here; the phone tab badge: every staged cut in every staged category, locked included.
- Click a staged card: inspector. Drag it: hold mode (cards list or lane).
- **Place** without a target: after the selected cut, else the end of the current section. "Placed <speaker> ^ref in the cut." with Undo.
- **Stage**: the selected cuts to the shelf; "Staged <speaker> ^ref to the shelf." / "Staged N cuts to the shelf." with Undo; leaves the edit view.
- **Remove**: cuts to the shelf, gaps removed; "Removed from the cut (kept on the shelf).", "Removed N cuts (kept on the shelf).", "Gap removed. Undo puts it back.", "Removed N gaps. Undo puts them back.", "Removed N cuts (kept on the shelf) and M gaps."; leaves the edit view.

## Find (search the cards)
(source: views/chrome.ts, views/app.ts)

- Searches every cut, in the cut and on the shelf: its words as the lane shows them (only its own in-to-out span), its English (translation or alignment) and stored gloss, person, clip, ^ref, note. Case and repeated spaces ignored; spaces between CJK characters ignored; a leading "^" ignored.
- Desk: popover under the header box while it has text: "N match(es)" / "No matches", "Esc clears", up to 30 rows, then "N more. Add a word to narrow it down."
- Phone/landscape: Find tab, its own box focused on open; up to 40 results; empty box "Search the words, speakers and ^refs of every card, in the cut and on the shelf."; none "Nothing matches "q"."
- Row: speaker colour, short name, where ("§ 1.1", section name, "In the cut", "Staged – 1.1", or the bench section title), ^ref, snippet ~34 characters each side with the match underlined.
- Pick: clears the search. A cut in the cut: selected, head to its start, Cards view. A staged cut: inspector, Staged view.

## The edit view (one cut, trimming)
(source: views/edit.ts, views/app.ts)

- Opened by: Split when the head is not inside the selected cut, double-click a card, B on a focused card, the phone card's "Edges", "Edit edges", inspector "Edit view".
- Header: "Back to cards", breadcrumb (speaker in colour, ^ref, "· § 1.1"), sync pill, Undo, Redo.
- **Trim lane** ("Trim", "drag an edge, or step it"): a second lane in edit mode.
- **Words** ("Words", "tap a word to move the split"):
  - The words in the lane's language (English first when a translation exists). Timed tokens when the clip has word timings; Chinese otherwise split by the browser's word segmenter (or 2-character chunks).
  - A red split bar between words: the editor's pick, else just before the word at the head, else the middle.
  - Tap a word: bar after it, head follows (when paused). Shift+tap selects a stretch.
  - During an edge drag: going words struck; extend shows "+N.NN s new material".
  - None: "No words yet. The lane and the steppers still trim."
  - Joins: "Before" (end of previous cut's line, ~14 chars), "This" (head or tail by armed edge, 12), "After" (start of next, ~16); "The start of the cut" / "The end of the cut".
  - Hints: "Tap a word to move the red split bar after it, Shift+tap to select a stretch." / "N word(s) selected: Delete removes them, Z collapses back to the blade." / "Struck words go with the new edge." / "Cyan is what the new edge brings in.", plus "The split lands in the pause between the two words." / "This is the English: the split lands on the nearest pause between the spoken words." / "This clip has no word timings, so the split lands at the word's share of the cut."
- **Edge panel** ("Out point"/"In point", length aside): "In"/"Out" armed-edge toggle (Out default); value m:ss.cc (cyan + delta while dragging); nudges "−10f", "−1f", "+1f", "+10f"; "Split here" (Enter; disabled under 2 words) and "Remove words" (Del, when words are selected) or "Stage"; desk only: Gain and Fade (armed edge's) steppers and "Remove from cut".
- **Thumb bar**: "Previous cut", "Next cut" (hidden on a portrait phone), "Play the cut"/"Pause" (from the cut's start), "Play the join" (from 2 s before the armed edge's join), "Done".
- **Trim mode keys** (no Ctrl/Alt/Meta, not in a field, no menu or drag): A / S move the blade a word (Shift extends) with the head following; Z collapses; Enter splits at the blade (not when a button has focus); Delete/Backspace removes selected words; Esc or B leave to Cards.
  - Split refusals: "Collapse the selection first: a split goes at the blade. Z collapses it.", "The blade is at the edge of the cut: move it between two words first (A / S)." The split lands mid-pause between two timed words.
  - Remove refusals: "Select the words to remove first: Shift+A / Shift+S, or Shift+tap a word.", "Those words sit on one pause between the spoken words: select one more." Success "Removed a word / N words from the cut." with Undo; trim mode ends.

## Playback controls (views side)
(source: views/chrome.ts, views/app.ts)

- **Transport** (desk, in the lane bar): Previous cut, Play/Pause (fixed width), Next cut; timecode (start from the list, default 01:00:00:00; ";" before frames when drop-frame; display only) "of m:ss"; on a landscape phone during an edge drag a readout "In/Out m:ss.cc ±N s now N s Esc cancels"; a static "J K L shuttle" legend; Zoom out, zoom slider (log scale from the whole cut to 400 px per second; a click sets the zoom about the playhead), Zoom in (×1.5 / ÷1.5, playhead held still), "m:ss visible"; Shortcuts (desk).
- **Play bar** (phone): Previous cut, large Play / "Pause mm:ss" (tip "Tap: play or pause. Hold: play at 2x while held"), Next cut. On the Lane tab also "Trim the start to the head" / "Trim the end to the head" (ripple-trim the cut under the head), disabled with "Put the head inside a cut first" when the head is in no cut.
- **Hold Play for 2x**: transport/play bar Play held 280 ms plays at 2x while held (starting if paused); release returns to 1x and re-pauses if it was paused. A tap toggles. A cancelled touch is never a tap.
- Card Play: pause if playing, else play the selected cut from its start.
- Split: at the head if inside the selected cut, else the edit view.
- Previous / Next cut: step one cut.

## Phone navigation and tabs
(source: views/chrome.ts, views/app.ts)

- Tab bar: Cards, Lane, Edit, Staged (count badge), Find.
- Lane tab: requests full screen (navigation UI hidden) then a landscape orientation lock; only on a touch device in phone layout, inside a tap. If refused, once a session: "This browser will not go full screen or lock landscape: turn the phone yourself." Leaving the Lane tab (or growing to desk size) releases both.
- Edit tab: the rows view. Staged: the shelf. Find: search.
- Back gesture: leaving Cards (or entering the edit view) pushes one history entry; back returns to Cards from any tab or the edit view and never leaves the page from Cards. Back with a menu open closes it only; with cards lifted, cancels the lift. Returning by the tab bar removes the entry.

## Where you were (per cut list, per device)
(source: views/places.ts, views/app.ts)

- Kept in this browser's local storage, key `tc.place.<cut list key>`, index `tc.places`; at most 40 lists, least recently used dropped. Not in the file, not on the server.
- Kept: playhead, lane zoom and scroll, selected cuts (up to 500), the top card in the list and its offset, the view (cards / lane / staged).
- Written at most every 400 ms while anything changes (a list scroll included) and when the page is hidden or closed.
- Restored once on opening a list: selection (without scrolling), the phone's tab (not over the edit view), zoom, scroll, playhead (left alone if already playing). The list is held on its top card for 2.5 s while things settle; any wheel, touch, pointer or key lets go.
- A damaged or over-20,000-character record is ignored; refused storage remembers nothing.
- **Recorded places** (Shift+P record, P jump): up to 50 per list per device, `tc.placelist.<key>`, index `tc.placelists` (40 lists). Toasts "Recorded place N.", "50 recorded places is the limit.", "There is nothing to record yet.", "Place N of M.", "Nothing is recorded yet. Shift+P records where you are." P goes round; a jump moves the head even while playing.
- Exposed for View-settings rows (`window.tc.places`): count, index, record, jump, drop ("Place dropped. N left." / "Recorded places cleared."), clear ("Recorded places cleared."). Follow is exposed as get/set (`window.tc.follow`) and never stored.

## Game controller requests handled by the views
(source: views/app.ts, views/types.ts)

- Connected: the shortcuts sheet lists the controller map from then on.
- A hint line from the pad: shown as a toast.
- LT + Menu: video window toggle, or "There is no video window in this build.".
- Menu: toggles the shortcuts sheet.
- Go to head, follow toggle, note, places record/jump, Delete arming: as the keyboard.
- View: to the lane or the transcript panel by name (the transcript list's open row, else its first row, else its body); on a phone, the next of Cards, Lane, Staged.
- L3 held: a landing line at the head's release point. LT + right stick: a long clip move drawn on the lane. LB/RB + right stick: an edge drag drawn like a mouse drag, the source scrubbed to the new edge. A mouse drag in progress is never taken over.

## The lane: what it draws
(source: views/lane.ts, views/geom.ts, views/peaks.ts, views/colours.ts)

There are two lanes: the **dock lane** (the main timeline strip) and the **trim lane** inside the edit view (zoomed to one cut, no minimap, no word picking, no wheel zoom, no handle words, no join marks).

- Layout from top to bottom: the lane bar (dock lane only, see "Lane bar"), the **section band** (one coloured flag per section in view), the **ruler** (time ticks and marker ticks), the **track** (the clips), the **minimap** (dock only), and floating parts (selection outline, two edge handles, readout, playhead, insertion line, word bar, a status line "lane say").
- **Zoom and scroll**: zoom is pixels per second, from "the whole cut with 4% air" up to 400 px/s (about 13 px a frame). Scroll is clamped so at least 10% of the window shows cut. The trim lane always shows its cut plus padding of half its length (between 3 and 12 s) each side.
- **Clips**: each cut a block in its speaker colour (a vertical gradient), with a 3 px speaker-coloured top rule and a hard 1 px seam at its end. Under 3 px wide a clip is only a colour tick.
  - **Name row**: short speaker name and length ("15.4 s"), pinned to the clip's visible left edge, shown only when it fits whole (name alone if only that fits, nothing if not). Not drawn when the clip is under 56 px wide, when the track is under 48 px, on the dock lane under 80 px tall, or when the layout turns names off (the portrait phone mini lane). An extra small tag after it when it fits: "English pick", "spoken words", or the no-English tag ("no English", "loading…", or the reason there is none).
  - **Words in the clip** (when the track is at least 40 px): the lead language's text wrapped inside the clip (wrap width from the clip's own width capped at the lane width, so horizontal scrolling never re-wraps; a clip wider than the screen slides its words to stay in view; a narrow clip lays words out at a minimum readable width and cuts them at its edge). Latin words are never broken; text that does not fit ends with "…". Machine translations are drawn a shade dimmer (alpha 0.75).
  - Second language under the first only if the first fitted completely and the second fits whole; a step smaller (86%, at least 12 px) and quieter.
  - **Literal line** (when turned on in the lane bar and the aids feature provides one): an italic word-for-word English line under the first, up to 3 lines, its word lit with the spoken one.
  - Ink colour by the fill's brightness: dark ink on fills with relative luminance of 0.22 or more, cream ink below.
  - **The lit word**: in the clip under the playhead, the word being spoken gets a faint cyan wash and a 2 px cyan underline; words already said stay at full brightness and words still to come are drawn at 85%. During an edge drag the lit word is the word the trim will cut to, and on a shortening drag the words that would go are faded and struck through in red. Nothing is lit in a pause more than 0.3 s after a word. In a translated line the lit word is carried across by position (or exactly, when the aids feature links the English words).
  - New wrapping work is limited to 3 ms per frame; clips that did not get their words that frame draw them on the next.
  - All cut texts are pre-measured at idle time after a list opens (dock lane), and measurements are reset when web fonts finish loading.
  - **Waveform**: drawn from the clip's peaks file at the gain the cut will play at (the auto-level gain times the cut's own dB, held to the gain limit). It sits under the text, bottom-aligned to a shared baseline, at most 160 px tall; with little room a 10 px strip at the foot, or none. Quiet (alpha 0.24) under words; full (0.62) for a clip with no words, for the cut being dragged, the cut with an armed edge, and the trim lane's cut. No peaks yet and no words: a dotted centre line.
  - Auto-level target: the median level of the clips currently used in the cut (recomputed when the set of clips changes), the same rule the audio engine plays by. Waveforms are fetched once per clip from `GET /media/peaks?project=<key>&clip=<clip>`; a failure means "no peaks".
  - **Fades**: a darkened triangle with a gold ramp line at each faded end.
  - **Gain**: a dashed gold line at a height set by the gain, with a "+2.0 dB" tag when the track is 80 px or taller and the clip 70 px or wider.
  - **Note marker**: a gold 8 px square in the top-right corner of a cut that has a note (clip at least 24 px wide).
  - **Gaps**: a dark hatched block with hairlines top and bottom and "gap 1.0 s" (or "gap") when there is room (30 px and names on).
  - **Selection**: with several items selected, each selected cut gets a cyan wash and a 4 px cyan foot bar. The cut under the playhead gets a bright white frame. Cuts being carried in a move are darkened where they were.
  - **Section stripe**: a 4 px stripe in each section's colour under the clips, a pixel short at each boundary.
  - Clips outside the current section are no longer dimmed (the dimming code is present but switched off).
- **Section band**: a flag per section spanning it, showing only what fits whole: "§ 1.1 Name N cuts", "§ 1.1 Name", "§ 1.1", or nothing. The current section is marked. Hover gives its name, plus "(drag to move the section, its cuts come too)" for a § section flag or "(drag to another clip to move it)" for other headings.
- **Ruler**: ticks at steps of 0.5, 1, 2, 5, 10, 15, 30 s, 1, 2, 5, 10, 15, 30 min, the smallest that keeps labels 80 px apart on the dock lane (64 px on the trim lane), labelled m:ss (m:ss.s for half seconds). A coloured marker tick at the first cut of every heading. Ruler labels under the readout are hidden while it shows.
- **Minimap** (dock): the whole cut as section-coloured segments with a window box for the visible part; press or drag to centre the window there.
- **Playhead**: a line moved every frame; hidden when outside the window.
- **Selection outline and handles**: the selected item (cut or gap) has an outline and two edge handles (sliders "In point, <speaker>" / "Out point, <speaker>", or "Gap start/end: drag to size the gap"). An armed edge is marked. Handles let presses through to the clip (so it moves rather than trims) when the clip is drawn narrower than 44 px on touch or the mouse trim minimum, or when several items are selected; a drag in progress keeps them.
- **Delete armed**: the selected clip's outline turns red until the second Delete.
- **In / out range** (dock): when range marks are set, a wash over the range with a bar at each set end, labelled "In m:ss.cc, out m:ss.cc" / "No in" / "no out".
- **Phone reveal**: on phone layouts, a new selection outside the window scrolls the window to show it, once per change of selection.
- **Playback follow**: while playing with playback follow on, the window pages along: when the head leaves the 2% to 92% part of the window, the window jumps so the head is at 10%.

## The lane: gestures and keys
(source: views/lane.ts, views/geom.ts)

- **Edge handles** (mouse, pen, finger; not with Shift/Ctrl/Cmd on a mouse): dragging an edge shows the change live and commits one trim on release; nothing is sent before.
  - The cut keeps its place on the timeline: an in-edge drag moves the cut's end by the change (later cuts ripple), with "start stays, later cuts move" in the readout.
  - The edge snaps to a frame, keeps the cut at least 1/24 s (the stored minimum), keeps the in point at 0 or more and the out point inside the source when its length is known.
  - **Safe cut snap** (when the aids feature is on): within 9 px (16 on touch) of the nearest "safe cut" the edge snaps to it; Alt drags free. A "safe cut" marker shows where the nearest one is while an edge is dragged or armed.
  - The audio scrubs the new edge as it moves (hear while trimming).
  - Shortening shows a red hatch over the part that goes; extending shows a cyan ghost and an outline of where the edge was.
  - Readout: "Out|In m:ss.cc ±N.NN s now N.N s [start stays, later cuts move] Esc cancels"; for a gap "Gap N.N s ±N s ... Esc cancels".
  - A gap's either edge sets its length (whole frames, never under the minimum gap); release commits one gap length change.
  - Esc, or a cancelled pointer, drops the drag and nothing is sent.
  - Pressing a handle arms that edge.
  - Arrow Left/Right on a focused handle trims that edge by one frame (Shift: ten frames) and arms it.
- **Handle words** (dock lane, track at least 48 px, clip has timed words): while an edge is dragged, armed or hovered (mouse within 22 px of a handle), up to 16 words just past the edge are shown faded beside it ("… words" or "words …"); while extending, the words being brought in are shown inside the ghost. In English-first mode the English for those words is shown first (from a cut's own English or a known alignment) with the spoken words under it. Drawn at the foot of the track.
- **Fade handles** (dock lane, mouse without modifiers; touch with a 350 ms hold that vibrates 12 ms): the top 16 px of a clip at least 12 px wide, within 7 px (16 on touch) of the fade ramp's top end. Dragging sets that fade (0.01 s steps, not past the other fade); readout "Fade in|Fade out N.NN s Esc cancels"; release commits one change. A touch that moves 10 px before the hold is a pan; released before the hold it is a tap.
- **Click / tap on a clip**: selects it (the playhead stays where it is). Click on the ruler or bare lane: moves the playhead there. A mouse acts on press; a finger tap on the ruler acts on release.
- **Drag on the ruler** (more than 6 px): scrubs the playhead.
- **Hold the ruler 350 ms** (dock): rate scrub. The sideways offset from the press sets the playhead's speed: nothing within 8 px, then e^((offset−8)/13) − 1 seconds per second up to 180 s/s; each 60 px above the ruler makes it finer (×1, ×1/4, ×1/16). Readout "Scrub ◂/▸ N s/s sideways: faster · up: finer · let go to stay". Release leaves the head there.
- **Finger pan**: a finger dragging the lane scrolls it and coasts on release (friction 0.985 per 60 Hz frame; a release slower than 0.05 px/ms is a stop; the coast stops under 0.02 px/ms or at an end). A new touch stops the coast.
- **Wheel** (dock lane only; one handler): Ctrl, Cmd or Alt + wheel zooms about the pointer (factor e^(−delta×0.0025)); otherwise the wheel scrolls along the cut (horizontal delta, or Shift + vertical). Line and page deltas are scaled (16 px, 400 px).
- **Zoom keys anchor**: while the pointer is over the dock lane, the zoom keys hold the time under the pointer still.
- **Zoom buttons**: hold the playhead still.
- **Moving clips** (drawn here, driven by the input layer): the lifted clips ride under the pointer as a ghost showing each clip's speaker tint, name, length and first line (gaps as hatched "gap N s"); an insertion line and readout "Move <^ref / name / the N s gap / N clips> before|after <target>" or "stays where it is", "Esc cancels" (pad: "Let go of LT to drop · B cancels"). A panel beside the line shows the words of the clip the carried clips will follow ("<speaker> ends", "then a N s gap" if a gap sits between), shown at once, flipping to the right near the lane's start.
- **Box selection** (driven by the input layer, Shift+drag): a tinted band with "N clip(s)[ added]".
- **Markers on the ruler and band** (dock lane, mouse/pen only, needs 4 px of movement): drag a heading's ruler tick or band flag (or a note marker) onto another clip to move that marker in front of it (readout "Marker <title> before <target>" / "stays where it is"). Dragging a § section's **flag** moves the whole section with its cuts: dropping over the first half of a section's span puts it before that section, over the second half before the next, past the last to the end (readout "Section <title> before <title> / to the end / stays where it is"). Toast "Section "<title>" moved. Ctrl+Z puts it back." Esc cancels. On touch, the ruler is always a scrub.
- **Placing a staged card** (desktop drag and drop from the shelf): an insertion line at the nearest boundary between items, readout "Place ^ref N s after ^ref / before ^ref Esc cancels"; dropping places it there. Leaving the lane clears the target.
- **Picking words in a clip** (dock lane, the selected clip, clip has timed words and is at least 40 px wide):
  - Mouse: Alt+drag across the words (a plain press moves or selects the clip). Shift+click grows an existing pick in the same clip. Finger: press and hold 450 ms on the words (12 ms vibration), then drag; moving 10 px before the hold is a pan; a short tap acts like a tap on the clip.
  - Keyboard: with the clips focused, Shift+Left/Right starts a pick at the word under the head (or the first/last word) and grows or shrinks it a word at a time.
  - A pick draws the spoken words in the clip with the picked ones washed and underlined in cyan, and a **word bar** over the pick: "N word(s) · N.N s", "Delete words" (Del), "Highlight"/"Unhighlight" (H), "Split here" (B, also Ctrl+B; disabled when the pick starts the clip), "To safe cuts" (when the aids feature offers safer boundaries), "Clear the pick" (Esc). On a phone the labels are shorter ("Delete", "Split", "Safe") and the bar sits at the foot.
  - **Delete words**: removes exactly those words as one edit (cut halfway through the pauses either side; a zero-length word is widened to one frame; a frame is kept from an unpicked neighbour); the lane says "Deleted one word / N words (N.N s). Ctrl+Z puts them back."
  - **Highlight**: marks those words as the part that plays (`==...==` in the file), joining touching highlights, or removes the highlight if the words are inside one: "Highlighted: those words are the part that plays." / "Highlight taken off those words." Refused when the words are not found in the card text: "those words are not in the card's text yet, so they cannot be highlighted (the words are still being refreshed)".
  - **Split here**: splits the cut where the pick starts: "Split where the picked words start." Refused: "The pick starts the clip, so there is nothing to split there."
  - **To safe cuts**: moves both ends to the nearest safe boundaries; if already safe: "These words already start and end where a cut leaves a whole thought."
  - A click on a word without dragging moves the playhead to that word and drops any pick.
  - A pick is dropped when the selection moves to another item, when its cut is deleted, or when an edge move trims the picked words out; if the cut's edges move and the words remain, the pick follows them.
  - Without timed words, Shift+arrows on the clips say: "Select a clip first, then pick its words.", "Fetching this clip's word timings…", or "This clip has no word timings yet (no words file or subtitles), so its words cannot be picked."
- **English picks** (English leads and the clip's English is a translation): the spoken timings belong to the original, so:
  - With the align feature present, dragging across the English picks English words; they are mapped to the spoken words. While mapping, the bar says "Lining the English up with the spoken words…" with Cancel; if it cannot: the reason with "Spoken words" and Clear. Once mapped the bar shows the original words (in their language), count and length, "Approximate" when the alignment is approximate, and Start/End nudges (one word earlier/later; Alt+Left/Right moves the start, Alt+Shift+Left/Right the end). On a desk, when the bar is more than 200 px wider than the clip, the nudges fold behind a "More" button. "Spoken words" switches to picking the spoken words. The original line stays drawn under the English with the mapped words washed (solid when sure, dashed underline when approximate).
  - An approximate English pick that maps to every word of the cut cannot Delete: "This English pick is approximate and stands for the whole cut. Pick from the spoken words to delete part of it."
  - Without the align feature, a drag or hold on a translation switches the clip to show its spoken words: "Showing the words as spoken (the timings are theirs). Drag across them now to pick."
  - When a clip with an English translation is selected, its alignment is asked for quietly in advance.
- Other surfaces (a card's English selection) can hand the dock lane a pick of spoken words and ask it to pick, delete, highlight or split. Refusals: "That card is not in the cut, so the lane cannot act on its words.", "This clip has no word timings yet, so its words cannot be picked.", "Those words could not be picked.", "The lane is not on screen, so its word tools cannot act.", "The lane refused that (it says why)."
- The lane's own messages show for 4.5 s.
- **Join checks** (when the aids feature provides them; dock lane, track at least 48 px): a dot on each seam between two cuts in the same section (seam at least 6 px from the edges, next cut at least 14 px wide), coloured by state. Hover (mouse) or tap opens a pop-up: "Checking the join…", "The join reads well", "Meaning changed" or "Grammar break", "quick check" when only the local check has answered, the note, the joined original words, and their fresh English, or "Claude is reading the joined words again…".
- **Aid marks in the words** (aids feature): thin underlines after the text (gold for verbs; cyan dotted for names and places; cyan dashed for numbers and dates; red for negation, conditions and contrast), a faint strike through fillers, short ticks between words for cut points (green "safe", red "strand"; a less certain safe tick fainter), and a gold sentence number after a sentence's last word where there is room.
- Cursor hints (mouse): over the selected clip's words with Alt held, a text cursor; over any clip, a move cursor.
- After a pointer gesture the clips take keyboard focus without the focus ring; the next key brings the ring back.

## Lane bar (dock lane: size, position, language, text size)
(source: views/laneBar.ts, views/laneText.ts)

- **Resize**: drag the bar's empty area ("drag to resize" grip; mouse, pen or finger). At the bottom pulling up grows the lane; at the top pulling down grows it. Keyboard on the grip: grow/shrink arrow 8 px (Shift 40 px), Page Up/Down 80 px, Home minimum, End maximum, Enter back to default. Double-click the grip: back to default. Esc during a drag puts it back.
  - Limits: at least 64 px (96 px on touch); the panels always keep at least 200 px.
  - Default ("the lane is the hero"): 58% of the room the lane and the panels share, never under 116 px, and leaving the panels at least min(300 px, half the room).
  - Remembered per device (local storage `tc.lane.h`); refitted when the window or the panels change size, without forgetting the wanted height.
- **Dock top or bottom**: the dock button flips it ("Move the lane to the bottom" / "to the top"); dragging that button more than 6 px shows a dashed outline and dropping in the top or bottom half of the window docks it there. Remembered per device (`tc.lane.dock`); **top by default**.
- **Hide the panels**: a button that folds the panels away so the lane takes the whole editor, and back ("Show the panels"). Remembered per device (`tc.lane.panels` = "hidden").
- **Language switch** (F9 per its tip): "EN" (English leads, the words as spoken under it where they fit) or the original language button labelled by the list's languages ("中文", "RU", "UK", "RU/UK", else "Original"; sampled from up to 400 cuts). Remembered per device (`tc.lane.lang`); **English by default**. Shared by every surface that reads it (the edit view's words, the joins, handle words).
- **Literal**: toggles the word-for-word line. Remembered per device (`tc.lane.literal`); off by default.
- **Word size**: smaller / larger buttons (12 to 24 px) and the current size. Automatic by default: the track height ÷ 24, between 13 and 20 px (116 px track → 13, 380 → 16, 480 → 20). Choosing a size remembers it per device (`tc.lane.font`); double-clicking the number (or a button) returns to automatic.
- **◐ rate scrub pad**: press and hold, then slide; works like holding the ruler (pauses playback first; 12 ms vibration); the press point is the origin.
- When the looks feature is mounted (it marks the page), this bar gives up the height and the dock to that feature's View settings and keeps only the word tools (so there is never two grips).
- On phones the layout owns the lane's place and height; the bar shows only the language and size tools, on the Lane tab.
- The desk transport sits in this bar row.

## Which words a clip shows
(source: views/laneText.ts, views/laneWords.ts)

- A card's text lines in a non-Latin script are the words as spoken; Latin lines beside them are its English gloss. An all-Latin card is English (an English interview), unless a translation says otherwise.
- English comes from (in order): the language model plugged in by features; the card's own gloss; a registered translation (dimmed when machine work).
- In English-first mode a clip with no English leads with its original and carries the no-English tag ("no English", "loading…" while the translate feature is still working, or the specific reason once it has answered).
- The second line is shown only when it differs from the first.
- While an edge moves, the clip's text is re-cut from the clip's timed words at once (before the server writes it); the stored English is kept only while the words are the same (within two characters, ignoring spaces and punctuation).
- **Timed words** come from the words service (`<clip>_words.json`, else the `.srt` cues). At most 48 clips are kept (least recently used dropped), 60,000 words per clip, 3 fetches at once (newest first); "no words" is remembered for 30 s, a failed request is retried after 2 s. A word belongs to a cut when its midpoint is inside the cut.

## The phone Edit tab ("rows": the cut running down the screen)
(source: views/rows.ts)

- Shown on phone and landscape layouts under the Edit tab. One row per cut in timeline order, each a gap a thin row (28% of the row height, at least 14 px) reading "gap N.N s". A point along a row is a point in time; the timeline runs down the screen.
- Each cut row: its number, short speaker name, the words in the lane's language (only at row heights of 48 px or more), its length (or "+/−N.NN s" while a trim is held), with the cut's waveform drawn behind at the playing gain (a flat line when no peaks). Rows in the selection and picked-up rows are marked. Only rows near the screen exist at a time.
- **The head**: a marker that travels across the row it is in; the list moves up under it so the head stays 38% down the list. A finger scrolling the list "browses": the head stays and the list stays where it was put until the head moves again (or play starts).
- **Row height**: four steps, 24, 48, 72, 96 px (default 48), set with "Shorter rows" / "Taller rows" or a two-finger pinch (each 30% change in finger distance is one step). Remembered per device (`tc.edit.rows.z`).
- **The dial** (a strip down the right edge): the only thing that scrubs. Dragging it pauses playback and moves the head down/up the rows, heard as it goes; the further left of the dial the finger is, the finer (down to a quarter, over 160 px). Keyboard on the dial: Up/Down one second, Shift ten.
- **Tap** in the list: play / pause, after a 300 ms wait (so a second tap can be a pick-up).
- **Two taps** on the same row within 450 ms: pick it up (15 ms vibration, it becomes selected): "Picked up cut N / the gap. Tap where it goes: the top half of a row puts it before, the bottom half after. Tap it again to put it back." The next tap moves it ("Moved. Undo puts it back.") or, on itself or empty space, puts it back ("Put back.").
- **Press and hold 450 ms then drag** on a cut row (12 ms vibration): trims its in point (pressed in the left half) or out point (right half); arms that edge; heard as it moves. A full-width drag moves the edge 5 s whatever the cut's length; the cut keeps at least 0.1 s; values in 1 ms steps. On release one trim is committed and auditioned: the head goes 1.5 s before the new edge and plays for 3 s, then pauses. Moving 10 px before the hold cancels it.
- **Loupe**: a waveform strip of 4 s (2 s either side of the head, or of the edge being trimmed) at the foot of the list, with the cut's own in/out lines labelled, a centre line (red for the head, amber for a held edge), and under it the word at that point, "· 4 s across" and "· trim"/"· fine". "the head is in a gap" when there. It shows by itself while a trim is held; the Loupe button pins it on ("Loupe on: the waveform around the head, 4 s across" / "Loupe off. It still appears while you trim."), remembered per device (`tc.edit.loupe`). A press-and-hold that starts on the loupe trims the nearer edge of the cut the head is in, 4 times finer; in a gap: "The head is standing in a gap. A hold trims the cut the head is in; take it into one with the dial." It redraws only when a pixel of travel changes it.
- **Bar buttons**: "2x" (toggles twice speed, pitch follows; again for 1x), "Split" (split the cut at the head), "Delete" (first tap turns it into "Tap again" for 3 s; the second deletes the cut under the head: "Deleted the cut under the head (it is on the shelf). Undo puts it back."), "Loupe", "Shorter rows", "Taller rows". Split and Delete are disabled with "Put the head inside a cut first" when the head is in no cut; tapping them then toasts that reason.
- The browser's long-press menu is suppressed on the list and loupe.

## Workspace (desk panel groups)
(source: views/workspace.ts)

- Applies only when the window is wider than 700 px and taller than 500 px; below that the panels go back to the phone layouts.
- To the right of the sections rail, the panels Cards, Transcript, Staged, Video and "Selected cut" live in **tab groups** side by side. Default: group 1 with Cards, Staged, Selected cut, Video (Cards showing; flex share 3) and group 2 with Transcript (share 2.2). Rail default width 272 px.
- Click a tab (or Enter/Space) to show its panel; Left/Right arrows on a tab walk the group. Hidden panels are kept, not rebuilt; their scroll positions are kept across rebuilds.
- **Drag a tab** (6 px threshold; a ghost with its name and a highlighted drop area): onto the left or right quarter of a group, it becomes its own group beside it, taking half that group's share; onto the middle, it joins that group and shows. A move that leaves the old group holding several panels shows "Which panel here?" with one button per panel. Esc cancels the drag.
- **Splitters**: the rail's width (160 to 520 px; double-click resets to 272) and the border between groups (each group at least 220 px).
- **⋯ "Panel layout"** button on each group: a menu with "Reset the panel layout". The button toggles it; Esc or any other key closes it (other keys then do their usual thing, so Space still plays).
- The layout is kept per device in local storage (`tc.ws.v1`); an unreadable layout falls back to the default, and every panel is always in exactly one group.
- **Transcript tab with no transcript open**: "No transcript open.", a "Browse transcripts" button (key hint 2) that asks the transcripts feature to open its browser, and "Every interview and montage clip in this episode, with filters and bins. Or double-click a clip in the lane, or press Q on a card, to open its transcript." When a transcript opens, its tab comes forward.
- A panel coming into view triggers its redraw (and tells features, so the shelf feature redraws).
- Toasts float over the groups, never inside a hidden tab.

## Video tab
(source: views/videoTab.ts)

- A dockable panel showing the pipeline's small preview render of the interview under the playhead (`GET /media/video?project=<key>&clip=<clip>`, under the dashboard mount base when there is one). Its time 0 is the clip audio's time 0.
- Always muted (the sound is the audio engine's). No picture-in-picture.
- Runs only while the tab is visible: no video element exists and nothing decodes otherwise.
- Playing: plays at the measured rate of the playhead (sampled every 250 ms, accepted between 0.2x and 4.5x, rounded to 0.05) and is pulled back when it drifts more than 0.25 s. Paused: shows the frame under the head (within 0.02 s).
- In a gap: "A gap: nothing plays here." A clip with no preview (load error): "No preview video for this interview yet. The pipeline makes it beside the interview's audio (<name> Preview.mp4)." (remembered for that clip for the session).
- **Kept on this device**: when the cut list's preview was kept on the device (the keep feature), the stored copy is played instead (looked up once per clip change); a stored copy that will not play falls back to the server for that clip.
- **Zoom**: wheel zooms at the pointer (faster with Ctrl, i.e. a trackpad pinch), from 100% to 800%; buttons "−", "100%" (fit), "+" step ×1.5; double-click fits; drag pans while zoomed; the picture always covers the frame. The zoom buttons appear on hover, while zoomed, or when focused.
- The Video panel is hidden whenever the workspace is not mounted (phones).

## Layouts, breakpoints, densities and look
(source: styles/layout.css, styles/views.css, styles/components.css, styles/tokens.css, styles/main.css)

- **One dark look only**; there is no light theme and no theme setting. Colours: warm near-black grounds, red brand accent (primary buttons, panel titles), cyan for "go", live values, focus and selection, gold for gain, fades, notes and warnings, green only for the "synced" dot. A faint red scanline and vignette sit on the page backdrop only, never over text.
- Fonts are bundled with the app (work offline, no web font service): IBM Plex Sans (reading text; Latin and Cyrillic), Noto Sans TC (Chinese), JetBrains Mono (meta, timecodes, labels), Orbitron (the wordmark). Russian and Ukrainian text never falls back to a system font.
- Type sizes: card words 18 px (CJK line height 1.85, otherwise 1.75), English gloss 16 px at a 66-character measure, UI 14 px, nothing smaller than 12 px; transport timecode 20 px.
- **Desktop** (wider than 1023 px and taller than 500 px): sections rail | panel groups (workspace), lane dock full width (top by default), header with a sync pill (the status line is hidden on the desk; the header pill shows the sync state instead).
- **Tablet** (701 to 1023 px wide, taller than 500 px): the sections rail is hidden; the workspace groups use the full width (the rail splitter is hidden).
- **Phone portrait** (700 px wide or less): one column; section chips strip; a mini lane 60 px tall with no band, ruler, minimap, names or readout; the play bar; the five-tab bar; rail, inspector, status line and desk transport hidden; brand text and breadcrumb episode hidden; feature controls in the header drop to a second header row.
  - Lane tab: the inspector of the selected cut fills the space above, and the lane track is 140 to 220 px (26% of the screen height) with its band and ruler shown; with nothing selected, the lane takes the whole space (track at least 140 px).
  - Edit view on a phone: controls in thumb order (lane, then edge controls, then words); trim lane 112 px; Previous/Next hidden in the thumb bar; "Back to cards" and "Play the join" become icon-only; the pill is hidden; words at 19 px.
- **Phone landscape** (500 px tall or less and wider than 700 px): a vertical tab rail on the left (64 px), cards | inspector (280 px), a 52 px lane with no band/ruler/minimap/readout, a compact transport (no zoom, no shuttle legend, 16 px timecode), no status line, no section rail. Lane tab: the lane takes the whole view (track 96 to 220 px). Edit view: trim lane 104 px, hints hidden.
- **Touch devices** (coarse pointer): every control grows to 44 px; key hints and tooltips are hidden; lane edge handles get a 44 px grab area; the shelf shows "Place" only on the selected item; the "Shortcuts" menu row is hidden; the lane bar is 44 px tall.
- **Header compaction** on the desk: below 1600 px the "TIMELINE CARDS" text is hidden; below 1500 px the search box drops its "Ctrl K" hint; below 1200 px Send to Resolve becomes an icon with a tip, the search box narrows to 120 px, and the feature tools fold into the "Tools" drop-down (also on landscape phones).
- **Reduced motion** (system setting): no transitions, no blinking caret, no spinning icons; busy buttons keep their "-ing" label.
- Long lists: cards and shelf items off screen skip layout (so 1,500+ cards stay fast); the selected and playing card are always laid out.
- Sticky section heads with a 28 px fade under them, so no half-faded line shows under a head.
- Selected card: a cyan frame (never a red wash). Playing card: a cyan dot in its left padding. Armed (lifted) card: cyan outline raised 2 px. Delete-armed card: red outline.
- Menus: a bottom sheet on phones; a centred 340 px dialog on the desk (the shortcuts sheet up to 760 px wide, two columns).
- Toasts: inside the cards panel, centred near its foot; in the edit view fixed 96 px from the bottom.

## Feature platform (how features join the editor)
(source: platform/index.ts, platform/modules.ts, platform/slots.ts, platform/proposals.ts, platform/features.gen.ts)

- Features mounted at start-up (each from its own folder): aids, align, chat, gapnotes, keep, lane, looks, markers, montage, resolve, search, shelf, shorten, transcripts, translate, video. "projects" is mounted by the shell itself (see "Page shell").
- **Turning features off**:
  - Server: `GET /api/features` lists features with `enabled: false`; those are not mounted. Its `flags` (booleans) are passed to features (looked up as "<feature>.<flag>" then "<flag>"). An unreachable or failing endpoint means "nothing off, no flags".
  - Per browser: local storage `tc.features.off` (comma-separated names) turns features off on this device only. DEV ONLY in practice (no control in this part sets it).
- A feature whose start throws is skipped and named in one warning toast: "Not available in this window: <names>. The editor still edits." A feature listed twice is refused ("mounted twice"). Everything a feature added is removed when it stops; stopping runs in reverse order.
- **Toolbar slot**: feature buttons drawn in the header tools group (ghost buttons with icon, label, key hint, tooltip and toggle state). Redrawn when the slot changes or the state changes, except for pure playhead/scroll/zoom movement.
- **Keys slot**: one window key listener; the first feature key whose chord matches (and whose condition holds) runs. Letters and digits match by physical key, so Alt+M works on any keyboard layout; Cmd counts as Ctrl. Key repeat is ignored unless the key asks for it; typing in a text box is ignored unless the key asks for it. A key's action that returns false lets the event through.
- Every key a feature binds appears in the shortcuts sheet as it comes and goes.
- Other slots exist (desk rail tab, phone tab, inspector section, card action, lane menu item, overlay, command palette entry, settings row). UNREACHABLE from the views in this part: the views never draw the desk rail, phone tab, inspector, card action, lane menu or palette slots. (The settings slot is drawn by the looks feature, outside this part.)
- **Proposals** (one pipeline for every AI feature and importer: chat, shorten, montage, search inserts, Resolve import, translate):
  - A proposal has a title (trimmed to 200 characters), a reason (up to 4,000), its edit operations, its source, optional per-operation labels. Refused: no title ("a proposal needs a title"), no ops, or an operation this editor does not know ("the <source> proposal has an op this editor does not know").
  - Preview: what it would do, card by card (added, removed, changed with the fields, moved, shelved, unshelved) and the lane as it would be (clips same/added/changed/moved, spans taken out, duration before and after). Nothing picked: "nothing is picked".
  - Accept all, accept some (picked operations in their own order), or none (rejected). An accepted proposal is ONE edit and one undo step. Refusals: "that proposal is gone", "that proposal was already <status>", "no cut list is open", "those changes do not stand without the ones left out: <reason>", or the editor's own refusal; nothing applies half way.
  - Once the server has taken the accepted edit, a server-side proposal is deleted there (`DELETE /api/proposals/<id>?key=<key>`); if the server refuses the edit, the proposal reopens with "the server refused it (the cut list had changed meanwhile); look at it again".
  - Rejecting a server-side proposal deletes it there too.
  - Server proposals are fetched with `GET /api/proposals?key=<key>`; failure: "the proposals could not be fetched (<status>)". Answers that arrive after switching cut lists are dropped; malformed ones are skipped; one already seen is not added again.
  - Limits: 50 open proposals (oldest dropped), 50 closed ones kept for history. Switching cut lists clears them.

## Kept on this device (the device store)
(source: device/index.ts, device/types.ts, device/app.ts, device/opfs.ts, device/cachefs.ts, device/fsstore.ts, device/paths.ts, device/meta.ts, device/hasher.ts, device/sha256.ts)

The keep feature itself (what is downloaded, when, the storage panel) is outside this part; this is where kept files live and how they are written and read.

- **Where kept cut lists live**, picked automatically once per page:
  1. Inside the Windows or Android app (the page is on `127.0.0.1:47823` / `localhost:47823`, or the Android bridge exists) and the app answers `GET /__app/api/keep`: real files in the app's project folder on disk (default described as `Documents\Timeline Cards\<episode>\<cut list>` for Windows). Labels "The Windows app's project folder" / "The Android app's projects folder".
  2. Else the browser's private file system (OPFS) under `tc-keep/`, if writes there actually work (a probe file is written; private windows that refuse fall through). Label "This browser".
  3. Else Cache Storage (`tc-keep-v1`), label "This browser".
  4. Else memory: nothing can be kept ("Nowhere (this browser keeps nothing)").
  - DEV ONLY: local storage `tc.keep.store` forces "opfs", "cache", "memory" or "app".
- **Folder names**: `<episode>/<cut list>` from the cut list key (`<episode>/Script Docs/Cuts/<name>.cut.md`), each made safe for Windows (characters `\ / : * ? " < > |` and control characters become "_", trailing dots/spaces removed, at most 120 characters, reserved names like CON get a leading "_"). Two lists landing on one name get " (2)", " (3)". A key that is not a cut list key goes under `Other/`. Clip files are named "<clip>.<ext>" with the clip's own media extension removed.
- Paths inside a list folder: relative, at most 4 levels, each part at most 200 characters, no "." or "..", no `.partial`, no `manifest.json`, nothing starting `.timeline-cards`; anything else is refused.
- Each list folder holds a `manifest.json` (every committed file's size and SHA-256, the time, and the keeper's notes), and the root holds an index `.timeline-cards-keep.json`.
- The keeper's notes per list: name, episode, whether everything planned is held, when the last keep finished, per clip its audio file (Ogg or WAV), peaks file, preview video and their server hashes, duration and size, the kept answers per request, bytes planned, and clips the server had no audio or video for. Analysis answers are kept in `Analysis/translations.json`, `Analysis/alignments.json`, `Analysis/language aids.json`, `Analysis/word links.json`, `Analysis/join checks.json`.
- **Writing a file** never leaves a half-written file in place: bytes go to `<path>.partial`, then a commit checks the size (and the hash when the download ran from the start) and renames it into place. A size mismatch drops the partial ("<path>: N bytes arrived, M were expected"); a hash mismatch drops it ("the bytes on the device are not the bytes that were sent"). A short body keeps the partial so the next try resumes from where it stopped ("<path>: N of M bytes arrived").
  - OPFS: committed to disk every 16 MB (or a quarter of the file size, whichever is larger), in 2 MB writes, so a closed tab keeps what landed.
  - Cache Storage: in 8 MB parts.
  - Apps: sent to the app in 4 MB requests.
  - Two tabs keeping lists at once do not lose each other's index entries (a per-storage queue plus a browser-wide Web Lock `tc-keep-opfs` / `tc-keep-cache`).
- **Hashing** (SHA-256) runs in a background worker so the page does not freeze; without a worker, it runs on the page in slices of at most 4 ms with breaks; documents under 256 KB are hashed directly.
- **Removing** a list deletes its folder and index entry (an episode folder left empty in OPFS goes too) and reports the bytes freed; removing one file updates the manifest. A keep in progress notices the list was removed and stops.
- **Usage**: bytes held, the browser's quota (or the disk's free space in the apps), whether the browser promised not to evict (the browser homes ask `navigator.storage.persist()`; the apps always say yes), and the folder on disk (apps).
- **Apps only**: show the folder in the file manager; move the project folder (refused when lists are kept unless told to move them or leave them: "N cut list(s) is/are kept in the current folder: move it/them, or leave it/them where it is/they are"). The app server refuses writes from another origin and a wrong Host. Errors: "this device has no room left for it" (quota), "the app answered <status> for <what>".
- Cache Storage files are never cleared by a new service worker (see "What works offline").

## Offline answers from a kept cut list
(source: device/answer.ts)

- Installed over the page's network calls at start-up, so every part of the editor works from a kept list with no network without knowing it.
- Only same-origin `/api/*` and `/media/*` requests are touched; the keeper's own downloads (header `x-tc-keep-fetch: 1`) pass straight through.
- **Kept documents** (GET requests the keeper saved, matched by path and query with parameters sorted): the network is tried first but waited on at most 5 s; on a network error, a 5xx, or no answer within 5 s, the kept copy answers (header `x-tc-kept: 1`). A good network answer quietly refreshes the kept copy (at most once a minute per document, only if the bytes changed, never while the keeper is writing that list). A late network answer still refreshes it.
- Which kept list a request belongs to: the `key` or `project` in its query, else the open cut list, else any kept list that holds that document.
- **Analysis lookups** (POST `/api/translate/lookup`, `/api/align/lookup`, `/api/aids/analysis`, `/api/aids/words`, `/api/aids/joins`) for a kept list: online, every READY answer (and for translate, every line and language) is merged into the list's analysis file, written 1.5 s after the last change (at most 100,000 unsaved entries buffered). Offline (network error or 5xx), the whole kept dictionary is the answer; translate answers say "you are offline" with no job running.
- **Search offline** (POST `/api/search/find`): a plain substring search over the kept transcripts (case-insensitive, or exact when the query is in double quotes), up to 200 results (or the `max` asked), counting all matches, plus matches in the cards' text sent with the request; results are marked approximate.
- **Audio windows and peaks offline** (`/media/pcm`, `/media/peaks` of a kept clip): the peaks file is read from the device; PCM windows are decoded from the kept audio.
- Anything else, or a list that is not kept: untouched.

## Audio and video playback from the device
(source: device/audio.ts, device/decode.ts, device/ogg.ts, device/video.ts)

- **Kept audio plays from the device, online or not**: for a kept list, every audio window the engine needs is decoded on the device from the clip's kept Opus (Ogg) or WAV copy, sparing the server. If a kept copy fails to decode, that window is fetched from the server ("the kept copy did not decode; asking the server" in the console). At most 2 windows decode at once.
- Decoding: the Ogg file is indexed once per clip (read in 1 MB pieces, never whole); each window decodes the pages it needs plus 80 ms of run-in, with the browser's WebCodecs Opus decoder (exact sample placement), else the older whole-run audio decode (placed at the first packet). The result is mixed to mono and resampled to the asked rate with a windowed-sinc filter, sized exactly as the server's `/media/pcm` would answer. WAV copies support 8, 16, 24 and 32-bit integer and 32-bit float. Errors: "this browser has no audio decoder", "the kept clip could not be read".
- **Clip facts** (`sources`): the server's when it answers, else the kept copy.
- **Peaks**: the kept peaks file first (a torn copy falls back to the server); one fetch per clip per page, shared by the waveform drawing and the audio levelling; a failed fetch is not remembered.
- **Video**: the kept preview is played through a local URL (a `blob:` URL of the stored file in a browser, which the player reads from disk as needed so seeking works with no network; the app's file route in the apps). Only a fully committed file is used; otherwise the Video tab uses the server.

## Looks redundant or overlapping

- Two separate "offline" layers answer the same requests: the service worker keeps the last `/api/project`, `/media/sources` and `/media/peaks` answers, and the device store's offline answers serve kept documents, peaks and PCM; plus (outside this part) the browser database copy of the cut list. Three caches for one cut list.
- Two Shortcuts buttons (status line and transport) plus a third in the header More sheet; on the desk the status line is hidden by CSS, so its button and its whole context text (mode, "rev N", "Synced, nothing queued") are drawn every frame but never seen.
- The status line duplicates the header sync pill; the desk CSS hides the status line and forces the pill (marked phone-only in markup) on.
- Two lane height/dock controls: the lane bar's own grip and dock button, and the looks feature's View settings (the bar defers when looks is mounted).
- Several ways to move a cut: mouse drag on cards, two-tap lift on cards, "Move this cut" menu item, two-tap pick-up in the phone rows, lane clip drag (input layer), pad long move.
- Several ways to trim: lane handles, inspector steppers, edit view nudges and steppers, edit-view trim lane, phone rows press-and-hold, the loupe, the play bar's "Trim the start/end to the head", handle arrow keys.
- Several ways to delete words/split: edit view trim mode (A/S/Enter/Delete), lane word picks (Delete words / Split here), card English selection handed to the lane.
- Two search surfaces in this part (header popover / Find tab) plus the search feature's "search every transcript" (G) outside it.
- Two "play from a point" helpers: card Play (from the cut start) and edit view "Play the cut"; "Play the join" in the edit view.
- Two places hold the per-device lane language/size/literal settings that other features also read (one setting, several switches: the lane bar, and the translate feature's header toggle hidden on desk by CSS).
- An "Offline" state panel builder exists alongside the offline toast that is actually used.
- The section dimming outside the current section is still computed (and has CSS `.clip.is-out`), but switched off.
- CSS for a DOM-drawn lane (`.clip`, `.lbl`, `.wave`, `.gainline`, `.fade`, `.stripe`, `.lane-gapsel`) remains, though the lane is drawn on a canvas; CSS for `.log`, `.diff`, `.queue .st`, `.prog`, `.switch`, `.card.is-question`, `.L-sheet`/`.sheetgrid` styles nothing drawn in this part.
- `places` storage (where you were) and recorded places (P/Shift+P) are two separate per-device lists with separate indexes and limits.
- The proposal pipeline and the views' own Undo-toast edits are separate paths for "an edit with one undo step".

## Claims the code does not back

- laneBar.ts module comment: dock position default is "bottom by default"; the code defaults to **top** (`dockPref()` returns top unless "bottom" is stored).
- layout.css header comment: "the four-tab bar (Cards / Lane / Staged / Find)"; the tab bar has **five** tabs (Edit added).
- layout.css header comment: "desktop ... the status line at the foot"; views.css hides the status line on the desk.
- workspace.ts module comment lists tab groups for "cards, the transcript, the staged shelf and the selected cut"; the default also includes a Video tab.
- shell.ts / chrome.ts comment: the status line is "the ONE home of the "> " prompt"; on the desk it is never displayed.
- rows.ts comment: "the four row heights, and the four things a row can say"; a row only switches between with and without its words (at 48 px).
- edit.ts / inspector.ts comments: "the model carries no word timings ... a transcript service will" and the strike preview "by proportion"; the edit view does use word timings, but the inspector's strike preview and the card's word underline fallback are still proportional.
- views/types.ts: `onRetry` "Reconnect now (offline / error states)" and the empty state's "New from canvas"; whether these hooks are supplied is outside this part (the projects feature), so the buttons may show "not wired in this build".
- answer.ts comment: Find offline "matched here over the kept transcripts"; it is a plain substring match, not the server's search (results flagged approximate).
- hasher.ts comment: describes the keep top-up schedule ("20 s after start-up, then every 10 minutes"); not implemented in this part (see Could not determine).
- device/types.ts: Windows default folder `Documents\Timeline Cards\<episode>\<cut list>`; decided by the app's server, not by code in this part.
- The Highlight button in the lane word bar uses an icon ("mark") that is added to the icon set only by the dock lane's bar; it exists only because the dock lane is built first.

## Could not determine

- What the keyboard, pad and pointer bindings are exactly (Space, J/K/L, Q/W, F, P, N, Delete double press timing, I/O range marks, arrows, zoom keys, G, C, Alt+Shift+M, F8, F9, Shift+X, Alt+S): they live in client/input and the features, outside this part; only the views' answers are listed here.
- How long the Delete arming lasts (the seconds come from the input layer).
- Whether the projects feature supplies the open, new-from-canvas, retry and recent-list hooks (so whether those buttons are live).
- What the View settings sheet contains and its defaults: it is drawn by the looks feature (outside this part); this part only exposes Follow and recorded places to it and defers the lane height/dock to it.
- The keep feature's schedule, what it downloads and the storage panel (features/keep, outside this part).
- How the IndexedDB copy of the cut list and pending edits works offline (client/state/persist.ts, outside this part).
- How the server's `/api/features` decides which features are off (`TC_FEATURES`, `TC_FEATURES_OFF` are named only in a comment).
- The Android app's `CardsNative` bridge beyond `duck()`.
- Whether `follow` in the store (playback follow) has a user control; only the views' own Follow (F held) is visible here.

