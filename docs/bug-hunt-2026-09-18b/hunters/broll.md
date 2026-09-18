# broll - the b-roll web app (broll/web/app, static, migrations, schema.sql)

Files read (with approximate coverage): `git diff` over the whole territory
first (`broll/web/app/ingest_batches.py`, `routes_api.py`, `routes_batches.py`,
`broll/web/static/ingest.js` - every hunk, with the CR-286/webapps-tools ledger
comments beside them); then `routes_api.py` in full, `ingest_batches.py`
(lease/claim/cancel/release/mark_uploaded, ~60%), `routes_batches.py` in full,
`routes_fleet.py` + `schemas.py` (the fleet ingest wire, ~80%), `edit_weight.py`
in full, `db.py`'s migration chain header, `migrations/012_geometry.sql` and
both `schema.sql` copies (byte-identical, verified with `diff`), `static/app.js`'s
Send-to-Resolve payload, `static/ingest.js`'s loopback error helper. Read as the
OTHER end of the wires, not reported on: `companion/src/ccsync_companion/
broll_ingest.py` (`_upload_plan`, `_enqueue_uploads`, the `/uploaded` 409 loop,
`run()`'s 409 shapes) and `broll_server.py`'s `plan_insert` / `known` reader.

Tests run:
- `cd broll/web; .venv\Scripts\python.exe -m pytest tests -q` -> **631 passed**
- scratch snippet (scratchpad, outside the repo) driving
  `routes_api.insert_target_detail` against a temp `BROLL_DATA_ROOT` holding
  NFD filenames -> the evidence for broll-1 below.

## Findings

### broll-1 - broll-3's NFC fix covers the ORIGINAL but not the editing proxy beside it
- Severity: medium
- Confidence: CONFIRMED
- Where: `broll/web/app/routes_api.py:161-179` (the `edit_proxy` stat), against
  the fix at `broll/web/app/routes_api.py:134-152` (the NFC-normalised stem
  match); consumed at
  `companion/src/ccsync_companion/broll_server.py:1010-1018` (`heavy`).
- What: today's broll-3 fix made the TOP-SLOT sibling search normalisation-
  insensitive (compare both sides through NFC, keep the entry's own bytes).
  The editing proxy two lines below is still discovered by building
  `preview.parent / (preview.stem + ".mov")` from the DB's NFC string and
  `is_file()`-ing it. On the container (Linux, byte-exact names) an editing
  proxy whose name is spelled NFD on the NAS - the CR-90 shape, a Mac's
  upload - is invisible, so `edit_proxy_rel` answers None while
  `original_rel` answers correctly. The fix landed half of CR-90 for this
  route.
- Failure scenario: `Matej Simalcik A001.mov` (accents NFD on the NAS) with a
  `Proxy/....mp4` preview and a `Proxy/....mov` editing proxy, the row's
  archive_path in NFC. The detail API answers `original_rel` = the original,
  `edit_proxy_rel` = null, `known` = true. A remote editor's Send to Resolve
  then takes one of two wrong roads in `plan_insert`: if
  `original_is_edit_weight` is false the clip gets a 540p stand-in with
  `upgrade_rel = None`, i.e. a ledgered stand-in the background upgrade will
  never replace with the editing proxy that exists; if
  `original_is_edit_weight` is null (a row indexed before migration 012 -
  every pre-2026-09-17 row) `heavy` is False and the companion downloads the
  multi-GB camera master over the internet, which is the exact outcome the
  tier exists to prevent.
- Evidence: scratch script against the real module, temp data root, three
  files written with NFD names, row archive_path in NFC:
  `original_rel  : Creators_Club/ff5/Day 1/Matej Simalcik A001.mov` /
  `edit_proxy_rel: None` / `known : True`
  (the top slot was found by the new NFC compare; the editing proxy beside
  the preview, present on disk, was not). The mirror test in
  `tests/test_bug_hunt_2026_09_18_webapps_tools.py::test_an_nfd_top_slot_is_still_found_beside_an_nfc_preview`
  creates only the top slot, so it cannot see this.
- Ledger: CR-286 / broll-3 does not fix the editing-proxy half of CR-90 on
  this route.
- Suggested fix: find the editing proxy the same way as the top slot - one
  `os.listdir(preview.parent)`, match `NFC(splitext(e)[0]) == want` and
  `splitext(e)[1].lower() == EDIT_PROXY_EXT`, and keep the entry's own bytes
  in `edit_proxy_rel`. Do not NFC the path that gets stat'ed (CLAUDE.md's
  CR-90 rule).

### broll-2 - broll-5's widened zero-byte rule turns a bad thumbnail into a clip that can never be archived
- Severity: medium
- Confidence: PLAUSIBLE
- Where: `broll/web/app/ingest_batches.py:1163-1183` (the widened
  `if actual == 0`), against
  `companion/src/ccsync_companion/broll_ingest.py:2804-2812` (`_upload_plan`
  declares `posters/<id>.jpg` and `sprites/<id>.jpg`) and
  `broll_ingest.py:3053-3075` (the 409 resend loop, capped by
  `MAX_UPLOAD_ATTEMPTS`).
- What: the rule used to be `actual == 0 and rel == edit_rel`; it is now
  `actual == 0` for EVERY entry in `declared`, and `declared` is seeded from
  the companion's `files` list, which includes the poster and the sprite
  sheet - not only the three media slots the comment reasons about. A
  zero-byte still therefore makes `/uploaded` answer 409 `not_uploaded`
  naming it; the companion re-sends the same zero-byte local file, burns
  `MAX_UPLOAD_ATTEMPTS` and then `_fail_item`s the clip. Before today the
  clip went live with a broken thumbnail.
- Failure scenario: `_make_stills` accepts a poster on `code == 0 and
  poster.is_file()` with no size test, so an ffmpeg that exits 0 having
  written nothing (a very short or truncated clip, a seek past the end)
  leaves a 0-byte `<id>.poster.jpg`. That clip is now failed out of the
  batch, permanently: every retry regenerates and re-uploads the same empty
  jpg. A clip that indexed perfectly is lost from the archive over its
  thumbnail.
- Evidence: read `_upload_plan` (poster and sprite are `declared` rels with
  sizes), `mark_uploaded` (no kind filter on the zero-byte arm), and the
  companion's 409 arm (`item["upload_attempts"] += 1`, `_fail_item` at the
  cap). Not reproduced live - hence PLAUSIBLE; what is CONFIRMED is that the
  poster and sprite now go through a rule written for media slots, and that
  the companion's only answer to a 409 naming them is to re-send the same
  bytes.
