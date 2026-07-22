# ccsync-companion

Editor-side companion app for the Creators Club Resolve remote-sync system.
See `../SPEC.md` (repo root) for the full system design — this README covers
just this `companion/` package: a tray app + three supervised daemons that
implement "Architecture + Components §2" of that spec.

## What it does

1. **Timeline watcher** (`watcher.py`) — polls the current Resolve project's
   current timeline every 3s (configurable), reads every video+audio
   timeline item's source file path, and classifies it:
   - **OK** — under your `local_root`.
   - **OUT_OF_TREE** — exists on disk but outside `local_root` → queued for
     the popup fixer.
   - **BAD_PREFIX** — starts with the canonical shared prefix (`P:\` on
     Windows) but doesn't resolve under `local_root` → a mapping-health tray
     notification (your `subst P:` / Mapped Mount setup is probably broken).
   Debounced per session — once you Ignore a path, it won't pop again until
   you restart the app.

2. **Popup fixer** (`fixer.py` + `popup.py`) — one tkinter dialog listing
   every accumulated OUT_OF_TREE clip, with a destination dropdown pre-filled
   by file type (audio → `Audio/Music`, stills → `B-roll/Stills`,
   video/other → `B-roll/Editor Added/<editor_name>`), editable free text,
   and existing directories under `local_root` (minus any `Proxy/` dirs) as
   suggestions. **Fix all** copies each file into `local_root` (never
   clobbering — collisions get ` (2)`, ` (3)`, ...) then relinks the Resolve
   media pool item via `ReplaceClip`, preserving every timeline usage.
   **Ignore** suppresses the listed clips for the rest of the session. The
   original file is never deleted or moved, even if the Resolve relink call
   fails.

3. **Sync orchestrator** (`sync/`) — three lanes behind a common
   `LaneAdapter` interface (`sync/base.py`), matching SPEC.md's table:

   | Lane | Module | Content | Direction | Trigger |
   |---|---|---|---|---|
   | A | `sync/rclone_lane.py` (`direction="up"`) | video originals, outside `Proxy/` | editor → NAS | watchdog file events (10s debounce) + periodic full pass (`scan_interval_up`, default 300s) |
   | B | `sync/rclone_lane.py` (`direction="down"`) | `**/Proxy/**` only | NAS → editor | periodic full pass only (`scan_interval_down`, default 120s) |
   | C | `sync/syncthing_lane.py` | everything else | bidirectional | supervises a locally-running Syncthing over its REST API; does not sync directly and does not install/launch Syncthing |

   Lane A uses `rclone copy` with `--ignore-existing` (never clobbers a file
   already on the NAS — SPEC.md's "editors sync originals up" is intentionally
   one-directional and non-destructive) and `--min-age 30s` (file-stability
   wait, so a file mid-copy from a camera card isn't uploaded half-written).
   Lane B uses `rclone sync` (NAS is authoritative for proxies — renames and
   deletes propagate down).

4. **Tray** (`tray.py`) — pystray icon: green = all lanes OK, orange = a lane
   is syncing, red = any lane has an error. Menu: per-lane status line,
   "Sync now", "Pause sync" toggle, "Open log", "Quit". Falls back to
   headless console logging if pystray/Pillow aren't installed (same
   try/except pattern used throughout).

`app.py` (`CompanionApp`) wires all of the above together and is what
`ccsync-companion` (see `pyproject.toml`'s `[project.scripts]`) actually runs.

## Requirements

- **DaVinci Resolve Studio**, with external scripting enabled:
  **Resolve → Preferences → System → General → External scripting using: Local.**
- Python 3.12.
- A pre-configured `rclone` remote pointing at the NAS (`rclone config`) —
  this app does not configure rclone remotes or install rclone for you.
- A locally-running Syncthing (bootstrap/installer's job, not this app's) if
  you want Lane C.

## Install & run (from source)

```
cd companion
python -m venv .venv
```

Windows:
```
.venv\Scripts\activate
pip install -e .
ccsync-companion
```

macOS:
```
source .venv/bin/activate
pip install -e .
ccsync-companion
```

Tray icon needs the optional extra: `pip install -e ".[tray]"` (installs
`pystray` + `Pillow`). Runs headless (console logging only) without it.

## Config reference

TOML at `~/.ccsync/config.toml`, written with sane (mostly empty) defaults on
first run — see `config.example.toml` in this directory for the same content
with inline comments. Restart the app after editing.

| Key | Default | Notes |
|---|---|---|
| `editor_name` | `""` | Used to build the `B-roll/Editor Added/<editor_name>` popup destination. |
| `local_root` | `""` | This machine's local project tree root. **Must be set.** |
| `canonical_prefix` | `"P:\\"` | The shared-drive prefix Resolve's stored clip paths use (SPEC.md's Path canon). Used for BAD_PREFIX detection. |
| `remote` | `"nas"` | Name of a pre-configured rclone remote. |
| `remote_root` | `""` | Root path on the remote under which project trees live. |
| `projects` | `[]` | Project relative paths (informational in v1; per-project lane scoping is a possible v2). |
| `poll_interval` | `3` | Resolve timeline poll interval, seconds. |
| `scan_interval_up` | `300` | Lane A periodic full-pass interval, seconds. |
| `scan_interval_down` | `120` | Lane B periodic full-pass interval, seconds. |
| `watch_debounce_seconds` | `10` | Lane A watchdog debounce, seconds. |
| `transfers` | `4` | rclone `--transfers` (parallel streams). |
| `syncthing_url` | `"http://127.0.0.1:8384"` | Local Syncthing REST API base. |
| `syncthing_api_key` | `""` | Overrides reading the key from Syncthing's `config.xml`. |
| `syncthing_folder_ids` | `[]` | Expected Syncthing folder ID per project (parallel to `projects`); skipped if empty. |
| `rclone_path` | `"rclone"` | Path to the rclone binary; must be on PATH if left as the default. |
| `log_path` | `"~/.ccsync/companion.log"` | Rotating log file. |
| `log_level` | `"INFO"` | Python logging level name. |

### SPEC deviations (and why)

SPEC.md's config bullet lists a single `scan_interval`, but the Lane A/B
bullets specify **different** default intervals (300s vs 120s) — so this
implementation splits it into `scan_interval_up` / `scan_interval_down`
rather than inventing an ambiguous single knob. `watch_debounce_seconds` and
`syncthing_folder_ids` aren't named explicitly in SPEC.md's config bullet
either, but both are needed to fulfil requirements stated elsewhere in the
same section (the 10s debounce, and "verify the expected folder ID... is
configured + shared") — see the inline comments in `config.py` next to each.

SPEC.md's Lane A/B description mentions "`--sftp-*`/remote params from
config" — this implementation instead relies on `rclone config`-managed
remotes (the `remote` key is just the remote's name), since rclone already
has a first-class, more secure way to store SFTP credentials than a TOML
file. Re-open this if a good reason to hand-roll SFTP params in-config
surfaces later.

## How the lanes map to SPEC.md

- **Lane A (video originals, up)** = SPEC.md Architecture table row 1 +
  "Flaws #2" (never deletes on NAS — reorganizations must happen server-side)
  and "Flaws #3" (same-name collisions: `--ignore-existing` means the
  *second* editor's file to reach `Audio/Music/track.mp3` silently loses the
  race and stays local-only, uploaded nowhere until renamed — this is a
  known sharp edge, not yet surfaced in the tray; see Known limitations).
- **Lane B (proxies, down)** = row 2. `rclone sync` direction (not `copy`)
  is deliberate: SPEC.md's Flaws #2 says renames propagate down because the
  server is authoritative for proxies.
- **Lane C (everything else)** = row 3 + Flaws #3's "Syncthing conflict-copies
  (surfaced in tray)" — this implementation currently surfaces Syncthing
  *health* (reachable / folder configured+shared / queued item count) in the
  tray, but does not yet parse individual `*.sync-conflict-*` filenames out
  of Syncthing's REST API to name-and-shame them in the tray menu. Noted as
  an open question below.
- **Popup fixer** = "Companion App" bullet 3 / Flaws is not listed but ties
  directly to the "Popup should move + relink automatically" line in the
  Current-state section — implemented as copy (not move) + `ReplaceClip`,
  matching the explicit "do NOT delete the original file ever" instruction
  in this task's own brief (which is stricter than SPEC.md's looser "move
  it" wording — copy-then-relink is a strict superset of safety, so this
  isn't really a deviation, just the stricter of two compatible readings).

## Tests

```
cd companion
.venv\Scripts\python -m pip install -e ".[tray,dev]"
.venv\Scripts\python -m pytest
```

105 tests, all green. Coverage:

- **Path classification** (`test_paths.py`) — Windows + posix paths,
  case-insensitivity, BAD_PREFIX priority over a coincidentally-existing
  file, similar-prefix-but-different-directory false positives.
- **Config** (`test_config.py`) — first-run creation, TOML parsing,
  malformed-file fallback, and a parity check that `config.py`'s DEFAULTS,
  `DEFAULT_TOML_TEXT`, and `config.example.toml` never drift apart.
- **Fixer** (`test_fixer.py`) — every extension → destination mapping,
  `Proxy/`-excluding directory listing, collision-safe renaming (`(2)`,
  `(3)`, ...), and the full copy+relink flow including relink-failure and
  missing-source paths (mocked `resolve_bridge.replace_clip`, real
  filesystem via `tmp_path`).
- **Popup logic** (`test_popup.py`) — the pure row-building /
  fix-all / ignore-all functions (no real Tk window is created in tests —
  see Known limitations).
- **Resolve interaction** (`test_resolve_bridge.py`, `test_watcher.py`) — a
  hand-rolled fake Resolve object graph (project manager → project →
  timeline → timeline items → media pool items) stands in for the real
  scripting API; no live Resolve instance is used anywhere in the suite.
- **rclone filter rules** (`test_rclone_filters.py`) — pure content
  assertions on the generated filter rule lists, PLUS integration tests that
  actually invoke rclone (`--dry-run` and for-real) against local temp dirs
  acting as both ends, proving: Lane A picks video files outside `Proxy/`
  only; `--ignore-existing` never clobbers a file already "on the NAS";
  Lane B's `+ **/Proxy/` / `+ **/Proxy/**` / `- **` rule set selects nested
  Proxy contents at any depth and excludes everything else; `rclone sync`
  propagates a rename (delete old name + add new name) locally. See "Test
  tooling" below for how rclone is sourced.
- **Syncthing lane** (`test_syncthing_lane.py`) — `config.xml` API-key
  parsing (missing file, malformed XML, no `<gui>` element), plus REST
  behaviour against a tiny in-process `http.server` fixture (idle/syncing/
  error states, missing-folder, folder-not-shared, unreachable server, no
  API key anywhere).
- **Tray** (`test_tray.py`) — the pure icon-color function
  (green/orange/red precedence).

### Test tooling: rclone

The integration tests in `test_rclone_filters.py` need a real `rclone`
binary. `tests/conftest.py`'s `rclone_binary` fixture checks `PATH` first,
then falls back to a **test-only** portable binary at `companion/.tools/
rclone.exe` (downloaded from rclone.org for this build, NOT installed
system-wide, NOT added to PATH, NOT referenced by any production code path —
`config.py`'s `rclone_path` default remains plain `"rclone"`). If neither is
found, those specific tests skip with a clear message rather than failing
the whole run. `.tools/` is gitignored.

## Build (PyInstaller)

```
cd companion
.venv\Scripts\activate      (or source .venv/bin/activate on macOS)
pip install -e ".[dev]"
pip install pyinstaller
pip install -e ".[tray]"     # optional, for the tray icon
pyinstaller build.spec
```

Output: `dist/ccsync-companion.exe` (Windows) or `dist/ccsync-companion`
(macOS, no extension). PyInstaller does not cross-compile — build separately
on each target OS. **This has not been run/verified in this environment**
(per task instructions) — sanity-check the resulting binary on a real
Windows/macOS box before shipping, same caveat as broll-platform's
`build.spec` this was forked from.

## Known limitations

- **PopupDialog (tkinter) is not exercised by the test suite** — it needs a
  real display. Everything it calls (`build_popup_rows`, `perform_fix_all`,
  `perform_ignore_all`) is pure and fully tested; only the widget wiring
  itself is unverified by automation. `popup.show_popup` catches any
  exception from creating the Tk window and falls back to a console listing
  (auto-suppressing nothing — the clips will be re-offered next poll) so a
  headless/no-display environment degrades rather than crashing the watcher
  thread.
- **Same-filename collisions across editors on Lane A** aren't surfaced
  anywhere yet (SPEC.md Flaws #3 flags this as a known asymmetry between
  lanes — Syncthing lane C shows conflict-copies natively; lane A's
  `--ignore-existing` silently "loses" the second editor's identically-named
  upload with no tray signal). Worth a v2 pass: e.g. content-hash compare
  before skip, or at minimum log + tray-notify on an ignored-due-to-existing
  event.
- **Syncthing lane reports aggregate health, not individual conflict
  files.** `check_once()` surfaces reachability, folder-configured+shared,
  and a queued-item count from `/rest/db/status`, but doesn't walk
  `/rest/db/browse` for `*.sync-conflict-*` names. Flagged as an open
  question below.
- **`sync/rclone_lane.py`'s watchdog integration is best-effort.** If the
  `watchdog` package (a hard dependency here, unlike the optional tray
  extras) somehow fails to start an `Observer` on a given filesystem, Lane A
  silently falls back to periodic-only uploads (logged, not raised) — there
  is no test exercising a live `Observer` end-to-end (would require real
  filesystem event delivery timing, which is flaky in CI); the debounce
  timer logic itself is straightforward enough that this was judged an
  acceptable coverage gap versus a flaky test.
- **PyInstaller build unverified**, per SPEC.md's own installer milestone
  being separate work (`installer/`) — see Build section above.
- **No macOS-specific manual testing was possible in this environment**
  (Windows-only sandbox) — `resolve_bridge.py`'s Darwin paths and
  `syncthing_lane.py`'s Darwin `config.xml` path are carried over from
  documented Resolve/Syncthing conventions and the broll-platform skeleton's
  existing (also unverified-on-Mac) pattern, not independently confirmed
  here.

## Open questions (for the orchestrator / next pass)

1. Should Lane A's `--ignore-existing` collision case get a tray
   notification (per Flaws #3), and if so, what's the intended resolution
   flow — rename-and-retry automatically, or just surface-and-let-a-human-
   sort-it-out like the mapping-health warning does?
2. Syncthing conflict-copy surfacing (see Known limitations) — worth a v2
   lane-C enhancement, or out of scope for the companion app entirely (i.e.
   "check the NAS-side Syncthing web UI")?
3. `projects` / `syncthing_folder_ids` are currently informational/
   per-project-check-only — Lane A/B sync `local_root` as a whole rather
   than scoping to just the listed `projects`. Confirm that's the intended
   v1 behaviour (SPEC.md's M4 verification describes a single fake editor
   root, which matches), versus needing per-project include/exclude rules
   once an editor has multiple projects checked out side by side.
4. The `--min-age 30s` file-stability wait (SPEC.md's own phrase) combined
   with the 10s watchdog debounce means a freshly-dropped large video file
   won't start uploading for at least 30s after its last write — is that
   window fine, or should `--min-age` be config-exposed too (right now it's
   hardcoded in `rclone_lane.py`)?
