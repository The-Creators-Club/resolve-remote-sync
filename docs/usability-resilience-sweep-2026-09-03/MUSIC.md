# Music tagger: CLAP search web UI + API, ingest, drain, rescore, indexer

## Summary
The engineering under this area is among the best in the repo: `drain.py`'s
bundle merge, `text_encoder.py`'s verified artefact, `routes_media.py`'s Range
parser and `db._check_swapped` are each careful, documented and tested. The
**usability** posture is the opposite: the whole ingest feature is reachable
only by dragging a file onto the page (there is no button anywhere), text search
silently discards every filter in the left rail, a failed search renders as
"Nothing matches. Try a looser description", the queue's parked-failure reasons
have no UI at all, and the batch cards speak the state machine's vocabulary
(`done_with_errors`). The biggest resilience risk is new: `rescore.write_scores`
opens with `DELETE FROM tags; DELETE FROM axes;` and nothing on the fleet-ingest
path rolls back, so one exception mid-rescore leaves an uncommitted
whole-library wipe on a pooled connection that a later write commits. The best
cheap win is an `[ ADD MUSIC ]` button plus wrapping the three query functions in
app.js in a try/catch that says what actually failed.

## Findings

### MUSIC-1: a failed rescore leaves an uncommitted "delete every tag" on a pooled connection
- **Lens:** resilience
- **Who:** editor (silently loses every facet), owner
- **Where:** `music/web/musicweb/rescore.py:163-186` (`write_scores`), called from
  `rescore.py:246-274` (`rescore_library`) ← `rescore.py:278-289` (`apply_for_track`)
  ← `music/web/musicweb/ingest_batches.py:872-881`
