# Adversarial review, wave 2: companion / onboarding / installer

Reviewer: Fable (one of three), 2026-09-25. Read-only. Base: HEAD 4462a2a,
reviewed against the uncommitted working tree. Area: `companion/`,
`onboarding/`, `installer/` (groups c-app, c-sync, c-ui, c-resolve,
c-broll-music, c-ytdl, c-media, c-core, onboarding). Wires into the
dashboard were checked from this side only.

## Method

- Read every hunk of `git diff HEAD` over the three trees (76 files,
  +5273/-960) against its ledger entry and, where the mechanism was not
  obvious from the hunk, the surrounding code at HEAD and in the tree
  (lock order, caller list, wire shape, platform branches).
- Ran the eight new companion test files on the tree: 351 passed.
- Honesty spot-checks: built eight scratch copies of `ccsync_companion`
  with ONE module swapped back to `git show HEAD:` and ran the regression
  tests that claim to cover it (`-o pythonpath=<scratch>`). selection.py:
  5/5 fail on HEAD. file_moves.py: 4/4. identity.py: 4/4. app.py: 7/7.
  lane_guard.py: 3/3. ytdl_executor.py: 6/6. sequencer.py: 3/3.
  (syncthing_admin.py could not be swapped alone: the tree's
  borrowed/shared managers import `release_guard` from it, so collection
  errors, which is an import dependency, not a test problem.) Every test
  read for this exercised the real code path and stubbed only the wire or
  the disk, not the thing under test.
- Did not run: the onboarding Tk suite (real windows; the full gate is
  running in parallel), `run_all_tests.ps1`, anything live.

## Verdict table

REAL-AND-SAFE = the finding is closed on every entry point I could find
and I found no regression. Notes give the residual, if any.

### c-app (app.py)

| Finding | Verdict | Notes |
|---|---|---|
| bug-comp-app-2 consolidate ignores halt/licence/sign-in | REAL-AND-SAFE | `_lanes_refusal()` asked at the door and before lane A and lane B; toast says the upload did not run. The base rig is unchanged: `sync_enabled=false` was already the first gate, so "works straight off the server" is never a new refusal there. |
| bug-comp-app-3 diagnostics ask stamped before the upload | REAL-AND-SAFE | Stamp moves to `_settle_diagnostics_request(ok=True)`; read-modify-write of `diagnostics_sent.json` now under one lock from both writers. Residual (low, below): the in-memory in-flight latch has no expiry. |
| bug-comp-core-3 site manifest fetched once | REAL-AND-SAFE | `_site_refresh_loop`: fetch+save every 900 s, 120 s after a failure, exits on `_stop_event`. `refresh_site` did only fetch+save+cache-fallback, so nothing was lost. One GET/15 min per machine against an existing route. |
| bug-comp-app-4 relink-done answer | ALREADY_FIXED (d-db) - correct | Companion half sends `ok=True` with no `state`/`relink_pending`; that is the shape the dashboard arm matches. Contract pin test only. |
| bug-comp-app-5 off-cycle report races the reporter thread | REAL-AND-SAFE | RLock around the fan-out. `_report_off_cycle` starts a daemon thread and never joins it, so no deadlock while the reporter thread holds the lock. |
| bug-comp-app-6 / bug-wire-6 answer appended outside the lock | REAL-AND-SAFE | Filter and append under one hold. |
| bug-comp-app-7 posix pid file trusts any live pid | REAL-AND-SAFE | `ps -o command=` + own-executable match + "ccsync" token; fail-safe (cannot tell = holder). Windows untouched. Needs a Mac build to reach the field. |
| ui-comp-windows-3 raw EULA.md in the licence dialog | REAL-AND-SAFE | Display only; hash/version read the untouched bytes. |
| bug-comp-core-4 / bug-wire-4 sign-in drops `upgrade_none_reason` | REAL-AND-SAFE | Passes the whole verify reply; falls back for a double. Dashboard-first is nicer, either order harmless. |
| bug-comp-media-5 (owed) no-ffmpeg sentence | REAL-AND-SAFE | Copy only. |
| bug-comp-resolve-2 (owed) rate limiters read the 20 s cache | REAL-AND-SAFE | `max_age=0.0` at both limiters and `undo_last_fix`; `undo_last_fix_summary` keeps the cache (menu build). |
| bug-comp-ui-1 (owed) register the popup lock with the picker | REAL-AND-SAFE | One call in `__init__`. See the picker row under c-ui for the macOS consequence. |
| ui-copy "both sync lanes" | REAL-AND-SAFE | Copy only; nothing parses it. |

