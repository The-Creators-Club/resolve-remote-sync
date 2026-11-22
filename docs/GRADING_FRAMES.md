# Grading frames - one frame of a camera raw original, in Resolve, on a remote computer

Written 2026-11-22, from the owner's ask (2026-11-10, repeated 2026-11-21 and
2026-11-22):

> what I really need is just the ability for a remote editor to see one frame
> in resolve of the camera raw original that's on the server so they can grade
> it and change the camera raw settings

It is requirement **RSV-147** in the rebuild knowledge base
(`docs/rebuild-spec/knowledge-base/resolve-on-the-editors-computer.md`), listed
there as still open.

**Status: BUILT and committed on 2026-11-22 (phases 1 to 4 of section 7), as
TWO companion releases in a fixed order (section 10.1). Release A is
companion 0.9.98, on `main`. Release B is companion 0.9.99, parked on the
branch `grading-frames-release-b`, and is NOT to be merged or published until
every machine runs 0.9.98 or newer.** Section 10 says what was built, what the
review changed, what was checked on real footage, and what still has to be
tried by hand.

Before the build: the file half of the spike (section 2.1 to 2.3) and the
Resolve half (section 2.4) were both run on creator-1 on 2026-11-22, the
Resolve half in a scratch project holding a real multicam copied out of Base
Drone. The method works, including inside a multicam. The spike changed the
design in four places (section 2.5). The other cameras (Sony, DJI, ProRes,
Nikon, iPhone) were tested the same evening for the second build (section
2.6). What is still untested is in section 6 and section 10.5.

Related: `docs/SELECTIVE_ORIGINALS.md` (whole originals on request, built: the
menu scripts, the request inbox and the download route this plan reuses),
`docs/BROLL_PROXY_TIERS_PLAN.md` section 3 and 6 (the stand-in spike: what
Resolve does when a file changes under a clip), `docs/SYNC_SAFETY.md`,
`docs/FILE_MOVES.md`, `docs/GOTCHAS.md` section 15 (CR-68).

Written against companion 0.9.97 and Resolve Studio 21.0.1.11 on creator-1.

---

## In plain words

- A remote editor has the small proxy copies, never the big camera originals.
  To set the camera raw controls (ISO, white balance, exposure, highlight
  recovery) Resolve needs the real raw file. A proxy has those choices baked
  in.
- Bringing the whole original down is already possible ("Bring originals"),
  but a clip is 3 to 40 GB, and one on the NAS is 370 GB. To judge a grade the
  colourist needs one frame.
- **The plan:** the editor parks the playhead on a frame and picks
  **Workspace > Scripts > CC Sync > Bring grading frame**. CC Sync fetches
  about 6 MB, a few seconds, and puts a **hollow copy** of the original where
  Resolve already expects the file. A hollow copy has the clip's index and the
  one frame asked for; the rest of it is empty space that takes no room on
  the disk.
- Because the hollow copy sits at the original's own path, it is the SAME
  clip in the shared project. The raw settings the editor changes are saved on
  the real clip. Nothing has to be copied across afterwards, and the base rig
  renders with them.
- **Tested in Resolve, and it works.** A 78 GB interview clip became a 14 MB
  hollow copy. Resolve shows the fetched frame pixel for pixel as it shows it
  from the real original, the Camera Raw panel is live on it, an exposure
  change shows at once, and it is still there after the project is saved,
  closed and reopened.
- **Inside a multicam it works too**, with one thing to know: on the multicam
  itself Resolve shows the Camera Raw panel greyed out (it always does). The
  raw settings are changed on the angle's own clip, in the angle timeline
  ("... ANGLE 1 (BMCC)"), and the change then shows in the multicam in the
  cut. The menu can work out which angle clip and which frame the playhead is
  on, and say where to go.
- **To see the frame the editor switches Playback > Proxy Handling to "Prefer
  Camera Originals".** In "Prefer Proxies" everything plays from the proxies
  exactly as before and the hollow copy is invisible. In "Prefer Camera
  Originals" the fetched frames show as true raw, and every other frame of
  that clip shows Media Offline.
- **Ask for the frames you want in one go.** Resolve locks the file while the
  project is open, so more frames for the same clip only show after the
  project is closed and reopened. The first request for a clip shows up as
  soon as the editor switches to another timeline and back.
- **A render cannot quietly go wrong.** Resolve refuses to render an empty
  frame: the job fails and names the clip and the timecode.
- A hollow copy must never be mistaken for a real copy of the footage: not
  uploaded, not counted as a backup. Section 4 is about that, and it is the
  part of this feature that most needs care.
- **Still untested:** a Mac, the download speed on a remote editor's
  connection, and the clip's own sound (section 6).

---

## 1. Where things stand today

| Route | What it gives | State |
|---|---|---|
| Lane B | proxies down | live; a proxy cannot carry raw settings |
| Swap P: to the server ("Grade from server originals", RSV-146, `drive_swap.py`, companion 0.9.54) | every original, read over the network for the session | built, Windows only. UX-6 (it could delete a real mapping on P:) has a fix that KNOWN_BUGS still marks unshipped; RSV-148 (its first real use left everything offline, because it needed a NAS login nothing asked for) is open |
| Bring originals (`docs/SELECTIVE_ORIGINALS.md`; `sync/originals_lane.py`, `originals_requests.py`, `resolve_menu/*.lua`) | whole chosen originals onto one computer | built. 3 to 40 GB a clip |
| One frame (RSV-147) | this plan | not built |

"Bring originals" answers "I need this clip for real". This plan answers "I
need to see what this clip really looks like so I can set it". They share the
menu, the request inbox and the download route.

---

## 2. What was measured (2026-11-22, creator-1)

The scripts are in `tools/spikes/grading_frames/` (`braw_atoms.py`,
`make_hollow.py`, `braw_probe.py`, `braw_sweep.py`). They read the NAS
read-only. The decoder used is `BlackmagicRawAPI.dll` from the installed
Resolve 21.0.1.11, driven directly on the CPU.

### 2.1 How a `.braw` is laid out

Test clip: `P:\Projects\2026\Base Drone\B-roll\2026台灣無人飛機創意設計競賽\A007_08090854_C137.braw`,
3,054,268,053 bytes, 990 frames, 6048x4032, 30 fps.

