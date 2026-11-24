# Proxies and file moves

Editors cut with proxies: small, light copies of each camera original that travel to every computer in the team, so a clip with no proxy is invisible to everyone but the computer that holds its original. This part of CC Sync finds the clips that have no proxy, gets their proxies made in a form DaVinci Resolve accepts, shows editors and admins how far that has got, and keeps Resolve pointed at the right proxy. It also lets an admin move or rename footage once, on the server, and have every computer that holds a copy, and Resolve on each of them, follow, with nothing ever deleted. A move made by hand on the NAS is noticed, explained and followed the same way. Making proxies is always available, with a setting on each computer saying whether that computer takes part.

## Making proxies on editors' computers

### Clips with no proxy are found and their proxies are made

A proxy lives in a folder named "Proxy" beside its original, with the same file name apart from the file type. Computers that receive footage from the server receive proxies, not originals, so a clip with no proxy cannot be seen by anyone else in the team (see Sync: What syncs where).

On every editor's computer the app looks for originals in this computer's projects that have no proxy, tells the editor about them, and gets the missing proxies made. Making a proxy is heavy work of the kind the studio's computers share: which able and free computer makes a given proxy is decided as for all such work (see Work shared out across the computers: Choosing who runs what), and it is always a computer that can read the original. Everything in this section about how making behaves (waiting until nobody is at the keyboard, giving way to Resolve, keeping the drive from filling) holds on whichever computer makes it.

Telling and making are switched separately for each computer. A computer with both off neither looks nor makes, and says so in its proxy line ("switched off"), so nobody mistakes silence for "all covered".

- Who: an editor for their own computer, or an admin for any computer, sets the two switches.
- Setting: Make proxies on this computer. Does: lets this computer make proxies for clips that lack them. Default: on. Who: an editor for their own computer, or an admin. Applies to: a computer. Search words: make proxies, proxy making, encode, proxies on this computer.
- Setting: Tell me about clips with no proxy. Does: shows the editor a notification and a line naming clips on this computer that nobody else can see because they have no proxy. Default: on. Who: an editor for their own computer, or an admin. Applies to: a computer. Search words: missing proxies, proxy notice, no proxy, proxy warning.
- Pending: proxies-and-file-moves-U1

### Which files need a proxy and how soon a new one is noticed

Only video originals count: files ending .braw, .mov, .mp4, .mxf, .avi, .mts, .m2ts, .mkv, .r3d, .crm, .mpg, .mpeg, .wmv or .webm, in any letter case. Never counted: files whose names start with a dot (the hidden companion files macOS writes beside files on shared drives, and folder settings files); the working files of a YouTube download still in progress; 360-degree camera files; empty files; and camera metadata files that sit beside raw footage. Folders named "Proxy" or "proxies" in any letter case, the sync folder's holding place for removed files, and hidden folders are never looked in.

A clip counts as having a proxy when a QuickTime or MP4 file of the same name sits in the "Proxy" folder beside it. A clip whose proxy Blackmagic Proxy Generator is writing at that moment is counted neither as missing nor as waiting.

The app looks again when it starts, about every 15 minutes after that, at once when the editor asks for proxies to be made now, and at once when the sync folder's drive comes back after being away. It looks only while the sync folder is present, and only in the projects this computer syncs (when that list is known). A newly ticked or newly created project is counted within about a minute; until it has been counted, every view says "counting" for it, never 0.

- Setting: How often to look for clips with no proxy. Does: sets how soon a new original without a proxy is noticed. Default: every 15 minutes. Who: an editor for their own computer, or an admin. Applies to: a computer. Search words: proxy scan, look for missing proxies, how often, proxy check interval.

### Clips waiting for a proxy are made newest first, and failures never crowd out the rest

Clips waiting for a proxy form one list across all of this computer's projects, newest original first. At most 500 clips of one project wait in the list at once; the counts stay exact, and the editor is told: "There are more clips without proxies than CC Sync queues at once. It will pick up the rest as the queue drains." Clips that have been given up on take no place in the list, so clips that can still be made are always made first: a computer stands idle only when nothing it could make remains.

### A project that cannot be read shows its proxies as unknown

When a project folder cannot be read at all (for example its drive was unplugged), or reading it fails partway, the project is never reported as covered and never as "no proxies needed". It is shown as unknown, on the editor's computer and on the dashboard, with the sentence: "CC Sync could not read <folder> to check its proxies (<reason>). Until it can, nobody knows whether that project's clips have proxies." Whatever was already counted before the failure is kept. An incomplete answer about a project's clips is never acted on: nothing is made, attached or relinked from it.

### The editor is notified when clips on their computer have no proxy

When clips without a proxy are found, the editor gets a notification titled with the studio's brand, naming the project with the biggest gap:

- "N clips in <Project> have no proxy, so nobody else in the team can see them."
- one clip: "1 clip in <Project> has no proxy, so nobody else in the team can see it."
- when the computer has more missing clips than that project alone: "N clips in <Project> (M on this computer) have no proxy, so nobody else in the team can see them."

One sentence follows, the first that applies: if every missing clip is in a format only Resolve can read, "Run the Blackmagic Proxy Generator on them."; if proxy making is switched off for this computer, "Ask your admin to generate proxies for them."; if this computer cannot make proxies, that it can only tell, not make; otherwise "I'll make them while you're away from the keyboard."

The notification is shown at most once while the same gap lasts (a new gap starts when the old one closes or the drive comes back), and no more often than the minimum time between notices, which is remembered across restarts.

- Setting: Minimum time between proxy notices. Does: limits how often the missing-proxy and low-space notices appear. Default: one day (zero means no minimum). Who: an editor for their own computer, or an admin. Applies to: a computer. Search words: proxy notification, how often, notice interval, reminders.
- When the help for the editing program is off: the sentence about the generator reads that the clips are in a raw camera format CC Sync cannot make proxies from.

### Proxies are made only while nobody is at the computer

Making starts only after 5 minutes with no keyboard or mouse use. If the computer cannot tell how long it has been idle, someone is taken to be there. When the editor touches the keyboard or mouse, pauses syncing, presses stop, or the app is shutting down, the clip being made is abandoned within about 2 seconds, its unfinished file is removed, the clip goes back to the front of the list, and no further clip is started. The reason shown is one of "you're back at the keyboard", "syncing is paused", "you asked it to stop", "the app is shutting down".

Making runs below normal priority and with no window, so the computer stays usable and Resolve keeps its full speed for its own work, renders included.

- Setting: Wait this long without input before making proxies. Does: how long the keyboard and mouse must be untouched before proxies are made. Default: 5 minutes. Who: an editor for their own computer, or an admin. Applies to: a computer. Search words: idle, away from keyboard, wait before encoding, idle time.
- See Work shared out across the computers: When a computer counts as free and able.

### Proxy making keeps the drive from filling

Before writing a proxy, the free space on the drive that will hold it is checked against the larger of 20 GB and 5% of that drive. Below it, the clip is skipped (never counted as a failure) and the editor is told "only X GB free on the drive holding <folder> (CC Sync keeps Y GB clear so syncing and Resolve's cache do not run out)". A notification titled with the brand and "low disk space" says "CC Sync stopped making video proxies: <reason>. Free some space and they will resume on their own.", no more often than the minimum time between proxy notices. The editor's computer and the dashboard show "CC Sync stopped making proxies: <reason>. They start again on their own once there is room." This clears on its own with the next clip that has room. If free space cannot be read, making goes ahead.

