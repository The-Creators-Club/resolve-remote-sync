# broll — b-roll web app (share links, media, ingest, search) + indexer

Files read (with approximate coverage):
- `broll/web/app/`: `routes_share.py` (100%), `client_folders.py` (100%),
  `routes_client_folders.py` (100%), `main.py` (100%), `config.py` (100%),
  `media.py` (100%), `routes_media.py` (100%), `routes_ingest.py` (100%),
  `fleet_auth.py` (100%), `routes_fleet.py` (~90%), `routes_batches.py` (~40%),
  `ingest_batches.py` (~40%: `_clean_rel_dir`/`archive_dir_for`/`_taken_names`/
  `_allocate`/`_resolve_under_root`/`mark_uploaded`), `search.py` (~55%),
  `semantic.py` (100%), `routes_api.py` (~50%).
- `broll/web/static/`: `share.html`, `share_gone.html`, `share.js` (~40%),
  greps over `sprite.js`/`clientfolders.js`/`share.css`.
- `broll/web/tests/`: `test_mounted_prefix.py` (100%), `test_client_folders.py`
  (the asset/URL section), `test_no_em_dashes.py` (header).
- `broll/indexer/`: `claude_client.py` (~50%), `hashing.py` (100%),
  `duplicates.py` (~40%), `ffmpeg_tools.py` (~40%), `local_vlm.py` (~45%),
  `local_runtime.py` (grep only), `pipeline.py` (~25%), `build_archive.py`
  (~30%), `storage/sqlite_backend.py` (~30%).

Tests run:
`cd broll/web; E:\Projects\broll-platform\web\.venv\Scripts\python.exe -m pytest tests -q`
-> **527 passed** in 109 s. Indexer suite not run (time-boxed).

Also ran three ad-hoc snippets from that venv: FTS5 behaviour on the
sanitizer's output (quoted-junk terms, 100-term AND, trigram short phrases —
all safe, no `OperationalError`), and the client-folder rename repro below.

## Findings

### broll-1 — a renamed or re-sorted clip vanishes from every live client link
- Severity: medium
- Confidence: CONFIRMED
- Where: `broll/web/app/client_folders.py:595` (`resolve_items`) and
  `:553` (`member_video_id`); trigger sites `broll/web/app/routes_ingest.py:250`
  (`POST /api/ingest/moved` sets `videos.rel_path`) and any re-index after a
  file rename.
- What: a `client_folder_items` row pins the clip's identity as
  `(video_id, share, rel_path)` and is **never updated afterwards** — nothing in
  `app/` writes those two columns after the insert (`grep` confirms only `note`
  and `ord` are ever UPDATEd). The identity re-check exists to defeat id REUSE
  after `publish_db.py` renumbers `videos.id`, but it cannot tell "this id is a
  different clip now" from "this is the same clip at a new path". So a *rename*
  fails the by-id check AND the by-name fallback, `resolve_items` drops the
  item, `public_video_ids` loses it, and `_member_id` 404s its media.
- Failure scenario: an editor curates `broll/Inbox/A001.mp4` into a client
  folder and sends the link. The sorter then moves the clip (`/api/ingest/moved`
  -> `rel_path = Nature/A001.mp4`), or the operator renames it and re-indexes.
  The client's page silently loses that card, its poster/sprite/proxy 404, and
  `n_items` shrinks — with no notice to the editor except a `missing: true`
  entry only visible if they reopen the panel. The clip is still in the index,
  under the same id.
- Evidence: repro from the web venv (temp DATA_ROOT, real modules):
  ```
  add:               {'added': [1], 'already': []}
  items before move: [{'id': 1, ..., 'name': 'A001', 'note': ''}]
  items after move : []
  public ids       : set()
  member_video_id  : False
  panel view       : [{'video_id': 1, 'share': 'broll',
                       'rel_path': 'Inbox/A001.mp4', 'note': '', 'missing': True}]
  ```
  (`UPDATE videos SET rel_path='Nature/A001.mp4'` was the only change.)
- Ledger: new. Adjacent to broll-1/broll-4/MEDIA-1/MEDIA-23 (all FIXED) — this
  is the *opposite* horn of the same identity problem those fixes created.
