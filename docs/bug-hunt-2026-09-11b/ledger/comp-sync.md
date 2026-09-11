# The sync lanes, the file moves and the asset libraries (CR-249, 2026-09-11)

Nine findings from the 2026-09-11b hunt, all in the companion's `sync/*` and
`file_moves.py`. Seven of them are the morning's own fix pass (CR-234)
landing half of itself; two are new.

### CR-249a (comp-sync-b-1) - the abandoned-lane-B latch could be set after the pass had already ended, and then nothing ever cleared it - FIXED (sync/sequencer.py)

comp-sync-7 latched `_lane_b_abandoned` from the SEQUENCER thread, after
`thread.is_alive()` had already answered True, while the only code that can
ever clear it is that same lane B thread's own `finally`. The two orderings
cross: a wedged pass that ends in the window between the `is_alive()` check
and the assignment - a `_note_lane_moved()` and a lock acquire wide - clears
first and is latched second. From that moment the latch is permanently on:
every project turn logs "not starting lane B ... an earlier pass was
abandoned", lane B reads `stalled on <y>`, and NO proxy downloads again until
the editor restarts the tray. The lane is not red and no notice is raised, so
it is green while dead, for the one lane an editor notices last.

Every lane B pass now takes a GENERATION number, minted under `_lock` beside
`_lane_b_subpath`. The pass's `finally` calls `_retire_lane_b_generation(gen)`
and `_note_lane_b_abandoned(subpath, thread, gen)` refuses to latch a
generation that has already retired - both sides take the same lock, so there
is no window left to lose, and the sequencer says so in the log rather than
latching silently. Belt and braces, the latch remembers its THREAD and
`_run_lanes_a_and_b` drops one whose thread is no longer alive before
honouring it: a pass that died without reaching its finally at all costs one
turn, not the process.

### CR-249b (regression-4) - the stale-subpath gate is the ROTATION's, not the lane's: CONSOLIDATE's proxy pull was silently dropped - FIXED (sync/rclone_lane.py, sync/sequencer.py)

comp-sync-7's second half put "has the rotation moved on?" inside
`_run_once_locked`, i.e. on every caller of `run_once`. CONSOLIDATE and FIX
ALL call `run_once` on the SAME lane object the sequencer holds
(`app._consolidate_upload_phase`), and `_lane_b_subpath` is sticky between
turns - it names the last project the rotation visited. So an editor
consolidating project X while the last turn was on Y had their proxy pull
answered with `skipped a queued pass: the rotation had moved on`, after the
progress UI had already published "Downloading proxies from the server...".
The consolidated project ended with no proxies and a log warning nobody reads.

`run_once` takes `rotation_pass` (default False) and only a rotation pass may
be dropped for having gone stale. `Sequencer._run_lane` passes it for lane B,
duck-typed through `_accepts_kw` the way the time budget already is, so a lane
adapter or test double that predates it behaves exactly as it did.

### CR-249c (comp-sync-b-3, res-companion-3) - an in-flight deletion credit that was never reconciled made the NEXT pass's deletions invisible to the breaker - FIXED (sync/lane_guard.py, sync/rclone_lane.py)

`_in_flight_credited` was reset only by `note_pass()` and `resume()`, and
`run_once` has return paths that never reach `_account_pass` (an exception out
of `_run_popen` or `subprocess_run` after the run had already emitted
`--stats` ticks). The counter was then left at the dead pass's total, so the
next pass's `delta = total - credited` was negative for its whole length and
`note_pass` subtracted the same stale figure a second time: a pass that really
did trash 400 proxies added zero to the cumulative account the breaker trips
on. Exactly the direction res-companion-5 was written to stop, in the fix that
introduced it.

