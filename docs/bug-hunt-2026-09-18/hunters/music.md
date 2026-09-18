# music - the music web app (`music/web/musicweb`, `music/web/static`) and the indexer (`music/indexer`)

Files read (with approximate coverage): `music/web/musicweb/config.py` (100%),
`fleet_auth.py` (100%), `routes_fleet.py` (100%), `routes_batches.py` (100%),
`routes_media.py` (100%), `ingest_batches.py` (~80%: names, batches, leases,
claim, result, uploaded, release), `rescore.py` (~70%), `db.py` (~60%:
schema/migrations/connection cache), `routes_ingest.py` (~30%: the credential
gate), `search.py` (~40%), `static/ingest.js` (the batch panel, take-over and
retry halves), `music/indexer/music_index/proxies.py` (100%),
`music/indexer/make_proxies.py` (~70%), `tests/test_bug_hunt_2026_09_11b_music.py`
(100%), `tests/conftest.py`. Cross-read for the wire only (not reported on):
`dashboard/src/ccsync_dashboard/music.py`, `companion/.../broll_ingest.py`
(`retry`/`run`), `broll/web/app/routes_batches.py`, `broll/web/static/ingest.js`.
Diffs read: `git diff 34a3c8f..HEAD -- music/` (EMPTY - nothing in this
territory changed in the week since the 09-11b fix pass) and
`git diff 18e69f3..34a3c8f -- music/` in full.

Tests run: `cd music/web; .venv\Scripts\python.exe -m pytest tests -q` ->
609 passed, 2 skipped. Plus an ad-hoc reproduction script run from the
music/web venv in the scratchpad (see music-1).

## Findings

### music-1 - a cancel that lands in the window between lease expiry and the next sweep wedges the batch in `running` for ever
- Severity: medium
- Confidence: CONFIRMED
- Where: `music/web/musicweb/routes_batches.py:181-192` (the `cancel` route), with
  `music/web/musicweb/ingest_batches.py:642-668` (`expire_stale_leases`)
- What: the route decides "nobody holds this batch, so finalise it" on the
  truthiness of `batch['lease_expires_at']`, not on `lease_live(batch)`, and -
  unlike `list`, `get_one`, `claim` and (since 09-11b) `retry-failed` - it does
  not call `expire_stale_leases(conn)` first. A batch whose lease has already
  run out but which no request has swept yet therefore takes the
  request-not-kill branch: `cancel()` sets `cancel_requested = 1` and nulls
  `lease_expires_at`, leaving the row `state='running'`, no live machine, and
  `lease_expires_at IS NULL` - which is exactly the predicate
  `expire_stale_leases` requires to be NOT NULL, so no later sweep can ever
  move it. Nothing else drives a batch terminal from that state.
