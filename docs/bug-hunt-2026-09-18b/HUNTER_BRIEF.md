# Bug hunt brief, tenth fleet hunt (2026-09-18, second of the day) - read fully before touching the code

Repo: E:\Projects\Editing\ccsync. git HEAD is still 214869b (companion
0.9.74 / dashboard 0.7.49, the build the whole fleet runs), and the WORKING
TREE holds today's entire fix pass UNCOMMITTED: about 12,000 changed lines
across 140 files plus 15 new test files, at companion 0.9.75 / dashboard
0.7.50 (schema v54). `git diff` (no arguments) IS the fix pass; `git status
--short` lists the new files. Nothing has shipped. You are ONE hunter in a
fleet of 25; eighteen own a disjoint TERRITORY of files, seven own a LENS
that cuts across every territory. Hunt only inside yours; a defect you notice
outside it while following a call goes under "OUT OF TERRITORY" at the bottom
as one line. Do not chase it.

Why now. The ninth hunt this morning (`docs/bug-hunt-2026-09-18.md`, raw
reports in `docs/bug-hunt-2026-09-18/hunters/`, adversarial verdicts in
`verifiers/`) found 132 distinct defects plus five more on the live dashboard
(`hunters/live.md`). Six Opus builders then fixed ALL of them in one
afternoon, in parallel, on disjoint file groups, with twenty-one hand-offs
between groups: the ten highs first (ledger `docs/bug-hunt-2026-09-18/ledger/highs.md`,
`KNOWN_BUGS.md` CR-282), then four groups (`ledger/companion-core.md` CR-283,
`ledger/companion-media.md` CR-284, `ledger/dashboard.md` CR-285 in two waves,
`ledger/webapps-tools.md` CR-286). Every ledger section cites its finding
id, says what the fix is, names its regression test, and lists what it OWED
to another group; every code site cites the id in a comment, so
`grep -rn <finding-id>` finds the fix from either end. The 13-suite gate is
green on this tree. Fixes written that fast, by that many hands, have a
characteristic set of defects, and they are what this hunt is for:

- a fix that lands HALF of itself: the companion side without the dashboard
  side (or the reverse), a wire whose two ends two builders built to two
  slightly different contracts, or an OWED line that was routed and answered
  with something other than what was asked;
- a regression test that pins the NEW behaviour without proving the old bug
  is gone, that passes for a reason unrelated to the fix, that mocks away
  the thing that breaks, or that was rewritten to the new contract and
  thereby stopped guarding an older one;
- a fix that closes the reported scenario and opens its neighbour: a new
  early return that skips a cleanup, a new lock or generation token that a
  second path does not take, a new field an older build in the field does
  not send read as if it did, a new state word an older dashboard cannot
  parse (today's own lesson: `file_moves_applied` is not a tolerant
  section, an unknown `state` 422s the WHOLE report), a new column read
  where the row may be NULL for every machine on the day of the deploy;
- version skew the fix forgot: the field runs companion 0.9.74 against
  dashboard 0.7.49 everywhere TODAY, and after the deploy will run 0.9.74
  against 0.7.50 (dashboard first) for hours or days per machine, and
  customers elsewhere may run 0.9.65 / 0.7.34. Every new wire key must be
  optional on read and harmless when ignored, in BOTH directions;
- schema v54 (three tables/columns, ONE migration step, never run anywhere
  yet): can it run on a v47 database from the 0.7.34 build, on a v53 one,
  and twice; does every reader of a new column survive NULL;
- two OWNER DECISIONS of the day that are NOT findings: a computer with
  nothing ticked is fine and must never read as a fault anywhere (live-5
  fixed the tray; if you find another surface that still treats
  `no_selection` as a problem, THAT is a finding); and any editor's live
  companion may finish another editor's expired YouTube job (ytdl-web-6 was
  declined and reverted; do not re-report it).

So: `git diff -- <your files>` FIRST, read every hunk with care alongside the
ledger section that explains it, then the rest of your territory as before.

