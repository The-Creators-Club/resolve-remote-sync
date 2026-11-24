# The Footage Sorter and camera cards, part 2 of 3

This part covers the record of where every copy of every clip is, sorting footage into the studio's shoots, people and cameras, moving originals into their final folders on the NAS, and placing sound recordings beside the picture they belong to.

## The record of every copy

### What a person can ask the record of every copy

The record of every copy answers four questions for anyone signed in, about every original, proxy and sound recording the studio has, wherever it sits: on a studio drive, a laptop, a client's drive, a camera card, the NAS or the cloud backup.

- **Where is every copy of this clip?** A clip's details list every copy, original, proxy and sound separately, each with its drive and path, whether it is there now, and how sure the product is of it (see "A clip's details list every copy recorded of it").
- **Which drives hold this shoot?** Choosing a shoot's folder lists every drive that holds copies of its clips, how many of the folder's clips each holds and the size, and whether each drive is plugged in now or when it was last seen (see "Which drives hold a shoot, and what is only in one place").
- **Is anything only in one place?** Every clip carries its copy count and a warning state, and the page lists everything not on the NAS, grouped by where it is (see "Every clip carries a copy badge" and "The page lists every clip that is not on the NAS").
- **Where did these go?** When copies vanish from a drive, the product asks, folder by folder, and an admin answers (see "Footage that vanishes from a drive raises one question per folder").

Every answer says how fresh and how sure it is:

- **How fresh.** A copy on a drive plugged in now is shown as plugged in, on which computer. A copy on a drive that is not plugged in is shown as last seen, with the date and the computer. A drive shows when it was last scanned and how many files that found. A drive sitting in a drawer stays fully searchable as it was last seen, every file with its drive and last-seen date, and is marked as not on the NAS.
- **How sure.** Each copy is "verified in full" (every byte read back and compared), "verified quickly", or only listed (seen in a listing, never read). A copy no longer found is shown "missing since <date>", and "a question is open: where did it go?" when one is.

- Who: anyone signed in sees every answer.
- Name and search words: Record of every copy. Search words: copies, backup, where is, drives, ledger, safe.

### Which files the record tracks

The record tracks three kinds of file and ignores everything else, in every scan and every report:

- **Camera originals**: video and raw formats (Blackmagic RAW, RED, ARRIRAW, MXF, QuickTime, MP4, M4V, AVCHD, MPEG transport streams, AVI, Canon raw video, DNG, Sony, Canon and Nikon raw stills, 360-camera files).
- **Sound recordings**: WAV, broadcast WAV, AIFF, MP3, M4A and FLAC, wherever they sit, even inside a proxy folder.
- **Proxies**: a video file (QuickTime, MP4, M4V, MXF, AVI, AVCHD, MKV, WebM) inside a folder named "Proxy" or "Proxies" (any letter case, any depth), or a Sony FX3's own proxy, which sits beside its clip with a name like the clip's number followed by S and two digits. A still or raw file inside a proxy folder is not tracked, nor is an MKV or WebM outside one.

Never looked into: the editing program's cache and optimised-media folders, a camera's thumbnail folders, a folder of set-aside duplicates, the operating systems' and the NAS's recycle bins, operating-system housekeeping and index folders, the NAS's own thumbnail and index folders, and developer folders. Never tracked: files with no extension, hidden files, the small "._" files macOS leaves on other disks, files still being written, and files left by an interrupted or set-aside copy.

- Setting: Files the record tracks. Does: the kinds of file the record counts as originals, sound and proxies, and the folders it never looks into. Default: the lists above. Who: an admin. Applies to: the site. Search words: tracked files, formats, extensions, ignore folders.

### Two copies are the same file, and a recording keeps its identity wherever it lands

The record recognises the same recording wherever a copy of it lands, so its sorting, its backup state and its history follow it through copies, renames, folder moves and a drive moving to another computer. In order of trust:

1. A Sony clip is recognised by the unique recording id its camera wrote.
2. An image sequence is recognised by its folder name, file count and total size.
3. Anything else (Blackmagic, drone, sound, stills) is recognised by its file name (letter case ignored), its size in bytes and its time: where both copies have a modified time, the times are within 3 seconds of each other (exFAT camera cards keep time only to 2 seconds). A missing, zero or absurd time (beyond about the year 2096) counts as unknown and does not stop a match.

A weaker look-alike link pairs two clips with the same name and recording day whose main files are the same size, for example an FX3 recording to both card slots at once, whose ids differ slightly. It is never used on its own to say two copies are one.

A path spelled with a Mac's decomposed accents and the same path spelled the Windows way are one path. On drives, paths are compared without letter case; on the NAS and in the cloud backup, with letter case. Every file name is stored exactly as it is on disk, Chinese and other non-Latin names included.

- On its own: whether two copies are the same recording, from the camera's recording id, else name, size and time as above.
- By hand: an admin answering "where did these go?" links missing copies to their twins on another drive or the same drive (see "Footage that vanishes from a drive raises one question per folder"); a link set that way is never undone by a later scan.

### Every place a copy was ever seen is kept

For each recording the record keeps its name, kind, camera and model, the camera's recording id when there is one, recorded time, duration, size, a checksum when one is known, and where it first came from (which card by serial and label, the card's kind, and when it was first seen), which is set once and never changed. It also keeps every place a copy was seen: on a card, in the NAS's staging folder, in the destination tree (a path that is both counts as the destination tree) or elsewhere, each with when it was last seen, whether it is there now, how it was learned (a scan, a card copy, a move), whether it was verified and when, its file count and each file's size, and whether it is damaged.

Nothing is ever removed. A place where a copy is no longer found is marked not present and keeps its last-seen time, so an unplugged card, an unmounted drive and a deleted file all stay on record. A thinner look never erases a detail a richer one found. Places are compared ignoring letter case and slash direction. When a verified copy's checksum disagrees with one already held, the disagreement is recorded on the clip and shown in its details.

### Drives are known by their own identity and noticed when plugged in

Every computer of the studio tells the record which drives, cards and fixed disks it has as they are plugged in and removed. A drive is known only by its own serial number or volume identity, never by its drive letter, and a computer cannot give a drive another identity: a USB stick can never pass itself off as the NAS.

A new drive is listed as untracked, "Plugged in somewhere and reported, but not tracked yet", with its label, size, free space, computer, drive letter, file system and whether it is plugged in now. A computer's own system drive is never offered as a new drive.

A tracked drive (never a system drive) that is plugged in is scanned on its own, once during that plug-in, when it has never been scanned, its free space differs from its last scan, or its last scan is older than 24 hours. A watched folder on a plugged-in drive is scanned when it has never been scanned or its last scan is older than its own interval. While a tracked drive stays plugged in, new files on it appear in the record within about half a minute without a full rescan, but only once a file is unchanged across two looks, so a file still being copied never appears half-written. A drive is only ever scanned once at a time, and a scan stops by itself when a copy starts reading from that same drive, then runs again afterwards. A scan that could not start is tried again the next time that computer is heard from. Unplugging a drive, or a missing top folder, removes nothing from the record.

Adding a drive or a folder to the record is one action, and from then on, each time it appears on any of the studio's computers, its changes reach the record without anyone asking.

- On its own: which plugged-in drives and folders are scanned, from whether they were ever scanned, their free space and the age of their last scan.
- By hand: an admin scans any drive, folder, the NAS or the cloud backup at once (see "An admin scans a drive, the NAS or the cloud backup now").
- Setting: Tell the studio about this computer's drives. Does: whether this computer lists its drives and their tracked files for the record of every copy. Default: on. Who: an admin, or the person whose computer it is. Applies to: a computer. Search words: drive reporting, drives, privacy, record.

### An admin tracks a drive by saying what it is and whose it is

"Track <drive>" (for a new drive) or "Edit <drive>" shows the drive's identity, the computer it is on and its size, and asks for:

- Name ("a name you will recognise");
- Kind: Ours (counts as a backup), Client drive, Laptop, Card, Other;
- Owner ("whose is it?");
- Folders to scan ("blank = the whole drive; one folder per line");
- Notes;
- Back up to the NAS automatically (when plugged in at home), which stays on only while the drive is tracked.

Buttons: Cancel; Untrack, when editing ("Stop tracking <drive>? Its recorded copies stay in the record."); Track and scan for a new drive, or Save. The person is told "<drive> is tracked now.", "<drive> saved." or "<drive> is no longer tracked (its history stays).", and a newly tracked drive is scanned at once. A failure shows "Could not save: <reason>" for 8 seconds. The NAS and the cloud backup cannot be edited this way.

- Who: an admin.
- Ways in: Track… on a new drive in the drives list, Edit on a tracked drive.

### An admin watches single folders, including on a computer's system drive

A watched folder is one folder on one drive, scanned on its own schedule ("A watched folder is rescanned whenever its drive is visible, for example the field backup on a laptop."). It works on drives that are not tracked whole, and it is the only way a computer's system drive is ever scanned or backed up.

To watch a folder an admin chooses the computer (every computer that reported a drive; "No machine has reported a drive yet."), the drive (shown with sizes), the folder (a drive letter and leading slashes are stripped; blank is the whole drive), an optional name (up to 120 characters). "Watch it" refuses without a drive ("Choose the drive first."). A drive must have been seen by some computer first, else the admin is told so, except a system drive that is plugged in right now. Refusals: a whole system drive ("the system drive can only be watched folder by folder, never as a whole"); the same folder twice ("already watching <folder> on <drive>"). On success: "Watching <name>.", and the folder is scanned at once when its drive is plugged in, then every 60 minutes while it stays plugged in; a failure shows "Could not add the folder: <reason>".

