# Pre-launch bug hunt - lens `bug-music` (2026-10-06)

**Territory:** `music/web` (musicweb: routes_api, routes_media, routes_ingest,
routes_batches, routes_fleet, fleet_auth, ingest_batches, db, config, search,
rescore, drain, schemas, static SPA sinks), `music/indexer` (index_music.py,
music_index/ingest.py, make_proxies.py, music_models.py), the dashboard mount
(`dashboard/src/ccsync_dashboard/music.py`, the `_music_fleet_re` carve-out in
app.py), the companion's music loopback and ingest
(`music_server.py`, `music_ingest.py`, the parts of `broll_ingest.py` it
inherits: the drain loop, `_fail_item`, `_pump_uploads`, `_maybe_finish`, the
fleet client) and `server/publish_db.py`'s music spec.

**Method:** read end to end. Two throwaway probes ran against the repo code in
the scratchpad, on the music/web venv with temp databases: (1) a fleet `result`
carrying one window of the wrong width, then a search index rebuild; (2) a
10,000-track library, a single batch heartbeat, then `search.index()`.

**Checked against:** KNOWN_BUGS.md (the MUSIC-ING-n block, CR-55, CR-64, CR-116,
CR-152, MEDIA-21) and docs/bug-hunt-2026-09-24.md (bug-music-ytdl-1..4). Nothing
below repeats a FIXED item. bug-music-3 is the open twin of bug-music-ytdl-4,
whose fix covered only the cancelled path.

**Not covered in depth:** the CLAP sidecar download and verify path
(`music_clap_sidecar.py`, apart from the catalogue's sha256 pins, which are
real), `ingest.js` beyond its HTML sinks, `eval/`, and the exporters.

---

