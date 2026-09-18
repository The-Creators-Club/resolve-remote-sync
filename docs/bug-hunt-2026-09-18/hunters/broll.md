# broll - the b-roll web app: `broll/web/app/*`, `broll/web/static/*`, migrations and schema

Files read (with approximate coverage): `git diff 34a3c8f..HEAD` and
`git diff 18e69f3..34a3c8f` over the whole territory (100%);
`broll/web/app/routes_api.py` (100%), `broll/web/app/edit_weight.py` (100%),
`broll/web/app/db.py` (100%), `broll/web/app/routes_ingest.py` (the upsert),
`broll/web/app/ingest_batches.py` (`ItemFiles`, `_allocate`, `claim`,
`_apply_probe`, `_resolve_under_root`, `mark_uploaded` - ~40%),
`broll/web/app/routes_fleet.py` (100%), `broll/web/app/schemas.py` (100%),
`broll/web/app/client_folders.py` (the 09-11b migration rework),
`broll/web/app/main.py`, `broll/migrations/012_geometry.sql`,
`broll/web/migrations/012_geometry.sql`, both `schema.sql`,
`broll/web/static/app.js` (the Send to Resolve body),
`broll/web/tests/test_insert_target.py` (100%), `test_migration.py` diff,
`test_fleet_ingest.py` diff. Read for the other side of the wire (not
reported on as territory): `companion/src/ccsync_companion/broll_server.py`
(`derive_insert_paths`, `plan_insert`, `build_insert_response`,
`run_proxy_upgrade`), `companion/.../ffmpeg_tools.py` (`probe_video`,
`is_edit_weight`), `companion/.../broll_ingest.py` (`_edit_proxy_skip`,
`_post_result`, `_post_uploaded`), `broll/indexer/build_archive.py`
(`archive_source`, `preview_source`), `broll/indexer/broll_index/pipeline.py`
(`stage_probe`), `dashboard/src/ccsync_dashboard/broll.py`
(`_init_broll_storage`), `server/publish_db.py`.

Tests run: `cd broll/web; .venv\Scripts\python.exe -m pytest tests -q` ->
626 passed, 1 warning in 59 s.

## Findings

### broll-1 - a null `original_rel` is turned back into "the preview IS the original", and the archive's own preview is then ledgered as a stand-in
- Severity: medium
- Confidence: CONFIRMED (mechanism), PLAUSIBLE (the operational harm)
- Where: `broll/web/app/routes_api.py:93-133` (`insert_target_detail`, the
  `original_rel = None` answers) and the other side,
  `companion/src/ccsync_companion/broll_server.py:764-772`
  (`derive_insert_paths`: `cleaned_original = _clean_rel(insert.get("original_rel"))`,
  falsy -> `derived["original_rel"] = rel_path`), consumed at
  `broll_server.py:1041-1053` (`broll_standins.record`).
- What: the detail object deliberately answers `original_rel: null` for the
  two cases where there is no original beside the preview (the stem-diverged
  archive-task-#23 clips, and any fleet-ingested clip whose original has not
  been uploaded yet - `original_uploaded: false` is a normal, supported
  state). The route's own docstring says "a caller must not read 'no
  original' as 'use the preview and pretend': that is what the flag is for".
  The companion does exactly that: an explicit null is treated as "the page
  said nothing" and `original_rel` falls back to the posted `rel_path`, which
  in precisely these cases IS the preview. `plan_insert` then sees a heavy
  original (weight `False`, from the row that describes the real original)
  plus a `preview_rel`, and returns `PLAN_FETCH_STANDIN` with
  `insert_rel: None`, i.e. "place the preview at the original's own path" -
  where "the original's own path" is the preview's own path under `Proxy/`.
