# B-roll proxy tiers: a better browser preview, an editing proxy, and "Send to Resolve" that downloads only a proxy

Written 2026-09-17 against HEAD `3643f7b`. Status: **phases 0-3 BUILT the
same evening (waves A `142e2cf`, B `7008e65`, phase 3 `11b81e1`), gated,
UNSHIPPED: no version bump, no KNOWN_BUGS entry yet, and the live checks
in §7 (a stand-in-born clip opened on a wired rig; the preview to
editing-proxy swap on a clip already in a timeline) still to run.** Phase 0
is the spike whose answer decided phase 3's shape (§3). Revised the same day after
[`BROLL_PROXY_TIERS_PLAN_AUDIT.md`](BROLL_PROXY_TIERS_PLAN_AUDIT.md): every
change the audit forced is marked **(audit Fn)** below, so the two documents
can be read against each other.

The owner's ask, sorted:

1. A remote editor who presses **Send to Resolve** on the b-roll page should
   download a **proxy**, never the full clip.
2. The clip in the Resolve project must still point at
   `P:\Assets\B-roll Archive\...`, the file on the NAS, **not** at a copy in a
   project folder. A wired rig that opens the same project then gets the full
   file with no relinking.
3. The browser previews are too low quality to judge a clip by. New clips
   should get a better one. **Existing previews stay as they are** (owner,
   2026-09-17): no re-encode sweep.
4. Two kinds of proxy per clip: a **browser preview** (what the page plays)
   and an **editing proxy** at the quality the fleet already uses for project
   footage. Send to Resolve should use the preview first, because it is small
   and arrives in seconds, then download the editing proxy in the background
   and swap it in.

Related: `BROLL_INGEST_PLAN.md` (how new clips reach the archive),
`LOOPBACK_API.md` (the 127.0.0.1:8899 contract), `broll/SPEC.md`,
`KNOWN_BUGS.md` R9 (10-bit previews), R10 (Resolve refusing a proxy whose
timecode does not match), R17 (ten refusals R10 does not explain, still
open), and the 2026-09-17 Reproductive Rights incident,
where Resolve refused seven proxies that were 1-18 frames short.

---

## 1. What happens today (verified 2026-09-17)

Two of the four complaints are already how the product behaves; two are real.

| Question | Today | Where |
|---|---|---|
| Is the downloaded clip copied into a project folder? | **No.** It is downloaded to `<local_root>/Assets/B-roll Archive/<rel>`, the same relative path as on the NAS, and nothing later moves it: `paths.classify_path` leaves an in-tree clip alone, so the fixer never sees it | `broll_server.py:242,353` (`BROLL_ARCHIVE_REL`, `contained_local_path`); `broll_fetch.py:252-277`; `paths.py:282-290` (audit F9) |
| What path does the Resolve project store? | **The canonical one**, `P:\Assets\B-roll Archive\...`, on Windows and macOS alike (a `ReplaceClip` after import); a wired rig resolves it to the NAS directly | `music_worker.py:128-151`; `canon.py:167-193`; `resolve_bridge.py:2989-2995,3250-3278` |
| What does a remote editor download? | **The archive's "top slot" file in full**: the one file beside `Proxy/` with the preview's stem, chosen live by `_insert_target`. If there is not exactly one, it falls back to the preview itself | `broll/web/app/routes_api.py:26-64,152` |
| What proxy gets linked in Resolve? | **The 540p browser preview**, `<dir>/Proxy/<stem>.mp4`, whenever the top slot was inserted. With "prefer proxies" on, the editor watches 540p. And it is linked AGAIN every 120 s: `app._relink_proxies_once` offers the first existing `Proxy/<stem>.mov`, `.mp4` to every in-tree clip whose proxy is not working (audit F1) | `resolve_bridge.py:2834-2878` (`_attach_adjacent_proxy`); `proxy_relink.py:304-350` (`plan_relinks`) |
| How good is the browser preview? | 540p max, `h264_nvenc -cq 34` or `libx264 -crf 30`, 8-bit, AAC 96k. Measured: 37-970 kbps, **1.9 MB per clip on average** for Creators_Club. The same spec lives in the companion as `ffmpeg_tools.preview_proxy_cmd` (`companion/.../ffmpeg_tools.py:698`) | `broll_index/ffmpeg_tools.py:188-270` |
| What does the index know about a clip's geometry? | `duration_s, fps, width, height, codec` and nothing else: **no frame count, no start timecode, no bitrate**. For a `source: proxies` share the probe is of the shoot's proxy, not the original (audit F3) | `broll/web/schema.sql`; `broll_index/ffmpeg_tools.py:124-160` (`probe_video`) |
| Does anything make an editing proxy for archive clips? | **No.** `proxy_gen` only scans `Projects/` | `proxy_scan.py:560-570` |

