# Sealed notes: rclone+yt-dlp

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names every one of these tools. 1 notes.

### SYN-S17: The transfer tool rewrites full-width punctuation in file names unless told not to.
- Why: By default on Windows it marked names holding full-width forms with U+201B and mapped ： ？ ｜ back to plain forms, asking for files that did not exist (628 of 2,507 names).
- Must: The tool's local name encoding is pinned so names round-trip byte for byte, tested with full-width ？ ： and quotes, and a failure names the file.
- Tool: rclone (--local-encoding; default Windows encoding) with yt-dlp's full-width names
- Where it bit: Sync
