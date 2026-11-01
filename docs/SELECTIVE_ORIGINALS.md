# Selective originals - bringing chosen camera originals down to one computer

Written 2026-10-31, from the owner's ask the same day:

> there should be an option to sync CERTAIN originals. Which originals should
> be selectable on specific clips inside of resolve.

and the case that prompted it: Ruskin (remote editor, Windows, local root
`F:\Creators_Club`, `P:` mapped to it) needed the 80 originals in
`Projects/2026/Beyond Nights/Footage Lusty/` for a job. It was done by hand,
over SSH, with an `rclone copy` from his own remote (`creators_club_sftp:` +
`remote_root`) into his tree.

**Status: DESIGN ONLY. Nothing here is built.** Written from source and docs
alone; Resolve was not touched (the owner was rendering), no machine was
reached over SSH and the live dashboard was not called, so everything that can
only be answered against a running Resolve is marked **unverified** and
collected in section 10.

Related: `SPEC.md` (the three lanes), `docs/UPLOAD_ONLY_TICK.md` (the other
per-tick mode), `docs/MULTI_MACHINE_PLAN.md` (a plan belongs to a computer),
`docs/FILE_MOVES.md` (the command that follows a file to every machine),
`docs/SYNC_SAFETY.md` (what stops a lane), `docs/LIBRARY_WALK_PLAN.md` and
`docs/GOTCHAS.md` §15-17 (Resolve, the library walk, NFD).

Versions this was written against: companion 0.9.86
(`companion/src/ccsync_companion/config.py:158`), dashboard 0.7.76
(`dashboard/src/ccsync_dashboard/__init__.py:34`), schema v59
(`dashboard/src/ccsync_dashboard/db.py:2232`).

---

## In plain words

- Today a remote editor gets the small **proxy** copies of the footage, never
  the big camera **originals**. That is on purpose: originals are huge, and an
  editor can cut with proxies.
- Sometimes an editor needs the real originals for a few clips (a grade, a
  render, a reframe). Today that means someone typing commands on their
  computer.
