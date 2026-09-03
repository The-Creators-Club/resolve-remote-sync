# music — music/web (musicweb + static) and music/indexer

Files read (with approximate coverage):
- `music/web/musicweb/`: `main.py`, `config.py`, `db.py`, `drain.py`, `rescore.py`,
  `search.py`, `routes_api.py`, `routes_media.py`, `routes_ingest.py`,
  `routes_batches.py`, `routes_fleet.py`, `ingest_batches.py`, `schemas.py`,
  `fleet_auth.py`, `identity.py`, `projection.py`, `vocab.py`, `text_encoder.py`
  — all read in full (~100%).
- `music/web/tests/`: `test_mounted_prefix.py`, `test_media_range.py`,
  `test_no_em_dashes.py`, `test_drain_bundle.py` (grep + targeted read), others skimmed.
- `music/web/static/`: `index.html` fully; `app.js` / `ingest.js` / `style.css` scanned
  for root-relative URLs and em dashes (not read line by line).
- `music/indexer/`: `mel_numpy.py` in full, `index_music.py` (drain/queue/main halves),
  `export_text_encoder.py` and `export_audio_encoder.py` (staging/verify/params halves),
  `music_index/vocab.py`. Not read: `music_index/proxies.py`, `audio.py`, `features.py`,
  `make_proxies.py`, `music/eval/`.
- Cross-side: `dashboard/src/ccsync_dashboard/app.py` `_music_fleet_re` (matches
  `routes_fleet` route shapes exactly — no contract mismatch found).

Tests run:
- `cd music/web && .venv\Scripts\python.exe -m pytest tests -q` -> **483 passed, 2 skipped**
- `cd music/indexer && python -m pytest tests -q` -> **46 passed, 1 skipped**
- ad-hoc: `starlette.responses.FileResponse` header check (see music-5 note below);
  `music/web/.venv` package listing (confirms **no torch**, onnxruntime + numpy only —
  the CLAUDE.md invariant holds).

## Findings

### music-1 — an unmounted music share turns a drag-and-drop upload into a silent loss
- Severity: high
- Confidence: CONFIRMED (mechanism read end to end; not reproduced against a live container)
- Where: `music/web/musicweb/routes_ingest.py:360` (`queue_one`), with
  `music/web/musicweb/db.py:519-529` (`unique_dest`) and
  `server/install_dashboard_app.py:1784` (`MUSIC_SHARE_ROOT: /music-share`)
