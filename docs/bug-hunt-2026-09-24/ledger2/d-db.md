# Fix wave 2, group d-db (db.py)

Tests: `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-db.py` (18 tests; 21 after the review round). Against
a scratch copy of the dashboard with HEAD's `db.py`, 11 fail (every fix's test)
and 7 pass (the guard tests that pin behaviour that must not change). With
this tree, 18 of 18 pass.

Wider run over the 36 existing test files that exercise the changed functions
(jobs, selections, file moves, backlog, forget, prune, report): 737 passed,
1 skipped, 1 failed. The failure is
`test_report_endpoint.py::test_report_transfers_list_is_capped`, which another
group edited for bug-wire-3 (the api.py side is still in progress). It does
not touch db.py.

## bug-dash-db-1 - The scheduler only looked at the first 200 queued jobs
- Status: FIXED
- Verified as: verifier med-05 CONFIRMED. I re-read `queued_jobs` (a single
  `LIMIT 200` over the whole queue), `claim_next_job` (scans that window even
  when given `allowed_ids`) and `jobs.offers_for_machine` (same window).
- Fix: `db.py` `queued_jobs` (~10451): `limit` now applies PER KIND
  (`ROW_NUMBER() OVER (PARTITION BY kind ORDER BY priority DESC, id ASC)`),
  and the result is still one list in scheduler order. A new `ids=` argument
  looks rows up by id with no window (chunked at 500 parameters).
  `claim_next_job` (~10731) passes the intersection of `allowed_ids` and `ids`
  as `ids=`, so an offered id is claimable wherever it sits in the queue.
  `jobs.offers_for_machine` gets the per-kind window with no change to its code.
  Window functions need SQLite 3.25 or later. The image is python:3.12.7-slim
  (3.40 or later), and the dev venv has 3.49.
- Regression test: `test_a_kind_nobody_can_run_does_not_hide_the_jobs_behind_it`,
  `test_the_claim_reaches_a_job_past_the_window`,
  `test_an_offered_id_deep_in_one_kind_is_claimed_by_id`. On HEAD the
  `peaks` id is missing from the window and the claim returns None.
  `test_priority_still_outranks_age_across_kinds` is a guard.
- Tests run: see top -> pass.
- Skew / deploy order: dashboard only. No wire or schema change.
- Left over: one kind can still starve ITSELF, for example 200 whisper jobs
  targeted at a machine that is off, ahead of a whisper job for another
  machine. That is much narrower than the finding and needs no change today.
- OWED: none.

## bug-dash-db-2 - Proxies past the 2,000 cap showed as downloads owed for ever
- Status: PARTIAL (the wording is OWED to d-ui)
- Verified as: verifier med-05 CONFIRMED. `fetch_sync_backlog`'s down diff
  counts every NAS proxy that has no `editor_media` row, and the companion
  lists at most 2,000 per kind.
- Fix: `db.py` new `_proxy_manifest_capped` (~9808) decides whether the
  PROXY list was the capped one. The project-wide `truncated` flag cannot say
  which kind hit the cap, so the test is rollup `n_proxies` > the number of
  listed proxy rows. When the proxy list was capped, `fetch_sync_backlog`
  (~9830) takes the count from the exact rollup:
  `min(diff, NAS proxies - held proxies)`, and the bytes the same way. If that
  comes to 0 the row is dropped. Otherwise it keeps the count but shows no file
  names, because any listed name could be one the machine holds.
  `manifest_truncated` is still set. The uncapped path and the upload path are
  unchanged.
- Regression test: `test_a_machine_holding_every_proxy_past_the_cap_owes_nothing`
  (on HEAD, 500 phantom downloads) and
  `test_a_capped_manifest_still_reports_what_is_really_missing`. Guard:
  `test_an_uncapped_proxy_list_keeps_the_exact_diff`.
