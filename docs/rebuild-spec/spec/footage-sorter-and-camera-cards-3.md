# The Footage Sorter and camera cards, part 3 of 3

This part covers the pictures and hover previews of clips, the Sorter's own page and everything on it, one search across every place the studio's footage lives, and taking footage away: downloading originals to a person's own computer and handing a folder to someone outside the studio by a link.

## Thumbnails and hover filmstrips

### Every recording gets a picture and a scrub filmstrip without anyone asking

Every clip of video, stills or image sequences gets a picture, and every video also gets a filmstrip for scrubbing on hover. Nobody asks for them: they are made in the background as soon as a clip is found (after each look through the folders and each card read), stored, and from then on shown at once.

- One recording has one picture and one filmstrip, shared by every copy of it: on a card, in the staging folder, in its final folder. They follow the recording, not its path, so they stay with it through any move, copy or rename by hand. A picture made while the clip was on a card is the picture of its copy on the NAS.
- Pictures come in two sizes, 320 and 160 pixels wide.
- A picture is taken from, in order of preference: an image sequence's first image; a playable proxy; a playable original; a still preview file the camera wrote beside it; an original that is itself an image; the preview a raw still camera embeds in its file (nothing is developed); any other playable or image file.
- A video's picture is the frame 1 second in, or the first frame of a clip shorter than that.
- A filmstrip has one frame for every 10 seconds of the clip, at least 12 and at most 50, each 160 pixels wide, made ahead of time as one small image of tens of kilobytes. Each frame comes from a later point than the one before, spread evenly to the end of the clip. A filmstrip found to have been made wrongly (for example, frames bunched at the start) is made again.
- Sound files, "other" files and project files get no picture: a sound clip shows an audio card, an "other" clip a placeholder for its kind. A Blackmagic RAW recording with no proxy beside it, never seen on a card, shows the placeholder for its kind until a proxy exists.
- Names with spaces, accents or Chinese characters make no difference.
- Any picture or filmstrip still missing is made on its own, at the latest within 6 hours, and after every look through the folders.
- A picture that cannot be made counts as "no picture". It is tried again after an hour, or sooner if the file changes, and never again just because the server restarted.
- Making pictures in the background never slows a picture someone is waiting for, never makes another dashboard page slow to answer (every other page still answers within a fraction of a second while hundreds are made), and never loads the NAS enough to slow syncing.
- On its own: which frame stands for a video (1 second in, or the first frame) and which file a picture is taken from, by the order above.

### A picture someone is waiting for is made first

When a clip on screen has no picture yet, its picture is made before any picture still waiting in the background. While it is being made the clip shows its placeholder, marked as pending, and the page asks again by itself. Clicking a clip moves its picture to the front. The page waits up to 10 seconds for a picture and up to 20 seconds for a filmstrip before it treats the clip as having none yet; it then shows the placeholder and asks again no sooner than 5 minutes later. A picture that could not be made is shown as "no picture" for the rest of the visit.

### Clips on a card get their pictures from the computer holding the card

The server cannot read a card sitting in a reader on an editor's computer, so that computer makes the card's pictures and the server keeps them. It does this by itself, in the order the clips were recorded (which is the order of the grid), and each picture shows within about 5 seconds of being needed, without the person doing anything.

- Only video and stills get pictures. Sound, "other" and the camera's index files do not.
- Where the camera wrote its own small proxies or thumbnails on the card (Sony cameras do), those are used, and they show straight away.
- While a card is being copied it is not read for pictures, so the copy runs at full speed: its clips stay pending until the copy ends, except where the camera's own thumbnails can be shown.
- A file that cannot be read is skipped. A picture that already exists is kept.
- The card shows how many of its clips still have no picture.
- When that computer's app is not running, the card's clips show their placeholders.

### Pictures load as the person scrolls

The clip grid asks only for the pictures it needs. While the grid scrolls fast (more than about 1,600 pixels a second) cards show placeholders; very shortly after scrolling stops, the pictures on screen load, nearest the middle first, then those just above and below. Narrow cards get the smaller picture. The browser keeps a picture for a day.

- Phone and desk: on a phone, pictures and filmstrips are the small ones (about 2 to 3 KB each) and are held only in the browser's ordinary cache, which the phone may empty when it needs room. Nothing piles up on the phone.

### Hovering a clip previews it, silently by scrubbing or with sound

Resting the pointer on a clip card for 300 milliseconds starts a preview; moving off it stops the preview. No preview starts while a box is being drawn or clips are being dragged, or for a clip whose preview already failed during this visit.

- With Sound off, a video shows its filmstrip, and the frame shown follows the pointer across the picture, with a thin bar showing the position. The filmstrip is fetched ahead after a brief pause on the card, unless the browser has asked to save data.
- A video with no filmstrip, an audio clip, or any clip with Sound on plays the clip's proxy instead. With Sound off it plays muted, following the pointer. With Sound on it plays with sound, starting from the point under the pointer, so a person can dip into the middle of an hour-long recorder file. If the browser refuses to start playing by itself, nothing happens.
- A clip whose length was not known gets it from the preview, and keeps it for the visit.
- The Sound switch is off at first and remembered on that browser. Its tooltip reads "Play sound while previewing (hover a clip)".
- Phone and desk: on a touch screen, Preview in the clip's menu (a long press on the clip) plays the same preview in place, with or without sound as the Sound switch says, and sliding a finger across the picture moves through it as the pointer does. A tap anywhere else stops it. The Sound switch is reachable on a phone too.

### Pictures where a person picks originals by folder

Wherever the dashboard lets a person pick originals to bring down by their place in the studio's folder tree, each file shows a small or large picture and can be played.

- The picture is made from the file's proxy beside it, or from the file itself; the person waits up to 12 seconds for one to be made.
- Playing plays the proxy, or the file itself when a browser can play it.
- What a person is told: "no picture yet: this file has no proxy"; "no picture could be made"; "nothing to play yet: this file has no proxy, and a browser cannot play the original"; "sign in first".
- Who: anyone signed in.

#### Lessons

- Met: SRT-151, SRT-156, SRT-158, SRT-152, SRT-153, SRT-154, SRT-155, SRT-157, SRT-159.

## The sorter page

### The Sorter is a page of the dashboard, behind its sign-in

The Footage Sorter is one of the dashboard's pages, reached from its menu and its search, and opened from any signed-in browser, a phone included. Everything done on it (sorting, moves, card copies, backups, downloads) acts as the person signed in, and every change is checked against what that person may do before it is made. Every place footage lives is named by where it is on the server, never by a drive letter on one computer.

- Who: anyone signed in.
- Name and search words: Footage Sorter. Search words: sort footage, camera cards, clips, offload, ingest.
- When camera cards with the Footage Sorter is off: nobody but an admin sees the Sorter, and an admin sees it only in settings, listed with its switch. Folder links it made stop opening (they show "This link is not available") until it is switched on again. Nothing it holds is deleted.

### What needs an admin and what needs only a sign-in

