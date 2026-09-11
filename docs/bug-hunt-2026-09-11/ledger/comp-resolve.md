## The companion's Resolve half, 2026-09-11 (CR-236)

Bug hunt 2026-09-11, territory comp-resolve: six findings from
`hunters/comp-resolve.md` plus res-companion-2, which the verifier ruled is
one change with comp-resolve-4. Nothing here is user-reported; all seven were
found by reading, and the Timeline Cards pair is latent (`cards_agent` is off
everywhere), which is the best time to fix it.

### comp-resolve-1 - one slow read shrank the read size for the whole rest of the file, and there was no way back up - FIXED (`fixer.py`, `copy_with_progress`)

RES-14 made the copy's read size adaptive: a read that took longer than
`POLL_MAX_SECONDS` (0.5 s) halved the next one, floor `MIN_CHUNK_BYTES`
(64 KB), so [ CANCEL ALL ] is answered inside a read rather than inside a
chunk. That halving was the ONLY writer of `read_size` after initialisation,
so it was monotonically non-increasing for the life of the file. The
realistic trigger is the case the change was written for: the FIRST read of a
Google Drive or OneDrive placeholder blocks while the file hydrates, so a
40 GB camera original was ratcheted on read #1 and then copied to the end at
the smaller size, long after the source had become fast - with one `report()`
and therefore one UI publish per read. `read_size` now grows back towards
`min(POLL_CHUNK_BYTES, chunk_size)`, doubling after
`GROW_AFTER_FAST_READS` (4) CONSECUTIVE reads that finished inside a quarter
of the budget. Several, never one: a link sitting either side of the budget
would otherwise oscillate, and the cancel latency the ladder exists for is
what would pay. A link that stays slow still ratchets down to 64 KB and stays
there, which is the property RES-14 bought.

### comp-resolve-2 - CONSOLIDATE counted a rehearsal as files and bytes copied in - FIXED (`consolidate.py`)

