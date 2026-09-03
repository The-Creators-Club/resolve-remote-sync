# Sync engine: lanes A/B/C, breaker, repath, root guard, drive swap, file moves

## Summary
The 08-28 sweep landed almost completely here: the stall watchdog, the disk
floor, `sync_guard.blocked`, `ROOT_NOT_ANSWERING`, the NFC folds, stray-project
scanning and the bounded children are all in the tree, and `classify_lane_error`
plus the Settings window's SYNC LANES section mean an editor now has real
sentences where they used to have `rclone exited 1`. The resilience posture is
strong; the remaining risk has moved from "nothing detects it" to **"something
detected it and the detection never reaches a person"** and to **whole
subsystems that were built with no editor-facing surface at all**: the shared
LUT library, borrowed folders and the server-side repath all fail permanently at
DEBUG level with no report field, no tray line and no dashboard chip. The second
theme is copy that is right in one place and wrong in the three others that
render the same event: a misplaced drive gets a careful dialog and three lines
that call it "disconnected"; a stalled lane gets its own tray line and a lane
line that says "Something went wrong"; a file move that has not been relinked
tells the editor it has. Biggest single risk: **`drive_swap.py` is hardcoded to
`P:`** while the drive letter is documented site data, so grade-swap on a
second customer unmaps a stranger's drive. Cheapest wins: four missing `if`
branches for `ROOT_MISPLACED`, one branch in `classify_lane_error` for the
stall sentence, and returning the shared-folder reconcile outcome the sequencer
already throws away.

## Findings

### SYNC-101: the shared LUT library and every borrowed folder fail silently, forever
- **Lens:** both
- **Who:** editor, admin
- **Where:** `companion/src/ccsync_companion/sync/shared_folders.py:302`, `:310`, `:163`; `sync/borrowed_folders.py:290`, `:297`, `:303`; caller `sync/sequencer.py:1032`, `:1042`
- **Today:** `reconcile()` returns `{folder_id: "ok"|"accepted"|"repaired"|"not-offered"|"error"}` and its own docstring says the outcome is *"for the log line and the tray"*. The sequencer calls it as a bare statement and discards the dict; nothing else calls it. The `not-offered` branch (the server has not shared the library with this device) logs at **DEBUG** with the comment *"permanent on a machine the server has not shared the library with"*. So an editor whose LUT library never arrives, or whose borrowed-folder subtree never appears, sees: no tray line, no lane state, no `sync_guard` field, no dashboard chip, and nothing in `companion.log` at the default level. Grep confirms `shared_folders` / `borrowed` appear nowhere in `reporter.py`, `tray.py` or `settings_window.py`.
- **Proposed:** keep the returned dict on the sequencer (`shared_folder_outcomes()`), emit `sync_guard.shared_folders = [{id, outcome, since}]` for any outcome that is not `ok`/`accepted`, and add a tray/Settings line beside `_unfiltered_line`: `"⚠ The LUT library is not shared with this computer yet. Ask your admin to approve it."` Promote a `not-offered` that persists past ~3 reconciles from DEBUG to WARNING with the same sentence, and add `shared_folder_missing` to `_BLOCKED_ORDER` below `folders_unfiltered` (it does not stop project sync, so it must not outrank it).
- **Effort:** S **Value:** high **Confidence:** high
- **Related:** SYNC-5's `folders_unfiltered` is the exact pattern to copy; ledger memory "Ruskin LUT onboarding".

