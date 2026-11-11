# Audit 2026-11-10 - every finding, one line each

Generated from `hunters/*.json` (merged in `results.json`). The detail, the evidence and the suggested change for each id are in `hunters/<hunter>.md`. Severity and confidence are the hunter's own; only the highs were re-read by the orchestrating session (see `../AUDIT_2026-11-10.md`).

## comp-app

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| comp-app-1 | medium | perf | confirmed | S | The tray rebuilds sync_guard() every 2 s, and that walks every retained ingest staging folder on the sync drive |
| comp-app-2 | low | idle | confirmed | S | Two net use (+ subst) probes per media-tree tick when one is enough |
| comp-app-3 | low | resilience | confirmed | S | Seven workers share one try in start(); one raising silently skips the rest under the wrong name |
| comp-app-4 | low | streamline | confirmed | M | sync_guard() is 282 lines of 26 hand-written try blocks rebuilt in full by two threads; a table would allow per-section cadence |

## comp-core

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| comp-core-1 | medium | perf | confirmed | S effort | The manifest walk spends ~85% of its CPU building pathlib objects, on every machine, every 300 s |
| comp-core-2 | medium | perf | confirmed | M effort (both sides of the wire, additi | An unchanged manifest is still re-sent in full every 10 minutes, and one changed project re-sends all of them |
| comp-core-3 | medium | bug | confirmed | S effort | Once `_fit_payload` has trimmed the manifest, it is never suppressed again: rebuilt, shed and re-sent every heavy tick, with a WARNING every minute |
| comp-core-4 | medium | bug | confirmed | S effort | One byte over the budget strips the per-file lists from EVERY ticked project, not just enough of them |
| comp-core-5 | low | perf | confirmed | S effort | A changed heavy section is serialised three times per report |
| comp-core-6 | low | idle | plausible | S effort | On macOS the idle probe spawns `ioreg` on every report tick, uncached |

## comp-sync

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| comp-sync-1 | medium | perf | confirmed | S (a) / M (b) | Lane B still spends a full-width SSH pool and a recursive NAS listing on every project every pass; CR-381's cheap half was never applied to it |
| comp-sync-2 | medium | bug | confirmed | S | CR-381's clean-project skip survives an untick/re-tick and a full <-> upload-only flip, so lane A skips files it has never looked at for up to 2 h |
| comp-sync-3 | medium | bug | confirmed | S-M | The skipped-exists alarm and the orphan .partial report hold only the LAST project scanned; tree-wide scans run N times per scan pass |
| comp-sync-5 | medium | idle | confirmed | S (adaptive) / M (events) | The Syncthing lane polls 3 + 2N REST calls every 15 s for the life of the process, including one expensive /rest/db/status per folder |
| comp-sync-4 | low | perf | confirmed | S | Every lane C turn PATCHes the folder config even when it is already running, and reads the full Syncthing config three times per project |
| comp-sync-6 | low | disk-growth | confirmed | S | Breaker and project-dir state files are rewritten every pass when nothing changed; the breaker persists the OLDEST 512 scopes and never prunes unticked ones |

## comp-resolve

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| comp-resolve-1 | medium | perf | confirmed | M | The 120 s media-tree refresh re-reads every pool clip's proxy state through Resolve, unchanged pool or not |
| comp-resolve-2 | medium | perf | confirmed | M | Every bridge call opens a brand-new scriptapp() connection (1/s with the Cards role, every 3 s from the watcher, per enrichment chunk, per relinked clip) |
| comp-resolve-3 | medium | perf | confirmed | S | The watcher stats and realpaths every timeline clip every 3 s, even when the Resolve answer came from the poll cache |
| comp-resolve-4 | medium | perf | confirmed | S | A project switch runs one full media-pool walk per pending file move, synchronously on the watcher thread |
| comp-resolve-5 | medium | perf | confirmed | S | Every relink builds Resolve's full 60-key property dict two to four times plus a fresh connection, while the probed one-arg reader sits unused |
| comp-resolve-6 | low | perf | confirmed | S | The undo journal rewrites the whole JSON file for every entry (quadratic) |
| comp-resolve-7 | low | idle | confirmed | S | The CR-68 probe snapshots every process even when nothing listens on 1144, and the disconnection text spawns tasklist every 30 s on top |
| comp-resolve-8 | low | idle | confirmed | S | The Cards role's refusal watchdog runs PowerShell + WMI every 60 s for as long as a standalone agent is running |
| comp-resolve-9 | low | perf | plausible | S | plan_relinks re-stats up to four proxy candidates for every clip without a working proxy on every 120 s pass, with no memory |
| comp-resolve-10 | low | perf | plausible | S | Every companion start walks the whole of local_root for *.ccsync-tmp, which on the base rig and wired rigs is the NAS share |

## comp-ui

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| comp-ui-1 | medium | perf | confirmed | S | Every card lookup that finds a copy the ledger mirror now has rewrites and fsyncs the whole local-copies file, once per file |
| comp-ui-2 | medium | perf | confirmed | S | A card verdict opens a fresh SQLite connection, re-runs the schema, and linearly scans every local copy, once per file on the card, every 20 s |
| comp-ui-3 | low | leak | confirmed | S | A dialog that raises on a tray click thread leaves its Tcl interpreter pinned for the life of the process |
| comp-ui-4 | low | perf | plausible | S | The menu fingerprint carries lane C's live byte and file counts, so the menu is rebuilt every tick while lane C uploads |
| comp-ui-5 | low | idle | confirmed | S | The 2 s tray tick re-reads and re-parses site.json three times, and the pulse thread wakes 2.7 times a second with nothing to pulse |

## comp-media

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| comp-media-1 | medium | perf | confirmed | S | Ingest asks tasklist before every extracted frame: the Resolve probe costs 2.7x the frames it guards |
| comp-media-2 | medium | perf | confirmed | S | The ingest state file is re-serialised whole, pretty-printed, at every stage of every item: O(n^2) bytes per batch |
| comp-media-3 | medium | idle | confirmed | S | The music page's 30 s Resolve-status poll re-launches the onefile companion exe every time, even with Resolve closed and the tab hidden |
| comp-media-4 | medium | perf | plausible | M | Ingest uploads spawn two rclone processes (copyto + lsjson verify) per artifact, five artifacts per clip, one at a time |
| comp-media-5 | low | perf | confirmed | S | Startup walks the whole tree twice for two leftover-file sweeps that were meant to share one walk |
| comp-media-6 | low | disk-growth | confirmed | S | llama-server's log is appended for the life of the install |

## comp-jobs

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| comp-jobs-1 | medium | perf | confirmed | S | The peaks recipe holds the whole decoded audio in RAM, then makes five more copies of it |
| comp-jobs-2 | medium | idle | confirmed | S | Every job-runner tick spawns tasklist 1-4 times, even when nothing can be claimed |
| comp-jobs-3 | medium | bug | confirmed | S | A stale offer plus an unreachable dashboard: a claim attempt and a full traceback every 20 s, and the gate says ready |
| comp-jobs-4 | low | concurrency | plausible | S | Two machines can write the same .partial in the shared vault after a lease expiry, and the loser deletes the winner's file |
| comp-jobs-5 | low | perf | confirmed | S | Media recipes spawn one more ffprobe than they need |

## comp-field

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| comp-field-1 | high | bug | confirmed | S | A card folder that cannot be read vanishes from the listing, and the card is then 'Safe to format' |
| comp-field-2 | high | bug | confirmed | S | 'Safe to format' ignores originals whose extension is not on an allow-list (Nikon N-RAW .NEV and others) |
| comp-field-3 | high | perf | confirmed | S | The verdict rewrites field-local-copies.jsonl with fsync once per file after a sync: 28 s for a 2,000-file card |
| comp-field-4 | medium | perf | confirmed | M | Every verdict reopens SQLite per file, re-reads field-state.json six times per file and scans all local copies per file: 4.4 s per 2,000-file card every 20 s |
| comp-field-5 | medium | bug | confirmed | S | Cards in fixed readers (CFexpress B) are reported to the sorter but cannot be copied by the companion or the field page |
| comp-field-6 | medium | perf | confirmed | S | The ledger outbox is quadratic to flush and fully re-parsed on every field-page poll |
| comp-field-7 | medium | perf | confirmed | M | The mirror is keyed on the volumes plugged in now: every card in or out re-pulls everything (NAS included) and deletes away drives' copies |
| comp-field-8 | medium | bug | plausible | S | Physical-disk key cached by drive letter for the process lifetime: two partitions of one disk can count as two copies |
| comp-field-9 | medium | perf | confirmed | S | A removable volume holding footage is re-listed in full and re-posted every 10 s whenever its free space moves |
| comp-field-10 | medium | bug | plausible | M | The Python copier's 'read back in full' verify reads the OS page cache, not the media |
| comp-field-11 | low | idle | confirmed | S | TeraCopy's wait spawns tasklist every 5 s per lane for the whole copy |
| comp-field-12 | low | perf | plausible | M | Every lane reads the whole card on its own; three destinations read the card three times at once |
| comp-field-13 | low | streamline | confirmed | S | Proxy-by-name rule has drifted from the ledger's, and the field page never uses the server's rules |

## dash-db

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| dash-db-1 | medium | perf | confirmed | M | Every machine's unchanged manifest and media tree are deleted and rewritten in full every 10 minutes |
| dash-db-2 | medium | disk-growth | plausible | S | Overlapping long backlog reads can starve WAL checkpoints, and the WAL file never shrinks |
| dash-db-3 | low | perf | confirmed | S | editor_media and media_tree_clips store a long TEXT composite key twice (rowid table + autoindex) |
| dash-db-4 | low | perf | confirmed | S | The hourly prune full-scans the largest tables while holding the write lock |
| dash-db-5 | low | streamline | confirmed | S | lane_report_history and completion_history are written and pruned but nothing displays them |
| dash-db-6 | low | perf | confirmed | S | The home page computes the fleet backlog three times per render, and each pair's download diff twice |

## dash-api

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| dash-api-1 | medium | perf | confirmed | S (companion compare) / M (ETag) | The selection reply re-sends the fleet-wide project_roots map every 30 s, and its per-response timestamp defeats the companion's write-on-change cache |
| dash-api-2 | medium | concurrency | confirmed | S | The report holds the database write lock across a filesystem walk of the Projects tree (CR-379 rival check) |
| dash-api-3 | low | perf | confirmed | M | standins_known re-sends up to 200 archive paths on every report reply to every machine |
| dash-api-4 | low | perf | confirmed | S | Two to three SQLite opens per companion request where one is needed |
| dash-api-5 | low | idle | plausible | M | Each light report writes about 28 KB of WAL, much of it re-stamping unchanged state |

## dash-collector

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| dash-collector-1 | medium | idle | confirmed | S | The self-diagnosis pass runs on every 15 s cycle and costs 18 write transactions and ~83 KB of WAL when nothing has changed |
| dash-collector-2 | medium | bug | confirmed | S | [ OK ] on WHAT THE SERVER CHECKS needs only that a kind was evaluated once, ever: a check that now raises every cycle, or a blind pass, still reads OK |
| dash-collector-3 | medium | disk-growth | confirmed | S | remoteneed deletes and re-inserts every unchanged missing-files list every minute |
| dash-collector-4 | medium | bug | plausible | S | The inventory skip-signature is directory mtimes only, so a file caught mid-copy keeps its partial size and mtime until something else in that project changes |
| dash-collector-5 | medium | perf | confirmed | M | The 8-projects-per-cycle inventory window is spent on unchanged projects too, so 'is it on the server' lags 3 h today and ~16 h at 500 projects |
| dash-collector-6 | low | perf | confirmed | S | Invariant 10 (proxy_pairs) re-reads every nas_media row of every project every 15 minutes even when no inventory changed |
| dash-collector-7 | low | idle | confirmed | S | Syncthing's pending-devices list is fetched on every cycle (~7,900 GETs a day) for a check whose threshold is 24 hours |

## dash-web

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| dash-web-1 | medium | concurrency | confirmed | M (mechanical, ~45 routes) | About 45 `async def` UI routes run their SQLite writes on the event loop; one click during a collector write freezes every request on the dashboard for up to 5 s |
| dash-web-2 | medium | perf | confirmed | S for (a); M for (b)+(c)+(d) | The home page and its polls rebuild the whole projects view 12 times a minute per open tab, and the page itself builds every view twice |
| dash-web-3 | low | perf | confirmed | S | The service worker revalidates content-hashed, immutable assets on every navigation and rewrites them into CacheStorage each time |
| dash-web-4 | low | perf | confirmed | M | Five `@app.middleware("http")` (BaseHTTPMiddleware) layers: +0.9 ms on every request and half the throughput on every streamed byte |
| dash-web-5 | low | perf | confirmed | S-M | Each authenticated request opens a fresh SQLite connection on the event loop just to look up the session; connection setup is 25-75 % of a poll's server time |
| dash-web-6 | low | perf | confirmed | S | PRAC-72's missing compression is wider than the transfers page: every home poll and the cold static load ship uncompressed |
| dash-web-7 | low | idle | confirmed | S | tab_memory.js saves the scroll position after every poll swap: a forced layout and two storage writes every ~2 s on a visible tab |

## dash-mounts

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| dash-mounts-1 | high | perf | confirmed | S | A video seek or an abandoned media request keeps streaming the rest of the file: /cards and /cards/edit never notice the browser has gone |
| dash-mounts-2 | medium | perf | confirmed | S | Every /broll, /music and /sorter request opens a fresh SQLite connection on the event loop to ask is_admin (local accounts), ~69 ms beside any busy thread |
| dash-mounts-3 | medium | perf | plausible | S | Gear identify keeps every earlier photo in the hot CLI conversation (quadratic input over 40 photos), and queued photos each hold a shared threadpool worker |
| dash-mounts-4 | medium | leak | plausible | S | Nothing caps how many Claude Code CLI processes Timeline Cards starts inside the dashboard container |
| dash-mounts-5 | low | perf | confirmed | S | The SDK path builds a new Anthropic client (and connection pool) per call and never closes it |
| dash-mounts-6 | low | resilience | plausible | S | A stop that lands between Popen and self._proc = proc leaves the new editor's child running and unflushed |

## dash-ops

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| dash-ops-1 | medium | perf | confirmed | S | The AI provider resolver probes EVERY CLI, below the winner too, with no single-flight, on the request path |
| dash-ops-2 | medium | disk-growth | confirmed | S-M | Every OTA apply copies every database twice, including a ~500 MB b-roll index it almost never migrates, and keeps up to eight such copies |
| dash-ops-3 | low | disk-growth | confirmed | S | Interrupted downloads on the two UNATTENDED paths leave staging files that nothing sweeps |
| dash-ops-4 | low | concurrency | plausible | S | The sign-in pty master fd is closed from two threads without the session lock, and while the reader thread may still read it |
| dash-ops-5 | low | deploy | confirmed | S | The release runbook restarts the dashboard to force a feed check that a button already does, and soaking/staged records wait a whole poll interval |

## web-broll

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| web-broll-1 | medium | perf | confirmed | S | Public share media requests re-resolve the whole folder on every request after an id-renumbering rebuild, and never heal |
| web-broll-2 | medium | perf | confirmed | S | Every card downloads its full sprite sheet up front; the share page does it for the whole folder |
| web-broll-3 | medium | leak | confirmed | S | Semantic index rebuild peaks at ~3x the matrix in the dashboard process on every search_generation bump |
| web-broll-4 | low | perf | confirmed | S | Per-search overhead: two COUNTs over embeddings, all visible ids into a Python set, a Python mask, before an 8 ms matmul |
| web-broll-5 | low | perf | confirmed | S | Editor-side posters and sprites carry no Cache-Control, so every render revalidates every image |
| web-broll-6 | low | perf | confirmed | S | The detail route lists the archive folders twice per open |
| web-broll-7 | low | idle | confirmed | S | The ingest panel keeps polling at full rate in a background tab |
| web-broll-8 | low | streamline | confirmed | M | style.css exists three times (b-roll, music, ytdl), ~70% shared; the client viewer loads the whole editor sheet |

## idx

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| idx-1 | high | bug | plausible | S | Frames now come from the 1080p proxy at full size: about twice the local VLM's image tokens, and 8- and 9-frame windows go past the 16k context |
| idx-2 | medium | perf | confirmed | M | The packet count that costs a second full NAS read of every original is already printed by the proxy encode |
| idx-3 | medium | perf | confirmed | S | The API describe path never hits the prompt cache: the ~3k-token instruction block sits after the images, with the per-window sheet list near its top |
| idx-4 | medium | perf | confirmed | M | Offline backfill pays full price: the Message Batches API (half price) is not used |
| idx-5 | medium | bug | plausible | S | anthropic.max_tokens 8000 sits below a third of the archive's historical outputs; a truncated answer costs two paid calls and then marks the clip error |
| idx-6 | low | streamline | confirmed | S | The cost estimate and alias table lag the price list: sonnet-5 is costed 50% high |
| idx-7 | low | bug | confirmed | S | usage.jsonl takes concurrent appends without a lock; the live file has a torn line, and the documented forecast snippet crashes on it |
| idx-8 | low | resilience | confirmed | S | An account-wide stop in the middle of a clip throws away the windows already paid for |
| idx-9 | low | perf | confirmed | S | A rescan writes and commits every unchanged file |
| idx-10 | low | idle | confirmed | S | A music sweep with nothing changed still loads CLAP onto the GPU and re-scores the whole library |

## web-music

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| web-music-1 | medium | idle | confirmed | S | An open /music tab spawns a Resolve worker child on the editor's machine every 30 s, forever |
| web-music-2 | medium | perf | confirmed | M | Fleet-ingested tracks never get a preview proxy, so every preview streams the ~60 MB original, and replays re-download it |
| web-music-3 | medium | leak | confirmed | S | The ONNX text tower holds ~560 MB in the dashboard process for its whole life after one search |
| web-music-4 | medium | perf | confirmed | M | The search index costs ~27 KB/track resident and ~2x that on every rebuild: 1.34 GB held and 2.84 GB peak at 50k tracks, with no single-flight |
| web-music-5 | low | perf | confirmed | S | Text search pools window scores in a Python loop: 4x slower than numpy at scale |
| web-music-6 | low | idle | confirmed | S | An open player pane redraws the waveform and rewrites two DOM nodes 60 times a second, even when paused |
| web-music-7 | low | perf | confirmed | S | The SPA's 205 KB of static files are re-read from disk and re-sent uncompressed on every /music load |
| web-music-8 | low | perf | confirmed | S | Every metadata read scans the tracks table with its 2 KB embedding inline, and browse sorts without an index |
| web-music-9 | low | streamline | confirmed | M | The ingest-batch lease machinery exists twice (music and b-roll) and is kept in step by hand |
| web-music-10 | low | disk-growth | confirmed | S | The ingest ledger is never pruned, and the name checks scan all of it on every result |

## web-ytdl

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| web-ytdl-1 | high | resilience | plausible | S | A live stream wedges the fleet-wide server worker with no bound (pasted /live/ link, or a ticked live result) |
| web-ytdl-2 | medium | streamline | confirmed | M | The two executors' conversion step has drifted: the server's ffmpeg/ffprobe have no timeout and cannot be cancelled |
| web-ytdl-3 | medium | perf | confirmed | S | Every download-phase poll re-fetches the whole manifest (296 KB for 400 candidates) to draw 40 rows, uncompressed, in hidden tabs too |
| web-ytdl-4 | low | idle | confirmed | S | The poll never stops at terms_review and re-renders the checkbox list every tick |
| web-ytdl-5 | low | perf | confirmed | S | Filter and enrich phases commit once per row (927 ms vs 11 ms for 400 rows) |
| web-ytdl-6 | low | perf | plausible | S | Each review-grid checkbox click rebuilds the whole grid twice |
| web-ytdl-7 | low | disk-growth | confirmed | S | Search candidates are kept forever: job_videos / job_video_terms are never pruned |

## ops-server

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| ops-server-1 | medium | disk-growth | confirmed | S | Pre-op snapshots (ccsync-pre-*) never expire, so nothing deleted after one is ever freed |
| ops-server-2 | medium | resilience | confirmed | S | check_health.py dies with a traceback when the NAS is unreachable, skipping every later check |
| ops-server-3 | medium | bug | confirmed | S | publish_db on Synology runs the swap without the DSM PATH, so docker exec / synoacltool are not found and every publish is refused |
| ops-server-4 | medium | security | confirmed | S | The Syncthing API key and GUI password are taken on the command line, and the runbook tells operators to type them there |
| ops-server-5 | low | perf | confirmed | S | One full SSH connect + password auth per remote command: 7 handshakes for a b-roll publish, 3 for a new project, one redundant |
| ops-server-6 | low | bug | plausible | S | run_ssh reads stdout to EOF before stderr: more than 2 MiB of stderr wedges the call until the inactivity timeout |
| ops-server-7 | low | resilience | plausible | S | The 500 MB b-roll index is staged in /tmp on TrueNAS, the place the deploy moved its big artefacts away from |
| ops-server-8 | low | streamline | confirmed | S | bench/ no longer measures the lanes the companion ships, yet is installed and tested on every CI run |

## ops-install

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| ops-install-1 | medium | bug | confirmed | S | The bootstrap re-fetches the site manifest the wizard already holds, and three keys come ONLY from that second fetch |
| ops-install-2 | medium | streamline | confirmed | L | Windows and macOS bootstraps implement the same steps twice and have drifted; move the drifted steps into the companion CLI |
| ops-install-3 | low | perf | plausible | S | macOS install waits for Resolve to quit twice, back to back, each up to 180 s |
| ops-install-4 | low | disk-growth | confirmed | S | The Windows pinned download leaves ~130 MB of zips and extracted folders in %TEMP% |
| ops-install-5 | low | bug | confirmed | S | A hand re-run of windows_bootstrap.ps1 with -CompanionExeSource aborts at step 9 while the companion is running |
| ops-install-6 | low | perf | confirmed | S | windows_upgrade.ps1 runs a full recursive ACL reset inside the companion-down window every upgrade |
| ops-install-7 | low | deploy | confirmed | S | build_editor_package's onboard.exe staleness check ignores four bundled inputs |
| ops-install-8 | low | bug | confirmed | S | The base-rig wizard path never switches on Resolve's External scripting |
| ops-install-9 | low | disk-growth | confirmed | S | Locked exe copies renamed to .stale-<epoch> by the clean slate are never pruned |

## deploy-release

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| deploy-release-2 | high | deploy | confirmed | S | With the linux CI job off, 'ci.yml green on the exact commit' no longer covers the dashboard/server/tools/web suites or the CRLF, licence and notices gates, yet release_customers.py publishes a dashboard bundle to every customer on it |
| deploy-release-1 | medium | deploy | confirmed | S | ship.cmd runs the whole dashboard suite twice, the first time serially (~21.5 min per ship); in image mode the first run guards a deploy that does not happen |
| deploy-release-3 | medium | deploy | confirmed | M | Pathway A builds a second, different binary of a commit CI already built; the studio soaks bytes no customer gets and one version names two binaries |
| deploy-release-4 | medium | deploy | confirmed | M | The studio gets a feed release after up to a day plus ~14 min per 50 MB from GitHub's CDN; the 1.2 s direct PUT lives only in an off-repo scratchpad helper |
| deploy-release-5 | low | streamline | confirmed | S | A companion ship means six hand edits of version strings (two companion copies, four installer copies forced every ship by SHIP-4) |
| deploy-release-6 | low | deploy | confirmed | S | publish_latest fails, and recommends --allow-red-ci, when CI on the newest build's commit is merely still running - the normal state for minutes after every push now |
| deploy-release-7 | low | deploy | confirmed | S | The push-triggered release builds still install the dashboard venv, ffmpeg and rclone for a test run they skip |
| deploy-release-8 | low | deploy | confirmed | S | CI runs twice per commit when a feature branch and main point at the same sha, and the publish gate accepts whichever run went green |
| deploy-release-9 | low | streamline | confirmed | S | The release docs and advisories still describe dispatch-only 36-minute builds and Mac-side publishing |
| deploy-release-10 | low | deploy | confirmed | S | release-dashboard.yml is still dispatch-only while release_customers.py requires it green on the release sha |

## deploy-nas

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| deploy-nas-1 | high | deploy | confirmed | S (docs) / M (guard) | The recipe's --mode image deletes and recreates the app on every Cards/Sorter deploy, which is the only reason the stale-digest trap exists |
| deploy-nas-2 | medium | deploy | confirmed | S | The premature health check FAILED is a fixed 10 s sleep followed by one probe, and on the recreate path it ends the run before the 150 s poll runs |
| deploy-nas-3 | medium | deploy | confirmed | S | In image mode the health gate demands the repo's dashboard VERSION, which an image-mode deploy never ships: 150 s of polling and exit 1 whenever the repo is ahead or an OTA bundle runs |
| deploy-nas-5 | medium | deploy | confirmed | S-M | Every run re-ships BOTH Cards and Sorter trees, so each recipe needs the other tree's live commit read by hand, and the Cards recipe now ships Sorter master unpinned |
| deploy-nas-8 | medium | deploy | plausible | S | Restart to pick up new vault data runs the full deploy and takes the whole dashboard down, when a restart or a per-episode close/open would do |
| deploy-nas-10 | medium | streamline | confirmed | M | A Cards or Sorter deploy runs the whole site provisioning and needs every secret to change one read-only directory |
| deploy-nas-4 | low | perf | confirmed | S | Every remote command opens a new SSH connection: about 31 handshakes per deploy, plus one per health poll |
| deploy-nas-6 | low | deploy | confirmed | S | The create-only host-dir step runs chown -R over all of <root>/data and <root>/venv on every deploy |
| deploy-nas-7 | low | streamline | confirmed | S | Cards ships the whole MulticamPipeline commit minus a deny-list: 479 files where the mount needs about 160 |
| deploy-nas-9 | low | deploy | confirmed | S | A routine run docker pulls an image it will not run |

## tests-ci

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| tests-ci-1 | medium | perf | confirmed | M effort (call sites build Settings inli | Every dashboard test migrates a fresh SQLite DB from schema v0 |
| tests-ci-2 | medium | bug | confirmed | S effort | test_deploy_resilience opens a real socket to the studio NAS (site.toml 192.168.0.102) with TRUENAS_PW="pw" |
| tests-ci-3 | medium | perf | confirmed | S effort | Three SYNC-3 express tests each stall 10 s and now pass via a timed-out fake spawn |
| tests-ci-4 | medium | deploy | confirmed | S effort | The companion and dashboard suites run serially in run_all_tests.ps1 |
| tests-ci-5 | medium | deploy | confirmed | S effort | CI runs the full matrix for duplicate pushes, docs-only commits and an unchanged nightly SHA; select_suites.py is not wired in |
| tests-ci-6 | medium | resilience | confirmed | S effort | With the linux job off, a green CI run gates no dashboard, server or web suite |
| tests-ci-7 | medium | concurrency | plausible | S-M effort | Six dashboard tests sit exactly on the 10 s SQLite busy_timeout on CI |
| tests-ci-10 | medium | deploy | plausible | S effort | The Cards gate runs every kind and every python suite one at a time |
| tests-ci-8 | low | perf | plausible | S effort | A one-off ~35 s stall per process on the macOS runner |
| tests-ci-9 | low | perf | confirmed | S effort | Fixed real sleeps pinned in two run.sh tests and one rclone test |

## cards-library

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| cards-library-1 | high | perf | confirmed | S | Waveform peaks: one unbounded thread + ffmpeg per clip, each buffering the whole decoded clip in the dashboard process |
| cards-library-2 | medium | leak | confirmed | S | ProjectAgentEngine runs LibraryEngine.__init__ twice: orphan GoogleTranslator thread + cache per engine, every store read twice |
| cards-library-3 | medium | leak | confirmed | S | A cooperative stop is cheap: ProjectAgentEngine.stop skips LibraryEngine.stop and _lib_worker has no exit |
| cards-library-4 | medium | perf | confirmed | M | Publish ring keeps 32 full copies of every card dict (~57 MB at 1,522 cards); frames cache duplicates token lists |
| cards-library-5 | medium | disk-growth | confirmed | S | timeline_plans.history.jsonl appends the whole op list per rev: quadratic, never pruned, never read |
| cards-library-6 | low | perf | confirmed | S | timeline_place.json rewritten whole, indented, ~1/s per device while the lane plays |
| cards-library-7 | low | concurrency | plausible | S | NoteStore and BinStore unlocked with one fixed .tmp: concurrent saves can raise or corrupt; a corrupt file loads as empty |
| cards-library-8 | low | resilience | confirmed | S | Extraction/proxy failures are sticky for the engine's life, even across a root switch |
| cards-library-9 | low | idle | confirmed | S | Library sweep polls Postgres every 2 s forever, 4 round trips per tick, with or without viewers |
| cards-library-10 | low | resilience | confirmed | S | Undo of an in-place library edit is two transactions; failure between them half-restores the timeline; backups never pruned |
| cards-library-11 | low | disk-growth | confirmed | S | remote_audio caches never pruned; crashed encodes leave .tmp files |

## cards-resolve

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| cards-resolve-1 | medium | resilience | confirmed | S | LibraryReader holds one open transaction on Resolve's live project library for the life of the process |
| cards-resolve-2 | medium | idle | confirmed | M | The 10 Hz loop serialises the whole state twice every tick whether or not anything changed or anyone watches |
| cards-resolve-3 | medium | idle | confirmed | M | Full 1 Hz sweep (~1,350 RPCs under the shared API lock) runs with no page open and during playback |
| cards-resolve-5 | medium | concurrency | confirmed | S | Library conform passes allow_open=True after proving the project closed, disabling the writer's lock gate for the race it exists for |
| cards-resolve-7 | medium | bug | plausible | S | Agent never re-binds its project database after the editor switches library |
| cards-resolve-4 | low | perf | confirmed | S | bridge.sweep_items() is called every second even when every item's detail is cached |
| cards-resolve-6 | low | security | confirmed | S | DB writer's real-library protection is a hard-coded denylist of five names |
| cards-resolve-8 | low | perf | confirmed | S | Agent uploads the whole ~680 KB state uncompressed on every version change |
| cards-resolve-9 | low | disk-growth | confirmed | S | Cut-list history grows without bound as full uncompressed copies in the vault |
| cards-resolve-10 | low | concurrency | plausible | S | project_pick.doc_save is an unlocked read-merge-write through one fixed .tmp name |
| cards-resolve-11 | low | resilience | plausible | S | ripple_keys.ahk checks the foreground window once per batch, by process, not per key |

## cards-server

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| cards-server-1 | medium | perf | confirmed | S | Every warm edit-chat turn re-sends a ~46k-character digest of the whole cut list, and the conversation keeps every copy |
| cards-server-2 | medium | perf | confirmed | S | The 1.67 MB page goes out in full on every load: no validator, and the gzip is redone for each request |
| cards-server-3 | low | idle | confirmed | M | Every pop-out panel window runs its own state poll loop |
| cards-server-4 | low | disk-growth | confirmed | S | Every Claude JSON turn leaves a temp directory and answer file that nothing deletes |
| cards-server-5 | low | perf | confirmed | S | The transcript-search corpus re-walks the episode tree six times to answer one /api/search/scopes |
| cards-server-6 | low | disk-growth | confirmed | S | A failed whisper corpus run leaves its scratch folder in %TEMP% |
| cards-server-7 | low | disk-growth | plausible | S | The two translation caches only ever grow, one entry per distinct text a cut has ever had |

## cards-page-a

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| cards-page-a-1 | medium | perf | confirmed | M | The edit view rebuilds every row by innerHTML on every new state version |
| cards-page-a-2 | low | idle | confirmed | S | An unchanged poll still repaints the whole lane canvas and walks every card row |
| cards-page-a-3 | low | perf | plausible | S | The spoken-word highlight rewrites the playhead card's innerHTML on every poll |
| cards-page-a-4 | low | perf | plausible | S | flip() interleaves layout reads with style writes over every card near the viewport |

## cards-page-b

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| cards-page-b-1 | high | bug | confirmed | S | Two `function oflAutoOn()` in one script: the app-only "keep what is open" runs in every desktop and Android browser |
| cards-page-b-2 | medium | perf | confirmed | S | The automatic keep re-downloads every video proxy every ten minutes |
| cards-page-b-3 | medium | bug | confirmed | S | Updating one episode's worker deletes every other episode's offline shell |
| cards-page-b-4 | medium | disk-growth | confirmed | M | Downloaded media is never evicted: [ REMOVE ] orphans it while any other copy exists, and old copies pile up |
| cards-page-b-5 | medium | resilience | confirmed | S | A quota failure while queuing an offline edit is swallowed and the edit is reported as made |
| cards-page-b-6 | medium | disk-growth | plausible | S | Search answer cache in localStorage is per episode root and never pruned across roots, on the dashboard's shared origin |
| cards-page-b-7 | low | perf | confirmed | M | Every offline edit rewrites the whole queue and the whole state |
| cards-page-b-8 | low | streamline | confirmed | M | In the apps every kept clip is stored twice on the device |
| cards-page-b-9 | low | bug | confirmed | S | The shortening duck stacks `timeupdate` listeners and cuts the next duck short |

## cards-storydeck

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| cards-storydeck-1 | high | security | confirmed | M | The Windows app installs an unsigned .exe from a vault folder any editor can write |
| cards-storydeck-2 | medium | idle | confirmed | S | Inside both native apps the page polls the NAS 4 times a second (and the Windows window keeps doing it when minimised) |
| cards-storydeck-3 | medium | perf | confirmed | M | The Android app opens a new TCP + TLS connection for every request; the Windows app re-uses them (the two have drifted) |
| cards-storydeck-4 | medium | idle | plausible | S | Android keeps probing a down server every 5 s with the app in the background, and the page's timers are never paused |
| cards-storydeck-5 | medium | perf | confirmed | M | Story Deck's fan-out stages resend a ~23k-token preamble on every call, uncached through the CLI door |
| cards-storydeck-6 | low | disk-growth | confirmed | S | Story Deck keeps every proposal forever and rewrites the whole board on every event |
| cards-storydeck-7 | low | deploy | confirmed | S | The Cards deploy ships 3.7 MB of files the /cards mount never imports, and CARDS_DEPLOY.md misstates what ships |
| cards-storydeck-8 | low | streamline | confirmed | S | Story Deck screenshots: 46 MB in the tree, 78 MB in history |
| cards-storydeck-9 | low | security | confirmed | S | The Android release build always enables WebView remote debugging |

## editor-client

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| editor-client-1 | medium | perf | confirmed | M | On a phone or landscape phone every playback frame is a full render |
| editor-client-2 | medium | perf | confirmed | S | Kept-clip audio windows resampled on the main thread, 25 ms per 5 s window |
| editor-client-3 | medium | bug | confirmed | S | Peaks fetched twice per clip; lane level target drifts from the engine's (q1-k5 shape) |
| editor-client-4 | low | idle | confirmed | S | Video tab frame loop runs while shown even when paused; rewrites DOM every frame in a gap |
| editor-client-5 | low | perf | confirmed | S | Two MutationObservers watch the whole editor or body for one header and one panel |
| editor-client-6 | low | perf | plausible | M | Card drag does an O(n) layout walk per pointermove with scroll writes before reads |
| editor-client-7 | low | deploy | confirmed | M | One 1.29 MB eager bundle; 11.6 MB of dead bytes in dist; font warm-up loads unused scripts |
| editor-client-8 | low | perf | plausible | M | Whole undo history structured-cloned to IndexedDB after every edit |
| editor-client-9 | low | perf | plausible | S | Store listener runs root.querySelector('.lane') on every store change |
| editor-client-10 | low | perf | confirmed | S | viewModel builds its own timeline instead of the store's cached one |

## editor-features-a

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| editor-features-a-1 | high | perf | confirmed | S | Transcript panel scans the whole word index once per paragraph per line on every redraw while a cut is shown (70-255 ms per keystroke / edit) |
| editor-features-a-2 | medium | perf | confirmed | S | englishOfSpan / bestEnglishOfCut re-squeeze every paragraph of the clip on every call (5-7 ms per lookup at 600 paragraphs, on the edit frame) |
| editor-features-a-3 | medium | perf | confirmed | M | projectCut costs 25-47 ms per call on the server event loop (quadratic edge search, nothing memoised), one caller re-runs it per request |
| editor-features-a-4 | medium | perf | confirmed | S | The words service folds the clip's whole token stream again for every changed cut (foldShift), synchronously |
| editor-features-a-5 | low | perf | plausible | S | The shelf replaces every staged card's DOM when any one changes |

## editor-features-b

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| editor-features-b-1 | high | perf | confirmed | S | Find (exact words) is quadratic in the episode's transcripts: 0.5-18 s per keystroke, uncancelled, on the shared pinned Python worker |
| editor-features-b-2 | medium | leak | plausible | S | Search worker keeps every episode's word index forever |
| editor-features-b-3 | medium | bug | confirmed | S | aids word-link sidecar is written whole from memory with no merge: the q3-k4 lost-paid-answers bug, unfixed here, and the pipeline writes the same file |
| editor-features-b-5 | medium | concurrency | confirmed | M | One FIFO queue of 4 Claude slots for interactive and background work; a shorten fan-out takes all four |
| editor-features-b-6 | medium | perf | confirmed | S | Shorten's model calls cannot be cancelled: a closed tab keeps opus running for up to 15 minutes per call |
| editor-features-b-4 | low | bug | confirmed | S | Stored alignments and word links from the vault are cached without a stat: new pipeline output is invisible until restart |
| editor-features-b-7 | low | leak | plausible | S | Pinned Python workers keep a per-episode corpus and translation stores with no bound |
| editor-features-b-8 | low | leak | confirmed | S | Shorten's record cache grows per cut list |
| editor-features-b-9 | low | perf | confirmed | S | Every stored alignment re-reads, re-parses and rewrites the whole clip sidecar |

## editor-server

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| editor-server-1 | medium | perf | confirmed | S | Every debounced .cut.md rewrite parses the whole file twice, copies it to .bak and fsyncs four times, all on the one event loop |
| editor-server-2 | medium | concurrency | plausible | M | /cards and /cards/edit both edit the same vault .cut.md files with no shared lock during the beside phase |
| editor-server-3 | low | perf | plausible | S | The projects list walks the vault four folders deep on every request, uncached |
| editor-server-4 | low | disk-growth | confirmed | S | Each cut list keeps up to 100 old log segments, three full snapshots, a .bak and an unpruned quarantine inside the vault |
| editor-server-5 | low | resilience | plausible | S | New log segments and renamed snapshots / head.json are not followed by a directory fsync |

## sorter-py

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| sorter-py-1 | medium | leak | confirmed | S | Every thread that reads the ledger leaks a SQLite connection for the life of the process |
| sorter-py-2 | medium | resilience | confirmed | S | A move run that raises leaves the plan "moving" forever, with no reconcile and no rescan |
| sorter-py-5 | medium | perf | confirmed | S | Thumbnail workers block on the background semaphore while holding a popped job: interactive requests wait behind the backfill |
| sorter-py-7 | medium | idle | plausible | S | Idle cost: the whole Projects tree is re-listed every 60 s, and the leaf refresh does disk I/O under the engine lock every 30 s |
| sorter-py-3 | low | bug | plausible | S | The rescan after a move is silently skipped when a scan is already running |
| sorter-py-4 | low | concurrency | plausible | S | Two concurrent Execute presses on one plan: the loser overwrites the winner's state and starts a scan mid-move |
| sorter-py-6 | low | perf | plausible | S | Backfill ffmpeg runs unthrottled inside the dashboard container (no -threads, no nice), for hours after any STRIP_VERSION bump |
| sorter-py-8 | low | perf | confirmed | S | /api/desttree: the full tree deep-copied under the engine lock and re-sent every 15 s per open tab, no ETag |
| sorter-py-9 | low | perf | confirmed | S | The catalog (25 MB) is rewritten and fsynced at least twice per scan even when nothing changed |
| sorter-py-10 | low | leak | confirmed | S | Move plans accumulate forever, in memory and on disk, and every scan walks all of them |
| sorter-py-11 | low | disk-growth | confirmed | S | The thumbnail and strip cache has no cap and no pruning |
| sorter-py-12 | low | perf | confirmed | S | The scan's content memo is in memory only: every restart (every deploy) re-runs ~2,264 ffprobes and ~7,600 XML/WAV reads |

## sorter-page

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| sorter-page-1 | medium | perf | confirmed | S | Any ledger write makes every open page re-download and re-adopt the whole clip list |
| sorter-page-2 | medium | idle | confirmed | S | Destination tree polled every 15 s, uncompressed and uncached, while the server only re-reads it every 60 s |
| sorter-page-3 | medium | perf | confirmed | S | Every assign/unassign downloads the whole manifest uncompressed and redraws every pane twice |
| sorter-page-4 | low | deploy | confirmed | S | Page assets shipped uncompressed, unversioned, and with the development mock |
| sorter-page-5 | low | idle | confirmed | S | Audio tab poll keeps running in a hidden browser tab and is never cleared |
| sorter-page-6 | low | idle | plausible | M | Session list polled every 5 s although an event stream for it is open |
| sorter-page-7 | low | perf | plausible | S | Hover intent can queue an ffmpeg filmstrip job on the NAS for every card the pointer crosses |
| sorter-page-8 | low | bug | confirmed | S | Em dashes and Node-era instructions in user-visible strings |

## sorter-node

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| sorter-node-1 | medium | deploy | confirmed | S | The docs still install and start the retired tray and Node server beside the companion |
| sorter-node-2 | medium | streamline | confirmed | M | lib/ and server.js cannot retire because they are the parity oracle, and that suite runs in no CI |
| sorter-node-3 | low | bug | confirmed | S | Duplicate decision drift: Node calls equal-size files over 64 MiB identical, Python reads every byte |
| sorter-node-4 | low | bug | confirmed | S | TeraCopy switch drift: Node and the PS1 workers copy new files with /OverwriteDiffSize; the companion uses /SkipAll |
| sorter-node-5 | low | resilience | plausible | S | The October ledger Worker still takes writes after the cut-over to ledger.db |
| sorter-node-6 | low | disk-growth | confirmed | S | 24 MB of machine state tracked in git and pushed to GitHub; 636 MB of dead local state |

## lens-longrun-companion

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| lens-longrun-companion-1 | medium | idle | confirmed | S | One cached 'is Resolve running' probe instead of a tasklist spawn behind nine doors |
| lens-longrun-companion-2 | medium | idle | confirmed | S | On a Mac, both sorter loops spawn diskutil for every mounted volume every 10 seconds |
| lens-longrun-companion-3 | low | leak | plausible | S | The proxy geometry-verdict cache keeps every proxy path it ever saw, with no field eviction |
| lens-longrun-companion-4 | low | idle | confirmed | S | Two upload-queue threads poll every second forever, and the originals inbox lists its folder every 2 s, though all have a wake path |

## lens-longrun-dashboard

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| lens-longrun-dashboard-1 | medium | resilience | confirmed | S | Shutdown is unbounded in front and serial behind, so docker stop SIGKILLs the lifespan - including the Node editor's cut-list flush - whenever a Cards page or agent is connected |
| lens-longrun-dashboard-2 | medium | resilience | plausible | M | Mount-time workers are never stopped, and on an exit-75 restart their ffmpeg/CLI children outlive the process into the next one |
| lens-longrun-dashboard-3 | medium | resilience | plausible | M | No memory limit, and every resident cache lives in the one process the fleet depends on: the OOM victim is the dashboard |
| lens-longrun-dashboard-4 | low | concurrency | confirmed | S | One unpartitioned 40-token threadpool carries both 25 s parked long polls and every sync route, so the standing reservation grows with fleet size |

## lens-sql

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| lens-sql-1 | high | leak | confirmed | S | The sorter ledger opens a new SQLite connection for every short-lived thread and never closes it |
| lens-sql-2 | medium | perf | confirmed | S | Every ledger change makes each open page re-run two whole-table scans of copies (1.0 s + 0.7 s at 2M files); the stats scan has no covering index |
| lens-sql-3 | low | concurrency | confirmed | S | The daily ledger backup holds the writer lock for the whole online backup |

## lens-disk

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| lens-disk-2 | medium | disk-growth | plausible | M | Clips fetched on demand from the b-roll archive and the music library are never evicted from a remote editor's disk |
| lens-disk-1 | medium | disk-growth | confirmed | S | Save-point exports (.drp, tens of MB) of a project nobody edits any more are never swept |
| lens-disk-3 | medium | disk-growth | plausible | S | Every force-kill of the companion leaves two 108 MB PyInstaller extraction folders in %TEMP% |
| lens-disk-4 | medium | disk-growth | plausible | M | The APP dataset's 24 hourly + 30 daily snapshots pin the dashboard DB's rewrite churn and everything deleted from <data>, sized on a 'kilobytes per hour' assumption |
| lens-disk-5 | low | disk-growth | confirmed | S | Footage Sorter keeps a full manifest copy for every day it is used, and its two journals only grow |
| lens-disk-6 | low | disk-growth | plausible | S | The NAS keeps a year of staggered Syncthing versions for every project folder, and nothing measures it |

## lens-dup

| id | severity | category | confidence | effort | title |
|---|---|---|---|---|---|
| lens-dup-1 | medium | streamline | confirmed | M | The old Cards page has no retirement step: ~61,000 lines and a second implementation of every Cards feature stay live after the flip |
| lens-dup-2 | medium | security | confirmed | S | The footage sorter tracks 23.6 MB of manifest backups, move plans and logs, with real interviewee names, on GitHub, against its own .gitignore |
| lens-dup-3 | low | deploy | confirmed | S | The companion build collects all of onnxruntime: 306 .py files (3.87 MB) and 156 submodules of transformers/quantization/tools that the code never imports |
| lens-dup-4 | low | resilience | confirmed | S | ffmpeg_tools twins: the indexer's copy has no timeout on any of its ten ffmpeg/ffprobe calls, and the verbatim-twin helpers are not pinned across the two copies |
| lens-dup-5 | low | bug | confirmed | S | Cards read-only guard is a second hand-kept list beside the route chain and has drifted: /api/fade writes a read-only project |
| lens-dup-6 | low | streamline | confirmed | S | The Cards media-job recipes are pinned against a literal, the shape audit F8 already found fails nothing when the other side moves |
| lens-dup-7 | low | streamline | confirmed | S | Dead dashboard feature and an expired shim: editor_prefs.project_root_override and truenas_client.py |
