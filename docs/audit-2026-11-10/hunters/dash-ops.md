# dash-ops - dashboard ops modules: release feed, OTA self-update, package store, CLI wizard, AI provider resolver, setup, tailnet, provision helpers
Files read (approximate coverage): release_feed.py (~60%: fetch/verify, check_now, policy, publish_from_feed, poller), dashboard_update.py (~75%: preflight, extract, stage-verify, backups/prune, apply, rollback, status, heal), release_trust.py (100%), ed25519.py (100%), package_store.py (store_verified_package, soak gate), cli_tools.py (~60%: install/download, staging sweeps, auto-update tick, the whole sign-in/pty path), ai_providers.py (~55%: probe cache, probe_cli, provider_states, resolved, routes), tailnet_serve.py (tick/snapshot), setup_engine.py / setup_routes.py (task registry, routes, tailnet sign-in loop - skimmed), provision.py (scan walkers), crash_report.py (bounds), build_flavor.py, appliance_config.py / sftp_transport.py / vendor_defaults.py / internal_sftp.py (skimmed). Callers followed into cards_ai.py, collector.py, api.py (`_sweep_stale_parts`, trash), deploy/select_code_root.py.
Probes run: (1) `ed25519.verify` timed, 20 runs, dashboard venv: 2.97 ms per verify on the base rig. (2) the local `feed/channel.json` (gitignored copy of the vendor channel): 20 records, 14.8 KB. (3) `ai_providers.resolved()` with stubbed `_run` (0.5 s per spawn), Claude Code and Codex both "installed", AUTO preference: one resolve = 4 CLI spawns; 8 concurrent resolves after the cache is empty = 32 spawns. (4) size of the base rig's b-roll index copy `E:\broll-queue\broll.db`: 501,460,992 bytes (stat only). Scripts in `scratchpad\dash-ops\`.

## Findings

### dash-ops-1 - The AI provider resolver probes EVERY CLI, below the winner too, with no single-flight, on the request path
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/ai_providers.py:864-956 (`provider_states` loop), :628-703 (`probe_cli`), :966-987 (`resolved`); callers cards_ai.py:278/:419-427 (every Timeline Cards AI call), ytdl.py:750 (`make_lookup`, every ytdl AI call), ai_providers.py:1110-1119 (GET Settings -> AI providers)
- What: In AUTO, `resolved()` builds the whole table, and `provider_states` probes every CLI provider whose cache entry is older than PROBE_TTL_SECONDS (600 s). A probe is two subprocesses of the customer's CLI (`--version`, then a real one-token `-p` / `exec` call). `resolve_provider` takes the FIRST available in chain order, so once Claude Code answers, the Codex probe can only change the reason string ("ahead of ..."), never the choice. `probe_cli` holds no lock across the spawn, so every caller that arrives while the entry is expired spawns its own pair.
- Cost / failure scenario: every 600 s of AI use (Cards search/translate/edit chat, ytdl jobs, opening Settings) the first call pays Claude Code's probe PLUS Codex's probe serially before its real call: measured 4 spawns per resolve, 2 of them wasted; with N concurrent Cards calls at expiry, 4N spawns (8 calls -> 32 spawns). Each spawn of the 238 MB Claude Code binary is estimated at ~200 MB RSS, and a cold start on busy NAS disks was measured at 50 s in the module's own comment (VERSION_TIMEOUT = 90 s, LOGIN_PROBE_TIMEOUT = 60 s), so the added latency on that one user request is estimated at 5-20 s warm and up to minutes cold. Each login probe is one subscription-billed request carrying the CLI's system prompt; at 6 expiries/hour across a working day that is ~50 probe calls per CLI per day, doubled when Codex is installed. Without Codex installed the waste is the single-flight half only.
- Evidence: probe_herd.py (stubbed `_run`): `single resolve -> chose claude_code | spawns: claude_code --version 1, claude_code -p 1, codex --version 1, codex exec 1`; `8 concurrent resolves -> spawns: 32`. Code: no early exit in the `for rank, name in enumerate(PROVIDER_ORDER)` loop; `_probe_lock` guards only the dict.
- Ledger: new; related to ytdl-web-5 (2026-08-21, fixed the PINNED case only) and CR-121
- Suggested change: in AUTO, probe in chain order and stop probing once one provider is available (fill the rows below it from `unprobed_cli_state`, i.e. `probe=False`, so the page and the reason string still render); add a per-provider lock in `probe_cli` so concurrent callers wait for the one in-flight probe and read its answer. Optionally let a successful real CLI call refresh the cache entry. Must not break: the Test button's `force=True`, the pin rule (refuse, never fall through), CR-121's stale-tolerant answers, CR-355's refusal detail.
- Effort / risk: S effort; low risk

