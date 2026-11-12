# Companion: uploading originals and downloading proxies and originals

Terms used throughout this section:

- **The NAS** is the central file server. **The tree** is the project folder
  hierarchy on it. Its top-level folder for projects is `Projects/`.
- **Local root** (`local_root` in the companion's config) is the folder on the
  editor's computer that mirrors the tree (on Windows usually reached as `P:\`).
- **A tick** is one project chosen for this computer on the dashboard. The list
  of ticks the dashboard hands this computer is **the selection**. A tick has a
  mode: **full** (sync both ways) or **upload-only**.
- **An original** is a camera video file (the large source footage). **A proxy**
  is a small edit-friendly copy kept in a `Proxy/` folder beside it.
- **Lane A** uploads originals from this computer to the NAS. **Lane B** brings
  proxies (and the project structure) down from the NAS. **Express** is a fast
  upload path for files that just appeared. **The originals lane** brings down
  originals the editor asked for. **Lane C** (Syncthing, a separate two-way
  folder sync program) is outside this section except where these lanes touch it.
- **rclone** is the third-party command-line copy tool every lane here runs as a
  child process.
- **The breaker** is a safety latch that stops lane B when a pass would remove
  too many local files.

## Lane status: what every lane reports
(source: sync/base.py)

- Every lane exposes the same status record, read by the tray, the Settings
  window and the report sent to the dashboard.
- A lane is always in exactly one of four states: `idle`, `syncing`, `error`,
  `paused`.
- Fields every lane carries:
  - the lane name;
  - the state, and **when it entered that state** (stamped automatically every
    time the state changes, and kept unchanged when a status snapshot is copied);
  - `queued` (files waiting) and `transferring` (files in flight);
  - `last_error` (a sentence) and `last_sync` (time of the last successful pass);
  - `detail` (a free-text line, shown on the tray);
  - the project currently being worked on;
  - bytes done, bytes total, speed in bytes per second, estimated seconds left;
  - a list of per-file transfers in flight, each with name, direction, bytes
    done, bytes total, percentage, speed and estimated seconds left (empty when
    idle or between progress ticks);
  - a **progress token**: a value that changes only when real work happened
    (bytes or files moved, and the project they moved for). The dashboard uses
    it to mark a lane that says `syncing` but has not moved as stuck. It is
    deliberately based on bytes, not time, so a slow but moving transfer is
    never read as a hang. Empty when nothing is running;
  - a **direction** (`up`, `down`, `both`, or empty), used inside the companion
    only (for example by the drive-pulled reminder); its comment says it is never
    sent (the report builder is outside this section) in the
    report.
- Every lane can be started, stopped and asked for its status, and none of
  those three may ever fail outward; failures appear as `last_error`.
- Every lane supports "run one pass now" (the tray's "Sync now"). A lane with
  no on-demand pass just returns its status.

## Asking the dashboard where a missing file went
(source: sync/server_locate.py)

- Purpose: before lane B treats files that vanished from the NAS as deletions,
  the companion can ask the dashboard whether the same file now lives elsewhere
  in the tree (a folder moved by hand on the NAS, possibly into a different
  project).
- The question is `POST <dashboard_url>/api/v1/files/locate` with a body
  listing files by **basename and size** only.
  - It carries two headers: `X-CCSync-Token` (the companion's fleet token from
    config `dashboard_token`) and `X-CCSync-Identity` (the signed-in editor's
    identity token, read fresh on every call so a token rotated at sign-in is
    used at once).
  - Names are compared in Unicode NFC form (the composed spelling; macOS
    filenames arrive decomposed). The location that comes back is the server's
    own spelling and is what a rename uses.
  - Duplicate (name, size) pairs are asked once. Pairs with an empty name or a
    non-numeric size are dropped.
  - At most **2,000** files per call (the dashboard's own limit; more would be
    refused as too large). Beyond that, only the first 2,000 are asked and the
    rest are treated as deletions, with a log line.
  - Timeout **10 seconds**. Called at most once per lane B pass.
- The answer lists, for each file, every (project slug, path inside the
  project) holding a file of that basename and size; whether the dashboard has
  ever completed a walk of the tree (`walked`); how old its picture is
  (`as_of`, logged only); and, from dashboard 0.7.50 on, which projects it could
  not read this cycle (`unreadable`, logged with up to five names).
- **Any failure means "cannot tell" and changes nothing**: no dashboard URL, no
  token, a network error, a non-200 answer, a body that will not parse, or
  `walked` false. In every one of those cases the pass behaves exactly as if the
  question had never been asked (the files are treated as deletions). Each case
  is logged ("treating these files as deletions").

## Following a project that was renamed or moved on the server
(source: sync/repath.py)

- **When**: at the start of every sequencer pass for the whole selection, and
  again inside each project's turn. It runs before any lane, so lane A never
  re-uploads a project to the server path it has just left.
- **What it compares**: for each ticked project, where this computer's local
  Syncthing folder for that project points, against where the selection says it
  should be: `<local root>/Projects/<project path from the dashboard>`. A
  mismatch means the project moved on the server. Comparison ignores case and
  path-separator differences.
- There is no history file deciding this: the local Syncthing configuration is
  the only state, so a fresh install, an editor who was offline through several
  moves, or an upgrade all converge on the first pass.
- **Project paths from the dashboard are validated** before any path is built
  from them, and the same check is used by every lane:
  - trailing slashes and surrounding whitespace are trimmed;
  - refused: empty; not text; a leading `/` or `\`; any empty, `.` or `..`
    segment; any segment that is a drive letter like `C:`;
  - a refused project is logged ("refusing selection item with an unsafe
    rel_path") and skipped by every lane, so it is consistently not synced
    rather than half-moved.
  - A selection item whose path is missing, or that is marked `active: false`,
    is skipped.
  - As a second check, the computed target must lie under the local root, or
    nothing is moved ("refusing to move anything").
- **Skipped silently**: if local Syncthing cannot be reached, the whole check is
  skipped for this pass. A project with no local Syncthing folder yet is left to
  the folder-accept flow (and any "blocked" note for it is cleared).
- **The move, step by step**:
  1. Pause the project's local Syncthing folder (if pausing fails, skip the
     project this pass).
  2. Move the local directory to the new path:
     - if the old directory is gone and the new one exists, nothing is moved
       and the folder is just re-pointed;
     - if neither exists, nothing happens and the folder is not re-pointed;
     - if the new path already exists and holds a `.stfolder` marker (it was a
       Syncthing folder), the old directory is left in place for a human and
       the folder is re-pointed to the new one;
     - if the new path exists, holds no files at all (only empty folders), the
       empty skeleton is removed and the move goes ahead;
     - if the new path exists and holds files but is not a Syncthing folder,
       the move is **refused** (see the "folder with its new name" note below);
     - otherwise the directory is renamed. Parent folders of the old location
       are never pruned, even if left empty.
     - Across drives (rename impossible), the directory is copied to
       `<new path>.ccsync-moving`, renamed onto the new path only when the copy
       is complete, and only then is the old directory removed. A
       `.ccsync-moving` copy left over from a failed attempt is deleted at the
       start of the next attempt. If the old directory cannot be fully removed
       afterwards it is left in place with a warning.
     - A move that fails (typically Resolve, Explorer or antivirus holding a
       file open on Windows) is logged and not re-pointed.
  3. If the move failed, the folder is **left paused and pointing at the old
     place**, deliberately (re-pointing would make Syncthing read the whole
     project as deleted and spread that to the NAS and every editor). A
     "blocked" event is recorded and the project's lanes are skipped by the
     sequencer. The next pass retries by itself.
  4. If the move worked: re-point the local Syncthing folder at the new path,
     with the project path as its label; try to relink the open Resolve
     project's clips from the old path to the new one; record a "moved" event;
     unpause the folder.
- **Recovery without a move**: if a project that was recorded as blocked is
  found at the right path again (the admin undid the rename, or the editor
  re-ticked it), its folder is unpaused first and the blocked note is cleared
  only if the unpause worked.
- **The events ledger**: `~/.ccsync/state/repath_events.json`, the last **20**
  events, each with a unique id, project slug, old path, new path, time,
  whether Resolve was relinked (yes / no / not answered), a note (cut to 512
  characters) and whether the move happened. Only one event per project, old
  path and outcome is kept, so a project that fails to move every pass does not
  push out real renames.
- **Resolve relink follow-up**: a moved project whose clips Resolve did not
  answer for (Resolve closed, or open on another project) stays pending for
  **30 days**. Pending relinks are retried at the head of each check, at most
  once every **5 minutes**, once per (old, new) pair. When one succeeds its
  note is rewritten to the "Resolve was relinked" form.
- **Sentences the editor is shown** (exact text, `{name}` is the project path):
  - moved and relinked: "Your admin renamed a project on the server. CC Sync
    moved your copy to match ({name}). Resolve was relinked."
  - moved, not yet relinked: "Your admin renamed a project on the server. CC
    Sync moved your copy to match ({name}). Resolve reconnects the clips next
    time you open that project."
  - move failed: "{name} is not syncing because CC Sync could not move its
    folder. Your files are safe where they are. Close it in Resolve and in
    Explorer, then it retries by itself."
  - refused because the new name is taken: "{name} is not syncing because a
    folder with its new name is already on this computer. Your files are safe
    where they are. Move that other folder somewhere else, then it retries by
    itself."

## Originals on request from inside Resolve (the request inbox)
(source: originals_requests.py)

- **What it is**: Resolve menu scripts (installed elsewhere) let an editor ask
  for the originals of chosen clips. The scripts cannot call the network, so
  they write a request file into `~/.ccsync/requests/originals/`. The companion
  watches that folder and does the rest.
- **Polling**: the folder is checked every **2 seconds** by a background loop.
  A missing folder is not an error.
- **Request file format** (JSON, schema version 1), validated strictly:
  - at most **4 MiB**; must be UTF-8 JSON and a JSON object;
  - `v` must be exactly the integer `1`;
  - `action` must be `add` or `remove`;
  - `source` must be one of `media_pool`, `timeline_range`,
    `timeline_playhead`, `timeline_all` (accepted but not otherwise used);
  - `clips` must be a non-empty list of at most **10,000** objects, each with
    `file_path` (text, at most 4,096 characters, may be empty) and `unique_id`
    (text, at most 1,024 characters), and optional `name` and `type` (at most
    1,024 characters); no field may contain a NUL character;
  - optional `project` and `timeline` names (at most 1,024 characters);
  - `created_at` (text, at most 64 characters) is required.
  - A malformed request is logged and **deleted unanswered**.
- **Age limit**: a request older than **1 hour** (by file time or by its own
  `created_at`, whichever is older) is logged and deleted unanswered.
  A half-written `*.tmp` file older than an hour is also deleted.
- **Turning clips into files**:
  - a clip with a file path uses it;
  - a clip without one (a multicam or compound clip) is resolved from memory of
    the timelines the Resolve watcher has already walked this session: a
    container's angle files, or a plain clip's own file. This memory holds up
    to **50,000** clip ids per kind, oldest dropped first. Nothing here talks
    to Resolve itself.
  - Each file path is turned into a path inside the tree, either from the
    canonical drive form (for example `P:\Projects\...`) or from the local root
    (for example a Mac's `/Volumes/<drive>/<tree>/Projects/...`). Paths with
    `.` or `..` map to nothing.
  - Each tree path is matched to the deepest ticked project containing it
    (compared NFC and case-folded). Upload-only ticks are kept on purpose, so
    the dashboard's refusal reaches the editor.
  - Files outside every ticked project are counted as "outside". Files inside
    one that are not camera originals (same rules as the originals lane
    below: proxies, partials, hidden, non-video) are counted as "skipped".
- **Recording the pick**: per project, the companion asks the dashboard to
  record the pick, with the files to add (each marked as a file, not a folder)
  or to remove. (The HTTP call itself is supplied by the caller; this file's
  header names it as `PUT /api/v1/selection/{editor}/{slug}/originals`.)
  - No answer, a network error, or an HTTP 5xx keeps the request file for the
    next poll; projects already answered are not sent again.
  - When every project has an answer, the file is deleted and one balloon
    notification is shown. If any project got HTTP 200, the originals lane is
    woken at once.
- **Balloon text** (built in this order, joined into one message):
  - a dashboard 409 refusal's own `detail` sentence, **verbatim and first**
    (for example the refusal of a pick on an upload-only tick), each distinct
    sentence once;
  - any other non-200: "The server refused part of this request (HTTP
    {status})." or "...(HTTP {status}): {detail}";
  - success, adding: "Bringing {N original(s)} to this computer ({size}). The
    tray shows progress." (the size comes from the dashboard's `total_bytes`
    and is left out when zero);
  - success, removing: "Stopped bringing {N original(s)}. Files already on this
    computer stay.";
  - "{N clip(s)} could not be matched to a file (a multicam or compound clip
    this computer has not seen on a timeline yet).";
  - "{N clip(s)} is/are not in a project this computer syncs.";
  - "{N clip(s)} is/are not camera originals.";
  - with no refusal and no success: prefixed "Nothing was queued:" (or just
    "Nothing was queued." when there is nothing else to say).

## Originals lane: bringing chosen originals down
(source: sync/originals_lane.py)

- **Lane name** reported: `lane_b_originals_down`.
- **What comes down is the dashboard's decision**: each tick in the selection
  may carry an `originals` list of paths inside the project. Absent or empty
  means nothing.
  - Only **full** ticks count; an upload-only tick brings nothing down even if
    it carries a list.
  - A tick whose project path fails validation is ignored.
  - An `originals` value that is not a list of text is ignored for that
    project, with a warning ("bringing nothing for it").
  - Duplicates (compared NFC, case-folded) are dropped; at most **20,000** paths
    per project, the rest dropped with a warning ("taking the first ...").
- **Which names may ever be fetched**, whatever the dashboard says (also used by
  the request inbox):
  - must be a relative path with forward slashes, no newline, carriage return
    or NUL, no backslash, no leading `/`, no drive letter, no empty, `.` or
    `..` segment;
  - no segment starting with `.` (hidden files, `.ccsync-trash`,
    `.stversions`, macOS `._` files);
  - no segment starting with the file-move staging prefix;
  - not inside any folder named `Proxy` (any case);
  - not ending in `.partial`, `.tmp`, `.part`, `.ytdl`, `.lock`,
    `.ccsync-tmp`, nor containing `.partial`;
  - must have a video file extension (the same list lane A uses).
- **When it runs**: its own background loop, independent of the other lanes,
  so originals coming down never slow footage going up.
  - Looks at the plan every **120 seconds**; woken sooner when the selection's
    wanted set changes (checked every time the sequencer reads a selection),
    when a Resolve request is accepted, or by "Sync now".
- **Gates checked before each look and every second during a run** (state
  `paused`, with the detail shown):
  - fleet or local halt: "NOT DOWNLOADING ORIGINALS: syncing is stopped on this
    computer";
  - tray Pause: "NOT DOWNLOADING ORIGINALS: syncing is paused";
  - sync drive missing: "NOT DOWNLOADING ORIGINALS: the sync drive is not
    connected";
  - a destination refusal from the same rule set the b-roll fetch uses:
    "NOT DOWNLOADING ORIGINALS: {reason}";
  - disk: "NOT DOWNLOADING ORIGINALS (disk): {reason}", either the shared
    free-space floor's reason (a nearly full drive parks originals with lane B)
    or "these originals need {size} and this drive has {size} to give, keeping
    {floor} free" when the whole batch would not fit above the floor.
- **Planning a pass**:
  - first a cheap check: any wanted file already present locally at its own
    spelling is dropped without asking the NAS. If nothing is outstanding:
    idle, "all {N} asked-for originals are here".
  - Otherwise each project with outstanding files is listed on the NAS
    (recursive listing, timeout **10 minutes**). A failed listing sets state
    `error`, "could not list the server to find the originals".
  - Each wanted path is matched to the listing by NFC, case-folded key; the
    NAS's own spelling is what gets downloaded. Counted and logged per project:
    not on the server; refused by the name rules; already here at a different
    size (left alone, never overwritten); already here at the same size.
  - If nothing is to be fetched: idle, with "{N} asked-for originals are not
    on the server" when that is why. The same unchanged outstanding set is not
    re-listed for **15 minutes**.
- **The download**: one rclone run per project, one run at a time, **2
  transfers**, using `copy` (never deletes) with "ignore existing" (never
  overwrites), from an explicit file list, through the same download route and
  tuning as lane B. Partial files are named `*.orig.partial`. Each run has a
  soft time limit of **1 hour** (the file in flight finishes) and a hard
  ceiling beyond that. A run cut off by the soft limit simply starts again.
- **Progress shown on the tray**: "Bringing originals: {done} of {total},
  {size} to go", with files in flight, files queued, bytes, speed and time left
  updated every 2 seconds.
- **A file counts as arrived** when rclone reports it copied, or, after the run,
  when it is present locally at exactly the size the NAS listed.
- **Stopping a run**: the companion stopping; un-picking any file in the run
  ("some of these originals are no longer asked for"; files already down stay,
  un-picking never deletes); any gate above becoming true; the hard time
  ceiling. A stop between two projects also prevents the next project's run.
- **Outcomes**: all good, idle with "brought {done} of {total} originals down"
  and the last-sync time updated; rclone failure, state `error` with rclone's
  last error line or "rclone exited with code {n}" or "{n} originals did not
  arrive"; could not write the list, "could not write the list of originals:
  ..."; could not start rclone, "could not start rclone: ..."; any unexpected
  failure, "could not bring originals: ...".
- **Ledger**: `~/.ccsync/state/originals.json` records each original this lane
  brought down (project, path, size, NAS modification time, arrival time). It
  is never used to decide what to download.
- **Keeping lane A quiet**: every file this lane is writing, or landed in the
  last **1 hour**, is excluded from lane A and express runs (in both Unicode
  spellings).
- It publishes the same status record as every other lane (state, counts,
  bytes, speed, progress token), so whatever reads lane statuses (tray, report,
  keep-awake guard, drive reminder) can see it; those readers are outside this
  section.
- Temporary list files `originals_<slug>_<pid>_<n>.txt` are written in the
  state folder and deleted after each run.

## Lane A: uploading originals to the NAS
(source: sync/rclone_lane.py)

- **Lane name** reported: `lane_a_video_up`. Direction: this computer to the
  NAS. Uses rclone `copy` with "ignore existing", so it **never deletes and
  never overwrites** anything on the NAS: the first version of a file name to
  reach the NAS is the only one that ever will.
- **What it uploads (normal, full tick)**: files with one of these video
  extensions, compared without regard to case: `.braw .mov .mp4 .mxf .avi .mts
  .m2ts .mkv .r3d .crm .mpg .mpeg .wmv .webm .insv .360`, at any depth, except:
  - anything inside a folder named `Proxy` (any case, at the root or nested);
  - macOS AppleDouble sidecars (names starting `._`);
  - names starting `.ccsync-move-` (a file move half-way through);
  - YouTube-download work files: `*.editready.*`, `*.original.*`,
    `*.temp.*`, `*.fNNN*.*` (yt-dlp format fragments such as `.f137.mp4`),
    `*.failed`;
  - empty (0-byte) files (`--min-size 1B`);
  - files whose modification time is less than **120 seconds** ago (so a file
    still being copied in is not uploaded half-written);
  - paths an express run or a background (handed-off) upload of this lane has
    in flight right now (logged: "deferring N path(s) to the in-flight express
    run", "leaving N file(s) to the upload still running in the background");
  - paths the server has moved away from (supplied by the file-moves feature;
    logged "keeping N path(s) the server moved away from out of this run").
- **Upload-only ticks carry every file**, not just video, because such a
  project has no Syncthing lane. Still excluded for those: the `Proxy` folders,
  AppleDouble, move staging, the YouTube work files, `.ccsync-trash`, names
  ending `.tmp .lock .partial .part .ytdl .ccsync-tmp` or containing
  `.part-Frag`, OS litter (`.DS_Store`, `Thumbs.db`, `desktop.ini`), and
  Syncthing's own state (`.stversions/`, `.stfolder/`, `.stignore`). A separate
  rule file (`filter_up_all.txt`) is used for these runs. If the "is this
  upload-only?" question fails, the video-only rules are used.
- **Rule files**: written to `~/.ccsync/state/filter_up.txt` and
  `filter_up_all.txt` (lane B: `filter_down.txt`), replaced atomically. Before
  every run the file is checked: missing, unreadable, empty, or not ending in
  the catch-all exclude means the run is **refused** with state `error` (the
  message names the file, for example "filter file is empty (...) -- refusing to
  run unfiltered").
- **When it runs**:
  - Normally ("managed mode") a separate sequencer (outside this section)
    calls one pass per project per rotation turn, with a per-project time
    budget. The lane's own timer is then not used, and the log says so once:
    "managed mode -- scan_interval_up/scan_interval_down are IGNORED ...".
  - When the lane is not driven by the sequencer (the older whole-tree mode),
    it runs one pass at start and then every `scan_interval` seconds (default
    **300**), plus one pass `watch_debounce_seconds` (default **10**) after the
    last file event.
- **One pass, step by step** (lane A and lane B share this order):
  1. If the local root folder is not there: idle, detail "local root missing
     (drive disconnected?)", one warning per disconnection ("If this is an
     external drive, plug it back in; syncing resumes on its own."). No rclone
     is started, so a pass can never fill the internal disk.
  2. If the lane is stopping: nothing happens.
  3. If this is a rotation turn and the sequencer has already moved on to
     another project: the pass is dropped, idle with "skipped a queued pass:
     the rotation had moved on". Only rotation turns are checked; consolidate
     and FIX ALL calls are never dropped.
  4. Lane B only: breaker and disk-floor checks (see lane B).
  5. rclone must be runnable: the binary is looked up on PATH or at the
     configured path and `rclone version` must succeed within 10 seconds.
     Failures: "rclone not found on PATH ('...')", "rclone not found at '...'",
     "rclone at '...' failed to run: ...", "rclone at '...' exited N" (state
     `error`). A success is remembered for **5 minutes**; failures are re-checked
     every time.
  6. Lane A: if the project folder does not exist locally, see "Project folder
     missing or moved on this computer" below.
  7. Lane B: the route, pre-flight listing and breaker check (see lane B).
  8. Lane A: if background (handed-off) uploads already hold every transfer
     slot, no pass is started (logged "all N upload slot(s) are busy").
  9. State `syncing`, current project set, progress token started.
  10. rclone runs with progress every **2 seconds**; live per-file rows, bytes,
      speed and time left are published.
  11. Outcome (see "How a pass ends").
- **Re-check passes use fewer connections**: when the sequencer says a project
  has had no local change since its last clean pass, lane A runs with **4**
  SSH connections and **4** checkers instead of the normal 16 and 16
  (`sftp_connections_verify`, `checkers_verify`; 0 means use the normal value).
  Anything found still uploads.
- **Background hand-off** (`lane_a_handoff_enabled`, default on): on a rotation
  turn, when the per-project budget plus **10 seconds** has passed and rclone
  still has files in flight, the pass returns and lets that rclone finish in
  the background instead of holding up every other project.
  - Nothing is killed (SFTP uploads cannot resume).
  - Later lane A runs leave those files out, use only the slots not held by
    background uploads (never fewer than 1), and use a distinct temporary-file
    suffix `.h<N>.partial` so two runs never write the same temp file.
  - The tray detail while only background uploads run: "uploading {name}
    ({percent}%)" for one file, otherwise "uploading N file(s)". The lane shows
    `syncing` (dated from the hand-off) and its bytes, speed and time left
    include the background uploads, so keep-awake and progress tracking see them.
  - Foreground detail at hand-off: "transferred N file(s); the rest are still
    uploading in the background".
  - Each time a background upload finishes a file, or exits, the sequencer is
    asked to start another pass at once.
  - A background upload's finish is logged (finished, ended by stop, ended for
    a project move, or failed with its command line). Failures are never shown
    as the lane's error; what did not land goes again next turn.
  - Background uploads are ended by stop (sign-out, halt, quit) and, for a
    project about to be moved to a new path, by "end background uploads under
    this folder".
  - `consolidate` and `FIX ALL` never hand off: they wait for their upload.
- **Express upload** (`express_upload_enabled`, default on): see its own area
  below.
- **Reports this lane keeps** (each read by the tray or the report, outside
  this section): completed files for the dashboard's transfer history; stray
  NAS temp files; same-name-different-size files; future-dated files; moved and
  stray project folders (see the areas below).

## Lane B: downloading proxies (and the folder structure) from the NAS
(source: sync/rclone_lane.py)

- **Lane name** reported: `lane_b_proxy_down`. Direction: NAS to this
  computer. Uses rclone `sync`, the one operation in the system that removes
  local files; every removal is turned into a move into the recovery folder.
- **What it downloads**: everything under any folder named `Proxy` (root or
  nested, any case), and nothing else. Excluded even inside `Proxy`:
  AppleDouble `._*`, the recovery folder `.ccsync-trash`, names ending `.tmp`,
  `.lock`, `.partial`, `.part`, `.ytdl`, and `.ccsync-move-*` staging names.
  - YouTube originals are deliberately **not** downloaded; only their `Proxy`
    previews come down.
- **Stability gate**: proxies modified less than `lane_b_min_age_seconds`
  ago (default **120**; 0 turns it off) are skipped, so a proxy still being
  generated on the NAS is never downloaded truncated.
- **Delete caps**: at most **100** files and **20 GB** removed per pass. When a
  cap is hit rclone stops removing; the lane shows idle, not error, with
  "transferred N file(s); tidying old files in slices (safety cap), continues
  next pass".
- **Recovery folder ("trash")**: every file lane B would remove or overwrite is
  moved to `<local root>/.ccsync-trash/<YYYYmmdd-HHMMSS>/<project path>/<its
  own path>`, one folder per pass.
  - When a pass moved something there, the log says "N local file(s) not
    present on the NAS were moved to ... -- nothing was deleted, recover them
    from there", and a notification callback is fired with the folder path, at
    most once every **30 minutes** (the notification text is built outside this
    section).
  - **Retention** (the pruning itself lives in another module; this lane
    triggers it): after a pass, at most once per
    `trash_prune_interval_seconds` (0 disables), with `trash_max_age_days` and
    `trash_max_bytes`; it also prunes towards a free-space target (the disk
    floor while running, the floor's "clear" level while lane B is parked for
    disk), and is handed the breaker. Defaults for these keys live in the other
    module.
  - The trash summary reported includes the folder path and the configured
    maximum age.
- **The breaker (safety stop)**, which lane B always carries (its rules live in
  another module):
  - Before a pass: the top level of the NAS side is listed (timeout **60
    seconds**, dot-entries ignored). If the breaker judges it does not look
    like the tree, the lane stops.
  - Once per process, the NAS root itself is checked for the breaker's marker
    folders (catches a wrong remote root even though every managed pass names a
    project). A failed listing never trips it.
  - The number of local proxies in the scope is counted before the pass.
  - During the pass, deletions are credited to the breaker on every progress
    tick, so a hard kill mid-pass does not reset the count.
  - After the pass, the breaker is given the number of files moved to trash,
    their bytes, the local proxy count, how many the server says were moved
    elsewhere, and a probe it may call to count "not really deletions" (see
    "Following files moved on the server").
  - When tripped, the lane is **paused** (not error) with detail "STOPPED
    (safety): {sentence for the editor}" (the sentence comes from the breaker
    module) and logs "lane B stands down, breaker reason: ..." once per trip.
    Lanes A and C keep running. Every pass while tripped stands down at once and
    costs nothing.
  - **Resume**: from the tray or from a dashboard request (each request id is
    applied once). On success the lane goes idle with "proxy download
    resumed".
- **Free-space floor** (rules in another module): before every pass the free
  space on the sync drive is measured; if the floor says park, lane B is
  **paused** with "NOT DOWNLOADING (disk): {reason}". A failed measurement
  parks nothing. Lane A is never parked for disk.
- **Folder structure clone** (a helper called from outside this file): lists
  every directory under a project on the NAS (timeout **300 seconds**, skipping
  `.stversions` and `.stfolder`) and creates the same empty folders locally, so
  a team's empty scaffolding appears on the editor's machine. It never creates
  a folder whose name starts with `.` (in particular never `.stfolder`), and
  never anything with `..` or an absolute path.
- **Fewer connections when idle**: if a project's last lane B pass completed
  and moved nothing, its next pass uses the narrow pool (4 connections, 4
  checkers). Any pass that moves something, fails, stalls or trips returns to
  full width. Forgotten on restart.
- **Download route (`remote_down`)**: see its own area below.

## Following files moved on the server (lane B)
(source: sync/rclone_lane.py, sync/server_locate.py)

- **After each lane B pass that trashed files** (and a dashboard address and
  token are configured), the companion asks the dashboard where those files
  are now (by basename and size; see "Asking the dashboard where a missing file
  went"). For each trashed file:
  - **One new place, in a project this computer syncs**: the trashed copy is
    renamed into that place (built from this computer's own project folder plus
    the server's spelling of the path). Never overwrites: if something is
    already there it stays in trash (warning if the size differs). On macOS and
    Linux the move is a hard link then unlink, so a file that appears at the
    destination meanwhile is never replaced; where hard links are refused it
    falls back to a rename. The file-moves feature is told the old and new
    path so Resolve can be relinked.
  - **One new place, in a project this computer does not sync**: stays in
    trash, but is not counted against the breaker.
  - **Several places**: nothing moves (ambiguity is a refusal); not counted
    against the breaker.
  - **The only place is the path it was just trashed from** (the server's
    picture is older than the deletion): treated as not found.
  - **Not found / no usable answer**: stays in trash, counted as a deletion.
  - Destinations that would escape the local root (`..`, `.`, or resolving
    outside it) are refused with a warning.
  - One summary line is logged per pass (moved, duplicate, not synced here,
    ambiguous, own path, deleted), plus a line naming up to five projects the
    server could not read.
- **When a pass is about to trip the breaker**, a second check counts as "not a
  deletion" any trashed file that:
  - was carried to its new home above;
  - is still on the NAS at the **same path** (any size): a proxy re-rendered in
    the last two minutes, hidden by the stability gate, or simply overwritten;
  - is on the NAS elsewhere in the same scope with the **same basename and
    size** (a move inside the project);
  - was reported elsewhere by the dashboard.
  - This check lists the whole scope recursively (timeout **10 minutes**).
    Names are compared in NFC so a Mac's spelling matches the NAS's. A failed or
    empty listing counts only the dashboard's answers.

## Download route through a second remote (`remote_down`)
(source: sync/rclone_lane.py)

- **Setting** `remote_down` (blank by default = download over the normal
  `remote`). When set, download-only operations (lane B passes, its pre-flight
  and relocation listings, its root check, the originals lane, and other
  download-only callers outside this file) read the tree from that rclone
  remote instead. Uploads never use it, and a lane A given a download route
  ignores it with a warning.
- `remote_down_root` sets the path on that remote; blank means the same as
  `remote_root`. A trailing `:` typed after `remote_down` is ignored.
- **Extra download flags on that route**: HTTP/2 off, 4 parallel streams per
  file for files above 256 MiB.
- **Refused when it would send a password in clear over the internet**: the
  companion reads the remote's URL (from rclone's config, the environment
  variables `RCLONE_CONFIG_<NAME>_URL` / `_TYPE`, or an inline connection
  string) and, if it is plain `http` to a public address, uses `remote` instead
  and logs once: "remote_down '...' points at plain http on a public host; its
  password would cross the internet in cleartext. Using `remote` instead until
  the rclone remote's url is https." If rclone's config cannot be read
  (timeout **20 seconds**), the route is used anyway. A successful config read
  is remembered for the life of the process.
- The route is re-chosen at the top of every pass; a change is logged
  ("downloading via ...").
- **Parks lane B (paused, not error) when the route misbehaves**, and retries
  next pass:
  - listing failed: "NOT DOWNLOADING (route): the server's download link did
    not answer, so proxy download is paused and nothing was changed here. It
    tries again next pass."
  - listing came back empty while this computer holds proxies in that scope
    (for example a sign-in page in front of the tunnel): "NOT DOWNLOADING
    (route): the server's download link listed {scope} as empty while this
    computer holds {N} proxies there, so proxy download is paused and nothing
    was deleted. It tries again next pass."
  - The technical cause (which remote, which path) goes to the log once per
    distinct park.

## Express upload (new clips go up within seconds)
(source: sync/rclone_lane.py)

- **What it is**: lane A watches the local root for file changes. When a video
  file inside a ticked project appears or changes, it is uploaded by its own
  short rclone run seconds after it settles, instead of waiting for the
  rotation. The normal pass still runs; express only adds to it.
- **Settings**: `express_upload_enabled` (default on);
  `express_debounce_seconds` (default: `watch_debounce_seconds`, which defaults
  to **10**; minimum 0.1); `express_max_batch` (default **200** paths).
- **Which events count**: created, modified or moved (destination path) files,
  not folders, whose path passes the lane A video rules (video extension, not
  under `Proxy`, not `._*`, not `.ccsync-move-*`, not a YouTube work file).
  Non-video files are never expressed, even on an upload-only tick.
- **Scope**: the file must be under `Projects/` (any case) and inside a project
  currently ticked here (deepest match, compared NFC and case-folded). With no
  known ticks yet (empty list) nothing is in scope. Only when no selection
  source is wired at all does it fall back to "the first three folders under
  `Projects`" (older whole-tree mode). Each matching event also tells the
  sequencer which project changed.
- **Batching**: events are collected for a fixed window starting at the first
  event (not restarted per event), then one rclone run uploads the batch. Over
  200 pending paths, extra paths are left to the normal pass (logged once per
  1,000 drops, counted as `dropped_over_cap`).
- **Readiness, checked per file when the window closes**:
  - gone since the event: dropped;
  - pending longer than **30 minutes**: given up, left to the normal pass;
  - empty: wait another window;
  - being uploaded by a background (handed-off) upload, or inside the project a
    normal pass is uploading right now: wait (logged "express deferred N
    path(s) to the periodic run already in flight");
  - size changed since the last look: wait;
  - modified less than **120 seconds** ago: wait;
  - otherwise uploaded.
- **The run**: `copy` with "ignore existing", an explicit file list (written to
  `~/.ccsync/state/express_<pid>_<n>_<random>.txt` and deleted afterwards),
  temporary files named `*.exp.partial`, the machine's `transfers` count, and
  a time limit equal to `project_rotation_seconds` (minimum **60** seconds,
  default **600**). Paths the server moved away from are removed from the list
  first.
  - Only one express run at a time; a batch that cannot start is put back for
    the next window (re-proving stability, keeping its original 30-minute
    clock, within the 200 cap).
  - Skipped (logged) when: the local root is missing, no remote is configured,
    rclone is not runnable, or the list could not be written (an empty entry,
    a newline, `..`, an absolute path or a drive letter is refused).
  - Paths in flight are claimed before the run so a normal pass leaves them out,
    and released afterwards even on failure.
- **Failures never turn the lane red**: they are logged ("express upload exited
  N: ...") and recorded in the express counters only. Successes go to the
  transfer history.
- **Pause**: the tray's "Pause syncing" pauses express too (pending paths
  dropped, timer cancelled); resume re-arms it. Stop disarms it and ends any
  express rclone.
- **Leftover list files** `express_*.txt` older than **1 day** are deleted when
  the watcher starts.
- **Counters reported**: enabled, runs, files uploaded, dropped over cap, last
  run time, last run file count, last error, and seconds since the last run
  (empty before the first run), so a dead express path is visible.

## File watcher and a drive that stops answering
(source: sync/rclone_lane.py)

- Lane A's file watcher (needed by express) is started at lane start (or
  watcher-only in managed mode). If the `watchdog` library is missing it logs
  that it falls back to periodic-only uploads.
- **Before the watcher opens the drive**, a separate short-lived process tries
  to open and list the local root (frozen build on Windows: `cmd /c dir /a /b`;
  frozen build on macOS and Linux: `/bin/ls -a1`; a source run: a small Python
  snippet). If it does not answer within **5 seconds**, the watcher is **not**
  started (a hung open would freeze the whole companion). If the probe cannot
  run at all, the watcher is started anyway.
- While the drive does not answer: retried after **60 seconds**, doubling to at
  most **15 minutes**. Uploads continue on the sequencer's schedule. A probe
  process that cannot be killed is left to the operating system with a warning.
- **Notifications** (one each way, not one per retry):
  - "The sync drive isn't responding, so CCSync can't watch it for new files.
    Disconnect and reconnect the drive, or restart the computer. Everything
    else is still running."
  - "The sync drive is responding again. CCSync is watching it for new files."
- Each watcher start bumps a counter the sequencer uses to tell whether the
  same watcher has been watching since a project's last clean pass; a dead or
  missing watcher means "cannot tell", which forces a full pass.

## How a pass ends (both lanes)
(source: sync/rclone_lane.py)

- **Success**: idle, last-sync time set, detail "transferred N file(s)". Error
  lines from retried attempts are logged but do not fail the pass.
- **Per-project budget reached** (rclone `--max-duration` with a soft cutoff:
  files in flight finish, nothing new starts): idle, not error, detail
  "transferred N file(s), paused at the {N}s project budget". The rest goes next
  turn.
- **Delete cap reached** (lane B): idle, see lane B.
- **Stopped** (sign-out, quit, upgrade): idle, "stopped mid-transfer" or
  "stopped before this pass started"; never red.
- **Killed as stuck**: error, with the stall sentence (see "Stuck transfer
  watchdog").
- **Any other non-zero exit**: error, with the most useful rclone error line
  (skipping rclone's generic "Fatal error received" notice), or the stderr tail
  without notice lines, or "rclone exited N". Logged locally with the full
  command line.
- **Breaker tripped by this pass** (lane B): ends as the breaker stand-down.
- The sequencer can read, per project: how many files the last pass moved
  (transfers plus trashed); whether it ended with work remaining, moved
  something, or found nothing (only for a clean ending; everything else is
  "unknown"); and whether the pass had to leave files to express or a
  background upload.
- **Stop behaviour**: stop ends the running rclone (terminate, wait 5 seconds,
  then kill), express and background children too, and stops the watcher. A
  stop that lands just before a spawn prevents the spawn. A lane latched off by
  stop is re-armed when the sequencer starts again.
- **Abort from the sequencer**: the sequencer can end just the running child of
  a pass it has given up waiting for (recorded as a stall with its reason)
  without latching the lane off, and can set the lane's detail to a short note
  (up to 200 characters) about a pass it walked away from.

## Stuck transfer watchdog
(source: sync/rclone_lane.py)

- Every lane A, lane B and express rclone is checked every **30 seconds**.
- **Killed when nothing moved** (no bytes and no files) for
  max(4 x the per-project budget, **15 minutes**); with the default 600 s budget
  that is 40 minutes. Detail: "rclone made no progress for {N}s - killed".
- **Killed when it ran too long and is not moving**: past 2 x budget + **5
  minutes** (default 25 minutes) and nothing moved in the last two checks.
  Detail: "rclone did not exit after {N}s - killed". A run still moving bytes
  is never killed for time (logged once: "past its ...s ceiling but still
  moving").
- A missing or zero budget is treated as **600 seconds**.
- Express runs are judged on their own file counts, not lane A's bytes.
- **The stall record**: `~/.ccsync/state/lane_stall.json` (shared by both
  lanes) holds the last kill: lane (`A`, `B` or `express`), seconds, killed,
  time, detail. It survives restarts.
  - Reported (time, lane, seconds, killed; never the sentence) until that lane
    completes a pass (then stamped `recovered_at` and no longer reported) or
    **24 hours** pass.
  - A child that cannot be killed is left to the operating system and the stall
    is still reported.
- The sequencer can ask how long ago the current child last moved anything.

## Leftover and risk scans (report only, never delete)
(source: sync/rclone_lane.py)

- Run per project on a cadence chosen by the sequencer (outside this section).
- **Stray temp files on the NAS**: lists `*.partial` files under the project on
  the NAS (timeout **120 seconds**), excluding temp files this machine's uploads
  are writing right now. Reports count, bytes and up to **20** samples. Logged
  as a warning: "N orphan .partial file(s) (X GB) under ... on the NAS -- left
  in place deliberately (never deleted); remove them by hand if you want the
  space back". Results from all projects are summed.
- **Recovery folder size**: count and bytes of `.ccsync-trash`, at most
  **50,000** files counted, walked at most once every **15 minutes**.
- **Same name, different size** ("your newer version will not upload"):
  `rclone check` of local against NAS by size only, one way (timeout **10
  minutes**). Logged with the first sample and the two fixes ("Rename the local
  file, or have an admin remove the NAS copy"). Reported as `skipped_exists`;
  the tray can get up to 20 samples with this machine's size (server size not
  known). Entries for projects no longer ticked, or whose folder is gone, are
  dropped.
- **Future-dated files**: files lane A would carry whose modification time is
  more than **300 seconds** ahead of this computer's clock never pass the
  120-second age gate and never upload. Logged with the first sample and advice
  (a few hours ahead uploads by itself; further ahead needs the date reset).
  Reported with count, samples, the earliest such date and the time checked.
- **Stray project folders**: project folders on this computer (found by their
  `.ccsync-project` marker under `Projects`, at most **20,000** folders walked)
  that are in no current tick. Reports count, total bytes (at most 20,000 files
  measured per folder), and up to **20** paths and project ids. Warns "N project
  folder(s) on this machine are in no sync plan ... no lane touches them and
  nothing here deletes them". Not run when the selection is empty or unknown.
  At most once every **15 minutes**.

## Project folder missing or moved on this computer
(source: sync/rclone_lane.py)

- Every lane A pass records in `~/.ccsync/state/project_dirs.json` that the
  project folder was present (time, path, project id from its marker).
- **Folder never seen here**: idle, "project dir not yet local: {path}" (an
  ordinary first-run state).
- **Folder seen before and now gone**: error, "Your project folder for {name}
  is not where CCSync expects it. Did you rename or move it?" and, if a folder
  with the same project marker is found elsewhere under `Projects`, " It looks
  like it is at {path} now." Nothing is moved automatically. Reported as
  `moved_project_dirs` (at most 20). Cleared when the folder is back.
- Duplicate markers: the first folder found wins, the rest are logged.

## Removal gate probes (for "Remove from this machine")
(source: sync/rclone_lane.py)

- These answer, for one project, whether deleting the local copy could lose
  work. The removal feature itself is outside this section. Every probe answers
  "could not tell" on any failure, which the caller must treat as "do not
  delete".
- **Pending uploads**: a dry run of the real lane A command but without the
  120-second age gate (so files just copied in, or dated in the future, count
  as not uploaded). Timeout **300 seconds**. Returns count and up to 20 names.
- **Strict same-name-different-size**: like the scan above but answers only if
  rclone demonstrably ran (exit 0, 1 or 3; no critical line; only known
  harmless error lines; exit 3 only for "destination folder does not exist
  yet"). Timeout **10 minutes**.
- **Edited after upload** (upload-only ticks only; zero for full ticks): a dry
  run with "update" minus a dry run with "ignore existing" lists files that
  exist on the NAS at the same size but are newer here.
- **Local scan, no NAS**: files nobody carries (upload-only: names lane A
  refuses; full tick: video names lane A refuses, or non-video names ending
  `.part`, `.ytdl`, `.ccsync-tmp` or containing `.part-frag`), and future-dated
  files. Skips `Proxy`, `.ccsync-trash`, Syncthing state, OS litter, AppleDouble,
  `.partial`, `.stignore` and empty files. A read error fails closed.

## Transfer history and live transfers
(source: sync/rclone_lane.py)

- **Live rows** (every 2 seconds while a pass runs): name, direction, bytes
  done, size, percent, speed, time left, and the project id from the project
  folder's `.ccsync-project` marker (only lowercase letters, digits and
  hyphens; at most 128 characters, otherwise left out).
- **History**: every file rclone reports as copied is queued for the next
  report as {name (with the project path prefixed), direction, lane, time}.
  At most **200** names per run and **400** waiting. Files moved into the
  recovery folder are counted as removals, never as downloads.
- Error lines kept per run: at most **200**; stderr kept: last **200** lines
  (express: **4,000**). Log lines quote at most **300** characters of rclone's
  error output, notice lines removed.
- The progress token is "bytes:files:project", cut to **200** characters.

## Transport settings shared by every transfer
(source: sync/rclone_lane.py)

- Config keys (each can be set to `""` or `0` to drop that flag):
  - `sftp_chunk_size` default `255Ki`;
  - `sftp_concurrency` default **64**;
  - `sftp_connections` default **16**;
  - `checkers` default **16**;
  - `sftp_connections_verify` / `checkers_verify` default **4** (re-check
    passes);
  - `rclone_ignore_checksum` default **on** (no full re-read of each uploaded
    file on the NAS; size check only);
  - `order_by_up` default newest first; `order_by_down` default smallest first.
- Other keys read here: `transfers` (passed in; default 4 in this file),
  `lane_b_min_age_seconds` (default **120**), `trash_prune_interval_seconds`,
  `trash_max_age_days`, `trash_max_bytes` (defaults defined elsewhere),
  `express_upload_enabled`, `express_debounce_seconds`, `express_max_batch`,
  `lane_a_handoff_enabled`, `project_rotation_seconds`, `remote`,
  `remote_root`, `remote_down`, `remote_down_root`, `rclone_path` (default
  `rclone`), `local_root`. A non-integer value logs "rclone tuning: KEY=... is
  not an integer -- using N".
- Fixed on every transfer: idle timeout **5 minutes**, connect timeout **60
  seconds**, **10 seconds** between retries, case-insensitive matching, and a
  filename encoding that keeps full-width punctuation (such as `？`) exactly as
  is in both directions (a name with a real Windows-forbidden character now
  fails loudly instead of being renamed).
- **Windows**: every rclone and probe process is started without a console
  window.

## Looks redundant or overlapping

- Three upload doors for the same files (the rotation pass, express, and
  background hand-offs), each needing rules to keep out of the others' way
  (in-flight claims, per-run temp suffixes, deferrals both ways).
- Four ways of noticing a move: the repath of whole projects
  (`repath.py`), lane B's scope listing (same basename and size), lane B asking
  the dashboard (`server_locate.py`), and the project-folder-moved detection by
  marker; plus the file-moves feature elsewhere that lane B now reports to.
- Two same-name-different-size scans (advisory and strict) running nearly the
  same rclone check; two pending-upload style dry runs (pending uploads and
  edited-since-upload).
- Stray project folder scan and moved project folder detection both walk the
  `.ccsync-project` markers for overlapping questions.
- Two rule files for lane A (video-only and carry-all), and the lane A rules
  restated three times: as rclone rules, as a Python matcher for express, and
  as the originals lane's name rules.
- Three Unicode-folding helpers with slightly different behaviour (one also
  folds case), and a duplicated byte-formatting helper between the originals
  lane and the request inbox.
- The older whole-tree mode (own timer, debounce timer, the
  "first three folders" guess, an injected-subprocess code path) lives
  alongside the sequencer-driven mode.
- The originals lane has its own simpler stuck-run ceiling instead of the
  shared stall watchdog.

## Claims the code does not back

- A code comment says both helpers that once used an unbounded
  `subprocess.run(timeout=)` were moved to the bounded runner; the two
  `rclone check` runners (the advisory size scan and the strict removal-gate
  scan) still use `subprocess.run` with a timeout, which that comment itself
  says can block forever on Windows.
- The module docstring says lane B is "periodic-only"; lane B is normally
  driven per project by the sequencer and has no file watcher, so this is only
  true in the older whole-tree mode.
- `repath.py`'s header says the sequencer calls `reconcile()` before running
  lanes each pass; that call is outside the files read here and was not
  confirmed.
- The originals lane's header says the power guards keep the PC awake, the
  drive reminder names it, the tray shows it and the report carries its counts;
  none of those readers are in these files, so this is unconfirmed here.
- Comments describe the recovery folder as a "14-day" window; the actual age
  limit is `trash_max_age_days` with a default defined in another module.

## Could not determine

- Defaults of `trash_prune_interval_seconds`, `trash_max_age_days`,
  `trash_max_bytes`, the breaker's thresholds and marker folders, and the
  free-space floor's size and "clear" multiple (all in `lane_guard.py`, not in
  this part).
- The exact text of the trash notification and of the breaker's editor
  sentences (built in other modules).
- Whether the older whole-tree mode (lane's own timer and debounce run, the
  "first three folders" guess) is reachable in any shipped configuration, or
  only in tests.
- The real HTTP call behind the originals pick (the inbox takes an injected
  function) and which editor name it uses.
- How often the sequencer runs the leftover and risk scans, and its per-project
  budget in practice.
- Whether anything other than the sequencer ever calls lane A with
  `verify_only` or with `may_hand_off`.
