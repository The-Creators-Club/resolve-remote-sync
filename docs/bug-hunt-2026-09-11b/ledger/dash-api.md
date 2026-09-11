## A rename took a machine off the fleet grid, the rollback button walked past the gate, and five of sync_guard's sub-sections still dropped what they were sent (CR-255, 2026-09-11)

### CR-255a (wire-2) - a project rename 422'd every report that machine sent afterwards - FIXED (`dashboard/src/ccsync_dashboard/api.py`)

`RepathEventIn.at` was declared `str | None` and the producer,
`companion/sync/repath.py`'s `RepathLedger.record`, writes `float(self._now())`
- an epoch float. `_BoundedSectionIn`'s before-validator truncates and clamps;
it does not coerce types, and pydantic v2 will not turn a float into a string.
`sync_guard` is deliberately NOT one of ReportIn's tolerant sections, so the
whole report failed validation. One rename by an admin, and from the moment the
companion (0.9.71, shipping tonight) repathed that folder, every 30 s report
from that machine was rejected 422 for the life of the ledger entry: no lane
state, no breaker or halt state on the grid, and - because the reply is the only
channel back - no `commands.halt`, no `commands.upgrade`, no
`commands.file_moves`, no lane B resume. The editor saw nothing at all. The
companion-side regression test that was supposed to pin this fed the model an
ISO string the producer never writes. `at` is `float | str | None` now, the two
spellings an older reader may hold; `max_length` cannot live on the Field
(pydantic applies it to the float arm and raises), so the string arm is bounded
by a validator on the same truncate-rather-than-reject terms as every other cap
in the file. The test loads the COMPANION's `repath.py` from source and feeds
`record(...)`'s actual output through `ReportIn`.

### CR-255b (wire-3) - the same section sent seven keys and declared four, so the first rename of the week would have put four "nothing is wrong" lines on the SYS-3 banner - FIXED (`api.py`)

comp-app-2 flipped `_BoundedSectionIn` to `extra="allow"` and taught
`_nested_extra_keys` to walk list items precisely so a dropped sub-key is NAMED
on the fleet page. The same afternoon comp-sync-4 added a section whose items
carry `id`, `slug`, `note` and `moved` undeclared, and `trash` has carried an
undeclared `skipped` since the breaker prune guard was written. As soon as
wire-2 was fixed, every machine that had had a rename would have logged four
undeclared keys a day and rendered them on the banner that exists to catch a
real dropped section. All five are declared now rather than dropped: `slug` is
the project, `moved=False` is "this machine could not follow the rename" (which
nothing on the server could previously see) and `skipped` is "the breaker is
down, so nothing was pruned".

### CR-255c (dash-api-1) - the rollback button was a sixth door into "make current", and it walked past the gate - FIXED (`api.py`)

CR-239's dash-api-3 fix added `db.set_current_package(...)` straight into
`roll_fleet_back` - the one call that function's own docstring forbids, and one
of the five doors `package_store.make_current_refusal` says it gates. The
in-line justification was "`ever_current` is the evidence this one already
earned", but nothing on that path read `ever_current`; `set_current_package`
only sets it. So the REL-1 soak gate, the UX-9 unsigned-binary confirmation and
the REL-4 `requires_dashboard` ordering check were all bypassed for any
published, non-retracted version an admin typed into `?to=`:
`POST .../0.9.66/roll-fleet-back?to=0.9.64` made an unsigned 0.9.64 current
with no confirmation, every companion then refused the offer's signature, and
the whole platform stopped updating with nothing on any page saying why. The
re-pointing goes through `make_current_refusal` now. On a refusal the FAN-OUT
still happens - the recall is the half that reaches the machines - `current` is
left where it is, and the refusal is named in the answer and the audit row
rather than raised, because a rollback that delivers nothing is how a recall
turns into a fleet nobody can reach. `ever_current` still passes the gate on its
own, so dash-api-3's re-pointing is not undone for a real rollback.

