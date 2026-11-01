# Pre-launch practicality pass: a working editor's day (`prac-editor-daily`)

Reviewed 2026-10-06 against HEAD 08b40eb plus the uncommitted working tree. Read-only; one
throwaway probe (`loopback_guard.allowed_origins` / `origin_allowed` against typical
Tailscale and LAN addresses) run in the scratchpad with the companion venv.

**What I covered:** the tray menu (`tray._build_menu`), the Settings window
(`settings_window.build_settings_model`, `_build_settings_window`), the out-of-tree popup
(`popup.py`, `fixer.IgnoreTracker`), pause/resume (`app.toggle_pause`), unattended and pushed
updates (`app._maybe_auto_update`, `apply_upgrade`, `_standing_down_would_kill_work`), the
drive reminder (`drive_reminder.py`), the grade swap (`drive_swap.py`), project removal,
the dashboard tick/queue UI (`home_macros.ticking_for`, `home_queue.html`), file moves
(`api._require_move_write`), b-roll Send to Resolve (`broll/web/static/app.js` sendToResolve,
`broll_server.handle_insert`, `loopback_guard.py`), YouTube in Settings, and the Timeline
Cards companion role (`timeline_cards_role.py`). Docs: `EDITOR_SETUP.md`, `HOW_IT_WORKS.md`
(served in-product at `/help`), `MOBILE.md`, `LOOPBACK_API.md`, `FILE_MOVES.md`,
`UPLOAD_ONLY_TICK.md`. Checked against `KNOWN_BUGS.md` and the 2026-09-03 sweep reports.

**What I did not cover:** the music SPA's own send path line by line (I assumed it has the
same shape as b-roll's), the YouTube web flow end to end, the Mac-specific tray, and the
first-day install journey. Those belong to other lenses.

---

### prac-editor-daily-1 - Send to Resolve is refused for anyone browsing the dashboard at a different address, and the page blames the browser
- **Severity:** high
- **Confidence:** CONFIRMED (code read end to end, plus a probe)
- **Where:** `companion/src/ccsync_companion/loopback_guard.py:205-249` (`origins_for_url`, `allowed_origins`); `companion/src/ccsync_companion/broll_server.py:2067-2086` (refusal: `_refuse(403)` with no CORS headers); `broll/web/static/app.js:1935-1949` (catch branch toast); `dashboard/src/ccsync_dashboard/site_store.py:77,185` (one `dashboard_url`); `docs/MOBILE.md` §1 recipe
- **What:** The allow-list is the host:port of ONE `dashboard_url` (from config, or the site manifest), in both schemes. The probe: with `dashboard_url = http://100.64.0.1:8480`, these are all refused: `https://nas.tail1234.ts.net` (Tailscale Serve on 443), `https://nas.tail1234.ts.net:9443` (the MOBILE.md recipe), `http://192.168.0.102:8480` (a wired editor on the office LAN), `http://nas:8480`. The docstring says "both schemes for the one host" covers the Tailscale Serve move, but Serve changes the host AND the port, so it does not. A refused Origin gets a 403 with no `Access-Control-Allow-Origin`, so the browser turns it into a network error and the page lands in the "could not reach" branch. The page then says: "open http://127.0.0.1:8899/status - if that shows ok:true, it's the browser, not the CC Sync tray". `/status` opened in a tab does answer ok, so the editor is told it is their browser, and they go looking for a local-network permission that does not exist. The real fix is a hand edit of `loopback_extra_origins` in `~/.ccsync/config.toml` on every machine, or the admin changing the site's one URL, which then breaks everyone browsing the other address. No alert kind exists for it (CMEDIA-5's `loopback_origin_mismatch` half is unbuilt).
- **Scenario:** A customer follows MOBILE.md and moves `dashboard_url` to `https://nas.<tailnet>.ts.net:9443` so phones can install the app. The editors in the office keep their `http://192.168.x.x:8480` bookmark. From then on, every Send to Resolve (b-roll and music) and every local YouTube dispatch silently fails for them. Each editor is told it is their browser. The vendor gets ten support tickets, and the fix is a config file edit on ten machines.
- **Recommendation:** (1) Make the origin list plural and learned. The dashboard records the scheme://host:port its logged-in sessions actually arrive on (the `Host` / `X-Forwarded-Host` of authenticated requests) and publishes them as `dashboard_origins` in `/api/v1/site`. The companion trusts that list, and the admin can prune it under Settings. (2) Answer a refused Origin with a body the page can read. A 403 that carries ACAO for that one response and says only "this computer's CC Sync does not know the address you are browsing (<origin>)" leaks nothing. Have the page show exactly that, plus "ask your admin to add this address", not the browser advice. (3) Put the refusal in the next report and build the `loopback_origin_mismatch` alert.
- **Known:** ops note under the loopback CR in KNOWN_BUGS.md (~line 552, "every companion's `dashboard_url` must equal the origin editors actually browse"); usability sweep CMEDIA-5 (copy half done, alert half open). Still open.

