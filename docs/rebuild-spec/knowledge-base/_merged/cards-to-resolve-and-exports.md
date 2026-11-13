# Timeline Cards: sending a cut to Resolve, and exports

## Frames, frame rates and timecode

### CRX-001: Resolve's scripted append treats the end frame as exclusive.
- What was going on: Passing a clip's last frame as the end drops one frame per clip, leaving a one-frame hole at every join, invisible across a 26-minute timeline.
- What the product must do: Clips laid end to end butt-join with zero gaps and zero frames lost, confirmed by reading back each placed item's start and duration.
- Kind: 1a
- From: C04-053, M05-047

### CRX-002: Resolve's scripted append sometimes places a clip one frame early.
- What was going on: Appending a clip through Resolve's scripting occasionally lands it one frame before the requested position.
- What the product must do: After every scripted placement the position is read back and corrected if it is off.
- Kind: 1a
- From: M02-047

### CRX-003: Resolve reports a clip's source frames slightly wrong.
- What was going on: Source frames come back a hair under the integer (1299.9999), the out frame disagrees with in plus duration on about half of cuts, and rates come back rounded.
- What the product must do: A cut's in-point is rounded to the nearest frame, its out-point is in-point plus duration, and an untouched cut never reads as trimmed by a frame.
- Kind: 1a
- From: M04-005, D05-006, D04-062

### CRX-004: Resolve's count of linked picture-sound pairs changed between sessions.
- What was going on: Reading the same timeline in different sessions gave 490, 242 and 238 linked pairs.
- What the product must do: Pairing a cut's picture with its sound never rests on one session's count of linked items.
- Kind: 1a
- From: M03-025

### CRX-005: Mixed-rate clips land in Resolve at a length Resolve decides.
- What was going on: Resolve was seen rate-conforming a 24 fps clip into 29.97, laying off-rate source frames one to one (a gap after each), and sizing cuts so they overwrote each other.
- What the product must do: Each cut starts at the previous item's read-back end, with no gaps or overlaps, and its placed length matches the clip's real rate within 0.04 seconds.
- Kind: 1a
- State: still open
- From: M05-025, M03-026, P09-044, M01-026
- Check: Does Resolve rate-conform mixed-rate clips or lay them frame for frame, and does a project setting decide which?

### CRX-006: A Resolve timeline's frame rate can be set only while it is empty.
- What was going on: Once a clip is placed the rate is fixed, so a build that does not set it first inherits the project default.
- What the product must do: A send lets the editor pick the new timeline's rate or keep the project default, and applies it before the first clip lands.
- Kind: 1a
- From: C05-016

### CRX-007: Resolve's set-marks call counts from the timeline start, not from zero.
- What was going on: Item positions are absolute, about 108,000 frames past zero at 01:00:00:00, so marks set from them landed exactly one hour late.
- What the product must do: Every conversion between item positions and timeline-relative calls subtracts the timeline's start frame.
- Kind: 1a
- From: M05-068

### CRX-008: A multicam's timecode restarts at 01:00:00:00 and its angles map frame for frame.
- What was going on: Building a multicam resets its timecode, and angles map frame for frame, even a true 24.000 angle in a 23.976 multicam, so matching by source timecode landed minutes off.
- What the product must do: Cuts are mapped onto a multicam frame for frame from each angle's own start, never by matching source timecode.
- Kind: 1a
- From: M05-053

### CRX-009: A cut must reach Resolve exact to the frame, never word-snapped.
- What was going on: The owner: "If the lane cannot conform frame-accurate to resolve it is essentially useless", and "I want exact second/frame timing. I've flagged this before."
- What the product must do: Every cut arrives in Resolve on exactly the frames shown in the editor, on the clip's own frame grid, and no screen calls a trim approximate.
- Kind: 2
- From: P08-038, P09-040

### CRX-010: A sent timeline is butt-joined at a chosen rate, 29.97 drop-frame by default.
- What was going on: The owner rejected built timelines at the wrong rate and with gaps: "Default frame rate going forward should be 29.97"; all 74 studio timelines were 29.97 drop-frame.
- What the product must do: A send offers a rate (default 29.97 drop-frame), butt-joins cuts and first imports any clip the Resolve project lacks; a file stating another rate keeps it.
- Kind: 2
- From: P09-042, D04-019
- Check: The same ruling asked for marker-free timelines, yet later rulings place section and gap-note markers: are markers wanted?

### CRX-011: Every clip was placed at the wrong moment because its rate was guessed.
- What was going on: Cut lists recorded 25 fps for every clip while the media ran at 29.97, 30, 29, 23.976 and 15, so the right clip landed at the wrong time.
- What the product must do: Every cut records its clip's measured rate, 29.97 drop-frame where none is known, and a cut list with a guessed rate is corrected before sending.
- Kind: 3
- From: C05-015, M03-027, P09-043

### CRX-012: Interviews mix frame rates, such as 29.97 clips on a 25 fps timeline.
- What was going on: Clip and timeline rates often differ; a cut's source span is its timeline duration times clip rate over timeline rate, never one to one.
- What the product must do: Every source span is computed at the clip's own rate, and a mixed-rate build matches hand-computed frames exactly.
- Kind: 3
- From: M04-006, D05-008

### CRX-013: Built cuts were a frame short, and inserted cuts far too long.
- What was going on: Treating 29.97 as 30 lost a frame on cuts of 500 frames or more (232 of 523), and inserted cuts kept stale out points (82 frames became 521).
- What the product must do: Every frame calculation uses the exact rate, frame counts are carried rather than recomputed from seconds, and out points stay current through trims and splits.
- Kind: 3
- From: M04-007, P08-039, D02-040

### CRX-014: Untouched cuts drifted 1-2 frames when a cut was sent again.
- What was going on: 316 of 490 unchanged cuts moved because source points were recomputed through Resolve's off-by-one and a rounded rate.
- What the product must do: Sending a cut list identical to the timeline writes nothing, and untouched cuts keep their exact frames and their grades.
- Kind: 3
- From: C04-062, D01-041

