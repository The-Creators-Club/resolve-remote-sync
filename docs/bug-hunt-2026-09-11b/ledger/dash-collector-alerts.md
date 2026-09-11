## The collector's own alarms told the truth about everything but themselves (CR-256, 2026-09-11)

The 2026-09-11 fix pass rewired four of the self-diagnosis paths and each one
landed about three quarters of itself: a silence spelled with a call that
mutates, a liveness flag with one threshold on a fleet that has two shapes, a
keep-list rebuilt from the rows the same pass deletes, and a restore that
refuses a walk it cannot trust while the preview it is chosen from still
prints the numbers that walk invented.

### CR-256a (dash-collector-alerts-2 / regression-2) - a machine on a personal project stopped reaching the RED backstop - FIXED (alerts.py)

CR-241 taught `_check_out_of_tree` to say NOTHING about a machine whose open
project is not one of the tree's, unless it had already raised that subject.
It spelt the test as `if ctx.name(who) not in ctx.open_alert_subjects(...)`,
and `Ctx.name` is not a getter: it ADDS the subject to `ctx.named`.
`_check_red_unexplained` is the last kind in the registry and reports only
machines no other check named, so the one backstop that turns "green while
dead" into a message went quiet for exactly the machines this check had
decided to be quiet about. An editor with a personal project open and lanes
RED for three hours was reported by nobody. The fix asks the question without
naming: the raw `who` against the open-subject set, with `ctx.name` left where
it was, on the line that only findings which are actually emitted reach.
Test: `test_a_quiet_out_of_tree_machine_can_still_reach_the_red_backstop`,
with the other direction (an already-raised subject stays named and quiet)
beside it.

### CR-256b (dash-collector-alerts-1, the alerts half) - a Syncthing-less dashboard called its own healthy collector STOPPED - FIXED (alerts.py)

`collector_stale` is the age of the newest `poll_runs.started_at` against a
fixed 180 s. A deployment with no `syncthing_url` runs `SYNCTHING_FREE_KINDS`
alone - prune 3600 s, invariants 900 s, alerts 600 s - so the newest start
there is ALWAYS older than three minutes and the flag is permanently True. A
vendor or zero-touch dashboard, before Syncthing is configured, put "The
server's background collector has not completed a cycle" on PROBLEMS THE
SERVER FOUND within ten minutes of booting, counted it in the topbar's red
chip and mailed it every day. `_check_collector_stale` now derives the
threshold this site can actually meet (`_stale_after_seconds`: two cadences of
the quickest kind that runs, never below the constant) and re-asks the
question against it before raising anything. A collector that has genuinely
stopped on such a site still raises within twenty minutes. The stored flag
itself, which the home page and `/api/v1/health` also read, is db.py's and is
OWED to dash-db below.

### CR-256c (dash-collector-alerts-8) - the duplicate liveness query is gone - FIXED (alerts.py)

Two builders fixed dash-collector-alerts-3 in two places with the same SQL:
`db.fetch_collector_status` derives the flag from `MAX(started_at)`, and
`alerts._collector_started_recently` re-ran that query against the same
constant, so the branch it guarded could never change the verdict. One extra
full-table aggregate per pass, and two thresholds to keep in step. Deleted;
what is in its place asks the opposite question (CR-256b) and only on the
sites where the stored threshold is meaningless.

### CR-256d (dash-collector-alerts-3) - the truncated-invariant keep-list survived exactly one pass - FIXED (invariants.py)

An invariant broken on 45 subjects reports the first 20, and CR-241 kept the
previously-stored broken subjects in the keep-list so the cap could not close
the notices for the other 25. But the keep-list is built from
`db.broken_invariants`, i.e. from `invariant_results`, and
`db.record_invariant_result` runs a few lines above and DELETES every subject
row a BROKEN pass did not name. From the second pass the stored set is only
the 20 currently visible; by the third window, the notices for the first
twenty are closed as "this has cleared" while all 45 are still broken, which
is the mistake the hunk's own comment is written against. `_TRUNCATED_CARRY`
now holds, per invariant, the broken subjects the cap has hidden - the union
of what the ledger held and what earlier truncated passes carried, minus what
this pass named, capped at `MAX_CARRY_SUBJECTS` - and is dropped the moment
the invariant answers OK or a whole BROKEN verdict. A module global on
`mount_status`'s rule (one process, one app), so a container restart still
loses it: the durable half is OWED to dash-db.
Test: `test_a_truncated_invariant_keeps_its_hidden_subjects_past_pass_two`
(three windows over 45 subjects).