Only an admin may carry out a move; change a drive's details, read a drive or a folder into the record of every copy, or add, remove or change a watched folder; answer a question about where footage went; change the cloud backup schedule or start a cloud backup; back up the record of every copy; copy between drives or cancel such a copy; make, see and switch off folder links. Anyone signed in may assign clips, edit planned folders, plan moves, start looks through the folders and audits, copy cards and download originals. A person who is not an admin and tries one of the admin acts is told "<what> needs an admin of this dashboard".

- Who: as above.

### The Sorter waits while it gets ready after the server starts

For a short while after the server starts, the Sorter is getting its records ready. A page or action asked for meanwhile waits rather than failing, for up to 2 minutes, and is then answered "the footage sorter is still loading: try again in a moment".

- If its records cannot be loaded, the Sorter leaves the menu, and the overview's state of the parts says "the footage sorter could not load its data (<error>)".
- When the folder the studio's footage lives in is not mounted on the server, the Sorter does not come up, and the overview's state of the parts says the footage folder is not mounted.

### The folders the Sorter works with

The Sorter works with these kinds of folder, all of them places on the server:

- **Source folders**: where footage arrives to be sorted (copies of cards, folders brought in from other computers). There can be several.
- **The final tree**: the studio's finished project folders. It is always looked through as well, even though it is not a source folder, so footage already sorted stays visible and can be sorted again. Project folders are only ever destinations, never sources.
- **The staging folder**: where a card is copied when it is not sorted straight into the final tree. When none is set it is the first source folder.
- **Folders looked at for their own files only**, never their sub-folders: for example loose sound files beside a drone card's folder. Such a folder that is also a full source folder is looked through in full.

With no final tree set, the destination tree is empty, and exporting a move plan, auditing, card copies straight into the final tree and every other feature that needs one are refused, each saying no final tree is set.

- Setting: Source folders. Does: which folders the Sorter looks through for footage to sort. Default: none until set when the part is switched on. Who: an admin. Applies to: the site. Search words: source folders, footage to sort, dump folders, sort from.
- Setting: Final tree. Does: which folder holds the studio's finished project folders that clips are sorted into. Default: the studio's project tree on the server. Who: an admin. Applies to: the site. Search words: final tree, destination, project folders, sorted tree.
- Setting: Staging folder. Does: where a card is copied when it is not sorted straight into the final tree. Default: the first source folder. Who: an admin. Applies to: the site. Search words: staging, card copies, holding folder, unsorted.
- Setting: Folders looked at for their own files only. Does: folders whose loose files are listed but whose sub-folders are not. Default: none. Who: an admin. Applies to: the site. Search words: loose files, top level only, sound files, drone folder.
- Pending: footage-sorter-and-camera-cards-3-Q1

### An admin adds or removes a source folder from the sources list

"+ folder" by the sources ("Sort footage from another folder") opens a dialog: "Sort footage that never passed through the staging folder. Paste the folder path - from Explorer, Shift+right-click the folder and choose “Copy as path” - or drag it in from the address bar."

- A drop area takes a dragged path or file link, with any quotes removed. Dropping a real file or folder from the file manager says "Windows does not hand a browser the path of “<name>”. Paste it instead - Shift+right-click the folder in Explorer, “Copy as path”."; anything else dropped says "Nothing usable in that drop."
- A path box, and a "Sorting from:" list of the source folders already in use, each with a way to remove it.
- A path is understood as the place it names on the server, whether it is pasted as the server names it or as the person's own computer names the studio's shared folders. Quotes around a pasted path are ignored, and letter case is ignored in every comparison.
- Add and rescan: an empty box gives "Give a folder path first."; success closes the dialog, says "Added <path> - rescanning" and starts a look through the folders. A refusal shows its reason (or "Could not add that folder") and keeps the dialog open. Cancel closes it.
- Refusals, each in these words: "give the full path, starting at the drive"; "no such folder: <path>"; "that is a file, not a folder"; "that sits inside the destination <tree>"; "already a source root"; "already covered by <folder>" (it lies inside a source folder already listed); "that contains the existing root <folder>"; on removal, "not a source root", and "that is the only source root" (the last one cannot be removed).
- Who: an admin.
- Windows and macOS: on a Mac the dialog's hint names Finder's own way to copy a folder's path instead of Explorer's.
- Pending: footage-sorter-and-camera-cards-3-Q1

### Each source folder belongs to the computer it is on

Each source folder is shown under the computer it is on: the computer recorded for it (the deepest recorded parent folder wins); else, when it is on the server, the server, shown as "NAS" unless the site has named it; else "Unknown computer". A computer is never guessed. Spellings of one computer's name are merged (letter case ignored, spaces and underscores treated as hyphens) and the first readable spelling is shown. The list of computers holds the computers of these folders, the server, any extra names the site added, computers that reported cards, and computers where drives or watched folders were seen.

- On its own: which computer a source folder is on, from what was recorded when it was added or seen.
- By hand: an admin sees each source folder's computer beside it in the Sorter's settings and can set it to any known computer. A computer set by hand is never changed by a later automatic pass.
- Setting: Name of the server's computer in the Sorter. Does: the name the server is listed under among the computers. Default: NAS. Who: an admin. Applies to: the site. Search words: NAS name, server name, computer name, sources.

### Sources are listed per computer, closed until opened

The sources area has a label naming every computer listed. There is one entry per computer the server knows, plus any computer a source folder or card names, plus "Unknown computer" when something is on none; the NAS comes first, then the rest alphabetically. Every entry starts closed. With none at all it reads "No computers yet."

- A computer shows its name, "<n> card(s)" when cards are in its readers, and its clip counts, with the tooltip "<name>: <n> tracked folder(s) · <n> card(s)". Pressing it opens or closes it.
- Inside: each source folder as a tree, then the cards ("<n>", or "<n> + <k> closed"); "No tracked folders" when there are none.
- A card put into a reader while the page is open opens its computer and its cards by themselves. Cards already in readers when the page opens do not.
- Folder rows show "<assigned>/<total>", or "<suggested>/<total>" when nothing is assigned, or just the total; the count's tooltip reads "<n> clips · <n> assigned · <n> suggested", the row's "<computer>: <full path>".
- Clips still on a card or already filed in the final tree are never listed under source folders. There is no "all clips" source.
- The arrow opens a folder without filtering. Pressing the row filters the clips to that folder and everything under it; pressing it again clears that filter.
- Phone and desk: on a phone, pressing a folder row filters the clips and goes to the Clips view by itself; pressing the arrow, a button inside the row, a rename box or a count does not.

### System, hidden and junk files are never listed

These are never listed, in any letter case: the recycle bins of Windows and of the NAS; Windows' system volume folder; macOS's indexing, trash and event folders; version-control and package folders; "lost+found"; the folder duplicates are set aside in; any folder whose name starts with a dot. Nor are these files: macOS folder-settings files and the "._" files macOS leaves on other drives; Windows' thumbnail cache and folder-settings files; a sync tool's state files. Shortcuts and links to other folders are not followed.

