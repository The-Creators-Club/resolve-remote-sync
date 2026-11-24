# Joins aimed at footage-sorter-and-camera-cards-3

## Checked

- J1 | fine
- J2 | F1
- J3 | F2
- J4 | F3
- J5 | F4
- J6 | F5, F6, F7
- J7 | F8, F9, F10, F11, F12, F13, F14, F15, F16, F17

## Findings

### F1: The b-roll "delivery link" and the Sorter's folder link: one kind of link or two, made by whom
- Kind: differs
- From: broll / A delivery link lets a client download full-quality files
- Here: An admin makes a link that hands a folder of footage to anyone holding it; An admin sees every folder link and can switch one off at once
- From says: "an editor can give a client a delivery link to chosen folders of the archive ... It is revoked, reactivated, renewed and expires exactly as a preview link does ... Who: anyone signed in makes one"
- Here says: "Share folder… (\"Make a link for a folder that anyone you send it to can download from\")" ... "Who: an admin." ... "Active links have Show link and Switch off"
- Settled by: SRT-182 (ruling) settles the Sorter's link ("An admin links one folder ... with an off switch"), but nothing settles the delivery link, so the owner must say: is the link that lets a client download whole folders of full-quality footage the Sorter's admin-made folder link, or is there also a separate b-roll link any editor can make that can be revoked, reactivated and renewed?
- Fix: if one kind, broll's delivery link becomes a pointer to this piece's folder link; if two, this piece's Links list and the open doors in accounts-privacy-legal must name the delivery link and both pieces must say how the two differ.

### F2: The one list of every link handed outside the studio is described as two lists with different people and words
- Kind: contradiction
- From: broll / An editor manages the folder list and makes new folders
- Here: An admin sees every folder link and can switch one off at once
- From says: "The same list also holds the folder links the Footage Sorter makes (see The Footage Sorter and camera cards: Downloading originals and sharing folders) and the delivery links, each marked as what it is."
- Here says: "Links lists every link ever made that hands footage to people outside the studio, newest first: the Sorter's folder links, and the b-roll archive's client folder links when that part is on" ... "Who: an admin."
- Settled by: decision 21.5 (answered 2026-11-24, recommendation A): "show every link handed outside the studio in one list, each saying its kind, switched off from there"
- Fix: one piece holds the one list (who may open it, that it includes delivery links if they exist, and one set of words for a dead link: "switched off"/"ran out" here against "revoked"/"expired" in broll) and the other points at it; broll's client-folder list then holds only client folders.

### F3: Field backup is pointed at a sub-topic of this piece that does not hold it
- Kind: missing
- From: editor-app / Field backup opens from the menu
- Here: nowhere under Downloading originals and sharing folders (the page's refreshing is under The sorter page / The field backup page on an editor's computer keeps itself up to date; the page itself is in part 1)
- From says: "opens the field backup page (see The Footage Sorter and camera cards: Downloading originals and sharing folders)"
- Here says: nothing under that heading; "The app on an editor's computer has its own page for backing up cards in the field" sits under The sorter page
- Settled by: nothing for the owner to decide: both pieces agree the page exists and when it is offered; only the pointer is wrong
- Fix: editor-app should point at part 1, "An editor can copy a card with no network at all" (and part 3, "The field backup page on an editor's computer keeps itself up to date").