### CR-256e (dash-collector-alerts-4) - the mount registry replayed a boot verdict over a newer one - FIXED (mount_status.py)

`recheck` stashes the pre-degrade verdict and replays it when the root comes
back, and `_STATE` is not its own: the ytdl feature gate rewrites that entry
from a request thread whenever `[features] youtube_download` flips. Root goes
away, gate records "disabled", root comes back, `recheck` puts "mounted" back
on a page that answers 404 to every request - and `_check_feature_mounts`
clears the notice saying so, because `ytdl._record` short-circuits on "same
status" and never re-asserts itself. The restore now only replaces a verdict
that is still the DEGRADED one this function installed; anything else drops
the stash and leaves the newer verdict alone.
Test: `test_a_verdict_written_while_a_root_was_away_is_not_overwritten`, with
the ordinary restore pinned beside it.

### CR-256f (dash-collector-alerts-5) - the registry lock was held across a filesystem probe - FIXED (mount_status.py)

The `is_dir` per recorded root ran with `_LOCK` held. It is cheap on a local
bind mount and not cheap on a hard NFS/CIFS mount whose export has hung rather
than gone - the exact case res-fleet-2 was written for - where it blocks in
the kernel; the collector thread then parked holding the registry and every
reader queued behind it, including `/api/v1/health` and the nav, i.e. the page
an admin opens to find out why. `recheck` now snapshots the roots and verdicts
under the lock, probes with no lock held, and re-takes it to apply - skipping
any entry another thread rewrote while the probe ran, since a verdict from now
beats one planned from a reading taken before it.
Test: `test_the_registry_is_readable_while_a_root_is_being_probed` (the probe
holds until a second thread has taken `snapshot()`, bounded by a timeout).

### CR-256g (dash-collector-alerts-7) - the restore refused a walk the preview still put a number on - FIXED (recovery.py)

CR-241 made `restore_into_quarantine` refuse when either walk hit
`MAX_SCAN_FILES`, because a truncated LIVE walk classifies every file it never
reached as missing. `preview_restore` has the identical defect and is where
the owner DECIDES: it still returned "18,402 files missing, 4.1 TB", almost
all of it present, with `truncated: True` as the only hint, and then the
button 409'd. A truncated preview now withholds the counts entirely and
carries the refusal's own sentence in `note` (plus `counts_unavailable`), with
the numeric keys kept as zeros because the template does arithmetic on them -
which also hides the restore form, correctly, since the restore would refuse.
The template line that still prints "0 file(s) missing" beside that note is
OWED to dash-mounts-ui.
Test: `test_a_preview_that_stopped_early_shows_no_counts`, with the untruncated
preview pinned beside it.

### CR-256h (regression-25 / res-fleet-4) - a half-hour relay outage deleted the week's report - FIXED (alerts.py)

res-fleet-4 stopped a failed send from retiring a slot and bounded the retries
with `MAX_SEND_ATTEMPTS_PER_SLOT = 3`. The alerts cycle runs every 600 s, so
three attempts cover about twenty minutes: an SMTP relay down 07:55 to 08:40
on a Monday spent the budget and the week's report was gone, not late - the
outcome the finding was raised about. The ceiling is now a BACKOFF
(`SEND_BACKOFF_SECONDS`, 10 min then 1 h then 6 h since the last attempt, for
the weekly report and the daily heartbeat alike), so a sink that comes back
inside the slot still delivers, and a dead sink costs about five SMTP timeouts
a day rather than one per cycle.
Test: `test_a_sink_outage_over_the_weekly_slot_delays_the_report_not_deletes_it`.

### CR-256i (dash-collector-alerts-6) - NOT A BUG, pinned (alerts.py)

