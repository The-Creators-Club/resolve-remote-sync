# verdicts — companion

Verified against git HEAD 097f5a3, read-only. Probes run from
`companion/.venv/Scripts/python.exe` (CPython 3.12.10), scratch scripts in the
scratchpad. No Resolve connection, no `scriptapp`, no Tk on the main thread.

## comp-sync-1
- Verdict: CONFIRMED (high)
- Reasoning: `path_matches_lane_a_filter` (rclone_lane.py:1671) does exactly
  three things - video extension, no `Proxy` component, no `._` prefix - and its
  own docstring claims equivalence with `build_filter_rules_up()`, which since
  YT-3 also emits `YTDL_WORK_EXCLUDE_RULES` (:595). I looked for a second gate
  on the express side and there is none: `_express_partition` (:4889) mirrors
  only the 0-byte floor, the min-age and the in-flight-periodic scope, and
  `build_express_command` cannot carry a filter file. `extra_excludes_fn` is
  consulted only in `_build_command` (:2680), i.e. the periodic door. Express
  is on by default (`EXPRESS_DEFAULT_ENABLED = True`) and lane A is
  `copy --ignore-existing`, so the first landing is permanent. The reachability
  I checked that the hunter did not spell out: `ytdl_executor.destination_for`
  writes into `<Projects root>/<label>/Youtube/<term>`, inside the watched
  tree, and `.original.<ext>` is deliberately a KEPT file (upgrade note at
  ytdl_executor.py:1313/1585 - it is a whole real download, not scratch), so
  the thing express uploads permanently is a full-size duplicate of a clip the
  periodic pass refuses by design.
- Evidence: `path_matches_lane_a_filter` returns True for
  `clip.editready.mp4`, `clip.original.mov`, `vid.f137.mp4`, `a.temp.mp4`
  (False for `a.failed` only because `.failed` is not a video extension - the
  rule is not being enforced, the extension filter happens to cover that one).
  `LANE_A_MIN_AGE = 120s`, `EXPRESS_DEFAULT_ENABLED = True`.
- Fix note: the suggested fix is right and cheap for the ytdl half (a basename
  regex in the predicate). The file-moves half is the weaker of the two claims:
  a locally applied move generates a watchdog event at the NEW path, so the old
  path is only re-offered when something independently touches it, and the
  express-side `extra_excludes_fn(None)` consult the hunter proposes would call
  `recent_excludes(None)`, which returns `[]` today (see comp-sync-3 in the same
  report) - so that half of the fix needs comp-sync-3 fixed first or it is a
  no-op. Do the predicate now, the excludes consult with comp-sync-3.

## comp-sync-2
- Verdict: CONFIRMED (medium)
- Reasoning: `_cmp_key` (file_moves.py:113) is normcase+normpath plus a darwin
  `.lower()` and no Unicode folding. I traced both ends the hunter asserted:
  `old_local` is built in `apply_move` (:165) from `move["from_project_rel"]` /
  `move["from_rel"]`, i.e. the dashboard's NFC spelling, while the query in
  `watcher.py:341` is a path that came out of the Resolve project library, and
  `resolve_bridge._nfc` is applied only to media-pool BIN names (confirmed by
  the comp-resolve hunter and by grep). `recent_excludes` in this same file
  already emits both spellings for SYNC-11, which shows the module knows the
  hazard at one door and not the other.
- Evidence: `_cmp_key(NFC path) == _cmp_key(NFD path)` -> False for
  `Matej Šimalčík.mov`. `tests/test_file_moves.py` has no NFD case.
- Fix note: correct and safe - `_cmp_key` is comparison-only, which is exactly
  the case CLAUDE.md's CR-90 rule permits normalising. Note the consequence is
  the loss of the RES-10 one-click relink offer (the clip is still there under
  its new path, and the editor can relink by hand), Mac-only, accented-Latin
  names only; that is why I left it at medium rather than raising it.