- Failure scenario: an editor's laptop is switched off mid-drop. 300 s later
  the lease has expired. Before anyone loads the panel (or from a page whose
  last poll predates the expiry), the editor clicks `cancel`. The batch is left
  `running` with `cancel_requested=1` for ever: the panel keeps drawing it as
  live work with a `cancel` button and no `take over` button (that is drawn
  only for `queued`), the fleet routes 410 every claim ("this batch has been
  cancelled"), and the batch never reaches a terminal state. A second click on
  `cancel` does clear it (the branch now reads `not lease_expires_at` -> True),
  but nothing tells the editor to click twice.
- Evidence: reproduced from the music/web venv (scratchpad script):
  create batch -> claim as RIG -> set `state='running'`,
  `lease_expires_at='2026-01-01T00:00:00+00:00'` -> call the cancel handler:
  `cancel -> {'ok': True, 'state': 'running', 'cancel_requested': True}`,
  then `state='running' lease=None cancel_requested=1`,
  `expire_stale_leases swept: 0`, and after the sweep still
  `state='running' lease=None`. A second call answers
  `{'state': 'cancelled', ..., 'finalised': True}`.
- Ledger: new (the same shape exists in `broll/web/app/routes_batches.py:187`;
  see OUT OF TERRITORY)
- Suggested fix: call `ingest_batches.expire_stale_leases(conn)` at the top of
  the route as every other batch route does, and make the finalise test
  `if batch['state'] == 'queued' or not ingest_batches.lease_live(batch):`
  instead of testing the column for truthiness.

### music-2 - the take-over / retry buttons report every loopback 409 as "another of your computers is still working on this batch"
- Severity: medium
- Confidence: CONFIRMED
- Where: `music/web/static/ingest.js:1288-1300` (`miTakeOver`), and
  `companion/src/ccsync_companion/broll_ingest.py:1726-1729, 1795-1806`
  (the other side of the wire)
- What: `miTakeOver` catches the loopback error and branches on
  `e.status === 409` alone, discarding `e.message` and the body. The
  companion's `run()` answers 409 for three unrelated conditions, only one of
  which is another machine: (a) "this computer is already indexing another
  batch", (b) the `staging_id_missing` refusal added by comp-broll-music-1 in
  the 09-11b fix pass - "this computer has those tracks staged, but the request
  did not say which drop: reload the page and try again" - and (c) the
  dashboard claim's own 409, which is the only one the toast describes. The one
  message that names the action the editor must take is the one thrown away.
- Failure scenario: the editor drops an album, the page is reloaded (or the
  batch was staged in an earlier page), and they press `take over on this
  computer`. `staging_id` is sent empty by design (ingest.js:1293), the
  companion sees it is holding staging entries for those very files and refuses
  409 `staging_id_missing`. The page toasts "Another of your computers is still
  working on this batch." The editor goes and looks at their other machine,
  which is idle, and has no way to learn that reloading this page is the fix.
  Same for `miRetryFailed`, whose loopback call is wrapped in a bare
  `catch { }` (ingest.js:1358) so the refusal is not surfaced at all and the
  toast still says the tracks are queued.
- Evidence: read both halves. `broll_ingest.run` returns
  `409 {"reason": "staging_id_missing", "message": "... reload the page and try
  again"}` when `staging_id` is empty and `self._staging_holding(items)` is
  truthy; `miTakeOver` sends `staging_id: ''` unconditionally and its 409
  branch ignores the body.
- Ledger: new; the fix for comp-broll-music-1 (09-11b) created the refusal but
  music's page was never taught to render it. The same blind 409 branch is in
  `broll/web/static/ingest.js:ingestTakeOver` (OUT OF TERRITORY).
- Suggested fix: show the server's message when the body carries one (e.g. a
  `staging_id_missing` reason -> the reload hint), and keep the "another of
  your computers" wording for the claim's own 409 only.

### music-3 - the drop preview mints names that ignore every name already promised to an unlanded item
- Severity: low
- Confidence: CONFIRMED
- Where: `music/web/musicweb/ingest_batches.py:487-496` (`precheck`) vs
  `music/web/musicweb/ingest_batches.py:920-928` (`write_item_result`)
- What: `precheck` calls `allocate_name(conn, item.name, reserved=reserved)`
  with only the local, per-request set, while the real allocation at `result`
  passes `reserved=reserved_names(conn)` - every `dest_name` held by an item of
  any batch that has not landed yet. So the preview's collision set is a strict
  subset of the real one and the two answer differently for exactly the case
  the reservation ledger was built for.
- Failure scenario: editor A has a batch in flight holding `Theme.mp3` (the
  item row carries the allocated `dest_name`, the audio is still uploading, and
  nothing is on disk). Editor B drags in their own `Theme.mp3`; the precheck
  panel promises `Theme.mp3`, and when the result lands the track is written as
  `Theme (2).mp3`. The panel's "what it will be called" column - the one thing
  precheck exists to answer - was wrong.
- Evidence: read both call sites; `reserved_names(conn)` exists and is used at
  `write_item_result` only.
