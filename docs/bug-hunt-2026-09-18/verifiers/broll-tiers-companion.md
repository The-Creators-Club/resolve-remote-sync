# verdicts - broll-tiers-companion

Verifier for `comp-broll-tiers.md` and `res-companion.md`. Read-only; the only
file written is this one. Evidence produced from `companion\.venv` and from
`ffmpeg 8.1` in the scratchpad.

## comp-broll-tiers-1
- Verdict: CONFIRMED (high)
- Duplicate of: res-companion-1 (same defect, same line - see the note under
  res-companion-1)
- Reasoning: `broll_standins.record` is called from exactly one place,
  `broll_server.py:1077`, inside `if action == PLAN_FETCH_STANDIN:` which is
  itself inside the `if not insert_path.is_file():` block after
  `if state != STATE_DONE: return`. The download runs on a daemon thread
  (`broll_fetch._run_job`) that sets `STATE_DONE` and renames `.partial` onto
  the destination without any callback; only a subsequent HTTP poll writes the
  row. So a page that stops polling (tab closed, browser asleep, companion
  restarted) leaves the preview's bytes at the original's name with no ledger
  entry. I looked for a reconciler and there is none: `grep -rn
  "broll_standins\." companion/src` shows readers only (`is_standin`,
  `is_under_archive`, `get`, `set_upgrade`, `pending_upgrades`) plus the single
  `record`, and `forget()` has no caller anywhere.
- Evidence: the grep above; `broll_fetch.poll_fetch`'s docstring ("done" is
  popped on the polling thread) and `_run_job`'s terminal state; the pinning
  test `test_a_download_in_flight_answers_the_page_the_shape_it_understands`
  asserting `broll_standins.all() == []` on exactly that path.
- Fix note: the suggested "record before the fetch with `size: None`" is right
  and safe - `_entry_is_stale` already returns False for a non-int `size`, so
  an unknown size reads as "still a stand-in", the conservative direction, and
  the real original arriving later falsifies the row by size. Two other files
  must move with it: `companion/tests/test_broll_insert_tiers.py:275-289`
  pins the current (wrong) behaviour and has to be inverted, and the DONE
  branch must then UPDATE rather than re-`record` (record currently rebuilds
  the row, which would drop an `upgrade` state set in between). Note the row
  must also be retired when the plan ends up NOT placing a stand-in (a refused
  fetch), which `is_stale` handles only once a real file of a different size
  lands - a `forget()` on a failed fetch is the cleaner half.

## comp-broll-tiers-2
- Verdict: CONFIRMED (medium)
- Duplicate of: none (comp-app-1 is about the same resume call being gated
  behind `proxy_relink_enabled`, a different defect on the same line)
- Reasoning: `start_proxy_upgrade` refuses only on `upgrade == done`; there is
  no in-flight registry and no lock. `resume_pending_upgrades` iterates every
  row whose state is `pending` - which is the state a RUNNING upgrade sits in
  (`run_proxy_upgrade` sets `UPGRADE_PENDING` before its download loop) - and
  is called from `app._relink_proxies_once` inside the `try` and BEFORE
  `if not ops: return`, i.e. on every 120 s media-tree pass. So a slow download
  accumulates one thread per pass. One mitigation the hunter did not name:
  `poll_fetch` keys jobs by destination, so the duplicate threads join one
  rclone rather than starting several - the duplication costs threads and,
  when the file lands, one `music_server.call(BROLL_LINK_PROXY_ACTION)` worker
  child per thread. The permanently-pending case (Resolve open on another
  project, deliberately left `pending` at `:1215-1221`) is the worse half: it
  costs one thread and one worker child every 120 s for ever, with no backoff
  or attempt ceiling anywhere.
- Evidence: read `run_proxy_upgrade`, `start_proxy_upgrade`,
  `resume_pending_upgrades` and `app.py:4416-4475`; the only `Thread(` in the
  proxy-upgrade half of `broll_server.py` is the unguarded one.
