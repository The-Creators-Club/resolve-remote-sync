# verdicts — webapps

Verifier notes: repo read-only, HEAD 097f5a3. Repro scripts written to the
scratchpad (`scratchpad/repro/`), never into the repo.

## broll-1
- Verdict: CONFIRMED (medium)
- Reasoning: I tried to refute this three ways and could not. (a) Nothing
  writes `client_folder_items.share`/`rel_path` after the INSERT — the only
  UPDATEs against that table in `app/` are `note` (`:498`) and `ord` (`:518`).
  (b) `resolve_items` (`:595`) treats the by-id row as invalid when
  `(share, rel_path)` disagrees and then re-resolves BY NAME only, so a clip
  that kept its id but changed its path fails both tests and is dropped;
  `public_video_ids` is defined as that same set, so `_member_id` 404s its
  media too. (c) The trigger is a real, designed flow, not a hypothetical:
  `broll_index/sorter.py:80` calls `storage.record_moved` for every
  `sortable_videos()` row (`in_inbox=1 AND status='indexed'`), and
  `http_backend.record_moved` POSTs `/api/ingest/moved`, which is exactly the
  `UPDATE videos SET rel_path=?, in_inbox=0, status='sorted'` at
  `routes_ingest.py:271`. I checked whether inbox clips are even curatable:
  `search.py`'s status filter is a `!= skipped/excluded/ingesting` exclusion
  (`:1023`), not `= 'sorted'`, and nothing in the web app filters `in_inbox` at
  all, so an indexed-but-unsorted clip is searchable and `add_items` accepts
  it. The structural reason nothing fixes it up is that the items live in
  `client_shares.db` and `videos` in `broll.db` — deliberately separate
  (publish_db must not carry client links), so the moved route has no handle on
  the other file.
