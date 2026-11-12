# Companion: everything it does with DaVinci Resolve

Terms used throughout:

- **Resolve**: DaVinci Resolve, the video editing program.
- **Scripting API**: the programmatic interface Resolve exposes to outside programs. The companion uses Resolve's own Python module (`DaVinciResolveScript`) and its native library (`fusionscript.dll` on Windows, `fusionscript.so` on macOS).
- **Script server**: the helper process Resolve starts (`fuscript.exe` on Windows, `fuscript` on macOS) that listens on TCP port 1144 and brokers every scripting connection.
- **Media pool**: the panel in Resolve that holds a project's imported clips, organised into **bins** (folders). The top bin is called "Master".
- **Media pool item / clip**: one imported file in the media pool. It has a **File Path** (the original) and, separately, an optional **Proxy Media Path** (a lighter stand-in file used for editing).
- **Relink**: point an existing clip at a different file on disk without changing any edit that uses it (Resolve's `ReplaceClip`).
- **Sync tree**: the shared project folder tree, reached on editor machines through a drive letter (default `P:\`) or, on macOS, a mounted path.
- **Canonical path**: the spelling of a path that every machine in the fleet agrees on (for example `P:\Projects\...`). **Local path**: the spelling this machine actually opens.
- **Project library**: the database Resolve keeps its projects in (PostgreSQL on a server, or SQLite files for a disk library).

## Connecting to Resolve (source: resolve_bridge.py, script_server.py)

- **Where it looks for Resolve's scripting files.**
  - Windows: modules folder `%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules` (falls back to `C:\ProgramData`), library `%PROGRAMFILES%\Blackmagic Design\DaVinci Resolve\fusionscript.dll`.
  - macOS: modules `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules`, library `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so`.
  - Linux: no default; the scripting bridge does nothing unless the environment variables below are set.
- **Environment variable `RESOLVE_SCRIPT_API`**: if already set, the companion uses `<value>/Modules` and leaves the variable alone. If not set, it is set to the parent of the default modules folder.
- **Environment variable `RESOLVE_SCRIPT_LIB`**: if already set, left alone; otherwise set to the default library path above.
- **Bundled Python pin (frozen builds only).** When running as the packaged executable:
  - Windows: if the bundle carries `python3.dll`, sets `PYTHON3HOME` and `PYTHONHOME` to the bundle's unpack folder so Resolve's library loads the companion's own Python instead of whatever Python is installed on the machine. Overwrites any inherited value.
  - macOS: does the same only if the bundle carries `libpython3.12.dylib`, `Python3.framework/Versions/3.12/Python3` or `Python3`; otherwise leaves the variables alone.
  - These two variables are stripped from the environment of every child process the companion starts (upgrades, rclone, opened files and links), because they point at a temporary folder that disappears.
- **Launch-window guard (the rule that protects Resolve's scripting for the whole machine).** Before every attempt to connect, the companion checks the operating system's TCP table (no network connection is opened) and decides one of four states:
  - `absent`: no process listening on TCP port 1144. The companion does NOT connect (connecting here would sit in a roughly 4-second retry loop and hit the server the moment it appears). Quiet; this is the normal state while Resolve is closed.
  - `starting`: a script server is listening but Resolve has not yet connected to it. The companion does NOT connect. It logs once per launch window: "Resolve is starting up (...) -- holding off every scripting call until it has registered...".
  - `ready`: a script server is listening and has an established connection from its parent process (Resolve). The companion connects.
  - `unknown`: the TCP table could not be read, or port 1144 is held by something that is not the script server. The companion connects anyway (fails open).
  - When a launch window ends, one log line says which way it ended: Resolve registered ("script server has its host now -- connecting (held off for N s)"), Resolve went away during launch ("Resolve went away during its launch window ... nothing has connected"), or the probe could not tell ("connecting anyway, which is what the guard fails open to").
  - Every caller asks this question before queueing to talk to Resolve; an answer up to 2 seconds old is reused once the caller gets its turn.
- **Connection itself.** If the guard allows, the companion imports Resolve's module and asks it for the "Resolve" application object. Any failure (import, call, or a None answer) is logged at debug level and treated as "no connection". The companion does not keep a connection between calls; it reconnects for every operation.
- **Only one conversation with Resolve at a time.** Every call into Resolve from any part of the companion (timeline watcher, media pool refresh, tray actions, fix-all, b-roll insert, Timeline Cards role) waits its turn behind a single gate. Other parts of the companion that drive Resolve (the Timeline Cards role) are given a named way to take the same turn.
- **Stuck-call warning.** If a caller has been waiting more than 30 seconds for its turn, the log gets one warning naming which call is inside Resolve, for how long, and who is waiting: "... has been inside Resolve for N s and everything else that talks to it is waiting ... if this does not clear, quit and reopen Resolve". At most one such warning every 300 seconds. Nothing is cancelled; calls keep queueing.
- **Live "what is Resolve doing" status.** A cheap status answer (no Resolve call) reports the call currently inside Resolve, how long it has been there, and, once it passes 30 seconds, that it is wedged. Used by the tray and the reporter.
- **Tray menu courtesy.** Before most Resolve calls the companion waits while the tray's right-click menu is open, so the menu does not freeze.
- **Sweep courtesy.** During long walks of a timeline or media pool, it pauses 2 milliseconds after every 25 clips so the tray stays responsive.

## Telling the editor why Resolve is not connected (source: resolve_bridge.py, resolve_prefs.py)

- **Four disconnection states, each with its exact message:**
  - Resolve in its launch window: "DaVinci Resolve is starting up".
  - No Resolve process found: "DaVinci Resolve is not running".
  - A Resolve process exists but no scripting is available, for less than 600 seconds: "DaVinci Resolve is open but its scripting isn't available right now (starting up or shutting down)".
  - The same state for 600 seconds or more: "DaVinci Resolve is running but isn't accepting scripting connections. Quit and reopen Resolve. If that does not help, also restart the companion (<Quit menu item>, then relaunch it) before reopening Resolve."
- **Process check** used for these messages runs at most once every 30 seconds (cached). If it cannot tell, it assumes Resolve IS running.
- **Advice for an editor whose Resolve is open but not scriptable** (chosen from whether this computer has ever connected, and the scripting preference in Resolve's preference file):
  - Has connected before on this computer: the "Quit and reopen Resolve ... also restart the companion" message above.
  - Never connected, preference readable and set to None (Resolve's default) or missing: explains the preference is None, tells the editor "In Resolve open Preferences > System > General and set 'External scripting using' to Local, click Save, then quit and reopen Resolve.", and adds "Scripting needs DaVinci Resolve Studio, the paid edition. The free edition has no scripting interface, and no setting can add it."
  - Never connected, preference readable and already Local or Network: says it is already set, adds the Studio note, then "If this is Studio, quit and reopen Resolve; if that does not help, also restart the companion...".
  - Never connected, preference unreadable: Studio note plus the preference instruction.
- **"This computer has connected before" marker.** The first successful connection writes a file `resolve_ever_connected` (containing a timestamp) into the companion's state folder. It survives restarts and is never deleted by the companion.
- **Session connection state.** The companion records, after every timeline or media pool read, whether it was connected and why not. Three values: not checked yet, connected, not connected (with reason), plus "ever connected this run". The tray and diagnostics read this; nothing probes Resolve to answer it.
- **Messages from a bridge that did connect but found nothing:** "no project open in Resolve", "no timeline open in Resolve", "no media pool available", "no root folder in media pool". A Resolve call that throws during a walk gives: "Resolve didn't answer. Make sure a project is open, then try again."

## Reading the open timeline (source: resolve_bridge.py, library.py)

- **What is read.** Every clip on every video and audio track of the current timeline: its file path, clip name, media pool id, track type, track number (1-based) and position on the track (0-based), plus the project name and the timeline's unique id.
- **What is skipped.** Generators, titles, adjustment clips, anything with no media pool clip, and anything with an empty file path.
- **Two ways to read, chosen automatically:**
  - From the **project library** database directly (preferred, setting `library_walk`, default on). This sees inside multicam and compound clips: each angle is listed as its own clip with the multicam's id attached. Only the first cut of a multicam on a timeline is expanded; later cuts of the same multicam are dropped. The database read happens without holding the one-at-a-time Resolve gate; only four cheap Resolve calls (project, project name, current timeline, its name and id) are made.
  - Through the **scripting API** (fallback): walks every track and asks each clip for its file path. Multicam and compound clips are reported as the container, not the angles.
- **Fallback conditions** (any one sends the read to the scripting API): `library_walk` is off; the timeline has no unique id (older Resolve build); no project library can be located for the open project; the library could not be opened; a library read failed.
- **Library retry back-off.** After any library failure the companion does not try the library again for 60 seconds. A change to any of the six library settings drops the open library and allows an immediate retry.
- **Fallback logging.** The first fallback of a run is a warning: "library walk unavailable (<why>) -- using the API walk; clicks in other Resolve clients will lag during walks". Repeats are logged at info level at most once every 300 seconds.
- **Library settings (config keys, all read together; changing any one reconnects):** `library_walk`, `library_db_host`, `library_db_port`, `library_db_name`, `library_db_user`, `library_db_password`. Defaults come from the companion's config defaults. (See the project library section for what each does.)
- **Poll cache for the timeline watcher only.** The watcher's every-few-seconds read first takes a cheap fingerprint:
  - API read: project name, timeline name, timeline id, and the number of clips on each track.
  - Library read: project name, timeline name, timeline id, and a counter bumped whenever the library reports it changed, or when 60 seconds have passed since the last real database read.
  - If the fingerprint matches the previous poll, the previous answer is reused.
  - A full read happens at least every 10th poll regardless (about every 30 seconds at the default 3-second interval).
  - Every other caller (tray "Scan whole project", the fixer) always gets a full, uncached read.
  - A second, library-only read is offered to the Timeline Cards role: it returns the library answer or nothing (never falls back to the API walk) and does not count as a watcher poll.
- **Library answer freshness ceiling.** Even if the library says nothing changed, its remembered clip paths are dropped and re-read at least once every 60 seconds, because the library only notices changes when the project is saved.
- **macOS one-time diagnostic.** On the first successful API timeline read of a run on macOS, one log line records how many clip paths came back in drive-letter spelling versus local mount spelling.
- **API detail.** The first time a clip property is read, the companion tests whether this Resolve build supports reading a single property by name; if not, or if it answers None where the full property list has a value, it reads the full property list per clip for the rest of the run and logs one info line.

## Reading the whole media pool (source: resolve_bridge.py, library.py)

- **What is read.** Every clip in every bin of the current project's media pool (including clips never cut into a timeline): file path, clip name, media pool id, project name, bin path (for example "Master/Interviews" is reported as "Interviews"; root clips get ""), proxy path, and proxy state ("1920x1080"-style when the proxy is online, "Offline" when attached but unreachable, "None" when there is none).
- **Skipped:** timelines, compound clips, generators and anything with no file path.
- **Folder depth limit:** bins nested more than 64 deep are not walked.
- **Library first, API fallback,** same rules as the timeline read. The library read always asks whether the library changed (not gated) because callers want the current truth.
- **Proxy details filled in from Resolve for library reads.** The library cannot give proxy path and proxy state cheaply, so after a library read the companion asks Resolve for them, in chunks of 100 clips, releasing the Resolve gate between chunks.
  - Only done when proxy generation is enabled on this machine or `proxy_relink_enabled` is on (default on). Otherwise skipped.
  - For clips under the b-roll archive, the frame count is also read.
  - If the project closes or the clip map comes back empty part way, the whole library answer is thrown away and the API walk answers instead.
- **Finding a clip again by id.** Anything that must act on a clip read from the library finds the live clip by its media pool id. The id-to-clip map is built with one walk of all bins and reused for 60 seconds, but only while the same project (same name and same open instance) is open. A project closed and reopened forces a new walk. A clip that cannot be found is skipped, never acted on.
- **Current project name** is cached for 20 seconds for display uses; any edit to the media pool re-reads it fresh.

## Relinking a clip to a different file (source: resolve_bridge.py)

- **What it does.** Points an existing media pool clip at a new file path. Every timeline use of the clip is kept.
- **Already linked:** if the clip's current path already equals the new path (after normalising case and separators), nothing is done and the answer is "Already linked to <path>".
- **Before the first change of a burst:** takes a save point if one is due (see "Save points and the undo journal").
- **Attempts:** up to 3 tries by default. Success is judged by re-reading the clip's file path, not by Resolve's return value. Between tries it waits 1 second, then 2 seconds.
- **After success:** writes an undo-journal entry (clip name, old path, new path, which feature made the change) and answers "Relinked to <path>".
- **Failure messages:**
  - Every attempt threw: "Resolve didn't answer. Make sure a project is open, then try again."
  - Resolve accepted the calls but the path did not change: "Copied the file in, but Resolve wouldn't relink it. Close the clip's timeline and use <Scan whole project menu item> again."
- **Forced refresh mode** (used to make Resolve re-read a file that changed underneath a clip at the same path):
  - Runs the relink even though the path is unchanged.
  - Success is judged by the clip's frame count or resolution changing.
  - No save point and no journal entry.
  - Answers: changed ("Re-read <path> from disk"); not changed ("Re-read <path>; its geometry did not change"); not changed but some attempts threw, marked "ask again next pass" ("Re-read <path>; Resolve did not answer cleanly").

## Linking and unlinking proxies (source: resolve_bridge.py)

- **Link a proxy:** attaches a given file as a clip's proxy. Takes a save point first if due. Resolve itself checks the pairing (timecode and frame count) and may refuse.
  - Refused: "Resolve wouldn't accept <path> as this clip's proxy" (marked as a real refusal, which the caller may remember).
  - Threw: "Resolve didn't answer. Make sure a project is open, then try again." (marked as a scripting error, which the caller must not remember).
  - No path given or no clip: refused with "no proxy path given" / "no media pool item to relink".
  - Success journals the clip name, the clip's original path, the old and new proxy paths, and answers "Proxy relinked to <path>".
- **Read a clip's proxy state now:** returns the clip's current proxy state, or "" when it cannot tell.
- **Unlink a proxy (undo only):** detaches the proxy. Not journalled. Messages: "this Resolve build cannot unlink proxies", "Resolve refused to unlink the proxy", "Proxy detached".

## Refreshing Resolve's LUT list (source: resolve_bridge.py)

- Asks the open project to re-read its LUT folders (the same as Project Settings, Color Management, "Update Lists"). Does nothing and reports false if Resolve is not running, no project is open, or the Resolve build lacks the call. Triggered by the LUT feature after the LUT library changes on disk.

## Save points and the undo journal (source: resolve_bridge.py, resolve_journal.py)

- **Save point** (taken before the first media pool change of a burst, when due):
  - Saves the project in Resolve (tries the project manager's save, then the project's own save).
  - Exports a rollback copy of the project as `<state folder>/resolve_edits/<project slug>/<YYYYMMDD-HHMMSS UTC>.drp`, without stills and LUTs.
  - Best effort: if Resolve has no export call ("this Resolve build cannot export projects"), refuses (collaboration projects: "Resolve refused to export a backup copy (a project open in a collaboration cannot be exported)"), or the folder cannot be made, the change still goes ahead.
  - Logs "saved <project> and exported a rollback copy to <file> before the <feature> pass", or a warning that there is no rollback copy and the undo journal is the fallback.
- **Every relink and proxy link is journalled** (see resolve_journal section for the files and retention).

## Undo of the last relinks (source: resolve_bridge.py, resolve_journal.py)

- **What it does.** Puts every clip changed in the newest not-yet-undone journal session for the OPEN project back where it was, replaying the entries newest first so a clip changed twice ends at its original path.
- **Choosing the session:**
  - The open project's newest session not already undone.
  - If the open project has sessions but all are undone: "Every clip-path change CCSync made in “<project>” has already been put back."
  - If the open project has none, but another project does and that session names a project: refused with "CCSync has not changed any clip paths in “<open>”. The last change it made was in “<other>”: open that project and undo there."
  - A session that names no project (old format) may be replayed against whatever is open.
  - No sessions at all on this machine: "CCSync has not changed any clip paths on this machine."
  - A session with no entries: "<file name> records no changes."
- **Project mismatch check.** If the session names a project different from the open one (compared by slug): "That change was made in “<A>” but “<B>” is open. Open “<A>” and undo there: replaying it here would re-address clips the two projects share."
- **Per entry:**
  - Relink entries: finds the clip at its new path and relinks it back to the old path (one try, not journalled). If the clip is instead found at the old path, it is counted as "already back". If neither, "skipped".
  - Proxy entries: finds the clip by its original file path (or, failing that, by clip name), then re-links the old proxy or, if there was none, detaches the proxy.
  - Unknown entry kinds are skipped.
- **Result message:** "Put N clip path(s) back the way they were (from <file>)." plus " M were already back." and/or " K could not be undone: those clips are no longer in this project's media pool." If nothing was undone and everything was already back: "Those clip paths were already back the way they were (from <file>): nothing to put back."
- **Marking done:** the session is marked undone only if something was put back, or everything was already back with nothing skipped. A replay Resolve refused can be pressed again.
- If the media pool cannot be read, the pool's own message (or "DaVinci Resolve is not running") is returned.

## B-roll "Send to Resolve" insert (source: resolve_bridge.py)

Triggered by the b-roll web page through the companion's local server (outside this section); the result message is shown in the web page's toast.

- **Modes:** "append" (end of the timeline on video track 1) and "playhead" (at the playhead on the lowest free overlay track). Any other mode: "unknown insert mode '<mode>'".
- **Refusals before doing anything:** not connected (disconnection message), "no project open in Resolve", "no timeline open - create one first".
- **Bin:** clips land in media pool bin `Master/B-Roll/Archive`, created if missing. If Resolve refuses to create it: "Resolve wouldn't create the B-Roll/Archive bin: the project is locked (or open elsewhere in a collaboration). Unlock it and try again."
- **Reuse:** if that bin already has a clip with the same file path (matched by path, also by the path's canonical spelling), it is reused instead of importing again. Otherwise the file is imported into that bin; failure: "failed to import media at <path>".
- **Automatic proxy attach** (Resolve does not attach adjacent proxies to scripted imports):
  - Only if the clip has no proxy yet.
  - Looks for `<folder>/Proxy/<file stem>.mov` or `.mp4` (candidates from the proxy relink feature).
  - Skips an `.mp4` candidate (the 540p browser preview) when the real original file is present on this computer and is not a registered stand-in; logs "not attaching ... that is the browser preview and the real file is on this computer".
  - On success journals a proxy link with no save point (feature name "insert-adjacent-proxy"). On refusal logs that missing embedded timecode in the preview is the usual cause. The insert still goes ahead.
- **Canonical spelling:** for a freshly imported clip, if its canonical spelling differs from the local path, the clip is relinked once to the canonical spelling (feature name "import-canonicalise"); a refusal is logged and the local spelling kept.
- **Append mode:** appends the in-to-out frame range onto video track 1 explicitly (so the timeline's destination track buttons cannot silently drop it). Checks that something actually landed (the returned item has a start, and the track's clip count grew).
  - "failed to append clip to timeline" when Resolve returns nothing.
  - "Resolve reported no error but nothing landed on the timeline. Check the destination track buttons (V1/A1) at the left of the timeline; with the video destination off, an append is silently dropped."
  - Success: "Inserted <clip name> (<N> frames)".
- **Playhead mode:**
  - Reads the playhead timecode (drop-frame aware), falling back to the timeline start. Failure: "couldn't read the playhead position from Resolve".
  - Estimates how many timeline frames the clip will cover, converting from the clip's frame rate to the timeline's (24 fps assumed if unreadable).
  - Picks the lowest track number from V2 upward whose video AND audio tracks are both free over that span; if none, one above the highest existing track. "couldn't read the timeline's tracks" if track counts are unreadable.
  - Adds video and audio (stereo) tracks as needed to reach that number. Failure: "couldn't add a <video|audio> track for the overlay -- is the timeline locked?"
  - Places the clip at the playhead on that track. If it did not land exactly at the playhead, deletes whatever landed and answers "placement failed on V<n> at the playhead -- something already occupies that span, or the track is locked".
  - Success: "Placed <clip name> on V<n> at the playhead" plus " (new track)" if a track was added.
- Any unexpected error: "Resolve didn't answer. Make sure a project is open, then try again."

## Importing downloaded YouTube files into bins (source: resolve_bridge.py)

Triggered by the YouTube auto-import feature (outside this section), which watches `<project>/Youtube/<term>/` folders.

- **Target bin:** `Master/<segments...>` (for example `Master/Youtube/<term>`), created as needed. Each segment matches only a direct child bin, compared after Unicode normalisation (so names from macOS match names Resolve stored).
- **Bin name cleaning:** `/` and `\` become `-`; leading and trailing spaces and trailing dots are removed; an empty result becomes "Untitled".
- **Project check:** if the caller says which project it scanned for and a different project is now open, nothing is imported ("project changed").
- **Refusals that are not charged to the files:** not connected, "no project open in Resolve", "project changed", "no media pool available", "no root folder in media pool", a pool walk that throws.
- **Duplicate check across the whole media pool** (not just the bin), by file path, also matching a second spelling supplied by the caller. Already-present files are reported as "skipped existing". The same file twice in one batch is imported once. If nothing is new: "already in the media pool".
- **Bin creation refused:** "could not create the bin".
- **Import without moving the editor's view:** imports into whatever bin the editor currently has selected, then moves the new clips into the target bin. The editor's selected bin is never changed. If Resolve will not move them, they stay where imported and a warning is logged; nothing is deleted.
- **Verification:** if Resolve returns fewer clips than asked for, the landing bin and the target bin are re-read before any file is called failed.
- **Canonical spelling:** after import, each imported clip is relinked once to its canonical spelling if that differs (best effort).
- **Result:** success, or "Resolve refused N file(s)" listing the failed files (the caller retries a failed file up to three times). ImportMedia throwing: "Resolve didn't answer...".

## Fixing clips that live outside the sync tree ("FIX ALL") (source: fixer.py)

An **out-of-tree clip** is a clip in Resolve whose file is not inside the sync tree, so it will never reach the server or other editors. The fixer copies such a file into the tree and relinks the clip to the copy. The dialog that drives it lives elsewhere (popup); this is what each fix does.

- **Suggested destination by file type** (relative to the sync tree, under the project prefix when one is known):
  - Audio (`.wav .mp3 .aif .aiff .flac .m4a .ogg .aac .opus`): `Audio/Music`.
  - Still images (`.png .jpg .jpeg .tif .tiff .psd .exr`): `B-roll/Stills`.
  - Video and anything else: `B-roll/Editor Added/<editor name>` (editor name "Unknown" if blank).
- **Choosing the project the destination goes under** (first that applies):
  - The project folder in the tree whose name best matches the open Resolve project name, by shared words. Words are lowercase letters and digits; bare numbers of up to 4 digits (years, season numbers) never count. The folder with the most shared words wins; a tie or no match means no match. Result is `Projects/<matched folder>`.
  - Otherwise the configured active project prefix.
  - Otherwise the root of the tree (no prefix).
- **What counts as a project folder:** any folder under `<sync tree>/Projects` (at any depth) that contains a `.ccsync-project` marker file; the search stops descending at a marker and skips hidden folders. Folders the dashboard says are selected are added if they exist on disk even before their marker arrives. Names that differ only in Unicode composition count once.
- **Destination dropdown contents:** the three type defaults (always, even if they do not exist yet) plus every existing folder inside the project prefix (or the whole tree if no prefix), excluding any folder named "Proxy" and everything under it.
- **Refusals before any copy:**
  - Source file missing: "source file not found: <path>".
  - Sync tree location not configured: "CCSync doesn't know where your sync folder is (local_root is not set), so it won't copy anything. <Diagnostics menu route>."
  - Sync tree path invalid: "bad local_root: <error>".
  - Destination outside the sync tree (absolute path, drive letter, `..` traversal, a different drive): "refusing destination outside local_root: <dest>".
  - Destination folder cannot be created, or no free name: "copy failed: <error>".
- **Rehearsal mode** (config key `fixer_dry_run`, default false, read once per run): runs every check above, then stops. Nothing is copied or relinked. Logs a warning at first read: "fixer_dry_run = true: FIX ALL will report its plan and copy NOTHING until that setting is removed from config.toml". Each clip answers "Rehearsal: would copy to <path> and relink N clip reference(s). Nothing was changed." and counts as success.
- **Reusing an earlier copy:** if the destination folder already holds `<name>.<ext>` or `<name> (N).<ext>` with the same size as the source and identical bytes in three 1 MB samples (start, middle, end), and it is not the source itself, that copy is relinked to instead of copying again. The message verb becomes "already copied to". Name matching ignores case on Windows only.
- **Name collision:** the final name is reserved up front by creating an empty file; if taken, tries `<name> (2).<ext>`, `(3)` and so on, up to 10,000.
- **Copy:**
  - Written to a temporary file `<final name>.<process id>-<8 hex>.ccsync-tmp` in the same folder, then renamed into place. Files ending `.ccsync-tmp` are excluded from all syncing (by the sync lanes' filters).
  - Reads 1 MB at a time; if a read takes more than 0.5 seconds the next read halves, down to 64 KB; after 4 consecutive reads faster than 0.125 seconds it doubles back up, to at most 1 MB.
  - Progress is reported after every read, and once at zero before the first read.
  - The skip and cancel buttons are checked before every read.
  - File times and permissions are copied after the data.
  - The original file is never moved, changed or deleted.
- **Cloud placeholder detection (Windows only, by file attributes):** if the source has the offline, recall-on-open or recall-on-data-access attribute (Google Drive, OneDrive, Dropbox online-only files) and the copy then fails, the message is: "Google Drive (or your cloud drive) couldn't download this file. Right-click it in the Google Drive folder → "Available offline", wait for it to finish, then run <Scan whole project menu item> again." Detection never blocks a copy.
- **Copy failure messages:**
  - Permission problem: "Windows wouldn't let CCSync read or write this file. It may be open in another program. Close it and try again." (the same text is shown on macOS).
  - Disk full: "Your disk is full. Free up space and try again."
  - File gone: "The file isn't there any more. It may have been moved or renamed."
  - Network or device not ready: "Lost the connection to the drive this file lives on. Reconnect it and try again."
  - Anything else: "Couldn't copy this file: <error>".
  - On failure the temporary file and the empty reserved name are removed.
- **Before renaming into place:** checks the reserved name is still the empty file it created. If something else wrote to it or removed it during the copy, a fresh name is claimed and the copy lands beside the arrival. If the check itself fails, the empty reservation is removed (only if still empty) and a fresh name is claimed.
- **Verification before Resolve is touched:** refuses to relink, and deletes the copy, if: the copy cannot be checked; the original is empty; the sizes differ ("the copy is N bytes of a M-byte original -- it was cut short"); or the original's size or modified time changed during the copy ("the original changed while it was being copied -- it is still being written. Try again once it has finished"). Message: "Copied <name>, but <reason>. Nothing was relinked and the bad copy was removed." plus "It is still at <path> (...); delete it by hand." if removal failed.
- **Relink:** every distinct clip that uses the file (duplicates collapsed by media pool id, or by object identity) is relinked to the copy, using the canonical spelling of the new path (so it opens on every machine). Each relink goes through "Relinking a clip to a different file" above, with feature name "fix-all". A clip that can no longer be found counts as a failure: "could not find <name> in the media pool".
- **Undo grouping:** one FIX ALL's changes are kept in a single undo-journal session even if copies take longer than the journal's 2-minute quiet gap.
- **Skip this file / cancel all during a copy:** stops at the next read, deletes the temporary file and the empty reservation, relinks nothing. Message: "Skipped by you. The half-copied file was removed. Nothing was relinked." or, if deletion failed, "Skipped by you, but CCSync couldn't delete the half-copied file at <paths>. Delete it by hand." This is a third outcome, neither fixed nor failed.
- **Stop during relinking** (checked between clips, never during one): keeps the copy and reports "Stopped by you. <name> was copied in and N of M clip(s) were repointed at the copy. Run FIX ALL again to finish the rest."
- **Destination that does not sync:** if the destination's first folder is not `Projects` or `Assets`, every result adds " This folder is outside every project, so the copy stays on this computer and will not reach the server or other editors."
- **Final messages:** success "Fixed: copied to <path> and relinked N item(s)"; partial failure "copied to <path> but relink failed for K of N item(s): <reasons>".

## Skip for now (source: fixer.py)

- **"SKIP FOR NOW"** hides one out-of-tree clip from the popup for 30 minutes (keyed by its normalised path). Pressing it again restarts the 30 minutes. Skips are forgotten when the companion exits.
- **"Scan whole project"** clears all current skips first so everything is shown.
- **Skipped-clips record:** every skipped path is also recorded permanently (path, time, how) in `skipped_clips.json` in the companion's state folder. It hides nothing; it is a count shown by the tray and the health report. Capped at 5,000 entries (oldest dropped).
- **Counts offered:** clips currently skipped (within their 30 minutes) and clips ever skipped on this machine.
- **Retired folder ignore list.** A file `fixer_ignores.json` from older versions (which permanently hid whole folders: "ALWAYS LEAVE THIS FOLDER ALONE ON THIS COMPUTER") is no longer honoured. At start-up its folder list is logged once and the file is renamed to `fixer_ignores.json.retired-cr356` (with a timestamp suffix if that name already exists). Never deleted.

## Clean-up of interrupted copies at start-up (source: fixer.py)

- **One walk** of the sync tree (skipping hidden folders) collects every `*.ccsync-tmp` file.
- **Leftover partial copies older than 1 hour** are reported in the log as a warning ("leftover partial copy from an interrupted FIX ALL: <path> (<MB>, last written <time>) -- NOT deleted; remove it by hand once you're sure nothing is using it"). Never deleted.
- **Empty reserved names left by an interrupted copy** are deleted automatically (the only deletion the fixer makes unprompted), only when all of these hold: the temporary file has the process-id name form, it has not been written for 30 seconds, its process id is not this process, and the reserved final file is exactly 0 bytes. A non-empty file is left alone with a log note; a failed delete logs "COULD NOT REMOVE the empty placeholder file at <path> ... delete it by hand ...".

## Timeline watcher (source: watcher.py)

A background loop that reads the open timeline (see "Reading the open timeline") and classifies every clip's path.

- **Interval:** every `poll_interval` seconds (default 3). One failed poll never stops the loop. Each pass stamps a heartbeat a separate watchdog reads to tell a stuck loop from a dead one. Logs "timeline watcher started (poll_interval=Ns)" and "timeline watcher stopped".
- **Drive gate:** if the companion positively knows the sync tree's drive is not present (for example an unplugged external SSD on macOS), the poll does nothing and reports "local root is not available (drive disconnected?)". The open project name is left as it was. If the check cannot answer, polling continues.
- **Ignored projects** (config `ignored_resolve_projects`): if the open project matches one (numbered copies such as "New Doc 1", "New Doc 2" match "New Doc"), the whole poll acts as if no project were open: nothing is reported, prompted or popped up, and the reported project name is cleared.
- **Project change:** the first time a new non-empty project name is seen, a project-changed notice is sent to the rest of the app. A brief disconnection does not count as a change.
- **Connection state:** every poll reports connected or not, with the reason, to the app (used to time a recurring warning). A change of state or of reason is logged once at info level: "Resolve bridge: connected to DaVinci Resolve" or "Resolve bridge: <reason>".
- **Per-clip classification** (the classification rules themselves live in paths.py, outside this section). The watcher acts on each class:
  - **OK:** nothing.
  - **Out of tree:** counted. Unless skipped (see "Skip for now"), the clip (with the open project name attached) is handed to the popup fixer.
  - **Non-canonical** (an in-tree clip stored under this machine's local spelling instead of the shared canonical spelling): offered once to the automatic fix (relink to the canonical spelling). After an offer, the same path is not offered again for 900 seconds. A failed relink re-arms it on the same 900-second cooldown and records the refusal (clip name and path, up to the 200 most recent) for display. A successful relink clears the refusal. Up to 2,000 cooldown records are kept (oldest dropped; a dropped path may be offered again).
  - **Bad prefix** (a clip on the canonical prefix that does not resolve on this machine: the drive mapping is broken): one mapping-health notification per broken episode, carrying the first such clip. Further paths in the same episode are logged: "clip on the canonical prefix does not resolve under local_root either: <path>". When a later poll sees canonical clips resolving again and none broken, it logs "mapping to <prefix> is healthy again -- re-arming mapping-health warnings" and the next break notifies again.
  - **Foreign** (another machine's private path spelling, not fixable here): one tray warning per path for the life of the process.
  - **Missing** (the canonical path resolves but the file is not on this computer):
    - Not counted if the clip is in the b-roll archive and either is a registered stand-in on this machine or has a proxy file on disk beside it.
    - Not counted if (outside the archive) a proxy file exists at the conventional place (`Proxy/<stem>.mov` or `.mp4` beside the original) and Resolve has not already refused that exact proxy file for this clip.
    - These two answers are remembered for 60 seconds per path (memory cleared entirely if over 4,000 paths).
    - Otherwise counted; the first 50 are kept by name and path for display; each path is logged once at debug level ("clip's original is not on this computer and no usable proxy for it is either: <path>"), plus a per-poll debug count.
    - If this machine itself moved that file on the server's instruction (file-move ledger), the clip and the move are handed to the app to offer a repoint.
- **Every successful poll's full answer** is also handed to the VP9 guard (outside this section).
- **Totals after a full poll** (for the tray and the health report): out-of-tree total (including skipped ones), bad-prefix total, missing total, and the time of the scan. Not updated by a poll that ended early (drive out, Resolve closed, ignored project), so the last real answer stays.
- **Questions the rest of the app can ask:** was the last poll connected (unknown until the first poll); the missing clips list (up to 50); the refused non-canonical relinks list.

## Reading Resolve's project library database directly (source: library.py)

The companion can read a project's timelines and bins straight out of Resolve's project database instead of asking Resolve. It only ever reads (every statement is a SELECT; disk databases are opened read-only).

- **Which library the open project lives in** (first that answers):
  - Resolve's own answer about its current database (works on Resolve 20; returns nothing on 21.0.1).
  - Resolve's log file (`davinci_resolve.log` and the previous `.1` file, located by the LUT module): the last line "Current project pointer changed to (<project>) from project library (<library> : <Network|Disk>)" for the open project names the library; lines "postgres project library <name> at <ip> " give each network library's host. A network library with no host line is assumed to be on 127.0.0.1.
  - Config overrides win over both: `library_db_host`, `library_db_name`, `library_db_user`, `library_db_password`, `library_db_port`. A host override alone is enough to try, and implies a PostgreSQL library.
  - If nothing names a library, the library read is not used.
- **Network (PostgreSQL) libraries:** connects with user `postgres`, password `DaVinci`, port 5432 by default (Resolve's own defaults), overridable by the config keys above. Connect timeout 5 seconds; every query has a server-side 5-second limit. Uses the bundled `pg8000` driver; if it is missing, the library read is unavailable.
- **Disk libraries:** finds `Project.db` for the open project at `<Resolve Support folder>/Resolve Project Library/<library>/Resolve Projects/Users/<user>/Projects/<project>/Project.db`, or under `Resolve Project Library/Resolve Projects/...` for the built-in "Local Database". The Support folder is the parent of Resolve's log folder (Windows `%APPDATA%\...\DaVinci Resolve\Support`, macOS `~/Library/Application Support/.../DaVinci Resolve`). Queries are cut off after 5 seconds.
- **Refusals (each makes the companion use the scripting API instead):** the library has no project of that name; the library holds two or more projects with that name (different folders) and cannot tell which is open; the project has no media pool or no root bin; the timeline has no sequence; any connection or query error (one reconnect is tried first); the `zstandard` decompressor is missing (logged once as a warning).
- **Clip paths** are read from the video information table, then the audio table for audio-only clips. Paths stored with a Windows backslash are returned in that spelling even on a Mac.
- **Timeline read:** video tracks then audio tracks in display order, clips in start order. Subtitle tracks are ignored. Titles and generators are not returned but still count for clip positions, so positions line up with Resolve's own list. Multicam and compound clips are expanded into their angles (up to 8 levels deep); each angle notes which multicam it came through. A multicam's angles are expanded only at its first appearance on the timeline. A multicam whose angles cannot be read is returned as itself. Each clip also carries its track's user-given name when it has one.
- **Change detection:** two cheap reads (the project's last-modified time and the newest save counter across its timelines). The first check always reports "changed". A change drops the remembered clip paths.
- **Media pool read:** every clip in the project's own bin tree, with its bin path; clips in other projects' bins are excluded. Proxy path and state are left blank (filled in from Resolve by the bridge).
- **All projects of one library at once** (used by the unopened-projects sweep): one connection reads every project's media pool. Projects whose name appears twice, and projects with no root bin, are reported separately and skipped.
- **Listing every library this computer knows:**
  - Network libraries from Resolve's own list (where Resolve answers) and from every "postgres project library <name> at <ip>" line in Resolve's log (last host per name wins).
  - Disk libraries by walking every `Project.db` under the Support folder's project library, including projects nested in Project Manager folders. Stops after 5,000 folders or 500 projects (logged). Disk libraries kept anywhere else on disk are not found.
- One warning per run if a clip's start position in the database is not a number ("that item sorts to the head of its track").

## Undo journal and save-point bookkeeping (source: resolve_journal.py)

- **Journal folder:** `~/.ccsync/resolve_edits/<project slug>/`. The project slug is the project name with `< > : " / \ | ? *` and control characters replaced by `_`, trailing dots and spaces removed, cut to 80 characters; an empty name becomes `_unknown`.
- **One journal file per burst of edits:** `<YYYYMMDD-HHMMSS UTC>.json`, holding the project name, start time, the rollback copy's path (if any), whether the project was saved, and the entries. A burst ends after 120 seconds with no edit to that project. A FIX ALL holds the burst open across long copies (a burst that had already gone quiet is not revived).
- **Each entry:** time, kind (`replace_clip` relink, `link_proxy_media` proxy link; `unlink_proxy_media` is defined but never written), which feature made it, clip name, the clip's original path, old path, new path.
- **Cap:** 5,000 entries per journal file; further edits in the same burst are made but not journalled.
- **If the journal cannot be written:** the edit still happens; a warning says it "will not be undoable".
- **Save points** are taken at most once every 900 seconds per project.
- **Rate limit for unprompted changes** (automatic canonical relink, automatic proxy repoint; button-driven FIX ALL is not limited):
  - Each (project, feature) may run at most once every 900 seconds.
  - Each project may have at most 8 unprompted passes per UTC day across all features. Further passes are held, counted, and logged as a warning: "<project> has already had N unprompted rewrites today, so this one is held (M held so far) -- this looks like a configuration problem, <diagnostics route>".
  - Both limits are saved in `~/.ccsync/state/resolve_auto.json` and survive restarts. A saved time in the future (clock put back) is treated as now and corrected on disk.
  - If the limiter itself fails, the pass is allowed.
  - A read-only "seconds until the next automatic pass" answer is available.
- **Undo bookkeeping:** a replayed journal is stamped with the time and the number put back, kept on disk, and skipped by the next undo (which moves to the change before). An edit made after an undo starts a new journal.
- **Tray line describing what undo would do:** "N clip path(s) in “<project>”, <start time>" for the newest journal not yet undone (blank if none or empty).
- **Journal ids for the dashboard:** `<project slug>/<file name>`. The machine reports its newest 20 journals (id, project, start time, entry count, which features; never the paths themselves). An id coming back from the dashboard is accepted only if it is exactly two plain parts, ends in `.json`, its slug is a valid slug, and it resolves inside the journal folder.
- **Retention:** journal files, rollback `.drp` copies and leftover temporary files (`*.json.tmp.*`) older than 60 days are deleted:
  - for the project being written to, on every new journal;
  - for every project, 120 seconds after start and then every 24 hours (a background task). An empty project folder unchanged for a day is removed. Logs "swept N file(s) past 60 days and M empty folder(s) across K project(s)" when anything went.

## Undo requested from the dashboard (source: resolve_undo.py)

An administrator can press "UNDO THIS CHANGE" on the dashboard for a change the companion made on this machine; the request arrives in the reply to the machine's report (`commands.resolve_undo`).

- **Accepted request:** a positive numeric id and a journal id; optional project, requester (default "your administrator"), request time. Anything else is ignored.
- **The replay itself** is the same undo as the tray's (see "Undo of the last relinks"), pointed at the named journal.
- **Outcomes sent back:**
  - Journal not on this machine (swept after 60 days, or another computer): failed, "this computer no longer has the record <id>: it has been cleared, or this is not the computer the change was made on".
  - Undo succeeded: done, with the undo's message (or "put the clip paths back").
  - Resolve not connected (any of the four disconnection messages, including "starting up"): retrying, with that message.
  - No project or timeline open, or "make sure a project is open", or "open that project": retrying, with the text "Waiting: there is no project open in Resolve on this computer. CCSync will put the clip paths back on its own the next time that project is open." (A finer state "parked" exists but is only sent if the caller allows it; by default it is sent as "retrying".)
  - Messages containing "is open", "didn't answer", "did not answer", an empty message, or one containing both "resolve" and "not": retrying.
  - The replay raised an error: retrying, "the undo could not run on this computer (<error>)".
  - Anything else: failed, with the message.
- **Ledger:** `resolve_undos.json` in the companion's state folder records each request's outcome, attempt count and first and last times, so a request delivered again after a restart is answered from the record instead of replayed. Keeps the 100 most recent. An unreadable ledger is logged and started empty.
- **Give up:** a request still retrying after 7 days counts as finished (the caller decides what to send).

## Editing Resolve's preference files (source: resolve_prefs.py)

Resolve keeps preferences in two plain-text files that must agree: `config.dat` (the engine's copy) and `.config.data` (the settings window's copy).

- **Where they are:**
  - Windows: `%APPDATA%\Blackmagic Design\DaVinci Resolve\Preferences`.
  - macOS: `~/Library/Preferences/Blackmagic Design/DaVinci Resolve`, or the sandboxed `~/Library/Containers/com.blackmagic-design.DaVinciResolve/Data/Library/Preferences/Blackmagic Design/DaVinci Resolve` if that one holds `config.dat`.
  - Linux: not supported.
  - Environment variable `BMD_RESOLVE_CONFIG_DIR` overrides the folder on every platform.
- **Two absolute rules for every write:**
  - Refused while Resolve is running (status `resolve-running`), because Resolve rewrites both files when it quits.
  - Never creates either file. A missing `config.dat` is `config-missing` with the message "<path> does not exist -- launch Resolve once, quit it, and retry". A missing `.config.data` makes every write `format-unrecognised`.
- **How edits are made:** only the lines being changed are touched; comments, unknown keys, spacing and line endings are preserved. Before writing, both files are backed up beside themselves as `<file>.ccsync-bak-<YYYYMMDD-HHMMSS>` (or a caller-given suffix). Written through a temporary file (`.ccsync-*.tmp`) and renamed, keeping the original file permissions. A no-op change writes nothing and makes no backup.
- **Outcomes:** `ok`, `already-present`, `resolve-running`, `config-missing`, `format-unrecognised`, `io-error`.
- **Is Resolve running?**
  - Windows: an in-process snapshot of running processes, looking for `resolve.exe`; if that fails, runs `tasklist /FI "IMAGENAME eq Resolve.exe" /NH` (20-second limit, no window).
  - macOS: `pgrep -x "DaVinci Resolve"` (20-second limit).
  - Three answers are available: yes, no, cannot tell. The two-valued form treats "cannot tell" as running (so writes are deferred rather than lost).
  - A general "is a process with this name running" check exists too (Windows only; "cannot tell" elsewhere).
- **LUT Locations list** (Preferences > System > General):
  - Read: the configured extra LUT folders in order.
  - Add a folder: appended to the end of the list in both files (an editor's own entries are kept). Already present (compared ignoring case and slash direction): `already-present`. If the two files disagree on how many entries there are: `format-unrecognised`.
- **Media storage list and gallery (stills) location:**
  - Read the media storage list (each entry's number, root, and mapped root).
  - Read where the gallery is kept: the media storage entry it points at, the folder name (default `.gallery`), the local path, and the path as other machines see it (the mapped form, with backslashes).
  - Add a media storage entry for a folder (with an optional mapped root): inserted just before Resolve's own last entry (`/Volumes` on macOS, `ResolveVirtual` on Windows), never touching entry 1, in both files, renumbering later entries. Already present: `already-present` with its number. An empty list: `format-unrecognised`.
  - Point the gallery at a media storage entry and folder (only in `config.dat`; there is no matching key in the other file). Unknown entry: `format-unrecognised`.
- **External scripting preference** ("External scripting using": 0 None, 1 Local, 2 Network):
  - Read: from `config.dat`, else `.config.data`; absent or not a number reads as "not set".
  - Status for the tray's explainer: the mode, its name ("None", "Local", "Network", "not set"), and whether the files could be read.
  - Switch to Local (an install-time action): if both files already say Local or Network, `already-present`; otherwise writes 1 into both files. Refused while Resolve runs. Never creates a file.
- **Detecting Resolve on this computer** (for the installer):
  - Windows: looks for `Resolve.exe` under `%ProgramFiles%\Blackmagic Design\DaVinci Resolve\` (overridable with `CCSYNC_RESOLVE_EXE`), else the registry key `HKLM\SOFTWARE\Blackmagic Design\DaVinci Resolve` (and its `Version`). Reports the Studio edition only if a `.davinciresolvestudio*` licence file exists under `%ProgramData%\Blackmagic Design\DaVinci Resolve\Support\.license`; otherwise edition is unknown (never "free").
  - macOS: looks for `/Applications/DaVinci Resolve/DaVinci Resolve.app` (overridable with `CCSYNC_RESOLVE_APP`). Edition is never detected.
  - Both: whether the preferences file exists (Resolve has been run here), and the version from the preferences folder's `.version` file (`Resolve.Version=`).
  - Other systems: everything unknown.

## Menu items inside Resolve: "originals on request" (source: resolve_menu_install.py, resolve_menu/*.lua)

The companion installs Lua scripts that appear inside Resolve as menu items. Each one writes a request file that the companion picks up (the companion side that reads these requests and brings files down is outside this section).

- **Install location:** `<Resolve user Scripts folder>/Edit/CC Sync/`, where the Scripts folder is:
  - Windows: `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts`.
  - macOS: `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts`.
  - Linux: not supported ("Resolve menu scripts are not supported on this system.").
- **Where they show in Resolve:** Workspace > Scripts > CC Sync (scripts in the `Edit` folder are listed on the Edit page). Resolve shows new scripts after it restarts.
- **Install rules:**
  - Refused if the parent `Fusion` folder does not exist: "DaVinci Resolve does not seem to be installed for this user (<path> is missing)."
  - Each shipped script has the shared body inserted at its marker line, so every installed file stands alone.
  - A file is rewritten only if its bytes differ (atomic write through `<name>.ccsync-tmp`).
  - Lua files in that folder that start with the line "-- CC Sync menu script. Installed and rewritten by the CC Sync companion" but are no longer shipped are deleted. Files without that first line are never touched. Leftover `.ccsync-tmp` files there are deleted.
  - Creates the request folder `~/.ccsync/requests/originals/` ahead of time.
  - Messages (logged): "Resolve menu scripts updated in <folder> (N written, M removed).", "Resolve menu scripts already up to date in <folder>.", or "Could not install the Resolve menu scripts: <error>". A failure never stops the companion starting.
  - The install does not talk to Resolve, so it is safe while Resolve is open.
- **The five menu items (exact names as shown):**
  1. **"Bring originals - selected media pool clips"**: asks for the camera originals of the clips selected in the media pool (action `add`, scope `media_pool`).
  2. **"Bring originals - timeline clips between In and Out"**: asks for the originals of every clip between the timeline's In and Out marks; with no marks, the clip under the playhead (action `add`, scope `timeline_range`).
  3. **"Bring originals - whole timeline"**: asks for the originals of every clip on the current timeline (action `add`, scope `timeline_all`).
  4. **"Stop originals - selected media pool clips"**: asks to stop bringing the originals of the selected media pool clips (action `remove`, scope `media_pool`).
  5. **"Stop originals - timeline clips between In and Out"**: asks to stop for the clips between the In and Out marks, or the clip under the playhead (action `remove`, scope `timeline_range`).
  - There is no "Stop originals - whole timeline" item.
- **What every item does, step by step:**
  1. Finds Resolve from inside the script. If not run from inside Resolve, prints "this script runs from inside DaVinci Resolve (Workspace > Scripts)." and stops.
  2. Gets the open project; none: prints "no project is open." and stops. Reads the project name and the current timeline and its name (timeline may be absent).
  3. Collects clips by scope:
     - **Media pool:** the clips selected in the media pool. None: "no clips are selected in the media pool. Select some and run this again."
     - **Timeline (In/Out and whole):** no timeline: "no timeline is open."
     - **In/Out:** reads the timeline's In and Out marks (video marks, falling back to audio marks; swapped if reversed). Marks are treated as counted from the timeline's start frame, unless that would land past the timeline's end while the raw numbers fit, in which case they are taken as absolute. Every clip on every video and audio track that overlaps that range is collected. None: "no clips from the media pool sit between the In and Out marks."
     - **No marks set:** switches to "under the playhead": the current video clip only. None: "no In and Out marks are set and there is no clip under the playhead." The request records the scope as `timeline_playhead`.
     - **Whole timeline:** every clip on every video and audio track. None: "this timeline has no clips from the media pool."
     - Each clip is recorded once (by media pool id, or by path and name if it has no id), with its file path, id, name and type. Titles, generators and other items without a media pool clip are skipped.
  4. Writes the request as JSON: `{"v": 1, "action", "source" (the scope used), "project", "timeline", "clips": [...], "created_at" (UTC)}` to `~/.ccsync/requests/originals/<milliseconds>-<12 random digits>.json` (via a `.tmp` file then rename). On Windows the home folder is `%USERPROFILE%`, elsewhere `$HOME`. If the folder is missing it tries Resolve's own folder creation, then a `mkdir` command (which may flash a console window on Windows).
  5. Prints to Resolve's console (Workspace > Console), all prefixed "CC Sync: ": success "asked for the originals of N clip(s). The companion will confirm." or "asked to stop bringing the originals of N clip(s). The companion will confirm."; failures "could not find your home folder, so the request was not sent.", "could not write to <folder>, so the request was not sent.", "could not write the request file.", "could not finish the request file (<error>).", or for any unexpected error "something went wrong, nothing was sent (<error>)."
  - No window or dialog is shown; output is only in Resolve's console.

## Script server probe in detail (source: script_server.py)

The launch-window guard described under "Connecting to Resolve" works like this.

- **What it reads (never opens a connection):**
  - Windows: the system TCP tables (IPv4 and IPv6) and a snapshot of running processes (name and parent), all in-process, no child process.
  - macOS: runs `lsof -nP +c 0 -iTCP:1144 -F pcRnT` (5-second limit) and reads process id, command name, parent id, endpoints and states.
  - Linux and anything else: always `unknown` ("no script-server probe on <system>"), so the companion connects as it did before the guard existed.
- **Decision:**
  - No listener on port 1144: `absent`.
  - A listener that is not named `fuscript.exe` or `fuscript`: `unknown` ("port 1144 is held by <name>, not Fusion's script server").
  - A script-server listener plus an established connection to port 1144 from the script server's parent process, or from any process named `resolve.exe`, `resolve` or `davinci resolve` (or a cut-off spelling of those of at least 7 characters), not counting the companion itself: `ready`.
  - Otherwise: `starting`.
  - Any probe error: `unknown` ("probe failed: ...").
- **Caching:** an answer is reused for 250 milliseconds.
- **The same Windows process snapshot** also answers "is Resolve running" for the preferences code and other callers (see "Editing Resolve's preference files").

## Shared LUT library (source: luts.py, resolve_prefs.py)

Makes Resolve use the shared, synced LUT folder `<sync tree>/Assets/Luts`.

- **Feature flag:** config `lut_sync_enabled` (default true). Off: every check reports `disabled` and strays are never looked for.
- **The location string written into Resolve's "LUT Locations" preference:**
  - Config `lut_location_override` if set (wins everywhere).
  - Windows: `<canonical prefix>\Assets\Luts` (for example `P:\Assets\Luts`), identical on every Windows machine.
  - macOS (and anything not Windows): the real local path `<sync tree>/Assets/Luts`.
- **Periodic check** (how often is decided by the caller, outside this section). Each check:
  - If the library folder has not arrived on this machine: status `no-library`, warning "the LUT library <path> has not synced to this machine yet".
  - Reads Resolve's preferences. Failures report the preference error's status and message.
  - If the location is already in the list: runs the stale-index repair (below); status `already-present`.
  - Otherwise adds it (see the preferences section). Results:
    - Added: logs "added <location> to Resolve's LUT Locations", asks a running Resolve to re-read its LUT list, status `ok`.
    - Resolve running: "Resolve is running -- its LUT Locations will be set the next time it is closed (Resolve overwrites its own preferences on exit)".
    - Files not in the expected shape: "Resolve's preference files are not in the expected shape -- add <location> by hand in Preferences > System > General > LUT Locations".
  - Each warning is logged at most once an hour while the status stays the same; a status change resets this.
- **Stale LUT index repair** (config `lut_index_repair_enabled`, default true; also needs `lut_sync_enabled`):
  - Problem it fixes: Resolve scans LUT locations once at launch; if the drive was not mapped yet, the shared LUTs are missing for the whole session.
  - Reads the last 2 MB of Resolve's log (`%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\logs\davinci_resolve.log` on Windows, `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/logs/davinci_resolve.log` on macOS; config `resolve_log_override` replaces it).
  - Finds the latest "Running DaVinci Resolve" session line and the latest "SyManager.Lut ... <location> : no dir" line for this location. If the "no dir" is from the current session, the session needs repair.
  - Only acts if Resolve is running, the session has not already been repaired by this companion run, and the location is reachable now. Then asks Resolve to re-read its LUT list. If that fails (for example no project open) it tries again on the next check.
  - On success logs "Resolve started at <time> without <location> (it was not reachable yet) -- re-scanned its LUT list". Works while Resolve is open; no restart and no preference change.
- **LUTs only on this machine ("strays"):**
  - Looks in Resolve's own LUT folder (`%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\LUT` on Windows, `/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT` on macOS; config `resolve_lut_dir` replaces it).
  - LUT file types: `.cube .ilut .olut .3dl .dat .mga .cms .lut` (DCTL files are deliberately excluded).
  - A file is NOT a stray if: it is inside the library; the library already has a file of the same name (anywhere) and size; it is Resolve's own factory content (top-level folders and files such as ACES, Apple, Arri, Astrodesign, Blackmagic Design, Canon, DCI, DCTL, DJI, Film Looks, Fujifilm, GoPro, HDR Hybrid Log-Gamma, HDR ST 2084, Leica, Nikon, Olympus, Panasonic, RED, Samsung, Sony, VFX IO, Z CAM, and the stock `.ilut`/`.olut` files; extendable with config `resolve_factory_luts_extra`, comma-separated); or the library already has a file at the exact place it would land.
  - Up to 200 strays are returned, each with its name, size and destination (its path relative to Resolve's LUT folder, so pack folders are kept).
- **Sharing strays into the library ("adopt"):** copies each chosen file into the library (through `<name>.ccsync-tmp`, then renamed). Never overwrites an existing file (counted as skipped), never deletes the original. Refuses any destination outside the library ("<name>: refused, <rel> is outside the LUT library"). A failed copy removes its partial temporary file. Returns copied, skipped and errors. If anything was copied, asks Resolve to re-read its LUT list.

## Shared stills (gallery) location (source: stills.py, resolve_prefs.py)

Points every machine's Resolve gallery (stills and PowerGrades on the Color page) at one shared synced folder so machines sharing a project database agree.

- **Feature flag:** config `stills_sync_enabled` (default true). Off: status `disabled`.
- **Shared folder:** `<sync tree>/Assets/Stills`, gallery subfolder `.gallery`.
- **Media storage entry used:**
  - Windows: root `<canonical prefix>\Assets\Stills` (default prefix `P:\`), no mapped root.
  - macOS: root is the real local path, mapped root `<canonical prefix>\Assets\Stills` so the shared database sees the same `P:\` spelling.
- **Each check:**
  - Shared folder not here yet: `no-library`, warning "the shared stills folder <path> has not synced to this machine yet". (The gallery is never pointed at a folder that does not exist.)
  - Gallery already at that root with folder `.gallery`: `already-present`.
  - Otherwise adds the media storage entry if missing, then points the gallery at it.
  - Success: logs "gallery now points at <root> (media storage entry N)", message "gallery moved to <root>\.gallery" (with `/` on macOS), status `ok`.
  - Resolve running: "Resolve is running -- the shared stills location will be set the next time it is closed (Resolve overwrites its own preferences on exit)".
  - Files not in the expected shape: "Resolve's preference files are not in the expected shape -- add <root> as a media storage location by hand, and set the gallery to it".
  - Each distinct status's warning is logged once per run.
- How often the check runs is decided by the caller (outside this section).

## "Copy this project's media in" (consolidate) (source: consolidate.py, fixer.py)

For a project that existed before the sync system: copies every out-of-tree clip in the media pool into the project folder and previews what the sync lanes would then upload and download. The tray action and dialog that drive it are outside this section.

- **Plan:** the media pool's out-of-tree clips are turned into one copy per distinct file, with the same destination rules as the FIX ALL popup (including a remembered server root for the project), and each file's size. Totals: file count and bytes.
- **Preview against the server (dry runs of rclone, 120-second limit each):**
  - Refused outright if no project folder could be worked out: "no active project resolved -- refusing whole-tree consolidate".
  - Writes filter files `consolidate_filter_up.txt` and `consolidate_filter_down.txt` in the state folder.
  - Upload preview: the same command as lane A (upload of originals) for that project subfolder, with `--dry-run`, against the main remote.
  - Download preview: the same command as lane B (proxy download) for that subfolder with `--dry-run`, through the download route if one is configured, with lane B's minimum-age setting.
  - Reads rclone's final statistics (files, bytes, deletions, deleted folders) and up to 200 sample names of would-be transfers and, separately, would-be deletions.
  - If either preview returned no statistics at all: refused, "the <upload|download> check returned no data from rclone -- refusing to report what it would do (a blank result is not 'nothing to do')".
  - If the download preview would delete any local file or folder: proxy download is marked to be skipped, and a warning is logged. The real proxy download may only run if the preview succeeded and reported no deletions.
- **Report text shown to the editor:**
  - "COPY THIS PROJECT'S MEDIA IN"
  - "Your original files are COPIED, never moved. Everything stays exactly where it is."
  - "  N scattered clip(s) to copy into the project folder (<size>)"
  - "  N original(s) will upload to the NAS (<size>), plus the consolidated clips above once copied in"
  - Either "  N proxy file(s) will download from the NAS (<size>)" or "  !!! WARNING: the NAS proxy sync would DELETE N local file(s)[ and M folder(s)] !!!" followed by "  Proxy download will be SKIPPED for this consolidate -- fix the mismatch on the NAS first, then re-run."
  - If the preview failed: "  (could not check the NAS: <error>)".
  - Sizes are shown in B, KB, MB, GB or TB (1,024-based).
- **Running it:** each planned file goes through the same copy-and-relink as FIX ALL (see that section), one after another.
  - Progress after every read: file number, file name, bytes of this file, bytes of the whole batch, and whether the file is a cloud placeholder.
  - Between files: stop (keeps what is done), and cancel all.
  - During a file: skip this file and cancel all (partial copy removed).
  - Batch bytes count only files really copied (not rehearsals, failures or skips).
  - Final summary: fixed, skipped, failed, rehearsal (rehearsal-mode files), stopped, cancelled.

## Projects nobody here has open (source: unopened_scan.py, library.py)

Finds Resolve projects on this machine's libraries that are not open but contain clips that exist only on this computer, and keeps reminding the editor.

- **Setting:** config `unopened_scan_minutes` (default 30; 0 turns it off). A negative or non-numeric value means the default. When turned off, findings are forgotten and the report goes back to "not checked".
- **Timing:** first run 120 seconds after start, then the thread wakes every 60 seconds, sweeps when the interval is due, and checks whether a reminder is due.
- **Which libraries are read (no Resolve scripting call is made by the sweep itself):**
  - Network libraries: a list from Resolve passed in by the caller, then every library named in Resolve's log, one per name (first wins). If both `library_db_host` and `library_db_name` are set, that library is added first. `library_db_user`, `library_db_password` and `library_db_port` overrides apply to every network library. Missing host means 127.0.0.1.
  - Disk libraries: every `Project.db` found under Resolve's project library folder (see the library section for limits).
  - No libraries found: logged once ("no Resolve project library found on this computer ... nothing to check").
- **Skipped:** the sweep is skipped when the sync folder is not usable or the sync tree location is unknown. Within a library: the project currently open (the watcher handles it), projects in `ignored_resolve_projects`, and project names that appear twice in one library (logged once each: "<library> holds more than one project named <name>; neither is checked").
- **A project is flagged when** at least one of its clips is out of tree by the watcher's rules (which includes "the file exists on this disk"), AND at least one other clip lives in the sync tree under `Projects/` and inside a recognisable project (using the known project folders, else a year/series/project rule). Projects entirely outside the tree are left alone. The count is distinct files.
- **Unreachable library:** logged once as a warning ("cannot read <library> (<why>); skipping it until it answers") and skipped; logged again at info when it answers. If no library could be read at all, the previous findings are kept.
- **Logs:** "N project(s) not open here have clips only on this computer: '<project>' (count); ..." or "clean again (N project(s) checked)".
- **Reminder balloon** (tray notification; title built by the site's notification title helper with "footage only on this computer"):
  - Shown on the first finding, then every 30 minutes while anything is still flagged. Re-armed once nothing is flagged. Only shown when the caller allows reminders.
  - The project currently open in Resolve is left out of the reminder.
  - One project: "N clip(s) in '<project>' is/are only on this computer (<last two folder names>). Open that project in Resolve and press FIX ALL."
  - Several: "N clip(s) in '<top project>' (<folder>) and more in M other project(s) are only on this computer. Open each project in Resolve and press FIX ALL."
  - Project names longer than 60 characters are cut with "...". Projects are ordered by most clips first.
- **Report to the dashboard:** up to 20 entries of project name and clip count (never a path), plus the time of the last sweep. Nothing (rather than an empty list) until a sweep has completed.

## Dormant, unreachable and diagnostic-only pieces in this part

- **DORMANT: the "parked" undo state.** The dashboard undo can return a finer "parked" state, but nothing passes the switch that enables it, so "retrying" is always sent (source: resolve_undo.py).
- **UNREACHABLE: the `unlink_proxy_media` journal kind.** Defined, never written; the undo can detach a proxy but that act is not journalled (source: resolve_journal.py).
- **UNREACHABLE (no caller in shipped code): "seconds until the next automatic pass"** read-out (source: resolve_journal.py), and the non-reserving name chooser `unique_destination_path` (source: fixer.py; FIX ALL uses the reserving one).
- **DEV ONLY / diagnostic: library walk status** (enabled, source library/api, library name, error, walk milliseconds, retry countdown). Its own docstring says only tools read it, but the Timeline Cards bridge reads it to tell whether the last walk came from the library (source: resolve_bridge.py).
- **Test-only resets** (bridge activity, session state, timeline cache, uid cache, library state, journal state, script-server cache) are not features.

## Looks redundant or overlapping

- **Three ways to read a media pool:** the scripting API walk, the open-project library read, and the whole-library read used by the unopened-projects sweep. The first two return the same shape and the bridge silently switches between them; the third re-implements the scoping for every project at once.
- **Two ways to learn "is Resolve running":** the process check (in-process snapshot on Windows, `tasklist` fallback, `pgrep` on macOS) and the script-server TCP probe; the disconnection messages combine both, with separate caches (30 seconds and 250 milliseconds).
- **Two rollback mechanisms for the same edits:** the exported `.drp` save point and the JSON undo journal. Only the journal is ever used by the undo.
- **Two undo surfaces for one replay:** the tray's "undo last fix" and the dashboard's "UNDO THIS CHANGE" (same function, different choice of journal).
- **Three copies of "relink an imported clip to its canonical spelling":** after a b-roll insert, after a YouTube import, and the watcher's automatic non-canonical relink (outside this part, fed by the watcher).
- **FIX ALL and "Copy this project's media in" (consolidate)** do the same copy-and-relink per file with the same dialog controls; consolidate adds a server preview. The unopened-projects reminder points editors at FIX ALL for a third discovery path.
- **LUT library and stills location** are two near-identical "reconcile one Resolve preference against a synced folder" managers with their own warning-dedupe rules (hourly re-log for LUTs, once per run for stills).
- **Two "missing but fine" exemptions in the watcher** (b-roll archive clip with proxy or stand-in, project clip with its proxy on disk), each with its own 60-second memory.
- **Library location found two ways:** Resolve's own database answer, then parsing Resolve's log; the unopened sweep repeats the log parse for all libraries.
- **Clip property read two ways** (single property vs. full property list), chosen per run, plus several functions that always use the full list.
- **Duplicated logic named in the code itself:** timecode-to-frame conversion copied from the music worker; project-name matching kept "in sync" with a dashboard twin; the project marker file name copied from the dashboard.
- **Disconnection logging in two places:** the bridge logs launch-window transitions, and the watcher logs connection transitions ("Resolve bridge: ...").

## Claims the code does not back

- `resolve_bridge.library_status()` docstring: "Nothing in the running companion calls this". The Timeline Cards bridge (`timeline_cards_bridge.py`) calls it.
- `resolve_bridge._attach_adjacent_proxy` docstring: link_proxy_media "takes the same non-reentrant lock". The lock is reentrant (the module's own `_API_LOCK` is an RLock and every public function re-enters it).
- `resolve_undo` parked detail: when the replay's message is the bridge's "Resolve didn't answer. Make sure a project is open, then try again." or "no timeline open in Resolve", the park hints match first and the admin is told "there is no project open in Resolve on this computer", which is not what happened. The "didn't answer" retry hint written for that message is never reached for it.
- `resolve_prefs.ResolvePrefs.ensure_scripting_local` docstring: "Returns OK, ALREADY or RESOLVE_RUNNING". It also returns `format-unrecognised` when `.config.data` is absent.
- `script_server.state()` and `classify()` docstrings list the answers as READY, STARTING or UNKNOWN. They also return ABSENT.
- `watcher.py` module docstring: out-of-tree clips are "debounced per session". The suppression is 30 minutes per skip (fixer's SKIP FOR NOW).
- `fixer.py` module docstring: the destination dropdown lists "existing directories under local_root". When a project prefix is known it lists only folders inside that prefix (plus the three defaults).
- `stills.py` module docstring: "Both preference files". The media storage entry is written to both, but the gallery pointer itself is written only to `config.dat` (the code says the other file has no such key).
- `resolve_bridge` comments describe the tray as "pystray's win32 message pump"; the project's own instructions say the tray is no longer pystray. Not verifiable from this part's files; the comment is at least stale.

## Could not determine

- How often the LUT check, stills check and stale-LUT repair run, and which tray items or windows show their status (the callers are outside this part).
- What the companion does with the originals request files the Resolve menu items write (`~/.ccsync/requests/originals/*.json`), and how it "confirms" as the menu items promise.
- The exact wording of menu-route strings inserted from `ui_copy` (`QUIT`, `SCAN_WHOLE_PROJECT`, `DIAGNOSTICS`) and of the reminder title produced by the site's notification-title helper.
- The path classification rules themselves (OK, out of tree, non-canonical, bad prefix, foreign, missing) live in `paths.py`, outside this part.
- Whether the unopened-projects sweep's Resolve library list is fetched only when the bridge is already connected (its docstring says so; the fetch is in the caller).
- Whether the companion restarts itself when Resolve goes away (a bridge comment says so; the code is elsewhere).
- Whether Resolve really lists `Scripts/Edit/CC Sync/` as Workspace > Scripts > CC Sync, whether the In/Out mark frame-base guess is right, and whether a playhead insert's audio really lands on the same-numbered audio track: the code's own comments say these were not verified against a running Resolve. The macOS script-server probe is likewise marked as untested on a live Mac when written.
- Which callers pass `tries`, `force` and `source` values to the relink, other than the ones named here (fix-all, import-canonicalise, insert-adjacent-proxy, manual).
