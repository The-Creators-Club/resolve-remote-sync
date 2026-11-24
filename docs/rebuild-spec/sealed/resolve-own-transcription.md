# Sealed notes: resolve-own-transcription

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 3 notes.

### CFI-041: Resolve transcribes a multicam to the end only from a 24-bit recorder track.
- Why: A 16-minute multicam stopped at 13 minutes and another left a 270 s hole; with a 24-bit recorder render active on track 1, both came back whole, 476 words more.
- Must: When Resolve must transcribe a multicam, it does so against a full 24-bit recorder render, and the result is checked for holes.
- Tool: Resolve's own transcription, started by script
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-042: Resolve's transcription language is one project-wide setting, and redoing returns the cache.
- Why: There is no per-clip language (46 of 84 English clips came out as fluent nonsense Mandarin), and re-transcribing returns the cached result unless it is cleared first.
- Must: Anything asking Resolve to transcribe sets each clip's real language, clears the earlier result first, and restores the project setting afterwards.
- Tool: Resolve's own transcription, started by script
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-047: Resolve refuses to transcribe after a render until the Edit page is opened.
- Why: After a Deliver-page render every clip refused transcription; sharing the GPU with another transcriber dropped Resolve to real time and stalled it 20 minutes.
- Must: Any Resolve transcription starts from the Edit page and never runs beside another GPU transcription.
- Tool: Resolve's own transcription, started by script
- Where it bit: Timeline Cards: footage in, ready to cut