- Evidence: independent repro (not the hunter's script), real modules, two
  in-memory DBs, the only mutation being `UPDATE videos SET
  rel_path='Nature/A001.mp4'`:
  ```
  add:        {'added': [1], 'already': []}
  before:     [{'id': 1, ..., 'name': 'A001', 'note': ''}]
  after :     []
  public ids: set()
  member    : False
  panel     : [{'video_id': 1, 'share': 'broll',
                'rel_path': 'Inbox/A001.mp4', 'note': '', 'missing': True}]
  ```
  Severity holds at medium: the client's page silently loses a card and its
  media 404s, but nothing is deleted and the curator's panel does say
  `missing`.
- Fix note: the `videos.hash` idea is the right shape but needs one guard the
  hunter did not state — `hash` is not unique (the pipeline records
  `duplicate_of`), so accept a `(share, hash)` match only when it resolves to
  exactly ONE row, else fall through to the current drop. Order must stay
  id -> (share, rel_path) -> hash, or a rebuild that renumbers ids could
  resolve to a duplicate instead of the curated clip. The alternative fix
  (have `/api/ingest/moved` rewrite the items row) is possible but crosses the
  two-database boundary the client-shares design is built on, so it needs the
  shares connection injected into that route and must not make a failure there
  fatal to the move.

## broll-2
- Verdict: CONFIRMED (medium held, with a wider blast radius than filed)
- Reasoning: the read is right — `get_server` (`local_vlm.py:187-195`) drops
  `existing` on the floor; `stop()` (`:81`) is reachable only from
  `stop_all_servers()` and `atexit`. My attempt to refute it on frequency
  half-succeeded and half-backfired. It half-succeeded because the indexer's
  only caller (`local_vlm.py:489`, once per clip) is sequential and single
  threaded, so the "busy image encode" trigger the hunter describes cannot
  actually happen from this process — the server is idle at the moment
  `get_server` asks; the realistic triggers are narrower (a sleep/resume, a
  hung server, GPU contention pushing `/health` past 3 s). It backfired
  because the module is VENDORED into the companion
  (`companion/src/ccsync_companion/broll_vlm/local_vlm.py`, same code at
  `:212-220`) and driven by `broll_vlm_sidecar.py`, and there the "atexit
  reaps it eventually" mitigation evaporates twice over: the tray app is
  long-lived (atexit is the editor quitting, and a `Stop-Process` runs no
  atexit at all), and `stop_server()` -> `stop_all_servers()` iterates
  `_servers`, which no longer contains the orphan. So the sidecar's own
  documented promise — "`stop_server()` is how the orchestrator frees the VRAM
  the moment the editor comes back" — is exactly the thing that would fail: an
  8B VLM stays resident on the editor's GPU while they edit, and no product
  code can reclaim it.
- Evidence: `stop_all_servers` (`:225-231`) loops `_servers.values()` only;
  `broll_vlm_sidecar.py:589-613` calls the vendored `get_server`, `:617-623`
  calls `stop_all_servers`. Not reproduced live (needs a GPU + llama.cpp), so
  the trigger frequency stays estimated, which is why I did not upgrade to
  high.
- Fix note: `if existing is not None: existing.stop()` before the replacement
  is correct and safe — `stop()` is a no-op on an already-exited process and
  swallows its own exceptions. Do it in BOTH copies (indexer and the
  companion's vendored one) or the half that matters most is unfixed. The
  suggested "retry `_health` once with a longer timeout" is also right and
  cheap; keep the 3 s first attempt so the happy path is unchanged.

## music-1
- Verdict: DOWNGRADED to medium
- Reasoning: the gap is real and I could not refute it. I checked every
  upstream the brief named. `server/install_dashboard_app.py:1989` binds
  `{music_library_root}:/music-share:rw` and `:1784` sets
  `MUSIC_SHARE_ROOT=/music-share`, so an unmounted dataset presents as an
  ordinary empty directory. The dashboard's mount DOES carry a storage probe
  (`dashboard/src/ccsync_dashboard/music.py:401 _init_music_storage`, the
  MOUNTED-vs-DEGRADED decision) but it probes DATA_ROOT only — it opens
  `music.db` and applies the schema; it never touches `share_root()`.
  `musicweb` has no lifespan at all (that function's own docstring says so),
  and on the request path `_ingest_queued` calls `_require_ffmpeg()` and
  `_check_request_ceilings()` and nothing else before `queue_one` does
  `share_root().mkdir(...)` + `shutil.move`. `db.prune_missing`
  (`db.py:372-392`) refuses an empty scan for precisely this reason, so the
  asymmetry the hunter names is genuine.
  I downgraded on consequence, not on mechanism, for three corrections to the
  failure scenario: (1) the share is a BIND MOUNT in every shipped deployment,
  so the bytes land on the host filesystem under the unmounted mountpoint, not
  in the container's writable layer — a recreate does NOT delete them (they
  become invisible when the dataset mounts back over them, which is its own
  mess, but it is not destruction); (2) the source audio is a file the editor
  dragged from their own disk, so nothing the editor owns is lost — the loss
  is a false "queued" plus orphaned bytes on the pool; (3) the row does not
  stay silent forever, the base rig's `--queue` pass parks it `failed` with the
  path it looked at. Misleading success on a write path with no mount check is
  a real defect; "high" overstates it.
- Evidence: read of `_init_music_storage` (probes DATA_ROOT, not SHARE_ROOT),
  `_ingest_queued` (`routes_ingest.py:403-412`), `queue_one` (`:359-372`), and
  the compose volume/env lines cited above. No test in `music/web/tests`
  points `MUSIC_SHARE_ROOT` at an absent path.
- Fix note: the suggested guard is right and belongs beside `_require_ffmpeg()`
  in `_ingest_queued` (and `_ingest_inline`, which has the same exposure on the
  base rig). Two cautions: "non-empty" alone is a bad test for a brand-new
  customer's empty library, so prefer a marker file or `is_dir()` plus "the
  library has tracks and at least one of them is present", and do NOT drop the
  `mkdir` without checking the first-run path — a fresh deployment whose share
  root does not exist yet would then 503 on the first ever ingest. Refuse when
  the root is absent; create only when the deployment says it should.

## music-2
- Verdict: CONFIRMED (medium)
- Reasoning: the premise the hunter has to prove is that the LIVE index can
  re-score itself between the pull and the apply, and it can: fleet ingest's
  `write_item_result` calls `rescore.apply_for_track` at
  `ingest_batches.py:878`, which is `rescore_library(con)` verbatim
  (`rescore.py:291`) — it recomputes `debias` over the whole library
  (`save_debias`) and rewrites every track's tags/axes. The container can do
  this without torch: only the exported CLAP TEXT tower is needed and
  `MUSIC_TEXT_ENCODER_DIR` is mounted. On the other side, `drain._copy_rescore`
  copies the whole library's tags/axes/debias out of the PULLED COPY and
  `apply_bundle` (`:387-398`) hands them to `rescore.apply_bundle_rows`, which
  deletes and re-inserts per matching `rel_path` (and `debias` wholesale).
  `_reject_reason` guards `bundle_tracks`/`bundle_failures` only, so nothing
  compares the bundle's age against the live index's `meta.tagged_at`. The
  result is exactly what the hunter describes: overlapping tracks reverted to a
  pull-time population, tracks ingested since keeping the newer one.
- Evidence: `apply_for_track` -> `rescore_library` -> `db.save_debias` +
  `write_scores` + `set_meta('tagged_at')` (`rescore.py:246-299`);
  `apply_bundle_rows` skips only rel_paths the live index LACKS
  (`rescore.py:313-317`); `tests/test_drain_bundle.py:225` pins the overwrite
  as intended behaviour, so the suite would not see the regression. I could
  not find any guard, flag default or operator prompt that notices the
  divergence. Medium is right: the damage is silently skewed percentiles and
  facet counts, not a crash or a loss.
- Fix note: the FIRST half of the suggested fix would break something
  load-bearing. `apply_bundle` imports `musicweb.rescore` inside the branch on
  purpose (comment at `:387-395`): the apply is stdlib-only so it can be run by
  whatever python3 the NAS host has, over SSH per `music/web/DEPLOY.md`, and
  `rescore.rescore_library` needs numpy. Calling it from `apply_bundle` turns a
  stdlib apply into one that needs numpy on the NAS. Take the SECOND half
  instead: compare the live index's `meta.tagged_at` against the bundle's
  `created_at` and refuse (or skip) the rescore half with a named reason,
  leaving the operator to re-run `retag` on the rig or apply with
  `apply_rescore=False`. That is a pure-stdlib check and it fails in the safe
  direction.

## music-3
- Verdict: CONFIRMED (medium)
- Reasoning: `allocate_name` (`ingest_batches.py:206-227`) takes `conn` and
  never uses it, which is the finding in one line. Its collision set is
  `_taken_on_disk` plus `reserved_names`, and `_taken_on_disk` (`:255-265`) is
  explicitly asymmetric — any `OSError`/traversal counts as taken, but an
  absent or empty share root makes `exists()` answer False for every candidate,
  so a name that belongs to an indexed `tracks` row is handed out as free.
  `write_item_result` then runs `INSERT ... ON CONFLICT(rel_path) DO UPDATE`
  (`:809-833`), which replaces the existing row's embedding, dim, probe fields,
  model and `analyzed_at` in place, and `_write_windows` DELETEs first, so the
  old cue's windows go with it. I tried to refute it on the recovery path and
  it got worse rather than better: `created` is computed as "no tracks row at
  this rel_path", which is False here, so the music-4 stale-proxy drop does not
  fire and the old id keeps serving the old preview for the new audio; and
  `mark_uploaded`'s stat() will SUCCEED in the unmounted case (the upload lands
  on the bind-mount path it also reads), so even the 409 the hunter counted on
  as a partial brake is not reached.
- Evidence: read of `allocate_name` / `_taken_on_disk` / `reserved_names` /
  `write_item_result` as cited. Reachability is the weaker half and I kept the
  hunter's own hedge: it needs the library mount absent (music-1's state) or a
  `tracks` row whose file was removed without `--prune`, plus a name collision.
  In a healthy mounted library the disk check settles collisions correctly, so
  this is a degraded-state defect, which is what medium is for.