## comp-core-1
- Verdict: CONFIRMED (high)
- Reasoning: I tried to find the client-side check and there is none.
  `_accept_offer` (upgrade.py:1227) runs `verify_offer`, the
  `_min_version_above_own` self-contradiction test and the downgrade floor;
  `download_and_verify` adds origin pinning, transport and size; `_apply_inner`
  renames whatever arrived over `sys.executable`. `grep '"kind"\|platform_key()
  \|arch_key()' upgrade.py` yields only the two definitions (:145, :729) and the
  `record_fields(info.get("kind"), info)` call in `parse_upgrade` (:1029) -
  canonicalised for verification, then discarded. `api._upgrade_info`
  (api.py:4728) is the sole enforcer and its own comment says why the check
  exists; that is the party the offline key was introduced to remove from the
  trust chain (release_pubkey.py:5-18).
- Evidence: source reads above; the onboard installer is published into the
  same `companion_packages` table by the same key, so a genuinely signed
  `kind="onboard"` record verifies against a companion's baked pubkey today.
- Fix note: the `kind`/`platform` half of the suggested fix is right and should
  land before `note_floor` as proposed. The `arch` half needs a decision, not
  just a patch: `release_pubkey.OPTIONAL_KIND_EXTRA_FIELDS`'s comment states
  deliberately that `arch`/`requires_dashboard` "are enforced by the DASHBOARD;
  a companion only has to canonicalise them", so adding a client arch test is a
  policy change (and must treat a missing `arch` and `universal2` as passing,
  or every pre-wave record is refused). Severity: the realistic impact is
  denial of service plus a wizard on the Run key, not arbitrary code - a
  compromised dashboard still cannot produce an unsigned build - but the
  invariant the module docstring states is false, so high stands.

