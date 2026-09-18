# verdicts - proxy-tiers-broll

Verified against the working tree as `git diff` showed it on 2026-09-18
(HEAD 214869b + the uncommitted fix pass). Scratch scripts and the ffmpeg
probes below ran in the session scratchpad; nothing in the repo, `~/.ccsync`,
P: or the live DB was touched.

## broll-1
- Verdict: CONFIRMED (medium stands)
- Duplicate of: none (the only NFC/NFD finding in `tally.txt` is this one; the
  downstream `heavy` flip is named in the hunter's own OUT OF TERRITORY note,
  not filed as a separate id)
- Reasoning: the asymmetry is real and not theoretical. `insert_target_detail`
  now finds the TOP slot through `unicodedata.normalize("NFC", ...)` on both
  sides of the compare (`routes_api.py:144-152`), while the editing proxy two
  lines below is still `preview.parent / (preview.stem + EDIT_PROXY_EXT)`
  built from the DB string and `is_file()`-d (`:161-163`). Nothing in
  `broll/` normalises `archive_path` on the way into the DB (grep: the only
  NFC calls in the whole tree are the two lines of today's fix), and
  `build_archive` mints ONE `name` for the top slot and the preview, so
  whatever makes the top-slot compare need a normaliser makes the
  editing-proxy stat need one too - the two files sit in the same folder pair
  and are compared against the same DB stem. The consequence chain the hunter
  draws is exactly what `broll_server.derive_insert_paths:1013` does: `heavy =
  weight is False or (weight is None and from_page and bool(edit_proxy_rel))`,
  so a missing `edit_proxy_rel` either (a) turns a null-bitrate row into "the
  original is small enough to edit with" and downloads the camera master, or
  (b) leaves a heavy row's stand-in with `upgrade_rel = None`, i.e. a ledgered
  stand-in nothing ever upgrades.
- Evidence: reproduced independently of the hunter, `broll/web/.venv`, temp
  `BROLL_DATA_ROOT`, three files written with NFD names, row `archive_path` in
  NFC:
  `original_rel -> NFD (the entry's own bytes, found by the new compare)`,
  `preview_rel -> NFC`, `edit_proxy_rel -> None`, `known -> True`, with the
  `.mov` beside the preview present on disk the whole time. The existing cell
  `test_an_nfd_top_slot_is_still_found_beside_an_nfc_preview` creates only the
  top slot, so the suite cannot see this.
- Fix note: the suggested fix is right - reuse the SAME `os.listdir(...)` of
  `preview.parent` and match `NFC(splitext(e)[0]) == want` with
  `splitext(e)[1].lower() == EDIT_PROXY_EXT`, keeping the entry's own bytes,
  and never NFC the path that is stat'ed (CLAUDE.md CR-90). Two things the fix
  must carry with it: the broll-4 guard already on that branch (`edit_proxy !=
  preview`, i.e. a preview whose own suffix is `.mov` is not its own editing
  proxy) must survive the rewrite, and the `OSError -> known = False` arm must
  stay, since the new listdir of `Proxy/` is a second call that can raise.
  A duplicate listing also feeds broll-3's "listed twice" point, so fixing
  both at once (one listing per folder, passed down) is the cheaper shape.
  Add a test cell with an NFD EDITING PROXY beside an NFC preview.

## broll-2
- Verdict: DOWNGRADED to low
- Duplicate of: none (dash-core-3's "zero-byte" is a secret file in the Setup
  wizard, unrelated)
- Reasoning: the MECHANISM is confirmed exactly as described - `mark_uploaded`
  now applies `actual == 0` to every entry in `declared`
  (`ingest_batches.py:1163-1183`), `declared` is seeded from the companion's
  `files` list, and that list is `[{"rel": rel, ...} for rel in rels]` over
  `item["uploads"]`, which `_upload_plan` fills with `posters/<id>.jpg` and
  `sprites/<id>.jpg` as well as the media slots; the companion's only answer
  to a 409 naming them is `_enqueue_uploads` again on the same local bytes,
  and `_fail_item` at `MAX_UPLOAD_ATTEMPTS`. What I could not make reachable
  is the premise, a 0-byte still produced by an ffmpeg that exits 0. I ran the
  real `poster_cmd` argv (ffmpeg 8.1) with `-ss` past the end of a 0.5 s clip:
  exit 0 and NO output file at all, so `poster.is_file()` is False and nothing
  is declared. The only way I could produce the hunter's state was to plant an
  empty file at the poster path FIRST and then run the frame-less command:
  image2 does not open the output until it writes a frame, so the pre-existing
  0-byte file survives, `is_file()` is True and the size is 0. That needs a
  stale empty jpg in staging at `<video_id>.poster.jpg` (a companion killed
  inside the few-byte window of a previous write) plus a frame-less run for
  the same clip. Real, but two coincidences deep, and the loss is one clip -
  hence low rather than medium.
- Evidence: `ffmpeg -y -ss 5.000 -i tiny.mp4 -vf scale=640:-2 -frames:v 1 -q:v
  3 -pix_fmt yuvj420p poster.jpg` -> `exit=0`, `ls: poster.jpg: No such file`.
  Same command with `: > poster.jpg` first -> `exit=0`, `-rw-r--r-- ... 0
  poster.jpg`. `_make_stills` (`broll_ingest.py:2585-2613`) has no size test on
  any of poster/sprite/thumb; `_enqueue_uploads` stats with `os.path.isfile`
  only, so a 0-byte file is queued and uploaded.
- Fix note: the suggested fix is right in both halves and the SOURCE half is
  the important one - add `st_size > 0` beside `code == 0 and path.is_file()`
  in `_make_stills` (all three stills), which also stops a 0-byte thumb
  reaching the page's preview grid. On the server side, narrowing the
  zero-byte arm to the media slots would re-open nothing (broll-5's own case
  is the preview, which is `slots.proxy`); if the stills keep the rule, the
  refusal for a still must be one the companion is allowed to give up on -
  today its 409 handler cannot tell a retryable rel from a hopeless one. A fix
  touches `broll/web/app/ingest_batches.py`,
  `companion/src/ccsync_companion/broll_ingest.py` and, if the server arm
  changes, whichever cell in `broll/web/tests` pins broll-5's widened rule
  (`test_a_preview_with_bytes_still_goes_live` and its neighbours).

## proxy-tiers-2
- Verdict: DOWNGRADED to low
- Duplicate of: dash-api-5, comp-resolve-8, res-companion-5, res-fleet-4,
  wire-4 - five other hunters found the identical line and ALL five rated it
  low, which is itself evidence on the severity question.
- Reasoning: the defect is real and I confirm the code contradicts its own
  comment: `api.py:9869-9871` is `known = db.standins_known(conn)` / `if
  known:` directly under a comment that says "an empty list is sent for the
  same reason, so the two shapes cannot be confused". The consequence is
  smaller than the finding claims, though, because a `False` from
  `fleet_says_standin` is explicitly NOT conclusive: `_geometry_disagrees`
  (`proxy_relink.py:565-572`) acts only on `fleet is True` and otherwise falls
  through to the probe it would have run anyway. So the "a fleet that has
  never had a stand-in can never move a companion out of ask-the-probe" half
  costs nothing at all - the probe path IS the pre-feature behaviour. What
  remains is the real half: a positive set can never be cleared by the
  dashboard, so after the last ledger row goes (a prune, a forgotten machine,
  proxy-tiers-1's fix) every running companion keeps answering True until its
  process restarts, costing one forced `ReplaceClip` per clip per process -
  which the companion's own comment at `proxy_relink.py:432-434` already
  budgets for ("at worst it costs one ReplaceClip that changes nothing").
  A wire-shape defect with a bounded, no-op cost is a low.
- Evidence: read both sides; `db.standins_known` returns `[]` for the empty
  fleet (pinned at `dashboard/tests/test_bug_hunt_2026_09_18_dashboard_lows.py:334`),
  while the only route-level cell (`:297-306`) asserts the key for a NON-empty
  set, so nothing pins the wire shape the comments promise.
- Fix note: `result["standins_known"] = {"rels": known}` unconditionally is
  correct and safe - the whole block is already inside a best-effort
  try/except, and `note_fleet_standins` accepts an empty `rels` list and sets
  `_FLEET_KNOWN` on it. Two other files a fix must touch: a new empty-reply
  cell in `dashboard/tests/test_bug_hunt_2026_09_18_dashboard_lows.py`, and a
  check that no report-reply size assertion elsewhere counts keys. Note the
  neighbouring finding wire-3 (the set is fleet-wide and never expires) would
  be fixed in the same lines, so the two should be built together.

## proxy-tiers-3
- Verdict: CONFIRMED (medium stands)
- Duplicate of: none
- Reasoning: I checked both ends. `git show HEAD:...broll_server.py` has no
  `known` branch anywhere in `derive_insert_paths`, and its `heavy` test is
  reached with `weight is False` for any heavy row; with `original_rel` null
  (which is precisely what today's route answers during the outage, because
  the listing raised) and `preview_rel` present, 0.9.74 plans
  `PLAN_FETCH_STANDIN` and writes the preview onto the preview's own path
  with a ledger row - the pre-fix harm, unchanged. `_is_edit_weight` is a pure
  `videos`-row read (`routes_api.py:68-76`) and is emitted unconditionally in
  `_insert_object`, so the object still carries `false` for every heavy clip
  during the outage. The fleet is on 0.9.74 today and the documented deploy
  order is dashboard first, so the window is not hypothetical. This is a
  "the fix is inert for every build in the field" finding rather than a brand
  new hazard, which is why it is a medium and not a high.
- Evidence: `git show HEAD:companion/src/ccsync_companion/broll_server.py`
  lines 860-920 (no `known`, the same `heavy` expression, `ext` guard only on
  `NEEDS_RESOLVE_EXTS`); current `broll_server.py:821-836` shows the reader
  that only 0.9.75 has.
- Fix note: the suggested fix works and I traced it on both builds. On 0.9.74,
  `original_is_edit_weight: true` makes `heavy` False and returns
  `PLAN_FETCH_ORIGINAL` with `fetch_rel = None`, which resolves to the posted
  `rel_path` - during an outage that IS the preview the editor clicked, i.e.
  "fetch the file the editor asked for", exactly the route 0.9.75 takes. On
  0.9.75 the `known is False` branch at `:999`/`:981` returns before the
  weight is consulted, so nothing changes there. No JS or template reads
  `original_is_edit_weight` (grepped), so the temporary lie is not visible
  anywhere else. Two cautions for the builder: the value must be set ONLY on
  the `known is False` path (it is a lie, and a lie that leaks into the
  healthy path would suppress every stand-in), and the existing known=false
  cell is `broll/web/tests/test_insert_target.py:250-271`, which pins
  `original_rel`/`edit_proxy_rel`/`preview_rel`/`known` but says nothing about
  the weight - so the fix needs its own assert added there (that clip's
  bitrate is 3 Mb/s, i.e. already edit-weight, so a new cell with a HEAVY row
  is what actually pins the forced answer).