- Fix note: right, and cheap — `SELECT 1 FROM tracks WHERE rel_path = ?` over
  `_spellings(candidate)` next to `_taken_on_disk`, which is what the unused
  `conn` parameter was evidently for. Making an absent share root a refusal in
  `allocate_name` is also right but should be the same helper music-1's fix
  introduces, not a second private notion of "the share looks wrong".

## ytdl-web-1
- Verdict: CONFIRMED (high)
- Reasoning: reproduced against the real app. `grep -n "machine:" static/app.js`
  returns one hit and it is a comment; neither `runSearch`'s payload
  (`:1913`) nor `runUrls`'s (`:1972`) carries the key, while `loadProjects`
  (`:671-672`) does put `&machine=` on the GET. `NewJob.machine` /
  `NewUrlJob.machine` default to `None` (`routes_api.py:583`, `:...`), and
  `resolve_project(..., machine=None)` answers "unknown is not wired" and falls
  back to the ticked list, so the picker and the POST disagree for exactly the
  account CR-96 exists for. On the ledger question the brief asked: the entry
  is not lying in its own terms — it says the SPA "puts the hostname on
  `GET /api/projects`", and that is all it does. What it also says, twice, is
  that "a picker offering what the POST then refuses is the worse bug", and
  `test_the_wired_machine_of_a_mixed_account_is_offered_every_project`
  (`tests/test_api.py:127`) tests that claim by calling
  `projects.resolve_project(..., machine='owen-rig')` DIRECTLY in Python rather
  than by posting a job body. That is precisely the seam the defect lives in,
  so the suite proves the server can widen while the client never asks it to.
  Practical reach is narrower than "any editor" and I considered downgrading
  for it: it needs the fleet's local-download flag ON (the probe is gated on
  `localWanted()`, `app.js:2143`), a companion at 0.9.64+ answering `machine`,
  and a mixed wired/remote account. That is the owner's own shape and the
  literal reported symptom, so high stands.