### CRX-015: A cut built in Resolve came out at the wrong total length.
- What was going on: A cut list running roughly 30 minutes built a Resolve timeline of a different length.
- What the product must do: A timeline built from a cut runs the cut list's length, give or take a frame per clip.
- Kind: 3
- State: outcome not found
- From: P16-042

## Placing, deleting and linking clips in Resolve

### CRX-016: With no track named, Resolve's append follows the destination-track buttons.
- What was going on: With V1's destination toggle off nothing lands and no error comes back, a rollback done the same way restores nothing, and some audio-only positions place nothing.
- What the product must do: Every placement names its track and media type and counts only after its track and start are read back; missing picture or sound is reported by track.
- Kind: 1a
- From: M04-003, M05-048

### CRX-017: Appending to a missing track reports success; a chosen track gets no linked audio.
- What was going on: An append at a track index that does not exist returns an item and places nothing; an append to a chosen track places picture without linked sound.
- What the product must do: A cut placed on an upper track lands on a track that exists, with picture and sound both placed and linked, as a hand edit would.
- Kind: 1a
- From: D05-009, P04-047

### CRX-018: A scripted delete in Resolve leaves the clip's linked audio behind.
- What was going on: The leftover audio silently blocks later appends over those frames while the call reports success, and left another interviewee's sound duplicated underneath a moved cut.
- What the product must do: Removing or moving a cut removes its picture and sound together, and no orphaned or duplicated sound is left on the timeline.
- Kind: 1a
- From: M04-004, D05-005, P04-044

### CRX-019: Resolve crashes on a timeline whose picture-sound links are one-sided.
- What was going on: 63 audio items named a video partner that did not name them back; Resolve 21.0.4 crashed 20-75 s after opening it, after bursts of "An attempt to unlink a not linked item!".
- What the product must do: Every timeline the product creates or changes has each picture-sound link recorded on both sides, checked after creation.
- Kind: 1a
- From: D05-064, P13-001

### CRX-020: Resolve's scripted delete hits the named timeline, but append lands on the current one.
- What was going on: Switching timeline tabs mid-edit deleted a tail from one timeline and appended it to another, which looked exactly like lost clips.
- What the product must do: Before every write the open timeline is confirmed as the one being edited and unchanged; otherwise the edit stops, is rolled back and is reported.
- Kind: 1a
- From: D05-007, M04-002, P04-045

### CRX-021: Resolve's select-at-playhead and split act on every track with auto-select on.
- What was going on: A delete aimed at V1 also took a V2 overlay or another interviewee's audio clip, and with A1 off a split cut picture but not sound.
- What the product must do: Deleting a card removes only that card's picture and sound; any change on another track is undone and reported.
- Kind: 1a
- From: M04-014, P07-069

### CRX-022: Resolve's scripting cannot move a clip, insert mid-timeline, or announce changes.
- What was going on: Scripting offers append and delete only, so moving one card meant rebuilding everything after it, and a change made in Resolve is seen only by reading again.
- What the product must do: A change the editor makes in Resolve shows in the cards within about one second without Resolve announcing it, and moving one card takes seconds.
- Kind: 1a
- From: D05-001, M04-001, P04-043

### CRX-023: Nothing in Resolve's scripting or shortcuts can insert empty time.
- What was going on: Scripting cannot set an item's position or insert empty time, and the Edit page has no insert-gap command.
- What the product must do: Gaps appear in timelines built whole; an in-place edit containing a gap is refused with that reason, never failing silently.
- Kind: 1a
- From: M03-036, G01-066

### CRX-024: Resolve's scripting cannot build a timeline from a transcript.
- What was going on: Resolve's text-based editing is absent from its scripting interface (checked in Resolve 20).
- What the product must do: Transcript-driven cuts are placed one by one from word timings, and every placement is checked.
- Kind: 1a
- From: M05-023

### CRX-025: Resolve gives a timeline clip a new id on every ripple move.
- What was going on: Notes keyed on Resolve's item id were lost on every cut-and-paste move, and a media pool id means nothing in another project or on another machine.
- What the product must do: Notes, colours and marks follow the cut's clip and source span, surviving ripple moves, project copies and other machines.
- Kind: 1a
- From: D04-061

### CRX-026: Resolve allows two clips of the same name in different bins.
- What was going on: Sound and colours looked up by clip name collided when two bins held same-named clips.
- What the product must do: Same-named clips in different bins are reported as ambiguous, never silently treated as one.
- Kind: 1a
- From: D04-063

### CRX-027: Exporting and re-importing a Resolve timeline damages multicam edits.
- What was going on: An FCP7 XML round trip unlinked half the pairs and lost every multicam angle, the subtitles and the grades; a .drt round trip left 304 one-way links and duplicated all 9 multicams.
- What the product must do: A multicam or graded timeline is never rebuilt by export and re-import, and any repaired timeline keeps every track, angle, link, colour, marker, subtitle and grade.
- Kind: 1a
- From: D05-066, M02-058, D04-064

### CRX-028: An insert or move from the cards must be exact, keep grades and undo once.
- What was going on: An insert rebuilt 160 or more later cuts, each its own undo step, landed in the wrong place and lost their grades; the owner called it "a major flaw".
- What the product must do: An insert or move lands exactly where chosen, leaves every other cut's position, identity and grade unchanged, and undoes with one Ctrl+Z in Resolve.
- Kind: 2
- From: M04-011, P07-035, D05-003

### CRX-029: Insert and place-on-top put the new cut at the playhead.
- What was going on: Both actions placed the new cut at a clip's start or end, far from the playhead; the owner wants it at the playhead.
- What the product must do: Insert and place-on-top put the new cut at the playhead frame, not at the nearest clip boundary.
- Kind: 2
- From: P04-046