What the archive actually holds (measured on the NAS the same day):

| Group | Clips | Size | Top-slot file | Preview in `Proxy/` |
|---|---|---|---|---|
| `Creators_Club/` (ff3, ff4, mofa-disaster, Base Drone, 2026-08-18 ingest) | 5,031 | 194.5 GB (avg 39 MB) | **1080p HEVC or H.264, about 6.5-8.3 Mbps**: the shoot's own editor proxy, copied as-is by `build_archive.py:194-197,221-240`, **not** the camera original | 540p H.264, 9.7 GB |
| `Downloads/` (YouTube and other downloads) | 2,224 | 287.1 GB (avg 129 MB) | The downloaded original, mostly 1080p H.264 around 2 Mbps | 540p H.264, 63.2 GB |

So for **today's** archive, "download the full clip" already means
downloading a 1080p editing-weight file: an editing proxy at the fleet's own
spec (1080p, 7 Mbps) would be about the same size, and for most downloads it
would be bigger. The download-size complaint becomes real **going forward**:
drag-and-drop ingest uploads the true camera originals behind the preview
(`BROLL_INGEST_PLAN.md` step 7). The Johnny Harris camera files are the
example, at up to about 10 GB each.

Two consequences shape the plan:

* **"Edit-weight" is a property of a file, not of a folder.** A top slot at
  or below 1080p and below about 12 Mbps *is* its own editing proxy.
  Downloading it is correct, and making a second file would waste space.
* **For existing Creators_Club entries, the full file a wired rig sees is
  itself a 1080p editor proxy**, because the archive never held the camera
  originals. Pointing those entries at the real originals in `Projects/` is a
  separate question (§8, question 2) and not part of this plan.

---

## 2. The design in one paragraph

Every **new** archive clip gets three files beside each other:
`<dir>/<stem>.<ext>` (the original, unchanged),
`<dir>/Proxy/<stem>.mp4` (a **better browser preview**), and, when the
original is heavier than edit-weight, `<dir>/Proxy/<stem>.mov` (the
**editing proxy**, at the spec `proxy_gen` already uses for project footage).
On a remote machine, Send to Resolve downloads the preview **to the
original's own path as a stand-in** (spike verdict, §3: Resolve creates no
clip at a path it cannot open), imports it there, and inserts it. It then
downloads the editing proxy in the background and links it as the proxy. On a wired rig nothing
is downloaded; the clip is the original, with the editing proxy linked if one
exists. **Existing clips keep today's behaviour**, apart from one change: the
540p preview is no longer linked as the Resolve proxy for a clip whose full
file is already on disk (§6).

The two extensions do not need a new naming rule. The companion's proxy
convention already accepts `.mov` and `.mp4` and **prefers `.mov`**
(`proxy_relink.PROXY_EXTENSIONS = (".mov", ".mp4")`, `proxy_relink.py:58`),
and `proxy_gen` already writes `.mov` (`proxy_scan.GENERATED_EXT`). The
preview and the editing proxy can sit in the same `Proxy/` folder, and every
existing reader will pick the editing proxy when both are there. One reader
picks it only when the clip has no working proxy: the 120 s relink pass
never swaps a working `.mp4` for a `.mov` that has since arrived (§6, audit
F1).

---

## 3. Phase 0: the spike (decides phase 3)

**Verdict (base rig, 2026-09-17 evening, Resolve Studio 21.0.1, scratch
project "Proxy tiers spike 2026-09-17"):** Resolve will not create, repoint
or import a media-pool clip whose file it cannot open, by any route, and it
refuses silently.

