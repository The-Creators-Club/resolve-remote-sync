# Companion app lifecycle, tray and UI (APP)

## Summary
This is the most defensively written area of the repo: every loop is supervised, every
guard fails in a named direction, and almost every hazard on my brief already has a
comment citing the incident that produced it (single-instance predecessor wait, UI
shutdown backstop, `_fit_payload`, `PendingTracker`'s liveness bound, `ui_dispatch`,
`crash_report`). The residual risk is therefore not *crashes* but **silence**: the
companion is excellent at surviving a fault and poor at telling anyone it survived one.
The biggest hole is that nothing on this machine or on the dashboard ever says "my
reports have not been accepted since Tuesday" -- a revoked token, a `dashboard_url`
typo or a 401 produces one WARNING and then DEBUG forever, with three green lanes and a
diagnostics bundle that does not carry the fact (APP-1). The cheapest strong win is a
three-field reporter health record (`last_success_at`, `last_status`, `consecutive_failures`)
surfaced in the tray line, `build_diagnostics()` and `sync_guard`. The second cheapest is
moving the two persistent safety latches out of `~/.ccsync/state/`, the one directory the
codebase itself says support sessions are told to delete (APP-3).

## Findings

### APP-1: nobody is told when the dashboard stops accepting this machine's reports
- **Lens:** pitfall
- **Where:** `companion/src/ccsync_companion/reporter.py:911-920` (`_run_cycle`), `reporter.py:846-857` (`post_once` raises on HTTPError), `companion/src/ccsync_companion/app.py:5040-5155` (`build_diagnostics`), `app.py:4361-4413` (`sync_guard`)
- **Scenario:** an admin revokes the editor's `cce1.…` per-editor token (dashboard Users page), or an installer typo leaves `dashboard_url = "http://nas.tail26290e.ts.net:800"`. The companion keeps running: lanes sync locally, the tray is green.
- **Today:** every POST raises; `_run_cycle` logs `WARNING` on the FIRST failure of the streak and `DEBUG` on every one after (`self._error_logged`). No lane detail changes, no toast, no tray line, and `build_diagnostics()` has no reporter section at all -- it prints `dashboard_url` but never "last successful report". A 401 (credential dead, needs a human) is indistinguishable from a 5-second timeout (NAS rebooting, self-healing). The machine simply goes dark on the fleet grid while the editor sees nothing wrong, which is the exact inversion of "the dashboard is what tells everyone whether their footage is syncing".
- **Proposed:** `DashboardReporter` keeps `last_success_at` (wall clock, so it survives into diagnostics), `last_status` (HTTP code or exception class) and `consecutive_failures`; persist `last_success_at` to `~/.ccsync/state/reporter.json` so it survives a restart. Add a `section("last dashboard report", ...)` to `build_diagnostics()`. Add a tray line "Dashboard: not reachable for 3h" once the streak exceeds ~10 intervals. Treat 401/403 specially: one toast ("Your CCSync credential was rejected by the dashboard -- sign in again"), a lane `detail`, and re-log at WARNING every hour rather than DEBUG.
- **Effort:** M   **Severity:** high   **Confidence:** high
- **Related:** identity.py's `preferred_report_token` precedence exists precisely because stale tokens 401'd "forever, invisibly" (S-15); this is the same failure one layer up.

