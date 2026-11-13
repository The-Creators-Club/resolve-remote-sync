# Entries a merger marked for another capability (30 groups)

## Group M1

Marked to move to `broll`:

### ACC-038 [accounts-privacy-legal / What each person may see and reach]: The public client page also served the internal app's code to anyone.
- What was going on: The internet-facing client preview page shared a file folder with the internal pages, so anyone could download the internal app and its request map.
- What the product must do: The internet-facing client page serves only the files its viewer needs and refuses any internal page or script.
- Kind: 3
- Move to: broll

The entries of `broll` that read most like it:

### BRO-133 [broll / Client folders and links]: The public client page exposed the whole internal app's files.
- What was going on: The public share address served every static file of the internal b-roll app, not just the viewer's.
- What the product must do: The public share serves only the viewer's own files and answers anything else as not found.
- Kind: 3

### BRO-101 [broll / Bringing new footage in]: When the app on this computer was not running, the page blamed it for refusing.
- What was going on: A failed connection, or an app too old for the request, was shown as the app's refusal, hiding the advice to use the computer holding the files.
- What the product must do: The page tells "the app on this computer did not answer" and "the app is too old" apart from a real refusal, keeping the next-step advice.
- Kind: 3

### BRO-128 [broll / Client folders and links]: A renamed or rebuilt clip vanished from, or swapped inside, client folders.
- What was going on: Client folders remembered clips by path or by a number that index rebuilds reassign and other machines number differently, so clips dropped, swapped or duplicated.
- What the product must do: A clip keeps one identity across renames, moves, rebuilds and machines; a folder serves exactly its curated clips; one that cannot be confirmed is hidden from the client, shown missing to the curator.
- Kind: 3

### BRO-129 [broll / Client folders and links]: Revoking a client's link did not stop playback for an hour.
- What was going on: Shared media was sent with a one-hour browser cache, and every link appeared in the access log.
- What the product must do: Every client request is checked against the folder's curated clips; after revoking, the very next media request is refused; a link never appears in any log.
- Kind: 3

### BRO-007 [broll / Givens: browsers, cameras, files and Resolve]: A 4 GB upload with no progress bar looked like a hung page.
- What was going on: The browser's newer request method cannot report upload progress, and browsers cannot preview camera raw or MXF files, so a drop showed nothing for minutes.
- What the product must do: Every file uploading from a page shows its progress, and a file the browser cannot preview says so until a thumbnail arrives.
- Kind: 1a

Sub-topics of `broll`: Givens: browsers, cameras, files and Resolve; How the archive is laid out; Describing and indexing clips; Search; The clip player; Previews made for the archive; Bringing new footage in; Sending a clip to Resolve; Previews standing in for originals; Client folders and links; Replacing the search index

## Group M2

Marked to move to `sync`:

### BRO-024 [broll / How the archive is laid out]: Footage used by many projects must not be set up again per project.
- What was going on: The owner wanted one shoot in several projects; a per-project bin of outside files "would be fiddly to set up every time there's a new [series] project".
- What the product must do: Footage shared across projects lives in one shared library every editor can use, with no setup when a new project starts.
- Kind: 2
- Move to: sync

The entries of `sync` that read most like it:

### SYN-003 [sync / What syncs where]: Nothing syncs until a project is ticked, and ticked projects go one at a time.
- What was going on: Everything was syncing at once; the owner wanted editors to tick or untick projects, nothing moving until ticked, and projects synced one after another.
- What the product must do: Nothing syncs to a computer until a project is ticked for it; unticking stops it; several ticked projects sync one at a time, in order.
- Kind: 2

### SYN-005 [sync / What syncs where]: A project can sit at any depth on the server, inside series or categories.
- What was going on: Owner: "The project could be any project inside any year inside any series"; an episode inside its series folder could not be found or ticked.
- What the product must do: A project at any folder depth on the server appears in the project list, can be ticked, and is reproduced locally with the server's exact names and nesting.
- Kind: 2

### SYN-017 [sync / What syncs where]: Renaming the projects folder in setup made every computer sync nothing.
- What was going on: The projects-folder name was honoured by server setup only, so a customer who changed it got a server tree under one name and computers looking for another.
- What the product must do: Every setting offered is honoured by every part of the product, or the product refuses to start with it set and says why.
- Kind: 3

### SYN-004 [sync / What syncs where]: An urgent project could not be moved to the front of a computer's queue.
- What was going on: Queue order was the order projects were ticked; the owner wanted one project "top of the queue" and it waited behind seven others.
- What the product must do: An editor or admin can move a project to the front of one computer's sync queue from the screen.
- Kind: 2
- State: still open

### SYN-012 [sync / What syncs where]: Studio-wide libraries must reach every computer, even one with nothing ticked.
- What was going on: The shared LUT, b-roll and music libraries had to reach everyone; deciding sharing from project ticks alone would have unshared them from every computer.
- What the product must do: Studio-wide library folders sync to every editor's computer automatically, with no project ticked, and never appear as projects.
- Kind: 3

Sub-topics of `sync`: What syncs where; A plan belongs to a computer; Wired or remote; Upload only; Deletions and removing a project; Safety stops; Studio-wide stops and the editor's pause; Files that must never sync; Names; The sync drive; Disk space; Stuck, slow and fair transfers; Uploads that cannot resume, shutdown and sleep; Saying truthfully what the sync is doing; What is owed; Load on the NAS when nothing changes; Speed and routes; Clocks and file age; Computers joining and changing; Project folders on an editor's computer; Facts about the NAS and the operating systems

## Group M3

Marked to move to `whole-product`:

### BRD-035 [cards-board / What the assistant may do]: One action's several refusals stacked identical red notices.
- What was going on: Each refused change raised its own red 8-second notice, so a single turn stacked several identical ones on screen.
- What the product must do: Several refusals from one action show as one summary with a count, the details kept where they can be read.
- Kind: 3
- State: still open
- Move to: whole-product

The entries of `whole-product` that read most like it:

### ALL-043 [whole-product / Wording]: The admin was told "ask your admin", and counts had the wrong scope.
- What was going on: A notice put a computer-wide 1,046 missing proxies under a project holding 438; one sentence covered three situations; only the first failing folder was named.
- What the product must do: Counts state their scope, each distinct problem gets its own true sentence, several show a count, and nobody is told to ask themselves.
- Kind: 3

### ALL-056 [whole-product / Could not check, refusals and nothing silent]: A refusal hid its reason behind a generic line.
- What was going on: Refusals read "this page has stopped updating", network errors posed as answers, errors vanished in 5 seconds, and computed reasons stayed in logs.
- What the product must do: Every refusal or failure shows its real reason to the person it affects, names a network failure as one, and stays on screen until read.
- Kind: 3

### ALL-090 [whole-product / Could not check, refusals and nothing silent]: The owner: "A computer having nothing ticked is FINE."
- What was going on: The owner: "I've already made this clear in the past. A computer having nothing ticked is FINE"; it kept appearing as blocked, amber or an open issue.
- What the product must do: A computer with no projects ticked shows as normal on every surface: no error, warning, blocked reason, red or amber state, alert or notice; real faults keep theirs.
- Kind: 2

### ALL-035 [whole-product / Wording]: Counts read "3 file(s)" instead of real plurals.
- What was going on: The owner retired the "(s)" shorthand, but it kept shipping in tray, dialog and page messages.
- What the product must do: Every count a person reads uses the correct singular or plural word ("1 clip", "3 clips") with an agreeing verb.
- Kind: 2

### ALL-013 [whole-product / The look]: One raw control character in a page script killed the whole page.
- What was going on: Browsers turn a raw NUL inside an inline script into a replacement character, so code that passed every non-browser check failed to compile and the page died.
- What the product must do: Page scripts carry no raw control characters other than tab, CR and LF, and every page change is run in a real browser before release.
- Kind: 1a

Sub-topics of `whole-product`: The rebuild itself; The look; Wording; Could not check, refusals and nothing silent; Safety in what the product does; Windows, text and names; Requests, logs and outside programs; The assistant

## Group M4

Marked to move to `cards-to-resolve-and-exports`:

### CE1-086 [cards-editor / Playback and audio]: Fade handles on cuts reach Resolve as real audio fades.
- What was going on: The owner asked for Resolve-style fade handles on cuts and ruled them audio only.
- What the product must do: A cut's audio fade handles arrive in Resolve as real audio fades, and no video fade is ever written.
- Kind: 2
- Move to: cards-to-resolve-and-exports

The entries of `cards-to-resolve-and-exports` that read most like it:

### CRX-041 [cards-to-resolve-and-exports / Undo, markers, titles, fades and properties]: Fade handles are audio only, heard in the browser and exact in Resolve.
- What was going on: The owner: "timeline cards only needs audio fades, not video fades", conforming "to resolve accurately", and fades must "actually play, not just be visual".
- What the product must do: Cuts carry audio fade-in and fade-out handles that play as drawn in the browser and arrive in Resolve at the same lengths; the picture is never faded.
- Kind: 2

### CRX-072 [cards-to-resolve-and-exports / Sending a cut to Resolve]: Clip colours set in the cards did not reach Resolve.
- What was going on: The owner wants clip colours set in the cards carried into the built timeline; on a montage they did not arrive.
- What the product must do: A colour set on a cut in the cards appears on that clip in the timeline Resolve receives.
- Kind: 3
- State: outcome not found

### CRX-038 [cards-to-resolve-and-exports / Undo, markers, titles, fades and properties]: Resolve's scripting cannot set fades, keyframes, transitions or clip volume.
- What was going on: Item properties cover only a static opacity, so one cut's 22 audio fades and its manual gains, and levelling heard in the preview, never reached Resolve.
- What the product must do: Every send and export carries fades, gain and levelling where it can, and names each one it dropped, with a count in words.
- Kind: 1a
- State: fixed, never shipped

### CRX-046 [cards-to-resolve-and-exports / Talking to Resolve: restarts, dialogs and speed]: Resolve clip handles work only on the connection that fetched them.
- What was going on: Media pool clips fetched on one scripting connection and appended through another silently return an empty list.
- What the product must do: Clips are fetched and appended on the same connection, and an empty append result counts as a failure.
- Kind: 1a

### CRX-073 [cards-to-resolve-and-exports / Sending a cut to Resolve]: A build stopped early left 54 cuts with no audio or markers.
- What was going on: The build placed all video first, then audio, then markers, and with no timeline open the status flickered between available and unreachable.
- What the product must do: A send reports done only when picture, sound and markers are all placed, flags any partial timeline, and keeps a steady status while Resolve is idle.
- Kind: 3
- State: still open

Sub-topics of `cards-to-resolve-and-exports`: Frames, frame rates and timecode; Placing, deleting and linking clips in Resolve; Undo, markers, titles, fades and properties; Talking to Resolve: restarts, dialogs and speed; Sending a cut to Resolve; Edits sent live and staged edits; Bringing Resolve's changes back into the cut; Which computer is driving Resolve; Exports; Renders from Resolve; Titles and compound clips; Subtitles and delivery

## Group M5

Marked to move to `cards-to-resolve-and-exports`:

