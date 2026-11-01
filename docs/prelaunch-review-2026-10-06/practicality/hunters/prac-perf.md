# Pre-launch practicality pass - prac-perf (performance a user feels)

2026-10-06, working tree on 08b40eb. Read-only except this file.

**What was covered, and how.**

- **Dashboard pages with a realistic fleet.** I seeded a throwaway dashboard DB: 10 editors x 2 computers x 10 ticked projects, 1,500 originals + 1,500 proxies per project, 90 % held per machine. That is 90k `nas_media` rows and 540k `editor_media` rows. I timed every home-page poll through `TestClient` as an admin on this desktop (a 24-thread Windows box, so faster than the NAS). Scripts were in the scratchpad (`probe_pages.py`, `probe_backlog.py`).
- **The companion's idle cost.** I measured the LIVE base-rig companion (0.9.84, pid 73072) read-only: per-thread CPU deltas, a 25 s `py-spy record --nonblocking` sample, its loaded modules and its memory. I also probed the `onnxruntime` import cost in the companion venv.
- **Startup.** I measured the `_MEI*` extractions in %TEMP% and read the startup log.
- **Tray right-click path** (`tray.py` `_tray_snapshot` / `start_tray`, `tray_native._show_menu`).
- **Watcher / Resolve probes** (`resolve_prefs.resolve_process_state`, `resolve_bridge` probe cache).
- **Music text-encoder cold load**, measured at 0.74 s plus 10 ms per query, so it is fine and not reported. **B-roll search** (FTS + optional fastembed) was read.

**What I did NOT do.**

- No timing on the NAS itself (no NAS access by rule), so server numbers are from a faster CPU.
- No sync-throughput measurement (rclone flags have been benchmarked already: `bench/`, CR-347).
- Not a cold-Defender startup of the frozen exe on an editor laptop.
- No popup (Tk) open latency.
- No measurement of a Cards episode open.

The probe's `create_app` opened the in-repo dev `music/web/data/music.db` read-side, which touched its WAL/shm files. That file is gitignored and its content was unchanged.

---

### prac-perf-1 - The admin transfers page downloads ~2 MB of uncompressed HTML every 2 seconds per open tab

- **Severity:** high
- **Confidence:** CONFIRMED (measured)
- **Where:**
  - `dashboard/templates/transfers.html:30-35` (`hx-get="/partials/transfers"`, `every 2s`, `hx-swap="none"` + `hx-select-oob`)
  - `dashboard/src/ccsync_dashboard/ui.py:1793-1801`
  - `dashboard/src/ccsync_dashboard/app.py` (no `GZipMiddleware` anywhere)
  - `db.fetch_sync_backlog(files_per_group=50)` (`db.py:11098`)
- **What:** The /transfers poll re-renders the WHOLE page partial: live list, queued list with up to 50 file names per (editor, machine, project) group, and history. The browser then keeps only six fragments with `hx-select-oob`. Nothing is compressed: the app has no GZip middleware, and Tailscale Serve/Funnel does not compress either.
  - Measured with the seeded fleet: `/partials/transfers` was **2,006,961 bytes** and `/transfers` 2,020,553 bytes. The home page is 103 KB.
  - Two seconds later the same 2 MB comes again, almost always unchanged: its inputs (the manifest diff) refresh every 5-15 min.
- **Scenario:** A new customer onboards ten editors. Everyone's first week is "everything is owed", which is exactly when the admin keeps /transfers open to watch.
  - Each open tab pulls ~1 MB/s over the tailnet. On a phone, or a DERP-relayed laptop, that is the whole link. Lane B downloads for that same person compete with their own dashboard.
  - The browser re-parses 2 MB of HTML every 2 s.
- **Recommendation:**
  1. Add `GZipMiddleware(minimum_size=1024)` (repetitive HTML compresses ~10-20x).
  2. Split the poll. Live rows every 2 s, from `fetch_active_transfers` only. Queued and history on their own 30 s poll, or only when an ETag/`max(reported_at)` changes. A 304 or an empty swap when nothing changed is fine.
  3. Cap the file-name lists in the poll response: names on expand, not on every tick.
- **Known:** not in KNOWN_BUGS (grep: gzip / transfers payload).

