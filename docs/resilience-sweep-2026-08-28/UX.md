# User error, end to end (UX)

## Summary

The companion tray is the best-defended surface in the product: every destructive
action there is confirmed, several with the consequence spelled out, and the
worst one (switch to REMOTE EDITOR) is behind a typed word. The dashboard is the
opposite: eight confirmation dialogs in the whole application, and the controls
that stop the fleet, arm unattended upgrades, delete rollback material and untick
a whole column all fire on one click. The biggest risk found is not a dialog
though: **three one-click actions an editor takes for innocent reasons (Settings
-> WIRED TO THE SERVER, SIGN OUT, Quit) stop that machine syncing indefinitely,
and `health.editor_status` still paints the dot GREEN**, because a machine that
was caught up when it went silent is never "behind" (`health.py:78-91`). The
cheapest high-value win is a report-freshness rule in `editor_status` plus a
confirmation on the role switch: two small diffs that close the "the dashboard
said everything was fine" failure. A close second: the companion reports no free
disk space at all, so nothing anywhere can warn before a tick fills a laptop.

## Findings

### UX-1: Ticking a project has no capacity preflight, and nothing in the fleet knows how full a disk is
- **Lens:** user-error
- **Where:** `dashboard/src/ccsync_dashboard/api.py:1755-1815` (api_tick: validates project, base rig, machine name - never size); `dashboard/templates/admin_assignments.html:60` `[ ALL ]`; `dashboard/static/assignments.js:158-169`; `api.py:5060-5125` (ReportIn has no free-space field); `companion/src/ccsync_companion/reporter.py` (never sends one)
- **Scenario:** The owner opens Assignments, sees a new editor's column empty, clicks `[ ALL ]` to "give them everything". Twelve projects, 4 TB of proxies, onto a 500 GB MacBook.
- **Today:** Every tick succeeds. Lane B (`sync/rclone_lane.py`) has no free-space preflight (the only `shutil.disk_usage` callers are proxy_gen, the VLM/CLAP sidecars and b-roll staging). rclone fills the disk, `.ccsync-trash` cannot prune (it runs every 6 h and refuses while the breaker is tripped, `sync/lane_guard.py`), and the editor's machine becomes unusable for Resolve too.
- **Proposed:** Add `disk: {free_bytes, total_bytes, root}` to the heavy report (one `shutil.disk_usage(local_root)`, the same cadence as the manifest). The dashboard already knows each project's NAS proxy bytes; make `api_tick` return `warning: "<project> is 620 GB of proxies. <machine> has 180 GB free."` and have the UI show a consequence confirm before the PUT (`[ ALL ]` shows the column total). Refuse nothing - the owner may know something we do not - but never let it be silent. Lane B should also skip a pass and set `paused` with "not enough room" rather than filling the volume.
- **Effort:** M **Severity:** high **Confidence:** high
- **Related:** lane B breaker (`lane_guard.py`) catches deletions, not exhaustion; CR-28 shows the tick endpoint is where refusals belong.

### UX-2: Three one-click ways for an editor to stop syncing forever, none confirmed, and the dashboard dot stays green
- **Lens:** user-error / pitfall
- **Where:** `companion/src/ccsync_companion/settings_window.py:170-206` (role buttons), `companion/src/ccsync_companion/config.py:745` (`"base": {"sync_enabled": False, ...}`), `tray.py:2715` + `app.py:4220-4234` (sign_out stops lanes AND reporting), `tray.py:2916` (Quit), `dashboard/src/ccsync_dashboard/health.py:78-91`
- **Scenario:** An editor opens Settings out of curiosity and clicks `WIRED TO THE SERVER` because their desk is in the office. Or clicks `SIGN OUT` meaning to switch account and gets distracted.
- **Today:** `action_set_role(app, "base")` writes `mode = base` with **no confirmation at all** and a toast that only says the role changed; on next start `sync_enabled=False` and every lane is dead. `sign_out()` stops the lanes and, because `editor_identity()` returns None, stops reporting too. In `health.editor_status`, an editor who was caught up has `behind=False`, so neither the offline branch nor the stale-completion branch fires: the dot is **GREEN** for a machine that has been dark for a week. (The lane chip does redden after 15 min, `health.py:105-110`, but the editor dot the owner scans does not.)
- **Proposed:** (a) Confirm the switch to base with the consequence in it (copy in C-1 below), the way the switch to REMOTE EDITOR already is. (b) In `editor_status`, add a report-freshness rule independent of `behind`: no report for `>= 3 * STALE_REPORT_SECONDS` is AMBER, `>= 6 h` is RED, with the tooltip naming the last report time and the reason the companion gave for stopping (`base`, `signed out`, `quit`). (c) Have `sign_out` and `shutdown` write a last-gasp reason into the final report so the grid can say "signed out 3 days ago" rather than just going quiet.
- **Effort:** S (a and b), M (c) **Severity:** critical **Confidence:** high
- **Related:** CR-28 (a base rig holds no tick) already models the base role server-side; this is the client half nobody confirms.