- **Today:** `write_scores` begins `con.execute('DELETE FROM tags')` /
  `DELETE FROM axes`, builds every row in Python, `executemany`s them and commits
  at the end. `sqlite3` auto-begins on the first DML, so from the DELETEs until
  the final `con.commit()` there is an open write transaction in which the
  library has no tags and no axes. The one caller on the live container path
  catches and *logs*: `log.error('music ingest: track %s written but not scored
  (%s: %s); it is searchable by similarity and has no tags until the next result
  or a base-rig --retag')` (`ingest_batches.py:876-879`) — **no `con.rollback()`**.
  The connection is the thread's cached one (`db.con()`), so it stays inside that
  transaction holding the writer lock; the next write on that same threadpool
  thread (another `result`, a `queue_add`, `/api/peaks`' INSERT) commits, and the
  empty `tags`/`axes` become permanent. Every other music write meanwhile waits
  out `timeout=30` and errors "database is locked". A plausible trigger is
  ordinary: `SQLITE_FULL` inside the `executemany` on a container whose data root
  filled (MEDIA-3's never-cleaned staging), or a MemoryError building ~9,000
  tuples. `drain.apply_bundle` gets this right (`drain.py:399-403` rolls back);
  the fleet path does not. `db.save_debias:431-436` has the same shape but
  commits immediately, so a transient empty `compute_directions` silently and
  permanently drops the source-bias axes.
- **Proposed:** wrap `rescore_library`'s body in `with con:` (or an explicit
  `try/except: con.rollback(); raise`), and make `ingest_batches`' handler call
  `conn.rollback()` before it logs. Then make the failure visible instead of
  log-only: set `meta['scores_stale'] = <iso>` on the same commit and have
  `/api/stats` return it, so the header reads
  `397 tracks · 24.1h · 9.5 GB · tags out of date since 14:02` and the operator
  has a reason to run `--retag`. An invariant (`invariants.py` shape:
  "tags is empty while tracks is not") would catch the wiped case on the next
  collector cycle.
- **Effort:** S   **Value:** critical   **Confidence:** high
- **Related:** MEDIA-19/MEDIA-20 (different failures, same "paid work lost
  quietly" family); not in the ledger.

### MUSIC-2: a broken search looks exactly like a search with no results
- **Lens:** both
- **Who:** editor, at `/music`, after pressing SEARCH
- **Where:** `music/web/static/app.js:454-467` (`runSearch`), `:443-452`
  (`loadTracks`), `:469-475` (`showSimilar`), `:417-420` (`render`),
  `:62-66` (`api`)
- **Today:** none of the three query functions has a `catch`. `api()` throws on
  any non-2xx; `$('#go').onclick = () => runSearch($('#q').value)` discards the
  rejected promise. Because `runSearch` calls `render([], 'Searching…', false)`
  first, the list is already showing `render`'s empty state:
  `'Nothing matches. Try a looser description or clear the filters.'` — and it
  stays there, under the headline "Searching…". So the text-encoder failing to
  load (`text_encoder.load()` raises `RuntimeError('no text encoder: neither an
  exported artefact in ... nor a music/indexer checkout')`, `text_encoder.py:498-501`),
  a 401 from an expired dashboard session, a 500 from MUSIC-1's locked database,
  and a genuinely empty result set are one screen. The advice it gives
  ("try a looser description") is actively wrong in three of the four cases.
- **Proposed:** `try/catch` in all three; on failure render a distinct state:
  `Search is not working right now (the server answered 503). Your filters and
  browsing still work. If this lasts, tell your admin: the music search model
  did not load on the server.` A 401 gets `Your session expired. Reload the page
  to sign in again.` and reloads. Keep "Nothing matches" for a real empty answer,
  and give it the right words for the other two callers ("Nothing similar
  enough to <name>", "No tracks match these filters").
- **Effort:** S   **Value:** high   **Confidence:** high

### MUSIC-3: the entire ingest feature is reachable only by dragging a file
- **Lens:** usability
- **Who:** editor, at `/music`
- **Where:** `music/web/static/ingest.js:143-150` (`miOpen`), its only two callers
  `:200` (inside `miHandleDrop`) and `:417` (inside `miPick`, which is itself only
  reachable from the open panel); `music/web/static/style.css:752-761`
  (`.dropzone {display:none}` until `.on`); `music/web/static/index.html:31-45`
  (the header controls: q, pool, SEARCH, clear, Resolve status, stats — no
  ingest control)
- **Today:** nothing on the page says music can be added. `#mi-panel` is `hidden`
  and only a drag opens it. Consequences beyond discovery: an editor who started a
  batch yesterday cannot look at it, cancel it, pause its uploads, or read why
  three tracks failed — the Batches list, the live progress block, the companion
  status dot and `[ recheck ]` all live inside a panel you can only reach by
  dragging a file you may not want to ingest. The admin's "All machines" tab
  (`ingest.js:978-1010`) has the same door.
- **Proposed:** an `[ ADD MUSIC ]` button in `.header-controls` beside `[ SEARCH ]`
  calling `miOpen()`, and a badge on it when `mi.batches` has anything not in a
  terminal state (`2 running`). One line of markup, one listener. Optionally
  re-open the panel automatically on load when the editor has a live batch, so
  "is my album in yet" is answered without a click.
- **Effort:** S   **Value:** high   **Confidence:** high

### MUSIC-4: typing a query silently throws away every filter in the left rail
- **Lens:** usability
- **Who:** editor, at `/music`
- **Where:** `music/web/static/app.js:454-467` (the POST body is
  `{query, k: 60, pool}` and nothing else), `music/web/musicweb/routes_api.py:127-148`
  (`SearchReq` has no filter fields; `search()` selects by id with no WHERE),
  versus `routes_api.py:90-124` (`/api/tracks`, which takes all seven)
- **Today:** the editor sets BPM 90-120, ticks the `mood: tense` chip, drags
  `arousal` to "top 20%", then types "driving synth for a chase". They get 60
  tracks scored on text alone. The rail still shows the chip highlighted, the
  slider at 20 and the numbers in the BPM boxes, so the page asserts the filters
  are on. `selectFacet` clears the query box (`app.js:480`) but no path clears the
  facet when a search runs, so the two states contradict each other on screen.
- **Proposed:** either (a) pass the filters: add the seven fields to `SearchReq`
  and intersect the `id IN (...)` set with the same WHERE `/api/tracks` builds
  (the hits are already an id set, so it is one extra clause), which is what the
  UI promises; or (b) if search is meant to be global, grey the rail out during a
  text search with the line `Filters do not apply to a description search.
  [ clear the search ]`. (a) is what an editor expects and is barely more work.
- **Effort:** M   **Value:** high   **Confidence:** high

### MUSIC-5: every track of a fleet batch re-scores the whole library and rebuilds the whole index
- **Lens:** resilience
- **Who:** editor (batch crawls), admin (dashboard stalls behind it)
- **Where:** `music/web/musicweb/ingest_batches.py:872-881` →
  `rescore.py:278-289` → `rescore.py:246-274`; and
  `music/web/musicweb/routes_fleet.py:181-197` → `:109-127` (`_refresh_search`)
  → `search.refresh` → `search.Index.__init__` (`search.py:204-233`)
- **Today:** one `POST .../items/{iuid}/result` does a full `load_matrix`, a
  `label_space` scoring pass, `DELETE FROM tags/axes` + reinsert of **every**
  track's ~22 rows, a `save_debias`, and then a complete `Index` rebuild
  (`load_matrix` + `load_window_matrix` + `projection.apply`). At today's 397
  tracks that is ~8,700 row writes and a ~2.5 MB matrix read per ingested track;
  a 200-track album drop costs ~1.7M row writes and 200 full rebuilds, serialised
  through the single-worker dashboard container's one SQLite writer, which is
  also serving `/api/report` for the whole fleet. `apply_for_track`'s docstring
  says "there is no cheaper honest version" — true of the *value*, not of the
  *frequency*. `_refresh_search` is additionally redundant now that
  `search._looks_stale` (`search.py:394-414`) notices a changed file within 2 s.
- **Proposed:** debounce rather than recompute. Write the track, mark
  `meta['scores_stale']`, and run `rescore_library` at most once every N seconds
  and once unconditionally at `release()` — a two-line coalescer keyed on a
  monotonic timestamp. Drop the eager `_refresh_search` call and let
  `_looks_stale` do it. Until scores land, `/api/stats` reports
  `tags catching up` so the panel can say so instead of the editor seeing an
  untagged track.
- **Effort:** M   **Value:** high   **Confidence:** high
- **Related:** MEDIA-14 (same single-worker scarcity, different consumer).

### MUSIC-6: `--export-drain` is a comment in three places and a constraint in none
- **Lens:** both
- **Who:** owner (non-technical), running the GPU drain
- **Where:** `music/indexer/index_music.py:407-409` (the flag is optional),
  `:474-489` (only reached `if args.export_drain`),
  `tools/indexer-entrypoint.sh:74-80` (the `drain` subcommand's warning is a shell
  comment), `server/publish_db.py:84-104` (`tables` for music is
  `("tracks","windows","tags")`; `read_live_counts:286-311` never looks at
  `ingest_queue`), `music/web/DEPLOY.md:315-320` ("step 4 ... still a lost-write
  window for anything else -- prefer 3a")
- **Today:** the safe path exists and is excellent (`drain.py`), and the unsafe
  path is one command away with no guard: `index_music.py --queue --db
  nas-index/music.db` (no `--export-drain`) followed by `publish_db.py --which
  music --apply` destroys every `pending` journal row and every track the fleet
  ingested into the live index since the copy was pulled, as long as under 10%
  of `tracks` is lost. Nothing in either tool mentions the other. For an owner
  who does this a few times a year from a ten-step hand-typed runbook with
  `sudo`, `-wal`/`-shm` copy rules and an ssh hop, "prefer 3a" is not a control.
- **Proposed:** two refusals and one wrapper.
  (1) `index_music.py --queue`: when `--db` resolves outside this host's own
  `MUSIC_DATA_ROOT` and `--export-drain` is absent, exit before the model loads
  with `you are draining a copy of another machine's index. Pushing this file
  back over the live one deletes every upload queued while this ran. Re-run with
  --export-drain <bundle>, or pass --i-am-rebuilding-from-scratch.`
  (2) `publish_db.py --which music`: read `count(*) FROM ingest_queue WHERE
  state='pending'` and `MAX(analyzed_at)` in `read_live_counts` and refuse when
  the live index holds pending rows or newer tracks (`--allow-clobber-queue` as
  the deliberate escape). This is MEDIA-4's proposal and it is still unbuilt.
  (3) a `tools/music_drain.py` that does pull → drain → export → apply → verify
  in one command, so the runbook is a command rather than a checklist.
- **Effort:** S (1+2), M (3)   **Value:** high   **Confidence:** high
- **Related:** MEDIA-4 (still open), CR-20, `docs/INDEXERS.md:226-269`.

### MUSIC-7: the ingest queue and its parked reasons have no UI at all
- **Lens:** usability
- **Who:** editor (browser-upload path), owner
- **Where:** `music/web/musicweb/routes_ingest.py:449-462` (`GET /api/ingest/queue`,
  returning `counts`, `failed`, `pending`); grep of `music/web/static/` finds
  **no caller** — only `tests/test_ingest_queue.py:465`
- **Today:** the route's own docstring is "without somewhere to read it the reason
  would only ever exist in the log of whichever indexer run happened to hit it",
  and that is the state it is in. `drain._apply_failures` (`drain.py:414-441`) and
  `music-3` went to real trouble to carry a failure's reason back to the live
  journal "so the reason is readable where the editor is looking" — and there is
  nowhere in the browser it is rendered. The only feedback an editor gets on the
  queued path is a 9-second toast: `Queued 2/2` plus `'nothing was analysed: this
  host has no GPU. They are in the library and will not be searchable until the
  base rig indexes them (5 waiting in all).'` (`app.js:594-604`). Reload the page
  and that is gone forever.
- **Proposed:** render it in the ingest panel, under the Batches list, whenever
  `counts.pending` or `counts.failed` is non-zero:
  `Waiting for the base rig: 5 tracks` and, per failed row,
  `✕ theme.wav - could not decode (moov atom not found). Nothing retries this on
  its own: fix the file and drop it again.` The route already returns exactly
  this. Same block belongs on the dashboard's own page for the owner, since
  `pending` is what tells them a drain is owed.
- **Effort:** S   **Value:** high   **Confidence:** high

### MUSIC-8: "Send to Resolve" on an older companion says "see its log"
- **Lens:** usability
- **Who:** editor whose tray app predates `/music/*` (CLAUDE.md: "the deployed
  build 404s on `/music/*`")
- **Where:** `music/web/static/app.js:288-300` (`sendToResolve`'s catch),
  `:248-252` (`companion()` throws `new Error('companion ' + status)`); compare
  the sibling `revealOnThisMachine` at `:326-334` and `ingest.js:69-73`
  (`MI_TOO_OLD`)
- **Today:** a 404 from an old companion arrives as `companion 404` and renders
  `the companion answered but refused the request (companion 404), see its log`.
  There is no log entry to see — the route does not exist — and an editor has no
  way to read the companion log anyway. Two neighbouring files already get this
  right: reveal says `an older build has no reveal; update the tray app`, and the
  ingest panel says `your companion app is too old for music ingest: update it
  from the tray icon (check for updates), then reload this page.`
- **Proposed:** attach `err.status` in `companion()` the way `miLoopback` already
  does (`ingest.js:340-356`) and branch: on 404,
  `your companion app is too old to send music to Resolve: update it from the
  tray icon (check for updates), then reload this page.` On any other status keep
  the current wording minus "see its log", plus the refused-origin hint
  (`loopback_guard.py` names the origin it refused; the page does not).
- **Effort:** S   **Value:** med   **Confidence:** high
- **Related:** MEDIA-6 (the origin allow-list half is still open).

### MUSIC-9: nothing refreshes the library after an ingest, and there is no way to sort by newest
- **Lens:** usability
- **Who:** editor, at `/music`
- **Where:** `music/web/static/ingest.js` — grep finds no call to `loadTracks`,
  `render`, `paintFacets` or `api('api/stats')` anywhere in the file;
  `routes_api.py:114-115` supports `sort=newest` (`t.analyzed_at DESC`);
  `app.js:427-436` (`filterParams`) never sends `sort` or `limit`;
  `routes_api.py:94` (`limit: int = 500`)
- **Today:** three compounding gaps. (1) A batch reaching `done` leaves the
  results list, the facets and the header stats exactly as they were — only the
  legacy browser-upload path re-renders (`app.js:620-632`). (2) There is no sort
  control at all, so a newly added cue is somewhere alphabetical among 397 rows.
  (3) `/api/tracks` truncates at 500 with no marker, so past 500 tracks
  "All tracks" says `500 tracks` and the library silently ends there.
- **Proposed:** when a batch's state becomes terminal, refresh stats and facets
  and render its landed tracks as `Just added` — the inline path's behaviour, one
  function away. Add a small sort control beside the result head
  (`filename · newest · bpm · length`) defaulting to filename, with `newest`
  selected automatically right after an ingest. Have `/api/tracks` return
  `truncated: true` with the real count and render
  `showing the first 500 of 812 - narrow it with a filter or a description`.
- **Effort:** S/M   **Value:** med-high   **Confidence:** high

### MUSIC-10: an absent or degraded music mount is a log line, and a swapped-in newer schema is a 500 on every request
- **Lens:** resilience
- **Who:** owner/admin
- **Where:** `dashboard/src/ccsync_dashboard/music.py:356-373` (DEGRADED path),
  `app.py:1223-1224` (`app.state.music_status`), `ui.py:170` (only
  `music_mounted` is read, to decide the nav link);
  `dashboard/src/ccsync_dashboard/alerts.py:1424-1512` (43 kinds, none about a
  mount); `music/web/musicweb/db.py:121-127` (`FATAL: ... user_version=N, newer
  than this app supports`)
- **Today:** if the music tree is missing, stale, or its data root is not writable
  by the container's uid, the MUSIC link simply disappears from the nav and the
  reason exists only as `log.error("music data root could not be prepared ...")`
  inside the container. Wave 4 built `notices` + `alerts` precisely so that a
  diagnosis stops being "a `log.error` into a log nobody opens", and this is one
  of the diagnoses it did not adopt. Second half: the newer-schema refusal is
  only checked at mount (`_init_music_storage`), so a `publish_db --which music`
  that lands a database written by a newer musicweb passes `_check_swapped`
  → `invalidate()` → `init()` raises inside every request. The mount still reports
  MOUNTED, the nav still offers the link, and every music page 500s.
- **Proposed:** one alert kind, `feature_mount`, evaluated from
  `app.state.{music,broll,ytdl,cards}_status`, SEV_WARN for ABSENT and SEV_ERROR
  for DEGRADED, whose `next action` names the actual cause the mount already
  logged ("`/music-data` is not writable by uid 3000: `chown -R 3000:3000
  <apps>/music-data`"). And catch the schema `RuntimeError` in `db.con()` once,
  record it as a notice, and have the routes answer 503 with
  `this server's music app is older than the index it was given (index v5, app
  v4). Update the dashboard, or restore the previous music.db.`
- **Effort:** M   **Value:** med-high   **Confidence:** high
- **Cross-cutting:** the same alert kind covers b-roll, ytdl and cards — hand to
  the DASH agent.

### MUSIC-11: the on-demand track fetch polls forever, with no elapsed time and no cancel
- **Lens:** both
- **Who:** editor on a remote machine, in the player pane
- **Where:** `music/web/static/app.js:267-285` (`for (;;)` re-POSTing
  `/music/send` every 1500 ms), `:255-256` (all pane buttons disabled for the
  duration), `companion/src/ccsync_companion/music_server.py:414-423`
- **Today:** the loop has no iteration cap, no deadline, no cancel and no clock.
  While a 60 MB wav crawls down a hotel-wifi link the pane reads
  `syncing the track to this machine…` (no percent when rclone has not reported
  one) and `similar` and `reveal` are disabled too. If the fetch stalls behind
  MEDIA-25's shared concurrency cap the message never changes and never ends;
  closing the pane does not stop the polling, and reloading the page abandons it
  with no record. There is no [ CANCEL ] anywhere for a music fetch.
- **Proposed:** show elapsed time and bytes when percent is absent
  (`syncing the track to this machine: 41 MB so far, 3m 20s`), stop polling when
  `state.playing !== t.id`, and after ~5 minutes with no progress movement swap
  to `still syncing. You can leave this page - the download keeps going. [ stop
  the download ]`, wired to a `POST /music/cancel_fetch` on the loopback
  (`FetchJob.cancel()` already exists and rclone writes `.partial`).
- **Effort:** M   **Value:** med   **Confidence:** high
- **Related:** MEDIA-25 (still open).

### MUSIC-12: the batch UI speaks the state machine's vocabulary
- **Lens:** usability
- **Who:** editor and admin, in the ingest panel
- **Where:** `music/web/static/ingest.js:867-870` (`${batch.state}${...} on
  ${batch.machine}`), `:1030` (`el('span','mi-batch-state', batch.state)`),
  `:895-901` and `:1074-1077` (`${item.state} · ${item.orig_name}`)
- **Today:** the cards render raw server enum values: `done_with_errors`,
  `claimed`, `queued_for_base_rig`, `indexed`, `uploaded`, `duplicate`. A batch
  header reads `done_with_errors on DESKTOP-7K2`. `queued_for_base_rig` is the
  MUSIC-ING-2 fallback and is the one an editor most needs explained — it means
  their audio is still on their own machine and they must drop it again — and it
  is shown as a bare identifier with no sentence. Batch cards also carry no time
  at all, so yesterday's and this morning's look identical.
- **Proposed:** one lookup table in ingest.js:
  `running` → `working`, `done` → `all done`, `done_with_errors` →
  `finished, some tracks failed`, `claimed` → `starting`, `cancelled` →
  `cancelled`; per item, `indexed` → `analysed`, `live` → `in the library`,
  `duplicate` → `already in the library`, `queued_for_base_rig` →
  `couldn't be analysed here - drop it again to upload it instead`. Add a
  relative time to each card head. Keep the raw value in `title=` for support.
- **Effort:** S   **Value:** med   **Confidence:** high

### MUSIC-13: a track with no stored waveform draws an empty box and says nothing
- **Lens:** usability
- **Who:** editor
- **Where:** `music/web/static/app.js:82-92` (`loadPeaks` returns an empty array
  on any non-2xx), `:105` (`drawWave` returns early on empty),
  `music/web/musicweb/routes_media.py:182-188` (a web-only host answers
  `404, 'no stored waveform and no indexer on this host to build one'`)
- **Today:** the container has no `music_index` to import, so every track whose
  `peaks` row is missing (a companion that sent no waveform, a row created by an
  older path, a `publish_db` from an index built before `--peaks` backfill) shows
  a blank strip. Click-to-seek still works over the blank strip, so it reads as
  "the waveform is broken" rather than "there is no waveform for this one". The
  server's carefully-worded 404 body is discarded by design.
- **Proposed:** distinguish 404 from a transport failure in `loadPeaks` and draw
  a flat mid-line plus a small caption inside the pane:
  `no waveform for this track yet - seeking still works`. If it is worth more,
  add a `peaks IS NULL` count to `/api/stats` so the owner knows a
  `index_music.py --peaks` backfill is owed.
- **Effort:** S   **Value:** med   **Confidence:** high

### MUSIC-14: the BPM and length filters silently hide every fleet-ingested track
- **Lens:** usability
- **Who:** editor
- **Where:** `music/web/musicweb/routes_api.py:105-108` (`t.bpm >= ?` — NULL is
  never true), KNOWN_BUGS MUSIC-ING-1 (the companion has no librosa, so `bpm`,
  `music_key`, `key_conf`, `lufs` are all sent null)
- **Today:** the ledger records that these tracks "fall out of" the BPM and
  duration filters; the UI does not. An editor who sets BPM 90-120 gets a result
  set from which every track added through the companion path is missing, with
  nothing on screen saying so, and no way to opt them back in. As the fleet path
  becomes the normal way to add music this grows monotonically.
- **Proposed:** cheapest honest interim: when a BPM range is active, append to
  the result head `(N tracks have no BPM and are not shown)` from a count
  `/api/tracks` can return, with a `[ include them ]` toggle that drops the
  clause. The real fix is the ledger's `--features-only` sweep.
- **Effort:** S   **Value:** med   **Confidence:** high
- **Related:** MUSIC-ING-1 (open by decision).

### MUSIC-15: the whole search index is rebuilt in RAM inside the dashboard container, with no ceiling
- **Lens:** resilience
- **Who:** owner (a customer with a big library), admin
- **Where:** `music/web/musicweb/search.py:204-233` (`Index.__init__` loads
  `track_mat`, `win_mat`, `dirs`, plus a projected copy `sim_mat`),
  `:437-450` (`refresh` builds the new one while the old is still referenced),
  `db.py:340-360` (`load_window_matrix` stacks every window row)
- **Today:** the docstring's premise — "397 tracks x 512 floats is under a
  megabyte" — is true today and scales badly: windows are ~12 per track, so
  10,000 tracks is ~120,000 x 512 float32 ≈ 245 MB for `win_mat` alone, plus
  `track_mat` and its projected copy, all resident in the container that also
  runs the fleet dashboard, and briefly **doubled** during every `refresh`. With
  MUSIC-5's per-result refresh a large batch does that repeatedly. Nothing warns,
  nothing caps, and the failure mode is the container OOMing, which reads to the
  owner as "the dashboard restarted".
- **Proposed:** no re-architecture needed yet — just make it visible and bounded.
  Log the matrix bytes at each build; add a `music_index_bytes` figure to
  `/api/stats`; and refuse to build over a configurable ceiling
  (`MUSIC_MAX_INDEX_MB`, default generous) with a clear 503 naming the number,
  rather than being killed. Combine with MUSIC-5's debounce so rebuild frequency
  is bounded too.
- **Effort:** S (visibility) / L (real fix)   **Value:** med   **Confidence:** med

### MUSIC-16: three small copy defects on the search page
- **Lens:** usability   **Who:** editor   **Effort:** S   **Value:** low-med
- **Where / today:**
  - `app.js:664-665` — the header stats line ends with the raw Hugging Face model
    id: `397 tracks · 24.1h · 9.5 GB · laion/larger_clap_music_and_speech`. That
    string means nothing to an editor and is the only place a third party's model
    name is shown to a customer. Move it to the `title=` tooltip.
  - `app.js:417-419` — `render`'s empty state is `'Nothing matches. Try a looser
    description or clear the filters.'` for all three callers, so a `similar`
    lookup with no neighbours and a facet with no members both advise rewording a
    description that was never typed. Pass the empty copy in per caller.
  - `app.js:526-532` — the four "Feel" sliders are mutually exclusive: changing
    one silently zeroes the other three (the API takes only one `axis`). The
    labels give no hint. Either render them as radio-style ("one at a time") or
    let `/api/tracks` accept several axes.
- **Confidence:** high

## Still open from 08-28
- MEDIA-4: `publish_db --which music` still clobbers the live queue and every
  fleet-ingested track — **not built** (`server/publish_db.py:97-103, 286-311`
  unchanged; see MUSIC-6 for the other half of the fix).
- MEDIA-5: a transient Hugging Face failure silently swaps the CLAP checkpoint —
  **not built**; `ingest_batches.py:786-796` still compares width only
  (`_library_dim`), and `body.model` is stored but never compared.
- MEDIA-13: a track row whose audio never lands is permanent and blocks its own
  re-ingest — **not built**; `db.find_reencode:551-583` still has no `is_file()`
  check, unlike `find_content_duplicate_by_digest:609-628` which does.
- MEDIA-17: staging inside the live library on a base rig, and
  `EXCLUDE_DIRS` with no dot-directory rule — **not built**.
- MEDIA-25 / MEDIA-26 / MEDIA-27 / MEDIA-29 (fetch cap and cancel, CLAP inference
  in the tray process, the long-file disagreement, the hardcoded
  `"Assets/Music"` on the fetch side) — **not built**; MUSIC-11 above is the
  browser-visible half of MEDIA-25.
- MEDIA-21 (NFD filenames) is **built** — `db.norm_stem:531-543` and
  `db.safe_upload_name:513` normalise NFC, `ingest_batches.py:243-244` tries all
  three spellings.

## Cross-cutting notes
- **DASH:** `alerts.ALERT_KINDS` has no check for a feature mount that came up
  ABSENT or DEGRADED. All four mounts (`music`, `broll`, `ytdl`, `cards`) fail
  the same way — the nav link vanishes and the reason is a container log line —
  and one registry row would cover all of them (MUSIC-10).
- **OPS/REL:** `server/publish_db.py`'s shrink check is content-table-only by
  design; the music index now has a *second* writer (the fleet) and a *third*
  (the drain bundle), so "is the candidate older than the live index" is a
  question the tool cannot currently ask. Same shape will apply to `broll.db`
  once client-share curation writes into it.
- **APP/companion:** `music_server.build_send_response` returns
  `{"ok": false, "state": "downloading"}` — a 200 with `ok:false` for a
  *progress* report. The b-roll `/insert` contract is the same, and both browsers
  poll it in an unbounded `for(;;)`; whoever owns the loopback contract may want
  one shared "long operation" shape with a cancel token.
