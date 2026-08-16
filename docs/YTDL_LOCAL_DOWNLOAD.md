# Requester-first downloads for the YouTube downloader

Status: **phases 1 + 2 SHIPPED 2026-08-15** (commit `5ab221d`; approved and
built 08-14 by five builder agents, orchestrator-reviewed). **It went out as
companion 0.7.8 / installer 1.0.27, NOT the 0.8.0 this document was written
against** — every "0.8.0" below means "the build that carries the local
executor", which is 0.7.8 and later. The dashboard/ytdl-web half rode
`ship.cmd` step 1 the same day, so both sides are live. SPEC.md still needs
its short section pointing here.

Windows editors get this when their tray takes the upgrade; **macOS editors
do not have it at all** until the Mac builds run on a Mac.

**2026-08-16 — it had never engaged, and two things had to change for it to.**
Read on ruskin's box the morning after he took 0.7.8: every job still
`download_mode: server`, `claimed_by: null`. Two independent blockers, both
invisible because the server path is the designed fallback and kept working:

1. **The flag was never set.** `YTDL_LOCAL_DOWNLOAD=1` was a deploy step in
   the ship checklist that nothing performed; `/ytdl/api/health` said
   `local_download: false`, so the SPA never probed the companion at all.
   `install_dashboard_app.py` and `dashboard/deploy/compose.yaml` now set it
   (the two are pinned equal by `server/tests/test_safety.py`).
2. **No editor machine has ffmpeg.** `/ytdl/capabilities` on his box:
   `ok:false — ffmpeg is not installed on this machine` (COMP-BROLL-5 refusing
   correctly). Nothing had ever put one there — ffmpeg was the proxy
   generator's optional dependency. Companion 0.7.9 adds `ffmpeg_manager.py`:
   a **pinned** static ffmpeg+ffprobe (eugeneware/ffmpeg-static b6.1.1,
   sha256 hardcoded per asset, verified against a real download) installed
   into the same tools dir as yt-dlp on the yt-dlp manager's daily thread,
   and `ffmpeg_tools._resolve_binary` falls back to it behind PATH for the
   bare default `ffmpeg_path`. An editor's own install still wins.

