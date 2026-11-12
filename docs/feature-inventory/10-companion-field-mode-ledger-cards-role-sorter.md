# Companion: field mode, the footage ledger, the Timeline Cards agent role, camera-card reporting, and packaging

Terms used throughout:

- **Card**: a camera or recorder memory card (or a camera SSD) in a reader attached to the computer.
- **Ledger**: a record kept by the dashboard of every copy of every footage file on every drive the
  studio knows about (which drive, which path, what size, what time, whether it was verified).
- **Ledger mirror**: an offline copy of part of the ledger kept on this computer.
- **Ledger outbox**: a file on this computer holding copy records not yet delivered to the ledger.
- **Volume id**: how the ledger names a drive: `vol:<SERIAL>` for a local drive (its filesystem
  serial number in upper case), `nas:<share>` for the NAS pool.
- **Kind** of a volume: one of `nas` (the home NAS pool), `ours` (a studio field drive), `laptop`
  (this computer's own disk), `client` (a client's drive), `card`, `unknown`.
- **Counting kinds**: `ours`, `laptop`, `nas`. Only copies on these count towards "safe".
- **Pool**: the NAS share the studio keeps footage on, reached on this computer at the config key
  `jobs_pool_root`.

## Field backup: opening the page

(source: field_server.py, tray.py `action_open_field`, app.py)

- A tray menu item **"Field backup…"** opens the field backup page in the default browser. The item
  is shown only when the field backup service was built at start-up (config `field_server_enabled`
  is on, which is the default).
- If the page is not running (switched off, or its port could not be taken), pressing the item shows
  the notification: "The field backup page is not running on this computer (it is switched off in
  the config, or its port is taken). The log says which."
- The page lives at `http://127.0.0.1:<port>/field`. The page, its script and its style are served
  from files bundled inside the companion; the page loads nothing from any other address and works
  with no network at all.
