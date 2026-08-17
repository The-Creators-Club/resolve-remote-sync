# Known bugs (original 2026-08 hunt worklist, archived)

> **Archive.** Kept as history; the addresses, hostnames and people in it are
> those of the original deployment. Do not copy commands out of it.

> Archived verbatim on 2026-08-03 when the fix fleet completed; see `KNOWN_BUGS.md`
> for resolution status. Line numbers reflect the tree as of commit 38066ba plus the
> then-uncommitted b-roll diff.

Findings from a six-agent bug hunt (companion core, companion sync engine, dashboard,
server/onboarding/installers, cross-component contracts, and the pending b-roll diff).
Each entry is self-contained: file:line, the defect, a concrete failure scenario, and a
fix hint. Nothing here has been fixed yet — this is a worklist.

**Confidence markers:**
- `[confirmed x2]` / `[confirmed x3]` — this many independent agents found it separately.
- `[verified]` — an agent reproduced it by running code, not just reading it.
- Line numbers were accurate at the time of the hunt; re-check before editing.

**Recurring theme worth reading first:** several of these bugs are *masked by tests that
assert the wrong thing* (B10, B4, B18, B14). Those false-greens are why the bugs shipped.
Fixing the test is part of fixing the bug.

---

## 0. The b-roll diff is not shippable as-is (uncommitted working tree)

The in-flight b-roll mount feature spans dashboard (`app.py`, `settings.py`, `ui.py`,
`base.html`, `compose.yaml`, `run.sh`, `requirements.txt`, `pyproject.toml`,
`test_hardening.py`), server (`common.py`, `install_dashboard_app.py`), and two new files
(`dashboard/src/ccsync_dashboard/broll.py`, `dashboard/tests/test_broll_mount.py`). The
b-roll *application* itself lives in a separate repo: `E:/Projects/broll-platform/web`.

It has four critical/major defects, three multiply-confirmed, and it is **enabled by
default**. Do not commit this diff until B1–B4 are resolved, or hold the feature and revert
`broll_enabled`'s default to off (`settings.py`, `install_dashboard_app.py:607`).

### B1. `broll-web` is created and mounted but nothing ever puts code in it — CRITICAL [confirmed x3]
- **Where:** `server/install_dashboard_app.py:447` (mkdir), `:460-461` (chown/chmod), `:217` (volume), `:607` (`broll_enabled` default `"1"`); upload path at `:230-236,264-292`.
- **Defect:** the script mkdirs `<root>/broll-web`, bind-mounts it read-only at `/broll-app`, and puts it on `PYTHONPATH`, but `upload_tree()` / `iter_local_files()` only ship this repo's `dashboard/` tree into `<root>/app`. No step, script, or doc copies `broll-platform/web/` into `broll-web`.
- **Failure:** clean `install_dashboard_app.py` run → `/broll-app` is empty → `from app.main import app` raises `ModuleNotFoundError` → `broll.mount_broll` swallows it (`broll.py:45-48`) → `app.state.broll_mounted=False` → nav link hidden → operator sees a green healthcheck and a silently-missing feature, warning buried in container logs.
- **Fix hint:** add a deploy step that ships the `broll-platform/web` checkout into `broll-web` (rsync/SFTP), or vendor it, and fail loudly if the source is absent while `broll_enabled=1`.

### B2. The install script prepares the wrong data directory — CRITICAL [confirmed x3]
- **Where:** `server/install_dashboard_app.py:448,462-463` (creates/chowns `<root>/broll-data`, `3000:3000`, `770`) vs `:221` (mounts `DEFAULT_BROLL_ARCHIVE_ROOT`); `server/common.py:46`.
- **Defect:** the prepared `<root>/broll-data` is never mounted. The path that *is* mounted — `/mnt/tank/TheCreatorsPool/Creators_Club/Assets/B-roll Archive` — is never created and never chowned. `setup_tree.py` only manages `Projects/`.
- **Failure:** if the archive path doesn't exist, Docker auto-creates the bind source `root:root 0755`; container runs as `3000:3001`; `_init_broll_storage` (`broll.py:74-82`) fails `mkdir`/`ensure_schema` with `PermissionError`; `broll.py:52-55` swallows it and mounts anyway; nav shows the link and every `/broll` request 500s with "unable to open database file." Separately, `770 root-group` is the wrong posture for that tree — it is the SMB-visible archive editors browse as `P:\Assets\B-roll Archive`, and would lock them out.
- **Fix hint:** create + chown the *mounted* path; do not `chmod 770` a share editors need; consider that the dataset is `aclmode=restricted` (NFSv4 ACLs) so a plain chmod may not behave as expected — confirm on the NAS.

### B3. `BROLL_INGEST_TOKEN` opens an under-authenticated write path — two ways in — CRITICAL [confirmed x3, one verified]
- **Where:** `dashboard/deploy/compose.yaml:55` (ships `"REPLACE_ME"`); `dashboard/src/ccsync_dashboard/app.py:103-117,136` (carve-out logic); `server/install_dashboard_app.py:612` (defaults `""`); upstream guard `broll-platform/web/app/routes_ingest.py:20-25`.
- **Defect A (checked-in live credential):** unlike other `REPLACE_ME` values that fail loudly, `BROLL_INGEST_TOKEN: "REPLACE_ME"` *works* if left alone — `_broll_ingest_token_ok` sees a non-empty expected value and opens `/broll/api/ingest/*` to anyone presenting `X-Ingest-Token: REPLACE_ME`, a value in the public repo.
- **Defect B (blank = session-open) [verified]:** the installer default is blank (`""`). With a blank token, the dashboard carve-out stays closed to the unauthenticated, but the b-roll sub-app's *own* guard flips to dev-mode-open, so **every logged-in editor** (or a stolen session cookie) can `POST /broll/api/ingest/{video,index,moved,shares}`. Verified with a live `200` from a plain non-admin session: `SESSION-ONLY ingest/shares -> 200 {"ok":true,"shares":1}`.
- **Failure:** repoint every clip's archive path via `/ingest/shares`, or flood `/ingest/video` to bloat `broll.db` (no b-roll body-size cap applies).
- **Fix hint:** require a strong non-placeholder token when `broll_enabled=1` and refuse to start otherwise; make the sub-app's None-token dev mode unreachable in this deployment; the `compose.yaml` header at `:6` still says "fill in the two REPLACE_ME values" — there are now five.