### dash-ops-2 - Every OTA apply copies every database twice, including a ~500 MB b-roll index it almost never migrates, and keeps up to eight such copies
- Category: disk-growth
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/dashboard_update.py:1660-1670 (`.dbcheck` copies, then `backup_databases`), :1203-1224, :1291-1293 (BACKUPS_KEEP_TOTAL = 8, BACKUPS_MAX_BYTES = 8 GiB), :978 (preflight demands 2x the DB sizes free)
- What: `apply` copies dashboard.db, broll.db and music.db with the SQLite backup API into `staging/.dbcheck` for stage-verify, deletes them, and then copies all three again into `/data/backups/<ts>-before-<v>/`. The second copy is taken whether or not the new code migrates that database; labels are per version, so the per-label cap of 3 never bites and retention is 8 backups or 8 GiB. A dashboard code update changes the b-roll schema rarely (broll is at v13 across ~80 dashboard versions), so the broll copy in almost every backup is a duplicate of the one before it.
- Cost / failure scenario: per apply, ~1 GB written to /data for b-roll alone (2 x ~500 MB, the size of the base rig's own copy) plus music.db (20 MB here) and dashboard.db, i.e. estimated 10-20 s of extra I/O on a NAS HDD pool inside the apply window; at steady state 8 backups x ~520 MB = ~4.2 GB of /data held, the same volume the SQLite database lives on. At a site with a larger index the 8 GiB cap is reached and preflight's `2 x db` free-space demand refuses updates earlier than it needs to.
- Evidence: code read (no branch skips an unmigrated database); `E:\broll-queue\broll.db` = 501,460,992 bytes; `music/web/data/music.db` = 20,537,344 bytes.
- Ledger: related to PL-RES-28 (open: a restore rolls broll.db and music.db back too) and PL-RES-29 (ytdl.db not backed up)
- Suggested change: have the stage-verify subprocess report each database's `user_version` before and after its migration on the copy, and back up only the databases whose version moved (always dashboard.db, which is small and is what REL-10's `backup_for_version` names). Then a restore can only ever roll back what the update actually touched, which also narrows PL-RES-28. Must not break: REL-10's schema check, `restore_backup` (it restores only what is in the directory), the free-space preflight.
- Effort / risk: S-M effort; low risk

### dash-ops-3 - Interrupted downloads on the two UNATTENDED paths leave staging files that nothing sweeps
- Category: disk-growth
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/release_feed.py:1449-1460 (feed auto-publish `.part`), api.py:6901-6923 / :7703 (`_sweep_stale_parts`, called only from the human PUT route); dashboard_update.py:1632-1634, :1751-1754 (OTA `<v>.tar.gz.part` and `<v>.staging/`), :714-791 (`_heal_orphaned_progress`), :1395-1422 (`prune_code_trees` only sees dirs carrying manifest.json)
- What: a container stop / OOM / NAS reboot during `fetch_artifact_to` skips its `unlink` and leaves `packages/<platform>/<file>.<uuid>.part` (up to ARTIFACT_MAX_BYTES 200 MiB). The only sweeper runs inside the human publish PUT, which a feed-only customer site never calls. An apply killed mid-way leaves `code/<v>.tar.gz.part` (up to 256 MiB, never swept by anything) and `code/<v>.staging/` with its `.dbcheck` database copies (~520 MB at b-roll scale), which go only when a later apply's `prune_code_trees` happens to drop them (needs 3 real trees on disk). The interrupted apply is healed to step `failed`, and the auto-apply policy never retries a failed version, so the same-name overwrite that would otherwise clean it does not come either.
- Cost / failure scenario: per interrupted fetch or apply, 0.2-0.8 GB on /data held indefinitely. Rare (needs a kill inside a download or stage-verify window of seconds to minutes), but it accumulates on exactly the appliance shape with no shell.
- Evidence: code read; `grep _sweep_stale_parts` finds one call site (api.py:7703).
- Ledger: new; same shape as REL-15 (CLI `.staging`, fixed with an import-time sweep in cli_tools.py:375-424)
- Suggested change: call `api._sweep_stale_parts(dest_dir)` (or a shared copy of it) in `publish_from_feed` before the download; in `_heal_orphaned_progress`, where the dead latch is cleared, remove `code/*.tar.gz.part` and `code/*.staging` (none can be live: their owning process is gone). Must not touch a `.part` younger than the in-flight window on the PUT path.
- Effort / risk: S effort; low risk

