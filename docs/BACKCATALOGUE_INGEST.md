# Back-catalogue ingest: FF2, Disinformation, WCT Event Doc

*Written 2026-08-19. Three older projects added to the b-roll archive as
`source: proxies` shares. Companion doc to `docs/INDEXERS.md` (what runs where)
and `broll/docs/indexing-local.md` (the Qwen backend).*

## What this was

Three back-catalogue projects, none of them previously in the b-roll index:

| Share | Source tree | Video files | On disk |
|---|---|---|---|
| `ff2` | `Q:\FF2` | 6,998 | 6.5 TB |
| `disinfo` | `R:\Project Backups\NAS Backup Projects-2023\Disinformation` | 1,991 | 6.4 TB |
| `wct` | `R:\Project Backups\NAS Backup Projects-2022\2022\WCT Event Doc` | 1,208 | 750 GB |

The instruction was: **high-quality proxies on the NAS, no camera originals.**
That is exactly what `source: proxies` already does (`broll_index/config.py`,
`ShareConfig.source`) - the shoot's `Proxy/` file is archived and the original
is recorded as `excluded`, never copied. ff3, ff4 and mofa-disaster all work
this way.

## The one thing that made this different from ff3/ff4

`source: proxies` recognises a proxy **by its path** - `initial_status()` asks
`PROXY_DIR_RE` whether the file sits under a `Proxy/`-ish folder, and anything
else on the share is `excluded`. ff3 and ff4 were shot after the Proxy/
workflow was standard, so the archive copy already existed for every clip.

These three do not have that property:

| Share | Clips with a proxy | Clips without |
|---|---|---|
| `ff2` | 3,276 (293 GB) | 493 |
| `disinfo` | ~0 | 793 |
| `wct` | 0 | 1,133 |

FF2's later episodes are well covered; **E1 High Stakes (11 proxies against 463
clips) and the whole Pilot (0) are not**, and the two backup projects have
none at all. Scanned as-is, `disinfo` and `wct` would have indexed **nothing**,
silently - the scan would report zero rows and look like a config error.

So the missing half had to be encoded first. That is `tools/make_own_proxies.py`.

## The proxy spec is not new

`make_own_proxies.py` does **not** define an encoding spec. It imports
`own_proxy_cmd` from `ccsync_companion.ffmpeg_tools` and uses it verbatim:

> **HEVC Main-10, 1080p, ~7 Mbit VBR (10M peak / 14M buffer), `hvc1` tag,
> AAC 192k, source timecode and metadata carried over.**

That function's own comment says it was "chosen to match the FF4-era Resolve
proxies already in the tree". Measured against FF2's existing Resolve proxies
(1080p H.264, ~6.3 Mbit, AAC 256k) it is the same class of file, so a generated
proxy and a hand-made one cut the same.

The import is worth the `sys.path` poke. Those flags encode constraints that
were each paid for once already - the `hvc1` tag (Resolve shows Media Offline
without it), `-f mp4` on a `.partial` filename (muxer EINVAL killed a whole
1,040-clip overnight queue on 2026-08-11), `-map 0:a?` for dual-audio camera
originals, the 10-bit pin against banding under a viewer LUT. A second copy of
the spec would drift the first time either was tuned.

## Two measurements that changed the plan

**AppleDouble stubs inflate every naive file count.** A plain
`find -iname "*.mp4"` over FF2 returns 3,717 clips with no proxy. The real
number is 493. The difference is **1,279 `._name.mp4` files** - 4 KB macOS
resource forks left by an editor on a Mac, which are not video and which
ffprobe rejects. `find_candidates` skips any name starting with `._`. Anyone
re-deriving these counts by hand will get the wrong answer without that filter.

**The sources are 4K 10-bit 4:2:2 XAVC at 140 Mbit, which NVDEC cannot
decode.** `nvidia-smi` reports the decoder at 0% throughout: NVDEC handles
8-bit 4:2:0 H.264, not 4:2:2 10-bit, so every frame is decoded on the CPU.
That, not the encoder, is what sets the rate. Measured on this rig (24 cores,
RTX 3080):

| Workers | Rate | Encoder block | CPU |
|---|---|---|---|
| 2 | 1.8 clips/min | 84% | ~65% |
| 5 | **11.5 clips/min (3.6x realtime)** | 96% | - |

Five is the setting. Going higher is not worth testing - the encoder block is
already saturated, and concurrent NVENC sessions are precisely what produce the
silently-damaged bitstreams `verify_decodes` exists to catch.

Measure in **video-seconds, not clips**: clip length varies by an order of
magnitude between a Pilot cutaway and an E1 interview take, so clips/min
sampled over a couple of minutes looks like a slowdown that is not there.
`3.6x realtime` is the stable number. FF2's 451 clips are only 4.6 video-hours
(avg 37 s), so it encodes in about 1.3 hours.

