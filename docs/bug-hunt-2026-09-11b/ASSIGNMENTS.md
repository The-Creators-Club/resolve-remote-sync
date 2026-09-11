# Builder assignments, fix pass 2026-09-11b

One builder per territory; the finding ids are headings in `hunters/*.md`
(`grep -rn "^### <id>" docs/bug-hunt-2026-09-11b/hunters/`). "also:" names the
other territories a finding's Where: touches - fix your side, record the rest
as OWED. Aliases are the same defect reported by another hunter: read both.

## comp-sync (CR-249) - 9 findings
- comp-sync-b-1 [high] the new abandoned-lane-B latch can be set after the thread has already cleared it, and then nothing ever clears it: proxy download is off fo  (aliases: res-companion-2, regression-15)
- comp-sync-b-2 [medium] res-companion-1's `applying` intent row is written with `relink_pending=True`, and `pending_relinks()` / `moved_to()` filter on neither `ok`  (also: comp-app)  (aliases: regression-17)
- comp-sync-b-3 [medium] a lane B pass that returns without reaching `_account_pass` leaves `_in_flight_credited` set, and the NEXT pass's deletions never reach the 
- regression-4 [medium] comp-sync-7: the new stale-subpath gate is on the shared lane object, so CONSOLIDATE's proxy pull is silently dropped  (also: comp-app)
- regression-6 [medium] comp-sync-12: the new case-only rename skips the proxy siblings every other move takes with it
- comp-sync-b-4 [low] a failed case-only rename can leave the editor's media file under a `.ccsync-move-<pid>-` name that lane A then uploads to the NAS
- comp-sync-b-5 [low] a fleet halt stops the borrowed folders from being accepted but not the shared asset libraries
- res-companion-3 [low] an in-flight deletion credit that is never reconciled makes the NEXT lane B pass's deletions invisible to the breaker
- security-4 [low] the companion's Syncthing helpers follow redirects while carrying `X-API-Key`

## comp-app (CR-250) - 12 findings
- res-companion-1 [high] the crash-resume for an interrupted file move is unreachable, and the crash now ends as a PERMANENT failed move instead of a retired one  (also: comp-sync, dash-db)  (aliases: wire-1)
- comp-app-2 [medium] the same answer floods the dashboard log once per move per report for as long as the drive is out  (also: dash-api)
- comp-app-3 [medium] the watchdog's hourly ceiling is unreachable: the constants make it dead code, and the two tests that assert it pass on the backoff instead
- comp-app-4 [medium] the clock-skew tolerance comp-app-7 added is missing from the one place the fix says reads those events
- comp-app-6 [medium] "Sync now" runs lane B on a machine where lane B is disabled by config, and names it in the toast
- regression-5 [medium] comp-sync-11: the twin the fix's own comment names, `CompanionApp._relink_moved`, was never converted to `cmp_key`  (also: comp-sync)
- comp-app-5 [low] the hold-off writes a WARNING every tick, so the per-tick spam comp-app-7 removed comes straight back in the same log
- comp-app-7 [low] the consolidate success toast still hides the copied count on the path where nothing was skipped
- comp-app-8 [low] a corrupt machine.json is now permanent, silent and unrepairable
- regression-19 [low] comp-ui-4: the "(s)" ban was extended to two files and app.py still ships four editor-visible plurals
- regression-20 [low] comp-sync-15: the second trash-summary producer still hands out the DEFAULT retention
- res-companion-5 [low] `_file_move_answers` is rebuilt from two threads with no lock, so an answer can be lost or an already-sent one resurrected

