# Usability + resilience sweep, 2026-09-03

Fifteen Opus agents, one per subsystem plus an end-to-end journey walker and a
systems-level reader of the ledger, swept the whole tree (about 205k lines of
Python, PowerShell, shell and JS) with a single brief and two lenses: the
USABILITY lens the 2026-08-28 sweep did not have (who touches this surface,
what do they see, quoted, and what should they see) and a RESILIENCE lens
limited to angles that sweep did not find. Every agent read the 08-28 raw
report for its area first, so nothing below re-reports a finding that was
built, and each report carries a one-line "still open from 08-28" ledger.
Every finding cites `file:line` against `097f5a3` (main, 2026-09-03) and was
checked against the source, `KNOWN_BUGS.md` and `docs/`. Nothing in the repo
was changed; this document and the directory below are the only additions.

**The result is 297 ranked findings, 16 of them rated critical.** The fifteen
raw reports, with every finding in full (who, where, what they see today,
proposed copy or control, effort, value, confidence, related ids), are in
`docs/usability-resilience-sweep-2026-09-03/`:

| File | Area | Findings | Critical |
|---|---|---|---|
| `SYS.md` | The whole system: ledger since CR-46 as data, docs vs code, the second customer's first day | 21 | SYS-1, SYS-2 |
| `UX.md` | Four end-to-end journeys across tray, dashboard, SPAs, installer and docs; terminology table | 22 | UX-1 |
| `SYNC.md` | Sync engine: lanes A/B/C, breaker, repath, root guard, drive swap, file moves | 20 | |
| `APP.md` | Companion lifecycle, tray, popups, Settings window, config, upgrade | 20 | APP-1 |
| `RES.md` | DaVinci Resolve: bridge, journal, watcher, fixer, proxies, BPG, Timeline Cards role | 22 | RES-1, RES-2, RES-3 |
| `CMEDIA.md` | Companion media side: 8899 loopback, b-roll ingest, local VLM, music worker, fleet jobs runner | 15 | |
| `CYT.md` | Companion YouTube side: executor, yt-dlp manager, cookies, browser login, import | 18 | |
| `DCORE.md` | Dashboard core: API, schema, report ingest, enforce, auth, provisioning | 16 | DCORE-1 |
| `DUI.md` | Dashboard web UI: every page, chip, button, toast, and the phone view | 20 | DUI-1, DUI-2 |
| `DDIAG.md` | Self-diagnosis (notices, alerts, invariants, protection, recovery) and fleet jobs | 23 | DDIAG-1 |
| `REL.md` | Release channel, signing, feed, dashboard self-update, CLI wizard, ship tooling | 16 | REL-1, REL-2 |
| `OPS.md` | NAS scripts, installers, uninstallers, onboarding wizard, appliance install | 25 | OPS-1 |
| `BROLL.md` | B-roll search UI + API, ingest, client folders, indexer, eval | 28 | BROLL-1 |
| `MUSIC.md` | Music tagger: CLAP search UI + API, ingest, drain, rescore, indexer | 16 | MUSIC-1 |
| `YTWEB.md` | YouTube download service: web UI, API, worker, fleet routes, AI backend | 15 | |

`BRIEF.md` in the same directory is the brief every agent worked from. The
sweep used about 3.4M tokens over roughly 30 minutes of wall clock.

This document is the synthesis: what the sweep says about the product, the
nine shapes the findings fall into, the terminology it proposes, and a ranked,
waved list of what to build first.

## 1. What the sweep says about the product

Every territory agent opened the same way the 08-28 agents did, and then
turned the corner: *the 08-28 waves landed here, the guards are real, and the
person the guard was built for cannot see it.* Five of the fifteen reports
independently coined some version of "the machine knows the answer and never
says it". The 08-28 sweep's diagnosis was that the system never raised an
alarm on its own. This sweep's diagnosis is one step later in the same story:
the system now computes the alarm, and delivers it to a log line, a `title=`
attribute, a Settings window nobody opens, or a sink configured to `none`.

Four facts frame everything below.

