# Resolve on the editor's computer: what real use taught

152 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## Multicams, frame rates and timelines

### CRX-091: Scripted effects inside compound clips lose their first frames and abort renders.
- Why: A Fusion composition added by script loses its first one or two frames ("No frame available") once its clip is wrapped in a compound clip.
- Must: A compound clip the product builds renders every frame including its first, checked by rendering the head frames before handing it over.
- Kind: given

### RSV-103: Resolve's scripting reports no file path and no angles for multicam clips.
- Why: A multicam answers "" for its file path and scripting shows nothing of its angles; on a 904-item multicam timeline scripting found 0-3 paths in 4-14 s, against 44 angle files really used.
- Must: Every multicam and compound clip's source files are found from its angles, and a timeline of multicams never reads as having no media.
- Kind: given

### RSV-104: A multicam angle can be a compound clip or several camera files in a row.
- Why: Four interviews had a compound clip as angle 1, and others had angle 1 spread over several camera files, leaving black stretches when only the first was used.
- Must: Anything built from a multicam angle follows compound clips down to the camera files and places every file at its own time.
- Kind: given

### RSV-105: Built multicams all start at 01:00:00:00 and carry no reel or file name.
- Why: Reconform attached cuts to the wrong multicam; the owner: "It's reconforming things named differently to the wrong multicam. I'm actually pissed."
- Must: Multicam matching uses a property unique to each (such as exact total duration), checks it is unique first, and refuses rather than guesses.
- Kind: given

### RSV-106: A multicam's angles map frame for frame from their starts, not by timecode.
- Why: Building a multicam resets its timecode to 01:00:00:00, and angles map frame for frame, even a true 24.000 angle in a 23.976 multicam, so timecode conform landed minutes off.
- Must: Moving cuts between a camera clip and its multicam maps frames one to one from the angle's start, never by source timecode or real time.
- Kind: given

### RSV-107: Importing a timeline into a project that holds its multicams duplicates them.
- Why: Resolve dedupes footage by path but re-imports multicam and compound clips as "... import" copies, and the grade lives inside the multicam, so copies split the grade.
- Must: Combined projects keep one copy of each multicam, matched by unique total duration since multicams share timecode, and leftovers are set aside, not lost.
- Kind: given

### RSV-108: Rebuilding a damaged multicam timeline by export and reimport fails both ways.
- Why: An XML round trip lost multicam angles, subtitles and half the links; Resolve's own timeline export kept the bad links and imported duplicate angle timelines into the bin.
- Must: A damaged multicam timeline is repaired inside Resolve (duplicate it and relink each pair), never by an export and import round trip, leaving no stray angle timelines.
- Kind: given

### RSV-109: Resolve places scripted clips a frame early and reports odd source times.
- Why: An append asked for frame 1238 landed at 1237; the source start counts from the file's start timecode; and Resolve reported an empty frame count for one WAV.
- Must: Every clip placed in Resolve by script is read back and re-laid once if it is off by a frame.
- Kind: given

### RSV-110: Resolve's append can report success while placing nothing.
- Why: Appending without naming a track follows the timeline's destination-track buttons; with the video destination off nothing lands, no error returns, and a returned item proves nothing.
- Must: After adding a clip to a timeline, the product confirms it is there at the expected start, without pinning it to one media type and losing its sound.
- Kind: given

### RSV-111: Resolve projects start at 24 fps or at the first raw clip's rate.
- Why: New projects were 24 fps, or 30 after the first Blackmagic raw import; scripting refuses a timeline's own rate, and the project rate changes only while there are no timelines.
- Must: Before anything is imported or built, the project's rate is checked against the footage (29.97 drop-frame here) and the person is stopped if it cannot be set.
- Kind: given

### RSV-112: Resolve counts an audio-only clip's frames in that clip's own rate.
- Why: Resolve gave recorder WAVs 24 fps; asking for 48,508 frames on a 29.97 timeline placed 60,574, making an angle timeline 401 s too long.
- Must: Placing audio-only clips into a timeline converts frames using the clip's own rate and checks the timeline's length afterwards.
- Kind: given

### RSV-113: Several things in Resolve cannot be done by script at all.
- Why: Scripting refuses clip speed, loudness normalising, a clip's frame rate, a timeline's own rate, audio fades, and putting a sound file on a multicam's audio angle.
- Must: Each such step is handed to the person as a named manual instruction with its exact value, and the product never reports success for a setting Resolve refused.
- Kind: given

### RSV-114: Resolve's count of linked clips changes between sessions on identical timelines.
- Why: The same timeline, with byte-identical stored data, showed 490 of 490 clips linked, then 242, then 238.
- Must: Resolve's scripted link count is never taken as proof that picture and sound are paired.
- Kind: given

### RSV-115: Resolve cannot decode VP9 originals at full resolution, though proxies edit fine.
- Why: Resolve Studio 21 on Windows logs "Failed to decode the video frame" for VP9 originals and the final render fails; YouTube MP4s are often VP9; AV1 and HEVC render fine.
- Must: The editor is warned as soon as a timeline uses VP9 originals, naming each clip and the fix, and is warned again for any newly added one.
- Kind: given

### RSV-116: Repairing undecodable clips before a deadline render takes seconds, not hours.
- Why: A 48-minute re-encode blocked a render; the owner: "just copy the proxy out into the main folder instead of re-encoding each one individually".
- Must: A pre-render repair swaps in an edit-ready copy with the same frame count in seconds per clip, re-encoding only when no matching copy exists.
- Kind: ruling

### RSV-117: A conformed timeline had no sound on one editor's computer.
- Why: Every audio clip, multicam source and file was present for that editor, yet the conformed timeline played silent; the cause was never found.
- Must: When a conformed timeline is silent on one computer, the product can check that computer's playback and offline clips and say which is at fault.
- Kind: situation

## Clip paths and media outside the shared tree

### RSV-058: Resolve stores a clip's path exactly as it was browsed.
- Why: Importing the shared tree through another drive letter or from a Desktop plays locally but is offline on every other computer; one shared project had over 200 such clips, unwarned.
- Must: Every clip imported from inside the tree, by any spelling, ends up stored in the shared spelling automatically, and a clip on a computer-private path is flagged to its importer.
- Kind: given

### APP-104: Clips found while a dialog was open were lost behind an "already open" notice.
- Why: The owner ruled: "get rid of the popup already open message ... the editor can decide"; clips found meanwhile were silently dropped.
- Must: Clips found while a dialog is open are shown, without duplicates, as soon as it closes, and no "already open" notice appears.
- Kind: ruling

