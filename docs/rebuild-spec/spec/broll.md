# The b-roll archive

The b-roll archive is the studio's library of footage that is not an interview: clips downloaded from elsewhere and the studio's own shoots. Footage dropped into it, or found in it, is described shot by shot and has its speech transcribed with no further step, so that anyone signed in can find a clip by what is seen in it or said in it, play it in the browser, mark the part they want and send exactly that part to the timeline open in DaVinci Resolve on their own computer. Editors use it while cutting; an admin sets how the archive is laid out and sees everyone's drops. Editors also gather clips into client folders, each with a link a client opens with no sign-in to see previews and the studio's contact for licensing. The b-roll archive, client folders included, is one of the six parts a site switches on and off. When it is off nobody but an admin sees it, and only in settings, where it is listed with its switch: there is no b-roll page, no b-roll entry in the menu bar or in the general search, no b-roll lines, buttons or settings in the app on an editor's computer, no computer describes or downloads anything for b-roll, and every client link answers as "not available" until the part is switched back on; nothing is deleted, and switching it back on brings everything back as it was.

## Givens: browsers, cameras, files and Resolve

### A site switches the b-roll archive on and off

The b-roll archive is one part a site can switch on and off by itself. Switching it off hides it from everyone but an admin and stops its work everywhere: drops being taken in or described stop where they are and keep their place, no computer starts describing, transcribing or downloading what describing needs, and the app on each editor's computer drops every b-roll line, button, notification and setting. Client links answer with the page for a link that is not available. Nothing is deleted: the archive's files, every clip's description, transcript and category, every drop and every client folder with its link stay as they are, and switching the part back on carries on from there, with every client link working again unless it was revoked or has expired.

- Who: an admin.
- Setting: B-roll archive. Does: shows or hides the b-roll archive and client folders for everyone and starts or stops all b-roll work. Default: off. Who: an admin. Applies to: the site. Search words: b-roll, archive, footage library, stock, part, switch.
- When the help for the editing program is off: the archive stays usable; every place that would send a clip to the editing program offers to save the clip's file instead, and nothing on the archive's pages mentions the editing program.

### The facts of each camera file are read and kept with the clip

For each clip the archive records its length, frame rate, width and height, codec, the date it was shot (the date the camera or downloader wrote into the file), its frame count, its starting timecode and its bitrate. These facts about camera files hold:

- A file's own claimed frame count is trusted only when it agrees with length times frame rate to within one frame or 1 percent, whichever is larger. Otherwise the frame count, and so the exact length in frames, is treated as unknown.
- The starting timecode is taken from the file's own header first, then from a timecode track, then from any stream.
- A timecode at 29.97 or 59.94 frames per second written with colons is really drop-frame and is shown with a semicolon before the frames, except when the file carries a QuickTime timecode track, whose colons are a genuine non-drop timecode and are kept as written. A timecode that already has a semicolon, or is at any other rate, is kept as written. Only a file with no timecode track has its drop-frame form decided from its frame rate.
- A file with no readable duration is set aside with a plain reason (nothing in it can be sampled; rewrap the file and add it again). It never stops the work and is never shown in search.
- File names in Chinese, Japanese or Korean never break describing, transcribing or search, whatever language the computer is set to.

### Facts about browsers that every picture the archive shows respects

Browsers cannot play 10-bit video: a 10-bit preview plays as a black rectangle. So every preview, poster, hover strip and still the archive shows in a browser is 8-bit 4:2:0 whatever the source, and plays in Chrome, Edge and Safari. Editing copies made for Resolve may stay 10-bit. A browser preview with keyframes far apart seeks slowly, so every browser preview carries one keyframe per second and a seek lands at once.

### Names in the archive follow each disk's own rule for capitals

Comparing places follows each disk's own rule: editors' Windows and Mac disks ignore letter case, so a change of capitals in a name there is the same place and never makes a folder be described again; the NAS does not ignore case, so a capitals-only rename there is a real rename. Names in the archive itself are compared without case: a new name that matches an existing one apart from case is given the next free "_2", "_3" form, never landed in the same folder as the other. Every file brought in is tracked by its own identity, so two different files with the same camera name in one drop both arrive and are both described.

#### Lessons

- Met: BRO-001, BRO-002, BRO-003, BRO-004, BRO-005, BRO-006, BRO-007, BRO-008, BRO-009, BRO-011, BRO-012, BRO-013, BRO-014, BRO-015.

## How the archive is laid out

### The archive has two halves: the studio's own footage and Downloads

Every clip is either the studio's own footage (its own shoots) or a download (anything else). A shoot added through the archive's own page counts as the studio's own footage, as does any collection the studio archives as its shoot's proxies. A site also lists, by name, which other collections of the archive hold its own shoots. When that list is blank or has never been set, everything browses as Downloads.

- Who: an admin.
- Setting: Name for the studio's own footage. Does: the label the folder tree and the search page give the studio's own footage. Default: "Our Footage". Who: an admin. Applies to: the site. Search words: own footage, our footage, label, shoots.
- Setting: Collections that are the studio's own footage. Does: which collections of the archive browse and filter as the studio's own shoots rather than Downloads. Default: blank (everything else is Downloads). Who: an admin. Applies to: the site. Search words: own footage, collections, shoots, downloads.
- Setting: Top folder for the studio's own shoots. Does: the folder of the archive under which shoots added through the archive's page are filed. Default: the archive's own-footage folder. Who: an admin. Applies to: the site. Search words: archive folder, shoots, own footage, filing.

### An editor browses the archive through a folder tree with two roots

The folder tree always shows Downloads first, then the studio's own footage, each with its clip count. A root or folder with no clips is left out.

- Downloads is organised by subject: groups (each a subject name) holding categories, both ordered by clip count, largest first, with "Unsorted" always last when it holds clips.
- Own footage is organised by shoot: one group per collection, largest first, and under it the shoot's real folders up to 5 levels deep, in alphabetical order, with proxy folders left out.

A folder's count is exactly the number of clips clicking it shows, and every clip it shows can be previewed or says why not. A folder shows an expand mark only when it has sub-folders, and its sub-folders show only when it or one inside it is selected. Each folder's tooltip is its short name. Clicking a folder selects it; clicking the selected folder moves up exactly one level; clicking a selected root with no folder clears the choice. "clear" ("Show everything") selects nothing. Choosing a folder clears any folder chosen from a clip's path, goes to page 1 and makes a step Back can undo.

- Who: anyone signed in.
- Ways in: the folder tree, and the folders and category shown in an open clip.

### Where a clip is filed in the archive, and what it is called

The archive on the NAS is laid out so that a person browsing it in their file browser or in Resolve finds every clip by subject or by shoot:

- The studio's own shoots go under the top folder for own shoots, then the shoot's name (its spoken name, the name the studio calls it), keeping every folder of the shoot to any depth and leaving out any proxy folder level.
- Everything else goes under the downloads folder, by category.
- Each clip has its best media at its place (for a shoot archived as its proxies, the shoot's proxy; otherwise the original if the archive has it, else the preview), with its browser preview, poster and hover strip in a Proxy folder beside it, under the same name.

Names: characters Windows forbids (the less-than and greater-than signs, colon, double quote, both slashes, vertical bar, question mark, asterisk and control characters) become an underscore, trailing dots and spaces go, a name is at most 90 characters, and "untitled" is used if nothing is left. Chinese and other scripts are kept. A name already used or reserved in that folder, letter case and extension ignored, gets "_2", "_3" and so on. Names are given in one place for the whole studio, at the moment a clip is taken in, so two editors adding files at once can never take the same name and a file added by one never overwrites another's.

Once a clip has its place in the archive it keeps it: the file at that place is never overwritten with another clip's footage, a clip that has been categorised never moves to another category's folder, and a downloaded clip is placed only once it has its category, never first under a holding folder. Nothing writes over an original. A file in the archive that has to be replaced (for example a preview that would not play) is replaced in one step, and the copy it replaces is kept aside in the archive, never emptied on its own. Nothing in the archive is ever deleted by the product.

- On its own: each clip's place and name, from its collection, its shoot's folders or its category, and the names already taken.
- By hand: an admin renames a collection's archive name (see "An admin sets how each collection is described and transcribed").

### A collection is either originals, or a shoot whose own proxies are the archive copy

Whoever adds a collection to the archive says which of two kinds it is:

- Originals (the default): the downloaded or camera file is the archive copy. A file inside a folder named proxy, proxies, optimized, optimised, transcode, transcodes, transcoded, lowres, or low and res joined by an underscore (any depth, any letter case) is an editor's redundant encode: it is kept at its own place when the collection is copied into the archive, but it is never described, and browser previews are always made from the originals.
- The shoot's own proxies: the high-quality proxies the shoot already made are what is archived and described, and they can be cut and rendered in timelines without the camera originals. The camera originals beside them are recorded only, never described and never copied into the archive, and each is remembered as its clip's true original. A shot of 5 minutes or more never enters the archive this way.

Own-shoot footage is sorted into its folders without transcription, and can be described in full later; it is never ruled out. A clip's kind is decided when it is first seen and does not change later.

- Who: an admin.

### Every clip is filed under one subject category

Downloaded clips are filed by subject. The studio keeps a two-level list of categories (for example energy / nuclear), each with a short label, a description and the words that point to it. Each described clip is filed under exactly one category:

- A word of a category matches a whole word, or any word starting with it when it ends in a star, letter case ignored. The category matching most of the clip's themes wins; ties go to the narrower category.
- A clip inside a named person's folder under a folder called interview, interviews, interviewee or interviewees is that interviewee's b-roll, decided from the folder alone. No clip outside such a folder is ever filed as interviewee b-roll from what it shows.
- A clip matching nothing is tried against a few general fallback categories, and then goes to "Unsorted". No described clip is left without a category.

A clip already filed keeps its category for good: describing it again never moves it, and no category is ever removed. The list may only grow: a new list adds and updates categories and never takes one away.

The studio's starting list has 33 subject categories in groups:

| Group | Categories |
|---|---|
| energy | nuclear, renewables, power and grid |
| environment | waste and recycling, pollution and climate, conservation and wildlife, coastal erosion |
| economy | industry and manufacturing, work and wages, retail and commerce, agriculture and fishing, cost of living and housing, finance and markets |
| society | government and politics, protest and activism, policing and crime, education, health and welfare, transport and road safety, indigenous affairs, gender and LGBT |
| culture | heritage and religion, food and drink, performance and music, digital and social media, animation and anime, media and broadcasting |
| leisure | esports and gaming, travel and tourism, sport and outdoors, animals and pets |
| security | military and defence, emergency and disaster |

Besides these: interviewee b-roll, reached only through the interview-folder rule; five fallbacks (news broadcast, interviews, archival, public life, places); and the default "Unsorted".

- On its own: each clip's category, from its themes and its folder.
- By hand: an admin edits the category list and the words that point to each category; a clip's category, once given, is kept.

### A clip found at a new place keeps everything known about it

A clip is recognised by its content, not its name or place, so a renamed or moved copy is still the same clip. When footage the archive knows is found at a new place (for example a collection that was copied onto the NAS from where it was first described), it keeps its description, transcript, category and every other fact, and is not described again. Of several copies of the same content, the one furthest along is the one the archive keeps; the others are marked as duplicates of it and are never deleted. A move onto a place where another clip already is, is refused. Clips in a folder that are not yet in the archive are taken in like any new footage. A collection's own record (where it lives, whether originals or the shoot's proxies are archived) is only ever added to.