- It is a QuickTime file: `wide` (8 bytes), `mdat` (the pictures and sound),
  then `moov` (the index) **at the end**, 450,197 bytes.
- Every frame is its own block: one sample per chunk, a 64-bit offset each
  (`co64`), no dependence on any other frame (no sync-sample table). Frames
  here are 2.28 to 3.69 MB.
- The first 4,100 bytes are the two headers and the 4-byte timecode sample.
  The first frame starts at byte 4,100 on every clip looked at.
- Every frame starts with the bytes `00 00 04 00 'bmdf'`, which gives a cheap
  "this really is a frame" check after a fetch.
- Sound (24-bit PCM) and two small metadata tracks are interleaved through the
  file in one-second chunks.

**Sweep of 160 clips from 124 folders** under `P:\Projects\2025` and `2026`
(3,629 `.braw` files in all), 18 seconds:

| Check | Result |
|---|---|
| index is the last thing in the file | 157 of 157 |
| one frame per chunk, 64-bit offsets, no sync-sample table | 157 of 157 |
| first frame at byte 4,100, starts with `bmdf` | 157 of 157 |
| codec variants seen | `brlt` 139, `brst` 16, `brxq` 2 |
| file size | median 4.96 GB, largest 370 GB, 84 over 4 GB |
| mean frame size | median 3.06 MB, largest single frame 15.4 MB |
| index size | median 0.46 MB, largest 2.07 MB |
| could not be read by the sweep script | 3, all `_S00n.braw` single-frame stills of about 3 MB. A file that small is simply fetched whole (section 3.4) |

### 2.2 The hollow copy, in Blackmagic's decoder