### APP-105: A clip from the b-roll archive must not set off the editor's popup.
- Why: The archive lives outside any project folder, and the owner warned such a clip should not "flip the trigger for a popup" asking where to file it.
- Must: A timeline clip whose file is in the shared b-roll archive is treated as correctly placed and never prompts the editor.
- Kind: ruling

### RSV-059: Every computer sees the project tree at the same drive and path.
- Why: The base computer used one drive letter and editors another, so Resolve projects shared between them could never link; the base was moved to match.
- Must: Every computer, base included, opens the project tree at the identical drive and path, so a Resolve project links the same everywhere.
- Kind: ruling

### RSV-060: Media used from outside the project folder raises a warning naming the project.
- Why: The owner wanted a popup to move such media "to where it is syncable", and: "this warning should say which project", since it may be an editor's personal project.
- Must: The warning names the clip, the Resolve project and where to move it, and a project that is not one of the studio's synced projects raises nothing.
- Kind: ruling

### RSV-061: On the base computer only media outside the project's own server folder is flagged.
- Why: The base got out-of-project popups for media already on the server; careless base work can also leave clips outside, so the owner wanted it narrowed, not removed.
- Must: On the base computer the out-of-project popup lists only clips outside that project's own server folder, never clips already inside it.
- Kind: ruling

### RSV-062: A reminder about missing or outside media can be skipped for 30 minutes only.
- Why: A folder skipped "always" hid 30 music files added a day later; "skip for now" lasted six days. The owner: "it should constantly bother people until they do it".
- Must: There is no permanent or per-folder dismiss; a skip lasts 30 minutes, pressing it again never extends that, the button says so, and anything new is always offered.
- Kind: ruling

### RSV-063: A clip fixed on a laptop opened offline on every other computer.
- Why: The fix relinked clips to the laptop's physical disk; the Resolve project travels between computers but drive layouts do not.
- Must: Every path the product writes into a Resolve project is the shared project-drive spelling, never one computer's physical disk.
- Kind: situation

### RSV-064: Clips at the right shared path kept being flagged as offline.
- Why: Clips relinked to the shared drive path were judged misplaced on the laptop, so the popup kept returning though the files opened fine.
- Must: A clip whose file exists at its shared project-drive path is never flagged, offered for fixing or warned about again.
- Kind: situation

### RSV-065: Clips on one editor's Desktop went unnoticed in a project nobody opened.
- Why: 45 music clips in a shared project pointed at one editor's Desktop for over a week, because only the project currently open in Resolve was checked.
- Must: Every 30 minutes every project in every library the computer can read is checked for media outside the tree, and its editor and the dashboard are told, naming project and count.
- Kind: situation

### RSV-066: Skipped clips stayed hidden, uncounted, even from a whole-project scan.
- Why: "Ignore all" or skip hid clips for the session with no total, and a full project scan honoured the skip too.
- Must: Skipped clips are counted and shown as still not syncing, a whole-project scan re-offers them, and an automatic skip is recorded apart from an editor's.
- Kind: situation

### RSV-067: Clips found while an editor read a popup were silently dropped.
- Why: A batch found while one popup was open was discarded behind an "already open" notice re-fired every 3 seconds.
- Must: Later batches queue and show when the current popup closes, deduplicated so the same clips never produce repeated dialogs.
- Kind: situation

### RSV-068: A 300-clip project on an unmapped drive raised 300 identical notifications.
- Why: The missing-drive warning fired once per clip path; on a Mac each was a slow system notification that also held up watching Resolve.
- Must: One problem raises one notice per episode, however many clips it touches, re-armed only after it has cleared and broken again.
- Kind: situation

### RSV-069: The broken drive mapping warning wrongly said nothing would sync.
- Why: When the media drive letter stopped pointing at the synced folder only Resolve's view broke, yet the warning said all syncing had stopped and offered no repair.
- Must: The warning says clips will show offline while transfers continue, offers a repair on Windows, and refuses to remove a mapping the product did not create.
- Kind: situation

### RSV-070: An editor with 40 dead links in Resolve saw no number anywhere.
- Why: Counts of missing clips, clips outside the tree and unattached proxies were computed but shown only in diagnostics, never to the editor or the admin.
- Must: The editor and the dashboard see those counts per computer with when they were checked; before any check finishes it reads "not checked yet", never zero.
- Kind: situation

### RSV-071: A pass that refreshed forty clips said "nothing to do".
- Why: Clips re-read after their file changed were counted nowhere people look, so every surface said "attached: 0" and the pass looked idle.
- Must: Every count of Resolve changes shown to editors and admins includes clips re-read after their file changed.
- Kind: situation

See also, filed under another capability:

- PRX-096 (Proxies and file moves): Music files in AAC were filed as b-roll instead of music.

## Setting Resolve up: edition, scripting switch, preferences

### RSV-032: Resolve's external scripting is off by default and absent from the free edition.
- Why: Only Resolve Studio has external scripting; it needs Preferences, System, General, "External scripting using" set to Local (default None), and the project library added.
- Must: Setup detects edition and setting, sets Local or names exactly what to change or that Studio is needed, and says done only after a real connection.
- Kind: given

### RSV-033: A dongle-licensed Resolve Studio has no licence file, like the free edition.
- Why: A Studio licence file proves Studio, but a dongle install has none, so a missing licence file does not mean the free edition.
- Must: A found Studio licence counts as proof of Studio, and no editor is told they have the free edition because a licence file is missing.
- Kind: given

### RSV-034: Resolve installed on another drive stopped the app from reaching it.
- Why: On a remote editor's computer with Resolve on drive F: and scripting set to network, the app could not reach Resolve until the location was dealt with.
- Must: The product reaches Resolve wherever it is installed, or says in plain words that it cannot find Resolve and where it looked.
- Kind: given

### RSV-035: Driving Resolve from another computer needs its network scripting switch, never tested.
- Why: It needs Resolve's "External scripting: Network" preference, which opens Resolve's scripting port to the network; the owner has not approved that.
- Must: Nothing relies on network scripting until tested, and if used, the port is reachable only from the studio's own computers.
- Kind: given

### RSV-036: Resolve discards preference changes made while it is running.
- Why: Resolve holds its preferences in memory and rewrites its preference files on quit, so outside edits made meanwhile vanish; LUT locations have no scripting interface.
- Must: Resolve's preferences change only while it is closed; setup asks the editor to quit, waits up to 180 s, continues by itself, and checks the change survived the next start.
- Kind: given

### RSV-037: Resolve's first run regenerates its whole configuration when no preferences exist.
- Why: Preferences written before Resolve has ever run on a computer are thrown away when it first starts.
- Must: Where no Resolve preferences exist yet, the editor is asked to launch and quit Resolve once before any preference is changed.
- Kind: given

