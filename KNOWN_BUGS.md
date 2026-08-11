# Known bugs

**Status 2026-08-11: fresh seven-agent hunt (Opus), orchestrated + verified.**
The 2026-08-03/05/06 hunt-and-fix passes closed everything in the old ledger
that was fixable from the base rig; that history is archived at
`docs/bug-hunt-2026-08.md` and `docs/macos-first-run-2026-08-05.md`. This file
is the **new** ledger from a clean sweep of all seven territories (companion
sync core, companion UI/Resolve, companion media pipeline, dashboard, b-roll,
music, ops/installer/server). The hunt prioritised the 0.5.x–0.6.3 and
2026-08-10 fold-in code, which had never been through a dedicated pass.

Nothing here is fixed yet — this is the worklist. **82 findings**: 3 critical,
~31 major, the rest minor/low. Entries are grouped by component with a prefix
(`SYNC-`, `UI-`, `MED-`, `DASH-`, `BROLL-`, `MUSIC-`, `OPS-`); severity and a
confidence note ride each one. `file:line` is as of commit `4075b3c`
(companion 0.6.3, installer 1.0.21, dashboard 0.3.8).

Findings the orchestrator verified directly against source are marked
**[verified]**; the rest are the hunter's analysis, marked **[analysis]** and
generally lower-stakes. A standing carryover section at the end keeps the old
ledger's genuinely-still-open items (proxy attach proof, the macOS validation
backlog, the `._*` NAS sweep, code-signing) alive.

---

## Critical

### SYNC-1 — lane B is never stopped in managed mode; a self-upgrade orphans a delete-authorised `rclone sync` [verified]
`app.py:2337-2360`. `_stop_lanes()`'s managed branch (the default whenever a
`dashboard_url` is set) stops the sequencer, lane C and lane A, but never
`self._lane_b.stop()`. `RcloneLane.stop()` is the *only* path to
`_kill_running_process()`, and its own comment names this exact hazard: on
Windows the rclone child outlives the parent, so a self-upgrade would leave the
old lane B `sync` racing the new process's lane B over one destination
(AUDIT_2 L-12/C-7). `sequencer.stop()` joins its worker with `timeout=10` and
returns while it is still inside `lane_b.run_once()`. **Failure:** self-upgrade
or sign-out during a lane B pass → two `rclone sync` children over the same
`P:\Projects\X`, each with its own `--max-delete` budget and `--backup-dir`,
both writing the same `<proxy>.<token>.partial`. **Fix:** add
`self._lane_b.stop()` beside the existing `self._lane_a.stop()`.

### UI-1 — RETRY FAILED permanently wedges the fix-all popup and holds `_popup_active_lock` for the session [verified]
`popup.py:880` (`_run_fix`) never resets `_finished`/`_pending_results`;
`_deliver_results()` (`popup.py:1034-1038`) latches `self._finished = True` and
nothing clears it. The MAC-11 fix (old item 18) made the exactly-once latch
**per-dialog** when it needed to be **per-batch**. **Failure:** FIX ALL over 5
clips, 1 fails (a cloud placeholder — the documented reason RETRY FAILED
exists). Editor clicks RETRY FAILED (`popup.py:867`); the copy and `ReplaceClip`
succeed, the worker publishes, both delivery routes hit the `if self._finished`
guard and no-op, `_fix_done` never runs, `_fixing` stays True forever. FIX ALL
and IGNORE are disabled, STOP/SKIP/CANCEL only set flags a finished worker
never reads, and the X routes to `_on_cancel_all` which returns — the window
cannot be closed by any means, and `app._popup_active_lock` (held across
`show_popup`) is never released, so sign-in, update, consolidate and every
later out-of-tree batch are refused with "Another CCSync window is already
open" for the rest of the session. On darwin the pump is parked in
`run_dialog`'s `tkwait` = MAC-11 reproduced exactly (SIGTERM dead, `kill -9`).
The same reset gap re-arms FIX ALL after any stopped batch. **Fix:** reset
`_finished = False` and `_pending_results = None` under `_progress_lock` at the
top of `_run_fix()`, and add a two-batch regression test (every existing
`test_popup.py` case drives a single batch).

### UI-2 — `ProgressWindow` ends itself with `root.quit()`, which never ends `run_dialog`'s tkwait on macOS [verified]
`popup.py:1381` (`_tick`), run via `ui_dispatch.run_dialog(root)` at
`popup.py:1305`. `ui_dispatch.py:29-31` states the rule outright: on darwin
`run_dialog` parks in `tkwait window`, and `root.quit()` is **not** the way out
— `_tkinter`'s quit flag is process-global and `Tk_WaitWindow` never consults
it. `ProgressWindow` (tray → "Bring an existing project's media in") is the one
dialog in the package that ends itself with `quit()` instead of `destroy()`;
the `finally: root.destroy()` at `:1308` is only reached *after* `run_dialog`
returns, so it never runs. **Failure:** on a Mac the copy + lane-A upload
complete, `_tick` calls `root.quit()` and returns without re-arming; the window
stays on screen, the pump is parked in `tkwait`, every later dialog queues
forever, `serve()`'s mainloop cannot return, SIGTERM cannot finish, and
`_popup_active_lock` is held permanently. Windows is unaffected (`mainloop()`,
which `quit()` does end). **Fix:** guarded `root.destroy()` instead of
`root.quit()`.

---

## Major — companion sync core

### SYNC-2 — `_unpause_all` releases folders the ignores-verification deliberately skipped [verified]
`sequencer.py:735-750` sweeps by raw `item.get("slug")` with no
`_item_is_valid` filter, and `_prune_bookkeeping` (`:712`) does
`_ignores_unconfirmed &= live_slugs` where `live_slugs` contains only *valid*
items — so a latch for an invalid-but-slugged item is erased. The dashboard
emits such rows routinely: `fetch_selections` is a LEFT JOIN, so an
archived/deleted project ships `{"slug": ..., "rel_path": None, "active":
False}`. **Failure:** editor ticks project X → a `set_ignores` times out → X is
correctly latched and paused → an admin archives X → next selection drops X as
invalid, prunes the latch, and the between-passes/`pause()`/`stop()` sweeps
release it, so an unfiltered `sendreceive` folder offers every `.braw`/`.mov`
and the whole `Proxy/` tree bidirectionally (the L-3 outcome the latch exists to
prevent). **Fix:** apply `_item_is_valid` in `_unpause_all` (skip = stay
paused), or latch invalid-but-slugged items instead of pruning them.

### SYNC-3 — sign-in silently overrides the tray's Pause [verified]
`app.py:2388-2400` (`on_signed_in`) gates on `_lanes_started` and the login
gate only; `_start_lanes()` checks `config_problems`, `_root_absent` and
`_sync_enabled` but never `self._paused`. Every other restart entry point does
(`_root_resume_lanes` opens `if self._paused: return` at `:1093`).
**Failure:** `require_login=true` (default), editor signed out with "Pause
syncing" ticked, signs in from the tray → full rotation and express uploads
resume while the tray checkbox still renders `checked`. **Fix:** return early
from `_start_lanes()` (or `on_signed_in()`) when `self._paused`.