| Method | Result on a path that does not exist here |
|---|---|
| 0 `ImportMedia(preview)` + `LinkFullResolutionMedia(ghost)` | `False`, clip unchanged. With an EXISTING full-res path the same call answers `True` and turns the preview into that clip's proxy (File Path becomes the full-res, Proxy becomes the preview), so the call works, it just validates the file |
| A `ImportTimelineFromFile(fcpxml, importSourceClips)` | `False`, no timeline, no clip, no dialog. The identical export with the real path imports fine (control), so it is the missing media that is refused, not the XML. Note: a hand-written 1.9 FCPXML is not accepted at all; only Resolve's own 1.10 export re-imports, and a `.drt` keeps its paths in an opaque `FieldsBlob`, so neither can be "edited to a ghost path" in the field |
| B `ImportMedia(preview)` + `ReplaceClip(ghost)` | `False`, clip unchanged |
| **C stand-in** (the preview's bytes at the original's own path and name) | **Works.** Imports as an ordinary clip at that path, with the stand-in's geometry (1920x1080, the preview's frame count and timecode) |

So phase 3 is method C, and "the project keeps pointing at
`P:\Assets\B-roll Archive\...`" holds because the stand-in sits at exactly
that path on the remote machine. Two consequences the design in §6 takes
on: a stand-in cannot be a `.braw`/`.r3d`/`.crm` (preview-only insert for
those, clip at the preview's path), and **the clip's stored geometry is the
stand-in's, and stays so**. Second half of the spike, same evening: the
stand-in's bytes were replaced by the real 6064x3424 ProRes original (1813
frames) and the project closed and reopened; Resolve still reported
1920x1080, 3255 frames and the stand-in's timecode, and still accepted the
preview as a proxy against those stored numbers. Resolve does not re-read
a file that changed under a clip. What does refresh it is
`MediaPoolItem.ReplaceClip(<the same path>)`: after that the clip read
6064x3424, 30 fps, 1813 frames, `12:09:12:22`. So a machine that holds the
real file must run one `replace_clip` on its own path for every
stand-in-born clip, through `resolve_bridge.replace_clip` (save point,
undo journal), before the clip is right there. For today's Creators_Club
entries this is moot: top slot and preview are both 1080p with the same
frame count and timecode, so the stand-in IS the geometry.

Also measured the same evening: the Johnny Harris previews re-encoded with
the tmcd-aware rule LINK (`cam-3-039.mov`, colon `14:59:25:29`, proxy
accepted, "1920x1080"); and R17's tenth clip is no longer refused: Resolve
reads the Sony rtmd colon `03:40:27:12` as drop-frame (`Start TC`
`03:40:27;12`) and the semicolon preview is attached, so the 2026-08-12
normalisation was right for Sony and the tmcd rule is right for Blackmagic.
Practical note for anyone scripting Resolve on this rig: a Resolve launched
with a monitor speaker unplugged raises an "Audio Output" message box on
every project load and page change, and the API returns `None` for
everything until it is dismissed; the spike ran under a UI Automation loop
that clicks OK.

The whole of goal 2 on a remote machine rests on one thing Resolve may not
allow: **a media-pool clip whose path is a file that does not exist on this
machine, with an online proxy linked to it.** Resolve plays such clips; the
fleet's project footage works exactly this way on every remote editor. But
those clips were imported on a wired rig, where the original existed.
`MediaPool.ImportMedia` needs the file to exist. Four candidate ways in, in
order of preference:

