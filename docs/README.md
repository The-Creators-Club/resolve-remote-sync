# Documentation index

CC Sync — fleet sync for DaVinci Resolve®. Every document in `docs/`, one line
each. Start at the top if you are new.

Index written 2026-08-17 (`COMMERCIAL_READINESS.md` item 13).

---

## Getting started

| Doc | What it is |
|---|---|
| [`INSTALL.md`](INSTALL.md) | **Start here.** Requirements, the order of operations, the secrets, the feature switches, and a verification checklist |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | The system overview: components, the three sync lanes, the dashboard and its mounts, auth, trust boundaries, what is stored where, and the platform envelope |
| [`CONFIG.md`](CONFIG.md) | Every configuration key: `site.toml`, the dashboard's environment, the companion's `config.toml`, the indexers |
| [`API.md`](API.md) | The dashboard's HTTP API — routes, auth per route, request/response shapes |
| [`SERVER.md`](SERVER.md) | The TrueNAS SCALE runbook |
| [`SERVER-SYNOLOGY.md`](SERVER-SYNOLOGY.md) | The Synology DSM runbook, including Tailscale Serve as the publish path |
| [`SYNOLOGY_EASY_INSTALL.md`](SYNOLOGY_EASY_INSTALL.md) | Design for a packaged (SPK) install a non-technical studio owner can run |
| [`ZERO_TOUCH_PLAN.md`](ZERO_TOUCH_PLAN.md) | The appliance plan: customer installs Tailscale + one container, browser wizard does the rest, only the vendor builds (item 16) |
| [`EDITOR_SETUP.md`](EDITOR_SETUP.md) | Onboarding one editor, from the operator's side |
| [`../installer/START_HERE.md`](../installer/START_HERE.md) | The same thing written *for* the editor |

## Operating it

| Doc | What it is |
|---|---|
| [`RELEASE.md`](RELEASE.md) | Shipping a companion build: versions, the signing key, the downgrade floor, code signing, the drift doctor |
| [`RELEASE_FEED.md`](RELEASE_FEED.md) | The signed vendor feed every customer's dashboard reads: the channel format, publishing it, and the dashboard's own code updates |
| [`LOOPBACK_API.md`](LOOPBACK_API.md) | The companion's 127.0.0.1:8899 listener: every route group, and who is allowed to call them |
| [`GOTCHAS.md`](GOTCHAS.md) | The accumulated "why is it doing that" list. Read it before debugging anything |
| [`INDEXERS.md`](INDEXERS.md) | The GPU indexers: what runs where, and what a customer without a GPU gets |
| [`YTDL_LOCAL_DOWNLOAD.md`](YTDL_LOCAL_DOWNLOAD.md) | The YouTube downloader's fleet job model and the local-download path |
| [`DOCKER.md`](DOCKER.md) | The two ways the dashboard container gets its code and its dependencies |
| [`CI.md`](CI.md) | What runs on a runner, and what still only runs on the base rig |
| [`PRODUCT_REPO.md`](PRODUCT_REPO.md) | The customer-facing repo, how it is exported, and what is withheld |

## Not losing footage

| Doc | What it is |
|---|---|
| [`SYNC_SAFETY.md`](SYNC_SAFETY.md) | The lane B circuit breaker, `.ccsync-trash` retention, the remove-project gate, and the halt |
| [`BACKUP_RESTORE.md`](BACKUP_RESTORE.md) | Snapshots, restoring a file / a project / the fleet database, and publishing a search index safely |
| [`RESOLVE_EDIT_SAFETY.md`](RESOLVE_EDIT_SAFETY.md) | Undoing a clip-path change CC Sync made |
| [`delete-protection-ignoredelete.md`](delete-protection-ignoredelete.md) | Why Syncthing runs with `ignoreDelete` on the server side |

## Security

| Doc | What it is |
|---|---|
| [`SECRETS.md`](SECRETS.md) | The operator secrets: where they live, and where they must not |
| [`TENANCY.md`](TENANCY.md) | Who can reach whose footage: one container per customer, `project_acl`, `editor_shell` |
| [`LOOPBACK_API.md`](LOOPBACK_API.md) | The companion's `127.0.0.1:8899` listener, and who may call it |

