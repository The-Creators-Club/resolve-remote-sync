# Sync, part 1 of 2

Sync gets footage between the studio's server and each editor's computer: the camera originals an editor shoots or brings in go up to the server, and the proxies, project files and chosen originals of the projects ticked for that computer come down, laid out exactly as on the server. Editors meet it through the app on their computer and the dashboard; an admin decides with them which computer takes which project, and watches and stops the whole studio's syncing from the dashboard. Syncing is the core of the product, on the server and on every editor's computer: it is never a part that can be switched off, and syncing and its state are always present on the dashboard and in the app, whatever parts a site has switched on. This part covers what syncs where, a plan belonging to each computer, wired and remote computers, upload only, deletions and the stops that protect footage, the editor's pause and studio-wide stops, files that never sync, names, the sync drive, disk space, and transfers that are stuck, slow or need sharing fairly.

## What syncs where

### A project is a folder on the NAS at any depth, marked as a project

A folder on the NAS becomes a project when it carries the product's project mark. It may sit at any depth inside the project tree, inside series or categories, and the top of the tree itself is never a project, nor is anything inside a hidden folder (a name starting with a dot) or inside another project. The mark holds the project's permanent identity, made of lowercase letters a to z, digits and hyphens, which is also the last part of the project page's address. A mark carrying anything else is ignored.

A newly marked folder appears as a project, ready to sync, within about five minutes, and is synced to no computer until someone ticks it. The project's name as shown is its path inside the project tree, and it follows the folder: when the folder is moved or renamed on the NAS, the shown name changes and the project keeps its identity, its ticks, its history and everything already synced, without anything travelling again.

Every computer reproduces each project at the same path inside its own copy of the tree, with the server's exact names and nesting, so a project opened on any editor's Windows or macOS computer finds every clip at that computer's own place for the same server file.

- On its own: a marked folder becomes a project, and its shown name follows the folder's path.
- See Proxies and file moves: Moves that reach every computer, for what each computer does when a project is moved on the server.

### A full tick sends a project's camera originals up and brings its proxies and other files down

When a project is ticked on a computer for full sync:

- **Camera originals go up.** Every camera video file in the project's folder on that computer, at any depth, is copied up to the same place on the server. The kinds carried are the common camera and video files: Blackmagic RAW, QuickTime, MP4, MXF, AVI, AVCHD, Matroska, RED, Canon Cinema RAW Light, MPEG, Windows Media, WebM and Insta360 360 video, recognised whatever the letter case of the name. An upload never deletes anything on the server and never replaces a file already there.
- **Proxies come down.** Everything inside any folder named Proxy (at any depth, any letter case) comes down from the server, smallest first, so a computer can show everyone's footage. For a clip downloaded from YouTube the downloaded original goes up to the server from the computer that downloaded it, and comes down by itself only to the computer of the editor who asked for it, when that computer syncs the project; every other computer gets only its proxy, and anyone else who wants the original fetches it by hand.
- **The project's other files are kept in step.** Edit projects, sound, graphics, documents and every other file that is neither video nor a proxy are kept the same on the NAS and on every computer with a full tick, both ways, and a change is noticed as it happens.
- **The folder layout comes down.** Within one pass of the tick, every folder of the project on the server exists on the computer, empty folders included, so a team's prepared folders appear before anything is in them. A folder whose name starts with a dot is never created.
- **Originals picked for this computer come down**, and no other originals do (see "An editor picks camera originals to come down to one computer").

Nothing comes down that was made on this computer and nothing goes up that came down: originals brought down are never sent back, and proxies that came down are never sent up. A proxy made on this computer goes up to the server's Proxy folder at the same place, never replacing one already there.


### New footage starts going up about two minutes after it stops changing

When a camera video file appears in, changes in, or is moved into a project ticked on this computer, it starts uploading on its own soon after it settles: once nothing has happened to it for about 10 seconds and it is at least 2 minutes old, so a clip still being copied off a card is never sent half-written. Everything is also checked over at least every 5 minutes, so a change the computer was never told about is still found and sent.

The editor's pause and every stop also hold new footage back, and resuming starts it watching again.

### Projects ticked on a computer sync one at a time, in the order set for that computer

Nothing syncs to a computer until a project is ticked for it, and unticking stops it. A computer works through its ticked projects one at a time, in the order set on the dashboard for that computer. An editor or an admin can move a project to the front of one computer's queue, or set any order, and the new order takes effect within about a minute without redoing projects already handled this round.

When a file changes in a ticked project on the editor's computer, that project moves to the front of the rest of the queue, right after the project being synced now; it never interrupts the project being synced now. A change in a project already handled this round does not send it round again; it only shortens the wait before the next round. Once everything is caught up, the computer looks again about a minute later.

- Who: the editor for their own computers, or an admin.
- Ways in: from the per-computer view, and from a person's own account page.
- See The dashboard: Ticking and unticking, for the controls.

### A tick or untick reaches the computer within about a minute

A tick, an untick, a change of mode or of order made on the dashboard reaches the computer within about a minute, and the dashboard shows the change taking effect almost at once. A change made any other way is still put into effect within about a minute.

### Only computers holding a full tick for a project receive its files

A computer receives a project's files only when that project, or a project that includes a folder of it, is ticked for full sync on that very computer. These receive nothing of it:

- a computer with an upload-only tick for the project (it gets only the project's empty folders, see "An upload-only tick sends every file up and brings down only the empty folders");
- a wired computer, and every computer of a person whose computers are all wired;
- every computer of a suspended editor;
- any computer, for an archived project (an archived project's ticks count for nothing, and so do those of an archived project that includes a folder of another).

The NAS always keeps its own copy. A computer the product cannot link to any known person is never touched: whatever it has is left as it is. Only who receives each project ever changes this way; the project itself is never changed.

### An editor picks camera originals to come down to one computer

Proxies come down on their own; camera originals come down only when picked. A pick names a file or a whole folder of a project, for one computer, and records who asked, from where (the dashboard or from inside Resolve) and when. A folder pick means every original under that folder on the server, including anything uploaded into it later. A file can be picked before the server has seen it; it is then shown as not on the server yet, with its size unknown, and looked for again about every 15 minutes.

The project's page lists every pick for the project, for everyone, under "Camera originals brought down to one computer, beside its proxies. A folder also brings what is uploaded into it later. Stopping keeps the files already down." Each pick shows the person, the computer, the folder or file and its path (who chose it, from Resolve or the dashboard, and when, on pointing), its size on the server, and how much of it is on that computer: "cannot tell" (the computer withholds its file list or has not reported), "nothing on the server yet", or "[at least ]N of M in". "Stop" is offered only on picks the viewer may change, asking "Stop bringing <path> to <computer>? The files already there stay." With none: "No originals chosen for this project. Proxies come down as usual."

To bring more, the person chooses one of their computers that has this project ticked for full sync. With none: "None of your computers has this project ticked for full sync, so there is nowhere to bring originals to." "Browse originals" shows "Originals of <project>[/<folder>] on the server, for <computer>.", "Up a folder", folders (opened on click, with file count and size, and "Bring this folder", asking "Bring the N originals in <folder> (<size>) to <computer>, and anything uploaded into it later?") and files (with size and "Bring this file"), marked "chosen" where already picked. At most 400 files are listed per folder, then "and N more files here. Bring the folder to get them all." Before the server has counted the project: "The server is still counting this project's files. They appear here within a minute or two: press Browse originals again." With nothing there: "The server has no originals here yet." Each file shows a small picture from its proxy that opens the proxy playing in a new tab, or "no proxy yet".

Before anything comes down the person sees the plan: the total size now picked for that computer and project, counting each file once however many picks cover it, and a file not yet seen counting as nothing. The answers are "<path> comes down to <computer> on its next pass. Everything chosen there for this project is <size>." and "<path> no longer comes down to <computer>. Files already there stay." Up to 5000 additions and 5000 removals are taken in one change, removals first, and the person is told how many were added and removed.

What comes down, and what never does:

- Up to 20,000 picked files per project; beyond that the first 20,000. A file named twice, in any letter case or either Unicode spelling, counts once. A picked file is found on the server in any letter case or spelling and fetched in the server's spelling.
- Only camera originals are ever fetched: never a hidden file, a file inside a Proxy folder, an unfinished or temporary file, a file half-way through a move, or a file that is not video.
- A file already on the computer is never overwritten: at the same size it counts as here, at a different size it is left alone.
- Un-picking stops a file coming, interrupting its download if it is in flight, and never deletes what is already down. Unticking the project drops that computer's picks in it, and the files already down stay.
- Originals come down alongside uploads and never hold them up. A change to the picks is acted on at once; "Sync now" starts it at once too.
- When a picked file or folder is moved on the server, the pick moves with it; a folder pick that merely held a moved file stays.

Refusals, each in these words:

- no computer named: "say which computer: originals are picked for one computer at a time";
- an unknown computer, or an unknown or inactive project, is refused by name;
- a path that is a full path or drive: "'<p>' is an absolute path: name the file inside the project instead"; an empty one: "a pick needs a path inside the project"; one too long to be a file in the project: "that path is too long to be a file in this project"; one with a bad folder name, refused by name;
- inside a Proxy folder: "'<p>' is inside a Proxy folder: proxies already come down on their own"; the project's own mark: "the project marker is not footage";
- additions (never removals) to a wired computer: "<computer> is wired to the server: it works directly off the NAS, so every original of <project> is already there and nothing needs to come down."; to a computer without the tick: "<project> is not ticked on <computer>, so nothing of it comes down there. Tick it for <computer> first, then choose its originals."; to an upload-only tick: "<project> is set to upload only on <computer>, so no originals come down to it. Switch it to full sync on the dashboard first.";
- someone else's computer: "you can only choose originals for your own computers (admins excepted)"; nothing chosen: "choose a computer and a file or folder first".

A computer that must be updated before it can bring originals down is listed but cannot be chosen: "<computer> must be updated before it brings originals down." Every change is recorded in the history with the count and up to 100 of the paths, under the editor's name even when their computer made it from inside Resolve. A refusal reaches the editor word for word, in Resolve too.

- Who: the editor for their own computers, or an admin for anyone's.
- Ways in: from the project's page, and from inside Resolve on the editor's computer.
- See Sync, part 2: Saying truthfully what the sync is doing, for what the app shows while originals come down.

### An editor asks for originals from inside Resolve

An editor can also pick originals to come down to the computer they are at, or stop them, from inside Resolve; the menu entries, what the editor is told and how a request is handled are described in one place (see Resolve on the editor's computer: Grading from the server's originals, "An editor asks for originals from inside Resolve"). A pick made there is the same pick as one made on the project's page: it is recorded as made from Resolve, under the editor's name, starts the download at once, is answered even while syncing is paused, and is refused by the same rules in the same words.

- Who: an editor, for the computer they are at.
- When the help for the editing program is off: no entries are put in Resolve, and originals are picked from the project's page only.
- Pending: sync-1-U2

### A project can include a folder of another project

A project can include a subfolder of another project (at least two levels inside it, never a Proxy folder and never a whole project), so footage filed in one project but needed in another reaches the editor at its true path with no second copy on the NAS. The list of included folders belongs to the including project and travels with its folder on the NAS, so it survives anything done to the dashboard.

On the project's page, shown when the project has included folders or to anyone signed in: "N in, N out"; under "shares from", each folder included into this project, with "ok" or what is wrong, the subfolder, which project it comes from (a link), the detail, and "Unshare" (nothing on disk is deleted); under "shared into", each subfolder of this project included in another project, with a link. A box ("a folder from another project, e.g. 2026/Show/Episode/Interviews/...") and "Share a folder into this project" add one; an empty box answers "type or paste the folder to share (e.g. 2026/FF5/Elections/Interviewees/...)".

Adding one already listed changes nothing. Each entry records who added it and when, and the page refreshes straight after each change. A project includes at most 32 folders: "this project already shares 32 folders; remove one first". Two entries for the same folder, or one inside another of the same project's, count once. Refusals: "only an admin or an editor syncing this project can change its shared folders"; "cannot share that folder: <reason>" (with the reasons in "Each included folder says whether it works, and why not"); and, for adding and removing alike, when the NAS's projects folder is unavailable, the project is unknown or inactive, or "this project's folder marker does not carry its identity; repair the marker before editing its shared folders".

When an included folder's link cannot be worked out, admins see "A shared-folder link between projects could not be resolved: <error>. The borrowed folder will not appear in the project that borrows it." with the repair "check the borrowing project's shared folder links"; it clears itself on the next success.

- Who: an admin, or a signed-in editor who has the project ticked.
- Ways in: from the including project's page, and from the Footage Sorter when it is on (see "The Footage Sorter includes a folder instead of copying a clip twice").

### Each included folder says whether it works, and why not

Each included folder is in one of four states, each with its reason in words:

- **ok.** When the lending project has been moved, it keeps working through the lender's new place and says "declared path is stale; the folder moved to Projects/<new>. Update the declaration when convenient."; what was entered is never rewritten on its own.
- **missing**: "folder not found on the server" or "folder could not be read on the server", still naming the lending project.
- **refused**, with one of: "empty path"; "absolute paths cannot be shared; declare a tree-relative Projects/ path"; "empty or dot path segment"; "segment ... starts with '.'"; "control character in path"; "segment ... contains ':' (declare a tree-relative path, not a drive path)"; "path segment over 255 bytes"; "only folders inside a project can be shared (the path must start with Projects/)"; "that is a whole project; tick both projects instead"; "cannot share a Proxy folder; share its parent instead"; "not inside a project"; "that folder is inside this project already"; "the lending project's marker is unreadable"; "contains a project (<folder>)"; "path escapes the Projects tree" (a shortcut that leads outside the tree).
- **lender inactive**: "the lending project is not active on the dashboard".

The lending project's page lists only working links, and only working links send anything to computers. One failed reading of the including project never takes an included folder away from anyone's computer: its links are kept until it can be read again. A file move inside an included folder is followed by the computers that include it, while the link is working or missing.

### A computer receives the folders its projects include

On a computer where the including project is ticked for full sync and the lending project is not, only the included folders come, at their true place inside the lending project, with everything a full tick brings (originals up, proxies and project files down). Each included folder gets its own full turn inside the including project's turn, a change in it moves the including project up the queue, and uploads go to the lending project's place on the server.

- Where the lending project is itself ticked for full sync on the computer, its own syncing covers the folder and nothing is fetched twice; the link still lets the app warn the editor before the lending project is removed.
- Where the lending project is ticked upload only, the included folder still comes down in full.
- Where two included folders overlap, the one first in the order wins. An upload-only including project includes nothing.
- If the lending project moves on the server, the included folder follows it on the editor's computer (never while the sync drive is missing).
- When nothing includes a folder any more it stops syncing and its files stay on disk. This never happens because a list came back empty or could not be read. If the editor then ticks the lending project, the folder becomes part of a normally synced project.
- Every stop covers included folders.
- An incomplete description from the server reads "<project> could not be set up on this computer: the server's description of it is incomplete. It keeps trying."

### The Footage Sorter includes a folder instead of copying a clip twice

When a clip on a card is already filed elsewhere (the same recording at the same size already sits in the studio's tree), and that copy's folder (or the folder above its Proxy folder) lies in one project while the card's planned destination lies in another, the person is offered **link folder** instead of copying. It adds that folder to the destination project's included folders, with the note "clip <name> already final here; folder linked instead of copied", who added it and when, so the footage syncs with that project without a second copy. Everything is worked out from the reviewed plan, never from what the browser sends. Already linked: nothing changes and the person is told so. Refusals: "unknown clip in this plan"; "this clip is not filed elsewhere on the destination"; "the existing copy is not inside another project"; the folder is the project's own top folder ("tick both projects instead"); the project's mark cannot be read ("fix it first") or has no identity ("refusing to edit it"); a plan that has changed since it was reviewed. The answer names the lending and including projects.

- Who: whoever may run the Footage Sorter.
- When the Footage Sorter is off: this is not offered, and folders are included from the project's page.

### The studio's shared libraries reach every computer without a tick

Two libraries come to every editor's computer whether or not anything is ticked, and never appear as projects: the LUT library ("Assets/Luts (LUT library)") and the Resolve gallery stills ("Assets/Stills (Resolve gallery)"), at those places in the computer's copy of the tree. No video ever travels in them. A library is never set up while the sync drive is missing, and while syncing is stopped a library waits and is taken up once the stop is lifted. If a library's place on the computer has moved, it is moved and pointed at again.

A library that fails is tried again after 1 minute, then less often, doubling up to every 30 minutes, and the editor is told in plain words what is wrong and what to do, whether or not any project is ticked, without project syncing being shown as broken. Each sentence stays until a later attempt succeeds:

- "<name> is not set up yet: CC Sync could not check it on this computer. It keeps trying."
- "<name> is not syncing yet: CC Sync could not confirm which files it must never carry. It keeps trying."
- "<name> is not syncing on this computer: its folder moved and it will not start at the new place on its own. Ask your admin to remove it from this computer so it is offered again."
- "<name> could not be set up on this computer[: <reason>]. It keeps trying."

- On its own: every computer the studio has accepted receives both libraries.
- See The server: installing it and keeping it running: Settings and secrets, "The kind of NAS, the project layout and the shared libraries", for the site's Shared libraries setting, whose default is these two.

### The app lists this computer's ticked projects and how each is doing

The app lists the projects ticked for this computer, each with its mode and its state, from one closed list of states, and never shows an empty plan as a warning (see The app on each editor's computer: Windows, dialogs and notifications, "The editor sees each ticked project with what it is doing and why").

- Who: the editor at the computer.

### The editor is told about waiting projects, broken included folders, renamed projects and files edited twice

The app's status shows, when they apply:

- "⚠ N projects are not syncing yet - waiting to be set up: <up to 3 names>, +M more".
- "⚠ <first problem> (and N other shared folders)".
- "⚠ A project was renamed on the server and this computer moved its folder to match: '<old>' is now '<new>'. Clips in Resolve may still point at the old path: Scan whole project in Settings relinks them", plus " (N more projects were renamed too)".
- "⚠ N files were edited on two computers at once, so both copies were kept (e.g. <name>). Nothing was lost: ask your admin which one to keep".

- When the help for the editing program is off: the renamed-project line ends after the new name.

### A blank or broken setting never widens what syncs

A blank, missing or empty value always narrows what is synced, moved or deleted, never widens it: where a value is missing, the action stops instead. A server destination that is empty, or not a full path, is refused when the computer is set up, and nothing uploads or downloads until a valid one is set. Every setting the product offers is honoured everywhere in the product; a setting it cannot honour makes it refuse to start, saying why.

#### Lessons

- Met: BRO-024, SYN-001, SYN-002, SYN-003, SYN-004, SYN-005, SYN-006, SYN-007, SYN-008, SYN-009, SYN-010, SYN-011, SYN-012, SYN-013, SYN-014, SYN-015, SYN-016, SYN-017.

## Uploads that cannot resume, shutdown and sleep

### An interrupted transfer carries on where it stopped

An upload cut off by quitting the app or by an update carries on where it left off (see "Quitting, signing out, updating or a stop ends transfers calmly"). A transfer cut off part-way in any other way, by a dropped or slow connection, sleep, a shutdown, signing out, the editor's pause or any stop, and a download cut off in any way, likewise carries on from where it stopped the next time it can, so a large camera original half-sent from the field over a poor connection is never sent again from the beginning. Leftover pieces of an unfinished transfer are never seen by anyone as files on the server or on a computer.


### Quitting, signing out, updating or a stop ends transfers calmly

Signing out, quitting the app, an update, a studio-wide stop or the editor's pause end every transfer in progress, including a large upload carrying on while another project has its turn. Quitting stops an upload at once, and it carries on where it left off the next time the app runs. An update first waits for the file in flight to finish, up to a limit the product states, then stops it the same way, and it carries on where it left off once the updated app runs. This is shown calmly, as stopped mid-transfer or stopped before it started, never as a failure. Once one of these begins nothing new starts, and no file is ever sent by two transfers at once: the one ended is finished with before anything takes its place.


### Shutting down while files are moving is warned against

While files are really moving, shutting the computer down is warned against. Work counts as really moving only while something moved in the last 3 minutes and there is somewhere to send it; a backlog that has not moved for 3 minutes counts as stalled, and after 8 hours of continuous work it stops counting until it settles. Paused or failed work never counts, and if it cannot be told, nothing counts.

The warning reads: "CC Sync is still syncing[ - <size> left[, about N min | about Nh Mm]]. Any file part-way across carries on where it stopped next time you switch on." (the time is shown only when it is a minute or more).

- Windows and macOS: on Windows, shutdown, restart and sign-out are held with Windows's own "this app is preventing you from shutting down" screen showing that sentence, and the person can still choose to shut down anyway. On macOS a logout cannot be held: the app closes cleanly; the first Quit of the app while files are moving is held once with a notification showing the sentence, and a second Quit within 2 minutes goes through. A real shutdown or logout counts as a deliberate exit, never a crash.
- On its own: anything going wrong with the check lets the shutdown or quit go ahead.
- Setting: Warn at shutdown while syncing. Does: holds shutdown with the warning while files are really moving. Default: on. Who: the editor in the app's settings for their own computer, or an admin for any computer from the dashboard. Applies to: a computer. Search words: shutdown, warning, still syncing, turn off.

### The computer is kept awake while files are moving

About every 30 seconds the product checks whether files are really moving (as above). While they are, the computer is kept from idle sleep on Windows and macOS (the screen may still turn off), and it is let go within about 30 seconds of the work finishing, stalling, or the app stopping. A stalled backlog never keeps it awake, and it is never held awake for more than 8 hours in a row. It cannot stop a deliberate sleep (the sleep command or closing a laptop lid). Nothing is held while syncing is paused or stopped, while the computer is not set up, or while the sync drive is out. Anything going wrong lets the computer sleep.

- Setting: Keep the computer awake while syncing. Does: holds off idle sleep while files are really moving. Default: on. Who: the editor in the app's settings for their own computer, or an admin for any computer from the dashboard. Applies to: a computer. Search words: sleep, awake, power, idle, laptop.

### A computer about to sleep says what is unfinished and catches up on waking

When the computer is about to sleep (a closed lid on battery, the sleep command) with transfers still owed, the editor is told what is unfinished. When the computer wakes, syncing starts again at once, without waiting for its next turn, and every transfer cut off by the sleep carries on.

### The editor can see whether it is safe to close the laptop

The app shows one line saying whether it is safe to close this computer: either that nothing is owed, or what is still to go up and which of the person's computers still owe uploads, by name. When it cannot be told, it says so rather than guessing.

- See Sync, part 2: What is owed.

#### Lessons

- Met: SRT-185, SYN-096, SYN-097, SYN-098, SYN-099.

## A plan belongs to a computer

### Each computer has its own sync plan

Each computer has its own plan: the projects ticked for it, in order, each with its mode. A tick names the person, the computer, the project, its place in that computer's order, who made it and when, when it last changed, and its mode. There are two modes: full (originals go up, proxies and everything else come down) and upload only (every file goes up and only the project's empty folders come down). Any other mode is refused with "unknown sync mode". One person may have several computers with different plans, and a computer keeps one identity, and so one plan, across renames of the computer and clashes of its name on the network.

A tick made for the person rather than one computer is a tick on each of their computers that is not wired. A person with no computer yet keeps it, and their first computer starts with it. Where a person's computers disagree about a project's mode, the project shows as mixed for the person.

- See Sync, part 2: Computers joining and changing, for renames and identity.

### The rules every tick and untick follow, wherever it is made

- Only the editor themself or an admin may change an editor's plan ("you can only change your own projects (admins excepted)" otherwise).
- A named computer must be one of that editor's ("<editor> has no computer named '<m>'"); with no computer named, the change is for the person: every computer they use that is not wired.
- A change can tick, untick, tick without touching an existing tick's mode, or set the mode (full or upload only), ticking if needed. A stale button never does the opposite of what it showed.
- Ticking a project the server does not have, or one that is archived, is refused: "unknown or inactive project '<name>'", with the project's name as people see it.
- A wired computer cannot be ticked: "<m> is wired to the server: it works directly off the NAS and syncs nothing, so projects cannot be ticked for it", and when every computer of the person is wired: "every computer on this account is wired to the server: they work directly off the NAS and sync nothing, so projects cannot be ticked for them". A tick for the person skips wired computers on its own, and a person whose every computer is wired gets nothing.
- Ticking a project for one computer adds it at the end of that computer's order and changes no other computer. Ticking one already ticked in the other mode switches the mode and keeps its place.
- Unticking for one computer removes the project from that computer only; the person's other computers keep syncing it. Unticking for the person removes it from every computer of theirs. An untick on a computer that never had the project changes nothing, and the person is told nothing changed rather than anything being widened.
- Every untick also drops that computer's picks of originals in that project; files already down stay.
- Every real change is recorded in the history with what was there before and after, takes effect at once, and every other view of the plan open on the page refreshes. The person is told whether anything changed.

- Who: the editor for their own computers, or an admin.
- See The dashboard: Ticking and unticking, for the controls.

### A plan can be copied from one computer to another of the same person

For any computer, another computer of the same person can be chosen to copy from. The target's ticks are replaced by the source's: the same projects, in the same order, in the same modes, recorded as made by the person copying. The person is first asked "Replace <target>'s <n> project(s) with <source>'s <m>?" followed by either "<target> stops syncing <k> of them: <names>..." or "Nothing is removed from <target>." Afterwards they are told how many projects the target now holds and which were added and removed, and the change takes effect within about a minute. The target's picks of originals in projects the source does not have are dropped; the source's picks are not copied.

Every project added or removed is recorded as its own tick or untick, marked as a copy from the source, so the computer's plan history shows it and each one can be undone (see The dashboard: Ticking and unticking, "Recent tick changes can be undone within an hour").

Refusals:

- an unknown source or target computer for that person;
- "source and target are the same computer";
- "this account is wired to the server: it works directly off the NAS and syncs nothing, so projects cannot be ticked for it";
- "'<machine>' is wired to the server: it works directly off the NAS and syncs nothing, so a plan cannot be copied onto it";
- "'<source>' is wired to the server: it works directly off the NAS and holds no plan, so there is nothing to copy from it";
- "<source> has no projects ticked. Copying it would leave <target> with nothing." (refused before anything is sent).

A failure reads "could not copy the plan: <reason>".

- Who: an admin, or the person for their own computers.

### Who may read a computer's plan

A person's plan can be read by that person signed in, by an admin, and by that person's own computers. The computers of a suspended, disabled or removed person are refused, but an admin can still read the plan, to see what resuming the person will restore. Anyone else is told to sign in. For one named computer the plan holds: every computer the person has; every remembered pairing of a Resolve project name with a project (who set it and when); and each ticked project in order, with its name, folder, position, whether it is active, its mode, the folders it includes from other projects, and, for a full tick of an active project, the originals picked for that computer. Asked for the person rather than one computer, the answer is everything ticked on any of their computers.

### A computer keeps its last plan when the dashboard cannot be reached

The app asks the dashboard for this computer's plan. Nothing is asked, and nothing syncs, until someone is signed in. After a sign-in the computer runs only the signed-in person's plan, asked for at once; a failed sign-in leaves the previous person signed in and their plan running. When the dashboard cannot be reached, the last plan received is used and the status line says so; a saved plan belonging to anyone other than the person signed in is never used. The app shows when it last received its plan and how long ago; when that is not known it says unknown, never "just now".

### A ticked project whose description is incomplete or unsafe is skipped

A ticked project is never synced, and no folder is ever made for it, by anything, when its path on the server is missing or blank, starts at a drive root, names a drive letter, contains an empty, "current folder" or "parent folder" part, or would otherwise reach outside the project tree; when it has no short name; when it is inactive; or when its mode is one this computer does not know. A missing mode means a full tick. Such a project is left alone consistently, never half-synced, and its name and the reason are shown in the app's list of projects.

### Admins are told when a tick has not taken effect

Admins see a serious problem, one per computer and project, when a computer's full tick is not matched by that computer actually receiving the project, and a warning, "a sharing change is held", when a tick or untick has been worked out but not put into effect. Wired computers and ticks for a person with no computer yet are left out; a tick on a computer whose identity is not known yet counts as unknown, not as a fault. Nothing is judged until the server knows what each computer is receiving. The fix offered: untick and tick again, and check the computer's row has its identity.

### Having nothing ticked is never a fault

A computer with nothing ticked is never an error, a warning, a blocked state or an alert on any screen. The admin can see, for information, which computers that report have nothing ticked.

#### Lessons

- Met: SYN-018, SYN-019, SYN-020, SYN-021, SYN-022.

## Wired or remote

### Each computer is wired or remote, set on that computer

A computer is either remote (it keeps its own copy of the projects ticked for it and syncs) or wired (it works straight off the server and syncs nothing). Any number of computers can be wired. The choice belongs to the computer: it is set on that computer, reported to the dashboard, and never decided by who signs in or whether they are an admin; signing in or out cannot change it. Where a computer has never said, it counts as remote. A person counts as wired only when every known computer of theirs is wired; a person with no computers is not. The product may switch a computer to wired on its own when it finds the computer's sync folder is the server's own share, and never switches one back to remote on its own.

The app's settings show "Computer name: <host name>" and "Current role: REMOTE EDITOR" or "Current role: WIRED TO THE SERVER", with two buttons, the current one marked "(current)":

- "REMOTE EDITOR", noted "syncs projects to this computer's own drive".
- "WIRED TO THE SERVER", noted "works directly off the server share, so nothing is synced to it".

A change takes effect the next time the app starts. Whether pop-ups about clips outside the tree are shown is a separate setting that this does not change.

- Who: the editor at that computer. Nobody can change it from the dashboard.
- On its own: a computer whose sync folder turns out to be the server's own share is switched to wired.
- By hand: the editor switches it back in the app's settings, with the confirmation below.
- Setting: Wired or remote. Does: decides whether this computer keeps its own copy and syncs, or works straight off the server and syncs nothing. Default: remote. Who: the editor on that computer. Applies to: a computer. Search words: wired, remote, role, NAS directly, syncs nothing.

### Switching a computer between remote and wired asks for confirmation

Switching to remote asks for the word REMOTE to be typed: "Switch this computer to REMOTE EDITOR? A REMOTE EDITOR computer syncs projects DOWN to its own drive. If this computer's synced folder is actually the live server share, switching will start moving files out of it the moment a download runs, because downloads make whatever this computer calls its own copy match the server. If you are not sure this computer has its own separate copy of the project tree, do not do this. Type "REMOTE" to confirm:". The confirm button reads "SWITCH TO REMOTE EDITOR". It asks even when the computer is already remote.

Switching to wired asks: "Set this computer to WIRED TO THE SERVER? A wired computer works straight off the server share, so CC Sync will sync NOTHING to it: no upload, no download. Your admin will not be able to tick projects for it either. If this laptop keeps its own copy of the projects, this is not the setting you want." with the button "WIRED TO THE SERVER".

Afterwards: "This computer is now set to <ROLE>. Takes effect the next time CC Sync starts: open Settings to restart now." or "Couldn't save that: see the log." Until the restart, a red line reads "The role above was changed and takes effect when CC Sync next starts."


### A wired computer syncs nothing and cannot be ticked

A wired computer downloads nothing, keeps no local copy of any project, never appears in any sync queue and puts no steady load on the NAS for syncing. It shows as healthy, still reports what its Resolve sees, and still warns about media used from outside the shared tree. Nothing of any project is ever sent to it.

It cannot be given a new tick: its box on the dashboard is locked, with the sentence given there (see The dashboard: Ticking and unticking, "A tick box always does what it showed"), and a person's own account page offers no project to add for it. Ticks left on a computer from before it became wired never raise an error, a notice or an alert; an admin can still see them and clear them.

- See The dashboard: Ticking and unticking.

### Setting up a computer starts with choosing remote or wired

The first step of setting up a computer says to pick how this computer reaches the footage, and that any number of computers can sit on the studio's network and work straight off the server. The two choices are "I'M A REMOTE EDITOR" and "I'M PHYSICALLY CONNECTED TO THE SERVER/NAS". The starting choice is what this computer was set to before, else remote editor; the role of the person's account never changes it.

- A remote editor's computer is set up to keep its own copy of the projects: on Windows the project drive letter is made fresh to point at that copy; on macOS Resolve's drive mapping is pointed at it.
- A wired computer gets only the app: its drive mappings on Windows, and the server shares mounted on a Mac, are left untouched. The folder chosen is both its copy of the tree and its drive. If the installer is incomplete it says "the app is not in this installer. Nothing has been changed on this computer. Get a complete package and run that instead." and offers to try again.

A wired computer's finish page is headed "DONE: CONNECTED TO THE NAS" and says the app is installed, signed in as the user, and starts automatically at sign-in; that nothing syncs on this computer because it works directly off the server; that the app (in the menu bar on a Mac) still watches the Resolve timeline for media outside the project tree; and that updates arrive as a one-click prompt. It then shows the dashboard address, the Resolve checklist, the support contact, where the log is, and the page's buttons.

- See The app on each editor's computer: Installing and setting up, for the rest of set-up.

#### Lessons

- Met: SYN-023, SYN-024, SYN-025, SYN-026, SYN-027.

## Upload only

### An upload-only tick sends every file up and brings down only the empty folders

For a project ticked upload only on a computer, every file in its folder goes up to the server, not just video. The only thing that comes down is the project's folder structure, empty: the editor sees the project's folders in their own copy of the tree, in the place their own originals go, so they can see where to put them. A folder made on the server later also arrives, empty. A file other than a camera original that is changed after it went up goes up again, replacing the server's copy, whose earlier version is kept on the NAS for a year; a camera original is never replaced. Nothing else comes down: no proxies, no project files, no originals (a pick of originals for it is refused), and it includes no folders of other projects. Left out of the upload: anything inside a Proxy folder, operating-system litter and hidden files, unfinished, temporary, lock and partial files, files half-way through a move, YouTube downloads still in progress and whatever a YouTube download leaves behind, the product's own recovery folder, and the hidden bookkeeping other sync tools keep in a folder.

Its status adds "Uploads only. Proxies do not come down for this project." while it is syncing or waiting, and it never reads as out of sync because no files came down. Whether a file belongs to an upload-only project is decided ignoring letter case, slash direction and the two ways Windows and macOS spell accented letters; when the product cannot tell, it uploads camera video only.

- Who: the editor for their own computers, or an admin.

#### Lessons

- Met: SYN-028.

## Deletions and removing a project

### A delete on an editor's computer never reaches the NAS or any other computer

Deleting any file or folder on an editor's computer never removes it from the NAS or from any other computer, with no step by the editor. Uploads never delete anything on the server. Nothing the product does on its own ever deletes footage on the NAS.

### Files deleted or replaced on the NAS are kept for a year

Within every project, a file deleted on the NAS, or replaced there by a newer version, is kept as an earlier version in the project's deleted-files folder on the NAS for up to one year, thinned out over time (more copies kept of recent versions than of old ones). Where a person goes looking for a lost file, the keep period is stated.

- Setting: Keep deleted and replaced files on the NAS. Does: how long earlier versions are kept on the NAS. Default: one year. Who: an admin. Applies to: the site. Search words: deleted files, earlier versions, recover, keep, NAS.

### A file removed or replaced on the server is moved aside on the editor's computer, never deleted

What comes down to an editor's computer follows the server: a file gone from the server goes from the computer too, and a changed one is replaced. Every file removed or replaced this way is moved, never deleted, into a hidden recovery folder at the top of the editor's synced tree, one dated batch per pass, keeping the project's path and the file's own path inside it, so it can be got back by hand.

- A file rewritten on the NAS (a proxy made again, a file replaced) is replaced on the computer, never removed, and never counts as a deletion.
- A file made on the editor's computer is never moved aside before it has reached the NAS.
- Files on the computer that the server does not have, in a folder that comes down, are moved aside rather than deleted, and the editor is told: "Some files in your project folder weren't on the server, so CC Sync moved them (never deleted) to:\n<folder>\nCopy anything you still need back out of there." (titled "files moved to the recovery folder"), with "OPEN THE RECOVERY FOLDER". The notice comes at most once every 30 minutes.
- A file the server moved into a project this computer does not sync stays in the recovery folder.
- Removals are recorded in the transfer history as removals, never as downloads.


### The recovery folder empties itself by age and size

A few times a day the oldest contents of the recovery folder are cleared, and every removal is recorded with its size and reason:

- batches older than 14 days;
- then, if what is left is over 50 GB, the oldest batches until it is under, never the newest batch;
- and when the sync drive is short of free space, the oldest batches until there is enough room again, never the newest (see "Downloads pause when the sync drive is nearly full, uploads never").

Earlier versions of a project file changed by syncing are kept in the same recovery folder, under the same rules. Nothing is cleared while downloads are halted by a safety stop, and no clearing ever removes a file the NAS does not hold.

- Setting: Keep removed files on editors' computers. Does: how many days the recovery folder keeps what was moved aside. Default: 14 days. Who: an admin. Applies to: the site. Search words: recovery folder, removed files, keep, days, trash.
- Setting: Recovery folder size. Does: the most the recovery folder keeps before the oldest batches go. Default: 50 GB. Who: the editor in the app's settings for their own computer, or an admin for any computer from the dashboard. Applies to: a computer. Search words: recovery folder, size, trash, space.

### The editor can open the recovery folder and see what it holds

The app shows where the recovery folder is, how many files and batches it holds, its total size, its oldest batch, and how long copies are kept, in the same words everywhere and with the site's actual keep period. From 1 GB up, its status says "Recoverable files in <path>: <size> (N files). Copies are removed automatically after D days, or sooner when the recovery folder passes <size> or the drive runs short of space" (the second size being the computer's recovery folder size). "Open the recovery folder" opens it; with no sync folder known: "CC Sync does not know where your sync folder is yet, so there is no recovery folder to open. Open Settings, THIS COMPUTER." The dashboard is told the folder's size (file count and bytes), where it is and how long files are kept there.

- Who: the editor at the computer.

### Admins are told when a computer holds over 200 GB of recovery copies

Admins see a warning when the recovery folder on one computer holds over 200 GB. The fix says the computer clears it by itself a few times a day unless downloads are halted by a safety stop, and points at resuming them.

### An editor removes a project from their computer in one action

The app's settings list each project ticked for this computer with "REMOVE '<project>' FROM THIS COMPUTER…" (" (upload only)" before "FROM" for an upload-only project). None are listed on a wired computer or when the plan is not known.

One action unticks the project on the dashboard, stops syncing it here, then deletes the local copy, stopping before any deletion if any step fails; the server's copy is never touched.

1. First: "Checking whether this project's files have reached the server…" (see "Removal is refused while anything here is missing from the server").
2. Ready: "Remove '<project>' from THIS computer? This unticks the project on the dashboard, stops syncing it here, and deletes the local copy to free disk space." then what was checked: for an upload-only project, "CC Sync has checked every file in this project's folder, apart from its Proxy folders (the server makes those again): each one is on the server at the same size and content, and none was left that CC Sync does not upload."; for a full tick, "CC Sync has checked this project's files: all of them have reached the server. Proxy folders are not counted, because the server makes those again." then "Tick the project again any time to sync it back." The button reads "REMOVE FROM THIS COMPUTER".
3. The check is made again at the moment of deletion.
4. The project is unticked for this computer (for every computer of the person when the dashboard does not know this computer, or when the tick is the person's own). Failures, each leaving everything in place: "sign in first"; "could not untick on the dashboard (<message>): nothing was deleted"; "the dashboard still lists it in this computer's sync plan after the untick. Untick it on the dashboard"; "There is no tick for <project> under this computer's name (<computer>), but it is still ticked for another of your computers. Nothing was removed. If this computer was renamed, wait until the dashboard shows the new name, or untick it on the dashboard."; "the dashboard has no tick for it under this computer's name (<computer>), and could not be asked whether another of your computers holds it. Try again in a minute".
5. Syncing stops here: "the project was unticked, but it could not be stopped syncing on this computer: nothing was deleted. Try again in a minute."
6. The folder is deleted. "'<project>' removed from this computer. The server copy is untouched." If the folder was already gone: "'<project>' is no longer synced here (its folder was already gone)". If some files could not be deleted: "'<project>' was unticked and stopped, but some files could not be deleted (<error>). Delete the folder by hand: it is safe now."

Other refusals: on a wired computer ("its folder IS the server's folder"); with the sync drive out ("<drive> is disconnected, so nothing was removed. Plug it back in and try again."); for an unsafe or out-of-place path ("nothing was deleted"). Anything else unexpected: "Remove failed. Copy the diagnostics for your admin from Settings, HELP."

- Who: the editor at the computer.

### Removal is refused while anything here is missing from the server

A project's local copy is deleted only when the product can show nothing would be lost. Any check that cannot be completed counts as "could not tell", and nothing is deleted. Proxy folders, the recovery folder, operating-system litter, unfinished files and empty files are not counted. It refuses while any of these hold, naming up to 20 files for each:

- part of the project is included in another project still ticked here: "part of this project ('<sub>') is shared into <other>, which is still selected here";
- files not yet on the server at the same size and content, of any age or date, files copied in moments ago included: "<N files> have not been uploaded yet (e.g. a, b, c)", or "CC Sync could not reach the server to check whether your footage has been uploaded";
- camera originals changed after they were uploaded: "<N files> changed after they were uploaded (e.g. ...). Rename them first, so they upload as new files", or that it could not check;
- files sharing a name with a different file on the server: "<N files> share a name with a different file already on the server, so they will never upload (e.g. ...). Rename them first", or that it could not check;
- files nothing carries up: "<N files> in this folder are not carried by any sync, so the server will never have them (e.g. ...)", or "CC Sync could not read this project's folder to check what is in it";
- files dated in the future (a camera clock set wrong) that have not reached the server yet: the editor is told how many, with examples, that such files upload like any other once they have stopped changing, and that their dates are wrong and are best reset to now by whoever looks after their computers;
- files coming down not all here yet (full tick): "<N files> have not arrived on this computer yet", or that it could not ask.

The editor sees "► project not ready to remove", "'<project>' is NOT ready to be removed." and each reason as a bullet, then "Deleting it now would destroy work that exists nowhere else. Leave CC Sync running until this finishes, then try again. If you have to free the space anyway (a dead server, a full disk), type the project's folder name exactly to confirm:" and the name, with a text box, CANCEL and "REMOVE ALL ELSE". A wrong entry shows "type exactly: <name>". Confirming removes everything that is safely on the server and keeps every file the server lacks, in place, listing them. The override (project, time, how much was owed, up to 4 reasons) is reported to the admin.

- Who: the editor at the computer.

### A computer holding footage the server lacks stays marked so

A computer stays marked as holding footage the server does not have until each of those files is confirmed on the server, however long that takes. When an editor removes a project's copy, or part of it, while uploads were still owed, the admin is told: which computer, which project, how many uploads were owed and why.

- See Sync, part 2: What is owed.

### A project whose folder disappears from the NAS is never deleted

A project whose folder has vanished from the NAS is left set up as it was; nothing is deleted. It is marked no longer active on the dashboard. When more than a quarter of the active projects (and never fewer than two) would go inactive in one check, none of them is marked and admins see a serious problem, "a mass project deactivation was refused", saying N projects looked deleted in one check, over the limit, so none were marked gone. A project seen within the last 15 minutes is never counted as gone.


#### Lessons

- Met: SYN-030, SYN-031, SYN-032, SYN-033, SYN-034, SYN-035, SYN-036, SYN-037, SYN-038, SYN-039.

## Safety stops

### Downloads stop themselves when the server suddenly looks wrong

Before and during every download the product checks that the server still looks like the studio's project tree and answers, and counts what the download is about to move aside on this computer. Downloads stop by themselves, and stay stopped across restarts, when:

- the server does not look like the project tree at all (its projects folder is not there);
- the server lists nothing where there were files last time, while this computer holds files;
- the server lists fewer than half the entries it did last time, where there were at least four;
- one pass would move aside more than 50 files from this computer, or more than a quarter of them where there were at least 20;
- removals add up to more than 200 since the stop was last cleared (a slow leak).

Every removal counts toward these limits as it happens, once only, through crashes, power cuts and passes that end early. A file gone from one path but present elsewhere with the same name and size, a file still on the server at the same path (a proxy made again), or a file the product knows was moved, is a move and never counts; if that cannot be checked, the files count as removed. A failed listing of the server is not a reason to stop: that pass simply fails and is tried again, and one failed reading of a project never takes its files from anyone's view.

While stopped, nothing is downloaded or moved aside. Uploads keep running. The app shows it as paused, not failed. The editor is told once per stop, in a notification and on the status line, with one of these sentences, each followed by "Nothing was deleted and your uploads are still running. Ask your admin to check the server.":

- "The server does not look like your project tree right now, so CC Sync stopped downloading before anything could be removed."
- "The server suddenly listed nothing where your files were last time, so CC Sync stopped downloading before anything could be removed."
- "Far fewer files are on the server than there were last time, so CC Sync stopped downloading before anything could be removed."
- "One download pass would have cleared out far more files than normal, so CC Sync stopped it."
- "Downloading has been clearing out files steadily for a while, so CC Sync stopped it."
- otherwise "Downloading stopped itself as a safety measure."

The dashboard sees that it stopped, why, when, and how many files and bytes were moved aside. Technical detail goes to the admin and the log, never to the editor.

- Setting: Download safety limits. Does: how many files one pass may move aside (50, or a quarter of the computer's files), how many in all before a stop (200), and how far the server's list may shrink (by half). Default: 50, a quarter, 200, half. Who: an admin, for any computer. Applies to: a computer. Search words: safety, limit, removals, download stop.

### Old files are cleared out a slice at a time

In one pass of a project at most 100 files and 20 GB are moved aside on an editor's computer. When that is reached the rest waits for the next pass, and the editor is told, as a calm state and not an error, how many files were transferred and that old files are being tidied in slices as a safety limit and it continues next time.

### Only a person restarts downloads after a safety stop

A safety stop never clears itself. The editor restarts downloads from the app ("Resume downloads…"), or an admin does so from the dashboard for that computer. Restarting clears every count and takes what the server shows next as the new normal, so the same listing never trips it again; downloading starts at once.

- From the app: "CC Sync stopped downloading because: <reason>. Only resume once your admin has confirmed the server is healthy. If it is not, resuming will move more of your local files into the recovery folder (they stay recoverable, but you will not see them in Resolve)." with "RESUME DOWNLOADS". Answers: "Downloads resumed."; "downloads are not stopped"; "could not resume downloads: see the log".
- From the dashboard: an admin presses Resume on the computer's row. Refused for an unknown computer, and when the computer's last report does not show downloads stopped: "that computer's last report does not show downloads stopped, so there is nothing to resume. Wait for its next report and try again." The request records who and when and is recorded in the history. It is delivered at the computer's next report, dropped if that report shows downloads already running again, and releases exactly the one current stop: a later stop waits for a person again. The admin may withdraw a waiting request, which always succeeds. The editor is told "<admin> checked the server and started downloads again."

- Who: the editor at the computer, or an admin.
- Ways in: from the app on the editor's computer, and from the computer's row on the dashboard.

### Safety stops survive restarts, and one that cannot be saved still holds

Every safety stop, the free-space pause, the editor's pause and every stop survive restarts of the app and the computer, updates, power loss and support clean-ups. A stop record that cannot be read counts as still stopped.

If a stop cannot be saved on the computer, it still holds while the app runs, saving is tried again about once a minute, and the dashboard is told the stop is not saved, why, and since when. The editor is told: "⚠ CC Sync cannot save its safety state on this computer (<errors>), so restarting CC Sync would lose what it stopped. Copy the diagnostics for your admin from Settings and send them before you restart." When it is saved again, the warning goes.

### The editor's status says plainly what is stopped and by whom

The app's settings window shows, when they apply:

- "⛔ Your administrator stopped syncing for everyone: <reason>";
- "⛔ DOWNLOADS STOPPED (safety): <reason>";
- "⚠ Not downloading: <reason>. Uploads are still running; free up space and it starts again on its own" (the drive nearly full);
- "⚠ <the reason syncing is held>", left out when that reason already has its own line.

### An admin sees each computer's stops and pauses

For each computer the dashboard shows whether downloads have stopped themselves, why and when; whether the studio-wide stop has reached it, with the reason; whether the editor has paused it; how many files the recovery folder holds and their size; how many uploads are held because the server already has a file of that name at a different size, and in which project; and the free space at which downloads pause. When a computer stops reporting one of these, it disappears from the dashboard at once.

- See The dashboard: Each computer's state.

### Admins are told when downloads have stopped themselves on a computer

Admins see a serious problem, "downloads stopped themselves", when a computer's safety stop has tripped: "Downloads have stopped themselves on <who>, <age>. Until somebody clears it, that computer gets no new proxies, so the editor cannot see anyone else's footage. Uploads from it are still running and nothing has been deleted." The fix: press Resume on that computer's row, after checking the server looks right.

### The product asks an admin before taking many projects off computers at once

Each project taken away from one computer counts as one removal. Removals a person clearly caused never count: those of an archived project, those of a suspended editor's computers, those backed by an untick or a switch to upload only made in the last 24 hours and still in force, and those an admin approved. When the rest of one round's removals exceed the limit, none of them is applied, while additions and the removals that do not count go ahead. The limit is 3, or, if larger, the site's allowance of removals per computer times the number of editors' computers.

A computer whose owner is not known is never taken off anything, and a computer that appeared after the round was worked out keeps what it has until the next round sees it.

Admins see a serious problem, "a sharing change was refused", and, on the list of computers, "refused": "N removal(s) refused: shares are frozen. No untick is being applied on N folder(s), N computer(s).", with when, how many, the limit, and up to 200 project and computer pairs (marked when there are more), and what the last round was about to add and remove per project (up to 100 projects, with totals). The advice: check no computer was renamed or removed, approve any computers waiting to join (the hold then clears itself on the next round), or, if these removals are meant, apply them or raise the allowance. While the hold lasts, each computer still being sent a project nobody has ticked for it is listed as its own warning (up to 20): "This computer is still being sent a project that nobody has ticked for it...". All of these clear when a round has nothing refused.

### An admin approves exactly the removals the product held back

An admin can press "Apply these N removals". The approval names the exact project and computer pairs shown, lasts one hour, is used whole by the next round, and is recorded in the history with up to 50 of the pairs; it takes effect at once. Refusals: "no removals are waiting for approval"; "the list changed: N removal(s) are waiting now, not M. Reload and check them again."; when the list was too long to show whole, "too many removals to approve one by one: raise the allowance of removals per computer instead", and the button is not offered.

- Who: an admin.

### An admin sets how many removals per computer are allowed before the product asks

"The server stops and asks when one round would take more projects away from computers than this limit, because that is what a broken list looks like. Removals a person caused on purpose (an archived project, a suspended person, an unticked project) never count. The limit is at least 3; set a number here to let it grow with the studio: this many removals for every computer. 0 keeps the limit at 3." A whole number from 0 to 100, refused otherwise with "Enter a whole number from 0 to 100." Saving answers "Saved. The limit of 3 applies." or "Saved. Up to N removal(s) per computer in one round before the product asks." It records who set it, goes into the history with the old and new value, and takes effect at once.

- Setting: Removals allowed per computer. Does: lets the number of projects taken off computers in one round grow with the number of computers before an admin is asked. Default: 0 (the limit is 3). Who: an admin. Applies to: the site. Search words: removals, unshare, safety, limit, approve.

### A count of a project that suddenly finds almost nothing is not believed

When the server counts a project's files on the NAS and the previous count had files, and either it had originals and the new one has none, or the new one found fewer than a tenth of the previous files, the last good count is kept. The project shows "The server found N of M files in this project and kept the last good count: the project's folder looks disconnected or was renamed on the NAS." It is counted again next time, and admins see a problem, "the file count collapsed, so the last good one is kept".

### A project keeps its identity when its mark is lost

When a project's folder loses its project mark, the product puts it back on its own, with the identity it knows, within about five minutes, keeping everything else the mark held (such as its included folders) and recording who wrote it and when. A mark is always written whole, so no computer ever sees a half-written one. When the product cannot be certain the folder is that project, or another folder already claims the identity, it leaves the folder alone and admins are told which folder, and why.

- On its own: a lost mark is put back where the product is certain which project the folder is.
- By hand: an admin is shown each mark the product would not put back, and can mark the folder from the project's page.

#### Lessons

- Met: SYN-040, SYN-041, SYN-042, SYN-043, SYN-044, SYN-045, SYN-046, SYN-047, SYN-048, SYN-049, SYN-050, SYN-051, SYN-052.

## Studio-wide stops and the editor's pause

### Syncing waits for a short list of reasons, each in its own words

When syncing does not start, the status says why. The reasons, their order and their words are one list, given the same everywhere: in the app, on the dashboard and in alerts (see Sync, part 2: Saying truthfully what the sync is doing, "Each computer says in one sentence why it is not syncing, and since when"). Sync never starts with nobody signed in.


### The editor pauses and resumes syncing

"⏸ Pause syncing" and "▶ Resume syncing (paused by you)" (ticked while paused) toggle the pause. Pausing stops every transfer in both directions after the current step, new footage included, and holds until the editor resumes: through sign-in, restarts, updates, a returning drive and the release of any other stop. Pausing is never reported as a fault. Resuming starts again at once, checks every project against the server, and fetches any originals asked for meanwhile. Unplugging the drive or a stop does not change the pause, and none of them undoes it. On a wired computer the pause changes nothing else.

- Who: the editor at the computer.

### Sync now runs every transfer this computer has switched on at once

"Sync now" cuts the wait short and checks every project at once, running only the transfers this computer has switched on, the same set its automatic start uses. The notice afterwards is "Sync requested: <what will sync>" or "Sync requested. Checking the server for changes now." when accepted, and "Not now: <reason>" or "Not now: nothing on this computer needs syncing." when refused. If the app gives no answer, nothing is shown. When the round trip it started ends, the editor is told what it did: how many files were sent up and how many brought down.

- Who: the editor at the computer.

### While any stop is in force nothing moves

A studio-wide stop, like the editor's pause, halts every transfer on every folder of the computer: uploads, downloads, project files, the shared libraries, included folders, and the first set-up of any new folder. While stopped, nothing that would start syncing is allowed, and if it cannot be told whether syncing is stopped, it is treated as stopped. A stop touches only what this product syncs, never other programs on the same computer, and the product does not try to bring its syncing back up while stopped, paused or wired. Releasing a stop returns each folder only to the state it would otherwise be in, so a project still waiting to be set up stays waiting, and a folder whose never-travel rules are not yet confirmed stays held (see "A project never syncs until these rules are in place for it"). The dashboard is told whether a computer is stopped or paused, and why.

### An admin stops syncing on every computer with a reason

An admin can stop all syncing on every computer at once. A reason is required, at least 3 characters after trimming and up to 500; a shorter one is refused with "say why: the reason is shown in every editor's app (at least 3 characters)" and nothing stops. The stop records the reason, who set it and when, and ends by itself after a chosen number of hours: 24 by default, more than 0 and at most 720 (30 days). Every computer learns of the stop, and of its release, the next time it checks in, normally within about 30 seconds. With no reason given the editors see "your administrator stopped syncing across the studio".

Each editor sees "STOPPED: your administrator stopped syncing for the whole studio[: <reason>]", and cannot release it from their computer: "your admin stopped syncing for the whole studio: <reason>. Only they can start it again." A computer that has not heard from the dashboard keeps whatever stop it has. A studio-wide release lifts only the studio-wide stop; an editor's own pause stays. When it is released, syncing starts again (subject to everything else) and the editor is told "Your administrator started syncing again."

A stop whose end time has passed reads as over and marked as having ended by itself, and the next check-in releases every computer. An end time that cannot be read is not treated as passed, and a stop that cannot be read at all counts as stopped.

- Who: an admin. A stop is for the whole studio; one computer is paused at that computer.

### An admin keeps a studio-wide stop going or starts syncing again

While a stop is in force, "Keep it stopped" moves its end to the chosen number of hours from now (24 by default, at most 720) and keeps the original reason, the person who set it and the start time; each extension is counted and shown. Pressed when nothing is stopped and with no reason of at least 3 characters, it is refused with "Syncing already started again at <date and time in the studio's time zone>. To stop it again, give a reason." or, if nothing was ever stopped, "Nothing is stopped, so there is nothing to keep stopped. Stop syncing with a reason." With a real reason after the stop ended it starts a fresh stop.

"Start syncing again" needs no reason (one may be given and is recorded). Every computer resumes at its next check-in, normally within about 30 seconds.

- Who: an admin.

### Everyone can see whether syncing is stopped studio-wide

While a studio-wide stop is in force, every page of the dashboard shows a banner saying so, with the reason. Anyone signed in, and every editor's computer, can see whether syncing is stopped, whether a stop ended by itself, the reason, who set it, when, when it ends and how many times it was extended; anyone not signed in is refused with "log in first". Admins see a warning, "syncing is stopped for the whole studio", while the stop is in force, with "Start syncing again" and "Keep it stopped"; and a warning, "a studio-wide stop ended by itself", for 24 hours after a stop ends on its own, so its ending is announced. The last 20 stops, extensions and releases are listed newest first (time, what, who, reason, end), and each is in the studio's record of admin actions.

- Who: anyone signed in.

#### Lessons

- Met: SYN-053, SYN-054, SYN-055, SYN-056, SYN-057, SYN-058, SYN-059.

## Files that must never sync

### Each kind of file travels only in its own direction

Within a ticked project, camera originals only go up (and come down only when picked), proxies come down (only a proxy made on this computer goes up, never replacing one on the server), and every other file is kept in step both ways. A video original is never carried as an ordinary project file, and neither is anything in a Proxy folder. The video kinds, matched in any letter case, are BRAW, MOV, MP4, MXF, AVI, MTS, M2TS, MKV, R3D, CRM, MPG, MPEG, WMV, WEBM, INSV and 360; these same kinds are what the product counts as video originals everywhere on an editor's computer. In the shared libraries no video travels at all.

### Some files never travel at all

These never travel in either direction, by any upload or download, and are never counted as owed or missing:

- unfinished, temporary, lock and partial files of every tool, files still being uploaded or downloaded, the product's own half-copied files, YouTube downloads still in progress or left by one that failed, and whatever a YouTube download leaves behind: the download kept aside under an "original" name while its name was held, and every half-made file of a conversion;
- files half-way through a move the product is making;
- empty (zero-byte) camera files;
- the hidden companion files macOS writes beside each file on drives it did not format ("._" files), and the folder settings files of macOS and Windows (Finder's and Explorer's hidden folder files, thumbnail files), and other operating-system clutter;
- the product's own recovery folder;
- the hidden bookkeeping other sync tools keep in a folder.

The same set is left out everywhere. Any macOS companion files already on the NAS are found and cleared, and the leftovers of an interrupted transfer are cleaned up; neither is ever footage.

A file whose size or time is still changing does not travel yet, whatever its kind: it travels once it has been still for a set time (see Sync, part 2: Clocks and file age, "A file is sent only once it has stopped changing").

### A project never syncs until these rules are in place for it

A project, a shared library or an included folder whose never-travel rules cannot be confirmed on a computer (they could not be read or written) is held offline there rather than synced without them, shows as blocked, and starts by itself once the rules are confirmed, across retries, restarts and the release of any stop. A newly ticked project therefore never carries a camera original the wrong way, even for a moment. If the rules are found changed, the correct ones are put back on their own within a few minutes.

### Files edited on two computers at once are both kept

When the same project file is changed on two computers before either change has travelled, both copies are kept, of any kind of file. Nothing is merged or deleted on its own. The editor is told (see "The editor is told about waiting projects, broken included folders, renamed projects and files edited twice") and the admin sees on the computer's row how many the computer holds and up to 20 of the files with their paths, marked as cut, with how many more, when there are more.

- See Sync, part 2: Saying truthfully what the sync is doing, "A file changed in two places at once keeps both versions".

### The editor is shown files that will never upload and included folders that do not work

The app shows: files dated in the future (a camera clock set wrong), which upload like any other file and are listed until their dates are put right; up to 5 files whose name already exists on the server at a different size, so this computer's version will never upload, with both sizes; up to 10 sentences about shared libraries or included folders that are not working on this computer; and up to 10 projects renamed on the server whose folder this computer moved to match (old name, new, when, and whether Resolve was relinked). Only projects ticked here count, and warnings about projects no longer ticked are dropped; when the app cannot tell what is ticked, it drops nothing. When the sync drive stops answering and the app can no longer notice new files at once, or when it can again, the editor is told.

- When the help for the editing program is off: renamed projects say nothing about relinking.

#### Lessons

- Met: SYN-060, SYN-062, SYN-063.

## Names

### Names cross exactly as written

File and folder names cross in both directions, on every path including recovery, byte for byte as written: full-width punctuation (such as a full-width question mark), brackets, braces and other pattern characters, spaces, and names in any script, Chinese included. A name holding a character Windows forbids fails visibly for that one file instead of being renamed. A name that cannot be read affects that one file only and never holds up syncing.

Names are compared ignoring letter case, and a Mac's names (in the decomposed Unicode spelling) match the server's and Windows's; but a file or folder is always opened, renamed or deleted by its exact spelling on disk. Every file-type and folder-name rule in syncing matches regardless of letter case.

- Windows and macOS: brackets, braces, spaces and both Unicode spellings are proven on both.

### An update never makes a computer download again what it holds

Updating the app never makes a computer bring down again files it already holds intact. If names must change, the copies on the computer are renamed in place.

### The editor is told about files that will never upload because of a name clash or a wrong clock

- "⚠ N files on the server have the same name but a different size, so your newer version will NOT upload (e.g. <name>: yours <size>, the server's <size>). Rename yours, or ask your admin to remove the server's copy". Each such file is listed with both sizes, up to 20, and the folder holding one can be opened.
- Files dated in the future: the editor is told how many there are, the first one's name and date, that a camera clock is set wrong, that the files upload like any other and only their dates are wrong, that a date further ahead is best reset to now by whoever looks after their computers (a copy or re-import keeps the date), and that fixing the camera clock only helps future recordings.

The first version of a camera original's name to reach the server is the only one that ever will; a newer local version with the same name stays behind and is reported like this, never sent.

- See Sync, part 2: What is owed, and Clocks and file age.

### The editor can open the folder of a file that will not upload

"Open the folder of a skipped file" opens the folder of the newest file that will not upload. With none: "Nothing is being skipped on this computer right now."; with no sync folder known: "CC Sync does not know where your sync folder is, so it cannot open the folder holding <name>."

- Who: the editor at the computer.

#### Lessons

- Met: SYN-064, SYN-065, SYN-066, SYN-067, SYN-068, SYN-069, SYN-070, SYN-071.

## The sync drive

### The product watches whether the sync drive is really there

Every 5 seconds the product checks the drive holding the editor's copy of the tree and acts only when the answer changes (at once after starting, so an app started with the drive out knows straight away). Every check is time-limited: a drive that does not answer within 5 seconds is reported as not answering and can never freeze the app. The drive is one of:

- there;
- disconnected: "the sync drive is disconnected";
- at a place the product cannot confirm (macOS only: something sits where the drive should be, or a drive appears under another name, and the product cannot tell whether it is the sync drive): "the sync drive is mounted at the wrong place: eject it, delete the leftover empty folder, then plug it back in";
- not answering (plugged in, but its files have stopped answering): "the sync drive is not answering: reconnect it or restart the computer".

These sentences are the same on the status line, in a notification, in the sync detail and on the dashboard. On the first change of an outage the editor gets one notification: "Sync paused: <Drive> is disconnected.", "Sync paused: <Drive> is mounted at the wrong place. See the CC Sync window for what to do." or "Sync paused: <Drive> is not answering: reconnect it or restart this computer." A change of kind within the same outage is announced in its own words. A check that itself fails changes nothing. While the app is quitting a change is not acted on.

A sync drive that comes back under another name (on a Mac, for example "SSD 1" instead of "SSD") counts as there and syncing carries on, at its new name, whenever it is provably the same drive, whatever it is called; nothing is ever written into a leftover folder at the old name. It pauses only when the product cannot tell.

The product never relies on being told of changes on the drive: it notices when such news stops (and tells the editor, "The sync drive isn't responding, so CC Sync can't notice new files on it at once. Disconnect and reconnect the drive, or restart the computer. Everything else is still running." and later "The sync drive is responding again. CC Sync notices new files on it at once again."), and it still finds every change by looking.

- Windows and macOS: on Windows only "there" and "disconnected" are told apart. On macOS an external drive's empty leftover folder on the startup disk counts as disconnected, and the product knows which volume is the sync drive (recorded when the computer was set up), so it follows that volume when it is mounted under a different name, such as "SSD 1"; when it cannot tell, the drive counts as absent.

### With the sync drive out nothing is written anywhere else

While the sync drive is disconnected, at a place the product cannot confirm, or not answering, nothing touches it and every kind of syncing waits: no upload, no download, no copying into the tree, no new footage noticed. Nothing is ever written to the computer's internal disk instead, nothing is created where the drive should be, and free space is never measured on another disk. The editor's own pause is not touched. A check of what the computer holds that overlaps the drive going away is thrown away, never reported as the computer holding nothing.

### A drive the product cannot confirm on macOS is explained in three steps

Only when the product cannot tell that what it finds is the sync drive, once per outage the editor is told "<Drive> is mounted at the wrong path. Sync is paused until it is fixed. See the CC Sync window." and a dialog titled "drive mounted at the wrong path", with OK, explains that an empty leftover folder sits where the drive should be, and gives three steps: eject the drive; delete the leftover empty folder; plug it back in and check it appears at the right place. If another window of the app is open, only the notification is shown.

- Windows and macOS: macOS only.

### A returning drive resumes syncing only if nothing else holds it

A drive coming back is not consent to sync. When it returns, nothing resumes if the editor paused, if a stop is in force, if the computer is not set up, or if nobody is signed in. Otherwise syncing resumes within about a minute, new footage is noticed again, and everything that piled up is checked at once rather than at the next turn; every folder on the drive, shared libraries and included folders too, comes back by itself within minutes, including when the app starts with the drive already there. The editor is told "Drive reconnected, sync resumed."; a drive present at start says nothing.

### A sync drive missing at start is waited for

When the only problem at start is that the sync folder is not there and it lives on a removable drive, the app waits and starts syncing by itself when the drive appears; it is never treated as a broken set-up. A sync folder that was never chosen is still a set-up problem.

### A drive pulled out with work owed is named and reminded about

When the sync drive goes away with uploads owed, or when what is owed cannot be told, the warning names what is owed instead of a calm note (what counts as owed, and how it is summed up in <owed>, see Sync, part 2: What is owed, "When the sync drive is pulled with work owed, the editor is told what is owed and reminded until it is back"):

- "<Drive> was disconnected with <owed> still to go: plug it back in to finish syncing"
- "<Drive> is mounted at the wrong place with <owed> still to go: eject it, delete the leftover empty folder, then plug it back in"
- "<Drive> is not answering with <owed> still to go: reconnect it or restart this computer to finish syncing"

It is repeated every 30 minutes until the drive is back, across restarts: what is owed is remembered, and a restart with the drive still out reminds again. A drive that stays not answering gets its own repeating reminder, which ends by itself when the drive answers or is removed. A drive pulled out with nothing owed gets the one calm "Sync paused" notification.

While reminders run, the editor has "REMIND ME LATER" (silences them for 2 hours: "CC Sync will remind you about this drive again in 120 minutes.") and "STOP REMINDING ME ABOUT THIS DRIVE" (silences them until the drive is back: "CC Sync will stop reminding you about this drive. Your unfinished syncing is still waiting for it, and Settings still says so."). Once silenced, "Reminders about this drive are off until it is plugged back in." replaces the buttons; "There is nothing to remind you about now." when there is nothing to silence; on failure "CC Sync could not do that." with the way to send diagnostics. Silencing never removes the warning line or forgets what is owed, and covers only this outage.

- Who: the editor at the computer.

### Choosing the sync folder on macOS checks the drive is really mounted

As the editor types the folder on a Mac it is checked, and refused in red with set-up held back when: it is empty; it starts or ends with a space; it starts with ~ (write the full path instead); it does not start with /; it is / or /Volumes on its own; for a remote editor, it is a whole external drive on its own (pick a folder on it); or it names an external drive that is not mounted now (remote: plug the drive in and unlock it if it is encrypted, and a leftover folder from an unclean eject may be in the way; wired: connect the server share first from the Finder). A check that itself fails never blocks.

When the folder is on an external drive, set-up stops and says to plug it in (and unlock it if encrypted) and run again if the drive is not there. If the Mac mounted the drive under a numbered second name (for example "SSD 1"), set-up records the drive by what it is rather than by its name, and says the app will follow it whatever it is called. If the drive's usual name is only a plain leftover folder and the drive itself cannot be found, set-up stops with a boxed warning that the path IS NOT A MOUNTED VOLUME, explaining that syncing into the leftover folder would fill the Mac's internal disk instead of the drive, then the fix: eject, remove the leftover folder, unplug and plug in again, run again. If the Mac cannot identify the volume, set-up refuses to guess. Two drives of the same name both mounted get a warning to rename one. A drive not formatted in the Mac's own format gets a warning that other formats lose macOS file details and some cannot keep names differing only in letter case. Set-up records which drive it is, so the app can later tell "drive unplugged" from "drive plugged in but empty".

- Windows and macOS: these checks are made on a Mac. See Sync, part 2: Project folders on an editor's computer, "The editor picks the folder for the project tree when setting up", for Windows.

#### Lessons

- Met: SYN-072, SYN-073, SYN-074, SYN-075, SYN-076, SYN-077, SYN-078, SYN-079, SYN-080, SYN-081, SYN-082, SYN-083.

## Disk space

### Downloads pause when the sync drive is nearly full, uploads never

Before each download the free space on the sync drive is measured. Below 20 GB free, downloads pause (shown as paused, never as an error) and the recovery folder is emptied oldest first, never its newest batch; uploads keep running and are never paused for disk space. Downloads start again on their own once 40 GB is free; between the two they stay paused. The sentence shown is "this drive has N GB free, and downloading needs F GB" below the floor, and "this drive has N GB free, and downloading starts again on its own at C GB" in between, updated as space changes. The editor is told once: "CC Sync is not downloading:\n<reason>\nYour uploads are still running. Free up some space and it starts again on its own." (titled "downloads paused"). The pause is remembered across restarts. "Sync now" tries again at once and pauses again if there is still not enough room. A free-space reading that failed changes nothing, and when free space cannot be measured nothing is paused. The dashboard sees whether downloads are paused, why, the free space and the floor.

While downloads are paused for space the app also offers "Resume downloads…", saying "CC Sync stopped downloading because: <reason, by default 'this drive is nearly full'>. Your uploads never stopped. Downloading starts again on its own as soon as there is enough room, so you only need this if you have just made space and do not want to wait." with "RESUME DOWNLOADS"; with nothing paused it answers "Nothing to resume".

- Setting: Keep this much free on the sync drive. Does: below this, downloads pause, and they start again at twice it. Off turns this off. Default: 20 GB. Who: the editor in the app's settings for their own computer, or an admin for any computer from the dashboard. Applies to: a computer. Search words: free space, disk full, floor, drive, pause downloads.

### Originals to come down must fit

Originals picked for a computer come down only while the whole batch would fit and still leave the floor free. Otherwise they pause with "NOT DOWNLOADING ORIGINALS (disk):", how much the originals need, how much the drive has to give, and how much it keeps free.

### Ticking warns when the proxies may not fit

Wherever a tick is made, ticking a project whose proxies may not fit on the computer warns, naming both figures, and asks before saving; it never refuses (see The dashboard: Ticking and unticking, "Ticking warns when the proxies may not fit but never refuses").

- Who: the editor for their own computers, or an admin.

### The dashboard shows each computer's free space and colours it

For each computer the dashboard shows the free and total space where it syncs, the free space on its system disk, and when they were measured; a check-in without a measurement leaves the last one shown. The whole studio's free and total space can be seen beside the ticks. The drive is red under 5 percent free or under the computer's own floor (20 GB, or the figure the computer reports); amber under 10 percent or under 50 GB; otherwise green. A computer that reports nothing about its drive gets no colour, never a reassuring green. Why a computer stopped downloading is told only from the reason the computer itself reported; a low-space colour is a warning, never a stop, and a computer with no figure never counts as stopped.
The computer's row shows "disk N%" when the drive is not healthy, with the sync drive's free and total space, the system drive's free space and when they were measured, and explains: downloads fill a drive file by file; below its floor downloads stop and the recovery folder is emptied oldest first until the drive has twice the floor free, which starts downloads again; downloads halted by a safety stop wait for a person to resume them, from that computer or by an admin on its row.

- See The dashboard: Each computer's state.

### Admins are told when a computer is short of space

- Serious, "a computer stopped its own downloads for space", when the computer reports its downloads paused for space: "<who> has stopped its own downloads because the drive is nearly full (X free)." Fix: clear space, or untick a project.
- Serious, "a computer is running out of space", when the computer's drive is red by the rule above, it is not wired, and (when known) it holds a full tick: "<who> has X free on its sync drive (P percent). Downloads fill a drive file by file, so this ends with that editor unable to work."
- Warning, when an editor's computer has under 50 GB free, from a reading no older than 48 hours (an older or undated reading clears it): for computers that take proxies, "Proxy downloads for one project are typically 50 to 300 GB..." with the fix to untick a project or clear space; for wired computers or ones with nothing ticked, "No project footage comes down to this computer... anything else it syncs, such as the shared LUT library, stops when it runs out", with the fix to clear space.


### Setting up warns when the chosen drive has under 200 GB free

When the chosen folder is otherwise fine and its drive has under 200 GB free, set-up shows an amber line with how many GB are free and that synced proxies for one project are typically 50 to 300 GB, adding that sync will still be set up there and to keep an eye on the drive or choose a bigger one. Nothing is said when free space cannot be measured, and it never blocks set-up.

#### Lessons

- Met: SYN-084, SYN-085.

## Stuck, slow and fair transfers

### Each project gets a turn, and a large upload carries on while the next project goes

Projects are synced one after another, each for up to about 10 minutes at a time. When a project's time is up, files in flight finish, nothing new starts for it, and the editor is told how many files were transferred and that it paused at the project's time limit; the rest goes on its next turn. A project with nothing moving gives up its turn within about a minute, so a slow or stuck project never holds up the others' downloads beyond that.

A large upload still running when its project's time is up is never stopped: it carries on while other projects take their turns, and other projects' transfers are never held behind it. The editor then sees "uploading <name> (<percent>%)" for one file or "uploading <N> file(s)" for several, and it still counts in the speed, the time left and in keeping the computer awake. While more than one file is owed, uploads keep the connection fully used. A large upload that fails while running this way is never shown as an error; whatever did not land goes again on the next turn. Fixing media and gathering media into a project wait for their upload to finish instead.

- Setting: Time for each project. Does: how long one project syncs before the next has its go. Default: 10 minutes, never less than 1 minute. Who: the editor in the app's settings for their own computer, or an admin for any computer from the dashboard. Applies to: a computer. Search words: turn, project time, fair, queue, order.

### Uploads go newest first and downloads smallest first, both at once

Originals upload newest first, proxies download smallest first, and uploading and downloading run at the same time. A file is never sent by two transfers at once; one skipped for that reason is picked up on the next pass. From time to time the server's folder layout is made again on the computer, empty folders included.

### A project with a big backlog gets extra turns while the others are idle

When a project's downloads stop at the end of its turn with files still to fetch, and every other ticked project had a complete turn in roughly the last ten minutes that found nothing to do and nothing has changed in any of them since, that project gets another turn straight away. Every quiet project is still checked again within about ten minutes. It never happens while syncing is paused or stopped, while the sync drive is missing, while another project is still waiting to be set up, or when the round found the server unreachable, and any change to the plan comes first. After the app restarts, the first round follows the plain order.

### A transfer that stops moving is stopped and started again

Transfers are watched about every 30 seconds, and bytes moved decide, not time taken. A transfer that has moved nothing for 15 minutes is stopped, shown in red with "no progress for N minutes", and started again; a transfer still moving bytes is never stopped or alerted on for taking long. A transfer a person asked for (originals picked, "Sync now") is never dropped by rules meant for background passes.

For 24 hours afterwards the editor sees "⚠ <Uploading | Downloading> stopped moving for N min and was restarted. If it keeps happening, check the drive is connected". The last such stop on a computer (which direction, how long, whether it was stopped, when) is reported to the dashboard, survives a restart of the app, and counts as current only until a transfer in that same direction completes a pass, or 24 hours at most; recovery in the other direction never clears it.

### A download that hangs on one project does not hold up the others

A download that runs well past its project's time is stopped so the other projects get their turn. If it still will not end, no new download starts on that computer until it does, and the download state shows "stalled on <folder>: waiting for an earlier pass to end". Downloads come back on their own when it finally ends, with no restart needed, and a late pass for a project that is no longer current is dropped. Uploads carry on throughout.

### When the server cannot be reached the app says so and waits

When the NAS cannot be reached, the app shows "cannot reach the server" as its own state, never as a broken sync, stops spending passes on transfers that cannot succeed, and resumes within about a minute of the network coming back.

### The app's background work restarts itself when it stops

A pass that fails costs that pass only; the next one runs as usual. If the app's background syncing stops or stops checking in, it is restarted within 30 minutes on its own, and the dashboard shows how many times this happened in the last 24 hours, the latest one and its error. A computer whose syncing has stopped never goes on reporting a frozen, healthy state.

### The dashboard shows why nothing is moving on a computer

For each computer the dashboard shows the computer's own answer to "why is nothing moving" (a reason, a detail and since when); the last transfer it found stuck, for how long and whether it had to be stopped; how long each project's turn is there, which sets how long the dashboard waits before calling something stuck; how many times its background syncing had to be restarted in the last 24 hours, the latest one and its error; whether any of its syncing has stopped working, since when, how many restarts were tried, the last error and whether anything is still trying (yes, no or cannot tell); and how many files edited on two computers it holds.

- See The dashboard: Each computer's state.

### Each direction on a computer's row has its own colour and reason

Every computer's row shows its uploads and its downloads, always in that order. A direction the computer did not report shows "not reported" in a muted green; green is always muted. Failing: red, with the last error. No report for 6 hours or more: red, "this computer has been silent for 6 hours or more"; 15 minutes or more: amber, "this computer has been silent for 15 minutes or more". Busy with no data moved for more than 15 minutes, timed by the server's own clock: red, "syncing, no progress for N min"; when the computer cannot say whether data moved, no verdict. Syncing: amber. Otherwise green. A stuck transfer stops counting as stuck when its report is over 24 hours old or that direction has since completed a pass.

Admins see a serious problem, "a sync transfer is stuck", while a computer's transfer is stuck: the computer's own "why" sentence plus "A drive that has stopped answering reads exactly like this, and the other transfers on that computer wait behind it." The fix: restart CC Sync on that computer and check the drive opens.

#### Lessons

- Met: SYN-086, SYN-087, SYN-088, SYN-089, SYN-090, SYN-091, SYN-092, SYN-093, SYN-094, SYN-095.