- The server listens on 127.0.0.1 only (never on any other interface).
- When the companion quits, the page server stops and every copy it started is cancelled first.
- If the port is taken, a warning is logged ("could not listen on 127.0.0.1:<port> ... the field
  backup page will not open on this computer. Everything else is unaffected.") and the companion
  carries on without the page. The same bind error is logged at warning level only once in a row.

### Settings

- `field_server_enabled` (default `true`): turns the page and the field backup service on or off. A
  hand-edited string value is read as off when it is `0`, `false`, `no`, `off` or empty.
- `field_server_port` (default `8898`): the port. A value that is not a whole number from 1 to 65535
  logs a warning and falls back to 8898.
- `field_dest_folders` (default empty): a list (or a single string) of folders on this computer that
  are always offered as destinations, in addition to folders added on the page.
- `field_state_path` (default `<config dir>/field-state.json`): where the page's remembered choices
  are kept.
- `field_copies_path` (default `<config dir>/field-local-copies.jsonl`): where this computer's own
  verified copies are kept until the ledger mirror knows them.
- `jobs_pool_root` (shared with the jobs feature): when set, the NAS pool is offered as a destination.
- `field_pool_folder` (default `FieldBackup`): the folder under the pool root that card folders go in.
- `field_pool_unc` (default empty): on Windows, the network path the pool's drive letter must point
  at to be accepted as the pool. Empty means any mapped network drive is accepted.
- `field_pool_volume_id` (default empty): the ledger volume id of the pool. When empty, the first
  `nas:` volume the ledger mirror knows is used, and failing that `nas:thecreatorspool`.
- `dashboard_url` and `dashboard_token`: when either is missing, the ledger sync step does nothing
  and says "No dashboard is set up on this computer."
- `ledger_outbox_path`, `ledger_mirror_path`: see the ledger sections below.

## Field backup: HTTP routes

(source: field_server.py)

Common rules for every request:

- **Host check**: the `Host` header must name this loopback address and this port; otherwise 403
  with the standard loopback refusal message (DNS rebinding protection).
- **Origin check**: a request with no `Origin` header is allowed through the origin check. A request
  with an `Origin` is allowed only if the origin is `http://127.0.0.1:<port>` or
  `http://localhost:<port>`, or is on the dashboard origin allow-list used by the loopback guard (the
  configured dashboard origin, plus development origins when the dev switch is on). Anything else
  gets 403, with no CORS headers. The allow-list is rebuilt at most every 30 seconds; if rebuilding
  fails the old list is kept.
- Every answer carries `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`.
- Any unexpected failure inside a route answers 500 "the companion failed to handle that; see its
  log".
- Every refusal and error body is JSON `{ok: false, error: "<sentence>"}`.

Routes:

- `GET /field`, `GET /field/`: the page (index.html). Sent with a Content-Security-Policy that allows
  only this server's own script, style and fetches (`default-src 'none'; script-src 'self'; style-src
  'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none';
  frame-ancestors 'none'`) and `X-Frame-Options: DENY`.
- `GET /field/field.css`, `GET /field/field.js`: the style and script. In a frozen (packaged) build
  the files are read from the unpacked bundle first, then from the source folder.
- Any other GET path: 404 "not found".
- `GET /field/api/state`: the whole page state (see "What the page shows"). `?refresh=1` forces a
  fresh look at the drives instead of using the 4-second cached look.
- POST rules (all POST routes):
  - Needs either an allowed `Origin` header or a valid loopback token header (the token the tray
    and local tools use). Neither: 403.
  - `Content-Type` must be JSON; otherwise 415 "send application/json".
  - Body must be at most 64 KiB; larger: 413 "that request is too large" (a negative or unreadable
    length gives 400 with the same message). An oversized body up to 16 times the limit is read off
    the connection and discarded before answering, so the page sees the sentence instead of a
    network error.
  - Body that is not JSON: 400 "that is not JSON". Body that is JSON but not an object: 400 "a JSON
    object is expected".
  - Any refusal the service raises as a sentence becomes 409 with that sentence.
- `POST /field/api/copy` `{serial, dests: [destination ids]}`: starts copying the named card to the
  ticked destinations. Answers `{ok, run}`. Refusals (409):
  - "that card is not in a reader any more. Put it back and look again."
  - "tick at least one destination"
  - "one of the ticked destinations is not available any more. Look again."
  - "a card cannot be a destination for itself"
  - "<destination label>: <why it is not present>" (for example "The NAS pool cannot be reached from
    here.", "That folder's drive is not connected.", or the pool identity refusals below)
  - "<label>: the folder cannot be made (<error>)" when a destination folder cannot be created.
  - "this card is already being copied: wait for it to finish, or stop it"
  - "<labels> is busy with another copy" when any ticked destination, or any destination on the same
    physical disk, is in use by another running copy.
  - Starting a copy also remembers the ticked destinations as the "last ticked" set.
- `POST /field/api/cancel` `{runId}`: asks a run to stop. Answers `{ok: true}` if the run exists,
  `{ok: false}` (status 200) if not.
- `POST /field/api/folder` `{path}`: adds a folder on this computer as a destination; answers the new
  folder list. Surrounding quotes are stripped. Refusals (409):
  - "give the full path of a folder, like D:\FieldBackup" (empty, not absolute, or containing `..`)
  - "that folder is not on a drive this computer has right now"
  - "that folder is on a card or a USB stick, not on this laptop's own drive, so a copy there would
    not count. A plugged-in drive is listed under Copy to already." (folder on a removable volume)
  - A folder already on the list (compared without case) is not added twice.
- `POST /field/api/folder/remove` `{path}`: removes a folder added on the page; answers the new list.
- `POST /field/api/kind` `{volumeId, kind}`: sets what a drive is. Refusals (409): "only a drive's
  kind can be set" (volume id not `vol:`), "a drive is ours, a laptop's, a client's or unknown" (kind
  not one of `ours`, `laptop`, `client`, `unknown`). Setting `unknown` removes the person's choice.
- `POST /field/api/remember` `{dests}`: stores which destinations are ticked (called on every tick).
- `POST /field/api/sync`: starts a ledger sync in the background. Answers `{ok: true, started}`;
  `started` is false when a sync is already running.
- Any other POST path: 404.

## Field backup: the page

(source: assets/field/index.html, field.js, field.css)

- Title "Field backup". Dark theme only. Two columns on screens 900 px wide or more, one column
  below. All server text is inserted as plain text, never as markup.
- Without JavaScript the page shows "This page needs JavaScript. It does not need the internet."
- **Polling**: the page asks for the state every 1 second while any copy is running, every 4 seconds
  otherwise. While the browser tab is hidden it does not ask; when the tab becomes visible again it
  asks at once. The first load forces a fresh drive look.
- If the companion does not answer, the header chips are replaced by a single red chip "Companion
  not answering".
- **Error toast**: refusals from adding a folder, setting a kind or starting a copy appear in a box
  at the bottom of the screen for 9 seconds.

### Header chips

- "<n> waiting to send" (yellow) when copy records are waiting in the outbox.
- "Ledger online" (green) when the last sync reached the dashboard; "Offline" (yellow outline) when
  it did not; "Ledger not asked yet" when no sync has run and a dashboard is configured; "No
  dashboard" when none is configured.
- The copier in use: "TeraCopy" or "built-in copier". Hovering shows how it verifies: "TeraCopy's own
  hash check after every file" or "every file read back in full and compared".
- The computer's name.

### Cards section

- Heading "Cards" with a **"Look again"** button that forces a fresh look at all drives.
- With no card: "No card in a reader. Put one in; this page looks every few seconds."
- One entry per card, sorted by drive letter then serial. The first card is selected automatically;
  clicking a card selects it (the selected card has a red left rail).
- Each card shows: its label (or serial when it has no label), a chip with its type ("Sony",
  "Blackmagic", "Drone", "Audio", "Card"), a "Copying" chip while it is being copied, and the line
  "<n> files · <size> · <drive> · lands in "<folder>"".
- **Verdict block**, coloured:
  - green "Safe to format";
  - yellow "Safe to format · laptop only" when safe but some files rest on laptop copies alone;
  - red "Not safe to format";
  - grey "Nothing to back up".
  Under it the verdict's headline sentence (see "The verdict") and each of its notes.
- A collapsible list "Files that are short of copies (<n>)" listing up to 40 files as "<path> (<n>
  counting, <n> in all)".

### Copy to section

- One row per destination. Each row has a checkbox (disabled when the destination is not present or
  is busy with another copy), the label, a type chip ("Drive", "Folder", "NAS"), and a kind chip
  ("Ours", "Laptop", "Home NAS", "Client drive", "Card", "Kind not set"); the kind chip is green when
  the kind counts, yellow when unknown.
- Drives (not the pool, not a folder with no drive) have a **kind drop-down**: "Set kind…",
  "Ours (counts)", "Laptop (counts, flagged)", "Client drive (never counts)", "Not set". Choosing
  one saves it and refreshes; choosing "Set kind…" does nothing.
- Folder destinations have a **"Remove"** button. It removes a folder added on the page; a folder
  that comes from the config key `field_dest_folders` also shows the button but stays listed.
- Drive and folder destinations with a volume id show the kind drop-down even when the folder sits on
  a drive; setting it sets the kind of the whole drive.
- A detail line: the destination path (for a drive or the pool, the `FieldBackup` folder under it)
  and "<size> free". Updated in place each poll so an open drop-down is not closed.
- When the destination is absent, a yellow reason line and the row is dimmed.
- "Already holds <have> of <of> files on this card" for the selected card.
- With no destinations: "No drive to copy to. Plug one in, or add a folder below."
- On first load, the destinations remembered as last ticked are ticked again if present. A tick on
  a destination that has disappeared or become unusable is dropped silently.
- Every tick or untick is saved to the computer at once.
- **Add a folder** box with placeholder "Add a folder, like D:\FieldBackup" and an **"Add folder"**
  button (Enter also submits). Empty input does nothing.
- **"Copy to all"** button (shows "Copy to all (<n>)" when more than one is ticked). It is disabled,
  with a reason beside it, when: starting ("Starting…"), no card ("Put a card in a reader."), the
  selected card is already copying ("This card is being copied."), or nothing usable is ticked
  ("Tick where to copy it."). When enabled the note reads "Only what is not already there is copied;
  nothing is overwritten. Lands in "<folder>"."

### Progress section

- Shows the 3 most recent runs (a run is one card copied to one or more destinations). With none:
  "Nothing copying. Pick a card, tick where it goes, and press Copy to all."
- Each run has a title "<card label> → <folder>" and a **"Stop"** button, hidden once the run is
  finished; after pressing it reads "Stopping…" and is disabled.
- One lane block per destination with: label, kind chip, state chip, percentage, a progress bar,
  and a stats line "<done> of <total> · <rate>/s · ETA <time> · <n> of <n> files · TeraCopy|built-in
  copier" (rate and ETA only while moving; copier only while copying; stats hidden when refused),
  the file being worked on (while checking or copying), the lane's message (red when failed, refused
  or stopped), and a yellow list of problems.
- State chip text: Waiting, Looking, "Checking what is there", Copying, "Verifying" (copying in its
  verify phase), Done (green), "Needs a look" (yellow), Failed, Stopped, "Not started" (red).
- ETA format: seconds under 90 s, minutes under 90 min, otherwise hours to one decimal.

### Ledger section

- "Waiting to send: <n> copies"; "Last tried: <how long ago>|not yet"; "Ledger on this laptop: <n>
  copies, updated <how long ago>|never".
- The last sync's error sentence, or "No dashboard is set up here. Copies are kept on this laptop."
- **"Send and refresh now"** button ("Sending…" while running); disabled while a sync runs or with no
  dashboard configured. After pressing, the page refreshes 1.5 seconds later.

## Field backup: what the page lists

(source: field_service.py)

### Drives and cards

- All attached volumes are listed again at most every 4 seconds (or at once on "Look again"). A card
  that is being copied from is not re-read; if it disappears from the list while busy it is still
  shown as last seen.
- Which physical disk each volume is on, and where it is mounted, is worked out again on every look.
- **Physical disk (Windows only)**: the disk number of each drive letter is read, so two partitions
  of one disk are one physical disk. On macOS and Linux nothing is read and each volume is its own
  disk.
- **A volume is a card** when it has a serial, is not the system disk, is not a drive whose kind is
  `ours`, `client`, `laptop` or `nas`, and the card detector recognises it (see "Camera-card
  detection"). A fixed (non-removable) volume counts as a card only when it carries a camera's own
  folder layout (so CFexpress Type B and Blackmagic SSD readers work, and an internal disk full of
  footage does not).
- A card's file list is kept for 30 seconds unless its root, capacity or free space change (free
  space is ignored for fixed volumes). A volume being written by a copy, or a card being copied from,
  is not re-read.
- A card that disappears (and is not busy) is forgotten.
- **Kind guessing** for a drive with no person's choice and nothing from the ledger:
  - label `CIB_D<number>`: `ours`;
  - label `WD-<number>` or containing "passport": `client`;
  - removable: `card`;
  - system disk: `laptop`;
  - a non-removable volume that holds a configured laptop folder: `laptop`;
  - otherwise `unknown`.
  - A volume id beginning `nas:` is `nas`.
- **Which kind wins**: a person's choice on the page, then the ledger's kind for that volume (unless
  `unknown`), then the guess.

### Destinations

- **Every attached drive** that has a serial, is not the system disk, and is not a recognised camera
  card (a `generic` card, meaning a drive that merely holds media, is still offered). Copies go into
  a `FieldBackup` folder on it. Labelled with the ledger's name for the volume when the ledger has
  one, else the drive label, else the drive letter.
- **Every configured folder** (`field_dest_folders` plus folders added on the page). Junctions and
  links are followed, so a folder that is really on a field drive counts as that drive. Copies go
  straight into the folder (no `FieldBackup` sub-folder). Its kind is the holding volume's kind, and
  a folder on a non-removable drive whose kind is unknown or card is treated as `laptop`. A folder
  whose drive is not attached is listed as absent ("That folder's drive is not connected."). A
  folder whose drive is attached but which does not exist yet is shown present (the copy creates it).
- **The NAS pool** when `jobs_pool_root` is set: labelled "NAS pool", copies go into
  `<pool>/<field_pool_folder>`. Its reachability is checked with a 2.5-second time limit (a dead
  network share can otherwise hang for half a minute): "The NAS pool cannot be reached from here."
- **Pool identity check**: the pool directory is accepted when it contains a `.ccsync-pool` marker
  file. On macOS and Linux it is otherwise always accepted. On Windows without the marker:
  - a local disk is refused: "That drive is a local disk, not the NAS pool (a drive letter can change
    hands). Put an empty .ccsync-pool file in the pool's top folder to say it is the pool."
  - a mapped network drive whose network path does not start with `field_pool_unc` is refused:
    "That drive is <\\server\share>, not the NAS pool (<expected>)."
- Each destination reports free space and capacity (when readable), whether it is ticked, busy, and
  whether its kind was set by "you", the "ledger" or a "guess".

## Field backup: the verdict ("safe to format")

(source: field_mode.py, field_service.py)

- **Which files the verdict waits for** ("judged" files): every original a camera or recorder writes.
  - Always: files the ledger tracks as masters or audio (see "Ledger: what is tracked"), except
    proxies.
  - Never: names starting `._`, names ending `.tmp.<x>`, `.part`, `.partial`, `.interrupted`,
    `.failed`, anything in a proxy folder (`Proxy`, `Proxies`, `SUB`, `THMBNL`) or named `…S03.MP4`,
    and the sorter's skip-list names.
  - Always: a long list of original extensions (video, audio, stills, raw formats, 360 files, HEIF,
    N-RAW `.nev`, ARRIRAW `.ari`/`.arx`, Phantom `.cine`, `.crm`, `.mlv`, `.dv`, `.bwf`, `.rf64` and
    others), plus every media extension the camera-card detector knows.
  - Never: sidecars (`.xml`, `.thm`, `.lrv`, `.lrf`, `.bim`, `.srt`, `.cpi`, `.mpl`, `.bin`, `.dat`,
    `.log`, `.txt`, `.json`, `.ini`, `.db` and others).
  - **Unknown extension**: judged when the file is 1 MiB or larger (fail closed on formats nobody
    listed).
- **A file is safe** when it has a copy on the NAS pool, or copies on two different physical disks
  whose kinds count. Two partitions of one disk, or a folder that is a junction onto a drive, count
  once. Copies on the card itself never count. Copies on `client`, `card` or `unknown` drives never
  count.
- **"Laptop only"**: a safe file whose copies include the laptop and none on an `ours` drive or the
  NAS.
- **Which copies belong to this card**: a copy found in the ledger by name, size and time (within
  3 seconds) is accepted only if:
  - it carries this card's serial (copies made by field backup do) and its path ends with the file's
    card-relative path (or it is on the NAS); a copy carrying a different card's serial is never
    accepted;
  - otherwise its path ends with the file's card-relative path;
  - otherwise, for a file at the card's top level, it sits in this card's own landing folder;
  - otherwise, a NAS copy is accepted wherever it is on the pool (the sorter moves clips into project
    folders).
- **A copy counts only if it is still there**: when the drive holding it is attached, the file is
  checked on disk (size, and time within 3 seconds); a missing or changed file is dropped. A copy on
  a drive that is not attached is believed.
- **Copies made on this computer count at once**, before the ledger knows them (kept in
  `field-local-copies.jsonl`; see below).
- **Verdict states and headlines** (quoted):
  - A folder on the card could not be read: state unsafe, "Not safe to format: <n> folder(s) on this
    card could not be read (<up to 3 names> and <n> more), so nobody knows what is in them/it." Notes:
    "Of the <t> files that could be read, <n> are also short of copies." (when any are short) and
    "Take the card out, put it back and look again. If the folder still will not read, try another
    reader before anything is formatted." This wins over every other answer, including "nothing to
    back up".
  - No judged files: state empty, "Nothing on this card needs backing up (no footage, audio or photos
    on it)."
  - All safe and all on the NAS: "Safe to format: all <t> files are at home."
  - All safe, some laptop only: "Safe to format, but <n> of <t> files rest on the laptop alone. Put
    one on a field drive when you can."
  - All safe otherwise: "Safe to format: all <t> files are on two drives that count."
  - Otherwise: "Not safe to format yet: <n> of <t> files are short (<n> with no copy, <n> with one
    copy)." with the note "Some copies are on drives that do not count (a client's drive, a card, or
    a drive with no kind set)." when relevant.
  - Extra note when the ledger mirror is empty and has never been pulled: "This laptop has not heard
    from the ledger yet, so only copies made here count."
- **Per destination**: "how many of this card's judged files that destination already holds".
- Only destinations currently present are used for the per-destination numbers.
- A verdict is cached for 20 seconds and recomputed sooner when anything relevant changes (a copy
  recorded, a kind set, a destination added or removed, a sync). Only one verdict is computed at a
  time; other polls wait and take its answer.

## Field backup: copying a card

(source: field_copy.py, field_service.py, field_mode.py)

- **Landing folder name**: `<day> <card label>`, where day is the local date (YYYY-MM-DD) of the
  newest file on the card (today if no file has a time). When the label is blank or generic ("NO
  NAME", "Untitled", "EOS_DIGITAL", "NIKON", "LUMIX", "CANON", "SD", "SD Card", "USB Drive",
  "Removable Disk", "Disk", "New Volume", "Card", "DCIM" and the like) the card's serial is used
  instead. Characters not allowed in file names become `_`. The card's own folder tree is kept
  beneath it.
- **Same label, same day, different card**: a hidden `.ccsync-card` marker file holding the card's
  serial is written into the landing folder. If a folder of that name already belongs to a
  different card, the card lands in `<day> <label> <serial>` instead. A folder with no marker is
  taken to be this card's. Failure to write the marker is ignored.
- **Layout**: on a drive `<drive>/FieldBackup/<landing folder>/...`, on the pool
  `<pool>/<field_pool_folder>/<landing folder>/...`, in a configured folder `<folder>/<landing
  folder>/...`.
- **One run per card at a time.** A destination already used by a running copy, or on the same
  physical disk as one, cannot be used by another run.
- **Lanes**: each destination gets a lane. Destinations on different physical disks copy at the same
  time; destinations on the same physical disk copy one after another (the waiting one shows "waiting
  for the other copy on this physical drive").
- Up to 12 finished runs are remembered (older finished ones are dropped); they are lost on restart.
- **Planning each destination** (state "Looking", "looking at what is already there"):
  - Destination root missing: refused "<label> is not there. Plug it in and try again."
  - Free space unreadable: refused "<label> cannot be read. Is it still plugged in?"
  - For each file on the card:
    - nothing at the target path: look in the ledger for a copy of the same name, size and time on
      the same drive under another path, confirmed on disk; if found the file is "already there
      elsewhere", otherwise "copy";
    - same size and time (within 2.5 s) at the target: "already there";
    - smaller file at the target: "resume" (an interrupted copy is finished, not replaced);
    - something else at the target (bigger, or a folder): handed to the copier, which treats it as a
      conflict and never overwrites it.
  - **Room check**: if the bytes to copy plus 256 MiB spare exceed the free space, the lane is
    refused before anything moves: "Not enough room on <label>: <free> free, and this card needs
    <need> more (plus 268 MB kept spare). Nothing was copied there." Other lanes carry on.
- **Checking what is already there** (state "Checking"): each file already present is compared with
  the card. If there is a record that exactly this copy was verified when it was made, a quick check
  is used (size, first 1 MiB, last 1 MiB, and for `.mp4`, `.mov`, `.m4v`, `.braw` the position and
  content of the "moov" index box, compared in full up to 64 MiB, beyond that only its first and
  last MiB). Otherwise the whole file is compared byte for byte ("comparing <file> in full (nothing
  says it was verified)"). A match is counted "already there" and recorded (quick or full); a
  mismatch is a conflict, left alone: "it is already at the destination but does not match the card:
  <reason>. It was left alone." A source with no moov box passes with the warning "the source has no
  moov (index): the clip itself is damaged, not the copy". Running a card again is therefore also a
  way to check its backups.
- **Copying** (state "Copying"): the remaining files go through the same copier the sorter's card
  ingest uses (TeraCopy on Windows when available, with its own verify; the built-in copier
  elsewhere, which reads every file back). Folders are created first.
  - A file the copier verified is recorded `full`.
  - A file copied but not verified by the copier is compared in full against the card; if it matches
    it is recorded `full`; otherwise it is counted "copied but not verified", renamed to
    `<name>.failed` (or `.failed2` … up to 49) and reported: "copied but not verified, and a full
    compare says: <why>. It was set aside as <name>."
  - A file the copier skipped as identical is counted "already identical" and recorded `full`.
  - A conflict is reported "<why> It was not overwritten."
  - A failed file is reported with its reason; a partial file this run wrote is renamed
    `<name>.failed` "so a later run cannot take it for a good copy". Only a file this run wrote (or
    resumed) is ever renamed; anything that was there before is left alone.
  - Up to 40 problems are listed per lane.
- **Stopping conditions**, checked at most every 2 seconds during the lane:
  - Stop pressed: "stopped by you" (state Stopped).
  - The destination root disappears: "<label> was taken out (or went away) during the copy".
  - The drive letter now holds a different drive (serial changed): "<label> is now a different drive
    (its letter changed hands)".
  - The card is no longer among local volumes: "the card was taken out of its reader".
  - Less than 48 MiB free: "<label> is full".
  - These give state Failed (Stopped only for the Stop button) and the message "Stopped: <reason>.
    <n> files are on <label> whole and verified (they are kept and recorded); the rest were not
    copied. A half-written file is never left under its real name by the built-in copier; TeraCopy
    may leave a short one, which the next run finishes."
  - A copier error that looks like a full disk ("no space left", "not enough space", "disk is full",
    errno 28, WinError 112 or 39): Failed, "<label> ran out of room. <n> files are on it whole and
    verified; the rest were not copied. Free some space or pick another drive."
  - A run that cannot start at all: every lane Failed "The copy could not run (see the companion
    log)."; a lane that crashes: "The copy could not run: <error>".
- **Finishing**: state Done when there were no conflicts, failures or unverified files, otherwise
  "Needs a look". Message lists the counts: "<n> copied and verified, <n> already identical, <n>
  already there, quick-checked, <n> left alone (something different is there), <n> failed, <n>
  copied but not verified." or "Nothing to copy."
- **Recording** after each lane (also after a stop): every verified copy of a judged or recordable
  file is recorded, unless the drive's letter now holds another drive ("<label> is now a different
  drive, so nothing was recorded for it." and the lane fails "<label> changed while copying; nothing
  was recorded."). A destination with no volume id (a folder on no known drive) records nothing.
- **Progress numbers**: percentage capped at 99 while running, 100 when Done or "Needs a look".
  Transfer rate is measured over a 6-second window and shown as 0 while verifying. Bytes for the
  "already there" checks count 2 MiB per file.
- While a card is being copied from, the sorter's card reporting treats it as busy, and the drive
  being written is not re-read as a card.

## Field backup: copies this computer made, and the ledger leg

(source: field_mode.py `LocalCopies`, `FieldStore`; field_service.py `_record`, `sync`)

- **Local copies file** (`field-local-copies.jsonl` in the config dir): one line per verified copy
  made here: drive, label, kind, path on the drive, name, size, time, verify level, the card's
  serial, the path on the card, the physical disk, when. Written durably as each lane finishes.
  - An entry is dropped once the ledger mirror holds the same copy (dropped in one rewrite at the end
    of a verdict).
  - Entries older than 30 days are ignored on load (entries with no date are kept).
  - At most 60,000 entries are kept (oldest dropped).
- **Page memory file** (`field-state.json` in the config dir): the last ticked destinations, the
  folders added on the page, and the kinds a person set. A damaged file reads as empty.
- **Outbox**: each lane's verified copies of ledger-recordable files are added to the ledger outbox
  with tool name `field`, but only for a destination on a drive with a serial (drive and folder
  destinations). Copies to the NAS pool are kept locally but not sent from here (the pool is not
  recordable from this page).
- **Ledger sync** runs:
  - when a run finishes;
  - when the page polls and the last attempt was more than 300 seconds ago and no copy is running;
  - when "Send and refresh now" is pressed.
  Only one at a time. It delivers the outbox, then pulls the ledger mirror for every attached drive's
  volume id and the pool, keeping away drives in the pull unless their kind is `card`.
- **Sync results** shown on the page: online or not; "No dashboard is set up on this computer.";
  "The dashboard could not be reached. Copies are kept here and sent when it can."; "The ledger was
  not refreshed: <error>"; "Could not sync: <error>".

## Ledger: what is tracked

(source: ledger_scan.py `Rules`)

- The rules come from the dashboard (the footage sorter's rule set sent with each scan); for any rule
  the dashboard does not send, or sends malformed, a built-in copy is used:
  - **Master extensions**: braw, r3d, ari, mxf, mov, mp4, m4v, mts, m2ts, avi, crm, dng, arw, cr3,
    nef, insv.
  - **Audio extensions**: wav, bwf, aif, aiff, mp3, m4a, flac.
  - **Proxy video extensions** (kept only inside a proxy folder): mov, mp4, m4v, mxf, avi, mts, m2ts,
    mkv, webm.
  - **Proxy folders**: `proxy`, `proxies` (any case).
  - **Skipped folders** (never entered): `CacheClip`, `OptimizedMedia`, `_sorter_test`, `THMBNL`,
    `dupe-quarantine`, `$RECYCLE.BIN`, `System Volume Information`, `#recycle`, `.git`,
    `node_modules`, `__MACOSX`, `.Spotlight-V100`, `.Trashes`, `.fseventsd`, `lost+found`,
    `.recycle`, `@eaDir`.
  - **Skipped names**: ending `.part`, `.partial`, `.interrupted`, `.failed`; starting `._`; matching
    `.tmp.<something>` at the end. A file with no extension is never kept.
- A file is kept when its extension is a master or audio extension anywhere, or a proxy video
  extension inside a proxy folder.
- The same built-in rules are used by field backup to decide which files the ledger tracks (field
  backup adds Sony's `SUB` and `THMBNL` folders and `…S03.MP4` names as proxies).

## Ledger: the drive scan job ("ledger-scan")

(source: ledger_scan.py)

- A fleet job kind `ledger-scan`: the dashboard asks this computer to list every tracked file on one
  of its drives (or on named folders of it) and upload the listing; the dashboard works out what is
  new, replaced, gone or back. Which job kinds the computer offers and when it runs one belong to the
  jobs runner (not in this part).
- **Fetching the job**: `GET <dashboard>/sorter/agent/ledger/scan/<job>` (60 s timeout) returns the
  volume id, the roots to scan, the rules, an optional `attempt` token and an optional chunk size.
  - Unreachable: the job fails, retryable ("could not fetch the scan manifest (...)").
  - 404, 409 or 410: fails, not retryable ("the sorter has no scan for this job (HTTP n)").
  - Any other non-200: fails, retryable.
- **Which drive**: the job's `serial` input, else the serial in a `vol:<serial>` volume id. The drive
  is found among attached volumes by serial (never by letter).
  - Drive not attached: a "finish" is posted with reason "the drive is not plugged in here" and the
    job fails, not retryable ("the drive <serial> is not plugged into this computer").
  - **System drive**: never scanned from its root. Only named sub-folders are scanned; if the job
    names only the root, a finish is posted with reason "the system drive is only scanned through a
    watched folder, never from its root" and the job fails, not retryable.
- **Roots**: relative, `/`-separated folders on the drive; empty means the whole drive. A root that
  is absolute, starts with a drive letter, or contains `..` is ignored with a warning. If roots were
  named and none is safe, the scan is refused: "none of the scan's roots is a safe folder on the
  drive" (not retryable). No roots named at all means the whole drive.
- **The walk** is read-only: folders are listed and their entries' sizes and times read; no file is
  opened, hashed, written or locked. Paths are relative to the drive root (never a drive letter).
  - Depth first. Skipped folders are not entered.
  - Symbolic links, junctions and other reparse points are not followed and not counted as failures
    (they are counted as "links"). An entry whose link status cannot be told is not entered.
  - Windows: long paths beyond 260 characters are listed (extended-length paths).
  - A folder that cannot be opened, or an entry that cannot be read, is noted as unreadable (the
    folder's path). A folder that simply does not exist is not a failure.
- **Upload**: rows `[path, size, mtime in ms]` are sent in gzip-compressed chunks to `POST
  .../scan/<job>/chunk` `{rows, seq, attempt?}`; 5,000 rows per chunk by default, or the job's own
  figure when it is between 100 and 10,000.
  - Each chunk is tried up to 5 times, waiting 3, 6, 9, 12 seconds between tries; retried on
    transport failure, 429 or 5xx, always with the same sequence number (so the dashboard applies it
    once).
  - Any other refusal ends the scan: "the dashboard refused scan chunk <n> (HTTP n)" (retryable only
    for 401 or 403). Exhausted retries: "scan chunk <n> could not be delivered (...)" (retryable).
- **Progress**: every 2 seconds `POST .../scan/<job>/progress` with files done, bytes seen, a
  smoothed bytes-per-second figure, the current folder and folders visited. If the dashboard answers
  409, this attempt is stale and the scan stops ("this scan attempt is no longer current (the server
  gave the job to a newer attempt)"). Other progress failures are ignored.
- **Drive presence**: checked at most every 5 seconds between folders, and after a folder fails to
  open. The drive is "gone" when its root folder is missing or no attached volume has its serial (a
  reader's letter can stay after the card is pulled). If the volume list cannot be read, the drive
  is assumed present.
- **Stopping**: a stop request from the jobs runner, a stale attempt, or the drive going stops the
  walk ("the drive is gone"). Rows already gathered are still sent.
- **Finish**: `POST .../scan/<job>/finish` `{files, bytes, complete, reason?, unreadable?,
  unreadableCount?, attempt?}`, tried up to 4 times 3 seconds apart; 404, 409, 410, 401 or 403 stop
  the retries with a warning.
  - `complete` is true only when the walk was not stopped and the drive did not vanish. Unreadable
    folders do not make it incomplete; they are listed (up to 200, relative to the drive root, ""
    meaning the whole drive) so the dashboard does not mark files under them as gone.
  - If more than 200 folders were unreadable, `complete` is false with reason "<n> folders could not
    be read (more than can be listed)".
  - Reason text is cut to 200 characters.
  - A scan that failed with an error still posts a finish with `complete: false` and that reason.

## Ledger: the outbox (copies not yet delivered)

(source: ledger_outbox.py, app.py)

- **File**: `ledger-outbox.jsonl` beside the companion log (normally `~/.ccsync`), or at the config
  key `ledger_outbox_path`. One line per copy with the time it was queued.
- **What goes in**:
  - verified copies made by the field backup page (tool `field`);
  - verified copies a `drive-copy` job made to a local drive whose receipt could not be delivered
    (tool = the copier's name, verify level `full`, the copy's time read from the file on disk;
    unverified copies and copies to the pool are not queued). This path is used by the jobs runner
    and only when `sorter_ledger_enabled` is on.
- A copy record holds: the drive's serial, label and (optionally) its kind; the path relative to the
  drive; file name; size; time (ms); verify level `listed`, `quick` or `full` (anything else becomes
  `listed`, missing becomes `full`); the tool; when.
- Refused on entry (silently dropped): no serial, no path, a path containing `..`, a negative or
  unreadable size. A copy already waiting with the same drive, path, size and time is not queued
  again.
- **Cap**: 200,000 waiting copies; beyond that new copies are not queued and a warning is logged.
- A damaged line (for example a power cut mid-write) is skipped, never fatal.
- **Delivery**: `POST <dashboard>/sorter/agent/ledger/copies` `{copies, machine}` with the fleet
  token and the person's identity token, 500 copies per request, 30-second timeout.
  - 200: the batch is removed (the file is rewritten after every 20 delivered batches and at the
    end, so a crash can cause a re-send, which the dashboard counts as duplicates).
  - 400, 413, 422: the batch is moved to `ledger-outbox.rejected.jsonl` beside it and delivery
    carries on.
  - Anything else (no answer, redirect, 401, 403, 404, 408, 429, 503, 5xx, unknown): delivery stops
    and everything is kept.
  - No dashboard URL or token: nothing is sent.
- **Background flusher** (runs when `sorter_ledger_enabled` is on, default on; a string value of `0`,
  `false`, `no`, `off` or empty is off): every 60 seconds, if anything is waiting, delivers it. After
  a 404 or 503 it waits 10 minutes before trying again.
- **Rejected copies are retried when the dashboard is upgraded**: the flusher remembers the last
  dashboard version it saw in `ledger-outbox.version`; when the version changes (not on first
  sight), every rejected copy is put back in the outbox and the rejected file is emptied.
- The field page's own sync delivers the outbox whatever `sorter_ledger_enabled` says.
- The field page's "waiting to send" count reads the outbox; the count is re-read only when the file
  changes.

## Ledger: the offline mirror

(source: ledger_mirror.py)

- **File**: `ledger-mirror.sqlite` beside the companion log (normally `~/.ccsync`), or at the config
  key `ledger_mirror_path`.
- **Pull** (only from the field page's sync): `GET
  <dashboard>/sorter/agent/ledger/mirror?volumes=<ids>&since=<cursor>` with the fleet token and
  identity token, 60-second timeout, up to 400 pages per pull. Pages continue while the dashboard
  says there is more (or, when it does not say, until an empty page) and the cursor moves.
  - Answer rows may be a list of objects or a column list plus row arrays.
  - A row without an id, volume, path or size is skipped. A row marked gone or deleted, or missing
    (not found by the last scan), is stored but never answered as a live copy.
  - Rows are stored by the dashboard's row id, so pulling twice changes nothing and a changed row
    replaces the old one.
  - The dashboard may also name volumes (label and kind); these are remembered and used by field
    backup to label drives and decide their kind.
- **Which volumes are pulled**: every volume id attached now (and the NAS pool), plus volumes pulled
  before that are away, as long as they were seen in the last 60 days and are not camera cards. At
  most 150 volume ids in total (the most recently seen away volumes win).
  - A volume new to the set is first caught up from the beginning on its own, then the shared cursor
    continues for all.
  - Rows of volumes no longer in the set are deleted, but only after the dashboard has answered.
  - An unreachable dashboard leaves the mirror as it was; pages already applied are kept.
  - No dashboard URL or token: "no dashboard is configured".
  - An unreadable mirror file: "the mirror file cannot be read (<error>)".
- **Lookup** (no network): live copies with the same lower-cased name and exact size, and time within
  3 seconds when both have one.
- **Status** reported to the field page: number of rows, cursor, volumes, when last pulled.

## Timeline Cards agent role: what it is and when it runs

(source: timeline_cards_role.py, app.py)

- **What it does**: lets this computer's DaVinci Resolve serve the Timeline Cards page (the
  card-based editing page hosted by the dashboard). The companion loads the Timeline Cards engine
  from a separate MulticamPipeline checkout on disk, hands it the companion's own Resolve connection,
  and runs the engine's two loops: a "push" loop that posts what Resolve is showing, and a "pull"
  loop that long-polls the dashboard for edits to apply and posts their results.
- **DORMANT by default**: config `cards_agent` (default `false`) turns it on.
- The role object is built on every computer at start-up (so the diagnostics can say why it is not
  running) and started when the companion starts; stopped when the companion quits ("no longer
  serving the page from this machine").
- **Settings**:
  - `cards_agent` (default off): the switch.
  - `jobs_mulcam_pipeline`: the MulticamPipeline checkout folder the engine is loaded from.
  - `cards_vault_root`, else `jobs_vault_root`: the vault folder the engine serves.
  - `dashboard_url` and `dashboard_token`: the dashboard and fleet credential (the token is re-read on
    every call, so a new sign-in takes effect without a restart).
- **Refusals, checked in this order** (each sets a state and a sentence, quoted):
  1. `disabled`: "cards_agent is not set in ~/.ccsync/config.toml"
  2. `no_dashboard`: "this companion has no dashboard to long-poll. Sign in from the tray and this
     computer will pick the page up on its own within a minute"
  3. `halted` (a fleet halt is active, or the halt check fails): "syncing is stopped by your admin,
     so this computer is not taking work of any kind". A halt prevents a START only; a role already
     running is not stopped by a halt.
  4. `no_checkout`: "jobs_mulcam_pipeline is not set, so there is no Timeline Cards engine to run"
  5. `no_vault`: "jobs_vault_root is not set, so the engine has no vault to read"
  6. `standalone_agent`, another Timeline Cards process is driving Resolve here: "a Timeline Cards
     process is already driving Resolve here: <name> (pid <n>): <command line, shortened in the
     middle>. Close the standalone Timeline Cards agent and this computer picks the page up within a
     minute". The other process is never killed.
  7. `standalone_agent`, the process list could not be read: "another Timeline Cards process may be
     running here and this computer's processes could not be listed, so the companion is not
     starting the role" (cannot tell is treated as running).
  8. Engine problems when loading (state `no_engine` unless said):
     - "no MulticamPipeline checkout at <path> (set jobs_mulcam_pipeline in ~/.ccsync/config.toml)"
     - "<path> is not a MulticamPipeline checkout (no multicam_pipeline/cards in it)"
     - "the Timeline Cards engine at <path> could not be imported (<error>)" (expected in a packaged
       companion that lacks the engine's own dependencies)
     - "this Timeline Cards checkout has no bridge contract: its ResolveEngine still owns a Resolve
       connection of its own, which cannot run beside the companion's. Update the checkout to one
       that defines BRIDGE_CONTRACT_VERSION = 1."
     - `old_engine`: "this Timeline Cards checkout implements bridge contract <n> and this companion
       speaks 1, so one of the two needs updating."
     - "this Timeline Cards checkout has no SyncEngine/ResolveEngine"
     - `old_engine`: "<class> says it speaks bridge contract <n> but takes no `bridge` argument.
       Update the checkout."
     - any other failure: "the role could not start (see the log)"
- Each refusal sentence is logged once per change (a warning for the standalone-agent case, info for
  the others).
- **Detecting a standalone agent**: lists every process's command line (Windows: PowerShell CIM query;
  macOS: `ps`), 30-second time limit, re-run at most every 60 seconds. A process whose command line
  mentions `reorder_web.py` or `multicam_pipeline` and contains `--agent` or `reorder_web.py` counts.
  A listing that exits with an error is "cannot tell". Linux: always "cannot tell", so the role
  never starts on Linux.
- Before importing the engine the companion makes its separately shipped LGPL libraries importable
  (psycopg2) and adds the checkout folder to the end of the import path.
- **Watchdog** (only on computers with `cards_agent` on): every 60 seconds, if the role is not
  running (or one of its loops has died), any dead role is taken down (its engine stopped) and a
  start is tried again. So signing in, closing a standalone agent, or a halt expiring brings the role
  up by itself within about a minute.
  - After 5 failed starts in a row (an error, not a refusal) the watchdog stops trying until the
    companion restarts, logging "the role has failed to start 5 times in a row: not trying again
    until the companion is restarted".
- **A loop that dies** is logged ("the push loop stopped: <error>" or "the <which> loop returned --
  the page will not update until the companion restarts") and reported; the watchdog then replaces
  the whole role.

## Timeline Cards agent role: talking to the dashboard

(source: timeline_cards_role.py)

- All engine traffic goes through the dashboard's tunnel, never directly to the Timeline Cards
  server:
  - `POST <dashboard>/cards/agent/state`: what Resolve is showing. The computer's name is added as
    `machine`.
  - `GET <dashboard>/cards/agent/pending?wait=<s>`: long poll for work, capped at 25 seconds.
  - `POST <dashboard>/cards/agent/result`: the result of an applied edit.
  - Any other route the engine asks for is refused locally ("no such agent route").
  - Headers: the fleet token and the person's identity token. Any `token` in the engine's body or
    query is dropped (the Timeline Cards secret is held by the dashboard).
- A non-200 answer becomes an error the engine's loops back off from: "the dashboard answered HTTP
  <n> for <route>: <detail>".
- **A replaced client gets no work**: when the role has been restarted, a leftover loop of the old
  engine is refused before and after each call ("this Timeline Cards client has been replaced; it
  takes no more work"); an answer arriving for it is dropped with a warning.
- **"Not in an episode"**: when the dashboard answers 200 but says this person is in no Timeline
  Cards episode (`attached: false`, a `note`, or an error containing "is not in a timeline cards
  episode"), the push is counted as discarded: logged once per change as "the dashboard is discarding
  this computer's pushes: <sentence>" and shown as the health detail; "the dashboard is taking this
  computer's pushes again" when it clears. Any other `error` in a 200 (an engine refusing one
  request) is logged at info once per change.
- **What is remembered for reporting**: the last time the dashboard answered 200, the last HTTP
  status, the last error, and from each state push the timeline and project names.

## Timeline Cards agent role: health and reporting

(source: timeline_cards_role.py)

- **Health word** (the fleet grid goes green only on `running`), in order:
  - `refused`: the role never started; detail = the refusal sentence.
  - `stopped`: a loop died or no loop is alive; detail = what killed it, or "the push and pull loops
    are no longer running".
  - `credential_refused`: the dashboard last answered 401 or 403; detail "the fleet credential is
    refused: sign in again from the tray".
  - `unreachable`: every call so far failed; or no successful answer within 50 seconds (two long
    polls); or, before any answer, more than 30 seconds since the start. Detail = the last error, or
    "the dashboard has not answered this computer's Timeline Cards loops".
  - `stopped` with the gate sentence if the state is somehow not running.
  - `running`: detail "serving <vault> to <dashboard>", or the "not in an episode" sentence.
- **Report block** sent with the machine report (`capabilities.cards_agent`): connected (true only
  when running), health word, detail (cut to 255 characters with "..."), the gate state, last
  successful answer as UTC ISO time, last HTTP status, current timeline name, engine version, when it
  started.
- **Status for diagnostics**: the above plus project name, time of last state push, and the bridge's
  Resolve-lock statistics.

## Timeline Cards agent role: the Resolve bridge handed to the engine

(source: timeline_cards_bridge.py)

- The engine never connects to Resolve itself. It is given:
  - the companion's single Resolve connection (the one guarded against connecting during Resolve's
    launch window); a failed connect is "no Resolve";
  - a readiness check ("may Resolve be talked to now"), which answers yes when it cannot tell;
  - the companion's Resolve API lock, to take around short Resolve calls; each take is timed;
  - edit start and end notices: logged as "applying a <kind> to the open timeline", "the <kind>
    finished (<note>)", or a warning "the <kind> failed: <note|no reason given>". The companion never
    refuses an edit;
  - a fast list of the current timeline's clips read from Resolve's project library database instead
    of the API (no lock held). It answers "ask Resolve yourself" when the library cannot be read,
    when the answer is about a different timeline than the engine asked for, or when any clip came
    from the slow API walk rather than the library.
- **Slow lock warning**: a lock take of 0.5 seconds or more logs "cards: <name> held the Resolve lock
  for <n>s -- the watcher and the tray queue behind it", at most once a minute.
- **Lock statistics** kept since start and shown in diagnostics: number of takes, total, longest (and
  by whom), mean, number of edits, the edit in progress.
- Bridge contract version: 1.

## Drives: how the companion lists this computer's volumes

(source: sorter_cards.py `list_volumes`)

- Shared by card reporting, the volume report, field backup and the ledger scan.
- Each volume: serial, label, drive, root, capacity, free space, removable or fixed, file system,
  whether the operating system lives on it.
- Three scopes: "removable" (card readers only), "local" (removable and fixed), "all" (same set as
  "local").
- **Windows**: drive letters A to Z; removable (and, for local/all, fixed) drives only. Network,
  optical and RAM drives are never listed. The serial is the volume serial in 8 hex digits. An empty
  card reader is skipped silently (the "There is no disk in the drive" system box is suppressed).
  The system drive is the `SystemDrive` letter (default C:).
- **macOS**: every folder in `/Volumes`. Details come from `diskutil info -plist` (10-second time
  limit); removable when it says removable, external or ejectable; the serial is the volume UUID
  without dashes. The startup disk (the `/Volumes/Macintosh HD` link to `/`) is listed for local and
  all scopes as root `/`, with the serial of the Data volume (stable across macOS updates). A volume
  diskutil cannot describe, or with no UUID, is skipped. `diskutil` answers are reused for 8 seconds
  (the startup disk's for the life of the process) and forgotten when a volume is ejected.
- **Linux**: no volumes are ever listed (so no card reporting, no volume report, no field backup
  drives and no ledger scan on Linux).
- Capacity and free space read for each; 0 when unreadable.

## Camera-card detection

(source: sorter_cards.py `classify`, `list_card`)

- Detection is by what is on the volume, never by drive letter. In order of precedence:
  1. **Sony**: a `PRIVATE/M4ROOT/CLIP` folder exists (even an empty Sony card counts).
  2. **Drone**: a `DCIM` folder with a `NNNMEDIA` sub-folder (three digits then MEDIA) holding an
     `.mp4` or `.mov`.
  3. **Blackmagic** (`bmcc`): a `.braw` file in the volume's top folder (not a `._` file).
  4. **Audio**: a `.wav` in the top folder whose name (without extension) matches `*Wireless PRO*`
     or six digits, underscore, three digits.
  5. **Generic**: anything else that holds a media file (video, audio or photo extension) within
     four folder levels, ignoring skipped folders and dot-folders. A volume with no media is not a
     card at all.
- A **fixed** (non-removable) volume is a card only for kinds 1 to 4, never `generic` (so an internal
  disk full of footage is not a card, and CFexpress Type B and Blackmagic SSD readers, which appear as
  fixed disks, still work).
- The system disk is never a card.
- **Listing a card** (read-only): every file with its card-relative path, size and time. Skipped:
  folders `$RECYCLE.BIN`, `System Volume Information`, `#recycle`, `.git`, `node_modules`,
  `__MACOSX`, `.Spotlight-V100`, `.Trashes`, `.fseventsd`, `lost+found`, `dupe-quarantine` and any
  folder starting with a dot; files `.DS_Store`, `Thumbs.db`, `desktop.ini`, `sync.ffs_db` and any
  starting `._`. For every `.xml` the first 4,096 bytes are read; for every `.wav` its duration is
  read from its header.
- A folder or entry that cannot be read is logged as a warning ("cannot read <path> (<error>); the
  listing is partial") and listed as unreadable; the card listing then says so. (An entry whose name
  would be skipped anyway does not count.)

## Camera-card reporting to the Footage Sorter

(source: sorter_cards.py `SorterCards`)

- A background loop that tells the dashboard's Footage Sorter which camera cards are in this
  computer's readers, with their full file listings, so the sorter can decide where the footage
  goes.
- **Settings**: `sorter_cards_enabled` (default on; strings `0`, `false`, `no`, `off` or empty mean
  off); `sorter_cards_scan_seconds` (default 10, minimum 1): how often the readers are looked at.
  Needs `dashboard_url` and `dashboard_token`; without them it does nothing.
- **Each look**: lists local volumes (removable and fixed), skipping the system disk and any card
  being copied from. A card's listing is re-read only when its root, capacity or free space change,
  or after 300 seconds. A volume that is not a card yet is looked at again on each of the next 6
  looks before "not a card" is believed for 300 seconds (a card can mount before its files are
  readable). A volume being written by a copy is not re-read. A card being copied from keeps its last
  listing in the report.
- The time each card was first seen is kept for as long as it stays in.
- **Posting**: `POST <dashboard>/sorter/agent/cards` `{cards, machine}` with the fleet token and the
  person's identity token, 60-second timeout. Each card: serial, label, drive, kind, capacity, free,
  first-seen time, files, xml texts, wav durations, and the unreadable list only when not empty. The
  full current set is sent when it changes (a card in or out, or a card's file count or total size
  changes) and every 5 minutes while any card is present. An empty set is sent once when the last
  card goes.
- **Answers**: no answer: try again in 30 seconds. 404 or 503 (a site with no sorter): wait 10
  minutes, logged only at debug. 401 or 403: warning "the dashboard refused this computer's card
  report (HTTP n)" and wait 5 minutes. Any other non-200: wait 60 seconds.
- **Busy cards**: while a card is being copied from (by a card-ingest job or field backup), nothing
  else reads it; its last listing is reported. The last root each serial was seen at is remembered
  for the copy jobs.

## Drive (volume) reporting to the ledger

(source: sorter_volumes.py)

- A background loop that tells the dashboard's ledger every drive plugged into this computer (card
  readers and fixed drives), so the ledger can show new drives, track which are visible where, and
  queue a ledger scan when a tracked drive appears.
- **Settings**: `sorter_ledger_enabled` (default on; same string rule); `sorter_ledger_volume_seconds`
  (default 10, minimum 1): how often drives are looked at. Needs `dashboard_url` and
  `dashboard_token`.
- **Left out of the report** ("virtual" drives):
  - serial blank, `00000000`, `FFFFFFFF`, or `19831116` (Google Drive for desktop);
  - label that is or starts with "Google Drive", "GoogleDrive", "My Drive", "OneDrive", "Dropbox",
    "iCloud", "Box Drive", "Proton Drive", "Nextcloud", "pCloud", "MEGA", "Sync.com";
  - file system fuse, webdav, vboxsf, virtiofs, 9p, cdfs, udf, afs, nfs, cifs, smbfs;
  - a FAT32 volume of 2 TiB or more.
- Each reported volume: serial (upper case), label, file system, size, free, removable or fixed,
  system drive flag, drive letter. No paths other than the drive letter.
- A volume being copied from is reported as last seen, even if it has dropped out of the listing.
- **Posting**: `POST <dashboard>/sorter/agent/volumes` `{machine, volumes, digest}`, 30-second
  timeout. Sent:
  - on the first look;
  - when the set changes (a drive in or out, relabelled, reformatted, resized, moved letter), but at
    most once every 10 seconds;
  - every 5 minutes regardless;
  - when any volume's free space moved by 1 GiB or 1 % of its size (whichever is larger), at most
    once a minute.
- **Answers**: same back-off rules as card reporting (30 s on no answer, 10 min on 404/503, 5 min
  with a warning on 401/403, 60 s otherwise). A 200 answer listing scans the ledger queued is logged:
  "the ledger queued <n> scan(s) for this computer's drives".

## Fleet path spelling (canonical paths)

(source: canon.py)

- Every Resolve project in the fleet stores media paths in one "canonical" spelling on the
  canonical prefix (config `canonical_prefix`, normally `P:\`), because that is the only spelling
  that works on every machine. The actual tree lives at the config key `local_root` on each machine.
  On the base rig the two are the same and every rule below passes paths through unchanged.
- On macOS the prefix is still `P:\` (Resolve reaches it through its own Mapped Mount preference), so
  a canonical path is a Windows-spelled string that is never handed to the Mac's file system.
- **Comparing**: paths written with a drive letter or backslashes are compared ignoring case and
  separator style (`P:\Projects\x` equals `p:/projects/x`) on every platform; other paths use the
  host's own rules. "Under a folder" requires a separator boundary (`P:\Creators_ClubExtra` is not
  under `P:\Creators_Club`).
- **Canonical to local**: `P:\Projects\X\a.braw` becomes `<local_root>/Projects/X/a.braw` in the
  host's spelling, keeping the file name's case (used for existence checks). No answer when the path
  is not on the prefix or either setting is empty.
- **Local to canonical**: a file at `<local_root>/...` becomes `P:\...` with backslashes on every
  platform (what is written back into Resolve). A file not under `local_root`, or no prefix
  configured, keeps its physical path.
- A bare drive root (`P:`, `P:\`, `P:/`) is recognised as such; any drive-rooted text is recognised
  as drive-rooted even on macOS, where it would otherwise be a legal relative folder name (used to
  refuse such text before it is joined to a folder).
- File-name extraction uses the path's own spelling (a `P:\...\track.wav` shows `track.wav` on a
  Mac, not the whole string).

## Classifying a timeline clip's path

(source: paths.py)

- Every media path on the open Resolve timeline is put in one class (the timeline watcher, outside
  this part, decides what each class triggers):
  - **OK**: under `local_root` and spelled canonically (or no prefix configured); or on the prefix,
    present, with the prefix mapping healthy.
  - **NON_CANONICAL**: under `local_root` but spelled with the local root instead of the prefix:
    plays here, offline on every other machine; fixable by relinking to the canonical spelling.
    Never produced on the base rig or with no prefix.
  - **OUT_OF_TREE**: not on the prefix, not under `local_root`, but the file exists here.
  - **FOREIGN**: not on the prefix, not in the tree, not on disk (another machine's private path).
    Unfixable here.
  - **BAD_PREFIX**: on the prefix, but the prefix itself does not lead to `local_root` (for example
    `subst P:` did not run at login, or points at the wrong folder): a mapping-health problem.
  - **MISSING**: on the prefix, not on disk, but the prefix mapping is healthy (the normal state for
    an original that was never downloaded to a remote editor's machine). An empty path is MISSING.
- **Prefix health check**: whether the prefix resolves to somewhere under `local_root`, cached for 2
  seconds.
  - Windows: the prefix is resolved; a loopback share (`\\localhost\<share>`, `\\127.0.0.1\...`,
    `\\::1\...` or `\\<this computer>\...`) is translated back to its local folder by asking `net
    share <name>` (10-second limit, answer cached 60 seconds, works with any display language). If
    that fails, the prefix and `local_root` being the same folder on disk also counts as healthy.
  - macOS with a drive-letter prefix: healthy when `local_root` exists.
  - A failure of the check itself counts as healthy (no warning storm).
- On a Windows machine with a healthy prefix, a present prefix file is OK without resolving each
  file; only if the prefix check fails is the file itself resolved.
- On macOS a prefix path is checked at its local twin under `local_root`.

## Owner-only permissions on credential files

(source: secretfile.py, and its callers in config.py, identity.py, loopback_guard.py,
ytdl_cookies.py)

- Files that hold credentials (the companion's config file with the fleet token, the machine identity
  file, the loopback token, the YouTube cookies file) are made readable by their owner only. The
  callers apply it to the temporary file before it replaces the real one.
- **macOS and Linux**: permissions set to 0600.
- **Windows**: inherited permissions are removed and only the current user (`USERDOMAIN\USERNAME`)
  gets read and write, in one `icacls` call (15-second limit, no console window).
- Never stops the companion. Failures are warnings naming the file: "could not restrict <file> to
  <user> (...); it keeps the permissions it inherited from your profile directory", "icacls refused
  to restrict <file> to <user> (exit n): <last line>", "could not restrict <file>: neither USERNAME
  nor USERDOMAIN is set, so there is no account to grant it to", "could not restrict <file> to
  owner-only (...); it keeps the default permissions".

## Repairing an unreadable settings folder (Windows)

(source: state_acl.py, app.py)

- At start-up on Windows, the companion checks its own settings folder (`~/.ccsync`) for entries it
  cannot open (a damage left by older installers, which made the licence acceptance be asked again,
  stopped the install log and stopped safety latches from being saved).
- The check tries to list each folder and open each file, looking at no more than 400 entries.
- If anything is denied it logs a warning ("<n> item(s) under <folder> cannot be opened (first:
  <path>) - the signature of the pre-2026-10-07 installer's ACL bug (GL-27). Repairing the folder's
  permissions.") and repairs:
  - the folder: inheritance removed; full control, inherited by everything inside, for the current
    user, SYSTEM and Administrators;
  - everything inside: reset to inherit from the folder (the folder itself is never reset).
  - `icacls` with a 60-second limit for each step.
- Then checks again: "repaired the permissions inside <folder>" or a warning "<n> item(s) under
  <folder> are still unreadable after the repair (first: ...)". Other failures: "could not repair
  <folder>: no USERNAME to grant it to", "could not re-grant <folder>", "could not reset every file
  inside <folder>", "icacls could not run (...)".
- Does nothing on macOS or Linux, or when the folder does not exist. Never stops the companion
  starting.

## Stopping a child process and everything it started

(source: proc_tree.py, callers in jobs_runner.py and ytdl_executor.py)

- Used when the companion cancels, halts or quits work that runs as a separate program which itself
  starts programs: the whisper transcription job (whose worker process holds the GPU) and YouTube
  downloads (whose ffmpeg merge holds the partial files).
- Such children are started as the head of their own process group (Windows: a new process group,
  keeping any existing flags such as "no console window"; macOS/Linux: a new session).
- **Stopping**:
  - Windows: `taskkill /T /F /PID <pid>` (the whole tree, forced, 20-second limit), then the normal
    terminate and up to the caller's wait (10 seconds by default; the YouTube downloader passes 5),
    then a kill and a further 5-second wait.
  - macOS/Linux: SIGTERM to the whole group, terminate, wait; if it has not ended, SIGKILL to the
    group, kill, 5-second wait.
  - A child that has already exited is not signalled. Every failure is swallowed.

## Packaging: the companion executable

(source: build.spec, launcher.py, pyproject.toml)

- **One single-file executable per operating system**, named `ccsync-companion` (`.exe` on Windows),
  built separately on Windows and on macOS (no cross-building). No Linux build is defined.
- **Windowed, not console**: no console window opens on launch.
- **macOS**: a bare executable (not a `.app` bundle), started by a LaunchAgent and living in the menu
  bar. Signed ad hoc by default (required on Apple silicon); signed with a Developer ID when the
  environment variable `CCSYNC_APPLE_DEV_ID` is set at build time.
- **Windows**: the program icon `icon.ico`, and a version information resource (file description "CC
  Sync companion", internal name `ccsync-companion`, original file name `ccsync-companion.exe`,
  version read from the companion's `VERSION`). Python's `python3.dll` is bundled so Resolve's
  scripting library inside the companion never loads a different installed Python.
- No UPX compression (it raises antivirus false positives on a self-updating unsigned exe).
- **Files bundled inside the executable**:
  - the window icon `icon.png`, the Creators Club mark `cc_mark_white.png` (default) and the neutral
    mark `ccsync_mark.png`;
  - the field backup page (`index.html`, `field.css`, `field.js`);
  - the licence `EULA.md` (its version decides whether the licence must be accepted again);
  - the local b-roll indexing prompt `index_clip_v7_compact.md`;
  - the six Resolve menu scripts for "originals on request" ("Bring originals - selected media pool
    clips", "Bring originals - timeline clips between In and Out", "Bring originals - whole
    timeline", "Stop originals - selected media pool clips", "Stop originals - timeline clips between
    In and Out", and their shared helper);
  - the third-party licence texts and notices (the build refuses to run if either file is missing:
    "<file> is missing -- generate it before building: python tools/gen_notices.py --write-texts");
  - the onnxruntime engine files (for the music CLAP audio tower);
  - psycopg2 (an LGPL database driver) as plain replaceable files in a `ccsync_lib` folder rather
    than inside the program archive, so a user can swap it; a user's own copy in `~/.ccsync/lib`
    wins. The build refuses to run without it installed ("psycopg2 is not installed in the build venv
    -- install companion/requirements.lock before building (GL-32)").
- Modules named explicitly so the frozen build has them: watchdog (and its macOS file-events
  backend), Pillow when installed, AppKit/Foundation/objc on macOS, numpy, onnxruntime, pg8000 and
  its helpers (scramp, asn1crypto, dateutil), zstandard and its C backend.
- Left out on purpose: setuptools, pkg_resources, distutils hack, and psycopg2 from the archive.
- **Start-up switches of the executable** (handled before the companion itself loads):
  - `--supervise`: runs as the supervisor that relaunches a companion that died unexpectedly.
  - `--self-test`: imports the whole companion and exits with success or failure (used by release
    steps).
  - Otherwise: records the start attempt first; if the start guard decides to revert to the previous
    build (after repeated failed starts) the process exits at once; then the companion runs.
- **Installed as a Python package**: package `ccsync-companion` version 0.9.91, Python 3.12 or newer,
  command `ccsync-companion` runs the companion.
- **Required dependencies** (always installed, one binary for the whole fleet): watchdog (file
  watching), xxhash (the b-roll content hash), numpy and onnxruntime (music CLAP audio embedding on
  the editor's machine), psycopg2-binary and zstandard (the Timeline Cards engine's project-library
  reads), pg8000 (the timeline watcher's reads of a Resolve project library on PostgreSQL),
  zstandard again (the project library's compressed clip records).
- **Optional extras**:
  - `tray`: Pillow, and on macOS pyobjc-framework-Cocoa (the menu-bar icon, Dock hiding and
    workspace notifications). Turns on the image-based tray icon and, on macOS, the menu bar
    presence.
  - `dev`: pytest and pytest-xdist (running the test suite).
- Package data shipped with a pip install: the b-roll prompt files and the Resolve menu `.lua`
  scripts.
- **Other files at the companion's top level**: `config.example.toml` (a commented example
  configuration; not read in full for this section), `requirements.lock` (hash-pinned dependency
  lock), `README.md`, and `tools/tray_smoke.py` (a developer-only manual check that draws a second
  tray icon for about 5 seconds; DEV ONLY). An untracked `Microsoft/` folder is a PowerShell cache
  left by a test run and is git-ignored.

## Looks redundant or overlapping

- `field_service.enabled()` and `field_server.is_enabled()` are the same check of
  `field_server_enabled`, written twice; `sorter_volumes.enabled()` and `jobs_runner`'s
  `ledger_outbox_enabled()` are the same check of `sorter_ledger_enabled`; `sorter_cards.enabled()`
  and the `OutboxFlusher.enabled` property repeat the same string-tolerant boolean pattern again.
- The ledger outbox is delivered by two independent paths: the background `OutboxFlusher` (every 60
  s, gated by `sorter_ledger_enabled`) and the field page's own sync (on run end, every 300 s while
  the page is polled, and on the button), which ignores that setting.
- Field backup and card reporting both detect camera cards and both list each card in full
  (`sorter_cards.list_card`), each with its own cache and its own re-read rules (field: 30 s; card
  report: 300 s); a card is therefore walked by both loops.
- Field backup's "is this a proxy" rule (`Proxy`, `Proxies`, `SUB`, `THMBNL`, `…S03.MP4`) differs
  from the ledger rules' proxy folders (`proxy`, `proxies`); the ledger also skips `THMBNL` as a
  folder. Field backup keeps three overlapping extension lists (tracked, original, sidecar) on top of
  the ledger's master and audio lists and the card detector's media list.
- The field page's volume list does not apply the volume report's "virtual drive" filter, so a
  cloud-sync drive (for example Google Drive for desktop, which appears as a fixed FAT32 drive) can be
  offered as a field backup destination and pulled into the ledger mirror, while the volume report
  leaves it out.
- The quick verify (first and last MiB plus the moov box) and the full byte-for-byte compare are both
  used for "already there" files, chosen by whether a verified record exists.
- The pool is offered as a field backup destination, but copies there are recorded only locally (not
  sent to the outbox), relying on the NAS-side ledger to learn of them.
- The Timeline Cards role carries its own process probe, watchdog, health vocabulary and lock
  statistics around an engine that lives in another repository and is OFF on every machine by
  default.
- `zstandard` is listed twice in `pyproject.toml` dependencies (`>=0.22,<1` and `>=0.23`) and twice in
  `build.spec` hidden imports.
- Three loops (card reporting, volume reporting, field page) each list all volumes on their own
  schedule (10 s, 10 s, 4 s while the page is open).

## Claims the code does not back

- `field_copy.py` module text says every file "already there" is "QUICK-VERIFIED against the card ...
  and recorded `quick`". The code quick-checks only when a record says that exact copy was verified
  when made; otherwise it compares the whole file and records `full`.
- `field_mode.py` module text says the quick verify is "Never a full read-back"; true of that
  function, but field backup as a whole does full read-backs for unverified "already there" files and
  for files the copier did not verify.
- The field page shows a **"Remove"** button on every folder destination, including folders from the
  config key `field_dest_folders`. Removing only edits the page's own list, so a configured folder
  stays listed after "Remove" (the route answers success).
- `field_server.py` module text says no route takes a path to write to "except add this folder, which
  only a person at this machine's page can send". The route also accepts a POST with no Origin header
  that carries the loopback token (any local program holding the token).
- `ledger_outbox.py` module text says the outbox is at `~/.ccsync/ledger-outbox.jsonl`; it is beside
  the configured log file (or at `ledger_outbox_path`), and only falls back to the config folder when
  neither is known. The same is true of the mirror (`ledger_mirror.py`).
- `ledger_outbox.py` says the outbox "catches a drive-copy whose receipt could not be delivered"; the
  queuing is done by the jobs runner (not in this part) and only when `sorter_ledger_enabled` is on,
  which could not be confirmed here beyond the call site.
- `timeline_cards_role.py` says the role "refuses to start beside a standalone agent" on "one
  machine"; on Linux the process probe always answers "cannot tell", so the role can never start
  there at all (not stated anywhere).
- `sorter_cards.py` says a card report is posted "when it changes"; the change signal is only the
  set of serials, kinds, file counts and total sizes, so a card whose files changed without changing
  count or total size (or whose unreadable list changed) is not re-sent until the 5-minute resend.
- `build.spec` header says "this has NOT been run in this environment. Verify it end-to-end on a real
  Windows/macOS box before shipping", which the rest of the file (dated build fixes) contradicts; the
  note is stale.

## Could not determine

- Who triggers a `ledger-scan` job on this computer, how often, and with what stop conditions (the
  jobs runner, not in this part).
- How the dashboard treats the field page's `kind` sent with each outbox copy, and whether NAS-pool
  copies made from the field page ever reach the ledger (they are not sent from here).
- Whether TeraCopy or the built-in copier is used, and the copier's own conflict, resume and verify
  rules (`card_copy.py`, `teracopy.py`, not in this part).
- The exact loopback token and origin allow-list rules (`loopback_guard.py`, not in this part).
- The Timeline Cards engine's own behaviour (what the push and pull loops send, which edits exist):
  it lives in the separate MulticamPipeline repository.
- What the timeline watcher does with each path class (popup, relink, warning): outside this part.
- `config.example.toml` (950 lines) was not read; defaults above come from the code.
