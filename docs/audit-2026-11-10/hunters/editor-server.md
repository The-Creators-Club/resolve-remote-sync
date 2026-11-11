# editor-server - the rebuilt Timeline Cards editor's server side (sync store, cutmd, media, auth/mount) and how the dashboard hosts it

Files read (approximate coverage): editor tree (`C:\Users\alex\AppData\Local\Temp\claude\tc-standalone\Resolve\MulticamPipeline\editor`, branch `standalone-editor`, 3dcf3b6): PERF.md, README.md (all), docs/NAS-CUTOVER.md (all); server/main.ts, server/app.ts, server/auth.ts (all); server/sync/store.ts, service.ts, options.ts, oplog.ts, fsx.ts, keys.ts (all), lock.ts (header + beat); cutmd/src/render.ts (all), cutmd/src/index.ts; core/src/reduce.ts (applyOp, guard, setGain), core/src/check.ts (checkProject), core/src/protocol.ts (LIMITS); server/media/service.ts and range.ts (all); server/pybridge/index.ts and server/ai/runner.ts (close paths only); features/projects/host.ts (all - the mount wrapper `host.mjs` is built from). ccsync: dashboard/src/ccsync_dashboard/cards_edit.py (all), docs/CARDS_EDITOR.md (all); uvicorn 0.52.3 `httptools_impl.send`, starlette 1.6.0 `middleware/base.py`. Old page: MulticamPipeline `cards/cutlist.py` save/write_text, `cards/project_engine.py` _stamp/_moved/reload.
Probes run: `probe.ts` (scratch copy of `core/` + `cutmd/`, run with plain `node` 24.14.1 type stripping, nothing run in the editor tree) against the fixture cut lists in `%TEMP%\claude\tc-fixtures\cutmd`: FF5 Framing Formosa E1 V1 (562 KB, 1,536 cuts + 1,029 bench items) and Reproductive Rights Ordered V5 (194 KB, 621 cuts). Results are quoted in the findings. Scratch: `C:\Users\alex\AppData\Local\Temp\claude\0821e15b7e474fe8\33581ba8-e460-4553-81c2-83b2208b6619\scratchpad\editor-server\ed\probe.ts`.

## Findings