## comp-core-2
- Verdict: CONFIRMED (medium)
- Reasoning: `supervisor.spawn_for` returns None on every non-win32 platform
  (:325) and its docstring justifies that with "macOS has launchd", while
  `installer/macos_bootstrap.sh:2366` writes the companion LaunchAgent with
  `RunAtLoad` and, with a comment saying so, no `KeepAlive` - and :2353 treats
  the PRESENCE of KeepAlive as a plist that must be rewritten. So the two files
  contradict each other and the Mac genuinely has no relaunch-after-abort net.
  `crash_report.start_supervisor` reports the gap at `log.debug` (:688), so no
  Mac log says the machine is unprotected. (The unrelated LaunchAgent at
  macos_bootstrap.sh:1847 does carry KeepAlive - it is not the companion's.)
- Evidence: the three sources above, read directly.
- Fix note: both halves of the suggestion are right, and the cheap one (fix the
  docstring, raise the line to INFO/WARNING on darwin) should land regardless.
  Porting the supervisor is more than the two ctypes helpers: `decide()` is
  platform-neutral, but the win32 exit-code tests (`DELIBERATE_EXIT_CODES`,
  0xFFFFFFFF for `Stop-Process`) are Windows semantics and need a POSIX
  equivalent, so do not treat it as a mechanical port.

## comp-core-3
- Verdict: CONFIRMED (medium)
- Reasoning: the mechanism is exactly as described - `fixer.list_project_dirs`
  unions a walked `rel.as_posix()` (macOS listdir, NFD in the case CR-90
  measured live) with `extra_rels` from the dashboard (NFC), guarded only by
  `is_dir()`, which succeeds on APFS/HFS+ for either spelling; `manifest.py:157`
  then tests `project_rel in selected_rels` as an exact string. I chased the
  one refutation that would have killed it - a dashboard-side collapse - and it
  makes the finding WORSE, not better: `_slug_for_rel` (api.py:7960) looks the
  rel up as a `projects.label` (NFC, so the NFD spelling misses) and falls back
  to `provision.slugify`, which splits on `[^a-z0-9]+`; NFC `Français` slugifies
  to `fran-ais` while NFD gives `franc-ais` (the combining mark leaves the bare
  `c` behind). Two distinct slugs, so `upsert_editor_media_project` writes two
  rows - a real project plus a phantom. `db.media_rel_key` is applied to
  per-file rels (db.py:6871, :6943) and to nothing on this path.
- Evidence: the slugify divergence above, computed from provision.py:103-107;
  no `unicodedata` import in manifest.py or fixer.py.
- Fix note: the suggested fix (fold both sides through `rclone_lane.nfc_key`
  for the union and the membership test, never for the walked path) is right.
  Caveat on the premise, which I cannot close from Windows: APFS is
  normalisation-PRESERVING, so the double only appears when the bytes on disk
  differ from the dashboard's spelling - which is what CR-90 measured on
  leso's Mac, so treat it as real but Mac-and-diacritic-only.

## comp-ui-1
- Verdict: CONFIRMED (high)
- Reasoning: tray.py:977 (`_install_youtube_cookies`) and tray.py:1088
  (`_show_youtube_terms_dialog`) build `tk.Tk()` directly on a `_spawn` worker
  thread and only `root.destroy()`. `install_tk_guard()` runs at ui_dispatch
  import (:1132) and pins every interpreter at birth, and the only two release
  paths are `dispatch()`'s reclaim and `release_root()` - neither is on these
  paths, and the worker thread then exits, so the record can never be freed.
  The docstring at :969 ("not one of this process's Tk roots") is falsified by
  the code six lines below it.
- Evidence: reproduced. A worker thread replicating tray.py:977 verbatim and
  then exiting leaves `ui_dispatch.pinned_records()` at 1 with the module's own
  ERROR line ("...is pinned for the life of the process... Held by: <none>");
  the same body wrapped in a `release_root()` finally adds none. Every existing
  test of both functions goes through the `picker=`/`confirm=` seam, so the Tk
  branch is untested.
- Fix note: the fix is right (dispatch + `release_root` in a `finally`, as
  `popup._tk_pick` does). One caution on the "take `_popup_active_lock` too"
  part: `_show_update_dialog` (tray.py:1115) takes that lock, so if the cookies
  picker is ever opened from a code path that already holds it the addition
  deadlocks - check the callers before adding it. The proposed AST guard in
  `test_tk_interpreter_hygiene.py` is the right regression pin. Severity: on
  Windows this is a bounded 1.8 MB-per-click leak plus a misleading ERROR; the
  sharp edge is macOS, where it builds a Tk-Aqua root off the main thread beside
  the dispatcher's own root - which is the CR-93 abort shape.

## comp-ui-2
- Verdict: DOWNGRADED to low
- Reasoning: the facts are all correct. `_build_menu` (tray.py:3244) renders
  ten rows with no Copy diagnostics, no Open log, no Scan whole project and no
  Advanced submenu; those buttons live in `settings_window.py` (:542, :591,
  :593), and nine strings in tray.py still say `Tray → Copy diagnostics for your
  admin.` plus `Advanced → Remove a project from this machine` (:484) and
  `Advanced → YouTube: use an exported cookies.txt…` (:951). I also found one
  the hunter missed: the disabled NOT SET UP row inside `_build_menu` itself
  says "(Copy diagnostics for your admin)". What I could not sustain is medium:
  the menu's tenth row is `Settings…`, the buttons are the first things inside
  it, and their labels are the exact words the copy uses, so an editor who
  right-clicks is one obvious click from the thing they were told to find. It
  is friction and a broken promise in the copy, not a dead end.
- Evidence: `_build_menu` read in full; `grep 'Tray → \|Advanced →' tray.py`
  gives the nine sites listed.
- Fix note: the suggested rewrite to the already-agreed `Tray > Settings >
  COPY DIAGNOSTICS FOR YOUR ADMIN` wording is right, and the scan test is worth
  more than the rewrite. Include the `_build_menu` disabled row and the
  out-of-territory sites in app.py/fixer.py/identity.py/resolve_journal.py/
  loopback_guard.py in the same sweep, or the test will fail on them.

## comp-resolve-1
- Verdict: CONFIRMED (high)
- Reasoning: `record()` (resolve_journal.py:399) holds `_lock` only inside
  `open_session`, then does an unlocked `_read` -> append -> `_write`, and
  `_write` uses a fixed `<file>.json.tmp`. The reachability question the hunter
  did not close, and which is the one that mattered: BOTH writers call
  `resolve_journal.record` OUTSIDE `_bridge_call` - replace_clip at
  resolve_bridge.py:2213 (after the `with` block closes) and link_proxy_media at
  :2310 - so `_API_LOCK` does not serialise them, and two threads really can be
  inside `record()` at once. The failure is silent: the `except` at :430 is
  `log.debug`.
- Evidence: reproduced with HOME redirected to a temp dir, 8 threads x 20
  `record()` calls into one project: **8 entries of 160 survived**, in a single
  session file. No test in the suite records concurrently.
- Fix note: right, and both halves are needed - the lock across the RMW and a
  unique tmp name (on Windows the shared tmp is a second, different failure).
  Raising the swallowed write failure above debug is worth doing: an entry that
  could not be journalled is an edit `undo_last_relink` will silently not undo,
  and today nothing at INFO says so.

## comp-resolve-2
- Verdict: CONFIRMED (medium)
- Reasoning: `link_proxy_media` catches its own exception and returns
  `{"ok": False, "message": _SCRIPTING_ERROR_MESSAGE}` (resolve_bridge.py:2303),
  so `apply_relinks`' `except Exception` arm (proxy_relink.py:385-392) - the one
  documented as "NOT a refusal" - is unreachable for the real `link_fn`, and a
  scripting error falls into the `else` that calls `note_refusal`. The
  refutation I tested: if Resolve has gone away, would `resolve_fn(op)` return
  None first and take the harmless `continue`? No - `resolve_media_pool_item`
  (:1970) returns `item["media_pool_item"]` when the dict already carries the
  object, and the ops come from the same pass's media-pool walk, so it hands
  back a live-but-now-dead handle without touching Resolve and the link call is
  what raises. `_REFUSALS` is process-lifetime and keyed on
  (clip, proxy) + the proxy's `(mtime, size)`, which never changes for a proxy
  that was fine, so the skip lasts until the tray restarts.
- Evidence: the four sources above, read directly; `tests/test_proxy_relink.py`
  never feeds `_SCRIPTING_ERROR_MESSAGE` through `apply_relinks`.
- Fix note: the message-comparison fix works but couples two modules on a copy
  string; the second suggestion (a machine-readable `"reason":
  "scripting_error" | "refused"` from `link_proxy_media`) is the right one, and
  the same distinction is wanted at resolve_bridge.py:2226 (replace_clip's
  all-attempts-raised return) if that ever grows a refusal memory.

## comp-broll-music-1
- Verdict: CONFIRMED (medium)
- Reasoning: `_save` (broll_ingest.py:697) builds the snapshot under
  `self._lock` but puts live references to `self._batch` and `self._staging`
  into it, then serialises OUTSIDE that lock with `indent=2`, which forces the
  pure-Python encoder. The mutators do add size-changing keys with no lock
  held: `_item_from_manifest` (:1627) pre-creates `outputs`/`uploads` but not
  `described`, and `_crunch_item` writes `item["described"] = True` and inserts
  into the nested `outputs` dict, all without `self._lock`. The existing
  mitigation (`_save_lock` + per-thread tmp name) serialises writers only, as
  the hunter says.
- Evidence: reproduced the encoder claim on this venv (3.12.10). A mutator
  thread adding new keys to nested dicts while the main thread dumps: with
  `indent=None` (C encoder) no error in 50 dumps; with `indent=2`,
  `RuntimeError('dictionary changed size during iteration')`. Note the race
  needs a net SIZE change at the moment the encoder resumes - my first attempt,
  which added and immediately removed a key, never fired, so this is rarer than
  the raw thread count suggests.
- Fix note: right. `copy.deepcopy` inside `self._lock` is the cleaner of the
  two options offered (dumping inside `self._lock` puts a multi-MB
  pure-Python encode on the lock every transition, which is what `_save_lock`
  was split out to avoid). Same shape exists in `music_ingest.py:242-345` and
  should be fixed with it.

## comp-broll-music-2
- Verdict: DOWNGRADED to low
- Reasoning: the mechanism is exactly as reported - `allowed_origins` is a
  frozenset built once in `BrollCompanionServer.__init__` (broll_server.py:1980)
  from config plus `site_mod.cached_site()`, `refresh_site` is kicked off on a
  background thread at app.py:7489 and `_start_broll_server` runs a few
  statements later in the same synchronous starter list, and there is no rebuild
  path. What holds it back from medium is the blast radius: it needs the site
  manifest's `dashboard_url` to have actually CHANGED (a re-provision or a
  moved Serve host) while the editor's config.toml still holds the old one, it
  costs one session because the very refresh that lost the race updates
  `site.json` on disk for the next start, and the 403 log line at :1201 names
  both the refused origin and the list held, which is the diagnosis. That is a
  narrow, self-healing, self-describing failure.
