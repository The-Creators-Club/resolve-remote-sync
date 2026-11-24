# Sealed notes: resolve-editing-a-timeline-by-script

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 3 notes.

### CRX-018: A scripted delete in Resolve leaves the clip's linked audio behind.
- Why: The leftover audio silently blocks later appends over those frames while the call reports success, and left another interviewee's sound duplicated underneath a moved cut.
- Must: Removing or moving a cut removes its picture and sound together, and no orphaned or duplicated sound is left on the timeline.
- Tool: Editing an existing Resolve timeline by script
- Where it bit: Timeline Cards: the hand-over to Resolve, and exports

### CRX-022: Resolve's scripting cannot move a clip, insert mid-timeline, or announce changes.
- Why: Scripting offers append and delete only, so moving one card meant rebuilding everything after it, and a change made in Resolve is seen only by reading again.
- Must: A change the editor makes in Resolve shows in the cards within about one second without Resolve announcing it, and moving one card takes seconds.
- Tool: Editing an existing Resolve timeline by script
- Where it bit: Timeline Cards: the hand-over to Resolve, and exports

### CRX-036: Resolve's markers stay put when a ripple edit moves the cuts under them.
- Why: Ripple moves, deletes, trims and inserts leave timeline markers at their absolute frames, so section markers land on the wrong cut; scripting has no marker move.
- Must: After any edit, each marker still sits on the cut it marked, keeping its name, colour, note and duration, within one undo step.
- Tool: Editing an existing Resolve timeline by script
- Where it bit: Timeline Cards: the hand-over to Resolve, and exports