### CR-255d (dash-api-7) - the rollback re-pointed `current` for the whole platform and named nobody - FIXED (`api.py`)

`_upgrade_info` offers a version that DIFFERS, not a newer one (equality, by
design), so re-pointing `current` at the rollback target reaches machines that
were never on the build being rolled off: the base rig after a `-AllowDirty`
hotfix, or a machine that took a targeted push, starts being offered a
downgrade nobody asked for. The response, the audit row and the log line now
carry `newer_machines`, the machines on that platform running something ABOVE
the target, with the build being rolled off excluded - those are the point of
the exercise, not a surprise. A version that cannot be compared is left out
rather than guessed at.

### CR-255e (dash-api-2) - five of sync_guard's sub-models still dropped undeclared keys in silence, and 422'd rather than truncated - FIXED (`api.py`)

comp-app-2 switched `_BoundedSectionIn` to `extra="allow"` so the walker could
NAME a dropped sub-key, and switched exactly one model. `lane_b_breaker`,
`halt`, `trash`, `skipped_exists` and `removal_overrides` stayed plain
`BaseModel`s - which is to say the three latches an editor's safety depends on,
and the very sections whose silently-dropped fields comp-sync-1 and comp-sync-15
were raised about the same afternoon. A model with `extra="ignore"` has an empty
`model_extra` by construction, so the detector was blind to exactly the
recurrence the fix pass was patching; and without `_bound_rather_than_reject`, a
value over a declared cap (`BreakerIn.editor_reason`, 1000 chars of free text)
422'd the whole report instead of truncating, which is the SYS-3 shape. All five
subclass `_BoundedSectionIn` now, and
`test_every_sync_guard_subsection_truncates_rather_than_rejects` walks
`SyncGuardIn.model_fields` so the next model added cannot be silent by default.

### CR-255f (dash-api-4, wire-5) - suspending an editor mid-job burned forty minutes of GPU and then threw the work away - FIXED (`api.py`)

dash-api-6 put the account bar on `_require_fleet_caller`, which gates the job
heartbeat and result routes as well as claim. The companion's runner treats
ONLY 410 as "this job is no longer ours, stop"; a 403 is read as a blip. So a
machine whose owner was suspended mid-transcode ran the job to completion,
wrote into the shared vault (SMB, which the bar does not reach), posted a result
that was refused, and the dashboard re-queued the same job onto a second machine
to do it all again - neither the editor nor the admin told anything. The bar has
three answers now, one per door: 403 on claim (no new work under a barred name),
410 on the heartbeat (the only status the runner acts on, so the child is
stopped within a heartbeat interval), and the result door is not gated at all,
because it only RETIRES work already claimed and refusing it is what threw the
work away.

### CR-255g (security-1) - "suspended means the same everywhere" stopped at api.py - FIXED IN PART (`api.py`)

dash-api-6's own docstring says suspension "meant one door only: /report ... One
line per gate makes the word mean the same thing everywhere", and added the line
to four api.py doors. The package door never asked, and the three mounted fleet
APIs (broll, music, ytdl) could not: `_refuse_barred_account` is private to
api.py and those apps have no notion of a suspended account at all. DCORE-4
revokes neither the session nor the `cce1.` token, so a suspended freelancer's
laptop kept a working credential and could still push indexed clips, re-score a
music library, claim a ytdl download into the shared tree - and keep itself
upgraded. `account_bar_reason(settings, conn, editor)` is public now (raising is
the caller's business; those apps answer in their own shapes, and it fails open
on a database error like the predicate it wraps), and
`GET /api/v1/companion/package/{platform}/{version}` asks it for an
editor-bound token. The shared token identifies nobody and is unchanged, and so
is an admin session. The three mount halves are OWED below.

### CR-255h (wire-1, res-companion-1 dashboard half) - the companion's crash-resume state had no spelling on the wire - FIXED (`api.py`)

