# Timeline Cards: the hand-over to Resolve, and exports: what real use taught

105 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## Frames, frame rates and timecode

### CRX-001: Resolve's scripted append treats the end frame as exclusive.
- Why: Passing a clip's last frame as the end drops one frame per clip, leaving a one-frame hole at every join, invisible across a 26-minute timeline.
- Must: Clips laid end to end butt-join with zero gaps and zero frames lost, confirmed by reading back each placed item's start and duration.
- Kind: given

### CRX-003: Resolve reports a clip's source frames slightly wrong.
- Why: Source frames come back a hair under the integer (1299.9999), the out frame disagrees with in plus duration on about half of cuts, and rates come back rounded.
- Must: A cut's in-point is rounded to the nearest frame, its out-point is in-point plus duration, and an untouched cut never reads as trimmed by a frame.
- Kind: given

### CRX-005: Mixed-rate clips land in Resolve at a length Resolve decides.
- Why: Resolve was seen rate-conforming a 24 fps clip into 29.97, laying off-rate source frames one to one (a gap after each), and sizing cuts so they overwrote each other.
- Must: Each cut starts at the previous item's read-back end, with no gaps or overlaps, and its placed length matches the clip's real rate within 0.04 seconds.
- Kind: given

### CRX-006: A Resolve timeline's frame rate can be set only while it is empty.
- Why: Once a clip is placed the rate is fixed, so a build that does not set it first inherits the project default.
- Must: A send lets the editor pick the new timeline's rate or keep the project default, and applies it before the first clip lands.
- Kind: given

### CRX-007: Resolve's set-marks call counts from the timeline start, not from zero.
- Why: Item positions are absolute, about 108,000 frames past zero at 01:00:00:00, so marks set from them landed exactly one hour late.
- Must: Every conversion between item positions and timeline-relative calls subtracts the timeline's start frame.
- Kind: given

### CRX-009: A cut must reach Resolve exact to the frame, never word-snapped.
- Why: The owner: "If the lane cannot conform frame-accurate to resolve it is essentially useless", and "I want exact second/frame timing. I've flagged this before."
- Must: Every cut arrives in Resolve on exactly the frames shown in the editor, on the clip's own frame grid, and no screen calls a trim approximate.
- Kind: ruling

### CRX-010: A sent timeline is butt-joined at a chosen rate, 29.97 drop-frame by default.
- Why: The owner rejected built timelines at the wrong rate and with gaps: "Default frame rate going forward should be 29.97"; all 74 studio timelines were 29.97 drop-frame.
- Must: A send offers a rate (default 29.97 drop-frame), butt-joins cuts and first imports any clip the Resolve project lacks; a file stating another rate keeps it.
- Kind: ruling

### CRX-011: Every clip was placed at the wrong moment because its rate was guessed.
- Why: Cut lists recorded 25 fps for every clip while the media ran at 29.97, 30, 29, 23.976 and 15, so the right clip landed at the wrong time.
- Must: Every cut records its clip's measured rate, 29.97 drop-frame where none is known, and a cut list with a guessed rate is corrected before sending.
- Kind: situation

### CRX-012: Interviews mix frame rates, such as 29.97 clips on a 25 fps timeline.
- Why: Clip and timeline rates often differ; a cut's source span is its timeline duration times clip rate over timeline rate, never one to one.
- Must: Every source span is computed at the clip's own rate, and a mixed-rate build matches hand-computed frames exactly.
- Kind: situation

### CRX-013: Built cuts were a frame short, and inserted cuts far too long.
- Why: Treating 29.97 as 30 lost a frame on cuts of 500 frames or more (232 of 523), and inserted cuts kept stale out points (82 frames became 521).
- Must: Every frame calculation uses the exact rate, frame counts are carried rather than recomputed from seconds, and out points stay current through trims and splits.
- Kind: situation

### CRX-014: Untouched cuts drifted 1-2 frames when a cut was sent again.
- Why: 316 of 490 unchanged cuts moved because source points were recomputed through Resolve's off-by-one and a rounded rate.
- Must: Sending a cut list identical to the timeline writes nothing, and untouched cuts keep their exact frames and their grades.
- Kind: situation

### CRX-015: A cut built in Resolve came out at the wrong total length.
- Why: A cut list running roughly 30 minutes built a Resolve timeline of a different length.
- Must: A timeline built from a cut runs the cut list's length, give or take a frame per clip.
- Kind: situation

See also, filed under another capability:

