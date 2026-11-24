# Sealed notes: resolve-keystrokes

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 5 notes.

### CRX-021: Resolve's select-at-playhead and split act on every track with auto-select on.
- Why: A delete aimed at V1 also took a V2 overlay or another interviewee's audio clip, and with A1 off a split cut picture but not sound.
- Must: Deleting a card removes only that card's picture and sound; any change on another track is undone and reported.
- Tool: Resolve's select-at-playhead and split commands, driven by keystrokes
- Where it bit: Timeline Cards: the hand-over to Resolve, and exports

### CRX-S09: Keystroke edits into Resolve work only on an unlocked desktop with Resolve open.
- Why: A locked or sleeping computer cannot take key presses, so the page must say Resolve is away rather than pretend.
- Must: When edits cannot reach Resolve, the page says "away since" a time, keeps playing, searching and staging, and never claims an edit landed.
- Tool: sending keystrokes into Resolve
- Where it bit: Timeline Cards: the hand-over to Resolve, and exports

### CRX-S10: Edits made by sending keys to Resolve need focus, settling time and order.
- Why: Keys reach Resolve only with its timeline panel focused, a key after a long playhead jump can vanish (settle 0.35 s), Match Frame resets marks, and one move took 6 s on 359 cuts.
- Must: Focus the timeline panel, set marks after Match Frame, and confirm every keystroke edit by reading the timeline back, reporting and undoing a lost step.
- Tool: sending keystrokes into Resolve (AutoHotkey; mark in is 1-based, clearing marks is not an undo step)
- Where it bit: Timeline Cards: the hand-over to Resolve, and exports

### CRX-S11: Keystroke edits landed on the wrong clip while Resolve was playing.
- Why: With Resolve playing or on another page, a keystroke edit acts on whatever clip the playhead happens to be over.
- Must: Read back Resolve's playhead and page before sending any keystroke edit, and refuse when the playhead is not exactly where intended.
- Tool: sending keystrokes into Resolve
- Where it bit: Timeline Cards: the hand-over to Resolve, and exports

### RSV-S12: Keystrokes typed into Resolve by simulation lose characters.
- Why: A multicam name sent as simulated typing arrived as "陳政隆 Mul" instead of "陳政隆 Multicam".
- Must: Anything entered into Resolve by simulated typing is read back and corrected if it differs.
- Tool: sending keystrokes into Resolve
- Where it bit: Resolve on the editor's computer
