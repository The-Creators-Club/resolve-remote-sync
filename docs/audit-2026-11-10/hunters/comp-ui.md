# comp-ui - the companion's tray, native tray backend, Tk windows, dispatch/CR-93 pinning, and field_mode
Files read (approximate coverage): `tray_native.py` in full (Win32 + AppKit backends, HICON cache, HMENU build/destroy, Explorer re-add, toast queue); `ui_dispatch.py` in full (dispatcher, Tk guard, pin/free/orphan logic); `tray.py` about 25% (icon cache and pulse frames 255-495, `_tray_snapshot` 2912-3147 and its getters, `_menu_fingerprint` / `_guard_fingerprint` 3904-4030, `_tooltip_text`, `_build_menu` tail, `start_tray` with both loops 5163-5360, `_spawn`/`_guarded`, the Tk root sites by grep); `popup.py` about 40% (PopupDialog build/tick, ProgressWindow, WorkProgressWindow in full, dialog helpers by grep); `settings_window.py` Tk shell 1920-2209; `theme.py` icon/PhotoImage half; `ui_state.py`, `ui_copy.py` skimmed; `field_mode.py` 282-763 (verdicts, LocalCopies, LedgerView; the file has no window-drawing half - the page is `assets/field/field.js`). Followed into: `site.cached_site`/`feature_enabled`/`_brand_site`, `eula.acceptance_problem`, `ytdl_cookies.health`, `app.sync_guard`/`ingest_staging_report`, `broll_ingest._dir_bytes`, `broll_standins` ledger cache, `crash_report.crash_summary`, `field_service.card_verdict`/`state`/`_record`, `field_copy` verify phase, `ledger_mirror.where`/`_connect`, `assets/field/field.js` poll cadence.
Probes run (companion venv, all files under scratchpad\comp-ui\, nothing under ~/.ccsync):
- `probe_snapshot.py`: `_tray_snapshot` on a stub app with a redirected CONFIG_DIR: 0.317 ms per call; 5 `read_text` per call (site.json x3, eula_accepted.json, ytdl-attestation.json); `_menu_fingerprint` distinct on 300 of 300 ticks when lane C's `sending N file(s) (X GB)` count moves; `_build_menu` 0.006 ms.
- `probe_dirbytes.py`: `broll_ingest._dir_bytes` at 500 / 2,000 / 8,000 files = 6.0 / 28.5 / 158.6 ms per walk (corroborates comp-app-1, not re-filed).
- `probe_verdict.py`: real `LedgerMirror` (temp DB) + `LocalCopies`: `mirror.where` 1.00-1.34 ms per call; `LocalCopies.matching` 0.154 ms at 4,000 rows, 3.47 ms at 60,000 rows; `card_verdict` 0.90 s for 1,000 files / 4,000 local rows, 9.81 s for 2,000 files / 60,000 local rows.
- `probe_forget.py`: first `card_verdict` after the mirror has caught up with a 1,000-file card (2,000 local rows): 7.48 s, all of it in 1,000 `LocalCopies.forget()` full-file rewrites with fsync.
- `probe_pin.py`: `ui_dispatch.dispatch` with a fake root/tkapp (no real Tk): a dialog that returns leaves 0 interpreters pinned after its click thread exits; the same dialog raising leaves 1 pinned on a dead thread (permanent).
- `python -c` PNG encode of a 64 px tray frame (macOS `_ns_image` cost): 0.115 ms - below the bar, not filed.

## Findings