| Test | Result |
|---|---|
| Hollow copy holding head + index + frame 495 (3.62 MB of 3.05 GB) | opens; frame count and timecode read correctly; **reading the picture size fails** |
| The same plus the first 4 KB of frame 0 | opens fully: 990 frames, 6048x4032, 30 fps |
| Frame 495 decoded from the hollow copy against the same frame from the original on the NAS | **identical** (same SHA-1 of the decoded picture, `839241b3...`) |
| An empty frame (100) | the read fails cleanly (`E_FAIL`, 0x80004005). No crash, no hang, and frame 495 decodes again straight after |
| A marker appended after the index (a `free` atom holding a line of JSON, so the length is no longer the original's) | opens and decodes exactly as before |
| Disk use on NTFS | 3.05 GB long, about 6 MB allocated (three ranges, `fsutil sparse queryrange`) |

Two traps found on the way, both for the build to carry as comments and
tests:

- **Never extend the file with `truncate()`.** On Windows the C runtime
  zero-fills, which fills the holes: the first attempt allocated 1.9 GB for a
  "hollow" 3 GB clip. Set the sparse flag, then seek and write; writing the
  index at the end is what sets the length.
- **The decoder needs the first frame's header** to open the clip at all. The
  plan fetches the whole first frame (2 to 3 MB), so the clip also has a
  picture at frame 0.

### 2.3 Not measured in the file half

- **A ranged read through the editors' download route.** `rclone cat --offset
  N --count M` is the documented way to read part of a remote file; the test
  from creator-1 failed at sign-in ("unable to authenticate") because this
  wired rig's own rclone remote has no working key, which is not what an
  editor's computer has. Timing it on a remote machine is item 2 of section 6.

### 2.4 The hollow copy, in Resolve (2026-11-22, Resolve Studio 21.0.1.11)

Set-up: the timeline `HMCC Spans` (three multicam clips and nine plain clips)
was exported from Base Drone as a `.drt` and imported into a scratch project,
`Grading frames spike 2026-11-22`, in the same library. Base Drone itself was
only read. Hollow copies were built in a scratch folder from the originals on
the NAS and the scratch project's clips were pointed at them. Pictures were
compared by exporting the Color page's current frame as a still and hashing
the pixels. `scriptapp()` was called only behind `script_server.ready_to_connect()`
(CR-68).

The multicam under test is `Talk UA 10-21 - war stories Multicam`. Its angle 1
is the timeline `Talk UA 10-21 - war stories — ANGLE 1 (BMCC)`, which holds
`G011_10211743_C075.braw`: 25,260 frames, **77.8 GB**. The hollow copy with
frames 0, 6557, 6558 and 6559 is **13.6 MB**.

| # | Question | Result |
|---|---|---|
| a | Does Resolve accept a hollow copy at all? | **Yes.** `ReplaceClip` to it returns True in under a second; length, timecode and resolution read as the original's |
| b | Is the frame the real frame? | **Yes.** The multicam item in the cut, at the fetched frame: the still is pixel-identical (6048x4032) to the still taken from the real original a minute earlier |
| c | Is the Camera Raw panel live? | **Yes, on the angle's clip.** In the angle timeline the panel shows Blackmagic RAW with the camera's own values read from the hollow copy (Gen 5, ISO 400, 5200 K, tint 17). Decode Using was set to Clip and Exposure to 1.50: the viewer and the still changed |
| d | And on the multicam item in the cut? | **The panel is greyed out there** (Resolve's own behaviour for a multicam), but it shows the angle clip's values, and **the change made in the angle timeline shows in the multicam** (the still changed) |
| e | Does the change stick? | **Yes.** Saved, project closed, reopened: same picture, Exposure still 1.50 |
| f | What does an empty frame look like? | The red **Media Offline** card, at once. No hang, no crash, and the fetched frame decodes again straight after |
| g | The file is absent when the project opens, then appears | **Not at once, and not after 10 s. After switching to another timeline and back, the clip is online.** While the original is absent Resolve shows the proxy, as today |
| h | Proxy handling (`perfProxyMediaMode`) with the proxy linked | **1, Prefer Proxies:** every frame plays from the proxy, fetched frame included; the hollow copy changes nothing the editor sees. **2, Prefer Camera Originals, and 0, Disable All Proxies:** a fetched frame is the raw picture; an empty frame is Media Offline, with **no** fall-back to the proxy |
| i | Write a second frame into the hollow copy while the project is open | **Refused** (`PermissionError`): Resolve holds the file open without write sharing. Renaming the file is allowed |
| j | So swap in a fuller hollow copy by rename, project open | Resolve does **not** read it: not at once, not after a timeline switch, a page switch or 20 s, and **not after `ReplaceClip` to the same path**. After the project is closed and reopened, the added frame shows |
| k | A frame that was looked at while empty | Stays Media Offline for the rest of the session even when the file later has it; a frame of the same file that was never looked at shows straight away after (j)'s reopen. Resolve caches the failure per frame |
| l | A render across fetched and empty frames | **The job fails** in both proxy modes: `Error decoding full resolution media for G011_10211743_C075.braw at 01:00:14;29. Please check that the file is accessible and has a valid codec.` It does not write offline frames |
| m | The trailing marker atom | Accepted (every hollow copy in the test carried it) |
| n | Which file frame is under the playhead, plain clip | `GetLeftOffset() + (playhead - GetStart())`. Measured on an item where `GetSourceStartFrame()` said 4146 and `GetLeftOffset()` said 4147: a hollow copy holding only frame 4184 showed at exactly `4147 + 37`. **`GetSourceStartFrame()` was one frame low** |
| o | Which file frame is under the playhead, multicam | Worked first time: multicam item's offset + playhead gives the frame inside the multicam; the angle timeline has the same timebase (it starts at 01:00:00;00), so the same frame number indexes the angle timeline; the item there gives the clip and its frame |

### 2.5 What the spike changed in the design

1. **Multicams are in the first build** (D8 is settled). For a multicam built
   by the Multicam Pipeline, whose angles are timelines, the menu script can
   resolve the playhead to the angle's clip and frame with calls it already
   has. The raw settings are changed in the angle timeline, so the answer to
   the editor names that timeline and timecode, and a second menu item takes
   them there (section 3.2).
2. **Proxy handling is the switch.** Prefer Proxies to cut, Prefer Camera
   Originals to see grading frames. No per-clip state for the editor to manage.
3. **Fetch generously the first time.** More frames for a clip that already
   has a hollow copy cost a project reopen (rows i, j, k), so the first request
   brings the playhead frame with its neighbours and the first and middle
   frames of the clip's use (D1, D2), not one bare frame.
4. **Frame arithmetic uses `GetLeftOffset()`**, never `GetSourceStartFrame()`
   (row n).

Also settled: the render risk (row l). A render from a hollow clip stops with
an error that names the clip, so the worst case is a failed job, not a
deliverable with offline frames in it.

### 2.6 The other cameras (2026-11-22, for the second build, D7)

Scripts: `tools/spikes/grading_frames/qt_sweep.py` (layout sweep) and
`make_hollow_qt.py` (a hollow copy of any QuickTime or MP4 file).

**What is on the NAS besides BRAW.** 18,020 video files under
`P:\Projects\2025` and `2026` outside `Proxy/`: 17,326 `.mp4`, 502 `.mov`,
113 `.mxf`, 77 `.mkv`, 2 `.avi`. About 8,500 of the `.mp4` are downloaded
programmes in YouTube folders, not camera files. The camera originals, from a
sweep of 166 files:

| Camera | Files (about) | Layout | One second of picture |
|---|---|---|---|
| **Sony XAVC S** (`fx3_...`, and the same files renamed: `C####`, `party...`, `energy_...`) | 5,000 | `ftyp, uuid, free, mdat, moov, meta`: the index is near the end, followed by a `meta` atom. H.264, long-GOP with B-frames stored out of order. A group of pictures is one second: 24 to 30 frames, 60 at 60p, 120 at 120p. 12 to 15 frames per chunk. PCM sound and a camera-metadata track | 13 to 22 MB at 4K; 35 MB at 4K 120p |
| **DJI drone** | 190 | index at the end; H.264 or HEVC, group of 30, no reordering | 12 to 14 MB at 4K |
| **Nikon Z** | 93 | index at the START; HEVC, group of 30 | 7 MB at 1080p60 |
| **iPhone** | few | index at the end; H.264, group of about 30 | 9 MB at 4K |
| **ProRes** (`.mov`: renders of BRAW clips, stock transitions) | 150 | every frame stands alone, like BRAW; the index is at the end on some and at the start on others | one FRAME is 0.5 to 43 MB (43 MB is 8K ProRes 4444 XQ) |
| MXF | 113 | not looked at: a different container altogether | |

One Sony file in the sample has no index at all (an interrupted recording).
A hollow copy cannot be made of it and Resolve cannot open it either.

**How a hollow copy is made for these.** Everything that is not picture or
sound is kept (every atom whole except the inside of `mdat`, wherever the
index sits), plus the first group of pictures, plus, for each frame asked for,
the whole group it belongs to. "Frame N" is counted as an editor counts, in
display order, so the stored sample is found through the composition offsets
(`ctts`); when that sample is shown before its own keyframe (an open group)
the group before is kept too. **The unit of fetch is a group, not a frame.**

**File level, in ffmpeg** (the wanted frame decoded from the hollow copy and
from the original, pixels hashed):

| File | Hollow copy | Wanted frame | A frame that was not kept |
|---|---|---|---|
| Sony 4K 29.97 (`C6192.MP4`, 0.47 GB) | 36.5 MB | identical | decode error |
| Sony 4K 120p (`fx3_20261021_2780.MP4`, 7.85 GB) | 73.5 MB (two groups) | identical (three frames tried) | decode error |
| DJI H.264 4K (2.48 GB) | 23.4 MB | identical | decode error |
| DJI HEVC | 7.9 MB | identical | decode error |
| Nikon Z HEVC (index first) | 10.6 MB | identical | decode error |
| iPhone 4K | 8.7 MB | identical | decode error |
| ProRes 422 8K (0.63 GB) | 25 MB a frame | identical, once its neighbours were kept (ffmpeg reads one frame ahead) | decode error |

**In Resolve 21.0.1**, in the scratch project, each clip alone on a timeline,
the project closed and reopened between the hollow stills and the stills from
the real original so that Resolve's frame cache could not answer for either:

| Clip | Kept frames | Empty frames | Render across empty frames |
|---|---|---|---|
| Sony 4K 120p, H.264 High 4:2:2 | **pixel-identical** to the real original (three frames) | Media Offline | **fails**, naming the clip and timecode; a render inside the kept group completes |
| DJI H.264 4K | pixel-identical (two frames) | Media Offline | fails the same way |
| ProRes 422 8K | pixel-identical (two frames) | Media Offline | fails the same way |

Not tried in Resolve, file level only: Nikon, iPhone, DJI HEVC, and the
commoner Sony 4:2:0 29.97 files.

**Two mistakes made on the way, both worth keeping as rules for any further
test:**

- **Resolve caches a frame it has shown for the rest of the session**, so a
  still taken "from the hollow copy" just after a still from the real original
  proves nothing. Reopen the project in between. (The BRAW results in section
  2.4 do not depend on this: the raw exposure change, the frame that was never
  viewed, and the one-frame-only clip of row n could not have come from a
  cache.)
- **Check that the clip is the one on screen.** The first Sony run looked
  wrong (empty frames showing a picture, a render that completed) because a
  clip on a track above was covering it.

**What it means for the second build:**

- The method carries over unchanged, and Resolve treats these hollow copies
  exactly as it treats BRAW ones: right picture, Media Offline elsewhere, a
  loud render failure.
- The parser must take the index wherever it is (end, start, or followed by
  `meta`), 32-bit or 64-bit offsets, several frames per chunk, and display
  order through `ctts`. `make_hollow_qt.py` does all of that in 150 lines.
- **Cost is per group, so it is several times BRAW's.** With D1 (playhead,
  first and middle) a Sony 4K clip is three one-second groups, about 55 to 65
  MB; a 120p clip about 110 MB. D2's neighbours come free, they are in the
  group.