### New footage appears on its own once it has finished arriving

New footage in any source folder or the final tree is noticed within about 20 seconds, and every open Sorter page shows it within about 15 seconds after that, with a message "<n> new clip(s) arrived" for 4 seconds. New folders, including ones made in a file manager, appear in the trees the same way.

- A clip appears only once its files have stayed the same size and date across two checks in a row, so a file still being copied is never shown half done; meanwhile the clip as it was before, if any, stays shown.
- A deleted folder's clips go. A drive that is unplugged, or a share that is not mounted, changes nothing: its clips stay as they were.
- The Sorter's status shows when the last check ran, how many folders it checked, how many had changed, and how many files are still arriving.
- An open page stops asking while its tab is hidden, while a look through the folders runs, and while a folder is being named; it asks at once when it comes back.
- Cards arriving in a reader, leaving it, and copying show in every open Sorter page as they happen; if the page loses its connection it is back within about 2 seconds. A card that the app on the editor's computer opens the Sorter for is shown straight away in that page, in the card's own view.
- On its own: when a clip has finished arriving (unchanged across two checks).
- By hand: a person can have chosen folders read again at once (below).

### A person has chosen folders read again now

From any folder in the source tree or the destination tree, a person asks for it to be read again at once; it is read in the background. This catches a file replaced in place under the same name, which the automatic check cannot see. Only folders that exist inside a source folder or the final tree count; if none of those asked for do, the person is told "none of those is a folder inside a source or destination root".

- Who: anyone signed in.

### A full look through every footage folder

A full look reads every source folder and the final tree and lists every clip. It never changes footage.

- It runs when a person presses Rescan, after every move, after every card copy, every night at 03:30 site time, and once when the Sorter is first switched on.
- Only one runs at a time: asking again while one runs says so and shows the count it has reached.
- While it runs the header shows "Scanning…" and the clip count found so far, and the page stays usable and keeps loading however long the look takes.
- A source folder that is missing is reported as unavailable, a file where a folder was expected as not a folder, and a folder that cannot be read as unreadable, with the reason. The look carries on with the rest, and up to 50 such warnings are shown.
- If the look fails, the list from the last look stays and the error is shown.
- Afterwards the status shows the clip count, total size, when it started and finished, any error, the warnings, and a one-line account of footage found moved or renamed outside the Sorter (see Moving footage on the NAS).
- With no clips at all the clip area reads "No clips scanned yet - press Rescan."
- Who: anyone signed in.
- Phone and desk: Rescan is reachable on a phone.

### The Sorter's work through the day and night

Without being asked, the Sorter: notices new footage within about 20 seconds; re-reads the final tree about every minute; re-reads the studio's calendar about every 15 minutes; makes missing pictures; stops showing a card no computer has reported for 30 minutes; makes a full look every night at 03:30; backs up the record of every copy every night at 04:00; and walks the whole footage share on the NAS every night at 04:30 to bring the record of every copy up to date (see The record of every copy). All times are the site's time.

- If any of these fails, it tries again at its next turn, and the Sorter's status shows which one failed, when, and why, beside when it last succeeded. A nightly job that fails two nights running is a problem the server found.

### The destination tree shows the final tree as it is, plus what is planned

The destination tree shows the folders of the final tree, never files, down to 8 levels, in the Sorter's name order. It leaves out hidden folders, names starting with "$", system folders, and folders called Proxy, Render in place or Renders in place (any letter case). Planned folders that do not exist yet are merged in and marked as planned. When time folders are on, the time folders the assignments would make are listed under each destination. An empty folder looks different from one holding footage.

- It is re-read about every minute, and at once after a look through the folders, a move or a card copy.
- With no final tree set, it is empty.

### Folder names sort in one fixed order that handles Chinese

Folder names, groups and planned folders sort in British English order: spaces before punctuation, then symbols, digits, Latin letters, other scripts, and then Chinese characters by radical and stroke count. Accents count before letter case, and lower case comes before upper. Characters outside this order come last, by character code. This order also decides which of two shoots at the same time is the one called "(2)".

### Opening the page asks where to look and loads little

The page opens quickly even on a laptop far from the studio: it loads the clips on cards and in source folders (well under 0.2 MB to start), and the clips already filed in the final tree, usually most of them, only when a view needs them; they are then kept for the visit. Until then the final tree's numbers come from a summary the server keeps ready (made shortly after start, daily, and after every change). A clip's full list of files is fetched when its details are opened.

Until the person says where to look, the clip area shows "Choose where to look", "Pick a source folder, a card or a drive on the left, and its clips appear here.", then "<n> clip(s) in your source folders · <n> card(s) in a reader. The destination’s clips are not loaded until you ask for them." with "All clips (<total>)" (tooltip "Load every clip, the destination’s too"), which clears any source folder picked and shows everything, and on a phone "Open Source". It goes away as soon as a source folder, card, destination folder, event, search or filter narrows the view.

- While a drive's clips are listed: "Listing the clips on <drive>", "One moment.".
- While the final tree's clips load: "Loading the destination’s clips", "About <n> clips · they are fetched once, then kept for this visit." (or "One moment."). If that fails: "The destination’s clips did not load", the reason, and Try again; a message "Could not load the destination clips: <reason>" shows too.
- When nothing matches: "No clips match the current filters."
- The clip area's heading reads "<n> clips" or "<n> of <total> clips".

### The page says it is loading, and says plainly when a load fails

Until the clips have arrived, the clip area shows a spinner with "Loading your clips" and "One moment.", never "No clips match the current filters". If the first load fails, a message "The clips did not load: <reason>" stays up for 20 seconds, and the clip area shows "The clips did not load", the reason, and Try again, which repeats the whole first load (clips, folder trees, calendar events and the missing-footage checks). Whenever the server refuses or fails a request, the person is shown the server's own explanation, or else the first 200 characters of its answer, or else the status it returned.

### The page chooses a phone or a desk layout, and a person can force either

The layout is chosen before the page is first drawn, so a phone never sees the desk layout flash up. The phone layout is used when the device has a touch pointer that cannot hover and the smaller of its screen width and window width is under 1,024 pixels, or whenever the window is narrower than 720 pixels; a browser's "desktop site" request does not change this. The choice is made again shortly after a window stops being resized.

- On its own: phone or desk layout, from the device and the window's width as above.
- By hand: in the Sorter's own settings a person picks Phone, Desk or Automatic. The choice is remembered on that browser until changed (Automatic when the browser will not remember anything).

### On a desk the sources, the clips and a panel sit side by side

The desk layout shows three areas at once: the sources (computers, their folders and cards), the clip grid, and a panel holding the destination folders, the calendar events, the selected clip's details, the audio worklist, the missing-footage checks and the crew's card tracker. A header carries the totals and the main actions; a toolbar carries search, filters, sort and the actions on selected clips. A line of hints reminds the person of the mouse and key moves ("click · ctrl+click · shift+click · drag box", "drag onto a destination folder to assign", "[ ] suggestion  Ctrl F search  Ctrl + Ctrl − size") and reads SORT, or COPY while an open card shows a copy running.