### CFI-039 [cards-footage-in / Grouping clips and building the multicam]: Resolve's "Brown" clip colour is never used; "Chocolate" is the brown.
- What was going on: The owner ruled that the mustard-ochre "Brown" is never assigned to anything; the chocolate brown is fine.
- What the product must do: No colour the product assigns in Resolve or on cards is ever Resolve's "Brown".
- Kind: 2
- Move to: cards-to-resolve-and-exports

The entries of `cards-to-resolve-and-exports` that read most like it:

### CRX-072 [cards-to-resolve-and-exports / Sending a cut to Resolve]: Clip colours set in the cards did not reach Resolve.
- What was going on: The owner wants clip colours set in the cards carried into the built timeline; on a montage they did not arrive.
- What the product must do: A colour set on a cut in the cards appears on that clip in the timeline Resolve receives.
- Kind: 3
- State: outcome not found

### CRX-060 [cards-to-resolve-and-exports / Sending a cut to Resolve]: Timeline Cards hands its cut to Resolve only, to start.
- What was going on: The owner ruled "resolve only to start": other editing programs later, if a client needs one.
- What the product must do: The cut is handed over to Resolve, and nothing before the hand-over depends on any editing program.
- Kind: 2

### CRX-085 [cards-to-resolve-and-exports / Which computer is driving Resolve]: The link to Resolve showed green while dead for hours.
- What was going on: Healthy meant "was started", so a crashed loop, hours of refused sign-ins or an unreachable dashboard looked fine, and restarts waited on a different test.
- What the product must do: Green needs a successful contact in the last 50 seconds, else it names stopped, refused or unreachable; anything shown stopped is restarted within a minute.
- Kind: 3

### CRX-044 [cards-to-resolve-and-exports / Undo, markers, titles, fades and properties]: A gap-note title must never cover the next cut or move anything.
- What was going on: A title longer than its gap would sit over the next cut in every render, and a note marker in a section colour comes back as a new section heading.
- What the product must do: Gap text never overlaps picture, no cut moves, every track lock is restored, and a note marker never reads back as a section.
- Kind: 3
- State: fixed, never shipped

### CRX-096 [cards-to-resolve-and-exports / Titles and compound clips]: Compound clips should carry the name and colour of what they hold.
- What was going on: Resolve names new compound clips "Compound Clip 1, 2..."; the owner wants each named after its clip and coloured like that interviewee's multicam.
- What the product must do: A compound clip the product creates is named after the clip it wraps and takes the clip colour of the related interviewee's multicam.
- Kind: 2
- State: outcome not found
- Move to: resolve-on-the-editors-computer

Sub-topics of `cards-to-resolve-and-exports`: Frames, frame rates and timecode; Placing, deleting and linking clips in Resolve; Undo, markers, titles, fades and properties; Talking to Resolve: restarts, dialogs and speed; Sending a cut to Resolve; Edits sent live and staged edits; Bringing Resolve's changes back into the cut; Which computer is driving Resolve; Exports; Renders from Resolve; Titles and compound clips; Subtitles and delivery

## Group M6

Marked to move to `cards-editor`:

### CFI-110 [cards-footage-in / Montages]: A montage uses only downloaded material, never the studio's own interviews.
- What was going on: The owner's rule: a montage is news, coverage or archive the product downloaded, with credits, never the studio's interview material.
- What the product must do: Building a montage refuses interview footage and any clip without a credit record.
- Kind: 2
- Move to: cards-editor

The entries of `cards-editor` that read most like it:

### CE1-079 [cards-editor / Playback and audio]: Every clip must play and show its waveform without an export step.
- What was going on: Only interview clips had prepared audio, so news and archive clips played silence; the owner: play "directly through to the lane, so we don't have to output wavs".
- What the product must do: Opening a cut starts preparing every clip's audio and waveform with progress per clip; any clip whose media exists plays, matching source timing within 0.05 s.
- Kind: 3

### CE1-012 [cards-editor / Search and the transcript panel]: "Interview" means a transcript filed under a named person.
- What was going on: News clips with reporter speaker labels counted as interviewees; the owner: "'Interview' means one of my documentary interviews, so a transcript inside a named person folder".
- What the product must do: Only transcripts filed under a named person appear among the people; the browser lists every transcript and cut list in the episode, filterable, searchable and multi-selectable.
- Kind: 2

### CE2-090 [cards-editor / Shortening and the assistant]: The assistant keeps one warm conversation while the owner works.
- What was going on: The owner: "does the session stay active ... so the cached content remains cached? I don't want it to reset context every time"; search covers one or all transcripts.
- What the product must do: Follow-ups on one cut or montage share one conversation, a reload or second browser joins it, and a forced restart says so on screen and re-sends the material.
- Kind: 2

### CE2-008 [cards-editor / The lane: clicking, trimming and dragging]: Extending over the next piece of the same recording is allowed.
- What was going on: Dragging an edge over the neighbouring cut from the same source raised a refusal; the owner said "allow it".
- What the product must do: A clip can be extended over material its neighbour also uses, with no refusal; the overlap then plays twice.
- Kind: 2

### CE1-095 [cards-editor / Lane clicks and keys]: Chrome and Edge keep F12 for developer tools, and no page can take it.
- What was going on: The owner's "head to mouse" shortcut on F12 opened developer tools instead, and his mouse side button sends F12.
- What the product must do: No page shortcut uses F12 or another browser-reserved key, and a mouse button sending F12 is remapped before the browser, leaving Resolve's own F12 alone.
- Kind: 1a

Sub-topics of `cards-editor`: Chinese text and matching; Search and the transcript panel; The English a cut shows; House style and the assistant; Shortening; Editing: selecting, deleting, inserting; Notes and the staged shelf; The cut list, undo and saving; Edit speed and answering the editor; Playback and audio; Lane clicks and keys; Game controller; Phone; Panels and layout; Opening episodes, restarts and Resolve; Offline and several devices; Connections; The lane: clicking, trimming and dragging; Cards, selection and keys; Sections and the overview; Colours; Media the browser gets; Shortening and the assistant; Working offline; Several people and devices; Phones, installing and the controller; Speed and smoothness; Opening episodes and keeping the editor running; The lane: how clips look and read; The lane: zoom, scrolling and dragging; Editing, undo and the cut list; Shortening and the edit chat; Working offline and on several devices; Resolve is optional; Phone and game controller; The page: header, warnings and redrawing; Opening episodes

## Group M7

Marked to move to `resolve-on-the-editors-computer`:

### CRX-091 [cards-to-resolve-and-exports / Renders from Resolve]: Scripted effects inside compound clips lose their first frames and abort renders.
- What was going on: A Fusion composition added by script loses its first one or two frames ("No frame available") once its clip is wrapped in a compound clip.
- What the product must do: A compound clip the product builds renders every frame including its first, checked by rendering the head frames before handing it over.
- Kind: 1a
- Move to: resolve-on-the-editors-computer

The entries of `resolve-on-the-editors-computer` that read most like it:

### RSV-118 [resolve-on-the-editors-computer / Bins, clip sorting and imports]: Resolve calls an ordinary clip's type "Video + Audio".
- What was going on: Testing for audio first filed nearly every clip as audio (174 clips called music), and compound clips landed in effects.
- What the product must do: A clip with picture is never classed as audio, compound clips get their own bin, and a file named like a YouTube download is filed as YouTube.
- Kind: 1a

### RSV-109 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Resolve places scripted clips a frame early and reports odd source times.
- What was going on: An append asked for frame 1238 landed at 1237; the source start counts from the file's start timecode; and Resolve reported an empty frame count for one WAV.
- What the product must do: Every clip placed in Resolve by script is read back and re-laid once if it is off by a frame.
- Kind: 1a

### RSV-104 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: A multicam angle can be a compound clip or several camera files in a row.
- What was going on: Four interviews had a compound clip as angle 1, and others had angle 1 spread over several camera files, leaving black stretches when only the first was used.
- What the product must do: Anything built from a multicam angle follows compound clips down to the camera files and places every file at its own time.
- Kind: 1a

### RSV-099 [resolve-on-the-editors-computer / Proxies in Resolve]: A clip imported into Resolve by script arrives with no proxy attached.
- What was going on: Resolve attaches a proxy from an adjacent Proxy folder when a person imports, but a scripted import skips that step.
- What the product must do: After every import it performs, the product links the clip's proxy itself and checks it took, and a refused link never fails the import.
- Kind: 1a

### RSV-084 [resolve-on-the-editors-computer / Missing clips, relinking and refreshing]: Render In Place files exist only on the computer that rendered them.
- What was going on: A re-synced project lost all 175 Render In Place clips: they pointed at empty folders elsewhere, and after a re-rooting the renders were nowhere on any disk.
- What the product must do: Render In Place files in a synced project reach the NAS like other media, or the editor is told which clips will be offline elsewhere before media moves.
- Kind: 1a

Sub-topics of `resolve-on-the-editors-computer`: Connecting to Resolve's scripting: launch, stalls and death; Setting Resolve up: edition, scripting switch, preferences; Project libraries and projects; Knowing which project is open; Clip paths and media outside the shared tree; Missing clips, relinking and refreshing; Proxies in Resolve; Multicams, frame rates and timelines; Bins, clip sorting and imports; Colour look-up tables (LUTs); Fixing media: copying in, rehearsals and undo; Grading from the server's originals; Other givens on the editor's computer

## Group M8

Marked to move to `resolve-on-the-editors-computer`:

### CRX-092 [cards-to-resolve-and-exports / Renders from Resolve]: A render queue across projects must survive Resolve crashing.
- What was going on: The owner wanted renders queued from several projects, with a crash detected, Resolve restarted and the interrupted render resumed.
- What the product must do: When Resolve dies during a queued render, the queue restarts Resolve, re-runs the interrupted job and continues with the rest.
- Kind: 2
- State: outcome not found
- Move to: resolve-on-the-editors-computer

The entries of `resolve-on-the-editors-computer` that read most like it:

### RSV-084 [resolve-on-the-editors-computer / Missing clips, relinking and refreshing]: Render In Place files exist only on the computer that rendered them.
- What was going on: A re-synced project lost all 175 Render In Place clips: they pointed at empty folders elsewhere, and after a re-rooting the renders were nowhere on any disk.
- What the product must do: Render In Place files in a synced project reach the NAS like other media, or the editor is told which clips will be offline elsewhere before media moves.
- Kind: 1a

### RSV-031 [resolve-on-the-editors-computer / Connecting to Resolve's scripting: launch, stalls and death]: Resolve crashed instantly on launch on the studio's main computer.
- What was going on: The owner reported Resolve crashing at launch on the main computer; no cause was found.
- What the product must do: Nothing on an editor's computer contacts Resolve before its launch completes, and Resolve launch failures are logged for diagnosis.
- Kind: 3
- State: outcome not found

### RSV-121 [resolve-on-the-editors-computer / Bins, clip sorting and imports]: Each interviewee gets their own bin, with their sound recordings beside their footage.
- What was going on: The owner wanted a bin per interviewee, detected from their folder name, holding all footage from that folder plus the field-recorder audio files.
- What the product must do: Sorting creates one bin per interviewee folder and puts all that folder's video and sound-recorder files in it.
- Kind: 2

