# Resilience sweep, 2026-08-28

Ten Opus agents, one per subsystem plus a systems-level and a user-error
walkthrough, swept the whole tree (about 169k lines of Python source) with a
single brief: find where a plausible real-world condition leads to silent
failure, wrong state, data loss or a stuck state only a human can clear; find
the user mistakes the system does not cope with; and propose safeguards tied to
a concrete mechanism in this codebase. Every finding cites `file:line` and was
checked against the source, `KNOWN_BUGS.md` and `docs/` so that existing guards
are not re-proposed wholesale. Nothing was changed in the repo.

**The result is 201 ranked findings plus about 20 minor ones.** The ten raw
reports, with every finding in full (scenario, what the code does today,
proposal, effort, severity, confidence, related ledger ids), are in
`docs/resilience-sweep-2026-08-28/`:

| File | Area | Findings |
|---|---|---|
| `SYS.md` | The whole system as a distributed system (ledger read end to end) | 20 |
| `SYNC.md` | Sync engine: lanes A/B/C, breaker, repath, root guard, manifest | 18 |
| `APP.md` | Companion lifecycle, tray, config, upgrade, identity | 15 |
| `RES.md` | DaVinci Resolve integration: bridge, journal, fixer, proxies, BPG | 18 |
| `DASH.md` | Dashboard core: ingest, enforce, inventory, auth, schema | 18 |
| `REL.md` | Release channel, upgrade, signing, dashboard self-update | 16 |
| `OPS.md` | NAS scripts, installers, onboarding wizard | 17 |
| `YT.md` | YouTube download stack, AI providers, CLI wizard | 24 (+7) |
| `MEDIA.md` | B-roll and music: ingest, share links, indexers, sidecars | 32 (+5) |
| `UX.md` | User error end to end, plus 10 confirmation dialogs with copy | 23 (+10) |

`BRIEF.md` in the same directory is the brief every agent worked from.

Line numbers were taken against `c245f50` (main, 2026-08-28 morning). A
concurrent session was editing `app.py`, `tray.py`, `settings_window.py`,
`shutdown_guard.py` and `config.py` for CR-92 while the sweep ran, so
references into those five files may be a few lines off.

This document is the synthesis: what the sweep says about the system as a
whole, the fourteen themes the findings fall into, and a ranked, waved list of
what to build first.

## 1. What the sweep says about the system

Every agent, independently, opened with a version of the same sentence: *this
is the most defensively written area of the repo*. The lane B breaker, the
fleet halt, `.ccsync-trash`, `root_guard`, `shutdown_guard`,
`script_server.ready_to_connect`, the signed upgrade channel, the Resolve undo
journal, `CollectorWatchdog`, the ingest checkpoints, the O_EXCL copy
reservations and the atomic latch files are all real, tested, and carry the
incident that produced them. The guards are not the problem.

Four things are.

**1. The system never raises an alarm on its own.** The systems agent read all
4,821 lines of `KNOWN_BUGS.md` as data: about 40 % of entries were found by the
owner noticing something, about 58 % by a periodic hand audit, about 2 % by a
test, and **0 % by the system telling anyone**. The dashboard, whose stated job
is to tell everyone whether their footage is syncing, has never once been the
discoverer of an outage, and in SYNC-17, CR-27a, CR-86, CR-90 and CR-91 it was
showing green or lying at the time. There is no outbound notification of any
kind (no email, no webhook), every alarm is pull-only, and detection latency is
"until the owner next looks".

**2. "Green while dead" is one failure class with a dozen faces.** A lane in
`syncing` with no bytes moving for hours (CR-91), a sequencer thread that died
with no handler and left the reporter cheerfully sending its frozen state
(SYS-2), a Syncthing folder parked for missing ignores while lane C reports
idle (SYNC-5), an express lane wedged for the life of the process (SYNC-13), a
manifest walk blocked in the kernel so presence data is days old (SYNC-9), a
wedged Resolve call nobody surfaces (RES-3), an upload thread that died with
`_active` set (MEDIA-28), a yt-dlp at 100 % CPU that the health endpoint calls
alive (YT-4). None of these states carries a progress token or a "state since"
stamp, so the dashboard cannot tell a slow machine from a dead one. One
contract closes all of them (Theme A below).