### comp-ui-1 - Every card lookup that finds a copy the ledger mirror now has rewrites and fsyncs the whole local-copies file, once per file
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/field_mode.py:737-751 (`LedgerView._raw` -> `self.local.forget(covered)`), field_mode.py:684-696 (`LocalCopies.forget` -> `_atomic_write` with `os.fsync`); reached from `card_verdict` (field_mode.py:336 via field_service.py:479) and from the field copier's verify phase (`view.verified_record`, field_copy.py:538, once per file already on the destination)
- What: `_raw(name, size, mtime)` is a per-FILE lookup, and whenever the mirror returns a row that also sits in this machine's own copies it calls `forget()` on just that file's rows. `forget()` filters the whole in-memory list and rewrites `field-local-copies.jsonl` in full through tmp + fsync + replace. So the catch-up that is meant to happen once happens N times, each rewriting M rows: O(N x M) bytes and N fsyncs.
- Cost / failure scenario: runs on the first `/field/api/state` after every ledger sync that follows a card copy (verdicts are invalidated by `_record` and recomputed per card), and on every re-run of a card whose files are already at a destination. Measured: a 1,000-file card copied to two drives (2,000 local rows) takes 7.48 s of rewrites before the page can answer; at the 60,000-row cap (`MAX_LOCAL_COPIES`) each rewrite is ~6 MB, so a 1,000-file card is ~6 GB written and 1,000 fsyncs (estimated tens of seconds to minutes on a laptop SSD, far worse on a USB disk). The page polls every 1-4 s and shows "Companion not answering" while this runs - in the field, at the moment the editor is deciding whether a card is safe to format.
- Evidence: probe_forget.py (7.48 s, all in forget); code read of `_raw`/`forget`/`_atomic_write`.
- Ledger: new (code from 1b7d03f / b229ee2 / bfb15de, after the 2026-10-06 hunt)
- Suggested change: have `_raw` collect covered rows into a pending set and flush them with ONE `forget()` at the end of `card_verdict` / the copier's verify loop (or lazily on the next `add`, or on a timer). The guarantee to keep: a row the mirror now covers is never counted twice and is eventually dropped from disk; dropping it a few seconds later changes no verdict, because `_raw` already de-duplicates against `seen`.
- Effort / risk: S effort; low risk

### comp-ui-2 - A card verdict opens a fresh SQLite connection, re-runs the schema, and linearly scans every local copy, once per file on the card, every 20 s
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/field_mode.py:336 (`card_verdict` -> `copies_of` per judged file), field_mode.py:672-682 (`LocalCopies.matching`, a full scan of up to 60,000 rows with `.lower()` per row); ledger_mirror.py:337-350 + 172-181 (`where` -> `_connect`: `mkdir`, `sqlite3.connect`, `PRAGMA journal_mode=WAL`, `executescript(SCHEMA)`, query, close - per call); cadence field_service.py:43 `VERDICT_TTL_SECONDS = 20.0` with field.js polling `/field/api/state` every 4 s (1 s while copying)
- What: the verdict is per-file lookups in a loop, and each lookup pays connection setup plus schema DDL plus an O(M) Python scan of the local-copies list. Neither the connection nor an index survives from one file to the next.
- Cost / failure scenario: recomputed per inserted card every 20 s while the field page is open (and immediately after every copy, via `invalidate()`). Measured: 0.90 s per verdict for a 1,000-file card with 4,000 local rows (about 4.5% of a core while the page is open, per card); 9.81 s for a 2,000-file card with the 60,000-row cap reached (about 50% of a core, per card, and the state request takes ten seconds). Two or three cards in readers multiply it. This is on a field laptop that is also running the copy.
- Evidence: probe_verdict.py: `mirror.where` 1.00-1.34 ms each (the connect + schema, the query itself is indexed), `matching` 0.154 ms at 4k rows and 3.47 ms at 60k rows.
- Ledger: new
- Suggested change: give `LedgerMirror` a `where_many(keys)` (or a context manager that holds one connection for the whole verdict) and run `executescript(SCHEMA)` once per process, not per connect; index `LocalCopies._rows` by `(name.lower(), size)` in a dict built in `_all()` and maintained by `add`/`forget`. Keep: "a copy counts only if it is still there" (`_present`) and the mtime slack, both per row, unchanged.
- Effort / risk: S effort; low risk