`LaneBBreaker.begin_pass()` starts a run's in-flight account at zero and the
lane calls it immediately before the spawn (`_begin_breaker_pass`, duck-typed
and never raising, because a safety device that can fail the run it guards is
worse than none). `note_deletes_in_flight` additionally re-baselines when the
running total is BELOW what is credited, which cannot be the same run - the
backstop for any caller that does not use `begin_pass`.

### CR-249d (comp-sync-b-2) - an `applying` intent row was indistinguishable from a completed move, so Resolve could be repointed at a file that was never moved - FIXED (file_moves.py)

res-companion-1 started writing `old_local`/`new_local` and
`relink_pending=True` BEFORE the first filesystem call, and `record()` carries
that pair forward into every later row for the id. Neither `pending_relinks()`
nor `moved_to()` looked at `state` or `ok`, and no consumer checked that
`new_local` exists. A companion killed between `record_intent` and
`src.replace(dest)` - CR-93's routine "died without a shutdown", or the
supervisor's own restart - therefore came back and, on the next project the
editor opened, walked the media pool and repointed every clip under
`old_local` at a path that does not exist on that machine: Media Offline,
journalled as a real Resolve mutation, in a project the editor was in the
middle of. The watcher's dialog was the same defect with a human in the loop,
telling the editor in writing that "Your copy has already been moved to
match".

`record_intent` now writes `relink_pending=False` (the completion row sets it
properly either way, including on the crash-resume path), and
`pending_relinks()` skips `applying` rows outright. `moved_to()` keeps the
one-click relink res-companion-1 built, but asks the DISK which of the two
crashes happened: the row is offered only when the file really is at
`new_local` and gone from `old_local`. Cannot tell counts as no.

### CR-249e (regression-6) - the case-only rename left its proxy behind - FIXED (file_moves.py)

Every other arm of `apply_move` calls `move_proxy_siblings`; comp-sync-12's
new case-only arm returned without touching `<parent>/Proxy/` at all. The
dashboard renames the proxy on the NAS with the original
(`docs/FILE_MOVES.md`), so the editor was left with `Clip.mov` beside
`Proxy/clip.mov`: lane B sees one proxy missing locally and one extraneous, so
it downloads the first, trashes the second into `.ccsync-trash` and charges
that deletion to the breaker's account. `move_proxy_siblings` could not be
reused as it stands - it keeps each proxy's own name, which for a rename that
differs only in spelling moves nothing. `rename_proxy_siblings_case_only`
renames each matching proxy to the destination's spelling through the same
staging two-step, and the count is folded into the detail the dashboard shows.

### CR-249f (comp-sync-b-4) - a failed case-only rename could leave the clip under a `.ccsync-move-` name that lane A then uploaded - FIXED (sync/rclone_lane.py, file_moves.py)

`_rename_case_only` stages the file at `.ccsync-move-<pid>-<original name>`,
and if both the second replace and the restore fail (Resolve holding a handle:
WinError 32 on both) that is what the editor is left holding. The staging name
keeps the original extension, and `recent_excludes` excludes the OLD rel path,
not this one - so the next lane A pass uploaded it to the NAS beside the real
clip, which is the duplicate-at-the-cleared-path failure `docs/FILE_MOVES.md`
exists to prevent, wearing a different name. `MOVE_STAGING_EXCLUDE_RULE` is in
both lanes' rule lists ahead of every include, and `path_matches_lane_a_filter`
refuses it too - express is lane A's other door, and a staging name sits
perfectly still on disk, so it clears the size-stability and min-age gates
easily.

### CR-249g (comp-sync-b-5) - a fleet halt held the borrowed folders but not the shared asset libraries - FIXED (sync/shared_folders.py)

`SharedFolderManager.reconcile` honours the halt only for a folder that
already EXISTS and is paused. A library being accepted for the FIRST time went
through `_accept` -> `admin.accept_folder`, which ends in an unpause, so an
admin who halted the fleet and then had the provision cycle offer a machine a
new library (LUTs, music) got that machine syncing it while every other lane
was stopped - the sync-safety-2 / CR-48 shape. comp-sync-10 edited both
`_accept` methods this afternoon and gave the guard to one of them.
`SharedFolderManager._accept` now returns `OUTCOME_HALTED` before it accepts,
exactly as the borrowed manager does; the offer keeps, and the next reconcile
after the halt takes it.