- **Frame arithmetic across frame rates**: a 119.88 fps clip on a 29.97
  timeline is played four source frames to one. `GetSourceStartFrame()` counts
  source frames and `GetLeftOffset()` counts timeline frames (19038 against
  4759 on the same item), so the rule of section 3.3 becomes
  `round((GetLeftOffset() + playhead - GetStart()) * clip fps / timeline fps)`.
  On a long-GOP file the group absorbs a small error; on BRAW and ProRes the
  neighbours do.
- There are no raw controls on any of these. What the editor gets is the true
  original frame under the grade: real noise, real sharpness, the full bit
  depth, where the proxy is a small 8-bit H.264.
- MXF stays out until someone needs it.

---

## 3. The design

### 3.1 The choice of method

| Method | Verdict | Why |
|---|---|---|
| **Hollow copy at the original's path** | **Recommended** | No relink, no second clip, no settings to carry across: the project already points at this path, and Resolve keeps the clip's stored length and timecode (`docs/BROLL_PROXY_TIERS_PLAN.md` section 3: "Resolve does not re-read a file that changed under a clip"), which here are the real original's, so they are right. Pure byte ranges: no decoding, no Blackmagic software on the server, nothing to license. Adding frames and upgrading to the whole original are the same operation continued. |
| A separate one-frame `.braw` made by Blackmagic's trim (`CreateJobTrim` is in the decoder's interface) | Rejected; the hollow copy passed its spike | It is a different file, so it is a different clip. The raw settings would then have to be moved onto the real clip, and Resolve's scripting has no call for raw settings (to confirm before relying on this row). It also needs Blackmagic's library running on a machine that holds the original, and a licence to ship it. Put at the original's path instead, the project would ask a one-frame file for frame 495. |
| Swap P: to the server | Exists; not the answer | Whole drive, Windows only, needs a NAS login from the remote computer, and its first real use failed (RSV-148). It stays as it is. |
| A link at the clip's path pointing at the NAS share | Rejected | Remote editors reach the NAS by SFTP, not as a mounted share; this is RSV-148's missing login again, plus a Windows privilege to create links. |
| Files that fetch themselves when read (Windows Cloud Files, macOS File Provider) | Later, perhaps | The ideal shape: Resolve asks for a frame and it arrives. It is one driver-level integration per operating system. The hollow copy is the same idea with the fetching done ahead by request, and would become its storage format. |
| The whole original | Built | The upgrade path, not the answer to "one frame". |

### 3.2 What the editor does

Four menu items beside the existing five, written the same way (Lua, no HTTP,
a request file; `resolve_menu/_originals_common.lua`). As built they are
installed under `Scripts/Utility/CC Sync`, not `Scripts/Edit/CC Sync` where the
originals items are: Resolve lists a script only on the page its folder names,
and a colourist is on the Color page (section 10.3, item 9).

- **Bring grading frame - clip under the playhead**: the exact frame showing,
  whether the item is a plain clip or a multicam.
- **Bring grading frames - timeline clips between In and Out** (no marks: the
  whole timeline): frames for every clip in the range (D1 says which).
- **Bring grading frames - selected media pool clips**: the same, for clips
  chosen in the pool.
- **Go to grading frame**: for a multicam under the playhead, opens the angle
  timeline at the matching timecode, which is where the Camera Raw panel is
  live (section 2.4 rows c and d). It runs inside Resolve at the editor's
  click; the companion still never touches Resolve.

The tray answers in one balloon, for example: `Grading frame ready: G011_C075
at 17:46:52:10. Switch to another timeline and back to load it, and set
Playback > Proxy Handling to Prefer Camera Originals to see it.` For a
multicam it adds the angle timeline's name. No em dashes in any of this copy.

A request for a clip that already has a hollow copy answers differently:
`Added to G011_C075. Close and reopen the project to see the new frames.`

### 3.3 Which frame

- **Plain clip**: `item:GetLeftOffset() + (playhead - item:GetStart())`.
  `GetSourceStartFrame()` is NOT used: it was one frame low in the spike
  (section 2.4 row n; `music_worker.py:40` had already noticed it comes back
  "a hair under the integer").
