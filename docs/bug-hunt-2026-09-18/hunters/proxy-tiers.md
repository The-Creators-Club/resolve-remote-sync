# proxy-tiers - the one feature read as ONE path: ingest -> upload -> index -> detail API -> page -> insert -> stand-in -> upgrade -> relink -> the wired rig

Files read (with approximate coverage): `docs/BROLL_PROXY_TIERS_PLAN.md` (100%),
`docs/BROLL_PROXY_TIERS_PLAN_AUDIT.md` (100%), `KNOWN_BUGS.md` CR-281,
`broll/web/app/routes_api.py` (`_insert_target`, `insert_target_detail`,
`_insert_object`, `_is_edit_weight`; 100% of the tiers half),
`broll/web/app/edit_weight.py` (100%), `broll/web/app/ingest_batches.py`
(`mark_uploaded`, `_apply_probe`, `_PROBE_*`, the settings parse),
`broll/web/app/schemas.py` (the three new fields), `broll/web/migrations/012_geometry.sql`
and its `broll/migrations` twin, `broll/web/static/app.js` (the insert POST body),
`broll/indexer/broll_index/ffmpeg_tools.py` `probe_video`,
`broll/indexer/broll_index/scanner.py` `VIDEO_EXTENSIONS`,
`companion/.../broll_ingest.py` (`_upload_plan`, `_enqueue_uploads`, `_pump_uploads`,
`_post_uploaded`, `_post_result`, `_status_fields`, `_edit_proxy_skip`,
`_mirror_locally`), `companion/.../broll_upload.py` (`UPLOAD_ORDER`),
`companion/.../broll_server.py` (`derive_insert_paths`, `plan_insert`, `_is_wired`,
`build_insert_response`), `companion/.../broll_standins.py` (100%),
`companion/.../proxy_relink.py` (`plan_relinks`'s phase-3 arms),
`companion/.../resolve_bridge.py` (`_attach_adjacent_proxy`, `perform_insert`,
`replace_clip`), `companion/.../ffmpeg_tools.py` (`probe_video`, `is_edit_weight`),
`broll/web/tests/test_insert_target.py` (100%). Read for context, reported on by
their owners: `docs/bug-hunt-2026-09-18/hunters/comp-broll-tiers.md`,
`.../comp-resolve.md`.

Tests run: `broll/web/.venv/Scripts/python.exe -m pytest tests/test_insert_target.py -q`
-> 13 passed (run from `broll/web`). Plus `git diff 34a3c8f..HEAD --stat --
companion/src/ccsync_companion/resolve_bridge.py` -> one commit, +39 lines, and a
grep of that diff for `_attach_adjacent_proxy` -> no hit (evidence for finding 1).

## Findings

### proxy-tiers-1 - "stop linking the 540p preview" was built in the relink pass only; every insert still attaches it, and the pass can never take it back
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/resolve_bridge.py:2873-2917`
  (`_attach_adjacent_proxy`, called unconditionally at `:3027`) vs
  `companion/src/ccsync_companion/proxy_relink.py:552-566` (the `.mp4` rule that
  WAS built), against `docs/BROLL_PROXY_TIERS_PLAN.md` section 6's table rows
  ("Wired ... link `edit_proxy_rel` if it exists, otherwise link nothing";
  "Remote, original on disk ... stop linking the 540p preview") and section 2's
  "apart from one change".
- What: phase 3's one behaviour change for EXISTING clips is that a browser
  preview is no longer linked as the Resolve proxy of a clip whose real file is
  on this machine. Two readers implement the offer of `Proxy/<stem>.{mov,mp4}`:
  `plan_relinks` (120 s pass) and `_attach_adjacent_proxy` (every insert). Only
  the first got the rule. The insert path still walks `expected_proxy_paths` and
  links the first file that exists, `.mov` then `.mp4`, with no question about
  whether the original is present.
- Failure scenario: a wired rig (or any machine holding the original) sends a
  legacy Creators_Club clip to Resolve. There is no editing proxy for those
  7,000-odd clips, so the insert links the 540p `Proxy/<stem>.mp4` exactly as it
  did before the release. The 120 s pass cannot undo it: `plan_relinks` skips
  every clip whose proxy IS working, which is now the whole point of audit F1.
  So the editor cuts at 540p under a full-quality original, permanently, on the
  machine the feature says gets "Original, with the good proxy or none", while
  CR-281 records the behaviour as changed.
- Evidence: `git diff 34a3c8f..HEAD -- companion/src/ccsync_companion/resolve_bridge.py`
  is +39 lines (the `Frames` enrichment and `_under_broll_archive`) and contains
  no hunk for `_attach_adjacent_proxy`; the function body at `:2888-2917` takes
  only `(media_pool_item, local_path)` and has no `original_present`/`is_standin`
  arm, unlike `proxy_relink.plan_relinks:552-566`, which has both.
- Ledger: "CR-281 does not fix the second of its three named defects on the
  insert path" (related to audit F1).
- Suggested fix: give `_attach_adjacent_proxy` the same two questions the relink
  pass asks (it already has `local_path`; `_original_on_disk` and
  `broll_standins.is_standin` are both importable there), and refuse a `.mp4`
  candidate for a clip whose original is present and not a stand-in.

### proxy-tiers-2 - a clip whose original is not in the archive folder turns the whole tier machine onto the PREVIEW: the project stores the preview's path for ever
- Severity: high
- Confidence: CONFIRMED
- Where: `broll/web/app/routes_api.py:104-133` (`original_rel = ... if len(matches) == 1 else None`,
  `"rel_path": original_rel or rel`) -> `broll/web/static/app.js:1692,1703` ->
  `companion/src/ccsync_companion/broll_server.py:766-772` (an explicit null
  original falls back to the posted rel) -> `:916-920` (`fetch_standin`);
  the enabling state is `broll/web/app/ingest_batches.py:219` (`upload_originals`)
  with `companion/.../broll_ingest.py:2766-2771`.
- What: "upload originals" is a per-batch checkbox (`broll/web/static/ingest.js:1293`).
  With it off, a clip goes live with a preview and an EDITING PROXY in `Proxy/`
  and nothing beside them, so `insert_target_detail` finds no sibling by stem and
  answers `original_rel: null` with `rel_path` = the preview. The companion maps
  the null original back onto the posted rel, so original == preview, and
  `plan_insert` still answers `fetch_standin`: fetch the preview to the preview's
  own path, ledger that genuine file as a stand-in, and import THE PREVIEW. The
  `edit_proxy_rel` the server just published is never considered as the file to
  insert - it is only linked as a proxy, to a clip that is itself the preview.
- Failure scenario: a shoot ingested with originals kept on the editor's own
  disk (the reason the checkbox exists). Every Send to Resolve puts a media pool
  clip at `P:\Assets\B-roll Archive\<dir>\Proxy\<stem>.mp4` into the project.
  Goal 2 of the plan ("the clip must point at the archive original, so a wired
  rig gets the full file with no relinking") is broken permanently and silently:
  the file at that path IS the preview on every machine, so no relink, refresh
  or later upload can ever repair the project - and `broll_standins` now holds a
  row warning that a correct file is a lie, which makes `is_standin()` true for
  ever (its size never changes), exempts it from the watcher's missing count and
  restarts an editing-proxy upgrade on every re-insert.
- Evidence: the companion half of the mechanism is comp-broll-tiers-4, proven
  there with a `derive_insert_paths`/`plan_insert` snippet; what that hunter
  could not see from inside the companion is that `original_rel: null` is not
  four legacy stem-diverged clips but (a) a first-class ingest MODE and (b) the
  answer for any clip whose original has not landed. `broll/web/tests/test_insert_target.py:198-212`
  pins the null as correct and asserts nothing about what a caller should then do.
- Ledger: new (extends comp-broll-tiers-4 across the wire; not in the plan, not
  in audit F1-F11).
- Suggested fix: on the server, answer the insert object with the tier that
  actually exists - when there is no original, the insertable file is the
  EDITING PROXY if there is one, else the preview, and say which - and on the
  companion treat a resolved `original_rel == preview_rel` as `preview_only`
  (record nothing), as comp-broll-tiers-4 suggests. The two halves are needed
  together: only the server knows an editing proxy is there, only the companion
  decides what it imports.

### proxy-tiers-3 - the container losing sight of the archive turns every insert into proxy-tiers-2, and nothing anywhere says so
- Severity: high
- Confidence: CONFIRMED
- Where: `broll/web/app/routes_api.py:106-110` (`except OSError: entries = []`)
  and `:120-127` (the same swallow for the editing proxy)
- What: `insert_target_detail` discovers both the original and the editing proxy
  by listing the archive folder inside the dashboard container. An OSError -
  the NAS dataset unmounted, an SMB/NFS hiccup, `BROLL_DATA_ROOT` wrong after an
  image update - is swallowed into "no entries", which is byte for byte the
  answer for "this clip has no original". The response carries no distinction
  and the route logs nothing.
- Failure scenario: the archive mount drops for ten minutes. Every Send to
  Resolve in that window follows proxy-tiers-2: a false stand-in ledger row on
  the editor's machine and a Resolve project pointing at the preview's path -
  damage that outlives the outage by for ever, on projects nobody will re-check.
  The dashboard shows no error, because the detail view is otherwise complete.
- Evidence: `broll/web/tests/test_insert_target.py:239-255`
  (`test_a_missing_archive_directory_answers_without_a_proxy`) is exactly this
  case and asserts `original_rel is None` and `edit_proxy_rel is None` as the
  desired answer - the suite pins the conflation. Ran it: 13 passed.
- Ledger: new.
- Suggested fix: distinguish "looked and found none" from "could not look":
  on OSError answer `original_rel`/`edit_proxy_rel` absent (not null) or add an
  explicit `insert.known: false`, refuse the insert object rather than publish a
  wrong one, and raise a notice (`dash-collector-alerts` owns the registry) -
  an archive the container cannot list is a server fault someone must act on.

### proxy-tiers-4 - the wired rig, which is the point of the whole design, has no working signal that a clip was born from a stand-in
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/proxy_relink.py:540-548` (the `refresh`
  expression) and `companion/src/ccsync_companion/broll_standins.py:22-38,102-112`
  (the ledger is `<log dir>/state/broll_standins.json`, per machine), against the
  plan's section 6 last row ("a clip is born from a stand-in when its stored
  `Frames`/`Resolution` disagree with the file at its path, OR the ledger says so")
- What: a stand-in is placed on the REMOTE editor's machine; the ledger row is
  written there and nowhere else. The wired rig that later opens the project has
  an empty ledger for those paths, so the "or the ledger says so" half of the
  rule can never fire on the only machine that needs it - it is used there only
  to SUPPRESS a refresh (`not is_standin()`). What remains is
  `_geometry_disagrees`, i.e. an `ffprobe -count_packets` of every archive clip
  every 120 s (comp-resolve-2's cost), whose one action is
  `replace_clip(<same path>)`, which returns "Already linked" without calling
  `ReplaceClip` (comp-resolve-1). So the last row of the plan's table - the row
  that carries goal 2 - has no mechanism that works, and none that could be made
  cheap by local state.
- Failure scenario: a remote editor cuts twenty archive clips from stand-ins and
  hands the project to the base rig. The base rig ffprobes the whole archive pool
  every two minutes for ever, "refreshes" every clip successfully without
  refreshing anything, burns `resolve_journal.allow_automatic`'s 8 grants a day
  (so genuine proxy relinks are held for the rest of the day), and the clips keep
  1920x1080 / the preview's frame count and timecode over 6K originals - which is
  what a conform, a render range and every timecode-matched proxy link then use.
- Evidence: comp-resolve-1 and comp-resolve-2 (both CONFIRMED there) are the two
  halves; what neither could see from inside the companion's Resolve surface is
  that the ledger CANNOT be the cheap alternative, because it is per-machine
  state describing an event that happened on a different machine. `record()` is
  called only in `broll_server.build_insert_response:1077`, on the machine doing
  the insert; nothing sends a stand-in fact to the dashboard or into the project.
- Ledger: "CR-281's wired-rig row does not work" (the live check it depends on is
  in CR-281's own "still owed" list, which is why it shipped unnoticed).
- Suggested fix: fix comp-resolve-1 first (a `force` on `replace_clip`), then
  make the fact travel with the PROJECT or the FLEET rather than with the machine
  that lied - a marker/metadata field on the media pool clip, or a stand-in
  report field the dashboard holds per (machine, archive rel) - so the wired rig
  asks one cheap question per clip instead of demuxing the archive.

### proxy-tiers-5 - "usable from the moment the editing proxy lands" is not what the code does: a clip stays invisible until its multi-GB original has finished uploading
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_ingest.py:2935-2981` (`_pump_uploads`:
  `missing = [rel for rel in rels if rel not in landed]`, and `_post_uploaded`
  only after every rel landed) and `broll/web/app/ingest_batches.py:1204-1210`
  (`status = 'indexed'` is written only by `mark_uploaded`), against plan
  section 5 item 5.
- What: the upload ORDER was implemented (`broll_upload.UPLOAD_ORDER` puts the
  editing proxy at 3 and the original at 4), but nothing consumes the order: the
  item posts `/uploaded` once, after the LAST file lands, and `videos.status`
  leaves `ingesting` only there. Browse, tree and search all skip an `ingesting`
  row, so the clip is not findable, let alone insertable, until the original is
  fully on the NAS - which for a 40 GB camera master is the whole point the
  ordering was supposed to buy.
- Failure scenario: an editor ingests a day of 6K material over a home link. The
  editing proxies are on the NAS within minutes; the archive shows nothing for
  the next eight hours. The feature's stated benefit is absent, and the only
  signal is the ingest SPA's progress bar.
- Evidence: read both halves. `mark_uploaded` already accepts
  `original_uploaded=False` (it requires `slots.original` only when the flag is
  true) and records it on the row, so the server side is ready for a two-stage
  report; no companion path ever sends the first stage.
- Ledger: new ("listed as built that the code does not do", the lens's own test).
- Suggested fix: post `/uploaded` with `original_uploaded=False` as soon as the
  stills, preview and editing proxy have landed (the server already stores the
  flag and flips the row live), then post it again with the original. Note the
  interaction: until proxy-tiers-2 is fixed, a clip live before its original is
  on the NAS inserts the PREVIEW, so these two must land together.

### proxy-tiers-6 - a stand-in can be written under a .mxf, .avi or .mkv name; the spike only ever tested a QuickTime original
- Severity: medium
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/broll_server.py:907-914` (the guard is
  `proxy_scan.NEEDS_RESOLVE_EXTS`) with `companion/.../proxy_scan.py:75`
  (`{".braw", ".r3d", ".crm"}`) and `broll/indexer/broll_index/scanner.py:21`
  (`VIDEO_EXTENSIONS = {".mov", ".mp4", ".mxf", ".braw", ".avi", ".mkv", ".m4v"}`)
- What: the stand-in is the preview's MP4 bytes written under the ORIGINAL's name
  and extension. Only camera-raw extensions are excluded. The archive indexes
  `.mxf`, `.avi` and `.mkv` originals, and for those the stand-in is an ISO-BMFF
  file wearing an MXF/AVI/Matroska extension. The plan's spike (section 3) was
  measured on one ProRes `.mov`; nothing tested a container mismatch, and
  Resolve's MXF path in particular is not a content sniffer the way ffmpeg is.
- Failure scenario: a remote editor sends an `.mxf` archive clip. Either
  `ImportMedia` refuses it silently (the spike's own finding for anything Resolve
  cannot open) and the insert reports a Resolve failure with a stand-in already
  ledgered at that path - after which every later insert takes the
  "already in place" branch and imports the same unopenable file - or it imports
  with the wrong container's geometry.
- Evidence: code reading plus the spike table in
  `docs/BROLL_PROXY_TIERS_PLAN.md` section 3, which records method C against one
  clip type. I could not test it (no Resolve, by the brief's rule), hence
  PLAUSIBLE.
- Ledger: new.
- Suggested fix: restrict the stand-in to extensions whose bytes the preview
  actually is (`.mov`, `.mp4`, `.m4v`) and fall back to `preview_only` for the
  rest, which is already an implemented action; and on a failed import, retire
  the ledger row that was written before it.

### proxy-tiers-7 - the geometry half of migration 012 is write-only: three columns, a wire field and a ledger field that nothing reads
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/web/migrations/012_geometry.sql` (and its `broll/migrations`
  twin), `broll/web/app/routes_api.py:145-154`, `broll/web/static/app.js:1703`,
  `companion/.../broll_server.py:792-797`, `companion/.../broll_standins.py:240`
- What: `frames` and `start_tc` were added, probed on both ingest paths, carried
  through the detail API, forwarded by the page and stored in the stand-in ledger
  because "phase 3 writes them into the interchange file that creates an offline
  clip" - method A, which the phase 0 spike rejected in favour of method C. No
  reader exists: `grep` for `geometry` across the companion finds only the
  producer, the log line and the ledger field. `bitrate` alone earns its place
  (`original_is_edit_weight`). Worse for a future reader: `videos.frames` is
  `nb_frames` off the container (`broll/indexer/broll_index/ffmpeg_tools.py:253`),
  which the same module's `count_frames` docstring calls "absent or a lie", while
  the refresh compares Resolve's `Frames` against a PACKET count - so wiring the
  column into the refresh later would compare a lie with a measurement.
- Failure scenario: no live failure today; the cost is a migration and a wire
  field carried on every detail view, and a trap for the person who fixes
  proxy-tiers-4 and reaches for the geometry that is already on the wire.
- Evidence: the greps above; `broll/web/tests/test_insert_target.py:188-196`
  asserts the nulls and nothing consumes them.
- Ledger: new (audit F3 asked for the columns for method A's sake).
- Suggested fix: either use `frames`/`start_tc` where they would help (the
  stand-in's own record, so the wired rig has a number to compare against
  without ffprobe - see proxy-tiers-4) or drop them from the insert object and
  say in the migration that the columns are kept for the index's own sake.

### proxy-tiers-8 - the machine that made the editing proxy re-downloads it from the NAS, and re-downloads its own preview as a stand-in
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/broll_ingest.py:3046-3065`
  (`_mirror_locally` mirrors `outputs["proxy"]` only) with
  `companion/.../broll_server.py:1030-1090` (the stand-in fetch) and `:1228-1290`
  (the upgrade fetch)
- What: after ingest, the companion moves its preview into
  `<archive>/<dir>/Proxy/<stem>.mp4` so a later Send to Resolve needs no fetch
  (plan §9.9). The editing proxy it just encoded is not mirrored, and the
  ORIGINAL's archive path does not exist locally (the original was dropped
  elsewhere), so the very machine that produced all three files answers
  `fetch_standin`: it downloads its own preview from the NAS to the original's
  archive path, then downloads its own editing proxy in the background.
- Failure scenario: an editor ingests 200 clips and then cuts with them.
  Hundreds of MB come back down a link that just sent them up, and the editor's
  ledger fills with stand-ins for clips whose real originals are sitting on the
  same computer, out of tree.
- Evidence: read `_mirror_locally` (only `outputs.get("proxy")` is handled, and
  the plan's §9.9 wording covers the preview only) and the two fetch paths.
- Ledger: new.
- Suggested fix: mirror the editing proxy the same way, and (better) let the
  insert notice that the item's real original is on this machine out of tree -
  the ingest state file holds `local_path` - before writing a lie at the archive
  path.

## Coverage note
I did not exercise a real ingest, a real fetch or Resolve (forbidden by the
brief), so finding 6 is reasoned from the spike's own scope rather than measured.
I read the b-roll web and companion halves of the feature but not the indexer's
encode spec or the dashboard's notices (owned by `broll-indexer`,
`comp-broll-tiers` and `dash-collector-alerts`, whose findings I have not
repeated). Not covered anywhere by any suite: a clip live with no original in the
archive folder (findings 2 and 5), an archive the container cannot list
(finding 3), a wired rig opening a stand-in-born project (finding 4 - the live
check CR-281 itself lists as still owed), and a non-QuickTime stand-in
(finding 6). The client-share prefix (`routes_share.py`) has no Send to Resolve
and is unaffected by the tier work.

## OUT OF TERRITORY
- `broll/web/app/ingest_batches.py:924-948`: `_apply_probe`'s docstring says
  "COALESCE-free on purpose" while every column in both statements is written
  with COALESCE; one of the two is wrong and the comment is what the next reader
  will trust (dash/broll territory).
- `broll/indexer/broll_index/ffmpeg_tools.py:253`: `videos.frames` is
  `nb_frames`, which the same file's `count_frames` calls absent or a lie
  (broll-indexer).
