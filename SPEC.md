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

**Path canon:** one virtual drive letter on Windows — `P:`. Host/Alex: `P:` → `\\192.168.0.102\TheCreatorsPool\Creators_Club` (SMB). Editors (Win): `subst P: C:\Creators_Club` at login. Editors (Mac): local root `~/Creators_Club` + Resolve **Mapped Mount** preference translating to `P:` paths (one-time documented setup; companion verifies it by checking timeline clip paths resolve). All DB-stored paths are `P:\Projects\...` → identical everywhere.

**Proxy generation:** **Blackmagic Proxy Generator on Alex's PC** watching `P:` (per-project watch folders). It natively handles BRAW (ffmpeg cannot decode .braw), is GPU-accelerated, preserves timecode, and writes to the in-place `Proxy/` subfolder convention — exactly what Resolve auto-links, and what the template tree already uses. Output: H.264 1080p (cross-platform safe; revisit H.265 later). NAS-side ffmpeg fallback container is a later nice-to-have for non-BRAW formats when the PC is off (PC has wake-on-LAN anyway).

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

## Execution model (per Alex)

Orchestrated build: I act as orchestrator — `builder` subagents implement the components (server setup scripts, companion, benchmark harness, installer) from detailed briefs; I review every diff they produce, run the tests myself, and do the integration/verification passes inline. Parallel tracks only where genuinely independent (e.g. companion vs benchmark harness); infra work on the NAS stays inline since it touches live systems.

## Verification

- **M2**: open test project on a second Windows login/machine with only the synced tree → all video clips play via proxy, no manual relinking.
- **M4 local rig**: `C:\Creators_Club` as fake editor root on this PC (Syncthing + rclone lanes against the NAS over LAN): drop an MP3 into `Audio\Music` → appears on NAS same path; add a Desktop file to a timeline → popup → Fix → file lands in tree, clip relinked, uploaded; add a local .braw → uploads, proxy appears back within one BPG cycle.
- **M3**: benchmark table artifact committed to repo; chosen config recorded.
- **M5**: remote editor opens the shared project, edits with proxies, adds media; host sees it in the right folder and in the same bins; measure their real up/down and compare to Resolve Cloud's 60 mb/s.