**1. The alarm has told nobody anything, ever.** The systems agent re-read the
ledger since the 08-28 sweep as data. The discoverers of every entry since
2026-08-29 are: the owner using the product (12), CI (4, all in CR-94), the
new chaos suites (2), and the self-diagnosis layer built by that sweep (0).
Two independent causes, both cheap: `alerts_sink` defaults to `none` and
nothing anywhere says so (no protection line, no setup task, the weekly report
is deliberately silent in that case: SYS-1, DDIAG-16, DDIAG-17), and the
studio's own dashboard is behind the repo, so the panels are running nowhere
that matters (SYS-7). The two machine discoverers that did find things are the
two the project invested in least (SYS-10).

**2. The 2026-08-27 tray reduction orphaned the product's own directions.**
CR-88 cut the tray to ten items and moved Copy diagnostics, Open log and the
Advanced submenu into a Settings window. About twenty editor-facing sentences
across `tray.py`, `app.py`, `fixer.py`, `identity.py`, `popup.py`,
`loopback_guard.py` and `resolve_bridge.py` still say "Tray -> Copy
diagnostics for your admin" or "tray -> Exit" (UX-1, APP-2, CYT-4, CMEDIA-5,
RES cross-cutting). Every dead end in the product points at a menu that no
longer has the item. Four agents found it independently; it is the single
most-hit dead end and the cheapest fix in the sweep. The same reduction is
why the tray icon stays green and the tooltip says "up to date" while
`sync_guard.blocked` names a reason nothing is syncing (APP-1) and while a
40-clip YouTube download runs (CYT-1): the advisory lines wave 1-4 wrote all
live in that Settings window, one unopened window from invisible.

**3. Six whole subsystems shipped with no user-facing surface.** The shared
LUT library and borrowed folders (SYNC-101), the server-side project rename
(SYNC-102), the proxy ATTACH half of the pipeline (RES-3), the fleet jobs
runner on an editor's machine (CMEDIA-2, "the tray does not render these
yet"), the companion's `youtube_import` report section (parsed by the
dashboard, then dropped: CYT-3), and the Timeline Cards role (RES-6, RES-7)
each fail permanently at DEBUG level with no tray line, no report field and no
chip. Two more have a surface reachable only by accident: the whole music
ingest feature exists only if you drag a file onto the page (MUSIC-3), and
`GET /ytdl/progress`, the entire CR-78 byte/speed/phase mirror, has no
consumer anywhere in the repo (CYT-2).