The finding says a vendor-default site now writes three failed heartbeat rows
a day. It cannot: `heartbeat_due` has returned False on
`alerts_sink == none` since CR-155..164 (`999b3e3`), above the attempt gate,
so no heartbeat row is written on such a site at all. No change; a test pins
the gate, because removing it is exactly what the finding describes.
Test: `test_a_site_with_no_sink_writes_no_heartbeat_rows_at_all`.

### Verification
All in `dashboard/tests/test_bug_hunt_2026_09_11b_dash_collector_alerts.py`,
run with the dashboard venv:
- `test_a_quiet_out_of_tree_machine_can_still_reach_the_red_backstop` -> fails at f1eeb42, passes now
- `test_a_syncthing_less_site_whose_collector_is_turning_is_not_stopped` -> fails at f1eeb42, passes now
- `test_the_duplicate_collector_liveness_query_is_gone` -> fails at f1eeb42, passes now
- `test_a_truncated_invariant_keeps_its_hidden_subjects_past_pass_two` -> fails at f1eeb42, passes now
- `test_a_verdict_written_while_a_root_was_away_is_not_overwritten` -> fails at f1eeb42, passes now
- `test_the_registry_is_readable_while_a_root_is_being_probed` -> fails at f1eeb42, passes now
- `test_a_preview_that_stopped_early_shows_no_counts` -> fails at f1eeb42, passes now
- `test_a_sink_outage_over_the_weekly_slot_delays_the_report_not_deletes_it` -> fails at f1eeb42, passes now
- `test_a_site_with_no_sink_writes_no_heartbeat_rows_at_all` -> passes at f1eeb42 too (CR-256i is a pin, not a fix)
Also green, unchanged: `test_alerts.py`, `test_invariants.py`,
`test_recovery.py`, `test_mount_status.py`,
`test_bug_hunt_2026_09_11_dash_collector_alerts.py`,
`test_bug_hunt_2026_09_03_dash_collector.py` (224 passed).

### OWED TO ANOTHER TERRITORY
- dash-db: `dashboard/src/ccsync_dashboard/db.py`: `fetch_collector_status`: derive the `collector_stale` threshold from the cadences this deployment actually runs (only `SYNCTHING_FREE_KINDS` run without a `syncthing_url`, and the quickest of those is 600 s against a 180 s constant), or gate the flag on `syncthing_url` the way `_check_nas_engine` is gated; the alert is safe without it (CR-256b), but the home page's collector panel and `/api/v1/health` still read the raw flag as STOPPED on a Syncthing-less site. Dashboard-only, no deploy ordering.
- dash-db: `dashboard/src/ccsync_dashboard/db.py`: `record_invariant_result`: take a `truncated: bool = False` and skip the "DELETE the subject rows this pass did not name" when it is set, exactly as a non-verdict already does; `invariants.run_cycle` would then pass `truncated=result.get("truncated")` and `_TRUNCATED_CARRY` could be deleted. Until then the carry is in-process only and a container restart loses the hidden subjects. Dashboard-only, no deploy ordering.
- dash-mounts-ui: `dashboard/templates/partials/recovery.html` (the `recovery_preview` block, around line 141): when `recovery_preview.counts_unavailable` is true, print `recovery_preview.note` instead of the "N file(s) missing / N different / N the same" line, which now reads "0 file(s) missing" on a folder this server could not walk. The counts are already zeros and the restore form is already hidden, so the page is safe without the change. Dashboard-only, no deploy ordering.

### Owner decisions
- The send backoff ladder is 10 minutes, 1 hour, 6 hours (CR-256h). That is at most about five SMTP timeouts a day on a dead sink, and a relay that comes back before 15:00 on a Monday still delivers that week's report. A tighter ladder delivers sooner and costs more timeouts.
- A truncated preview withholds its counts rather than labelling them (CR-256g). The alternative - keep the numbers and print "these are not the whole picture" - leaves a number on the page that is wrong by orders of magnitude, and the restore refuses anyway.
- `MAX_CARRY_SUBJECTS = 200` bounds how many hidden broken subjects one invariant carries between passes (CR-256d). Past that the notices for the oldest hidden subjects can still close.


### Hand-off wave

