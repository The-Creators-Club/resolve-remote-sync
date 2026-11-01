# Pre-launch resilience review, lens res-deps: external dependency failure

Date 2026-10-06, HEAD 08b40eb plus the uncommitted working tree. Read-only review.

**What I covered:** how the installers pick rclone and Syncthing, and how the companion
resolves them at run time (`installer/windows_bootstrap.ps1` sections 2 and 6,
`installer/macos_bootstrap.sh`, `sync/rclone_lane.py` `rclone_available`). How
ffmpeg is resolved (`ffmpeg_tools._resolve_binary`, `sidecar_tools`). Syncthing's
self-upgrade: I read the `autoUpgradeIntervalH` value in this rig's ccsync-generated
`~/.ccsync/syncthing/config.xml`. The TrueNAS backend (`nas/truenas.py`,
`server/common.py` `truenas_api` / `snapshot_before`). The AI provider chain
(`ai_providers.py` `provider_states` / `resolved` / `api_set_ai_key`,
`ytdl/web/ytdlweb/ai_backend.py`, `claude_cli.py`, `worker.py`'s two ClaudeError
handlers, `broll/indexer/broll_index/claude_client.py`'s retry policy, the hardcoded
model ids). The server's yt-dlp nightly (CR-361: `run.sh`, `ytdlp_nightly.py`).
`ytdl/web/ytdlweb/vendor` EJS remote components. The alert registry (`alerts.ALERT_KINDS`),
for whether each of these failures reaches anyone. The Tailscale sidecar
(`compose.appliance.yaml`, `tailscale_local.py`) and the appliance's other image pins.
Companion TLS trust (`win_trust.py`, `sidecar_tools` CR-280). The release-feed URL
configuration. The Claude Code CLI auto-updater (`cli_tools.py`).

**What I checked them against:** the 2026-08-28 and 2026-09-03 sweep ledgers
(YT-1, YT-10, CYT-7, CYT-9, OPS-13, OPS-15, OPS-19, REL-11) and KNOWN_BUGS (CR-280,
CR-350, CR-361). Already fixed, so not re-reported: YT-1/CYT-7 (yt-dlp freshness and
its alert), REL-11 (feed staleness), CR-280/CR-350 (CA bundle and expired-root
handling), DDIAG-16 (alert-sink evidence), and the b-roll indexer's 429/529 backoff,
which is sound.

**Not covered:** Synology DSM API drift in detail (`nas/synology.py`, 1,165 lines,
only skimmed), OIDC provider outage, whisper/MulticamPipeline (an in-house set-up, not
customer-facing), PyPI/GHCR availability during a fresh appliance install, and the
music indexer's model downloads.

---