- What: `queue_one` does `config.share_root().mkdir(parents=True, exist_ok=True)`
  and then `shutil.move(staged, dest)`. Nothing anywhere on this route asks whether
  the share root is actually the mounted library. In the container the library is a
  bind mount at `/music-share`; when the underlying dataset is not mounted that path
  is an ordinary **empty directory** (DASH-5's exact shape, one layer over). `mkdir`
  is then a no-op, `unique_dest` sees no collisions because nothing is visible, and
  the upload is moved into the container's own writable layer.
- Failure scenario: the NAS dataset behind `/music-share` is offline (maintenance, a
  failed import, a mount that did not come back after a reboot). An editor drags four
  cues into the ingest panel. All four are answered `{"status": "queued"}`, four
  `pending` `ingest_queue` rows are written, and the four files sit inside the
  container. The next `docker`/app recreate deletes them. The base rig's later
  `index_music.py --queue` resolves `(share, rel_path)` on its own mount, finds
  nothing, and parks each row `failed: file is not at ...`. The editor was told the
  drop succeeded; the audio is gone and only the ledger disagrees.
- Evidence: `db.prune_missing` (`db.py:377-386`) refuses an empty scan with the words
  *"that is a share that is not mounted, not an empty library"* — the codebase already
  knows this hazard for the destructive path and does not apply it to the write path.
  `Path('/nonexistent/x').exists()` is `False`, not an error, so no branch here can
  distinguish "free name on the library" from "cannot see the library".
  `_require_ffmpeg()` is called before a byte is written for exactly this
  "refuse the whole request rather than half-apply it" reason; the share is not
  checked the same way. No test in `tests/` mounts an absent share root.
- Ledger: new. Same class as **DASH-5** (`KNOWN_BUGS.md:4094`, "an unmounted project dir
  wiped that project's NAS inventory", fixed 2026-08-28) — the wave-4 sweep fixed the
  dashboard's inventory walk and never reached `musicweb`.
- Suggested fix: before `_ingest_queued` writes anything (beside `_require_ffmpeg()`),
  refuse with 503 unless the share root exists **and** looks like the library — e.g.
  `share_root().is_dir()` and non-empty, or a marker file. Drop the `mkdir` from
  `queue_one`: creating the library root is a deployment act, never an ingest one.

### music-2 — a drain bundle rolls the whole library's tags, axes and debias back to pull time
- Severity: medium
- Confidence: CONFIRMED
- Where: `music/web/musicweb/drain.py:263-283` (`_copy_rescore`, `include_rescore=True`)
  and `music/web/musicweb/rescore.py:322-380` (`apply_bundle_rows`), applied from
  `drain.apply_bundle` (`drain.py:352-360`) and `index_music.py:478-487`
- What: `--export-drain` copies the **whole library's** `tags`/`axes` rows and the
  entire `debias` set out of the *pulled copy*, and `apply_bundle_rows` DELETEs and
  re-INSERTs them per matching `rel_path` on the live index (`debias` wholesale,
  "all or nothing"). That was sound when the base rig was the only producer of
  scores. Since 2026-08-18 it is not: dashboard fleet ingest writes `tracks` rows on
  the live index and calls `rescore.apply_for_track` -> `rescore_library`, which
  re-scores **every** track and recomputes the source-bias axes. Nothing in
  `_reject_reason` guards the rescore payload — the uid/content_hash agreement checks
  cover only `bundle_tracks` and `bundle_failures`.
- Failure scenario: operator pulls `music.db` at 09:00 and drains it on the base rig.
  At 09:20 an editor's companion lands two tracks through `/api/fleet/ingest`; the
  live index re-scores all 380 tracks and recomputes `debias` over 380. At 09:40 the
  operator runs `python -m musicweb.drain apply`. Every one of the 378 overlapping
  tracks has its `tags.pct`/`axes.pct` replaced by values percentile-ranked over the
  376-track pull-time population, the two fleet-ingested tracks keep their
  380-population values, and `debias` reverts to the 376-track axes that
  `search.Index` projects `/api/similar` through. The library is now scored against
  two different populations at once — CLAUDE.md's "every score in this database is
  relative to the library it was computed against" quietly violated, with facet
  counts and axis-range filters skewed and nothing anywhere reporting it.
- Evidence: `tests/test_drain_bundle.py:225` `test_the_library_wide_rescore_travels_with_the_bundle`
  pins precisely the overwrite (it mutates a `pct` on the rig, applies, and asserts the
  NAS row now carries the rig's value) — the test encodes the pre-fleet-ingest
  assumption and would not catch the regression. `rescore.apply_bundle_rows`'s own
  docstring only considers rel_paths the live index *lacks*, never rows it has
  re-scored since.
- Ledger: new (extends **CR-20** / MUSIC-13, `KNOWN_BUGS.md:783`, which fixed the
  file-copy overwrite for the journal rows but left the library-wide payload wholesale).
- Suggested fix: the container can compute these itself now. Have `apply_bundle` call
  `rescore.rescore_library(con)` after the merge instead of importing the pulled copy's
  library-wide rows (falling back to `apply_bundle_rows` only when no text encoder is
  loadable), or at minimum refuse the rescore half when the live index's
  `meta.tagged_at` is newer than the bundle's `created_at`.

### music-3 — `allocate_name` fails OPEN on a share it cannot read, and the result overwrites a live track row
- Severity: medium
- Confidence: CONFIRMED (mechanism); PLAUSIBLE that the unmounted-share trigger is hit in practice
- Where: `music/web/musicweb/ingest_batches.py:206-227` (`allocate_name`),
  `:255-265` (`_taken_on_disk`), `:270-276` (`reserved_names`), consumed at
  `:788-800` and `:809-833` (`write_item_result`'s `INSERT ... ON CONFLICT(rel_path) DO UPDATE`)
- What: a name is settled against (a) what is on disk and (b) names promised to
  *unlanded items* — never against the `tracks` table. `_taken_on_disk` is careful in
  one direction (any `OSError` or traversal error counts as **taken**) and fails open in
  the other: a share root that is absent or empty makes `exists()` return `False` for
  every candidate, so a name that already belongs to an indexed track is handed out as
  free. `write_item_result` then upserts on `rel_path`, replacing that track's
  embedding, dim, duration, model and analysed_at in place.
- Failure scenario: the library mount is missing or a `tracks` row's file was removed
  by hand without a `--prune`. An editor's companion posts a result for `theme.wav`;
  `allocate_name` returns `theme.wav`; the ON CONFLICT branch overwrites the existing
  `theme.wav` row. The old cue's `tracks.id`, its `peaks` and its `windows` are
  replaced (`_write_windows` DELETEs first), so the row now describes different audio
  while the id — and therefore the preview proxy — is unchanged. `mark_uploaded` will
  409 `not_uploaded` afterwards, which stops the item going `live` but does **not**
  undo the row that was already written.
- Evidence: `_taken_on_disk`'s own asymmetry (OSError -> taken, missing root -> free)
  makes the intent explicit and the gap visible. `reserved_names` deliberately excludes
  `cancelled/failed/skipped/duplicate`, so an item that reached `result` and then
  failed also releases its name back while its `tracks` row stands.
- Ledger: new; adjacent to music-4 (id reuse, `KNOWN_BUGS.md` CR-64) which fixed the
  proxy half of "a new track inherits an old one's identity".
- Suggested fix: add the `tracks` table to the collision set —
  `SELECT 1 FROM tracks WHERE rel_path = ?` (over `_spellings`) alongside
  `_taken_on_disk` — and make an unreadable/absent share root a refusal in
  `allocate_name` rather than an empty answer.

### music-4 — the mounted-prefix guard does not scan `ingest.js`, the largest shipped asset
- Severity: low
- Confidence: CONFIRMED
- Where: `music/web/tests/test_mounted_prefix.py:112` (`for name in ('app.js', 'index.html', 'style.css')`)
  and `:126` (`for path in ('/music/', '/music/app.js', '/music/style.css')`)
- What: `static/ingest.js` (1108 lines, added 2026-08-18 for the ingest panel and served
  by its own route in `main.py`) is not in either list, so the regression test that
  exists to stop root-relative app URLs reaching the browser does not look at the file
  most likely to grow one. `ROOT_RELATIVE` also has no alternative for `/ingest.js`.
- Failure scenario: someone adds `fetch('/api/ingest-batches/limits')` to `ingest.js`.
  The suite stays green; under the `/music` mount every ingest call resolves against
  the dashboard's origin root and 404s, and the panel reports "this companion is too
  old" — MUSIC-ING-5's symptom, with no test to catch it.
- Evidence: I grepped the four shipped assets with the test's own pattern extended to
  `/ingest.js` — **no current offenders**, so this is a coverage gap, not a live bug.
  `test_the_urls_the_index_asks_for_resolve_under_the_prefix` does *fetch* ingest.js
  (it is an `index.html` `<script src>`) but never inspects its bytes.
  The em-dash suite does cover it (`_static_files()` rglobs every `.js`).
- Ledger: new.
- Suggested fix: add `'ingest.js'` to both lists and `ingest\.js` to `ROOT_RELATIVE`;
  better, drive the file scan off `STATIC.rglob('*.js')` so a fourth asset is covered
  the day it is written.

### music-5 — a bundle row that fails the read-back leaves its `tracks` write committed
- Severity: low
- Confidence: CONFIRMED
- Where: `music/web/musicweb/drain.py:329-343` (`apply_bundle`)
- What: when the post-INSERT verification (`live is None or not live['dim'] or
  live['len'] != live['dim'] * 4`) fails, the row is appended to `report['skipped']`
  and the loop `continue`s — but the `INSERT ... ON CONFLICT` that preceded it is
  inside the one transaction that goes on to `con.commit()`. The module docstring's
  "each row's journal entry is marked `done` only after its track row has been written
  AND read back" holds for the journal; the malformed track row itself is kept.
- Failure scenario: a bundle carries a track whose `embedding` blob length disagrees
  with its `dim` (a truncated export, a hand-edited bundle). The apply reports
  `SKIPPED <uid>: write not verified` and exits 1, the journal row correctly stays
  `pending` — and a `tracks` row with a malformed embedding is now in the live index.
  `db.load_matrix` does `np.frombuffer` + `np.stack` over every non-null embedding, so
  a row of the wrong width raises inside `Index.__init__` and takes **every** text
  search and `/api/similar` down until it is deleted by hand.
- Evidence: read of the control flow; `load_matrix` (`db.py:335-345`) stacks without a
  width check, and `search.index()` has no guard around `Index(...)`. `created` is also
  not appended for such a row, so its stale proxy is not dropped either.
- Ledger: new.
- Suggested fix: `con.execute('DELETE FROM tracks WHERE rel_path=?', ...)` (or a
  SAVEPOINT per row) before the `continue`, so a row that could not be verified is not
  the one thing the transaction keeps.

## Coverage note
- Not examined: `music_index/proxies.py`, `music_index/audio.py`, `music_index/features.py`,
  `music_index/ingest.py`, `make_proxies.py`, `music/eval/`, and the bulk of
  `static/app.js` / `static/ingest.js` logic (only URL and em-dash scans there).
- The mel/torch parity story checks out on inspection (`mel_numpy` mirrors
  `transformers.audio_utils` including the complex64 round-trip and the
  `filters.T @ power` operand order) and `tests/test_mel_numpy.py` claims bit parity —
  but this rig's `music/indexer` run had **1 skipped** test, which is very likely the
  torch-backed parity test. **The numpy front end was therefore not actually compared
  against the torch reference in this session**; a divergence there would silently ruin
  every companion-computed embedding and is the single highest-value thing left to verify
  (run the indexer suite on a host with torch).
- What the suites do not cover at all: any state where the share root is absent or
  unmounted (music-1, music-3); a drain applied to an index that has been re-scored
  since the pull (music-2); `ingest.js`'s URL shape (music-4); a malformed embedding
  reaching `load_matrix` (music-5).
- Checked and found sound: the `musicweb` != `app` rule (no import of `app` anywhere in
  the tree; `identity.py`/`ingest_batches.py` document the vendoring instead; the web
  venv carries no torch); `parse_range` (multi-range, inverted, suffix, `bytes=-0`,
  zero-size, `start >= size` all correct, and HEAD works because Starlette adds it to a
  GET route); `FileResponse` does set `accept-ranges` on the no-Range path; the
  `/music` -> `/music/` redirect and every document-relative URL; `_music_fleet_re`
  against `routes_fleet`'s route shapes; `safe_join` traversal defences; the two
  `vocab.py` files (the indexer's is an alias module, so no drift); no em dashes in
  visible copy (its scan covers every static file and every non-docstring string).

## OUT OF TERRITORY
- none found while following calls out of this territory.
