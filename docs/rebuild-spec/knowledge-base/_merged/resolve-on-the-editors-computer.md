# DaVinci Resolve on the editor's computer

## Connecting to Resolve's scripting: launch, stalls and death

### RSV-001: Connecting during Resolve's launch hangs it and kills scripting for the session.
- What was going on: Resolve's script server (fuscript, port 1144) starts 90-470 s into launch; any client connecting before Resolve registers with it ends scripting for every program until Resolve restarts.
- What the product must do: Nothing on the computer, helpers included, connects until the script server is listening and Resolve itself is connected to it; only an unreadable check may connect anyway.
- Kind: 1a
- From: C04-051, C02-072, M02-002, L01-083, G01-001, P07-001, P04-010, H07-138

### RSV-002: A connect attempt with no script server present blocks about four seconds.
- What was going on: The connect call retries about 4 s (8 s behind a second thread) instead of failing, so a "quick check" is mid-connect when the server appears; a fixed wait after launch misses the window.
- What the product must do: Readiness is judged from the script server and Resolve's connection to it, never from a delay after Resolve starts, and no check ever attempts a connection to find out.
- Kind: 1a
- From: L04-048, P07-002, G01-002

### RSV-003: Resolve's script server, if it fails at launch, never retries that session.
- What was going on: Resolve then looks normal on screen while every scripted action is silently lost; only quitting and reopening Resolve brings scripting back.
- What the product must do: The product tells "Resolve is closed" apart from "Resolve is open but not accepting scripting", and names restarting Resolve as the fix for the second.
- Kind: 1a
- From: C01-064, P04-009

### RSV-004: A client still connected to a closed Resolve breaks scripting in later sessions.
- What was going on: A long-running client keeping its connection after Resolve quits wedges scripting in every new Resolve session for all programs, until that client is stopped before Resolve restarts.
- What the product must do: When Resolve exits every connection to it is dropped, and recovery advice says: close the app, close Resolve, start the app, start Resolve.
- Kind: 1a
- From: M05-067, P05-018, L03-076

### RSV-005: Resolve answers scripting calls one at a time, so one slow client stalls all others.
- What was going on: All properties of a clip cost 12.5 ms, one property 0.1 ms; a 904-clip walk held Resolve 11-95 s, turning another program's 0.3 s click into 7 s, and froze Resolve.
- What the product must do: No program of the product holds Resolve's scripting for more than half a second at a time, and every read asks only for the properties it needs.
- Kind: 1a
- From: L03-036, G01-003, P07-061, M04-021, D02-031, P01-012

### RSV-006: Reading every clip's details from Resolve took about 90 seconds.
- What was going on: Asking Resolve for each clip's properties on a project of about 1,300 clips took about 90 s, and 1,300 clips is a normal project here.
- What the product must do: Any whole-project scan shows progress, keeps the product usable throughout, and treats a 1,300-clip project as normal size.
- Kind: 1a
- From: P01-026

### RSV-007: Sweeping Resolve's media pool by script stalls Resolve's own interface.
- What was going on: Asking every clip's proxy state took about 5.5 s per 1,298 clips, each new scripting connection about 75 ms, and a once-a-second 1,350-call sweep ran during playback.
- What the product must do: Background work never sweeps Resolve's whole media pool or timeline on a timer when nothing changed, and asks Resolve nothing during playback.
- Kind: 1a
- State: still open
- From: H08-062

### RSV-008: A single Resolve call can block for seconds, minutes or indefinitely.
- What was going on: A call lasts as long as Resolve's main thread takes: milliseconds idle, seconds in playback, render or a big project, indefinitely behind a modal dialog, the Project Manager or a dropped share.
- What the product must do: No Resolve call blocks the tray, a window, other features or quitting; each call has a deadline after which it is reported and abandoned.
- Kind: 1a
- State: still open
- From: P02-040, L01-088, H01-014

### RSV-009: A Resolve call hung twenty minutes while Resolve still read as connected.
- What was going on: Importing media from a share that had gone away hung a scripting call for twenty minutes or more, while the status still showed Resolve connected in green.
- What the product must do: When any Resolve call has run over 20 s, the status shows "Resolve: not answering for N s" in amber, never connected.
- Kind: 1a
- From: L04-096

### RSV-010: Resolve's scripting went dead for hours with nothing logged.
- What was going on: Scripting died at 00:20 and stayed dead until Resolve was relaunched at 08:00, and no client recorded a cause.
- What the product must do: When Resolve stops answering, the product says so plainly and tells the person Resolve must be relaunched.
- Kind: 1a
- State: outcome not found
- From: D02-035

### RSV-011: Any open Resolve dialog makes its scripting answer nothing, for every program.
- What was going on: An "Audio Output: device not found" box (speaker unplugged, or "Remote Audio" after Remote Desktop) appears on project load; until clicked, calls return nothing and queued renders sit at Ready.
- What the product must do: Empty answers mean "Resolve cannot answer now", never missing data; nothing is written meanwhile, the person is told to check Resolve for an open box, and renders are confirmed started.
- Kind: 1a
- From: D02-014, M02-053, P14-025, L08-051, M01-017, P08-040

### RSV-012: Opening projects by script stops on Resolve's own dialogs.
- What was going on: Resolve halted on a "save current project" box and an audio output box, then sat on "loading" a project until someone clicked.
- What the product must do: Automated work in Resolve notices a blocking dialog or a stalled project load and tells the person, instead of waiting forever.
- Kind: 1a
- From: P15-008

### RSV-013: After a forced restart Resolve showed a "save current project" box that would not close.
- What was going on: A forced close and automatic restart of Resolve brought up a save dialog for an unknown project that could not be dismissed.
- What the product must do: The product never force-closes Resolve without first saving or closing the open project, and checks Resolve is usable after a restart.
- Kind: 1a
- State: outcome not found
- From: P01-037

### RSV-014: Resolve's scripting returns nothing with no project or only "Untitled Project" open.
- What was going on: On the Project Manager connecting returns nothing; on the placeholder "Untitled Project" it connects but load, create, page and library calls return nothing; calls were seen stalling 120 s.
- What the product must do: With Resolve open and no real project loaded, the product says so and asks for a project, never hangs or claims Resolve is closed.
- Kind: 1a
- From: M05-045, P03-043

### RSV-015: Resolve's scripting goes dead while the Remote Desktop session is disconnected.
- What was going on: With the Windows session disconnected, load, save and page calls return nothing; one such Resolve stopped responding and crashed about 30 minutes later.
- What the product must do: A disconnected desktop session on the Resolve computer is detected and the person told to reconnect, instead of attempting Resolve work.
- Kind: 1a
- From: M04-020

### RSV-016: Resolve crashes after about 13 minutes of continuous scripted work.
- What was going on: A run exporting 57 projects one after another crashed Resolve after about 13 minutes, each export taking well under a minute.
- What the product must do: Long scripted work records progress per item, survives Resolve crashing or hanging, resumes without redoing finished items, and verifies each output exists at the right size.
- Kind: 1a
- From: M05-049, P03-041

### RSV-017: Two simultaneous calls into Resolve's scripting can crash the calling program.
- What was going on: Resolve's scripting library is not safe to call from two threads at once; a concurrent call crashed the editor app with an access violation and nothing logged.
- What the product must do: The editor app never has two calls into Resolve's scripting in flight at once, including small lookups made after a relink.
- Kind: 1a
- From: H03-005

### RSV-018: Resolve's scripting objects accept any method name and fail only when called.
- What was going on: A save called on the project object passed every check because the object claims any method; the save belongs to the project manager, and fake tests never caught it.
- What the product must do: Every Resolve scripting call the product uses is checked once against a real Resolve before it ships.
- Kind: 1a
- From: D01-043

### RSV-019: On a Mac every Resolve feature was silently dead.
- What was going on: On macOS Resolve's scripting modules sit under a Developer folder in its support folder; a wrong location meant no connection, noted only at debug level.
- What the product must do: When Resolve's scripting cannot be reached, the person is told in plain words, never only in a debug log line.
- Kind: 1a
- From: C01-058

### RSV-020: Blackmagic Proxy Generator runs as the Resolve program itself.
- What was going on: The proxy generator is the Resolve program started with a "-pg" switch, so a process check reads it as Resolve running.
- What the product must do: Detecting Resolve ignores a Resolve process started with the proxy generator switch.
- Kind: 1a
- State: still open
- From: L01-085