- Setting: Keep this much space free when making proxies. Does: the floor below which no proxy is written, as the larger of a size and a share of the drive. Default: 20 GB and 5% (zero switches either part off). Who: an editor for their own computer, or an admin. Applies to: a computer. Search words: free space, disk full, low space, reserve.
- See Sync: Disk space.

### Proxy making gives way to Resolve

An idle computer makes several proxies at once, using the whole computer. Whenever DaVinci Resolve is open or rendering, it makes only one at a time, even when the editor asked for proxies now, so Resolve stays responsive; within about a minute of Resolve closing it widens again. A setting stops all making while Resolve runs, including when the editor asked for proxies now; with it on, if the app cannot tell whether Resolve is running, it takes Resolve to be running.

- Setting: Make no proxies while Resolve is open. Does: holds all proxy making back while Resolve runs. Default: off. Who: an editor for their own computer, or an admin. Applies to: a computer. Search words: Resolve open, pause proxies, hold back, editing program running.
- When the help for the editing program is off: making does not watch for Resolve and this setting is not shown.

### A clip that keeps failing is set aside so the others are made

After 3 failed attempts on the same unchanged file, the clip is given up on and the editor is told: "N clip(s) failed too many times and CC Sync has stopped trying them. It will try again if the file changes, or when you ask for the missing proxies to be made now." A file that changes (different size or time) starts a fresh count. Running out of disk space never counts as a failure. A run that ends with nothing made and some failed shows that failure plainly on that run, never a full queue standing still.

- Setting: Attempts before giving up on a clip. Does: how many times a clip's proxy is tried before it is set aside. Default: 3. Who: an editor for their own computer, or an admin. Applies to: a computer. Search words: retries, failed proxies, give up, attempts.
- Pending: proxies-and-file-moves-Q1

### An editor makes the missing proxies now, or stops them

"Make the missing proxies now" looks for missing proxies at once, retries every clip given up on, and starts making straight away without waiting for the editor to be away from the keyboard. It opens the progress window and says "Making the missing proxies now. It stops on its own when they're done." (or "Proxy generation is not set up on this computer."). It still respects a pause in syncing, a computer that is not set up right or cannot make proxies, and the Resolve rules above. It ends when its list is done.

"Stop making proxies" abandons the clips being made, leaving no unfinished files, and drops the current list; it says "Stopped making proxies." It stops only the work running at that moment: it is not a switch-off, and the next regular look finds the missing ones again.

- Who: an editor for their own computer.
- Ways in: from the app's menu on the editor's computer ("Make proxies now", "Stop making proxies"), from the app's window showing this computer's state ("MAKE PROXIES NOW (don't wait until I'm away)", "STOP MAKING PROXIES"), and from the progress window's button ("start now", or "cancel" while making).

### What proxy making on a computer is doing, in one line

One state is shown at a time, the first that applies, in this order:

1. switched off;
2. the sync drive is not connected ("waiting: the sync drive is not connected"; if the app cannot tell, the drive counts as there);
3. syncing is paused ("paused");
4. held back because other heavy work on this computer goes first, with the reason (for example "indexing b-roll first");
5. the computer is not set up right ("waiting: this computer's sync config needs fixing");
6. this computer cannot make proxies ("waiting: the tools needed to make proxies are not installed here"); it still says which clips have none;
7. nothing to do;
8. waiting because someone is at the keyboard ("waiting until you're away from the keyboard");
9. waiting because Resolve is open ("waiting: DaVinci Resolve is open", only with "Make no proxies while Resolve is open" on);
10. making proxies.

The state is worked out again right after each look for missing proxies, so "nothing to do" is never shown while clips are waiting. When the computer becomes able to make proxies, making starts without a restart.

On the editor's computer this shows as:

- "Proxies waiting: <reason>" when not making for a known reason;
- "Making proxies… N left (stops when you're back)" and "About <duration> to go at this rate" while making;
- otherwise "N clips have no proxy: other editors can't see them";
- "N BRAW clips need the Blackmagic Proxy Generator";
- "Made N proxies today · <source size> → <proxy size> · M failed".

Every reason making is held back (given up on, with the clips named; low space; more clips than are queued at once; cannot make proxies here; another kind of work first) is told to the editor at that computer in a sentence, not only to the admin.

- Ways in: on the editor's computer, in the app's window showing this computer's state, with "SHOW PROXY PROGRESS" while making and "PROXIES THIS COMPUTER HAS MADE…" when it can make proxies or has made any.
- See Work shared out across the computers: Choosing who runs what, for which work goes first.

### The progress window for proxies being made

The window "MAKING PROXIES" says "Proxies let the rest of the team see this footage. Closing this window does not stop them." It shows:

- the clip being made (its name only), its length, its percent done, its time left and time taken, updated about once a second;
- done out of total, failed, and time left for the whole list;
- how many clips have no proxy, how many are Blackmagic RAW, how many need Resolve, how many are left to make;
- how many were made and failed since the app started;
- when it is not making one, why it is waiting (the reasons in the line above);
- the reasons making is held back, with their sentences.

The number of missing clips drops the moment each proxy is finished. From the last 60 clips finished (at least 3 are needed), it shows clips made per hour and an estimate of how long the rest will take; this rate starts afresh when the app restarts. Its button reads "cancel" while making one and "start now" otherwise; it shows that it is finished when none are left.

- Name and search words: Making proxies. Search words: proxy progress, encoding, time left, making proxies.

### The history of proxies a computer has made

Each finished or failed proxy is added at once to this computer's proxy history, with the size of the original and the proxy, the clip's length and how long making took. Skipped and interrupted clips are not recorded. The history survives restarts.

On request the editor gets a plain-text report, "CC Sync: proxies made on this machine", with "Since: <first> (last: <last>)":

- a "TODAY" block and an "ALL TIME" block, each with "N proxies made, M failed", "<size> of footage → <size> of proxies (N× smaller)" and "<duration> of footage covered, <duration> spent encoding";
- "Recent rate: N clips/hour";
- BY DAY for the 14 most recent days (made, failed, sizes, ratio);
- the last 60 clips, newest first, each "ok" or "FAIL" with time, name, project, sizes, how it was made, time taken, or the error (at most 300 characters).

With nothing made yet it says "Nothing has been encoded on this machine yet."; if the history cannot be read, "The proxy history could not be read."; if the report cannot be written, "The proxy history could not be written." Sizes are shown in B, KB, MB, GB, TB (1024-based); durations like "45s", "18m", "2h 40m", "3d 4h". Daily totals are kept for the last 90 days; totals for all time are kept indefinitely. The current day's and all-time totals, the rate and the estimate are also shown on the editor's computer and on the dashboard.

- Ways in: from the app's menu ("Proxy history"), and from the app's window showing this computer's state ("PROXIES THIS COMPUTER HAS MADE…").
- Name and search words: Proxies this computer has made. Search words: proxy history, proxies made, encoding report, proxies per day.

### The dashboard shows each computer's proxy coverage

For each computer, the dashboard's per-computer view shows: the proxy-making state and whether making is on; how many clips have no proxy, split into Blackmagic RAW, needing Resolve, camera footage and downloaded footage; how many are waiting and how many are left; how many were made and failed; whether the computer can make proxies and whether it has fast hardware video encoding; when it last looked; any low-space reason; per project, the clips missing a proxy (only projects with a gap, and "counting" for a project not yet counted, "unknown" for one that could not be read); the history totals; and every reason making is held back. Originals lacking a proxy are counted per project, so a project page can say how many of its clips nobody else can see. When a computer has not sent fresh figures, the last known values stay, with their age.