## comp-ui (CR-251) - 10 findings
- comp-ui-1 [high] a failed Explorer-restart re-add kills the tray refresh loops for ever  (aliases: regression-7)
- comp-resolve-b-1 [medium] comp-resolve-2's fix landed in consolidate only: FIX ALL still counts a rehearsal as bytes copied  (also: comp-resolve)
- comp-ui-2 [medium] the Explorer-restart re-add freezes the tray for 15.5 s, not the 2.5 s its own comment promises  (aliases: regression-16)
- comp-ui-3 [medium] every relaunch is counted twice, so the "three relaunches an hour" ceiling fires after two
- comp-ui-4 [medium] the "cannot save its safety state" line tells the editor to do the one thing that drops the latch
- comp-ui-5 [low] the Quit-while-copying confirmation is garbled when the batch total is not known
- comp-ui-6 [low] the three new Settings-only advisories are in the tray MENU fingerprint
- comp-ui-7 [low] show_settings can release a lock another window now holds
- regression-12 [low] res-companion-3 is claimed fixed and there is no fix anywhere in the tree  (also: comp-ytdl-jobs)
- regression-21 [low] comp-ui-2: the "second source that does not need a filesystem" is itself a file, written with a silent swallow

## comp-resolve (CR-252) - 5 findings
- comp-resolve-b-2 [medium] clips held by the auto-relink rate limiter can wait for the life of the process, because only a FAILED relink re-arms the watcher  (also: comp-app)
- regression-8 [medium] comp-resolve-4: the cards watchdog still never recovers a role that lost ONE of its two loops
- comp-resolve-b-3 [low] `_elide` can return MORE characters than the cap it is given
- comp-resolve-b-4 [low] an UNKNOWN probe closes the launch window with the "Resolve registered" line
- comp-resolve-b-5 [low] the res-companion-2 regression test passes on a half-reverted fix (or-assertion)

## comp-broll-music (CR-253) - 5 findings
- comp-broll-music-2 [medium] a staged drop that was never run can now never be deleted, and CLEAR FINISHED STAGING still tells the editor to press it  (aliases: regression-9)
- comp-broll-music-3 [low] a clip whose original vanished still uploads its poster, sprite and proxy to the archive, with no row to own them
- comp-broll-music-4 [low] a music track waiting out a result retry publishes "nothing to do" and tears the model down every 15 s
- comp-broll-music-5 [low] the deferred CLAP analysis is never dropped when a batch is cancelled or its lease is lost
- comp-broll-music-6 [low] a non-OSError failure to start the loopback server is neither latched nor recorded

## comp-ytdl-jobs (CR-254) - 7 findings
- comp-ytdl-jobs-1 [medium] the refusal is now sticky FOR EVER: a rollback the admin abandons leaves every machine permanently alarmed, and nothing can clear it  (also: dash-api, dash-collector-alerts)
- comp-ytdl-jobs-2 [medium] the sidecar cause/counter never reaches the report on a YouTube-enabled machine's two commonest failures, so the new tray line can never app
- comp-ytdl-jobs-3 [low] the new `sync_guard.ytdlp.sidecar` block is stored by the dashboard and read by nobody, so the admin half of the finding is still open  (also: dash-api, dash-collector-alerts, dash-mounts-ui)
- comp-ytdl-jobs-4 [low] the new drain-liveness check fires on stderr too, and it runs BEFORE the real-failure check, so it can replace ffmpeg's own error with a gen
- comp-ytdl-jobs-5 [low] the one fix in this territory with no regression test is the one that changed fleet-visible behaviour
- comp-ytdl-jobs-6 [low] `_local_cancel` has no ceiling and is merged ahead of the admin's list, so 16 stale local stops would crowd out a fleet cancel
- res-companion-4 [low] "this machine cannot keep its crash-loop counter" is a log line and an accessor nobody calls

## dash-api (CR-255) - 13 findings
- dash-api-1 [high] the rollback button is a sixth door into "make current", and it walks past the gate  (also: dash-db)
- wire-2 [high] `sync_guard.repath_events[].at` is a float on the companion and a string in the model: every report from a machine that has had a project re  (also: comp-sync, comp-app)
  NOTE: receiver tolerance: RepathEventIn.at float|str|None on the dashboard; comp-sync may ALSO stringify on the wire, but the dashboard change is the fix that lets 0.9.71 machines report