- Evidence: both sides read; `grep broll_server app.py` shows only start/stop,
  i.e. no reload seam.
- Fix note: of the two options, the cheap correct one is ordering - the refresh
  thread exists so a slow/unreachable dashboard cannot delay startup, so do not
  await it; instead have the handler read the allow-list through a small TTL'd
  accessor as suggested. If a TTL is added, keep the "read the file off a
  request thread" objection in the constructor's comment satisfied: cache the
  frozenset, not the file read.

## comp-broll-music-3
- Verdict: CONFIRMED (medium)
- Reasoning: GETs are exempt from `_post_authorised` by design and `_vet_request`
  only refuses a PRESENT, non-allow-listed Origin (`if origin:` at :1197), so a
  subresource load (`new Image().src=...`) with no Origin passes; `host_allowed`
  does not help, because such a request carries `Host: 127.0.0.1:8899`, which is
  the loopback it demands. `GET /music/status` then reaches `music_server.call`
  with the module default `TIMEOUT = 90`, and `call` is an unconditional
  `subprocess.run` of the frozen companion re-entered as a Resolve worker. I
  grepped for a semaphore, in-flight guard, cache or rate limit on that path and
  there is none, and the server is `ThreadingHTTPServer` with daemon threads.
  The b-roll `/status` route is the same shape at a 20 s timeout.