### bug-music-1 - Publishing music.db deletes every fleet-ingested track and the whole batch ledger
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `server/publish_db.py:88-135` (SPECS["music"]: `"drain": False`, `tables: ("tracks","windows","tags")`), `server/publish_db.py:404-418` (shrink check), `music/web/DEPLOY.md:237, 246-252, 321-355`
- **What:** The music spec says music.db holds no NAS-only rows except
  `ingest_queue`, which the base rig drains. That stopped being true on
  2026-08-18, when dashboard (companion) ingest arrived. The LIVE music.db is now
  the only place that holds: every fleet-ingested `tracks` row (its embedding
  was computed on an editor's laptop and exists nowhere else), its windows,
  peaks, tags and axes, and the whole `ingest_batches`/`ingest_items` ledger.
  This is the BROLL-1 shape exactly, but CR-152 fixed it for b-roll only: b-roll
  takes a drain and merges it back, and music still renames the base rig's file
  over the live one. The shrink guard cannot see the loss. It ignores the
  ledger tables, and it allows a 10% drop in `tracks`.
- **Scenario:** A customer has a 3,000-track library. Editors drop 200 tracks
  through the companion over a month. The operator re-indexes on the base rig
  (a new vocabulary, or a CLAP model bump) and runs `publish_db.py --which music
  --apply`, which DEPLOY.md calls "how you publish a re-index". 200 of 3,200
  rows is 6.25%, so the publish goes through. Three things then go wrong:
  - Every fleet track whose audio was not also re-swept by the base rig
    vanishes from search.
  - Every in-flight batch 404s on claim and heartbeat ("no such batch").
  - The ingest panel loses its history.

  Even tracks the base rig did re-sweep come back with different ids, so every
  `ingest_items.track_id` the editors' companions hold is wrong.
- **Recommendation:** Give music the b-roll treatment. Before the swap, take
  out of the live file: every `tracks` row that some `ingest_items.track_id`
  points at (with its children), and the two ledger tables. Merge them back
  after the swap, keyed by rel_path. Otherwise refuse the publish while the
  live file holds any `ingest_items` row the source lacks. Add `ingest_batches`
  and `ingest_items` to the refusal logic. Fix DEPLOY.md and the SPECS comment,
  which both say music has nothing to lose.
- **Known:** CR-152 (BROLL-1) fixed the b-roll half only. The music half is not recorded.

### bug-music-2 - A dropped connection or a timeout on the `result` POST fails the track for good (and can strand a track row)
- **Severity:** medium
- **Confidence:** CONFIRMED (code path); the timeout variant is PLAUSIBLE on NAS hardware
- **Where:** `companion/src/ccsync_companion/music_ingest.py:424-431` (`item["embedded"] = True` is set BEFORE `_post_result`), `music_ingest.py:540` (`item_result` is not guarded), `broll_ingest.py:249-271` (`default_request` raises on a transport error), `broll_ingest.py:2306-2313` (`_drain` fails the item), `broll_ingest.py:2340-2349` (a failed item with fewer than 2 attempts is handed straight back), `music_ingest.py:636-642`, `broll_ingest.py:114` (20 s timeout)
- **What:** music-2 (2026-09-11) made a 503 or `name_race` answer to `result`
  retryable, with backoff. It did not cover a TRANSPORT failure:
  - Connection refused while the dashboard container restarts (an OTA, a
    deploy, a NAS reboot) raises out of `default_request`.
  - So does a read timeout. The handler runs `rescore_library` inline. The
    first result after a restart also cold-loads the ~480 MB ONNX text tower
    and builds the 240-caption label space. On NAS CPUs that can pass 20 s.

  `_drain` catches the exception and fails the item (attempt 1). `_next_item`
  hands it straight back with no backoff. The second crunch sees
  `embedded=True`, so it skips the embedding and therefore skips the POST. It
  reaches `_enqueue_uploads` with no `dest_name` and fails "the library did not
  name this track" (attempt 2, final). In the timeout variant the server DID
  write the row and allocate the name, so it is left behind with no audio
  (see bug-music-3).
- **Scenario:** An editor drops a 15-track album. The admin deploys a dashboard
  update 4 minutes in. The track whose result POST lands during the roughly
  30-second restart is failed twice within a second and ends `failed`. The
  batch finishes `done_with_errors`. If the request timed out instead, the
  library also gains a searchable row whose audio 404s.
- **Recommendation:** Treat a transport exception from `item_result` as
  retryable: route it into `_result_retry_wait`'s backoff and keep the analysis
  in `_deferred_analysis`. Set `embedded=True` only after a 200. Make a failed
  item's retry re-POST the result whenever `dest_name` is empty. Consider
  pre-warming the text encoder and label space at mount time, so the first
  result is not the one that pays for them.
- **Known:** Not recorded. music-2 covers HTTP 503 and 409 `name_race` only.

### bug-music-3 - A track that fails after its `result` keeps a library row with no audio, which also blocks re-dropping it
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `music/web/musicweb/ingest_batches.py:1237-1293` (`release`: only `cancelled` calls `_drop_unlanded_tracks`), `ingest_batches.py:1296-1324` (selects only `indexed`/`uploading`), `music/web/musicweb/db.py:647-671` (`find_reencode` matches any tracks row), `companion/.../broll_ingest.py:3091-3110, 3150-3161` (an upload fails after MAX_UPLOAD_ATTEMPTS)
- **What:** `write_item_result` writes the `tracks` row before the audio
  exists. If the item then fails, its row stays. Ways it fails:
  - rclone fails 3 times;
  - `uploaded` answers 409 `not_uploaded`/`size_mismatch` until the budget is
    spent;
  - bug-music-2's timeout path.

  The batch is then released `done` (which becomes `done_with_errors`) or
  `failed`, and neither branch drops unlanded rows. The bug-music-ytdl-4 fix
  covered only `cancelled`. The orphan row:
  - shows in search, browse and similar, and its audio 404s;
  - counts in every percentile and the debias axes;
  - keeps its filename (`_track_state`);
  - makes `find_reencode` answer "already in the library as theme.wav" to a
    browser re-drop of the same file. So the editor's obvious fix (drop it
    again through the browser) is refused as a duplicate.

  RETRY FAILED rescues it only while the companion still holds the staged
  copy (7 days by default).
- **Scenario:** An editor on hotel wifi drops 12 tracks and the upload of
  track 7 fails 3 times. The batch ends `done_with_errors`. A week later the
  staging is pruned. Track 7 is still in /music search: it plays nothing, and
  Send to Resolve answers "couldn't sync the track from the NAS". Dropping the
  file again in the browser answers "already in the library".
- **Recommendation:** On every terminal release (not only `cancelled`), call
  `_drop_unlanded_tracks` for `failed` items that hold a `track_id` whose file
  is not on disk. Do the same in `expire_stale_leases`' finalise branch. Keep
  the slot only while a retry is actually possible, for example by deferring
  the drop until staging retention ends, or just re-allocating on retry. At
  minimum, have `find_reencode` ignore rows whose `ingest_items` state is
  `failed`.
- **Known:** bug-music-ytdl-4 (2026-09-24, FIXED for `cancelled` only). This failed-item twin is open.

### bug-music-4 - One malformed window vector takes text search and "similar" down for the whole fleet, and it survives restarts
- **Severity:** medium
- **Confidence:** CONFIRMED (probed)
- **Where:** `music/web/musicweb/ingest_batches.py:1088-1119` (`_write_windows` checks float32-ness and norm, never the width), `music/web/musicweb/db.py:349-358` (`np.stack` over every window), `music/web/musicweb/search.py:24-26, 230-262`
- **What:** The pooled embedding is checked against the library's width. The
  per-window vectors are not: any float32 vector with a non-zero norm is
  stored. `load_window_matrix` then `np.stack`s every window in the library, so
  one window of another width raises `ValueError: all input arrays must have
  the same shape`, and `Index()` can never be built again:
  - `/api/search` and `/api/similar` (and inline ingest's `index().clap`) 500
    for everyone;
  - a restart does not help, because the row is in the database;
  - the only cure is SQL surgery on the live file.

  The route is reachable by any editor's companion credential (shared or
  per-editor) on that editor's own batch. A companion bug that sent windows
  from a different tower would do the same without any malice.
