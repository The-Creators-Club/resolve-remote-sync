# comp-app - the companion's process core: app.py, config/site/identity/machine/paths, reporter, idle, supervisor, upgrade, ed25519

Files read (with approximate coverage):
- `companion/src/ccsync_companion/app.py` - the whole uncommitted diff (401 changed
  lines) hunk by hunk, plus the surrounding code of every hunk: `LaneWatchdog`
  (lines 900-1260), the new module helpers (1317-1400), `_refresh_media_tree_once` /
  `_relink_proxies_once` / `_media_tree_loop` (4277-4720), `resolve_health` +
  `standins_owed` (5060-5230), the `sync_guard` block (6900-6930),
  `_lane_stall_fallback` (7419), `_apply_file_moves` (8035-8200),
  `_start/_abandon/_target media tree` (9480-9520), `run()` (11180-11260). ~60% of the
  file read, 100% of the diff.
- `companion/src/ccsync_companion/supervisor.py` - `read_history` / `write_history` /
  `merge_history` / `decide` (diff plus callers), 100% of the diff.
- `companion/src/ccsync_companion/upgrade.py` - `note_report_response`,
  `_clear_refusal`, `refusal()`, `parse_version`, `compare_to_running`. 100% of the diff.
- `companion/src/ccsync_companion/config.py` - the VERSION bump only.
- Both sides of every wire the diff touches (read, not reported on):
  `dashboard/src/ccsync_dashboard/api.py` (`_upgrade_info`, the report reply block,
  `FileMoveResultIn`, `ResolveHealthIn`, `StandinsOwedIn`, `StandinsPlacedIn`),
  `companion/.../file_moves.py` (`_dest_is_synced_here`, `apply_move`),
  `sync/sequencer.py` (`rel_to_slug_with_borrowed`, `borrowed_lenders`,
  `_build_borrowed`, `_include_is_valid`), `sync/rclone_lane.py:_local_destination`,
  `proxy_relink.py` (`plan_relinks` signature, `header_frame_estimate`,
  `note_fleet_standins`), `broll_standins.py` (`set_upgrade`, `given_up_upgrades`,
  `placed_report`), `broll_server.py` (the upgrade worker), `sidecar_tools.ensure_ca_bundle`,
  `settings_window.py:action_repair_machine_id`.
- `docs/bug-hunt-2026-09-18/ledger/companion-core.md` (CR-283A..Y, the OWED section)
  and the dashboard ledger's CR-285Q.

Tests run:
- `companion\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_18_companion_core.py tests/test_file_moves.py -q` -> 66 passed
- two ad-hoc snippets from `companion/.venv` (below, in the evidence of comp-app-1 and comp-app-2)

## Findings

### comp-app-1 - the remembered dashboard version is never forgotten, so a dashboard rollback 422s every report from that machine for ever
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:1331-1346` (`_note_dashboard_version`),
  used at `app.py:8095` and `app.py:8173`; other side
  `dashboard/src/ccsync_dashboard/api.py:8796-8802` (`FileMoveResultIn.state`, a `Literal`)
- What: `_note_dashboard_version` only WRITES `app._dashboard_version` when the reply
  carries the key; an absent key leaves the previously remembered value in place. Its
  own docstring states the opposite contract ("an ABSENT `dashboard_version` means a
  dashboard older than the one that started sending it, which is the safe reading"),
  and the whole `not_synced_here` gate rests on that reading. The value lives for the
  life of the companion process (days), so once a companion has seen 0.7.50 it will
  keep putting the new state word on the wire against any dashboard, including one
  that has been rolled back.
- Failure scenario: 0.7.50 is deployed; a companion on 0.9.75 gets one report reply
  carrying `dashboard_version: "0.7.50"` alongside a `file_moves` command. The deploy
  is then rolled back - a documented, scripted operation
  (`docs/RELEASE.md:114-124`, `install_dashboard_app.py --rollback-on-unhealthy`, the
  `mv <root>/app.old.<ts> <root>/app` one-liner) - so the answering dashboard is 0.7.49
  again and sends no `dashboard_version` at all (verified: `git show
  HEAD:dashboard/src/ccsync_dashboard/api.py` has the key only in the packages block,
  never on the report reply). `_dashboard_knows_state_word` still answers True, the
  redelivered section-4b move is answered with `state: "not_synced_here"`, and 0.7.49's
  `FileMoveResultIn.state` Literal rejects it: **422 for the WHOLE report** - lanes,
  presence, alarms, jobs - every 30 s. Nothing recovers: the companion has no 422
  shedding path (`grep -n 422 companion/src/.../reporter.py` -> nothing), the dashboard
  never records the answer so it redelivers the command for ever, and the machine reads
  as silent on the fleet grid until somebody restarts the tray. This is precisely the
  failure res-fleet-3 was written to prevent, reached from the one direction the fix
  did not model.
- Evidence:
  ```
  $ companion/.venv/Scripts/python.exe -c "...":
  note 0.7.50 ->  0.7.50
  knows? True
  note old reply (no key) -> '0.7.50'
  knows after rollback? True
  ```
  The regression test cannot see it: `companion/tests/test_file_moves.py:245-256`
  iterates `{"dashboard_version": "0.7.49"}`, `{}` and `{"dashboard_version":
  "nightly"}` but builds a FRESH `_Stub()` for each, so the `{}` case only proves a
  companion that has never been told. `test_the_ledger_keeps_the_word_even_when_the_wire_cannot`
  (line 271) exercises the UPGRADE direction on one stub and nothing exercises the
  downgrade direction.
- Ledger: new (CR-283/res-fleet-3 does not fix the downgrade direction of its own gate)
- Suggested fix: make the absent key clear the memory, as the docstring says -
  `app._dashboard_version = version` on a value, `app._dashboard_version = ""` when
  `resp` is a dict with no `dashboard_version`; add the rollback case to
  `test_file_moves.py` (one stub, 0.7.50 then a reply with no key, assert
  `state is None`).

### comp-app-2 - CR-283D moved the editing-proxy resume out of the relink flag but left it behind `get_media_pool_items()`, so a closed or ignored Resolve still strands a stand-in at `pending`
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:4329-4339` (the new call site, inside
  `_refresh_media_tree_once`, below its two early returns at 4288 and 4303)
