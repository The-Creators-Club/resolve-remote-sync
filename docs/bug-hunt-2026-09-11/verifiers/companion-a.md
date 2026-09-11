# verdicts - companion-a

Verified at git HEAD 40f931a (companion 0.9.70, dashboard 0.7.42). Read-only
on the repo; snippets run from `companion/.venv` and `dashboard/.venv`, no
live Resolve, no real Tk root.

## comp-app-1
- Verdict: CONFIRMED
- Reasoning: `sync_now_result()` (app.py:4623-4652) tests exactly two things -
  `self._sync_enabled` and, in managed mode, an empty tick list. `_start_lanes()`
  (app.py:5601-5665) refuses on SIX conditions in this order: `self._paused`,
  `self.halt.active`, `self.config_problems`, `self.eula_problem()`,
  `self._root_absent`, `not self._sync_enabled`. Five of the six are invisible to
  the verdict function, so on a halted / paused / misconfigured / EULA-parked /
  drive-absent machine the verdict is `{"accepted": True, ...}` and
  `sync_now()` (app.py:8276-8294) goes on to call `sequencer.trigger_pass_now()`
  on a sequencer `_start_lanes` deliberately never started. I could not refute
  it: there is no guard between them and the menu item is unconditional.
- Evidence: `tray.py:4543` adds `MenuItem("Sync now", on_sync_now)` with no
  gate on halt/pause, and `action_sync_now` (tray.py:3966-3989) renders
  `accepted` as `Sync requested: <lanes>` with no further check.
  `grep -rn sync_now_result companion/` finds it in exactly two places in `src`
  and once in `tests/` - `test_app_contract.py:60`, a NAME-only contract list.
  No test calls it with `halt.active`, `_paused`, `config_problems` or an EULA
  problem set, so the suite is green either way.
- Fix note: the hunter's fix is right and is the cheap one - have
  `sync_now_result` ask the same six questions in `_start_lanes`'s own order and
  return `accepted: False` with the sentence each gate already owns
  (`_halt_detail()`, `config_problem_detail()`, `eula_problem()`,
  `_lane_root_absent_detail()`). Better still, extract one
  `_lanes_refusal() -> Optional[str]` that BOTH call, so the next gate added to
  `_start_lanes` cannot miss this door again. Only `app.py` needs to change;
  `tray.py`/`settings_window.py` already render whatever `reason` says. Add a
  test per gate to `companion/tests/test_app.py`; nothing pins the current
  (wrong) answer, so nothing breaks.

## comp-app-2
- Verdict: CONFIRMED (both sides checked)
- Reasoning: companion side - `app.resolve_health()` (app.py:4474-4504) puts
  `connected`, `project_open`, `wedged_seconds`, `wedged_call`, `missing_clips`,
  `non_canonical_refused`, `proxy_attach`, `proxy_gaps` and `stills` on the wire.
  Dashboard side - `ResolveHealthIn` (api.py:7036-7053) declares only
  `out_of_tree`, `bad_prefix`, `missing`, `ignored_this_session`,
  `ignored_folders`, `last_scan_at`, `open_project`, and inherits
  `_BoundedSectionIn`'s `model_config = ConfigDict(extra="ignore")` (api.py:6797).
  I checked the two escape hatches the hunter did not: (1) nothing reads the raw
  body - `db.store_resolve_health` is fed `flatten_sync_guard(payload.sync_guard,
  ...)`, i.e. the PARSED model (api.py:8579), so the keys are gone before storage
  is reached; (2) the ignored-sections banner cannot see it -
  `undeclared_report_sections` (api.py:8098-8110) walks `payload.model_extra` and
  `payload.sync_guard.model_extra` only, one level, and a sub-model with
  `extra="ignore"` has an empty `model_extra` anyway. So the loss is silent in
  both the log and the banner.