### SYNC-102: a project renamed on the server moves the editor's folder with no notice and no relink, and a failed move parks it paused for ever
- **Lens:** both
- **Who:** editor
- **Where:** `sync/repath.py:207-247` (the move), `:222-233` (the "leaving the folder PAUSED" branch), `:283-288` (target exists), called at `sync/sequencer.py:1673`
- **Today:** an admin renames `2026/FF5/Animals` on the NAS. On the next pass the companion pauses the folder, moves the editor's whole project directory on their disk, and re-points Syncthing. The editor is told **nothing** - no toast, no tray line, no report field - and every clip in the open Resolve project still points at the old canonical path, so the project goes offline mid-session with no explanation. Contrast `file_moves.py`, where a single file move gets a toast (`app.py:6385`) *and* a Resolve relink *and* a retry ledger *and* a `blocked` answer. When the move fails (Resolve or Explorer holding a handle - the routine case) the folder is deliberately left PAUSED and the only trace is `log.error("... close Resolve/Explorer on that folder and the next pass will retry")`, which the editor never reads. Nothing in `_BLOCKED_ORDER` (`app.py:5587`) covers it, so `sync_guard.blocked` stays empty and the fleet grid shows a machine quietly not syncing one project.
- **Proposed:** (a) on a successful repath, one toast in the file-move voice: `"Your admin renamed a project on the server. CCSync moved your copy to match and will relink Resolve."` plus the same `_relink_moved_result` call `_apply_file_moves` makes. (b) On a failed move, expose it: `ProjectRepather` returns `blocked=[{slug, from, to, reason}]`, the sequencer publishes `sync_guard.repath_blocked`, a new `repath_blocked` reason lands in `_BLOCKED_ORDER` just above `folders_unfiltered` with the detail `"<project> is not syncing because CCSync could not move its folder. Close it in Resolve and Explorer, then it retries by itself."`, and a Settings line carries the same words.
- **Effort:** M **Value:** high **Confidence:** high
- **Related:** SYNC-4/SYNC-10 (08-28) touched the same module for a different hole; `docs/FILE_MOVES.md` is the model.

