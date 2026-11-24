# Answers against lessons: cards-to-resolve-and-exports

## Lessons

### CRX-014: amend
- Answer: page 29, 29.2 (accepted, confirmed on page 31, 31.1 "Yes, it goes."): "B: it goes; a cut is edited only as a cut list, handed over as a new timeline, and Resolve's later changes come back through the header chip and the Import tab as one undoable step."
- Lesson says: "untouched cuts keep their exact frames and their grades."
- Field: must
- New words: Sending a cut list identical to the timeline writes nothing, and untouched cuts keep their exact frames.
- Because: every send builds a new timeline, whose cuts arrive ungraded, so no send rewrites cuts in an existing graded timeline whose grades it could keep.

### CRX-020: amend
- Answer: page 29, 29.2 (accepted; page 31, 31.1): "nobody edits a Resolve timeline from the cards; they edit the cut, send it, and bring Resolve's changes back."
- Lesson says: "Before every write the open timeline is confirmed as the one being edited and unchanged; otherwise the edit stops, is rolled back and is reported."
- Field: must
- New words: Before every write the new timeline is confirmed as the current one; otherwise the send stops, the new timeline is removed and the person is told.
- Because: the only writes left are the building of a new timeline, so there is no timeline "being edited" to confirm unchanged or roll back.

### CRX-023: amend
- Answer: page 29, 29.2 (accepted; page 31, 31.1): "Editing Resolve's timeline live from the cards (moving, deleting, splitting and inserting clips in Resolve from Timeline Cards, and staged drafts) ... **"Yes, it goes."**"
- Lesson says: "an in-place edit containing a gap is refused with that reason, never failing silently."
- Field: must
- New words: Gaps appear in timelines built whole, never failing silently.
- Because: in-place edits of a Resolve timeline are cut, so there is nothing to refuse.

### CRX-035: amend
- Answer: page 29, 29.2 (accepted; page 31, 31.1): "B: it goes; a cut is edited only as a cut list, handed over as a new timeline"
- Lesson says: "An edit the product makes costs a known small number of undo steps, and undoing it checks the timeline state, never undoing the editor's own work."
- Field: must
- New words: A send costs a known small number of undo steps, and nothing the product does ever undoes the editor's own work in Resolve.
- Because: the product no longer makes live edits it undoes through Resolve's undo history; a send is taken back by removing its new timeline.
- Doubt: whether a build of hundreds of appends can cost "a small number" of undo steps at all; the specification keeps the phrase, so it is kept here.

### CRX-048: amend
- Answer: page 29, 29.2 (accepted; page 31, 31.1): "Following Resolve's playhead and sending a finished cut both stay."
- Lesson says: "Following a Resolve timeline of up to 500 cuts updates the cards within a second"
- Field: must
- New words: Reading a Resolve timeline of up to 500 cuts finishes within a second and never stalls the editor's own clicks in Resolve.
- Because: the view that showed Resolve's open timeline as cards is gone; a timeline is read only for the comparison, and only the playhead is followed.

### CRX-052: amend
- Answer: page 29, 29.1 (accepted): "A: one hand-over, always into Resolve running on the sender's computer with the project open; ... nothing closed; refused at the press with Resolve's state when Resolve is not there."
- Lesson says: "Any change made to a timeline outside Resolve closes it first and reopens it after, with the editor's work saved beforehand."
- Field: must
- New words: Nothing is ever written into a Resolve project from outside Resolve; every change to a timeline goes through Resolve running with the project open.
- Because: he chose against option B, the write into a saved project with the project closed and reopened, so no change is ever made outside Resolve.

### CRX-053: amend
- Answer: page 29, 29.2 (accepted; page 31, 31.1): "B: it goes; a cut is edited only as a cut list ... The Live tab (following Resolve's playhead and jumping Resolve to a cut) stays either way."
- Lesson says: "the cards show it again, with nothing restarted."
- Field: must
- New words: Within seconds of Resolve reopening a timeline, even an unchanged one, the editor shows it open again, with nothing restarted.
- Because: Resolve's open timeline is no longer shown as cards; the editor shows only what Resolve has open.

### CRX-063: amend
- Answer: page 29, 29.1 (accepted): "A: one hand-over, always into Resolve running on the sender's computer with the project open; missing clips imported ... refused at the press with Resolve's state when Resolve is not there."
- Lesson says: "only an unreachable Resolve blocks it."
- Field: must
- New words: A send succeeds into an open project with no timeline open, or none at all, whenever its clips are in the media pool; only an unreachable Resolve blocks it.
- Because: a send needs the cut's project open in Resolve, so a reachable Resolve without that project open also blocks it.
- Doubt: a ruling; the two can be read side by side. If "unreachable" already meant "not running with the project open", nothing changes.

### CRX-095: amend
- Answer: page 30, 30.10 (accepted, the figure now his): "A: one minute by default, shown and settable by hand each time."
- Lesson says: "A timeline's real end is found at the first gap of minutes"
- Field: must
- New words: A timeline's real end is found at the first empty stretch of one minute or more, shown and settable each time, and renders and exports stop there.
- Because: he set the length to one minute by default, settable by hand.

### CRX-097: amend
- Answer: page 30, 30.9 (accepted): "A: no. The rulings describe how name titles you add yourself in Resolve must be treated (left where they are, never moved or lost by a later hand-over)."
- Lesson says: "A name title's visible edge sits 50 px in from the side and bottom, on the side away from where the speaker appears."
- Field: must
- New words: A name title the editor places in Resolve, visible edge 50 px in from side and bottom, away from the speaker, is never moved, shortened or lost by the product.
- Because: the product never places name titles; the ruling now governs how the editor's own are treated.

### CRX-098: amend
- Answer: page 30, 30.9 (accepted): "A: no. The rulings describe how name titles you add yourself in Resolve must be treated (left where they are, never moved or lost by a later hand-over)."
- Lesson says: "On a direct cut between two speakers, the first speaker's title plays its exit and the second speaker's title plays its entrance."
- Field: must
- New words: On a direct cut between two speakers, the editor's titles, the first playing its exit and the second its entrance, are left as they are by every hand-over.
- Because: the product never places name titles, so the rule is about keeping the editor's own.

### CRX-105: amend
- Answer: page 30, 30.11 (accepted, the figure now his): "A: pauses under one second are bridged, as a setting."
- Lesson says: "The owner asked that gaps up to 1.2 seconds in documentaries, 1.5 in reels, be closed by extending the earlier caption."
- Field: why
- New words: The owner asked that short pauses between captions, under one second by default, be closed by extending the earlier caption.
- Because: he set one default of under one second, replacing the two lengths.
- Doubt: page 30 said the limit was "not built" and did not show him his earlier 1.2 and 1.5 seconds; asking whether documentaries and reels keep different defaults would settle it.

### CRX-105: amend
- Answer: page 30, 30.11 (accepted): "A: pauses under one second are bridged, as a setting."
- Lesson says: "Gaps at or under the set limit are bridged"
- Field: must
- New words: Gaps under the set limit are bridged, longer gaps stay empty, and a limit of zero turns bridging off.
- Because: his answer bridges pauses under the limit, not at it.
- Doubt: as above; a one-word difference at the boundary.

## Read

- lessons read: 93
- decision questions read: 67 (page 29: 9, page 25: 14, page 3: 10, page 30: 14, page 31: 4, DECISIONS pages 1 and 2: 16)
