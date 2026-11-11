# deploy-nas - the dashboard / Timeline Cards / Footage Sorter deploy to the NAS

Files read (approximate coverage): `server/install_dashboard_app.py` (main() 5936-7421 in full; preflight, health/boot verification, pull, install_tree/upload_tree/swap/prune, host-dir chain; the Synology and music-data helpers skimmed), `server/common.py` (ssh_client, run_ssh, snapshot_before), `server/backends/truenas.py` (delete/restart/deploy_stack/snapshot), `dashboard/deploy/Dockerfile`, `.dockerignore`, `dashboard/deploy/run.sh`, `.github/workflows/image.yml`, `dashboard/src/ccsync_dashboard/dashboard_update.py` (restart, backups, stage-verify, snapshot), `cards_pool.py` (drop/close), `site.toml [stack]`, docs `CARDS_DEPLOY.md`, `SORTER_DEPLOY.md`, `DOCKER.md` (image mode, code-root selection), `RELEASE.md` §6 and "Every door to make current".
Probes run: (1) GHCR manifest + config of `:edge` (`sha256:3887ea84...`, read-only registry API): 17 layers, 156.8 MB compressed; base 45 MB, venv 108.1 MB, all code layers together 2.6 MB, the `chmod -R` layer 0.25 MB. (2) `gh run view 42847901553 --log`: the image smoke test pulled in 8 s and answered `/api/v1/health` 2.3 s after `docker run` (empty data, no mounts). (3) `gh run list --workflow image.yml`: builds take 1.3-4.2 min. (4) `git ls-tree -l` of the Cards and Sorter commits with the deploy's exclude rules applied: Cards ships 479 files / 8.45 MB, of which `multicam_pipeline/` is 156 files / 5.36 MB; Sorter ships 57 files / 1.61 MB. (5) `site.toml [stack]`: `mode = "image"`, `image = ...2d43c24c` commented "dashboard 0.7.78, deployed 2026-11-08". The deploy script was NOT run, not even `--dry-run`; no SSH, no NAS, no live dashboard.

## The deploys as an operator runs them today

Downtime figures are estimated unless marked measured: nothing here could be timed on the NAS. "SSH" = one new paramiko connection (TCP + key exchange + password auth), counted from the code path.

**A. Dashboard release that needs a new image (image mode, runtime change).**
1. Bump `VERSION`, commit, push `main`. `image.yml` builds and pushes `:<sha>` + `:edge` (1.3-4.2 min, measured).
2. By hand: copy the new digest out of the Actions step summary.
3. By hand: read the live Cards and Sorter commits off the NAS (`live.sh`: a `.sh` file you write yourself, run through Git Bash from a PowerShell that dot-sourced the secrets; 1 SSH), because the run re-ships both trees.
4. `. .\tools\load_secrets.ps1; ...install_dashboard_app.py --mode image --container-image <new> --cards-commit <live> --sorter-commit <live> --music-data none --yes --dry-run`, read it, then the same line again without `--dry-run`.
5. The run: identity probe, snapshot (2 SSH), 8 provisioning steps (8 SSH), Cards re-ship (5 SSH incl. SFTP of 479 files), Sorter re-ship (5), `docker pull` (1), app DELETE + job wait, 4 dataset/snapshot probes (4), app CREATE + job wait (5 s polls), `sleep 10`, logs/runtime-id/health (3). About 29 SSH connections plus the REST calls.
6. Frequently ends `FAILED: /api/v1/health did not answer` and exit 1 (deploy-nas-2). By hand: SSH in and `sudo docker ps` until `(healthy)`.
7. By hand: edit `site.toml [stack] image` to the new digest. Forget this and the NEXT run of the recipe-without-pin rolls the dashboard back (deploy-nas-1). It is stale today: it says 0.7.78 while SORTER_DEPLOY records 0.7.79 going live on 2026-11-10.
Downtime: app delete + app create + cold boot, estimated 1-3 min. Manual steps: 6. SSH round trips: about 31.