And a policy reversal in the same release: **lane B no longer pulls
`/Youtube/**` down** (owner's call, 2026-08-16). The R12 include existed
while the NAS was the only downloader; with requester-first downloads the
original starts on the requester's disk and lane A carries it up, and pulling
every editor's clips to every other editor was 58 GB of bandwidth on
ruskin's first pass. YouTube originals go **up only**. Consequences accepted:
a clip that fell back to the server path stays NAS-only (the history's
reveal now says so instead of "has it synced here yet?"), and an editor-local
original the NAS lacks is excluded rather than swept to `.ccsync-trash`
(item 22's Youtube/ case is gone). `Youtube/<term>/Proxy/` previews still
come down via `**/Proxy/**`.

As-built deviations from the prose below, all deliberate and documented at the
code site:

- The sidecar is **8 fields**, not 9 (§5 was written from memory; the vendored
  writer is the authority — `ytdl_common.SIDECAR_FIELDS`, pinned against it).
- The local executor runs **only the h264-representable rungs** (480p/720p/
  1080p — `ytdl_executor.SCOPE_QUALITIES`). `best`/2160p/1440p/audio need
  `ensure_edit_ready`'s transcode (whose `.editready.mp4` NAME the executor
  cannot reproduce) and stay server-side; an out-of-scope claim is handed back
  by letting the lease expire.
- There is **no release endpoint**: every early-out (scope, label, template
  skew) ends by stopping the heartbeat and letting the ≤180 s lease expire —
  one reclaim path instead of a second endpoint whose failure mode is a job
  nobody owns. Same mechanism finishes a completed local job: the last clip's
  status post requeues local failures, ends the lease and nudges the worker,
  whose ordinary close-out is the second-chance sweep (§2 step 7).
- `ytdl_common` also carries `QUALITY_HEIGHTS` + `format_selector`, COPIED
  from the untouchable vendored downloader and pinned equal to it by test.
- The dashboard's `login_gate` passes exactly the four fleet route shapes on
  the fleet token (per-suffix regex; browser job routes stay session-gated)
  and opens `config/ytdl-client` unconditionally (the sidecar manager reads
  it tokenless).
- The parity gate lives in `tools/release.ps1` step 1 (byte-compare below the
  vendored-content marker, fail-safe on missing/unreadable/ambiguous) plus an
  8-test section in `server/tests/test_cross_component.py`.
- macOS tools dir is the plan's `~/Library/Application Support/ccsync/tools`,
  which is NOT beside the mac install's `~/.local/ccsync/bin` — recorded in
  `ytdlp_manager.tools_dir()`; the tools dir only has to agree with itself.

Added by the 2026-08-14 bug-hunt fix pass (same one-reclaim-path philosophy):

- **CANCEL and "download on the server instead" now end a running local
  download on the spot**: both call `db.expire_lease()`, so the companion's
  next call 410s (it kills yt-dlp and clears that clip's litter) and the
  nudged worker reclaims immediately instead of waiting out the ≤180 s lease
  (YTDL-WEB-1/-2). No new endpoint — the lease stays the only reclaim path.
- The info json never touches the synced tree: `--write-info-json` writes to
  a scratch dir (`%LOCALAPPDATA%\ccsync\ytdl-info`) via a second `-o
  infojson:` template — §7's in-tree write-then-delete would have recreated
  the ignoreDelete immortality bug (COMP-BROLL-1). No scratch dir available →
  the flag is dropped and the clip lands without a sidecar, fail absent.
- `capabilities()` gates on ffmpeg actually resolving (every in-scope rung is
  a merge format), so a machine without ffmpeg never claims (COMP-BROLL-5) —
  amends §6/§11's "editor with no ffmpeg" row.
- The claim body now declares `sidecar_version` and `scope_qualities`, and the
  server 410s a skew (`reason:'sidecar_version'`) or an out-of-scope job
  (`reason:'out_of_scope'`) at claim time instead of burning a 180 s lease;
  `capabilities()` also advertises `scope_qualities` so the SPA never
  dispatches an out-of-scope job at all (COMP-BROLL-6/-10). Version floors
  rank numerically on both sides (COMP-BROLL-9).

## 1. Why

Three measured facts from the 2026-08-13/14 incident (docs/ — "The Empty
Youtube Folder" writeup) drive this:

1. **YouTube is hostile to the NAS's IP.** The fleet has already hit the
   112-metadata-call cutoff (why `CANDIDATE_CAPS` defaults to 100), ships a
   cookies.txt escape hatch, paces with `YTDL_DOWNLOAD_PAUSE`, and on
   2026-08-13 had five clips fail outright. Bulk anonymous downloads from one
   static IP is exactly the bot-check profile. Editors' residential IPs,
   each fetching only their own reviewed selections, don't fit it.
2. **The requester waited on two machines to get their own clips.** NAS
   download, then a sync hop down — and on pre-0.7.6 builds the hop didn't
   even exist. Clips born on the requester's machine make the requester's
   latency zero and reuse lane A (originals up) exactly as camera media does.
3. **yt-dlp rots.** The container's copy is fixable in one rebuild; that must
   stay true wherever the download executes — which forces the sidecar
   design in §6, and is the biggest risk this plan manages.

Non-goals: the search pipeline (Claude expansion, ytsearch, enrich, review
manifest) stays server-side, untouched. The NAS worker is NOT removed — it
becomes the fallback executor, and its recent fixes (quality-rung fallback,
id-scoped corpse cleanup) apply to both executors.

## 2. Shape

```
                    ┌─ dashboard container ──────────────────┐
  browser (SPA) ────┤ /ytdl: search, review, job rows, claims │
     │              │ worker: FALLBACK download executor      │
     │ probe        └────────────▲───────────────────────────┘
     ▼                           │ token-authed: claim / manifest /
  127.0.0.1:8899                 │ per-clip status / heartbeat
  companion loopback ────────────┘
  local download executor
     │ writes P:\Projects\<label>\Youtube\<term>\
     ▼
  editors: lane A carries originals up • base rig: P: IS the NAS
```

The browser is the only party that can see both the dashboard and the
requester's loopback, so **dispatch is browser-mediated but data never is**:
the SPA passes only a `job_id` to the companion; everything the companion
acts on comes from the server over its own authenticated channel. This is
the `/music/send` principle (never trust the page with paths) extended to
never trusting it with the work order either.

Happy path, in order:

1. Review submitted → job enters `downloading` with `download_mode=server`
   (the default; nothing regresses if every later step fails).
2. SPA probes `GET 127.0.0.1:8899/ytdl/capabilities`. Timeout 1s. Any
   failure → server path, no UI noise.
3. Capability OK → SPA tells the companion `POST /ytdl/download {job_id}`.
4. Companion → dashboard `POST /ytdl/api/jobs/{id}/claim` (fleet token).
   Server checks the lease is free and `ytdlp_version >= min_ytdlp_version`,
   flips `download_mode=local`, sets `claimed_by`, starts the lease.
   Claim rejected → companion answers the SPA "declined", SPA does nothing
   further; the server worker downloads as today.
5. Companion `GET .../download-manifest`: clip list (video_id, url, quality,
   term_dir, project label), naming template version, sidecar spec version.
6. Companion downloads into `P:\Projects\<label>\Youtube\<term>\` via path
   canon (editor: local tree; base rig: straight onto the NAS), reporting
   per-clip status + heartbeat. Server mirrors status into the job rows —
   the SPA polls the server exactly as today and cannot tell the modes apart
   except for the badge (§9).
7. Job completes → server runs the **second-chance sweep**: any clip not
   `done` is retried server-side, once, with the existing worker path. Final
   completeness is the max of both executors.

## 3. Claim, lease, reclaim

- One holder per job. `claim` is compare-and-set on `(download_mode,
  claimed_by, lease_expires_at)`; a second claim while leased gets 409.
- Heartbeat every 30s extends the lease to now+3m. The numbers are config
  (`YTDL_LEASE_SECONDS`, `YTDL_HEARTBEAT_SECONDS`) but ship as 180/30.
- Lease expiry (laptop closed, companion killed, tray upgraded mid-job) →
  server logs the reclaim, flips `download_mode=server`, and the worker
  downloads **only what's missing**. Missing = no `done` row AND no
  `[video_id]`-bearing finished file in the NAS-side term folder — the same
  id-scan the corpse cleanup uses, because on an editor machine the finished
  files arrive via lane A with the id in the name. A clip the editor half
  -downloaded leaves only `.part` litter, which both the local executor's
  failure path and (now) Syncthing's stignore keep out of everyone's way.
- Reclaim is one-way for a given job: once the server takes it back, later
  companion status posts for that job get 410 and the companion stops. No
  ping-pong.

## 4. Server additions (ytdl/web)

Schema (one migration, all additive):

- `jobs.download_mode` TEXT DEFAULT 'server' ('server' | 'local')
- `jobs.claimed_by` TEXT NULL, `jobs.lease_expires_at` TEXT NULL
- `clip_downloads.download_host` TEXT NULL ('server' | editor name) — for
  the history row and for debugging "whose IP fetched this"

Endpoints, all under `/ytdl/api`, all requiring `X-CCSync-Token` (the fleet
report token the companion already holds — NOT the browser session; these
are machine-to-machine and must work when no browser is open):

- `POST /jobs/{id}/claim` {editor, ytdlp_version, free_bytes} → 200 lease |
  403 stale yt-dlp | 409 leased | 410 job not claimable (already done, or
  mode locked server-side)
- `POST /jobs/{id}/heartbeat` → 200 | 410 reclaimed
- `GET  /jobs/{id}/download-manifest` → clip list + template/sidecar spec
  versions (§5) — leaseholder only
- `POST /jobs/{id}/clips/{video_id}/status` {state, error, quality_note} —
  leaseholder only; drives the same row updates the worker makes
- `GET  /config/ytdl-client` → {min_ytdlp_version, download_pause_seconds}
  — unauthenticated-read is fine (nothing secret), lets the fleet be forced
  onto a newer yt-dlp the day YouTube breaks the old one

Worker changes: skip leased jobs; reclaim pass on lease expiry; the
second-chance sweep at job close. The dispatch decision costs the worker
nothing — an unclaimed `downloading` job is simply worked as today, which
is the whole rollback story.

## 5. Naming parity is a contract, not a convention

Server and companion MUST produce byte-identical artifacts for the same
clip: outtmpl `%(uploader).60B - %(title).140B [%(id)s].%(ext)s`, the
9-field `.credits.json` sidecar, embedded tags, `ensure_edit_ready`'s
h264 policy, and the quality-fallback rung semantics. Divergence here is
silent data skew across the fleet — the exact class of bug the path-canon
work (R12) exists to prevent.

- Extract the template + sidecar builder + fallback-rung logic out of
  `ytdl/web/ytdlweb/vendor/downloader.py`'s CALLERS into a small
  `ytdl_common` module vendored into BOTH trees (worker imports it;
  companion vendors a copy the way installer parity files are vendored —
  `tools/release.ps1` gains a parity check, the same mechanism that already
  refuses on installer drift).
- The download-manifest carries `template_version` / `sidecar_version`;
  a companion whose vendored copy is older than the server's declines the
  claim in the capability handshake. Version skew degrades to server-side
  execution, never to divergent files.
- One cross-component test pins server output == companion output for a
  fixture clip (same style as the stignore three-way pin added 2026-08-14).

## 6. The yt-dlp sidecar (the risk that kills this if unmanaged)

The companion is a frozen PyInstaller build; yt-dlp needs updating every
few weeks. Bundling yt-dlp as a library would tie download health to the
companion release cadence — Ruskin sat on 0.4.22 for a month; that must
never mean "Ruskin's downloads are broken for a month".

- The companion manages the **standalone yt-dlp binary** (`yt-dlp.exe`,
  `yt-dlp_macos`) under `%LOCALAPPDATA%\ccsync\tools\` (mac:
  `~/Library/Application Support/ccsync/tools/`), NOT importable code.
- On tray start and then daily: `yt-dlp --version`; if older than
  `min_ytdlp_version` from `/config/ytdl-client`, run `yt-dlp -U` (its
  built-in self-updater; it handles the in-place swap on all three OSes).
  First run downloads the binary from github's release URL — over the same
  origin-checked download_and_verify machinery upgrade.py already has, with
  sha256 from the github API, free-space check first.
- Capability handshake reports the version; a stale/missing/broken binary
  = no capability = server-side path. Editors never see a broken local
  downloader — they see the old behaviour.
- ffmpeg: reuse the proxy generator's existing ffmpeg_tools resolution.
  No new binary management.

## 7. Local executor (companion 0.8.0)

Loopback additions to `broll_server.py`'s ONE listener (a second 8899
listener breaks the tray — standing rule):

- `GET /ytdl/capabilities` → {ok, editor, ytdlp_version, template_version,
  free_bytes} — computed fresh per call, 200 always (ok:false carries why),
  so the SPA probe is one round-trip.
- `POST /ytdl/download` {job_id} → 202 started | 409 already running one |
  503 declined (claim failed / capability gone). Body carries job_id ONLY.
- `GET /ytdl/progress?job_id` → local mirror for instant UI, optional for
  the SPA (server rows remain the truth).

Executor rules, all inherited from the worker's current behaviour:
one job at a time; sequential clips with `download_pause_seconds` between
(server-provided — residential pacing can be gentler than the NAS's 3s);
per-clip: download at manifest quality → on the truncated-stream signature
(persistent truncation after yt-dlp's own retries), one rung down, note
recorded — the 2026-08-14 worker fix, via the shared `ytdl_common`; on
final failure, delete own `[video_id]` `.part`/`.ytdl` litter; write
sidecar; report status. Free-space check before starting (decline the
claim, don't die at clip 40 — the 0.7.x upgrade free-space lesson).

Write destination goes through path canon (`canonical_prefix` →
`local_root`), so the same code writes to F:\ on an editor and through the
P: mapping on the base rig. The companion validates the manifest's project
label against its own selection (a project it doesn't sync = decline;
protects against a server bug pointing it outside the tree) and rejects
any manifest URL whose host isn't YouTube's.

Sync interactions (all already in place, verified 2026-08-14):

- Originals up: lane A's filter includes the video extensions anywhere
  under the project; `Youtube/<term>/` is in scope. Consider the express
  lane (`_express_inflight`) for freshly-finished clips so other machines
  see them in minutes, not at the next periodic pass — nice-to-have,
  phase 3.
- Sidecars/manifest.json travel Syncthing (not video extensions, not
  ignored). In-flight `.part`/`.ytdl` litter on the EDITOR side is now
  stignored (the 2026-08-14 six-line fix, three components in agreement) —
  prerequisite, or every editor download would leak partials fleet-wide
  exactly the way the NAS's did.
- Proxies: unchanged — base rig's proxy_gen sees the originals land on the
  NAS and generates `Youtube/<term>/Proxy/`, which lane B distributes.
- Originals: since 2026-08-16 lane B does NOT distribute them (see the
  status header). Up via lane A only.

## 8. Security

- Loopback stays 127.0.0.1-only with the existing fail-closed origin
  checks (0.7.0 hardening). New endpoints get the same treatment; the
  browser contributes nothing but a job id.
- The fleet token authenticates companion↔server; the browser session
  authenticates human actions. Neither crosses into the other's lane.
- The companion never accepts paths, URLs-to-download, or templates from
  the browser; all three come from the server manifest under the token.

## 9. UI

- Job header badge: "downloading on your machine" / "downloading on the
  server" — flips visibly on reclaim, because a silent executor swap is
  how editors conclude features are broken (the 2026-08-11 hash-pinning
  lesson).
- A per-job "download on the server instead" link (sets a server-side
  `mode_lock=server` before claim; usable when an editor is tethered/hotel
  -wifi'd). No global toggle — per-job is enough and self-documenting.
- History rows show `download_host`.

## 10. Rollout

- **Phase 0 — shipped or in tree now**: lane B `/Youtube/**` (0.7.6+;
  **reversed 2026-08-16 in 0.7.9** — originals go up only, see the header),
  stignore `*.part`/`*.ytdl` three ways, worker quality-rung fallback +
  corpse cleanup, project-select persistence. These stand alone and are
  worth shipping regardless.
- **Phase 1 — server only, flag off→on**: migration, claim/lease/manifest/
  status endpoints, worker skip+reclaim+sweep, SPA probe/dispatch behind
  `YTDL_LOCAL_DOWNLOAD` (default off). Deploy. With no companion speaking
  the protocol, behaviour is byte-for-byte today's. Flag on: still no
  change until a 0.8.0 companion exists — the probe 404s and falls back.
  This is why phase 1 is safe to soak on the live dashboard.
- **Phase 2 — companion 0.8.0**: `ytdl_common` vendoring + parity gate,
  yt-dlp sidecar manager, capabilities/download/progress endpoints,
  executor. Windows + macOS builds published (+ installer bump — standing
  rule). Editors adopt at click-speed; each machine flips itself the day
  its tray upgrades. Base rig upgrades first and becomes the pilot: its
  "local" path writes straight to the NAS, so a phase-2 bug there cannot
  strand files on a remote machine.
- **Phase 3 — tighten**: raise the NAS worker's `DOWNLOAD_PAUSE` (it is
  now the fallback, so it can afford to be slow and polite), express-lane
  fresh Youtube originals, consider retiring the cookies.txt hatch.
- **Rollback** at any point: flag off (SPA stops dispatching), or
  `mode_lock=server` per job. The third lever this list used to name — "simply
  never publish 0.8.0" — is spent: the executor shipped inside **0.7.8** on
  2026-08-15, so rollback now means the flag, the per-job lock, or republishing
  an older companion as CURRENT (the upgrade channel's version-difference rule
  makes that a first-class downgrade). No schema rollback needed; additive
  columns idle harmlessly.

## 11. Failure modes

| Failure | Behaviour |
|---|---|
| Companion absent / old / dead binary | Probe fails → server path, as today |
| Laptop closes mid-job | Lease expires ≤3m → reclaim → server downloads missing clips only |
| yt-dlp stale on editor | Claim rejected 403 → server path; sidecar self-updates for next time |
| Truncated stream (the f137 wave) | Same one-rung fallback both executors, via shared ytdl_common |
| Clip fails locally (bot check on editor IP) | Status recorded; second-chance sweep retries it server-side at job close |
| Editor disk near-full | Free-space check declines the claim up front |
| Two browser tabs / editors on one job | Single-holder lease; second claim 409s |
| Template drift server↔companion | Version handshake declines claim; parity test + release gate prevent it shipping |
| Companion crashes between claim and first clip | Same as laptop-close: lease expiry reclaims |

## 12. Test plan

- ytdl/web: lease CAS + expiry reclaim + 410-after-reclaim; sweep
  downloads-only-missing (id-scan fixture); manifest leaseholder gating;
  SPA probe/dispatch/fallback pinned in test_static_app's node harness.
- companion: executor against a fake yt-dlp binary (script that emits
  files/errors on cue — no network); claim-decline paths; path-canon
  destination on both platforms; free-space decline; litter cleanup.
- cross-component: fixture-clip parity (server worker output ==
  companion executor output, byte-for-byte names + sidecar).
- server/: none — this feature doesn't touch NAS provisioning.

## 13. Open questions (decide during phase 1 review)

1. Express-lane fresh Youtube originals in 0.8.0 or defer? (Costs little,
   but 0.8.0 is already large.)
2. Should `min_ytdlp_version` live in the dashboard admin UI or config
   file only? (Plan assumes config-only first.)
3. Per-editor opt-out (an editor on metered upload may prefer server
   downloads always) — config key in the companion, or dashboard-side
   preference? (Plan assumes companion config key, absent = opted in.)