- Tests run: see top -> pass.
- Skew / deploy order: dashboard only. It reads columns the companion has
  sent for a long time.
- OWED: d-ui, `dashboard/templates/partials/transfers.html:78`: word the
  `manifest_truncated` line by `q.direction`. For `up`, keep "totals may
  undercount". For `down`, say something like "(this computer's proxy list
  was capped; the count is worked out from its totals)". No em dash. Also,
  the related logic-sync-truth-2 `safe_to_close` half belongs to its own group.

## bug-wire-1 - The "Resolve relinked after all" answer was dropped
- Status: FIXED
- Verified as: verifier med-08 CONFIRMED (a duplicate of bug-comp-app-4).
  Companion `app._relink_pending_moves` queues `ok=True` with no
  `relink_pending` and no `state`. Every arm of `mark_file_move_applied` was
  `AND applied_at IS NULL`.
- Fix: `db.py` `mark_file_move_applied` (~6278). When the main UPDATE matches
  nothing, an `ok` answer that is not relink-pending and has no
  retrying/blocked state clears `relink_pending` and replaces `detail`, but
  only on a row that is `ok=1 AND relink_pending=1`. `applied_at` keeps the
  time of the first answer. A terminal failure cannot be rewritten, and a
  repeat answer is a no-op that returns False, so api.py's de-duplicating log
  line stays quiet.
- Regression test: `test_the_relinked_after_all_answer_clears_the_flag`
  (fails on HEAD). Guards: `test_a_late_answer_cannot_rewrite_a_terminal_failure`
  and `test_a_repeated_relink_pending_answer_changes_nothing`.
- Tests run: see top, plus test_file_moves.py -> pass.
- Skew / deploy order: dashboard only. Companions from 0.9.55 on already send
  the second answer.
