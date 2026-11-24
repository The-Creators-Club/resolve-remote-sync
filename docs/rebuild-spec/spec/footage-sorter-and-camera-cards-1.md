# The Footage Sorter and camera cards, part 1 of 3

The Footage Sorter gets footage off camera cards and sound-recorder cards and into the studio's folders, and keeps track of every copy so that nobody formats a card before its footage is safe. Editors and crew use it when they come back from a shoot, and in the field on their own computer with no network at all; an admin uses it to see what is not yet safe at home and to look after the studio's drives and cards. This first part covers recognising cards and drives, what cameras and recorders write, damaged and unfinished recordings, clocks, telling recordings apart, copying a card, checking the copy, drives and interruptions, and when a card is safe to format. Everything the Footage Sorter offers is usable by touch as well as with a mouse and keys: every control works with a tap, and whatever a tooltip says also opens on a tap. Camera cards with the Footage Sorter is one of the six parts a site switches on and off, and it is off on a new site until an admin switches it on. When it is off, nobody but an admin sees it, in settings, where it is listed with its switch: there is no Footage Sorter page, menu entry or search result, the app on an editor's computer does not watch for cards, report drives, announce a card or offer field backup, no drive is copied to the NAS by automatic backup, and no mail about footage not at home is sent. Switching it off never deletes anything: every copy already made stays where it is, and the record of every copy, every card's name, every drive's kind and every card-use entry are there again when it is switched back on.

## Recognising cards and drives

### The app on an editor's computer watches for cards and drives

While the Footage Sorter is on, the app on every editor's computer watches that computer's card readers and drives from the moment someone signs in to the computer, under the product's own name and icon, since the app starts whenever someone signs in (see The app on each editor's computer: Starting, staying running and crashing, "The app starts whenever the editor signs in to the computer, and set-up confirms it is running"). Watching runs whether or not anyone has the Footage Sorter open, and whether or not the computer can reach the studio at that moment.

Watching can be switched off for one computer. That computer then reports no cards and no drives and does not bring the Sorter up when a card goes in, and the Sorter says plainly, under that computer, that card watching is off there. When a computer is watching but cannot get its cards and drives through to the studio (it cannot reach the studio, or its sign-in is refused), the Sorter says so under that computer, with the reason, instead of only showing no cards.

- Who: the editor for their own computer, and an admin for any computer.
- Setting: Watch for cards and drives on this computer. Does: lets this computer notice camera cards and drives, bring the Sorter up on a new card, and tell the studio's record which drives are plugged in. Default: on. Who: the editor for their own computer, and an admin. Applies to: a computer. Search words: card watching, card reader, detect cards, drives, plugged in.
- When the Footage Sorter is off: no computer watches for cards or reports drives, and this setting is not shown.

### Which drives a computer can see, on Windows and on macOS

On Windows a computer sees the drive letters A to Z, removable and fixed drives only; network, optical and RAM drives are never seen. An empty card reader is skipped without the system's "There is no disk in the drive" box ever appearing. The system drive is the drive Windows runs from.

On macOS a computer sees every mounted volume. A volume is removable when macOS says it is removable, external or ejectable. The startup disk is listed exactly once, as itself, never as a card, and is known by an identity that stays the same across macOS updates. A volume macOS cannot describe is skipped.

On both, some drives are never seen at all: a drive with no identity of its own, a cloud-storage drive (Google Drive, OneDrive, Dropbox, iCloud, Box, Proton Drive, pCloud, MEGA, Sync.com and self-hosted cloud folders), a network or virtual-machine file system, an optical disc, and a FAT32 drive of 2 TiB or more. None of these is ever offered as a card or as a place to copy a card to. A drive's free space or size that cannot be read is shown as unknown.

A drive that does not answer within 5 seconds is skipped for that look and noted in the computer's log, and every other card and drive on that computer goes on being seen. On any other operating system the app sees no drives, so there is no card watching, drive reporting or field backup there.

- Windows and macOS: as described above.

### A card is recognised by what is on it, never by its drive letter

Drive letters change between plug-ins and between computers, so a card is never known by its letter. What kind of card a drive holds is decided from its contents, first match wins:

1. **Sony**: the camera's clip folder (PRIVATE, M4ROOT, CLIP) exists, even when it is empty. Stills in the card's DCIM folder are taken too.
2. **Drone**: a DCIM folder holds a folder named three digits then MEDIA (100MEDIA, 101MEDIA and so on) with MP4 or QuickTime video in it.
3. **Blackmagic**: a Blackmagic RAW clip sits in the card's top folder (macOS "._" files are ignored). The whole card is read.
4. **Sound recorder**: WAV files in the top folder whose names match the studio's recorders (a name containing "Wireless PRO", or six digits, an underscore and three digits).
5. **Card**: any other removable drive holding video, sound or photos within four folder levels.

On a Sony or drone card, matching recorder WAVs in the top folder are taken too. A drive with no media on it is not a card.