### SYNC-4 — the editor's TrueNAS password reaches `companion.log`, a tray toast, and the diagnostics clipboard [verified]
`drive_swap.py:136-142` builds `net use P: <unc> /persistent:no /user:<u>
<password>` and runs it under a 30 s timeout; the except arm returns
`f"net use failed: {exc}"`, and `TimeoutExpired.__str__` embeds the **full argv,
cleartext password included**. `app.swap_p_to_server` logs it at INFO (the
default level) and returns it to the tray, which shows it as a balloon;
`copy_diagnostics()` then ships the log tail to the clipboard. **Failure:**
first grade-swap on a machine prompts for the editor's TrueNAS login; the
default `dashboard_url` is a tailnet address, and an SMB connect to a
sleeping/unreachable host routinely exceeds 30 s → the password lands in
`~/.ccsync/companion.log` and on screen. `persist_credentials` has the same
exposure via `cmdkey /pass:` under `log.debug(..., exc_info=True)`. **Fix:** the
except arm should report `type(exc).__name__` (or a redacted argv); passing the
secret positionally on argv is also visible to any process on the box.

### SYNC-5 — `share_stray_luts` opens a Tk root without `_popup_active_lock` [verified]
`app.py:3075-3119`, dialog at `:3101`. This is the only `popup.confirm_dialog`
call site in the companion that does not take `_popup_active_lock` (six others
do, each citing CORE-M3→CORE-H8). **Failure:** a watcher out-of-tree popup is on
screen (a real Tk root on a `ccsync-popup` thread); the editor picks "Share N
LUTs", which builds a second Tk root on the tray worker — the documented
wedge-the-Tcl-interpreter condition. Independently, because the lock is never
held, `apply_upgrade`'s `if self._popup_active_lock.locked()` guard (`:2451`)
sees nothing, so a self-upgrade can swap the exe and `request_shutdown()`
mid-`adopt(strays)` — a truncated LUT under a final name in the shared library,
which lane A publishes fleet-wide. **Fix:** wrap the dialog and the `adopt()`
in `_popup_active_lock.acquire(blocking=False)` / `finally: release()`.

### SYNC-6 — `consolidate_project()` has no disconnected-drive gate [verified]
`app.py:1518-1558` gates on `_sync_enabled`, `_paused` and `config_problems`
but never `_root_absent`; the two sibling copy-and-relink entry points do
(`scan_whole_project` at `:1447-1458`). `_root_absent` is invisible to a
`config_problems` check (`_demote_removable_root_problem` strips it at startup).
**Failure:** macOS editor, external SSD unplugged, project also references
Desktop media so the plan is non-empty. Advanced → "Bring an existing
project's media in" → `fixer.fix_clip` refuses only a *blank* local_root, so it
`mkdir(parents=True)`s and copies the originals onto the **boot volume** at
`/Volumes/T7/Creators_Club/Projects/…` and relinks Resolve to canonical `P:\…`.
Lane A then correctly blocks (root not present), so the files sit unsynced; on
replug macOS mounts the SSD at `/Volumes/T7 1` (ROOT_MISPLACED). **Fix:** add
the `_root_absent` / `_local_root_is_broken()` refusal alongside the existing
three gates.

### SYNC-7 — the macOS SIGTERM self-chain guard compares a bound method with `is`, so it never fires [verified]
`shutdown_guard.py:949`: `if callable(previous) and previous is not
self.handle_sigterm:`. `self.handle_sigterm` builds a **new** bound-method
object on every access, so the identity test is always True even when
`previous` is this guard's own handler. **Failure:** `_restore_signal_handler`
deliberately leaves our handler installed when it cannot restore (previous is
None, or the restore raised off the main thread); a later `start()`
(pause→resume, config reload) then captures our own still-registered handler
as `_previous_sigterm`, and the next SIGTERM recurses `handle_sigterm` → chain →
`handle_sigterm` to the recursion limit, each frame logging a traceback.
`app.shutdown()`'s `_shutdown_started` latch bounds the real damage to a
logout that unwinds ~1000 frames and floods the log — but the guard is provably
dead code, on the least-validated platform. **Fix:** compare with `==`, or
`getattr(previous, "__func__", None) is type(self).handle_sigterm and
previous.__self__ is self`.

### SYNC-8 — a stop during startup ignores-verification leaves unverified folders unpaused [analysis]
`sequencer.py:626` + `:589-592`. `_verify_startup_ignores` returns early on
`_stop_event` having latched only a prefix of the selection; `_startup_unpause`
then runs `_unpause_all(cached)` over the **whole** cached selection.
**Failure:** verification costs one `GET /rest/db/ignores` per folder; with 6
projects at a 5 s read timeout that is up to a 30 s window at every launch (and
after every pause→resume). A quit/sign-out/config-reload inside it sets
`_stop_event`, the loop bails after folder 1, folders 2..N are never latched,
and the sweep releases them while Syncthing runs on. **Fix:** on the early
return, latch every not-yet-verified slug — or skip the unpause sweep entirely
when `_stop_event` is set.

## Major — companion UI / Resolve

### UI-3 — the tray never rebuilds its menu for a change in stray-LUT count [verified]
`tray.py:1575-1599` (`_menu_fingerprint`) omits `stray_luts`, though
`_build_menu` renders the "► N LUTs only on this machine — share with the
team" item from it (`:1802-1809`) and gathers it at `:1547`. Every other
conditional block (`setup_name`, `upgrade_info`, `removable`, `p_swap`,
`_proxy_fingerprint`) is in the tuple. `_refresh_loop` only reassigns
`icon.menu` on a fingerprint change. **Failure:** an editor drops a new LUT
into Resolve's own LUT folder; the scan takes `stray_lut_count()` 0 → 3; on an
otherwise-idle machine nothing else in the fingerprint moves, so the menu is
never rebuilt and the whole shared-LUT onboarding item is silently unreachable
(and the mirror: it lingers after `share_stray_luts` drops the count to 0).
**Fix:** add `int(snap.get("stray_luts") or 0)` to the tuple.

## Major — companion media pipeline

### MED-1 — own-footage proxies silently drop every audio track but the first [verified — hunter ran real ffmpeg]
`ffmpeg_tools.py:511-539` (`own_proxy_cmd`) has no `-map`, so ffmpeg's default
selection takes exactly one video and one audio stream. Camera originals in
this tree routinely carry two-plus audio streams (Sony/Canon MXF dual pairs,
dual-system, `.mts`). Reproduced live: a 3-stream `.mov` through the exact
`own_proxy_cmd` flags yields 1v+1a+tmcd — the second audio track is gone. An
editor cutting on the proxy has no scratch/lav track; it reappears only on the
original — the same silent wrongness `-tag:v hvc1` and `-timecode` exist to
prevent. **Fix:** add `-map 0:v:0 -map 0:a?` to `own_proxy_cmd` (leave
`preview_proxy_cmd` alone for indexer parity).

### MED-2 — the verification decode's timeout is a flat 30 min while the encode's scales with duration [analysis]
`proxy_gen.py:998-1002` (`_verify` passes `STUCK_FLOOR_SECONDS` = 1800) vs
`:1155` (`encode_once` computes `ceiling = max(1800, duration × 60)`, pinned by
`test_proxy_gen.py:591`). **Failure:** a multi-hour source encodes fine, then
the full-decode verify of the ~20 GB HEVC `.partial` (on the base rig, over
SMB) exceeds 30 min; `_verify` returns "the verification decode never
finished", the partial is discarded, and three passes later the clip is capped
permanently — the encode work thrown away every time, the log blaming the file.
**Fix:** pass the same duration-scaled ceiling (or a smaller multiple) into
`_verify`.

