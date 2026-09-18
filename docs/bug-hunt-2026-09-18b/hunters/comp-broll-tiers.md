# comp-broll-tiers - the proxy-tiers feature on the companion side, end to end

Files read (with approximate coverage): `git diff` of
`companion/src/ccsync_companion/broll_standins.py` (100%, plus the whole file),
`broll_server.py` (the tiers half: `derive_insert_paths`, `_no_self_referential_proxy`,
`plan_insert`, `build_insert_response`, the upgrade lane, `build_status_response`;
~100% of the diff), `broll_ingest.py` (the diff in full: `_maybe_stage_live`,
`_encode_gave_up`, the `/uploaded` non-200 arm, `_mirror_locally`/`_mirror_one`),
`ffmpeg_tools.py` (`frames_match`, `_plausible_frames`, `probe_video`),
`sidecar_tools.py` (the CR-280 CA-bundle block), `loopback_guard.py` (read, no diff),
`broll_fetch.py`/`broll_upload.py` (read where the insert and upload paths cross).
Both ends of the wires this feature owns: `broll/web/app/routes_api.py`
(`insert_target_detail`, `_insert_object`), `broll/web/app/ingest_batches.py`
(`mark_uploaded`, `set_item_state`, `_check_transition`), `broll/web/app/routes_fleet.py`,
`dashboard/src/ccsync_dashboard/api.py` + `db.py` for the `standins_placed` /
`standins_known` pair, and `proxy_relink.note_fleet_standins` /
`_geometry_disagrees` / `resolve_bridge._real_original_here` / `watcher.py` as the
ledger's three other readers. Docs: `docs/BROLL_PROXY_TIERS_PLAN.md` section 6,
`_AUDIT.md`, the ledger sections that cite comp-broll-tiers-1..5, proxy-tiers-3..8,
broll-1/-4, tests-2/-4, wire-1.

Tests run: `companion\.venv\Scripts\python.exe -m pytest tests/test_broll_standins.py
tests/test_broll_insert_tiers.py tests/test_broll_server.py
tests/test_broll_proxy_upgrade.py tests/test_bug_hunt_2026_09_18_companion_media.py -q`
-> 304 passed. Plus two scratch snippets against the real module from the companion
venv (outputs quoted below).

## Findings

### comp-broll-tiers-1 - a tree that is absent for one poll erases the stand-in ledger
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_standins.py:316-342` (`_prune_locked`,
  called from `_load_locked`:314)
- What: the new comp-broll-tiers-5 prune drops every entry whose `placed_at` is
  older than 30 days AND whose `local_path` cannot be stat'ed. "Cannot be stat'ed"
  is not "has been deleted": an external sync drive pulled (CR-92), a `P:` share
  not yet mapped at companion start (the LUT-index startup race), an SMB blip or a
  NAS reboot makes `_size_of` return None for EVERY entry at once. The prune has no
  root-presence check although the repo already has `root_guard.py`/`drive_swap.py`
  for exactly this question, and although the module's own docstring rule is
  "a file that is absent leaves the entry standing".
- Failure scenario: an editor's tree is on an external drive. They unplug it; the
  companion keeps polling (`/status` -> `_standins_owed` -> `all()` -> `_load_locked`)
  and the ledger loads with every entry older than 30 days dropped. The next write
  of any kind (one `record`, `forget` or `set_upgrade`) persists the pruned file.
  The drive comes back; `is_standin()` now answers False for those paths, so
  `resolve_bridge._real_original_here` calls a 1080p H.264 lie the real original,
  the insert path imports it instead of fetching, and a render on that machine
  renders 1080p H.264 under a 6K name - the one failure the module says it exists
  to prevent.
- Evidence: scratch script against the venv, a 40-day-old entry pointing at an
  absent `X:\Assets\B-roll Archive\CC\old.mov`:
  `entries seen with the drive absent: 0` and, after a single unrelated
  `record()`, the on-disk file contains only the new row. The log line it prints
  ("gone for over 30 days") is untrue in this scenario.
- Ledger: new (comp-broll-tiers-5 opens it)
- Suggested fix: only prune when the tree is demonstrably present - e.g. require
  `os.path.isdir()` of the entry's archive root (or `root_guard`'s verdict) before
  treating a missing file as gone, and skip the whole prune when the root is
  absent. A prune that cannot tell must do nothing.

### comp-broll-tiers-2 - the pre-fetch intent row can never be falsified, so a stand-in stays a stand-in after the real original arrives
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_server.py:1176-1183` (the
  `size=None` intent row) with `broll_standins.py:483-495` (`_entry_is_stale`)