The companion's file-move ledger writes an `applying` INTENT row before the
rename and clears it after, so a tray killed in between (a CR-93 abort, a
reboot, an upgrade swap) starts again holding one. `FileMoveResultIn.state` was
`done|failed|retrying|blocked`, and a MISSING state means "answered, stop
asking": the redelivered command was answered `ok=false` with no state,
`mark_file_move_applied` wrote `applied_at`, and a crash mid-move became a
PERMANENT failed move with the resume - proxy siblings, the Resolve relink -
never run. `applying` is accepted now and stored as `retrying`, the one state
`db.py` spells that records the attempt WITHOUT retiring the command. THE
DASHBOARD DEPLOYS FIRST: a companion sending `applying` to a dashboard below
0.7.44 fails the Literal, and `file_moves_applied` is not a tolerant section.

### CR-255i (dash-api-6) - `resolve_health_detail` carried unbounded undeclared keys out of the validator, against its own comment - FIXED (`api.py`)

`_BoundedSectionIn`'s comment asserted "nothing reads `model_extra` except that
reporting, so an undeclared key is still not stored". Not true of the VALUE:
`model_dump()` on an `extra="allow"` model includes the extras, and
`_bound_to_field_caps` bounds declared fields only, so a 200 KB string posted
into `sync_guard.resolve_health` rode out of the validator, through the
flattened dict and into two db writers - each of which happens to filter it by
an allow-list of its own. "Happens to" is not a bound. `_declared_dump` is what
the three blob columns (`resolve_health_detail`, `ytdlp`, `youtube_import`) use
now, and the comment says where the real bound is.

### CR-255j (dash-api-5) - a machine with no platform was "unknown" here and "windows" in `rollout_status`, so the ship gate could never clear it - FIXED (`api.py`)

`ReportIn.platform` is optional, so a `machine_state` row can carry NULL.
`db.rollout_status` reads that as `windows`; `_rollout_platforms_block` read the
same row as `unknown`, and `tools/ship_gates.ps1` then looked for a channel
covering the platform key `unknown`, never found one, and emitted a straggler on
every ship that no build an admin could publish would ever clear. One coercion,
`or "windows"`, the same one the counter it is compared against uses.

### CR-255k (tests-3) - an authorization assertion that could never fail - FIXED (`dashboard/tests/test_selection_api.py`)

`assert client.get("/api/v1/selection/jsmith").status_code == 401 or True` in
`test_auth_matrix` was the only line asserting that a signed-in editor cannot
READ another editor's sync plan. The `or True` is gone; the gate is correct
today, so this was a hole rather than a live bug.

### Verification
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_a_real_repath_event_does_not_422_the_whole_report -> fails at f1eeb42, passes now (wire-2)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_the_model_keeps_the_float_and_still_bounds_a_string -> fails at f1eeb42, passes now (wire-2)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_every_key_the_repath_ledger_writes_is_declared -> fails at f1eeb42, passes now (wire-3)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_the_prune_guards_skipped_key_is_declared -> fails at f1eeb42, passes now (wire-3)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_every_sync_guard_subsection_truncates_rather_than_rejects -> fails at f1eeb42, passes now (dash-api-2)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_a_new_breaker_key_is_named_rather_than_dropped -> fails at f1eeb42, passes now (dash-api-2)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_a_long_breaker_reason_truncates_rather_than_422ing_the_report -> fails at f1eeb42, passes now (dash-api-2)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_resolve_health_detail_carries_only_declared_keys -> fails at f1eeb42, passes now (dash-api-6)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_a_machine_with_no_platform_is_counted_the_way_rollout_status_counts_it -> fails at f1eeb42, passes now (dash-api-5)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_a_rollback_cannot_make_an_unsigned_build_current -> fails at f1eeb42, passes now (dash-api-1)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_a_rollback_to_a_build_that_has_been_current_still_repoints -> pins dash-api-3's fix against dash-api-1's gate (green both sides)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_the_rollback_names_the_machines_it_would_downgrade -> fails at f1eeb42, passes now (dash-api-7)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_a_suspended_editors_running_job_is_told_to_stop -> fails at f1eeb42, passes now (dash-api-4 / wire-5)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_a_suspended_editors_finished_job_can_still_be_retired -> fails at f1eeb42, passes now (dash-api-4)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_the_account_bar_is_importable_by_the_mounted_apps -> fails at f1eeb42, passes now (security-1)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_a_suspended_editors_machine_cannot_keep_itself_upgraded -> fails at f1eeb42, passes now (security-1)
- tests/test_file_moves.py::test_a_crash_mid_move_is_answered_applying_and_keeps_the_command -> fails at f1eeb42 (422 on the Literal), passes now (wire-1)
- tests/test_selection_api.py::test_auth_matrix -> the assertion can fail now (tests-3); green today
- tests/test_bug_hunt_2026_09_11_dash_api_jobs.py::_publish_rows -> its two rollback tests now publish SIGNED rows, because dash-api-1's gate refuses the re-pointing of an unsigned one

