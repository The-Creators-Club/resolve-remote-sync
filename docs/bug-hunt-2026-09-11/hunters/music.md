# music - the music tagger: music/web (musicweb/*.py, static/*, tests/) and music/indexer

Files read (with approximate coverage):
- `git diff 097f5a3..HEAD -- music/` in full (24 files, ~2,550 added lines) - the
  primary target.
- `music/web/musicweb/`: `config.py` (100%), `routes_media.py` (100%),
  `routes_api.py` (100%), `routes_batches.py` (100%), `routes_fleet.py` (100%),
  `routes_ingest.py` (~85%), `drain.py` (100%), `rescore.py` (~90%),
  `schemas.py` (100%), `fleet_auth.py` (100%), `identity.py` (100%),
  `search.py` (100%), `text_encoder.py` (~90%), `main.py` (100%),
  `ingest_batches.py` (~60%: naming, `write_item_result`, `mark_uploaded`,
  `release`, `set_item_state`), `db.py` (~30%: `safe_upload_name`, `con`,
  `generation`/`file_state`/`invalidate`, `save_debias`).
- `music/web/static/`: the app.js diff in full; whole-file scans of
  `app.js`/`ingest.js`/`index.html`/`style.css` for em dashes and
  root-relative URLs.
- `music/indexer/`: `index_music.py` (~50%: `retag`, `drain_queue`, `_park`,
  the `--export-drain` main flow), `music_index/audio.py` (peaks half),
  `music_index/config.py` (skim).
- Cross-tree (both sides of the wire): `companion/src/ccsync_companion/music_ingest.py`
  (100%), the `IngestClient` / `_fail_item` / `_post_result` half of
  `broll_ingest.py`, `ytdl/web/ytdlweb/identity.py` (byte-compare).
- `CLAUDE.md`, `HUNTER_BRIEF.md`, `KNOWN_BUGS.md` (grepped for every symbol
  below), `music/web/tests/test_no_em_dashes.py`.

Tests run:
`cd music\web; .venv\Scripts\python.exe -m pytest tests/test_media_range.py tests/test_search_filters.py tests/test_rescore_transaction.py tests/test_drain_bundle.py tests/test_mounted_prefix.py -q`
-> **71 passed**. Plus three ad-hoc snippets from that venv (scratchpad, nothing
written into the repo): the `allocate_name` loop probe in music-1, a
`TestClient` Range/HEAD matrix in music-6, and an `identity.py` byte-compare
against the ytdl source (identical, marker present exactly once).

## Findings

### music-1 - `allocate_name`'s collision loop has no ceiling, and both of its "taken?" helpers answer TAKEN on error: a persistent sqlite error spins a dashboard worker thread forever
- Severity: high
- Confidence: CONFIRMED
- Where: `music/web/musicweb/ingest_batches.py:236-242` (the `while` loop), with
  `_taken_by_a_track` at `:281-296` and `_taken_on_disk` at `:265-278`
- What: the loop's only exit is "no reserved name, nothing on disk, nothing in
  `tracks`". Both disk and DB helpers deliberately return `True` on any error
  ("a query that cannot run counts as TAKEN ... which is the harmless
  direction"). That reasoning holds only for a TRANSIENT error. For a
  persistent one - `sqlite3.OperationalError: database is locked`,
  `DatabaseError: database disk image is malformed`, `ProgrammingError: Cannot
  operate on a closed database`, or an `OSError` from a share that is mounted
  but returning EIO - every candidate answers TAKEN, `i` increments without
  bound, and the loop never returns. There is no iteration cap, no timeout, and
  no "I have minted 1,000 names, something is wrong" refusal.
- Failure scenario: the container's music.db goes unreadable (a mid-publish
  swap, a malformed image, a share that mounts but faults). An editor's
  companion posts `POST /music/api/fleet/batches/<uid>/items/<iuid>/result`.
  `write_item_result` -> `allocate_name` enters an infinite tight loop on a
  uvicorn threadpool thread at 100% CPU. The companion's HTTP timeout fires and
  it RETRIES, so every retry of every item of every drop adds another spinning
  thread. The dashboard runs one uvicorn worker; a handful of these saturates
  the box that "tells everyone whether their footage is syncing". Nothing logs
  anything, nothing times out server-side, and only a container restart clears
  it.
