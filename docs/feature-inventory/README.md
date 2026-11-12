# CC Sync feature inventory

Written 2026-11-12 at the owner's request: "produce an extremely detailed
list of all the features that this project has, without discussing the
architecture at all. Do not trust the documentation or notes throughout the
code ... to create a briefing doc for a full rebuild of the whole project."

**Status: 29 sections written. Nine are owed: five listed below (24, 31 to 34) and the Footage Sorter (35 to 38). The plan this belongs to is [`../REBUILD_PLAN.md`](../REBUILD_PLAN.md).**

## How to read it

Each numbered file is one slice of the software, listed as behaviour: what a
person can see, press or type, and what a machine does on its own, with the
limits, timings, wording and refusals. One bullet is one behaviour. Nothing
describes how the code is organised; the only pointer back to the code is a
short `(source: file)` tag under each heading so a claim can be checked.

Every section ends with three lists:

- **Looks redundant or overlapping**: features that duplicate each other.
  This is the list to read first when deciding what to cut.
- **Claims the code does not back**: places where a comment or document says
  one thing and the code does another. The inventory records what the code
  does.
- **Could not determine**: what that section could not settle, usually
  because the answer lives in another section's files.

## How it was made, and how far to trust it

- Each section was written by a separate reader told to use the executable
  code as the only source of truth, to read every line of its files, and to
  say exactly which files it read in full and which only in part.
- The readers did not see each other's work, so a feature that spans two
  slices is described from both sides, and a section's "Could not determine"
  list is often answered in another section.
- Nothing here was checked by running the software. It is a reading of the
  code as it stood on 2026-11-12 (ccsync `7a81073`, Editing `94cbab7`).
- Sections 13, 17, 18, 20, 21, 22, 23, 25, 26, 27, 28 and 29 were interrupted
  once (a usage pause) and finished by the same reader from where it stopped.
- Section 21 is in five files: the main file plus four parts in `_parts/`,
  each named at the top of the main file.

## The sections

### The companion (the app on each editor's computer)