### OWED TO ANOTHER TERRITORY
- dash-mounts-ui: `ui.py`: `partial_admin_roll_fleet_back`: pass `settings=request.app.state.settings` into `api.roll_fleet_back` (it defaults to None, which makes `make_current_refusal` read the DEFAULT soak minutes rather than this site's when `meta` has no override), and render the response's new `current_refused` / `newer_machines` on the Packages page - the JSON route answers them and the htmx door shows an error only on an exception; dashboard deploys alone, no companion side.
- dash-mounts-ui: `ui.py`: the home page (`ui.py:649`) and `/partials/queue` (`ui.py:925`) call `api.build_queue_view(conn, editor)` with no machine, so dash-api-4's per-machine `resolve_project` / `root_*` fix (CR-239) is still unreachable from the only template that renders them (`partials/fix_root.html`): thread the `?machine=` the assignments grid already uses (or the person's single machine) into both calls and assert on the rendered sentence through the HTTP route (dash-api-3). Dashboard only.
- dash-collector-alerts: `alerts.py`: an `ALERT_KINDS` row WITH its writer reading `ytdlp.sidecar.ok/cause/consecutive_failures` off the `ytdlp:` meta blob api.py already stores (regression-11 / comp-ytdl-jobs-3). The report model and the storage are done here; no reader exists anywhere. Dashboard only.
- dash-mounts-ui + dash-release-jobs: render that sidecar cause beside `cap_ffmpeg` on the jobs machine list, and in `GET /api/v1/jobs/{id}/why`'s `no_capable_machine` explanation (regression-11's second half). Dashboard only.
- broll / music / ytdl-web: `broll/web/app/routes_fleet.py`, `music/web/musicweb/routes_fleet.py`, `ytdl/web/ytdlweb/routes_fleet.py` (or the three `_fleet_stamp` helpers in `dashboard/src/ccsync_dashboard/{broll,music,ytdl}.py`, which is the one place all three already share): after `api.resolve_companion_credential` resolves an editor, call `api.account_bar_reason(settings, conn, editor)` and refuse when it answers (security-1). Dashboard deploys alone; nothing on the companion changes.
- comp-ytdl-jobs: `companion/src/ccsync_companion/jobs_runner.py`: `_heartbeat` must treat 401/403 as terminal for the current job the way 410 is (stop the child, record cancelled, do not retry), and surface the refusal on the tray the way `reporter`'s APP-1 notice does (wire-5). The dashboard half answers 410 now, so a companion of ANY version already stops - this is belt and braces for the claim door and for an older dashboard. Dashboard first either way.
- dash-db: `db.py`: a first-class `applying` state in `file_move_targets` if the companion is meant to report it distinctly - api.py stores it as `retrying` today, which gives the behaviour (the command stays live) but not the word on the project page (wire-1). Dashboard deploys before any companion that sends `applying`.
- comp-sync (optional): `sync/repath.py` may also stringify `at` on the wire; it does not need to, since `RepathEventIn` takes the float now, and the dashboard is the half that lets 0.9.71 machines report at all.