| | Method | Why it might work | What to measure |
|---|---|---|---|
| **0** | `ImportMedia(preview)`, then `MediaPoolItem.LinkFullResolutionMedia(<canonical original>)` (audit F5) | The API has exactly this call: "Links proxy media to full resolution media files specified via its path" (Resolve README line 324). Two calls, no interchange file, no throwaway timeline | Does it accept a full-res path that does not exist on this machine? What geometry does the clip report afterwards, and does a wired rig see the original at full resolution with no relink? |
| **A** | Write a one-clip FCPXML whose asset points at the canonical original path and carries its real geometry, frame rate, duration and start timecode; `MediaPool.ImportTimelineFromFile(xml, {"importSourceClips": True})`; keep the source clip, delete the throwaway timeline; `LinkProxyMedia(preview)` | Resolve creates **offline** media-pool clips from an interchange file whose media it cannot find, and takes the clip's metadata from the file, not from the media | Is the clip created offline at the exact path? Does `LinkProxyMedia` accept a proxy for an offline clip? Can it be moved into `B-Roll/Archive` and appended? Does a wired rig that opens the project see the original, at full resolution, with no relink? |
| **B** | `ImportMedia(preview)`, then `MediaPoolItem.ReplaceClip(<canonical original>)` | `ReplaceClip` already rewrites paths (`resolve_bridge.py:3250-3278`) | Does `ReplaceClip` accept a path that does not exist? Does the clip keep the preview's 1080p geometry, which would be wrong on a wired rig with a 4K original? |
| **C** | A **stand-in**: download the preview **to the original's local path**, import it, link it as its own proxy | Always works: the file exists | Only if A and B fail. It needs a ledger of stand-ins, `broll_fetch`'s `is_file` check taught to treat a stand-in as absent, and a render warning, because a remote render would silently use proxy quality. Same geometry question as B |

The spike runs on three machines: the base rig, one Windows remote editor
and leso's Mac (Mapped Mount). Every Resolve connection goes through the
CR-68 guard (`script_server.ready_to_connect`). Test clips:

* a 4K camera original with a 1080p proxy (the geometry case);
* a 23.976 fps clip and a 29.97 drop-frame clip (the timecode case);
* a clip already on a timeline when its proxy is swapped (the phase 3
  upgrade step);
* a proxy one frame short, to confirm the refusal is detected and reported
  instead of passing silently.

**Exit:** a written verdict at the top of this section and a
`resolve_bridge` function (or a note that there is none) that creates an
offline clip at a given canonical path with given metadata. If **no** method
works cleanly, the fallback is "remote editors download the editing proxy
**as** the clip" (the Johnny Harris cost stays small, but the path is wrong
for wired rigs). That breaks goal 2 and goes back to the owner before
anything is built.

---

## 4. Phase 1: a better browser preview, new clips only

**Spec** (one constant pair, shared by the indexer's `build_proxy` and the
companion's `ffmpeg_tools.preview_proxy_cmd`, which `broll_ingest_media`
and `proxy_gen`'s download tier both call). Today's "parity test"
(`companion/tests/test_ffmpeg_tools.py:235-262`) is a hand-copied list of
the indexer's flags and fails nothing when the indexer alone changes
(audit F8), so the first change of this phase is an **import-based** argv
parity test, the way `test_broll_ingest_media.py` already loads the indexer
module for the sprite and poster argv. Then the spec moves, on both sides,
in one commit:

| | Today | New |
|---|---|---|
| Max height | 540 | **1080** (never upscaled) |
| Video | `h264_nvenc -cq 34` / `libx264 -crf 30 veryfast` | `h264_nvenc -preset p5 -rc vbr -cq 25` / `libx264 -crf 23 -preset medium` |
| Pixel format | `yuv420p` | `yuv420p` (unchanged: browsers need 8-bit, R9) |
| Keyframes | encoder default | `-g` = 1 s of frames, so scrubbing on the page lands close to where the pointer is |
| Audio | AAC 96k | AAC 128k |
| Container | mp4, `+faststart`, source timecode | unchanged |

Expected size: roughly 3-5 Mbps at 1080p, so a 40 s clip goes from about
2 MB to about 20 MB. **Decision for the owner:** 1080p, or 720p at about
half that size (§8, question 1).

What changes:

* `broll/indexer/broll_index/ffmpeg_tools.py` `build_proxy`: the new spec,
  used for every clip indexed after the change.
* `companion/.../broll_ingest_media.py` `preview_proxy_cmd`: the same spec,
  kept identical by the parity test.
* `broll/web`: nothing. The player already supports Range requests
  (`app/media.py:60-102`); client share links (`CLIENT_FOLDERS.md`) get the
  better preview for free.
* **No sweep.** Existing previews are not re-encoded (owner, 2026-09-17).
  `broll/indexer/fix_10bit_proxies.py` stays unused.
* A preview must keep **every frame and the source timecode**, because it is
  also the first proxy Resolve links (phase 3). The encoder gets a
  post-encode check: count frames with `ffprobe -count_packets` and compare
  with the source. On a mismatch, retry once on the CPU, then fail the item
  visibly. This is the Reproductive Rights lesson: a short proxy is refused
  by Resolve and nothing tells the editor.
* That check is necessary, not sufficient (audit F6). KNOWN_BUGS **R17**
  records nine previews Resolve refused with identical `nb_frames`,
  duration and `pix_fmt` and no timecode on either side; what differed was
  the encoder run. R17's two experiments (re-encode one of the nine with the
  new spec and link it; remux the tenth with the colon form and link it)
  are this phase's first task, before the check is trusted.
