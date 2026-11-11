# comp-core - companion core: the report wire, local manifest, config, upgrade/verify, supervisor, crash files, capabilities, idle probe
Files read (approximate coverage): reporter.py (all of the payload, suppression, fitting, post and loop paths, ~85%), manifest.py (100%), upgrade.py (offer acceptance, floor, download/verify, hand-off, ~40%), ed25519.py / release_pubkey.py (verify path), capabilities.py (~80%), idle.py (~70%), machine_settings.py (report section, ~45%), config.py (set_value, load/backup, validate DNS path, ~15%), site.py (cached_site / feature_enabled), transport.py (DNS cache), secretfile.py, supervisor.py (wait/import shape), crash_report.py (retention), selection.py (fetch/TTL); dashboard side: api.py report route media writes (11355-11430), db.replace_editor_media / replace_media_tree, MEDIA_REPORT_MAX_AGE_DAYS prune. Not read in depth: shutdown_guard.py, eula.py, state_acl.py, win_trust.py, canon.py, paths.py, machine.py, identity.py beyond the 2026-10-07 diff.
Probes run (all under scratchpad\comp-core\, companion / dashboard venvs):
- `probe_manifest.py`: synthetic tree, 10 marker projects, 50,171 files (38,280 video). `scan_local_manifest` best of 3 = 3.58 s rollup-only, 3.70 s all selected; cProfile; payload size, encode and digest timings for 10 and 64 projects.
- `probe_fastscan.py`: an `os.scandir` + string-prefix walk producing identical rollups: 0.47 s on the same tree.
- `probe_server_write.py`: real schema (`db.migrate`) in a temp DB; one forced resend of 10 unchanged projects x 4,000 rows through `db.replace_editor_media`.
- `probe_suppress.py`: a real `DashboardReporter` with a stub `http_post`, three heavy `post_once` calls with an unchanged manifest at 10 / 25 / 30 / 64 ticked projects of 2 x 2,000 files.
- Inline timings: `ed25519.verify` 2.9 ms; sha256 of 100 MB in 256 KiB chunks 27 ms; spawn of `ffmpeg -version` 26 ms, `ffprobe -version` 24 ms, `nvidia-smi` query 47 ms; `import ccsync_companion.supervisor` 36 ms.

## Findings

### comp-core-1 - The manifest walk spends ~85% of its CPU building pathlib objects, on every machine, every 300 s
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/manifest.py:186-226 (`Path(file_path).relative_to(project_dir)` and `rel.parts` per video file, `size_fn=os.path.getsize`), :369-373 (300 s loop)
- What: For every video file the walk builds a `Path`, calls `relative_to` (which itself builds and compares several `Path`s), then `rel.parts` and `rel.as_posix()`, and stats the file a second time with `os.path.getsize`. The pathlib work, not the disk, is the cost. It runs whether or not a project is selected (rollup-only projects pay it too), on the manifest thread, holding the GIL against the tray, the reporter and the lanes.
- Cost / failure scenario: 50k files: 3.6 s of pure-Python CPU every 300 s on a local NVMe tree (1.2% of a core, all day, beside Resolve). At commercial scale (64 projects, 500k files on a base or wired rig) about 36 s per pass, 12% of a core, before any SMB latency. The second stat per file is a network round trip on an SMB `local_root`.
- Evidence: cProfile of one scan: 9.4 s profiled total, of which `pathlib.relative_to` 5.8 s cumulative (38,293 calls, 783k `PurePath.__getitem__`, 898k `Path.__init__`), `os.stat` via getsize 1.8 s. A rewrite with `os.scandir` recursion, a carried `"prefix/"` string, a carried in-Proxy flag and `DirEntry.stat()` (free on Windows) produced identical rollups for all 10 projects in 0.47 s best of 3 against 3.58 s (7.6x).
- Ledger: related to PL-RES-107 / prac-perf-3 (open: base rig walks the NAS, extra getsize). New here: the dominant cost is pathlib and it hits every machine, so the recorded fix (scandir + `entry.stat()`) alone leaves most of it in place.
- Suggested change: Walk with an explicit `os.scandir` stack carrying the relative prefix as a string and an `in_proxy` flag; size from `entry.stat().st_size`; `VIDEO_EXTS` as a frozenset. Must keep: the conflict-marker count ahead of the extension filter, the NFC fold only for comparison, the bytes-on-disk rel that is returned, the present-before-and-after check in `refresh_once`, and `size_fn` as a test seam (make `entry.stat` the default and accept an override).
- Effort / risk: S effort; low risk (output pinned by the existing manifest tests; the probe shows equal rollups).