**3. The guard exists, but only in one of the N places it belongs.** Almost
every finding is a pattern this repo already built correctly somewhere else:
`CollectorWatchdog` on the dashboard but nothing supervising the companion's
sequencer; free-space floors in proxy generation and both ingest sidecars but
none in any of the three lanes that move footage; `folder_tuning_drift`
repairing one kind of fact and nothing re-verifying any other; the enforce
cycle's blast-radius brake but no brake on `deactivate_missing_projects` one
function up; the CR-90 NFC normaliser at the dashboard's two write chokepoints
but not in the breaker's relocation probe, the file-move exclusion or the music
ingest path; `file_moves`' acknowledgement contract but five other command
channels with five other rules; `hx-confirm` consequence copy on user deletes
but nothing on the fleet halt, the feed policy, or the role switch that stops a
machine syncing for good. The work is mostly *applying an existing pattern to
the second and third place*, not invention.

**4. The system is good at surviving a fault and bad at saying it survived
one.** The companion is excellent at catching exceptions, falling back to
cached state, and carrying on. Then it says nothing: a revoked token gives one
WARNING and DEBUG forever with three green lanes (APP-1); crash reports are
written to a directory nothing reads (APP-6); a report section the companion
has computed for weeks is dropped by an undeclared pydantic field for the
*third* time (SYS-3); sixteen `log.error` diagnoses in the collector reach only
the container log (UX-10); a refused enforce cycle is recorded as a successful
poll (DASH-14); a failed snapshot is a stderr line in a 500-line deploy log
(OPS-9).

## 2. The fourteen themes

Each theme names the findings it groups, across agents, and the single
mechanism that closes most of them. Ids refer to the raw reports.

### A. A liveness contract: nothing is green without evidence of progress

*SYS-1, SYS-2, SYS-17, SYNC-1, SYNC-5, SYNC-9, SYNC-13, RES-3, YT-4, MEDIA-28,
UX-2(b), DASH-16.*

Every non-terminal state in the system (a lane pass, proxy generation, an
ingest batch, a ytdl job, a Resolve bridge call, a collector kind) gains two
fields: a monotonic **progress token** (bytes + files + current item, which
the lane already tallies in `RcloneRunTally`) and **`state_since`**. The
dashboard's `health.lane_chip_status` turns a state RED with the sentence
"syncing, no progress for 47 min" when the token has not moved past
`max(3 x project_rotation_seconds, 30 min)`. Bytes, not wall clock, so a slow
40 GB upload is not mistaken for a hang. **The detector belongs on the
server**: the thread that would run a companion-side watchdog is exactly the
one the fault wedges. Companion side, the complementary half is a hard ceiling
on `proc.wait()` in `_run_popen` (today unbounded; `--max-duration` is SOFT and
does not bound a local read blocked in the kernel), a bounded `thread.join()`
in `_run_lanes_a_and_b`, and a zero-bytes-moved kill using the `--stats`
records `_handle_stderr_line` already parses.

`editor_status` also needs a report-freshness rule independent of `behind`: a
machine that was caught up when it went silent is never "behind", so the dot
the owner scans stays GREEN for a machine that has been dark for a week.

### B. Supervise every thread, bound every child

*SYS-2, SYNC-2, SYNC-12, SYNC-18, APP-7, APP-15, MEDIA-2, MEDIA-9, MEDIA-28,
YT-4, YT-18, OPS-3, OPS-17.*

`sequencer._run` has no try/except around its loop body and nothing restarts
it; the dashboard solved exactly this with `CollectorWatchdog` and the pattern
should be mirrored (`LaneWatchdog` in `app.py`, restarts recorded in a state
file and reported, so a machine that needs restarting three times an hour is
visible rather than merely self-healing). The root guard's own `isdir` blocks
on the wedged mount it exists to detect; `probe_watch_root` (out-of-process,
5 s cap) already exists and is used in one place. `_run_lsf` and
`_run_capture` use `subprocess.run(timeout=)`, which on Windows can block
forever in `communicate()` after the kill; `_end_probe` documents the trap and
the fix. The b-roll ingest's `stop()` promises to kill the ffmpeg child but
`self._child` is assigned `None` at construction and nowhere else, so cancel is
inert for up to fifteen minutes and ffmpeg outlives the tray. An orphaned
llama-server keeps 4-12 GB of VRAM after a hard kill and the next start
launches a second one. Two `subprocess.run` calls in the ytdl downloader have
no `timeout=` at all.