- The sources area and the panel can be resized by dragging the border between them (sources between 150 and 560 pixels wide, the panel between 200 and 640).
- The sources area can be hidden, and the clips then fill its space; one control brings it back. Widths, whether the sources are hidden, and the last panel opened are remembered on that browser.
- Managing the studio's known drives is in the Sorter's settings, not on the sorting screen.

### On a phone the Sorter shows one of three views at a time

The phone layout shows one view at a time, switched from a bar that never moves: Source, Clips (its button carries the clip count) and Folders (the destination folders and every other panel). The phone opens on Clips.

- Leaving Clips adds one step to the browser's history, so the phone's back gesture or button returns to Clips; moving between Source and Folders adds no more steps.
- Pressing a folder row in either tree filters the clips and goes to Clips by itself.
- The toolbar keeps the search box, the status buttons and a Filters button that opens and closes every other filter (camera, date, pick a day, kind, location, where the copies are, drive, sort and its direction, clear filters, thumbnail size, structure); the open filters scroll when taller than about half the screen.
- Accept suggestions appears only when it would do something. With clips selected, the selection count, Assign to… and Unassign appear.
- Dialogs fill the width, and messages stretch across the bottom, above the bar.

### Every control of the Sorter can be reached by touch

Everything a person can do in the Sorter with a mouse and keys can be done on a touch screen, a phone included.

- Controls are at least 44 pixels tall (small ones 36) on any touch device, and form fields use text large enough that a phone does not zoom in.
- The add, remove and rename buttons on folder rows are always shown on a touch device (with a mouse they appear when the row is hovered).
- A long press on a clip opens its menu, the same menu a right-click opens, with Preview and Clip info added.
- A tap on a clip selects it alone. Select several in the toolbar turns each tap into adding or removing one clip, and Select all selects every clip in view; these stand in for Ctrl or Cmd, Shift and drawing a box.
- Assign to… stands in for dragging clips onto a folder, and Clip info for double-clicking.
- The Sound switch, the suggestions menu for several clips, Download…, Share folder…, Rescan, and the calendar's connection and settings are all reachable on a phone. The key hints are shown only where there is a keyboard.
- Phone and desk: the controls are the same; only where they sit differs.

### The header shows the library's totals and leads back to the dashboard

The product mark leads back to the dashboard, with a compact "‹ CC Sync" link as well. The totals: clips in the whole library (filed clips not yet loaded included), clips assigned (clips assigned in place and every filed clip count), clips suggested but not yet assigned, the total size assigned and the total size of everything. "Scanning…" shows while a look through the folders runs. The header also carries the not-at-home and backups counts (see The record of every copy), the Sorter's settings and Move….

- Phone and desk: on a phone and in windows 1,500 pixels wide or less, the suggested count and the total size are left out and the not-at-home and backups counts are shown in short form; every one of them is still in the Sorter's status.

### Short messages appear and fade on their own

Messages are plain, success, warning or error. They fade after 3.2 seconds, or 6.5 seconds for an error, unless a message says otherwise. A message may carry one button (Go to open a card, Undo, or Fix); pressing it closes the message and does the action.

### Every dialog closes the same ways

A dialog has a title with a close cross, a body, and a row of buttons (a single Close unless it needs others). Escape closes the topmost dialog, as does a press on the dimmed area outside it or on the cross. The first field, list or button inside gets the keyboard focus unless that dialog says otherwise.

### A destination folder is picked from one searchable list wherever a folder is chosen

"Choose destination folder" lists every folder of the final tree and every planned folder (tagged "planned"), each with its parent path and its name. Typing ("Type to filter folders…") filters by any part of the path, ignoring letter case. At most 400 rows are drawn at once; typing narrows them. Up and Down move the highlight, Enter picks the highlighted folder, a press picks a folder, and the pointer highlights the row under it; arrows and Enter are ignored while Chinese, Japanese or Korean typing is mid-composition. "No matching folder." shows when nothing matches. Clear (only where no folder is allowed) and Cancel; any other way of closing it is a cancel.

### Sizes, counts, lengths, days and times read the same way everywhere

- Sizes: B, KB and MB as whole numbers; GB and TB with two decimals under 10 and one decimal from 10 up.
- Counts with thousands separated by commas.
- Lengths as m:ss or h:mm:ss; nothing is shown for zero or unknown.
- A day as year-month-day with the weekday ("No date" when there is none).
- A clip's time as hours and minutes exactly as the camera recorded them, in the camera's own local time, never converted between time zones ("--:--" when unknown).
- The same rules hold on the page a folder link opens.
- Pending: footage-sorter-and-camera-cards-3-Q4

### The clip grid stays smooth with tens of thousands of clips

Clip cards fill the width of the area, each between 168 and 262 pixels wide at normal size, as many columns as fit, and the grid scrolls smoothly however many clips it holds. Thumbnail size has six steps (0.78, 1, 1.3, 1.7, 2.2 and 2.9 times normal; normal at first), changed with minus and plus buttons or Ctrl or Cmd with minus or equals, and remembered on that browser. After a size change or a window resize the grid keeps roughly the same clip at the top.

### Each clip card says what the clip is, where it is and where it is headed

A clip is one recording (a video, a still, an image sequence, an audio file or "other"), possibly made of several files. Its card shows:

- its picture, or a placeholder for its kind until the picture arrives, and for a card clip whether its picture has arrived yet;
- the camera ("other" when unknown), its kind when it is not video, and its length when known;
- a mark for where the footage physically is (on a card, in staging, in the final folders, or elsewhere), and whether a second copy exists;
- its backup state (see Backed up and safe to format), the state of a planned copy when there is one, and on how many drives it sits with a warning when it is only on a card or a laptop (see The record of every copy);
- how many copies of it are known elsewhere, whether one is at home, and for a card clip where it is already filed;
- its name ("(unnamed)" when none), the recording time, the last part of its source folder, and its size;
- at its foot, either its destination (the last two parts of the path, "(root)" for the root) with a ✕ that unassigns that clip, or its suggestion with a ＋ that accepts it, never both;
- whether it is selected, assigned or only suggested.

The clips shown can be limited to some of these places. Opening one clip's full details lists its files ("unknown clip" when it has gone).

- On its own: a suggested destination for each unassigned clip (see Sorting into shoots, people and cameras).
- By hand: ＋ accepts the suggestion, any folder can be assigned instead, and ✕ unassigns. A clip assigned by hand keeps that assignment whatever later suggestions say.

### Hovering a card's destination or suggestion explains it

A destination reads "In place: <dest>" when the clip already sits where it is assigned, otherwise "Assigned to <dest> · <structure>" (the structure is "convention" unless another was chosen). A suggestion shows its summary or folder name, starting with "♪ " when it came from the audio, and looks different when its confidence is low, when it was read from an event's title, when it was heard in the audio, and when other shoots are in contention. Its tooltip reads "Suggested (<confidence>, heard in the audio | , inferred from the event title | , from a folder you bound): <dest>", then the reason, then one line per alternative "also possible: <dest>  (<summary>, <n> min off)", then "Click to accept".