- See The dashboard: Each computer's state.

### A computer making proxies stays awake and says why it should not shut down

While any proxy is being made the computer is kept from sleeping. On Windows a shutdown is met with the reason "still making video proxies so the rest of the team can see this footage (N clip(s) left, M at once)". Once making stops the computer may sleep again. When the app quits, proxy making is stopped first, leaving no unfinished file.

- Windows and macOS: only Windows shows a reason at shutdown.
- See The app on each editor's computer: Starting, staying running and crashing.

### A computer is equipped to make proxies with nothing for the editor to install

Without any step by the editor and without any error window, the app equips the computer to make proxies (and to do the b-roll and downloaded-footage work that needs the same ability). This is a one-off download of about 300 MB, and it needs that much free on the computer's drive; it never holds up the app starting. If the editor already has their own copy of what is needed, that is used instead. Supported: Windows on Intel or AMD processors, and Macs with Apple or Intel processors. On anything else (Windows on ARM, Linux) the computer cannot make proxies or index b-roll, and its proxy line says so. When equipping fails, the computer shows "waiting: the tools needed to make proxies are not installed here" with the reason, on the editor's computer and on the dashboard, and is not offered proxy, sound-extraction or waveform work until equipping succeeds. It becomes able without a restart as soon as equipping succeeds. A warning appears when making proxies is on but the computer cannot make them.

- Windows and macOS: Windows on Intel or AMD and every Mac are supported; Windows on ARM is not.

### An editor can rehearse proxy making and FIX ALL without changing anything

Two rehearsal settings, both off: one makes the computer report which files it would make proxies for and make none; the other makes FIX ALL report the copies and relinks it would make and do nothing. They are read when the app starts.

- Setting: Rehearse proxy making. Does: reports what would be made, makes nothing. Default: off. Who: an admin. Applies to: a computer. Search words: dry run, rehearse, proxy test, what would be made.
- Setting: Rehearse FIX ALL. Does: reports the copies and relinks FIX ALL would make, changes nothing. Default: off. Who: an admin. Applies to: a computer. Search words: dry run, fix all rehearsal, preview fixes, test relink.
- Pending: proxies-and-file-moves-Q2
- See Resolve on the editor's computer: Fixing media: copying in, rehearsals and undo.

### Picking originals shows a picture of each file and plays its proxy

Wherever a person picks original files (for example to bring originals down to their computer), each file has a thumbnail and plays its proxy when clicked. A Blackmagic RAW file without a proxy says "no proxy yet".

- See Sync: What syncs where.

### A proxy made on an editor's computer is never removed by syncing

A proxy an editor's computer made itself is sent to the server like any proxy and is never put in the holding place for removed files, or removed as a stray, by downloading proxies or by tidying the sync folder.

- See Sync: Deletions and removing a project.

#### Lessons

- Met: PRX-030, PRX-031, PRX-033, PRX-040, APP-147, PRX-032, PRX-034, PRX-035, PRX-036, PRX-037, PRX-038, PRX-039, PRX-041.

## What Resolve accepts as a proxy

### Resolve finds a proxy by its folder and its exact name

DaVinci Resolve attaches a proxy on its own when the proxy sits in a folder named "Proxy" beside its original under the same name apart from the file type. So every proxy is placed there, and editors are told to set Resolve's Proxy Handling to "Prefer Proxies". A proxy one character off in its name never attaches: every file reaches every other computer under a byte-identical name, Chinese characters and fullwidth punctuation included, in both directions.

- See Resolve on the editor's computer: Proxies in Resolve.

### A proxy's timecode matches its original's in the form Resolve reads

Resolve refuses to attach a proxy whose start timecode differs from its original's. Every proxy carries its original's start timecode, or none when the original has none, and names the same frame in the same form Resolve reads from the original.

Some cameras (Sony among them) record a non-drop-frame style start timecode at 29.97 or 59.94 frames per second without a separate timecode track. Resolve refuses a proxy for such a clip unless the proxy's timecode is in drop-frame form, so it is written that way. A timecode from a proper timecode track, one already in drop-frame form, or any other frame rate is kept as it is. The timecode written is checked, both its value and its form, and a link counts as done only when Resolve accepts it.

### A proxy has exactly its original's frame count

Resolve refuses a proxy even one or two frames shorter than its original. For constant-frame-rate footage every proxy, from whatever made it, has exactly the original's number of picture frames, or it is refused and made again. Footage from phones has a variable frame rate and no exact frame count to match: there a proxy is accepted when its running time is at least 97% of the original's, and such footage never fails as a whole over it. A clip's length is found by counting its picture frames, never from the figures stated in the file's header (which can differ from the real frames), and is read at most once for each version of the file.

A proxy whose frame count differs from its original's is named to the editor and on the dashboard as a proxy fault, not as syncing being stuck, and is made again.

### A proxy carries every sound track and opens in Resolve

A proxy carries every audio track of its original, in the same order. A proxy holding high-efficiency (HEVC) video is tagged "hvc1", without which Resolve shows it as Media Offline though it plays everywhere else; this is checked by Resolve opening it.

### A proxy Resolve refuses is named once with its likely cause

