# Assignments, 2026-09-18b mediums wave (15 builders, 15-minute box)

Confirmed mediums only (verdicts.txt). Duplicates of fixed highs are skipped: comp-broll-tiers-2, comp-broll-tiers-3, comp-resolve-4, dash-api-1, regression-1, wire-2, wire-3.
Also skipped as duplicates of fixed highs: comp-sync-5 (= res-companion-2), res-fleet-3 (= dash-release-jobs-1, in dashboard-release).
Downgraded-to-low (only if a builder finishes early): broll-2, broll-indexer-2, comp-app-3, comp-app-4, comp-music-ytdl-jobs-2, comp-resolve-5, comp-ui-2, comp-ui-3, comp-ui-5, dash-cards-2, dash-collector-alerts-4, dash-release-jobs-3, install-onboard-2, install-onboard-5, install-onboard-6, music-2, proxy-tiers-2, regression-2, ytdl-web-4

## companion-core (CR-291) - files: companion app.py, file_moves.py, sync/*, tests
- comp-app-2 [medium] CR-283D moved the editing-proxy resume out of the relink flag but left it behind `get_media_pool_items()`, so a closed o  (verdict: CONFIRMED)
- comp-sync-3 [medium] res-companion-2 does not cover the folder move, which is the shape the feature exists for  (verdict: CONFIRMED)
- comp-sync-4 [medium] lane B's recovery stamp overwrites lane A's live stall record and erases it from the wire and from disk  (verdict: CONFIRMED)

## companion-ui (CR-292) - files: companion tray.py, tray_native.py, popup.py, settings_window.py, tests
- comp-ui-1 [medium] a rehearsal still says `Copying "...": 0 B of 12.7 GB` for its FIRST clip, and for the whole run when there is one clip  (verdict: CONFIRMED)
- comp-ui-4 [medium] CR-283P's twin: the CONSOLIDATE progress window still draws "Copying ... 0 B of 800 GB" for a whole rehearsal  (verdict: CONFIRMED)

