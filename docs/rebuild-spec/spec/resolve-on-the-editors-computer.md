# Resolve on the editor's computer

This is the help the product gives with DaVinci Resolve on an editor's computer, outside Timeline Cards: it notices clips that are missing, stored outside the studio's shared folders or under a path only one computer can open, fixes them with the editor's say and with undo, attaches synced proxies, keeps every Resolve pointed at the studio's shared colour look-up tables (LUTs) and stills, lets a remote editor grade from the server's originals, and sets Resolve itself up when the app is installed. Editors meet it in the app on their computer and in Resolve; admins meet it on the dashboard, where each computer's Resolve health is shown and a change the product made can be undone. Resolve is something the studio has, so this piece also states, as facts about Resolve, what its scripting allows and refuses, when connecting to it is unsafe, and what it does to clips, bins, proxies and paths: every part of the product that works with Resolve relies on them. It is one of the six parts a site can switch off, and it is on by default. With it off, nothing in the product mentions Resolve: the app on the editor's computer never looks at Resolve or changes its preferences, the dashboard shows no Resolve health, pairings or undo, the b-roll archive, music and Timeline Cards offer exports instead of sending to Resolve, and syncing carries on exactly as before.

## Multicams, frame rates and timelines

### What Resolve does with multicams, timelines and frame rates

These are facts about DaVinci Resolve. Every part of the product that builds or places anything in Resolve (sending a b-roll clip, a music track or a YouTube download, the hand-over of a cut from Timeline Cards, a repair made here) keeps the promise that goes with each.

| Fact about Resolve | What the product promises |
|---|---|
| Resolve's scripting reports no file path and no angles for a multicam clip, and none for a compound clip. | The source files of every multicam and compound clip are found from its angles, and a timeline of multicams never reads as having no media. |
| A multicam angle can itself be a compound clip, or several camera files one after another. | Anything worked out from an angle follows compound clips down to the camera files and places every file at its own time. |
| Multicams built in Resolve all start at 01:00:00:00 and carry no reel or file name. | Multicams are told apart by a property unique to each (such as the exact total duration), which is checked to be unique first. When it is not unique the product refuses rather than guesses. |
| A multicam's angles map frame for frame from their starts, not by timecode. | Moving a cut between a camera clip and its multicam maps frames one to one from the angle's start, never by source timecode or by real time. |
| Importing a timeline into a project that already holds its multicams makes a second copy of each. | Combined projects keep one copy of each multicam, matched by unique total duration, and leftovers are set aside in the project, never lost. |
| Rebuilding a damaged multicam timeline by exporting and importing it fails both ways. | A damaged multicam timeline is repaired inside Resolve (the timeline is duplicated and each pair relinked), never by an export and import round trip, and no stray angle timelines are left behind. |
| Resolve places a clip added by script a frame early now and then, and reports odd source times. | Every clip the product places in Resolve is read back and laid again once if it is a frame out. |
| Resolve's append can report success while placing nothing. | After adding a clip to a timeline, the product confirms it is there at the expected start, without tying it to one media type and so losing its sound. |
| A new Resolve project starts at 24 fps, or at the rate of the first raw clip imported. | Before anything is imported or built, the project's rate is checked against the footage (29.97 fps drop-frame for this studio's footage), and the person is stopped, with the reason, if it cannot be set. |
| Resolve counts an audio-only clip's frames in that clip's own rate. | Placing audio-only clips converts frames using the clip's own rate, and the timeline's length is checked afterwards. |
| Several things in Resolve cannot be done by script at all. | Each such step is handed to the person as a named instruction with its exact value, and the product never reports success for a setting Resolve refused. |
| Resolve's count of linked clips changes between sessions on identical timelines. | Resolve's link count is never taken as proof that picture and sound are paired. |
| Scripted effects inside a compound clip can lose their first frames and stop a render. | A compound clip the product builds renders every frame including its first, checked by rendering its first frames before it is handed over. |

### The editor is warned when the open timeline uses VP9 originals

DaVinci Resolve cannot decode VP9 originals (typical of YouTube downloads) at full resolution, although editing with proxies looks fine; the render then fails with "Error decoding full resolution media". So the app checks each original used on a video track of the open timeline whenever the timeline's video clips change. If any is VP9, a window titled "CC Sync: VP9 media in this timeline" says:

- "N source media file(s) is/are VP9 in project “<project>”, and DaVinci Resolve cannot render VP9 originals at full resolution. This timeline WILL FAIL to render with “Error decoding full resolution media”."
- "It plays fine now only because Resolve is using the H.264 proxies.", shown only when the affected clips are in fact playing from proxies, and left out otherwise.
- "Affected clips:", listing up to 12 files, each with the clip's name, the file's name and up to 4 positions such as "V2 clip 5" ("and N more"), then "... and N more files".
- "How to fix it: convert each original to H.264, then relink the clip to the converted file or remake its proxy."
- "STOP WARNING FOR THIS TIMELINE keeps this quiet until a new VP9 clip is added to this timeline."

Buttons: "STOP WARNING FOR THIS TIMELINE" and "CLOSE". The window also offers to repair the clips before a render: each VP9 original is swapped for an edit-ready copy with the same frame count, which takes seconds per clip when such a copy exists (as it does for a YouTube download made ready to edit); only a clip with no matching copy is re-encoded. The swap is a relink, recorded so it can be undone like any other.

While the app runs, the same VP9 files on the same timeline are not shown again after either button. "STOP WARNING FOR THIS TIMELINE" remembers those files for that project and timeline across restarts, for up to 500 timelines, forgetting the oldest first. A VP9 file newly added to the timeline warns again. A remembered file later found not to be VP9 (converted in place) is forgotten, so a new VP9 file at that path warns again. A file that cannot be found (for example on a computer holding only proxies) or cannot be read is never warned about. If the window cannot be shown because another of the app's windows is open, the warning is shown at the next chance.

- Who: the editor at that computer.
- On its own: the app decides which originals are VP9 by reading the files on this computer.
- By hand: the editor silences the warning for one timeline, or switches it off for the computer.
- Setting: VP9 warning. Does: warns when the open timeline uses VP9 originals that Resolve cannot render. Default: on. Who: the editor at that computer. Applies to: a computer. Search words: VP9, render fails, decoding error, YouTube originals.

### A timeline that is silent on one computer can be checked

When a timeline that plays with sound elsewhere is silent on one computer, the product can check that computer's audio playback and the timeline's offline clips, and says which of the two is at fault.

- Who: the editor at that computer, or an admin looking at that computer.

#### Lessons

- Met: CRX-091, RSV-103, RSV-104, RSV-105, RSV-106, RSV-107, RSV-108, RSV-109, RSV-110, RSV-111, RSV-112, RSV-113, RSV-114, RSV-115, RSV-116, RSV-117.

## Clip paths and media outside the shared tree

### Every clip path in a Resolve project is written one way for the whole studio

Resolve stores a clip's path exactly as it was browsed to. So that a project opens with its media on every computer, every computer of the studio, the one beside the server included, sees the shared project tree at the identical drive and path, and every Resolve project in the studio stores media paths under the studio's shared drive letter (P:\ unless the site chose another), the only spelling that works on every computer, wherever the footage really sits on each one. A path the product writes into Resolve is always in that spelling, with backslashes, on Windows and macOS alike, and never one computer's physical disk; on macOS Resolve reaches it through its own mapped-mount preference (see "On a Mac, Resolve is given a mapping from the studio drive to the local folder"). A file outside the shared folder keeps its real path. Paths are compared ignoring letter case and slash direction, and "inside a folder" means inside it, not a folder whose name merely starts the same way. A file's name is shown from the end of its path whatever the spelling (a Windows-spelled path on a Mac shows just the file name). On a computer whose shared folder is the drive itself, paths pass through unchanged.

- Windows and macOS: on Windows the shared drive letter leads to the local copy of the tree; on macOS nothing is mounted at a drive letter and Resolve translates the drive's paths through its mapped mount.

### Clips stored under this computer's own spelling are repointed to the shared spelling without asking