- What: comp-broll-tiers-1's fix writes the ledger row BEFORE the fetch with
  `size=None`, and `_entry_is_stale` returns False for a non-int recorded size.
  The row is only rewritten with the real size if the SAME request survives to
  observe `STATE_DONE`. The abandoned-poll case the fix was written for (tab
  closed, laptop asleep, companion restarted) is precisely the case where the
  rewrite never happens - so the row that survives is the unfalsifiable one, and
  nothing ever repairs it: a later insert finds the file present and takes the
  `import_original` branch without recording anything.
- Failure scenario: editor sends a 6K clip to Resolve, closes the tab while it
  syncs; the stand-in lands with `size: null`. Weeks later lane B or a hand copy
  puts the REAL original at that path. `is_standin` still answers True and
  `is_stale` still answers False for ever: (a) `resolve_bridge._real_original_here`
  returns False, so the 540p `.mp4` preview is attached as the proxy of a clip
  whose real file is on this machine - the exact thing proxy-tiers-1's `.mp4` rule
  forbids; (b) `plan_insert` keeps answering "the stand-in for this clip is already
  in place" with an `upgrade_rel`, so every insert restarts an editing-proxy
  download for a clip that is already the original; (c) the watcher keeps exempting
  it.
- Evidence: scratch script - record with `size=None`, write 100 bytes (the
  preview), then 999999 bytes (the real original):
  `is_standin after real original: True`, `is_stale after real original: False`,
  `entry size: None`. The relink pass's exact-count probe still eventually
  corrects the geometry, which is why this is medium and not high.
- Ledger: CR-284 / comp-broll-tiers-1 does not fully fix comp-broll-tiers-1
- Suggested fix: stamp the size the first time the file is seen - e.g. in
  `_entry_is_stale`/`get`, when `size` is None and the file now exists, record the
  observed size once (the ledger is already write-through), or have
  `resume_pending_upgrades`/the relink cycle repair `size: null` rows.

### comp-broll-tiers-3 - staging a clip live before the upload-failure check leaves a `live` row the companion then cannot fail
- Severity: medium
- Confidence: CONFIRMED (by reading both sides; not executed)
- Where: `companion/src/ccsync_companion/broll_ingest.py:2991` (`_maybe_stage_live`
  is called before the `broken` branch) with
  `broll/web/app/ingest_batches.py:852-880` (`_check_transition`) and
  `broll_ingest.py:3451-3466` (`_fail_item`)
- What: proxy-tiers-5 posts `/uploaded` as soon as everything but the original has
  landed, which sets `ingest_items.state='live'` (a member of `ITEM_TERMINAL`).
  It is called BEFORE the code that notices the original's upload has failed. When
  the original then fails `MAX_UPLOAD_ATTEMPTS` times, `_fail_item` posts
  `item_status(..., failed)`, which `_check_transition` refuses with
  `400 illegal_transition` ("item is already live"), and the companion swallows
  that at `log.debug`.
- Failure scenario: a 40 GB original's rclone dies four times on a flaky link.
  Server-side the item stays `live`, `n_failed` is 0, the batch releases as `done`
  (not `done_with_errors`), and the SPA the editor is watching shows the clip
  finished. `videos.original_path` is NULL for ever, so every remote Send to
  Resolve for that clip answers `original_rel: null` and inserts the preview
  instead - and nobody is told the original never reached the NAS.
- Evidence: `ITEM_TERMINAL = {"live", ...}`; `_check_transition` raises 400 for
  `new in ITEM_ENDINGS and old in ITEM_TERMINAL`; `_fail_item` catches everything
  but `LeaseLost` at debug level. `_recount`/`release` read the server's own
  `ingest_items.state`, so the local `failed` never reaches the batch summary.
- Ledger: new (opened by proxy-tiers-5)
- Suggested fix: call `_maybe_stage_live` only after the `broken`/`unknown`
  branches (i.e. only when the original is genuinely still in flight), and give a
  staged-live item whose original ultimately fails its own surfaced state - a
  notice or an `error` on the live row - rather than a swallowed 400.

### comp-broll-tiers-4 - the early stage-live post retries every 15 s for ever with no counter and no visible failure
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_ingest.py:3116-3168`
  (`_maybe_stage_live`, the `status != 200` arm)
- What: `staged_live` is only set on a 200, and there is no attempt counter and no
  backoff, so any non-200 (a 409 because a still is zero bytes, the mounted app's
  500 for a busy database, a 4xx `wrong_edit_proxy`) is retried on every tick for
  the whole life of the original's upload. Every other post in this class
  (`/uploaded`, the 409 arm, the new wire-1 arm) counts against
  `MAX_UPLOAD_ATTEMPTS`; this one does not, and its only trace on the companion is
  `log.debug`.
- Failure scenario: a 40 GB original uploads for six hours behind a clip whose
  preview is 0 bytes. 1,440 POSTs to the NAS, each one stat-ing the archive and
  each one writing `b-roll ingest: item ... not live` at WARNING in the server log,
  while the companion side says nothing at any level an operator reads.
- Evidence: `TICK_SECONDS = 15.0`; `_pump_uploads` is called twice per tick
  (`tick` and `_drain`); the arm returns without touching `upload_attempts`.
- Ledger: new (opened by proxy-tiers-5)
- Suggested fix: stage-live at most once per N ticks (or once per item, on the
  first tick after the non-original rels land) and stop asking after a couple of
  refusals - the ordinary end-of-upload post is the one that counts.

### comp-broll-tiers-5 - a lost lease raised inside the stage-live post bypasses `_lease_lost`
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_ingest.py:3140-3141` (`except
  LeaseLost: raise`) with the call site at 2991 and `_loop` at 1962-1971