- Phone and desk: on a touch screen the same words are in the clip's details.

### Hovering a clip card shows where it is and whether it is safe

The card's tooltip gives the name, the source folder ("(root)"), the number of files and size, the recording time, the explanation of its health, then "On card <drive>", "Staging", "Final" or "Elsewhere", and "backed up" (with " to <backup>", or " (the record of copies: copies elsewhere)" when only the record of every copy says it is safe, plus " (matched as a twin of a copy already filed)" when that applies) or "not backed up", and " · destination: <plan state>" when a copy is planned.

- Phone and desk: on a touch screen the same facts are in the clip's details.

### Clips assigned to a folder but not yet in it are marked as staged

When the grid is filtered to a destination folder, a clip assigned there but physically still on a card, in staging, elsewhere, or filed in a different final folder, is marked as staged. A clip assigned in place is never staged.

### Selecting clips

- A plain click selects only that clip and makes it the anchor.
- Ctrl or Cmd click adds or removes one clip and moves the anchor.
- Shift click selects every clip between the anchor and the clicked one in the present view, replacing the selection, or adding to it with Ctrl or Cmd held.
- Pressing on empty grid space and dragging draws a box, and every clip it touches is selected, clips scrolled out of view included. Without a modifier the old selection is cleared at the press; with Ctrl, Cmd or Shift the box adds. A box counts after more than 3 pixels of movement, and holding the pointer within 34 pixels of the top or bottom edge scrolls the grid, faster the further past the edge.
- Ctrl or Cmd A selects every clip in the view. Escape clears the selection.
- A selection survives filtering: clips filtered out stay selected and are still acted on, after the visible ones.
- The toolbar reads "0 selected" or "<n> selected · <size>".
- A click (not a box) also shows the clip's destination folder in the destination tree.
- Phone and desk: on a touch screen, see Every control of the Sorter can be reached by touch.

### Dragging clips onto a folder assigns them

Dragging a clip that is not selected makes it the only selection first; then every selected clip moves together, in grid order, under a label "<n> clip(s) · <total size>", and the dragged cards dim. Dropping them on a destination folder assigns them there (see Sorting into shoots, people and cameras). Double-clicking a clip opens its details.

- Phone and desk: on a touch screen Assign to… does the same as dragging, and Clip info the same as double-clicking.

### One search box finds clips by name, folder, camera, kind, destination, event and suggestion

The search box ("Search stem, folder, camera, destination, event…"; Ctrl or Cmd F puts the cursor in it and selects its text from anywhere) matches, ignoring letter case, any part of a clip's name, source folder, camera, kind, assigned destination, its suggestion's summary and folder, and those of its alternatives, so a shoot's name finds every clip it was in contention for. When an event is picked as a filter, the typed text does not filter clips: the event is the search.

### Clips are filtered by camera, day, kind, sorting state and where they are

- Camera: "All cameras", then each camera with its count ("other" for unknown).
- Date: "All dates", then each recording day with its count ("(no date)"); picking a day shows every clip from that day.
- Kind: "All kinds", then each kind with its count.
- A chosen value that no longer exists falls back to All.
- Status buttons: All, Unsorted (no assignment), Suggested (no assignment, has a suggestion), Assigned, Not backed up (tooltip "Clips that exist in only one place").
- Location: All locations, Card (<n>), Staging (<n>), Final (<n>).
- Clear filters resets the search, camera, date, kind, status, location, where the copies are, drive, source folder, destination folder, event and "All clips".
- Filters, selection and search are not kept between visits.

### Clips sort by time, length, size, name or fewest copies, with unfinished work first

Time is the starting sort; ↑/↓ reverses it ("Reverse the sort"). Whatever the direction, clips that still need work come first and finished ones last: a clip the present move plan will skip, or that already survives elsewhere (with no plan, a clip already backed up), sinks to the bottom. Clips whose value is unknown also sink, in either direction. Ties are broken by name in natural order. Length uses lengths learned while previewing too. The sort field is remembered on that browser; the direction is not.

### The destination tree follows the clip the person clicks

Clicking one clip opens the destination folders and shows its assigned (or else suggested) folder: every parent opens, the folder scrolls to the middle and flashes for 1.2 seconds. With several clips selected it only opens the destination folders. It does not switch away while the clip's details or the audio worklist are showing; a single audio clip with transcript results opens the audio worklist instead. When another control asks to show a folder that is not in the tree, the person is asked "That folder is not in the tree - rescan the destinations?" (nothing is said when the tree was only following a click).

### A clip's details show everything about it, or a summary of several

The details are headed "Clip info", or "<n> selected" with several. They show the clip as it is at the moment they open. They open when a clip is selected (in the panel on a desk, in the Folders view on a phone), and also on a double-click and from Clip info in the clip's menu.

- Nothing selected: "Select a clip to see its details."
- Several selected: the count, the total size, "Assigned (<n> of <m>)", and the kinds ("video × 3, audio × 1").
- One clip: Stem, Kind, Camera, Recorded ("unknown"), Duration, Size and number of files, the clip's id, and for an image sequence its folder.
- "Where it is": the root, the folder ("(root)"), the main file's full place on the server, and Show in source, Show in destinations (when assigned or suggested; its tooltip is the folder, with "(suggested)" when only suggested) and Show in the file manager.
- Every place a copy of it is stored, with whether each was verified (see The record of every copy).
- "Sorting": Assignment ("unassigned", "in place - <folder>", or the folder), Structure, Suggestion ("<dest> (<confidence>)" or "none"), "From event" or "Heard", Timing ("recorded during the event" or "<n> min outside it", not for audio), and Why.
- "Also possible": each alternative's folder, "<summary> · also within the hour window | same day · <n> min off", and Use this instead, which assigns the clip there.
- "Heard on the audio": each name recognised with its episodes, "(two episodes - not guessed)", "(part of the name only)", a quote and the second it was said at; up to four self-introductions ("said: <name>" with the quote); "Scanned <n> of <m> min."
- "Media": "Reading…", then the technical details (below), or "no media streams", or the reason they could not be read.
- "Files", when there is more than one: each file's role, place and size.

### Right-clicking a clip opens a menu to find it, its other possible folders and the clips shot alongside it

Right-clicking a clip selects it if it was not, and opens a menu at the pointer, kept inside the window; anywhere else the browser's own menu stays. The menu closes on any press outside it, a scroll, a resize, the window losing focus, or Escape. On a touch screen a long press opens it.