A clip whose file is in the shared tree, but which Resolve holds under a spelling only this computer has (for example a local drive letter or the local folder's own path instead of the shared drive), is offline on every other computer. The app repoints it in Resolve to the shared spelling, copying nothing; inside a multicam or compound clip, the angle's own clip is repointed. The same path is not tried again for 15 minutes after an attempt, whether it worked or not, and the change counts towards the limit on changes made unasked (see "Changes the product makes in Resolve unasked are limited and retried by themselves"). A clip that fails is tried again later; one Resolve no longer has is skipped. After at least one success the editor is told: "Re-addressed <N clips> to <shared drive> so they stay online for every editor." Clips Resolve refused to repoint are listed for the editor (name and path, the 200 most recent); a later success removes the clip from that list. Every change is saved first and recorded so it can be undone (see "Every change the product makes in Resolve is recorded so it can be put back").

- On its own: the app decides a clip is in the tree under a private spelling from its path and this computer's shared folder.
- By hand: the editor or an admin undoes the change (see "The editor undoes the last change the product made in Resolve").
- Windows and macOS: never done on a computer whose shared folder is the drive itself, where both spellings are the same.

### A clip outside the shared tree raises a window offering to fix it

While Resolve has a timeline open, a clip whose file is outside the shared tree (so it will never reach the server or other editors) opens a window offering to copy it in and relink it. The window shows one row per file: several uses of the same file (compared ignoring letter case) are one row, and fixing it relinks every use. It reads:

- Heading "► MEDIA OUTSIDE PROJECT TREE".
- "N timeline clips live outside <sync folder> and will NOT sync. Pick a destination. FIX ALL copies them in and relinks Resolve. Your original file is left exactly where it is. Nothing is moved or deleted."
- Per row: the clip's name, its full path, and "  dest:" with a list of destination folders that also accepts typed text, filled with a suggestion (see "Each clip outside the tree is given a suggested destination"). When the destination is outside every project, a red line under the row, updating as the editor picks or types: "This folder is outside every project and will not sync. Pick one under Projects to share the copy." It warns but does not stop the copy.
- Buttons "FIX ALL" and "SKIP FOR 30 MINUTES" above the list, so they stay reachable with many rows; the rest of what the window does is under "FIX ALL copies the listed clips in and repoints Resolve at the copies".

The window stays on top, fits within 80 % of the screen's height and 90 % of its width, and only the list of rows shrinks and scrolls to fit; a row is never empty. A clip shown in the last 5 minutes is not shown again until that time is up. Clips found while a window is already open are kept, without duplicates, and shown as soon as it closes; no "already open" notice ever appears. Each window waits its turn behind any other window of the app.

The window is never raised:

- for a clip inside the shared b-roll archive, which is correctly placed wherever it sits;
- for a project that is not one of the studio's synced projects (a scratch or ignored project, or one tied to no project in the tree);
- on a computer that works directly off the server, for a clip already inside that project's own folder on the server: there only clips outside the project's own folder are listed;
- while the sync folder is set up wrongly or the sync drive is out, because every clip would then look outside the tree;
- while the shared drive is pointed at the server for grading.

Before showing it the app asks the dashboard where the open project lives; when it cannot: "Can't reach the server right now, so CC Sync doesn't know where this media belongs. It'll ask again once the connection is back. Nothing was changed." Fixed clips are always stored under the shared spelling. If the window cannot be shown at all (no display), every clip is put off for 30 minutes; that skip is recorded apart from an editor's own and counted.

- Who: the editor at that computer.
- On its own: the app decides a clip is outside the tree from its path, and decides which project it belongs to from the project's pairing (see "A Resolve project is tied to a project in the tree").
- By hand: the editor picks or types each destination, skips, or fixes.
- Setting: Fix-it window for media outside the tree. Does: raises the window when the open timeline uses a clip outside the shared tree. Default: on. Who: the editor at that computer. Applies to: a computer. Search words: outside tree, fix all, popup, media not syncing.

### Each clip outside the tree is given a suggested destination

The suggestion is inside the project's folder in the shared tree:

- Audio files: "Audio/Music".
- Still images: "B-roll/Stills".
- Video and anything else: "B-roll/Editor Added/<editor name>" ("Unknown" if the editor has no name).

The project's folder is the first of: the folder the dashboard holds for the open Resolve project (see "Everyone can see where FIX ALL puts files for each Resolve project"); otherwise the project folder in the shared tree whose name shares the most words with the Resolve project's name (words are letters and digits, letter case ignored; bare numbers of up to 4 digits, such as years and season numbers, never count; a tie or no shared word is no match); otherwise the project this computer is set to work in; otherwise the top of the shared tree under the editor's own folder. A project folder is any folder under "Projects" marked as a project, plus any folder the dashboard says this computer syncs; names differing only in how accented letters are encoded count once. Suggestions only ever point inside the open project's folder when there is one. The destination list offers the three suggestions (even if those folders do not exist yet) plus every existing folder in the project's folder (or the whole tree when there is no project), never a "Proxy" folder or anything inside one.

When the dashboard cannot be reached, the last answer it gave is used; with no answer at all, the product refuses to choose where media should go. A folder that would reach outside the project tree is never offered.

- On its own: the suggestion, from the rules above.
- By hand: the editor picks another folder or types one; an admin changes which folder a Resolve project files into.

### A clip can be skipped for 30 minutes and never for longer

"SKIP FOR 30 MINUTES" puts off every clip in the window for 30 minutes and closes the window; it does nothing while a copy runs. Pressing it again for a clip already skipped never extends its 30 minutes, and anything new is always offered. There is no permanent or per-folder dismiss. Skipping a single file during a copy never puts it on the 30-minute list. Skips are forgotten when the app quits, and "Scan whole project" clears every skip first so everything shows. Skipped clips still count as not syncing: the app's Resolve status and the computer's report to the dashboard count clips skipped now and clips ever skipped on this computer, and an automatic skip (a window that could not be shown) is counted apart from an editor's own.

- Who: the editor at that computer.

### The editor scans the whole open project for media outside the tree

"SCAN WHOLE PROJECT" reads every clip in every bin of the open project, not only the timeline (see "The product reads the whole media pool, including clips never cut into a timeline"). It works even with the fix-it window switched off, ignores the five-minute quiet time, forgets this session's skips so everything is shown again, and at once repoints any clips waiting to be moved to the shared spelling. It shows progress while it reads, keeps the app usable throughout, and treats a project of 1,300 clips as normal size. Results: "Whole-project scan: all media is in the tree", or the fix-it window for the clips found. Refusals: "<Drive> is disconnected, so CC Sync can't tell where your media is. Plug it back in and try again."; "CC Sync's sync folder isn't set up correctly, so it can't tell which media is in the wrong place." with how to get help; "Whole-project scan failed: <message>".

- Who: the editor at that computer.
- Ways in: from the app's Resolve status in its settings window. The open timeline is watched on its own, and projects not open are checked on their own.

### Clips pointing at a path only another editor's computer has are named to the editor

A clip whose path exists only on another editor's computer can never sync or come online here, and cannot be fixed here. The app tells the editor once per path while it runs, in one notice per batch found: "“<first clip>”[ and <N other clips>] point at paths that only exist on another editor's computer, so they can never sync or come online here. Whoever imported them should re-import through <shared drive> (the app on their computer will offer the fix)." The notice names the first path, up to its first 60 characters, and the full list is in the app's diagnostics.

- Who: the editor at that computer.

### Projects not open in Resolve are checked for footage that exists only on this computer

About every 30 minutes, starting about 2 minutes after the app starts, the app looks through every Resolve project in every project library this computer can read, without opening them in Resolve, for clips whose files exist only on this computer. A project is flagged when at least one of its clips is a file outside the shared tree that exists on this disk AND at least one other clip is in a project in the shared tree; projects wholly outside the tree are left alone. Not looked at: the project open now (already watched), ignored and scratch projects, and a project name that appears twice in one library (it cannot be told which is meant). Nothing is looked at while the sync folder is broken, the sync drive is out, or the shared drive is pointed at the server for grading. A library that cannot be read is skipped until it answers; if none can be read, the last findings stand. Facts about Resolve: a library may be a database on a server or on this disk; disk libraries kept outside Resolve's usual place are not found, and the search stops after 5,000 folders or 500 projects.

The editor is reminded by a notification titled for "footage only on this computer", first on finding something and then every 30 minutes while anything is flagged, leaving out the project open now:

- One project: "N clip(s) in '<project>' is/are only on this computer (<last two folder names>). Open that project in Resolve and press FIX ALL."
- Several: "N clip(s) in '<top project>' (<folder>) and more in M other project(s) are only on this computer. Open each project in Resolve and press FIX ALL."

Projects are ordered by most clips; names over 60 characters are cut with "...". The app's Resolve status lists the flagged projects other than the one open. The dashboard receives up to 20 project names with clip counts (never paths) and when the last look finished, and reads "not checked yet" until a look has finished.

- Who: the editor at that computer.

### Admins are told when footage used in Resolve is outside the shared tree

- "footage is outside the tree", titled "footage is outside the tree in '<project>'" when the project is known: raised when a computer's last look at Resolve found clips used from outside the shared tree. It names the clip, the Resolve project and where to move it. It is raised only if the open project is tied to a project in the tree, or the computer has not said which project is open; a project that is not one of the studio's synced projects raises nothing, and an alert already open for it is held quiet.
- "footage on one computer only in '<first>' and N other projects", listing up to 5 projects, from the computer's look through the Resolve projects not open. Fix: open each project and press FIX ALL.

One problem raises one alert per episode however many clips it touches, raised again only after it has cleared and broken again.

- Who: an admin.

#### Lessons

- Met: RSV-058, APP-104, APP-105, RSV-059, RSV-060, RSV-061, RSV-062, RSV-063, RSV-064, RSV-065, RSV-066, RSV-067, RSV-068, RSV-069, RSV-070, RSV-071.

## Setting Resolve up: edition, scripting switch, preferences

### What Resolve's editions and its scripting switch allow

Facts about DaVinci Resolve:

- Outside programs can drive only the paid edition, DaVinci Resolve Studio. The free edition has no scripting at all, and no setting adds it.
- Studio allows it only when Preferences > System > General > "External scripting using" is set to Local or Network. Its default is None.
- Local lets programs on the same computer drive Resolve. Network would let other computers drive it, over a port anyone who can reach the computer can use.
- A Studio licence held on a dongle leaves no licence file, just like the free edition, so a missing licence file is not proof of the free edition.
- Resolve may be installed on any drive, and on a Mac in the Applications folder or from the Mac App Store, which keeps its preferences elsewhere.

What the product does with them:

- It drives Resolve only on the computer Resolve runs on, with "External scripting using" set to Local. It never turns on Network and never relies on it.
- It finds whether Resolve is installed wherever it is installed, its version, and whether it has ever been run on this computer (its preferences exist). When it cannot find Resolve, it says so in plain words and names where it looked.
- On Windows it recognises the Studio edition from its licence when one is found; when it cannot tell, the edition is reported as "unknown", never as "free". On macOS the edition is never recognised and is reported as unknown.
- Setup counts as done only after the app has really connected to Resolve once.
- Syncing never depends on Resolve or its scripting: with Resolve Free, scripting off, an older Resolve or a Windows in another language, setup completes or names exactly what the editor must change, and everything else in the product keeps working.

- Windows and macOS: only Windows and macOS are supported. On any other system everything about Resolve is reported as unknown and nothing is changed.

### Every change the product makes to Resolve's preferences waits until Resolve is closed

Facts about Resolve: it keeps its preferences in two files that must agree with each other, and rewrites both whenever it quits, so a change made while it runs is thrown away. It does not create them until it has been run once, and a first run with no preferences rebuilds its whole configuration. The product's rules for every change it makes to Resolve's preferences (the scripting switch, the shared LUT location, the shared stills location, the drive mapping on a Mac, the shared project library):

- Never while Resolve is running. If Resolve is open, the person is asked to quit it: "DaVinci Resolve is running. It rewrites its own preferences when it quits, so anything set now would be thrown away. Please quit DaVinci Resolve. This will continue automatically." The product checks every 3 seconds for up to 3 minutes and carries on by itself the moment Resolve closes. If it times out: "Still running - skipping. CC Sync will apply these settings the next time Resolve is closed." The app then makes the change the next time Resolve is closed. If the product cannot tell whether Resolve is running, it assumes it is.
- Never creates the files. If they do not exist yet: "<path> does not exist - launch Resolve once, quit it, and retry".
- Only the lines being changed are touched; the editor's own entries, comments and layout are kept.
- Both files are backed up beside themselves, stamped with the date and time, before any change. A change that would change nothing writes nothing.
- If the files are not in the shape expected, nothing is changed and the editor is told how to make the change by hand in Resolve, with the exact value.
- After the change, the product checks at Resolve's next start that it survived.

### Installing the app sets Resolve up for the studio

After the app is in place, the install sets Resolve up, following the rules above:

1. "External scripting using" is set to Local when it is None or not set, and never changed when it is Local or Network. This is done by writing Resolve's preference, never by talking to Resolve. Outcomes, each a note on the install's finish page: done or already set (nothing shown, and the note says so when a Studio licence was found); Resolve not found and never opened ("Could not find DaVinci Resolve on this computer ... Install Studio, open it once, quit it, then run this installer again"); Resolve open (quit it, then set Preferences, System, General, External scripting using, Local); never opened (after its first launch, set it); preferences incomplete (set it and click Save). Every computer gets this step, whether wired or remote.
2. Resolve's LUT list is pointed at the studio's shared LUT library (see "Every Resolve lists the studio's shared LUTs").
3. Resolve's stills gallery is pointed at the studio's shared stills folder (see "Resolve's gallery on every computer uses one shared stills folder"). The first media storage entry is never moved, and nothing changes until the shared folder exists on this computer.
4. On a Mac, the drive mapping (see "On a Mac, Resolve is given a mapping from the studio drive to the local folder").
5. The studio's shared project library, when the studio has one (see "Resolve is given the studio's shared project library").

Each step reports "set", "already correct", "not set" with the reason and the exact manual step, or "failed". If Resolve is open and does not close within 3 minutes, the editor is told the app will apply the rest the next time Resolve is closed.

- Who: the person installing the app on that computer.
- Windows and macOS: on a Mac where the app itself is not yet installed, the LUT and stills steps are left to the app.

### On a Mac, Resolve is given a mapping from the studio drive to the local folder

On a Mac nothing is mounted at a drive letter. So that the studio's Windows-style clip paths open on the Mac, the install adds a Mapped Mount to Resolve's Media Storage preferences that maps the studio's drive (for example P:\) to the local shared folder. An existing mapping of the drive is repointed, never duplicated; both preference files are backed up first and everything else in them is kept. If Resolve is open, the install asks for it to be quit and waits up to 3 minutes; on time-out it carries on without the mapping and says how to set only the mapping later.

The finish page says either "DONE FOR YOU: Resolve maps P:\ to <folder>" or NOT DONE with the fix, each a warning on the finish page:

- Resolve was running: quit Resolve and run the install again.
- Resolve has never been launched: launch Resolve once, quit it, then run the install again.
- Resolve is not installed: "CC Sync needs Resolve Studio, the paid version".
- The preferences are in a form the install does not know: nothing was changed, with the manual steps (Resolve, Preferences, Media Storage, add a Mapped Mount: local path, mapped path).
- The Mac's developer tools are missing: install them and run the install again.

A separate choice in the install sets only this mapping and touches nothing else.

- Who: the person installing the app on that Mac.
- Windows and macOS: macOS only; on Windows the shared drive letter does the same job.

### Resolve is given the studio's shared project library

Fact about Resolve: it registers the address of the project library entry selected in its project manager as its collaboration address. So when the studio keeps its Resolve projects in a shared project library on the server, the product adds that library to Resolve's project manager for the editor: one entry per library, each using the address every editor's computer can reach (the site's server address), written only while Resolve is closed. The editor types the library's password once, when Resolve first asks.

- Who: the person installing the app; the password comes from an admin.
- On its own: the address, from the site's settings.
- By hand: the editor can add or change the entry in Resolve's project manager.

### The finish page lists what the editor still has to do in Resolve

Under the heading "BEFORE YOU OPEN A PROJECT, CONNECT RESOLVE (needs DaVinci Resolve Studio)":

1. In Resolve's project manager, the studio's shared network project library (Resolve's database-server kind of library), with the host (the site's server, else the dashboard's host, else "ask your admin") and the user name and password from the admin; shown as done when the install added the entry.
2. External scripting: already set to Local, or the manual instruction plus the reason it was not set.
3. Open the shared project and set Playback, Proxy Handling, Prefer Proxies.

Below: "Problems? Contact" the site's support contact (else the vendor's), the place of the install's log, and buttons to close, copy the log, and see the open-source licences (a read-only window with the licence texts, or a note that copies are available on request). The closing text of an install run by hand adds: never map any server share to another drive letter yourself (on a Mac: never mount a server share alongside this), and, on a Mac, how to uninstall.

- Who: the person installing the app.

#### Lessons

- Met: RSV-032, RSV-033, RSV-034, RSV-035, RSV-036, RSV-037, RSV-038, RSV-040, APP-106, RSV-041.

## Bins, clip sorting and imports

### The product reads the whole media pool, including clips never cut into a timeline

For "Scan whole project" and for the fixes, the product reads every clip in every bin of the open project (timelines, compound clips and generators excluded), with its bin, its proxy file and its proxy state. Bins nested more than 64 deep are not looked into. "Scan whole project" always takes a complete fresh look, never a remembered one, and a project closed and reopened is always read afresh. A clip that cannot be found again when it is time to change it is skipped, never acted on.

### The dashboard keeps each computer's Resolve bin layout for projects tied to the tree

For each Resolve project tied to a project in the tree, the dashboard keeps, per computer, each clip's bin, name, file path, kind and whether its file is present, replacing that computer's earlier layout for that project with each new one. Scratch projects and projects tied to nothing are not kept.

- Who: kept for anyone who may see that project.

### What Resolve does when clips are imported into bins

Facts about Resolve, and the promise the product keeps wherever it imports anything into Resolve:

| Fact about Resolve | What the product promises |
|---|---|
| A scripted import files clips into whichever bin is selected at that moment. | An import the product makes never changes which bin the editor has selected, even when the editor clicks while it runs. |
| Its scripting can read a bin's name but cannot rename a bin. | Bins the product creates are named correctly when created, and a rename that is needed is listed for the person to do by hand, never claimed as done. |
| It calls an ordinary clip's type "Video + Audio". | A clip with picture is never classed as audio, compound clips get their own bin, and a file named like a YouTube download is filed as YouTube. |
| Re-importing a folder of numbered stills adds them again, beside the image sequence already held. | Re-importing a folder never adds a second copy of stills Resolve already holds as an image sequence. |
| In a locked project it refuses to make a bin and says nothing. | When Resolve will not create a bin, the editor is told the project looks locked. |

### An editor sorts a project's clips into bins

The product proposes where each clip of the open project belongs, and the editor approves before anything moves:

- Each interviewee folder gets its own bin, holding all of that folder's video and sound-recorder files together.
- The project's existing bins are the template, unfamiliar ones included: a clip goes to an existing bin whose name plainly describes it.
- A repeat sort moves only clips not yet placed, files them into existing matching bins before proposing any new bin, and never touches interview bins.
- After a sort, no YouTube or archive clip sits loose in its parent bin: each is in a theme bin or, last, in "Uncategorised".
- Clip colours: the product never assigns or offers "Brown", and wherever a person picks a colour, they see swatches, not Resolve's colour names alone.

- Who: the editor at that computer.
- On its own: the proposed bin for each clip, from the clip's folder, its kind and the project's bins.
- By hand: the editor sees every proposed move before it is made, changes the bin of any clip, and refuses any proposed new bin. A clip the editor placed by hand is never moved by a later sort.

#### Lessons

- Met: SRT-186, RSV-118, RSV-119, RSV-120, RSV-121, RSV-122, RSV-123, RSV-124, RSV-125.

## Connecting to Resolve's scripting: launch, stalls and death

### Facts about Resolve's scripting connection

These are facts about DaVinci Resolve that hold whatever is built:

- Every outside program that talks to Resolve goes through a helper program that Resolve starts late in its own launch (it can be minutes after Resolve opens), listening on TCP port 1144 on the computer. Resolve then connects to that helper and registers as its host. The helper exits when its last connection closes.
- A program that connects in the short gap between the helper starting and Resolve registering gets no Resolve, drops, and takes the helper down. Resolve retries a few times (the editor sees Resolve hang for 10 to 20 seconds while it launches) and then gives up scripting for the whole session, for every program on that computer. It never retries that session. The only cure is to quit Resolve and every program that talks to it, start Resolve, then start the programs.
- Asking Resolve for a connection when no helper is present does not fail at once: it keeps retrying for about 4 seconds, so a program that "just checks whether Resolve is up" is in the middle of an attempt when the helper appears.
- Waiting a fixed time after Resolve opens does not work: the dangerous gap starts when the helper starts, not when Resolve does.
- A program still connected to a Resolve that has closed breaks scripting in later Resolve sessions.
- Resolve answers scripting requests one at a time, so one slow program stalls every other. A single request can block for seconds, for minutes, or for ever. Two requests made at once can crash the program making them.
- Any dialog open in Resolve makes its scripting answer nothing, for every program. Opening a project by script stops on Resolve's own dialogs.
- After a forced restart, Resolve can show a "save current project" box that will not close.
- With no project open, or only "Untitled Project", Resolve's scripting returns nothing.
- Resolve's scripting goes dead while a Remote Desktop session to that computer is disconnected.
- Resolve can crash after about 13 minutes of continuous scripted work.
- Resolve's scripting accepts any request name and fails only when the request is made.
- Blackmagic Proxy Generator runs as the Resolve program itself, started with its own switch.

### The product never harms a Resolve session

- The product connects to Resolve only when Resolve's scripting helper is listening AND Resolve itself has registered with it. It learns this by looking at what is listening and connected on the computer, never by attempting a connection and never by waiting a time after Resolve starts. With no helper (Resolve closed) it stays quiet; with a helper but no Resolve registered yet, it holds off every request until Resolve has registered. Only when it cannot tell at all (the computer's list of connections cannot be read, or something other than Resolve's helper holds port 1144) does it go ahead and connect. This holds for everything the product does with Resolve, scheduled work included, and nothing on an editor's computer contacts Resolve before its launch completes.
- The app is the one part of the product that talks to Resolve on a computer. It holds Resolve only during a request, never while working something out. Another program found driving Resolve on the same computer is named to the editor and left alone, never stopped, and is looked for again on its own so the editor need not restart anything; when it cannot be told whether one is running, it counts as running.
- When Resolve quits, the app lets go of it entirely, so the next Resolve starts clean.
- The product never force-closes Resolve without first saving or closing the open project, and after any restart of Resolve it checks that Resolve is usable.
- Learning whether Resolve is running costs nothing noticeable on an idle computer, and one answer serves every part of the product. A Resolve started as Blackmagic Proxy Generator does not count as Resolve.
- Every request the product makes of Resolve is proven against a real Resolve of each supported version before a release.
- The app's diagnostics say plainly what happened: "Resolve went away, nothing connected", "could not tell, connected anyway", and "registered" only when Resolve's registration was seen. A Resolve that fails to launch is recorded there for diagnosis.

- Windows and macOS: the same rule on both.

### Resolve stays responsive while the product works with it

- Only one request at a time goes from the product to Resolve, small look-ups after a relink included, so two features never talk over each other inside Resolve.
- No request holds Resolve for more than half a second, and every read asks only for what it needs.
- The product asks Resolve nothing while it is playing back, and never re-reads the whole timeline or media pool on a timer when nothing has changed.
- No request to Resolve ever blocks the app's menu, a window, other features, or quitting. Each request has a deadline; one that passes it is reported and given up.
- When a request has been inside Resolve for more than 20 seconds, the app's Resolve status reads "Resolve: not answering for N s (<what it asked>)" in amber, never "connected", and the computer's report to the dashboard shows which request is waiting and for how long. In the app's diagnostics the advice is "if this does not clear, quit and reopen Resolve".
- Empty answers mean "Resolve cannot answer now", never missing data: nothing is written meanwhile, and the editor is told to check Resolve for an open dialog. A render the product asks for is confirmed started.
- Automated work that opens projects notices a blocking dialog or a stalled project load and tells the person, instead of waiting for ever.
- Long scripted work records its progress item by item, survives Resolve crashing or hanging, carries on without redoing finished items, and checks that each output exists at the right size.

### What the editor is told when Resolve cannot be reached

The editor is told which situation it is, in plain words, never only in the app's diagnostics:

- Resolve is starting up: "DaVinci Resolve is starting up".
- Resolve is not running: "DaVinci Resolve is not running".
- For 10 minutes after Resolve launches or quits, while it cannot be scripted: "DaVinci Resolve is open but its scripting isn't available right now (starting up or shutting down)".
- Open but not taking scripting for 10 minutes or more, on a computer that has connected to Resolve before: "DaVinci Resolve is running but isn't accepting scripting connections. Quit and reopen Resolve. If that does not help, quit the CC Sync app, quit Resolve, start the CC Sync app, then start Resolve."
- The same on a computer that has never connected to Resolve, which gets setup advice instead of restart advice:
  - preference None or not set: it says so, then "In Resolve open Preferences > System > General and set 'External scripting using' to Local, click Save, then quit and reopen Resolve." and "Scripting needs DaVinci Resolve Studio, the paid edition. The free edition has no scripting interface, and no setting can add it.";
  - preference already Local or Network: it says it is already set, the Studio note, then "If this is Studio, quit and reopen Resolve; if that does not help, also restart the CC Sync app.";
  - preference cannot be read: the Studio note and the instruction to set the preference.
- A Remote Desktop session to this computer is disconnected: the editor is told to reconnect it, and no Resolve work is tried meanwhile.

Whether this computer has ever connected is remembered across restarts of both programs and never forgotten. Whether Resolve is running is checked at most every 30 seconds; when the check cannot tell, Resolve is taken to be running. When Resolve is connected but has nothing to work on, the messages are "no project open in Resolve" (with "Untitled Project" open: save the project under a real name), "no timeline open in Resolve", "no media pool available" or "no root folder in media pool"; Resolve is never called closed for this. When Resolve stops answering in the middle of a request: "Resolve didn't answer. Make sure a project is open, then try again."

- Who: the editor at that computer.

### The app's menu says whether it can see Resolve and what is wrong in the open project

The app's menu has a Resolve line, absent until the app has first tried to reach Resolve, and read without contacting Resolve:

- "Resolve: not answering for N s (<what it asked>)" when Resolve has not answered for over 20 seconds;
- "Resolve: connected", or "Resolve: connected - <up to two counts>", the counts being (zero counts left out) "N clips outside the tree", "N missing", "N on the wrong drive", "N other projects with clips only here", "N proxies not attached", "N clips still on a preview copy"; further counts are in the line's hover text;
- "Resolve: not connected right now (<reason>)" if this computer has connected before;
- "Resolve: NOT CONNECTED this session (<reason>)" if it never has; when the reason is that scripting is switched off in Resolve, the advice about Resolve's scripting preference is shown instead.

The counts use the same words, and mean the same, in the menu, the settings window and on the dashboard.

- Who: the editor at that computer.

### The editor is warned while Resolve is open but will not take scripting

While Resolve is confirmed running and its scripting is unavailable, every feature that works with Resolve is gone, so the app warns. The first warning comes after one full interval (5 minutes by default), then once per interval counted from when the editor closed the last one; never two at once. It stops on recovery, and any good contact resets it. The window:

- Heading "► RESOLVE SCRIPTING IS DOWN".
- The advice for this computer (see "What the editor is told when Resolve cannot be reached"), led by "quit and reopen Resolve" on a computer that has connected before.
- "Until then CC Sync can't see your timeline, so it can't warn you about media outside your project folder, attach proxies, or send b-roll, music and YouTube clips to Resolve. Your files and your sync are not affected."
- "Save your work first - nothing here is urgent enough to lose a take over."
- Buttons "STOP WARNING ME" (no more such warnings until the link recovers) and "OK"; Enter and closing the window both dismiss.

If another of the app's windows is open or the window cannot be shown, the advice is shown as a notification instead. Nothing is said while Resolve is only starting up or shutting down.

- Who: the editor at that computer.

#### Lessons

- Met: RSV-001, RSV-002, RSV-003, RSV-004, RSV-005, RSV-006, RSV-007, RSV-008, RSV-009, RSV-010, RSV-011, RSV-012, RSV-013, RSV-014, RSV-015, RSV-016, RSV-017, RSV-018, RSV-019, RSV-020, RSV-021, RSV-022, RSV-023, RSV-024, RSV-025, RSV-026, RSV-030, RSV-031.
- Tied to an arrangement: RSV-027, RSV-028, RSV-029 (the promise is in "The product never harms a Resolve session").

## Project libraries and projects

### Facts about Resolve's project libraries

Givens about DaVinci Resolve, whatever is built:

- Resolve keeps its projects in a project library. A library server can hold several libraries, each holding many projects, each with many timelines. Two projects in one library can hold clips of the same name, and two projects can share a name, so a project is known by its name together with its folder.
- What the library holds is what Resolve last saved; unsaved work in a running Resolve is not there. While Resolve is closed or refusing scripting, its last save stays readable from the library.
- When a Resolve has a project open, the library records that it is open and by which Resolve.
- A Resolve that has a timeline open never re-reads it, so a change made to that timeline behind its back silently diverges from what the editor sees and may be overwritten.
- In a Resolve timeline each cut is a video piece on V1 and an audio piece on A1 that Resolve keeps linked to each other.
- A clip in the media pool may be a plain file, a multicam clip, a compound clip, or a timeline used as a clip. Each video track of a multicam is one angle; the lowest is Angle 1.
- A cut's clip colour is one of 16 named colours: Green, Teal, Blue, Purple, Pink, Tan, Brown, Apricot, Beige, Chocolate, Lime, Navy, Olive, Orange, Violet, Yellow (or none).
- Marker colours are 16 named colours: Blue, Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream.
- Resolve keeps at most one timeline marker per frame.
- Resolve has been seen to give a cut's source start one frame differently depending on where it is read from (about a quarter of the cuts on one measured timeline).
- Resolve 21 does not say through its scripting which project library is open.
- On Windows, Resolve names that differ only in letter case overwrite each other's files.
- Resolve freezes about five seconds per unreachable remote project library when it launches, and a Resolve launched before the network was up keeps its network project libraries offline for that session.

What the product promises from them: a Resolve project is identified by its name together with its folder, and where that is still ambiguous the product refuses or asks, never picks. Names that differ only in letter case stay distinct everywhere, files written from them never collide, and every export is checked to be present at the right size. The product finds the open project library without asking Resolve's scripting, shows the person which library it found, and never treats the library as holding unsaved work. Anything that shows a timeline while Resolve is closed or refusing scripting shows it as of Resolve's last save and says plainly that it is not live.

- Pending: resolve-on-the-editors-computer-U1

### The product lists the studio's Resolve libraries, projects and timelines

The product can list every project library on the studio's library server (sorted by name); every project in a library, with which timeline was open at its last save and when it was last changed (sorted by name); and every timeline of a project in Resolve's own order, each with when it was last changed, whether it is the one open at the last save ("current" means open at the LAST SAVE, not open now), and whether it is a helper. The helper timelines that building a multicam leaves behind (one per camera angle, and the syncing ones) are listed but marked, so a picker can put them lower. It can also tell, from the library alone and without any right to write to it, whether a project is open in some Resolve and which one, or that nobody has it open.

### The product reads a project's clips from the library

For a project the product can list its media pool clips (plain video files first, then the rest, each by name), and for every clip its file as it is now, so a relink done in Resolve is reflected (audio-only clips, timelines and compound clips have none of their own). For one clip it can tell its name, frame rate and start timecode: a multicam or compound clip takes these from the edit it is made of; a plain clip with an unreadable start is taken to start at 01:00:00:00; a clip with no stored rate (seen on downloaded YouTube clips) takes them from its video, or is unknown. For a multicam it can list each angle's cuts, with the file, the clip's rate and whether the piece carries a speed change (the speed itself is not known). The audio of a multicam is not read. Resolve's own transcription of a clip can be read from the library too.

### The server can host the studio's shared Resolve project library

Off unless the studio asks for it. The server then runs the database Resolve uses for a shared project library, answering only on the studio's own network and private-network addresses, on port 5432 by default (the port Resolve's project server uses). Its password:

- The person setting the server up may give one; otherwise a random 32-character one is made once, kept, and reused on every reinstall, so nobody has to invent it.
- An empty password, or Resolve's well-known default "DaVinci" in any letter case, is refused from any source, because anyone who can reach the library's port would have full control. The person is told to let the product make one or to choose their own long random one.
- On a library that already exists, the password is first set to the one configured; if that cannot be done, the library does not start and the person is told so.
- The person is told the password must be entered once in each editor's Resolve entry for the library, and that the library is reachable only on the studio's local network and private-network addresses.

- Who: an admin setting the server up.
- Setting: Shared Resolve project library on the server. Does: runs the database that holds the studio's shared Resolve projects. Default: off. Who: an admin. Applies to: the site. Search words: project library, Resolve database, project server, collaboration.

### Every shared Resolve project library is backed up every night

Fact about Resolve: a dump of its project server can be restored straight from Resolve's Project Manager. Every Resolve project library the server holds is backed up nightly in that form, checked to be readable, and kept for 30 days.

- Who: happens on its own; an admin restores from Resolve's Project Manager.

### The editor is warned when Resolve's project library cannot be reached

When the shared project library cannot be reached, the editor is told the network to it is down, before or as Resolve opens (Resolve freezes for each unreachable library at launch). When Resolve started before the library's network was up, the editor is told so and told to quit and reopen Resolve to bring the library online.

- Who: the editor at that computer.

### Projects open quickly and look right in the project manager

Projects the product creates or closes are left on a timeline with picture, so their tile in Resolve's project manager shows a frame and not the Resolve logo. Opening a synced project shows its audio waveforms without waiting for Resolve to regenerate them at each launch.

#### Lessons

- Met: RSV-042, RSV-043, RSV-044, RSV-045, RSV-046, RSV-047, RSV-048, RSV-049, RSV-050, RSV-051.

## Knowing which project is open

### Scratch projects and projects on the ignore list are left alone

Resolve projects named "Untitled Project" or "New Doc" are scratch: Resolve makes them, and they look open though nobody is working in them. A name counts as scratch when it matches one of those, ignoring letter case and extra spaces, or matches one followed only by a duplicate number with optional spaces, dashes, underscores or brackets ("New Doc 1", "New Doc - 2", "New Doc [4]", "Untitled Project (3)"). Names that merely start the same way, like "New Documentary" or "New Doc Final", are real projects.

The editor can add more names to the ignore list on their computer; numbered copies of an added name match too. A scratch or ignored project is treated as if no project were open: nothing is noticed, prompted, reported or popped up about it, no project name is reported, it is never tied to a project, never raises the "set this project up" question, never changes what the dashboard says the computer is working on, never counts as the computer holding media, and its clips never raise the window about media outside the shared tree. An editor working in "Untitled Project" is told to save it under a real name to be asked about it.

- Who: the editor at that computer.
- Setting: Ignored Resolve projects. Does: lists the Resolve project names the product leaves completely alone on this computer. Default: "Untitled Project" and "New Doc". Who: the editor at that computer. Applies to: a computer. Search words: ignore project, scratch, untitled, new doc.

### The product follows which Resolve project is open

The app follows which project is open in Resolve, and in which library, and tells the dashboard (unless it is scratch or ignored). A brief loss of connection is not taken as a change of project. The check for media outside the tree keeps working for the whole Resolve session; if it loses Resolve, the app says so instead of going quiet.

- Who: the editor at that computer; shown to admins on the dashboard.

### A Resolve project is tied to a project in the tree

Each Resolve project name (trimmed, capitals ignored, up to 256 characters) is tied to at most one project in the tree, so the product knows where its media belongs. A tie records the Resolve project's name, the project, its folder, whether it was made automatically, by an editor or by an admin, who and when.

- The product ties a name on its own only when it exactly matches one project: the Resolve name equals, ignoring capitals, accent spelling, and treating hyphens and underscores as spaces, either a project's whole name or the last folder of its path, for exactly one project. Two projects with that name (for example "2025/Shinto" and "2026/Shinto") mean no tie. A folder in the projects tree that is not a registered project but has that name also leaves the choice to a person. When the tree cannot be read, nothing is tied.
- A looser guess, counting shared words, is used only where a wrong answer costs nothing (a suggested destination); it never makes a tie.
- The first time a person opens a Resolve project that is tied to nothing, the app asks them once whether to set it up, and they can then pick or create its folder on the server.
- The first tie wins and cannot be set again; two at the same moment cannot both win. A second attempt is told "already mapped. Ask an admin to change it."
- The first tie may be made by an admin for any name, or by an editor only for a Resolve project one of their own computers has reported open: "'<name>' is not a Resolve project any of your computers has reported. Open it in Resolve first, or ask an admin".
- Only an admin may change or remove a tie ("admins only: destination roots are fixed once set"). A removed tie is worked out again from the next report.
- Tying to an unknown or inactive project is refused by name.
- Resolve project names that computers have reported and that have no tie are listed for an admin.

- Who: anyone signed in sees every tie; an editor makes a first tie for their own reported project; an admin makes, changes and removes any.
- On its own: the tie, from an exact name match with exactly one project.
- By hand: an admin sets or changes any tie, and a tie set by hand is never replaced by an automatic one.
- Ways in: from the question the app asks when an untied project is first opened, and from the list of Resolve projects and their folders on the dashboard.

### Everyone can see where FIX ALL puts files for each Resolve project

A list on the dashboard reads "Resolve project, then where "Fix all" puts its files. The first match is kept; only admins change these." It is a table of Resolve project, the folder its files go into, and the source ("admin (<who>)" or how it was matched); Resolve projects seen but not tied show "no match", "seen, not mapped". The list refreshes itself every 30 seconds, but not while a folder picker is open. An admin can pick an active project, or "remove (match again)", and "Set"; or "Browse" the whole Projects tree (folders marked "project" and "same name", "Files go into Projects/<folder>", "Pick", "no folders here"). Any folder under Projects may be picked, registered as a project or not. Refusals: "admins only: destination roots are fixed once set"; a folder outside the Projects tree; "no such folder under Projects/: '<rel>'"; "unknown project '<project>'". With nothing yet: "Nothing yet. These appear when an app reports an open Resolve project."

For each computer, a person also sees: "open in Resolve[ on <computer>]: <Resolve project>, files go into <folder> (set by an admin / matched by itself, then kept; admins change it in the list of Resolve projects and their folders)"; when nothing matched, "no match", "no project in the tree matched; an admin can map it"; when nothing has been reported, "no Resolve project reported yet". A person with several computers can choose between "last to report" and each computer.

- Who: anyone signed in reads it; an admin changes it.
- Ways in: from the list of Resolve projects and their folders, and from the per-computer view.
- Name and search words: Resolve projects and their folders. Search words: Resolve project, fix all folder, destination, mapping, project roots.

### Nothing is copied or fixed for a project that is no longer open

Before showing or acting on any row of a scan or a fix, the app checks that the same Resolve project is still open. A clip listed from another project is refused: "Not copied. This clip belongs to the Resolve project "<A>", but "<B>" is open now. Open "<A>" and press FIX ALL again." When either name cannot be known, nothing is refused.

#### Lessons

- Met: RSV-052, RSV-053, RSV-054, RSV-055, RSV-056, RSV-057.

## Missing clips, relinking and refreshing

### The product watches the open timeline and sorts every clip by where its file is

While Resolve has a timeline open, the app looks at every clip on every video and audio track, including each angle inside a multicam clip and inside compound clips. A change the editor makes is noticed within a few seconds, and at worst within about a minute; when nothing has changed nothing is re-read, nothing is asked of Resolve during playback, and the looking never makes Resolve stutter for the editor or for other programs talking to it. Titles, generators, adjustment clips and anything with no media file are ignored. Each clip falls into one of these:

| Situation | What it means | What happens |
|---|---|---|
| Fine | In the shared folder, written the shared way, and the drive letter leads to the right place. | Nothing. |
| Plays here only | In the shared folder but written with this computer's own path, so it is offline on every other computer. | Repointed to the shared spelling on its own (see "Clips stored under this computer's own spelling are repointed to the shared spelling without asking"). |
| Outside the shared folder, present here | It will never reach the server or other editors. | Offered to the editor to fix, unless skipped (see "A clip outside the shared tree raises a window offering to fix it"). |
| Another computer's private path, not here | It can never come online here. | Named to the editor, once per path (see "Clips pointing at a path only another editor's computer has are named to the editor"). |
| The shared drive letter is wrong on this computer | The letter is not mapped at sign-in, or points at the wrong folder: a set-up problem. | One warning per breakage, naming the first such clip. It says the clips will show offline in Resolve while transfers carry on, and on Windows offers to repair the drive letter (see "The editor repairs the shared drive letter"). Once clips resolve again, a later breakage warns again. |
| Missing | Written the shared way, drive letter healthy, file not on this computer (normal for an original never downloaded to a remote editor's computer); an empty path counts as missing. | Counted as missing, unless a usable proxy is here (see "A clip whose original is not here is not missing when its proxy is"). If this computer itself moved that file when the studio moved it, the editor is offered to point the clip at its new place. |

A clip whose file exists at its shared path is never flagged, offered for fixing or warned about. A clip inside the b-roll archive whose original is not on this computer is normal on a remote computer (only clips sent to Resolve are brought down), so it is never counted as missing, whether reached through this computer's tree or the server's drive.

Whether the drive letter leads to the right place is checked at most every 2 seconds; on Windows a letter pointing at this computer's own network share is followed back to its folder, in any display language. If that check itself fails, the letter is taken as healthy, so a fault in checking never floods the editor with warnings. When the app knows the drive holding the shared tree is absent (for example an unplugged external drive), it reports "local root is not available (drive disconnected?)" and makes no other judgement until the drive is back; when it cannot tell, it carries on. While the shared drive points at the server for grading, the drive check and the clip checks stand aside.

Totals kept: clips outside the tree (skipped ones included), clips on a broken drive letter, missing clips, and when the last full look finished. The first 50 missing clips are kept by name and path for display. A look that ended early (drive out, Resolve closed, ignored project) leaves the last real totals in place. Before any look finishes, every count reads "not checked yet", never zero.

- Who: the editor at that computer.
- On its own: the situation of each clip, from its path, the shared folder and the drive letter.
- Windows and macOS: Windows checks where the drive letter leads; macOS checks the shared path at its place in the local shared folder.

### Pointing a clip at a different file keeps every edit and is reported only when Resolve shows it

A relink points an existing clip in the media pool at another file; every timeline use of the clip is kept. Resolve silently refuses to relink a clip to a path it cannot open, its replace call returns nothing even when it works, and in a shared project it can apply a relink seconds to minutes later. So:

- A clip is relinked only to a file that really exists, is playable media of the clip's kind (never a shortcut), and is in no place the product may delete.
- If the clip already points at that file (ignoring letter case and slash direction), nothing is done: "Already linked to <path>".
- Otherwise the product tries a few times over a few seconds and judges success by reading the clip's path back from Resolve after a wait, never by Resolve's own answer; a retry happens only after that re-read. Each clip's path is read again just before it is relinked.
- Messages: "Relinked to <path>"; "Resolve didn't answer. Make sure a project is open, then try again."; and, when Resolve accepted the request but the path did not change, "Copied the file in, but Resolve wouldn't relink it. Close the clip's timeline and use Scan whole project again."
- A relink during which Resolve raised any error is tried again on the next pass, never remembered as settled.
- Resolve cannot relink subtitle clips: a relink that meets one re-imports it from the new place or names it to the person, and never counts it as fixed.
- Resolve reports an image sequence by a bracketed path that never exists on disk: an image-sequence clip counts as online when its first frame exists, and is relinked by pointing at that first frame.
- Resolve's media pool can show a relinked clip as offline until the bin changes: the product checks each clip's status itself, and tells the person that switching bins refreshes the display.
- Any new way of changing where clips point (an interchange file, for example) is proven on a real Resolve before it is relied on; Resolve rejects hand-edited project and timeline interchange files.

### Resolve is made to re-read a file that changed under the same name

Resolve does not re-read a file swapped under an existing clip. When a clip's file is replaced under the same name (a stand-in replaced by the proper file, a file made again), the product relinks the clip to the same path to make Resolve read it again, and judges success by the clip's length or picture size changing, never by its path; proxies are attached only after Resolve shows the new file's length and resolution. A clip that was playing a proxy is still playing it afterwards. This is not recorded for undo. Answers: "Re-read <path> from disk"; "Re-read <path>; its geometry did not change"; "Re-read <path>; Resolve did not answer cleanly" (tried again later). Clips re-read this way are counted in every count of Resolve changes shown to editors and admins.

### An editor relinks offline clips to files found in the tree

The editor can ask the product to find the files for offline clips, for just the open timeline's clips or for the whole project. For each clip the product looks for files of the same name in the shared tree. When several are found, they are ranked by the longest matching end of the path, then by the folder most other clips were found in, then by the larger file, and clips with more than one possible file are shown first so the editor can choose. Nothing is relinked to a shortcut, to a file that is not playable media of the clip's kind, or into any place the product may delete (its own bin of removed files among them). Every relink is recorded so it can be undone.

- Who: the editor at that computer.
- On its own: the best candidate for each clip, from the ranking above.
- By hand: the editor sees each pick before it is made and chooses another candidate for any clip.

### Resolve holds its media files open

Resolve keeps the files it uses open, so they cannot be moved, renamed, replaced or deleted while it has them. Every such change the product makes expects this: it tries again later, reports what stayed where it was, and tells the editor that closing Resolve lets it finish. Render In Place files exist only on the computer that rendered them: in a synced project they reach the server like other media, or, before media moves, the editor is told which clips will be offline elsewhere.

### Changes the product makes in Resolve unasked are limited and retried by themselves

Changes made without anyone pressing a button (repointing a clip to the shared spelling, attaching proxies) run for a given project and kind at most once every 15 minutes, and at most 8 times a day per project across all kinds; the limits survive restarts and updates, and a clock put back does not stretch them. A change held back by a limit is carried out by itself as soon as the limit allows, without a restart. Reaching the daily limit is shown to the editor in the app's Resolve status and on the dashboard as a set-up problem on that computer (a computer that keeps rewriting a project is set up wrongly). Waiting changes are kept once each, and checked against Resolve at most once per pass however many projects or clips wait. A large batch never blocks noticing which project is open, new findings, or quitting and updating.

A change counts only when Resolve shows it took; one that changed nothing is not tried again until the file or clip changes. A busy or absent Resolve leads to a later retry, a real refusal is not retried until the file or clip changes, and repeats are summarised rather than listed one by one. Repeating checks ask cheap questions first and remember each answer until the file's size or date changes, while a real deletion still shows within the next report. FIX ALL and other work started by a button are never limited.

- On its own: when an automatic change may run, from the limits above.

### The app's settings window shows Resolve's state and what is wrong with the open project's media

Present once the app has anything to say about Resolve:

- "Connected to Resolve", or red "Not connected to Resolve right now".
- Red "Resolve has not answered <what it asked> for Ns. Nothing is wrong with your sync; Resolve itself is busy" after more than 20 seconds.
- "Project open: <name>" or "No project is open in Resolve".
- Each when not zero and the project has been checked, in red: "N clips are stored outside your synced folder, so nothing is backing them up"; "N clips in this project are offline"; "N clips point at a drive letter this computer does not have"; "N clips were left alone: their path is not one CC Sync may rewrite"; then the "SCAN WHOLE PROJECT" button.
- For up to 3 projects not open whose clips exist only on this computer: red "N clips in '<project>' are only on this computer. Open that project in Resolve and press FIX ALL"; beyond that "...and N more projects".
- "Proxies attached to clips: N", plus ", N clips re-read after the file changed" and ", N could not be attached: <why>" (red when any failed).
- Red "N clips still on the preview copy: the editing proxy did not arrive (<why>). Send them to Resolve again to ask for it."
- Red "N proxies skipped: this disk is low on space" / "...: this computer's proxy limit was reached" / "...: the list was too long to finish".
- The state of the shared stills folder (red unless all is well).
- The daily limit on changes made unasked, when reached.
- When it was checked: "Checked just now" (under 90 s), "N min ago" (under 90 min), "N h ago" (under 48 h), otherwise "N days ago".
- "UNDO LAST FIX" when the last change can be undone (see "The editor undoes the last change the product made in Resolve").

Anything not yet measured reads "not checked yet", never zero.

- Who: the editor at that computer.
- Name and search words: Resolve status on this computer. Search words: Resolve, offline clips, missing media, scan project, connected.

### The dashboard shows Resolve's health on each computer

For each computer, from its reports: how many clips point outside the shared tree, how many through a wrong drive or path, how many are missing, how many were skipped, when the last scan finished, and the Resolve projects not open whose clips exist only on that computer (up to 20, with counts, and when that look finished). Also: whether the app is connected to Resolve and why not, which project is open, whether a request to Resolve has been waiting and on what and for how long, up to 50 missing clips, up to 50 clips left alone because their path is not the shared one, proxies attached and proxy gaps, the last proxy result, b-roll stand-ins whose proper proxy gave up (count and first reason), clips given up on for proxies (repeated failures, low disk, a per-project limit), the stills folder check, stand-ins still owed, clips skipped now and ever, stray project folders (count and size), project folders that were moved, bytes waiting in a folder for footage to be brought in, and the daily limit on changes made unasked when reached. Each part is replaced by every report that carries it, so a problem that is over clears; when the computer stops sending a part, it is cleared. Anything not yet measured reads "not checked yet", never zero.

- Who: an admin, and the editor for their own computers.
- Name and search words: Resolve health per computer. Search words: Resolve health, missing clips, outside tree, computer, offline.

#### Lessons

- Met: RSV-073, RSV-074, RSV-075, RSV-076, RSV-077, RSV-078, RSV-079, RSV-080, RSV-081, RSV-082, RSV-083, RSV-084, RSV-085, RSV-086, RSV-087, RSV-088, RSV-089, RSV-090, RSV-091, RSV-092, RSV-093, RSV-094, RSV-096, RSV-097.

## Proxies in Resolve

### Synced proxies are attached to their clips by themselves

In the open project, clips whose proxy is missing or out of date are pointed at the proxy files that have synced into the tree, soon after a proxy arrives; with nothing to do, nothing is asked of Resolve. A clip whose stored proxy path is dead on this computer (Resolve keeps a clip's proxy path separately, and it beats a proxy sitting beside the original) is repointed to the matching proxy in the tree (same rate, start timecode and frame count), in the shared spelling, copying nothing. After every import the product makes into Resolve, it attaches the clip's proxy itself and checks it took; a refused proxy never fails the import. For b-roll archive clips, frame counts tell a lower-quality stand-in from the proper proxy. Proxies of every valid kind are attached, older MP4 proxies included, and every proxy left unattached carries a reason the editor can see. The work counts towards the limit on changes made unasked, and every attach is saved first and recorded for undo. The last result is shown: attached, refreshed, failed, when, and a reason such as "Resolve would not attach N proxy file(s) (first: <name>). A timecode that does not match the original is the usual cause."

- Who: happens on its own on the editor's computer.
- Setting: Attach synced proxies in Resolve. Does: points clips in the open project at the proxies that have synced to this computer. Default: on. Who: the editor at that computer. Applies to: a computer. Search words: proxies, attach proxy, proxy link, offline proxy.

### A clip whose original is not here is not missing when its proxy is

Outside the b-roll archive, a clip whose original is not on this computer is not counted as missing when a proxy of the same name sits in the Proxy folder beside where the original would be, unless Resolve has already refused that exact proxy for that clip. Inside the b-roll archive, it is not counted when the clip has a proxy beside it on this computer or a preview standing in for it on this computer. These answers are kept for about a minute.

### What Resolve checks when a proxy is attached

Facts about Resolve: it pairs a proxy with its clip only by exact file name, so a proxy carries exactly the original's name, byte for byte, on every computer. When a file is attached as a clip's proxy, Resolve checks it matches (timecode and frame count) and may refuse; a proxy whose timecode is missing or differs from its source's is refused, so every proxy carries exactly the timecode its source's timecode track states (see Proxies and file moves: What a proxy must be). Messages: "Proxy relinked to <path>"; "Resolve wouldn't accept <path> as this clip's proxy" (remembered, so that proxy no longer counts as usable for that clip); "Resolve didn't answer. Make sure a project is open, then try again." (not remembered). Each attached proxy is recorded and can be undone. The product can read a clip's proxy state as Resolve shows it: a resolution such as "1920x1080" when online, "Offline" when attached but unreachable, "None" when there is none.

#### Lessons

- Met: RSV-098, RSV-099, RSV-100, RSV-101, RSV-102.

## Colour look-up tables (LUTs)

### Every Resolve lists the studio's shared LUTs

The studio keeps one shared LUT library, "Assets/Luts" in the shared tree, which every Resolve reads directly. On every computer, wired ones included, it is added to the end of Resolve's Preferences > System > General > LUT Locations, keeping the editor's own entries: on Windows under the shared drive letter (P:\Assets\Luts unless the site chose another letter), so it reads the same on every Windows computer, and on macOS under the local path. The app checks this about every 15 minutes and repairs it. Outcomes:

- Library not on this computer yet: "the LUT library <path> has not synced to this machine yet".
- Added: a running Resolve is asked to re-read its LUT list (the same as Project Settings > Color Management > "Update Lists").
- Resolve running: "Resolve is running - its LUT Locations will be set the next time it is closed (Resolve overwrites its own preferences on exit)".
- Preferences not as expected: "Resolve's preference files are not in the expected shape - add <location> by hand in Preferences > System > General > LUT Locations".
- Already there: nothing changes.

Each warning is shown once while it stays the same, and again only after it has cleared and come back.

- Who: happens on its own on the editor's computer.
- Setting: Shared LUTs in Resolve. Does: keeps Resolve's LUT list pointed at the studio's shared LUT library. Default: on. Who: the editor at that computer. Applies to: a computer. Search words: LUT, shared LUTs, LUT locations, colour.

### Every editor's computer receives the shared LUT library and stills gallery without ticking anything

Two shared libraries reach every editor's computer by default: the LUTs folder ("LUT library") and the stills folder ("Resolve gallery"), both under the tree's Assets folder. The server sets them up on the NAS if missing, and every editor's computer receives them, except the computers of suspended editors. They are not projects: they cannot be ticked, never appear among projects and are never counted. A site can replace the list with its own folders under Assets (the change takes effect within seconds); an entry with no letter or digit, or one that would clash with an earlier one, is left out. A library already set up somewhere other than where the site says is left alone. When the libraries cannot be set up, a problem opens on the dashboard: "The shared asset libraries (the LUT library) could not be set up: <error>. Editors will see their LUTs missing in Resolve." The repair: check the NAS's file sharing, then the site's shared-folder setting. It closes itself on the next success. Within a library, video, unfinished transfers and operating-system clutter (Mac folder records, Windows thumbnail caches and folder settings, temporary files, folders named __MACOSX and files whose names start with "._") never travel, and that rule cannot be undone by accident.

- Who: an admin chooses the libraries.
- Setting: Shared asset libraries. Does: which folders under Assets reach every editor's computer without being ticked. Default: the LUT library and the Resolve gallery. Who: an admin. Applies to: the site. Search words: shared libraries, LUT library, gallery, assets.

### Resolve picks up shared LUTs it missed at launch without a restart

Fact about Resolve: it scans its LUT locations once, at launch. If the shared drive was not connected yet, the shared LUTs are missing for the whole session, and Resolve's own log records that the folder was not there. The app notices this for the current Resolve session and, once the folder is reachable, asks Resolve to re-read its LUT list, once per Resolve session, without restarting Resolve or changing its preferences; if that fails (for example no project open) it tries again later.


### LUTs found only on one computer are offered to the team

The app looks in Resolve's own LUT folder and Resolve's other LUT locations on this computer for LUT files (the usual LUT file kinds) that the shared library lacks. Not counted: files already in the shared library; a file of the same name and size anywhere in it; Resolve's own factory LUTs (the camera makers' and standards folders Resolve ships, such as ACES, Arri, Blackmagic Design, Canon, DJI, Film Looks, Sony and the rest, extendable by a setting); folders named __MACOSX and files whose names start with "._" (junk from packs unzipped on a Mac); and DCTL files, because Resolve loads DCTLs only from its own LUT folder and never from a shared extra location. A file whose place in the shared library is taken is not offered.

While any are found, the app's menu shows "► N LUT(s) only on this computer: share with the team". Choosing it asks "Share these LUTs with the team?": "<N LUTs> on this computer (<X.X> MB) are not in the shared library. Copying them to <library> puts them on every editor's computer. Your own copies stay where they are.", with up to 12 names ("… and N more"), each going where its pack folders put it, and "SHARE". Up to 200 are listed. Nothing is copied or moved unasked. Sharing copies, never moves: it never overwrites (counted as skipped), never deletes the original, refuses any place outside the shared library ("<name>: refused, <rel> is outside the LUT library"), and leaves nothing half-copied. Then it counts again: "Shared <N LUTs> with the team." plus " <E> could not be copied - see the log.", and asks Resolve to re-read its LUT list if anything was copied. The offer clears once acted on. Refusals: "LUT sharing is not set up on this computer."; "No LUTs to share - the library already has everything here."; "The shared LUT library hasn't synced to this computer yet - try again later."; "Another CC Sync window is open. Close it and try sharing again."

- Who: the editor at that computer.
- Ways in: from the app's menu. The app's settings window shows how many there are.

#### Lessons

- Met: RSV-126, RSV-127, RSV-128, RSV-129, RSV-130, RSV-131.

## Fixing media: copying in, rehearsals and undo

### FIX ALL copies the listed clips in and repoints Resolve at the copies

Before the editor presses anything, the window states the size and the room:

- "N clips, X GB in total. This computer has Y GB free." When the batch is over 90 % of the free space it adds, in red, " That is not much room. Everything copied in is also uploaded to the server." When the batch does not fit in the free space, FIX ALL is refused and the editor is told how much room is needed. When free space cannot be read, or reads as zero, the line is left out and nothing is refused on its account.
- "N of M files are online-only in your cloud drive and have to download before they can be copied. That happens automatically, but it can be slow, so the bar will sit at 0% for those while they download." (Cloud drives that keep files online-only, such as Google Drive or OneDrive, behave this way.)

Pressing "FIX ALL" starts the copy. FIX ALL and SKIP are disabled until it finishes, so a second press can never start a second copy of the same batch. The status reads "Copying N files in. Your originals stay exactly where they are. Nothing is moved or deleted." (plus the cloud warning when it applies). Progress, updated continuously:

- A file line and bar: `Copying "<name>": 4.1 GB of 12.7 GB · 33 MB/s · ~4 min left`. While a cloud file downloads: `Waiting for your cloud drive to download "<name>" (<size>). This can take a while`, and the copy regains full speed once reads are fast again.
- A batch line and bar: "File I of N: X GB of Y GB done" (or "File I of N").
- Speed is measured over the last 6 seconds. Time left reads "almost done", "~N sec left", "~N min left" or "~Nh Mm left".

Buttons while it runs, each answering within 2 seconds:

- "STOP AFTER THIS FILE": "Stopping after the current file finishes. Please wait."
- "SKIP THIS FILE": "Skipping the file being copied now. The half-copied file is deleted and the rest of the list carries on." Nothing is relinked for it.
- "CANCEL ALL": "Cancelling. The file being copied now is abandoned and its half-copied file deleted. Everything already copied in stays." All three buttons are then disabled.

Only a person's click stops a copy; it never gives up by itself while the file is still arriving. Closing the window during a copy asks first, and then means CANCEL ALL; the window closes once the copy has really stopped. Quitting the app during a copy asks first too. While a copy runs, other windows of the app wait, and the app never updates or restarts itself. "RETRY FAILED" is hidden until a run leaves failed, skipped or part-way rows; it re-runs only those, with the same destinations, redoing only the step that failed and reusing a checked copy already made.

After copying, each distinct clip using the file is relinked to the copy's shared spelling (see "Pointing a clip at a different file keeps every edit and is reported only when Resolve shows it"), so the project opens on every computer. A clip no longer in the media pool counts as a failure: "could not find <name> in the media pool". Per clip: "Fixed: copied to <path> and relinked N item(s)"; "copied to <path> but relink failed for K of N item(s): <reasons>". A stop while relinking takes effect between clips, never in the middle of one, and keeps the copy: "Stopped by you. <name> was copied in and N of M clip(s) were repointed at the copy. Run FIX ALL again to finish the rest."

- Who: the editor at that computer.

### The copy FIX ALL makes is safe

- The original file is never moved, changed or deleted. The copy keeps the original's file times and permissions.
- If the destination already holds an identical copy (same name or a numbered variant, same size, same content at start, middle and end; letter case ignored on Windows only), that copy is used and nothing is copied again ("already copied to").
- A name already taken gets " (2)", " (3)" and so on, up to 10,000. If something else takes the chosen name during the copy, the copy lands beside it under a fresh name instead.
- A copy in progress is invisible to syncing and to other programs under its final name until it is complete.
- Copies go only where they will sync, unless the editor chose a folder outside every project and was warned.
- The copy is checked before Resolve is touched. Nothing is relinked, and the copy is deleted, when the copy cannot be checked, the original is empty, the sizes differ ("the copy is N bytes of a M-byte original - it was cut short"), or the original changed while being copied ("the original changed while it was being copied - it is still being written. Try again once it has finished"). Message: "Copied <name>, but <reason>. Nothing was relinked and the bad copy was removed.", plus "It is still at <path> (...); delete it by hand." if it could not be removed.
- Skip this file and cancel all stop the copy at once, remove the half-finished copy and relink nothing: "Skipped by you. The half-copied file was removed. Nothing was relinked." or "Skipped by you, but CC Sync couldn't delete the half-copied file at <paths>. Delete it by hand." A skip is its own outcome, neither fixed nor failed.
- When a copy fails, the editor is told why in plain words: "<Windows or macOS> wouldn't let CC Sync read or write this file. It may be open in another program. Close it and try again."; "Your disk is full. Free up space and try again."; "The file isn't there any more. It may have been moved or renamed."; "Lost the connection to the drive this file lives on. Reconnect it and try again."; otherwise "Couldn't copy this file: <error>". A failed copy leaves nothing behind.
- A file that is only a cloud-drive placeholder (an online-only file) and then fails gives: "Google Drive (or your cloud drive) couldn't download this file. Right-click it in the Google Drive folder, choose "Available offline", wait for it to finish, then run Scan whole project again." Recognising a placeholder never blocks a copy.

- Windows and macOS: the system named in the "wouldn't let" message is the one the editor uses. Cloud placeholders are recognised on Windows.

### Nothing is copied when the copy could not end up in the right place

FIX ALL refuses before copying anything:

- "source file not found: <path>".
- When the app does not know where the shared tree is on this computer: "CC Sync doesn't know where your sync folder is, so it won't copy anything", with how to get diagnostics.
- When that location is not usable: a message naming the location and the error.
- For any destination that would leave the shared tree: a refusal naming the destination as outside the sync folder.
- "copy failed: <error>" when the folder cannot be made or no free name is left.

If the destination is not inside "Projects" or "Assets", every result adds: " This folder is outside every project, so the copy stays on this computer and will not reach the server or other editors."

### What the editor is told when FIX ALL finishes

- All done cleanly: the window closes and a notice "media copied in" says "Fixed N of M, copied X.X GB" (decimal gigabytes; a copy reused from an earlier run is not counted), "Will not sync: <names>. Its/Their copy/copies are outside every project, so it/they stay on this computer and never reach(es) the server or other editors." for copies outside every project, and "To undo: press Undo last fix in the app's settings window." when anything was relinked.
- Otherwise the window stays open, FIX ALL and SKIP come back, RETRY FAILED appears if anything can be retried, and the status shows:
  - "N of M copied in, P stopped part way, S skipped by you, F failed", starting "Stopped: " and ending ", K left alone" when stopped early;
  - copied but not repointed: up to 12 lines "■ <name>: <message>", then "Press RETRY FAILED to finish repointing them. The copy is not made again.";
  - skipped: "You skipped: <up to 6 names>. Nothing was copied in or relinked for them, and the half-copied files were deleted. Press RETRY FAILED to try them again.", and if a half copy could not be deleted: "⚠ CC Sync could NOT delete the N half-copied files: <paths>. Please delete them by hand.";
  - failed: up to 12 lines "✗ <name>: <reason>", "… and N more (the rest are in the app's log)", and for cloud files "These are online-only cloud files. Make them available offline in your cloud drive, then press RETRY FAILED.";
  - only stopped: "Nothing was moved or deleted.";
  - the "Will not sync" line and the undo pointer as above.

Every batch change to a Resolve project ends with such a summary: fixed of total, size copied, failures with the first reason, and how to undo it.

### Leftovers of an interrupted copy are cleaned up or reported

When the app starts, an empty name reserved by a copy that was interrupted (the app or computer stopped) is deleted on its own when it is certainly empty and nothing is still writing. A half-finished copy is never deleted on its own: the editor is told where it is so they can remove it by hand.

### Every change the product makes in Resolve is recorded so it can be put back

Resolve's own Undo does not cover clip relinks made by script. So for every clip path or proxy the product changes, it records the project open at that moment, the clip's name, its original file, the old and new path, and which feature made it. Changes to one project close together form one undoable change: it ends after 2 minutes with no further change to that project, except that one FIX ALL is always one change however long its copies take. An edit made after an undo starts a new change. Every change lands in the record even when many happen at once, up to 5,000 clip changes in one change; any beyond that are still made, and the editor is told that they cannot be undone. If the record cannot be written, the change still happens and the editor is told plainly that it cannot be undone. Records are kept 60 days, then deleted, along with any project's record folder left empty for a day.

### The project is saved and a backup copy kept before the product changes it

At most once every 15 minutes per project, before changing clips, the product saves the project in Resolve and exports a backup copy of it (without stills and LUTs), stamped with the date and time and kept for 60 days; copies and leftovers of interrupted saves older than 60 days are deleted, so their disk use stays bounded. Facts about Resolve: some Resolve builds cannot export a project when asked from outside, and a project open in a collaboration cannot be exported ("Resolve refused to export a backup copy (a project open in a collaboration cannot be exported)"). When there is no backup copy for any reason, the change still goes ahead. The backup copy is not used by the product's undo; a person restores it by hand in Resolve's project manager, and the app's diagnostics say where the copies are.


### The editor undoes the last change the product made in Resolve

"UNDO LAST FIX" is offered only when there is something to undo, and says what the last change was: "N clip path(s) in “<project>”, <start time>" (for the open project, else the latest of any). Undo puts every clip in the newest change not already undone, in the project open in Resolve, back where it was, newest first, so a clip changed twice ends at its first path. A proxy change puts the old proxy back, or removes the proxy if there was none. Each clip's path is read again just before it is put back. Pressing undo again goes to the change before. Each press undoes exactly one change, restoring the exact earlier state or saying it cannot. Answers:

- "Put N clip path(s) back the way they were (from <change>)." plus " M were already back." and/or " K could not be undone: those clips are no longer in this project's media pool.", naming any clip not restored.
- "Those clip paths were already back the way they were (from <change>): nothing to put back."
- "Every clip-path change CC Sync made in “<project>” has already been put back."
- "CC Sync has not changed any clip paths in “<open>”. The last change it made was in “<other>”: open that project and undo there."
- "That change was made in “<A>” but “<B>” is open. Open “<A>” and undo there: replaying it here would re-address clips the two projects share."
- "CC Sync has not changed any clip paths on this machine."
- "<change> records no changes."
- On failure: "CC Sync could not undo the last clip-path change. Open the log, and send it to your admin."

A change counts as undone only if something was put back, or everything was already back and nothing was skipped; an undo Resolve refused can be pressed again.

- Who: the editor at that computer.
- Ways in: from the app's settings window. An admin can ask for the same undo from the dashboard (see "An admin undoes, from the dashboard, a change the product made in Resolve on an editor's computer").

### An admin undoes, from the dashboard, a change the product made in Resolve on an editor's computer

"Every time CC Sync changes where Resolve looks for clips, that computer writes the change down and tells this server. Undoing one puts those clip paths back on that computer, the same as "Undo last fix" on the computer itself. It happens when the computer next reports, and only while that project is open in its Resolve."

Each computer reports its 20 newest changes (project, when started, how many clips, which features made them; names and counts only, never paths); a report without the list keeps the last one, and a damaged list reads as empty. Per computer the admin sees when, project, clips changed, and "Undo this change" ("Put back the N clip path(s) CC Sync changed in <project> on <computer>?"), or "undo asked" while one is unanswered; then the recent requests, newest first ("<ago> <who> asked to undo <project>: <state>"). After asking: "Asked <computer> to put those clip paths back. It happens when that computer next reports, and only while that project is open in its Resolve; the answer shows in its list below." Asking is refused when the computer has not reported that change: "that computer has not reported a change called '<id>'. Its list is refreshed every time it reports: reload and try again." Each request is recorded in the audit history with who asked and when. With none: "No computer has told this server about a clip-path change it could undo. On the computer itself, "Undo last fix" is in the app's settings window."

The computer carries out the undo exactly as the editor's own, for that change, once; a request delivered again after a restart is answered from what already happened, never carried out twice. It refuses while a different project is open in Resolve. The admin sees the state in a sentence:

- done, with the undo's message (or "put the clip paths back");
- waiting, with the real reason: Resolve not running, Resolve not answering, or "waiting: no project open in Resolve, will resume when one is"; the undo then happens on its own when that project is open;
- trying again ("retrying on this computer's next report"), when it failed unexpectedly ("the undo could not run on this computer (<error>)");
- failed, "this computer no longer has the record <id>: it has been cleared, or this is not the computer the change was made on", when the record is gone (past 60 days) or never was there;
- failed, with the undo's own message, otherwise;
- no answer yet: "waiting for that computer to report".

A request still waiting after 7 days is given up and reported as failed "(this computer has been unable to do it for a week)". On success the editor is told "<admin> put back the clip paths CC Sync changed in Resolve." (titled "... clip paths put back"). When the editor has withheld project reporting, the project part is hidden from the admin, an undo still finds the one matching change and refuses when it cannot tell which, and the answer does not name the project. Answers are matched to the computer even when it was renamed.

- Who: an admin.
- Ways in: from the per-computer view. The dashboard's guide to recovering from a Resolve problem points there.

#### Lessons

- Met: RSV-132, RSV-133, RSV-134, RSV-135, RSV-136, RSV-137, RSV-138, RSV-139, RSV-140, RSV-141, RSV-142, RSV-143, RSV-144, RSV-145.

## Grading from the server's originals

### An editor grades from the server's originals and switches back to proxies

An editor whose computer holds proxies can point the shared drive letter (P: unless the site chose another) at the server's tree, so Resolve streams the full-resolution camera originals while they grade, then point it back. Resolve's paths stay the same, nothing is relinked, and syncing is unaffected.

- To the server: "Point P: at the SERVER's tree so Resolve streams full-resolution originals while you grade? Pause playback first. Frames come over the network, so scrubbing is only as fast as your connection. In Resolve, set Playback > Proxy Handling > Prefer Camera Originals to actually use them. Syncing is not affected. Swap back when you are done with FINISH GRADING." Button "SWAP P: TO SERVER". Success: "P: now shows the SERVER originals"; already so: "P: already shows the SERVER originals".
- Back: "Point P: back at this computer's local copy (proxies)? Set Resolve's Playback > Proxy Handling back to Prefer Proxies." Button "SWAP P: BACK". Success: "P: is back to your local copy (proxies)". If that fails, a second way of pointing the letter at the local copy is tried; if both fail, "P: could not be restored (<error>) - remap it by hand or re-run the installer", or, with no local folder set, that the letter is now unmapped.
- When a login is needed: a window "► SERVER LOGIN", "Windows needs your login for <server name or 'the server'> to stream originals. Use the same username and password you sign in to CC Sync with. It is saved on this computer, so you will only be asked once." The username is filled in with the signed-in editor and the cursor starts in the password. CANCEL stops there; CONNECT tries the swap again; "username and password are both required". If the window cannot open: "Couldn't open the login window. Restart CC Sync and try again." A password is never shown in a message or a log, and the system never prompts by itself.
- Refusals: the server's share is not known; "P: is currently mapped to <target>, which CC Sync did not create. Swapping would replace it and CC Sync cannot put it back."; "CC Sync could not tell what P: is mapped to, so it is being left exactly as it is. Nothing was changed. If P: is not mapped at all, restart the CC Sync app or re-run the installer to put your local mapping back, then try the swap again."; "the server did not answer within 30s - the drive was not remapped". Each step gives up after 30 seconds.
- The system's own refusals, each "System error N: " and a plain sentence: access denied; network path not found (is the server up?); share no longer available; wrong resource type; network name not found; letter already in use; wrong password; already connected to this server as a different account (disconnect or sign out and try again); connection cancelled (the server wants a login); not a valid device name; no network provider accepted the path; user name or password incorrect; blank password not allowed; any other "System error N mapping P:".
- A failed switch leaves the drive exactly as it was before: "Swap stopped: <message>", or "The P: swap failed. Copy the diagnostics for your admin from the app's help." While the drive points at the server, the drive-letter warning and the clip checks stand aside.

The server's share comes from the site's settings, or is worked out from the server's address and the NAS's own folder layout, or is set on the computer. The choice is offered only on a computer that holds proxies (not on one that works directly off the server) and only when a server share is known.

- Who: the editor at that computer.
- Setting: Server share for grading. Does: where the shared drive letter points while grading from the server's originals; off switches grading from the server off on this computer. Default: from the site's settings. Who: the editor at that computer. Applies to: a computer. Search words: grade, server originals, swap drive, full resolution.
- Windows and macOS: on Windows the drive letter is pointed at the server's share. On macOS, where Resolve reaches the shared drive through its mapped-mount preference, which can only change while Resolve is closed, the editor is asked to quit Resolve for the switch and for the switch back.

### The editor repairs the shared drive letter

"REPAIR P: NOW" answers: "P: is already pointing at your synced folder."; "P: is showing the server originals because you asked for a grade swap. Use FINISH GRADING to put it back."; "P: is mapped to <target or 'something else'>, which CC Sync did not create. Nothing was changed. Ask your admin before removing it."; when unmapped, it maps it back to the synced folder; and on a computer where it cannot: "P: cannot be repaired from here on this computer." with how to get help. A mapping the product did not create is never removed.

- Who: the editor at that computer.
- Windows and macOS: Windows only; a Mac has no drive letter.

### A remote editor brings one grading frame of a camera raw original

A remote editor who holds only proxies can bring just enough of a camera raw original from the NAS into Resolve to set the raw controls on the real clip, without downloading the whole clip. That partial file is never taken for the footage by any part of the product: it is never counted, uploaded, checked or used to make proxies as an original, and it gives way to the real original when that is brought down.

- Who: the editor at that computer.

### An editor asks for originals from inside Resolve

The app adds entries to Resolve's own Scripts menu: "Bring originals - selected media pool clips", "Bring originals - timeline clips between In and Out", "Bring originals - whole timeline", "Stop originals - selected media pool clips", "Stop originals - timeline clips between In and Out", "Stop originals - whole timeline"; the clip under the playhead can be asked for, or stopped, too. Every way of asking for originals has a way to stop. The app acts on the request within a couple of seconds.

- Each clip is turned into its file. A multicam or compound clip is turned into its angles' files. A path in the studio's drive spelling or in this computer's own spelling (a Mac's mounted drive) both work.
- Each file is matched to the ticked project that holds it. Files in no ticked project, and files that are not camera originals (proxies, unfinished, hidden or non-video files), are counted and reported, not asked for. Files in an upload-only project are sent, so the server's refusal reaches the editor.
- The pick is recorded for that project and this computer, and an accepted pick starts the download at once (see Sync: What syncs where).
- If the server cannot be reached or fails, the request is kept and tried again; parts already answered are not sent twice. Up to 10,000 clips go in one request. A request not answered within 1 hour, or one that cannot be read, is dropped and the editor is told so.

The editor gets one notification per request, built from these parts in this order:

- each distinct refusal sentence from the server, word for word and first (for example the refusal of a pick in an upload-only project);
- for any other refusal: "The server refused part of this request." followed by the server's own reason when it gave one;
- when adding worked: "Bringing {N original(s)} to this computer ({size}). The app shows progress." (the size is left out when the server gives none);
- when removing worked: "Stopped bringing {N original(s)}. Files already on this computer stay.";
- "{N clip(s)} could not be matched to a file.";
- "{N clip(s)} is/are not in a project this computer syncs.";
- "{N clip(s)} is/are not camera originals.";
- with no refusal and no success it starts "Nothing was queued:" (or is just "Nothing was queued." when there is nothing else to say).

- Who: the editor at that computer.

#### Lessons

- Met: RSV-146, RSV-147, RSV-148.

## Other givens on the editor's computer

### Resolve's gallery on every computer uses one shared stills folder

Fact about Resolve: the gallery on the Color page (stills and PowerGrades) is kept in a folder on one of Resolve's media storage locations. Computers sharing a project library must agree on it, or Resolve warns at every launch that the stills location differs; a Mac can give a location a second, Windows-style spelling that other computers see. The shared folder is "Assets/Stills" in the shared tree. The product adds it as a media storage location (before Resolve's own last entry, never touching the first) and points the gallery at it; on macOS the location carries the Windows spelling so the shared library agrees. The gallery is never pointed at a folder that has not arrived. Outcomes: "the shared stills folder <path> has not synced to this machine yet"; already set (nothing changes); "gallery moved to <root>\.gallery" (with / on macOS); "Resolve is running - the shared stills location will be set the next time it is closed (Resolve overwrites its own preferences on exit)"; "Resolve's preference files are not in the expected shape - add <root> as a media storage location by hand, and set the gallery to it". It is checked with the shared LUTs, and each warning is shown once while it stays the same, and again only after it has cleared and come back.

- Who: happens on its own on the editor's computer.
- Setting: Shared stills gallery in Resolve. Does: keeps Resolve's gallery pointed at the studio's shared stills folder. Default: on. Who: the editor at that computer. Applies to: a computer. Search words: stills, gallery, PowerGrades, media storage.

### The product's own graphics work gives way to Resolve

Resolve holds graphics memory that grows over a session and starves other players. While Resolve is open, the product's own graphics work on that computer gives way to it, and any check of why playback stutters looks at Resolve's graphics memory before blaming the network or the file.

### Refusals about Resolve lead with what to do

A refusal shown to an editor or an admin leads with the part that says what to do. Where a message must be shortened, it is shortened deliberately in the middle, never cut off mid-word or before the part that names what to close.

#### Lessons

- Met: RSV-149, RSV-152.