### RSV-021: Warn every five minutes while Resolve runs without working scripting.
- What was going on: Resolve looks normal while every insert and fix is silently lost; the owner asked for a popup "every five minutes" telling the editor to restart Resolve.
- What the product must do: While Resolve is confirmed running and scripting is unavailable, a warning repeats every five minutes, the first after one full interval, and stops on recovery.
- Kind: 2
- From: P05-019

### RSV-022: Editors were told scripting was dead while Resolve was only starting or quitting.
- What was going on: The script server appears 90-470 s after launch and Resolve lingers as a process after quitting, so "no server" is normal for minutes.
- What the product must do: For ten minutes after Resolve launches or quits the product shows a neutral "starting up or shutting down", and dead-scripting advice leads with "quit and reopen Resolve".
- Kind: 3
- From: C02-073, L01-084, P07-003

### RSV-023: A computer that had never connected was told "quit and reopen Resolve" for ever.
- What was going on: Restarting Resolve cannot fix scripting that was never switched on, and the product forgot across its own restarts that this computer had never connected.
- What the product must do: A computer that has never connected to Resolve gets setup advice, not restart advice, and that knowledge survives restarts of both programs.
- Kind: 3
- State: fixed, never shipped
- From: L11-047

### RSV-024: The log claimed scripting was ready when Resolve had gone or nothing was seen.
- What was going on: Resolve quitting mid-launch, or a connection table that could not be read, was logged with the same line as Resolve registering, misleading anyone diagnosing a hung launch.
- What the product must do: The log says "Resolve went away, nothing connected" or "could not tell, connected anyway" when so, and says "registered" only when registration was seen.
- Kind: 3
- From: H05-049, L06-005, L07-010

### RSV-025: Checking whether Resolve is running must cost almost nothing.
- What was going on: Each check started an operating-system process listing (202 ms), 230 to 1,100 times an hour, and b-roll ingest checked before every frame.
- What the product must do: An idle computer starts no helper processes to learn whether Resolve is running, and one answer serves every part of the product.
- Kind: 3
- State: fixed, never shipped
- From: H08-063

### RSV-026: Two programs on one computer talking to Resolve endanger its scripting.
- What was going on: A second Resolve client on the same computer risks scripting for the whole session and queues behind or ahead of the first for Resolve's one-at-a-time answers.
- What the product must do: One program per computer talks to Resolve, holding it only during calls, never while computing; another found running is named and left alone, and "cannot tell" counts as running.
- Kind: 3
- From: C03-033, D01-057

### RSV-027: A check for a competing Resolve client mistook unrelated programs and stayed refused.
- What was going on: It matched any command line containing certain words, including an operator's shell, and was run again only at the next app start.
- What the product must do: The check identifies only a real competing Resolve client, names it, and re-checks by itself without an app restart.
- Kind: 3
- State: outcome not found
- From: M03-060

### RSV-028: A failed start left extra Resolve workers running, one more every minute.
- What was going on: A start that failed after its Resolve worker began left it running, each retry added another, and a restarted stuck worker later ran beside its replacement, both changing the project.
- What the product must do: A failed start stops what it began, retries stop after five failures and say so, a stuck worker is reported rather than duplicated, and one computer never runs two.
- Kind: 3
- From: L06-003, L08-080

### RSV-029: A dead background helper kept reporting itself as running.
- What was going on: The restart check counted helpers started rather than alive, so a dead one was never restarted and the editor's phone page stayed dead.
- What the product must do: A helper whose work has stopped is restarted within a minute, judged by whether it is actually alive.
- Kind: 3
- From: L06-002

### RSV-030: A scheduled per-project Resolve export must wait for Resolve to finish launching.
- What was going on: A per-project export needs a running Resolve, and a scheduled job connecting during Resolve's launch would kill scripting for every program on that computer.
- What the product must do: Scheduled Resolve exports connect only after Resolve has fully registered with its script server, never during launch.
- Kind: 3
- State: still open
- From: D07-107

### RSV-031: Resolve crashed instantly on launch on the studio's main computer.
- What was going on: The owner reported Resolve crashing at launch on the main computer; no cause was found.
- What the product must do: Nothing on an editor's computer contacts Resolve before its launch completes, and Resolve launch failures are logged for diagnosis.
- Kind: 3
- State: outcome not found
- From: P10-071

## Setting Resolve up: edition, scripting switch, preferences

### RSV-032: Resolve's external scripting is off by default and absent from the free edition.
- What was going on: Only Resolve Studio has external scripting; it needs Preferences, System, General, "External scripting using" set to Local (default None), and the project library added.
- What the product must do: Setup detects edition and setting, sets Local or names exactly what to change or that Studio is needed, and says done only after a real connection.
- Kind: 1a
- State: fixed, never shipped
- From: H07-079, M05-038, L04-073, L11-044

### RSV-033: A dongle-licensed Resolve Studio has no licence file, like the free edition.
- What was going on: A Studio licence file proves Studio, but a dongle install has none, so a missing licence file does not mean the free edition.
- What the product must do: A found Studio licence counts as proof of Studio, and no editor is told they have the free edition because a licence file is missing.
- Kind: 1a
- State: fixed, never shipped
- From: L11-046

### RSV-034: Resolve installed on another drive stopped the app from reaching it.
- What was going on: On a remote editor's computer with Resolve on drive F: and scripting set to network, the app could not reach Resolve until the location was dealt with.
- What the product must do: The product reaches Resolve wherever it is installed, or says in plain words that it cannot find Resolve and where it looked.
- Kind: 1a
- State: outcome not found
- From: P02-020

### RSV-035: Driving Resolve from another computer needs its network scripting switch, never tested.
- What was going on: It needs Resolve's "External scripting: Network" preference, which opens Resolve's scripting port to the network; the owner has not approved that.
- What the product must do: Nothing relies on network scripting until tested, and if used, the port is reachable only from the studio's own computers.
- Kind: 1a
- State: still open
- From: D06-027

### RSV-036: Resolve discards preference changes made while it is running.
- What was going on: Resolve holds its preferences in memory and rewrites its preference files on quit, so outside edits made meanwhile vanish; LUT locations have no scripting interface.
- What the product must do: Resolve's preferences change only while it is closed; setup asks the editor to quit, waits up to 180 s, continues by itself, and checks the change survived the next start.
- Kind: 1a
- From: C01-060, P04-008, H02-027

### RSV-037: Resolve's first run regenerates its whole configuration when no preferences exist.
- What was going on: Preferences written before Resolve has ever run on a computer are thrown away when it first starts.
- What the product must do: Where no Resolve preferences exist yet, the editor is asked to launch and quit Resolve once before any preference is changed.
- Kind: 1a
- From: G01-016

### RSV-038: Resolve warned at every launch that the stills location differed between computers.
- What was going on: Resolve derives its stills gallery folder from the first numbered media storage entry, normally each computer's own scratch disk; the render cache also refers to entry one by number.
- What the product must do: Every computer sharing a project library uses one shared stills location, the first media storage entry never moves, and nothing changes until the shared folder exists.
- Kind: 1a
- From: C01-062, P04-007

### RSV-039: Resolve collaboration failed for editors connecting from outside the studio.
- What was going on: Collaborators connect peer to peer at the address the project database saw; remote editors arriving through address translation registered an address nobody could reach.
- What the product must do: Every collaborator's Resolve registers an address all other collaborators can reach, whether on the studio network or remote.
- Kind: 1a
- From: P02-056

### RSV-040: Resolve registers the selected library entry's address as its collaboration address.
- What was going on: A second library entry for the same server re-registered an unreachable address, and Resolve rewrites its library list when it exits.
- What the product must do: Library entries are written only while Resolve is closed, one per library, each using the address every editor can reach.
- Kind: 1a
- From: M05-051

### RSV-041: Setup must cope with Resolve Free, scripting off, older Resolve and non-English Windows.
- What was going on: Setup had never been tried on those, nor on security-locked Windows.
- What the product must do: On each, setup completes or names exactly what the editor must change, and syncing keeps working without Resolve's scripting.
- Kind: 3
- State: outcome not found
- From: H08-018