### res-deps-1 - The rclone and Syncthing pins are only a last resort; the fleet runs whatever version PATH, winget, scoop or brew supplies
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `installer/windows_bootstrap.ps1:1075-1112` (rclone), `:1257-1300` (Syncthing, `Get-SyncthingExePath`); `installer/macos_bootstrap.sh:1740-1760`; `companion/src/ccsync_companion/config.py:353,1108` (`rclone_path = "rclone"`); `sync/rclone_lane.py:1108-1145` (`rclone_available`: PATH lookup plus `rclone version` exit code, no version check); `sync/rclone_lane.py:2423-2476` (lane B's tally parses rclone's English log `msg` strings: "Copied", "Moved", "Deleted", the `--backup-dir` line)
- **What:** The installers do these in order:
  1. Accept any rclone or Syncthing already on PATH, at any version ("already installed: ...").
  2. Otherwise run `winget install` / `scoop install` / `brew install`, which installs whatever version is current that day, with no checksum.
  3. Only if all of that fails, download the pinned, sha256-verified `v1.75.0` / `v2.1.3`.

  Every Windows 11 machine has winget, so step 2 is the normal path, and the pin almost never applies. At run time the companion resolves the bare name `rclone` through PATH, so a later `winget upgrade --all` (by the editor, or by a customer's IT) swaps the sync engine under it. Nothing records or checks the version. Lane B's trash and delete accounting, the move probe and the breaker inputs all read rclone's log message text. The flag set (`--max-duration` exit code 10, `--stats-log-level`, `--max-delete-size`) is also "measured against the bundled 1.74.4".
- **Scenario:**
  - A customer laptop has `rclone 1.53` from an old tutorial, or Chocolatey's copy. The installer prints "rclone already installed" and the companion runs it. A flag it does not know fails every pass with a usage error.
  - Worse, a future rclone reword of the per-file "Deleted"/backup-dir log line leaves `RcloneRunTally` counting zero moved-aside files. The lane-guard breaker and the editor-facing trash notice then go blind, while `--backup-dir` keeps moving files. Each site is then on its own sync engine version, and nobody can say which.
- **Recommendation:**
  1. Make the pinned, checksum-verified download the default.
  2. Install it into `%LOCALAPPDATA%\ccsync\bin` (and the macOS equivalent), and write that absolute path into `rclone_path` / the Syncthing launch command.
  3. Use a PATH or winget copy only on an explicit flag.
  4. In the companion, run `rclone version` once and report it in `capabilities` / the report. Refuse lane B (park, never error) below a floor or outside a tested major.minor, and alert on version skew across the fleet.
  5. Add the cross-file pin-equality test OPS-15 proposed, plus a site-manifest override for a withdrawn asset.
- **Known:** OPS-15 (usability-resilience sweep 2026-09-03; still open: no override, no cross-file test). COMMERCIAL_READINESS.md table row "rclone · Syncthing · Tailscale: winget/brew/zip (latest, no checksum)": the pin was added only as a fallback behind winget, so this part remains.

### res-deps-2 - Syncthing on every editor machine upgrades itself every 12 hours, which defeats the pin and restarts lane C on upstream's schedule
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `installer/windows_bootstrap.ps1:1960-2020` (`syncthing generate` then `serve --no-browser --home=...`, with no options written); `installer/macos_bootstrap.sh:~2012`; nothing anywhere in the repo sets `autoUpgradeIntervalH` or `STNOUPGRADE` (repo-wide grep: zero hits). This base rig's ccsync-generated `~/.ccsync/syncthing/config.xml` reads `<autoUpgradeIntervalH>12</autoUpgradeIntervalH>`.
- **What:** Syncthing's official release binaries (the GitHub zip the pin points at, and the winget package) upgrade themselves by default. The companion never turns that off. Every editor machine therefore replaces the binary that `sha256` was checked against, and restarts its daemon, whenever upstream publishes. The server's Syncthing stays on whatever compose pins (`syncthing/syncthing:1.30.0` in all three compose files).
- **Scenario:** Upstream ships a 2.x point release with a regression, or with a behaviour change: ignore-pattern semantics, a new default, a database migration on first start (2.0 itself ran a long one-time migration). Within 12 hours every editor machine on every customer site runs it, untested by the vendor. Each upgrade restarts Syncthing mid-transfer. The CR-xx supervisor brings it back, but a long migration reads as `engine_down` on every machine at once. Rolling back means a new installer. Meanwhile the fleet, which the installer meant to put on one version, drifts across several.
- **Recommendation:** After `generate`, set `options.autoUpgradeIntervalH = 0` (config.xml edit, or `PATCH /rest/config/options` from `syncthing_admin`, which already writes options). Also enforce it in the companion's Syncthing supervisor on every start, so existing installs are corrected by a companion update. Make Syncthing upgrades a vendor decision that ships with the companion or the installer, and report the running Syncthing version in the machine report.
- **Known:** not recorded.

### res-deps-3 - Every NAS operation uses TrueNAS's REST API (`/api/v2.0`), which iXsystems has deprecated for removal; a routine NAS upgrade would break provisioning and quietly remove the snapshot safety net
- **Severity:** high
- **Confidence:** CONFIRMED (the code depends only on REST). The upstream timeline is PLAUSIBLE: the REST API was deprecated in TrueNAS 25.04 in favour of the JSON-RPC 2.0 WebSocket API, with removal announced for a 2026 release. Check the exact release against iX's current notes.
- **Where:** `dashboard/src/ccsync_dashboard/nas/truenas.py:111-140` (`_request`, base `https://{host}/api/v2.0`, the only transport); `server/common.py:1339` (`truenas_api`); `server/install_dashboard_app.py:143-155`, `server/install_syncthing_app.py`, `server/setup_editor_account.py`, `server/create_api_key.py`; `server/common.py:1992-2044` (`snapshot_before`: best-effort by default, so a failing API means "WARNING ... Continuing" on stderr).
- **What:**
  - **Dashboard.** Account provisioning, set/reset password, delete user, snapshot task listing (protection/recovery), `system_info` and editor listing all go through `/api/v2.0`.
  - **Base-rig scripts.** Deploy, Syncthing app install, editor account setup, API key creation and snapshots do too.
  - **No probing.** Nothing probes the NAS version or API generation, and no JSON-RPC client exists.
  - **Snapshot fallback.** `snapshot_before` is best-effort unless `CCSYNC_REQUIRE_SNAPSHOT` is set. So the recursive `chown -R` and the deploy swap would run with no pre-change snapshot, and say so only on the operator's terminal.
- **Scenario:** A customer's admin clicks "update" in the TrueNAS UI to the release that drops REST. They do this on a site we cannot reach, because a vendor-neutral appliance is supposed to survive NAS updates.
  - From then on, adding an editor fails, and so does resetting a password.
  - `protection` / `recovery` can no longer list snapshot tasks.
  - The next dashboard deploy (`install_dashboard_app.py`) fails. Dashboard OTA code updates still work, but nothing that redeploys the stack does.
  - A `setup_tree.py` or `chown -R` run proceeds with no snapshot behind it.
  - The 404/405 errors read as "the NAS answered 404 on /user", which tells nobody that the API generation changed.
- **Recommendation:**
  1. Before launch, add a JSON-RPC (WebSocket `/api/current`) implementation of `NasBackend`, choose between it and REST from `system.version`, and cover both in the suite against recorded fixtures.
  2. Until then, publish a "supported TrueNAS versions" line in the install docs, and add an alert/notice kind for "the NAS API answered 404/405 to a known route". Name the likely cause there: a NAS upgrade to an unsupported release.
  3. Make `snapshot_before` strict by default for the recursive privileged operations.
- **Known:** not recorded.

### res-deps-4 - Nothing watches Tailscale node-key expiry; the appliance logs in interactively, so its node expires on Tailscale's schedule and takes the whole fleet with it
- **Severity:** high
- **Confidence:** CONFIRMED that nothing checks it: no code reads `KeyExpiry`, and no doc says to disable key expiry (repo-wide grep). The expiry itself is PLAUSIBLE, because it depends on the customer's tailnet settings (Tailscale's default for user-authenticated devices is 180 days).
- **Where:** `dashboard/deploy/compose.appliance.yaml:357-421` (tailscaled run directly and logged in through `login-interactive`, no `TS_AUTHKEY` / tag); `dashboard/src/ccsync_dashboard/tailscale_local.py:105-122` (`summarise` keeps four fields, `Self.KeyExpiry` is dropped); `setup_engine.py:1029-1126`; `alerts.ALERT_KINDS` (no tailnet kind); docs/APPLIANCE_INSTALL.md, CLIENT_FOLDERS.md (Funnel), memory "Tailscale-only access": Serve is the only publish path.
- **What:**
  - **Single path.** The product's only network path between editors and the server is the tailnet: dashboard over Serve, SFTP lanes, Syncthing to the NAS, client links over Funnel.
  - **Expiry is invisible.** The NAS node is logged in as a user device. When its key expires, the NAS drops off the tailnet, and the dashboard has no alert kind for that.
  - **Editor machines.** These are also user devices. Each expires on its own clock and shows up only as `machine_silent`.