## companion-resolve (CR-293) - files: companion proxy_relink.py, resolve_bridge.py, watcher.py, tests
- comp-resolve-2 [medium] a forced refresh in which ReplaceClip RAISED (but not every time) is remembered for ever as "this file is settled"  (verdict: CONFIRMED)
- comp-resolve-3 [medium] the `.mp4` refusal is not scoped to the b-roll archive, so a legacy project `.mp4` proxy is silently never attached and   (verdict: CONFIRMED (narrowed: the plan side is the live half; the insert)

## companion-broll (CR-294) - files: companion broll_server.py, broll_standins.py, broll_fetch.py, tests
- proxy-tiers-3 [medium] the `known: false` outage guard protects only 0.9.75, and the deploy order guarantees the fleet runs the unprotected bui  (verdict: CONFIRMED (medium stands))

## companion-jobs (CR-295) - files: companion jobs_runner.py, ytdl_executor.py, sidecar_tools.py, tests
- comp-music-ytdl-jobs-1 [medium] a cancelled or HALTED whisper job kills `pipeline.py` and leaves the whisper worker (and the GPU) running  (verdict: CONFIRMED)
- comp-music-ytdl-jobs-3 [medium] killing yt-dlp does not kill the ffmpeg it spawned  (verdict: CONFIRMED)

## indexer (CR-296) - files: broll/indexer/*
- broll-indexer-3 [medium] audio-only clips are never transcribed, although two files say their speech is the only index they get  (verdict: CONFIRMED)

## dashboard-api-db (CR-297) - files: dashboard api.py, db.py, locate.py, tests
- dash-api-3 [medium] `upgrading` in fleet_facts/machine_facts is `update_requested_version != ''` alone, so a withheld push costs the machine every job kind for 14 days (verifier: the hunter's fix cannot be implemented as written; see its verdict for the workable shape)
- dash-api-2 [medium] locate excludes a project for ever after one transient inventory error  (verdict: CONFIRMED)
- dash-db-3 [medium] dash-db-4's LIKE escaping was applied to the db helper and not to the identical query the admin's MOVE button actually r  (verdict: CONFIRMED)

## dashboard-collector-core (CR-298) - files: dashboard collector.py, alerts.py, notices.py, app.py, mount_status.py, health.py, tests
- dash-collector-alerts-2 [medium] the new b-roll archive check cannot fire on the failure it was written for, and its test pins the wrong answer  (verdict: CONFIRMED)
- dash-collector-alerts-3 [medium] a project's FIRST inventory writes one pending half per file, inside the collector's write burst  (verdict: CONFIRMED)
- dash-core-1 [medium] wire-2's fix makes every unhandled error under a mount record itself TWICE, and write to the busy database twice  (verdict: CONFIRMED)
- dash-core-2 [medium] a notice written for a mounted app names a path that does not exist on this dashboard, and two mounts collide on one row  (verdict: CONFIRMED (conclusion), with the hunter's mechanism and suggested fix both WRONG)
- res-fleet-2 [medium] the carried move halves are written without a bound and read with one  (verdict: CONFIRMED)

## dashboard-cards-ui (CR-299) - files: dashboard cards*.py, cards_landing.py, deploy/select_code_root.py, templates, static, tests
- dash-cards-1 [medium] the kill switch deletes the NEW per-episode page's shell cache too  (verdict: CONFIRMED)
- dash-mounts-ui-1 [medium] a retire carries a refusal the admin can never clear, and the banner tells them to restore a backup  (verdict: CONFIRMED)
- security-1 [medium] the new 15-minute idle release measures SERVER REQUESTS, so an editor working OFFLINE in Cards is evictable by any other  (verdict: CONFIRMED (medium))

## dashboard-release (CR-300) - files: dashboard dashboard_update.py, release_feed.py, tests
- dash-release-jobs-1 [medium] CR-285S does not fix its own `request_restart` half: the restart intent lives only in the file that could not be written  (verdict: CONFIRMED)
- tests-1 [medium] the only test for dash-release-jobs-5 re-implements the fixed expression and cannot fail on the unfixed code  (verdict: CONFIRMED)

## webapps-server (CR-301) - files: server/*, tools/*, bench/
- server-tools-1 [medium] release_macos.sh silently cancels a CCSYNC_REQUIRE_FFMPEG the caller (and CI) set  (verdict: CONFIRMED)
- server-tools-2 [medium] publish_db's "older schema than the live one" refusal is false for `--which music`  (verdict: CONFIRMED)
- server-tools-3 [medium] gen_notices still decodes pip-licenses by the console codec, in the very pass that fixed five other sites  (verdict: CONFIRMED)

## webapps-broll (CR-302) - files: broll/web/*
- broll-1 [medium] broll-3's NFC fix covers the ORIGINAL but not the editing proxy beside it  (verdict: CONFIRMED (medium stands))

## installer (CR-303) - files: installer/*, onboarding/*
- install-onboard-1 [medium] the -Full leftovers verdict tells the editor to retry and, two lines later, to delete the retry path  (verdict: CONFIRMED)
- install-onboard-3 [medium] section 5 reports "removed your sign-in and settings" from ~/.ccsync without looking, and the verdict never checks that   (verdict: CONFIRMED)
- install-onboard-4 [medium] any surviving file is reported as "your sign-in and Syncthing identity", and one run can say both that the identity is g  (verdict: CONFIRMED)

## music (CR-304) - files: music/web/*, music/indexer/*
- music-1 [medium] the cancel wedge CR-286/music-1 names is still reachable on the OTHER branch of the same `if`  (verdict: CONFIRMED)
- music-3 [medium] the retry toast now reports a browser/network error as if it were the companion's answer, and drops the one actionable s  (verdict: CONFIRMED)

## ytdl (CR-305) - files: ytdl/web/*
- ytdl-web-1 [medium] CR-286K does not fix ytdl-web-3: a failed job has no manifest, so the retry button is still hidden  (verdict: CONFIRMED)
- ytdl-web-2 [medium] the paste free-space guard can never size a paste, so it misses its own stated scenario  (verdict: CONFIRMED)