- Evidence: run from `music/web/.venv`, with a connection whose `tracks` query
  raises `sqlite3.OperationalError('database is locked')`:
  ```
  share_root_ready -> (True, '')          # the gate above passes: it swallows
                                          # the same exception and fails open
  alive after 3s: True []                 # allocate_name never returned
  ```
  (`config.share_root_ready`'s `except Exception: return True, ''` at
  `config.py:478-479` is what lets the bad connection through to the loop in
  the first place, so the new music-1 gate does not cover this.)
- Ledger: new. (The helpers themselves are the bug-hunt-2026-09-03 music-3 fix,
  KNOWN_BUGS line ~10444; the unbounded loop is not recorded.)
- Suggested fix: cap the loop (`for i in range(2, 1000)` and raise
  `HTTPException(503, ...)` if it falls through), and separate "taken" from
  "could not tell" - an error should raise a 503 the companion can retry, not
  mint another candidate for ever.

### music-2 - the companion fails a track PERMANENTLY on every non-200 `result`, including the server's own retryable 409 `name_race` and the new 503 "the library is not mounted here"
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/music_ingest.py:377-397`
  (`MusicIngestor._post_result`) and `companion/src/ccsync_companion/broll_ingest.py:2880-2895`
  (`_fail_item`), against `music/web/musicweb/ingest_batches.py:885-891`
  (409 `name_race`) and `music/web/musicweb/ingest_batches.py:234-236`
  (`allocate_name`'s new `HTTPException(503, why)`)
- What: `_post_result` treats any `status != 200` identically: it clears
  `embedded`, calls `_fail_item`, and returns False. `_fail_item` is terminal -
  it sets `ITEM_FAILED` and posts `failed` to the server. Only 410 is special
  (raised as `LeaseLost` by `IngestClient._call`). So the two statuses the
  SERVER emits meaning "try again" are consumed as permanent failures:
  - 409 `{'reason': 'name_race', 'detail': 'another batch claimed that filename
    first; retry'}` - the server's comment says "The companion retries the
    result, which re-allocates around it." It does not.
  - 503 from `config.share_root_ready` via `allocate_name`, which is NEW in
    this cycle (c50d274..931c9b2). A 503 is by definition transient, and the
    message it carries ("Nothing is written until it is back") says so.
- Failure scenario: the NAS bind mount `{music_library_root}:/music-share`
  blips for thirty seconds during a fifteen-track album drop (a NAS reboot, an
  SMB reconnect, a dataset remount). Every in-flight `result` gets 503. The
  companion marks each track `failed` with "the library would not take this
  track: the music library is not mounted here (nothing at /music-share)", the
  batch releases as `done_with_errors`, and the editor's whole drop is dead -
  with the audio still staged on their machine and no retry anywhere. The mount
  comes back a minute later and nothing notices.
- Evidence: read both sides. `_call` (broll_ingest.py:352-358) raises only on
  410; `item_result` returns `(status, parsed)` untouched; `_post_result`'s sole
  branch is `if status != 200: ... self._fail_item(...)`. `_fail_item` sets
  `item["stage"] = ITEM_FAILED` and posts `ITEM_FAILED`, with no attempts
  budget and no re-queue. The 503 site is `allocate_name`, which
  `write_item_result` calls first thing.
- Ledger: new. (The 503 itself is the bug-hunt-2026-09-03 music-1/music-3 fix;
  its interaction with the companion's terminal failure path is not recorded.)
- Suggested fix: give `_post_result` a retry class - 503 and 409 `name_race`
  should leave the item at its current stage with a backoff and a bounded
  attempts budget, and only 409 `model_mismatch` / 422 should be terminal. The
  server already names the reason in `reason`, so branch on that, not on the
  status alone.

### music-3 - `rescore_library` clears `scores_stale` from a snapshot it took before the concurrent write, so a track can end up untagged with nothing saying so
- Severity: medium
- Confidence: CONFIRMED (mechanism); the window is a real-fleet race, so the
  frequency is PLAUSIBLE
- Where: `music/web/musicweb/rescore.py:340-372` (`rescore_library`: `load_matrix`
  at the top, `DELETE FROM meta WHERE key='scores_stale'` at the bottom) and
  `music/web/musicweb/routes_fleet.py:130-152` (`_settle_scores`'s early return)
- What: `rescore_library` reads `ids, mat = db.load_matrix(con)` first, then
  spends seconds in numpy (`compute_directions`, `label_space`, `score_all`),
  then writes and finally deletes the `scores_stale` marker unconditionally.
  The marker is a global fact about the whole library, but the rescore only
  covers the tracks that existed at `load_matrix` time. A `result` on another
  threadpool thread that writes a track and calls `mark_scores_stale` in that
  window has its marker deleted by a rescore that never saw its track.
  `_settle_scores` then does `if not rescore.scores_stale(conn): return`, so the
  end-of-batch settle - the one place MUSIC-5 relies on to guarantee "a batch is
  fully tagged by the time it finishes" - is skipped.
- Failure scenario: two editors drop albums at the same time. Editor A's batch
  releases; `_settle_scores` starts a full rescore. Mid-pass, editor B's next
  `result` lands, writes track T, is inside `RESCORE_MIN_SECONDS`, defers, and
  sets `scores_stale`. A's rescore finishes and deletes the marker. B's batch
  releases: `scores_stale` is empty, `_settle_scores` returns immediately.
  Track T is in the library, searchable by similarity, with no tags, no axes,
  no facet membership - and `/api/stats` reports `scores_stale: null`, so the
  SPA's "the tags are catching up" banner does not show either. It stays that
  way until the next drop or a base-rig `--retag`.
- Evidence: read `rescore_library` (the `DELETE FROM meta` is inside the same
  `with con:` as `tagged_at`, unconditional, with no comparison against
  anything written since `load_matrix`), `apply_for_track`'s defer branch
  (`rescore.py:390-394`), and `_settle_scores`'s guard. The container runs one
  uvicorn worker but sync routes are dispatched to a threadpool, so two
  `result`/`release` handlers do overlap; SQLite serialises only the writes,
  not the numpy pass between them.
- Ledger: new (related to the MUSIC-1 / MUSIC-5 work of 2026-09-04,
  KNOWN_BUGS line ~11394, which introduced the marker).
- Suggested fix: make the clear conditional - capture the marker value (or the
  max `tracks.id`) before `load_matrix` and only `DELETE` if it is unchanged;
  or have `_settle_scores` call `apply_for_track(..., force=True)` on the
  batch's own tracks rather than gating on a library-wide flag.

### music-4 - `apply_for_track(force=True)` has no production caller, and its docstring says otherwise
- Severity: low
- Confidence: CONFIRMED
- Where: `music/web/musicweb/rescore.py:374-386` ("`release` passes force=True,
  so a batch is always fully tagged by the time it finishes") vs
  `music/web/musicweb/routes_fleet.py:143-152`, which calls
  `rescore.rescore_library(conn)` behind a `scores_stale` guard instead
- What: the only `force=True` anywhere in the tree is
  `music/web/tests/test_rescore_transaction.py:186`. `release` never uses it.
  The two are nearly equivalent but not identical, and the difference is
  exactly music-3: the documented design (force a rescore at release) has no
  gate to lose, while the implemented one (rescore only if the flag is set) does.
  A reader reconciling the two will trust the docstring.
- Failure scenario: not a runtime fault on its own - it is the reason music-3
  is invisible to a reviewer, and it is a `force` parameter only a test
  exercises, so nothing would catch it rotting.
- Evidence: `grep -rn "force=True" --include=*.py music/web/` returns one test
  line and two unrelated `prune_missing`/`build_track` hits.
- Ledger: new.
- Suggested fix: either make `release` actually call `apply_for_track(...,
  force=True)` (which also fixes music-3), or correct the docstring to describe
  `_settle_scores`.

### music-5 - `share_root_ready` samples the 50 LOWEST track ids, so a library whose oldest files were tidied away 503s every ingest route
- Severity: medium
- Confidence: CONFIRMED (logic); PLAUSIBLE that a fleet hits it
- Where: `music/web/musicweb/config.py:476-491`
- What: the readiness probe asks `SELECT rel_path FROM tracks WHERE rel_path IS
  NOT NULL ORDER BY id LIMIT 50` and returns "not mounted" unless at least one
  of those fifty exists on disk. Those fifty are the OLDEST rows, not a sample
  of the library. They are also the rows most likely to have been superseded -
  the first wav imports, files replaced by a transcode, tracks removed by hand
  without a `--prune` (which the codebase elsewhere treats as a normal state:
  `db.prune_missing` exists precisely because rows outlive files, and
  `_taken_by_a_track`'s docstring cites "a row's file was removed by hand
  without a --prune" as the case it defends against).
- Failure scenario: an operator reorganises or replaces the first fifty cues in
  a 400-track library without running `--prune`. From then on every
  `/music/api/ingest`, every `_ingest_inline` and every fleet `result` answers
  503 "the music library at /music-share is there but empty ... Nothing is
  written until it is back" - on a share that is mounted and full. The message
  actively misdirects the operator toward the mount. There is no override.
  Secondary cost: up to 50 stat()s against an SMB/NFS mount on the request path
  of every `allocate_name`, i.e. per item of every drop.
- Evidence: read the query and the loop; the only early exits are "no rows" and
  "one of these fifty exists".
- Ledger: new (the helper is the bug-hunt-2026-09-03 music-1/music-3 fix,
  KNOWN_BUGS line ~10446).
- Suggested fix: sample the NEWEST rows (`ORDER BY id DESC`) or a random
  sample, or cache a positive answer for a few seconds; and make the negative
  answer overridable, since the failure mode is "the whole write path is
  closed".

### music-6 - `HEAD /api/audio/{id}` answers 405, not the headers the module docstring promises
- Severity: low
- Confidence: CONFIRMED
- Where: `music/web/musicweb/routes_media.py:103` (`@router.get`)
- What: Starlette's plain `Route` adds HEAD whenever GET is registered; FastAPI's
  `APIRoute` does not. So the route that exists specifically to speak HTTP
  Range correctly ("That is why the app is mounted in-process by the dashboard
  rather than proxied") refuses the one method a client uses to discover
  `Accept-Ranges` and `Content-Length` before it starts seeking.
- Failure scenario: a player or an intermediary that probes with HEAD before a
  ranged GET (some Safari/AVFoundation paths, curl-based diagnostics, a future
  reverse proxy doing a liveness probe) gets a 405 and either falls back to a
  full download or reports the track as unplayable. Browsers' `<audio>` mostly
  use ranged GETs, which is why this has not bitten yet.
- Evidence: `TestClient` against `musicweb.main:app` with a 100-byte track:
  ```
  HEAD+Range status 405 ...   HEAD status 405
  GET206 206 bytes 0-9/100 10   unsat 416 bytes */100
  ```
  (The GET/Range/416 semantics themselves are correct - suffix ranges, inverted
  ranges, open-ended ranges and zero-length files all behave as documented.)
- Ledger: new.
- Suggested fix: `@router.api_route('/api/audio/{track_id}', methods=['GET',
  'HEAD'])` and return the headers with an empty body for HEAD (the
  `StreamingResponse` branch would otherwise send the body on a HEAD, since
  Starlette only special-cases HEAD inside `FileResponse`).

### music-7 - `/api/peaks` on-demand fallback can 500 with a traceback, and can `bytes(None)`
- Severity: low
- Confidence: PLAUSIBLE
- Where: `music/web/musicweb/routes_media.py:188-193`
- What: `data = _audio.peaks_from_file(path)` is unguarded.
  `peaks_from_file` -> `decode(path)` shells out to ffmpeg and will raise on an
  undecodable or truncated file; the route has no `try`. And the final
  `Response(bytes(data), ...)` runs even when `data` is falsy, so a `None`
  return is a `TypeError`. Both surface as a 500 with a traceback on a route
  that the SPA calls for every track the user clicks.
- Failure scenario: a base rig (the only host where the indexer imports) serves
  a track whose file is half-synced or has a broken header. Clicking it gives a
  500; the new MUSIC-13 frontend renders "The waveform could not be loaded (the
  server answered 500)", which is better than before but still tells the editor
  nothing, and the server log gets a traceback rather than a named cause.
- Evidence: read `routes_media.peaks` and `music_index/audio.peaks_from_file`
  (`return peaks(decode(path, sr=8000), n)` - no exception handling in either).
  Marked PLAUSIBLE because I did not exercise it with a real broken file.
- Ledger: new.
- Suggested fix: wrap the decode in `try/except Exception` and answer 404/503
  with the reason, the way the `ImportError` branch immediately above already
  does; and return early when `data` is empty.

## Coverage note

Not reached, and worth another pass:
- `ingest_batches.py` is 1,126 lines and I read roughly 60% of it. `precheck`,
  `create_batch`, `claim`, `expire_stale_leases`, `heartbeat`, `_recount`,
  `_check_transition` and the duplicate-detection helpers
  (`find_reencode`/`find_content_duplicate_by_digest`) were only skimmed.
- `db.py`: the query half (`load_matrix`, `load_window_matrix`,
  `unique_dest`, `content_hash`, `prune_missing`, `queue_*`) and the
  `migrations/` directory were not read. A migration-replay check against a
  0.7.34-era music.db was not attempted.
- `music/indexer/` is mostly unread: `export_audio_encoder.py` (1,000+ lines),
  `export_text_encoder.py`, `mel_numpy.py`, `music_index/{ingest,tagging,
  features,debias,proxies,vocab}.py`. The brief's "indexer's proxies/ingest path
  handling on Windows vs the container" is therefore only partly covered - I
  checked `config.share_root`/`_join_canonical`/`safe_join` (which are correct
  about a drive-style prefix on POSIX) but not `proxies.py`'s own path work.
- `static/ingest.js` (49 kB) was scanned for em dashes and root-relative URLs
  only, not read for logic. Its diff since 097f5a3 is 243 lines.
- `music/eval/` was not in scope and was not read.

What the suite does not cover:
- No test drives `allocate_name` with a failing connection or a failing
  filesystem, which is why music-1 is undetected; `test_ingest_batches.py`
  only exercises the happy collision path.
- Nothing anywhere tests the companion against the music server's actual
  refusals - there is no cross-tree test that asserts what `_post_result` does
  with a 409 `name_race` or a 503, which is music-2.
- `test_rescore_transaction.py` is single-threaded throughout, so music-3's
  interleaving cannot be caught by it.
- `test_media_range.py` asserts GET semantics only; no HEAD case (music-6), and
  no "file vanishes between `stat()` and the first `read()`" case (the
  generator in `chunks()` opens the file lazily, so that failure lands
  mid-response with headers already sent - I did not develop this into a
  finding because the window is genuinely tiny).
- `test_no_em_dashes.py` scans `music/web/musicweb` and `music/web/static` only.
  `music/indexer` is outside it; `export_audio_encoder.py:559,587` do contain
  U+2014, but only in a generated developer-facing markdown report, so I am not
  raising it as a finding.

Clean on the brief's explicit checks: no `import app` / `from app` anywhere in
the music tree (only `from musicweb.main import app`, which is the FastAPI
object); `drain.py` and `config.py` are stdlib-only by AST check and
`musicweb/__init__.py` imports nothing, so `python -m musicweb.drain apply`
still runs under a bare NAS python3; `identity.py` is byte-identical to
`ytdl/web/ytdlweb/identity.py` below its single marker; no root-relative
`/api|/media|/static|/app.js|/style.css|/ingest.js` URL in `static/`; `safe_join`
correctly refuses `..`, absolute paths, drive letters and post-resolution
escapes, and `mark_uploaded`/`item_uploaded` take no path off the wire at all;
`fleet_auth` fails closed on an unset `DASH_REPORT_TOKEN` and on an unset
`DASH_SESSION_SECRET`, and `stamp_ok` is inert unless `config.login_gated()`.

## OUT OF TERRITORY

- `companion/src/ccsync_companion/music_ingest.py:377-397` and
  `broll_ingest.py:2880-2895`: the companion half of music-2 - `_post_result`
  has no retry class, so a retryable server status ends the item. The b-roll
  `_post_result` at `broll_ingest.py:2363-2406` has the identical shape, so the
  same defect probably exists for b-roll's fleet ingest.
- `companion/src/ccsync_companion/broll_ingest.py:352-358`: `IngestClient._call`
  special-cases only 410; a 503 from any fleet route is indistinguishable from
  a 4xx to every caller.