## Project libraries and projects

### RSV-042: Resolve freezes about five seconds per unreachable remote project library at launch.
- What was going on: Resolve tries every listed remote library in turn on its splash; Windows marks it Not Responding and editors force-quit, thinking it will not start.
- What the product must do: When the shared project library is unreachable, the editor is told the network to it is down before or as Resolve opens.
- Kind: 1a
- From: M05-052, P05-022

### RSV-043: Resolve launched before the network keeps network project libraries offline.
- What was going on: After a reboot Resolve started before the private network was up, timed out on every network library and kept them offline until relaunched.
- What the product must do: The editor is warned when Resolve started before its project library's network was up, and told to relaunch Resolve.
- Kind: 1a
- From: M04-104

### RSV-044: Resolve 21 does not say which project library is open.
- What was going on: In Resolve 21 the current-library and library-list calls return nothing (they worked in 20); with Live Save off, the library holds nothing newer than the last save.
- What the product must do: The product finds the open project library without those calls, shows the person which one it found, and never treats the library as holding unsaved work.
- Kind: 1a
- From: M04-024, G01-007

### RSV-045: Two Resolve projects can share a name.
- What was going on: Same-named projects can sit in different project-manager folders, and finding a project by name took the first match, using the wrong project's media.
- What the product must do: A Resolve project is identified by its name together with its folder; if still ambiguous the product refuses or asks, never picks.
- Kind: 1a
- From: H07-065, H06-040

### RSV-046: Resolve names differing only by case overwrote each other's files on Windows.
- What was going on: Resolve project and clip names are case-sensitive and Windows file names are not; one export silently replaced the other and both reported done.
- What the product must do: Names differing only by case stay distinct everywhere, files written from them never collide, and every export is verified present at the right size.
- Kind: 1a
- From: P03-042, M05-028

### RSV-047: A dump of Resolve's project server restores straight from Project Manager.
- What was going on: Resolve's project libraries live in a database server; a dump in the format of Resolve's own Backup restores in Project Manager; six libraries came to 144 MB.
- What the product must do: Every Resolve project library is backed up nightly, checked readable, kept 30 days, in a form Resolve's Project Manager can restore.
- Kind: 1a
- From: D07-104

### RSV-048: Resolve can be open while refusing scripting, and its last save stays readable.
- What was going on: With scripting refusing, the timeline and transcripts as of Resolve's last save were still in the project library, so work could continue.
- What the product must do: With Resolve closed or refusing scripting, the editor still shows the timeline as of Resolve's last save and says plainly it is not live.
- Kind: 1a
- From: D06-019

### RSV-049: Resolve project tiles showed the Resolve logo instead of a picture.
- What was going on: Resolve samples five frames from the current timeline on close; gaps, black or undecodable media leave the shown slot empty.
- What the product must do: Projects the product creates or closes are left on a timeline with picture, so their tile shows a frame.
- Kind: 1a
- From: M05-056

### RSV-050: In a locked project Resolve refuses to make a bin and says nothing.
- What was going on: Creating a bin in a locked or collaboration project returns nothing instead of an error, so the editor was wrongly told to open a project.
- What the product must do: When Resolve will not create a bin, the editor is told the project looks locked, not given a generic "open a project" error.
- Kind: 1a
- From: H01-056

### RSV-051: Resolve regenerated every audio waveform at each launch.
- What was going on: The owner's Resolve opened synced projects with waveforms missing and rebuilt them every time; he wanted them kept with the project on the NAS.
- What the product must do: Opening a synced project shows its audio waveforms without waiting for them to regenerate on each launch.
- Kind: 1a
- State: outcome not found
- From: P04-075

## Knowing which project is open

### RSV-052: Resolve's scratch projects look open though nobody is working in them.
- What was going on: Blackmagic Proxy Generator runs a helper project "New Doc", every unsaved project is "Untitled Project", and Resolve numbers copies ("New Doc 1", "Untitled Project (3)").
- What the product must do: These names and numbered copies never trigger prompts, matches or dashboard reports; an editor in "Untitled Project" is told to save under a real name to be asked.
- Kind: 1a
- From: M02-030, C01-007, P02-008, P14-038

### RSV-053: A Resolve project is linked to a project folder only on an exact name match.
- What was going on: Linking on a partial name overlap was silent and permanent; the owner: auto-linking into a non-matching project "is not useful behaviour".
- What the product must do: A Resolve project links automatically only when its name exactly matches one project folder's name; anything else, or an unreadable tree, asks the editor.
- Kind: 2
- State: fixed, never shipped
- From: L11-060

### RSV-054: Opening an unknown Resolve project asks once whether to set it up.
- What was going on: The owner wanted a prompt when a never-seen project opens, leading to picking or creating its server folder; once he got no prompt in a new project.
- What the product must do: The first time a person opens an unlinked Resolve project they are asked once to set it up, then can pick or create its server folder.
- Kind: 2
- From: P02-004

### RSV-055: Switching Resolve projects mid-check copied files into the wrong project.
- What was going on: A check taken in one project was acted on after the editor switched; 23 music files went into the wrong project's folder and all 23 relinks failed.
- What the product must do: Before showing or acting on any scan or fix row, the product confirms that same Resolve project is still open; if not, it refuses and names the project.
- Kind: 3
- From: L10-079, P13-008, M02-026

### RSV-056: The fix list pointed clips at another project's folder and ran off screen.
- What was going on: In one project the fix list proposed moving clips into a different project's folder, showed empty rows, sat off the top of the screen and could not scroll.
- What the product must do: Fix suggestions target only the open project's folder, empty rows never appear, and the window fits the screen and scrolls.
- Kind: 3
- State: outcome not found
- From: P02-014

### RSV-057: The out-of-project prompt went quiet until Resolve was restarted.
- What was going on: On a laptop a clip outside the project folder raised no prompt until Resolve was restarted, suggesting the product's view of Resolve had gone stale.
- What the product must do: The out-of-project check keeps working for a whole Resolve session, and if it loses Resolve it says so instead of going quiet.
- Kind: 3
- State: outcome not found
- From: P02-058

## Clip paths and media outside the shared tree

### RSV-058: Resolve stores a clip's path exactly as it was browsed.
- What was going on: Importing the shared tree through another drive letter or from a Desktop plays locally but is offline on every other computer; one shared project had over 200 such clips, unwarned.
- What the product must do: Every clip imported from inside the tree, by any spelling, ends up stored in the shared spelling automatically, and a clip on a computer-private path is flagged to its importer.
- Kind: 1a
- From: H01-050, M05-031, P05-017, L03-075

### RSV-059: Every computer sees the project tree at the same drive and path.
- What was going on: The base computer used one drive letter and editors another, so Resolve projects shared between them could never link; the base was moved to match.
- What the product must do: Every computer, base included, opens the project tree at the identical drive and path, so a Resolve project links the same everywhere.
- Kind: 2
- From: P02-028

### RSV-060: Media used from outside the project folder raises a warning naming the project.
- What was going on: The owner wanted a popup to move such media "to where it is syncable", and: "this warning should say which project", since it may be an editor's personal project.
- What the product must do: The warning names the clip, the Resolve project and where to move it, and a project that is not one of the studio's synced projects raises nothing.
- Kind: 2
- From: P01-046, C03-063

### RSV-061: On the base computer only media outside the project's own server folder is flagged.
- What was going on: The base got out-of-project popups for media already on the server; careless base work can also leave clips outside, so the owner wanted it narrowed, not removed.
- What the product must do: On the base computer the out-of-project popup lists only clips outside that project's own server folder, never clips already inside it.
- Kind: 2
- From: P02-013

### RSV-062: A reminder about missing or outside media can be skipped for 30 minutes only.
- What was going on: A folder skipped "always" hid 30 music files added a day later; "skip for now" lasted six days. The owner: "it should constantly bother people until they do it".
- What the product must do: There is no permanent or per-folder dismiss; a skip lasts 30 minutes, pressing it again never extends that, the button says so, and anything new is always offered.
- Kind: 2
- From: P16-048, L11-064, C04-034, L10-076, P13-007