### CRX-030: Cuts are built from each interviewee's multicam, and plain clips work too.
- What was going on: The owner wants lines cut from the interviewee's multicam, never the separate camera files, and montages from news clips "will need to use clips which are not multicams".
- What the product must do: A cut is built in its own order from each interviewee's multicam where one exists, and from ordinary single clips otherwise.
- Kind: 2
- From: P04-001, P04-041

### CRX-031: Several passages inserted in a row must land one after another.
- What was going on: Inserting at the playhead mid-cut splits that cut; a playhead left one frame short made the next insert split the passage just placed.
- What the product must do: After an insert the playhead sits at the inserted passage's end, so a run of inserts lands in order without splitting each other.
- Kind: 3
- From: M04-009

### CRX-032: Sending a cut refused every clip because names had been shortened.
- What was going on: The cards dropped " Multicam" and the extension from names, but Resolve finds clips only by exact media pool name, odd casing like "MultiCam" included.
- What the product must do: Clips are identified by exact media pool name or unique id, never by a shortened display name.
- Kind: 3
- From: G01-067

### CRX-033: A send placed clips from other Resolve projects.
- What was going on: Resolve's library holds many projects; matching clips by name across all of them, or picking a re-wrap or subclip, put foreign or wrong media into the timeline.
- What the product must do: A send uses only media from the target Resolve project, prefers the original file over re-wraps and subclips, and refuses another project's timeline.
- Kind: 3
- From: C05-017

### CRX-034: A timeline rebuilt by duplicating and renaming has a new id.
- What was going on: Replacing a damaged timeline with a renamed duplicate gives it a new id, so anything remembered against the old id points nowhere.
- What the product must do: What the product remembers about a timeline survives it being duplicated and renamed, or the product says plainly that it lost track.
- Kind: 3
- State: outcome not found
- From: D05-067

## Undo, markers, titles, fades and properties

### CRX-035: Resolve's undo history is project-wide and counts every scripted change.
- What was going on: Every scripted append, delete, link, mark and marker change is its own step in one shared history; one undo too many undid the editor's own timeline duplication.
- What the product must do: An edit the product makes costs a known small number of undo steps, and undoing it checks the timeline state, never undoing the editor's own work.
- Kind: 1a
- From: P07-034, M04-013, D05-004

### CRX-036: Resolve's markers stay put when a ripple edit moves the cuts under them.
- What was going on: Ripple moves, deletes, trims and inserts leave timeline markers at their absolute frames, so section markers land on the wrong cut; scripting has no marker move.
- What the product must do: After any edit, each marker still sits on the cut it marked, keeping its name, colour, note and duration, within one undo step.
- Kind: 1a
- From: D05-012

### CRX-037: Resolve keeps one marker per frame and silently refuses the rest.
- What was going on: A second marker on a frame is refused; 25 of 36 markers were lost where section headings and notes shared frames, and 6 of 14 in another send.
- What the product must do: A marker that would share a frame moves to the next free frame, and none is lost.
- Kind: 1a
- From: M03-029

### CRX-038: Resolve's scripting cannot set fades, keyframes, transitions or clip volume.
- What was going on: Item properties cover only a static opacity, so one cut's 22 audio fades and its manual gains, and levelling heard in the preview, never reached Resolve.
- What the product must do: Every send and export carries fades, gain and levelling where it can, and names each one it dropped, with a count in words.
- Kind: 1a
- State: fixed, never shipped
- From: M01-022, P14-017, C06-021, D01-044, D05-083

### CRX-039: Resolve inserts a title only at the playhead, at a default length.
- What was going on: The title call takes no track, frame or duration, nothing resizes it later, the default is 5 s, and it ripples into track one and fails on a locked track.
- What the product must do: Any title placed by script is checked for track, start and length afterwards, and removed without ripple when wrong.
- Kind: 1a
- From: D01-059

### CRX-040: Resolve silently refuses some property writes.
- What was going on: Setting loudness normalisation on Resolve 21.0.1 returns failure, and renaming a Fusion clip by its clip-name property silently does nothing.
- What the product must do: Every Resolve property or name the product sets is read back, and a refusal is shown to the person.
- Kind: 1a
- From: M02-059

### CRX-041: Fade handles are audio only, heard in the browser and exact in Resolve.
- What was going on: The owner: "timeline cards only needs audio fades, not video fades", conforming "to resolve accurately", and fades must "actually play, not just be visual".
- What the product must do: Cuts carry audio fade-in and fade-out handles that play as drawn in the browser and arrive in Resolve at the same lengths; the picture is never faded.
- Kind: 2
- From: D01-046, P11-027

### CRX-042: A per-cut gain was asked for but never reached Resolve.
- What was going on: The owner asked for per-cut gain; how Resolve stores a clip's volume was never confirmed, so a guessed level could put an unseen level into a timeline.
- What the product must do: A cut's gain reaches Resolve at the level set, proven by reading back a known level; until then every send says gain was not carried.
- Kind: 2
- State: still open
- From: D01-047

### CRX-043: A note on a gap becomes on-screen text in the Resolve timeline.
- What was going on: The owner: a gap note "should get built as a text object in resolve ... so that editors can see what the gap is for", "standard going forward for all conforms".
- What the product must do: Every noted gap arrives as a Text+ title with its latest saved note, on a separate upper track at the gap's exact frame and length, moving no clip.
- Kind: 2
- From: D01-058, P12-028, P16-041, M03-030

### CRX-044: A gap-note title must never cover the next cut or move anything.
- What was going on: A title longer than its gap would sit over the next cut in every render, and a note marker in a section colour comes back as a new section heading.
- What the product must do: Gap text never overlaps picture, no cut moves, every track lock is restored, and a note marker never reads back as a section.
- Kind: 3
- State: fixed, never shipped
- From: D01-060

## Talking to Resolve: restarts, dialogs and speed

