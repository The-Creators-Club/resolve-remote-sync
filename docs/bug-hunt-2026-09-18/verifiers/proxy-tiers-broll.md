# verdicts - proxy-tiers-broll

Verified at git HEAD 214869b, read-only. Evidence scripts ran from
`companion/` with `companion\.venv\Scripts\python.exe`; nothing was written
outside this file.

## proxy-tiers-1
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: `resolve_bridge._attach_adjacent_proxy` (2872-2917) takes only
  `(media_pool_item, local_path)`, walks `proxy_relink.expected_proxy_paths`
  (PROXY_EXTENSIONS = .mov then .mp4) and links the first file that exists,
  with no `original_present` / `is_standin` question; it is called
  unconditionally at 3027 for every insert, freshly imported or not.
  `proxy_relink.plan_relinks:552-566` has exactly those two questions and is
  the only place audit F1 was implemented. The 120 s pass cannot undo the
  attachment because `proxy_is_working(state)` short-circuits before the
  `.mp4` rule is reached, so the state is permanent for the clip.
- Evidence: code read at both sites; KNOWN_BUGS CR-281 (line 24433) names the
  F1 fix as "the 120 s relink pass" only, and the plan's section 6 table row
  for a machine holding the original says "link `edit_proxy_rel` if it exists,
  otherwise link nothing".
- Fix note: the suggested fix is right and self-contained; note
  `_attach_adjacent_proxy` runs with `_API_LOCK` held, so the new questions
  must be the filesystem-only helpers (`proxy_relink._original_on_disk`,
  `broll_standins.is_standin`) and never a bridge call. A fix must also touch
  `companion/tests/test_resolve_bridge*.py` (the tests that pin today's
  unconditional attach) and should keep the `.mov` arm unconditional.

## proxy-tiers-2
- Verdict: DOWNGRADED to medium
- Duplicate of: broll-1 (and comp-broll-tiers-4) - same wire defect, one
  mechanism
- Reasoning: the mechanism is real and I reproduced it: with
  `original_rel: null` the companion's `derive_insert_paths` leaves
  `original_rel` = the posted preview rel, and `plan_insert` answers
  `fetch_standin` with `fetch_rel` = the preview and `insert_rel` = None, i.e.
  fetch the preview onto its own path and ledger it as a stand-in. The hunter
  is right that this is not four legacy clips: `upload_originals` is a
  first-class per-batch setting (`ingest_batches.py:219`,
  `static/ingest.js:1293`, `broll_ingest.py:2767`), so "no original in the
  archive" is a supported steady state. But the severity claim ("the project
  points at the preview instead of the archive original, goal 2 broken
  permanently") overstates it: in that mode there IS no original on the NAS,
  so no plan could point the clip anywhere better; the real damage is the
  false stand-in ledger row (permanent `is_standin`, watcher exemption, an
  editing-proxy upgrade restarted per insert) plus ignoring the editing proxy
  as the file to insert. That is broll-1's medium, not a high.
- Evidence: `derive_insert_paths({...original_rel: None...}, "<...>/Proxy/clip.mp4")`
  -> `original_rel` = the preview; `plan_insert(False, False, tiers, False)`
  -> `{'action': 'fetch_standin', 'fetch_rel': '.../Proxy/clip.mp4',
  'insert_rel': None, 'upgrade_rel': '.../Proxy/clip.mov'}`.
  `broll_server.py:1077` records the ledger row before the import.
- Fix note: the two-sided fix is right and both halves are needed. Name the
  third file: `broll/web/tests/test_insert_target.py:198-212` pins the null as
  correct and would need the new field (or an explicit "insertable tier")
  asserted; `companion/tests/test_broll_server.py`'s plan table pins the
  current fallback comment ("there is always an original").

## proxy-tiers-3
- Verdict: DOWNGRADED to medium
- Duplicate of: none (amplifier of broll-1 / proxy-tiers-2)
- Reasoning: the swallow is exactly as described - `except OSError: entries =
  []` at 106-110 and the same for the editing proxy at 120-127 - and it is
  indistinguishable on the wire from "this clip has no original", which is
  what makes it dangerous. It is a medium rather than a high for two reasons:
  the damage it causes is proxy-tiers-2's damage (a false ledger row and a
  preview-path insert), so fixing broll-1 removes most of it, and the
  "dashboard shows no error" claim is weakened by the fact that a data root
  the container cannot list also breaks `/broll` media, stills and sprite
  serving from the same mount, which is loud. A single-directory OSError
  (permissions, a deleted shoot folder) is the residual case.
