# Stage a folder: a project folder on the NAS to a client link, in one click

*Planned and built 2026-09-10. Owner's ask, after the Taichung Drone Basic
Camp folder had been staged by hand (`CLIENT_FOLDERS.md` section 6a): "I want
to be able to share only a single folder going forward."*

Contents: [1. What it does](#1-what-it-does) · [2. Where the work runs, and why](#2-where-the-work-runs-and-why)
· [3. The rules](#3-the-rules) · [4. Data](#4-data) · [5. API](#5-api) · [6. UI](#6-ui)
· [7. Files](#7-files) · [8. Operating it](#8-operating-it) · [9. Not built](#9-not-built)

---

## 1. What it does

On the b-roll page, the Client folders panel gets **[ STAGE A FOLDER ]**. The
editor browses the tree's `Projects/`, picks a folder (a shoot, an
interviewee, a day), gives the client folder a title, and clicks **[ STAGE ]**.
The dashboard then, by itself, inside its own container:

1. creates the client folder and its link **immediately**, so the link can go
   out before a single preview exists (the page fills as clips land);
2. walks the folder, finds every clip and the best playable copy of it;
3. makes the 540p preview, the poster and the sprite sheet for each clip with
   the container's own ffmpeg, one clip at a time, and places them in the
   archive tree exactly where `build_archive.py` would have;
4. adds each clip to the index (`videos`, status `organised`, no model call)
   and to the client folder as it goes live;
5. shows progress in the folder's panel entry, survives a container restart
   (resumes where it was), and can be cancelled.

Nothing is described by a model, nothing is transcribed and nothing is
embedded: the clips browse and search by filename, exactly as an `index:
false` share does. Describing them later is the indexer's job, unchanged.

## 2. Where the work runs, and why

**In the dashboard container, on the NAS.** Verified 2026-09-10: the
container mounts the tree's `Projects/` at `/projects` (rw, `DASH_PROJECTS_DIR`)
and the archive at `/broll-data` (rw, `BROLL_DATA_ROOT`), carries a static
ffmpeg 7.0 at `/opt/ffmpeg` (the mount ytdl and music ingest already use), and
the NAS is a 16-core Xeon with 62 GB. Every file the job reads and writes is on
the same box, so there is no upload, no machine that has to be switched on
and no companion that has to be up to date.

The alternatives, and why not:

- **The companion's ingest pipeline** (`docs/BROLL_INGEST_PLAN.md`) already
  makes previews and rows, but it is built around an editor's machine
  crunching dropped files and a local model describing them: it needs that
  machine on, needs llama-server and a model present (or refuses), and
  uploads with rclone. For a folder that is already on the NAS every one of
  those is overhead, and "no describe" is not a setting it has.
- **A fleet job** (`dashboard/jobs.py`, a `proxy-480p`-style kind run on the
  base rig's NVENC) would be faster per clip, but it depends on a capable
  machine being idle, and the single-worker fallback that would make it
  reliable is this design anyway. It stays the phase-2 accelerator (§9).

**One ffmpeg at a time.** The Timeline Cards executor's rule holds here: the
NAS must never run dozens of ffmpegs because a page asked. The stager runs
one encode at a time at `nice 10` with `-threads` capped at half the cores.
With Timeline Cards' own worker that is at most two ffmpegs on the NAS.
Throughput is measured, not promised: the first live run logs seconds per
clip and the panel shows an estimate from the clips already done.

## 3. The rules

**Which files are clips.** The indexer's `VIDEO_EXTENSIONS`
(`broll_index/scanner.py`), recursively, hidden/system files and `._`
AppleDouble stubs skipped, sub-folders kept as sub-folders in the archive
(mirrors `build_archive.dest_dir`).

**Which copy is the source of the preview**, per clip, in order:

1. a file with the same stem under a `Proxy/` folder beside it (`.mp4`,
   `.mov`, `.mxf`, `.mts`, the companion's `PROXY_EXTS`) - the shoot's own
   editor proxy, which is what the ff3/ff4/mofa/base-drone shares in the
   index are built from;
2. otherwise the file itself, if ffprobe finds a video stream (a DJI or
   phone original);
3. otherwise the clip is **listed but not staged** (`no playable copy`: a
   BRAW with no proxy, a corrupt file) and the panel says so.

A file that is itself under a `Proxy/` folder is never a clip of its own; it
is only ever the copy of the clip beside it. A `Proxy/` file with no original
beside it (the original left on a shoot drive) IS a clip, so a folder that
holds only proxies stages in full.

**Where things go in the archive** (`BROLL_DATA_ROOT`), byte for byte the
`build_archive.py` layout for a `source: proxies` share:

```
<creators dir>/<archive name>/<sub dirs, the Proxy/ level dropped>/<stem>.<ext>     top slot
<creators dir>/<archive name>/<sub dirs, the Proxy/ level dropped>/Proxy/<stem>.mp4  the 540p preview = archive_path
posters/<video id>.jpg
sprites/<video id>.jpg
```

- `<creators dir>` is `config.get_archive_creators_dir()` (`Creators_Club`
  unless the site overrides it).
- `<archive name>` is the PROJECT's folder name (`safe_name`), the project
  being the nearest ancestor of the chosen folder that carries the
  dashboard's `.ccsync-project` marker (`provision.MARKER_FILENAME`), or the
  first path component under `Projects/` when no marker is found. If the
  share already has rows, the name is read from an existing row's
  `archive_path` prefix instead, so a project staged twice lands in one
  folder.
- The **top slot is copied only when the source is a `Proxy/` copy**. An
  original with no proxy is not duplicated into the archive (a folder of 4K
  originals would double on the NAS); its row records `original_path` as the
  tree path and the archive holds the preview alone. Send to Resolve then
  inserts the preview; a later proxy pass can fill the slot.
- Names are claimed the `build_archive.claim_name` way: a stem already taken
  in that folder by a different clip gets `_2`, `_3`.
- Every write is `.partial` then atomic rename; a preview whose encode fails
  leaves nothing behind. An existing, complete preview is reused (size and
  mtime agree with the row), never re-encoded.

**The share.** Own footage in the index is a `share_roots` row with
`source = 'proxies'` (that is what files it under Our Footage,
`search.creators_shares()`). The stager finds the project's share by the
tree-relative tail of `share_roots.root` (`…/Projects/2026/Base Drone` and
`tree:Projects/2026/Base Drone` are the same project, separators and case
folded); when none exists it creates one with `root = 'tree:Projects/<rel>'`,
`share = <the marker's slug, else slugify(rel)>`, `indexed = 0`. The
2026-09-10 hand-staged `base-drone` share (`root = P:/Projects/2026/Base
Drone`) is therefore reused, not duplicated.

**The rows.** One `videos` row per clip, `share` + `rel_path` relative to the
share's project root (the Proxy copy's path when that is the source, as the
indexer records it), the original beside it as an `excluded` row (the durable
record of which camera file the proxy came from, as `initial_status` writes
it). Probe fields from ffprobe (`duration_s`, `fps`, `width`, `height`,
`codec`, `shot_date` from the container's creation tag or the file mtime),
`size_bytes`, sprite geometry after the sprite is built, `archive_path` after
the preview lands, `hash` = the indexer's xxh64 head+tail digest when
`xxhash` is importable, else NULL (the container has no xxhash today; a NULL
hash matches nothing, by `_resolve_by_hash`'s rule). Status is `ingesting`
from the moment the row exists (hidden from browse and search, like ingest
rows) and `organised` once the preview, poster and sprite are all on disk.
`meta.search_generation` is bumped in the same transaction as every status
flip. A clip staged twice is the same row (matched by `share` + `rel_path`).

**Idempotent, resumable, cancellable.** Re-staging a folder reuses rows and
files and only makes what is missing. A container restart finds a job
`running` with items outstanding and continues it (the worker starts with the
mount and is stopped with it, the `cards.stop_engine` shape). Cancel marks
the job, kills the current ffmpeg, discards its `.partial`, and leaves every
clip already live exactly as it is: the client folder keeps what it has.

**Security.** The folder is a path relative to `Projects/`, normalised; `..`,
absolute paths, and anything whose real path leaves the projects root
(symlinks) are refused with a 400 that names the rule, not the path. The
worker reads under the projects root and writes under `BROLL_DATA_ROOT` and
nowhere else. Any signed-in editor may stage (client folders are the
studio's); the folder browser lists directories only, never file contents,
and never a path outside the root. Nothing here deletes.

## 4. Data

Job state lives in **`client_shares.db`**, not `broll.db`: it is client-folder
state, the ledger already has its own schema versioning
(`client_folders.SCHEMA_VERSION` 2 -> 3), and a `broll.db` migration would
have to be mirrored in five places and in the base rig's indexer. `videos`
gains no column.

```sql
CREATE TABLE stage_jobs (
    id INTEGER PRIMARY KEY,
    folder_id INTEGER NOT NULL REFERENCES client_folders(id) ON DELETE CASCADE,
    rel_dir TEXT NOT NULL,            -- below Projects/, forward slashes
    share TEXT NOT NULL,
    archive_dir TEXT NOT NULL,        -- '<creators dir>/<archive name>/<sub dirs>' for the folder root
    state TEXT NOT NULL CHECK (state IN ('queued','running','done','done_with_errors','cancelled','failed')),
    n_items INTEGER NOT NULL DEFAULT 0, n_done INTEGER NOT NULL DEFAULT 0,
    n_failed INTEGER NOT NULL DEFAULT 0, n_skipped INTEGER NOT NULL DEFAULT 0,
    current_item_id INTEGER, seconds_per_clip REAL,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    error TEXT, created_by TEXT NOT NULL,
    created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE stage_items (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES stage_jobs(id) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    rel_path TEXT NOT NULL,           -- the CLIP (original), relative to the folder
    source_rel TEXT,                  -- what the preview is made from, relative to the folder; NULL = no playable copy
    video_id INTEGER,                 -- broll.db videos.id once minted
    state TEXT NOT NULL CHECK (state IN ('pending','probing','encoding','stills','live','failed','skipped','cancelled')),
    error TEXT, attempts INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
);
CREATE INDEX ix_stage_items_job ON stage_items(job_id, ord);
```

`folder_id` is the client folder the job fills. A folder can have several
jobs over time (stage two folders into one client folder, or re-run one).

## 5. API

All under the existing `/api/client-folders` router (session identity, like
every other route there). Every URL the SPA builds is document-relative.

| Route | Body / query | Answers |
|---|---|---|
| `GET  /api/client-folders/stage/browse?path=` | `path` below `Projects/` (empty = the root) | `{path, parent, dirs: [{name, n_clips, n_with_proxy, has_marker}], available: bool, reason}` - directories only; the counts are a shallow scan of that directory (its own files, plus whether a `Proxy/` sits in it); `available: false` with a `reason` when the projects root is not configured or not readable |
| `POST /api/client-folders/stage` | `{path, title, description?, contact?, expires_at?, folder_id?}` | 201 `{job, folder}`; `folder_id` adds into an existing folder instead of creating one; 400 on a bad path; 409 when that folder already has a job `queued`/`running` |
| `GET  /api/client-folders/stage/{job_id}` | | `{job, items: [{ord, rel_path, source_rel, state, error, video_id}]}` plus `eta_seconds` from `seconds_per_clip` |
| `POST /api/client-folders/stage/{job_id}/cancel` | | `{job}` |
| `GET  /api/client-folders/{folder_id}` | (existing) | gains `stage: {job_id, state, n_items, n_done, n_failed, n_skipped, eta_seconds}` for the folder's latest job, or null |
| `GET  /api/client-folders` | (existing) | each summary gains `staging: bool` (a job queued or running) |

The worker: a single thread owned by the b-roll app, started by the mount
(`ccsync_dashboard.broll`) after the schema is ensured and stopped with the
app; standalone (`broll/web` run bare) it starts in `lifespan`. It polls the
ledger for `queued`/`running` jobs, processes items in `ord`, writes every
transition to the ledger before doing the next thing (never in-memory-only),
and reads `cancel_requested` between clips and between stages.

## 6. UI

In `clientfolders.js` / `index.html` / `style.css`, the panel's theme:

- **[ STAGE A FOLDER ]** beside `+ new folder` in the panel header. Hidden
  with a one-line note when `browse` answers `available: false`.
- **The picker**: a modal with a breadcrumb, a list of directories with
  `N clips · M with proxies` on the right and a `▸` to descend; clicking a
  name descends, **[ USE THIS FOLDER ]** selects the folder being viewed.
  Below it: title (prefilled with the folder's name), description, contact,
  expiry (the same four fields the folder editor has), and **[ STAGE ]**.
- **Progress** in the folder's detail view: a line
  `Staging: 37 of 142 ready, 1 skipped, about 12 min left` with a thin bar,
  refreshed every 3 s while a job is queued/running, **[ CANCEL STAGING ]**,
  and a list of skipped/failed clips with their reason. The link, Copy and
  open stay where they are and work from the first second.
- The panel list shows a `staging` chip on a folder with a live job.
- No em dashes anywhere in the copy (scan test). Every URL relative to the
  page (`test_mounted_prefix.py`).

## 7. Files

| File | What |
|---|---|
| `broll/web/app/stage_folder.py` | enumerate, plan, the ledger (schema v3 in `client_folders.py`), the worker thread, cancel/resume |
| `broll/web/app/stage_media.py` | the ffmpeg/ffprobe argv for preview, poster, sprite, probe - **verbatim from `broll_index/ffmpeg_tools.py`**, pinned by a by-path parity test the way `companion/tests/test_broll_ingest_media.py` pins the companion's copy |
| `broll/web/app/routes_client_folders.py` | the five routes in §5 |
| `broll/web/app/schemas.py` | `StageFolderIn` |
| `broll/web/app/config.py` | `get_projects_root()` (`BROLL_PROJECTS_ROOT`, else `DASH_PROJECTS_DIR`), `get_ffmpeg_dir()` (`BROLL_FFMPEG_DIR`, else `/opt/ffmpeg` when it exists, else PATH) |
| `dashboard/src/ccsync_dashboard/broll.py` | start the worker after the mount, stop it with the app |
| `broll/web/static/clientfolders.js`, `index.html`, `style.css` | §6 |
| `broll/web/tests/test_stage_folder.py`, `test_stage_media.py` | enumeration rules, path refusal, ledger transitions, resume, cancel, the parity test |
| `docs/CLIENT_FOLDERS.md` | §1 gains the button; §6a becomes "what the button does by hand" |

## 8. Operating it

- Watch a job: the folder's panel entry, or
  `GET /broll/api/client-folders/stage/{id}`.
- Container logs carry one line per clip: `stage job 3 item 41/142
  <rel_path>: encode 9.4 s, stills 1.1 s` and one per job.
- A job that died with the container resumes on the next boot. One that
  keeps failing on the same clip marks that clip `failed` after 2 attempts and
  moves on; the job ends `done_with_errors` and the panel names the clips.
- Re-running **[ STAGE ]** on the same folder into the same client folder
  makes only what is missing.
- To take a folder out of the archive again there is no button, on purpose
  (nothing here deletes); the clips are rows in `broll.db` and files under
  `<creators dir>/<archive name>/`.

## 9. Not built

- **Fleet acceleration.** A `broll-preview` job kind run on the base rig's
  NVENC through `dashboard/jobs.py`, with this worker as the pinning
  fallback. Worth it when a shoot is hours long and the link is needed in
  minutes.
- **Describing the staged clips** from the button (a local model in the
  container, or a fleet `describe` job). Today: flip the share to
  `index: true` in the base rig's queue config and run the indexer.
- **Watermarking, downloads, per-client passwords**: `CLIENT_FOLDERS.md` §6,
  unchanged.
