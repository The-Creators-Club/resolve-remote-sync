# sorter-node - footage-sorter outside the shipped package: server.js, lib/, ingest/tray/*.ps1, mover.ps1, cloud/ledger Worker, tools/, package.json

Files read (approximate coverage): HUNTER_BRIEF; ccsync docs/SORTER_DEPLOY.md, docs/FIELD_BACKUP.md (full); footage-sorter INGEST.md (full), README/SPEC (run instructions by grep), docs/LEDGER-BROWSER-DESIGN.md (start/deploy sections), docs/DASHBOARD-MODULE-PLAN.md (phase table by grep); lib/teracopy.js (full); ingest/tray/Common.ps1 and Config.psd1 (full); server.js resolveMoveTargets/sameFile (1380-1481) and timers/main guard; footage_sorter/moveplan.py same_file/resolve_move_targets; tests/py/js_driver*.js require lists; cloud/ledger/src/index.js routes and auth (grep), wrangler.toml; mover.ps1 move path (grep); AutoBackupTray.ps1 timers/spawns (grep); tools/purge-dupes.js header; companion teracopy.py / card_copy.py switch selection (grep); .gitignore and tracked data/.
Probes run: Startup folder and "Startup (retired)" .lnk targets (WScript.Shell, read-only); Get-ScheduledTask filtered for footage/sorter/ledger/backup; Win32_Process command lines for server.js / AutoBackupTray / mover; git ls-files + blob sizes of tracked data/; du of data/, cache/, node_modules/. No tests run, no node, no npm.

## 1. WHAT STILL RUNS (creator-1, 2026-11-11)