Each watched folder is listed with its name or folder ("(whole drive)"), "visible now" (its drive is plugged in on the watch's own computer) or "not visible", "<drive> / <folder> · <computer>", "every <n> min · last scan <ago>" or "not scanned yet", how many files the last scan found, and its automatic-backup line. A scan of the whole drive, or of a folder containing the watch, updates it too. An admin can switch its automatic backup on or off, scan it now, or remove it ("Stop watching <folder>? Its copies stay in the record."; then "No longer watching <folder>."). Removing a watch keeps every copy it found.

- Who: an admin adds, changes and removes; anyone signed in sees the list.

### Drives and folders back themselves up to the NAS when they are at home

Each tracked drive and each watched folder has a switch, off by default, "Copy what is in this folder and not on the NAS yet into the NAS staging folder, by itself, when this computer is at home". With it on, whenever the drive is plugged in at the studio, every tracked file on it that has no copy on the NAS is copied into the NAS's staging folder, under the computer's and the drive's names, and verified. It only adds: it never deletes, never overwrites and never moves anything, on the drive or on the NAS. Each copy is recorded like any other copy the product makes.

It runs only when the computer is on the studio's own network. When the computer is away, or the product cannot tell, nothing is copied and the drive says "Waiting: this computer is away from home".

The drive's backup line reads one of: "Backs up to the NAS by itself when plugged in at home", "Backing up to the NAS: <n> files · <size> (more after this)", "Backed up <n> files · <size> <ago>", "Everything on it is at home", "Waiting: this computer is away from home", "Backs up when it is plugged in at home", "Automatic backup failed: <reason>". Switching it on or off says "<folder> now backs up to the NAS by itself, at home." or "<folder>: automatic backup off."

- Who: an admin switches it.
- Setting: Back up to the NAS automatically. Does: copies whatever on this drive or folder is not yet on the NAS into the NAS staging folder whenever it is plugged in at the studio. Default: off. Who: an admin. Applies to: a computer (one of its drives or watched folders). Search words: automatic backup, laptop backup, staging, at home.

### An admin scans a drive, the NAS or the cloud backup now

Scan now on the NAS walks the whole footage tree of the NAS. On the cloud backup it reads the backup's listing again, even if no new backup has run. On a drive:

- the drive must be plugged in: "that drive is not plugged into any machine that reports to the dashboard right now";
- a system drive is only scanned through its watched folders: "the system drive is only scanned through its watched folders";
- a tracked drive scans its folders to scan plus every watched folder on it; an untracked drive scans only its watched folders, or the whole drive when it has none.

A scan already running is not started twice; the person is pointed at the one running. The person is told "Scan of <drive> queued." or "Scan of <drive> started."; when the computer the drive is in cannot be reached right now, the person is told so, and a failure is shown for 8 seconds.

- Who: an admin.
- Ways in: Scan on a drive in the drives list, scan now on a watched folder, the record's own scan now for the NAS and the cloud backup.

### A scan never changes a file and never writes off footage on a doubtful listing

A scan only lists: nothing on the drive is opened for writing, renamed, moved or locked, links are not followed, and very long Windows paths are included. A file the scan cannot record (an odd name, an unreadable entry) is skipped and counted, and the rest of the drive is still recorded. Pulling the drive stops its scan ("the drive is gone"); what was gathered is kept and the scan counts as unfinished.

Only a good scan marks copies missing, and only under the folders it covered:

- a scan that did not finish, was cancelled or was cut short marks nothing missing; it only adds;
- when a scan finds under 80 % of the copies the record held under the folders it covered, and the record held more than 100 there, it is treated as a bad scan (a half-mounted or damaged drive) and nothing changes: "suspect listing: <n> files where <m> were; nothing changed (a half-mounted drive or a scan during a disk check?)";
- folders the scan could not read, or was told to leave out, are never judged; the scan names them (up to 200; more than 200 and the scan counts as unfinished, "<n> folders could not be read (more than can be listed)"); if a drive's top folder cannot be read, nothing on that drive is judged.

Only a good scan updates the drive's "last scanned" time, file count and free space.

### A finished scan updates the record all at once

A page never shows half a scan: the record changes all at once when a scan ends. A new file is recorded as listed, the lowest level of sureness. A file at the same path with a different size, or a time more than 3 seconds apart, is the same file updated: it stays tracked at that path, with its new size and time, and is never treated as a loss plus a new file. A missing copy seen again unchanged becomes present again. A copy no longer found that has a twin (same name, size and time) present elsewhere on the same drive was moved within the drive, and the record follows it with no question asked. Each scan reports how many files it saw, added, replaced, found missing and found back, and the questions it opened.

### Footage that vanishes from a drive raises one question per folder

Copies a good scan no longer finds, that were not moved within the drive, are marked "missing since" that moment and stay on record. For each folder, ONE question is opened: "these files left <folder> on <drive>: where did they go?", with the number of files and their size. If one other drive (not a card, not the cloud backup) holds a present twin of every missing file of that folder, it is offered as the likely answer. A second disappearance from a folder with an open question adds to that question. Cards and the cloud backup never raise questions: a card is formatted on purpose, and cloud copies age out with the backup's own keeping period, quietly.

Above the clips the page shows "<n> folder(s) went missing", "Where did these go?", with Answer and Hide. Each question shows its folder ("(the drive root)"), "on <drive> · <n> file(s) · <size> · gone since <date>". The full list shows open questions largest first by size (or every question, answered ones too, on request), at most 500, each with its drive, folder, file count, size, the suggested drive, when it was opened, and the answer, who gave it and when. An admin answers:

- **Moved to…** another, known drive (the suggested one preselected and marked "(suggested)"; "Choose where it went first."): each missing file is linked to its twin there. If that drive has not been scanned since, the question stays open with that answer and settles itself when the drive's next scan or copy supplies the files.
- **Moved within this drive** (moved, renamed or replaced): each missing file is linked to its twin on the same drive; the question closes when none are left.
- **Deleted on purpose**, after "Mark <n> file(s) in <folder> as deleted on purpose? They stop counting as copies.": every missing file of the folder is marked deleted and the question closes.
- **Plug it in and rescan** ("Leave it open until the drive is scanned again"): noted, and the question stays open.

The answer is confirmed with "<what> - thanks." or "<what> - recorded; the rest waits for the next scan."; a failure shows "Could not record that: <reason>". A question already answered refuses another: "already answered: <answer>". Questions also settle themselves: when the missing files turn up again the question closes as "found again", and when they turn up elsewhere on the same drive it closes as "moved within the drive". A missing copy is never written off without an answer.

- On its own: which drive is the likely answer, from which single other drive holds a twin of every missing file.
- By hand: an admin's answer decides; a suggestion is never applied without one.
- Who: an admin answers; anyone signed in sees the questions without the answers.
- Ways in: the warning above the clips, the open-questions count on each drive in the drives list.

### Copies the product makes are recorded with how carefully they were checked

Every copy the product makes (a card copy, a field backup, an automatic backup to the NAS, a move) is recorded the moment it is verified, with how carefully it was checked (listed, quick or full), when, and which person and computer made it. It counts towards "backed up" at once and survives a power cut, even when the computer that made it cannot reach the studio's server; it reaches the record for everyone within about a minute of that computer reaching the server again, and nothing waiting is ever lost by being offline. A copy already recorded is kept, and upgraded if the new check was more thorough.

A copy is recorded only on a drive the computer identifies by its own identity. If a drive letter came to hold a different drive while copying, nothing is recorded for it: "<destination> is now a different drive, so nothing was recorded for it." and the destination fails "<destination> changed while copying; nothing was recorded." A copy to a folder on no known drive records nothing. A report from a computer that disagrees with a copy the record holds as present at the same path is counted as a conflict and left alone: it never replaces it. Only a copy the server itself verified on the NAS may replace a changed file at a known path. Any copy recorded settles pending "moved to" answers and closes questions whose files are back.

### A laptop in the field knows what is safe without reaching the studio

The field backup page on an editor's computer (see part 1, "Copying a card" and "Backed up and safe to format") can be opened only from that computer itself; a page from anywhere else, any other site open in the same browser included, is refused, except the studio's own dashboard. Anything that changes something (starting a copy, adding a folder, setting a drive's kind) must come from the page itself, the dashboard, or the app on that computer. A request too large to be real is refused with "that request is too large", an unexpected failure answers "the app failed to handle that" instead of hanging, and every refusal the page receives is a plain sentence.

Along its top the page shows:

- "<n> waiting to send" when copies made here have not yet reached the studio's record;
- whether the studio's record can be reached: "Record online" when the last attempt reached it, "Offline" when it did not, "Record not asked yet" when no attempt has been made, "No dashboard" when this computer has no dashboard set up;
- how copies are verified, on hovering: a check by the copier after every file, or "every file read back in full and compared";
- the computer's name.

The laptop keeps its own copy of what the record knew, when it last reached it, about every drive plugged in then and the NAS, plus drives seen in the last 60 days that are not plugged in (never cards), with their names and kinds. Away from the studio it can therefore still say which of a card's files already have a safe copy. A card file's copy counts only when it really is a copy of this card's file and is still there: it matches by name, size and time (within 3 seconds) and then belongs to this card (a field copy carrying this card's identity at the file's place on the card, never one marked from a different card; otherwise a path ending with the file's path on the card, or, for a file at the card's top level, a place in this card's own landing folder); a copy on the NAS counts wherever it is, since footage there is moved into project folders. When the drive holding a copy is plugged in, the copy is checked there (size and time) and a missing or changed copy does not count; a copy on a drive not plugged in is believed. Copies made on this computer count the moment they are verified.

The page's record section shows "Waiting to send: <n> copies", "Last tried: <how long ago>" or "not yet", and "Record on this laptop: <n> copies, updated <how long ago>" or "never", with the last attempt's problem or "No dashboard is set up here. Copies are kept on this laptop." Sending and refreshing happen on their own when a copy finishes and every 5 minutes while the page is open and nothing is copying; "Send and refresh now" ("Sending..." while it runs; unavailable while one runs or with no dashboard set up) does it at once, and the page refreshes 1.5 seconds later. Messages: "No dashboard is set up on this computer."; "The dashboard could not be reached. Copies are kept here and sent when it can."; "The record was not refreshed: <error>"; "Could not sync: <error>". When the studio cannot be reached, the laptop's copy stays as it was. Every verified copy the page makes reaches the studio's record, whatever its destination, the NAS included.

- Who: a person at that computer.

### The NAS's footage tree is walked every night and after each clean move

The whole footage tree of the NAS is walked every night at 04:30 on the NAS's clock, after every move that finished cleanly, and when an admin presses scan now on the NAS. Only one walk runs at a time. It skips the folders the record never looks into and any folders an admin lists to leave out (paths inside the NAS tree, letter case ignored); left-out and unreadable folders are not judged, and the rest of the tree still is. It records the NAS's total and free space. Its progress updates about once a second. Refusals say that no NAS footage tree is set up, so the NAS cannot be scanned; that the NAS tree is not reachable; or that it cannot be read, with the error. When the nightly walk cannot run, that is shown as the last walk's outcome on the activity panel.

- Setting: Folders the NAS walk leaves out. Does: folders inside the NAS footage tree that are never walked or judged. Default: none. Who: an admin. Applies to: the site. Search words: exclude, leave out, NAS folders, skip.

### The drives list shows every drive that holds footage

"Drives" shows a count of new untracked drives ("New drives nobody has said are ours or not"), "<n> drive(s)", a sort (Name, Last seen, Size, Files), Backups, and a refresh ("Ask the record again"). While loading: "Loading…"; with nothing: "No drives reported yet."

New drives, most recent first: name, "plugged in · <computer>", "<size> · on <computer> · seen <ago>", and Track… for admins.

Tracked drives, in label order (letter case ignored), grouped "Home NAS", "Our drives", "Laptops", "Cloud", "Client drives", "Cards", "Unknown". Each shows its kind, name, owner, notes, where it is plugged in now (computer, drive letter, since when) or "not tracked", "scanning" or "scan <state>", "auto backup"; "<free> free of <size>"; "<n> masters · <n> proxies · <n> audio" (with their sizes) or "<n> files"; "seen on <computer> <ago> · scanned <ago>" or "never scanned"; when it was first recorded; "<n> file(s) not found by the last scan"; "<n> open question(s)"; and its backup line. Watched folders are listed with whether each is visible now.

Clicking a drive (or Enter or Space, or Show clips) shows the clips with a copy on it ("Clips with a copy on <drive>"; again to clear) and, on a phone, goes to the clips. Admins also get Scan and Edit (not for the NAS or the cloud backup). Times read "just now", "<n> min ago" under an hour, "<n> h ago" under 48 hours, then "<n> d ago".

- Who: anyone signed in; Track, Scan and Edit for an admin.
- Name and search words: Drives. Search words: drives, disks, laptops, client drives, where plugged.
- Phone and desk: on a phone, choosing a drive goes straight to its clips.

### A clip's details list every copy recorded of it

A clip's details give one answer about its copies:

- where the clip is: "Card", "Staging", "Final" or "Elsewhere";
- whether it is backed up: "backed up (<where>)" or "not backed up";
- the last copy plan's verdict when it had one ("Destination check: <state> · <time folder> · ±<size>", the existing path on hovering);
- "Copies on drives" with the copy-count summary, then groups "Masters · <n>", "Proxies · <n>", "Audio · <n>". Each copy shows its drive, the path, "plugged in · <computer>" or "last seen <ago> · <computer>" / "not plugged in", "missing since <date>" when gone, "verified in full", "verified quickly" or its check note, "recorded <date>", where it came from, and "a question is open: where did it go?" when one is.

Messages: "Reading the record…"; "No copies recorded yet."; "Not in the record yet - it gets a key when it is copied."; "Record: <error>".

- Who: anyone signed in.

### Anyone can look a clip up in the record by clip, path or name

The record can be searched by a clip on screen, by any path a copy is known at, or by name (letter case ignored, at most 50 results); each result shows its copies and backup state. With nothing given the person is told what to give; an unknown entry is "not in the record". A summary gives how many recordings and copies are known, how many present copies on each shelf (card, staging, destination tree, other), and how many recordings have a verified copy in the destination tree.

- Who: anyone signed in.

### Every clip carries a copy badge

Each clip shows on how many drives its original sits, "<n>×", in three states: healthy (drawn outlined), not backed up (filled gold), and only on a laptop, a card or a client's drive (filled red). Its tooltip reads "<n> copy/copies · home · cloud proxy · only on a laptop | only on a card | only on a client drive | not backed up". A clip with no record shows nothing. A clip with a copy on tape carries a small mark, never green, naming the tapes.

The page also shows the percentage of master files that have a second copy that counts as a backup.

- On its own: the badge's state, from where the record holds present copies of the clip's original.

### Clips can be filtered by where their copies are, and sorted by fewest copies

Where ("Copies anywhere" by default): On a drive… or Not on a drive…, then "Choose a drive…", each "<name> · <kind>" (with no drive chosen nothing is filtered; while the drive's list loads nothing matches and "Listing the clips on <drive>" shows; a failure shows "Could not list the clips on <drive>: <reason>"); On a computer… or Not on a computer… (every drive that computer reported); 2 or more copies; 3 or more copies; 4 or more copies; Only on a laptop; Not at home (not on the home NAS); No cloud proxy (the clip's proxy is not in the cloud backup). Clips with no record match only "Not on a drive" and "Not on a computer". Sorting by fewest copies orders clips by copy count, unknown last. These filters and this sort work in every view of clips.

### The page lists every clip that is not on the NAS

When any clip is not at home the header shows "⌂ <n> not at home", or the warning "⚠ <n> only on a laptop" when some live only on a laptop; its tooltip reads "<n> clips exist only on a laptop. <n> clips are not on the home NAS. Click for the list." Clicking opens "Not at home": "<n> clips are not on the home NAS · <size>.", then the groups "Only on a laptop · <n>", "On our drives, not on the NAS · <n>", "On other people's drives · <n>" and any other, each row a folder with "at <where> · <n> file(s) · <size>". With nothing away: "Everything is at home." Drives… opens the drives list; Close closes.

### Which drives hold a shoot, and what is only in one place

Choosing a shoot's folder (or any folder of the destination tree) shows which drives hold copies of the clips in it or headed for it: each drive with how many of the folder's clips it holds, their size, its kind, and whether it is plugged in now or when it was last seen. Clips of the folder held in only one place are counted and can be shown at once.

### Auditing the destination tree into the record

Any signed-in person can audit the destination tree: it is read in the background, every clip found there is recorded as present in the destination tree, and anything recorded there but not seen is marked not present. Progress shows the start and finish, clips so far, clips linked, and any error. Only one audit runs at a time; asking again shows the running one. Refused, saying so, when no destination tree is set up.

- Who: anyone signed in.

### Moves the product makes are followed in the record at once

Every file the product moves is followed in the record the moment it moves: the clip gains its new place, keeping whether its copy was verified, and its old place is marked moved, so no scan ever asks "where did these go?" about it. A moved folder takes every copy beneath it. Only the main file's move changes where a clip is recorded; its proxies and metadata files are not separate places. A clip's sorting counts as done only when all its planned files moved: a clip whose main file moved but whose other files did not is held back, across restarts too, so its leftover files go with its next move. After a move that finished cleanly the NAS is walked again to catch anything else. A failure in this follow-up never fails the move.

### The activity panel shows every scan and copy running and waiting

The panel lists:

- the NAS walk: "Scanning <label>", files and size so far, files per second, the current folder;
- the cloud backup's listing being read: "Reading the <label> listing", files so far;
- a drive scan on a computer: "Scanning <label> on <computer>", shown as running once files arrive or it was heard from in the last 2 minutes, otherwise as waiting; files, size, speed and current file while fresh;
- each scan still waiting: "Scan of <label> waiting for <computer>";
- running copies: "Copying <card label or serial> to the NAS" and "Copying <drive> to <drive>", each with its phase, bytes, files, speed, time left, current file and start time.

It also shows the last backup of the record itself, the last NAS walk's outcome (time, status, number of errors, up to 20 folders that could not be read, files), and the cloud backup's status. The panel updates by itself whenever something changes.

### The page keeps up with the record

While the page is visible it checks for changes about every 30 seconds, every 2 seconds while the backups panel is open, and at once when the tab comes back into view. When the record changes, every copy count, drive list, open question and not-at-home figure on the page is refreshed. Open questions are re-read about every minute and the not-at-home figures about every five minutes.

### The record survives losing the NAS

Every day at 04:00 on the NAS's clock, and whenever an admin presses back up now, a consistent copy of the record is taken and checked for damage; a damaged copy is deleted and the error shown. The Sorter's own settings and sorting plan (not its pictures or caches) are copied alongside. They go into the folder the NAS carries to the cloud backup when one is set up, else beside the record. The newest 7 days are kept and older ones deleted. The last result (time, size, whether it worked, error, number of files) is shown with the activity and the cloud backup's status.


### The NAS's footage goes to the cloud backup every night

The cloud backup of the NAS's footage runs every night and sends only new and changed files. The record's page has its on and off switch, its time and Run now, and shows the last run. A run never starts beside one in progress. The cloud backup itself is the server's (see The server: installing it and keeping it running: Off-site backup).

- Setting: Nightly cloud backup of footage. Does: sends new and changed footage to the cloud backup every night. Default: off until a cloud backup is set up. Who: an admin. Applies to: the site. Search words: cloud backup, off-site, nightly, run now.

### Clips that exist on tape

A tape is a place in the record like a drive, identified by its barcode, never by its drive letter (tapes share one letter). A clip whose only copies are on tape offers a restore request that names the tapes and where they are kept.

#### Lessons

- Met: SRT-091, SRT-092, SRT-093, SRT-094, SRT-095, SRT-096, SRT-097, SRT-098, SRT-099, SRT-100, SRT-101, SRT-102, SRT-103, SRT-104, SRT-105, SRT-106, SRT-107, SRT-108, SRT-109, SRT-110.

## Sorting into shoots, people and cameras

### The studio's calendar is connected, read-only, so footage can be placed by shoot

The Sorter reads shoots from the studio's online calendar (Google Calendar for this studio), with read-only access. Connecting opens the calendar provider's sign-in in a new tab; the page says "Waiting for Google in the other tab…" and waits up to 3 minutes: "Connected to Google Calendar as <account>", or "Gave up waiting. If the tab is still open, finish there and press Connect again." The sign-in link works once and expires after 10 minutes. The tab it returns to says "Connected to Google Calendar", "Signed in as <account>." (or "Signed in."), "You can close this tab. The sorter is already syncing."; or "Not connected" with what the provider said; or "The sign-in link had expired or was not started from this app. Try again from the sorter." When the server has not been set up to sign in to the provider, the calendar settings say "Not configured" with the admin's set-up steps, and offer only Close.

The calendar settings show a status, "Connected as <account> · synced <ago> · <n> events", "Not connected", with any error; one tick per calendar on the account, the main one ticked by default ("Reading your calendars…", "Not connected yet - press Connect.", "Could not list the calendars", "No calendars on that account.", "Press Connect to sign in with Google."); and From date ("Ignore anything scheduled before this day"). Sync now says "Synced - <n> events"; Save says "Calendar settings saved - <n> events" and stays open. Disconnect asks first, "The sorter will stop refreshing events. Bindings and assignments are untouched.", then forgets the access and the events at once (nothing is revoked on the provider's side). Failures are shown in the dialog.

While connected, events are fetched again every 15 minutes and on request, from the start date to one year after it, from each chosen calendar. Every occurrence of a repeating event within that window is its own event, marked repeating, and a changed single occurrence replaces it. Cancelled and undated events are left out. An all-day event runs from midnight of its first day to midnight after its last. Event times are read and shown in the studio's time zone. If a fetch fails, the error is shown and the last events are used, so the Sorter keeps working offline. If the provider withdraws access, every calendar action says "Google access was revoked or expired" with the reason until someone connects again.

The page header always shows the calendar's state: connected, "● Google · synced <n> min ago" ("just now", "<n> h ago", "<n> d ago", "never synced"; the "ago" text updates every minute), with the account, "<n> events" and "Click for calendar settings" on hovering; failing or revoked, "● Google · reconnect" with the error, and each new failure shown once as "Calendar: <error>" for 9 seconds with Fix; nothing, "Connect Google Calendar" ("No calendar - suggestions have nothing to go on. Click to connect.").

- Who: an admin connects, disconnects and changes the settings; anyone signed in sees the status and the calendars and may ask for a sync now.
- Ways in: the calendar state in the page header, the calendar settings, the refresh on the events list.
- Setting: Calendars the Sorter reads. Does: which of the account's calendars count as shoots. Default: the account's main calendar. Who: an admin. Applies to: the site. Search words: calendar, shoots, Google, events.
- Setting: Calendar start date. Does: events scheduled before this day are ignored; events are read up to one year after it. Default: 1 April 2026. Who: an admin. Applies to: the site. Search words: from date, calendar start, ignore before, events.

### The events list shows every shoot on the calendar by day

The events list carries a count of all events (hidden at zero), "Calendar events", a refresh ("Refresh the calendar now", which fetches from the connected calendar and says "Calendar refreshed - <n> events", or "Could not refresh the calendar"; disabled while working) and "<n> bound / <total>". A filter box ("Filter events…") matches title, place, bound folder and start time. Events are listed by start under day headings, each with its time range or "all day", its title ("(no title)") and place.

Each event's folder control shows the bound folder; or the folder read from the title, marked as a guess; or "Bind folder…". On hovering: "Bound to <dest> - click to change"; "Read from the title: <reason> / Already suggesting clips. Click to change, or ✓ to lock it in."; "Bind this event to a destination folder to generate suggestions". "<n> suggested" ("Select the <n> suggested clips") clears the search, camera, date, kind, status, source folder and event filters, selects that event's unassigned suggested clips, scrolls to them and says "<n> clips selected - drag them onto a folder, or press Accept suggestions." Clicking an event's title filters the clips to that event; clicking again removes the filter. Empty: "No events match the filter." or "No calendar events loaded."

- Who: anyone signed in.
- Name and search words: Calendar events. Search words: events, shoots, calendar, schedule, bind.

### The studio's episodes, naming rules and roster

Three pieces of studio data tell the Sorter where each shoot's footage belongs. An admin manages them in the Sorter's settings, and a change takes effect within 15 minutes with nothing restarted.

- **Episodes**: the season's top folder, each episode, its short names, and the folder layout under an episode (its "B-roll" and "Interviewees" branches and its standard subfolders).
- **Title rules**: patterns on event titles that skip an event or set its kind, person, episode, the name of its interviewees branch, or send it to a whole destination outside the episode tree. Patterns match any letter case, in any script. A rule that cannot be used is shown as broken, with why, and is not applied.
- **Roster**: per person, their episode, Chinese name and English name. Never contact details.

The roster can be built from the studio's planning sheet saved as a spreadsheet file with an Episode column, a Name column and optionally an English name column; it is refused with a plain message if a column is missing or the sheet is empty. The episode carries down through its block of rows; one cell may hold several names separated by new lines, semicolons or the Chinese list comma (never commas, because English names are written surname first); bracketed text is removed and placeholder words (b-roll and the like) dropped; Chinese and English names are paired by position. Only episode, Chinese name and English name are kept: the sheet's e-mails, phone numbers and addresses are never copied. It reports how many people across how many episodes, and a count per episode.

With no episodes set up nothing is placed on its own and no misses are listed. A roster that is missing counts as empty.

- Who: an admin.
- Setting: Season folder. Does: the top folder under which episodes are filed. Default: none until set (this studio: "2026/FF5"). Who: an admin. Applies to: the site. Search words: season, top folder, episodes, layout.
- Setting: Episodes and their short names. Does: the episodes footage is sorted into and the short names that point at each in an event title. Default: none. Who: an admin. Applies to: the site. Search words: episodes, aliases, short names, series.
- Setting: Title rules. Does: patterns on calendar titles that skip an event or decide its kind, person, episode or folder. Default: none. Who: an admin. Applies to: the site. Search words: rules, patterns, event titles, routing.
- Setting: Roster. Does: who appears in which episode, by Chinese and English name. Default: empty. Who: an admin. Applies to: the site. Search words: roster, interviewees, people, planning sheet.
- Setting: Standard subfolders of an episode. Does: the folders every episode is given when its skeleton is planned. Default: "B-roll" and "Interviewees". Who: an admin. Applies to: the site. Search words: subfolders, skeleton, layout, episode folders.

### The Sorter places each calendar event in a folder on its own

For each event the Sorter works out its kind, its episode, its person and its folder.

**Kind.** B-roll if the title contains b-roll, broll, event, shooting, filming, montage, or the Chinese words for press conference, march or parade, drill, competition, open tournament, course or activity, and no interview word; interview if it contains "interview" or the Chinese word for interview; otherwise interview.

**Episode and person**, in order of trust:

1. the first title rule whose pattern matches;
2. an episode's short name found in the title (leftmost, then longest);
3. a roster name in the title: the Chinese name, the given name alone for 3-4 character names, the full English name, or each English word of 4 or more letters that is not a title (dr, mr, prof, jr, sr, iii) or a common word ("the", "and"), English only as whole words; small misspellings of a roster name still match. With an episode known, a person in that episode is preferred; with none, only a name in exactly one episode decides it. A name belonging to two episodes is never guessed;
4. for interviews only, an existing person folder under an episode's interviewees whose first word appears in the title (longest wins).

**Folder.** "<season>/<episode>/B-roll/<subject>" or "<season>/<episode>/Interviewees/<subject>". The subject is the person's folder name, "<Chinese> <English>" or whichever exists, when a person was found; otherwise the title with the episode's short name removed from either end, trailing words "interview", "broll", "filming", "online" and a leading "broll" removed, and separators trimmed. Characters Windows forbids become spaces, control characters go, spaces collapse, and trailing dots and spaces go. An existing sibling folder whose name equals, starts with, or is the start of the subject is used instead (the shortest), so a subject named in Chinese lands in an existing folder named in Chinese and English; existing folders are looked at 6 levels deep. A b-roll event with no subject goes to the episode's B-roll folder itself; an interview with no subject is not placed.

**Two people in one event.** When one event names two people, its clips and sound are split between their two folders by what is heard on them, or the person is asked; they are never all filed under one name.

Each placed event carries a plain reason: 'title matches /<pattern>/', '"<name>" is in the <episode> roster', '"<name>" already has a folder in <episode>'. Every event that got no folder and is not bound by hand says why: skipped (naming the rule), ambiguous (a roster name in several episodes, naming the name and the episodes), or unmatched.

- On its own: the event's kind, from its title words or a title rule.
- On its own: the event's episode and person, from title rules, short names, the roster and existing folders, in that order.
- On its own: the event's folder and its name, from the episode, kind and person, reusing a matching existing folder.
- By hand: a person binds the event to any folder, or to none, and that binding replaces all three decisions for that event (see "A person binds an event to a folder, or dismisses it"); an admin's title rule decides kind, person or folder for every event it matches. A binding set by hand is never overwritten by a later automatic pass.

### A person binds an event to a folder, or dismisses it

Any calendar event can be bound to a folder of the destination tree. The folder control on the event opens the folder picker "Bind “<title>” to folder" (with Clear when bound); ✓ next to a folder read from the title ("Confirm <dest> as a real binding") binds it as it stands. Binding to nothing removes the binding and the event is placed on its own again. A binding set by a person always wins over the folder worked out from the title, and the person sees which suggestions come from a binding, from the title, or from sound. Suggestions are recalculated at once; failures say "Binding failed: <reason>" or "Could not refresh suggestions: <reason>".

An event can also be dismissed (no footage expected) and later restored. Bindings and dismissals are part of the sorting plan, so they hold on every computer, and dismissed shoots are left out of the missing-footage checks and the card report.

- Who: anyone signed in.
- Ways in: the folder control in the events list, the event cards a search shows.

### Each clip's camera label is decided on its own

Each clip gets a camera label, used for its time folder and for telling camera bodies apart. First rule winning:

- sound clips get the sound label;
- stills, image sequences and other files get none;
- a Sony FX3 (by the model the camera wrote, never an FX30) gets the A-camera label;
- any other Sony model (cinema, mirrorless, camcorder, compact) gets the B-camera label;
- a Blackmagic RAW file or a Blackmagic camera gets the Blackmagic label;
- a file name starting "DJI_" (a drone) gets the drone label;
- otherwise a camera folder in the path: one named B-cam or Bcam (as a word) gives the B-camera label, one named A-cam or FX3 the A-camera label;
- anything else gets none, and so no time folder.

The model the camera wrote beats the folder name.

- On its own: each clip's camera label, from the model the camera wrote, the file's kind, its name and its folder, as above.
- By hand: a person sets the camera label of any selected clips from the clip's details or the clip menu; the clip keeps that label through every later scan.
- Setting: Camera labels. Does: the words used for the A camera, B camera, Blackmagic camera, drone and sound in time folder names. Default: A-CAM, B-CAM, BMCC, DRONE, AUDIO. Who: an admin. Applies to: the site. Search words: camera label, A-CAM, B-CAM, camera folders.

### The Sorter suggests a folder for each clip

Only events with a folder (bound or worked out from the title) suggest anything. Every clip with a recorded time is considered, clips on cards still in readers included.

- **High** confidence: the clip was recorded from 1 hour before the event's start to 2 hours after its end.
- **Low** confidence: no high match, but an event with a folder covers the clip's day.

Among candidates, a timed event beats an all-day one, then the nearest, then the shorter, then the earlier. An event counts for at most 400 days. Each suggestion shows its folder, the event and its title, the confidence, how many minutes the clip is outside the event (0 inside), whether it came from a binding or from the title (with the reason), and up to 3 alternatives: other events in the high window or on the same day pointing at a different folder, one per folder, nearest first, each saying high or same-day and minutes off. A sound clip the calendar leaves without a suggestion may get one from what is heard on it (see "The Sorter proposes where each sound recording belongs").

A clip belongs to an event when the event is its suggestion or one of its alternatives, or when it is assigned to the event's folder (or below) and was recorded within the event's window (1 hour before the start to 2 hours after the end, or the whole day for an all-day event); an event with no folder claims assigned clips by the window alone.

A suggestion never assigns anything: it waits for a person. A suggested folder appears in the destination tree marked as not yet confirmed.

- On its own: each clip's suggested folder and alternatives, from the calendar events it was recorded during or on the day of.
- By hand: a person accepts, picks an alternative, or assigns any other folder; an assignment made by hand is never changed by a later suggestion.
- Who: anyone signed in sees suggestions.

### A person reviews suggestions with their evidence before accepting them

Accept suggestions works on the selection if there is one, otherwise on every suggested, unassigned clip in view. Clips already backed up are left out (they would be second copies) and can still be assigned by hand. The button reads "Accept <n> suggestion(s)", with " (view)" when working on the view; "All backed up already" when every candidate is backed up; otherwise "Accept suggestions", disabled. When some were left out it says on hovering "<n> suggested clip(s) are already backed up and left out - assign those by hand if you want a second copy." With none: "No suggestions to accept here." Clicking a single clip's suggestion accepts that one at once.

The review is headed "<n> clip(s) · <size> into <n> folder(s)", with notes "<n> already backed up - left out", "<n> low confidence (same day only)", "<n> with another event in contention", or "every one is a high-confidence match". It has one row per destination, most clips first: a tick (on by default; clicking the row head toggles it; an unticked row dims), the path and "<n> · <size>"; up to three pieces of evidence ("← <event> ×<n>" or "← ♪ <name>"), "… and <n> more", and "<n> matched on the day only, not the hour". Where some clips have alternatives, the row offers the group's own suggestion and each alternative ("<folder> · <n>" or "<folder> · <n> of <m>"), reading "All <n> go to their own suggestion" or "<n> go to <folder> · <m> stay on <folder>"; choosing an alternative sends only the clips that have it. Show these selects that group's clips, closes the review and scrolls to them. Cancel, or Accept checked ("Nothing checked." when none is ticked). Accepting ends with "Accepted <n> suggestion(s) into <n> folder(s)", with Undo, which puts every clip back exactly as it was. Nothing is written before Accept.

- Who: anyone signed in.

### Selected clips switch among their own suggested folders in one step

The suggestions menu (enabled when a selected clip has a suggestion) is headed "<n> of <m> selected clip(s) has/have suggestions" and lists every folder that is a suggestion or alternative for any selected clip, most clips first, each with "<event> · <n> of <m> clips (<k> as first choice)" and a way to show that folder in the tree. Choosing one assigns only the selected clips that have it among their own choices: "Assigned <n> clip(s) to <folder> · skipped <k> without that suggestion" for 12 seconds with Undo, which restores every clip exactly as it was. Otherwise: "None of these clips has <folder> as a suggestion." or "The selected clips have no suggestions."


- Who: anyone signed in.

### A person assigns clips to a folder, or takes them back

Any number of clips can be assigned to one folder of the destination tree, in one of two ways: **the studio's convention** (time folders and the studio's layout inside the folder, see "Footage is filed in day-and-camera time folders" and "Where each file of a sorted clip goes") or **keep the card's layout** (each file keeps its path below its source folder, and no time folders). Which one new assignments use is a choice on the page ("Folder structure used for new assignments": Convention, the default, or Preserve), stored with every assignment made after it is changed. Assigning again replaces the earlier choice; unassigning returns clips to unsorted.

Each change shows at once, with the count and the folders and time folders it produces: "<n> clip(s) → <dest>". If the server refuses it, it is put back on screen and "Assign failed: <reason>" or "Unassign failed: <reason>" is shown. With no clips chosen the person is told clips are required. Unassign (also Delete or Backspace) removes the selected clips' assignments; a clip that is in place has nothing to remove. The answer refreshes the suggestions and the planned time folders.

A folder lists the clips assigned to it but not yet there, drawn with a dashed outline at lower opacity, beside the clips already in it.

- Who: anyone signed in.
- Ways in: dragging clips onto a folder, Assign to… with the folder picker, a clip's own suggestion, Accept suggestions, the suggestions menu, Assign in a recording's detail or the audio worklist, and dropping files from the file manager onto a folder. The row under the pointer is highlighted. The root takes no clips.

### Files dragged in from the file manager are found in the library and join the plan

Dragging files over the page covers it with "Drop to find these clips in the library" (not while dragging clips or folders inside the page; dialogs handle their own drops). On drop, filed clips are loaded if needed and each file is matched by name, ignoring case (and by the folder name of an image sequence), using its exact size when a name appears more than once. Dropped on a destination folder, the matched clips are assigned there at once, show in that folder, and are selected ("<n> clip(s) → <dest>"). Dropped elsewhere, they are shown and selected ("<n> clip(s) selected - dropped from Explorer" or "<n> files dropped from Explorer"). "“<name>” matches <n> clips and none is the same size - showing all of them." Not found: "“<name>” is not in the library." or "<n> of those files are not in the library.", then "Add the folder they live in with ＋ folder in the Source pane, then Rescan."

### A clip already in its folder counts as in place

A clip already sitting inside a destination folder (on the NAS, in any project folder) counts as assigned to that folder without anyone assigning it. Everywhere the Sorter counts, filters or badges, it is "in place": nothing is written for it, it is never moved, and Unassign has nothing to remove. It is never counted as work left to do. A clip still on a card is never in place.

### Folder names are cleaned the way Windows stores them and match existing folders without case

Every folder name a person gives, typed or bound, is cleaned the same way: "\" is read as "/", spaces at the ends, empty parts and double slashes are dropped, and trailing dots and spaces are removed from each part (Windows would drop them silently, so "Day 1." becomes "Day 1"). Refused as invalid ("invalid dest", or the plainer message where a name is typed): an empty name; a name starting with a drive letter or a network path ("//"); a part made only of dots; a part containing < > : " | ? * or a control character, or broken characters; a part that is empty once trimmed; and a part whose name before its first dot is a name Windows reserves (CON, PRN, AUX, NUL, COM1 to COM9, LPT1 to LPT9).

Each part that matches a folder already on disk, or already planned, differing only in letter case, takes the existing spelling (an exact match wins), so "ff5/b-roll" lands in "FF5/B-roll" and the NAS, where letter case matters, never gets a second folder differing only in case. A new part keeps the first spelling used in the same plan. Names with accents or in non-Latin scripts are kept exactly, and clips moved into such a folder land there and are shown there.

### The destination tree shows real, planned, suggested and held folders

"Destinations" shows the destination root with "<root path>  ·  <n> clips · <size>" and "+ folder" ("New folder at destination root"). The root is always open; other folders open with their arrow. Folders sort naturally (numbers in order, case ignored), and names match ignoring case, keeping the spelling of the existing folder.

Every planned folder, every folder a clip is assigned to, every folder an event is bound to, every folder a suggestion points at for an unassigned clip, and every folder known to hold clips appears in the tree even when it is not on disk. Counts include subfolders: assigned, "+<suggested>", and size (on hovering, "<n> assigned directly here, <n> including subfolders" or "nothing assigned yet", plus "<n> suggested (not accepted)"); filed clips not yet loaded are counted from the server's summary. A folder is one of:

- on disk;
- planned ("(planned - created by the next move)");
- suggested only, existing only because suggestions point at it ("(suggested only - nothing is committed here yet; accept the suggestions to make it real)"), which cannot be renamed, moved or removed;
- held for someone not filmed yet, greyed and not made on disk until a clip lands in it ("(no footage yet - held for them, and not created on disk until a clip lands here)"), reading normally once a clip is assigned or suggested to it;
- held and filed elsewhere: a held folder whose person's footage is filed in another folder of the same name, greyed, showing "→ filed in <episode>" (click to jump there; on hovering "(their footage is filed under <dest> - <n> clips. Nothing is created here.)").

Clicking a folder shows the clips assigned or suggested to it or any folder beneath it, and opens it if it has subfolders; clicking again clears; clicking the root clears the folder filter. A folder with a gap in its footage carries ⚠ (see "The missing-footage checks").

- Name and search words: Destinations. Search words: destination tree, folders, sorted footage, episodes, interviewees.

### Footage is filed in day-and-camera time folders

Under the folder it is assigned to, each clip is filed in a time folder per day and camera, named "<YYYY-MM-DD> <HH.mm>-<HH.mm> <camera label>", for example "2026-08-09 08.54-15.06 A-CAM" (a dot instead of a colon, which Windows forbids). Clips are grouped by folder, camera label and local day; the range runs from the earliest to the latest recording time of that group. No time folder is made for clips kept in the card's layout, image sequences, stills, other files, clips with no recording time, or clips with no camera label: those land straight in the assigned folder. Card copies into the NAS's staging folder always use time folders.

An existing time folder for the same day and camera that already holds any of the group's clips (by the record, or by name and recorded size among its own files) is reused under its existing name and never renamed, even when the new range is wider; the person is warned "range widened: <fresh name> reused <existing name>". A folder with exactly the new name that holds none of the group's clips belongs to another shoot, so the new one becomes "<name> (2)", "(3)" and so on, in the order the folders are named. Every existing folder name, "(2)" suffixes included, is kept exactly.

Before anything moves, the person sees, under each open destination folder, each time folder its assignments imply, with "<n> clips · <size>", "(existing, will merge)" when it exists already, and on hovering its path, "merges into <folder>", its camera and day, and "not created yet - the copy makes it". Clicking one selects its clips ("<n> clip(s) heading for <name>"). Nothing can be dropped on one. What is on disk is read again at least every 30 seconds, and at once after a change to assignments, a move, a card copy, a scan or an audit.

- On its own: each time folder's name and range, from the clips' recording times and camera labels, reusing an existing folder that holds any of them.
- By hand: a person renames a time folder in the plan like any other folder, or assigns clips with the card's layout kept to have none; a name set by hand is never changed by a later pass.
- Setting: Time folders. Does: whether sorted clips are filed in per-day, per-camera time folders under their folder. Default: on. Who: an admin. Applies to: the site. Search words: time folders, day folders, camera folders, date range.

### Planning every episode's folders and every interviewee's folder at once

Two actions fill the plan from the studio's data, each with a rehearsal first that lists what it would add and changes nothing.

- **Plan every episode's skeleton**: every episode folder and every standard subfolder is added as a planned folder. It reports "<n> episodes x <m> folders = <k> planned folders", how many were new, any rejected names, and that they are created on disk by the next move.
- **Plan a folder for every interviewee on the roster**: every person on the roster gets a held folder "<Chinese> <English>" in their episode's Interviewees folder (shown greyed, not created until a clip lands). The episode's Interviewees folder is the one that already holds clips (shortest path wins), else any such folder (flagged "nothing is filed here, check this"), else the standard place; an admin can pin one per episode. A person already filed under that episode (a folder holding clips whose path contains their Chinese name, or their English name of 5 or more characters) is left alone, and a near-identical existing folder is reused. A person on the roster of several episodes shows greyed in the others. It reports people, already filed, to plan, skipped rows, folders per episode, "<n> folder(s) still empty - held as placeholders: shown greyed out in the tree, and NOT created on disk until a clip lands in one.", and "No assignment was touched." It needs a roster (an empty one is refused) and the episodes.

- Who: an admin.

### The missing-footage checks

The checks carry a count of everything still open (hidden at zero), headed "<n> to look at". While filed clips are not loaded the count reads "<n>+" ("At least this many: open the tab to load the destination and check the rest"), with "These checks need the destination's clips, which are not loaded." and Load them, or "Loading the destination's clips to finish these checks…". Opening the checks loads them.

**Interview folders short of footage.** Every folder under an "Interviewees" folder is checked. It is short if it has no video ("no video"), fewer than two distinct camera bodies ("no second camera"), or no sound ("no sound"). The gap clears whenever the folder holds two cameras' clips, or a matching recorder file, whatever its subfolders are called. Camera bodies are told apart by the model the file records, then by being a Blackmagic RAW file, then by a camera label, and otherwise by the card folder with dates, offload time ranges (like "15.56-17.17") and the camera's own card folders ignored. A folder that also holds filed clips not yet loaded is never flagged. Each row: the folder (its full path on hovering), one tag per gap, "<n> clips · <n> camera(s) (<bodies>) · <n> sound" or "· no sound", and Show (filters to that folder). With none: "Every interview folder has A-CAM, B-CAM and sound." A short folder also carries ⚠ in the destination tree ("Missing <a second camera, sound…> - see the Missing tab") and a warning in its clips' details, "⚠ <folder> has no <gaps>", with clip, camera and sound counts.

**Shoots with no footage.** Timed (not all-day) events with no clip recorded from 30 minutes before the start to 30 minutes after the end, and not covered by filed clips. Newest first: title ("(untitled)"), "no footage", start date and time, "→ <folder>" when bound or read from the title, and Dismiss ("I know about this one - stop listing it"; a failure shows the reason or "Could not save that"). With none: "Every scheduled shoot has footage against it." A Dismissed list shows each dismissed event with Restore.

**People with no footage.** People on the roster whose Chinese name, or full English name of 5 or more characters, appears in no assigned, filed or suggested folder path, grouped by episode, most missing first: "<episode>", "<n> not shot", then each name. A name heard on some recordings is marked "♪" ("Heard on <n> clip(s) - the interview exists, it is just not filed"). With no roster, a note says none is loaded and how an admin loads one. With nobody missing: "Everyone on the roster has footage."

**Gaps in a camera's numbering.** For each camera, a gap in its clips' running numbers is listed with the dates of the clips either side, so a card that was never offloaded is noticed.

- Who: anyone signed in; dismissing and restoring a shoot too.
- Name and search words: Missing footage. Search words: missing, gaps, no sound, second camera, not shot.

### Pick a day shows a month of what was shot and what was scheduled

The month opens on the day filter's month, or the last day with footage, or the current month ("Nothing scanned yet." when there is no footage and no events). ‹ and › change month; Latest shoot jumps to the month of the last day with footage. A Monday-first grid: a day with footage shows its clip count and total size and can be clicked; a day with events but no footage shows "no footage"; up to three event titles per day, then "+<n>". On hovering: the date, "<n> clips · <size>" and the cameras, or "no footage", then each event's time and title. Filed clips not yet loaded are counted from the server's summary. Clicking a day sets the day filter, closes, and says "<n> clip(s) on <date> · <event titles>". The footer shows "<n> day(s) shot this month · <n> clips", All dates (clears the day filter) and Close.

### A search also shows the matching shoots and folders

Typing a search shows, above the clips, up to 12 matching shoots and folders as cards, events first (by start) then folders (by path), with "+<n> more - narrow the search" beyond.

- An event card shows "Event", its day and time range (no time when all-day), title ("(no title)"), place, the folder it feeds ("Bound to <dest>", "Read from the title: <dest>", or "no folder bound": "Bind it on the Events tab"), "<n> assigned", "<n> suggested", and "not counting the destination" when filed clips are not loaded ("The destination's clips are not loaded: open All clips to count them too"). It matches on title, place or folder. Clicking filters the clips to that event (clearing a folder filter); clicking again removes it.
- A folder card shows "Folder", the span of recording days ("no dates", one day, or "<first> → <last> · <n> days"), its name and full path, the first event feeding it and "+<n>" more (on hovering, each with date, time, and whether bound or only at the same time), "<n> clip(s)", and "dates need the destination loaded" when relevant. It matches only on its own last name (so "Interviewees" does not return every interviewee). Clicking filters to clips assigned or suggested to it or below; clicking again clears.

### The card tracker lists which cards were used each day and the likely shoot

Footage taken in with no card record: up to 40 rows of day, card, "<n> clips → <folders>", then "… and <n> more". Recorded card use, one block per day ("Nothing recorded yet."): the cards used ("<card> recorded <local date time> by <who>", backed up since or not yet), each with "<n> clips ingested → <folders>" or " (staging)"; then that day's main events (others as "+ <n> all-day / recurring event(s)"), each with its time, title (click to filter to that event, again to clear), "★ likely" ("The only shoot on the calendar that day with a known destination") or "☆ likely" ("The only timed event that day - no destination known for it"), and its folder. "Nothing on the calendar that day." Dismissed shoots are left out.

- On its own: the likely shoot for a day's cards, from the only shoot that day with a known folder, or the only timed event.
- By hand: a person assigns the cards' clips to any folder; the "likely" mark is only shown, never applied.

### Every change to the sorting plan is kept, with who made it

The sorting plan is which clip goes to which folder, which event points at which folder, which folders are planned or held, and which shoots are dismissed. Each change is all or nothing: if it cannot be saved, the plan stays as it was and the person is told. Each change is recorded with the time, the person, what was done and its detail, and a dated copy of the whole plan is kept after every change; the newest 200 copies are kept. Rescans, restarts and updates keep every assignment and plan a person has made.

### Footage for client drives keeps each shoot day on one drive

When footage is put onto client drives, each shoot day is given to one client drive and never split across two, and no clip is placed on two client drives.

#### Lessons

- Met: SRT-111, SRT-112, SRT-113, SRT-114, SRT-115, SRT-116, SRT-117, SRT-118, SRT-119, SRT-120, SRT-121, SRT-122, SRT-123, SRT-124, SRT-125, SRT-126, SRT-127, SRT-128, SRT-129, SRT-130.

## Moving footage on the NAS

### Looking at footage never changes it, and only the Sorter's moves of sorted clips move it

Looking through folders, drives and cards only reads: it lists folders, reads file sizes and dates, reads the start of camera metadata files and sound files' headers, and may ask a video file for its recording time. It never writes, renames or deletes anything where it looks. A copy from a card only adds files (see part 1, "Copying a card").

The only thing that moves footage is the Sorter moving a clip that has been sorted into the folder it was sorted to (see "Sorted footage moves into its folder on its own"), or a person moving it somewhere else or putting it back. A suggestion nobody has accepted, and a sound match left waiting for a person, sort nothing and so move nothing. The Sorter always knows who is signed in from their sign-in, and nobody can claim to be someone else. Every move is recorded with the person whose sorting or hand move led to it, and every change made in the Sorter carries the dashboard's protection against another site acting on a signed-in person's behalf.

### Where each file of a sorted clip goes

When a clip has been sorted, its files go to its folder like this:

- an image sequence moves as one whole folder;
- with the card's layout kept, each file keeps its path below its source folder;
- by the studio's convention (the default), main files go straight into the folder (or its time folder), a proxy from a folder named Proxy or Proxies or a Sony card's proxy folder goes into a "Proxy" folder inside it, keeping any deeper path, and the small file a Blackmagic camera writes beside each clip, and a grade file beside its original, stay beside their clip (Resolve reads the grade there);
- with time folders on, into the time folder under the assigned folder.

Every planned folder is created, even with nothing moving into it, so an episode's skeleton is made empty; held folders wait until a clip lands in them. The leftover files of a half-moved clip go with its next move. A clip that is only on a camera card in a reader is left to the card copy. A card's paths reported by a Windows computer are understood by Windows rules wherever they are handled.

A file whose destination already holds the identical file (same size, and for files of 64 MB or less the same content) is not moved and is listed as "already there"; of two identical files headed for the same place (the same card staged twice) only one moves, and the other is listed. Anything not identical (a different file already at the destination, or two different files for one name) is a **collision**; an unreadable file counts as not identical. A collision is never resolved on its own.

Under each destination folder a person can see what is headed for it before it arrives: assigned clips not yet there are drawn dashed and dimmed, and the time folders they will make are shown (see "Footage is filed in day-and-camera time folders"). There is no deliberate wait before a move: a sorted clip moves as soon as its checks pass, so what a person sees as "about to move" is whatever is still waiting for its turn or for its checks.

- Setting: Layout inside a destination folder. Does: whether a clip's files are laid out by the studio's convention or keep their layout from the card. Default: the studio's convention. Who: an admin. Applies to: the site. Search words: layout, proxy folder, convention, keep layout.

### Every move is checked before it starts

Before any file of a sorted clip moves, the Sorter checks, on its own and without changing anything: both paths are complete and clean; source and destination differ; a folder is not moved into itself; every destination is inside the destination tree; no two moves share a source or a destination; the source exists with exactly the size the record holds (a folder's size ignores system housekeeping files); the destination does not exist; and the destination's parent is not a file. Paths may hold brackets, spaces, Chinese characters and be very long.

A clip fails the check, and is held back whole, for any of: "a file sits where a folder is planned"; "source missing" (or "recovered" when an interrupted earlier move clearly completed it, which counts as done); "expected a folder"; "source unreadable"; "size changed: <src> (<n> bytes, the record says <m>)"; "destination occupied"; a collision; a proxy that would be left behind (see "Moves in the folders editors sync reach every editor's computer"); an assigned clip that is no longer in the scan ("no longer in the scan: rescan, then sort it again"); or a destination on a different disk ("on a different filesystem: refused, nothing is ever copied"). A move is always a rename on the same disk and never quietly becomes a copy. A clip is never moved in part.

### Sorted footage moves into its folder on its own

As soon as a clip is sorted (assigned to a folder by a person, a suggestion accepted, a recording's place decided, or a destination folder renamed or moved with footage under it), the Sorter moves its files into that folder by itself. Nothing waits for an approval. Moves run one at a time, in the order clips were sorted; a clip sorted while a move is running waits its turn.

Every move keeps these promises:

- **It never deletes, never copies over and never overwrites.** An existing file at a destination is never replaced, a source folder emptied by a move is left in place and listed, and nothing is ever removed.
- **It is checked just before and just after each item.** Just before, the destination is still free and the source still there at its recorded size; just after, the destination exists with the right size and the source is gone.
- **A clip that clashes is held back whole and shown to a person, while the clean clips move.** Every held-back clip is listed in "Held back" with each reason and its clashing files (up to 500 shown, with the total), and stays exactly where it is until a person decides: sorts it elsewhere, or clears the clash and presses Try again.
- **Nothing moves while the NAS looks wrong.** No move starts while the NAS's footage tree cannot be reached or read, while its last walk was unfinished or treated as a bad scan, or while what is on disk differs from what the checks found ("the disk changed since it was checked: nothing was moved"). The Sorter shows "Moves paused: <reason>" and carries on by itself once the NAS looks right again.
- **Every move is recorded and can be seen and undone by hand** (see "What was moved can be seen, moved elsewhere or put back").

While a move runs, the activity panel and the Sorter show "Moving <n> clip(s) into <folder>", "<done> of <total> · <size>", updated about every second. When it ends: "✓ Moved <n> item(s), <size> · <n> source folder(s) now empty (left in place). Verified at the destination.", with moved, skipped, recovered, size and folders created, and the NAS is walked again. Every count, list and the destination tree follow at once.

The first failure stops that run and undoes nothing. The failed clip is held back with which item failed and why, how many were completed and not attempted, and "Nothing was deleted or overwritten."; what had already moved stays where it was recorded as moved. The rest carry on by themselves once their checks pass again.

- On its own: which clips move and when, from their being sorted (by a person, by an accepted suggestion, or by a decided recording) and their passing every check.
- On its own: where each file lands, from the clip's folder, its layout and its time folder.
- By hand: a person sees every move and moves any clip somewhere else or puts it back (see "What was moved can be seen, moved elsewhere or put back"); a place set by hand is never changed by a later automatic pass.
- Who: anyone signed in sees moves and held-back clips; the move itself needs nobody.

### What was moved can be seen, moved elsewhere or put back

"Moves" lists every move, newest first: when, the clip, from where, to where, why (whose sorting or hand move led to it), and its check result. A clip's details show its moves too. From either place a person can:

- **Move it elsewhere**: sort it to another folder; it moves there on its own with every promise above.
- **Put it back**: return it to where it was before that move, with the same checks; a clip put back is marked as placed by hand there and is never moved again on its own until a person sorts it again.
- **Try again** on a held-back clip, once its reason is cleared.

A place set by hand (a clip sorted, moved elsewhere or put back by a person, or moved by hand outside the product and adopted) is never changed by a later automatic pass.

- Who: anyone signed in.

### An interrupted move is picked up where it stopped

Every move is written down before and after each item, so a power cut, a crash or a restart mid-move loses nothing. When the product comes back it rescans, shows which files moved and which did not, and a move is never left showing as running. The move then carries on by itself, skipping what already moved, and an item interrupted after its file arrived is recognised as done.

### Moves in the folders editors sync reach every editor's computer

Footage in the folders editors' computers sync is moved so that every editor's copy follows (see Proxies and file moves: Moves that reach every computer). A proxy there moves only with its original, to exactly the planned place beside it; a plan that would leave a proxy behind holds that clip back: "a proxy moves only with its original (Proxy/<same name> beside it, to exactly the planned place), so <src> would be left behind. Move it by hand, or plan it without this proxy". When the server cannot make every editor's copy follow, the move of such footage is refused: "inside Projects, so every editor's copy must follow; this server has no way to make that happen for it".

### A move is checked afterwards and a list shows where everything went

A check judges a move after it ran: each destination must exist with the recorded size and its source must be gone ("missing at destination", "size differs at destination", "still at the source too"; up to 500 listed). A check after one move judges only that move. A person can also check every move ever made, or those since a given day. A file moved again later, or under a folder later moved by hand, is followed to where it is now (up to 64 moves along) and counts as verified; only files truly gone are reported. It ends "All verified - every moved item is at its destination with the expected size and no source remains." or "<n> problem(s)", lists the source folders now empty, and with nothing ever moved says "Nothing has been moved yet."

It also gives a list, readable in a spreadsheet program with Chinese names shown correctly, of every original path and where it went.

- Who: anyone signed in.

### Footage moved by hand is noticed and the plan follows it

After every scan, without touching any file, the Sorter works out what happened to clips moved or renamed outside it (dragged in Explorer, copied onto the NAS, a folder moved to the right episode):

- a clip whose assignment points at a place it has left, found at exactly one other place (or exactly one in the destination tree), keeps its assignment ("re-keyed"); none found is "gone", several is "ambiguous", and both are left untouched and never guessed;
- a clip now inside the folder it was assigned to, or a time folder of it, is marked done ("found in place");
- a clip found elsewhere in the destination tree that was never filed stays a re-file to do;
- a clip already filed that a person then moved elsewhere: if another copy is still in its assigned folder, the moved one is a duplicate, counted and left alone; otherwise the hand move wins and its new place becomes its folder, remembering where it came from and when ("moved by hand, adopted");
- a clip still in staging keeps its plan;
- when every clip of one folder went to the same other folder and none is left behind, the folder was renamed: its planned folders, held folders, event bindings and assignments follow it, and later checks of earlier moves follow it too.

The person sees one line, for example "3 re-keyed, 2 found in place, 1 moved by hand, adopted, 1 folder move(s): A -> B, 1 duplicate copies left alone, 4 gone, 1 ambiguous".

- On its own: whether a clip moved by hand is the same clip, a duplicate, or a renamed folder, from the record's identity of the recording.
- By hand: a person assigns the clip again anywhere; an assignment set by hand after a hand move is never changed by a later scan.

### Rescan reads every source and destination again

Rescan (ignored and disabled while one runs) shows "Scanning… <n> clips", updated about every second, until it ends (the page stops watching after one hour). Then everything reloads: "Scan complete - <n> clips · <size>". If the scan found footage moved or renamed outside the Sorter and followed it: "Moved outside the app: <what>". A failure shows "Scan failed: <reason>". Moved clips show at their new place and can be sorted again, and every count and the destination tree follow what is on disk.

- Who: anyone signed in.

### A new destination folder is planned without anything being made on disk

＋ on any folder, the root included ("New folder inside <folder>"), opens a "New folder name…" box; Enter or leaving the box creates, Escape cancels. Refused: any of \ / : * ? " < > | ("Folder name cannot contain \ / : * ? " < > |"); CON, PRN, AUX, NUL, COM1-9, LPT1-9 ("“<name>” is a reserved Windows name and cannot be a folder."); only dots and spaces ("That folder name is only dots and spaces."); a name that exists in any letter case ("That folder already exists."). Trailing dots and spaces are removed with "Trailing dots/spaces removed - Windows would drop them anyway." Otherwise it appears at once as planned: "Planned folder: <path>"; a failure shows "Could not create folder: <reason>" and the tree reloads.

Many folders can be planned at once (duplicates differing only in letter case skipped, invalid names listed back). A folder can instead be planned as a held folder: shown greyed, and not created on disk until a clip is assigned into it. A planned folder is created on disk by the next move, even when nothing moves into it.

- Who: anyone signed in.

### A destination folder is renamed or moved in the plan

Rename: ✎ ("Rename <name>  (F2, or double-click the name)"), double-clicking the name, or F2 on the last-clicked folder turns the name into a box with the name selected; Enter or leaving saves, Escape cancels (Enter is not taken while a character is being composed). Move: dragging a folder onto another folder, or onto the root; not into itself, its own subfolder, or where it already is. Both work on real folders: on disk, planned, or with something assigned or bound to them.

The folder's planned subfolders, held folders, assignments and event bindings follow it, and a filter on the folder follows it. Success: "Renamed to <name>  (<n> clip(s) followed it)" or "<name> → <target or destination root>  (<n> clip(s) and <n> subfolder(s) followed it)". When the old folder exists on disk and is empty, it stays: "The empty folder is still at the old place on disk - nothing was deleted. Remove it yourself if you want it gone: <path>". When the old folder holds footage on disk, its clips are sorted to the new place and move there on their own, with every promise of a move (see "Sorted footage moves into its folder on its own"); the old folder, once empty, is left in place.

Refusals, in order: "that is not a usable folder name"; "a folder cannot be moved inside itself"; '"<from>" is not a folder this app can move.' (nothing refers to it and it is not on disk); '"<to>" already exists' (a planned folder of that name); '"<to>" already exists on disk and is not empty'. Moving a folder onto itself does nothing and says so. Any other failure shows its reason, or "Could not rename that folder" / "Could not move that folder".

- Who: anyone signed in.

### A folder is taken out of the plan and nothing on disk is deleted

✕ ("Remove this folder from the tree (nothing on disk is touched)") first shows what removing would take, for the folder and everything beneath it. If nothing in the plan refers to it: "“<dest>” only exists on disk. This app never deletes inside your projects - remove it in Explorer, then reload." or "Nothing to remove here." Otherwise "Remove folder" lists "<n> planned folder(s) dropped from the plan", "<n> clip(s) unassigned - back to unsorted. The footage itself is not touched.", "<n> calendar binding(s) cleared", and, when it is on disk, "This folder also exists on disk and holds <n> file(s)" (counted up to 2,000) or ", empty", with "It stays where it is - this app never deletes inside your projects. Remove it in Explorer if you want it gone." Cancel or Remove. After: "Removed <dest> - <n> clip(s) unassigned, <n> binding(s) cleared", and "The folder is still on disk - nothing was deleted there." when so. A failure shows "Could not remove folder: <reason>" or "Could not check that folder".

- Who: anyone signed in.

### A clip filed in another project can be shared into this one

A clip already filed in another project can be shared into this one as a link to its folder, never as a second copy, and only when a person clicks to do it.

- Who: anyone signed in.

#### Lessons

- Met: SRT-131, SRT-132, SRT-133, SRT-134, SRT-135, SRT-136, SRT-137, SRT-138, SRT-139, SRT-140, SRT-141.

## Placing sound recordings

### The Sorter proposes where each sound recording belongs

Field recorders (lavalier transmitters, handheld recorders) often carry a wrong date, because the recorder's clock was reset, so the calendar alone cannot place their files. For every sound recording, and especially those the calendar cannot place, the Sorter weighs every clue it has and proposes a folder (an interviewee's folder, or a shoot's folder) and the recording's true start. It never files anything by itself.

The clues, each proposing a folder with a score:

| Clue | Score |
|---|---|
| An identical file (same recorder name and size, and length within 2 seconds) already filed in or headed for a folder | 0.92 in an interviewee's folder ("An identical file is already filed here: <path>"), else 0.3 ("An identical file was also copied to <path>") |
| What is said matches one of the studio's interview transcripts, compared in runs of four words (each Chinese character counts as a word), counted from 6 % and 25 shared runs | 0.85, rising to 0.95 from 25 % and 120 shared runs; 0.55 from 12 % and 60 runs; else 0.3. The top 4 transcripts are shown: "<n>% of what was said is in the transcript of <name> (<episode>)" |
| A roster name heard on the recording | 0.72, or 0.35 when only part of an English name was heard; a name on two episodes gives a 0.4 note with no folder. The quote (up to 90 characters) and its time are shown |
| Someone introducing themselves | 0.6 with a folder, 0.3 without ("Said: …"; up to 6 introductions, quotes up to 120 characters) |
| The calendar's suggestion, when the recording has a believable date (a year from 2024 to 2027) | 0.7 if high confidence, else 0.35 |
| The recorder's clock overlaps the clips of a shoot folder (the recording's span padded by 15 minutes; clips that started up to 4 hours earlier count), ranked by real overlap, then padded overlap, with clip and camera counts | 0.8 when exactly one folder really overlaps, else 0.4 |
| Its sound matches the cameras' sound in a shoot folder | 0.6 plus half the best peak, at most 0.99 |

A second clue for the same folder adds 0.08 to its best score, up to 1. Confidence is high from 0.75, medium from 0.45, otherwise low.

**Matching sound to the cameras.** From the camera clips overlapping in time that have sound and are at least 8 seconds long, up to 24 spread over the recording's span are tried: 90 seconds from each clip's middle, searched within 20 minutes of where the time estimate expects it. A match is strong at a peak of 0.35 with a margin of 0.05 over the best rival more than half a second away. The recording is placed when at least two strong matches from one camera agree on its start within 2 seconds, or when one match reaches a peak of 0.75 and beats the next candidate by a margin of 0.25. Its true start is the middle of the agreeing matches, on that camera's clock, and the folder is the commonest among them. Weaker agreement is recorded as weak and does not place it. Both channels of one take always stay together in one folder. When the recorder's clock as read finds nothing, whole-hour time zone shifts are tried in turn (a recorder on Kyiv time against cameras on Taiwan time is 5 hours out), and the shift used is noted. Only the studio's own camera clips are compared, never downloaded video. A recording with no believable date and no estimate gets no time or sound clue; an unreadable file is noted as an error and never stops the rest.

**Words.** Chinese is compared in one script, so the same speech written in Simplified on one side and Traditional on the other still matches. The interviewee folder for a transcript match is the folder whose name carries the person's Chinese name whole, or two parts of their English name, or one English part of 4 or more letters that is not a common Taiwanese surname; the evidence notes "folder from the roster", "but two folders carry that name", or "no folder carries that name".

**Filed recordings that disagree.** A recording already filed is flagged as disagreeing when its strongest confident clue (an identical file, or a transcript) points at a different folder, unless an identical copy is also filed where it sits. Before any recording is reported missing, every unassigned recording everywhere is searched by its content.

New interview transcripts are taken into account within about 15 seconds of appearing.

- On its own: each recording's proposed folder, from the clues above.
- On its own: each recording's true start, from matching its sound with the cameras', else its recorder's clock.
- On its own: whether a filed recording disagrees with where it is filed, from identical files and transcripts.
- By hand: a person sees every candidate with its evidence, sets the folder and the start, and approves, rejects or reassigns (see "A person decides a recording's folder and start"); a decision set by hand is never overwritten by a later pass.
- When Timeline Cards is off: the studio's interview transcripts are not compared; every other clue still works.

### Every sound recording is listened to for names and introductions

Every sound recording that arrives is listened to on its own, as heavy work on one of the studio's computers able and free (see Work shared out across the computers), with no one starting it. The whole recording is used, not only its start, so a name said late is still found. Recordings with an identical copy elsewhere go last, otherwise smallest first. Work is kept as it goes: a recording already heard is not heard again unless asked, and a file that moved (same name, size, and length within 1 second) reuses what was heard. Missing files and files under 5 seconds are skipped.

A roster person's Chinese name (3 or more syllables) matches when heard with the same sounds, even written with other characters; an English name matches whole, or by two of its parts of 5 or more letters; a single usable part is a weak "partial" match; a name in two episodes is marked ambiguous. Self-introductions are recognised from "我是", "我叫", "這位是", "我們今天訪問", "my name is", "I am called", and "we are" followed by an organisation. A name only mentioned, not used to introduce someone, is never credited as the speaker. Guesses are marked as guesses, and recordings that cannot be attributed are reported as such. Each finding keeps its quote and its time. Every recording is transcribed in full, with its language identified and speakers told apart, and camera clips with at least 20 seconds of sound are transcribed too. A recording and a camera clip that share enough of their words (runs of 4 words, or 6 characters in Chinese and Japanese; at least 3 runs and 5 % of the shorter) give the recording's folder and start, which is then confirmed by matching sound around that start against every clip in that folder. Listening never assigns anything.

- On its own: who is named or introduces themselves on a recording, from what is heard.
- By hand: a person reads the transcript, plays any line and assigns the recording anywhere (see "One recording's detail shows who it could be and plays it against the cameras").

### Each recording gets one verdict

Every recording gets one verdict:

- **duplicate**, with the kept copy and why;
- **not field sound**: broken, music, or not a 32-bit file, with the reason;
- placed by sound: **matched** (a loose recording), **confirmed** (a filed one already in that folder or below it), or **misplaced** (a filed one elsewhere);
- placed by time: **time-only** when exactly one folder overlapped, else **ambiguous** (a filed recording in that one folder is confirmed);
- **inferred**, when only the recorder's clock places it;
- otherwise **unmatched**.

Transcript matches and weak sound matches do not change the verdict on their own. The destination is the shoot folder's Audio folder (not for a confirmed one), unless a person's decision names another. A report gives the count and hours per origin (loose or filed) and verdict.

- On its own: each recording's verdict, from the clues.
- By hand: a person's decision (approve, b-roll ambience, reject) stands over the verdict and is never undone by a later pass.

### A sound suggestion appears only where the calendar says nothing

On the main clip list, a suggestion from sound, marked with a note symbol, is offered for a sound clip that is not assigned, has no calendar suggestion, whose top candidate has a folder and is not low in confidence (medium shows as low), and that is either filed nowhere or filed where the sound confidently disagrees. It shows the folder, high or low, the clues that point there, the moment something was heard and what, and a reason of up to 300 characters.

### The audio worklist says whose interview is on each recording

The audio worklist carries a count of the recordings filed where the audio disagrees plus the unfiled ones with a likely match (hidden at zero), and ↻ ("Re-read the transcripts and re-score"). It refreshes about every 30 seconds while open; a failure shows "Audio report unavailable: <reason>". With nothing or several selected it shows "<n> of <m> audio clips heard", how many interview transcripts it can compare against, and the sections "Filed where the audio disagrees" ("The folder each of these sits in is contradicted by an identical filed copy or by the transcript itself."), "Not filed yet" and "Filed, nothing contradicts it", each best match first, then by name. A row shows the name, length, "transcribing…" / "names only" / "<n>% heard", "Filed in" or "Assigned to" <folder>, and "Sounds like" (disagreeing) or "Looks like" <name> with confidence and evidence, or a note that nothing matched and no name was heard. Clicking a row shows and selects that clip. Empty: "Nothing needs a look." or a note that no transcripts exist yet. A footer says when recordings were last listened to.

It can be filtered by verdict, each with its count (matched, misplaced, time-only, ambiguous, inferred and unmatched shown at first; confirmed, duplicate and not field sound hidden), by loose and filed, loose only or filed only, and by name or folder, with "<n> shown". "Approve visible with score ≥" (default 0.85, in steps of 0.05) approves every visible matched or misplaced recording at or above that score that has a folder and no decision yet, after "Approve <n> matches?" (or "Nothing visible at that score."). Recomputing the verdicts can be asked for.

- Who: anyone signed in sees it; approving needs an admin.
- Name and search words: Audio worklist. Search words: sound, recordings, whose interview, field audio, recorder.

### One recording's detail shows who it could be and plays it against the cameras

Opening one recording shows:

- **Clip**: "<name> · <duration> · <size>", its path, recorder and counter, channels, bits, the recorder's clock and note, the true start, and "goes to" folder. **Heard**: "<scanned> of <duration> · <language>", "names only (no full transcript yet)" or "not yet", and whether it was taken from a moved copy. **Assigned / Filed in** ("unassigned · suggested <folder>").
- A player of the clip's proxy (loading when played, keeping its place across a redraw); Assign to…, Unassign, Show in destinations, Open in Explorer.
- A disagreement: "⚠ Filed under <folder>, but this sounds like <name>", "From: <evidence>. Assign it below to queue the re-file."
- **Who this could be**: every candidate with its name, confidence (score to two decimals), evidence, folder and Assign ("✓ here" when already there), or Pick folder… when no folder carries the name; each piece of evidence quoted with "▶ <time>" to play from there. Empty: a note that nothing matched and the transcript should be read, or "Waiting for the transcript."
- **Why**: per candidate folder, the time evidence (estimated start, the clock anchors and offset, a table of shoot folders with overlap, padded overlap, clips and cameras) and the sound evidence (how many clips agree, the start, whose clock, best peak and margin, a table of the matches tried). "Nothing found anything yet." when there is nothing.
- **Timeline**: the recording as a bar with every overlapping camera clip, one lane per camera, the chosen folder's clips set apart and a strong sound match marked, each with its name, start and length on hovering; "No time estimate, so there is nothing to draw." without a start.
- **Listen**: clicking a camera clip plays 30 seconds of it (from up to 30 seconds in, around its middle) and the matching 30 seconds of the recording together; a raw camera clip with no proxy says it cannot be previewed; "Play recording" plays 120 seconds of the recording.
- **Who talks when** (when at least two five-minute windows have a match): cells along the recording showing the best match, "<from>-<to>: <name> (<n>%)" or "no match" on hovering, click to play from there, with a legend.
- **Transcript**: "Find in transcript…" (kept between clips), every line with its time (to a tenth of a second) to play from, its window's language, evidence lines highlighted, at most 4,000 lines drawn. "No transcript for this clip yet.", "Nothing in the transcript says that.", "The transcript is empty - silence, or room tone.", "Transcribed up to <time> of <time> so far."; "Could not read this clip: <reason>".
- **Copies**: the other sound clips with the same name and size and, where known, length within 2 seconds, each with where it is and whether it is assigned.

Nothing here assigns on its own.

- Who: anyone signed in.

### A person decides a recording's folder and start

The decide section has a folder box suggesting shoot folders as the person types (up to 200, oldest first, with clip counts); buttons nudging the true start by -10 s, -1 s, -0.1 s, -1 frame, +1 frame, +0.1 s, +1 s, +10 s (a frame is 1/30 s) with the adjusted start shown; and "Re-check waveform here", which searches the clips within 60 seconds of the hand-set start (optionally in one folder only, within a minute either side) and reports a match with how many clips agree and the peak, offering "Use this start", or "No strong match here (<n> clips compared, best peak <p>)", or "No clips with sound to compare here." Then Approve, "B-roll ambience (no picture)", Reject (no folder), Clear decision, and a note. After a decision the list reloads and the next undecided visible recording opens. Errors are shown on the page.

- Who: an admin decides.

### Approved recordings are filed beside their video, and duplicates are set aside

An approved recording is filed in the Audio folder inside its shoot's folder, or the folder the person named, moving there on its own like any sorted clip, with every promise of a move (see "Sorted footage moves into its folder on its own"). A loose duplicate is set aside in the duplicates folder, never deleted. Skipped: a recording already in that folder ("already there"), or one with an identical copy already at the destination. Held back: a recording whose shoot folder is itself still unsorted goes with its shoot ("the shoot is itself still unsorted; goes with it"); duplicates are never held. A different file with the same name at the destination is never overwritten: the recording is filed with "_1", "_2" and so on added to its name.

- Who: an admin decides a recording's place; the move then needs nobody.
- Setting: Name of a shoot's sound folder. Does: the folder inside a shoot's folder that approved recordings are filed in. Default: "Audio". Who: an admin. Applies to: the site. Search words: audio folder, sound folder, recordings, filing.
- Setting: Where duplicate recordings are set aside. Does: the folder loose duplicate recordings are moved into instead of being deleted. Default: a "Duplicates" folder in the NAS's staging folder. Who: an admin. Applies to: the site. Search words: duplicates, set aside, recordings, quarantine.

### Field recordings not yet on the NAS are found on every computer and drive

From the record of every copy, the Sorter lists the field recordings that exist on the studio's computers and drives but not yet on the NAS: how many, how many are unique, how many hours, and the 40 biggest groups by computer and folder. A field recording is an unbroken 32-bit WAV file at least 30 seconds long that is not named like music. Each is listed with where it is, its size, time, format, recorder and the computer, Chinese names intact; files left out are listed with their reason (broken, music, too short, not field sound). Copies are recognised as the same recording by size plus the contents of their first and last megabyte.


### Loose video is placed into shoots by the same matching

A video clip outside the destination tree, under a folder a person names, is placed the same way: filed camera clips elsewhere (never downloaded video) overlapping its time padded by 15 minutes are searched, 60 seconds from its middle against up to 12 of the longest with sound. A single match must reach a peak of 0.75 with a margin of 0.25 ("waveform"); otherwise, if exactly one folder overlaps in time, "time (one shoot overlaps)"; if several, "ambiguous by time". Counts per outcome and folder are shown, and each proposal waits for a person in the same review as sound recordings. Nothing moves until a person accepts a proposal or sorts the clip.

- On its own: a loose video clip's proposed shoot folder, from its sound and time.
- By hand: a person assigns it to any folder, as any clip.

#### Lessons

- Met: SRT-142, SRT-143, SRT-144, SRT-145, SRT-146, SRT-147, SRT-148, SRT-149, SRT-150.
