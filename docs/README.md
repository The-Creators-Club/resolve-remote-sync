# Documentation index

CC Sync — fleet sync for DaVinci Resolve®. Every document in `docs/`, one line
each. Start at the top if you are new.

Index written 2026-08-17 (`COMMERCIAL_READINESS.md` item 13); completed and
put under test 2026-09-04 (SYS-12). `tools/tests/test_docs_index.py` fails if a
document is added to `docs/` and not listed here, because the promise in the
line above is machine-checkable and nothing was checking it.

---

## Getting started

| Doc | What it is |
|---|---|
| [`INSTALL.md`](INSTALL.md) | **Start here.** Requirements, the order of operations, the secrets, the feature switches, and a verification checklist |
| [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md) | **Customer-facing.** Plain-English, end-to-end explanation of the whole product for non-technical owners, producers and editors; glossary and troubleshooting table |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | The system overview: components, the three sync lanes, the dashboard and its mounts, auth, trust boundaries, what is stored where, and the platform envelope |
| [`CONFIG.md`](CONFIG.md) | Every configuration key: `site.toml`, the dashboard's environment, the companion's `config.toml`, the indexers |
| [`API.md`](API.md) | The dashboard's HTTP API — routes, auth per route, request/response shapes |
| [`SERVER.md`](SERVER.md) | The TrueNAS SCALE runbook |
| [`SERVER-SYNOLOGY.md`](SERVER-SYNOLOGY.md) | The Synology DSM runbook, including Tailscale Serve as the publish path |
| [`SYNOLOGY_EASY_INSTALL.md`](SYNOLOGY_EASY_INSTALL.md) | Design for a packaged (SPK) install a non-technical studio owner can run |
| [`ZERO_TOUCH_PLAN.md`](ZERO_TOUCH_PLAN.md) | The appliance plan: customer installs Tailscale + one container, browser wizard does the rest, only the vendor builds (item 16) |
| [`APPLIANCE_INSTALL.md`](APPLIANCE_INSTALL.md) | The paste-and-click install written as customer-facing steps. **A draft**: it marks every place a later work package changes the story, so read the NOT YET TRUE flags before handing it to anyone |
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
| [`BACKCATALOGUE_INGEST.md`](BACKCATALOGUE_INGEST.md) | Adding older projects to the b-roll archive as `source: proxies` shares: what it cost, and what it taught about the pipeline |
| [`YTDL_LOCAL_DOWNLOAD.md`](YTDL_LOCAL_DOWNLOAD.md) | The YouTube downloader's fleet job model and the local-download path |
| [`YTDL_RESILIENCE_PLAN.md`](YTDL_RESILIENCE_PLAN.md) | After CR-80: why cookies and pinned player clients keep breaking YouTube downloads, and the fix. WP1-WP7 BUILT in repo 2026-08-26 (CR-83, dashboard 0.7.11 / companion 0.9.52, unshipped); WP8 deliberately not built |
| [`CLIENT_FOLDERS.md`](CLIENT_FOLDERS.md) | Curated b-roll folders with a link a prospective licensee can open: how to use them, what the client sees, and publishing the one path prefix with Tailscale Funnel |
| [`STAGE_A_FOLDER.md`](STAGE_A_FOLDER.md) | Stage a folder: a project folder on the NAS to a client link in one click (the one-folder share the owner asked for on 2026-09-10) |
| [`CLIENT_DELIVERY.md`](CLIENT_DELIVERY.md) | Runbook for handing a client terabytes of footage to download once, without joining the tailnet: stage in Backblaze B2 near the client (TrueNAS Cloud Sync task, scoped read-only key, what to tell them), the shared-Tailscale-node direct route, and why not Funnel, Syncthing, MASV or a port-forward |
| [`DOCKER.md`](DOCKER.md) | The two ways the dashboard container gets its code and its dependencies |
| [`CARDS_DEPLOY.md`](CARDS_DEPLOY.md) | Refreshing Timeline Cards on the NAS: the one code mount that is another repo's checkout, why a copy without a restart changes nothing, and the rollback |
| [`CARDS_TWO_PROJECTS.md`](CARDS_TWO_PROJECTS.md) | Two people in two episodes at once: the landing page, one engine per episode keyed by a slug in the URL, why the cap is a refusal and not an eviction, and the two-engine measurement (section 12) |
| [`RELEASE_PATHWAYS.md`](RELEASE_PATHWAYS.md) | **Read before starting a release.** Which of the two publish pathways applies right now: Alex's terminal, or CI plus `publish_latest.py` |
| [`FILE_MOVES.md`](FILE_MOVES.md) | Moving a file on the server without it coming straight back: the project page's move button, the two-phase command, and why nothing in that path deletes |
| [`HAND_MOVES_ON_THE_SERVER.md`](HAND_MOVES_ON_THE_SERVER.md) | A folder moved by hand on the NAS becomes a recorded move every machine follows: the server diffs its own inventory walks, lane B asks the server where a vanished file went before it trashes anything, and why the breaker still has the last word |
| [`UPLOAD_ONLY_TICK.md`](UPLOAD_ONLY_TICK.md) | The upload-only tick: originals up, nothing down, and why it is "no share" rather than a send-only folder |
| [`ACCOUNT_PAGE_FEATURES.md`](ACCOUNT_PAGE_FEATURES.md) | The spec for the personal /account page (2026-09-25): display name, changing your own password, your browsers, your sync keys, asking a computer to change its fleet-job settings, three new read-only machine settings; schema v58, the wire, and six builder groups with disjoint files |
| [`TRANSFER_SPEED.md`](TRANSFER_SPEED.md) | Where the "18 MB/s" ceiling really is (measured 2026-09-25 from Ruskin's PC, this rig and the NAS): the remote editor's upload tier for lane A, a cap on the Tailscale UDP path for lane B, how bandwidth is shared between editors, what would move each ceiling, and the measurement plan |
| [`MOBILE.md`](MOBILE.md) | The dashboard on a phone: installing it from the browser, what works offline, and what the admin sets up |
| [`ANDROID.md`](ANDROID.md) | The Android APK half of the phone story, and the one symptom it exists for (the app showing a URL bar) |
| [`YTDL_TERMS_AND_QUEUE.md`](YTDL_TERMS_AND_QUEUE.md) | The YouTube downloader's term review and search queue |
| [`CI.md`](CI.md) | What runs on a runner, and what still only runs on the base rig |
| [`PRODUCT_REPO.md`](PRODUCT_REPO.md) | The customer-facing repo, how it is exported, and what is withheld |
| [`PROJECTS_CLEANUP_PLAN.md`](PROJECTS_CLEANUP_PLAN.md) | **A plan, not yet done.** Renaming this repo's folder to `E:\Projects\Editing\ccsync` and sorting the rest of `E:\Projects` into categories: the five things that break silently (the tray's rclone path, the Claude memory directory, the five venvs), what does not change, and the rollback |