- RSV-106 (Resolve on the editor's computer): A multicam's angles map frame for frame from their starts, not by timecode.
- RSV-109 (Resolve on the editor's computer): Resolve places scripted clips a frame early and reports odd source times.
- RSV-114 (Resolve on the editor's computer): Resolve's count of linked clips changes between sessions on identical timelines.

## Placing, deleting and linking clips in Resolve

### CRX-016: With no track named, Resolve's append follows the destination-track buttons.
- Why: With V1's destination toggle off nothing lands and no error comes back, a rollback done the same way restores nothing, and some audio-only positions place nothing.
- Must: Every placement names its track; naming a media type means placing picture and sound separately and linking them; it counts only after read-back, and missing picture or sound is reported by track.
- Kind: given

### CRX-017: Appending to a missing track reports success; a chosen track gets no linked audio.
- Why: An append at a track index that does not exist returns an item and places nothing; an append to a chosen track places picture without linked sound.
- Must: A cut placed on an upper track lands on a track that exists, with picture and sound both placed and linked, as a hand edit would.
- Kind: given

### CRX-018: A scripted delete in Resolve leaves the clip's linked audio behind.
- Why: The leftover audio silently blocks later appends over those frames while the call reports success, and left another interviewee's sound duplicated underneath a moved cut.
- Must: Removing or moving a cut removes its picture and sound together, and no orphaned or duplicated sound is left on the timeline.
- Kind: given

### CRX-019: Resolve crashes on a timeline whose picture-sound links are one-sided.
- Why: 63 audio items named a video partner that did not name them back; Resolve 21.0.4 crashed 20-75 s after opening it, after bursts of "An attempt to unlink a not linked item!".
- Must: Every timeline the product creates or changes has each picture-sound link recorded on both sides, checked after creation.
- Kind: given

### CRX-020: Resolve's scripted delete hits the named timeline, but append lands on the current one.
- Why: Switching timeline tabs mid-edit deleted a tail from one timeline and appended it to another, which looked exactly like lost clips.
- Must: Before every write the open timeline is confirmed as the one being edited and unchanged; otherwise the edit stops, is rolled back and is reported.
- Kind: given

### CRX-021: Resolve's select-at-playhead and split act on every track with auto-select on.
- Why: A delete aimed at V1 also took a V2 overlay or another interviewee's audio clip, and with A1 off a split cut picture but not sound.
- Must: Deleting a card removes only that card's picture and sound; any change on another track is undone and reported.
- Kind: given

### CRX-022: Resolve's scripting cannot move a clip, insert mid-timeline, or announce changes.
- Why: Scripting offers append and delete only, so moving one card meant rebuilding everything after it, and a change made in Resolve is seen only by reading again.
- Must: A change the editor makes in Resolve shows in the cards within about one second without Resolve announcing it, and moving one card takes seconds.
- Kind: given

### CRX-023: Nothing in Resolve's scripting or shortcuts can insert empty time.
- Why: Scripting cannot set an item's position or insert empty time, and the Edit page has no insert-gap command.
- Must: Gaps appear in timelines built whole; an in-place edit containing a gap is refused with that reason, never failing silently.
- Kind: given

### CRX-024: Resolve's scripting cannot build a timeline from a transcript.
- Why: Resolve's text-based editing is absent from its scripting interface (checked in Resolve 20).
- Must: Transcript-driven cuts are placed one by one from word timings, and every placement is checked.
- Kind: given

### CRX-025: Resolve gives a timeline clip a new id on every ripple move.
- Why: Notes keyed on Resolve's item id were lost on every cut-and-paste move, and a media pool id means nothing in another project or on another machine.
- Must: Notes, colours and marks follow the cut's clip and source span, surviving ripple moves, project copies and other machines.
- Kind: given

### CRX-026: Resolve allows two clips of the same name in different bins.
- Why: Sound and colours looked up by clip name collided when two bins held same-named clips.
- Must: Same-named clips in different bins are reported as ambiguous, never silently treated as one.
- Kind: given

### CRX-027: Exporting and re-importing a Resolve timeline damages multicam edits.
- Why: An FCP7 XML round trip unlinked half the pairs and lost every multicam angle, the subtitles and the grades; a .drt round trip left 304 one-way links and duplicated all 9 multicams.
- Must: A multicam or graded timeline is never rebuilt by export and re-import, and any repaired timeline keeps every track, angle, link, colour, marker, subtitle and grade.
- Kind: given

### CRX-028: An insert or move from the cards must be exact, keep grades and undo once.
- Why: An insert rebuilt 160 or more later cuts, each its own undo step, landed in the wrong place and lost their grades; the owner called it "a major flaw".
- Must: An insert or move lands exactly where chosen, leaves every other cut's position, identity and grade unchanged, and undoes with one Ctrl+Z in Resolve.
- Kind: ruling

### CRX-029: Insert and place-on-top put the new cut at the playhead.
- Why: Both actions placed the new cut at a clip's start or end, far from the playhead; the owner wants it at the playhead.
- Must: Insert and place-on-top put the new cut at the playhead frame, not at the nearest clip boundary.
- Kind: ruling

### CRX-030: Cuts are built from each interviewee's multicam, and plain clips work too.
- Why: The owner wants lines cut from the interviewee's multicam, never the separate camera files, and montages from news clips "will need to use clips which are not multicams".
- Must: A cut is built in its own order from each interviewee's multicam where one exists, and from ordinary single clips otherwise.
- Kind: ruling

### CRX-031: Several passages inserted in a row must land one after another.
- Why: Inserting at the playhead mid-cut splits that cut; a playhead left one frame short made the next insert split the passage just placed.
- Must: After an insert the playhead sits at the inserted passage's end, so a run of inserts lands in order without splitting each other.
- Kind: situation

### CRX-032: Sending a cut refused every clip because names had been shortened.
- Why: The cards dropped " Multicam" and the extension from names, but Resolve finds clips only by exact media pool name, odd casing like "MultiCam" included.
- Must: Clips are identified by exact media pool name or unique id, never by a shortened display name.
- Kind: situation

### CRX-033: A send placed clips from other Resolve projects.
- Why: Resolve's library holds many projects; matching clips by name across all of them, or picking a re-wrap or subclip, put foreign or wrong media into the timeline.
- Must: A send uses only media from the target Resolve project, prefers the original file over re-wraps and subclips, and refuses another project's timeline.
- Kind: situation

### CRX-034: A timeline rebuilt by duplicating and renaming has a new id.
- Why: Replacing a damaged timeline with a renamed duplicate gives it a new id, so anything remembered against the old id points nowhere.
- Must: What the product remembers about a timeline survives it being duplicated and renamed, or the product says plainly that it lost track.
- Kind: situation

## Undo, markers, titles, fades and properties

### CRX-035: Resolve's undo history is project-wide and counts every scripted change.
- Why: Every scripted append, delete, link, mark and marker change is its own step in one shared history; one undo too many undid the editor's own timeline duplication.
- Must: An edit the product makes costs a known small number of undo steps, and undoing it checks the timeline state, never undoing the editor's own work.
- Kind: given

### CRX-036: Resolve's markers stay put when a ripple edit moves the cuts under them.
- Why: Ripple moves, deletes, trims and inserts leave timeline markers at their absolute frames, so section markers land on the wrong cut; scripting has no marker move.
- Must: After any edit, each marker still sits on the cut it marked, keeping its name, colour, note and duration, within one undo step.
- Kind: given

### CRX-037: Resolve keeps one marker per frame and silently refuses the rest.
- Why: A second marker on a frame is refused; 25 of 36 markers were lost where section headings and notes shared frames, and 6 of 14 in another send.
- Must: A marker that would share a frame moves to the next free frame, and none is lost.
- Kind: given

### CRX-038: Resolve's scripting cannot set fades, keyframes, transitions or clip volume.
- Why: Item properties cover only a static opacity, so one cut's 22 audio fades and its manual gains, and levelling heard in the preview, never reached Resolve.
- Must: Every send and export carries fades, gain and levelling where it can, and names each one it dropped, with a count in words.
- Kind: given

### CRX-039: Resolve inserts a title only at the playhead, at a default length.
- Why: The title call takes no track, frame or duration, nothing resizes it later, the default is 5 s, and it ripples into track one and fails on a locked track.
- Must: Any title placed by script is checked for track, start and length afterwards, and removed without ripple when wrong.
- Kind: given

### CRX-040: Resolve silently refuses some property writes.
- Why: Setting loudness normalisation on Resolve 21.0.1 returns failure, and renaming a Fusion clip by its clip-name property silently does nothing.
- Must: Every Resolve property or name the product sets is read back, and a refusal is shown to the person.
- Kind: given

### CRX-041: Fade handles are audio only, heard in the browser and exact in Resolve.
- Why: The owner: "timeline cards only needs audio fades, not video fades", conforming "to resolve accurately", and fades must "actually play, not just be visual".
- Must: Cuts carry audio fade-in and fade-out handles that play as drawn in the browser and arrive in Resolve at the same lengths; the picture is never faded.
- Kind: ruling

### CRX-042: A per-cut gain was asked for but never reached Resolve.
- Why: The owner asked for per-cut gain; how Resolve stores a clip's volume was never confirmed, so a guessed level could put an unseen level into a timeline.
- Must: A cut's gain reaches Resolve at the level set, proven by reading back a known level; until proven, every send and export says plainly whether gain was carried.
- Kind: ruling

### CRX-043: A note on a gap becomes on-screen text in the Resolve timeline.
- Why: The owner: a gap note "should get built as a text object in resolve ... so that editors can see what the gap is for", "standard going forward for all conforms".
- Must: Every noted gap arrives as a Text+ title with its latest saved note, on a separate upper track at the gap's exact frame and length, moving no clip.
- Kind: ruling

### CRX-044: A gap-note title must never cover the next cut or move anything.
- Why: A title longer than its gap would sit over the next cut in every render, and a note marker in a section colour comes back as a new section heading.
- Must: Gap text never overlaps picture, no cut moves, every track lock is restored, and a note marker never reads back as a section.
- Kind: situation

## Talking to Resolve: restarts, dialogs and speed

### CRX-045: Clip references taken before a Resolve restart silently place nothing.
- Why: References from before a restart look usable but every append returns nothing; a 489-cut send built a blank timeline and reported success.
- Must: Clip references never outlive a Resolve restart, and a send placing fewer cuts than asked fails loudly, names refused cuts and leaves no empty timeline.
- Kind: given

### CRX-046: Resolve clip handles work only on the connection that fetched them.
- Why: Media pool clips fetched on one scripting connection and appended through another silently return an empty list.
- Must: Clips are fetched and appended on the same connection, and an empty append result counts as a failure.
- Kind: given

### CRX-047: Every Resolve call returns nothing while a dialog box is open.
- Why: While a modal dialog is up (a message box, a transcription progress window, "Audio Output: Remote Audio not found"), scripting calls return nothing at once; only closing it helps.
- Must: A call that returns nothing is treated as a possible blocking dialog and named to the editor, and an editor's own transcription is never cancelled.
- Kind: given

### CRX-048: Reading a 266-cut Resolve timeline takes about 150 ms.
- Why: Listing a 266-item track took about 90 ms, their source frames about 60 ms, the playhead 0.1 ms; appending in one batch cost about 11 ms per cut.
- Must: Following a Resolve timeline of up to 500 cuts updates the cards within a second and never stalls the editor's own clicks in Resolve.
- Kind: given

### CRX-049: A card click took up to 7 seconds to move Resolve's playhead.
- Why: A click normally reaches Resolve in 0.3 s, but took 7 s when every clip's path and name was asked one call each, or another program was walking the timeline.
- Must: A card click moves Resolve's playhead within half a second on several hundred cuts, even while other programs talk to Resolve.
- Kind: given

### CRX-050: Building a long timeline one Resolve call at a time is very slow.
- Why: A 396-cut build needed about 2,000 separate calls, and deleting 1,269 subtitle items one at a time was just as slow.
- Must: A build or bulk change of several hundred items shows progress and finishes in minutes.
- Kind: given

### CRX-051: A grabbed Resolve still exported an all-black frame while reporting success.
- Why: When Resolve's viewer has not reloaded, grabbing a still succeeds but exports black, and animated titles look different along their length.
- Must: Visual checks render a single frame at the item's midpoint instead of trusting a grabbed still.
- Kind: given

### CRX-052: Resolve never re-reads an open timeline whose stored data changes.
- Why: Changes written to the library for an open timeline are not seen until the project is closed and reopened.
- Must: Any change made to a timeline outside Resolve closes it first and reopens it after, with the editor's work saved beforehand.
- Kind: given

### CRX-053: After Resolve restarted, the page kept saying no timeline was open.
- Why: When Resolve came back on the same timeline, the page saw no change and kept its error banner and empty list until its own server restarted.
- Must: Within seconds of Resolve reopening a timeline, even an unchanged one, the cards show it again, with nothing restarted.
- Kind: situation

### CRX-054: A send to an unreachable Resolve failed eight minutes later.
- Why: With Resolve closed or unreachable, the build request was accepted, queued and only failed minutes later.
- Must: A send while Resolve is closed or unreachable is refused at the press with a sentence giving Resolve's state.
- Kind: situation

### CRX-055: Only one program may drive Resolve on a computer.
- Why: A second program driving Resolve on the same computer risks scripting for the whole session, and each failed start left another hidden connection running.
- Must: Never more than one connection to Resolve per computer: a second is refused (an unreadable process list counts as one running), and a failed start leaves nothing running.
- Kind: situation

### CRX-056: A stop must never cut a Resolve edit off halfway.
- Why: An edit sent to Resolve is several steps; stopping it partway leaves a timeline nobody asked for.
- Must: A stop, of one computer or the whole fleet, lets a Resolve edit in progress finish before taking effect.
- Kind: situation

### CRX-057: Keys sent to Resolve on the editor's behalf stopped him typing in Resolve.
- Why: Pressing "c" in Resolve triggered the product's helper and produced odd output and errors.
- Must: Nothing the product installs ever intercepts keys the editor types into Resolve or any other program.
- Kind: situation

## Sending a cut to Resolve

### CRX-058: Resolve files a new timeline in whatever bin the editor last clicked.
- Why: Resolve's scripted create-timeline puts the timeline in the currently selected media pool bin, wherever the editor happened to click last.
- Must: The editor can choose the bin a built timeline goes into, the editor's selected bin is restored afterwards, and an unknown bin is refused before building.
- Kind: given

### CRX-059: Resolve refuses a duplicate timeline name with a bare "Failed to create timeline".
- Why: Creating a timeline whose name already exists in the project fails with no reason given.
- Must: Every timeline the product creates gets a unique name, suffixed automatically when the asked-for name exists.
- Kind: given

### CRX-060: Timeline Cards hands its cut to Resolve only, to start.
- Why: The owner ruled "resolve only to start": other editing programs later, if a client needs one.
- Must: The cut is handed over to Resolve, and nothing before the hand-over depends on any editing program.
- Kind: ruling

### CRX-061: Nothing is built in Resolve until the editor confirms a dry run.
- Why: The owner: "don't automatically conform until I have looked at" the plan; nothing is applied unprompted, and plain edits never reach Resolve.
- Must: No timeline is built or changed in Resolve until the editor confirms after seeing the cut, marker and length counts.
- Kind: ruling

### CRX-062: "Conform" means the editor's edited cut, never the candidate pool.
- Why: Asked to conform a montage, the whole unedited pool (104 cards, 5-10 times too long) was sent; the owner: "the cut file is what needs conforming".
- Must: A send to Resolve uses the editor's saved cut, never the assistant's candidate pool or a board's arrangement unless explicitly named.
- Kind: ruling

### CRX-063: Sending a cut needs only its clips in the media pool, not an open timeline.
- Why: Sends were refused until a populated timeline was open; the owner: it "should be able to just conform even into a project with no timelines in it at all".
- Must: A send succeeds into a project with no timeline open, or none at all, whenever its clips are in the media pool; only an unreachable Resolve blocks it.
- Kind: ruling

### CRX-064: Every timeline sent to Resolve goes into a Timelines bin.
- Why: The owner: they "should always be moved to a timelines bin. If it doesn't exist, create it"; he renames a new timeline within seconds.
- Must: Each send puts its new timeline in a root bin named Timelines, created if missing, and follows it by unique id, never by name.
- Kind: ruling

### CRX-065: Sending is an action on the cut, with no top-bar button.
- Why: The only send control was a switch, so the owner's clicks "did nothing", and he does not want a send button in the top bar.
- Must: A cut offers one action that sends it to a new Resolve timeline: name it, see dry-run counts, confirm; the top bar holds no such button.
- Kind: ruling

### CRX-066: A person may drive Resolve only on computers signed in to their own account.
- Why: The owner: "users can only use [the app on computers] which are also signed in to their own account".
- Must: A cut sent to Resolve reaches only computers signed in to the sender's account, never another person's.
- Kind: ruling

### CRX-067: A send with missing clips must name each one and build nothing.
- Why: A cut's clips may be unknown or absent from the target media pool, and a partial timeline is worse than none.
- Must: A dry run lists every unmatched card; a send with any missing clip names each, says whose media pool was checked and when, and writes nothing.
- Kind: situation

### CRX-068: Short soundbites were matched to the wrong place in an interview.
- Why: Polished transcript text matches the raw words only loosely (0.77 to 0.93), so a loose match on a short phrase or two-character anchor can land anywhere.
- Must: When existing cuts located by text are brought in, a short excerpt is placed only on an exact match, otherwise flagged unmatched, never guessed.
- Kind: situation

### CRX-069: A montage arrived in Resolve under another project's timeline name.
- Why: An unset name fell back to a default left over from the first project.
- Must: A timeline sent to Resolve is named after its own cut, never a leftover default.
- Kind: situation

### CRX-070: The cut must record the name Resolve actually gave its timeline.
- Why: When the requested name is taken, the build takes the next free name, so the requested name may not be the timeline built.
- Must: After a build, the cut names the timeline that was really created.
- Kind: situation

### CRX-071: A thirteen-cut montage built a timeline with far more clips.
- Why: Sending a thirteen-cut montage to Resolve produced a timeline holding many more clips than the cut.
- Must: A timeline made from a cut holds exactly one clip per card, in the cut's order, and nothing else.
- Kind: situation

### CRX-072: Clip colours set in the cards did not reach Resolve.
- Why: The owner wants clip colours set in the cards carried into the built timeline; on a montage they did not arrive.
- Must: A colour set on a cut in the cards appears on that clip in the timeline Resolve receives.
- Kind: situation

### CRX-073: A build stopped early left 54 cuts with no audio or markers.
- Why: The build placed all video first, then audio, then markers, and with no timeline open the status flickered between available and unreachable.
- Must: A send reports done only when picture, sound and markers are all placed, flags any partial timeline, and keeps a steady status while Resolve is idle.
- Kind: situation

## Edits sent live and staged edits

### CRX-074: Edits wait as a draft until applied; a cut-loose draft becomes a new timeline.
- Why: Moves in Resolve were slow, so the owner wanted edits staged until he says so, an edit-at-once mode removed ("serves no purpose"), and independent cutting away from Resolve.
- Must: Edits stay a draft until applied, Resolve's own changes show meanwhile, and a cut-loose draft is sent as a new timeline the editor then follows, the original untouched.
- Kind: ruling

### CRX-075: Nothing cut from the timeline is ever lost.
- Why: The owner asked that every piece removed by a trim or delete be kept on an offcuts timeline in the same project, created if missing.
- Must: Every piece removed by a delete or trim stays recoverable in the project, leaving there only when its removal is undone.
- Kind: ruling

### CRX-076: After staged edits ran, the cards no longer matched Resolve.
- Why: A run can stop partway when Resolve refuses one edit, and once the moves worked in Resolve while the page stayed out of step.
- Must: Staged edits are saved on every change, each leaves the draft only once Resolve confirms it, and after a run the cards show exactly what Resolve holds.
- Kind: situation

### CRX-077: A card dragged on the page did not move in Resolve, and nothing said so.
- Why: Drags and later moves silently did nothing in Resolve, leaving the editor unsure whether the edit happened.
- Must: A move Resolve did not perform is reported on the page within seconds, and the card returns to where Resolve has it.
- Kind: situation

### CRX-078: The page silently showed a different timeline from Resolve's.
- Why: With the page held on another timeline, Resolve's updates were set aside, and only a small status text said so.
- Must: When the page shows something other than Resolve's open timeline, it names Resolve's timeline and offers a one-click "follow Resolve".
- Kind: situation

## Bringing Resolve's changes back into the cut

### CRX-079: Edits made in Resolve after a send had no way back into the cut.
- Why: Editing continues in Resolve after a send; one real comparison found 45 moved, 26 trimmed, 51 split, 51 new and 25 removed cuts.
- Must: The editor shows whether cut and timeline are in step and what differs, and on request, after a dry run, takes Resolve's changes back as one undoable revision.
- Kind: situation

### CRX-080: A comparison claimed every cut after one dragged cut had moved.
- Why: Compared naively, one cut dragged to the top marks everything after it as moved, and a blade reads as a trim plus a new cut.
- Must: A comparison reports the fewest moved cuts, a blade as one split, plus changed gaps, colours and markers, so a single drag reads as one move.
- Kind: situation

### CRX-081: Updating from a timeline must keep its colours and the cut's own notes.
- Why: A build paints each cut its interviewee's colour, and an update using derived colours left every cut and 23 sections a colour apart.
- Must: Updating a cut from its timeline takes the timeline's cut and marker colours, keeps notes, shelf, sequences and highlights, and then reports in step.
- Kind: situation

### CRX-082: Updating a cut from a different timeline than it names is a decision.
- Why: A cut names one timeline; updating it from another would silently replace the whole cut.
- Must: Updating from a timeline other than the one the cut names is refused, naming both, until the editor confirms.
- Kind: situation

## Which computer is driving Resolve

### CRX-083: The computer shown driving Resolve could be a made-up name, or merged with another.
- Why: With no declared machine the name came from the computer's own claim, and an older app's two computers registered as one bare person.
- Must: The computer shown driving Resolve comes from its verified identity; each of a person's computers appears separately, and a self-given name is marked unverified.
- Kind: situation

### CRX-084: An editor's two computers could not work in two episodes at once.
- Why: Requests followed the person's last request on any device, so Resolve requests and their answers landed in different episodes and applied edits were reported lost.
- Must: Each computer follows the episode open on that computer, and a request and its answer always reach the same episode.
- Kind: situation

### CRX-085: The link to Resolve showed green while dead for hours.
- Why: Healthy meant "was started", so a crashed loop, hours of refused sign-ins or an unreachable dashboard looked fine, and restarts waited on a different test.
- Must: Green needs a successful contact in the last 50 seconds, else it names stopped, refused or unreachable; anything shown stopped is restarted within a minute.
- Kind: situation

### CRX-086: The link looked healthy while every update from Resolve was thrown away.
- Why: With no episode open in the editor, updates were discarded with an OK answer, and the computer showed its timeline as being served.
- Must: When updates are discarded because no episode is open, the computer's status says so, with "open an episode", on the computer and the dashboard.
- Kind: situation

## Exports

### CRX-087: A cut exports as XML, OTIO, EDL and a plain text script.
- Why: The owner: "we should also keep the ability to export an xml otio edl and a txt script"; Premiere's reading of the XML is untested.
- Must: Any cut exports in those four forms, each naming what its format could not carry; a Premiere import is verified before being promised.
- Kind: ruling

### CRX-088: The text export holds each card in its spoken language only.
- Why: The owner asked for the cards as plain text and as a Markdown document with no English for Mandarin cards.
- Must: The cards export as plain text and as Markdown in timeline order, each card in its spoken language only, without translations.
- Kind: ruling

## Renders from Resolve

### CRX-089: An audio-only render from Resolve refused to start as WAV.
- Why: With WAV chosen through scripting, Resolve leaves the format unknown and refuses to render; an audio-only render works as MOV/H.264 with video export off.
- Must: Audio-only renders the product requests from Resolve start and finish without manual help.
- Kind: given

### CRX-090: A Resolve render can silently come out without its picture or sound.
- Why: After an audio-only export, Export Video stays off; turning it on by script reports success, yet renders are audio-only, and one episode render had no sound.
- Must: Every render is checked for a picture stream, sound and expected length before use; a 25-minute render finishing in under a minute is audio-only.
- Kind: given

### CRX-092: A render queue across projects must survive Resolve crashing.
- Why: The owner wanted renders queued from several projects, with a crash detected, Resolve restarted and the interrupted render resumed.
- Must: When Resolve dies during a queued render, the queue restarts Resolve, re-runs the interrupted job and continues with the rest.
- Kind: ruling

### CRX-093: The studio's default render is QuickTime H.264 at 3840x2160, proxies off.
- Why: The owner's defaults: QuickTime H.264, timeline frame rate, 3840x2160, proxy media off, best quality, subtitle export off.
- Must: Before a queue starts, each job differing from the studio defaults is listed per project with a yes or no to switch it.
- Kind: ruling

### CRX-094: Before rendering, clips hidden inside compound clips must be checked online.
- Why: Offline media inside compound clips does not show on the timeline.
- Must: Before a render is queued, every clip inside every compound clip on the timeline is checked, and offline ones are named.
- Kind: ruling

### CRX-095: A 61-minute timeline held a 25-minute cut plus parked clips.
- Why: Editors park unused clips after the cut: one timeline was 24:41 of cut, a 14-minute gap, then 96 unused clips.
- Must: A timeline's real end is found at the first gap of minutes, and renders and exports stop there.
- Kind: situation

## Titles and compound clips

### CRX-096: Compound clips should carry the name and colour of what they hold.
- Why: Resolve names new compound clips "Compound Clip 1, 2..."; the owner wants each named after its clip and coloured like that interviewee's multicam.
- Must: A compound clip the product creates is named after the clip it wraps and takes the clip colour of the related interviewee's multicam.
- Kind: ruling

### CRX-097: Name titles sat half off screen and could cover the speaker.
- Why: Left titles were placed by their far edge and right ones ran off frame; the owner wants the visible edge 50 px in, opposite the speaker.
- Must: A name title's visible edge sits 50 px in from the side and bottom, on the side away from where the speaker appears.
- Kind: ruling

### CRX-098: When one interviewee cuts straight to another, name titles hand over.
- Why: The owner: with no b-roll between, "the outro for the previous third plays and the new third for the new interviewee comes in. Obviously."
- Must: On a direct cut between two speakers, the first speaker's title plays its exit and the second speaker's title plays its entrance.
- Kind: ruling

## Subtitles and delivery

### CRX-099: Resolve places imported subtitles offset along the track.
- Why: Imported subtitles land at the end of the track, offset by their own times, so cues sat too far along and looked misaligned.
- Must: Subtitles placed on a timeline line up with the cut from frame zero, each within a frame of its speech, with no manual shifting.
- Kind: given

### CRX-100: Subtitle files exported from Resolve carry invisible line-separator characters.
- Why: Ten of eleven English subtitle files exported from Resolve held 293 invisible line separators (Unicode U+2028), 150 of them in one episode.
- Must: Every subtitle file the product writes or passes on is free of invisible line-separator characters.
- Kind: given

### CRX-101: Subtitles already on a Resolve timeline are reused, never made again.
- Why: The owner: "you shouldn't need to transcribe again because the srts already exist ... you will be able to export the SRTs from the timelines directly".
- Must: When a Resolve timeline already carries subtitles, the product exports those rather than making new ones.
- Kind: ruling

### CRX-102: A finished cut's English subtitles read as natural documentary English.
- Why: The owner asked for English "in a natural, dramatic way suitable for a documentary", with gap notes put on as text or subtitles.
- Must: A finished cut gets English subtitles in natural documentary English, timed to the speech, with gap notes carried as visible text.
- Kind: ruling

### CRX-103: Bilingual on-screen text splits lines by count, Chinese above English.
- Why: The owner's layout: two lines are one title and one subtitle, three are one and two, four two and two; same size and colour, one bottom baseline.
- Must: Lines split 1, 1+1, 1+2, 2+2, both languages change at the same frames, blocks grow upward from a fixed margin, and sizes and gaps are adjustable first.
- Kind: ruling

### CRX-104: A subtitle line must never start with the tail of the previous sentence.
- Why: Generated subtitles were cut by length mid-clause, so a cue opened with "heavy." then a new sentence; the owner wants sentence-first breaks.
- Must: Cues break at sentence ends then clauses, at most about 95 English or 42 Chinese characters, with times interpolated and all text kept.
- Kind: ruling

### CRX-105: Captions hold through short pauses.
- Why: The owner asked that gaps up to 1.2 seconds in documentaries, 1.5 in reels, be closed by extending the earlier caption.
- Must: Gaps at or under the set limit are bridged, longer gaps stay empty, and a limit of zero turns bridging off.
- Kind: ruling

### CRX-106: A TV network delivery needs two-language subtitles and a name-strap list per episode.
- Why: The owner: subtitles in a folder inside each submission, one English and one Chinese; name straps in a sheet, "each episode in its own tab", no file names.
- Must: Each delivered episode gets English and Chinese subtitle files in its own folder, and a list of every speaker with a screenshot and name.
- Kind: ruling

### CRX-107: Chinese subtitle lines split English words mid-word, as "crea" and "tivity".
- Why: Character-based Chinese line breaking cuts through embedded English words and numbers ("40%" into "4" and "0%"), which the studio's Chinese speech often quotes.
- Must: No line break falls inside a run of Latin letters, digits or % ' . -, and lines carry no stray leading or trailing space.
- Kind: situation

### CRX-108: Delivered subtitles had unsubtitled stretches and lines lingering through music.
- Why: Archive news went unsubtitled for up to 2.5 minutes, lines held up to 2 minutes across music, cues overlapped, and some covered footage cut out.
- Must: Before delivery, every stretch of speech has a subtitle, no cue spans a break in speech, no cues overlap, and none fall past the cut's end.
- Kind: situation

### CRX-109: A person's name was spelled differently across subtitles and name straps.
- Why: One interviewee had two English spellings and a mayor three Chinese renderings, and subtitles disagreed with the name-strap sheet the network would use.
- Must: Each person's name is spelled one way per language across every subtitle file and name-strap list of an episode.
- Kind: situation
