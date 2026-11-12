# Dashboard: in-browser behaviour, the help pages, the personal account page and personal-data tools

Terms used throughout:

- **htmx**: the third-party script the dashboard pages use to fetch a piece of
  HTML from the server and swap it into the page without a full reload. A
  "poll" is such a fetch repeated on a timer ("every 15s").
- **Panel**: a box on a page that refreshes itself by such a fetch.
- **Service worker**: a script the browser keeps installed for a site, which
  can answer the site's requests itself (for example from a saved copy when
  the network is down).
- **Installed app / PWA**: the dashboard added to a phone's or desktop's home
  screen, opening in its own window without browser chrome.

## Third-party and static assets (source: static/htmx.min.js, htmx.LICENSE, fonts/, icons/, favicon.*)

- `htmx.min.js` is the minified htmx library (version 1.9.12 per the comments
  in pwa.js and htmx_errors.js; licence text in `htmx.LICENSE`). Every
  dashboard page built on the shared page frame uses it for every panel,
  poll and in-page button. The service worker precaches it.
- Fonts: JetBrains Mono (regular, medium, bold) and Orbitron (variable
  weight) are served from the dashboard itself, with their open-font
  licence texts (`OFL-JetBrainsMono.txt`, `OFL-Orbitron.txt`). No font is
  fetched from the internet.
- `fonts/manifest.json` lists a SHA-256 checksum for each of the four font
  files (nothing in this part reads it; see "Could not determine").
- Icons: an SVG icon plus PNG icons at 180, 192 and 512 pixels, and
  "maskable" 192 and 512 versions (a maskable icon is one a phone may crop
  to a circle or rounded square). Favicons in SVG, PNG and ICO.

## Installable app manifest (source: static/manifest.webmanifest)

- The dashboard is installable as an app named "CC Sync" (short name the
  same), description "The fleet dashboard: who is syncing, what is
  transferring, what is wrong."
- It opens at `/`, its scope is the whole site `/`, it runs `standalone`
  (no browser bars), falling back to `minimal-ui`; any orientation.
- Background and title-bar colour are near-black `#0a0a0d`.
- Icons offered: 192 and 512 PNG ("any"), 192 and 512 maskable, and the SVG.
- The app name is fixed as "CC Sync" in this file, not taken from the site's
  brand settings.

## Phone behaviour, polling discipline and the install button (source: static/pwa.js)

Loaded on every page that uses the shared page frame.

- **Slower polls on touch devices.** When the device's main pointer is
  coarse (a finger, i.e. phones and tablets), any panel that polls "every
  2s" is changed to every 10 s, and any that polls "every 5s" to every 15 s.
  Other intervals (15 s, 30 s, etc.) are left alone. This applies to the
  page as loaded and to every panel swapped in later.
- **Hidden tab costs nothing.** When the tab or app goes to the background
  (page hidden), every polling panel's in-flight request is aborted. When it
  becomes visible again, every polling panel is refreshed once at once, so
  the page shown is current rather than minutes old.
- **"install this app" button.** When the browser reports the dashboard is
  installable (Chrome's install offer), a button reading `install this app`
  is placed in the page's install slot (inside the top bar's "more" sheet).
  Pressing it opens the browser's install dialog once and removes the
  button. Nothing is shown when already running as an installed app, when
  the browser has made no offer (Safari, Firefox), or when the page has no
  install slot.
- **Service worker registration.** On secure origins only (https, or
  localhost) the dashboard's service worker `/sw.js` is registered for the
  whole site. On plain http (the default LAN setup) nothing is registered
  and nothing is shown; a registration failure is only written to the
  browser console.

## The dashboard's service worker (source: static/sw.js)

Served at `/sw.js` (by a route outside this part) with the dashboard version
substituted in, so each release installs a new worker on every device.

- **Never caches anything that depends on who is asking.** These paths are
  never touched at all, always straight to the network: `/api/`,
  `/partials/`, `/cards/`, `/broll/`, `/music/`, `/ytdl/`, `/login`,
  `/logout`, `/.well-known/`. Only GET requests to the dashboard's own origin
  are considered.
- **Precache on install**: the `/offline` page, htmx, pwa.js,
  htmx_errors.js, all the app icons, plus (when the serving route fills it
  in) the content-hashed style sheets, scripts and fonts the offline page
  needs. Each file is fetched separately, so one missing file only leaves
  that file out.
- **Takes over at once** on install and on activation; on activation every
  older cache whose name starts `ccsync-` is deleted. The cache name is
  `ccsync-<dashboard version>-terminal-1`; the `terminal-1` part changes
  when the precached pages change look without a version change.
- **Page loads (navigations)**: always the network first. Only when the
  network request itself fails is the saved `/offline` page shown; if even
  that is missing, a plain-text `offline` with status 503.
- **Files under `/static/`**: the saved copy is shown at once if there is
  one, and at the same time a fresh copy is fetched (bypassing the browser's
  ordinary cache) and saved for next time ("stale while revalidate"). A
  failed refresh never turns a saved file into an error. With no saved
  copy, the network answer is used and saved.
- Everything else (the manifest, favicon, `/sw.js` itself): straight to the
  network, never saved.

## "This page has stopped updating" banner and refusals beside the button (source: static/htmx_errors.js, first block)

Loaded on every page with the shared page frame; precached by the service
worker.

- The page remembers the time of the last successful in-page exchange with
  the server (counted from page load).
- **Stale banner.** A red alarm banner fixed at the bottom of the page,
  reading `▲ THIS PAGE HAS STOPPED UPDATING (last update <N seconds /
  minutes / hours ago>). Nothing below is current.` followed by a reason:
  - status 401: `Your session has ended. Reload the page and sign in again.`
  - status 403 that is not a refused write (below): `The server refused this
    to your account (403)[: <server's reason>]. Reload the page; if you were
    signed out, sign in again.`
  - any other error status: `The server answered <status>. Reload the page
    to try again.`
  - network failure: `The server could not be reached. Reload the page to
    try again.`
  - timeout: `The server did not answer in time. Reload the page to try
    again.`
  The page is padded by the banner's height so it hides nothing.
- **The banner clears itself** the moment any in-page request succeeds
  (including ones that change nothing on screen).
- **A refused write is not an outage.** When a button, form or toggle that
  sends a change (anything other than a GET) gets a 4xx answer other than
  401, no stale banner is shown. Instead a small error note is put directly
  above the form (or label) that was used:
  - 403: `▲ Not allowed: <server's reason>` or, with no reason, `▲ Not
    allowed: this account cannot do that.`
  - other 4xx: `▲ Refused: <server's reason>` or `▲ Refused: the server
    answered <status> and gave no reason.`
  The server's reason is read from its JSON `detail` (or a list of
  validation messages joined with "; ") or `error` field.
  A checkbox that was ticked or unticked is flipped back to what the server
  still holds. The note is scrolled into view. Pressing the same control
  again removes the old note first.
- All server text is shown as plain text, never as markup.

## Tap-to-explain chips (source: static/htmx_errors.js, second block)

- Any status chip, tag, LED, dot or element marked as carrying an
  explanation, and which is not itself a link, button, field, label or
  fold-out heading, opens a small explanation sheet when tapped or clicked.
  The sheet shows the chip's own text as a label and the explanation (the
  same text as its hover tooltip) below.
- Tapping the sheet, tapping elsewhere, or pressing Escape closes it.
- Keyboard: such chips are made reachable with Tab (on load and after every
  panel refresh); Enter or Space on a focused chip opens the sheet.
- Only works on pages that include the sheet element (the shared frame).

## A write's error appears next to the button that caused it (source: static/htmx_errors.js, third block)

- When a panel refreshes itself in answer to a button press (a POST, DELETE
  or PUT) and the refreshed panel contains an error banner, that banner is
  moved from the top of the panel to directly above the control that made
  the request, and scrolled to the middle of the screen.
- When there is no error banner but there is a "result" banner (an outcome
  that is not a refusal, e.g. a test email that failed or went out), it is
  moved the same way. An error wins over a result.
- When several forms send to the same address, the one whose hidden fields
  match what was sent is chosen; otherwise the first.
- For a form taller than half the screen, the banner goes above its last
  submit button instead of above the form.
- Refreshes on a timer never move a banner; only presses do.

## Timed refreshes never wipe what you are doing (source: static/htmx_errors.js, fourth block)

