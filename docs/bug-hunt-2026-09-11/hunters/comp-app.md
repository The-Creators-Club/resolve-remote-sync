# comp-app - the companion app core (app.py, config/site/identity/machine/paths/canon/secretfile/eula/capabilities/ui_state)

Files read (with approximate coverage):
- `companion/src/ccsync_companion/app.py` - the full `097f5a3..HEAD` diff (2,547 diff lines) plus targeted full reads of the single-instance guard (l.348-670), `LaneWatchdog`/`_SupervisedThread` (l.857-1150), `_on_report_response` (l.1930-2010), `effective_mode`/P: helpers (l.4195-4460), `resolve_health` and the whole wave-3 reader block (l.4459-5060), `_start_lanes`/`_stop_lanes` (l.5601-5760), `sync_guard` (l.6114-6360), auto/pushed update (l.6955-7190), the loopback bind pair (l.8614-8700). ~55% of the file read directly, 100% of the diff.
- `site.py`, `eula.py`, `machine.py`, `canon.py`, `paths.py`, `ui_copy.py` - read in full.
- `identity.py` - l.1-400 (load/save/token/verify/IdentityManager head).
- `capabilities.py` - `build`/`_jobs_gate`/`_cards_block` region.
- Cross-checked against `dashboard/src/ccsync_dashboard/api.py` (`SyncGuardIn`, `ResolveHealthIn`, `_BoundedSectionIn`, `CapabilitiesIn`), `companion/src/ccsync_companion/settings_window.py` (sections), `tray.py` (`action_sync_now`), `watcher.py` (`missing_clips`/`non_canonical_refused`), `broll_server.py` (`start`).

Tests run:
`cd companion; .venv\Scripts\python.exe -m pytest tests/test_app.py tests/test_app_contract.py tests/test_canon.py tests/test_capabilities.py tests/test_config.py tests/test_eula.py tests/test_identity.py tests/test_machine.py tests/test_paths.py tests/test_secretfile.py tests/test_site.py -q`
-> **850 passed, 1 skipped in 47.54s** (clean baseline; none of the findings below is caught by any of them).

## Findings

