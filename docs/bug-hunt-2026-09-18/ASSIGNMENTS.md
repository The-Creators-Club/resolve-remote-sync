# Builder assignments, fix pass 2026-09-18 (mediums and lows, plus what the live dashboard showed)

Four builders, one per FILE GROUP; the finding ids are headings in `hunters/*.md` (`grep -rn "^### <id>" docs/bug-hunt-2026-09-18/hunters/`) and every one has a verifier verdict with a Fix note in `verifiers/*.md`. Aliases are the same defect reported by another hunter: read both. A finding whose Where names a file outside your group: fix your side, record the rest as OWED.

Groups: **companion-core** = companion `app.py`, `__main__.py`, `config.py`, `site.py`, `identity.py`, `machine.py`, `paths.py`, `canon.py`, `secretfile.py`, `eula.py`, `capabilities.py`, `ui_state.py`, `ui_copy.py`, `reporter.py`, `idle.py`, `shutdown_guard.py`, `theme.py`, `supervisor.py`, `upgrade.py`, `release_pubkey.py`, `ed25519.py`, `tray.py`, `tray_native.py`, `popup.py`, `settings_window.py`, `ui_dispatch.py`, `crash_report.py`, `stills.py`, `sync/*`, `selection.py`, `file_moves.py`, `drive_reminder.py`, `drive_swap.py`, `manifest.py`, `root_guard.py`, `sidecar_tools.py` (the HTTPS/cert half for CR-280), and their tests. **companion-media** = companion `resolve_*.py`, `script_server.py`, `fixer.py`, `library.py`, `proxy_*.py`, `luts.py`, `bpg.py`, `consolidate.py`, `project_setup.py`, `watcher.py`, `timeline_cards_*.py`, `broll_*.py`, `ffmpeg_tools.py`, `loopback_guard.py`, `music_*.py`, `ingest_kinds.py`, `youtube_import.py`, `ytdl*.py`, `jobs_*.py`, `job_paths.py`, and their tests, plus `.github/workflows/*` ONLY for the ffmpeg gate of tests-1. **dashboard** = everything under `dashboard/` (src, templates, static, deploy, tests) and `.github/workflows/*` otherwise. **webapps-tools** = `broll/`, `music/`, `ytdl/`, `server/`, `tools/`, `bench/`, `installer/`, `onboarding/`.


## companion-core - 18 findings (3 medium, 15 low)
- comp-sync-2 [medium] CR-278's path-missing heal never runs on the machine shape its own docstring describes
- comp-ui-2 [medium] a failed Explorer-restart re-add leaves the companion permanently headless: nothing ever retries NIM_ADD again
- res-companion-4 [medium] a wedged media-tree (or watcher) thread is "restarted" without being stopped, so the watchdog stacks duplicate
- comp-app-1 [low] the b-roll editing-proxy upgrade resume is gated behind `proxy_relink_enabled` and behind `plan_relinks()` not
- comp-app-2 [low] the relaunch ceiling's primary source is still written non-atomically, in the one process that exists because   (aliases: comp-app-5)
- comp-app-3 [low] a standing upgrade refusal is cleared by the four report replies that mean "there IS a build, we are just not 
- comp-app-4 [low] "CCSync" is hardcoded in ~60 user-visible companion strings while the vendor-neutral brand helper is used once
- comp-app-6 [low] the "cannot read this computer's id file" toast does not mention the repair the same fix pass built
- comp-sync-3 [low] `_move_out_of_trash` claims it can never overwrite; on macOS and Linux `os.rename` silently does
- comp-sync-4 [low] a file moved into a BORROWED project has a home on this disk and is trashed anyway
- comp-sync-5 [low] the 09-11b fix pass wrote mojibake into two `file_moves.py` comments
- comp-sync-6 [low] the path-missing heal hardcodes `.stfolder` instead of the folder's own `markerName`
- comp-ui-1 [low] the startup registration backoff widened the "every toast is dropped" window from 2.5 s to 105 s, and nothing 
- comp-ui-3 [low] a self-recovering re-add failure writes a crash report and prints the terminal remedy
- comp-ui-4 [low] a terminal registration failure leaks the tray window and its HICON cache: `run()`'s error path never calls `_
- comp-ui-5 [low] the FIX ALL bar now reads a flat 0% for a whole rehearsal, while the file line says "Copying"
- comp-ui-6 [low] the stills "gallery moved" line joins a POSIX path with a backslash on macOS
- regression-6 [low] CR-255k fixed one of tests-3's two neutered assertions; the companion one is untouched and unledgered, and the