### comp-core-2 - An unchanged manifest is still re-sent in full every 10 minutes, and one changed project re-sends all of them
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/reporter.py:212 (`SECTION_RESEND_SECONDS = 600`), :1162-1186 (whole-section digest); dashboard/src/ccsync_dashboard/api.py:11378-11393, db.py:11423-11455 (DELETE + INSERT per project)
- What: Suppression is all-or-nothing per section: `local_manifest` is one sha1, so a new file in one ticked project re-sends every ticked project's per-file lists, and the server DELETEs and re-INSERTs all of them. And even with nothing changed, the forced 600 s resend ships the whole section again so the server can re-learn what it already holds.
- Cost / failure scenario: An editor with 10 ticked projects of ~5k files: the heavy body is 3.55 MB (measured) and the server rewrites ~40k `editor_media` rows, 0.27 s of write locks on desktop NVMe (27 ms per project; a NAS is slower). Idle, that is 144 resends a day: about 510 MB a day of upload per machine and ~5.8M row writes a day, every one of them a no-op. At 20 machines: ~10 GB/day into the dashboard and ~115M no-op row writes/day, all retained by the hourly ZFS snapshots (res-time-scale-10). While one project is syncing, the 300 s rescan changes the section and the other nine are rewritten with it.
- Evidence: `probe_manifest.py` (3.55 MB body for 10 selected projects, 16.8 MB for 64); `probe_server_write.py` (10 x 4,000-row `replace_editor_media` = 0.27 s, WAL grew 4.7 MB); code read of `_drop_unchanged_sections` (`(now - sent[1]) >= SECTION_RESEND_SECONDS` re-sends regardless of digest).
- Ledger: related to CR-62 (open: "the per-project change signal"), res-time-scale-10 and PL-RES-44 (open, gzip). The quantified cost of the forced resend and the keep-alive alternative below are new.
- Suggested change: Keep digests per project key (and per media-tree project), send only the changed keys (the server already treats an absent key as "leave it alone"). Replace the forced full resend with a keep-alive: send `{rel: digest}` for unchanged projects; the server bumps `refreshed_at` / `reported_at` with one UPDATE when its stored digest matches and answers `resend: [rels]` when it does not (restored backup, pruned rows, truncation). Must keep: the 14-day age-out still sees live machines (the keep-alive touches the timestamps), a failed POST suppresses nothing, a new editor identity clears the state.
- Effort / risk: M effort (both sides of the wire, additive field, dashboard first); low-medium risk.