### RSV-038: Resolve warned at every launch that the stills location differed between computers.
- Why: Resolve derives its stills gallery folder from the first numbered media storage entry, normally each computer's own scratch disk; the render cache also refers to entry one by number.
- Must: Every computer sharing a project library uses one shared stills location, the first media storage entry never moves, and nothing changes until the shared folder exists.
- Kind: given

### RSV-040: Resolve registers the selected library entry's address as its collaboration address.
- Why: A second library entry for the same server re-registered an unreachable address, and Resolve rewrites its library list when it exits.
- Must: Library entries are written only while Resolve is closed, one per library, each using the address every editor can reach.
- Kind: given

### APP-106: Installing on a Mac sets Resolve's path mapping automatically.
- Why: The owner asked that a Mac install "auto set resolve path mapping", so projects made on Windows find their media.
- Must: After install on a Mac, Resolve maps the shared drive's Windows paths to the Mac's mount without the editor doing it by hand.
- Kind: ruling

### RSV-041: Setup must cope with Resolve Free, scripting off, older Resolve and non-English Windows.
- Why: Setup had never been tried on those, nor on security-locked Windows.
- Must: On each, setup completes or names exactly what the editor must change, and syncing keeps working without Resolve's scripting.
- Kind: situation

See also, filed under another capability:

- SRV-012 (The server: installing it and keeping it running): Resolve collaborators were shown an internal server address and could not connect.

## Bins, clip sorting and imports

### SRT-186: Re-importing a folder of numbered stills duplicates them in Resolve.
- Why: Resolve groups numbered JPGs into image sequences whose path is not one file, so an "already imported" check misses them; 941 stills became 86 sequences and 50 stills.
- Must: Re-importing a folder into Resolve never adds a second copy of stills it already holds as image sequences.
- Kind: given

### RSV-118: Resolve calls an ordinary clip's type "Video + Audio".
- Why: Testing for audio first filed nearly every clip as audio (174 clips called music), and compound clips landed in effects.
- Must: A clip with picture is never classed as audio, compound clips get their own bin, and a file named like a YouTube download is filed as YouTube.
- Kind: given

### RSV-119: Resolve's scripting can read a bin's name but cannot rename a bin.
- Why: The owner asked for a bin's capitalisation fixed, and it had to be done by hand.
- Must: Bins the product creates are named correctly when created, and a needed rename is listed for the person instead of claimed as done.
- Kind: given

### RSV-120: Resolve's scripted import files clips into whichever bin is currently selected.
- Why: Aiming background imports meant switching the current bin and back every 20-60 s, overwriting a bin the editor had just clicked.
- Must: Background imports into Resolve never change which bin the editor has selected, even when the editor clicks mid-import.
- Kind: given

### RSV-121: Each interviewee gets their own bin, with their sound recordings beside their footage.
- Why: The owner wanted a bin per interviewee, detected from their folder name, holding all footage from that folder plus the field-recorder audio files.
- Must: Sorting creates one bin per interviewee folder and puts all that folder's video and sound-recorder files in it.
- Kind: ruling

### RSV-122: A project's existing bins are the sorting template, including unfamiliar ones.
- Why: The owner wanted sorting to follow the project's own bins and react to unfamiliar ones by meaning, for example a "dmg" bin attracting .dmg files.
- Must: Sorting targets the project's existing bins and routes clips to an unfamiliar bin when its name plainly describes them, proposing rather than applying.
- Kind: ruling

### RSV-123: Sorting again never re-sorts clips already placed.
- Why: The owner wanted sorted clips remembered, existing theme bins preferred over new ones, and interview bins left alone, to avoid "an insane number of categories".
- Must: A repeat sort moves only new clips, files them into existing matching bins before proposing any new bin, and never touches interview bins.
- Kind: ruling

### RSV-124: Every downloaded YouTube clip goes into a theme bin, never the parent bin.
- Why: The owner: "It should put ALL youtube clps into a subcategory bin, and only uncategorised at the absolute last resort, and never into the master youtube clips bin".
- Must: After sorting, no YouTube or archive clip sits loose in its parent bin; each is in a theme bin or, last, in "Uncategorised".
- Kind: ruling

### RSV-125: Resolve's clip colour names mislead, and the owner bans "Brown".
- Why: Resolve's "Brown" renders mustard ochre, which the owner never wants; "Chocolate" is the brown, "Pink" is pale and "Violet" is hot pink.
- Must: No clip colour the product assigns or offers is "Brown", and colour pickers show swatches, not Resolve's names alone.
- Kind: ruling

## Connecting to Resolve's scripting: launch, stalls and death

### RSV-001: Connecting during Resolve's launch hangs it and kills scripting for the session.
- Why: Resolve's script server (fuscript, port 1144) starts 90-470 s into launch; any client connecting before Resolve registers with it ends scripting for every program until Resolve restarts.
- Must: Nothing on the computer, helpers included, connects until the script server is listening and Resolve itself is connected to it; only an unreadable check may connect anyway.
- Kind: given

### RSV-002: A connect attempt with no script server present blocks about four seconds.
- Why: The connect call retries about 4 s (8 s behind a second thread) instead of failing, so a "quick check" is mid-connect when the server appears; a fixed wait after launch misses the window.
- Must: Readiness is judged from the script server and Resolve's connection to it, never from a delay after Resolve starts, and no check ever attempts a connection to find out.
- Kind: given

### RSV-003: Resolve's script server, if it fails at launch, never retries that session.
- Why: Resolve then looks normal on screen while every scripted action is silently lost; only quitting and reopening Resolve brings scripting back.
- Must: The product tells "Resolve is closed" apart from "Resolve is open but not accepting scripting", and names restarting Resolve as the fix for the second.
- Kind: given

### RSV-004: A client still connected to a closed Resolve breaks scripting in later sessions.
- Why: A long-running client keeping its connection after Resolve quits wedges scripting in every new Resolve session for all programs, until that client is stopped before Resolve restarts.
- Must: When Resolve exits every connection to it is dropped, and recovery advice says: close the app, close Resolve, start the app, start Resolve.
- Kind: given

### RSV-005: Resolve answers scripting calls one at a time, so one slow client stalls all others.
- Why: All properties of a clip cost 12.5 ms, one property 0.1 ms; a 904-clip walk held Resolve 11-95 s, turning another program's 0.3 s click into 7 s, and froze Resolve.
- Must: No program of the product holds Resolve's scripting for more than half a second at a time, and every read asks only for the properties it needs.
- Kind: given