### RSV-063: A clip fixed on a laptop opened offline on every other computer.
- What was going on: The fix relinked clips to the laptop's physical disk; the Resolve project travels between computers but drive layouts do not.
- What the product must do: Every path the product writes into a Resolve project is the shared project-drive spelling, never one computer's physical disk.
- Kind: 3
- From: P02-030, C01-030

### RSV-064: Clips at the right shared path kept being flagged as offline.
- What was going on: Clips relinked to the shared drive path were judged misplaced on the laptop, so the popup kept returning though the files opened fine.
- What the product must do: A clip whose file exists at its shared project-drive path is never flagged, offered for fixing or warned about again.
- Kind: 3
- From: P02-031

### RSV-065: Clips on one editor's Desktop went unnoticed in a project nobody opened.
- What was going on: 45 music clips in a shared project pointed at one editor's Desktop for over a week, because only the project currently open in Resolve was checked.
- What the product must do: Every 30 minutes every project in every library the computer can read is checked for media outside the tree, and its editor and the dashboard are told, naming project and count.
- Kind: 3
- From: C04-035, P16-049, L11-065

### RSV-066: Skipped clips stayed hidden, uncounted, even from a whole-project scan.
- What was going on: "Ignore all" or skip hid clips for the session with no total, and a full project scan honoured the skip too.
- What the product must do: Skipped clips are counted and shown as still not syncing, a whole-project scan re-offers them, and an automatic skip is recorded apart from an editor's.
- Kind: 3
- From: L03-012, H07-142

### RSV-067: Clips found while an editor read a popup were silently dropped.
- What was going on: A batch found while one popup was open was discarded behind an "already open" notice re-fired every 3 seconds.
- What the product must do: Later batches queue and show when the current popup closes, deduplicated so the same clips never produce repeated dialogs.
- Kind: 3
- From: C01-038

### RSV-068: A 300-clip project on an unmapped drive raised 300 identical notifications.
- What was going on: The missing-drive warning fired once per clip path; on a Mac each was a slow system notification that also held up watching Resolve.
- What the product must do: One problem raises one notice per episode, however many clips it touches, re-armed only after it has cleared and broken again.
- Kind: 3
- From: H03-007, L01-040

### RSV-069: The broken drive mapping warning wrongly said nothing would sync.
- What was going on: When the media drive letter stopped pointing at the synced folder only Resolve's view broke, yet the warning said all syncing had stopped and offered no repair.
- What the product must do: The warning says clips will show offline while transfers continue, offers a repair on Windows, and refuses to remove a mapping the product did not create.
- Kind: 3
- From: L03-014

### RSV-070: An editor with 40 dead links in Resolve saw no number anywhere.
- What was going on: Counts of missing clips, clips outside the tree and unattached proxies were computed but shown only in diagnostics, never to the editor or the admin.
- What the product must do: The editor and the dashboard see those counts per computer with when they were checked; before any check finishes it reads "not checked yet", never zero.
- Kind: 3
- From: L04-097, L03-013

### RSV-071: A pass that refreshed forty clips said "nothing to do".
- What was going on: Clips re-read after their file changed were counted nowhere people look, so every surface said "attached: 0" and the pass looked idle.
- What the product must do: Every count of Resolve changes shown to editors and admins includes clips re-read after their file changed.
- Kind: 3
- From: L08-064

### RSV-072: Music in .aac files was filed as b-roll footage.
- What was going on: The list of audio file types lacked .aac and .opus, so licensed music gathered from outside the tree went to the b-roll folder instead of the music folder.
- What the product must do: .aac and .opus files are treated as audio and filed with music, like .wav and .mp3.
- Kind: 3
- From: L10-080

## Missing clips, relinking and refreshing

### RSV-073: Resolve silently refuses to create or relink a clip at a path it cannot open.
- What was going on: Linking, replacing or importing at a missing path just answers false, with no error.
- What the product must do: A clip is placed or relinked only where a real file exists, and an absent original gets a stand-in file at its real path first.
- Kind: 1a
- From: C03-032

### RSV-074: Resolve does not re-read a file swapped under an existing clip.
- What was going on: When a clip's file is replaced (a preview by the real original), Resolve keeps the old length and resolution, even after reopening, until the clip is replaced with that same path.
- What the product must do: After a clip's file changes, Resolve shows the new file's length and resolution before proxies are linked, and success is judged by those changing, never by the path.
- Kind: 1a
- From: L08-049, M01-016

### RSV-075: Resolve's replace-clip call returns nothing even when it works.
- What was going on: The call gives no value whether or not it succeeded, so every successful relink had been logged as a failure.
- What the product must do: Every relink is verified by re-reading the clip's file path, with retries, before its outcome is reported.
- Kind: 1a
- From: C01-099, L03-074

### RSV-076: In a shared project Resolve applies relinks seconds to minutes later.
- What was going on: In a collaborative project replace, relink and proxy-link calls return no result and take effect seconds to minutes later, reaching other open sessions without reopening.
- What the product must do: Success is judged by re-reading the clip's paths after a wait, and a retry happens only after that re-read.
- Kind: 1a
- From: M05-032

### RSV-077: Resolve's clip replace can fail on some tries and succeed on others.
- What was going on: Mid-render or in a scripting hiccup some attempts raise errors; treating the surviving "nothing changed" answer as final disabled the repair for that clip.
- What the product must do: A repair attempt during which Resolve raised any error is retried on the next pass, never remembered as settled.
- Kind: 1a
- From: L09-061

### RSV-078: Resolve cannot relink subtitle clips.
- What was going on: Resolve's replace call fails for subtitle (.srt) items in the media pool; they can only be imported again.
- What the product must do: A relink that meets a subtitle clip re-imports it from the new place or names it to the person, and never counts it as fixed.
- Kind: 1a
- From: P03-003, M02-029

### RSV-079: Resolve reports an image sequence by a bracketed path that never exists on disk.
- What was going on: Resolve keeps a sequence as "Name_[00000-00287].exr" even after relinking, so every sequence looked offline; replacing with the first frame relinks the whole sequence.
- What the product must do: An image-sequence clip counts as online when its first frame exists, and is relinked by pointing at that first frame.
- Kind: 1a
- From: M05-060, P01-011

### RSV-080: Resolve's media pool can show a relinked clip offline until the bin changes.
- What was going on: After a scripted relink some clips showed offline in the media pool though fine on the timeline; going to another bin and back cleared it.
- What the product must do: After relinking, the product checks each clip's status itself rather than trusting the media pool's display, and tells the person a bin switch refreshes it.
- Kind: 1a
- From: P02-032

### RSV-081: Resolve holds its media files open, so they cannot be moved or deleted.
- What was going on: On Windows a file used in an open project, including a NAS proxy a wired computer is playing, refuses rename, move or delete until the project closes or Resolve quits.
- What the product must do: Every move, rename, replace or delete of media expects Resolve may hold it, retries later, reports what stayed, and tells the editor closing Resolve will let it finish.
- Kind: 1a
- From: L02-034, L03-001

### RSV-082: Resolve crashed opening a project whose clip was relinked to a shortcut file.
- What was going on: A relink picked a Windows shortcut (.lnk) with the clip's name; Resolve then crashed opening that project until the shortcut was deleted.
- What the product must do: Relinking never links or offers a shortcut or any file that is not playable media of the clip's kind.
- Kind: 1a
- State: outcome not found
- From: P01-007

### RSV-083: Resolve rejects hand-edited project and timeline interchange files.
- What was going on: Resolve's exported project keeps clip paths in an opaque block, and a hand-written FCPXML is not accepted at all, so repointing clips by editing such files fails.
- What the product must do: Any way of changing where clips point is proven on a real Resolve before it is relied on.
- Kind: 1a
- From: L08-052

### RSV-084: Render In Place files exist only on the computer that rendered them.
- What was going on: A re-synced project lost all 175 Render In Place clips: they pointed at empty folders elsewhere, and after a re-rooting the renders were nowhere on any disk.
- What the product must do: Render In Place files in a synced project reach the NAS like other media, or the editor is told which clips will be offline elsewhere before media moves.
- Kind: 1a
- From: M05-001, P03-005

### RSV-085: The owner wanted a quick relink of only the open timeline.
- What was going on: Relinking a whole project takes long; the owner asked "to only relink the active timeline if you're in a hurry".
- What the product must do: Relink offers a scope of just the active timeline's clips, besides the whole project.
- Kind: 2
- State: outcome not found
- From: P03-004