### prac-editor-daily-2 - A b-roll clip that is not on disk yet is inserted only if the editor keeps the tab open, and it lands wherever Resolve is by then
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `broll/web/static/app.js:1869-2020` (`sendToResolve`: `sendInFlight` lock, `for (;;)` re-POST every 1.5 s); `companion/src/ccsync_companion/broll_server.py:1100-1112` (docstring: "the poll that finds the file in place falls through to the ordinary insert"); `companion/src/ccsync_companion/broll_fetch.py:138-164,519-529` (`FetchJob.cancel` only reachable from `stop_all` at shutdown); `docs/HOW_IT_WORKS.md` §9.2 ("inserts it when it arrives")
- **What:** For a clip not on this computer, the companion starts a fetch, and the INSERT happens only when the browser's next re-POST finds the file in place. Four consequences follow. (a) If the editor closes the tab, navigates away or the laptop sleeps, the original downloads and is never inserted, and nothing says so. (b) The insert targets whatever project, timeline and playhead Resolve has when the download finishes, which for a 40 GB original over a remote link is many minutes after the click. "Place at playhead" then lands at a playhead the editor has since moved, possibly in another timeline. (c) `sendInFlight` disables every Send button on the page for the whole download, so the editor cannot queue a second clip. (d) There is no cancel. `FetchJob.cancel()` exists but no UI reaches it. The in-product help promises the opposite of (a).
- **Scenario:** On deadline, an editor sends a 30 GB drone original from the archive. The page says "syncing it down, then inserting". They switch to another timeline to keep working and close the b-roll tab. Twenty minutes later the file is on disk but not in any timeline. If they had left the tab open, it would have been placed on top of the timeline they were now cutting.
- **Recommendation:** Make the companion own the pending insert. At the click, capture the target (project name, timeline unique id, and record frame for playhead mode). When the fetch completes, insert into that target if it is still current, otherwise put the clip in the B-Roll / Archive bin and send a balloon ("drone_014 is in your Archive bin. The timeline you sent it to is not open"). Show pending sends as a list with a CANCEL that calls `FetchJob.cancel`, and let several queue (the companion already caps concurrent fetches at 2). Fix HOW_IT_WORKS §9.2 to match whatever ships.
- **Known:** usability sweep 2026-09-03 cross-cutting note (`for(;;)` with no cancel, `FetchJob.cancel()` unreached). Still open; the queue-wait cap (CMEDIA-7) was built, the rest was not.

