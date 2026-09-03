# Release channel and platform plumbing (REL)

## Summary
The 08-28 wave landed almost in full: the soak gate, the recall, the
`requires_dashboard` ordering field, the arch discriminator, the `+dirty`
provenance, the ship journal + `-Resume`, the key-rotation refusal, the
loopback boot-health probe, the process nonce, the `/data` gauge and the
upgrade-attempt telemetry are all in the tree and on the page. What this sweep
finds is the seams *between* those pieces: the soak gate has five doors and
guards three of them (the vendor feed and the whole macOS ship path go around
it), the one upgrade failure that can never self-heal - a REFUSED offer -
is the one that produces no telemetry and no attempt count, and the free-space
floor guards one of the three things that write to `/data`. On the usability
side the developer's honest question, "did it actually reach the fleet",
still has no answer anywhere: `ship` ends with "Editors' trays will offer
v0.9.65 on their next report" and nothing ever says whether they took it. The
biggest risk is REL-1 combined with `[releases] policy = "current"`: a second
customer's whole fleet takes a build no machine anywhere has run, with no
canary and no click. The best cheap win is REL-2 - one `run_in_threadpool`
stops the Packages page's `[ PUBLISH ]` button from freezing the entire
single-worker dashboard for up to ten minutes.

## Findings

### REL-1: the soak gate has five doors and guards three - the vendor feed and every Mac build walk past it
- **Lens:** both
- **Who:** owner / admin
- **Where:** `dashboard/src/ccsync_dashboard/api.py:5224` (`make_current_refusal`, docstring: *"One function because there are three doors into 'make current'"*), `package_store.py:199` (`if make_current: db.set_current_package(...)` - no gate), `release_feed.py:689` (`make_current=(policy == "current")`), `ui.py:3115-3137` (`[ PUBLISH + MAKE CURRENT ]`), `tools/release_macos.sh:874` and `tools/build_onboard_macos.sh:549` (`...&make_current=$MC` on the PUT). Screen: Settings -> Packages -> AVAILABLE FROM THE VENDOR.
- **Today:** verified. The Windows ship publishes with `$mc = 0` always (`installer/build_editor_package.ps1:949`) and flips through the gated route afterwards, so pathway A is canary-gated - `docs/RELEASE_PATHWAYS.md:94` says as much: *"the only path that exercises the staged -> soak (REL-1) -> make-current machinery"*. Everything else reaches the fleet through `store_verified_package(make_current=True)`, which checks the signature, the `min_version` typo and `requires_dashboard`, and then sets current with no soak, no recall check on the target and no unsigned-build confirmation. Three concrete cases: (a) `./tools/release_macos.sh --publish --make-current`, the exact command CLAUDE.md tells the owner to run on the Mac, hands every Mac editor a build nothing has run; (b) an admin clicking `[ PUBLISH + MAKE CURRENT ]` on a vendor record does the same on one click with no typed confirmation; (c) a site on `policy = "current"` does it unattended, on a daily poller, which is the shape a second customer ships with.
- **Proposed:** move the gate into `package_store.store_verified_package`: when `make_current` is asked for, call the same predicate and, on a refusal, publish STAGED and return the refusal as a *note* rather than 4xx-ing the publish (the bytes are fine; only the flip is in question). Then the Mac scripts print the same "published and STAGED - push it to one machine, let it soak, then MAKE CURRENT" text the Windows ship prints on exit 3, `[ PUBLISH + MAKE CURRENT ]` becomes `[ PUBLISH ]` + the existing typed override, and the `current` policy stages instead of flipping until one machine has run the build (a policy that is explicitly "no human here" is exactly where a canary is worth most). Keep an `[releases] soak_minutes = 0` escape for a site that wants today's behaviour.
- **Effort:** M   **Value:** critical   **Confidence:** high
- **Related:** 08-28 REL-1 (built for one door), `docs/RELEASE_PATHWAYS.md:94`