## companion-media - 25 findings (12 medium, 13 low)
- comp-broll-tiers-2 [medium] nothing dedupes an in-flight editing-proxy upgrade, and a permanently pending row spawns a Resolve worker chil
- comp-music-ytdl-jobs-1 [medium] the CLAP model allow-list is hard-coded to GitHub, so a fleet whose release feed is anywhere else can never do
- comp-music-ytdl-jobs-2 [medium] `test_ytdlp_manager.py` leaks a live ytdlp manager thread that holds `sidecar_tools._work_lock` through real G
- comp-resolve-4 [medium] every test of the refresh injects `replace_fn`, so the shipped default is untested
- proxy-tiers-1 [medium] "stop linking the 540p preview" was built in the relink pass only; every insert still attaches it, and the pas
- proxy-tiers-2 [medium] a clip whose original is not in the archive folder turns the whole tier machine onto the PREVIEW: the project   (aliases: broll-1, comp-broll-tiers-4, wire-4)
- proxy-tiers-3 [medium] the container losing sight of the archive turns every insert into proxy-tiers-2, and nothing anywhere says so
- proxy-tiers-4 [medium] the wired rig, which is the point of the whole design, has no working signal that a clip was born from a stand
- proxy-tiers-5 [medium] "usable from the moment the editing proxy lands" is not what the code does: a clip stays invisible until its m
- proxy-tiers-6 [medium] a stand-in can be written under a .mxf, .avi or .mkv name; the spike only ever tested a QuickTime original
- tests-1 [medium] twenty media-job tests skip silently on every CI and release runner
- wire-3 [medium] an agent whose editor has no episode open is told so in a body nobody reads, and reports itself healthy  (aliases: dash-cards-8)
- comp-broll-tiers-3 [low] an exact frame-count equality now fails the WHOLE ingest item, including for VFR sources
- comp-broll-tiers-5 [low] the stand-in ledger grows for ever and nothing surfaces a failed upgrade to the editor
- comp-music-ytdl-jobs-3 [low] `broll_vlm_sidecar.host_allowed` accepts an `http://` URL; its music sibling refuses one
- comp-music-ytdl-jobs-4 [low] the YouTube cookie jar is written to a temp file before it is hardened, contrary to the comment beside it
- comp-music-ytdl-jobs-5 [low] a `None` returncode from the edit-ready conversion reads as success
- comp-resolve-3 [low] a refresh is never remembered, so a clip that does not refresh is re-ReplaceClip'd for ever  (aliases: res-companion-5)
- comp-resolve-5 [low] a refresh-only pass reports "nothing to do" and `attached: 0`
- comp-resolve-6 [low] a refresh on a clip whose proxy is working carries no proxy, and ReplaceClip may drop the link
- comp-resolve-7 [low] the watcher's archive exemption stats the disk for every missing archive clip on a 3 s poll
- proxy-tiers-8 [low] the machine that made the editing proxy re-downloads it from the NAS, and re-downloads its own preview as a st
- tests-2 [low] the malformed-`insert` test asserts three fields and misses the one that changes the plan
- tests-3 [low] a phase-2 test still pins "the insert object changes nothing", after phase 3 shipped
- tests-4 [low] the "a write that cannot land is not an exception" test monkeypatches away the thing that raises