* **The drop-frame rule changes** (audit F6). `dropframe_normalized`
  (indexer `ffmpeg_tools.py:102-123`, and the companion's identical copy at
  `ffmpeg_tools.py:388`) rewrites every colon-form 29.97/59.94 timecode to
  the semicolon form, because Sony bodies print drop-frame material with
  colons in an rtmd tag. A **tmcd track** carries its own drop-frame flag,
  and ffprobe prints that flag as the separator, so a colon from a tmcd
  track is a real non-drop timecode and the rewrite breaks the link.
  Verified 2026-09-17 on the Johnny Harris shoot: 231 of 377 proxies at
  29.97 NDF, `13:53:30:02` in the source, `13:53:30;02` in the preview,
  which is R17's tenth case exactly. New rule: **trust the separator a
  `tmcd` stream prints; normalise only a timecode that came from a
  format/data tag with no tmcd stream.** Both copies change together, with
  a parity test.

---

## 5. Phase 2: an editing proxy at ingest, new clips only

At ingest (`BROLL_INGEST_PLAN.md` step 6, "crunch per item"), after the
preview:

1. **Is the original edit-weight?** Yes when it is at most 1080 lines high,
   at most about 12 Mbps and in a codec Resolve decodes cheaply (H.264,
   HEVC or ProRes Proxy/LT). If so, no editing proxy is made: the original is
   its own editing proxy. This covers most downloaded footage and every
   existing Creators_Club top slot.
2. **Otherwise encode `Proxy/<stem>.mov`** with `proxy_gen`'s own-footage
   recipe, unchanged: 1080p max, HEVC Main10, 7 Mbps target, `hvc1` tag, AAC
   192k, source timecode (`ffmpeg_tools.py:551-664`). One function builds
   the argv for both callers, so project proxies and archive proxies can
   never drift apart.
3. **Verify** as in phase 1: frame count and timecode must match the
   original, or the item fails.
4. **BRAW, R3D, CRM**: ffmpeg cannot decode them. v1 records "editing proxy:
   none (needs Resolve)" and inserts use the preview only. Handing these to
   Blackmagic Proxy Generator, as projects already do (`bpg.py`), is a
   follow-up.
5. **Upload order** becomes stills, preview, editing proxy, then the
   original (`broll_upload.UploadQueue`). An editor can use a clip from the
   moment its editing proxy lands, long before a multi-GB original finishes.

**One schema change** (audit F3): `videos` gains `frames INTEGER`,
`start_tc TEXT` and `bitrate INTEGER` (a `broll/web/migrations` step plus
both `schema.sql` files), written by the indexer's `stage_probe` and by the
ingest crunch's probe alike. Without them the detail route would have to
ffprobe a multi-GB original on the NAS inside the container on every detail
view. Both proxies are still found by stem next to the original, the same
way `_insert_target` already finds the top slot. The detail API
(`routes_api.py:152`) gains an `insert` object that older pages ignore:

```json
"insert": {
  "share": "broll",
  "original_rel": "Creators_Club/CIA_City/cam_1/cam-1-001.mov",
  "preview_rel":  "Creators_Club/CIA_City/cam_1/Proxy/cam-1-001.mp4",
  "edit_proxy_rel": "Creators_Club/CIA_City/cam_1/Proxy/cam-1-001.mov",
  "original_is_edit_weight": false,
  "geometry": {"width": 6064, "height": 3424, "fps": "30/1",
               "frames": 1674, "start_tc": "12:05:55:26"}
}
```