### RSV-086: A timeline that played perfectly reported dozens of clips Resolve "cannot find".
- What was going on: Remote editors hold no camera originals by design while proxies play, yet every absent original, even one with its proxy playing, was counted missing (50 to 57 clips).
- What the product must do: A clip counts as missing only when neither its original nor a usable proxy that Resolve has not refused is on this computer.
- Kind: 3
- From: P12-013, L10-036, C04-020

### RSV-087: A Resolve change that did nothing was counted done, every two minutes.
- What was going on: A forced re-read reported success without happening, or its verdict was kept under another spelling of the path, so it repeated each pass and spent the daily automatic-change allowance.
- What the product must do: An automatic Resolve change counts only if Resolve shows it took, and one that changes nothing is not tried again until the file changes.
- Kind: 3
- From: H06-036, L08-063

### RSV-088: Refreshing a clip may drop the proxy it was playing.
- What was going on: Re-importing a clip that was playing its editing proxy may clear that attachment, leaving it on the original or offline; never confirmed on a live Resolve.
- What the product must do: After any refresh, a clip that was playing a proxy is still playing it.
- Kind: 3
- From: L08-065

### RSV-089: Resolve being briefly busy or gone was treated as a final refusal.
- What was going on: A relink refused for a busy second was never asked again, Resolve closing mid-pass was remembered as refusing every remaining clip, yet real refusals were retried every 120 s (144,000 log lines a day).
- What the product must do: A busy or absent Resolve leads to a later retry; a real refusal is not retried until the file or clip changes, and repeats are summarised.
- Kind: 3
- From: L04-107, H01-054, H04-075

### RSV-090: Relinks held back by a rate limit waited until the app restarted.
- What was going on: Automatic relinks refused because one ran under 15 minutes ago were kept in a list nothing drained, while the log promised a scan would apply them.
- What the product must do: A Resolve relink postponed by a rate limit is retried by itself once the limit allows, without restart, and any remedy the product names really works.
- Kind: 3
- From: L07-008, H03-003

### RSV-091: A misconfigured computer could rewrite Resolve projects unasked about 96 times a day.
- What was going on: The limit on unrequested project rewrites lived only in memory, so every restart or update re-armed it, with no daily cap.
- What the product must do: Changes the product makes to a Resolve project unasked are capped per project per day across restarts and updates, and reaching the cap is reported as a setup problem.
- Kind: 3
- From: H07-139, L02-016

### RSV-092: Pending relinks hammered Resolve over and over.
- What was going on: Each pending relink walked Resolve's whole media pool several times per pass, and 158 refused clips were re-offered every 3 seconds without de-duplication.
- What the product must do: Pending relink work is de-duplicated, capped, and checked against Resolve at most once per pass, however many projects or clips wait.
- Kind: 3
- From: H05-019

### RSV-093: Background checks re-read whole media files over the network on a timer.
- What was going on: A length check decoded every archive clip every 120 s (about 100 GB per pass), and presence checks made thousands of network round trips every 3 to 120 s.
- What the product must do: Repeating checks ask cheap questions first and remember each verdict until the file's size or date changes, while a real deletion still shows within the report window.
- Kind: 3
- From: L08-061, H06-035, H04-046

### RSV-094: Relinking 158 clips at once froze project tracking and quitting for over a minute.
- What was going on: Relinking a whole timeline's wrongly spelled clips, about half a second each, ran where the open project is tracked and quit is heard.
- What the product must do: A large batch of Resolve fixes never blocks tracking which project is open, new detections, or a quit or update.
- Kind: 3
- From: H01-015

### RSV-095: An offline clip whose file already sat in the tree was copied again.
- What was going on: 107 interview clips pointed at a temporary drive while identical copies sat in the project tree; the fix only knew how to copy.
- What the product must do: When an offline clip's same-named, same-size file already exists in the project tree, the fix relinks to that copy instead of duplicating it.
- Kind: 3
- State: outcome not found
- From: P03-002

### RSV-096: Relinking 1,559 offline clips found several same-named candidates for many.
- What was going on: Moved media often has byte-identical backups on several drives, and full-resolution and proxy copies share names.
- What the product must do: Candidates are ranked by longest matching path tail, then the root most other clips resolved to, then larger file, and ambiguous picks are shown first.
- Kind: 3
- From: M05-061

### RSV-097: The editor was offered a one-click relink into the product's own trash.
- What was going on: After a moved folder was set aside, its trash location was recorded as the move's destination and offered as where Resolve should look.
- What the product must do: Resolve is never relinked, or offered a relink, to a place the product may delete.
- Kind: 3
- From: H06-006

## Proxies in Resolve

### RSV-098: A clip's stored proxy path beats the proxy sitting beside the original.
- What was going on: Resolve stores a clip's proxy path apart from its file path; a stale path to another computer's drive overrides the adjacent Proxy folder (59 of 431 clips went offline).
- What the product must do: A clip whose stored proxy path is dead here is repointed to the matching in-tree proxy (same rate, start timecode, frame count), in the shared spelling, copying nothing.
- Kind: 1a
- From: P03-022, C01-041, M02-003

### RSV-099: A clip imported into Resolve by script arrives with no proxy attached.
- What was going on: Resolve attaches a proxy from an adjacent Proxy folder when a person imports, but a scripted import skips that step.
- What the product must do: After every import it performs, the product links the clip's proxy itself and checks it took, and a refused link never fails the import.
- Kind: 1a
- From: C01-097, L03-059, P05-024

### RSV-100: Resolve refuses a proxy whose timecode is missing or differs from its source.
- What was going on: Rewriting a 29.97 non-drop timecode as drop-frame made Resolve refuse 231 of 377 proxies; Resolve does read Sony's colon-written tag timecode as drop-frame.
- What the product must do: Every proxy carries exactly the timecode its source's timecode track states; only a timecode held in a Sony tag alone is normalised.
- Kind: 1a
- From: L08-050, M01-015

### RSV-101: Resolve pairs a proxy with its clip only by exact file name.
- What was going on: A proxy whose name differs from the original's by even one character is not attached, so the clip plays the original or goes offline.
- What the product must do: A proxy always carries exactly the original's name, byte for byte, on every computer.
- Kind: 1a
- From: C01-026

### RSV-102: Older project proxies in MP4 were never attached, with no reason given.
- What was going on: A rule meant for b-roll previews refused every MP4 proxy, though older project proxies are valid MP4 files, and nothing told anyone why.
- What the product must do: Valid older-format proxies are attached, and every proxy left unattached carries a reason the editor can see.
- Kind: 3
- From: L09-062

## Multicams, frame rates and timelines

### RSV-103: Resolve's scripting reports no file path and no angles for multicam clips.
- What was going on: A multicam answers "" for its file path and scripting shows nothing of its angles; on a 904-item multicam timeline scripting found 0-3 paths in 4-14 s, against 44 angle files really used.
- What the product must do: Every multicam and compound clip's source files are found from its angles, and a timeline of multicams never reads as having no media.
- Kind: 1a
- From: G01-004, L03-037, C02-079, M03-023

### RSV-104: A multicam angle can be a compound clip or several camera files in a row.
- What was going on: Four interviews had a compound clip as angle 1, and others had angle 1 spread over several camera files, leaving black stretches when only the first was used.
- What the product must do: Anything built from a multicam angle follows compound clips down to the camera files and places every file at its own time.
- Kind: 1a
- From: P15-041

### RSV-105: Built multicams all start at 01:00:00:00 and carry no reel or file name.
- What was going on: Reconform attached cuts to the wrong multicam; the owner: "It's reconforming things named differently to the wrong multicam. I'm actually pissed."
- What the product must do: Multicam matching uses a property unique to each (such as exact total duration), checks it is unique first, and refuses rather than guesses.
- Kind: 1a
- From: P01-015

### RSV-106: A multicam's angles map frame for frame from their starts, not by timecode.
- What was going on: Building a multicam resets its timecode to 01:00:00:00, and angles map frame for frame, even a true 24.000 angle in a 23.976 multicam, so timecode conform landed minutes off.
- What the product must do: Moving cuts between a camera clip and its multicam maps frames one to one from the angle's start, never by source timecode or real time.
- Kind: 1a
- From: P01-016