## dashboard - 47 findings (17 medium, 30 low)
- dash-cards-2 [medium] an episode that failed to build can never be opened again
- dash-cards-3 [medium] the cap refusal names a page that does not exist, and an act that frees nothing
- dash-cards-4 [medium] the /cards/sw.js kill switch deletes every cache on the origin, not just its own
- dash-cards-5 [medium] closing an episode leaks its 24-thread WSGI executor
- dash-cards-6 [medium] the per-slug data dir abandons every engine's existing state, with no migration
- dash-collector-alerts-1 [medium] a hand move BETWEEN two projects is detected only if both projects happen to fall in the same cycle's 8-projec
- dash-collector-alerts-2 [medium] the 500-move cap drops the rest of a pass permanently, while its log line promises they will be picked up late
- dash-collector-alerts-3 [medium] a folder RENAMED in place becomes one detected row per file, not one folder row
- dash-core-1 [medium] the DCORE-3 boot refusal passes on a zero-byte secret file, so a half-written `dash_session_secret` still sign
- dash-db-1 [medium] a collector poll that held no write lock at all is recorded as the writer that held it, for ever  (aliases: dash-collector-alerts-4)
- dash-db-2 [medium] the two notice kinds the busy rework writes are not in the registry, so the panel that exists to say what the   (aliases: dash-collector-alerts-5)
- dash-mounts-ui-4 [medium] the fleet-grid declutter moved five amber conditions behind [ DETAILS ] that neither the headline nor the note
- dash-release-jobs-1 [medium] the restart path still dies on a full or read-only /data: CR-260g fixed the reader, not the writer its own fai
- res-fleet-3 [medium] a detected hand move between two projects makes every holding machine file its copy into a directory that is n
- res-fleet-4 [medium] forgetting or renaming a computer strands its outstanding file moves and Resolve undos, and leaves an alert no
- security-2 [medium] any signed-in non-admin can take both Timeline Cards engine seats, and only an admin can give one back
- wire-2 [medium] "a busy database is contention, not an error" stops at the dashboard's own routes; the mounted apps still 500,
- dash-api-3 [low] `as_of` is a tree-wide MAX, so one freshly walked project makes every locate answer look current
- dash-api-4 [low] a lane a machine never reported draws as a quiet GREEN chip  (aliases: dash-mounts-ui-5)
- dash-api-5 [low] `skipped_exists` is now a per-subpath figure rendered as a tree-wide fact, and a stale one never clears
- dash-api-6 [low] a publish places the file before the row is inserted, so a failed insert leaves a replaced live artefact under
- dash-cards-7 [low] the raw build exception is rendered into the landing page
- dash-cards-9 [low] the failed-episode test cannot fail for the bug it sits next to
- dash-collector-alerts-6 [low] the dashboard's stand-in for the companion's disk floor is hard-coded, so a machine with a configured floor is
- dash-core-3 [low] OIDC mints a session for a username the rest of the dashboard will not accept, and says nothing
- dash-core-4 [low] the per-episode open paths are not restricted to GET, although the comment beside them says they are
- dash-core-5 [low] expired browser sessions accumulate on a long-running container: the only sweep runs at boot
- dash-core-6 [low] `internal.env` and `syncthing.env` are rewritten in place on every boot, so a boot cut off mid-write leaves th
- dash-db-4 [low] the "who holds this file" query is a LIKE with the path's own wildcards unescaped
- dash-db-5 [low] the assignments picker offers a computer whose grid can never have a column  (aliases: dash-mounts-ui-3)
- dash-db-6 [low] a write-lock test in my territory failed once and will not reproduce
- dash-mounts-ui-1 [low] CR-270 writes `retired_from` / `retired_reason` into a file no surface reads, so an applied OTA update vanishe
- dash-mounts-ui-2 [low] the new vendor section calls a locally RECALLED build "[ STAGED, NOT CURRENT ]" and offers [ MAKE CURRENT ] on
- dash-mounts-ui-6 [low] the b-roll mount records its PROXIES directory as its root, so a degraded-mount notice names the wrong path
- dash-release-jobs-2 [low] `repair_provenance` lets an untrusted feed host rewrite the provenance of a package this dashboard published i
- dash-release-jobs-3 [low] the new "only upload what changed" skip trusts a GitHub asset's name and size, and cannot see a half-uploaded 
- dash-release-jobs-4 [low] a channel `retracted` entry whose `kind` is not lower-case recalls nothing, silently, on both halves of the re
- dash-release-jobs-5 [low] re-applying the version already running erases the rollback target
- regression-3 [low] CR-270's retire branch is asked before CR-259a's schema guard, is not schema-aware, and no test can reach it
- regression-4 [low] CR-259a's guard treats "the staged tree could not say what schema it knows" as schema v0, and permanently refu
- regression-5 [low] CR-258B does not close dash-collector-alerts-1 for a deployment whose collector has not yet run any kind twice
- regression-7 [low] tests-4 was dropped from the fix pass with no fix, no decline and no ledger entry anywhere
- res-fleet-2 [low] a pushed update the machine can never take removes that computer from the jobs fleet for ever, and nothing any
- security-1 [low] the `/cards` PWA login-gate carve-outs are method-agnostic, so an unauthenticated POST reaches the mounted eng
- security-3 [low] the Cards carry-on cookie sets `secure` from the raw request scheme, not from the site's cookie policy
- security-4 [low] `/api/v1/files/locate` answers across every active project for any fleet credential, with no per-editor scopin
- tests-5 [low] the "every new kind is in the registry" test is a hand-written list, so it cannot fail for a new kind