- On its own: which known clip a file at a new place is, from its content.

### A clip whose file has gone from the archive is hidden from search

A clip whose file is no longer in the archive is hidden from search and browsing, and comes back by itself when the file returns. Nothing known about it is forgotten. While the archive cannot be read at all (an unmounted share, an empty or missing folder), no clip is hidden on that account.


### An admin can check the archive for damaged files

An admin can have every clip's file in the archive opened and tested. The report reads "N of M source files cannot be read as media. These are damaged in the archive itself - re-download or re-copy them." and lists each by collection with its size and reason: "MISSING from disk", or the first line of what went wrong when it was read.

- Who: an admin.

#### Lessons

- Met: BRO-016, BRO-017, BRO-018, BRO-019, BRO-020, BRO-021, BRO-022, BRO-023, BRO-025, BRO-026, BRO-027, BRO-028, BRO-029, BRO-030, BRO-031.

## Describing and indexing clips

### Every clip in the archive is described shot by shot, with no further step

Every clip that enters the archive, by any way in, is described and becomes searchable with nobody doing anything more. The description is produced by the product itself and never depends on Resolve's own analysis data. Every clip carries the same description, transcript, search preparation and category whichever computer did the work. A clip's description is:

- A list of shots. A new shot starts whenever place, subject or camera set-up changes ("when in doubt, split"). Every shot change in the clip is looked at, plus the very start and the very end, and no stretch of more than 4 seconds goes unlooked at, so even a short shot is seen; a clip with no cuts is still looked at throughout. Each shot's start and end are the first and last moments actually looked at, never a guess, so shot times are as precise as that. Neighbouring shots that are nearly the same (most of their visible things in common and nearly the same wording) are joined into one shot covering both, so one continuous shot is not listed several times.
- For each shot, a terse description: 8 to 20 words of nouns and noun phrases, no sentences, no "footage showing", keeping colour, time of day, camera position and counts. At most 220 characters.
- For each shot, every visible thing, most specific first and including the plain broader terms (frigate, warship, navy ship; "sedan" is also found as "car" and "vehicle"), and the names of people, places, organisations and brands read from on-screen text, in both their original script and English. At most 300 characters.
- For each shot, text burned into the picture, word for word in its original script (Chinese, Japanese and Korean are never romanised): captions, lower thirds, channel names, dates, signs, banners, vehicle markings and name plates, stopping where the text becomes illegible and ignoring camera timecode, with a short English rendering beside it. It is transcribed even on newsreader and title shots. At most 300 characters each.
- Where the picture allows it, the setting and the camera's movement.
- Two to six themes for the clip (or each stretch of it): free tags such as the subject matter. At most 160 characters.
- Picture-quality flags (see "Each clip is flagged for poor exposure or focus").
- The category it is filed under (see "Every clip is filed under one subject category").
- The words spoken in it, with their times (see "Speech in a clip is transcribed so the archive can be searched by what is said").
- Which describing, at which quality, described it, and when.

Only what is visible is described: no narration, no story across frames, no guessed events or causes. Uncertainty is hedged briefly ("possibly melons") or the look is described instead. Red lights on vehicles are brake lights unless a light bar or livery shows; slow traffic is congestion, not an accident; lamps alone do not make a tunnel.

Describing a clip again replaces its whole earlier description, themes, flags and search data in one step, never mixing old and new shots, and search shows the change at once. It keeps the clip's category, duplicate mark, place and other facts unless new ones are given.

- On its own: every shot, its description, things, text, themes and flags, from the clip's pictures.

### A shot with nothing searchable in its picture gets one of five labels

A shot with no searchable picture is given exactly one of five labels a person can search for: newsreader (a studio anchor at a desk), title card, black frame, colour bars, station ident. Near spellings are folded into these: a news anchor, presenter or talking head is newsreader; a test pattern is colour bars; titles are title card; a blank frame is black frame; a channel ident is station ident.

### Each clip is flagged for poor exposure or focus

A clip can carry picture-quality flags from a fixed list of six: shaky, soft focus, overexposed, underexposed, noisy, rolling shutter. They are measured from the frames looked at:

- overexposed: at least 30% of the frames are very bright on average, or at least a quarter of their pixels are clipped white;
- underexposed: at least 30% of the frames that are not plain black are very dark;
- soft focus: the frames that are not black are, on the whole, blurred.

Shaky, noisy and rolling shutter are given when describing finds them.

### Speech in a clip is transcribed so the archive can be searched by what is said

The spoken words in every clip are turned into timed passages: neighbouring lines are joined while the pause between them is at most 1 second and the passage stays under 30 seconds. The language is detected on its own unless the collection fixes one (for example Chinese). A clip with no sound gets an empty transcript and is not tried again. A clip with sound but no picture is still transcribed, is searchable by what is said, and is still placed in the archive. Speech search works as soon as a clip is transcribed, without waiting for its pictures to be described.