### CR-249h (security-4) - the Syncthing helpers followed redirects while carrying the API key - FIXED (sync/syncthing_admin.py, sync/syncthing_lane.py)

`syncthing_admin.http_request` and `syncthing_lane.default_http_get` both
handed a request carrying `X-API-Key` to the bare `urllib.request.urlopen`,
which follows 3xx and RE-SENDS the header to the new location. The shipped
`base_url` is loopback, so the peer is normally benign - but the constructor
takes a `base_url`, and a site that points a companion at a Syncthing GUI on
another host over plain http (or anything that can answer on that port first)
gets the machine's full lane C admin credential posted wherever it likes for
the cost of one 302. Every other outbound caller in this product installs
`build_no_redirect_opener` for exactly this reason; these two were the last
that did not. Both now share one lazily built no-redirect opener, so a 3xx
surfaces as an HTTPError and the key stays on the machine.

### Verification

- companion/tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_a_lane_b_that_ends_inside_the_latch_window_does_not_latch_for_ever -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_a_latch_whose_thread_has_died_is_not_honoured -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_a_consolidate_pass_is_not_dropped_by_the_rotations_subpath -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_a_rotation_pass_for_a_stale_subpath_is_still_dropped -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_the_sequencer_marks_its_own_passes_as_rotation_passes -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_deletions_after_a_pass_that_never_finished_still_reach_the_account -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_a_running_total_below_the_credit_is_read_as_a_new_run -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_lane_b_clears_the_in_flight_credit_before_it_spawns -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_an_intent_row_is_never_offered_as_a_completed_move -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_the_finished_move_is_still_offered -> the control: passes both sides
- companion/tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_a_case_only_rename_renames_the_proxy_beside_it -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_the_rename_staging_name_is_refused_by_both_lane_a_doors -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_a_halt_holds_a_new_asset_library_offer -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_the_offer_is_accepted_once_the_halt_is_over -> the control: passes both sides
- companion/tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_the_admin_helper_refuses_a_redirect_rather_than_resend_the_key -> fails at f1eeb42, passes now
- companion/tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_the_lane_c_helper_refuses_a_redirect_rather_than_resend_the_key -> fails at f1eeb42, passes now

Two existing tests were updated for the new contracts, both in this
territory's own files: `test_rclone_filters.py`'s lane B rule-list equality
(the new staging exclude) and
`test_bug_hunt_2026_09_11_comp_sync.py::test_a_queued_pass_for_a_stale_subpath_is_dropped`
(which now passes `rotation_pass=True`, since that is the only kind of call
the gate may drop).

Also run green after the change: test_sequencer.py, test_rclone_lane.py,
test_rclone_lane_races.py, test_rclone_express.py, test_rclone_filters.py,
test_lane_guard.py, test_file_moves.py, test_shared_folders.py,
test_borrowed_folders.py, test_syncthing_admin.py, test_syncthing_lane.py,
test_sync_sequencer_policy.py, test_bug_hunt_2026_09_11_comp_sync.py.

### OWED TO ANOTHER TERRITORY

- comp-app: `companion/src/ccsync_companion/app.py`: `_relink_pending_moves`
  (~:7759) and `_show_moved_clip_dialog` (~:7801): refuse an entry whose
  `entry["new_local"]` does not exist on disk before calling
  `resolve_bridge.replace_clip` / before telling the editor "Your copy has
  already been moved to match". comp-sync-b-2's belt and braces: the ledger
  half is fixed here (an `applying` row is no longer offered as a completed
  move), so this is defence in depth, not a dependency. No deploy ordering:
  both halves are companion-side.