The OWED lines wave 1 routed here. Two are new alert kinds for conditions the
companion and the boot loader have been reporting to a dashboard that read
neither; one is a leftover alarm that outlived what it was about; one closes
the "two rules for one question" that CR-110's belt was quietly holding up; one
is the registry half of a probe another territory needs.

#### CR-256j (regression-11 / comp-ytdl-jobs-3) - the media sidecar's cause reached nobody - FIXED (alerts.py)

comp-ytdl-jobs-3 landed its companion half in 0.9.71: which of
ffmpeg/ffprobe/deno failed, why, and how many checks in a row, all carried in
`sync_guard.ytdlp.sidecar`. On the dashboard only the pydantic model was
added. `api._store_ytdlp_state` swallowed the block whole into the `ytdlp:`
meta JSON and NO READER EXISTED - no `ALERT_KINDS` row, no render, nothing in
`GET /api/v1/jobs/{id}/why`. A Mac editor whose sidecar install fails on an SSL
CA problem reports `capabilities.ffmpeg = false`; the admin queues a
`proxy-480p` job, `why` answers `no_capable_machine`, and the whole fleet
picture says only that the machine is not capable - which reads as "nobody set
that computer up". The cause was in exactly one place, that editor's own tray,
which is the audience the finding was raised about.
`_check_media_sidecar_failed` is now an `ALERT_KINDS` row REGISTERED WITH ITS
WRITER (`media_sidecar_failed`, warn), naming the machine, the tools and the
companion's own cause sentence. `consecutive_failures >= 2`, not the first
failure: the installer retries and one miss on a flaky network heals itself on
the next daily check. An ABSENT sidecar block (a companion below 0.9.71) is
silence, never "it is fine".
Tests: `test_a_failing_media_sidecar_reaches_the_alerts_page`, with the single
failure and the too-old companion pinned beside it.

#### CR-256k (res-fleet-3, the alerts half) - a container booting the image over an applied tree said so to nobody - FIXED (alerts.py)