- Failure scenario: an editor drops a 4K ProRes clip; the companion makes
  `Proxy/<stem>.mov`, uploads preview + editing proxy, and the original
  upload is still running (or was interrupted, plan section 6 "Upload
  interrupted"). `mark_uploaded` takes the clip live with
  `original_uploaded: false`, so no sibling exists above `Proxy/` and the
  detail object answers `original_rel: null, edit_proxy_rel:
  ".../Proxy/<stem>.mov", original_is_edit_weight: false`. A remote editor
  hits Send to Resolve: the companion downloads the preview to the preview's
  own archive path and calls `broll_standins.record(...)` on it. From then on
  `broll_standins.is_standin()` answers true for a file that is a genuine,
  lane-B-managed archive preview, not a stand-in - so every later insert of
  that clip answers "the stand-in for this clip is already in place" and
  re-runs the editing-proxy upgrade, and the ledger's `is_stale` retirement
  ("the next real file at that path retires the row") can never fire, because
  the file at that path is already the real one and will never change. The
  correct plan for this shape is `PLAN_PREVIEW_ONLY` (no ledger row, no
  upgrade thread).
- Evidence: read both sides. Web: `insert_target_detail` returns
  `original_rel=None` on the `len(matches) != 1` branch and on the
  non-`Proxy` branch, while `rel_path` falls back to `rel` (the preview) -
  pinned by `test_the_preview_only_fallback_reports_no_original`, which
  asserts `insert["original_rel"] is None` and
  `video["insert_rel_path"] == ".../Proxy/alone.mp4"`. Companion: the `for key
  in ("preview_rel", "edit_proxy_rel")` loop honours an explicit null, but
  `original_rel` has no such arm - the comment says "there is always an
  original", which is the assumption this case breaks.
- Ledger: new (related to CR-281, the proxy-tiers release).
- Suggested fix: make the null explicit on the wire and honour it - either
  have the companion treat `"original_rel" in insert and insert["original_rel"]
  is None` as "the page named the preview itself" and return
  `PLAN_PREVIEW_ONLY`, or have the web side stop advertising
  `edit_proxy_rel`/`original_is_edit_weight` when `original_rel` is null, so
  `heavy` can never be true for a clip that has no original to stand in for.

### broll-2 - migration 012 makes a published `broll.db` unreadable by any dashboard older than 0.7.49, and `publish_db.py` neither checks nor warns
- Severity: medium
- Confidence: CONFIRMED
- Where: `broll/web/app/db.py:62` (`CURRENT_SCHEMA_VERSION = 12`) and
  `db.py:212-220` (the deliberately fatal "newer than this app supports"),
  reached through `dashboard/src/ccsync_dashboard/broll.py:601`
  (`ensure_schema(...)` inside `_init_broll_storage`, whose exception marks
  the whole `/broll` mount DEGRADED); `server/publish_db.py` (no
  `user_version` handling anywhere - `grep -n "user_version\|version"` in
  that file returns nothing).
- What: `PRAGMA user_version` is stamped to 12 by the base rig's indexer, and
  the published file carries that stamp. A dashboard in the field on
  0.7.34..0.7.48 has `CURRENT_SCHEMA_VERSION = 11` and raises
  `RuntimeError: ... newer than this app supports` at mount time, which turns
  the entire b-roll search UI off (nav link hidden, `/broll` degraded), not
  just the new columns. The reverse skew is worse in a different way: because
  `ensure_schema` runs only at mount/boot, an OLDER (v11) file dropped under
  a RUNNING 0.7.49 container is never stepped, and `routes_ingest.ingest_video`'s
  INSERT (which now names `frames, start_tc, bitrate` unconditionally) and
  `ingest_batches._apply_probe` both raise `no such column` -> 500 on every
  ingest push and every fleet checkpoint until someone restarts the container.
- Failure scenario: an operator on a customer site runs
  `server/publish_db.py --which broll` from a base rig on this week's code
  against a dashboard they have not upgraded yet. The publish reports
  success; the b-roll tab disappears for every editor, with the reason only
  in the container log.
- Evidence: `db.py` raises rather than degrading gracefully by design (the
  comment says so); `dashboard/.../broll.py:610` comments that "the caller
  marks the whole /broll mount DEGRADED on an exception"; `publish_db.py`
  contains no version string at all.
- Ledger: new.
- Suggested fix: have `publish_db.py --which broll` read the source file's
  `PRAGMA user_version` and the target's before the swap, and refuse (or
  loudly warn) when the source is newer than what the deployed app carries;
  and re-run `ensure_schema` after a publish (the reload hook the music side
  already has) so a swapped-in file is stepped without a restart.

### broll-3 - the archive top slot is matched by an exact stem string, with no NFC/NFD normaliser
- Severity: low
- Confidence: PLAUSIBLE
- Where: `broll/web/app/routes_api.py:110-117` (`os.path.splitext(e)[0] ==
  preview.stem`).
- What: CLAUDE.md's CR-90 rule is that a path from one platform is not `==` a
  path from another and that comparisons go through a normaliser
  (`db.media_rel_key`, `links.normalise_declared`, `resolve_bridge._nfc`).
  This comparison is between `os.listdir()` bytes on the NAS and a stem
  stored in the DB. A file whose name reached the NAS in NFD (a Mac editor's
  rclone upload of a name it decomposed) will not compare equal to the NFC
  stem the DB holds, so `len(matches)` is 0, `original_rel` becomes null and
  the clip silently degrades to a preview-only insert - the same degraded
  path as archive task #23, but for a clip that does have an original.