### comp-ui-3 - A dialog that raises on a tray click thread leaves its Tcl interpreter pinned for the life of the process
- Category: leak
- Severity: low
- Confidence: CONFIRMED (mechanism, with a fake interpreter); frequency PLAUSIBLE
- Where: companion/src/ccsync_companion/ui_dispatch.py:544-553 (`dispatch` inline path: `try: return fn() finally: reclaim_mine(...)`); same shape in `_Job.run` ui_dispatch.py:146-158 (macOS)
- What: when `fn` raises, the `finally` runs `reclaim_mine` while the propagating exception's traceback still references fn's frame, whose locals (widgets, StringVars, the root) hold the tkapp, so `_try_free` sees refs above baseline and leaves it pinned. On Windows the caller is usually a per-click `_spawn` thread or the per-open `ccsync-work-window` thread; it exits moments later, after which no thread may ever free that interpreter (`_report_orphans`). On macOS the main thread is long-lived, so the next dialog reclaims it.
- Cost / failure scenario: about 1.8 MB (the module's own measured figure) per failed dialog build, never returned. The triggers are the ones the code already anticipates - a TclError from an RDP reconnect or a display change mid-build, a refresh timer on a torn-down root (comp-ui-6 2026-09-11) - so this is rare; on a machine that is RDP'd into daily it is a few MB a month, plus one WARNING with holder chains each time. It is the one realistic route by which the CR-93 pin grows without a code bug in the dialog itself.
- Evidence: probe_pin.py: identical fake dialog, return path -> 0 pinned after the thread exits; raise path -> 1 pinned on a dead thread, with the module's own "closed with its Tcl interpreter still referenced (5 refs, baseline 4)" warning.
- Ledger: related to CR-93 (fixed; this is a residual path, not a regression)
- Suggested change: in both places, catch `BaseException as exc`, call `traceback.clear_frames(exc.__traceback__)` (drops the finished frames' locals; the exception and its message survive), then `reclaim_mine`, then re-raise. Must not break: the pin-at-birth rule and the "free only on the building thread" rule are untouched; this only lets the existing reclaim succeed.
- Effort / risk: S effort; low risk

### comp-ui-4 - The menu fingerprint carries lane C's live byte and file counts, so the "only on real state changes" rebuild happens every tick while lane C uploads
- Category: perf
- Severity: low
- Confidence: PLAUSIBLE (fingerprint churn CONFIRMED; the macOS cost is estimated, not measured)
- Where: companion/src/ccsync_companion/tray.py:3942-3945 (`_menu_fingerprint` includes `str(s.detail)` raw); detail source sync/syncthing_lane.py:921-929 (`sending {n} file(s) ({size}) to the server`, `({owed} file(s) owed)`); consumer tray.py:5252-5255, and on macOS tray_native.py:1883-1889 -> `_apply_menu_now` -> `_build_nsmenu`
- What: the fingerprint was made coarse on purpose (progress in tenths, ytdl by clip, trash by GB) and then includes every lane's raw `detail`, which for lane C embeds counts that move as files go. Every changed count is a full `_build_menu`, and on macOS a full NSMenu rebuild on the main thread (the Tk-Aqua thread) with a fresh set of ObjC target objects.
- Cost / failure scenario: during a lane C upload the probe saw a distinct fingerprint on 300 of 300 ticks, i.e. a rebuild every 2 s (43,200 a day at worst) instead of on state changes. On Windows the rebuild is ~6 us and the assignment is free, so the cost there is nil. On macOS each rebuild is an NSMenu of ~13 rows plus ~10 PyObjC targets allocated and the old set released on the UI thread, estimated 1-3 ms per rebuild.
- Evidence: probe_snapshot.py (300 distinct fingerprints over 300 ticks with only the lane C count moving); code read of the fingerprint and the darwin `__setattr__` hook.
- Ledger: new
- Suggested change: put `re.sub(r"\d[\d.,]*", "#", detail)` (or the detail minus its parenthesised counts) in the fingerprint instead of the raw detail. The menu's Sync: line would then show counts as of the last structural change rather than the last tick; the tooltip already carries the live numbers, which is the split the fingerprint's own docstring describes.
- Effort / risk: S effort; low risk

### comp-ui-5 - The 2 s tray tick re-reads and re-parses site.json three times, and the pulse thread wakes 2.7 times a second with nothing to pulse
- Category: idle
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/tray.py:2962 (`_dashboard_url` -> `site.cached_site`), 2971-2975 (`youtube_enabled` called twice + `unblock_enabled`, each `site.feature_enabled` -> `cached_site()`, a full read + `json.loads` every call), 3002 (`_current_project_line` calls `app.lane_statuses()` a second time per tick, tray.py:2531); pulse loop tray.py:5276-5309 (`time.sleep(0.375)` forever)
- What: `site._brand_site` already memoises the manifest by (path, mtime) "because the tray asks on every status repaint", but `cached_site`/`feature_enabled` - what the tray actually calls - do not use it. Separately, the pulse thread polls a tuple every 375 ms even when the state is steady (most of the day), and the refresh loop polls at 4 Hz whenever the menu is open.
- Cost / failure scenario: 43,200 ticks a day x 5 small file opens (3 of them the same site.json) = 216,000 file opens and 130,000 JSON parses a day per machine, each passing through Defender's on-access scan; plus ~230,000 pulse-thread wakeups a day. Measured total snapshot cost is 0.33 ms per tick, so the CPU is small (~15 CPU-seconds a day); the case for fixing it is wakeups and disk I/O on a laptop beside Resolve, and that it is a one-line reuse of a cache that already exists.
- Evidence: probe_snapshot.py (`read_text` per snapshot: site.json x3, eula_accepted.json, ytdl-attestation.json; 0.317 ms per snapshot).
- Ledger: related to comp-app-4 (the whole `sync_guard()` rebuilt every 2 s); new for the site.json half
- Suggested change: route `feature_enabled()` with no `site` argument through `_brand_site()` (mtime-keyed, so a re-provisioned site is still picked up on the next tick), and pass the snapshot's own `statuses` into `_current_project_line`. Let the pulse loop wait on a `threading.Event` the refresh loop sets when `pulse_state` turns pulsing. Must not break: fail-closed feature reads (an unreadable or absent file is still False).
- Effort / risk: S effort; low risk

## What is already good
- Win32 handles: HICONs are cached per pre-rendered image (3 colours x 8 pulse levels, so at most 24 handles for the life of the process), both bitmaps are deleted right after `CreateIconIndirect`, the cache is emptied under a lock at teardown, and the HMENU exists only around `TrackPopupMenuEx` with `DestroyMenu` in a `finally`. No GDI or USER growth per icon update or per right-click was found on any path.
- The refresh loop assigns `icon.icon` / `icon.title` only on change, skips every write while the menu is open, and `icon.menu` is a free attribute rebind on Windows. Leave the model alone.
- `theme` caches the tinted window mark as base64 text, not as a `PhotoImage`, so no Tk object outlives its interpreter through a cache; every PhotoImage is parked on its own root and popped by `release_root`.
- Every `after` loop found (PopupDialog, ProgressWindow, WorkProgressWindow, Settings) checks a closed flag or a `None` root first and is cancelled or ends on destroy; the Settings window skips a re-render when its signature is unchanged.
- Bounded queues: the pre-registration toast deque (`maxlen=5`), the Explorer re-add timer (one attempt a minute), `crash_summary`'s TTL and the stand-in ledger's (mtime, size) stamp keep the 2 s path off the disk for those sections.

## Coverage note
Not covered: the individual tray dialogs (sign-in, credentials, update, typed confirmation, scripting warning) were checked only for Tk-root and `after` patterns, not read line by line; PopupDialog has no row cap (about 5 widgets per out-of-tree clip in one scrolling frame) but its build cost could not be measured without opening a real Tk window, so it is not filed; the macOS PyObjC side was read, not run. The staging walk on the 2 s tray path is real and measured here too (28.5 ms at 2,000 files, 159 ms at 8,000; the Settings window, while open, runs a second full `_tray_snapshot` every 2 s and so doubles it) but is already filed as comp-app-1.

## OUT OF TERRITORY
- companion/src/ccsync_companion/ledger_mirror.py:172-181: `_connect()` runs `mkdir` + `PRAGMA journal_mode=WAL` + `executescript(SCHEMA)` on EVERY connection (every `where`, `status`, `volumes_holding`); one schema pass per process would do.
- companion/src/ccsync_companion/app.py:7749 / broll_ingest.py:3839: staging walk every 2 s, see comp-app-1 (corroborating timings above).
- companion/src/ccsync_companion/field_service.py:470: the verdict cache stamp formats `sorted(self.store.kinds().items())`, and `kinds()` reads and parses `field-state.json` from disk on every `state()` poll per card.