- Evidence: `test_a_missing_archive_directory_answers_without_a_proxy`
  (tests/test_insert_target.py:239-255) pins the conflation; `mount_status`
  already records the b-roll root, so the notice half of the suggested fix has
  a home.
- Fix note: right in direction. Careful with "answer absent, not null": the
  companion treats an ABSENT `preview_rel`/`edit_proxy_rel` as "fall back to
  the stem convention" and an absent `original_rel` as "use the posted rel",
  so simply dropping the keys re-creates the same wrong answer. An explicit
  `insert.known: false` that the companion refuses on is the safer shape, and
  it needs the companion's `derive_insert_paths` in the same change.

## proxy-tiers-4
- Verdict: DOWNGRADED to medium
- Duplicate of: overlaps comp-resolve-1 and comp-resolve-2 (its two named
  operational halves, CONFIRMED in that hunter's report)
- Reasoning: the structural claim holds. `broll_standins.record` is called in
  exactly one place (`broll_server.build_insert_response:1077`), on the
  machine doing the insert; the ledger file is per machine
  (`<log dir>/state/broll_standins.json`), and nothing sends a stand-in fact
  to the dashboard, into the project or onto the clip. So on the wired rig the
  "or the ledger says so" half of the plan's last table row can never fire, and
  what remains is `_geometry_disagrees` + `replace_clip(<same path>)`, which
  returns `{"ok": True, "message": "Already linked to ..."}` at
  `resolve_bridge.py:2284-2285` without calling ReplaceClip. Downgraded from
  high because the two harms the hunter prices (the ffprobe cost, the refresh
  that refreshes nothing) are comp-resolve-2 and comp-resolve-1, already
  confirmed and separately fixable; what is new here is the design point that
  the ledger cannot be the cheap alternative, which is an architecture note
  rather than a second live defect.
- Evidence: `grep -rn "broll_standins\."` over the companion - one `record`
  call, all other uses are reads; `replace_clip`'s short-circuit read at
  2280-2285.
- Fix note: the ordering advice (fix comp-resolve-1 first) is right; a `force`
  flag on `replace_clip` must keep the save point and the journal entry, since
  a forced ReplaceClip onto the same path is still a mutation. Making the fact
  travel with the fleet touches the dashboard (a report field) and the
  companion's report payload, so it is not a companion-only change.

## proxy-tiers-5
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: `_pump_uploads` computes `missing = [rel for rel in rels if rel
  not in landed]` and only posts `/uploaded` when NOTHING is missing, so the
  single report happens after the original lands; `mark_uploaded` is the only
  writer of `status = 'indexed'`. The upload ORDER exists
  (`broll_upload.UPLOAD_ORDER`) and buys nothing. The plan's section 5 item 5
  says in so many words "An editor can use a clip from the moment its editing
  proxy lands, long before a multi-GB original finishes", which the code does
  not do.
- Evidence: `broll_ingest.py:2935-2981` read; `ingest_batches.mark_uploaded`
  requires `slots.original` only when `original_uploaded` is true and stores
  the flag on the row, and `routes_fleet.item_uploaded` has no item-state
  guard, so a second, later post is accepted - the server side really is ready
  for a two-stage report.
- Fix note: right, and the hunter's own interaction warning is the important
  part: staging live before the original lands makes every such clip a
  broll-1 / proxy-tiers-2 clip, so the two must land together. A fix also
  touches the item state machine (`_final_state`, `item["original_uploaded"]`)
  and `_mirror_locally`, which today runs once at the end.

## proxy-tiers-6
- Verdict: CONFIRMED (harm unverified, as the hunter says)
- Duplicate of: none
- Reasoning: the guard really is only `proxy_scan.NEEDS_RESOLVE_EXTS =
  {.braw, .r3d, .crm}` while the indexer scans `.mov .mp4 .mxf .braw .avi
  .mkv .m4v`, so an `.mxf`/`.avi`/`.mkv` original gets a stand-in that is MP4
  bytes under that extension. What makes it more than a style point is the
  ordering in `build_insert_response`: `broll_standins.record` runs BEFORE the
  import (1077, deliberately), so a Resolve that refuses the file leaves a
  ledger row behind, and the next insert takes the `local_path.is_file()` +
  `is_standin` branch ("already in place") and re-imports the same unopenable
  file for ever. I could not test Resolve's behaviour (brief forbids it), so
  the outcome - silent refusal vs wrong-container import - stays unproven;
  the gap between the spike's one-ProRes-.mov sample and the indexed extension
  set is proven.
- Evidence: `proxy_scan.py:75` and `scanner.py:21` read side by side; the
  record-before-import ordering at `broll_server.py:1070-1085`.
- Fix note: restricting the stand-in to `.mov/.mp4/.m4v` is right and cheap.
  Retiring the row on a failed import is the more important half and needs
  care: `is_stale` is a SIZE comparison, so an explicit `forget()` (or a
  recorded failure state) is needed rather than relying on the file changing.
  `companion/tests/test_broll_standins.py` pins the ledger's retirement rule.

## proxy-tiers-7
- Verdict: CONFIRMED
- Duplicate of: related to broll-indexer-2 (the `nb_frames` half), not the
  same finding
- Reasoning: `geometry` is produced (`routes_api._insert_object`), carried
  (`app.js`), parsed (`derive_insert_paths:792-797`), logged and stored
  (`broll_standins.record`'s `geometry` field) and read by nothing: the only
  `frames` reader in the companion is `proxy_relink.py:276`, which reads
  Resolve's own `Frames` clip property (`resolve_bridge.py:1853`), not the
  ledger or the wire. Low is the right severity - no live failure, a real trap
  for the next reader.
- Evidence: `grep -rn "geometry" companion/src/ccsync_companion/*.py` - only
  the producer, the log line and the ledger field; the sprite-geometry hits
  are unrelated.
- Fix note: the "use it in the stand-in's own record" option is the one that
  helps proxy-tiers-4, but only if the comparison is like for like: the plan's
  `frames` comes from `nb_frames` while the refresh compares a packet count,
  which is broll-indexer-2's finding. Dropping the field from the wire would
  need `test_insert_target.py:188-196` changed too.

## proxy-tiers-8
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: `_mirror_locally` handles `outputs["proxy"]` only and writes it
  to `<archive>/<dir>/Proxy/<stem>.mp4`; the editing proxy it just encoded is
  left where it was made, and the original's archive path never exists locally
  (the original was dropped from outside the tree). So on the ingesting
  machine the next Send to Resolve finds no file at the original's path,
  plans `fetch_standin`, and rclone pulls that machine's own preview back down
  from the NAS, then its own editing proxy in the upgrade lane.
- Evidence: `broll_ingest.py:3046-3065` read; the fetch paths at
  `broll_server.py:1030-1090` and `:1228-1290`.
- Fix note: mirroring the editing proxy is safe and symmetrical. The better
  half of the suggestion (notice the real original out of tree, via the ingest
  state file's `local_path`) crosses a module boundary - `broll_server` has no
  handle on the ingest orchestrator's state today - so it is a bigger change
  than it reads, and it must not write a stand-in ledger row for a path that
  holds a genuine original.

## broll-1
- Verdict: CONFIRMED
- Duplicate of: same defect as proxy-tiers-2 and comp-broll-tiers-4; this is
  the clearest statement of it
- Reasoning: reproduced end to end (see proxy-tiers-2's evidence). The
  companion honours an explicit null for `preview_rel`/`edit_proxy_rel` but
  not for `original_rel`, whose comment ("there is always an original") is
  false for both the stem-diverged clips and the normal
  `original_uploaded: false` state. The result is `PLAN_FETCH_STANDIN` onto
  the preview's own path and a `broll_standins.record` on a genuine,
  lane-B-managed archive preview: `is_standin` then answers true for ever
  (size never changes), the watcher's missing-count exemption applies, and
  every later insert re-enters the upgrade lane. Medium is right - nothing is
  corrupted on disk, but a per-machine ledger is permanently wrong and the
  plan's `PLAN_PREVIEW_ONLY` is the answer the table wants here.
- Evidence: the `derive_insert_paths`/`plan_insert` snippet above;
  `broll_server.py:986` (`standin_here`) and `:1077` (the record);
  `broll_standins.py`'s size-based `is_stale`.
- Fix note: both suggested shapes work; prefer the companion-side one (honour
  an explicit null), because the web-side one ("stop advertising
  `edit_proxy_rel` when `original_rel` is null") throws away the one tier that
  IS insertable in that state, which is what proxy-tiers-2 wants used. Other
  files a fix must touch: `broll/web/tests/test_insert_target.py` (pins the
  null), `companion/tests/test_broll_server.py` (pins the fallback), and
  proxy-tiers-5's two-stage go-live must not land first.

## broll-2
- Verdict: DOWNGRADED to low
- Duplicate of: KNOWN_BUGS "MUSIC-10, second half" covers the symptom class
- Reasoning: the code facts are right (`CURRENT_SCHEMA_VERSION = 12`, the
  deliberate FATAL for a newer file, no version handling anywhere in
  `server/publish_db.py`). But the hunter's headline harm - "the b-roll tab
  disappears with the reason only in the container log" - is already handled:
  `dashboard/src/ccsync_dashboard/broll.py:444-454` (`_schema_too_new`)
  recognises that exact refusal and the mount reports DEGRADED with the
  sentence "written by a newer version of the app", carried by
  `mount_status`, `/api/v1/health` and the self-diagnosis notice. KNOWN_BUGS
  records it for music and says "b-roll's identical guard is handled the same
  way". What is genuinely unfixed is the missing pre-flight in `publish_db.py`
  and the reverse skew (an older file dropped under a running newer container
  500s on ingest until a restart), which is a rare operator action - low.
- Evidence: `grep -an "user_version|publish_db" KNOWN_BUGS.md` -> MUSIC-10 at
  11828; `db.py:232-238`; `broll.py:444-454`.
- Fix note: the pre-flight is worth having and is the right place. The
  "re-run `ensure_schema` after a publish" half is the more delicate one: the
  container holds the live file open in WAL mode, and stepping a schema from
  the base rig over SSH is not the same act as the mount's boot-time step -
  it would need the container-python path `publish_db` already uses for the
  drain, not a local call.

## broll-3
- Verdict: CONFIRMED (severity low, as reported; harm remains PLAUSIBLE)
- Duplicate of: none (CR-90 is the standing rule, not an open bug for this
  file)
- Reasoning: the comparison at `routes_api.py:110-117` is a raw
  `os.path.splitext(e)[0] == preview.stem` between container `listdir` bytes
  and a DB string, with no normaliser, which is precisely what CLAUDE.md's
  CR-90 rule forbids for a value that is only compared. A miss degrades the
  clip to `original_rel: None`, i.e. straight into broll-1's path, which makes
  it worse than it looks. It stays low because fleet-ingested names are
  server-minted and the base-rig archive builder takes both sides from one
  walk, so the exposure is a Mac-placed file whose row came from elsewhere.
- Evidence: read only; I did not create an NFD name anywhere (read-only rule).
  The neighbouring `_resolve_under_root` is correctly un-normalised.
- Fix note: right, and the constraint the hunter states is the important one -
  normalise the STEM TEST only, never the path that is then joined and
  stat'ed. The natural fix normalises both sides with
  `unicodedata.normalize("NFC", ...)`; note the archive can legitimately hold
  two files whose names differ only by normalisation, in which case
  `len(matches) == 1` becomes 2 and the clip degrades anyway - worth a log
  line rather than silence.

## broll-4
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: `edit_proxy = preview.parent / (preview.stem + ".mov")` with no
  inequality test, so a preview whose own suffix is `.mov` is advertised as
  its own editing proxy. `build_archive.preview_source` can produce that: the
  `status == "skipped"` arm returns the TOP SLOT as the preview and
  `dest_rel` keeps its suffix. Low is right - the outcome is a wasted
  background upgrade thread and a ledger field, not a wrong file - and the
  case is narrow (an audio-only `.mov` top slot; the fleet-ingest path always
  allocates a `.mp4` preview).
- Evidence: `routes_api.py:119-128` and `build_archive.py:252-276` read.
- Fix note: the one-line guard is correct and has no other side. Worth adding
  the same guard on the companion's stem convention in
  `derive_insert_paths` (the `basename(parent) == "Proxy"` arm builds
  `stem + ".mov"` the same way), or an old page keeps producing the same
  self-referential pair.

## broll-5
- Verdict: CONFIRMED
- Duplicate of: none
- Reasoning: verified at `ingest_batches.py:1165-1171`: `if actual == 0 and
  rel == edit_rel` is the only zero-byte rejection, while `required` seeds
  `slots.proxy` (and `slots.original`) via `declared.setdefault(rel, None)`,
  and the size-mismatch arm is skipped when `want is None`. So a 0-byte
  preview with no declared size passes both checks and the clip goes live with
  the one file the search UI plays being empty. Narrow, as the hunter says -
  the companion normally declares a real size from the upload queue - which is
  why low is right.
- Evidence: read of `mark_uploaded`'s full checking loop; `files` is built in
  `_pump_uploads` from `landed[rel].get("size")`, which can legitimately be
  absent.
- Fix note: correct and one line. It must stay `actual == 0` and not become a
  general "size must be declared", or a rebuilt queue entry (the very case
  that produces `size: None`) would start 409-looping instead of going live.
  `broll/web/tests/test_fleet_ingest.py` holds the go-live tests a change here
  should extend.