### UX-3: Renaming or moving a project folder in Explorer stops that project syncing, and it reports as normal
- **Lens:** user-error
- **Where:** `companion/src/ccsync_companion/sync/rclone_lane.py:2647-2657`; `sync/repath.py:1-22` (handles SERVER-side moves only)
- **Scenario:** An editor tidies up: `P:\Projects\2026\Nuclear` becomes `P:\Projects\2026\Nuclear FINAL`. Or drags it one level up by accident.
- **Today:** `repath.reconcile` compares the local Syncthing folder path against the selection and finds them equal (nothing changed server-side), so it does nothing. Lane A finds the source missing and sets `STATE_IDLE` with detail `"project dir not yet local: <subpath>"` - a string that reads like ordinary first-run state on the tray line and the dashboard chip. Everything the editor puts in the renamed folder from that moment on is invisible to the fleet. Lane B recreates the original folder and re-downloads it, so the editor now has two folders and no error.
- **Proposed:** Lane A should distinguish "never seen" from "was here last pass and is gone": persist a per-project `last_seen_at` alongside the existing lane state and, when a directory that previously existed disappears, set `STATE_ERROR` with "Your project folder for <label> is not where CCSync expects it. Did you rename or move it?" and report it. Cheap self-heal: walk `local_root/Projects` for a `.ccsync-project` marker carrying that slug and offer a one-click "put it back" (the marker already survives renames, `rclone_lane.py:1761-1789`).
- **Effort:** M **Severity:** high **Confidence:** high

### UX-4: Out-of-tree clips - the one editor mistake that guarantees unsynced footage - are invisible to the admin
- **Lens:** user-error / safeguard
- **Where:** `companion/src/ccsync_companion/popup.py:704-705` (`SKIP FOR NOW (this session)`), `popup.py:1930-1946` (a Tk failure auto-skips the whole batch), `fixer.py:37-56` (`IgnoreTracker` is in-memory by design), `dashboard/.../api.py:5060-5125` (no field carries it)
- **Scenario:** An editor cuts from their Desktop for a week and hits SKIP FOR NOW each time the dialog appears, because FIX ALL once copied for twenty minutes. Or their Tk is wedged (the CORE-M3/H8 class) and the dialog never renders at all.
- **Today:** Nothing is copied, nothing is recorded past the process lifetime, and **no field in `ReportIn` carries out-of-tree counts**, so the owner has no way to learn that this editor has 40 timeline clips that will never reach anyone. The headless path logs and silently ignores every row (`popup.py:1939-1946`).
- **Proposed:** Add `resolve_health: {out_of_tree, bad_prefix, non_canonical, last_scan_at}` to the report and a `⚠ n clips outside the tree` chip per machine on the fleet grid, with the paths behind a click for the admin. Persist the skip decisions to `~/.ccsync/state/skipped_clips.json` with a count in the tray line ("14 clips skipped and not syncing") so the editor cannot forget either. Nothing here needs to copy a byte to be worth having.
- **Effort:** M **Severity:** high **Confidence:** high