### REL-2: `[ PUBLISH ]` on the vendor feed blocks the whole dashboard for the length of the download
- **Lens:** resilience
- **Who:** admin (and every editor at once)
- **Where:** `dashboard/src/ccsync_dashboard/ui.py:3115` (`async def partial_admin_feed_publish`) calling `release_feed.publish_from_feed` at `:3131` with no `run_in_threadpool`; `release_feed.py:99` (`ARTIFACT_FETCH_TIMEOUT = 600.0`); `dashboard/deploy/run.sh:396,411` (`--workers 1`)
- **Today:** verified. The JSON twin at `release_feed.py:982` is a plain `def`, so FastAPI runs it in the threadpool - correct. The HTML route an admin actually clicks is `async`, because it awaits `_form(request)`, and then does a synchronous ~40 MB HTTPS download inside the event loop. On a single-worker uvicorn that stalls *everything*: every companion report, every lane status, the fleet grid, the b-roll and music mounts, for up to ten minutes. The same click on a slow link also loses its own answer: the packages box is re-swapped every 30 s (`templates/admin_packages.html:14`), so by the time the publish returns its `hx-target="closest .admin-packages-box"` has been detached and the success/error banner is discarded.
- **Proposed:** `await run_in_threadpool(release_feed.publish_from_feed, ...)` (one line; `ai_providers.py:927` is the pattern already in the tree). Then give the button the progress model the Dashboard panel two sections down already has: disable it, show "downloading ccsync-companion.exe (12 of 41 MB)" from a `feed_publish` status object polled the way `static/dashboard_update.js` polls its own, and stop the 30 s refresh while a publish is in flight.
- **Effort:** S (the unblock) / M (with progress)   **Value:** critical   **Confidence:** high