## Safety properties of the pre-pass

- **It never reads, moves, modifies or deletes a source file.** It only creates
  `<dir>/Proxy/<stem>.mp4`, and skips any clip that already has a proxy beside
  it in any of `.mov/.mp4/.mxf/.mts`.
- **Every output is verified before it is accepted**, against both failure
  modes seen on the real archive: a damaged bitstream (decodes with errors) and
  a truncated file (decodes cleanly, just stops early). A bad NVENC output is
  retried once on libx265 rather than on the encoder that just failed.
- **Interrupting it is safe.** Work in flight goes to `.mp4.partial` and is
  swapped into place with `os.replace` only after it has been proved to decode,
  so a resumed run redoes at most the one clip that was mid-encode.
- **The 300 s cap is applied at probe**, before any encoding - a 40-minute
  A-cam take costs one ffprobe, not an encode. Same rule the shares'
  `max_duration_s` applies later, for the same reason: these folders hold
  interviews and cutaways side by side.
- Windows `MAX_PATH`: these trees carry CJK news headlines as filenames and run
  to 275 characters before `Proxy/` is inserted, so paths near the limit are
  passed to ffmpeg in `\\?\` extended form.

## Running it

```bash
cd broll/indexer
bash tools/run_backcatalogue.sh          # all six phases, unattended
```

Ordered, not parallel: every phase contends for the same GPU, and two sharing
it is slower than either alone. Each phase is independently resumable, which is
why the driver is a flat list of commands and not a state machine.

1-3. `make_own_proxies.py` for each of the three roots (`--preset ff2 |
     disinfo | wct` selects the exclude list).
4.   `broll-index scan` per share - `source` and `exclude` are read from the
     config, never passed as flags, so a rescan cannot disagree with the first.
5.   `parallel_local.py --workers 8` - probe, the 540p browsing proxy, contact
     sheets. Note this is a *different* file from the 1080p editor proxy phases
     1-3 wrote: it lives in `data_root` and is what the search UI plays.
6.   `broll-index run --stages claude` (Qwen3-VL-4B, ~20 s/clip on this card)
     then `--stages embed`.

**Keep Resolve closed for phase 6.** The eval measured Resolve alone holding
9.3 of the 3080's 10 GB; the describe stage wants ~5 GB and will crawl or fail
against that. Measured on this rig 2026-08-19: desktop baseline 2.5 GB, and
llama-server with the Good tier loaded takes it to **8.7 GB of 10**. There is
no room for a second consumer.

### Pre-flighting the local backend

`broll-index doctor` proves the runtime and weights are on disk; it does not
prove the model loads. This does, in about 6 seconds, and is worth running
before a long queue rather than discovering a problem six hours in:

```python
cache = local_runtime.default_cache_dir()
exe = local_runtime.server_path(cache)
w, m = local_runtime.model_paths(cache, local_models.tier("good"))
h = local_vlm.start_server(exe, w, m, load_timeout=300)   # -> healthy in ~6s
h.stop()                                                  # NOT stop_all_servers()
```

**`stop_all_servers()` will not stop that handle.** It iterates the `_servers`
registry, which only `get_server()` populates - so a handle from a direct
`start_server()` call is invisible to it and the call returns quietly having
done nothing, leaving a `llama-server` holding 8.7 GB. `pipeline.py` uses
`get_server()` (registered, with an `atexit` hook), so this only bites
hand-written pre-flights. If a describe run refuses to allocate, check for a
stray process first:

```powershell
Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
```

A dry run reports what would be encoded and changes nothing:

```bash
python tools/make_own_proxies.py --root "Q:/FF2" --preset ff2
```

## Exclude lists

The presets in `make_own_proxies.py` and the `exclude:` lists in
`config.queue.yaml` describe the same subtrees and **must be kept in step** - a
folder the pre-pass skips but the scan walks contributes nothing, and a folder
the pre-pass encodes but the scan skips is wasted GPU time.

One asymmetry to know about: the scanner's `is_excluded_dir` is pure fnmatch,
where `*` crosses separators but `*/AE` does **not** match a top-level `AE`.
The config therefore lists both `AE` and `*/AE` where a project has one at its
root. `make_own_proxies.is_excluded` folds that case in itself.

Because the two implementations differ, agreement is worth checking rather than
assuming. Walking all three trees and comparing the two verdicts per directory
reported **0 disagreements** on 2026-08-19; re-run it after editing either
list:

```python
# from broll/indexer, with tools/ and . on sys.path
for dp, dn, fn in os.walk(root):
    rel = Path(dp).relative_to(root).as_posix()
    if rel == "." or PROXY_DIR_RE.search(rel):
        continue
    a = is_excluded(rel, PRESETS[name])              # the pre-pass
    b = is_excluded_dir(rel, cfg.shares[name].exclude)  # the scanner
    assert a == b, (rel, a, b)
    if a:
        dn[:] = []                                   # prune, as both callers do