### RSV-011 [resolve-on-the-editors-computer / Connecting to Resolve's scripting: launch, stalls and death]: Any open Resolve dialog makes its scripting answer nothing, for every program.
- What was going on: An "Audio Output: device not found" box (speaker unplugged, or "Remote Audio" after Remote Desktop) appears on project load; until clicked, calls return nothing and queued renders sit at Ready.
- What the product must do: Empty answers mean "Resolve cannot answer now", never missing data; nothing is written meanwhile, the person is told to check Resolve for an open box, and renders are confirmed started.
- Kind: 1a

### RSV-016 [resolve-on-the-editors-computer / Connecting to Resolve's scripting: launch, stalls and death]: Resolve crashes after about 13 minutes of continuous scripted work.
- What was going on: A run exporting 57 projects one after another crashed Resolve after about 13 minutes, each export taking well under a minute.
- What the product must do: Long scripted work records progress per item, survives Resolve crashing or hanging, resumes without redoing finished items, and verifies each output exists at the right size.
- Kind: 1a

Sub-topics of `resolve-on-the-editors-computer`: Connecting to Resolve's scripting: launch, stalls and death; Setting Resolve up: edition, scripting switch, preferences; Project libraries and projects; Knowing which project is open; Clip paths and media outside the shared tree; Missing clips, relinking and refreshing; Proxies in Resolve; Multicams, frame rates and timelines; Bins, clip sorting and imports; Colour look-up tables (LUTs); Fixing media: copying in, rehearsals and undo; Grading from the server's originals; Other givens on the editor's computer

## Group M9

Marked to move to `resolve-on-the-editors-computer`:

### CRX-093 [cards-to-resolve-and-exports / Renders from Resolve]: The studio's default render is QuickTime H.264 at 3840x2160, proxies off.
- What was going on: The owner's defaults: QuickTime H.264, timeline frame rate, 3840x2160, proxy media off, best quality, subtitle export off.
- What the product must do: Before a queue starts, each job differing from the studio defaults is listed per project with a yes or no to switch it.
- Kind: 2
- State: outcome not found
- Move to: resolve-on-the-editors-computer

The entries of `resolve-on-the-editors-computer` that read most like it:

### RSV-046 [resolve-on-the-editors-computer / Project libraries and projects]: Resolve names differing only by case overwrote each other's files on Windows.
- What was going on: Resolve project and clip names are case-sensitive and Windows file names are not; one export silently replaced the other and both reported done.
- What the product must do: Names differing only by case stay distinct everywhere, files written from them never collide, and every export is verified present at the right size.
- Kind: 1a

### RSV-115 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Resolve cannot decode VP9 originals at full resolution, though proxies edit fine.
- What was going on: Resolve Studio 21 on Windows logs "Failed to decode the video frame" for VP9 originals and the final render fails; YouTube MP4s are often VP9; AV1 and HEVC render fine.
- What the product must do: The editor is warned as soon as a timeline uses VP9 originals, naming each clip and the fix, and is warned again for any newly added one.
- Kind: 1a
- State: fixed, never shipped

### RSV-084 [resolve-on-the-editors-computer / Missing clips, relinking and refreshing]: Render In Place files exist only on the computer that rendered them.
- What was going on: A re-synced project lost all 175 Render In Place clips: they pointed at empty folders elsewhere, and after a re-rooting the renders were nowhere on any disk.
- What the product must do: Render In Place files in a synced project reach the NAS like other media, or the editor is told which clips will be offline elsewhere before media moves.
- Kind: 1a

### RSV-116 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Repairing undecodable clips before a deadline render takes seconds, not hours.
- What was going on: A 48-minute re-encode blocked a render; the owner: "just copy the proxy out into the main folder instead of re-encoding each one individually".
- What the product must do: A pre-render repair swaps in an edit-ready copy with the same frame count in seconds per clip, re-encoding only when no matching copy exists.
- Kind: 2

### RSV-020 [resolve-on-the-editors-computer / Connecting to Resolve's scripting: launch, stalls and death]: Blackmagic Proxy Generator runs as the Resolve program itself.
- What was going on: The proxy generator is the Resolve program started with a "-pg" switch, so a process check reads it as Resolve running.
- What the product must do: Detecting Resolve ignores a Resolve process started with the proxy generator switch.
- Kind: 1a
- State: still open

Sub-topics of `resolve-on-the-editors-computer`: Connecting to Resolve's scripting: launch, stalls and death; Setting Resolve up: edition, scripting switch, preferences; Project libraries and projects; Knowing which project is open; Clip paths and media outside the shared tree; Missing clips, relinking and refreshing; Proxies in Resolve; Multicams, frame rates and timelines; Bins, clip sorting and imports; Colour look-up tables (LUTs); Fixing media: copying in, rehearsals and undo; Grading from the server's originals; Other givens on the editor's computer

## Group M10

Marked to move to `resolve-on-the-editors-computer`:

### CRX-094 [cards-to-resolve-and-exports / Renders from Resolve]: Before rendering, clips hidden inside compound clips must be checked online.
- What was going on: Offline media inside compound clips does not show on the timeline.
- What the product must do: Before a render is queued, every clip inside every compound clip on the timeline is checked, and offline ones are named.
- Kind: 2
- State: outcome not found
- Move to: resolve-on-the-editors-computer

The entries of `resolve-on-the-editors-computer` that read most like it:

### RSV-084 [resolve-on-the-editors-computer / Missing clips, relinking and refreshing]: Render In Place files exist only on the computer that rendered them.
- What was going on: A re-synced project lost all 175 Render In Place clips: they pointed at empty folders elsewhere, and after a re-rooting the renders were nowhere on any disk.
- What the product must do: Render In Place files in a synced project reach the NAS like other media, or the editor is told which clips will be offline elsewhere before media moves.
- Kind: 1a

### RSV-103 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Resolve's scripting reports no file path and no angles for multicam clips.
- What was going on: A multicam answers "" for its file path and scripting shows nothing of its angles; on a 904-item multicam timeline scripting found 0-3 paths in 4-14 s, against 44 angle files really used.
- What the product must do: Every multicam and compound clip's source files are found from its angles, and a timeline of multicams never reads as having no media.
- Kind: 1a

### RSV-118 [resolve-on-the-editors-computer / Bins, clip sorting and imports]: Resolve calls an ordinary clip's type "Video + Audio".
- What was going on: Testing for audio first filed nearly every clip as audio (174 clips called music), and compound clips landed in effects.
- What the product must do: A clip with picture is never classed as audio, compound clips get their own bin, and a file named like a YouTube download is filed as YouTube.
- Kind: 1a

### RSV-107 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Importing a timeline into a project that holds its multicams duplicates them.
- What was going on: Resolve dedupes footage by path but re-imports multicam and compound clips as "... import" copies, and the grade lives inside the multicam, so copies split the grade.
- What the product must do: Combined projects keep one copy of each multicam, matched by unique total duration since multicams share timecode, and leftovers are set aside, not lost.
- Kind: 1a

### RSV-080 [resolve-on-the-editors-computer / Missing clips, relinking and refreshing]: Resolve's media pool can show a relinked clip offline until the bin changes.
- What was going on: After a scripted relink some clips showed offline in the media pool though fine on the timeline; going to another bin and back cleared it.
- What the product must do: After relinking, the product checks each clip's status itself rather than trusting the media pool's display, and tells the person a bin switch refreshes it.
- Kind: 1a

Sub-topics of `resolve-on-the-editors-computer`: Connecting to Resolve's scripting: launch, stalls and death; Setting Resolve up: edition, scripting switch, preferences; Project libraries and projects; Knowing which project is open; Clip paths and media outside the shared tree; Missing clips, relinking and refreshing; Proxies in Resolve; Multicams, frame rates and timelines; Bins, clip sorting and imports; Colour look-up tables (LUTs); Fixing media: copying in, rehearsals and undo; Grading from the server's originals; Other givens on the editor's computer

## Group M11

Marked to move to `resolve-on-the-editors-computer`:

### CRX-096 [cards-to-resolve-and-exports / Titles and compound clips]: Compound clips should carry the name and colour of what they hold.
- What was going on: Resolve names new compound clips "Compound Clip 1, 2..."; the owner wants each named after its clip and coloured like that interviewee's multicam.
- What the product must do: A compound clip the product creates is named after the clip it wraps and takes the clip colour of the related interviewee's multicam.
- Kind: 2
- State: outcome not found
- Move to: resolve-on-the-editors-computer

The entries of `resolve-on-the-editors-computer` that read most like it:

### RSV-104 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: A multicam angle can be a compound clip or several camera files in a row.
- What was going on: Four interviews had a compound clip as angle 1, and others had angle 1 spread over several camera files, leaving black stretches when only the first was used.
- What the product must do: Anything built from a multicam angle follows compound clips down to the camera files and places every file at its own time.
- Kind: 1a

### RSV-118 [resolve-on-the-editors-computer / Bins, clip sorting and imports]: Resolve calls an ordinary clip's type "Video + Audio".
- What was going on: Testing for audio first filed nearly every clip as audio (174 clips called music), and compound clips landed in effects.
- What the product must do: A clip with picture is never classed as audio, compound clips get their own bin, and a file named like a YouTube download is filed as YouTube.
- Kind: 1a

### RSV-129 [resolve-on-the-editors-computer / Colour look-up tables (LUTs)]: LUT packs unzipped from a Mac carry junk files with real LUT extensions.
- What was going on: Mac-made zips hold __MACOSX folders and "._" companion files of 176 B or 4 KB named like LUTs; a scan by extension would have copied about 139 junk files.
- What the product must do: LUT sharing and every stray-file scan skip __MACOSX folders and files whose names start with "._".
- Kind: 1a

### RSV-119 [resolve-on-the-editors-computer / Bins, clip sorting and imports]: Resolve's scripting can read a bin's name but cannot rename a bin.
- What was going on: The owner asked for a bin's capitalisation fixed, and it had to be done by hand.
- What the product must do: Bins the product creates are named correctly when created, and a needed rename is listed for the person instead of claimed as done.
- Kind: 1a

### RSV-103 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Resolve's scripting reports no file path and no angles for multicam clips.
- What was going on: A multicam answers "" for its file path and scripting shows nothing of its angles; on a 904-item multicam timeline scripting found 0-3 paths in 4-14 s, against 44 angle files really used.
- What the product must do: Every multicam and compound clip's source files are found from its angles, and a timeline of multicams never reads as having no media.
- Kind: 1a

Sub-topics of `resolve-on-the-editors-computer`: Connecting to Resolve's scripting: launch, stalls and death; Setting Resolve up: edition, scripting switch, preferences; Project libraries and projects; Knowing which project is open; Clip paths and media outside the shared tree; Missing clips, relinking and refreshing; Proxies in Resolve; Multicams, frame rates and timelines; Bins, clip sorting and imports; Colour look-up tables (LUTs); Fixing media: copying in, rehearsals and undo; Grading from the server's originals; Other givens on the editor's computer

## Group M12

Marked to move to `resolve-on-the-editors-computer`:

### CRX-097 [cards-to-resolve-and-exports / Titles and compound clips]: Name titles sat half off screen and could cover the speaker.
- What was going on: Left titles were placed by their far edge and right ones ran off frame; the owner wants the visible edge 50 px in, opposite the speaker.
- What the product must do: A name title's visible edge sits 50 px in from the side and bottom, on the side away from where the speaker appears.
- Kind: 2
- State: outcome not found
- Move to: resolve-on-the-editors-computer

The entries of `resolve-on-the-editors-computer` that read most like it:

### RSV-056 [resolve-on-the-editors-computer / Knowing which project is open]: The fix list pointed clips at another project's folder and ran off screen.
- What was going on: In one project the fix list proposed moving clips into a different project's folder, showed empty rows, sat off the top of the screen and could not scroll.
- What the product must do: Fix suggestions target only the open project's folder, empty rows never appear, and the window fits the screen and scrolls.
- Kind: 3
- State: outcome not found

### RSV-109 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Resolve places scripted clips a frame early and reports odd source times.
- What was going on: An append asked for frame 1238 landed at 1237; the source start counts from the file's start timecode; and Resolve reported an empty frame count for one WAV.
- What the product must do: Every clip placed in Resolve by script is read back and re-laid once if it is off by a frame.
- Kind: 1a

### RSV-123 [resolve-on-the-editors-computer / Bins, clip sorting and imports]: Sorting again never re-sorts clips already placed.
- What was going on: The owner wanted sorted clips remembered, existing theme bins preferred over new ones, and interview bins left alone, to avoid "an insane number of categories".
- What the product must do: A repeat sort moves only new clips, files them into existing matching bins before proposing any new bin, and never touches interview bins.
- Kind: 2

### RSV-132 [resolve-on-the-editors-computer / Fixing media: copying in, rehearsals and undo]: Resolve's own Undo does not cover clip relinks made by script.
- What was going on: Relinks made through scripting, some unprompted, cannot be undone in Resolve, and nothing else saved the project or kept the old paths.
- What the product must do: Before any change to a Resolve project the product saves and exports the project and records the old paths, so every change can be undone.
- Kind: 1a

### RSV-011 [resolve-on-the-editors-computer / Connecting to Resolve's scripting: launch, stalls and death]: Any open Resolve dialog makes its scripting answer nothing, for every program.
- What was going on: An "Audio Output: device not found" box (speaker unplugged, or "Remote Audio" after Remote Desktop) appears on project load; until clicked, calls return nothing and queued renders sit at Ready.
- What the product must do: Empty answers mean "Resolve cannot answer now", never missing data; nothing is written meanwhile, the person is told to check Resolve for an open box, and renders are confirmed started.
- Kind: 1a

Sub-topics of `resolve-on-the-editors-computer`: Connecting to Resolve's scripting: launch, stalls and death; Setting Resolve up: edition, scripting switch, preferences; Project libraries and projects; Knowing which project is open; Clip paths and media outside the shared tree; Missing clips, relinking and refreshing; Proxies in Resolve; Multicams, frame rates and timelines; Bins, clip sorting and imports; Colour look-up tables (LUTs); Fixing media: copying in, rehearsals and undo; Grading from the server's originals; Other givens on the editor's computer

## Group M13

Marked to move to `resolve-on-the-editors-computer`:

### CRX-098 [cards-to-resolve-and-exports / Titles and compound clips]: When one interviewee cuts straight to another, name titles hand over.
- What was going on: The owner: with no b-roll between, "the outro for the previous third plays and the new third for the new interviewee comes in. Obviously."
- What the product must do: On a direct cut between two speakers, the first speaker's title plays its exit and the second speaker's title plays its entrance.
- Kind: 2
- State: outcome not found
- Move to: resolve-on-the-editors-computer

The entries of `resolve-on-the-editors-computer` that read most like it:

### RSV-146 [resolve-on-the-editors-computer / Grading from the server's originals]: Grade from the server's full-quality originals, then switch back to proxies.
- What was going on: The owner wanted a remote colourist to "momentarily swap to a direct map of the server" to view originals while grading, then click back.
- What the product must do: Any editor can switch their project drive to the server's originals and back again in one action, with no relinking and syncing unaffected.
- Kind: 2

### RSV-121 [resolve-on-the-editors-computer / Bins, clip sorting and imports]: Each interviewee gets their own bin, with their sound recordings beside their footage.
- What was going on: The owner wanted a bin per interviewee, detected from their folder name, holding all footage from that folder plus the field-recorder audio files.
- What the product must do: Sorting creates one bin per interviewee folder and puts all that folder's video and sound-recorder files in it.
- Kind: 2

### RSV-119 [resolve-on-the-editors-computer / Bins, clip sorting and imports]: Resolve's scripting can read a bin's name but cannot rename a bin.
- What was going on: The owner asked for a bin's capitalisation fixed, and it had to be done by hand.
- What the product must do: Bins the product creates are named correctly when created, and a needed rename is listed for the person instead of claimed as done.
- Kind: 1a

### RSV-130 [resolve-on-the-editors-computer / Colour look-up tables (LUTs)]: One shared LUT library that every editor's Resolve reads directly.
- What was going on: Each editor's LUTs lived only on their own computer; the owner asked for one shared LUT folder on the NAS, kept in sync, with Resolve pointed straight at it.
- What the product must do: Every editor receives the shared LUT folder without ticking anything, and Resolve on every computer lists the LUTs from it.
- Kind: 2

### RSV-101 [resolve-on-the-editors-computer / Proxies in Resolve]: Resolve pairs a proxy with its clip only by exact file name.
- What was going on: A proxy whose name differs from the original's by even one character is not attached, so the clip plays the original or goes offline.
- What the product must do: A proxy always carries exactly the original's name, byte for byte, on every computer.
- Kind: 1a

Sub-topics of `resolve-on-the-editors-computer`: Connecting to Resolve's scripting: launch, stalls and death; Setting Resolve up: edition, scripting switch, preferences; Project libraries and projects; Knowing which project is open; Clip paths and media outside the shared tree; Missing clips, relinking and refreshing; Proxies in Resolve; Multicams, frame rates and timelines; Bins, clip sorting and imports; Colour look-up tables (LUTs); Fixing media: copying in, rehearsals and undo; Grading from the server's originals; Other givens on the editor's computer

## Group M14

Marked to move to `cards-editor`:

### DSH-129 [dashboard / Speed under load]: Each edit in the editor recomputed the whole cut.
- What was going on: Recomputing every card's words after each edit took 4 s at 97% of a core.
- What the product must do: Work done per edit scales with the edit, not with the whole cut.
- Kind: 3
- Move to: cards-editor

The entries of `cards-editor` that read most like it:

### CE2-092 [cards-editor / Shortening and the assistant]: Shortening used a massive amount of assistant capacity.
- What was going on: Each of about 50 calls per pass carried six transcripts and the whole cut, about 180,000 tokens; a one-person search read 322,000 characters for a 97,000-character transcript.
- What the product must do: Each call carries only what that step needs, so a one-section or one-person request costs in proportion to that material, and each pass logs its cost.
- Kind: 2

### CE2-173 [cards-editor / Speed and smoothness]: Opening a big episode ate a server core for seconds.
- What was going on: An episode of 1,166 cards and 114,245 words cost seconds of server CPU per page open, slowing everything else the server did.
- What the product must do: Opening or editing the largest episode never makes other dashboard requests or reports wait.
- Kind: 3

### CE1-022 [cards-editor / House style and the assistant]: The film reads as one conversation between people who never met.
- What was going on: The owner: people answering each other "'accidentally' is a core part of my style ... one large conversation"; suspense by withholding, partial sentences when tenser, splices highlighted.
- What the product must do: Assisted ordering and cutting see cards in cut order and choose each as a reply to the one before; the house style is the owner's to edit per series.
- Kind: 2

### CE2-010 [cards-editor / The lane: clicking, trimming and dragging]: A trimmed clip kept its whole sentence, and its English lagged.
- What was going on: Cutting a trimmed clip's text to its remaining words went through the server, which refused it on one host and gave up; when it worked it took seconds.
- What the product must do: After a trim or split the clip shows only the words inside its edges, and their English, in the same frame as the edit, with no network wait.
- Kind: 3

### CE3-063 [cards-editor / Shortening and the edit chat]: An assisted edit applies whole or not at all.
- What was going on: Two thirds of a request carried out is not what was asked, and undoing it under later edits takes away other work.
- What the product must do: If any step fails, every step already made is undone; undoing an assisted edit is refused once anything else has changed the cut since.
- Kind: 3

Sub-topics of `cards-editor`: Chinese text and matching; Search and the transcript panel; The English a cut shows; House style and the assistant; Shortening; Editing: selecting, deleting, inserting; Notes and the staged shelf; The cut list, undo and saving; Edit speed and answering the editor; Playback and audio; Lane clicks and keys; Game controller; Phone; Panels and layout; Opening episodes, restarts and Resolve; Offline and several devices; Connections; The lane: clicking, trimming and dragging; Cards, selection and keys; Sections and the overview; Colours; Media the browser gets; Shortening and the assistant; Working offline; Several people and devices; Phones, installing and the controller; Speed and smoothness; Opening episodes and keeping the editor running; The lane: how clips look and read; The lane: zoom, scrolling and dragging; Editing, undo and the cut list; Shortening and the edit chat; Working offline and on several devices; Resolve is optional; Phone and game controller; The page: header, warnings and redrawing; Opening episodes

## Group M15

Marked to move to `releases-and-updates`:

### APP-067 [editor-app / Starting, staying running and crashing]: After an update the app was gone until someone restarted it by hand.
- What was going on: The new version started while the old one still held the run-once lock and quit, and "update complete" was reported without checking the new app stayed up.
- What the product must do: After an update exactly one copy runs; success is reported only if the new app is still running seconds later, and otherwise the old one keeps running.
- Kind: 3
- Move to: releases-and-updates

The entries of `releases-and-updates` that read most like it:

### REL-046 [releases-and-updates / Installing an update on an editor's computer]: An update failed but reported success, leaving the old build running for days.
- What was going on: The install step failed yet exited cleanly, relaunched the old build, and the release reported complete.
- What the product must do: An update is reported done only once the new version is confirmed running; otherwise it says it failed and names the version still running.
- Kind: 3

### REL-047 [releases-and-updates / Installing an update on an editor's computer]: After a one-click update no app was running at all.
- What was going on: The new copy started while the old one still held the one-copy-only lock, waited a fixed 20 seconds, gave up, and the old copy exited too.
- What the product must do: After an update exactly one app is running, however long the old copy takes to stop mid-transfer, and a new copy dying on start rolls back.
- Kind: 3

### REL-003 [releases-and-updates / Facts about Windows, macOS and the NAS that bite an update]: Windows antivirus held the installed program, and the update still said complete.
- What was going on: Windows antivirus can hold an installed program file for over ten seconds, so replacing it fails and the old version starts again.
- What the product must do: An update that cannot replace the program reports failure, says what holds the file, and is never counted as installed.
- Kind: 1a

### REL-004 [releases-and-updates / Facts about Windows, macOS and the NAS that bite an update]: A file someone has open over the share cannot be replaced.
- What was going on: An editor running the installer straight off the NAS share kept it open, so publishing a new one failed, yet the release said it was complete.
- What the product must do: When publishing cannot replace a file on the share, the release fails loudly and names the file.
- Kind: 1a