Text that speech recognition invents from silence or music is thrown away: any passage holding a subtitle-credit or "please like and subscribe" line in Chinese (both scripts: the subtitle-volunteer credit, subscribe, tip and reprint notices, and one news programme's credit), or in English "subtitles by", "subtitled by", "thanks for watching", "thank you for watching", "please subscribe" or a subtitling website's name. What is left is rejected whole when it is empty, when one line makes up 60 percent or more of three or more lines (stuck repeating), when it has under 12 characters in all, or when the clip is over 2 minutes and the text averages under 8 characters a minute (noise, not speech). A rejected transcript counts as tried, so the clip is not transcribed again.

A collection can have transcription switched off, and a clip longer than its collection's longest clip, or with no readable duration, is never transcribed or described (see "An admin sets how each collection is described and transcribed"). Both always hold.


### Describing needs a graphics card and offers two quality levels, Good and Best

Describing runs on a graphics card, never on the processor alone: an NVIDIA graphics card on Windows, or an Apple Silicon Mac, where the Mac's shared memory is what counts. A computer without one cannot describe clips, and the work is done on another of the studio's computers that can (see Work shared out across the computers). Two quality levels exist:

| Level | Needs | Download, once per computer | Compared |
|---|---|---|---|
| Good (the default) | a graphics card with 8 GB of memory, or an Apple Silicon Mac with 16 GB | about 3.3 GB | about 20 seconds a clip on a high-end gaming graphics card |
| Best | 12 GB, or 24 GB on Apple Silicon | about 6.2 GB | "a little sharper on on-screen text and vocabulary", about twice as slow |

Wherever a level is offered, its tooltip states the memory it needs. The product recommends the best level a computer can run (Best at 12 GB or more, or 24 GB on Apple Silicon; Good at 8 GB, or 16 GB; otherwise none). The quality used is recorded with each clip's description.

The site's level is the default for every drop; the person dropping clips may choose the other level for that drop. A level a computer cannot hold is never downloaded there and never run there. Its refusal names the memory figure and is shown to the person on the page, as a notification and in the app's menu on that computer, and to admins on the dashboard:

- "Can't index b-roll: no usable GPU on this computer (<detail>). Indexing needs an NVIDIA GPU or Apple Silicon"
- "Can't index b-roll: Best needs N GB VRAM, this GPU has M GB - choose Good" (on a Mac: "unified memory", "this Mac has")
- "Can't index b-roll: Good needs N GB VRAM, this GPU has M GB - indexing needs a bigger GPU: this batch can run on another computer"

- Setting: B-roll describing quality. Does: whether new clips are described at Good or Best unless a drop chooses otherwise; anything else is refused. Default: Good. Who: an admin. Applies to: the site. Search words: describing quality, good, best, model, b-roll indexing, VRAM.
- Ways in: the site setting, and the choice on each drop.

### What describing needs is downloaded once, checked, resumable and then works offline

The first time a computer describes clips at a level, it downloads what that level needs (sizes in the table above). Before it starts, a notification says what and how big: "Downloading the Good b-roll indexing model (3.9 GB). Right-click the tray icon to see progress." and when done "The b-roll indexing model is ready. Indexing starts now." Progress shows on the page, in the app on that computer and on the dashboard as percent, rate and time left: "Downloading <name>: 61% at 38 MB/s, about 1 min left" (time phrases: "almost done", "about N sec left", "about N min left", "about Hh Mm left"). The person starting a drop is asked first (see "Running a drop asks first when it is large or needs a download").

- Every file is checked against a known fingerprint. One that does not match is deleted and fetched again: "the model download's checksum did not match. The file was deleted and will be fetched again".
- A download that is interrupted, by quitting or a dropped connection, resumes where it left off ("the download was stopped - it will resume where it left off"), and a stalled connection is recovered from on its own.
- Downloads come only from a short fixed list of trusted places, over a secure connection; anything else is refused.
- Not enough disk space: "Not enough disk space for the Good model: needs about X GB free at <folder>, has Y GB - free some space and try again". A disk whose free space cannot be measured does not refuse.
- Any other failure: "the b-roll model could not be downloaded: <error>". Success: "<Good|Best> is ready".

Once present nothing is fetched again and describing works with no internet.


### A computer says whether it can describe clips, and every reason why not

The b-roll page asks the app on the editor's computer whether this computer can describe clips, and gets an answer at once: yes, or every reason why not, in these words:

- the computer's graphics card cannot run the description (with the refusal above);
- "this computer has no synced tree, so there is nowhere to stage the clips";
- "only X GB free where the clips would be staged (the floor is Y GB)";
- "this computer is already indexing a b-roll batch";
- "nobody is signed in on this computer";
- "b-roll indexing is switched off on this computer".

A one-off download that describing needs and that is not yet on the computer is not a reason: it is fetched the first time a drop runs. The answer also gives the computer's graphics card and its memory, which levels fit, which is recommended, which are already downloaded and how big a download would be, the free space where dropped clips are kept, and whether a drop is running. It is asked afresh whenever the page asks, so a computer never keeps an out-of-date answer after it restarts.

### Describing keeps the computer it runs on usable

When the person dropping clips chooses "Only when idle", describing works only while nobody has been at that computer for the computer's quiet time (5 minutes unless changed) and Resolve is closed, as for all shared work (see Work shared out across the computers: When a computer counts as free and able). "Start now", from the page or from the app on that computer, makes a waiting drop work at once until it ends or is paused. The conditions are checked again between every step of every clip, so a person coming back loses at most the step in progress, and the graphics memory used for describing is given back the moment work stops. When the computer cannot tell whether the person is away it counts them as present; when it cannot tell whether Resolve is open it counts it as open.

While describing runs on a computer someone is working at, it stays under the site's share of that computer's capacity. At most one describing holds a graphics card at a time: one is stopped before another starts. Making proxies on that computer waits while describing runs, and says so ("indexing b-roll first"). While a computer is describing, or downloading what describing needs, it is kept from sleeping, and a shutdown is met with a warning (see The app on each editor's computer: Settings, records and background work).

- Setting: Share of a working computer that describing may use. Does: caps how much of a computer's capacity background describing takes while someone is working at it. Default: 60%. Who: an admin. Applies to: the site. Search words: capacity, background, usable, indexing load, share.

### The computer doing the work shows what describing is doing, and the person at it can pause, resume, start now or cancel

While a computer is describing a drop, the app on it shows one line, in clips:

- a warning for the drop first, when there is one (for example the graphics card refusing for lack of memory);
- "Downloading the b-roll indexing model… P %";
- "Indexing b-roll… D of T (stops when you're back)" (without the tail when started with "Start now");
- "B-roll indexing waits until you're away: N clips queued" (while the person is at the computer or Resolve is open);
- "B-roll indexing paused: N clips left";
- "Uploading indexed b-roll is paused: N left" or "Uploading indexed b-roll… N clips left";
- "N b-roll clips could not be indexed: <first file name> (<reason>), and M more", with up to 20 failed clip names and their reasons in its status.

What a drop is waiting for is said in words, the first that applies: b-roll indexing is switched off on this computer; "waiting: the sync drive is not connected"; "paused" (by the person, from the app or the page); "waiting: this computer's sync config needs fixing"; waiting for the one-off download describing needs; "fetching the local indexing model" (or the level does not fit, shown once as a warning); nothing to do; "waiting until you're away from the keyboard"; "waiting: DaVinci Resolve is open"; working.

Buttons while a drop exists: "RESUME B-ROLL INDEXING" when paused; otherwise "INDEX B-ROLL NOW (don't wait until I'm away)" (only while waiting) and "PAUSE B-ROLL INDEXING"; then "SHOW B-ROLL INDEXING PROGRESS" and "CANCEL THE B-ROLL BATCH…".

- Index now: "Indexing the b-roll batch now. It keeps going while you work." (or "B-roll indexing is not set up on this computer.")
- Pause: "B-roll indexing paused. Nothing already indexed is lost."
- Resume: "B-roll indexing will carry on from where it stopped."
- Cancel asks "STOP INDEXING THIS B-ROLL BATCH": "<done> of <total> clips are already in the archive and they stay there. The rest will not be indexed. The clips themselves are not deleted." with "STOP INDEXING", then "B-roll indexing stopped."

The progress window "INDEXING B-ROLL" ("Your clips are indexed on this computer and uploaded to the archive. Closing this window does not stop it.") opens from the menu, or by itself when a drop starts or a download begins, shows up to 5 clips that failed with their reasons, and has Pause, Resume, Start now and Cancel (see The app on each editor's computer: Windows, dialogs and notifications). Signing out on the computer stops new work at once. Quitting the app keeps the drop, which carries on where it was at the next start.

- Who: the person at the computer doing the work.
- Ways in: the app on that computer, the drop on the b-roll page, and the dashboard (see "A person pauses, resumes, starts now or cancels their drop").

### An admin sees describing on every computer

For each computer, the dashboard shows whether it is describing a drop, which drop, its state and what it is waiting for, done, total and failed counts, the current clip and its percent, the quality level, now or while away, whether it is uploading or uploads are paused, the download percent of what describing needs, and any warning (for example not enough graphics memory), shown even when nothing runs. A computer with nothing to say shows "not indexing". It also shows how much space the computer's held drops take, how many drops, the oldest, split into finished, never indexed and held. An admin can ask the computer to stop a drop from here.

- Who: an admin.
- When the b-roll archive is off: no b-roll describing is shown and no stop is sent.

### An admin sees how far the archive is described

An admin can see how much of the archive is described, out of all clips not skipped, with the count in each state; how many shots there are and how many have on-screen text; how many spoken passages there are and how many are ready for search by meaning; how many shots got each of the five labels; how many clips failed, with the first ten named; and the free space where describing works.

- Who: an admin.

### A clip that cannot be described fails alone, with a reason a person can read

Each problem is kept against that clip only, and the rest of the drop carries on. A clip gets at most two tries. A failed clip always shows why, and a later look at the archive never blanks that reason. The reasons:

- "this clip could not be indexed: <error>";
- "the source file is not on this computer any more", or after a restart "the source file is no longer on this computer (the drive was unplugged, or it was moved)";
- no length recorded in the file: nothing in it can be sampled, rewrap the file and add it again;
- longer than its collection's longest clip: "longer than <cap>s cap (<length>s) - not indexed" (it is still placed in the archive);
- unreadable: "file is truncated or incompletely downloaded" when the file was cut short, or "file is not valid media";
- "no frames could be extracted - unreadable or truncated media";
- its preview could not be made correctly (see "Each clip's preview is checked complete before it counts");
- "the local model could not describe this clip (<error>)", or the describing declined to describe it, or its answer was unusable twice running;
- "the archive would not take this clip's description: <detail>" (the next try describes it again).

A clip with no picture is not a failure: it reads "audio-only (no video stream) - transcript indexed, no visuals". A failure while transcribing or preparing search never fails the clip; it is tried again.

### A problem every clip would share stops the work with one message and keeps the queue

When describing fails for a reason every clip would share (the describing does not start or does not answer, or a setting every clip would repeat), the work stops at once without marking the clip it was on, says "The queue is unchanged - fix the cause and re-run to resume", and resumes where it stopped. Brief errors are tried again for a while first. Any other failure is the clip's own, names its cause, and the queue moves on. When the server is busy for a moment, finished work is offered again, never thrown away.

### Long describing work survives restarts and shows live progress

Describing outlives the window or page that started it, survives the app quitting, a crash and a reboot, and resumes each clip at the step it reached, never redoing finished work. While it runs it shows how many clips are left, clips per minute, time to finish, and counts done, failed, skipped and not started, in local time, as sentences whose age shows ("updated 2 min ago"). When it makes no progress for several minutes it says so. It reports success only when every clip is done.

### An admin can set a time after which no new clip is described

An admin can set a clock time after which no new clip is started; clips already started finish and are saved, and the rest stay waiting. There is no limit on how many clips are described in a day.

- Setting: Stop starting new clips at. Does: a clock time after which no new clip is started until the next day; clips under way finish. Default: none. Who: an admin. Applies to: the site. Search words: stop time, overnight, cutoff, indexing hours.

### An admin sets how each collection is described and transcribed

Each collection of the archive has, besides its place and an optional note:

- Describe its clips (default on). Off: each clip still gets its preview, hover strip, poster and transcript, but nothing looks at its pictures; it rests as "kept, not described". Switching it back on makes every such clip be described next, however the work is started.
- Transcribe its speech (default on). Off: no transcript is made for its clips.
- Language of its speech (default: detected on its own).
- Longest clip to index (default: no limit). A longer clip is not described or transcribed, is marked skipped with the reason "longer than <cap>s cap (<length>s) - not indexed", and is still placed in the archive.
- Folders to leave out (default none): each excludes its whole folder at any depth, letter case ignored; "anything/AE" leaves out an AE folder at any depth.
- Its kind: originals, or the shoot's own proxies (see "A collection is either originals, or a shoot whose own proxies are the archive copy").
- The name its clips get in the archive, when it should differ from the folder's own name. Changing it later renames the collection's folder in the archive in one move, never copying it again, and every computer and Resolve follow the move (see Proxies and file moves: Moves that reach every computer).

A mistake (an unknown kind, an exclusion list written as a single word) is refused with a message naming the setting.

- Who: an admin.
- Setting: Describe a collection's clips. Does: whether its clips' pictures are described. Default: on. Who: an admin. Applies to: a collection. Search words: describe, index, collection, visuals.
- Setting: Transcribe a collection's speech. Does: whether its clips' speech is transcribed. Default: on. Who: an admin. Applies to: a collection. Search words: transcribe, speech, collection, transcript.
- Setting: Longest clip to index. Does: clips longer than this are placed in the archive but not described or transcribed. Default: no limit. Who: an admin. Applies to: a collection. Search words: length cap, long clips, skip, limit.
- Setting: Folders to leave out. Does: folders of a collection that are never taken into the archive. Default: none. Who: an admin. Applies to: a collection. Search words: exclude, leave out, ignore folders.
- Setting: Archive name of a collection. Does: the name the collection's folder has in the archive. Default: the folder's own name. Who: an admin. Applies to: a collection. Search words: archive name, rename, collection, folder name.

#### Lessons

- Met: BRO-032, BRO-033, BRO-034, BRO-035, BRO-036, BRO-037, BRO-038, BRO-039, BRO-040, BRO-041, BRO-042, BRO-043, BRO-044, BRO-045, BRO-046, BRO-047, BRO-048.

## Search

### The b-roll page is the archive's search

The b-roll page is part of the dashboard, behind its sign-in, and carries the dashboard's menu bar. It holds the search box, the narrowing choices, the folder tree, the results and the open clip. One page of results answers within about a second even over a remote connection, and even for very common or misspelt words.

- Who: anyone signed in.
- Name and search words: B-roll archive. Search words: b-roll, footage, archive, stock footage, clips, search.

### Some clips never appear in the archive, whether searching or browsing

Never shown in search, browsing or folder counts: editors' redundant proxy copies; camera originals of a shoot archived as its own proxies; clips still being taken in, until their description, still, hover strip and preview are all safely in the archive; and clips that are byte-for-byte copies of another clip already in the archive (only the kept copy shows). A clip with an editing proxy appears once, with its preview, never a second time as its proxy. A clip whose still or hover strip is missing shows a placeholder saying so.

### An editor searches the archive by words, and finds both what is seen and what is said

Typing in the search box searches 250 ms after typing stops and goes back to the first page. Words are separate terms and every term must match; text in double quotes is one exact phrase. Punctuation is taken as plain text, never as search syntax. English words match their other forms ("surf" finds "surfing"). What is searched: what is seen (each shot's description, visible things, setting, on-screen text in the original and in English) and what is said (the transcript).

Chinese is matched so that Traditional (Taiwan) and Simplified script find each other whichever was typed, two-character words are found as words, and part of a Chinese word is found too. An unquoted Chinese term of more than two characters also finds clips where its words appear separately; quoting keeps it as one unbroken phrase. So 堵車, its Simplified form and 同志伴侶 all find clips whose speech or on-screen text holds them in either script. A Chinese, Japanese or other non-Latin search finds matching clips in every way of searching where the same search in English would.

Clips are ordered by their single best matching moment. Each result carries up to 20 matching moments, best first, each with its time range, a snippet with the matched words highlighted, and whether it was seen or said. A clip newly described, transcribed or removed shows in search at once, with nothing restarted.

### An editor narrows a search, and every narrowing applies together

The narrowings, all applied at once:

- a subject category, which includes everything under it ("military" also finds "military / naval");
- own footage or Downloads (if the studio has no own footage known, own footage shows nothing and Downloads shows everything);
- a shoot, and optionally a folder inside it, or a folder of a collection: a folder matches that exact folder and everything below it, at folder boundaries ("Day 1" never matches "Day 10"), with every character taken literally;
- "hide flagged": one tick per quality flag (shaky, soft focus, overexposed, underexposed, noisy, rolling shutter), hiding every clip carrying any ticked flag;
- what to search: All, Visuals ("what is seen on screen, including burned-in on-screen text") or Transcript ("what is said (spoken word)"). With Visuals or Transcript a clip with no match of that kind is dropped, and the results say which was searched.

A new folder or category replaces the old one, never adds to it. Every narrowing in force is named above the results and can be cleared, and a folder shows the same choices however it was reached.

### With no search words, the archive is browsed newest first

With the search box empty, every clip the narrowings allow is listed, newest added first, with no matching moments, and the total is the full count.

### Search finds the words first, then a few clips related by meaning

Results are every clip the words find, in their order, then up to 5 more clips found only by meaning, always after every word result, under a "Related" heading and with a dashed border. A meaning match on a clip the words already found never changes the order. Meaning matches count only when close enough. If the search is mostly Chinese and the words found nothing, no related clips are added, so an empty result stays possible. When meaning search cannot run, the search still answers by words and carries "Keyword only right now: the meaning-based half of this search is not available.", with the reason as its tooltip, word for word: "Meaning-based search is not available on this server: <a part it needs> is missing.", "Meaning-based search is not available on this server: the query model is not installed." or "No clips have been prepared for meaning-based search yet, so it can only find nothing."

### Search forgives misspellings and partial words when the exact words find little

When the exact words find fewer than 5 clips, the search also tries: the start of any word of 5 or more letters ("ambul" finds "ambulance"; shorter words are never expanded, so "mars" never finds "marriage"); the Chinese word split above; and spelling correction, replacing each word of 3 or more letters that the archive has never seen by the closest whole word of similar length the archive does contain, only when it is very close ("ambluance" becomes "ambulance", never "Blu"). Forgiving matches never replace the snippet shown for an exact match.

### The search page says while it is searching and when a search fails

While a search runs the results are dimmed and "Searching..." shows above them, and screen readers are told the area is busy. The results on screen always belong to the newest search or narrowing the person made: an older answer arriving late is thrown away. A failed search shows "Search failed: <message>".

### The page's address holds the search and the open clip

The address holds the search words, category, own footage or Downloads, folder, what to search, the hidden flags, page, open clip and the second the clip was opened at. Reloading, or following such a link, restores the search and reopens the clip at that second; the highlighted matching moments on the clip's bar are not restored from a link. Back and Forward walk folder choices, pages and clip openings before leaving the page; typing in the search box does not add steps. Links to a collection that has since been renamed still open it.


### A line above the results says what is being shown

The line reads, as applicable and joined by " · ": `search: "<words>"`, `folder: <root> / <folder>`, `folder: <collection>/<path>`; or "browsing all videos" with nothing chosen. When a folder from a clip's path is chosen, a "clear folder" link is shown.

### Results come 24 to a page

The pager reads "← prev", "<from>-<to> of <total>", "next →". Each press is a step Back can undo.

### An empty result says why and offers the likely way out

Browsing: "There are no clips in <scope>." where the scope names the root, folder or path, or "the whole archive". Searching: `Nothing matched "<words>" in <scope>.`, then "N clips were searched." (or "1 clip was searched."), then "Try fewer words." If meaning search is unavailable, its reason is added as a warning. Links are shown only for what is actually in force: "clear the folder filter", "stop hiding flagged clips".

#### Lessons

- Met: BRO-049, BRO-050, BRO-051, BRO-052, BRO-053, BRO-054, BRO-055, BRO-056, BRO-057, BRO-058, BRO-059, BRO-060, BRO-061, BRO-062, BRO-063, BRO-064, BRO-065, BRO-066, BRO-067, BRO-068, BRO-069, BRO-070.

## The clip player

### Results are thumbnails that scrub on hover and show the moment that matched

Results are thumbnails only, with no text under them; names and buttons appear only when a clip is opened. Each thumbnail is a still with the clip's length (m:ss) in a corner and a tooltip "<file name> - <category>". Each clip's still belongs to that clip alone. Stills load as they come into view; a clip with no still shows a "no preview" placeholder. Moving the pointer across a thumbnail shows the frame at that point of the clip, keeping up with the pointer. In search results the thumbnail holds the frame of the best matching moment instead, and returns to it when the pointer leaves, for clips of any length. Each thumbnail has a "+" that adds the clip to a client folder without opening it. Clicking a thumbnail opens the clip at its best matching moment, or at its start when browsing, never at a moment belonging to a clip opened earlier.

- Phone and desk: the "+" shows on hover on a desk, and always on a touch screen or when the thumbnail has keyboard focus.

### Opening a clip shows its player and everything known about it beside the results

The clip opens beside the results, which keep their place, with its video in view without scrolling. A "close this clip" control goes back, as Back would. The player has no built-in controls and starts at the matching moment that opened it. Shown:

- the file name;
- its path, where the collection and every folder are clickable and show that folder (clearing the search words), then the file name, length and frame rate ("@ ?fps" when unknown);
- "category: <name>", clickable to show that category (clearing the search words and folder), or "none";
- "themes:", each clickable to search for it as an exact phrase;
- "flags:", listed, not clickable;
- "Visual segments": each time range (hours:minutes:seconds:frames at the clip's rate, or 24 if unknown), what is seen, on-screen text in quotes and its English;
- "Transcript", only when the clip has speech: each time range and the words said.

Clicking any segment or transcript line jumps there and plays. "+ client folder" adds the clip to a client folder.

### The clip's bar shows the matching moments, the segments, the playhead and the in and out points

The bar under the picture marks each search match that opened the clip as a band (never narrower than half a percent of the bar; a match with no end is drawn one second long, and no mark draws beyond either end of the bar), the start of each described segment as a tick, the playhead, and the in and out points. An in or out point shows at once as a red line, drawn above the playhead, as soon as it is set, and the range between them is shaded once both are set. Pressing and dragging with the left button seeks to that point, pausing while dragging and resuming if it was playing, with the picture keeping up. Readouts show the current timecode, IN, OUT and the play rate.

### Dragging across the picture scrubs, and clicking it plays or pauses

Pressing and dragging sideways on the picture scrubs from where the press began, the full width being the whole clip, once the pointer has moved a few pixels; the picture keeps up while dragging. A click without moving plays or pauses.

### An open clip is driven from the keyboard

Only while a clip is open, never while typing in a field and never while a panel or the client-folder list is open:

| Key | Does |
|---|---|
| Space or K | play and pause |
| L | play forward; each further L goes 1x, 2x, 4x, 8x |
| J | play backward the same way, stopping at the start |
| Left and Right arrows | pause and step one frame |
| I and O | set the in and out point at the current position |
| Enter | append to the timeline |
| Shift+Enter | place at the playhead |

A focused button or link always keeps its own Enter, so nothing reaches Resolve unless the editor meant to send it. A help line reads "space/K play/pause · J/L shuttle · ←/→ ±1 frame · I/O set in/out · Enter append · ⇧Enter place at playhead".

- When the help for the editing program is off: Enter and Shift+Enter do nothing and the help line leaves them out.

#### Lessons

- Met: BRO-071, BRO-072, BRO-073, BRO-074.

## Previews made for the archive

### Each clip gets a browser preview, a poster, a hover strip and a thumbnail

Every clip in the archive gets, made from its original (never from an editor's proxy):

- A browser preview: 540 lines high, never enlarged, much smaller than the source, H.264, 8-bit 4:2:0 so 10-bit camera footage plays in every browser, a keyframe every second so scrubbing is quick, AAC sound at 128 kbps, set up to start playing before it has fully downloaded, and carrying the source's timecode (with the drop-frame rule of "The facts of each camera file are read and kept with the clip").
- A poster: the picture one tenth of the way into the clip, 640 pixels wide.
- A hover strip: one picture every 2 seconds, 240 pixels wide, ten across, at most 240 pictures; a longer clip spaces them further apart so any clip, hours long included, gets a strip of bounded size. The strip's layout is measured when it is made, so the hover scrub lines up exactly.
- A small thumbnail, 160 pixels wide.

The poster and strip are taken from the preview, or the original when there is no preview. A clip shorter than the spacing still gets a preview and stills from its first frame. A still that fails does not fail the clip. Making a preview has a time limit that grows with the clip's length and the computer's speed; running out is reported as "timed out", never as a bad file.

### Each clip's preview is checked complete before it counts

Before a preview is accepted it is played through end to end. Any decoding error, any difference from the source's frame count (Resolve refuses a proxy whose frame count differs), or a length under 97 percent of the source's rejects it, and it is made once more the slower, surer way. If it is still wrong the clip fails with the reason: "N decode errors", "X frames of the source's Y", or "truncated: Xs of Ys". A file that arrives empty is never accepted, whatever size was declared.

### An editing copy is made only when the original is too heavy to edit with

An original is light enough to edit with as it is when its video is H.264, HEVC or any ProRes, it is at most 1080 pixels tall, and its bitrate is at most 12 Mbit/s. When the bitrate is unknown the answer is "cannot tell", and that counts as heavy; any other video type is heavy. For a heavy original an editing copy is made as well, of the same kind as the proxies the product makes for projects (see Proxies and file moves: What a proxy must be), carrying the source timecode. An original light enough gets none ("original is edit-weight"). Camera raw never gets one here ("needs Resolve"). An editing copy that fails its exact frame check, or cannot be made, is dropped with its reason, and the clip still goes live with its preview.

- On its own: whether an original is too heavy, from its codec, height and bitrate.

### A shoot archived as its proxies gets any missing proxy made first

For a shoot archived as its own proxies, every camera file without a proxy beside it (in a Proxy folder, under the same name) gets one before the shoot enters the archive, made with the same settings as editors' own proxies, carrying the source timecode, written aside and only then put in place, and checked as a preview is. Folders that look like proxy folders, names starting with "@" or a dot, and the collection's left-out folders are skipped; a clip of 5 minutes or more is left out. Each clip's result (made, unreadable, no length, no picture, over 5 minutes, bad result, failed) is recorded and shown. Camera files are never moved, changed or deleted.

#### Lessons

- Met: BRO-075, BRO-076, BRO-077, BRO-078, BRO-079, BRO-080, BRO-081.

## Bringing new footage in

### An editor adds footage by dropping it on the b-roll page or choosing it on their own computer

A "+" button ("Add clips to the archive (or drag clips/folders anywhere on this page)") opens "Add b-roll". Dropping files or folders anywhere on the b-roll page opens it too, with a full-window message "Drop clips or folders to add them to the archive" that stays steady while dragging. "Choose files…" and "Choose a folder…" open the computer's own file or folder chooser ("Choose clips to index", "Choose a folder of clips to index"); clips chosen this way are worked on where they lie, never copied through the browser, and are marked "indexed in place". Escape closes "Add b-roll", and closing it stops it refreshing.

Once a drop is run, nothing more is needed: every clip gets its previews, is described and transcribed, is filed in the archive and becomes searchable. That work is done on a computer of the studio's that is able and free (see Work shared out across the computers), starting with the computer the clips were dropped from when it is able; the person sees its progress on the page, in the app on the computer doing it, and on the dashboard, and an admin sees every computer that is describing.

The app on the editor's computer only ever reads, uploads or reveals files the editor chose in the computer's own chooser, or dropped: a page can have files worked on in place only if they lie inside a folder the editor actually chose there (the last 32 chosen folders are remembered across a restart of the app). Otherwise a file is refused: "that file was not chosen on this computer: use the "choose from this computer" picker and pick it again".

The chooser offers at most 2,000 files; a folder chosen is searched all the way down for video files, each listed with its size and sub-folder. Only one chooser opens at a time; a second request gets the first one's answer. It is refused while another of the app's windows is open: "Another CCSync window is open on this computer. Close it, then choose again." Closing the chooser reads "cancelled", and any other failure "the file picker could not be opened on this computer". The page waits up to 5 minutes for a choice; after that the chooser closes as if cancelled.

A red notice that stays until dismissed ("dismiss") holds refusals.

- Who: anyone signed in, for a computer they are at.
- Ways in: dropping anywhere on the b-roll page, the "+" button, and the file and folder choosers.
- Windows and macOS: the chooser is the system's own on each; on both it closes by itself after 5 minutes.

### Only video files are taken, and camera raw is not

A drop's every nested folder is read and only video files are taken: MP4, MOV, M4V, MXF, MTS and M2TS (AVCHD), AVI, MKV and WebM, in any letter case. Names starting with a dot, and files Windows marks hidden or system, are skipped. Camera raw (Blackmagic RAW, RED, Canon Cinema RAW Light) is not taken, because it cannot be decoded without Resolve; a shoot in raw enters the archive as its own proxies. "N of M files were not video and were left out."; nothing usable: "Nothing there this app can index: b-roll takes video files (...)". A single file of another kind is refused on its own line ("<kind> is not a video this machine can index") while the rest of the drop goes ahead. A file name may be up to 255 characters and a sub-folder path up to 1024.


### A drop holds at most 2,000 clips and is taken only if it fits

A drop holds at most 2,000 clips: "Only the first N clips were taken: a batch holds 2000." or "A batch holds at most 2000 clips. Run this one first." Refusals of the whole drop, before anything is copied:

- nothing offered: "no clips were offered";
- more than 2,000: "that is N clips; 2000 is the most one batch can hold";
- this computer has no synced tree: "this computer has no synced tree, so there is nowhere to stage the clips";
- it does not fit: a drop that would leave less than the computer's floor of free space (20 GB unless changed) where dropped clips are held is refused whole: "Not enough space where the clips would be staged (<folder>): X GB free, and this drop needs Y GB on top of the Z GB floor. Nothing was staged.", followed by whichever applies: "N GB of that drive is finished b-roll staging: open Settings from the tray icon and use CLEAR FINISHED STAGING"; "N GB of that drive is b-roll staging that was never indexed: open the b-roll page and index or re-drop it, and it is cleared automatically after 7 days"; "N GB more is b-roll staging kept on this computer because the archive does not have those files yet; it is released once they reach it"; "Free some space and it will continue";
- the holding folder cannot be made: "CC Sync could not create its staging folder: <reason>".

The same one rule (the drop, plus the floor) is used whenever the computer is asked, so a computer never says it can take a drop and then refuses it. A disk whose free space cannot be measured never refuses.

- Setting: Keep this much space free. Does: the one floor of free space on this computer that nothing CC Sync writes there (dropped b-roll and music, proxies, downloads) ever eats into. Default: 20 GB. Who: an editor for their own computer, or an admin. Applies to: a computer. Search words: free space, floor, disk full, staging, reserve.

### A drop is filed under a shoot name, suggested and made safe for every computer

One dropped folder becomes the suggested shoot name and is not repeated as a sub-folder; several dropped folders keep their names as sub-folders. Otherwise the suggestion is "<YYYY-MM-DD> ingest". Once the editor types a name, a later drop does not replace it. The name is made safe as it is typed, by the archive's naming rule (see "Where a clip is filed in the archive, and what it is called"); Chinese and other scripts are kept. When the name would be saved differently: "the shoot name will be saved as “<name>”"; a name that is not safe is refused with "the shoot name must be '<suggestion>' (Windows forbids some characters, and the archive caps a name at N characters here)". "Keep sub-folders" (on by default) keeps the clips' sub-folders under the shoot; off, they are dropped.

- On its own: the suggested shoot name, from the dropped folder or the date.
- By hand: the editor types the shoot name, and a typed name is never replaced by a later drop.

### The editor sees each clip of the drop, its archive name, and whether it is already in the archive

"<chosen> of <n> clips selected", then for each clip a tick, a thumbnail (made in the browser from about a tenth of the way in, or made on the editor's computer for any clip the browser cannot show, such as 10-bit footage or MXF, else "no preview"), the name with its sub-folder, size, length, "indexed in place" where so, "will be saved as <name>", and a progress bar. A file the browser cannot preview says so until its thumbnail arrives. The archive names and the duplicate check are asked again shortly after each change. A clip whose content matches a clip already in the archive shows "already in the archive: clip #N (<name>)" and is unticked once, the first time it is found; the editor may tick it again. A clip that was refused shows its reason and cannot be ticked. "clear" empties the drop. Every clip dropped ends in the drop with an outcome, "skipped, duplicate of" the kept clip included, so the counts always add up.

- On its own: which clips are already in the archive, from their content.
- By hand: the editor ticks or unticks every clip.

### Dropped files are copied in with progress, and an interrupted copy is tried again

Shortly after a drop the files are copied onto the editor's computer, two at a time, each with its progress, so even a 4 GB file never looks like a hung page. A dropped file takes its real name only once every byte has arrived; a broken copy is deleted. A broken connection is retried on its own, 3 tries in all (after 2, 4 and 8 seconds), showing "upload interrupted, retrying (n of 3)..."; two minutes without progress counts as broken, and there is never a limit on total time. After that: "<message> Tried N times: press retry when the connection is back." with "try again" on the row and "try all failed again (N)". A file already fully copied counts as done ("that clip is already staged"), so a page that reconnects never sends a big file twice. When a copy is refused, the person sees the reason, never a network error:

- "not enough space to stage this clip: it needs X GB and only Y GB is free (the floor is Z GB). Free some space and drop it again";
- "this upload sent more than it declared - nothing was kept";
- "the upload stopped before the whole file arrived";
- "CC Sync could not write the clip to its staging folder: <reason>";
- "no path was given for that clip", "that file is not on this computer", "that file could not be read", "that is not a video this machine can index".

Each file shows waiting, ready or failed ("the file is not there", "this file could not be read (<error>)"). A failed clip is tried again with its row's "try again", or together with every other failed clip of the drop by "try all failed again (N)", whichever step it failed in; retrying re-checks chosen files and clears a broken copy; retrying something that did not fail does nothing harmful. Leaving the page while files are still being copied brings up the browser's leave warning.


### The editor chooses the description quality, when the work runs, and what is uploaded

- "Model": Good (needs about 8 GB of graphics memory) or Best (about 12 GB). A level this computer's graphics card cannot hold is disabled with the reason, and one not yet on the computer says "not downloaded yet, about <size>". The default is the site's level unless it does not fit.
- "When to run": "Only when idle" (the default) or "Foreground".
- "Keep sub-folders" (on).
- "Upload the originals too" (on). Off, the archive holds the clips' previews and editing copies only, and the clips owe no original.

Speech in the clips is transcribed as the collection's own setting says, with no choice on the drop. The summary reads "<n> clips, <size> - will run now" or "... will run when you're away".


### Running a drop asks first when it is large or needs a download

"Run" is available only with clips chosen, the app on this computer answering, a shoot name, and every file copied in. A drop of 50 GB or more asks "This drop is X across N clips. Staging it needs X free on this computer and it has Y. Indexing will run for about H hours. Start it?" (estimated at a minute and a half a clip). A level not yet on the computer asks "The <quality> model isn't on this computer yet. Running this batch downloads it first (about X). Continue?". Both questions offer "Cancel" (the default) and "Go ahead". Success reads "Indexing started on this computer." or "Queued: it starts when you step away from this computer.", and is shown only once the work has really been taken. When the computer refuses (for example its graphics card cannot run the chosen level), its own sentence is shown as a lasting notice telling the editor to change the level or let another computer take it; any other failure: "The CC Sync app did not take the batch: <message>".

### The page says whether the app on this computer is ready to do the work

A status line with "recheck" shows the state of the app on this computer:

- "checking…";
- "connected (v<version>, <graphics card, or N GB of graphics memory, or no GPU>)", and whether Resolve answered ("Resolve: yes|no"; a Resolve that does not answer within 20 seconds counts as no);
- "the CC Sync app can't index yet: <reasons>";
- "Your CC Sync app needs the update it offers before it can do this. Take the update, then reload this page.";
- "not reachable: the CC Sync app is not running, or the browser blocked local connections (self-test: open <the app's local status address> in a tab; if that shows ok:true it is the browser, not the app)".

A page that cannot reach the app never claims the app is not running: it names both possibilities and offers the one-click self-test. "The app did not answer", "the app needs updating" and a real refusal are told apart, each with its next step. It is shown in the "Add b-roll" panel.

### While a drop runs, the person sees its progress and can act on it

A running drop shows "<shoot> - <state>"; the counts "<indexed> of <n> indexed · <live> searchable · <failed> failed · <dup> already in the archive · <skipped> skipped · <owed> still to send the original", where "indexed" counts only clips that were indexed; when the computer doing it last answered; what it is waiting for, in words (waiting for the indexing model, waiting until you step away from the keyboard, waiting for DaVinci Resolve to close, paused, waiting for the one-off download, waiting: the sync drive is not connected, waiting: this computer's sync config needs fixing, this GPU cannot run the chosen model, b-roll ingest is off on this computer, nothing to do, indexing); the download with its rate and minutes left; the current step and percent; whether uploads are queued or paused; and up to 200 clip lines. It refreshes every second or two for progress and every few seconds for the drop's record. Reopening the page shows the person's newest unfinished drop again.

Buttons: Pause or Resume, "Start now" (only while waiting for the person to step away or Resolve to close), "Pause uploads"/"Resume uploads", "cancel batch…". All are disabled once the drop has finished. While the computer doing the work does not answer, Pause, Resume and Start now are disabled with "the CC Sync app isn't answering right now - the batch keeps its place (...)".


### A drop's state is shown in fixed words

"waiting to start"; "waiting: <computer> stopped answering <ago>"; "starting on <computer>"; "indexing on <computer>"; "stopping"; "finished"; "finished, N could not be indexed"; "stopped"; "could not run". "ago" reads "Ns ago" under 90 seconds, "Nm ago" under 90 minutes, else "Nh ago", or "never". A drop that ends with clips failed or originals still owed finishes as "finished, N could not be indexed". A clip's own state never goes backwards except a failed clip being tried again; searchable, duplicate, cancelled and skipped clips are final. Every clip ends searchable, failed, skipped or cancelled within a bounded time, and a stuck drop never blocks new drops.

### A person sees their own drops, and an admin sees every computer's

"Batches" has "Mine" and, for an admin only, "All computers" (anyone else is refused: "only an admin can see every computer's batches"), newest first, up to 200. Another editor's drop is invisible to anyone but an admin, as if it did not exist. Each card shows the shoot, state, the editor (in the all view), the computer or "no computer yet", last answer, quality, "foreground" or "when idle", counts, "uploads paused", and any stored error (up to 500 characters). Actions: "clips"/"hide clips" (up to 200 lines); "take over on this computer" (a waiting drop of one's own); "try all failed again (N)" (a finished drop of one's own with failed clips or originals still owed); "cancel" (unfinished). The list can be opened at any time, without dropping anything, to see what is waiting and what failed, with reasons.

- Who: anyone signed in for their own drops; an admin for everyone's. Cancel and retry are for the drop's owner or an admin.

### A drop survives the page closing, a restart and the network dropping

A drop is never lost and never done twice. Closing the page, the app or the computer restarting, or the network dropping for a while leaves every clip where it was; work carries on where it stopped, and uploads under way are sent again. A file that has gone in the meantime fails alone with "the source file is no longer on this computer (the drive was unplugged, or it was moved)". When the computer doing a drop has not answered for 5 minutes, the drop goes back to waiting, still naming that computer ("waiting: <computer> stopped answering <ago>"), and another of the person's computers may take it over with "take over on this computer". While a computer is still answering, another is refused: "<computer> is already indexing this batch". A computer that loses a drop (cancelled, finished, taken over) stops working on it at once and keeps the dropped files. When a computer refuses a drop, its reason is shown, among them "this computer is already indexing another batch", "nobody is signed in on this computer", "this computer is not signed in to the studio's server", "those clips are no longer staged on this computer - drop them again", "this computer could not reach the dashboard", and "this computer has those clips staged, but the request did not say which drop: reload the page and try again". A computer whose graphics card cannot run the chosen level leaves the drop waiting for another that can.

### A person pauses, resumes, starts now or cancels their drop

Pause (which also ends "start now"), resume, start now (work at once, and unpause), cancel, pause uploads and resume uploads. Pausing uploads holds the drop's uploads to the archive while describing carries on, and lets the file in flight finish; the choice belongs to the drop, so it holds whichever computer works it. Cancelling asks "Stop this batch? Clips already in the archive stay there; the rest are dropped and their staged files are kept for a week." A drop no computer is working is stopped at once; one being worked shows "stopping" until its computer learns of it, within about half a minute, and the computer stops all work on it within 5 seconds, any running encode included, leaving no half-written file in the archive. A finished drop answers that it was already finished. Cancelling frees the names the drop had reserved for clips that never arrived.

- Who: the drop's owner, or an admin.
- Ways in: the drop on the b-roll page, the app on the computer doing the work, and the dashboard.

### A clip is searchable as soon as its preview is safely in the archive, before its original

For each clip the poster, hover strip, preview, editing copy (if made) and the original are sent to the archive one file at a time, cheapest first, so the person's syncing is never crowded. Every file a clip needs is checked to be present before any of it is sent: a clip whose original has vanished fails alone with its reason, sends nothing, and the drop finishes. A clip becomes searchable only once it is described and its preview has arrived complete (present, not empty, the declared size); a clip never goes live without its description, and a refused description is tried again and, after the tries, fails visibly. It shows on the dashboard once its stills land, plays once its preview lands, and is searchable on its previews while a large original is still on its way, shown as "original still owed". The original and editing copy are checked the same way. A copy that lands at the wrong size is sent again ("<file> arrived at N bytes, not M - it will be sent again").

Every answer to a sent file is either done, try again later (up to 3 times), or failed for good with the archive's own sentence ("the archive refused this clip (HTTP N)", "the archive would not take this clip (HTTP N)", "the archive never saw these files: <up to 3 names>"), shown to the editor and retryable. While the NAS cannot be reached, sending waits and starts again on its own every few seconds, and only failures with the NAS reachable count against a file. A send interrupted part way starts that file again. An unexpected error fails only the clip it hit, with its text, and the rest carries on. A bulk send shows progress and speed, and moves many small files at close to the connection's capacity.

If a clip is live on its previews and then its original fails to arrive, the clip stays live, shows "original still owed", the drop finishes "with errors", and the dropped file is kept on the computer, never cleaned away, until a retry gets the original into the archive. A cancelled drop takes out of the archive only clips whose media never arrived. The computer that brought a clip in never downloads that clip's preview or editing copy again: once the clip is live they are already in place in its own copy of the archive.

### Failed clips and owed originals of a finished drop can be tried again

"try again" on a failed clip, or "try all failed again (N)", puts every failed clip and every clip still owing its original back to waiting, keeping its archive name, so no duplicate is made; the drop waits for a computer again, and the editor is told how many. The work is redone from the files this computer holds; if it cannot tell which drop, it refuses with a reason. "running" is said only once a computer has taken it. Refused while a computer is still working the drop, naming it: "<computer> is still working on this batch. Stop it first, then try the failed clips again." A drop whose computer went away can still be tried again.


### Dropped files are cleaned away a week after they are no longer needed

The files held on a computer for a drop are deleted 7 days after the drop ended, or, for files dropped but never run, once they and the newest of them are older than that. Never deleted: a drop not yet finished, and originals the archive does not have yet. "CLEAR FINISHED STAGING", in the app's settings on the computer, deletes every finished drop at once, never one running or held: "Cleared <N finished staging folders>, <X.X> GB."; when only drops never run are held: "The staging on this computer is <N drops> that were never indexed, so there is nothing FINISHED to clear. Those clear themselves once they are past the staging retention window, or as soon as the drop is run."; otherwise "There is no finished staging to clear on this computer.", and it says how many it kept back. A failure reads "CC Sync could not clear the staging folders. See the log." A folder that cannot be deleted yet (a file still open on Windows) is tried again shortly. The space held is shown on the computer (size, drops, the oldest), with a red line "Finished indexing staging is holding X.X GB on this computer" beside the button, and on the dashboard. An editor can also remove a drop they no longer want from the list of drops.

- Who: the editor on that computer.
- When the b-roll archive is off: the button and the line count music drops only.

### Copies of a clip already in the archive are found and set aside, never deleted

Whenever footage is taken in, each file's content is compared with what the archive holds; only files whose size or date changed are read again, never the whole known archive. A candidate is confirmed by comparing the whole file; one that looked the same but is not stays a clip of its own, and an empty file is a broken download, never a duplicate of anything. Of the copies, the one kept is the furthest along (filed into a category, then described, then with a preview, and so on), then the one with most shots described, then the oldest. The others are marked as duplicates of the kept one: they are never described again, never placed in the archive and never shown in search, but they are not deleted. An admin can see each group of duplicates with its counts ("N duplicate(s), N kept, N found to be different (not marked), N file(s) missing (not marked)").

- On its own: which files are copies of a clip already in the archive, from their content.

### Messages on the archive's pages stay long enough to read

An error stays until it is closed with its ×, with at most 4 errors kept; other messages stay about 60 ms per character, between 5 and 15 seconds. A repeated message replaces its earlier copy. Message text can be selected and copied. A question before a destructive step offers "Cancel" (the default) and "Go ahead". Tooltips show on hover or keyboard focus, and on a tap on touch screens; Escape or scrolling hides them.

#### Lessons

- Met: BRO-082, BRO-083, BRO-084, BRO-085, BRO-086, BRO-087, BRO-088, BRO-089, BRO-090, BRO-091, BRO-092, BRO-093, BRO-094, BRO-095, BRO-096, BRO-097, BRO-098, BRO-099, BRO-100, BRO-101, BRO-102, BRO-103, BRO-104.

## Sending a clip to Resolve

### An editor sends the marked part of a clip to the timeline open in Resolve on their own computer

An open clip has two buttons: "Append to Timeline ⏎" (adds the marked range at the end of the open timeline) and "Place at Playhead ⇧⏎" (places it on a track above, at the playhead). Both need an in and an out point: without them, "Set both an in point (I) and an out point (O) first."; the two may be set in either order and the earlier is the in; on the same frame, "Out point must be after in point." Exactly the marked range lands in Resolve. A clip whose frame rate is unknown is sent as 24 fps.

The page is served by the server, and Resolve can only be driven on the computer it runs on, so the editor's own browser hands the request to the app on their own computer (see The app on each editor's computer: Settings, records and background work). The page names the clip by its place in the archive, never by a path on any computer, and the app works out where the clip lives on that computer. The clip is used from the archive at the shared path every computer reaches; it is never copied into a project.

In Resolve:

- Refusals first: Resolve cannot be reached (see Resolve on the editor's computer: Connecting to Resolve's scripting: launch, stalls and death), "no project open in Resolve", "no timeline open - create one first".
- The clip goes into the bin "B-Roll/Archive" in the media pool, made if missing. If Resolve will not make it: "Resolve wouldn't create the B-Roll/Archive bin: the project is locked (or open elsewhere in a collaboration). Unlock it and try again." A clip already in that bin for the same file is used again; otherwise it is imported ("failed to import media at <path>"). A newly imported clip is pointed at the path spelling every computer shares (if Resolve refuses, the local spelling is kept).
- Append: the In to Out range is appended to video track 1 whatever the timeline's destination buttons say, and checked to have landed. Fact about Resolve: with the video destination button (V1/A1, left of the timeline) off, an append is silently dropped. Messages: "failed to append clip to timeline"; "Resolve reported no error but nothing landed on the timeline. Check the destination track buttons (V1/A1) at the left of the timeline; with the video destination off, an append is silently dropped."; "Inserted <clip name> (<N> frames)".
- Place at Playhead: reads the playhead (drop-frame aware; the timeline start if it cannot be read), works out how long the clip will be on this timeline (24 fps if the clip's rate cannot be read), and picks the lowest track from V2 up whose video and audio are both free over that span, else one above the highest, adding video and stereo audio tracks as needed. The clip's sound lands on the audio track with the same number as its video track (V3 and A3, for example). Messages: "couldn't read the playhead position from Resolve"; "couldn't read the timeline's tracks"; "couldn't add a <video|audio> track for the overlay - is the timeline locked?"; "placement failed on V<n> at the playhead - something already occupies that span, or the track is locked" (anything that landed in the wrong place is removed); "Placed <clip name> on V<n> at the playhead" plus " (new track)".
- Anything unexpected: "Resolve didn't answer. Make sure a project is open, then try again." A Resolve that does not answer within 90 seconds is given up on, so neither the page nor the app ever hangs on it.

Success shows the app's own message, or "Sent to Resolve." Every outcome either places the clip in the open project or says in plain words why not and what to do.

- Who: an editor, at their own computer.
- When the help for the editing program is off: the two buttons are replaced by one that saves the clip's file, and Enter and Shift+Enter do nothing.

### Which file lands in Resolve: the original when there is one

For a clip filed in the archive, what goes into Resolve is the original beside its preview (the single file of the same name; a name typed on a Mac matches one typed on Windows), with the editing copy of the same name attached as its proxy where one exists. With no original found, or several candidates, the preview itself goes, under its own name. A clip not yet filed in the archive goes from where it is. When the original is still on its way to the archive, the clip goes with the place where the original will land, so it can follow (see "A heavy clip sent from a remote computer arrives as its preview at once and upgrades by itself"). When the archive's folders cannot be read at that moment, the clip asked for is fetched as it is and nothing lasting is recorded about it.

### A clip not on this computer yet is fetched first, with progress, and then placed

When the clip's file is not on this computer, exactly that one file is downloaded from the NAS to the place a full sync would have put it, and the send carries on by itself once it is in place: the editor presses nothing again. The page shows "Clip isn't on this computer yet: syncing it down, then inserting." and the button reads "SYNCING <n>%" (or "SYNCING…" until the size is known), checking every second and a half with no time limit. Pressing send again joins the download already running. A download never leaves a half-written file under the clip's real name.

A computer downloads at most two clips at once for an editor who is waiting. A third reads "not sent yet: this computer is already downloading as much as it will at once. This one starts as soon as a slot is free": the page shows "Waiting for this computer's other downloads to finish." with the button reading "WAITING…", never as an error and never as success, asks again at the pace the app suggests (at least every second), and starts the moment a slot frees; after 15 minutes it gives up with "This computer has been busy with other downloads for a while. Try again when they have finished." A failure reads "couldn't sync the clip from the NAS: <reason>", and the next send starts again from the beginning. Quitting the app stops every such download ("cancelled - CC Sync shut down").

A clip is fetched this way only on a computer that syncs remotely (a computer wired to the server already sees the NAS itself), and only when the archive is at its usual place on this computer; an editor who points the archive at a folder of their own is told "nothing was fetched: the archive on this computer is in a folder of your own, which CC Sync does not fill" with "file not found at <path> - is the share mounted?". Other refusals, each on the page:

- this computer's sync settings are incomplete (no server named, no folder on the server, or no folder on this computer), each in its own sentence naming which is missing;
- "can't fetch the clip from the NAS - <detail>";
- "that file is outside this computer's tree - nothing was downloaded";
- "this computer's tree isn't mounted right now, so nothing can be downloaded into it - reconnect the drive and try again" (an unplugged external drive, an unmounted macOS volume; when this cannot be told, the download goes ahead);
- "this computer could not start the download (<error>)".

- Ways in: sending a b-roll clip; the same one-file fetch serves a music track sent to Resolve and a downloaded YouTube original brought to the editor's computer.

### A clip sent to Resolve gets its editing proxy, never the browser preview as its proxy

Fact about Resolve: it attaches a proxy from the Proxy folder beside a clip on its own only for clips it imported itself, never for clips another program brings in. So when a sent clip has no proxy, the editing copy of the same name from the Proxy folder beside it is attached as its proxy, through the shared spelling where it can be. The browser preview is never attached as a clip's proxy. If Resolve refuses (a proxy missing its timecode is the usual cause; with no reason of its own it reads "Resolve refused the proxy"), the clip is still inserted. A proxy can also be attached to a clip already in the media pool; with none for that file: "that clip is not in this project's media pool". Every attach is recorded so it can be undone (see Resolve on the editor's computer: Fixing media: copying in, rehearsals and undo).

### One clip is sent at a time from a page

Both send buttons are disabled while a send is under way. Opening another clip meanwhile, its buttons carry `Still sending "<name>" to Resolve. This clip can go when that one has finished.`, and pressing one shows the same as a warning. Once the editor has moved to another clip, every message about the earlier send begins `"<file name>": `.

### When the app on the editor's computer cannot be reached or refuses, the editor is told what to try

Unreachable: "Couldn't reach the CC Sync app. It may not be running, or your browser blocked the connection (look for a “local network” permission prompt, or allow it in site settings). Self-test: open <the app's local status address> - if that shows ok:true, it's the browser, not the CC Sync app." followed by where to get the app. Any other refusal: the app's own message, or "The CC Sync app returned HTTP <n>". When the app must be updated first: "Your CC Sync app needs the update it offers before it can do this. Take the update, then reload this page." Resolve's own refusals, and "the Resolve worker failed" when Resolve could not do it, are passed on as they are.


### The dashboard shows whether each computer can take "Send to Resolve"

For each computer the dashboard shows whether the part of the app that takes "Send to Resolve" from the browser is on, whether it is listening, on which port, any error and since when. When nothing is known it says the computer cannot say, never that it is listening. If the app cannot take its local port, it keeps trying, waiting longer each time up to 30 minutes, and the dashboard always knows. This is what to look at when a person's "Send to Resolve" does nothing.

- Who: an admin.

#### Lessons

- Met: BRO-105, BRO-106, BRO-107, BRO-108, BRO-109, BRO-110, BRO-111, BRO-112, BRO-113.

## Previews standing in for originals

### A heavy clip sent from a remote computer arrives as its preview at once and upgrades by itself

Every archive clip has a small browser preview beside it, and an original too heavy to edit with also has an editing copy. When an editor sends a clip, the product decides which copy lands, in this order:

1. The original is already on this computer: it is used. Nothing downloads.
2. The archive's folder for the clip cannot be read, or this computer is wired to the server: the original is fetched.
3. The archive has no original for this clip, or the editor sent the preview itself: the preview is fetched and used under its own name ("preview only"); nothing is recorded as a stand-in and no upgrade is ever offered.
4. The original is light enough to edit with (or its weight is unknown and the archive has no editing copy), or there is no preview: the original is fetched.
5. The original is heavy and is a MOV, MP4 or M4V file, which Resolve takes as an ordinary video file: the preview's picture is placed at the original's own name and place (a "stand-in"), so within seconds the clip in Resolve is usable and already points at where the original belongs, and is never reported missing. The editing copy is then fetched and attached as its proxy, with no step by the editor.
6. The original is heavy and in any other form (camera raw such as Blackmagic RAW, RED or Canon Cinema RAW Light, or MXF, AVI, MKV, or no recognisable type): "preview only". A preview is never written under such a name.

A clip sent while its original is still on its way to the archive is placed as a stand-in at the place the original will land, and upgrades when it arrives; a drop that sends no originals owes none. Facts the archive gives about the clip (which copies exist, whether the original is still on its way, its size and frame rate) guide the choice; anything wrong in them is ignored and never makes a send fail.

The editing copy for a stand-in is downloaded in the background, one at a time per computer, never making a waiting editor's send wait, and with Resolve closed if need be: the clip picks it up when Resolve next opens. Once it is here it is linked in Resolve as the clip's proxy, leaving the clip pointing at the original's place. If it has not arrived within an hour it is given up ("the editing proxy did not finish downloading") and the clip keeps the preview. If Resolve could not take it (Resolve closed, another project open), it is tried again about every two minutes, at most once at a time per clip, up to 8 times counted across restarts; after that it stops until the editor sends that clip again, which starts the count afresh. A clip whose editing copy is attached is never redone. The upgrade runs whatever the computer's other settings, but not while the sync folder is broken.

- On its own: which copy of a clip lands in Resolve, from where the original is, its weight and its form.
- By hand: the editor sends the preview itself, or sends the clip again to restart its upgrade.

### The editor is told while any clip is cut on a stand-in

While any clip on this computer is still a stand-in, the app on the editor's computer shows how many, says they are being cut on the preview and not the editing proxy, and says to send them again; stand-ins whose upgrade gave up are shown as a count with one reason. The b-roll page lists the stand-ins whose editing copy was given up. A stand-in holds the preview's picture under the original's name, so a render made on this computer while it is a stand-in renders the preview: the app says so beside its count and, when it can tell a render is starting on this computer, warns before it that the render would use the preview for those clips.


### Each computer knows which of its files are stand-ins, and never forgets one by mistake

Each computer keeps a record of every stand-in it placed: which clip, which preview, which editing copy, the original's picture size, frame rate, length and start timecode, when placed and how big. The record is written before any byte of the download, so a closed browser tab can never leave an unrecorded stand-in, and is removed if the download is refused, fails or vanishes. One bad record never stops later ones being written. A stand-in stops counting as one only when the real original is confirmed in its place, by something that differs between the two (its size against the original's known size, or its length within 1 frame), never by picture size alone; a file that cannot be identified stays a stand-in. A record whose file never appears within 6 hours is dropped; records whose file has been gone for over 30 days are forgotten; neither forgetting happens while the archive folder itself is missing, so an unplugged drive never wipes the record. The same name spelt the macOS way and the Windows way, or in different letter case, is one file.

### Every computer learns which archive clips anyone cut against a stand-in

Every computer opening a project learns which archive clips any computer in the studio has stood a preview in for, at most 200, newest first, each named once whatever its spelling. "The server does not know" means keep checking, never "there are none". The mark clears when the real file has landed, and a stand-in not heard of again for 30 days is forgotten. Paths are never shown in full.

### Resolve re-reads a clip once its real original arrives

When an archive clip in Resolve was placed from a stand-in and the real original is now on this computer, Resolve may still hold the stand-in's frame count and picture size. If the clip's frame count disagrees with the file's, Resolve is made to re-read the clip from its own file, before any proxy is attached. If either side cannot be read, nothing is done. If the clip had a working proxy and lost it in the re-read, the proxy is attached again at once. A clip whose re-read changed nothing is not tried again until the file changes.

### Admins are told when the b-roll archive cannot be read

When the archive cannot be read (its proxies folder is missing: "the archive folder is there but its contents are not"; it cannot be listed; or it lists empty: "the folder is there but completely empty"), admins are told "the b-roll archive cannot be read", as a serious problem, checked afresh every few minutes and shown until it is readable again. The text explains that every clip an editor sends to Resolve is then the small preview instead of the editing proxy. During such an outage nothing lasting is recorded about a clip sent: "could not read the archive" is never taken to mean "this clip has no original". Not raised when the b-roll archive is switched off.


### The archive remembers where each clip's true original lives

Every archive clip, downloaded or own shoot, carries the place and size of its original: for a shoot archived as its proxies, the camera file with the same name in the same folder (ignoring a proxy folder level, letter case ignored); otherwise the clip's own file. This needs no drive to be connected. An admin can have every original checked for being there now; the check is dated, and an original not found is counted as not found, never recorded as gone. The report reads "recorded N original path(s) of M; K unresolved", and with the check, how many were found and not found.

#### Lessons

- Met: BRO-114, BRO-115, BRO-116, BRO-117, BRO-118, BRO-120, BRO-121, BRO-122, BRO-123, BRO-124.

## Client folders and links

### Editors gather archive clips into client folders, each with its own link

A client folder is a titled, ordered set of archive clips with one link a client opens with no sign-in, seeing previews only. Folders belong to the studio: every signed-in editor can see, change, revoke and delete every folder; who made it is recorded and shown but grants nothing. Each folder is "live" (its tooltip gives the expiry), "revoked" or "expired"; revoked wins over expired.

- Who: anyone signed in.
- Name and search words: Client folders. Search words: client folders, share link, client preview, licensing, share footage.

### An editor makes a client folder from any folder of the archive in one step

From the folder tree an editor can make a client folder of a whole folder of the archive and gets its link at once, without waiting for anything to be described. Its clips show with their previews and stills as soon as each has them; a clip still without a preview is not shown to the client until it has one. The folder can then be captioned, ordered and trimmed like any other.

- Who: anyone signed in.

### A client folder has limits, and going over one is refused, never cut short silently

Title required ("a folder needs a title"), at most 120 characters; description up to 2,000; licensing contact up to 200; a clip's caption up to 500; at most 500 clips in a folder. Adding clips that would pass 500 adds nothing and says "a client folder holds at most 500 clips. This one has X, so there is room for Y more and Z new clips were sent. Nothing was added." Adding a clip already in the folder is not an error. A clip no longer in the archive cannot be added ("clip N is not in the archive index").

### The client link is unguessable and can be copied again at any time

The link carries 22 random characters, as hard to guess as a 128-bit key. It is kept so it can be copied again later. The folder shows the link in a read-only field with "Copy" ("Link copied"; when the browser refuses the clipboard, the field is selected and "Copy failed: select the link and press Ctrl+C") and "open", which opens the client's view in a new tab without counting as a client's visit. A link never appears in any log.

### An editor revokes a link, reactivates it, or issues a new one

"Revoke link" (after "Revoke this link? ...") makes the link dead until "Reactivate link". "New link" (after "Issue a new link? The old one stops working immediately.") replaces the link: the old one is dead at once, and a revoked folder becomes live again. Messages: "Link revoked", "New link issued", "Link reactivated", "Failed: <message>". A link already open in a client's browser stops serving at its very next request, a video already playing included.

### An editor writes what the client reads, and sets when the link expires

Title, "Description (shown to the client)", "Contact for licensing (email or a line of text)" and "Link expires": keep current, never, in 7 days, in 30 days or in 90 days, counted from the moment of saving. "Save details" answers "Saved" or "Not saved: <message>". The note under the link says that the link is revoked, or expired, or that it is reachable only inside the studio's private network until an admin sets the public link address, or "Opened N time(s), last <date>." / "Not opened yet.".

### An editor adds a clip to folders from its thumbnail or from the open clip

The "+" on a thumbnail, or "+ client folder" in the open clip, shows "Add to client folder": one tick per folder, already ticked where the folder holds the clip, each with its clip count. Ticking adds (`Added to "<title>"`), unticking removes (`Removed from "<title>"`); a failure puts the tick back and says "Failed: <message>". "+ new folder…" makes a folder and adds the clip (if the add fails: `Folder "<title>" was created, but the clip was not added: <message>`). "manage folders" opens the folder list. Not signed in: "Sign in to use client folders". It closes on a click outside or Escape.

- Ways in: the "+" on a thumbnail, and "+ client folder" in the open clip.

### An editor manages the folder list and makes new folders

The list explains that clients see previews only and need no sign-in. The same list also holds the folder links the Footage Sorter makes (see The Footage Sorter and camera cards: Downloading originals and sharing folders) and the delivery links, each marked as what it is. It offers "+ New folder" and "refresh". Each row shows the title, its state, "<n> clips · by <person> · opened Nx" or "never opened"; clicking opens it. Newest first. Empty: "No client folders yet. Make one, then add clips from the + on any thumbnail." Failure: "Could not load client folders: <message>". "+ New folder" asks "Name for the new client folder (the client sees this):"; a blank name warns "A folder needs a title"; otherwise "Created "<title>"" and the folder opens; failure "Could not create the folder: <message>". Escape does not close the list.

### An editor captions, orders and removes the clips in a folder

"Clips (N)" lists each clip with its still (clicking opens the clip in the archive), name and length; a caption field ("caption the client sees (optional)"), saved when changed with a "saved" mark for about two seconds, or "Caption not saved: <message>"; up and down arrows, saved at once ("Order not saved: <message>"); and remove ("Not removed: <message>"). A clip that cannot be found in the archive is shown as "<file name> (no longer in the archive index)" with only remove and the arrows, and is hidden from the client. Empty: "Empty. Hover any thumbnail in the grid and press its + to add it here." An order sent from an out-of-date page can never remove clips; clips it does not mention keep their order after the ones it does.

### A clip in a client folder keeps its identity through renames, moves and rebuilds

A clip in a client folder is the same clip however the archive changes: renamed, moved, described again, or the archive's search data rebuilt. It is found by its place, or failing that by identical content when exactly one clip in that collection has it; only then is it shown as missing to the curator, and it is hidden from the client. A folder serves exactly its curated clips, never a different clip that took a place. A clip that ends up in a folder twice is shown once. Nothing that happens to the archive's search data ever removes a client folder.

### An editor deletes a client folder and its link

"Delete folder" asks "Delete "<title>" and its link? This cannot be undone." and answers "Folder deleted" or "Not deleted: <message>".

### An admin sets the public address client links are built on, and the name a client sees

Only an admin may set the public link address ("only an admin can change the public link base" otherwise). It must be a scheme and host with an optional port and no path; anything else is refused with a message giving an example of that shape. A trailing slash is dropped; blank clears it. Answers: "Public link base set to <address>", "Public link base cleared" or "Not saved: <message>". Until it is set, links use the dashboard's own address and work only inside the studio's private network, and the folder list warns that links only work for people on the studio's private network: an admin is told to set the address once client links are published to the internet, anyone else to ask an admin. Client links and everything they serve sit under one address prefix, so that prefix is the only thing that needs publishing beyond the private network.

- Who: an admin.
- Setting: Public address for client links. Does: the address client links are built on, so clients outside the studio's private network can open them. Default: blank (the dashboard's own address, private network only). Who: an admin. Applies to: the site. Search words: public link, client link address, share address, internet.
- Setting: Organisation name shown to clients. Does: the name in the header and footer of every client page. Default: "CC Sync". Who: an admin. Applies to: the site. Search words: organisation, studio name, client page, branding.

### Each client visit is counted, but not the studio's own looks

Every opening of a client link adds one to the folder's visit count and records when, except an opening by a signed-in person of the studio or through the folder's own "open". The count and the last visit show in the list and in the folder.

### A client opens a link and sees only what is in that folder, with no sign-in

Everything behind a client link answers on the link alone, read only, and is checked afresh on every request, each piece of media included, against the folder's curated clips. For each clip a client sees only its display name (the file name without its extension), caption, length, frame rate, picture size, codec, shoot date and its visual descriptions (time range, what is seen, setting, motion). A client never sees paths, collection names, transcripts, themes or quality flags, nor anything about clips outside the folder, nor any other page or file of the product: anything else asked for under a link answers as not found. The pages ask search engines not to list, follow or archive them, tell no other site where the visitor came from, and are not kept by the browser. A dead link (revoked, expired, never existed or mistyped) looks the same at every address.

- Who: a client holding a link.

### A dead client link shows a page that says so and whom to ask

"THIS LINK IS NOT AVAILABLE", "The footage preview you were sent has been closed, has expired, or the address is not quite right.", then, for an unknown link, "Please contact whoever sent it to you for a fresh link."; for a revoked or expired folder, "Please ask <maker> at <contact> for a fresh link.", "Please ask <maker> for a fresh link." or "Please contact <contact> for a fresh link.", as known. Nothing else about the folder is shown.

### A client sees the folder as a page of previews with the studio's contact for licensing

The page is drawn in the product's one look and carries the studio's own name and mark. Header: the studio's mark, "<ORGANISATION> // PREVIEW" ("Footage" until loaded) and "N clip(s)"; the browser tab reads "<title> - footage preview". Then the title, description and "To licence any of this footage, contact <contact>." (an e-mail address becomes a mail link with the subject "Licence enquiry: <title>"). Help: "Tap or click a clip to play the preview and see what is in it. On a computer, hover over a thumbnail to scrub through it. Previews are low resolution. Full-quality masters are supplied on licence." Then the clips in the folder's order: still, hover scrub, length, and "<name> - <caption>" (up to 3 lines). Empty: "This folder is empty." Footer: the organisation name, " · this preview is available until <local date>" when an expiry is set, and the contact line.

- Phone and desk: long names wrap on narrow screens; hover scrub is for a pointer, and a tap opens the clip.

### A client page that cannot load says whether the link is gone or the trouble is brief

Gone: "This link is not available" / "The preview you were sent has been closed or has expired. Please ask whoever sent it for a fresh link." Any other failure: "The preview could not load just now" / "This is usually brief. Please try again in a moment." with "Try again", which reloads.

### A client opens a clip, plays it and reads what is in it, but cannot download it

Clicking a clip opens "← back to the folder", "← prev" / "N / total" / "next →" (disabled at the ends), a player with its ordinary controls but no download, casting or picture-in-picture, playing in place on phones; the title; "<width>x<height> · <fps> fps · <m:ss> · shot <date>"; the caption in italics; and "What is in this clip": each time range (m:ss) with what is seen and the setting, clickable to jump and play, or "No description available.". A clip removed while open: "This clip is no longer in this folder. Refresh the page to see what is." Any other playback failure: "This clip could not be played just now. Refresh the page to see what is in this folder." Keys: Space plays and pauses, Left and Right go to the previous and next clip, Escape returns to the folder. An address ending in the clip's number opens that clip directly; Back from a clip returns to the folder, and previous and next add no Back steps.

- Phone and desk: the key help is hidden on touch screens.

### A delivery link lets a client download full-quality files

Besides the preview link, an editor can give a client a delivery link to chosen folders of the archive, so a distant client can download full-quality files, possibly terabytes, without joining the studio's private network and without any software of their own. A delivery link is read only, downloads straight from the NAS at close to the studio's connection speed, resumes after an interruption, and allows several connections at once. It is revoked, reactivated, renewed and expires exactly as a preview link does. Every download request is recorded lastingly with the visitor's address, the file and the bytes sent, never with the link itself.

- Who: anyone signed in makes one; a client holding the link uses it.
- See also The Footage Sorter and camera cards: Downloading originals and sharing folders.

### Admins are warned before a client link expires

Admins are warned "a client link is about to expire" when a client folder's link that has not been revoked expires within 7 days. Links already expired are not raised. Admins are also warned "a b-roll indexing job has stopped" when a drop waiting or being described has shown no sign of life for 24 hours.

- Who: an admin.
- When the b-roll archive is off: neither warning is raised.

### Client links keep working when something else fails

A failure in client folders' own records never stops the b-roll archive, and a failure elsewhere never stops client links: if client folders cannot start, only they are shown as not working, with the reason, and search carries on. A read-only disk or an interrupted update of the product never takes client links down; every client link the studio has handed out keeps working through any update.

#### Lessons

- Met: BRO-125, BRO-126, BRO-127, BRO-128, BRO-129, BRO-130, BRO-131, BRO-132, BRO-133, BRO-134, BRO-135.

## Replacing the search index

### What people add to the archive is never lost when its search data is refreshed

Clips, descriptions, transcripts, categories, drops and client folders that people added are never lost, rolled back or hidden by any refresh or rebuild of the archive's search data, by a better describing of the whole archive, or by an update of the product, whatever arrives while it happens. A refresh either keeps every clip and every waiting drop added since it began, or changes nothing at all and says why. If anything added during a refresh could not be carried into the new search data, the admin is told how many clips, drops and items, that nothing is lost, and the one step that puts them back, which can be repeated safely. Search always answers from the newest data within a minute, with nothing restarted.

### Search never stops because of an update

An update of the product never switches the archive's search off: search keeps answering from the data it has until the new data is complete and checked, and the switch to it happens in one step. When the archive cannot work (for example its search data cannot be read by this version of the product), the archive is shown as not working, with the reason, wherever the state of each part is shown, never as switched off or absent, and admins are told what to do first.

#### Lessons

- Met: BRO-136.