### Owner decisions
- On a `make_current_refusal` refusal the rollback still asks every machine to move and leaves `current` alone, returning the refusal in `current_refused` rather than raising it. The alternative (refuse the whole call) would mean an admin recalling a bad build gets nothing at all until they clear the gate. If you would rather the button refuse outright, it is one branch in `roll_fleet_back`.
- The job RESULT door is now outside the account bar on purpose: a suspended editor's machine may still retire work it already holds. The claim door and the heartbeat are what stop it.
- Noticed while running the suite, NOT mine and NOT touched: `db.fetch_collector_status` raises `NameError: name 'collector_stale_bound' is not defined` (an unterminated docstring around `db.py:8832`), logged by every notice check. It is another builder's in-flight edit to `db.py`; the gate will fail on it if it is left.

### Hand-off wave

The OWED lines other territories routed to `api.py` (`HANDOFFS.md`,
"## dash-api"). Same numbering: these are further sub-entries of CR-255.

#### CR-255l (res-companion-4, from comp-ytdl-jobs) - the upgrade block's new counter was undeclared, so the banner that catches a dropped section would have named it every day - FIXED (`api.py`)

`upgrade.upgrade_report` sends `state_write_failures` on every report from a
0.9.72 companion (zero is the normal answer, and always sent, so that "cannot
count" and "nothing to count" stay different answers). `UpgradeIn` did not
declare it, and comp-app-2's walker NAMES an undeclared sub-key on the SYS-3
banner - so the fleet's whole population would have put
`sync_guard.upgrade.state_write_failures` on the banner that exists to catch a
section the dashboard is really dropping, daily, for ever. Declared now,
`int | None`, `ge=0`. Nothing stores or renders it yet: the counter is
non-zero only on a machine whose `~/.ccsync/state` is unwritable, which is
APP-5's crash-loop guard reading "first start" for ever, and that is worth an
alert row - OWED below. The test reads the producer's own dict literal out of
`companion/src/ccsync_companion/upgrade.py` with `ast` rather than restating
its keys by hand, which is the wire-2 lesson.

#### CR-255m (dash-db-5, from dash-db) - a locked database turned the Users page into a 500 - FIXED (`api.py`)

CR-240's dash-db-2 made the suspension and archive readers re-raise
`database is locked` rather than answer the empty value. That is right where
the empty answer was a fail-OPEN (the enforce cycle re-sharing folders an
admin had just suspended) and wrong on a page that only RENDERS:
`_build_admin_users_view` called `db.suspended_editors`,
`db.editor_suspension` and `db.fetch_pending_ssh_keys` unguarded, so a lock
during a slow collector write 500'd the whole Users page - the page carrying
[ RESUME ] and the pending-SSH-key approval, i.e. the two buttons the admin
opened it to press, both of them unreachable exactly while something else is
busy. The reads are guarded on their own terms now (`sqlite3.OperationalError`
only, the two groups independently) and answer the empty value plus
`suspensions_unreadable` / `pending_ssh_keys_unreadable`, so the page can say
"could not read this right now" instead of stating as fact that nobody is
suspended and no key is waiting. `assignments._assignments_view`'s
`archived_unreadable` is the same move on the same afternoon. The strip that
renders the two flags is OWED to dash-mounts-ui; until it lands the page
renders as it did before CR-240 rather than 500ing, which is the point.

#### CR-255n (comp-app-2, from comp-app) - a drive left out overnight wrote the same WARNING a thousand times - FIXED (`api.py`)

A `retrying` answer deliberately does not retire the file-move command, so
the move is re-sent on the next report and re-answered, every 30 s, per move,
per machine, for as long as the external drive is out or Resolve holds the
file open. The report handler logged on every `rowcount > 0`, so one editor's
drive pulled overnight with four moves owed wrote thousands of identical lines
and pushed the events an operator reads the next morning out of the log.
The previous answer is read off the row (`_file_move_answer`, a read rather
than state in this process - a container restart must not make the fleet shout
again) and the line is written only when `state` or `detail` CHANGED. A
terminal answer cannot repeat at all, because `mark_file_move_applied` only
matches `applied_at IS NULL`. A read that cannot be made counts as "no
previous answer", i.e. log it: the safe direction for a de-dupe is to say it
twice. comp-app-2's companion half cuts the volume at the source for 0.9.72;
this is what makes the log quiet for the fleet as it is today
(0.9.65..0.9.71), and either side may deploy first.

#### Confirmations (no code change)

- `_require_fleet_caller`'s three doors are as comp-ytdl-jobs asked: claim
  403 (`barred="refuse"`), heartbeat 410 (`barred="gone"`, the only status
  `jobs_runner` acts on), result ungated (`barred="allow"`, because it only
  retires work already claimed). Wave 1 covered the heartbeat and the result;
  a control test for the claim door is added here so the split cannot be
  collapsed by accident.
- `_rollout_platforms_block` already buckets a NULL/blank
  `machine_state.platform` as `windows`, the coercion `db.rollout_status`
  uses (CR-255j, wave 1, with
  `test_a_machine_with_no_platform_is_counted_the_way_rollout_status_counts_it`).
  Nothing to do for server-tools's line.
- DECLINED (one sentence, as the brief allows): the OPTIONAL first-class
  `applying` state for `file_move_targets` is in `db.py`, which is dash-db's
  territory, not mine - it stays OWED below, and `applying` continues to be
  stored as `retrying`, which gives the behaviour without the word.

### Verification (hand-off wave)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_every_key_the_upgrade_report_writes_is_declared -> fails without the field, passes now (res-companion-4)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_the_upgrade_section_names_no_undeclared_key -> fails without the field, passes now (res-companion-4)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_the_users_page_survives_a_locked_suspension_read -> fails without the guard (sqlite3.OperationalError out of the view), passes now (dash-db-5)
- tests/test_file_moves.py::test_a_machine_retrying_the_same_move_logs_once -> fails without the de-dupe (7 lines where 1 is owed), passes now (comp-app-2)
- tests/test_bug_hunt_2026_09_11b_dash_api.py::test_a_suspended_editor_cannot_claim_new_work -> control: the claim door stays 403 while the heartbeat is 410 (green both sides)
- Suites run: tests/test_bug_hunt_2026_09_11b_dash_api.py (20 passed), tests/test_file_moves.py (18 passed), and the three api.py-driven Users-page suites tests/test_admin_users{,_local,_partial_parity}.py (57 passed). py_compile on api.py.

### OWED TO ANOTHER TERRITORY (hand-off wave)
- dash-mounts-ui: `templates/admin_users.html`: render a "could not read this right now" strip when `suspensions_unreadable` or `pending_ssh_keys_unreadable` is true, instead of the empty suspension list and the empty key table (dash-db-5). Dashboard only.
- dash-db: `db.store_upgrade_state`: keep `state_write_failures` on the machine's row so something can read it; the report model declares it now and nothing stores it (res-companion-4). Dashboard only, and harmless until it lands.
- dash-collector-alerts: an `ALERT_KINDS` row WITH its writer for `state_write_failures > 0` ("this machine cannot write its own state, so the crash-loop guard can never fire"), once dash-db stores it. Dashboard only.
- dash-db (still OWED, unchanged from wave 1): a first-class `applying` state in `file_move_targets` if the project page should show the word; api.py stores it as `retrying` today.

### Owner decisions (hand-off wave)
- The file-move de-dupe key is (state, detail) only: a `retrying` answer whose ATTEMPTS went up but whose state and detail did not is no longer logged. The attempt count is on the project page and in the row; the log is for changes. If you would rather see every attempt, it is one tuple in `api.py`.
- `suspensions_unreadable` and `pending_ssh_keys_unreadable` are two flags, not one, because the two reads fail independently and the page has two sections - the same reason DASH-7 split `truenas_error` from `syncthing_error`.
