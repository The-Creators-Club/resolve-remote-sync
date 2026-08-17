# Can the b-roll indexer piggyback on Resolve's IntelliSearch? (2026-08-17)

Read-only investigation against the live base rig: DaVinci Resolve Studio
21.0.1 build 11, project "Animals - Pangolins and Bears"
(`16220a5b-b6e0-4a92-8318-0ab319ce8669`) on the PostgreSQL project server
`FF5` at 100.71.216.3, four clips freshly analysed with IntelliSearch by the
operator (Faster pack, faces on). Nothing in Resolve, on the NAS, or in the
project was modified; the one export went to a scratch directory.

**Verdict — piggyback: NO for the part that costs us money, PARTIAL for the
free extras.** IntelliSearch does not produce captions, object tags, or any
text describing what is in the picture. What it stores per clip is a list of
shot ranges, each with one **768-dimensional float32 unit vector** — an opaque
image embedding from a model whose weights ship encrypted inside the
"AI IntelliSearch - Faster" pack — plus the transcript and language it already
had from the transcription feature. We can read those vectors (they sit,
zstd-compressed protobuf, in the project database's `BtLockableBlob` table
keyed by MediaPoolItem id, and they come out in a plain `.drp` export), but an
embedding is only searchable if you can embed the *query* with the same model,
and Blackmagic exposes no text encoder, no search call, and no read-back
API — the scripting API has `AnalyzeForIntellisearch()` and
`ResetIntellisearchAnalysis()` and nothing else. So the vectors cannot drive our
FTS-based search, and using them at all would mean running Resolve's model
outside Resolve, which the EULA's reverse-engineering clause is there to
forbid. What *is* usable, and free, is the text that Resolve's other analysers
put in ordinary clip metadata (`Transcription`, `Category`/`Subcategory` audio
classes, `People` face labels) — readable through the supported
`GetClipProperty()` — but that is a side-channel for interview clips, not a
substitute for the contact-sheet description pass. The Claude stage stays.

---

## 1. What IntelliSearch is (public record)