### REL-052 [releases-and-updates / Installing an update on an editor's computer]: Installing an update threw away an upload that had run for hours.
- What was going on: Pushed and unattended updates restarted the app without waiting, so a large upload started again from zero and jobs were killed.
- What the product must do: An update waits for uploads, fetches and jobs to reach a safe point, or they resume where they stopped, unless a person chooses otherwise.
- Kind: 3
- State: still open

Sub-topics of `releases-and-updates`: Facts about Windows, macOS and the NAS that bite an update; Version numbers; Signing and trust; Making and publishing a release; Trying a build on one computer first; Offering an update to a computer; Installing an update on an editor's computer; Pushing updates and seeing who has what; Rolling back and withdrawing a build; The server updating itself; Customer sites and the vendor's release feed

## Group M16

Marked to move to `releases-and-updates`:

### APP-068 [editor-app / Starting, staying running and crashing]: A new build that died on start was never rolled back.
- What was going on: Deaths before the app finished starting were not counted as failed starts, so sync stopped until someone restored the old build by hand on each machine.
- What the product must do: After two failed starts of a new build, the app restores the previous build by itself and syncing resumes with no one touching the machine.
- Kind: 3
- State: fixed, never shipped
- Move to: releases-and-updates

The entries of `releases-and-updates` that read most like it:

### REL-048 [releases-and-updates / Installing an update on an editor's computer]: An update that crashed minutes after starting left the editor with no app.
- What was going on: The previous build was deleted a minute after updating, and a macOS login item never restarts a crashed app.
- What the product must do: The previous build is kept until the new one proves healthy, and three crashing starts within 10 minutes restore it, never below the signed minimum, and tell the editor.
- Kind: 3
- State: outcome not found

### REL-042 [releases-and-updates / Offering an update to a computer]: An Intel Mac was offered an Apple silicon build it could never run.
- What was going on: Builds were matched by operating system only, from some offer paths, so the Mac downloaded, failed to start and rolled back for ever.
- What the product must do: Every offer, from every path, matches the computer's operating system and processor, and when no build exists for it the computer and dashboard say so.
- Kind: 3

### REL-025 [releases-and-updates / Making and publishing a release]: A failed installer build was published under the new version carrying the old app.
- What was going on: When building the installer failed, the previous build was uploaded under the new number, and the channel then refused that number for the real build.
- What the product must do: A build that fails at any step is never published, and every published version contains exactly the code built for it.
- Kind: 3

### REL-070 [releases-and-updates / The server updating itself]: A stale server froze every app update where nobody clicks.
- What was going on: App updates need a minimum server version, and the server was the one part with no unattended update.
- What the product must do: On a site set to follow the vendor, the server updates itself after the waiting period, rolls back if it will not start, and never retries a failed build unattended.
- Kind: 3

### REL-049 [releases-and-updates / Installing an update on an editor's computer]: A computer reinstalled the crashing build it had just rolled back from.
- What was going on: The next offer or push handed back the same build, and an admin's own rollback of the server was overridden every ten seconds the same way.
- What the product must do: A build undone on a computer or server is never installed there again automatically, only a newer one, and an admin's push of it is refused in words.
- Kind: 3
- State: fixed, never shipped

Sub-topics of `releases-and-updates`: Facts about Windows, macOS and the NAS that bite an update; Version numbers; Signing and trust; Making and publishing a release; Trying a build on one computer first; Offering an update to a computer; Installing an update on an editor's computer; Pushing updates and seeing who has what; Rolling back and withdrawing a build; The server updating itself; Customer sites and the vendor's release feed

## Group M17

Marked to move to `releases-and-updates`:

### APP-069 [editor-app / Starting, staying running and crashing]: An update interrupted mid-swap left the computer with no app at all.
- What was going on: A power cut, reboot or antivirus quarantine between moving the old program aside and placing the new one left nothing to start.
- What the product must do: An interrupted self-update restores a runnable app without a person, and recovery never overwrites an app that is present.
- Kind: 3
- Move to: releases-and-updates

The entries of `releases-and-updates` that read most like it:

### REL-050 [releases-and-updates / Installing an update on an editor's computer]: An update killed midway left nothing to start at sign-in.
- What was going on: For a moment during a self-update no program exists at the expected path, and a kill then leaves nothing to start.
- What the product must do: An update interrupted at any point leaves a program that starts at sign-in, recovered without a person renaming files.
- Kind: 3
- State: outcome not found

### REL-054 [releases-and-updates / Installing an update on an editor's computer]: A computer that could not install an update retried every ten minutes for ever.
- What was going on: Antivirus quarantine, a corrupted download or a full disk failed every attempt, refetching 20 MB each time while the push showed pending.
- What the product must do: Failed attempts back off from 10 minutes to 1 hour to 6 hours and stop after 8 with the reason shown; a push expires after 14 days.
- Kind: 3

### REL-068 [releases-and-updates / The server updating itself]: A server killed mid-update refused every later update and rollback.
- What was going on: Power loss or a kill during the restart left "update in progress" recorded, and only a shell could clear it.
- What the product must do: An "in progress" left by a dead process becomes "failed, interrupted" on start, and update and rollback work again from the page.
- Kind: 3

### REL-003 [releases-and-updates / Facts about Windows, macOS and the NAS that bite an update]: Windows antivirus held the installed program, and the update still said complete.
- What was going on: Windows antivirus can hold an installed program file for over ten seconds, so replacing it fails and the old version starts again.
- What the product must do: An update that cannot replace the program reports failure, says what holds the file, and is never counted as installed.
- Kind: 1a

### REL-051 [releases-and-updates / Installing an update on an editor's computer]: Crash-loop protection went silent when the app could not write its records.
- What was going on: With the home folder full or locked by antivirus, the app could not record its starts, so a crashing build was never reverted.
- What the product must do: When the app cannot record a start it warns naming where, and never treats that as "nothing known" about crashes.
- Kind: 3

Sub-topics of `releases-and-updates`: Facts about Windows, macOS and the NAS that bite an update; Version numbers; Signing and trust; Making and publishing a release; Trying a build on one computer first; Offering an update to a computer; Installing an update on an editor's computer; Pushing updates and seeing who has what; Rolling back and withdrawing a build; The server updating itself; Customer sites and the vendor's release feed

## Group M18

Marked to move to `resolve-on-the-editors-computer`:

### APP-104 [editor-app / Windows, dialogs and notifications]: Clips found while a dialog was open were lost behind an "already open" notice.
- What was going on: The owner ruled: "get rid of the popup already open message ... the editor can decide"; clips found meanwhile were silently dropped.
- What the product must do: Clips found while a dialog is open are shown, without duplicates, as soon as it closes, and no "already open" notice appears.
- Kind: 2
- Move to: resolve-on-the-editors-computer

The entries of `resolve-on-the-editors-computer` that read most like it:

### RSV-067 [resolve-on-the-editors-computer / Clip paths and media outside the shared tree]: Clips found while an editor read a popup were silently dropped.
- What was going on: A batch found while one popup was open was discarded behind an "already open" notice re-fired every 3 seconds.
- What the product must do: Later batches queue and show when the current popup closes, deduplicated so the same clips never produce repeated dialogs.
- Kind: 3

### RSV-011 [resolve-on-the-editors-computer / Connecting to Resolve's scripting: launch, stalls and death]: Any open Resolve dialog makes its scripting answer nothing, for every program.
- What was going on: An "Audio Output: device not found" box (speaker unplugged, or "Remote Audio" after Remote Desktop) appears on project load; until clicked, calls return nothing and queued renders sit at Ready.
- What the product must do: Empty answers mean "Resolve cannot answer now", never missing data; nothing is written meanwhile, the person is told to check Resolve for an open box, and renders are confirmed started.
- Kind: 1a

### RSV-061 [resolve-on-the-editors-computer / Clip paths and media outside the shared tree]: On the base computer only media outside the project's own server folder is flagged.
- What was going on: The base got out-of-project popups for media already on the server; careless base work can also leave clips outside, so the owner wanted it narrowed, not removed.
- What the product must do: On the base computer the out-of-project popup lists only clips outside that project's own server folder, never clips already inside it.
- Kind: 2

### RSV-021 [resolve-on-the-editors-computer / Connecting to Resolve's scripting: launch, stalls and death]: Warn every five minutes while Resolve runs without working scripting.
- What was going on: Resolve looks normal while every insert and fix is silently lost; the owner asked for a popup "every five minutes" telling the editor to restart Resolve.
- What the product must do: While Resolve is confirmed running and scripting is unavailable, a warning repeats every five minutes, the first after one full interval, and stops on recovery.
- Kind: 2

### RSV-060 [resolve-on-the-editors-computer / Clip paths and media outside the shared tree]: Media used from outside the project folder raises a warning naming the project.
- What was going on: The owner wanted a popup to move such media "to where it is syncable", and: "this warning should say which project", since it may be an editor's personal project.
- What the product must do: The warning names the clip, the Resolve project and where to move it, and a project that is not one of the studio's synced projects raises nothing.
- Kind: 2

Sub-topics of `resolve-on-the-editors-computer`: Connecting to Resolve's scripting: launch, stalls and death; Setting Resolve up: edition, scripting switch, preferences; Project libraries and projects; Knowing which project is open; Clip paths and media outside the shared tree; Missing clips, relinking and refreshing; Proxies in Resolve; Multicams, frame rates and timelines; Bins, clip sorting and imports; Colour look-up tables (LUTs); Fixing media: copying in, rehearsals and undo; Grading from the server's originals; Other givens on the editor's computer

## Group M19

Marked to move to `resolve-on-the-editors-computer`:

### APP-105 [editor-app / Windows, dialogs and notifications]: A clip from the b-roll archive must not set off the editor's popup.
- What was going on: The archive lives outside any project folder, and the owner warned such a clip should not "flip the trigger for a popup" asking where to file it.
- What the product must do: A timeline clip whose file is in the shared b-roll archive is treated as correctly placed and never prompts the editor.
- Kind: 2
- Move to: resolve-on-the-editors-computer

The entries of `resolve-on-the-editors-computer` that read most like it:

### RSV-060 [resolve-on-the-editors-computer / Clip paths and media outside the shared tree]: Media used from outside the project folder raises a warning naming the project.
- What was going on: The owner wanted a popup to move such media "to where it is syncable", and: "this warning should say which project", since it may be an editor's personal project.
- What the product must do: The warning names the clip, the Resolve project and where to move it, and a project that is not one of the studio's synced projects raises nothing.
- Kind: 2

### RSV-064 [resolve-on-the-editors-computer / Clip paths and media outside the shared tree]: Clips at the right shared path kept being flagged as offline.
- What was going on: Clips relinked to the shared drive path were judged misplaced on the laptop, so the popup kept returning though the files opened fine.
- What the product must do: A clip whose file exists at its shared project-drive path is never flagged, offered for fixing or warned about again.
- Kind: 3