`edit_proxy_rel` is `null` when there is none, `original_is_edit_weight` is
`null` when the index has no bitrate for the clip (a row indexed before this
change), and `geometry` is what phase 3's method A writes into the FCPXML.
The existing `insert_share` and `insert_rel_path` keep their meaning.

**How it reaches the companion** (audit F2): the companion never fetches
the detail API. The page POSTs `{share, rel_path, in_frame, out_frame,
mode}` today (`app.js:1691`), so the page now forwards the whole `insert`
object in that body, and the companion uses it **when present** and
otherwise derives both proxy paths by the stem convention
(`proxy_relink.expected_proxy_paths`) with no geometry. So an old page with
a new companion and a new page with an old companion both behave exactly as
today, and both skews are test cells (KNOWN_BUGS `comp-broll-music-4` is
the precedent for a page/companion skew biting).

---

## 6. Phase 3: Send to Resolve downloads a proxy

`broll_server.build_insert_response` (`broll_server.py:700-800`) chooses a
path by machine and by what exists:

| Machine | Original on disk? | Does | Result in Resolve |
|---|---|---|---|
| Wired (base rig, or `local_root` is the NAS) | yes | No download. Import the original. Link `edit_proxy_rel` if it exists, **otherwise link nothing** | Original, with the good proxy or none |
| Remote | yes (fetched before, or old behaviour) | As today, but stop linking the 540p preview | Unchanged apart from no 540p proxy |
| Remote | no, `original_is_edit_weight` | Download the top slot, as today | Unchanged |
| Remote | no, heavy original | **(1)** download `preview_rel` (seconds) **to the original's own local path** as a STAND-IN (spike method C: the bytes of the preview under the original's name; a `.braw`/`.r3d`/`.crm` original cannot have one and gets a preview-only insert at the preview's path) **(2)** record it in the stand-in ledger `~/.ccsync/state/broll_standins.json` **(3)** import it: the clip's File Path IS the canonical original path **(4)** insert, answer the page "inserted" **(5)** in the background, download `edit_proxy_rel` and link it as the proxy | The original's path, playing the stand-in at once, then the editing proxy as its proxy |
| Wired, or a remote that later holds the real file | yes, and the clip was born from a stand-in elsewhere | The relink pass runs `replace_clip(<same path>)` once for such a clip, which is the one call that makes Resolve re-read the file (spike, second half); then links the editing proxy if there is one. A clip is "born from a stand-in" when its stored `Frames`/`Resolution` disagree with the file at its path, or the ledger says so | The real original, right geometry, with the good proxy |

Details that matter:

* **The upgrade in step 5 reuses what exists.** It uses a `broll_fetch` job
  (same shutdown kill) and `LinkProxyMedia` through `resolve_bridge`'s save
  point and undo journal, the only sanctioned way to change the media pool.
  It is an **explicit** relink: the 120 s pass (`proxy_relink.plan_relinks`)
  skips every clip whose proxy is working, so it never swaps a playing
  preview for the `.mov` that has since arrived (audit F1). A pending
  upgrade is written to `~/.ccsync/state/broll_proxy_upgrades.json`, so a
  restart, or Resolve being closed when the download finishes, only delays
  it.
* **The relink pass changes with this** (audit F1). Today it offers the
  first existing `Proxy/<stem>.mov`, `.mp4` to any in-tree clip whose proxy
  is not working, every two minutes, so "link nothing" in the table above
  would last until the next pass and the 540p preview would come back on
  every machine. `plan_relinks` gets the same rule as the insert: offer an
  `.mp4` only when the clip's original is NOT on this machine; an `.mov`
  always.
* **Fetch concurrency** (audit F7). `broll_fetch.MAX_CONCURRENT_FETCHES` is
  2 and a third request answers `busy`. The background editing-proxy
  download does not count against that cap: it runs in its own single
  lane, so two inserts in a row never park the next Send to Resolve behind
  hundreds of MB of proxy.
* **The insert runs in a one-shot worker child with a timeout**
  (`music_server.call`, `music_worker.BROLL_INSERT_ACTION`). Steps 2-4 have
  to fit that budget, and the upgrade is its own child call.
* **If the editor closes the project first,** the upgrade runs the next time
  that project is open (the relink pass already runs on project open).