### prac-perf-2 - Every home-page poll recomputes the whole fleet's file-level backlog (0.4 s each) even when it shows none of it

- **Severity:** medium
- **Confidence:** CONFIRMED (measured)
- **Where:**
  - `dashboard/src/ccsync_dashboard/ui_home.py:423-433` (`/partials/home-transfers`, every 2 s)
  - `ui_home.py:436-443` (`/partials/home-queue`, every 10 s, calls `build_transfers_view` only to feed `safe_to_close`)
  - `api.py:1044` (the fleet grid, every 15 s, calls `fetch_sync_backlog` for the WHOLE fleet even on an editor-scoped view)
  - `ui.py:914`, `ui_home.py:141` (page loads)
  - `api.py:611-667` `build_transfers_view` → `db.fetch_sync_backlog`
- **What:** `build_transfers_view` runs `fetch_sync_backlog`: ~600 anti-join queries, two per ticked (editor, machine, project) pair, plus a Python pass over every owed original. Each of the polls above calls it.
  - Seeded fleet, admin scope: `build_transfers_view` **0.41-0.44 s**, all of it in `fetch_sync_backlog`. An editor scope takes 0.04-0.06 s.
  - HTTP timings: `/partials/home-transfers` **370 ms to return 105 bytes** ("nothing is moving"). `/partials/fleet` **367 ms** (62 KB). `/` **796 ms**.
  - On the NAS CPU this is slower, and it shares the process with the Cards engines and the report writers (CR-351's contention story).
- **Scenario:** One admin with the home page open costs ~0.2 s of server CPU per second, 20 % of a core, to redraw a "nothing moving" window, and each additional admin tab adds the same again. During onboarding, when the backlog is biggest, the dashboard is slowest for every editor's report.
- **Recommendation:**
  - Cache the backlog per editor scope, keyed on its inputs: `max(editor_media_project.reported_at)`, the NAS inventory generation, and the selections/plan version. Recompute only when one moves.
  - Better: compute it in the collector once per cycle and store the result.
  - Make `/partials/home-transfers` read only `active_transfers` + the lane C rows.
  - Make the fleet grid's owed-count use the scoped editor.
- **Known:** CR-351 fixed the write-lock side of dashboard CPU contention. This read-side cost is not recorded.

### prac-perf-3 - A wired/base computer walks the entire NAS project tree over SMB every 5 minutes, even with sync switched off

- **Severity:** medium
- **Confidence:** CONFIRMED (live sample + code)
- **Where:**
  - `companion/src/ccsync_companion/app.py:2037-2042` and `:10175-10178` (ManifestCache built and started unconditionally)
  - `manifest.py:170-210` (`os.walk` + `os.path.getsize` per video file), `manifest.py:368-372` (300 s loop)
  - `proxy_scan.py:401` / `fixer.py:435` (the proxy-gap walk every ~16 min)
- **What:** `ManifestCache` starts on every machine regardless of `mode` or `sync_enabled`. On a wired machine (and the base rig), `local_root` is the NAS share (`P:\`), so the "local disk manifest" is a full SMB walk of up to 64 projects.
  - Every video file gets a second stat (`getsize`). On Windows `os.scandir`'s `DirEntry.stat()` already carries the size for free.
  - The dashboard already holds the NAS inventory from its own walk, and `fetch_sync_backlog` excludes `mode='base'` rows, so the result is largely redundant.
  - The proxy-gap scan walks the same tree again every ~16 min.
- **Live evidence:** the base rig runs with `sync_enabled=false`, `local_root = "P:\\"` and syncs nothing. Its companion used **6,291 CPU-seconds in 14 h**, ~12.5 % of a core around the clock, and 29 % during a 30 s sample.
  - A 25 s py-spy sample: **209 of 315 active samples (66 %) were in `ManifestCache._loop → scan_local_manifest`**, mostly `getsize` and `os.walk`. 7 more were in the proxy-gap walk.
  - The log shows the proxy-gap pass every ~16 minutes all night (`ccsync.proxy_gen: proxy gap: ...`).
- **Scenario:** A customer with eight wired edit bays in one studio has eight companions stat-walking the whole NAS tree every few minutes, all day. That is NAS metadata load and SMB chatter while editors scrub 4K over the same share. On each bay it is a constant background CPU slice beside Resolve.
- **Recommendation:**
  - Do not start ManifestCache, or make it report rollups only from the dashboard's inventory, on machines whose effective mode is wired/base or whose `sync_enabled` is false.
  - Everywhere else, switch the walk to `os.scandir` recursion using `entry.stat()`, and skip unchanged directories by mtime as the server's `tree_sig` does.
  - Give the proxy-gap scan the same mode gate, or make it event-driven from the watcher.
- **Known:** not recorded (KNOWN_BUGS mentions the manifest walk only for conflicts, line ~3609).

### prac-perf-4 - The Timeline Cards agent polls the script-server probe at 10 Hz whenever Resolve is not connectable, a full process snapshot four times a second

- **Severity:** medium
- **Confidence:** CONFIRMED (live sample + code)
- **Where:**
  - `E:\Projects\Editing\Resolve\MulticamPipeline\multicam_pipeline\cards\resolve_engine.py:3396-3420` (`_sweep_loop`: `if not self._ready(): ... time.sleep(POLL_FAST)`), `cards/config.py:80` (`POLL_FAST = 0.1`)
  - `companion/src/ccsync_companion/timeline_cards_bridge.py:174-182`
  - `script_server.py:319-357` (`state()` cached only 250 ms; each miss runs `_windows_tcp_rows()` + `_windows_processes()`, which is CreateToolhelp32Snapshot plus a Python loop decoding every process name)
- **What:** While Resolve is closed, launching, or has a dead scripting server (the base rig's log shows the last of these on 2026-10-06), the engine retries at 10 Hz. The 250 ms cache turns that into ~4 full TCP-table + process-table scans per second, indefinitely.
  - py-spy on the live companion: **77 of 315 active samples (~25 %)** were in `_sweep_loop → bridge.ready → script_server._windows_processes`.
- **Scenario:** An editor's machine with `cards_agent` on and Resolve closed burns several percent of a core all day. A laptop on battery never idles the CPU. With Resolve open but its scripting server dead, it does the same next to Resolve.
- **Recommendation:** Back off when `ready()` is false: 1 s, growing to 5 s, reset the moment the state changes. A connection is never wanted faster than a human can open Resolve. Alternatively, have the bridge rate-limit `ready()` itself (answer from a 1 s cache) so no engine can drive the probe harder. The CR-68 guard is unaffected: a stale "not ready" only delays a connect.
- **Known:** not recorded. The bridge contract is plan §7c.1; `cards_agent` is OFF in the vendor build, so this hits only customers who turn it on.

### prac-perf-5 - Asking "is onnxruntime installed?" commits ~740 MB in every companion that asks (OpenBLAS per-thread buffers)

- **Severity:** medium
- **Confidence:** CONFIRMED (probe + live process)
- **Where:**
  - `companion/src/ccsync_companion/music_clap_sidecar.py:342-353` (`runtime_available()` does `import onnxruntime`), called from `refresh()` :380, `refusal()` :1061, `ensure()` :481
  - Callers: `music_ingest.py:135,145` (ingest tick) and `broll_server.py:1900` (the loopback capability route)
- **What:** An availability check imports onnxruntime, which imports numpy and its bundled OpenBLAS. OpenBLAS reserves buffers per core at import.
  - Measured in the companion venv on this 24-thread machine: `import onnxruntime` takes the process from 6 MB to **768 MB private (committed)**, while the working set grows only to 49 MB.
  - With `OPENBLAS_NUM_THREADS=1` the same import commits **29 MB**.
  - The live base-rig companion has `onnxruntime_pybind11_state.pyd` and `libscipy_openblas64_*.dll` loaded and shows **832 MB private / 125 MB working set**.
- **Scenario:** An editor's 16-32 GB workstation runs Resolve, which is commit-hungry with large GPU/host buffers, and Task Manager's "Committed" column shows the CC Sync companion at ~800 MB. That is the first thing a customer's IT person or a performance-minded editor will blame when Resolve stutters, and it costs real commit charge. It is spent to answer a yes/no question for a music-indexing feature most machines never use.
- **Recommendation:**
  - Answer availability with `importlib.util.find_spec("onnxruntime")`, as `broll/web/app/semantic.py:encoder_installed()` already does for fastembed. Import onnxruntime only when actually embedding.
  - Set `OPENBLAS_NUM_THREADS=1` (and `OMP_NUM_THREADS`) in `launcher.py` before anything can import numpy. The companion never does BLAS-heavy work on the tray process.
- **Known:** not recorded.

### prac-perf-6 - The frozen companion is a 54 MB one-file exe: every start writes 2 x 116 MB to %TEMP%, and it restarts itself whenever Resolve quits

- **Severity:** medium
- **Confidence:** CONFIRMED (measured on this machine). The added startup latency on an AV-scanned editor laptop is PLAUSIBLE (not measured).
- **Where:**
  - `companion/build.spec:257-298` (`EXE(...)` with binaries/datas inlined: onefile)
  - `supervisor.py` (the same exe re-entered with `--supervise`)
  - `app.py` ("the Resolve this companion was connected to has exited -- restarting the companion")
- **What:**
  - Every start runs the bootloader, which unpacks the archive to `%TEMP%\_MEIxxxx`. Measured: **116 MB per extraction**, including onnxruntime, numpy/OpenBLAS and Tcl/Tk.
  - The supervisor is the same onefile exe, so it extracts a second 116 MB copy and runs two more processes (bootloader + child) just to wait on a process handle. Four `ccsync-companion.exe` processes are running on this rig.
  - The companion deliberately restarts itself whenever the Resolve it was connected to exits. In the base rig's last two logs, **24 of 55 starts** were that restart.
  - So every "quit Resolve" costs ~232 MB of fresh DLLs written to disk, a real-time AV scan of all of it, and a cold Python start before the tray is back.
  - 40 leftover `_MEI*` directories sit in this machine's %TEMP% from killed instances (empty now, but they accumulate).
- **Scenario:** On an editor laptop with Defender or a corporate EDR, each start can take several seconds of disk and CPU, right when the editor has just closed Resolve or logged in. A customer's IT department sees an unsigned exe unpacking DLLs into %TEMP% several times a day, the classic packer/dropper heuristic, and may quarantine it.
- **Recommendation:**
  - Ship onedir into `%LOCALAPPDATA%\ccsync\bin\<version>\` and point the Run key at a stable shim. Upgrades then swap a directory (the upgrader already renames; it would rename a folder). Starts become a cold Python import with no extraction, and the supervisor costs ~10 MB instead of a second unpack.
  - If onedir is too large a change before launch, at least make the supervisor a tiny separate stub, and reconsider the restart-on-Resolve-exit, for example by reconnecting the bridge in-process after a clean disconnect.
- **Known:** CR-93/supervisor entries describe the mechanism but not the cost. Not recorded as a defect.

### prac-perf-7 - Opening a Cards episode runs seconds of pure Python inside the dashboard process that serves everyone else

- **Severity:** medium
- **Confidence:** PLAUSIBLE (from CR-351's own live measurements; not re-measured here)
- **Where:** `dashboard/src/ccsync_dashboard/cards.py`, `cards_pool.py` (engines in-process, `a2wsgi` threads); KNOWN_BUGS CR-351 "The CPU was Timeline Cards".
- **What:** CR-351 measured opening an episode at 4.6 s CPU of token loading, and 5-10 s at up to 80 % of a core live, plus ~1.6 s after each edit. All of it runs in the uvicorn process that also serves every page poll above and every companion's `/api/v1/report`. The bulk-insert fix stopped this stretching the write lock, but the CPU and GIL are still shared.
- **Scenario:** A customer with two people in Cards (the pool's default cap is 2) and ten editors with the dashboard open. Every episode open or edit makes every other page and every report reply slow for seconds. Add prac-perf-2's 0.4 s backlog recomputes and the NAS's slower CPU, and the dashboard feels sluggish exactly when the studio is busiest.
- **Recommendation:** Before selling Cards, measure page p95 latency on the NAS while an episode opens. If it stalls, take CR-351's own "next step": run each Cards engine in its own process (the pool already owns its lifecycle), so its CPU cannot take the dashboard's GIL.
- **Known:** CR-351 (FIXED for the lock; the CPU half is explicitly left open: "moving the engine into its own process is the next step only if pages still stall").