```

What is excluded, and why:

- **FF2's three download folders** (`FF2 E1 - High Stakes/Youtube Downloads`,
  `FF2 E2-4 - Birthrate/Youtube`, `FF2 E3 - Idols/Archive`) are already indexed
  as the `ff2-e1-yt`, `ff2-e24-birth` and `ff2-e3-idols-ar` shares. Those were
  rooted at `H:/FF2` before the drive was remounted as `Q:` - the tree is the
  same one. Without these, each download's editor proxy would index as a second
  clip of footage already in the archive, which content hashing cannot catch
  (same footage, different encode, different bytes).
- **Disinformation's `E1`..`E5`** are the episode *edit* folders - After
  Effects comps, renders, stock packs. `E4` is the exception: it holds
  `E4/Interviews`, real shoot material, so it is pruned by part.
- Graphics and post scaffolding everywhere (`*/AE`, `*/Renders`, `*/Resolve`,
  `Premiere`, `Photoshop`, ...). An AE comp described by the model returns a
  search hit an editor cannot cut with.

## Where it lands on the NAS

`build_archive.py`'s `dest_dir` drops the source's own `Proxy/` component for a
`Creators_Club` share, so the shape is:

```
Creators_Club/ff2/<episode>/<shoot dirs>/<name>.mp4         the 1080p proxy
Creators_Club/ff2/<episode>/<shoot dirs>/Proxy/<name>.mp4   the 540p preview
```

The 1080p proxy occupies the slot a download's original would - Resolve treats
it as the source, so the clip is online and renderable exactly like a download.
That uniformity is deliberate: no per-collection special case downstream, and
no clip that can be cut but not exported. **No camera original is copied.**

## Phase 1 result (FF2, 2026-08-19)

54 minutes wall, 426 proxies, 12.4 GB for 4.3 video-hours. No NVENC retries and
no verification failures at 5 workers, which is the evidence for that setting.

| Verdict | Count | What it means |
|---|---|---|
| `ok` | 426 | proxy written and verified |
| `over-cap` | 39 | interview takes past 300 s, dropped at probe |
| `no-video-stream` | 10 | ElevenLabs voice-clone takes (see below) |
| `probe-failed` | 3 | corrupt at source (see below) |

**Read the ledger deduped.** `proxy-prepass-*.jsonl` is append-only across
runs, so a resumed or re-tuned run leaves several verdicts for the same source
and the raw counts double-count. Collapse to the last verdict per `src`:

```python
last = {}
for line in open("proxy-prepass-ff2.jsonl", encoding="utf-8"):
    r = json.loads(line)
    if r["status"] != "would-encode":
        last[r["src"]] = r
