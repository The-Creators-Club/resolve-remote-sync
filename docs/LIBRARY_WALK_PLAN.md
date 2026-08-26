# Library walk — enumerating Resolve clips from the project library, not the API

Plan and interface contract, 2026-08-26. Status: in build (branch `library-walk`).

## Why

The companion's timeline watcher walks every item of every track through the
scripting API — `GetMediaPoolItem()` + `GetClipProperty()` per item — every
10th poll and after every edit that changes an item count. On a 451-cut
multicam timeline (904 items) that is **11–14 s per walk** (32–95 s on a bad
evening, per this companion's own "inside Resolve for Ns" warnings), and
Resolve answers scripting calls one at a time, so every other client on the
machine queues behind it: Timeline Cards' card click went from 0.3 s to 7 s.
See `E:\Projects\Editing\Resolve\MulticamPipeline\LAG-INVESTIGATION.md`.

The same walk finds **3 usable items out of 904** on that timeline, because
multicam clips report an empty `File Path` and the API exposes nothing about
their angles.

The project library (PostgreSQL on the fleet's NAS; SQLite `Project.db` for
disk libraries) has all of it, and reading it costs Resolve nothing:

| need | where | measured |
|---|---|---|
| items of a timeline | `Sm2Sequence` (`Sm2Timeline_id` = timeline uid) → `Sm2TiTrack` (`Sequence` = sequence id; `Type` 0 video / 1 audio; `UserDefinedName`) → `Sm2TiItem` (`Sm2TiTrack_id`; `Name`, `MediaRef` = pool uid, `Start`, `Duration`) | 904 items, 3 ms |
| a multicam's / compound's angles | same chain with `Sm2Sequence.Sm2MpMedia_id` = that clip's pool uid (tracks named *Angle N*) | 7 multicams → 44 angle items, 5 ms |
| a pool clip's **live** path | `BtVideoInfo.Clip` / `BtAudioInfo.Clip`, keyed by `Sm2MpMedia_id`: Resolve blob framing (header, then a zstd frame — `multicam_transcripts.decompress_blob`), inside it protobuf field 1 = directory, field 2 = file name (length-prefixed varints) | whole library (3,943 clips) 40 ms; equals the API's `File Path` for 1,298 / 1,298 clips of the open project |
| pool clip name / folder | `Sm2MpMedia.Name`, `Sm2MpMedia.Sm2MpFolder_id` → `Sm2MpFolder` | — |

Verified traps (do not re-learn):

- **`Sm2TiItem.MediaFilePath` is a placement-time snapshot** — stale after a
  relink (10 items in Energy Transition still carry the pre-relink `P:\` path
  while the pool says `W:\Creators_Club\…`). Never use it as truth.
- **`Sm2MpMedia.FieldsBlob` holds only the PROXY path**, not the media path.
- **The `Clip` blob is zstd.** Read raw it looks like a path with characters
  missing (back-references into the directory name). Decompress first.
- **One library holds many projects** (FF5: Animals, Civil Defence, Elections,
  Energy Transition, test). Always scope by timeline / sequence uid, and scope
  the pool by the project's folder tree.
- **The library does not record which timeline is open.** One API call
  (`GetCurrentTimeline().GetUniqueId()`) — or Resolve's log line
  `Current timeline (<name>) is changed`.
- **The library trails the UI by the Live Save interval** (~0.3 s here; until
  the next manual save with Live Save off). Acceptable for the watcher.
- **Resolve 21.0.1 returns `None` from `GetCurrentDatabase()` and
  `GetDatabaseList()`.** The locator must fall back to Resolve's log (project
  pointer line names the library and Network/Disk; startup lines give each
  postgres library's host) — reference implementation
  `multicam_transcripts.database_info_from_log` /
  `current_database_info` in `E:\Projects\Editing\Resolve\MulticamPipeline`.
- Resolve's library credentials on the fleet: user `postgres`, the Resolve
  default password (see `DB_DEFAULTS` in `multicam_transcripts.py`), port
  5432, server `postgres:13` on the TrueNAS (`SPEC.md`).

## Shape

```
watcher poll (every 3 s)
  └─ resolve_bridge.poll_timeline_items()
       ├─ API, under _API_LOCK, 3 cheap calls: project name, current timeline
       │  name + uid (the fingerprint; per-track item counts are no longer
       │  needed — a library walk is cheap enough to run on every fingerprint
       │  change AND every _FULL_WALK_EVERY_POLLS)
       ├─ library.ProjectLibrary.timeline_items(timeline_uid)   ← no API
       │     multicam / compound items expanded to their angles
       └─ on ANY library failure: the existing API walk, unchanged
            (one WARNING per process, then INFO at most every 5 min)

media-tree refresh (every 120 s) / Scan whole project / consolidate
  └─ resolve_bridge.get_media_pool_items()
       ├─ library.ProjectLibrary.pool_items(project)            ← no API
       └─ same fallback

anything that must ACT on a clip (ReplaceClip, LinkProxyMedia, GetName …)
  └─ resolve_bridge.media_pool_item_by_uid(uid)  ← API, on demand, cached
       (a walk of GetClipList per folder + GetUniqueId per clip: ~0.15 s for
        1,318 clips; only ever runs when there is something to fix)
```

## Interface contract (all three wave-1 tracks depend on this)

### Item dicts

Every consumer of `get_timeline_items` / `poll_timeline_items` /
`get_media_pool_items` keeps working unchanged. The dict gains keys; the
`media_pool_item` value may now be `None`:

```python
{
  "file_path":         str,        # live media path; "" when the clip has none
  "media_pool_item":   MediaPoolItem | None,   # None from the library walk
  "media_pool_uid":    str,        # Sm2MpMedia_id == MediaPoolItem.GetUniqueId()
  "clip_name":         str,
  "source":            "api" | "library",
  # timeline items only:
  "track_type":        "video" | "audio",
  "track_index":       int,        # 1-based
  "item_index":        int,        # 0-based, in Start order within the track
  "via_multicam":      str | None, # pool uid of the multicam / compound this
                                   # angle was reached through (library only)
  # media-pool items only:
  "resolve_project_name": str,
  "bin_path":          str,        # "/"-joined folder names below the root
  "proxy_path":        str,        # "" when unknown  (see open question 1)
  "proxy_state":       str,        # "" when unknown
}
```

Rule for every native call site: **never touch `item["media_pool_item"]`
directly**; call `resolve_bridge.resolve_media_pool_item(item)` which returns
the object (cached lookup by uid when the walk did not carry one) or `None`,
under `_API_LOCK` like every other native call.

### `library.py` (new module, `companion/src/ccsync_companion/library.py`)

```python
class LibraryUnavailable(Exception): ...

@dataclass
class LibraryInfo:
    kind: str            # "PostgreSQL" | "Disk"
    name: str            # library name as Resolve shows it
    host: str = ""       # PostgreSQL only
    port: int = 5432
    user: str = "postgres"
    password: str = ""   # Resolve default when empty
    sqlite_path: str = ""  # Disk only: the project's Project.db

def locate(resolve, project_name: str, overrides: dict) -> LibraryInfo | None
    # 1. resolve.GetProjectManager().GetCurrentDatabase() when it answers
    # 2. else Resolve's log (Windows + macOS paths; luts.resolve_log_path)
    # 3. overrides win for host/port/name/user/password (config keys below)
    # Disk: find Project.db under Resolve Project Library/<lib>/Resolve Projects/Users/*/Projects/<project>/
    # Never raises; None means "no idea", caller falls back to the API.

class ProjectLibrary:
    def __init__(self, info: LibraryInfo, project_name: str)   # connects; raises LibraryUnavailable
    def timeline_items(self, timeline_uid: str) -> list[dict]   # item dicts above, source="library"
    def pool_items(self) -> list[dict]                          # scoped to this project's folder tree
    def pool_paths(self) -> dict[str, str]                      # uid -> live path, cached until changed()
    def changed(self) -> bool                                   # cheap: has the library moved since last read?
    def close(self) -> None
```

- Postgres driver: **`pg8000`** (BSD, pure Python — no LGPL entry in the
  licence gate, no compiled wheel per platform). `zstandard` (BSD) for blobs.
- Every query has a statement timeout (5 s) and the connection a connect
  timeout (5 s). A failure of any kind raises `LibraryUnavailable`; the bridge
  falls back and the watcher never blocks longer than that.
- Connection is owned by one `ProjectLibrary` and guarded by its own lock;
  reconnect on error, at most once per call.
- Multicam / compound expansion recurses (a compound inside a multicam) with a
  depth cap of 8 and a seen-set.
- Ordering: tracks by (`Type`, `DbIndex` or index), items by `Start`.

### Config keys (declared in wave 2, names fixed now)

```
library_walk = true          # false = the old API walk only
library_db_host = ""         # overrides for when Resolve's own answer is wrong or absent
library_db_port = 5432
library_db_name = ""
library_db_user = ""
library_db_password = ""     # goes through secretfile like the report token
```

## Tracks

Wave 1 (parallel, separate worktrees off `library-walk`):

- **A — reader**: `library.py`, `tests/test_library.py` (SQLite fixture that
  builds the tables with the exact mixed-case column names, rows with real
  zstd + protobuf blobs made by the test), `tools/library_walk_check.py`
  (live: library vs API for the open project — counts, path agreement,
  timing; prints a table, exit 1 on any disagreement).
- **B — packaging**: `pg8000` + `zstandard` into `companion/pyproject.toml`,
  `requirements.lock`, `build.spec` hidden imports, the licence gate and
  notices; prove pg8000 authenticates against the fleet's postgres:13.
- **C — consumers**: `media_pool_uid` on every item the API walk produces;
  `resolve_media_pool_item()` + `media_pool_item_by_uid()` in
  `resolve_bridge`; every native call site (`app._handle_non_canonical`,
  `popup`, `fixer`, `consolidate`, `proxy_relink`) goes through it and copes
  with `None`; doubles gain `GetUniqueId`; tests.

Wave 2 (after A + C merge): **D — integration** (library-first walks with
fallback, config keys, logging, `source`), then **E — docs/release**
(GOTCHAS §16, KNOWN_BUGS entry, changelog + version), then **F — review**
(adversarial, three lenses) and live validation on the base rig.

## Open questions (A investigates, D decides)

1. `proxy_path` / `proxy_state` from the library: `Sm2MpMedia.FieldsBlob`
   carries the proxy path; is there a cheap "Proxy" state (`BtVideoInfo.Proxy`?).
   If not derivable, `get_media_pool_items` may keep the API for those two keys
   only when `proxy_gen_enabled`, or report "" and let proxy relink fall back.
2. The cheapest "library changed" signal: `Sm2Sequence.DbSavedTime` /
   `LastChangedTime`, `Sm2Timeline.ModTimeInSecs`, or `SM_Project.UpToDate`.
3. Scoping the pool to one project: `SM_Project` → root `Sm2MpFolder` — find
   the link (`Sm2MpFolder_Sm2MpMedia` association vs `Sm2MpMedia.Sm2MpFolder_id`).
4. macOS: does a Mac's library report the canonical `P:\` spelling or the
   mount-resolved path? (`_log_darwin_clip_path_flavor` was written to find
   out for the API; the library answer is the *stored* string, which is what
   `classify_path` wants.)
