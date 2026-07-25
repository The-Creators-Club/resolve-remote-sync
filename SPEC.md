# Resolve Remote-Editor Sync System ("Creators Club Sync")

## Context

Remote editors will collaborate on the self-hosted Resolve Project Server (postgres:13 app on TrueNAS `192.168.0.102:5432`) over Tailscale. Blackmagic Cloud's media side must be replicated self-hosted, with three automatic behaviors:

1. **Proxies auto-download** to each editor's machine, recreating the server's folder tree exactly.
2. **Anything an editor adds to a timeline auto-uploads** to the *same relative folder* on the NAS (music in `Audio\Music` locally → `Audio\Music` on NAS), so every Resolve workstation picks it up. Editors sync their video *originals* up; the server syncs only *proxies* of video down.
3. **Popup warning** on the editor's machine when a timeline clip lives outside the synced project folder, with a one-click "move it to where it's syncable" fix.

Target: beat Blackmagic Cloud's observed ~60 mb/s up/down. User explicitly OK with A/B-testing different transfer services.

Canonical layout = existing template `Z:\Cablewrap\Projects\2025\FF4\Nuclear` (`AE/ Audio/ B-roll/ Interviewees/ Render in Place/ Subs/ Youtube/`), which already uses **per-folder `Proxy/` subfolders** — the exact convention Resolve + Blackmagic Proxy Generator auto-link from. Final NAS home: `/mnt/tank/TheCreatorsPool/Creators_Club/Projects/<year>/<series>/<project>`.

## Current state (verified)