- dash-api-2 [medium] the new undeclared-key walker is blind to the five sync_guard sections where this afternoon's dropped fields actually lived
- dash-api-3 [medium] dash-api-4's per-machine queue fix is unreachable from any page that renders the thing it fixes  (also: dash-mounts-ui)
- dash-api-4 [medium] suspending an editor mid-job throws away the work their machine has already done  (also: comp-ytdl-jobs)
- regression-11 [medium] comp-ytdl-jobs-3: the dashboard half was never built, so the finding's central symptom stands  (also: dash-collector-alerts)
- security-1 [medium] the dash-api-6 "suspended means the same everywhere" gate stops at api.py; the three mounted fleet APIs and the package door never ask  (also: broll, music, ytdl-web)
  NOTE: make the suspended-account predicate importable and record the three mount halves (broll/music/ytdl fleet gates) as OWED; the mounts builders will wire it
- wire-3 [medium] the same section sends seven keys and declares four, and `_nested_extra_keys` now turns that into a daily warning and a SYS-3 banner line  (also: comp-sync)
  NOTE: declare the seven repath keys the companion sends (or make the walker ignore this section)
- wire-5 [medium] dash-api-6's new 403 has no answer in the companion's fleet-jobs error model: a suspended editor's machine keeps running the job and writing  (also: comp-ytdl-jobs)
- dash-api-5 [low] `rollout` and `rollout_platforms` on the same /health answer disagree about a machine with no platform, and the ship gate cannot clear it  (also: dash-db, server-tools)
- dash-api-6 [low] `resolve_health_detail` carries unbounded undeclared keys out of the validator, against its own comment
- dash-api-7 [low] the rollback re-points `current` for the whole platform, not just the machines being rolled back
- tests-3 [low] dashboard/tests/test_selection_api.py assertion shape (see tests.md)

## dash-collector-alerts (CR-256) - 8 findings
- dash-collector-alerts-2 [medium] the out-of-tree silence now also silences the catch-all "red and we cannot say why"  (aliases: regression-2)
- dash-collector-alerts-3 [medium] the truncated-invariant keep-list only survives one pass  (also: dash-db)
- dash-collector-alerts-4 [medium] mount_status restores a stale boot verdict over a newer one the ytdl gate wrote  (also: dash-mounts-ui)
- dash-collector-alerts-5 [low] `recheck()` holds the mount registry lock across a filesystem probe
- dash-collector-alerts-6 [low] the vendor default (no sink) now writes three failed heartbeat rows a day instead of one
- dash-collector-alerts-7 [low] the restore refuses on a truncated walk but the preview it is chosen from still shows the wrong list
- dash-collector-alerts-8 [low] `_collector_started_recently` is dead code: both sides of the same wire were fixed  (also: dash-db)
- regression-25 [low] res-fleet-4: the per-slot attempt ceiling loses the weekly report for an outage longer than about twenty minutes

## dash-core (CR-257) - 8 findings
- dash-core-1 [medium] a `warn` on the EULA task is sticky, so the licence is never accepted once it arrives
- dash-core-2 [medium] the dash-core-6 "other direction" regression test asserts a constant and can never fail
- dash-core-3 [low] the login backoff raises OverflowError once a key passes ~1024 recorded failures
- dash-core-4 [low] APP_UID without APP_GID is written to internal.env but ignored by the reader
- dash-core-5 [low] the /help index re-walks and re-opens the whole docs tree on every admin render
- dash-mounts-ui-b-4 [low] the image build now hard-fails on a document published_docs.py calls best effort
- music-6 [low] `editor:` stamps are rejected for any editor name with a space, silently downgrading to a token mismatch 403
- security-2 [low] the login-gate carve-out for `GET /broll/api/fleet/ingest/batches` outlived the route it was written for  (also: broll)

## dash-db (CR-258) - 7 findings
- comp-app-1 [high] comp-sync-20's "retrying while the drive is out" does not stop the 7 day expiry it was written to stop  (also: comp-app)  (aliases: regression-18)
  NOTE: the dashboard half: exclude state=retrying rows from expire_delivered_file_moves; the companion half already landed