- Evidence: the dispatch chain read end to end (do_GET :1391 -> `_vet_request`
  -> `_dispatch_get` :1814); `music_server.call` :153-190.
- Fix note: the suggested memoise-and-serialise is right and is the whole fix -
  the answer really is a yes/no a settings dot draws. The `Sec-Fetch-*` belt is
  weaker than it looks (a same-origin fetch from the dashboard page is
  `Sec-Fetch-Mode: cors`, a top-level self-test navigation is `navigate`), so
  if it is added, allow-list explicitly rather than refusing `no-cors` alone,
  and keep the self-test URL working. No disclosure risk either way: no CORS
  header is emitted to the attacker.

## comp-ytdl-jobs-1
- Verdict: CONFIRMED (high)
- Reasoning: `JobRunner._heartbeat` (jobs_runner.py:509) calls `self._call` with
  no `try`, `_call` falls through to `broll_ingest.default_request`, whose
  docstring states plainly that transport failures RAISE (only HTTP statuses are
  answers). Inside `_run_child` that raise is caught by the catch-all at :884,
  which calls `_terminate(proc)` and returns a failure, and the caller posts it
  with `retryable=error != CANCELLED_ERROR`, i.e. True - so it counts an
  attempt and, per the dashboard's `fail_job`, cools the machine down. The
  module's own docstring ("miss ten in a row before it is treated as gone")
  describes a tolerance the code does not have. The two sibling implementations
  in this repo both got it right (`ytdl_executor.FleetClient._call` retries,
  `DownloadJob._heartbeat_loop` swallows anything but a 410), which is what
  makes this an omission rather than a design choice.