### comp-core-3 - Once `_fit_payload` has trimmed the manifest, it is never suppressed again: rebuilt, shed and re-sent every heavy tick, with a WARNING every minute
- Category: bug
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/reporter.py:1177-1183 (compares the digest of the UNFITTED section), :1199-1206 (`_note_sections_sent` stores the digest of the FITTED section), :1259-1262 (the WARNING)
- What: `_drop_unchanged_sections` runs before fitting and hashes the full manifest; `_note_sections_sent` runs after the POST and hashes the trimmed one. When the body is over budget the two never match, so the unchanged-section suppression (CR-62, ops-efficiency-1) is permanently off for exactly the machines with the biggest manifests. Fitting is deterministic, so the same input always yields the same trimmed output; nothing is gained by re-sending it.
- Cost / failure scenario: An editor with 30 ticked projects of >=2,000 files (8.5 MB untrimmed): every 60 s the reporter serialises ~8.5-18 MB twice (digest, then fit), trims, sends, and logs `report payload is 8.5 MB (budget 7.3 MB): dropped the per-file lists ...` at WARNING. 60-140 ms of CPU and a transient multi-MB string per minute, 1,440 identical WARNING lines a day pushing the useful lines out of the rotated `companion.log` a support session reads, and 30-64 `editor_media_project` upserts a minute on the dashboard instead of one round every 10 minutes.
- Evidence: `probe_suppress.py`: three heavy posts of an unchanged manifest. 10 projects (2.8 MB, under budget): sent, omitted, omitted (CPU 58, 11, 11 ms). 30 projects: sent, sent, sent, each 4,925 bytes after trimming, CPU 82, 60, 61 ms, WARNING each time. 64 projects: sent x3, 141, 141, 137 ms.
- Ledger: new (a hole in CR-62's fix; KNOWN_BUGS states the fitted digest is recorded on purpose but not this consequence).
- Suggested change: Record both digests on acceptance (`(unfitted, fitted, at)`) and suppress when the new unfitted digest equals the stored unfitted one; keep the fitted one only for the "shed means not sent" rule. Log the budget WARNING on a change of the shed set, DEBUG otherwise. Must keep: a shed section still counts as not sent; a server-truncated reply still clears the state.
- Effort / risk: S effort; low risk.

### comp-core-4 - One byte over the budget strips the per-file lists from EVERY ticked project, not just enough of them
- Category: bug
- Severity: medium
- Confidence: CONFIRMED (companion side); dashboard consequence PLAUSIBLE
- Where: companion/src/ccsync_companion/reporter.py:1241-1266 (step 1 of `_fit_payload`)
- What: Step 1 sets `originals`/`proxies` to None on every project in one go and only then re-measures. The manifest is already in priority order (ticked, then most recently touched), so dropping lists from the tail until the body fits would keep the file lists of the projects that matter. Instead a machine that crosses 7 MiB by one project loses all of its per-file presence at once.
- Cost / failure scenario: An editor ticks a 26th project of >=2,000 files (body ~7.4 MB). From the next heavy report every project goes rollup-only. On the dashboard, `replace_editor_media` is no longer called for any of them, so their `editor_media` rows freeze at the last full report and are deleted by the 14-day age-out (db.py:10807-10809), after which the per-file sync view for that machine has nothing for any project, not just the new one. The editor did nothing but tick one more project.
- Evidence: `probe_suppress.py`: 30 projects at 8.5 MB -> `dropped the per-file lists from 30 project(s)`, final body 4,925 bytes against a 7.3 MB budget (99.9% of the budget unused). Dashboard path read at api.py:11388-11391 (lists only replaced when not None).
- Ledger: new; related to res-time-scale-4 (open, per-project 2000-file cap) and B6.
- Suggested change: In step 1 drop lists from the lowest-priority projects first (iterate the manifest in reverse order, re-measure every few projects or by subtracting each project's encoded size), stopping as soon as the body fits. Must keep: copies, never in-place edits of the cache's dicts; `truncated: True` on every project that lost its list; the later shedding steps unchanged.
- Effort / risk: S effort; low risk.

### comp-core-5 - A changed heavy section is serialised three times per report
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/reporter.py:360-371 (`_section_digest`, sort_keys), :1177 (digest before fitting), :1236 (`_fit_payload` encode), :1202 (digest again after the POST)
- What: Each heavy tick with a changed manifest JSON-encodes it once with `sort_keys` to digest it, once to measure and send it, and once more with `sort_keys` to record what was accepted. When nothing was trimmed the third digest is identical to the first. And on every idle heavy tick (60 s) the unchanged manifest is still re-encoded once just to discover it is unchanged, although `ManifestCache` knows whether it rescanned.
- Cost / failure scenario: 10 projects: 8 + 11 + 8 ms; 64 projects: 59 + 55 + 59 ms plus transient copies of a 16 MB string; the idle digest is 8-59 ms a minute per machine. Small, but it is on the reporter thread on the base rig, which also runs the encoder and the indexer.
- Evidence: `probe_manifest.py` timings (encode 11 / 55 ms, digest 8 / 59 ms for 10 / 64 projects).
- Ledger: new (COMP-CORE-5 of 2026-08-14 removed the fourth serialisation; these three remain).
- Suggested change: Reuse the pre-fit digest in `_note_sections_sent` when the section came through `_fit_payload` untouched; give `ManifestCache` (and the media-tree cache) a generation counter so an unchanged generation skips the digest entirely. Must keep: digest of the fitted content when it was trimmed (or the two-digest rule of comp-core-3).
- Effort / risk: S effort; low risk.

### comp-core-6 - On macOS the idle probe spawns `ioreg` on every report tick, uncached
- Category: idle
- Severity: low
- Confidence: PLAUSIBLE (not measurable on this Windows rig)
- Where: companion/src/ccsync_companion/idle.py:213-260 (`default_ioreg_run`, no cache); capabilities.py:317 and :383 (`idle_seconds` recomputed on every build, cached assembly or not); app.py:2396 / 2485 / 7639 (the same probe handed to the jobs runner and ingest)
- What: `capabilities.build` deliberately re-reads `idle_seconds` on every report, and on a Mac each read is a `/usr/sbin/ioreg -c IOHIDSystem -d 1 -w 0` subprocess. The report runs every 5 s while any lane is syncing and every 60 s otherwise; the jobs runner and ingest ask the same probe on their own cadence.
- Cost / failure scenario: Estimated 10-30 ms per spawn (fork/exec plus an IOKit dump): ~17,000 spawns a day on a Mac during an all-day upload, ~1,440 idle. Small on its own, but it is a process spawn every 5 s on a laptop on battery, for a number whose resolution the scheduler needs only to the minute (the idle floor is 60-300 s).
- Evidence: code read; no cache in `MacIdleProbe.seconds_idle` or `default_ioreg_run`. Windows uses `GetLastInputInfo` (no spawn) and is unaffected.
- Ledger: new.
- Suggested change: Cache the ioreg answer for ~5 s and extrapolate (`cached + (now - cached_at)`; any input resets it on the next real read). Must keep: None still means "cannot tell, so NOT idle" on both sides; a cached value never claims more idleness than real time allows.
- Effort / risk: S effort; low risk.

## What is already good
- Signature and hash cost: `ed25519.verify` is 2.9 ms (the module comment says ~15 ms) and runs once per report reply that carries an offer; the package sha256 is streamed during the download in 256 KiB chunks (27 ms per 100 MB). Neither is worth caching or replacing with a native library.
- The supervisor imports nothing of the companion (36 ms import) and blocks in `WaitForSingleObject` on Windows: zero wakeups while the tray is alive.
- Capability probes are bounded: the assembly is cached 45 s, `ffmpeg -version` / `ffprobe -version` 300 s (24-26 ms each), `nvidia-smi` 600 s (47 ms), the encoder list once per binary. About 0.2 ms of spawn per second in total.
- Disk bounds: crash JSONs capped at 20, the native fault log dropped past 512 KB, `companion.log` rotated, reporter state written at most once a minute unless the status changes, `config.set_value` under one RLock with tmp + harden + replace + re-read, `machine_settings` reads config.toml only on an mtime/size change, the transport DNS verdict cached 30 s.

## Coverage note
Did not read shutdown_guard.py, eula.py, state_acl.py, win_trust.py, canon.py, paths.py or machine.py beyond greps, nor the light-tick payload end to end on the dashboard (what a 5 s light report writes server-side). Did not measure the walk over SMB (no NAS access by rule); the SMB figures above are estimated from the per-file round trip.

## OUT OF TERRITORY
- companion/src/ccsync_companion/resolve_journal.py:682-710: `summaries()` globs every journal dir and fully parses the newest 20 journals (up to 5,000 entries each) on every heavy tick, to report counts that change only when a journal is written; cache by (path, mtime).
- companion/src/ccsync_companion/app.py:2092-2098 / 10574: ManifestCache starts regardless of mode or `sync_enabled` (already PL-RES-107 / prac-perf-3, open).
- companion/src/ccsync_companion/selection.py:214-288: the plan is re-fetched every 30 s (`selection_fetch_ttl`) whether or not it changed; a plan generation on the report reply would let it fetch only on change.