- **Scenario:** Day 180 after a customer's install: the NAS node key expires.
  - Every companion fails to report, and lanes A, B and C stop on every machine at once. Editors see "cannot reach the dashboard". Client links on Funnel die.
  - The dashboard still has internet egress, so it mails "a computer has gone quiet" once for every machine. It never names the cause, which is one click in the Tailscale admin console.
  - The dashboard itself is reachable only on the tailnet, so the admin cannot open it to read the alerts either.
  - The same thing then happens again to each editor laptop, on its own schedule.
- **Recommendation:**
  1. Read `Self.KeyExpiry` (and, on the base-rig path, `tailscale status --json`) in the collector.
  2. Add an alert kind that fires 14 days before expiry and names the fix ("disable key expiry for this machine in the Tailscale admin console").
  3. Have the appliance wizard tell the admin to disable expiry on the NAS node, or join with a tagged auth key, where expiry is off by default.
  4. Add a "the whole fleet went silent at once" aggregate finding that names the server's own connectivity as the likely cause, instead of N machine_silent rows.
  5. Have companions report their own node's `KeyExpiry` (LocalAPI, read-only) so an editor's expiring laptop shows up before it goes silent.
- **Known:** not recorded.

### res-deps-5 - An AI provider that stops working (revoked key, exhausted credit, outage) stays selected, fails every job, and nobody with the power to fix it is told
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/ai_providers.py:866-880` (an API row is `available = bool(key)`), `:953-972` (`resolved`: first available, no runtime failover), `:1113-1137` (`api_set_ai_key`: no live check); `ytdl/web/ytdlweb/ai_backend.py:477-497` (402/429/529/404 after the SDK's two retries become `ERR_OUTPUT`); `ytdl/web/ytdlweb/worker.py:380-387` (generate-terms `ClaudeError` ends the job `failed`); `claude_cli.py:1130-1146` (health is an in-memory dict, `note_failure`); `dashboard/src/ccsync_dashboard/ytdl.py:825-871` (the health snapshot carries `claude`), `alerts.py` ALERT_KINDS (no kind reads it).
- **What:**
  - **The chain never fails over.** It resolves by key presence, so a key that exists but no longer works keeps winning over a working lower-rank provider.
  - **Failures are terminal.** A sustained outage, rate limit or billing stop fails each YouTube search job outright. Generate-terms fails the job, and the relevance filter degrades. There is no retry-later.
  - **Only editors see it.** The failure shows on the editor's YOUTUBE page as a chip. The alert registry has no AI-provider kind, so the admin, who is the only person who can rotate a key or top up credit, gets no mail and no home-page problem.
- **Scenario:** The customer's Anthropic account hits its spend limit on the 20th of the month. They also entered a DeepSeek key as a backup.
  - Every editor's YouTube search fails with "the Anthropic API answered 400: ... credit balance" until the 1st.
  - The DeepSeek key is never tried.
  - The admin hears about it only when an editor complains.
  - The same shape follows a revoked key (YT-10) or a multi-hour Anthropic outage.
- **Recommendation:**
  1. Record the outcome of each real call per provider in `site_settings` (`ai_<name>_last_check`, as YT-10 proposed). Treat auth, permission and billing failures as unavailable-with-a-reason for about an hour so the chain falls through.
  2. Run `_live_api_check` on key save.
  3. Treat 429/529/5xx as retry-later (re-queue with backoff) instead of a terminal `failed`.
  4. Add an alert kind, `ai_provider_failing`, that reads the ytdl snapshot's `claude` state and the per-provider records, and names the provider and its last error.
- **Known:** YT-10 (resilience sweep 2026-08-28): still OPEN (no KNOWN_BUGS entry, and `api_set_ai_key` still stores the key unvalidated).

### res-deps-6 - Model ids are compiled in, so a model retirement upstream becomes a dated outage that only a new build fixes
- **Severity:** medium
- **Confidence:** CONFIRMED (the hardcoding). The retirement dates are upstream's.
- **Where:** `ytdl/web/ytdlweb/config.py:65` (`claude-sonnet-5`), `:82` (`gpt-4o-mini`), `:85` (`deepseek-chat`), overridable only by container env (`YTDL_CLAUDE_MODEL` ...); `broll/indexer/broll_index/claude_client.py:51-66` (alias map and price table); `dashboard/src/ccsync_dashboard/triage.py:77` (`claude-opus-5-5`); `ai_backend.py:466-471` (also sends `output_config.effort`, which not every model accepts); `ai_backend.py:492-497` (a 404 `not_found_error` is classified `ERR_OUTPUT`, not "model retired").
- **What:** Timeline Cards follows model families through the Models API and CLI aliases (2026-09-23). The other AI features do not.
  - YouTube term generation and the relevance filter, the triage agent and the b-roll indexer each name a fixed model.
  - On a customer appliance the only override is a container environment variable. There is no Settings control, and env changes need a redeploy.
- **Scenario:** Anthropic retires the model behind `claude-sonnet-5` (or OpenAI retires `gpt-4o-mini`) at its scheduled date. From that day:
  - Every YouTube search on every customer site that is not on the newest build fails with "the Anthropic API answered 404".
  - The triage agent's reports stop.
  - Nothing classifies that error as "model retired", and no alert tells the admin.
- **Recommendation:**
  1. Resolve the model for ytdl, triage and the indexer the way cards_ai does (family alias, then the newest matching id from the Models API, cached), with the pinned id only as a fallback.
  2. Map a 404 `not_found_error` on `model` to its own error class that says "this model was retired upstream; update or set a model on Settings, AI providers".
  3. Add a per-provider model field to that Settings page.
  4. Track upstream deprecation dates in the release checklist.
- **Known:** not recorded. (The Cards half is solved: CR-309 and the 2026-09-23 Models API work.)

### res-deps-7 - The server's yt-dlp nightly (CR-361) has no way back from a bad build, can shadow a newer image copy, and applies a fix only at a restart nobody is prompted to do
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `dashboard/deploy/run.sh:382-424` (`ytdlp_nightly_suffix` puts `versions/<current>` on PYTHONPATH and never compares it with the image's own yt-dlp at boot); `ytdl/web/ytdlweb/ytdlp_nightly.py:285-385` (`refresh`: the only gates are import, the extractor table and "not older than the image" at STAGING time; no rollback path); `:446-471` (`pending_restart` is exposed only in `/ytdl/api/health`); `dashboard/src/ccsync_dashboard/alerts.py:3575-3604` (`ytdl_downloads_failing` tells the admin to "check for a dashboard update: a newer build carries a newer download tool"); `PIP_ARGS` `--no-deps`.
- **What:** CR-361 (built in the working tree, unshipped) has four gaps:
  1. **No way back from a bad nightly.** A nightly that imports and builds a `YoutubeDL` but cannot download (a regression, or a dependency floor `--no-deps` kept below what it needs) becomes `current`. Nothing ever moves `current` back to `previous` or to the image copy when the canary starts failing.
  2. **The alert gives advice that cannot work.** It tells the admin to update the dashboard. But a newer image's pinned yt-dlp is shadowed by any nightly that ranks higher, and if the nightly refresh has been failing (PyPI blocked by the customer's egress rules), even a stale nightly keeps shadowing a newer image copy, because the "not older than the image" test runs only when a build is staged.
  3. **A fix waits for a restart nobody is prompted to do.** A good nightly that fixes a YouTube break sits staged until the next process start. No alert, notice or button tells anyone a restart is waiting.
  4. **The off switch is not in the product.** The only remedy, `YTDL_YTDLP_NIGHTLY=0`, is a container environment variable.
- **Scenario:** YouTube changes. The night's nightly fixes it and is staged, but the dashboard runs on for weeks, so downloads keep failing. The admin follows the alert, updates the dashboard, and the restart picks up the staged fix. If instead the nightly was the broken part, the update changes nothing: the same nightly is still `current` and still shadows the image.
- **Recommendation:**
  1. At boot (in sh, or in a tiny Python pre-step), skip the nightly when it ranks below the image's own yt-dlp.
  2. When the canary fails on build N, automatically revert `current` to `previous` (or to none, meaning the image copy) and record why.
  3. Add an alert or notice for `pending_restart` older than a few hours while `ytdl_downloads_failing` is open, with a [ RESTART THE DOWNLOADER ] action through the existing exit-75 re-exec.
  4. Rewrite the `ytdl_downloads_failing` next action for nightly-enabled sites.
  5. Put the nightly on/off switch in Settings.
- **Known:** CR-361 (BUILT, unshipped); these gaps are not recorded there.

### res-deps-8 - The appliance's Syncthing, Tailscale and SFTP images are pinned in compose with no update path, so they never get upstream security fixes
- **Severity:** medium
- **Confidence:** CONFIRMED that the pins have no update path. PLAUSIBLE that the Syncthing 1.x line is at end of life (2.0 replaced it in 2025).
- **Where:** `dashboard/deploy/compose.appliance.yaml:237` (`syncthing/syncthing:1.30.0`), `:363` (`tailscale/tailscale:v1.102.2@sha256:...`), `:291` (`ccsync-sftp:1`); `compose.yaml:711`, `compose.image.yaml:387`. Neither OTA (`dashboard_update.py`, code only) nor the image update touches those service images, and nothing in `server/` or `dashboard/` references them (grep).
- **What:** The dashboard can update itself over the air. The sidecars that move every byte cannot: the Syncthing peer every editor connects to, the Tailscale node that is the only way in, and the SFTP server lanes A and B use. They change only when someone re-runs an installer with a new compose. Editors run Syncthing 2.x (pinned 2.1.3, then self-upgraded, see res-deps-2) against a 1.30.0 server.
- **Scenario:** A Tailscale or Syncthing security advisory, or a coordination-server change that stops supporting old clients, arrives. Two years after the first sales, customer appliances still run the launch-day sidecars. The vendor has no channel to move them, and nothing tells the admin they are behind.
- **Recommendation:**
  1. Carry the sidecar image digests in the signed release manifest.
  2. Add a "stack update" action (stage-verify-swap, with a snapshot first) that the dashboard can offer the way it offers its own updates.
  3. Report each sidecar's running version on /admin/health with a "behind the supported version" notice.
  4. Move the server Syncthing to the 2.x line the editors run.
- **Known:** not recorded.

### res-deps-9 - Any ffmpeg on PATH wins over the pinned sidecar with no version floor, and the pinned sidecar comes from one individual's GitHub repo
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `companion/src/ccsync_companion/ffmpeg_tools.py:101-142` (`_managed_binary` is a fallback behind PATH, on purpose); `sidecar_tools.py:95` (`https://github.com/eugeneware/ffmpeg-static/releases/download/...`), `:607` ("A binary that is present is trusted as-is; there is no version floor").
- **What:** The `proxy-480p` / `audio-extract` / `peaks` recipes reproduce `library_engine.py`'s argv verbatim and rely on timecode carry-over that Resolve's LinkProxyMedia checks. They run on whatever ffmpeg the editor has on PATH: an ancient 4.x, or a build without libx264. The per-machine cooldown stops a failing machine from hogging the queue. But a subtly different output (lost timecode, a different default pixel format) is not a failure, and lands in the vault as a proxy Resolve refuses. The pinned asset's source is a personal repository that can be deleted or re-tagged. New machines would then get "sha256 mismatch" or a 404 and never become media-capable.
- **Recommendation:** Report the ffmpeg version and build flags in `capabilities`, and make media job kinds require a floor (or the managed copy). Mirror the pinned assets to the vendor's own release feed, keeping the same sha256 checks, so the upstream repo is not a single point of failure.
- **Known:** not recorded. (CMEDIA-3 covered the sidecar's visibility, not the version floor or the source.)

### res-deps-10 - The Claude Code CLI auto-updater has no working-call check before switching and deletes the previous version an hour later
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `dashboard/src/ccsync_dashboard/cli_tools.py:1430-1663` (`auto_update_tick` / `_auto_update_run` / `_auto_finished`); `:1366-1405` (`sweep_superseded` removes the replaced version after `PRUNE_GRACE_SECONDS`).
- **What:** It is off in the vendor build, so the first customer is safe by default; any site that turns on `ai_cli_auto_update` gets this. The updater installs the publisher's newest CLI daily and flips to it once the install finishes. Nothing runs the real `-p` call that Cards, ytdl and triage depend on before the flip, and nothing switches back when the first real calls fail. The previous version is deleted an hour after the flip. An upstream CLI change (a renamed flag, a new prompt, a changed output format; 2.1.267's model-catalog refusal is the precedent) breaks every CLI-backed AI feature on that site with no rollback button.
- **Recommendation:** Before moving `installed_version`, run the same one-token call `probe_cli` uses. On failure keep the old version and record "update refused: <reason>". Keep the previous version until N successful real calls on the new one, and offer [ GO BACK TO <previous> ] on Settings, AI providers.
- **Known:** not recorded (CR-309 built the updater).

