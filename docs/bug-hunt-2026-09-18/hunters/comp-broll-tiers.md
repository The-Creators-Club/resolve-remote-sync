# comp-broll-tiers - the proxy-tiers feature on the companion side, end to end

Files read (with approximate coverage): `companion/src/ccsync_companion/broll_standins.py`
(100%), `broll_server.py` (the whole proxy-tiers half: `_clean_rel`,
`derive_insert_paths`, `plan_insert`, `_is_wired`, `build_insert_response`,
`run_proxy_upgrade`, `start_proxy_upgrade`, `resume_pending_upgrades`,
`_fetchable_from_nas`; ~40% of the file overall), `broll_fetch.py` (the
background-lane diff plus `poll_fetch`/`_running_count`), `broll_upload.py`
(kind + order diff), `broll_ingest.py` (the editing-proxy half: `_encode_verified`,
`_make_proxy`, `_make_edit_proxy`, `_edit_proxy_skip`, `_edit_proxy_decided`,
`_frames_missing`, `_fail_item`, the upload plan and `_item_uploaded`),
`broll_ingest_media.py` (100% of the diff), `ffmpeg_tools.py` (100% of the diff:
`timecode_from_probe`, `dropframe_normalized`, `probe_video`, `is_edit_weight`,
`preview_proxy_cmd`, `count_frames*`), `loopback_guard.py` and `sidecar_tools.py`
(unchanged since 34a3c8f, skimmed). Read for the contract, not reported on:
`broll/web/static/app.js` (the `insert` POST body), `broll/web/app/routes_api.py`
(`insert_target_detail`, `_insert_object`), `app.py:4421-4460` and
`app.py:4926-4940` (the relink cycle's resume call), `watcher.py:505-535`,
`proxy_relink.py:235-245,505-515`. Docs: `docs/BROLL_PROXY_TIERS_PLAN.md`
sections 4-6, `docs/BROLL_PROXY_TIERS_PLAN_AUDIT.md` (F1-F11), `KNOWN_BUGS.md`
CR-281, CLAUDE.md.

Tests run: `companion/.venv/Scripts/python.exe -m pytest tests/test_broll_insert_tiers.py
tests/test_broll_standins.py tests/test_broll_proxy_upgrade.py
tests/test_broll_ingest_media.py tests/test_ffmpeg_tools.py -q` -> 250 passed.
Plus one ad-hoc `derive_insert_paths`/`plan_insert` snippet from that venv
(output quoted in finding 4).

## Findings

### comp-broll-tiers-1 - a stand-in whose download finishes after the page stops polling is never ledgered
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_server.py:1033-1042` (the
  `STATE_DOWNLOADING` early return) vs `:1072-1085` (the only
  `broll_standins.record` call); test that pins it:
  `companion/tests/test_broll_insert_tiers.py:275-289`
- What: on the `fetch_standin` route the preview's bytes are written to the
  ORIGINAL's local path and name by an asynchronous rclone job, but the ledger
  row is written only on the request that observes `state == "done"`. Every
  earlier request returns `{"state": "downloading"}` and records nothing. If
  the page's poll loop stops before the job finishes - the tab is closed or
  backgrounded, the browser sleeps, the laptop's wifi drops, the companion is
  restarted, the editor navigates away after the "syncing 40%" toast - the
  download still completes (the job thread is independent of the request) and
  the lie lands on disk with no ledger entry at all.
- Failure scenario: remote editor clicks Send to Resolve on a 6K original,
  sees "syncing the clip to this computer: 40%", switches to Resolve and the
  page stops polling. rclone finishes and renames `<stem>.mov.partial` ->
  `<stem>.mov` under `Assets/B-roll Archive/...`. That file is a 1080p H.264
  preview under the original's name and nothing knows: the next Send to
  Resolve takes `plan_insert(local_path_exists=True, is_standin=False)` ->
  `import_original`, `upgrade_rel=None`, so the editing proxy is never
  fetched and the clip's proxy is never upgraded; `broll_fetch`'s
  `is_file()` calls the original present for ever, so the real file can never
  be pulled down; the relink pass never learns the clip's stored geometry is
  the stand-in's; and a render on that machine renders 1080p H.264 under a 6K
  name - the three readers the module docstring names as the reason the
  ledger exists (`broll_standins.py:12-21`).
- Evidence: `record()` is inside the `if action == PLAN_FETCH_STANDIN:` block
  that sits after `if state != broll_fetch.STATE_DONE: return`; there is no
  other caller of `broll_standins.record` in the tree (`grep -rn
  broll_standins companion/src` - only `broll_server.py:1077`). The download
  is asynchronous by design (`broll_fetch.poll_fetch` spawns a daemon thread
  and returns `downloading`). `test_a_download_in_flight_answers_the_page_the_shape_it_understands`
  asserts `broll_standins.all() == []` on exactly that path, so the suite
  pins the gap rather than catching it.
- Ledger: new (CR-281 does not cover it; not in the audit's F1-F11 nor in its
  "still owed" list)
- Suggested fix: record the intent BEFORE the fetch is started (a row with
  `size: None` and, say, `state: "placing"`), and let the DONE branch update
  `size`; `_entry_is_stale` already treats an unknown size as "still a
  stand-in", which is the safe direction. Alternatively have the fetch job's
  terminal write call back into the ledger for stand-in destinations.

### comp-broll-tiers-2 - nothing dedupes an in-flight editing-proxy upgrade, and a permanently pending row spawns a Resolve worker child every relink cycle
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_server.py:1228-1290`
  (`start_proxy_upgrade` / `resume_pending_upgrades`), called from
  `companion/src/ccsync_companion/app.py:4449` inside `_relink_proxies_once`
- What: `start_proxy_upgrade` refuses only when the row is already `done`. It
  keeps no registry of running threads, and `resume_pending_upgrades` is
  called from the 120 s relink cycle for every row whose state is `pending` -
  which is precisely the state a running upgrade sits in. So each cycle
  starts a NEW daemon thread per pending row, on top of any already running.
- Failure scenario: (a) a 400 MB editing proxy takes 12 minutes over SFTP;
  six threads end up in `run_proxy_upgrade` for the same path, all polling
  `poll_fetch` every 2 s, and when the file lands all six call
  `music_server.call(BROLL_LINK_PROXY_ACTION)` - six worker child processes
  hitting Resolve for one clip. (b) Resolve is open but the clip's project is
  not loaded, so the link fails and the row is deliberately left `pending`
  (`:1211-1221`): from then on, for ever, every 120 s spawns a thread and a
  worker child per such row. With a dozen stand-ins placed over a week that
  is a dozen child processes every two minutes with nothing that retires
  them.
- Evidence: read both functions and the call site; `test_broll_proxy_upgrade.py`
  only ever calls `resume_pending_upgrades` once per test with an injected
  `starter`, so the repeat is not exercised. No `_RUNNING`/set/lock exists in
  `broll_server.py` (grep for `Thread(` in the file: the only proxy-upgrade
  spawn is the unguarded one at `:1256`).
- Ledger: new (audit F7 gave the upgrade its own fetch LANE, which caps
  concurrent downloads, not concurrent threads or worker calls)
- Suggested fix: keep a module-level set of in-flight stand-in paths under a
  lock, cleared in the thread's `finally`; and give a row that has failed to
  LINK a backoff or an attempt ceiling so a permanently pending entry stops
  costing a worker child every cycle.

### comp-broll-tiers-3 - an exact frame-count equality now fails the WHOLE ingest item, including for VFR sources
- Severity: medium
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/broll_ingest.py:2427-2452`
  (`_encode_verified` -> `_fail_item(item, why)`) and `:2454-2472`
  (`_frames_missing`)
- What: the new check compares the source's video PACKET count with the
  encoded file's and treats any difference as fatal, with no tolerance, for
  the preview AND the editing proxy. ffmpeg's default frame-rate mode for a
  filtered encode is CFR, so a variable-frame-rate source (screen recordings,
  phone footage, many YouTube-derived archive clips - the comment at
  `ffmpeg_tools.py:784` says this archive is largely YouTube downloads) legitimately
  produces a different output frame count. Both the NVENC and the CPU pass
  produce the same mismatch, so the loop exhausts and `_fail_item` marks the
  whole clip failed: no preview published, no stills, no original uploaded,
  for a file that is perfectly good.
- Failure scenario: an editor drops a folder containing one 29.97-VFR screen
  recording. `_make_proxy` encodes it twice, `_frames_missing` reports e.g.
  "the proxy has 5391 frames, the original has 5388", the item goes to
  `failed` with that text, and the clip never reaches the archive - whereas
  before 2026-09-17 it ingested normally (the old `_verify_proxy` allowed a
  3% duration tolerance; this check allows none).
- Evidence: read the loop - `short = self._frames_missing(...)`; any non-None
  answer skips the `os.replace` and, after the last pass, `self._fail_item(item, why)`.
  `_verify_proxy`'s own tolerance is `VERIFY_DURATION_RATIO = 0.97`, i.e. the
  same pipeline accepts a 3% short DURATION but rejects a one-frame count
  difference. I did not encode a real VFR file to measure the drift, hence
  PLAUSIBLE; the "fails the item wholesale rather than dropping the tier" half
  is CONFIRMED by reading.
- Ledger: new (CR-281's frame check is the Reproductive Rights lesson; the
  blast radius was not bounded)
- Suggested fix: allow a small tolerance (or compare durations when the
  counts disagree by less than a frame-rate's worth), and for the EDITING
  proxy specifically fall back to `edit_proxy = None` with a reason rather
  than failing an item whose preview and original are both fine.

### comp-broll-tiers-4 - an archive clip with no unique original sibling is "downloaded onto itself" and ledgered as a stand-in
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_server.py:706-780`
  (`derive_insert_paths`, the `basename(parent) == PROXY_DIR_NAME` branch and
  the "an explicit null for the ORIGINAL is not an answer" rule) with
  `broll/web/app/routes_api.py:118` (`original_rel = ... if len(matches) == 1
  else None`)
- What: the detail API deliberately answers `original_rel: null` for a clip
  whose original could not be identified beside its preview (the archive task
  #23 clips), and the page then posts `rel_path` = the PREVIEW's rel. The
  companion maps a null original back onto the posted rel, so `original_rel`
  and `preview_rel` become the same path; `plan_insert` still returns
  `fetch_standin` with `fetch_rel == preview_rel` and `insert_rel is None`,
  i.e. fetch the preview to the preview's own path, then
  `broll_standins.record()` that genuine file as a stand-in.
- Failure scenario: such a clip, with an `Proxy/<stem>.mov` beside it and a
  row whose bitrate reads heavy, is sent to Resolve. The download is
  harmless (right file, right place), but the ledger gains a permanent row
  claiming a real preview holds "the PREVIEW's bytes, not the original"
  (a WARNING in the log saying a render would be wrong), `is_standin()`
  answers True for it for ever (its size never changes, so `is_stale` never
  retires it), the watcher exempts it from the missing count on false
  grounds, `proxy_relink`'s stand-in branch treats its geometry as suspect,
  and every re-insert reports "the stand-in for this clip is already in
  place" and restarts an editing-proxy upgrade.
- Evidence:
  ```
  >>> t = derive_insert_paths({'original_rel': None,
  ...   'preview_rel': 'cc/ff5/Proxy/clip.mp4',
  ...   'edit_proxy_rel': 'cc/ff5/Proxy/clip.mov',
  ...   'original_is_edit_weight': False, 'geometry': {}},
  ...   'cc/ff5/Proxy/clip.mp4')
  {'preview_rel': 'cc/ff5/Proxy/clip.mp4', 'edit_proxy_rel': 'cc/ff5/Proxy/clip.mov',
   'original_rel': 'cc/ff5/Proxy/clip.mp4', ... 'from_page': True}
  >>> plan_insert(False, False, t, wired=False)
  {'action': 'fetch_standin', 'fetch_rel': 'cc/ff5/Proxy/clip.mp4',
   'insert_rel': None, 'upgrade_rel': 'cc/ff5/Proxy/clip.mov',
   'why': 'the original is heavier than edit weight'}
  ```
- Ledger: new
- Suggested fix: when `insert.original_rel` is explicitly null (or when the
  resolved `original_rel == preview_rel`), the answer is `preview_only` -
  there is no original to lie about, so fetch the preview to its own path,
  import it and record nothing.

### comp-broll-tiers-5 - the stand-in ledger grows for ever and nothing surfaces a failed upgrade to the editor
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_standins.py:212-262` (no prune)
  and `companion/src/ccsync_companion/broll_server.py:1180-1200`
  (`UPGRADE_FAILED` is a log line and a ledger field only)
- What: entries are added and never removed except by an explicit `forget()`,
  which nothing calls; `all()` is read (and re-sorted) on every
  `pending_upgrades()` poll from the relink cycle. And an upgrade that ends
  `failed` - the editing proxy is not on the NAS, rclone refused, the rel was
  not containable - is written to the ledger and the log and to nothing the
  editor sees: they keep cutting on the 1080p preview believing it is the
  editing proxy, which CLAUDE.md's "a failure logged but never surfaced to
  the person who must act" rule calls a defect.
- Failure scenario: a clip whose `edit_proxy_rel` was the stem convention's
  GUESS (no `insert` object, older dashboard) can never download; the row
  goes `failed` silently and the editor is never told the clip they are
  cutting is a 1080p preview, permanently.
- Evidence: read both; `grep -rn "broll_standins.forget\|\.forget(" companion/src`
  finds no caller.
- Ledger: new
- Suggested fix: retire entries whose file is gone AND older than N days on
  load, and give a `failed` upgrade one tray line (or a field on the
  companion's report) so the state is visible somewhere an editor looks.

## Coverage note
I did not read the whole of `broll_server.py` (the ytdl, status, media and
static-serving halves are unchanged since 34a3c8f and belong to
comp-music-ytdl-jobs / the earlier hunts), nor `broll_ingest.py` outside the
editing-proxy and upload-plan changes. `loopback_guard.py` and
`sidecar_tools.py` have not changed in the window and I only skimmed them. I
did not exercise a real encode, so finding 3's VFR drift is reasoned, not
measured; nor did I verify the wired-rig row live (the plan's own section 7
still lists those live checks as owed). The suite does not cover: a page that
stops polling mid-download (finding 1 is pinned the wrong way round), two
concurrent upgrades for one path, a `pending` row that never links, or any
ingest of a VFR source.

## OUT OF TERRITORY
- `broll/web/app/routes_api.py:118,133`: `rel_path` falls back to the preview
  when `original_rel` is None, which is what makes comp-broll-tiers-4
  reachable from the real server contract; the web side may want to send the
  flag the docstring at `:88-91` describes instead.
- `companion/src/ccsync_companion/app.py:4449`: `_resume_broll_proxy_upgrades()`
  is called before the `if not ops: return`, i.e. on every relink cycle - the
  driver of comp-broll-tiers-2's repeat.