### CRX-045: Clip references taken before a Resolve restart silently place nothing.
- What was going on: References from before a restart look usable but every append returns nothing; a 489-cut send built a blank timeline and reported success.
- What the product must do: Clip references never outlive a Resolve restart, and a send placing fewer cuts than asked fails loudly, names refused cuts and leaves no empty timeline.
- Kind: 1a
- From: C04-059, D06-022, P08-011, M03-037

### CRX-046: Resolve clip handles work only on the connection that fetched them.
- What was going on: Media pool clips fetched on one scripting connection and appended through another silently return an empty list.
- What the product must do: Clips are fetched and appended on the same connection, and an empty append result counts as a failure.
- Kind: 1a
- From: M05-024

### CRX-047: Every Resolve call returns nothing while a dialog box is open.
- What was going on: While a modal dialog is up (a message box, a transcription progress window, "Audio Output: Remote Audio not found"), scripting calls return nothing at once; only closing it helps.
- What the product must do: A call that returns nothing is treated as a possible blocking dialog and named to the editor, and an editor's own transcription is never cancelled.
- Kind: 1a
- State: outcome not found
- From: M04-019, M03-032

### CRX-048: Reading a 266-cut Resolve timeline takes about 150 ms.
- What was going on: Listing a 266-item track took about 90 ms, their source frames about 60 ms, the playhead 0.1 ms; appending in one batch cost about 11 ms per cut.
- What the product must do: Following a Resolve timeline of up to 500 cuts updates the cards within a second and never stalls the editor's own clicks in Resolve.
- Kind: 1a
- From: D05-002

### CRX-049: A card click took up to 7 seconds to move Resolve's playhead.
- What was going on: A click normally reaches Resolve in 0.3 s, but took 7 s when every clip's path and name was asked one call each, or another program was walking the timeline.
- What the product must do: A card click moves Resolve's playhead within half a second on several hundred cuts, even while other programs talk to Resolve.
- Kind: 1a
- From: D03-007, D02-032

### CRX-050: Building a long timeline one Resolve call at a time is very slow.
- What was going on: A 396-cut build needed about 2,000 separate calls, and deleting 1,269 subtitle items one at a time was just as slow.
- What the product must do: A build or bulk change of several hundred items shows progress and finishes in minutes.
- Kind: 1a
- State: outcome not found
- From: P14-018

### CRX-051: A grabbed Resolve still exported an all-black frame while reporting success.
- What was going on: When Resolve's viewer has not reloaded, grabbing a still succeeds but exports black, and animated titles look different along their length.
- What the product must do: Visual checks render a single frame at the item's midpoint instead of trusting a grabbed still.
- Kind: 1a
- From: M05-058

### CRX-052: Resolve never re-reads an open timeline whose stored data changes.
- What was going on: Changes written to the library for an open timeline are not seen until the project is closed and reopened.
- What the product must do: Any change made to a timeline outside Resolve closes it first and reopens it after, with the editor's work saved beforehand.
- Kind: 1a
- From: D06-021

### CRX-053: After Resolve restarted, the page kept saying no timeline was open.
- What was going on: When Resolve came back on the same timeline, the page saw no change and kept its error banner and empty list until its own server restarted.
- What the product must do: Within seconds of Resolve reopening a timeline, even an unchanged one, the cards show it again, with nothing restarted.
- Kind: 3
- From: P07-063, D02-033, M04-022

### CRX-054: A send to an unreachable Resolve failed eight minutes later.
- What was going on: With Resolve closed or unreachable, the build request was accepted, queued and only failed minutes later.
- What the product must do: A send while Resolve is closed or unreachable is refused at the press with a sentence giving Resolve's state.
- Kind: 3
- From: D05-027

### CRX-055: Only one program may drive Resolve on a computer.
- What was going on: A second program driving Resolve on the same computer risks scripting for the whole session, and each failed start left another hidden connection running.
- What the product must do: Never more than one connection to Resolve per computer: a second is refused (an unreadable process list counts as one running), and a failed start leaves nothing running.
- Kind: 3
- From: G01-050, H05-047

### CRX-056: A stop must never cut a Resolve edit off halfway.
- What was going on: An edit sent to Resolve is several steps; stopping it partway leaves a timeline nobody asked for.
- What the product must do: A stop, of one computer or the whole fleet, lets a Resolve edit in progress finish before taking effect.
- Kind: 3
- From: L04-118

### CRX-057: Keys sent to Resolve on the editor's behalf stopped him typing in Resolve.
- What was going on: Pressing "c" in Resolve triggered the product's helper and produced odd output and errors.
- What the product must do: Nothing the product installs ever intercepts keys the editor types into Resolve or any other program.
- Kind: 3
- State: outcome not found
- From: P07-036

## Sending a cut to Resolve

### CRX-058: Resolve files a new timeline in whatever bin the editor last clicked.
- What was going on: Resolve's scripted create-timeline puts the timeline in the currently selected media pool bin, wherever the editor happened to click last.
- What the product must do: The editor can choose the bin a built timeline goes into, the editor's selected bin is restored afterwards, and an unknown bin is refused before building.
- Kind: 1a
- From: D05-028, M01-027

### CRX-059: Resolve refuses a duplicate timeline name with a bare "Failed to create timeline".
- What was going on: Creating a timeline whose name already exists in the project fails with no reason given.
- What the product must do: Every timeline the product creates gets a unique name, suffixed automatically when the asked-for name exists.
- Kind: 1a
- From: P09-045, M03-028

### CRX-060: Timeline Cards hands its cut to Resolve only, to start.
- What was going on: The owner ruled "resolve only to start": other editing programs later, if a client needs one.
- What the product must do: The cut is handed over to Resolve, and nothing before the hand-over depends on any editing program.
- Kind: 2
- From: P19-013