### B4. The b-roll tests only run on one workstation — MAJOR [confirmed x2]
- **Where:** `dashboard/tests/test_broll_mount.py:21-23` (`BROLL_WEB = Path(r"E:/Projects/broll-platform/web")`), `:27-32` (sys.path leak), `:73-81`, `:85`, `:98-107`.
- **Defect:** 6 of 8 tests are gated on a hardcoded developer-machine path, including *all* auth tests. On CI/NAS/any other machine they skip silently (pytest exits 0). Two "passing" tests would pass even with the mount entirely absent — the 401/303 they assert comes from `login_gate`, not the mount. No test ever authenticates and renders a b-roll page. `broll_env` also does `sys.path.insert(0, ...)` without cleanup, polluting the session.
- **Fix hint:** provide a lightweight fake `app.main` module for tests instead of a real checkout; assert `broll_mounted is True` explicitly; add one test that logs in and GETs a page through the mount.

### B-roll minors
- **numpy/rapidfuzz make the next boot depend on PyPI** — `requirements.txt:17-18` + `run.sh:36-44` md5-stamps requirements and pip-installs on change under `set -e`; a network blip crash-loops the *whole* dashboard, defeating the "a broken b-roll checkout must leave the fleet dashboard functional" design in `broll.py:16-18`. (`bench` finding parity: the deps are genuinely needed and import-guarded upstream, so the risk is purely the boot-time pip step.)
- **`/broll/docs` + `/broll/openapi.json` exposed to every editor** — mounting a second `FastAPI()` brings default docs routes; both return 200 for a plain session. Set `docs_url=None` upstream.
- **Failed storage init still reports mount success** — `broll.py:50-59` falls through to `app.mount(...); return True` after logging the failure; `ui.py:92` then advertises a link to an app that 500s on every request. Return `False`/tri-state.
- **Orphaned comment block** — `settings.py:56-68`: `broll_enabled` was inserted between the `packages_dir` explanation and `packages_dir` itself, so the packages comment now describes the wrong field and `packages_dir` is undocumented.
- **No drift test on `volumes:`** — `server/tests/test_safety.py:621` compares env *keys* only; there is no equivalent for the volume list, which is exactly where B1/B2 live. `compose.yaml:104,112` vs `install_dashboard_app.py:217,221` are unverified.
- **`umask 077` on the b-roll data root** — `run.sh:50` + `broll.py:74-81` create `proxies/`, `sprites/`, `posters/`, `sheets/`, `broll.db` mode `0700`/`0600` owned by uid 3000; if editors browse this over SMB they may be locked out. Confirm against the NFSv4 ACL behaviour on the NAS.

---

## 1. Critical — data-loss / silent-failure in the shipping product