### RSV-006: Reading every clip's details from Resolve took about 90 seconds.
- Why: Asking Resolve for each clip's properties on a project of about 1,300 clips took about 90 s, and 1,300 clips is a normal project here.
- Must: Any whole-project scan shows progress, keeps the product usable throughout, and treats a 1,300-clip project as normal size.
- Kind: given

### RSV-007: Sweeping Resolve's media pool by script stalls Resolve's own interface.
- Why: Asking every clip's proxy state took about 5.5 s per 1,298 clips, each new scripting connection about 75 ms, and a once-a-second 1,350-call sweep ran during playback.
- Must: Background work never sweeps Resolve's whole media pool or timeline on a timer when nothing changed, and asks Resolve nothing during playback.
- Kind: given

### RSV-008: A single Resolve call can block for seconds, minutes or indefinitely.
- Why: A call lasts as long as Resolve's main thread takes: milliseconds idle, seconds in playback, render or a big project, indefinitely behind a modal dialog, the Project Manager or a dropped share.
- Must: No Resolve call blocks the tray, a window, other features or quitting; each call has a deadline after which it is reported and abandoned.
- Kind: given

### RSV-009: A Resolve call hung twenty minutes while Resolve still read as connected.
- Why: Importing media from a share that had gone away hung a scripting call for twenty minutes or more, while the status still showed Resolve connected in green.
- Must: When any Resolve call has run over 20 s, the status shows "Resolve: not answering for N s" in amber, never connected.
- Kind: given

### RSV-010: Resolve's scripting went dead for hours with nothing logged.
- Why: Scripting died at 00:20 and stayed dead until Resolve was relaunched at 08:00, and no client recorded a cause.
- Must: When Resolve stops answering, the product says so plainly and tells the person Resolve must be relaunched.
- Kind: given

### RSV-011: Any open Resolve dialog makes its scripting answer nothing, for every program.
- Why: An "Audio Output: device not found" box (speaker unplugged, or "Remote Audio" after Remote Desktop) appears on project load; until clicked, calls return nothing and queued renders sit at Ready.
- Must: Empty answers mean "Resolve cannot answer now", never missing data; nothing is written meanwhile, the person is told to check Resolve for an open box, and renders are confirmed started.
- Kind: given

### RSV-012: Opening projects by script stops on Resolve's own dialogs.
- Why: Resolve halted on a "save current project" box and an audio output box, then sat on "loading" a project until someone clicked.
- Must: Automated work in Resolve notices a blocking dialog or a stalled project load and tells the person, instead of waiting forever.
- Kind: given

### RSV-013: After a forced restart Resolve showed a "save current project" box that would not close.
- Why: A forced close and automatic restart of Resolve brought up a save dialog for an unknown project that could not be dismissed.
- Must: The product never force-closes Resolve without first saving or closing the open project, and checks Resolve is usable after a restart.
- Kind: given

### RSV-014: Resolve's scripting returns nothing with no project or only "Untitled Project" open.
- Why: On the Project Manager connecting returns nothing; on the placeholder "Untitled Project" it connects but load, create, page and library calls return nothing; calls were seen stalling 120 s.
- Must: With Resolve open and no real project loaded, the product says so and asks for a project, never hangs or claims Resolve is closed.
- Kind: given

### RSV-015: Resolve's scripting goes dead while the Remote Desktop session is disconnected.
- Why: With the Windows session disconnected, load, save and page calls return nothing; one such Resolve stopped responding and crashed about 30 minutes later.
- Must: A disconnected desktop session on the Resolve computer is detected and the person told to reconnect, instead of attempting Resolve work.
- Kind: given

### RSV-016: Resolve crashes after about 13 minutes of continuous scripted work.
- Why: A run exporting 57 projects one after another crashed Resolve after about 13 minutes, each export taking well under a minute.
- Must: Long scripted work records progress per item, survives Resolve crashing or hanging, resumes without redoing finished items, and verifies each output exists at the right size.
- Kind: given

### RSV-017: Two simultaneous calls into Resolve's scripting can crash the calling program.
- Why: Resolve's scripting library is not safe to call from two threads at once; a concurrent call crashed the editor app with an access violation and nothing logged.
- Must: The editor app never has two calls into Resolve's scripting in flight at once, including small lookups made after a relink.
- Kind: given

### RSV-018: Resolve's scripting objects accept any method name and fail only when called.
- Why: A save called on the project object passed every check because the object claims any method; the save belongs to the project manager, and fake tests never caught it.
- Must: Every Resolve scripting call the product uses is checked once against a real Resolve before it ships.
- Kind: given

### RSV-019: On a Mac every Resolve feature was silently dead.
- Why: On macOS Resolve's scripting modules sit under a Developer folder in its support folder; a wrong location meant no connection, noted only at debug level.
- Must: When Resolve's scripting cannot be reached, the person is told in plain words, never only in a debug log line.
- Kind: given

### RSV-020: Blackmagic Proxy Generator runs as the Resolve program itself.
- Why: The proxy generator is the Resolve program started with a "-pg" switch, so a process check reads it as Resolve running.
- Must: Detecting Resolve ignores a Resolve process started with the proxy generator switch.
- Kind: given

### RSV-021: Warn every five minutes while Resolve runs without working scripting.
- Why: Resolve looks normal while every insert and fix is silently lost; the owner asked for a popup "every five minutes" telling the editor to restart Resolve.
- Must: While Resolve is confirmed running and scripting is unavailable, a warning repeats every five minutes, the first after one full interval, and stops on recovery.
- Kind: ruling

### RSV-022: Editors were told scripting was dead while Resolve was only starting or quitting.
- Why: The script server appears 90-470 s after launch and Resolve lingers as a process after quitting, so "no server" is normal for minutes.
- Must: For ten minutes after Resolve launches or quits the product shows a neutral "starting up or shutting down", and dead-scripting advice leads with "quit and reopen Resolve".
- Kind: situation

### RSV-023: A computer that had never connected was told "quit and reopen Resolve" for ever.
- Why: Restarting Resolve cannot fix scripting that was never switched on, and the product forgot across its own restarts that this computer had never connected.
- Must: A computer that has never connected to Resolve gets setup advice, not restart advice, and that knowledge survives restarts of both programs.
- Kind: situation

### RSV-024: The log claimed scripting was ready when Resolve had gone or nothing was seen.
- Why: Resolve quitting mid-launch, or a connection table that could not be read, was logged with the same line as Resolve registering, misleading anyone diagnosing a hung launch.
- Must: The log says "Resolve went away, nothing connected" or "could not tell, connected anyway" when so, and says "registered" only when registration was seen.
- Kind: situation