### RSV-131 [resolve-on-the-editors-computer / Colour look-up tables (LUTs)]: A LUT added outside the shared library prompts the editor to copy it in.
- What was going on: The owner wanted the editor asked, whenever they add a LUT that is not in the shared folder, whether to copy it there.
- What the product must do: A LUT in Resolve's LUT locations but outside the shared library triggers an offer to copy it there; nothing is copied or moved unasked.
- Kind: 2

### RSV-127 [resolve-on-the-editors-computer / Colour look-up tables (LUTs)]: Resolve loads DCTL files only from its own LUT folder.
- What was going on: DCTLs placed in an additional LUT location, such as a shared one, are never loaded.
- What the product must do: The product never offers DCTLs through a shared extra LUT location as if Resolve would load them.
- Kind: 1a

### RSV-052 [resolve-on-the-editors-computer / Knowing which project is open]: Resolve's scratch projects look open though nobody is working in them.
- What was going on: Blackmagic Proxy Generator runs a helper project "New Doc", every unsaved project is "Untitled Project", and Resolve numbers copies ("New Doc 1", "Untitled Project (3)").
- What the product must do: These names and numbered copies never trigger prompts, matches or dashboard reports; an editor in "Untitled Project" is told to save under a real name to be asked.
- Kind: 1a

Sub-topics of `resolve-on-the-editors-computer`: Connecting to Resolve's scripting: launch, stalls and death; Setting Resolve up: edition, scripting switch, preferences; Project libraries and projects; Knowing which project is open; Clip paths and media outside the shared tree; Missing clips, relinking and refreshing; Proxies in Resolve; Multicams, frame rates and timelines; Bins, clip sorting and imports; Colour look-up tables (LUTs); Fixing media: copying in, rehearsals and undo; Grading from the server's originals; Other givens on the editor's computer

## Group M20

Marked to move to `resolve-on-the-editors-computer`:

### APP-106 [editor-app / Windows, dialogs and notifications]: Installing on a Mac sets Resolve's path mapping automatically.
- What was going on: The owner asked that a Mac install "auto set resolve path mapping", so projects made on Windows find their media.
- What the product must do: After install on a Mac, Resolve maps the shared drive's Windows paths to the Mac's mount without the editor doing it by hand.
- Kind: 2
- Move to: resolve-on-the-editors-computer

The entries of `resolve-on-the-editors-computer` that read most like it:

### RSV-069 [resolve-on-the-editors-computer / Clip paths and media outside the shared tree]: The broken drive mapping warning wrongly said nothing would sync.
- What was going on: When the media drive letter stopped pointing at the synced folder only Resolve's view broke, yet the warning said all syncing had stopped and offered no repair.
- What the product must do: The warning says clips will show offline while transfers continue, offers a repair on Windows, and refuses to remove a mapping the product did not create.
- Kind: 3

### RSV-058 [resolve-on-the-editors-computer / Clip paths and media outside the shared tree]: Resolve stores a clip's path exactly as it was browsed.
- What was going on: Importing the shared tree through another drive letter or from a Desktop plays locally but is offline on every other computer; one shared project had over 200 such clips, unwarned.
- What the product must do: Every clip imported from inside the tree, by any spelling, ends up stored in the shared spelling automatically, and a clip on a computer-private path is flagged to its importer.
- Kind: 1a

### RSV-059 [resolve-on-the-editors-computer / Clip paths and media outside the shared tree]: Every computer sees the project tree at the same drive and path.
- What was going on: The base computer used one drive letter and editors another, so Resolve projects shared between them could never link; the base was moved to match.
- What the product must do: Every computer, base included, opens the project tree at the identical drive and path, so a Resolve project links the same everywhere.
- Kind: 2

### RSV-103 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Resolve's scripting reports no file path and no angles for multicam clips.
- What was going on: A multicam answers "" for its file path and scripting shows nothing of its angles; on a 904-item multicam timeline scripting found 0-3 paths in 4-14 s, against 44 angle files really used.
- What the product must do: Every multicam and compound clip's source files are found from its angles, and a timeline of multicams never reads as having no media.
- Kind: 1a

### RSV-119 [resolve-on-the-editors-computer / Bins, clip sorting and imports]: Resolve's scripting can read a bin's name but cannot rename a bin.
- What was going on: The owner asked for a bin's capitalisation fixed, and it had to be done by hand.
- What the product must do: Bins the product creates are named correctly when created, and a needed rename is listed for the person instead of claimed as done.
- Kind: 1a

Sub-topics of `resolve-on-the-editors-computer`: Connecting to Resolve's scripting: launch, stalls and death; Setting Resolve up: edition, scripting switch, preferences; Project libraries and projects; Knowing which project is open; Clip paths and media outside the shared tree; Missing clips, relinking and refreshing; Proxies in Resolve; Multicams, frame rates and timelines; Bins, clip sorting and imports; Colour look-up tables (LUTs); Fixing media: copying in, rehearsals and undo; Grading from the server's originals; Other givens on the editor's computer

## Group M21

Marked to move to `proxies-and-file-moves`:

### APP-147 [editor-app / Settings, records and background work]: Background encoding at normal priority slowed Resolve's own render.
- What was going on: Three normal-priority encoders took the processor; dropping them to below normal raised Resolve's output from about 100 to 144 MB/s.
- What the product must do: The product's encoding on an editor's computer runs below normal priority so Resolve keeps its speed.
- Kind: 3
- Move to: proxies-and-file-moves

The entries of `proxies-and-file-moves` that read most like it:

### PRX-008 [proxies-and-file-moves / What Resolve accepts as a proxy]: HEVC proxies played everywhere except Resolve, which showed Media Offline.
- What was going on: Resolve and QuickTime refuse HEVC in MP4 tagged "hev1" (VLC plays it), and common encoders write "hev1" by default.
- What the product must do: Every HEVC-in-MP4 proxy is tagged "hvc1", verified by opening it in Resolve.
- Kind: 1a

### PRX-031 [proxies-and-file-moves / Making proxies on editors' computers]: Proxy making uses the whole computer while idle, but backs off for Resolve.
- What was going on: The owner: idle proxy making "can absolutely max out compute", "unless yeah the computer is doing a render or something else".
- What the product must do: An idle computer encodes several proxies in parallel, dropping to one whenever Resolve is open or rendering, even on a forced run; each computer can override.
- Kind: 2

### PRX-088 [proxies-and-file-moves / Names: letter case and Unicode]: Clips with Chinese names were not found by the relink though on disk.
- What was going on: The file list was read in the wrong text encoding, so Chinese-named clips showed "no match" while the owner's own search found them.
- What the product must do: A clip with Chinese characters in its name is found and relinked exactly as one with an English name.
- Kind: 3

### PRX-021 [proxies-and-file-moves / Raw camera formats and Blackmagic Proxy Generator]: Blackmagic RAW, RED and Canon raw clips sat without proxies for months.
- What was going on: General-purpose encoders cannot decode .braw, .r3d or .crm; the owner: re-encoding them "will require bm proxy generator".
- What the product must do: Raw clips are counted, routed to a decoder that reads them, started without the editor's help, verified like any proxy, and never failed as broken.
- Kind: 1a

### PRX-017 [proxies-and-file-moves / What a proxy must be]: Proxies for odd-height screen recordings failed and were given up on.
- What was going on: Some sources (screen captures, full-colour or lossless video) have an odd pixel width or height, and video encoders refuse odd dimensions.
- What the product must do: A source with an odd width or height still gets a proxy, rounded to even dimensions.
- Kind: 3

Sub-topics of `proxies-and-file-moves`: What Resolve accepts as a proxy; What a proxy must be; Raw camera formats and Blackmagic Proxy Generator; Making proxies on editors' computers; Pairing proxies with their originals; Writing, copying and deleting files safely; Moving footage through the product; Moves that reach every computer; Following a move on an editor's computer; Relinking Resolve after a move; Moves made by hand on the NAS; Names: letter case and Unicode; Relinking and gathering missing clips

## Group M22

Marked to move to `sync`:

### SRT-184 [footage-sorter-and-camera-cards / Filed here, belonging elsewhere]: A camera with a wrong clock dates clips in the future, and they never upload.
- What was going on: Clips dated ahead of now never passed an "old enough to upload" test, and nothing reported it.
- What the product must do: Footage dated in the future is uploaded like any other and reported to the editor, never skipped as too new.
- Kind: 1a
- State: still open
- Move to: sync

The entries of `sync` that read most like it:

### SYN-124 [sync / Clocks and file age]: Footage dated in the future by a wrong camera clock never uploads.
- What was going on: Cameras with clocks set ahead write files dated in the future, and a rule to wait until files stop changing never sees them as settled.
- What the product must do: Future-dated files upload like any other, and the editor sees which file and date are wrong until they are fixed.
- Kind: 3
- State: still open

### SYN-093 [sync / Stuck, slow and fair transfers]: The same camera file was uploaded twice at once, splitting the uplink.
- What was going on: A quick upload of a just-finished file and the regular pass both saw it missing on the NAS and both sent it, over an uplink saturated near 50 Mbit/s.
- What the product must do: A file is never uploaded by two transfers at once, and one skipped for that reason is picked up on the next pass.
- Kind: 3

### SYN-064 [sync / Names]: Camera files with capital-letter extensions were never uploaded.
- What was going on: Cameras write extensions like .MOV and .BRAW in capitals; case-sensitive rules skipped them, and a lowercase "proxy" folder inverted both directions.
- What the product must do: Every file-type and folder-name rule in the sync matches regardless of letter case.
- Kind: 3

### SYN-033 [sync / Deletions and removing a project]: "Remove from this computer" deleted footage the NAS had never received.
- What was going on: Files under two minutes old, future-dated by a camera clock, same-named but different, or not video on an upload-only project, counted as safe and were deleted.
- What the product must do: Removal is refused while any local file, of any age or date, is not on the NAS at the same size and content; it lists and keeps each one.
- Kind: 3
- State: fixed, never shipped

### SYN-117 [sync / Load on the NAS when nothing changes]: Every computer re-sent its unchanged file lists every few minutes.
- What was going on: About 510 MB a day per computer was re-sent and rewritten unchanged, about 47 GB of server writes a day at 20 computers.
- What the product must do: A report about unchanged projects sends and stores almost nothing, idle computers back off, and an over-size report drops only enough detail.
- Kind: 3
- State: still open

Sub-topics of `sync`: What syncs where; A plan belongs to a computer; Wired or remote; Upload only; Deletions and removing a project; Safety stops; Studio-wide stops and the editor's pause; Files that must never sync; Names; The sync drive; Disk space; Stuck, slow and fair transfers; Uploads that cannot resume, shutdown and sleep; Saying truthfully what the sync is doing; What is owed; Load on the NAS when nothing changes; Speed and routes; Clocks and file age; Computers joining and changing; Project folders on an editor's computer; Facts about the NAS and the operating systems

## Group M23

Marked to move to `sync`:

### SRT-185 [footage-sorter-and-camera-cards / Filed here, belonging elsewhere]: Field internet abroad is too slow for uploads and downloads.
- What was going on: Hotel and mobile internet abroad was slow and dropped, so proxy uploads kept failing and downloads ran at about 60 KB/s.
- What the product must do: Field uploads survive slow, dropping connections by resuming, and heavy work such as transcription is left for home.
- Kind: 1a
- Move to: sync