### CRX-061: Nothing is built in Resolve until the editor confirms a dry run.
- What was going on: The owner: "don't automatically conform until I have looked at" the plan; nothing is applied unprompted, and plain edits never reach Resolve.
- What the product must do: No timeline is built or changed in Resolve until the editor confirms after seeing the cut, marker and length counts.
- Kind: 2
- From: D05-024, D02-059, P05-039

### CRX-062: "Conform" means the editor's edited cut, never the candidate pool.
- What was going on: Asked to conform a montage, the whole unedited pool (104 cards, 5-10 times too long) was sent; the owner: "the cut file is what needs conforming".
- What the product must do: A send to Resolve uses the editor's saved cut, never the assistant's candidate pool or a board's arrangement unless explicitly named.
- Kind: 2
- From: M03-075, P12-062, P13-020, M04-026

### CRX-063: Sending a cut needs only its clips in the media pool, not an open timeline.
- What was going on: Sends were refused until a populated timeline was open; the owner: it "should be able to just conform even into a project with no timelines in it at all".
- What the product must do: A send succeeds into a project with no timeline open, or none at all, whenever its clips are in the media pool; only an unreachable Resolve blocks it.
- Kind: 2
- From: C05-018, P10-032, L05-065, D05-026, D03-040

### CRX-064: Every timeline sent to Resolve goes into a Timelines bin.
- What was going on: The owner: they "should always be moved to a timelines bin. If it doesn't exist, create it"; he renames a new timeline within seconds.
- What the product must do: Each send puts its new timeline in a root bin named Timelines, created if missing, and follows it by unique id, never by name.
- Kind: 2
- From: M03-033, P14-037

### CRX-065: Sending is an action on the cut, with no top-bar button.
- What was going on: The only send control was a switch, so the owner's clicks "did nothing", and he does not want a send button in the top bar.
- What the product must do: A cut offers one action that sends it to a new Resolve timeline: name it, see dry-run counts, confirm; the top bar holds no such button.
- Kind: 2
- From: P09-041, M03-052

### CRX-066: A person may drive Resolve only on computers signed in to their own account.
- What was going on: The owner: "users can only use [the app on computers] which are also signed in to their own account".
- What the product must do: A cut sent to Resolve reaches only computers signed in to the sender's account, never another person's.
- Kind: 2
- From: P11-024

### CRX-067: A send with missing clips must name each one and build nothing.
- What was going on: A cut's clips may be unknown or absent from the target media pool, and a partial timeline is worse than none.
- What the product must do: A dry run lists every unmatched card; a send with any missing clip names each, says whose media pool was checked and when, and writes nothing.
- Kind: 3
- From: D05-025, D04-065, P14-013

### CRX-068: Short soundbites were matched to the wrong place in an interview.
- What was going on: Polished transcript text matches the raw words only loosely (0.77 to 0.93), so a loose match on a short phrase or two-character anchor can land anywhere.
- What the product must do: When existing cuts located by text are brought in, a short excerpt is placed only on an exact match, otherwise flagged unmatched, never guessed.
- Kind: 3
- From: M05-027

### CRX-069: A montage arrived in Resolve under another project's timeline name.
- What was going on: An unset name fell back to a default left over from the first project.
- What the product must do: A timeline sent to Resolve is named after its own cut, never a leftover default.
- Kind: 3
- From: C04-076

### CRX-070: The cut must record the name Resolve actually gave its timeline.
- What was going on: When the requested name is taken, the build takes the next free name, so the requested name may not be the timeline built.
- What the product must do: After a build, the cut names the timeline that was really created.
- Kind: 3
- From: D05-029

### CRX-071: A thirteen-cut montage built a timeline with far more clips.
- What was going on: Sending a thirteen-cut montage to Resolve produced a timeline holding many more clips than the cut.
- What the product must do: A timeline made from a cut holds exactly one clip per card, in the cut's order, and nothing else.
- Kind: 3
- State: outcome not found
- From: P09-046

### CRX-072: Clip colours set in the cards did not reach Resolve.
- What was going on: The owner wants clip colours set in the cards carried into the built timeline; on a montage they did not arrive.
- What the product must do: A colour set on a cut in the cards appears on that clip in the timeline Resolve receives.
- Kind: 3
- State: outcome not found
- From: P08-046

### CRX-073: A build stopped early left 54 cuts with no audio or markers.
- What was going on: The build placed all video first, then audio, then markers, and with no timeline open the status flickered between available and unreachable.
- What the product must do: A send reports done only when picture, sound and markers are all placed, flags any partial timeline, and keeps a steady status while Resolve is idle.
- Kind: 3
- State: still open
- From: M01-028

## Edits sent live and staged edits

### CRX-074: Edits wait as a draft until applied; a cut-loose draft becomes a new timeline.
- What was going on: Moves in Resolve were slow, so the owner wanted edits staged until he says so, an edit-at-once mode removed ("serves no purpose"), and independent cutting away from Resolve.
- What the product must do: Edits stay a draft until applied, Resolve's own changes show meanwhile, and a cut-loose draft is sent as a new timeline the editor then follows, the original untouched.
- Kind: 2
- From: P07-040, M04-051, P07-043

### CRX-075: Nothing cut from the timeline is ever lost.
- What was going on: The owner asked that every piece removed by a trim or delete be kept on an offcuts timeline in the same project, created if missing.
- What the product must do: Every piece removed by a delete or trim stays recoverable in the project, leaving there only when its removal is undone.
- Kind: 2
- From: M04-012, P07-050

### CRX-076: After staged edits ran, the cards no longer matched Resolve.
- What was going on: A run can stop partway when Resolve refuses one edit, and once the moves worked in Resolve while the page stayed out of step.
- What the product must do: Staged edits are saved on every change, each leaves the draft only once Resolve confirms it, and after a run the cards show exactly what Resolve holds.
- Kind: 3
- From: D05-044, P07-041

### CRX-077: A card dragged on the page did not move in Resolve, and nothing said so.
- What was going on: Drags and later moves silently did nothing in Resolve, leaving the editor unsure whether the edit happened.
- What the product must do: A move Resolve did not perform is reported on the page within seconds, and the card returns to where Resolve has it.
- Kind: 3
- State: outcome not found
- From: P07-044