- Ledger: new
- Suggested fix: seed `reserved` from `reserved_names(conn)` in `precheck` (it
  still reserves nothing, which is the property the docstring defends).

### music-4 - `make_proxies --dry-run` dies on the files the real run survives, and over-counts the ones it cannot decode
- Severity: low
- Confidence: CONFIRMED
- Where: `music/indexer/make_proxies.py:149` and
  `music/indexer/music_index/proxies.py:52-64` (`_ffprobe`)
- What: `_ffprobe` documents "{} if unreadable" but only catches `ValueError`
  from `json.loads`; `subprocess.run` still raises `FileNotFoundError` (no
  ffprobe on PATH) and `subprocess.TimeoutExpired` (120 s) out of it. Every
  real-run caller is inside `build_all.one()`'s blanket `except Exception`, so
  those become one FAILED row; the `--dry-run` branch calls
  `proxies.source_info(src)` with no guard at all and the whole estimate dies
  with a traceback on the first such file. Separately, when `source_info`
  returns `{}` (no audio stream), `is_pointless({})` is False, so the dry run
  counts the file as BUILT with `duration=0` - while the real run raises
  `RuntimeError('no decodable audio stream')` and counts it FAILED, so the
  estimate promises proxies that cannot be made.
- Failure scenario: an operator runs `make_proxies.py --dry-run` over a library
  holding one truncated `.aac` whose ffprobe hangs past 120 s. The command
  exits with `subprocess.TimeoutExpired` and no summary at all, having already
  probed several hundred files. The same library runs to completion without
  `--dry-run`.
- Evidence: read `_ffprobe` (only `except ValueError` around `json.loads`; the
  `subprocess.run(..., timeout=120)` is outside any try) and both call paths.
- Ledger: new
- Suggested fix: wrap the `subprocess.run` in `_ffprobe` in
  `except (OSError, subprocess.SubprocessError): return {}`, and in the dry-run
  branch count an empty `source_info` as FAILED so the estimate matches the run.

## Coverage note
Not reached: `drain.py` (650 lines, the base-rig drain/apply path),
`text_encoder.py`, `vocab.py`, `identity.py`, `projection.py`, the second half
of `search.py` (`_looks_stale`, the facet/filter SQL), most of
`routes_ingest.py` (the multipart upload and transcode path), `static/app.js`
and `style.css`, and on the indexer side `index_music.py`,
`export_audio_encoder.py`, `export_text_encoder.py`, `mel_numpy.py`,
`music_index/ingest.py`, `features.py`, `debias.py`, `tagging.py` and
`music/eval/`. The suite itself does not cover: a cancel racing lease expiry
(music-1 - there is no test that calls `cancel` on a batch with a past
`lease_expires_at`); any of the loopback error bodies the page renders (the
09-11b JS tests assert on the SOURCE TEXT of `ingest.js` with regexes rather
than driving the page, so message quality is untested end to end); and the
`--dry-run` branch of `make_proxies.py`, which has no test at all. Nothing in
this territory changed since 34a3c8f, so the proxy-tiers / engine-pool /
busy-database work of the past week did not reach it - the one thing worth a
second look that I could not confirm is whether the dashboard's busy-database
rework (4aaca6a) changes what a `sqlite3.OperationalError` looks like to
`musicweb`, which opens its own connections with `timeout=30`, sets no
`busy_timeout` pragma, and shares no contention helper with `ccsync_dashboard`.

## OUT OF TERRITORY
- `broll/web/app/routes_batches.py:187`: the cancel route has music-1's exact
  shape (`not batch["lease_expires_at"]` with no `expire_stale_leases` first).
- `broll/web/static/ingest.js:1669-1673` (`ingestTakeOver`): music-2's blind
  `e.status === 409` branch, including for its own `staging_id_missing`.
- `companion/src/ccsync_companion/broll_ingest.py:1738-1742`: `run()` returns
  409 for "this computer is already indexing another batch", which no caller
  can tell apart from the dashboard's own 409 without reading the body.