- What: the fix's own comment and `ledger/companion-core.md:64-77` justify the move
  with "the resume needs no Resolve connection at all
  (`broll_server.resume_pending_upgrades` ... so nothing is lost by moving it out)".
  The new call site is still the tail of `_refresh_media_tree_once`, which returns
  early when `resolve_bridge.get_media_pool_items()` answers `ok: False` (Resolve
  closed, scripting dead, bridge wedged) and again when the open project is in
  `ignored_resolve_projects`. Only the `proxy_relink_enabled` half of the reported
  defect is closed; the Resolve-connection half the ledger claims is not.
- Failure scenario: an editor inserts an archive clip, gets a stand-in, and the
  companion restarts (an upgrade, a crash, a reboot) before the editing proxy has
  landed. They do not reopen Resolve that day, or they reopen a project listed in
  `ignored_resolve_projects`. `resume_pending_upgrades` is never called, so the
  ledger row stays `pending`, the download is never resumed, and the attempt budget
  is never spent either - the clip silently keeps the 1080p H.264 preview under the
  6K name. `_resume_broll_proxy_upgrades`'s own docstring ("a Resolve that was closed
  when the download landed, leaves the row `pending` -- which is the whole reason the
  state is on disk") describes exactly the case the call site cannot reach.
- Evidence: snippet from `companion/.venv`, driving the real
  `_refresh_media_tree_once` with `get_media_pool_items` stubbed to
  `{"ok": False, "reason": "resolve is closed"}` ->
  `resume calls with Resolve closed: []`. The new regression test
  (`tests/test_bug_hunt_2026_09_18_companion_core.py:512-560`) stubs
  `get_media_pool_items` to `{"ok": True, ...}`, i.e. it mocks away the gate that is
  still there - the brief's "pins the NEW behaviour without proving the old bug is
  gone" shape.
- Ledger: CR-283D does not fix comp-app-1 (2026-09-18) in full
- Suggested fix: call `self._resume_broll_proxy_upgrades()` from `_media_tree_loop`
  next to `retry_loopback_bind()` (which already runs every 120 s regardless of
  Resolve), not from inside `_refresh_media_tree_once`; add a test that drives the
  loop with `ok: False`.

