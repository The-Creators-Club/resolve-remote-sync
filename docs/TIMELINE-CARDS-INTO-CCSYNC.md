# Timeline Cards into CC Sync — the agent into the companion, the page into the dashboard, and the jobs across the fleet

Investigation and plan, 2026-08-29. Status: **NOT BUILT, NOT DECIDED.** Nothing
in this document has been implemented; §7 is the list of things the owner has
to choose before phase 0 can start.

Written from a read-only pass over both trees on the base rig. Facts are cited
`file:line` on both sides; where CC Sync has no concept for something this
plan needs, it says so rather than inventing one.

Related here: `docs/ARCHITECTURE.md` (the stranger's map), `docs/GOTCHAS.md`
§15 (CR-68, the script server) and §16 (the library walk),
`docs/YTDL_LOCAL_DOWNLOAD.md` (the only fleet job model this repo has),
`docs/BROLL_INGEST_PLAN.md` §3.2 (per-machine ingest state),
`docs/MULTI_MACHINE_PLAN.md` (the machine is the unit, not the person),
`docs/LIBRARY_WALK_PLAN.md`, `SPEC.md`.

Related over there:
`E:\Projects\Editing\Resolve\MulticamPipeline\docs\LAYOUT.md`,
`docs\TRUENAS-APP-PLAN.md`, `docs\REORDER-PLAN.md`,
`docs\PROJECT-FORMAT-PLAN.md`, `README.md` "On the NAS".

---

## 1. What each system is today

**CC Sync.** One FastAPI dashboard in a container on the TrueNAS
(`dashboard/src/ccsync_dashboard/app.py`, 1 106 lines; `api.py` 7 968;
`db.py` 7 183; SQLite WAL at `/data/dashboard.db`), and one frozen tray
companion on every machine (`companion/src/ccsync_companion/app.py`, 8 964
lines, version 0.9.55 at `config.py:148`). The companion runs three sync
lanes, a Resolve watcher/fixer (`resolve_bridge.py`, 3 359 lines, whose
`connect()` at `:306` is the single chokepoint carrying the CR-68 guard from
`script_server.ready_to_connect()` at `script_server.py:328`), a proxy
generator gated on user idleness (`proxy_gen.py` 2 353 lines + `idle.py`), a
project-library reader added on `library-walk` (`library.py`,
`ProjectLibrary` at `:548`), and one loopback listener on `127.0.0.1:8899`
(`broll_server.py`, 2 153 lines) that the dashboard's browser pages call.
It talks to the dashboard by POSTing a report every 5-60 s
(`reporter.py:499,504`) and reading `commands` out of the reply
(`api.py:7405-7557`: halt, upgrade, resume_lane_b, diagnostics,
broll_ingest.cancel, music_ingest.cancel, file_moves, resolve_undo). The
dashboard mounts three sub-apps in-process behind its login — `/broll`,
`/music`, `/ytdl` — each tri-state and best-effort (`broll.py:398`).

**Timeline Cards.** One Python program in
`E:\Projects\Editing\Resolve\MulticamPipeline`, `reorder_web.py` as a
136-line façade over `multicam_pipeline/cards/` (`docs/LAYOUT.md` "The cards
package"). Two halves that can live on two machines: **`LibraryEngine`**
(`library_engine.py`, 2 084 lines — transcripts, folding, search,
translations, plans, notes, peaks, the WAV/Opus/480p ffmpeg queue, the served
state) and **`ResolveEngine`/`SyncEngine`** (`resolve_engine.py`, 2 862 lines
— the guarded scripting connection at 10 Hz, the sweep of the open timeline
into cards, and every edit as synthetic keystrokes), joined by **`agent.py`**
(2 023 lines: `AgentLink` on the server side, `AgentClient` on the PC side).
The browser page is a hand-rolled `BaseHTTPRequestHandler`
(`handler.py`, 938 lines, ~70 routes) serving `page/` reassembled by
`page.render_page()`. It is deployed as its own TrueNAS custom app —
`deploy/Dockerfile` (python + ffmpeg + libpq5 + node 22 + a pinned
`@anthropic-ai/claude-code`), `deploy/compose.yaml` with ~24 `CARDS_*`
variables, running as **3003:3000** with `/vault` (`/mnt/tank/web`) rw,
`/media` ro and `/data` rw. On creator-1 the same code runs as
`--agent http://truenas…:8800/`, which serves nothing and listens on nothing.

---

## 2. The seams

### 2.1 What is already companion-shaped

`ResolveEngine` + `AgentClient` are, structurally, a second CC Sync companion
already living on creator-1:

* **It carries the CR-68 guard.** `multicam_pipeline/resolve/resolve_script_server.py`
  is a copy of `companion/src/ccsync_companion/script_server.py` — same
  `READY`/`STARTING`/`ABSENT` classify, same `is_starting()` at `:323` and
  `ready_to_connect()` at `:328`, same Windows-ctypes/macOS-lsof split.
  GOTCHAS §15 tells every other Resolve client to make exactly that copy.
* **It has no listener.** `AgentClient.push_loop` (`agent.py:1873`) POSTs
  `/agent/state`; `pull_loop` (`:1935`) long-polls `/agent/pending?wait=25`
  (`config.py:67`); `_result` (`:1999`) POSTs back with five retries. That is
  the same posture as `reporter.py` — outbound only, never forwarded to.
* **Its work items are already typed and idempotent-ish.** `agent_job`
  (`agent.py:200`) dispatches `kind` ∈ edits / `conform` / `release` /
  `reload`, with an explicit refusal matrix in the docstring, and
  `_apply_one` (`:1959`) returns `{ok, note, error, inserted_uid, conformed,
  renamed}`.
* **It advertises machine facts.** The `/agent/state` body carries `name`,
  `tl_id`, `tl_fps`, `clips`, this machine's Resolve keyboard preset
  (`keys: lane_keys()`) and `db: {info, project}` — which is a capability
  report by another name.

### 2.2 What is already dashboard-shaped

* `LibraryEngine` needs only PostgreSQL, the vault and ffmpeg. The PostgreSQL
  it needs **is already a service in CC Sync's own stack** —
  `dashboard/deploy/compose.yaml:660` runs `postgres:13` under the
  `project-server` profile, with the comment "postgres:13 is what DaVinci
  Resolve's project server expects".
* `handler.make_handler` + `page.render_page()` are a self-contained web app
  with its own state polling — the same shape `/broll` and `/music` have.
* The project files (`.cut.md`, `docs/PROJECT-FORMAT-PLAN.md`) and the plans
  (`Script Docs\timeline_plans.json`, `timeline_plans.history.jsonl`) are
  server-side documents shared by every device. That is dashboard data.
* The `.cut.md` engines (`project_engine.py` 1 032, `project_edit.py` 352,
  `project_conform.py` 884, `cutlist.py` 929) touch neither Resolve nor the
  vault caches.

### 2.3 What is neither

* **The caches in the vault.** `Script Docs\remote_audio\` (Opus copies),
  `…\remote_audio\source\` (m4a/ogg extractions and `*.480p.mp4` proxies),
  peaks, `card_translations.json`, `gt_translations.json`. They live in the
  media tree, are written by whichever half serves the page, and have their
  own merge-on-save discipline. CC Sync has no notion of a derived-artefact
  cache inside the tree: everything under the tree is either an original
  (lane A), a proxy (lane B) or a small file (lane C), and these are none of
  the three.
* **`cards_pick.json` / `cards_mirror.json` / `cards_ui.json`** — per-server
  UI state under `DATA_DIR` (`config.py:51,81,114,158`). Singleton files with
  no owner, no schema and no migration. The dashboard has a settings table
  and a schema version; these have neither.
* **The single-worker ffmpeg queue.** `LibraryEngine._src_worker`
  (`library_engine.py:1452`): one thread, audio strictly before video,
  in-memory `_src_q`/`_vid_q`/`_src_fail`, no persistence, no cross-machine
  anything. It exists precisely because "the NAS must never run dozens of
  ffmpegs because a lane opened". This is the piece the whole fleet-job idea
  is meant to replace, and it is also the piece with no equivalent on the CC
  Sync side to inherit from.

---

## 3. The port, module by module

### 3.1 The companion gains a `timeline_cards` role

**One process, one Resolve client.** This is not negotiable and it is the
single largest constraint in the plan: `README.md` "On the NAS" already says
*"Do not run this PC's own `reorder_web.py 8800` and the agent at the same
time — one Resolve client at a time"*, and GOTCHAS §15 says one unguarded
poller kills scripting for every client on the machine. So the agent cannot
run *beside* the companion on creator-1 in the finished state; the companion
must **absorb** it.

What that means concretely:

| Timeline Cards module | Where it lands | Note |
|---|---|---|
| `resolve/resolve_script_server.py` | **deleted** | the companion's `script_server.py` is the one copy; `resolve_bridge.connect()` (`:306`) is the one chokepoint |
| `cards/resolve_engine.py` `ResolveEngine` | `companion/src/ccsync_companion/timeline_cards.py` (new) | must move onto `resolve_bridge`'s `_API_LOCK` (`resolve_bridge.py:50`) — see the risk below |
| `cards/agent.py` `AgentClient` | folded into the new module, or replaced by the report channel (§3.3) | |
| `cards/keys.py` `lane_keys()` | new module | reads Resolve's keyboard preset on this machine |
| `cards/agent.py` `run_agent` / the `.cmd` launchers | **retired** | phase 2 |

**The lock is the hard part.** Timeline Cards' engine sweeps at
`POLL_FULL = 1.0` s with playhead reads at `POLL_FAST = 0.1` s
(`config.py:53,60`). The companion's watcher polls every 3 s and takes
`_API_LOCK` through `bridge_call()` (`resolve_bridge.py:110`) with a wedge
warning at `BRIDGE_WEDGE_SECONDS`. Two schedulers, one lock. The good news is
that `LIBRARY_WALK_PLAN.md` already fixed the symmetric problem in the other
direction: the companion's 11-14 s API walk is what made Timeline Cards' card
click take 7 s, and the library walk removed it. The merged process should
sweep the timeline **from the library** (`library.ProjectLibrary.timeline_items`)
and reserve `_API_LOCK` for the fingerprint (3 cheap calls) and for edits.

**Idle and capability reporting come free.** `idle.py`'s
`seconds_idle() -> Optional[float]` with its "None means cannot tell means
not idle" contract, and `proxy_gen`'s demotion while Resolve is running
(`proxy_gen_skip_while_resolve_running`), are exactly the gates a fleet job
runner needs, already written and already tested with injected seams.

### 3.2 The dashboard gains the page and the engines

Mount it the way `/broll` and `/music` are mounted — in-process, behind
`login_gate`, tri-state, never fatal (`broll.py:398` is the template; the
three rules are in `ARCHITECTURE.md` §4). Call it `/cards`.

Three things have to be solved that b-roll and music did not have to:

1. **The handler is not ASGI.** `handler.make_handler` is a
   `BaseHTTPRequestHandler` with ~70 hand-dispatched paths
   (`handler.py:139-908`) and its own Range/gzip code. Mounting it needs
   either a WSGI/ASGI shim (`a2wsgi`, one dependency, keeps the routes byte
   for byte) or a rewrite to an `APIRouter`. Recommendation in §7.
2. **Frontend URLs must be document-relative.** `broll/web` and `music/web`
   each carry a test pinning this (`test_mounted_prefix.py`) because a
   root-relative `/api|/media|/static` breaks under a prefix. Timeline Cards'
   page is full of absolute `/api/...` — every one of the ~70 routes and
   every fetch in `page/01-state.js`..`08-places.js`. This is a real,
   mechanical, boring day of work, and it is the single most likely thing to
   be skipped and then discovered live.
3. **The mounts the dashboard does not have.** Today its container mounts
   `{{NAS_TREE_ROOT}}/Projects:/projects:rw`, the b-roll archive, music data
   and its own `/data` (`dashboard/deploy/compose.yaml:416-470`). It does
   **not** mount the vault (`/mnt/tank/web`), and it does not mount the
   footage share. Both are required (`CARDS_VAULT_HOST` → `/vault`,
   `CARDS_MEDIA_HOST` → `/media:ro` plus `CARDS_MEDIA_MAP`, which is useless
   without the other). And the uid differs: the dashboard runs
   `{{APP_UID}}:{{APP_GID}}` = 3000:3001, Timeline Cards runs 3003:3000
   because `tank/web` is Alex's and files it writes should look like his SMB
   writes (`TRUENAS-APP-PLAN.md` §0.1). Merging means one of: chown the
   vault, add `group_add`, or accept that the page's writes are owned by the
   dashboard user.

**ffmpeg**: the dashboard already has it — a static build mounted read-only
at `/opt/ffmpeg` and prepended to PATH (`dashboard/deploy/run.sh:291-318`),
provisioned by `server/install_dashboard_app.py`. Timeline Cards' `ffmpeg_path()`
looks on PATH first, so this just works.

**Claude**: the two systems made opposite decisions and this needs a ruling.
Timeline Cards shells out to `claude -p` and **bundles** the CLI in its image
(`deploy/Dockerfile:55-125`, node 22 + `@anthropic-ai/claude-code` pinned to
2.1.251), authenticated by `CARDS_CLAUDE_OAUTH_TOKEN`. CC Sync deliberately
removed `/opt/claude` — "the two AI calls use the anthropic SDK with the
customer's `ANTHROPIC_API_KEY`, so there is no subprocess, no binary to put
on PATH, and no need for a writable HOME"
(`dashboard/deploy/run.sh:311-316`), because bundling the CLI was
`COMMERCIAL_READINESS.md` item 1. The bridge already exists:
`ai_providers.py` has a `claude_code` CLI adapter behind the site feature flag
`[features] ai_cli_providers` (ships OFF), with `cli_tools.py` fetching the
CLI at an admin's click into the customer's own data volume. So: **route the
three Claude features through `ai_providers`**, not through a bundled binary.
`library_engine._run_claude` (`:881`) and `_run_claude_json` (`:914`) are the
only two call sites; `claude.py` is 67 lines.

### 3.3 The `/agent/*` protocol on CC Sync's channel

There are three options and they are not equally good.

**(a) Tunnel it — keep `/agent/state`, `/agent/pending`, `/agent/result`
verbatim under `/cards/agent/*`, authenticated by the fleet credential.**
The companion already holds `X-CCSync-Token` + a signed `X-CCSync-Identity`
and uses them on the ytdl fleet routes (`ytdl/web/ytdlweb/routes_fleet.py:374`
`claim`, verified server-side by `require_fleet_caller` — note the H5
comment: the *verified* name, never `body.editor`). `CARDS_TOKEN` disappears;
`app.py:562-564`'s existing `login_gate` carve-out regex for fleet routes is
the precedent. Cheapest, and it keeps the long-poll.

**(b) Put it on the report channel.** `commands.timeline_cards` alongside
`commands.file_moves` and `commands.resolve_undo` (`api.py:7533,7557`).
Correct-shaped, and wrong: the report cadence is 5-60 s
(`reporter.py:499,504`) and Timeline Cards' interactive latency budget is
`AGENT_WAIT_S = 25` s for the poll but ~0.3 s for a card click. A keystroke
edit that takes up to a minute to reach Resolve is not the product.

**(c) Loopback.** The browser is on the editor's own machine, so the page
could call `127.0.0.1:8899` for edits the way b-roll's "Send to Resolve"
does. But the phone is *not* on creator-1, and the phone case is half the
reason the NAS page exists.

**Recommendation: (a) for the interactive path, (b) for the fleet jobs.**
Two channels with two latency budgets, each honest about which it is.

---

## 4. The fleet job model

**CC Sync has no general job concept.** It has exactly one specific one — the
ytdl download lease — and two per-machine ingest state blocks. Say that
plainly before designing on top of it.

What exists:

| Piece | Where | What it gives |
|---|---|---|
| lease/claim/heartbeat | `ytdl/web/ytdlweb/db.py:653` `claim_next_job`, `:780` `claim_download`; `routes_fleet.py:374` claim, `:515` heartbeat, `:542` manifest, `:654` per-item status | compare-and-set claim, `claimed_by` + `claimed_machine` + `lease_expires_at`, expiry reclaim, one-way `mode_lock` fallback to the server |
| per-machine progress | `machine_state.ingest_*` (`db.py:379-390`) and `music_ingest_*` (`:411-421`), 12 + 11 flat columns | the fleet grid's `[ INDEXING B-ROLL: 12/40 ]` and `[ VRAM ]` chips |
| capability probe | `broll_vlm/local_runtime.py:929` `_nvidia_smi` → `GpuInfo(present, vram_gb, name)`; `broll_vlm_sidecar.gpu()` `:157`, `fits()` `:206`; served at `broll_server.py:990` | GPU + VRAM, **on the loopback only** |
| idleness | `idle.py` `seconds_idle()`; `proxy_gen`'s idle gate and Resolve-running demotion | measurable today |
| machine identity | `machine.py` (uuid4 in `~/.ccsync/machine.json`), `machines` table (`db.py:708`), `db.adopt_renamed_machine` | a stable per-machine key |

What does **not** exist and has to be built:

* **A `jobs` table in the dashboard.** No generic queue. Nothing in
  `db.py`'s 34 tables is one.
* **A capability report.** `_nvidia_smi`'s answer never reaches the
  dashboard — `reporter.py` has no `gpu`, `vram`, `capabilities` or anything
  like it (grep is empty). The dashboard learns about VRAM only as a *refusal
  string* in `ingest_warning`.
* **Any scheduler.** Every existing dispatch is either browser-initiated
  ("this machine, because I clicked here") or requester-first ("whoever asked
  for it claims it"). Nothing has ever chosen a machine.

### 4.1 A job

```
job = {
  id, kind, created_at, created_by, priority,
  inputs:   { ... paths as the FLEET spells them ... },
  requires: { gpu_vram_gb: 6, resolve_project: "…", mount: "vault", claude: true },
  cost:     { seconds_estimate, bytes_out_estimate },
  state:    queued | claimed | running | done | failed | abandoned,
  claimed_by, claimed_machine, lease_expires_at, attempts, last_error,
  result:   { paths written, note }
}
```

**Paths are the interesting field.** CC Sync's whole premise is that the tree
is spelled the same everywhere — `P:\` on Windows by explicit decision
(`ARCHITECTURE.md` §1). The vault is not in that tree: it is `X:\` on
creator-1, `/vault` in the Timeline Cards container, `\\192.168.0.102\web`
on the wire. And the footage share needs `CARDS_MEDIA_MAP` to be usable at
all — "either alone does nothing" (`compose.yaml:91`). So a job's inputs must
be **(root-name, relative-path)** pairs — `("vault", "Vault/2026/FF5/Civil
Defence/Script Docs/…")` — resolved per machine by the claimant, never
absolute paths on the wire. This is the same discipline
`POST /music/send` already follows: "The body is `{action, share, rel_path}`,
never a path" (CLAUDE.md).

### 4.2 Kinds

| kind | needs | today | after |
|---|---|---|---|
| `whisper` | GPU ≥ ~6 GB VRAM (large-v3, float16 — `resolve_multicam_whisper.load_model:206`), the faster-whisper venv, the WAV readable | creator-1 only, by hand, `pipeline.py resolve-multicam-whisper` | any GPU machine that is idle |
| `proxy-480p` | ffmpeg, media share readable | the NAS container's single worker (`library_engine._vid_make:1637`) | any idle machine with the share; nvenc where present |
| `audio-extract` | ffmpeg, media share readable | same single worker (`_src_make:1490`) | NAS by default (it is I/O bound and fast), any idle machine under load |
| `peaks` | ffmpeg + the WAV | NAS (`_peaks_make:1171`) | NAS or idle |
| `claude-run` (translate / semsearch / summary) | a Claude credential | whichever machine serves the page (`_run_claude:881`) | any machine with a credential, via `ai_providers` |
| `conform` | Resolve **or** library write allow-list | agent keystrokes, or the NAS writing rows | unchanged: pinned |
| `resolve-edit` | Resolve open on **that** project, unlocked interactive session | agent only | unchanged: pinned |

The last two rows are the ones that must never become schedulable. Every edit
is a synthetic keystroke into whatever Resolve has open on that one machine
(`agent.py:200`'s matrix; README: "a locked screen or a disconnected RDP
session blocks synthetic input"). A scheduler that "helpfully" moves an edit
to an idle machine has moved it to the wrong timeline.

### 4.3 Capabilities

Add one section to the companion's report — the same way b-roll ingest added
one (`BROLL_INGEST_PLAN.md` §3.2) and for the same reason: flat columns, not
a JSON blob, because the grid sorts and alarms on them.

```
capabilities: {
  gpu_present, gpu_name, gpu_vram_gb,          # broll_vlm_sidecar.gpu()
  nvenc,                                        # proxy_gen._has_nvenc (:971)
  ffmpeg,                                       # shutil.which / sidecar_tools
  whisper,                                      # a venv the companion knows about
  claude,                                       # ai_providers-style availability
  resolve: {installed, running, version, project, timeline_uid, unlocked},
  mounts: ["tree", "vault", "media"],           # by ROOT NAME, not path
  cpu_count, idle_seconds, load,
}
```

`idle_seconds` must keep `idle.py`'s contract end to end: **`None` means
cannot tell means not idle**, and the scheduler must treat a machine with no
idle answer as busy. That is the difference between "we harnessed more
compute" and "we transcoded under the editor's hands".

### 4.4 Scheduling

Deliberately dumb, in this order:

1. **Filter by capability.** Hard requirements only; a machine that cannot
   run it never sees it.
2. **Filter by policy.** Not halted (`db.get_fleet_halt`), not mid-upgrade,
   lane B breaker not tripped, `idle_seconds >= job_kind_idle_floor` for the
   heavy kinds. The base rig is exempt from the idle floor by config — it is
   `mode = "base"` and nobody sits at it (`MULTI_MACHINE_PLAN.md` WP0).
3. **Rank.** Prefer nvenc for `proxy-480p`, prefer the NAS for
   `audio-extract` (it is next to the media), then least-loaded, then
   longest-idle.
4. **Offer, don't push.** Publish `commands.jobs` in the report reply and let
   the companion **claim** on a fleet route, compare-and-set, exactly as
   `claim_download` does. Two machines cannot both get it; a machine that
   dies loses its lease and the job is reclaimed. That mechanism is already
   written, already has a heartbeat, and already has a documented one-way
   fallback to the server.
5. **Retry, then pin.** N attempts, then `mode_lock`-style pinning to the NAS
   worker so a job that no machine can do does not ping-pong for ever
   (`YTDL_LOCAL_DOWNLOAD.md` §3's breaker is the precedent, including the
   hand-back-by-silence design).
6. **Results go to the vault**, which every machine shares. The job row
   records paths, not bytes. Nothing streams a proxy through the dashboard.

---

## 5. What it buys, and what it costs

**Buys.**

* **Whisper stops being a creator-1 hand-run.** Today it is
  `pipeline.py resolve-multicam-whisper` on the PC's RTX 3080, large-v3
  float16, started by a human. `docs/MONTAGE-BUILDER-PLAN.md`'s coming
  `transcribe` job makes that a per-clip demand rather than a batch, which is
  exactly when queueing it matters. Any fleet machine with a GPU that fits
  the model becomes a transcriber; ruskin's PC and leso's Mac are on the
  tailnet today (`TRUENAS-APP-PLAN.md` §0.1).
* **Proxies stop being one thread on a GPU-less box.** Measured on the NAS
  container on 2026-08-29 (2× Xeon E5-2620 v4, `libx264 veryfast` 480p,
  encode time from the container log against `ffprobe` durations of the
  finished proxies): **11–33× realtime** — a 38 s clip in 3.3 s (11×), a
  139 s clip in 13.0 s (11×), a 132 s clip in 5.0 s (26×), an 86 s clip in
  2.6 s (33×), the 484 s ETtoday 1080p package in 32.8 s (15×); the hour-long
  TFC interview ran for several minutes at ~12–15×. On creator-1 a
  `testsrc`/`mandelbrot` 1080p30 clip encoded at ~21× on the CPU
  (`MulticamPipeline/README.md`, `GOTCHAS.md` §4a); nvenc was never tried.
  For comparison, creator-1's full-quality proxy passes ran at **3.6×
  realtime** on FF2 and **6.4×** on Disinformation
  (`docs/BACKCATALOGUE_INGEST.md:83,275`) — a different, much heavier job.
  The win here is *parallelism and not blocking the lane*, not per-clip
  speed: one worker becomes N machines, and the audio extraction that the
  lane cannot play without stops queueing behind an x264 encode.
* **The NAS stops being the only place Claude runs**, and stops being the
  only place with a Claude credential.
* **One Resolve client, properly.** Absorbing the agent removes a whole class
  of CR-68 exposure: one guard, one `_API_LOCK`, one poller.

**Costs.**

* **A second Resolve client is not allowed**, so phase 2 is all-or-nothing on
  creator-1: the moment the companion carries the cards role, the standalone
  agent and the PC's own `reorder_web.py 8800` must both stop. There is no
  gradual rollout on that machine.
* **CC Sync's release cadence becomes Timeline Cards' cadence.** The
  companion is frozen with PyInstaller and shipped through the upgrade
  channel; `docs/RELEASE.md` records ruskin's PC sitting two versions behind
  for a day. A page tweak that is a browser reload today becomes a fleet
  release. This is the single biggest cultural cost of the move, and it
  argues for keeping the *page* in the dashboard (redeployable) and only the
  *engine* in the companion.
* **Two repos, two test suites.** `MulticamPipeline/tests/` (`test_handler.py`
  50/50, the golden `names.txt` re-export list, byte-identical page goldens
  with `.gitattributes` pinning `eol=lf`) versus CC Sync's cross-component
  pinning tests. The page goldens in particular will fight a mount prefix.
* **The vault becomes a dashboard dependency**, with a uid question (§3.2)
  and a size question: 41.9 GB / 38 430 files that the dashboard container
  currently knows nothing about.
* **The dashboard's boot contract.** "A broken or absent mount must never
  stop the dashboard booting." Timeline Cards currently *refuses to start*
  without `CARDS_TOKEN` (`deploy/run.sh:20`) and warns loudly on an
  unwritable root (`:43`). Mounted, those become tri-state, not exits.

---

## 6. Phases

**Phase 0 — a job API, and one job kind.** *Size: medium. Risk: low.*
`jobs` table + schema bump in `dashboard/src/ccsync_dashboard/db.py`; routes
under `/api/v1/jobs` modelled on `routes_fleet.py` (claim / heartbeat /
result); a `capabilities` section in the companion report and the columns to
land it in `machine_state`; a `whisper` runner in the companion behind the
idle gate. Timeline Cards is **unchanged** and calls the job API as a client.
Nothing moves. This is the phase that proves the model, and it is the one to
stop at if the answer is disappointing.
*Risk:* the companion has no whisper venv today — `sidecar_tools.py`'s pinned
static-binary pattern is the precedent for provisioning one, and it is not
small.

**Phase 1 — proxies and audio as jobs.** *Size: medium. Risk: medium.*
`proxy-480p`, `audio-extract`, `peaks` become job kinds.
`LibraryEngine.src_state`/`vid_state`/`peaks_state` enqueue instead of
appending to `_src_q`, and poll the job row. The in-process worker stays as
the fallback for "no fleet reachable" — and stays as the *only* path when the
media share is not mounted anywhere else.
*Risk:* two writers to one output path. Timeline Cards' `_src_make` already
writes `out + ".tmp"` then `os.replace`; `proxy_gen`'s rule 2 is the same
idea, stricter ("never two writers on one proxy", `.partial` excluded by
every lane filter). Adopt proxy_gen's version wholesale.

**Phase 2 — the agent role into the companion.** *Size: large. Risk: high.*
`ResolveEngine` moves onto `resolve_bridge`'s lock and guard; the sweep moves
to the library walk; `resolve_script_server.py` is deleted; the standalone
`--agent`, `Launch Timeline Cards Agent.cmd` and the launcher card are
retired. `/agent/*` moves to the fleet credential.
*Risk:* the lock (§3.1). And the four Resolve calls in the release/reload
handshake (`SaveProject`, `CloseProject`, `LoadProject`,
`SetCurrentTimeline`) **have still never run live** — `TRUENAS-APP-PLAN.md`
§0 says so twice and names `FF5lab` as the first live use. Do not port an
unexercised path and change its host in the same week.

**Phase 3 — hosting into the dashboard.** *Size: large. Risk: medium.*
`mount_cards()` on the `/broll` contract; the ASGI shim or the router
rewrite; document-relative URLs plus the pinning test; the vault and media
mounts, the uid decision; Claude through `ai_providers`; the
`timeline-cards` custom app retired and its `CARDS_*` variables folded into
the dashboard's compose. `server/backends/truenas.py:168 deploy_stack` already
creates custom apps by exactly the `midclt app.create` call the Timeline
Cards installer makes, so the deploy tooling is shared from day one.

**Phase 4 — the scheduler.** *Size: medium. Risk: medium.*
Capability match → policy filter → rank → offer. Fleet-grid chips for running
jobs, on the pattern of `[ INDEXING B-ROLL: 12/40 ]`. Backpressure, retry
budget, pinning.
*Risk:* the failure mode is invisible — a scheduler that quietly assigns
nothing looks exactly like a fleet with nothing to do. It needs an
"unschedulable, and why" view from the first commit, the way `[ VRAM ]` is
shown even with nothing running.

---

## 7. Decisions for Alex

**7.1 One repo or two?**
*Options:* move `multicam_pipeline/cards/` into `resolve-remote-sync`; or keep
the repo and vendor it as a package (`cards-web` on PYTHONPATH, as `broll/web`
and `music/web` already are).
**Recommend: keep the repo, import it as a package.** It is the pattern this
repo already has twice, it keeps the page reloadable without a fleet release,
and it keeps `pipeline.py`'s other twenty commands where they belong. Revisit
only if the engine and the companion start sharing code weekly.

**7.2 Where does the job queue live?**
*Options:* `dashboard.db` (SQLite WAL); the vault as files; the FF5 PostgreSQL.
**Recommend: `dashboard.db`.** The lease pattern, the migration discipline
and the invariant checker are all already there, and the ytdl queue proves
the shape works on this box. The vault is a shared filesystem with no
compare-and-set — a claim written as a file is a race with no primitive to
lose it safely.

**7.3 Long-poll or report channel for edits?**
**Recommend: both, split by latency** — §3.3 (a) for `/cards/agent/*`,
(b) for jobs. Do not make a card click wait on a 60 s report.

**7.4 Does the phone page stay a separate origin?**
*Options:* `truenas…:8800` as now; or `dashboard/cards` behind the dashboard
login.
**Recommend: behind the dashboard login, eventually — but not in phase 3.**
The dashboard's session cookie is real auth, which is strictly better than
`?key=…` in a URL, and it removes `CARDS_KEY` entirely. But it also means
every phone must sign in to CC Sync before it can stage a cut on the sofa,
and it means the page's ~70 absolute URLs must all be relative first. Ship
phase 3 with the mount serving on both origins, cut the old one over when the
prefix test is green.

**7.5 Two project-library readers, or one?**
Right now `companion/src/ccsync_companion/library.py` (`ProjectLibrary:548`,
one project, live paths, the zstd `Clip` blob) and
`MulticamPipeline/multicam_pipeline/library/library_reader.py`
(`LibraryReader:394`, every library, markers, frame-rate decode,
transcription blobs, plus a writer) read the same `Sm2*` tables with two
independent implementations, and `LIBRARY_WALK_PLAN.md` cites the cards tree
as its own reference implementation.
**Recommend: one reader, in the companion package, and the cards tree imports
it.** Two decoders of an undocumented protobuf-in-zstd blob is one decoder
too many, and the traps list in GOTCHAS §16 is written once.

**7.6 Claude: bundled CLI or `ai_providers`?**
**Recommend: `ai_providers`.** It is a two-call-site change
(`library_engine._run_claude:881`, `_run_claude_json:914`), it respects
`COMMERCIAL_READINESS.md` item 1, and it drops node + 190 MB from an image
that would otherwise have to be built for the dashboard too.

---

## 7a. PHASE 0 BUILT (2026-08-29/30)

Status of the document above: §1-§5 and §7 are unchanged. §6's phase 0 is
**built** on branch `timeline-cards-port`; phase 1's ccsync half followed on
2026-08-30 and is §7b. Timeline Cards
itself is untouched -- it is a CLIENT of this API and calls nothing yet.

### What exists now

| Piece | Where |
|---|---|
| the `jobs` table (schema **v41**) + lease helpers | `dashboard/src/ccsync_dashboard/db.py` -- `create_job`, `queued_jobs`, `claim_job` (the compare-and-set), `claim_next_job`, `heartbeat_job`, `finish_job`, `fail_job`, `expire_leases`, `prune_jobs`, `job_requirements_met` |
| the scheduler | `dashboard/src/ccsync_dashboard/jobs.py` -- capability match -> policy -> rank -> offer, plus `explain()` |
| the routes | `api.py`: `POST/GET /api/v1/jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/why` (admin session); `POST /jobs/claim`, `/jobs/{id}/heartbeat`, `/jobs/{id}/result` (fleet token + signed identity). Carve-outs in `app.py`, per suffix |
| the offer channel | the report reply's `commands.jobs = {offered:[ids]}` |
| capabilities (schema **v42**) | `companion/src/ccsync_companion/capabilities.py` -> the report's `capabilities` section -> sixteen flat columns on `machine_state` -> `db.machine_capabilities` |
| root mapping | `companion/src/ccsync_companion/job_paths.py` -- `tree`/`vault`/`media`, `resolve(cfg, root, rel_path)` |
| the runner | `companion/src/ccsync_companion/jobs_runner.py` -- claim, run `pipeline.py transcribe`, heartbeat every 30 s, post the result |
| the fleet grid | `[ GPU 10G ]`, `[ WHISPER ]`, `[ WHISPER: JOB 12 ]` |
| submit / list / why / watch | `tools/jobs.py`, documented in `docs/API.md` §6c |
| config | `jobs_*` keys, `docs/CONFIG.md` §3 |

Tests: `dashboard/tests/test_jobs.py` (the table, the lease, two claimants,
expiry/reclaim, retry->abandon, the offer filter, `why`, the routes),
`dashboard/tests/test_capabilities_report.py`,
`dashboard/tests/test_jobs_contract.py` (**the wire between the two
deployment units**, the way `test_packages.py` pins the release record),
`companion/tests/test_capabilities.py`, `companion/tests/test_jobs_runner.py`,
`tools/tests/test_jobs_cli.py`.

### How to submit one

```
python tools/jobs.py submit --kind whisper --root vault \
    --rel "Vault/2026/FF5/Civil Defence/Youtube/Interview 3" \
    --episode "Vault/2026/FF5/Civil Defence" --watch
python tools/jobs.py why 12        # "unschedulable, and why", per machine
```

The receipt already says whether anything can run it. A queue that never
moves is the failure mode of every scheduler, and `why` is how it is told
apart from a fleet with nothing to do.

### Decisions this build made, that the plan left open

* **Flat `jobs_*` config keys**, not a `[timeline_cards]` TOML table: every
  other feature in `config.py` is flat (`broll_ingest_*`, `proxy_gen_*`), and
  one table would be the only place in that file where a key's name depends
  on where it sits.
* **A running job is NOT killed when the editor returns.** proxy_gen kills
  ffmpeg in ~2 s because a proxy costs seconds and resumes trivially; a
  whisper pass is minutes of GPU work that resumes from nothing. No NEW job
  is claimed while somebody is at the machine, which is the half that
  protects them. A fleet halt does stop a running one.
* **An expired lease counts as an attempt**, so a machine that claims and
  dies three times is not re-offered the same job for ever.
* **`POST /api/v1/login` returns the caller's own `csrf` token**, so a
  non-browser client can use the session write routes. The alternative was
  exempting them from CSRF, which is the wrong direction.
* **Resolve's version, timeline uid and unlocked flag are NOT reported.**
  Every one needs a scripting call, and a capabilities probe on a 30 s cadence
  must never be the thing that calls `scriptapp()` (CR-68). The two kinds
  that would need them are pinned and unschedulable anyway.
* **`claude` is reported but nothing schedules on it** (an env key or a
  binary on PATH). Decision 7.6 stands: the answer that will matter is the
  dashboard's `ai_providers`.

### What is NOT there yet

* **No second job kind.** `proxy-480p`, `audio-extract` and `peaks` are
  phase 1 and were built on 2026-08-30 (§7b); `claude-run` is not built;
  `conform` and `resolve-edit` are pinned for ever (§4.2).
* **No ranking worth the name.** Priority then age, and every capable idle
  machine is offered the same job -- the compare-and-set sorts it out. (Phase
  1 added the rank, as a 60 s grace period rather than a filter: §7b.)
* **No pinning fallback.** §4.4 rule 5's "then pin it to the NAS worker" is
  not built: a job past its retry budget is `abandoned` and visible, not
  handed to a server-side executor (there is no job executor in the
  container).
* **No admin page.** The queue is `tools/jobs.py` and the API; the fleet grid
  shows a chip for a job in flight and nothing else. No cancel route either
  -- an admin's lever today is the fleet halt.
* **No provisioning of the whisper venv.** `sidecar_tools.py`'s pinned
  static-binary pattern is the precedent and it is not small (§6's own risk
  note). Today a machine either has the venv and the checkout, or reports no
  capability.
* **Timeline Cards is unchanged** and calls none of this.
* **Nothing is deployed.** No dashboard deploy, no companion publish. The
  companion is bumped to 0.9.56 with `REQUIRES_DASHBOARD = 0.7.18` (dashboard
  0.7.18), so the release machinery already knows the dashboard must go
  first -- and it must: a 0.9.56 companion sends a section only v42 can
  store.

### What Alex has to do before any of it runs

1. **Deploy the dashboard (0.7.18) before publishing the companion.** The
   version floor enforces it, but the order is the rule either way.
2. **Point creator-1's `~/.ccsync/config.toml` at the two paths** --
   `jobs_whisper_python = "C:\Users\alex\tools\whisper\.venv\Scripts\python.exe"`,
   `jobs_mulcam_pipeline = "E:\Projects\Editing\Resolve\MulticamPipeline"`,
   `jobs_vault_root = "X:\\"`. Until then the fleet grid will show creator-1
   with `[ GPU 10G ]` and no `[ WHISPER ]`, and `why` will say so per machine.
3. **Decide whether an editor's machine should ever take one.** Today any
   machine with the venv, the vault and 300 s of idleness will. There is no
   per-machine opt-in beyond `jobs_enabled`.

---

## 7b. PHASE 1 BUILT, ccsync side (2026-08-30)

Status: §6's phase 1 is **built on the CC Sync side** on branch
`timeline-cards-port`. Phases 2-4 are not. **Timeline Cards itself is still
untouched** -- it is a CLIENT of this API and calls nothing yet; §7b.4 below is
the spec for the builder who makes it one.

### What exists now

| Piece | Where |
|---|---|
| three new kinds | `db.py` -- `JOB_KIND_PROXY_480P`, `JOB_KIND_AUDIO_EXTRACT`, `JOB_KIND_PEAKS`, with `JOB_KIND_LABELS` for the grid and per-kind retry budgets |
| the recipes | `companion/src/ccsync_companion/jobs_media.py` -- `MediaJob.run(kind, source, out_dir, stem)`, the argv builders, the peaks binning, rule 2 |
| the dispatch | `jobs_runner.py` -- `runnable_kinds()`, `_execute` by kind, `_execute_media`, `_media_paths`, a heartbeat thread carrying progress |
| the requirements | `jobs.default_requires(kind, inputs)`, applied by `POST /api/v1/jobs` only when the submitter sent none |
| the rank | `jobs.py` -- `fleet_facts` (five queries for the whole fleet), `rank_key`, `ranked_machines`, `first_refusal`, `RANK_GRACE_SECONDS` |
| progress (schema **v43**) | `jobs.progress` (0..1, nullable) + `cap_ffprobe`; `heartbeat_job(..., progress=)`, `clamp_progress`, `fetch_running_jobs_map` -> `{label, percent}` |
| the chip | `[ PROXY 480p: 62% ]` on the fleet grid, falling back to `[ PEAKS: JOB 31 ]` where nothing measured a fraction |
| `ffprobe` | `capabilities.py` -- its own capability, probed on `ffmpeg_tools.ffprobe_for`'s answer |
| submit / watch | `tools/jobs.py submit --kind proxy-480p --root media --rel ... --out-root vault --out-rel ...`; `watch` prints the percentage |

### The kinds, as built

| kind | requirements | idle floor | retries | preferred |
|---|---|---|---|---|
| `whisper` | the submitter's (`whisper`, `gpu_vram_gb`, `mount`) | 300 s | 3 | a GPU |
| `proxy-480p` | `ffmpeg`, `ffprobe`, `mount:[root, out_root]` | 300 s | 3 | **nvenc** |
| `audio-extract` | same | 60 s | 2 | the **base rig** |
| `peaks` | same | 60 s | 2 | the **base rig** |

`conform` and `resolve-edit` remain unschedulable and absent from
`tools/jobs.py`'s parser as well as from `JOB_KINDS`.

### Recipe fidelity, and the one deliberate difference

The argv builders reproduce `library_engine.py` line for line and
`companion/tests/test_jobs_media.py` pins each one verbatim. THE ONE CHANGE IS
`-f`: Timeline Cards writes `out + ".tmp.m4a"` and lets ffmpeg pick its muxer
from the extension, and this writes `out + ".partial"` -- the suffix every
sync lane in this repo already excludes in both directions -- which has no
extension ffmpeg knows. `-f ipod` is exactly what `.m4a` resolves to and
`-f mp4` exactly what `.mp4` does; both were measured BYTE-IDENTICAL against
the Timeline Cards command on 2026-08-30. The ogg differs only in its random
Ogg stream serial, which the muxer re-rolls on every run of any argv at all.

nvenc is the phase-1 win: `-c:v h264_nvenc -preset p4 -cq 26` replaces
`-c:v libx264 -preset veryfast -crf 26` and NOTHING ELSE changes -- the GOP,
the scale filter, the pixel format, the audio and the faststart are identical,
so the page cannot tell which machine made a file.

`.peaks` is the one output that must be byte-identical rather than merely
equivalent, because the page reads it as raw bytes: `b"PK"`, the rate byte
(200), a zero, then one byte a bin. The rate byte is what makes a rate change
survivable, and both the numpy and the `array` branch produce the same bytes,
including at -32768 where the arithmetic exceeds 255.

### Rule 2, adopted wholesale

`proxy_gen`'s "never two writers on one proxy", applied to all three recipes:
every output is written as `<final>.partial`, claimed in a process-wide set
keyed on the OUTPUT path (normcased), and moved with `os.replace` only after
RE-CHECKING that no finished file has appeared meanwhile. The fleet lease
stops two MACHINES claiming one JOB; what it cannot stop is a Timeline Cards
server making the same file locally at the same moment, which is exactly the
shape lane B + the Blackmagic Proxy Generator had. FIRST WRITER WINS and we
discard ours -- and the job still reports SUCCESS, because the file the caller
asked for is there.

One thing that bit during the build and is worth knowing: **peaks needs its
own "already made" test in the publish re-check, not just the mtime one.** A
`.peaks` written at the old 50/s rate is NEWER than its source, so the bare
`mtime >= source mtime` check let a stale file refuse every remake for ever.
`_with_partial` takes an `already_made` predicate for exactly this.

### Decisions this build made, that the plan left open

* **Rank is a GRACE PERIOD, not a filter.** §4.4 rule 3 says "prefer nvenc,
  prefer the machine next to the media". Implemented as: for the first 60 s a
  job is offered only to the best-placed machines (ties together), and after
  that to every capable one. A preference that could starve a queue would be
  worse than no preference, because the symptom is identical to a fleet with
  nothing to do -- and `why` now reports each able machine's `rank` so the
  order is visible while the queue is still moving.
* **"Next to the media" is read as THE BASE RIG.** Every machine offered a
  media job has the media mount already (it is a hard requirement), so mount
  adjacency carries no information; `mode == "base"` does. Nobody sits at the
  base rig, so an audio copy that runs there costs an editor nothing.
* **`requires` is defaulted for the media kinds only.** Phase 0 decided the
  submitter states the requirements. That stays true where there is a
  judgement to make (whisper's VRAM floor) and is wrong where there is not:
  three recipes with one right answer, the same on every clip, is a thing to
  keep in one place rather than in every future caller.
* **`progress` is a COLUMN, not the heartbeat's `note`.** The note lands in
  `last_error`, which is right for a sentence about a failure and wrong for a
  number the fleet page renders every 15 s. Null is not zero, both ways:
  `COALESCE` on write, and the chip shows the job id when nothing measured a
  fraction.
* **The media recipes run IN-PROCESS**, unlike whisper's subprocess: a recipe
  is ffmpeg plus about forty lines of binning, and the companion already owns
  an ffmpeg discovery and a `.partial` discipline. Shelling out to a second
  Python would mean a second copy of both.
* **A media job must NAME its output directory.** No default, no derivation
  from the source path: the page decides where its cache goes (`source/` for
  extractions and proxies, one level up for peaks), and nothing on this side
  guesses where a cache belongs in somebody's vault.

### What is NOT there yet

* **`claude-run` is still phase 1's fourth kind on paper and is not built.**
  Decision 7.6 stands and the answer is the dashboard's `ai_providers`, which
  is a dashboard-side executor and not a fleet job at all.
* **No pinning fallback** (§4.4 rule 5's "then pin it to the NAS worker"), no
  admin page, no cancel route. Unchanged from phase 0.
* **Nothing is deployed.** Dashboard 0.7.19 (schema v43), companion 0.9.57
  with `REQUIRES_DASHBOARD = 0.7.19`. The order is enforced by the machinery
  and is the rule either way: a 0.9.57 companion reports `capabilities.ffprobe`
  and heartbeats `progress`, and only v43 can store either.
* **Timeline Cards calls none of this.** §7b.4.

---

## 7b.4 What the Timeline Cards side must do next

This is the spec for a builder in `E:\Projects\Editing\Resolve\MulticamPipeline`.
It is written so it can be implemented from this document alone.

### The three call sites

`multicam_pipeline/cards/library_engine.py`, all on the HTTP thread:

| Method | Line (2026-08-30) | Today | After |
|---|---|---|---|
| `src_state(mp_uid)` | :1439 | appends to `self._src_q`, starts `_src_worker` | enqueue an `audio-extract` job, or fall back |
| `vid_state(mp_uid)` | :1583 | appends to `self._vid_q` | enqueue a `proxy-480p` job, or fall back |
| `peaks_state(mp_uid)` | :1159 | spawns `_peaks_make` on its own thread | enqueue a `peaks` job, or fall back |

Each already returns a `(state, path)` pair the page understands:
`ready | making | failed | none | noffmpeg | off`. **KEEP THAT CONTRACT
EXACTLY.** A fleet job in flight is `making`; nothing in `page/` changes.

### What to send

```
POST <dashboard>/api/v1/jobs        (admin session; see "the credential")
{
  "kind":   "audio-extract" | "proxy-480p" | "peaks",
  "inputs": {
    "root":     "media",          # the root the RUSH is under
    "rel_path": "<clip>",         #   relative to it
    "out_root": "vault",
    "out_rel":  "<episode>/Script Docs/remote_audio/source",   # peaks: one level up
    "out_stem": "<self._mp_names[mp_uid]>"                     # the MULTICAM name
  },
  "requires": {},                 # leave empty: the dashboard fills it in
  "priority": 1                   # audio ahead of video, as _src_worker already is
}
```

Three things to get right, each of which is a whole class of bug:

1. **NEVER SEND AN ABSOLUTE PATH.** `media_path(mp_uid)` gives you
   `/media/...` inside the container or `Y:\...` on a PC; the job needs the
   part BELOW the root and the root's NAME. `CARDS_MEDIA_MAP` is the existing
   mapping to invert. Both ends refuse an absolute value rather than guessing.
2. **`out_stem` is `self._mp_names.get(mp_uid, mp_uid)`,** which is what
   `_src_out`/`_lite_out` already use -- NOT the media file's stem. Get this
   wrong and the file lands beside the one the page is looking for.
3. **`out_rel` differs per kind**: `remote_audio/source` for `audio-extract`
   and `proxy-480p` (`src_dir()`), `remote_audio` for `peaks` (`lite_dir()`).

### Polling the row

`GET /api/v1/jobs/<id>` -> `{job}`. Map it onto the existing states:

| job `state` | what `*_state` returns |
|---|---|
| `queued`, `claimed`, `running` | `("making", None)` -- and `job.progress` (0..1 or null) is the number for the placeholder, which today says "N of M" |
| `done` | re-run the EXISTING `src_ready`/`vid_ready`/peaks-header check against the vault and return `("ready", path)` from that, NOT from `result.files` |
| `failed`, `abandoned` | `("failed", job.last_error)` -- the same slot `_src_fail` fills today |

**Read the answer off the DISK, not out of the row.** The job's result names
paths relative to `result.out_root`, which is useful for logging and for a
future admin page, but the file is in the vault and the vault is what the page
serves from. Re-checking the disk is also what makes a job that came back
`skipped: true` (the file was already current) indistinguishable from one that
did work, which is what you want.

Cache the id per output path so a second `*_state` call for the same clip
polls the existing job instead of queueing a second one -- the same job
`self._src_jobs` does today. A queued id survives a page reload; it does not
need to survive a server restart (the row is still there, and a re-queue costs
one duplicate job that finds its output already made and returns `skipped`).

### The fallback, which is not optional

`_src_worker` STAYS, and stays the default when any of these is true:

* no dashboard is configured or reachable (a connection error, any 5xx, a
  timeout -- treat all of them as "no fleet");
* the dashboard answered but `why.schedulable` is false and
  `why.summary` says nothing can run it (`POST /api/v1/jobs` returns `why` on
  the receipt precisely so this is decidable at submit time, without polling);
* the media share is not mounted anywhere else, which is the case §6 calls out
  explicitly: on a single-machine setup the in-process worker is not a
  fallback, it is the only path.

Fall back by doing exactly what the code does today -- append to `_src_q` /
`_vid_q` / spawn `_peaks_make`. Do not fail the lane. A job that was queued and
then abandoned should also fall back rather than showing `failed` for ever,
with ONE exception: a result whose error is a permanent property of the input
("no audio track", "no video track") is the same answer the local worker would
give, so record it in `_src_fail`/`_vid_fail` as today and do not retry
locally.

### The credential

`POST /api/v1/jobs` is an ADMIN SESSION route (a job is work on somebody
else's computer). A server-side caller signs in once with
`POST /api/v1/login`, keeps the cookie, and sends the `csrf` token that reply
carries on every write -- `tools/jobs.py`'s `Client` is 40 lines and is the
reference implementation. Do NOT reach for the fleet token: it is for
companions claiming work and the login gate carves out only the three claim /
heartbeat / result suffixes.

### What must NOT change

* The recipes. If `_src_make`, `_vid_make` or `_peaks_make` changes, the copy
  in `jobs_media.py` changes in the same week, or half the vault is made one
  way and half the other. `companion/tests/test_jobs_media.py` pins the argv
  verbatim so the diff is loud.
* `PEAK_RATE`. It is in the file's header on both sides.
* The `.tmp` -> `os.replace` discipline in the local worker. The fleet path
  uses `.partial` and the local one keeps `.tmp.m4a`; either is atomic, and
  the reason they differ is that `.partial` is what CC Sync's sync lanes
  exclude and Timeline Cards has no sync lanes.

---

## 7c. PHASE 2 BUILT, ccsync side (2026-08-30)

Status: §6's phase 2 is **built on the CC Sync side** on branch
`timeline-cards-port`. **Timeline Cards itself is still untouched**: the
companion's role imports its engine and REFUSES to start until that repo lands
the bridge contract in §7c.1, which is written below as a spec a builder over
there can implement from alone. Nothing is deployed and nothing is retired --
the standalone `--agent` and its `.cmd` launcher keep working exactly as they
do today.

### What exists now

| Piece | Where |
|---|---|
| the tunnel | `dashboard/src/ccsync_dashboard/cards_tunnel.py` -- `POST /cards/agent/state`, `GET /cards/agent/pending?wait=25`, `POST /cards/agent/result`, on `_require_fleet_caller` |
| its carve-outs | `app.py`: `_cards_fleet_re` (login gate), `_CSRF_EXEMPT_RE` (the two POSTs), the JSON-401 prefix list, and two body ceilings (`MAX_CARDS_STATE_BODY_BYTES` 6 MB, credential checked BEFORE the body) |
| its config | `DASH_CARDS_SERVER_URL` / `DASH_CARDS_TOKEN` -> `settings.cards_server_url` / `cards_token` |
| the bridge | `companion/src/ccsync_companion/timeline_cards_bridge.py` -- `CardsBridge`, `CONTRACT_VERSION = 1`, lock hold-time stats |
| one public lock entry | `resolve_bridge.api_call(name)` -- `_bridge_call` for callers outside that module; `_API_LOCK` stays private |
| the role | `companion/src/ccsync_companion/timeline_cards_role.py` -- the gate, the engine import, the contract check, the standalone-agent probe, the two loops, `report_block()` |
| its config | `cards_agent` (default **false**), `cards_vault_root` (defaults to `jobs_vault_root`); the checkout is `jobs_mulcam_pipeline`, which the whisper runner already names |
| the report | `capabilities.cards_agent = {connected, state, timeline, version, since}` -> schema **v44**'s five columns -> `db.machine_capabilities` |
| the chip | `[ CARDS: E1 v5 ]` on the fleet grid, green, on the connected machine only |

Tests: `dashboard/tests/test_cards_tunnel.py` (22),
`dashboard/tests/test_cards_capability.py` (10),
`companion/tests/test_timeline_cards_bridge.py` (19),
`companion/tests/test_timeline_cards_role.py` (30), and two more in
`dashboard/tests/test_jobs_contract.py` -- **the wire between the two
deployment units**, now covering the tunnel as well as the job routes.

### The tunnel, exactly

```
POST /cards/agent/state     body verbatim, minus `token`, with `name` replaced
GET  /cards/agent/pending?wait=<0..25>
POST /cards/agent/result    body verbatim, minus `token`
```

Every one needs `X-CCSync-Token` (the shared report token or a per-editor
`cce1.` one) **and** a dashboard-signed `X-CCSync-Identity`, the same pair the
job routes take, checked by the same `_require_fleet_caller`.

Four decisions in it:

* **`CARDS_TOKEN` leaves the editor's machine.** The dashboard attaches it
  outbound as `X-Cards-Token` from its own environment. The companion holds
  only what it already held. A body's own `token` field is dropped rather than
  forwarded, so a companion cannot present a secret of its choosing upstream,
  and an echoed one is stripped on the way back.
* **The agent's `name` is the VERIFIED identity**, plus the machine the caller
  declared, sanitised: `alex/CREATOR-1`. `AgentClient` puts
  `socket.gethostname()` there and the page's away/stale text is built from
  it. Same rule as ytdl's H5: the verified name, never `body.editor`.
* **Per suffix, never per prefix.** `/cards/` is where phase 3 mounts the
  PAGE -- a whole cut of a documentary -- and it stays session-gated. The
  three routes are registered before any future mount, so phase 3 replaces
  `_forward` with an in-process call and changes nothing else.
* **Upstream down is a 502 with a sentence**, and an upstream 401/403 says
  `DASH_CARDS_TOKEN` explicitly: that failure is THIS dashboard's secret being
  wrong, not the caller's, and an admin who cannot tell them apart rotates the
  fleet's token by mistake. No server configured at all is a 503 naming the
  variable, because a 404 reads as an old dashboard.

### The role's start and refuse rules

It starts when ALL of these hold, and refuses -- with a sentence, in
`status()["detail"]` and in the log -- on the first that does not:

1. `cards_agent = true` in `~/.ccsync/config.toml` (default false everywhere);
2. a dashboard URL and a fleet token (i.e. signed in);
3. no fleet halt (fails CLOSED: a halt check that cannot answer refuses);
4. `jobs_mulcam_pipeline` set, and `jobs_vault_root`/`cards_vault_root` set;
5. **no standalone Timeline Cards process talking to Resolve here** -- a
   command line matching `reorder_web.py` or `--agent`. It is NAMED and NOT
   KILLED: a human started it, and §6 says nothing is retired until Alex
   flips the config. A process probe that cannot answer counts as one
   running (fail closed): a false refusal costs the page, a false clearance
   costs scripting for the whole Resolve session for every client on the
   machine.
6. the checkout imports, and its engine declares
   `BRIDGE_CONTRACT_VERSION == 1` **and** takes a `bridge` argument. Both,
   because a constant is a claim and a signature is whether it is true.

`stop()` (companion shutdown) lets go. A fleet halt refuses a START and does
not interrupt a RUNNING role: the edits are synthetic keystroke sequences, and
one stopped half way through is a timeline nobody asked for.

### The cadence budget, and what it measured

Three schedulers now meet on `resolve_bridge._API_LOCK`:

| who | period | what it holds the lock for |
|---|---|---|
| the companion's timeline watcher | 3 s | its fingerprint, then the library walk with the lock RELEASED |
| the engine's full sweep | 1 s (`POLL_FULL`) | the timeline fingerprint: current timeline, item list, markers |
| the engine's playhead read | 0.1 s (`POLL_FAST`) | `GetCurrentTimecode` + `GetCurrentVideoItem` |
| an edit | on demand | the keystroke sequence and its verification |

The lock is never held for a per-clip property walk: that is
`bridge.sweep_items()`, which reads the project library with `_API_LOCK`
released, and which REFUSES to answer at all from an API walk (returning
None, i.e. "ask Resolve yourself") rather than putting the 11-95 s crawl on
the sweep's hot path.

Measured by `test_the_budget_a_sweep_costs_is_milliseconds` with the fake
bridge: **100 takes cost < 0.5 s in total and < 5 ms each**, against a watcher
tick of 3 s. `bridge.stats()` carries `takes`, `held_total`, `held_max` and
`held_max_call` for ever (cumulative, never reset -- the number that matters
is the worst take since the companion started), and a take past
`SLOW_TAKE_SECONDS` (0.5) is logged with its name, at most once a minute.

### THE HANDSHAKE HAS NEVER RUN LIVE

`release` and `reload` -- `SaveProject`, `CloseProject`, `LoadProject`,
`SetCurrentTimeline` -- are routed through the bridge like any other edit and
are otherwise untouched. `TRUENAS-APP-PLAN.md` §0 says twice that those four
calls have never been executed against a real project, and §6's own risk note
says not to port an unexercised path and change its host in the same week.
**So: run the release/reload handshake on `FF5lab` from the CURRENT
standalone agent first, before `cards_agent` is ever set to true.** If it is
wrong, it is wrong in the code that has been running for weeks, which is a far
better place to find out.

### Decisions this build made, that the plan left open

* **Flat `cards_*` config keys**, not a `[timeline_cards]` table -- phase 0's
  decision, unchanged, and for its reason: every other feature in `config.py`
  is flat. The dashboard's half is env vars (`DASH_CARDS_*`), because that is
  where every dashboard setting lives.
* **The role is CONSTRUCTED on every machine and starts on almost none.**
  `status()` is what answers "why is this computer not serving the page", and
  a role that is not built cannot answer anything. The chip, by contrast,
  renders only on the connected machine: `cards_agent is not set` is true of
  every computer in the fleet and would be a chip on all of them.
* **`AgentClient` is subclassed, not rewritten.** Its `_req` is the only
  place it touches a socket, so the push/pull loops that have driven Resolve
  from creator-1 for weeks are re-pointed rather than re-implemented.
* **`sweep_items` is the per-clip facts, not the item geometry.** The project
  library has no Resolve item UniqueId and its `MediaFilePath` is a stale
  snapshot (GOTCHAS §16), so uid/start/duration stay API reads -- three cheap
  calls a sweep. What comes out of the library is exactly what
  `_learn_media_path` and `_tokens_for` buy today with a GetClipProperty per
  clip, which is the part that made a card click take 7 s.
* **A refusal carries its own state**, not a word in its message. "No bridge
  contract at all" and "a contract from another version" are different
  answers for different people.

### What is NOT there yet

* **Timeline Cards implements none of §7c.1**, so the role refuses on every
  machine today, by design and with a message that says which document to
  read.
* **Nothing is retired.** The standalone `--agent`, `Launch Timeline Cards
  Agent.cmd` and the launcher card all still work. They come out when Alex
  has set `cards_agent = true` on creator-1 and watched a cut go through it:
  then `multicam_pipeline/resolve/resolve_script_server.py` is deleted (the
  companion's is the one copy), `run_agent` and the `.cmd` go, and §3.1's
  table loses its last row.
* **Nothing is deployed.** Dashboard 0.7.20 (schema v44) -- 0.7.21 with
  phase 3 (§7d) -- and companion 0.9.58 with `REQUIRES_DASHBOARD = 0.7.20`,
  bumped to **0.9.59** by the three findings above. The floor is unchanged:
  none of them is a wire change. The order is enforced by the machinery and
  is the rule either way.
* **No `claude-run` job and no admin view of the agent** beyond the chip and
  the diagnostics bundle. (The in-process page that used to be listed here is
  built: §7d.)
* **Whether a FROZEN companion can import the engine is untested.** The
  shipped build is one-file PyInstaller carrying its own dependencies, and
  the cards package pulls in whatever the MulticamPipeline checkout needs. A
  missing one is an import refusal with a sentence, not a crash -- but the
  answer to it is a decision (bundle them, or run the companion from source
  on creator-1), so try the role from a SOURCE run of the companion the first
  time it is switched on.

### What Alex has to do before any of it runs

1. **Run the release/reload handshake on FF5lab from the current standalone
   agent.** Before anything else, and see above for why.
2. **Deploy the dashboard (0.7.20) before publishing the companion**, and set
   `DASH_CARDS_SERVER_URL` (`http://<truenas>:8800`) and `DASH_CARDS_TOKEN`
   (the same value as the cards container's `CARDS_TOKEN`) in its compose
   environment. Until then the three routes answer 503 naming the variable.
3. **Have the Timeline Cards side implement §7c.1.** Nothing here runs until
   it does.
4. **Then, on creator-1 only**: stop the standalone agent and this PC's own
   `reorder_web.py 8800`, put `cards_agent = true` in
   `~/.ccsync/config.toml`, and restart the companion. There is no gradual
   rollout on that machine (§5's cost note): the moment the companion carries
   the role, it is the one Resolve client there.

### Three findings from the other side's implementation (2026-08-30)

Timeline Cards implemented §7c.1 (`47c2487` in that repo: `ResolveEngine(lib,
bridge=None)`, and a `_sweep_rows` that keys the library's rows by
`item_index` and reads them back with `rows.get(index)` against
`enumerate(GetItemListInTrack("video", 1))`). Reviewing THAT against this
side turned up three things, all fixed here:

**1. `sweep_items(tl_uid)` ignored `tl_uid`.** It returned
`resolve_bridge.get_timeline_items(allow_cached=True)` -- whatever timeline is
current, or a CACHED answer from a moment ago -- and the engine maps those
rows positionally onto the V1 items of the timeline it fingerprinted. An
editor who switched timeline between the fingerprint and the read (or a cache
hit from the previous one) would get every card's name, path and transcript
from somebody else's cut, **and nothing about the result would look wrong**.
Fixed on both halves: `get_timeline_items` now returns `timeline_uid` -- which
timeline the items are from -- and `CardsBridge.sweep_items` returns None on a
mismatch, or when the answer cannot say. An answer that cannot name its
timeline and one that names yours must not be the same answer to a caller
that is about to index into it.

**2. `item_index` skipped items it did not emit.** The contract is: rows come
back in `GetItemListInTrack("video", 1)` order, `item_index` 0-based within
the track, `track_index` 1-based, V1 = (`track_type "video"`, `track_index
1`). The track ORDER was already right and is now pinned by a test -- tracks
sort by `Sm2SequenceContainer_Sm2TiTrack.DbIndex`, never by row id, because
`Sm2TiTrack` carries no index of its own and its `SubType` is uninitialised
memory. The INDEX was not: an item with no `MediaRef` (a title, a generator,
an adjustment clip) was skipped WITHOUT advancing the counter, while Resolve's
own list returns it -- so every clip after a title on V1 was off by one.
`library.timeline_items` now counts every item and emits only the ones with
media.

**3. `_Take`'s plain form was not thread-safe.** `bridge.lock` is one object
and the engine has three threads that take it (the 1 s sweep, the 0.1 s
playhead read, an edit). The inner context and the start time lived on
`self`, so two threads entering at once overwrote each other's: the second
`__exit__` released a lock it never took and timed the take from the wrong
instant. They are a thread-local STACK now, which also makes the re-entrant
case free (`_API_LOCK` is an RLock). The engine only ever uses the named form
today; the docstring promised both, so both work.

And two smaller things the adapter is now pinned to, because the engine
depends on them: `on_edit_end(kind, ok, note)` is called POSITIONALLY (from a
`finally`, where a TypeError would be swallowed), and **`resolve()` returning
None is "wait", never a counted failure** -- Resolve closed, or inside its
launch window, is an ordinary state, and this bridge scores no connections of
its own.

---

## 7c.1 The engine's bridge contract (the spec for the Timeline Cards side)

This is written so it can be implemented from this document alone, in
`E:\Projects\Editing\Resolve\MulticamPipeline`. It is the ONLY thing the CC
Sync side is waiting on.

### The one-line summary

`ResolveEngine` stops owning a Resolve connection. It is handed one, and it
never calls `scriptapp()`, never imports `DaVinciResolveScript`, and never
reads the TCP table itself.

### The signatures, verbatim

```python
# multicam_pipeline/cards/resolve_engine.py

BRIDGE_CONTRACT_VERSION = 1        # module level; the companion checks it


class ResolveEngine(threading.Thread):
    def __init__(self, lib, bridge=None):
        ...


class SyncEngine(LibraryEngine):
    def __init__(self, root, bridge=None):
        LibraryEngine.__init__(self, root)
        self.res = ResolveEngine(self, bridge=bridge)
```

`bridge=None` keeps `python reorder_web.py 8800` and `--agent` working
unchanged: with no bridge the engine builds its own (an `_OwnBridge` wrapping
today's `mt.connect_resolve()` + `resolve_script_server`) and behaves exactly
as it does now. The companion always passes one.

### What a bridge provides

```python
class Bridge(Protocol):

    lock: ContextManager
    """The API lock. `with bridge.lock:` around EVERY call into Resolve.

    Re-entrant, so a helper that takes it inside a caller that already has it
    costs nothing. It may also be called with a name --
    `with bridge.lock("cards.conform"):` -- which is what a wedge warning
    reports; the plain form is always valid.
    """

    def resolve(self) -> Any | None:
        """The connected scriptapp object, or None. Never raises.

        None is an ordinary state, not an error: Resolve is closed, or it is
        inside its launch window and connecting now would kill the script
        server (CR-68). Wait and ask again.
        """

    def ready(self) -> bool:
        """May Resolve be talked to at all right now? Never raises, fails
        OPEN. Cheap enough to ask every tick; `resolve()` asks it too."""

    def on_edit_start(self, kind: str) -> None:
        """About to drive Resolve with synthetic keystrokes. `kind` is the
        request's own kind ("move", "trim", "conform", "release", ...).

        INFORMATIONAL. The bridge may not refuse an edit the page has already
        accepted; it logs it and reports it.
        """

    def on_edit_end(self, kind: str, ok: bool = True, note: str = "") -> None:
        """...and it is over, with how it went."""

    def sweep_items(self, tl_uid: str) -> list[dict] | None:
        """The clips of THE TIMELINE `tl_uid` NAMES, from the PROJECT LIBRARY.

        None means "ask Resolve yourself" -- no library, it stopped
        answering, OR the answer turned out to be about another timeline --
        and is the state most machines are in. Not an error, and not to be
        cached.

        `tl_uid` IS A CONSTRAINT, NOT A HINT (finding 1 below). The rows are
        matched to the API's items by POSITION, so a bridge that answered
        about whatever timeline is current would put one cut's clip name,
        path and transcript on another's the moment somebody switched
        timeline mid-sweep.

        Each dict:
            {"media_pool_uid": str,     # MediaPoolItem.GetUniqueId()
             "clip_name":      str,
             "file_path":      str,     # the file ON THIS MACHINE, "" if none
             "track_type":     "video" | "audio",
             "track_index":    int,     # 1-based, Resolve's convention
             "item_index":     int,     # 0-based within the track
             "via_multicam":   str | None,   # the multicam it came through
             "source":         "library"}

        NOT in it, and NOT obtainable from it: the timeline ITEM's unique id,
        its start and its duration. The project library carries no item uid
        and its MediaFilePath is a stale snapshot. Those three stay API reads.
        """
```

### What the engine has to change

1. **Delete `multicam_pipeline/resolve/resolve_script_server.py`** and every
   call to it. The companion's `script_server.py` is the one copy, reached
   through `bridge.ready()` / `bridge.resolve()`.
2. **`_connect`** becomes `self._resolve = bridge.resolve()`; None means "not
   now", not an exception. The project handle is read from it under the lock,
   as today.
3. **Every call into Resolve goes inside `with bridge.lock:`** -- the sweep's
   fingerprint, the playhead read, `_apply_*`, `_render_wav`, the conform and
   the release/reload handshake. The lock is SHARED with the companion's
   timeline watcher, so hold it for the calls and not for the thinking: build
   card dicts, diff plans and write JSON outside it.
4. **`_sweep` asks `bridge.sweep_items(tl_id)` first.** When it answers, use
   its rows for the per-clip facts `_learn_media_path` and `_tokens_for`
   currently buy with `GetClipProperty` -- clip name, file path, and the
   multicam mapping -- and read only the item geometry from the API. When it
   answers None, do exactly what the code does today.
5. **`_apply` calls `bridge.on_edit_start(kind)` before it touches Resolve
   and `on_edit_end(kind, ok, note)` in a `finally`.**
6. **Nothing else changes.** `KeyHelper`, `ripple_keys.ahk`, the undo journal,
   `_apply_conform`, the offcuts bank, `AgentClient` and the page all stay as
   they are. `AgentClient._req` in particular must remain the single place
   that touches a socket: the companion subclasses it and replaces only that
   method.

### How the companion drives it

```python
from multicam_pipeline.cards.resolve_engine import SyncEngine
engine = SyncEngine(vault_root, bridge=CardsBridge(cfg))
engine.start()
client = _TunnelClient(dashboard_url, "", engine, machine_name)  # AgentClient
threading.Thread(target=client.pull_loop, daemon=True).start()
threading.Thread(target=client.push_loop, daemon=True).start()
```

The token is empty on purpose, for ever: the cards server's secret lives in
the dashboard container and is attached there.

### How to know it landed

`companion/tests/test_timeline_cards_role.py` builds a fake checkout and
checks the refusals; the real one has to satisfy the same two questions:

```python
import multicam_pipeline.cards.resolve_engine as m
assert m.BRIDGE_CONTRACT_VERSION == 1
import inspect
assert "bridge" in inspect.signature(m.SyncEngine.__init__).parameters
```

If either is false the companion refuses to start the role and says so in one
sentence naming this section. That is the intended behaviour on every machine
until the work above is done.

---

## 7d. PHASE 3 BUILT, ccsync side (2026-08-30)

Status: §6's phase 3 is **built on the CC Sync side** on branch
`timeline-cards-port`. The page, its engine and its Claude features are hosted
IN the dashboard container at `/cards`, behind the dashboard login, on the
same contract `/broll` and `/music` have. **Timeline Cards itself is still
untouched**, and -- the good surprise of this phase -- it barely needs to
change: §7e's audit found the page is ALREADY document-relative, so the "real,
mechanical, boring day of work" §3.2 problem 2 predicted does not exist.
Nothing is deployed and nothing is retired: the standalone `timeline-cards`
custom app on :8800 keeps serving, and the tunnel keeps forwarding to it until
a dashboard is deployed with the mount configured.

### What exists now

| Piece | Where |
|---|---|
| the mount | `dashboard/src/ccsync_dashboard/cards.py` -- `mount_cards()`, the tri-state, `build_engine`, `CardsGate`, `stop_engine`, `health_block` |
| the shim | `cards_wsgi.py` -- one `BaseHTTPRequestHandler` class -> one STREAMING WSGI app; `a2wsgi.WSGIMiddleware` makes it ASGI |
| the Claude seam | `cards_ai.py` -- `Runner.run()/status()` over `ai_providers`, injected as `engine.claude_runner` (§7d.1) |
| its settings | `settings.py` -- `cards_enabled`, `cards_src`, `cards_vault_root`, `cards_root`, `cards_project`, `cards_db_{host,name,write_allow,backups}`, `cards_media_map`, beside phase 2's `cards_server_url`/`cards_token` |
| the gates | `app.py` -- the mount after the routers, the JSON-401 prefixes (`/cards/api/`, `/cards/audio`, `/cards/video`, `/cards/peaks`), `_CSRF_ORIGIN_ONLY_PREFIXES`, and `cards.stop_engine(app)` in the lifespan's `finally` |
| the tunnel, in-process | `cards_tunnel.py` -- `local_engine(request)`; with a mount the three routes call `agent_state` / `agent_pending` / `agent_result` directly, with no HTTP hop and no upstream token |
| the health line | `GET /api/v1/health` -> `cards: {status, detail, root, agent, claude:{ok,why}}`, authenticated callers only |
| the nav | `[ CARDS ]` in the drawer, `/cards/` **with the trailing slash**, only when the mount fully took |
| the deploy | `dashboard/deploy/compose.yaml` + `compose.image.yaml` (the `DASH_CARDS_*` block, `/cards-app`), `server/install_dashboard_app.py` (`[timeline_cards]`, the ship step, the two per-site mounts, `group_add`), `site.example.toml`, `docs/DOCKER.md` "The Timeline Cards mounts" |
| the dependency | `a2wsgi>=1.10`, pinned in `deploy/requirements.lock` at 1.10.10, in pyproject's new `cards` extra and in `test_hardening`'s group list |

Tests: `dashboard/tests/test_cards_mount.py` (31 -- the tri-state, the gate,
the shim, the Range pass-through, the in-process tunnel, the shutdown hook,
the health line) and `dashboard/tests/test_cards_page_prefix.py` (5, against
the REAL checkout when one is reachable: §7e's audit, and our media-map parser
diffed against the real `split_pairs` in a subprocess).

### The tri-state, and what each state means

`mount_cards()` returns `(status, detail)` and never raises. The order of the
checks IS the diagnosis, and each answer names the variable to fix:

| state | when | `detail` |
|---|---|---|
| `disabled` | `DASH_CARDS_ENABLED` is not `1` (and no `CARDS_SRC` in the environment) | "DASH_CARDS_ENABLED is not 1" |
| `disabled` | enabled, no checkout configured | "no Timeline Cards checkout is configured (DASH_CARDS_SRC)" |
| `disabled` | enabled, no vault configured | "no vault is mounted here (DASH_CARDS_VAULT_ROOT)" |
| `absent` | the checkout path is not a directory | "the configured checkout is not there (\<path\>)" |
| `absent` | the vault path is not a directory **in this container** | "the vault root is not mounted (\<path\>)" |
| `absent` | the import raised | "the checkout did not import (ImportError: ...)" |
| `absent` | the engine's constructor or `start()` raised | "the engine did not start (...)" |
| `mounted` | -- | "serving \<vault root\>" |

`disabled` is "this deployment did not ask for it" and logs at INFO;
`absent` is "it was asked for and something is not there" and logs at WARNING.
There is no fourth `degraded` state, unlike b-roll's: an engine that could not
be built is not mounted at all, because there is nothing to serve requests
with.

### Where the engine gets its settings

`build_engine()` constructs exactly what `server.main`'s `--remote-agent`
branch does -- `ProjectAgentEngine(project, root, token, db_host=, db_name=,
write_allow=, backup_dir=)` -- from `DASH_CARDS_*`, one dashboard variable for
each `CARDS_*` the standalone container takes. Then three assignments the
command line makes too: `access_key`, `media_map`, and (new) `claude_runner`.

Two of those are decisions rather than translations:

* **`CARDS_KEY` IS RETIRED.** `engine.access_key = None`, explicitly, with no
  setting behind it. §7.4 said the session cookie is strictly better auth than
  `?key=...` in a URL; under this mount it is also the ONLY auth, and a second
  gate could only ever disagree with the first. **This is the answer to §7.4's
  open question, and it makes the phone case sign in to CC Sync once.**
* **`/api/restart` IS BLOCKED BY THE GATE.** In the standalone server that
  route closes the listener and re-execs; `restart_server` ends in
  `os._exit(0)`. In this process that is the dashboard, and the whole fleet
  would go down because somebody pressed the reload button on a page. The
  gate answers it `{"error": "...cannot restart itself..."}`, and the
  handler's `self.server` is an object whose `shutdown()` refuses and logs --
  two locks, because this one is unrecoverable.

### The shim, and why not a router rewrite

§3.2 problem 1's decision stands: **keep the ~70 routes byte for byte.**
`cards_wsgi.handler_wsgi()` builds the handler with `__new__` (there is no
socket, and exactly one request per call), feeds it a synthesised request head
plus the WSGI input as its `rfile`, and gives it a `wfile` that parses the
status line and headers out of the first bytes, calls `start_response` once,
and hands every later chunk to the WSGI `write()` callable.

**IT STREAMS.** a2wsgi's `write()` puts each chunk on an asyncio queue of ten
and blocks until the event loop has taken it, so a 480p proxy of an hour-long
interview flows through at the browser's pace instead of into this container's
memory -- the same backpressure the real socket gave it. `Date` and `Server`
are dropped (uvicorn writes its own; two `Date` headers is a malformed
response). A handler that raises is a 500 and a handler that writes nothing is
a 502, neither of which can happen today and both of which now have an answer
instead of a hung request.

`WSGIMiddleware(..., workers=24)` rather than its default ten: one open page
holds a poll and a media stream at once and a phone on the sofa is a second
pair, and a full pool is a stall with no error message.

### CSRF: exempt from the TOKEN, not from the ORIGIN

`/broll/`, `/music/` and `/ytdl/` are outright CSRF-exempt prefixes because
their SPAs do not send the token yet. `/cards/` is not simply added to that
list: its POSTs delete clips, trim them and run conforms in somebody's open
timeline. It is exempt from the token and still subject to `_origin_mismatch`,
which is the half that actually stops the attack -- a browser attaches
`Origin` to every cross-site POST. `_CSRF_ORIGIN_ONLY_PREFIXES` disappears the
day the page sends `X-CSRF-Token`.

### The tunnel is in-process when the page is here

Phase 2's three routes are unchanged in shape, credential and name rule. They
now ask `app.state.cards_engine` first: with a mount they call the engine
directly (`agent_state` / `agent_pending` / `agent_result`, each followed by
`tick()`, which is `handler.py`'s own sequence, including its
`{"error": str(exc)}`-with-a-200 contract and its `unhand()` on an answer that
cannot leave the process). With no mount they forward to
`DASH_CARDS_SERVER_URL` exactly as before -- which is what lets both origins
run side by side during the transition (§7.4).

### Decisions this build made, that the plan left open

* **The checkout is a MOUNT and a SETTING, not a `PYTHONPATH` entry.** The
  other three sub-apps are on `PYTHONPATH` in `run.sh`; this tree is another
  repo's, is never in the vendor image and is never in an over-the-air code
  bundle, and `select_code_root.py` re-derives that path list on every
  image-mode boot. `cards.py` appends `DASH_CARDS_SRC` to `sys.path` itself,
  so the path entry and the mount are one decision instead of two that can
  disagree. It is also the only code mount that survives IMAGE MODE.
* **`CARDS_SRC` in the environment is taken as consent.** A developer pointing
  it at a checkout should not also have to set the enable flag; a deployment
  never has it set.
* **No identity headers.** `BrollGate` and `MusicGate` mint
  `X-CCSync-User`/`X-CCSync-Admin` from the session because those sub-apps
  make per-user decisions. Timeline Cards has no per-editor state -- the cut,
  the plans and the notes are one document per episode that everyone with a
  login is editing together -- so there is nothing here for a header to say,
  and a header the sub-app trusts because we sent it is not something to add
  speculatively.
* **The vault being absent is `disabled`, not `degraded`.** "Blank = /cards
  says no vault mounted" was the requirement; an engine rooted at a path that
  is not there would answer every request with an empty episode, which is
  worse than a mount that is honestly off.
* **The Claude seam is an OBJECT injected at mount time**, not a config flag
  the other side reads (§7d.1). The dashboard is where the credential, the
  chain and the site's feature flag live; the engine should ask, not decide.
* **The fleet (`FleetJobs`, §7b) is NOT wired up in the mounted engine.**
  Submitting a job is an admin-session call and this engine would be signing
  in to the dashboard it is running inside. The in-process ffmpeg worker --
  which §7b.4 keeps as the fallback anyway -- is what makes the proxies here.
  Worth revisiting only when somebody wants the NAS's `/cards` to farm work
  out to the fleet as well.

### What is NOT there yet

* **Nothing is deployed and nothing is retired.** Dashboard **0.7.21**. The
  `timeline-cards` custom app still runs on :8800; its retirement is a runbook
  step below, deliberately not done.
* **`claude-run` as a FLEET JOB is still not built** (§7b's fourth kind), and
  after this phase it is unlikely ever to be: the answer is a dashboard-side
  executor, and this is it.
* **The page still polls.** Mounting it in-process removed the HTTP hop for
  the AGENT protocol, not for the browser: `/cards/api/state?v=N` is still one
  request a second per open page, now against the dashboard's event loop with
  24 shim workers behind it.
* **No admin view of the mount** beyond the health line and the nav link.
* **The Timeline Cards side has one line to change** (§7e) and one seam to
  implement (§7d.1), and both are optional in the sense that the mount works
  without them -- with `scope: "/"` an installed home-screen app claims the
  whole dashboard origin, and with no `claude_runner` the three Claude
  features report themselves unavailable in a container that has no CLI.

### What Alex has to do before any of it runs

1. **Chown the vault on the NAS**, once, before the first deploy with
   `[timeline_cards]` set: `docs/DOCKER.md`, "The chown, and why it is needed
   BEFORE the first deploy". `group_add` without it is a page whose every save
   is refused, and the symptom is only visible in the container log.
2. **Decide the Claude credential**: an `ANTHROPIC_API_KEY` on Settings -> AI
   providers (the vendor path, metered), or `[features] ai_cli_providers = true`
   plus installing the CLI from that page (the subscription path, whose ToS
   consequences are the customer's own -- `CLI_TOS_NOTE`). With neither,
   translate / semantic search / summaries stay dimmed and say why.
3. **Fill in `[timeline_cards]` in `site.toml`** -- `src`, `vault_host`,
   `media_host` + `media_map`, `db_host`/`db_name`, and `enabled = true` -- and
   deploy the dashboard (0.7.21).
4. **Retire the custom app, when the mounted one has been used for real**
   (and not before -- see the runbook step below).

### The runbook step for retiring `timeline-cards` (NOT DONE)

In this order, on the NAS:

1. Open `/cards` on the dashboard and use it for a session: the cards, the
   lane's audio and video, a plan save, a translate run, and one edit through
   an agent (which now reaches Resolve via `/cards/agent/*` with no
   `CARDS_TOKEN` on the editor's machine at all).
2. Point the phone at `https://<dashboard>/cards/` and re-add it to the home
   screen. The old install's `start_url` is the other origin and it will keep
   working -- which is the point of leaving the app up until this step.
3. Only then: stop and delete the `timeline-cards` custom app in the TrueNAS
   UI. Its `/data` volume (`cards_pick.json`, `cards_mirror.json`,
   `cards_ui.json`, `library_backups/`) is **per-server UI state with no
   owner and no migration** (§2.3) -- the mounted server starts with its own,
   so expect the picker and the mirror to be empty once, not wrong.
4. Clear `DASH_CARDS_SERVER_URL` from the dashboard's compose (or
   `[timeline_cards] server_url`) so the three tunnel routes stop offering to
   forward to a container that is gone.

---

## 7d.1 The Claude seam (the spec for the Timeline Cards side)

Written so it can be implemented from this document alone, in
`multicam_pipeline/cards/library_engine.py`. **The mount already injects it;
until this lands, the engine's own `_run_claude` is what runs -- and in this
container it finds no `claude` on PATH, so `claude_status()` says so and the
page dims the three buttons. That is the honest failure and it is the state
today.**

### The seam

```python
class LibraryEngine:
    claude_runner = None      # class attribute; the mount sets an instance one
```

One optional attribute. When it is None, EVERYTHING BELOW IS UNCHANGED -- the
CLI path stays exactly as it is, which is what `reorder_web.py 8800` on the PC
and the standalone container both keep using.

### What the runner is

```python
runner.run(prompt: str, model: str = "", timeout: float = 900,
           think: bool = True, json_out: str = "") -> dict
runner(...)                     # __call__ is run
runner.status() -> {"ok": bool, "why": str}
```

`run()` returns, always, never raising across the seam:

```python
{"ok": True,  "text": "<the model's reply>", "data": <parsed JSON or None>,
 "provider": "anthropic_api" | "claude_code", "error": ""}
{"ok": False, "text": "", "data": None, "provider": "...", "error": "<one sentence>"}
```

### The three call sites

| method | today | with a runner |
|---|---|---|
| `_run_claude(prompt, model, timeout, think)` | `subprocess.run(claude_argv() + ...)` -> `CompletedProcess` | `self.claude_runner.run(prompt, model, timeout, think)`; on `ok` behave as `returncode == 0` with `stdout = text`, on failure raise `RuntimeError(error)` |
| `_run_claude_json(prompt, out, model, timeout)` | run agentically, then `json.load(open(out))` | `run(prompt, model, timeout, json_out=out)`; on `ok` return `data` (the file at `out` has also been written), on failure raise `RuntimeError(error)` |
| `claude_status()` | is there a `claude` on PATH | `self.claude_runner.status()` when there is one |

`_run_claude` is a `@classmethod` today and the runner is per-instance, so it
becomes an instance method (or takes the runner as an argument). Its two
`CompletedProcess`-shaped uses -- `proc.stdout` and `proc.returncode` in
`_tx_chunk` and `start_summary` -- are the only things that have to move.

### The model names it may pass

Unchanged, and passed straight through: `TX_MODEL =
"claude-haiku-4-5-20251001"` (translate), `SEM_MODEL = SUM_MODEL =
"claude-sonnet-5"` (semantic search, summaries). A name this API does not know
comes back as `{"ok": false, "error": "this API does not know the model
claude-sonnet-5: ..."}` -- with the name in it, because the alternative is a
bare `NotFoundError` in a worker thread.

### The JSON contract, and the one thing that changes

**THE MODEL NEVER GETS FILE TOOLS.** `_run_claude_json`'s prompt asks for an
agentic run that writes a file; the runner instead appends one line to the
prompt --

```
OUTPUT: reply with the JSON object alone -- no prose before or after it, no
code fence. (If you have file tools you may also write it to <path>; the reply
is what is read.)
```

-- parses the first `{...}` block out of the reply, and writes `<path>` itself
(`.partial` then `os.replace`). A file the CLI wrote anyway is honoured first,
because it is the one the model meant. So `out` exists and parses on every
`ok`, whichever provider answered, and an agent binary with filesystem tools
never runs inside a container that mounts the vault read-write.

Which means the SEM_PROMPT / SUM_PROMPT wording does not have to change --
but if it is ever reworded, "write your answer to the file" must stay
acceptable rather than required.

### Errors, and what the page shows

`error` is one sentence, already phrased for a human, and the existing
`{"error": ...}` slots the page reads are where it goes:

* no credential -> "no provider has a working credential" (the site's chain
  found nothing);
* a non-Claude provider -> "this site's AI provider is OpenAI API, and
  Timeline Cards' translate, semantic search and summaries are written for
  Claude...";
* a refused key -> "the site's ANTHROPIC_API_KEY was refused for model X: ...";
* a CLI that is not signed in -> "Claude Code exited 1: ..." with its own
  stderr.

`status()` NEVER PROBES (a CLI probe is a real one-token call), so it is safe
on the state publish that happens every second.

---

## 7e. The URL spec for the page (the audit, and it is nearly empty)

§3.2 problem 2 predicted "a real, mechanical, boring day of work... the single
most likely thing to be skipped and then discovered live". **It was already
done.** Audited on 2026-08-30 against
`multicam_pipeline/cards/page/` in the fork, counting every quoted, backticked
or parenthesised URL beginning `/api`, `/audio`, `/video`, `/peaks`, `/agent`,
`/icon.svg` or `/manifest.webmanifest`:

| file | absolute URLs |
|---|---|
| `cards.html` | **0** (`<link rel="manifest" href="manifest.webmanifest">`) |
| `cards.css` | **0** |
| `01-state.js` | **0** (every fetch is `fetch('api/...')`) |
| `02-markers.js` .. `10-look.js` | **0** each |
| **total in `page/`** | **0** |

The one absolute URL in the whole page is not in `page/` at all:

| file | line | what | fix |
|---|---|---|---|
| `page.py` `render_manifest()` | `"scope": "/"` | claims the WHOLE dashboard origin for the installed home-screen app | `"scope": "."` |

`start_url` is already `"."` and the icons are already `"icon.svg"`, both
relative, and for the right reason (an install had to keep whatever `?key=`
the browser was let in with). `scope` was missed because nothing before this
served the page under a prefix: a scope of `/` is legal while the page IS the
origin, and under `/cards/` it means an installed app that captures every
dashboard URL.

### The test the Timeline Cards side should add

The dashboard already carries this check, so the TC side's copy is a mirror
rather than a discovery: `dashboard/tests/test_cards_page_prefix.py`. It skips
when no checkout is reachable and runs against the real one otherwise
(`CARDS_REAL_SRC`, else this machine's fork), and it is GREEN today except for
one `xfail` -- the manifest's `scope`, which flips green the day that
character changes.

Over there it should be `tests/test_mounted_prefix.py`, matching what
`broll/web` and `music/web` each carry:

```python
ABSOLUTE = re.compile(r"""["'`(]\s*(/(?:api|audio|video|peaks|agent"""
                      r"""|icon\.svg|manifest\.webmanifest)[\w./?=&-]*)""")

def test_the_page_is_document_relative():
    for name in PAGE_FILES:                    # cards.html, cards.css, 01..10
        assert not ABSOLUTE.findall(read(name)), name

def test_the_manifest_scope_is_relative():
    assert json.loads(render_manifest())["scope"] == "."
```

**Why it must exist over there and not only here**: the page's goldens
(`tests/golden/page.html`, byte-identical, `.gitattributes eol=lf`) make any
edit to `page/` a deliberate act -- but they pin the bytes, not the shape, so
a new `fetch('/api/whatever')` would sail through a golden UPDATE without
anybody noticing, and the failure is invisible until somebody opens the page
under a prefix and it says "connecting..." for ever.

---

## 8. Verdict

**Do it, in this order, and do not skip phase 0.**

The port is sound because the seam is already cut: Timeline Cards was split
into a Resolve half and a library half on 2026-08-27 for a completely
different reason, and that split lands almost exactly on CC Sync's
companion/dashboard boundary. The agent is already a companion in everything
but name — outbound-only, CR-68-guarded, typed work items, retries — and the
page is already a mountable sub-app in everything but its HTTP layer. The
PostgreSQL it reads is already a service in CC Sync's own compose file, and
the deploy tooling that installs its container is already CC Sync's
`deploy_stack`.

The fleet job model is the part with real new value and the part CC Sync
genuinely does not have. But it is *nearly* there: `claim_next_job` /
`claim_download` / heartbeat / lease-expiry / one-way pinning is a working,
battle-tested queue that has already survived a bad evening (CR-80's job 28),
and `idle.py` + `proxy_gen`'s gates are a working, tested "only while nobody
is here". Generalising those two is a smaller job than writing either.

The thing to be careful about is phase 2, and the care is not technical
nerve, it is sequencing: absorbing the agent means creator-1 has exactly one
Resolve client on the day it lands, with no fallback to the standalone agent,
and it means the release/reload handshake — four Resolve calls that have
never run live — changes host in the same change. Run those on `FF5lab`
first, from the current code, before anything moves.

Phase 0 alone is worth shipping even if the rest is never built.