### dash-ops-4 - The sign-in pty master fd is closed from two threads without the session lock, and while the reader thread may still read it
- Category: concurrency
- Severity: low
- Confidence: PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/cli_tools.py:2100-2117 (`_kill`), :2016-2032 (`cancel_signin` on the request thread), :2195-2212 (`_run_strategy` loop calling `_kill`), :2271-2279 (`_read_pty`)
- What: `_kill` does `fd = session._master; session._master = -1; os.close(fd)` with no lock. A CANCEL runs `_kill` on the request thread (after up to 5 s in `proc.wait`), while the worker's 0.2 s loop sees `_cancel` and runs `_kill` too; both waits return when the child dies, and both can read the same fd before either writes -1, so the second `os.close` closes whatever reused that fd number in between (a uvicorn socket, a SQLite file). Separately, the worker closes the master after `reader.join(timeout=2)`; if a grandchild still holds the pty slave, the reader is still blocked in `os.read(master)`, and its next loop reads from the reused fd number. After `proc.kill()` there is also no `wait()`, so the child stays a zombie until the next `Popen` reaps it.
- Cost / failure scenario: needs a CANCEL (or a timeout) racing the child's exit, or a CLI that leaves a child holding the tty; the result is one stolen or closed descriptor in the dashboard process (an HTTP request or a DB handle failing once). Rare; a few sign-ins per site per year.
- Evidence: code read only; not reproduced.
- Ledger: new
- Suggested change: swap the fd under `session._lock` (`fd, session._master = session._master, -1`) and let only the reader thread close it on EOF/EIO (the killer just kills); add `proc.wait(timeout)` after `proc.kill()`.
- Effort / risk: S effort; low risk

### dash-ops-5 - The release runbook restarts the dashboard to force a feed check that a button already does, and soaking/staged records wait a whole poll interval
- Category: deploy
- Severity: low
- Confidence: CONFIRMED (the doc and the button); PLAUSIBLE (the latency, depends on site policy)
- Where: docs/RELEASE_PATHWAYS.md:67-69; dashboard/src/ccsync_dashboard/release_feed.py:1698-1717 (poller: 10 s after boot, then `release_feed_interval` = 86400 s), :939 / :963 (`_apply_policy` and `apply_dashboard_policy` run only inside `check_now`); templates/partials/admin_packages.html:349 (`[ Check now ]`, POST /partials/admin/feed/check), release_feed.py:1743 (`POST /api/v1/admin/feed/check`)
- What: step 5 of pathway B says "a `docker restart` of the dashboard container triggers a check 10 s after boot when you need it now". A restart costs the whole dashboard: the Cards engines and the `/cards/edit` child are stopped, running ytdl jobs are interrupted (the OTA path itself refuses to restart over them), every editor's report gets a connection error. The Packages page's Check now does the same check with none of that. Separately, the soak gates (DEFAULT_SOAK_MINUTES = 30 for packages, the same window for dashboard bundles) are re-evaluated only by a check, so a build first seen inside its soak waits for the next daily poll: up to 24 h of latency on a `policy = current` site for a 30-minute soak.
- Cost / failure scenario: per release published by the studio, one avoidable container restart (dashboard down for the restart plus boot, estimated 10-60 s, plus lost in-flight work); on customer sites, up to a day between "soak satisfied" and "offered to the fleet".
- Evidence: doc and code read.
- Ledger: new
- Suggested change: point the runbook at Check now (or have `tools/publish_latest.py` call the studio's check route with its minted-admin session); re-run `_apply_policy` / `apply_dashboard_policy` against the CACHED verified channel on a short timer (hourly, no network fetch, no re-verify) so a soak that ends mid-day is acted on the same day.
- Effort / risk: S effort; low risk

## What is already good
- Every artefact download is streamed to disk in 1 MiB chunks with a running sha256 and a byte cap (`release_feed.fetch_artifact_to`, `cli_tools._download`); nothing reads a package into memory. Only channel.json (capped 1 MiB, 14.8 KB today) and the 8 KB signature are read whole.
- Pure-Python Ed25519 is cheap where it is used: 2.97 ms per verify measured, once per record per feed check (20 records = ~60 ms/day) and once per publish; the verified channel is cached on app.state so admin page GETs never re-verify. Do not add `cryptography` for speed.
- Idle cost of this territory is tiny: feed poller once a day; `cli_tools.auto_update_tick` is comparisons plus a 300 s state.json read; `tailnet_serve.tick` is rate-limited to 60 s and inert with no socket; crash reports capped at 20, log rotation 5 MB x 3.
- Disk is bounded on the paths that matter: packages pruned to current + 2 newest per kind/platform, `.trash` for 30 days, code trees to 3, CLI versions to one plus a one-hour grace (CR-309), CLI `.staging` swept at first status read (REL-15).
- `setup_snapshot` / install polling spawn no subprocess (file reads and a statvfs per poll), as their docstrings promise.

## Coverage note
Did not measure the OTA restart's real downtime (needs the container); did not read setup_engine.py's individual task checks in depth, release_feed's `build_feed_view` / `record_offer_state`, provision.py's stignore builders, or the sign-in strategy table. Did not verify how often the studio's dashboard actually takes OTA bundles versus image deploys, which scales dash-ops-2.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/collector.py:1110-1141: `_creatable` calls `provision.marked_descendants(target)`, which walks a refused project's WHOLE media tree to depth 8 (it never prunes at the target itself), and the refusal re-runs every provision pass (300 s) for as long as the folder stays unprovisioned.
- dashboard/src/ccsync_dashboard/alerts.py:1357-1367: `_tailnet_state()` makes two LocalAPI socket calls per alert evaluation; cadence not checked here.