### CRX-078: The page silently showed a different timeline from Resolve's.
- What was going on: With the page held on another timeline, Resolve's updates were set aside, and only a small status text said so.
- What the product must do: When the page shows something other than Resolve's open timeline, it names Resolve's timeline and offers a one-click "follow Resolve".
- Kind: 3
- From: G01-056

## Bringing Resolve's changes back into the cut

### CRX-079: Edits made in Resolve after a send had no way back into the cut.
- What was going on: Editing continues in Resolve after a send; one real comparison found 45 moved, 26 trimmed, 51 split, 51 new and 25 removed cuts.
- What the product must do: The editor shows whether cut and timeline are in step and what differs, and on request, after a dry run, takes Resolve's changes back as one undoable revision.
- Kind: 3
- From: D05-030, C04-080, D02-060, M04-052, D04-068

### CRX-080: A comparison claimed every cut after one dragged cut had moved.
- What was going on: Compared naively, one cut dragged to the top marks everything after it as moved, and a blade reads as a trim plus a new cut.
- What the product must do: A comparison reports the fewest moved cuts, a blade as one split, plus changed gaps, colours and markers, so a single drag reads as one move.
- Kind: 3
- From: D05-031

### CRX-081: Updating from a timeline must keep its colours and the cut's own notes.
- What was going on: A build paints each cut its interviewee's colour, and an update using derived colours left every cut and 23 sections a colour apart.
- What the product must do: Updating a cut from its timeline takes the timeline's cut and marker colours, keeps notes, shelf, sequences and highlights, and then reports in step.
- Kind: 3
- From: D05-032

### CRX-082: Updating a cut from a different timeline than it names is a decision.
- What was going on: A cut names one timeline; updating it from another would silently replace the whole cut.
- What the product must do: Updating from a timeline other than the one the cut names is refused, naming both, until the editor confirms.
- Kind: 3
- From: D05-033

## Which computer is driving Resolve

### CRX-083: The computer shown driving Resolve could be a made-up name, or merged with another.
- What was going on: With no declared machine the name came from the computer's own claim, and an older app's two computers registered as one bare person.
- What the product must do: The computer shown driving Resolve comes from its verified identity; each of a person's computers appears separately, and a self-given name is marked unverified.
- Kind: 3
- From: L06-006, H05-077, L07-056

### CRX-084: An editor's two computers could not work in two episodes at once.
- What was going on: Requests followed the person's last request on any device, so Resolve requests and their answers landed in different episodes and applied edits were reported lost.
- What the product must do: Each computer follows the episode open on that computer, and a request and its answer always reach the same episode.
- Kind: 3
- From: H06-071

### CRX-085: The link to Resolve showed green while dead for hours.
- What was going on: Healthy meant "was started", so a crashed loop, hours of refused sign-ins or an unreachable dashboard looked fine, and restarts waited on a different test.
- What the product must do: Green needs a successful contact in the last 50 seconds, else it names stopped, refused or unreachable; anything shown stopped is restarted within a minute.
- Kind: 3
- From: L04-117, L07-009

### CRX-086: The link looked healthy while every update from Resolve was thrown away.
- What was going on: With no episode open in the editor, updates were discarded with an OK answer, and the computer showed its timeline as being served.
- What the product must do: When updates are discarded because no episode is open, the computer's status says so, with "open an episode", on the computer and the dashboard.
- Kind: 3
- From: L08-072

## Exports

### CRX-087: A cut exports as XML, OTIO, EDL and a plain text script.
- What was going on: The owner: "we should also keep the ability to export an xml otio edl and a txt script"; Premiere's reading of the XML is untested.
- What the product must do: Any cut exports in those four forms, each naming what its format could not carry; a Premiere import is verified before being promised.
- Kind: 2
- From: P19-020

### CRX-088: The text export holds each card in its spoken language only.
- What was going on: The owner asked for the cards as plain text and as a Markdown document with no English for Mandarin cards.
- What the product must do: The cards export as plain text and as Markdown in timeline order, each card in its spoken language only, without translations.
- Kind: 2
- From: P04-069

## Renders from Resolve

### CRX-089: An audio-only render from Resolve refused to start as WAV.
- What was going on: With WAV chosen through scripting, Resolve leaves the format unknown and refuses to render; an audio-only render works as MOV/H.264 with video export off.
- What the product must do: Audio-only renders the product requests from Resolve start and finish without manual help.
- Kind: 1a
- From: M03-034

### CRX-090: A Resolve render can silently come out without its picture or sound.
- What was going on: After an audio-only export, Export Video stays off; turning it on by script reports success, yet renders are audio-only, and one episode render had no sound.
- What the product must do: Every render is checked for a picture stream, sound and expected length before use; a 25-minute render finishing in under a minute is audio-only.
- Kind: 1a
- From: M04-102, P15-009

### CRX-091: Scripted effects inside compound clips lose their first frames and abort renders.
- What was going on: A Fusion composition added by script loses its first one or two frames ("No frame available") once its clip is wrapped in a compound clip.
- What the product must do: A compound clip the product builds renders every frame including its first, checked by rendering the head frames before handing it over.
- Kind: 1a
- From: P01-017, M05-066
- Move to: resolve-on-the-editors-computer

### CRX-092: A render queue across projects must survive Resolve crashing.
- What was going on: The owner wanted renders queued from several projects, with a crash detected, Resolve restarted and the interrupted render resumed.
- What the product must do: When Resolve dies during a queued render, the queue restarts Resolve, re-runs the interrupted job and continues with the rest.
- Kind: 2
- State: outcome not found
- From: P01-035
- Move to: resolve-on-the-editors-computer

