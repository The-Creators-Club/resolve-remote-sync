# Sealed notes: loudness-envelope-cross-correlation-for-multicam-sync

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 1 notes.

### CFI-S31: Camera microphones agree on loudness contours, not on raw waveforms.
- Why: Raw waveforms disagree between mics while loudness envelopes agree; a narrow search found 3 of 43 takes until a whole-track pass found the 154 s offset.
- Must: The coarse offset is found over whole tracks first, then each take in a narrow window, judged against the consensus of strong matches.
- Tool: loudness-envelope cross-correlation for multicam sync
- Where it bit: Timeline Cards: footage in, ready to cut