- Fix note: the suggested module-level in-flight set under a lock cleared in a
  `finally` is right. It must be keyed on the normalised stand-in path
  (`broll_standins.normalise_key`), not the raw string, or two spellings of
  one path both start. A failure ceiling has to live in the ledger, not in
  memory, or a restart resets it; that means a new field written by
  `set_upgrade`, so `broll_standins.py` and `test_broll_proxy_upgrade.py`
  (which calls `resume_pending_upgrades` once per test with an injected
  `starter`) both move with the fix.

## comp-broll-tiers-3
- Verdict: DOWNGRADED to low
- Duplicate of: none (broll-indexer-1/-3 are the same check on the indexer
  side, not the same code)
- Reasoning: the structural half is confirmed by reading - `_encode_verified`
  treats any non-None `_frames_missing` as fatal for the pass, and after the
  last pass calls `self._fail_item(item, why)`, so a count mismatch fails the
  WHOLE item (no preview, no stills, no upload) rather than dropping the
  editing-proxy tier. But the hunter's stated mechanism, VFR sources, does not
  reproduce. Neither `preview_proxy_cmd` nor `own_proxy_cmd` passes `-r`, and
  both mp4 and mov carry `AVFMT_VARIABLE_FPS`, so ffmpeg's default frame-rate
  mode passes VFR timestamps through rather than conforming to CFR. I built a
  deliberately variable-rate source and ran the shipped argv shape over it:
  source 200 packets, mp4 output 200, mov output 200. With the named failure
  mode refuted the residual is "a genuinely damaged source whose trailing
  frames ffmpeg drops fails the item wholesale", which is rarer and is at
  least arguably the intended CR-281 behaviour.
- Evidence: `ffmpeg -f lavfi -i testsrc=...:rate=30:duration=10 -vf
  "select='not(mod(n,3))+gt(random(0),0.5)'" -fps_mode vfr` -> `vfr.mp4`,
  `nb_read_packets = 200`, `avg_frame_rate 20/1` vs `r_frame_rate 30/1`;
  re-encoded through the preview argv (`scale`, `-g`, `-pix_fmt yuv420p`,
  `-f mp4`) -> 200, and through `-f mov` -> 200. ffmpeg 8.1.
- Fix note: the "fall back to `edit_proxy = None` with a reason rather than
  failing the item" half is worth doing regardless and is cheap -
  `_decide_edit_proxy` already has the `edit_proxy_reason` shape for it. Do
  NOT add a blanket tolerance to `_frames_missing`: the Reproductive Rights
  clips were 1-18 frames short and Resolve refused every one, so a tolerance
  of "a frame rate's worth" would readmit exactly the defect the check was
  written for. Any change here must keep parity with
  `broll/indexer`'s copy of the same check (broll-indexer-1) or the two
  pipelines drift again.

## comp-broll-tiers-4
- Verdict: CONFIRMED (medium)
- Duplicate of: none
- Reasoning: I reproduced the hunter's snippet exactly in the companion venv,
  and I verified the other end of the wire, which the hunter only cited:
  `broll/web/app/routes_api.py:118` sets `original_rel = None` when there is
  no unique stem sibling and `rel_path = original_rel or rel`, and
  `static/app.js:1692,1703` posts that `rel_path` plus the whole `insert`
  object. `derive_insert_paths` then maps the explicit null back onto the
  posted rel, so `original_rel == preview_rel`, and `plan_insert` still
  answers `fetch_standin`. The download itself is harmless (right bytes, right
  path), but `broll_standins.record()` then marks a genuine preview as a lie
  whose size never changes, so `_entry_is_stale` never retires it and all four
  readers (insert, watcher exemption, proxy_relink, the upgrade resume) are
  wrong about that clip for the life of the machine. Reachability depends on
  the row reading heavier than edit weight, which is a property of the indexed
  original's metadata, not of the missing sibling - plausible for the task #23
  clips but not universal, which is why medium and not high is right.