- Show in source (hint: its folder) opens the sources down to its folder, filters to it, keeps the clip selected, scrolls to it and flashes it: "<n> clip(s) in <folder>". For a filed clip: "That clip is in the destination, not a source folder.", and its folder in the destination tree is shown instead. A button beside it shows the folder in the file manager.
- Show in destinations (hint: the folder; "<folder>  (already there)" for a card clip the final tree already holds; "<folder>  (suggested)"; or "nowhere yet", greyed out).
- "Also suggested": Assign to <folder> for each alternative (hint "<dest>  ·  <summary>, <n> min off"), each with a button that shows that folder.
- "Rolling at the same time": up to six source folders where another camera (or the same camera on another card) recorded within this clip's span widened by 30 minutes on each side, other cameras first and then the biggest, each "<camera> · <n> clip(s)  HH:MM-HH:MM" with the hint "<folder>  ·  <n> already placed in <folder>" or "none placed yet". Choosing one shows and selects exactly those clips ("<camera> at the same time").
- Transcript & who is talking (audio only; hint "looks like <name> (<confidence>)", "sounds like …" when the evidence disagrees, "transcribed, nobody recognised" or "not transcribed yet") opens the audio worklist (see Placing sound recordings).
- Show in the file manager ("Reveal this file on disk").
- Preview (on a touch screen) and Clip info.
- Showing a set of clips from anywhere clears every filter, selects them, scrolls to the first and says "<n> clip(s) selected - <label>".

### A clip can be played in the browser, with seeking

A clip plays, and can be scrubbed, in the browser: its proxy when it has a playable one, else the recording, else any playable file. Playable: MP4, M4V, MOV, MKV, WebM, WAV, MP3, M4A, AAC, FLAC and OGG. What a person may be told: "unknown clip"; "card is being copied" (a card is not read while it is being copied); "no playable file for this clip"; "file unavailable". A clip on a card in a reader plays only on the computer holding the card, from the camera's own proxy where there is one.

- Who: anyone signed in.

### A clip's technical details

For a clip's main file the Sorter shows the file format, length, bit rate and number of streams; the video codec, profile, frame size, frame rate and average frame rate, pixel format, bit depth, colour space, transfer and primaries, pixel shape and frame count; and the sound codec, channels, layout, sample rate and bit depth. They are read from the recording, giving up after 30 seconds, and remembered until the file changes. When they cannot be read the person is told why in plain words: the file could not be read, the read took too long, the file holds no media streams, the clip is unknown, or the clip has no files. A clip still on a card shows its details once it has been copied.

### Showing a clip's file in the file manager on the person's own computer

Show in the file manager, from the clip's menu, its details and the audio worklist, opens the person's own file manager (Explorer on Windows, Finder on macOS) with the clip's file selected; for an image sequence it opens the sequence's folder. It works on a computer where the app is running and the footage is reachable (the studio's shared folders, or a card in that computer's reader): the clip's place on the server is turned into the place as that computer reaches it.

- Where that cannot be done (a phone, a computer without the app, footage that computer cannot reach), the person is told so and shown the clip's place on the server, with a button to copy it.
- What a person may be told: "Opened in the file manager"; "nothing to show"; "not on disk any more - rescan?"; "Could not open it: <reason>".
- Windows and macOS: Explorer on Windows, Finder on macOS.
- Pending: footage-sorter-and-camera-cards-3-Q3

### The page summarises the final tree by destination and by day

The Sorter shows: the number and size of the clips in the final tree; for each destination, how many clips are assigned there and their size, and the total assigned; clips in the final tree whose name matches a clip still waiting to be sorted (possible duplicates); for each day, the count, size and cameras, for picking a day; which timed events already have sorted footage within 30 minutes of their time; and on how many clips each name heard in the footage was heard.

### The Sorter remembers a person's view on that browser, but not their filters or selection

Remembered on that browser: the layout choice, thumbnail size, sort field (not its direction), Sound, the last panel opened (the destination folders at first), the widths of the areas, whether the sources are hidden, and the order the drive list is sorted in. Not remembered: filters, selection, search.

### The Sorter's keys