* **The page** shows "inserted" as soon as step 4 finishes, then "full-quality
  proxy downloading" with progress from the same poll it already runs. The
  tray shows the background download like any other fetch.
* **The popup and fixer must not nag** about an offline archive original that
  has a proxy. On a remote machine the stored path is `P:\...`, which is
  not under `local_root`, so `classify_path` returns **`MISSING`**
  (`paths.py:312-326`; the module docstring calls it the designed steady
  state on a remote rig), never a popup (audit F4). But since RES-12/RES-19
  the MISSING count and up to 50 paths go into every report as
  `sync_guard.resolve_health` (`app.py:4819`) and the tray's diagnostics
  line prints "N missing on disk" (`tray.py:2586`). An offline archive
  original with a working proxy must not be counted there: the watcher
  subtracts clips under the archive prefix whose proxy is working. A test
  pins MISSING for the classification and zero for the count.
* **The stand-in is a lie the companion must remember.** It sits at the
  original's path with the original's name, so `broll_fetch`'s
  `local_path.is_file()` would call the original present and never fetch
  it, lane A must never upload it, and a render on that machine would
  render 1080p H.264 under a 6K name. The ledger
  (`~/.ccsync/state/broll_standins.json`: local path, the original's real
  size/geometry from the `insert` object, when) is read by all three:
  `build_insert_response` treats a ledgered path as absent for the "is the
  original here" test, lane A's filter excludes ledgered paths, and the
  render warning names them. A stand-in is retired (file replaced, ledger
  entry dropped) only by a real download of the original, which is a
  follow-up: v1 never fetches a heavy original to a remote machine.
* **Disk:** downloaded proxies accumulate under
  `<local_root>/Assets/B-roll Archive/**/Proxy/`, which no sync lane manages.
  v1 counts them in diagnostics. A "clear cached b-roll proxies" action is a
  follow-up.
* **A render on a remote machine** would render from proxies, because the
  original is offline. The companion warns before a render on a timeline that
  has offline b-roll originals. v1 only logs it; a real warning is a
  follow-up if Timeline Cards or the render path needs it.
* **Music is not changed.** Tracks are small and are downloaded whole, as
  today.

### What phase 3 found that this section did not foresee (2026-09-17, built)

Four things the wording above did not match, all settled in the code:

1. **"A ledgered path counts as absent" cannot be the whole test.** The
   ledger has to be falsifiable, or a stand-in that a later real download
   replaces would be treated as a lie for ever and never imported again. So an
   entry records the stand-in's SIZE, `is_standin()` is "there is an entry AND
   the file is still that size", and `is_stale()` -- an entry whose file is a
   different size now -- is what tells the relink pass this clip was born from
   a stand-in. A file that is simply ABSENT leaves the entry standing.
2. **Lane A's filter does not need to read the ledger.** Every lane A run is
   scoped to `Projects/<rel_path>` of one selected project
   (`sequencer._process_project`), and a rel that could climb out of it is
   refused before any path is built, so `Assets/B-roll Archive` is never
   inside a lane A source. Code there would be dead code; the guarantee is a
   test instead (`test_broll_standins.py`), which fails the day the scope
   widens.
3. **The relink pass must not stat every clip to answer the `.mp4` rule.**
   "Is the original on this machine" is a stat per clip per 120 s, which is
   exactly the SMB round-trip storm ops-efficiency-8 (CR-66/CR-67 item 9)
   removed. `plan_relinks` asks it LAZILY: only when the only proxy candidate
   on disk is a `.mp4`, and only for a clip whose proxy is not working.
