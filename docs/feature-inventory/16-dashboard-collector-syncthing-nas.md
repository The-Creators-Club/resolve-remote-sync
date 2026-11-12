# Dashboard: the background cycle, Syncthing management, project provisioning, recovery and the NAS back-ends

Terms used throughout:

- **Syncthing**: the file-sync program running on the NAS. The dashboard talks to its REST API.
- **Folder**: a Syncthing folder, i.e. one directory Syncthing keeps in step between the NAS and some editor computers. Every project is one folder; its folder id is the project's **slug**.
- **Device**: one Syncthing installation (the NAS's own, or one editor computer's), identified by a long device id.
- **Share**: a folder being shared with a device. Sharing means that computer receives the folder.
- **Tick / selection**: an editor's choice (per computer) to sync a project. "Full" ticks receive the folder; "upload-only" ticks do not.
- **Marker**: the file `.ccsync-project` (JSON) inside a directory. A directory is a project only because it carries one. Its `slug` key is the project's permanent identity.
- **Projects tree**: the `Projects` directory on the NAS, mounted into the dashboard container (`DASH_PROJECTS_DIR`). Syncthing sees the same tree under a different prefix (`DASH_SYNCTHING_DATA_PREFIX`, default `/data/Projects`).
- **Notice**: a card on the dashboard home page under "problems the server found", keyed by (kind, subject), with a body text and a "fix" text. Writing one again re-opens it; clearing it closes it.
- **Poll run record**: per pass kind, the time, success or failure and a note, shown on the collector health panel.

## The background cycle: scheduling, failure handling and health
(source: collector.py, settings.py defaults)

- One background loop runs inside the dashboard process for its whole life. It runs ten kinds of pass, always in this fixed order when several are due together: `provision`, `config`, `enforce`, `inventory`, `connections`, `completion`, `remoteneed`, `prune`, `invariants`, `alerts`.
- Default interval of each pass (each overridable by an environment variable):
  - provision: every 300 s (`DASH_INTERVAL_PROVISION`).
  - config: every 120 s (`DASH_INTERVAL_CONFIG`).
  - enforce: every 60 s (`DASH_INTERVAL_ENFORCE`).
  - inventory: every 900 s (`DASH_INTERVAL_INVENTORY`).
  - connections: every 15 s (`DASH_INTERVAL_CONNECTIONS`).
  - completion: every 60 s (`DASH_INTERVAL_COMPLETION`).
  - remoteneed: every 60 s (`DASH_INTERVAL_REMOTENEED`).
  - prune: every 3600 s (`DASH_INTERVAL_PRUNE`).
  - invariants: every 900 s (`DASH_INTERVAL_INVARIANTS`).
  - alerts: every 600 s (`DASH_INTERVAL_ALERTS`).
- All ten passes are due immediately when the loop starts.
- The loop sleeps until the next pass is due, but never longer than 5 s and never shorter than 0.5 s, then runs every due pass in the canonical order.
- **Backoff on failure**: a failed pass is next run after the longer of (its normal interval) and (a backoff that starts at 15 s and doubles each consecutive failure, capped at `DASH_BACKOFF_MAX`, default 300 s). A success resets the backoff. Backoff never makes a pass run sooner than its normal interval.
- **Nudge**: other parts of the dashboard (for example ticking a project) can ask for specific passes to run at the next wake (within about 5 s) instead of waiting out their interval. The default nudge set is config, enforce, connections and completion.
- **Database connection**: the loop opens its own long-lived database connection with a longer lock-wait than a web request (the "background" busy timeout) and runs the schema migration on it. If opening or migrating fails, it logs, closes the half-opened connection and retries every 5 s, forever.
- Any unexpected error in one loop iteration is logged ("collector loop iteration failed; continuing") and the loop carries on.
- **Per-pass fault isolation**: an exception inside one pass rolls back that pass's database changes, logs it (warning level for a Syncthing error, error level otherwise), records the pass as failed with the error text, and the remaining passes in the same cycle still run.
- Every pass's outcome is recorded (start time, end time, ok or failed, and an optional note). A pass that succeeded but did only part of its job returns a note such as "partial: ..." or "skipped: ..." which is stored with the success.
- **Slow pass log**: a pass that takes more than 1.0 s is logged as "poll <kind> took N s".
- **Slow pass notice**: a pass that takes longer than the notice module's slow-poll threshold opens a `slow_poll` notice with subject "collector poll <kind>"; the next pass of that kind that finishes under the threshold closes it. Nothing is written for a clean pass unless a card is open (the open state is remembered in memory and looked up once per kind per process so a card surviving a restart is still cleared).
- **Liveness heartbeat**: the loop stamps a heartbeat at the top of every iteration. The dashboard's watchdog (outside this part) reads "seconds since heartbeat" to detect a loop stuck inside one call, and "thread died" to detect a loop that is gone. A deliberately stopped loop never reads as dead.
- **Restart by watchdog**: the watchdog can start a replacement loop only when the old one died and was not stopped on purpose, and never while one is still running. Each restart is counted; the next alerts pass reports the restarts it has not yet reported.
- **Stop**: stopping sets the stop flag, wakes the loop and waits up to 10 s for it to finish.
- **Passes that do not need Syncthing**: prune, invariants and alerts run even when no Syncthing URL is configured. Every other pass is recorded as a silent success when there is no Syncthing.
- **Passes that need the Projects tree**: provision and inventory are recorded as silent successes (no record noise) when `DASH_PROJECTS_DIR` is not set.
- **Hydration rule**: if completion or remoteneed is due and the config pass has never filled the project/device lookups in this process, a config pass is added to the cycle. If that config pass failed in the same cycle, completion and remoteneed are recorded as failed with the note "skipped: config hydration failed".
- **Work done at the start of every cycle, whatever is due** (each wrapped so a failure is logged and never stops the cycle):
  - Re-reads this site's list of shared asset libraries from site settings. On a read failure, or an empty answer, it keeps the previous list (never empties it). Initial list: the environment value `DASH_SITE_SHARED_ASSETS`, or the two defaults `Assets/Luts` and `Assets/Stills`.
  - Reconciles file moves: finishes or quarantines any recorded server-side file move whose rename never completed, and ages out move commands that were delivered and never answered (the logic lives outside this part, in the API module).
  - Runs the Claude Code command-line tool auto-update tick (keeps a wizard-installed copy current and sweeps the replaced version after its grace period; logic outside this part).
  - Runs the tailnet Serve watchdog tick (logic outside this part).
  - When Syncthing is configured, runs the Syncthing admin-page login guard tick (see "Syncthing admin page login guard" below).
- **Work done at the end of every cycle, whatever ran** (wrapped, never fails the cycle):
  - Re-probes the optional feature mounts (b-roll, music, cards and the like) and logs "feature mount <name> is now <status>: <detail>" for any that changed.
  - Asks Syncthing for its pending (not yet approved) devices when Syncthing is configured; "could not ask" is passed on as unknown, not as "none pending".
  - Runs the self-diagnosis notice checks (logic outside this part), handing them the pending devices and the current folder-to-device share picture. The share picture is passed as "not checked" until a config pass has completed in this process.
  - Brings the inventory pass forward for any project that has never been walked (see "Inventory pass").
- **One-shot command-line mode** (DEV ONLY): `python -m ccsync_dashboard.collector --once [--db PATH]` runs provision, config, connections, completion and remoteneed once against the configured Syncthing, prints "<kind>: ok" or "<kind>: FAILED" for each and the row counts of the projects, devices, current completion and missing-files tables, and exits with the number of failed passes.
  - Refuses with "FAILED: SYNCTHING_GUI_URL is not set" (exit 1) when no Syncthing URL is set.
  - Without `--once` it prints "use --once (the service runs the collector in-process via app.py)" and exits 2.
  - `--db` overrides the database path.

## Provision pass: turning marked directories into Syncthing folders
(source: collector.py `_run_provision`, provision.py)

- Runs every 300 s. Needs the Projects tree and Syncthing.
- Fails the whole pass with "DASH_PROJECTS_DIR does not exist: <path>" if the configured Projects directory is not a directory.
- Reads the full Syncthing configuration once at the start.
- **Marker scan**: walks the Projects tree up to 8 levels deep, skipping hidden directories (names starting with "."), never treating the Projects root itself as a project, and stopping descent at every directory that carries a marker (projects cannot nest). For each marker found it records the directory and the marker's slug.
  - A marker is read as UTF-8 (a byte-order mark is tolerated). It is ignored (treated as having no slug) when the file is missing, unreadable, not JSON, not a JSON object, has no `slug`, or the slug is not made only of lowercase a-z, 0-9 and "-". An invalid slug is logged as "IGNORING project marker in <dir>: slug <x> is not a valid identity".
- **Unreadable marker**: a directory whose marker cannot be read is skipped and gets a warning notice `unreadable_project_marker` (subject: the directory). Body: "The folder <rel> on the server has a damaged CCSync marker file, so it is not a project as far as this dashboard is concerned: nobody can tick it and nothing in it syncs."
  - If Syncthing already serves that directory under some folder id, the fix text tells the operator to replace the marker with one whose `slug` is that id, and says the server usually rewrites a fresh marker by itself within a few minutes.
  - Otherwise the fix text tells them to copy a working marker and set the slug to the project's id (the last part of its `/project/<id>` page address), or delete the damaged file if the folder was never a project.
  - The notice closes by itself on a pass where the directory is no longer unreadable.
- **Step 1, marker self-heal**: for every existing Syncthing folder whose path is under the Syncthing projects prefix, whose directory exists on disk and has no readable marker, the pass writes a marker carrying the folder id as slug, but only if:
  - the directory contains Syncthing's own `.stfolder` marker (otherwise logs "NOT writing a project marker ... no .stfolder there"), and
  - no other directory in the tree already claims that slug (otherwise logs "NOT writing a project marker ... that identity already lives at ...").
  - A write failure is logged and does not fail the pass.
- **Step 2, ignore-list repair**: for every project folder that exists in Syncthing, the folder's live ignore list (`.stignore`) is read and compared line by line with the canonical project list; any difference makes the pass write the canonical list back and log "REPAIRED .stignore on folder <id>". A failure to read the ignore list is logged and skipped; a failure to write it fails that project.
- **Step 3, retarget (a project directory that was moved or renamed on the NAS)**: when a marker's slug already has a Syncthing folder but at a different path, the folder's path and label are changed in place to the new location and the project's database row is updated (logged "RETARGETED syncthing folder <id>: <old> -> <new> (dir moved on the NAS)"). All the project's ticks and history survive because they are keyed on the slug. Refused (logged loudly, nothing changed, re-checked next pass) when any of these hold:
  - the folder's current path is outside the Syncthing projects prefix ("its current path ... is outside ..., so this container cannot verify what is there -- fix the folder by hand");
  - the old directory still exists (the new one is a copy, not a move);
  - the new directory has no `.stfolder` (an interrupted or still-running copy);
  - the new directory holds fewer than 50% of the video files (originals plus proxies) the last NAS inventory recorded for this project.
