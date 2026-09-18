# Bug hunt brief, ninth fleet hunt (2026-09-18) - read fully before touching the code

Repo: E:\Projects\Editing\ccsync (git HEAD 214869b, main: companion 0.9.74,
dashboard 0.7.49 schema v53, installer 1.0.43). The working tree has one
unrelated modified file (`broll/eval/local_vlm/config.base-rig.json`); ignore
it. You are ONE hunter in a fleet of 25; eighteen own a disjoint TERRITORY of
files, seven own a LENS that cuts across every territory. Hunt only inside
yours; a defect you notice outside it while following a call goes under
"OUT OF TERRITORY" at the bottom as one line. Do not chase it.

Why now. The eighth hunt (`docs/bug-hunt-2026-09-11b.md`) found 136 distinct
defects in the seventh hunt's fix pass; its own fix pass is commit 34a3c8f
(CR-249..CR-266). Since then, in one week, 30 commits changed 302 files
(+65,000 / -21,600 lines) WITHOUT a hunt: the evening pass of 2026-09-11
(CR-267a..i, CR-268a/b: hand moves on the server, detection v53, a locate
route, lane B moving instead of trashing), the two dashboard false alarms
(CR-269/270), the Timeline Cards engine POOL (one engine per episode,
`cards_pool.py`, `cards_landing.py`, CR-276, dashboard 0.7.47/0.7.48), the
busy-database rework (4aaca6a: "contention, not a server error"), lane C's
path-missing heal and the watchdog's rclone-progress read (CR-278/279), and
the largest of them, the **b-roll proxy tiers** feature (CR-281,
`docs/BROLL_PROXY_TIERS_PLAN.md` and its `_AUDIT.md`): a 1080p preview, an
editing proxy made at ingest and uploaded before the original, a stand-in
that Send to Resolve downloads instead of the original, a stand-in ledger
(`broll_standins.py`), a background editing-proxy upgrade, a relink pass that
must no longer undo it, geometry columns (migration 012), a tmcd-aware
drop-frame rule, and a detail API `insert` object the page forwards to the
companion. All of that shipped on 2026-09-17: the WHOLE FLEET (four machines,
Windows and one Mac) is on companion 0.9.74 and the studio dashboard runs
0.7.49 in image mode. The vendor feed carries the same. Customers elsewhere
may still run anything from companion 0.9.65 / dashboard 0.7.34 upward, so
version skew stays in scope.

What a week of unhunted work looks like, and what this hunt is for:

- a feature built in phases (proxy tiers 0-3, waves A/B, an audit folded
  back in) whose later phase changed a contract an earlier phase's code or
  test still assumes;
- a new file (`broll_standins.py`, `sync/server_locate.py`, `locate.py`,
  `cards_pool.py`, `cards_landing.py`, `deploy/select_code_root.py`) that
  has had no reader but its author;
- a wire with a new field (the `insert` object, `sync_mode`, `standin`,
  geometry columns, the locate route, `proxy_pairs` notices) where one side
  is optional and the other reads it as if it were not, or where an older
  build in the field sends nothing;
- a fix from the 09-11b pass (CR-249..CR-266) that a later commit quietly
  reverted or made unreachable;
- the "busy database" rework: a `sqlite3.OperationalError: database is
  locked` that used to be a 500 and is now something else, on EVERY route,
  not just the one it was written for;
- the engine pool: two Timeline Cards engines in one process, the refuse-
  not-evict cap, per-slug data dirs, the sw.js kill switch, and a landing
  page that must draw with no engine.

So: `git diff 34a3c8f..HEAD -- <your files>` FIRST (and `git diff
18e69f3..34a3c8f -- <your files>` second, the 09-11b fix pass, which was
hunted by nobody either), read every hunk with care, then the rest of your
territory as before.

## Rules
1. READ-ONLY. Do NOT edit, create or delete any file inside the repo, with ONE
   exception: your own report file under `docs/bug-hunt-2026-09-18/hunters/`.
   No `git` commands that change state (no stash/checkout/commit/reset/tag).
   You may run the tests that exercise your files and ad-hoc python snippets
   that import the code, from the component's venv (CLAUDE.md "Running
   tests" has the interpreter per component; run pytest from the component
   directory). Write scratch scripts to your scratchpad directory, never into
   the repo. Do NOT run `tools\run_all_tests.ps1` or another territory's whole
   suite (owner rule: the full gate runs once, centrally). Do not touch
   `~/.ccsync`, `%LOCALAPPDATA%\ccsync`, the NAS, the dashboard, Resolve, or
   any live process; this machine is the studio's base rig and its companion
   is running.