- Evidence: parsed through the real model in the dashboard venv:
  `ResolveHealthIn.model_validate({'out_of_tree':1,'connected':True,
  'wedged_seconds':12,'missing_clips':[...],'proxy_attach':{...},'stills':{...}})`
  -> `{'out_of_tree': 1, 'bad_prefix': None, 'missing': None,
  'ignored_this_session': None, 'ignored_folders': None, 'last_scan_at': None,
  'open_project': None}`. All six wave-3 keys dropped, no error, no warning.
  `grep -an ResolveHealthIn KNOWN_BUGS.md` -> one hit (16321, the CR-232 entry),
  which notes in passing that even the DECLARED `open_project` is "accepted from
  the guard section too and stored nowhere" - so declaring a field is necessary
  but not sufficient here.
- Fix note: declaring the nine on `ResolveHealthIn` is correct but is only half
  the wire: `db.store_resolve_health` (db.py:6316) writes a fixed column list, so
  anything meant to reach the grid also needs a schema step (v49+) and a renderer,
  and `flatten_sync_guard` must carry the new keys. The cheaper half of the
  hunter's suggestion - flip `_BoundedSectionIn` to `extra="allow"` and teach
  `undeclared_report_sections` to walk sub-models - is the durable one and is
  worth doing on its own even if the nine fields are not wanted: it turns the
  FOURTH recurrence of SYS-3 into a log line. Watch that flipping `extra="allow"`
  changes every subclass of `_ReportSectionIn` too (proxy coverage, cards agent,
  jobs gate), and that `_bound_to_field_caps` does not bound undeclared keys -
  the request-size limit is then the only ceiling.

