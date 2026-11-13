# Sealed notes: ffmpeg

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 8 notes.

### JOB-S01: A machine lists the hardware encoder and then fails mid-encode.
- Why: A machine without a suitable graphics card still lists the hardware encoder; a 64x64 test frame fails even on a real RTX 3080.
- Must: Hardware encoding is used only after a real one-frame encode of at least 320x240 succeeded on that machine.
- Tool: ffmpeg h264_nvenc
- Where it bit: Work shared out across the computers

### JOB-S02: A temporary output name broke the encoder.
- Why: The tool picks the format from the extension, so "name.m4a.partial" fails; .m4a, .mp4 and .ogg map to the formats ipod, mp4 and ogg.
- Must: Any output written under a temporary name states its format explicitly, and the result is byte-identical to the normal command.
- Tool: ffmpeg
- Where it bit: Work shared out across the computers

### SRT-S05: The general decoder cannot read BRAW or R3D, so pictures come from the proxy.
- Why: BRAW clips showed no thumbnail or preview because the decoder used cannot open BRAW or RED RAW files.
- Must: A RAW clip's thumbnail and preview come from the camera's proxy; with no proxy yet the page shows a placeholder and retries later.
- Tool: ffmpeg (no BRAW or R3D decoder)
- Where it bit: The Footage Sorter and camera cards

### SRT-S06: One decode run reading many points of one file grew to tens of gigabytes.
- Why: Opening the same 4K clip as 50 separate inputs in one run, each with every processor thread, held frame buffers for all of them at once.
- Must: Each filmstrip frame is taken by its own short seek-and-decode with few threads, and frames are tiled in a separate small step.
- Tool: ffmpeg
- Where it bit: The Footage Sorter and camera cards

### SRT-S07: Joining many seeked inputs of one clip gave consecutive frames from the start.
- Why: When each seeked input ran to the end of the file, the join took the first input's frames first, so every tile came from the opening seconds.
- Must: Each seeked input is limited to exactly one frame before frames are joined into a strip.
- Tool: ffmpeg
- Where it bit: The Footage Sorter and camera cards

### PRX-S01: The open-source encoder cannot make proxies from BRAW, R3D or Canon RAW.
- Why: The encoder cannot decode these camera raw formats at any quality, so those clips stayed without proxies.
- Must: Raw clips missing proxies are reported and handed to a tool that reads them, never queued for this encoder.
- Tool: ffmpeg (no BRAW, R3D or CRM decoding)
- Where it bit: Proxies and file moves

### PRX-S02: An overnight run of 1,040 proxies produced none.
- Why: The encoder picks its output format from the file extension, and a temporary ".partial" name gave it none, so all 6,290 attempts failed at start.
- Must: Every encode names its output format explicitly whatever the temporary file is called, and a failure records the encoder's first error lines.
- Tool: ffmpeg
- Where it bit: Proxies and file moves

### PRX-S03: Encode progress stuck at 0 percent, or the encoder hung.
- Why: The progress field named in milliseconds holds microseconds, and an unread progress pipe fills at about 64 KB and blocks the encoder for good.
- Must: Progress shows a true percentage, is updated at most once a second, and asking for it never stalls an encode.
- Tool: ffmpeg -progress (out_time_ms holds microseconds, like out_time_us)
- Where it bit: Proxies and file moves