- Suggested fix: carry a third, rename-stable identity. `videos.hash` is
  already on the row and already the pipeline's fingerprint: store it on the
  item and accept a match on `(share, hash)` as well, refreshing the stored
  `rel_path` when it resolves that way. Failing that, have `/api/ingest/moved`
  (and the dashboard file-move path) rewrite `client_folder_items.rel_path` for
  the old `(share, rel_path)`.

### broll-2 — an unhealthy llama-server is replaced, never stopped (VRAM leak)
- Severity: medium
- Confidence: PLAUSIBLE
- Where: `broll/indexer/broll_index/local_vlm.py:187-195` (`get_server`)
- What: the warm-server cache keeps one handle per
  `(exe, weights, mmproj, gpu_layers, ctx)`. When the cached handle fails the
  liveness test — `existing.proc.poll() is None and _health(existing.url)`, with
  `_health` on a **3-second** timeout — a brand-new `llama-server` is started
  and `_servers[key] = handle` overwrites the entry. The previous handle is
  dropped on the floor: `existing.stop()` is never called. If the old process is
  still alive but merely slow to answer `/health` (busy image encode, a paused
  or swapping machine, a transient socket error), it keeps the whole Qwen model
  resident in VRAM while a second copy loads beside it.
- Failure scenario: a long `broll-index run` on the base rig hits one slow
  `/health` between clips. A second `llama-server` starts; on a GPU sized for
  one 8B VLM the new one either OOMs (the whole stage errors out) or both spill
  to host memory and the stage crawls. Each subsequent hiccup adds another
  orphan, and none is reaped until the interpreter exits (the `atexit` handlers
  do accumulate, so they do eventually die — but only at process end).
- Evidence: read of `get_server`; `stop()` at `:81` is reachable only from
  `stop_all_servers()` and from `atexit`, and `_servers[key] = handle` at `:195`
  discards `existing` without touching it. Not reproduced live (needs a GPU +
  llama.cpp), hence PLAUSIBLE.
- Ledger: new.
- Suggested fix: `if existing is not None: existing.stop()` before starting the
  replacement, and consider retrying `_health` once with a longer timeout before
  declaring an existing server dead.

### broll-3 — `start_server` leaks its log handle and orphans a hung process
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/indexer/broll_index/local_vlm.py:127` and `:145-155`
- What: `logf = open(log_path, "a", ...)` is never closed on any path — not on
  the "exited early" raise, not on the load-timeout raise, and not when the
  handle is later stopped. Every server start leaks one file object (released
  only by GC/interpreter exit). And the load-timeout path calls
  `proc.terminate()` with no `wait()`/`kill()` follow-up, unlike `ServerHandle.stop()`
  three lines up which correctly escalates: a `llama-server` still mmap-ing a
  10 GB model and ignoring SIGTERM is simply abandoned, holding VRAM, while the
  caller is told it never became healthy.
- Failure scenario: the model file is on a slow share and load exceeds
  `DEFAULT_LOAD_TIMEOUT_S`. The indexer reports "did not become healthy", the
  process survives the terminate, and the operator's next attempt fights it for
  the GPU.
- Evidence: direct read; `ServerHandle.stop()` (`:81-91`) is the correct
  pattern that this path does not reuse.
- Ledger: new.
- Suggested fix: wrap the wait loop in `try/finally` that closes `logf` when it
  is a real file, and replace the bare `proc.terminate()` with
  `ServerHandle(url, proc).stop()`.

### broll-4 — `sprite.js` is published past the tailnet but scanned by neither URL test
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/web/tests/test_mounted_prefix.py:113` (scans `app.js`,
  `index.html`, `style.css`, `ingest.js`) and
  `broll/web/tests/test_client_folders.py:526` (scans `share.html`, `share.js`,
  `share.css`, `clientfolders.js`); the file itself is
  `broll/web/static/sprite.js`, listed in `main.py:SHARE_ASSETS` and loaded by
  `share.html:82`.
- What: the document-relative-URL rule is pinned by two disjoint scans and
  `sprite.js` is in neither list, even though it is one of the seven files
  `SHARE_ASSETS` exposes under `/broll/share/assets/` — the one prefix an
  operator publishes past the tailnet with a Funnel. A future `/api/...` or
  `/media/...` URL added to it would 404 for every client viewer (and reach the
  dashboard root, not this app) with a green suite.