### MED-3 — b-roll `/insert` and `/status` run the blocking Resolve API on the 8899 request thread under `_API_LOCK` [verified]
`broll_server.py:320` (`try_connect`), `:362` (`perform_insert`) →
`resolve_bridge.py:968` (`with _API_LOCK`). `music_server.py:20-23` states the
rule the music routes were built around — the scripting API blocks
indefinitely when Resolve is modal/busy/on the Project Manager, so it runs its
half in a killable child with a 90 s timeout. The b-roll half on the *same
listener* calls `scriptapp`/`ImportMedia`/`AppendToTimeline` in-process with no
timeout, holding `_API_LOCK`. **Failure:** editor has a modal dialog open in
Resolve and clicks "Send to Resolve" (or the settings panel polls `/status`);
the request thread blocks inside the Resolve API forever holding the lock, and
the timeline watcher, fixer, FIX ALL, LUT/stills and the tray's Resolve reads
all queue behind it; repeated clicks accumulate one wedged daemon thread each.
**Fix:** route `/insert` and `/status` through the same `music_server.call`
child-process-with-timeout, or at minimum a bounded `_API_LOCK.acquire(timeout=)`.

### MED-4 — `perform_insert` appends with no `trackIndex`/`mediaType` and never verifies placement [verified]
`resolve_bridge.py:1007-1015` calls `AppendToTimeline([{mediaPoolItem,
startFrame, endFrame}])` and only checks `if not appended`. This is the exact
landmine documented in `music_worker.py:35-40`: AppendToTimeline without
`trackIndex` obeys the timeline's destination-track buttons — with the video
destination toggled off it places **nothing and reports no error**, and a
returned item is not proof of placement (verify `GetStart()`). **Failure:**
editor has the video destination track toggled off (normal during audio work);
"Send to Resolve" returns `{"ok": true, "message": "Inserted A001 (240
frames)"}`, the UI shows success, and nothing is on the timeline. The music
path (`music_worker.place`, `:197-220`) guards both cases. **Fix:** pass
explicit `trackIndex`/`mediaType` and verify `GetStart()`, mirroring
`music_worker.place`.

## Major — dashboard

### DASH-1 — the admin "Approve device" UI partial skips the device-ID shape check [verified]
`ui.py:899-924` (`partial_admin_approve_device`, what
`templates/partials/admin_users.html` actually posts to) passes
`form["device_id"]` straight to `syncthing.approve_device()` with no
`normalize_device_id()` and no uppercasing; the JSON API twin
(`api.py:1621`) does normalize. **Failure:** an admin pastes a
truncated/lowercased device ID; Syncthing 502s generically or creates a device
that can never connect — the failure `_DEVICE_ID_RE` was added to prevent, on
the only route a human uses. **Fix:** call `api.normalize_device_id()` in the
partial and surface its `ValueError` as the panel error.