### editor-server-1 - Every debounced .cut.md rewrite parses the whole file twice, copies it to .bak and fsyncs four times, all on the one event loop
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: editor `server/sync/store.ts:773-835` (`writeFile`), `cutmd/src/render.ts:45-55` (`render` already re-parses its own output to check it)
- What: After every saved edit (debounce `TC_WRITE_DEBOUNCE_MS`, 150 ms) the store renders the whole head with `renderForWrite`, which itself calls `parse(out)` to verify the preserving writer; then `writeFile` parses the same text AGAIN only to get `.layout` (line 831). Around that it writes head.json (atomic, fsync), the `.tmp` (fsync), copies the whole old file to `.bak`, renames, stats, and writes head.json again (fsync). All parsing and rendering is synchronous on the Node thread that also serves every socket ack, media request and Python bridge reply.
- Cost / failure scenario: Measured per write: Framing Formosa E1 (1,536 cuts) render 26.6 ms + extra parse 14.6 ms + hashes 1.9 ms = ~43 ms of blocked event loop; Reproductive Rights (621 cuts) ~15 ms. During a drag-trim or a held key the client sends ops continuously, so a write fires roughly every 150 ms + write time: up to ~5-6 writes/s, i.e. ~20-25% of a core and a 43 ms stall every ~200 ms for every other user and media range on that server (the NAS container's CPU is slower than this workstation; estimated 1.5-2x). Disk per write: ~1.6 MB (tmp + .bak of a 560-800 KB file) + 4 fsyncs into the vault dataset, which ZFS snapshots hourly. About a third of the CPU (the second parse) is pure repetition.
- Evidence: probe.ts timings above; render.ts line 52 `parse(out).project` inside `render`; store.ts line 831 `this.layout = parse(text, this.key).layout;`.
- Ledger: new (PERF.md covers only the client's frame budget)
- Suggested change: Return the verification parse's layout from `render`/`renderForWrite` (e.g. `renderForWriteWithLayout` returning `{text, layout}`; when the canonical fallback is taken, parse once there) and drop the second parse. Consider raising the write debounce to ~1 s under continuous editing (the op log, not the file, is the durability, as the store's own header says) and making the `.bak` copy at most once per N seconds. Must keep: the preserving writer's check (it is the round-trip guarantee), `diskIsOurs` before rename, head.json `writing` markers.
- Effort / risk: S effort; low risk

### editor-server-2 - /cards and /cards/edit both edit the same vault .cut.md files with no shared lock during the "beside" phase
- Category: concurrency
- Severity: medium
- Confidence: PLAUSIBLE
- Where: ccsync `dashboard/src/ccsync_dashboard/cards_edit.py:287-289` (`--write` on the old page's vault); editor `README.md` "Pointing it at the real vault" ("Do not run the old Timeline Cards server with its edits on the same cut list at the same time: each would see the other's writes as outside edits"); editor `server/sync/store.ts:921-986` (external-edit merge); MulticamPipeline `cards/project_engine.py:1730-1800` (old engine's `_moved_really` / `reload`)
- What: The cut-over plan (NAS-CUTOVER.md phases 3-4) runs both editors live on one vault, each believing it owns the file. The new editor's lock lives in `.tcards/<name>/lock`, which the old engine does not read; the old engine's change detection is stat + sha1 before its own save. Each side treats the other's writes as an external edit and merges by diff.
- Cost / failure scenario: (a) Lost update: the old engine checks `_moved` and then writes `<path>.tmp` + `os.replace`; a new-editor write landing between the old engine's check and its replace is overwritten, and the new editor then merges the old engine's file as an Obsidian edit, diffing it against what it last wrote, which yields ops that UNDO the overwritten edits (logged as "merged an edit made to the file outside the editor"). The window is milliseconds per save, but the new editor writes every ~150 ms while someone edits, so two people on one episode (or one person with both tabs) hit it within a session. (b) Cost even without a race: every new-editor write makes the old engine's next look see a moved file, reload and `_reslice_all` the whole list (the old engine's own note: 435 cuts make this the expensive path), and adds a `.history` revision per old-page save. Nothing in the landing page or either editor tells the person the other one has the file open.
- Evidence: code read on both sides as cited; no cross-editor lock or "open elsewhere" signal exists in cards_edit.py, host.ts or the old engine. Not reproduced live (read-only rules).
- Ledger: new (the editor README states the hazard; CARDS_EDITOR.md and NAS-CUTOVER.md do not, and the deploy puts both on one vault)
- Suggested change: Cheapest safe guard: have the old engine refuse (read-only banner) a cut list whose `.tcards/<name>/lock` is held and beating, and have the new editor show a notice when the file's `written:` stamp says the old page wrote it; or mount `/cards/edit` read-only (`TC_WORK`) until the flip. Must not break: the new editor's Obsidian-merge path, which is the same mechanism and is wanted.
- Effort / risk: M effort; low risk

### editor-server-3 - The projects list walks the vault four folders deep on every request, uncached
- Category: perf
- Severity: low
- Confidence: PLAUSIBLE
- Where: editor `server/sync/keys.ts:90-110` (`findCutLists`), called by `server/sync/service.ts:273-282` (`GET /api/projects`)
- What: Every `/api/projects` (the projects sheet, the landing's chooser) runs `readdir` on every non-hidden folder down to depth 4 under `TC_VAULT`, then a `stat` per cut list. The peek of each file is cached by size+mtime, but the walk is not. Under `Vault/<year>/<series>/<Episode>/` depth 4 reaches the episodes' own subfolders (Interviewees, media folders).
- Cost / failure scenario: Estimated: with ~100 episodes and ~10-30 folders each within depth 4, ~1,000-3,000 `readdir` calls per open of the sheet on the NAS pool; on a warm ARC cache tens to a few hundred ms, cold seconds. Grows linearly with the vault (500 projects: ~5x). Runs on demand only, so no idle cost.
- Evidence: code read; not timed against the real vault (the brief forbids touching it).
- Ledger: new
- Suggested change: Cache the key list for ~30 s (as `cards_edit.newest_cut` already does on the dashboard side) and invalidate it on the editor's own create/rename/duplicate routes. Must keep: new cut lists made by the old page appearing within the TTL.
- Effort / risk: S effort; low risk

### editor-server-4 - Each cut list keeps up to 100 old log segments, three full snapshots, a .bak and an unpruned quarantine inside the vault
- Category: disk-growth
- Severity: low
- Confidence: CONFIRMED (retention rules) / estimated (sizes)
- Where: editor `server/sync/options.ts:49-50` (`keepSnapshots: 3`, `keepOldSegments: 100`), `server/sync/store.ts:870-881` (`prune`), `store.ts:456-459` and `952-954` (quarantine writes, never pruned)
- What: Segments roll every `TC_SNAPSHOT_EVERY` (200) ops; 100 segments before the oldest kept snapshot are retained, i.e. ~20,000 ops of history per cut list beyond what recovery needs (recovery needs only the newest verifying snapshot plus the segments after it). Snapshots are the full project JSON. The quarantine folder gets a full copy of the file for every unreadable external edit (after 3 looks) and every torn write, and nothing ever deletes them.
- Cost / failure scenario: Estimated per actively edited cut list: 3 snapshots x 0.8 MB (measured snapshot size for the 1,536-cut list) + ~20k entries x 300-600 bytes = ~8-15 MB; across ~100-300 edited cut lists, 1-4 GB of `.tcards` inside the vault dataset, churned by ZFS hourly snapshots. Quarantine grows only with incidents (low).
- Evidence: options.ts and prune() as cited; snapshot size from probe.ts (`JSON.stringify` of the project: 799,342 bytes).
- Ledger: new
- Suggested change: Lower `keepOldSegments` to a small number (e.g. 5) unless the history is a deliberate feature, and cap quarantine by count/age (e.g. newest 20 or 30 days). Must keep: `findInLog`'s dedupe beyond the 10k window, which reads old segments; if retries older than a few thousand ops are possible, keep enough segments to cover `dedupeWindow`.
- Effort / risk: S effort; low risk

### editor-server-5 - New log segments and renamed snapshots / head.json are not followed by a directory fsync
- Category: resilience
- Severity: low
- Confidence: PLAUSIBLE
- Where: editor `server/sync/oplog.ts:105-110` (`SegmentWriter.open` creates the file), `server/sync/fsx.ts:51-65` (`atomicWrite`: fsync of the temp, rename, no fsync of the parent)
- What: Acks wait for `fh.sync()` of the segment, which makes its bytes durable, but the directory entry of a segment created at the last snapshot (and the rename of a snapshot) is not synced. On a power cut (not a SIGKILL, which loses nothing here) a filesystem that does not order the create with the file's fsync can lose a whole freshly created segment holding acked ops.
- Cost / failure scenario: Only power loss / kernel crash on the host, only for ops acked since the last segment roll (up to 200). The NAS is ZFS, whose ZIL makes this unlikely there; a Windows/ext4 standalone run is the exposed case.
- Evidence: code read; not reproduced (needs a power-cut harness).
- Ledger: new
- Suggested change: fsync the log and snap directories after creating a segment and after each rename (open dir 'r' + sync; skip silently on Windows where it is unsupported). Cost: one fsync per 200 ops.
- Effort / risk: S effort; low risk

### (cited, not re-described) Media streams through /cards/edit keep running after the browser leaves
Independently confirmed from uvicorn 0.52.3 `httptools_impl.py:467-468` (`if self.disconnected: return`, spec 2.3) and starlette 1.6.0 `_StreamingResponse`: `cards_edit.Passthrough` never sees the abort, so httpx pulls the editor's `/media/video` or `/media/audio` `bytes=N-` answer to EOF. Already reported as dash-mounts-1. On the editor's own side the stream IS destroyed on close (`server/media/range.ts:70-71`), so the fix belongs in the proxy only.

## What is already good
- Per-op cost is tiny: `applyOp` with its full `checkProject` guard is 0.43 ms at 1,536 cuts (measured), entries are stringified once for the fan-out, and ops batch under one fsync (group commit, `maxBatch` 256). Do not "optimise" the guard away.
- Memory per open project is bounded (dedupe 10k, catch-up 5k entries / 64 MB, 256 structurally shared states) and a project with no clients is flushed and closed after 10 minutes; per-socket state is freed on close; slow sockets are terminated at 32 MB `bufferedAmount`; heartbeats every 15 s. Idle cost per open project: one `stat` every 2 s and one lock beat every 10 s, nothing when nothing is open.
- Durability: no ack before fsync; a torn last line is cut and quarantined; the `.cut.md` is a view rebuilt from the log, and `writing`/`prepared` markers in head.json distinguish a torn write from an Obsidian edit. SIGTERM flushes every store; feature closes are bounded (Python workers SIGKILL after 2 s), well inside the dashboard's 15 s grace.
- Trust: the mount checks `X-TC-Proxy-Secret` (HMAC-then-`timingSafeEqual`, constant time) before any route, the index page or `sw.js` is served; the dashboard binds the child to 127.0.0.1; client `X-TC-*` is stripped by the proxy. Keys are checked as text and by `realpath` against the vault; static files are confined with a prefix check.
- Range parsing is strict (single range, 416 for unsatisfiable), ETag/If-Range honoured, the read stream destroyed on `res` close; PCM windows go through a capped disk LRU, a decode gate (3 + queue 12) and a coalescer, and ffmpeg children are aborted when the request goes.

## Coverage note
Not reached in the time box: `server/media/library.ts`, `cache.ts` (DiskLru eviction cost), `ffmpeg.ts` (child kill on abort - read only via the service's AbortSignal use), `peaks.ts`, `loudness.ts`; `server/pybridge` beyond close (restart/backoff, stdout framing); `server/ai/runner.ts` beyond close; `server/platform/workqueue.ts`; `core/src/reduce.ts` beyond applyOp/guard/setGain (insertRun/move cost on large pastes not measured); `cutmd/src/parse.ts` and `diff.ts` (round-trip fidelity of unreadable lines in a CHANGED block: render.ts documents that they are dropped there, not verified which inputs parse as warnings rather than problems); `adapters/`, `scripts/`; startup time of `host.mjs` (1.06 MB bundle, not run). Memory of 256 kept states was reasoned from the reducer's copy-on-write, not measured.

## OUT OF TERRITORY
- ccsync `dashboard/src/ccsync_dashboard/cards_edit.py:701-726`: the Passthrough docstring says a departed browser is noticed by `send` failing; on uvicorn 0.52.3 it never is (dash-mounts-1).
- ccsync `dashboard/src/ccsync_dashboard/cards_edit.py:875-882`: `to_editor` relays browser frames with no size cap of its own (the editor's 8 MB `maxPayload` is the only bound); fine today, note if the editor's limit changes.