### CRX-093: The studio's default render is QuickTime H.264 at 3840x2160, proxies off.
- What was going on: The owner's defaults: QuickTime H.264, timeline frame rate, 3840x2160, proxy media off, best quality, subtitle export off.
- What the product must do: Before a queue starts, each job differing from the studio defaults is listed per project with a yes or no to switch it.
- Kind: 2
- State: outcome not found
- From: P01-036
- Move to: resolve-on-the-editors-computer

### CRX-094: Before rendering, clips hidden inside compound clips must be checked online.
- What was going on: Offline media inside compound clips does not show on the timeline.
- What the product must do: Before a render is queued, every clip inside every compound clip on the timeline is checked, and offline ones are named.
- Kind: 2
- State: outcome not found
- From: P01-038
- Move to: resolve-on-the-editors-computer

### CRX-095: A 61-minute timeline held a 25-minute cut plus parked clips.
- What was going on: Editors park unused clips after the cut: one timeline was 24:41 of cut, a 14-minute gap, then 96 unused clips.
- What the product must do: A timeline's real end is found at the first gap of minutes, and renders and exports stop there.
- Kind: 3
- From: M04-103

## Titles and compound clips

### CRX-096: Compound clips should carry the name and colour of what they hold.
- What was going on: Resolve names new compound clips "Compound Clip 1, 2..."; the owner wants each named after its clip and coloured like that interviewee's multicam.
- What the product must do: A compound clip the product creates is named after the clip it wraps and takes the clip colour of the related interviewee's multicam.
- Kind: 2
- State: outcome not found
- From: P01-018
- Move to: resolve-on-the-editors-computer

### CRX-097: Name titles sat half off screen and could cover the speaker.
- What was going on: Left titles were placed by their far edge and right ones ran off frame; the owner wants the visible edge 50 px in, opposite the speaker.
- What the product must do: A name title's visible edge sits 50 px in from the side and bottom, on the side away from where the speaker appears.
- Kind: 2
- State: outcome not found
- From: P01-019
- Move to: resolve-on-the-editors-computer

### CRX-098: When one interviewee cuts straight to another, name titles hand over.
- What was going on: The owner: with no b-roll between, "the outro for the previous third plays and the new third for the new interviewee comes in. Obviously."
- What the product must do: On a direct cut between two speakers, the first speaker's title plays its exit and the second speaker's title plays its entrance.
- Kind: 2
- State: outcome not found
- From: P01-020
- Move to: resolve-on-the-editors-computer

## Subtitles and delivery

### CRX-099: Resolve places imported subtitles offset along the track.
- What was going on: Imported subtitles land at the end of the track, offset by their own times, so cues sat too far along and looked misaligned.
- What the product must do: Subtitles placed on a timeline line up with the cut from frame zero, each within a frame of its speech, with no manual shifting.
- Kind: 1a
- From: M03-031, P01-042, P14-023

### CRX-100: Subtitle files exported from Resolve carry invisible line-separator characters.
- What was going on: Ten of eleven English subtitle files exported from Resolve held 293 invisible line separators (Unicode U+2028), 150 of them in one episode.
- What the product must do: Every subtitle file the product writes or passes on is free of invisible line-separator characters.
- Kind: 1a
- From: P15-003

### CRX-101: Subtitles already on a Resolve timeline are reused, never made again.
- What was going on: The owner: "you shouldn't need to transcribe again because the srts already exist ... you will be able to export the SRTs from the timelines directly".
- What the product must do: When a Resolve timeline already carries subtitles, the product exports those rather than making new ones.
- Kind: 2
- From: P15-005

### CRX-102: A finished cut's English subtitles read as natural documentary English.
- What was going on: The owner asked for English "in a natural, dramatic way suitable for a documentary", with gap notes put on as text or subtitles.
- What the product must do: A finished cut gets English subtitles in natural documentary English, timed to the speech, with gap notes carried as visible text.
- Kind: 2
- From: P14-022

### CRX-103: Bilingual on-screen text splits lines by count, Chinese above English.
- What was going on: The owner's layout: two lines are one title and one subtitle, three are one and two, four two and two; same size and colour, one bottom baseline.
- What the product must do: Lines split 1, 1+1, 1+2, 2+2, both languages change at the same frames, blocks grow upward from a fixed margin, and sizes and gaps are adjustable first.
- Kind: 2
- From: P01-041, M05-057

### CRX-104: A subtitle line must never start with the tail of the previous sentence.
- What was going on: Generated subtitles were cut by length mid-clause, so a cue opened with "heavy." then a new sentence; the owner wants sentence-first breaks.
- What the product must do: Cues break at sentence ends then clauses, at most about 95 English or 42 Chinese characters, with times interpolated and all text kept.
- Kind: 2
- From: M05-083

### CRX-105: Captions hold through short pauses.
- What was going on: The owner asked that gaps up to 1.2 seconds in documentaries, 1.5 in reels, be closed by extending the earlier caption.
- What the product must do: Gaps at or under the set limit are bridged, longer gaps stay empty, and a limit of zero turns bridging off.
- Kind: 2
- From: M05-084

### CRX-106: A TV network delivery needs two-language subtitles and a name-strap list per episode.
- What was going on: The owner: subtitles in a folder inside each submission, one English and one Chinese; name straps in a sheet, "each episode in its own tab", no file names.
- What the product must do: Each delivered episode gets English and Chinese subtitle files in its own folder, and a list of every speaker with a screenshot and name.
- Kind: 2
- State: still open
- From: P15-006

### CRX-107: Chinese subtitle lines split English words mid-word, as "crea" and "tivity".
- What was going on: Character-based Chinese line breaking cuts through embedded English words and numbers ("40%" into "4" and "0%"), which the studio's Chinese speech often quotes.
- What the product must do: No line break falls inside a run of Latin letters, digits or % ' . -, and lines carry no stray leading or trailing space.
- Kind: 3
- From: M05-037