| Piece | Lines | Still used by what | Safe to retire to `legacy\` |
|---|---|---|---|
| `server.js` | 2,713 | Nothing starts it: no Startup entry (the "Auto Backup Utility" shortcut sits in `Startup (retired)`), no scheduled task, no running process. BUT `tests/py/js_driver.js` `require('../../server.js')._internals` (move-plan parity oracle), and README/SPEC/INGEST still say `npm start` | NO, not until the parity oracle is frozen (sorter-node-2) |
| `lib/` scan, suggest, catalog, infer, timefolder, clipkey, audio-match, google, cards, relocate, roster, routes/cards, routes/google | ~4,500 | Parity oracle only (`tests/py/js_driver.js`, `js_driver_modules.js`) | NO, same reason |
| `lib/teracopy.js`, `lib/thumbs.js`, `lib/ingest/*` (1,709), `lib/routes/ingest.js`, `routes/catalog.js` | ~2,980 | Only `server.js` and the Node `test/*.test.js`; no Python test loads them; superseded by companion `teracopy.py`/`card_copy.py`/`sorter_cards.py` and `footage_sorter/thumbs.py`, `ingest.py` | YES |
| `ingest/tray/AutoBackupTray.ps1`, `Start-Tray-Hidden.vbs`, `Install.ps1`, `Config.psd1` | 585+151 | Shortcut moved to `Startup (retired)` 2026-11-10; companion detects cards now. INGEST.md section 1 still tells a person to run `Install.ps1`, which re-creates the Startup shortcut | YES (and fix the doc, sorter-node-1). Other editor machines not checked (no SSH under the rules) |
| `ingest/tray/Backup-Card/Blackmagic/Audio/Drone/RecorderAudio.ps1`, `Common.ps1`, `TeraCopyStatus.py` | 1,022+806+459+388+156+386 | Only `AutoBackupTray.ps1`'s `LegacyWorkers` fallback, which needs the retired tray | YES |
| `mover.ps1` (+ `test/mover-test.ps1`) | 1,258 | Superseded by `footage_sorter/moves.py` (plan phase 4); README lines 641-643 still give the command; consumes `data/moveplan.json` that only the Node server exports | YES (doc fix) |
| `cloud/ledger/` (Worker + D1) | 636+32 | DEPLOYED at thecreatorsclub.co/backups/api, daily cron email; imported once into ledger.db 2026-11-10; plan says read-only for a month then delete; `ledger_import.py --from-worker` still reads it | NO for now (live service); see sorter-node-5 |
| `tools/gen-collation.js` | 103 | Generates `footage_sorter/_collation.py` (needs Node's ICU) | NO (dev tool, keep) |
| `tools/purge-dupes.js`, `rekey-assignments.js`, `plan-episodes.js`, `plan-interviewees.js`, `ui-shots.js` | 865 | Talk to the Node server on :8787 or its data/ files | YES |
| `tools/check-footage.js`, `tools/image-card.ps1` | 252 | INGEST.md 4a tells a person to run both; `image-card.ps1` is what the damaged-card banner tells you to run | NO (live operator tools) |
| `package.json` / `node_modules` (express 5 + 64 transitive, 3.3 MB) | - | express is imported only by `server.js`; nothing else needs a package | With server.js |
| `nas/cloud-backup.sh` | - | LIVE (TrueNAS cron job 4) | NO |

## Findings

### sorter-node-1 - The docs still install and start the retired tray and Node server beside the companion
- Category: deploy
- Severity: medium
- Confidence: CONFIRMED
- Where: footage-sorter INGEST.md:20-36 (Install.ps1, Start-Tray-Hidden.vbs, "starts node server.js"); README.md:16,25,33 (`npm start`), README.md:641-643 (`mover.ps1 -Execute`); SPEC.md:8-12,169
- What: SORTER_DEPLOY.md records that the tray was retired 2026-11-10 because the companion watches cards now, but the sorter's own user guide still says "Set-up (once): powershell -File ingest\tray\Install.ps1", which writes the "Auto Backup Utility" Startup shortcut back, and that tray starts `node server.js` and polls drives every 3 s (`Config.psd1` PollSeconds, a `Get-CimInstance Win32_LogicalDisk` per tick, AutoBackupTray.ps1:149,500).
- Cost / failure scenario: anyone setting up a second machine from INGEST.md gets two card watchers (the tray and the companion's sorter_cards) and two TeraCopy drivers on one card, plus a second writer of a Node `data/manifest.json` that no longer matches `/sorter`'s. `mover.ps1 -Execute` from README moves on W:/P: behind the NAS sorter's ledger and catalog (the move journal it writes is no longer reconciled by anything).
- Evidence: Startup / "Startup (retired)" .lnk targets; no matching scheduled task or process; INGEST.md and README text above; DASHBOARD-MODULE-PLAN.md phase 3 says the Node server "retires to legacy/", which has not happened.
- Ledger: new
- Suggested change: a banner at the top of README/INGEST/SPEC saying the Node server, tray and mover are retired, pointing to `/sorter` and FIELD_BACKUP.md; move the YES rows above to `legacy\` (plain move, a row in E:\Projects README "Where things went").
- Effort / risk: S effort; low risk.

### sorter-node-2 - lib/ and server.js cannot retire because they are the parity oracle, and that suite runs in no CI
- Category: streamline
- Severity: medium
- Confidence: CONFIRMED
- Where: footage-sorter tests/py/js_driver.js:14,115-129; tests/py/js_driver_modules.js:33; tests/py/jsbridge.py:18-23
- What: 13 `test_parity_*.py` files run the frozen JS (last change 2026-11-01, cdf3d64) in a Node child and compare with the Python. That keeps ~7,200 lines of JS, express and Node-on-PATH as a test dependency, and the oracle is only as good as the moment the JS froze. Neither the footage-sorter suite nor its parity tests run in ccsync CI (`ci.yml` covers only `test_sorter_deploy.py`; footage-sorter has no `.github`).
- Cost / failure scenario: every deliberate Python change since cut-over (e.g. sorter-node-3's full-byte compare) either breaks a parity test or the parity test does not cover it; nobody sees which, because the suite runs by hand only. Retiring the JS today would turn 13 test files into errors.
- Evidence: require lists above (scan, suggest, catalog, infer, timefolder, clipkey, audio-match, google, cards, relocate, roster, routes/cards, routes/google, server._internals); `git log` on lib/ server.js.
- Ledger: new
- Suggested change: record the oracle's answers once as JSON goldens under tests/py/golden/ (the driver already batches every call), point the parity tests at the goldens, then move server.js + lib/ + package.json to legacy\. Keep `tools/gen-collation.js`. Saves Node as a test dependency and ~7,200 lines in the live tree; add the sorter's tests/py to CI in the same step.
- Effort / risk: M effort; low risk.

### sorter-node-3 - Duplicate decision has drifted: Node calls any two equal-size files over 64 MiB identical, Python reads every byte
- Category: bug
- Severity: low
- Confidence: CONFIRMED
- Where: footage-sorter server.js:1392-1395 (`sameFile`: `if (size > SAME_FILE_HASH_MAX) return true`) vs footage_sorter/moveplan.py:315-339 (`same_file`, chunked full compare)
- What: in the move plan, a destination already holding a same-size file, or two sources aimed at one destination, is dropped as "alreadyThere"/"duplicates". Node decides that from size alone for anything over 64 MiB; Python compares full contents. Python is the correct one (its docstring says a sampled hash once called a damaged copy identical).
- Cost / failure scenario: only matters if the Node server is started again (sorter-node-1): two different 4 GB takes of exactly equal size (constant-bitrate cameras make this likelier than the comment assumes) - one is silently left out of the move and reported as redundant, and `tools/purge-dupes.js plan` builds its quarantine list from that export (its own verify cascade then refuses true mismatches, so no loss there).
- Evidence: the two functions quoted.
- Ledger: new
- Suggested change: none beyond retiring the Node path; note the drift in the parity goldens so they do not "fix" Python back.
- Effort / risk: S effort; low risk.

### sorter-node-4 - TeraCopy switch drift: Node and the PS1 workers copy new files with /OverwriteDiffSize; the companion uses /SkipAll
- Category: bug
- Severity: low
- Confidence: CONFIRMED
- Where: footage-sorter lib/teracopy.js:75, lib/ingest/plan.js:16,279, server.js:174, ingest/tray/Config.psd1:198 (TeraCopyConflictSwitch, used by every Backup-*.ps1 for "copy" groups) vs ccsync companion/src/ccsync_companion/teracopy.py:71-74 and card_copy.py:816-819
- What: in the Node and tray paths, a file planned as "copy" (destination absent at plan time) is handed to TeraCopy with /OverwriteDiffSize. If anything lands at that name between plan and run (the second card's C0001.MP4 into the same leaf, a re-run in another lane), the incoming file overwrites it whenever sizes differ. The companion port fixed this: /SkipAll for copies, /OverwriteDiffSize only for a same-clip resume, /RenameCopied for collisions. Also in the PS1 path only: `Invoke-TeraCopy` (Common.ps1:349-355) returns 0, success, on presence+size when the History DB cannot be read, where lib/teracopy.js returns 12 (unconfirmed); and `Get-TeraCopyStatus` matches a job by destination + time without its source list (Common.ps1:186), so two cards into one folder can read each other's record.
- Cost / failure scenario: dead today on creator-1; live again if anyone reinstalls the tray (sorter-node-1) with `LegacyWorkers = $true` (the shipped default) and the server unreachable.
- Evidence: the lines above.
- Ledger: new
- Suggested change: retire `ingest/tray` and `lib/ingest`/`lib/teracopy.js`; no fix needed in the companion, which is the correct twin.
- Effort / risk: S effort; low risk.

### sorter-node-5 - The October ledger Worker still takes writes after the cut-over to ledger.db
- Category: resilience
- Severity: low
- Confidence: PLAUSIBLE
- Where: footage-sorter cloud/ledger/src/index.js:567-625 (every write route still live behind the one bearer token); docs/LEDGER-BROWSER-DESIGN.md:390-392
- What: the plan says "retire ... the Worker's writers (razer tools). The Worker stays read-only for a month". Nothing in the Worker enforces read-only, and the razer field tools (branch `razer-field-mode`, `lib/ledger.js`, not in this checkout) were its writers. A copy recorded to D1 after 2026-11-10 never reaches `ledger.db` unless someone re-runs `ledger_import --from-worker` by hand.
- Cost / failure scenario: a field copy recorded only in D1 makes `/sorter`'s "not at home"/"safe to format" pessimistic for that card (not unsafe), and the daily cron email (`scheduled` -> `remind`) keeps reporting from D1, so two "not at home" lists disagree. D1 daily limits (100k writes / 5M reads, shared with /cards and /expenses, both exhausted once) remain at risk while razer still writes.
- Evidence: route table and auth (Bearer + constant-time compare, all routes but /health; no secrets in the repo, LEDGER_TOKEN is a Worker secret); could not check razer's scheduled tasks under the rules.
- Ledger: new
- Suggested change: deploy the Worker with an env flag `READ_ONLY=1` that 405s every POST/PUT and stop the cron email, or set a date and delete it; confirm on razer that nothing still points at /backups/api.
- Effort / risk: S effort; low risk.

### sorter-node-6 - 24 MB of machine state is tracked in git and pushed to GitHub; 636 MB of dead local state on creator-1
- Category: disk-growth
- Severity: low
- Confidence: CONFIRMED
- Where: footage-sorter data/manifest.backup-*.json (8 files, 1.7-2.7 MB each), data/moveplan.*.json (to 3.4 MB), data/dupes-20260819.json, data/server.out.log, data/settings.json; .gitignore
- What: hand-made backups of the Node manifest and executed move plans are committed (the .gitignore ignores `manifest.json` and `data/*.bak-*` but not `manifest.backup-*`); they carry every P:\ path, project and person folder names, and settings.json carries the owner's address and Google calendar ids. Origin is github.com/The-Creators-Club/footage-sorter. Locally, `data/` (176 MB) and `cache/` (460 MB, Node thumbnails) are dead after the 2026-11-09 migration (the new thumbnails are made on the NAS).
- Cost / failure scenario: every clone carries ~24 MB of history that is only useful on creator-1, and personal data leaves the studio with any share of the repo; 636 MB of stale state on creator-1.
- Evidence: `git ls-files -s data` blob sizes; `du`.
- Ledger: new
- Suggested change: `git rm --cached` the backups/logs/moveplans and add `data/manifest.backup-*`, `data/moveplan*`, `data/dupes-*`, `data/*.log` to .gitignore (history rewrite is the owner's call); archive `data/` and `cache/` with the Node server when it moves to legacy\.
- Effort / risk: S effort; low risk.

## What is already good
- The Worker's auth is right: bearer on every route except /health, constant-time compare, 503 when the token is unset, token not in the repo; `/changes` is paged (`MAX_ROWS`, `(seq,id)` cursor).
- `mover.ps1` is careful: no Remove-Item, no Copy-Item of footage, Move-Item without -Force plus a last-moment collision check, so it cannot overwrite or delete.
- `lib/teracopy.js` and the companion port share the hard-won History-DB rules (file creation time not TeraCopy's clocks, source-list match, locked != done); the companion is the stricter twin (sorter-node-4) and should stay the reference.
- express 5 is the only npm dependency; there is no unused package to drop short of retiring server.js itself.

## Coverage note
Not reached: the drift pairs scan/suggest/catalog/infer/timefolder/audio-match/google/cards beyond noting they are parity-tested (tests not run); lib/thumbs.js vs thumbs.py (no parity test - unguarded drift, but the JS is dead); Backup-Card.ps1 / Backup-Blackmagic.ps1 line by line (card pulled mid-copy, disk full, C0001 on two cards beyond the switch issue), AutoBackupTray handle/memory growth over weeks (moot while retired); mover.ps1 journal/verify; Worker input validation and per-request D1 cost; the other editor machines' Startup folders and razer's tools.

## OUT OF TERRITORY
- footage-sorter footage_sorter/moveplan.py:315-339: `same_file` reads both files end to end for every alreadyThere/duplicate candidate inside move-plan resolution (32 threads); on a 14 TB plan with many already-moved files that is TBs of NFS reads at plan time, where Node stopped at a size match. Worth a size+sampled-hash prefilter with a full compare only before an actual drop.
