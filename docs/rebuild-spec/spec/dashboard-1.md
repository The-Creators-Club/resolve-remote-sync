# The dashboard, part 1 of 2

The dashboard is the set of web pages the studio's people open in a browser to see and steer CC Sync: what each computer is syncing and how far along it is, which projects exist and who takes them, what is moving and what is waiting, who the people and computers are, and what the server has found wrong with itself. Every signed-in person can open it; an editor sees what concerns them and their own computers, and an admin sees and steers the whole studio. The dashboard is core: it is never switched off, and a switchable part that is broken or absent never stops it from opening. This part covers the home page and how people find their way, each computer's state, ticking and unticking, projects, transfers and the queue, people and computers, what the dashboard knows about each computer, and the problems the server finds.

## Overview, menus and finding things

### The Overview is the home page

The Overview is the first page after signing in, and the product's mark with the studio's name always leads back to it. It gathers, on one page:

- the problems the server has found (admins only), in an area of fixed size that scrolls when it is full, so many problems never push the rest of the page away (see "Everything the server knows is wrong is in one list");
- the studio's health and the state of each switchable part (see "Each part's state is shown on the Overview");
- a summary of syncing: the four readouts (see "Four readouts sum up the studio at a glance") and the computers, with a link to each computer's details;
- the version the server runs and whether the computers are up to date;
- quick links to the settings people use most.

An editor sees their own computers in full and summary counts for the rest of the studio. An admin sees every computer. The head of the sync summary reads "N computer(s) · N project(s)".

An admin can look at the Overview as another person: they choose the person, then optionally one of that person's computers. A computer chosen that is not that person's is ignored. An editor sees only themself. Projects are ticked on the Projects page, not here.

