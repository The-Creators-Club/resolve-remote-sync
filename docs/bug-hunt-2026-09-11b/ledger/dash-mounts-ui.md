## The dashboard's UI, its three mounts and its boot (CR-259, 2026-09-11)

The second hunt of 2026-09-11 read the morning's fix pass (CR-233..CR-248)
rather than the code it changed, and this territory's six findings are all of
that shape: a watchdog that was taught not to blame the bundle and stopped
covering it, a runtime probe that watches the one thing that never goes away,
a revalidation nothing holds alive, and two sentences that say the wrong thing
to the person who has to act.

### CR-259a (res-fleet-2) - the automatic crash-loop revert could revert into a dashboard that can never boot again - FIXED (dashboard/deploy/select_code_root.py)

`dashboard_update.rollback()` refuses a MANUAL rollback whose target knows a
lower database schema than the live database and names the backup to restore
(REL-10). The automatic watchdog revert - the one that runs with nobody
watching - had no equivalent. An OTA tree runs `db.migrate` at the top of its
lifespan, so the database can already be at the NEW tree's schema by the time
the boot fails; `select_code_root` then rewrote `current.json` to the previous
tree (or to the image), whose `migrate()` raises `RuntimeError: database schema
is newer than this build` on every start, uncaught, for ever. The escape hatch
was the thing that closed the hatch, and on an appliance there is then no
dashboard, no rollback page, no `restore_db` and no `/help` - only a shell on
the NAS, which is the one thing a zero-touch deployment is supposed not to
need.

The fix teaches the boot script REL-10's own test, with the image's own
stdlib and nothing imported from the tree being judged: `live_schema_version()`
reads `PRAGMA user_version` from `DASH_DB_PATH` read-only,
`tree_schema_version()` reads the revert target's `manifest.json`
(`schema_version`, written at apply time) or, for the image, parses the highest
step out of the image's own `db.py` the way `image_version()` parses VERSION.
Lower than the live database is a refusal; equal or higher reverts exactly as
before; CANNOT TELL does not refuse, which is REL-10's third answer and the
reason a pre-REL-10 tree still gets its escape hatch. A refusal keeps booting
the applied tree - the only code that can open this database at all - says so
on stderr, and records `revert_refused_reason` / `revert_refused_from` into
`current.json`, which `partials/admin_dashboard_update.html` now renders in its
own banner. The refusal is dropped again on the first boot where the counter is
back to zero, so the banner cannot outlive the problem.

### CR-259b (dash-mounts-ui-b-2, res-fleet-3) - a tree that can never boot stopped counting, so the watchdog stopped covering it - FIXED (dashboard/deploy/select_code_root.py)

CR-243's dash-mounts-ui-8 moved `bump_boot_attempts` below `check_tree` so that
an environment-shaped refusal ("DASH_RELEASE_PUBKEYS is not set") could not
blame a perfectly good bundle. It went one step too far: `check_tree` also
refuses for TREE-shaped reasons - a missing `manifest.json`, a `record.json`
that does not verify, a `runtime_id` that no longer matches the image after a
dependency bump - and `revert()` is reachable only through the counter. A
bundle that can never be selected therefore never reverted: the container
booted the image on every restart for ever while `current.json` went on naming
the applied version, `boot_attempts` rendered 0, `reverted_reason` stayed empty
and the only evidence anywhere was one WARNING per boot in a container log. The
studio believes the fleet is running an update that has never run.