- What: `_maybe_stage_live` deliberately re-raises `LeaseLost` for a caller to
  handle, but it is called OUTSIDE the `try/except LeaseLost` that guards
  `_post_uploaded` further down the same method, and `_pump_uploads` itself has no
  handler. The exception unwinds to `_loop`'s generic `except Exception:
  self.log.exception("tick failed")`, so `self._lease_lost(...)` never runs.
- Failure scenario: the dashboard takes the batch back (container restart, lease
  expiry) while an original is uploading. Instead of the orderly lease-lost path,
  every tick logs a traceback and abandons the rest of the pump - including the
  `broken`/`unknown` handling for every later item - until the heartbeat's 410
  independently notices.
- Evidence: code reading; `_drain` and the `_post_uploaded` call site both wrap
  their posts in `except LeaseLost as exc: self._lease_lost(str(exc)); return`,
  and this one is not wrapped.
- Ledger: new (opened by proxy-tiers-5)
- Suggested fix: wrap the `_maybe_stage_live` call in the same
  `except LeaseLost as exc: self._lease_lost(str(exc)); return` the two posts
  below it use.

### comp-broll-tiers-6 - CR-280's CA-bundle fix also fires on every frozen WINDOWS companion, where it can only be wrong
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sidecar_tools.py:225-259`
  (`ensure_ca_bundle`), called unconditionally from `app.py:11228`
- What: the guard is `if not sys.frozen and sys.platform != "darwin": return None`,
  so the frozen Windows build (three of the four machines in the field, and every
  customer's Windows editor) runs it too. `certifi` is in no
  `requirements.lock`, and every entry of `CA_BUNDLE_CANDIDATES` is a POSIX path,
  so on Windows the function always reaches its `log.warning("no CA bundle was
  found on this machine, so HTTPS downloads ... may fail to verify certificates
  (CR-280)")` - a permanent false alarm on a platform whose Python has been using
  the Windows certificate store successfully all along. If `certifi` ever arrives
  in the frozen Windows build transitively, the same line sets `SSL_CERT_FILE` to
  a path inside `_MEIPASS`, which is exported through `os.environ` to every child
  (rclone, yt-dlp, ffmpeg) and disappears when the companion exits.
- Failure scenario: an admin reading a Windows companion log during a support call
  is told HTTPS may fail to verify certificates, on a machine where it never has.
- Evidence: `grep -in certifi companion/requirements.lock` -> nothing; the
  candidate list is `/etc/...`, `/private/etc/...`, `/opt/homebrew/...`; the three
  new tests all monkeypatch `sys.frozen = True` and a POSIX-shaped candidate, so
  none of them exercises Windows.
- Ledger: related to CR-280 (open)
- Suggested fix: scope it to `sys.platform == "darwin"` (the only platform where
  the failure was ever measured), or at minimum suppress the warning on Windows.

## Coverage note
Not covered: `broll_upload.py`'s queue internals and `broll_ingest_media.py` (read
only where the insert/upload paths cross them); `loopback_guard.py` has no diff and
I only re-read its CORS gate; I did not re-derive the geometry columns' behaviour on
the indexer side (broll-indexer's territory). I verified the `standins_placed` /
`standins_known` wire in both directions and found it sound: the dashboard omits the
key when its set is empty, `fleet_says_standin` treats a miss as "don't know", and
both caps are 200 - the truncated tail only costs a probe, so it is not a finding.
The `known: false` path, `_no_self_referential_proxy` and the `STANDIN_EXTS`
allow-list all match `insert_target_detail`'s half. The suite does not cover: the
ledger with the tree absent, a `size: null` row meeting a real original, any
stage-live path that is not a 200, or `ensure_ca_bundle` on Windows.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/broll_ingest.py:3040-3100`: the new wire-1 arm
  fails an item on ANY 4xx, including a 400 `illegal_transition` that
  `_maybe_stage_live` can now provoke on the final `/uploaded` - worth a look from
  the wire lens.
- `broll/web/app/ingest_batches.py:1216-1240`: `mark_uploaded` clears
  `ingest_batches.current_item_uid` on the early stage-live post, while that item is
  still uploading its original.