### comp-app-3 - the retired media-tree thread is only checked at the loop boundary, so it finishes the whole wedged pass beside its replacement and keeps stamping the shared heartbeat
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:4704-4717` (the generation checks),
  `app.py:4674-4681` (`_stamp_media_tree_heartbeat`), `app.py:9498-9509`
  (`_abandon_media_tree_thread`), `app.py:1049-1056` (the watchdog's abandon call)
- What: `_abandon_media_tree_thread` only bumps a counter; the retired thread tests it
  at the TOP of the loop and after the pass returns, so between abandonment and the
  replacement's first pass there are two live media-tree threads. The wedge the fix
  exists for is by construction inside that pass (an ffprobe over a share that stopped
  answering), which is why the thread was declared wedged after 30 minutes in the
  first place - so the overlap is not a moment, it is however long the hang lasts, and
  during it both threads walk the media pool and both call `apply_relinks` into the
  same Resolve project. That is the exact harm res-companion-4's own comment names
  ("two walkers of the same media pool, two callers of apply_relinks into one Resolve
  project"); the fix bounds it to one pass rather than removing it. Worse, the retired
  thread keeps calling `on_probe=self._stamp_media_tree_heartbeat` for every clip it
  probes, and that stamps the single shared `self._media_tree_heartbeat`, so while the
  zombie is alive the watchdog cannot see the REPLACEMENT wedging either.
- Failure scenario: the SMB share stops answering mid-probe. The watchdog retires the
  thread at t+30 min and starts a second one. The old thread is still blocked in
  ffprobe (or grinds through hundreds of remaining clips over a slow share); both
  threads reach `_relink_proxies_once` and issue `replace_clip` / `link_proxy_media`
  into one Resolve project, and the second thread's own silence is masked by the
  first's probe stamps.
- Evidence: read of `_media_tree_loop` - the only two `generation != ...` tests are
  before `_refresh_media_tree_once()` (line 4704) and after it (4714); there is no
  check inside `_refresh_media_tree_once`, and `on_probe` is called from inside the
  wedged pass. `_stamp_media_tree_heartbeat` writes the same attribute
  `LaneWatchdog._media_tree_target` reads via `self._silence(app,
  "_media_tree_heartbeat")` (app.py:1178).
- Ledger: new (CR-283T/res-companion-4 leaves a neighbour open)
- Suggested fix: hand the generation to the pass - have `on_probe` (and a check at the
  top of `_relink_proxies_once` / before each `apply_relinks` batch) raise or return
  when `generation != self._media_tree_generation`; and stamp a PER-THREAD heartbeat
  (`self._media_tree_heartbeat` written only when the caller is the current
  generation) so a retired thread cannot vouch for its replacement.

### comp-app-4 - CR-283F leaves a standing upgrade refusal that nothing can ever clear once the build it names is retracted
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/upgrade.py:1559-1592` (the added
  `and not resp.get("upgrade_none_reason")`); other side
  `dashboard/src/ccsync_dashboard/api.py:5804-5808`
- What: the companion has exactly three ways out of `last_refusal`: an offer that
  passes `_check_offer` (upgrade.py:1406), `refusal()` self-retiring when the machine
  is RUNNING that same version (1531), and the "no `upgrade` key" clear this fix has
  just narrowed. `_upgrade_info` appends `'that build was recalled by the vendor'` to
  `withheld` when the current package is retracted, so a retracted build now blocks
  the third way out as well. A retracted build is never offered again and is not the
  version the machine runs, so none of the three can fire: the refusal is permanent.
- Failure scenario: a machine refuses 0.9.76 (signature, `min_version` floor,
  free-space check - any `_check_offer` refusal). The admin sees it, agrees, and
  RETRACTS 0.9.76. From that report onward every reply carries
  `upgrade_none_reason` and no `upgrade`, so the machine keeps its
  `[ REFUSING 0.9.76 ]` chip and keeps firing the `upgrade_refused` alert for a build
  that no longer exists, with no way to clear it but restarting the companion. That is
  exactly the "alarm that cries wolf" `refusal()`'s docstring exists to avoid.
- Evidence: read of the three clear paths (upgrade.py:1406, 1531, 1592) against
  `api._upgrade_info`'s four `withheld.append` sites; `retracted_at` is checked
  before everything else (api.py:5804) so the reason is emitted for the CURRENT
  package whatever the refusal was about.
- Ledger: CR-283F opens a neighbour of CR-283F (related to REL-3)
- Suggested fix: keep the refusal only for reasons that can change back for THIS
  machine; clear it on the retracted reason (or, more precisely, gate the clear on the
  refusal's own version - if `upgrade_none_reason` is present and the standing refusal
  names a version the dashboard is no longer carrying as current, clear it). Simplest
  correct shape: have the dashboard send the withheld VERSION beside the reason and
  clear the refusal when it no longer matches.