- Failure scenario: someone adds `fetch("/media/sprite/…")` to `sprite.js` for
  the editors' SPA; it works at `/broll/` for editors and breaks silently on
  every client preview link.
- Evidence: read both test lists; `grep -E "[\"'\`(]/(api|media|static|share|assets)/"`
  over `sprite.js` is currently clean, so this is a coverage gap, not a live
  break.
- Ledger: new (test gap, same family as broll-3 of 2026-08-21).
- Suggested fix: add `sprite.js` (and `favicon.svg`) to the
  `test_the_viewer_page_and_script_use_only_document_relative_urls` list — or
  better, drive both scans off `main.SHARE_ASSETS` so a file added to the mount
  is automatically pinned.

### broll-5 — `add_items` past MAX_ITEMS discards the clips that would have fitted
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/web/app/client_folders.py:461-476` (`add_items`)
- What: the `len(present) >= MAX_ITEMS` guard raises `ClientFolderError`
  mid-loop, after earlier iterations have already `INSERT`ed. The `conn.commit()`
  is only reached at the end of the loop, so the connection is closed unstamped
  by `get_shares_db`'s `finally` and sqlite rolls the whole batch back. The
  editor gets a 422 saying "a client folder holds at most 500 clips" and nothing
  was added, including the ones that fitted.
- Failure scenario: a folder holds 495 clips; the editor selects 20 and presses
  "+". All 20 are refused rather than 5 added and 15 reported. The message does
  not say the add was abandoned.
- Evidence: read of the loop; `conn.commit()` is outside it and
  `get_shares_db` closes without committing on the exception path.
- Ledger: new.
- Suggested fix: check capacity *before* the loop (`len(present) + len(new) >
  MAX_ITEMS`) and refuse up front, or stop inserting at the cap and report the
  overflow in the response alongside `added`/`already`.

## Coverage note

Not reached: `ingest_batches.claim`/`set_item_state`/`_check_transition`/
`expire_stale_leases` (the batch state machine and lease arithmetic — the
largest unaudited surface in the territory), `fuzzy.py` in full, the back half
of `search.py` (`search_videos`, paging, the browse tree), `routes_batches`
beyond the auth helpers, `app/db.py` migrations, `identity.py`,
`local_runtime.py`'s resumable multi-stream downloader (sidecar/slice logic),
`transcribe.py`, `taxonomy.py`, `rebase.py`, `compact_format.py`, and the
indexer's own pytest suite (not run).

What the suite does not cover, beyond broll-4: nothing exercises a clip whose
`rel_path` changes after curation (broll-1 has no test either way); the
`local_vlm` server-cache tests all pass `server_url`, so `start_server` /
`get_server`'s spawn-and-reuse path is never executed; and `mark_uploaded`'s
`_resolve_under_root` is tested for `..` but not for a symlink inside the
archive root pointing out of it (the docstring claims the resolve check covers
it, and it does — but only because `Path.resolve()` is called before
`relative_to`, which no test pins).

Verified-and-clean (checked, no defect found): the FTS5 sanitizer
(`sanitize_fts_query` — quoted-junk terms, 100-term ANDs and sub-trigram
phrases all return empty rather than raising); `_proxy_path`'s containment
check; `media.serve_file_with_range`'s Range/416/304 arithmetic; the
`SHARE_ASSETS` allow-list and its mount ordering; `share_gone.html`'s
self-containment and the `escape()` on the injected contact sentence;
`fleet_auth`'s two-credential gate and `hmac.compare_digest` usage;
`estimate_cost_usd` (the alias is resolved before pricing, so no silent
zero-cost); `hash_file_partial`/`hash_file_full`; `build_archive`'s
copy-to-`.part`-then-`replace` with `inplace_fixes.stash`; and `semantic.py`'s
cache key (an equality test, so a *decreasing* generation after a `publish_db`
swap still busts it).

## OUT OF TERRITORY
- `broll/web/app/routes_fleet.py` <-> `companion/`: `/claim` takes the machine
  name from the request BODY while every later route compares the
  `X-CCSync-Machine` HEADER (`_leaseholder_or_410`). If the companion ever
  spells the two differently (case, trailing dot, FQDN vs short name) the batch
  claims fine and then 410s `other_machine` on the first heartbeat. Worth one
  cross-check on the companion side.