2. Read `CLAUDE.md` at the repo root FIRST (every invariant it states is a
   bug if the code violates it), then the parts of `SPEC.md` your territory
   implements, then the docs it names. For proxy tiers, the plan and the
   audit ARE the contract: `docs/BROLL_PROXY_TIERS_PLAN.md`,
   `docs/BROLL_PROXY_TIERS_PLAN_AUDIT.md`. For the engine pool,
   `docs/CARDS_TWO_PROJECTS.md`. For hand moves, `docs/HAND_MOVES_ON_THE_SERVER.md`.
3. `KNOWN_BUGS.md` (grep with `-a`, it holds a stray binary byte) is the
   ledger through CR-281. Before reporting, `grep -an` it for the function,
   file or symptom; an OPEN entry is cited, not re-described; an entry that
   says FIXED for something you find is NOT fixed IS a finding ("regression
   of CR-nn" or "CR-nn does not fix <id>"). The eighth hunt's raw reports
   (`docs/bug-hunt-2026-09-11b/hunters/`) and its builders' ledgers
   (`docs/bug-hunt-2026-09-11b/ledger/`) are your map of what was fixed
   where; the 09-11b summary lists findings that were deliberately NOT
   fixed (its "Not fixed" section) - those are cited, not re-found.
4. Hunt for REAL DEFECTS, not style: wrong logic, off-by-one, races,
   unhandled exceptions on realistic input, resource leaks, state that is not
   persisted when CLAUDE.md says it must be, security holes (auth bypass,
   path traversal, token leakage into logs/responses, missing fail-closed),
   cross-platform breakage (Windows/macOS/Linux, NFC/NFD, CRLF, drive
   letters, separators), version compares with two-digit minors (0.9.74 vs
   0.10.0), schema-migration hazards (v53 now, plus b-roll migration 012; a
   migration that cannot run twice, or on a v47 database from the 0.7.34
   build in the field, is a finding), API contract mismatches between
   companion, dashboard and the web apps (compare BOTH sides of every wire
   you see), tests that assert the wrong thing or that a bug would not fail,
   CLAUDE.md invariants the code does not enforce, and user-visible copy
   with an em dash (owner rule) in tray/popup/template/SPA/HTTP-detail
   strings.
5. RESILIENCE is half of this hunt. For every path that touches the disk,
   the network, a subprocess, a database or another machine: what happens
   when the NAS is unreachable mid-call, the disk is full, the process is
   killed between two writes, the container restarts, the DB is locked, the
   clock is wrong, the other side is one release older or newer, a file is
   half-written, a value is None because an older build did not send it, or
   an exception escapes a thread and nothing restarts it. "Green while
   dead", an in-memory-only safety latch, a retry with no backoff or
   ceiling, a thread with no supervisor, and a failure logged but never
   surfaced to the person who must act, are all findings.
6. VERIFY before you claim. Read the callee, not just the call. Trace the
   data flow. Where feasible prove it with a small snippet from the venv or
   by naming a test that would fail. A finding you could not verify is
   PLAUSIBLE, not CONFIRMED. Do not pad: five confirmed defects beat twenty
   guesses.
7. Read the tests in your territory too. A test that pins wrong behaviour,
   or mocks away the exact thing that breaks, is a finding. The
   `test_bug_hunt_2026_09_11b_*.py` files, `test_db_busy_2026_09_17.py`,
   `test_cards_pool.py`, `test_locate.py`, `test_hand_moves_detected.py`,
   `test_broll_standins.py`, `test_broll_insert_tiers.py`,
   `test_proxy_relink_standins.py` and `test_broll_proxy_upgrade.py` are the
   week's regression tests and deserve particular suspicion.
8. Time-box: about 30-45 minutes of work. The diff since 34a3c8f first, then
   the files CLAUDE.md talks about most, then the paths that touch data, the
   fleet, or an editor's Resolve.

## Output
Write your report to `docs/bug-hunt-2026-09-18/hunters/<territory-id>.md`,
Markdown, in EXACTLY this shape so the orchestrator can merge them
mechanically:

```
# <territory-id> - <one-line scope>
Files read (with approximate coverage): ...
Tests run: <command> -> <result>   (or "none")

## Findings

### <territory-id>-1 - <short title>
- Severity: high | medium | low
- Confidence: CONFIRMED | PLAUSIBLE
- Where: <path>:<line> (repo-relative, plus a second location if two-sided)
- What: <the defect in 1-3 sentences, mechanism not symptom>
- Failure scenario: <concrete input/state -> concrete wrong outcome>
- Evidence: <what you ran / read that proves it; snippet output if any>
- Ledger: <"new" | "regression of CR-nn" | "CR-nn does not fix <id>" | "related to CR-nn (open)">
- Suggested fix: <one or two sentences>

### <territory-id>-2 - ...

## Coverage note
<what you did NOT get to, and what the suite does not cover>

## OUT OF TERRITORY
- <path>: <one line>
```

Severity guide: high = data loss, sync of the wrong thing, security, a
fleet-wide outage, the dashboard or tray dying, an editor's Resolve project
damaged; medium = a feature wrong for some real input or platform, a bad
state the user cannot clear, misleading UI that causes a wrong action, a
failure nobody is told about; low = edge case, cosmetic, hygiene with a real
but small consequence.

Use a hyphen, never an em dash, in your report.

## Territories (source files; the tests that exercise them belong too)

All companion paths are under `companion/src/ccsync_companion/`, all
dashboard paths under `dashboard/src/ccsync_dashboard/`.

- **comp-sync**: `sync/*` (base, borrowed_folders, lane_guard, rclone_lane,
  repath, sequencer, server_locate, shared_folders, syncthing_admin,
  syncthing_lane, syncthing_supervisor), `selection.py`, `file_moves.py`,
  `drive_reminder.py`, `drive_swap.py`, `manifest.py`, `root_guard.py`.
  Fresh: CR-268 (lane B moves instead of trashing, `server_locate.py`),
  CR-278 (`_heal_missing_paths`), CR-279 (`seconds_since_heartbeat`).
- **comp-app**: `app.py`, `__main__.py`, `config.py`, `site.py`, `identity.py`,
  `machine.py`, `paths.py`, `canon.py`, `secretfile.py`, `eula.py`,
  `capabilities.py`, `ui_state.py`, `ui_copy.py`, `reporter.py`, `idle.py`,
  `shutdown_guard.py`, `theme.py`, `supervisor.py`, `upgrade.py`,
  `release_pubkey.py`, `ed25519.py`.
- **comp-ui**: `tray.py`, `tray_native.py`, `popup.py`, `settings_window.py`,
  `ui_dispatch.py`, `crash_report.py`, `stills.py`.
- **comp-resolve**: `resolve_bridge.py`, `resolve_journal.py`,
  `resolve_undo.py`, `resolve_prefs.py`, `script_server.py`, `fixer.py`,
  `library.py`, `proxy_gen.py`, `proxy_history.py`, `proxy_relink.py`,
  `proxy_scan.py`, `luts.py`, `bpg.py`, `consolidate.py`, `project_setup.py`,
  `watcher.py`, `timeline_cards_bridge.py`, `timeline_cards_role.py`.
  Fresh: the relink pass that must not undo a stand-in (audit F1), the
  `.mp4` offer rule, `watcher.py`'s b-roll archive changes.
- **comp-broll-tiers**: the proxy-tiers feature on the companion side, end
  to end: `broll_server.py`, `broll_fetch.py`, `broll_standins.py`,
  `broll_upload.py`, `broll_ingest.py`, `broll_ingest_media.py`,
  `ffmpeg_tools.py`, `sidecar_tools.py`, `loopback_guard.py`, and the
  `insert` object the page forwards (`broll/web/static/app.js`'s Send to
  Resolve call is yours to read for the contract, not to report on). The
  stand-in ledger, its upgrade, the "first writer wins" rule, what happens
  to a stand-in-born clip when the original later arrives, and what an old
  page (no `insert` object) or an old companion (no stand-in code) does.
- **comp-music-ytdl-jobs**: `music_server.py`, `music_ingest.py`,
  `music_worker.py`, `music_clap_sidecar.py`, `broll_vlm_sidecar.py`,
  `ingest_kinds.py`, `youtube_import.py`, `ytdl_attestation.py`,
  `ytdl_browser_login.py`, `ytdl_common.py`, `ytdl_cookies.py`,
  `ytdl_executor.py`, `ytdl_server.py`, `ytdlp_manager.py`, `jobs_media.py`,
  `jobs_runner.py`, `job_paths.py`.
- **dash-api**: `api.py`, `package_store.py`, `settings.py`, `local_users.py`,
  `provision.py`, `android.py`, `locate.py`. Fresh: the locate route
  (CR-268a), the busy-database rework on every route (4aaca6a), CR-267a..c.
- **dash-collector-alerts**: `collector.py`, `alerts.py`, `notices.py`,
  `health.py`, `invariants.py`, `protection.py`, `recovery.py`,
  `crash_report.py`, `mount_status.py`, `syncthing_client.py`. Fresh:
  hand-move detection (v53), one `proxy_pairs` notice per folder, the 5%
  vs 20 GB floor (CR-269), the retired-tree rule (CR-270).
- **dash-core**: `app.py`, `auth.py`, `sessions.py`, `oidc.py`,
  `secrets_boot.py`, `setup_api.py`, `setup_engine.py`, `setup_routes.py`,
  `site_store.py`, `truenas_client.py`, `tailscale_local.py`,
  `internal_sftp.py`, `published_docs.py`, `help.py`.
- **dash-db**: `db.py`, `links.py`, `assignments.py`, `runtime_id.py`,
  `schema.sql`, and every migration step v47..v53 against a database
  shaped like the 0.7.34 build's (v47) and the 0.7.43 build's (v52); the
  busy-database rework (4aaca6a, `test_db_busy_2026_09_17.py`) is yours
  at the db layer: what "the long writer names itself" costs, and what a
  busy answer looks like to every caller that used to catch a 500.
- **dash-mounts-ui**: `ui.py`, `broll.py`, `music.py`, `ytdl.py`,
  `dashboard/templates/*`, `dashboard/static/*` (incl. `sw.js`),
  `dashboard/deploy/*` (Dockerfile, compose, run.sh, `select_code_root.py`,
  requirements.lock), `.github/workflows/*`. Fresh: CR-267d/e/f/g/i, the
  Packages relayout, the Assignments filter, fleet-grid declutter,
  `select_code_root.py` and the retired-tree boot rule (CR-270).
- **dash-cards**: `cards.py`, `cards_ai.py`, `cards_exec.py`, `cards_tunnel.py`,
  `cards_wsgi.py`, `cards_pool.py`, `cards_landing.py`,
  `templates/cards_landing.html`, `static/sw.js` (shared with dash-mounts-ui:
  you own its kill-switch semantics, they own its serving), and the
  companion's `timeline_cards_role.py` as the other end of the tunnel (read,
  cite; comp-resolve reports on it). Fresh: the engine pool (one per
  episode, refuse-not-evict cap of 2, per-slug data dirs, the slug from an
  NFC case-folded root, `/api/root` blocked, `_routed` pushes to the
  editor's own machine), CR-276, the landing page with no engine.
- **dash-release-jobs**: `release_feed.py`, `release_trust.py`,
  `dashboard_update.py`, `jobs.py`, `ai_providers.py`, `cli_tools.py`,
  `ed25519.py`, and `tools/publish_feed.py`, `tools/publish_latest.py`,
  `tools/sign_release.py`, `tools/release_key.py` as the other end of the
  feed. Fresh: the macOS artifact slimming (c9303bd), upload-only-missing
  assets (687d0a0), the `git_dirty` string parse (CR-267c), CR-280 (macOS
  certificate verification, OPEN: is anything else on the Mac hitting it).
- **broll**: `broll/web/app/*`, `broll/web/static/*`, `broll/web/migrations/*`,
  `broll/migrations/*`, `broll/schema.sql`, `broll/web/schema.sql`. Fresh:
  geometry columns (012), the detail API's `insert` object, `edit_weight.py`,
  the fleet ingest routes declaring an editing proxy, the retry-failed 409
  fixes, client folders.
- **broll-indexer**: `broll/indexer/*` (`broll_index/*`, `tools/*`, the
  scripts, `tests/*`). Fresh: `ffmpeg_tools.py`'s tmcd-aware drop-frame
  rule, the 1080p preview, the frame check, migration 012 and schema
  parity, `fix_proxy_timecode.py` and `make_own_proxies.py` moved with the
  rule.
- **music**: `music/web/musicweb/*`, `music/web/static/*`, `music/indexer/*`.
- **ytdl-web**: `ytdl/web/ytdlweb/*`, `ytdl/web/static/*`,
  `ytdl/web/migrations/*`.
- **server-tools**: `server/*.py`, `tools/*` (py, ps1, sh, EXCEPT the four
  feed tools dash-release-jobs owns), `bench/`. Fresh: the utf-8 git decode
  in `install_dashboard_app.py` (e050413), `ship_gates.ps1`,
  `run_all_tests.ps1`, `check_deploy_drift.ps1`.
- **install-onboard**: `installer/*` (ps1, sh, and `installer/tests/*.ps1`),
  `onboarding/*`.

## Lenses (cross-cutting; read across every territory, own no file)

- **res-companion**: what an editor's MACHINE does when things go wrong.
  Trace whole failure paths end to end (a kill mid-write, a NAS that vanishes
  mid-lane, a Resolve that quits mid-relink, a drive pulled, a full disk, a
  clock jump, an upgrade mid-anything, a stand-in half-downloaded, an
  editing-proxy upgrade interrupted) through whichever files they cross.
  Report only what a territory hunter reading one file could not see.
- **res-fleet**: what the FLEET does when the server side goes wrong (the
  container restarting mid-report, a locked or busy DB under the new
  contention rule, a migration that half-ran, an OTA update that
  half-applied, the Syncthing API down, alerts that cannot be delivered, a
  halt/rollback/push command that reaches a machine on an older build, a
  hand move on the server detected while a machine is mid-upload, two Cards
  engines and a third episode). Same rule: whole paths, across files.
- **wire**: every contract between two processes, both sides side by side:
  companion report/reply (`reporter.py`, `app.py` vs `api.py`), commands
  (`commands.*`), jobs offer/claim/cancel, file moves and the locate route,
  upgrade offers and the signed record, the 8899 loopback vs the b-roll/music
  SPAs (the `insert` object above all), the fleet routes of broll/music/ytdl
  vs their companion callers (the editing-proxy declaration and upload
  order), the Cards tunnel vs `timeline_cards_role.py`, the vendor feed vs
  `release_feed.py`. A field one side sends and the other ignores, a status
  one side emits and the other cannot parse, a version gate that reads the
  wrong number, a change this week that touched one side only. State the
  older-build combinations that break (0.9.65..0.9.73 companions, 0.7.34..
  0.7.48 dashboards, a page cached by the service worker).
- **security**: auth and session gates, every fleet-credential binding
  (`cce1.` tokens must bind an identity: the CR-55 shape), path traversal on
  every route that takes a name or a path (the locate route and hand-move
  detection take PATHS; the Cards slug is minted from a path; the stand-in
  ledger names files), token/secret/password leakage into logs, responses,
  notices, alert mails and `/api/v1/site`, fail-closed on every gate, the
  client-share prefix, the `/help` audience gate, redirect following, CORS
  on 8899, the per-slug Cards data dir.
- **tests**: test QUALITY across the whole tree. For each test file added
  or changed since 34a3c8f (`git diff --stat 34a3c8f..HEAD -- '*test*'`):
  does the test fail without the fix (revert the hunk in your head, or in a
  scratch copy OUTSIDE the repo), does it test the scenario its commit
  describes, does it mock away the thing that breaks? Then the older suites:
  fixtures that bypass a gate, asserts that cannot fail, platform assumptions
  that make the macOS runner red (the companion and onboarding suites run
  there too; 214869b and 3c7cf8e were both "the release runner has no
  rclone" fixes - is there a third).
- **regression**: for EACH of the 09-11b fix pass's findings (ids in
  `docs/bug-hunt-2026-09-11b/tally.txt`, builder reports in
  `docs/bug-hunt-2026-09-11b/ledger/`, ledgered CR-249..CR-266), find the
  fix (`grep -rn <id>`) and judge whether it actually closes the hunter's
  failure scenario, the whole of it, on every platform the finding named -
  AND whether one of the 30 commits since then reverted or bypassed it.
  Prioritise the 11 highs and the mediums; sample the lows. Then CR-267..
  CR-281 the same way against their ledger text.
- **proxy-tiers**: the one feature that crosses five territories, read as
  ONE path: an original dropped on an editor's machine -> ingest makes the
  editing proxy -> declares it to the server -> uploads it before the
  original -> the indexer/preview side -> the detail API's `insert` object
  -> the page -> the companion's Send to Resolve downloads the stand-in ->
  the stand-in ledger -> Resolve gets a clip -> the background upgrade
  replaces it with the editing proxy -> the relink pass leaves it alone ->
  one day the original arrives (or never does). Judge it against the plan
  and the audit (`docs/BROLL_PROXY_TIERS_PLAN.md`, `_AUDIT.md`) section by
  section, including the audit's own "still owed" list: is anything listed
  as built that the code does not do, and what does the companion do with a
  stand-in on a WIRED rig where the original is already on P:. Report only
  what a territory hunter reading one component could not see.