The entries of `sync` that read most like it:

### SYN-121 [sync / Speed and routes]: Another route tripled one remote editor's download speed.
- What was going on: Through a relay in the same city one editor's proxy downloads reached 47-55 MB/s instead of 18; such a relay can answer with a sign-in page that lists as empty.
- What the product must do: A slow editor's downloads can use another read-only route; a failing or empty answer there pauses downloads and never deletes local files.
- Kind: 3

### SYN-118 [sync / Speed and routes]: Transfers must be as fast as the studio saw from Resolve's own cloud.
- What was going on: Owner: "On resolve cloud we get around 60mb/s max up and down", and big transfers must "maximise speed", not ride a slow private network.
- What the product must do: On the same connection uploads and downloads each reach at least 60 MB/s, over the fastest route available, with the achieved speed visible.
- Kind: 2

### SYN-016 [sync / What syncs where]: A mistyped server folder sent camera originals into the editor's home folder.
- What was going on: A server destination that was not a full path was only a warning, so uploads landed in the editor's own home folder on the server, where nothing finds them.
- What the product must do: An empty or relative server destination is refused at install, and nothing uploads or downloads until a valid one is set.
- Kind: 3

### SYN-095 [sync / Stuck, slow and fair transfers]: The sync loop died and the computer kept reporting a frozen healthy state.
- What was going on: An unexpected error, such as the mapped drive dropping mid-pass, ended the sync loop while reports kept sending its last state.
- What the product must do: A failing pass costs one pass; a background loop that dies or stops checking in is restarted within 30 minutes and its restarts are reported.
- Kind: 3

### SYN-084 [sync / Disk space]: Proxy downloads filled a laptop drive until nothing could work.
- What was going on: Nothing measured free space before moving footage, so one "tick everything" filled a laptop, and a full disk then failed downloads file by file.
- What the product must do: Downloads pause below about 20 GB free and resume at 40 GB while uploads continue, recovery copies are pruned under pressure, and a tick first shows its size against free space.
- Kind: 3

Sub-topics of `sync`: What syncs where; A plan belongs to a computer; Wired or remote; Upload only; Deletions and removing a project; Safety stops; Studio-wide stops and the editor's pause; Files that must never sync; Names; The sync drive; Disk space; Stuck, slow and fair transfers; Uploads that cannot resume, shutdown and sleep; Saying truthfully what the sync is doing; What is owed; Load on the NAS when nothing changes; Speed and routes; Clocks and file age; Computers joining and changing; Project folders on an editor's computer; Facts about the NAS and the operating systems

## Group M24

Marked to move to `resolve-on-the-editors-computer`:

### SRT-186 [footage-sorter-and-camera-cards / Filed here, belonging elsewhere]: Re-importing a folder of numbered stills duplicates them in Resolve.
- What was going on: Resolve groups numbered JPGs into image sequences whose path is not one file, so an "already imported" check misses them; 941 stills became 86 sequences and 50 stills.
- What the product must do: Re-importing a folder into Resolve never adds a second copy of stills it already holds as image sequences.
- Kind: 1a
- State: outcome not found
- Move to: resolve-on-the-editors-computer

The entries of `resolve-on-the-editors-computer` that read most like it:

### RSV-038 [resolve-on-the-editors-computer / Setting Resolve up: edition, scripting switch, preferences]: Resolve warned at every launch that the stills location differed between computers.
- What was going on: Resolve derives its stills gallery folder from the first numbered media storage entry, normally each computer's own scratch disk; the render cache also refers to entry one by number.
- What the product must do: Every computer sharing a project library uses one shared stills location, the first media storage entry never moves, and nothing changes until the shared folder exists.
- Kind: 1a

### RSV-088 [resolve-on-the-editors-computer / Missing clips, relinking and refreshing]: Refreshing a clip may drop the proxy it was playing.
- What was going on: Re-importing a clip that was playing its editing proxy may clear that attachment, leaving it on the original or offline; never confirmed on a live Resolve.
- What the product must do: After any refresh, a clip that was playing a proxy is still playing it.
- Kind: 3

### RSV-079 [resolve-on-the-editors-computer / Missing clips, relinking and refreshing]: Resolve reports an image sequence by a bracketed path that never exists on disk.
- What was going on: Resolve keeps a sequence as "Name_[00000-00287].exr" even after relinking, so every sequence looked offline; replacing with the first frame relinks the whole sequence.
- What the product must do: An image-sequence clip counts as online when its first frame exists, and is relinked by pointing at that first frame.
- Kind: 1a

### RSV-002 [resolve-on-the-editors-computer / Connecting to Resolve's scripting: launch, stalls and death]: A connect attempt with no script server present blocks about four seconds.
- What was going on: The connect call retries about 4 s (8 s behind a second thread) instead of failing, so a "quick check" is mid-connect when the server appears; a fixed wait after launch misses the window.
- What the product must do: Readiness is judged from the script server and Resolve's connection to it, never from a delay after Resolve starts, and no check ever attempts a connection to find out.
- Kind: 1a

### RSV-107 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Importing a timeline into a project that holds its multicams duplicates them.
- What was going on: Resolve dedupes footage by path but re-imports multicam and compound clips as "... import" copies, and the grade lives inside the multicam, so copies split the grade.
- What the product must do: Combined projects keep one copy of each multicam, matched by unique total duration since multicams share timecode, and leftovers are set aside, not lost.
- Kind: 1a

Sub-topics of `resolve-on-the-editors-computer`: Connecting to Resolve's scripting: launch, stalls and death; Setting Resolve up: edition, scripting switch, preferences; Project libraries and projects; Knowing which project is open; Clip paths and media outside the shared tree; Missing clips, relinking and refreshing; Proxies in Resolve; Multicams, frame rates and timelines; Bins, clip sorting and imports; Colour look-up tables (LUTs); Fixing media: copying in, rehearsals and undo; Grading from the server's originals; Other givens on the editor's computer

## Group M25

Marked to move to `cards-to-resolve-and-exports`:

### RSV-117 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: A conformed timeline had no sound on one editor's computer.
- What was going on: Every audio clip, multicam source and file was present for that editor, yet the conformed timeline played silent; the cause was never found.
- What the product must do: When a conformed timeline is silent on one computer, the product can check that computer's playback and offline clips and say which is at fault.
- Kind: 3
- State: outcome not found
- Move to: cards-to-resolve-and-exports

The entries of `cards-to-resolve-and-exports` that read most like it:

### CRX-094 [cards-to-resolve-and-exports / Renders from Resolve]: Before rendering, clips hidden inside compound clips must be checked online.
- What was going on: Offline media inside compound clips does not show on the timeline.
- What the product must do: Before a render is queued, every clip inside every compound clip on the timeline is checked, and offline ones are named.
- Kind: 2
- State: outcome not found
- Move to: resolve-on-the-editors-computer

### CRX-073 [cards-to-resolve-and-exports / Sending a cut to Resolve]: A build stopped early left 54 cuts with no audio or markers.
- What was going on: The build placed all video first, then audio, then markers, and with no timeline open the status flickered between available and unreachable.
- What the product must do: A send reports done only when picture, sound and markers are all placed, flags any partial timeline, and keeps a steady status while Resolve is idle.
- Kind: 3
- State: still open

### CRX-096 [cards-to-resolve-and-exports / Titles and compound clips]: Compound clips should carry the name and colour of what they hold.
- What was going on: Resolve names new compound clips "Compound Clip 1, 2..."; the owner wants each named after its clip and coloured like that interviewee's multicam.
- What the product must do: A compound clip the product creates is named after the clip it wraps and takes the clip colour of the related interviewee's multicam.
- Kind: 2
- State: outcome not found
- Move to: resolve-on-the-editors-computer

### CRX-032 [cards-to-resolve-and-exports / Placing, deleting and linking clips in Resolve]: Sending a cut refused every clip because names had been shortened.
- What was going on: The cards dropped " Multicam" and the extension from names, but Resolve finds clips only by exact media pool name, odd casing like "MultiCam" included.
- What the product must do: Clips are identified by exact media pool name or unique id, never by a shortened display name.
- Kind: 3

### CRX-018 [cards-to-resolve-and-exports / Placing, deleting and linking clips in Resolve]: A scripted delete in Resolve leaves the clip's linked audio behind.
- What was going on: The leftover audio silently blocks later appends over those frames while the call reports success, and left another interviewee's sound duplicated underneath a moved cut.
- What the product must do: Removing or moving a cut removes its picture and sound together, and no orphaned or duplicated sound is left on the timeline.
- Kind: 1a

Sub-topics of `cards-to-resolve-and-exports`: Frames, frame rates and timecode; Placing, deleting and linking clips in Resolve; Undo, markers, titles, fades and properties; Talking to Resolve: restarts, dialogs and speed; Sending a cut to Resolve; Edits sent live and staged edits; Bringing Resolve's changes back into the cut; Which computer is driving Resolve; Exports; Renders from Resolve; Titles and compound clips; Subtitles and delivery

## Group M26

Marked to move to `editor-app`:

### RSV-150 [resolve-on-the-editors-computer / Other givens on the editor's computer]: Send to Resolve failed when the dashboard address differed from the browser's.
- What was going on: The editor's app accepts browser requests only from the configured dashboard address, so another spelling of the same address refused every Send to Resolve.
- What the product must do: Site settings warn that the dashboard address must be exactly what editors type, and a refusal names both addresses.
- Kind: 3
- Move to: editor-app

The entries of `editor-app` that read most like it:

### APP-085 [editor-app / The tray or menu-bar icon and its menu]: "Open dashboard" did nothing when clicked.
- What was going on: On a remote editor's computer the open-dashboard action silently failed to open a browser.
- What the product must do: If opening the dashboard fails, the person is told and shown the address to open by hand.
- Kind: 3
- State: outcome not found

### APP-081 [editor-app / The tray or menu-bar icon and its menu]: The tray's "Open dashboard" opened an address browsers could not use.
- What was going on: The owner wanted the link to work for remote editors too; after the dashboard went https-only for browsers, the tray still opened the plain address the app reports to.
- What the product must do: "Open dashboard" opens the address the site publishes for people, reachable from wherever the computer is, falling back to the reporting address only when none is published.
- Kind: 2

### APP-022 [editor-app / Installing and setting up]: A dashboard address typed without a scheme, or on port 8443, never connected.
- What was going on: Editors type the bare name the admin gave them; setup rejected it silently, or guessed http or https from the port and saved the wrong guess.
- What the product must do: A typed scheme is always kept; without one, secure is tried first, a guess is never saved silently, and the check says "not reachable" or "not a dashboard".
- Kind: 3

### APP-133 [editor-app / Settings, records and background work]: An update must never reset a computer's own settings.
- What was going on: An editor's Resolve is installed off the C: drive, and the owner required that updating the app never resets that setting.
- What the product must do: After any update, every setting chosen on that computer, including where Resolve is installed, is unchanged.
- Kind: 2
- State: outcome not found