- Evidence: run from `companion\.venv`: `derive_insert_paths({'original_rel':
  None, 'preview_rel': 'cc/ff5/Proxy/clip.mp4', ...}, 'cc/ff5/Proxy/clip.mp4')`
  -> `original_rel = 'cc/ff5/Proxy/clip.mp4'`; `plan_insert(False, False, t,
  wired=False)` -> `{'action': 'fetch_standin', 'fetch_rel':
  'cc/ff5/Proxy/clip.mp4', 'insert_rel': None, 'upgrade_rel':
  'cc/ff5/Proxy/clip.mov'}`.
- Fix note: the suggested `preview_only` answer is right and is best keyed on
  `insert` carrying the key with an explicit null (the docstring at
  routes_api.py:88-91 says as much), with `resolved original_rel ==
  preview_rel` as the belt-and-braces test - a bare-rel fallback where the page
  named the preview must keep working. The fix has to touch
  `derive_insert_paths` (so a null original does not silently become the
  preview) or `plan_insert`, plus `companion/tests/test_broll_insert_tiers.py`,
  and should be paired with the web side so the two agree on what "no original"
  means.

## comp-broll-tiers-5
- Verdict: CONFIRMED (low)
- Duplicate of: none (the res-companion report lists the same never-pruned
  ledger in its OUT OF TERRITORY section and hands it to this hunter)
- Reasoning: both halves check out by reading. `forget()` has no caller in the
  tree, nothing prunes on load, and `all()` re-reads and re-sorts the whole
  file on every `pending_upgrades()` poll from the 120 s cycle. `UPGRADE_FAILED`
  is written to the ledger and logged at WARNING/INFO and reaches no tray line,
  no report field and no dashboard row (`grep -rn "standin" app.py` finds only
  the `configure` call and comments), so an editor cutting on a 1080p preview
  they believe is the editing proxy is never told. Severity stays low: growth
  is one row per stand-in actually placed, so the file is small in practice -
  the invisible `failed` state is the part that matters.
- Evidence: `grep -rn "\.forget(" companion/src` -> nothing;
  `broll_standins.py:212-290` has no prune path; `broll_server.py:1161-1199`
  sets `UPGRADE_FAILED` and returns, with `log.warning` as the only surfacing.