### RSV-025: Checking whether Resolve is running must cost almost nothing.
- Why: Each check started an operating-system process listing (202 ms), 230 to 1,100 times an hour, and b-roll ingest checked before every frame.
- Must: An idle computer starts no helper processes to learn whether Resolve is running, and one answer serves every part of the product.
- Kind: situation

### RSV-026: Two programs on one computer talking to Resolve endanger its scripting.
- Why: A second Resolve client on the same computer risks scripting for the whole session and queues behind or ahead of the first for Resolve's one-at-a-time answers.
- Must: One program per computer talks to Resolve, holding it only during calls, never while computing; another found running is named and left alone, and "cannot tell" counts as running.
- Kind: situation

### RSV-027: A check for a competing Resolve client mistook unrelated programs and stayed refused.
- Why: It matched any command line containing certain words, including an operator's shell, and was run again only at the next app start.
- Must: The check identifies only a real competing Resolve client, names it, and re-checks by itself without an app restart.
- Kind: situation

### RSV-028: A failed start left extra Resolve workers running, one more every minute.
- Why: A start that failed after its Resolve worker began left it running, each retry added another, and a restarted stuck worker later ran beside its replacement, both changing the project.
- Must: A failed start stops what it began, retries stop after five failures and say so, a stuck worker is reported rather than duplicated, and one computer never runs two.
- Kind: situation

### RSV-029: A dead background helper kept reporting itself as running.
- Why: The restart check counted helpers started rather than alive, so a dead one was never restarted and the editor's phone page stayed dead.
- Must: A helper whose work has stopped is restarted within a minute, judged by whether it is actually alive.
- Kind: situation

### RSV-030: A scheduled per-project Resolve export must wait for Resolve to finish launching.
- Why: A per-project export needs a running Resolve, and a scheduled job connecting during Resolve's launch would kill scripting for every program on that computer.
- Must: Scheduled Resolve exports connect only after Resolve has fully registered with its script server, never during launch.
- Kind: situation

### RSV-031: Resolve crashed instantly on launch on the studio's main computer.
- Why: The owner reported Resolve crashing at launch on the main computer; no cause was found.
- Must: Nothing on an editor's computer contacts Resolve before its launch completes, and Resolve launch failures are logged for diagnosis.
- Kind: situation

## Project libraries and projects

### RSV-042: Resolve freezes about five seconds per unreachable remote project library at launch.
- Why: Resolve tries every listed remote library in turn on its splash; Windows marks it Not Responding and editors force-quit, thinking it will not start.
- Must: When the shared project library is unreachable, the editor is told the network to it is down before or as Resolve opens.
- Kind: given

### RSV-043: Resolve launched before the network keeps network project libraries offline.
- Why: After a reboot Resolve started before the private network was up, timed out on every network library and kept them offline until relaunched.
- Must: The editor is warned when Resolve started before its project library's network was up, and told to relaunch Resolve.
- Kind: given

### RSV-044: Resolve 21 does not say which project library is open.
- Why: In Resolve 21 the current-library and library-list calls return nothing (they worked in 20); with Live Save off, the library holds nothing newer than the last save.
- Must: The product finds the open project library without those calls, shows the person which one it found, and never treats the library as holding unsaved work.
- Kind: given

### RSV-045: Two Resolve projects can share a name.
- Why: Same-named projects can sit in different project-manager folders, and finding a project by name took the first match, using the wrong project's media.
- Must: A Resolve project is identified by its name together with its folder; if still ambiguous the product refuses or asks, never picks.
- Kind: given

### RSV-046: Resolve names differing only by case overwrote each other's files on Windows.
- Why: Resolve project and clip names are case-sensitive and Windows file names are not; one export silently replaced the other and both reported done.
- Must: Names differing only by case stay distinct everywhere, files written from them never collide, and every export is verified present at the right size.
- Kind: given

### RSV-047: A dump of Resolve's project server restores straight from Project Manager.
- Why: Resolve's project libraries live in a database server; a dump in the format of Resolve's own Backup restores in Project Manager; six libraries came to 144 MB.
- Must: Every Resolve project library is backed up nightly, checked readable, kept 30 days, in a form Resolve's Project Manager can restore.
- Kind: given

### RSV-048: Resolve can be open while refusing scripting, and its last save stays readable.
- Why: With scripting refusing, the timeline and transcripts as of Resolve's last save were still in the project library, so work could continue.
- Must: With Resolve closed or refusing scripting, the editor still shows the timeline as of Resolve's last save and says plainly it is not live.
- Kind: given

### RSV-049: Resolve project tiles showed the Resolve logo instead of a picture.
- Why: Resolve samples five frames from the current timeline on close; gaps, black or undecodable media leave the shown slot empty.
- Must: Projects the product creates or closes are left on a timeline with picture, so their tile shows a frame.
- Kind: given

### RSV-050: In a locked project Resolve refuses to make a bin and says nothing.
- Why: Creating a bin in a locked or collaboration project returns nothing instead of an error, so the editor was wrongly told to open a project.
- Must: When Resolve will not create a bin, the editor is told the project looks locked, not given a generic "open a project" error.
- Kind: given

### RSV-051: Resolve regenerated every audio waveform at each launch.
- Why: The owner's Resolve opened synced projects with waveforms missing and rebuilt them every time; he wanted them kept with the project on the NAS.
- Must: Opening a synced project shows its audio waveforms without waiting for them to regenerate on each launch.
- Kind: given

## Knowing which project is open

### RSV-052: Resolve's scratch projects look open though nobody is working in them.
- Why: Blackmagic Proxy Generator runs a helper project "New Doc", every unsaved project is "Untitled Project", and Resolve numbers copies ("New Doc 1", "Untitled Project (3)").
- Must: These names and numbered copies never trigger prompts, matches or dashboard reports; an editor in "Untitled Project" is told to save under a real name to be asked.
- Kind: given

### RSV-053: A Resolve project is linked to a project folder only on an exact name match.
- Why: Linking on a partial name overlap was silent and permanent; the owner: auto-linking into a non-matching project "is not useful behaviour".
- Must: A Resolve project links automatically only when its name exactly matches one project folder's name; anything else, or an unreadable tree, asks the editor.
- Kind: ruling

### RSV-054: Opening an unknown Resolve project asks once whether to set it up.
- Why: The owner wanted a prompt when a never-seen project opens, leading to picking or creating its server folder; once he got no prompt in a new project.
- Must: The first time a person opens an unlinked Resolve project they are asked once to set it up, then can pick or create its server folder.
- Kind: ruling