## Not losing footage

| Doc | What it is |
|---|---|
| [`SYNC_SAFETY.md`](SYNC_SAFETY.md) | The lane B circuit breaker, `.ccsync-trash` retention, the remove-project gate, and the halt |
| [`SELF_DIAGNOSIS.md`](SELF_DIAGNOSIS.md) | The server's own diagnosis: the `notices` panel, the alert registry and its sink (none/smtp/webhook), the weekly report, and how to add a check |
| [`SERVER_TRIAGE_AGENT.md`](SERVER_TRIAGE_AGENT.md) | The twice-daily server check: a read-only Claude Code run over the dashboard's own evidence, emailed with numbered actions, and a reply that carries them out through a fixed catalogue of dashboard actions |
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
| [`RESILIENCE_SWEEP_2026-08-28.md`](RESILIENCE_SWEEP_2026-08-28.md) | The ten-agent resilience sweep: 201 findings in `resilience-sweep-2026-08-28/`, fourteen themes, and a ranked, waved build list ("green while dead" is one class; the guard usually exists in one of N places) |
| [`USABILITY_RESILIENCE_SWEEP_2026-09-03.md`](USABILITY_RESILIENCE_SWEEP_2026-09-03.md) | The fifteen-agent usability + resilience sweep: 297 findings (16 critical) in `usability-resilience-sweep-2026-09-03/`, nine shapes ("computed, then discarded" is the biggest), a one-vocabulary table, and a six-wave build list; nothing built yet |
| [`SYNOLOGY_PORT_PLAN.md`](SYNOLOGY_PORT_PLAN.md) | The plan behind the second NAS backend |
| [`BROLL_INGEST_PLAN.md`](BROLL_INGEST_PLAN.md) | Drag-and-drop b-roll ingest: the design, the contracts and what was deviated from |
| [`BROLL_PROXY_TIERS_PLAN.md`](BROLL_PROXY_TIERS_PLAN.md) | A better browser preview and an editing proxy for new archive clips, and a Send to Resolve that downloads only a proxy while the project keeps pointing at `P:\Assets\B-roll Archive` (phase 0 is a Resolve spike) |
| [`BROLL_PROXY_TIERS_PLAN_AUDIT.md`](BROLL_PROXY_TIERS_PLAN_AUDIT.md) | The 2026-09-17 audit of that plan: eleven ranked findings, among them the relink pass that would undo phase 3, the detail fields the companion never receives, the geometry the index does not hold, and the citations that point at the wrong file |
| [`MUSIC_INGEST_PLAN.md`](MUSIC_INGEST_PLAN.md) | The same for music, reusing the b-roll machinery, plus what it deliberately does not compute |
| [`MULTI_MACHINE_PLAN.md`](MULTI_MACHINE_PLAN.md) | One person, several computers: the sync plan belongs to a machine (schema v22-v25), the base rig holds no tick, and how an update reaches a machine without its editor clicking |
| [`MULTI_BASE_RIG_PLAN.md`](MULTI_BASE_RIG_PLAN.md) | Wired or remote is a property of the COMPUTER, not the person: an office with several machines cabled to the NAS, and what changes in the wizard, the manifest and the companion |
| [`TREE_LAYOUT_PLAN.md`](TREE_LAYOUT_PLAN.md) | The plan that executes that audit: one layout object published in the manifest (`projects_dir`, `proxy_dir_name`, the `Assets/*` roles, `Youtube`, fixer targets, extensions), plus the Setup step that learns a customer's template from their own sample projects |
| [`SHARED_FOLDERS_PLAN.md`](SHARED_FOLDERS_PLAN.md) | One folder used by two projects: a project's marker declares `includes`, the dashboard resolves them into the selection, lanes A/B run the borrowed subpath, lane C reuses the lender's Syncthing folder with a restricted `.stignore`; no second copy, no relinking |
| [`TREE_LAYOUT_AGNOSTICISM.md`](TREE_LAYOUT_AGNOSTICISM.md) | The 2026-08-19 audit of what a customer can change about the tree by config (root, depth, template folders) versus what is code (`Projects`, `Assets/*`, the `Proxy/` sibling rule that defines the lanes, the archive taxonomy), with sales qualification questions and a costed work list |
| [`TIMELINE-CARDS-INTO-CCSYNC.md`](TIMELINE-CARDS-INTO-CCSYNC.md) | Timeline Cards folded in: the agent into the companion, the page into the dashboard, and the job queue across the fleet (phases 0-4; §9 is what runs where) |
| [`MOBILE_PLAN.md`](MOBILE_PLAN.md) | The plan behind the phone port: one app, no second URL, the web manifest and service worker, and the Android wrapper |
| [`LIBRARY_WALK_PLAN.md`](LIBRARY_WALK_PLAN.md) | Enumerating Resolve clips from the project library file instead of the scripting API, and what "As built" changed |
| [`TRAY_MENU_LATENCY.md`](TRAY_MENU_LATENCY.md) | Why the tray menu sometimes opens late (Windows): the investigation, and which step of the fix is built |
| `../SPEC.md` | The internal architecture document — history, rationale, known flaws |
| `../KNOWN_BUGS.md` | The live defect ledger (numbered entries, per-platform prefixes) |
| `../CLAUDE.md` | Repo conventions, test commands, and the two release pathways |

