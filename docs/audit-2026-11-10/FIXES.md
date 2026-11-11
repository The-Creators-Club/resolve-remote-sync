# Audit 2026-11-10 - fix ledger

What was changed for each finding in `FINDINGS.md`, written as the fixes were
made (2026-11-11, by the orchestrating session itself, no agents). One line of
status per finding id; the detail of what was wrong is in
`hunters/<hunter>.md`.

Status words: **FIXED** (code changed, test added or extended, the test file
run), **DECLINED** (the code is deliberate, or the change is not worth its
risk; the reason is given), **REFUTED** (the finding is wrong against the code
as it is now), **OPEN** (not done; why).

"Not proven" under a fix names what could not be run on this machine: live
Resolve, the NAS, a real card or reader, a Mac, a browser.

## Companion: field backup, card copy, ledger (comp-field, comp-ui-1/-2)

| id | status | what changed |
|---|---|---|
| comp-field-1 (high) | FIXED | `sorter_cards.list_card` returns `unreadable` (folders and entries that would not read) instead of skipping them at debug. `field_mode.card_verdict` takes it and answers `unsafe` with "Not safe to format: N folder(s) on this card could not be read (...)" before every other answer, the "nothing to back up" one included. `FieldService` carries the list on the card. The card report posted to the sorter gains the key only when the listing is partial, so the wire is unchanged for a card that read in full. Tests: `test_sorter_cards.py` (4), `test_field_mode.py` (2), `test_field_service.py` (1, end to end). Not proven: a real reader returning EIO. |
| comp-field-2 (high) | FIXED | `field_mode.is_judged(rel, size)` fails closed on the unknown: a file that is not a known original, not a known sidecar, and is 1 MiB or more is waited for. Known originals gained `.nev .ari .arx .cine .crw .erf .rwl .m2t .mod .vob .tod .crm .rdc .mlv .dv .bwf .caf .amr .w64 .rf64`; a `SIDECAR_EXTS` deny-list (`.xml .thm .lrv .lrf .srt .bin .dat ...`) keeps camera bookkeeping and low-res twins out whatever their size. The 1 MiB floor is a decision taken here (the audit text said "any unknown file"): cameras write small bookkeeping files under names nobody has listed, and those would hold every card ingested at home "unsafe" for ever, because the ledger never tracks them. Not changed: the ledger's own master list (`ledger_scan.MASTER_EXTS` and the sorter's `ledger_rules`), so an N-RAW clip is judged and counted from this machine's own copies, and is not yet a ledger row. |
| comp-field-3 (high) | FIXED | `LedgerView._raw` notes the copies the mirror now holds and `LedgerView.settle()` drops them in ONE rewrite at the end of a verdict (was one rewrite + fsync per file). `FieldService.card_verdict` is single-flight (polls that arrive during a verdict wait for it instead of starting their own). Test counts the rewrites: 300 lookups, 1 write. |
| comp-field-4, comp-ui-1, comp-ui-2 | FIXED | `LocalCopies` is held by (volume, path) and indexed by (name, size); `LedgerMirror.reading()` keeps one connection for a whole verdict and the schema runs once per process, not per lookup; `FieldStore` re-reads its file only when its size or time moved; a volume's kind is resolved once per verdict. Not done: the per-row `stat` of NAS copies when the pool is mounted stays (it is the "a copy counts only if it is still there" rule). |
| comp-field-5 | FIXED | A fixed volume with a camera's own layout is a card on the field page (`_cards_from`), is never offered as a destination, and can be copied: `card_copy._find_card` / `_card_gone` and `field_copy._card_present` look at "local" volumes, not removable ones only. The system disk is never a card. Test copies a CFexpress-style fixed card end to end. |
| comp-field-6 | FIXED | `ledger_outbox.flush` reads the file once per pass and rewrites it once per 20 delivered batches and at the end (was two parses and a full rewrite per batch); `pending()` parses only when the file changed. Delivery was already at-least-once; a batch accepted just before a crash may be re-sent and is answered as `duplicates`. |
| comp-field-7 | FIXED | The mirror pulls a REMEMBERED set (attached now + pulled before and seen within 60 days, at most 150), not "what is plugged in now": a drive in the bag keeps its rows and stays in the pull; a NEW volume is caught up on its own from the start and the one cursor carries on for the rest (no more re-pull of the NAS's whole ledger per card in or out). An away camera card is dropped (`keep=` from `FieldService.sync`). `FieldService._scan` rebuilds the mounted-root map each scan, so an away drive is no longer looked for at its old letter. Wire: unchanged (same route, same parameters). Not proven: against the live sorter. |
| comp-field-8 | FIXED | The disk-number cache lives one scan, not the life of the process, and `file_verdict` prefers what the machine says now over the disk a row was stamped with. |
| comp-field-9 | FIXED | A volume a field copy is writing to is registered (`sorter_cards.dest_busy`) and is not re-listed while it is written, by the sorter card loop or the field page. A fixed volume's free space is no longer part of its "changed" signature on the field page. |
| comp-field-10 | FIXED | `card_copy.verify_whole` reads the copy back past the file cache: `FILE_FLAG_NO_BUFFERING` on Windows (page-aligned buffer, whole-sector reads, never past the end), `F_NOCACHE` on macOS for both the write and the read-back, `posix_fadvise(DONTNEED)` elsewhere; any refusal falls back to the old buffered read. Tests cover lengths 0, 1, 4095, 4096, 4097 and multi-buffer, prove the Windows handle really is unbuffered, and the fallback. **Not proven: the macOS half (no Mac here), and a real USB bridge.** |
| comp-field-11 | OPEN until the shared process probe (lens-longrun-companion-1) | TeraCopy's `tasklist` every 5 s goes when that probe lands. |
| comp-field-12 | DECLINED | A fan-out copy (one read, N writers) is M effort and medium risk in the path that makes the safety copies; low severity. |
| comp-field-13 | DECLINED | The drifted proxy-name rule errs toward judging MORE files (safe direction). |
| (found while testing) | FIXED | `field_server._read_json` answered 413 with the body unread, which makes Windows reset the connection: the page saw a network error and `test_a_bad_or_oversized_body...` failed once in a few parallel runs. It now drains a modestly oversized body first. |

## Companion: sync lanes (comp-sync)

| id | status | what changed |
|---|---|---|
| comp-sync-1 (a) | FIXED | Lane B re-checks a subpath whose last pass completed and found nothing on the narrow pool (`RcloneTuning.for_verify`, lane A's knobs). Same `sync`, filter, `--max-delete`, `--min-age`, `--backup-dir`, breaker. A pass that moves anything, fails, stalls or trips puts the next one back at full width. |
| comp-sync-1 (b) | OPEN | Skipping lane B on an unchanged NAS-side signature needs the dashboard to ship a per-project signature on the selection reply (a wire change, dashboard first). |
| comp-sync-2 | FIXED | Any tick, untick or mode flip forgets every lane A clean check (`_update_known_selection`), and `_lane_a_changed_at` is pruned with the other per-slug state. |
| comp-sync-3 | FIXED | The size-mismatch ("skipped, exists") and orphan reports are kept per subpath and reported as a sum; one project's clean scan no longer wipes another's. `subpath` names the project when exactly one has mismatches, else null. The two tree-wide local scans on that cadence run once per scan pass (15 min floor), not once per project. An unticked project's entry is pruned with the future-dated one. |
| comp-sync-4 | DECLINED | The per-turn unpause is unconditional on purpose (the comment at the call says so: it is what releases a folder a crashed pass or a hand-pause left stuck). |
| comp-sync-5 | FIXED | The Syncthing lane's poll goes quiet after four idle sweeps: a ping and one `/rest/system/connections` per poll, the full per-folder sweep again when a device connects or drops, more than 64 KiB crosses the wire, or 120 s pass. The supervisor still hears within one poll that Syncthing is gone. Not proven: against a live Syncthing. |
| comp-sync-6 | OPEN (low) | |

## Companion: fleet jobs (comp-jobs)

| id | status | what changed |
|---|---|---|
| comp-jobs-1 | FIXED | `jobs_media.PeakBinner`: the peaks recipe bins the decode a block at a time instead of holding the whole PCM and five copies of it (288 MB per hour of audio). Output bytes are identical (tested at block sizes that split samples and bins, against the Timeline Cards reference arithmetic). The drain thread, its failure hand-back and the "read to the end" check are unchanged. |
| comp-jobs-2 | OPEN until the shared process probe | |
| comp-jobs-3 | FIXED | A claim that cannot reach the dashboard is "not now": one INFO line, the offer is dropped (the next report reply re-issues it), no traceback every 20 s. |
| comp-jobs-4, -5 | OPEN (low) | |

## Timeline Cards, the live page (tree `E:\Projects\Editing\Resolve\MulticamPipeline`)

| id | status | what changed |
|---|---|---|
| cards-library-1 (high) | FIXED | `library_engine._peaks_make` streams the decode through `_PeakStream` (about 1 MB held, was 307 MB for a 64-minute clip) via a new `_ff_stream` (stderr drained on its own thread, killed at the timeout, registered for a pinned job's cancel exactly as `_ff_run`). At most `PEAKS_PARALLEL` = 2 decodes at once (the rest wait, still reported as "making"). A failed decode is remembered against that version of the source for 10 minutes, so the page's retries do not start it again; the page stops asking on `failed` and waits 10 minutes instead of 2 for a queued one (`03-lane.js`). Same bytes as before: `tests/test_peaks_make.py` (new, registered in `run_all.py`) checks them against the old arithmetic and through real ffmpeg. |
| cards-page-b-1 (high) | FIXED | The app-only keep's switch is `oflKeepOn` (was a second `function oflAutoOn()` that lost to the later one by hoisting). `test_offline_page.js` now also fails if ANY function is declared twice anywhere in the page's scripts (1,382 scanned, none left). |
| cards-page-b-2 | FIXED | The video line of the automatic keep has the same `held()` test as peaks and audio. |
| cards-page-b-3 | FIXED | `sw.js` `activate` removes only its own scope's entries from older shell caches and deletes an old cache only when it is empty, so one episode's update no longer throws away every other episode's offline shell. Cache names are unchanged, so the dashboard's `savedEpisodes()` / `savedShells()` readers are untouched. |
| cards-page-b-5 | FIXED (told, not rolled back) | A failed IndexedDB save (a full device) is said once, in the page's error line: the edits are kept only while the page stays open. The edit is NOT taken back off the list: that needs a snapshot of the state before each local apply, which is a larger change. |
| cards-page-b-9 | FIXED | One `timeupdate` listener on the shared duck element; the previous one is removed before a new one is added. |
| cards-page-b-4, -6, -7, -8 | OPEN | Media eviction and the per-edit rewrite are M-sized. |
| cards-page-a-1..4 | DECLINED for now | The old page is to be replaced by the rebuilt editor; rewriting its row rendering is work on code with a retirement date. |

The golden page (`tests/golden/page.html`) was regenerated from `render_page()` for the page changes above, as `test_page_golden.py` asks.

## Dashboard: the Cards mounts (dash-mounts)

| id | status | what changed |
|---|---|---|
| dash-mounts-1 (high) | FIXED | `cards_wsgi.DisconnectAware` wraps the a2wsgi mount (`cards.py`): for GET and HEAD it watches `receive()` for `http.disconnect` and sets an event that rides a ContextVar into the WSGI thread, where `_Writer.write` raises `BrokenPipeError`, the error the Cards handler already expects from a closed socket. `cards_edit.Passthrough` races each chunk of a GET against the disconnect and closes the upstream at once (a long poll nobody is waiting for is let go too). POST and the other body-carrying methods are untouched, because the body gate's replayed `receive` belongs to them. Tests: a real uvicorn on a loopback port behind five BaseHTTPMiddleware layers; the client reads 256 KiB of a 200 MB answer and leaves, and the producer stops within a few buffers (it ran all 200 MB before). Not proven: against the live dashboard and a real browser's seek. |
| dash-mounts-2..6 | OPEN | |

## Footage Sorter (tree `E:\Projects\Editing\footage-sorter`)

| id | status | what changed |
|---|---|---|
| lens-sql-1 = sorter-py-1 (high) | FIXED | `Ledger._rd` records each reader with its thread and, when a new reader is opened, closes the readers of threads that have ended (under its own small lock, not the writer's). 40 short-lived threads now leave at most 3 connections open (was 40). A live thread's reader is never closed under it. `tests/py/test_ledger.py` (2 new). |

## Server scripts and deploy (deploy-nas)

| id | status | what changed |
|---|---|---|
| deploy-nas-1 (high) | FIXED in code, NOT RUN | `install_dashboard_app.py`: `--mode` implies `--recreate` only when the running container's image is not the image this run's mode would give it (`mode_flag_needs_recreate`, `apply_mode_flag`, new `backend().container_image()` = a read-only `docker inspect` on both backends). The same image means the same mode and the same image, so the run is the routine redeploy (restart). "Could not tell" (no container yet, a dry run, an SSH failure) re-creates as before. Decided after the pre-flight refusals and before the confirmation and the snapshot. `docs/CARDS_DEPLOY.md` says what changed, that a digest which is NOT the live one still re-creates with that image (the rollback trap is unchanged for a wrong digest), and that the first real run must be watched. **Not proven: nothing was run against the NAS. A dry run cannot show the new path (it connects to nothing).** `CLAUDE.md`'s recipe line is still valid and was not edited. |
| deploy-nas-2, -3, -5, -8, -10 and the lows | OPEN | The subcommands (`cards`, `sorter`, `restart`, `image --to`) are a design the owner should see first. |

## Web apps and indexers

| id | status | what changed |
|---|---|---|
| web-ytdl-1 (high) | FIXED | `vendor/downloader.py`: a `match_filter` refuses a stream that is live or has not started (an ended one is an ordinary video) and `download()` raises `ClipStopped` with the sentence, instead of yt-dlp silently skipping it; a 2-hour wall-clock ceiling per download (the companion's number) and a `should_stop` callable are checked from yt-dlp's progress hook, on the thread that owns the download. `worker.py`: [ CANCEL ] reaches a running download (the flag is re-read at most every 2 s) and the clip goes back to waiting; a stopped clip is one failed row, is not path evidence, and never feeds the identical-failure breaker. Not proven: against YouTube. |
| web-ytdl-2 | FIXED (timeouts) | The server's ffmpeg conversion has the companion's 3-hour ceiling and ffprobe its 120 s; a conversion that hits it removes its half-written output, puts the download back and fails the clip with a sentence. Not done: cancelling a conversion in progress, and a `-threads` cap. |
| web-ytdl-3..7 | OPEN | |
| idx-1 (high, plausible) | FIXED | Stills are cut at 960 px wide at most (`FRAME_SCALE`), never upscaled, in BOTH twins: `broll/indexer/broll_index/ffmpeg_tools.extract_frames` and the companion's `broll_ingest_media.extract_frame_cmd` (which cuts from the same 1080p proxy and is pinned equal to the indexer's argv by an existing test). A contact-sheet cell is 384 px wide whatever it is scaled from, so the API path is unaffected. Not proven: that an 8-frame window of 1080p stills really overflowed the local model (nobody has run it since the proxy change); the fix is right either way. |
| idx-2..10 | OPEN | |

## Release and tests

| id | status | what changed |
|---|---|---|
| deploy-release-2 = tests-ci-6 (high) | FIXED (the gate), the job itself is the owner's switch | `publish_latest.ci_jobs_not_run(sha, jobs)` reads the jobs of the green `ci.yml` run; `release_customers.py` refuses a customer dashboard release unless the `linux` job RAN to success on that commit (a skipped job leaves the run green), and refuses when the jobs cannot be read. `--allow-unrun-ci-jobs` is the named override and prints that no automated suite has run the dashboard. Companion and onboard publishing are unchanged. `ci.yml`'s `if: false` was NOT touched: turning the job back on is the owner's call (it was turned off on 2026-11-10 by the owner). `docs/CI.md` has the paragraph. **Effect today: a customer dashboard release is refused until the linux job is back on or the override is passed.** |
| tests-ci-7 | FIXED for the two files measured | Reproduced locally: three tests spent exactly 10.0 s in TEARDOWN. The cause is not a lifespan writer at boot but the reverse: the test's own second connection still holds an open write when the app shuts down, and the shutdown's write waits out the 10 s busy timeout. `test_presence.py` and `test_multi_machine.py` close that connection before the app exits (28 s to 9 s for the two files). 92 other fixtures have the same shape; the ones that actually stall will show in the central run's durations. Whether this was the source of the CI flake (test_smoke_boot, the socket relay, test_cli_tools) is not established. |
| tests-ci-1..5, -8..10, deploy-release-1, -3..10 | OPEN | |

## More fixes (second sitting, same day)

| id | status | what changed |
|---|---|---|
| cards-storydeck-1 (high) | PARTLY FIXED | `apps/windows/src/proxy.js` refuses an update whose `latest.json` entry carries no sha256 (it used to install it unchecked). **This is not the fix the finding asks for.** The checksum sits in the same file as the name, so whoever can write `<vault>/Apps/Timeline Cards/` can still write both. What is owed is a signature over each entry, made with a key that is not on the vault and checked against a public key baked into the app (the shape of CC Sync's signed upgrade channel). That needs three decisions that are the owner's: which key signs it (the CC Sync release key, or a new one), `apps/publish.ps1` asking for its passphrase, and a rebuilt and republished Windows app. Android relies on the APK's own signature and was not changed. Takes effect only when the Windows app is rebuilt. |
| cards-resolve-1 | FIXED | `LibraryReader._connect` sets `autocommit` (it only ever SELECTs), so the reader no longer sits "idle in transaction" on Resolve's live project library for the life of the process. `LibraryWriter`'s explicit transaction is a different connection and is untouched. |
| dash-collector-2 | FIXED | The checks panel calls a kind OK only on FRESH evidence: `db.notice_checks_fresh` treats a stamp older than 36 hours (the slowest honest writers are daily) as NOT CHECKED, with "last ran on" in its title; and a check that RAISES in `notices.run_checks` is now a notice of its own (`notice_check_failed`, subject = the check's name, closed by the same pass when the check next runs clean). Two older tests that stamped evidence with a fixed August date were updated to stamp "now". |
| lens-longrun-companion-1, comp-jobs-2, comp-media-1, comp-field-11, comp-resolve-7 (the spawn half) | FIXED | "Is Resolve running" is answered from one in-process Toolhelp snapshot (`resolve_prefs.windows_process_names`, the snapshot `script_server.py` already takes for CR-68) instead of spawning `tasklist`; the spawn stays as the fallback when the snapshot cannot be taken. Nothing is cached, so no caller can be handed a stale "not running". TeraCopy's wait loop uses the same snapshot. macOS is unchanged (`pgrep`). |
| comp-core-1 | FIXED | The manifest walk works out each folder's relative path once, as strings, instead of building a `pathlib.Path` and calling `relative_to` per video file. The strings reported are the ones pathlib produced (tested with an NFD name, a nested Proxy folder and a conflict file). The second `stat` per file stays (it is the `size_fn` test seam). |
| comp-core-3 | FIXED | The "unchanged section" stamp is the digest of the section as built, not as trimmed, so a manifest that had to be trimmed to fit is recognised as unchanged on the next report instead of being rebuilt, trimmed and re-sent every heavy tick. The forced resend every 10 minutes still goes. |
| comp-core-4 | FIXED | When the report is over its budget the per-file lists are dropped from the lowest-priority projects first and only as far as needed (was: from every project at once). The cache's own dicts are still never edited in place. |
| dash-api-1 (companion half) | FIXED | `selection._write_cache` ignores `generated_at` when deciding whether the plan changed, so `selection.json` is no longer rewritten on every 30 s fetch. The dashboard-side ETag is not done. |
| dash-api-2 | FIXED | The CR-379 rival walk is done BEFORE the report takes the write lock (`_prewarm_rival_walk`); the auto-map block then finds the 60 s cache warm. An unreadable tree is cached too, so it is asked once a minute, not once a report. Test proves the write lock is free during the walk. |
| lens-longrun-dashboard-1 | PARTLY FIXED | The lifespan stops the new editor's child FIRST, so its cut-list flush no longer sits behind twenty seconds of joins. Not done: `--timeout-graceful-shutdown` in `run.sh` and a `stop_grace_period` in the compose files (both are byte-for-byte-pinned deploy files). |
| sorter-py-2 | FIXED | A move run that raises ends as `failed` with the reason, and the reconcile, the tree refresh and the rescan always run. Nothing in that path moves, copies or deletes a file. |
| sorter-page-8 | FIXED (page strings) | 84 em dashes in the visible strings of `public/*.js` are hyphens; the two ingest refusals and the Google sign-in page read as two sentences or with a colon (in `footage_sorter/` and in the old `lib/routes/` twin, which the parity tests compare). Comment lines were left alone. Not changed: `audio_match.py`'s reason strings (a byte-for-byte port of the Node oracle) and `infer.py`'s regexes (they MATCH em dashes in folder names). The "Node-era instructions" half of the finding is not done. |
| tests-ci-2 | FIXED | `server/tests/conftest.py` refuses any connection that leaves the machine (an autouse fixture over `socket.create_connection`, `connect` and `connect_ex`), and `_real_run` stubs the TrueNAS version note that was making one. The server suite was only run after this was in. |
| (found while testing) | FIXED | `footage-sorter/tests/py/test_ingest.py::test_card_clips_are_never_opened_on_the_server` skips when `starlette` is missing; it only guarded `httpx`, and failed outright on this machine's system Python. |

## What was run

Once each, centrally, after the fixes above (2026-11-11):

| Suite | Result |
|---|---|
| companion (`-n auto`) | 9,150 passed, 24 skipped on the first run with 2 failures, both consequences of these changes and both fixed (a test that asserted the OLD mirror contract; the orphan report pruned by a missing local folder). The four files involved were re-run green. |
| dashboard (`-n auto --dist loadfile`) | 6,599 passed, 9 skipped |
| server (Git Bash) | passed (with the new no-network guard) |
| tools | 618 passed |
| ytdl/web | 1,125 passed |
| broll/web | 724 passed |
| music/web | 699 passed, 2 skipped |
| broll/indexer | 833 passed |
| music/indexer | 50 passed, 1 skipped |
| onboarding | 570 passed, 1 skipped |
| bench | 175 passed, 1 skipped |
| Footage Sorter `tests/py` | 647 passed, 9 skipped, 1 failed (the missing-`starlette` test above, since made to skip); the Node front-end tests `app`, `cards`, `ingest`, `ledger`, `design`, `google` pass |
| Timeline Cards | NOT the gate. `run_all.py --fast` includes `test_project_conform.py`, which writes to the NAS library, so the gate was not run from this session. Run individually and green: `test_peaks_make.py` (new), `test_offline_page.js`, `test_shorten_page.js`, `test_page_golden.py`, `test_fleet_jobs.py`, `test_fleet_execute.py`, `test_offline.py`; `node --check` on every changed script. **The owner should run `run_all.py --fast` before deploying Cards.** |
| installer (PowerShell) | not run: nothing under `installer/` was changed |

## Two slips, for the record

- `tests/test_library_reader.py` (Cards) was run once by this session. It reads the REAL Resolve project library on the NAS (192.168.0.102:5432). Every query in it is a SELECT and it stopped at its first data check (its reference timeline is gone, which is why the gate skips it), but it should not have been run at all.
- The first run of the Footage Sorter suite used the system Python, which is why one test failed on a missing package rather than on anything in the tree.

## Not done

Everything not listed above is still open: most mediums and all lows. The larger pieces, each of which is a design the owner should see before it is built:

- **Hash-and-skip on the report wire and the collector's writers** (theme 1: comp-core-2, dash-db-1, dash-collector-1/-3, dash-api-5). A wire change, dashboard first.
- **The deploy subcommands** (`cards`, `sorter`, `restart`, `image --to`) and the one-command release (deploy-nas-2..10, deploy-release-1, -3..-5).
- **Resolve load** (comp-resolve-1..5, cards-resolve-2/-3): fewer round trips into Resolve.
- **The dashboard's event loop** (dash-web-1: about 45 `async def` routes that write on the loop; dash-web-4/-5).
- **Signing the Cards app update** (the rest of cards-storydeck-1).
- **The rebuilt editor** (editor-*, including two highs): another session's live worktree, not touched.
- **Repository hygiene** (sorter-node-6 = lens-dup-2: 24 MB of machine state tracked in the footage-sorter repo and pushed to GitHub). Untracking is one commit; removing it from history is a rewrite, which is the owner's call.

Versions were NOT bumped and nothing was committed, published or deployed. The companion changes need a new companion version before a ship (`config.py` and `pyproject.toml`), the dashboard changes a new dashboard version; nothing here changes a wire or a schema, so there is no deploy order to respect.

## Third sitting (same day)

| id | status | what changed |
|---|---|---|
| dash-collector-3 | FIXED | `db.replace_missing_files` compares the stored list first and does not delete and re-insert one that has not changed; the only write for an unchanged list is a bump of `refreshed_at` once the stored stamp is 10 minutes old (the page's "refreshed N ago" and the age prune both read it). Not done: skipping the Syncthing FETCH for a pair whose need count has not moved. |
| comp-media-3 = web-music-1 | FIXED | `music_server.call` answers without starting a worker child when the kernel's TCP table says Resolve's script server is absent or still starting (the two states in which the child could not have connected either; "cannot tell" starts the child as before). The sentence returned is the worker's own. The `/music` page asks only while its tab is visible, and at once on coming back to it. Not done: answering from the watcher's in-process state when Resolve IS up, and a onedir build. |
| comp-app-1 | FIXED | `ingest_staging_report()` is memoised for 30 s and cleared by the button that prunes staging; the tray's 2 s tick no longer walks every staging batch on the sync drive. The space refusal still does its own exact walk. |
| (reported by the owner, 2026-11-11) | FIXED | **A card closed in the Source panel on `/sorter` could not be brought back.** Closing sets the session to `dismissed`, and it stayed that way for as long as the card sat in its reader, with nothing listing it: the only ways back were to pull the card and put it in again, or to restart the dashboard. Now: the sessions answer carries a `closed` list, the Source panel shows closed cards under their computer's Cards (greyed, with a `closed` pill and a "Show again" button, and the Cards row says "N + M closed"), and `POST api/ingest/restore` puts the card back in the state it was closed in. Its clips come back unassigned (closing a card drops its assignments, and that is not undone). Tests: `tests/py/test_ingest.py` (2), and end to end through the dashboard mount in `dashboard/tests/test_sorter_mount.py`. Not proven: in a browser against the live page. |

### What was run after the third sitting

| Suite | Result |
|---|---|
| companion (`-n auto`) | 9,156 passed, 24 skipped |
| dashboard (`-n auto --dist loadfile`) | four full runs: 6,599 passed; then 2 failures; then 1 failure; then 6,601 passed. The three failures were three different tests (`test_smoke_boot::test_every_mount_is_mounted...`, one not captured, `test_sorter_mount::test_two_editors_with_one_machine_name...`), each of which passes alone and in repeated runs of its own file. This is the intermittent parallel-run failure the linux CI job was switched off for on 2026-11-10; nothing here fixes it, and nothing here was shown to cause it. |
| music/web | 699 passed, 2 skipped |
| Footage Sorter `tests/py/test_ingest.py`, Node `ingest`, `app`, `cards` | pass |

### Asked for by the owner during the pass (not audit findings)

| what | status | what changed |
|---|---|---|
| "in timeline cards you should be able to change the colour of an entire transcript not just individual clips" (2026-11-11) | BUILT on the live page, not deployed | The clip-colour picker (`page/03-lane.js`), opened on cuts that all come from one clip, now has a first row: `whole transcript: <name> · N cuts`. Pressing it re-opens the picker on every cut of that clip in the cut list; a swatch then colours them all, and "default" puts them all back to the interviewee's colour. It is the ordinary colour edit with every uid in it (one `api/color`: one undo entry in immediate mode, one staged op in queue mode), so nothing new is stored and no server code changed. **What it is not:** it does not change the interviewee's own base colour (the map in `Script Docs` that canvases and new cuts start from), and it colours the cuts in the cut list that is open, not that person's cuts in other cut lists. If the base colour is what was meant, that is a separate, larger change (it rewrites the map and recolours every timeline that uses it). New test `tests/test_color_transcript.js` (no browser, registered in `run_all.py`); the golden page was regenerated. Not proven: in a browser, and against Resolve. The rebuilt editor (`/cards/edit`) is another session's worktree and does not have this. |
| "with the controller it should be double y to open that clip in its transcript, not single y select like it is now" (2026-11-11) | BUILT on the live page, not deployed | `page/19-pad.js`: one Y on the lane does what it did (select the cut under the head and centre its card, at once); a second Y on the SAME cut within 450 ms opens that cut in its transcript (`padOpenCut`, what View from the lane already calls). It mirrors the mouse: click selects, double-click opens. LT + Y (the run select) is unchanged and never counts as either half. The pad's help text says so. New test `tests/test_pad_double_y.js` (no browser, registered). Not proven: on a real controller. **If single Y was meant to stop selecting altogether, that is a one-line change; say so.** |
| "improve switching between panels and selecting find, inserting clips etc with the controller ... everything else should be controller manageable" (2026-11-11) | NOT STARTED | Asked as the five-hour usage window passed the 80% pause point. It is a design pass over `19-pad.js` (the lane, transcript and results ports, the find box, insert) against `docs/LANE-GAMEPAD-PLAN.md` and `docs/TRANSCRIPT-GAMEPAD-PLAN.md`, and needs the layout agreed before it is built. |

### Paused here

The five-hour usage window reached 82% at 01:19 UTC on 2026-11-11 (it resets at 05:00 UTC), which is past the 80% pause point set for this work. Nothing is half-edited: every change above has its test file passing.

## Later on 2026-11-11: the controller, one colour, and the Cards deploy

This replaces three rows above: the whole-transcript colour and the double Y are no longer "not deployed", and the controller pass is no longer "not started".

| what | status | what changed |
|---|---|---|
| "improve switching between panels and selecting find, inserting clips etc with the controller ... the only touch I want to make to the keyboard is typing" | BUILT and LIVE | `page/19-pad.js`. Three places where the pad needed the mouse: (1) **a find match could be heard but not taken**: Y in the find box now selects the sentence the match is in and puts the pad on the transcript, X inserts it at the playhead and stays in the box (LT + X places it on top), and Y on the transcript right after a match is cued selects it too; (2) **the other search box**: up / down in a box swap this transcript's find and the search over every transcript, carrying the text into an empty box, and View leaves a box (it did nothing there); (3) **the transcript list has a cursor**: View with nothing to open lands on the list, up / down walk it (LT: five at a time), A opens, B goes back, and LT + R3 reaches it from an open transcript. Cut lists and canvases at the top of that list are deliberately not on the cursor (A on one would switch the project). Tests: `tests/test_pad_hands.js` (40, no browser) and new checks in `tests/test_pad.js` (184 in headless Chrome against the fixture). **Not done:** the cards list on the pad, the staged / shortening / sequences tabs, the claude sheet's and semantic list's boxes from the swap, and inserting a results hit without opening it. Not proven: on a real controller. |
| "update yang zi ting in super age to a different unique colour, right now it's the same as gao shi nan" | DONE in the vault | 楊子霆 was `#c8a9fe`, which Resolve can only show as Purple, the same swatch as 高誓男. Now `#e8792b` / Orange, which nobody else in the episode uses. Changed in `Script Docs/interviewee_colors.json`, in seven planning canvases (424 cards) and on his 136 cut lines in the three cut lists. The sync-conflict copy of one canvas was left alone. Originals are kept in the session scratchpad (`yang-colour-backup-2026-11-11`). **Not changed: Resolve itself.** The multicam clip in the media pool and any timeline already conformed are still Purple until `pipeline.py interviewee-colors "<episode>" --apply --timeline` is run with the project open, or the next conform. |
| "interviewee's base colour everywhere" (the answer to what the colour feature should be) | NOT BUILT | Today's picker row colours the cuts in the open cut list. Changing a person's base colour from the page (the map, every cut list, the canvases, Resolve) is what was done by hand for 楊子霆 above and is still to build. |
| Cards deploy | LIVE 2026-11-11 09:43 local | Commit `d9188d7` on a new branch `cards-pad-2026-11-11`. **The live `/cards` was not `main`:** it was `3dcf3b6` on `standalone-editor` (another session's branch, 154 commits ahead of `main`, with the pinyin find and the preview video), so a deploy from `main` would have rolled those back. The new branch is that live commit plus only this pass's Cards changes. `main`'s working tree still holds the same changes uncommitted, and `standalone-editor` does not have them: **the next deploy from `standalone-editor` will take these changes off the page unless `cards-pad-2026-11-11` is merged into it first.** Gate before the deploy: `run_all.py --fast -k .js`, 36 suites, 0 red (the Python suites were not run; one of them writes to the NAS library). |
| deploy-nas-1, proven | FIXED and RUN | This deploy was the first real run of the 2026-11-11 change: with the live digest named, the script printed `NOT re-creating the app`, swapped the Cards code, restarted the container, and the dashboard answered v0.7.79 healthy after two probes. A ZFS snapshot was taken first. |
| the closed-card fix on `/sorter` | NOT DEPLOYED | It is uncommitted in the Footage Sorter repo (branch `sorter-dashboard-module`); the deploy ships `master`, which is the commit already live. |

## 2026-11-11, afternoon: the new editor is the one

The owner works in the NEW Timeline Cards editor (`/cards/edit`), and said so after the morning's controller work had been built and deployed on the old page: "merge the standalone editor branch and get rid of the old, it's superseded now". What followed, in order.

| what | status | what changed |
|---|---|---|
| Merge | DONE | `standalone-editor` and the morning's deploy branch merged into `main` of the Editing repo (`728a155`), no conflicts. `main` had been 155 commits behind what `/cards` runs. Its own 2026-11-10 checkpoint (the old reader takes a gap's note so a conform can build it as a title) came in with it; two of the editor's tests pinned the old reader passing over those notes and were brought in line. The other session's checkout of `standalone-editor` was not touched; it holds uncommitted work of its own. |
| "this english is wrong" (a screenshot: a 32 s cut across three paragraphs showing the middle one's English alone) | FIXED | The editor's lookup put the transcript's own paragraphs first on 2026-11-08; the page's instant answer (`features/translate/local.ts` -> `align/shared.ts englishOfSpan`) never got the rule. The clip's stored alignments held an earlier cut of the same words with the wrong English; it won as the longest run from the cut's first letter, the rest read as untranscribed speech, and the wrong English was then stored for the longer cut too. `englishOfSpan` now asks the transcript's paragraphs first. Reproduced on the real sidecar of that clip before and after: the cut now reads all three paragraphs' English, trimmed to the cut. |
| The controller, in the editor the owner uses | BUILT | `editor/client/input/pad.ts`, `surface.ts`, `types.ts`, the transcript panel and the search sheet. Y twice on a lane cut opens it in its transcript. In the find box: Y selects the sentence the match is in and goes to the transcript, X inserts it at the head and stays in the box, up / down go to the other box (this transcript's find, the search over every transcript) carrying the word, View leaves the box. Y on the transcript right after a match is cued selects its sentence. The list of transcripts is a port of its own: up / down walk it (LT: five), A opens, B goes back; LT + R3 reaches it from a transcript. Tests: 19 new unit tests of the map, 3 new real-browser tests of the panel's handle. Not proven: on a real controller. |
| A person's colour, not one cut at a time | BUILT | The editor's clip-colour picker has a row "Every cut of <name> (N cuts)" under the swatches; it widens the picker to every cut of that person in the cut list and on the shelf, and the swatch is then one edit and one undo. In this editor a cut with no colour of its own takes the colour most of its person's cuts carry, so this IS the person's colour in that cut list from then on. **Not built:** the same change carried to the episode's other cut lists, the pipeline's colour map, the canvases and Resolve (done by hand for 楊子霆 this morning). |
| Retiring the old page | PLANNED, nothing switched | [`../CARDS_OLD_PAGE_RETIREMENT.md`](../CARDS_OLD_PAGE_RETIREMENT.md): what "the old" is (the page) and what stays (the Python engine, which the new editor runs), seven things that still lean on the old page, the steps, and what needs the owner. The flip needs a dashboard release: the editor's mount path is a constant in `cards_edit.py` today. |
| Cards deploy | LIVE 2026-11-11 13:32 local | Commit `3f2344a` on `main` (the merge, the English fix, the controller, the colour row), on the image that was already running; dashboard v0.7.79 healthy after one probe. The deploy command read the live image and the live Cards commit off the NAS first and would have refused on either being unexpected. |
| The deploy died twice before it changed anything | FIXED | Step 1 (`chown -R` over the app's `data/` and `venv/`, about 23,000 entries) ran under `run_ssh`'s default two minutes. With the NAS busy (load 6 to 8) `venv/` alone took 68 s to walk; the step timed out in a paramiko traceback, twice, each attempt leaving its pass running on the NAS behind it. Nothing live was touched either time (the step is before the upload and the swap). `install_dashboard_app.py` now gives that step `HOST_DIRS_TIMEOUT_S` (900 s). Not done: a clean message instead of a traceback when an SSH step does time out, and skipping the walk of `venv/` in image mode, where the host venv is not used. |

### What was run this afternoon

| Suite | Result |
|---|---|
| editor, vitest | 2,041 passed, 1 skipped; one timing test in `features/align/test/server.test.ts` failed once in the full run and passes alone |
| editor, `tsc --noEmit` | clean |
| editor, real browser (input, transcripts, search, translate, align, shelf colour) | 57 passed |
| Cards, on the merged tree | `test_page_golden`, `test_cutlist`, `test_gap_notes`, `test_text_index`, `test_peaks_make`, `test_offline_page`, `test_pad_hands`, `test_pad_double_y`, `test_color_transcript` pass |
| ccsync `server/` (Git Bash) | passes |

Not run: the Cards gate's Python suites (one writes to the NAS library), and the companion and dashboard suites (nothing of theirs changed this afternoon).

### Still open from this day

- The owner's yes or no on retiring the old page, and the checks listed in the plan.
- The closed-card fix for `/sorter`: uncommitted in the Footage Sorter repo, so not deployed (the deploy says so itself: 13 modified files there are not in the snapshot).
- A person's colour carried beyond one cut list (other cut lists, the colour map, canvases, Resolve).
- Everything in the ccsync repo from the audit fix pass is still uncommitted, with no version bump.
- The remaining audit mediums and lows.

## 2026-11-11, later: three more audit findings, and a plan for the sorter

| id | status | what changed |
|---|---|---|
| comp-media-2 (a) | FIXED | `broll_ingest._save` writes the checkpoint compact instead of `indent=2` (about twelve saves per clip, the whole batch each time; the indented encoder is pure Python, measured 6.2 to 6.8 times slower and 31% larger). Part (b), coalescing the saves, is not done. |
| ops-server-2 | FIXED | `server/check_health.py`: every check runs through `run_check`, so one that raises (the NAS unreachable) is one FAILED line and the checks after it still run; the exit code is again the number of failed checks. `EnvError` and `NotImplementedError` still go to `cli()`. Not done: the same guard in `setup_tree.py` and `write_marker.py`. |
| deploy-nas-3 | FIXED | In image mode the after-restart gate expects the version that was serving BEFORE the restart (`version_serving_now`, `expected_after_restart`), not the repo's, which that mode never ships. Not run against the NAS yet: today's deploys had the two versions equal. `docs/CARDS_DEPLOY.md` says so. |
| Footage Sorter: the false "No clips match", the first load, and clips without a full rescan | PLANNED, read-only | [`SORTER_LOAD_AND_LIVE_SCAN_PLAN.md`](SORTER_LOAD_AND_LIVE_SCAN_PLAN.md). Another session was working in that repo, so nothing there was touched. The wrong message has one cause (a `ResizeObserver` in `grid.js` un-hides the empty text 60 ms after the page starts, before any data); the first load after a restart waits on answers the server could have built ahead (0.84 s measured on the workstation); and a walk of folder times every 20 s would have shown the copied clips with no button. |

Run after these: `server/` 953 passed, 1 skipped (Git Bash); `companion/tests/test_broll_ingest.py` 100 passed.

## 2026-11-11, evening: the sorter plan, parts A and B built (not deployed, by the owner's word)

The owner read the plan and said to go ahead; then, while it was being built, "when this is done do not deploy". The other session had committed its downloads feature (`2af2fe1`), so the repo was free. All of this is uncommitted in the Footage Sorter repo, beside the audit pass's earlier changes there.

| plan | status | what changed |
|---|---|---|
| A1, A2, A3, A4, A5, A7 | BUILT | The centre starts as "Loading your clips" in `index.html` itself; `grid.js` no longer un-hides "No clips match the current filters" before the state has arrived (the `ResizeObserver`'s first callback, 60 ms into the page); `renderCenter()` has `boot`, `failed` (with "Try again", `App.retryLoad`) and `drive` ("Listing the clips on <drive>", `Ledger.wherePending`); a failed load no longer ends in "No clips scanned yet - press Rescan". |
| A6 (a card still being read) | DROPPED | The server never reports a card as `scanning`: a card appears once it has been read, with its clips. Nothing to wait on. |
| B1 | BUILT | `SorterEngine.prewarm()`: the lean meta, the source clips, the destination summary, the destination's clips and its detail are built 3 s after start and after every scan, in place of `/api/state` (which no page asks for). |
| B2 | BUILT | `_json` gzips a body of 8 KB or more for a browser that takes it; a POST's answer is built and compressed off the event loop. |
| B3 | BUILT | `index()` stamps every script and stylesheet with `?v=<version>` (the deployed commit, else a digest of the files); a stamped request is answered `immutable` and gzipped, a bare one is revalidated as before; `dev-mock.js` is fetched only with `?mock=1`. |
| B4 | BUILT | `api/ingest/sessions` and `api/ledger/volumes` start with the other early requests; `ingest.js` and `ledger.js` take those answers (`earlyOr`). |
| B5 (the second redraw after an edit) | NOT DONE | |
| Part C (new clips without a full rescan) | NOT STARTED | Stopped at the usage pause point before it. The design and the measured cost (2,048 folders, 0.22 s a look on the NAS once warm, 2.7 s cold) are in the plan. |

Run: the sorter's Python suite 751 passed, 5 skipped (dashboard venv); Node `app` 341, `design` 167, `prefix` 31, `ledger` 184, `ingest` 296, `download` 21, `server` 187, all passing. New tests: thirteen assertions in `test/app.test.js`, three tests in `tests/py/test_perf_server.py`.

`dashboard/tests/test_sorter_mount.py` (the sorter mounted in the dashboard) passes with these changes: 27 passed.

Not proven: in a browser against the live page.

### The folder watch (part C), built the same evening after the owner said "continue"

| plan | status | what changed |
|---|---|---|
| C1 | BUILT | `scan.py`: the body of `_Scan.root()`'s loop is `_Scan.directory()`; `scan_dirs()` rescans named folders with the same code; `unit_dir()` says which folder made a clip. The scanner's parity tests still pass. |
| C2, C3 | BUILT, differently | No separate walk and no new module: a full scan records every folder it walks with its modified time and the folder that owns its files (`scan(dirs=...)`), kept in `data/watch.json`. A look is then one `stat` per known folder; a NEW folder is found through its parent, whose time moved when it was made. |
| C4, C5 | BUILT | `SorterEngine.watch_tick()` every 20 s (`watchSeconds`): rescans the folders whose time moved, replaces only their clips (every other clip object is left as it was), then the same follow-ups a full scan runs. A file counts once it has been seen the same at two looks running; a changed folder is looked at again for three looks after it last changed. A root that is not there concludes nothing. Skipped while a full scan runs. |
| C6 | BUILT | `flush_clips()`: `clips.json` is written at most once a minute behind the watch, and on the way out. |
| C8 | BUILT, server only | `POST /api/scan {"paths": [...]}` (`rescan_folders`). No menu item on the page yet. |
| C9 | BUILT, the simple way | The page's 15 s poll also asks for the rows again (conditional: two 304s unless something arrived) and says "N new clips arrived". The single `/api/changes` answer, and dropping the full destination-tree download from that poll, are not done. |
| C10 | BUILT | A full scan once a night (`nightlyScanAt`, 03:30). |
| C7 (the ledger told about the changed folders) | NOT DONE | The ledger's own nightly pool walk still records them. |
| with no `watch.json` (the first start after this ships) | by design | The first look starts one full scan, which makes the map. |

Tests: `tests/py/test_watch.py`, 14 (a copied file appears after it has stood still and nothing else is touched; a growing file is held back; a removed file and a removed folder go; a new folder is found and scanned whole; a proxy joins its clip; an absent root drops nothing; a restart sees what changed while it was down; one folder scanned alone equals what the full scan makes of it). The sorter's Python suite: 769 passed, 5 skipped. Node page tests and the dashboard's sorter-mount tests pass.

Not proven: on the NAS (the look was timed there, the watch itself has not run there), and with a real copy over the network, where the test of "has stood still" meets a real copier for the first time.