### RSV-055: Switching Resolve projects mid-check copied files into the wrong project.
- Why: A check taken in one project was acted on after the editor switched; 23 music files went into the wrong project's folder and all 23 relinks failed.
- Must: Before showing or acting on any scan or fix row, the product confirms that same Resolve project is still open; if not, it refuses and names the project.
- Kind: situation

### RSV-056: The fix list pointed clips at another project's folder and ran off screen.
- Why: In one project the fix list proposed moving clips into a different project's folder, showed empty rows, sat off the top of the screen and could not scroll.
- Must: Fix suggestions target only the open project's folder, empty rows never appear, and the window fits the screen and scrolls.
- Kind: situation

### RSV-057: The out-of-project prompt went quiet until Resolve was restarted.
- Why: On a laptop a clip outside the project folder raised no prompt until Resolve was restarted, suggesting the product's view of Resolve had gone stale.
- Must: The out-of-project check keeps working for a whole Resolve session, and if it loses Resolve it says so instead of going quiet.
- Kind: situation

## Missing clips, relinking and refreshing

### RSV-073: Resolve silently refuses to create or relink a clip at a path it cannot open.
- Why: Linking, replacing or importing at a missing path just answers false, with no error.
- Must: A clip is placed or relinked only where a real file exists, and an absent original gets a stand-in file at its real path first.
- Kind: given

### RSV-074: Resolve does not re-read a file swapped under an existing clip.
- Why: When a clip's file is replaced (a preview by the real original), Resolve keeps the old length and resolution, even after reopening, until the clip is replaced with that same path.
- Must: After a clip's file changes, Resolve shows the new file's length and resolution before proxies are linked, and success is judged by those changing, never by the path.
- Kind: given

### RSV-075: Resolve's replace-clip call returns nothing even when it works.
- Why: The call gives no value whether or not it succeeded, so every successful relink had been logged as a failure.
- Must: Every relink is verified by re-reading the clip's file path, with retries, before its outcome is reported.
- Kind: given

### RSV-076: In a shared project Resolve applies relinks seconds to minutes later.
- Why: In a collaborative project replace, relink and proxy-link calls return no result and take effect seconds to minutes later, reaching other open sessions without reopening.
- Must: Success is judged by re-reading the clip's paths after a wait, and a retry happens only after that re-read.
- Kind: given

### RSV-077: Resolve's clip replace can fail on some tries and succeed on others.
- Why: Mid-render or in a scripting hiccup some attempts raise errors; treating the surviving "nothing changed" answer as final disabled the repair for that clip.
- Must: A repair attempt during which Resolve raised any error is retried on the next pass, never remembered as settled.
- Kind: given

### RSV-078: Resolve cannot relink subtitle clips.
- Why: Resolve's replace call fails for subtitle (.srt) items in the media pool; they can only be imported again.
- Must: A relink that meets a subtitle clip re-imports it from the new place or names it to the person, and never counts it as fixed.
- Kind: given

### RSV-079: Resolve reports an image sequence by a bracketed path that never exists on disk.
- Why: Resolve keeps a sequence as "Name_[00000-00287].exr" even after relinking, so every sequence looked offline; replacing with the first frame relinks the whole sequence.
- Must: An image-sequence clip counts as online when its first frame exists, and is relinked by pointing at that first frame.
- Kind: given

### RSV-080: Resolve's media pool can show a relinked clip offline until the bin changes.
- Why: After a scripted relink some clips showed offline in the media pool though fine on the timeline; going to another bin and back cleared it.
- Must: After relinking, the product checks each clip's status itself rather than trusting the media pool's display, and tells the person a bin switch refreshes it.
- Kind: given

### RSV-081: Resolve holds its media files open, so they cannot be moved or deleted.
- Why: On Windows a file used in an open project, including a NAS proxy a wired computer is playing, refuses rename, move or delete until the project closes or Resolve quits.
- Must: Every move, rename, replace or delete of media expects Resolve may hold it, retries later, reports what stayed, and tells the editor closing Resolve will let it finish.
- Kind: given

### RSV-082: Resolve crashed opening a project whose clip was relinked to a shortcut file.
- Why: A relink picked a Windows shortcut (.lnk) with the clip's name; Resolve then crashed opening that project until the shortcut was deleted.
- Must: Relinking never links or offers a shortcut or any file that is not playable media of the clip's kind.
- Kind: given

### RSV-083: Resolve rejects hand-edited project and timeline interchange files.
- Why: Resolve's exported project keeps clip paths in an opaque block, and a hand-written FCPXML is not accepted at all, so repointing clips by editing such files fails.
- Must: Any way of changing where clips point is proven on a real Resolve before it is relied on.
- Kind: given

### RSV-084: Render In Place files exist only on the computer that rendered them.
- Why: A re-synced project lost all 175 Render In Place clips: they pointed at empty folders elsewhere, and after a re-rooting the renders were nowhere on any disk.
- Must: Render In Place files in a synced project reach the NAS like other media, or the editor is told which clips will be offline elsewhere before media moves.
- Kind: given

### RSV-085: The owner wanted a quick relink of only the open timeline.
- Why: Relinking a whole project takes long; the owner asked "to only relink the active timeline if you're in a hurry".
- Must: Relink offers a scope of just the active timeline's clips, besides the whole project.
- Kind: ruling

### RSV-086: A timeline that played perfectly reported dozens of clips Resolve "cannot find".
- Why: Remote editors hold no camera originals by design while proxies play, yet every absent original, even one with its proxy playing, was counted missing (50 to 57 clips).
- Must: A clip counts as missing only when neither its original nor a usable proxy that Resolve has not refused is on this computer.
- Kind: situation

### RSV-087: A Resolve change that did nothing was counted done, every two minutes.
- Why: A forced re-read reported success without happening, or its verdict was kept under another spelling of the path, so it repeated each pass and spent the daily automatic-change allowance.
- Must: An automatic Resolve change counts only if Resolve shows it took, and one that changes nothing is not tried again until the file changes.
- Kind: situation

### RSV-088: Refreshing a clip may drop the proxy it was playing.
- Why: Re-importing a clip that was playing its editing proxy may clear that attachment, leaving it on the original or offline; never confirmed on a live Resolve.
- Must: After any refresh, a clip that was playing a proxy is still playing it.
- Kind: situation

### RSV-089: Resolve being briefly busy or gone was treated as a final refusal.
- Why: A relink refused for a busy second was never asked again, Resolve closing mid-pass was remembered as refusing every remaining clip, yet real refusals were retried every 120 s (144,000 log lines a day).
- Must: A busy or absent Resolve leads to a later retry; a real refusal is not retried until the file or clip changes, and repeats are summarised.
- Kind: situation