- A timed refresh of a panel is skipped (not delayed; the next beat runs as
  normal) while that panel has any of:
  - keyboard focus in a text box, text area or drop-down (not ones that send
    themselves on change);
  - a field you have typed into or changed and not yet sent, for up to 5
    minutes after your last change;
  - a change request of its own still waiting for an answer (counted for up
    to 5 minutes);
  - a sub-panel marked to hold the poll (the folder picker opened by
    PROJECT ROOTS' browse button), for up to 5 minutes from when it was
    first seen;
  - an open pop-over.
- The same rule covers the one-off refresh pwa.js sends when a tab becomes
  visible again.

## Remember where you were on each page (source: static/tab_memory.js)

- On every dashboard page (not on the b-roll, music, YouTube-download or
  Timeline Cards apps, under `/broll`, `/music`, `/ytdl`, `/cards`), the
  browser remembers, per page, the scroll position, which fold-out sections
  were open (up to 100, those with an id or key), and the nearest heading
  above the top of the screen.
- "Per page" is the path plus only these view-selecting query keys, in this
  order: `editor`, `finished`, `kind`, `machine`, `project`, `tab`, `view`.
  Any other query part (search text and the like) shares the plain page's
  memory.
- Saved at most every 0.5 s while scrolling or after a panel refresh, and
  always when leaving the page, when the app goes to the background, or when
  the tab is hidden. Saved to both the tab's own storage and the browser's
  long-lived storage (so an installed app killed by the phone still
  remembers). An entry older than 8 hours is ignored.
- On arriving at a page: the remembered sections are re-opened, then the
  page waits up to 3 s (checking every 0.1 s) for late-loading panels to make
  the page tall enough, then scrolls to the remembered spot. If it never gets
  tall enough, it scrolls to the remembered heading, or else to the bottom.
- Not restored when the address has a `#anchor` (a deep link wins), when the
  browser restored the page itself from back/forward, or once you scroll,
  touch, press a key or click before the restore lands.
- No visible cue. If storage is blocked, nothing happens.

## Confirming the "publish automatically and make current" feed policy (source: static/confirms.js)

- On the package panel, the feed-policy drop-down (named `policy`) submits
  itself on change. Choosing `current` first asks: "Publish new builds
  automatically AND make them current? Every editor's computer will take
  each new build from the vendor feed without anyone approving it first.
  Choose 'stage' if you want to test a build before the fleet gets it."
- Cancel puts the drop-down back to the policy previously shown and sends
  nothing. OK, or any other choice, submits at once.
- Works after the packages panel's 30 s refreshes.

## Timeline Cards episode picker, in-browser behaviour (source: static/cards_landing.js)

Runs on the `/cards` landing page (the list of episodes). Without it the
page still works: folders fold, every button is a real form, the list is
alphabetical.

- **Sort chips**: LAST OPENED (default), DATE (last modified), LARGEST,
  A - Z. Rows within each folder, and the folders themselves (by their
  newest / largest content), are re-ordered. Ties and A - Z use natural,
  case-insensitive name order. "Last opened" sorts by when you opened it,
  then by when anyone did.
- **View chips**: tree (folders) or a flat list of every episode. The
  fold-all controls are hidden in list view.
- **Year chips**: show only episodes of one year, or all. A remembered year
  no longer present falls back to all. The "recent" tiles are filtered by
  year too.
- **Search line**: every space-separated word must appear (case-insensitive)
  in the episode's searchable text. Matching letters in the name are
  highlighted. While searching, folders holding a match open and the others
  close and hide; clearing the search returns folders to your own open or
  closed choices. Folder counts show "N of M" when filtered. The total line
  shows "N episode(s)" or "N of M episodes". A "nothing matches" note shows
  when nothing is left. A clear (x) button appears while searching and
  refocuses the search.
  - Terminal look: the recent tiles stay visible and dim during a search;
    otherwise they hide during a search.
- **Keys**: `/` (outside a text field, no modifier) jumps to the search
  line and selects it. Escape in the search clears it. Enter in the search
  opens the episode when exactly one is left (its go link or its open
  button); otherwise nothing.
- **Fold controls**: unfold all, fold all; a reset control clears the year
  and the search.
- **Folder sizes** are summed from the episodes and shown human-readably
  (B, KB, MB, GB, TB, 1024-based); a "+" is added when any episode's size is
  unknown.
- **Remembered**: sort, view, year and each folder's open or closed state in
  the browser's long-lived storage (`ccsync.cards.picker`); the search text
  only for the tab (`ccsync.cards.picker.q`). Clicking a folder heading
  records its new state, except while a search is folding things.
- **While an episode is opening**: if any episode shows "loading", the page
  asks the server for `state.json` every 3 s (skipped while the tab is
  hidden; after a failure it waits twice as long, up to 15 s). When any
  episode's state changes (or one disappears from the answer), the page
  reloads; but if the page was opened waiting for a particular episode
  (`?want=`) and that one is now ready, the browser goes straight into it
  instead (replacing the history entry so Back does not return to the
  waiting page).

## Timeline Cards episode picker, offline (source: static/cards_offline.js)

Also on the `/cards` landing page.

- **Registers the Cards worker** (`/cards/sw.js`, scope `/cards/`) on secure
  origins when not already offline, asks it to check for a newer version,
  and hands it the page and every asset the page loaded so the next launch
  works with no network. Repeated when a newer worker takes over.
- **"downloaded" marks**: reads, without creating anything, the episode
  page's own browser store of cut lists saved on this device, and which
  episode pages are saved. Each saved cut list is matched to an episode by
  its server path (the longest matching episode folder; if there is no path
  and only one episode page is saved, that one).
  - An episode with a usable copy gets a green `downloaded` tag (tooltip "A
    cut list of this episode is saved on this device and opens with no
    network.") and one `open <file>` button per saved cut list (tooltip
    names the file and "N edit(s) wait to sync" when there are unsynced
    edits).
  - An episode whose cut list is saved but whose page is not gets an amber
    `downloaded, page not saved` tag (tooltip: "...open the episode once
    with a connection.") and no button.
- **ON THIS DEVICE window** at the top, newest first: "N cut list(s) open
  offline", and per copy "<episode>: <file>", with cuts count, "N edit(s)
  waiting to sync", "saved <local date/time>", and either "its episode is
  not in this list" or "the episode page is not saved: open the episode once
  with a connection". Only shown when at least one copy exists.
- **Opening a copy**: records which copy to load and goes to the episode
  page `/cards/p/<slug>/`. If online and the episode is not yet open on the
  server, it submits the episode's ordinary open form instead.
- **Offline mode** (the worker served a saved copy of the list, or the user
  chose to work offline): a warning note with an `offline` tag:
  - not by choice: "The server cannot be reached. This is the episode list
    as of <date/time or 'your last visit'>. Cut lists marked downloaded open
    from this device and sync when the server is back. Opening or closing
    anything else needs the server." plus a `try the server again` link.
  - by choice: "You are working offline by choice. Cut lists marked
    downloaded open from this device, and their edits wait here until you go
    back online. Opening or closing anything else needs the server." plus a
    `go back online` button.
  Every open and close button is disabled with the tooltip "Needs the
  server, which cannot be reached."
- **work offline button** (when online): tooltip "Use the cut lists
  downloaded on this device even with the server up, as on a plane. Nothing
  goes to the server until you go back online." It stores the choice in the
  browser (shared with the episode page) and reloads `/cards/`. `go back
  online` clears it.
- When the page is served from the native Cards app's own local server
  (address 127.0.0.1 port 47823), the choice is also sent to that app
  (`POST /__app/api/offline`).

## Terminal-look page behaviour: folding windows (source: static/cc/cc.js)

`cc.js` is loaded on every page of the "terminal" look, which is now the
dashboard's only look. A **window** is a titled box on a page; its title strip
is its **bar**.

- Every window marked foldable has a fold button in its bar. Clicking it, or
  clicking an empty part of the bar (not a link, button, field, label or
  fold-out heading), folds or unfolds the window.
- Folded windows are remembered per page path in the browser's long-lived
  storage (`ccsync.fold:<path>`) and re-applied on load and after every panel
  refresh, so a timed refresh never unfolds or refolds anything. Windows
  marked not-foldable are left alone.
- A folded window is opened (without changing the remembered choice) when:
  an answer to something the person did lands inside it; a deep link
  (`#anchor`) points inside it; an error, result or refusal banner lands
  inside it; a one-time secret is shown inside it; or a settings save refuses
  a field inside it. A refusal inside a closed fold-out section is opened up
  to as well (including after timed refreshes).
- An answer marked "reveal" (for example "Read the answer" landing in a
  separate window) is scrolled into view and given keyboard focus, unless it
  came from a timed refresh.
- While the browser tab is hidden, the page is marked hidden so its
  decorative film-grain animation stops.

## Terminal-look page behaviour: tooltips and "?" buttons (source: static/cc/cc.js)

- Every element with a hover title, a tip, or a status tag/LED with a title,
  and every link, button, tab, label or field with a title, has its title
  turned into a custom floating tip (and kept as an accessible description).
  Non-control elements with a tip are made reachable by Tab.
- **Mouse (fine pointer)**: hovering shows the tip after 0.25 s, placed
  under the element (or above it near the bottom of the screen), kept at
  least 8 pixels from the edges. Moving off hides it; the pointer may move
  onto the tip itself.
- **Keyboard**: focusing an element shows its tip at once, or after 0.9 s
  for a control (so tabbing along a row of buttons does not cover the next
  one). The tip follows its control while the page scrolls. Escape hides it.
  Leaving focus, changing the `#anchor`, scrolling (other than following a
  focused control) or a refresh that replaces the element all hide it.
- **Touch (coarse pointer)**: every control with an explanation gets a small
  `?` button right after it (not in the bottom dock, side navigation,
  dialogs or fold buttons; a field inside a label uses the label's `?`).
  Tapping `?` opens the explanation sheet with the control's name and text.
  Its accessible name is "What <name> does".

## Terminal-look page behaviour: confirmation dialog (source: static/cc/cc.js)

- Every in-page action that asks a question before acting shows it in one
  shared modal dialog with OK and Cancel (when the page has that dialog;
  otherwise the browser's own confirm box). Cancel has focus by default.
- While the dialog is open, every other in-page request (including timed
  refreshes) is held back.
- Which submit button was pressed (its name and value) is carried through
  to the request after OK.
- If a timed refresh replaced the control while the question was open, the
  control is found again by its key and sent once. If it can no longer be
  found, the dialog reads "This changed while you were reading; nothing was
  sent." with only a close option.
- Cancel or Escape sends nothing; a checkbox that had already flipped is
  flipped back.

## Terminal-look page behaviour: tabs and deep links (source: static/cc/cc.js)

- Tab strips follow the standard accessible tabs pattern: click a tab to
  show its panel; Left and Right arrows move to the previous or next tab
  (wrapping), Home to the first, End to the last, moving focus.
- The last tab chosen on each tab strip is remembered per page
  (`ccsync.cctab:<path>`) and reopened on the next visit.
- A `#anchor` in the address opens the tab holding that element, unfolds
  its window and scrolls to it; done on load and whenever the anchor
  changes. Clicking an in-page link to the anchor already in the address
  (which the browser would otherwise ignore) does the same again.
- There are no single-key page shortcuts and no visual settings panel in
  this look (confirmed: none are registered here).

## Sign-in expiry warning (source: static/cc/cc.js, second block)

- On every page that states when the session ends, a non-blocking amber
  note appears at the top once the sign-in has 14 days or less to run:
  "Your sign-in expires in <N days | less than a day>. Sign in again now so
  this phone/computer keeps working offline for another 100 days."
- `Sign in again` goes to `/login?renew=1&next=<this page>`, which signs in
  again while the session is still live.
- `Not now` (tooltip "Hides this until tomorrow.") hides it until the next
  local calendar day.
- Shown only while the browser believes it is online. When online, the page
  asks `GET /api/v1/session` for the real expiry (a cached page may carry an
  old one) and redraws; failures leave the page's own value. Re-checked when
  the browser comes back online; hidden when it goes offline.

## Personal account page, in-browser helpers (source: static/cc/account.js)

Used on `/account` (the server half is described under "Personal account
page" below).

- **Password length counter** under the new-password box: "0 of <min>
  characters", "<n> of <min> characters: <k> more to go" (warning colour),
  or "<n> characters: long enough" (OK colour). The minimum comes from the
  page (12 if the page gives none).
- **Match hint** under the repeat box: "type it again", "the two match" or
  "the two do not match yet".
- **Show passwords** checkbox switches all three password boxes (current,
  new, repeat) between hidden and visible text.
- **Checks before sending**: too short gives "The new password needs at
  least <min> characters. Nothing changed."; a mismatch gives "The two new
  passwords are not the same. Nothing changed." Shown in the form's result
  slot; nothing is sent.
- **Last kind of fleet work**: on a computer's fleet-work form, unticking the
  last ticked kind is refused in the browser (because an empty list means
  "every kind"): the box is re-ticked and the page's own message for this is
  shown under the form. Nothing is sent.
- **Tick a project on one of my computers**: the add row has a project
  drop-down and one button per mode (full or upload-only). Choosing full for
  a project marked with a capacity warning first asks "<warning> Sync it
  there anyway?". It then sends the existing selection toggle request
  (`POST /partials/selection/<person>/<project>/toggle?view=none&machine=
  <computer>&mode=<mode>`), and on completion refreshes the panel.

## Admin assignment grid (source: static/cc/assignments.js)

Used only on the admin assignments page. Each cell is one project on one
computer of one person.

- **Person and computer pickers**: choosing a person refills the computer
  drop-down from data on the page: "choose a computer…", "every computer"
  (only when the person has more than one), then each computer. A person
  with one computer has it pre-chosen. The computer picker is disabled until
  a person is chosen.
- **Ticking a cell** sends `PUT /api/v1/selection/<person>/<project>
  [?machine=<computer>&mode=full]` with the page's anti-forgery token.
  Unticking sends `DELETE` for the same. A cell whose person's computer has
  never reported sends no computer (meaning every computer, or the
  unassigned bucket). The box is disabled and pulses while saving.
- **Capacity warning before ticking** (refuses nothing): when both the
  project's proxy size on the NAS and the computer's last reported free
  space are known, and the project would leave less than 20 GB free or is
  half or more of the free space, it asks "<project> is <size> of proxies.
  <computer> has <free> free.[ That is more than will fit.]" plus "Sync it
  there anyway?". Cancel unticks it again.
- **Upload-only qualifier** per cell: turning it on ticks the project as
  upload-only (ticking it if it was not); turning it off returns it to a full
  tick. It never unticks. Ticking the main box always makes a full tick;
  unticking clears the qualifier.
- **Wired computers**: after a wired computer's ticked cell is unticked, the
  box is locked with the tooltip "<computer> is wired to the NAS: it works
  directly off the tree, so a new sync cannot be ticked here".
- **Failures** roll the box back and show a red note that stays until
  clicked ("click to dismiss"): "could not tick <project> on <computer>:
  <reason>" or "could not set upload-only for ...". Successes show a green
  note for 4 s.
- **Signed out (401)** on any of these: the browser goes to the sign-in page
  with this page as the return address, and a running column stops.
- **ALL / NONE per column**: ticks (full) or unticks every cell in that
  column that differs, one at a time in order.
  - ALL first shows the capacity warning for the column total ("<n>
    projects (<k> of them measured) are <size> of proxies...").
  - NONE first asks "Untick all <n> projects for <person[ on computer]>?
    Their copies stay on disk. Nothing new comes down and proxy sync stops
    for all of them."
  - While running, the button shows "done/total" and a second click stops
    it after the request in flight ("click to stop after the change that is
    in flight").
  - At the end: "ticked all for ..." / "unticked all for ...", or "stopped
    after i of n for ...", or (red, sticky) "[stopped after i of n. ]<f> of
    <n> change(s) failed: <first six names>[, and <k> more]".
- **Copy from another computer** (drop-down per computer column): replaces
  this computer's plan with another of the same person's computers.
  - Refused in the browser if the source has nothing ticked: "<source> has
    no projects ticked. Copying it would leave <target> with nothing."
  - Otherwise asks "Replace <target>'s <n> project(s) with <source>'s <m>?"
    and either "<target> stops syncing <k> of them: <names>..." or "Nothing
    is removed from <target>."
  - Sends `POST /api/v1/admin/machines/<person>/<target>/copy-plan?source=
    <source>`, then reloads the page. Failure: "could not copy the plan:
    <reason>".
- **Filter box**: hides project rows whose label does not contain the typed
  text (case-insensitive).

## Copy buttons (source: static/cc/copy_value.js)

- Any "Copy" button copies either the text of the element it points at or a
  value stored on the button; used for one-time passwords, fresh fleet
  tokens, checksums and device ids.
- Uses the system clipboard where available (https); on plain http it falls
  back to the browser's older copy command.
- The button reads "Copied" (or its own copied label) for 2 s, then returns
  to its original label. If copying is impossible but the value can be
  selected, it is left selected and the button reads "Selected: press
  Ctrl+C"; otherwise "Could not copy". (The Ctrl+C wording is shown on macOS
  too.)

## Transfers page: open rows stay open (source: static/cc/everyday.js)

- On pages whose lists refresh by replacing only parts of the page (the
  Transfers page), every keyed fold-out row that was open stays open across
  the refresh, and closed ones stay closed.

## Home and project pages: find box and deep links (source: static/cc/home.js)

- **Find box** above the projects tree filters project rows by name as you
  type: case-insensitive and Unicode-normalised, so accented names written
  either way match; nothing is filtered while an input method (for example
  Zhuyin or Pinyin) is still composing, only when composition ends.
  - Groups with no match are hidden; groups with a match are opened while
    filtering and closed again when the box is cleared (only those it
    opened).
  - A "no match" line shows when nothing matches.
  - The filter is re-applied after each refresh of the tree, and the typed
    text survives it.
- `/` (outside a text field, no modifier, not composing) focuses the find
  box.
- A `#anchor` naming a fold-out section (for example `/#fleet-collector`)
  opens it once per anchor; folding it again is not overruled by later
  refreshes.

## Packages page: updating or rolling back this dashboard (source: static/cc/dashboard_update.js)

Admin page section "this dashboard".

- **Update button** for a newer version: asks "Update this dashboard to
  <version>? It will be offline for about ten seconds while it restarts. The
  databases are backed up first."
- **Older version on the feed** (pick from a drop-down, then press): asks
  "Roll this dashboard back to <version>? It will be offline for about ten
  seconds while it restarts. The databases are backed up first and stay as
  they are: they are not taken back to an older copy." The button is
  disabled until a version is chosen.
- After OK: sends `POST /api/v1/admin/dashboard-update/apply` with the
  version (never forced). Only one update at a time from this page.
  - Progress line "starting the update", then "working: <step>[, <message>]"
    from `GET /api/v1/admin/dashboard-update/status` every 1 s, until the
    step is "restarting", the update stops, or the status stops answering
    (taken as restarting).
  - Then "restarting: the dashboard is offline for about ten seconds", and
    `GET /api/v1/health` every 1.5 s (first after 2 s) until the expected
    version (or, with none expected, any different version) answers, for up
    to 180 s. Success reloads the page. Timeout: "the dashboard has not come
    back yet. It may still be restarting: reload this page in a minute, or
    check the container's logs."
  - A failed update shows the error in red and redraws the panel.
  - A refused apply redraws the panel and shows "Not applied: <reason>"
    above the progress line; if an update was already running, it keeps
    watching it.
- **Rollback** (tree or image, from a drop-down): an optional "restore the
  databases from <backup>" checkbox. The question names the consequence:
  restoring discards everything recorded since that backup; not restoring
  with a compatible database says "The databases are NOT restored: use a
  backup for that."; not restoring when the database is on a newer schema
  says "...Tick the restore box, or this will be refused." Sends `POST
  /api/v1/admin/dashboard-update/rollback`, waits for the version as above,
  reloads; otherwise "the dashboard has not come back yet. Reload this page
  in a minute."
- A panel redrawn while an update is already running picks up the watch and
  redraws again when it ends.
- Redrawing the panel when the server says the page is from an older build,
  or when the session expired, reloads the whole page instead.

## First-run setup wizard, browser side (source: static/cc/setup.js)

- **Error placement**: every error appears inside the step that failed (its
  form, table cell or window), unfolding its window and scrolled to the
  centre; older errors are cleared first. Server text is shown as plain
  text.
- **Step strip and step status tags**: each step shows `done`, `check
  this`, `failed`, `to do`, `skipped` (or "not listed"). The strip marks
  done or skipped steps and highlights the first unfinished step as current.
- **Licence (EULA) step**: loads the text from `GET /api/v1/setup/eula`
  ("(no EULA shipped in this build)" when none, and the accept button stays
  disabled). The accept button is enabled only once the accept box is
  ticked. Accepting sends `POST /api/v1/setup/eula` and shows "accepted
  (<detail>)". Errors: "could not load the EULA: ...", "could not accept the
  EULA: ...".
- **First admin step**: asks `GET /api/v1/setup/status`. If available, shows
  a username and password form with a `create` button ("Makes the first
  admin account and signs you in with it."), which sends `POST
  /api/v1/setup/admin` and reloads the page. Otherwise shows "not available
  in this build" (404), "an admin account already exists" (401 or 403) or
  "could not check: ...". Error: "could not create the admin account: ...".
- **Your studio step**: fields organisation name, short name, tree name,
  drive letter (canonical prefix) and template folders. When signed in they
  are prefilled from `GET /api/v1/admin/site` (never over typed text).
  Saving sends only fields that are non-blank and changed from the prefill
  (`PUT /api/v1/admin/site`); with nothing changed it says "nothing changed";
  on success "saved". Error: "could not save: ...".
- **Alert destination step**: email, webhook and a "daily still-here
  message" checkbox, sent to `POST /api/v1/setup/alerts`; shows the server's
  answer. A test button sends `POST /api/v1/setup/alerts/test`, showing
  "sending...", then "test sent to <where>." or "the test could not be sent:
  <detail>".
- **Checklist table** (`GET /api/v1/setup/tasks`), one row per task: title
  (with "(optional)"), status tag, detail, and "(you chose to skip this on
  <date>)" when a skip was recorded but the task is not skipped now.
  - The "done" row lists each outstanding step as a link to its row.
  - Buttons per row: `check` ("Looks again at how this step stands.
    Changes nothing."); the task's own action (its label, lower-cased, or "do
    it") when it can run; `skip` or `skip, I understand` (for a step that
    gates completion) on optional steps not yet skipped; `restart server`
    when the task can restart and its detail contains "RESTART SERVER". Each
    sends `POST /api/v1/setup/tasks/<id>/<check|run|skip>` and redraws.
  - A task with settings to enter (and not yet OK) shows a form in its row:
    drop-downs for fixed choices, password-style boxes for secrets ("set;
    leave blank to keep it" when one is already set), text boxes otherwise,
    and a `save and restart` button. It sends `POST
    /api/v1/setup/config/<task>`, shows "Saved. The server is restarting and
    this page reloads by itself.", then waits for the server. A "for an
    operator" fold-out shows "Container settings for these values: ...".
  - `restart server` sends `POST /api/v1/setup/restart` and shows "The
    server is restarting. This page reloads by itself."
  - Waiting for the server: `GET /api/v1/health` every 1.5 s (first after
    2.5 s); the page reloads once health answers OK on the third try or
    later.

## Settings > Site page: saving, importing, history and undo (source: static/cc/site_settings.js)

Admin-only page. Questions are asked in the page's own modal dialog (with a
named "yes" button and a "no" button that has focus), or the browser's
confirm box if the dialog is missing.

- **Save**: the settings form is sent whole to `PUT /api/v1/admin/site` as
  name-to-value pairs. Read-only (automatically worked out) fields are
  skipped; a checkbox is sent as "1" or "0"; only the chosen option of a
  radio group is sent.
  - Every result line under the save buttons shows "saving...", then "saved
    at HH:MM:SS" (local clock) or "could not save: <reason>". Each new answer
    replaces the last. Buttons keep their width while busy.
  - When the refusal text names a field, the tab holding that field is
    opened and its window unfolded.
- **Switching a reporting category off** (the per-site reporting switches,
  see "Reporting categories" below): saving with any such switch going from
  on to off first asks "Stop every computer reporting: <names>? What this
  dashboard holds about it/them is deleted for every computer now, for good.
  Sync is not affected." with the button "Stop reporting". Turning one back
  on is not asked.
- **Connection line** (information only): from the same site answer, counts
  computers reaching the dashboard over plain http: "<n> computer(s)
  reach(es) this dashboard over plain http on your network or tailnet.
  Serving it over https (Tailscale Serve does this) is recommended." and
  "<n> ... over plain http from the internet: see the alerts on the home
  page." Nothing is shown when there are none.
- **Import a settings file**: paste the text of a `site.toml`. Blank gives
  "could not import: paste a site.toml first". First a dry run (`POST
  /api/v1/admin/site/import?dry_run=1`):
  - nothing differs: "Nothing in that text differs from the current
    settings. Nothing was changed."
  - otherwise asks "This will change <n> setting(s), including <key> from
    <old or (blank)> to <new or (blank)>, ... [, and <k> more]. Apply it?"
    (first three named), with the reporting-off warning added when the
    import switches a category off. "Apply" sends the real import and
    reloads the page. Failure: "could not import: <reason>".
- **Change history**: the latest five site-setting changes from `GET
  /api/v1/admin/site/history`, each "<action, default save> by <person>",
  how long ago (s, m, h or d; exact time on hover) and "<n> setting(s)",
  plus "<n> recorded". Empty: "No site setting changes recorded yet."
  Failure: "could not load change history: <reason>". Reloaded after every
  save and every change that records history.
- **Undo the last change**: disabled until the history has loaded. Asks
  "Put back the <n> setting(s) changed by <person> <ago> (<exact time>)?"
  (plus the reporting-off warning if undoing switches one off), button
  "Undo". Sends `POST /api/v1/admin/site/undo-last-change` naming that exact
  entry's time, so it never undoes a newer change than the one named.
  Success reloads; failure "could not undo: <reason>" and reloads the
  history.

## Settings > Site page: AI providers (source: static/cc/site_settings.js)

The AI providers panel manages which AI service answers the features that
ask one. There are five providers in a fixed order (two of them are the
Claude family: "Claude Code", a command-line tool, and "the Claude API").
Two kinds: **API key** providers (a key billed per use) and **command-line
tool** providers (a program installed on the server and signed in with a
subscription).

- Loaded from `GET /api/v1/admin/ai-providers`. Failure: "could not read the
  AI providers: <reason>" in a red line.
- **Who answers window**, three lines:
  - "YouTube downloader (search terms, then relevance)": the chosen provider
    and why, or "no usable AI provider" and the reason ("nothing is
    configured").
  - "Timeline Cards (translate, semantic search, summaries)": the same answer
    if it is a Claude provider ("the same answer, and it is Claude");
    "refused" with "this site's AI provider is <X>, and Timeline Cards'
    translate, semantic search and summaries are written for Claude. Add the
    Claude API, or pin Claude." otherwise; "nothing to answer" when none.
  - "Server check (on the alerts page, when it is on)": on a build that
    locks out command-line tools, "your own Claude Code" with "This build
    does not include Claude Code or sign in to it. The check runs only if
    you installed it on this server (path below) and added a Claude API
    key."; with command-line tools off for the site, "cannot run";
    Claude Code working, "always Claude Code, whatever the order or the pin
    say"; installed but not signed in, a warning that "its runs fail and
    mail a plain summary until it is"; otherwise "cannot run: Claude Code is
    not set up on this server".
  - Header shows "pinned to <provider>", "pinned, not available" (red) or
    "auto: first available".
- **Pin drop-down**: "auto: first available in the order", then each set-up
  provider "<rank>. <name>" (a pinned one not set up is listed with "(not
  set up)"). Changing it sends `PUT /api/v1/admin/ai-providers/preference`;
  a refusal puts the drop-down back and shows "could not pin: <reason>"
  after the redraw.
- **List of set-up providers**, in order, header "<n> of <total> set up ·
  in order". An API provider counts as set up when it has a key; a CLI
  provider when it was installed here, has a typed path, or is working or
  installed-but-not-signed-in. None set up: "No AI provider is set up. The
  YouTube downloader cannot search, Timeline Cards cannot translate and the
  server check mails a plain summary. Add one below: an API key takes a
  minute."
  - Each row: rank, name, kind ("command-line tool" or "api key"), a status
    tag (available, not configured, not installed, not signed in, disabled
    by site, unknown; each with an explanatory tooltip), the last test
    result ("testing...", "test ok, <s>s" or "test failed, <s>s", details on
    hover), the key masked and whether it is "set by the deployment
    (<environment variable>)" or "stored on this server", or for a tool its
    path / "installed by set up" / version and "signed in as <account>", and
    a usage line (in use for or pinned to which features, standing by and
    why, or not used and why). A newly finished provider is highlighted
    once.
  - **manage ▾** menu per row (Escape or a click elsewhere closes it):
    - Test: one real call (`POST .../<provider>/test`), timed.
    - Pin as preferred / Unpin.
    - API key set by the deployment: a note that it cannot be changed or
      removed here.
    - API key stored here: Replace key (opens the wizard at the paste step);
      Remove key (asks "Remove the stored <name> key from this server? The
      YouTube downloader will fall back to the next available provider.",
      sends `DELETE .../<provider>/key`; failure "could not clear the key:
      ...").
    - Tool disabled by the site: a note to turn CLI tools on.
    - Tool otherwise: Sign out (`DELETE .../<provider>/signin`; failure
      "could not sign out: ...") or "Finish setting up: sign in"; Update
      (only if installed by set up); "Use my own copy" or "Change its path";
      Remove (only if installed by set up; asks "Remove <name> and its
      sign-in from this server? The YouTube downloader will fall back to the
      next available provider.", sends `DELETE .../<provider>/install`;
      failure "could not remove it: ...").
- **+ add new**: shown with "<n> more you can set up: <names>", or "All five
  providers are set up." It opens a picker of providers not set up yet, each
  with what it is and what it needs, and a cancel button.
- **Wizard for an API key provider**, steps "get a key", "paste it", "test":
  - 1: the provider's own instructions (supplied by the server), a link
    button "open <site> ↗" in a new tab, what is needed and a note that any
    spending limit is set on the provider's side.
  - 2: a hidden-text key box and "Save key". Refused in the browser when
    blank ("the key is blank") or containing a space ("the key contains a
    space: paste the key alone, with no 'Bearer' prefix"). Sends `PUT
    .../<provider>/key` with the key in the request body. Shows "saved" and
    "Stored as <masked>." or "could not save the key: <reason>". Next is
    allowed only after a save. Explains the key is stored in its own file
    readable only by the dashboard and never shown again except masked.
  - 3: "Test key" (one real call) with OK or FAILED and seconds, and a line
    saying its place in the order and whether it now answers ("<n>th in the
    order"; "It answers from now on"; or "<X> still answers first"; "Timeline
    Cards will not use it: it only runs on Claude." for a non-Claude one).
- **Wizard for a command-line tool**, steps "allow cli tools", "install",
  "sign in", "test". It starts at the first unfinished step, read from `GET
  .../<provider>/setup`. A note is shown when this server cannot run the
  tool.
  - 1: the server-supplied notice text and checkbox. Next is allowed only
    when ticked; pressing Next turns on the site feature "AI CLI providers"
    (`PUT /api/v1/admin/site` with `features.ai_cli_providers = 1`) and
    reloads the history.
  - 2: Install / Update / Try again (`POST .../<provider>/install`): "From
    <publisher>, checked against its published sha256 before anything runs.
    It goes into this server's data folder and nowhere else." While running,
    progress "<step>: <MiB> of <MiB> (<n>%)" and a meter, polled every 1 s
    (`GET .../install-status`). States shown: interrupted ("interrupted:
    ..."), error, installed ("installed: <version>", with a note when the
    publisher had no checksum and the received file's checksum was recorded
    instead). A fold-out "installed it yourself? type its full path" with a
    path box ("blank = search PATH") and Save path (`PUT .../<provider>/
    path`): a typed path wins over the installed copy. Next is allowed once
    installed or a path is saved, and not while installing.
  - 3: sign in. When the tool offers account types, an "account type"
    drop-down (subscription, or per-use console). "open <tool> sign-in ↗"
    (`POST .../<provider>/signin` with the mode) opens the publisher's own
    sign-in page in a new tab. Shows a one-time code to type there, a box to
    paste back a code from that page ("Submit code", `POST .../signin/code`;
    blank is refused "that code is blank"), "waiting for the sign-in to
    finish (<n>s left)", "starting the sign-in", "cancel the sign-in" (`POST
    .../signin/cancel`) and failure/cancel messages. Polled every 1.5 s
    while waiting. Once signed in: "Signed in as <account>." and a sign out
    button. A hint names the login command to run on the host instead.
  - 4: "Test and finish": version, signed in or not, Test, and the order
    line ("The server check uses it whatever the order says." for Claude
    Code).
  - Both wizards: back, cancel ("Closes this without going further. Anything
    already saved stays saved."), Next or Finish. The first "pick" step is a
    link back to the picker (not when replacing or managing). What was typed
    in the key, code and path boxes survives redraws. The wizard never
    shrinks while open. Errors appear as a red line at the top of the
    wizard.
- **Allow CLI tools checkbox** (under the list): sends `PUT
  /api/v1/admin/site` with `features.ai_cli_providers` 1 or 0; turning it
  off closes an open tool wizard. Status text "allowed for this site" or
  "not allowed. Adding Claude Code or Codex shows the notice and asks
  first." The terms-of-service notice text is on its tooltip. A refusal flips
  it back: "could not change the CLI provider setting: <reason>".
- **Builds that lock out command-line tools**: no tool rows, no switch, no
  notice. Instead one line "Server check, Claude Code you installed
  (optional):" with a path box (placeholder `/usr/local/bin/claude`) and
  "Save path" (`PUT .../claude_code/path`), status "path saved" or "blank:
  the server looks for claude on its PATH". The tooltip says it runs only on
  your Claude API key, never a subscription sign-in.

## Look and feel a person notices (source: static/cc/terminal.css, components.css, hud.css, phone.css, home.css, everyday.css, health.css, settings_fleet.css, settings_people.css, cards_landing.css)

Only behaviour a person would notice is listed. There are no print rules
in any of these style sheets, and no light theme.

- **One dark theme only** ("CC Terminal"): near-black background, red frames,
  cyan highlights, green / amber / red for OK / warning / fault. The browser
  is told the page is dark so native drop-downs, date pickers and scroll
  bars are dark too. Scroll bars are thin and red on dark red everywhere
  (also inside the b-roll, music and YouTube apps, which carry the same
  block). Range sliders, text selection (red) and the default focus ring
  are themed.
- **Decorations**: a faint scan-line and film-grain overlay, a glow on
  windows and keys, a dotted "DOS" drop shadow under windows, and a custom
  red crosshair mouse pointer (a text cursor stays in text fields). Fonts:
  JetBrains Mono for everything, Orbitron for big headings; if the font is
  not yet loaded the system monospace font is used rather than reflowing
  the page when it arrives.
- **Keyboard focus**: a 2-pixel cyan outline on every focused control.
- **Blinking is bounded**: fault LEDs blink four times then stop; a loading
  episode icon blinks four times; saving cells in the assignment grid pulse
  six times; nothing animates forever.
- **Reduced motion** (operating-system setting): all animations and
  transitions are switched off, including the grain overlay, LED blinks,
  the saving pulse and the loading-episode blink.
- **High-contrast / forced colours** (Windows high contrast): LEDs get a
  visible border, windows a text-coloured border, and the current page in
  the navigation is outlined and underlined, because their meaning is
  otherwise only colour.
- **Hidden tab**: the grain overlay is removed while the tab is hidden.
- **Top bar ("HUD")**, sticky at the top: brand mark and the site's short
  name (cut with an ellipsis when long), navigation, then status: counts,
  a stale-data warning, the "updated N ago" stamp (which is the first thing
  to shorten), and the user menu. Deep links and keyboard focus land below
  it, not under it.
  - Below 1600 px wide, the long "syncthing unreachable" sentence is hidden
    (the LED and "stale" stay; the sentence is in its tooltip).
  - 601 to 900 px wide (tablet): low-priority items move into a "more"
    sheet with its own button.
  - 600 px and below (phone): the navigation leaves the bar and becomes a
    fixed bottom dock with equal-width buttons; the alert count and account
    link leave the bar; the bar is 52 px tall. The page, the stale banner,
    toasts, the explanation sheet and other fixed items are lifted above the
    dock. The Settings navigation strip scrolls sideways, snapping to the
    current page.
  - Installed app: the bar extends under the phone's notch.
  - Touch screens: every top-bar, dock, menu and settings-strip control is
    at least 44 px tall.
- **Menus**: the user menu drops from the top right (up to 300 px wide);
  the "more" sheet rises from the bottom on a phone (up to 80 % of the
  screen). Both darken the page behind them.
- **Page layout breakpoints**:
  - Wider than 1100 px: a side column (300 px) beside the main column; the
    side column stays in view while scrolling.
  - 1100 px and below: one column; two- and three-column groups stack;
    form labels go above their fields; the computer rows of the fleet grid
    reflow (version column and column headings hidden); on the home page
    the projects tree comes first, above the computers.
  - 1320 px and below: three-pane app layouts drop their detail pane below.
  - 760 px and below (phone layout): tighter padding, smaller headings,
    tables become stacked cards where every cell shows its column name,
    transfer rows lose their progress bar and time left, most small text is
    raised to at least 12 px, text fields are 16 px (so iPhones do not zoom
    in on focus), long names and paths wrap rather than widening the page,
    window drop shadows are dropped.
  - Touch screens (any width): buttons, tabs, fold buttons, checkboxes,
    tags with explanations, fields and project-tree rows are at least 44 px
    tall; "?" explanation buttons appear; the "add" button on b-roll clip
    cards is always shown (no hover needed).
- **Home page specifics**: a computer row's headline wraps up to three
  lines with a mouse (all of it on touch or phone); a warning or fault
  headline is a small boxed area that scrolls inside itself (not on touch).
  The lane meter is hidden when its column is too narrow, keeping the words.
  The live-transfers box is at most 35 % of the screen height and only as
  tall as its content.
- **"Nothing shifts" rules**: result lines, the safe-to-close line on
  Transfers, the password result area and several panels reserve their
  height so the page does not jump when an answer arrives; buttons keep
  their width while their label changes to a "busy" word ("creating the
  account..." and the like) during a request; the Settings tab panels keep
  at least 60 % of the screen height; the AI wizard never shrinks while
  open.
- **Long lists live in fixed-height scrolling windows** (examples: health
  lists 620 to 760 px, checks 520 px, jobs 60 % of the screen, audit and
  checks 70 %, the assignment grid 620 px with sticky project column and
  heading row, Cards picker tree 760 px except on phones).
- **Stale banner** sits fixed at the very bottom (above the phone dock),
  and pads the page by its own height.
- **Help pages**: wide code blocks and tables scroll inside themselves
  rather than widening the page; a long document title ends in an ellipsis.
- **Notes stack** for the assignment grid sits fixed in the bottom right
  corner, above the dock.

## Help pages: the in-dashboard document reader (source: help.py, published_docs.py)

The `/help` page (its route is defined elsewhere; this part supplies what it
shows) is a reader for the product's documentation, available to anyone
signed in.

- **Which documents a reader may see**:
  - Everyone signed in: `HOW_IT_WORKS.md` (the customer explainer),
    `EDITOR_SETUP.md`, and every Markdown file under `legal/` (licence
    agreement, privacy note, telemetry note, YouTube feature notice,
    third-party notices), plus the plain-text licence files under
    `legal/licenses/` (the only non-Markdown files ever shown).
  - Admins: additionally every other Markdown file found in the docs folder
    and, on a development checkout only, the repository's top-level
    `README.md`, `SPEC.md`, `KNOWN_BUGS.md` and `CLAUDE.md` (under a "top
    level" group). Deployed servers do not receive these extra documents,
    so on a customer's server an admin sees the same set as everyone else.
  - Nobody, admins included: three legal drafts awaiting counsel,
    `legal/BETA_AGREEMENT.md`, `legal/DPA.md`,
    `legal/SUPPORT_DATA_PROCEDURE.md` (matched case-insensitively). They
    still ship inside the legal folder but are never listed or shown.
  - Anything not on these lists is treated as not published (fails closed).
- **Path safety** for a requested document: must be `.md` (or a licence
  text under `legal/licenses/`), no leading slash, no colon (so no drive
  letter or scheme), no null byte, no `..` segment, and its real location
  (after following links) must still be inside the docs folder. Any failure
  shows the not-found message.
- **Where the documents are looked for**, first found wins:
  - the folder named by environment variable `DASH_HELP_DOCS_ROOT`;
  - the folder of the file named by `DASH_HELP_DOC` (an older setting that
    names the guide file itself);
  - `docs/` inside the application folder;
  - `docs/` beside the application folder (a development checkout).
  The guide alone is also looked for at `DASH_HELP_DOC`, `<app>/docs/`,
  `<app>/` and `<app>/../docs/`.
- **Index of documents**: grouped by folder, in the order "docs/" first,
  "top level" next, then each subfolder alphabetically ("docs/<folder>/").
  Within a group the guide comes first (labelled "the customer explainer"),
  then by file name. Each entry shows the document's first `#` heading
  (read from its first 60 lines; backticks and asterisks removed) or else
  its file name; licence texts always show the file name. The index never
  lists a document this reader may not open. Linked files are skipped.
- The index is cached per reader type (admin or not) and rebuilt after 30
  seconds or when the docs folder's modification time changes.
- **Opening `/help` with no document named** opens `HOW_IT_WORKS.md`. If the
  tree cannot provide it, the single guide file is tried by the older search
  order.
- **Messages**:
  - No documents found at all: "Help is not installed on this server. The
    documents ship as the docs/ tree (the guide itself is
    docs/HOW_IT_WORKS.md); ask whoever deployed this dashboard to put a copy
    beside the application."
  - A document that is missing or refused: "That document is not on this
    server. It may be one this build does not ship, or the link inside the
    document you came from may be stale." The page still shows the index,
    and is flagged so the route answers with a not-found status.
- **Licence texts** are shown exactly as written, in a preformatted block,
  titled with the file name.
- **Markdown rendering** (a built-in subset; no HTML in a document is ever
  passed through, everything is escaped):
  - headings 1 to 6, each with a stable anchor id made from its text with
    any leading section number removed (for example "4.1 Your sync plan"
    becomes `#your-sync-plan`); repeated headings get `-2`, `-3`;
  - a table of contents of every level 2 and 3 heading;
  - paragraphs, bullet and numbered lists with one level of nesting
    (numbered steps separated by blank lines stay one list), fenced code
    blocks, pipe tables (scrolling sideways when wide), horizontal rules,
    inline code, bold, italic and links;
  - in the section titled "Glossary", each table row gets an anchor
    `#term-<first cell>` so other pages can link to one term;
  - links: `http(s)`, `mailto:`, site-absolute and `#` links are kept; any
    other scheme (for example `javascript:` or `data:`) is shown as plain
    text; a relative link to another document is rewritten to its
    `/help/<path>` address (keeping the `#section`), resolved as if the
    documents sat in the repository; a relative link to anything else (a
    script, an image, a path outside the tree) is shown as plain text
    followed by the path in brackets.
  - The page title is the document's first `#` heading, or its path.

## Personal account page: the page and who it is about (source: account_ui.py, account_api.py)

- `GET /account`: any signed-in person. Always about the signed-in person:
  an `?as=<other person>` parameter is ignored (the side panel is pinned to
  them too). Not signed in: 401 "Sign in first." (every route in this
  section answers that when there is no session).
- The page shows: the person's sign-in name, display name and "shown as";
  whether they are an admin and why (the source of their admin rights);
  sign-in method; password facts; whether the account is suspended; each of
  their computers (remote editing machines and wired "base rig" machines
  listed separately); site facts: drive prefix (default `P:\`), whether
  automatic updates are on, whether YouTube downloads are on, whether the
  fleet is halted.
- **Computers listed** are exactly the person's rows from the fleet grid,
  plus their "lost" computers (no longer heard from). For each:
  platform, wired or remote, CCSync version and the current version ("up to
  date" when they match or no current version is known), last report time,
  whether it is live (report fresh), why it is in its state, the licence
  line and which reporting categories it withholds, its sync plan (project
  and mode, full or upload-only), fleet-work facts, the settings it last
  reported, and any pending settings request.
- **After a password change** the page is opened as
  `/account?changed=password&others=<n>` and shows a confirmation; `others`
  is clamped to 0..999; when missing or unreadable the page says the
  password changed but it cannot say whether other browsers were signed
  out. Any other `changed` value shows nothing.
- `GET /api/v1/me/account`: the same data as JSON for the signed-in person.
  The anti-forgery token is never included.

## Personal account page: display name (source: account_api.py, account_ui.py)

A display name is a label shown to other people instead of the sign-in
name; it is never used as an identity (audit records, sessions, sync plans
always use the sign-in name).

- `PUT /api/v1/me/display-name` (JSON `display_name`, at most 256
  characters before cleaning) and the page form `POST
  /partials/account/display-name` (field `display_name`): set or clear your
  own.
  - Empty text clears it ("Cleared. Other people now see your sign-in
    name."). Unchanged text changes nothing.
  - The text is Unicode-normalised and its whitespace collapsed.
  - Refusals (422): only whitespace: "A name cannot be empty. To go back to
    your sign-in name, clear the box and save."; more than 64 characters: "A
    name can be at most 64 characters."; invisible or control characters: "A
    name cannot contain invisible or control characters."
  - Refused 409 "Someone else already goes by that name. Pick another." when
    it matches another person's sign-in name (any known editor, local
    account, configured admin) or another person's display name. Your own
    sign-in name is allowed.
  - Success: "Saved. Other people now see <name>."
  - Each change is recorded in the audit log (before and after) under the
    action for own display-name changes.
  - On the page, the "you" panel is redrawn with the answer and what was
    typed; a refusal is shown as a red line (status 200), not an error.
- `PUT /api/v1/admin/users/<username>/display-name` and `POST
  /partials/admin/users/display-name` (fields `username`, `display_name`):
  admins only (403 "admins only" on the page route); set or clear another
  person's name with the same rules. Unknown or invalid username: 404
  "There is no account called <username>." The Users panel is redrawn with
  "<username> is now shown as <name>." or "<username> is shown by their
  sign-in name again." or the refusal. Audited under the admin action.
- Display names are cached for 30 seconds for page drawing and refreshed
  immediately after any change made here. If they cannot be read, sign-in
  names are shown.

## Personal account page: change your own password (source: account_api.py, account_ui.py, account_password.py)

- `POST /api/v1/me/password` (JSON `current_password`, `new_password`,
  `new_password_again`) and the page form `POST /partials/account/password`.
  Any field over 1024 characters or not text: 422 "A password must be text
  of at most 1024 characters. Nothing changed." (the typed value is never
  echoed back).
- **Checks, in order, before anything changes** (status in brackets):
  1. Single sign-on site (OIDC): "You sign in with your organisation's
     account, so there is no password here to change. Change it where your
     organisation looks after its accounts." (409). Any sign-in method other
     than server (SMB) or local: "This dashboard does not know how to change
     passwords for its sign-in method. Ask your admin. Nothing changed."
     (409).
  2. New passwords differ: "The two new passwords are not the same. Nothing
     changed." (422).
  3. Too short (the shared minimum length): "The new password needs at least
     <n> characters. Nothing changed." (422).
  4. Same as current: "The new password is the same as the current one.
     Nothing changed." (422).
  5. Sign-in throttle (shared with the sign-in page, so wrong guesses here
     count against the same budget): 429 with the throttle's wait message
     and a Retry-After header.
  6. Local sign-in and no local account row (for example a configured admin
     name with no account): "<user> is not an account this dashboard keeps a
     password for. Ask another admin, or change it where that account
     lives." (409).
  7. The current password is checked exactly as at sign-in. Checker busy:
     "The server is busy checking other sign-ins. Try again in a minute.
     Nothing changed." (503). Wrong: "That is not your current password, so
     nothing changed. Several wrong tries in a row make this form wait, like
     the sign-in page." (422) and a sign-in failure is recorded. Right: the
     failure count is cleared.
- **Setting it**:
  - Local sign-in: the dashboard's own stored password is replaced.
  - Server (SMB) sign-in: the NAS account's password is changed. No NAS
    credential configured: "This dashboard holds no server credential, so it
    cannot change server passwords. Ask your admin." (503). NAS unreachable
    or its client cannot be set up: "Could not reach the server, so nothing
    changed. Try again in a minute." (502). Account is not one the
    dashboard may manage (not an editor on the NAS): "The server does not
    let this dashboard change the password of <user>. Change it in the NAS's
    own settings, or ask your admin." (409). NAS refuses: "The server
    refused the change, so nothing changed. Try again, or ask your admin."
    (502). NAS error text is written to the log with anything resembling
    either password masked, never shown.
- **After a change**: an audit record (method and how many other sessions
  existed; never the password or its length) and a warning-level log line.
  Then this browser gets a fresh session cookie and every other signed-in
  browser of this person is signed out. Fleet tokens and computer
  identities are not touched. If the fresh session cannot be created, the
  other browsers are still signed out and this one keeps its old session.
- Answer: `ok`, the method, how many other browsers were signed out (or
  unknown), and a new anti-forgery token. The page form instead redirects
  the browser to `/account?changed=password[&others=<n>]`; a refusal is
  shown in the form's result slot.

## Personal account page: signed-in browsers (source: account_api.py, account_ui.py)

- `GET /api/v1/me/sessions` and the panel `GET /partials/account/sessions`:
  your own live browser sessions (expired ones not yet cleaned up are
  hidden): a 12-character handle (never the full session id), IP address,
  browser description, when it signed in, when last seen, and whether it is
  this browser. The panel also counts the others. When the server keeps no
  session records: 503 "Signed-in browsers are not being recorded on this
  server." (shown in the panel as its message).
- `POST /api/v1/me/sessions/<handle>/revoke` and `POST
  /partials/account/sessions/revoke` (field `handle`): sign out one of your
  OTHER browsers. Refusals: handle not 12 lowercase hex characters: 422
  "That is not a browser on this list."; not found among your live
  sessions: 404 "That browser is already signed out."; matches more than
  one: 409 "Two browsers match that; use sign out the others instead.";
  it is this browser: 409 "That is this browser. Use Sign out instead."
  Another person's session is never matched. Success on the page: "Signed
  that browser out." Audited.
- `POST /api/v1/me/sessions/revoke-others` and `POST
  /partials/account/sessions/revoke-others`: sign out every browser but this
  one. If this browser's session cannot be identified: 503 with the
  not-recorded sentence. The count reported is of live other browsers
  (capped by what was actually signed out). Page: "Signed out <n> other
  browser(s). This one stays signed in." or "No other browser was signed
  in." Audited.

## Personal account page: your sync keys (read only) (source: account_api.py, account_ui.py)

A sync key is the SSH key a computer uses to upload and download.

- `GET /api/v1/me/sync-keys` and the panel `GET /partials/account/sync-keys`
  (loaded after the page so a slow NAS never holds it up).
- Lists keys waiting for approval (fingerprint, computer, when submitted)
  and approved keys (fingerprint, computer, comment up to 64 characters,
  when added). The key text itself is never returned.
  - Local sign-in: approved keys come from the dashboard's own key list
    (computer = the key's label).
  - Server (SMB) sign-in with a NAS configured: approved keys are read from
    the NAS account; each key's computer is taken from the newest approval
    record in the audit log. If the NAS shows only "(installed)" (Synology
    cannot show key text), the page is told the keys exist but cannot be
    listed. If the NAS cannot be asked: "The server could not be asked which
    keys are approved just now." (the NAS's own error is only logged).
  - Single sign-on: no approved keys are looked up.
- Says whether a key is needed: not needed only when every one of the
  person's computers is a wired base rig; a person with no computers yet
  still needs one.
- Adding, approving and removing keys is not possible here (it stays on the
  admin Users page).

## Personal account page: asking one of your computers to change its fleet-work settings (source: account_api.py, account_ui.py)

"Fleet work" is jobs the dashboard hands to idle computers (transcribing,
preview copies, audio extraction, waveforms). Only two settings can be
asked for: whether the fleet may use the computer, and which kinds of work
it takes. The ask is delivered with the computer's next report and takes
effect when CCSync next starts there.

- `POST /api/v1/machines/<person>/<computer>/settings` (JSON
  `jobs_enabled` true/false and/or `jobs_kinds` list) and the page form
  `POST /partials/account/machines/settings` (fields `editor`, `machine`,
  and either `jobs_enabled` or `jobs_kinds` with a `jobs_kinds_sent`
  marker; two separate forms so each click asks only for what it changed).
  - Who: the computer's owner or an admin, otherwise 403 "Only the person
    this computer belongs to, or an admin, can change it." Computer names
    are matched exactly. Unknown computer: 404 "<person> has no computer
    called <computer>."
  - Any other key (including wired/remote mode, which can never be asked
    for), an empty body or a non-object: 422 "Only these can be changed
    from here: whether the fleet may use the computer, and which kinds of
    work it takes."
  - `jobs_enabled` not true/false: 422 "Let the fleet use this computer must
    be on or off."
  - `jobs_kinds` not a list: 422 "The kinds of work must be a list."; empty
    list: 422 "That is the last kind of work this computer takes. Untick Let
    the fleet use this computer instead." (the page refuses this before
    sending); an unknown kind: 422 "<kind> is not a kind of fleet work."
    Duplicates are dropped; naming every kind is stored as "every kind".
  - The computer has never reported: 409 "<computer> has not reported yet."
    The computer does not say it accepts every key asked (an older CCSync):
    409 "<computer>'s CCSync is too old to change this from here. Update it,
    or change it in its tray: Settings, FLEET JOBS."
  - When no request is pending and both the running values and what is
    saved on the computer already match, nothing is stored: "Nothing to ask:
    it already works that way." When the running value cannot be read
    (unknown or a kind this dashboard does not know), it is treated as
    different.
  - Otherwise the request is stored (one pending ask per computer) and
    logged.
- `DELETE /api/v1/machines/<person>/<computer>/settings` and `POST
  /partials/account/machines/settings/withdraw`: withdraw a pending ask.
  Same permission checks. Page: "Withdrawn. Nothing is asked of it now." or
  "There was nothing waiting to withdraw."
- On the page, after an ask or withdrawal for one of your own computers,
  that computer's fleet-work section is redrawn with the result; for
  another person's computer (only reachable by a hand-built request) only
  the result line comes back.
- **Request status line** under each computer:
  - pending, not yet delivered: "Asked <ago>. <computer> gets it the next
    time it reports in." (grey)
  - pending, delivered: "Sent to <computer> <ago>. Waiting for its answer."
  - pending with a problem reported: "<computer> could not save it yet and
    will try again: <detail>" (amber)
  - applied but waiting for a restart, or the running value does not yet
    match, or is not reported: "<computer> saved it. It takes effect the
    next time CCSync starts there."
  - applied and running: "In effect." (green), shown for 10 minutes after
    the answer, then nothing.
  - refused: "<computer> refused: <detail>" (red)
  - expired: "<computer> did not report in for 14 days, so the request was
    dropped." (amber)
  - withdrawn or none: no line.
- **The tick boxes** show what the computer WILL do: a pending ask if any,
  else what is saved there awaiting restart, else what is running. Kinds
  are worded: "Transcribe audio (uses the graphics card)", "Make small
  preview copies of video", "Pull the audio out of video", "Draw audio
  waveforms"; any other kind shows its short label. "Every kind" ticks all.
- **Fleet-work status words**: lost computer: "Not taking work: not heard
  from" (red); switched off: "Not taking work: switched off on this
  computer"; a gate reason reported by the computer is shown as is
  (amber); on and wired: "Taking fleet work"; on and remote: "Taking fleet
  work while nobody is using it" (green); else "not reported".
- **Idle**: wired: "no wait (a computer wired to the server is exempt)";
  else "<n> s with nobody using it" under a minute, "<n> min with nobody
  using it", or "not reported". The job running now: "<label>[ on <file>][,
  <n>%]". Graphics card name and memory are shown when reported.
- **Read-only settings the computer last reported** (blank when not
  reported), each with where to change it:
  - "lend it to the fleet for" <n> min (tray: Settings, FLEET JOBS);
  - remote computers only: "drive reminder": "the first warning only" (0)
    or "every <n> min" (the computer's config file; tray: Settings, SYNCING
    mutes one);
  - only when the site has YouTube downloads on: "YouTube terms" (accepted
    / not accepted, plus "downloads off on this computer") and "YouTube
    sign-in" (signed in / signed in, needs a refresh / expired: sign in
    again / not signed in / not used on this computer) (tray: Settings,
    YOUTUBE).
- **Settings cannot be asked** (shown instead of the controls) when the
  computer has not reported or its CCSync is too old, using the sentences
  above.
- **Adding a project to one of your remote computers**: a list of active
  projects not yet in that computer's plan, each carrying a capacity
  warning when the project's proxies would not fit comfortably in the
  computer's last reported free space (the same rule as the assignment
  grid). Upload-only plan rows carry the same warning for switching to
  full sync. Wired computers get neither.
- `GET /partials/account/computer?machine=<name>`: one computer's panel
  (the page refreshes it on a timer). A computer that is no longer the
  person's answers empty, so the panel disappears.
- Form bodies are capped at the dashboard's form-field limit; a malformed
  body is 400 "malformed form body".

## Personal-data export ("give me everything you hold about me") (source: subject_data_api.py, subject_data.py)

- `POST /api/v1/me/export`: any signed-in person downloads their own data.
  The subject is always the signed-in person (no `?as=` or scope can change
  it).
- `POST /api/v1/admin/users/<username>/export`: an admin downloads anyone's
  data. Not an admin: 403 "Only an admin can do this for another person."
  Invalid name: 400 "That is not a user name this dashboard can hold."
  Nobody known by that name: 404 "This dashboard holds nothing about
  <username>." A person counts as known if they have an account, a
  configured admin entry, a display name, a computer in the fleet, any row
  in the dashboard's records about them, or any sign-in session record.
- Both are POST only and require the anti-forgery check (no GET exists).
  Not signed in: 401 "Sign in first."
- **Limits** (per subject, counted in memory, forgotten on restart):
  - one export at a time: 429 "An export of <username>'s data is already
    being made. Try again when it has finished." (Retry-After 30 s);
  - at most 5 exports per hour, counted separately for the person's own
    copies and for admin copies, and only counting exports actually handed
    over: 429 "<username>'s data has been exported <n> times in the last
    hour. Try again later." (Retry-After = seconds until the oldest drops
    out);
  - at most 50 MB: 413, for an admin "The export of <username>'s data is
    larger than 50 MB, so it was not made. Erase their history first, or ask
    for a copy by other means.", for the person "Your data is larger than 50
    MB, so the file was not made. Ask an admin for a copy by other means."
- **When sent from a plain browser form** (not a script), a refusal other
  than 401/403 is shown as a small HTML page with the sentence and a "Go
  back" link (to `/admin/users` or `/account`), with the same status code.
- **The file**: downloaded as `ccsync-data-<username>-<YYYY-MM-DD>.json`
  (UTC date), not cached, indented JSON with: when generated, dashboard
  version, the subject, every table of records naming the person, and a
  "not included" list. Binary values are written as base64; dates as ISO
  text.
- **What it gathers** (all read-only):
  - every dashboard database table that names a person (secret columns
    removed);
  - sign-in sessions and failed sign-ins under the name (from the session
    store);
  - YouTube requests, downloads and rights confirmations (from the YouTube
    feature's own records);
  - client folders and clips added to them (`client_folders.created_by`,
    `client_folder_items.added_by` in the b-roll app's `client_shares.db`);
  - b-roll and music indexing batches (`ingest_batches` rows where the
    person is the editor, canceller or cancelled-by, in `broll.db` and
    `music.db`).
  Names are matched case-insensitively in the other stores. Columns named
  `token`, `token_hash`, `sid`, `sid_hash`, `password_hash` or `secret` are
  never exported from them (a client folder token is the link itself).
- **"Not included" always lists** (in plain words): files on the person's
  own computers including `~/.ccsync`; files on the storage server and
  Syncthing's database; the text of server triage reports (mailed, runs
  deleted after 60 days); Timeline Cards working records (kept per episode);
  sign-in throttle records kept by network address; snapshots of the
  dashboard's storage. **And adds**, when it happens, a sentence for each
  store that could not be read: "<what>: not available on this dashboard, so
  it could not be read." (store not mounted), "<what> (<table>): could not
  be read just now.", "<what>: this dashboard version cannot read them
  yet.", or the store's own reason.
- Every export is written to the audit log with counts only (rows per
  table, total rows, bytes), never the data.

## Erase a person's history, keeping their account (source: subject_data_api.py)

- `POST /api/v1/admin/users/<username>/erase-history` (JSON answer) and the
  Users panel's button `POST /partials/admin/users/erase-history` (field
  `username`). Admins only (403 "Only an admin can do this for another
  person."), same name checks and 404 as the export.
- Removes, in order: the dashboard database's past-history records about
  the person (current state is never touched); then revoked sessions in the
  session store (live sessions stay); then the person's YouTube history.
- A store that cannot be reached is listed as not done ("sessions",
  "ytdl") and the rest still runs. An audit record carries the counts
  removed per table, the total and what was not done.
- Answer: `ok`, the username, counts removed per table, total, and what was
  not done. The Users panel is redrawn with "Erased <n> past record(s) about
  <username>. Their account and their computers' current state are
  unchanged." plus " Some stores could not be reached; press it again
  later." when anything was not done; a refusal is shown as the panel's
  error line.

## Deleting a person: client-folder names replaced (source: subject_data.py)

Used when a person is deleted (the deleting route is outside this part).

- In the b-roll app's `client_shares.db`, every client folder's "created
  by" and every clip's "added by" that names the person (case-insensitive)
  is replaced with the person's stand-in name (a pseudonym derived from a
  salt kept in the dashboard database; minted and saved on first use, so
  the same person always gets the same stand-in). Client links keep
  working. Free-text fields (contact, description, notes) are not changed.
- Nothing to do when the dashboard has no client folders. If no stand-in
  can be made, or the file cannot be opened or written, the deletion is
  reported as failed for this part (so the admin is warned).
- The b-roll and music indexing batch records are not edited (they are
  replaced whole when an index is published).

## Reporting categories: what the dashboard strips from computer reports (source: telemetry_fields.py)

The dashboard can be told that a category of report data must not be kept
(per site switch, or because the computer says it withholds it). It removes
the same fields from every incoming report, whatever CCSync version sent
it, before anything is stored.

- Four categories: `resolve_project`, `local_manifest`, `media_tree`,
  `input_idle`. Switching off `resolve_project` also switches off
  `media_tree`. Unknown category names are ignored.
- **resolve_project** removes: the open Resolve project, the Resolve project
  in the computer's capabilities, the open-project fields of the Resolve
  health check, the list of unopened projects with clips only on that
  computer, each Resolve undo journal's project name, and the media tree.
  It masks rather than removes: each undo journal id becomes
  `withheld:project/<file name>`, and each undo answer's text has quoted
  project names replaced by `<project>` and journal ids masked the same way
  (or, if that fails, "(detail withheld: this computer does not report
  project names)"). Effect: undoing a Resolve change from the dashboard
  stops working for an older CCSync that does not understand the masked id.
- **local_manifest** removes: the computer's local file list, the missing
  clips and refused non-canonical paths of the Resolve health check, the
  file paths of sync conflicts (the count stays), stray projects and moved
  project folders (whole, so they read as "not reported"), and sample file
  names of "skipped, exists" uploads (counts stay).
- **media_tree** removes the media tree.
- **input_idle** removes how long the computer has been idle (which also
  means fleet-work idle times read as not reported).
- Never removed, because sync or the editor's own action needs them:
  transfer names, completed transfers, applied file moves, the Timeline
  Cards agent's timeline.
- If a field cannot be removed, its whole top-level section is dropped and
  an error is logged; if even that fails, the report is refused rather than
  stored with withheld data.

## Looks redundant or overlapping

- Two separate explanation surfaces for tooltips: `htmx_errors.js` block 2
  (tap a chip to open the sheet) and `cc.js` (floating tips, "?" buttons
  that open the same sheet via its own function). Both run on every page;
  both make tipped elements keyboard-focusable.
- Two confirmation mechanisms: `cc.js`'s shared modal dialog for in-page
  actions, plus native `window.confirm` in `confirms.js`, `assignments.js`,
  `account.js`, `dashboard_update.js`, and a third modal (`#site-ask`) in
  `site_settings.js`.
- Three "keep panels stable across refreshes" mechanisms: `htmx_errors.js`
  block 4 (skip a poll while editing), `everyday.js` (keep fold-outs open
  across partial swaps), `cc.js` folds re-applied on load; plus
  `tab_memory.js` remembering open fold-outs per page.
- Two "remember view per page" stores: `tab_memory.js` (`ccsync.tab:`
  scroll and open sections) and `cc.js` (`ccsync.fold:` folded windows,
  `ccsync.cctab:` last tab).
- Two `/` keyboard shortcuts to a search box (`cards_landing.js`,
  `home.js`), written separately.
- Two service workers and two registrations: the dashboard's `/sw.js`
  (pwa.js) and the Cards worker `/cards/sw.js` (cards_offline.js, whose
  worker code lives outside this part).
- Two "wait for the server to come back, then reload" loops polling
  `/api/v1/health` (`dashboard_update.js`, `setup.js`) with different
  timings.
- Two capacity-warning implementations: the browser rule in
  `assignments.js` (20 GB / half of free space) and the server's sentence
  used by the account page; the browser copy claims to mirror the server.
- Display-name setting for oneself and for others exists as both JSON
  routes and page partials (four routes for one feature); likewise the
  session sign-out and machine-settings routes each have a JSON and a page
  twin.
- `AI CLI providers` can be switched by the checkbox under the list and by
  accepting the notice in the tool wizard (both write the same setting),
  and also through the site settings form generally.
- Several style sheets restate the 12 px phone font floor for their own
  classes because the shared list cannot reach them (home, everyday,
  settings_fleet, settings_people).
- `[hidden] { display: none !important; }` is declared three times in
  components.css; `details.fold > summary` rules are declared twice there.
- `@font-face` for JetBrains Mono is declared in both terminal.css and
  hud.css.

## Claims the code does not back

- `cc/account.js` says it is "a fork of static/account.js" and that "the
  classic file is untouched"; `cc/setup.js` says `static/setup.js` "stays
  frozen for the classic page"; `cc/site_settings.js` says the same of
  `static/site_settings.js`; `cc/copy_value.js` and `cc/assignments.js`
  refer to classic originals. None of those classic files exist in
  `dashboard/static/`.
- `cc.js` header and `terminal.css` say a hidden tab "stops the grain"
  animation; the grain overlay has a `grain` keyframe defined but no rule
  applies it, so there is no grain animation to stop (the overlay is merely
  hidden).
- `everyday.js` says the Transfers page polls "every two seconds"; the
  interval is set in a template outside this part and could not be
  confirmed here. Likewise `account_ui.py` says a computer panel refreshes
  "every 30 s" and `htmx_errors.js` says the fleet grid refreshes every 15
  s; those intervals live in templates.
- `hud.css` describes rules for "classic pages under the HUD" (project tree
  offsets, sheet handle, toast host); the classic look is retired, so those
  rules have nothing to apply to.
- `pwa.js`'s install button: the comment says the slot is in the HUD's
  "more" sheet; whether the template provides `#install-slot` could not be
  confirmed here.
- `help.py`'s docstring says the guide is "788 lines"; not verifiable from
  code and irrelevant to behaviour.
- `assignments.js` says its capacity rule "MIRRORS health.capacity_warning";
  the server function is outside this part and was not checked.

## Could not determine

- Which pages load which scripts and style sheets, and the exact polling
  intervals of panels, are set in templates outside this part.
- What `fonts/manifest.json` (font checksums) is used for; nothing in this
  part reads it.
- The exact text of the sign-in throttle message, the minimum password
  length value, and the health-check capacity sentence (defined outside
  this part).
- The route that serves `/help` and `/help/<path>` and whether it sets the
  404 status (it is in `ui.py`, outside this part).
- What `/cards/sw.js` itself caches (its code is in `cards_landing.py`).
- What `db.purge_subject_history` counts as "history" versus current state,
  and which tables `db.fetch_subject_rows` covers (defined in `db.py`).
- Whether the `#site-ask`, `#cc-confirm`, `#chip-sheet` and
  `#install-slot` elements exist on every page that loads the matching
  script.
- `htmx.min.js` was not read line by line (it is the minified third-party
  library, named per the brief).