RES-15 flipped `fixer.fix_clip`'s dry run from `ok: False` to `ok: True,
dry_run: True` and taught `popup.summarize_fix_results` to read the new flag.
`consolidate.run_consolidation` is the OTHER caller of `fix_clip` and was not
taught - the same twin-miss shape as UI-5 (2026-08-11), whose comment sits
four lines from the defect. With `fixer_dry_run` on (a supported mode with a
tray switch, `settings_window._rehearsal_mode`), tray > COPY THIS PROJECT'S
MEDIA IN credited every rehearsed file's `size` to the bar, made the ETA
nonsense and finished on "69 copied in" about a run that copied nothing - and
the rehearsal mode exists precisely so an admin can trust that screen. A
`dry_run` result no longer advances `batch_done`, `fixed` counts only real
copies, and the published block carries its own `rehearsal` count beside
`fixed`/`skipped`/`failed`. `count_copied()` / `count_rehearsed()` are
exported so the toast and the upload gate can share the answer instead of
re-deriving it from `ok` a third time; see OWED below for that half.

### comp-resolve-3 - the Timeline Cards refusal lost its actionable half at the dashboard's 255-character cap - FIXED (`timeline_cards_role.py`)

`CardsAgentIn.detail` is `max_length=255` and `_BoundedSectionIn` truncates
rather than rejecting, so the dashboard stores the first 255 characters
silently. The standalone-agent refusal was 247 characters BEFORE RES-7's
`describe_process(found)` was appended, so the fleet grid - where the admin
looks - rendered "... will pick the page up on its own within a minute.
Found: python.e", and RES-7's whole reason for existing ("the refusal used to
name a command line and nothing else, so 'stop it' meant 'find it yourself'")
was invisible. The sentence now LEADS with the process, so what gets cut is
constant advice rather than the pid, and the companion truncates DELIBERATELY
at `DETAIL_MAX_CHARS` instead of letting the wire choose the character: the
process description is elided in the MIDDLE (`_elide`), because a command
line's two useful halves are the image name at the front and the script plus
its arguments at the back with a long interpreter path between them.
`_note_loop_end`'s 300 and `report_block()["detail"]` (which carries
`load_engine`'s and `check_contract`'s long refusals) are capped at the same
number. The dashboard's side of the cap is not touched here.

### comp-resolve-4 + res-companion-2 - a role whose loops died was never restarted, and a start that half-succeeded leaked a live engine - FIXED (`timeline_cards_role.py`)

One change, because either fix alone is worse than neither. `supervise_now()`
short-circuited on `if self._threads: return True`, and nothing ever clears
that list: a role whose push and pull loops had both died held two dead
Thread objects for ever, so the RES-7 watchdog answered "running" every 60 s
while `health()` correctly reported `stopped`. The report was honest and the
recovery was not, and the editor's phone showed a dead page until somebody
restarted the tray - the one refusal in this file that did not self-heal.
Separately, `_start` constructed the engine, called `engine.start()`, and only
recorded it in `self._engine` AFTER `make_tunnel_client`, which calls another
repo's `AgentClient` positionally: anything raised in that window left a
started engine nothing held a reference to, `_start_guarded` swallowed it, and
the watchdog started another one a minute later, for ever. An hour of that is
60 engines sweeping the media pool through `CardsBridge`, which is exactly the
"one machine, one Resolve client" breach this module exists to prevent.

Now: `supervise_now` (and `_start`) test LIVENESS, not list length; the
restart path goes through `_clear_dead()`, which empties `_threads`, drops
`_client`, clears `_loop_error` and stops the old engine before another is
started; `_start` records the engine BEFORE anything that can raise, builds
the client before `engine.start()` and stops the engine on any failure in
between; `stop()` stops the engine too, which it never did; and a start that
FAILS (a raise, never a refusal) counts towards `MAX_START_FAILURES` (5),
after which the watchdog stops re-entering and says so once. An explicit
`start()` - the editor, or a companion restart - resets that counter, and a
refusal still gets re-asked for ever, which is the point of RES-7.

### comp-resolve-5 - a journal tmp orphaned by a kill was never swept - FIXED (`resolve_journal.py`)

`_tmp_path` writes `<name>.json.tmp.<pid>.<tid>` and its docstring claimed "a
tmp that is left behind is unlinked by the writer that made it". That is only
true when the WRITE raises: a process killed between `open()` and
`os.replace()` unlinks nothing, and `_sweep`'s `*.json` / `*.drp` globs do not
match the name. On this codebase a death without a shutdown is routine
(CR-93's `Tcl_AsyncDelete` abort, the 0.9.62 supervisor's relaunch), so one
~1 KB orphan per incident accumulated in the editor's home for ever while
`docs/RESOLVE_EDIT_SAFETY.md` told their admin everything older than 60 days
is swept. `SWEPT_SUFFIXES` now carries `*.json.tmp.*` on the same retention
cutoff, and the docstring says what is true.

### comp-resolve-6 - "Resolve went away" was logged as "the script server has its host now" - FIXED (`resolve_bridge.py`)

`connect()` called `_note_starting(None)` for the ABSENT phase, which is the
same call the READY path makes, and `_note_starting` had only two outcomes.
So a bridge in the CR-68 launch window that went STARTING -> ABSENT, i.e.
Resolve quitting or dying mid-launch, logged "resolve: script server has its
host now - connecting (held off for 12.3s)" immediately before not connecting
to anything. CR-68 diagnoses are read out of that exact line in a diagnostics
bundle, and it said scripting had recovered at the second it went away.
`_note_starting` takes a third outcome (`ready=False`) and logs "Resolve went
away during its launch window after 12.3s - there is no script server now and
nothing has connected (CR-68)". The held-off line and the recovery line are
unchanged.

### dash-release-jobs-6 - the `/agent/state` push now names its machine - DONE (`timeline_cards_role.py`, `call()`)

Owed to the dash-release-jobs builder, whose side stopped trusting the
agent's self-asserted `name` and derives the machine from the editor plus
`body.get("machine")`. `TimelineCardsRole.call()` adds `machine` (the same
hostname `machine_state` and the report carry) to the `state` body only; the
engine's own `name` is still sent, unchanged, and `token` is still stripped.
The field is OPTIONAL in both directions: an older dashboard ignores it, and
a dashboard that wants it falls back the way it did before, so neither side
has to deploy first.

### Verification

All in `companion/tests/test_bug_hunt_2026_09_11_comp_resolve.py` unless said
otherwise.

- `::test_one_slow_read_does_not_shrink_the_whole_rest_of_the_file` -> fails at 40f931a, passes now (comp-resolve-1)
- `::test_a_link_that_stays_slow_still_ratchets_down_and_stays_there` -> passes at 40f931a and now (the property the grow-back must not undo)
- `::test_consolidate_does_not_count_a_rehearsal_as_copied_in` -> fails at 40f931a, passes now (comp-resolve-2)
- `::test_a_real_copy_is_still_counted`, `::test_run_consolidation_reports_what_a_rehearsal_did` -> fail at 40f931a, pass now (comp-resolve-2)
- `::test_the_process_to_close_is_inside_the_first_255_characters` -> fails at 40f931a, passes now (comp-resolve-3)
- `::test_a_long_detail_is_truncated_here_rather_than_on_the_wire` -> fails at 40f931a, passes now (comp-resolve-3)
- `::test_a_role_whose_loops_died_is_restarted_by_the_watchdog` -> fails at 40f931a, passes now (comp-resolve-4)
- `::test_a_running_role_is_still_not_restarted` -> passes at 40f931a and now (the property the liveness test must not break)
- `::test_a_start_that_fails_after_engine_start_stops_that_engine` -> fails at 40f931a, passes now (res-companion-2)
- `::test_the_watchdog_does_not_become_an_engine_factory` -> fails at 40f931a, passes now (res-companion-2)
- `::test_stop_lets_go_of_the_engine` -> fails at 40f931a, passes now (res-companion-2)
- `::test_an_orphaned_journal_tmp_is_swept` -> fails at 40f931a, passes now (comp-resolve-5)
- `::test_resolve_dying_in_its_launch_window_is_not_logged_as_a_recovery` -> fails at 40f931a, passes now (comp-resolve-6)
- `::test_a_real_recovery_still_says_so` -> passes at 40f931a and now
- `::test_the_state_push_carries_this_machine` -> fails at 40f931a, passes now (dash-release-jobs-6)
- `tests/test_timeline_cards_role_health.py::test_the_refusal_names_the_process_and_what_to_close` -> edited for the new word order (it pinned the old sentence); it now asserts the process comes BEFORE the advice

Run: `cd companion; .venv\Scripts\python.exe -m pytest
tests/test_bug_hunt_2026_09_11_comp_resolve.py tests/test_timeline_cards_role.py
tests/test_timeline_cards_role_health.py tests/test_fixer.py
tests/test_consolidate.py tests/test_resolve_journal.py
tests/test_resolve_bridge_launch_window.py tests/test_popup.py
tests/test_resolve_edit_safety.py tests/test_no_em_dash.py -q` -> 506 passed
(507 with the dash-release-jobs-6 case added afterwards).

### OWED TO ANOTHER TERRITORY

- `companion/src/ccsync_companion/app.py:3561-3589` (comp-app): the consolidate
  toast still computes "copied in" as `len(results) - len(failures) -
  len(skipped)` off the same `ok` flag, so with `fixer_dry_run` on it will say
  "Copy & upload finished (69 copied in)" about a rehearsal. The counts are
  now available without re-deriving them: `consolidate.count_copied(results)`
  and `consolidate.count_rehearsed(results)`, and the toast should say
  "Rehearsal: nothing was copied" the way `popup.summarize_fix_results` does.
  The progress block published from `run_consolidation` carries `rehearsal`
  alongside `fixed`/`skipped`/`failed` for the same purpose. My half is safe
  without it: the bar, the ETA and the published counts no longer credit a
  rehearsal, so the only remaining lie is that one toast sentence.
- `companion/src/ccsync_companion/app.py:3610` `_consolidate_upload_phase`
  (comp-app): a rehearsal that copied nothing should not run a lane A push.
  Gate it on `consolidate.count_copied(results) > 0`.
- `dashboard/src/ccsync_dashboard/api.py:7716` `CardsAgentIn.detail` and
  `:7733` `JobsGateIn.detail` (dash-api-jobs): the 255-character cap that
  truncates rather than rejecting. Nothing is owed for correctness - the
  companion now fits its own sentences under 255 deliberately - but if the
  cap is ever raised, `timeline_cards_role.DETAIL_MAX_CHARS` is the one
  constant to raise with it, and `db.cap_cards_*` would need checking.
- `companion/src/ccsync_companion/proxy_gen.py:1169-1174` is in my territory
  but the hunter's concern is the reporter's size guard (report-size
  territory): `report()` splices `**self._brakes()`, adding a nested `reasons`
  dict of three ~150-character sentences under a comment demanding
  scalars-only. Left alone deliberately - it was not one of my findings and
  the judgement belongs to whoever owns the reporter's payload budget.
- `KNOWN_BUGS.md:12566-12570` (orchestrator): the RES-14 entry says
  "`chunk_size` stays the unit of PROGRESS reporting". It is not: the code
  reports once per READ and its own comment says so. Ledger text, not code.

### Owner decisions

- The grow-back needs FOUR consecutive reads inside a quarter of the budget
  before it doubles (`fixer.GROW_AFTER_FAST_READS`). Fewer would recover
  faster on a link that hiccuped once; more would be safer for cancel
  latency. Four costs at most ~2 MB at the reduced size per step.
- A rehearsal now leaves the consolidate progress bar at 0 % for the whole
  run, because nothing was copied. That is honest but it is a visible change
  for anyone who has used `fixer_dry_run`: the alternative (credit the bytes,
  label the screen a rehearsal) would need the popup's copy, which is another
  territory.
- The watchdog's ceiling is 5 consecutive FAILED starts and then it waits for
  an explicit `start()`, i.e. a companion restart. The alternative is an
  exponential back-off that never gives up; I chose the ceiling because a
  start that has raised the same way five times is a broken checkout, and a
  machine quietly retrying for ever is how 60 engines happened in the first
  place.
- An orphaned journal tmp is swept on the same 60-day retention as the
  journals. The hunter suggested a shorter cutoff (a day) since nothing ever
  needs an old tmp; 60 days keeps one rule in one place, and the files are
  ~1 KB.