### APP-138 [editor-app / Settings, records and background work]: A feature switched on for the site never reached apps already running.
- What was going on: Site settings were read once at start, so a switch flipped later, or an app that started offline, waited for a restart.
- What the product must do: Site settings changes reach every running app within minutes, with no restart, and an app that started offline picks them up when it reconnects.
- Kind: 3

Sub-topics of `editor-app`: Installing and setting up; Security warnings, permissions and certificates; Drive letters and network drives; Starting, staying running and crashing; The tray or menu-bar icon and its menu; Windows, dialogs and notifications; Telling the editor what is wrong; Signing in, the computer's identity and the licence; Settings, records and background work; Uninstalling

## Group M27

Marked to move to `editor-app`:

### RSV-151 [resolve-on-the-editors-computer / Other givens on the editor's computer]: Send to Resolve did nothing when another program held the app's local port.
- What was going on: The app tried its local listening port once at start; when another program held it, the app still believed it was serving and only the browser saw failures.
- What the product must do: The local port's health is retried, shown on the computer and reported to the dashboard, which warns when the feature is on and the port is not ours.
- Kind: 3
- Move to: editor-app

The entries of `editor-app` that read most like it:

### APP-140 [editor-app / Settings, records and background work]: Setting the local helper's port to 0 silently killed Send to Resolve.
- What was going on: Port 0 means "any free port", so the helper came up where no web page could find it while the app reported it fine.
- What the product must do: An invalid helper port is refused with a warning and the standard port used; switching the helper off is a separate, explicit setting.
- Kind: 3

### APP-041 [editor-app / Drive letters and network drives]: The app removed a drive mapping it did not create, breaking every Resolve path.
- What was going on: Install, update, uninstall and a grading feature removed the NAS mapping on the project letter, reading "cannot tell" as "ours", or acting on an unverified default role.
- What the product must do: A drive mapping is removed or replaced only when provably the product's own; when unsure, or the chosen and verified roles disagree, it is left and the editor asked.
- Kind: 3

### APP-022 [editor-app / Installing and setting up]: A dashboard address typed without a scheme, or on port 8443, never connected.
- What was going on: Editors type the bare name the admin gave them; setup rejected it silently, or guessed http or https from the port and saved the wrong guess.
- What the product must do: A typed scheme is always kept; without one, secure is tried first, a guess is never saved silently, and the check says "not reachable" or "not a dashboard".
- Kind: 3

### APP-085 [editor-app / The tray or menu-bar icon and its menu]: "Open dashboard" did nothing when clicked.
- What was going on: On a remote editor's computer the open-dashboard action silently failed to open a browser.
- What the product must do: If opening the dashboard fails, the person is told and shown the address to open by hand.
- Kind: 3
- State: outcome not found

### APP-121 [editor-app / Telling the editor what is wrong]: A repeating warning rotated away the log history support needed.
- What was going on: A port held by another program logged six lines every two minutes, and a per-clip "missing" line filled the 5 MB log every 25 minutes.
- What the product must do: A recurring condition is logged loudly once when it starts, then as a count per pass until it changes, so the log keeps days of history.
- Kind: 3

Sub-topics of `editor-app`: Installing and setting up; Security warnings, permissions and certificates; Drive letters and network drives; Starting, staying running and crashing; The tray or menu-bar icon and its menu; Windows, dialogs and notifications; Telling the editor what is wrong; Signing in, the computer's identity and the licence; Settings, records and background work; Uninstalling

## Group M28

Marked to move to `youtube`:

### SYN-061 [sync / Files that must never sync]: A YouTube download that keeps getting cut short is retried at a lower quality.
- What was going on: Partial and fragment files from repeatedly truncated YouTube downloads sat in a synced project folder.
- What the product must do: A download truncated repeatedly retries one quality step lower rather than leaving partial files.
- Kind: 3
- Move to: youtube

The entries of `youtube` that read most like it:

### YTD-026 [youtube / How YouTube throttles and refuses]: One quality of a clip can arrive truncated every time while another works.
- What was going on: One clip's 1080p stream died at about 10 MB on every attempt from two different networks, while 720p downloaded fine.
- What the product must do: A truncated download retries once a quality lower and records it; a transient refusal never lowers quality, and a final failure removes its partial files.
- Kind: 1a

### YTD-060 [youtube / Where a download runs, and saying so]: Computers took download jobs they could not finish.
- What was going on: A computer without the tool that merges video and audio accepted jobs and failed every clip, and computers claimed qualities they could not handle, leaving jobs idle three minutes.
- What the product must do: A computer takes a download job only if it can complete it (tools, quality, project); otherwise the job starts elsewhere at once.
- Kind: 3

### YTD-062 [youtube / Where a download runs, and saying so]: A failed tool install turned off downloading on that computer for a day.
- What was going on: After a failed install or update of the download tools the next try was 24 hours away, so one network blip at start sent that computer's downloads to the server.
- What the product must do: A failed install or update retries within minutes with backoff, and the editor can see why downloading on their computer is off.
- Kind: 3

### YTD-058 [youtube / Where a download runs, and saying so]: A retried job stayed stuck on the server for good.
- What was going on: A retry inherited the finished run's "taken back by the server" state, so it never ran on the editor's computer again and kept hitting the address YouTube had blocked.
- What the product must do: Pressing download again on a finished job starts a fresh run that may go to the editor's computer, unless that computer had abandoned the job.
- Kind: 3

### YTD-045 [youtube / Files Resolve can decode]: Scratch files written inside a synced project spread and could never be deleted.
- What was going on: Download scratch files written into a synced project folder spread before deletion, and since deletions are not passed on, they stayed on every computer.
- What the product must do: No temporary file is ever created inside a synced folder; work happens outside it and only finished files move in.
- Kind: 3

Sub-topics of `youtube`: Searching and reviewing results; How YouTube throttles and refuses; Signing in to YouTube; Files Resolve can decode; File names and what a file carries; Where a download runs, and saying so; One job, one computer; Choosing the destination and checking space; Jobs on the page: queue, retry, cancel; Progress; Reaching the editor and Resolve; Keeping the downloader working; The assistant behind search; Rights and terms

## Group M29

Marked to move to `whole-product`:

### YTD-092 [youtube / Reaching the editor and Resolve]: A backslash path shown to a Mac editor is a wrong path.
- What was going on: On a Mac a backslash is legal inside a file name, and a page served from the NAS cannot know an editor's drive letter or system.
- What the product must do: Pages served from the NAS show a file's path relative to the project tree, with forward slashes and no drive letter, saying "under your sync drive".
- Kind: 1a
- Move to: whole-product

The entries of `whole-product` that read most like it:

### ALL-040 [whole-product / Wording]: Parts of the product ignored the site's drive letter and folder names.
- What was going on: Installers, messages and sync steps assumed the default drive letter, projects folder, login port and account ids, so another studio's install mapped wrong drives and broke silently.
- What the product must do: Every part reads drive letter, tree, projects and proxy folder names, NAS login port and account ids from the same site settings, or refuses a value it cannot honour.
- Kind: 3

### ALL-042 [whole-product / Wording]: Raw error text with local paths left an editor's computer.
- What was going on: Error strings, which can carry an editor's local paths, were forwarded to the server and shown in settings and on a landing page.
- What the product must do: No raw error text or local path leaves an editor's computer; the server receives and shows a plain sentence.
- Kind: 3

### ALL-036 [whole-product / Wording]: The owner: no customer's name, drive letter or example in what ships.
- What was going on: Defaults named the first studio's shoot and archive folder, its drive letter, its NAS brand, its episode, its search language and real people in sample data.
- What the product must do: A fresh site shows no name, folder, drive letter, language default or example taken from another studio; every such value comes from the site's own settings.
- Kind: 2
- State: outcome not found

### ALL-077 [whole-product / Windows, text and names]: The owner: every Windows file picker is the full Explorer dialog.
- What was going on: The owner: "make sure it is the proper explorer file picker not the limited one without an address bar in the top".
- What the product must do: Every file or folder picker on Windows is the full system dialog with an address bar a path can be typed or pasted into.
- Kind: 2

### ALL-080 [whole-product / Windows, text and names]: Names containing ".." could reach outside the studio tree.
- What was going on: Project paths, template folder names and downloaded file names containing ".." or "." created folders or records outside the tree.
- What the product must do: Any folder or file name typed or received is refused if it would resolve outside the studio tree or to the folder itself.
- Kind: 3

Sub-topics of `whole-product`: The rebuild itself; The look; Wording; Could not check, refusals and nothing silent; Safety in what the product does; Windows, text and names; Requests, logs and outside programs; The assistant

## Group M30

Marked to move to `releases-and-updates`:

### YTD-096 [youtube / Keeping the downloader working]: A version floor written "2026.8.5" refused every computer in the studio.
- What was going on: One side compared versions as text and the other as numbers, so the server refused everyone while each computer believed itself current.
- What the product must do: Versions are compared numerically by one rule everywhere, and a floor that does not parse is refused when it is set.
- Kind: 3
- Move to: releases-and-updates

The entries of `releases-and-updates` that read most like it:

### REL-009 [releases-and-updates / Version numbers]: A computer on a build with a version suffix never finished a pushed update.
- What was going on: A version with a suffix marking local changes did not parse as a number, so a push to a computer already on it was resent every report for ever.
- What the product must do: A suffixed build counts as its numeric version for completing a push, but never as newer than the clean build of that version.
- Kind: 3

### REL-022 [releases-and-updates / Making and publishing a release]: One version number meant two different programs.
- What was going on: Two builds of one commit differ in bytes, and republishing a version with new bytes swapped the served file under its checksum, so computers failed to update.
- What the product must do: A version always means one set of bytes everywhere; republishing identical bytes changes nothing, different bytes are refused as a conflict, and the studio tests exactly what customers receive.
- Kind: 3
- State: outcome not found

### REL-043 [releases-and-updates / Offering an update to a computer]: Editor builds reached computers before the server they needed.
- What was going on: "Server first" lived only in documents and was broken seven times; a server too old for a build hid the refusal and showed everyone current.
- What the product must do: Each build states the minimum server it needs; a server never offers one it is too old for and shows what to do, measuring "up to date" against the vendor.
- Kind: 3

### REL-017 [releases-and-updates / Signing and trust]: One typo in a minimum version could freeze every computer's updates.
- What was going on: A record whose minimum version exceeded its own version raised each computer's floor on mere receipt, refusing that build, its corrected republish and any rollback.
- What the product must do: Such a release is refused at signing, publishing and on every computer, and a refused offer never changes any computer's floor.
- Kind: 3

### REL-013 [releases-and-updates / Signing and trust]: A signing-key change would have stranded every computer on its current build.
- What was going on: Each computer trusts only the keys inside the build it already runs, so a build signed only with a new key is refused everywhere.
- What the product must do: A key change first ships a build signed by the old key that trusts both; publishing a build no installed computer trusts is impossible.
- Kind: 3

Sub-topics of `releases-and-updates`: Facts about Windows, macOS and the NAS that bite an update; Version numbers; Signing and trust; Making and publishing a release; Trying a build on one computer first; Offering an update to a computer; Installing an update on an editor's computer; Pushing updates and seeing who has what; Rolling back and withdrawing a build; The server updating itself; Customer sites and the vendor's release feed