```

### Audio in a video container

Ten FF2 files under `Footage/Interviews/*/Elevenlabs/Input/` are voice-clone
source takes: `.mov` containers with an audio stream and **no video stream**.
They reached the encoder on the first pass and died on `-map 0:v:0` with
"Stream map '' matches no streams", which reads like a broken encoder rather
than a file that was never footage.

Fixed on both sides: `*/Elevenlabs` is now excluded by the preset and by the
share config, and `encode_one` checks `width`/`height` from the probe it
already paid for and reports `no-video-stream` rather than an encode failure.
Worth keeping in mind for any future project - an audio asset in a `.mov`
wrapper is not rare in these trees.

## Phase 2 result (Disinformation, 2026-08-19)

83 minutes, 590 proxies, 25.5 GB for 8.8 video-hours - about 6.4x realtime,
faster than FF2's 3.6x because less of this tree is 4:2:2 10-bit XAVC.

| Verdict | Count |
|---|---|
| `ok` | 590 |
| `over-cap` | 200 |
| `probe-failed` | 6 |

**No encode failures.** The ElevenLabs problem does not recur here: this
project's `E3/ASSETS/ElevenLabs` sits inside the already-excluded `E3` subtree,
and WCT has no such folder at all. The high `over-cap` count is the 300 s rule
working as intended - this is the interview-heavy project, 3.6 TB of long takes
against 627 GB of actual shoot footage.

## Known bad sources

Nine files across the two projects are corrupt at source - `moov atom not
found`, i.e. aborted camera writes, interrupted copies or (the two `_iris3`
ones) a recorder stopped mid-file. They are recorded as `probe-failed` and are
not a tool failure; nothing in the index needs changing, but they cannot be
proxied or indexed until re-copied from the original media.

FF2:

```
Q:\FF2\FF2 E3 - Idols\Footage\B Roll\fx3ke20240802_1232.MP4
Q:\FF2\FF2 E3 - Idols\Footage\Interviews\Wang Peiti\Wang_Upscaled.mp4
Q:\FF2\Pilot\twn filibuster 22052024\fx320240521_0110.MP4
```

Disinformation (paths relative to the share root):

```
Footage\Tainan 2\fx3\fx320231224_0022.MP4
Footage\Taichung-Tainan Trip 3\Day 2\Blackmagic\A010_01261818_C334.mov
Footage\Taichung-Tainan Trip 3\Day 2\Blackmagic\A010_01261906_C339.mov
Footage\Taichung-Tainan Trip 3\Day 2\FX3\fx320240209_0070.MP4
Interviews\Edward Barss\2023-12-14 01-02-06_iris3.mp4
E4\Interviews\Dannagal Young\Dannagal_Young_iris3.mp4
```

## WCT is not described (2026-08-19)

Taken mid-run, at phase 6: `wct` is `index: false` in `config.queue.yaml`. Its
proxies were encoded (phase 3) and its contact sheets built (phase 5), but the
1,113 clips get no model call - it was not worth another 3 hours of the card.

What that means in practice:

- The clips rest at `organised`, not `proxied`. That is the resting status the
  pipeline already has for an opted-out share: out of the work queue, so the
  next run does not pick them up and the watchdog does not respawn on them,
  but not claiming an `indexed` row's segments and themes either.
- **They are still copied to the archive.** `build_archive.py`'s copy set is
  `indexed`, `proxied` and `organised`, so WCT lands on the NAS and browses
  and searches by filename like any other folder - it simply has no
  descriptions, no themes and no category behind it.
- **It is reversible in one line.** Flip `index: false` back and
  `reopen_if_now_indexable` puts every one of the 1,113 rows back to `proxied`
  on the next run, sheets and all.

The flag only takes effect in a fresh process - `run` loads the config once at
start and holds it - so the describe pass was restarted after the edit rather
than left to reach WCT with the old config in memory. Restarting is safe by
construction: at most the one clip in flight is redone.

## Every project keeps its own folder, and its own subfolders

Owner's instruction, 2026-08-19. Nothing about it is new for an own-shoot
share - `source: proxies` already files a clip at
`Creators_Club/<share>/<the shoot's own directories>`, with only the source's
`Proxy/` level dropped (in the archive that level means "the preview"). What
changed is the top-level NAME.

`disinfo` and `wct` are share keys, not project names, and the key is what
every `videos` row is stored under - renaming it would orphan the lot. So the
folder is now a separate, optional setting, `archive_name` on the share:

| Share key | Folder on the NAS |
|---|---|
| `ff2` | `Creators_Club/ff2/FF2 E1 - High Stakes/Footage/Interviews/...` |
| `disinfo` | `Creators_Club/Disinformation/Footage/Bento/Bento shop b roll/` |
| `wct` | `Creators_Club/WCT Event Doc/Footage/Interviews/session 2/` |

Set it BEFORE a share's first copy. `build_archive.py` never deletes at the
destination, so changing it afterwards moves nothing - the old folder stays and
the next run copies every clip again under the new name. These three had not
been built yet, which is why this cost nothing; `ff3`, `ff4` and
`mofa-disaster` keep their existing folders for exactly that reason.

**The download shares are deliberately not part of this** (decided 2026-08-19).
They file under `Downloads/<category>/`, which loses the origin project, and
2,223 of them are already on the NAS with editors' timelines pointing at those
paths. Re-filing them by project is a real change with a real migration behind
it, held for its own pass rather than folded into this one.

## Afterwards

Neither of these is part of the driver - both are deliberate steps.

```bash
python build_archive.py --dest "P:/Assets/B-roll Archive" --apply
python ../../server/publish_db.py --which broll
```

`publish_db.py`, never a file copy: the container holds `broll.db` open
read-write in WAL mode. See `docs/BACKUP_RESTORE.md`.

**The live copy holds rows this one has never seen** (BROLL-1, 2026-09-04):
every clip the fleet has drag-and-drop ingested since you pulled, and every
`ingest_batches` row. `publish_db.py` drains them out before the rename and
merges them back after it, and refuses to publish if it could not take that
drain - so read what it prints rather than assuming a publish is a file swap.
Check the b-roll ingest panel for a running batch first: a batch that starts
between the drain and the rename is the one thing the drain cannot see.
`docs/INDEXERS.md`, "Publishing broll.db without deleting what the fleet
ingested".