- OWED: d-api, `dashboard/src/ccsync_dashboard/api.py` ~9589 (the comment
  "Terminal answers cannot repeat: mark_file_move_applied only matches
  `applied_at IS NULL`"). A comment only: add that the one exception is RES-10's
  relinked-after-all answer, which clears `relink_pending` once.

## logic-plans-1 - Unticking a bucket-inherited project did nothing, and the tray then widened the untick
- Status: FIXED (the dashboard side). A companion belt is OWED to c-sync.
- Verified as: the hunt table has it as medium (was high). I reproduced it in
  the new test on HEAD: `remove_selection(pb, machine=LAP)` returns True and
  `selections_for_machine(LAP)` still returns `['pb']`, because LAP has no own
  rows left and falls back to the bucket.
- Fix: `db.py` `remove_selection` (~6915). When the project being unticked
  came from the bucket and the machine is REGISTERED: after materialising onto
  this machine, every other registered, non-wired computer that still
  inherits the bucket gets its own copy (`materialise_bucket` does nothing for
  one that already has a plan, and is not stamped as a change). Then the
  project's bucket row is deleted. An emptied plan now reads as empty, and no
  other computer's plan changes. An unregistered hostname keeps the old
  behaviour, so a first report still inherits. This follows copy_machine_plan's
  own §3.2 note that a new computer starts empty on purpose.
  add_selection_for_person already stopped writing the bucket once a person
  has machines.
- Regression test: `test_unticking_the_last_inherited_project_really_removes_it`
  (fails on HEAD). Guards: `test_the_bucket_drain_keeps_another_inheriting_computer_whole`
  and `test_an_unregistered_hostname_does_not_end_the_inheritance`.
- Tests run: see top, plus test_multi_machine, test_selection_api,
  test_admin_assignments, test_fleet_audit, test_upload_only -> pass.
- Skew / deploy order: DASHBOARD FIRST. Until the dashboard is deployed, a
  companion that unticks its last inherited project still widens the untick
  (today's behaviour).
- Audit note: the untick's before/after placement snapshot is scoped to the
  target machine, so the bucket row's removal is not in it. A DASH-8 undo
  restores the row on the target, and the other machines keep their
  materialised copies, so the effective plan is the same.
- OWED: c-sync, `companion/src/ccsync_companion/selection.py` ~499 (the
  `elif ok and machine and self._still_selected(view, slug)` branch). Widen
  to the person-wide DELETE only when the answer's `view.get("changed")` is
  falsy. A `changed=True` answer that still lists the slug is a dashboard older
  than this fix, and widening then deletes the person's other computers' rows,
  which is the comp-lane-c-2 outcome. This is a skew belt only.

- Review round (2026-09-25, adversarial reviewer): PROBLEM accepted, both halves.
  (1) The bucket drain was gated only on "the bucket holds the slug and the
  machine is registered", so a NO-OP untick (LAP with a plan of its own that
  never held pb) deleted the ('', pb) row and pinned every other computer,
  against the comment's own "a no-op removal does not quietly end the
  inheritance". Fixed: `remove_selection` now drains only when
  `materialise_bucket(conn, editor, machine) > 0`, i.e. the machine really was
  inheriting (no own rows, and the bucket was copied onto it). Test:
  `test_an_untick_of_a_project_the_machine_does_not_inherit_leaves_the_bucket_alone`
  (the reviewer's probe: answers False, the bucket row stays, DESK writes no
  own row and still inherits pb).
  (2) The undo gap (predates this fix, made lasting by the drain): a
  machine-scoped untick snapshotted `selection_placements(machine=LAP)`, which
  read only own rows, so an inherited project read before=[] after=[] and
  `audit_plan_change` dropped the row as a no-op: no [ UNDO ] and no
  enforce-cycle freeze for a project that really stopped syncing there.
  Fixed: `selection_placements` with a named, non-wired machine that has NO own
  rows reports the bucket's row for that slug under the machine's own name, in
  the bucket's mode (the same inheritance rule as `selections_for_machine`).
  The untick now records before=[{LAP, full}] after=[], and DASH-8's undo
  re-adds LAP's row, which restores what LAP syncs; the other computers keep
  their materialised copies, so every effective plan is back. The bucket row
  itself is not recreated; the only lasting difference is that a computer
  registered LATER does not inherit pb, which matches copy_machine_plan's §3.2
  note that a new computer starts empty. Side effect, checked: a tick of an
  already-inherited project now reads before=[LAP] after=[LAP] and writes no
  audit row (it changed nothing), where it used to record before=[] and its
  undo would have removed an inherited project. Tests:
  `test_an_inherited_placement_is_snapshotted_under_the_machines_name` (own-plan,
  wired and newcomer cases) and
  `test_an_untick_of_an_inherited_project_is_recorded_and_undoable` (end to end
  through DELETE /api/v1/selection and /partials/plan-changes/<id>/undo).
  All three fail with the pre-review code and pass now. Tests run: the d-db file
  (21 passed) plus test_multi_machine, test_selection_api,
  test_admin_assignments, test_fleet_audit, test_upload_only and every test
  file that calls selection_placements / remove_selection / copy_machine_plan /
  materialise_bucket / the plan-change undo: 308 passed.
  The earlier "Audit note" above is superseded by (2).

## logic-plans-4 - A move out of a borrowed folder never reached the borrowing machines
- Status: PARTIAL (the dashboard side is fixed; the companion manifest half is OWED to c-sync)
- Verified as: verifier med-09 CONFIRMED. I re-read `file_move_target_machines`
  (the plan holders of `from_slug` plus the `editor_media` holders only). On
  the companion side, `file_moves._dest_is_synced_here` already treats
  borrowed subtrees as synced here, and `apply_move` resolves by
  `from_project_rel`. So a borrower that receives the command does the right
  thing: it follows the move, or does the 4b trash when the destination is not
  synced there.
- Fix: `db.py` `file_move_target_machines` (~5893) also adds every machine
  whose plan (for_enforce, any mode) holds a borrower of `from_slug`, through
  `project_links` rows with status `ok` or `missing` and a non-empty `sub_rel`.
  A link matches when `from_rel` is the shared folder, is inside it, or is a
  directory above it. The comparison is NFC through `media_rel_key` and is
  segment-exact, so `Shared B-roll 2` does not match `Shared B-roll`.
  `missing` counts because the folder having just moved away is the likeliest
  reason a link reads missing at that moment.
- Regression test: `test_a_move_out_of_a_borrowed_folder_reaches_the_borrower`
  (fails on HEAD. It also pins the sibling-prefix and non-shared-path cases).
- Tests run: see top, plus test_file_moves, test_hand_moves_detected,
  test_enforce -> pass.
- Skew / deploy order: dashboard only. Any companion that handles file moves
  (0.9.55 or later) can apply them.
- OWED: c-sync, `companion/src/ccsync_companion/manifest.py` ~173. Build the
  per-file lists for borrowed subtrees as well (the keys of
  `rel_to_slug_with_borrowed`). Without that, the `editor_media` arm still
  cannot find a borrower that has since unticked the borrowing project. The
  hunter's second half, and not needed for the scenario above.

## bug-dash-db-3 - Forgetting a computer or person left their diagnostics bundles
- Status: FIXED
- Verified as: low, so I verified it myself. The only DELETE on
  `diagnostics` is prune's 30-day bound, and `_MACHINE_STATE_TABLES` cannot
  hold the table because its columns are `editor`/`machine`.
  `newest_diagnostics_per_machine` ("every computer that has ever sent one")
  kept listing the forgotten computer on the admin diagnostics panel, and a
  reused username inherits the bundles. This is not covered by the "history
  tables are kept on purpose" comment: a bundle is drawn as the computer's
  newest state, not as a log.
- Fix: `db.py` new `_forget_diagnostics` (~8603). `forget_machine` deletes by
  (editor, machine) and `forget_editor` by editor. Both return the count in
  `deleted["diagnostics"]`.
- Regression test: `test_forgetting_a_computer_takes_its_diagnostics` and
  `test_forgetting_a_person_takes_every_bundle` (KeyError / leftover rows on HEAD).
- Tests run: see top, plus test_admin_delete, test_diagnostics -> pass.
- Skew / deploy order: dashboard only.
- OWED: none.

## logic-ytdl-jobs-5 - The collector's lease sweep ignored DASH_JOBS_COOLDOWN_SECONDS
- Status: PARTIAL (the collector call site is OWED to d-diag)
- Verified as: low, so I verified it myself. `prune` called `expire_leases(conn, now, pin=pin)`
  with the 120 s default. `settings.jobs_cooldown_seconds` is read only by
  api.py's claim and fail routes. `collector._run_prune` calls
  `db.prune(conn, self.now_fn(), pin=pin)` and has `self.settings` in hand.
- Fix: `db.py` `prune` (~8925) takes `jobs_cooldown_seconds: float | None = None`
  and passes it to `expire_leases`. None keeps JOB_COOLDOWN_SECONDS, so
  existing callers are unchanged.
- Regression test: `test_prune_takes_the_operators_cooldown` (TypeError on
  HEAD). Guard: `test_prune_default_cooldown_is_unchanged`.
- Tests run: see top -> pass.
- Skew / deploy order: dashboard only.
- OWED: d-diag, `dashboard/src/ccsync_dashboard/collector.py` `_run_prune`
  (~2298). Call `db.prune(conn, self.now_fn(), pin=pin,
  jobs_cooldown_seconds=self.settings.jobs_cooldown_seconds)`. Until that
  lands, the operator setting still has no effect on the collector path.


# Owed round (2026-09-25, builder d-db)

Items other groups left for `db.py`. Regression tests are appended to
`dashboard/tests/test_bug_hunt_2026_09_24_w2_d-db.py` (section "owed round").
HEAD check: the file was run against `git archive HEAD dashboard` in a scratch
copy with `PYTHONPATH` on that copy's `src`. All ten new tests fail there, and
the one guard (`test_a_capped_proxy_list_alone_does_not_make_the_upload_uncertain`)
passes on both.

Tests run (dashboard venv, from `dashboard/`): `test_bug_hunt_2026_09_24_w2_d-db.py
test_notices_sweep_wave2.py test_cr313_315_ruskin_phantoms.py test_fleet_halt.py
test_notices.py test_cr311_queue_says_on_hold.py test_alerts.py
test_bug_hunt_2026_09_18_dashboard_mediums.py test_cli_auto_update.py
test_health_page.py test_notices_auto_resolve_cr320.py test_protection.py
test_sweep_2026_09_04_dashboard.py test_triage.py` -> 414 passed (after the
test_fleet_halt edit below).

Existing tests changed because the behaviour changed: `test_notices_sweep_wave2.py`
lines 58 and 139 pinned the `/fleet` href (now `/`), and `test_fleet_halt.py`
`test_extend_on_an_expired_halt_refuses_rather_than_going_blank` pinned the raw
ISO in the banner (now it pins the readable form).

## logic-sync-truth-2 (owed by c-sync) - a capped ORIGINALS list must hold back "Safe to close"
- Status: PARTIAL (db half FIXED; the api filter and the UI are OWED)
- Verified as: med-09 CONFIRMED. Read `fetch_sync_backlog`: the up diff walks
  `editor_media` only, and `if not n_files: continue` drops the pair when the
  listed originals are all on the NAS, even when the rollup `n_originals`
  says the machine holds more than it listed.
- Fix: `db.py` new `_original_manifest_capped` (beside `_proxy_manifest_capped`),
  true when `truncated` and held `n_originals` > listed `kind='original'` rows.
  `fetch_sync_backlog` selects `emp.n_originals`, keeps the up row for such a
  pair even with `n_files` 0, and every row now carries `"uncertain"` (true
  only on an up row whose originals list was capped). No invented count: the
  unlisted originals may be on the NAS, and the rollup also counts files lane A
  skips (CR-315), so "held minus NAS" is not even a lower bound.
- Regression test: `test_a_capped_originals_list_is_an_uncertain_upload_even_when_the_diff_is_empty`
  (HEAD: no up row), `test_a_capped_originals_list_with_a_real_diff_is_flagged_uncertain`,
  `test_an_uncapped_originals_list_is_certain_and_empty_when_all_uploaded`,
  `test_every_down_row_carries_uncertain_false` (KeyError on HEAD); guard
  `test_a_capped_proxy_list_alone_does_not_make_the_upload_uncertain`.
- Tests run: see top.
- Skew / deploy order: dashboard only. `uncertain` is a new optional key on an
  internal dict; readers must use `.get`.
- OWED:
  - d-api, `dashboard/src/ccsync_dashboard/api.py` ~line 690, the transfers
    view: `queues = [q for q in queues if q["n_files"] > 0]` drops the new
    zero-file uncertain row. Keep `q.get("uncertain")` rows
    (`if q["n_files"] > 0 or q.get("uncertain")`). Until this lands, the
    signal stops at the api, and the page behaves as it did on HEAD.
  - d-ui, `dashboard/templates/partials/transfers.html` ~line 64: an
    `uncertain` up row with `n_files` 0 would render "0 files · 0 B upload".
    Say that this computer's file list was capped and the dashboard cannot
    tell whether it still owes uploads, naming the machine. c-sync already
    routed `ui.py` `safe_to_close` to d-ui: key it on `q.get("uncertain")` for
    an up row (never "Safe to close" then; name the machine and project).

## ui-copy-2 (owed by d-diag) - notice hrefs to `/fleet` are 404s
- Status: FIXED (one extra 404 found and fixed; one in recovery.py OWED)
- Verified as: `/fleet` has no route (d-diag's TestClient run). My new test
  requests every registry href from a TestClient app as an admin, and it found
  one more 404 the finding did not name: `file_moves_dropped` linked
  `/projects`. Only `/api/v1/projects` exists; the project cards are on `/`.
- Fix: `db.py` NOTICE_KINDS: the seven `"/fleet"` kinds and the `_slug_href` /
  `_plan_pair_href` fallbacks now go to `/`. `collector_cycle_failed`,
  `collector_watchdog_restart`, `syncthing_unreachable`, `db_busy`,
  `slow_write` and `slow_poll` go to `/#fleet-collector`. `server_error` and
  `feature_not_mounted` go to `/admin/health`. `file_moves_dropped` goes to
  `/`. A block comment above the registry cites the finding.
- Regression test: `test_no_notice_links_to_the_fleet_path_that_404s`,
  `test_the_collector_kinds_point_at_the_collector_panel`,
  `test_every_notice_href_is_a_page_the_dashboard_serves` (HEAD: `/fleet` 404,
  then `/projects` 404).
- Tests run: see top.
- Skew / deploy order: dashboard only.
- OWED:
  - d-ui (already routed by d-diag): `templates/partials/collector_health.html`,
    `id="fleet-collector"` on the [ COLLECTOR ] side-head. It is not there yet
    (grep 2026-09-25). Until then the six collector kinds land at the top of
    SYNC STATUS: not a 404, but it does not scroll to the panel.
  - d-diag, `dashboard/src/ccsync_dashboard/recovery.py` ~line 1036: the
    rollback plan's "Create it again from the Projects page here" step has
    `href="/projects"`, which is a 404 too. Project creation is `/project-setup`
    (ui.py `@router.get("/project-setup")`). `tests/test_recovery.py:366`
    pins `/projects` and must change with it.

## ui-dash-admin-12 (owed by d-ui) - the stale KEEP HALTED refusal printed a raw ISO stamp
- Status: FIXED
- Verified as: read `set_fleet_halt`. The refusal was
  `f"Syncing already started again at {when}"` with `when` the stored ISO,
  and the halt panel shows ValueError text verbatim.
- Fix: `db.py` new `_halt_when_text(conn, when)`, called by the refusal. It
  renders the stamp in the site zone as `YYYY-MM-DD HH:MM <zone>`, the same
  format as `triage.local_time`, through `alerts._zone_or_utc`. alerts is
  imported lazily because it imports db. Any failure there falls back to UTC,
  and an unparseable stamp falls back to the stored text. No em dash.
- Regression test: `test_the_stale_keep_halted_refusal_reads_as_a_time`,
  `test_the_stale_keep_halted_refusal_uses_the_site_zone`,
  `test_a_broken_zone_lookup_still_gives_the_refusal` (HEAD: the ISO in the
  message and no helper).
- Tests run: see top (test_fleet_halt 32 passed).
- Skew / deploy order: dashboard only.
- OWED: none.

## ui-copy-6 (owed by d-ui) - " -- " hits in db.py
- Status: NOT_A_DEFECT
- Verified as: re-ran d-ui's AST scan (string constants, docstrings and log
  calls excluded) over the current db.py. It finds nine hits: the eight named
  (47, 131, 268, 472, 499, 517, 775, 817) plus 7778. Every one is a `--` column
  comment inside a CREATE TABLE / migration / upsert SQL string. SQLite strips
  them, and no browser, toast, mail or HTTP detail ever shows them. The strings
  this round added contain none.
- Fix: none.
- Regression test: n/a.
- Tests run: n/a.
- Skew / deploy order: n/a.
- OWED: none. When d-ui widens DUI-14's scan to the package, it should exclude
  SQL strings (those passed to `execute`/`executescript`, or the module-level
  SCHEMA constants) or db.py will read as nine false hits.