### prac-editor-daily-3 - "Pause syncing" is forgotten at every restart and does not stop folder sync
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/app.py:1723` (`self._paused = False` at construction, nothing persisted), `app.py:10075-10126` (`toggle_pause`: "Lane C's poll loop ... keeps running regardless of pause state"); `docs/HOW_IT_WORKS.md` §6.6 ("for a laptop on a hotspot. Folder sync keeps running")
- **What:** Pause lives in memory only. Any restart un-pauses silently: the tray's own Restart CCSync, a pushed or unattended update, the supervisor relaunching after a crash, logging off, or a reboot. Nothing tells the editor it happened. Folder sync (Syncthing: audio, AE, subs, every non-video file) is never paused at all, so on a metered hotspot the button stops some traffic, not all of it. The stated use case is exactly the one it does not serve.
- **Scenario:** An editor on a tethered phone pauses syncing and keeps cutting. An admin pushes an update an hour later (or the tray crashes and is relaunched). The companion comes back un-paused and starts uploading the day's 60 GB of card dumps over the hotspot. Meanwhile a 4 GB AE project folder has been syncing the whole time.
- **Recommendation:** Persist the pause in `~/.ccsync/state/` with an optional end ("Pause for 2 hours / until tomorrow / until I resume"), and restore it at start. Say it in the first tray line after a restart ("Sync: paused by you since 14:10"). Make the item pause Syncthing folders too, or split it into "Pause uploads and downloads" and "Pause everything". Never let an update or relaunch clear it.
- **Known:** none found in KNOWN_BUGS.md.

### prac-editor-daily-4 - Pushed and unattended updates restart the companion in the middle of uploads, downloads and fetches
- **Severity:** medium
- **Confidence:** CONFIRMED (the gate); the cost of a restarted upload is taken from HOW_IT_WORKS §6.8 ("Uploads cannot resume part-way")
- **Where:** `companion/src/ccsync_companion/app.py:6948-6966` (`_standing_down_would_kill_work`: only "popup" and "consolidate"), `app.py:6968-7012` (`apply_upgrade`), `app.py:8382-8470` (`_maybe_auto_update`, `_run_auto_update`); `broll_fetch.stop_all` at shutdown
- **What:** The one stand-down predicate that every restart path uses blocks only for an open CCSync window or a consolidate. It does not look at any of these: a lane A upload in flight, a lane B pass, an on-demand b-roll or music fetch, a local YouTube download, a fleet job, or proxy generation. An admin's [ UPDATE NOW ] push and `auto_update` therefore restart the companion whenever the next report reply arrives. Every one of those transfers is killed, and an upload starts again from zero.
- **Scenario:** A remote editor on a 20 Mbit/s uplink is 90% through a 40 GB interview original. The admin pushes 0.9.86 to the fleet. The companion restarts and the upload starts over: about four hours lost. Their b-roll Send to Resolve fetch dies with "cancelled -- the companion shut down" in the same moment.
- **Recommendation:** For unattended paths only (push and auto-update, not the editor's own click), extend the stand-down to "a transfer is moving" (`PendingTracker.live_busy()`, which the drive reminder already uses), a running ytdl job, a fetch, or a held fleet job. Cap the deferral (for example 6 hours, or "next idle period") so an always-busy machine still updates. Show the admin "waiting for an upload to finish" on the Packages row, not just "pending".
- **Known:** none found; MULTI_MACHINE_PLAN §9 says "Neither installs anything the tray click could not", which is true, but a click is a person choosing the moment.

### prac-editor-daily-5 - An editor cannot say "this project first"; the only lever on a deadline is unticking everything else
- **Severity:** medium
- **Confidence:** CONFIRMED (no reorder route or control exists: grep of `api.py` / `ui.py` / templates)
- **Where:** `dashboard/templates/partials/home_queue.html` ("one project at a time, top to bottom"; the only row control is Untick); `companion/src/ccsync_companion/sync/sequencer.py:151` (sorted by `position`); `docs/EDITOR_SETUP.md` §3 ("they sync one at a time, in the order you ticked them")
- **What:** The sync plan is a rotation ordered by tick position, and nothing in the dashboard lets an editor or admin change the order. An editor with four ticked projects who needs the newest one's proxies before a review has two options: wait their turn in the rotation, or untick the other three. Unticking stops their proxy sync and, when re-ticked, sends them to the bottom. The doc's "one at a time, in the order you ticked them" also undersells the turn-based rotation the sequencer actually runs.
- **Scenario:** A client review is in two hours. The editor ticked the project this morning, behind three large ones ticked last week. Its proxies trickle in one turn at a time. They untick the other three, forget to re-tick them, and the next day those projects are missing from their machine.
- **Recommendation:** Add a "Sync this first" action on each queue row: set position to 1, and optionally "only this one until it is done", which sets the others aside without unticking them. Reword the doc and the panel hint to describe turns honestly.
- **Known:** none found.

### prac-editor-daily-6 - A misfiled upload can only be fixed by the admin, and the natural self-fix makes it worse
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/api.py:3035-3045` (`_require_move_write`: "Admins only ... even when the editor who mis-filed the card is the one asking"); `docs/EDITOR_SETUP.md` §7 ("ask the admin to do it server-side"); `docs/FILE_MOVES.md` §1 (the leso incident)
- **What:** The incident that created FILE_MOVES.md was an editor filing a card dump in the wrong folder. Today the editor's options are both bad. They can ask the admin to press the move button. Or they can do the obvious thing and drag the folder in Explorer or Resolve's media management, which makes lane A upload a second full copy at the new path and leaves an orphan at the old one. That doubles the server footprint and leaves two copies for other editors to find. The companion does not notice a local move and offer to do it properly.
- **Scenario:** An editor uploads 200 GB to the wrong project at 6 pm. The admin is offline until tomorrow. They fix it locally, and by morning the NAS holds 400 GB, with the misfiled copy still linked in someone else's timeline.
- **Recommendation:** Let an editor REQUEST a move from the project page, for files under a project they have ticked. It appears in the admin's queue as one click ("approve move"), or auto-approves for files that only their own machines hold, which the manifest already knows. Separately, have the companion detect a lane A path that vanished while an identical name and size appeared under a new path in the same project, and offer "Move it on the server too?" through the same `file_moves` machinery rather than uploading a duplicate.
- **Known:** CR-87 / FILE_MOVES.md built the admin path; the editor path is a deliberate gap, not a recorded bug.