### APP-2: IGNORE ALL is permanent for the session, invisible, and even "Scan whole project" honours it
- **Lens:** user-error
- **Where:** `companion/src/ccsync_companion/fixer.py:37-55` (`IgnoreTracker`, in-memory, no `clear()` caller anywhere), `app.py:2374-2388` ("Still respects ignore_tracker"), `popup.py:552` (`perform_ignore_all`), `popup.py:1944-1947` (headless fallback auto-ignores)
- **Scenario:** the out-of-tree popup opens with 65 clips (ruskin's PC does this on every start -- CR-27). The editor is mid-edit, wants the modal gone, and clicks IGNORE ALL. Later they think better of it and use tray -> Scan whole project.
- **Today:** the scan walks the whole media pool and reports nothing wrong, because `_take_popup_batch` and the scan both filter through `ignore_tracker.is_ignored`. Nothing in the tray, the log summary, diagnostics or the report says "65 clips are hidden because you skipped them". `grep` finds no caller of `IgnoreTracker.clear()`. The only cure is restarting the tray, which nobody knows.
- **Proposed:** (a) `scan_whole_project()` is an explicit "show me everything" -- have it clear the tracker first (it already deliberately bypasses `popup_enabled` and the snooze filter for the same reason); (b) keep a count and surface it -- a tray line "65 clip(s) skipped this session" and an `ignored_clips` integer in `sync_guard` so an admin can see a machine where somebody dismissed the fixer; (c) name the count in `build_diagnostics()`.
- **Effort:** S   **Severity:** high   **Confidence:** high

### APP-3: the two persistent safety latches live in the directory the code says people are told to delete
- **Lens:** pitfall
- **Where:** `app.py:908-916` (`guard_state_dir = …/"state"`, `BREAKER_STATE_FILENAME`, `HALT_STATE_FILENAME`), `sync/lane_guard.py:82-83`, contrast `machine.py:58-63` ("`state/` is the directory a support session is most likely to be told to delete") and `upgrade.py:170-213` (the floor moved out for exactly this reason)
- **Scenario:** lane B's breaker trips on an editor's machine. Support (or the editor, following an old note) does the usual "close CCSync, delete `~/.ccsync/state`, start it again".
- **Today:** `lane_b_breaker.json` and `sync_halt.json` go with it. The breaker -- which `docs/SYNC_SAFETY.md` says only a human may clear -- clears itself, and a *fleet* halt an admin set clears on that machine too. Both were made persistent specifically so a restart could not clear them (CLAUDE.md: "Never make a safety latch in-memory-only"), and then placed where a restart-adjacent ritual does.
- **Proposed:** move both to `config_mod.CONFIG_DIR` beside `machine.json`/`upgrade_floor.json`, with the one-time legacy read `upgrade.adopt_legacy_floor()` already models. Failing that, have `BreakerState`/`HaltState` write a tombstone (`state_wiped.json`) beside config.toml when they find `state/` missing but the tombstone marker absent, and report `state_reset: true` in `sync_guard` so the dashboard shows that a latch may have been erased.
- **Effort:** S   **Severity:** high   **Confidence:** high
- **Related:** CR-45, `docs/SYNC_SAFETY.md`

### APP-4: `config.set_value` rewrites config.toml non-atomically -- a bad moment there takes the machine to ALL DEFAULTS
- **Lens:** pitfall
- **Where:** `config.py:1354-1402` (`text = path.read_text(); … path.write_text(…)`), called from `settings_window.py:146`; contrast `identity.py:249-255`, `machine.py:100-102`, `eula.py:986-988`, `upgrade.py:125-127`, which all use tmp + `replace`
- **Scenario:** an editor uses the new Settings -> THIS COMPUTER role switch (companion 0.9.54, CR-88) on a machine whose disk is full, or the process is killed / the machine loses power in the millisecond `write_text` has truncated the file and not yet refilled it.
- **Today:** `config.toml` is left empty or half-written. On the next start `load_config` catches `TOMLDecodeError`, logs "falling back to ALL DEFAULTS", and returns defaults: blank `local_root`, blank `remote`, blank `dashboard_url`, no `report_token`. The lanes refuse (DEL-3 path, correctly), but the machine also stops reporting entirely -- `dashboard_url` is blank, so `DashboardReporter.enabled` is False and no thread is even created. The machine vanishes from the fleet grid with the editor's credentials gone, and the only route back is a reinstall. `_config_load_error` is recorded but only reaches the log and the lane detail, which nothing can now transmit.
- **Proposed:** write through `path.with_name(path.name + ".tmp")` + `secretfile.harden` + `replace`, exactly as `identity.save_identity` does (config.toml holds a report token too, so the harden-before-rename ordering matters). Additionally: keep a `config.toml.bak` of the last successfully-parsed file and, when `load_config` hits a decode error and a backup exists, log LOUDLY and load the backup rather than defaults -- "the settings you had yesterday" beats "no settings at all".
- **Effort:** S   **Severity:** high   **Confidence:** high

### APP-5: an upgraded build that boots and then dies has no way back -- the rollback copy is deleted 60 s in
- **Lens:** pitfall
- **Where:** `upgrade.py:96` (`CHILD_TAKEOVER_GRACE_SECONDS = 2.0`), `upgrade.py:1005-1019` (the poll window), `app.py:6725-6731` (`threading.Timer(60.0, upgrade_mod.cleanup_old_exe)`), `upgrade.py:450-478`
- **Scenario:** a published build starts fine, puts a tray icon up, and then hits a fault three minutes later -- a Tk failure in the first dialog, a `TclError` on a locked session, an exception on a code path only one editor's config reaches. It exits (or the process is restarted at the next logon into the same fault).
- **Today:** the child survived 2 s, so the parent stood down and exited; 60 s later `cleanup_old_exe` deleted `<exe>.old`. There is no rollback copy left, `note_version_start` records the new version regardless of whether the run was healthy, and nothing counts restarts. On Windows the Run key relaunches at each logon into the same fault; on macOS the LaunchAgent is RunAtLoad-only, so the machine simply has no companion. A whole fleet can take this offer.
- **Proposed:** two cheap changes. (1) Gate `cleanup_old_exe` on evidence of health rather than a 60 s timer -- delete the `.old` only after this build has had one dashboard report ACCEPTED (or after ~10 minutes of uptime), keeping the rollback binary for the window in which a bad build actually manifests. (2) Extend `last_version.txt` into `last_version.json` with `{version, starts, first_start_at, last_clean_shutdown}`: increment `starts` on each launch of the same version, reset it on a clean `shutdown()`, and when it reaches 3 starts inside 10 minutes with an `<exe>.old` present, restore the `.old` and toast "The last update kept crashing, so CCSync went back to vX". That is an automatic rollback built entirely from mechanisms already here (`_rollback`, `note_version_start`, `_default_spawn`).
- **Effort:** M   **Severity:** high   **Confidence:** high
- **Related:** AUDIT_2 CORE-H6/H7, R11

### APP-6: a crash report is written and nothing anywhere surfaces it
- **Lens:** safeguard
- **Where:** `crash_report.py:1-35` (the docstring names "the tray stayed up with a dead lane" as the failure to fix), `crash_report.py:255-270` (`handle` -> a file + one log line), `app.py:5040-5155` (diagnostics has no crash section), `app.py:4361-4413` (`sync_guard` has no crash counter)
- **Scenario:** a background thread raises out of an unsupervised call -- e.g. a tray `_spawn` worker, or `_pump`'s re-arm failure path in `ui_dispatch.py:429-455`.
- **Today:** `threading.excepthook` writes `~/.ccsync/crashes/<stamp>-<thread>.json` and logs one ERROR that rotates away at 5 MB. The tray stays green; the dashboard never hears; `build_diagnostics()` -- the thing an admin actually asks for -- does not mention the directory exists. The stated problem is unfixed by the fix.
- **Proposed:** count the files in `crash_dir()` at start and after each write; add `crashes: {count, newest}` to the `sync_guard` section (it is a handful of bytes and is never shed by `_fit_payload`); add a diagnostics section listing the newest three crash file names and their exception types; add a tray advisory line when the count is non-zero ("A background task failed -- Copy diagnostics"). No new plumbing: `sync_guard` is exactly the "an admin cannot see this any other way" channel.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** COMMERCIAL_READINESS item 13

### APP-7: a slow logon leaves the companion permanently headless, and the Explorer-restart repair can never fire
- **Lens:** pitfall
- **Where:** `tray_native.py:784-800` (`run()`: `_create_window()` + `_add_icon()` in one try; on failure `self._stopped.set(); return` -- the pump never starts), `tray_native.py:271-272` (`_NIM_ADD_RETRIES = 6`, `_NIM_ADD_RETRY_DELAY = 0.5` -> a 3-second budget), `tray_native.py:1035-1044` (the `TaskbarCreated` repair, reachable only from inside `_pump`), `app.py:6693-6704` (falls back to headless and never retries)
- **Scenario:** a domain logon on a laptop; the Run-key companion starts before Explorer's notification area will accept `NIM_ADD`. Three seconds is not enough.
- **Today:** `_add_icon` raises, `run()` returns without ever pumping messages, so the window that would receive the `TaskbarCreated` broadcast is dead. `run_detached` waits 5 s on `_running`, gives up and returns anyway; `start_tray` hands back an Icon that will never show anything, `_notify_tray` silently swallows every toast, and `run()` sits in `while not self._stop_event.is_set(): wait(1.0)` for the whole session. The editor sees no icon, double-clicks the exe, and is told "CCSync is already running. Look for the CCSync icon in your system tray" (`app.py:543-575`) -- pointing at an icon that does not exist. There is no menu, so no Quit, no Sign in, no diagnostics.
- **Proposed:** separate the two steps: create and PUMP the window unconditionally, and treat `_add_icon` as retryable -- retry on a `SetTimer`/`after`-style tick (30 s, indefinitely) in addition to the existing `TaskbarCreated` handler, which then works for the "Explorer was not up yet" case as well as "Explorer restarted". Independently, when `app.run()` ends up headless, log at ERROR and put `tray: none` into the report payload so an admin can see a machine that has no UI; and have `_warn_already_running` say "…but its tray icon failed to appear, so restart the computer or run it from the Start menu" when a marker file written by the headless path is present.
- **Effort:** M   **Severity:** high   **Confidence:** med

### APP-8: the tray's Pause is invisible to the dashboard and silently forgotten on restart
- **Lens:** pitfall
- **Where:** `app.py:743` (`self._paused = False`, never read from disk), `app.py:5396-5450` (`toggle_pause`), `app.py:4144-4185` (`_stop_lanes` sets no lane `detail` and no `STATE_PAUSED`), `app.py:4361-4413` (`sync_guard` carries halt + breaker but not pause)
- **Scenario:** an editor on a hotel 4G hotspot clicks "Pause syncing" to protect their data allowance. That night the machine takes an auto-update (`site.toml [features] auto_update`) or is simply rebooted.
- **Today:** the new process starts with `_paused = False` and syncs. Meanwhile, while it IS paused, the fleet grid shows the lanes as ordinary `idle` with no detail -- an admin chasing "why is this editor not uploading" has nothing to distinguish "paused by the person at the keyboard" from "nothing to do". Both the halt and the breaker were made persistent and reported for exactly these reasons; pause was left as the odd one out.
- **Proposed:** persist the flag beside the halt (`~/.ccsync/paused.json`, or `state/` -> see APP-3) with who/when, restore it in `__init__`, and have `_start_lanes`'s existing `if self._paused` refusal stamp a lane `detail` ("PAUSED from the tray on this computer, <when>"). Add `paused: {since, by}` to `sync_guard`. A pause that outlives a restart also wants an expiry or at least a tray line stating its age, so "paused three weeks ago and forgotten" is visible.
- **Effort:** S   **Severity:** med   **Confidence:** high

### APP-9: one un-dismissed window blocks every update path on that machine, indefinitely and invisibly
- **Lens:** pitfall
- **Where:** `app.py:4258-4276` (`_standing_down_would_kill_work` -> `self._popup_active_lock.locked()`), `app.py:4278-4322` (`apply_upgrade` returns `"popup"`), `app.py:4672-4693` + `4767-4792` (auto/pushed retries every 90 s with `quiet_refusals=True`), `app.py:712` (the lock records no timestamp)
- **Scenario:** the out-of-tree popup opens on Friday while the editor is away from the desk; they lock the screen and go home. An admin presses [ UPDATE NOW ] on the dashboard on Monday to ship a fix.
- **Today:** the push is refused every report cycle with a log line and no toast (`quiet_refusals` from the second attempt on -- correct, CR-41), auto-update likewise, and the tray click says "Can't update while a CCSync window is open" only if somebody clicks it. Nothing tells the dashboard *why* the machine will not take the build; the admin sees a machine that ignores [ UPDATE NOW ]. Restart-from-Settings is blocked by the same predicate.
- **Proposed:** record `self._popup_opened_at` when the lock is taken and expose `blocked_by: {reason, age_seconds}` in `sync_guard`, so the fleet grid can say "update blocked: a CCSync window has been open for 3 days". Additionally: once a popup has been open with no interaction for (say) 4 hours, toast a reminder and pulse the tray -- the popup already knows how to stay up indefinitely, and nothing currently notices that it has.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** CR-27, CR-41

### APP-10: a cloned disk gives two computers one identity, one machine_id and one credential
- **Lens:** user-error
- **Where:** `machine.py:80-107` (`machine_id` -- minted once, never bound to anything, no hostname recorded), `identity.py:218-255` (`identity.json` holds `editor_report_token`), no installer/onboarding code touches either (`grep machine.json installer/ onboarding/` -> nothing)
- **Scenario:** the studio images one editing rig and clones it to the next two -- normal practice, and the fastest way to stand up a second machine for the same editor (which the per-machine plan work explicitly encourages).
- **Today:** all three machines report the same `machine_id` under different hostnames. The dashboard's documented behaviour is to "carry the plan across when it sees a known id under a new name", so the machines take it in turns to be recognised as each other; whichever reported last owns the plan. They also share `identity.json`, i.e. one editor's per-editor revocable token is now on three boxes, and a Syncthing folder shared with "that computer" reaches the wrong one.
- **Proposed:** record the hostname at mint time in `machine.json` (`minted_on`), and report both. When the current hostname differs from `minted_on`, report `machine_id_renamed_from` -- a legitimate rename says so once and settles, whereas a clone produces reports from two hostnames flip-flopping on the same id, which the dashboard can detect and flag ("two computers are claiming to be the same machine"). Independently, the Windows/macOS uninstall + first-run paths should delete `machine.json` and `identity.json` (sysprep-style), and the onboarding wizard should refuse to proceed when `identity.json` names an editor other than the one signing in.
- **Effort:** M   **Severity:** med   **Confidence:** med
- **Related:** MULTI_MACHINE_PLAN.md WP1, CR-91 (dashboard side)

### APP-11: `set_value` can silently write the role into a TOML table and the button then does nothing forever
- **Lens:** pitfall
- **Where:** `config.py:1391-1402` (matches `^\s*key\s*=` anywhere in the file; when absent, appends at EOF), `settings_window.py:88-96` (`_mode_needs_restart` compares disk vs memory)
- **Scenario:** an admin adds a `[proxy]` or `[experimental]` table to an editor's `config.toml` by hand (nothing in the shipped `DEFAULT_TOML_TEXT` has one, so this is the plausible route). Later the editor uses Settings -> WIRED TO THE SERVER.
- **Today:** `mode` is not in the file, so the line is appended at the end -- *inside* the last table. `tomllib` then parses it as `proxy.mode`, top-level `mode` stays absent, `load_config` returns the old value, `_mode_needs_restart` compares equal and never shows the "takes effect next start" banner, and the button appears to do nothing at all, every time. Nothing logs a discrepancy.
- **Proposed:** `set_value` should insert before the first `^\s*\[` line rather than at EOF, refuse to match a key that appears after a table header, and -- cheapest and most valuable -- READ THE FILE BACK through `load_config` and verify the value took, logging ERROR and returning False if not. `action_set_role` already has a "Couldn't save that -- see the log" path to route the failure into.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** CR-88

### APP-12: a machine that was installed and never signed in is completely invisible
- **Lens:** pitfall
- **Where:** `reporter.py:826-836` (`post_once` returns before any request when `get_editor_name()` is None), `app.py:3808-3826` (`editor_identity`), `app.py:5387-5390` (`_login_gate_blocks_sync`)
- **Scenario:** an editor runs the installer, never gets round to the tray sign-in (or signs in with the wrong password twice and gives up). Or a token expires while they are on holiday -- `_identity_watch_loop` stops the lanes and toasts, and the machine goes quiet.
- **Today:** the reporter makes no request at all, deliberately, so the machine never appears on the fleet grid. Nobody can tell "installed and never signed in" from "never installed", and the one screen that would tell the admin to go and help this person shows nothing.
- **Proposed:** when there is no verified identity but a shared/config report token exists, send a MINIMAL heartbeat -- `{machine, machine_id, platform, companion_version, unclaimed: true, reason}` and no lane/manifest sections -- so the dashboard can list "computers waiting for someone to sign in". It reports no editor identity, so it cannot pollute any `(editor, machine)` table; it needs a dashboard-side accept path (cross-cutting, below).
- **Effort:** M   **Severity:** med   **Confidence:** high

### APP-13: nothing anywhere notices that this machine's clock is wrong
- **Lens:** safeguard
- **Where:** `identity.py:325-339` (`is_valid` compares the token expiry to `time.time()`), `reporter.py:463` (`reported_at` is this machine's wall clock), `app.py:1279-1330` (`_on_report_response` -- a natural place to check), `eula.py:983`, `crash_report.py:137`
- **Scenario:** a dead CMOS battery, a VM restored from a snapshot, or a Mac that came back from sleep before NTP caught up.
- **Today:** a clock far in the future invalidates a pre-CR-86 identity token instantly -- `_identity_watch_loop` stops the lanes and tells the editor their sign-in expired, which is a lie they cannot act on (`sign_in` even hints at this in its failure text, but only after they try). A clock far in the past skews `reported_at`, `last_sync`, log lines and the crash-report stamps that a support session is reading; the dashboard's `ago` rendering has already produced one bug from timestamp semantics (CR-89).
- **Proposed:** have the dashboard put its own `server_time` in the report reply and have `_on_report_response` compare it to `time.time()`; over ~5 minutes of skew, log a WARNING once an hour, add a `clock_skew_seconds` field to `sync_guard`, and add a diagnostics line. Then make the "sign-in expired" toast conditional: when skew is large, say "this computer's clock is <n> hours out, which is why the sign-in looks expired -- fix the clock" instead.
- **Effort:** M   **Severity:** med   **Confidence:** high

### APP-14: the licence watcher never arms on a machine that also has a config error
- **Lens:** pitfall
- **Where:** `app.py:6689-6720` (`if errors: notify(...) else: eula_problem = ...; threading.Thread(_licence_watch)`)
- **Scenario:** an upgraded machine has both a config problem (a blank `remote_root`, say) and no `eula_accepted.json` -- exactly the shape CR-22 describes for a self-upgraded editor.
- **Today:** only the config toast fires (deliberately -- two "NOT SYNCING" toasts tell nobody anything), so `_licence_watch` is never started at all. The admin fixes config.toml remotely, the editor restarts, and only THEN does the licence offer begin -- one extra round trip on a machine already parked, and if the editor does not restart, nothing changes.
- **Proposed:** always start `_licence_watch` when there is a licence problem; let it stay quiet (it only ever opens a dialog, which is the action the person at the keyboard can take regardless of the config fault) and let the toast precedence stay as it is. Cost: one thread that mostly sleeps.
- **Effort:** S   **Severity:** low   **Confidence:** high
- **Related:** CR-22, CR-27, CR-27a

### APP-15: the single-instance guard fails open on the one condition most likely to break it
- **Lens:** pitfall
- **Where:** `app.py:373-413` (`_acquire_lock_file`: `except Exception: return True  # never block startup on the guard itself failing`), `app.py:494-521`
- **Scenario:** the editor's home volume is full (a 40 GB original half-copied into the tree is the usual cause here). `path.write_text(str(os.getpid()))` raises `OSError`.
- **Today:** the guard returns True and a second companion starts alongside the first -- two watchers on the Resolve C extension, two rclone lane sets on one tree, two reporters under one identity, two self-upgrades renaming the same exe: precisely the catastrophe the module docstring enumerates. The trade is deliberate, but the failure mode that triggers it is not a rare one, and it is silent (a single DEBUG line).
- **Proposed:** keep failing open, but distinguish the cases: a read failure or a missing directory is benign, whereas an `OSError` with `errno.ENOSPC`/`EROFS` on the WRITE means "the guard is off" -- log at ERROR, toast the editor ("CCSync could not check whether it is already running -- restart this computer if you see two icons"), and record it in `build_diagnostics`. On win32 the ctypes path already falls back to the lock file, so this covers both.
- **Effort:** S   **Severity:** med   **Confidence:** high

## Cross-cutting notes
- **Dashboard/API agent:** `db.py:676` derives machine presence from `reported_at, reported_at` -- the client's own wall clock -- while `machine_state` also stores a server-side `received_at`. A machine with a wrong clock (APP-13) can look permanently fresh or permanently stale on the fleet grid. Also: APP-1's reporter-health and APP-12's "unclaimed machine" heartbeat both need a receiving end; and `SyncGuardIn` still drops `syncthing_supervisor` on `extra="ignore"` (noted in `app.py`'s own comment at `sync_guard`) -- the same will happen to any new field proposed here unless the schema is widened at the same time.
- **Sync-lane agent:** `RcloneLane.stop()` does not set `STATE_PAUSED`, so a tray-paused lane reports its last state (usually `idle`) with no detail -- relevant to CR-91's "a lane that never finishes and never errors looks exactly like a lane that is working", from the other direction.
- **Installer/onboarding agent:** nothing in `installer/` or `onboarding/` deletes or regenerates `~/.ccsync/machine.json` or `identity.json`, which is what makes disk cloning (APP-10) hand two machines one identity and one credential.
