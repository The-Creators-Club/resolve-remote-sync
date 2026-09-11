# Bug hunt brief, eighth fleet hunt (2026-09-11, second of the day) - read fully before touching the code

Repo: E:\Projects\Editing\ccsync (git HEAD 18e69f3, tag v0.7.43: companion
0.9.71, dashboard 0.7.43 schema v52, installer 1.0.42). The repo moved here
from E:\Projects\resolve-remote-sync this morning; older docs and ledger
entries still say the old path, that is not a finding. You are ONE hunter in
a fleet of 23; seventeen own a disjoint TERRITORY of files, six own a LENS
that cuts across every territory. Hunt only inside yours; a defect you notice
outside it while following a call goes under "OUT OF TERRITORY" at the bottom
as one line. Do not chase it.

Why now. The seventh hunt (`docs/bug-hunt-2026-09-11.md`, this morning) found
131 defects at 40f931a and SIXTEEN builders fixed all of them in one afternoon,
in parallel, on disjoint file territories, with fourteen hand-offs where a
finding had two sides. That fix pass is commit 18e69f3: about 15,000 changed
lines across 185 files, ledgered as CR-233..CR-248 in `KNOWN_BUGS.md`, and it
is shipping to the fleet this evening. Fixes written that fast, by that many
hands, have a characteristic set of defects, and they are what this hunt is
for:

- a fix that lands HALF of itself (the companion side without the dashboard
  side, or the reverse), or that the two builders of one wire built to two
  slightly different contracts;
- a regression test that pins the NEW behaviour without proving the old bug
  is gone, or that passes for a reason unrelated to the fix;
- a fix that closes the reported scenario and opens its neighbour (a new
  early return that skips a cleanup; a new lock that a second path does not
  take; a new field that older builds in the field do not send, read as if
  they did);
- a `KNOWN_BUGS.md` entry that says FIXED for a finding the code does not
  actually address (compare the hunter's finding in
  `docs/bug-hunt-2026-09-11/hunters/<territory>.md` with the fix at the
  code site: every fix cites its finding id, so `grep -rn <id>` finds it);
- version skew the fix forgot: the field today runs companion 0.9.65..0.9.71
  and dashboards 0.7.34..0.7.43 in every combination, and a Mac on 0.9.70.

So: `git diff 40f931a..HEAD -- <your files>` FIRST, read every hunk with
care, then the rest of your territory as before.

## Rules
1. READ-ONLY. Do NOT edit, create or delete any file inside the repo, with ONE
   exception: your own report file under `docs/bug-hunt-2026-09-11b/hunters/`.
   No `git` commands that change state (no stash/checkout/commit/reset/tag).
   You may run the tests that exercise your files and ad-hoc python snippets
   that import the code, from the component's venv (CLAUDE.md "Running
   tests" has the interpreter per component; run pytest from the component
   directory). Write scratch scripts to your scratchpad directory, never into
   the repo. Do NOT run `tools\run_all_tests.ps1` or another territory's whole
   suite (owner rule: the full gate runs once, centrally). A ship is in
   progress from this machine while you hunt: do not touch `~/.ccsync`,
   `%LOCALAPPDATA%\ccsync`, the NAS, the dashboard, or any live process.
2. Read `CLAUDE.md` at the repo root FIRST (every invariant it states is a
   bug if the code violates it), then the parts of `SPEC.md` your territory
   implements, then the docs it names.