### c-core (identity.py, machine.py, reporter.py, config.py)

| Finding | Verdict | Notes |
|---|---|---|
| bug-comp-core-4 arch + reason on /verify | REAL-AND-SAFE | `arch` is ignored by a VerifyIn that does not declare it (pydantic default); `upgrade_none_reason` read with `.get`. |
| bug-comp-core-6 remint not reported until restart | REAL-AND-SAFE | Generation counter in machine.py, reporter drops its cache on change. machine.py imports only config, no cycle. |
| bug-comp-core-7 unusable sign-in reply overwrites identity.json | REAL-AND-SAFE | `is_valid(candidate)` before save/swap/adopt. Behaviour change (a signed-in editor stays signed in on a bad re-sign-in) is the right direction. |
| bug-wire-3 lane strings uncapped, older dashboard 422s the report | REAL-AND-SAFE | Caps mirror `LaneReportIn`/`TransferIn`/`CompletedIn`; `None` passes through; drift guard reads the dashboard's api.py. |
| logic-resolve-3 (owed) `resolve_factory_luts_extra` default | REAL-AND-SAFE | DEFAULTS + template + example. |
| ui-copy-4 (owed) "machine" in identity.py | REAL-AND-SAFE | |

### c-sync (lane_guard, rclone_lane, sequencer, syncthing_admin, syncthing_lane, shared_folders, borrowed_folders, selection, file_moves, drive_reminder, manifest, base)