### C. Make silence impossible: every computed diagnosis reaches a person

*SYS-3, SYS-8, SYS-16, SYNC-8, SYNC-15, APP-1, APP-6, APP-8, APP-9, APP-12,
DASH-3, DASH-14, UX-4, UX-10, RES-3, RES-12, REL-11, OPS-9, MEDIA-6, YT-23.*

Three mechanisms:

1. **Widen the wire contract and pin it.** `ReportIn` gets
   `extra='allow'` and logs once a day any top-level key it does not read;
   a cross-component test asserts every key `_build_payload` can emit is
   declared. Then land, in one schema change, the fields four agents asked
   for independently: `disk`, `crashes`, `resolve_health` (out-of-tree,
   bad-prefix, missing counts), `sync_guard.blocked` (one derived reason),
   `syncthing_supervisor` (sent today, dropped today), `upgrade`
   (attempts, last error), `paused`, `clock_skew_seconds`, `manifest_age`,
   `ignored_clips`, `stray_projects`.
2. **A `notices` table on the dashboard** that `collector`/`provision`
   write instead of `log.error` alone, rendered as PROBLEMS THE SERVER FOUND
   on the home page. Sixteen already-written diagnoses (a stray marker
   hiding three projects, two Syncthing folders over one path, a refused
   enforce cycle) currently reach nobody.
3. **Outbound notification**: a weekly fleet health report and four
   immediate alerts (breaker trip, machine silent past 24 h, collector
   watchdog restart, disk below floor) through a pluggable sink (SMTP from a
   site setting, or a tailnet webhook). The ledger shows every long outage
   was found by the owner happening to look.

Plus: a machine with no verified identity should report *that* (an
unauthenticated presence beacon carrying machine id, version and reason) rather
than vanish from the grid indistinguishably from "switched off".

### D. Disk space is invisible to everything that moves footage

*SYS-5, SYNC-7, SYNC-16, UX-1, UX-14, UX-17, RES-7, RES-8, DASH-7, DASH-15,
REL-5, OPS-2, OPS-11, YT-5, YT-18, MEDIA-3, MEDIA-32.*

No lane, the fixer, the file-move path, the report payload, the tick endpoint,
the installer's root validator, the dashboard's own `/data`, the NAS pool, or
the package/backup stores measure free space; the ingest paths and proxy
generator do. Consequences today: one `[ ALL ]` click fills a laptop; lane B
thrashes ENOSPC per file while the 50 GB `.ccsync-trash` cannot prune because
prune only runs at the tail of a *successful* pass; FIX ALL copies until the
system drive is at zero; a full `/data` takes `dashboard.db` down with green
health; 24 hourly + 30 daily ZFS snapshots pin every deleted block of a
multi-TB media tree for a month with nothing watching `usedbysnapshots`; b-roll
ingest staging is never deleted although the plan promises 7-day retention, so
the feature fills its own disk and blames the editor. One `shutil.disk_usage`
per heavy tick, in the report, rendered as a chip, used as the first branch of
the "why" tree; lane B parks in `paused` (never `error`) under a floor exactly
like the breaker; `api_tick` returns a warning with the sizes; `check_health`
gains a capacity check; publish paths refuse under 2x payload.

### E. Nobody measures the clock

*SYS-4, APP-13, DASH-17.*

A slow clock makes lane B's `--min-age` exclude every NAS file (rclone exits 0,
zero transferred, green): the editor downloads nothing, indefinitely, with no
error. A fast clock invalidates pre-CR-86 identity tokens and tells the editor
their sign-in expired. `db.prune()` and `evict_extra_machines` are the only two
retention predicates that trust the client's `reported_at`; every neighbour
uses `received_at`. The server's `received_at` is already in every report
reply and the companion discards it. Three lines to compare, store
`skew_seconds`, warn past 60 s, chip the grid; two predicates to switch.