### CRX-108: Delivered subtitles had unsubtitled stretches and lines lingering through music.
- What was going on: Archive news went unsubtitled for up to 2.5 minutes, lines held up to 2 minutes across music, cues overlapped, and some covered footage cut out.
- What the product must do: Before delivery, every stretch of speech has a subtitle, no cue spans a break in speech, no cues overlap, and none fall past the cut's end.
- Kind: 3
- From: P15-004

### CRX-109: A person's name was spelled differently across subtitles and name straps.
- What was going on: One interviewee had two English spellings and a mayor three Chinese renderings, and subtitles disagreed with the name-strap sheet the network would use.
- What the product must do: Each person's name is spelled one way per language across every subtitle file and name-strap list of an episode.
- Kind: 3
- State: outcome not found
- From: P15-007

## Sealed

### CRX-S01: Reading a timeline from Resolve's library could describe the wrong one, or shift clips.
- What was going on: The read answered for whichever timeline was current, not the one asked, and titles were skipped uncounted, so every later clip was one position off.
- What the product must do: A read of a timeline confirms it is the requested one, and track positions count every item, titles included.
- Kind: 1b
- Tool: reading Resolve's project library directly (its database; compressed transcription records)
- From: C03-034

### CRX-S02: Resolve's stored project data has no timeline item ids and stale file paths.
- What was going on: The library gives each clip's pool id, name and file path cheaply, but holds no timeline item id, and its stored media path can be out of date.
- What the product must do: Item identity, start, length, clip colour, source in-point and rate are read live from Resolve; only clip name and path may come from stored data.
- Kind: 1b
- Tool: reading Resolve's project library directly
- From: D03-008

### CRX-S03: A timeline written straight into Resolve's shared library damaged a live project.
- What was going on: A direct write left 63 audio clips naming videos that did not name them back, and copied an outlier save counter of 665 billion that Resolve itself had written.
- What the product must do: Nothing is written directly into a library editors work in; any test-library write uses Resolve's real save counter, ignoring outliers, and every link is mutual.
- Kind: 1b
- Tool: writing Resolve's project library database directly
- From: M02-057, D05-065, P13-002

### CRX-S04: Writes into Resolve's library land only while the project is closed.
- What was going on: Resolve never re-reads an open timeline and saves back only what its own edits dirtied, so a write under an open project was partly overwritten.
- What the product must do: The library is written only while no Resolve holds the project, is verified before commit, undoable to an identical state, and the project is always reopened afterwards.
- Kind: 1b
- Tool: writing Resolve's project library directly
- From: P08-013, C04-061, D01-039

### CRX-S05: A whole episode can be written into Resolve's library in under two seconds.
- What was going on: A 490-cut timeline was written in 1.5 s and opened with picture, sound and links; grades and effects are not carried on new cuts.
- What the product must do: A written timeline is verified before commit, backed up, undoable row for row, and refused for grade-carrying or multi-track timelines it cannot reproduce.
- Kind: 1b
- Tool: writing Resolve's project library directly
- From: D01-040

### CRX-S06: Reading Resolve's live library must not hold it open or bypass its locks.
- What was going on: A reader held one transaction open on the live library for the life of the process, a writer switched off its lock check, and real libraries were protected by name.
- What the product must do: Reads never stay open between uses, writes always check Resolve's lock, and every real library is protected whatever its name.
- Kind: 1b
- Tool: reading and writing Resolve's project library database directly
- State: still open
- From: H08-073

### CRX-S07: Where Resolve stores audio fade handles.
- What was going on: Fades sit in an item's effects record, not in columns, as audio fade in and out in frames at the timeline rate (36 and 59 on a live check).
- What the product must do: Writing a fade merges it into existing effects, leaves clip volume untouched, clamps to the cut's length, and reads back as written.
- Kind: 1b
- Tool: reading and writing Resolve's project library directly (item effects record)
- From: D01-045

### CRX-S08: Resolve stores a timeline clip's colour in a hidden record with its own order.
- What was going on: Colour is field 5 (zigzag, 2 times index 1-16) of the item's lockable record; proven 1 Green, 2 Teal, 3 Blue, 5 Pink, 6 Tan, 7 Brown, 10 Chocolate, 15 Violet.
- What the product must do: Use the proven index table and verify the rest; clear a colour with the scripted clear call (setting empty does not clear); count each change as an undo step.
- Kind: 1b
- Tool: reading Resolve's project library directly (item colour record)
- From: G01-065

### CRX-S09: Keystroke edits into Resolve work only on an unlocked desktop with Resolve open.
- What was going on: A locked or sleeping computer cannot take key presses, so the page must say Resolve is away rather than pretend.
- What the product must do: When edits cannot reach Resolve, the page says "away since" a time, keeps playing, searching and staging, and never claims an edit landed.
- Kind: 1b
- Tool: sending keystrokes into Resolve
- From: D06-028

### CRX-S10: Edits made by sending keys to Resolve need focus, settling time and order.
- What was going on: Keys reach Resolve only with its timeline panel focused, a key after a long playhead jump can vanish (settle 0.35 s), Match Frame resets marks, and one move took 6 s on 359 cuts.
- What the product must do: Focus the timeline panel, set marks after Match Frame, and confirm every keystroke edit by reading the timeline back, reporting and undoing a lost step.
- Kind: 1b
- Tool: sending keystrokes into Resolve (AutoHotkey; mark in is 1-based, clearing marks is not an undo step)
- From: D05-011, M04-016

### CRX-S11: Keystroke edits landed on the wrong clip while Resolve was playing.
- What was going on: With Resolve playing or on another page, a keystroke edit acts on whatever clip the playhead happens to be over.
- What the product must do: Read back Resolve's playhead and page before sending any keystroke edit, and refuse when the playhead is not exactly where intended.
- Kind: 1b
- Tool: sending keystrokes into Resolve
- From: M04-015

## Removed

- P04-002 | no longer applies: planned lines were found in Resolve's transcriptions by matching text, and transcripts found by matching text are gone