### res-deps-11 - The dashboard's address is fixed into every machine at install, so a tailnet rename or a NAS move strands the fleet with no channel to repoint it
- **Severity:** low
- **Confidence:** PLAUSIBLE
- **Where:** `companion/src/ccsync_companion/config.py:374,1128` (`dashboard_url`), the `settings_window.py:1248-1284` editor; the installers write the tailnet host into rclone.conf (`$TailnetHost`) and the Syncthing NAS device address; `loopback_guard.py` origin allow-list.
- **What:** The fix channel is the report reply, but a companion that cannot reach the dashboard never gets one. The address the fleet uses is a MagicDNS `<host>.<tailnet>.ts.net` name, an IP or a LAN name. It changes when the customer:
  - renames the tailnet,
  - renames the NAS node, or
  - moves to a new tailnet (account consolidation, or an acquisition of the studio).

  When it changes, every machine needs a hand edit in three places: `dashboard_url`, the rclone remote host and the Syncthing NAS address. Until each is fixed, Send to Resolve 403s through the loopback guard.
- **Recommendation:**
  1. Have the site manifest publish an ordered list of dashboard addresses (MagicDNS name, tailnet IP), and have the companion cache it and try each before giving up.
  2. Derive rclone and Syncthing hosts from that cached list instead of install-time literals.
  3. Document the procedure for a planned rename: publish the new name, wait one report cycle, then rename.
- **Known:** not recorded.