### RSV-107: Importing a timeline into a project that holds its multicams duplicates them.
- What was going on: Resolve dedupes footage by path but re-imports multicam and compound clips as "... import" copies, and the grade lives inside the multicam, so copies split the grade.
- What the product must do: Combined projects keep one copy of each multicam, matched by unique total duration since multicams share timecode, and leftovers are set aside, not lost.
- Kind: 1a
- From: P01-014, M05-055

### RSV-108: Rebuilding a damaged multicam timeline by export and reimport fails both ways.
- What was going on: An XML round trip lost multicam angles, subtitles and half the links; Resolve's own timeline export kept the bad links and imported duplicate angle timelines into the bin.
- What the product must do: A damaged multicam timeline is repaired inside Resolve (duplicate it and relink each pair), never by an export and import round trip, leaving no stray angle timelines.
- Kind: 1a
- From: P13-003

### RSV-109: Resolve places scripted clips a frame early and reports odd source times.
- What was going on: An append asked for frame 1238 landed at 1237; the source start counts from the file's start timecode; and Resolve reported an empty frame count for one WAV.
- What the product must do: Every clip placed in Resolve by script is read back and re-laid once if it is off by a frame.
- Kind: 1a
- From: D02-019

### RSV-110: Resolve's append can report success while placing nothing.
- What was going on: Appending without naming a track follows the timeline's destination-track buttons; with the video destination off nothing lands, no error returns, and a returned item proves nothing.
- What the product must do: After adding a clip to a timeline, the product confirms it is there at the expected start, without pinning it to one media type and losing its sound.
- Kind: 1a
- From: H01-016

### RSV-111: Resolve projects start at 24 fps or at the first raw clip's rate.
- What was going on: New projects were 24 fps, or 30 after the first Blackmagic raw import; scripting refuses a timeline's own rate, and the project rate changes only while there are no timelines.
- What the product must do: Before anything is imported or built, the project's rate is checked against the footage (29.97 drop-frame here) and the person is stopped if it cannot be set.
- Kind: 1a
- From: D02-016

### RSV-112: Resolve counts an audio-only clip's frames in that clip's own rate.
- What was going on: Resolve gave recorder WAVs 24 fps; asking for 48,508 frames on a 29.97 timeline placed 60,574, making an angle timeline 401 s too long.
- What the product must do: Placing audio-only clips into a timeline converts frames using the clip's own rate and checks the timeline's length afterwards.
- Kind: 1a
- From: D01-009

### RSV-113: Several things in Resolve cannot be done by script at all.
- What was going on: Scripting refuses clip speed, loudness normalising, a clip's frame rate, a timeline's own rate, audio fades, and putting a sound file on a multicam's audio angle.
- What the product must do: Each such step is handed to the person as a named manual instruction with its exact value, and the product never reports success for a setting Resolve refused.
- Kind: 1a
- From: D02-020, M01-002

### RSV-114: Resolve's count of linked clips changes between sessions on identical timelines.
- What was going on: The same timeline, with byte-identical stored data, showed 490 of 490 clips linked, then 242, then 238.
- What the product must do: Resolve's scripted link count is never taken as proof that picture and sound are paired.
- Kind: 1a
- From: D01-042

### RSV-115: Resolve cannot decode VP9 originals at full resolution, though proxies edit fine.
- What was going on: Resolve Studio 21 on Windows logs "Failed to decode the video frame" for VP9 originals and the final render fails; YouTube MP4s are often VP9; AV1 and HEVC render fine.
- What the product must do: The editor is warned as soon as a timeline uses VP9 originals, naming each clip and the fix, and is warned again for any newly added one.
- Kind: 1a
- State: fixed, never shipped
- From: L11-061, P13-022

### RSV-116: Repairing undecodable clips before a deadline render takes seconds, not hours.
- What was going on: A 48-minute re-encode blocked a render; the owner: "just copy the proxy out into the main folder instead of re-encoding each one individually".
- What the product must do: A pre-render repair swaps in an edit-ready copy with the same frame count in seconds per clip, re-encoding only when no matching copy exists.
- Kind: 2
- From: P13-024

### RSV-117: A conformed timeline had no sound on one editor's computer.
- What was going on: Every audio clip, multicam source and file was present for that editor, yet the conformed timeline played silent; the cause was never found.
- What the product must do: When a conformed timeline is silent on one computer, the product can check that computer's playback and offline clips and say which is at fault.
- Kind: 3
- State: outcome not found
- From: P14-024
- Move to: cards-to-resolve-and-exports

## Bins, clip sorting and imports

### RSV-118: Resolve calls an ordinary clip's type "Video + Audio".
- What was going on: Testing for audio first filed nearly every clip as audio (174 clips called music), and compound clips landed in effects.
- What the product must do: A clip with picture is never classed as audio, compound clips get their own bin, and a file named like a YouTube download is filed as YouTube.
- Kind: 1a
- From: M04-025, P01-024

### RSV-119: Resolve's scripting can read a bin's name but cannot rename a bin.
- What was going on: The owner asked for a bin's capitalisation fixed, and it had to be done by hand.
- What the product must do: Bins the product creates are named correctly when created, and a needed rename is listed for the person instead of claimed as done.
- Kind: 1a
- From: P01-028

### RSV-120: Resolve's scripted import files clips into whichever bin is currently selected.
- What was going on: Aiming background imports meant switching the current bin and back every 20-60 s, overwriting a bin the editor had just clicked.
- What the product must do: Background imports into Resolve never change which bin the editor has selected, even when the editor clicks mid-import.
- Kind: 1a
- From: L10-077, P13-006

### RSV-121: Each interviewee gets their own bin, with their sound recordings beside their footage.
- What was going on: The owner wanted a bin per interviewee, detected from their folder name, holding all footage from that folder plus the field-recorder audio files.
- What the product must do: Sorting creates one bin per interviewee folder and puts all that folder's video and sound-recorder files in it.
- Kind: 2
- From: P01-021

### RSV-122: A project's existing bins are the sorting template, including unfamiliar ones.
- What was going on: The owner wanted sorting to follow the project's own bins and react to unfamiliar ones by meaning, for example a "dmg" bin attracting .dmg files.
- What the product must do: Sorting targets the project's existing bins and routes clips to an unfamiliar bin when its name plainly describes them, proposing rather than applying.
- Kind: 2
- From: P01-025

### RSV-123: Sorting again never re-sorts clips already placed.
- What was going on: The owner wanted sorted clips remembered, existing theme bins preferred over new ones, and interview bins left alone, to avoid "an insane number of categories".
- What the product must do: A repeat sort moves only new clips, files them into existing matching bins before proposing any new bin, and never touches interview bins.
- Kind: 2
- From: P01-023

### RSV-124: Every downloaded YouTube clip goes into a theme bin, never the parent bin.
- What was going on: The owner: "It should put ALL youtube clps into a subcategory bin, and only uncategorised at the absolute last resort, and never into the master youtube clips bin".
- What the product must do: After sorting, no YouTube or archive clip sits loose in its parent bin; each is in a theme bin or, last, in "Uncategorised".
- Kind: 2
- From: P01-022

### RSV-125: Resolve's clip colour names mislead, and the owner bans "Brown".
- What was going on: Resolve's "Brown" renders mustard ochre, which the owner never wants; "Chocolate" is the brown, "Pink" is pale and "Violet" is hot pink.
- What the product must do: No clip colour the product assigns or offers is "Brown", and colour pickers show swatches, not Resolve's names alone.
- Kind: 2
- From: M03-044

## Colour look-up tables (LUTs)

### RSV-126: Resolve scans its LUT folders once, at startup.
- What was going on: If the shared drive mounts moments after Resolve starts, its LUTs stay missing all session though the settings are right, and only LUTs a grade uses report errors.
- What the product must do: When the LUT library was absent at Resolve's start and is reachable now, Resolve's LUT list is refreshed once without restarting Resolve or changing preferences.
- Kind: 1a
- From: P05-021, M02-004

### RSV-127: Resolve loads DCTL files only from its own LUT folder.
- What was going on: DCTLs placed in an additional LUT location, such as a shared one, are never loaded.
- What the product must do: The product never offers DCTLs through a shared extra LUT location as if Resolve would load them.
- Kind: 1a
- From: C01-061