### comp-app-1 - "Sync now" answers "Sync requested" on a machine whose lanes are halted, paused, unlicensed or misconfigured
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:4623` (`sync_now_result`), consumed at `companion/src/ccsync_companion/tray.py:3966` (`action_sync_now`)
- What: `_start_lanes()` (app.py:5601) has SIX refusals - tray pause, fleet/local halt, `config_problems`, the EULA gate, `_root_absent`, `sync_enabled=false`. APP-6's new `sync_now_result()` reproduces only the last of those plus an "empty tick list" check, so on the other five it returns `{"accepted": True, "lanes": [...]}`. `sync_now()` then calls `sequencer.trigger_pass_now()` on a sequencer `_start_lanes` deliberately never started, and the tray toasts "Sync requested: lane_a_video_up, lane_b_proxy_down, lane_c_syncthing".
- Failure scenario: an admin halts the fleet (or an editor is parked behind the licence gate - the exact CR-27 population APP-9 was written for). The editor clicks the most-clicked item in the menu and is told, in writing, that a sync pass is running on all three lanes. Nothing happens, ever, and the sentence that would have told them what to do (`_halt_detail()` / `eula_problem()`) is already in hand two methods away. This is the "misleading UI that causes a wrong action" the APP-6 change existed to remove, reintroduced for the states that matter most.
- Evidence: driven directly from the companion venv against a stub carrying every blocker at once:
  ```
  halted+paused+misconfigured+drive absent, lanes never started:
    {'accepted': True,
     'lanes': ['lane_a_video_up', 'lane_b_proxy_down', 'lane_c_syncthing'],
     'reason': 'Checking the server for changes now.'}
  ```
  `tray.action_sync_now` renders that as `Sync requested: lane_a_video_up, lane_b_proxy_down, lane_c_syncthing`. No test in `tests/test_app.py` exercises `sync_now_result()` with `halt.active`, `_paused`, `config_problems` or an EULA problem set.
- Ledger: new (APP-6 is recorded as fixed; this is the half it did not cover).
- Suggested fix: give `_start_lanes()` and `sync_now_result()` one shared predicate. Simplest: have `sync_now_result` return `accepted: False` with `self._halt_detail()` / `"Syncing is paused from the tray."` / `self.config_problem_detail()` / `self.eula_problem()` / `_lane_root_absent_detail()` whenever the matching gate is up, in `_start_lanes`'s own order, and pin it with a test per gate.

### comp-app-2 - nine new `resolve_health` fields are sent on every report and silently dropped by the dashboard (SYS-3 again)
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:4474-4504` (`resolve_health`) / `dashboard/src/ccsync_dashboard/api.py:7036-7053` (`ResolveHealthIn`, which inherits `_BoundedSectionIn` -> `model_config = ConfigDict(extra="ignore")`, api.py:6797)
- What: wave 3 added `connected`, `project_open`, `wedged_seconds`, `wedged_call`, `missing_clips`, `non_canonical_refused`, `proxy_attach`, `proxy_gaps` and `stills` to the wire payload. `ResolveHealthIn` declares only `out_of_tree`, `bad_prefix`, `missing`, `ignored_this_session`, `ignored_folders`, `last_scan_at`, `open_project`. Unlike `SyncGuardIn` (which is `extra="allow"` precisely so `api_report` can NAME an undeclared section), the sub-model is `extra="ignore"`, so all nine are discarded with no log line and no ignored-sections banner.
- Failure scenario: an editor's Resolve bridge is wedged, or 12 proxies were refused by Resolve, or stills needs a media-storage location added by hand. The companion computes and sends all of it every 30 s; the fleet page shows nothing, and the admin has no more than before wave 3 was written. The dashboard half now needs a schema change, but the companion half is already in the field on 0.9.66+.
- Evidence: both models read directly. `ResolveHealthIn`'s own docstring says "Declared here BEFORE the companion half ships, which is SYS-3's lesson" - and then the companion half shipped nine fields past it. `app.py:4498` even carries the comment "Not in the reported contract (the dashboard drops what it does not declare)" about `skipped_ever`, immediately below nine keys in exactly that position. Identical shape to SYNC-8 (`syncthing_supervisor`) and BROLL-ING-1.
- Ledger: new (third recurrence of SYS-3).
- Suggested fix: declare the nine fields on `ResolveHealthIn` with caps (`missing_clips`/`non_canonical_refused` as `list[...] | None` with `max_length`), or, cheaper and more durable, flip `_BoundedSectionIn` to `extra="allow"` and make `api_report`'s ignored-sections banner walk sub-models too so the next one is loud instead of invisible.