3. `KNOWN_BUGS.md` (grep with `-a`, it holds a stray binary byte) is the
   ledger through CR-248. Before reporting, `grep -an` it for the function,
   file or symptom; an OPEN entry is cited, not re-described; an entry that
   says FIXED for something you find is NOT fixed IS a finding ("regression
   of CR-nn" or "CR-nn does not fix <id>"). The prior hunt and its raw
   reports (`docs/bug-hunt-2026-09-11.md`, `docs/bug-hunt-2026-09-11/`) are
   your map of where the fresh code is.
4. Hunt for REAL DEFECTS, not style: wrong logic, off-by-one, races,
   unhandled exceptions on realistic input, resource leaks, state that is not
   persisted when CLAUDE.md says it must be, security holes (auth bypass,
   path traversal, token leakage into logs/responses, missing fail-closed),
   cross-platform breakage (Windows/macOS/Linux, NFC/NFD, CRLF, drive
   letters, separators), version compares with two-digit minors (0.9.71 vs
   0.10.0), schema-migration hazards (v52 now; a migration that cannot run
   twice, or on a v47 database from the 0.7.34 build in the field, is a
   finding), API contract mismatches between companion, dashboard and the
   web apps (compare BOTH sides of every wire you see), tests that assert
   the wrong thing or that a bug would not fail, CLAUDE.md invariants the
   code does not enforce, and user-visible copy with an em dash (owner rule)
   in tray/popup/template/SPA/HTTP-detail strings.
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
   `test_bug_hunt_2026_09_11_*.py` files are this afternoon's regression
   tests and deserve particular suspicion.
8. Time-box: about 30-45 minutes of work. The diff since 40f931a first, then
   the files CLAUDE.md talks about most, then the paths that touch data, the
   fleet, or an editor's Resolve.

## Output
Write your report to `docs/bug-hunt-2026-09-11b/hunters/<territory-id>.md`,
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
- Ledger: <"new" | "regression of CR-nn" | "CR-nn does not fix <hunter-id>" | "related to CR-nn (open)">
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
  repath, sequencer, shared_folders, syncthing_admin, syncthing_lane,
  syncthing_supervisor), `selection.py`, `file_moves.py`, `drive_reminder.py`,
  `drive_swap.py`, `manifest.py`, `root_guard.py`.
- **comp-app**: `app.py`, `__main__.py`, `config.py`, `site.py`, `identity.py`,
  `machine.py`, `paths.py`, `canon.py`, `secretfile.py`, `eula.py`,
  `capabilities.py`, `ui_state.py`, `ui_copy.py`, `reporter.py`, `idle.py`,
  `shutdown_guard.py`, `theme.py`.
- **comp-ui**: `tray.py`, `tray_native.py`, `popup.py`, `settings_window.py`,
  `ui_dispatch.py`, `crash_report.py`, `supervisor.py`, `stills.py`.
- **comp-resolve**: `resolve_bridge.py`, `resolve_journal.py`,
  `resolve_undo.py`, `resolve_prefs.py`, `script_server.py`, `fixer.py`,
  `library.py`, `proxy_gen.py`, `proxy_history.py`, `proxy_relink.py`,
  `proxy_scan.py`, `luts.py`, `bpg.py`, `consolidate.py`, `project_setup.py`,
  `watcher.py`, `timeline_cards_bridge.py`, `timeline_cards_role.py`.
- **comp-broll-music**: `broll_server.py`, `broll_fetch.py`, `broll_ingest.py`,
  `broll_ingest_media.py`, `broll_upload.py`, `broll_vlm_sidecar.py`,
  `loopback_guard.py`, `music_server.py`, `music_ingest.py`, `music_worker.py`,
  `music_clap_sidecar.py`, `ingest_kinds.py`, `ffmpeg_tools.py`.
- **comp-ytdl-jobs**: `youtube_import.py`, `ytdl_attestation.py`,
  `ytdl_browser_login.py`, `ytdl_common.py`, `ytdl_cookies.py`,
  `ytdl_executor.py`, `ytdl_server.py`, `ytdlp_manager.py`, `jobs_media.py`,
  `jobs_runner.py`, `job_paths.py`, `sidecar_tools.py`, `upgrade.py`,
  `release_pubkey.py`, `ed25519.py`.
- **dash-api**: `api.py`, `package_store.py`, `settings.py`, `local_users.py`,
  `provision.py`, `android.py`.
- **dash-collector-alerts**: `collector.py`, `alerts.py`, `notices.py`,
  `health.py`, `invariants.py`, `protection.py`, `recovery.py`,
  `crash_report.py`, `mount_status.py`, `syncthing_client.py`.
- **dash-core**: `app.py`, `auth.py`, `sessions.py`, `oidc.py`,
  `secrets_boot.py`, `setup_api.py`, `setup_engine.py`, `setup_routes.py`,
  `site_store.py`, `truenas_client.py`, `tailscale_local.py`,
  `internal_sftp.py`, `published_docs.py`, `help.py`.
- **dash-db**: `db.py`, `links.py`, `assignments.py`, `runtime_id.py`, and
  every migration step v40..v52 against a database shaped like the 0.7.34
  build's (v47) and the 0.7.29 build's.