### SYNC-103: `drive_swap.py` is hardcoded to `P:` while the drive letter is site data
- **Lens:** resilience
- **Who:** owner, editor
- **Where:** `drive_swap.py:43` (`P_DRIVE = "P:"`), `:44` (`LOOPBACK_SHARE = "CCSync_P"`), `:184`, `:198`, `:266`, `:314` (`net use P: /delete /y` **unconditional**), `:490`, `:502`; contrast `app.py:4171` `canonical_prefix_label()`
- **Today:** CLAUDE.md's rule is that the drive letter comes from the site manifest's `canonical_prefix` and "a second customer no longer forks the installer". `app.py` honours it in nine places. `drive_swap` does not: GRADE FROM SERVER ORIGINALS on a site whose prefix is, say, `Q:\` runs `_unmap()` first - `net use P: /delete /y` then `subst P: /D` - against whatever `P:` happens to be on that machine (someone else's mapping), then maps the server at `P:`, which Resolve does not use. The swap silently does nothing useful and can break an unrelated drive; `swap_to_local` then "restores" `P:` to `\\localhost\CCSync_P`, a share the installer only creates when the prefix is `P:`. Every error string the editor reads says `P:` too.
- **Proposed:** take the letter from config: `drive_swap.swap_to_server(..., letter=app.canonical_prefix_label())`, default `"P:"` for compatibility, and derive the loopback share name from it (`CCSync_<letter>`). Refuse the swap outright, with `"This computer's sync drive is <X>: but CCSync was built for P:. Ask your admin."`, when the two disagree, rather than unmapping a letter this product does not own.
- **Effort:** M **Value:** high **Confidence:** high
- **Related:** COMMERCIAL_READINESS item 11; memory "Drive letter setting deferred" (deferred in 2026-07, un-deferred by the manifest work).

### SYNC-104: the stall watchdog writes a good sentence and the lane line answers "Something went wrong"
- **Lens:** usability
- **Who:** editor
- **Where:** `sync/rclone_lane.py:4100-4104` (`"rclone made no progress for {n}s - killed"` / `"rclone did not exit after {n}s - killed"`), set as `last_error` at `:3496`; `tray.py:442-496` (`classify_lane_error`), rendered at `:551`
- **Today:** the SYNC-1 watchdog kills the wedged child and sets `last_error` to its own sentence. `classify_lane_error` has branches for the sync engine, a missing marker, disk full, auth and network - none matches "made no progress" or "did not exit" - so the lane line reads `"Proxies (server → you): PROBLEM. Something went wrong. Tray → Copy diagnostics for your admin."` while three lines below it `_stalled_line` (`tray.py:2277`) says `"⚠ Proxy download stopped moving for 15 min and was restarted. If it keeps happening, check the drive is connected"`. The editor gets two different stories about one event, and the more prominent one is the useless one.
- **Proposed:** one branch, above the generic fallback: `if "made no progress" in text or "did not exit" in text: return "This lane stopped moving and was restarted. If it keeps happening, check the drive is connected."` Same words as `_stalled_line`, per the repo's own "the tray line, the chip and the log agree word for word" rule.
- **Effort:** S **Value:** high **Confidence:** high

### SYNC-105: a misplaced drive is called "disconnected" everywhere except the one dialog that gets it right
- **Lens:** usability
- **Who:** editor
- **Where:** `app.py:2189-2195` (the `else` balloon), `root_guard.py:646`, `tray.py:1837-1846` (`_sync_line`), `:2988-2992` (`_tooltip_text`), `:543` (`_format_lane_line_from`), `app.py:2278-2320` (the correct dialog)
- **Today:** on `ROOT_MISPLACED` the editor gets, within one second: balloon 1 `"Sync paused: your Creators Club drive is disconnected."` (the `else` arm, because only `ROOT_NOT_ANSWERING` got its own branch), balloon 2 `"...is mounted at the wrong path. Sync is paused until it is fixed. See the CCSync window."`, a tray line `"Sync: paused (drive disconnected)"`, a tooltip `"CCSync: PAUSED (your drive is disconnected)"` and three lane lines `"...: PAUSED (drive disconnected)"`. The drive is plugged in. Worse, `root_guard.state_sentence(ROOT_MISPLACED)` - the string `sync_guard.blocked.detail` carries to the tray *and the dashboard* - says `"the sync drive is mounted at the wrong place - eject it and plug it back in"`, which is advice that **reproduces the fault**: the dialog correctly says you must delete the leftover empty folder first. And `_root_misplaced_announced` is set to True *before* the dialog is attempted (`app.py:2291`), so when another CCSync window is open (`app.py:2327`) the instructions are dropped for the whole episode with no way to ask for them again.
- **Proposed:** (a) a `ROOT_MISPLACED` arm on the balloon, `_sync_line`, `_tooltip_text` and `_format_lane_line_from`, all reading `"Sync: paused (the drive is mounted at the wrong place)"`. (b) Fix `state_sentence`: `"the sync drive mounted at the wrong place - eject it, delete the leftover empty folder, then plug it back in"`. (c) Set `_root_misplaced_announced` only after the dialog is actually shown, and add a Settings-window `[ WHAT TO DO ABOUT THE DRIVE ]` button while the state stands.
- **Effort:** S **Value:** high **Confidence:** high

### SYNC-106: the breaker tells the editor to edit `config.toml`
- **Lens:** usability
- **Who:** editor
- **Where:** `sync/lane_guard.py:447-453`, rendered by `tray.py:2168-2180` and `app.py:2500-2510`
- **Today:** the trip reason is user-visible in four places (tray line, balloon, Settings, dashboard chip) and one of the three reasons ends `"Check remote_root in config.toml."` The full line an editor reads is: `"⛔ PROXY DOWNLOAD STOPPED (safety): the NAS root does not look like the tree: none of Projects, Assets is under remote_root (saw 0 entries). Check remote_root in config.toml."` An editor cannot open `config.toml` (it is under `~/.ccsync`, the build is frozen, and touching it is not their job); "remote_root" and "the NAS root" are internal names. The other two reasons are good, and neither says what to do next either.
- **Proposed:** split the sentence: keep the technical half for the log and `copy_diagnostics`, and give the editor `"The server does not look like your project tree right now, so CCSync stopped downloading proxies before anything could be removed. Nothing was deleted and your uploads are still running. Ask your admin to check the server."` Add the same "nothing was deleted, uploads are still running" tail to the EMPTY and SHRANK reasons, which today end on the alarm.
- **Effort:** S **Value:** high **Confidence:** high

### SYNC-107: nowhere on the editor's own computer lists the projects it syncs
- **Lens:** usability
- **Who:** editor
- **Where:** `settings_window.py:353` / `:512` / `:538` / `:587` / `:601` (the five sections: THIS COMPUTER, SYNC LANES, YOUTUBE, ADVANCED, HELP); the data exists at `sync/sequencer.py` `_queue_slugs` / `_slug_to_item` and is rendered only as `"syncing 2026/CCT/Show (2/5)"` (`:682-690`)
- **Today:** the only enumeration of this machine's plan is a stack of destructive buttons in ADVANCED: `"REMOVE '<name>' (upload only) FROM THIS MACHINE…"` (`settings_window.py:578-583`). That is the sole place the words "upload only" appear to an editor - inside the label of the button that deletes the project. An editor asking "is FF5 meant to be on this machine? why have its proxies not arrived? what is it waiting for?" has to open the dashboard in a browser, and an editor on upload-only has no way to learn that their proxies are never coming by design.
- **Proposed:** a `PROJECTS ON THIS COMPUTER` section above ADVANCED, one line per selected project: `2026/FF5/Animals   syncing now (3/5)` / `waiting its turn` / `uploads only (no proxies come down)` / `paused: waiting for its filter list`. Every value is already in `_slug_to_item`, `_queue_slugs`, `_ignores_unconfirmed` and the repath state. It also gives SYNC-101/102/SYNC-5 a natural home per project instead of a global warning line.
- **Effort:** M **Value:** high **Confidence:** high

### SYNC-108: the file-move toast says Resolve was relinked when it was not
- **Lens:** usability
- **Who:** editor
- **Where:** `app.py:6353-6389`
- **Today:** `relink_pending = not matched` is computed at `:6365` for exactly the case RES-10 describes ("Resolve was not open" is not "there was nothing to relink"), then the toast at `:6385` fires on `if paths is not None:` regardless: `"<admin> moved 'A001_C003.braw' to 2026/FF5/Rushes on the server. Your copy followed and Resolve was relinked."` When `relink_pending` is True nothing was relinked; the clip is offline the next time that project is opened, and the editor has been told in writing that it is fine.
- **Proposed:** two sentences off the flag. Relinked: as today. Pending: `"... Your copy followed. The clip will reconnect the next time you open that project in Resolve."`
- **Effort:** S **Value:** high **Confidence:** high

### SYNC-109: "your newer version will NOT upload" names no file and offers no action
- **Lens:** usability
- **Who:** editor, admin
- **Where:** `tray.py:2253-2266` (`_skipped_exists_line`), fed by `sync/rclone_lane.py:2948-2983` (`_refresh_size_mismatches`, which keeps `samples`)
- **Today:** the tray/Settings line is `"⚠ 3 files on the server have the same name but a different size. Your newer version will NOT upload"`. Full stop. The log line right beside it (`rclone_lane.py:2971-2979`) names the first sample **and** the two fixes: *"Rename the local file, or have an admin remove the NAS copy, if the local one is the good one."* The report carries `samples` to the dashboard. The editor gets the alarm and neither the filename nor the remedy, for the one silent data-loss shape on the upload lane.
- **Proposed:** `"⚠ 3 file(s) already exist on the server with the same name at a different size (e.g. A001_C003.mov), so your newer version will not upload. Rename yours, or ask your admin to remove the server's copy."` The sample is already in the dict; nothing new is computed.
- **Effort:** S **Value:** high **Confidence:** high

### SYNC-110: a week-old cached sync plan is indistinguishable from a live one
- **Lens:** resilience
- **Who:** editor, admin
- **Where:** `selection.py:279` (`"fetched_at"` written), `:296-324` (`_load_cached_response` / `load_cached` - `fetched_at` is never read anywhere in the repo), `sync/sequencer.py:1046-1052` (`_describe_no_selection`)
- **Today:** a dashboard that is unreachable falls back to the on-disk cache. When the cache holds projects, the sequencer reports `RUNNING` and the tray reads `"Sync queue: syncing 2026/CCT/Show (2/5)"` - identical to a healthy machine. `"dashboard unreachable"` is only ever said when the cache is *also* empty. So an editor whose dashboard has been down (or whose token was revoked, or whose hostname changed) for a week keeps syncing a week-old plan: new ticks never arrive, unticks never take effect, and the only clue is `_reporter_line` (APP-1), which is about reports, not the plan.
- **Proposed:** read `fetched_at` back; expose `selection_age_seconds`; when the last successful fetch is older than ~3 poll intervals, append to the sequencer detail `"(using the plan saved <n> h ago - the dashboard is not answering)"` and report `sync_guard.selection_stale`. Above ~24 h it deserves a `blocked` reason of its own between `no_selection` and `project_dir_moved`.
- **Effort:** S **Value:** high **Confidence:** high
- **Related:** SYNC-14 (08-28) is the hostname half of the same hole and is still open.

### SYNC-111: a tripped breaker and a full disk deadlock each other
- **Lens:** resilience
- **Who:** editor
- **Where:** `sync/lane_guard.py:913-915` (prune refuses while tripped), `:902-908` (the `min_free_bytes` trigger's own docstring: *"disk-full is precisely the state in which a fortnight-old recovery copy is worth less"*), `sync/rclone_lane.py:3919-3929`, `tray.py:2182-2195` (`_disk_line`)
- **Today:** the two 08-28 fixes interact. `.ccsync-trash` may hold up to the 50 GB cap. If the breaker is tripped **and** the free-space floor parks lane B, the disk-pressure prune - the third trigger added precisely for this - is refused by the breaker gate at the top of `prune_trash`, and the tray tells the editor `"⚠ Not downloading proxies: this drive has 8 GB free. Uploads are still running; free up space and it starts again on its own"`. It cannot start again on its own: the largest reclaimable thing on the disk is exactly what the tripped breaker is holding, and the editor is not told it exists. `[ RESUME PROXY DOWNLOAD ]` clears both parks together (`app.py:5811`), so the way out is a button whose dialog asks the editor to assert something about the server.
- **Proposed:** keep the breaker gate for age/size pruning, but let the `min_free_bytes` trigger through while tripped, capped at the oldest batches and never the newest (the rule the size cap already follows). And when both are set, say so: `"⚠ Not downloading proxies: this drive has 8 GB free, and CCSync is holding 34 GB of recovery copies it cannot clear while proxy download is stopped. [ OPEN THE RECOVERY FOLDER ]"`
- **Effort:** M **Value:** high **Confidence:** med

### SYNC-112: `.ccsync-trash` is the recovery story and there is no way to open it
- **Lens:** usability
- **Who:** editor
- **Where:** `app.py:2488-2498` (`_notify_trash_recovery`), `tray.py:2236-2250` (`_trash_line`), `sync/lane_guard.py:879-950` (`prune_trash`), `tray.py:3194` (`action_open_sync_drive` exists; no trash equivalent)
- **Today:** the toast pastes a raw path into a balloon (`"...moved (never deleted) to:\nP:\\.ccsync-trash\\20260903-141201\nCopy anything you still need back out of there."`) and the Settings line reports the size once it passes 1 GB. Both ask the editor to navigate by hand to a dot-prefixed folder Explorer hides by default. There is an `action_open_sync_drive` but no `action_open_trash`. Meanwhile `prune_trash` deletes batches by age and size with no warning anywhere: the retention line the editor sees never mentions that these copies expire.
- **Proposed:** an `[ OPEN THE RECOVERY FOLDER ]` button in SYNC LANES whenever `trash.bytes > 0` (it is one `os.startfile`/`open`, the same call `action_open_log` makes), and extend `_trash_line`: `"Recoverable files in .ccsync-trash: 12.4 GB (318 files). Copies older than 30 days are removed automatically."`
- **Effort:** S **Value:** med **Confidence:** high

### SYNC-113: the "why isn't it syncing" sentence leaks raw rclone text and raw slugs
- **Lens:** usability
- **Who:** editor, admin
- **Where:** `app.py:5765-5768` (`transport_offline`), `:5717-5722` (`folders_unfiltered`)
- **Today:** `sync_guard.blocked.detail` is the one sentence the tray, the Settings window and the dashboard machine row all render. Two of its producers put internals in it. `transport_offline` returns `"This computer cannot reach the server: " + str(errors[-1].last_error ...)` - i.e. the verbatim rclone tail that `classify_lane_error` exists to keep off screen, appended to an editor-facing sentence. `folders_unfiltered` returns `"2 project(s) are not sharing yet - waiting for their filter list: 2026-ff5-animals, 2026-cct-ep3"`: slugs, which appear nowhere the editor has ever seen; the labels are in `_slug_to_item`.
- **Proposed:** route the first through `tray.classify_lane_error` (move it to a shared module so `app.py` may import it without importing the tray), and resolve slugs to `item["label"] or item["rel_path"]` in the second.
- **Effort:** S **Value:** med **Confidence:** high

### SYNC-114: two sign-in dialogs name TrueNAS to customers who may not have one
- **Lens:** usability
- **Who:** owner, editor
- **Where:** `tray.py:843` (`"Enter your TrueNAS username and password to verify this machine."`), `tray.py:1701-1703` (`"Windows needs your server login to stream originals. Enter the same TrueNAS username and password you sign in with."`, the grade-swap credential prompt)
- **Today:** the repo's rule is that brand strings come from the site manifest and no customer's name is in code; the Synology port is real (`drive_swap.py:512-528` matches both `/mnt/<pool>/…` and `/volume<N>/…`). These two dialogs hardcode a NAS vendor. On a Synology site the sentence is simply false, and the editor looks for a login they do not have.
- **Proposed:** `"Enter your server username and password to verify this machine."` and `"...Enter the same server username and password you sign in with."` If a vendor word is wanted, it belongs in the site manifest beside `org_name`, not in the exe.
- **Effort:** S **Value:** med **Confidence:** high

### SYNC-115: the consolidate report speaks to an admin and calls the server "the NAS"
- **Lens:** usability
- **Who:** editor
- **Where:** `consolidate.py:349`, `:357-362`, `:366`, `:370`
- **Today:** the dialog an editor reads before onboarding an old project says `"12 original(s) will upload to the NAS"`, `"!!! WARNING: the NAS proxy sync would DELETE 40 local file(s) !!!"`, `"Proxy download will be SKIPPED for this consolidate -- fix the mismatch on the NAS first, then re-run."` and `"(could not check the NAS: <raw exception>)"`. Everywhere else in the product the same machine is "the server" (file-move toasts, `classify_lane_error`, the breaker copy). "Fix the mismatch on the NAS" is an instruction to somebody with an SSH session, handed to a video editor; the fallback prints a Python exception string.
- **Proposed:** "the server" throughout; `"Proxy download will be skipped this time. Ask your admin to check the server, then run this again."`; and `"(CCSync could not check the server. Try again, or Copy diagnostics for your admin.)"` with the exception kept in the log.
- **Effort:** S **Value:** med **Confidence:** high

### SYNC-116: "no selection" is developer copy on the tray's most-read line
- **Lens:** usability
- **Who:** editor
- **Where:** `sync/sequencer.py:682-683`, `:1046-1052`; rendered by `tray.py:1780-1795` as `"Sync queue: …"`
- **Today:** the three strings are `"no selection (zero projects selected)"`, `"no selection (dashboard unreachable)"` and `"no selection (dashboard unreachable, no cache)"`. `sync_guard.blocked` has a good sentence for the first case (`"No projects are ticked for this computer"`, `app.py:5702`) but the sequencer line is rendered independently and is the one that appears when nothing is blocked. A new editor whose admin has not yet ticked anything reads "no selection" and reasonably concludes the software is broken.
- **Proposed:** `"Nothing to sync yet: no projects are ticked for this computer"`, `"Waiting for the server: using the plan saved <n> h ago"` (with SYNC-110) and `"Waiting for the server: this computer has no plan saved yet"`.
- **Effort:** S **Value:** med **Confidence:** high

### SYNC-117: the drive reminder cannot be dismissed or tuned except by editing config.toml
- **Lens:** usability
- **Who:** editor
- **Where:** `drive_reminder.py:175-192` (`interval_seconds`), `config.py:693`, `:1378`, `:2092`; there is no `drive_reminder` control in `settings_window.py` or `tray.py`
- **Today:** the only way out of a balloon every 30 minutes - `"Your Creators Club drive is still disconnected and syncing is unfinished: 2 uploads (2.3 GB left) still to go. Plug it back in to finish syncing."` - is the drive coming back (`clear()`, `app.py:2213`). An editor who has deliberately retired that SSD, or who is on a plane, gets it every half hour indefinitely; `drive_reminder_minutes = 0` is the documented escape and lives in a TOML file under `~/.ccsync` that a frozen-exe user has no reason to know exists. The module docstring anticipates the complaint verbatim ("every half hour is too often for my one-drive laptop") and then puts the answer somewhere the editor cannot reach.
- **Proposed:** a `[ REMIND ME LATER ]` / `[ STOP REMINDING ME ABOUT THIS DRIVE ]` pair in SYNC LANES while an episode is open (the tray already renders the episode at `settings_window.py:398-402`). "Stop" suppresses reminders for this episode only, keeps the `drive_unfinished.json` record and the standing warning line, and is cleared when the drive returns - it must not be a persistent opt-out of a data-safety warning.
- **Effort:** S **Value:** med **Confidence:** high

### SYNC-118: SYNC LANES is an unranked wall of up to sixteen identical warning lines
- **Lens:** usability
- **Who:** editor
- **Where:** `settings_window.py:366-412` (fourteen `_*_line` producers, every one appended with `style="warning"`), plus three lane lines, the sequencer line and the current-project line
- **Today:** every advisory the 08-28 sweep added renders the same way, in source order, with the same warning styling: halt, breaker, skipped-exists, unfiltered, conflicts, reporter, clock skew, ignored, crashes, restarts, upgrade, reverted, stalled, disk, blocked, trash. `_blocked_line` is deliberately last and is a *summary* of several of the others (`tray.py:2197-2224` suppresses only six reasons). On a machine having a bad week the editor gets a dozen equally-loud yellow lines with the one sentence that matters at the bottom, next to "Recoverable files in .ccsync-trash: 12 GB", which is not a problem at all.
- **Proposed:** three tiers in the section: the `blocked` sentence first and alone at the top (it is already the ordered answer), then `problem` lines that stop sync, then a collapsed `"3 more advisories"` line expanding to the informational ones (trash size, conflicts, ignored clips). No new state; it is an ordering and a style attribute.
- **Effort:** M **Value:** med **Confidence:** med

### SYNC-119: the resume dialog asks the editor to consult an admin it gives them no way to reach
- **Lens:** usability
- **Who:** editor
- **Where:** `tray.py:1544-1551`
- **Today:** `"Only resume once your admin has confirmed the server is healthy. If it is not, resuming will move more of your local proxies into .ccsync-trash…"` - correct, and the dialog offers exactly two buttons: RESUME PROXY DOWNLOAD and cancel. `COPY DIAGNOSTICS FOR YOUR ADMIN` is three sections away in HELP, and the dashboard's own `[ RESUME ]` (the admin-side answer) is not mentioned.
- **Proposed:** add a third button `[ COPY DIAGNOSTICS FOR YOUR ADMIN ]` to this dialog and one sentence: `"Your admin can also resume it for you from the dashboard."`
- **Effort:** S **Value:** low **Confidence:** high

### SYNC-120: a `not_answering` drive that never answers again produces one balloon and then silence
- **Lens:** resilience
- **Who:** editor
- **Where:** `app.py:2177-2192` (the `resume_remembered` / `not_answering` arms), `drive_reminder.py:243-264` (`begin` is reached only via `unfinished`)
- **Today:** CR-92's reminders are gated on work having been owed at the moment the drive went. A drive that wedges (`ROOT_NOT_ANSWERING`) while the machine happens to be up to date gets one balloon - `"Sync paused: Your Creators Club drive is not answering - reconnect it or restart this computer."` - and then nothing, indefinitely. The tray line stays correct, but the tray is not looked at; the editor keeps working in Resolve against a wedged mount and their footage is on one disk for as long as it lasts. This is the *harder* failure of the two (a physically absent drive is obvious; a wedged one is not).
- **Proposed:** reuse the reminder machinery for a duration rule rather than an owed-work rule: any non-present root state that persists past ~2 hours earns a reminder on the same cadence, with the state's own `state_sentence`. The episode file already exists; only the trigger changes.
- **Effort:** S **Value:** med **Confidence:** med

## Still open from 08-28
- **SYNC-4** (an upload-only project can never be repathed): not built - `repath.py:194-196` still `continue`s on a missing local folder, and upload-only machines never have one.
- **SYNC-9** (frozen manifest walk): partly built - `sync_conflicts` landed, but `manifest.py` still has no `scanned_at` stamp, no reported cache age, and `start()` still guards on `self._thread is not None` (`manifest.py:261`) rather than `is_alive()`.
- **SYNC-14** (a renamed computer gets somebody else's plan or none): not built - `selection.py:31` is still `platform.node()` and `machine_id` is not sent with `?machine=`.
- **SYNC-18** (`_verify_startup_ignores` has no aggregate budget): partly built - the stop-event exit and `_latch_unverified` are in (`sequencer.py:1158-1167`), but there is still no wall-clock cap on the serial GETs.

## Cross-cutting notes
- **Dashboard:** SYNC-101 and SYNC-102 both want one new `sync_guard` sub-model each (`shared_folders`, `repath_blocked`); `SyncGuardIn` is `extra="allow"` (`api.py:6300`) so an undeclared key is at least named now, but neither becomes a chip without a column. SYNC-113's slug-vs-label leak also renders on the machine row.
- **Resolve/app area:** a server-side project rename (SYNC-102) is the largest un-relinked event in the product; whoever owns `resolve_bridge`/`fixer` should know that `repath` moves a whole project directory with none of `file_moves`' relink or undo journal.
- **Installer/site:** SYNC-103 (`P:` hardcoded in `drive_swap.py`) and SYNC-114 (TrueNAS in two dialogs) are both COMMERCIAL_READINESS item 11 / "no customer's name in code" residue outside the areas that sweep covered; a repo-wide grep for a bare `"P:"` and for vendor names in Tk copy is worth one pass.