- **Label repair**: when the path is right but the folder's label differs from the directory's path relative to the Projects tree, the label is corrected ("fixed label drift").
- **Folder settings repair**: three settings are checked on every existing project folder and put back if they differ: `maxConcurrentWrites` = 32, `pullerMaxPendingKiB` = 65536, `ignoreDelete` = true (logged "REPAIRED folder settings on folder ..."). This repair is combined into the same single write as a retarget or label fix when both are needed. Other folder settings (devices, versioning) are never rewritten by this repair.
- **Step 4, create**: a marker whose slug has no Syncthing folder yet gets a new folder created, using the marker's slug as the folder id (not a slug derived from the path), with no devices (unshared until ticked), followed by setting its canonical ignore list (logged "auto-provisioned syncthing folder <id> (<rel>), unshared until ticked"). Creation is refused when:
  - the directory sits inside another marked project: notice `project_nested_marker` (error), body "The folder <rel> on the server is marked as a project, but it sits INSIDE another project (<parent>). Projects cannot be inside each other, so this one is not being set up and nothing in it syncs on its own." Fix: delete the inner marker or move the folder out beside the parent.
  - the directory contains marked projects below it (looked for up to 8 levels down, skipping hidden directories): notice `project_container_marker` (error), body "The folder <rel> on the server is marked as a project, but it CONTAINS N project(s) (...). Setting it up would hide them, so the dashboard has refused, and those projects are missing from this dashboard until it is sorted out." Fix: delete the container's marker.
  - another Syncthing folder already serves exactly that directory: notice `duplicate_syncthing_folder` (error), body "Two sync folders point at the same directory on the server (<rel>): this project's own (<slug>) and another one (<other>). Only one of them is the folder editors are connected to, so work saved through the other one goes nowhere." Fix: delete the stray folder in Syncthing on the server ("Nothing is deleted from disk by removing a Syncthing folder").
- **Duplicate marker (copied project)**: when two or more directories carry the same slug, the pass never guesses. If one of them is the folder's current path it keeps working with that one and ignores the rest; otherwise it skips all of them. Either way it opens notice `duplicate_slug_dirs` (error): "Two folders on the server both claim to be the same project (...). That happens when a project folder is COPIED rather than moved, because the copy brings the project's identity file with it." followed by either "The dashboard is working with the one it already knew and ignoring the other." or "The dashboard cannot tell which one is real, so it is leaving both alone and this project is not syncing." Fix: delete the `.ccsync-project` inside the copy, or delete the copy.
- **Per-project isolation**: each slug is handled separately. A failure for one opens notice `provision_failed` (error, subject the slug): "The project folder <rel> could not be set up for syncing: <error, first 200 chars>. Until this clears, nothing in that project reaches anybody." Fix: look at other problems first, otherwise check Syncthing is running. Other projects continue. At the end of the pass, if any project failed, the pass is recorded as failed with "N folder(s) failed to provision: ...".
- **Step 5, shared asset libraries** (see next section). Failure opens notice `shared_assets_failed` (error, subject "shared asset libraries"): "The shared asset libraries (the LUT library) could not be set up: <error>. Editors will see their LUTs missing in Resolve." Fix: check Syncthing, then the shared folders on Settings, Site. Cleared on the next success. Counts as a pass failure.
- **Step 6, cross-project folder links** (see "Cross-project folder links"). Failure opens notice `project_links_failed` (warn, subject "shared folder links"): "A shared-folder link between projects could not be resolved: <error>. The borrowed folder will not appear in the project that borrows it." Fix: check the borrowing project's shared folder links. Cleared on success. Counts as a pass failure.
- Every notice kind this pass writes (unreadable marker, provision failed, duplicate slug, duplicate Syncthing folder, container marker, nested marker) is closed automatically for any subject that no longer has the problem on this pass.
- The pass never deletes a Syncthing folder. A folder whose directory has vanished is left alone.

## Shared asset libraries (the LUT library and friends)
(source: collector.py `_ensure_shared_folders`, provision.py)

- Default libraries: folder id `assets-luts` at `Assets/Luts`, labelled "Assets/Luts (LUT library)"; folder id `assets-stills` at `Assets/Stills`, labelled "Assets/Stills (Resolve gallery)".
- A site can replace the list with `DASH_SITE_SHARED_ASSETS` (comma-separated relative paths) or through site settings (read every cycle). Each library's folder id is the slugified path. A path with no letter or digit, or one whose id duplicates an earlier one, is left out and logged. `..` segments and leading slashes are dropped. Labels other than the two defaults are the path itself.
- The libraries live at `DASH_SYNCTHING_ASSETS_PREFIX` (default `/data/Assets`) plus the part of the path after `Assets/`. If the prefix is set blank, the libraries are not provisioned at all.
- A missing library folder is created unshared, then its asset ignore list is set ("auto-provisioned shared asset folder ...").
- A library folder whose path differs from the configured one is left alone and logged as an error ("leaving it alone. Fix the folder in the Syncthing GUI or set DASH_SYNCTHING_ASSETS_PREFIX to match."). It is never retargeted.
- An existing library gets its ignore list and its three tuned settings repaired every provision pass exactly like a project.
- Libraries are not projects: no marker, no database project row, no tick, never listed among projects, never inventoried, never seeded with ticks.
- Sharing: every editor device the dashboard can map to a known editor receives every library, except devices of suspended editors.
- Folder settings for a library are the same as a project's (below), with the full path and fixed label.

## Syncthing folder settings and ignore lists the dashboard writes
(source: provision.py)

