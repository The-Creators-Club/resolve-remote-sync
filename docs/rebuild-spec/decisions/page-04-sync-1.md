# Decision list, page 4: Sync, part 1

Stays behind: never shown to the session that rebuilds the product.

21 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 4.1 Should every transfer that is cut off carry on where it stopped, instead of a camera original starting again from nothing?

- **Today:** an upload of a camera original cut off by quitting, an update, a stop, a shutdown or a lost connection starts again from the beginning next time (the shutdown warning tells the editor so, and a large upload is kept running past its project's turn to avoid it), while project files pick up where they were.
- **Options:** A: every transfer, up or down, carries on where it stopped. B: keep it as it is, with the warning saying a part-way file starts again.
- **Recommended:** A, because a field editor on a slow connection may otherwise never finish a large file, and with it the special handling for long uploads is no longer needed.
- **What you would notice:** with A, switching off mid-upload loses nothing and the shutdown warning says so; with B, a half-sent 20 GB clip goes again from zero.
- (sync-1-Q1)

### 4.2 Should everything that comes down to a computer follow the server's deletions the same way, by moving the removed file into the recovery folder?

- **Today:** a proxy removed or replaced on the server is moved into the recovery folder on every editor's computer and the safety stop guards those removals; a project file (an edit project, sound, a document) deleted on the server or another computer is never deleted on this computer, and earlier versions of changed project files are kept separately for 30 days.
- **Options:** A: one rule for everything that comes down: a file gone from the server is moved aside into the recovery folder, never deleted, under the same safety stop and limits. B: keep proxies following the server and other project files never following deletions.
- **Recommended:** A, one rule with one place to look for a lost file and one stop protecting it.
- **What you would notice:** with A, a document deleted on the server leaves an editor's computer too, recoverable from the recovery folder for its keep period; with B it stays on every computer until removed by hand.
- (sync-1-Q2)

### 4.3 Should one recovery folder with one keep period hold everything moved aside or replaced on an editor's computer, set by an admin beside the NAS's own keep period?

- **Today:** removed proxies are kept in the recovery folder for 14 days and up to 50 GB; earlier versions of changed project files are kept for 30 days elsewhere on the computer; the NAS keeps deleted and replaced files for a year.
- **Options:** A: one recovery folder per computer, 14 days and 50 GB by default, set by an admin for the site together with the NAS's year. B: keep the separate periods.
- **Recommended:** A, so an editor looking for a lost file has one place and one stated period.
- **What you would notice:** with A, an earlier version of a changed edit project is kept 14 days instead of 30, in the same folder as everything else.
- (sync-1-Q3)

### 4.4 When a file already on the server is changed on an editor's computer, what should happen?

- **Today:** a camera original whose name already reached the server is never replaced (the first version wins) and the editor is only told; in an upload-only project a changed file of any kind never goes up again; in a full-sync project other files replace the server's copy, the earlier one kept for a year. Earlier readers also asked whether an editor should be able to replace the server's copy of an original from the product.
- **Options:** A: camera originals stay first-version-wins, with the editor told and the two fixes (rename yours, or have the admin remove the server's copy); every other file, in either mode, replaces the server's copy with the earlier one kept for a year. B: keep today's three behaviours. C: as A, and let an editor replace the server's copy of an original from the product.
- **Recommended:** A, one rule for originals and one for everything else, while footage on the server is never overwritten.
- **What you would notice:** with A, an edit project changed after an upload-only upload goes up again; nothing changes for camera originals.
- (sync-1-Q4)

### 4.5 Should an editor have one pause, or both a pause and a stronger "stop all syncing"?

- **Today:** "Pause" stops uploads and proxy downloads but lets project files keep syncing and is forgotten on restart; "Stop all syncing" stops everything and holds across restarts until cleared, from the menu or the settings window. Lessons from real use require the pause to hold across sign-in, restarts and updates too, which leaves the two almost the same.
- **Options:** A: one pause that stops everything and holds until the editor resumes; no separate stop. B: keep both.
- **Recommended:** A, since with the pause remembered the stronger stop adds a second control for the same result.
- **What you would notice:** with A, the editor has one Pause and Resume; the "STOP ALL SYNCING ON THIS COMPUTER" control and its clearing entries go.
- (sync-1-Q5)

### 4.6 Should "Resume downloads" also be offered when downloads paused because the drive was nearly full?

- **Today:** one "Resume proxy download" action clears both the safety stop and the low-disk pause, with a different warning for each, although the low-disk pause ends by itself once there is room.
- **Options:** A: offer Resume only for the safety stop; the low-disk pause ends by itself and "Sync now" tries again at once. B: offer it for both.
- **Recommended:** A, because it removes a button that only does what happens anyway.
- **What you would notice:** an editor who has just freed space presses "Sync now" instead of "Resume downloads".
- (sync-1-Q7)

### 4.7 Who may copy one computer's plan onto another computer of the same person?

- **Today:** in the admin's view only an admin can; another part of the product lets the person copy between their own computers.
- **Options:** A: the person for their own computers, and an admin. B: an admin only.
- **Recommended:** A, the same people who may tick and untick for those computers.
- **What you would notice:** with A, an editor with a new laptop copies their desktop's plan themself.
- (sync-1-Q8)

### 4.8 Should a computer with no dashboard set sync the whole tree all the time?

- **Today:** with no dashboard address, a computer syncs the entire shared tree, with no ticks and no order; elsewhere the same case is described as syncing nothing.
- **Options:** A: cut it: a computer always belongs to a studio and syncs only what is ticked for it. B: keep the whole-tree mode.
- **Recommended:** A, because every computer is set up against the studio's dashboard and a whole-tree sync can fill a laptop.
- **What you would notice:** none for a computer set up the normal way.
- (sync-1-Q9)

### 4.9 Which libraries should reach every editor's computer without a tick?

- **Today:** the LUT library and the Resolve gallery stills; notes in the product expected the b-roll archive and the music library too.
- **Options:** A: those two only. B: also the b-roll archive and the music library. C: those two, plus any folder an admin marks as a studio-wide library.
- **Recommended:** A, because the archive and music are large and are reached through their own pages, which bring a clip or track down when asked.
- **What you would notice:** with B, every editor's drive carries the whole archive and music library.
- (sync-1-Q11)

### 4.10 Should the button that switches a computer to remote read "SWITCH TO REMOTE EDITOR" instead of "DELETE ANYWAY"?

- **Today:** the confirmation asks for REMOTE to be typed but the button reads "DELETE ANYWAY".
- **Options:** A: "SWITCH TO REMOTE EDITOR". B: keep "DELETE ANYWAY".
- **Recommended:** A, the button says what it does.
- **What you would notice:** the button reads plainly.
- (sync-1-Q14)

### 4.11 Should the Resolve menu offer "Stop originals - whole timeline", to match "Bring originals - whole timeline"?

- **Today:** "Bring originals" has selected clips, In to Out and the whole timeline; "Stop originals" has only the first two.
- **Options:** A: add it. B: leave it out.
- **Recommended:** A, so every way to ask has a way to stop.
- **What you would notice:** one more menu entry in Resolve.
- (sync-1-Q15)

### 4.12 Should an admin be told when an editor removes a project from their computer while uploads were still owed?

- **Today:** the computer reports it, but the server only writes it to its log; nobody is told.
- **Options:** A: the admin is told, naming the computer, the project, how much was owed and why. B: leave it in the log.
- **Recommended:** A, because footage the server never received is exactly what an admin must hear about.
- **What you would notice:** an admin sees a problem when this happens.
- (sync-1-Q16)

### 4.13 Should the dashboard show the things each computer already knows about its syncing?

- **Today:** each computer knows whether its sync folder is there, problems with its included folders and libraries, project folders it moved after a rename on the server, and its recovery folder's details, but the dashboard does not show all of them.
- **Options:** A: show those about syncing on the computer's view. B: stop collecting what is not shown.
- **Recommended:** A, so the admin sees what the editor sees without asking.
- **What you would notice:** the per-computer view gains these lines.
- (sync-1-Q17)

### 4.14 Should one "keep this much free" figure per computer decide every free-space verdict?

- **Today:** downloads pause below 20 GB and restart at 40 GB; recovery copies are dropped when the drive is short by another measure; the dashboard colours red below 5 percent or the floor and amber below 10 percent or 50 GB; one alert fires under 50 GB, another when the drive is red, a third when the computer says it stopped; set-up warns under 200 GB.
- **Options:** A: one floor per computer (20 GB by default) decides when downloads pause and restart, when recovery copies are dropped, and every "has stopped" verdict and alert; the amber colour and the 50 GB and 200 GB notes stay as early advice above it. B: keep the separate rules.
- **Recommended:** A, one number that every screen agrees on.
- **What you would notice:** an admin's "stopped for space" problem appears exactly when the editor's downloads pause.
- (sync-1-Q18)

### 4.15 When project folders disappear from the NAS, is "never delete, mark inactive, refuse a mass disappearance and tell the admin" what you want?

- **Today:** a vanished project is left set up and marked inactive; when many vanish at once none is marked and only a line on the health panel says so.
- **Options:** A: as written, with the admin told in a problem. B: something else for cleaning up old projects (for example, archiving them).
- **Recommended:** A, since a mass disappearance usually means the NAS is not mounted, not that projects were deleted.
- **What you would notice:** an admin sees a problem rather than a quiet health line.
- (sync-1-Q19)

### 4.16 Should the Footage Sorter's "link folder" be offered wherever the Sorter runs?

- **Today:** it is offered only in the stand-alone Sorter; the Sorter page on the dashboard answers that it is "not here".
- **Options:** A: offer it wherever the Sorter runs. B: cut it, and include folders only from the project's page.
- **Recommended:** A, since the Sorter is where the person sees the second copy about to be made.
- **What you would notice:** the dashboard's Sorter page gains "link folder".
- (sync-1-Q20)

### 4.17 Should the reminder about a pulled-out sync drive have a setting that can turn the repeats off?

- **Today:** the reminder repeats every 30 minutes by default and a computer setting can change it, with 0 giving only the first warning. Your ruling says it repeats every 30 minutes until the drive returns, and any narrowing needs your agreement.
- **Options:** A: no setting; every 30 minutes as ruled, with the editor's "remind me later" and "stop reminding me" for one outage. B: keep the setting.
- **Recommended:** A, as ruled; the editor's own buttons already cover a drive in a bag.
- **What you would notice:** nobody can turn the repeats off for good.
- (sync-1-Q21)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 4.18 | Where can downloads be restarted after a safety stop? | from the app's menu, from the app's settings window, and by an admin from the computer's row on the dashboard. | A, one way at the computer and the admin's remote way that real use showed was needed. (sync-1-Q6) |
| 4.19 | Can sharing a project with a computer by hand, while accepting it, go? | while accepting a new computer an admin can share one project with it by hand, but the dashboard undoes such a share for every editor it knows. | A, since ticking does the job and the hand share is undone anyway. (sync-1-Q10) |
| 4.20 | Should "why is this computer not syncing" give the same reasons in the same order everywhere? | the app gives six reasons with "paused" first; the dashboard's sentence knows seventeen and puts "nobody signed in" first. | A, so an editor and an admin read the same reason. (sync-1-Q12) |
| 4.21 | Should "this computer works straight off the server" be reached only by choosing wired, without the separate switches? | a computer stops syncing or keeping local proxies by being set to wired, or by two separate switches (no syncing, no local copies of proxies). | A, one choice with one meaning. (sync-1-Q13) |

## Your answers

ANSWERED 2026-11-24. After answering pages 2 and 3 and most of page 4 one
by one, he said of everything still waiting: "accept all the
recommendations." So every question on this page is answered with its
recommendation, with one exception he chose himself before that: 4.6, where
"Resume downloads" IS still offered when downloads paused because the drive
was nearly full (against the recommendation). 4.1 to 4.5 and 4.7 to 4.19 he
answered one by one, each as recommended.