### comp-app-5 - the watchdog's "alive but silent" hold-off is logged once per process, not once per episode
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:1041-1056`
- What: `self._held_logged[target.name] = "alive"` is only ever removed in the branch
  that actually restarts (line 1057, `self._held_logged.pop`). A thread that goes
  silent, is reported once, then RECOVERS and goes silent again weeks later gets only
  a `log.debug`, because the dict still says `"alive"`. comp-app-5's own stated rule
  is "once per CHANGE of answer, and the transition into the hold-off is the line that
  matters"; a recovery is a change of answer and is not recorded.
- Failure scenario: leso's sequencer is silent for an hour during a 32 GB upload,
  earns its one WARNING, recovers. A month later it genuinely wedges; the only
  evidence in the log is a DEBUG line that the shipped log level does not emit, and
  nothing is reported to the fleet either (the fix deliberately stopped recording the
  event). The wedge is invisible on both surfaces.
- Evidence: read of `check()` - the `else: continue` at line 1006 (target healthy)
  never touches `_held_logged`.
- Ledger: new (related to CR-283T)
- Suggested fix: clear `self._held_logged.pop(target.name, None)` in the healthy
  `else: continue` branch at the top of the loop.

### comp-app-6 - `standins_owed.why` forwards a raw exception string to the dashboard, and it can carry a local absolute path
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/app.py:5204-5224` (`standins_owed`),
  sourced from `broll_standins.set_upgrade(..., str(exc))` at
  `companion/src/ccsync_companion/broll_server.py:1380-1381` and the rclone failure
  message at 1403-1404
- What: the new health key ships `entry["upgrade_note"][:300]` to the dashboard, and
  one of the notes is `str(exc)` for `PathTraversalError` / `MountNotConfiguredError`
  and another is the fetch layer's failure message. Both can contain a local absolute
  path (a drive letter, a mount point, a share name), which the neighbouring
  `standins_placed` block is careful to exclude ("never an absolute path ... the vault
  is a drive letter here, a container mount there"). The string is then rendered on a
  dashboard page for every admin.
- Failure scenario: a misconfigured mount makes `contained_local_path` raise; the
  editor's `E:\Media\...` (or their username, if the share is a home path) is recorded
  as `upgrade_note`, reported in `resolve_health.standins_owed.why` and shown on the
  fleet page.
- Evidence: read of the three `set_upgrade(..., <message>)` call sites; two of the
  four messages are fixed sentences, two are not.
- Ledger: new (related to CR-283X)
- Suggested fix: send the sentence for the fixed cases and a generic
  "the editing proxy could not be downloaded" for the exception cases, or strip
  anything that looks like a path before it leaves the machine.

## Coverage note

- The diff over my territory is small (4 files); the rest of the time went on the
  two-sided wires it opens. I did NOT re-read the unchanged bulk of `app.py` (it is
  ~11,000 lines), nor `site.py`, `identity.py`, `paths.py`, `canon.py`,
  `secretfile.py`, `eula.py`, `capabilities.py`, `ui_state.py`, `ui_copy.py`,
  `idle.py`, `shutdown_guard.py`, `theme.py`, `release_pubkey.py` or `ed25519.py` -
  none of them is touched by today's pass, and nothing in the diff calls into them in
  a new way except `theme.claim_app_identity` (unchanged order) and
  `machine.machine_id_unreadable` (copy only).
- I did not exercise the `ed25519` / `release_pubkey` verification path at all.
- The suite does not cover: a dashboard DOWNGRADE against a running companion
  (comp-app-1); `_refresh_media_tree_once` with `ok: False` (comp-app-2); two
  media-tree generations overlapping inside one pass (comp-app-3 - the new tests
  drive `_media_tree_loop` with no pass in flight); `upgrade_none_reason` for a
  retracted build against a standing refusal (comp-app-4).
- `ensure_ca_bundle()` (CR-280) is called from `run()` early enough to precede every
  HTTPS fetch in this process and is inherited by children; `ca_bundle_path()`
  validates existence, and on Windows `load_default_certs()` still loads the system
  store, so I found no regression there. It remains unverified on a Mac, as its own
  comment says.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/sync/rclone_lane.py:4210-4212`: `try: fn(slug, rel) except TypeError: fn(slug)` cannot tell an arity mismatch from a `TypeError` raised INSIDE `_project_rel_for_slug`, and would then call it a second time with the borrowed lookup silently disabled (comp-sync).
- `companion/src/ccsync_companion/broll_server.py:668-683`: `_standins_owed()` returns a LIST under the same key name (`standins_owed`) that `app.resolve_health()` publishes as a DICT; two shapes for one word will bite the next reader (comp-broll-tiers).