- Introduced in **DaVinci Resolve 21** (announced NAB, April 2026); Studio only;
  runs **locally** on the DaVinci Neural Engine (GPU), no cloud. Two model
  packs downloaded through the Extras manager: **Faster** (~1 GB) and
  **Better** (~4 GB, ~6-10x slower). Sources: Blackmagic "What's new"
  (<https://www.blackmagicdesign.com/products/davinciresolve/whatsnew>), CineD
  NAB hands-on
  (<https://www.cined.com/davinci-resolve-21-hands-on-at-nab-2026-photo-page-intellisearch-and-cinefocus-in-action/>),
  DIGITAL PRODUCTION's July review with pack sizes and timings
  (<https://digitalproduction.com/2026/07/29/how-much-intelligence-in-davinci-resolves-ai/>),
  Larry Jordan's walkthrough
  (<https://larryjordan.com/articles/the-power-of-intellisearch-in-davinci-resolve-21/>).
- What the user gets: a natural-language search box (English only) over
  "visual" (objects, animals, colours, scenes), "transcript" (words already
  produced by Transcribe Audio) and "metadata" (filenames, keywords, fields).
  Results are **whole clips** in the media pool, with yellow bars marking where
  in the clip the hit is; a search can be saved as a Smart Bin. Faces are
  detected, clustered and nameable. Compositional queries ("wide shot") are
  reported not to work.
- No public source documents the storage format, and no source describes a
  scripting-level search or read-back. A Blackmagic forum thread asks for an
  "ad-hoc file for IntelliSearch results"
  (<https://forum.blackmagicdesign.com/viewtopic.php?f=33&t=234856>, 403 to
  fetchers) — i.e. users are asking for exactly the export that does not exist.
- Scripting API (installed `README.txt`, `Support\Developer\Scripting`, and
  X-Raym's mirror <https://gist.github.com/X-Raym/2f2bf453fc481b9cca624d7ca0e19de8>):

  ```
  Folder.AnalyzeForIntellisearch(identifyFaces, isBetterMode) --> Bool
  MediaPoolItem.AnalyzeForIntellisearch(identifyFaces, isBetterMode) --> Bool
  Project.ResetIntellisearchAnalysis() --> Bool
  ```

  `CHANGELOG.txt` dates all three to "21.0 Beta". There is **no** getter, no
  `Search`, no `GetIntellisearch*`, nothing on `MediaPoolItem` that returns
  analysis output. Trigger-only.

## 2. The four clips through the scripting API

Dumped every clip in the project (716 items) with `GetClipProperty()`,
`GetMetadata()`, `GetThirdPartyMetadata()`, `GetMarkers()`, `GetFlagList()`,
`GetClipColor()`, `GetUniqueId()`, `GetMediaId()` (script:
`scratchpad/dump_clips.py`, direct `DaVinciResolveScript`, read-only calls).
The analysed clips are the only four whose ordinary metadata changed:

| Clip (`Master/Interviewees/Bear/綦孟柔 Meng-Jou Chi`) | MediaPoolItem UniqueId | Category | Subcategory | People | Transcription | Transcription Status |
|---|---|---|---|---|---|---|
| `20260611_ff9941.MP4` | `a6228439-8065-4f84-bf2e-ae0f96898d82` | Dialogue | | | `(Speaking Foreign Language)` | Transcribed |
| `20260611_ff9942.MP4` | `4a4ddbed-bdc2-459d-9b74-92f840aad05a` | Effect | | `Face 1` | | Transcribed |
| `20260611_ff9943.MP4` | `411533ef-c227-4d00-8a70-824f26b91beb` | Effect | | | `(Blank Audio)` | Transcribed |
| `20260611_ff9944.MP4` | `88618a97-648a-4694-9d2b-cdda8d39375e` | Effect | `Animals,Birds` | | `(Birds Chirping)` | Transcribed |

- Sibling `20260611_ff9945.MP4` (not analysed) has every one of those fields
  empty; the property key set is identical (no new keys appear on analysed
  clips — `Category`, `Subcategory`, `People`, `Transcription` all exist as
  empty strings on every clip). `GetThirdPartyMetadata()` is `{}` on all 716
  clips; no markers, flags, colours or `Keyword`/`Description`/`Comments`
  entries were written.
- So `AnalyzeForIntellisearch(identifyFaces=True)` runs, as one job, **audio
  transcription** (the log shows four `Audio Transcription: Transcribe clip N`
  lines at 22:37:41-49), **audio classification** (`Category`/`Subcategory`),
  **face detection/clustering** (`People = "Face 1"`) and the visual pass — but
  only the first three surface as text in the API. **No object/scene tags reach
  any API-visible field.**
- Do not confuse this with the MCP server's own feature: `media_analysis
  capabilities()` reports its ffprobe/ffmpeg-based, opt-in analysis with
  `transcription.available=false`, `vision.available=false`, and
  `index_status()` says its SQLite index at
  `C:\Users\alex\Documents\davinci-resolve-mcp-analysis\...\index.sqlite`
  **does not exist**. Everything below is Resolve's own data.

## 3. On disk (read-only sweep)

Files written between 22:34 and 22:42 (the analysis window) under
`%APPDATA%`, `%LOCALAPPDATA%`, `%PROGRAMDATA%`, `Program Files\Blackmagic
Design`, the CacheClip drive and the clips' own folder:

| Path | Note |
|---|---|
| `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Extras\qNhyAA00…\log.dpl1` (22:36) | pack log for **"AI IntelliSearch - Faster"** — `3e7a856b….bin` 933 MB + `25327f52….bin` 152 MB |
| `…\Extras\GH6hQjnZ…\log.dpl1` (22:39) | **"AI IntelliSearch - Data Files"** — `e16b9b35….bin` 30 MB |
| `…\Extras\VNHigwn8…\log.dpl1` (22:36) | "Tensor RT Engines" 2.2 GB |
| `%APPDATA%\NVIDIA\ComputeCache\…` (22:37:49) | CUDA kernel cache from the inference run |
| `%APPDATA%\Blackmagic Design\DaVinci Resolve\Preferences\{user.data.xml,UI.preset}` (22:37:52) | prefs save |
| `G:\Resolve Media\CacheClip\audio\…\Proxy\20260611_ff99410_{0,1}.mov.pfl` (22:39) | audio peak files for playback |

Nothing else — **no local database, index, JSON or embedding file is written**;
the "Better" pack is not installed here. The model `.bin` files are
FlatBuffers-framed high-entropy blobs (one readable name inside the 152 MB
file: `clapper_text_emb_e.fb`, i.e. encrypted flatbuffer of a slate-detector
text embedding); the weights are not in a runnable open format.

The local disk-database schema (`Support\Resolve Project Library\Resolve
Projects\Users\guest\Projects\Nuclears\Project.db`, 146 tables, upgraded by
21.x) has no table named for search, embeddings or vectors; the only
analysis-shaped tables are the `FaceTagging*` family (present since Resolve
17) and `Sm2MpSmartFolder.SearchFilter` (Smart Bin criteria).

## 4. The Postgres project database `FF5`

Connected from a scratch venv (`pg8000`, BSD) with Resolve's project-server
default credentials (`postgres` / the well-known default — it worked, which is
itself worth noting for the SECURITY doc), SELECT only. 136 tables, 4
projects. Using the `xmin` system column, the save at 22:37:52 is transaction
**456854**, which touched exactly:

| Table | Rows written | What |
|---|---|---|
| `BtLockableBlob` | 8 | 4 × per-clip **analysis blob** (`BlobOwner` = MediaPoolItem UniqueId; DbType `Sm2MpItemLockableBlob`) + 4 × per-clip metadata blob (`BlobOwner` = the clip's `BtVideoInfo_id`; DbType `BtMetadataLockableBlob`) |
| `BtLockableBlobMap` | 1 | the project's blob map (`SM_Project_id = 16220a5b…`) |
| `FaceTaggingClip` | 4 | one row per analysed clip: `Path`, `Name`, `StartFrame`, `EndFrame` |
| `FaceTaggingData` | 2 | frames 0 and 7 of ff9942: `Features` = 1024 bytes = **512 × float16 big-endian, L2 = 1.0000** (a face embedding), `BoundingBox` = 4 × fp16 BE normalised `(0.628, 0.122, 0.911, 0.616)`, `People` → cluster |
| `FaceTaggingPeople` | 1 | `Cluster=1`, `Name='FT_Default_Name_1'` (shown as "Face 1"), `Img` = 4-byte length + zlib → 172 812-byte raw thumbnail |
| `FaceTaggingThumbnail`, `FaceTaggingClip_*` join tables | 1-4 | linkage |
| `Sm2MpMedia`, `SmPreset` | 1, 4 | the clips' own rows / PTZR presets touched by the save |

Row format of `BtLockableBlob.FieldsBlob` (Qt `QDataStream`): `u32 1, u32 1,
QString "BlobData" (UTF-16BE, length-prefixed), QVariant type 12
(QByteArray), null byte, u32 length, then the payload: `u32 0x2711` (10001,
a version tag), `u32 len`, **flag byte `0x80` = raw / `0x81` = zstd**, data.

- The four **metadata blobs** are raw protobuf: `{field 2: {1: <metadata field
  id>, 2: <value>}}…` with ids `227 = Category ("Effect"/"Dialogue")`, `228 =
  Subcategory ("Animals,Birds")`, `91 = People ("Face 1")` — the same values
  the API returns.
- The four **analysis blobs** (2 956 / 11 487 / 25 779 / 28 647 bytes
  compressed) decompress (`zstandard`) to protobuf with three top-level fields:

  ```
  f6  transcript segment(s): f1 start_s (float32, absolute TC seconds, 57612.12 = 16:00:12),
                             f2 end_s, f3 text (" (Speaking Foreign Language)"), f5 speaker (-1/-2)
  f8  language: "en"
  f11 visual shot embedding (repeated): f1 start_frame (omitted when 0), f2 end_frame,
                                        f3 bytes[3072] = 768 x float32 LE, f5 = 1
  ```

  Decoded ranges (frames at 29.97): ff9941 `[0-284]` (1 vector, static
  interview); ff9942 `[0-97] [104-149] [157-202] [209-329]`; ff9943 nine
  ranges; ff9944 ten ranges including a single-sample `[591-591]`. Gaps of 7-8
  frames between ranges show a **~4 samples/s** cadence with runs of similar
  samples merged into one vector. Every vector has **L2 norm 1.0000**, mean
  |component| 0.028; cosine similarity is 0.76-0.85 within a clip and 0.54-0.67
  across clips — semantic image embeddings, 768-d (CLIP-ViT-L/SigLIP-class
  width; the model itself is unidentifiable from the encrypted pack).
- DB-wide, 579 of 2 376 `BtLockableBlob` rows are zstd blobs; every other one
  is transcription (`f6` word timings, `f7` speakers, `f8` language) or other
  clip state (`f2`, `f5`, `f9/10`, `f13`). **`f11` appears on exactly the four
  IntelliSearch-analysed clips** — this is where IntelliSearch lives.
- No captions, no object labels, no keyword list, no per-frame class scores
  anywhere in the DB: not in these blobs, not in `Sm2MpMedia`, `BtVideoInfo`,
  `CoMediaMetadata`, or a smart-folder filter (0 rows). Search-time matching
  is done in-process against the vectors.

## 5. The `.drp` export

`ProjectManager.ExportProject()` to the scratch dir (2.5 MB zip: `project.xml`
+ one `MpFolder.xml` per bin). `project.xml` carries the same payloads as hex
text: 14 `<Sm2MpItemLockableBlob>` elements (`<BlobOwner>` = MediaPoolItem
id; four of them are the clips above, ten are transcribed interview clips),
388 `<BtMetadataLockableBlob>` elements, and the `FaceTaggingClip/Data/People`
records with `Features`/`BoundingBox` inline. So the vectors *travel* with a
project export and can be pulled from a `.drp` without touching the database —
which does not change what they are.

Compare with what `broll/indexer` writes per clip (`broll/SPEC.md`,
`docs/indexing-api.md`): human-readable `description`, `objects` (with
synonyms/hypernyms), `setting`, `motion`, on-screen text in two scripts,
`themes`, `category_hint`, `quality_flags`, and Whisper transcripts — all
text, all queryable with FTS5, model-independent, and readable by an editor.
IntelliSearch stores none of that.

## 6. Conclusions

- **(a) Where/how it is stored.** In the project database, not on the client:
  `BtLockableBlob` rows (`DbType = Sm2MpItemLockableBlob`, `BlobOwner` =
  MediaPoolItem UniqueId), Qt-framed, tag `0x2711`, flag `0x81`, zstd →
  protobuf with `f11` = shot ranges × 768-d float32 unit vectors, alongside the
  clip's transcript segments (`f6`) and language (`f8`). Faces are in the
  older `FaceTagging*` tables (512-d fp16 BE features, bboxes, zlib
  thumbnails). The same bytes appear hex-encoded in a `.drp` export.
- **(b) Can we read it?** Technically yes, three ways: SQL against the project
  server (Blackmagic's documented default `postgres` credentials are unchanged
  on this fleet — that is a SECURITY item, not a feature), a `.drp` export, or
  `GetClipProperty()` for
  the text fields. Decoding the blob format is reverse engineering of an
  undocumented Blackmagic format, and *using* the vectors would additionally
  require Blackmagic's text encoder — the DaVinci Resolve Studio EULA restricts
  reverse-engineering the software and its models; note it for counsel, do not
  build on it. Reading the documented API fields carries no such issue.
- **(c) Is it usable for our search?** No. The visual output is opaque
  embeddings from an encrypted, unidentified model. Our search is text FTS
  over descriptions/objects/on-screen text; embeddings help only if we can
  embed the *query* with the same model, which we cannot (no text tower
  exposed, no search API). Even if we could, we would lose everything the
  Claude pass gives us that IntelliSearch's own UI cannot: descriptions an
  editor can read, synonym-expanded object lists, chyron OCR in Chinese and
  English, quality flags, category hints — and per-timecode hits.
- **(d) Scripting hook?** Trigger only: `AnalyzeForIntellisearch(identifyFaces,
  isBetterMode)` on `MediaPoolItem`/`Folder`, `ResetIntellisearchAnalysis()` on
  `Project`. No search, no getter, nothing in `GetClipProperty`/`GetMetadata`
  for the visual pass. The MCP server's `media_analysis` tool is its own
  ffprobe/Whisper/vision pipeline, unrelated to IntelliSearch.
- **(e) Verdict for the plan.** **Piggyback: no.** The Claude contact-sheet
  stage remains the only source of the text our search runs on. **Partial,
  optional, and cheap:** on machines with Studio, `AnalyzeForIntellisearch`
  (or plain `TranscribeAudio` + audio classification) leaves *text* in
  documented clip fields — `Transcription`, `Category`/`Subcategory`,
  `People` — that a future companion-side enrichment could copy into the
  index for interview/dialogue clips via `GetClipProperty()`. That is a
  Whisper substitute for clips already in an editor's project, not a
  replacement for indexing an archive, and it costs GPU time on an editor's
  machine and a project save on the shared server. Not worth pursuing before
  the archive pipeline's own transcription is measured against it.

## Appendix — commands and files (scratchpad, not in the repo)

- `dump_clips.py` — walks the media pool with `DaVinciResolveScript` (needs
  `RESOLVE_SCRIPT_API`/`RESOLVE_SCRIPT_LIB`), writes `clips_dump.json`.
- `pgq.py` — `pg8000.native` connection to `100.71.216.3:5432/FF5`
  (password from `RESOLVE_PG_PW`, never in the file); `pbdec.py` — minimal
  protobuf wire decoder used for the blob dumps.
- Useful SQL (read-only):
  `select max(xmin::text::bigint), count(*) from "<table>"` per table to find
  what a save touched;
  `select "BlobOwner", octet_length("FieldsBlob") from "BtLockableBlob" where
  position('\x28b52ffd'::bytea in "FieldsBlob") > 0` for the zstd blobs;
  `select "Features","BoundingBox","FrameIdx","People" from "FaceTaggingData"`.
- Resolve log with the run: `%APPDATA%\Blackmagic Design\DaVinci
  Resolve\Support\logs\davinci_resolve.log` (22:37:41 `Audio Transcription:
  Transcribe clip 0..3`, 22:37:52 `Start saving project`).