A fixed drive counts as a card only when it has one of the first four layouts, because CFexpress Type B readers and Blackmagic SSDs appear as fixed disks, while an internal disk full of footage is not a card. The system disk is never a card. A drive chosen as a place to copy cards to (a field drive, a laptop folder's drive, the NAS) is recognised by its identity and never offered as a card to back up, and a card is never offered as a place to copy to.

A card's listing leaves out system, recycle and hidden folders and the small files the operating systems add. A folder or file on the card that cannot be read is listed as unreadable, and the card's listing says it is partial (which stops the card ever being called safe to format, see "Each card shows a verdict on whether it may be formatted").

On Windows the card's volume serial, label and size are read; on macOS the volume's own identity takes the place of the serial. When a person asks the Sorter to read a drive that holds nothing it recognises, it says "nothing recognisable on <drive> (no Sony/BRAW/DJI/audio structure)".

- On its own: whether a drive is a card, and which of the five kinds, from its folders and files.
- By hand: a person can mark a drive as a card or as not a card, and set a card's kind. The choice is kept for that drive until a person changes it, and no later look overwrites it.

### Every card put in a reader appears within seconds, with no click

A card put into a reader on any watching computer appears in the Footage Sorter within about 10 seconds, wherever the Sorter is open, with its full list of files (each file's place on the card, size and time, and what the Sorter needs from camera metadata files and sound recordings), the card's type, capacity, free space and when it was put in. This holds for every card, including one put in straight after another was pulled.

- A drive just plugged in that looks empty is looked at again over the next minute and then for 5 minutes before it is taken not to be a card, because a card can appear before its files can be read.
- A card that changes while it is in (a different number of files, a different total size, or different files with the same count and size) shows the change within 5 minutes.
- A card being copied is not read by anything else while the copy runs; its last listing stands, and if it drops out of the list mid-copy it stays shown as last seen.
- A card taken out of its reader is taken off the list, unless a copy of it is running. A card its computer has not mentioned for 30 minutes is taken off the list in the same way.
- A card that stays in its reader across a restart of the studio's server stays listed, as it was.

- Who: anyone signed in sees the cards of every computer.
- On its own: which cards are in which computer's readers, from what each watching computer sees.

### When a card goes in, the Footage Sorter comes up on it

When a card goes into a watching computer, the Footage Sorter comes up on that card without a click, and only ever in one browser tab:

- If a Sorter tab is already open on that computer, it switches to that computer and shows the card's view, and the notice reads "<what> - showing in the sorter." (<what> is "Card on K:", "Drone clips on K:", "Blackmagic BRAW on K:" or "Loose audio on K:", with the card's own drive). If that tab is already showing another card's view, that view stays, and "Card <drive> detected" with Go is shown instead.
- If no Sorter tab is open, one opens on that card: "<what> - opening the sorter...". A tab that is just opening is waited for rather than opening a second.
- If the drive holds nothing the Sorter recognises: "<what> - the sorter did not recognise it." as a warning.
- If the studio's Footage Sorter cannot be reached from this computer, field backup opens on the card instead, so the card can still be copied (see "An editor can copy a card with no network at all"), and the notice says that the Sorter could not be reached and field backup is open instead.

Every card put in while a tab is open joins that tab's list of cards. A card taken out is reported too. A card that was already in a reader when the person signed in is listed, but does not bring the Sorter up again.

- On its own: opening the Sorter, or switching an open one, on each new card.

### The person is told when a card arrives, is ready, fails, is removed, and when its copy ends

While a Sorter page is visible it checks the list of cards about every 5 seconds and announces each change once per card and state. Cards already listed when the page opened are not announced.

| What happened | What is shown |
|---|---|
| A card arrives | "Card <drive> detected - <n> clips" for 8 seconds, with Go; that card's computer is opened in the list |
| The card is read and ready | "Card <drive> - <n> clips · <size>" with Go |
| The card could not be read | "Card <drive> - <error or 'could not be read'>" |
| The card is taken out | "Card <drive> was removed" |
| Its copy ended, all checked | "<drive> - <n> clip(s) copied and checked" |
| Its copy ended with some not checked | "<drive> - <n> clips copied, <n> not checked" |
| Its copy was stopped | "<drive> - copy stopped" |
| Its copy failed | "<drive> - <error or 'the copy failed'>" |

The list of clips reloads when a copy ends, when a card finishes being read, is taken out, closed or disappears, and when it gets new thumbnails.

### Each card is listed under its computer with its state, its health and its copy

Cards are listed under the computer they are in, sorted by drive and then by the card's serial. With no card anywhere: "No card in a reader. Put one in; this page looks every few seconds." A "Look again" control takes a fresh look at every drive of every watching computer at once. No card is selected on its own: a page opened while cards are already in readers asks where to look (see The Footage Sorter and camera cards: The sorter page, "Opening the page asks where to look and loads little"), except that a card the app brings the Sorter up on is shown in its own view (see "When a card goes in, the Footage Sorter comes up on it"). Clicking a card selects it.

Each card shows:

- its drive, its name (the studio's written name for it, else its volume label, else its serial), and its camera: up to two camera models seen on it joined by "/", else its kind ("Sony", "Blackmagic", "Drone", "Audio" or "Card");
- its state: "detected", "reading…", "ready", "copying <n>%" with a small bar and the speed in MB/s (one decimal under 10), "done ✓", "error", "ejected" (it was pulled), or "closed";
- "<n> clips · <size>" (the camera's index files are not counted as clips), when it was put in and read, any error, and how many warnings;
- "<n> files · <size> · <drive> · lands in "<folder>"" for where a field copy would land;
- its capacity, the studio's guess at which named card it is, and how many thumbnails are still missing;
- a health mark when it has problems: "⚠ <n> damaged · <n> bad copies" or "⚠ <n> to check", explained as "Clips on this card are damaged. Image the whole card before you format it.", "Copies came out damaged although the card is fine. Copy them again before you format the card." or "Clips on this card were not closed normally by the camera. Check them before you format the card.";
- a "which card?" mark ("Formatted since it was last named: open it and say which card it is") when nobody has named the card's serial since its last format, unless it is ejected or was marked not one of the studio's;
- a tooltip with drive, label, serial, "<kind> · <n> clips · <size>" and any error.

Clicking a card opens its view. A card being read shows its clips as soon as reading finishes. There is one entry per card: when the same card comes back (the same serial, or the same drive when it has no serial) after it was pulled, finished or failed, the earlier entry is replaced so its clips are never listed twice, and the new entry keeps every assignment the earlier one had. After a copy ends the card is ready again. Clips the record of every copy already knows a copy of show that state on the card.

- Who: anyone signed in.

### A card can be taken off the list and shown again

✕ on a card ("Take this card off the list (nothing is copied or deleted)") takes it off the list. Nothing on the card or anywhere else is copied, moved or deleted. Taking a card off is refused while it is being copied: "a copy is running for this card". Before it is taken off, the person is warned when that is unsafe (see "Taking a card off the list warns when it is not safe to").

A card taken off the list but still in its reader is listed under its computer as "closed", with Show again ("Put this card back on the list."). Showing it again returns it in the state it was closed in, with every assignment of its clips as it was. If it has left its reader: "that card is not in a reader any more. Put it back in and it will be listed again." Failures read "Could not bring that card back" and "Could not dismiss that card". A card that was pulled out (rather than closed) keeps its assignments too, since it may come back.

- Who: anyone signed in.

### A card is read again when a person asks

"Rescan" on a card's view, and "Look again" for every card, read the card again from the computer it is in and show what is on it now ("Rescanning the card…"). Reading again is refused while the card is being copied, and when its drive no longer holds a recognisable card ("<drive> no longer holds a recognisable card"); a failure reads "Could not rescan that card". Reading again also picks up cards that were already in and handled before.

- Who: anyone signed in.

### A folder holding a copied card or a card image can be read as a card

A person can point the Sorter at a folder that holds a card's contents, or at a mounted image of a whole card, on a computer the studio watches, and it is read and offered exactly like a card in a reader, so a card copied by hand or recovered from an image goes through the same checks and copy.

- Who: anyone signed in.

### Every drive is known by its identity, and the product knows which computer it is plugged into

Every drive is known by its volume serial (on macOS, its volume identity), never its letter, so it is recognised whatever letter it gets, including a letter another drive had before. A drive with no usable identity is ignored.

Each watching computer tells the studio's record about every card reader and fixed drive plugged into it: its identity, label, file system, size, free space, whether it is removable or fixed, whether it is the system drive, and its drive letter, and nothing else about the computer. A drive plugged in, pulled, relabelled, reformatted, resized or moved to another letter shows within about 10 seconds; free space is kept up to date within about a minute once it moves by 1 GiB or 1 % of the drive, whichever is larger; and every drive is confirmed at least every 5 minutes. A drive being copied from is shown as last seen even if it drops out.

A drive counts as plugged in while some computer has seen it within the last 15 minutes, so a drive on a computer that stops answering is shown as no longer plugged in after 15 minutes. When two computers see the same drive, the fresher sighting wins. A drive seen for the first time is recorded as unknown and untracked, with its label, size, free space, and when and on which computer it was last seen. A system drive is never offered as a new drive.

- On its own: which drives exist, which computer each is plugged into, and their free space.
- When the Footage Sorter is off: no drive is reported.

### Each drive has a kind, set by a person or guessed until they do

Every drive and every place that holds copies has one kind:

| Kind | Shown as | Counts toward a clip being safe |
|---|---|---|
| The studio's NAS | "Home NAS" | yes |
| A studio drive | "Ours" | yes |
| A laptop's own disk | "Laptop" | yes, flagged |
| A client's drive | "Client drive" | never |
| A camera card | "Card" | never |
| The cloud backup | its own label | for proxies and sound recordings only, never for a camera original |
| Not set | "Kind not set" | never |

A person sets a drive's kind with "Ours (counts)", "Laptop (counts, flagged)", "Client drive (never counts)" or "Not set" ("Not set" removes the person's choice). Only a drive has a kind of its own: a folder takes its drive's kind, and asking to set a folder's kind is refused with "only a drive's kind can be set". A person's choice is saved for the whole drive, at once, and the verdicts that depend on it are worked out again straight away.

Until a person sets it, the kind is guessed: a drive labelled in the studio's field-drive naming is "Ours"; a drive labelled in the client-drive naming is a client's; a removable drive is a card; the system disk, or a fixed drive holding a laptop folder, is the laptop; anything else is not set. A folder on a fixed drive whose kind is not set (or is a card) counts as the laptop. Each drive shows where its kind came from: "you", the studio's "record", or a "guess".

- Who: the editor at the computer the drive is plugged into, and an admin.
- Ways in: from the list of places a card can be copied to, and from the studio's list of drives.
- On its own: a drive's kind, from its label, whether it is removable, and whether it is the system disk.
- By hand: a person sets the kind; a kind a person set is never overwritten by a guess or by what a computer later reports.
- Setting: How the studio's and clients' drives are named. Does: decides which drive labels are guessed to be a studio field drive and which a client's drive. Default: studio drives are the letters CIB then D and a number; client drives are WD and a number, or have "passport" in the label. Who: an admin. Applies to: the site. Search words: drive naming, field drive, client drive, drive label, drive kind.

### An admin describes a drive and chooses what of it is tracked

For any drive an admin can set:

- a label, an owner and notes, each up to 200 characters (empty clears it);
- its kind (see "Each drive has a kind, set by a person or guessed until they do");
- which folders of it are tracked, by default the whole drive. The whole drive swallows any other folder, a folder inside another chosen folder is dropped, and a folder that climbs out of the drive or names a drive letter is refused with "a root must be a folder inside the volume";
- whether it is tracked, meaning that everything on it is looked over every time it is plugged in. Switching tracking on while the drive is plugged in starts its first look at once;
- whether automatic backup copies it to the NAS (see "Drives and folders with automatic backup on are copied to the NAS when the computer is at home").

The NAS appears as "Home NAS" and the cloud backup under its own label; both appear by themselves the first time they are read and are tracked whole. A label or kind a person set is never overwritten by what a computer later reports: a reported label only fills an empty one, and a kind is only guessed while it is still unknown. A computer's system drive can never be tracked or backed up whole: "the system drive cannot be tracked as a whole: watch a folder on it instead" and "the system drive cannot be backed up as a whole: back up a watched folder on it instead".

- Who: an admin.
- By hand: every value above is set by hand and never overwritten.

### Each of the studio's camera cards has a written name, like SD-1

A camera gives a card a new volume serial every time it is formatted, and some USB card readers report their own serial instead of the card's, so a serial on its own cannot say which of the studio's cards is in a reader. Each of the studio's cards therefore has the name written on it, which must look like 1 to 4 letters, a hyphen and 1 to 3 digits (for example SD-1), and a person names a serial as that card. A serial is 2 to 40 letters, digits, hyphens or underscores. Both are upper-cased. An empty name removes it, and naming a serial again replaces its earlier name. Once named, a serial reads "<serial> is <card> from now on."; an emptied one "<serial> unmapped."; a failure "Could not map <serial>: <reason>".

When the named card is in a reader, its size is learnt for later guesses. Every finished copy from that serial is checked again at once, so a card named after its copy finished is marked backed up straight away when its footage is safe.

The list of serials nobody has named shows each one with its label, kind, "<n> clips" and "shot <days>", beside a "which <kind> card?" list of every card (cards of other kinds dimmed).

- Who: anyone signed in.
- Ways in: from a card's own view, and from the list of serials nobody has named.
- By hand: the name is always set by a person; the guess below only suggests.

### A card formatted since it was last named asks which of the studio's cards it is

When the serial of a card in a reader has not been named since its last format, the card's view asks "Which card is this?" (or "Which card is this, if not <card>?" when it already has a name), with the reason:

- "Probably <card>: the crew recorded it on the day this footage was shot.";
- "Formatted since it was last named. <n> card(s) fit(s) its type and size."; or
- "None of the cards it could be is free; pick from the rest."

It offers one button per likely card (the probable one highlighted, the current one disabled; each with a tooltip giving its reasons, or "no record of it on these days"), and a list "Cards it is unlikely to be: the wrong type or size, or already in a reader". Choosing one shows "<drive> is <card> until its next format" (failure "Could not name the card: <reason>"). "Not one of ours" ("A borrowed card: stop asking for this insertion") stops asking about this card until it is next put in. Cancel closes the question when renaming. Nothing is listed while the card is still being read. A card already named still shows the list, so a person can say it is not that card.

How the likely cards are found: a Blackmagic RAW card can only be one of the studio's CF cards, a Sony card only an SD card, and drone and sound cards either; cards marked inactive, cards already named for another card in a reader, and cards whose learnt size differs by more than 2 % are left out. Each remaining card scores 2 when the crew recorded it used on a day this footage was shot ("used <days>"), and 1 when it is marked used rather than backed up ("marked used"); "same size" is noted. One card is suggested only when the top score is at least 2 and no other card ties it.

At most one such question is shown at a time, and nothing else asks while one is open.

- Who: anyone signed in.
- On its own: which of the studio's cards a freshly formatted card probably is, from its type, size and the crew's record of which cards were used on which day.
- By hand: a person picks the card, or says it is not one of the studio's; a choice made by hand is never replaced by a guess.

### Card settings a computer cannot read are reported, never ignored

If the settings for field backup and card watching on a computer cannot be read (a damaged settings file, a value that makes no sense), the app says so where the person looks: in a notice on that computer, on the field backup page, and under that computer in the Sorter, naming what could not be read. It never quietly carries on as if the settings were at their defaults, so a laptop in the field never behaves as if it were at home without saying why.

#### Lessons

- Met: SRT-001, SRT-002, SRT-003, SRT-004, SRT-005, SRT-006, SRT-007, SRT-008, SRT-009, SRT-010, SRT-011, SRT-012, SRT-013, SRT-014, SRT-015.

## What cameras and recorders write

### What a Sony card holds, and how its files travel with their clips

A Sony camera keeps its clips, its proxies and its thumbnails in separate folders under PRIVATE, M4ROOT, and writes a metadata file per clip (named after the clip with M01 and the extension XML) holding the recording time with its zone, the duration, a unique recording id and the camera model. An FX3 recording to both card slots gives two clips whose ids differ slightly.

The Sorter reads a Sony card so that everything the camera wrote for one clip stays with that clip:

- The camera's proxy of a clip (in its proxy folder, the SUB folder, named after the clip plus S and two digits) is that clip's proxy. A proxy whose clip is not on the card stays listed as a clip of its own, so it is never lost.
- The camera's own thumbnail of a clip (named after the clip plus T and two digits, in its thumbnail folder, or beside the video when a card was copied flat) is part of that clip, becomes its thumbnail and moves with it.
- A clip's identity and camera model come from the metadata file beside the clip itself, never from one in its proxy folder.
- The card's own index and status files (BIM, BIN, SMI, PPN, TXT, DAT, IND or XML files with no footage beside them) are never listed as clips, but are copied whenever a whole card is copied, so a copied card stays a complete card.
- A camera's side files travel with their clip on every copy and every move, and are never shown as clips of their own. A clip that was assigned somewhere but is missing from a later look at the card is listed as missing, never silently dropped.

Footage looked at before it was grouped this way is regrouped by the same rules without being read again.

### What a drone card holds

A drone keeps its clips under DCIM in numbered MEDIA folders. Its clock may never have been set, so a drone clip dated before 2020 is flagged as having a wrong date ("the drone's clock was not set"), and its recorded time is not trusted for sorting until a person sets it.

### What a Blackmagic card holds

A Blackmagic camera writes Blackmagic RAW files to the card's top folder, with the month, day, hour and minute in the name and the clip number after a C (for example A007_08090854_C137), its proxies in a Proxy folder, and, when the card has been in a Mac, macOS companion files carrying creation dates. A card reused in the camera can carry empty metadata files named like real ones; those never replace a real file (see "The Sorter decides clip by clip whether a card clip needs copying").

### The studio's field sound recorders, and how their files are read

From each recording's own header the Sorter reads its format, the broadcast-WAV description, maker, origination date and time, and length. A recorder recognised by its maker, then by its file name:

| Recorder | Known by | File counter | Clock |
|---|---|---|---|
| RODE Wireless PRO | a five-digit number then "Wireless PRO" in the name | from the name | from the header, with the firmware's year fault corrected (year 0026 read as 2026); each transmitter's card told apart by its folder |
| Zoom | maker "ZOOM", or a name of a date (day, month, year as DDMMYY), an underscore and three digits with no maker | from the name | from the header, else only the date from the name |
| Tascam | maker containing TASCAM or FR-AV2 | from the name | from the header |
| Any other broadcast WAV | its maker | none | from the header |

Anything else is an unknown recorder. A sound recorder stamps a WAV's file time when it closes the file, so a file's time is its end, not its start. A recording never closed after a power loss is measured by what is actually on disk (see "A recording whose recorder lost power still shows its true length").

Every recorder the studio uses writes 32-bit float, so only 32-bit WAVs count as field recordings; a WAV that does not count says why ("not 32-bit").

- On its own: which recorder made a file, its counter and its clock.
- By hand: a person can set a file's recorder and mark a file as a field recording or not; a value set by hand is never overwritten.

### Raw clips and raw stills always have a picture to show

Camera raw video has no picture to show until a proxy of it exists. A raw clip shows its picture from its proxy, says plainly when it has none yet, and shows the picture by itself soon after a proxy appears. Every camera raw still shows a thumbnail taken from the preview picture the camera embeds in it. How pictures are shown is in part 3 (see The Footage Sorter and camera cards: Thumbnails and hover filmstrips).

### Footage the studio shot is told apart from downloaded video

The studio's own camera clips are recognised by what their cameras write: a Sony metadata file with a recording id, a Blackmagic RAW file and its name pattern, a drone's DCIM layout, the studio's recorders' names and headers. Video downloaded from YouTube or elsewhere carries none of these marks and is never treated as the studio's footage: it is not offered as a card, not counted as a camera original waiting for a backup, and not matched to a shoot as if a camera had recorded it.

### A clip with no sound is recognised once

Some clips have no sound track at all (some FX3 settings record picture only). Such a clip is recognised as having no sound, is reported once as one that cannot be matched by its speech, and is never retried as a failure.

### Files a Mac or Windows adds are never counted as footage

Cards used on a Mac fill up with hidden files whose names start with "._", and opening a folder in Windows adds a small file of its own. Every look at a card, drive or folder, every check of a copy and every backup verdict skips:

- recycle bins and trash, and the operating systems' housekeeping folders (Windows' system volume information, the macOS index, trash and event folders, lost-and-found), and macOS archive leftovers;
- any hidden folder (a name starting with a dot);
- the quarantine folder that redundant copies are set aside in (see "Redundant copies are set aside into a quarantine, never deleted");
- files the operating systems and sync tools leave in folders: thumbnail caches, folder settings, macOS "._" files, and sync tools' databases.

They are never counted as missing footage and never make a size or completeness check fail, while those that sit in a folder still travel with the folder when it is copied or moved.

#### Lessons

- Met: SRT-016, SRT-017, SRT-018, SRT-019, SRT-020, SRT-021, SRT-022, SRT-023, SRT-024, SRT-025, SRT-026, SRT-027, SRT-028.

## Damaged and unfinished recordings

### Every clip on a card is checked for damage before the card is ready

While a card is being read, and before it is offered as ready, each clip's main file (MP4, MOV, M4V, MXF, Blackmagic RAW, R3D, Canon RAW, WAV, broadcast WAV, and Sony's unfinished RSV files) is checked with a few small reads. Stills and image sequences are not checked. A clip comes out **damaged**, **suspect** ("to check") or fine, and the person is told, in these words:

| Found | Told | Verdict |
|---|---|---|
| An empty file | "The file is 0 bytes." | damaged |
| The first MiB is all zeros and nothing after it | "Reads as nothing but zeros (<size>). The camera never committed this clip; the footage may still be on the card, but only a raw image of the whole card can get it back. Don't format the card." | damaged |
| The first MiB is zeros, data later | "The first MiB is zeros (the header is gone). Data from about <size> before the end. Image the card before formatting it." | damaged |
| A Sony unfinished recording | "An unfinished Sony recording (RSV, <size>): the camera never turned it into an MP4. Put the card back in the same camera and let it recover the clip; failing that, it can be rebuilt using a healthy clip from the same camera and settings. Keep the RSV either way." | damaged |
| Cut short | "Cut short: the '<box>' box claims <size> but the file ends <size> before that (<size> on disk)." and, if it has no index either, that it will not open, with the rebuild advice | damaged |
| No index | "No index (moov box): it won't open. " with the rebuild advice, and when the end is zeros " The last <size> (<n>%) are zeros: the recording was cut off, and that part exists only on the card." | damaged |
| Other video over 2 MiB ending in a whole MiB of zeros | "The last <size> are zeros: the recording may have been cut off." | suspect |
| The file cannot be read | "Could not read the file: <error>" | damaged |
| Sony clip with no metadata file | "No M01.XML: the camera never closed this clip normally." | suspect |
| Sony clip with an empty metadata file | "The M01.XML is 0 bytes: the camera never closed this clip normally (it was likely rebuilt by the camera's recover function)." | suspect |
| Sony clip with no proxy while the card's other clips have one | "No proxy, although the other clips on this card have one." | suspect |

The rebuild advice: for Blackmagic RAW, that the common repair tools do not handle it and a Blackmagic RAW recovery tool or service rebuilds the index from the frames using a healthy clip from the same camera and settings, with "Keep this file exactly as it is."; for anything else, that a repair tool can rebuild it using a healthy clip from the same camera and settings.

Proxies get the same checks, always only as suspect, prefixed "Proxy: ". Sizes read in GB with one decimal from 1 GB, otherwise in whole MB.

A camera that stops mid-clip on exFAT leaves a full-size file of zeros that copies perfectly, so a copy that matches the card is never taken as proof that a clip plays: only this check says that. Interrupted Sony and Blackmagic takes can be recovered only from a raw image of the card taken before it is formatted, and the person is told so at the moment the card is read, while it is still unformatted.

- On its own: whether each clip is fine, damaged or to check, from its first and last bytes, its index and its metadata file.
- By hand: a person can mark a clip they have opened and found playable as fine, or a clip they have given up on as lost; the mark is kept and shown, and no later check overwrites it.

### A recording whose recorder lost power still shows its true length

A sound recording's length, sample rate, channels and bit depth are read from the start of the file, without reading the sound itself, the same way wherever the file is (on a card, a drive or the NAS), so every listing gives the same figures. A recorder that stopped without closing its file leaves a length that says "never closed" or claims more than the file holds; then the bytes actually on disk are used. A file that is not a readable WAV has no length shown.

### A damaged or unclosed clip is marked on its card

Each clip carries a badge: "⚠ DAMAGED" when the camera's file is damaged, "⚠ CHECK" when the camera did not close the clip normally, and "⚠ BAD COPY" when the check after copying found a copy broken that the card's file is not. The badge's tooltip lists each problem as "• <text>" and each copy problem as "• Copy: <text>".

### A card with damaged clips or bad copies says plainly not to format it

A card's view shows a block for each kind of problem:

- Copies damaged although the card is fine: "⚠ <n> copy/copies came out damaged|wrong although the card is fine. Do not format the card." with "The post-copy check read the copies back and found damage the card does not have. Those copies have been removed and do not count as backed up: copy them again."
- Damaged clips on the card: "⚠ <n> damaged clip(s) on this card. Do not format it." with "Copying and checking will not fix these: the copy will match the card exactly. While the card is unformatted the footage is usually still on it, so take a raw image of the whole card first, then recover from the image." and "Image the whole card" (see "A person can take a raw image of a whole card").
- Clips not closed normally: "⚠ <n> clip(s) the camera did not close normally" with "Probably fine, but open them before you format the card."

Each block lists up to 8 clips (damaged first, then by name) with their problems, "…and <n> more", and "Select them". A card with a damaged clip or a bad copy is never called safe to format.

### A person can take a raw image of a whole card

So that a clip the damage check flagged can be recovered later, after the card has been reused, a person can have the whole card copied sector by sector into one image file, on the computer the card is in. Windows and macOS both allow reading a whole card only with administrator rights, so the person is asked to grant them on that computer. Refusals, each said plainly with nothing written: the card is not in a reader on that computer; administrator rights were not granted; the drive is on the system disk; not enough room for the image (it needs the card's size plus 1 GB; not checked for a network place).

The image is named from the card's label and serial and the time, in the studio's card-images folder, never over an existing file, with a details file beside it: the drive, label, file system, serial, model, connection, size, bytes read, whether it is complete, the image's fingerprint, the unreadable ranges, and when it started and finished. A part that cannot be read is read again sector by sector; sectors that still cannot be read are written as zeros and listed. Progress every 2 seconds shows done, total, speed and time left. It ends "Done: <size> in <time>", with the fingerprint, any unreadable ranges, and "Recover from the image, not the card". An image that stops short says how much was read.

- Who: an admin, and the editor at the computer the card is in.
- Windows and macOS: both ask for administrator rights on the computer.

### The same damage check can be run on footage already on disk

An admin can have any folders on the NAS or on a watched drive checked for dead clips. The check walks them (skipping recycle bins, system folders, caches, proxy folders, Sony proxy and thumbnail folders, the quarantine folder and macOS "._" files), runs the damage check on every footage file, and also marks as suspect a Sony-named MP4 whose metadata file beside it is 0 bytes. It shows each damaged and suspect file with its problems (fine ones too if asked), progress every 200 files, and ends "N files checked in X s: D damaged, S to check". The results can be saved. It never changes footage.

- Who: an admin.

#### Lessons

- Met: SRT-029, SRT-030, SRT-031.

## Clocks and file dates

### The studio has one time zone, used for every time that carries none of its own

The Sorter follows the studio's one time zone, the one setting everything in the product follows (see The server: installing it and keeping it running: NAS speed, load and clock, "Schedules run on the studio's own clock"). Every camera time, calendar time and file time that does not state a zone of its own is read in this zone, every time the Sorter shows is shown in it, shoot folders are named in local time in it, and the Sorter's nightly work runs by it. A zone that is named (rather than a fixed offset) follows its own summer time.

### The Sorter works out when each clip was recorded

Each clip's recording time comes from the first of these that works, the same way wherever the clip is (on a card in any computer, on a drive or on the NAS), so the same files always get the same time:

1. A Blackmagic file name (camera letter, reel, month-day-hour-minute, clip number) gives the month, day, hour and minute. The year comes from a date in the path with the same month and day, else a year in the path, else the file's own date; if that would put the recording more than 30 days after the file's date, the year before is used (shot in December, copied in January).
2. A Sony camera's metadata file gives the recording time at its own offset, the duration (to a hundredth of a second), the recording id and the camera model.
3. A date in the file name (2026-08-09, 2026_08_09 or 20260809), else in the folder path (deepest folder first): if the file's own date is that day, the file's hour and minute are used; if not, the video file itself is asked for its recording time (giving up after 20 seconds); failing that, the date with the file's hour and minute.
4. The file's own modified time.

A sound recorder stamps a WAV when it closes it, so a WAV whose time came from its file date is moved back by its length. A WAV's duration comes from its header. An image sequence takes a date found in its path with the time of day of its oldest frame, else the oldest frame's time. A recording time from a clock the Sorter judges wrong is shown with " clock?" beside it.

- On its own: each clip's recording time and duration, from the evidence above.
- By hand: a person can set a clip's recording time, or shift every clip from one camera or recorder by an offset; a time set by hand is never overwritten by a later look.

### Each sound recording is told whether its clock can be believed

Each recording's clock is judged, and the note shown with it:

| Judgement | Note |
|---|---|
| Trusted: a believable year, and the clock agrees with the file time within 120 seconds | "recorder clock plausible and agrees with mtime" |
| Trusted, the file time differs | "recorder clock plausible; mtime differs by <n> s" |
| Trusted, no file time to compare | "recorder clock plausible" |
| Not trusted: an unbelievable year | "recorder clock reads <date>: reset" |
| Unknown: no recorder clock, a believable file time | "no recorder clock; mtime only" |
| None | "no usable clock" |

Only a trusted clock places a recording by its time; an unknown one uses the file's closing time less its length. Recordings are also marked as loose or already filed, and each clip records its shoot folder (a proxy folder counts as its parent), start, length, camera, proxy and whether it has sound. Files that have not changed are not read again.

- On its own: whether a recording's clock is trusted, from its year and how it agrees with the file time.
- By hand: a person can mark a recording's clock as trusted or not, or set its start; the value set by hand is never overwritten.

### A recorder's reset clock is corrected from its neighbouring files

A sound recorder with an unset clock writes wrong dates but keeps steady time, so the recorder's own time stamp is a clue tried first, which the recording's sound against the cameras' sound, and then its speech, may overrule. Once one file is placed, the clock offset found for it estimates its neighbours' on the same kind of recorder, provided:

- the file counter order agrees with the clock order;
- the neighbour is within 25 files and 14 days;
- there is no gap over 72 hours, nor an overlap over 60 seconds;
- for a file between two placed ones, both agree within 2 seconds per hour apart plus 1 second (otherwise nothing between them is estimated).

Each estimate is a weak placement that is then checked against the cameras' sound, repeating up to 7 times while new files are confirmed. A dual-mono recorder writes one file per channel of the same take: an unplaced channel goes where its twin was placed, a little less certain, and is noted as placed through its twin. Placing sound recordings is in part 2 (see The Footage Sorter and camera cards: Placing sound recordings).

- On its own: an estimated start for files on a recorder whose clock was reset, from its placed neighbours and the cameras' sound.
- By hand: a person can set or clear any recording's placement; a placement set by hand is never overwritten.

### Clocks that are hours off, or change during a trip, are allowed for

Camera and recorder clocks are often whole hours off (a camera left on another zone), and are changed part-way through a trip. Matching by time tries whole-hour offsets as well as a fitted offset for a clock that was reset, never assumes that one offset holds for a whole trip, and names shoot folders in the studio's local time. A file's date is only a hint: matching by sound may overrule it.

- On its own: the offset of each camera's and recorder's clock, per day.
- By hand: a person can set the offset of a camera or recorder for a day; an offset set by hand is never overwritten.

### A night shoot stays one shoot after midnight

A shoot that runs past midnight gives its clips two dates. Clips recorded after midnight stay with the night's shoot, and are not filed as a separate day. Grouping clips into shoots is in part 2 (see The Footage Sorter and camera cards: Sorting into shoots, people and cameras).

### Every copy keeps the original file times

Every copy the product makes, from a card or from a drive, keeps the card file's own created and modified times, so a file's date on any copy is the same as on the card.

### Nightly work runs on the studio's clock

The Footage Sorter's nightly work (its walk over the NAS, the daily backup of the record of every copy, and the cloud backup's next run) happens at night by the studio's time zone, and the daily mail at 08:00 by the same clock (see "The studio has one time zone, used for every time that carries none of its own").