**B. OTA dashboard code update (no new image).** Build the bundle and publish it to the feed (deploy-release's territory), then Settings -> Packages -> [ APPLY ], or nothing at all on `policy = current` after the soak. In-container: download, verify, stage-verify in a subprocess against database copies, sqlite-API backups, optional NAS snapshot via the API key, rename, exit 75, `run.sh` re-selects the code root and re-execs uvicorn. No SSH, no container restart. Downtime: one uvicorn boot, estimated 15-40 s. This path is good (see "What is already good").

**C. Cards-only deploy (CARDS_DEPLOY.md "The usual deploy").** Commit in `E:\Projects\Editing`; `live.sh` by hand (1 SSH); dry run; real run with `--mode image --container-image <live digest> --cards-commit <sha> --music-data none --yes`. The run is case A's run in full: `--mode image` implies `--recreate`, so the TrueNAS app is DELETED and CREATED again for a code change that needs only a restart, and the Sorter tree is re-shipped too, from `master`, because the Cards recipe was written before the Sorter existed and does not pin it (deploy-nas-5). Ends in the premature FAILED / exit 1 (deploy-nas-2), then `docker ps` by hand. Downtime estimated 1-3 min. Manual steps: 5 (commit, live.sh, dry run, run, docker ps). SSH: about 31.

**D. Sorter-only deploy (SORTER_DEPLOY.md).** Identical to C, plus the live Cards commit must be read by hand and passed as `--cards-commit` or Cards `main` ships alongside. Same downtime, same 31 SSH, same exit 1.

**E. "Just restart to pick up new vault data" (CLAUDE.md sends this to the C recipe).** The whole of C: snapshot, provisioning, two tree re-ships, app delete + create, the FAILED line. What is actually needed is one `docker restart` (1 SSH, estimated 20-60 s of downtime) or, for one episode, no dashboard restart at all (deploy-nas-8).

## Findings

### deploy-nas-1 - The recipe's `--mode image` deletes and recreates the app on every Cards/Sorter deploy, which is the only reason the stale-digest trap exists
- Category: deploy
- Severity: high
- Confidence: CONFIRMED
- Where: server/install_dashboard_app.py:6122-6131 (`if args.mode: args.recreate = True`), 7173-7237 (restart path), 1969 (`SITE_CONTAINER_IMAGE`), 2131; docs/CARDS_DEPLOY.md:28, 173-212; docs/SORTER_DEPLOY.md:154-166
- What: `site.toml` already says `[stack] mode = "image"`, so `--mode image` adds nothing but the implied `--recreate`, which deletes the TrueNAS app and re-creates it from a compose body rendered with `[stack] image`. Without `--mode`, the same run takes the restart path (`app_installed` -> `restart_dashboard_container`), which keeps the live container and its live image; no digest is needed at all. The docs' claim that "a bare run recreates the container on whatever site.toml says" is not what the code does today. The recipe makes the dangerous operation the routine one and then guards it with a hand-read digest.
- Cost / failure scenario: every Cards or Sorter deploy (several a week by the doc history) pays an app delete + create job instead of a restart: an estimated 40-120 s of extra dashboard downtime and ~4 extra SSH probes. Worse, any run that follows the recipe with the digest left out or mistyped, or copies `site.toml`'s value (stale today: 0.7.78 vs the 0.7.79 SORTER_DEPLOY records as live), recreates the fleet dashboard on an older image. That is the "rolls the dashboard back" the docs warn about, one omitted argument away, on the service that tells everyone whether their footage is syncing.
- Evidence: code path read end to end; `site.toml [stack]` read (mode image, digest annotated "0.7.78, deployed 2026-11-08"); CARDS_DEPLOY.md's own 2026-10-29 transcript shows "deleted app for re-create" on a Cards-only run.
- Ledger: new (the recipe in CLAUDE.md and CARDS_DEPLOY.md; KNOWN_BUGS 16110 records a recreate with "live digest" done by hand)
- Suggested change: (1) Drop `--mode image` from both recipes now (a docs change; keeps stage-verify-swap and the snapshot). (2) In the script, read the live image with one `docker inspect --format {{.Config.Image}}` at the start; when the requested image (flag, else `[stack] image`) differs from the live one, refuse unless `--container-image` was given explicitly, and refuse an image whose version label is older than the live one unless `--allow-older`. (3) Recreate only when the rendered compose differs from the live app's config (or on an explicit `--recreate`), and after a successful recreate write the deployed digest to `~/.ccsync/state/dashboard_deployed.json` and print the `site.toml` line (or rewrite it). Must not break: `--mode` still implies recreate for a real mode MIGRATION (live mode differs from requested).
- Effort / risk: S for the docs, M for the live-image guard; low risk.

### deploy-nas-2 - The "premature health check FAILED" is a fixed 10 s sleep followed by ONE probe, and on the recreate path it ends the run before the 150 s poll ever runs
- Category: deploy
- Severity: medium
- Confidence: CONFIRMED
- Where: server/install_dashboard_app.py:2604 (`time.sleep(10)`), 2656-2674 (single-shot probe), 7403-7405 (recreate path: `return 1` on it), 7218-7219 + 7235 (restart path: its False also forces exit 1)
- What: `verify_image_boot` waits a fixed 10 s, reads `docker logs`, then asks `/api/v1/health` exactly once. A container still starting fails that one ask, `ok_boot` becomes False, and the recreate path returns 1 straight away, so `verify_dashboard_after_restart` (the one with the 150 s deadline loop) never runs. The restart path does run the loop, but still exits 1 because `boot_ok` is False. The FAILED text in CARDS_DEPLOY.md ("/api/v1/health did not answer from inside the container on port 8480") is this function's line 2673 verbatim, and it also prints a `--mode bind` ROLL BACK instruction, inviting exactly the wrong reaction.
- Cost / failure scenario: on 2026-10-04 and 2026-10-29 (the doc) every deploy ended in a false FAILED + exit 1 + a manual SSH `docker ps` by the operator, and `ship.cmd`-style callers cannot tell it from a real failure. A cold boot on the NAS demonstrably takes longer than 10 s (the 2026-10-29 log), while the CI smoke boot takes 2.3 s (measured), so the NAS's mounts and engines are what push it past the fixed sleep.
- Evidence: code read; the doc's quoted output matches line 2673; CI smoke log timing.
- Ledger: related to OPS-1 (KNOWN_BUGS 5660, fixed): OPS-1 added the polling probe but the image-mode check in front of it was left single-shot.
- Suggested change: poll health first with the existing `probe_dashboard_health` deadline (the compose healthcheck's 120 s start_period), and only then read logs and `/venv/.runtime-id` once. Do not print the `--mode bind` rollback unless the boot line is actually missing after the deadline. Must keep: a container that never answers still exits non-zero.
- Effort / risk: S; low.

### deploy-nas-3 - In image mode the health gate demands the repo's dashboard VERSION, which an image-mode deploy never ships: 150 s of polling and exit 1 whenever the repo is ahead or an OTA bundle is running
- Category: deploy
- Severity: medium
- Confidence: CONFIRMED
- Where: server/install_dashboard_app.py:2416-2430, 2446-2497, 2543-2551; called at 7227 and 7409
- What: `verify_dashboard_after_restart` requires `version == repo_dashboard_version()`. In image mode `push_code` is False, so the version that comes back is the image's or the OTA bundle's (CARDS_DEPLOY's own example: code root `/data/code/0.7.76` while the repo was newer). Any repo commit that bumped VERSION ahead of what is live makes every Cards or Sorter deploy poll the full 150 s (30 probes, each a new SSH connection plus `sudo docker exec`) and then print FAILED with a rollback one-liner for an app tree this mode never touched.
- Cost / failure scenario: on the restart path, 150 s of wall clock and 30 SSH handshakes per Cards/Sorter deploy whenever dashboard VERSION has been bumped but not yet released (that is the normal state between a dashboard commit and its OTA). CARDS_DEPLOY.md documents "Exit 1 is also printed whenever the repo's dashboard VERSION is ahead of the pinned image" as something to ignore, which trains the operator to ignore exit 1.
- Evidence: code read; CARDS_DEPLOY.md:241-245.
- Ledger: related to OPS-1 (fixed)
- Suggested change: in image mode, read `/api/v1/health` once BEFORE the restart and use that version as the expected one (code did not change, so the version must not either); keep repo VERSION only when `push_code` is True. Same deadline loop.
- Effort / risk: S; low.

### deploy-nas-4 - Every remote command opens a new SSH connection: about 31 handshakes per deploy, plus one per health poll
- Category: perf
- Severity: low
- Confidence: CONFIRMED (count) / PLAUSIBLE (seconds)
- Where: server/common.py:1571-1601 (`run_ssh`: `ssh_client(...)` then `client.close()` per call); install_dashboard_app.py:5220, 2481, 5259-5296, 5699-5745
- What: `run_ssh` builds a fresh `paramiko.SSHClient`, connects, authenticates by password, runs one command and closes. A Cards deploy on the recipe makes about 31 such connections (counted in the timeline above), and a restart-path deploy adds up to 30 more from the health poll (deploy-nas-3).
- Cost / failure scenario: estimated 0.5-1.5 s per connect+auth with paramiko's Ed25519 KEX on the LAN, so 15-45 s per deploy and up to 45 s more on a slow poll. Each also makes a fresh sshd auth log entry on the NAS.
- Evidence: code read; the count is from main()'s path with sorter configured and `--music-data none`.
- Ledger: new
- Suggested change: cache one connected client per process in `run_ssh` (module-level, re-connect on a dead transport) and open a channel per command; the sudo password still goes over each channel's stdin (SEC-2 unchanged), and the host-key pin is still checked once on the connect. The SFTP upload can reuse the same transport.
- Effort / risk: S; low.

### deploy-nas-5 - Every run re-ships BOTH Cards and Sorter trees, so each recipe needs the other tree's live commit read by hand, and the Cards recipe now ships Sorter `master` unpinned
- Category: deploy
- Severity: medium
- Confidence: CONFIRMED
- Where: server/install_dashboard_app.py:6284-6355 (both resolved on every run), 7124-7160 (both shipped whenever present), 1200 (`SORTER_DEFAULT_REF = "master"`); docs/CARDS_DEPLOY.md:200-212 (no `--sorter-commit`); docs/SORTER_DEPLOY.md:154-159
- What: `ship_cards` and `ship_sorter` are true whenever the site names a checkout, so any run ships both, each from its default ref (`main` / `master`) unless pinned. The SORTER recipe deals with this by having the operator read the live Cards commit off the NAS by hand. The CARDS recipe (written before the Sorter mount, 2026-10-29) passes no `--sorter-commit` at all, so since the Sorter went live on 2026-11-10 following CARDS_DEPLOY.md ships whatever footage-sorter `master` is. Today `master` equals the work branch (`abe2539`, checked), so it happens to be harmless; the next commit on master that is not ready is not.
- Cost / failure scenario: per deploy, an unneeded second tree: 5 SSH connections, an SFTP of 57 files (Sorter) or 479 files (Cards), two `find` walks, a privileged `cp -a` + `chown -R`, a rename and a prune; plus one manual SSH step and one pasted sha per deploy. Failure: a Cards hotfix deploy publishes an unfinished Sorter to `/sorter`, which moves real files in the pool.
- Evidence: code read; `git -C footage-sorter merge-base --is-ancestor`.
- Ledger: new
- Suggested change: make the default for each tree "keep what is live": read both `DEPLOYED_COMMIT` markers in the one start-of-run SSH (deploy-nas-1's `docker inspect` call) and skip `install_tree` when the requested commit equals the live one; ship a tree only when its `--*-commit` is given (or `--cards-commit main` explicitly). Same staged-verify-swap for whatever does ship. Fix CARDS_DEPLOY.md now to pass the live sorter sha until the code changes.
- Effort / risk: S-M; low.

### deploy-nas-6 - The "create-only" host-dir step runs `chown -R` over all of `<root>/data` and `<root>/venv` on every deploy
- Category: deploy
- Severity: low
- Confidence: CONFIRMED
- Where: server/install_dashboard_app.py:6644-6651 (comment: "create-only (contents never touched on re-run)") vs 6674-6677 (`chown -R {private_owner} data`, `chown -R ... venv`)
- What: the comment says data/ and venv/ contents are never touched on re-run; the command recursively re-owns both, as root, every time. In image mode `<root>/venv` is not even mounted (it is the bind-mode leftover), and `/data` holds the live `dashboard.db`, OTA code trees, up to 8 GiB of backups, packages, Cards state and the yt-dlp nightly.
- Cost / failure scenario: a recursive privileged metadata walk per deploy over a dataset measured at 23,135 entries / 12.9 GB in 2026-09-08 (KNOWN_BUGS ~16106; most of it is under data/), estimated 1-5 s, plus a recursive mutation of the directory the live database is in during every Cards deploy. It also flips the group of files the container created as 3000:3001 to 3000:3000 on every run.
- Evidence: code read against its own comment.
- Ledger: related to the bug-hunt-2026-08-21 uid/gid finding (fixed: literals replaced); this recursion was not raised.
- Suggested change: `chown`/`chmod` the top directory only, and `chown -R` only when the directory was just created (`[ -d x ] || { mkdir; chown -R; }`). Skip `<root>/venv` entirely in image mode.
- Effort / risk: S; low.

### deploy-nas-7 - Cards ships the whole MulticamPipeline commit minus a deny-list: 479 files where the mount needs about 160
- Category: streamline
- Severity: low
- Confidence: CONFIRMED (counts) / PLAUSIBLE (exact allow-list)
- Where: server/install_dashboard_app.py:539-543 (`CARDS_EXCLUDE_DIRS`), 5192-5198; docs/CARDS_DEPLOY.md:136-151
- What: what ships is everything but `docs/deploy/scratch/golden/tools/.claude/tests`: `work/` (198 files, 1.94 MB of per-project working data such as `media_pool_*.json` and plans), `apps/` (40 files of Android source), legacy and 26 root scripts ride along with the 156-file `multicam_pipeline/` package. The Sorter already uses an allow-list (`SORTER_SHIP_DIRS`). CARDS_DEPLOY.md also says `tests/` ships and must not be excluded; the code excludes it (`BROLL_EXCLUDE_DIRS` contains `tests`), so the doc is wrong.
- Cost / failure scenario: per Cards deploy about 320 extra SFTP puts (each several round trips) and 3 MB, roughly two thirds of the upload's file count. Small in seconds (estimated 5-10 s), but it is also project data copied onto the NAS on every deploy.
- Evidence: `git ls-tree -l HEAD` with the deploy's rules: 479 files / 8.45 MB shipped, `multicam_pipeline` 156 / 5.36 MB.
- Ledger: new
- Suggested change: an allow-list, `multicam_pipeline/` plus the root modules it imports (`cards/config.py` imports `webtheme` from the checkout root; derive the list from an import test, not by hand). Correct the `tests/` paragraph in CARDS_DEPLOY.md.
- Effort / risk: S; low (a missing root module shows as `/cards` "absent", which the health block reports).

### deploy-nas-8 - "Restart to pick up new vault data" runs the full deploy and takes the whole dashboard down, when a restart (or a per-episode close/open) would do
- Category: deploy
- Severity: medium
- Confidence: PLAUSIBLE
- Where: CLAUDE.md "Deploying it (new Cards code, or just a restart to pick up new vault data)"; E:\Projects\CLAUDE.md "Deploying it, or restarting it to pick up new vault data, has one recipe"; dashboard/src/ccsync_dashboard/cards_pool.py:616-730 (`may_close`, `drop`); cards_landing.py:443-455
- What: both CLAUDE.md files send a vault-data refresh through the C recipe: snapshot, 8 provisioning steps, two tree re-ships, app delete + create, premature FAILED. The engine is built per episode on first open (`_run_build` reads the root fresh), and the landing page already lets the occupant or an admin Close an episode; reopening rebuilds it from the vault without restarting anything else.
- Cost / failure scenario: each refresh costs the recipe's ~31 SSH and an estimated 1-3 min of fleet-dashboard downtime, versus 1 SSH and an estimated 20-60 s (`docker restart`), or zero dashboard downtime for a Close/Open. Close/Open leaks the three upstream threads per episode (cards_pool `drop` docstring, CARDS_TWO_PROJECTS §6.1, owner-accepted), so a periodic real restart is still needed. PLAUSIBLE because whether the engine also re-reads a changed vault on its own (library sweep) is cards-library's territory and was not checked.
- Evidence: code read of `drop`/`_run_build`; recipe text.
- Ledger: related to CARDS_TWO_PROJECTS §6.1 (open, owner decision)
- Suggested change: give the "just restart" case its own command (`install_dashboard_app.py restart`: docker restart + the deadline health poll from deploy-nas-2/3, no snapshot needed because nothing on disk changes), and say in both CLAUDE.md files that one episode's new data needs only Close/Open on `/cards`.
- Effort / risk: S; low.

### deploy-nas-9 - A routine run `docker pull`s an image it will not run
- Category: deploy
- Severity: low
- Confidence: CONFIRMED
- Where: server/install_dashboard_app.py:7166-7167, 2686-2724; restart path 7189-7204
- What: step 2h pulls `[stack] image` (or the flag) on every image-mode run, including the restart path, which the code itself says "keeps the container's CURRENT image". With `site.toml` stale, that is a pull of an older digest nothing will start.
- Cost / failure scenario: 1 SSH + a registry round trip per run when the image is cached; when the NAS has pruned it, a 157 MB download (measured image size) of an image nobody uses, on a 900 s timeout.
- Evidence: code read; GHCR manifest size.
- Ledger: new
- Suggested change: pull only when the run is going to create/recreate, or when the requested image differs from the live one (the same `docker inspect` as deploy-nas-1).
- Effort / risk: S; low.

### deploy-nas-10 - A Cards or Sorter deploy runs the whole site provisioning (and needs every secret) to change one read-only directory
- Category: streamline
- Severity: medium
- Confidence: CONFIRMED
- Where: server/install_dashboard_app.py:6186-6230 (b-roll token refusal), 6367-6496 (all secrets, API key, cert pin, admins), 6605-6609, 6665-7009 (steps 0-1, assets, archive, music library, ffmpeg, venv quarantine)
- What: the only thing that changes in C/D/E is `cards-web` or `sorter-web` plus a restart. The run still refuses without `BROLL_INGEST_TOKEN`, `DASH_RELEASE_PUBKEYS`, `TRUENAS_API_KEY` rules etc., probes the uid, makes 8 provisioning SSH calls (host dirs with recursive chowns, backup folder, staging prune, shared assets, b-roll archive, music library, ffmpeg presence, venv quarantine) and, on the recipe, re-renders the full compose. This is why the recipe must be "secrets and deploy in ONE PowerShell command" and why it only works from creator-1's desktop session (DPAPI).
- Cost / failure scenario: per Cards/Sorter deploy, ~10 SSH connections and their privileged commands that cannot affect the outcome (estimated 10-25 s), a snapshot that is right to keep, and a dependency on five unrelated secrets being loadable. The main() function that does all of it is ~1,480 lines (5936-7417) and is where the last several deploy bugs (SERVER-8, OPS-1/2/3, server-tools-b-5) landed.
- Evidence: code read.
- Ledger: new
- Suggested change: subcommands with their own short paths, sharing the existing helpers: `cards`/`sorter` = connect once, read live state, snapshot `[apps] root`, `install_tree` for the changed tree(s), `docker restart`, deadline health poll against the pre-restart version; needs only the NAS credential. `restart` = the last two steps. `image --to <digest>` = the current full path with deploy-nas-1's guards. The current full run stays the default for a fresh install and for compose changes. Saving: roughly 20 of ~31 SSH connections and the delete/create on the three routine cases.
- Effort / risk: M; low (it reuses `install_tree`, `snapshot_before` and the probes unchanged).

## Proposal: one command per case, digest-safe

All keep snapshot-before-privileged (`snapshot_before` on `[apps] root`) and stage-verify-swap (`install_tree` unchanged). "Live state" is ONE SSH at the start: `docker inspect` image + `cat` both `DEPLOYED_COMMIT` + in-container health version.

| case | today | proposed | steps (manual) | SSH | downtime (est.) |
|---|---|---|---|---|---|
| A new image | 7 manual, recreate, site.toml edited by hand | `install_dashboard_app.py image --to <digest\|latest-green>`: refuses older than live without `--allow-older`, recreates only if compose or image differs, polls health, records the digest | 7 -> 2 (push, run) | ~31 -> ~14 | unchanged (recreate is needed) but no false FAILED |
| B OTA | Packages [APPLY] | unchanged | - | 0 | 15-40 s |
| C Cards | 5 manual, recreate, Sorter re-shipped, FAILED | `install_dashboard_app.py cards [--commit <sha>]` | 5 -> 2 (commit, run) | ~31 -> ~7 | 1-3 min -> 20-60 s |
| D Sorter | 6 manual (+ live Cards sha), same | `install_dashboard_app.py sorter [--commit <sha>]` | 6 -> 2 | ~31 -> ~7 | 1-3 min -> 20-60 s |
| E vault data | the full C recipe | `install_dashboard_app.py restart`, or Close/Open the episode on /cards | 5 -> 1 | ~31 -> ~2 | 1-3 min -> 20-60 s, or 0 |

With deploy-nas-4's connection reuse the remaining SSH count costs one handshake. Wall-clock saving per Cards/Sorter deploy, estimated: 40-120 s of downtime (no delete/create), 150 s of false polling when VERSION is ahead (deploy-nas-3), 15-40 s of handshakes, and the manual `live.sh` + `docker ps` round trips (a few minutes of operator time). Megabytes: ~3 MB / 320 files per Cards ship (deploy-nas-7) and the whole other tree (1.6-8.5 MB) per deploy (deploy-nas-5); up to 157 MB of needless pull (deploy-nas-9).

## What is already good
- Image layering: the lockfile is the only input to the 108 MB venv layer (deps stage copies `requirements.lock` alone), every code change is 2.6 MB of layers, `CCSYNC_GIT_SHA` is declared last, and the `chmod -R a+rX` layer is 0.25 MB (measured), so a code-only image update pulls about 3 MB. Do not "optimise" the Dockerfile order.
- The OTA path (B): signed record, stage-verify against database copies in a subprocess, sqlite-API backups, bounded `/data/code` and `/data/backups`, exit 75 instead of a container restart. It is the cheapest and safest deploy in the product.
- `install_tree`: one source walk, count+bytes verify via metadata only (SERVER-6), atomic rename with rollback, prune that skips a still-mounted backup. Keep it as the primitive for every proposal above.
- One snapshot per run (`snapshot_before` is called once in main()); it is not duplicated.
- `.dockerignore` keeps the context to the four trees plus the named customer docs.

## Coverage note
Not read: the Synology half of main() and `backends/synology.py`, the music-data push (`install_music_db`, 1.4 GB path), `provision_ffmpeg`/`provision_node` bodies, `compose_config`/`compose_variables` (3120-3950) for drift against `compose.image.yaml`, `select_code_root.py`, `tools/build_dashboard_bundle.py`. No NAS-side timing was possible: every downtime and handshake figure is estimated. The app delete/create job duration on TrueNAS is the largest unmeasured number; one `time` around a recreate in the next real deploy would settle it.

## OUT OF TERRITORY
- .github/workflows/image.yml: builds and pushes an image (1.3-4.2 min) on every push to `main`, including companion-only commits; a `paths:` filter on dashboard/, broll/web, music/web, ytdl/web, docs/legal would skip most (deploy-release).
- dashboard/deploy/Dockerfile:29-31: comment still says the file "has never been through docker build"; it has been built by CI since 2026-08-17.
- E:\Projects\Editing\ccsync\site.toml `[stack] image` is annotated 0.7.78 while SORTER_DEPLOY.md records 0.7.79 going live on 2026-11-10 (operator data, not code).