Admins also get a "Stop the fleet" shortcut, explained as "it pauses syncing on every computer at once until you start it again. Nothing is deleted, and the pause ends by itself after 24 hours unless you choose another length." It leads to the one studio-wide stop (see Sync: Studio-wide stops and the editor's pause, "An admin stops syncing on every computer with a reason"). While the studio is stopped, every page says so.

- Who: anyone signed in; acting for another person and the stop are for admins only.
- Name and search words: Overview. Search words: home, overview, start page, summary, dashboard.

### Four readouts sum up the studio at a glance

Four readouts sit at the top of the sync summary. They are drawn when the page opens and refreshed together with the list of computers, and each count always agrees with the rows below it for the same view.

| Readout | Figure | Line underneath |
|---|---|---|
| online | "N / M": M is the computers with at least one project ticked (a computer wired to the server, or one with nothing ticked, is left out), N those heard from recently | "<computer> not heard from[, and N more]" as a warning; "every computer with a project ticked has reported"; or "no computer has a project ticked" |
| moving | everything still owed: files moving now plus uploads and downloads waiting | "N project(s) catching up", "N file(s) moving now", or "nothing waiting" |
| problems (admins only) | open problems of error severity the server found, the same count as on every page | "N warning(s)", "listed below with what to do", or "nothing needs you" |
| in sync | "N / M": M is the projects ticked anywhere (by this person for an editor, by anyone for an admin), N those not behind and not getting ready | "all caught up", "N still catching up", or "no project is ticked anywhere" |

A computer with nothing ticked never turns the online readout into a warning.

### Each part's state is shown on the Overview

Each switchable part (the b-roll archive, music, YouTube downloads, Timeline Cards, the Footage Sorter, the help for the editing program) is in one of these states, shown on the Overview with its reason in plain words:

- working;
- not working: it is switched on but could not start or cannot do its job, with the reason;
- working badly: it started, but something it needs has gone (for example its library can no longer be read), shown within one check of it happening;
- not checked: its state could not be read, with the reason.

A part that is switched on but not working, or working badly, keeps its place in the menu; opening it shows a page saying in plain words that it is not working right now, why, and that admins have been told. It is also named on the list of problems. The dashboard always opens, whatever state any part is in. With the b-roll archive switched off, the health line for it reads "the b-roll platform is switched off on this server". The Timeline Cards editor, when something it needs is missing, shows a page that says so.

A new site starts with every switchable part off except the help for the editing program, which is on. A part that is switched off is seen by nobody except an admin, in settings, where it is listed with its switch. No menu entry, link, tab or control of a switched-off part appears anywhere else.

- On its own: the product decides each part's state from whether it started and whether what it needs can still be reached.

### The menu bar

The menu bar is on every page of the dashboard and on every page of every switchable part, so a person can always get back to the dashboard in one click. It holds:

- Overview;
- Sync, which opens a dropdown with three entries, each a page of its own: Projects, Transfers, and Computers (which computer is syncing what, and how far along). The dropdown opens when rolled over with a mouse and when tapped on a touch screen;
- each switchable part that is switched on, listed after the dashboard's own sections;
- Settings, for admins only;
- the general search;
- the count of open problems and alerts, for admins (see "Every page shows admins how many problems and alerts are open");
- the account menu.

On a phone the main places stay reachable with one hand. When nobody is signed in, the only thing offered is "sign in".

- Who: anyone signed in sees the menu; Settings and the problem counts are for admins only.
- Name and search words: Sync menu. Search words: sync, menu, projects, transfers, computers.

### The general search finds any page, part, setting, project, computer or person

A search box in the menu bar takes a name and jumps straight to what it finds: any page, any switchable part, any setting, any project, any computer and any person. It matches each page's, part's and setting's plain name and its search words, and the names of projects, computers and people (display names and sign-in names). It finds only what the person searching may open: an editor never finds admin pages or settings, and nobody but an admin finds a part that is switched off (and only as its switch in settings). Choosing a result opens it; for a setting, the page holding it opens with the setting in view.

- Who: anyone signed in.
- Name and search words: Search. Search words: search, find, jump to, go to, look up.

### The settings search finds settings only

Inside Settings, a second search finds any setting by its plain name or its search words and opens it in view. It returns settings only, never pages, projects, computers or people. Settings are listed in groups by what they do; the groups are the ones the builder proposes from the list of every setting and the owner approves.

- Who: an admin.
- Name and search words: Settings search. Search words: settings, find a setting, options, preferences, configure.

### Every state word and status light explains itself

Every state label, status light, short tag and coloured chip carries a plain explanation of what it means. It can be read in full with a mouse (pointing at it), on a touch screen (tapping opens a sheet with the label, the explanation and "tap anywhere to close") and from the keyboard. No reason code from inside the product is ever shown to a person.

### Every page remembers where the person was on it

For each dashboard page (not the pages of the b-roll archive, music, YouTube downloads or Timeline Cards), the browser remembers the scroll position, which fold-out sections were open, which sections the person folded away, and the last tab chosen. A page showing a particular person, computer, project, kind or view is remembered apart from the plain page; text typed into a search does not make a separate memory. The memory survives a phone closing the installed app, and is ignored after 8 hours.

On returning, sections are opened again and the page scrolls back once its panels have loaded, waiting up to 3 seconds and then going to the remembered heading. It does not restore when the address points at a particular place, when the browser restored the page itself (Back or Forward), or once the person scrolls, touches, types or clicks first. There is no visible cue, and nothing happens where the browser blocks storage. Folded sections stay folded across refreshes.

### A link can lead to any place on a page

Following a link to a particular part of a page opens whatever holds it (a tab, a folded section, a fold-out) and scrolls to it, once that place has arrived, when the page loads and whenever the link changes, without fighting a person who has already started scrolling; following the same link again does it again. A link naming a fold-out section of the Overview opens it once; if the person folds it again, later refreshes respect that. Every control can be reached and worked from the keyboard. The only single-key shortcut on dashboard pages is "/", which puts the cursor in the page's find box.

### The account menu

The account menu shows "signed in as <name> (admin)" (without "(admin)" for an editor) and offers:

- the person's own page (see "A person's page shows each of their computers");
- help;
- the installer download (see "The installer link downloads the build for the visitor's computer");
- sign out;
- sign out everywhere, which asks "Sign yourself out of every browser, including this one? You will need to sign in again to finish what you are doing."

When the browser offers to install the dashboard as an app, an INSTALL button appears. The person's name (with "@admin" for admins) is shown in the menu bar and leads to their own page; it is hidden on small screens.

- Who: anyone signed in.
- Name and search words: Account menu. Search words: account, sign out, log out, profile, me.

### The installer link downloads the build for the visitor's computer

Clicking the installer link downloads, at once, the installer for the operating system of the computer the visitor is using (Windows or macOS). The installer for the other system is still offered beside it.

- Who: anyone signed in.
- Windows and macOS: the link picks the visitor's own system.
- Name and search words: Installer download. Search words: installer, download, install app, set up computer, get the app.

### Builds on offer are listed in a fixed order

Wherever builds of the app or the server are listed, the ones being served to the studio's computers come first, then the other versions the server holds, then what the vendor offers. Within each, builds are grouped by kind, then by platform. Each group of held versions shows its current and its newest version; only older held versions are folded away, and they are offered when choosing a version to go back to. The page is in Releases and updates: Pushing updates and seeing who has what, "The versions page shows every version the site holds"; publishing and offering builds are in Releases and updates: Offering an update to a computer.

### Help and the glossary are open to everyone signed in

The help pages show the product's documentation. Opening help with no document named opens the customer guide to how the product works ("How this system works, in plain English... The glossary is what every word on the other pages links back to."), with "Need a person? Contact <support contact>".

The page shows a list of documents in groups (the main documents first, then each further group alphabetically; within a group the guide first, labelled "the customer explainer", then by title), each entry showing the document's own title and an optional note, with the current one marked; a contents list built from the document's headings; and the document.

Every person signed in sees the same documents: the customer guide, the editor set-up guide, every legal paper (licence agreement, privacy note, note on what computers report, YouTube feature notice, third-party notices) and the plain-text licence texts of third-party parts. Documents not yet published (legal drafts awaiting counsel) are never listed or shown. The list never names a document the person may not open. A newly added document appears in the list within about 30 seconds.

Messages:

- no documents at all: "Help is not installed on this server.", asking whoever installed the server to put the documents in place;
- a missing or refused document: "That document is not on this server. It may be one this build does not ship, or the link inside the document you came from may be stale.", with the list still shown.

- Who: anyone signed in.
- Name and search words: Help. Search words: help, guide, manual, documentation, how does it work.

### Every word on the pages links to the glossary

The glossary is a help document in which every term has its own link. The "what the words mean" links on other pages, and the per-word links beside state words, land on the exact term.

- Name and search words: Glossary. Search words: glossary, what the words mean, terms, definitions, meaning.

### Help documents are shown safely and link to each other

Licence texts are shown exactly as written. Other documents are shown formatted: headings, each with a stable link made from its words and leaving out any section number (so "4.1 Your sync plan" is linked as "your-sync-plan", and a repeated heading gets -2, -3), a contents list of the second- and third-level headings, paragraphs, lists (one level of nesting; numbered steps separated by blank lines stay one list), code blocks, tables (scrolling sideways when wide), rules, bold, italic and links. Web, mail, in-site and in-page links work; a link to another document opens it in the help pages, keeping the section; a link of any other kind, or to something that is not a document, is shown as plain text with its target in brackets. Nothing written inside a document can ever act as part of the page. The page's title is the document's title. Only the product's own help documents can ever be opened, whatever address is typed.

#### Lessons

- Met: DSH-001, DSH-002, DSH-003, DSH-004, DSH-005, DSH-006, DSH-007, DSH-008, DSH-009, DSH-010.

## Each computer's state

### The Computers page lists every computer and its state

The Computers page (the per-computer view in the Sync menu) has one row for every computer that has ever reported, including one silent for 30 days or more. It refreshes every 15 seconds.

The head reads "N computer(s) · checked <ago>" (when the server last finished looking at the studio), with a link "what the words mean" to the glossary. The columns are: computer, sync (explained: what goes up, what comes down, the project files kept in step), issues, version, last report. Each row shows:

- a status light and one headline (see "Each computer leads with one headline");
- the computer's name and the person's display name (and sign-in name when different);
- how each kind of movement is going: video originals going up, proxies coming down, and the project's other files kept in step both ways. Each has a small meter and a state word, with ", stalled" when that one is making no progress; pointing at it or tapping it reads "<what>: <state> - <reason or last error>". A quiet row never shows an alarming detail;
- the version running ("?" when unknown) plus "current <v>" when it is behind;
- the time since its last report.

An editor sees only their own computers, with the line "Showing your computers. N other computer(s) in the fleet: N unhealthy, N on an out-of-date build."

A page or a row about one computer shows only that computer's facts, and which computer was chosen survives a refresh. Only a page about a person (not one of their computers) shows the facts of that person's most recently heard-from computer.

- Who: anyone signed in; an editor sees their own computers.
- Ways in: the Sync menu, the Overview's sync summary, a person's page, a project's page.
- Name and search words: Computers. Search words: computers, machines, fleet, who is syncing, devices, per computer.

### Each computer leads with one headline

Each computer shows exactly one headline. The first of these that is true wins:

1. A named fault, red: the computer's own sentence saying why it is not syncing, for a reason that is a fault (see Sync: Saying truthfully what the sync is doing, "Each computer says in one sentence why it is not syncing, and since when"), including "Not syncing: nobody is signed in to CC Sync on this computer" when no person is signed in on it, and "Not syncing: this computer cannot sign in to the server: <reason>" when it is running but the server turns it away (its sign-in refused or revoked, its person suspended or removed). A pause the editor made and an admin's studio-wide stop are not faults: they take the information line below.
2. Not heard from. With nothing ticked, muted: "Nothing ticked for this computer. Last report <date time> UTC". Otherwise "Not heard from since <date time> UTC" (or "Not heard from this computer for 15 minutes or more" when the time is not known), amber from 15 minutes, red from 6 hours.
3. The app out of date, amber: "Out of date: running X, current is Y".
4. A kind of movement that has stopped, red: "<Kind> has stopped: <reason>".
5. An information sentence, muted: the computer's information reasons ("Nothing ticked for this computer", "Nothing to download: this project is upload-only on this computer"), "Not syncing: syncing is paused on this computer" for a pause the editor made, and "Not syncing: syncing is stopped by your admin for the whole studio" for an admin's studio-wide stop.
6. "Syncing", muted.
7. Idle, muted: "Idle between checks, N file(s) still to move", "Idle, nothing owed" (only once the number of files owed has been checked and is zero), or "Idle".

A computer that has gone quiet reads as asleep or not reporting, never as a sync fault, unless it was known to be in the middle of moving files when it went quiet. A computer with nothing ticked is always fine: it leads with the neutral line above and is never an error, a warning, an alert, a blocked state, an open issue or a computer expected to sync, however long it is quiet. A computer wired to the server syncs nothing by design and never shows a sync fault, chip, headline or alert about syncing.

Beside the folded details, a count says how many further notes there are, so a headline is never calmer than what is folded under it. Each of these counts as a note: crashes of the app; the drive filling up; clips outside the shared tree; projects not open in Resolve with clips only on this computer; stray project folders; a project folder that has moved; conflicting copies of project files; an update that keeps failing; this computer being turned away; files it will not upload; a lot of footage in its own recoverable-files bin (over 5 GB); footage waiting in its drop folder; clips that need proxies; the Timeline Cards link to Resolve on this computer not running; YouTube clips waiting for Resolve, or the YouTube import having given up; clips with neither the original nor a proxy on this computer; Resolve having stopped answering. A note, issue or problem that depends on a kind of information the computer or the site withholds (clips outside the tree, clips only on this computer, stray project folders, a moved project folder) is not raised for that computer, and one already open closes without a message (see "A computer withholds kinds of information by choice").

Nothing in the headline, the notes or the issues is ever said about a state chosen on purpose (nothing ticked, a part the site switched off, a plan with nothing to change, a build already replaced by a newer one).

### Every status is red, amber or green and the worst wins

Every status on the dashboard is red, amber or green; wherever several are combined, red beats amber beats green.

How fresh a computer's last report is: under 15 minutes, green; from 15 minutes to under 6 hours, amber, "no report since <time>"; 6 hours or more, red, "no report since <time>". A last-report time that cannot be read is amber, "the last report time on record cannot be read".

One computer within one project, first match wins:

- a kind of movement failing: red;
- the report's freshness red: red;
- behind, and known to have been moving files when it went quiet 15 minutes or more ago: red;
- behind, or syncing, or the report's freshness amber: amber;
- otherwise green.

A project is the worst of its computers, and the whole studio is the worst of its projects.

### Each computer's issues are listed worst first, each explained

Each computer's row lists what is wrong with it, errors first and then warnings, or "nothing wrong" when there is nothing. Each issue carries its explanation:

- "downloads stopped themselves": "<reason>, stopped <ago>. Uploads are still moving; nothing was deleted." The reason is only ever the one the computer gave, at its own threshold (see Sync: Safety stops, "Downloads stop themselves when the server suddenly looks wrong").
- "stopped by your admin" or "syncing paused on this computer", with the reason.
- "project files not syncing <ago>" (never on a computer wired to the server): they have not been kept in step since <time>, whether anything is still trying, and the last error.
- "clock <amount> ahead" or "clock <amount> behind": "this computer's clock is <amount> ahead of/behind the server's. A clock this far out can make files fail to come down while reporting no error. Fix the clock on that computer (turn on automatic time)." Shown once the two clocks are a minute or more apart; the alert mailed to admins waits until they are five minutes apart.
- "stalled: <what>": it made no progress for N seconds, <ago>; "A local drive that stops answering reads exactly like this." Shown only while the stall is current: a finished pass in that direction since the stall began clears it, while a stall nothing can confirm as over stays shown.
- "being turned away: sign in on its app": "the last report from this computer was refused <ago>: <reason>. Nothing below is current. The editor has to sign in again in the app on this computer."
- "nobody signed in": nobody is signed in on this computer, so it syncs nothing until someone signs in.
- "update kept crashing": it installed <version>, kept crashing and was put back; it will not take that build again on its own; "Do not install it by hand: publish a newer build."
- "update failed xN": it tried to install <version> N times and failed; "Antivirus quarantine, a proxy mangling the download and a full disk all look like this."
- "withdrawn build": the reason the build was withdrawn (or "no reason given").
- "reverted from <version>": it installed <version>, could not start it, and put itself back on <running>; "That build should not be made current for the fleet."
- "suspended": "an admin suspended this person. Their computers are being turned away and their projects are not being sent to them. Their sync plan is kept: Resume puts it all back."
- "conflicts: N": "Two people saved one project file; nothing was lost, but somebody's edit is sitting in a renamed copy."
- "N clips outside the tree in <project>", with "N on the wrong drive" beside it when some are under the wrong drive letter: the project open in Resolve uses N clips from outside the synced tree; they will never upload, so the timeline opens with missing media on every other computer. Scanned <ago>. A Resolve project tied to no synced project raises nothing. When the open project cannot be known it reads "could not check", never fine; when the computer or the site withholds the open project, it shows the "not reported" tag instead (see "A computer withholds kinds of information by choice").
- "N other projects with clips only here": N clips exist only on this computer, outside the tree, in Resolve projects it does not have open ('<first three names>'[ and N more]); they never upload until the editor opens each project and gathers its media (see Resolve on the editor's computer: Fixing media: copying in, rehearsals and undo).
- "N stray project folders": N project folders on this disk are not in the synced tree, holding <size>; nothing in them is on the server or visible to anybody else.
- "project folder moved": N project folders are not where the tree expects; syncing for them looks busy and moves nothing; move it back (the app's put-back button), or, to rename or move the project for everyone, rename or move its folder on the server, which every computer follows (see Proxies and file moves: Moves made by hand on the NAS, "A project folder moved or renamed by hand on the NAS is followed").
- "won't upload: N": N files exist on the NAS under the same name at a different size (counted under <subfolder> when known); an upload never overwrites a file already on the server, so this computer's newer versions will never go up.
- "crashes: N": the app on this computer crashed N times in the background and wrote a report each time; its icon stays up and syncing looks normal, so ask this computer why (see "An admin asks a computer why, from its details").
- "youtube clips waiting for resolve: N" (they are on the disk, nothing is lost) or "youtube import gave up" (they stay on the disk under the YouTube folder and are tried again when the app restarts).
- the computer's YouTube state: its state and reason, how many clips are waiting and since when, and whether it can download; and, for any clip this computer should have downloaded and did not, its reason. The states and reasons are YouTube downloads' own (see YouTube downloads: Where a download runs, and saying so, "The page always says where each job ran and why", and Keeping the downloader working, "Admins are warned when downloading on the server or a computer is not working").
- "N need proxies": N clips on this computer have no proxy yet, so nobody else can see that footage; with the state of proxy making and how many are waiting.
- "N clips with neither original nor proxy here".
- "trash: <size>" (only above 5 GB): N recoverable files in this computer's own recoverable-files bin, removed by themselves after 14 days.
- "drop folder <size>": footage in this computer's drop folder not yet filed into a project; "It is on one disk."
- "drive filling up": the sync drive's free space is amber or red (see "Each computer's free space is shown with a plain verdict").
- "Resolve not answering": Resolve has not answered the app for N seconds, while doing <what>.
- warnings reported by shared work on this computer (b-roll or music indexing and the like).
- "version unknown" ("this app has never reported its version") or "out of date" ("<platform>: running <v>, current is <v>").

- When the help for the editing program is off: no issue mentions Resolve, clips in Resolve, or the editing program.
- When YouTube downloads are off: no YouTube issue is shown.

### Each computer shows the work in progress on it

After the issues, a computer's row shows what it is working on:

- each piece of shared work it is doing, "<kind of work>: N%", leading to the list of shared work, with the work's number, kind, state, file and last sign of life on pointing (see Work shared out across the computers: Progress);
- "lending until <time>": somebody at that computer chose to take shared work now, so it is offered work while they use it until <time> or until they turn it off; nothing else is bypassed (a studio-wide stop, an update or downloads that stopped themselves still hold it);
- when this computer is the one whose Resolve Timeline Cards works with: "cards[: <timeline>][ v<version>]" while that link is "running" (with the timeline and when it last talked to Resolve), or "cards not running" with the link's state word, "refused", "stopped", "credential refused" or "unreachable", and its sentence, so what the page shows from it is not current. Only "running" is green. Anything shown stopped is restarted within about a minute; only after 5 failed starts in a row does it stop trying until the app is restarted. The states are Timeline Cards' own (see Timeline Cards: the hand-over to Resolve, and exports: Which computer is driving Resolve, "Each computer shows whether its Resolve is taking part and if not why").

A computer stops showing work the moment its first report after the work ended arrives.

- When Timeline Cards is off: no "cards" state is shown.

### A computer's details fold out

Each computer's row folds out into its details. They stay open across refreshes, with "· N note(s)" beside them when there are notes (listed on pointing):

- storage: "disk N% used, <free> free" on the sync drive, and the free space on the system drive;
- Resolve, only when this computer has said something about it (never shown as zero when it has said nothing): connected, not connected or not checked; the project open; Resolve not answering for N seconds and what it was doing; proxies attached and proxies that failed, with why; a low-space note; the state of shared stills, with what to do when it is not all right; fold-outs listing missing clips, and clips refused because their path is not the right one;
- reporting: one quiet tag per kind of information this computer does not send, "not reported by this computer: <label>", explained as a privacy choice made on the computer or for the site, never a fault;
- this computer: its graphics card and hardware video encoder, and whether it can transcribe, when it has said;
- version: "<platform>, running <v>, current is <v>";
- licence: whether the licence was accepted, with when and, on pointing, a short fingerprint of the text accepted.

- When the help for the editing program is off: the Resolve details are not shown.
- Name and search words: Computer details. Search words: computer details, machine info, disk, licence, version.

### Each computer's free space is shown with a plain verdict

Each computer's sync drive free and total space and its system drive's free space are shown with the time they were measured. A value that could not be measured is shown as unknown, never as zero.

Beside them is shown the computer's own floor: the free space at which its downloads pause (20 GB unless the computer reports another figure). The verdict on the sync drive: amber under 10% free or under 50 GB free; red under 5% free or under the computer's own floor; otherwise green. A computer that never said, or whose figure is more than 48 hours old, gets no verdict. A low-space colour is a warning and never a stop: why a computer stopped bringing files down is told only from the reason the computer itself gave.

### What each computer holds of each project is shown

For each computer and each project on it, the dashboard shows how many video originals and proxies it holds and their total size; for projects ticked on that computer, the list of those files with sizes. Only video counts. This is refreshed about every five minutes, and as soon as the app starts. Counts come only from files found on that computer.

When there are more files than the dashboard lists, counts and sizes stay exact, the list says it was cut short, and no file ever looks owed because a list was cut. When the sync drive is unplugged, or goes during a check, the last complete figures stand. Ticked projects are matched however the computer spells accented names.

Where the editing program is in use, the dashboard also knows each computer's Resolve bins for each project: for each clip, its bin (empty is the top bin), clip name, file, whether it is an original, a proxy or something else, and whether the file is there. Pages show each computer's totals per project, which computers sent a bin listing, and each bin with its clips and how many are present. What a computer holds and its bin listings are forgotten when not refreshed for 14 days.

Every figure names the project or folder it covers, and a figure for one project never stands in for the whole computer or for another project.

- Windows and macOS: a Mac spells accented file names differently from Windows and the NAS; the dashboard treats both spellings as the same name.
- When the help for the editing program is off: bin listings are not shown.

### An admin asks one computer to do something and is told when it will happen

Requests an admin aims at one computer (update now, resume downloads, ask this computer why, change one of its settings) wait for that computer and reach it when it is next heard from. Each request waits until it has been carried out or for 14 days, whichever comes first, follows the computer if it is renamed, and is never delivered to a different computer claiming the same identity. Each answer to the admin names the editor and the computer and says when it will apply:

- nothing on record of the computer being heard from: "when that computer next reports. Nothing on record says when it last did";
- last heard from 24 hours ago or more: "when that computer next reports. It was last heard from <age>, so this may sit for a while";
- otherwise: "on that computer's next report, usually within 30 s. It was last heard from <age>".

For a version held back and not yet the studio's current one, it adds ", as an offer of a held-back version to this computer alone". These are the sentences for every request aimed at one computer, an update pushed to it included (see Releases and updates: Pushing updates and seeing who has what, "An admin pushes a version to one computer"). Ages read "N s ago" under 90 seconds, "N minutes ago" under 90 minutes, "N hours ago" under 48 hours, and otherwise "N days ago". A computer heard from 24 hours ago or more, or never, is marked as silent. A silent computer is warned about and never a reason to refuse. The admin is also told when the same request was already waiting from an earlier click.

- Who: an admin.

### An admin resumes a computer's stopped downloads

In a computer's details, "Resume" is offered when its downloads stopped themselves to protect footage and no resume is already waiting. It asks the computer to start again when it is next heard from, and then shows "resume asked" ("waiting for <machine> to report in and pick this up"). If the computer has left the studio: "That computer has left the fleet, so nothing was resumed. Reload the page." Why downloads stop themselves is in Sync: Safety stops.

- Who: an admin; the editor can also resume from the app on their computer.

### An admin asks a computer why, from its details

In a computer's details, "Ask this computer why" asks it to send its diagnostics when it is next heard from, and then shows "asked why" ("waiting for <machine> to report in and send its diagnostics") until the diagnostics have arrived, not merely until the ask was delivered. When diagnostics exist, "Read the answer" opens them (see "An admin reads the diagnostics computers sent"). An unknown computer is refused: "no computer '<machine>' for '<editor>'". The admin is told whether an earlier ask is still unanswered, together with when it will apply (see "An admin asks one computer to do something and is told when it will happen"). Asking is recorded in the history with who asked and when. It is not offered for a lost computer.

- Who: an admin.
- Ways in: a computer's details.

### Fleet-wide trouble is shown above the computers

Above the list of computers, banners say when syncing is stopped somewhere:

- the studio-wide stop: "stopped", "Syncing is stopped on every computer: an admin stopped the whole fleet." with the reason and "set by <who> <ago>" (the stop itself is in Sync: Studio-wide stops and the editor's pause, "An admin stops syncing on every computer with a reason");
- downloads that stopped themselves: "stopped", "Downloads stopped on N computer(s): <person/computer list>. Check the server, then press "Resume" on that computer's row (or have each editor resume downloads in the app on their computer)." with each computer's reason;
- paused at the computer: "paused", "Syncing is paused on N computer(s), by whoever is sitting at it/them: <list>.";
- computers being turned away (admins only): "refused", "N computer(s) is/are being refused: <list>. They are reporting and the dashboard is turning them away (<reason>). Have each editor sign in again in the app on that computer.";
- projects the server would not take off its lists all at once (see "Projects never vanish all at once because the NAS looked empty").

For admins the same place also lists the lost computers (see "A computer silent for a week is listed as lost"). When the server has never checked the vendor's release feed, or has had no successful check of it for more than 7 days, the one banner about it is the Overview's (see Releases and updates: Customer sites and the vendor's release feed, "The server checks the vendor's list every day, and an admin can check now").

### What computers can be asked to change is shown before asking

For each computer, the dashboard shows which of its settings can be asked for from the dashboard (nothing listed means it cannot take a request): whether it takes shared work and which kinds. Asking is in Accounts, privacy and the legal paperwork: What each person may see and reach, "A person or an admin asks one of the person's computers to change its settings". Beside them the dashboard shows, read-only, how long it lends itself to shared work (changed on the computer), whether YouTube downloads, YouTube sign-in and the YouTube terms are on, off or unknown, its YouTube sign-in state, and which settings are waiting for the app to restart. When the computer did not say what is waiting for a restart, that shows as "cannot tell", never "nothing waiting". The settings themselves are in The app on each editor's computer: Settings, records and background work.

- When YouTube downloads are off: the YouTube values are not shown.

### How fresh the dashboard's picture is

Every time on the dashboard about a computer is measured from when the server received what that computer said, never from the computer's own clock. A wrong clock on the server is reported as a problem of its own and never makes healthy computers look stale. A computer counts as live when it was heard from within the last 5 minutes; a time that cannot be read is not live.

| What | How soon it shows |
|---|---|
| which computers are heard from | about every 15 seconds |
| a tick or untick reaching the computer | within about a minute |
| sync progress for each project | about every minute, and within seconds while files are moving |
| a new project folder becoming tickable | within about five minutes |
| a file that reached the server showing as on the server | within five minutes |
| the server looking for problems | about every 10 minutes |

### Whether a computer is safe to close

Where the dashboard tells a person whether they may close or shut down a computer, it names each computer that still owes uploads, and says nothing is owed only once that has been checked. It is never shown while any project on that computer is still getting ready.

#### Lessons

- Met: DSH-011, DSH-012, DSH-013, DSH-014, DSH-015, DSH-016, DSH-017, DSH-018, DSH-019, DSH-020, DSH-021, DSH-022, DSH-023, DSH-024, DSH-025, DSH-026, DSH-027, DSH-028, DSH-029, DSH-030, DSH-031, DSH-032.

## Ticking and unticking

### An editor or an admin ticks a project for a computer

Ticking a project for a computer means that computer takes the project: its originals go up, and its proxies and project files come down (see Sync: What syncs where). Ticking is done on the dashboard, by the editor for their own computers or by an admin for anyone's. The app on an editor's computer cannot tick.

A tick is either full sync (the default) or upload only (see "Full sync or upload only, and switching between them"). Ticking a project that is already ticked the other way switches it.

A tick changes only the computer chosen. When no single computer is chosen, the tick covers every computer the person has that is not wired to the server; before it is saved the person is asked, with every computer named. A person with no computer yet gets the tick held for their first computer, which takes it when it is first heard from.

A tick is refused, saying why, when it is someone else's plan and the person is not an admin, when the project is unknown or archived, when the computer named is not the person's, and when the computer, or every computer of the person, is wired to the server. The rules and their sentences are in Sync: A plan belongs to a computer, "The rules every tick and untick follow, wherever it is made".

A tick is recorded in the history with where the project was ticked before and after (nothing is recorded when nothing changed), and reaches the computer within about a minute.

- Who: an editor for their own computers, an admin for anyone's.
- Ways in: the Projects page (each project's row and each project's own page), the admin's plan grid.

### An editor, an admin or the editor's own computer unticks a project

Unticking a project for a computer means it stops coming down there: "Its copies stay on disk; nothing new comes down and proxy sync stops for it there." Nothing on the computer is deleted by unticking.

The editor or an admin can untick from the dashboard. The app on the editor's computer can also untick a project for that computer, so it can take a project off the computer before removing its copy (see Sync: Deletions and removing a project). When no single computer is chosen, the project is removed from every computer of the person, and from any tick held for a computer not yet heard from; the person is asked first, with every computer named.

When a computer asks to untick a project that is not ticked under its own name but is still ticked on another of the person's computers, nothing is removed and it is told: "There is no tick for <project> under this computer's name (<computer>), but it is still ticked for another of your computers. Nothing was removed. If this computer was renamed, wait until the dashboard shows the new name, or untick it on the dashboard." A project ticked nowhere is simply fine. An untick is recorded in the history, naming the computer when a computer did it, and takes effect at once.

- Who: an editor for their own computers, an admin for anyone's, the app on the editor's computer for that computer.
- Ways in: the Projects page (each project's row and each project's own page), the admin's plan grid, the app on the editor's computer.

### Choosing whose plan and which computer a tick changes

Wherever ticks are shown, the page says whose plan and which computer a tick changes.

- An admin who has other editors can pick "<me> (me)" or any other known editor; picking one clears the computer choice.
- When the chosen person has more than one computer, a computer choice offers "every computer" or each computer ("A sync plan belongs to a computer, not a person. Every computer ticks or unticks all of them at once."). With exactly one computer it simply says "computer: <name>".
- A tick for a whole person ("every computer") leaves out their computers wired to the server on its own; a person whose every computer is wired gets nothing ticked.
- When acting for someone else, a warning reads "acting as <name>: a tick here starts a real sync on their computer".

The choice works in every browser, with or without scripts.

- Who: anyone signed in chooses among their own computers; only an admin chooses another person.

### A tick box always does what it showed

Each project in a list has a tick box whenever there is a person to tick for.

- A box drawn unticked only ever ticks, and a box drawn ticked only ever unticks, so a list that is out of date can never do the opposite of what the person saw. Every tick and untick carries what the person intends.
- Cancelling a question restores exactly what the screen showed.
- A box that fails to save says so and goes back to what it was; a change never looks saved when it was not.
- With one computer chosen, the box explains: "Tick to sync <project> to <computer> only. Untick to stop it there." With none chosen: "Tick to sync <project> to every computer <person> uses. Per-computer plans: pick a computer above."
- Unticking for a whole person asks: "This removes <project> from <person>'s N computer(s) (<names>). Their copies stay on disk; nothing new comes down and proxy sync stops for it." For one computer: "This removes <project> from <computer>. Its copies stay on disk; nothing new comes down and proxy sync stops for it there."
- A computer wired to the server (or a person whose computers are all wired) cannot be ticked: "<name> is wired to the server: it works directly off the NAS and syncs nothing. Change it in the app on that computer." A tick left on such a computer stays visible, can always be unticked, reads "syncs nothing: untick to clear this stale sync.", and is never reported as an error.
- Tags beside a project: "upload only" (leading to the glossary entry); "link" when a borrowed folder on the project needs attention; a number with a down arrow when N computers are still catching up.

Every action and question works for any project name a person can type, shows the name exactly, and never treats any of it as anything but text.

### Ticking warns when the proxies may not fit but never refuses

When the project's proxy size on the server and the computer's free space are both known, ticking asks first unless the proxies plus 20 GB fit and the proxies are under half the free space: "<project> is <size> of proxies. <computer> has <free> free." plus "That is more than will fit." when they are larger than the free space, then "Sync it there anyway?". Cancel unticks it again. The tick is never refused. A project whose proxies were never measured shows "not measured", meaning a tick cannot warn about space; nothing is said when either figure is unknown, and a computer that never reported its disk is unknown, never empty. The same question is asked when switching an upload-only tick to full sync.

Ticking for a whole person checks each of their computers and shows up to three such sentences. Ticking a whole column of the plan grid gives one warning for the column's total ("<n> projects (<k> of them measured) are <size> of proxies..."). The same rule is used everywhere a tick is made.

### Full sync or upload only, and switching between them

A tick is full sync (originals go up, proxies and project files come down) or upload only ("For footage you already have on this computer: send every file to the server and download nothing but the project's empty folders (no proxies, no shared project files, no originals)."). An upload-only tick sends every file of the project up (system clutter and temporary files excepted), and the only thing that comes down is the project's folder structure, empty, so the editor sees where originals go. What upload only does is in Sync: Upload only, "An upload-only tick sends every file up and brings down only the empty folders".

- "Upload only for me/<name>" ticks a project upload only.
- "Switch to upload only" on a ticked project asks: "This sets <project> to upload only on every one of <list>: nothing more comes down on any of them, and a computer that has a full sync of it now stops downloading. Their copies stay on disk. Switch to upload only?"
- "Switch to full sync" ("Download this project's proxies and shared files as well: the normal sync.") asks: "This syncs <project> in full on every one of <name>'s N computers (<list>), including any that do not have it ticked yet: its proxies and shared files come down on each. [space warning] Switch to full sync?"

When the switch is for one computer, only that computer is named and changed.

- Who: an editor for their own computers, an admin for anyone's.

### A project's page shows who syncs it and offers its ticks

On a project's page, "selected by" lists every editor who has it ticked on at least one computer, with "upload only" or "upload only on one computer" tags; or "nobody, so it is not syncing to any editor". The project's state reads "needs attention", "catching up", "in sync" or "not synced anywhere".

For the viewer (or the person an admin is acting for, with "acting as <name>: these keys change their sync plan, not yours."):

- "Tick for me" / "Tick for <name>", or "Tick for all of my/<name>'s computers (N)" when they have several, asking first with every computer named, and asking the space question when the proxies may not fit;
- "Untick for me/<name>" when ticked, asking with every computer named;
- the upload-only and full-sync switches above;
- when not ticked and the person has several computers: "or one computer at a time:" with one button per computer.

### Each person's sync queue shows their ticked projects in order

For one person, or one of their computers, the sync queue shows each ticked project in the order it is worked through: its name, position, full or upload only, whether the project has gone from the server, whether the computer is working on it right now, how complete it is, the files and bytes still needed, the speed and time left, a status (green when nothing is known), and the borrowed folders it brings in. It also names every computer of the person (listed in the question when unticking for the whole person), the Resolve project open now, the project it was matched to, and whether that pairing was made by the editor, an admin, or worked out by the product.

With a computer chosen, that computer's facts are used; otherwise those of the person's most recently heard-from computer. Projects are ticked and unticked on the Projects page.

With one computer chosen, any project in its queue can be moved to the front, or the whole order set by hand; the new order is that computer's alone, reaches it within about a minute, and does not redo projects already handled this round (see Sync: What syncs where, "Projects ticked on a computer sync one at a time, in the order set for that computer"). The same is offered for each computer on the per-computer view.

- Who: the person themself, or an admin for anyone; the order is changed by the editor for their own computers, or by an admin for anyone's.
- Ways in: the per-computer view, and a person's own page.
- Name and search words: Sync queue. Search words: queue, my projects, order, waiting projects, progress.
- When the help for the editing program is off: the open Resolve project and its pairing are not shown.

### An admin sets what each computer syncs in one grid

The plan grid shows projects against one person's computers.

- The admin chooses a person, then one of their computers or "every computer" (offered only when they have more than one), then "show". Nothing is listed until both are chosen ("Choose a person above, then one of their computers, then show. Nothing is listed until then: a company with many editors has a grid too wide to read, and a plan belongs to one computer anyway."). When the site has only one editor, or the person has one computer, it is chosen already. The computer choice is unavailable until a person is chosen. The choice is in the page's address, so a link lands on it.
- The head reads "N person/people · N computer(s) · N project(s)". It explains that a plan belongs to a computer, that "every computer" shows them side by side, that every box is the same change as ticking anywhere else ("there is one list, not two"), and that the small "up" box makes a tick upload only.
- Each person in the choice shows their worst status across their computers (green, amber or red; empty if never heard from), and which people have only wired computers.
- One column per computer: its name with whether the person is present, the person, "<size> free" on its sync drive, and either "wired: set on that computer" or the column actions "all", "none" and "copy from..." (see "An admin ticks or unticks a whole column at once").
- One row per active project: its name and its proxies' size on the server ("not measured" meaning a tick cannot warn about space). Each cell has a tick ("sync "<project>" to <computer>") and an "up" box.
- A filter box hides projects whose name does not contain the typed text ("Filtering unticks nothing").
- Legend: ticked "synced: the project comes down and goes up"; up "upload only: every file goes up, only the empty folders come down"; empty "not on this computer".
- On a wired computer an unticked cell cannot be ticked, and a ticked one can only be unticked ("syncs nothing: untick to clear this stale sync.").
- A cell for a person whose computer has never been heard from applies to the person as a whole (every computer, or the plan held for their first computer).
- The "up" box ticks the project upload only (ticking it if needed); turning it off returns it to a full tick; it never unticks.
- While saving, the box is unavailable and pulses briefly. A failure puts the box back and shows a note that stays until clicked ("click to dismiss"): "could not tick <project> on <computer>: <reason>" or "could not set upload-only for ..."; a success shows a short note for 4 seconds. If the admin's sign-in has ended, the browser goes to sign-in and comes back to the grid afterwards, and any column action in progress stops.
- Empty states: "No known editors yet: one appears here once they sign in, tick a project of their own, or their app reports."; "This person has no computer to show a plan for yet." (the computer choice reads "no computer yet"); "No active projects yet."
- Beside the grid: the archived projects (with a warning when that list could not be read right now, never claiming none is archived), how many people tick each project, and the number of computers in the whole studio.

- Who: an admin.
- Name and search words: Sync plans. Search words: sync plans, plan grid, what syncs where, assign projects, ticks per computer.

### An admin ticks or unticks a whole column at once

In the plan grid, each computer's column offers:

- "all" ticks (full) every project that is not ticked, one after another, asking first if the proxies would not fit;
- "none" unticks every ticked project, first asking "Untick all <n> projects for <person[ on computer]>? Their copies stay on disk. Nothing new comes down and proxy sync stops for all of them.";
- "copy from..." gives this computer the same projects as another of the person's computers ("Give this computer the same projects as another of <person>'s. Asks first, and names anything it would stop syncing."). Copying an empty plan is refused.

While "all" or "none" runs, the button shows "done/total"; pressing it again stops after the change in flight ("click to stop after the change that is in flight"). At the end: "ticked all for ...", "unticked all for ...", "stopped after i of n for ...", or a note that stays until dismissed: "[stopped after i of n. ]<f> of <n> change(s) failed: <first six names>[, and <k> more]". Every change it makes is recorded in the history and can be undone like any other (see "Recent tick changes can be undone within an hour").

- Who: an admin.

### Recent tick changes can be undone within an hour

Admins see every tick and untick of the last hour, newest first, re-read every minute. Each change shows when, who (display name), "ticked" or "unticked", the project, the editor, and where ("every computer (N)" for a whole person, otherwise the computer, or "unassigned" for a tick held for a first computer), marked when it has since been undone, and "Undo" or "put back".

Undo restores exactly what was there before (the same computers, the same modes, including a computer that held the project only because the tick covered every computer of the person), removing anything the change added. When that would take the project off computers it first asks "This removes <project> from <editor>'s N computer(s) (<names>). Their copies stay on disk; nothing new comes down and proxy sync stops for it." The undo is itself recorded and takes effect at once.

Results: "put <project> back for <editor>" or "removed <project> again for <editor>". Refusals: "that is not a plan change this page can undo"; "that record does not name a project and an editor, so it cannot be undone"; and after an hour "that change is more than an hour old, so it cannot be undone here. Tick or untick it yourself if that is what you want." Empty: "No tick or untick in the last hour. Older changes are in the history."

- Who: an admin.
- Name and search words: Recent plan changes. Search words: undo tick, recent changes, put back, who unticked, plan changes.

### Ticks reach the computers within about a minute and every project is handled on its own

A tick or untick reaches the computer within about a minute. A project's page lists any change in who receives it that has not yet been carried out, "Sharing change held: <note> (<ago>)". When one project's change cannot be carried out, every other project's change still goes ahead, and the health line says "applied A of B folder(s)" with the first error.

#### Lessons

- Met: DSH-033, DSH-034, DSH-035, DSH-036, DSH-037, DSH-038, DSH-040, DSH-041.

## Projects

### The Projects page lists every project and its health

The Projects page lists every active project. Projects are nested by folder: a project named with slashes ("2026/CCT/Website Highlights") appears in a tree of year and show folders, each project shown by its last part, each folder with its project count. Folders start folded, except the branch holding the project the person came back from, which opens by itself; the folds survive refreshes.

For each project the list shows its name and folder, a health status, how much is still needed in total, how many editors are below 100%, and a tick box (see "A tick box always does what it showed"). A project whose folder was moved or lost on the server shows as stopped, with the reason. It shows how many of the folders it borrows from other projects are working and how many are not (broken, missing, or the lending project not active). The whole studio gets one status, the worst of its projects, and whether the server's own syncing can be reached.

A count line reads "N of M ticked for <computer or person>". The list re-reads every 30 seconds while in view, and straight after any tick or untick on the page. Each project name leads to its own page. Empty: "No projects yet: they appear after the server's first look at the tree."

- Who: anyone signed in.
- Ways in: the Sync menu.
- Name and search words: Projects. Search words: projects, project list, episodes, tick projects, all projects.

### Finding a project by typing

A find box above the list ("find a project", with "/" as its key) filters projects by name as the person types, ignoring letter case and treating accented letters written either way as the same. Nothing is filtered while an input method (Zhuyin, Pinyin and the like) is still composing; the filter applies when composition ends. Folders with no match are hidden; folders with a match open while filtering, and close again when the box is cleared (only those it opened). "No project matches." is shown when nothing does. The filter and the typed text survive the list refreshing.

### A project's page shows where it lives and what is wrong with it

Any signed-in person can open a project's page; an unknown project says "unknown project '<name>'". It shows the project's name, its path on the server, the name its shared folder is known by, a way back to the Projects page, whether it is active, what media the server holds for it, the folders it borrows from other projects (with each one's status) and the projects that borrow from it (working links only). Its details re-read every 10 seconds and after any tick.

Warnings:

- "folder removed": "This project's folder cannot be found on the server.";
- "sync folder <state>" when syncing of the project on the server is in error or stopped: "The completion figures below are out of date until this is fixed.";
- "server count not updated" when the server cannot count the project's files: "The server figures below are the last good ones, from before this started. checked <ago>";
- "Sharing change held: <note> (<ago>)" for each change in who receives the project that the server is holding back.

Admins can act for another person here as on the Overview.

- Who: anyone signed in.
- Name and search words: Project page. Search words: project page, project details, who syncs, project status, missing files.

### A project's page lists every computer that shares it and what each is missing

The project's page reads "N computer(s) share it" and, for each:

- a state light; the person, with "wired" (works off the server, reports only) and online or offline;
- percent synced: the bytes held of everything this computer should have, proxies and the project's other files, against what the server has, to one decimal; camera originals that live only on the server are left out. Before a computer has said what files it holds, its plain completion is shown instead;
- "N / M files" held; missing "N files, <size>"; originals and proxies held against the server's counts;
- each kind of movement for this computer: its state with a coloured chip and the chip's reason in words, how long it has been in that state, how many files are waiting, its last error, its last good sync, the bytes done of total, the speed and the time left (only while something is actually moving), or "no reports" if none;
- the app's version, the project it is working on, last seen, and a sentence saying why its light is not green when the computer has gone quiet.

Computers wired to the server show "-" for synced, held and missing. Computers that hold media for the project but do not sync it (for example a computer wired to the server) appear as "report only" rows with their media counts and a status.

"Missing files" opens a list under the row that survives refreshes: "missing on <name>, refreshed <ago>", each file and size, "and N more (the list stops at M)" when cut, or "Nothing listed yet.". These lists are refreshed every minute for computers that are behind. A person cannot open the list for a computer of someone they may not see.

None: "No editor computer shares this folder yet. Approve the computer on the people and computers page: sharing follows by itself within a minute."

### A project's page shows which originals, proxies and Resolve clips each computer holds

Re-read every 5 seconds; an editor sees their own computers, an admin every person's. The head reads "the server has N originals and N proxy files", or, before the server has counted the project, "counting", "the server is counting this project's files. A new project is counted within a minute or two." (never shown as zero).

For each person and computer (folded): its state, person, computer, wired or not, "proxy only", "originals N/M, proxies N/M" (or "holds N originals and N proxies, server count pending"), whether its list was cut short, and "N offline in Resolve". A computer that has sent its bins but not yet what it holds on disk still appears, with zero counts.

Inside, each Resolve bin ("(root)" for the top): "N/M present" and each clip as uploading (while its file is being uploaded), online or offline, with "proxy" for proxy clips; "(clip list shortened)" when cut. "No Resolve bin data. Open this project in Resolve on that computer to fill it in." Nothing reported: "No computer has reported what it holds for this project yet."

Whether a computer holds the media it should:

- a computer wired to the server: red if the server has originals and the computer can see fewer of them; otherwise green;
- an editor's computer: green if the server has no proxies or the computer has all of them; amber if it has none or only some. Holding proxies and no originals is normal for an editor.

- Who: anyone signed in; an editor sees their own computers.
- When the help for the editing program is off: no bins, clips or "offline in Resolve" figures are shown.

### Borrowed folders count in a project's figures

A project's media figures include the files in the folders it borrows from other projects, labelled as borrowed. What a borrowed folder is, and how it syncs, is in Sync: What syncs where.

### The server counts what each project holds on the NAS

For each active project the server knows every video file: its path in the project, whether it is an original or a proxy (a file inside any folder named Proxy, in any letter case, is a proxy; every other video is an original), its type, size and modified time. For each project: the folder count, original and proxy counts and sizes, when it was counted, and the last error.

- A file that reached the server shows as on the server within five minutes, however many projects the studio has.
- A newly found project is counted first, within a minute or two. A project never counted shows "not counted yet", never "0 originals", and its proxy size is unknown, never zero, when warning about a tick.
- A count that fails is recorded with its time, and the project is counted again next time, so a passing fault does not stick. When the server is refused while listing a project's files, admins see a serious problem, one per project: "The figures on that project's page are the last good ones", with a fix that, if the project folder was moved or renamed, says to move it back (the app's put-back button), or, to rename or move the project for everyone, rename or move its folder on the server, which every computer follows (see Proxies and file moves: Moves made by hand on the NAS, "A project folder moved or renamed by hand on the NAS is followed"). This is only checked while the projects folder itself is healthy.
- A count that would drop more than 90% of a project's files at once is not taken: the last good figures stay, and admins see "A project's file count collapsed, so the last good one is kept" until a count comes in that agrees.
- Files the sync deliberately never sends are never counted as owed, waiting or behind.

This count is what shows each project's proxy size before a tick, what moves on the NAS are recognised from (see Proxies and file moves: Moves made by hand on the NAS), and what the app on an editor's computer is told when it asks where a file went.

### Anyone signed in can create a project

A person names the project (1 to 128 characters) and the folder it goes in (by default the top of the projects tree), and may pair a Resolve project with it. The project's folder and the site's standard subfolders (see "New projects get a standard set of folders") are made, the project is active straight away, appears for every editor and can be ticked; nobody has to grant anyone access. The Resolve pairing, if given, is made (the first pairing wins). Asking twice is harmless. The creation is recorded in the history with who made it.

Refusals, each saying why:

- the server's projects folder cannot be reached;
- "parent folder does not exist";
- "project name is required";
- a name with slashes, starting with ".", containing "..", or containing control characters;
- "cannot create a project inside another project (<path>)";
- "that folder already contains a project (<path> [(+N more)]). Pick that one instead";
- "that name produces an empty identifier. Use letters or numbers";
- an archived project already there: "<path> is an archived project. An admin can put it back with "Unarchive" in the list of archived projects, and it keeps its folder, its files and its ticks";
- "that folder is already a project with a different identity";
- "a different project already uses this identifier: <name>. Pick another name";
- an existing ordinary folder of that name: "Projects/<path> already exists. Use "Use this folder" to point the project at it instead of creating another folder inside it";
- "could not create the folders on the NAS. Ask an admin to check the server" (the details, which name places on the server, are kept from the person);
- a Resolve project none of the person's computers has reported (checked before anything is made).

The new folder is open only to that project's members, and the creator is given access at once (see Accounts, privacy and the legal paperwork: What each person may see and reach, "Each project is reachable only by its members").

- Who: anyone signed in.
- Ways in: the Projects page, and the page an editor reaches from Resolve (see "A new Resolve project with no folder leads the editor to pick or create one").
- When the help for the editing program is off: no Resolve project can be paired.

### Turning an existing folder into a project

"Use this folder" makes an existing folder on the server a project, changing nothing inside it and adding no subfolders. A folder that already belongs to a project keeps that project, so a project moved on the NAS is picked up again at its new place. Using a folder is recorded in the history with who did it.

Refusals: the server's projects folder cannot be reached; a bad name; "pick a folder: the Projects root itself cannot be a project"; "folder does not exist"; "this folder is inside an existing project (<path>)"; the folder contains a project (naming it); "that folder name produces an empty identifier"; an archived project there; "a different project already uses this identifier: <name>"; "could not mark the folder as a project: <error>"; "this folder claims to be <project>, which still exists. Resolve the duplicate on the NAS first" (a project copied rather than moved); a Resolve project the person's computers have not reported.

- Who: anyone signed in.

### A new Resolve project with no folder leads the editor to pick or create one

When the app on an editor's computer notices a new Resolve project with no project folder, it opens a page for that Resolve project. Without a project name the page goes to the Overview.

- Already set up (names compared ignoring letter case): the folder its files go into, who set it, and "Mappings are fixed once set. As an admin you can change it on the project's page." (for an admin) or "Ask your admin if this looks wrong." (for an editor). Once set, only an admin changes it, and nothing automatic ever rewrites it.
- The server cannot see the projects tree: it says so, and that whoever installed the server must fix it, as this page cannot.
- Pick: "Browse the server's Projects tree. If the project's folder is already there, pick it with Use this folder. Nothing inside it is changed. Only create a new folder when there is not one yet; new folders get the standard subfolders (<the site's standard folders>)." The page is a real browser of the server's tree: a path from Projects; "You are in Projects/<folder>" with "Use this folder" when allowed, otherwise "Open a year, then a show, to find the folder." or "You are inside a project: go up a level to pick a folder." Folders are listed in name order, hidden ones skipped, marked "same name" when the name matches the Resolve project exactly and "project" when already a project (these do not open, as projects cannot nest), each with "Use this folder" or "Link this project"; "empty folder" when empty. One folder that cannot be read does not hide the others ("not shown", "could not list the folder: ..."). When the tree cannot be read at all, the page says it cannot tell, never that there are no folders.
- Create: "or create a new project folder here": "Only for a folder that does not exist yet. A name that is already listed above would nest a second folder inside it, so pick it with Use this folder instead.", a name and "Create & link". "Anyone signed in can create a project, and it appears for everyone: in the tick lists, the plan grid and the queue. Who made it is recorded in the history. Only an admin can take one back off those lists, by archiving it, and even that keeps the folder and the files."
- Done: "ok", "Projects/<folder> is set up on the server[ and "<name>" now files into it].", "Syncing for it is set up automatically within about 5 minutes. You can close this page."
- Not done: the error, and when the typed name already exists, "Use Projects/<folder>" to link that folder instead; "pick a folder to link"; a Resolve project already paired can only be pointed elsewhere by an admin ("this Resolve project is already mapped: ask an admin to change it").

A Resolve project is paired with a project on its own only when its name matches exactly one project, by the rule in Resolve on the editor's computer: Knowing which project is open, "A Resolve project is tied to a project in the tree"; any partial match is put to a person, and no guess is ever kept unconfirmed.

- Who: anyone signed in; changing a pairing once set is for an admin.
- On its own: pairs a Resolve project with a project when its name matches exactly one project by that rule.
- By hand: the editor picks or creates the folder on this page; an admin changes a pairing on the project's page, and an automatic pass never changes a pairing that has been set.
- When the help for the editing program is off: this page does not exist; projects are made from the Projects page.
- Name and search words: Set up a Resolve project. Search words: new Resolve project, link folder, pick folder, project folder, set up project.

### New projects get a standard set of folders

A new project gets these folders: AE, Audio/Music, Audio/Voiceover, B-roll, Interviewees, Render in Place, Subs, Youtube. A site can give its own list. Whatever the list, any part of a name that would lead out of the project folder (such as "..", or a leading slash) is stripped before any folder is made.

- Setting: New project folders. Does: the subfolders made inside every new project. Default: AE, Audio/Music, Audio/Voiceover, B-roll, Interviewees, Render in Place, Subs, Youtube (a blank list means the default). Who: an admin. Applies to: the site. Search words: project template, subfolders, new project folders, folder structure.

### An admin archives a project and brings it back

Archiving takes a project off every list, the plan grid and every queue, and computers stop syncing it. Nothing is deleted: the folder, its files and every tick on it stay. "archive" asks "Archive <project>? N editor(s) sync it now, and it stops being sent to their computers. Nothing is deleted: the folder and the files stay on the server, and UNARCHIVE puts it back.", naming who has it ticked.

The archived projects are listed, newest archived first ("Off every tick list and the queue. Nothing was deleted: the folders and the files are still on the server."): project, "archived <ago> by <who>, still ticked for N editor(s)", and "unarchive" ("The ticks it had are still there, so it starts syncing again on the next cycle."). Unarchiving makes the project active at once. An archive survives every later look at the NAS: the project stays archived however often its folder is seen. Creating or using a folder under an archived project's name is refused until it is unarchived.

The project's members lose access to its folder while it is archived and get it back when it is unarchived. Both acts are recorded in the history with who ticks the project. Refusals: "no project called '<name>'"; "'<name>' is already archived"; "'<name>' is not archived". If the list cannot be read: "The archived list could not be read right now, so it is not shown. Nothing was archived or restored by this, and the projects above are unaffected."

- Who: an admin.
- Ways in: the project's page, the plan grid.
- Name and search words: Archived projects. Search words: archive, unarchive, archived projects, hide project, restore project.

### A project whose folder disappears leaves the lists and comes back when it reappears

A project whose folder is no longer found on the NAS becomes inactive and leaves every list, queue and backlog. When its folder is found again, it is active again, with its place and name brought up to date, unless it was archived.

### Projects never vanish all at once because the NAS looked empty

If one look at the NAS would take out more than a quarter of the active projects (or more than 2, whichever is larger), nothing is taken out at all. Admins see a banner with the time, the counts, the limit and up to 100 of the projects concerned: when the NAS showed no project folders at all, it says it showed 0 of N folders and nothing is being taken out; otherwise that it showed X of N folders and K project(s) are not being taken out. "The project list is being kept exactly as it was." The banner stays until a later look comes in under the limit, and a serious problem is raised ("too many projects would have been marked gone at once").

From the banner, an admin can choose to take those projects out anyway, after a question naming how many.

- Who: an admin sees the banner and the choice.

### Proxies left without their original are reported once per folder

When proxies on the server have no original beside them, one warning is raised per proxy folder, naming the first few clips and counting the rest.

#### Lessons

- Met: DSH-042, DSH-043, DSH-044, DSH-045, DSH-046, DSH-047, DSH-048, DSH-049, DSH-051, DSH-052, DSH-053, DSH-054, DSH-055, DSH-056, DSH-057, DSH-058, DSH-059, DSH-060.

## Transfers and the queue

### The Transfers page shows what is moving now, file by file

The Transfers page is a page of its own. Its first list shows every file moving right now, in either direction, re-read every 2 seconds while in view. A transfer shows within seconds of starting, its progress updates within seconds, and a transfer its computer has not updated for 2 minutes drops out of the list.

Each moving file shows an up or down arrow (up: from the computer to the server; down: from the server to the computer), its name, the project, for an admin the person and computer, a meter and percent, bytes done of total, the speed per second and the time left. When the server is receiving files for a project that no computer has listed, a row reads "<project>: N file(s) arriving at the server", with no editor named. Rows are sorted fastest first. The head reads "N moving · <total speed>/s total". Empty: "Nothing is moving right now."

An editor sees their own files on every computer they use; an admin sees every editor's. File names wrap anywhere and can be read whole by pointing or tapping; progress, speed and time left stay in view on a phone (390 pixels wide) and on desk screens (1100 and 1600 pixels wide).

- Who: anyone signed in.
- Ways in: the Sync menu; the Overview's "moving" readout leads here.
- Name and search words: Transfers. Search words: transfers, moving now, uploads, downloads, progress, speed.

### What is waiting is listed per person, computer, project and direction

Below what is moving, the Transfers page lists what is still waiting: only files of ticked projects, waiting behind the transfers above. Unticking a project takes it out of every queue and every "behind" mark at once.

The head reads "N file(s) · <size> waiting", or "not counted yet". The lead reads "N file(s) waiting behind the transfers above, from what the computers last said they hold. May lag a few minutes.", "Nothing counted yet, but the rows below are not finished: see each one.", or "Everything that should be somewhere is there."

There is one fold-out per person, computer, project and kind of movement:

- "getting ready" ("the project was just ticked, and the computer and server are setting it up. Nothing needs doing."), with "Just ticked as upload only. Waiting for this computer's first list of files, then its files start uploading (only the empty folders come down)." or "Just ticked. Syncing starts within a minute or two.";
- "cannot tell" ("The dashboard cannot tell whether this computer still owes uploads."), with the reason and "Leave it running and check the app on it.";
- otherwise: the direction, "N file(s) · <size>", and whether it is an upload, a proxy download or project files, each explained;
- "on hold" with the computer's own reason and "(since <ago>)" (see "Files waiting are on hold only for the computer's own reason");
- inside each: every file and its size, "... and N more" when the list is cut, or "no file names reported".

Folds, open rows and scroll positions survive the 2-second refresh. For an editor, the only settings links on this page are to transfers and help.

- Who: anyone signed in; an editor sees their own computers.

### Files waiting are on hold only for the computer's own reason

A file waiting in the queue is shown on hold, with the reason and since when, only when its computer said that something holds that kind of transfer:

| Reason the computer gave | What it holds |
|---|---|
| not signed in, licence not accepted, sync drive missing or not answering or not the right drive, studio-wide stop, stopped on this computer, paused, offline | every kind of transfer |
| a wrong clock, a full drive | proxy downloads only |
| downloads that stopped themselves as a safety measure | every download; uploads keep going |
| project files not syncing | project files only |

A stuck transfer never marks a hold. A backlog its computer says it cannot move never looks as if it were draining.

### Every finished file lands in the history and is kept 7 days

Every file copied up or down, by any computer, is recorded when it finishes, with the person, the computer, the direction, the project and file name, and when it finished (the computer's time, or the server's when the computer did not say). Files moved into the recovery folder on a computer are recorded as removals. Each file that finishes arriving at the server is recorded as an upload once, credited to the computer that sent it when that is known, otherwise to nobody.

The Transfers page lists them under "Recently completed files: what the apps report, plus files arriving at the server.", newest first, 50 at first: for an admin the person, then the direction, the file and how long ago. Empty: "Nothing completed recently." Entries are kept for 7 days.

- Who: anyone signed in; an editor sees their own.

#### Lessons

- Met: DSH-061, DSH-062, DSH-063, DSH-064.

## People and computers

### An admin sees every person and computer in one place

The people and computers page shows an admin:

- how people sign in on this site (see Accounts, privacy and the legal paperwork: Who may sign in);
- every person: "N accounts", or "No editor accounts yet.". Each shows the sign-in name, "shown as" (their display name), role, status (active or suspended), their computers, and the actions: set a password, suspend or resume, end their sign-ins, download their data, erase their history, and remove. Where the studio's NAS holds people's logins, it also shows whether the person's account may open the shared folders, and whether the NAS has it locked. When the account list cannot be read: "The account list is unavailable: <error>", with whatever did answer. The list refreshes by itself every 30 seconds, and every action answers with a notice or an error line. What each action does is in Accounts, privacy and the legal paperwork: Who may sign in, "An admin manages the studio's people from one list";
- every known computer with its owner, name, operating system, app version, when last heard from, wired or syncing, its identity (on pointing) and how many projects are ticked on it, with "remove" ("Every computer that has reported in. Remove forgets it: its sync plan, its status and its membership of the studio."); empty: "No computer has reported in yet.";
- suspended people, with each suspension's details;
- computers waiting to be approved, each with a suggested owner and name when that computer has already said who it is (see "A new computer is approved under its owner");
- people the studio knows by a computer, a plan or a report who have no account ("Known to the fleet (a device, a plan or a report), but no account here."), with remove, download data and erase history.

Only real people appear in any list of people; the product's own accounts never do. When one part of this page cannot be read right now, it says so for that part only and shows the rest.

- Who: an admin. Anyone else is told "admins only".
- Name and search words: People and computers. Search words: people, users, editors, computers, accounts, approve.

### A new computer is approved under its owner

A computer not yet tied to a person waits for an admin to approve it. Approving means choosing its existing owner, filled in from what the computer said; one person may own many computers, so a second computer takes the same owner as the first. Approving it under a name the dashboard does not know is refused unless the admin ticks CREATE NEW EDITOR: "'<name>' is not an editor this dashboard knows. Pick the OWNER of this computer: one editor can own several computers, so a second computer takes the same username as the first. Tick CREATE NEW EDITOR if this really is a new person." A computer waiting more than 24 hours is raised as a problem (see "The kinds of problem the server finds and where each leads"). Once approved, sharing follows by itself within a minute.

- Who: an admin.
- On its own: suggests the owner and name from what the computer said.
- By hand: the admin chooses the owner, or a new person by explicit choice.

### People are shown by the name they chose

On every signed-in page a person appears under their chosen display name if they have one, otherwise their sign-in name. A display name is only a label: it never takes the place of the sign-in name in any record.

- Setting: Display name. Does: the name others see for this person on every page. Default: blank (the sign-in name shows). Who: the person themself. Applies to: a person. Search words: display name, my name, rename me, shown name.

### A person's page shows each of their computers

A person's own page lists their computers, those that sync to their own drive and those wired to the server, each refreshed every 30 seconds and after its own buttons. Each shows:

- its name with "not heard from", "online" or "not reporting";
- its role: wired ("works off the server share; syncs nothing", with the share it maps as its drive) or syncing ("syncs projects to its own drive");
- the app version with "up to date" or "out of date: <current>" (admins get "Update now"; an editor reads "update it from the app on that computer. Your admin can also push it.");
- its system, its licence acceptance, "not reported" tags for kinds of information it withholds, its last report, and its current one-sentence state;
- for a syncing computer: "projects on this computer N ticked", each with "full" or "upload only", or "Nothing is ticked for this computer.", with a link to the Projects page, where projects are ticked and unticked;
- for each project ticked there: what has synced, what has not, and what is missing;
- a link to the computer's details;
- the foot: "Remote or wired, pause, stop all syncing, YouTube sign-in: in the app on <computer>.".

No syncing computers: "No computers that sync have reported in as <name>. Install CC Sync on a computer and sign in to it as <name>: it appears here after its first report." with "Get the installer". No wired computers: "No computers wired to the server. A computer becomes one in the app on it, followed by a restart of the app."

An admin can open any person's page and sees the same, for that person.

- Who: the person themself, or an admin for anyone.
- Name and search words: My account. Search words: my account, my computers, person, profile, my settings.
- When YouTube downloads are off: no YouTube sign-in is mentioned.

### A person sees every setting that concerns them and where it is changed

A person's page lists each computer's settings as that computer last told them: name, value (or "not reported") and where it is changed. A table lists every setting that concerns the person, in four kinds:

- kept by the dashboard: display name; what each computer syncs ("N projects, N upload only"); password; signed-in browsers;
- each computer's own, changed from the dashboard: whether it takes shared work, and which kinds of work it takes;
- each computer's own, changed at that computer: remote or wired; how long it lends itself to shared work; lend it now; the YouTube terms and sign-in (only when YouTube downloads are on for the site); updating the app; signing the computer in or out;
- set for everyone: the drive letter; automatic updates; YouTube downloads; the studio-wide stop.

Admins get links to each; editors read "your admin".

### A computer silent for a week is listed as lost

A computer not heard from for 7 days is listed as lost, together with the projects still ticked for it. It keeps its sync plan and is still sent the projects in it. A computer that holds ticks is never forgotten on its own: only an admin forgets it.

The "lost computers" fold-out (open by default) reads "Each one still holds its sync plan, and is still shared the projects in it." Each shows its state, person, computer, platform, what it still has planned ("N project(s): names" or "nothing"), its last report, and "Forget". With no computers at all: "No computer has reported yet. Each app is given this dashboard's address when it is installed: if one is running and is not here, ask that editor to send you its diagnostics." Beside it, a "projects" fold-out lists each project with its state: "N editor(s), N behind, <size> queued" or "all synced".

- Who: an admin.
- Name and search words: Lost computers. Search words: lost computers, silent, missing computer, not reporting, gone quiet.

### A computer silent for two weeks is offered for forgetting

A computer not heard from for over 14 days is reported to admins once more, and then stands as one warning, for up to 20 such computers: "<computer> has not reported for over 14 days, so this server has stopped asking about it. Nothing is syncing to or from that computer, and anything ticked for it is sitting unapplied." The fix: press "Forget" on its row, or nothing if it is coming back. It clears when the computer reports again or is forgotten.

### An admin forgets a computer

Forgetting a computer removes it from the studio: it stops being sent projects, and everything the server holds about it now goes (its sync plan, its status, what it holds, its Resolve bins, requests waiting for it, its diagnostics, its settings requests and the rest). The history of its syncing and its finished transfers is kept. A person's ticks that apply to all of their computers are not touched. Files already on the computer stay there.

Forgetting is all or nothing: if the server cannot stop sending that computer its projects right now, nothing is removed, and the admin is told so and to try again once it can. The admin is told how much was removed. An unknown computer is refused by name. Forgetting is recorded in the history.

It asks first: "Forget the computer <m> (<editor>)? Its sync plan, its status and its membership of the studio go, so it stops being sent projects. Files already on it stay there. If its app is still installed and signed in, it will register itself again on its next report." Forgetting is not taking access away: the person keeps their account and their sign-in, and an app still running and signed in on that computer registers it again the next time it reports. To keep it gone, uninstall the app there first, or delete the person (see Accounts, privacy and the legal paperwork: Suspending and removing a person, where deleting a person removes their accounts, computers, shares and sessions all together or not at all).

- Who: an admin.
- Ways in: wherever a computer's row is shown to an admin, with one "Forget" and the one question above.

### A renamed or cloned computer keeps what is its own

Each computer is known by its owner and its name, and also by a lasting identity of its own, so the server recognises it when it is renamed. A renamed computer keeps its plan, its history and the requests waiting for it; the rename counts once the earlier name has been silent for five minutes. A person's computers are listed oldest first. A person may have any number of computers, and a computer leaves the list only when an admin forgets it.

When two computers claim one identity (for example two computers set up from one copied disk), both stay visible and flagged, with how to reset the newer one, and neither gets the other's requests. A computer renamed onto another computer's name changes neither plan, and the admin is warned.

### Accounts no computer has reported for

An editor account at least 30 days old (or of unknown age) that no computer has ever reported for is shown to admins as information: send that editor the installer, or delete the account.

### An admin reads the history of who changed what

Every change to plans, people, computers, builds and settings is kept in a history of who did what and when, for 180 days. Nothing edits or removes a line, except removing lines past 180 days; deleting a person changes how their lines name them but does not remove the lines (see Accounts, privacy and the legal paperwork: What the product records about a person).

Recorded acts include: ticks, unticks, undos and plan copies; creating, using a folder as, archiving and unarchiving a project; the studio-wide stop and start; downloads resumed; asking a computer for diagnostics; a person deleted; a computer approved or forgotten; a build published, made current or withdrawn; an update pushed to a computer and its withdrawal or expiry; a file moved and sent again; a Resolve undo asked for; site settings saved; asking a computer to change its settings and that being withdrawn, applied, refused or expiring; dismissing a problem, and a problem closing itself; changes to how many removals are allowed, and approving removals that were held back.

The page shows the newest 200 lines: when (exact time on pointing), who (display name, sign-in name on pointing; "?" when unknown, never blank), the act, its subject and its details as recorded (damaged details shown as plain text). A filter ("filter by project, editor, computer, version or action") with "filter" and "clear" searches across subject, who and act. It does not refresh by itself. Empty: "Nothing in the history matches "<q>"." or "Nothing has been recorded yet. Every tick, stop, deletion and publish from here on lands in this list."

- Who: an admin.
- Name and search words: History. Search words: history, audit, who changed, timeline, log of changes.

#### Lessons

- Met: DSH-065, DSH-066, DSH-067, DSH-068, DSH-069, DSH-070, DSH-071, DSH-072, DSH-073.

## Reports from computers

### What an admin and an editor can see about a computer, and how fresh it is

Every running computer with someone signed in tells the server about itself within seconds of the app starting, then about every 30 seconds, and every few seconds while files are moving, so progress on the dashboard is live during transfers. Pressing "Sync now" in the app also brings the dashboard up to date at once. Signing in as a different person makes the next account of the computer complete.

What can be seen about a computer, by the admin and (for their own computers) by the editor:

- what each kind of movement is doing and on which project (a borrowed folder under the project borrowing it), and the order its projects are worked through;
- the project open in Resolve and its bins (each clip's bin, name, file, whether it is a proxy, an original or something else, and whether the file is on this computer);
- which files of each project are on this computer;
- wired or syncing; who is signed in;
- proxy coverage; YouTube clips downloaded but not yet in Resolve; shared work in progress, what work it can take, and how long nobody has used it;
- the safety stops in force; free space on the sync drive and the system drive; how far its clock is from the server's; whether the server is accepting it;
- update attempts and refusals; whether sending to Resolve from the browser works on it; the sync drive's state; Resolve's health;
- project folders that have disappeared since it last said, and folders in no plan; conflicting copies of project files held there; recent restarts of the app;
- its one sentence saying why it is not syncing (see Sync: Saying truthfully what the sync is doing).

A value nobody has measured yet is shown as unknown, never as zero. One part that cannot be measured never removes the others. Something a computer did not mention this time keeps its last value, shown with its age; a part it has stopped sending is cleared rather than left as if it were current; a part it never sent shows nothing.

- Who: an admin for every computer, an editor for their own.
- When the help for the editing program is off: nothing about Resolve is shown.

### What is said when a computer has not been heard from

| Silent for | What is said |
|---|---|
| under 15 minutes | nothing: the computer is green on freshness |
| 15 minutes | amber, "Not heard from since <date time> UTC" |
| 6 hours | red, the same words |
| 24 hours | a serious problem for admins (see "A computer quiet for a day or red for an hour is raised as a problem"), and requests to it say "this may sit for a while" |
| 7 days | listed as lost, with the projects still ticked for it |
| 14 days | reported once more, then one standing warning offering to forget it |

A computer with nothing ticked never climbs this ladder: it stays on its neutral line however long it is quiet. A computer that went quiet reads as asleep or not reporting, never as a sync fault, unless it was moving files when it went quiet.

### A computer is never cut off for what it says

What a computer says about itself is never refused whole. A part that is wrong, unknown to this server, or too long is trimmed or set aside and named, the rest is kept, requests waiting for the computer are still delivered, and the computer stays listed. Where a list is cut, the counts and sizes stay exact and the dashboard says the list was cut short.

### A computer that cannot sign in is still shown, and admins are told

A computer that is running but cannot prove who it belongs to, or whose person is suspended or removed, is still shown, as "Not syncing: this computer cannot sign in to the server: <reason>" or "being turned away", with the reason. Admins see a serious problem, "a computer is being turned away": "<who> IS running and IS trying to report, and this server is turning it away (<age>). ..." The fix: "Ask that editor to sign in again in the CC Sync app on that computer." A computer's own sign-in never expires on its own (see Accounts, privacy and the legal paperwork: How a computer proves who it belongs to).

### A computer withholds kinds of information by choice

A computer, or the whole site, can choose not to send some kinds of information about itself (for example the Resolve project open, what is on its disk, or how long the computer has been idle). Those kinds are never shown, never kept, and never present in the computer's diagnostics either. Wherever the dashboard would show them, a quiet tag reads "not reported by this computer: <label>", explained as a privacy choice, never a fault; a withheld open Resolve project shows this tag, never "could not check". A withheld kind never changes any colour, headline, note or alert. Issues, notes and problems that depend on a withheld kind (clips outside the tree, clips only on this computer, stray project folders, a moved project folder) are not raised for that computer, and one already open is closed without a message (see Accounts, privacy and the legal paperwork: What the product records about a person, "Withheld information reads as not reported, never as a fault"). The switches themselves are in Accounts, privacy and the legal paperwork: What the product records about a person.

### Diagnostics reach an admin on their own and when asked

A computer's diagnostics are a plain-text account of its own state: who it is, its sign-in state, its sync folder, problems in its set-up, what its sync is doing, its link to Resolve, and so on (see The app on each editor's computer: Telling the editor what is wrong). They reach the admin, with no action by the editor:

- on their own, when any kind of movement on the computer newly falls into an error (not again while it stays in error), at most once an hour for each kind;
- when an admin asks the computer why, once per ask, on its next report (see "An admin asks a computer why, from its details");
- when the editor sends them from the app.

A send that fails is tried again a few minutes later. Diagnostics longer than 256 KB are cut, never refused. Each one received is recorded in the history. They are kept for 30 days.

- Who: an admin reads them.

### An admin reads the diagnostics computers sent

The diagnostics page starts with "Press "Read the answer" on a computer's row to read what it sent." For one person or one computer it shows their last diagnostics; otherwise the newest from each computer, newest first. Each is a fold-out (the first one open): person, computer, why it was sent (a sync failure, so the computer sent its own; an admin asked; or the editor sent them), when it arrived and the computer's own time if different, and the full text. "Showing <name> only." with "every computer". None: "No computer has sent diagnostics yet. Press "Ask this computer why" in a computer's details, or have the editor send them from the app."

When the server has crash reports of its own: "This server has N saved crash report(s) of its own." with "download crash reports" (all of them in one download) and "then send them to <support contact>".

- Who: an admin.
- Name and search words: Diagnostics. Search words: diagnostics, ask why, computer report, crash reports, troubleshoot.

#### Lessons

- Met: DSH-074, DSH-075, DSH-077, DSH-078.

## Problems the server finds

### Everything the server knows is wrong is in one list

The server looks at itself and the studio and keeps one list of everything it finds wrong, shown to admins on the Overview in an area of fixed size that scrolls when full. Each problem is about one thing (a computer, a project, a folder, or "the server"), and shows:

- its severity: error, warning or information;
- what it is about, and the name of the check that found it;
- when it was last seen (first seen on pointing);
- the diagnosis: its real cause in plain words, or "cannot tell";
- the fix, with the support contact: always a button, a link to the place to act, or "ask whoever installed this server", never a command to type;
- a link to the place to act (its words depend on the problem, "Take me there" otherwise): a problem about a project goes to that project, one about a computer to that computer, otherwise to the place named for its kind;
- "dismiss".

The list is ranked: errors, then warnings, then information, then checks that could not be made. It gathers what the server's checks found, the alerts, the always-true facts that are broken, and the protection lines that are not all right (see The server: installing it and keeping it running: Health checks and alerts, and Snapshots, restoring and the server's disk). When one of these cannot be read, it becomes one row of its own, "Could not read <source>", the error, "This page could not ask this source, so nothing it would report is shown here. That is not checked, not OK.", so the list can never read all clear while a source is not answering. The open problems include an editor's computer whose installation failed.

Opening the list runs every check afresh. The list is refreshed every minute while in view. The head reads "checked against N things every M minutes" (every 10 minutes unless set otherwise) and "N open" with counts "N needs attention", "N worth a look", "N not checked", and "Support: <contact>". "Not checked is not OK. It means this server cannot answer that one, and the reason is beside it." With nothing open: "All clear. N of M checks ran and found nothing wrong.", plus a warning "N never ran" when some checks have never run.

Dismissing asks "Dismiss this? It is only hidden. If the server finds the same problem again it comes straight back, so dismissing it is not a fix." If the problem had already gone: "that notice is already gone. Reload the page." After a dismiss, every count and list that includes it updates. A problem found again keeps its first-seen time and opens again, even if it was dismissed or had closed. Looking never changes anything: the checks only read, and they never repair.

- Who: an admin.
- Name and search words: Problems. Search words: problems, health, what is wrong, issues, notices, alerts.

### Every page shows admins how many problems and alerts are open

On every page an admin sees "N problem(s)" (open problems of error severity: "the server has found problems it cannot fix by itself"), leading to the list, and "N alert(s)" (errors and warnings from the last alert check), which shows whether any is an error, leading to the same list. Each is absent at zero. The alert count is hidden on small screens. The same counts are in the server's public health answer.

### The server looks for problems about every ten minutes

About every ten minutes the server checks for every kind of problem it knows, whether or not a way to send alerts is set up. Sending alerts, the weekly report and the daily messages are in the second part of the dashboard's specification ("Alerts by mail"). A scheduled check past its usual time shows as overdue and is itself a problem; a newly installed server running on time is never flagged, but work that died at start is, within minutes.

### What the server checks, and whether each check ran

A fold-out "what the server checks" (N checks) lists every check with one of:

- "found": it found something, which is in the list;
- "ok": its latest run passed, recently;
- "not checked": it has never run, its last run is not recent, or it could not read what it looks at, with the reason (pointing names when it last ran);
- "check failed": the check itself went wrong.

Each looks different. Only recent evidence counts as OK. A check that cannot read what it looks at changes nothing on the list, neither opening nor closing a problem, and never sends an all-clear.

The product's own safety rules are shown the same way, each as fine, broken, not checked or check failed, with a summary and up to 20 named subjects, each with its state, detail and time. A fine or broken verdict drops subjects not named this time; a failed check keeps the earlier subjects with their earlier times. No results yet reads as no results, not as an error.

### Problems close themselves when they are over

Every problem has a rule that closes it, and the reason it closed is recorded in the history as automatic:

- a problem about a state stays while the state is true, and closes the first time a complete check finds it gone;
- a one-off error (a page that failed, a busy server, a slow write, a restart of the server's own work, more moves by hand at once than could be followed) closes after 24 hours without being seen again;
- a reply to the server-check mail that failed a check closes when a later reply from the same sender was acted on, otherwise after 7 days;
- a file moved by hand on the server closes once it is at least 24 hours old and every computer has followed the move (or none held a copy), otherwise after 7 days without happening again;
- slow work closes the next time the same work finishes in time, also after a restart of the server.

A subject left out of a check because the list was capped, filtered or skipped stays open, and nothing is sent about it. Evidence that cannot be read is never taken to mean a problem is over. A protection line that was missing and this time could not be checked stays missing, with "(last seen <date>; this pass could not check it again: <reason>)", and its problem stays open; only a real answer replaces it. Acknowledging something a problem asked for updates that problem, and anything it raised, at once. Problems about information this server could not read are judged afresh after the server is updated.

Closed problems are forgotten 120 days after both closing and last being seen. An open problem is never removed by any clean-up, however old.

### At most 40 problems of one kind are listed and the rest are counted

Each kind lists at most 40 problems. Beyond that one more entry, "and more of the same", says: "There are N of these and this server shows the first 40. The other M are real and are not listed here." The fix: "Open the dashboard and work through the list: something fleet-wide is usually behind this many at once." Problems not listed because of this are never treated as cleared.

### A computer quiet for a day or red for an hour is raised as a problem

- A computer never heard from, or last heard from 24 hours or more ago, is a serious problem: "<who> has not been in touch since <age>. Everything this dashboard shows for that computer is frozen at that moment, so a green row there means nothing right now." The fix: "Ask that editor to check the CC Sync app is running and that the computer is on and online. If that computer is gone for good, press "Forget" on its row so this stops." After 14 days of silence it is said once more and then stands as the warning in "A computer silent for two weeks is offered for forgetting".
- A computer shown red for an hour or more that no other problem names is a serious problem, "a computer is not syncing": its own sentence saying why it is not syncing, or "<who> has been showing a problem for <duration> and this dashboard cannot say which. It is not syncing normally.", followed by " Nothing more specific could be worked out from what that computer has reported." The fix: "Press "Ask this computer why" on that computer's row, then send us the diagnostics it returns."

Neither is raised for a computer with nothing ticked or a computer wired to the server.

When most computers go quiet at the same time, one serious problem, "most computers went quiet at the same time", points the admin at the server and its network. It stands beside each silent computer's own problem and does not replace it (see The server: installing it and keeping it running: Connections and credentials, "Admins are warned when most computers go quiet at once").

### Project folders the server cannot set up are named with the repair

Each of these opens a problem that closes itself once the cause is gone; every other project carries on.

- A project folder inside another project: "The folder <folder> on the server is marked as a project, but it sits INSIDE another project (<parent>). Projects cannot be inside each other, so this one is not being set up and nothing in it syncs on its own." The repair: stop it being a project, or move the folder out beside the other.
- A project folder that holds other projects (looked for up to eight levels down, skipping hidden folders): "The folder <folder> on the server is marked as a project, but it CONTAINS N project(s) (...). Setting it up would hide them, so the dashboard has refused, and those projects are missing from this dashboard until it is sorted out." The repair: stop the outer folder being a project.
- A project folder copied rather than moved, so two folders claim one project: "Two folders on the server both claim to be the same project (...). That happens when a project folder is COPIED rather than moved." When one of them is where the project already lives: "The dashboard is working with the one it already knew and ignoring the other.", and syncing carries on from it. Otherwise: "The dashboard cannot tell which one is real, so it is leaving both alone and this project is not syncing." The product never guesses. The repair: stop the copy being a project, or delete the copy.
- A project that cannot be set up for syncing: "The project folder <folder> could not be set up for syncing: <the error, cut to 200 characters>. Until this clears, nothing in that project reaches anybody." The repair: look at the other problems first, otherwise check that the NAS's file sharing is running. The health line counts how many projects failed.

### Files moved by hand on the NAS are reported as they are followed

For each move made by hand on the NAS that the server recognises, an information problem opens: "N file(s) were moved on the server, by hand, from <old place>. K computer(s) are following: each moves its own copy and relinks Resolve, so nothing re-uploads the old path." Its fix: "Nothing to do; the computers follow on their own. If this was not a move, open the project page's list of moves." If one look ever finds more moves by hand than can be followed, a serious problem opens, "more file moves were made on the server in one go than could be followed", naming how many were found and how many were not followed; it closes as a one-off error (see "Problems close themselves when they are over"). When not every project could be read, the check for moves made by hand is not marked as checked. How a move is followed is in Proxies and file moves: Moves made by hand on the NAS.


### Slow work on the server is shown as a problem until it is fast again

When a kind of work the server does by itself takes longer than a minute, a warning opens naming that work and how long the last one took. It measures only how long the work itself took, names what was really holding it up, and never advises an editor to untick anything. The next time the same work finishes within a minute, the warning closes, also after a restart of the server.


### Problems in the server's own set-up are shown at start

Each time the server starts it checks its own set-up and puts what it finds on the list of problems, for example a secret that was typed with quotes or spaces around it.

### Protection lines that are missing or cannot be checked are problems

Each protection line that is missing (each project or computer, where a line has several) opens an error, or a warning for the line about editors' deleted copies; each line that cannot be verified or could not run opens a warning. Each closes itself when the line changes. The lines themselves are in The server: installing it and keeping it running: Snapshots, restoring and the server's disk.

### The kinds of problem the server finds and where each leads

| Problem | Severity | Leads to |
|---|---|---|
| A project folder holds other projects, hiding them all | error | the project |
| A project folder sits inside another project | error | the project |
| One project claimed by two folders (a copied project folder) | error | the project |
| A project folder could not be set up for syncing | error | the project |
| The shared libraries (such as the colour look-up tables) could not be set up | error | the Overview |
| A borrowed folder could not be found | warning | the project |
| Proxies with no original, one per proxy folder | warning | the project |
| A project's file count collapsed, so the last good one is kept | error | the project |
| The server was refused while counting a project's files | error | the project |
| Too many projects would have been marked gone at once | error | no button |
| Too many computers would have stopped receiving a project at once, so none was stopped | error | the project |
| Files moved by hand on the server are being followed | information | the Overview |
| More moves by hand at once than could be followed | error | the Overview |
| A project is ticked for a computer that is not being sent it | error | the project |
| A computer is being sent a project nobody ticked for it | warning | the Overview |
| A computer has waited more than 24 hours to be approved | warning | the people and computers page |
| Two computers claim one identity (a cloned computer) | error | the Overview |
| A computer has been silent for a day | error | the computer |
| A computer has been red for an hour, cause unknown | error | the computer |
| A computer is being turned away | error | the computer |
| A computer has been silent so long the server stopped asking | warning | the computer |
| A computer's disk is low, or its recoverable-files bin is too big | warning | the computer |
| An account no computer has reported for in 30 days | information | the people and computers page |
| The NAS's file sharing cannot be reached | error | the health of the server's own work |
| The projects folder is missing or not mounted | error | the Overview |
| The server's disk is low | error | the list of builds |
| The server could not save its records | error | the list of builds |
| Work the server does by itself keeps failing, is overdue, was restarted, or is slow | error or warning | the health of the server's own work |
| A page or request failed on the server | error | the health of the server's own work |
| The server crashed | error | "Download crash reports" |
| One of the server's own checks is failing | error | the health of the server's own work |
| One of the product's safety rules is broken, or its check failed | error | the safety rules |
| A protection the server relies on is missing, or cannot be verified | error or warning | the protection lines |
| A switchable part (b-roll, music, YouTube downloads, Timeline Cards, the Footage Sorter) is on but did not start | warning | that part's state |
| The b-roll archive cannot be read, so every clip sent to Resolve is the small preview | error | the b-roll archive |
| "an update will not install" | error | the computer |
| "a computer is refusing every update" | error | the computer |
| "a new version is not being taken" | warning | the computer |
| "a computer is several versions behind" | warning | the computer |
| "a computer cannot be updated from here" | error | the computer |
| "a trial version is failing" | warning | the list of builds |
| "a computer went back from an update" | warning | the computer |
| "a recalled version is still running" | error | the computer |
| "one platform's version is behind another's" | warning | the list of builds |
| "a held version can strand computers" | error | the list of builds |
| "the server is not running the update applied to it" | error | the list of builds |
| "computers send things this server is too old to read" | warning | the list of builds |
| "this server cannot check for updates" | warning | the list of builds |
| "updates cannot install on this NAS" | warning | the list of builds |
| "work is waiting and nobody is taking it" | warning | the work page |
| "the fleet gave up on some work" | warning | the work page |
| "the server has stopped making work it took over" | error | the work page |
| "footage is outside the tree in '<project>'" | warning | the computer |
| "footage on one computer only in '<first>' and N other projects" | warning | the computer |
| "this server's private network connection is down" | error | the health of the server's own work |
| "this server's private network key is about to expire" | error | the health of the server's own work |
| "the dashboard is not published on the private network" | error | the health of the server's own work |
| "most computers went quiet at the same time" | error | the health of the server's own work |
| "a computer reaches this dashboard unencrypted over the internet" | error | the computer |
| A configured secret has quotes or spaces around it | error | no button |
| The server is running with its security checks relaxed | error | no button |
| Alert mail is slow to go out, or no way to send alerts is set up | warning | the alert settings |
| A reply to the server-check mail failed a check | warning | the alert settings |
| The assistant is not working (its own update failed, or it is stuck) | warning or error | the assistant's settings |

Comparing who should receive each project with who does is done both ways in every check, and each mismatch is named with what it means and how to fix it; the server never repairs it by itself. A problem about a page or request that failed on the server names the full address that failed, carries its own error type, message and the innermost few places it happened, bounded in size and with every key or token masked, never the secret part of a link handed to a client. Deliberate restarts are never counted as crashes, and running a newer release than the vendor offers is never flagged.

Each problem's own rule (when it opens, its words and its fix) is kept with the capability it belongs to: the version problems in Releases and updates: Pushing updates and seeing who has what, "The server tells an admin when versions are not reaching computers"; the shared-work problems in Work shared out across the computers: Failures, retries and the queue ("Admins are warned when work waits and nobody can take it", "Admins are warned when work was given up"); the two footage problems in Resolve on the editor's computer: Clip paths and media outside the shared tree, "Admins are told when footage used in Resolve is outside the shared tree"; the private-network problems and the quiet computers in The server: installing it and keeping it running: Connections and credentials; and the unencrypted connection in Accounts, privacy and the legal paperwork: How secrets and keys are kept, "A credential never crosses the internet unencrypted", where it is repeated daily while that computer still reports. The two footage problems are raised only while the help for the editing program is on, and neither is raised for a computer that withholds the kind of information it depends on.

- When a part is off: no problem about that part is raised or shown.
- When the assistant is off: no problem about the assistant is raised or shown.

#### Lessons

- Met: DSH-079, DSH-080, DSH-081, DSH-082, DSH-083, DSH-084, DSH-085, DSH-086, DSH-087, DSH-088, DSH-089, DSH-090, DSH-091, DSH-092, DSH-093, DSH-094, DSH-095, DSH-096.