#### Lessons

- Met: SRT-032, SRT-033, SRT-034, SRT-035, SRT-036.

## Telling recordings apart

### The files of one recording are shown as one clip

Files in one folder that share a name (ignoring the extension) are one clip: the recording itself, its proxy, the small files and look files a camera or program writes beside it, the camera's metadata file and its camera thumbnail. The file that names the clip, its main file, is the highest in this order:

1. video: Blackmagic RAW, RED, MXF, MOV, MP4, M4V, MTS, M2TS (AVCHD), AVI, MKV, MPG, MPEG, WMV;
2. raw stills: Sony, DNG, Canon, Nikon, Fuji, Olympus, Panasonic, Samsung, Pentax;
3. other stills: PSD, EXR, DPX, TIFF, HEIC and HEIF, PNG, BMP, JPEG;
4. sound: WAV, AIFF, FLAC, M4A, MP3, AAC, OGG.

Ties go by name, and a group with no recognisable type takes its first file by name. A JPEG beside a raw still of the same name is that still's companion picture. Files in a folder named "proxy" or "proxies" (any case, at any depth below it) belong to the clip of the same name in the folder above, as its proxy or one of its side files; a Sony proxy whose name ends in "S03" joins the recording without that ending, and a Sony metadata file ending "M01" joins its recording. Blackmagic side files, look files, Sony metadata and housekeeping files and subtitles beside a main file join it. A proxy with no matching recording, or a lone metadata or look file, still becomes a clip of its own, so nothing is lost.

Each clip is one of: video, sound, still, image sequence, or other, from its main file. Clips are listed by recorded time, then by name.

- On its own: which files make up each clip and which is the main file.
- By hand: a person can split a file out of a clip, join a file to a clip, and choose the main file; what a person set is kept and never regrouped by a later look.

### A numbered run of frames is one clip

A folder (other than a top folder) holding a numbered run of at least 3 frames with the same prefix, type and number of digits, in EXR, PNG, TIFF or DPX, is one clip, an image sequence. The whole folder is the clip, its size and file count are the whole folder's, and it is always copied and moved as one folder. Its recording time is a date found in its path with the time of day of its oldest frame, else the oldest frame's time. An image sequence is never matched to a look-alike clip.

- On its own: that a folder of frames is one image sequence.
- By hand: a person can mark a folder as an image sequence or as separate stills; the choice is kept.

### The Sorter decides which camera each clip came from

A clip's camera is decided from, in order: a folder in its path named B-CAM or A-CAM; a path naming Blackmagic or one of its cameras; a file name containing FX3; a Blackmagic RAW file; a file name starting "DJI_" (a drone); otherwise "other". When clips are put into time folders, the camera model a Sony camera wrote into its own metadata beats a folder name.

- On its own: each clip's camera, from its path, name, type and metadata.
- By hand: a person can set a clip's camera, or the camera of every clip on a card; a camera set by hand is never overwritten.

### A recording is recognised as the same recording wherever it is copied

A file name does not identify a recording. The identity that survives copying is, most trusted first:

1. the unique recording id a Sony camera writes;
2. for an image sequence, the folder name, frame count and total size;
3. otherwise the file name (any case), the size of the recording and its recorded day; for sound recordings also the file's modified time.

Two files count as the same recording's content only when their content is checked to match; two different files of the same size are never taken as one another, never skipped as already there, and never one replacing the other.

A looser match (the same name and day, with the same recording size, or the same total size when sizes are unknown) finds the same recording on a camera's second card slot or recorded differently in the record of every copy. It is only ever used to show a likely state, never as an identity on its own.

A Sony camera recording to both slots writes two files that differ slightly but hold the same footage: they are recognised as one recording from two slots, shown as copies of each other and never as conflicting takes.

Two recorders started together can write files that look the same. A copy vouches for a card's file only when it is tied to that card (it was copied from that card, or it has been checked against that card's file); a look-alike file from another card never vouches for it.

- On its own: whether two files are the same recording.
- By hand: a person can say that two clips are, or are not, the same recording; the answer is kept and never overwritten.

### A shorter copy that is the start of a longer one is shown as a partial copy

When a second card or a copy stopped early, it holds a shorter file with the same name whose content is exactly the beginning of the longer one. Such a file is shown as a partial copy of the complete one ("partial second-card copy"), and the complete one is the one kept and placed. It never counts as a backup of the complete recording.

### Copies of the same recording are found, and one is kept as the one to place

Recordings with the same size and the same first and last megabyte are taken to be one recording when the Sorter places footage. One copy is kept as the one to place: an already filed copy beats a loose one, then the shortest path, then alphabetical order. The others are marked "already filed at <path>" or "same as <path>". Nothing is moved or deleted by this.

- On its own: which copy of a recording is the one to place.
- By hand: a person can choose another copy as the one to place; the choice is kept.

### Two clips with the same file name are badged, saying which copy to keep and why

Of two clips with the same file name, the copy worth keeping gets a plain badge and the other an "S" badge. The rule, in order:

1. the copy already sorted into its project's folders is kept, unless it is a shorter partial copy of the other (then the complete one is kept);
2. otherwise the larger copy is kept;
3. at the same size, the more recent recording;
4. when they are identical (same size and time), a fixed tie-break, so the answer never changes from one look to the next.

The tooltip names the rule. For the copy not kept: "Same size as the copy of “<name>” already sorted into the destination - that one is kept", "A smaller copy of “<name>” - another clip has the same name and more of it", "Same size as another copy of “<name>”, but recorded earlier - that one is kept", "Identical to another copy of “<name>” (same size, same time) - that one is kept; either would do". For the kept copy: "Duplicated: another clip has this name, and this one is already sorted into the destination, so it is kept", "...this is the larger copy to keep", "...this is the more recent recording", "...this one is kept so the answer does not move between renders". A plan keeps one copy and never moves both.

- On its own: which of two same-name clips to keep.
- By hand: a person can choose the other copy; the choice is kept.

### Same-name clips headed for one folder are listed before anything lands

The checks for missing footage list assigned clips with the same name that would land in the same folder under the studio's folder layout (keeping a source's own layout never collides). Groups where one copy is a different size come first. The lead line reads "<n> clips · these would collide in the same folder · <n> where one copy is shorter than the other". Up to 40 groups are shown, each with the name, "one copy is short" or "<n> identical", "→ <dest>", one line per copy with size, duration and source folder, and "Show these" (which shows exactly those clips as "<name> - duplicate copies"), then "… and <n> more". With none: "No destination has two clips sharing a filename." A name already taken is never overwritten: the copy is written beside it under another name, or left out.

- Who: anyone signed in.
- Ways in: on each clip, in the checks for missing footage, and when moving clips.

### Music and broken files are kept out of field recordings, with the reason given

A WAV is music, not field sound, when it sits in a folder named music, songs, bgm, sfx, sound effects, stems, soundtrack or library; when its name contains a music word (music, song, mix, remix, beat, instrumental, feat, OST, soundtrack, the names of stock music libraries, sfx, ambient, loop, stem, master or mastered, bgm, demo, jingle, intro, outro, vocal, bpm, or a tempo like 120bpm); when it is named "Artist - Title" with no recorder number; or when a music program wrote it (Pro Tools, Logic, Ableton, FL Studio, Reaper, Cubase). A file is unusable, with the reason shown, when it is "not a readable WAV", has "no fmt chunk", has "no audio data", or is "shorter than 30 s".

- On its own: whether a WAV is a field recording, music or unusable.
- By hand: a person can mark any WAV as a field recording or as not one; the mark is never overwritten.
- Setting: Shortest field recording. Does: a WAV shorter than this is not treated as a field recording. Default: 30 seconds. Who: an admin. Applies to: the site. Search words: short recording, field sound, minimum length, wav.

### Redundant copies are set aside into a quarantine, never deleted

An admin can have redundant copies in the staging folder and the sorted folders set aside. Candidates are files already at their destination, two identical sources for one destination, and clashes (the destination holds a different copy, or several sources lead to it). Which copy stays is decided by the studio's preference lists (some folders always kept, some losing ties); a chain of kept copies that loops, or anything outside those two folders, is refused.

Each candidate is then checked against the copy that stays: identical content; else identical picture and sound; else, if smaller, an exact beginning of the kept one (a card that stopped early); else a metadata file whose footage was proven. Anything not proven stays put, with the reason. The checking can be picked up again after it is interrupted.