### B5. Failed `set_ignores` is swallowed, then the Syncthing folder is unpaused anyway — CRITICAL
- **Where:** `companion/src/ccsync_companion/sync/sequencer.py:981-995` (swallow), `:970` (unpause).
- **Defect:** `_reassert_folder_policy()` catches every non-404 exception from `admin.set_ignores()` with a bare `log.exception` and returns normally; `_lane_c_turn` can't tell it failed and unpauses a `sendreceive` folder whose `.stignore` is not known to be in place. This is the exact state `syncthing_admin.py:233-265` goes out of its way to prevent on the accept path.
- **Failure:** a config write exceeds `config_write_timeout` (the codebase documents these routinely outlast the read timeout — that's why `config_write_timeout=30` exists) → exception logged and discarded → folder unpaused → lane C indexes and offers every `.braw`/`.mov` original and the whole `Proxy/` tree bidirectionally, duplicating lanes A/B and propagating any local video delete to the NAS and every editor. Window lasts up to a full rotation (600s x N projects). No test covers this path.
- **Fix hint:** propagate the failure so the caller leaves the folder paused (mirror the accept-path guarantee); add a test with a `set_ignores` that raises.

### B6. A 65th project silently drops a machine off the fleet grid — CRITICAL
- **Where:** dashboard cap `dashboard/src/ccsync_dashboard/api.py:1880` (`MAX_REPORT_PROJECTS=64`), `:1955` (`queue max_length=64`), `:1986-1991`; companion has no cap: `manifest.py:57-115` emits one key per project dir (only caps `MAX_PER_FILE_ENTRIES=2000` *within* a project), fed unfiltered at `reporter.py:248-251` from `app.py:383`.
- **Defect:** the dashboard hard-caps `local_manifest`/`media_tree`/`queue` at 64; the companion enumerates every marker-bearing dir under `local_root/Projects` with no cap.
- **Failure:** the 65th project makes every HEAVY report a pydantic 422 — which fires *before* the route body, so lane status, transfers, machine_state, presence, and the upgrade advertisement are all lost too. An idle machine only ever sends heavy ticks (`reporter.py:350-352`), so it disappears from the grid entirely with one WARNING then DEBUG forever. **Worst-placed is the base rig** — its `local_root` is the whole NAS tree at `P:\`, so it hits 64 first and holds the authoritative copy of everything. Lower-trigger variant: `MAX_REPORT_BODY_BYTES=8MB` (`app.py:37`) vs a payload with no total-size guard (64 x 2 lists x 2000 entries exceeds 8MB → 413).
- **Fix hint:** cap/paginate on the companion side and degrade gracefully server-side (accept and truncate, or split heavy sections) rather than 422-ing the whole report.

### B7. Bootstrap hard-abort reported to the editor as a successful install — CRITICAL
- **Where:** `onboarding/onboard.py:562`.
- **Defect:** `if exit_code != 0 and not capability_problems:` treats a non-zero exit as *either* a hard failure *or* a capability miss — but it can be both, and any capability warning suppresses the failure branch.
- **Failure:** `windows_bootstrap.ps1` runs under `$ErrorActionPreference="Stop"`; `Add-CapabilityMiss "rclone is NOT installed"` fires (`:558`); the P:-mapping block then hits a terminating error and exits 1 — before the companion install and before the capability-summary `exit 3` (`:1584`). onboard.py sees exit 1 + non-empty `capability_problems`, skips `_install_failed()`, and tells the editor "Everything else installed fine" while P: was unmapped and never recreated and the companion was never installed. The signal that distinguishes the cases (exit 1 vs exit 3) is discarded.
- **Fix hint:** distinguish exit 3 (capability summary) from other non-zero exits; only suppress the failure branch for exit 3.

---

## 2. Major — companion runtime

### B8. Every shutdown-guard / keep-awake log line is silently discarded — MAJOR [verified]
- **Where:** `companion/src/ccsync_companion/shutdown_guard.py:58`.
- **Defect:** it is the only module using `logging.getLogger(__name__)` (→ `ccsync_companion.shutdown_guard`); every other module uses `"ccsync.<x>"`, and `setup_logging()` only attaches handlers to `"ccsync"`. Records propagate to the unconfigured root logger.
- **Failure:** in the windowed PyInstaller build (`console=False`, `build.spec:99`), stderr is `None`, so WARNING+ hit `logging.lastResort` → `Handler.handleError` returns silently and INFO/DEBUG vanish outright. The two most recently-added features (shutdown warning, keep-awake) are undiagnosable from `~/.ccsync/companion.log` or tray → Copy diagnostics. Reproduced.
- **Fix hint:** one-line fix — use `logging.getLogger("ccsync.shutdown_guard")`.

### B9. "Busy" has no liveness bound — a disconnected NAS keeps a PC awake and un-shutdownable forever — MAJOR
- **Where:** `shutdown_guard.py:113-155` (`describe_pending`), `sync/syncthing_lane.py:497-509` (`check_once`), `app.py:2163` (`_shutdown_block_reason`), `:521` (keep-awake flags).
- **Defect:** a lane counts as busy on `state==STATE_SYNCING` or `queued>0`, with no staleness timestamp and no check that data is moving; `SyncthingLane` sets `STATE_SYNCING` purely from `needTotalItems`/outgoing `needItems`, independent of peer connectivity.
- **Failure:** Tailscale drops / NAS off overnight with 4 unreceived files → lane C reports `syncing` indefinitely → `_shutdown_block_reason()` never returns None → `ES_CONTINUOUS|ES_SYSTEM_REQUIRED` held permanently (PC never sleeps until companion restart) and every shutdown/restart/logoff is interrupted by "still syncing" with zero bytes in flight. Contradicts the module's own "only while actually transferring" promise (`config.py:212-214`) and its "a guard that cries wolf gets ignored on the night it is right" rationale. Same shape for lane A/B if rclone wedges in SFTP retries. No test covers it.
- **Fix hint:** require peer-connected + progress-within-N-seconds before counting a lane as blocking; add a max-hold ceiling.

### B10. Pause→Resume starts sync lanes with nobody signed in — MAJOR [verified]
- **Where:** `app.py:2044-2059` (`toggle_pause`) → `app.py:1564-1626` (`_start_lanes`); gates at `:2073` (`start`) and `:1686` (`on_signed_in`).
- **Defect:** `start()` and `on_signed_in()` both gate `_start_lanes()` on `self._require_login and not self.identity.valid()`; the legacy-mode branch of `toggle_pause` calls `_start_lanes()` directly with no such gate.
- **Failure:** legacy (blank `dashboard_url`) machine, `require_login=true`, never signed in → `start()` correctly leaves lanes down → editor clicks ⏸ then ▶ → lanes sync under an unverified identity and `_lanes_started=True`. Same path after token expiry (`_identity_watch_loop` sets `_lanes_started=False`, `:2218`). **The existing test enshrines the bug:** `test_app.py:785-809` asserts `"lane_a_video_up" in started` after resume. Confirmed it passes.
- **Fix hint:** apply the same login gate in `toggle_pause`'s resume path; fix the test to assert lanes stay down when unsigned.

### B11. Two paths spawn a second concurrent Tk root — MAJOR
- **Where:** `app.py:1939-1963` (`copy_diagnostics`, takes no lock); `app.py:989-993,1001,1023` (consolidate drops `_popup_active_lock` then opens `tk.Tk()` via `popup.ProgressWindow`).
- **Defect:** every other `tk.Tk()` site takes `_popup_active_lock`; these two don't. A watcher popup on a sibling thread can then acquire the free lock and open a second root.
- **Failure:** the "another Tk root has run on a sibling thread" condition the lock exists to prevent (AUDIT_2 CORE-M3/H8, cited at `popup.py:578-586`, `tray.py:362-364`) → wedged/raising Tcl interpreter → for `PopupDialog`, the batch is auto-ignored and clips are never re-offered this session. `copy_diagnostics` also bypasses `apply_upgrade`'s `if self._popup_active_lock.locked()` guard (`app.py:1742`), so a self-upgrade can swap the exe while a Tk root is live.
- **Fix hint:** take `_popup_active_lock` around `copy_diagnostics`; for consolidate, hold the lock around the Tk window creation even if released during the long copy.

### Companion-runtime minors
- **B8-adjacent: guard window class outlives its WNDPROC** — `shutdown_guard.py:404-427,284-304`: `RegisterClassW` registers process-wide with `self._wndproc_ref`; `stop()` never clears it and `UnregisterClassW` is never called. Only hit by tests that build/start/stop/drop a guard (`test_shutdown_guard.py:264,277`) — a second guard's `CreateWindowExW` dispatches `WM_NCCREATE` into freed ctypes memory. Non-deterministic.
- **Dead pump = permanently un-restartable guard** — `shutdown_guard.py:266-283,429-444`: on any `_pump` failure the `finally` sets `_hwnd=None` but leaves `_thread` non-None, so `start()` early-returns forever and `active` mis-reports `False`. Combined with B8, the `log.exception` explaining it never lands.
- **Popup-queue race strands a batch** — `app.py:706-728,654-681`: a thread finishing its last dialog can leave a just-queued batch unpopped until some unrelated future popup closes; the `snooze=True` stamp (`:709-712`) suppresses the clips 300s then re-fires them as a fresh batch, leaving the original entry permanently in `_popup_queue_keys`.
- **"not signed in (nothing syncs)" shown when login isn't required** — `tray.py:908-909,1027-1028`: `_tooltip_text` and `identity_items` lack the `_require_login` check that `compute_overall_color` has (`:84`); with `require_login=false` and lanes running, the tooltip and menu wrongly tell the editor nothing syncs.
- **`shutdown()` has no re-entrancy guard** — `app.py:2227-2266` + `tray.py:972-974`: `on_quit` calls `shutdown()` then `run()`'s `finally` calls it again, racing two `_stop_lanes()`/`reporter.stop()` sequences (incl. `RcloneLane.stop`'s `self._observer=None` racing itself, `rclone_lane.py:1498-1504`).
- **Batch progress counts bytes never copied** — `popup.py:489`: `batch_done += file_total` runs even on aborted/failed fixes, inflating the bar, the "X of Y done" text, and `RateEstimator` speed/ETA.
- **Main fixer popup lacks the app icon** — `popup.py:588-590`: `PopupDialog._build` never calls `theme.apply_window_icon`, unlike every other root; the most-seen dialog shows the default Tk feather.
- **`upgrade.py:236-237` `size_bytes` parsed and unused** — neither the free-space check (`:437-443`, flat 200MB margin) nor the post-write `MAX_DOWNLOAD_BYTES` ceiling (`:461`) consults it.
- **`config.example.toml` drift** — `lane_b_enabled`, `sync_enabled`, `server_p_unc` are in `DEFAULTS`/`DEFAULT_TOML_TEXT` but absent from `config.example.toml`; `test_config.py:119-145` only checks the first two against each other.

---

## 3. Major — sync engine data integrity

### B12. Orphaned rclone `.partial` files are invisible to every `.stignore` builder — MAJOR
- **Where:** `sync/rclone_lane.py:563-566,581-645`; ignore builders `server/common.py:95-108`, `dashboard/src/ccsync_dashboard/provision.py:60-65`, `sync/syncthing_admin.py:50-59`.
- **Defect:** lane A uses rclone default `--inplace=false`, writing `<name>.<token>.partial` into the NAS project dir (also a `sendreceive` Syncthing root). Every `.stignore` emits only `(?i)*<video-ext>` plus `Proxy` patterns; `.partial` matches none. The module already documents these accumulate forever (`scan_orphan_partials()` exists to report them).
- **Failure:** lane A killed mid-transfer of a 40GB `.braw` (upgrade/reboot; `--max-duration` is soft) orphans a ~39GB `.partial` on the NAS → NAS Syncthing indexes it and fans it out over lane C to every editor with that project ticked → junk nothing on the editor side ever deletes (`path_matches_lane_a_filter` returns False for `.partial`).
- **Fix hint:** add a `.partial` exclusion to all three `.stignore` builders (and keep them in sync — see B-cross note on `VIDEO_EXTS` duplication).

### B13. `stop()` can orphan a freshly-spawned express rclone on Windows — MAJOR
- **Where:** `rclone_lane.py:2215` (last shutdown check), `:2291,2322,2380-2388` (spawn), `:1506-1533` (`_express_stop`); periodic path `:1848,1884`.
- **Defect:** `_express_flush_inner` checks `_express_shutdown` at `:2215` then does substantial work (partition, lock acquire, `rclone_available()` subprocess, write file list, build command) before spawning, with no re-check. `_express_spawn` publishes `self._express_proc` only *after* the child starts, so `_express_stop()` finds `None` throughout that window and returns.
- **Failure:** self-upgrade calls `stop()` while an express window closes → `_express_stop` finds no child → old process exits → `_express_spawn` starts a fresh rclone that outlives the parent on Windows → new companion's lane A runs alongside an orphaned express upload (AUDIT_2 C-7 dual-rclone). Same publish-after-spawn gap on the periodic lane-B path; `_run_once_locked` never consults `_stop_event`.
- **Fix hint:** re-check `_express_shutdown`/`_stop_event` immediately before spawn, under the run lock; publish the proc handle before releasing the ability to be cancelled.

### B14. `accept_folder` writes config before ignores, so "leave it paused" holds only one pass — MAJOR
- **Where:** `sequencer.py:1020-1040` (`_maybe_auto_accept`), `:912-916` (caller), `syncthing_admin.py:262-264` (order: POST folder, then `set_ignores`); test `test_sequencer.py:72-84,629-658`.
- **Defect:** the real `accept_folder` POSTs the folder config first, so a subsequent `set_ignores` failure leaves the folder *existing* (gone from `pending_folders()`). Next pass: `slug not in pending` → `return True` → `_accept_failed.discard(slug)` → `_reassert_folder_policy` (whose failure is swallowed, B5) → unpause with no ignores. Also `:1027`: when `pending_folders()` raises, it returns `True`, releasing a deliberately-latched folder. The test only proves the opposite because `FakeAdmin.accept_folder` raises *without* popping from `pending`; the real admin pops.
- **Fix hint:** set ignores before adding the folder to config, or track accept-in-progress separately so a half-accepted folder stays paused; fix the fake to match real ordering.

### Sync-engine minors
- **Express busy-requeue resets the give-up clock and bypasses the batch cap** — `rclone_lane.py:2237-2242`: `setdefault(rel, (-1, time.monotonic()))` resets `first_seen` so `EXPRESS_PENDING_MAX_SECONDS` never fires for a path that keeps losing the lock, and skips `_express_max_batch`.
- **`VIDEO_EXTS` duplicated in four modules with no shared source or cross-check test** — `rclone_lane.py:46`, `syncthing_admin.py:45`, `server/common.py:67`, `provision.py`. Byte-identical today; adding an extension in one place gives a type carried by both lanes or neither. (Cross-agent: the lists *are* currently consistent, incl. `TEMPLATE_FOLDERS`, `slugify`, `MARKER_FILENAME`.)
- **Case-sensitive `Projects` check in a case-insensitive matcher** — `rclone_lane.py:1144`: `_project_rel_for_path` rejects a first component that isn't literally `"Projects"` while lowercasing the rest; `P:\projects\...` returns None and the file waits for the next full rotation, no log line.
- **Null `slug` becomes folder ID `"None"`** — `sequencer.py:71-92,689,741,899-905`: `_item_is_valid` never checks `slug`; `_run_pass` iterates `selection` directly, so `_process_project` runs with `slug="None"`, issuing every Syncthing call against folder ID `"None"` and leaving permanent `"None"` keys in `_clone_ages`/`_orphan_ages`.
- **`stop()` cancels the debounce timer before stopping the observer, without the lock** — `rclone_lane.py:1496-1504`: a file event in that window arms a new timer under `_lock` (which `stop()` doesn't hold), firing `run_once()` on a stopped lane. Legacy mode only.
- **`reader_thread.join()` is unbounded** — `rclone_lane.py:1889`: if a grandchild inherits the stderr write handle, the reader never sees EOF and `_run_once_locked` blocks forever holding `_run_lock`, stalling project rotation.
- **Sequencer bookkeeping sets never pruned** — `sequencer.py:242,247,250-252,262`: `_accept_failed`, `_clone_ages`, `_orphan_ages`, `_paused_by_us` only grow; a stale `_accept_failed` entry permanently excludes a slug from every `_unpause_all` leak-recovery sweep (`:591-600`) even after clean re-accept.

**Verified sound (don't re-investigate):** express/periodic stand-down filter construction (excludes lead, `- **` terminator survives, metacharacters escaped, case/backslash/subpath handling), `_express_inflight` locking with `finally` release, no lock-ordering cycle, lane B `--backup-dir` never overlaps destination, `.ccsync-trash`/`.ccsync-tmp` exclusion, `write_filter_file`/`write_files_from_list` atomicity, `validate_filter_file` fail-closed, `consolidate.reconcile_with_nas` `saw_stats` fail-closed, `repath.normalized_safe_rel` genuinely shared.

---

## 4. Major — cross-component contracts

### B15. Report body cap is bypassable and pre-auth — MAJOR [verified]
- **Where:** `dashboard/src/ccsync_dashboard/app.py:45,89-101` (`body_size_gate`), `:26-29` (`_OPEN_EXACT`), `api.py:2003-2011`.
- **Defect:** `body_size_gate` enforces `MAX_REPORT_BODY_BYTES` only from `Content-Length`; a chunked request has none, so the check is skipped. And `/api/v1/report` is in `_OPEN_EXACT` with `payload: ReportIn`, so FastAPI reads/validates the whole body before `api_report` checks `X-CCSync-Token`.
- **Failure:** any host on the LAN/tailnet, no credentials: `curl -X POST .../api/v1/report -H 'Transfer-Encoding: chunked' --data-binary @/dev/zero` → uvicorn buffers it all → single-worker container OOM-killed → the fleet's only sync-status view goes down. The correct belt-and-braces pattern already exists at `ui.py:152-164` and `api.py:1756-1773`.
- **Fix hint:** stream-count bytes with a hard ceiling regardless of `Content-Length`; check the token before reading the body.

### B16. A machine-style device name is read as an editor and unshared from everything — MAJOR
- **Where:** `server/accept_device.py:77,98,122-124` (accepts `editor-laptop`, no username validation); `db.py:453-464,302` (`resolve_editor_username` returns any `_USERNAME_RE` match); `collector.py:536-543,579-583,593-617`.
- **Defect:** the server treats machine names as legitimate device labels; the dashboard reads any username-shaped name as an editor. A device approved as `editor-laptop` maps to editor `editor-laptop`, which has no `selections` rows.
- **Failure:** `collector.py:579-583` preserves only devices whose editor resolves to `None`, so a device with a real-but-empty editor is removed from every folder it's shared with. Only `enforce_max_share_removals=3` stands between that and a fleet-wide unshare — and it caps *devices*, not folders, so one such device is under the limit and gets silently unshared everywhere.
- **Fix hint:** validate device names against the actual editor account list before treating a name as an editor; count folder removals in the brake.

### B17. `transport_health` computed every tick and dropped by the server — MAJOR
- **Where:** companion `app.py:1768-1811,392` + `reporter.py:242-246` (sends it); dashboard `api.py:1944-1962` (`ReportIn` has no such field, pydantic `extra='ignore'` drops it).
- **Defect:** the field crosses the wire and is read by nobody (`grep transport_health` over `dashboard/` is empty).
- **Failure:** the case the companion docstring names — "a RELAYED editor and a merely slow one are indistinguishable on the fleet grid" — is still true. Same for orphaned `.partial` and express-lane failure counters, which `app.py:1800-1810` notes exist *only* to give the server visibility it otherwise lacks.
- **Fix hint:** add the field to `ReportIn`, persist it, surface it on the grid.

### B18. Sign-in error text never reaches the editor, and 403 has no mapping — MAJOR
- **Where:** companion `identity.py:158-164` (reads `data.get("error")`, fallback map covers only 401/429/503); dashboard sends `{"detail": ...}` everywhere: `api.py:745,753,811-814,816-820,834,842`.
- **Defect:** the companion reads `error`; FastAPI sends `detail`. And 403 (`:816-820`, "not in the 'editors' group on the NAS — ask an admin to add the account") has no fallback entry.
- **Failure:** an editor with a NAS account but not in `editors` sees "sign-in failed (HTTP 403)" instead of the actionable sentence; a TrueNAS-unreachable 503 renders as "sign-in is not available on this server" when the real cause is "retry." `onboarding/steps.py:184` reuses the helper, so the install gate loses it too. `test_identity.py:247` builds a fake `{"error": ...}` 401 body — a shape the dashboard never sends — pinning the wrong contract.
- **Fix hint:** read `detail` (fall back to `error`); add a 403 entry; fix the test's fake body.

### B19. `setup_syncthing_folder.py --force` silently strips WAN puller tuning — MAJOR
- **Where:** dashboard `provision.py:217-218` (`maxConcurrentWrites:32`, `pullerMaxPendingKiB:65536`), applied at `collector.py:348` only in the create branch; server `setup_syncthing_folder.py:136-159,162` PUTs a full folder object without those keys.
- **Defect:** a `--force` PUT resets both knobs to Syncthing defaults permanently; unlike `.stignore` there is no repair pass for folder settings.
- **Failure:** re-running `--force` to fix a path leaves that project pulling at `maxConcurrentWrites=2` over the WAN forever, nothing logged. Folders created by the server script rather than the collector never get the tuning at all.
- **Fix hint:** include the tuning in the server script's folder object, or add a collector repair pass for folder settings.

### Cross-component minors
- **Folder-ID derivation disagrees** — server `setup_syncthing_folder.py:113` uses `slugify(rel)`; dashboard `collector.py:243-245` uses the marker slug (deliberately, for moved/adopted projects). A moved project keeps its old slug; an admin repairing ignores via the server script misses `find_folder` and creates a *second* Syncthing folder over the same directory, which editors never see and which fails the collector every cycle.
- **Syncthing `--label` is load-bearing, not cosmetic** — `setup_syncthing_folder.py:97,116,137` documents it as human-readable, but `collector.py:510-512` writes it to `projects.label` and `api.py:906` treats label as the rel path; `sequencer.py:1033,742` makes it the editor's on-disk dir and the rclone remote subpath. A non-path label makes lane A create a wrong dir on the NAS.
- **macOS self-upgrade cannot work (latent)** — `api.py:1588,1630-1644,1602` will advertise a macOS package with no extension; `upgrade.py` has no `chmod` and downloads to a hardcoded `.new.exe` name. macOS build "NOT SHIPPED YET" (`macos_bootstrap.sh:606`) but both halves of the plumbing exist. **[Closed 2026-08-03 by the macOS port: `upgrade.py` derives the staged name and platform key from `sys.platform` and chmods 0o755 after the sha verify; the macOS build/publish path is `tools/release_macos.sh`. Unvalidated on real hardware — see KNOWN_BUGS item 8 and `installer/MACOS_FIRST_RUN.md`.]**
- **Dashboard version drift unguarded** — `dashboard/src/ccsync_dashboard/__init__.py:3` `VERSION="0.3.5"` vs `pyproject.toml:7` `version="0.2.0"`; `release.ps1:183` and `check_deploy_drift.ps1:135` read only `__init__.py`. Cosmetic today (container runs from `PYTHONPATH`, never pip-installs).
- **`ship.ps1` reports success when installer publish was skipped** — `build_editor_package.ps1:537-539` warns and continues on a stale/missing `onboard.exe`; `ship.ps1:121-124` checks only `$LASTEXITCODE`. (Same root cause as B23.)
- **`TransferIn.project_slug` expected but never sent** — `api.py:1902` + `db.py:1383` persist it; companion transfer dicts (`rclone_lane.py:1932-1938`) omit it. Column always NULL.
- **`/api/v1/verify`'s `report_token` dropped by the companion** — `api.py:857` returns it; `onboarding` consumes it but `identity.verify_credentials` (`identity.py:241-251`) does not, so a tray sign-in with a stale `dashboard_token` still 401s every report forever.
- **Device ID validated on one side only** — `accept_device.py:51-66` shape-checks and uppercases; `api.py:1575-1580` passes `payload.device_id.strip()` through, so a truncated paste surfaces as a generic 502.

**Verified consistent (no action):** `VIDEO_EXTENSIONS`, `TEMPLATE_FOLDERS`, `slugify`, `MARKER_FILENAME` across server/dashboard/companion; identity-token format between `auth.py:172-177` and `identity.parse_token`; the upgrade contract (`url`/`sha256`/relative-URL origin pinning/token-authed download) across `api._upgrade_info`, the middleware carve-out, and `upgrade.download_and_verify`; lane names/states; `compose.yaml` env vs `install_dashboard_app.compose_config`; Syncthing REST endpoints and `X-API-Key`.

---

## 5. Major — onboarding / installer destructive-op safety

### B20. Destructive P: teardown keys on the radio button, not the verified role — MAJOR
- **Where:** `onboarding/onboard.py:468` (dispatch), `:377-380` (detection); `steps.py:758-763,799,993-994`.
- **Defect:** `show_install` detects a base-vs-editor mismatch against `self.verified_role`, prints an amber note, then dispatches on `self.role_var.get()` anyway (`_worker_editor` → `_clean_slate("editor")` → `build_cleanup_plan(role="editor")` sets `unmount_p=True` and adds `P:/` to cleanup).
- **Failure:** re-run on the base rig with the radio left at its default `"editor"` → `verify_account` returns `role:"base"` (the code knows) but proceeds: `subst P: /D` + `net use P: /delete /y` destroy the base rig's NAS mapping, then cleanup scans the live `P:\` share for exes; bootstrap recreates P: as a subst of a *local* folder, taking every `P:\Projects\...` clip path offline. This is exactly what `test_base_role_never_reaches_into_p_drive` asserts at the steps layer — but the caller hands it the wrong role.
- **Fix hint:** dispatch on `verified_role` (or block install on mismatch), not the radio.

### B21. The `Test-Path "P:\"` foreign-mapping guard is blind in the two cases that matter — MAJOR
- **Where:** `installer/windows_bootstrap.ps1:737` (guard), `:785-786` (teardown), `:946` (its own comment about elevation).
- **Defect:** if `Test-Path "P:\"` is false, `$script:PIsForeign` stays false and the script deletes P:. Two false negatives: (a) an elevated run can't see the unelevated session's drive letters, yet teardown runs via `Invoke-AtUserIntegrity` inside the user session where the mapping exists; (b) a disconnected persistent mapping (NAS asleep / Tailscale not up — likely during bootstrap) reads as absent while still in the device map.
- **Failure:** base rig, P: is the real NAS mapping, admin right-clicks "Run as administrator" → guard says "no P:" → teardown deletes it → section 5 recreates P: as a loopback of local `C:\Creators_Club` → every Resolve clip path resolves into a near-empty local tree (INST-15).
- **Fix hint:** detect the mapping via the device map / `net use` inside the correct integrity level, not `Test-Path`; treat "can't tell" as foreign.

### B22. Base-rig install clean-slates before checking the companion exe exists — MAJOR
- **Where:** `onboarding/onboard.py:581-585` (base worker); contrast editor worker `:533-540`.
- **Defect:** `_clean_slate("base")` taskkills the companion, deletes all four `ALL_RUN_VALUES` autostart entries, and unlinks the binary — *then* `steps.install_companion()` can raise `FileNotFoundError`. No rollback, no resume; RETRY fails identically forever. The editor worker pre-checks this case; the base worker doesn't.
- **Fix hint:** pre-flight `find_companion_exe` before the destructive phase in the base worker.

### B23. `build_editor_package.ps1` exits 0 on a stale package, defeating `ship.ps1`'s only gate — MAJOR [confirmed x2, verified]
- **Where:** `installer/build_editor_package.ps1:261,271,279,308-316,312` (+ `:537-539`); `tools/ship.ps1:121`.
- **Defect:** `$missing` (source absent) and `$copyFailed` (destination locked) produce warnings but never a non-zero exit — confirmed exit code 0 under `-DryRun`. `ship.ps1:121` gates step 3 solely on `$LASTEXITCODE`.
- **Failure:** an editor has `P:\Assets\Software\CC_Sync\onboard.exe` open off the share (seen live) → `Copy-Item` throws → script prints "package is STALE", exits 0 → `ship.ps1` publishes and prints "ship complete" while every new editor still gets the previous `onboard.exe`.
- **Fix hint:** `exit 1` on `$missing`/`$copyFailed`.

### B24. `install_syncthing_app.py` uses the broken `query-filters` call its sibling documents and fixed — MAJOR
- **Where:** `server/install_syncthing_app.py:91` vs the fix + rationale in `install_dashboard_app.py:343-345`.
- **Defect:** the 25.10 middleware returns `[]` for a filtered `GET /app` even when the app exists (observed live 2026-07-24); the dashboard installer fetches the full list and filters client-side, this script doesn't.
- **Failure:** re-run against a NAS with Syncthing installed → filtered GET returns `[]` → `app_already_installed()` False → POSTs a create for an existing app → opaque 422 → printed advice tells the admin to delete the healthy production app.
- **Fix hint:** copy the full-list-then-filter approach from the dashboard installer.

### Onboarding / installer minors
- **`setup_editor_account.py` can strip the ACL off the shared `homes` parent** — `:141` blocklists `/`, `/nonexistent`, `/var/empty` but not the `homes` dataset root (`:296`); a hand-created account whose `home` points there gets `filesystem.setperm mode:700 stripacl:True recursive:False` against the shared parent, breaking every other editor's SMB path in.
- **`validate_local_root` accepts a bare drive root** — `steps.py:590,616` (`_DRIVE_PATH_RE`): `"D:\"` passes, and `windows_bootstrap.ps1:691,818` then `New-SmbShare ... -FullAccess` publishes the entire D: volume and maps P: to it. No guardrail case for volume-root.
- **Windows Syncthing autostart guarded on registry-value existence only** — `windows_bootstrap.ps1:1146`: never re-checks the baked command line against the detected `$syncthingPath`; a stale entry pointing at a deleted path is reported "already registered" and never repaired. macOS got this fix (`macos_bootstrap.sh:378`); Windows didn't.
- **Fleet tokens on native-process argv** — `tools/ship.ps1:79,100` (`curl.exe -H "X-CCSync-Token: $env:..."`), `onboarding/steps.py:468` (`-DashboardToken` on the bootstrap argv), `installer/windows_upgrade.ps1:36` (literal 48-hex token in an `.EXAMPLE` shipped to every editor via `build_editor_package.ps1:226`). Readable via `Get-CimInstance Win32_Process` with no admin. Contrast `server/common.py:377` which pipes secrets over stdin (AUDIT SEC-2).
- **BACK button guard during install is dead code** — `onboard.py:425,464-465,605-606`: `_nav_bar` returns None for the BACK widget when `next_ is None`, so `self._install_back_btn` is always None; clicking BACK mid-`_clean_slate` destroys the log widget and the worker's `_append_log` raises `TclError` into an invisible handler.
- **`setup_syncthing_folder.py` skips path-segment validation** — `:112-114`: `--project-rel-path "../../etc"` → folder id `etc` at `/data/Projects/../../etc`, sendreceive-syncing the container's `/etc`. Siblings route through `common.project_path_rel`.
- **`HOST_ROOT_RE` permits spaces the `xargs` prune can't handle** — `install_dashboard_app.py:92,549-552`: a space in root word-splits the unquoted `ls | xargs rm -rf` backup prune; not destructive but pruning silently stops forever.
- **`retire_old_venv` return code discarded** — `install_dashboard_app.py:483-484`: unlike every other `run_ssh`, neither `rc` nor `err` captured; a failed `mv` leaves the pre-C-2 editor-writable venv in place and reports success.
- **`ensure_config` doesn't catch `UnicodeDecodeError`, runs after clean-slate** — `steps.py:1078-1081`: a cp1252-saved `config.toml` raises `ValueError` (not `OSError`) post-destruction → "install failed" → RETRY fails identically forever.
- **`finalize_config_identity` implemented and tested but never called** — `steps.py:542`; four tests exercise it (`test_steps.py:696-724`), no production caller. A green suite asserting a guarantee nothing runs.
- **Zero-byte `last_version.txt` kills `check_deploy_drift.ps1`** — `:237`: `Get-Content -Raw` on an empty file returns `$null`, `.Trim()` throws under `$ErrorActionPreference="Stop"` before VERDICT; `upgrade.py:87` can leave a 0-byte marker; `ship.ps1:139` runs this as its final step.
- **Predictable `/tmp` staging on macOS** — `macos_bootstrap.sh:182-191,286-305`: `/tmp/ccsync-rclone.zip` etc; on a shared Mac another local account can pre-plant the binary that becomes `rclone_path`. Windows uses per-user `$env:TEMP`.
- **Uninstall knows only `CCSync-SubstP`** — `windows_uninstall.ps1:107` vs `windows_bootstrap.ps1:226` (`CCSync-OneShot-<hex>` tasks unregistered only if the process survives; the bootstrap timeout kills it). `-Full` leaves orphan scheduled tasks accumulating.
- **User PATH read expanded, written flat** — `windows_bootstrap.ps1:524`, `windows_uninstall.ps1:216,228`: `GetEnvironmentVariable("Path","User")` expands `REG_EXPAND_SZ`, `SetEnvironmentVariable` writes `REG_SZ`; a `%USERPROFILE%\...` entry is permanently rewritten to a literal. Uninstall inflicts this even on a machine the bootstrap never touched.

**Verified sound:** `common.build_marker_write_cmd`/`setup_tree.build_remote_script` guards (marker, ancestor/descendant refusals, single-quoting) are real; `build_swap_script` is rename-only with working rollback; `SUDO_PW_PREAMBLE` keeps the password off the remote argv; `test_env_keys_match_compose` passes with the new b-roll keys.

---

## 6. Bench harness — result-corrupting bugs

### B25. Syncthing runs can report "complete" at t≈0 — CRITICAL (bench)
- **Where:** `bench/ccbench/runners/syncthing.py:283-293`, `:352,355,358,377`; `report.py:127`.
- **Defect:** `needBytes==0 and state in ("idle","")` is true both *before* the peer connects and the global index arrives *and* after sync finishes; the loop checks neither `globalBytes` nor peer connection, and polls immediately after `add_folder`.
- **Failure:** empty `sendreceive` folder scans instantly → state `idle`, `needBytes 0`, peer not yet dialled → first poll matches → returns `(True, ~0.0)` → `_tree_bytes` returns 0 → emits `ok=True, num_bytes=0, MB_s=0.0`; because `ok=True`, `report.summarize_repeats` medians a 0.0 into lane C. The `if not completed` guard is bypassed precisely because the bug looks successful. No test covers `_wait_for_sync`.
- **Fix hint:** require `globalBytes>0` (or peer-connected) before accepting `needBytes==0`; add an initial delay/poll for connection.

### B26. The report's "exact flags" recommend a config it didn't measure — MAJOR (bench)
- **Where:** `bench/ccbench/report.py:162-164`.
- **Defect:** `--multi-thread-streams 0` is falsy so the flag is dropped, but rclone's default is 4 — omitting it selects 4, not 0.
- **Failure:** `multi_thread_streams=[0,4,8]` (the shipped example) with `0` winning lane A → printed `Exact flags` omit the flag → editor runs 4 streams, possibly the config measured as slower.
- **Fix hint:** emit `--multi-thread-streams 0` explicitly when the winning value is 0.

### Bench minors
- **Partial pre-clean / destination-empty produces a fast "verified" row** — `_rclone_common.py:349-355`, `guard.py:113-116`: only total-zero is caught; a timed-out `cleanup_remote` (swallows `TimeoutExpired`/`OSError`) or `rmtree(ignore_errors=True)` leaving a warm dest yields `num_bytes << expected_bytes`, short `seconds`, `verify_upload=True` (it only checks presence+size). `report._winner` *prefers* verified rows, so the corrupted row is more likely to be selected.
- **`rclone_smb` obscured password can land in `results.jsonl` and the report** — `rclone_smb.py:59` → `guard.py:92-96` → `_rclone_common.py:326` → `report.py:191,197`; `rclone reveal` is reversible. Triggers when `remote_subpath` lacks a `_bench` component.
- **iperf3 `param_matrix` unguarded** — `matrix.py:194` vs `:135-142`; a malformed `[params.iperf3]` escapes `run_matrix` before `:220`, so `_cleanup_endpoints` never runs.
- **`--lanes` doesn't filter iperf3** — `matrix.py:189`: `ccbench run --lanes A` still runs the full iperf3 sweep.
- **Cached combos never register for cleanup** — `matrix.py:150-152` vs `:180`: `pending_cleanup.setdefault` sits after the `[skip-cached]` continue, so resuming a complete matrix does no remote cleanup.
- **`syncthing direction="bidirectional"` performs a one-way sync** — `syncthing.py:320,331`: passes the direction check then falls to the `else`/down branch; the row is labelled bidirectional but measured one-way.

---

## 7. rcta/

`rcta/` is untracked and gitignored (`.gitignore:9`) — a local scratch harness for testing
rclone filter behaviour, not part of the shipped product. Cross-agent recommendation:
**delete it.** Its stale 4-line `filter.txt` carries 1 of the 16 `VIDEO_EXTS` (`+ *.mov`
only) and no lane-B rules, so anything reaching for it would silently never upload
`.braw/.mxf/.mp4` and it would pass `validate_filter_file` unchallenged. Everything it once
probed is now covered by `companion/tests/test_rclone_filters.py`. (Also: `+ *.mov` is
case-sensitive and wouldn't match the harness's own `src/Sub/CLIP.MOV`.)

---

## Suggested order of work

1. **b-roll diff decision (blocking, uncommitted):** either wire the deploy end-to-end (B1, B2), force a strong token (B3), fix the tests (B4) — or hold the feature and default `broll_enabled` off. The tests currently give false green.
2. **Silent data-integrity criticals:** B5 (unfiltered lane C), B6 (base rig drops off grid), B12 (orphaned `.partial` fan-out).
3. **Security / availability:** B15 (chunked pre-auth OOM), B3, B16 (machine-name unshare).
4. **Runtime correctness:** B8 (one-line logger fix), B9 (keep-awake forever), B10 (Pause/Resume auth bypass), B13/B14 (sync-engine races).
5. **Installer destructive-op safety:** B7, B20, B21, B22 — each can brick a base rig or misreport a failed install.
6. **False-green test sweep:** B10, B4, B18, B14 all have tests that assert the wrong thing; treat as its own pass.
7. **Bench + rcta:** B25/B26 corrupt benchmark results that inform real config choices; delete `rcta/`.