### F4: A raw clip without a proxy: told plainly, and picked up soon after its proxy appears, is not what this piece says
- Kind: missing
- From: footage-sorter-and-camera-cards-1 / Raw clips and raw stills always have a picture to show
- Here: Thumbnails and hover filmstrips / Every recording gets a picture and a scrub filmstrip without anyone asking
- From says: "Camera raw video has no picture to show until a proxy of it exists. A raw clip shows its picture from its proxy, says plainly when it has none yet, and shows the picture by itself soon after a proxy appears."
- Here says: "A Blackmagic RAW recording with no proxy beside it, never seen on a card, shows the placeholder for its kind until a proxy exists." and "Any picture or filmstrip still missing is made on its own, at the latest within 6 hours" and "It is tried again after an hour, or sooner if the file changes"
- Settled by: SRT-026 (given, weaker): "A RAW clip previews from its proxy, says plainly when it has none yet, and picks up the picture soon after a proxy appears."
- Fix: this piece should say that every camera raw video (not only Blackmagic RAW) with no proxy shows its placeholder with words saying it has no proxy yet, and that its picture is made as soon as a proxy appears beside it (not after the hour's retry or the 6-hour sweep).

### F5: Whether the first card is selected on its own when the page opens
- Kind: contradiction
- From: footage-sorter-and-camera-cards-1 / Each card is listed under its computer with its state, its health and its copy
- Here: Sources are listed per computer, closed until opened; Opening the page asks where to look and loads little
- From says: "The first card is selected on its own; clicking a card selects it."
- Here says: "Every entry starts closed." ... "Cards already in readers when the page opens do not." ... "Until the person says where to look, the clip area shows \"Choose where to look\""
- Settled by: the owner must say: when a person opens the Sorter while a card is already in a reader, does it open on that card, or on "Choose where to look" with every computer closed?
- Fix: part 1 should drop "The first card is selected on its own" (or part 3 should say the first card is opened and selected, and the prompt shows only when no card is in a reader).

### F6: How quickly a new card shows on an open page: every few seconds or as it happens
- Kind: contradiction
- From: footage-sorter-and-camera-cards-1 / Each card is listed under its computer with its state, its health and its copy (and "The person is told when a card arrives...")
- Here: New footage appears on its own once it has finished arriving
- From says: "No card in a reader. Put one in; this page looks every few seconds." and "While a Sorter page is visible it checks the list of cards about every 5 seconds"
- Here says: "Cards arriving in a reader, leaving it, and copying show in every open Sorter page as they happen; if the page loses its connection it is back within about 2 seconds."
- Settled by: the owner must say: when a card goes into a reader, must every open Sorter page show it at once, or is within about 5 seconds enough?
- Fix: one piece states the promise and the other points at it; part 1's empty-list sentence should then match ("this page shows it as soon as it goes in" if at once).

### F7: A card arriving while another card's view is open: shown straight away, or the other view stays
- Kind: contradiction
- From: footage-sorter-and-camera-cards-1 / When a card goes in, the Footage Sorter comes up on it
- Here: New footage appears on its own once it has finished arriving
- From says: "If that tab is already showing another card's view, that view stays, and \"Card <drive> detected\" with Go is shown instead."
- Here says: "A card that the app on the editor's computer opens the Sorter for is shown straight away in that page, in the card's own view."
- Settled by: part 1 holds the full rule and its exception; nothing in the owner's answers says otherwise
- Fix: this piece should add "unless that page is already showing another card's view" or replace its sentence with a pointer to part 1.

### F8: Time folders are on by default in one piece and off in the other
- Kind: contradiction
- From: footage-sorter-and-camera-cards-2 / Footage is filed in day-and-camera time folders
- Here: The Sorter's settings
- From says: "Setting: Time folders. Does: whether sorted clips are filed in per-day, per-camera time folders under their folder. Default: on."
- Here says: "Setting: Time folders. Does: whether each assigned folder gets one folder per day and camera (see Sorting into shoots, people and cameras). Default: off."
- Settled by: the owner must say: on a new site, are sorted clips filed in day-and-camera time folders until an admin turns that off, or not until an admin turns it on? (Decision 21.2 carries this studio's own value over either way.)
- Fix: one piece holds the setting with one default and the other points at it.

### F9: Calendar and camera-label settings are defined in both pieces, under two names and with different defaults
- Kind: contradiction
- From: footage-sorter-and-camera-cards-2 / The studio's calendar is connected, read-only...; Each clip's camera label is decided on its own
- Here: The Sorter's settings
- From says: "Setting: Calendar start date. ... Default: 1 April 2026." and "Setting: Camera labels. ... Default: A-CAM, B-CAM, BMCC, DRONE, AUDIO." and "Setting: Calendars the Sorter reads."
- Here says: "Setting: Calendar events from. ... Default: the day the part is switched on." and "Setting: Camera labels. ... Default: none until set; the studio's own labels are carried over." and "Setting: Calendars read."
- Settled by: decision 21.2 (answered 2026-11-24, recommendation A): "every setting is on the Sorter's settings, changed by an admin; card names by anyone signed in; one studio's values become that site's settings, carried over."
- Fix: part 2 should drop its three setting lines (or give this studio's values only as carried-over values) and point at this piece's settings, so each setting has one name and one default.

### F10: Destination folders sort naturally in one piece and by British English collation in the other
- Kind: contradiction
- From: footage-sorter-and-camera-cards-2 / The destination tree shows real, planned, suggested and held folders
- Here: Folder names sort in one fixed order that handles Chinese
- From says: "Folders sort naturally (numbers in order, case ignored)"
- Here says: "Folder names, groups and planned folders sort in British English order: spaces before punctuation, then symbols, digits, Latin letters, other scripts, and then Chinese characters by radical and stroke count. Accents count before letter case, and lower case comes before upper."
- Settled by: the owner must say: in the destination tree, does "Day 2" come before "Day 10" (numbers in numeric order), and are Chinese names ordered by radical and stroke? (SRT-126, situation, only requires existing "(2)" names to be kept.)
- Fix: one piece holds the order, saying how numbers within names sort, and the other points at it.

### F11: How often the destination tree is re-read from disk
- Kind: contradiction
- From: footage-sorter-and-camera-cards-2 / Footage is filed in day-and-camera time folders
- Here: The destination tree shows the final tree as it is, plus what is planned; The Sorter's work through the day and night
- From says: "What is on disk is read again at least every 30 seconds, and at once after a change to assignments, a move, a card copy, a scan or an audit."
- Here says: "It is re-read about every minute, and at once after a look through the folders, a move or a card copy."
- Settled by: the owner must say: how soon must a folder made on the NAS by hand appear in the destination tree: within 30 seconds or within about a minute?
- Fix: one piece states the interval and the full list of "at once" triggers (assignment change and audit included), and the other points at it.

### F12: Rescan is described in full twice, and the two differ on a second press and on long looks
- Kind: contradiction
- From: footage-sorter-and-camera-cards-2 / Rescan reads every source and destination again
- Here: A full look through every footage folder
- From says: "Rescan (ignored and disabled while one runs) shows \"Scanning… <n> clips\", updated about every second, until it ends (the page stops watching after one hour)."
- Here says: "Only one runs at a time: asking again while one runs says so and shows the count it has reached." and "the page stays usable and keeps loading however long the look takes."
- Settled by: the owner must say: if a look through every footage folder takes more than an hour, does the page keep showing its progress until it ends?
- Fix: part 2 should replace its Rescan description with a pointer to this piece's "A full look through every footage folder", keeping only its "Moved outside the app: <what>" line if this piece lacks it.

### F13: The nightly jobs run on the NAS's clock in one piece and on the site's time in the other
- Kind: differs
- From: footage-sorter-and-camera-cards-2 / The NAS's footage tree is walked every night and after each clean move; The record survives losing the NAS
- Here: The Sorter's work through the day and night
- From says: "walked every night at 04:30 on the NAS's clock" and "Every day at 04:00 on the NAS's clock"
- Here says: "backs up the record of every copy every night at 04:00; and walks the whole footage share on the NAS every night at 04:30 ... All times are the site's time."
- Settled by: the owner must say: are the studio's nightly jobs timed by the studio's own time zone setting, or by whatever clock the server keeps?
- Fix: both pieces should name the same clock (the site's time, if that is the answer) for 03:30, 04:00 and 04:30.

### F14: The list of what needs an admin leaves out deciding sound recordings and planning every episode's folders
- Kind: contradiction
- From: footage-sorter-and-camera-cards-2 / A person decides a recording's folder and start; The audio worklist says whose interview is on each recording; Planning every episode's folders and every interviewee's folder at once
- Here: What needs an admin and what needs only a sign-in
- From says: "Who: an admin decides." and "Who: anyone signed in sees it; approving needs an admin." and (planning) "Who: an admin."
- Here says: "Only an admin may change a drive's details, ... change the Sorter's settings; make, see and switch off folder links. Anyone signed in may assign clips, edit planned folders, put a moved clip back or move it elsewhere"
- Settled by: the owner must say: may any signed-in person approve where a sound recording is filed and fill the plan with every episode's and interviewee's folders, or only an admin?
- Fix: if part 2 is right, this piece's admin list should add deciding and bulk-approving sound recordings and the two planning actions; otherwise part 2 should change its three "Who" lines.

### F15: Where the drives list sits: on the sorting screen, or only in the Sorter's settings
- Kind: differs
- From: footage-sorter-and-camera-cards-2 / The drives list shows every drive that holds footage (and The activity panel shows every scan and copy running and waiting)
- Here: On a desk the sources, the clips and a panel sit side by side; Opening the page asks where to look and loads little
- From says: "Clicking a drive (or Enter or Space, or Show clips) shows the clips with a copy on it" and "Phone and desk: on a phone, choosing a drive goes straight to its clips."
- Here says: "Managing the studio's known drives is in the Sorter's settings, not on the sorting screen." and "Pick a source folder, a card or a drive on the left, and its clips appear here." (the sources area and the panel are listed without the drives list or the activity panel)
- Settled by: the owner must say: when a person wants to see the clips on one drive, do they pick the drive beside the sources on the sorting screen, or go to the Sorter's settings?
- Fix: this piece should name where the drives list and the activity panel sit on the page (and keep only tracking and editing drives in settings, if so), or part 2 should drop "shows the clips with a copy on it" from its drives list.

### F16: A person who drops files that are not found is told to add a source folder, which only an admin may do
- Kind: contradiction
- From: footage-sorter-and-camera-cards-2 / Files dragged in from the file manager are found in the library and join the plan
- Here: An admin adds or removes a source folder from the sources list
- From says: "Add the folder they live in with ＋ folder in the Source pane, then Rescan."
- Here says: "Who: an admin."
- Settled by: decision 21.1 (answered 2026-11-24, recommendation A): "an admin adds and removes them from the Sorter page (\"+ folder\")"
- Fix: part 2 should give that line to admins only and tell anyone else to ask an admin to add the folder.

### F17: The recording's detail still has "Open in Explorer" where this piece has "Show in the file manager"
- Kind: differs
- From: footage-sorter-and-camera-cards-2 / One recording's detail shows who it could be and plays it against the cameras
- Here: Showing a clip's file in the file manager on the person's own computer
- From says: "Assign to…, Unassign, Show in destinations, Open in Explorer."
- Here says: "Show in the file manager, from the clip's menu, its details and the audio worklist, opens the person's own file manager (Explorer on Windows, Finder on macOS)"
- Settled by: decision 21.3 (answered 2026-11-24, recommendation A): "it opens the person's own Explorer or Finder, through the app on their computer, where that computer can reach the footage; elsewhere (a phone, no app) it shows the clip's place with a Copy button."
- Fix: part 2 should call the button "Show in the file manager" and point at this piece's sub-topic.