## Archives — history, not instructions

These record what happened on a specific date, on specific machines. **The
addresses, hostnames and people in them are those of the original deployment**
and are deliberately left as they were; do not copy commands out of them.

| Doc | What it is |
|---|---|
| [`bug-hunt-2026-08.md`](bug-hunt-2026-08.md) | The original August bug-hunt worklist, archived when the fix fleet completed |
| [`bug-hunt-2026-08-11.md`](bug-hunt-2026-08-11.md) | The 127-finding hunt |
| [`bug-hunt-2026-08-14.md`](bug-hunt-2026-08-14.md) | The 94-finding hunt |
| [`bug-hunt-2026-08-21.md`](bug-hunt-2026-08-21.md) | The 78-finding hunt plus the 53-issue design review. Fixed in the repo on 2026-08-21 and **unshipped**: `KNOWN_BUGS.md` CR-46 to CR-67 is what landed, what was deliberately deferred, and which seams were still open |
| [`bug-hunt-2026-09-03.md`](bug-hunt-2026-09-03.md) | The 84-finding sixth fleet hunt (seventeen hunters, five verifiers), fixed the same day as CR-102 to CR-119 |
| [`bug-hunt-2026-09-11.md`](bug-hunt-2026-09-11.md) | The seventh fleet hunt and resilience pass (nineteen hunters incl. two cross-cutting lenses, six verifiers): 131 distinct findings, 10 high, fixed the same day as CR-233 to CR-248 |
| [`bug-hunt-2026-09-11b.md`](bug-hunt-2026-09-11b.md) | The eighth fleet hunt, run the same evening ON the seventh's fix pass (23 hunters incl. six lenses: wire, security, tests, regression): 136 distinct findings, 11 high, 27 of them a same-day fix that did not fix; fixed as CR-249 to CR-266 |
| [`bug-hunt-2026-09-18.md`](bug-hunt-2026-09-18.md) | The ninth fleet hunt, over the unhunted week after the eighth (25 hunters incl. seven lenses, the new one reading proxy tiers end to end; 13 adversarial verifiers): 152 raw, 4 refuted, 132 distinct, 10 high, plus five from the live dashboard. ALL fixed the same day as CR-282 to CR-286 (companion 0.9.75 / dashboard 0.7.50 schema v54, unshipped, dashboard first) bar two declined with reasons; 13 suites green |
| [`bug-hunt-2026-09-18b.md`](bug-hunt-2026-09-18b.md) | The tenth fleet hunt, run the same evening ON the ninth's fix pass (26 hunters incl. seven lenses): 154 raw findings, 14 high (12 distinct), 45 of them a same-day fix that does not fix or half-lands. The twelve highs FIXED the same evening as CR-287 to CR-290 with the orchestrator reading and probing every fix (three sent back, one more defect found in the reading); the 65 mediums verified (44 confirmed, 19 downgraded, 1 refuted) and then 33 of the 34 non-duplicate confirmed ones FIXED by fifteen builders as CR-291 to CR-305, each read by the orchestrator; tree still uncommitted, b-roll schema v13 |
| [`bug-hunt-2026-09-24.md`](bug-hunt-2026-09-24.md) | The eleventh fleet hunt, whole repo in three waves (37 hunters: nineteen bug, ten logic and usability, eight UI): 266 raw findings, 16 high (11 confirmed, 5 downgraded, 0 refuted); raw reports, builder ledgers and fix-wave reviews under `bug-hunt-2026-09-24/` |
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