- Evidence: source chain above; every jobs test's `request_fn` returns a status
  and none raises, so the suite cannot see it.
- Fix note: right. Prefer the "return True on a raise" form over a bare retry:
  a heartbeat that cannot be delivered is not evidence the lease is gone, and
  the lease expiring is already the backstop. If a consecutive-failure counter
  is added, it must be larger than `JOB_LEASE_SECONDS / HEARTBEAT_SECONDS` or it
  re-introduces the same premature kill more slowly.

## comp-ytdl-jobs-2
- Verdict: DOWNGRADED to medium
- Reasoning: the defect is real and the source is unambiguous - `beat()`
  (jobs_runner.py:703) has no exception handling, so the same raise that
  finding 1 traces kills the beater thread permanently, nothing sets
  `lease_lost`, `should_stop()` never learns, and in a frozen windowed build
  the `threading.excepthook` output goes nowhere. What I could not sustain is
  high: unlike finding 1 no work is destroyed. The encode runs to completion,
  `_publish`'s rule-2 re-check protects the file from the second machine's
  copy, and `_post_result`'s 410 is swallowed by design (:536-539) - the cost is
  one duplicated encode elsewhere in the fleet plus a silent lease loss. It is
  also the same root cause as finding 1 and is fixed by the same one-line
  change, so it should not be counted as a second high.
- Evidence: `beat()` read in full; `_post_result`'s swallow read at :530-539.
- Fix note: right on both counts. Fix `_heartbeat` (finding 1) AND give
  `beat()` its own `try/except Exception` - a daemon thread whose only job is
  liveness must not be killable by anything it calls, whatever `_heartbeat`
  promises today.

## comp-ytdl-jobs-4
- Verdict: CONFIRMED (medium)
- Reasoning: `_popen(cmd, binary_stdout=True)` (jobs_media.py:428) deliberately
  skips `ffmpeg_tools.TEXT_UTF8`, so `proc.stdout` is a binary `BufferedReader`
  with the default `bufsize=-1`; `BufferedReader.read(1 << 20)` returns short
  only at EOF, so `_read_pcm`'s loop (:646) is parked inside the read and
  neither `should_stop()` nor the `ceiling` (COPY_TIMEOUT_SECONDS = 1800) is
  consulted until a full megabyte arrives. The docstring's claim that chunking
  makes a stop "honoured within a chunk" is true only for a chunk that
  completes. I checked for an external kill and there is none: `recipe.run` is
  called inline on the job thread with no wall-clock guard, and the beater keeps
  renewing the lease, so `expire_leases` will not reclaim it either. Contrast
  `_run_ffmpeg` (:560), which polls on a 0.5 s timer with both checks inside.
  PLAUSIBLE -> CONFIRMED on the mechanism; what stays unverified is only whether
  a real ffmpeg on a dropped share stalls rather than erroring, which is why I
  did not raise it further.
- Evidence: the two functions read side by side; `COPY_TIMEOUT_SECONDS =
  1800.0`; no test drives a child that stops producing output.
- Fix note: right, and the second option (drain stdout on its own thread, keep
  the stop/ceiling check on a `POLL_SECONDS` timer) is the better one - it
  reuses the pattern `_run_ffmpeg` and `_drain_text` already establish in this
  module, whereas a `selectors` loop does not work on a Windows pipe.