When Resolve refuses to attach a proxy, that refusal is remembered for that version of the proxy file and shown once, not offered again and again. A failure because Resolve was closed or did not answer is not a refusal: it is tried again later. The editor sees how many proxies Resolve refused, the first such clip, and the likely cause in plain words (usually that the proxy's timecode does not match the original).

- Pending: proxies-and-file-moves-Q1
- When the help for the editing program is off: nothing is attached in Resolve and nothing about refusals is shown.

#### Lessons

- Met: PRX-001, PRX-002, PRX-003, PRX-004, PRX-005, PRX-006, PRX-007, PRX-008, PRX-009, PRX-010, PRX-011, PRX-012, PRX-013.

## What a proxy must be

### A proxy of camera footage

A proxy made for camera footage is:

- a QuickTime (.mov) file, which Resolve and Blackmagic Proxy Generator recognise as an existing proxy (previews played in a browser stay MP4);
- 10-bit high-efficiency (HEVC) video, tagged so QuickTime and Resolve accept it;
- at most 1080 pixels tall, never enlarged, width in proportion, rounded to even width and height (so a screen recording of odd size still gets one);
- small enough to travel over the internet: on average no more than about 2.5 megabits a second, and never larger than its original;
- carrying every audio track of the original (a silent original still gets a proxy), the original's descriptive information, and the original's start timecode;
- laid out so it starts playing before it has fully loaded;
- placed where Resolve links it: in the "Proxy" folder beside the original, under the original's name.

- Setting: Proxy size and rate. Does: the largest height and the average rate of proxies this computer makes, never above 1080 pixels and about 2.5 megabits a second. Default: 1080 pixels, about 2.5 megabits a second. Who: an admin. Applies to: a computer. Search words: proxy quality, proxy resolution, bitrate, proxy size.

### A lighter proxy for downloaded and reference footage

A clip is downloaded or reference footage when any folder or file name on its path contains "youtube", "yt" or "downloads" as a separate word (words split on anything that is not a letter or digit, so "Kyoto" does not count but "YouTube Downloads" and "yt-clips" do). Everything else, and every camera format (Blackmagic RAW, MXF, RED, Canon RAW, AVCHD), is camera footage; a doubtful path counts as camera footage. A proxy of downloaded footage is 8-bit H.264 video at most 1080 pixels tall, never enlarged, with a keyframe every second, audio at a modest quality, and a timecode only where the original has one (YouTube downloads have none).

### A new proxy counts only once it plays cleanly and is the right length

Every new proxy, from whatever made it, is played through in full before it is used. Any playback error fails it ("the proxy does not decode cleanly (N error line(s))"), and so does a length that does not match its original as set out above ("the proxy is X s of a Y s source", saying that making stopped early). A failed proxy is made again.

An original that cannot be read to its end (for example a truncated download, or a camera original cut short on the NAS) fails before making starts, and is reported as damaged with its path, not tried again and again.

Every time limit on making or checking a proxy grows with the clip's length: making one clip is given up after the larger of 30 minutes and 60 times the clip's length ("the encode was still running after N minutes"), and finished work is never thrown away for a time limit alone. A failure message quotes the last few lines of what went wrong, at most 500 characters.

### A proxy with a look burned in is never used as an editing proxy

A proxy with a colour look (a LUT) burned into its picture is useless for editing. It is never attached as an editing proxy; it is set aside, not deleted, and the clip counts as having no proxy.

#### Lessons

- Met: PRX-014, PRX-015, PRX-016, PRX-017, PRX-018, PRX-019, PRX-020.

## Raw camera formats and Blackmagic Proxy Generator

### Raw camera clips get their proxies from Blackmagic Proxy Generator

Blackmagic RAW, RED and Canon RAW clips can be read only by DaVinci Resolve and its Blackmagic Proxy Generator. Such clips are counted as missing a proxy and as "needs Resolve" (Blackmagic RAW also on its own), are never failed as broken, and are handed to Blackmagic Proxy Generator, which comes with Resolve and is Resolve itself started in a special mode. Every clip CC Sync can read itself gets its proxy from CC Sync; only formats it cannot read go to the generator. A proxy the generator makes is checked like any other proxy.

The generator takes no list of files: it watches folders listed in its own settings and makes a proxy for every clip there that has none. Its window opens idle, with a Start button.

- Setting: Hand raw clips to Blackmagic Proxy Generator. Does: lets this computer open the generator for raw clips that have no proxy. Default: on wherever this computer makes proxies and the generator is found. Who: an editor for their own computer, or an admin. Applies to: a computer. Search words: BRAW proxies, raw proxies, Blackmagic Proxy Generator, BPG.
- When the help for the editing program is off: raw clips are still counted as having no proxy, the generator is never opened, and the editor is told the clips are in a raw camera format CC Sync cannot make proxies from.

### When the generator is opened for raw clips

The app opens the generator when all of these hold, checked in this order; the first that fails is the reason shown:

1. handing raw clips to the generator is on ("disabled");
2. the generator is installed ("no proxy generator installed");
3. at least one raw clip needs it ("nothing needs BPG");
4. every other clip's proxy is made and nothing else is being made, so two proxy jobs never compete for one graphics card ("still has clips queued");
5. the editor is away from the keyboard ("user is at the keyboard");
6. no generator is already running on the computer ("already running", in which case it presses Start if it is idle);
7. at least 30 minutes since the last attempt to open it, whether that worked or not ("launched too recently");
8. the folders could be added to its watch list ("watch folders could not be set").

It is never opened while syncing is paused, the drive is absent, the computer is not set up right, other heavy work goes first, or CC Sync is making proxies itself. It may run beside an open Resolve, it keeps running after the app quits, and the app never stops or closes it mid-run. Work counts as handed over only once the generator is running, and the generator never makes a second proxy for a clip that already has one.

### Raw clips' folders are added to the generator's watch list without disturbing it

Only while the generator is closed, the app adds the folders holding raw clips that lack proxies to its watch list. Entries already there are kept as they are and are never removed; a folder already covered by an entry or by one of its parent folders is not added again (compared ignoring letter case and slash direction). A folder whose name has Chinese or accented characters shows correctly in the generator and is watched; an entry spelt wrongly in an earlier attempt is replaced when it matches a folder being added. The list is never taken above 32 entries; when it is full the generator is not opened and the editor is told that its watch list is full. Before the first change, the generator's original settings are saved once and never overwritten. On a computer where the generator has never been opened, and so has no settings yet, they are created, so it can be set up and started all the same.

- Setting: Add raw clip folders to the generator's watch list. Does: lets the app add folders to the generator's list. Default: on. Who: an editor for their own computer, or an admin. Applies to: a computer. Search words: watch folders, BPG folders, proxy generator list, raw folders.

### The generator is started without the editor's help

After opening the generator, the app waits up to 3 minutes for its window and presses Start, only if the button reads Start, then checks that it now reads Stop. It tries at most once every 5 minutes. If the window or button cannot be found, or pressing changed nothing, the editor is told on their computer: "CC Sync opened the Blackmagic Proxy Generator to make proxies, but could not press Start. Press Start in its window." The note clears once Start is pressed or the generator is running.

- Setting: Press Start in the generator. Does: lets the app start the generator's work for the editor. Default: on. Who: an editor for their own computer, or an admin. Applies to: a computer. Search words: press start, start BPG, proxy generator start, automatic start.
- Windows and macOS: the same on both; on either, a generator not found where Resolve installs it stays unused until its location is given.
- Pending: proxies-and-file-moves-Q3

### Where the generator is found and what the editor sees of it

The generator is looked for where Resolve installs it; its location can also be given. A location given where nothing is counts as not installed. The editor sees whether handing raw clips to the generator is on, whether the generator is installed, whether Start is pressed for them, whether a generator the app opened is still running, how many clips it was opened for, and the note about pressing Start.

- Setting: Where Blackmagic Proxy Generator is. Does: tells the app where to find the generator when it is not where Resolve installs it. Default: where Resolve installs it. Who: an editor for their own computer, or an admin. Applies to: a computer. Search words: generator location, BPG path, proxy generator, find generator.
- Windows and macOS: the same on both; on either, a generator not found where Resolve installs it stays unused until its location is given.
- Pending: proxies-and-file-moves-Q3

### When raw proxies cannot be made the editor is told which file and why

When the generator stalls on a file or fails others, the editor is told which file failed and why, instead of a progress line that never moves.

#### Lessons

- Met: PRX-021, PRX-022, PRX-023, PRX-024, PRX-025, PRX-026, PRX-027, PRX-028, PRX-029.

## Pairing proxies with their originals

### Two originals with one name in one folder

When two originals in one folder have the same name but different file types (for example a QuickTime and an MP4 of the same clip name), they would need the same proxy file. They never share one and neither overwrites the other's: only the newer is made into a proxy, the older keeps counting as missing (it is never taken as covered by the newer's proxy), and the editor is told that the two clips share one name, so only one of them can have a proxy until one is renamed. Two such clips are never made at the same time.

### Every proxy on the server has its original beside it