- Every project folder is created with: type send-and-receive; file-system watcher on; permissions ignored (the dataset refuses chmod); full rescan every 3600 s; `maxConcurrentWrites` 32; `pullerMaxPendingKiB` 65536 (64 MiB); staggered versioning (clean every 3600 s, keep versions up to 31,536,000 s, i.e. one year); `ignoreDelete` true (a delete made on an editor's machine is never applied to the NAS copy); label = path relative to the Projects tree; path = Syncthing projects prefix + that relative path.
- **Video extensions** (decide what travels by the other sync lanes rather than Syncthing, and what the inventory counts): `.braw .mov .mp4 .mxf .avi .mts .m2ts .mkv .r3d .crm .mpg .mpeg .wmv .webm .insv .360`, case-insensitive.
- **Project ignore list**, in this exact order: one case-insensitive pattern per video extension; `**/*.partial` and `*.partial` (interrupted rclone transfers); `**/*.part`, `*.part`, `**/*.part-Frag*`, `*.part-Frag*`, `**/*.ytdl`, `*.ytdl` (in-progress YouTube downloads); then `Proxy`, `**/Proxy`, `**/Proxy/**` (proxy folders). All case-insensitive.
- **Library ignore list**: the video extension patterns, the two `.partial` patterns, then OS junk: `.DS_Store`, `Thumbs.db`, `desktop.ini`, `*.tmp`, `*.ccsync-tmp`, each at top level and at any depth.
- **Media classification for the inventory**: a file counts only if its extension is a video extension; it is a "proxy" if any folder in its path is named `Proxy` (any case), otherwise an "original".
- **Default new-project template folders** (used by the project-creation flow elsewhere): `AE`, `Audio/Music`, `Audio/Voiceover`, `B-roll`, `Interviewees`, `Render in Place`, `Subs`, `Youtube`. Overridable with `DASH_SITE_TEMPLATE_FOLDERS` (comma-separated; blank means default; `..` segments dropped).
- **Slug rule** (for derived ids such as library ids): lowercase, every run of characters other than a-z and 0-9 becomes one "-", leading and trailing separators removed; an empty result is an error.
- **Marker writing**: a marker write keeps every existing key in the file (for example `includes`) and sets `slug`, `created_by` (default "dashboard") and `created_at` (UTC, seconds). It is written atomically through a temporary file in the parent directory (named `.ccsync-project.<dir>.<pid>.<random>.tmp`), never inside the project, so Syncthing never sees a half-written or temporary file. The temporary file is removed if the final rename fails.
- **Unregistered folder listing** (used by another surface): lists folders under the Projects tree, up to 3 levels deep, that are not projects, not inside a project and contain no project, skipping hidden directories. If the Projects root cannot be listed it raises (the caller shows "cannot tell").

## Config pass: the device and project picture
(source: collector.py `_run_config`)

- Runs every 120 s, and whenever nudged.
- Reads Syncthing's configuration and its own device id ("myID").
- If Syncthing reports an empty device id, the last known one is kept (logged as an error). If none is known yet (first pass), the pass does nothing and records the note "skipped: empty myID".
- Every device in Syncthing's configuration is recorded (device id, its name, whether it is the NAS itself). Each device is mapped to an editor account by its name, but only to an editor the dashboard positively knows; when the dashboard knows no editors at all yet (a fresh database), the mapping falls back to "any name shaped like a username".
- Every folder except the shared asset libraries is recorded as a project (slug, label, path). For each, the pass remembers which editor devices it is shared with (excluding the NAS) and its versioning settings (used later by the protection panel).
- **Project deactivation**: projects that are active in the database but no longer present as Syncthing folders are deactivated, subject to a mass-deactivation brake in the database layer. When the brake refuses, the pass logs "REFUSING to deactivate N of M active project(s)" and records the note "refused deactivating N project(s)".

## Enforce pass: making Syncthing shares match the ticks
(source: collector.py `_run_enforce`, `_enforce_loop`, `_run_enforce_and_groups`)

- Runs every 60 s, and whenever nudged (ticking a project nudges it, so a tick starts syncing within about 5 s).
- Skipped with the note "skipped: empty myID" if Syncthing reports no device id for itself.
- Only the list of devices of each folder is ever changed. Folder paths, labels and other settings are never touched by this pass.
- **One-time seed (first run on a fresh database)**: if ticks have never been seeded, every existing share of every project folder (not libraries) to a device whose name looks like a username becomes a tick for that editor, on the computer that device is known to be, or on the "unassigned" bucket if the computer is unknown; each such editor is recorded as known. The seed is marked done only if there was at least one folder and at least one username-shaped device in the snapshot; otherwise it logs "not marking selections as seeded ... retrying next cycle" and records the note "seed deferred: no mapped editor device in this snapshot". The seed can only add ticks, never remove a share.
- **Who counts as mapped**: a device whose name resolves to an editor the dashboard knows. A device with a username-shaped name that matches no known editor is treated as unmapped and its shares are left alone; this is logged once per device per process ("device ... has a username-shaped name that matches no editor account the dashboard knows -- treating it as UNMAPPED ...").
- **Desired share set for each project folder**:
  - always the NAS's own device;
  - every current share to a device that maps to no editor and is not claimed by any registered computer (left as is);
  - for each full tick of this project (or of any project that borrows a folder from this one, see "Cross-project folder links"), the Syncthing device of that exact computer, from the computer registry;
    - upload-only ticks are excluded entirely (the folder is not shared at all for them);
    - computers marked as wired / base rig are excluded, and editors who only have base rigs are excluded;
    - suspended editors are excluded;
    - an archived project contributes no ticks, neither its own nor through an archived borrower;
    - a computer whose reported device id has not been approved on the NAS yet is skipped and logged once ("... reports Syncthing device ..., which this server has not approved -- its shares CANNOT be made yet. Approve the pending device (Admin > Devices) and the next cycle will share its projects.");
  - for each editor with a full tick of this project, every device of that editor that no registered computer claims (the "by person" fallback for older companions). Logged once per (editor, device) per process ("device ... is being shared <editor>'s projects BY PERSON: no machine row claims it ...");
  - any current share to a device not present in the configuration snapshot at all (left as is);
  - any current share whose tick was changed in the last few seconds (the Undo window on the fleet page; its length is defined in the database layer) is kept, so an untick followed by Undo costs nothing. This delay applies to removals only, never additions.
- **Desired share set for each shared asset library**: the NAS plus every device of every known, non-suspended editor.
- **Blast-radius brake on removals**: removals are counted as (folder, device) pairs. Removals an admin caused on purpose do not count: those on an archived project, those of a suspended editor's devices, those backed by an audited untick within a window (length defined in the database layer), and pairs an admin approved by name from the refusal banner. If the remaining count exceeds the limit, those counted removals are held back for this pass while additions and authorised removals still apply.
  - Limit: the larger of `DASH_ENFORCE_MAX_REMOVALS` (default 3) and (a site setting "removals per computer", default 0) multiplied by the number of mapped editor devices.
  - On refusal: logs "REFUSING N share removal(s) in one enforce cycle (limit L) ... Additions still applied; raise DASH_ENFORCE_MAX_REMOVALS to override.", stores the refusal (pairs and limit) for the dashboard's banner, and records the note "refused N share removal(s)". A pass with no refusal clears any stored refusal.
  - An admin approval is spent as soon as any approved pair is applied (in a refused pass too).
- The computed plan (folder, desired, actual) is stored in the database before any change is sent to Syncthing, so the dashboard can show what is pending.
- **Applying**: each folder needing a change is re-read live from Syncthing and written back with the new device list. Devices found in the live folder that were not in the snapshot the plan was made from are kept (logged "folder ... has N device(s) that were not in this cycle's snapshot ... keeping them"). New devices are added with no introducer. Each applied folder is logged "enforced shares on <id>: +[...] -[...]".
- A folder Syncthing refuses does not stop the others. If any failed, the note becomes "applied A of B folder(s); syncthing refused the rest (<first error>)".
- After a successful write, the in-memory share picture is updated straight away so the end-of-cycle self-diagnosis does not raise a false "ticked but not shared" problem.
- **NAS group membership afterwards**: when per-project NAS access control is on (see "Per-project NAS groups"), the enforce pass then reconciles NAS group membership. Its failure is logged and never fails the enforce pass.

## Inventory pass: counting the video files on the NAS
(source: collector.py `_run_inventory`, `_nudge_first_walks`)

- Runs every 900 s. Needs the Projects tree. Only reads the disk.
- Fails with "DASH_PROJECTS_DIR does not exist" if the directory is missing, or "cannot read DASH_PROJECTS_DIR ..." if it cannot be listed.
- **Unmounted-tree guard**: if the Projects directory has zero entries, the pass skips everything, logs an error, and records the note "skipped: the Projects tree looks unmounted (0 entries)". No inventory is wiped.
- Considers active projects only. The project's location under the tree is taken from its Syncthing folder path (with the label as fallback).
- **Order and budget**: projects never walked before go first and are always walked, outside the budget. Every other project has a cheap directory signature computed every pass (a hash of every sub-directory's relative path and modification time). If unchanged since the last walk, the project is skipped. Changed projects are fully walked, at most `DASH_INVENTORY_PROJECTS_PER_CYCLE` (default 8, minimum 1) per pass; the rest wait, and the next pass starts with the first one left over (rotating cursor).
- **Bring-forward for new projects**: at the end of every cycle, if any active project has never been walked and has not been asked for within the last inventory interval, the inventory pass is nudged to run within seconds, walking only the never-walked projects.
- A full walk lists every file, keeps only video files (original or proxy), and records relative path, kind, lowercase extension, size and modification time.
- Problems recorded per project (the pass still succeeds):
  - "project dir missing on NAS" when the directory does not exist;
  - "project dir has no .stfolder marker and no media files - it looks unmounted, not empty" when a walk finds no video and no `.stfolder`.
- **Collapse brake**: the database layer refuses to replace a non-empty inventory with a walk that collapsed; the pass then keeps the previous inventory and logs "walked to N media file(s) from a non-empty inventory -- KEEPING the previous one".
- Notes recorded: "N project dir(s) unreadable", "kept N project inventory(ies): the walk collapsed", "N move(s) detected on the server", joined with "; ".
- File walks all happen before any database write, so a slow disk never holds the database lock.

## Hand-move detection: recognising moves made on the NAS by hand
(source: collector.py `_record_detected_moves`, `detect_moves`, `pair_across_cycles` and helpers)

- Runs at the end of every inventory pass, after the new inventories are stored. Never touches any file. A failure is logged and the inventory result stands.
- **What counts as a move**: a video file identified by (file name, size, modification time to the nanosecond) that vanished from exactly one path and appeared at exactly one other path, within or across projects. Paths are compared in normalised Unicode form (so a Mac's spelling matches), and the destination is recorded in the exact bytes the disk uses.
- **Refusals** (nothing recorded; the change stays a plain deletion and arrival):
  - a file that could not be measured (no size or time);
  - a key that vanished from two paths or appeared at two paths (ambiguous);
  - a file that only vanished (a deletion);
  - a file in a `Proxy` folder whose original did not move with it.
- **Folder moves**: when every file the previous walk saw under a folder moved to the matching path under one new folder, and nothing is left at the old folder, it is recorded as one folder move (with the file count). Both a folder moved under a different parent and a folder renamed in place qualify. A folder named `Proxy` is never recorded as a moved folder.
- **Proxies with their original**: files in `Proxy/` beside an original, with the same name stem, that moved to the `Proxy/` beside the original's new location, are carried on the original's move record (counted as "proxies moved"), not recorded separately.
- **Cross-pass moves**: because only a few projects are walked per pass, a vanish and its arrival may be seen in different passes. Unpaired single halves (not in `Proxy/`, not ambiguous) are kept in a pending table and paired on later passes. Rules:
  - a half whose file is, at the moment it is seen, also present elsewhere in the inventory is dropped (it is a copy, not a move); if that check fails the half is dropped too;
  - at pairing time the file must exist only at the destination now (no third copy), else the pair is refused and both halves are discarded;
  - the vanish must have been seen before or in the same pass as the arrival; otherwise neither half is used (the stale arrival ages out on its own, after a period set in the database layer);
  - a file that came back to the path it left cancels both halves;
  - cross-pass moves are always single-file moves, never folder moves;
  - at most 1000 unpaired halves are kept per pass; above that, none from that pass are kept (logged "N unpairable move halves in one pass, keeping none of them").
- **Cap per pass**: at most 500 moves are recorded per pass. Above that, the first 500 (sorted by source project and path) are recorded and the rest discarded, a "moves dropped" notice is written, and it is logged ("recording the first 500 and DISCARDING N"). Halves of cross-pass moves dropped by the cap are kept for a later pass.
- **Repeat suppression**: a move identical to one recorded within the last 1 day is not recorded again.
- **What is recorded**: a file-move record in the "done" state (the server-side rename has already happened), source "detected", actor "detected on the server", with the computers that hold the source file as targets. Those computers then follow it through the normal file-move machinery (outside this part): each moves its own copy and relinks Resolve.
- **Notice**: each recorded move opens an info notice `file_move_detected` (subject: destination project and path): "N file(s) were moved on the server, by hand, from <old>. K computer(s) are following: each moves its own copy and relinks Resolve, so nothing re-uploads the old path." Fix: "Nothing to do; the computers follow on their own. If this was not a move, open the project page's MOVES history."
- **"Checked" stamps**: the "file move detected" check is stamped as checked only when every project in the pass was read and no inventory was refused; otherwise the old stamp is left to go stale. The "moves dropped" check is stamped on every pass.

## Connections pass
(source: collector.py `_run_connections`)

- Runs every 15 s, and whenever nudged.
- Reads Syncthing's live connections and records, for every connected device, that it is connected and from which address; the full set replaces the previous one (what "online" means is decided outside this part).

## Completion pass: how far each editor computer is in sync
(source: collector.py `_run_completion`, `_ingest_item_finished`)

- Runs every 60 s, and whenever nudged.
- For every project folder: reads Syncthing's folder status (state, error text, total files and bytes, and the folder's own outstanding items and bytes, i.e. what editors are still pushing to the NAS). Then for every editor device the folder is shared with, reads the completion percentage, outstanding items, bytes and deletions.
- Each request has a timeout of 3 s (or the Syncthing client's own timeout if shorter).
- **Time budget**: the pass stops starting new folders after `DASH_COMPLETION_BUDGET_SECONDS` (default 30 s; 0 means no budget), only at a folder boundary, logs "completion: N s budget spent after X of Y folder(s); the rest run next cycle", records the note "partial: N folder(s) left for the next cycle", and the next pass starts with the folders left over.
- A folder or device whose request fails is skipped and logged; a reply without a completion figure is skipped (never recorded as 0%).
- Records per folder: Syncthing state and error (so a stopped or broken folder shows), and the folder's own outstanding items/bytes (shown on the transfers page).
- Records per (folder, device): completion %, outstanding items, bytes, deletions, and the folder's global file count and size. A pair at 100% with nothing outstanding has its missing-file list cleared.
- Completion rows for (project, device) pairs that are no longer shared are deleted, but only when the current share picture is non-empty.
- Keeps an in-memory list of incomplete pairs (used by the remoteneed pass). Pairs of folders not reached this pass keep their last known value.
- **Uploads finished on the server**: reads Syncthing's event stream from the last event id seen (stored in the database). If Syncthing restarted (its newest event id is lower than the stored one), it starts from 0. Every successful "file updated" finish event for a known project is added to the transfer history as an upload on lane C named `Projects/<label>/<file>`, attributed to the folder's single sharing editor when there is exactly one, otherwise to nobody. The last event id is stored. Any failure here is silent (debug log) and never fails the pass.

## Remoteneed pass: which files each computer is still missing
(source: collector.py `_run_remoteneed`)

- Runs every 60 s.
- For each (folder, device) pair the last completion pass found incomplete, reads the list of files that device still needs, 200 per page, at most 3 pages (600 files). Each file has a name and, when given, a size.
- Stores the list per (project, device), marked as truncated when the outstanding count is larger than the number of names fetched.
- A failing pair is logged and skipped; others continue.

## Prune pass: retention
(source: collector.py `_run_prune`)

- Runs every 3600 s, with or without Syncthing.
- Runs the database retention sweep (tables and periods are defined in the database layer, outside this part). The sweep also expires fleet job leases; it is told whether this container has a job executor (so a job that runs out of retries is pinned to the dashboard's own worker when there is one, abandoned otherwise) and the job cooldown `DASH_JOBS_COOLDOWN_SECONDS` (default 120 s).
- Then deletes expired login sessions through the session store, when one was provided. A failure there is logged and does not fail the pass.

## Invariants pass and the protection panel's evaluation
(source: collector.py `_run_invariants`)

- Runs every 900 s, with or without Syncthing.
- Asks the NAS once per pass for its snapshot schedule (memoised for the pass) and runs the cross-component invariant checks (outside this part) with it and with the current share picture ("not checked" until a config pass has completed in this process).
- Then runs the protection panel evaluation (see "Protection panel"), with the same NAS answer and the folders' versioning settings ("not checked" until a config pass has completed). A failure of the protection evaluation is logged and adds "protection pass failed" to the note.

## Alerts pass
(source: collector.py `_run_alerts`)

- Runs every 600 s, with or without Syncthing, last in the cycle.
- Runs the alert evaluation and delivery (outside this part), handing it the number of watchdog loop restarts not yet reported, and returns its note (for example the number of open problems) to the health panel.

## Cross-project folder links (a project borrowing a folder from another)
(source: links.py, collector.py `_run_links`, `_retarget_link`)

- A project's marker may carry an `includes` list. Each entry is either a string path or an object with a string `path`. It declares that this project (the "borrower") borrows a folder that lives inside another project (the "lender"). Any computer with a full tick of the borrower receives the lender's whole Syncthing folder (see the enforce pass); limiting what is pulled is the companion's job.
- Resolved on every provision pass for every scanned project with exactly one directory (a duplicated slug is skipped). The marker on disk is the truth; the stored link rows are a cache replaced each pass. A borrower with no `includes` gets its rows cleared. Rows of a borrower that vanished from the scan are left alone; rows of borrower projects that no longer exist in the database at all are deleted.
- Entries with no usable path are skipped and logged; a non-list `includes` counts as one bad entry.
- At most 128 entries are read; the rest are dropped unread (logged).
- Paths are normalised (Unicode NFC, forward slashes, trimmed, no trailing slash). Duplicates, and entries inside another entry of the same marker, are dropped (logged).
- At most 32 links per marker; past that, one "invalid" row says "too many includes (limit 32); N ignored" and the rest are not processed.
- Statuses: `ok`, `missing`, `invalid`, `lender-inactive`. Refusals (status invalid), with their exact detail text:
  - "empty path";
  - "absolute paths cannot be shared; declare a tree-relative Projects/ path";
  - a segment empty or "." or "..": "empty or dot path segment"; starting with ".": "segment ... starts with '.'"; a control character: "control character in path"; containing ":": "segment ... contains ':' (declare a tree-relative path, not a drive path)"; over 255 bytes: "path segment over 255 bytes";
  - not starting with `Projects/`: "only folders inside a project can be shared (the path must start with Projects/)";
  - fewer than three segments, or the path is itself a project: "that is a whole project; tick both projects instead";
  - any segment named `Proxy` (any case): "cannot share a Proxy folder; share its parent instead";
  - not inside any marked project: "not inside a project";
  - inside the borrower itself: "that folder is inside this project already";
  - lender marker unreadable: "the lending project's marker is unreadable";
  - the folder contains a project: "contains a project (<rel>)";
  - the resolved real path leaves the Projects tree (symbolic link): "path escapes the Projects tree".
- `missing`: the folder does not exist ("folder not found on the server") or cannot be read ("folder could not be read on the server"). A missing link still names its lender.
- `lender-inactive`: an ok or missing link whose lender project is unknown or inactive in the dashboard ("the lending project is not active on the dashboard").
- **Lender moved**: when a link no longer resolves but its previous row named a lender and a sub-folder, and that lender is active, it is re-resolved through the lender's current location; if that lands on the same lender, the link stays ok with the detail "declared path is stale; the folder moved to Projects/<new>. Update the declaration when convenient." The marker itself is never rewritten.
- Each borrower's rows are committed separately; a failure for one borrower is logged and the pass is failed at the end ("N borrower(s) failed link resolution").

## File locate: where else on the NAS is a file with this name and size
(source: locate.py)

- Answers, for up to a list of (file name, size) pairs, every place on the NAS a video file with that name and size sits, from the inventory table only (no disk access). Used by a companion that sees files vanish to ask whether they were moved (the HTTP route that calls it is outside this part).
- The intended maximum is 2000 files per request (a constant; the route enforces it, not this function).
- Names are compared after Unicode normalisation and taking only the base name; the paths returned are exactly as stored.
- Only active projects count, and a project whose last inventory walk recorded an error is excluded entirely (its old rows are not used).
- Answer fields: `walked` (false when the inventory has never produced any row; the caller must treat "not found" as "not known"); `as_of` (the oldest walk time among the projects that contributed a match, or, with no match, the newest walk time in the whole inventory); `unreadable` (the slugs of active projects whose inventory has an error); `files` (each asked name and size with every `found` project slug and path). Ambiguity is not resolved: all matches are returned.

## Admin assignments page (who syncs which project)
(source: assignments.py)

- **Route** `GET /admin/assignments` (admin session only; a non-admin is refused by the shared admin-page guard). Query parameters: `editor`, `machine`.
- The page has no write route of its own. Every tick in the grid is sent by the browser to the existing per-editor tick routes (outside this part), so a tick here is exactly the editor's own tick.
- **Pickers**: first a person picker (every known editor account), then a computer picker for that person. The grid shows only when both are answered.
  - When there is exactly one known editor and no `editor` was given, that editor is preselected.
  - An `editor` that is not a known editor is treated as not chosen.
  - Computer options: that person's registered computers, oldest first; a person with no computer gets one option "no computer yet". The "unassigned" bucket is never offered beside real computers.
  - The value `*` means "every computer of this person" (all their columns).
  - A `machine` that is not one of the chosen person's computers (and not `*`) is treated as not chosen. When the person has exactly one option it is preselected.
  - The page also carries every person's computer options up front (so the select can be filled in the browser) and the total number of registered computers in the fleet.
- **Grid**: rows are active projects sorted by label; columns are computers (one per registered computer of each known editor; a person with none gets one column labelled with the name and "no computer yet"). Each column of a person with several computers lists the person's other computers (to copy a plan from; the action itself is elsewhere).
- Each cell shows ticked or not, and whether the tick is upload-only.
- Shown alongside: each editor's worst presence status across their computers (green / amber / red, empty if never reported), which editors have only base-rig computers (their columns are read-only) and which individual computers are base rigs (read-only cells), each project's proxy size on the NAS and each computer's free disk (so the browser can warn about capacity before a tick; a never-walked project is absent, meaning "cannot say"), the archived projects (with a flag when the list could not be read because the database was busy, rather than claiming nothing is archived), and how many distinct editors tick each project (for the archive confirmation).
- Projects are listed regardless of the picker; only the columns are narrowed.

## Per-project NAS groups (per-project access control on the NAS)
(source: project_groups.py; called from the enforce pass and from project creation)

- Switched on by `DASH_PROJECT_ACL=per-project` (default `shared`, which makes all of this inert). `DASH_NAS_PROJECTS_ROOT` (NAS-side path of the Projects tree, default blank) is needed for closing new project directories.
- **Group name per project**: `proj-<slug>`; when that exceeds 32 characters, it is cut to 25 characters (trailing "-" removed) plus "-" plus the first 6 hex characters of the SHA-256 of the slug. Slugs must start with a letter or digit and contain only a-z, 0-9 and "-"; others are skipped.
- **Membership sources**: an editor should be in the group of every non-archived project they have ticked (on any of their computers, full or upload-only), plus every project an admin explicitly granted them. Grants are the only way in for wired (base-rig) editors, whose ticks are refused elsewhere. Grants are stored per project as a list of editors; grant and revoke report whether anything changed. (The HTTP routes that call grant and revoke are outside this part.)
- **Reconcile** (after every enforce pass when on): reads the NAS's existing groups, creates any project group needed that does not exist, then for each known editor sets their memberships so that they are in exactly the wanted project groups among the groups this feature manages for them. "Managed" means groups this dashboard previously added (a ledger it keeps) or is about to add. A membership made by hand or by the server script is never removed. Logs "project groups for <editor>: +[...] -[...]". A failure for one editor is logged and counted; the reconcile never raises.
- When the NAS backend lacks the capability (Synology lacks the group index and membership operations, see NAS back-ends), a warning is logged once per process ("project_acl is per-project but this NAS backend cannot manage project groups ...") and nothing is done.
- Nothing happens when no NAS is configured.
- **Closing a new project directory**: right after the dashboard creates a project, when per-project is on and the NAS projects root is set and the NAS backend can do it, the directory `<root>/<rel>` is made private to its project group (on TrueNAS: owner unchanged, group `proj-<slug>`, mode 2770). Failure is logged ("could not make Projects/<rel> private to its project group") and never stops the creation.

## Protection panel: what is backed up, and what only looks protected
(source: protection.py; evaluated by the invariants pass every 900 s)

- Each line has a state: PROTECTED (ok), MISSING (broken), CANNOT VERIFY (not checked), COULD NOT RUN (the check itself raised). A line is green only on positive evidence; "could not ask" is never shown as green.
- **NAS read**: once per pass the dashboard asks the NAS for its periodic snapshot tasks. Unconfigured NAS, unreachable NAS, a Synology NAS (no such interface) or an unexpected answer all mean "could not ask". The panel and the invariant checks share the same answer.
- **Lines, in display order** (title; when each state is shown; the fix text is shown with any non-green line):
  1. "the project tree is on a snapshot schedule". Synology: always CANNOT VERIFY with "cannot verify, confirm in DSM: this Synology's snapshot schedules are in the Snapshot Replication package, which this server has no way to read. Open DSM, Snapshot Replication, and check the schedule yourself." TrueNAS: CANNOT VERIFY when the NAS could not be asked, or when `DASH_TREE_DATASET` is not set ("this server has not been told which dataset the project tree is on ... Set DASH_TREE_DATASET on the dashboard container."); MISSING when no enabled snapshot task covers that dataset (a task covers it when it names the dataset exactly, or names a parent and is recursive); PROTECTED otherwise ("N enabled snapshot task(s) cover <dataset>"). Fix: add an enabled periodic snapshot task under Data Protection, or run `server/setup_snapshots.py`.
  2. "this dashboard's own data is on a snapshot schedule". Same rules, with the dataset from `DASH_UPDATE_SNAPSHOT_DATASET`. Fix: make the data folder a dataset, add a snapshot task (`server/setup_snapshots.py --apps-root`), and set the variable.
  3. "a snapshot was actually taken in the last day". Synology: CANNOT VERIFY. TrueNAS: CANNOT VERIFY when the NAS could not be asked; MISSING when no task is enabled ("N snapshot task(s), none enabled"); CANNOT VERIFY when no enabled task reports a last-run time; MISSING when the newest last run is older than 25 hours ("newest snapshot N h old, over the 25 h limit"); PROTECTED otherwise. A disabled task is treated as absent.
  4. "this server only accepts CC Sync builds we signed": MISSING when `DASH_RELEASE_PUBKEYS` is empty; otherwise PROTECTED with only the number of keys shown (never the keys).
  5. "the release signing key has been backed up": CANNOT VERIFY when no release key is configured; PROTECTED on a vendor-build dashboard whose every configured key is the vendor's ("the vendor holds the update signing key; there is nothing for you to back up"); MISSING when no admin has recorded a backup date; PROTECTED with the recorded date otherwise.
  6. "somebody has actually restored from a backup this year": MISSING when no restore date has been recorded, or when the recorded date is over 365 days old; PROTECTED otherwise.
  7. "files deleted on the server are kept for a year": CANNOT VERIFY until a config pass has read the folder list in this process, or when there are no project folders; MISSING for each project folder with no versioning type or a maximum age of 0 ("files deleted on the server for this project are not kept anywhere"); PROTECTED otherwise, showing the shortest kept age in days. Fix: untick and re-tick the project, or set staggered File Versioning in Syncthing.
  8. "deleted-file copies on editors' computers are within their limit" (warn severity): reads each computer's reported trash size; CANNOT VERIFY when none has reported (companion 0.9.55 and newer report it); MISSING for each computer over 50 GB; PROTECTED otherwise, stating that the 14-day half of the rule is not checked.
  9. "somebody is told when this server finds a problem": PROTECTED only when an alert channel is set and something was delivered through it within the alerts module's evidence window; MISSING otherwise ("nobody is told when something breaks here" when no channel is set). The consequence text quotes the number of alert checks (falls back to 40 if they cannot be counted). Fix: choose mail or a webhook on Settings, Alerts, and press "Send a test".
- **Notices**: each MISSING subject opens a `protection_missing` notice (severity error, or warn for line 8) with subject "<line key>: <subject>"; each CANNOT VERIFY or COULD NOT RUN line opens a `protection_unverifiable` warn notice. Notices for lines that are no longer in that state close themselves.
- **Carry-over rule**: a line that was MISSING and on this pass could not be checked at all stays MISSING (marked as carried, its detail extended with "(last seen <date>; this pass could not check it again: <reason>)"); its notice is held open, not refiled. Only a real verdict replaces it.
- **Admin acknowledgements**: two dates an admin can record: "release key backed up" and "restore drill". The date must be readable as YYYY-MM-DD ("that is not a date this server can read. Use YYYY-MM-DD.") and not later than tomorrow in UTC ("that date is in the future."). A blank date means today. The admin's name and the time are stored with it. Recording one immediately re-evaluates that single line and files or closes its notices, so the panel agrees with the button at once. (The HTTP routes and buttons, "I have backed it up" and "Record a restore", are outside this part.) The recovery tools record a restore drill through the same store.
- **Panel view**: every line is always listed; a line no pass has evaluated yet shows CANNOT VERIFY "no protection pass has run yet on this server". Shows the counts per state and the last pass time. The release-key acknowledgement row is hidden on a vendor-build dashboard whose keys are all the vendor's.
- **Weekly report block**: "WHAT IS PROTECTED (X of 9 confirmed, Y missing, Z unverifiable)", then each line as "<STATE>: <title>", its detail, its subjects and, if not green, "WHAT TO DO: <fix>"; plus "(no protection pass has run on this server yet)" when applicable. Read from the last stored pass, never evaluated on the spot.
- Pass note on the collector panel: "N safety mechanism(s) missing", "N protection check(s) could not run", "N unverifiable here".

## Recovery tools: snapshot restore, restore rehearsal and the guided runbook
(source: recovery.py; the page and its routes are outside this part, this lists what the operations do)

- **Configuration** (environment variables on the dashboard container):
  - `DASH_SNAPSHOT_DIR`: a read-only mount of a directory whose entries are snapshots (on TrueNAS the dataset's `.zfs/snapshot`, on Synology `/volume<N>/@sharesnap/<share>`). Unset means "this server cannot see snapshots", never "there are none".
  - `DASH_SNAPSHOT_PROJECTS_SUBPATH`: the path from one snapshot's root to the Projects tree inside it (blank means the snapshot root is the Projects tree).
  - `DASH_CONTAINER_NAME`: the dashboard container's name, used only to fill in printed commands.
  - `DASH_TREE_DATASET` and `DASH_UPDATE_SNAPSHOT_DATASET` (shared with the protection panel).
- **Listing snapshots**: one directory listing of the snapshot mount, newest first (by name descending, then modification time). When none can be listed, a reason sentence is always given instead:
  - not set: "this deployment was never given a snapshot mount, so this server cannot read any snapshot (DASH_SNAPSHOT_DIR is not set on the dashboard container). Re-run the deploy, or mount the NAS's snapshots into the container read-only and set DASH_SNAPSHOT_DIR to that path."
  - not a readable directory, or a read error ("The snapshot mount may be gone.");
  - empty: "there are no snapshots under <dir>. Either none has been taken yet, or that mount points somewhere else."
- **Preview of a project restore** (read-only): for a chosen project and snapshot, compares the snapshot's copy of the project folder (looked up by the project's current label) with the live folder, file by file by relative path and size, skipping dot-files and dot-directories. Reports files missing now (count, bytes, up to 300 listed), files present but with a different size (count, bytes, up to 300 listed), unchanged count, and files added since (count, up to 300 listed).
  - If either walk exceeds 50,000 files, no counts are given (all zero, `counts_unavailable`), with the note "That <snapshot|project> folder holds more than 50000 files, more than this server compares in one go ... Restore the folder with the commands on the recovery page instead: a restore this large is a transfer, not a click."
  - Otherwise the note says "Nothing here is overwritten. Whatever you restore is copied into a new .restored folder at the top of the Projects folder on the server, under the project's own name, and the files that are there now are left exactly as they are." It is prefixed, when this snapshot was already restored for this project, with "This snapshot was already restored on <date> UTC: N file(s) went into <where> on the server. [It has been restored N times from this snapshot.] Those copies are there, not in the project, so the same files still count as missing below ... Restoring again makes another full copy."
- **Restore into quarantine**: copies the files missing from the live project (and, when the "also bring back the ones that are there but different" option is chosen, files whose size differs) out of the snapshot into `<Projects tree>/.restored-<YYYYMMDDTHHMMSS>/<project label>/`, at the same relative paths. The leading dot keeps it from being discovered as a second project; it is outside every Syncthing folder so it is not sent to any editor.
  - Nothing existing is overwritten, deleted or re-owned. File timestamps are preserved.
  - Before copying, a NAS snapshot named for `restore-<slug>` is attempted (best effort; failure is logged and the restore continues). Its outcome is reported.
  - A file that fails to copy is counted and named (first 20 shown) and the rest continue.
  - Records the restore (time, actor, project, snapshot, file count, bytes, location, failures) in a history of the last 20, writes an audit record `recovery.restore`, and logs "recovery: <actor> restored N file(s) from <snapshot> into <where>".
  - Refusals (with HTTP status for the route):
    - project unknown: "there is no project called ... on this server" (404);
    - project has no recorded folder (409);
    - Projects tree not mounted: "... (DASH_PROJECTS_DIR), so this server cannot restore anything into it ..." (409);
    - live project folder missing: "there is no folder for <label> on the server to restore into ..." (409);
    - snapshot mount not configured (409); snapshot name empty or containing a slash, backslash, "." or ".." ("... is not a snapshot name this server will accept", 400); snapshot not found or escaping the mount ("there is no snapshot called ... on this NAS", 404); snapshot unreadable (502);
    - the snapshot has no folder for the project: "Either the project did not exist yet when it was taken, or its folder has been renamed since" (404);
    - a path escaping the project folder (400);
    - either walk over 50,000 files (409);
    - nothing missing but some files differ and the option was not chosen: "... N file(s) are there with different contents. Tick 'also bring back the ones that are there but different' ..." (409);
    - nothing to restore (409);
    - more than 20,000 files to copy (409);
    - the quarantine folder already exists: "A restore never writes into a folder that is already there: rename or delete it first." (409);
    - the quarantine folder cannot be created (read-only tree, full pool): "... Nothing was changed." (502).
- **Restore rehearsal ("drill")**: takes the newest snapshot (or a named one), finds the first file (in sorted walk order, skipping dot entries) between 1 byte and 64 MB, copies it into `<data dir>/restore-drills/<timestamp>/`, compares size and SHA-256 with the original, and deletes the scratch copy. Any scratch directories left by an interrupted earlier drill are deleted first.
  - On a byte-identical result, records today as the restore drill date on the protection panel (so that line turns green). A failed comparison records nothing on the panel.
  - Always records the drill in a history of the last 20 and an audit record `recovery.drill`. Result text: "restored one file out of this snapshot and it came back byte for byte" or "the file that came back is NOT the file in the snapshot".
  - Refusals: no snapshots visible ("this server cannot rehearse a restore: <reason>", 409); the snapshot holds no Projects tree at the configured sub-path (409); no file small enough ("under 64 MB", 409); a copy error (502).
- **Facts the runbook gathers** (each shown with its value, whether it is verified, why not, and how to fix it):
  - "which kind of NAS this is": verified when the NAS answers a ping (and, where supported, its system info) and a NAS kind is configured. The value shown is the configured kind (TrueNAS or Synology DSM). Not verified when no NAS credential is configured, the NAS does not answer, or no kind is configured.
  - "the project tree" dataset (`DASH_TREE_DATASET`) and "this dashboard's own data" dataset (`DASH_UPDATE_SNAPSHOT_DATASET`): verified only when the NAS's own snapshot task list names it or a recursive parent of it. Never verified on Synology. Fix text points to the SETUP page's "Protect your data" task.
  - "the storage pool the footage is on": the first path component of the verified tree dataset.
  - "where this dashboard reads the project tree": verified when `DASH_PROJECTS_DIR` is mounted.
  - "snapshots this dashboard can read for itself": verified when at least one snapshot is listed ("N snapshot(s), newest <name>").
  - "what this dashboard's container is called": verified when `DASH_CONTAINER_NAME` is set.
- **Runbook rule**: a printed command block that needs a fact which is not verified is replaced by a refusal, "<title>: this server will not print these commands", naming each missing fact, why, and its fix, and pointing to doing it by hand with someone who can check the NAS. Verified facts are substituted into the commands.
- **The five problems a person can choose, and their steps**:
  1. "Something on the server was deleted, overwritten or changed by mistake" ("One project, one folder or one file. The usual one."):
     - action "Restore it here, into a new folder beside the projects" (link to the restore section);
     - note "Look in the deleted-files folder first, if it was recent" (the `.stversions` folder inside the project);
     - only when this server cannot read snapshots: command block "Restore it over SSH instead" needing platform and tree dataset: list `/mnt/<dataset>/.zfs/snapshot/`, `cp -a` one file from a snapshot back into the project, `chown broll:editors` on it.
  2. "CC Sync changed clip paths in somebody's Resolve project and they are wrong":
     - action "Undo it from here" (in-page link to the "UNDO A CLIP-PATH CHANGE" panel; the change is undone when that computer next reports with the project open; or "Undo last fix" in the tray's Settings);
     - note "If the undo cannot help" (the exported project copy under `.ccsync/resolve_edits` on that computer).
  3. "This dashboard has lost projects, editors or their ticks":
     - action "Put back one of this dashboard's own backups" (link to the dashboard-update section of the packages page);
     - note "What a restore of this database costs" (ticks made since the backup must be redone);
     - command block "Restore it from a NAS snapshot instead" needing platform, apps dataset and container name: `docker stop`, `cp -a` the snapshot's `ccsync-dashboard/data/dashboard.db` over the live one, `chown 3000:3000`, `docker start`.
  4. "The b-roll or music search is empty or wrong":
     - notes on the previous index kept as `.prev-<timestamp>` and who can roll it back;
     - command (always printed): `cd server` then `python publish_db.py --which broll --rollback --apply`, on the computer that publishes the index.
  5. "Everything on the server is wrong since a particular moment" ("The last resort, and the only one here that destroys anything."):
     - action "Stop the fleet writing first" (link to "Stop all syncing" on Settings, Users);
     - note "This is the one that cannot be undone";
     - command block "Roll the project tree back" needing platform and tree dataset: `zfs list -t snapshot -r <dataset>` and `zfs rollback -r <dataset>@<SNAPSHOT>`;
     - notes "Afterwards: put back anything the rollback undid" (recreate lost projects through `/project-setup?resolve_project=<name>` and "Create & link") and "Then watch the first pass" (on SYNC STATUS).
  - An unknown problem key gives a single refusal step "there is no recovery here for <key>".
- **Page data**: facts, the five problems, the chosen plan, the snapshot list or why there is none, active projects (for the restore picker), the protection panel, and the last 20 restores and drills. Gathering never fails the page: a fact-gathering error gives an empty fact list.

## Talking to Syncthing (every operation the dashboard performs on the NAS's Syncthing)
(source: syncthing_client.py)

- Configured by `SYNCTHING_GUI_URL` (trailing slash removed; blank means "no Syncthing", see the cycle rules) and `SYNCTHING_API_KEY`. Every request carries the key in the `X-API-Key` header.
- Default timeout 10 s per request; the completion pass uses 3 s per call.
- **Redirects are never followed.** Any 3xx answer is refused with "HTTP <code> redirecting to <location>. Nothing was sent on. Point SYNCTHING_GUI_URL at the address Syncthing's API serves". Any other status of 300 or above, a network error, or a non-JSON body is an error.
- Folder and device ids are percent-encoded when they go into a URL path.
- Operations used:
  - ping (`/rest/system/ping`), system status including the NAS's own device id (`/rest/system/status`), full configuration (`/rest/config`), pending devices (`/rest/cluster/pending/devices`), live connections (`/rest/system/connections`), global options read and change (`/rest/config/options`), events (`/rest/events`, non-blocking, `ItemFinished` by default, up to 200), folder status (`/rest/db/status`), per-device completion (`/rest/db/completion`), files a device still needs (`/rest/db/remoteneed`, paged), add a folder, read one folder, replace one folder, read and set a folder's ignore list.
  - **Approve a device** (used by the device-approval route, outside this part): if the device is unknown, adds it with the given name, the configured address list and introducer off; if known with a different name, renames it. Never touches any folder's share list.
  - **Address list for new devices**: when `DASH_SYNCTHING_TAILNET_IP` is set, `tcp://<ip>:22000`, `quic://<ip>:22000`, then `dynamic`; otherwise just `dynamic` (global discovery).
  - **Remove a device** (used by deleting a user or forgetting a computer, outside this part): removes the device from every folder that shares with it (each folder re-read live and written back), then deletes the device record. Returns which folders it was removed from. A device Syncthing does not have is "not removed", not an error. If Syncthing cannot be asked, it raises so the caller can abort.
- **Tailnet-only options** (UNREACHABLE: nothing in the dashboard calls it; the setting `DASH_SYNCTHING_TAILNET_ONLY` is read into the settings but no code applies it): would set `relaysEnabled` false, `globalAnnounceEnabled` false, `natEnabled` false, `localAnnounceEnabled` true. When called with "off" it only logs what it would change ("tailnet-only options NOT applied (opt-in, currently off). Would set ...").

## Syncthing admin page login guard
(source: syncthing_gui_guard.py; ticked from the start of every collector cycle)

- Purpose: make sure Syncthing's own web admin page on the NAS requires a login.
- On by default; `DASH_SYNCTHING_GUI_SECURE=0` turns it off. Also inert when no Syncthing URL is configured.
- **Schedule**: rate limited to one attempt every 120 s while it has not succeeded; once the page is found protected or has been secured, re-checked every 3600 s.
- **What it does**: reads Syncthing's GUI configuration.
  - If it cannot be read, or does not look like a real GUI configuration (no `address` or `enabled` key), the result is "unknown" (never "unprotected") and nothing is changed.
  - If a user and password are set and "insecure admin access" is off: "protected", nothing changed.
  - If a user and password are set but "insecure admin access" is on: only that flag is turned off and the existing login is kept (logged "insecureAdminAccess turned off; the existing login (user ...) was kept").
  - If no login is set: uses a stored password from `<data dir>/secrets/syncthing_gui_password`, or generates a 28-character random password (letters and digits) and stores it there first (owner-only file permissions). Sets the user to the existing user name or `ccsync-admin`, sets the password, turns "insecure admin access" off (logged "a login (user ...) was set; the password is in <path>").
  - Statuses: disabled, unknown, protected, secured, failed (storing the password failed, or Syncthing refused the change). Never raises.
- The API key keeps working after a login is set, so nothing else is affected.
- The setup wizard (outside this part) also uses the "is it protected" check and the same "ensure" action.

## Internal SFTP identity routes (for the SFTP sidecar container)
(source: internal_sftp.py)

- Two routes, not behind the login session, meant for the separate SFTP server container that serves lanes A and B. Both need `Authorization: Bearer <token>`.
- Token: `CCSYNC_INTERNAL_TOKEN` if set; otherwise the first non-empty file of `<data dir>/secrets/ccsync_internal_token` or `<data dir>/secrets/internal_token`, re-read on every request (so a rotated token works without a restart).
- Refusals: no token configured anywhere: 503 "internal token not configured". Missing or wrong token: 401 "bad or missing bearer token", logged with the method, path and caller address. Comparison is constant-time.
- `GET /internal/sftp/users`: every local dashboard account that is not disabled, has role admin or editor, and has at least one SSH key, as `{"users": [{"username", "uid", "gid"}]}`. Every user gets the same uid and gid: `APP_UID` and `APP_GID` when both are set and numeric; otherwise this process's own ids (on Windows, which has none, 3000 and 3001). Half a pair, or non-numeric values, are ignored with a logged warning.
- `GET /internal/sftp/keys/<username>`: the user's authorized SSH keys as plain text, one per line, with no restriction prefix added. The name is trimmed and lower-cased. 404 "unknown or disabled user" for an unknown or disabled account.

## SFTP transfer limits for a Synology NAS
(source: sftp_transport.py; used by the site settings and the published site manifest, outside this part)

- Applies only when the NAS kind is `synology` and the dashboard is not a vendor build (the vendor appliance's own SFTP server does not have the limitation). Elsewhere the stored values pass through unchanged.
- Safe limits: chunk size 64Ki (65,536 bytes), concurrency 16.
- **Problem text** for an admin: "sftp_chunk_size '<x>' is not a size (use "64Ki")"; "sftp_chunk_size '<x>' is above 64Ki: this NAS's sshd silently cuts downloads over 514 MiB short at that size"; "sftp_concurrency N is above 16". Empty when safe.
- **What is published to companions**: a blank, unreadable or too-large chunk size becomes 64Ki; a concurrency of 0 or less, or above 16, becomes 16.
- Size syntax accepted: a number with an optional k, m, g or t (powers of 1024) and optional "i" and "b", case-insensitive.

## Choosing and configuring the NAS back-end
(source: nas/factory.py, nas/base.py, nas/__init__.py, truenas_client.py)

- `DASH_NAS_KIND`: `truenas` (default) or `synology`. Any other value is refused with "unknown DASH_NAS_KIND '<x>': allowed values: truenas, synology"; it never falls back to TrueNAS.
- Connection settings (the newer name wins; the older `TRUENAS_*` spelling is still read): `DASH_NAS_HOST` / `TRUENAS_HOST`, `DASH_NAS_USER` / `TRUENAS_USER`, `DASH_NAS_PW` / `TRUENAS_PW`, `DASH_NAS_API_KEY` / `TRUENAS_API_KEY` (TrueNAS only), `DASH_NAS_API_KEY_USER` / `TRUENAS_API_KEY_USER` (TrueNAS only), `DASH_NAS_VERIFY_SSL` / `TRUENAS_VERIFY_SSL`, `DASH_NAS_HOMES_PARENT` (TrueNAS only).
- **"NAS configured"** (the switch that enables every NAS-backed feature; without it those features are simply unavailable and everything else works): a host is set, and a password is set, or on TrueNAS an API key is set.
- **TLS verification setting** (both back-ends): unset means "record the NAS's certificate fingerprint on first use, refuse any other afterwards"; `0`/`false`/`no` turns verification off; `1`/`true`/`yes` verifies against the system certificate authorities; a value starting with `sha256:` followed by 64 hex digits (colons and spaces ignored) accepts exactly that certificate; any other value is a path to a certificate-authority bundle. A malformed `sha256:` value is an error at start-up of the client, never treated as "off".
- **First-use certificate record**: stored in `<data dir>/secrets/nas_cert_pins.json` (owner-only), keyed by host and port. The first connection reads the certificate (4 s timeout) and records it, logging "recorded the NAS certificate for <host:port> on first use: sha256:... A different certificate is refused from now on; to accept a replaced one, remove that entry from <file>". If the NAS cannot be reached to read the certificate, it falls back to "verify against the system certificate authorities" (which fails closed against a self-signed certificate) and does not try again for 60 s. Removing the record is a deliberate admin act (a helper exists; nothing calls it automatically).
- **Shared rules for both back-ends**:
  - The fleet group is named `editors` on both.
  - Valid usernames: start with a lowercase letter, then up to 31 of lowercase letters, digits, ".", "_", "-".
  - A text counts as an SSH public key when its first word is one of `ssh-ed25519`, `ssh-rsa`, `ssh-dss`, `ecdsa-sha2-nistp256`, `ecdsa-sha2-nistp384`, `ecdsa-sha2-nistp521`.
  - Every back-end answers: ping, find a group, ensure the `editors` group exists, find a user, list editors, is a user an editor, create or update an editor (with SSH key and optional full name), set a known password, delete an editor.
  - Optional abilities are looked up by name; "absent" means "this NAS cannot be asked", never "no".
  - Refusals both carry: never modify, set the password of, or delete a system or built-in account, or an existing account that is not already in `editors`.
  - Redirects from the NAS are never followed (refused with "... Nothing was sent on. Point DASH_NAS_BASE_URL ..." on TrueNAS, "... Point DASH_NAS_HOST / DASH_NAS_PORT ..." on Synology).
  - A non-JSON success answer is turned into an error message rather than a crash.
- `truenas_client` is a leftover import alias for the TrueNAS back-end, kept "for one release"; nothing in the dashboard imports it any more.

## TrueNAS back-end: every operation
(source: nas/truenas.py)

- **Authentication**: a scoped API key when set (sent as a bearer token, never together with the password), otherwise the admin user and password. Request timeout 30 s.
- **Transport** (`DASH_NAS_API_TRANSPORT` / `TRUENAS_API_TRANSPORT`, `auto` by default, or `jsonrpc` or `rest`): see "TrueNAS JSON-RPC transport". With `auto`, a NAS with no JSON-RPC endpoint is remembered as REST-only for 300 s (logged "the NAS serves no JSON-RPC API ...: using REST /api/v2.0, which TrueNAS 26 no longer has"); a route with no JSON-RPC mapping falls back to REST with a warning. With `jsonrpc`, both cases are errors. REST is `https://<host>/api/v2.0`.
- A REST 404 after a fallback forgets the REST-only memory (so JSON-RPC is tried again) and, for a route that is not an object id, logs that TrueNAS 26 or later has no REST.
- **Ping**: reads the `editors` group; success means "reachable, and these credentials can read users and groups".
- **Find group / find user**: list query filtered by name, then exact match.
- **Ensure `editors` group**: creates it (with SMB on) when missing, then re-reads it. Note: listing editors, checking "is editor", setting a password, deleting an editor and setting project groups all call this, so any of them can create the group on a NAS that lacks it.
- **List editors**: every user whose primary or supplementary group is `editors`.
- **Is editor**: false for an invalid name, a missing user, or a uid below 1000; otherwise membership of `editors`.
- **Create or update editor**:
  - Refuses an existing account with uid below 1000 ("... is a system account (uid N): refusing to modify it. Pick a different username.") or not in `editors` ("... already exists on the NAS and is not in the 'editors' group: refusing to take over an account this dashboard didn't create. Add it to the group by hand first, or pick a different username.").
  - Existing editor: replaces the SSH key, turns SMB on, ensures `editors` membership.
  - New account: full name (default the username), primary group `editors`, home created under the homes parent (`DASH_NAS_HOMES_PARENT`, falling back to the first studio's `/mnt/tank/TheCreatorsPool/homes` with a warning when unset), shell `/usr/bin/bash`, a random password, the SSH key, SMB on, not locked.
  - Re-reads the account and warns "sshpubkey is not set", "smb flag is not set", "user is not a member of group 'editors'".
  - Fixes the home directory's permissions: mode 700, owner the user, group `editors`, any ACL stripped, not recursive; waits for the NAS job (polled every 2 s, up to 120 s). Skipped for `/`, `/nonexistent`, `/var/empty`. On failure warns "home directory permissions could not be confirmed fixed: SSH/SFTP (lanes A/B) may fail with a generic auth error ...".
  - Tries to disable password login for SSH; the NAS refusing this for SMB users (a 422 mentioning SMB) is expected and not warned; any other failure warns "could not set password_disabled=True".
  - Returns created or not, the username, whether the home is fixed, and the warnings.
- **Set known password**: refuses an invalid username, a missing user ("no such user"), uid below 1000 ("... refusing to set its password. This dashboard only manages editor accounts."), and a non-editor ("... refusing to set the password of an account this dashboard didn't create.").
- **Delete editor**: same refusals; a missing account is "not deleted" (not an error). Deletes without deleting the group, then re-reads and fails if the user is still listed. Warns that the home directory was left in place.
- **Per-project groups** (optional abilities used by "Per-project NAS groups"):
  - index of every group whose name starts with `proj-` (name, id, gid);
  - ensure a project group: refuses a name not starting with `proj-` ("... is not a project group"); creates it with SMB off when missing;
  - set an editor's project-group memberships: a missing user is a no-op; refuses uid below 1000 and non-editors; changes only the managed groups and leaves every other membership; reports added and removed;
  - close a project directory: refuses `/` and `/mnt`; sets the directory's group to the project group, mode 2770, strips ACLs, recursive, waits for the job; true only on success.
- **System information** (optional): version, hostname, and a support note (see the version rule below).
- **Snapshot tasks** (optional): lists the NAS's periodic snapshot tasks (read only).
- A "set password" method that only raises "use set_known_password(username, password)" exists and is never used.

## TrueNAS JSON-RPC transport
(source: nas/truenas_rpc.py)

- Speaks JSON-RPC 2.0 over a secure WebSocket at `wss://<host>/api/current` (the path can be overridden with `DASH_NAS_API_PATH` / `TRUENAS_API_PATH`; "current" or a name is turned into `/api/<name>`).
- Plain `ws://` is refused for any host other than loopback ("refusing plaintext ws:// to a non-loopback host: TrueNAS revokes an API key used over an unencrypted connection").
- Certificate handling follows the same verification setting; with a `sha256:` pin the certificate's fingerprint is compared after the connection and a mismatch is refused ("a changed NAS certificate is never re-trusted").
- Any non-upgrade HTTP answer below 500 (other than 429) means "this NAS has no JSON-RPC here" (fall back to REST); 5xx and 429 are errors. Messages over 64 MiB are refused.
- **Login**: with an API key, first `auth.login_ex` with mechanism API_KEY_PLAIN as the key's own account (`DASH_NAS_API_KEY_USER`, else the admin user), then the older `auth.login_with_api_key`; on failure the error explains which account the key was presented as and how to set the right one. With a password, `auth.login_ex` PASSWORD_PLAIN, falling back to `auth.login`. Every login refusal is reported as an authentication error with the NAS's own words.
- **Session reuse**: one logged-in session per (target, credentials, verification setting) per process, dropped after 25 s idle. Before a write on a reused session, a cheap `core.ping` checks it is alive and replaces it if not. A GET (or a write whose request never left) is retried once on a fresh session after a connection failure; a write that may have run is never replayed.
- **Route mapping** (each REST call the product makes and its JSON-RPC method): user/group/app/api_key list and create (`.query`, `.create`), get one, update, delete by id; snapshot task list, create, update; `filesystem.setperm`; `core.get_jobs`; snapshot creation (`pool.snapshot.create`, falling back to `zfs.snapshot.create` where the first does not exist); `system.info`; SSH service read and update; available apps, catalog apps, app redeploy (needs an app name). Anything else is a named "unmapped route" refusal.
- NAS errors come back as HTTP-like statuses: invalid 422, not found 404, access denied 403, not authenticated 401, already exists 409, unknown method 404, bad parameters 422, otherwise 500.
- **Version rule** (used by the system information note): versions before 25.04 get "TrueNAS <v> predates 25.04: only the REST API exists there, which works but is not a supported version. Upgrade to 25.04 or later"; versions newer than 26.99 get "TrueNAS <v> is newer than this CC Sync release has been tested against ..."; an unreadable version gets "cannot tell the TrueNAS version from ...". Never a refusal.

## Synology (DSM 7.2+) back-end: every operation
(source: nas/synology.py)

- **Two channels**: the DSM web API over HTTPS on port 5001 for accounts and groups, and SSH (default port 22, `DASH_NAS_SSH_PORT`) for SSH keys, which DSM has no API for. Request timeout 15 s.
- **API check before the first login**: asks DSM which APIs it offers and requires `SYNO.API.Auth` version 7 and version 1 of `SYNO.Core.User`, `SYNO.Core.Group`, `SYNO.Core.Group.Member`, `SYNO.Core.User.Group`, `SYNO.Core.User.Home`, `SYNO.Core.FileServ.FTP.SFTP`, `SYNO.Core.Share`, `SYNO.Core.Share.Permission`. Any missing or wrong version refuses everything with "this DSM does not offer the web API shapes CC Sync provisions with: ... Provision editors in DSM's Control Panel instead ...". A DSM that does not answer this query: "... this does not look like a DSM 7 box".
- **Login**: password only (no API key support); refused with "no DSM password configured (DASH_NAS_PW)" when blank. Logs in with session name `ccsync` (so it never logs out the operator's own browser session), password in the request body. Login errors are explained in words (invalid account or password, account disabled, no permission to log in, needs a 2-factor code: "give the dashboard an account with 2FA off", wrong 2-factor code). The session is logged out when the client is closed or discarded.
- An expired session (DSM error 119) is retried once after logging in again; other errors are reported with DSM's code and a plain-language explanation (for example 105 no privilege, 3106 no such user, 3107 user already exists, 3117 password policy, 3205 no such group).
- **Ping**: reads the `editors` group (so a green ping also means the API shapes and credentials work).
- **Find group**: by name; on DSM the group id and gid are the same number.
- **Ensure `editors` group**: creates it if missing (tolerating "already exists" from a race), then re-reads.
- **Find user**: scans the full local user list (200 per page) and matches the name case-insensitively; reads the user's group names.
- **List editors**: members of `editors` (200 per page; no group means no editors), with details from the user list. Each row shows `smb` as always on (DSM has no per-user SMB flag), the home as `/var/services/homes/<name>`, shell shown as `/sbin/nologin`, locked when the account's expiry state is not "normal", and the SSH key column as "(installed)" or empty (the key text cannot be read).
- **SSH key probe for the list**: one SSH session for the whole list checks which editors have a non-empty `authorized_keys`. Best effort (unknown when SSH is unavailable). `DASH_NAS_SSH_KEY_PROBE=0` turns it off.
- **Is editor**: false for an invalid or reserved name, a missing user, or a uid outside 1024 to 169,999; otherwise membership of `editors`.
- **Refusals** (shared by create, add key, set password, delete): invalid username; reserved names `admin`, `guest`, `anonymous`, `root`, `system`, `http` ("... is a DSM built-in account"); names starting `sc-` ("... looks like a DSM package account (sc-*)"); an existing account with uid below 1024 or at or above 170,000 ("... is a system or package account ..."); an existing account not in `editors` ("... Add it to the group in DSM first, or pick a different username.").
- **Create or update editor**: ensures `editors` first; creates the account with a random password nobody is told (always satisfying a mixed-case-and-digit policy), description = full name, never expiring, no email notification. "Already exists" from DSM for an account the list does not show is refused as a probable package account. For an existing editor, updates the description if a different full name is given. Adds the user to `editors` and reads membership back (warns "user is not a member of group 'editors'" if it did not take). Installs the SSH key over SSH (replacing `authorized_keys`).
- **Add a second SSH key** (approving another computer for the same editor): refuses anything that is not a single "<type> <key> [comment]" line; for a missing account it goes through create; otherwise appends the key to `authorized_keys` unless the same type and key are already present (then reports "already"), keeping all existing keys. A key that could not be written is an error here (not a warning), so the caller keeps the pending approval.
- **SSH key installation** (both forms): runs a script on the NAS as root through `sudo` (password on standard input, never on the command line), with the Synology tool directories added to the search path. It refuses if the home directory does not exist ("<home> does not exist: DSM's User Home service is off ... Turn it on in Control Panel > User & Group > Advanced, then re-run this."). It writes through a temporary file and a rename with a restrictive umask, sets `~/.ssh` to 700 and `authorized_keys` to 600 owned by `<user>:users`, and never changes the home directory itself or anything in a shared folder. It then reads back the modes and reports:
  - the home writable by group or others: "... sshd's StrictModes will refuse the key and log nothing. Repair with `synoacltool -enforce-inherit`: do NOT chmod it, that deletes the Synology ACL.";
  - `~/.ssh` not 700 owned by the editor; `authorized_keys` not 600 owned by the editor;
  - an interactive login shell: "... has an interactive shell (...); DSM's default is /sbin/nologin and SFTP does not need one" (warning only).
  - On create, an SSH failure is a warning ("could not install the SSH key over SSH: ...") and the account is kept.
- **SSH connection security**: the SSH session logs in as the admin user with the password (no agent, no key files). Host key: when `DASH_NAS_SSH_HOSTKEY` is set (a bare base64 key or a full key line; the type is read from the key itself), only that key is accepted. Otherwise the first host key seen is recorded in `DASH_NAS_KNOWN_HOSTS` or `<data dir>/secrets/nas_known_hosts` (owner-only) and any different key later, including a different key type, is refused ("... a different key is already recorded in <file>; refusing ..."). A damaged record file is refused rather than ignored. With no data directory known, any key is accepted. Each case logs a warning that the key is not pinned. SSH needs the optional `paramiko` package; without it: "the Synology backend needs paramiko for the parts DSM has no API for ...".
- **Set known password**: same refusals plus "no such user".
- **Delete editor**: same refusals; missing account is "not deleted". Deletes by DSM's exact spelling of the name, then re-reads and fails if still listed. Always warns "DSM removes the account's home folder together with the account".
- **SFTP service check** (UNREACHABLE: nothing in the dashboard calls it): reports whether DSM's SFTP service is on.
- **Test-account delete helper** (DEV ONLY): deletes only accounts whose names start with `ccsync_`, for a live verification script.

## Differences between the TrueNAS and Synology back-ends
(source: nas/truenas.py, nas/synology.py, protection.py, recovery.py, project_groups.py, sftp_transport.py)

- Credentials: TrueNAS accepts a scoped API key (preferred) or password; Synology needs the admin password (and uses it for SSH and sudo too).
- API: TrueNAS JSON-RPC over WebSocket with a REST fallback; Synology DSM web API on port 5001 plus SSH.
- System account floor: TrueNAS uid below 1000; Synology uid below 1024 or at/above 170,000, plus reserved names and the `sc-` prefix.
- Username match: exact on TrueNAS; case-insensitive on Synology.
- New account: TrueNAS creates a home under the configured homes parent with shell `/usr/bin/bash`, SMB on, random password, and then disables password login where allowed; Synology creates the account with a random password, home at `/var/services/homes/<name>` made by DSM, primary group `users` with `editors` supplementary.
- SSH key: TrueNAS stores it on the account through the API (a second key replaces the first through this method; the merging for a second computer happens in the API layer outside this part); Synology writes `authorized_keys` over SSH and can append a second key.
- Home permissions: TrueNAS sets the home to 700 through a NAS job; Synology never changes the home (it would delete the Synology ACL) and only checks it.
- SMB: a per-user flag on TrueNAS; not applicable on Synology (always shown as on).
- Deleting an editor: TrueNAS leaves the home directory; DSM deletes it.
- Group creation: TrueNAS creates `editors` with SMB on; Synology plain.
- Per-project NAS groups: TrueNAS only. On Synology the feature logs once and does nothing.
- Snapshot tasks: readable on TrueNAS; on Synology the protection panel's snapshot lines are permanently CANNOT VERIFY with a "confirm in DSM" message, and the recovery runbook never verifies a dataset, so it prints no snapshot commands.
- System information (version, hostname, support note): TrueNAS only.
- SFTP transfer limits: chunk size and concurrency are capped (64Ki, 16) on a Synology that serves the lanes itself; no cap on TrueNAS.
- Editor list SSH key column: TrueNAS shows the key; Synology shows "(installed)" from an SSH probe.

## Looks redundant or overlapping

- `truenas_client.py` is an import alias for `nas/truenas.py` that nothing imports any more.
- Two ways to secure the Syncthing admin page: the collector's guard (every cycle) and the setup wizard's own call to the same function; the comments also mention a separate server script that does the same by hand.
- Snapshot-task "covers this dataset" logic exists twice (protection panel and the recovery runbook's fact check) with the same rule written separately.
- The collector's directory-signature walk and full media walk, the retarget media-count walk, the restore preview walk and the drill's file pick all walk project trees separately with their own limits.
- The inventory (every 15 minutes) feeds three separate consumers in this part: the retarget sanity check, hand-move detection (including a cross-pass pending table), and the locate answer; hand-move detection alone carries two pairing systems (within a pass and across passes) with different rules.
- Device-to-editor mapping is computed in the config pass (with a fallback when no editor is known) and again, with different rules, in the enforce pass (a seed-time shape-only mapping and a known-editor mapping).
- "Unknown editor", "unapproved device" and "shared by person" warnings are logged once per process only, in the container log, beside the notice system that exists for exactly this.
- The TrueNAS back-end carries a `set_password` method that only raises, and the Synology back-end carries `sftp_enabled` and a test-only delete helper that nothing in the dashboard calls.
- Per-project NAS groups have three membership sources (ticks, admin grants, and a ledger of what was added), alongside the Syncthing share logic that already decides who receives each project.
- The admin assignments page renders a separate whole-fleet grid view whose ticks go to the same per-editor routes the editor switcher uses.
- The ignore lists, video extension list, slug rule, template folders, folder settings, project marker logic and the JSON-RPC transport are each kept as hand-copied duplicates of server-side code (per comments, pinned equal by tests).

## Claims the code does not back

- recovery.py's `_nas_identity` docstring says it reports "what the NAS says it is". The code only checks that the NAS answers; the platform it reports is the configured `DASH_NAS_KIND`, not anything the NAS said.
- synology.py says the DSM port is "Overridable because a site can move it", and its redirect error tells the operator to "Point DASH_NAS_HOST / DASH_NAS_PORT". There is no `DASH_NAS_PORT` setting and the factory never sets the port: it is always 5001 (only the tests' base URL override changes it).
- syncthing_client.py's tailnet-only options are described as an opt-in that an operator can turn on; nothing calls `apply_tailnet_only_options`, so `DASH_SYNCTHING_TAILNET_ONLY=1` has no effect.
- syncthing_gui_guard.py's docstring says it secures the admin page "at boot". It runs from the collector's cycle, first on the first cycle and then every 120 s until it succeeds, then hourly.
- collector.py's `_run_inventory` docstring says "At most `inventory_projects_per_cycle` projects are touched per cycle via a rotating cursor"; the code checks every active project's directory signature every pass and only bounds full walks, and never-walked projects are outside the bound.
- collector.py's comment on the hand-move cap refers to "`_record_inventory`"; no such function exists (the walk is in `_run_inventory`).
- truenas.py's `_verify_setting` comment says "Default False preserves the existing behaviour"; unset now means first-use certificate pinning.
- settings comment for `nas_verify_ssl` says "Default False preserves the existing behaviour"; `Settings.from_env` turns an unset value into first-use pinning ("tofu").
- protection.py's module docstring says green requires "a last run inside 25 hours, a key configured, a date an admin set"; the restore-drill line is also turned green by the dashboard's own automated drill (recovery.py), not only by an admin.
- project_groups.py's docstring says per-project is "the default for a NEW site"; inside the dashboard the default of `DASH_PROJECT_ACL` is `shared` (a new site gets per-project only if its deploy writes it).
- synology.py's `_delete_user` docstring says "Removing an editor is a DSM Control Panel action -- the admin UI has never offered it"; `delete_editor` in the same file is called by the dashboard's delete-user flow.

## Could not determine

- The undo window length for recent tick changes, the audited-untick authorisation window, the mass-deactivation brake's threshold, the inventory collapse brake's rule, the pending-move-half retention and read cap, and the retention periods of the prune pass: all live in the database layer (db.py), which is outside this part.
- The exact slow-poll notice threshold (`notices.SLOW_POLL_SECONDS`) and the wording of the slow-poll and moves-dropped notices: in notices.py, outside this part.
- What the self-diagnosis notice checks, invariants, alerts, file-move reconciliation, the Claude Code auto-update tick and the tailnet Serve watchdog actually check: outside this part; only that the cycle calls them and when.
- Which HTTP routes call project-group grant/revoke, protection acknowledgements, the recovery operations and the locate function, and who may call them: in api.py and ui.py, outside this part (the recovery routes exist in both api.py and ui.py).
- Whether the JSON-RPC login shapes work against a live TrueNAS: the module itself states they were never verified live.
- Whether "machine" values containing `*` can exist (the assignments page reserves `*` as "all computers" on the assumption that hostnames cannot contain it).
