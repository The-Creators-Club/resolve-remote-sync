# Audit of `BROLL_PROXY_TIERS_PLAN.md`

Audited 2026-09-17 against the same HEAD the plan cites (`3643f7b`, working
tree at `4aaca6a`), by reading every file and line the plan cites and the
Resolve scripting README on this rig. Nothing was changed; this is the list
of what the plan gets right, what it gets wrong, and what it leaves out.

**Verdict.** The plan's account of today's behaviour is right in substance:
all six rows of its §1 table hold, the archive really does file the shoot's
1080p proxy as the top slot, and the two-extension `Proxy/` convention it
leans on exists and prefers `.mov`. The design is sound. But four things
would change the shape of phases 2 and 3 if they were known before building,
one of them would silently undo phase 3 two minutes after every insert, and
several citations point at the wrong file or function. Ranked below.

## Findings

### F1 (high) The relink pass undoes "stop linking the preview" and does not perform the upgrade

`app._relink_proxies_once` runs every 120 s over the whole media pool
(`proxy_relink.py:208-213`). `plan_relinks` (`proxy_relink.py:304-350`)
takes every clip whose original is in the tree or on the canonical prefix
and whose proxy is **not working**, and links the first of
`Proxy/<stem>.mov`, `Proxy/<stem>.mp4` that exists on disk. Two consequences
the plan does not account for:

- §6's wired row ("link `edit_proxy_rel` if it exists, otherwise link
  nothing") and remote row ("stop linking the 540p preview") only hold until
  the next pass. A clip inserted with no proxy has the preview attached by
  the relink pass within two minutes, on every machine, for all 5,031
  Creators_Club clips that have only a preview.
- §6 step 5 says "`proxy_relink` already relinks when a proxy file
  changes". It does not. `plan_relinks` skips any clip whose proxy is
  working (`proxy_relink.py:344-346`), so a clip playing the preview is never
  swapped to the editing proxy by that pass. The upgrade needs its own
  explicit `LinkProxyMedia` through `resolve_bridge.link_proxy_media` (the
  plan describes this too, so the sentence is wrong rather than the design).

Phase 3 therefore has to change the candidate rule in `plan_relinks` (only
ever offer a `.mov`, or consult the same "original is on disk" test the
insert uses), and `proxy_relink.py` belongs in §7's "Where" column.

### F2 (high) The companion never sees the detail API

The page POSTs `{share, rel_path, in_frame, out_frame, mode}` and nothing
else (`broll/web/static/app.js:1691-1692`, `broll_server.py:717-721`). The
fields §5 adds (`preview_rel`, `edit_proxy_rel`, `original_is_edit_weight`,
`geometry`) are in a response the companion never fetches. Either the page
forwards them in the POST body, which is a `broll/web/static` change §4
says does not exist and needs the old-page/new-companion and
new-page/old-companion cells in the test matrix (`comp-broll-music-4` in
KNOWN_BUGS is the precedent for that skew biting), or the companion derives
both proxy paths itself by the stem convention
(`proxy_relink.expected_proxy_paths`) and probes edit-weight with its own
ffprobe. §7's deploy note ("a new companion talking to an old dashboard
sees no `preview_rel`") implies the first. Say which.

### F3 (high) "geometry comes from the index" is half true, and "no schema change" does not hold

`videos` carries `duration_s, fps, width, height, codec`
(`broll/web/schema.sql`) and nothing else: no frame count, no start
timecode, no bitrate. `frames` and `start_tc` are what method A writes into
the FCPXML, and bitrate is what `original_is_edit_weight` is decided on.
Either the indexer and the ingest crunch both store three new columns, or
the detail route runs ffprobe against the NAS file per request, inside the
container, on a possibly multi-GB ProRes original. Also, for a
`source: proxies` share the stored probe is of the shoot's **proxy**, not
the original.

The sample geometry in §5 does not describe the file it was evidently taken
from. `Johnny_Harris/cam_1/cam-1-001.mov` is 6064x3424 ProRes 422 at 30/1
with timecode `12:05:55:26` (colon, non-drop) and 1674 frames; the example
says 3840x2160, 30000/1001 and `12:05:55;26`.

### F4 (medium) The popup claim is wrong in mechanism, and the count is not debug-only

§1 and §6 say `classify_path` returns `OK` for an offline archive original
and that the missing-on-disk count is debug-only, citing `paths.py:282-290`.
On a remote machine the stored path is `P:\...`, which is not under
`local_root`, so `classify_path` returns **`MISSING`** (`paths.py:312-326`;
the module docstring calls this the designed steady state on a remote rig).
`MISSING` is not a popup and never was, but since RES-12/RES-19 the count
and up to 50 paths go into every report as `sync_guard.resolve_health`
(`app.py:4819`) and the tray's diagnostics line prints "N missing on disk"
(`tray.py:2586`). Every proxy-only b-roll insert adds one to that number on
the dashboard. The test the plan proposes should pin `MISSING`, not `OK`,
and the dashboard-side reader of `resolve_health.missing` must not count
these as a problem. RES-19's list gives it the paths to tell them apart.

### F5 (medium) A spike candidate is missing: `LinkFullResolutionMedia`

The Resolve README (line 324) has
`MediaPoolItem.LinkFullResolutionMedia(fullResMediaPath)`: "Links proxy
media to full resolution media files specified via its path". Import the
preview as the clip, then link the canonical original as its full-res. It
is two calls, no FCPXML, no throwaway timeline, and whether it accepts a
path that does not exist on this machine is exactly the spike's question.
It belongs at the top of §3's table.