### DASH-2 — the admin UI partials never record the known editor (B16 evidence gap) [verified]
`ui.py:822-860` and `:899-924`. The JSON API routes `api_admin_create_user`
and `api_admin_approve_device` both call `db.record_known_editor(conn,
username, "admin")` — the whole point of the B16 fix (an admin naming the
device is the strongest evidence the username is a real editor). The two htmx
partials that back the actual admin UI do neither (`partial_admin_create_user`
doesn't even take a `conn`). **Failure:** admin creates editor `newbie` and
approves their device through the Users page; `known_editors` gets no row, so
`_run_enforce` classifies the device UNMAPPED, logs the "username-shaped name
that matches no editor account" warning, and never shares any folder with it —
the editor syncs nothing until someone ticks a project for them. **Fix:** add
`conn: Depends(get_conn)` to both partials and call `record_known_editor(...,
"admin")` + `conn.commit()` on success, as the api.py twins do.

### DASH-3 — every session-gated write path reads an unbounded request body [verified]
`app.py:50-59` (`_BODY_LIMITS` / `_BODY_LIMIT_PREFIXES`), `ui.py:788-789`
(`_form`). The body-size gate covers exactly two paths (`POST /api/v1/report`,
`PUT /api/v1/admin/packages/*`); `/login` has its own 8 KB cap. Every other
write path — all the htmx `POST /partials/...` handlers via `_form()`
(`await request.body()` + `parse_qs` with **no** `max_num_fields`, unlike
`page_login_submit`) and every pydantic-bodied `/api/v1/*` POST — buffers the
whole body in memory in the single-worker container before any length check.
**Failure:** any editor with a valid session POSTs a multi-GB body to
`/partials/selection/<self>/<slug>/toggle`; the one uvicorn worker allocates
it and the container OOMs — the exact outcome `MAX_REPORT_BODY_BYTES` exists to
prevent, reached through an unguarded door. **Fix:** apply a modest default
ceiling in `body_size_gate` for all non-exempt POST/PUT/PATCH (keeping the
packages streaming carve-out) and pass `max_num_fields` in `ui._form`.

## Major — b-roll

### BROLL-1 — sprite cell height is re-derived in the browser from source dimensions, misaligning 95.3% of sheets [verified — hunter measured the live archive]
`static/app.js:714-716` (`positionSprite`) uses `Math.round(240 *
height/width)` from `videos.width/height` (the **source**); the generator
builds the sheet from the 540p **proxy** with ffmpeg `scale=…:-2`
(`indexer/broll_index/ffmpeg_tools.py:282`, `:158`), whose `-2` rounds each
scale step to an even number — so the real cell height is
`even(round(240 * proxy_h/proxy_w))`, and there is no CSS `background-size` to
absorb the drift. **Measured across 7,117 live sheets: 6,783 (95.3%) have a JS
cell height 1px short of the generator's** (1920×1080 → JS 135, sheet 136); on
a 24-row sheet the overlay lands ~17% off and shows a splice of two rows. 31
are worse (id 894 portrait: 426 vs 428). **Fix:** persist sheet geometry (cell
w/h, or proxy dims) at generation time and serve it on the video row instead of
re-deriving from source dims.

### BROLL-2 — the 8-minute fix regressed 95 legacy uncapped sheets [verified — hunter measured]
`static/app.js:697-702` (`spriteInterval`), pinned by
`tests/test_sprite_geometry.py`. `SPRITE_MAX_CELLS` was added to `build_sprite`
after part of the archive was already sprited at a flat 2 s interval;
`positionSprite` now applies the cap unconditionally and nothing regenerates
old sheets (they carry no version marker). **Measured: 6,991 sheets match the
capped model, 95 match only the uncapped model — all of them clips over 8
minutes** (of 492 such), 31 match neither. id 11 (58:47): a hit at 30:00 is
computed as cell 122 → the frame at 4:04. Every legacy long clip now shows a
frame from its first ~8 minutes — the mirror of the bug commit `64134c2` fixed.
**Fix:** read real geometry (BROLL-1) or re-run `build_sprite` for every clip
gated on a recorded sprite-format version.

### BROLL-3 — clicking a tree folder never clears the crumb-derived `state.path`, a reachable zero-result dead end [verified]
`static/app.js:531-548` (`selectFolder`), `:300-302` (`wireFolderClear`).
`state.path` (set only by detail-panel crumbs) and `state.collection`/`category`
(set only by the tree/dropdown) are independent filters ANDed together in
`runSearch`, but only `renderResultsMeta`'s own "clear folder" link resets
`path`. The tree's "clear" calls `selectFolder("", "")`, leaving `path` intact.
**Failure:** open an `ff4` clip → click the "Erosion" crumb → click the
Downloads root in the tree → `collection=downloads` AND `path=ff4::Erosion` are
mutually exclusive → 0 results, and the tree's "clear" button cannot escape it.
**Fix:** clear `state.path` in `selectFolder` (and the category `<select>`
handler).

### BROLL-4 — the serial pipeline runs full Whisper on clips `probe` just discarded for length [verified]
`indexer/broll_index/pipeline.py:483`, `:499-502`, `:544-545`; over-length gate
at `:123-134`. `transcribe` has no `STAGE_PREREQ_STATUS` entry, so it runs
whatever the row's status is — including `'skipped'`, which `stage_probe` just
set for an over-cap clip — and `_process_video` calls `stage_transcribe`
**without** `ingest_only=True`, so with no `.srt` on disk it does a real Whisper
run. `parallel_local.py:72` was fixed for exactly this; the serial path was
not. **Failure:** `broll-index run` over `ff4`: a 3-hour A-cam take is probed,
marked `skipped` by the 300 s cap, and transcribed end-to-end anyway — the
waste `config.queue.yaml:88-93` documents. **Fix:** skip `transcribe` when the
row is `skipped` for the duration cap (audio-only `skipped` must still
transcribe), and pass `ingest_only=True` from `_process_video`.

### BROLL-5 — an `index: false` share can never get a transcript [analysis]
`indexer/broll_index/pipeline.py:58` (`STAGE_ORDER = [probe, proxy, frames,
transcribe, claude, embed]`), `:504-514`. `frames` sits before `transcribe`,
and the `index: false` branch does `update_video(status=ORGANISED)` then
`return` — abandoning the loop before `transcribe`/`embed`. So `index: false`
silently implies `transcribe: false` regardless of the share's own flag.
**Failure:** a share with `index: false, transcribe: true` (a legitimate combo
the config treats as independent axes) gets probe → proxy → organised, never a
transcript. **Fix:** order `transcribe` before `frames`, or `continue` past the
remaining status-gated stages instead of `return`ing.

### BROLL-6 — `build_archive` records no `archive_path` when the generated proxy is also the top slot [analysis]
`indexer/build_archive.py:330-331`, `:368-369`. For an `originals` share with
no `original_path`, `archive_source` falls back to `proxies/{id}.mp4`, which
equals `preview`, so no `Proxy/` copy is planned and the clip is excluded from
`write_paths`; `_proxy_path` then falls back to a `proxies/` dir `build_archive`
never ships, and the file lands outside `Proxy/` so lane B never syncs it.
Latent today (all rows have `original_path`); fires the first time
`build_archive` runs on a share before `origins` has resolved it, or with the
originals drive unmounted. **Fix:** always plan the `Proxy/` preview copy even
when it is the same file as the top slot, or record `archive_path` from the top
slot when no preview entry exists.

### BROLL-7 — `eligible()` admits `status='proxied'`, whose Downloads `category` is NULL, and files clips twice [analysis]
`indexer/build_archive.py:253-274` (docstring claims "additive and idempotent")
vs `:159` (`f"{DOWNLOADS}/{video['category'] or UNCATEGORISED}"`). Idempotence
holds only for `source: proxies` shares; for a Downloads share the destination
depends on `videos.category`, NULL at `proxied`. The script never deletes, so
the first placement is stranded and `dedupe`'s name claims shift once the clip
moves. Latent today (all `proxied` rows are a creators share). **Fix:** exclude
Downloads-share rows with a NULL `category` from `eligible()`, or key Downloads
placement on something that doesn't change after the model pass.

## Major — music

### MUSIC-1 — suffix byte ranges (`bytes=-N`) are served as `bytes=0-N` [verified]
`web/musicweb/routes_media.py:88-91`: `re.match(r'bytes=(\d*)-(\d*)')` treats an
empty first group as "start at 0" instead of RFC 7233's suffix-range ("the last
N bytes"). `bytes=-500` yields `start=0, end=500`. **Failure:** a client probing
the tail of an mp3 (ID3v1/Xing/LAME) or an m4a `moov` atom with `Range:
bytes=-128` gets the **first** 129 bytes, labelled `Content-Range: bytes
0-128/size`, and reports a wrong duration or refuses to seek. `test_media_range`
never covers the suffix form. **Fix:** when group(1) is empty and group(2) is
present, `start = max(0, size - int(group(2)))`, `end = size - 1`. (Same site:
an unparseable `Range` falls through to a 206 over the whole entity, and an
inverted range 416s where RFC says ignore-and-200 — fold both into the fix.)

### MUSIC-2 — `/api/reveal` shells the path through `cmd.exe`, allowing command injection [verified]
`web/musicweb/routes_ingest.py:353-356`: `os.spawnl(P_NOWAIT, COMSPEC, 'cmd',
'/c', 'explorer', f'/select,{path}')` hands an unquoted absolute path to
`cmd.exe`, which re-parses shell metacharacters. `db.safe_upload_name` strips
`<>:"/\|?*` but **not** `&`. **Failure:** a library file `x&calc.mp3` turns a
logged-in user's "reveal" click into arbitrary local command execution;
`rock&roll.mp3` splits and opens Explorer on the wrong path. Limited to
`os.name == 'nt'` (the base rig running the app standalone; the NAS container
returns `ok: False` and never spawns). **Fix:** drop `cmd.exe` —
`subprocess.Popen(['explorer', f'/select,{path}'])` passes the argument with no
shell re-parse.

### MUSIC-3 — the queued-ingest handoff has no way back to the base rig [verified]
`indexer/index_music.py:339` and `web/DEPLOY.md:166-174`. The container writes
`pending` rows into `/music-data/music.db` on the NAS; `index_music.py --queue`
calls `db.connect()` with no argument, draining `config.DB_PATH` — the in-repo
`music/web/data/music.db` on the base rig. There is no `--db`/`--data-root`
flag (argparse has `--root` for the share, not the DB) and no documented
pull-down, so the two halves never meet. **Failure:** an editor's queued cue
lands a `pending` row on the NAS; a base-rig `--queue` prints "nothing to
analyse"; the next `--music-data db` push overwrites the NAS db and discards the
row. **Fix:** add a `--db`/`--data-root` argument and document the
pull-drain-push loop, or have the queued path record enough for a plain sweep to
close the row.

## Major — ops / server / installer

### OPS-1 — `ship.cmd` never runs the companion or dashboard test suites, on a false premise in its own comments [verified]
`tools/ship.ps1:158-159` justifies running only `server/` + `onboarding/` with
"release.ps1 (step 2) runs the companion and dashboard suites" — but step 2
(`ship.ps1:267-268`) invokes `installer\build_editor_package.ps1 -RebuildExe
-RebuildOnboard -Publish -MakeCurrent`, which runs PyInstaller directly and no
tests (its own comment at `build_editor_package.ps1:192-194` says so, and stamps
`tests_run=false`). **THE ship command builds and publishes a companion to the
whole fleet as CURRENT with the companion suite never executed.** Secondary: the
ship path also skips `release.ps1`'s `pip install -e .[dev,tray]`, whose absence
lets `build.spec`'s import probe silently drop the tray from the bundle.
**Fix:** have ship step 2 go through `tools\release.ps1` (build + tests +
manifest) and let `build_editor_package.ps1 -Publish` publish that artifact, or
add the companion/dashboard suites to ship's step 0.

### OPS-2 — a deploy that fails after the `app` swap can, two runs later, delete the live dashboard's code [verified]
`server/install_dashboard_app.py:1327-1331` (prune) with `:1687-1754` (steps
2b–2d `return 1` before step 3's restart). `install_tree` swaps `app` →
`app.old.<ts>` and prunes all but the newest backup; the running container
keeps serving the **inode** it bind-mounted (the previous run's `app.old.<ts>`).
**Failure:** deploy A succeeds; deploy B swaps `app`, fails in step 2d (music
data, 1.4 GB over SFTP — the newest, least-proven step) and returns 1, leaving
the container on `app.old.T_B`; deploy C swaps again and its prune `rm -rf`s
`app.old.T_B` — the directory the live dashboard is reading templates and
static from — and the fleet dashboard 500s on every page. **Fix:** restart the
container immediately after a successful `app` swap (or before any following
`return 1`), and/or make the prune skip any `.old.*` still bind-mounted.

### OPS-3 — the 1.4 GB music trees are staged, verified and swapped under the default 120 s SSH channel timeout [verified]
`server/install_dashboard_app.py:1287`, `:1307-1310` (no `timeout=`),
`:1195-1202`, `:1226-1243`, against `server/common.py:479` (`run_ssh` default
`timeout=120`). `install_tree` was written for the ~1 MB dashboard tree; steps
2c/2d push it 906 MB of proxies + 505 MB of encoder through the same code with
no override, while the ffmpeg paths in the same file deliberately pass
`timeout=300`/`600` for a 42 MB job. The verify (`find … -exec cat {} + | wc
-c`) reads the whole tree twice and the swap `cp -a`s it — all silent until
finished, and paramiko's channel timeout is an *inactivity* timeout.
**Failure:** first install on a fresh host (or `--music-data all`): `cp -a` +
`chown -R` + re-read of 906 MB exceeds 120 s, `run_ssh` raises an unhandled
`socket.timeout`, `main()` dies with a traceback, the container is never
restarted (so the freshly swapped `app` is not picked up), and it repeats
deterministically — also the precondition for OPS-2. **Fix:** give
`install_tree` a size-derived (or large explicit) timeout and catch transport
exceptions around the swap.

### OPS-4 — `windows_upgrade.ps1` exits 0 after failing to install the new build, so ship prints "ship complete" [verified]
`installer/windows_upgrade.ps1:140-165`, `:320-336` (no `exit` at end of file),
consumed by `ship.ps1:326-332`. When all five copy attempts fail the script
sets `$copySucceeded = $false`, prints "Upgrade INCOMPLETE", relaunches the
**old** exe, and falls off the end — implicit exit 0. `ship.ps1` gates only on
`$LASTEXITCODE`, so it proceeds to "ship complete. Editors' trays will offer
v<X>". Same exit-code-vs-warning root cause as B23. **Failure:** AV holds a
handle on the installed exe for >10 s → ship publishes the new build fleet-wide,
fails to install it locally, relaunches the previous companion, and reports
success — the base rig back in the "verified against a build nobody was
running" state the drift check exists to prevent (and `check_deploy_drift.ps1`
always exits 0 by design). **Fix:** `exit 1` when `$copySucceeded` is false, and
have ship treat it as a hard stop.

### OPS-5 — `--music-data auto` re-pushes and overwrites the live `music.db` on every deploy [verified — mechanism]
`server/install_dashboard_app.py:601-606` (`music_components_present`), with
`:1566-1568` (music-data owned `3000:3000` mode `770`), `:579`. The presence
probe runs **unprivileged** (`run_ssh(probe)`, no `sudo`), unlike every other
FS action; the `db` target is inside a `770` directory `TRUENAS_USER` cannot
traverse, so `[ -e … ]` is false and the probe reports `db no` every time.
Routine `ship.cmd` (default `--music-data auto`) therefore re-uploads the index
on every ship and swaps it over the live one — silently replacing any
container-written `pending`-ingest rows (the rows MUSIC-3's queue is about) with
the base rig's copy, and leaving a never-pruned `music.db.old.<ts>` each time.
The masking `|| echo x` in the probe also turns a permission error on the two
trees into "present", skipping a push that was needed. **Fix:** run the probe
under `sudo -S` like every other check, and drop the `|| echo x` so an
unreadable path counts as absent.

---

## Minor / low

Grouped by component. These are real but lower-stakes — display glitches,
narrow-window races, resource waste, latent-until-a-precondition footguns.

**Companion sync core:**
- **SYNC-9** [analysis] `_pid_is_alive` uses `os.kill(pid, 0)` with no platform
  guard (`app.py:158-169`); on win32 that is `TerminateProcess`, and dead pids
  return True (wrong both ways). Reachable only via the CreateMutexW-unavailable
  fallback, which a frozen build essentially never hits. Fix: branch on
  `sys.platform` (`OpenProcess`+`GetExitCodeProcess` on win32).
- **SYNC-10** [analysis] `RcloneRunTally` counts every `--stats` tick as a
  transferred **and** deleted file (`rclone_lane.py:1329-1341`, fed
  unconditionally at `:2429`): the stats record's `msg` contains
  `Deleted: N (files)`, so `"Deleted" in msg` is true each tick; `--backup-dir`
  "Moved into backup dir" lines also land as completions. A lane B pass that
  trashes 12 proxies over 10 min reports `deleted ≈ 300`. Fix: skip
  stats-keyed records before the per-file matcher; treat backup moves as
  deletes.
- **SYNC-11** [analysis] rclone `critical`-level records never reach
  `result.errors` (`rclone_lane.py:1323-1328` records only `level == "error"`),
  so the `Failed to create file system for …` shape (old item 14) leaves
  `errors` empty; `_most_informative_error([])` returns `""` and
  `_is_max_delete_abort` goes blind. Fix: treat `critical`/`fatal` as errors.
  (The NOTICE filter being inert under `--use-json-log` is **not** a bug — old
  item 14 scopes it to `_run_lsf` deliberately.)
- **SYNC-12** [verified] consolidate reports "Copy & upload finished"
  immediately after reporting failures (`app.py:1722-1741` — the `if failures:`
  branch has no `return`, unlike the `elif should_stop()` below it). Fix:
  `return` at the end of the failures branch.
- **SYNC-13** [analysis] "Remove project from this machine" claims the folder
  was already gone when the drive is merely unplugged (`app.py:2202-2203`; no
  `_root_absent` check) — the multi-GB folder stays on the unplugged SSD, now
  unticked and unshared so nothing reclaims it, while the editor believes the
  space was freed. Fix: refuse early when `_root_absent`.
- **SYNC-14** [analysis] `project_roots_result()` labels an arbitrarily stale
  mapping `"live"` after a failed refresh (`selection.py:349-365`): a failed
  `fetch()` leaves `_last_response` untouched and the next line returns it
  tagged `"live"`, so the base rig files media under a superseded root with full
  confidence when the dashboard is down. Fix: return `"cache"`/`"unreachable"`
  when the refresh failed.
- **SYNC-15** [analysis] `shutdown_guard.stop()` orphans the pump thread when
  the window has not come up yet (`shutdown_guard.py:597-617`): `_hwnd`/`_thread`
  are cleared unconditionally but `WM_CLOSE` is posted only `if hwnd`, so a
  `stop()` after the 5 s `_ready.wait` gives up leaves a permanent
  `ccsync-shutdown-guard` thread and a live window; the next `start()` builds a
  second pump. Fix: keep the references until the join succeeds.
- **SYNC-16** [analysis] the keep-awake 8-hour hold ceiling is global, not
  per-lane (`shutdown_guard.py:445`): one churning lane stands the ceiling down
  for a genuinely healthy transfer, so a real 200 GB lane A ingest can
  idle-sleep mid-upload. Fix: track the hold clock per lane.

**Companion UI / Resolve:**
- **UI-4** [verified] the pulse loop's falling-edge icon write skips the
  menu-open guard (`tray.py:2037-2048`: the `if not pulsing:` branch NIM_MODIFYs
  `icon.icon` with no `guard.is_open()` check, contradicting the docstring at
  `:2026-2029`) — a ~375 ms one-shot window for the 2026-07-26 hover-hang. Fix:
  hoist the guard over both branches.
- **UI-5** [verified] consolidate's progress bar credits bytes for copies that
  failed or were skipped (`consolidate.py:463`, `batch_done += size`
  unconditional) — `popup.py:493-500` is the deliberately-fixed twin, pinned by
  a test. Display only. Fix: gate on `outcome.get("ok")`.

**Companion media pipeline:**
- **MED-5** [verified — hunter reproduced] a non-string `share` or `rel_path`
  crashes the 8899 handler with no response and no log line
  (`broll_server.py:277-285` `translate_path` assumes strings;
  `AttributeError`/`TypeError` escape to `socketserver.handle_error`, which
  writes to `sys.stderr` = None in the windowed build). Fix: coerce/validate to
  `str` (400 otherwise) and wrap `do_POST`/`do_GET` dispatch in a logging try.
- **MED-6** [verified] "Make the missing proxies now" does not clear the
  failure cap (`proxy_gen.py:583-590` `request_run` leaves `_failures` intact;
  `scan_once` filters capped clips at `:750`) — after the 0.6.1 mass-cap the one
  user-facing retry does nothing. Fix: clear `_failures` in `request_run()`.
- **MED-7** [analysis] BPG is launched while paused and while the config is
  broken (`proxy_gen.py:683-699` `_maybe_launch_bpg` gates only on
  `queue_empty and state != STATE_RUNNING`, never PAUSED/MISCONFIGURED/
  DRIVE_ABSENT) — a paused base rig still spawns `Resolve.exe -pg`, which this
  module never stops. Fix: gate on an explicit allow-list of states.
- **MED-8** [analysis] the BPG gate spawns an idle probe on every tick on every
  machine (`proxy_gen.py:693-697`: `user_away=self._user_is_away()` is evaluated
  eagerly; `self._bpg` is never None so the early return never fires) — every
  Mac editor forks `ioreg` every 15 s (~5,700/day) for a value BPG discards
  (BPG is Windows-only). Fix: return early when `not self._bpg.enabled`; make
  `user_away` a lazily-called callable.
- **MED-9** [analysis] `is_bpg_running` shells out to PowerShell+CIM every 15 s
  when BPG was started by hand (`bpg.py:93-105`, `:178`: the short-circuit only
  covers *our* child; the cooldown is checked after the probe). Fix: TTL-cache
  the CIM lookup (the `resolve_bridge._PROBE_TTL_SECONDS` precedent).
- **MED-10** [analysis] the 8899 `Content-Length` is trusted
  (`broll_server.py:402-403`, `:431-432`): a non-numeric value crashes the
  handler, an oversized one blocks a daemon thread on an unbounded buffered read
  — no cap, unlike `/api/v1/report` (B15). CORS is `*` + private-network. Fix:
  try/except the parse, cap at a few hundred KB, read in bounded chunks.
- **MED-11** [analysis] the music route's containment check is skipped whenever
  the mount came from the `/Volumes` probe (`music_server.py:131-141`, guard
  runs only `if root:` and `root = mounts.get(share)` is None for a probed
  mount) — a Mac editor with `/Volumes/music` mounted but no config entry (the
  documented case) gets component validation only, so a symlink out of the
  volume is followed. Fix: have `translate_path` return the root it used so the
  check always has one.
- **MED-12** [analysis, low] `scale=-2:'min(H,ih)'` guards width to even but
  passes height through unrounded (`ffmpeg_tools.py:524`, `:590`) — an
  odd-height non-4:2:0 source (RGB/4:4:4 screen capture, ffv1/utvideo) fails at
  encoder init and is capped. Fix: `trunc(min(H\,ih)/2)*2` in both builders
  (indexer needs parity).
- **MED-13** [analysis] `_run_ffmpeg` can raise "deque mutated during
  iteration" (`proxy_gen.py:980-985`: `reader.join(timeout=5.0)` may time out,
  then `"\n".join(lines)` iterates the deque the reader is still appending to),
  breaking `encode_once`'s documented never-raise contract when `_kill` fails to
  reap the child. Fix: snapshot with `list(lines)` inside a try.

**Dashboard:**
- **DASH-4** [verified] the parent app publishes `/docs`, `/redoc`,
  `/openapi.json` to every logged-in editor (`app.py:104`, default docs URLs)
  while both mounts 404 theirs — full route inventory and admin request schemas
  disclosed to any session (authz still holds at each route, so disclosure not
  bypass). Fix: `FastAPI(..., docs_url=None, redoc_url=None, openapi_url=None)`
  and add the parity test.
- **DASH-5** [verified] a non-ASCII token header 500s instead of 401ing
  (`api.py:69-78` `token_ok`; `broll.py:124` `BrollGate`): Starlette decodes
  headers latin-1 and `hmac.compare_digest` raises `TypeError` on a byte ≥ 0x80.
  Turns an unauthenticated `/api/v1/health` with a junk `X-CCSync-Token` into a
  traceback + log-spam. Fix: compare on bytes, or `except TypeError: return
  False`.
- **DASH-6** [verified] `_run_enforce` rebinds `devices` inside the shared-asset
  branch (`collector.py:719` vs `:812`: `for devices in
  editor_devices.values()` shadows the pass-wide list with a `set[str]`) —
  harmless today (nothing reads it after), a footgun the moment anything does.
  Fix: rename the loop variable.
- **DASH-7** [verified] first-cycle empty `myID` is not actually handled in the
  config pass (`collector.py:645-694`: the comment says it keeps the last known
  id, but `self._my_id` is `""` on the first cycle) — every device is upserted
  `is_server=0`, so the NAS shows as a phantom editor row until the next good
  cycle. `_run_enforce` guards this correctly (`:712-717`); `_run_config` does
  not. Fix: mirror the enforce guard.
- **DASH-8** [verified] the collector thread's `db.connect`+`db.migrate` sit
  outside its `try`/`finally` (`collector.py:145-148`) — a `database is locked`
  during the app's concurrent startup migration kills the thread and leaks the
  connection, and nothing restarts it, so `db.prune` never runs for the process
  lifetime (eight tables grow unbounded, `syncthing_reachable` goes false and
  masks the real cause). Fix: move connect+migrate inside a retrying try.
- **DASH-9** [analysis] the bare `/music` → `/music/` redirect that CLAUDE.md
  calls load-bearing is **not pinned by any dashboard test**
  (`tests/test_music_mount.py` only exercises `/music/`). Not a bug today (the
  redirect works), but a silent regression risk. Fix: add the bare-path test.

**B-roll (minor):**
- **BROLL-8** [verified] `runSearch` has no request-sequence guard
  (`static/app.js:554-585`): a slow semantic response can overwrite a newer one,
  showing unfiltered results while the sidebar highlights a folder. Fix: a
  monotonic token, or `AbortController`.
- **BROLL-9** [analysis] `build_shoot_clause` matches loosely
  (`web/app/search.py:354-371` vs `routes_api.py:115-170`): the shoot tree
  counts by exact `rel_path` components but clicking sends a `LIKE 'A%B%C%'`
  contains-in-order match (and escapes `%` but not `_`/`\`), so counts disagree
  with what a click returns. Fix: reuse `build_path_clause`'s directory-boundary
  matching.
- **BROLL-10** [verified] `/api/tree`'s Downloads root total counts only
  `status='indexed'` (`routes_api.py:208-212` vs `search.py:931` `_browse`,
  which excludes only skipped/excluded/duplicate) — the root reads N and
  clicking it returns N + the discovered/probed/proxied/error rows. Fix: use
  `_browse`'s predicate for the root total.
- **BROLL-11** [verified] `renderResultsMeta` names the query and `path` but
  never `category`/`collection` (`static/app.js:1110-1125`) — clicking a
  category crumb filters the grid while the line reads "browsing all videos"
  and no tree node is active. Fix: include the active category/collection.
- **BROLL-12** [verified] `jumpToSearch` from a category crumb keeps the
  previous query (`static/app.js:1068-1076` vs the path/theme closures at
  `:1035`/`:1088`, which reset `state.q`) — search "ambulance", open a result,
  click its category → the grid shows "ambulance" ∩ category, nearly empty, with
  no cue why. Fix: clear `state.q`/`#q-input` in the category closure.
- **BROLL-13** [verified] re-ingesting a video orphans its segment embeddings
  (`web/app/routes_ingest.py:88-113`; `embeddings` has `ON DELETE CASCADE` only
  on `video_id`, `schema.sql:151-159`) — semantic search returns hits for dead
  `source_id`s that `search_videos` silently drops, consuming the
  `SEMANTIC_ONLY_MAX_VIDEOS=5` budget so the clip's real content is unreachable
  until `stage_embed` reruns. Fix: delete `embeddings WHERE source='segment' AND
  video_id=?` in the same transaction.
- **BROLL-14** [verified] audio-only `skipped` clips are transcript-searchable
  but excluded from the archive build (`pipeline.py:108-114` vs
  `build_archive.py:267-271`) — they surface as "no preview" cards whose
  `/media/proxy/{id}.mp4` 404s (3 live rows have transcript cues). Fix: include
  audio-only `skipped` rows in `eligible()`, or apply browse's status filter to
  search.
- **BROLL-15** [analysis] `batch_transcribe.py` documents "run it before the
  local stages" but filters `status != 'skipped'`, which only exists after
  probe (`batch_transcribe.py:9-11`, `:90-94`; `config.queue.yaml:88-93` states
  the opposite) — following the docstring transcribes every multi-hour take on
  the way to discarding it. Fix: exclude `status='discovered'` and correct the
  docstring.
- **BROLL-16** [analysis, low] `is_excluded_dir` is case-sensitive
  (`fnmatch.fnmatchcase`) on a case-insensitive FS (`scanner.py:63`) — a folder
  renamed `Erosion/YouTube` stops matching the `Erosion/Youtube` exclude and the
  whole tree is re-indexed as a second copy. Fix: `fnmatch.fnmatch` or lowercase
  both sides.
- **BROLL-17** [analysis, low] the semantic-matrix and fuzzy-vocabulary caches
  are keyed on row **count** (`web/app/semantic.py:130-162`,
  `fuzzy.py:106-123`) — a re-index that replaces a clip's segments with the same
  number of rows serves stale vectors until an unrelated count change evicts
  them. Fix: add `MAX(id)` or `PRAGMA data_version` to the key.

**Music (minor):**
- **MUSIC-4** [verified] `loadPeaks` ignores the HTTP status and renders the
  error body as a waveform (`static/app.js:72-78`; a 404 JSON `{"detail": ...}`
  becomes the peak array, and is cached). Fix: `if (!r.ok) return new
  Uint8Array(0)` before reading, and don't cache the failure.
- **MUSIC-5** [verified] searching/filtering while a preview plays orphans the
  audio (`static/app.js:313-330`: `render()` wipes `#list` and nulls
  `state.playing` without `closePane()`/pausing `#audio`, which lives outside
  `#list` and has no `controls`) — playback continues with no transport. Fix:
  `closePane()` at the top of `render()`, and pause `#audio` there.
- **MUSIC-6** [verified] the ONNX encoder's lock guards the thread-safe half,
  not the unsafe half (`web/musicweb/text_encoder.py:266-275`:
  `tokenizer.encode_batch` — the non-thread-safe BPE cache the comment names —
  is outside the lock, and only `session.run` is inside it). Benign under
  CPython's GIL, unsafe under free-threaded builds, and needlessly serialises
  every query through the 30 ms forward pass. Fix: move `encode_batch` inside
  the lock (or make the cache write the only locked region).
- **MUSIC-7** [verified] `pool='mean'` returns `[]` when the `windows` table is
  empty (`web/musicweb/search.py:86`: the `win_mat.size == 0` guard covers both
  modes, but the `mean` branch reads only `track_mat`) — a DB with track
  embeddings but no window rows answers every whole-track search with an empty
  result the UI shows as a genuine miss. Fix: move the guard into the max-pool
  branch and add `if self.track_mat.size == 0: return []` for mean.
- **MUSIC-8** [verified] the player's transport controls are wired only after
  the peaks fetch resolves (`static/app.js:173`, then `:187-192`; the pane is in
  the DOM and animating from `:167`) — first open over Tailscale leaves pause
  and seek dead for the peaks round-trip (seconds on the ffmpeg-rebuild path).
  Fix: assign the handlers before the `await`.
- **MUSIC-9** [analysis] search/similar/filter responses can land out of order
  and overwrite each other (`static/app.js:344-370`, no request token). Fix: a
  monotonic `state.seq` captured before each fetch.
- **MUSIC-10** [analysis] `Index.reload()` mutates a live shared object
  statement-by-statement (`web/musicweb/search.py:17-34`, `:139-146`; only
  construction is under `_index_lock`) — a concurrent `/api/similar` can read
  the new `sim_mat` against the old `pos` and return neighbours for a different
  track. Fix: build a fresh `Index` and swap the reference under the lock.
- **MUSIC-11** [analysis] two threads reaching `db.con()` first can both run the
  migrations (`web/musicweb/db.py:146-163`; `_schema_ready` is an unlocked
  global) — on the upgrade, the loser gets `duplicate column name` and 500s
  once. Fix: guard the check/set with a module lock.
- **MUSIC-12** [analysis] `make_proxies` aborts the whole run on a row with an
  unknown share (`indexer/make_proxies.py:44` catches only
  `PathTraversalError`; `resolve_path` also raises `UnknownShareError`, which
  `music_index.config` doesn't even re-export) — one NULL/foreign-share row
  kills the run before encoding anything. Fix: re-export `UnknownShareError` and
  catch both.
- **MUSIC-13** [verified] comments in two files claim the debias projection is
  applied to text queries; it is not, and the next comment explains why
  (`web/musicweb/search.py:20-23` and `projection.py:24-26` vs the measured
  `search.py:25-31`) — a live trap that would cost text retrieval 40%→20% top-10
  if someone "fixed" the apparent gap. Fix: rewrite both to say the projection
  is index-side and similarity-only.
- **MUSIC-14** [verified] the waveform paints bar 0 as "played" before playback
  starts (`static/app.js:97`, `:107`: `i <= played` with `played = floor(bars *
  progress)` marks index 0 at `progress === 0`) — a "→ Resolve" open shows one
  red bar, and the last bar never fills at `progress === 1`. Fix: `i < played`
  with `Math.round`.
- **MUSIC-15** [analysis, low] the ingest toast interpolates server strings into
  `innerHTML` (`static/app.js:471-491`, `:503`): `x.error` carries indexer
  `rel_path` and raw ffmpeg stderr, neither filtered by `safe_upload_name`. Not
  reachable on Windows/SMB today (`<` is illegal in a filename). Fix: build the
  toast with `textContent`/`el()`.

**Ops (minor):**
- **OPS-6** [verified] `run_all_tests.ps1` omits the `music/web` suite entirely
  and runs `server/` from PowerShell with no bash (`tools/run_all_tests.ps1:22-30`)
  — the 18 remote-script tests skip silently and the table prints PASS, and the
  `test_mounted_prefix.py` that pins music's document-relative URLs never runs.
  `ship.ps1` routes server through Git's bash; this wrapper does not. Fix: add
  music/web and route server through bash (or warn like ship does).
- **OPS-7** [verified] a failed PyInstaller run still restamps
  `ccsync-release.json` with the new version over the old exe
  (`build_editor_package.ps1:178-180` warn-only; restamp `:195-228`
  unconditional; the sha is taken from the same stale file, so the publish
  provenance cross-check passes). Fix: skip the restamp (and `Set-Failed`) when
  PyInstaller's exit code is non-zero.
- **OPS-8** [verified] music data is staged in the NAS's `/tmp`
  (`install_dashboard_app.py:1136-1148`) and deliberately left on failure
  (`:1296`, `:1315`) — ~1.4 GB per failed attempt in a possibly RAM-backed
  `/tmp`, so a repeated OPS-3 failure can ENOSPC unrelated NAS services. Fix:
  stage the large music components under the host root (same pool), and/or prune
  orphaned `/tmp/ccsync-music*-upload.*` at start.
- **OPS-9** [verified] the documented macOS wizard publish command stages
  without making current (`CLAUDE.md:141` and `ship.ps1:306` say
  `build_onboard_macos.sh --publish`, which uploads STAGED — `MC=0`,
  `build_onboard_macos.sh:416-443`; `build_editor_package.ps1`'s own advisory
  correctly says `--publish --make-current`). Whoever is on the Mac follows
  CLAUDE.md and Mac editors keep the old zip. Fix: add `--make-current` to
  CLAUDE.md:141 and ship.ps1's advisory.
- **OPS-10** [analysis] ship's post-deploy health gate is a fixed 8 s sleep +
  one check + `exit 1` on miss (`ship.ps1:244-258`) — a restart that takes 10 s
  (venv revalidation, cold pool; compose allows a 120 s `start_period`) reads a
  good deploy as failed and aborts before the companion publish. Fix: poll
  `/api/v1/health` for ~60–90 s instead of one shot.

---

## Carryover — still open from the pre-2026-08-11 ledger

These predate this hunt and are not re-derived above; the full write-ups are in
`docs/bug-hunt-2026-08.md` and `docs/macos-first-run-2026-08-05.md`.

- **Proxy generator, live-attach proof (was item 23) — SHIP-BLOCKER for the
  editor proxy rollout.** The generated proxy's timecode / `LinkProxyMedia`
  attach is still UNVERIFIED against a real Resolve. 0.6.2/0.6.3 proved the
  encode half only as far as "ffmpeg accepts the argv"; the four-point proof
  (HEVC Main-10 + `hvc1` + source timecode; Resolve adjacent-`Proxy/` auto-link;
  `LinkProxyMedia` over a stale absolute proxy path; byte-flag parity with the
  b-roll indexer's `build_proxy`) has not been run on the base rig. Until it is,
  the feature stays base-rig-only by the derived default. **MED-1 and MED-4
  above are the kind of gap this proof exists to catch.**
- **Lane B can sweep an editor-generated proxy into `.ccsync-trash` (was item
  22) — tracked risk, mitigated by the tri-state derived `proxy_gen_enabled`
  default.** Revisit only if editor-side generation for synced projects is ever
  wanted (needs a lane A rule change).
- **AppleDouble sweep (was item 12 residual).** The `._*` exclude rule is fixed
  in both lane builders and the express predicate, but the NAS tree predates it:
  a one-time sweep for already-uploaded `._*` sidecars is still owed.
- **macOS code-signing (was item 16).** The companion is ad-hoc signed, so its
  Full Disk Access / TCC grant is a hash of the binary and does not survive a
  self-upgrade. The tray fallback that surfaces "macOS is blocking access to the
  sync volume" is shipped; a stable Developer ID identity (a purchase) is the
  real fix and remains open.
- **macOS runtime validation backlog.** `installer/MACOS_FIRST_RUN.md` §A7–H is
  unrun: the onedir wizard bundle (was item 9) has never been built on a Mac
  (dry-verified only); the re-guarded onboarding suite (was item 15) expects
  ~211 pass / 4 skip on darwin but needs one darwin run; lane C's
  `.stfolder`-marker behaviour is untested on the platform; MAC-12's wedged
  FSEvents stream on Leso's SAMDISK still needs someone at the machine
  (remount/reboot — the code-side probe is shipped).
- **Bench Syncthing 1.x (was item 1 residual).** The v1 argv is test-pinned to
  the previously-working shape but never live-verified (no 1.x binary here).
- **Mac builds owed.** The music "send to Resolve" endpoints (`/music/send`,
  `/music/status`) 404 on the deployed companion until the fleet is republished;
  the macOS companion and wizard both need a build on a Mac. (See OPS-9 — the
  documented publish command doesn't make it current.)
- **NAS hygiene (was item 7 incidental).** The `editors` group contains a
  machine-shaped account `alex_laptop` — a live cousin of B16; rename if it is a
  machine.