## Legal

| Doc | What it is |
|---|---|
| [`legal/EULA.md`](legal/EULA.md) | Draft end-user licence agreement |
| [`legal/PRIVACY.md`](legal/PRIVACY.md) | Draft privacy notice — what the product collects and where it goes |
| [`legal/TELEMETRY.md`](legal/TELEMETRY.md) | What is reported, by whom, and how to turn it off |
| [`legal/THIRD_PARTY_NOTICES.md`](legal/THIRD_PARTY_NOTICES.md) | Bundled and downloaded third-party components and their licences |
| [`legal/YOUTUBE_FEATURE_NOTICE.md`](legal/YOUTUBE_FEATURE_NOTICE.md) | **Read before enabling `[features] youtube_download`** |

> These are **drafts prepared in-house, not legal advice.** They need review by
> counsel in your jurisdiction before you rely on them.

## Engineering / planning

| Doc | What it is |
|---|---|
| [`COMMERCIAL_READINESS.md`](COMMERCIAL_READINESS.md) | The 2026-08-17 audit and the ranked list of what must change to sell this to other organisations |
| [`SYNOLOGY_PORT_PLAN.md`](SYNOLOGY_PORT_PLAN.md) | The plan behind the second NAS backend |
| [`BROLL_INGEST_PLAN.md`](BROLL_INGEST_PLAN.md) | Drag-and-drop b-roll ingest: the design, the contracts and what was deviated from |
| [`MUSIC_INGEST_PLAN.md`](MUSIC_INGEST_PLAN.md) | The same for music, reusing the b-roll machinery, plus what it deliberately does not compute |
| `../SPEC.md` | The internal architecture document — history, rationale, known flaws |
| `../KNOWN_BUGS.md` | The live defect ledger (numbered entries, per-platform prefixes) |
| `../CLAUDE.md` | Repo conventions, test commands, and the one ship command |

## Archives — history, not instructions

These record what happened on a specific date, on specific machines. **The
addresses, hostnames and people in them are those of the original deployment**
and are deliberately left as they were; do not copy commands out of them.

| Doc | What it is |
|---|---|
| [`bug-hunt-2026-08.md`](bug-hunt-2026-08.md) | The original August bug-hunt worklist, archived when the fix fleet completed |
| [`bug-hunt-2026-08-11.md`](bug-hunt-2026-08-11.md) | The 127-finding hunt |
| [`bug-hunt-2026-08-14.md`](bug-hunt-2026-08-14.md) | The 94-finding hunt |
| [`synology-spikes-2026-08-17.md`](synology-spikes-2026-08-17.md) | The eight day-1 spikes run against real Synology hardware |
| [`macos-first-run-2026-08-04.md`](macos-first-run-2026-08-04.md) | The first macOS bring-up session |
| [`macos-first-run-2026-08-05.md`](macos-first-run-2026-08-05.md) | The follow-up session |
| [`macos-onboarding-handoff.md`](macos-onboarding-handoff.md) | The macOS onboarding handoff notes |
| [`youtube_dlp_bugs.md`](youtube_dlp_bugs.md) | yt-dlp behaviour notes gathered while building the downloader |

## Component READMEs

| Doc | What it is |
|---|---|
| [`../companion/README.md`](../companion/README.md) | The editor tray app |
| [`../dashboard/README.md`](../dashboard/README.md) | The dashboard, and the deep dive on authentication |
| [`../server/README.md`](../server/README.md) | The NAS-side setup scripts |
| [`../installer/README.md`](../installer/README.md) | The per-OS editor bootstrap |
| [`../onboarding/README.md`](../onboarding/README.md) | The first-run wizard |
| [`../broll/README.md`](../broll/README.md) | The b-roll platform |
| [`../music/README.md`](../music/README.md) | The music tagger |

---

DaVinci Resolve is a registered trademark of Blackmagic Design Pty Ltd. CC Sync
is not affiliated with, endorsed by, or sponsored by Blackmagic Design.
