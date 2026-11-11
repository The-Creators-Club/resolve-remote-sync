# lens-sql - every SQLite database in the product except the dashboard's main DB
Files read (approximate coverage): footage-sorter `footage_sorter/ledger.py` (schema, hot statements, `_tx`, `_rd`, volumes_view, `_volume_stats`, `_not_home`, `batch_summaries`, `report_volumes`, `backup`), `engine.py` (thread starts, `ledger_summaries_now`), `public/ledger.js` (poll + `changed()`); ccsync `broll/web/app/db.py` + `client_folders.py` (connection helpers), `music/web/musicweb/db.py`, `ytdl/web/ytdlweb/db.py` (connect), `companion/.../ledger_mirror.py` (connect), `teracopy.py` (history DB reader), `library.py` (Resolve Project.db reader, grep only), `broll/indexer/broll_index/storage/sqlite_backend.py` (grep), `server/publish_db.py` (grep); MulticamPipeline `transcripts/multicam_transcripts.py` (Resolve Project.db reader); the `/cards/edit` server (grep only: it has no SQLite). Territory reports web-broll, web-music, web-ytdl, comp-field, idx, dash-mounts (titles + the SQL-related findings).
Probes run (scratch `...\scratchpad\lens-sql\`, system python 3 + the sorter's own `Ledger` class, never a live DB): `p_readers.py` (200 short-lived threads each calling `Ledger._rd()` on a 200k-row ledger), `p_big.py` (the real `Ledger` schema filled to 2,010,000 copies over 4 volumes, `ANALYZE`, timing `_volume_stats` and `_not_home`, EXPLAIN QUERY PLAN), `p_big2.py` (same with one candidate partial covering index), an online-backup + `integrity_check` timing of the 458 MB file.

## Inventory

| DB file | Owner module | Writers, cadence | PRAGMAs (where set) | Connection lifetime | Write batching | Grows forever / pruned by | VACUUM / checkpoint | Lives on |
|---|---|---|---|---|---|---|---|---|
| `ledger.db` (Footage Sorter) | footage-sorter `footage_sorter/ledger.py` | dashboard process (`/sorter` mount): every companion volume report (one tx, every volume row UPDATEd), scan chunks, scan finish, copy receipts, moves; plus `ledger_import --write` as a second process | WAL, synchronous=NORMAL, temp_store=MEMORY on the ONE writer conn; readers get only `query_only=1`; no busy_timeout pragma (timeout=60 in connect); foreign_keys not set; cache/mmap default | writer held for process life; readers one per THREAD, held forever (see lens-sql-1) | one `BEGIN IMMEDIATE` per operation, executemany for chunks - good | `copies` keeps missing/deleted/moved rows by design (history); `scans` rows never pruned; `stage`/`scan_chunks` cleared per scan | no VACUUM; autocheckpoint default; daily online backup + integrity_check, 7-ish kept | NAS container data dir (local ZFS) |
| `broll.db` | ccsync `broll/web/app/db.py` (web), `broll/indexer/.../sqlite_backend.py` (indexer) | web: ingest/curation writes per request; indexer: base rig, commit per file (idx-9) | WAL persisted by `ensure_schema`; foreign_keys per connection; no busy_timeout (default 5 s), synchronous default FULL | per request (`get_db`) | per request | see web-broll / idx | publish via `server/publish_db.py` (checkpoint TRUNCATE on the source, quick_check on the NAS, then swap) | container data dir; indexer copy `E:\broll-queue` local |
| `client_shares.db` | `broll/web/app/client_folders.py` | share curation, rare | WAL (ensure_schema), foreign_keys per conn | per request; `ensure_schema` per request (one PRAGMA) | per request | small | none needed | beside broll.db, kept out of publish on purpose |
| `music.db` | `music/web/musicweb/db.py`, `drain.py`, `ingest_batches.py` | container: ingest ledger, rescore; base rig indexer then publish/drain | WAL from schema.sql; foreign_keys per conn; timeout=30 | per call/request | per batch | `ingest_batches/items` never pruned (web-music-10) | publish_db / drain apply | container data dir |
| `ytdl.db` | `ytdl/web/ytdlweb/db.py` | worker every 5 s (indexed claim), filter/enrich per row (web-ytdl-5) | WAL from schema.sql; foreign_keys per conn; timeout=30 | per call | per row in two phases (web-ytdl-5) | `job_videos`/`job_video_terms` never pruned (web-ytdl-7) | none | container data dir |
| companion ledger mirror | `companion/.../ledger_mirror.py` | field page polls, mirror pulls | WAL + full `executescript(SCHEMA)` on EVERY connect (comp-field-4) | per call | executemany per pull | keyed on plugged volumes (comp-field-7) | none | `~/.ccsync` local (configurable `ledger_mirror_path`) |
| TeraCopy History `*.db` | `companion/.../teracopy.py`, sorter `lib/teracopy.js`, `ingest/tray/TeraCopyStatus.py` | TeraCopy itself | read with `mode=ro` (not immutable), timeout 1 s | per poll, closed | n/a (read only) | TeraCopy's | n/a | `%APPDATA%\TeraCopy\History` local |
| Resolve `Project.db` (Disk libraries) | `companion/.../library.py`, MulticamPipeline `transcripts/multicam_transcripts.py` | Resolve | `mode=ro`; library.py uses a progress handler as a statement timeout | held per bind | n/a | Resolve's | n/a | `%APPDATA%\Blackmagic Design\...` local |
| backup ledger (Cloudflare D1) | footage-sorter `cloud/ledger` Worker | sorter cloud sync | D1-managed | n/a | n/a | not read | n/a | Cloudflare |
| `/cards/edit` editor server | tc-standalone `editor/server` | - | no SQLite (grep for sqlite / better-sqlite3 / DatabaseSync: none) | - | - | - | - | - |

No database in this territory is opened over SMB: every writer opens a file on the machine's own disk (container dataset, `~/.ccsync`, `E:\broll-queue`, `%APPDATA%`). The two-process cases are guarded: `ledger_import --write` vs the dashboard (WAL + `BEGIN IMMEDIATE` + 60 s timeout + the `meta.changes` counter that `check_external` reads), and broll/music publish (staged copy, quick_check, swap; drain instead of copy-back).

## Findings

### lens-sql-1 - The sorter ledger opens a new SQLite connection for every short-lived thread and never closes it: ~2.3 MB and two handles per ledger change while the sorter page is open
- Category: leak
- Severity: high
- Confidence: CONFIRMED
- Where: footage-sorter `footage_sorter/ledger.py:342-351` (`_rd`: thread-local connection, appended to `self._readers`, closed only in `close()`); `footage_sorter/engine.py:808` (`ledger_summaries_now` starts a NEW `sorter-ledger-sums` thread on every ledger version change), also `engine.py:387, 422, 939, 1451, 1477`, `ledger_sources.py:227, 365` (one thread per event)
- What: `_rd()` caches the reader in `threading.local()`, but also appends it to `self._readers` so `close()` can reach it. A thread that exits drops its `threading.local` slot, yet the list still holds the connection, so it is never closed or collected. The anyio threadpool reuses ~40 threads (bounded), but `ledger_summaries_now` spawns a fresh thread each time `led.version` moves while a page asks for `/api/clips`, and `batch_summaries` calls `_rd()` there; scans, moves, audits and NAS/cloud listings do the same per event.
- Cost / failure scenario: one leaked connection per ledger change that a page sees (a scan finishing, every copy receipt batch from field backup / auto-backup at home, every move, every answered question, every `ledger_import --write`), for the life of the dashboard process. Measured: 200 short-lived threads each doing one `count/sum` read of a 200k-row ledger -> `len(_readers)` 200, +401 OS handles, +466 MB RSS (each connection keeps its own up to 2 MB page cache plus the `-shm` map). At a few dozen changes a day that is hundreds of MB within weeks in the one uvicorn process that also runs the fleet dashboard; at commercial scale (busier fleets, auto-backup posting receipts per batch) days.
- Evidence: `p_readers.py`: `readers 200 handles + 401 rss +MB 466.1`.
- Ledger: new
- Suggested change: open a per-call reader in the short-lived threads (or close the thread's connection in a `finally` at the end of each spawned `run`), or keep the readers in a small fixed pool keyed by nothing that keeps arriving; also make `ledger_summaries_now` single-flight with one long-lived worker instead of a thread per change. Must keep: readers never share the writer connection, `query_only=1`.
- Effort / risk: S effort; low risk

### lens-sql-2 - Every ledger change makes each open page re-run two whole-table scans of `copies`: 1.0 s + 0.7 s at 2M files, and the stats scan has no covering index
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: footage-sorter `footage_sorter/ledger.py:576-585` (`_volume_stats`), `:1548-1572` (`_not_home`), `:544-546` (memoised on `version`), `public/ledger.js:358-365` (`changed()` reloads volumes, questions, not-home and rows on every version change the 2 s activity poll sees)
- What: `_volume_stats` is `SELECT volume_id, role, count(*), sum(size) FROM copies WHERE live GROUP BY volume_id, role`; the plan is `SCAN copies USING INDEX copies_seq` + `USE TEMP B-TREE FOR GROUP BY`, i.e. every row of every volume visited through the table. The memo only lasts until the next `version` bump, and each bump makes every open sorter page call `/api/ledger/volumes` and `/api/ledger/not-home` at once (two pages racing the memo may both build it).
- Cost / failure scenario: today ~100 projects x tens of thousands of files puts the ledger in the high hundreds of thousands to 2M rows (10x target used: 2,010,000). Measured on NVMe: `_volume_stats` 1013 ms, `_not_home` 701 ms per change per process; on the NAS's ZFS/HDD pool, estimated several times that, and it holds a threadpool worker each time. During a working day with copy receipts and scans landing every few minutes that is a second or more of dashboard CPU per change.
- Evidence: `p_big.py` (2,010,000 rows, ANALYZE): `_volume_stats: 1013 ms`, `_not_home: 701 ms`, plan above. `p_big2.py` with `CREATE INDEX copies_stats ON copies(volume_id, role, size) WHERE missing_since IS NULL AND deleted_at IS NULL`: plan `SCAN copies USING INDEX copies_stats` (covering), 114-116 ms - 9x faster.
- Ledger: new
- Suggested change: add that partial covering index in a v4 migration (cost: one more index on a ~460 MB-at-2M table, roughly +15%); for `_not_home`, keep a per-(name_lc,size) "home" flag or narrow the CTE to master/audio via a partial index on `(name_lc, size, volume_id) WHERE live AND role IN ('master','audio')`. Must keep `tests/py/test_ledger_plans.py` green (it EXPLAINs the hot statements).
- Effort / risk: S effort; low risk

### lens-sql-3 - The daily ledger backup holds the writer lock for the whole online backup
- Category: concurrency
- Severity: low
- Confidence: CONFIRMED
- Where: footage-sorter `footage_sorter/ledger.py:1724-1729` (`with self._wlock: self._w.backup(dst)`)
- What: the backup is taken from the writer connection under `_wlock`, in one step (`pages=-1`), so every companion volume report, copy receipt and scan chunk waits for it. In WAL mode a separate read connection sees a consistent snapshot and needs no writer lock at all.
- Cost / failure scenario: once a day; measured 0.9 s for the 458 MB 2M-row file to a local NVMe file, estimated several seconds when the destination is the HDD pool (and `integrity_check` adds 2.6 s, outside the lock). Requests block for that long; harmless today, a visible stall at commercial size.
- Evidence: online backup timing of the probe DB: `backup s 0.9`, `check s 2.6`.
- Ledger: new
- Suggested change: back up from a fresh `query_only` connection (`sqlite3.connect(path).backup(dst)`) without taking `_wlock`. Must keep: never a file copy of the live DB or its WAL.
- Effort / risk: S effort; low risk

## What is already good
- The sorter ledger's hot delta statements are written against the planner on purpose (CROSS JOIN to pin the small side, named statements EXPLAINed by `test_ledger_plans.py`), with one `BEGIN IMMEDIATE` writer and executemany chunks; leave them alone.
- `publish_db.py` (checkpoint TRUNCATE on the source, quick_check on the NAS, staged swap) and the music drain are the right answer to "two processes, one live WAL DB"; nothing here is SQLite over SMB.
- `client_shares.db` kept out of `broll.db` so a publish can never take client links with it.
- TeraCopy and Resolve databases are only ever opened `mode=ro`, filtered by creation time first (TeraCopy) and closed per poll.

## Coverage note
Not reached in the budget: 10x probes of broll.db search/list (web-broll-4 measured the search path), music.db (web-music-8/10 measured), ytdl.db at 5k jobs x 400 candidates (web-ytdl-5/7 measured the per-row commit and growth), and the companion mirror (comp-field-4 measured 2,000 connects per verdict); I cite those rather than re-probe. Not checked: whether TeraCopy's own History DB is rollback-journal (a non-immutable `mode=ro` reader polling every 5 s could then make TeraCopy's write see SQLITE_BUSY), `SQL_EXEMPT_CI`'s `lower(path)` per-volume scan, the `scans` table's growth, and `report_volumes` rewriting every volume row on every companion report even when nothing changed.

## OUT OF TERRITORY
- footage-sorter `footage_sorter/engine.py:805-808`: the "is a refresh running" check acquires and releases `_sum_lock` before starting the thread, so two requests can both start one (no single-flight).