### UX-5: A file move expires after 7 days, so a laptop that was away resurrects the file at the old path
- **Lens:** pitfall
- **Where:** `dashboard/src/ccsync_dashboard/db.py:2062` (`FILE_MOVE_MAX_AGE_DAYS = 7`), `db.py:2102-2123` (`pending_file_moves` filters on `m.requested_at >= cutoff`), `companion/src/ccsync_companion/file_moves.py:44` (`EXCLUDE_WINDOW_SECONDS = 24*3600`, and the window starts when the machine HEARS)
- **Scenario:** The owner moves a mis-filed card dump on Monday. One editor is on a two-week shoot with the laptop closed. They come back on day 15.
- **Today:** The command has aged out of `pending_file_moves`, so it is never delivered; the local copy still sits at the old path and has never been excluded from lane A (the exclusion only starts on hearing). The next lane A pass uploads it straight back to the path the admin cleared - the exact failure `docs/FILE_MOVES.md` exists to prevent. The project page shows that machine as `[ WAITING FOR 1 ]` indefinitely with no escalation.
- **Proposed:** Do not expire an UNDELIVERED move; expire only ones that were delivered and unanswered (the docstring's reasoning - "must not shuffle files shuffled again since" - is about stale state, and the companion already refuses a move whose source is not where the command says, `file_moves.py:126-131`, which makes an old command harmless). Additionally: when a target has been `WAITING` past the cutoff, show it on the project page as `[ NOT APPLIED - THIS COMPUTER MAY RE-UPLOAD THE OLD PATH ]` rather than a neutral waiting chip.
- **Effort:** S **Severity:** high **Confidence:** high
- **Related:** `docs/FILE_MOVES.md`; CR-90's lesson that a machine's own spelling is the truth.

### UX-6: The grade swap deletes a foreign P: mapping without the ownership check every other code path makes
- **Lens:** pitfall / user-error
- **Where:** `companion/src/ccsync_companion/drive_swap.py:310-318` (`_unmap` runs `net use P: /delete /y` then `subst P: /D`, unconditionally), vs. `installer/windows_bootstrap.ps1:1279-1305` and `onboarding/steps.py:1587-1606` which both refuse to touch a P: they did not create
- **Scenario:** An editor on a machine that also has a real NAS mapping on P: (the base rig, or a machine set up before CCSync) clicks `GRADE FROM SERVER ORIGINALS (SWAP P:)`.
- **Today:** The confirmation talks about playback speed only; `_unmap()` then destroys whatever P: was, `/y` answering the open-files prompt on the way. The swap back re-maps P: at `local_root`, not at whatever was there before, so the original mapping is gone for good and every `P:\...` clip path in that machine's Resolve database now points at a different tree.
- **Proposed:** Reuse `classify_p_target` (it already exists, `drive_swap.py:295-307`) before `_unmap`: on `other`, refuse with "P: is currently mapped to <target>, which CCSync did not create. Swapping would replace it and CCSync cannot put it back." On `none` (which also means "we could not read the mapping table") refuse the same way the installer does, rather than proceeding.
- **Effort:** S **Severity:** high **Confidence:** high

### UX-7: Syncthing conflict copies are never detected, surfaced or ignored, though SPEC says they are
- **Lens:** pitfall
- **Where:** `SPEC.md:343` ("surfaced in tray"); zero occurrences of `sync-conflict` anywhere in `companion/src` or `dashboard/src`; `companion/src/ccsync_companion/sync/syncthing_admin.py:125-142` (the ignore lists do not mention it)
- **Scenario:** Two editors open the same project and both save. Or both drop a `track.mp3` into `Audio/Music`.
- **Today:** Syncthing writes `<name>.sync-conflict-20260828-104500-XXXX.<ext>` beside the file, silently. Nothing tells anyone. Lane A then uploads the conflict copies to the NAS as new files, where they persist forever (lane A never deletes), and lane B redistributes them. One editor's work is orphaned into a file nobody looks at.
- **Proposed:** A cheap periodic scan (the manifest walk already visits every file) counting `*.sync-conflict-*` under the tree, a warning tray line and a report field, plus a `CONFLICTS` panel on the project page listing path, size and mtime so the owner can decide. Do not auto-delete or auto-merge.
- **Effort:** S **Severity:** high **Confidence:** high

### UX-8: HALT ALL SYNCING is one click, has no expiry, and the API does not require the reason the UI does
- **Lens:** user-error / safeguard
- **Where:** `dashboard/templates/partials/fleet_halt.html:46` (no `hx-confirm`), `dashboard/src/ccsync_dashboard/ui.py:1689` (the partial requires a reason), `api.py:3535-3539` (`FleetHaltIn.reason: str = Field(default="")` - the JSON route does not), `db.set_fleet_halt` writes one `meta` blob with no history
- **Scenario:** The owner halts the fleet on a Friday because something looked wrong, then goes away for the weekend and forgets. Or clicks the wrong red button on the Users page.
- **Today:** Every machine in the company stops syncing until someone remembers. There is no reminder, no expiry, no record of previous halts, and no confirmation before the click. The release path needs no reason at all.
- **Proposed:** Give the halt an `expires_at` (default 24 h, "keep halted" extends it) and a standing banner on every dashboard page counting the hours and the machines affected. Add the confirm in C-2 below. Give `FleetHaltIn.reason` a `min_length=3` so the JSON twin cannot bypass the UI's rule. Keep a small `halt_history` list in `meta` so "who stopped the fleet last month and why" is answerable.
- **Effort:** M **Severity:** high **Confidence:** high

### UX-9: The release controls are the least guarded and the most fleet-wide
- **Lens:** user-error
- **Where:** `dashboard/templates/partials/admin_packages.html:135-138` (feed policy `<select onchange="this.form.requestSubmit()">`), `:38` `[ MAKE CURRENT ]` with only an `[ UNSIGNED ]` chip at `:23`, `:49` `[ DELETE ]`, `ui.py:1974-1997` (delete unlinks the file, `OSError` swallowed), `:170` `[ PUBLISH + MAKE CURRENT ]`
- **Scenario:** The owner tabs into the policy select and presses Down. Or makes an unsigned dev build current. Or deletes an old package "to tidy up".
- **Today:** One arrow key arms `current - auto-publish + make current`, i.e. unattended fleet-wide upgrades from the vendor feed, with no confirmation and no undo prompt. Making an UNSIGNED build current silently stops every companion upgrading (they verify, `release_trust`), and the only signal is a chip. Deleting a package removes the bytes that a rollback needs, with no confirm and a swallowed `OSError`.
- **Proposed:** Confirms C-3, C-4 and C-5 below. Refuse `[ MAKE CURRENT ]` on an unsigned package unless a `?force=1` the UI only sends after a typed confirmation. Make package delete move the file to `<data>/packages/.trash/` with a 30-day prune, not `unlink`, and stop swallowing the `OSError`.
- **Effort:** S **Severity:** high **Confidence:** high

### UX-10: The server refuses things for good reasons and tells only the container log
- **Lens:** safeguard
- **Where:** `dashboard/src/ccsync_dashboard/collector.py:751-778` (`_creatable`: a stray marker on a container hides the real projects underneath), `collector.py:735-749` (`_duplicate_path_folder`), 16 `log.error` sites across `collector.py`/`provision.py`; no notices/alerts table exists in `db.py` or `schema.sql`
- **Scenario:** Someone drops a `.ccsync-project` marker (or copies a project folder including its marker) onto `Projects/2026/CCT/`. Three real projects vanish from discovery.
- **Today:** The refusal is correct and the message is excellent - and it is written to a Docker log that a non-technical owner will never open. The projects are simply gone from the dashboard with no explanation anywhere in the UI.
- **Proposed:** A `notices` table (`id, kind, severity, subject, body, first_seen, last_seen, cleared_at`) that `collector`/`provision` write instead of `log.error` alone, and a `PROBLEMS THE SERVER FOUND` panel on the dashboard home that lists open notices with the fix in plain words. This is the single highest-leverage safeguard in the dashboard: sixteen already-written diagnoses currently reach nobody.
- **Effort:** M **Severity:** high **Confidence:** high

### UX-11: The MOVE confirmation does not say what is being moved or where, and there is no undo
- **Lens:** user-error
- **Where:** `dashboard/templates/partials/project_detail.html:92-104` (one fixed `hx-confirm` string regardless of the free-text path and the destination select), `api.py:1985-1996` (`src.rename(dest)`), `api.py:2012` (journalled but no reverse endpoint), no `common.snapshot_before()` call on this path
- **Scenario:** The owner pastes a path with a typo into the free-text box, or leaves the destination project select on the previous project they were looking at.
- **Today:** The confirm reads "Move it on the server now, and tell every computer that holds it to move its copy and relink Resolve?" whatever "it" and wherever "there" is. The move then rewrites the server tree and fans out to every holding machine. The `file_moves` row is a good journal but there is no button that reads it backwards.
- **Proposed:** Build the confirm text from the form values (copy C-6). Add `POST /projects/{slug}/moves/{id}/undo` that issues the inverse move through the same machinery (the record already carries both ends and `is_dir`), enabled while every target is `DONE` or `WAITING`. Call `snapshot_before()` for a directory move, per the repo's own rule for privileged recursive operations.
- **Effort:** M **Severity:** med **Confidence:** high

### UX-12: A tick with no machine means every computer that person owns, and the button does not say so
- **Lens:** user-error
- **Where:** `ui.py:841-843`, `api.py:1810-1815` (`add_selection_for_person`), `dashboard/templates/partials/project_detail.html:25-28` (`[ TICK FOR <NAME> ]`), `dashboard/templates/partials/sidebar.html:18` (the only place it is stated, in a `title` attribute)
- **Scenario:** The owner ticks a 900 GB project "for leso", meaning his desktop; leso also owns a MacBook.
- **Today:** Both computers start pulling it. Untick with no machine correctly removes it everywhere (the safe direction), but the tick fans out with nothing on screen saying so.
- **Proposed:** Label the person-level control `[ TICK FOR ALL OF LESO'S COMPUTERS (2) ]` and, when the person owns more than one machine, show a per-machine list instead of the single button. The data is already there (`db.machines_of`).
- **Effort:** S **Severity:** med **Confidence:** high
- **Related:** `docs/MULTI_MACHINE_PLAN.md`; CR-91 is the same class of mistake one level down.

### UX-13: Closing the wizard mid-install leaves a machine with no companion, no P: and no autostart, and nothing records it
- **Lens:** pitfall / user-error
- **Where:** `onboarding/onboard.py` (no `WM_DELETE_WINDOW` handler anywhere), `:874-875` (clean-slate then bootstrap), `onboarding/steps.py:1817` (`execute_cleanup` kills the companion, deletes Run entries, scheduled tasks, exes and unmaps P:)
- **Scenario:** An editor re-runs the wizard to fix something, it takes longer than they expected, and they close the window.
- **Today:** The daemon worker dies with the process, possibly between the clean slate and the re-install. The machine now has nothing installed and no P:, and no file on disk says an install was interrupted. The editor believes they still have CCSync.
- **Proposed:** Write `~/.ccsync/state/install_in_progress.json` before `_clean_slate` and delete it on success; on wizard start, if it is present, open on a page that says so and offers `[ FINISH THE INSTALL ]`. Add a `WM_DELETE_WINDOW` handler that, during the install phase, asks "The install is part-way through. Closing now leaves this computer with no CCSync and no P: drive. Close anyway?" The companion, if it is ever started again, should refuse to sync and say the same thing.
- **Effort:** M **Severity:** high **Confidence:** high

### UX-14: Nothing on the install path checks free space, though the wizard's own copy asks for room
- **Lens:** user-error
- **Where:** `onboarding/steps.py:1335-1493` (`validate_local_root`: nine checks, none about space), `onboard.py:711` ("proxies + anything you add land here - leave room"), no `disk_usage` in `windows_bootstrap.ps1` or `macos_bootstrap.sh`
- **Today:** A path on a nearly-full drive validates cleanly and the install proceeds; the disk fills days later during the first lane B pass.
- **Proposed:** Add a tenth validator: warn (do not refuse) below 200 GB free with "This drive has 41 GB free. Synced proxies for one project are typically 50 to 300 GB." Show the figure live beside the field, the way the other validators already update on every keystroke.
- **Effort:** S **Severity:** med **Confidence:** high

### UX-15: The broken-mapping toast tells the editor something untrue and offers no repair
- **Lens:** user-error
- **Where:** `companion/src/ccsync_companion/app.py:1964-1968`, `drive_swap.py:295-307` (`classify_p_target` computes `other`/`none` and only `server` is ever consumed - `app.py:1952`, `app.py:3153`)
- **Today:** The toast says "Nothing will sync until this is fixed. See EDITOR_SETUP step 6." Both halves are wrong for the audience: lanes A and B run off `local_root` and are unaffected (what is broken is Resolve's view of the media), and an editor has no EDITOR_SETUP. It fires once per episode, is not reported to the dashboard, and there is no button to fix it even though `drive_swap.swap_to_local` is exactly the repair.
- **Proposed:** Rewrite as "Resolve is looking for your media on P: but P: is not pointing at your synced folder, so clips will show offline. Your uploads and downloads are still running. Tray > Settings > REPAIR P: NOW." Add that button, wired to the existing mapping code, and report `bad_prefix` (see UX-4) so the owner can see it too.
- **Effort:** S **Severity:** med **Confidence:** high

### UX-16: A folder dropped into the tree by hand saturates the shared upstream, and no one is told or throttled
- **Lens:** pitfall / safeguard
- **Where:** no `--bwlimit` anywhere in `sync/rclone_lane.py` (only `--transfers`, `:1370`, `:1521`, `:1586`); `SPEC.md:346` names the shared upstream as a known constraint
- **Scenario:** An editor copies a 200 GB card dump straight into `P:\Projects\...\Footage` in Explorer, which is exactly what we ask them to do.
- **Today:** Lane A uploads all of it at full rate. Every other editor's proxy download crawls for days. Nobody is warned, nothing is rate limited, and there is no "this will take about 26 hours" anywhere.
- **Proposed:** A `bwlimit` config key honoured by both lanes (default unset, so nothing changes for the base rig), plus a lane A pre-pass estimate: when a pass is about to move more than N GB, toast "About 190 GB is queued to upload. At your current speed that is roughly 26 hours." and put the same number on the fleet grid so the owner can see who is using the pipe.
- **Effort:** M **Severity:** med **Confidence:** high

### UX-17: The ingest drag-and-drop has no size ceiling and no confirmation before hundreds of GB
- **Lens:** user-error
- **Where:** `broll/web/static/ingest.js:39` (`ING_MAX_ITEMS = 2000`, a COUNT cap only), `:212-244` (any drop opens the panel), `:1055` (the GB total is shown but nothing gates on it), `companion/src/ccsync_companion/broll_server.py:1657` (the only stop is a per-file 507 after earlier files are already staged); no `beforeunload` handler in any of the three scripts
- **Today:** Dropping a 200 GB shoot starts staging it; the space refusal fires per file, mid-batch, once part of the drop is on disk. Closing the tab loses the whole un-run drop (only a dispatched batch is re-attached, `:1355-1362`) and a mixed drop discards its non-video half with no message at all.
- **Proposed:** Check `free_bytes` (the status endpoint already returns it, `broll_server.py:951`) against the drop's total before the first byte and refuse the whole drop with the figure. Add a confirm above a threshold (copy C-7). Add a `beforeunload` while uploads are in flight. Say what was filtered out ("14 of 60 files were not video and were left out").
- **Effort:** M **Severity:** med **Confidence:** high

### UX-18: A misconfigured dashboard_url is indistinguishable from a dead companion, and the music page throws the reason away
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/broll_server.py:1178-1212` (a disallowed Origin gets a 403 with no CORS headers, so the browser blocks the response and the page sees a network error), `loopback_guard.py:111-112` (`REFUSED_MESSAGE`), `music/web/static/app.js:248-252` (`companion()` throws `companion ${r.status}` without reading the body, so a 403 and a 404 collapse into one string)
- **Today:** An admin who changes the dashboard URL breaks Send to Resolve for everyone, and every editor reports "the companion is not running". The actionable sentence exists only in the companion's log.
- **Proposed:** Keep the 403 but always emit the CORS headers on a refusal so the page can read the body (the refusal itself is what protects, not the header suppression), and have both SPAs render `body.message`. Add the refused origin to `GET /status`, which is already same-origin-exempt, so the self-test page can say "This companion expects the dashboard at http://x; you are browsing http://y."
- **Effort:** S **Severity:** med **Confidence:** med

### UX-19: The client's dead end
- **Lens:** user-error
- **Where:** `broll/web/app/routes_share.py:72-73`, `:109-139`; `broll/web/static/share_gone.html:23-25`; `broll/web/static/share.js:179-182`, `:256`
- **Scenario:** A client is sent a link that has since been rotated, or the editor removes a clip while the client has the page open.
- **Today:** "THIS LINK IS NOT AVAILABLE ... Please contact whoever sent it to you for a fresh link." - with no name, no organisation and no address, from a page that is the only thing the client has. A clip revoked mid-session gives the browser's own broken-video state with no copy at all.
- **Proposed:** Carry the curating editor's display name and contact into the share record (the page already builds a `mailto:` for licensing, `share.js:94`) and put it on the gone page: "Please ask <name> at <address> for a fresh link." For a mid-session removal, catch the 404 on the video element and render "This clip is no longer in this folder. Refresh the page to see what is."
- **Effort:** S **Severity:** med **Confidence:** high

### UX-20: [ RESUME ] on the fleet grid reports success for a machine it did not find
- **Lens:** pitfall
- **Where:** `dashboard/src/ccsync_dashboard/ui.py:1952` - `db.request_lane_b_resume(...)` returns False for an unknown editor/machine and the return value is discarded; the JSON twin (`api.py:3662`) is not affected
- **Scenario:** The admin clicks RESUME from a fleet page left open across a machine rename or a `[ FORGET ]`.
- **Today:** The grid re-renders looking fine, no resume is queued, and the editor's proxies stay stopped until somebody notices.
- **Proposed:** Use the return value and render "That computer is no longer in the fleet, so nothing was resumed. Reload the page." Same for `partial_admin_machine_update` if it has the same shape.
- **Effort:** S **Severity:** med **Confidence:** high
- **Related:** CR-45.

### UX-21: site.toml IMPORT is a bulk overwrite with no confirmation and no history
- **Lens:** user-error
- **Where:** `dashboard/templates/admin_settings.html:159-163`, `dashboard/static/site_settings.js:729-737`, `dashboard/src/ccsync_dashboard/setup_routes.py:257-265`
- **Today:** Pasting an older or another site's config and clicking `[ IMPORT ]` overwrites every recognised key and reloads the page. `[ EXPORT site.toml ]` exists but the operator must have thought to click it first. `canonical_prefix`, `remote_root` and `tree_name` are in there, and they are read by both installers and every companion.
- **Proposed:** Snapshot the current values into `site_history` (a `meta` list of the last 10 imports, with who and when) before applying, show a diff-style confirm ("This will change 7 settings, including canonical_prefix from P:\ to Q:\ ..."), and add `[ UNDO LAST IMPORT ]`. The same snapshot belongs on `[ SAVE ]` for the three tree keys.
- **Effort:** M **Severity:** med **Confidence:** high

### UX-22: Revoking a token or a session is unconfirmed, unrecoverable, and can be your own
- **Lens:** user-error
- **Where:** `dashboard/templates/partials/admin_report_tokens.html:55` `[ REVOKE ]` and `:69` `[ CREATE ]`, `ui.py:1596-1600` (the secret is displayed exactly once), `dashboard/templates/partials/admin_sessions.html:27` `[ REVOKE ALL ]` on a row that may be marked `(you)`, `templates/partials/topbar.html:110` `[ LOGOUT ALL ]`
- **Today:** One click revokes a per-editor `cce1.` token that cannot be re-shown, taking that editor's companion off the fleet until someone re-issues and re-enters one. `[ REVOKE ALL ]` next to `(you)` logs the admin out of the machine they are fixing things from.
- **Proposed:** Confirms C-8 and C-9. For the admin's own session row, label the button `[ SIGN ME OUT EVERYWHERE ]` rather than `[ REVOKE ALL ]`.
- **Effort:** S **Severity:** med **Confidence:** high

### UX-23: The Windows uninstaller decides whether P: is "ours" with the mechanism the installer says is unsafe
- **Lens:** pitfall
- **Where:** `installer/windows_uninstall.ps1:179-188` (`Test-Path` + `Get-PSDrive`/`DisplayRoot`) vs `installer/windows_bootstrap.ps1:1274-1305`, whose own comment says `Test-Path` is blind to the session's mappings and to disconnected persistent mappings
- **Today:** A disconnected persistent NAS mapping on P: reads as absent, the ownership guard is bypassed, and the uninstall removes a mapping it did not create.
- **Proposed:** Hoist the bootstrap's `Get-DriveMapping` classification into a shared helper both scripts dot-source, and keep its fail-closed rule ("unreadable means somebody else's").
- **Effort:** S **Severity:** med **Confidence:** med
- **Related:** KNOWN_BUGS B21.

## Top 10 consequence-spelled-out confirmations the UI should have and does not

Exact copy, no em dashes.

- **C-1 Tray > Settings > WIRED TO THE SERVER** (`settings_window.py:186-190`, currently no dialog at all):
  "Set this computer to WIRED TO THE SERVER? A wired computer works straight off the server share, so CCSync will sync NOTHING to it: no uploads, no proxy downloads, no shared project files. Your admin will not be able to tick projects for it either. If this laptop keeps its own copy of the projects, this is not the setting you want."
- **C-2 Dashboard > HALT ALL SYNCING** (`fleet_halt.html:46`, no confirm today):
  "Stop syncing on EVERY computer in the fleet? Uploads, proxy downloads and shared project files stop everywhere until you start them again here. Nothing is deleted. Work done while the halt is on will not reach anyone until you release it."
- **C-3 Settings > Packages > feed policy = current** (`admin_packages.html:138`, submits on change today):
  "Publish new builds automatically AND make them current? Every editor's machine will take each new build from the vendor feed without anyone approving it first. Choose 'stage' if you want to test a build before the fleet gets it."
- **C-4 Settings > Packages > MAKE CURRENT on an unsigned build** (`admin_packages.html:38`):
  "This build has no release signature. Companions verify signatures, so making it current stops EVERY machine in the fleet from updating, silently. Republish it through tools\ship.cmd instead. Make it current anyway?"
- **C-5 Settings > Packages > DELETE** (`admin_packages.html:49`):
  "Delete companion {version} for {platform}? These are the bytes a rollback to that version needs. Once it is gone you cannot put the fleet back on it without rebuilding and republishing."
- **C-6 Project page > MOVE ON THE SERVER AND ON EVERY MACHINE** (`project_detail.html:92`, currently a fixed string):
  "Move '{path}' from {from_project} to {to_project}/{to_path} on the server, and tell {n} computer(s) to move their copy and relink Resolve? Proxies move with it. There is no undo button: putting it back means moving it again."
- **C-7 B-roll ingest > run a large drop** (`ingest.js`, no size gate today):
  "This drop is {size} across {n} clips. Staging it needs {size} free on this computer and it has {free}. Indexing will run for about {hours} hours. Start it?"
- **C-8 Users > report token REVOKE** (`admin_report_tokens.html:55`):
  "Revoke {editor}'s report token? Their companion stops reporting and stops syncing until you issue a new token and they enter it. The old token cannot be shown again."
- **C-9 Users > REVOKE ALL on your own session row** (`admin_sessions.html:27`):
  "Sign yourself out of every browser, including this one? You will need to log in again to finish what you are doing."
- **C-10 Assignments > [ ALL ] on a column** (`admin_assignments.html:60`):
  "Tick all {n} projects for {machine}? That is about {size} of proxies to download. This computer has {free} free."

## Cross-cutting notes

- **For the sync/lanes agent:** `sync/rclone_lane.py:2653` returns `STATE_IDLE` with `"project dir not yet local"` for a directory that existed last pass and has vanished; that state is indistinguishable from first-run and is the whole of UX-3.
- **For the dashboard/data agent:** there is no notices/alerts table anywhere. Sixteen `log.error` diagnoses in `collector.py`/`provision.py` (stray marker on a container, two Syncthing folders over one path, un-provisionable folders) reach nobody. This is the cheapest structural win in the dashboard.
- **For the release agent:** `dashboard/static/dashboard_update.js:165` hard-codes `restore_db: ""`, so `RollbackIn.restore_db` (`dashboard_update.py:1191`) is unreachable from the UI; a rollback that needs its databases back has no button.
- **For the report/protocol agent:** `ReportIn` (`api.py:5060-5125`) has no field for free disk space, out-of-tree clips, mapping health or Syncthing conflicts. Four of the findings above are blocked on the same one-line schema addition.
