# CR-292 - the rehearsal progress screen, both surfaces - FIXED in repo 2026-09-18 (companion-ui, 2026-09-18b mediums)

CR-283P (comp-ui-5) gave FIX ALL a screen an admin can trust while
`fixer_dry_run` is on. It missed the FIRST file of every such run, and the
CONSOLIDATE window entirely. Both are fixed here, in `popup.py`.

### CR-292A (comp-ui-1) - the first file of a rehearsal still said "Copying ... 0 B of 12.7 GB" - FIXED (companion/src/ccsync_companion/popup.py)

`perform_fix_all` learned `rehearsing` from the first `dry_run` ANSWER, but a
file's progress keys are published BEFORE `call_fix_clip` runs. So file 1 of
every rehearsal was published with `rehearsing` false and the real
`file_bytes_total`/`batch_bytes_total`, and with a single dead link - the
common FIX ALL case - that was the whole run: the word "Copying", a byte total
that will never be reached, and two bars that never move. The loop now SEEDS
`rehearsing` before the first publish from `fixer.dry_run_default()`, the same
cached `fixer_dry_run` answer `fixer.fix_clip` itself reads (one resolution per
process, so the screen cannot disagree with the run), and only when the caller
injected no `fix_clip_fn` - an injected copier decides its own dry-run, and the
first-answer latch stays its fallback. `_FIX_CLIP_DEFAULT` exists because the
bound default arg and `fixer.fix_clip` are two different objects once a test
monkeypatches the module attribute. Test:
`test_the_first_file_of_a_rehearsal_is_already_checking` (the real-fixer path,
`popup.call_fix_clip` stubbed so Resolve is never reached) and
`test_an_injected_fix_clip_still_decides_its_own_rehearsal`.

### CR-292B (comp-ui-4) - the CONSOLIDATE window drew a whole rehearsal as a copy - FIXED (companion/src/ccsync_companion/popup.py)

`consolidate.run_consolidation` publishes the real byte totals and no
`rehearsing` key, and its renderer is `ProgressWindow._tick`, which called
`format_file_progress` with no `rehearsal=` and drew its batch bar off bytes.
An 800 GB COPY THIS PROJECT'S MEDIA IN rehearsal therefore sat at `File 7 of
412: 0 B of 800 GB done` with "Copying" beside every clip. `_tick` now asks the
new `ProgressWindow._rehearsing(info)`: an explicit `rehearsing` key wins (so
the publisher can start sending one later with no second mechanism), a phase
with its own `headline` is never a rehearsal (the lane A upload's bytes are
real, and a rehearsal never reaches it - `app.py` skips the upload when nothing
was copied in), and otherwise it falls back to the same cached `fixer_dry_run`
answer every copy in this process obeys. When rehearsing, the file line reads
`Checking "x"`, the batch line drops its byte total and the batch bar counts
CLIPS, exactly as `_render_progress` does for FIX ALL. Tests:
`test_the_consolidate_window_says_checking_on_a_rehearsal`,
`test_a_real_consolidate_copy_is_untouched`,
`test_the_upload_phase_headline_is_never_a_rehearsal` - all against stand-in
widgets, since `ProgressWindow.__init__` builds no Tk (CR-93 is not in play).

### Verification
- comp-ui-1: `tests/test_bug_hunt_2026_09_18b_companion_ui.py` - 5 passed; with
  the seed neutralised, `test_the_first_file_of_a_rehearsal_is_already_checking`
  fails (`rehearsing` False, `file_bytes_total` 1024).
- comp-ui-4: same file; with `_rehearsing` reduced to the key lookup,
  `test_the_consolidate_window_says_checking_on_a_rehearsal` fails with
  `Copying "A001_C012.braw": 0 B of 11.8 GB`.
- `tests/test_popup.py` 134 passed with the new file; the CR-283P test
  (`tests/test_bug_hunt_2026_09_18_companion_core.py -k rehearsal`) still
  passes and now says why it asserts on `mid[-1]`.

### Not fixed
- Nothing from this group's list. (`consolidate.py`'s own publish is OWED
  below, not required: the renderer fix stands alone.)

### OWED TO ANOTHER GROUP
- `companion/src/ccsync_companion/consolidate.py` (unassigned this wave):
  `run_consolidation` should publish the rehearsal explicitly rather than lean
  on the renderer's fallback - seed `rehearsing = fixer.dry_run_default()` when
  no `fix_clip_fn` was injected, latch it on the first `dry_run` outcome, add
  `rehearsing=rehearsing` to the per-file publish at `consolidate.py:471-473`
  and send `file_bytes_total`/`batch_bytes_total` as 0 while it is true (the
  shape `popup.perform_fix_all` already has). `ProgressWindow._rehearsing`
  takes an explicit key in preference to its fallback, so that change is
  additive and needs no second change here.

### Deploy order
- Companion-only, no wire. Any companion build carries both halves; a
  dashboard rollback is not involved.

### Owner decisions
- None.