Only then, and only when the admin asks for it, are proven copies moved (never deleted) into a quarantine folder on the same drive, keeping their path. A move is refused when the source is gone or has changed size, when the kept copy is gone ("refusing to quarantine the only copy"; a kept copy that has since been moved to its folder still counts), or when the quarantine path is taken. The first error stops the run. It reports "moved N file(s), X GB; skipped M". Empty folders are only reported, never removed. A person empties the quarantine by hand. Every look ignores the quarantine folder.

- Who: an admin.
- On its own: which copies are redundant and which copy stays.
- By hand: the admin reviews and starts the move; a copy the admin marks to keep is never set aside.

#### Lessons

- Met: SRT-037, SRT-038, SRT-039, SRT-040, SRT-041, SRT-042, SRT-043, SRT-044.

## Copying a card

### There is one card copy, and it starts at once on the computer the card is in

A card is copied by the computer it is in, because only that computer can read it. Wherever the copy is started from (the Footage Sorter in any browser, or field backup on the editor's own computer), it is the same copy with the same promises, described in this sub-topic and the next three. It starts at once, whether or not someone is using that computer, with no wait for the computer to be free. It is recorded as started by the person who started it.

The card must be in a reader on that computer, and never on its system disk: otherwise "card <serial> is not in a card reader on this computer, so nothing was copied". If the drive that last held the card now holds another card: "drive <X> now holds a different card (<serial>), not <wanted>: nothing was copied". While a card is being copied, nothing else on that computer reads it. A copy of a drive that is not on that computer is refused: "the drive with serial <serial> is not on this computer" (worth trying again once it is plugged in).

- Who: anyone signed in, and the editor at the computer the card is in, even with no network.
- Ways in: from a card's view in the Footage Sorter, and from field backup on the editor's computer.

### An editor can copy a card with no network at all

The app on an editor's computer offers "Field backup…" in its menu, which opens field backup in the computer's default browser. Everything it needs is carried inside the app, so it loads nothing from anywhere else and works with no internet and no studio network. It lists the cards in this computer's readers and the places on this computer they can be copied to, copies a card to every ticked place at once, and shows for each card what is already on which drive ("Already holds <have> of <of> files on this card") and whether it is safe to format, all with no network. What it copies reaches the studio's record of every copy as soon as the computer is next online.

Field backup is offered only while the Footage Sorter is on, and is off on each computer until it is switched on for that computer. Switched off for a computer, it is not offered in that computer's menu at all. If it is on but could not start on this computer, choosing it shows a notice that field backup could not start on this computer, saying why, and nothing else in the app is affected. When the app quits, field backup stops, and every copy it started is stopped cleanly first (see "A copy stops cleanly, and says why, when a card or drive is pulled, a drive fills, or the person presses Stop").

- Who: the editor at that computer.
- Setting: Field backup on this computer. Does: offers field backup in this computer's menu, so a card can be copied here with no network. Default: off. Who: the editor for their own computer, and an admin. Applies to: a computer. Search words: field backup, offline copy, laptop, on location, card backup.
- Name and search words: Field backup. Search words: field backup, offline, laptop, copy card, on location.
- When the Footage Sorter is off: there is no field backup on any computer.

### The places a card can be copied to

For the selected card, a "Copy to" list shows one row per place it can be copied to: a tick (unavailable while the place is absent or busy with another copy), its name, its type ("Drive", "Folder" or "NAS"), its kind ("Ours", "Laptop", "Home NAS", "Client drive", "Card", "Kind not set", marked as counting or not), where the copy will land, how much room is free, and "Already holds <have> of <of> files on this card". A place that is not there is dimmed with its reason. With no place at all: "No drive to copy to. Plug one in, or add a folder below." The rows update in place, so a choice the person has open is never closed by a refresh.

The places offered:

- **The studio's NAS**, in two ways: into the sorted folders, where each clip assigned to a folder goes to its place ("Copy to destinations…"), or into the staging folder to sort later ("Stage only…": "Copy the card into the staging folder and sort it later"). Copying into the sorted folders is refused, saying so, when the studio has no sorted folders set up, and staging when it has no staging folder. The NAS is offered only while this computer can reach it, which is checked within 2.5 seconds so a dead network share never freezes the page; when it cannot: "The NAS pool cannot be reached from here.", with how to fix it (join the studio's network, or connect the studio's footage share on this computer).
- **Every plugged-in drive** that is not the system disk and not a recognised camera card (a drive that merely holds some media is still offered). Copies land in a "FieldBackup" folder on it. It is named by the studio's record's name for the drive, else its label, else its drive letter.
- **Every folder set up as a place to copy to on this computer.** Copies go straight into the folder. A folder whose drive is not plugged in is shown absent ("That folder's drive is not connected."); a folder that does not exist yet on a plugged-in drive is shown present and is made by the copy.

- Who: anyone signed in from the Sorter, and the editor at the computer from field backup.

### An editor adds and removes folders as places to copy to

An "Add folder" box (placeholder "Add a folder, like D:\FieldBackup"; Enter also adds; empty does nothing) adds a folder on this computer. Surrounding quotes are removed. Refusals: "give the full path of a folder, like D:\FieldBackup" (empty, not a full path, or stepping up a level); "that folder is not on a drive this computer has right now"; "that folder is on a card or a USB stick, not on this laptop's own drive, so a copy there would not count. A plugged-in drive is listed under Copy to already." A folder already listed (ignoring letter case) is not added twice. Each folder has "Remove", which removes it from the list. The folders added here and the folders an admin sets for this computer are one list.

- Who: the editor at that computer, and an admin for any computer.
- Ways in: from field backup and the card copy on that computer, and from the computer's own settings.
- Setting: Places to copy cards to on this computer. Does: the folders on this computer offered as places a card can be copied to. Default: none. Who: the editor for their own computer, and an admin. Applies to: a computer. Search words: backup folder, copy destination, field folder, laptop folder.

### A place to copy to is checked to be the drive it claims to be

Drives are known by their identity, never their letter, so a field drive that comes back under another letter is the same drive, and a letter that now belongs to another drive is not mistaken for it.

The NAS is accepted as a place to copy to only when the product can confirm that it really is the studio's NAS, on Windows and on macOS alike. On a letter that is a local disk: "That drive is a local disk, not the NAS pool (a drive letter can change hands)." On a mapped network drive that points somewhere other than the studio's NAS: "That drive is <network path>, not the NAS pool (<expected>)." A copy to a place that is not confirmed never counts as "at home".

A card is never a place to copy itself to: "a card cannot be a destination for itself". When the places ticked are not the ones the last copy on this computer went to, the copy names the difference and asks the person to confirm before it starts.

- Windows and macOS: the same check on both.

### The places last ticked are ticked again

Every tick and untick is saved on the computer at once. On the next visit, the places last ticked are ticked again if they are there; a tick on a place that has gone or can no longer be used is dropped without a word. Starting a copy also records the ticked set as the last ticked.

### Where a card's files land

| Copied to | Lands in |
|---|---|
| A drive | "<day> <card label>" inside its "FieldBackup" folder |
| A folder set up on this computer | "<day> <card label>" directly inside the folder |
| The NAS, staging | one time folder per day and camera (see The Footage Sorter and camera cards: Sorting into shoots, people and cameras); clips that cannot have one (stills, no time, unknown camera) go to "<day> <card label, serial or drive> loose" |
| The NAS, sorted folders | each assigned clip at its place in its project's folders (see the same sub-topic) |

The day is the local date (year-month-day) of the newest file on the card, or the date of the copy when no file has a time. When the label is blank or one cameras give every card ("NO NAME", "Untitled", Canon's default label, "NIKON", "LUMIX", "CANON", "SD", "SD Card", "USB Drive", "Removable Disk", "Disk", "New Volume", "Card", "DCIM" and the like), the card's serial is used instead. Characters not allowed in file names become underscores. On a drive or folder, the card's own folder tree is kept beneath the landing folder. A landing folder remembers which card it belongs to; when a folder of that name already belongs to a different card, the second card lands in "<day> <label> <serial>", so two cards with the same label never mix. A folder that does not say whose it is is taken to be this card's.

Proxies copied off a card land in a Proxy folder inside the dated folder holding their originals, each under its clip's exact name (an ending the camera adds to its own proxies, such as Sony's "S03", is dropped), so the editing program, which pairs a proxy with its clip only by exact name, finds them beside their clips. Main files are copied before their proxy folders.

- On its own: each landing folder's name, from the card's files, label and serial.
- By hand: a person can rename a landing folder before the copy starts; the name set is kept for that card.
- Setting: Field backup folder. Does: the name of the folder a card copy lands in on a plugged-in drive. Default: "FieldBackup". Who: the editor for their own computer, and an admin. Applies to: a computer. Search words: field backup folder, landing folder, backup folder name.

### Before a card is copied, a review shows what goes where, whether it fits and what would be lost

Every copy starts from a review of what it will do. If the review cannot be worked out: "Could not plan the copy: <reason>". The review shows:

- a title, "Copy card <drive> (<kind> <camera>) to destinations" or "Stage card <drive> (<kind> <camera>)", and a lead "<n> clips · <size> → <n> folders on <drive>";
- room: "Needs <size> · <free> free on <drive>", "free space unknown on <drive>", or "… - not enough room, free some space first" (and Copy is then unavailable);
- how much of the card is backed up already and how much is not, and "<n> clip(s) is/are already backed up elsewhere - no destination needed, nothing to copy.";
- one row per destination folder: a tick, the destination with the time folder the copy will create highlighted, "(merges into <folder>)" when it joins one that exists, "<n> clips · <size>", and how many clips are in each state: "new", "partial", "present (skip)", "already elsewhere (off)", "differs";
- "clips ▸" on each row, opening its clip list (Missing only by default, or All): a tick, the name, size, state, the size difference ("+<size>" or "−<size>"), " clock?" when the recorded time looks wrong, and "⚠ damaged" or "⚠ check";
- warnings on a row ("⚠ <text>"), plan warnings "⚠ <n> warning(s)" (up to 12 shown), "long path (<n>): <path>" for a destination path longer than 240 characters, and "⚠ <n> name collision(s)" with up to 60 names, each of which is written beside under another name or left out, never overwritten.

By default only new and partial clips are ticked. A row is ticked when any of its clips is; ticking a row ticks only its new and partial clips; unticking a row clears all of them and dims it. Clips are grouped by destination folder, each showing its path, whether it exists, camera, day, size and its clips (those to copy first, then clashes, then skips).

- Who: anyone signed in, and the editor at the computer.
- By hand: a person ticks or unticks any clip or folder before copying.

### The Sorter decides clip by clip whether a card clip needs copying

Each file is judged at its planned place:

| What is at the planned place | What happens | Shown as |
|---|---|---|
| Nothing | copied | new |
| The same recording, whole, its content checked against the card | not copied again, and recorded as a checked copy | present (skip) |
| The same recording but shorter, and every byte there matches the start of the card's file | finished from the card; only the difference counts toward room | partial |
| A shorter file that is not the start of the card's file, a different file of any size (the same size included), a folder or a link | left exactly as it is; the card's file is written beside it | differs |
| An image sequence's folder name already taken | never merged; the sequence is written beside it | differs |
| Nothing, but the same recording sits at another place on that drive or in the sorted folders at the same size | offered but not ticked, and not counted toward room | already elsewhere (off) |

Writing beside means the copy is named "name (2)", "name (3)" and so on up to 99. If the plain name or a numbered copy already holds an identical copy (from an interrupted earlier copy), the file is not copied again. With 99 numbered copies already there: "99 renamed copies of it are already there". Two clips in one copy that would land on the same name: the second is written beside. Nothing that was at a destination before the copy is ever overwritten, renamed or removed; an empty metadata file of a reused card never replaces a real file. A clip with nothing left to copy (only its proxies, and proxies were not asked for) is skipped.

A clip counts as copied only when every file chosen for it (its main file, and its proxy and metadata when those were chosen) is at its place at full size and checked; any that are missing are copied. Every file in a review is either copied or listed with the reason it was not.

A file the card no longer holds as reviewed fails: "the source is N bytes now and the review listed M: it changed since it was read"; "the source cannot be read (<error>)"; "the source is not a file". At the destination: "the destination cannot be read (<error>)"; "a file appeared at the destination during the copy; it was left alone".

- On its own: what to do with each file, from what is at its planned place and what the record of every copy knows.
- By hand: a person can tick a clip that is "already elsewhere" or "differs" to copy it anyway, or untick any clip; the copy follows the ticks exactly.

### Camera proxies come off a card only when asked

A copy offers "Back up proxies too", unticked by default. Camera proxies and the files that describe them are copied only when it is ticked when the copy starts. Changing it works the review out again. A proxy whose clip is not on the card is a clip of its own, and is copied like any clip. The card's own index files are copied only with a whole-card copy.

- By hand: "Back up proxies too", for each copy.

### Clips with no destination are accounted for before copying

In a copy into the sorted folders, a clip not assigned to any folder is not copied there. Before anything is copied, every such clip is accounted for:

- a clip that already has a checked copy is listed as "unassigned but backed up", with where. It counts as backed up, never counts as unassigned, raises no warning, and needs no acceptance before copying;
- any other is listed as "unassigned", with the warning "⚠ <n> clip(s) has/have no destination and is/are not backed up anywhere" and "Wipe the card without dealing with it/them and the footage is gone.", and the choice: "Stage them to <staging folder>" (the default, in the same copy), "Skip them - leave them on the card", or "Go back and assign" (which opens the card's view on its unsorted clips with those clips selected).

The summary always shows how many clips on the card are backed up and how many are not.

### The copy does exactly what the person reviewed

A copy does what its review showed, and only that. If the card or any assignment of its clips changed after the review was shown, starting is refused ("assignments changed since the review was made: review again", or "the card changed since the review: review again") and a fresh review opens. A copy cannot start without a review. The clips can be chosen within the review; with none chosen, clips already elsewhere in the sorted folders are left out.

### Starting a copy, and when it is refused

The review's start button reads "Copy <n> clip(s) · <size>", and in field backup "Copy to all" ("Copy to all (<n>)" with more than one place ticked), with the note "Only what is not already there is copied; nothing is overwritten. Lands in "<folder>"." It is unavailable, with the reason beside it, while starting ("Starting..."), with no card ("Put a card in a reader."), while the card is being read ("still reading the card") or copied ("This card is being copied."), with nothing usable ticked ("Tick where to copy it."), or with not enough room.

Refusals when starting:

- "that card is not in a reader any more. Put it back and look again."
- "tick at least one destination"
- "one of the ticked destinations is not available any more. Look again."
- "a card cannot be a destination for itself"
- "<destination>: <why it is not there>"
- "<destination>: the folder cannot be made (<reason>)"
- "a copy is already running for this card: wait for it to finish, or stop it"
- "<destinations> is busy with another copy" (a ticked place, or another on the same physical drive, is in use by another copy)
- "nothing to copy: every selected clip is already there"
- no sorted folders, or no staging folder, set up for the studio, saying which.

Every place a copy is going must be reachable before anything is copied, so a missing NAS share fails the whole copy at the start rather than file by file. The folders the copy needs are made first ("could not make the folder <path>: <error>" stops the copy). On a start, the card's state becomes copying, the card's view shows the copy started and its progress follows, and each clip shows its verdict from the review. A quick "stage this card now" from a card's view is the same copy with the same review rules and refusals, reviewed and started in one step.

### A card copy shows live progress and can be stopped

While a copy runs, its progress is refreshed about every 2 seconds while the page is visible, never in a hidden tab:

- for the copy: "<card label> → <folder>", a bar (by bytes when known, else by clips), "<n>% · copying|checking · <n> MB/s · <time> left · <done>/<total> clips · <size> of <size> · checked <n> · <current file>", and Stop;
- for each destination: name, kind, state, percentage, a bar, "<done> of <total> · <rate>/s · ETA <time> · <n> of <n> files", the file being worked on, the destination's message, and a list of up to 40 problems ("<clip> - <message>");
- details for each destination folder: its own bar, "<done>/<total> · checked <n>" and "<n> failed".

States of a destination: Waiting, "Looking" ("looking at what is already there"), "Checking what is there", Copying, "Checking", "Resting" (see "Long copies to a field drive let the drive rest"), Done, "Needs a look", Failed, Stopped, "Not started". Rate and time left show only while bytes are moving; no figures show for a refused destination. Time left reads in seconds under 90 seconds, minutes under 90 minutes, otherwise hours to one decimal, and "<n.n> days" over a day and a half. The percentage stays at 99 or below until the end, and shows 100 for Done or "Needs a look". Speed is averaged over about the last 5 seconds and shows 0 while checking. Before the first news, a rough bar shows the copy is starting.

With nothing copying: "Nothing copying. Pick a card, tick where it goes, and press Copy to all." The three most recent copies stay shown with their outcome. Stop reads "Stopping..." once pressed (see "A copy stops cleanly, and says why, when a card or drive is pulled, a drive fills, or the person presses Stop"); stopping with nothing running just says so.

- Who: anyone signed in can watch and stop a copy, and the editor at the computer.
- Ways in: on the card's row, on the card's view (which holds the copy's details), and in the list of everything copying right now; on the editor's own computer, in field backup.

### A copy's result reaches the studio's record even when it finished offline

Every copy ends with a result: each file copied, already there, finished, written beside, left alone or failed, with where it came from, where it went, its size, whether it was checked, the name it was written under, or the reason. A copy that stopped early is marked unfinished and still lists what landed. When the studio cannot be reached at the end (in the field, or on a dropped network), the result is kept on the computer and reaches the studio's record of every copy as soon as the computer is next online, so no copy is ever lost from the record; until then the card's verdict on that computer counts the copies made there. A copy that ran counts as finished even when some files were skipped, left alone or failed; the counts say so. The record of every copy is in part 2 (see The Footage Sorter and camera cards: The record of every copy).

### After a card copy, the sorting follows the footage

Every clip that landed is recorded with its card (serial, label and kind) as its origin. A checked clip copied into the sorted folders has its assignment done. A checked clip copied to staging keeps its assignment on its staged copy, so it shows assigned there, and it moves into its folder on its own, with no one approving the move; a person can move it somewhere else by hand afterwards. Every checked copy on the NAS is recorded as a trusted copy; a failure to record it never undoes the copy. The copied folders show in the Sorter as soon as the copy ends. Moving footage on is in part 2 (see The Footage Sorter and camera cards: Moving footage on the NAS).

### Footage short of a second copy is copied when a second drive appears

When a card's files have been copied to fewer places than "safe" needs (for example to one field drive in the field), the product remembers what is still owed, across restarts of the app and the computer. As soon as a drive that counts and does not yet hold those files is plugged in (or the card is put back), it offers, once, to copy the owed files to it, naming how many files and which drive; accepting starts the copy from the card if it is in, else from the copy already made. The offer stays listed on the card until the files are safe or the person dismisses it.

### An admin copies files from one drive to another, or between a drive and the NAS

An admin chooses the computer, the source drive, the destination (another drive on the same computer, or the NAS), files or folders on the source, and optionally a destination folder. Each file lands at the destination folder, then the name of what was picked, then the rest of its path. The copy only adds: a file already at that exact place with the same size and matching content is not copied again and is counted. Optionally, everything that already has a copy on the NAS is left out. It runs on the computer holding the drive and is checked exactly like a card copy.

Refusals: source, destination and files are all needed; "copy to a different volume"; the destination folder must be a folder inside the destination drive; an unknown drive; the drive is not plugged into any computer right now; the two drives are plugged into different computers; that computer does not have those drives; "<a> and <b> would both land at <dst>: copy them one at a time, or into different folders"; "more than 20000 files: copy a smaller folder"; nothing to copy; no NAS footage share set up for the studio. Progress, stopping and the result are as for a card copy. A copy into the NAS shows there as soon as it ends. The 40 most recent drive copies stay listed.

- Who: an admin.

### A card's view shows its clips under a banner that says how much of it is safe

Opening a card shows only that card's clips and clears every other filter (status, search, destination and location). The card's view has its own link: opening the link, or going back or forward to it, opens the card; leaving it clears it. The banner reads "💾 Ingest · <computer> · <drive> · <card> · <camera>", with ✎ ("Not <card>? Say which card it is") when the card was named by a guess, then "<n> clips · <size> · <n> backed up · <n> not backed up · <n> suggested · <n> assigned · <n> unassigned" (not backed up highlighted when any), whether a copy is running, failed or done, and the latest error.

From it a person can: "Copy to destinations…" (the review for a copy into the sorted folders); "Stage only…" (the review for a copy into staging), both unavailable while the card is being copied or read; "Retry" (only after a failed copy), which reviews again carrying only what is still missing; "Rescan"; "Dismiss" (take it off the list); and ✕ (leave the card's view).

- Who: anyone signed in.

#### Lessons

- Met: SRT-045, SRT-046, SRT-047, SRT-048, SRT-049, SRT-050, SRT-051, SRT-052, SRT-053, SRT-054, SRT-055, SRT-056, SRT-057, SRT-058, SRT-059, SRT-060, SRT-061, SRT-062, SRT-063.

## Checking a copy

### What makes a copy count as checked

A copy counts as checked only when the product has read it back from the destination drive itself (never from what the computer still holds in memory) and found it matches the card. Until then it counts for nothing.

- Each file is written under a name that marks it unfinished, written fully to the drive, given the card file's own dates, and checked. Only then does it take its real name, and never over an existing file. A half-written or unchecked file is never left under its real name.
- The check is quick by default: the same size, identical first and last 1 MiB, and, for camera video, the clip's index, compared in full up to 64 MiB and beyond that by its first and last MiB. The result says the check was quick. A person can ask for a full check of a copy ("Check every byte"), which reads every byte back from the drive and compares it with the card.
- A copy whose check proves a mismatch is removed (it was written by this copy, under its unfinished name), counted as failed, and reported: "check failed: the copy is N bytes and the source M" or "check failed: the copy read back differs from the source". It never stays where it could be taken for a good copy.
- A drive that cannot be read back during the check (it hung or dropped off) stops the check for that destination, and the person is told that the check could not finish and nothing was marked bad. Only a proven size or content mismatch ever marks a copy bad.
- A file counts only if it is at its planned place, inside the studio's folders when it went to the NAS, at the size planned, and checked. Nothing counts on any computer's word alone; a file reported anywhere else is listed with the reason and not counted.
- Progress is measured by bytes written and checked, never by a drive's free space. A file that is already at a destination counts only once its size and modified time (within 3 seconds) match and its content is checked.
- A file checked once stays checked when a later copy skips it.


### Files already at a destination are checked against the card

Before copying, each file already at its place is compared with the card ("Checking what is there", "checking <file>"). A match counts as "already there" and is recorded as a checked copy, so running a card again also checks its earlier backups, and a copy picked up after a stop checks every earlier copy it skips. A mismatch is left alone: "it is already at the destination but does not match the card: <reason>. It was left alone." (the card's file is then written beside it). A clip on the card with no index passes, with the warning that the source has no index, so the clip itself is damaged, not the copy.

### Every copy is checked for damage, and damage the copy brought in fails it

After each part of a card copy, what landed gets the same damage checks as the card (see "Every clip on a card is checked for damage before the card is ready"), plus: "The copied <part> is not there: <path>"; "The copied <part> is N bytes; the card's is M." (damaged for a main file, suspect otherwise); and "The copied M01.XML is 0 bytes although the card's is not." A problem the card's own file does not have counts as brought in by the copy (if the card has already gone, its earlier verdict stands in). A damaged copy is recorded as damaged and never counts as a backup, and damage the copy brought in fails that clip with "the copy of <clip> is damaged but the card's is not (<problems>): it was removed; copy it again". Clips skipped as already there are checked too.

### How a card copy ends, and what the person is told

Each destination ends:

- **Done**: every file copied and checked;
- **Needs a look**: finished, but something was left alone, failed, or could not be checked;
- **Failed**: files missing or of the wrong size, or the copy could not run;
- **Stopped**: stopped by a person or by a pulled card or drive.

A copy with any unchecked file is never Done. At the end, each destination shows its counts: "<n> copied and checked, <n> already identical, <n> already there, quick-checked, <n> written beside a different file, <n> left alone (something different is there), <n> failed, <n> copied but not checked." or "Nothing to copy." The card goes back to ready; a pulled card stays ejected.

When the copy and its check finish, a notice names the card and gives the counts copied, already there and checked, and points to any failures. A failure names the clip, the destination and the reason in plain words, and says what was partly copied. A clip whose main file did not land shows "not copied" with the reason, and a clip missing some files "<n> of its files not copied". Every finished destination is added to the lasting copy history (source, destination, size, checked or not, fingerprint, any name it was written under).

#### Lessons

- Met: SRT-064, SRT-065, SRT-066, SRT-067, SRT-068, SRT-069.

## Drives, speed and interruptions

### A card copies to several drives at once, never twice to the same physical drive at once

One card has one copy at a time. Within it, places on different physical drives are written at the same time, and places on the same physical drive one after another, the waiting one showing "waiting for the other copy on this physical drive". A place in use by one copy, or on the same physical drive as one, cannot be used by another copy at the same time. Copies from different cards to different places run at the same time. Reading from any one card or drive is never split into so many reads at once that it slows down, copies from separate cards run side by side only where the computer's connections let them run at full speed, and small proxy folders are copied last.

### A copy stops cleanly, and says why, when a card or drive is pulled, a drive fills, or the person presses Stop

A running copy notices within about 2 seconds:

| What happened | State | Said |
|---|---|---|
| The person pressed Stop | Stopped | "stopped by you" |
| The card was taken out of its reader | Failed | "the card was taken out of its reader" (worth trying again) |
| A destination was taken out or went away | Failed | "<destination> was taken out (or went away) during the copy" |
| A destination's letter now belongs to another drive | Failed | "<destination> is now a different drive (its letter changed hands)" |
| A destination is full (under 48 MiB free) | Failed | "<destination> ran out of room. <n> files are on it whole and checked; the rest were not copied. Free some space or pick another drive." |

For every reason but a full drive, the destination's message is "Stopped: <reason>. <n> files are on <destination> whole and checked (they are kept and recorded); the rest were not copied. A half-written file is never left under its real name". A copy that cannot run at all shows every destination Failed, "The copy could not run: <reason>".

A pulled card stops the whole copy once, with that one reason, instead of failing every remaining file. Stop takes effect within a few seconds; the file being written is kept under its unfinished name. Whatever landed whole and checked before a stop is kept, recorded and reported. The next copy of the same card copies only what is missing, and finishes an unfinished file rather than starting it again.

After a destination drive lost power or was pulled mid-copy, its last writes may be lost even though the files look whole. The next copy to that drive therefore looks the drive over first, and finishes each unfinished file from well before the point it had reached, checking the part already there.

### A copy that stops moving says so

A long copy runs steadily, and the person always sees its live speed. When a copy makes no progress for a set time, which the product states on the copy (a destination drive hung, a card stopped answering), it stops cleanly as above and says which drive stopped answering, telling the person to plug it back in if it stays gone; the next copy copies only what is missing. While a copy runs slower than it should, the progress says where the slowness comes from: the card being read, the drive being written, or the network to the NAS.


### Room and path length are checked before anything moves

Before anything is copied, each place is checked for room and for what is already there ("Looking", "looking at what is already there"). A place that is gone is refused at once: "<destination> is not there. Plug it in and try again."; "<destination> cannot be read. Is it still plugged in?". If what needs copying there, plus the room kept spare (256 MiB unless an admin sets another amount), is more than its free space, that place is refused before anything moves: "Not enough room on <destination>: <free> free, and this card needs <need> more (plus 268 MB kept spare). Nothing was copied there." (268 MB is the default room kept spare; the message gives whatever amount is set). The other places carry on, so the card gets a copy wherever there is room. Only what still needs copying counts (a partial file counts only its missing part, and a clip already elsewhere counts nothing unless ticked). The free space of a folder not yet made is the free space of the drive it will be made on. Free space that cannot be read counts as enough, and the review says it is unknown.

A destination path longer than 240 characters is warned about: "long path (<n>): <path>".

- Setting: Room kept spare on a place to copy to. Does: how much free space a card copy leaves untouched on each place it copies to; a place that would be left with less is refused. Default: 256 MiB. Who: an admin. Applies to: the site. Search words: free space margin, spare room, disk full, room kept free.


### Card copies are as fast as a dedicated card-copying program

A card copy reads and writes at the same time, and to or from the NAS keeps the connection full, so it reaches at least the speed a dedicated card-copying program gets from the same card over the same connection, and at least 80 % of the speed of an ordinary Windows file copy to the same place. A copy picked up after a stop resumes where it was and never starts over. Large copies to slow external drives never let the computer's write cache pile up, so the computer stays responsive while it copies.

### Long copies to a field drive let the drive rest

Some field drives hang after a few hundred GB of non-stop writing. During a long copy to such a drive, the copy pauses to let it rest (by default 10 minutes after every 150 GB written), shows "Resting" with the time left, and stays stoppable throughout.

- Setting: Rest field drives during long copies. Does: pauses a long copy to a field drive to let it cool. Default: 10 minutes after every 150 GB. Who: an admin, and the editor for their own computer. Applies to: a computer. Search words: rest, pause copy, drive hang, cool down, long copy.

### Copies and moves within the NAS never pass through an editor's computer

A copy between two folders on the studio's NAS is made on the NAS and runs at the NAS's own speed, never pulled down to an editor's computer and sent back. A move between staging and project folders on the same NAS volume is a rename that finishes in seconds whatever the size, and keeps the files' times. Moving footage on the NAS is in part 2 (see The Footage Sorter and camera cards: Moving footage on the NAS).

### A look over a drive survives interruptions, and one that dies is said so

A look over a drive or the NAS that is interrupted and taken up again starts cleanly; nothing half-finished from the first try is kept. A file whose name cannot be used (too long, unreadable characters, a path climbing out of the drive) or that has no size is skipped and counted, never failing the whole drive; files of types the Sorter does not track are ignored. A look that ended without finishing is marked failed ("the scan ended without finishing") within about a minute, and what it had found is not used. Looking again over files whose size and time have not changed is quick. A file replaced under the same name, which a check of folder times can miss, is still caught by a full look over the NAS every night.

### Everything copying right now is shown in one place

While anything is copying, an indicator shows "<n> backup(s)" and the combined speed. It counts card copies (waiting, copying, checking), every drive copy and look, and the cloud backup's upload. Opening it shows "Backups in progress" (closed again by ✕, a click outside, or Escape), refreshed every 2 seconds: each item with its kind ("card copy" or the work's kind), a title ("<drive> · <card>" for a card), a percentage and bar (a busy bar when unknown), "<phase> · <speed> · <eta> left · <done>/<total> files · <size> of <size>" and the file in hand. With nothing running: "Nothing is running." / "No card, drive or scan copies are running."

- Who: anyone signed in.
- Ways in: this indicator, and each card's row and view.

#### Lessons

- Met: SRT-070, SRT-071, SRT-072, SRT-073, SRT-074, SRT-075, SRT-076, SRT-077, SRT-078, SRT-079, SRT-080, SRT-081.

## Backed up and safe to format

### Which copies count, and when a file is backed up

A file is **backed up** (safe) when it has a checked copy on the studio's NAS ("at home"), or checked copies on at least two different physical drives of kinds that count. The kinds that count are the NAS, the studio's own drives ("Ours") and a laptop's own disk ("Laptop"). The cloud backup counts for proxies and sound recordings but never for a camera original. Copies on the card itself, on another card, on a client's drive or on a drive whose kind is not set never count, and a copy known to be missing counts for nothing.

- Copies are counted per physical disk, worked out again whenever drives change: two partitions or volumes of one physical disk count once, on Windows and on macOS, and a folder that is really a link onto a drive counts as that drive.
- A checked copy on a drive that is unplugged still counts, shown as on that drive while it is away.
- Only a checked, whole copy counts. An unfinished or partial copy, an unchecked one, or a damaged one never counts.
- Copies are compared by recording, never by the folder they sit in, so two drives that filed the same footage differently both count.
- A card clip counts as on the NAS, showing the folder it is in, when a copy matching its name, size and recorded time is anywhere on the NAS and has been checked against the card's file, unless that copy is recorded as coming from another card.
- A file is **laptop-only** when its counting copies include a laptop and none is on a studio drive or the NAS.

A clip whose recording is split over several files is judged file by file: backed up and at home only if every file is, laptop-only if any file is, with the copy count being the fewest places any one file is in; it is card-only when every copy of every file is on a card or a client's drive. A clip with no original is judged by its sound.

- Windows and macOS: partitions of one physical disk count once on both.

### The files a card's verdict waits for

A card's verdict waits for every original a camera or recorder writes: every video, sound recording and still, including raw camera formats (Blackmagic RAW, RED, ARRIRAW, Canon raw, Nikon N-RAW, Phantom, Magic Lantern raw), 360-camera files, HEIF photos, broadcast and large WAV, DV, and every kind of media cards are recognised by. A file of a kind nobody has listed is waited for when it is 1 MiB or larger, so an unknown format never makes a card look safe.

Never waited for: camera proxies and thumbnails whose clip is on the card (anything in a "Proxy", "Proxies", "SUB" or "THMBNL" folder, and Sony's small proxy clips whose names end "S03"); files that go with a clip (metadata, thumbnails, low-resolution previews, subtitles, playlists, logs, text and settings files and the like); the camera's housekeeping files, which share names and sizes across cards; macOS "._" files; and files left unfinished or removed by an earlier copy. A proxy whose clip is not on the card is waited for like any original, so such a card is never called safe until that proxy has been copied. Every real media file on the card is matched wherever its copy sits in the studio, not only at the place this copy would put it.

### Each card shows a verdict on whether it may be formatted

For every card the person sees one verdict, worked out again within 20 seconds and at once when a copy is recorded, a drive's kind is set, a place to copy to is added or removed, or the record of every copy is updated:

| Verdict | When |
|---|---|
| "Safe to format" | every file the verdict waits for is backed up and none is laptop-only |
| "Safe to format · laptop only" | every such file is backed up, but some rest on a laptop and on no studio drive or the NAS |
| "Not safe to format" | anything else, including any damaged clip or bad copy |
| "Nothing to back up" | the card holds no footage, sound or photos |

Under it, a headline sentence and notes:

- A folder on the card could not be read: "Not safe to format: <n> folder(s) on this card could not be read (<up to 3 names> and <n> more), so nobody knows what is in them/it." with "Of the <t> files that could be read, <n> are also short of copies." (when any are) and "Take the card out, put it back and look again. If the folder still will not read, try another reader before anything is formatted." This answer beats every other, "Nothing to back up" included.
- Damaged clips or bad copies: the card says "Do not format" (see "A card with damaged clips or bad copies says plainly not to format it").
- "Nothing on this card needs backing up (no footage, audio or photos on it)."
- "Safe to format: all <t> files are at home."
- "Safe to format, but <n> of <t> files rest on the laptop alone. Put one on a field drive when you can."
- "Safe to format: all <t> files are on two drives that count."
- "Not safe to format yet: <n> of <t> files are short (<n> with no copy, <n> with one copy)." and, when it applies, "Some copies are on drives that do not count (a client's drive, a card, or a drive with no kind set)."
- When this computer has not yet heard from the studio's record: "This laptop has not heard from the studio's record yet, so only copies made here count."

Below the verdict, "Files that are short of copies (<n>)" lists up to 40 files as "<path> (<n> counting, <n> in all)", so the person sees how many separate copies each file has and which have only one before anything is formatted.

- Who: anyone signed in, and the editor at the computer in field backup.
- Ways in: on the card in the Sorter's list and view, and in field backup.

### Each clip shows how safe it is and where it is

Every clip on screen shows its backup state, from present, undamaged, checked copies only: **final, verified** (a checked copy in the sorted folders), **final** (in the sorted folders), **staging** (in staging), or none. It also shows where it sits now: on a card (it belongs to a card in a reader), in staging, in the sorted folders, or elsewhere. A filed clip is its own backup; a staging clip is backed up only once a copy is in the sorted folders.

When a clip (other than an image sequence) is not in the record of every copy under its own identity, the looser match (the same name, the same day and the same main-file size) is tried; of several, the safest wins (final, verified, then final, then staging), and the screen says the state came from a look-alike. A card clip already filed in the sorted folders (the same identity, or the same name and exact recording size) shows where it is filed. A state borrowed from a look-alike is shown but never makes a card safe to format until that copy has been checked against the card's file.

On the clip grid each clip also carries its copy count and its flags: at home, laptop-only, not backed up, not at home, card-only, every proxy in the cloud, and has a proxy not all in the cloud.

- On its own: each clip's backup state and place.

### A person can see every copy of a clip, and ask about any files

For one clip a person sees every copy, present or missing, of each of its files, grouped as original, proxy and sound, each with its drive and that drive's kind, its path, how carefully it was checked, when it was recorded, whether it is missing and since when, whether its drive is plugged in now and into which computer, and, for a missing copy, the open question about it. The clip's summary gives how many copies of each kind exist, which drives hold it, whether it is backed up, laptop-only, at home or not, and whether every proxy is in the cloud. A person can also list the clips that have a copy on a given drive.

For any list of files (by name, size and time) a person can ask where they are: every copy (drive, label, kind, path, how checked, missing or not) and a verdict for each: **at home** (a copy on the NAS); **safe** (at home, or copies on at least two of the studio's drives, laptops and the NAS); **on a laptop**; **laptop-only**; and how many drives count. Missing copies count for nothing.

- Who: anyone signed in.

### Taking a card off the list warns when it is not safe to

Before a card is taken off the list, the person is asked to confirm when:

- a copy is running: "A copy is running on <drive>. Dismiss anyway?" (taking it off is refused until the copy ends or is stopped);
- copies came out damaged: "<n> copies from <drive> came out damaged although the card is fine. The card is the only good copy: copy again before you format it. Dismiss it from the list anyway?";
- clips are damaged: "<n> clip(s) on <drive> is/are damaged, and so is/are its/their copy/copies. Do not format this card until you have taken a raw image of it (or you have decided those clips are lost). Dismiss it from the list anyway?"

Once confirmed it moves to the closed list at once. Nothing is copied or deleted.

### After a card copy, a fully backed-up card is marked backed up

When a card's copy finishes with nothing unchecked, and every clip on the card has a backup copy, and the card's serial is named as one of the studio's cards, the card is marked backed up in the crew's card record, by itself. When it cannot be (the serial is not named, or some clips have no copy yet), the person is told on the card, in words: "Not marked backed up: this card's serial is not named yet. Say which card it is." or "Stays marked used: <n> of <m> clips have no copy yet." A card is marked backed up only when every clip on it has a copy. A person can also mark one or more cards backed up or used by hand (see "The crew record which cards they used on which day").

- On its own: marking a card backed up when all its footage is safe.
- By hand: a person can mark any card backed up or used; the mark is kept until the card's next copy or the next change by hand.

### The crew record which cards they used on which day

On their phones, during a shoot, the crew record which of the studio's camera cards they used on which day, on a card-use page that installs to the home screen on iOS and Android and opens as an app. It shows English and Traditional Chinese. Logging a card's use on a new day always works, even when the card was used on earlier days and not yet backed up, and keeps every earlier use. The card list holds every card the studio owns, in order (CF cards before SD cards, then by number). It keeps working with no network on the phone and catches up when the phone is next online.

Each card shows its mark: "<card> ✓" (backed up), "✗" (not backed up) or "?" (unknown), with a tooltip giving its state, "last used <day>", "changed <ago> by <who>", the serials named for it, and "Click to mark it used|backed up". Clicking asks "Mark <card> as backed up|used (not backed up) …?", then "<card> marked <state>."; a failure shows "Could not flip <card>: <reason>" for 9 seconds. A count of cards not backed up is shown (hidden at zero). With no cards: "No cards known yet - add the studio's cards first." Hint: "Click a card to flip it. Red = footage on it is not backed up yet; a finished card copy flips it green by itself once its serial is named." Loading reads "Loading…", and a failure "Could not load: <error>".

- Who: the crew (anyone signed in) record use; anyone signed in may flip a card's mark.
- Name and search words: Card use. Search words: card use, card tracker, which cards, crew, shoot day.
- Phone and desk: the card-use page is made for a phone and installs as an app there; on a desk it is the same page in a browser.

### The card report: every card, every shooting day, and what is unaccounted for

A report lays the crew's card use against the calendar and the footage:

- the studio's cards in order (CF before SD, then by number): backed up or not, active, last change and by whom, last used, and the serials named for it;
- shooting days, newest first: each card used that day, who recorded it and when, its backed-up state, and the footage known to have come off it that day (clip count, the folders it landed in with time folders and proxy folders folded into their parent, and how many copies are in staging and in the sorted folders);
- each day's calendar events (dismissed shoots left out) with where the Sorter would file each and why: events with a folder first, then timed events, then all-day events, then repeating all-day events; and the day's likely event, "strong" when exactly one event has a folder, else "weak" when exactly one timed event exists. An event spanning several days appears on each (at most 60);
- **unrecorded**: footage that came off a named card on a day the crew did not record that card;
- **unmapped serials**: serials seen on copied clips that nobody has named, with volume label, kind, clip count, last seen, the last 4 days, and a hint (CF for Blackmagic RAW cameras, SD for Sony), most recent first.

Footage from before the comparison start date is not compared. The report also shows how many cards and use entries there are and which serials are named as which card.

- Who: anyone signed in.
- Name and search words: Card report. Search words: card report, shooting days, unrecorded, unmapped serials, card use.
- Setting: Compare card use from. Does: footage and card use before this date are left out of the card report. Default: 1 April 2026. Who: an admin. Applies to: the site. Search words: card report start, start date, card use, compare from.

### A report and a daily mail say what footage is not at home

A report lists every original and sound recording with copies but none on the NAS, grouped by category, then by the folder it sits in and where it is (drive labels joined by " + "), largest first within each category. The categories, in order: only on a laptop; on at least one studio drive; only on drives that are not the studio's (client drives, cards, unknown drives). It gives the total size and file count, the groups, the open questions, and a plain-text digest a person can read or paste:

- "Not at home: <size> in <n> folder(s)."
- "Only on a laptop - <size>:", "On drives we own, not at home - <size>:", "Only on drives that are not ours (client drives, cards) - <size>:", each followed by lines "<folder> (<size>, <n> files) on <where>".
- "Where did these go? <n> folder(s) no longer where they were:" followed by "<folder> on <drive> (<n> files, <size>) - probably <suggested drive>".

Sizes read in TB with one decimal from 1 TB, in GB with no decimals from 10 GB, otherwise in GB with one decimal.

Every day at 08:00 studio time the report is mailed to the alert recipients, from the alert sender address, through the alert mail settings, and is listed and tried again like every other message the product sends (see The dashboard: Alerts by mail, "An admin chooses who is told when the server finds a problem"), with the subject "[backups] Not at home: <size>" plus " · ⚠ <size> only on a laptop" and " · N to answer". Footage resting only on a laptop gets its own reminder every few days while it stays that way. Nothing is sent when there is nothing to report. When mail is not set up, the overview says that these reminders cannot be sent, instead of saying nothing.

- Who: anyone signed in sees the report; the mail goes to the alert recipients.
- Setting: Daily mail about footage not at home. Does: mails the alert recipients every morning what footage is not yet on the NAS. Default: on. Who: an admin. Applies to: the site. Search words: backups mail, not at home, daily report, laptop only, reminder.

### Drives and folders with automatic backup on are copied to the NAS when the computer is at home

For each drive with automatic backup on (never a system drive) and each watched folder with it on, while it is plugged into a watching computer, the product copies to the NAS every file under it that has no copy anywhere on the NAS. It looks about every 10 minutes, the first time about 90 seconds after starting. Files land on the NAS at "Auto backup" / the computer's name / the drive's label (else the folder's label, else the serial) / the same path as on the drive, so a whole drive lands as the whole drive would. Each part of that path has characters Windows cannot use turned into "-", leading and trailing spaces, dots and dashes trimmed, is cut to 80 characters, and becomes "drive" if empty. Nothing is ever deleted or overwritten, and every file is checked like a card copy.

It copies only while the computer is on the studio's home network: the NAS must answer at least 2 of 3 quick checks, with a typical answer under 15 ms. Away, nothing is copied and the source shows "waiting: this computer is away from home", with the reason: "away from home: the NAS's home address did not answer; nothing was copied", "... answered in N ms, not like the same network (under 15 ms); nothing was copied", or that the product does not know where the NAS is, so it cannot tell whether the computer is at home. After a failure or an away attempt, that drive is not tried again for 60 minutes. A watched folder whose drive is plugged into a different computer from the one the watch names counts as not plugged in.

Each source shows one state, kept across restarts: copying (files, size, whether more remains, destination, computer, also while waiting to start or checking), done (files, size, when), away, error (no staging folder on the NAS to copy into, the copy's own refusal, or "the copy ended <state>"), nothing to copy, or not plugged in.

- Who: an admin switches it on for a drive or folder.
- On its own: whether the computer is at home, and what still needs copying.
- By hand: an admin switches automatic backup on or off for each drive and folder.
- Setting: Automatic backup of drives. Does: copies drives and folders marked for it to the NAS whenever their computer is at home. Default: on. Who: an admin. Applies to: the site. Search words: automatic backup, auto backup, drive backup, home network.
- Setting: Automatic backup folder. Does: the folder on the NAS automatic backups land in. Default: "Auto backup". Who: an admin. Applies to: the site. Search words: auto backup folder, backup destination, NAS folder.

#### Lessons

- Met: SRT-082, SRT-083, SRT-084, SRT-085, SRT-086, SRT-087, SRT-088, SRT-089, SRT-090.