### F. The release pipeline has no canary, no rollback signal, no recall, and no ordering enforcement

*SYS-6, SYS-13, REL-1, REL-2, REL-3, REL-4, REL-6, REL-7, REL-8, REL-12,
REL-13, REL-14, REL-15, REL-16, APP-5, OPS-1, OPS-12.*

`-MakeCurrent` hands a build to every machine within one report interval. A
companion that starts and dies at minute five has no way back: the takeover
grace is 2 s and `.old` is deleted 60 s in, nothing restarts the tray before
the next logon, and crashes never leave the machine, so there is no fleet-wide
signal that would justify the rollback the channel already supports. A
retracted build is never withdrawn under the default `manual` policy. "Deploy
the dashboard before the companions" is written in four places and enforced
nowhere; it has been violated enough times to be its own ledger class. A
bind-mode deploy restarts the container and returns 0 without probing
`/api/v1/health` (the probe exists; its result is discarded), so `ship.cmd`
carries on to publish companions against a dead dashboard. The dashboard's own
crash-loop watchdog clears `boot_attempts` after a 45 s sleep without asking
whether the app can serve. A key rotation without `--add` strands the whole
fleet with no over-the-air recovery, and the parity check compares the signing
key against the artefact it just built, the one place they can never disagree.

Proposals, all built from parts that exist: publish staged by default, soak on
one machine via the existing per-machine `commands.upgrade`, then MAKE CURRENT
gated on "N minutes reporting, 0 crashes"; keep `.old` until the first accepted
report and auto-restore it on three starts in ten minutes; a signed
`retracted` block honoured under every policy plus one ROLL THE FLEET BACK
button; `requires_dashboard` on companion records via `KIND_EXTRA_FIELDS`,
refused at MakeCurrent when above the running dashboard; the loopback health
probe in the watchdog and in the deploy, with a non-zero exit that stops the
ship; a ship journal with `-Resume`; `arch` in the record so an Intel Mac is
offered nothing rather than an arm64 binary.

### G. Safety latches that are not durable, or live where support is told to delete

*APP-3, APP-4, APP-8, APP-11, RES-2, RES-13, YT-12, YT-15, MEDIA-10, MEDIA-30,
SYS-20, OPS-13.*

CLAUDE.md's own rule is "never make a safety latch in-memory-only". The
breaker and halt files are durable, and they live in `~/.ccsync/state/`, the
one directory `machine.py`'s docstring says support sessions are told to
delete; the upgrade floor was moved out for exactly this reason. The tray's
Pause is in-memory and forgotten on restart, invisible to the grid. The
15-minute bar on unprompted Resolve project rewrites is module globals, re-armed
by every OTA. The ytdl identical-failure breaker is a `DownloadJob` attribute
that dies with the job. `config.set_value` rewrites `config.toml` with
`write_text` (every neighbour uses tmp + replace): a bad moment there takes the
machine to ALL DEFAULTS, blank `dashboard_url`, no reporting, reinstall the
only cure; it can also append `mode =` inside a hand-added TOML table so the
role button silently does nothing forever. `secrets_boot.write_secret_file`
truncates then writes, so an ENOSPC leaves a truncated API key that
`key_present` still calls present. The project marker is written with
`printf > file`, and a truncated marker puts `setup_tree` into a permanent
"different identity, not overwriting" refusal.

### H. Write orders that are not journalled, and moves that undo themselves

*DASH-1, DASH-4, DASH-5, DASH-9, DASH-13, RES-1, RES-10, UX-5, MEDIA-4,
MEDIA-15, MEDIA-5, REL-10, YT-3, YT-6, YT-7, YT-8, YT-20, SYNC-4, SYNC-10,
SYNC-17.*