| Finding | Verdict | Notes |
|---|---|---|
| bug-comp-rclone-2 followed moves never leave the cumulative counter | REAL-AND-SAFE | `known` clamped to the pass, discounted before the trip test, probe credited only for `probed - known`, eager reads the RAW count. `_relocate_trashed` runs before `_account_pass` and resets the count per pass. What counts as "known" (moved, ambiguous, not-synced-here, never own-path) is exactly what the trip-time probe already discounted at HEAD, so the cumulative rule now agrees with the trip rule rather than gaining a new blind spot. |
| bug-comp-rclone-3 free-space park never clears after the prune | REAL-AND-SAFE | Reason rebuilt per measurement; prune works towards `clear_free_bytes` while parked. |
| bug-comp-syncthing-1 a locked proxy turns a done move into a failed one | REAL-AND-SAFE | Original's rename alone is fatal; proxies best-effort and named in the detail; resume arm also accepts a retryable/blocked row whose intent paths match with src gone and dest present. Residual (low, below): a `blocked` "destination already exists" row can match later. |
| bug-comp-syncthing-2 upload-only borrower builds a lender | REAL-AND-SAFE | |
| bug-comp-syncthing-3 upload-only lender "covers" a full borrower | REAL-AND-SAFE (companion half) | Works against 0.7.57/0.7.58 as they are; the optional d-api `_expand_includes` change helps companions <= 0.9.78 only. |
| bug-comp-syncthing-4 late sequencer thread unpauses through a halt | REAL-AND-SAFE | `_set_paused(False)` is the one door and refuses under `_is_halted()` (cannot tell = halted); `accept_folder(release_ok=)` leaves a folder paused (it is POSTed `paused: True`) if the halt landed during its writes; `release_halt` clears the latch before `_release_lane_c_folders`. |
| bug-comp-core-5 scan overlapping a drive unplug reports zero | REAL-AND-SAFE | Presence re-checked after the walk; unanswerable = present, as before. |
| logic-sync-truth-2 manifest cap | PARTIAL, correctly routed | Companion side already exact; the rest is d-db/d-ui. |
| logic-sync-truth-4 disk-floor park | ALREADY_FIXED (rclone-3) - correct | Copy owed to d-ui. |
| logic-sync-truth-3 lane C with no peer says "syncing N" for ever | REAL-AND-SAFE | `progress_token = "c:<bytes>"` from Syncthing's connection totals (pings move it, so a connected lane is never "stalled"); `NO_PEER_DETAIL` only when the connection list is readable and lists nobody. Existing optional wire field; dashboard 0.7.57 already runs the stall rule on it. |
| bug-comp-rclone-4 stray scan / express attribution without NFC | REAL-AND-SAFE | Comparison only; reported paths keep the disk's bytes (CR-90). |
| bug-comp-rclone-5 a trashed file counted as transferred | REAL-AND-SAFE | `_last_run_moved` still sees a trash-only pass as work. |
| bug-comp-syncthing-5 backslash escapes in .stignore on Windows | REAL-AND-SAFE, UNVERIFIED LIVE | Class form `[[]`/`[{]`/`[}]` on nt only; self-heals via `_ensure_ignores`. Not measured against a real Windows Syncthing (the ledger says so). Worth the 5-minute spike it asks for before the next borrowed-folder customer. |
| bug-comp-syncthing-6 cached plan not keyed by editor | REAL-AND-SAFE | Refused only when BOTH names are known and differ; the halt re-pause reads `any_editor=True` (it only pauses). Additive key. |
| bug-comp-syncthing-7 re-pointed shared folder comes up empty | REAL-AND-SAFE | `_repoint` = SYNC-6 guard, pause, move (only Luts/Stills, so `_default_move`'s cross-volume copy is bounded), mkdir, PATCH; marker never created (right: a marker on an empty dir would announce every file deleted). `reconcile` returns `{}` when the root is absent, so an unplugged drive can NOT raise `marker-missing`. Copy note below (low). |
| logic-plans-5 untick fallback that never fires | REAL-AND-SAFE (as revised) | Widening removed; a machine-scoped DELETE that provably removed nothing asks the person's union and refuses unless the tick is gone everywhere. `app.remove_project_from_machine` stops on `False` before any delete. Reads `changed`/`selection`, which 0.7.57 sends. |
| logic-sync-truth-6 (owed) drive reminder recurs for downloads; lane C direction | REAL, POLICY CHANGE (below) | Recurs unless every owed lane is a KNOWN download (lane B, lane C `:down`); `direction` in-process only; `lanes` in the JSON record additive. |
| ui-copy-4 (owed) file_moves wording | REAL-AND-SAFE | `DETAIL_NOT_SYNCED_HERE` untouched; nothing parses the rest. |
| bug-dash-api-2 (owed) proxy keeps the old stem on a renaming move | REAL-AND-SAFE | New stem; NFC-equal stems keep their own bytes; same-disk-file goes through `_rename_case_only`; never overwrites a different file. |
| logic-plans-1 (owed) widening skew belt | REAL-AND-SAFE | A `changed: true` answer that still lists the slug is refused, not widened. |
| logic-plans-4 (owed) borrowed per-file manifests | DEFERRED - correctly | A d-db/d-ui design decision, argued well. |

### c-ui (tray, tray_native, popup, settings_window, theme, ui_copy, crash_report)

| Finding | Verdict | Notes |
|---|---|---|
| bug-comp-ui-1 ingest picker: no lock, timeout abandons the dialog, second root | REAL-AND-SAFE on Windows; macOS consequence below | One live picker; joiners wait on it; WM_CLOSE at the timeout (win32); the picker THREAD releases the popup lock when the dialog ends. |
| ui-comp-windows-2 "nothing ticked" drawn red in Settings | REAL-AND-SAFE | Uses the tray's own `_BLOCKED_INFORMATIONAL`. Owner rule honoured. |
| bug-comp-ui-2 macOS menu rebuild under an open menu | REAL-AND-SAFE (not run on a Mac) | Rebuild deferred to `menuDidClose_`, queued after the callback. |
| bug-comp-ui-3 WorkProgressWindow.close() before the root exists | REAL-AND-SAFE | `_closed` set only by the window thread's exit; flag checked after build and on first tick. |
| bug-comp-ui-4 work window outside the popup lock | DEFERRED - correctly | Owner decision; the ledger's recommendation (coexistence, fix the comments) is the sensible one. |
| bug-comp-ui-5 five dialog builders leak a mapped root on raise | REAL-AND-SAFE | `release_root` on the building thread; original exception re-raised. |
| bug-comp-ui-6 `_hicon_cache` mutated during teardown | REAL-AND-SAFE | |
| ui-comp-windows-1/4/5/6/7/8/9/10/11, ui-onboarding-9 (theme), ui-copy-5 | REAL-AND-SAFE | All copy/layout/contrast/keyboard. `neon_button` now `takefocus=1`, 1 px ring, Enter -> `invoke()` + "break": a focused CANCEL on Enter is now CANCEL (was: the root's `<Return>`), which is the intent. |
| logic-sync-truth-6 tray half, logic-sync-truth-3 tray half | REAL-AND-SAFE | `_lane_direction` reads `NO_PEER_DETAIL` (imported from the lane) first, then the "sending" sentence; pin tests fail on a reword of either. |
| logic-resolve-1/4/5 (owed) popup halves | REAL-AND-SAFE | Undo pointer only on `ok` or `relinked > 0` (the review round's correction is right: a landed copy is not journaled). Destination watcher uses widget bindings, not a StringVar trace (CR-93). |
| bug-dash-ops-4 (owed) crash redactor | REAL-AND-SAFE | |
| bug-dash-ops-9 (owed) crash file O_TRUNC | REAL-AND-SAFE | `~NN` counter, numbered past the highest slot, `_age_key` sort. Docstring damage below. |
| ui-onboarding-8 (owed) Enter on themed buttons | REAL-AND-SAFE | |
| ui-copy-4 (owed) MODULES + plural `_WORD_RE` | REAL-AND-SAFE | The two rows it left red (app.py, broll_server.py) were fixed in round 3; scan passes. |

### c-resolve (resolve_bridge, resolve_journal, resolve_undo, fixer, luts, library, timeline_cards_*)

| Finding | Verdict | Notes |
|---|---|---|
| bug-comp-resolve-1 undo in the launch window recorded FAILED | REAL-AND-SAFE | `is_disconnection_message` exists; `retrying` is an existing state. |
| bug-comp-resolve-2 20 s name cache journals under the previous project | REAL-AND-SAFE | `max_age=0.0` in `_before_mutation` and the adjacent-proxy record. |
| bug-comp-resolve-3 Cards sweep pays the API walk | REAL-AND-SAFE | `library_timeline_items` -> `_library_timeline_items`, which takes `_bridge_call` itself (line 1446), so the lock invariant holds; `count_poll=False` keeps the watcher's valve. |
| bug-comp-resolve-4 orphan loop served after a role restart | REAL-AND-SAFE | `caller is self._client` before and after the request. The other repo's missing `stop()` is correctly flagged as out of scope. |
| bug-comp-resolve-5 lsof under `_API_LOCK` on macOS | REAL-AND-SAFE | Probe primed OUTSIDE the lock by the outermost `_bridge_call`, 2 s max age, cleared in `__exit__` (outermost only). The staleness argument holds: the only late answer that matters ("connect" while STARTING) needs a Resolve relaunch (>= 90 s). Never calls `scriptapp()`. |
| bug-comp-resolve-6 stat blip leaves a 0-byte reservation | REAL-AND-SAFE | `remove_reserved_name` deletes only an empty file. |
| bug-comp-resolve-7 uid-map cache keyed on identity | DEFERRED - correctly | Needs a live measurement; keying on `GetUniqueId` could trade slowness for a crash. |
| bug-comp-resolve-8 library picks rows[0] of a duplicated name | REAL-AND-SAFE | Refuses; bridge falls back to the API walk. |
| bug-comp-resolve-9 `.ccsync-tmp` left in the LUT library | REAL-AND-SAFE | Removes only its own fixed-suffix name. |
| logic-resolve-1 RETRY copies the whole file again | REAL-AND-SAFE | Reuse only for `name.ext`/`name (N).ext` with equal size AND three 1 MB windows equal; the reused copy skips `verify_copy` (it was verified when made). Also dedupes a second FIX ALL of the same source into a second project (improvement). |
| logic-resolve-2 one FIX ALL = several journals; second undo press lies | REAL-AND-SAFE | `hold_sessions` around each `fix_clip`; `undone_at` additive; admin undo-by-id of an undone journal now answers done/already back. |
| logic-resolve-3 factory LUTs offered | REAL-AND-SAFE | Judged by the top-level entry under Resolve's own LUT folder only (`search_dirs()` is that folder), so an editor's pack elsewhere is unaffected; an editor who drops their own "Sony" folder INTO Resolve's LUT folder is never offered (low, by design). The deletion of the factory copies already in `P:\Assets\Luts` is correctly left to the owner. |
| logic-resolve-4 root-level FIX ALL "Fixed" | REAL-AND-SAFE | Warns, does not refuse; refusal correctly left to the owner. |
| logic-resolve-5 partial relink | REAL-AND-SAFE (with owed round 3) | |
| logic-cards-9 stale-result refusal called "discarding" | REAL-AND-SAFE | `attached` key first; sentence fallback for a dashboard without it. |
| ui-copy-4 / ui-copy (owed) Cards wording | REAL-AND-SAFE | `PROBE_UNREADABLE` used by identity, so the constant change is safe. |

### c-broll-music, c-ytdl, c-media

| Finding | Verdict | Notes |
|---|---|---|
| bug-comp-broll-2 keep-sub-folders unticked fails every clip | REAL-AND-SAFE | Folder-blind tiers only after every exact tier consumed; hash veto kept. |
| bug-comp-broll-4 held staging never released | REAL-AND-SAFE | `held_bytes` is a new local key; `ended_at` re-stamped on a rerun (extends retention, acceptable). |
| bug-comp-broll-5 15-minute ceiling on every encode | REAL-AND-SAFE | Rule read from proxy_gen; `timeout=` offered only to a runner that takes it. |
| bug-comp-media-6 music insert into a straddling clip | REAL-AND-SAFE | Refuses before any delete. |
| logic-broll-music-2 1080p heavy original called the stand-in | REAL-AND-SAFE | Codec other than h264 retires; h264/unknown asks the job record; residual stated honestly. |
| bug-comp-broll-3 finished fetch jobs leak | REAL-AND-SAFE | `reap_finished` pops only DONE/FAILED; the page re-POSTs rather than polling, so nothing reads the popped job afterwards. |
| bug-comp-broll-6 upload queue survives a batch | REAL-AND-SAFE | |
| bug-comp-media-7 music decode 3x PCM, capped duration | REAL-AND-SAFE | |
| bug-wire-7 non-Latin-1 hostname header | REAL-AND-SAFE | Plain header when Latin-1, `-Pct` twin otherwise; servers ignore the twin until their owed halves land (documented degradation). |
| bug-comp-ui-1 (owed) PickerBusy in broll_server | REAL-AND-SAFE | |
| bug-music-ytdl-2 `--ignore-existing` | NOT_A_DEFECT - agreed | The three reasons (removes the healing resend, turns an overwrite into a silent mis-binding, buys nothing on the landed-upload retry) are right. |
| bug-comp-ytdl-2 stop mid in-place conversion | REAL-AND-SAFE | |
| bug-comp-ytdl-3 mid-job 403 never stops the executor | REAL-AND-SAFE | 401/403/404 on the HEARTBEAT only; 5xx stays a blip. Hand-back sentence uses an existing key. |
| bug-comp-ytdl-4 one failed install = 24 h off | REAL-AND-SAFE | Backoff 5 min doubling, capped at the cadence; any enabled pass with `ok=False` counts except the hand-managed override. Side effect: a DISABLED site whose ffmpeg-pair install fails now retries at 5/10/15 min instead of 15 (harmless). |
| bug-comp-ytdl-5 litter name delivered | REAL-AND-SAFE | `swap_in` returns `None`; staged original unstaged and kept as `.failed`. |
| ui-copy-4 c-ytdl half | REAL-AND-SAFE | `NOTICE_TEXT` correctly left (versioned legal text mirrored server-side). |
| bug-wire-7 ytdl half | ALREADY_FIXED - agreed | `_header_safe` already drops non-ASCII. |
| logic-ytdl-jobs-3 claim refusal said to the page | REAL-AND-SAFE (as revised) | `identity`/`identity_mismatch`/bare count as sign-in refusals; unknown codes stay quiet. |
| bug-comp-media-4 peaks of a video-only clip tours the fleet | REAL-AND-SAFE | Needs BOTH the empty probe and ffmpeg's own sentence. |
| bug-comp-media-3 `out_stem` unvalidated | REAL-AND-SAFE (as revised) | `/`, control, dot names refused fleet-wide; `\`/`:` refused retryably on Windows only, so a Mac or the pinned Linux engine still makes `Q&A: Ruskin`. The d-cards half (`cards_exec._paths`) is correctly owed with the same Linux caveat. |
| bug-comp-media-5 ffprobe not gated | REAL-AND-SAFE | `ffmpeg_available` only runs `-version` and checks exit 0, so asking it about ffprobe is sound. |
| bug-comp-media-8 NUL in a path escapes the runner | REAL-AND-SAFE | Broad `(ValueError, OSError)` catch: any other ValueError in `_media_paths`/`_whisper_command` is now a non-retryable FAILED with the exception text rather than a silent drop. Acceptable, noted. |
| ui-copy-4 (owed) proxy toast + low-space balloon | REAL-AND-SAFE | |

### onboarding + installer

| Finding | Verdict | Notes |
|---|---|---|
| logic-onboarding-1 the radio decides the role | REAL-AND-SAFE, POLICY (below) | Verified role now unread; radio seeded from config.toml `mode`. Destructive path guarded by `p_mapping_is_ours` (a mapping to the site's `smb_unc` or any non-loopback, non-subst target is refused), `$PIsForeign`, `validate_local_root`. A config with no `mode` line is already an editor machine to `effective_mode()`, so the "editor" default is not a new trap. |
| logic-onboarding-2 no fleet credential, wizard says DONE | REAL-AND-SAFE | `write_identity` carries `editor_report_token` and the shared token through (`save_identity` takes both); pasted key forced into config `report_token`, blank never erases; `report_token_kind` None from an older dashboard = old behaviour. |
| ui-onboarding-1 fixed 660x560 clips the bars | REAL-AND-SAFE | `before=` packing + grow-only fit. |
| ui-onboarding-2 raw EULA | REAL-AND-SAFE | Display only. |
| ui-onboarding-4 winget outcome | REAL-AND-SAFE | |
| bug-ops-4 macOS --full says removed without checking | REAL-AND-SAFE | Re-lists; `state/` kept; verdict wired. LF kept (per ledger). |
| logic-onboarding-3 licence-only problem launches the whole wizard | REAL-AND-SAFE (as revised) | "tray" only when the NEW build relaunched and not a dry run; wizard for a failed relaunch (that build may predate `_licence_watch`). |
| logic-onboarding-4/5, ui-onboarding-3/5/6/7/10/11/12 | REAL-AND-SAFE | Copy and page-keyed request guards. `CCSYNC_FROM_WIZARD` is an env var, ignored by older scripts. `test_macos_uninstall_profile.sh` / `test_macos_first_steps.sh` are NOT yet in `run_all_tests.ps1`/CI (owed to release-tools; other reviewer's area). |
| ui-onboarding-9 (owed) FIELD_BORDER | REAL-AND-SAFE | |

## Problems, ranked

### High

None found.

### Medium

1. **Two policy changes ride in as "bug fixes" and deserve an explicit owner
   nod before the commit message calls them fixes.**
   - `companion/src/ccsync_companion/drive_reminder.py:~95-140` and
     `:~537` (logic-sync-truth-6): CR-92's rule was "a reminder every half
     hour until the drive is back". Now an episode that owes ONLY known
     downloads (lane B, lane C `:down`) gets the first warning and no
     cadence; the Settings window then says reminders are off. The
     reasoning (a download resumes; only an upload's sole copy is at risk;
     matches the dashboard's safe-to-close rule) is sound and the safe side
     is kept (unknown lane or direction still recurs), but it narrows a
     behaviour the owner asked for by name.
   - `onboarding/steps.py:~1918-1990` (logic-onboarding-1): the account's
     role no longer corrects the radio. Consistent with CR-88 and
     MULTI_BASE_RIG_PLAN WP5, and the destructive branch is guarded
     mechanically, but an admin re-running the wizard on a wired machine
     now has to READ the radio (it is seeded from `mode`, so the default
     is right on any installed machine).
   Neither blocks; both should be one line in the commit message and, for
   the first, in `docs/SYNC_SAFETY.md` or wherever CR-92 is written up.

2. **`bug-comp-syncthing-5` (Windows `.stignore` classes) is unmeasured
   against a real Syncthing.** `companion/src/ccsync_companion/sync/syncthing_admin.py:203-245`.
   The fix does not depend on how Windows treats `\` (it emits none), and
   `[[]`/`[{]`/`[}]` is correct under gobwas glob rules by reading, but the
   lender's whole subtree stays invisible on the borrower if the reading is
   wrong, and the list reads back "confirmed" either way. The ledger asks
   for the same 5-minute spike. Not a blocker for the commit; a blocker for
   calling borrowed folders on Windows done.

### Low

3. **Docstring damage from the edits** (fix before commit, one minute each):
   - `companion/src/ccsync_companion/crash_report.py:11-12`: the header
     line "LOCAL, always on, no configuration, never leaves the machine:"
     was overwritten by the new path line, which now appears twice.
   - `companion/src/ccsync_companion/tray_native.py:86`: " is for the
     tooltip (ui-comp-windows-7...)" lost its subject (`log_full=False`).
   - `companion/src/ccsync_companion/broll_server.py:253`:
     `README_SNIPPET ="""` (missing space; cosmetic).

4. **Diagnostics in-flight latch has no expiry.**
   `app.py:~9220-9235` (`_apply_diagnostics_request`). `_diagnostics_request_inflight`
   is cleared only by `_settle_diagnostics_request`, which runs on the
   upload thread. `Thread.start()` raising, or a poster that blocks past
   any timeout, leaves the latch set for the process lifetime and every
   redelivered ask is refused with no log line. Scenario is rare (the
   poster goes through the reporter's timed HTTP) but the old code could
   not get stuck this way. A `(request_id, started_at)` with a generous
   ceiling (say 10 min) would close it.

5. **macOS: the ingest picker now holds the popup lock until the editor
   closes the panel.** `popup.py:~3060-3110`. On Windows the timeout closes
   the dialog; on macOS it cannot, so after the 300 s timeout the page gets
   `[]` while the modal panel stays up holding `_popup_active_lock`: every
   fixer popup, Settings, licence and update dialog answers "A popup is
   already open" and `apply_upgrade` stands down until someone finds the
   panel. Correct (a CCSync window IS open) and better than a second root,
   but it is a new way for a Mac to look stuck. Worth a line in
   `docs/GOTCHAS.md` next to CORE-M3.

6. **`file_moves._attempt_moved_it` accepts `blocked` rows.**
   `file_moves.py:~204-223`. A `blocked` row written for "the destination
   already exists on this computer" has intent paths equal to src/dest and
   a present dest; if src later disappears (a hand delete, a later lane B
   pass following a relocation the ledger did not record), the redelivery
   answers "finished a move this computer was interrupted during" with
   paths and relinks Resolve to whatever sits at dest. In practice that is
   the file the server has at the new path, so the outcome is right; the
   row's history is not. Restricting the arm to `retryable` (the state the
   0.9.77 bug actually left) would remove the doubt at no cost.

7. **shared-folder `marker-missing` sentence asserts a cause it cannot
   see.** `shared_folders.py:185-189`: "its folder moved and the sync
   engine will not start it at the new place on its own" is also shown for
   a running Luts/Stills folder whose `.stfolder` went missing for any
   other reason (a cleanup tool, a restore). The remedy (unshare/reshare)
   is the same; only the first clause over-claims.

8. **`_pid_looks_like_companion` "ccsync" token is a case-insensitive
   substring of the whole command line.** `app.py:~470-500`. After a reboot
   a reused low pid whose command line merely mentions a path under
   `~/.ccsync` or `.../Editing/ccsync/...` reads as a companion and the
   real companion refuses to start (the fail-safe direction, and it needs
   a pid collision first). Acceptable; noting it so the next "Mac has no
   tray after reboot" report checks `ps` before assuming the fix failed.

9. **`jobs_runner` now catches every `ValueError` from `_media_paths` /
   `_whisper_command`** (`jobs_runner.py:1055,1109`) and posts it as a
   non-retryable failure with the exception text. Better than a silent
   drop, but a companion bug in either helper now retires jobs fleet-wide
   with a Python message as the admin-facing reason. Fine for now; the
   `why` route makes it visible.

10. **`ytdlp_manager` backoff counts the sidecar half while the feature is
    off.** `ytdlp_manager.py:~1283-1290`. A vendor-default site whose
    ffmpeg-pair fetch fails (the Mac certificate case) now retries at 5,
    10, then 15 min instead of 15. Harmless; noted because the docstring
    says "the loop is the only retry" for the enabled case only.

## Waved-away findings

Every NOT_A_DEFECT / ALREADY_FIXED / DEFERRED in my area was checked
against the code: bug-comp-app-4, bug-wire-4, bug-wire-7 (ytdl half),
bug-comp-media-5 (round 2), ui-onboarding-7 are genuinely already fixed;
bug-music-ytdl-2 is genuinely not a defect (the flag would remove the only
healing path); bug-comp-ui-4, bug-comp-resolve-7 and logic-plans-4 are
correctly deferred to an owner/live decision rather than guessed at. None
were waved away wrongly. The one first-round wrong call (ui-comp-windows-11
focus ring "not a defect") was caught and reversed in its review round with
a real measurement.

## Invariants checked

- No em dash in new visible text (spot-read every new sentence; the EULA
  display helpers convert U+2014; the wave's own no-em-dash scan passes).
- "Nothing ticked is fine": Settings now agrees with the tray.
- `scriptapp()` still has one caller (`resolve_bridge.connect`); the primed
  CR-68 probe is `script_server.state()` (TCP table), taken OUTSIDE
  `_API_LOCK`, never a connection.
- Sync lanes: every new sequencer unpause path goes through `_set_paused`;
  lane A never gains a delete; lane B's breaker is only ever discounted by
  what the trip-time probe already discounted; the trash prune keeps
  oldest-first / never-the-last-batch.
- File moves: nothing new deletes; a failed proxy stays put; the proxy's
  bytes are never re-spelled across an NFC/NFD-only difference.
- Deletes/trash: `remove_reserved_name` only removes an empty file; the LUT
  tmp is a fixed suffix only this code writes; `_prune` keeps the newest of
  a burst now.
- Wire: every new key is additive and optional in both directions (`arch`,
  `upgrade_none_reason`, `X-CCSync-Machine-Pct`, `attached`, lane C
  `progress_token`), every new local key is ignored by an older build
  (`editor`, `lanes`, `undone_at`, `held_bytes`, `~NN` crash names). No
  schema migration in this area. Deploy order: dashboard first is nicer
  for the verify reason; nothing breaks either way.
- Windows vs macOS branches are explicit (`escape_ignore_glob`,
  `_close_picker_dialog`, `_pid_looks_like_companion`, `safe_stem`,
  `_half_installed_loss`).
- Blocking IO on hot threads: the site refresh, diagnostics upload, picker
  and off-cycle report are all on their own threads; the one new
  subprocess (`ps`) runs once at startup on posix with a 5 s timeout; the
  lsof probe moved OFF the bridge lock.

## Should anything block the commit?

No. Nothing in `companion/`, `onboarding/` or `installer/` is NOT-FIXED or
REAL-BUT-BREAKS-X. Before committing: fix the three docstring/spacing
glitches (item 3) and name the two policy changes (item 1) in the commit
message. Before calling Windows borrowed folders done: the Syncthing spike
(item 2). Before the next Mac build: know about item 5.
