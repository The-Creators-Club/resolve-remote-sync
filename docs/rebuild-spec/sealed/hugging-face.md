# Sealed notes: hugging-face

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 2 notes.

### BRO-S13: A 3.3 GB model download crawled at 2 MB/s on one stuck connection.
- Why: The model host can pin one long connection to a slow edge; fresh connections got 13 MB/s, six parallel ranges about 40 MB/s.
- Must: Large downloads use parallel ranges, reconnect a range moving under 256 KiB in 20 s, resume per range, and retry from the original link.
- Tool: Hugging Face (model download network)
- Where it bit: The b-roll archive

### APP-S14: A model download crawled at 2 MB/s and looked broken.
- Why: One long connection to the model host's delivery network stalled near 2 MB/s while fresh parallel connections reached 37 to 45 MB/s.
- Must: A multi-gigabyte download recovers from a stalled connection by itself, resumes after interruption, and shows its rate and time left.
- Tool: Hugging Face CDN downloads
- Where it bit: The app on each editor's computer