- Fix note: retiring "file gone AND older than N days" is safe only in that
  order - an entry whose file is merely absent must stand (the module
  docstring's rule, and `_entry_is_stale` already returns False for it), so the
  prune must be time-bounded as well as absence-bounded. Surfacing a failed
  upgrade should reuse `_note_proxy_attach`'s existing RES-3 shape rather than
  a new tray path, and any new report field needs the dashboard side to ignore
  unknown keys (it does today).

## res-companion-1
- Verdict: CONFIRMED (high)
- Duplicate of: comp-broll-tiers-1 - the SAME defect. Both name
  `broll_server.py`'s single `broll_standins.record` call inside the
  `STATE_DONE` branch, both name the asynchronous `broll_fetch` job as the
  reason the file can land unledgered, and both propose the same fix (record
  before the fetch with `size: None`, or a completion callback). They should
  be one ledger entry; res-companion-1 adds the companion-restart /
  self-upgrade variant of the trigger and comp-broll-tiers-1 adds the
  downstream "next insert takes `import_original` with `upgrade_rel=None`"
  consequence, so the merged entry should keep both halves.
- Reasoning: as for comp-broll-tiers-1. I additionally checked the claim that
  nothing reconciles at startup - `app.py` touches `broll_standins` only at
  `:1628` (`configure`), so there is no sweep.
- Evidence: see comp-broll-tiers-1.
- Fix note: the extra option this report raises, an on-success callback from
  `broll_fetch`, would work but is the wider change: `poll_fetch` is shared
  with the music route and the background upgrade lane, so a callback
  parameter has to be threaded through `FetchJob`, `_run_job` and both other
  callers. The record-first variant touches one function.

## res-companion-2
- Verdict: CONFIRMED (high)
- Duplicate of: none
- Reasoning: every link in the chain is in the code as described.
  `_relocate_trashed` -> `_move_out_of_trash` does a bare `os.rename` into the
  server's new relative path and touches neither the `file_moves` ledger nor
  Resolve (no `record_intent`, no `relink` in `sync/rclone_lane.py`).
  `apply_move`'s `if not src.exists():` resume branch fires only when
  `ledger.entry(move["id"])` is in `STATE_APPLYING`, which lane B never wrote,
  so it returns `(True, "nothing at the old path on this machine", None)`;
  `app.py:7842-7860` then skips `_relink_moved_result` entirely because
  `paths is None`, sets `relink_pending = False` and answers the dashboard
  `ok`. Nothing anywhere else re-tries the relink, because `_relink_pending_moves`
  only walks moves the ledger recorded with `relink_pending = True`. One
  qualification worth carrying into the ledger entry: lane B's include is
  `**/Proxy/**`, so the files it relocates are proxies, and the clip whose
  File Path is the ORIGINAL would answer "nothing at the old path" on a
  proxy-only machine even without lane B - the new part is that the resume
  evidence (src gone, dest present) now exists and is ignored, and that after
  the follow `expected_proxy_paths(<old original path>)` no longer finds the
  proxy, so the 120 s relink pass cannot heal it either.
- Evidence: `sync/rclone_lane.py:3974-4120` read in full; `file_moves.py:337-359`;
  `app.py:7833-7860` and `_relink_moved_result` at `:8031`; lane B's filter
  rules at `sync/rclone_lane.py:605,658-660`.
- Fix note: of the two suggestions, "record an intent row keyed by the move"
  is not available to lane B - it does not know the move id, which is minted
  later by the dashboard's detection. So the fix is the other one: make
  `apply_move` treat "src absent, dest present, dest size matches" as
  resumable regardless of the intent row (the intent row then becomes
  corroborating rather than required), and/or have `_relocate_trashed` relink
  Resolve itself. The second must go through `resolve_bridge.replace_clip` (the
  CLAUDE.md rule that every media-pool write takes the save point and the undo
  journal) and would put a Resolve call on the lane thread, which is a real
  design cost - the `apply_move` half is cheaper and lands in one file plus
  `companion/tests/test_file_moves.py`, which pins the current "nothing at the
  old path" answer.

## res-companion-3
- Verdict: CONFIRMED (medium)
- Duplicate of: comp-resolve-2 ("the geometry check ffprobes every archive
  clip, whole-file, on every 120 s pass") - same code, same cost, reported
  independently; keep one ledger entry.
- Reasoning: confirmed by reading both ends. `plan_relinks` evaluates
  `_under_archive(...) and original_present() and not is_standin() and
  _geometry_disagrees(...)` for every in-tree clip, and `_geometry_disagrees`
  calls `count_frames_fn`, which `app.py:4442` binds to
  `proxy_relink.frame_counter(...)` -> `ffmpeg_tools.count_frames` ->
  `-count_packets`, a full demux, 60 s timeout, serial, on the media-tree
  thread. `resolve_bridge` attaches `frames` for archive clips only, so
  `stored_frames` is non-None for all of them and the probe proceeds. The cache
  is per pass by design, so it repeats every 120 s, and `allow_automatic` is
  consulted only after `if not ops: return`, so the rate limiter does not bound
  it. Two things keep it at medium rather than high: the scope really is the
  archive only (project footage is excluded deliberately), and on a REMOTE
  editor's machine most archive originals are absent, so `original_present()`
  short-circuits. The base rig, whose `local_root` is the SMB share and where
  every original IS present, pays the whole bill.
- Evidence: `proxy_relink.py:285-309,310-343,540-552`; `ffmpeg_tools.py:905-962`;
  `resolve_bridge.py:1843-1853`; `app.py:4431-4444`.
- Fix note: the suggested (path, size, mtime) cache is right and is the same
  falsifier `_entry_is_stale` uses. The second suggestion - "ask only about
  clips the ledger has an entry for" - would be WRONG as stated: the refresh is
  deliberately scoped to clips that are NOT currently ledgered stand-ins
  (`not is_standin()`), i.e. exactly the ones whose entry has gone stale or was
  never written (comp-broll-tiers-1/res-companion-1), so narrowing to ledgered
  clips would turn the feature off. Any fix here interacts with comp-resolve-1:
  while `replace_clip` short-circuits on its own path the probe can never stop,
  because the geometry never converges.

## res-companion-4
- Verdict: CONFIRMED (medium)
- Duplicate of: none
- Reasoning: `LaneWatchdog._restart` calls `target.restart()` and nothing else -
  no stop, no join, no liveness precondition - and for the media tree that is
  `app._start_media_tree_thread`, whose first statement is
  `self._media_tree_stop_event.clear()` before it overwrites
  `self._media_tree_thread`. `_media_tree_loop` tests that same shared event,
  so the orphan does not exit when it unblocks, and `_media_tree_target`
  computes `died` from the NEW reference, so the wedge reads as healed. Both
  threads then run `_refresh_media_tree_once` -> `_relink_proxies_once` ->
  `apply_relinks`, i.e. two unprompted writers into one Resolve project, plus
  two `retry_loopback_bind()` callers. The same shape applies to the watcher
  (`_start_watcher_thread` shares `_stop_event` with the sync loop, so it
  cannot even be signalled without stopping everything). Medium is right: it
  needs a 30-minute silent pass first, which res-companion-3 on a base rig
  makes reachable rather than theoretical.
- Evidence: `app.py:1133-1148` (`_media_tree_target`), `:1159-1169` (`_restart`),
  `:9152-9162` (`_start_media_tree_thread`), `:4477-4500` (`_media_tree_loop`
  stamping the heartbeat at the top of the loop only).
- Fix note: the suggested per-thread stop event is the right shape, but note
  the watcher branch cannot reuse it as written - `_start_watcher_thread`
  passes the process-wide `self._stop_event`, so giving the watcher a private
  event is a separate change with its own blast radius (shutdown ordering).
  The cheapest correct fix for both is the owner-token check the finding ends
  with: stamp a generation counter on start, and have each loop exit when it
  is no longer the current generation. `companion/tests/` has watchdog tests
  that assert a restart happened; they will need the new "the old thread
  stopped" assertion rather than replacement.

## res-companion-5
- Verdict: CONFIRMED (low)
- Duplicate of: overlaps comp-resolve-2, whose evidence and suggested fix are
  the same "record that a refresh was attempted for (path, size, mtime) so it
  is not re-planned" - merge them.
- Reasoning: the reading is right: the `refresh` op is appended and `continue`s
  before any `is_refused`/`note_refusal` logic, and `apply_relinks`' refresh
  branch increments `refreshed` and logs INFO without remembering anything, so
  a clip whose stored `Frames` never converges is re-planned every pass for
  ever. One correction to the failure scenario, which the hunter could not see
  from their file set: `resolve_bridge.replace_clip` returns
  `{"ok": True, "message": "Already linked to ..."}` BEFORE `_before_mutation`
  whenever the requested path equals the clip's current File Path, which for a
  refresh is always (comp-resolve-1). So today there is no `SaveProject`, no
  `ExportProject` and no undo-journal entry - `~/.ccsync/resolve_edits` does
  not grow, and the real cost is one burnt `allow_automatic` grant per pass
  (8/day) plus the ffprobe of res-companion-3. The stated harm becomes real
  only once comp-resolve-1 is fixed, which is precisely why the memo should be
  fixed in the same change.
- Evidence: `proxy_relink.py:551-580,703-722`; `resolve_bridge.py:2279-2285`
  (the `Already linked` early return, ahead of `_before_mutation`).
- Fix note: the suggested `note_refusal`-shaped memory is right, but it must be
  keyed on (path, size, mtime, stored_frames) and not on (path, proxy) - the
  existing refusal store is a proxy-pairing store and reusing it directly would
  suppress genuine proxy relinks for that clip. Fixing this without
  comp-resolve-1 would cement the current no-op: the memo would remember a
  refresh that never happened.