## Rules
1. READ-ONLY. Do NOT edit, create or delete any file inside the repo, with ONE
   exception: your own report file under `docs/bug-hunt-2026-09-18b/hunters/`.
   No `git` commands that change state (no stash/checkout/commit/reset/tag;
   `git diff` and `git show HEAD:<path>` are how you compare before and
   after). You may run the tests that exercise your files and ad-hoc python
   snippets that import the code, from the component's venv (CLAUDE.md
   "Running tests" has the interpreter per component; run pytest from the
   component directory; the `server/` suite from Git Bash). Write scratch
   scripts and scratch copies to your scratchpad directory, never into the
   repo. Do NOT run `tools\run_all_tests.ps1` or another territory's whole
   suite (owner rule: the full gate runs once, centrally). Do not touch
   `~/.ccsync`, `%LOCALAPPDATA%\ccsync`, the NAS, the dashboard, Resolve, or
   any live process; this machine is the studio's base rig and its companion
   is running.
2. Read `CLAUDE.md` at the repo root FIRST (every invariant it states is a
   bug if the code violates it), then the parts of `SPEC.md` your territory
   implements, then the docs it names. For proxy tiers:
   `docs/BROLL_PROXY_TIERS_PLAN.md` and `_AUDIT.md`; for the engine pool
   `docs/CARDS_TWO_PROJECTS.md`; for hand moves `docs/HAND_MOVES_ON_THE_SERVER.md`.
3. `KNOWN_BUGS.md` (grep with `-a`, it holds a stray binary byte) is the
   ledger through CR-286. Before reporting, `grep -an` it for the function,
   file or symptom; an OPEN entry is cited, not re-described; an entry that
   says FIXED for something you find is NOT fixed IS a finding ("regression
   of CR-nn" or "CR-28nX does not fix <id>"). The morning's raw reports and
   verdicts are your map of what each fix was FOR: read the finding, then
   the verifier's fix note, then the fix.
4. Hunt for REAL DEFECTS, not style: wrong logic, off-by-one, races,
   unhandled exceptions on realistic input, resource leaks, state that is not
   persisted when CLAUDE.md says it must be, security holes (auth bypass,
   path traversal, token leakage into logs/responses, missing fail-closed),
   cross-platform breakage (Windows/macOS/Linux, NFC/NFD, CRLF, drive
   letters, separators), version compares with two-digit minors (0.9.75 vs
   0.10.0), schema-migration hazards, API contract mismatches between
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
   or mocks away the exact thing that breaks, is a finding. Today's
   `test_bug_hunt_2026_09_18_*.py` files and every test file `git diff`
   shows as edited deserve particular suspicion: for each, ask whether it
   would fail on `git show HEAD:<source file>`.
8. Time-box: about 30-45 minutes of work. The diff over your files first,
   then the files CLAUDE.md talks about most, then the paths that touch
   data, the fleet, or an editor's Resolve.

## Output
Write your report to `docs/bug-hunt-2026-09-18b/hunters/<territory-id>.md`,
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
- Ledger: <"new" | "regression of CR-nn" | "CR-28nX does not fix <id>" | "related to CR-nn (open)">
- Suggested fix: <one or two sentences>

### <territory-id>-2 - ...

## Coverage note
<what you did NOT get to, and what the suite does not cover>

## OUT OF TERRITORY
- <path>: <one line>
```

Severity guide: high = data loss, sync of the wrong thing, security, a
fleet-wide outage, the dashboard or tray dying, an editor's Resolve project
damaged, a deploy that breaks the fleet in the documented order; medium = a
feature wrong for some real input or platform, a bad state the user cannot
clear, misleading UI that causes a wrong action, a failure nobody is told
about; low = edge case, cosmetic, hygiene with a real but small consequence.

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
- **regression**: for EACH section of the five ledgers
  (`docs/bug-hunt-2026-09-18/ledger/highs.md`, `companion-core.md`,
  `companion-media.md`, `dashboard.md`, `webapps-tools.md`: CR-282A..J,
  CR-283A..Y, CR-284A..AB, CR-285A..AX, CR-286A..AL, about 150 in all),
  find the fix (`grep -rn <finding-id>`), read the hunter's finding and
  the verifier's fix note it was built against, and judge whether the fix
  actually closes the hunter's failure scenario, the whole of it, on every
  platform the finding named, without opening a neighbour. Prioritise the
  ten highs and every medium; sample the lows. Then the twenty-one OWED
  hand-offs (each ledger's "OWED TO ANOTHER GROUP" section): was each one
  answered, by the group it named, with what was asked. A fix that does not
  fix, fixes a different case, was answered with something else, or
  reintroduces a ledgered bug is your finding, ledgered as "CR-28nX does not
  fix <hunter-id>".
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