- Evidence: scratchpad repro, `dashboard/.venv` pytest, `-p tests.conftest`
  against the real app with the CR-96 fixture seeding:
  ```
  OFFERED at wired rig: ['2025-ff4-nuclear', '2026-ff5-energy', '2026-ff5-water']
  POST /api/jobs {'term','project_slug':'2025-ff4-nuclear','quality','local':True}
    -> 400 'that project is not one you are syncing. Tick it on the dashboard first...'
  ```
- Fix note: the fix is right. Send `machine` on both payloads next to
  `local: localWanted()`; use `undefined`/omission rather than `''` when
  `localMachine` is null so an unknown machine keeps reading as "unknown", the
  degradation path the whole design rests on. Extending
  `test_the_picker_tells_the_server_which_computer_is_asking` to assert the
  POST body is the right test, but it must be paired with ytdl-web-2's fix or
  the widened job still dies at DOWNLOAD.

## ytdl-web-2
- Verdict: CONFIRMED (high)
- Reasoning: reproduced, and this one is worse than ytdl-web-1 because it
  needs no companion, no flag and no mixed account. `start_download`
  (`routes_api.py:1216`) calls `projects.resolve_project(user,
  job['project_slug'])` with neither `machine=` nor `local=`, i.e. the
  pre-CR-72-follow-up narrow rule, while creation at `:577` and `:842` passes
  `machine=req.machine, local=req.local`. I checked the brief's obvious
  refutation — that the job row remembers what it was created under — and it
  does not: `grep` over `schema.sql` and `migrations/*.sql` finds no `local` or
  `machine` column, so no correct answer is reachable from that function today.
  Because the fleet's `YTDL_LOCAL_DOWNLOAD` flag ships OFF, `localWanted()`
  returns false, the SPA posts `local: false`, half 1 widens the create for
  EVERY editor, and the DOWNLOAD button at the end of the review then answers a
  409 whose text ("no longer a project you sync") is false — the project was
  never ticked and never had to be. The same 409 catches the RETRY button on a
  finished or failed job.
- Evidence: scratchpad repro against the real app, no `machine_state` needed:
  ```
  POST /api/jobs/urls {urls, project_slug:'2025-ff4-nuclear', local: False}
    CREATE   -> 200 {'job_id': 1, 'phase': 'queued', ...}
  (phase forced to ready_for_review)
  POST /api/jobs/1/download
    DOWNLOAD -> 409 {'detail': '2025/FF4/Nuclear is no longer a project you sync,
                     so nothing can be downloaded into it. ...'}
  ```
- Fix note: of the two options offered, persist the create-time flags on the
  job row (a migration adding `local`/`machine`, defaulting to the pre-widening
  values so existing rows keep today's behaviour) and pass them back in here.
  The "just re-run with the same widening" shortcut is only safe if the flags
  are read from the JOB, not re-derived from the current request — a
  `start_download` that trusted a client-supplied `local=false` would let any
  editor download into any active project, which is the one thing this check
  exists to stop. The missing test is the one the hunter names: create ->
  `ready_for_review` -> DOWNLOAD for a widened project.