The server-side file move renames on the NAS *before* recording it, and a
failure in the proxy-sibling loop 503s with "the file stayed where it was",
which is untrue: half-moved, no row, no machine told. On the companion, a move
Resolve blocked (file open, `PermissionError`) is ledgered as a permanent
refusal, never retried, and 24 h later the lane A exclusion expires and the
machine re-uploads the file to the old path, undoing the admin's move. An
undelivered move expires after 7 days, so a laptop away on a shoot resurrects
the file. `_relink_moved` only fixes the project that happens to be open. One
Syncthing config answering 200 with zero folders deactivates every project and
the hourly prune then wipes the whole NAS inventory (the enforce cycle has a
brake; this path does not). An unmounted project dataset reads as an empty
directory and `replace_nas_media` deletes that project's inventory, after
which the page tells the owner his footage is not on the server. The ytdl
pre-conversion VP9 original is uploaded under the clip's final name (neither
executor passes `--no-mtime`, so `--min-age` is satisfied on arrival) and
lane A's `copy --ignore-existing` makes it the fleet's permanent copy. An
upload-only project can never be repathed because the repather's only record
is the Syncthing folder it deliberately does not have. `publish_db --which
music` still clobbers the live ingest queue the drain rule exists to protect.

Two-phase intent rows (`pending` before the rename, reconciled on boot),
retryable failures with attempt counts, refusing an inventory walk that takes
a project from N to 0, and staging downloads outside the tree close these.

### I. The human-facing layer: confirmations, undo, audit, and "explain why"

*SYS-7, SYS-10, SYS-11, SYS-12, UX-2, UX-3, UX-6, UX-8, UX-9, UX-11, UX-12,
UX-13, UX-19, UX-20, UX-21, UX-22, DASH-6, DASH-8, APP-2, APP-9, RES-12,
RES-17, OPS-4, OPS-6, OPS-7, MEDIA-6, UX-18, YT-13, YT-14.*

The tray is the best-guarded surface (the worst action is behind a typed
word); the dashboard has eight confirmation dialogs in the whole application,
and the controls that stop the fleet, arm unattended upgrades, delete rollback
material, import a whole `site.toml`, revoke a token that cannot be re-shown,
or untick a whole column fire on one click with no history and no undo. Three
one-click actions an editor takes for innocent reasons (Settings -> WIRED TO
THE SERVER, SIGN OUT, Quit) stop that machine syncing indefinitely with no
confirmation. Renaming a project folder in Explorer reports as benign
"project dir not yet local". IGNORE ALL hides clips for the session with no
count, no log summary, and even Scan whole project honours it. `UX.md` §"Top
10" has the exact copy for the ten confirmations that matter most.