### RSV-128: Resolve's own LUT folder holds factory LUTs that are not the editor's.
- What was going on: Resolve installs factory LUT packs; offering them as an editor's unshared LUTs, plus a version mismatch in sizes, made a permanent offer that copied nothing.
- What the product must do: Only LUTs an editor added are offered to the shared LUT library, never Resolve's factory set, and an offer clears once acted on.
- Kind: 1a
- From: H06-041, H07-066

### RSV-129: LUT packs unzipped from a Mac carry junk files with real LUT extensions.
- What was going on: Mac-made zips hold __MACOSX folders and "._" companion files of 176 B or 4 KB named like LUTs; a scan by extension would have copied about 139 junk files.
- What the product must do: LUT sharing and every stray-file scan skip __MACOSX folders and files whose names start with "._".
- Kind: 1a
- From: M02-031

### RSV-130: One shared LUT library that every editor's Resolve reads directly.
- What was going on: Each editor's LUTs lived only on their own computer; the owner asked for one shared LUT folder on the NAS, kept in sync, with Resolve pointed straight at it.
- What the product must do: Every editor receives the shared LUT folder without ticking anything, and Resolve on every computer lists the LUTs from it.
- Kind: 2
- From: P04-005

### RSV-131: A LUT added outside the shared library prompts the editor to copy it in.
- What was going on: The owner wanted the editor asked, whenever they add a LUT that is not in the shared folder, whether to copy it there.
- What the product must do: A LUT in Resolve's LUT locations but outside the shared library triggers an offer to copy it there; nothing is copied or moved unasked.
- Kind: 2
- From: P04-006

## Fixing media: copying in, rehearsals and undo

### RSV-132: Resolve's own Undo does not cover clip relinks made by script.
- What was going on: Relinks made through scripting, some unprompted, cannot be undone in Resolve, and nothing else saved the project or kept the old paths.
- What the product must do: Before any change to a Resolve project the product saves and exports the project and records the old paths, so every change can be undone.
- Kind: 1a
- From: L01-039

### RSV-133: The first read of a cloud-drive "online only" file blocks while it downloads.
- What was going on: Google Drive and OneDrive placeholders download as they are read (about 22 MB/s), so a copy stalled on one file, slowed itself for good, and one 8 MB read blocked cancel for seconds.
- What the product must do: A copy says per file that its source is still downloading, can skip it, regains full speed once reads are fast, and answers cancel within two seconds.
- Kind: 1a
- From: L05-094, H05-043, P02-021, L04-114

### RSV-134: A long media copy shows its progress and can be skipped, never hangs.
- What was going on: Fix-all hung then closed; another copy sat at "35/69" with no clue which file; the owner wanted file name, per-file and overall bars, skip, and cancel all.
- What the product must do: A copy shows the current file name, per-file and overall progress, and offers skip this file and cancel all; only a person's click stops it.
- Kind: 2
- From: P02-015

### RSV-135: A rehearsal of fixing media reported files copied, failed or uploading.
- What was going on: In rehearsal mode nothing is copied, yet results said "69 copied" or 69 failed, the bar showed 800 GB in two seconds or froze at 0%, and an upload could start.
- What the product must do: The mode is visible before the click; a rehearsal says "Checking", moves by clips checked, says nothing was copied, starts nothing; a real run states how many it copied.
- Kind: 3
- From: H05-044, L05-075, L07-005, L08-085, L06-007, L04-158

### RSV-136: Fixing many clips gave no size or space check and could die mid-copy.
- What was going on: Fix-all copied until the system drive was full, quitting killed a multi-GB copy unasked, and one button closed the window while copying continued.
- What the product must do: Before copying, fix-all states size and free space and refuses without room; an unreadable or zero free-space reading drops that line; quitting mid-copy asks; the window stays until done.
- Kind: 3
- From: H07-069, L04-052

### RSV-137: Fix-all rewrote 158 clips and the window just closed.
- What was going on: After copying files and rewriting paths in the editor's Resolve project, nothing summarised the result or said how to undo it.
- What the product must do: After any batch change to a Resolve project, a summary gives fixed of total, size copied, failures with the first reason, and how to undo it.
- Kind: 3
- From: L04-105

### RSV-138: Retrying a clip fix copied a multi-gigabyte file all over again.
- What was going on: A retry made a second "(2)" copy, then uploaded it; fixing one source into a second project copied it twice; with no matched project the copy went where it never syncs.
- What the product must do: A retry redoes only the step that failed and reuses a verified copy already made, copies go only where they will sync, and results state exactly what happened.
- Kind: 3
- From: H06-043, H07-067

### RSV-139: A second click on fix-all started a second copy of the same batch.
- What was going on: The relink window's buttons stayed live during a run, so the natural second click started a duplicate copy.
- What the product must do: Every action that moves media disables its buttons until it finishes, and re-enables them after.
- Kind: 3
- From: L04-051

### RSV-140: Undo of a path fix rewrote clips in a different project.
- What was going on: Undo replayed the newest change of any project, and a project name remembered for 20 seconds filed changes under the previously open project, repointing shared music and b-roll clips.
- What the product must do: Every Resolve change is filed under the project open at that moment, and undo acts only on that project, refusing and naming it when another is open.
- Kind: 3
- From: H03-004, H06-038, H07-064

### RSV-141: An undo asked while Resolve was starting or had no project was failed for good.
- What was going on: "Resolve is starting up" and "no project open", Resolve's commonest state, were recorded as permanent failures and never retried.
- What the product must do: A Resolve change waiting for Resolve to start or for its project to open is shown as waiting, and runs once that happens.
- Kind: 3
- From: H06-039, L04-112

### RSV-142: An admin could not undo Resolve path changes on an editor's computer.
- What was going on: Undoing the product's clip relinks was only a click on the editor's own computer, with no way for an admin to trigger it.
- What the product must do: An admin can ask any computer to undo a recorded Resolve change; it waits until that project is open, for up to a week, then reports failure.
- Kind: 3
- From: L03-026

### RSV-143: One fix needed several undos, and a repeat undo claimed success.
- What was going on: A long fix was recorded as several changes, one change had no record at all, and undoing one already undone reported success again.
- What the product must do: Each press is undone by one undo restoring the exact earlier state or saying it cannot, a repeat says it is already undone, and relinks re-check each clip's path just before.
- Kind: 3
- State: outcome not found
- From: H08-027, H07-068, H06-037

### RSV-144: Undo reported success though most fixes were never recorded.
- What was going on: Several path fixes made at once overwrote each other's undo records, keeping as few as 1 to 5 of 160, and undo then reported success.
- What the product must do: Every Resolve change lands in the undo record even when many happen at once, a failure to record one is a visible warning, and undo names any clip not restored.
- Kind: 3
- From: H04-070, L03-084

### RSV-145: Safety copies of Resolve projects piled up on the editor's disk for ever.
- What was going on: Whole-project safety copies, tens of megabytes, were written before automatic edits up to every 15 minutes, and they and half-written leftovers from crashes were never deleted.
- What the product must do: Safety copies and leftovers from interrupted saves older than the stated retention, 60 days, are deleted, so their disk use stays bounded.
- Kind: 3
- From: H03-006, H05-048

## Grading from the server's originals

### RSV-146: Grade from the server's full-quality originals, then switch back to proxies.
- What was going on: The owner wanted a remote colourist to "momentarily swap to a direct map of the server" to view originals while grading, then click back.
- What the product must do: Any editor can switch their project drive to the server's originals and back again in one action, with no relinking and syncing unaffected.
- Kind: 2
- From: P02-044

### RSV-147: A remote editor needs one frame of a camera raw original in Resolve to grade.
- What was going on: The owner: "what I really need is just the ability for a remote editor to see one frame in resolve of the camera raw original that's on the server".
- What the product must do: A remote editor can bring one frame of a raw original from the NAS into Resolve and change its raw settings, without downloading the whole clip.
- Kind: 2
- State: still open
- From: P17-029

### RSV-148: The first switch to server originals left everything offline and proxies grey.
- What was going on: The switch briefly unmaps the project drive; it needed a NAS login nothing asked for, so it failed, Resolve lost everything, and warnings mid-switch read as a broken setup.
- What the product must do: A needed login is asked once per computer and remembered, drive warnings stay silent mid-switch, and a failed switch leaves the drive exactly as before.
- Kind: 3
- From: C01-036, P02-045