- TrueNAS 25.10.4: `resolve-projectserver` (postgres:13) RUNNING, bound 0.0.0.0:5432. **Tailscale app RUNNING but logged out** — needs re-auth.
- Syncthing 2.1.2 available in TrueNAS stable app catalog (not installed).
- SMB share `TheCreatorsPool → /mnt/tank/TheCreatorsPool` (only `Temp Transfer` in it; project tree is greenfield). Dataset owner `broll`, mode 770.
- HiNet: inbound 80/443 blackholed, but high-port forwarding works (BitTorrent 51413 hit line rate) → Tailscale direct connections achievable (forward UDP 41641 if NAT traversal relays).
- Reusable skeleton: `E:\Projects\broll-platform\companion\` — cross-platform Resolve scripting bridge (`src/broll_companion/resolve_bridge.py`: env bootstrap for Win/Mac, never-raise connect, `ReplaceClip`-style media pool ops), pystray tray (`tray.py`), config, tests, PyInstaller `build.spec`.
- Editors: **Windows + macOS**. Popup should **move + relink automatically** (with Ignore option).

## Architecture

Three sync lanes with different directions, one policy:

| Lane | Content | Direction | Engine (initial pick, benchmarked in M3) |
|---|---|---|---|
| A: video originals | video files outside `Proxy/` dirs | editor → NAS only | rclone (SFTP, multi-stream) |
| B: proxies | `**/Proxy/**` | NAS → editors only | rclone (SFTP, multi-stream) |
| C: everything else | audio, GFX, AE, subs, docs, stills | bidirectional | Syncthing (event-driven, block-delta, versioning) |

Why split: no single tool expresses "video up-only, proxy down-only, rest both ways" in one folder. Syncthing `.stignore` can't upload a file type it ignores; rclone bisync is weak on conflicts. Splitting gives multi-stream bulk lanes (where speed matters) and battle-tested bidirectional sync for the small-file lane. Lanes are behind an adapter interface so the benchmark can swap engines per lane.

**Path canon:** one virtual drive letter on Windows — `P:`. Host/base rig: `P:` → `\\192.168.0.102\TheCreatorsPool\Creators_Club` (SMB). Editors (Win): `subst P: C:\Creators_Club` at login. Editors (Mac): local root `~/Creators_Club` + Resolve **Mapped Mount** preference translating to `P:` paths (one-time documented setup; companion verifies it by checking timeline clip paths resolve). All DB-stored paths are `P:\Projects\...` → identical everywhere.

**Proxy generation:** **Blackmagic Proxy Generator on the base rig** watching `P:` (per-project watch folders). It natively handles BRAW (ffmpeg cannot decode .braw), is GPU-accelerated, preserves timecode, and writes to the in-place `Proxy/` subfolder convention — exactly what Resolve auto-links, and what the template tree already uses. Output: H.264 1080p (cross-platform safe; revisit H.265 later). NAS-side ffmpeg fallback container is a later nice-to-have for non-BRAW formats when the PC is off (PC has wake-on-LAN anyway).

**Resolve behavior:** editors run Playback → Proxy Handling → *Prefer Proxies* (original offline locally → proxy plays); host prefers camera originals. Auto-link requires same filename + timecode in the adjacent `Proxy/` folder — BPG guarantees this.

## Components to build

New repo: `E:\Projects\resolve-remote-sync`

### 1. Server setup (scripted, `server/`)
- Re-auth TrueNAS Tailscale app; confirm editors get **direct** (not DERP) connections — forward UDP 41641 on the HiNet router if needed. Postgres reachable at tailnet address:5432 (check container pg_hba allows it).
- Create `Creators_Club/Projects/...` tree under the dataset; per-editor TrueNAS accounts (SSH key for rclone-SFTP lanes + SMB) with ACL on the dataset.
- Install Syncthing app (stable catalog), one Syncthing folder per project, `.stignore` = video extensions + `**/Proxy` (lane C only carries the rest), **staggered file versioning ON server-side** (deletion safety net).

### 2. Companion app (`companion/`, fork of broll companion skeleton, Win + Mac)
- **Tray app** (pystray): sync status per lane, pause, open log.
- **Sync orchestrator**: runs lane A/B rclone jobs (watchdog file events + periodic scan; file-stability wait before upload; `--immutable`-style skip-if-exists on lane A so last-writer-wins can't clobber), supervises/auto-configures bundled Syncthing via its REST API for lane C. NAS endpoint over Tailscale hostname.
- **Resolve watcher**: poll current timeline every ~3 s via scripting API (reuse `resolve_bridge.py` bootstrap). For each timeline item → media pool item → `File Path` clip property:
  - outside local project root → **popup** (native dialog): lists offending clips, suggested destination by type (audio → `Audio\Music`, video → `B-roll\<picker>`, etc., editable), **Fix** = copy into tree + `mediaPoolItem.ReplaceClip(new_path)` + queue upload; **Ignore** (per-session).
  - wrong path prefix (e.g. `C:\...` instead of `P:\...` on Windows, unmapped path on Mac) → mapping-health warning.
- Config file: project list, local root, endpoints, editor name.

### 3. Benchmark harness (`bench/`) — the "optimise for speed" phase
- `iperf3` editor↔NAS over Tailscale: raw ceiling + direct-vs-DERP verification (this alone likely explains the Resolve Cloud 60 mb/s).
- Matrix: rclone-SFTP vs rclone-SMB vs Syncthing v2 vs raw SMB copy; stream counts 1/4/8/16; two datasets (few large .braw ~10 GB; many small assets). Runs both directions, outputs a table; per-lane winner becomes config. Reuses the A/B-before-committing approach from broll-platform.

### 4. Editor bootstrap (`installer/`)
- Win: PowerShell script — Tailscale join, create `C:\Creators_Club`, `subst P:` at login (scheduled task), install companion (PyInstaller, autostart), print Syncthing device ID for one-time server-side approval.
- Mac: shell script equivalent + Mapped Mount setup doc with screenshots.
- `docs/EDITOR_SETUP.md`, `docs/SERVER.md`.

### 5. Fleet dashboard (`dashboard/`, added 2026-07)
- Web dashboard served off the NAS (TrueNAS custom app, port 8480, tailnet-only, no login): project list with health dots, per-project editor rows (online, completion %, has X of Y files, missing-file lists), companion fleet strip.
- Backed by SQLite (WAL) at `/mnt/tank/apps/ccsync-dashboard/data/dashboard.db`: an in-process collector polls the server Syncthing REST API (`/rest/db/completion`, `/rest/db/remoteneed`) for lane C state across all editor devices; keeps 30 days of completion history with anti-bloat snapshot rules.
- Lanes A/B have no server-side status API, so the companion gained a reporter thread that POSTs its `LaneStatus` for all three lanes to `POST /api/v1/report` every 60s (`dashboard_url`/`dashboard_token` config keys; static shared token via `DASH_REPORT_TOKEN`).
- Known limitation / future work: lanes A/B are **status-only** (state, queue counts, errors). The server cannot see an editor's local originals/proxy trees, so per-file lane A/B inventory would need the companion to report rclone `check` summaries — deliberately deferred.
- Auto-provisioning (added same day, after the "Creator Profiles" gap): the collector scans the Projects tree (mounted `rw` since the `/project-setup` create flow landed) every 5 min and creates the Syncthing folder for any project dir lacking one — **unshared**, with sharing driven by editors' dashboard ticks — so new projects need only `setup_tree.py`. Trigger is deliberately the tree, not the Resolve project DB — a Resolve project name carries no year/series path to map from; a DB cross-check ("Resolve project with no media folder") is possible future work.
- Deploy: `server/install_dashboard_app.py` (`--recreate` for compose changes; installs code with an inode-preserving copy + real `docker restart`, since TrueNAS `/app/redeploy` doesn't restart the container); UI-YAML fallback in `dashboard/deploy/compose.yaml`; runbook section in `docs/SERVER.md`.

### Companion popup/fixer extensions (added 2026-07)
- The out-of-tree fixer popup (`popup.py`) gained: dedupe of duplicate timeline references, a scrollable list with FIX ALL pinned at the top, and a **threaded** FIX ALL (copying multi-GB originals over SMB on the UI thread previously froze/killed the window) with a live progress counter.
- Destination suggestions honor the sticky per-Resolve-project root the dashboard stores (`project_roots` table), matched by the open project's name; base rigs one-shot-fetch that mapping since their sequencer doesn't run.
- Tray **Scan whole project** walks the entire media pool (not just the current timeline) for out-of-tree media. Tray **Consolidate pre-existing project…** (`consolidate.py`) onboards a project with media scattered on an editor's disk: media-pool scan → rclone `--dry-run` reconciliation report (uploads/downloads vs the NAS) → on confirm, copy-and-relink every out-of-tree clip into the tree, then upload originals (lane A) and pull proxies (lane B). Copies, never moves.
- Base rig (`mode = "base"`): no sync lanes, but the popup stays ON — a careless base edit referencing media outside the project directory still needs fixing into the tree. `local_root`/`canonical_prefix` both set to the tree root so anything else on the same drive counts as out-of-tree.
- Upgrade channel (added 2026-07-25): the dashboard hosts published companion builds (`companion_packages` table, schema v7; files under `/data/packages/`) and advertises the CURRENT one via a conditional `upgrade` key on the `/api/v1/report` and `/api/v1/verify` responses — present only when the reporting companion's version *differs* (so rollback works for free). Publishing: `build_editor_package.ps1 -Publish [-MakeCurrent]` (admin session auth, sha256-verified streaming PUT, 409 on version reuse; every build is kept unless `?prune=1` opts into trimming to current+2). Companion side (`upgrade.py`): tray "Update available → vX — Update now" (notify + one-click, never silent) → download to the exe's own dir, sha256 verify, rename-swap (`.old` aside, cleaned next start), spawn detached, shutdown; spawn failure rolls back. Fleet grid flags `[ OUT OF DATE ]` machines; `[ COMPANION PACKAGES ]` admin box lists/flips/deletes versions. Also fixed: the reporter now reports `effective_mode()` (identity role wins over config `mode`).
- Marker-identified projects at any depth (added 2026-07-25, supersedes the fixed `Projects/<year>/<series>/<project>` depth-3 rule): a directory IS a project because it carries a hidden `.ccsync-project` marker (JSON, whose `slug` is the project's IMMUTABLE identity); containers/sub-categories (e.g. `2026/CCT/…`) nest freely, projects never nest (discovery prunes at markers). Discovery is markers-only (`provision.scan_project_dirs`; companion twin `fixer.list_project_dirs`); bare dirs are invisible until claimed. The collector's provision cycle self-heals missing markers, creates folders **with the marker's slug**, and **retargets** a folder whose marker moved on the NAS (path+label PATCH — slug-keyed rows: ticks, roots, history, media all survive). Companion side (`sync/repath.py`, v0.4.0): statelessly compares each selected project's local Syncthing folder path against `local_root/Projects/<rel>` and on mismatch pauses → moves the local dir → re-points → unpauses, BEFORE lanes run (so lane A can't resurrect the old NAS path). `/project-setup` is now an explorer-style folder browser (browse/link/create at any depth; create lays down TEMPLATE_FOLDERS + marker; link adopts bare folders or existing marker identities). CLI: `setup_tree.py --project-rel-path`, `write_marker.py` (adoption/repair with an explicit slug). Watchdog attribution uses longest-known-rel-prefix (`known_rels_fn`).
- New-project onboarding (added 2026-07-25, closes the "Resolve project with no media folder" future-work item above): the report response carries a conditional `resolve_project_unmapped: "<name>"` (computed after the existing inline auto-match, so it's authoritative); the companion (`project_setup.py`) prompts once-ever per project (persisted in `state/project_prompts.json`) and deep-links to the dashboard's `/project-setup` page, with a conditional tray item as re-trigger. There, any signed-in editor can first-set an unmapped root (`project_roots.source='editor'`, first-write-wins via INSERT OR IGNORE; changing stays admin-only) or create `Projects/<y>/<s>/<p>` + the TEMPLATE_FOLDERS (dashboard `/projects` mount now rw; eager `projects` row + a 15-min deactivation grace covers the ≤5-min Syncthing provisioning gap). Login pages gained safe `?next=` deep-link redirects.
- Structure clone on tick (added 2026-07-25): before each project's lane runs, the sequencer replicates the NAS project's full directory skeleton locally — including empty folders (`rclone lsf --dirs-only -R` + mkdirs, `rclone_lane.clone_directory_tree`). Needed because lane B copies proxy *files* only and lane C's editor-side .stignore drops video/Proxy, so empty scaffolding never arrived otherwise. Idempotent; picks up server-side folder additions each pass.
- Per-editor selection + sequenced sync (added 2026-07): editors log into the dashboard with TrueNAS credentials (SMB auth probe on :445 — the only verification 25.10 permits for non-admin users) and tick projects; the `selections` table (schema v2) + a 60s `enforce` collector cycle drive Syncthing folder shares (tick = share to the editor's devices, untick = unshare; unmapped devices never touched; first run seeds from pre-existing shares). New folders provision **unshared**. The companion in managed mode (`dashboard_url` set) fetches its selection and a Sequencer syncs projects **one at a time in tick order**: per project lane A run → lane B run → lane C turn (only the current folder unpaused locally; others paused; auto-accepts pending folders with editor-side .stignore), rotating after `project_rotation_seconds` (600) to prevent starvation; all selected folders unpause between passes. Live progress: rclone `--stats` JSON → LaneStatus (bytes/speed/ETA) via the companion report, and a server-side EMA of Syncthing needBytes drain → per-editor speed/ETA on the dashboard.

## Flaws / holes you asked me to flag

1. **Lag window**: editor adds video → other editors see it offline until upload + proxy-gen + proxy-download complete (minutes to hours for big files). Inherent to originals-up/proxies-down; companion tray shows queue so it's at least visible.
2. **Deletes & renames**: lane A never deletes on NAS (archival safety) — so folder reorganizations must happen **on the server side (host)** or stale copies accumulate; lane B mirrors server exactly (renames propagate down); lane C propagates deletes but server keeps versioned trash. This asymmetry is a rule editors must know.
3. **Same-name collisions**: two editors dropping different `track.mp3` into `Audio\Music` → Syncthing conflict-copies (surfaced in tray); on lane A skip-if-exists + warn.
4. **BRAW proxying depends on your PC being on** (BPG). WOL + optional NAS ffmpeg fallback mitigates.
5. **Postgres over WAN**: bin/timeline ops are latency-sensitive; fine on direct Tailscale, painful via DERP — the bootstrap must verify direct connectivity per editor.
6. **Shared upstream**: every editor's proxy download rides the HiNet upstream simultaneously; benchmark establishes the real ceiling.
7. **Mapped Mount on Mac is manual** Resolve preference — can't be set via scripting API; companion detects misconfiguration but a human does the one-time fix.

## Milestones

1. **Infra**: Tailscale re-auth + direct-path check; `Creators_Club` tree + editor accounts; Postgres over tailnet verified from a second machine.
2. **Proxy pipeline**: BPG watch folder on host PC; end-to-end test that a BRAW + FX3 MP4 auto-link their generated proxies in Resolve on a machine *without* the originals.
3. **Benchmark**: harness + pick per-lane transports (beat 60 mb/s or know why not).
4. **Companion v1**: lanes + tray + timeline watcher + move-and-relink popup; test on this PC with a simulated editor root.
5. **Pilot**: one real remote editor through the bootstrap; fix what breaks; write docs.

## Execution model (as directed by the admin)

Orchestrated build: I act as orchestrator — `builder` subagents implement the components (server setup scripts, companion, benchmark harness, installer) from detailed briefs; I review every diff they produce, run the tests myself, and do the integration/verification passes inline. Parallel tracks only where genuinely independent (e.g. companion vs benchmark harness); infra work on the NAS stays inline since it touches live systems.

## Verification

- **M2**: open test project on a second Windows login/machine with only the synced tree → all video clips play via proxy, no manual relinking.
- **M4 local rig**: `C:\Creators_Club` as fake editor root on this PC (Syncthing + rclone lanes against the NAS over LAN): drop an MP3 into `Audio\Music` → appears on NAS same path; add a Desktop file to a timeline → popup → Fix → file lands in tree, clip relinked, uploaded; add a local .braw → uploads, proxy appears back within one BPG cycle.
- **M3**: benchmark table artifact committed to repo; chosen config recorded.
- **M5**: remote editor opens the shared project, edits with proxies, adds media; host sees it in the right folder and in the same bins; measure their real up/down and compare to Resolve Cloud's 60 mb/s.