- **The plan:** the editor selects the clips in Resolve's media pool and picks
  **Workspace > Scripts > CC Sync - Bring originals here**. CC Sync downloads
  just those originals onto that one computer, shows progress in the tray, and
  says when they are in. The same choice can be made from the project page on
  the dashboard, for a whole folder at once (that is exactly Ruskin's case).
- It is **per computer**. Selecting clips on Ruskin's PC never sends 80 camera
  files to anyone else, even though everyone shares the same Resolve project.
- **Nothing is ever deleted** by choosing or un-choosing. The files are copies
  of what the server already holds. Clearing them off the disk is a separate,
  checked button.
- Resolve should not need relinking: the clips already point at `P:\...`, and
  on an editor's computer `P:` is their own tree, so the file simply appears
  where Resolve is already looking. Whether Resolve notices without a nudge
  is the one thing that has to be tried on a real machine.
- Build order: the download engine and the dashboard folder picker first (that
  alone would have solved Ruskin's job), then the Resolve menu item.

---

## 1. What happens today

| Lane | What | Direction | Evidence |
|---|---|---|---|
| A | video files outside `Proxy/` | editor to NAS only | `SPEC.md:38`; `build_filter_rules_up`, `companion/src/ccsync_companion/sync/rclone_lane.py:980` |
| B | `**/Proxy/**` and nothing else | NAS to editor only | `build_filter_rules_down`, `rclone_lane.py:1032-1081` (`"- **"` last) |
| C | everything that is not video | both ways | `.stignore` ignores every video extension: `server/common.py:662-679`, companion copy `sync/syncthing_admin.py:93` |

So there is no route by which a camera original reaches a remote editor.
There is one narrow precedent: `broll_fetch.py` already pulls single files out
of the **Projects tree** for the YouTube path (`PROJECTS_REMOTE_REL =
"Projects"`, `broll_fetch.py:106`, CR-32), with one `rclone copyto` per file
(`build_fetch_command`, `broll_fetch.py:268-303`). It is "deliberately NOT a
lane: no filter files, no LaneStatus, no dashboard reporting"
(`broll_fetch.py:27-31`) and is capped at two concurrent jobs
(`broll_fetch.py:58`).

Ruskin's manual `rclone copy` worked and broke nothing, for reasons this
design relies on (each is checked in section 4): lane B is `rclone sync` with a
Proxy-only filter, and a file its filter excludes is not deleted from the
destination; lane A is `copy --ignore-existing`, so a file the NAS already has
is not uploaded again.

---

## 2. How an editor marks clips (question 1)

### 2.1 What the companion can already see, and what it costs

- **The media pool walk** runs every `media_tree_refresh_interval`, 120 s by
  default (`app.py:2057`, `_refresh_media_tree_once` at `app.py:4598`). Every
  item carries `file_path`, `clip_name` and `bin_path`
  (`resolve_bridge.py:1808-1830`).
- With the **library walk** on (default, `resolve_bridge.py:1109`), the pool
  comes out of Resolve's PostgreSQL project library in milliseconds with
  `_API_LOCK` released (`library.py:1-12`, `pool_items` at
  `library.py:1097-1138`). It reads `Sm2MpMedia.Name` and `Sm2MpFolder_id`
  and the paths from `BtVideoInfo`/`BtAudioInfo`, nothing else. **Bin
  membership is therefore free; any per-clip attribute is not.**
- The API walk, the fallback, reads three properties per clip under
  `_API_LOCK` (`resolve_bridge.py:1806-1830`; "Three one-arg reads ... 0.3 ms
  against 12.5 ms per clip"). Every extra property is one more locked native
  call per clip, every 120 s, for as long as the companion runs. The proxy keys
  are already read that way in 100-clip chunks with the lock released between
  chunks (`docs/GOTCHAS.md` §16, around line 1203), precisely because a whole
  pass under the lock parks the watcher, the tray and the b-roll `/insert`
  (`resolve_bridge.py:52-69`).
- The project library is **shared**: remote editors collaborate on the
  self-hosted project server, `postgres:13` on the NAS (`SPEC.md:5`,
  `docs/LIBRARY_WALK_PLAN.md:24`). One library holds every project
  (`library.py:38-39`).

### 2.2 The options

| Door | Who sees the mark | Cost on every pass | Verdict |
|---|---|---|---|
| **Clip colour** (`MediaPoolItem.SetClipColor`) | every editor, it lives in the shared library | one extra locked API call per clip per pass; the library column is not known (unverified, likely inside `Sm2MpMedia.FieldsBlob`, which `library.py:1101-1108` says costs 76 ms and a nested zstd frame to open) | **No.** One colour per clip, shared by everyone, so "Ruskin wants this" and "Leso wants this" cannot both be said, and editors already use colours to organise (unverified). A colour set for one person downloads to everyone who reads it. |
| **Flag** (`AddFlag`) | every editor | same as colour | **No**, same reasons; several flags per clip, but a flag is a colour, not a person. |
| **Keyword** (metadata `Keywords`, e.g. `originals:ruskin`) | every editor, but multi-valued, so it can name a person | one `GetMetadata` per clip per pass (unverified where the library keeps it) | **Fallback only.** It works per person and a Smart Bin can show "my originals", but it costs a locked call per clip forever, keys on a typed name (a display name is a label, never a key, `CLAUDE.md` account page), and a typo silently selects nothing. |
| **A dedicated bin** ("CC Sync originals/ruskin") | every editor | **zero**: `bin_path` is already in every walk | **No.** A Resolve clip lives in exactly one bin, so marking means MOVING the clip out of the bin the team organised it into, for everyone. That is an edit to a shared project made for a private reason. |
| **Marker** | every editor | per-clip `GetMarkers` | **No**; markers are for the cut and show on the timeline. |
| **Scripts menu item** (Workspace > Scripts) acting on the clips selected in the media pool | **only this computer**: nothing is written into the project | **zero on every pass**; it runs only when the editor clicks it | **Recommended.** |
| **Dashboard project page**, per folder or per file | the editor and admins | zero | **Recommended as the second door**, and the first to build. |

### 2.3 Recommendation

**Two doors into one store (section 3):**

1. **Resolve: a Scripts menu item** installed by the companion into Resolve's
   per-user `Fusion/Scripts/Edit/` folder (exact paths per OS unverified):
   - `CC Sync - Bring originals here` (the clips selected in the media pool)
   - `CC Sync - Stop bringing originals` (same selection)
   - `CC Sync - Bring originals for this timeline` (optional third item; the
     companion expands it, see below)

   The script reads the selection (`MediaPool:GetSelectedClips()`, existence in
   Resolve 21 **unverified**) and each clip's `File Path`, and **writes a
   request file** into `~/.ccsync/requests/originals/` instead of making a
   network call. The companion picks the file up, validates it, and does the
   rest. Reasons for a file rather than a POST to 8899:
   - **Lua, not Python.** Resolve runs Python menu scripts only when a
     separate Python 3 is installed on the machine (unverified on the fleet);
     Lua is built in, and Lua can write a file but has no HTTP client.
   - The loopback token (`loopback_guard.py:83-84`) would otherwise have to be
     read and sent by the script; a file under `~/.ccsync` carries the same
     trust (same user) without it.
   - The script does nothing to the project: no colour, no bin move, no
     metadata write. The shared library is never changed for a private choice.

   **CR-68 is not touched.** The menu script runs inside an already-running
   Resolve that the editor is clicking in, so it cannot fall into the launch
   window, and the companion itself makes **no new Resolve call** for this
   feature: `scriptapp()` keeps exactly one caller, `resolve_bridge.connect()`.
   The "for this timeline" item is answered by the companion from the walk it
   already does (the library walk sees inside multicams; the API walk finds 3
   usable paths of 904 on a multicam timeline, `docs/LIBRARY_WALK_PLAN.md:20`),
   so the script only names the timeline.

2. **Dashboard: the project page**, `[ BRING ORIGINALS TO ... ]` on a folder
   or a file, choosing which of the person's computers. Driven by `nas_media`
   (the NAS inventory, `db.py:48-57`, `kind = 'original'`), never by the
   reported media tree: `media_tree_clips` (`db.py:97`) is withheld on any
   computer that switches off `media_tree` (`telemetry_policy.py:78-80`,
   `app.py:4644`), and the NAS inventory is the truth about what can be
   downloaded anyway. This door needs no Resolve at all, which is why it is
   built first.

**So who is "selecting"?** A person, for one of their computers. The pick is
keyed like a tick (section 3) and is never visible to, or acted on by, another
machine. That answers the shared-library question by not writing into the
library at all.

---

## 3. Where the choice lives (question 2)

**On the dashboard, beside the tick.** A pick belongs to a computer exactly as
a tick does (`docs/MULTI_MACHINE_PLAN.md`), survives a companion reinstall,
shows on the project page, and is what the dashboard's backlog view needs to
say "Ruskin's PC: 37 of 80 originals in".

Proposed schema (v60, additive):

```sql
CREATE TABLE IF NOT EXISTS original_picks (
  editor_username TEXT NOT NULL,
  machine         TEXT NOT NULL,      -- never '' (no bucket for picks, see below)
  project_slug    TEXT NOT NULL,
  rel_key         TEXT NOT NULL,      -- db.media_rel_key(rel): NFC, the compare key
  rel_path        TEXT NOT NULL,      -- posix, relative to the project dir, as picked
  is_dir          INTEGER NOT NULL DEFAULT 0,
  picked_by       TEXT NOT NULL,      -- username, for fleet_audit
  picked_via      TEXT NOT NULL,      -- 'resolve' | 'dashboard'
  created_at      TEXT NOT NULL,
  PRIMARY KEY (editor_username, machine, project_slug, rel_key)
);
```

- **The key is the selections key** (`(editor_username, machine,
  project_slug)`, `selections` with `sync_mode`, `db.py:972`,
  `db.py:5354-5356`) plus the file. Not `machine = ''`: the unassigned bucket
  makes sense for a plan, not for "put 400 GB on that laptop".
- **Paths are (project, relative path) pairs, never absolute.** A Resolve
  `File Path` is `P:\Projects\...` on every machine (`SPEC.md:46`); the
  companion turns it into a tree rel with `canon.py` (`canonical_to_local`,
  `canon.py:147`) and into `(slug, rel)` with the sequencer's map
  (`sequencer.rel_to_slug`, `sequencer.py:824`). The dashboard stores the
  project slug and the rel inside it, as `nas_media` does (`db.py:50`).
- **NFC/NFD (CR-90, `docs/GOTCHAS.md` §17).** `rel_key` is
  `db.media_rel_key(rel)` (`db.py:10733`): the pick is compared against
  `nas_media` and `editor_media` in SQL, so it is normalised on the way in.
  The **download never uses either stored spelling**: before each run the
  companion lists the folder on the NAS and matches each pick by NFC key, then
  hands rclone the NAS's own bytes (the CR-44 shape: re-list, match, act on
  what is really there). "Never normalise a path something opens" holds.
- **Picks require a FULL tick** of the project on that computer. An
  upload-only tick means "nothing comes down" (`docs/UPLOAD_ONLY_TICK.md` §1)
  and a wired machine's tree is the NAS (CR-28, `db.base_only_editors`);
  both refuse with a sentence, never a silent no-op. Unticking the project
  drops its picks (they are about that tick).
- **A folder pick is a live rule** (default, open decision D3): every original
  under it, including ones uploaded later.
- **The companion keeps a local ledger** (`~/.ccsync/state/originals.json`):
  which files it brought down, their size and NAS mtime at arrival. It is what
  the "free the space" button (section 5) checks against, and it is never the
  source of what to download; the dashboard is.

---

## 4. How the bytes come down (question 3)

### 4.1 The options

| Engine | Verdict | Why |
|---|---|---|
| **Syncthing, per-machine `!` lines in `.stignore`** | **Rejected** | The NAS's own folder ignores every video extension (`server/common.py:662-679`), so the NAS never offers a video to any peer; an editor-side `!*.braw` brings nothing. Making the NAS offer it means changing the NAS folder's `.stignore`, which is ONE file per folder for every device sharing it: fleet-wide, not per machine. The dashboard collector re-POSTs that file on any difference (`collector.py:1164-1194`, `have == want`), and the companion fail-closes on missing lines and on `!` restrictions (`syncthing_admin.py:170`, `is_restricted` at `:267`). `SPEC.md:42` already says why: Syncthing cannot be told "this type, this direction, this machine". |
| **Widen lane B's include list** | **Rejected** | Lane B is `rclone sync`, the one verb that deletes locally (`build_down_command`, `rclone_lane.py:2668`; delete caps `rclone_lane.py:150-151`; trash `rclone_lane.py:69`). An original inside its filter is an original lane B will move to `.ccsync-trash` the moment the NAS loses it (a hand move, `docs/SYNC_SAFETY.md` §7), counted by the breaker (`sync/lane_guard.py`, CR-44/45) as a mass delete of 40 GB files. Picks would also be rewritten into the filter file every pass. Keeping originals OUT of lane B's filter is what makes them safe: an excluded file is never deleted by `sync` (the same property `rclone_lane.py:1062` relies on for YouTube originals). |
| **`broll_fetch.poll_fetch`, one `copyto` per file** | **Reuse the parts, not the module** | Right shape for one clip a page is polling for; wrong for 80 files: no LaneStatus (so the power guards, the drive reminder and the tray cannot see it, `broll_fetch.py:27-31`), a two-job cap shared with Send to Resolve (`broll_fetch.py:58`), one rclone process per file. |
| **A new down-only run: `rclone copy --files-from-raw --ignore-existing`** | **Recommended** | The express lane's argv, reversed (`build_express_command`, `rclone_lane.py:2557-2626`; list writer `write_files_from_list`, `rclone_lane.py:2505`). `copy` never deletes; `--ignore-existing` never overwrites a local file; the list is validated and written atomically. |

### 4.2 The recommended engine: `lane_b_originals_down`

- **A new `RcloneLane`-shaped adapter** (direction down), name
  `lane_b_originals_down`, so it has a `LaneStatus` like every lane and
  everything that reads statuses sees it.
- **argv**: `rclone copy <down route>:<remote_root>/Projects/<project rel>
  <local_root>/Projects/<project rel> --files-from-raw <list> --ignore-existing
  --no-traverse --partial-suffix <own suffix> --transfers 2`, plus the down
  tuning and route flags exactly as `broll_fetch.build_fetch_command` takes
  them (`rclone_lane.down_route`, `RcloneTuning.flags(DIRECTION_DOWN)`,
  `route_flags`, `_transport_flags`, `broll_fetch.py:283-303`), so a tunnel
  route or an operator knob applies here too. `--files-from-raw` refuses every
  filter flag (measured, `rclone_lane.py:2585-2601`), so the rules are applied
  in Python before a name enters the list: inside the project, a video
  extension, not under `Proxy/`, not a partial, not trash, and present in the
  NAS listing taken for this run.
- **Off the rotation's critical path.** Sequencer turns are one project at a
  time and joined (`_run_lanes_a_and_b`, `sequencer.py:2557-2590`); a 40 GB
  original inside that join would hold every other project's proxies back,
  which is the CR-347 lesson (`sequencer.py:2571`). The originals run gets its
  own thread and one slot, woken by a pick change or the sequencer's pass, and
  bounded by `--max-duration` like the express run.
- **Disk floor.** It shares lane B's `DiskFloorLatch` (`sync/lane_guard.py:958`,
  `_check_disk_floor`, `rclone_lane.py:5195-5216`): a nearly-full drive parks
  originals first (they are the optional bytes), never lane A. Before a pick
  is accepted the dashboard shows the total from `nas_media.size`, and the
  companion refuses a run whose total exceeds free space minus the floor, with
  a sentence naming both numbers.
- **Root guard.** Same `fetch_refusal` questions (`broll_fetch.py:220-265`):
  destination inside the tree, tree actually mounted (a Mac's absent
  `/Volumes/<Name>` would otherwise fill the boot disk).
- **Power guards and the drive reminder.** Because it has a LaneStatus,
  `shutdown_guard.busy_lanes` (`shutdown_guard.py:211`) and
  `PendingTracker.live_busy` (`shutdown_guard.py:389`) see it. The drive
  reminder needs a noun and a set entry (`drive_reminder.py:90`,
  `DOWNLOAD_LANES` at `drive_reminder.py:109`): an interrupted download owes
  nothing, so it never recurs as a reminder. Open decision D6: whether a
  download alone should keep the PC awake (default: yes, like lane B).
- **Tray.** One line while it runs ("Bringing originals: 12 of 80, 140 GB to
  go"), one balloon when a request is done. No em dashes in that copy.
- **Halt.** Honours `sync_halt.json` and the fleet halt like every lane.

### 4.3 Interaction with the other lanes

- **Lane B** never sees the files: its filter is Proxy-only with `- **` last
  (`rclone_lane.py:1069-1081`), so an original placed beside the `Proxy/` dir
  is outside it and is neither copied nor deleted. The breaker's mass-delete
  judgement is lane B's alone and is untouched.
- **Lane A** would not re-upload them: it is `copy --ignore-existing`
  (`docs/FILE_MOVES.md` §1) and the NAS has every one of them. Two costs to
  handle in the build: the express watchdog sees each arriving file and runs a
  `--ignore-existing` no-op for it (harmless, but the downloader should hand
  its in-flight and just-landed names to lane A's exclude hook, the one
  `file_moves` already uses, `rclone_lane.py:3234-3238`); and the pulled
  files are mtime-preserved, so the express gate's age test passes at once
  (`_express_partition`, `rclone_lane.py:7242`). The partial name never
  matches the lane A video rules (`+ *<ext>`, `rclone_lane.py:1028`).
- **Lane C** is unaffected: video is ignored on both ends.
- **A file moved on the NAS** through the dashboard follows to every machine
  "whose manifest says it holds the file" (`docs/FILE_MOVES.md` §2 item 2), so
  a pulled original moves with it. A pick must follow too: the move route
  rewrites matching `original_picks` rows in the same transaction.
- **A file deleted on the NAS by hand** comes back from the editor's pulled
  copy through lane A, as it does today from whichever editor holds a copy
  (lane A never deletes, `docs/SYNC_SAFETY.md` §5 and §7). Accepted; it is the
  safe direction.
- **Proxy generation** does not start for a pulled original: on a lane B
  editor rig `proxy_gen_enabled` derives to false (`config.py:2505-2543`).
- **The removal gate** ("Remove from this machine", `app.removal_blockers`,
  `app.py:6183`) treats them correctly as already on the server: its lane A
  dry run lists nothing for a file the NAS has.

---

## 5. Un-choosing, and Resolve (question 4)

### 5.1 Un-choosing never deletes

- **Un-picking** stops a download that has not finished (the partial is
  rclone's to clean) and removes the row. **The files already down stay.**
- **Is a pulled original ever the only copy?** Not when it arrives: it is a
  copy of a NAS file. It can BECOME the only copy if the NAS loses its own
  (section 4.3), which is exactly why nothing in this feature deletes on its
  own.
- **"Free the space"** is a separate tray/dashboard action, per project:
  delete pulled originals that (a) are in this computer's ledger, (b) still
  exist on the NAS at the same size (a fresh `rclone lsjson`, not the cached
  inventory), and (c) are unchanged locally since they arrived (size and
  mtime). Any doubt keeps the file. That is the removal gate's fail-closed
  posture (`app.py:6200-6204`) applied to a smaller set. The whole-project
  "Remove from this machine" (`app.py:6530-6595`) stays as it is.

### 5.2 Resolve after the file lands

- **No relink should be needed.** All project-stored paths are
  `P:\Projects\...` on every machine (`SPEC.md:46`); on a Windows editor `P:`
  is `subst`ed to the local root, on a Mac Resolve's Mapped Mount translates
  it (`SPEC.md:46`). The download writes exactly where the path already
  points. Resolve's `File Path` is unchanged, so no `replace_clip`, no save
  point, no undo journal (`docs/RESOLVE_EDIT_SAFETY.md` rules stay
  untouched).
- **Does Resolve notice?** **Unverified.** Whether an offline clip goes
  online by itself, needs the project re-opened, or needs "Relink Selected
  Clips" in Resolve 21 is the first thing to try on FF5lab when Resolve is
  free. The balloon will say what to do; the companion does not touch Resolve
  to force it.
- **Proxies stay attached** (`Proxy Media Path` is independent of `File
  Path`, `proxy_relink.py:1-20`), so playback keeps using them when the
  project prefers proxies, and a render or grade can use the original.
  Resolve's proxy/render settings for this are **unverified**.

---

## 6. Wire, schema, deploy, telemetry, copy (question 5)

- **Dashboard (schema v60):** `original_picks` above. Routes:
  `PUT /api/v1/selection/{editor}/{slug}/originals?machine=` with
  `{"add": [rel...], "remove": [rel...], "dirs": [...]}` (session or the
  companion's identity-bound token, the `_require_selection_read` rule,
  `api.py:2915`); a 409 with a sentence for upload-only, unticked or wired.
  `fleet_audit` row per change.
- **Selection GET:** each item gains `originals` (resolved list of rels under
  the item's project, from picks expanded against `nas_media`). Additive, like
  `includes` (`api.py:2904-2908`). An old companion ignores it, which is the
  safe direction (nothing comes down).
- **Progress, without a new personal report key.** The dashboard computes
  "N of M in" from the picks against `editor_media` (`db.py:86`, `kind =
  'original'`), which the companion already reports under `local_manifest`.
  A computer withholding `local_manifest` shows "cannot tell", never "done".
  The lane's own status rides the existing lane status block (counts and
  bytes only); if a per-file name is ever added it needs a
  `telemetry_policy.FIELDS` row under `local_manifest`
  (`telemetry_policy.py:65-76`) and a line in `docs/legal/TELEMETRY.md`, and
  `tests/test_telemetry_disclosure.py` fails until both exist.
- **Deploy order: dashboard first**, as everywhere. A new companion against an
  old dashboard sees no `originals` key and does nothing; an old companion
  against a new dashboard ignores the key. Picks made before a computer
  upgrades simply wait. Neither order can over-share, but dashboard-first means
  the page never offers a pick the computer cannot act on (gate the button on
  the computer's reported version).
- **Versions:** dashboard 0.7.77, companion 0.9.87 (or whatever is next), both
  `VERSION` and `pyproject.toml`.
- **Feature flag:** `site.toml [features] originals_on_request`, off in the
  vendor build, on for this studio (the "optional features are off in the
  vendor build" rule, read by `site.feature_enabled`,
  `companion/src/ccsync_companion/site.py:296`, which fails closed). The menu
  script is installed only when it is on, and removed when it is turned off.
- **Copy (no em dashes):** menu items `CC Sync - Bring originals here`,
  `CC Sync - Stop bringing originals`; tray `Bringing originals: 12 of 80`;
  refusals like `This project is upload only on this computer, so nothing
  comes down. Switch it to full sync first.`

---

## 7. Build plan (question 6)

**Phase 0 - spikes (no fleet change).** On FF5lab, when Resolve is free:
does `MediaPool:GetSelectedClips()` exist in Resolve 21 from Lua; where the
per-user Scripts folder is on Windows and macOS; does a clip go online when its
original appears; do `GetSelectedClips` items include multicam/compound clips.
Each answer replaces an "unverified" in section 10.

**Phase 1 - the engine and the dashboard door (solves Ruskin's case).**
Dashboard: v60 table, PUT route, selection `originals` key, project page
folder/file picker with sizes, progress from `editor_media`. Companion: the
`lane_b_originals_down` adapter, NAS re-list and NFC match, disk floor, root
guard, halt, lane A exclude hand-off, LaneStatus (tray line, power guards,
drive reminder noun), the local ledger. Ship dashboard first.

**Phase 2 - the Resolve door.** The Lua menu script, its install/remove by the
companion (only with the flag on), the request inbox
(`~/.ccsync/requests/originals/`, polled, each file validated and deleted
after it is answered), mapping `File Path` to `(slug, rel)`, the PUT to the
dashboard, a balloon per request. "For this timeline" through the existing
walk.

**Phase 3 - free the space.** The checked delete of section 5.1, from the
tray and the project page (the page sends a command the companion executes and
answers, like `commands.file_moves`, `app.py:8882`).

**Phase 4 - polish.** File moves rewrite picks; the backlog view lists picks;
`tools/` doctor line.

---

## 8. Risks

- **A large pick on a small drive.** Mitigated by the size shown up front, the
  free-space refusal and the shared disk floor; the residual risk is a drive
  that fills from something else mid-run, which the floor latch already parks.
- **Bandwidth.** 80 originals can be hundreds of GB on the same link lanes A
  and B use. One slot, `--transfers 2`, off the rotation's join; lane A's
  footage reaching the NAS outranks it (open decision D5).
- **Resurrection.** A pulled original re-uploads a file someone deleted on the
  NAS by hand (section 4.3). Existing behaviour for any held copy; called out
  so nobody is surprised.
- **Menu script drift.** A Resolve update that moves the Scripts folder or
  changes `GetSelectedClips` breaks only the Resolve door; the dashboard door
  keeps working. The companion logs (and the Settings window says) when the
  script could not be installed.
- **Request files from another local process.** Same trust as the loopback
  token file; the worst a forged request does is download footage the user
  could already download, into their own tree, after every validation above.
- **NFD.** Covered by matching against the NAS listing at run time; a test
  with `Matej Šimalčík` in both spellings is part of phase 1.

---

## 9. Open decisions for the owner (recommended default first)

- **D1. Where clips are picked.** *Default:* both doors, the dashboard folder
  picker first, the Resolve menu item second. Alternative: Resolve only.
- **D2. Shared mark or private choice.** *Default:* private (per computer,
  nothing written into the Resolve project). Alternative: a keyword that names
  the person, visible to the team, costing a Resolve call per clip on every
  pass.
- **D3. A folder pick: now, or also later uploads?** *Default:* also later
  uploads (a live rule). Alternative: only what is there now.
- **D4. Who may pick for whom.** *Default:* an editor for their own computers,
  an admin for anyone's (the tick rule).
- **D5. Priority against uploads.** *Default:* originals coming down never slow
  footage going up: one slot, two transfers. Alternative: full speed.
- **D6. Keep the PC awake for an originals download.** *Default:* yes, like
  proxies.
- **D7. Un-picking.** *Default:* keeps the files; "free the space" is a
  separate, checked button. Alternative: un-picking offers to free the space
  in the same step.
- **D8. Feature flag.** *Default:* `originals_on_request` off in the vendor
  build, on here.
- **D9. Picks on an upload-only tick.** *Default:* refused with a sentence.
  Alternative: picking switches the tick to full.

---

## 10. Not verified (needs a running Resolve or a live machine)

- `MediaPool:GetSelectedClips()` exists in Resolve 21 and is callable from a
  Lua menu script; whether it returns multicam and compound clips.
- The per-user `Fusion/Scripts/Edit/` paths on Windows and macOS, and whether
  Python menu scripts need a separately installed Python on fleet machines.
- Whether an offline clip goes online by itself when its file appears, or needs
  a project re-open or a relink.
- Resolve's proxy-preference and render-with-originals settings in this
  workflow.
- Where the library keeps clip colour, flags and keywords (assumed
  `Sm2MpMedia.FieldsBlob`; only matters if D2 goes the other way).
- That editors already use clip colours for their own organisation.
- The cost of one extra `GetMetadata`/`GetClipColor` per clip per pass (the
  0.3 ms per three reads figure at `resolve_bridge.py:1806` suggests about
  0.1 ms per call, about 0.4 s per pass under the lock for a 4,000-clip
  project; not measured).

## 11. Tests the build should carry

Dashboard: picks keyed per computer, refused for upload-only / unticked /
wired, the `originals` key expands a folder pick against `nas_media`, NFC and
NFD picks are one row, a file move rewrites picks, an old companion's
selection GET is unchanged apart from the new key, progress reads "cannot
tell" when `local_manifest` is withheld, and the no-em-dash scan covers the new
copy. Companion: the argv is `copy` and carries `--ignore-existing` and never
a filter flag, every list entry passes the Python rules, a name absent from the
NAS listing never reaches the list, the disk floor parks it, lane B's filter is
unchanged, lane A's exclude hook receives in-flight names, the drive reminder
treats it as a download, an unknown `originals` shape fails closed (nothing
downloads), and the request inbox rejects paths outside a ticked project.

---

## 12. Owner decisions and the build contract (2026-10-31)

The owner answered section 9 the same evening:

| | Decision |
|---|---|
| D1 | Build the Resolve menu, AND make it work on timeline clips. The dashboard side is built too (it is where picks are stored and shown). |
| D2 | **Choices are visible**: every pick is listed, with the person and computer it belongs to, on the project page for everyone who can see the project. Nothing is written into the Resolve project (no keyword, colour or flag): "visible" is the dashboard listing. A pick still belongs to one computer. |
| D3 | Yes: a folder pick is a live rule (later uploads come too). |
| D4 | Yes: an editor picks for their own computers, an admin for anyone's. |
| D5 | Never: originals coming down never slow footage going up (one slot, `--transfers 2`). |
| D6 | Yes: an originals download keeps the PC awake. |
| D7 | Yes: un-picking keeps the files ("free the space" is phase 3, not in this build). |
| D8 | **No feature flag.** The feature is on everywhere; the menu script is always installed. |
| D9 | Picks on an upload-only tick are refused, and the user is WARNED with a sentence that says how to fix it (balloon from the menu, inline error on the page). |

**Resolve has no timeline-selection API.** The installed `README.txt`
(Resolve 21, `Developer/Scripting`) offers `MediaPool:GetSelectedClips()` but
nothing that returns the timeline items the user has selected. "Timeline
clips" is therefore what the API can see: the items between the timeline's
In and Out marks (`Timeline:GetMarkInOut()`), else the item under the
playhead (`Timeline:GetCurrentVideoItem()`), or the whole timeline.

### 12.1 Menu items (Lua, `Fusion/Scripts/Edit/CC Sync/` per user)

- `Bring originals - selected media pool clips`
- `Bring originals - timeline clips between In and Out` (no marks: the clip
  under the playhead)
- `Bring originals - whole timeline`
- `Stop originals - selected media pool clips`
- `Stop originals - timeline clips between In and Out`

Per-user Scripts root: Windows `%APPDATA%\Blackmagic Design\DaVinci
Resolve\Support\Fusion\Scripts`, macOS `~/Library/Application Support/Blackmagic
Design/DaVinci Resolve/Fusion/Scripts` (README lines 48-58). The companion
installs (and on upgrade rewrites) the files; it never calls Resolve to do so.

### 12.2 Request file (script -> companion)

`~/.ccsync/requests/originals/<unix_ms>-<random>.json`, written to `.tmp`
then renamed. UTF-8 JSON:

```json
{"v": 1, "action": "add" | "remove",
 "source": "media_pool" | "timeline_range" | "timeline_playhead" | "timeline_all",
 "project": "<Resolve project name>", "timeline": "<name or null>",
 "clips": [{"file_path": "P:\Projects\...", "unique_id": "<MediaPoolItem id>",
            "name": "<clip name>", "type": "<Type clip property>"}],
 "created_at": "<ISO-8601>"}
```

A clip with an empty `file_path` (multicam, compound, generator) is resolved
by the companion from the walk it already does; the script never descends.
The companion validates, answers with a balloon, and deletes the file
(malformed or older than 1 h: logged and deleted).

### 12.3 Dashboard wire

- Schema v60 `original_picks` as section 3.
- `PUT /api/v1/selection/{editor}/{slug}/originals?machine=<m>` body
  `{"add": [{"rel": "<posix rel inside the project>", "is_dir": false}],
  "remove": ["<rel>"], "via": "resolve" | "dashboard"}` -> 200
  `{"ok": true, "added": n, "removed": n, "total_bytes": n}`; 409 `{"detail":
  "<sentence>"}` for upload-only (D9 wording), not ticked, or a wired machine;
  auth = the companion's identity-bound token for its own editor, or a session
  (own computers; admin any). `fleet_audit` row per change.
- `GET` selection: each item gains `originals`: the expanded list of posix
  rels (files only, live folder rules expanded against `nas_media` kind
  `original`). Absent key = nothing to bring.
- Project page: an ORIGINALS ON REQUEST window listing every pick (person,
  computer, file or folder, size, "N of M in" from `editor_media`, "cannot
  tell" when `local_manifest` is withheld), a folder/file picker to add for a
  computer you may pick for, and remove.

Versions: dashboard 0.7.77 (carries CR-379 too, the exact-name auto-map), companion 0.9.87.