| | Section |
|---|---|
| 01 | [Start-up, the main cycle and every action](01-companion-main-app.md) |
| 02 | [Uploading originals, downloading proxies and originals](02-companion-transfer-lanes.md) |
| 03 | [What syncs when, the Syncthing lane, the safety latches](03-companion-sync-control-and-safety.md) |
| 04 | [The tray icon, menus, windows, dialogs, notifications](04-companion-tray-windows-dialogs.md) |
| 05 | [Everything it does with DaVinci Resolve](05-companion-resolve.md) |
| 06 | [Proxies, file moves, camera-card copying, bundled tools](06-companion-proxies-file-moves-copy-tools.md) |
| 07 | [The b-roll send-to-Resolve server, b-roll ingest, local clip indexing](07-companion-broll.md) |
| 08 | [YouTube downloads on the editor's machine; music ingest](08-companion-youtube-and-music.md) |
| 09 | [Every config key, reporting to the server, fleet jobs, self-update, crashes](09-companion-config-reporting-jobs-updates.md) |
| 10 | [Field mode, the footage ledger, the Timeline Cards agent role, camera-card reporting, packaging](10-companion-field-mode-ledger-cards-role-sorter.md) |

### The dashboard (the server people sign in to)

| | Section |
|---|---|
| 11 | [The API, part 1](11-dashboard-api-part-1.md) |
| 12 | [The API, part 2 (including the companion's report and every command in its reply)](12-dashboard-api-part-2.md) |
| 13 | [Every page, panel and control](13-dashboard-pages.md) |
| 14 | [In-browser behaviour, help, the personal account page, personal-data tools](14-dashboard-scripts-help-account-personal-data.md) |
| 15 | [Alerts, notices, invariants, health, the daily triage agent](15-dashboard-alerts-notices-health-triage.md) |
| 16 | [The background cycle, Syncthing management, provisioning, recovery, the NAS back-ends](16-dashboard-collector-syncthing-nas.md) |
| 17 | [Start-up, request gates, sign-in, every setting, the setup wizard](17-dashboard-signin-settings-setup.md) |
| 18 | [Self-update, the package channel, AI providers, the container](18-dashboard-updates-packages-ai-providers-container.md) |
| 19 | [Fleet jobs, and how it hosts Timeline Cards, b-roll, music, YouTube and the footage sorter](19-dashboard-fleet-jobs-and-hosted-apps.md) |
| 20 | [What it remembers, the rules it decides by, what it forgets](20-dashboard-records-rules-retention.md) |

### Installing and running it

| | Section |
|---|---|
| 21 | [Operator scripts for the NAS](21-server-install-and-maintenance-scripts.md) (plus `_parts/21a` to `21d`) |
| 22 | [Editor installers, upgrade and uninstall, the first-run wizard](22-editor-installers-and-first-run-wizard.md) |
| 27 | [Building, signing, publishing and checking releases; CI; the sync benchmark](27-release-tooling-ci-and-benchmarks.md) |

### The hosted apps

| | Section |
|---|---|
| 23 | [B-roll: the search app, its API, client folders, the public share page](23-broll-search-app-and-client-folders.md) |
| 24 | [B-roll: the clip indexing pipeline and the search evaluation tools](24-broll-indexer-and-search-eval.md) |
| 25 | [Music: the search app, its API, the audio indexing pipeline](25-music-search-app-and-indexer.md) |
| 26 | [The YouTube downloader: pages, API, jobs, AI search, download strategies](26-youtube-downloader-service.md) |

### Timeline Cards (the editor, from the Editing repo's `Resolve/MulticamPipeline/editor`)

| | Section |
|---|---|
| 28 | [Every key, controller control, pointer gesture and editing command](28-timeline-cards-keyboard-controller-pointer-commands.md) |
| 29 | [Every screen, panel, control and setting; playback; what works offline](29-timeline-cards-screens-panels-playback-offline.md) |
| 30 | [The transcript panel, English-to-original alignment, reading aids](30-timeline-cards-transcripts-alignment-reading-aids.md) |
| 31 | [Search across transcripts, auto-shorten, the edit chat, translation](31-timeline-cards-search-shorten-chat-translate.md) |
| 32 | [Sending to Resolve, the projects sheet and keep-on-this-device, the video window, the montage builder, markers](32-timeline-cards-resolve-projects-video-montage-markers.md) |
| 33 | [The shelf, gap notes, keep, looks, the lane feature, audio, the Windows and Android apps](33-timeline-cards-shelf-notes-looks-audio-apps.md) |
| 34 | [The editor's server, the cut-list model and the `.cut.md` file format](34-timeline-cards-server-and-cut-list-format.md) |

### The engine behind Timeline Cards (found owed 2026-11-12)

The editor is not self-contained: its server calls a Python engine in the
same repo (`Resolve/MulticamPipeline/multicam_pipeline/cards`, about 38,000
lines without the old page) for the real work of sending a cut to Resolve,
shortening, searching, the chat's edits, translation and the media library.
Section 31's reader could not settle several behaviours for that reason.
Sections 28 to 34 describe what the editor shows and asks for; these two
describe what actually happens.

| | Section |
|---|---|
| 39 | **OWED.** What happens when a cut is sent to Resolve, and the cut-list and project rules behind it (`resolve_engine`, `project_engine`, `project_conform`, `project_diff`, `project_edit`, `project_agent`, `project_pick`, `agent`, `cutlist`, `timecode`, plus the `multicam_pipeline/resolve` package) |
| 40 | **OWED.** The media library, shortening, search, chat edits, translation and the rest (`library_engine`, `shorten`, `chat_edit`, `transcript_search`, `translate`, `corpus`, `text`, `gap_notes`, `offline`, `stores`, `montage`, `fleet_jobs`, `claude*`, `models`, `config`, and the small files) |

Not read: `handler.py`, `server.py`, `page.py` and the `page` folder, which
are the old Timeline Cards page's own server, retired 2026-11-12.

### The Footage Sorter (`E:\Projects\Editing\footage-sorter`, read as its working tree stood on 2026-11-12)

| | Section |
|---|---|
| 35 | [The engine, part 1: scanning, collating, sorting, ingest, suggestions, the catalogue](35-footage-sorter-engine-part-1.md) |
| 36 | [The engine, part 2: the footage ledger, card tracking, audio matching, downloads, thumbnails, moves, automatic backup, audio sync](36-footage-sorter-engine-part-2.md) (audio sync was unfinished and untracked when read) |
| 37 | **OWED.** Every page, screen and control (`public`) |
| 38 | **OWED.** The server, ingest, NAS and cloud parts, the tools and the mover script (`server.js`, `lib`, `ingest`, `nas`, `cloud`, `tools`, `mover.ps1`) |

## Left out on purpose

- **The Footage Sorter app** (`E:\Projects\Editing\footage-sorter`, about
  45,000 lines) is NOT left out any more: the owner asked on 2026-11-12 for
  the rebuild to include it. It is owed as sections 35 to 38
  (`../REBUILD_PLAN.md` has the split). Until then only the dashboard's and
  the companion's sides of it are covered, in sections 10 and 19.
- **The old Timeline Cards page** (`multicam_pipeline/cards/page`). It was
  retired on 2026-11-12. What the dashboard still does for it is in section 19.
- **The rest of the MulticamPipeline repo** (the transcript and canvas
  pipeline, Story Deck). It is not part of CC Sync.

## Where the overlap is, across sections

Each section's own list has the detail. Read together, the same shapes come
up again and again:

- **The same job reachable several ways.** Three ways to install a companion
  update (01), three ways to move the fleet to another build (12, 13), four
  ways to publish a build to one dashboard and four ways to reach the vendor
  feed (27), six places to tick a project (13), six ways to stop a person
  (11), about eight ways to trim a cut and six to move one (29).
- **Work done on both the server and the editor's machine.** YouTube
  downloads (08, 26), music ingest (08, 25) and b-roll indexing (07) each
  exist twice, with hand-off rules between the two copies.
- **One fact reported many ways.** 70 alert kinds, about 35 notice kinds and
  15 invariants, where one problem often surfaces three to five times and is
  mailed twice (15); Health repeats four other pages (13); "why is this
  computer not syncing" is worked out twice in the companion with different
  orderings (01).
- **Per-computer command channels.** Six to ten separate "send this computer
  an instruction until it answers" channels, each with its own expiry and
  clearing rule (12, 20).
- **Settings with several sources.** Site settings come from five places that
  override each other, and NAS settings have two names each (17, 21);
  credentials are juggled four ways in the companion (09).
- **Safety machinery around simple acts.** About ten interlocking mechanisms
  to swap one code folder on a dashboard update (18); three overlapping crash
  and rollback mechanisms in the companion (09); seven "do less when idle"
  mechanisms in sync (03).
- **Features that are off, dormant or unreachable but still carried.** The
  old Timeline Cards machinery (19), the Timeline Cards agent role (10), the
  requester-first YouTube system when its switch is unset (26), the AI
  command-line tool wizard behind two switches (18), per-project NAS groups
  (16), dead controller behaviours (28), and leftover panels and styles from
  earlier looks (14, 29).
- **Side services living in the tray app.** Besides syncing, the companion
  hosts camera-card reporting, a field-backup web page, a footage ledger, the
  job runner, three indexers and a second local web server (01, 10).