## webapps-tools - 32 findings (13 medium, 19 low)
- broll-indexer-1 [medium] `make_own_proxies.py` never got the frame-count check that the rest of the fleet did
- broll-indexer-3 [medium] the new frame check costs a second full network read of every original, on the one path the pipeline was tuned
- install-onboard-1 [medium] a macOS `--dry-run` uninstall now ends "CCSync uninstall NOT complete"
- install-onboard-2 [medium] `-Full` on Windows says "removed" and "your identity is gone" without looking
- music-1 [medium] a cancel that lands in the window between lease expiry and the next sweep wedges the batch in `running` for ev
- music-2 [medium] the take-over / retry buttons report every loopback 409 as "another of your computers is still working on this
- regression-1 [medium] CR-262C does not close music-3: the retry it made unconditional is refused by CR-253A from the SAME fix pass, 
- server-tools-1 [medium] an LGPL dependency shipped to customers has no notice, and the generator that would catch it is in no gate
- server-tools-2 [medium] a b-roll publish whose drain merge fails still exits 0, and a test pins that
- ytdl-web-2 [medium] the worker's new "no room" refusal reintroduces the wrong sentence a vanished share earns (ytdl-web-1's whole 
- ytdl-web-3 [medium] the "no room" failure tells the editor to press RETRY FAILED, and the page hides that button in exactly that s
- ytdl-web-4 [medium] a pasted-links job never gets a free-space check at all, on either executor
- ytdl-web-5 [medium] when the share vanishes but the container has room, the download SUCCEEDS into the container overlay and the l
- broll-2 [low] migration 012 makes a published `broll.db` unreadable by any dashboard older than 0.7.49, and `publish_db.py` 
- broll-3 [low] the archive top slot is matched by an exact stem string, with no NFC/NFD normaliser
- broll-4 [low] `edit_proxy_rel` can name the preview itself
- broll-5 [low] the zero-byte guard in `mark_uploaded` covers only the declared editing proxy, not the preview the server itse
- broll-indexer-2 [low] the `frames` column that decides an offline clip's LENGTH is read from `nb_frames`, which this same module doc  (aliases: proxy-tiers-7)
- broll-indexer-4 [low] a probe that yields no duration crashes the proxy stage with a bare TypeError
- broll-indexer-5 [low] `fix_proxy_timecode` verifies that the remux has *a* timecode, not the one it just decided on
- install-onboard-3 [low] the macOS uninstall test pins the verdict function, not the code path that sets its argument
- install-onboard-4 [low] `_same_dashboard` compares hostnames only, so two deployments on one host share a cache
- install-onboard-5 [low] a macOS dry run claims, in the past tense, that the Syncthing identity was deleted
- music-3 [low] the drop preview mints names that ignore every name already promised to an unlanded item
- music-4 [low] `make_proxies --dry-run` dies on the files the real run survives, and over-counts the ones it cannot decode
- server-tools-3 [low] `tailscale status --json` is decoded with the console codec, so a non-ASCII peer name turns a health check int
- server-tools-4 [low] bench's rclone readback decodes with the console codec and its decode failure is not caught
- server-tools-5 [low] one absent guide now suppresses the licence agreement as well
- tests-6 [low] three copies of the b-roll schema and migrations, no test that they are the same
- ytdl-web-6 [low] any fleet-credentialled editor can claim, and be handed the work order for, another editor's job
- ytdl-web-7 [low] `db.py` defines `_column` twice; the first definition is dead
- ytdl-web-8 [low] the new "download on this computer was unticked" sentence says "this search" on a pasted-links job

## Added from the live dashboard (`hunters/live.md`)
- companion-core: live-5 [medium] (the tray colours nothing-ticked orange: owner rule, fix in tray.py), live-1 [medium] (companion half: the stall record ages out and is cleared by a later completed pass), CR-279 queueing half [open ledger item], CR-280 [open ledger item; say what cannot be verified without a Mac]
- dashboard: live-1 [medium] (dashboard half: `_why_code` and `_check_lane_stalled` age gate, safe alone), live-2 [medium] (with dash-api-6, raised to medium), live-3 [low], live-4 [medium]

## Ledger numbers
- companion-core: CR-283; companion-media: CR-284; dashboard: CR-285; webapps-tools: CR-286. Write `ledger/<group>.md` with one `### CR-28nX (<finding-id>) - <title> - FIXED (<file>)` section per finding, lettered A, B, C ... in the order above.