### comp-app-3 - the licence refusal sends a parked editor to the wrong section of the Settings window
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/eula.py:236,240,243` / button at `companion/src/ccsync_companion/settings_window.py:1219`
- What: all three refusal sentences say "Press [ READ AND ACCEPT THE LICENCE ] in Settings, THIS COMPUTER." The button is appended to `lane_items`, which becomes `Section(SYNCING_SECTION, ...)` (`SYNCING_SECTION = "SYNCING"`, settings_window.py:659, section built at :1350). `Section("THIS COMPUTER", computer_items)` is a different section, closed at :1196, and has no licence button. The route also bypasses `ui_copy` entirely (it spells the path as "in Settings, THIS COMPUTER" rather than "Tray > Settings > ..."), so neither `test_sweep_2026_09_04_copy.py`'s "Tray >" scan nor `test_tray_copy_names_real_menu_items.py`'s `ROUTE_ROWS` check can see it - which is the exact failure `ui_copy.py`'s docstring says the module exists to prevent.
- Failure scenario: a machine self-upgrades into a new EULA version, parks, and shows the editor a sentence pointing at a section of the window where the button is not. The population this affects is the one CR-27 showed is least able to recover on its own.
- Evidence: both files read; `grep -n 'Section("' settings_window.py` shows THIS COMPUTER closing at 1196 and the licence button added at 1219 inside `lane_items`.
- Ledger: new (APP-9 is recorded as fixed; the copy it introduced names the wrong place).
- Suggested fix: add `ACCEPT_LICENCE_SETTINGS = "Tray > Settings > READ AND ACCEPT THE LICENCE"` to `ui_copy` with its `ROUTE_ROWS` entry, and have `eula.acceptance_problem` use it (it already imports nothing, so pass the phrase in or import `ui_copy` the way `identity.py` now does).

### comp-app-4 - `non_canonical_refused` grows without bound and rides every report
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:4491` + `4544` (`_watcher_list`) / `companion/src/ccsync_companion/watcher.py:202,454,476`
- What: `watcher._non_canonical_refused` is a plain dict keyed by normalised path; `rearm_non_canonical` adds an entry for every relink Resolve refuses and only `clear_non_canonical_refusal` (a SUCCESS) ever removes one. There is no cap on the dict, none in `watcher.non_canonical_refused()`, and none in `app._watcher_list()` - unlike its sibling `missing_clips`, which is capped at `MAX_MISSING_REPORTED = 50`, and unlike every other list in `sync_guard` (`moved_project_dirs[:20]`, `folders_unfiltered[:20]`, `repath_events[:10]`, `removal_overrides[-5:]`).
- Failure scenario: a project in the 2026-08-12 "Energy Transition" shape (200+ non-canonical clips) on a machine where Resolve refuses the relinks (project open read-only, clips locked). Every refusal is retried and re-recorded, the dict reaches the size of the media pool, and each 30 s report (and each 5 s light tick, since `sync_guard` is rebuilt per tick) serialises `{"name","path"}` for all of them - entirely wasted, since the dashboard drops the key (comp-app-2).
- Evidence: `watcher.py:454` `return [dict(entry) for entry in self._non_canonical_refused.values()]` with no slice; `app.py:4544` `return list(getter() or [])` with no slice; `watcher.py:40` shows the sibling cap.
- Ledger: new.
- Suggested fix: cap at the source (`MAX_MISSING_REPORTED`-sized, evicting oldest) and slice in `_watcher_list` as well, the way every other reported list already does.

### comp-app-5 - an unreadable `machine.json` mints a NEW machine id and overwrites the old one
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/machine.py:68-107`
- What: `read()` returns `None` for **any** exception, not just `FileNotFoundError` - a truncated/0-byte file, a BOM-mangled write, a `PermissionError` from a scanner holding the handle. `machine_id()` treats that `None` as "no id yet" and mints a fresh UUID4, writing it over the file. The module docstring's own rule is "never a value that was not persisted: an id that changes every run is worse than none, because the dashboard would read each one as another new computer" - but the code cannot tell "absent" from "unreadable".
- Failure scenario: `machine.json` is corrupted (a hard power loss between `write_text` and `replace` on the very first mint, an antivirus quarantine, an editor's backup tool restoring a partial file). The companion mints a second id; the dashboard's `machines` registry (schema v23) sees a known hostname carrying an unknown `machine_id` and loses the rename affordance that id exists for. Silent: the only trace is one `log.warning` in a rotating log.
- Evidence: `machine.py:74-76` `except Exception: log.warning(...); return None`, then :86-92 mints unconditionally when `create=True`. `tests/test_machine.py` passes but has no corrupt-file case (the suite is green either way).
- Ledger: new.
- Suggested fix: have `read()` distinguish "not there" from "could not read", and make `machine_id()` return `""` (report no id, do not overwrite) on the second - a machine with no id syncs fine, a machine with a NEW id looks like a different computer.

### comp-app-6 - the loopback rebind re-runs the whole server start every 120 s and logs a six-line WARNING each time
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:4131-4140` (`_media_tree_loop`), `app.py:8691` (`retry_loopback_bind`) / `companion/src/ccsync_companion/broll_server.py:2185-2229`
- What: `retry_loopback_bind()`'s docstring says "Cheap: one bind attempt a minute". It is not one bind attempt: `broll_server.start()` re-reads `load_config()`, runs `resolve_music_mounts` / `resolve_ytdl_mounts` / `resolve_mounts` (which probe `VOLUMES_DIR` on macOS), and on the `OSError` arm emits a six-line `log.warning` naming the retired standalone companion. `media_tree_refresh_interval` defaults to 120 s (config.py:388), so a machine whose 8899 is genuinely held by another program writes ~720 of those warnings a day into a 5 MB rotating log.
- Failure scenario: an editor who never uninstalled the old standalone BRoll Companion. The retry never succeeds, and the log the support workflow depends on ("Tray > Settings > COPY DIAGNOSTICS FOR YOUR ADMIN", `OPEN LOG`) rotates away the real evidence of whatever else went wrong that day, replaced by 4,000 lines of the same paragraph.
- Evidence: `broll_server.start` read in full - the `except OSError` arm is a `log.warning` with no once-per-process latch, and `_LAST_BIND_ERROR` is already the state that could gate it. CMEDIA-3's own report field (`loopback.error`, `loopback.since`) is the surface that makes the repeated log unnecessary.
- Ledger: new.
- Suggested fix: log the paragraph at WARNING on the first failure and at DEBUG thereafter while `last_bind_error()` is unchanged (the state is already tracked), and skip the mount re-resolution on a retry by hoisting the bind ahead of it.

