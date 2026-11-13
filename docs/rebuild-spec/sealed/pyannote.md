# Sealed notes: pyannote

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 1 notes.

### CFI-S15: The speaker-detection models are gated, read only some audio formats, and break on upgrades.
- Why: Models load only for an account that accepted their terms, else nothing returns with no error; MP4 fails; newer torch refuses old checkpoints.
- Must: Speaker detection gets decoded 16 kHz mono audio, pinned runtime versions, and an up-front licence check naming which terms to accept.
- Tool: pyannote.audio 3.3 speaker-diarization-3.1 under torch 2.6
- Where it bit: Timeline Cards: footage in, ready to cut