- comp-app: `companion/src/ccsync_companion/app.py`: `_relink_moved`
  (~:7846-7857): this is regression-5, already assigned to comp-app. Noting
  it only because `file_moves.cmp_key` - the public spelling it must use - is
  in this territory and is unchanged by anything above.

### Owner decisions

- comp-sync-b-2: the hunter's suggested fix would have dropped the
  `applying` row from `moved_to()` outright, which would have taken
  res-companion-1's whole point with it (the one-click relink after a crash
  BETWEEN the rename and the record). I kept the offer and gated it on
  filesystem evidence instead: the row is offered only when the file really
  is at `new_local`. A case-only rename's two paths fold together on Windows
  and macOS, so an interrupted case-only rename is never offered - it answers
  "no relink to offer" rather than guessing.
- security-4's second half ("reject a non-loopback `base_url` over http") is
  NOT implemented. A site that has deliberately pointed a companion at
  another host's Syncthing GUI would stop syncing at the upgrade, and the
  no-redirect opener closes the leak this finding is about. Say the word and
  it becomes a refusal.
- comp-sync-b-4 spells `.ccsync-move-` in two places (`file_moves.py` and
  `rclone_lane.MOVE_STAGING_PREFIX`) rather than importing one from the
  other: `file_moves.py` deliberately imports nothing of its own. Each site
  names the other in a comment.
- The case-only rename's detail line reuses the existing "N proxy file(s)
  with it" wording from the ordinary move arm. It is the same string the
  dashboard already shows for every other move; the "(s)" plural ban's scan
  covers tray/settings/app/popup, not this module.

### Hand-off wave

#### CR-249i (regression-19, owed from comp-app) - the relink answer still said "clip(s)" to the editor - FIXED (`file_moves.py`)

`relink_moved`'s detail used to be a log line and a wire `detail`. comp-sync-11
folded `CompanionApp._relink_moved`'s own sentence into it, so the string is
now what the editor reads: the RELINK IT dialog answers with it through
`_notify_tray`, and `_relink_pending_moves` puts it in the answer that comes
back after a project change. It still spelled the plural "N Resolve clip(s)
relinked" - the developer shorthand the owner's 2026-08-18 rule retired from
copy an editor reads, and the one regression-19 could not reach because
app.py is not this territory. It goes through `ui_copy.count` now ("1 Resolve
clip relinked" / "3 Resolve clips relinked"); the refused tail is unchanged,
because a clip Resolve will not let us repoint is not something another pass
fixes and the sentence must still say so. The "proxy file(s)" details in
`apply_move` are deliberately NOT converted: those are the wire `detail` the
dashboard stores and shows an admin, the audience regression-19's owner note
draws the line at.

### Verification (hand-off wave)

From `companion/` with `.venv\Scripts\python.exe -m pytest`:

- tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_the_relink_answer_the_editor_reads_has_a_real_plural[1-...] -> fails on the wave-1 source ("1 Resolve clip(s) relinked"), passes now
- tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_the_relink_answer_the_editor_reads_has_a_real_plural[3-...] -> fails on the wave-1 source, passes now
- tests/test_bug_hunt_2026_09_11b_comp_sync.py::test_the_refused_half_of_the_relink_answer_is_still_reported -> fails on the wave-1 source, passes now (the failed tail must survive the rewording)
- Both runs measured by reverting the one line and re-running, not by reading.
- tests/test_file_moves.py re-run green: its SYNC-102 case asserted the old
  spelling and now asserts the new one (one line, cited).
- `py_compile` clean on file_moves.py.

### OWED TO ANOTHER TERRITORY (hand-off wave)

- none.

### Owner decisions (hand-off wave)

- Only the editor-visible sentence was converted. `apply_move`'s "N proxy
  file(s) with it" strings stay as they are: they are the dashboard-side
  `detail`, the same audience the comp-app ledger left alone.