### prac-editor-daily-7 - Every button in the Settings window closes the window
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/settings_window.py:20-31` (module docstring, "ONE rule"), `settings_window.py:2010-2016` (`_run`: `_release_and_close()` then `_spawn`)
- **What:** Every button closes the window before it acts, by design, to avoid two Tk roots. That includes buttons that open no window at all: PAUSE B-ROLL INDEXING, INDEX NOW, the fleet-jobs choices, OPEN LOG, OPEN THE RECOVERY FOLDER. Settings is also where the per-computer job settings live, and each of those "needs a restart". So changing one setting takes three steps: open, click (window closes), open again, scroll back, RESTART NOW (window closes). Two settings take five. Since CR-88, everything that is not in the ten-item menu lives here, so this window is the editor's control panel, and it slams shut on every touch.
- **Scenario:** An editor wants to stop fleet jobs on their laptop and pause b-roll indexing before a render. Open Settings, click the first, the window closes. Reopen, scroll past SYNCING, click the second, it closes. Reopen, find RESTART NOW. Most will give up halfway.
- **Recommendation:** Split buttons into two classes. "Opens a dialog" keeps the close-then-spawn rule. "Does not" runs on a worker and leaves the window open; the 2 s refresh already re-renders the new state. Better still, build confirm dialogs as `Toplevel`s of the Settings root on its own thread, so nothing needs to close. That is the sibling-root hazard solved by having one root, not by closing it.
- **Known:** none found.

### prac-editor-daily-8 - Timeline Cards "stage a cut from your phone" cannot be set up at a customer
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/timeline_cards_role.py:1-55` (needs `jobs_mulcam_pipeline` checkout, "TRY IT FROM A SOURCE RUN OF THE COMPANION FIRST", "THE HANDSHAKE HAS NEVER RUN LIVE"); `companion/src/ccsync_companion/config.py:838,873,1543` (`cards_agent` default false, example path `E:\Projects\Editing\Resolve\MulticamPipeline`); `settings_window.py:1098-1100` (not in Settings); `dashboard/src/ccsync_dashboard/db.py:13233` (`MACHINE_SETTING_KEYS` excludes it); the `/cards` mount needs `DASH_CARDS_SRC`, another repo's checkout
- **What:** Every step of the phone-to-Resolve journey needs a developer. On the server, a checkout of a second repo has to be mounted. On the editor machine, a checkout of MulticamPipeline and its Python dependencies (the frozen companion may not be able to import them), plus a hand-edited `cards_agent = true` that neither Settings nor the dashboard can set. And the release/reload handshake has never been run against a real project. The nav hides `/cards` when it is not mounted, so a customer sees nothing broken. The risk is that it is sold or demoed as part of the product.
- **Scenario:** A customer saw Timeline Cards in a demo and asks for it. There is no installer step, no setting, and no supported way to turn it on without the vendor remoting in and running a source checkout on their editing machine.
- **Recommendation:** Declare it out of scope for the commercial v1 in writing (sales copy, HOW_IT_WORKS §14 "What the product does NOT do"), and gate the mount and the role behind a site `[features] timeline_cards` flag that is off in the vendor build, like `youtube_download`. Productise it later as its own feature with a packaged engine and a Settings toggle.
- **Known:** TIMELINE-CARDS-INTO-CCSYNC.md phase 2 notes ("inert until the other repo implements the bridge contract"); not a KNOWN_BUGS entry.

