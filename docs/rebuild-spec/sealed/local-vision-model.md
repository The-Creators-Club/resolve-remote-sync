# Sealed notes: local-vision-model

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 3 notes.

### BRO-S07: The largest local vision model needed about 18 minutes per clip on a laptop.
- Why: On an Apple M4 laptop the 30-billion-parameter model was forecast at 6 hours for 20 clips; the owner: "it's a disaster then".
- Must: Every describing tier offered finishes a 20-clip batch in under an hour on the hardware its tooltip names.
- Tool: Qwen3-VL 30B-class local vision model on Apple silicon
- Where it bit: The b-roll archive

### BRO-S08: Full-HD stills cost twice the image budget of the local vision model.
- Why: A 1080p frame costs about 2,040 image tokens against 1,024 at 960 wide, so an 8 or 9 frame window overflows the 16,384-token slot and the clip fails.
- Must: Every b-roll clip from a 1080p proxy is described without failing on input size.
- Tool: local Qwen3-VL vision model
- Where it bit: The b-roll archive

### BRO-S11: A local vision model invents shot times unless pinned to real frames.
- Why: Model-reported shot times drift; frames labelled with timecodes, output bounded to the frames sent, and times looked up from those frames gave usable segments.
- Must: Every shot segment's start and end come from frames actually sampled, and adjacent near-identical segments are merged.
- Tool: Qwen3-VL through llama.cpp, with a GBNF grammar and timecode-labelled frames
- Where it bit: The b-roll archive