dash-mounts-ui-8 moved the boot counter below `check_tree` so an
environment-shaped refusal ("DASH_RELEASE_PUBKEYS is not set") stops counting
against a good bundle. Its neighbour: a PERMANENT refusal no longer accumulates
either, so it never reaches the two boots that produced a revert with a
sentence on the Packages page. An image update that changes `/venv/.runtime-id`
leaves the applied 0.7.43 tree unbootable, the container runs the image's older
code on every restart for ever, and the page still names 0.7.43 as current. The
only evidence was a stderr line in the container log and `source: "image"` in
`status()`; nothing in alerts, notices or invariants read `running_source` or
`reverted_reason`. `_check_code_not_applied` (`code_not_applied`, error) is the
registry row with its writer: `source == "image"` AND `current.json` naming a
version different from the one running. It reads `running_source` and the
`current.json` file directly rather than `dashboard_update.status()`, on the
`_ytdl_health` rule - there is no app object on the collector thread, and
status() would pull the verified feed records for two facts that are a
`sys.path` check and one small file read. It carries
`revert_refused_reason`, which select_code_root now writes, when it is there. A
checkout, a `volume` source, an image that has caught up and an unreadable
`current.json` are all silence.
Tests: `test_a_container_booting_the_image_over_an_applied_tree_is_reported`,
`test_the_applied_tree_answering_is_not_a_finding`,
`test_a_current_json_this_server_cannot_read_raises_nothing`, and
`test_both_new_kinds_are_registered_with_their_writers` (the row, the writer
identity and the weekly report's "checked and found nothing wrong" line, for
both new kinds - a registered kind with no writer was a prior build's own bug).

#### CR-256l (comp-ytdl-jobs-1, the dashboard side) - a refusal an admin had already cleared stayed lit - FIXED (alerts.py)

`_check_upgrade_refused` fired on any stored `upgrade_refused_version`, with no
bound. The companion re-stamps `refused_at` every time it turns an offer down
and reports every heavy tick, so a live refusal is minutes old; an OLD stamp
means the opposite, that nothing is being offered and refused any more. On
companions 0.9.65..0.9.71 the standing refusal only ever cleared by taking a
LATER offer, which a machine already running the current build is never given -
so an admin who published 0.9.65 as a rollback, watched the fleet refuse it and
put the newer build back left `[ REFUSING 0.9.65 ]` and this alert lit on every
machine for the life of each tray process, with the alert's own action text
("publish a build that computer will accept") describing the move that had just
failed to clear it. 0.9.72 clears it from a reply with no offer; the fleet will
hold older builds for months, so the row also ages out here at
`UPGRADE_REFUSED_STALE_SECONDS = 24 h`. A machine that is merely switched off
ages out too, which is right: `machine_silent` owns that.
Tests: `test_a_refusal_nobody_is_restamping_stops_alarming`, with the
re-stamped refusal still alarming beside it.

#### CR-256m (dash-db-4) - the enforce cycle now asks for the enforce view - FIXED (collector.py)

`db.fetch_machine_selections(for_enforce=True)` is named after this cycle and
this cycle did not pass it: `_run_enforce` read the ADMIN view (which keeps a
wired machine's own rows so the tick grid still has a button to clear them) and
dropped wired machines further down its own function on CR-110's separate
`base_pairs`/`base_editors` belt. Two rules for one question, agreeing only
because the belt happens to exist, with the db docstring itself warning that an
edit to the belt or a new consumer written from it brings the CR-110/B16 shape
back. The read now asks the same question `notices._check_plan_without_share`
and `invariants._check_plan_has_share` ask. THE BELT STAYS: it is what kept the
shape away while the two rules were apart, and a flag is not a reason to remove
a latch. No behaviour change today, by construction - that is what the belt
was for.
Test: `test_the_enforce_cycle_asks_for_the_enforce_view` (the real cycle
against the fake Syncthing, asserting the flag on the real call).

#### CR-256n (dash-mounts-ui-b-1, the registry half) - a mount may name a file as its witness - FIXED (mount_status.py)

`recheck` probed each recorded root with `os.path.isdir`. A bind mount that
goes away LEAVES ITS MOUNT POINT BEHIND, so for a mount with no directory of
its own inside that root the probe can never see the failure it was written
for: `/music-data` holds `music.db` and nothing else the music mount creates,
and `MUSIC_PROXIES_DIR` is a separate bind outside the root. `record_root` now
takes `witness=""` - the path actually probed - and `recheck` probes EXISTENCE,
so a file is a legal witness; recording a file under the old probe would have
reported every healthy deployment as degraded, which is worse than the bug. The
degraded sentence still names the ROOT: the admin has to be told which mount is
gone, not which file this server happened to stat. The argument is optional and
`recheck`'s probe parameter keeps its position, so every existing caller and
test is unchanged; passing the witness from music and ytdl is dash-mounts-ui's
half, below.
Tests: `test_a_mount_may_name_a_file_as_its_witness`, with the witness-less
caller pinned beside it.

#### CR-256o (dash-collector-alerts-1, the second look) - NOT DONE, and why - (alerts.py)

The hand-off asked `_stale_after_seconds` to compare against
`db.collector_stale_bound` as well, as "the other way the false positive
fires". By the time it was read, dash-db's wave-1 fix had already made
`db.fetch_collector_status` compute the stored flag against exactly that bound,
with the same 180 s floor. Re-running it in the alert would be
dash-collector-alerts-8 in its purest form: a second query, of the same rows,
against the same threshold, that can never change the verdict the first one
reached - the duplicate this very ledger deleted eight hours earlier. What is
left in `_stale_after_seconds` is the half `collector_stale_bound` cannot
reach, because it is not in the data: a container whose `poll_runs` hold no
REPEAT of any kind yet, where the observed bound falls back to the floor and
only the CONFIGURED intervals say what the site can meet. The docstring now
says so at the code site. Wave 1's three
`test_a_syncthing_less_site_*` tests cover the surviving half.

### Verification
Hand-off wave, all in
`dashboard/tests/test_bug_hunt_2026_09_11b_dash_collector_alerts.py`, run with
the dashboard venv:
- `test_a_failing_media_sidecar_reaches_the_alerts_page` -> fails at f1eeb42 (no such kind), passes now
- `test_one_failed_sidecar_check_is_not_yet_a_finding` -> pins the 2-failure floor
- `test_a_companion_too_old_to_send_a_sidecar_block_is_silent` -> pins "absent is not fine"
- `test_a_refusal_nobody_is_restamping_stops_alarming` -> fails at f1eeb42, passes now
- `test_a_refusal_that_is_being_restamped_still_alarms` -> the other direction
- `test_a_container_booting_the_image_over_an_applied_tree_is_reported` -> fails at f1eeb42 (no such kind), passes now
- `test_the_applied_tree_answering_is_not_a_finding` -> the four silent shapes
- `test_a_current_json_this_server_cannot_read_raises_nothing` -> "could not ask" is not an alarm
- `test_both_new_kinds_are_registered_with_their_writers` -> fails at f1eeb42, passes now
- `test_a_mount_may_name_a_file_as_its_witness` -> fails at f1eeb42 (record_root took no witness), passes now
- `test_a_mount_with_no_witness_still_probes_its_root` -> passes at f1eeb42 too: it pins that the optional argument did not change the ordinary caller
- `test_the_enforce_cycle_asks_for_the_enforce_view` -> fails at f1eeb42, passes now

27 passed in that file. Also green, unchanged, and covering every module
touched: `test_alerts.py`, `test_mount_status.py`, `test_collector.py`,
`test_bug_hunt_2026_09_11_dash_collector_alerts.py`,
`test_bug_hunt_2026_09_03_dash_collector.py` (164 passed), plus the mount half
of `test_bug_hunt_2026_09_11b_dash_mounts_ui.py` (13 passed), which exercises
`mount_status.recheck` with a real filesystem and is the one other territory's
file the probe change could have broken.

### OWED TO ANOTHER TERRITORY
- dash-mounts-ui: `dashboard/src/ccsync_dashboard/music.py` (~457-461): `mount_status.record_root("music", str(music_config.DATA_ROOT), witness=str(music_config.DATA_ROOT / "music.db"))`, and replace the comment block that says the witness "needs `mount_status.recheck` to probe existence" - it does now. Same offer for `ytdl.py` (~704) if that root has no directory of its own. Dashboard-only, no deploy ordering; the registry half is already in and is harmless without it.
- dash-db: `dashboard/src/ccsync_dashboard/db.py`: `fetch_machine_selections` docstring, the paragraph beginning "THE ENFORCE CYCLE ITSELF DOES NOT PASS IT (dash-db-4, 2026-09-11)": it does now (`collector._run_enforce`, hand-off wave). The two rules are one; CR-110's belt is kept deliberately as a latch, not as the rule. Comment only.
- dash-api / dash-release-jobs / dash-mounts-ui: the other three surfaces regression-11 asked for are still theirs - the `ytdlp.sidecar` cause beside `cap_ffmpeg` on Settings -> JOBS, and in `GET /api/v1/jobs/{id}/why`'s `no_capable_machine` explanation. The alert now carries it to the Alerts page and the mail, so the fleet is no longer silent about it either way.
- The three wave-1 OWED lines above (db.py's collector_stale threshold, `record_invariant_result(truncated=...)`, and the `recovery.html` counts line) are unchanged and still owed.

### Owner decisions
- `UPGRADE_REFUSED_STALE_SECONDS = 24 h` (CR-256l). A refusal that is really being made is re-stamped within minutes, so a day is generous; the cost is that a machine switched off for two days with a real refusal goes quiet here, where `machine_silent` picks it up instead.
- `MEDIA_SIDECAR_MIN_FAILURES = 2` (CR-256j). One failed daily check is a flaky network; alerting on the first would put a warn on the Alerts page for something that heals itself overnight.
- `code_not_applied` is an ERROR, not a warn (CR-256k). The fleet is running a build the studio believes it replaced, and every restart repeats it: that is the same severity class as the collector having stopped.
- The two OPTIONAL hand-off items are DECLINED: a `feed_record_rejected` notice kind and a `client_shares_unreadable` notice kind both belong in `db.NOTICE_KINDS`, which is dash-db's file, so neither could be registered WITH its writer from this territory in this wave - and a registered kind with no writer is exactly the bug the rule exists to prevent.