### prac-editor-daily-9 - The in-product help and the editor guide describe controls that moved or were renamed
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `docs/HOW_IT_WORKS.md` (served at `/help` by `dashboard/src/ccsync_dashboard/help.py`, and opened by Settings > HELP); `docs/EDITOR_SETUP.md`
- **What:** The text an editor is sent to does not match the screen in front of them:
  - HOW_IT_WORKS §6.2 and the §16 table: "**IGNORE** hides those clips for this session". The button is `SKIP FOR NOW (this session)` (`popup.py:1128`).
  - HOW_IT_WORKS §9.2: "inserts it when it arrives". It only does if the page stays open (see -2).
  - HOW_IT_WORKS §11: "**Accept YouTube Terms** in the tray". It is in Settings > YOUTUBE (`settings_window.py:1755`). Also "Sign in to YouTube ... takes a cookies file": there are two buttons, a browser sign-in and "Use an exported cookies.txt…".
  - HOW_IT_WORKS §16, Send to Resolve row: "if it answers, tell the admin the addresses differ". The page itself says the opposite ("it's the browser").
  - EDITOR_SETUP §7: "use the tray's **Scan whole project**" and "the tray's **Consolidate pre-existing project…**". Both are in Settings > ADVANCED, and the second is now "BRING AN EXISTING PROJECT'S MEDIA INTO THE SYNCED FOLDER…". Also "the tray app shows the upload/proxy-wait queue".
  - EDITOR_SETUP §6.2: "the menu says `PAUSED — drive disconnected`". The tray line is `Sync: paused (drive disconnected, … still to go)` (`tray.py:2571-2581`). Also "Plugging the drive back in is what ends it; nothing else does": Settings now offers REMIND ME LATER and STOP REMINDING ME ABOUT THIS DRIVE (`settings_window.py:837-839`).
  - EDITOR_SETUP §3: "files already on your disk stay there (delete them yourself if you need the space)". Settings > ADVANCED > REMOVE '<project>' FROM THIS COMPUTER… exists and is the safe way.
  - EDITOR_SETUP §0 and §3: "Your TrueNAS username", "your TrueNAS username and password". A Synology customer's editors have no TrueNAS; the companion's own copy was already de-branded (`site.py:442`).
- **Scenario:** An editor stuck on a toast opens HELP > HOW CC SYNC WORKS, searches for the words on their screen and finds nothing, or is sent to a tray item that is not there. Each one costs a support message.
- **Recommendation:** Fix each line above. Then add a test, like the existing em-dash scans, that every **bold** control name in HOW_IT_WORKS.md and EDITOR_SETUP.md appears verbatim (case-insensitive) in the companion's or dashboard's UI strings. Copy drift has been found in four sweeps running.
- **Known:** UX-1/APP-2 (2026-09-03) fixed the in-code "Tray > ..." strings; these doc lines are the leftover half. Not in KNOWN_BUGS.

### prac-editor-daily-10 - A tick from the dashboard defaults to "every computer" the editor owns
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `dashboard/templates/partials/home_macros.html:62-69` (`<option value="">every computer</option>` first and default); CLAUDE.md multi-machine note ("A request with no `?machine=` is the PERSON ... every computer to tick")
- **What:** An editor with a desktop and a laptop who ticks a project from the laptop's browser, without first noticing the "computer" picker, ticks it on both machines. A full tick pulls every proxy and the shared folders onto the laptop's small SSD, and onto the desktop too.
- **Scenario:** An editor ticks a 1.5 TB project on the road to grab one interview's proxies. The laptop disk fills, and the free-space floor parks lane B. The desktop at home also starts pulling 1.5 TB.
- **Recommendation:** Pre-select the computer the browser is most likely on. The companion can open the dashboard with `?machine=<this host>` from "Open dashboard". Failing that, require an explicit choice when the person has more than one computer, and name the disk cost in the confirm.
- **Known:** none found.

### prac-editor-daily-11 - Vendor jargon on editor surfaces ("fleet", "lane")
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/tray.py:3079-3084` ("⚡ Take fleet jobs now (N min)"); `settings_window.py` section "FLEET JOBS"; `HOW_IT_WORKS.md` §6.6
- **What:** "Fleet" is the vendor's word for its studio's machines. A customer's editor reads "Take fleet jobs now" as meaningless or alarming. The Settings window also mixes casing: buttons are UPPER CASE except the YouTube ones ("Sign in to YouTube (for downloads)…").
- **Recommendation:** "Lend this computer to the team (N min)" and a section called "TEAM WORK ON THIS COMPUTER" or "SHARED JOBS". Normalise the Settings button casing.
- **Known:** usability sweep's vocabulary work (SYS-8) covered the headers, not this label.