### F6 (medium) R17 is the closest prior art and is not cited, and phase 1 inherits its live case

KNOWN_BUGS R17 records ten previews Resolve refused as proxies. Nine have
identical `nb_frames`, duration, `pix_fmt` and no timecode on either side,
so phase 1's post-encode check (count frames, compare with the source)
passes them; the refusal tracks which encoder run made the file, and the two
experiments R17 names have never been run. Phase 1 should run them before
trusting the check.

R17's tenth case is live today and phase 1's "source timecode, unchanged"
carries it forward: `dropframe_normalized`
(`broll_index/ffmpeg_tools.py:102-123`) rewrites a colon 29.97 timecode to
the semicolon form for the preview. A genuinely non-drop 29.97 source gets a
preview Resolve refuses. The Johnny Harris shoot being prepared for the
archive today has 231 such proxies (of 377), all colon-form from a tmcd
track, so every one of its 29.97 previews will be refused as an adjacent
proxy until that rule can tell Sony's colon-printed drop-frame from real
non-drop material.

### F7 (medium) Fetch concurrency

`broll_fetch.MAX_CONCURRENT_FETCHES = 2`; a third request answers `busy`
and the page polls. §6 step 5 puts a background editing-proxy download of
hundreds of MB per insert into that same pool, so two inserts in a row park
every further Send to Resolve behind them for minutes. Either the upgrade
takes a lower-priority lane or the cap counts foreground fetches only.

### F8 (low) The "argv-parity test" is a hand copy, not a cross-check

`companion/tests/test_ffmpeg_tools.py:235-262` compares the companion's
preview argv against a hand-copied list of the indexer's flags.
`test_broll_ingest_media.py` imports the indexer module for hash, probe,
sprite and poster parity, but not for the proxy argv. Changing the indexer's
spec alone fails nothing. Make the proxy argv an import-based parity (like
the sprite one) before changing the spec, or the two pipelines diverge on
the first tuning.

### F9 (low) Citations that point at the wrong place

| Plan cites | Actually |
|---|---|
| `ffmpeg_tools.py:551-664` for the own-footage recipe | the **companion's** `ffmpeg_tools.py` (`own_proxy_cmd`, `OWN_BITRATE = "7M"`, `hvc1`, AAC 192k). Lines 551-664 of the indexer file the table names two rows earlier are contact-sheet code |
| `fixer.py:300-315` "the fixer only copies clips outside local_root" | `suggest_destination`. The in-tree rule is `paths.classify_path` (OK / MISSING); the fixer never sees those |
| `broll_fetch.py:86` for the download destination | `ARCHIVE_REMOTE_REL` (the NAS side). The local destination is `broll_server.contained_local_path` with `BROLL_ARCHIVE_REL` (`broll_server.py:242,353`) |
| `companion/.../broll_ingest_media.py` `preview_proxy_cmd` as the spec | a one-line delegate (`:129`). The spec is `companion/ffmpeg_tools.py:698` |

Everything else cited checks out: `routes_api.py:26-64,152`,
`resolve_bridge.py:2834-2878`, `:2989-2995`, `:3250-3278`,
`music_worker.py:128-151`, `canon.py:167-193`, `proxy_scan.py:560-570`,
`proxy_relink.py:58`, `media.py:60-102`, `build_archive.py:194-240`; the
named files (`fix_10bit_proxies.py`, `broll_upload.UploadQueue`, `bpg.py`,
`test_insert_target.py`) exist; `ImportTimelineFromFile` with
`importSourceClips`, `LinkProxyMedia`, `ReplaceClip` and `DeleteTimelines`
are all in the Resolve README; `BROLL_INGEST_PLAN.md` step 7 already says
originals upload last, so §5 item 5 restates it consistently.

### F10 (low) Not re-measured

The §1 measurements (37-970 kbps, 1.9 MB average, 5,031 and 2,224 clips,
194.5 and 287.1 GB) were not re-taken. Nothing seen contradicts them.

### F11 (low) Small points worth knowing before building

- `_attach_adjacent_proxy` links the first candidate that **exists** and
  returns whether or not Resolve accepted it (`resolve_bridge.py:2855-2878`),
  so with both files present a refused `.mov` means no `.mp4` fallback.
- The insert runs in a one-shot worker child with a timeout
  (`music_server.call` -> `music_worker.BROLL_INSERT_ACTION`). The FCPXML
  import, folder move and `LinkProxyMedia` of phase 3 steps 2-4 must fit
  that budget, and the background upgrade needs its own child call.
- CR-90: the rel paths in the detail response are NFC; the `Proxy/` path a
  Mac writes on disk is NFD. The upgrade ledger's keys and
  `find_proxy_on_disk`'s probe both need the normaliser.
- The archive is not managed by any sync lane (only `Assets/Luts` and
  `Assets/Stills` are Syncthing folders; lanes A and B are project-scoped),
  so §6's "no sync lane manages it" holds.

## Recommendation

Fold F1-F4 into the plan before phase 0 starts: F2 and F3 change phase 2's
contract (what is stored, and how it reaches the companion), F1 changes
phase 3's file list. Add F5 to the spike table as the first method tried.
Make R17's two experiments phase 1's first task, and decide what
`dropframe_normalized` should do with a colon-form 29.97 tmcd track before
any preview is re-specified.