Now the refusal is classified. `ENV_REFUSALS` (plus one marker for "the image's
own verifier could not be imported") are the refusals where the container is
wrong and the bundle is fine, and they are still free; every other refusal
counts, carries its sentence in `boot_attempts.json`, and reaches the same
revert on the MAX_BOOT_ATTEMPTS'th try - with the real reason in
`reverted_reason` rather than "failed to reach a healthy boot", which was never
true of a tree that was never booted. `check_tree` returns the two constants
verbatim so the classifier and the message cannot drift, and a test pins that.

### CR-259c (dash-mounts-ui-b-1, regression-1) - the per-cycle mount probe watched the bind mountpoint, which never goes away - FIXED (dashboard/src/ccsync_dashboard/broll.py)

res-fleet-2's fix in the morning pass has the collector re-probe each mount's
recorded data root every cycle with one `os.path.isdir`. On every shipped
deployment that root is a bind-mount TARGET (`BROLL_DATA_ROOT=/broll-data`),
and a bind mount whose backing export goes away leaves its mount point behind
inside the container - the same mechanism `alerts._check_nas_tree` states in so
many words, which is why IT probes for an entry. So `isdir` answered True in
every failure the re-probe was written for, `mount_status` kept saying
`mounted`, the topbar kept advertising B-ROLL, and every request under it
failed with no notice and no degraded verdict. `_init_broll_storage` also
`mkdir`s that root at boot, so the directory provably exists whatever the host
does.

b-roll now records the `proxies` directory it creates INSIDE the root: still a
directory (the probe is `os.path.isdir`), created on whatever is really mounted
there, and gone with it. Music and ytdl have no directory of their own under
their roots - `/music-data` holds `music.db` and MUSIC_PROXIES_DIR is its own
bind - so their witness has to be the database FILE, which needs
`mount_status.recheck` to probe existence rather than `isdir`. That half is
OWED below; recording a file under today's probe would report every healthy
deployment as degraded, which is worse than the bug. Both call sites carry a
comment saying so.

### CR-259d (dash-mounts-ui-b-3, regression-23) - the stale-while-revalidate write was not held alive - FIXED (dashboard/static/sw.js)

A service worker's lifetime is extended only by the promises handed to
`event.respondWith` and `event.waitUntil`. dash-mounts-ui-5's fix returned the
cached hit immediately and left the revalidating `fetch(...).then(cache.put)`
detached, so the user agent may terminate the worker before the cache write
runs - most likely on exactly the slow, flaky mobile connection the fix exists
for. A CSS hotfix redeployed under an unchanged VERSION then stayed stale
indefinitely, behind a fix that looked applied. The handler now builds a
`stored` promise that settles when the bytes are IN the cache and passes it to
`event.waitUntil` beside the cached response; the no-hit branch still answers
from the network without waiting for the write.

### CR-259e (dash-mounts-ui-b-5) - the uid warning blamed APP_UID for a number it read off /data - FIXED (dashboard/deploy/run.sh)

CR-243's dash-mounts-ui-6 gave the uid advisory a fallback for bind-mount mode,
where `APP_UID` is not in the environment: the expected uid is read off `/data`
instead. The sentence was not branched with it, so on the case the fallback
exists for - a `/data` docker created as root, before
`install_dashboard_app.py`'s chown - the warning told the admin that the
deployment's files are owned by uid 0 "(APP_UID)" and to change compose's
`user:` line to 0, which is the one change that would be wrong. The two
provenances now get two sentences: "(APP_UID)" only when APP_UID was set, and
otherwise "chown /data to <our uid>, or fix `user:` if <that uid> is right".

### CR-259f (dash-mounts-ui-b-6) - an out-of-band error banner lost its button - FIXED (dashboard/static/htmx_errors.js)

htmx fires `htmx:afterSwap` once per settled element, and an out-of-band swap
adds its elements to that same list with the same xhr. The WeakMap fallback
added by dash-mounts-ui-7 deleted its entry on the FIRST of them, so a response
that answers with a main partial plus an `hx-swap-oob` error strip lost the
path on the swap that actually carries the banner, and the refusal stayed two
thousand pixels above the viewport: DUI-6 again for that shape of response. The
entry is no longer deleted; the map is weak and keyed on the xhr, so it dies
with the request anyway.

### Verification
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_mounts_ui.py::test_the_watchdog_does_not_revert_into_a_build_that_cannot_open_the_database -> fails at f1eeb42, passes now
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_mounts_ui.py::test_the_image_is_judged_by_its_own_migration_list -> fails at f1eeb42, passes now
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_mounts_ui.py::test_the_refusal_is_cleared_once_the_applied_tree_boots_healthily -> fails at f1eeb42, passes now
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_mounts_ui.py::test_the_watchdog_still_reverts_when_the_schema_allows_it and ::test_a_target_whose_schema_is_unknown_still_reverts -> the controls: the guard is a refusal, not an off switch (both pass before and after)
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_mounts_ui.py::test_a_tree_shaped_refusal_counts_towards_the_revert -> fails at f1eeb42, passes now
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_mounts_ui.py::test_check_tree_still_returns_the_two_environment_reasons_verbatim and ::test_an_environment_shaped_refusal_is_still_free -> the anti-drift pair for CR-259b
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_mounts_ui.py::test_a_bind_mount_that_goes_empty_is_seen_by_the_broll_re_probe -> fails at f1eeb42, passes now (a real emptied directory, not an injected `is_dir`)
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_mounts_ui.py::test_the_revalidation_is_an_extend_lifetime_promise -> fails at f1eeb42, passes now (the node harness models worker termination and records a cache.put that arrives after it)
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_mounts_ui.py::test_the_uid_warning_blames_the_right_thing_when_it_read_the_number_off_data -> fails at f1eeb42, passes now (the block executed under a real `sh` with `id`/`stat` stubs, not grepped)
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_mounts_ui.py::test_the_uid_warning_still_names_app_uid_when_app_uid_is_what_it_read -> the image-mode control
- dashboard/tests/test_bug_hunt_2026_09_11b_dash_mounts_ui.py::test_an_out_of_band_banner_still_reaches_its_button -> fails at f1eeb42, passes now
- dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py -> 20 passed (its finding-8 test now stubs `check_tree` with the constant check_tree really returns; a paraphrase would have exercised the new tree-shaped branch and pinned nothing)

### OWED TO ANOTHER TERRITORY
- dash-release-jobs: `dashboard/src/ccsync_dashboard/dashboard_update.py`: `status()`: add `"revert_refused_reason": str(current.get("revert_refused_reason") or "")` and `"revert_refused_from": ...` to the `current` dict it builds (it has a fixed key set, so the two keys select_code_root now writes are dropped before the template sees them). The template half is already in and renders nothing while the key is Undefined, so either order is safe; no companion involved.
- dash-collector-alerts: `dashboard/src/ccsync_dashboard/mount_status.py`: `recheck()`: probe EXISTENCE (`os.path.exists`, or `any(os.scandir(root))`) instead of `os.path.isdir`, and give `record_root(name, root, witness="")` a second argument so the degraded sentence can keep naming the ROOT while the probe watches the witness. With that in, `music.py` and `ytdl.py` can record `music_config.DB_PATH` / `<root>/ytdl.db` and CR-259c is closed for all three (b-roll's directory witness works under either probe, so there is no deploy order: dashboard only).
- dash-collector-alerts: `alerts.py` / `notices.py`: res-fleet-3's other half. Nothing anywhere reads `running_source` or `reverted_reason`, so "this container is booting the image while `current.json` names a version" reaches no one but the container log. CR-259b makes that state revert itself after two boots, which is the urgent half; an ALERT_KINDS row for it is still worth having.

### Owner decisions
- The schema guard REFUSES the revert and keeps booting the applied tree, rather than reverting and restoring the `before-<version>` backup automatically. Restoring a database with nobody watching takes the day's reports back to that moment, which is a bigger decision than a builder should make; the refusal is the part that must not wait. If the owner wants the automatic restore too, it belongs beside `dashboard_update.restore_backup` and is a second change.
- CANNOT TELL (a target with no `schema_version` in its manifest, an unreadable database) does not refuse, following REL-10's own rule. The alternative - refusing whenever the number is missing - would make every pre-REL-10 tree unrevertible.

### Hand-off wave

Seven items other builders finished half of and routed here, because the other
half is a template, a mount or a UI call site. One of them (security-1) is the
only door in this wave a stranger can push on.

#### CR-259g (security-1) - a suspended editor's laptop was still stamped by all three mounts - FIXED (broll.py, music.py, ytdl.py)

DCORE-4 revokes no session and no `cce1.` token when an admin suspends an
account, and dash-api-6 closed that gap one door at a time on the dashboard's
own routes. The three MOUNTED fleet APIs were not among them: they cannot reach
`_refuse_barred_account`, had no notion of a suspended account at all, and each
mints `X-CCSync-Fleet-Auth: editor:<name>` from the per-editor token - which is
the whole of what the sub-app authorises a write on. A freelancer who left on
Friday could still claim an ingest batch and push clips into the shared
archive, take a whole-library music re-score, and pull a YouTube download into
the tree, from the laptop nobody collected.

All three now ask dash-api's `api.account_bar_reason` (public for exactly this)
before minting, and WITHHOLD the stamp on a refusal rather than raising: the
sub-app then falls back to its own fail-closed shared-secret compare, which a
`cce1.` token never matches, and each of the three answers in its own shape.
`_account_bar` lives in broll.py beside `_header_value` - music imports it the
way it already imports that - and ytdl has its own, beside the `_credential`
dance it already owns. FAILS OPEN on an unopenable database, like the
predicate itself: a read that cannot answer must never lock a fleet out of its
own archive.

#### CR-259h (dash-api-1) - the rollback button read the DEFAULT soak minutes, and a refusal it earned reached nobody - FIXED (ui.py, partials/admin_packages.html)

`api.roll_fleet_back` takes the re-pointing of `current` through
`package_store.make_current_refusal` now, which reads this site's soak minutes
from `settings`. The htmx twin passed none, so the gate read
`getattr(None, "release_soak_minutes", DEFAULT)`: a site that had turned the
gate off - `[releases] soak_minutes = 0`, the documented escape - was refused
the re-pointing the JSON route performs, `current` stayed on the build being
rolled off, and every machine that took the older build was offered the bad one
again on its next report. Unattended where `auto_update` is on.

The button passes `settings=request.app.state.settings`, and the refusal is now
RENDERED: it is deliberately not raised (the fan-out is the half a recall is
about), so nothing anywhere said the channel had been left where it was. One
strip above the packages table, on its own key rather than the error banner,
because this is not a failed action.

#### CR-259i (dash-api-4) - the per-machine queue view was unreachable from the only two templates that render it - FIXED (ui.py, fleet.html, partials/fix_root.html)

dash-api-4 made `build_queue_view` about ONE COMPUTER - which is what the panel
under it claims to be, since "where does FIX ALL put the files for the project
open in Resolve" has no answer for two computers at once. The home page and
`/partials/queue` both called it with no machine, so leso's MacBook page still
named whatever was open on the iMac and the fix reached nobody.

Both callers read `?machine=` through `_queue_machine`, which accepts only a
name in `db.machines_of` - a typo, or a bookmark taken before a rename, is the
PERSON's view and never an empty one that reads as "nothing is ticked on that
computer". The poll URL carries it, or the panel would silently become about
the other machine ten seconds after it was opened, and `fix_root.html` grew the
chips that switch between them (plain links, because the choice has to survive
the poll) plus the computer's name in the sentence.

#### CR-259j (dash-collector-alerts' hand-off) - "0 file(s) missing" from a preview that could not count - FIXED (partials/recovery.html)

A snapshot comparison that exceeds `MAX_SCAN_FILES` withholds its counts and
returns zeros with `counts_unavailable` and a sentence. The template printed
the zeros: "0 file(s) missing from the server now, 0 that are there but
different, 0 the same", to the person deciding whether they need a restore at
all. The counts line is conditional now, `[ CANNOT SAY ]` takes its place, and
the refusal's own sentence is what is read.

#### CR-259k (dash-db-5's hand-off) - an unreadable archived list read as "nothing is archived" - FIXED (admin_assignments.html)

dash-db-5 separated the archived read so a table this database cannot answer
for stops taking the whole page down. What was left was an empty list, and an
empty list on that page says the one thing it does not know. A strip says so,
and says the projects above are unaffected.

#### CR-259l (broll-5's hand-off) - a client-folder ledger locked for two seconds at boot hid the whole archive - FIXED (broll.py)

`_init_broll_storage` called `client_folders.ensure_schema()` bare. It is a
BOOT path, and its caller marks the whole /broll mount DEGRADED on an exception
- nav link hidden, home page saying every /broll request will fail - which
since broll-2's request-path guard is simply false: the archive serves every
search fine without a client-folder ledger, and the migration takes
`BEGIN IMMEDIATE` now, so a ledger locked for the seconds the container starts
is a real possibility. It calls `ensure_schema_best_effort` through `getattr`,
because `BROLL_WEB_SRC` can point at a checkout older than that function.

#### CR-259m (regression-11's hand-off) - the ffmpeg sidecar cause on the jobs machine list - FIXED (partials/admin_jobs.html)

dash-release-jobs landed the reader (`jobs.sidecar_notes` / `sidecar_cause`),
which folds the cause into the per-machine sentence and puts it on its own
`sidecar_cause` key so a page need not parse a sentence apart. Settings -> JOBS
chips it now: "this tool's installer failed" and "this computer was never set
up" are the same empty answer without something that tells them apart, and the
chip is what makes the line scannable in a list of eight machines.

#### CR-259n (dash-mounts-ui-b-1, closing CR-259c) - music and ytdl now name a witness that goes away with their export - FIXED (music.py, ytdl.py)

CR-259c fixed b-roll and recorded the other two as OWED, because a file witness
needed `mount_status.recheck` to probe existence rather than `os.path.isdir`.
dash-collector-alerts shipped that half (and `record_root(name, root,
witness=)`), so music records `music_config.DB_PATH` and ytdl `ytdl.db`: the
root is a bind-mount TARGET whose mount point survives its export, and neither
mount creates a directory of its own inside it. The degraded sentence still
names the ROOT - the admin has to be told which mount is gone, not which file
this server stat'ed.

### Verification
- dashboard/tests/test_hand_off_2026_09_11b_dash_mounts_ui.py::test_a_suspended_editors_laptop_is_not_stamped_by_the_broll_mount -> fails before, passes now (with `api.account_bar_reason` stubbed back to None the claim is answered 200 and stamped `editor:editor2`, which is the pre-fix world)
- dashboard/tests/test_hand_off_2026_09_11b_dash_mounts_ui.py::test_a_suspended_editors_laptop_is_not_stamped_by_the_music_mount -> fails before, passes now
- dashboard/tests/test_hand_off_2026_09_11b_dash_mounts_ui.py::test_a_suspended_editors_laptop_is_not_stamped_by_the_ytdl_mount -> fails before, passes now (each of the three claims ONCE while in good standing first, so a test that passed by refusing everything would fail on its own control)
- dashboard/tests/test_hand_off_2026_09_11b_dash_mounts_ui.py::test_the_rollback_button_reads_this_sites_soak_minutes -> fails before, passes now
- dashboard/tests/test_hand_off_2026_09_11b_dash_mounts_ui.py::test_the_page_says_when_current_was_left_where_it_was -> fails before, passes now
- dashboard/tests/test_hand_off_2026_09_11b_dash_mounts_ui.py::test_the_queue_panel_can_be_asked_about_one_computer and ::test_the_home_page_queue_can_be_asked_about_one_computer -> fail before, pass now (each asks about BOTH computers: `reported_at` is clamped to the server's clock on receipt, so "the newest wins" is a tie inside a test and pinning it would be pinning a coin toss)
- dashboard/tests/test_hand_off_2026_09_11b_dash_mounts_ui.py::test_an_unknown_computer_is_not_taken_as_a_machine -> the control for the same fix
- dashboard/tests/test_hand_off_2026_09_11b_dash_mounts_ui.py::test_a_preview_that_could_not_count_says_so_instead_of_zero -> fails before, passes now (through the real POST route, with recovery.preview_restore returning the refusal shape recovery.py builds)
- dashboard/tests/test_hand_off_2026_09_11b_dash_mounts_ui.py::test_an_unreadable_archived_list_says_so -> fails before, passes now (the real page, with `db.fetch_archived_projects` raising OperationalError, so assignments.py's own except is what is exercised)
- dashboard/tests/test_hand_off_2026_09_11b_dash_mounts_ui.py::test_a_locked_client_ledger_does_not_degrade_the_whole_broll_mount -> fails before, passes now
- dashboard/tests/test_hand_off_2026_09_11b_dash_mounts_ui.py::test_the_jobs_page_names_the_ffmpeg_sidecar_cause -> fails before, passes now (a real report carrying the sidecar block, an idle machine with ffmpeg false, so the CAPABILITY refusal is the one that fires)
- dashboard/tests/test_hand_off_2026_09_11b_dash_mounts_ui.py::test_the_music_mount_notices_its_export_going_away and ::test_the_ytdl_mount_notices_its_export_going_away -> fail before, pass now (the database file is really deleted and the mount point really left behind; re-recording the root with no witness reproduces the old empty answer)
- Also run, because they read what I changed: test_broll_fleet_stamp, test_music_fleet_stamp, test_broll_mount, test_music_mount, test_ytdl_mount, test_home_layout, test_no_em_dash, test_admin_assignments, test_bug_hunt_2026_09_11_dash_api_jobs, test_jobs_machines, test_packages, test_recovery, test_upload_only, test_mount_status, and both earlier dash-mounts-ui files -> all green. `py_compile` on ui.py, broll.py, music.py, ytdl.py.

### OWED TO ANOTHER TERRITORY (hand-off wave)
- dash-release-jobs: `dashboard/src/ccsync_dashboard/dashboard_update.py`: `status()`: STILL OWED from wave 1 - add `revert_refused_reason` / `revert_refused_from` to the `current` dict it builds (fixed key set, so the two keys select_code_root writes are dropped before the template sees them). Dashboard only, either order.
- dash-collector-alerts: `alerts.py` / `notices.py`: STILL OWED from wave 1 - an ALERT_KINDS row for "this container is booting the image while `current.json` names a version" (`running_source` / `reverted_reason` / `revert_refused_reason`). CR-259b makes that state revert itself after two boots, which was the urgent half.
- Nothing NEW is owed: every hand-off item landed whole.

### Owner decisions (hand-off wave)
- A suspended editor's machine is refused by WITHHOLDING the fleet stamp rather than by a 403 at the gate. It is the smaller change and the fail-open rule survives it, but it means the sub-app answers with its own wording, not a sentence naming the suspension. If the owner wants "your account is suspended" on the editor's tray for these three doors too, that is a refusal in `login_gate` with a companion-visible `detail`, which is dash-core's file and a bigger change.
- The queue panel's computer is chosen with `?machine=` on the URL plus chips in the [ FIX DESTINATION ROOT ] box, shown only to a person with more than one computer. The alternative - defaulting the home page to the computer the browser is sitting on - is not knowable server side, and remembering the last choice per editor is a preference store this page does not have.