- **Multicam** (a Multicam Pipeline multicam, whose angles are timelines):
  `m = item:GetLeftOffset() + (playhead - item:GetStart())` is the frame
  inside the multicam. The angle comes from the item's name (`<name> Multicam
  - Angle N`), the angle timeline is the one named `<name> — ANGLE N (...)`,
  and its frame `angle:GetStartFrame() + m` falls in an item there that gives
  the clip and, by the plain-clip rule, the frame. A multicam the script
  cannot resolve this way (made by hand from clips, a renamed angle timeline)
  is refused with a sentence that says to select the angle's clip in the media
  pool instead.
- When the clip's frame rate differs from the timeline's, or the clip is
  retimed, the mapping is not exact: the script says so in the request. The
  companion fetches one frame either side in every case (D2). A frame outside
  the clip is refused with a sentence, never clamped silently.

### 3.4 The request, and the fetch

- **Request file**: `~/.ccsync/requests/frames/<unix_ms>-<random>.json`, the
  selective-originals contract (`docs/SELECTIVE_ORIGINALS.md` 12.2) plus, per
  clip, `frames: [<index>, ...]`, `clip_fps`, `timeline_fps`, `exact: bool`.
  Same validation, same one-hour expiry, same inbox poller pattern
  (`originals_requests.py`), and CR-68 holds: nothing here calls Resolve.
- **Where the bytes come from**: the editor's own rclone remote, through the
  same down route, tuning and transport flags as `originals_lane`
  (`build_originals_command`, `rclone_lane.down_route`), so a tunnel route
  applies here too. The dashboard is not in the byte path. Per clip:
  1. `rclone lsjson` the file: its size and time.
  2. read the first 64 KB: the headers, the timecode sample, the first
     frame's header. The headers give the index's position.
  3. read from the index to the end.
  4. parse the index in the companion (standard library only; about 150 lines;
     `field_mode.py` already reads this box for its copy check) to get each
     wanted frame's offset and length.
  5. read the first frame and each wanted frame.
  A file under 64 MB is fetched whole instead. That covers the `_S00n` stills.
- **Building the file**: written under a temporary name in the same folder
  (sparse flag set first; on Windows by `DeviceIoControl`, never `fsutil`,
  never `truncate()`), each range checked for length and each frame for its
  `bmdf` start, the marker appended, then one atomic rename into place. Resolve
  never sees a half-built hollow copy. **Adding frames to an existing hollow
  copy is the same build again**, never a write in place: Resolve holds the
  file open without write sharing (section 2.4 row i). The new file is built
  from the old one's filled ranges plus the new frames, the old one is renamed
  aside (allowed while open) and removed when Resolve lets go, and the new one
  is renamed into place. Resolve reads it at the next project open.
- **Refusals, each one a sentence naming the cause**: not a `.braw` (D7, first build); a
  layout the parser does not recognise (index not last, more than one frame
  per chunk); the real original is already here; the project is not ticked on
  this computer or is upload-only; the drive cannot hold sparse files (D3);
  the tree is not mounted (`broll_fetch.fetch_refusal`'s questions); a sync
  halt.
- **Cost**: about 6 MB and five short reads for the first frame of a clip,
  about 3 MB and two reads for each further frame. A 300-clip timeline at two
  frames a clip is about 2 GB. If the per-read connection cost makes a batch
  slow (item 2 of section 6), the batch moves to one long-lived `rclone serve http
  --read-only` on loopback with ranged GETs. That is a transport swap behind
  one function, decided by the measurement, not now.
- **Not a lane.** Seconds long, megabytes: no LaneStatus, no power guard, off
  the sequencer's rotation entirely (the CR-347 lesson), one worker thread, two
  clips at a time. A batch shows one tray line while it runs.

### 3.5 Upgrading and removing

- **Bring originals on a clip that has a hollow copy** must work. Today
  `originals_lane.plan_project` leaves a local file of a different size alone
  as "the editor's own" (`differs_here`), and the copy is `--ignore-existing`,
  so a hollow copy would block the real download for ever. The plan: a file
  the hollow test (section 4) recognises is treated as absent, moved aside,
  and removed once the real file has landed and matches the NAS size. By
  section 2.4 row j the editor then reopens the project to get the whole clip;
  the balloon says so. No `replace_clip` is needed or useful: the clip's
  stored length and timecode were always the real ones.
- **Removing**: Settings > THIS COMPUTER gets a line, `Grading frames: 12
  clips` and `[ REMOVE GRADING FRAMES ]`. Hollow copies cost almost no disk,
  so nothing expires by itself (D6).
- **The NAS file moved or changed**: a `commands.file_moves` for a path that is
  hollow here drops the hollow copy instead of moving it. A hollow copy whose
  NAS size or time no longer matches the ledger is stale and is dropped at the
  next request for that clip.
- Deleting a hollow copy is the one delete in this feature. It happens only
  when all three signs of section 4 agree. Any doubt keeps the file and says
  so.

---

## 4. A hollow copy must never count as the footage

This is the main risk. A file with the original's name, at the original's
path, almost exactly the original's length, that holds one frame. Three
independent signs mark it, so that no single lost file or missed code path
turns it into "a copy":

1. **The ledger**: `~/.ccsync/state/grading_frames.json` (local path, NAS size
   and time at fetch, frames held, when). The pattern is the b-roll stand-in
   ledger (`broll_standins.py`), including its lesson that an entry must be
   falsifiable against the file.
2. **The file says so itself**: the trailing `free` atom with `{"ccsync":
   "hollow", ...}`, readable from the last few hundred bytes by any tool, and
   it makes the length differ from the original's, so no name-and-size
   comparison anywhere matches it to the real file.
3. **The filesystem says so**: allocated size far below length (Windows: the
   sparse attribute in `st_file_attributes`, plus `GetCompressedFileSizeW`;
   macOS: `st_blocks`). This needs no ledger and no read, so every walk the
   companion already does can apply it for free. It also catches cloud-drive
   placeholder files, which have the same problem today.

One predicate, `hollow.is_hollow(path, stat)`, and every reader below asks it:

| Reader | Without the predicate | With it |
|---|---|---|
| **Lane A** (`copy --ignore-existing`, up) | harmless while the NAS has the file; but if the NAS copy is ever moved or lost by hand, lane A re-uploads "the editor's copy" (`docs/SELECTIVE_ORIGINALS.md` 4.3), which would put a 3 GB file of zeros on the NAS under the original's name | excluded on every run through `extra_excludes_fn` (the hook `file_moves` already uses, `rclone_lane.py:3260`), fed by the ledger AND by the walk's filesystem test |
| **Local manifest** (`manifest.scan_local_manifest`) | counts it as an original this computer holds, at its full length; the dashboard then believes this machine has the clip (file moves follow it, and a size that differs from the NAS can read as an upload owed for ever) | skipped, in both the rollups and the per-file lists |
| **Field backup and the footage ledger** (`field_mode.row_is_this_file`, `ledger_scan.py`) | the length differs, so the size test already fails; the first and last MiB and the index really are the original's, which is exactly what that check samples | refused outright as a copy, before any comparison. **A camera card must never be judged safe to wipe on the strength of a hollow copy** |
| **Bring originals** | blocked for ever by `differs_here` | treated as absent, then replaced (section 3.5) |
| **Remove from this machine** (`app.removal_blockers`) | its lane A dry run lists nothing, fine | unchanged; hollow copies are listed separately |
| **Proxy generation** (`proxy_scan`, and the folders handed to Blackmagic Proxy Generator by `bpg.py`) | would try to make a proxy from it on a machine with proxy generation on | skipped, and never a reason to add a folder to the generator's watch list |
| Lane B, lane C | never see it: lane B's filter is Proxy-only, Syncthing ignores video on both ends | unchanged |

Also in the build: a test per reader that plants a hollow copy and asserts the
right answer, and one cross-cutting test that fails when a new caller of
`VIDEO_EXTS` appears that does not go through the predicate, in the manner of
`test_broll_standins.py`.

**Render.** Settled by the spike (section 2.4 row l): Resolve fails a render
job that reaches an empty frame and names the clip and timecode, in either
proxy mode. A hollow copy cannot put offline frames into a deliverable. The
Settings line still says that this computer cannot render the final picture
from these clips, so the failed job is not a surprise.

---

## 5. What is in and out of the first build

**In:** `.braw` clips, plain and inside Multicam Pipeline multicams; Windows
(NTFS) and macOS (APFS, once item 1 of section 6 passes); the four menu items;
the hollow copy, ledger, predicate and every reader in section 4; upgrade by
Bring originals; the Settings line and remove button; companion-only, so no
dashboard deploy and no schema change.

**Out, for later:**

- The dashboard listing who holds grading frames, and a report key for it. A
  new report key needs a `telemetry_fields` row and the dashboard deployed
  first; it earns its place once the feature is in use (D4).
- Other originals. The method is not specific to BRAW: any QuickTime original
  whose frames stand alone (ProRes) works the same way, and long-GOP camera
  files need the frames back to the previous keyframe. But raw settings exist
  only on raw footage, which here is BRAW. The owner wants Sony and ProRes
  originals in the second build all the same, to check a true frame of any
  clip (D7).
- Multicams not built by the Multicam Pipeline (angles that are clips, not
  timelines): the media-pool route covers them meanwhile.
- Fetch-on-read (section 3.1).

---

## 6. What is still untested

The Windows spike is done (section 2.4). These are left, none of them a
reason to wait with phases 1 and 2:

| # | Question | If the answer is bad |
|---|---|---|
| 1 | The same on one Mac: a sparse file on APFS, the Mapped Mount path, and rows a, b, c, g of section 2.4 | macOS waits for a second build |
| 2 | On Ruskin's computer: time the five reads for one clip, plain route and tunnel route; and the filesystem of each remote computer's sync drive | batch transport (section 3.4); D3 |
| 3 | The clip's own sound. With a hollow copy in place and Prefer Proxies on, does the BRAW's sound still play from the proxy? (Interviews take their sound from the recorder's WAV angle, so this matters for b-roll, not for multicams.) | fetch the clip's sound as well (24-bit: about 9 MB a minute for each channel), or say so in the balloon |
| 4 | Is there any way short of reopening the project to make Resolve read a fuller hollow copy, or forget a cached Media Offline frame? (Not found: timeline switch, page switch, waiting, `ReplaceClip` to the same path.) | none needed; the design already assumes a reopen |
| 5 | The raw change seen on the base rig against the REAL original. In the spike the scratch clip pointed at the hollow copy's scratch path, so this was not observed directly; it follows from the settings being stored on the clip in the shared project (row e) | the feature loses its point; check it in the first real use, before relying on it |
| 6 | A 30 fps clip on a 24 or 25 fps timeline, and a retimed clip: is the neighbour-frame margin of D2 enough? | widen the margin for those cases |
| 7 | A real remote machine end to end: the original was never on that computer, the proxy is linked, the hollow copy arrives at the path the project already points at (the spike relinked a scratch clip instead) | row g says it works; this is the confirmation |

The helpers used for the Resolve half (`rs.py` the guarded connection,
`common.py` the still-and-hash routine, `ui.py` a window capture and posted
click that never moves the real mouse) are in
`tools/spikes/grading_frames/resolve/`. The scratch project was left in the
library for inspection; it can be deleted.

---

## 7. Build plan

| Phase | What | Where | Ships as |
|---|---|---|---|
| 0 | The spike. DONE 2026-11-22 on Windows (section 2); section 6 lists what is left | no code | nothing |
| 1 | `hollow.py`: the index parser, the sparse writer (Windows and macOS), the marker, the ledger, `is_hollow`. Pure and fully unit-tested against fixture files built in the test (no camera footage in the repo) | companion | not yet |
| 2 | Every reader in section 4 asks the predicate, each with its planted-file test. **This phase ships before any hollow copy can exist**, so a build that can create one is never older than a build that knows what one is | companion: `rclone_lane`, `manifest`, `field_mode`, `ledger_scan`, `originals_lane`, `proxy_scan` | companion release A |
| 3 | The fetch (`rclone cat` ranges through the down route), the request inbox, the playhead menu item for plain clips AND multicams, `Go to grading frame`, the balloon, the Settings line and remove button | companion + `resolve_menu/` | companion release B, on everywhere (D5), published only after release A is on every machine |
| 4 | The timeline-range and media-pool menu items; the batch transport if item 2 of section 6 says so | companion | release B or C |
| 5 | Second build: Sony, DJI and ProRes originals (D7; spike passed, section 2.6), then Nikon and iPhone after a Resolve check each. The generic parser of `make_hollow_qt.py` replaces the BRAW-only one | companion | companion release |
| 6 | Later: dashboard listing and report key; multicams with clip angles | both | separate |

Tests go in the module's own test file (`CLAUDE.md`, 2026-11-10 rule) and
must pass under `-n auto`: no fixed ports, no shared paths under `~/.ccsync`.
Sparse-file tests skip, loudly, on a filesystem that cannot do them.

---

## 8. Owner decisions (2026-11-22)

The owner answered every question the same evening. These are the build
contract.

| | Question | Decision |
|---|---|---|
| D1 | Which frames of each clip come with a request? | **The playhead frame (when there is one), plus the first and middle frames of the clip's use on the timeline.** About 30 MB a clip with D2. |
| D2 | One frame either side of every frame fetched? | **Yes, always.** |
| D3 | A sync drive that cannot hold sparse files (exFAT, FAT32) | **Refuse, with a sentence naming the drive's format.** Nothing large is ever written by surprise. |
| D4 | Show grading frames on the dashboard? | **Not in the first build.** Each computer shows its own count in Settings; companion update only. |
| D5 | Feature flag? | **None: on for everyone at once**, like Bring originals (its D8). This was not the recommended answer, and it raises the stakes on section 4: phase 2 (every reader knows what a hollow copy is) must be on the whole fleet, at every customer, before the build that can create one is published. The build plan's two-release order is how that is enforced. |
| D6 | Do hollow copies expire? | **Never automatically.** They go when the real original arrives or the editor presses Remove grading frames. |
| D7 | Which files? | **`.braw` in the first build; Sony (XAVC) and ProRes originals in the second**, so a colourist can check a true frame of any clip. Tested the same evening at the owner's request (section 2.6): Sony, DJI and ProRes hollow copies work in Resolve; Nikon and iPhone pass at file level. Those have no raw controls, and a frame costs a whole one-second group (about 20 MB at 4K). |
| D8 | Multicam clips | **In the first build** (the owner, 2026-11-22: "the clips mostly needing grading will be inside a multicam"; and the spike, section 2.4 rows c, d, o). |

---

## 9. Risks

- **A hollow copy taken for footage** (section 4). Mitigated by three
  independent signs, phase 2 shipping first, and a test per reader. This is
  now the largest risk in the feature.
- **The reopen.** A second request for the same clip shows only after the
  project is reopened, and a frame looked at while empty stays Media Offline
  until then. Mitigated by fetching generously (D1, D2) and by the balloon
  saying so; it remains the roughest edge for the editor.
- **An editor who cuts in "Prefer Camera Originals"** sees Media Offline on
  every unfetched frame of a hollowed clip, where an absent original would
  have shown the proxy. The balloon names the setting, and `[ REMOVE GRADING
  FRAMES ]` puts things back.
- **Multicam name matching.** The angle timeline is found by the Multicam
  Pipeline's naming. A renamed timeline breaks the match; it is refused with a
  sentence, never guessed.
- **Sound, a Mac, and a real remote machine** are untested (section 6).
- **An unusual `.braw`**: the parser refuses anything it does not recognise
  and says so; 157 of 157 sampled clips fit, across three codec variants, but
  every camera body in the fleet should be in the phase 1 fixtures' shapes.
- **The decoder's needs change** in a later Resolve (it needed the first
  frame's header in 21.0.1). The hollow copy always carries the whole first
  frame, and `tools/spikes/grading_frames/braw_probe.py` re-checks any Resolve
  version in a minute.


---

## 10. What was built (2026-11-22)

Built by one builder in two stages, each stage then read line by line against
this plan and tried on real footage.

### 10.1 Two releases, in this order

| Release | Version | Where | Holds | State it must reach first |
|---|---|---|---|---|
| **A** (phases 1 and 2) | companion **0.9.98** | `main` | `hollow.py` and every reader of section 4. It can recognise a hollow copy and cannot make one: a test in that state fails if anything outside the tests calls the writer | on EVERY machine of every fleet |
| **B** (phases 3 and 4) | companion **0.9.99** | branch `grading-frames-release-b`, one commit on top of A | `grading_frames.py` (the fetch, the request inbox, the balloons), the four menu items, the tray line, the Settings line and button | merged and published only after A is everywhere |

**Why B is on a branch and not on `main`.** `tools/publish_latest.py` publishes
the newest green build of `main`, whatever it holds. With B on `main`, the next
release of anything at all (a hotfix, an unrelated feature) would carry the
build that can create hollow copies out to machines that do not yet know what
one is. The tool refuses a commit that is not an ancestor of `origin/main`, so
B on its branch cannot be published by accident.

**To release B, later:** check that every machine at every site reports
companion 0.9.98 or newer (the FLEET page, and each customer's), then merge the
branch into `main` (rebasing it first if `main` has moved; if another release
has taken 0.9.99 meanwhile, give B the next free version in `config.py` and
`pyproject.toml`), let CI go green, and publish by pathway B of
`docs/RELEASE_PATHWAYS.md`. Between the two, only `app.py`, `build.spec`,
`resolve_menu_install.py`, `settings_window.py`, `tray.py`, one test in
`test_hollow.py` and one sentence in `hollow.py` differ, plus B's new files.
**Nothing in the code enforces the order.** It is a publishing rule (D5), and
the person who publishes B has to have looked at the fleet's versions first.

### 10.2 Where things are

| Piece | File |
|---|---|
| Index parser, sparse writer, marker, ledger, the two predicates (`is_hollow`: any sign; `may_delete`: all three), lane A's exclusion walk | `companion/src/ccsync_companion/hollow.py` |
| The readers | `app.py` (`_lane_a_extra_excludes`), `sync/rclone_lane.py` (`_express_partition`), `manifest.py`, `ledger_scan.py`, `field_mode.py` (`row_is_this_file`, `quick_compare`, `LedgerView._present`), `sync/originals_lane.py`, `proxy_scan.py`, `file_moves.py` |
| The fetch, the inbox `~/.ccsync/requests/frames/`, the frame rule, balloons, Settings strings | `companion/src/ccsync_companion/grading_frames.py` |
| The menu scripts | `resolve_menu/_frames_common.lua` and four entry scripts; installed by `resolve_menu_install.py` |
| Tests | `tests/test_hollow.py`, `tests/test_grading_frames.py`, `tests/hollow_fixtures.py`, and a planted-file test in each reader's own test file |

The byte path is `rclone lsjson`, then `rclone cat --offset N --count M`
through `rclone_lane.down_route` with Bring originals' flags. Reads less than
1 MiB apart are joined, so a playhead request is about five reads.

### 10.3 What the build and the review changed in the plan

1. **Lane A has two doors, and both ask.** Section 4 names the
   `extra_excludes_fn` hook; an express upload cannot carry a filter file, so
   `_express_partition` checks each file itself.
2. **Lane A reads the marker too.** A hollow copy that was COPIED by hand (a
   sync tree moved to a new drive, a project folder duplicated) arrives with
   its holes filled in, at a path the ledger has never heard of: two signs
   gone at once, and what is left is a clip-sized run of zeros under the
   original's name. Lane A's walk now asks the marker of every original, once
   per file (the verdict is remembered by path, size and time). The manifest
   and the proxy scan still ask only the two cheap signs.
3. **The sparse ATTRIBUTE is not a sign.** rclone's own multi-thread downloads
   leave a WHOLE original marked sparse on Windows (checked with rclone
   1.74.4). The sign is "less than half the length is on the disk", measured.
   On a filesystem that reports no blocks at all, the answer is "cannot tell",
   never "hollow".
4. **A hollow copy always shows the filesystem sign when it is made.** If what
   would be written is more than a third of the clip (a very short clip), the
   whole original comes down instead, as section 3.4 already does for a file
   under 64 MB. Otherwise the copy could never be removed (a delete needs all
   three signs).
5. **A file only the filesystem calls hollow is not ours.** A cloud-drive
   placeholder is kept out of lane A and the manifest (and named in the log
   once per walk), but it is never renamed, deleted or downloaded over, and a
   server move treats it as the editor's own file, as before.
6. **A folder holding a hollow copy is not handed to Blackmagic Proxy
   Generator**, even for a real BRAW beside it: the generator watches folders,
   not files. This cannot take back a folder it already watches. In practice
   only the base rig runs it, and the base rig holds real originals.
7. **A moved folder takes its hollow copies with it** (their ledger rows
   follow); a single moved file's hollow copy is dropped, as section 3.5 says;
   a folder going to a project this computer does not sync drops them first.
8. **A retimed clip is placed from its own source range.** Read off a live
   timeline: `GetProperty("Speed")` is nil on every item in Resolve 21.0.1, and
   on a slow-motion item the left-offset rule of section 3.3 pointed far
   outside the clip. The script now compares the item's source span with its
   timeline span; when they disagree the frame is `GetSourceStartFrame() +
   (playhead - start) * source span / timeline span`, marked inexact. A clip
   at normal speed still uses `GetLeftOffset()` only. **An inexact frame gets
   two neighbours either side, not one** (section 6 item 6's own fallback):
   the 119.88 fps clip of section 2.6 worked out two frames from where
   Resolve's own source start puts it.
9. **The four items are under `Scripts/Utility/CC Sync`**, so they are in the
   menu on every page. Under `Edit` they would have been missing on the Color
   page. The originals items did not move.
10. **macOS refuses for now**, in one sentence, behind one constant
    (`grading_frames.FETCH_ENABLED_ON_MACOS`), until item 1 of section 6 has
    been run. Every reader of section 4 is live on a Mac.
11. **The balloon's timecode is the timeline's** at the playhead, not the
    clip's own. The multicam balloon adds the angle timeline's name and
    timecode.
12. **"Is the server's file still the one the frames came from"** compares the
    size, then the modification time as a time (two seconds or more apart),
    never as text: two download routes can print the same instant differently.

### 10.4 What was checked, and how

- **On a real clip, through the real rclone binary.** `ClipFetch` read
  `A007_08090854_C137.braw` (3.05 GB) off the NAS share read-only (rclone's
  local backend standing in for the editor's remote) and built the hollow
  copy in 1.0 s: 31 MB on the disk, nine frames plus frame 0. Blackmagic's
  decoder gives frame 495 the same picture hash this plan records for the
  real original (`839241b3...`), fails cleanly on an empty frame, and decodes
  a frame added by a second request. `Remove grading frames` then removed it.
- **No real original is mistaken for a hollow copy.** The filesystem sign over
  12,000 video files on the NAS share: none flagged, 4.6 s.
- **The shipped menu script against the live Resolve's own objects**, read
  only (every non-getter refused, the playhead and current timeline
  pretended, nothing in Resolve changed): the multicam `Talk UA 10-21 - war
  stories Multicam - Angle 1` resolved to `G011_10211743_C075.braw` frame 6544
  in the angle timeline, the same answer as worked out straight from the API;
  the item of section 2.4 row n gave 4184; the retimed item gave 5670,
  inexact. The request files it wrote pass the companion's own parser.
- **Tests.** The whole companion suite, in parallel, with a Lua runtime
  present so the menu scripts really ran: 9,386 passed. 32 failed, all in the
  b-roll and music ingest tests and all for one reason that is not this
  build: drive C: had about 10 GB free and those tests refuse below a 20 GB
  floor. Run them again once the drive has room.
- **The Lua tests skip on a machine with no Lua.** creator-1 has neither a
  `lua` binary nor `lupa`; without one, the frame arithmetic is not executed
  at all. They were run here with `lupa` installed outside the repo.

### 10.5 Not yet tried, on top of section 6

| # | What | Why it matters |
|---|---|---|
| 1 | A real click in Resolve: each of the four menu items from the Color page, on a plain clip and on a multicam, with the companion running | everything above drove the script from outside. Whether the items appear, and `Go to grading frame` (`SetCurrentTimeline`, `SetCurrentTimecode`), has only run against a stand-in |
| 1b | A Mac's disk and holes. The first CI run on GitHub's macOS runner (APFS, 2026-11-22) left every test clip FULLY allocated: holes of a few MB, and one of 8 MiB, were filled in. The suite now measures holes of 4, 32 and 128 MiB on every run and prints the result in the warnings summary (`HOLES ON ...`), and the writer refuses to place any copy that did not come out mostly holes. **The next run, on the released commit f07a2e9, read: `HOLES ON apfs (darwin): 4 MiB hole FILLED IN; 32 MiB hole KEPT (24576 of 33558529 bytes on disk); 128 MiB hole KEPT`.** So APFS keeps large holes and fills small ones: a real clip's holes are gigabytes, which is encouraging, but frames a few MB apart will cost the gap between them as well | if a Mac fills in large holes too, a grading frame there would cost the whole clip's size. Read that line in a macOS CI log before flipping `FETCH_ENABLED_ON_MACOS` |
| 2 | The fetch through a real editor's remote (SFTP, and the tunnel route) | only rclone's local backend was available on this rig (section 2.3) |
| 3 | Which frame Resolve really shows for a clip at another frame rate or a retimed clip | the wider margin is a guess from one measurement |
| 4 | What Blackmagic Proxy Generator does when it meets a hollow copy in a folder it already watches | item 6 of 10.3 only stops NEW folders |
| 5 | A request made while the companion is restarting | the request file is deleted when its work starts, so a crash mid-fetch loses it and the editor asks again |
