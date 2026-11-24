# Sync, part 2 of 2

This part covers what a person is told about the sync and what is still owed, how lightly an idle studio loads its NAS, speed and routes, clocks and file age, computers joining and changing, project folders on an editor's computer, and the facts about NAS systems, Windows and macOS that the sync must live with.

## Saying truthfully what the sync is doing

### Each computer says in one sentence why it is not syncing, and since when

Every computer that is not syncing carries a sentence saying why, with the time the cause began (or was first seen). The same sentence, in the same words, is shown in the app on the editor's computer, on the overview, on the per-computer view, on the editor's own view of their computers and in diagnostics, and it is there within one report of the computer. Each cause has its own sentence. A deliberate stop or pause is shown as what it is, never as a fault, and only a cause that truly needs an admin's approval sends the editor to their admin. When no reason applies there is no sentence: the computer's state line says what it is doing instead, and no sentence is ever shown just to say "all good".

The reasons, highest first:

| Cause | Sentence |
|---|---|
| nobody is signed in on the computer | "Not syncing: nobody is signed in to CC Sync on this computer" |
| the licence has not been accepted on it | "Not syncing: the licence agreement has not been accepted on this computer yet" |
| the sync drive is missing | "Not syncing: the sync drive is not there on this computer" |
| the sync drive is there but not answering | "Not syncing: the sync drive is mapped but not answering, so nothing can be read or written" |
| the sync drive is mounted in the wrong place | "Not syncing: the sync drive is pointing at the wrong place" |
| downloading stopped itself because the drive is nearly full | "Not downloading: downloading stopped itself because the sync drive has only <free> free" |
| an admin stopped syncing for every computer | "Not syncing: syncing is stopped by your admin for the whole studio" |
| syncing is stopped on this computer | "Not syncing: syncing is stopped on this computer" |
| the editor paused it | "Not syncing: syncing is paused on this computer" |
| downloading stopped itself as a safety measure | "Not downloading: downloading stopped itself as a safety measure and needs a person to check the server: <reason>" |
| nothing is ticked (information, never a fault) | "Nothing ticked for this computer" |
| a ticked project's folder is not where it should be | "Your project folder for <name> is not where CC Sync expects it. Did you rename or move it?" with " (<N> project folders are missing)" when there are several |
| one or more projects are held back while the others sync | "Not syncing <N> project(s): <up to 3 names> (<why>)", for example while a newly ticked project is not yet protected against the files that must never sync |
| the project is upload only here (information) | "Nothing to download: this project is upload-only on this computer" |
| uploading or downloading is busy with nothing moving | "Not syncing: <uploading or downloading> has been busy for <duration> with nothing moving" |
| syncing on the computer has stopped running | "Not syncing: syncing on this computer has stopped running" with how many times it has been restarted and its last error |
| the computer cannot reach the server | "Not syncing: this computer cannot reach the server" with the reason when known |

Every other cause that is also true and can be fixed separately is added after the first as ". Also: <sentence>", so the computer names every reason it is not syncing, most actionable first. The computer's own detail is added in brackets unless it only repeats the sentence, is over 120 characters, or the reason is that nothing is ticked. A stuck upload or download that the server can see has started moving again is no longer shown. On a computer that works straight off the server, nothing is ever said about nothing being ticked, about being stuck, or about syncing having stopped running.

Two further lines are added as information, never as a fault: "N clip(s) in the open project are outside the tree and will never upload", and "N clip(s) only on this computer in '<project>' [and M other project(s)], which it does not have open; they will never upload".

A wrong clock on the computer is never a reason for not syncing; it is shown on its own (see "Each computer's clock is measured against the server's and a gap is shown").

- Ways in: the app on the editor's computer, the overview, the per-computer view, the editor's own view of their computers, and diagnostics.

### The app's menu says in one phrase what syncing is doing now

The menu of the app on the editor's computer always carries one line starting "Sync:". The first that applies:

1. A stop is in force: "Sync: stopped by your admin" (an admin's stop for every computer) or "Sync: stopped on this computer", with " (and paused)" when the editor has also paused.
2. Downloading stopped itself as a safety measure: "Sync: downloading stopped (see Settings)".
3. The computer is not set up, or the licence is not accepted: "Sync: not set up yet".
4. The sync drive is away: "Sync: paused (<drive phrase>)" or "Sync: paused (<drive phrase>, <owed> still to go)".
5. Paused by the editor: "Sync: paused".
6. Another reason syncing is held: "Sync: <the sentence>".
7. Files are moving: "Sync: up U · down D files · 4.2 MB/s", "Sync: uploading N files · <rate>" or "Sync: downloading N files · <rate>". The rate is in megabytes per second (decimal), with one decimal.
8. Files are waiting: "Sync: waiting, not connected to the server (N files owed)" when everything waiting needs a server that is not connected, otherwise "Sync: N files waiting", with " (not connected to the server)" when part of it is waiting for a connection.
9. "Sync: up to date".

When both a stop and a pause are set, a second line warns: "⚠ Two things are stopping sync on this computer: your admin's stop and a pause." or "⚠ Two things are stopping sync on this computer: a stop and a pause. Clear both to sync again."

The same sentences, word for word, are used wherever the app says why syncing is held or that it is waiting for a connection.

- Pending: sync-2-U1

### The app's window shows what is going up, what is coming down and the originals asked for

The app's own window has one line for each of: "Going up (your footage and project files → server)", "Coming down (server → you)" and "Originals you asked for (server → you)". Each line reads, the first that applies:

- the sync drive is away: "<label>: PAUSED (<drive phrase>)";
- the computer is not set up: "<label>: NOT SYNCING: <the sentence naming what is wrong, cut to 180 characters>" or "<label>: NOT SYNCING (this computer isn't set up yet)";
- paused: "<label>: PAUSED";
- failed: "<label>: PROBLEM. <the error, explained in plain words>";
- nobody signed in: "<label>: NOT SYNCING (sign in first)";
- on a computer that works straight off the server: "<label>: not used on this computer (it works straight off the server)";
- moving: "<label>: syncing (X of Y · speed/s · ~N min left)", or "<label>: syncing…" when the totals are not known yet;
- waiting: "<label>: N items to go";
- otherwise: "<label>: up to date (<detail>)".

When the computer's list of what to sync was last confirmed by the dashboard 24 hours or more ago, the syncing, waiting and up-to-date lines add " (sync plan from N days ago: the dashboard has not answered since)". The age is the time since the dashboard last answered, never the time the list was first made, and an age that cannot be told is never shown as fresh. A line "Now syncing: <project>" names the project being worked on.

### An editor asks for a sync now

"Sync now" in the app checks the server for changes at once. It is refused, with the reason in the words above, when something holds syncing. When the dashboard's plan for this computer is known and empty it says "Nothing is ticked for this computer, so there is nothing to sync." Otherwise it says "Checking the server for changes now." and what it will do (send footage up, bring files down). If it cannot start: "CC Sync could not start syncing. Open the log and send it to your admin."

- Who: the editor, on their own computer.

### An editor sees the originals they asked for arrive

While originals the editor asked for are coming down, the app shows "Bringing originals: {done} of {total}, {size} to go", with files moving, files waiting, bytes, speed and time left, refreshed about every 2 seconds. Otherwise it shows:

- all present: "all {N} asked-for originals are here";
- nothing to fetch because the files are missing on the server: "{N} asked-for originals are not on the server";
- finished: "brought {done} of {total} originals down";
- held, checked continually so that a download in progress stops within about a second: "NOT DOWNLOADING ORIGINALS: syncing is stopped on this computer" (an admin's stop or the computer's own), "NOT DOWNLOADING ORIGINALS: syncing is paused" (the editor's pause), "NOT DOWNLOADING ORIGINALS: the sync drive is not connected", "NOT DOWNLOADING ORIGINALS: {reason}" when the place they would land is refused by the same rules that guard every download into the tree, and the sentences about disk space (see Sync: Disk space);
- failed: that the server could not be listed to find the originals, that some originals did not arrive (with how many), or the transfer's own failure in a sentence.

### The app and the dashboard show the same live picture of what is moving

For what is going up and for what is coming down, separately, the app and the dashboard show in the same terms:

- the state, one of idle, syncing, waiting, paused, stopped or error, and since when it has held;
- since when progress last moved: repeating the same figures does not reset it, and a report with no progress figures shows "no verdict";
- files waiting and files moving;
- the last failure, as a sentence, up to 2,000 characters;
- when it last finished cleanly;
- a one-line detail of what it is doing, and the project it is working on;
- bytes done and to do, speed and time left;
- a row for each file moving, up to 256 at a time: its name, direction, bytes done and total, percentage, speed, time left and project.

The picture is refreshed about every 2 seconds in the app and with each report on the dashboard. Each finished file is added to the transfer history (name, direction, when). Every change of state or of the last failure is kept in a history for 30 days. The current state of a computer that has said nothing for 30 days is forgotten.

The detail line says, among other things:

- idle: "last synced" is the time of the last check that found everything in step; a computer with no projects to check says "no project folders to check yet" and keeps its last-synced time, never setting it to now;
- waiting: "waiting: not connected to the server (N file(s) owed)" when nothing can reach the server;
- going up only: "sending N file(s) (<size>) to the server";
- a project just ticked: "setting up N newly ticked project(s)";
- paused: "N folder(s) paused" when every project is paused;
- error: the projects not set up or held back on this computer, by name; projects in error, with the reason; and problems with shared folders, the first one plus "(+N more)".

The dashboard marks an upload or download as stuck when it says it is working but has moved nothing; a slow one that is still moving bytes, a long upload of one big file included, is never called stuck. A transfer that cannot start, stop or report never takes the app down with it; the problem appears as its last failure.

- Name and search words: Transfers. Search words: transfers, moving, upload, download, progress, speed.

### How a sync that did not simply succeed is shown

A clean ending shows how many files were transferred. A failure shows the most useful error line from the transfer, leaving out generic notices, or says that it ended with a failure. Retries that succeeded inside a sync are not shown. Running out of a project's time, reaching the limit on removals, being stopped, and a safety stop are each shown as what they are (see Sync: Safety stops and Sync: Stuck, slow and fair transfers), never as a failure. An upload is never shown in error when every file it was sending is on the NAS, and an error names its files and its reason, in the app, on the dashboard and in the log, in the same words.

### Syncing comes back by itself when it stops running

Syncing on a computer that dies, for whatever reason and at whatever time, is brought back within a minute or two, without waiting for anyone to sign in to the computer again. While it is not running it is shown as failing, with its cause, never as healthy. Restarts back off when they keep failing, and the editor is told after repeated failures. A failed attempt is logged, kept as a local crash report and counted ("N failed attempt(s) since the app started"), and the next one follows after the usual wait. If syncing stops altogether, the reason is recorded and it shows as stopped.

Every part of the sync resumes after a pause, after signing out and in again, and after the drive returns: nothing that is not running ever shows a healthy status. A deliberate pause is never overridden by a restart and never reported as an outage. A transfer stopped because a person or the app asked it to stop shows as stopped, never as an error, and a safety limit doing its job shows as paused.

The dashboard shows, for each computer, the app's own reason for not syncing, its detail and since when, and how many times syncing restarted in the last 24 hours, with the last time and the last error. These clear with the next report that says syncing is fine.

### Admins are told when syncing has been down or failing on a computer for an hour

Two serious alerts:

- "syncing is down on a computer": raised when a computer has reported its syncing down for an hour or more, never for a computer that works straight off the server. "Syncing on <who> has been down for <duration>." The fix given: quit and restart CC Sync from its icon, and send diagnostics if it happens again. The detail names how many times the computer tried to restart it and the last error.
- "a sync transfer has been failing": raised when uploading or downloading on a computer has been in a failed state for an hour or more; the subject names the computer and the direction. "<Uploading or downloading> on <who> has been failing for <duration>."

- Who: admins.

### A file changed in two places at once keeps both versions

When a project file was changed on two computers at once, both versions are kept: the second is kept beside the first as a conflict copy. The product counts the conflict copies, shows the count and up to 20 examples on the dashboard, and logs a warning while any exist. It never deletes or merges them.

### Each project's progress on each computer is shown, with the project's own state on the NAS

About every minute, for every project, the dashboard records the project's state on the NAS and any error (so a stopped or broken project shows), its total files and size, and what editors are still sending up to it. For each computer that receives the project it shows the percentage complete (0 to 100), the files and bytes still owed, how many deletions are pending, and a download speed averaged over recent readings so that it does not jump about, starting afresh when new work arrives. Progress is counted by bytes, so proxies and other files weigh what they are.

A figure that could not be got is left out, never shown as 0%. On a studio with very many projects a figure may be up to about two minutes old; until refreshed, a project keeps its last known figures. The project list shows every computer's completion under each active project, ordered by person and then computer name. When a project stops being shared with a computer, its completion and its list of missing files are removed at once, so a computer that no longer syncs a project never shows as behind on it. Forgetting a computer removes all of this for it.

A history of each computer's completion on each project is kept for a graph: a point is written the first time the pair is seen, when the whole-number percentage changes, when the files still needed go from none to some or change by more than 10 percent, every 15 minutes while incomplete, and at most every 6 hours while complete. After 48 hours the history is thinned to one point an hour, and after 30 days it is forgotten.

- Name and search words: Projects. Search words: projects, progress, complete, behind, percent.

### The sync list shows, per person and computer, the order projects sync in and what is left

Under the safe-to-close sentence, the sync list reads "For <person>[ on <computer>]: top to bottom, in the order they sync." Each ticked project shows its position, a state light, its name with "syncing now" on the one being worked on, "upload only" (leading to the glossary), "gone" ("This project no longer exists on the server."), and "shares <subfolder> from <other project>" lines; how far it has synced (a meter and percent, "upload only", or "no data yet"); and what is left ("N files, <size>, <speed>/s, about <time> left", "synced" or "-"). It is refreshed every 10 seconds and at once after any tick.

"Untick" on a project removes it from every computer of that person, after asking: "This removes <project> from <person>'s N computer(s) (<names>). Their copies stay on disk; nothing new comes down and syncing stops for it." with the button "Stop syncing this project to <person>'s computers. Nothing already there is deleted."

With nothing ticked the list reads "Nothing ticked, so nothing syncs to this computer. Tick a project in the projects list." for one computer, or "Nothing ticked, so nothing syncs to your computers. Tick a project under each computer above, or in the projects list." for a person. This is never shown as a warning.

- Who: anyone signed in sees their own; an admin may choose any person or computer.
- Ways in: on the overview, for whoever is chosen; on a person's own view of their computers, always for themselves.

### A tick takes effect within seconds and says "getting ready" until data flows

A project ticked for a computer starts to take effect within about 5 seconds, and shows "getting ready" until data begins to flow. For 30 minutes after a tick, the ordinary states of setting a project up raise no error, notice or mail; anything still wrong after that is alerted as usual. After a project is ticked again, or its mode changes, the next look at it examines every file in it, so nothing new is skipped.

### A computer's warnings clear as soon as it reports they are over, and silence means "cannot tell"

These conditions a computer reports are rewritten, back to nothing included, by every report that carries them, and left as they were by a report that does not: downloading stopped by itself (with reason and time), a stop for every computer or for this one (with scope and reason), syncing not running (since when, how many restarts were tried, last error), how many times the app has crashed and its newest crash report, shared folders not yet protected against the files that must never sync (count and names), the number of conflict copies, and transfers the app ended because they stalled (which direction, how long, when). A computer whose last report did not carry them answers "cannot tell" to questions such as "has its downloading stopped itself", never "no".

A warning about one project stays until that project itself is found clean; a clean look at another project never clears it.

#### Lessons

- Met: SYN-100, SYN-101, SYN-102, SYN-103, SYN-104, SYN-105, SYN-106, SYN-107, SYN-108, SYN-109, SYN-110, SYN-111, SYN-112, SYN-113.

## What is owed

### When the sync drive is pulled with work owed, the editor is told what is owed and reminded until it is back

Only work that is really moving counts as owed: a direction that says it is syncing but moves nothing does not. The summary names what is owed, for example "2 uploads and 14 other files (2.3 GB left)", using uploads, downloads, originals coming down, other files going up, other files coming down and other files. The drive is named as the site names it ("Your ... drive").

- First notice: "<Your ... drive> was disconnected before syncing finished: <summary> still to go. Plug it back in to finish syncing."
- Reminder: "<Your ... drive> is still disconnected and syncing is unfinished: <summary> still to go. Plug it back in to finish syncing."
- A drive plugged in but not answering: "<Your ... drive> is still not answering, so nothing is syncing. Reconnect it or restart this computer."

With nothing owed, the editor gets only one calm "Sync paused" notice. Reminders come every 30 minutes, and only while something owed is going up; when everything owed is coming down, only the first notice is given. A drive that is not answering is always reminded. The editor can snooze ("remind me later": one reminder after the chosen minutes, then the usual pace) or stop the reminders for this time; neither removes the standing warning line, and neither is remembered after a restart. The drive coming back ends it all. The episode is remembered across restarts: if the app restarts while the drive is still out with work owed, reminders carry on with one at once and no new first notice.

- Who: the editor, on their own computer.
- Setting: Drive reminders. Does: how many minutes pass between reminders that the sync drive is away with work owed; 0 means the first notice only. Default: 30 minutes. Who: the editor for their own computer, or an admin. Applies to: a computer. Search words: drive, reminder, unplugged, disconnected, owed.

### The dashboard lists what each computer still owes, and never claims "nothing" when it cannot tell

For each person, computer and ticked project, the dashboard lists what is waiting to go up and to come down, worked out from what the server holds against what the computer says it holds:

- Owed down: files on the NAS the computer does not hold, never for an upload-only tick. When the computer's own list was cut short, the number shown is the smaller of the difference and "files on the NAS minus files held", sizes likewise, with no names.
- Owed up: originals the computer holds that are not on the NAS (see "Files that are never sent are never counted as owed").

Each row gives direction, kind, file count, size, up to 50 file names (an admin can ask for more), and whether the names, the list or the count are uncertain. For a computer behind on a project, the full list of files it still lacks can be opened, with sizes where known, up to 500 names; a list cut there says it is cut and how many more there are. The list is cleared when the computer is complete on that project, and forgotten when it has not been refreshed for 7 days.

Rules that keep the list true:

- Only ticked projects are listed. Computers that work straight off the server, and people whose every computer does, never appear.
- A file already moving is not listed again as waiting.
- A row with nothing waiting is dropped, unless the computer's own list was cut short, so that "nothing" really means "cannot tell": then the row stays, at zero, marked uncertain.
- A just-ticked project shows a "preparing" row on each computer until there is something to count. An upload-only tick shows "preparing" until that computer's first list of its files arrives.
- A computer that withholds its file list (see Accounts, privacy and the legal paperwork: What the product records about a person) shows, for each ticked active project, an uploads row marked uncertain and "not reported", never "nothing owed".
- A row on a computer that has said it cannot move (drive unplugged, stopped, nobody signed in and so on) says it is held, and why.
- "Idle, nothing owed" is claimed for a computer only when the server could really count what it owes: never for a computer that works straight off the server, one that never sent its file list, or one whose only answer is "cannot tell". That count is at most about 15 seconds old and is redone as soon as anything it depends on changes.

Totals give the files queued (preparing rows not counted) and the bytes queued. No list of what is owed is ever cut short without saying so.

- Name and search words: Transfers. Search words: queue, owed, waiting, still to upload, behind.

### Files that are never sent are never counted as owed

Whatever uploads deliberately leave behind is never counted as owed going up, judged by the same rule on the editor's computer and on the server (see Sync: Files that must never sync). Among them: Mac resource-fork files whose names start with "._", copies the product made itself to make a file ready to edit, files marked as an original kept aside or as temporary, unfinished pieces of downloads, files that failed, and files of a move in progress, all compared ignoring capitals. Leftovers of a download that died are never owed for ever.

### Every editor is told whether it is safe to shut down or unplug their computer

Worked out for the signed-in person only, naming their computers (the dashboard cannot know which computer the browser is on). Shown to an editor always, and never on an admin's view of the whole studio.

- A computer holds more video originals than it can list, and nothing is known to be owed: "Cannot tell yet: <computer> (<project>) holds more video originals than it can list to the dashboard, so some may not have uploaded. Leave it running and check its tray." A computer that withholds its file list: "Cannot tell yet: <computer> does not report its file list to the dashboard, so the dashboard cannot tell whether everything uploaded. Check its tray." Never "safe" then.
- Nothing owed going up, something coming down: "Safe to close: nothing of yours is waiting to go to the server. 1 file is still coming down and carries on where it left off next time." (or "N files are still coming down and carry on where they left off next time.")
- Nothing at all: "Safe to close: nothing is transferring."
- Uploads owed: "Not yet: N file(s) still uploading from <computers> (<size>), about <time>. Leave that computer running." ("Leave those computers running." for several, "Leave it running." when a computer is unnamed), adding "There may be more: <computer> holds more video originals than it can list to the dashboard." where it applies. The time is what is owed divided by the current upload speed, given only when there is a speed.
- The short form beside what is moving: "Safe: nothing of yours is going up, so you can shut down or unplug." or "Not yet: closing or unplugging now would leave footage on one disk. Leave it running until this says safe."

- Who: anyone signed in, for themselves.
- Ways in: on the overview, beside what is moving now, and at the head of the sync list on the overview and on a person's own view of their computers.

### The dashboard knows what each computer holds, project by project

For each project on an editor's disk, the dashboard knows how many originals and proxies it holds, their total size, whether the list was cut short, when it was sent, and the files with their sizes. A folder on the disk is matched to its project by name, with names compared so that a Mac's spelling of accented letters matches the same name from Windows or the NAS. A folder with no registered project still gets its own entry. A new full list for a project replaces the earlier one. Whatever a computer reports is stored only up to a limit: past it, one entry says how many were left out, so no computer and no file an editor can write can make the server store without end.

### An interrupted upload never leaves a broken file where a good one is expected

An upload cut off part way (the computer shut, the network dropped) never leaves a broken or partial file where the footage is expected on the server: until a file has arrived whole, the server's copy of the project does not show it, and the upload carries on where it left off next time. Nothing of an editor's is ever deleted to tidy up after one. For each computer an admin can see how much space unfinished uploads from it hold, and how many there are.

- Who: admins see the space held.

### A newer local file that will never upload because the server has its name is reported

Each project is checked for files that exist both on the editor's computer and on the server with the same name but a different size. The first version of a name to reach the server is the one kept there (see Sync: What syncs where), so the local one will never upload. It is reported with an example and the two ways out: rename the local file, or have an admin remove the server's copy. The app can list up to 20 such files with this computer's size. Projects no longer ticked, or whose folder is gone, drop out of the report.

#### Lessons

- Met: SYN-114, SYN-115.

## Load on the NAS when nothing changes

### A change starts syncing within about a minute, and an idle studio barely touches the NAS

- A new or changed file in a ticked project on an editor's computer starts going up within about a minute.
- A tick, an untick or a change of mode takes effect within about 5 seconds.
- A change on the server reaches every computer that syncs it within about 5 minutes.
- "Sync now", resuming after a pause and the drive coming back each look at once.

When nothing changes, a computer looks less and less often, but never less often than every 5 minutes. A computer with nothing new costs the NAS a few sign-ins an hour, and that cost does not grow with the number of computers times the number of projects. A project found fully in step is not compared with the server on every look, but is always compared again within about two hours, at once after "sync now" or a resume, and whenever there is doubt (a restart, a change of plan, a recent change in the project, a failed download).

What a computer reports about projects that have not changed sends and stores almost nothing. A report that would be too large drops only as much detail as it must, and says so.

When the server cannot be reached, the computer stops trying for that moment, says so in its log and on its status, and tries again shortly.

#### Lessons

- Met: SYN-116, SYN-117.

## Speed and routes

### Transfers are fast, and each computer's speed is shown against what its connection can do

On the same connection, uploads and downloads each reach at least 60 MB/s, over the fastest route available between the editor's computer and the NAS. The speed each computer really achieves, going up and coming down, is shown in the app and on the per-computer view, beside a public measure of what that computer's internet connection can carry, so that when an internet route is the limit, that is what a person sees, not a slow product.

- Name and search words: Speed. Search words: speed, slow, bandwidth, MB/s, connection.

### Several editors' transfers run together and share the studio's connection

When several editors sync at once, their transfers run together and together fill the server's connection to the outside; no editor waits for another to finish.

### The app and the dashboard say when a computer's connection goes the slow way round

For each computer the dashboard shows whether its connection to the studio goes direct or the slow way round through a go-between. The app's detail line says when transfers are taking a slow, indirect route to the server. A report that does not mention these leaves the last values in place.

### A remote editor's downloads take the studio's fastest path, and an admin can choose it

A remote editor's downloads take the fastest of the studio's connections that reaches their computer. Where the studio has more than one (for example a faster link used only for downloads), an admin can choose which one a computer's downloads use; everything the computer sends up always goes the normal way, and the other connection is only ever read from. The change takes effect at the next sync. The per-computer view shows which connection each computer's downloads use, and says so plainly when it is the slow one.

- A connection that would send the studio's password readable across the public internet is never used; that computer's downloads stay on the normal connection, and the per-computer view says why.
- The chosen connection does not answer: downloading pauses with "NOT DOWNLOADING (route): the server's download link did not answer, so download is paused and nothing was changed here. It tries again next time."
- The chosen connection shows a project as empty while this computer holds files there (for example a sign-in page standing in front of it): "NOT DOWNLOADING (route): the server's download link listed {project} as empty while this computer holds {N} files there, so download is paused and nothing was deleted. It tries again next time."
- Either way it tries again by itself, and nothing on the computer is ever deleted because of an answer from that connection.

- Who: an admin.
- Setting: Download connection. Does: which of the studio's connections this computer's downloads use. Default: the studio's normal connection. Who: an admin. Applies to: a computer. Search words: download, faster, remote editor, connection, speed.

### Footage travels only over the studio's own private network

Footage and project files move only over the studio's own private and local network, never through outside relay services, and the NAS never announces itself publicly. A newly approved computer finds the NAS on the studio's private network by itself.

- Pending: sync-2-Q2

### A computer can be set to sync one project at a time, everything in it included

Normally every ticked project's smaller files (everything other than footage and proxies) keep syncing whichever project the computer is busy with. A computer can instead be set to hold every other project still while one project has its turn, for up to that project's whole turn.

- Setting: One project at a time. Does: holds every other project's files still while one project syncs. Default: off. Who: an admin. Applies to: a computer. Search words: one project, at a time, turn, order, queue.
- Pending: sync-2-Q1

#### Lessons

- Met: SYN-118, SYN-119, SYN-120, SYN-121.

## Clocks and file age

### A file is sent only once it has stopped changing

A file is not uploaded while it is still being written, so a clip still being copied off a card or out of another program never goes up half-written. Whether a file has finished is judged by watching its size and its time stop changing for 2 minutes, never by its date alone: a 40 GB camera file just copied can carry a date hours old, and still be growing. A file whose date is in the future uploads like any other once it has stopped changing.

### A new proxy on the server is brought down only once it has stopped changing

A proxy still being written on the server is never brought down cut short: one that has changed in the last 2 minutes, measured by the server's own clock, is fetched later.


### Files dated in the future are shown to the editor until their date is fixed

Files the app sends whose date is more than 5 minutes ahead of this computer's clock, often from a camera with a wrong clock, are listed for the editor and on the per-computer view: how many, examples with their dates, the earliest such date and when it was checked, with the advice that a few hours ahead usually means this computer's clock is wrong, and further ahead means the file's date should be reset. They upload like any other file, and the list stays until the dates are put right.

### Each computer's clock is measured against the server's and a gap is shown

Each report that gets through compares the computer's clock with the server's. The difference is kept (ahead counts as positive) and shown as "N seconds" under 90 seconds, "N minutes" under 90 minutes, otherwise "N hours", followed by "ahead" or "behind". A difference of more than 60 seconds is shown to the editor in the app, at sign-in and in diagnostics, and to an admin on the per-computer view: "This computer's clock is <N ahead of/behind> the server's. Turn on setting the time automatically." A computer time more than 7 days away from the server's is not trusted as a time, though how far off it is is still kept. An unreadable time is shown as unknown, never as "no difference". No rule about a file's age trusts a computer's clock alone, so a wrong clock never stops anything from syncing.

### Admins are told when a computer's clock is five minutes or more out

A serious alert, "a computer's clock is wrong", is raised when a computer's clock is 5 minutes or more ahead of or behind the server's. It explains that the times that computer reports, and the dates it gives new files, are wrong by that much. The fix given: turn on setting the time automatically on that computer.

- Who: admins.

#### Lessons

- Met: SYN-122, SYN-123, SYN-124.

## Computers joining and changing

### An admin approves a new computer and ties it to an editor

A new editor's computer asks to join the studio, and waits, listed among the computers waiting for approval. An admin approves it and ties it to an editor by choosing that editor; the computer is named after the editor so that it is matched to them, and receives that editor's ticked projects within about a minute of approval. Until then nothing is shared with it, and its row says it is waiting for approval.

- Approving without choosing a known editor leaves the computer belonging to nobody, and the admin is told that the dashboard will then not manage what it receives.
- A computer already approved is not added again; choosing a different name renames it (a rename that fails is a warning).
- When approving shares several projects, each succeeds or fails on its own, the rest still run, and the admin is told "applied N of M" with the reason for each refusal.
- It ends by saying that the next step is ticking the editor's projects. Doing it again changes nothing.
- A known computer that comes back as if new (reinstalled, for example) is shown as such, waiting for approval, and once approved its transfers resume within a minute.
- When the list of computers waiting cannot be read, it is shown as unknown, never as "nobody waiting".

A warning is raised for each computer that has waited 24 hours or more to be approved (or whose waiting time is unknown), naming it when known: "approve it from the list of computers waiting for approval". It cannot be approved by replying to a mail.

- Who: an admin.
- Name and search words: Computers waiting for approval. Search words: approve, new computer, join, waiting, accept.

### A computer belongs to a person only once it is tied to a known editor

A computer is linked to a person only when it has been tied to an editor the dashboard knows (on a brand-new dashboard that knows no editors yet, any computer named like a sign-in name counts). A computer that belongs to nobody is listed as belonging to nobody, and the product never adds or removes anything it receives on its own. For every computer that has ever connected, the dashboard knows its name, whose it is (or nobody's), whether it is the server itself, when it was first and last seen, whether it is connected now, its last address and when it last connected; whether it is connected is refreshed about every minute. Whose a computer is is worked out afresh each time, never remembered from before.

### A renamed computer keeps its plan and everything waiting for it

Each computer is recognised as itself after a change of its name. When a computer reports under a new name and is recognised as an older entry of the same person that has been quiet for 5 minutes or more, the new name takes over: its ticks, its chosen project for new footage, the originals it asked for, and every request still waiting for it (file moves, Resolve undo, a settings change and the rest) move to the new name, and the old entry is removed. What it last said it holds on disk, and its transfers, rebuild under the new name, and the old ones are forgotten in time.

The rename is refused, with nothing changed, when the new name is already a computer of that person with a plan of its own, so a clash of names can never destroy a plan. When the computer is already known to be the same one (recognised as itself, old name quiet), it may take over a new-name entry that has no ticks and no chosen project of its own. A settings request already finished at the new name gives way to one still waiting at the old name; one still waiting at the new name is kept.

### A disk copied onto a second computer is caught and explained

When an editor's disk has been copied onto a second computer and both are running CC Sync, the two look like one computer. The product notices, moves nothing between them, and shows a serious problem on the overview: "Two computers are reporting the same identity: ... This happens when one computer's disk was copied onto another one ...", saying a copied disk is in use on two computers at once when both have been heard from within 15 minutes of each other. The fix given: on the newer computer, quit CC Sync, have it start afresh as a new computer (the app's Settings window offers this), wait five minutes, then remove the old entry with "Forget" on the per-computer view. The problem is raised once, in the same words, on the overview and as an alert by mail, and clears when the clash is gone. Neither computer's ticks are touched.

- Who: admins.

### An editor is told once when their computer may not be recognised after a rename, and syncing carries on

When the app cannot be sure it will recognise this computer again after a rename, it says so once each time it starts: "Syncing is not affected, but this computer cannot be recognised again if it is renamed. The Settings window can repair this, and your admin may want to look first." Syncing carries on as normal.

- By hand: the editor repairs it from the app's Settings window.

### A new server over a NAS editors already sync from keeps what each computer syncs

When a server that has no ticks recorded meets projects already being synced to editors' computers, each of those becomes a tick for that editor once: on that computer if known, or on the person's not-yet-assigned plan if not. This only adds ticks, never takes one away. It waits, saying "waiting to read what editors already sync" on the server's health, until at least one project and at least one computer it can tie to a person are seen.

#### Lessons

- Met: SYN-125, SYN-126, SYN-127.

## Project folders on an editor's computer

### The editor picks the folder for the project tree when setting up

At this step of setting up, the screen is headed with the signed-in name and a sentence saying what will happen for this computer's role and system. The field is "local sync folder" on a remote editor's computer and "project tree root" on one that works straight off the server. Suggestions:

| | Windows | macOS |
|---|---|---|
| remote | a folder named after the studio's tree on drive C:, with the hint to point it at a drive with room to spare (it does not have to be C:) | a folder of that name in the home folder, with the hint that it is best on an external SSD plugged in now (for example a folder on it named after the tree) |
| straight off the server | the site's drive letter | empty: the editor points it at the server share, mounting the share first |

If the editor changes role, a suggestion they have not edited follows the new role. The tree's name defaults to CC Sync's own when the site gives none, or gives one that is not a plain folder name.

The folder is checked as the editor types. A problem shows in red with a cross and keeps the install button disabled; a check that itself fails never blocks.

- Windows and macOS: on Windows a folder is refused when it is empty (with an example), starts or ends with a space, holds a double quote, does not start with a drive letter (a network path gets its own message), is a whole drive on its own such as D:\ for a remote editor (it must be a folder), is on the project drive letter itself for a remote editor (that drive is the one the install creates: pick the real folder it should point at), or names a drive letter this computer does not have. On macOS it is refused when it is empty (the example depends on the role), starts or ends with a space, starts with ~ (write the full path instead), does not start with /, is / or /Volumes on its own, is a whole external drive on its own for a remote editor (pick a folder on it), or names an external drive not mounted now (remote: plug the SSD in and unlock it if it is encrypted, and a leftover folder from an unclean eject may be in the way; straight off the server: connect the server share first with Finder, Go, Connect to Server).

### A ticked project's folder layout is made on the editor's computer, empty folders included

For a fully ticked project, every folder of the project on the server is made on the editor's computer, empty ones included, so the editor sees the project laid out as on the server. A folder made on the server appears on editors' computers within about 5 minutes without anyone asking, and at once after the project is moved on the server. It never happens for an upload-only project, and never while the sync drive is missing, so no stray tree is ever built on the start-up disk.

### When an admin renames or moves a project on the server, every editor's copy follows by itself

Before anything else syncs, the app compares where each ticked project lives on the computer with where the dashboard says it is now. When they differ, the project was renamed or moved on the server, and the editor's folder is moved to match first, so nothing is ever uploaded back to the old place. Nothing needs remembering: a fresh install, an editor who was away through several renames, or an update all land in the right place at the first look. Letter case and the direction of slashes are ignored in the comparison.

- Old folder gone and new one present: nothing is moved.
- Neither present: nothing happens.
- The new place already holds a synced copy of the project: the old folder is left where it is for a person to deal with, and syncing continues from the new one.
- The new place holds only empty folders: they are cleared and the move goes ahead.
- The new place holds files but is not a synced copy: the move is refused.
- Moving to another drive: the folder is copied, put in place only when complete, and the old one removed only then; if it cannot all be removed it is left with a warning. A half-finished copy from a failed attempt is cleared at the next attempt. Empty parent folders left behind are not tidied.
- The move fails (on Windows usually because Resolve, Explorer or antivirus holds a file open): the project stops syncing and stays visibly blocked until the move can be made, because syncing from the wrong place would spread the whole project as deleted to the server and every editor. It tries again by itself at every look. The product never adopts a folder it made itself in place of the real copy, and never stops uploading the real copy.
- The target must lie inside the editor's synced tree, or nothing is moved.
- If the admin undoes the rename, or the editor ticks the project again, it syncs from where it is.

The editor sees one of these ({name} is the project's path):

- "Your admin renamed a project on the server. CC Sync moved your copy to match ({name}). Resolve was relinked."
- "Your admin renamed a project on the server. CC Sync moved your copy to match ({name}). Resolve reconnects the clips next time you open that project." This changes to the relinked sentence once the relink succeeds.
- "{name} is not syncing because CC Sync could not move its folder. Your files are safe where they are. Close it in Resolve and in Explorer, then it retries by itself."
- "{name} is not syncing because a folder with its new name is already on this computer. Your files are safe where they are. Move that other folder somewhere else, then it retries by itself."

Once the folder is where it belongs, the "could not move" sentence clears and the project syncs again. The last 20 such events are kept for each computer, one per project, old place and outcome, so a project that fails every time does not crowd out real renames. Relinking Resolve continues in Resolve on the editor's computer: Missing clips, relinking and refreshing.

- When the help for the editing program is off: the sentences end at "CC Sync moved your copy to match ({name})." and the two failure sentences say "Close any program using it" in place of naming Resolve.

### A project folder moved or renamed by the editor is noticed, named and can be put back in one click

The app remembers that each ticked project's folder was there. A folder not yet seen on this computer is an ordinary first state ("project folder not yet on this computer: {path}"). A folder seen before and now gone is shown as an error naming it: "Your project folder for {name} is not where CC Sync expects it. Did you rename or move it?", and, when a folder carrying the same project is found elsewhere among the projects, " It looks like it is at {path} now." The app's window shows, for up to 5 folders, "'<name>' is not where CC Sync expects it - nothing in it is reaching the server", with "  found at <path>" when it was found. It clears when the folder is back. If two folders claim the same project, the first found is taken. Up to 20 such folders are reported to the dashboard.

The app never moves it on its own. Where the folder was found, a button "PUT '<name>' BACK WHERE CC SYNC EXPECTS IT" moves it back. It never overwrites a folder already at the expected place and never deletes anything. Its answers:

- "<N project folders> put back where CC Sync expects them. Syncing starts again at the next look."
- "<N folders> put back; <M> could not be moved. Close Resolve and Explorer on them and try again."
- "CC Sync could not move that folder back. Close Resolve and Explorer on it and try again."
- "CC Sync cannot find that project folder anywhere on this computer. If you moved it to another drive, move it back by hand."
- "CC Sync could not check where that folder is. See the log."
- "CC Sync is still starting up. Try again in a moment."

- Who: the editor, on their own computer.
- By hand: the put-back button; the app never follows a move the editor made.
- Windows and macOS: on macOS the answers name Finder in place of Explorer.

### Project folders in no sync plan are reported and never deleted

Project folders on an editor's computer that are not ticked there are found and reported: how many, their total size, and up to 20 of them. The app's window shows "N project folders on this computer are in no sync plan (X.X GB). Nothing syncs them and CC Sync will not delete them". Nothing syncs them and nothing deletes them. They are looked for at most every 15 minutes, and not at all while the computer's plan is empty or cannot be read: an empty or unknown plan is never taken to mean that every folder is stray, and never raises a warning.

### The dashboard shows and warns about project folders out of place and footage not yet filed

For each computer the dashboard shows how many project folders on its disk are in no plan, and their size; how many project folders are not where they should be; and how much footage was dropped in on that computer but not yet filed. Three warnings name the computer: "project folders outside the tree", "a project folder has moved", and "footage is waiting in a drop folder".

- Who: admins.

### Every project folder on the server is checked to still be recognised as its project

A standing check confirms that every active project folder the server can see is still recognised as the same project. A folder that is not is a serious problem. Folders missing entirely are skipped, and the check shows as not checked when no project tree or no folder can be found.

- Who: admins.

### A computer or a person can have a chosen project that new footage lands in

Each computer, or a person as a whole, can have a chosen project that new footage dropped in on it lands in. A computer's own choice records who set it and when. A computer without its own choice uses its person's; for a person with neither, any of their computers' choices is used.

- Setting: Project for new footage. Does: names the project that new footage dropped on this computer lands in. Default: none. Who: the editor, or an admin. Applies to: a computer, or a person. Search words: new footage, drop, landing project, default project.

#### Lessons

- Met: SYN-128, SYN-129, SYN-130, SYN-131.

## Facts about the NAS and the operating systems

### Downloads from a Synology NAS always arrive whole

A fact about Synology: its built-in secure file transfer service silently cuts short any download larger than 514 MiB when the file is asked for in pieces larger than 64 KiB, and it should not be given more than 16 transfers at once. On TrueNAS there is no such limit. Downloads from a Synology NAS therefore always stay within those limits (an appliance the vendor supplies does not have the fault), and always complete; no admin ever has to tune anything for it.

On every NAS, a downloaded file shorter than its source is never marked done.

### Sync onto the NAS never depends on changing permissions

A NAS share can be in a restricted permission mode that refuses changes to file and folder permissions. Syncing onto the NAS never depends on changing them, and transfers complete on such a share.

### Moving or restoring a file never overwrites one already there, on any system

On macOS a rename silently replaces a file already at the destination. Moving or restoring a file never overwrites an existing file on any system, including one that appears while the move is under way: the clash is refused and the file is named.

### A file of zeros left by a power cut is never sent over a good copy

A power cut can leave a file of the right size filled with zeros, which a check of the size alone calls good. Such a file is never sent over a good copy on the server or on another computer.

#### Lessons

- Met: SYN-132, SYN-133, SYN-134, SYN-135.