Structural pieces: an append-only `fleet_audit` table written from the dozen
state-changing routes (tick/untick, halt, resume, deletes, publish, push,
move, settings, approval), so "who unticked this on Tuesday" becomes a lookup;
a 60 s UNDO window on unticks (the enforce cycle runs on a timer anyway; skip
selections younger than that); a halt with an expiry and a standing banner;
one command envelope `{id, kind, payload, delivery}` with
`commands_applied` acks instead of six channels with six rules; and a
server-side **decision tree** that renders one sentence per machine, ordered
by what actually goes wrong here (not signed in -> clock -> drive absent ->
disk full -> halt -> breaker -> Syncthing down -> no plan -> no share ->
upload-only so B is meant to be idle -> stalled -> offline). Every one of
those states is computed somewhere today; none is composed into a sentence.
Diagnostics should upload on the report channel (on the button, on any lane
entering `error`, and on an admin's ASK THIS MACHINE WHY), not go to the
clipboard of a broken machine.

### J. Identity and duplication

*APP-10, DASH-11, SYNC-14, DASH-2, SYS-16, APP-12, YT-11.*

A cloned disk gives two computers one `machine_id`, one identity token and one
Syncthing device id; the registry ping-pongs the device between them every
report and the enforce cycle restarts the affected folders every 60 s. A
renamed computer asks for a plan by hostname (the selection fetch does not send
`machine_id`, which exists precisely so a rename does not lose identity) and
parks in "no selection". Rotating or losing `DASH_SESSION_SECRET` 401s every
companion's never-expiring identity token, fleet-wide, until each editor signs
in at their own tray, with no message anywhere. Record `minted_on` in
`machine.json`, resolve plans by id first, accept a previous session secret,
and flag "two computers claim to be the same machine".

### K. CR-90's lesson reached the dashboard and stopped

*SYNC-3, SYNC-11, MEDIA-21.*

The breaker's relocation probe compares macOS-NFD trashed paths against NFC
NAS paths, so on a Mac a benign reorganisation trips the breaker and CR-44's
promise is false there. The file-move exclusion is handed to rclone as a
literal NFC glob against NFD bytes on disk, so the moved file re-uploads. The
music ingest path has no `unicodedata.normalize` anywhere. Three small,
comparison-only fixes; and a repo-wide grep for `rel in` / `== rel_path`
comparisons that cross the Mac/NAS boundary.

### L. Exposure the sweep found on the way

*YT-9, MEDIA-1, MEDIA-8, MEDIA-14, MEDIA-22, MEDIA-31c, YT-24, UX-6, OPS-8,
UX-23.*

The AI CLI is handed the dashboard's entire environment minus four names, so
it receives `DASH_SESSION_SECRET`, `DASH_REPORT_TOKEN`, `SYNCTHING_API_KEY`,
`TRUENAS_API_KEY` and `BROLL_INGEST_TOKEN` while processing untrusted YouTube
text; `cli_env` should be an allow-list. `client_folders.resolve_items` keeps a
by-id row when the identity check fails, so an index rebuild that reuses ids
can serve a client a clip nobody curated (the fourth site of CR-63). Every live
share token is written to the uvicorn access log. Share media routes are sync
`def`s streaming from the single-worker process that serves fleet reports,
reachable from the open internet by one forwarded link. Revoked share media
keeps playing for an hour of `max-age`. The grade swap deletes a foreign `P:`
mapping without the ownership check the installer makes; the uninstaller
inverts the "can't tell = foreign" rule the bootstrap was fixed to obey.

### M. Recovery for a non-technical owner

*SYS-14, SYS-15, SYS-19, OPS-4, OPS-9, OPS-14, DASH-13, REL-10.*

Every one of the five documented restore paths is a root SSH session
requiring judgement the owner cannot supply (dataset or directory? which
snapshot? `chown` deletes the share ACL on DSM). The live TrueNAS's `apps`
path is a plain directory with no snapshot task at all (CR-10, open), every
page renders green, and `SYNC_SAFETY.md` says in prose that there is no banner
for "this NAS has no snapshot schedule". No server script prints which NAS it
is about to `chown -R`. Proposals: a **protection panel** where a safety
mechanism the dashboard cannot positively verify renders as MISSING, never as
silence (snapshot task exists, last snapshot younger than 25 h, release key
backed up, restore drill run this year); snapshot browse-and-restore into
`<project>/.restored-<ts>/` rather than over the live path; an admin-side
Resolve undo on the command channel; a guided disaster runbook page that
substitutes the customer's real pool name and platform into the commands it
prints; a durable snapshot log every script reports in its final summary; a
NAS host banner and a typed confirmation on the recursive scripts.

### N. Fault injection

*SYS-18.*

Thirteen suites, strong on logic and near-silent on conditions; 2 % of ledger
entries were found by a test. The seams are already injectable
(`popen_factory`, the reporter's `_http_post`, the selection opener,
`subprocess.run`). Nine chaos tests, each closing a class rather than a bug: a
child that never exits; a clock 20 min slow; `disk_usage` at 1 GB; a report
POST that 401s then recovers; `_run` raising on the third pass; a kill between
an atomic latch's tmp-write and replace; a report carrying an undeclared
section; a second hostname reporting an existing `machine_id`; a Syncthing
that 200s with an empty folder list.

## 3. Do these first

Ranked by severity x breadth x cheapness. Effort S is hours, M is a day or
two, L is a work package.

| # | Ids | What | Effort | Sev |
|---|---|---|---|---|
| 1 | SYS-2 | try/except around `sequencer._run`, `LaneWatchdog` mirroring `CollectorWatchdog`, restarts reported | M | critical |
| 2 | SYNC-1 / SYS-17 | hard ceiling on `proc.wait()`, bounded lane B join, zero-bytes-moved kill; `project_rotation_seconds <= 0` refused (CR-91's mechanism) | M | critical |
| 3 | SYS-1 | progress token + `state_since` on every lane report; server-side stall detector turns the chip RED | M | critical |
| 4 | UX-2 | confirm on WIRED TO THE SERVER; report-freshness rule in `editor_status` | S | critical |
| 5 | MEDIA-1 | drop the by-id row when identity disagrees in `client_folders.resolve_items` | S | critical |
| 6 | YT-1 | yt-dlp max-age self-update rule (kills the CR-80/83 class) | S | critical |
| 7 | OPS-1 / REL-6 | deploy probes `/api/v1/health` and exits non-zero; dashboard watchdog clears `boot_attempts` only after a served 200 | S+M | critical |
| 8 | SYS-3 / SYNC-8 | `ReportIn` `extra='allow'` + unread-key warning + parity test; declare `syncthing_supervisor` | S | high |
| 9 | SYS-4 / APP-13 | clock skew from the reply's `received_at`; `prune`/`evict` on `received_at` | S | high |
| 10 | DASH-4 / DASH-5 | brake on `deactivate_missing_projects`; refuse an inventory walk from N to 0 | S | high |
| 11 | DASH-3 / DASH-14 | persist and banner the enforce refusal; `_timed` notes for "did nothing" | S | high |
| 12 | APP-3 | move `lane_b_breaker.json` / `sync_halt.json` out of `state/` | S | high |
| 13 | APP-4 / APP-11 | atomic `config.toml` write + `.bak`; `set_value` inserts before the first table and reads back | S | high |
| 14 | APP-5 / REL-2 | keep `.old` until the first accepted report; auto-restore on 3 starts in 10 min | M | high |
| 15 | DASH-1 / RES-1 / UX-5 | two-phase file move; retryable failures on the companion; never expire an undelivered move | M | high |
| 16 | SYS-5 / SYNC-7 / UX-1 | `disk` in the report, `[ DISK 4% ]` chip, lane B parks under a floor, tick warns with sizes | M | high |
| 17 | SYNC-2 | `ROOT_NOT_ANSWERING` via `probe_watch_root` | M | high |
| 18 | SYNC-3 / SYNC-11 / MEDIA-21 | NFC at the three remaining comparison sites | S | high |
| 19 | SYNC-5 / SYNC-6 | latched-paused folders reported; shared/borrowed reconcile checks the root first | S | high |
| 20 | YT-9 | `cli_env` allow-list, pinned by a test | S | high |
| 21 | YT-3 / YT-6 | `--no-mtime` + five exclude lines; `.editready`/`.original` out of the importer | S | high |
| 22 | RES-2 | persist the unprompted-rewrite limiter, add a per-day cap | S | high |
| 23 | RES-4 / RES-5 | BPG launch consults `script_server.state()`; a `-pg` sighting is not "Resolve running" | S+M | high |
| 24 | MEDIA-2 / MEDIA-3 | real `_kill_child`; staging retention as documented | M | high |
| 25 | UX-10 | `notices` table + PROBLEMS THE SERVER FOUND panel | M | high |
| 26 | APP-1 / APP-6 | reporter health (`last_success_at`, status, streak) in tray, diagnostics and `sync_guard`; crash counter reported | S | high |
| 27 | UX-8 / UX-9 | halt expiry + banner + confirm; refuse MAKE CURRENT on unsigned; package delete to `.trash` | M | high |
| 28 | SYS-7 | one-sentence "why" per machine; diagnostics uploaded on the report channel; ASK THIS MACHINE WHY | M | high |
| 29 | SYS-13 / REL-4 | `requires_dashboard` in the signed record, refused at MakeCurrent | M | high |
| 30 | REL-1 / SYS-6 | staged-by-default publish + soak gate + crash counter | M | high |
| 31 | REL-3 | retraction honoured under every policy + ROLL THE FLEET BACK | M | high |
| 32 | DASH-2 | `DASH_SESSION_SECRET_PREVIOUS`; refused reports still stamp `last_seen` with a reason | M | high |
| 33 | OPS-4 / OPS-9 | NAS host banner + typed confirmation; durable snapshot log in every final summary | S+M | high |
| 34 | SYS-14 | protection panel: unverifiable safety renders MISSING | M | high |
| 35 | UX-3 / SYNC-10 | "was here last pass, now gone" is an error, not idle; stray-project scan | M | high |
| 36 | UX-6 / OPS-8 / UX-23 | `classify_p_target` before the grade swap unmap; shared `Get-DriveMapping` in the uninstaller | S | high |
| 37 | UX-7 | detect and list `*.sync-conflict-*` | S | high |
| 38 | APP-2 / RES-12 / UX-4 | Scan whole project clears the ignore tracker; counts reported; persisted "leave this folder alone" | M | high |
| 39 | SYS-11 / DASH-8 | `fleet_audit` table + recent plan changes with UNDO | S | med |
| 40 | SYS-9 | continuous invariant checker (start with invariants 1, 3, 5, 9) | L | high |
| 41 | SYS-8 | weekly fleet report + four alerts through a pluggable sink | M | high |
| 42 | SYS-15 | snapshot browse-and-restore into a quarantine path; guided runbook page | L | high |
| 43 | SYS-18 | nine chaos tests | M | med |

## 4. Suggested waves

**Wave 1, the cheap day (all S):** 4, 5, 6, 8, 9, 10, 11, 12, 13, 18, 19, 20,
21, 22, 26, 33(a), 36, 37, 39. **BUILT 2026-08-28** by nine builder agents
(plus DASH-16, MEDIA-23, MEDIA-22 and DASH-14, which fell out of the same
edits); ledger section "Resilience sweep, wave 1" in `KNOWN_BUGS.md`. Ships
as companion 0.9.55, dashboard schema v30+v31, and a rebuilt installer
package (OPS-8 adds `installer/drive_mapping.ps1`). Nineteen small diffs, each closing a class the
ledger has already paid for at least once. Most are companion-side and ship in
one build; the dashboard half (8, 9, 10, 11, 39) is one OTA.

**Wave 2, liveness and the wire contract:** 1, 2, 3, 16, 17, 28. This is the
"green while dead" fix. **BUILT 2026-08-28** by five builder agents (plus
SYNC-12, SYNC-13, SYNC-15, SYNC-16 from the same files); ledger section
"Resilience sweep, wave 2" in `KNOWN_BUGS.md`; dashboard schema v32 + v33. Land the report schema widening once (Theme C) so the
disk, crash, resolve-health, blocked-reason and upgrade fields ride the same
change. Deploy the dashboard before the companions, as always.

**Wave 3, the release pipeline:** 7, 14, 29, 30, 31, 32. After this a bad
build reaches one machine first, a crash-looping companion puts itself back,
a dashboard that cannot serve is not called healthy, and the deploy ordering
is a refusal rather than a memory.

**Wave 4, the human layer:** 15, 24, 25, 27, 35, 38, 41, plus the ten
confirmation dialogs in `UX.md`. Notices, audit, halt expiry, the "why"
sentence, the weekly report.

**Wave 5, recovery and invariants:** 34, 40, 42, 43. The protection panel and
invariant checker are what make the system tell the owner what it is *not*
protected against; the chaos tests are what stop the classes above from
coming back.

## 5. Ledger notes from the sweep

- `CR-91` is used for two entries: "approving a computer mints a phantom
  editor" (fixed, dashboard 0.7.16) and "lane A stuck in `syncing`" (open).
  The raw reports write them as CR-91a / CR-91b. CR-70 and CR-71 sit out of
  order after CR-69. A concurrent session added CR-92 (drive reminder) while
  the sweep ran.
- `SYNC_SAFETY.md` §2 now bounds `.ccsync-trash` at 14 d / 50 GB while
  `BACKUP_RESTORE.md` still calls it never-pruned; `.stversions` `maxAge` is
  365 d NAS-side and 30 d editor-side (R5), unreconciled in code and prose.
- `dashboard/static/dashboard_update.js` hard-codes `restore_db: ""`, so the
  rollback path that restores databases has no button.
- `KNOWN_BUGS CR-68` records the base rig's Resolve MCP guard as uncommitted;
  the `davinci-resolve` MCP server's tools "automatically launch Resolve if
  it is not running", which is the CR-68 trigger by design.
- Guards each agent verified sound and asked nobody to re-check are listed at
  the end of `YT.md` and `MEDIA.md`.