The server checks that every file in a "Proxy" folder has an original of the same name (apart from the file type) in the folder above. Proxies that cameras make themselves are also matched with their known endings removed (Sony's ending "S03", in any letter case, and others as cameras are added). Files whose names start with a dot and camera metadata files are ignored, so footage that moved is seen as moved even when its metadata file stayed. A proxy matching neither reading is reported. Proxies left behind after their originals moved are reported once per proxy folder, naming up to 5 clips and counting the rest, with the originals' new place when it can be found. Originals without proxies are never flagged here.

- See The dashboard: Problems the server finds.

#### Lessons

- Met: PRX-042, PRX-043, PRX-044, PRX-045, PRX-046.

## Writing, copying and deleting files safely

### A clip is checked again just before its proxy is made

Just before each proxy is made, the clip is skipped, silently and without counting as a failure, if:

- it is itself a proxy (inside a folder named "Proxy" or "proxies" at any depth) or an unfinished file;
- it no longer exists, or is empty;
- it changed within the last 2 minutes, or its size or time changed between two looks about 5 seconds apart, meaning it is still arriving;
- it already has a proxy (for example one that has just arrived from the server);
- Blackmagic Proxy Generator is writing its proxy;
- it has been given up on.

- Setting: Leave new files alone for this long. Does: how long a file must be unchanged before a proxy is made from it. Default: 2 minutes. Who: an editor for their own computer, or an admin. Applies to: a computer. Search words: still copying, settle time, new files, wait before proxy.

### A proxy appears under its real name only when it is finished

While being made, a proxy has an unfinished name in the "Proxy" folder (created if missing), and a file under an unfinished, temporary or lock name never travels to any other computer by any route. When it is finished, if a proxy for that clip appeared meanwhile under any accepted name (for example downloaded from the server), the new one is thrown away and the clip counts as done. Otherwise it takes its real name. If that is refused (for example Resolve holds the file open), it counts as a failure and the finished file stays under its unfinished name: "could not put the finished proxy in place (...): it is still there as <name>". More generally, a file whose size or time is still changing never travels; it travels once it has been still for a set time (see Sync: Files that must never sync).

### Leftovers of an interrupted proxy or copy are cleared at the next start

A copy, or a proxy, appears under its final name only when it is complete. When the app starts it looks through the tree once:

- an unfinished proxy left by an interruption is removed (it is CC Sync's own unfinished work, never footage) and its clip is made again on a later run;
- an empty placeholder an interrupted copy left is removed quietly;
- a half-copied file from an interrupted copy-in is moved out of the tree into the holding place for removed files, never deleted, and the editor is told: "Found <N half-copied files> from an interrupted copy. Nothing was deleted. <how to get help>."

None of these ever travels to another computer.

### Files Resolve holds open wait for Resolve to close

Resolve keeps media and proxy files locked while a project is open. A move, rename or delete blocked by that says "waiting for Resolve to close", finishes on its own once Resolve has let go, and is never counted twice.

- When the help for the editing program is off: the wait reads "waiting for the file to be let go".

### Deletes and moves on the NAS are checked and done in place

After deleting or replacing a file on the NAS share, the folder is listed again, and a file still present counts as a failed delete. Moving a file within the NAS is always a rename in place, never a copy followed by a delete; when a rename is impossible the move fails and says so.

### During a long copy the editor can skip, cancel or stop after the current file

While CC Sync copies files for the editor (bringing media into a project, gathering or backing up), the editor can skip the current file, cancel the whole copy, or stop once the current file is done. A file whose copy was abandoned leaves nothing behind.

### Anything set aside is kept as long as promised

Anything CC Sync sets aside instead of deleting is kept at least as long as people are told it will be, and is never removed while the NAS does not hold the same file (see Sync: Deletions and removing a project).

#### Lessons

- Met: PRX-047, PRX-048, PRX-049, PRX-050, PRX-051, PRX-053, PRX-054, PRX-055.

## Moving footage through the product

### An admin moves a file or folder on the server and every computer follows

An admin names something inside a project and where it goes: the same project or another, a folder (it moves into it, keeping its name) or a full new path, or nothing for the destination project's top. A change of letter case alone is a valid move. The move is made on the NAS, on every computer that holds a copy, and in Resolve on each of them. Nothing is ever deleted by a move and nothing is ever overwritten.

The form asks for: what to move (a file or folder in this project, for example "B-roll/A001_0512.braw"), to which project (any active project, this one chosen to begin with), into which folder (blank for the project's top), and has the button "Move on the server and on every computer". With nothing typed: "type the file or folder to move, e.g. B-roll/A001_0512.braw". Before anything moves it asks: "Move '<path>' from <project> to <dest>[/<folder>] on the server, and tell N computer(s) to move their copy and relink Resolve? Proxies move with it. You can put it back with Undo while every computer has either applied it or is still waiting for it."

Refusals, each with its reason:

- no slashes inside a name, no names starting with "." and no "..", no control characters;
- nothing naming a proxy folder: "must not name a Proxy folder: proxies move with their originals";
- never the project's own identity mark;
- nothing leading outside the projects tree: "path escapes the Projects tree";
- the server cannot reach its projects folder: "the server's Projects folder is not available. Ask whoever installed this server to create or link the folder: it is a server-side step";
- an unknown or inactive project at either end;
- "nothing at <project>/<path> on the server";
- "<project>/<path> already exists: nothing was moved";
- "a folder cannot be moved into itself";
- "that is where it already is";
- when the NAS refuses: "the server could not move it: <error>", which is also recorded in the history.

When it is done: "moved", "<from> is now <to> on the server (N proxy file(s) with it); N computer(s) told to follow." When the original moved but some proxies could not: "moved, some proxies stayed", "<from> is now <to> on the server, but these proxy files did not move: <list>. Move them by hand or run the move again once whatever is holding them has let go." The admin is told what moved where, how many proxies moved and failed, and which computers must follow. A file moved by hand on the NAS instead would come back at its old path from every computer still holding it there, which is why moves go through here.

- Who: an admin ("only an admin can move files on the server").
- Ways in: from the project's own page, and from the Footage Sorter when it moves a clip inside a project.
- Name and search words: Move on the server and on every computer. Search words: move file, rename file, move folder, relocate footage, rename clip.
- When the help for the editing program is off: the question and the messages say nothing about relinking.

### A clip's proxies move and are renamed with it

Every proxy beside a moved file whose name matches (ignoring letter case and accent spelling, any file type) goes to the "Proxy" folder beside the new place, and when the move also renames the file, the proxies take the new name, so Resolve shows both the original and its proxy online afterwards. In a folder move the proxies travel inside the folder. A proxy is never overwritten: if a different file is already where it would go, the proxy stays. A proxy that cannot follow (something already there, held open, unreadable) stays at the old place and is named.

A clip counts as fully moved only when all its files have moved. Until then the move shows as "moved, some proxies stayed", and the proxies left behind are remembered and carried to the clip's new place by the next move made for that clip, or by running the same move again.

### A move made in the Footage Sorter inside a project reaches every editor's copy

When the Footage Sorter moves a clip that is inside a project, the move is made exactly as "Move on the server and on every computer", so every editor's computer follows it. The clip and its destination must each be inside an active CC Sync project; otherwise the move fails with "<path> is in no CC Sync project, so no editor's copy can follow it". A refusal is shown in the Sorter as its error. Moves into a project from outside every project (for example from a transfer folder) are plain moves on the server.

- See The Footage Sorter and camera cards: Moving footage on the NAS.

#### Lessons

- Met: PRX-056, PRX-057, PRX-058, PRX-059, PRX-060, PRX-061, PRX-062.

## Moves that reach every computer

### Every computer that holds the moved item is told

A move reaches:

- every computer that syncs the source project (ticked to sync in full or to upload only);
- every computer that borrows a folder of the source project when the moved path is in, is, or contains that folder;
- every computer known to hold the moved path or something under it;
- while the source project is active, every computer that keeps what it holds to itself, since what it holds cannot be checked.

A computer that works straight from the NAS is never told to move its copy again, unless it holds a separate copy of its own. Ticks made for a person rather than a computer are never told. Each computer files its copy only where its own plan says (below). Paths are compared exactly, letter by letter, with accents folded: underscores, percent signs and every other character match only themselves, so a folder with a look-alike name is never moved by mistake.

- See Sync: Wired or remote, and Sync: A plan belongs to a computer.

### A move is offered to computers only once the NAS has really moved it

A move is recorded before anything changes on the NAS and is offered to no computer until the NAS has moved it. If the server stops partway, then when it starts again, and every few minutes while it runs, it settles every unfinished move on its own:

- only the new place exists: the move is completed ("completed after an interrupted move") and the computers are told;
- only the old place exists: nothing moved, and the record is dropped;
- both or neither exist: it stays unfinished, is offered to nobody, and is shown on the project's page as a problem, with what, from where to where, whether both exist, and the two projects: "This move was interrupted part-way through on the server. Nothing has been sent to any computer. Check both paths on the server; the dashboard re-checks them every cycle and finishes it by itself once only one of them exists."

Nothing is ever left in two places or lost.

### A computer that could not follow tries again for a week

A move a computer could not apply is tried again after 10 minutes and then every hour, until it succeeds, or 20 attempts or 7 days have passed, whichever comes first. Until then it is shown as "still trying here (N attempts)"; after that as "blocked here after N attempts".

### The moved file never uploads again from its old place

For 24 hours after a computer hears of a move, whether it applied it or not, that computer uploads nothing from the old place; while the move is still being tried, blocked, or partway done on that computer, for as long as it stays so. This holds for accented names spelt the macOS way too. So a computer still holding the file at the old place never sends it back to the server.

### A move waits for each computer however long it is away

A move waits for each computer however long the computer is offline or its sync drive is away; a computer whose drive is away shows "waiting for the sync drive", and its move never runs out. Only silence counts against it: a computer that has been told about a move and gives no answer at all for 7 days, by the server's clock, is shown as "not applied: this computer may upload the old path again". A computer never yet told never runs out.

An admin can ask that computer again ("Ask that computer again"), which starts its 7 days afresh; this is refused with "that computer has already answered this move" when it has, and with "no such move in this project" when the move is unknown. Asking again is recorded in the history.

- Who: an admin.

### A move reaches the computer it was meant for, also after a rename

A move for a computer follows that computer when it is renamed, both the telling and the answer, and is deleted with a computer the admin forgets. It is never followed by a different computer, such as a twin cloned from the same disk that is still running under the old name.

### An admin puts a move back

"Undo this move" is offered while the move is done or partly done, no computer has failed it or given up on it, and it has not already been put back. It asks: "Move <to> back to <from> on the server, and tell every computer that holds it to move its copy back and relink Resolve? Proxies go back with it." The undo is a move in the other direction that restores the exact original path and name, and it reaches every computer the first move reached as well as the usual ones. Before putting back a folder move the server takes a snapshot of the NAS if it can, and goes ahead if it cannot.

Refusals: "no move <id> on this project"; "that move has already been put back"; "one of the computers could not apply this move, so its copy is still at the old path. Sort that computer out first, then put it back."; and any refusal a move would get (for example, something has since been created at the old place). The original move is then shown as "put back".

- Who: an admin.
- See The server: installing it and keeping it running: Snapshots, restoring and the server's disk.

### Each project's moves and how every computer followed

A project's page lists its moves into and out of it, newest first (the 20 most recent), headed "N move(s)". Each move shows one state: "unfinished on the server", "put back", "N blocked", "N failed", "N not applied", "waiting for N", or "done", plus "some proxies stayed"; from and to; "by <who> <ago>" (a person, or "detected on the server" for a move made by hand on the NAS); ", putting move N back" for an undo; and "Undo this move" while it can be undone. It counts the computers waiting, failed, run out, given up and awaiting a Resolve relink.

Under each move, one line per computer, with its detail and how many days it has waited:

- "not applied, this computer may upload the old path again";
- "still trying here (N attempts)", with the last error;
- "told, not done yet";
- "waiting: not in touch since <ago>";
- "blocked here after N attempts";
- "put in the trash on this computer: it does not sync the destination project";
- "moved", or "moved, Resolve not repointed yet";
- "failed".

A success marked "Resolve not repointed yet" becomes "moved" when the relink is done; a failure is never rewritten.

A "moves awaiting computers" list shows each computer that has not applied a finished move: person, computer, path, "asked <ago>", "waiting" or "waiting N days" (2 days or more), ", this computer is still trying (N attempts)", the last error, and "Ask that computer again" where it applies. A studio-wide list shows every computer still owing a move of any project, oldest first, the 50 oldest, with days waiting.

- Who: an admin.
- Name and search words: File moves. Search words: moves, moved files, undo move, move history, computers following.

### Admins are told when a computer never confirmed a move

A warning, "a file move was never confirmed", has one entry per computer and old path whose move ran out unconfirmed (the first 40), titled "<computer> <old path>", with the fix: run "Move on the server and on every computer" again, or ask that computer again, once it is online. Moves owed by computers the server no longer has are grouped as one entry, "computers this server no longer has".

- See The dashboard: Problems the server finds, and The dashboard: Alerts by mail.

### Every move is recorded

Every move through CC Sync is recorded: the source project and its folder as it was then, the source path, the destination project and folder as it was then, the destination path, whether it was a folder, how many proxies moved with it, who asked (an admin, or "detected" for a hand move on the NAS) and when, the move's state with a detail, the move it put back, and the move that put it back. Every move also goes into the audit history with from, to, folder or not, who asked and how many computers were told. Requests for original files of the moved item follow it to the new place as soon as the move is done or partly done.

#### Lessons

- Met: PRX-063, PRX-064, PRX-065, PRX-066, PRX-067, PRX-068, PRX-069.

## Following a move on an editor's computer

### Each editor's computer moves its own copy and the editor is told

Each computer that holds a copy moves it the same way, with its proxies, and points every Resolve clip that used the old place at the new one. Each move is carried out once. Nothing in this ever deletes and nothing is ever overwritten. Clips are repointed only once the new file is on this computer; if no open project used it, they are repointed the next time a project is opened (see Relinking Resolve after a move). A move into a project this computer does not sync is handled as set out below.

The computer's answer, shown to the admin for that computer, is one sentence. Answers that count as done: "nothing at the old path on this computer"; "already where the server has it"; "moved", with ", N proxy file(s) with it" and "; N proxy file(s) were in use and stayed at the old path" as they apply. A failure answers "could not move it on this computer: <error>", and is tried again as set out under Moves that reach every computer.

The editor is told, with the name of the admin who asked, or "your administrator":

- title "… file moved": "<admin> moved '<name>' to <where> on the server. Your copy followed and Resolve was relinked.", or "… Your copy followed. The clip will reconnect the next time you open that project in Resolve.";
- on the first failure, title "… file move needs attention": "<admin> moved '<name>' to <where> on the server, but your copy could not follow yet: <detail>. Nothing was deleted and CC Sync will keep trying.";
- after a week, title "… file move blocked": "Your copy of '<name>' still could not be moved to <where> after a week of trying: <detail>. Nothing was deleted; ask your admin."

A computer has followed a move only when its copy and its proxies have moved and every Resolve clip under it points at the new place; until then it shows as "moved, Resolve not repointed yet".

- When the help for the editing program is off: the messages say only "Your copy followed."

### A move already carried out is recognised and not done twice

A move interrupted at any point on a computer (by a crash, a restart or an update) finishes on the next attempt, is never reported done early, and nothing ever recreates the old place. If the file is already at the new place because this computer was interrupted partway, the answer is "finished a move this computer was interrupted during". If downloading proxies already carried this exact file to the new place within the last day, the answer is "proxy download had already moved it on this computer"; for a folder, "proxy download had already moved this folder on this computer" (also when only an empty old folder is left). Either way Resolve is then pointed at the new place. A move told again after a restart is not applied twice.

### Moves a computer refuses

A computer refuses, and the admin sees why:

- something already exists at the new place: "the destination already exists on this computer (<path>)";
- a folder would move into itself: "a folder cannot be moved into itself";
- a folder's new name differs only in letter case or accents: "a folder cannot be renamed by spelling alone on this computer; ask your admin to do it in two steps".

A move naming an unsafe place (a full path, a drive letter, a step up out of the folder, a blank or a control character) is never carried out, and the admin is shown, for that computer, that it was refused because it named an unsafe place.

### A file moved to a place this computer does not sync is set aside, never deleted

A file moved into any folder this computer syncs, including folders of a project it syncs only in part and folders it borrows, is moved there on this computer. When the new place is outside everything this computer syncs, its copy is moved to the sync folder's dated holding place for removed files, where it can be recovered, and Resolve is not changed. When this computer's list of what it syncs is empty, cannot be read or is not known, or the move stays inside one project, that counts as "cannot tell": the copy follows the move and is never set aside.

No local file is set aside until the server is seen holding the same file, at the same place and size:

- for a file (with its proxies), the answer is "trashed locally, destination not synced here"; on failure, "could not move it out of the way on this computer: <error>";
- for a folder, each file is set aside only if the server is known to hold it at the new place (same name ignoring case and accents, same size); anything else stays at the old place and is uploaded later; emptied folders are removed one by one. Answers: "trashed locally, destination not synced here", or "destination not synced here; kept N file(s) at the old path that the server may not have (e.g. <name>), trashed M";
- if the server cannot be asked and the folder holds originals: "destination not synced here, and the server could not be asked which of these files it already holds; keeping the folder where it is and trying again". A folder with no originals is set aside whole in that case.

"Not synced here" is final, counts as success, is recorded in the history, and the move is not sent to that computer again.

- See Sync: Deletions and removing a project.

### A project folder moved on the server is followed before anything syncs

When a project's folder has moved on the server, each editor's computer moves its own copy of the project folder to match before that project syncs anything. Any upload reading from the old folder is ended first ("its folder is being moved to where the server now keeps it"), and the project is relinked in Resolve. If the move cannot be carried out on this computer, the project does not sync at all, nothing is created at the new place meanwhile, and the project shows as blocked with the reason: "Could not move this project's folder". A stray folder at the new place (for example one holding only proxies) never counts as the move; the move completes only into the folder really moved. The message clears as soon as the two places agree, and the project is never shown as fine while its syncing is still held.

#### Lessons

- Met: PRX-070, PRX-071, PRX-072, PRX-073, PRX-074.

## Relinking Resolve after a move

### Resolve's clips follow a moved file now or when the project next opens

After a move, every clip in Resolve's media pool at the old place (or inside the old folder) is pointed at the new place, written in the shared drive's spelling so the project still opens on other computers, and can be undone like every other change CC Sync makes in Resolve. Old and new places are compared ignoring letter case and accent spelling. A folder renamed or moved is one move, and every clip under it is relinked once the whole folder has arrived. Answers: "Resolve not relinked (<reason or 'not open'>)", "N Resolve clip(s) relinked, M could not be", or "Resolve relink failed (see the log)".

When Resolve is closed or open on another project, the relink waits, and is tried again when the open project changes and at most every 5 minutes, for up to 30 days, until it succeeds. Every Resolve project that uses a moved file is relinked when it next opens, and the editor is told. The same holds when a whole project's folder moved.

- See Resolve on the editor's computer: Missing clips, relinking and refreshing, and Fixing media: copying in, rehearsals and undo.
- When the help for the editing program is off: nothing is relinked; the copy still moves.

### An offline clip that moved on the server offers to relink itself

For 30 days after a move, when Resolve shows a clip as missing at the old place (or inside a moved folder), CC Sync can tell that a move took it away and where to. Moves where the copy was set aside rather than moved, and interrupted moves whose file is not really at the new place, are never given as the answer.

When the editor's open timeline has such a clip, once per move each time the app runs, the editor is told: "'<name>' moved on the server. CC Sync can repoint Resolve to where it is now." (title "… this clip moved"). A dialog (title "… this clip moved on the server") then says: "'<name>' is offline in this project because it was moved on the server. It is now at: <new path>. Your copy has already been moved to match. CC Sync can point this project's clips at the new location for you. Nothing is deleted and the change is journalled, so it can be undone." with "RELINK IT" and cancel; then the result, or "Nothing in this project pointed at the old location." If the new file is not here yet: "That clip has not finished moving on this computer yet. CC Sync will offer to repoint Resolve once it has." No dialog opens while another of the app's windows is open.

- When the help for the editing program is off: this does not happen.

#### Lessons

- Met: PRX-075, PRX-076, PRX-077.

## Moves made by hand on the NAS

### A file or folder moved by hand on the NAS is recognised and every computer follows

Within about 15 minutes of the change being seen, the server recognises a move made by hand on the NAS: the same video file (same name, size and modification time) gone from exactly one place and present at exactly one other place, within a project or between projects. Names spelt differently by a Mac and by Windows still match. A move is believed only when the file left one place and then arrived at exactly one other, its new home differs from where it vanished, and a listing known to be current shows it there; before a pair is believed, the server checks that no file with the same name, size and time exists anywhere else right now (if one does, it was a copy, not a move). The two halves are paired even when seen at different times, as long as both are seen within 2 days of each other, the file is now only at its new place, and the disappearance was seen no later than the arrival; a file that comes back to where it was cancels it.

A whole folder whose every file moved to the matching place under one new folder, with nothing left behind, is recorded as one folder move (a folder renamed in place counts too; a folder named "Proxy" is never recorded as a moved folder). Proxies in the "Proxy" folder beside an original that moved to the "Proxy" folder beside its new place go with the original's move.

The move is recorded as already done on the server, by "detected on the server", and every computer holding the file at the old place is told to follow, exactly as for a move made through CC Sync; nothing on the NAS is touched. Every answer built from what the server last saw of the NAS carries the time of the oldest look that went into it.

### Changes on the NAS that are not taken as moves

Each of these stays a plain disappearance and arrival: a file whose size or date could not be read; a file that disappeared from two places or appeared in two places; a file that only disappeared (a deletion); a proxy that moved without its original; a file that, when seen arriving, is also still somewhere else (a copy). The same move is never recorded twice within a day.

### A possible hand move with weaker evidence waits for an admin

When the evidence for a hand move is weaker than the rule above (for example the file arrived at its new place before it left the old one, which is also what a copy followed by a delete looks like), nothing is moved on any computer. The admin is shown the possible move, with the old and new places and why it was not taken as certain, and can confirm it as a move (it is then followed everywhere as above) or dismiss it.

- Who: an admin.

### Every hand move is recognised or the admin is told how many were not

Every hand move is recognised however many happen at once and however the NAS is looked over. If, even so, one look finds more hand moves than can be followed, the admin is shown a serious problem saying exactly how many were not followed, which stays until dismissed.

- See The dashboard: Problems the server finds.

### A project folder moved or renamed by hand on the NAS is followed

Within about five minutes of a project folder being moved or renamed on the NAS, the server points the project at the new place and updates its shown name. Every tick and all its history carry on, because they belong to the project, not to its path. The server does not follow, and checks again every few minutes, when:

- the old folder still exists, so the new one is a copy;
- the new folder does not look like a finished copy of the project (an interrupted or still running copy);
- the new folder holds fewer than half the video files (originals and proxies together) last counted for the project;
- the project's current place is somewhere the server cannot see, in which case it must be pointed at its folder by hand.

Each of these is shown to the admin as a problem with the project, naming the reason, and clears on its own when it no longer holds.

### Proxies moved by hand on the NAS are moved on each computer, not downloaded again

When proxies are only moved on the NAS, each editor's copies are moved on that computer, not removed and fetched again. When a sync has taken proxies off an editor's computer, the computer asks the server where files of the same name and size now are:

- found in exactly one other place, in a project this computer syncs: the copy is moved there (in the server's spelling of the path) instead of being downloaded again, and Resolve's clips are relinked. A file already at that place is never replaced; the copy stays where removed files are held (with a warning when the two sizes differ);
- found in one place, in a project this computer does not sync: it stays where removed files are held, and does not count as a deletion;
- found in several places: nothing moves, since an unclear answer is a refusal, and it does not count as a deletion;
- found only where it was just removed from, or not found: it stays where removed files are held and counts as a deletion.

A file found elsewhere on the NAS with the same name and size is never counted as a deletion toward the download safety stop. A destination outside the editor's synced tree is refused. Names are compared in one Unicode spelling, so a Mac's file names match the server's. Whenever the server cannot answer, or has never finished looking over the NAS, the answer is "not known", never "not found", and the files are treated as removed (kept where removed files are held). The server answers only from what it last saw of the NAS, says how old that is, and names any project it could not read, so nothing is decided from a picture it does not have.

- See Sync: Safety stops.

#### Lessons

- Met: PRX-079, PRX-080, PRX-081, PRX-082, PRX-083, PRX-084.

## Names: letter case and Unicode

### A rename only in letter case or accent form is followed on each computer

The NAS treats "a.mov" and "A.mov" as two names; Windows and macOS treat them as one, and macOS spells accented letters differently from Windows and the NAS. When a file is renamed on the server only in letter case or accent form, each computer renames its copy to match, with its proxies, in two steps, putting the original name back if the second step fails: "renamed to match the server's spelling, N proxy file(s) with it"; on failure "could not rename it on this computer: <error>". A folder renamed only in letter case or accent form is refused on a computer with a sentence (see Moves a computer refuses).

### Names are compared as people read them and files are touched by their exact names

Every comparison of file, folder or project names treats both Unicode spellings of an accented letter as equal, and follows the real drive's rule on letter case; but every opening, moving, renaming or deleting of a file uses the exact name on disk. A clip with Chinese characters in its name is found and relinked exactly as one with an English name.

#### Lessons

- Met: PRX-085, PRX-086, PRX-087, PRX-088.

## Relinking and gathering missing clips

### Resolve clips are pointed at their synced proxies on their own

About every 2 minutes, for clips in the open Resolve project whose original is in the shared tree (the editor's own local or cloud media is left alone) and whose proxy does not work (Resolve shows it offline or it has none), the app attaches the proxy that sits in the "Proxy" folder beside the original, preferring a QuickTime proxy to an MP4. It never copies, moves or deletes a file. The path written into Resolve keeps the original's own spelling (the shared drive's spelling stays the shared drive's spelling, so the project still opens on other computers), even on a Mac without that drive. Each change is recorded as a proxy that was attached but unreachable, or one that was not attached at all, and can be undone like every other change CC Sync makes in Resolve.

- Setting: Attach synced proxies in Resolve. Does: points clips whose proxy is offline or missing at the proxy synced beside the original. Default: on. Who: an editor for their own computer, or an admin. Applies to: a computer. Search words: attach proxies, relink proxies, proxy offline, stale proxy path.
- When the help for the editing program is off: this does not happen.

### Some clips are deliberately not pointed at a proxy

If the clip already points at that exact proxy and Resolve still cannot play it, the proxy itself is damaged: "Resolve already points at this proxy and still cannot play it, so the proxy file itself is damaged. Delete it and CC Sync will make it again." In the b-roll archive only, an MP4 in the "Proxy" folder is the browser preview, not an editing proxy; when the full-quality original is on this computer, it is not attached: "This file is the b-roll browser preview, not an editing proxy, and the full quality original is already on this computer. CC Sync left the clip on the original so you are not cutting at preview quality." Outside the archive an MP4 proxy is attached normally.

- See The b-roll archive: Previews made for the archive.

### The editor is told what attaching proxies did

Each run gives the editor one sentence built from: "Repointed N proxy file(s) to the copies in your sync folder.", "N could not be attached: usually the proxy's timecode does not match the original.", "N got no answer from Resolve and will be tried again." For each clip: "Resolve would not attach this proxy. Usually the proxy's timecode does not match the original.", "Resolve did not answer about this clip, so CC Sync will try it again.", "This clip is not in the project's media pool any more, so there was nothing to attach the proxy to." A pairing Resolve refused is not offered again until the proxy file changes (size or time); a clip Resolve did not answer about is tried again next time.

- Pending: proxies-and-file-moves-Q1

### A missing clip whose file is already in the tree is relinked, never copied

When a missing clip's file already exists in the shared tree with the same name and size, the person is offered a relink to it, never a second copy. When several files of the same name are candidates, the one whose folder path matches the clip's old path most closely wins; only when that leaves a tie does the largest file (the original) beat a smaller one (a proxy); identical backups are no conflict. A match that is uncertain or ambiguous is never applied silently: the person sees each candidate's path, size and a preview, and picks one before anything is relinked. When a clip cannot be relinked because the drive holding its copy is unreachable, the result says that drive is offline.

- See Resolve on the editor's computer: Missing clips, relinking and refreshing.

### A whole project is checked and its stray media gathered into its folder

A person can check a whole project at once. Media the project uses from outside the shared tree is copied into the project's folder on that computer and then uploaded like any other footage. Common audio types (.aac, .opus and every other common audio type) are filed as audio, not as b-roll. Gathering behaves the same on every computer; a failure names the file and the reason. Any check that comes back with no answer is treated as failed and named to the person, never taken as an empty list of things to do.

- See Resolve on the editor's computer: Fixing media: copying in, rehearsals and undo.

### A backup of chosen timelines takes only the media they use

A person can back up a project by choosing timelines. The backup copies only the media used in those timelines, with their proxies, and a project file. Before it starts it shows how much space is free where it is going, and while it runs it shows live progress.

### A new project gets the studio's folder template without disturbing what is there

Creating or adopting a project adds any of the studio's template folders that are missing, and never moves, renames or overwrites a folder or file already there.

- See Sync: Project folders on an editor's computer.

#### Lessons

- Met: PRX-089, PRX-090, PRX-091, PRX-092, PRX-093, PRX-094, PRX-095, PRX-096, PRX-097, PRX-098.

