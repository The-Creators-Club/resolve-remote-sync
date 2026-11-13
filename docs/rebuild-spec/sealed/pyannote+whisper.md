# Sealed notes: pyannote+whisper

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names every one of these tools. 1 notes.

### CFI-S11: An hour of rushes transcribes in about three minutes on the studio GPU.
- Why: On an RTX 3080: 20 to 24x realtime transcribing, about 20x for speakers, about 10x for both; models load in 2.2 s and 5.1 s.
- Must: An hour of footage transcribes in minutes, and models load once per batch, never once per clip.
- Tool: faster-whisper large-v3-turbo float16 on CUDA, with pyannote for speakers
- Where it bit: Timeline Cards: footage in, ready to cut