## Other givens on the editor's computer

### RSV-149: Resolve holds graphics memory that grows over a session, starving other players.
- What was going on: On a 10 GB card an idle Resolve held 6.2 GB plus 6.7 GB spilled to system memory; the driver falls back silently, so 6K raw playback stutters rather than fails.
- What the product must do: The product's own graphics work yields to Resolve while it is open, and playback diagnostics check Resolve's graphics memory before blaming the network or file.
- Kind: 1a
- From: M05-071, P03-040

### RSV-150: Send to Resolve failed when the dashboard address differed from the browser's.
- What was going on: The editor's app accepts browser requests only from the configured dashboard address, so another spelling of the same address refused every Send to Resolve.
- What the product must do: Site settings warn that the dashboard address must be exactly what editors type, and a refusal names both addresses.
- Kind: 3
- From: L04-161
- Move to: editor-app

### RSV-151: Send to Resolve did nothing when another program held the app's local port.
- What was going on: The app tried its local listening port once at start; when another program held it, the app still believed it was serving and only the browser saw failures.
- What the product must do: The local port's health is retried, shown on the computer and reported to the dashboard, which warns when the feature is on and the port is not ours.
- Kind: 3
- From: L04-053
- Move to: editor-app

### RSV-152: A refusal's reason was cut off before the part naming what to close.
- What was going on: The sentence naming the other program holding Resolve was cut at 255 characters on the way to the dashboard, so the admin saw advice but not the program.
- What the product must do: A refusal shown to an admin leads with the actionable part, and any length limit shortens it deliberately in the middle, never silently mid-word.
- Kind: 3
- From: L06-001

## Sealed

### RSV-S01: Read directly, Resolve's project library answers in milliseconds and shows multicam angles.
- What was going on: The media pool lists in 31 ms against 20 s by scripting, media ids equal scripting's unique ids, angles show; but link columns are empty, subtitle tracks must be skipped, frames are text.
- What the product must do: Reads are read-only with 5 s timeouts, scoped to one project via association tables, video and audio tracks only, matching scripting's results, falling back to scripting on any surprise.
- Kind: 1b
- Tool: reading Resolve's project library directly (PostgreSQL or disk library, zstd-compressed protobuf clip blobs)
- From: C02-080, G01-005, L03-038, P07-062, M04-017

### RSV-S02: A direct library read misses unsaved edits and keeps stale per-cut paths.
- What was going on: A whole timeline reads in about 11 ms, live clip paths matching Resolve's on 1,298 of 1,298; edits since the last save are absent, and per-cut paths go stale after relinks.
- What the product must do: Trust the clip's current pool path, never the per-cut path, and fall back to asking Resolve when the read fails or the format changes.
- Kind: 1b
- Tool: reading Resolve's project library directly
- From: D02-036

### RSV-S03: How Resolve's library stores timelines, rates, markers and multicams.
- What was going on: Rate is a double plus a drop-frame byte; extents are start and duration; frames are text; a multicam is a sequence; markers sit in a compressed blob; the save stamp is a counter.
- What the product must do: A timeline read from the library matches what Resolve's scripting reports for every cut's id, start, length, clip and rate.
- Kind: 1b
- Tool: reading Resolve's project library directly
- From: D02-037

### RSV-S04: A plain imported clip's frame rate is missing where the library usually keeps it.
- What was going on: Plain clips (235 of 235 downloads) lack a rate on the media record; it is in the video info's typed dictionary, a pad byte after each type tag.
- What the product must do: A plain clip's rate (16 bytes: little-endian double plus drop flag) is read from the video info record, and the decoder is tested on downloaded clips.
- Kind: 1b
- Tool: reading Resolve's project library directly
- From: G01-006

### RSV-S05: Leaked library connections can lock the whole studio out of Resolve's project server.
- What was going on: The network library server allows 100 connections; failed readers leaked theirs, one retry per 3 s per computer would exhaust it in minutes; library-wide listings return other projects' clips.
- What the product must do: Every connection closes on every failure path, retries come at most once a minute, reads list one project only, and Resolve use is never held up.
- Kind: 1b
- Tool: reading Resolve's project library directly
- From: G01-008, M03-024

### RSV-S06: A quarter of in-points read from the library are one frame off Resolve's.
- What was going on: Read with Resolve closed, a 490-cut timeline matched on all items and 137 of 140 cards, but 114 of 490 in-points read one frame higher, with no pattern found.
- What the product must do: Library reads give cards identical to the live read or report the difference, tolerate a one-frame in-point gap, and frame-exact work uses Resolve's own figure.
- Kind: 1b
- Tool: reading Resolve's project library directly
- State: outcome not found
- From: D02-038, D06-020

### RSV-S07: Resolve's list of project libraries can miss the shared database libraries.
- What was going on: The scripting call that lists project libraries did not return every database library, but Resolve's own log names each one it connects to.
- What the product must do: Every project library is found from the scripting list, Resolve's log and the disk library folders, and each is read read-only, once per library.
- Kind: 1b
- Tool: reading Resolve's project libraries and log directly
- State: fixed, never shipped
- From: L11-066

### RSV-S08: Resolve keeps LUT locations and drive mappings in two plain-text preference files.
- What was going on: Both files must change together; their numbering bases can differ, Resolve's own trailing entry must stay last, and a root-owned file can be silently re-owned.
- What the product must do: Edits are made while Resolve is closed, back up first, keep both files consistent, and preserve every existing entry and its numbering.
- Kind: 1b
- Tool: editing Resolve's preference files directly
- From: M02-032, C01-063

### RSV-S09: Changing Resolve's drive mapping on a Mac seemed to work, then reverted.
- What was going on: Mac Resolve keeps it in config.dat and hidden .config.data, rebuilding the first from the second; direct IO is "MacDIO" there, and /Volumes must stay last.
- What the product must do: Both Mac files change together with the Mac spelling, inserted before Resolve's trailing entry, also checking the App Store build's own sandbox folder.
- Kind: 1b
- Tool: editing Resolve's preference files directly (macOS)
- From: G01-015

### RSV-S10: Resolve's scripting switch lives in both preference files, which must agree.
- What was going on: The "External scripting" choice is stored as System.Scripting.Mode in config.dat and .config.data, 1 meaning Local (0 and 2 inferred).
- What the product must do: The setting is written to both files while Resolve is closed, and reported as set only when both say Local.
- Kind: 1b
- Tool: editing Resolve's preference files directly
- State: fixed, never shipped
- From: L11-045

### RSV-S11: A Mac's open-files listing cuts command names to nine characters.
- What was going on: By default the listing truncates command names to 9 characters, so "davinci resolve" never matched when finding Resolve's process.
- What the product must do: Finding Resolve's process on a Mac never depends on a truncated command name.
- Kind: 1b
- Tool: lsof on macOS (needs +c 0)
- From: H04-087

### RSV-S12: Keystrokes typed into Resolve by simulation lose characters.
- What was going on: A multicam name sent as simulated typing arrived as "陳政隆 Mul" instead of "陳政隆 Multicam".
- What the product must do: Anything entered into Resolve by simulated typing is read back and corrected if it differs.
- Kind: 1b
- Tool: sending keystrokes into Resolve
- From: D02-015

### RSV-S13: Resolve's windows expose little to automation.
- What was going on: The main window has no child windows; the menu bar is exposed with submenus under their items; dialogs are hidden, reused top-level windows; buttons are named, fields anonymous.
- What the product must do: A Resolve dialog is judged open only by whether it is visible, never by its window existing.
- Kind: 1b
- Tool: Windows UI Automation on Resolve
- From: M04-023

### RSV-S14: Importing into the current bin and then moving the clips aims without switching bins.
- What was going on: Moving newly imported clips avoids changing the selected bin; each scripting call returns a new folder object, so folders must be compared by unique id.
- What the product must do: Import, then move the new clips to their bin comparing folders by unique id; a refused move leaves the clips in the project and logs where.
- Kind: 1b
- Tool: Resolve scripting API (ImportMedia then MoveClips)
- From: L10-078

## Removed

- C01-005 | superseded by RSV-053