- dash-collector-alerts-1 [high] a Syncthing-less deployment now reports its own healthy collector as STOPPED, for ever  (also: dash-collector-alerts)
- dash-db-1 [high] the per-machine [ UPDATE NOW ] push still cannot deliver a rollback: dash-api-3 landed on the fleet route only  (also: dash-api, dash-mounts-ui)  (aliases: res-fleet-1)
- dash-db-2 [medium] a cancelled job re-queued by an older companion becomes a permanently unclaimable `queued` row that still counts in the queue depth  (aliases: regression-3)
- dash-db-3 [medium] dash-db-3's cap bounds the ROWS but not the WORK: `resolve_marker_includes` is still quadratic in a tampered marker  (also: dash-collector-alerts)  (aliases: regression-22)
- dash-db-4 [low] the enforce cycle, the reader `for_enforce` is named for, does not pass it  (also: dash-collector-alerts)
- dash-db-5 [low] dash-db-2's raise reaches two display-only admin pages, which now 500 on a transient lock  (also: dash-api)

## dash-mounts-ui (CR-259) - 6 findings
- res-fleet-2 [high] the AUTOMATIC crash-loop revert has no schema check, and reverting past a migration is an unrecoverable dashboard  (also: dash-db, dash-core)
- dash-mounts-ui-b-1 [medium] the res-fleet-2 runtime mount probe watches the bind MOUNTPOINT, which never goes away  (also: dash-collector-alerts)  (aliases: regression-1)
- dash-mounts-ui-b-2 [medium] a permanently unbootable code tree is now never reverted, because only a tree that PASSES check_tree is counted  (aliases: res-fleet-3)
- dash-mounts-ui-b-3 [medium] the new stale-while-revalidate does not hold the service worker alive, so the revalidation it was added for can be killed  (aliases: regression-23)
- dash-mounts-ui-b-5 [low] run.sh's new uid fallback blames APP_UID for a number it read off /data
- dash-mounts-ui-b-6 [low] the refusal banner's path is consumed by the FIRST swap of a response, so an out-of-band banner loses it

## dash-release-jobs (CR-260) - 10 findings
- dash-release-jobs-1 [medium] the FeedPoller restart fix revives the OLD thread as well as starting a new one  (aliases: regression-24)
- dash-release-jobs-2 [medium] the staged half of the SELECTED CARDS block is truncated silently, and its count lies
- dash-release-jobs-3 [medium] an older companion's Cards agent loses its machine name, so one editor's two machines become one string  (also: comp-resolve)
- wire-4 [medium] the cards tunnel stopped accepting the agent's `name`, so every companion below 0.9.71 now registers as the bare editor and two of one edito  (also: comp-resolve)
- dash-release-jobs-4 [low] a feed record with a non-canonical kind/platform is now dropped with nothing at all to tell the admin
- dash-release-jobs-5 [low] `_signature_url` still cannot fetch the signature for the pre-signed URL its docstring is about
- dash-release-jobs-6 [low] two different fixes in the tree cite "dash-release-jobs-3", and the citations are off by one from -3 onward
- dash-release-jobs-7 [low] `read_state` writes to disk, so a full or read-only data dir turns a status read into an exception on the boot and shutdown paths
- regression-13 [low] CR-242b/CR-242c cite the wrong finding ids, and dash-release-jobs-5 is unledgered while dash-release-jobs-3's real fix is uncredited
- res-fleet-4 [low] `FeedPoller.stop()` drops the thread handle before the join succeeds, and `start()` then clears the stop event under it

## broll (CR-261) - 7 findings
- comp-broll-music-1 [high] the b-roll RETRY FAILED button now claims the batch with no staging id, so every clip in it fails at once  (also: comp-broll-music)
- broll-1 [medium] the retry button's new 409 branch prints the one sentence that is almost always false  (also: comp-broll-music)
- broll-2 [medium] the new retry-failed 409 reaches the editor as "[object Object]"
- broll-3 [medium] `client_shares.db` creation is still the crash-unsafe half of the migration broll-2 fixed, and the new try/except now hides it  (aliases: regression-14)
- broll-4 [low] the deleted discovery route left its login-gate carve-out behind, and today's test asserts the opposite  (also: dash-core)
- broll-5 [low] a ledger `ensure_schema` failure at BOOT degrades the whole /broll mount, which the same fix says must not happen  (also: dash-mounts-ui)
- broll-6 [low] a failed backfill still stamps the schema version, so those items lose the hash identity for ever