- **Scenario (probe):** Seed one 512-d track and its window. Post a fleet
  result whose pooled embedding is 512-d with one window of 1 float. The
  result answers `indexed`. `search.refresh()` raises ValueError, and so does
  `search.index()` on a fresh process.
- **Recommendation:** In `_write_windows`, refuse (422) or drop any window
  whose size differs from the pooled `dim`. Make `load_window_matrix` and
  `load_matrix` skip and log rows of the wrong width, rather than failing the
  whole index.
- **Known:** Not recorded.

### bug-music-5 - A new customer with no GPU base rig gets a music page whose search 500s and whose fleet-ingested tracks are never tagged
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `music/web/musicweb/text_encoder.py:293-365` (falls back to `ClapTextEncoder`, which raises "no text encoder" in the container), `music/web/musicweb/rescore.py:110-118, 389-391` (rescore needs the same encoder), `dashboard/src/ccsync_dashboard/music.py:480-517` (`_init_music_storage` probes only the DB, so the mount is reported MOUNTED), `dashboard/deploy/compose.image.yaml:323` (`/music-encoder` is a data mount), `server/install_dashboard_app.py:5849-5862` (the encoder ships only from a base rig's `music/web/data/text_encoder`)
- **What:** Every text query and every tag computation in the container needs
  the exported CLAP text tower (about 482 MB). It is not in the image, and not
  on the release feed: unlike the audio tower, nothing sha-pins it in
  `music_models.py`. It reaches a NAS only when someone pushes it from a
  machine that ran `export_text_encoder.py`, which needs torch and a GPU host.
  A new customer installed from the vendor image (the zero-touch path) has an
  empty `/music-encoder`. As a result:
  - `/music/api/search` raises RuntimeError and returns 500.
  - Every fleet `result` writes its track, then fails `rescore_library`. The
    tracks are untagged, `scores_stale` never clears, and the facet rail stays
    empty.
  - The mount still reports MOUNTED and the nav advertises Music.

  The existing library is also never embedded without a base rig (the
  practicality half).
- **Scenario:** Customer #2 has a NAS and editor laptops, no RTX box. They
  install from the image and open /music. Typing any description shows "search
  is broken". The ingest panel drops land with no tags, and the panel says
  "tags are catching up" for ever.
- **Recommendation:** Publish the text tower on the release feed as a sha-pinned
  artefact, as the audio tower already is, and have the container (or the
  setup wizard) fetch and verify it. Until then, probe the encoder in
  `mount_music`, report DEGRADED with a sentence when it is absent, and hide
  the search box rather than 500.
- **Known:** Operator-facing NOTE in install_dashboard_app.py only. Not in KNOWN_BUGS or COMMERCIAL_READINESS.

### bug-music-6 - Any write to music.db (a heartbeat, a status checkpoint, a waveform cache) makes the next search rebuild the whole index
- **Severity:** medium
- **Confidence:** CONFIRMED (probed)
- **Where:** `music/web/musicweb/db.py:208-236` (`file_state` includes the -wal size and mtime), `music/web/musicweb/search.py:207-245` (`_looks_stale` leads to `refresh`), `music/web/musicweb/ingest_batches.py:779-792` (a heartbeat every 30 s), `routes_media.py:221-223` (a peaks INSERT on view)
- **What:** The stale check compares the file's identity, size and mtime,
  including the WAL. It cannot tell a new track from a lease heartbeat. So
  during any active batch (a heartbeat every 30 s, plus a status write per
  stage per item), every search more than 2 s after a write reloads every
  embedding and every window from SQLite and rebuilds the debias projection,
  on the dashboard's single uvicorn worker. Probe: 10,000 tracks x 12 windows,
  then one `heartbeat()`; the next `search.index()` took 0.67 s on a fast
  desktop. The windows matrix alone is about 245 MB, and the rebuild briefly
  holds two of them. At the library sizes a commercial customer will have
  (20-50k cues), that is seconds of CPU and up to a GB of memory per search,
  on the process that serves fleet status.
- **Scenario:** A studio with a 30,000-track library has one editor dropping an
  album. Every other editor's search on /music stalls for several seconds, and
  the dashboard's RSS spikes with each one. Other page loads queue behind it.
- **Recommendation:** Key staleness on what the matrices are built from, not
  on the file. For example, a `meta` counter bumped by every writer of `tracks`,
  `windows` or `debias` (`write_item_result`, `upsert`, `drain.apply_bundle`,
  `_drop_unlanded_tracks`, `prune_missing`, `save_debias`). Keep the inode
  identity check for swaps.
- **Known:** Not recorded. music-2 (2026-08-21) introduced the file_state check.

### bug-music-7 - Preview proxies from the base rig can play another track's audio after a drain, because ids diverge between the two copies
- **Severity:** medium
- **Confidence:** PLAUSIBLE
- **Where:** `music/web/musicweb/drain.py` `apply_bundle` (the upsert gives the live row its own id), `music/indexer/make_proxies.py:20-40` (proxies named by the base rig copy's ids), `music/web/DEPLOY.md:270-320` (step 3 makes the drained copy the base rig's copy; proxies ship "with the rest of the data root"), `music/web/musicweb/config.py:132-172`
- **What:** Proxies are keyed by `tracks.id` and chosen on existence alone. The
  base rig's copy and the live index assign ids independently whenever the
  fleet writes to the live index between pull and apply. The base rig drains
  queued track Q as id N+1 in its copy. Meanwhile, in the live index, a fleet
  ingest took N+1 for track F, and the drain apply gives Q id N+2.
  `make_proxies.py` on the base rig then writes `proxies/N+1.mp3` from Q's
  audio. Pushing proxies (`--music-data proxies|all`) lands it at the id the
  LIVE index uses for F. `drop_proxy` only protects ids at the moment a row is
  created, never against a later push.
- **Scenario:** After a routine drain and proxy refresh, an editor clicks a
  freshly ingested cue F and hears Q. The waveform and tags are F's, while
  `?original=1` and Resolve play the right file. This is the music-4 symptom,
  arriving by a different door.
- **Recommendation:** Name proxies by a stable key: a content hash or a
  rel_path digest, or a `proxy_key` column. Alternatively, make the push
  verify each proxy's id against the live index's (id, rel_path) and drop the
  ones that disagree.
- **Known:** Related to music-4 (2026-08-21, which fixed the in-process id reuse). This cross-copy path is not recorded.

### bug-music-8 - The fleet routes accept unvalidated shapes: `live` via /status skips the upload check, and a nested `probe` value is a 500
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `music/web/musicweb/ingest_batches.py:79-80, 797-825` (`live` is in ITEM_PROGRESS, so `uploading -> live` is legal through `set_item_state`), `music/web/musicweb/schemas.py:112-123, 161` (`probe: dict | None`, `size_bytes: int | None`), `ingest_batches.py:831-838, 1004-1006`
- **What:**
  - `POST .../items/{iuid}/status {"state":"live"}` is a legal transition, so a
    companion can mark a track live without `mark_uploaded`'s `stat()`. That
    breaks the module's own guarantee that `uploaded` is what verifies the
    audio arrived.
  - `probe` is an arbitrary dict whose values are bound straight into SQL.
    `{"samplerate": {"x": 1}}` (or an int beyond 2^63 in `size_bytes`) raises
    `sqlite3.ProgrammingError`/`OverflowError`. That is not an
    `IntegrityError`, so it escapes as a 500. The companion treats a 5xx as
    retryable and re-sends the identical body until its budget is spent.
- **Scenario:** A future companion build (or a hostile editor credential)
  posts `live` directly, and the track is counted live with no file. Or a
  probe dict with a nested value 500s every retry.
- **Recommendation:** Refuse `live` in `set_item_state` (only
  `mark_uploaded` may set it). Give `probe` a typed model (`samplerate: int |
  None`, `channels: int | None`, `codec: str | None` with max_length), and
  bound the integer fields.
- **Known:** Not recorded.

### bug-music-9 - Inline (base rig) ingest leaves the uploaded file in the library with no index row when analysis raises
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `music/indexer/music_index/ingest.py:145-171`
- **What:** After `claim_dest` and `shutil.move`, the file is in the library.
  Only `fields is None` unlinks it. `index_music.analyse_one` raising goes to
  the bare `except`, which returns an error and leaves the file. Two ways it
  can raise:
  - `audio.decode` on a truncated file that ffprobe accepted (routes_media's
    music-7 comment names this as the ordinary case);
  - a locked database in `upsert`.

  The file then stays in the shared library with no row. The editor sees
  "error", and their next drop of the fixed file lands as `name (2).ext` beside
  the broken one.
- **Scenario:** A half-synced wav is dropped on the base rig's /music page.
  ffprobe reads its header, decode fails, and a corrupt file is now in
  `Assets/Music`, visible to every editor over SMB and picked up by the next
  full sweep as a failing file.
- **Recommendation:** Wrap everything after the move in a try that unlinks
  `dest` (or moves it back to staging) on any exception before the row commits.
- **Known:** Not recorded.