- Failure scenario: a shoot folder with an accented or Hangul stem
  (`Matej Šimalčík`-shaped) ingested from the Mac in the fleet: Send to
  Resolve hands every remote editor the 540p/1080p preview instead of the top
  slot, and nothing reports why.
- Evidence: read only - I could not produce an NFD name on the live archive
  (read-only rule), so this is PLAUSIBLE rather than CONFIRMED. The
  neighbouring stat-based code is correctly NOT normalised (`_resolve_under_root`
  opens the path, where the bytes on disk are the truth).
- Ledger: related to CR-90 (the rule), new for this file.
- Suggested fix: compare `unicodedata.normalize("NFC", ...)` on both sides of
  the stem test only (never on the path that is then joined and stat'ed).

### broll-4 - `edit_proxy_rel` can name the preview itself
- Severity: low
- Confidence: CONFIRMED (by construction)
- Where: `broll/web/app/routes_api.py:119-128`.
- What: the editing proxy is derived as `<preview.parent>/<preview.stem>.mov`
  with no check that this is a different file from the preview. When the
  preview's own extension is `.mov` the two are the same path, and the object
  advertises an editing proxy that is the browsing preview. `build_archive`
  can produce exactly that: `preview_source` falls back to the TOP SLOT when
  no generated proxy exists (the audio-only `status='skipped'` case, BROLL-14),
  and that file keeps its own suffix (`dest_rel(..., preview.suffix.lower(),
  as_preview=True)`).
- Failure scenario: such a clip is inserted on a remote machine; the
  companion records `upgrade_rel` = the preview it has already downloaded and
  runs a background upgrade thread that re-fetches the same file and links a
  clip's preview as its own proxy. Harmless in outcome, but it is a
  background thread and a ledger row for a tier that does not exist.
- Evidence: `preview_source` in `broll/indexer/build_archive.py:252-276`;
  no equality guard in `insert_target_detail`.
- Ledger: new.
- Suggested fix: `if edit_proxy != preview` before the `is_file()` test.

### broll-5 - the zero-byte guard in `mark_uploaded` covers only the declared editing proxy, not the preview the server itself requires
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/web/app/ingest_batches.py:1165-1171` (`if actual == 0 and rel
  == edit_rel`).
- What: the comment's reasoning - "a zero-byte file is a transfer that died,
  not an upload" - applies verbatim to `slots.proxy` and `slots.original`,
  and those are the files the route adds to `required` itself with
  `declared.setdefault(rel, None)`, i.e. with NO declared size to compare
  against. A 0-byte file therefore passes presence and passes the size check
  (because `want is None`), and the clip goes live with an unplayable
  preview, which is the one file the search UI plays.
- Failure scenario: the companion's declaration for the preview carries
  `size: None` (its `landed[rel].get("size")` is absent - the queue entry was
  rebuilt after a restart) and the NAS holds a 0-byte file from a killed
  transfer: `mark_uploaded` returns `{"ok": true, "live": true}` and the clip
  is in search with a preview that plays nothing. Narrow, because the normal
  path declares a real size and would 409 on the mismatch.
- Evidence: read; the size-mismatch arm is guarded by `want is not None`, and
  the server-added slots are seeded with `None`.
- Ledger: new (part of CR-281's phase-5 work).
- Suggested fix: apply the `actual == 0` rule to every entry in `required`,
  not just `edit_rel`.

## Coverage note
Not covered: `search.py` (1,386 lines - the hybrid/fuzzy/RRF path is
untouched since 34a3c8f and I read only `BROWSE_PREDICATE`'s callers),
`client_folders.py`'s route surface beyond its migration rework,
`semantic.py`, `fuzzy.py`, `normalize.py`, `routes_share.py` and
`static/clientfolders.js` / `static/ingest.js` in any depth. The suite
(626 tests) does not cover: a `broll.db` whose `user_version` is ahead of the
app (broll-2 - `test_migration.py` only steps forwards), a preview whose own
extension is `.mov` (broll-4), a zero-byte preview (broll-5), or any NFD
filename anywhere (broll-3). `test_insert_target.py` pins the web side of
broll-1 exactly as it behaves and does not exercise the companion's reading
of it - the two sides are tested apart, which is how the null survived.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/broll_server.py:764-772`:
  `derive_insert_paths` has no arm for an explicit `original_rel: null` - the
  companion half of broll-1 (comp-broll-tiers / wire).
- `server/publish_db.py`: no schema-version check or post-publish
  `ensure_schema` on either index - the server-tools half of broll-2.