- **dash-mounts-ui**: `ui.py`, `broll.py`, `music.py`, `ytdl.py`,
  `dashboard/templates/*`, `dashboard/static/*`, `dashboard/deploy/*`
  (Dockerfile, compose, run.sh, requirements.lock), `.github/workflows/*`.
- **dash-release-jobs**: `release_feed.py`, `release_trust.py`,
  `dashboard_update.py`, `jobs.py`, `ai_providers.py`, `cli_tools.py`,
  `cards.py`, `cards_ai.py`, `cards_exec.py`, `cards_tunnel.py`,
  `cards_wsgi.py`, `ed25519.py`.
- **broll**: `broll/web/app/*`, `broll/web/static/*`, `broll/indexer/*`.
- **music**: `music/web/musicweb/*`, `music/web/static/*`, `music/indexer/*`.
- **ytdl-web**: `ytdl/web/ytdlweb/*`, `ytdl/web/static/*`,
  `ytdl/web/migrations/*`.
- **server-tools**: `server/*.py`, `tools/*` (py, ps1, sh), `bench/`.
- **install-onboard**: `installer/*` (ps1, sh, and `installer/tests/*.ps1`),
  `onboarding/*`.

## Lenses (cross-cutting; read across every territory, own no file)

- **res-companion**: what an editor's MACHINE does when things go wrong.
  Trace whole failure paths end to end (a kill mid-write, a NAS that vanishes
  mid-lane, a Resolve that quits mid-relink, a drive pulled, a full disk, a
  clock jump, an upgrade mid-anything) through whichever files they cross.
  Report only what a territory hunter reading one file could not see.
- **res-fleet**: what the FLEET does when the server side goes wrong (the
  container restarting mid-report, a locked or corrupt DB, a migration that
  half-ran, an OTA update that half-applied, the Syncthing API down, alerts
  that cannot be delivered, a halt/rollback/push command that reaches a
  machine on an older build). Same rule: whole paths, across files.
- **wire**: every contract between two processes, both sides side by side:
  companion report/reply (`reporter.py`, `app.py` vs `api.py`), commands
  (`commands.*`), jobs offer/claim/cancel, file moves, upgrade offers and
  the signed record, the 8899 loopback vs the b-roll/music SPAs, the
  fleet routes of broll/music/ytdl vs their companion callers, the Cards
  tunnel vs `timeline_cards_role.py`, the vendor feed vs `release_feed.py`.
  A field one side sends and the other ignores, a status one side emits and
  the other cannot parse, a version gate that reads the wrong number, a
  fix this afternoon that changed one side only. State the older-build
  combinations that break (0.9.65/0.9.70 companions, 0.7.34 dashboards).
- **security**: auth and session gates, every fleet-credential binding
  (`cce1.` tokens must bind an identity: the CR-55 shape), path traversal
  on every route that takes a name or a path, token/secret/password leakage
  into logs, responses, notices, alert mails and `/api/v1/site`, fail-closed
  on every gate, the client-share prefix, the `/help` audience gate landed
  this afternoon (`published_docs.py`), redirect following, CORS on 8899.
- **tests**: test QUALITY across the whole tree. For each
  `test_bug_hunt_2026_09_11_*.py` file (and `Test-BinDirLeftovers.ps1`,
  `test_cards_snapshot.py`): does the test fail without the fix (revert the
  hunk in your head, or in a scratch copy OUTSIDE the repo), does it test the
  scenario the hunter described, does it mock away the thing that breaks?
  Then the older suites: fixtures that bypass a gate, asserts that cannot
  fail, platform assumptions that make the macOS runner red (the companion
  and onboarding suites run there too).
- **regression**: for EACH of the 131 findings in
  `docs/bug-hunt-2026-09-11.md` (ids in `docs/bug-hunt-2026-09-11/tally.txt`,
  verdicts in `verdicts.txt`, builder reports in
  `docs/bug-hunt-2026-09-11/ledger/`), find the fix (`grep -rn <id>`) and
  judge whether it actually closes the hunter's failure scenario, the whole
  of it, on every platform the finding named. Prioritise the 10 highs and
  the 41 verified mediums; sample the lows. A fix that does not fix, fixes
  a different case, or reintroduces a ledgered bug is your finding, ledgered
  as "CR-nn does not fix <hunter-id>".