## comp-ui-1
- Verdict: CONFIRMED
- Reasoning: `_WindowsIcon.run` (tray_native.py:825-843) catches a failed
  `_create_window`/`_add_icon`, logs once, sets `self._stopped` and returns.
  `start_tray`'s Windows arm (tray.py:4750-4753) is `Thread(target=icon.run,
  daemon=True).start(); return icon` - it neither waits nor reads `_running`, and
  `app.run()` logs "tray icon started" unconditionally on the next line
  (app.py:9963-9964). `notify()` (tray_native.py:869-877) is `if not self._added:
  return`, and `_notify_tray` (app.py:3032-3040) only logs on an EXCEPTION, of
  which there is none. So every toast after a failed registration - including the
  breaker, halt, free-space and drive-pulled latches - is discarded in silence,
  permanently: `_add_icon` raises only after `_NIM_ADD_RETRIES` (6) attempts, and
  with `run()` returned there is no pump left to receive the `TaskbarCreated`
  re-add. I could not refute it; the macOS half has the check
  (`_schedule_icon_placement_check`, tray.py:4747), Windows has none.
- Evidence: `grep -n "_stopped" tray.py app.py` -> no reader outside
  `tray_native.py`. `grep -an "NIM_ADD\|tray icon could not be created"
  KNOWN_BUGS.md` -> nothing; not in the ledger.
- Fix note: the suggested fix is right in shape. Smallest correct version:
  `start_tray` waits on `icon._running` the way `run_detached` already does
  (5 s), and on timeout logs at ERROR and takes the macOS route (a `notices`/
  crash-report entry). Setting `_ccsync_stop` on the failure path is worth doing
  too but is only the spinning-loops half - it does not make the failure visible.
  Files a fix touches: `tray_native.py` (record the failure on the instance),
  `tray.py:start_tray`, `app.py:9963` (stop logging success unconditionally), and
  ideally `app.py:_notify_tray` for the dropped-toast fallback.
  `companion/tests/test_tray_native_main_thread.py` and `test_tray.py` are the
  suites to extend; neither pins the current behaviour, so nothing breaks.

## comp-ui-2
- Verdict: DOWNGRADED to low (and it is the SAME defect as res-companion-4 - see
  there)
- Reasoning: the mechanism is exactly as reported and I confirm it -
  `read_history` returns `[]` on any exception (supervisor.py:167-172),
  `write_history` swallows any exception (:175-181), and `decide`'s cap is
  computed only from that list (:138-142), so an empty history relaunches for
  ever. What refutes the SEVERITY is the second gate, which the hunter did not
  weigh: `decide` stands down at :127-130 when the run marker does not name the
  supervised pid, and the marker lives in `crash_dir(cfg)` =
  `resolved_log_path(cfg).parent / "crashes"` (crash_report.py:106-119) while the
  history lives in `resolved_log_path(cfg).parent / "state"` - SIBLING directories
  under the same parent. The headline scenario (disk full, unwritable `~/.ccsync`)
  therefore breaks `write_run_marker` (crash_report.py:481-496, which also
  swallows) at the same moment: the relaunched companion cannot refresh the
  marker, the next supervisor reads a marker naming a dead pid, and the chain
  stops after ONE relaunch, not "for ever". An unbounded loop needs an ASYMMETRIC
  filesystem condition - the marker writable, `state/supervisor.json` not (a
  per-file AV lock or ACL, `supervisor.json` existing as a directory) - which is
  real but narrow. The clock half is file-independent and stands: `0 <= now - t`
  in `decide` means a backwards NTP/resume step forgives every recent relaunch.
- Evidence: `decide()` read in full - the `marker_pid != supervised_pid` refusal
  is evaluated BEFORE the history cap. `crash_report.crash_dir` and
  `config_mod.resolved_log_path(cfg).parent / "state"` (crash_report.py:679)
  confirm the shared parent. The hunter's own repro (empty history -> `relaunch`
  True six times) reproduces from the code without running it.
- Fix note: "stand down when the history cannot be written" is the right
  instinct but must NOT be implemented as "stand down when the state dir is
  unwritable" alone - that would also stand down on the read-only-profile case
  where a relaunch is exactly what is wanted, and the supervisor is the last net
  there is. The durable fix is the one the hunter lists second: pass the previous
  attempt count on the child's command line (`supervisor.spawn_for` /
  `crash_report.start_supervisor` already build that argv), so the ceiling
  survives without the file; plus a monotonic-safe skew tolerance in `decide`.
  Files: `supervisor.py`, `crash_report.start_supervisor` (argv), and
  `companion/tests/test_supervisor.py`, which pins the verdict matrix and the
  loop cap and WILL need its `decide(...)` signature updated.

## comp-resolve-1
- Verdict: DOWNGRADED to low
- Reasoning: the code fact is exactly as reported and I reproduced it - the
  halving at fixer.py:697-699 is the only writer of `read_size` after
  initialisation, so it is monotonically non-increasing for the life of a file
  and one transient stall penalises every remaining byte. What does not survive
  scrutiny is the medium rating. Reaching the 64 KB floor needs FOUR reads each
  over `POLL_MAX_SECONDS` (0.5 s), i.e. four reads at under ~1 MB/s - a link that
  is genuinely that slow is not bottlenecked by the read size. The hunter's own
  evidence shows the realistic cloud-placeholder case settling at 512 KB, not
  64 KB (one slow read, one halving), and 512 KB vs 1 MB is one extra syscall per
  megabyte. Separately, the code comment at :695-697 states that the shrink exists
  "so the cancel the editor already pressed is honoured, not so the copy goes
  faster" - responsiveness is the declared goal, and the smaller read serves it.
- Evidence: reproduced in the companion venv against the real
  `copy_with_progress` with an instrumented reader and an injected clock in which
  only read #1 exceeds the budget: `first 8: [1048576, 524288, 524288, 524288,
  524288, 524288, 524288, 524288]`, `last 3: [524288, 524288, 524288]`. Never
  recovers. Constants read: `POLL_CHUNK_BYTES = 1 MB`, `POLL_MAX_SECONDS = 0.5`,
  `MIN_CHUNK_BYTES = 64 KB` (fixer.py:526-528).
- Fix note: the suggested grow-back is right and cheap, but the doubling must be
  capped at `min(POLL_CHUNK_BYTES, chunk_size)` AND must not undo the
  responsiveness property - grow only after several consecutive fast reads, never
  after one, or a marginal link oscillates. Nothing needs to change outside
  `fixer.py`; nothing in `companion/tests` references `POLL_MAX_SECONDS`,
  `MIN_CHUNK_BYTES` or the `clock` seam, so there is no test to break and a new
  one should be added with the fix. The hunter's side note is also correct and
  worth carrying: `KNOWN_BUGS.md:12566-12570` says `chunk_size` "stays the unit of
  PROGRESS reporting", while the code reports once per READ and its own comment
  (fixer.py:686-692) says so - ledger text, not code.

## comp-resolve-2
- Verdict: CONFIRMED
- Reasoning: `fixer.fix_clip`'s rehearsal arm returns `{"ok": True, "dry_run":
  True, ...}` since RES-15 (fixer.py:1267-1289) and its docstring names
  `dry_run` as "what a caller counting successes must look at".
  `consolidate.run_consolidation` never looks: `grep -n dry_run consolidate.py`
  finds only the rclone `--dry-run` helpers, and the two counting sites are
  `if outcome.get("ok"): batch_done += size` (:467-468) and `copied = sum(1 for r
  in results if r.get("ok"))` (:493), published as `fixed=copied`. `app.py`'s
  consolidate toast (:3561-3589) computes `len(results) - len(failures) -
  len(skipped)` from the same flag and ends on "Copy & upload finished." This is
  the UI-5 twin-miss shape, and the comment ABOUT that miss sits four lines below
  the defect (consolidate.py:469-475). I could not refute it.
- Evidence: `popup.summarize_fix_results` (popup.py:199-215) and
  `popup.fix_copied_bytes` (:240-250) both branch on `dry_run`; nothing in
  `consolidate.py` or `app.py`'s toast does. The mode is a supported, UI-exposed
  one, not a dev hatch: `settings_window._rehearsal_mode` (:511) renders it and
  `action_turn_rehearsal_off` (:522) turns it off, so "an admin will never have
  this on" is not available as a refutation.
- Fix note: the suggested fix is right. It must touch THREE places, not one:
  `consolidate.run_consolidation` (exclude `dry_run` from `copied` and from
  `batch_done`, and publish a `rehearsal` count beside `fixed`/`skipped`/
  `failed`), `app.py:3561-3589` (the toast, which must say "Rehearsal: nothing was
  copied" the way `summarize_fix_results` does), and the upload phase gate -
  `_consolidate_upload_phase` should not run a lane A push for a rehearsal that
  copied nothing. `companion/tests/test_consolidate.py` has no `fixer_dry_run`
  case at all, so nothing pins the old counting.

## comp-resolve-3
- Verdict: CONFIRMED
- Reasoning: the standalone-agent refusal sentence
  (timeline_cards_role.py:523-529) measures 247 characters before
  `describe_process(found)` is appended; `CardsAgentIn.detail` is
  `Field(default="", max_length=255)` (api.py:7716) on `_ReportSectionIn` ->
  `_BoundedSectionIn`, whose `_bound_rather_than_reject` validator TRUNCATES
  rather than 422s. So the dashboard stores the first 255 characters and RES-7's
  whole reason for adding `describe_process` - "the refusal used to name a
  command line and nothing else" - is cut off after 8 characters. I traced the
  field to its source to be sure it is this sentence: `report_block()["detail"]`
  is `status["health_detail"]` (:886), which for a role with no threads is
  `health()`'s `HEALTH_REFUSED, gate_detail` (:813-814), i.e. the refusal.
- Evidence: measured `len(base) == 247` in the companion venv; parsed through
  the real model in the dashboard venv with a plausible process line ->
  `sent 292, stored 255, tail: 'p on its own within a minute. Found: python.e'`.
- Fix note: prefer the hunter's first option (reorder so the process description
  leads) OR do both, but in either case add a DELIBERATE truncation on the
  companion side - a sentence cut by a wire cap is cut at whatever character the
  cap lands on, and this file already truncates `_loop_error` to 300
  (`_note_loop_end`). If `detail` is raised to 512 on `CardsAgentIn`, check the
  dashboard's storage width and renderer as well (`db.cap_cards_*`), and note
  that the same 255 cap sits on `JobsGateIn.detail` (api.py:7733) and truncates
  `check_contract`'s and `load_engine`'s long refusals in the same way.

## comp-resolve-4
- Verdict: CONFIRMED
- Reasoning: `supervise_now` (timeline_cards_role.py:676-683) returns True on
  `if self._threads:` without asking whether any of them is alive; `_start`
  (:562-564) short-circuits the same way; `_loop` records `_loop_error` on a
  raise or a return (:619-635) and `_note_loop_end` (:637-643) touches only that
  string. The only writer that empties `_threads` is `stop()` (:696), which the
  watchdog never calls. So a role whose loops have both died holds two dead
  Thread objects for ever and the RES-7 watchdog answers "running" every 60 s.
  `health()` gets it right (:816-818 returns HEALTH_STOPPED off `_loop_error` or
  `not alive`), which is precisely the asymmetry: the REPORT is honest and the
  RECOVERY is not. I could not refute it - and `KNOWN_BUGS.md:12627` records the
  same "nothing ever cleared that list" as RES-6's finding, fixed only for
  `report_block`.
- Evidence: `grep -n "_threads" timeline_cards_role.py` -> written at `_start`
  (:568) and `stop()` (:700), read at `_start`/`supervise_now`/`health`/`status`;
  no clear anywhere else. `tests/test_timeline_cards_role_health.py` asserts
  `supervise_now()` five times but only over live threads and refusal states
  (`role._threads = [LiveThread(), LiveThread()]`, :110) - never after a loop
  death, so the suite cannot see it.
- Fix note: the suggested fix is right (`if any(t.is_alive() for t in
  self._threads): return True`), but the restart path MUST clear `_threads`,
  `_client`, `_engine` and `_loop_error` first and stop the old engine if it
  exposes a stop - otherwise the fix turns one dead role into a second live
  engine beside the first, which is the same "one machine, one Resolve client"
  breach as res-companion-2. Do the two together; they are one change in
  `_start`/`supervise_now`. A consecutive-failure ceiling belongs with it, or a
  restart that fails the same way becomes a minute-by-minute engine factory.
  `tests/test_timeline_cards_role_health.py` is where the new cases go; nothing
  there pins the current answer.

## comp-ytdl-jobs-1
- Verdict: CONFIRMED
- Reasoning: `UpgradeManager.refusal()` (upgrade.py:1464-1481) self-clears when
  `compare_to_running(record["version"])` is `VERSION_SAME` **or**
  `VERSION_OLDER`, while its own docstring justifies only "a machine that is now
  RUNNING the build it refused". Every refusal produced by the downgrade floor is
  by construction about a version at or below the running one (`_accept_offer` ->
  `_check_offer` -> the floor test, upgrade.py:1352-1369 and :1405+), so the
  refusal REL-3 exists to surface is the one refusal that can never be reported.
  I checked the obvious refutation - that a not-newer offer might be dropped
  before `_note_refusal` is reached - and it is not: `_accept_offer` records the
  verdict first and `note_report_response` only then discards the offer
  (:1502-1505).
- Evidence: run against the real module in the companion venv (running VERSION
  0.9.70): `_note_refusal('0.9.65', 'v0.9.65 is below the downgrade floor
  v0.9.70')` stores the record, then `refusal()` -> `None`; the same call with
  `'0.10.0'` returns the record. The pinning test is the giveaway:
  `tests/test_upgrade.py:1764 test_a_build_below_the_floor_is_a_refusal_too`
  refuses version **9.9.8** - still NEWER than 0.9.70 - so it asserts the
  behaviour holds using a version that cannot arise from a real downgrade-floor
  refusal. Rule 7's "a test that mocks away the exact thing that breaks".
- Fix note: the fix (clear on `VERSION_SAME` only) is right and is one line, but
  it changes what `test_a_build_below_the_floor_is_a_refusal_too` is actually
  testing - rewrite that test to use a version BELOW `config.VERSION`, which is
  what makes the bug visible. Nothing on the dashboard side needs to change:
  `UpgradeIn.refused_version/_reason/_at` (api.py:6935) and
  `api._store_upgrade_refusal` already accept whatever arrives. Check
  `upgrade_report(..., refusal=...)` (upgrade.py:456) is the only reader - it is.

## comp-ytdl-jobs-2
- Verdict: CONFIRMED
- Reasoning: `stop_current()` (jobs_runner.py:427-453) appends the job id to
  `self._cancel` and returns True immediately; `note_report_reply` (:327-331)
  does `self._cancel = stops[:16]` - a wholesale REPLACE, not a merge - and the
  dashboard can never carry that id, because nothing tells it about a local stop
  (`db.pending_job_cancels` is fed only by an admin cancel). Worse, the common
  case is `stops == []`: `api_report` omits `commands.jobs` entirely when the
  block is empty, so an idle fleet's reply erases the list. The consumer
  (`_cancel_requested`, :514-522) is polled once per `proc.wait` slice - for
  whisper `max(0.1, min(HEARTBEAT_SECONDS, PROGRESS_MIN_SECONDS))` at
  jobs_runner.py:1140-1141 - so there is a real window in which the id is erased
  before it is read, and once erased it never comes back: the heartbeat keeps
  renewing the lease and the job runs to completion after the tray said it was
  stopped. I could not refute it.
- Evidence: `grep -n "_cancel" jobs_runner.py` -> written at :264 (init), :330
  (the replace) and :450 (the append); no persistence, no merge, no second store.
  `tests/test_jobs_runner_visibility.py` exercises `stop_current` in isolation and
  never calls `note_report_reply` afterwards.
- Fix note: the suggested fix is right - a separate `_local_cancel` set that
  `note_report_reply` unions in rather than overwrites - with one caveat the
  hunter did not state: the local set must be PRUNED when the job's result is
  posted (`_post_result`), or a stale id cancels the next job that happens to
  reuse the number after a dashboard rebuild. Only `jobs_runner.py` changes; add
  the race to `tests/test_jobs_runner_visibility.py` (stop, then feed a reply
  with no `jobs` block, then assert `_cancel_requested` is still true).

## comp-ytdl-jobs-3
- Verdict: CONFIRMED
- Reasoning: verified each hop. `install_tool`'s download arm swallows the
  exception into `log.info("sidecar: %s download failed (%s)", asset, exc)` and
  returns False (sidecar_tools.py:314-318); `ensure_ffmpeg_pair` turns that into
  `{"action": "failed", "message": f"could not install {', '.join(failed)}"}`
  with the cause dropped (:410-413); `ytdlp_manager._loop` logs that string at
  `logging.INFO if enabled else logging.DEBUG` (:1149-1150) - DEBUG on the
  vendor default, i.e. nothing at the shipped level. I tried to refute it on
  fleet visibility and it only half survives: `cap_ffmpeg` IS stored (db.py:1458)
  and IS exposed per machine on `GET /api/v1/jobs/machines` (api.py:9776), so the
  FACT is retrievable - but `grep -rn ffmpeg dashboard/src/.../alerts.py` has no
  hits, no frontend renders the capability (`grep -rn ffmpeg --include=*.html
  --include=*.js dashboard/src` -> nothing), and nothing consumes that route
  inside the dashboard (`grep -rn "jobs/machines"` -> only its own definition).
  So the cause reaches nobody and the fact reaches only an admin who thinks to
  curl the picker API or run `tools/jobs.py`.
- Evidence: the greps above; `sidecar_tools.ensure_ffmpeg_pair` read in full.
  The known field trigger is recorded in MEMORY ("macOS sidecar downloads fail
  on SSL CA verify"), so this is not a hypothetical failure mode.
- Fix note: the suggested fix is right and CYT-7 is the pattern to copy, but it
  is a four-file change, not one: `sidecar_tools.py` (carry the exception text
  into `message`, and count consecutive failures so a repeat logs at WARNING
  regardless of the flag), `ytdlp_manager.py` (stop demoting the line to DEBUG
  when the downloader is off - the ffmpeg half is no longer a YouTube
  entitlement, as its own comment at :1135-1142 says), a new
  `sync_guard.sidecar` block on the companion reporter, and the dashboard:
  a model on `_BoundedSectionIn`, a column, and an `alerts.ALERT_KINDS` row -
  which per CLAUDE.md must be registered WITH its writer.

## res-companion-1
- Verdict: CONFIRMED
- Reasoning: I traced the whole chain and it holds. `_apply_file_moves`
  (app.py:7289-7307) calls `apply_move`, then `_relink_moved_result`, and only
  THEN `self.file_moves.record(...)`. `record` (file_moves.py:319-341) stores
  `old_local`/`new_local` only `if paths:`, with an `elif previous.get(
  "old_local")` arm that needs an entry the crash prevented. On redelivery the
  file is already at the new path, so `apply_move` takes the `if not src.exists():
  return True, "nothing at the old path on this machine", None` arm
  (file_moves.py:193) - `paths is None`, so app.py:7303's `if ok and paths is not
  None` skips the relink, `relink_pending` stays False, and the companion answers
  the dashboard `ok: true`. Both recovery routes then fail for the same missing
  field: `pending_relinks()` filters on `relink_pending and old_local`
  (:385-388) and `moved_to()` skips any entry without both (:397-409). The window
  is not the rename - `src.replace(dest)` is atomic - it is
  `move_proxy_siblings` plus the media-pool walk in `_relink_moved_result`, which
  is seconds to tens of seconds, on a codebase where "died without a shutdown" is
  a routine event (CR-93, supervisor 0.9.62).
- Evidence: the three gates read directly (file_moves.py:193, :334-338, :385-388;
  app.py:7303). `grep -an "old_local" KNOWN_BUGS.md` -> two hits, both in the
  RES-10 entry, neither covering the no-entry crash window.
- Fix note: the intent-entry fix is the right shape, with one correction: the
  resume test must be `an entry in state applying exists AND src is gone AND dest
  exists` - not `dest exists` alone, or a legitimate "nothing was ever here"
  answer on a machine that never held the file becomes a relink attempt against
  another machine's move. The change touches `file_moves.py` (a new
  `STATE_APPLYING`, written before the first filesystem call, and the resume arm
  in `apply_move` or its caller) and `app.py:_apply_file_moves`; the dashboard
  side needs nothing new, since `retrying` already exists as an answer (v36).
  `docs/FILE_MOVES.md` should record the new state.

## res-companion-2
- Verdict: CONFIRMED (mechanism), with the trigger noted as dormant
- Reasoning: `_start` (timeline_cards_role.py:597-612) constructs the engine and
  calls `engine.start()` BEFORE `make_tunnel_client(...)`, and `self._engine =
  engine` is inside the `with self._lock:` block that follows it. Anything raised
  by `make_tunnel_client` - and it calls another repo's class positionally,
  `_TunnelClient(role.dashboard_url, "", engine, role.machine)`
  (:335-351), with `class _TunnelClient(agent_mod.AgentClient)` itself able to
  raise AttributeError - leaves a STARTED engine nothing holds a reference to.
  `_start_guarded` (:549-557) swallows it, `_threads` is still empty, and
  `supervise_now`'s only liveness test is `if self._threads` (:678), so
  `_supervise` re-enters `_start` every `PROBE_CACHE_SECONDS` (60 s) with no
  ceiling, starting another engine each time. `stop()` (:697-701) sets
  `self._engine = None` and never calls `engine.stop()`, so even the referenced
  one is not stopped. I could not refute the mechanism. Trigger: `cards_agent` is
  off everywhere and the bridge contract has never run live, so this is latent -
  which is the best time to fix it.
- Evidence: `_start` read in full; the assignment order is unambiguous.
  `grep -n "engine.stop\|_engine" timeline_cards_role.py` -> `_engine` is only
  ever assigned or cleared, never stopped.
- Fix note: build the client BEFORE `engine.start()` - that is strictly better
  than a try/except around the tail, because it removes the window rather than
  cleaning up after it. Keep the try/except as well if `engine.start()` can fail
  after partially taking Resolve. The consecutive-failure ceiling the hunter asks
  for is the same one comp-resolve-4's fix needs; do them in one change, and give
  `stop()` a best-effort `engine.stop()` while you are in there. Only
  `timeline_cards_role.py` changes; `tests/test_timeline_cards_role.py` has no
  case for a start that half-succeeds.

## res-companion-3
- Verdict: DOWNGRADED to low
- Reasoning: the state is real - between `self._replace(exe, old)` and
  `self._replace(new, exe)` (upgrade.py:1752-1762) there is no
  `ccsync-companion.exe` - and `supervisor.decide` does stand down on it
  ("the companion exe is no longer on disk", :136-137). Two things argue the
  rating down. First, the window is two CONSECUTIVE `os.replace` calls, i.e.
  sub-millisecond, with every failure of the second one already handled by
  `_rollback`. Second, and more telling: `_rollback` itself documents this exact
  end state as an accepted outcome with a human as the answer - "ROLLBACK FAILED
  -- the previous build is at %s; rename it back to %s by hand"
  (upgrade.py:1830-1833, AUDIT_2 CORE-H7). So this is not an unrecognised failure
  path; it is a recognised one that the supervisor could, but does not, repair.
  Third, the proposed repair helps in fewer cases than it appears: a power loss
  takes the supervisor with it and the next boot has only the Run key (which
  points at the missing name), and an AV or `Stop-Process` that kills by image
  name kills the supervisor too - the module docstring says so deliberately.
  That leaves "an AV killed only the companion process, by pid, inside a
  sub-millisecond window" as the case the fix covers.
- Evidence: `_apply_inner` and `_rollback` read in full; `decide` :136-137;
  `grep -rn "cleanup_old_exe\|revert_to_previous_build"` -> app startup only,
  which confirms the hunter's point that every other recovery is inside a
  companion that has started.
- Fix note: the fix is still worth doing - it is cheap, it is strictly safer
  than leaving an install with no binary, and it is the one repair only an
  outside process can perform. Guard it tightly: restore `.old` only when the
  marker names OUR supervised pid, `exe` is absent AND `<exe>.old` exists, and
  log it loudly, or a supervisor racing a live `windows_upgrade.ps1` install
  will put the OLD build back over a swap in progress. Files:
  `supervisor.py:main` and `tests/test_supervisor.py`. Note that
  `installer/windows_upgrade.ps1` performs its own swap on the same paths, so
  the guard has to be right.

## res-companion-4
- Verdict: DOWNGRADED to low - and this is the SAME DEFECT as comp-ui-2
- Reasoning: same mechanism, same file, same lines (supervisor.py:167-181 and
  :138-142): the relaunch ceiling has no memory outside
  `<state>/supervisor.json`, and both the read and the write swallow everything.
  res-companion-4 adds the second half comp-ui-2 does not have, and it is a real
  addition: `upgrade._write_json` returns False and logs at DEBUG (:180-193), its
  caller `note_version_start` (:219) does not check the return, and so the
  companion's OWN crash-loop revert (app.py:9888-9897, APP-5) degrades the same
  way from the same directory. Treat them as one finding with two counters.
  The downgrade is for the reason given under comp-ui-2: the run marker
  (`crash_dir` = `resolved_log_path(cfg).parent / "crashes"`) and the history
  (`resolved_log_path(cfg).parent / "state"`) are siblings under one parent, so
  the disk-full / unwritable-`~/.ccsync` scenario that drives this finding also
  stops `write_run_marker` refreshing the marker - and `decide` stands down on a
  marker that does not name the supervised pid BEFORE it ever reaches the
  history cap. That caps the loop at one relaunch in the named scenario. The
  unbounded case needs the marker writable and the history not.
- Evidence: `crash_report.crash_dir` (:106-119) vs
  `crash_report.start_supervisor`'s `state_dir` (:679) - same parent;
  `write_run_marker` (:481-496) swallows exactly like `write_history`;
  `decide`'s pid check at :127-130 precedes the cap at :138-142.
  `upgrade._write_json` and `note_version_start` read directly.
- Fix note: as comp-ui-2 - carry the count on the child's argv rather than
  making the ceiling depend on a file, and give `decide` a symmetric skew
  tolerance. The extra file this half adds is `upgrade.py`: `note_version_start`
  should at minimum log at WARNING when `_write_json` returns False, since a
  crash-loop counter that cannot be written is a machine that needs a human.
  `companion/tests/test_supervisor.py` and `tests/test_crash_loop_revert.py` are
  the suites that pin the current behaviour.