- Ledger: CR-286 / broll-5 closes the zero-byte preview and opens the
  zero-byte still.
- Suggested fix: keep `actual == 0` for the media slots (`slots.proxy`,
  `slots.original`, `edit_rel`) and for the stills either accept them or
  answer a refusal the companion is allowed to give up on - and add the
  missing `st_size > 0` test to `_make_stills` so an empty still is never
  declared in the first place.

### broll-3 - the detail route lists and stats the archive folder twice, and the two answers can disagree
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/web/app/routes_api.py:301` (`_insert_target`) and
  `broll/web/app/routes_api.py:305` (`_insert_object`), both calling
  `insert_target_detail(video)`.
- What: `GET /api/videos/{id}` runs `insert_target_detail` twice, so every
  detail view does two `os.listdir` of the shoot folder on the NAS plus two
  `is_file()`. Beyond the cost, the two calls are independent: with `known`
  now derived from whether the listing RAISED, a folder that becomes
  readable (or unreadable) between them yields `insert_rel_path` describing
  one file and `insert.original_rel` / `insert.known` describing another,
  and the page POSTs both halves to the companion in one body.
- Failure scenario: a dataset that remounts mid-request - first call raises
  (`insert_rel_path` = the preview), second succeeds (`insert.original_rel` =
  the original, `known` true). `plan_insert` trusts `insert`, resolves
  `fetch_rel = None` to "the original's own rel_path", and gets the PREVIEW
  path from the other half of the same body.
- Evidence: both call sites read; `insert_target_detail` has no cache and no
  memoisation.
- Ledger: new (the second call site is proxy-tiers phase 3, 2026-09-17; the
  disagreement is new with today's `known`).
- Suggested fix: call it once in `get_video` and pass the dict to both
  `_insert_target` and `_insert_object`.

### broll-4 - the "another of your computers" fallback music-2 kept is now unreachable
- Severity: low
- Confidence: CONFIRMED
- Where: `broll/web/static/ingest.js:1670-1681`.
- What: the new condition is `(body.reason || body.message) ? e.message :
  "Another of your computers..."`, but `ingestLoopback` builds `e.message`
  from `parsed.message || parsed.detail`, and EVERY 409 the companion's
  `run()` can produce sets `message` - including the forwarded dashboard
  claim refusal (`{"ok": false, "message": _detail_of(parsed)}`). So the
  branch the comment describes as "the fourth case" never selects the
  fallback string; the fallback fires only when the 409 body is not JSON at
  all, which is the one case where it is least likely to be true. Harmless
  today (the forwarded detail is a better sentence than the fallback), but
  the code does not do what its comment claims and the dead string reads as
  live to the next editor of this file.
- Failure scenario: companion answers 409 with an empty body or a non-JSON
  error page -> the editor is told another of their computers is working on
  the batch, when the refusal was "this computer is already indexing another
  batch".
- Evidence: `ingest.js:578-583` (message construction) vs
  `companion/src/ccsync_companion/broll_ingest.py:1745-1830` (every 409 sets
  `message`) and `:1777-1780` (the forwarded refusal sets `message` too).
- Ledger: CR-286 / music-2, partial.
- Suggested fix: gate on `e.body` being absent rather than on
  `reason || message`, or key the fallback on `body.machine`, which only the
  dashboard's claim refusal carries.

## Coverage note
Verified and NOT findings: migration 012 is in the chain
(`_MIGRATIONS[11]`, `CURRENT_SCHEMA_VERSION = 12`), both `schema.sql` copies
carry `frames`/`start_tc`/`bitrate` and `PRAGMA user_version = 12` and are
byte-identical to each other; `edit_weight.is_edit_weight` keeps None
distinguishable from False on a NULL bitrate; the `known` wire landed on
BOTH sides (`routes_api._insert_object` and `broll_server.plan_insert`
:980) and is optional on read; the music-1 twin in `cancel` does close its
scenario (on `HEAD`'s source the batch stays `running` and the new test's
`state == "cancelled"` assert fails).

Not reached: `client_folders.py` / `routes_client_folders.py` /
`routes_share.py` (927 + 280 + 269 lines, untouched by today's pass - the
security lens owns the share prefix), `search.py`, `semantic.py`, `fuzzy.py`,
`normalize.py`, `media.py`, and `static/app.js` beyond the Send-to-Resolve
payload. The suite does not cover: any NFD spelling of an EDITING PROXY (the
new broll-3 test creates only an NFD top slot), a zero-byte poster or sprite
(only a zero-byte preview), a detail request whose two
`insert_target_detail` calls disagree, or `insert_target_detail` hitting a
real transient `OSError` (the `known is False` test uses a missing
directory, a permanent condition, not the unmount the fix was written for).
`test_a_preview_with_bytes_still_goes_live` cannot fail in its stated sense:
the item has no segments, so it always takes the `no_result` 409 arm and
only the conditional assert runs.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/broll_ingest.py:2589-2612`: `_make_stills`
  accepts a poster/sprite/thumb on `code == 0 and path.is_file()` with no
  size test, which is the source side of broll-2 (comp-broll-tiers).
- `companion/src/ccsync_companion/broll_server.py:1010-1018`: `heavy` reads
  `weight is None and from_page and edit_proxy_rel`, so an absent
  `edit_proxy_rel` (broll-1) silently flips a heavy clip to "small enough to
  edit with" for every row with no bitrate (comp-broll-tiers).