### RSV-090: Relinks held back by a rate limit waited until the app restarted.
- Why: Automatic relinks refused because one ran under 15 minutes ago were kept in a list nothing drained, while the log promised a scan would apply them.
- Must: A Resolve relink postponed by a rate limit is retried by itself once the limit allows, without restart, and any remedy the product names really works.
- Kind: situation

### RSV-091: A misconfigured computer could rewrite Resolve projects unasked about 96 times a day.
- Why: The limit on unrequested project rewrites lived only in memory, so every restart or update re-armed it, with no daily cap.
- Must: Changes the product makes to a Resolve project unasked are capped per project per day across restarts and updates, and reaching the cap is reported as a setup problem.
- Kind: situation

### RSV-092: Pending relinks hammered Resolve over and over.
- Why: Each pending relink walked Resolve's whole media pool several times per pass, and 158 refused clips were re-offered every 3 seconds without de-duplication.
- Must: Pending relink work is de-duplicated, capped, and checked against Resolve at most once per pass, however many projects or clips wait.
- Kind: situation

### RSV-093: Background checks re-read whole media files over the network on a timer.
- Why: A length check decoded every archive clip every 120 s (about 100 GB per pass), and presence checks made thousands of network round trips every 3 to 120 s.
- Must: Repeating checks ask cheap questions first and remember each verdict until the file's size or date changes, while a real deletion still shows within the report window.
- Kind: situation

### RSV-094: Relinking 158 clips at once froze project tracking and quitting for over a minute.
- Why: Relinking a whole timeline's wrongly spelled clips, about half a second each, ran where the open project is tracked and quit is heard.
- Must: A large batch of Resolve fixes never blocks tracking which project is open, new detections, or a quit or update.
- Kind: situation

### RSV-096: Relinking 1,559 offline clips found several same-named candidates for many.
- Why: Moved media often has byte-identical backups on several drives, and full-resolution and proxy copies share names.
- Must: Candidates are ranked by longest matching path tail, then the root most other clips resolved to, then larger file, and ambiguous picks are shown first.
- Kind: situation

### RSV-097: The editor was offered a one-click relink into the product's own trash.
- Why: After a moved folder was set aside, its trash location was recorded as the move's destination and offered as where Resolve should look.
- Must: Resolve is never relinked, or offered a relink, to a place the product may delete.
- Kind: situation

See also, filed under another capability:

- PRX-089 (Proxies and file moves): Fixing a project would duplicate 100 GB that was already in the tree.

## Proxies in Resolve

### RSV-098: A clip's stored proxy path beats the proxy sitting beside the original.
- Why: Resolve stores a clip's proxy path apart from its file path; a stale path to another computer's drive overrides the adjacent Proxy folder (59 of 431 clips went offline).
- Must: A clip whose stored proxy path is dead here is repointed to the matching in-tree proxy (same rate, start timecode, frame count), in the shared spelling, copying nothing.
- Kind: given

### RSV-099: A clip imported into Resolve by script arrives with no proxy attached.
- Why: Resolve attaches a proxy from an adjacent Proxy folder when a person imports, but a scripted import skips that step.
- Must: After every import it performs, the product links the clip's proxy itself and checks it took, and a refused link never fails the import.
- Kind: given

### RSV-100: Resolve refuses a proxy whose timecode is missing or differs from its source.
- Why: Rewriting a 29.97 non-drop timecode as drop-frame made Resolve refuse 231 of 377 proxies; Resolve does read Sony's colon-written tag timecode as drop-frame.
- Must: Every proxy carries exactly the timecode its source's timecode track states; only a timecode held in a Sony tag alone is normalised.
- Kind: given

### RSV-101: Resolve pairs a proxy with its clip only by exact file name.
- Why: A proxy whose name differs from the original's by even one character is not attached, so the clip plays the original or goes offline.
- Must: A proxy always carries exactly the original's name, byte for byte, on every computer.
- Kind: given

### RSV-102: Older project proxies in MP4 were never attached, with no reason given.
- Why: A rule meant for b-roll previews refused every MP4 proxy, though older project proxies are valid MP4 files, and nothing told anyone why.
- Must: Valid older-format proxies are attached, and every proxy left unattached carries a reason the editor can see.
- Kind: situation

## Colour look-up tables (LUTs)

### RSV-126: Resolve scans its LUT folders once, at startup.
- Why: If the shared drive mounts moments after Resolve starts, its LUTs stay missing all session though the settings are right, and only LUTs a grade uses report errors.
- Must: When the LUT library was absent at Resolve's start and is reachable now, Resolve's LUT list is refreshed once without restarting Resolve or changing preferences.
- Kind: given

### RSV-127: Resolve loads DCTL files only from its own LUT folder.
- Why: DCTLs placed in an additional LUT location, such as a shared one, are never loaded.
- Must: The product never offers DCTLs through a shared extra LUT location as if Resolve would load them.
- Kind: given

### RSV-128: Resolve's own LUT folder holds factory LUTs that are not the editor's.
- Why: Resolve installs factory LUT packs; offering them as an editor's unshared LUTs, plus a version mismatch in sizes, made a permanent offer that copied nothing.
- Must: Only LUTs an editor added are offered to the shared LUT library, never Resolve's factory set, and an offer clears once acted on.
- Kind: given

### RSV-129: LUT packs unzipped from a Mac carry junk files with real LUT extensions.
- Why: Mac-made zips hold __MACOSX folders and "._" companion files of 176 B or 4 KB named like LUTs; a scan by extension would have copied about 139 junk files.
- Must: LUT sharing and every stray-file scan skip __MACOSX folders and files whose names start with "._".
- Kind: given

### RSV-130: One shared LUT library that every editor's Resolve reads directly.
- Why: Each editor's LUTs lived only on their own computer; the owner asked for one shared LUT folder on the NAS, kept in sync, with Resolve pointed straight at it.
- Must: Every editor receives the shared LUT folder without ticking anything, and Resolve on every computer lists the LUTs from it.
- Kind: ruling

### RSV-131: A LUT added outside the shared library prompts the editor to copy it in.
- Why: The owner wanted the editor asked, whenever they add a LUT that is not in the shared folder, whether to copy it there.
- Must: A LUT in Resolve's LUT locations but outside the shared library triggers an offer to copy it there; nothing is copied or moved unasked.
- Kind: ruling

## Fixing media: copying in, rehearsals and undo