| Key | What it does |
|---|---|
| Ctrl/Cmd+F | Put the cursor in the search box and select its text, even while typing |
| Ctrl/Cmd and = or + | Bigger thumbnails (instead of the browser's zoom) |
| Ctrl/Cmd and - or _ | Smaller thumbnails |
| Ctrl/Cmd+A | Select every clip in view (not while typing or in a dialog) |
| F2 | Rename the last-clicked real destination folder |
| Escape | Clear the selection and stop a preview; in a card's view with nothing selected, leave the card's view; also closes the topmost dialog, the clip menu and the settings |
| [ and ] | Previous or next suggestion for the selected clips |
| Delete or Backspace | Unassign the selected clips |

Except for the first three, keys do nothing while typing in a box or with a dialog open.

- Phone and desk: every one of these has a control that can be reached by touch; renaming a folder is the rename button on its row.

### The Sorter's settings

Every setting of the Sorter is on the Sorter's settings, besides the folders above:

- Setting: Studio time zone. Does: the time zone every recording time and calendar time is read in when footage is matched to the studio's calendar, as a fixed offset with no daylight saving. Default: the site's own time zone, set when the part is switched on. Who: an admin. Applies to: the site. Search words: time zone, offset, clock, calendar times.
- Setting: Calendar events from. Does: the earliest date of the studio's calendar events that are read. Default: the day the part is switched on. Who: an admin. Applies to: the site. Search words: calendar start, events from, earliest event, date.
- Setting: Calendar refresh. Does: how often the studio's calendar is read again. Default: every 15 minutes (from 5 minutes to one day). Who: an admin. Applies to: the site. Search words: calendar refresh, how often, events, interval.
- Setting: Calendars read. Does: which of the studio's calendars the Sorter reads events from. Default: the connected account's main calendar. Who: an admin. Applies to: the site. Search words: calendars, which calendar, events, account.
- Setting: Time folders. Does: whether each assigned folder gets one folder per day and camera (see Sorting into shoots, people and cameras). Default: off. Who: an admin. Applies to: the site. Search words: time folders, per day, per camera, day folders.
- Setting: Camera labels. Does: the label each kind of camera gets in time folder names (for example a label for each camera model the studio shoots on, one for drones, one for sound). Default: none until set; the studio's own labels are carried over. Who: an admin. Applies to: the site. Search words: camera labels, A-CAM, camera names, angle names.
- Setting: Bring the camera's proxies with a card copy. Does: whether a card copy also copies the proxies the camera wrote, into a folder named "proxy" beside the footage. Default: on. Who: an admin. Applies to: the site. Search words: camera proxies, card copy, proxy folder, bring proxies.
- Setting: Room to leave on the target drive. Does: the space a card copy must leave free on the drive it copies to, or it does not start. Default: 256 MB. Who: an admin. Applies to: the site. Search words: free space, spare room, margin, disk full.
- Setting: Count an unverified card copy as done. Does: whether a card copy that could not be checked may still count as finished. Default: off. Who: an admin. Applies to: the site. Search words: unverified copy, verify, checked copy, done.
- Setting: Same name, different file. Does: what a card copy does when a file of the card has the name of a different file already there: keep both (the incoming one is renamed) or skip the incoming file. Default: keep both. Who: an admin. Applies to: the site. Search words: name clash, same name, duplicate name, keep both.
- Setting: Crew card list refresh. Does: how often the crew's list of cards is read again. Default: every 15 minutes. Who: an admin. Applies to: the site. Search words: crew cards, card tracker, card list, refresh.
- Setting: Card names. Does: the label written on each card, given to its serial number (see Recognising cards and drives). Default: none. Who: anyone signed in. Applies to: the site. Search words: card names, card labels, serial number, SD card.
- Name and search words: Footage Sorter settings. Search words: sorter settings, card copy settings, calendar, time folders.
- Pending: footage-sorter-and-camera-cards-3-Q2

### Connecting the studio's calendar

The control for connecting the studio's calendar stays on screen, steady, until the calendar is connected. When a connection fails the person is told why, and the control stays so they can try again. Once connected, the header says whether the calendar is connected and when it was last read.

- Who: an admin.
- Phone and desk: the connection and its settings are reachable on a phone.
- Pending: footage-sorter-and-camera-cards-3-Q2

### The field backup page on an editor's computer keeps itself up to date

The app on an editor's computer has its own page for backing up cards in the field, opened in a browser on that computer; it needs no internet. It refreshes every second while any copy is running and every 4 seconds otherwise; while its browser tab is hidden it does not refresh, and when the tab is shown again it refreshes at once. The first load always takes a fresh look at the drives. With scripts switched off in the browser it shows "This page needs scripts switched on in the browser. It does not need the internet." If the app stops answering, the status at the top is replaced by one red "The app is not answering". A refusal from adding a folder, setting a drive's kind or starting a copy is shown at the bottom of the screen for 9 seconds. The page is two columns on a screen 900 pixels wide or more and one column below that.

- Who: the person at that computer.

#### Lessons

- Met: SRT-160, SRT-163, SRT-164, SRT-165, SRT-166, SRT-167, SRT-168, SRT-169, SRT-170, SRT-161, SRT-162, SRT-171, SRT-172.

## Archive search

### One search covers every place the studio's footage lives

Archive search finds footage wherever the record of every copy knows it to be: on the NAS, on every known drive (plugged in or not), in the cloud backup and on tapes. Each result shows the clip, its project, recording date, name, camera, size and every place a copy of it is stored, and the results sort by project, date, name, camera, size or number of copies.

There are four ways to search, chosen beside the search box:

- **Exact**: the words as typed, in names and folders.
- **Loose**: close spellings and parts of words.
- **Across languages**: an English word finds a Chinese name and the reverse (below).
- **Ask the assistant**: a question in ordinary words (below).

- Who: anyone signed in.
- Name and search words: Archive search. Search words: find footage, where is clip, archive, drives, tapes.
- Phone and desk: the search and its results work at phone width, every control reachable by touch.

### Names are found across languages and scripts

A name search matches across Traditional and Simplified Chinese, across English and Chinese, and across pinyin, so a person can type a name in whichever way they know it. Any query of two Chinese characters finds every name containing them. When a person corrects how a name is translated, the correction is kept and used for every later search.

- On its own: the English, pinyin and other-script forms each name is matched under.
- By hand: a person sees the forms a name is matched under beside the result and corrects any of them; a correction made by hand is never overwritten by a later automatic pass.

### Searching an event or folder name shows the event and its clips

Searching the name of an event (a shoot in the studio's calendar) or a folder, in Chinese or English, returns the event itself with its date and the clips assigned to it, as well as matching clips.

### The assistant searches on a person's behalf and shows every search it ran

Asked a question in ordinary words, the assistant runs searches of the archive for the person and answers with results. The answer lists every search it ran, each as a query the person can edit and run again, and gives a reason for every result it shows. Only file details (names, folders, dates, cameras, sizes) are ever sent to the assistant; no footage leaves the NAS.

- When the assistant is off: the Ask mode is not offered and the other three ways to search work as before.

#### Lessons

- Met: SRT-173, SRT-174, SRT-175, SRT-176.

## Downloading originals and sharing folders

### A signed-in person downloads chosen clips' originals into a folder on their own computer

Download… ("Download the selected clips into a folder on this computer") is available once clips are selected. Only one download runs at a time: "A download is already running. Wait for it to finish, or cancel it first."

- A dialog "Download <n> clip(s)" says "Working out what to download…", then "<n> file(s), <size>, from <n> clip(s)." and, when some are left out, "Left out: <n> clip(s) is/are still on a card in a reader, not on the server; <n> file(s) is/are no longer on the server; <n> clip(s) could not be found." If it cannot be worked out: "The download could not be planned: <reason>".
- At most 20,000 clips at once: "that is more than 20000 clips at once: download a folder at a time". Only footage the Sorter has found can be downloaded.
- Also download the proxies (off at first; ticking it works the download out again).
- In a browser that can save into a folder the person picks (Chrome or Edge on a computer): "You will be asked for a folder on this computer. Choose or make a folder INSIDE Documents, Downloads or a drive: the browser refuses those themselves (it says the folder contains system files). The files are saved into it with their folders kept. Keep this tab open while it runs. Files already in the folder are not downloaded again. If the tab or the browser crashes, the file that was arriving starts again from its beginning." and Choose a folder and download. The folder picker opens in Downloads, or the last folder chosen, so a folder inside it can be picked; "The folder could not be opened: <reason>".
- The files keep their folder layout below the clips' common folder (just their names when the files come from two different drives).
- In other browsers and on phones: "This browser cannot save into a folder you pick: use Chrome or Edge on a computer for that. Here, click each file to download it." and up to 500 links "<path>  (<size>)", each downloading one file and able to resume.
- While it runs, a panel stays in a corner: "Downloading to <folder>", a bar, "<done> of <total> files, <size> of <size>, <speed>/s, <eta>" ("Paused. " first while paused), the files in hand or "Connection lost, trying again", Pause or Resume, and Cancel. Speed is over the last 10 seconds, updated every half second; time left reads "<n> s left" under 90 seconds, "<n> min left" under 90 minutes, then "<h> h <m> min left".
- How it ends: "Done. All <n> files are in <folder> (<n> were already there)."; "<n> of <m> files are in <folder>. <k> could not be downloaded:" with up to 50 lines "<path>: <reason>"; "Your sign-in ran out. Sign in again in another tab, then download again into the same folder to carry on."; "Stopped. Download again into the same folder to carry on from here." ✕ removes the panel.
- If the person is not signed in: "sign in to download footage".
- Who: anyone signed in.
- Windows and macOS: the same in Chrome or Edge on either.
- Phone and desk: on a phone the files are offered one by one as links; Download… is reachable there.

### A download into a folder keeps folders, never overwrites, and carries on where it stopped

- Folders are kept. Characters Windows forbids in names (< > : " \ | ? * and control characters) become "_", and trailing dots and spaces are removed.
- A file already there at full size is left alone and counted as already there.
- A different file with the same name is never touched: "A different file with this name is already in the folder. It was left alone."
- A file being downloaded is marked as unfinished beside itself. The next download into the same folder continues it from where it stopped (from its start if the server cannot resume it); the mark goes when it completes. Only files the download itself marked are continued, and nothing else is ever deleted. What arrived before a fault is kept.
- Every file is checked by name before it is sent. If the footage was found again and reordered since the download was worked out: "the clip changed since the download was planned: start the download again". A file gone from the server: "the file is not on the server any more". A file the server answers in full when asked to resume starts again from its beginning.
- A dropped connection is tried again after 2, 5, 10, 20, 30, 60, 60 and 60 seconds while nothing new arrives (any progress starts the count again); then "The connection kept dropping. Run the download again to carry on from here.", or "The server kept ending the file early."
- A sign-in that runs out stops the whole download. A file the server refuses, no longer has, or has lost fails on its own with the server's message or "The server no longer has this file."; any other error reads "the server answered <status>" and is tried again.
- Leaving the tab while it runs asks first, and the screen is kept awake, where the browser allows both.

### An admin makes a link that hands a folder of footage to anyone holding it

Share folder… ("Make a link for a folder that anyone you send it to can download from") shares the last-clicked destination folder, or else the source folder picked; long-pressing or right-clicking a destination folder opens it for that folder directly. With no folder picked: "To make a link, click a folder in the Source or Destinations tree first, then press Share folder. Right-clicking a destination folder works too."

- The dialog: "A link for <folder>", "Anyone who has the link can download everything in this folder, without an account, until it runs out or you switch it off.", a name ("Name shown to the person (optional)", at most 120 characters; the folder's name when left empty), how long it lasts (7, 14, 30 or 90 days, or No end date; 14 at first), and Make the link. Failure: "The link could not be made: <reason>".
- Refusals: a whole source folder, the whole final tree or a card: "choose a folder inside it: a link for a whole root would hand out everything"; "that folder is not inside one of the sorter's folders"; "that is not a folder a link can be made for"; "that folder is not on the server yet (a planned folder has nothing in it to share)"; "a link lasts between 1 and 365 days, or has no end date".
- A link made shows "For anyone" (the studio's public address, when one is set up) and "On the team network" (or just "Link", with a note that it only opens for people on the team network because no public address has been set up), each with Copy ("Link copied").
- The link cannot be guessed.
- Who: an admin. Anyone else is told "<what> needs an admin of this dashboard".
- Phone and desk: Share folder… is reachable on a phone.
- When camera cards with the Footage Sorter is off: its links do not open.
- Pending: footage-sorter-and-camera-cards-3-Q5

### An admin sees every folder link and can switch one off at once

Links lists every link ever made that hands footage to people outside the studio, newest first: the Sorter's folder links, and the b-roll archive's client folder links when that part is on, each saying which kind it is. For each: its name or folder, "<folder>  ·  by <who>  ·  opened <n> time(s)  ·  until <date>" (or "no end date"), and "switched off" or "ran out" when it is no longer active. It also shows when each was made, when it was last opened and when it was switched off. Active links have Show link and Switch off ("Link switched off"; "Could not switch it off: <reason>"); a link switched off stops opening at once. "Loading…", "No links yet.", "The links could not be loaded: <reason>".

- Who: an admin.
- Name and search words: Folder links. Search words: shared links, share folder, footage links, switch off link.
- Pending: footage-sorter-and-camera-cards-3-Q5

### Someone holding a folder link sees its files and picks which to take

No account or sign-in is needed. The page is hidden from search engines and passes no referrer. It reads "Footage shared with you", the link's name (or "Footage", also the tab's title), and "<n> file(s), <size>. This link works until <long date>.", with "Only the first <n> files are shown" when the list stopped early. It lists up to 16 folders deep and 50,000 files.

- Files are grouped by folder ("Top folder" for loose files), each group with "<n> file(s), <size>". Groups start open unless there are more than 12 groups or the group holds more than 60 files.
- Each file shows its path, size and when it was changed, and is a direct download link that can resume.
- A tick per group and per file; "<n> of <m> files ticked, <size>".
- Each opening of the list counts as an open of the link.
- If the list cannot be loaded: "The folder could not be loaded" with "<reason>. Reload the page to try again."
- On its own: which files start ticked: every file, except any folder named "proxy" at any depth, which starts unticked.
- By hand: the person ticks or unticks any group or file before downloading.
- Who: a client or anyone holding the link.
- Phone and desk: the page works at phone width, every control reachable by touch.

### From a folder link a person downloads the ticked files into a folder, or everything as one zip

- Download into a folder… (only where the browser can save into a folder the person picks; greyed out with nothing ticked or while a download runs), with "Download into a folder: pick a folder on your computer and the ticked files are saved into it, keeping their folders. Choose or make a folder inside Documents, Downloads or a drive: the browser refuses those themselves (it says the folder contains system files). Keep this tab open until it finishes. If it stops, press the button again and pick the same folder: only what is missing is fetched. Proxy folders start unticked." It behaves exactly as a download into a folder from the Sorter, with the same progress panel.
- Download everything as one zip is always offered: every file, whatever is ticked, uncompressed, with no size limit, named after the folder or the link's name ("footage" when there is none). A single sub-folder can be taken as one zip the same way. A file that vanished meanwhile is left out; an empty folder says "nothing to download there".
- Without a folder picker: "This browser cannot save into a folder you pick. Open this link in Chrome or Edge on a computer for that. Here you can click a file to download it, or take everything as one zip (best for smaller folders)."
- How it ends: "Done. All <n> files are in the folder (<n> were already there).", "<n> of <m> files are in the folder. <k> could not be downloaded:", "This link stopped working during the download. Ask whoever sent it for a new one, then pick the same folder to carry on.", "Stopped. Press Download into a folder and pick the same folder to carry on from here."; "The folder could not be opened: <reason>".
- Who: a client or anyone holding the link.
- Pending: footage-sorter-and-camera-cards-3-Q4

### A folder link reaches nothing outside its folder, and an unusable link says so

An unknown link, a link switched off and a link that ran out all look the same, on a page titled "Link not available": "This link is not available" and "It may have been switched off or have run out. Ask whoever sent it to you for a new one." The same words appear if the list cannot be found after the page has opened. Nothing outside the shared folder can be reached ("no such file"), no path can climb out of it, and links to other places, hidden files, Windows' thumbnail and folder-settings files, and files still being downloaded or copied are never listed or served.

### A clip already filed in another project is shared into this one instead of copied again

On a clip that is already elsewhere, filed in another CC Sync project's final folders, Link folder instead (tooltip: CC Sync will share that folder into this project at its original path, with no second copy and no relink) shares that folder into this project. The button then reads "Linked ✓" or "Already linked ✓", with "Folder linked: <path> now shares into this project."; failure says "Could not link: <reason>". The shared folder then reaches editors as any shared folder does (see Sync: What syncs where).

- Who: anyone signed in.

#### Lessons

- Met: SRT-178, SRT-179, SRT-177, SRT-182, SRT-180, SRT-181, SRT-183.
