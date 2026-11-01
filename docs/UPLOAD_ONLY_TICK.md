# The upload-only tick

Written 2026-08-27, from the owner's ask the same day:

> I want to add an upload only tick for editors who have backed up footage
> locally and want to upload originals to the server but don't want to sync
> all the other project files down.

Built the same day: dashboard 0.7.14 (schema v28), companion 0.9.54.
Related: `docs/MULTI_MACHINE_PLAN.md` (a tick belongs to a computer),
`docs/SYNC_SAFETY.md` (what stops a lane), `SPEC.md` (the three lanes),
`KNOWN_BUGS.md` CR-85.

---

## 1. What it is

A tick now carries a **mode**:

| mode | lane A (video originals, up) | lane B (proxies, down) | lane C (everything else, both ways) |
|---|---|---|---|
| `full` (every tick until now) | runs | runs | the folder is shared with the machine |
| `upload_only` | runs, **carries every file** (CR-366, section 5) | **skipped** | **the folder is never shared with the machine** |

So an upload-only tick is **lane A alone**. The editor puts the footage in
the project's folder on their own disk, in the tree's layout
(`P:\Projects\<year>\<series>\<project>\...`, exactly where a full tick would
have put it), and the companion uploads **every file** it finds outside `Proxy/`
directories (since 2026-10-07; it was video only before, see section 5),
with the same age floor and `--ignore-existing` rule lane A has always had. Nothing is downloaded: no
proxies, no shared project files, no borrowed folders, no folder skeleton
beyond what the project's own structure clone has always made.

It is a tick like any other everywhere else: it has a position in the
machine's queue, it is per computer, the sidebar checkbox and the queue
panel show it (marked `[ UP ]` / `[ UPLOAD ONLY ]`), unticking it is the
same untick, and the tray's "Remove from this machine" still asks whether
the originals have reached the server before it deletes anything.

## 2. The controls

- **Project page**: `[ UPLOAD ONLY FOR ME ]` beside `[ TICK FOR ME ]`. On a
  project already ticked it reads `[ SWITCH TO UPLOAD ONLY ]`; on an
  upload-only tick it becomes `[ SWITCH TO FULL SYNC ]`. It is a SET, never
  a toggle: pressing it never unticks. Like the tick button it is the
  PERSON's control (every computer they use); the marker in `SELECTED BY`
  says `[ UP ]`, or `[ UP ON ONE ]` when one of their computers is upload-only
  and another is not.
- **Settings, Assignments**: every cell has a small `up` box beside the tick.
  On = that computer, upload only (ticking it if it was not); off = back to a
  full tick. `[ ALL ]` skips cells that are already ticked, so it never turns
  an upload-only project into a download; `[ NONE ]` unticks them like any
  other. `copy from…` copies modes with the plan.
- **API**: `PUT /api/v1/selection/{editor}/{slug}?machine=&mode=upload_only`
  (`mode=full` is the default and what every old client sends). Same PUT on
  the other mode switches it and answers `changed: true`; an unknown mode is
  a 400, never read as `full`. The companion's `GET` carries `sync_mode` on
  every item.

## 3. Why "not shared" rather than a `sendonly` folder

Syncthing can express "send only" per folder, and the first draft of this
reached for it. It was rejected for three reasons:

1. **Every page that reads completion would show it permanently behind.**
   A sendonly folder still indexes, still compares against the server's
   index, and reports every server-side file it lacks as "out of sync". The
   dashboard is what tells everyone whether their footage is syncing; a row
   that is red by design would train people to ignore red.
2. **It is more surface for the L-3 failure.** A folder that exists on the
   machine is a folder whose `.stignore`, type and paused state all have to be
   right at once, verified at startup and re-asserted every turn. The sequencer
   already carries three latches for exactly that class of bug. A folder that
   does not exist has none of them.
3. **The owner's sentence has no lane C in it.** "Upload originals, don't
   sync the other project files down" is lane A up and nothing down. Lane C
   is bidirectional by construction; the honest shape of "nothing down" is
   "no share".

The cost is stated in §5.

## 4. Where it lives

Dashboard:

- `selections.sync_mode` (v28, `NOT NULL DEFAULT 'full'`), so a dashboard
  upgraded ahead of its fleet changes nothing (the B16 rule). Constants
  `db.SYNC_MODE_FULL` / `db.SYNC_MODE_UPLOAD_ONLY`.
- `db.add_selection` takes `sync_mode`; a row that exists in the other mode is
  UPDATEd in place, keeping its position. `materialise_bucket`,
  `copy_machine_plan` and `adopt_renamed_machine` carry it.
- `db.fetch_machine_selections` / `fetch_all_selections` take `sync_modes=`.
  The bucket rule ("a machine with rows of its own is never handed the
  bucket") is decided on ALL of a machine's rows before the filter applies:
  otherwise a laptop holding one upload-only tick would inherit every full
  tick in the bucket the moment the enforce cycle asked for full ticks only.
- `collector._run_enforce` reads full ticks only: the share set, and the
  borrower rule, never see an upload-only tick.
- `db.fetch_sync_backlog` lists the lane A (up) side for it and never the lane
  B (down) side. `build_transfers_view`'s lane C backlog and its GETTING READY
  rows are full ticks only; an upload-only tick gets its own GETTING READY
  row that clears on the machine's first media manifest for the project
  (`editor_media_project`), not on a Syncthing completion row it will never
  have - the CR-28 permanent-chip shape, avoided by construction.
- `_selection_view` adds `sync_mode` to every item (additive key).

Companion:

- `sequencer._item_sync_mode`: missing or blank is `full`; `upload_only` is
  upload only; **anything else fails closed** - the item is invalid and is not
  synced at all, logged like any other invalid item. Reading an unknown mode
  as `full` would start the download the tick was meant to prevent; reading
  it as upload-only would silently stop a project syncing.
- `_process_project` runs lane A (`_run_lanes_a_and_b(..., upload_only=True)`
  skips lane B and does not count a lone lane A failure as offline evidence),
  then the orphan scan, then returns: no borrowed-folder runs, no lane C turn.
- `expected_folder_slugs()` (lane C's "which folders am I behind on") leaves
  them out; `_verify_startup_ignores`, `_unpause_all`, the rotate pause sweep
  and the folder-sync wait all skip them. `rel_to_slug` / `known_rels` keep
  them: lane A's express watchdog and the manifest need the project.
- A mode flip is a selection change (`_update_known_selection` wakes the
  sequencer), so full -> upload-only stops lane B on the next pass and the
  reverse starts it.
- `app.removal_blockers` asks the lane A questions only; `removable_projects`
  carries `upload_only`; the tray's "Remove…" item says `(upload only)`.
  Since CR-366 (2026-10-07) those are: the lane A dry run WITHOUT the age
  floor, a strict same-name-different-size check, a local scan for files no
  lane carries, and a local scan for future-dated files (section 5).

## 5. Known limits and open decisions

- **Lane A carries EVERY file of an upload-only project** (decided by the
  owner 2026-10-07, CR-366 / prelaunch GL-13; this section used to say "only
  VIDEO originals go up" and leave it as an open decision). The tick has no
  lane C, so a sound recording from a separate recorder, a still or a
  document had no way to reach the server, and "Remove from this machine"
  deleted them. `build_filter_rules_up(carry_all=True)` is `+ *` instead of
  the `+ *<video ext>` list, for runs whose subpath is an upload-only
  project (`RcloneLane.carry_all_fn` <- `Sequencer.is_upload_only_subpath`;
  its own filter file, `filter_up_all.txt`). Everything the video rules
  already refused stays refused: `Proxy/` (lane B's, the server makes
  proxies), AppleDouble `._*`, file-move staging, ytdl work files, the
  half-written `.partial`/`.tmp`/`.lock`/`.part`/`.ytdl`/`.ccsync-tmp`,
  OS litter (`.DS_Store`, `Thumbs.db`, `desktop.ini`: nobody's work, and a
  Finder-rewritten `.DS_Store` would otherwise block almost every Mac
  removal) and Syncthing's own state (`.stfolder/`, `.stignore`,
  `.stversions/`: a project that was a full tick holds them, and they must
  never be pushed into the server's versioning tree). A full tick is
  unchanged (video only on lane A; the rest is lane C). The consequence the
  owner accepted: a later re-tick to full sync finds the audio already on
  the server. The express path is unchanged and still video only; the
  periodic pass carries the rest.
- **What the removal gate checks, and the one thing it blocks on by name.**
  An upload-only removal is blocked, behind the typed override and naming the
  files, when the folder holds a file no lane carries (the refused names
  above). `Proxy/` content, OS litter (`.DS_Store`, `Thumbs.db`,
  `desktop.ini`, `._*`) and 0-byte files do not count. The confirm dialog
  claims only what was checked (`tray.remove_ready_body`).
  **The same rule holds for a full tick (round 2):** lane C ignores every video
  extension, so a video file lane A refuses (`*.original.*`, `*.temp.*`,
  `*.editready.*`, `*.f137.*`, `*.failed`, move staging) is carried by nobody
  on a full tick either, and so are `.part`/`.ytdl`/`.ccsync-tmp`. The local
  scan names them and the gate blocks.
- **An edit to an already uploaded file never goes up on an upload-only tick.**
  Lane A is `copy --ignore-existing`: the first version of a name to reach
  the server is the only one that ever will, and that now applies to the
  documents, project files and WAVs the lane carries. The gate looks for the
  two shapes of it and blocks, naming files: a different size (the strict
  `rclone check`) and a same-size edit (`scan_edited_since_upload`, a
  `copy --update` dry run: a file whose local copy is NEWER than the server's,
  minus what is simply not uploaded yet). The way out is the one the block
  names: rename the file so it uploads as a new one. Video re-exports behave
  the same way.
- **Same-name files and future dates** (GL-12, GL-14, any tick): the gate's
  lane A dry run drops `--min-age` (a file under two minutes old, or dated
  in the future by a camera clock, has not reached the server), the strict
  `rclone check --combined` finds local files the NAS holds at another size
  (they never upload) and returns "could not tell" on anything it does not
  understand, and a local walk names files dated more than 300 s ahead of
  the machine clock. Every one of them blocks, names files, and fails
  closed. The editor sees future-dated files in Settings as an advisory line
  naming the first file and its date (`tray._future_dated_line`, a local read
  of `RcloneLane.future_dated_report`, summed over all projects). That line is
  deliberately NOT a `sync_guard` report key: it is injected into the tray's
  own copy of the guard, so there is no telemetry row and nothing on the wire;
  a dashboard chip needs a model on both sides and a dashboard-first deploy
  and is left for a later wave. Not done: uploading future-dated files (lane
  A's age floor still refuses them; the gate, the tray line and the log name
  them).
- **An old companion (< 0.9.54) treats an upload-only tick as originals up
  AND proxies down.** It ignores `sync_mode`, so lane B runs for the project;
  lane C still cannot, because the server never shares the folder. That is
  the editor's stated goal met with proxies as a side effect, not the
  promise; deploy the dashboard first, then push the companion (Settings ->
  Packages -> [ UPDATE NOW ]).
- **Switching full -> upload-only does not delete what already came down.**
  Proxies and shared files already on the machine stay; the local Syncthing
  folder (if one exists from the full tick) is left exactly as it is and the
  server unshares it. "Remove from this machine" is how the disk is
  reclaimed, and it goes through the caught-up gate as always.
- **The project's folder skeleton is still cloned** (`_maybe_clone_structure`
  runs before lanes for every project). Empty folders are not "project files
  coming down" in any sense the ask meant, and they are what lets a card dump
  land in the right bin.
- A **wired machine** cannot be ticked upload-only any more than fully: its
  tree IS the NAS tree, there is nothing to upload (the CR-28 refusals apply
  unchanged).

## 6. Tests

`dashboard/tests/test_upload_only.py` (the tick, its plan-level operations,
the three consumers, the controls), `companion/tests/test_upload_only.py`
(lane A alone, lane C never expects it, mode flip wakes, unknown mode fails
closed, startup sweeps skip it), `companion/tests/test_sync_halt.py` (the
removal gate asks the lane A questions only),
`companion/tests/test_removal_gate_cr366.py` (carry-all rules against the real
rclone, the age-floor-free dry run, the strict same-name check, the local
scan, the dialog wording).