### comp-app-7 - `LaneWatchdog` restarts a thread with no ceiling and no backoff
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:938-961` (`check`) and `1051-1072` (`_restart`/`_record`)
- What: `check()` consults only `_must_not_restart()` (shutdown, or work in flight). `_events`/`_last_error` are written for the `sync_guard.restarts` report and are never read back as a policy input, so a thread whose `restart()` fails or whose loop dies again immediately is restarted every `LANE_WATCHDOG_INTERVAL_SECONDS`, for ever, with no growing wait and no "this has failed N times, stop trying" ceiling. `_WATCHDOG_EVENTS_KEPT` bounds the *record*, not the behaviour.
- Failure scenario: a sequencer that raises inside `start()` on a machine with a broken config (or a watcher whose `poll_once` dies on a wedged fusionscript call). The watchdog spins the restart forever; the only sign is the `count_24h` climbing on a report field, and the state file is rewritten on every single restart (`_record` -> `_write_record`, one JSON write per tick).
- Evidence: read in full; `self._events` appears only in `_record`, `report`, `_write_record`, `_load_record` - never in `check` or `_must_not_restart`. `_load_record` also drops any event whose `now - t` is `<= 0`, so a clock that steps backwards erases the crash-loop evidence the comment at :907-910 says must survive a restart.
- Ledger: new (related to SYS-2).
- Suggested fix: add a per-thread ceiling read from `_events` (e.g. refuse and say so once after N restarts in an hour, which is already computed as `count_1h`), and an exponential wait between attempts; relax `_load_record`'s `0 < now - t` to a symmetric skew tolerance.

## Coverage note
Not reached: `config.py`'s 2,385 lines beyond `VERSION`/`coerce_numeric`/`MODE_PROFILES` spot checks (its diff since 097f5a3 is one line, the version bump, so I prioritised elsewhere); the second half of `identity.py` (`IdentityManager` sign-in/sign-out body past l.400); `secretfile.py` and `ui_state.py` (read, nothing found, both tiny and unchanged); the `_apply_file_moves` / `_apply_resolve_undo` / `_apply_diagnostics_request` command handlers were skimmed for exception containment only, not traced against their dashboard senders. I did not exercise the Windows single-instance path on a real process pair - `_pid_is_alive_win32`'s new `WaitForSingleObject` arm and the 15 s release grace were read and reasoned about but not measured.

What the suite does not cover: `sync_now_result()` under any blocker other than `sync_enabled=false` and an empty tick list; any corrupt-file case for `machine.json`; the `resolve_health` wire shape against the dashboard model (there is no companion test that asserts the dashboard declares what the companion sends, and that is now three separate incidents); the loopback retry's log volume; and `LaneWatchdog` restart-loop behaviour over more than one tick.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/api.py:7036` `ResolveHealthIn` - the receiving half of comp-app-2; `_BoundedSectionIn`'s `extra="ignore"` (api.py:6797) means any future sub-section field is lost the same silent way.
- `companion/src/ccsync_companion/watcher.py:202` `_non_canonical_refused` - the unbounded dict behind comp-app-4.
- `companion/src/ccsync_companion/broll_server.py:2219` - the un-latched WARNING behind comp-app-6.
- `companion/src/ccsync_companion/identity.py:296` - the one-time plaintext warning still says "your TrueNAS username and password", the exact phrasing `site.server_phrase()` was added to retire. Log line only, so not user-visible copy, but it is the same vendor-name leak.