## music (CR-262) - 8 findings
- music-1 [high] retry-failed takes a LIVE batch away from the machine indexing it (the broll-5 guard was not ported)  (also: broll)
- music-2 [medium] the retry button is drawn on running batches and on other editors' batches  (also: broll)
- music-3 [medium] a retried batch is undispatchable after a page reload: music has no take-over path  (also: broll)
- music-4 [medium] the positive readiness cache keeps the write gate open for 5 s after the library mount disappears
- regression-10 [medium] music-5: `ORDER BY id DESC` now samples the rows least likely to be on disk, so a live drop refuses itself from item ~51
- music-5 [low] `_snapshot_token` can raise out of the first line of `rescore_library`
- security-3 [low] musicweb believes `X-CCSync-Fleet-Auth` on an ENVIRONMENT VARIABLE, which its own comment says it does not  (also: dash-core)
- tests-4 [low] a regression test that skips itself when the thing it guards appears

## ytdl-web (CR-263) - 7 findings
- ytdl-web-b-1 [medium] ytdl-web-1's own guard leaves the stale number behind, so the press after the share comes back says "free some space"
- ytdl-web-b-2 [medium] ytdl-web-4 removed the only free-space gate from exactly the jobs the NAS worker is the fallback executor for
- regression-26 [low] ytdl-web-5: the new claim refusal reaches the page as "this computer declined the job (HTTP 503)"
- ytdl-web-b-3 [low] the ' -- ' scan added for ytdl-web-7 does not cover the SPA, where most editor-facing copy is written
- ytdl-web-b-4 [low] the worker still holds the claim door open for 4 s per job that claim_download can no longer grant
- ytdl-web-b-5 [low] `free_bytes_at` no longer caches its negative answer, so a hung mount is re-stat'd on every press
- ytdl-web-b-6 [low] `_refuse_if_the_tree_is_gone` compares a database label against on-disk bytes with no normaliser

## server-tools (CR-264) - 9 findings
- server-tools-b-1 [medium] the cards snapshot deploy ships a commit and never says the checkout is dirty
- server-tools-b-2 [medium] `rollout_platforms` and `rollout_status` bucket a NULL platform differently, so the -EmitKindExtras gate refuses on a phantom platform  (also: dash-api, dash-db)
- server-tools-b-3 [medium] an explicit `--cards-src-dir` / `CARDS_SRC` deploy leaves a stale record, and the drift doctor reports it as OK
- tests-2 [medium] the new installer regression test is not in the local gate  (also: install-onboard)
- server-tools-b-4 [low] the drift doctor's new TIMELINE CARDS section runs on sites that have no Timeline Cards
- server-tools-b-5 [low] `_stage_docs_tree` can still raise out of a function documented never to
- server-tools-b-6 [low] `cards_repo_for`'s prefix fallback silently turns a subtree export into a whole-repo export
- server-tools-b-7 [low] `ro,rslave` reaches TrueNAS's middleware, and nothing offline can say it is accepted
- tests-5 [low] a large share of the new regression tests fail on the old code only because a new helper is missing

## install-onboard (CR-265) - 6 findings
- tests-1 [high] the install-onboard-1 regression test passes against the bug, on every runner it actually runs on
- install-onboard-1 [medium] `site_manifest_value` lets a stale, unbounded, unidentified cache override a manifest this run actually fetched, and beat the bootstrap's ow
- install-onboard-2 [low] the closing advice on a failed uninstall contradicts itself: "run this uninstaller again" and then "delete that file, and the folder it is i
- install-onboard-3 [low] the macOS uninstaller still claims "removed" and "complete" over a removal that did not happen
- install-onboard-4 [low] the hoisted legacy-agent retirement can leave a Mac with no companion autostart at all, and the big warning block does not say so
- install-onboard-5 [low] `normalise_dashboard_url`'s new 8443 rule is a deployment-specific guess applied to every customer's hostname