### REL-3: a machine that REFUSES an offer tells nobody, counts nothing, and retries forever
- **Lens:** both
- **Who:** admin
- **Where:** `companion/src/ccsync_companion/upgrade.py:1227-1266` (`_accept_offer`), `:1276` (`_log_refusal`: *"one line per distinct (version, reason)"*), `:1298-1308` (`info = None` -> `_available` never set), `companion/src/ccsync_companion/app.py:6132` (`if outcome == "failed"` is the only branch that counts an attempt; a refused offer yields `"no-offer"` -> flat `PUSHED_UPDATE_FAILED_RETRY_SECONDS`), `app.py:5403-5414` (the report's `guard["upgrade"]` block is the attempts ledger only)
- **Today:** verified. REL-8's telemetry covers *attempts* - a download that 404s, a sha mismatch, a failed exec. It does not cover the class that can never self-heal: `release signature rejected` (a mis-rotated key, or a `--emit-kind-extras` record a pre-0.9.55 build cannot parse), `below the downgrade floor`, and `plain HTTP to a public host`. Those are refused at *receipt*, so no attempt is ever made, `last_failure` stays blank, the report carries nothing, and the Packages page renders the machine identically to one that simply has not reported yet: `[ 0.9.49 ]`, `[ UPDATE NOW ]`, no `[ FAILED xN ]` chip. The evidence exists only in one `log.error` in that editor's `companion.log`. Meanwhile `_run_auto_update` re-arms every 600 s for ever, uncapped, because "no-offer" is not "failed".
- **Proposed:** have `_accept_offer` record `self.last_refusal = {"version", "reason", "at"}` and put it in `guard["upgrade"]` as `refused_version` / `refused_reason`; render it on Packages beside the machine as `[ REFUSING 0.9.65 ]` with the reason in the title, and add an `AlertKind("upgrade_refused", SEV_ERROR, "a computer is refusing every update", ...)` to `alerts.ALERT_KINDS` - a refusing machine is strictly worse than a merely outdated one, because no button on the page can fix it. Back the retry off on the same curve as a failed attempt, and make `[ UPDATE NOW ]` on a refusing machine say so instead of queueing a request that can never be honoured.
- **Effort:** M   **Value:** high   **Confidence:** high
- **Related:** 08-28 REL-7 / REL-8 (both built, both blind to this path), CR-52

### REL-4: `-EmitKindExtras` can permanently strand a machine, and nothing asks the fleet first
- **Lens:** resilience
- **Who:** owner / developer
- **Where:** `tools/sign_release.py:362-374` (*"Emitting them while any machine in the fleet is older makes that machine refuse the build with 'release signature rejected', and there is no over-the-air recovery from that"*), `tools/ship.ps1:145` and `:733` (a bare pass-through switch), `installer/build_editor_package.ps1:138,1001`
- **Today:** verified. The precondition - "once every companion in the fleet is 0.9.55+" - is stated in a code comment, in `docs/RELEASE.md` and in the owner's own memory notes, and is checked nowhere. The ship is already authenticated to the dashboard that knows every machine's reported version (it reads `/api/v1/admin/packages` for the macOS advisory at `ship.ps1:800`). One stale Mac at 0.9.49 turns this flag into a permanent, silent, hands-on-reinstall stranding of that machine. Compounding it: `-EmitKindExtras` (like `-PublishFeed`, `-FeedRepo` and `-AllowUnsignedBinary`) has no `.PARAMETER` block, so `Get-Help tools\ship.ps1` does not describe the most dangerous switch on the script.
- **Proposed:** make `-EmitKindExtras` a *gated* flag: before the build, read the packages view, and refuse when any machine that has reported in the last 30 days is below `0.9.55`, naming them ("ruskin/RUSKIN-PC is on 0.9.49 and would refuse this build for good"). Better: drop the flag entirely and derive it - the dashboard can answer "is every reporting machine at or above X" and that is the only input the decision has. Add the missing `.PARAMETER` blocks either way.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** 08-28 REL-4/REL-16 (the fields these emit), REL-7

### REL-5: no EULA ships in the image or the OTA bundle, so the wizard's first step is a green tick nobody read
- **Lens:** both
- **Who:** owner / customer admin
- **Where:** `dashboard/src/ccsync_dashboard/setup_engine.py:63` (`EULA_PATH = parents[3] / "docs" / "legal" / "EULA.md"` -> `/docs/legal/EULA.md` in the container), `:272-278` (`return TaskState(status="ok", detail="no EULA shipped in this build")`), `setup_routes.py:184-186` (returns `{"text": "", "version": None}`), `static/setup.js:52-55` (renders `"(no EULA shipped in this build)"`, `btn.disabled = true`), `dashboard/deploy/Dockerfile:87-101` (copies src/deploy/templates/static and the three web apps, no `docs/`), `tools/build_dashboard_bundle.py:84-92` (`TREES` - same seven, no `docs/`). Screen: `/setup` step `[ 1. WELCOME, EULA ]`.
- **Today:** verified end to end. On a bind-mode dev checkout the EULA is there; on the image - the shape the appliance direction is selling - the first-run wizard shows an empty licence box, a disabled `[ ACCEPT ]`, and the checklist below ticks `eula` green. The fallback's own comment reasons about not blocking the wizard, which is right, but the resulting state reads as "accepted" to every reader: the checklist, `_check_done`, and any auditor. CLAUDE.md treats the EULA's version marker as load-bearing ("bumping it pushes every editor in every fleet back through the wizard") and it has never been shown to a dashboard admin on a real deployment.
- **Proposed:** `COPY docs/legal /app/docs/legal` in the Dockerfile and `("docs/legal", "docs/legal")` in `build_dashboard_bundle.TREES` (it is ~40 KB of markdown, and `THIRD_PARTY_NOTICES.md` should ride along - it has the same problem). Then change the absent-file fallback from `ok` to `warn` with `detail="no licence agreement is included in this build, so nothing has been accepted"`, so a build that ships without one is visibly wrong rather than quietly complete.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** `docs/legal/`, COMMERCIAL_READINESS item on paperwork

### REL-6: "did it actually reach the fleet" has no answer anywhere
- **Lens:** usability
- **Who:** owner / developer
- **Where:** `tools/ship.ps1:889` (*"ship complete. Editors' trays will offer v0.9.65 on their next report."* - the last line, then exit), `tools/check_deploy_drift.ps1:607-641` (the VERDICT block speaks only about THIS machine), `:598-600` (`foreach ($o in $pkgs.outdated_machines) { Write-Drift "machine behind: ..." }`), `alerts.py:92` (`VERSIONS_BEHIND_ALERT = 3`)
- **Today:** verified. The minute after a ship, *every* machine is in `outdated_machines`, so the drift check prints a wall of "machine behind" lines that are simply the normal state of a successful ship - they carry no rollout meaning. There is no adoption number anywhere: not in the ship's exit summary, not in the drift VERDICT, not on the Packages page (which lists who is behind but never says "5 of 7 are on 0.9.65, oldest holdout last seen 3 days ago"). The one automatic signal, `versions_behind`, needs a machine to be **three** published builds behind - so a fleet that stopped upgrading after one release is silent for months.
- **Proposed:** (a) a `[ ROLLOUT ]` block in `check_deploy_drift.ps1` and in the ship's closing summary, computed from data already in `build_packages_view`: `fleet: 5 of 7 on 0.9.65 (2 behind: ruskin/RUSKIN-PC 0.9.64, 3 d; leso/Mac 0.9.64, 4 h) - 0 reverts, 0 failed attempts`; (b) a `-Watch` switch on the drift check that re-reads every 60 s until adoption is 100% or the operator stops it; (c) a new `AlertKind("rollout_stalled", SEV_WARN, "a new build is not being taken")` firing when a build has been current for more than 48 h and any machine reporting inside that window is still below it. Both (a) and (c) read state that already exists.
- **Effort:** M   **Value:** high   **Confidence:** high

### REL-7: the free-space floor guards one of the three things that write to `/data`
- **Lens:** resilience
- **Who:** admin
- **Where:** guarded: `dashboard/src/ccsync_dashboard/api.py:4980-4990` (PUT publish, 507) and `dashboard_update.py:661-666` (code apply, 507). Unguarded: `release_feed.py:775-790` (`publish_from_feed` streams the artefact straight into `settings.packages_path()`), `cli_tools.py:487-505` (`install_supported` checks writability only) with `CLAUDE_MAX_BYTES = 512 MiB` at `:191`
- **Today:** verified. REL-5 of 08-28 put a floor on the human PUT and a gauge on the page. The two writers that arrive *without* a human sizing them up are the ones that skipped it: the vendor feed's auto-publish (unattended, on a daily poller, under `stage`/`current`) and the CLI wizard's install, which downloads up to 313 MB of Claude Code onto the same volume as `dashboard.db`. A full `/data` is a SQLite write failure on the database that tells the whole fleet whether its footage is syncing.
- **Proposed:** hoist the PUT's check into a helper both publish paths call, with the feed's `record["size_bytes"]` as the declared size - and on a refusal, record it as the feed's `last_error` so the Packages banner says "could not take companion 0.9.65: 380 MiB free". In `install_supported`, add `shutil.disk_usage` against the tool's known size and refuse with "Claude Code needs ~330 MB and this volume has 210 MB free" before a byte moves. Sweep `<data>/tools/<tool>/.staging/*` older than a day at startup (only a `_finish_install` currently clears it, so a container killed mid-download leaves the part file for ever).
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** 08-28 REL-5 (built for one writer)

### REL-8: the Packages page tells the admin to run the command that publishes an untested build
- **Lens:** usability
- **Who:** admin / owner
- **Where:** `dashboard/templates/partials/admin_packages.html:239-243`: *"Publish new builds from the base rig: `.\build_editor_package.ps1 -RebuildExe -RebuildOnboard -Publish [-MakeCurrent]` uploads both the companion and the installer. Each machine's tray then shows "Update now"."*
- **Today:** verified, and it is the exact opposite of the repo's own rule. CLAUDE.md: *"There is one command. It is `tools\ship.cmd`."* `ship.ps1:672` explains at length that it runs `build_editor_package.ps1` **without** `-RebuildExe` because that switch *"would rebuild the exe untested and restamp the manifest tests_run=false, which is how ship published a companion to the whole fleet with the companion suite never executed (OPS-1)"*. The page also uses curly quotes around "Update now" where every other string on it uses the bracket style.
- **Proposed:** replace the block with: `Publish new builds from the base rig with one command: [ tools\ship.cmd ]. It runs the gates, both test suites, the build, the publish and the soak-gated flip. See docs/RELEASE.md.` Nothing on a customer-facing page should name a script flag that is a known footgun.
- **Effort:** S   **Value:** med   **Confidence:** high

### REL-9: `publish_latest` signs off with a sentence that is false on the sites that matter
- **Lens:** usability
- **Who:** owner / developer
- **Where:** `tools/publish_latest.py:409-411`: *"the fleet does NOT have these yet: the dashboard offers a feed build only after Settings > Packages > check, and an admin clicks Publish ([releases] policy = manual)."*
- **Today:** verified. That is the `manual` story, printed unconditionally - including when `--make-current` was passed, which is what `docs/RELEASE_PATHWAYS.md:53` tells you to always do, and including for every site on `policy = "current"`, which is what this studio's own `site.toml` uses (`RELEASE_PATHWAYS.md:64`). On those sites the build reaches the fleet within one poll with nobody clicking anything. The operator is told the opposite of what is about to happen.
- **Proposed:** make the closing line conditional on `--make-current` and say what it actually means: *"published and pointed CURRENT. Any dashboard on `policy = current` will publish this and offer it to its whole fleet on its next check (default: daily; a container restart checks 10 s after boot). Sites on `manual` need Settings > Packages > [ CHECK NOW ] > [ PUBLISH ]."* Add the recall command (`publish_feed.py --retract`) to the same block, because that is the sentence you want in front of you at the moment you learn the build is bad.
- **Effort:** S   **Value:** med   **Confidence:** high

### REL-10: the first-run wizard's software step points at a page that has not held the packages table since 2026-08-18
- **Lens:** usability
- **Who:** owner / customer admin
- **Where:** `dashboard/src/ccsync_dashboard/setup_engine.py:1145-1149`: `detail="no companion build is current for any platform: publish one on the Users page, under PUBLISHED PACKAGES"`; the table lives at `/admin/packages` (`ui.py:2625`), and `ui.py:1817-1819` records the move: *"No packages context here since 2026-08-18: the packages table ... are page_admin_packages() now."*
- **Today:** verified. This is the only next-action a brand-new customer gets for "your editors have nothing to install", and it names the wrong page. The `editors` task next to it (`setup_engine.py:1104`, "Users page, add one") is still correct, which makes the wrong one harder to spot.
- **Proposed:** `"no companion build is current for any platform: Settings, then PACKAGES - publish one from the vendor feed under [ AVAILABLE FROM THE VENDOR ]."` And since every task detail is a next action, add a test that each `detail` naming a page names one that exists (the nav list is a fixed set).
- **Effort:** S   **Value:** med   **Confidence:** high

### REL-11: the feed panel says when it last checked and never when it will check again
- **Lens:** usability
- **Who:** admin
- **Where:** `dashboard/templates/partials/admin_packages.html:257-261` (`feed: <url> · last checked {{ ... | ago }}`), `release_feed.py:925` (`interval = max(POLLER_MIN_INTERVAL, settings.release_feed_interval or 86400.0)`), `release_feed.py:105-107` (first check shortly after boot)
- **Today:** verified. The default interval is a **day**, and nothing on the page says so. An admin who has just been told by the vendor that a fix is out sees "last checked 19 hours ago", has no idea whether waiting five minutes would help, and either clicks `[ CHECK NOW ]` (correct) or waits (wrong). The banner for a stale feed exists (REL-11 of 08-28, `feed_stale`), but that only fires after a week of failures - it says nothing about the normal cadence.
- **Proposed:** one line: `feed: <url> · last checked 19 h ago · checks every 24 h · next in about 5 h`, and when `last_error` is set, `next retry in ...` instead. Same data, already in `settings` and `feed_state`.
- **Effort:** S   **Value:** med   **Confidence:** high

### REL-12: neither long-running button on the Packages page shows that anything is happening
- **Lens:** usability
- **Who:** admin
- **Where:** `admin_packages.html:262-265` (`[ CHECK NOW ]`), `:296-312` (`[ PUBLISH ]`, `[ PUBLISH + MAKE CURRENT ]`), `:79-91` (`[ PUSH TO ONE MACHINE ]`) - none carries `hx-indicator`, and no `.htmx-request` rule exists in `dashboard/static/*.css` (grepped)
- **Today:** verified. `[ CHECK NOW ]` is a network round trip to a host outside the customer's control with a 10 s timeout; `[ PUBLISH ]` is a multi-megabyte download (REL-2). Both look identical to a dead button for their whole duration, so the natural response is a second click - which for `[ PUBLISH ]` starts a second download of the same artefact (the 409 comes only after the first one finishes and inserts the row). The Dashboard panel immediately below has a full progress model with polling and a "restarting - the dashboard is offline for about ten seconds" line; the section above it has nothing.
- **Proposed:** add a shared `.htmx-request` rule (dim the button, append a `...`) plus `hx-disabled-elt="this"` on the four long forms - two lines of CSS and one attribute each. For `[ PUBLISH ]`, the status object from REL-2.
- **Effort:** S   **Value:** med   **Confidence:** high

### REL-13: the Mac half of every ship is an advisory line that scrolls past, once
- **Lens:** usability
- **Who:** owner
- **Where:** `tools/ship.ps1:830-836` (a yellow WARNING naming the two Mac commands, then `exit 0` at the end regardless), `tools/check_deploy_drift.ps1:585-596` (`Write-Drift ... "(advisory)"`, explicitly outside the VERDICT), no `notices`/`alerts` kind for it (grepped `ALERT_KINDS`)
- **Today:** verified, and the memory notes confirm the outcome: Mac builds have been "owed" across many ships, and one Mac sat on 0.9.2 for weeks. The signal exists exactly twice per ship, in the scrollback of a terminal, in yellow, between two green lines. Nothing durable records "the macOS channel is 6 versions behind", so nothing ever reminds the owner on a day he is not shipping.
- **Proposed:** the dashboard already knows both current versions. Add `AlertKind("platform_channel_stale", SEV_WARN, "one platform's build is behind", ...)` firing when the current companion for one platform is more than N days older than another's, with the next action being the two Mac commands verbatim - so it lands in PROBLEMS THE SERVER FOUND and the Monday report, where a non-technical owner will actually meet it. Keep the ship line as is.
- **Effort:** S   **Value:** med   **Confidence:** high
- **Related:** `docs/SELF_DIAGNOSIS.md` (adding a check is adding a registry row)

### REL-14: losing the release key ends the product, and nothing but a paragraph of prose protects it
- **Lens:** resilience
- **Who:** owner
- **Where:** `docs/RELEASE.md:666-669` (*"Back the key file up offline. Losing it means you can never offer the fleet another build ... the only way out is a hand reinstall on every machine."*), `tools/release_key.py:95-129` (`new` prints the public half and a "Next:" line, says nothing about backing up), no `backup`/`export` subcommand
- **Today:** verified. `~/.ccsync-release/release.key` is 32 bytes on one Windows profile on one workstation, deliberately never on GitHub, and its loss is unrecoverable for every fleet that exists. The strongest statement of that fact lives on line 668 of a 1200-line runbook. Nothing in `ship.cmd`, `publish_latest` or the drift check ever asks whether a copy exists.
- **Proposed:** `release_key.py new` should end with the warning in the same voice `bake` uses for a replaced key, and offer `release_key.py backup --to <path>` writing a passphrase-wrapped copy (the ed25519 module is already in-tree; a scrypt+XSalsa wrap is not needed - a printed base64 the owner puts in a password manager is enough and is what a non-technical owner will actually do). Record `backed_up_at` beside the key and have `ship.cmd`'s gates print one line when it is absent: *"this rig's release key has no recorded backup. If this machine dies, no fleet can ever be updated again: python tools\release_key.py backup"*. Never a refusal.
- **Effort:** S   **Value:** med   **Confidence:** high

### REL-15: an install started in the CLI wizard does not survive a container restart, and says nothing about it
- **Lens:** resilience
- **Who:** admin
- **Where:** `dashboard/src/ccsync_dashboard/cli_tools.py:768-790` (`start_install` -> `_install_running` / `_install_status`, module globals), `:791-812` (`_install_worker`, a daemon thread), `:834-836` and `:900-902` (the `.staging` part file), `:954-964` (`_prune_old_versions`, called only from `_finish_install`)
- **Today:** verified. A 313 MB download over a slow customer link takes minutes; a `docker restart`, an image update or an OOM kill in that window loses the status entirely - the page comes back saying "not installed", with no trace that anything was in flight - and leaves the `.part` behind, which nothing sweeps until a *later successful* install prunes `.staging`. `_download`'s `except BaseException: dest.unlink()` handles every in-process failure correctly; it cannot handle SIGKILL.
- **Proposed:** persist the in-flight state next to the tool (`<data>/tools/<tool>/install.json`: version, url, bytes, started_at) and read it at status time: a record with no running thread renders as `[ INTERRUPTED ]` with a `[ TRY AGAIN ]` button, not as "not installed". Sweep `.staging/*` older than 24 h at module import, the way `api._sweep_stale_parts` already does for package uploads.
- **Effort:** S   **Value:** med   **Confidence:** high

### REL-16: `[ ROLL THE FLEET BACK ]` is offered only for companions, and only while the recall banner is on screen
- **Lens:** usability
- **Who:** admin
- **Where:** `dashboard/templates/partials/admin_packages.html:150-172` (`{% for p in packages.retracted %}` ... `{% if p.kind == "companion" and p.machines_running %}`), `api.py:5360` (`roll_fleet_back`)
- **Today:** verified. The recall path is good, but its recovery button is reachable only from a *vendor recall*. There is no "put the fleet back on 0.9.64" control for the far commoner case: the owner ships a build, an editor reports something broken an hour later, and the build was never recalled by anyone. Today the recovery is to click `[ MAKE CURRENT ]` on the older row (which the gate correctly allows, since `ever_current` short-circuits the soak) and then `[ UPDATE NOW ]` on every machine individually, because a companion refuses to move backwards on its own.
- **Proposed:** attach the same control to any non-current companion row that machines are currently running: `[ PUT THE FLEET BACK ON 0.9.64 ]`, with the same confirm text and the same `machine_update_request` fan-out `roll_fleet_back` already writes. One template change and a relaxed condition on an existing route.
- **Effort:** S   **Value:** med   **Confidence:** med

## Still open from 08-28
Everything in the 08-28 REL report reads as built (soak gate, recall, `requires_dashboard`, arch, `+dirty` provenance, `.prev` on the upgrade script, ship journal + `-Resume`, key-rotation refusal, boot-health probe, process nonce, schema-aware rollback, `/data` gauge, feed health, upgrade attempt telemetry), with these carve-outs, all re-reported above as new-angle findings rather than repeats:
- REL-1 (canary): built for the PUT/HTML `MAKE CURRENT` door only - see REL-1 here.
- REL-5 (disk): the floor covers the PUT and the code apply, not the feed publish or the CLI install - see REL-7 here.
- REL-8 (upgrade telemetry): covers attempts, not refusals - see REL-3 here.
- Noted-open in 08-28 and still open, not re-analysed: `release-pipeline-8` (`min_version` is still `0.0.0` on real records, so the floor mechanism protects nothing in practice), `release-pipeline-9` (the mutable `:1` image tag).

## Cross-cutting notes
- **Whoever owns `ui.py`:** `partial_admin_feed_publish` (REL-2) is likely not the only `async def` route in that 3200-line file doing blocking work on a `--workers 1` event loop; the pattern is worth a sweep. Every other module in my territory (`ai_providers`, `cli_tools`) is scrupulous about `run_in_threadpool`, which suggests this one was missed rather than decided.
- **Alerts/notices owner:** three findings here (REL-3 `upgrade_refused`, REL-6 `rollout_stalled`, REL-13 `platform_channel_stale`) are all "add a registry row" per `SELF_DIAGNOSIS.md`, and all three read state the dashboard already holds. They would be one small batch.
- **Report schema owner:** REL-3 wants one more pair of fields in `guard["upgrade"]`. 08-28 already added that block; this is an extension, not a new section.
- **Companion lifecycle owner:** `_run_auto_update`'s "no-offer" branch (`app.py:6135`) treats "the dashboard offered nothing" and "I refused what it offered" as the same outcome. That conflation is the root of REL-3 and is a two-line distinction in that file.
- **Product repo / packaging:** `tools/run_all_tests.ps1:74` hardcodes `E:\Projects\broll-platform\web\.venv` - a path on one workstation, in a script that is exported into the customer-facing repo by `make_product_repo.ps1`. It has a documented fallback, so it is cosmetic, but it is a personal absolute path in shipped code.