**4. The second customer is a first-day problem, not a roadmap item.** The
systems agent walked their first day in order (SYS-18): an SMB admin password
because `local` auth is not the default; `DASH_RELEASE_PUBKEYS` by hand or
every publish 503s; no snapshot task (CR-10 has never been applied on either
of the vendor's own NASes); an alert sink of `none`; a dashboard with no
unattended update path that, one version stale, silently freezes every
companion update for the fleet while every surface reports the fleet as
current (SYS-2); and a customer explainer, `HOW_IT_WORKS.md`, that describes a
tray menu no shipped build has (SYS-5). Around that: `drive_swap.py` is
hardcoded to `P:` including an unconditional `net use P: /delete` (SYNC-103),
two sign-in dialogs ask for a "TrueNAS username" (APP-10, SYNC-114), 51
dialog titles hardcode `ccsync-companion` / `CCSYNC.EXE` (UX-4), the ytdl SPA
hardcodes `P:` with Windows backslashes for Mac editors (YTWEB-10), fifteen
dashboard messages answer a non-technical owner with "edit an env var and
redeploy" (DUI-8), and the only install path is a hand-edited compose file
from a doc labelled DRAFT (UX-21).

## 2. The sixteen critical findings

Ranked by the orchestrator across reports. Effort is the agent's estimate.

| # | Id | One line | Effort |
|---|---|---|---|
| 1 | SYS-1 | 42 alert kinds, 10 invariants and a weekly report deliver to nobody by default, and nothing says so | S |
| 2 | BROLL-1 | `publish_db.py --which broll` silently destroys every fleet-ingested clip and the whole `ingest_batches` table; the 10% shrink check passes it | S/M |
| 3 | MUSIC-1 | a failed rescore leaves an uncommitted `DELETE FROM tags; DELETE FROM axes;` on a pooled connection that the next write commits | S |
| 4 | DDIAG-1 | a hanging SMTP server exceeds the 900 s wedged-watchdog threshold and restarts the container, every cycle, for ever | S |
| 5 | DCORE-1 | disabling or deleting an editor does not stop their computer syncing: Syncthing untouched, identity token never expires | M |
| 6 | SYS-2 | a dashboard one version too old swallows every `requires_dashboard` refusal into a log line while the fleet reads as current | S |
| 7 | REL-1 | the soak gate guards three of five "make current" doors; the vendor feed and every Mac build walk past it unattended | M |
| 8 | REL-2 | `[ PUBLISH ]` on the feed runs a 600 s download on the single-worker event loop and freezes the whole dashboard | S |
| 9 | DUI-2 | no `htmx:responseError` handler anywhere, and the only freshness stamp is in a topbar that is never re-rendered | S |
| 10 | DUI-1 | a one-time password and a one-time fleet token are painted into panels a 30 s / 60 s poll erases, with no [ COPY ] | S |
| 11 | APP-1 | the tray icon and tooltip never read `sync_guard.blocked`; green and "up to date" while nothing has synced for days | S |
| 12 | RES-2 | `[ ALWAYS LEAVE THIS FOLDER ALONE ]` destroys the popup and releases the lock while FIX ALL is still copying | S |
| 13 | OPS-1 | a machine whose tree drive could not be mapped exits 0 and the wizard shows the green DONE page | S |
| 14 | RES-1 / SYS-4 | `GOTCHAS.md` section 15 hands every other Resolve client the `is_starting()` guard that CR-68 proved broken; `ready_to_connect` appears nowhere in `docs/` | S |
| 15 | RES-3 | the proxy ATTACH half has zero user-visible surface; `apply_relinks`'s summary is discarded and `_REFUSALS` is a permanent invisible skip list | S/M |
| 16 | UX-1 | about twenty editor-facing sentences point at tray menu items removed on 2026-08-27 | S |

Thirteen of the sixteen are S effort. That is the sweep's second headline:
the critical list is mostly a day of string edits, one `rollback()`, one
`run_in_threadpool`, one `Add-CapabilityMiss` and one time budget.

## 3. The nine shapes

Every finding in the fifteen reports fits one of these. The ids after each are
representative, not exhaustive; the raw reports carry the rest.

**A. Computed, then discarded.** A decision or diagnosis reaches `log.info`
or a return value nobody reads. `reconcile()`'s outcome dict "for the log
line and the tray" is thrown away by the sequencer (SYNC-101); the sentence
naming the broken setting is written into the lane detail and dropped by the
renderer (APP-5); `apply_relinks`'s summary (RES-3); every count the companion
computes about Resolve (RES-5); `js_runtime` measured, shipped in the health
payload, rendered nowhere (YTWEB-3); the degraded-filter note composed and
discarded by `hintFor` (YTWEB-7); `ReportIn.youtube_import` validated and
never read (CYT-3); `install()` and `self_update()` throw away every reason
they failed (CYT-12); `cap_cards_state` stored and rendered nowhere (RES
cross-cutting); `stills.check()`'s "add it by hand" instruction discarded on
every pass (RES-17); the whole-job hand-back reason (CYT-11); the machine's
own "why am I taking no work" (CMEDIA-12). The fix is the same each time:
return it, put it on the report, render it.

**B. The alarm with no listener.** SYS-1 is the root. Beneath it: a mounted
app that fails to mount is a vanished nav link (DDIAG-7, MUSIC-10, BROLL-2);
zero alert kinds for ytdl (YTWEB-2), b-roll (BROLL-2), the loopback
(CMEDIA-3), fleet jobs (DDIAG-2), an upgrade refusal (REL-3), a stalled
rollout (REL-6), a stale yt-dlp (CYT-7); the AI health cache can only go green
(YTWEB-6); a stale-cookies warning can never clear (CYT-5); turning the sink on
never delivers the warnings already open (DDIAG-4); `machine_silent` mails an
ERROR every day for ever for a retired laptop, which is how the owner learns
to ignore it (DDIAG-3); the server's own crash reports have no reader
(DDIAG-10). SYS-17 proposes five invariants that look where the last thirty
ledger entries actually were: written vs deployed vs rendered.

**C. Directions to a place that moved.** The CR-88 string debt (UX-1 and its
four duplicates), the setup wizard sending the owner to the Users page for
packages that moved to Settings on 2026-08-18 (UX-7, REL-10, plus siblings in
`recovery.py` and `setup_engine.py`), `START_HERE.md` describing a role page
renamed on 2026-08-19 (UX-15, OPS-21), both of the dashboard's own deep links
pointing at anchors that do not exist when the browser looks (DUI-7), the
topbar and settings strip as two hand-maintained copies of one list that have
drifted by six entries (UX-8), `HOW_IT_WORKS.md` describing an unshipped menu
(SYS-5), `docs/README.md` missing ten documents (SYS-12), `BACKUP_RESTORE.md`
wrong about a safety mechanism (SYS-9). Nothing tests a string that names a
page; UX proposes one constant for the help route and a scan test.

**D. Long work with no feedback.** The wizard runs a 30-minute child process
and shows nothing (OPS-4, log dies with the window: OPS-5); no htmx control
has loading feedback, including one that blocks for two minutes (DUI-4);
neither long-running Packages button shows anything (REL-12); the recovery
restore blocks the dashboard with no progress (DDIAG-5); the sign-in dialog
freezes 15 s and can show a raw urllib error (APP-11); an hours-long re-encode
is one static line (CYT-16); the indexer prints nothing for six hours
(BROLL-3); the on-demand fetches poll for ever with no elapsed time and no
cancel (MUSIC-11, BROLL-17); "Sync now", the most-clicked menu item,
acknowledges nothing (APP-6).

**E. Destructive and harmless look alike, or destruction has no confirm.**
"copy from ..." wipes a computer's plan on a `change` event with no confirm,
audit row or undo while the tick beside it has all three (DCORE-2); [ NONE ]
does the same (DUI-5); [ DISABLE ], [ REVOKE ] and [ SET ] fire on one click
in the panel where [ DELETE ] asks twice (DUI-18); STOP ALL SYNCING looks
exactly like OPEN LOG (APP-7); [ CLEAR FINISHED STAGING ] looks like its
neighbours (CMEDIA-11); Quit during FIX ALL kills a multi-GB copy silently
(RES-8); FIX ALL states no total size and never checks free space (UX-9); the
package trash is a guard with no UI and the confirm says recovery is
impossible (DUI-9); half the admin surface writes nothing to the fleet audit
(DCORE-7).

**F. Correct in one place, wrong in the three others that render the same
event.** A misplaced drive gets one careful dialog and three lines calling it
"disconnected" (SYNC-105); the stall watchdog writes a good sentence and the
lane line says "Something went wrong" (SYNC-104); the file-move toast says
Resolve was relinked when it was not (SYNC-108); the same idea has four
vocabularies in four toasts (RES cross-cutting); a fact worded two ways on two
pages, one saying "hour(s)" (DDIAG-22); [ UP ], [ UP ON ONE ], [ UPLOAD ONLY ]
and "originals up only" for one mode (UX-17). The terminology table in section
4 is the structural answer.

**G. Reachable only by editing a file or running a script.** The Settings
window can change exactly one setting, `mode`; the other 122 documented keys
are a hand-edited TOML on the editor's machine (SYS-21, SYS-8); the breaker
tells the editor to edit `config.toml` (SYNC-106); the drive reminder cannot
be tuned except in the file (SYNC-117); FIX ALL rehearsal is config-only
(RES-15); the three job knobs have no UI and the docs say they do (UX-11); the
CR-80 cookie recovery is an env var plus a container restart written into an
editor-facing error (YTWEB-4); the ytdl service has no settings page at all
(YTWEB cross-cutting); fifteen dashboard answers are "edit an env var and
redeploy" (DUI-8); RECOVERY prescribes repo scripts the customer does not have
(UX-18); there is no way to restart the companion (APP-13) and no findable way
to uninstall it (OPS-17).

**H. The guard stops at a boundary it did not know about.** DISABLE stops at
the account and never reaches Syncthing (DCORE-1); eviction deletes the
registry row and leaves the plan and the share (DCORE-12); the fleet-membership
gate is inert on the deployment shape it ships on (DCORE-6); the soak gate
guards three of five doors (REL-1); the free-space floor guards one of three
writers to `/data` (REL-7); only the companion has its quarantine flag
stripped, not rclone or Syncthing (OPS-13); the em-dash scan catches the glyph
and not its ASCII stand-in, in 14 places (DUI-14); a tripped breaker and a full
disk deadlock each other (SYNC-111); the download claims a disk lane B already
parked as full (CYT-8); three GPU consumers on one machine and only two
negotiate (CMEDIA-1). SYS-16 names this the repo's most reliable repeat
offender: a fix narrower than the rule it came from.

**I. Data loss and container stability, the short list.** BROLL-1, MUSIC-1,
DDIAG-1, REL-2, DUI-2, DCORE-3 (a session secret that could not be persisted
401s the whole fleet on the next restart), SYNC-103, OPS-12 (a non-absolute
`--remote-root` uploads lane A into the editor's SFTP home), OPS-16
(`config.toml` written non-atomically on macOS), OPS-18 (two wizards at once,
each doing a clean slate), BROLL-15 (two indexers, non-atomic proxy), MUSIC-5
(every fleet-ingested track re-scores the whole library), MUSIC-15 (the search
index rebuilt in RAM in the container with no ceiling), DUI-13 (400 projects
and 40 machines rendered whole every poll), DDIAG-13/14/15, APP-12 (no crash
safety net on macOS and launchd will not restart the companion).

## 4. One vocabulary

The journey agent built the table from cites on every surface. Concepts and
the one word proposed for each; the full table with citations is in `UX.md`.

| Concept | In use today | Proposed |
|---|---|---|
| "this project should sync here" | tick, selection, plan, assignment | **tick** (verb), **sync plan** (the set for one computer); the page becomes `[ SYNC PLANS ]`, `selections` stays in the DB |
| the box on the desk | machine, computer, device, rig, companion | **computer** in all copy; `machine` in code and routes; `device` only for a Syncthing identity |
| sync is not running | paused, halted, stopped, breaker, parked | **paused** = you did it; **stopped by your admin** = fleet halt; **stopped itself** = breaker or disk floor |
| how the computer reaches the footage | wired to the server, physically connected, base, base rig | **wired** / **remote**; "base rig" leaves the UI |
| the three transports | lane A/B/C, upload / proxy download / folder sync | **upload** / **proxy download** / **folder sync**; "lane" never in a visible string |
| upload-only | [ UP ], [ UP ON ONE ], [ UPLOAD ONLY ], "originals up only" | **[ UPLOAD ONLY ]** |
| the home page | [ SYNC STATUS ], "the Fleet page", `CC SYNC: FLEET` | **SYNC STATUS** |
| where the editor gets help | Tray -> Copy diagnostics, Advanced -> ..., "See EDITOR_SETUP step 6" | **Settings > Help > Copy diagnostics**, one constant |

Two structural proposals sit with the table. `UX-3` / `SYS-21`: nothing in
the companion, the dashboard or any SPA links to a single document, so serve
the deployed `HOW_IT_WORKS.md` from the dashboard at `/help` and deep-link its
glossary from the four places the words appear (the sync line, the lane
lines, the fleet chips, the tick modes). `SYS-6` / `DDIAG` cross-cutting: the
Settings strip has grown to twelve flat entries, six of them diagnostic pages
from one sweep that read as five separate products; one `[ HEALTH ]` page
rendering open notices, red/amber alerts, broken invariants and missing
protection lines in one ranked list, as the Settings landing, with the strip
grouped into *Run the fleet* / *Is it healthy* / *When it breaks*.

## 5. What to build, in waves

Ordered so each wave is shippable on its own and the cheapest, highest-value
work is first. Deploy the dashboard before the companions throughout.

**Wave 0: the string day.** No new mechanism. One commit, one scan test per
surface.
- The CR-88 route sweep: UX-1, APP-2, CYT-4, CMEDIA-5, `NO_SCRIPTING_MESSAGE`,
  with the help route as one constant.
- Docs with a safety consequence: `GOTCHAS.md` section 15 (RES-1 / SYS-4),
  `BACKUP_RESTORE.md` (SYS-9), `RESOLVE_EDIT_SAFETY.md` daily cap (RES-21).
- Wrong page, wrong role: UX-7, REL-10, UX-15, OPS-21, DUI-7, UX-8.
- The `P:` and vendor-name residue: SYNC-103's dialog half, SYNC-114, APP-10,
  RES-9, YTWEB-10, UX-4, UX-5, DUI-15.
- Copy that lies or leaks: SYNC-104, SYNC-105, SYNC-108, SYNC-113, SYNC-116,
  UX-6, UX-10, UX-16, UX-17, DUI-14, CYT-13, MUSIC-12, MUSIC-16, OPS-25.
- APP-3 (the newline that silences every macOS safety toast) and APP-4 (the
  250-character Windows truncation) belong here: small, and they gate whether
  anything else in this list is ever seen on a Mac.

**Wave 1: stop the bleeding.** Every item is S or S/M.
- BROLL-1: `publish_db.py --which broll` drains fleet-ingested rows and
  `ingest_batches` first, as the music branch already models.
- MUSIC-1: `rollback()` on the rescore failure path; MUSIC-5 while there.
- DDIAG-1: a per-pass delivery budget under the wedged-watchdog threshold.
- REL-2: `run_in_threadpool` on `partial_admin_feed_publish`, then a sweep of
  `ui.py` for other blocking `async def` routes.
- DUI-2: a global `htmx:responseError` / `sendError` handler and the
  `updated` stamp in a polled fragment. DUI-1: credentials out of polled
  panels, with [ COPY ]. DUI-4: `hx-indicator` everywhere.
- APP-1: `compute_overall_color` and `_tooltip_text` read `sync_guard.blocked`.
- RES-2: disable the popup's buttons during FIX ALL. RES-8: confirm on Quit
  mid-copy. UX-9: total size and free space before FIX ALL.
- OPS-1: `Add-CapabilityMiss` on the `$PIsForeign` refusal. OPS-4/5: stream
  the bootstrap's stdout and write the log to disk. OPS-6: normalise a
  scheme-less URL.
- DCORE-2 and DUI-5: confirm + audit + undo on "copy from" and [ NONE ].
  DUI-18: confirm on DISABLE, REVOKE, SET.
- DCORE-3: refuse to boot on a secret that could not be persisted.
- SYS-2: the `requires_dashboard` refusal becomes a notice, and
  `_check_versions_behind` measures against the feed, not this dashboard.
- SYNC-103: `drive_swap.py` reads `canonical_prefix`.
- CMEDIA-3: loopback health in `GET /status` and in the report.
- CYT-5, YTWEB-6: the two health caches that can only go one way.

**Wave 2: the alarm reaches someone.**
- SYS-1: a ninth protection line and a thirteenth setup task, "who do we tell
  when something breaks"; DDIAG-16 (say the alarm is off), DDIAG-17 (a
  dead-man's heartbeat), DDIAG-4 (deliver what was already open when the
  sink is turned on), DDIAG-3 and DDIAG-9 (staleness cutoffs for retired
  machines, and name [ FORGET ]).
- Registry rows, one small batch: a mount that came up ABSENT or DEGRADED
  (DDIAG-7, MUSIC-10, BROLL-2), the ytdl stack (YTWEB-2, YTWEB-5), the loopback
  (CMEDIA-3), fleet jobs (DDIAG-2, DDIAG-11), upgrade refused / rollout
  stalled / platform channel stale (REL-3, REL-6, REL-13), stale yt-dlp
  (CYT-7).
- SYS-17: invariants 11-15 (fleet current with vendor, dashboard meets
  requirements, mount assets open, cards tree matches source, alerts
  deliverable).
- DDIAG-8: every "what to do" becomes a link. DDIAG-10: a reader for the
  server's own crash reports.
- SYS-18: the first-boot completeness gate (release key, snapshot task, alert
  destination, each skippable with a recorded skip and a red protection line).
- SYS-10: nine more chaos tests, parameterised over the shapes of the last
  thirty ledger entries.

**Wave 3: the machine says what it knows.** The shape-A findings, area by
area. Each is "return it, put it on the report, render it".
- Sync: SYNC-101, SYNC-102 (with a relink and an undo journal for a server
  rename), SYNC-107 (the computer lists its own projects), SYNC-109, SYNC-110,
  SYNC-112 (open `.ccsync-trash`), SYNC-118, SYNC-120.
- Resolve: RES-3, RES-5 (a RESOLVE section in Settings), RES-11, RES-13 (a FIX
  ALL summary with a pointer to undo), RES-16, RES-17, RES-19, RES-22, RES-4,
  RES-6, RES-7, RES-10, RES-14.
- YouTube: CYT-1, CYT-2 (point the existing poll at `/ytdl/progress`), CYT-3,
  CYT-11, CYT-14, CYT-15; YTWEB-1 (count the fleet's queue), YTWEB-3, YTWEB-7,
  YTWEB-8, YTWEB-9, YTWEB-11, YTWEB-13.
- Media: CMEDIA-2 (a JOBS line, history and stop for the editor), CMEDIA-4,
  CMEDIA-7, CMEDIA-10, CMEDIA-12, CMEDIA-13; MUSIC-2, MUSIC-3 ([ ADD MUSIC ]),
  MUSIC-4, MUSIC-7, MUSIC-9, MUSIC-13, MUSIC-14; BROLL-5 (retry a failed
  upload), BROLL-8, BROLL-9, BROLL-10, BROLL-18, BROLL-22, BROLL-23.
- Dashboard: DUI-3 (chips explain themselves on a phone), DUI-6 (the error
  beside the button), DUI-19 ("am I safe to close my laptop"), DUI-20,
  DCORE-8, DCORE-9, DCORE-13, DCORE-14, DCORE-16, REL-11, REL-12, REL-16.
- Companion: APP-5, APP-6, APP-8, APP-9, APP-13 (a Restart item), APP-14,
  APP-16.

**Wave 4: one vocabulary, one help page, one health page.**
- The terminology table (section 4), applied surface by surface with the scan
  tests extended to the retired words.
- UX-3 / SYS-21a: `/help` serving `HOW_IT_WORKS.md`, deep-linked from the four
  places the words appear; UX-22 (the login page explains what this is).
- SYS-6: the `[ HEALTH ]` page and the grouped Settings strip.
- SYS-21b / SYS-8: promote the ten config keys an editor or admin plausibly
  changes into real controls (SYNC-106, SYNC-117, RES-15, UX-11, CMEDIA-9
  among them); APP-17 (sections, not one scroll); DUI-11 (hints on SITE
  SETTINGS); DUI-12 (rename TIMELINE); UX-19 (pause vs local halt).
- CMEDIA-1: the three GPU consumers negotiate through one gate.

**Wave 5: the second customer.**
- Access: DCORE-1 (DISABLE reaches Syncthing and the identity token expires),
  DCORE-4, DCORE-5, DCORE-6, DCORE-12; OPS-2 / UX-14 (an account without a key
  the editor cannot yet have; a key-update control on Users).
- Install and restore: OPS-3 (`DASH_SNAPSHOT_DIR` set by the install and named
  in the runbook), OPS-8 (a backup path for the release key), OPS-9, OPS-10,
  OPS-11, OPS-12, OPS-13, OPS-17, OPS-20, OPS-22, OPS-24; UX-21 (an install
  path that is not a DRAFT doc and a hand-edited compose file).
- Release: REL-1 (the soak gate on all five doors), REL-4, REL-5 (an EULA in
  the image), REL-7, REL-8, REL-9, REL-13, REL-14, REL-15; SYS-7 (the product
  measures its own written-vs-deployed gap); the dashboard's unattended update
  path (SYS cross-cutting).
- Docs hygiene: SYS-5, SYS-12, SYS-13, SYS-14, SYS-19, SYS-20, DUI-8, UX-13,
  UX-18.

## 6. Still open from 2026-08-28

Each raw report ends with a one-line ledger of that sweep's findings for its
area. In summary: SYNC, DCORE, DUI, REL, DDIAG and OPS are mostly built (the
remaining items are named per report); RES has 14 of 18 not built, APP 7 of
15, CMEDIA 12 of the companion-side MEDIA items, and MUSIC/BROLL most of
theirs. Two are worth restating because they recur here as the cause of a new
finding: CR-10's snapshot task has still never been applied to either NAS
(SYS-18, OPS-9), and KNOWN_BUGS item 23, the live proxy-attach proof, is still
unrun and still marked SHIP-BLOCKER (RES-3).

## 7. How to read the raw reports

Each finding carries a lens (usability / resilience / both), who it affects
(editor / admin / owner / developer), the exact `file:line` and screen, the
copy or behaviour as it is today (quoted), the proposed copy or control,
effort, value and confidence, and the related ids. Findings are ranked within
each report. The cross-cutting notes at the end of each report are hand-offs
between agents; most of them became the shape groupings in section 3. When a
fix lands, cite the finding id at the code site, as the 08-21 and 08-28
passes did, so `grep -rn DUI-2` finds what was done about it.