### RSV-132: Resolve's own Undo does not cover clip relinks made by script.
- Why: Relinks made through scripting, some unprompted, cannot be undone in Resolve, and nothing else saved the project or kept the old paths.
- Must: Before any change to a Resolve project the product saves and exports the project and records the old paths, so every change can be undone.
- Kind: given

### RSV-133: The first read of a cloud-drive "online only" file blocks while it downloads.
- Why: Google Drive and OneDrive placeholders download as they are read (about 22 MB/s), so a copy stalled on one file, slowed itself for good, and one 8 MB read blocked cancel for seconds.
- Must: A copy says per file that its source is still downloading, can skip it, regains full speed once reads are fast, and answers cancel within two seconds.
- Kind: given

### RSV-134: A long media copy shows its progress and can be skipped, never hangs.
- Why: Fix-all hung then closed; another copy sat at "35/69" with no clue which file; the owner wanted file name, per-file and overall bars, skip, and cancel all.
- Must: A copy shows the current file name, per-file and overall progress, and offers skip this file and cancel all; only a person's click stops it.
- Kind: ruling

### RSV-135: A rehearsal of fixing media reported files copied, failed or uploading.
- Why: In rehearsal mode nothing is copied, yet results said "69 copied" or 69 failed, the bar showed 800 GB in two seconds or froze at 0%, and an upload could start.
- Must: The mode is visible before the click; a rehearsal says "Checking", moves by clips checked, says nothing was copied, starts nothing; a real run states how many it copied.
- Kind: situation

### RSV-136: Fixing many clips gave no size or space check and could die mid-copy.
- Why: Fix-all copied until the system drive was full, quitting killed a multi-GB copy unasked, and one button closed the window while copying continued.
- Must: Before copying, fix-all states size and free space and refuses without room; an unreadable or zero free-space reading drops that line; quitting mid-copy asks; the window stays until done.
- Kind: situation

### RSV-137: Fix-all rewrote 158 clips and the window just closed.
- Why: After copying files and rewriting paths in the editor's Resolve project, nothing summarised the result or said how to undo it.
- Must: After any batch change to a Resolve project, a summary gives fixed of total, size copied, failures with the first reason, and how to undo it.
- Kind: situation

### RSV-138: Retrying a clip fix copied a multi-gigabyte file all over again.
- Why: A retry made a second "(2)" copy, then uploaded it; fixing one source into a second project copied it twice; with no matched project the copy went where it never syncs.
- Must: A retry redoes only the step that failed and reuses a verified copy already made, copies go only where they will sync, and results state exactly what happened.
- Kind: situation

### RSV-139: A second click on fix-all started a second copy of the same batch.
- Why: The relink window's buttons stayed live during a run, so the natural second click started a duplicate copy.
- Must: Every action that moves media disables its buttons until it finishes, and re-enables them after.
- Kind: situation

### RSV-140: Undo of a path fix rewrote clips in a different project.
- Why: Undo replayed the newest change of any project, and a project name remembered for 20 seconds filed changes under the previously open project, repointing shared music and b-roll clips.
- Must: Every Resolve change is filed under the project open at that moment, and undo acts only on that project, refusing and naming it when another is open.
- Kind: situation

### RSV-141: An undo asked while Resolve was starting or had no project was failed for good.
- Why: "Resolve is starting up" and "no project open", Resolve's commonest state, were recorded as permanent failures and never retried.
- Must: A Resolve change waiting for Resolve to start or for its project to open is shown as waiting, and runs once that happens.
- Kind: situation

### RSV-142: An admin could not undo Resolve path changes on an editor's computer.
- Why: Undoing the product's clip relinks was only a click on the editor's own computer, with no way for an admin to trigger it.
- Must: An admin can ask any computer to undo a recorded Resolve change; it waits until that project is open, for up to a week, then reports failure.
- Kind: situation

### RSV-143: One fix needed several undos, and a repeat undo claimed success.
- Why: A long fix was recorded as several changes, one change had no record at all, and undoing one already undone reported success again.
- Must: Each press is undone by one undo restoring the exact earlier state or saying it cannot, a repeat says it is already undone, and relinks re-check each clip's path just before.
- Kind: situation

### RSV-144: Undo reported success though most fixes were never recorded.
- Why: Several path fixes made at once overwrote each other's undo records, keeping as few as 1 to 5 of 160, and undo then reported success.
- Must: Every Resolve change lands in the undo record even when many happen at once, a failure to record one is a visible warning, and undo names any clip not restored.
- Kind: situation

### RSV-145: Safety copies of Resolve projects piled up on the editor's disk for ever.
- Why: Whole-project safety copies, tens of megabytes, were written before automatic edits up to every 15 minutes, and they and half-written leftovers from crashes were never deleted.
- Must: Safety copies and leftovers from interrupted saves older than the stated retention, 60 days, are deleted, so their disk use stays bounded.
- Kind: situation

## Grading from the server's originals

### RSV-146: Grade from the server's full-quality originals, then switch back to proxies.
- Why: The owner wanted a remote colourist to "momentarily swap to a direct map of the server" to view originals while grading, then click back.
- Must: Any editor can switch their project drive to the server's originals and back again in one action, with no relinking and syncing unaffected.
- Kind: ruling

### RSV-147: A remote editor needs one frame of a camera raw original in Resolve to grade.
- Why: The owner: "what I really need is just the ability for a remote editor to see one frame in resolve of the camera raw original that's on the server".
- Must: A remote editor can bring one frame of a raw original from the NAS into Resolve and change its raw settings, without downloading the whole clip.
- Kind: ruling

### RSV-148: The first switch to server originals left everything offline and proxies grey.
- Why: The switch briefly unmaps the project drive; it needed a NAS login nothing asked for, so it failed, Resolve lost everything, and warnings mid-switch read as a broken setup.
- Must: A needed login is asked once per computer and remembered, drive warnings stay silent mid-switch, and a failed switch leaves the drive exactly as before.
- Kind: situation

## Other givens on the editor's computer

### RSV-149: Resolve holds graphics memory that grows over a session, starving other players.
- Why: On a 10 GB card an idle Resolve held 6.2 GB plus 6.7 GB spilled to system memory; the driver falls back silently, so 6K raw playback stutters rather than fails.
- Must: The product's own graphics work yields to Resolve while it is open, and playback diagnostics check Resolve's graphics memory before blaming the network or file.
- Kind: given

### RSV-152: A refusal's reason was cut off before the part naming what to close.
- Why: The sentence naming the other program holding Resolve was cut at 255 characters on the way to the dashboard, so the admin saw advice but not the program.
- Must: A refusal shown to an admin leads with the actionable part, and any length limit shortens it deliberately in the middle, never silently mid-word.
- Kind: situation