4. **The refresh needs the clip's stored `Frames`, which nothing read.**
   `get_media_pool_items` reads three properties per clip (5.5 s over 1,298
   clips), so a fourth is not free. `Frames` is therefore enriched **for
   archive clips only** (`resolve_bridge._under_broll_archive`), and the
   refresh is scoped to the archive for the same reason: project footage is
   imported on the machine that holds the original and cannot be in that
   state. Two consequences worth knowing: on a machine whose pool is read
   through the API fallback rather than the project library, `Frames` is not
   carried and the refresh does not fire; and the refresh runs the
   `replace_clip` BEFORE the proxy link and skips the link when it fails,
   because a proxy judged against the stand-in's frame count would be refused
   and that refusal is REMEMBERED (COMP-MEDIA-5's brake working against us).

---

## 7. Order, deploy and tests

| Phase | Where | Depends on | Ships as |
|---|---|---|---|
| 0 spike | base rig, one Windows remote, leso's Mac | nothing | a verdict in §3 |
| 1 preview spec | indexer + companion `ffmpeg_tools` (both `preview_proxy_cmd` and `dropframe_normalized`), the import-based parity test | nothing | indexer change + companion build |
| 2 editing proxy at ingest | `broll/web` migration + detail API + page POST body, indexer probe, companion ingest | 1 | dashboard (b-roll web) **first**, then companion |
| 3 proxy-only insert | companion `broll_server`, `broll_standins` (new), `broll_fetch`, `music_worker`, `proxy_relink`, `resolve_bridge`, `watcher`, `app` | 0, 2 | companion build |

Deploy the dashboard before the companions: the new detail fields are
additive, an old companion ignores them, and a new companion talking to an
old dashboard sees no `preview_rel` and falls back to today's behaviour.

Tests (per component, run once centrally as usual):

* Indexer and companion: import-based argv parity for the new preview spec
  and for `dropframe_normalized` (a tmcd colon stays a colon, a tag-only
  colon at 29.97 becomes a semicolon), and the frame-count check (a short
  encode fails).
* `broll/web`: the migration adds the three columns and an old row answers
  `original_is_edit_weight: null`; the page forwards the `insert` object;
  `test_mounted_prefix` still passes.
* `broll/web`: the insert payload for every case: edit-weight original,
  heavy original with and without an editing proxy, a legacy clip with only
  a preview, and the two-files-with-one-stem fallback
  (`tests/test_insert_target.py` grows).
* Companion: the table in §6 as a decision-table test with a fake bridge;
  the upgrade ledger survives a restart; no preview is linked when the
  original is local; the popup stays quiet for an offline archive original
  that has a proxy. **DONE 2026-09-17**, as four companion test files, all
  green and none of them needing Resolve, ffmpeg, NVENC, Tk or a NAS:
  * `tests/test_broll_standins.py` (21) - the ledger: restart round trip,
    the CR-90 key, staleness, a corrupt file, the archive prefix against its
    two other copies, and lane A's "cannot see the archive at all".
  * `tests/test_broll_insert_tiers.py` (30) - §6's table cell by cell, then
    the wiring: which rel is fetched to which dest, the ledger written
    BEFORE the import, a failed fetch recording nothing, and the
    `downloading`/`busy` shapes unchanged.
  * `tests/test_broll_proxy_upgrade.py` (14) - the background upgrade: its
    own fetch lane in both directions, pending across a restart, a refusal
    that stays pending, a failure that does not, and the worker action.
  * `tests/test_proxy_relink_standins.py` (12) + `test_watcher_broll_archive.py`
    (5) - the `.mp4`/`.mov` rule, the refresh op, a working proxy left
    alone, and MISSING-but-counted-nowhere.
* Manual, on the three spike machines: insert on remote, open on wired,
  confirm full quality with no relink; confirm the swap from preview to
  editing proxy on a clip already in the timeline.

---

## 8. Questions for the owner

1. **Preview size:** 1080p (about 3-5 Mbps, sharper, about 10x today's
   files) or 720p (about half that)? The plan assumes 1080p.
2. **Existing Creators_Club archive entries** point at a 1080p editor proxy,
   not at the camera original. A wired rig that "gets the full file" gets
   that 1080p file. Is that good enough, or should those entries point at
   the real originals under `Projects/`? That is a separate piece of work.
3. **BRAW and other camera-raw originals at ingest:** preview-only inserts
   for now, or should phase 2 include the Blackmagic Proxy Generator
   hand-off?
4. **Where the edit-weight line sits:** 1080p and about 12 Mbps is the
   proposal. Anything above that gets an editing proxy.

Decisions taken without the owner on 2026-09-17 evening, so building could
start; each is one line to reverse: the preview is 1080p (question 1), the
edit-weight line is question 4's proposal, and the drop-frame rule is the
tmcd-trusting one in §4.
