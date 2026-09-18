## CR-285 - the ninth hunt's dashboard mediums and lows: an episode nobody could reopen, a card that blamed an innocent pass, and a publish that swapped the bytes first - FIXED in repo 2026-09-18 (dashboard 0.7.50), unshipped

The `dashboard` group of `docs/bug-hunt-2026-09-18/ASSIGNMENTS.md`: 47 hunt
findings plus the four the live dashboard showed on the morning of the pass,
fixed against `214869b` plus the uncommitted CR-282 wave, by one builder
(CR-285A..AK) and then a second (CR-285AL..AW: the mediums the first left,
the lows it could not reach, and the alert half of live-1).
Mediums first, in the order the assignment lists them, then the lows it could
reach. Five findings are in code the whole fleet took on 2026-09-17 (dashboard
0.7.49), five are in the Timeline Cards engine pool that went live 2026-09-14,
and four are things the live dashboard was doing while the hunt was being read.

Three OWED items routed here by other builders are folded in as lettered
sections of their own (comp-app-3, comp-resolve-5, comp-broll-tiers-5,
proxy-tiers-3's dashboard half, server-tools-1's CI step and regression-6's
neutered assertion), because they are changes to files in this group.

### CR-285A (dash-cards-2) - an episode that failed to build could never be opened again - FIXED (cards_pool.py, templates/cards_landing.html)

`EnginePool.open` was idempotent on the SLUG, not on the STATE: an entry the
builder thread left in `FAILED` came back as-is with an empty refusal, so
`_run_build` was never re-entered. The landing page drew `[ FAILED ]` and, in
the final `{% else %}` branch of the action cell, offered `[ OPEN ]` - which
posted, got the same failed entry back, and redirected to `?want=<slug>` with
nothing changed. `[ CLOSE ]` was inside `{% if ep.state == 'ready' %}`, so not
even an admin had a door. One transient cause - the vault share not up yet,
Postgres refusing at the moment somebody clicked - poisoned that episode for
the life of the container, and the only cure was redeploying the dashboard.

`open()` now treats a FAILED entry as ABSENT: it is dropped and a fresh
builder thread starts. A failed entry already held no seat (the `live` count
skips it), so nothing about the cap changes. `RETRY_FLOOR_SECONDS` (20 s) is
the one addition the verifier asked for: a build that fails SLOWLY plus a page
somebody keeps pressing would otherwise be a thread per press, so a retry
inside the floor is refused with the seconds to wait. The template draws
`[ CLOSE ]` from a new per-row `may_close` instead of `session_is_admin`, and
for `failed` as well as `ready`, so a failed episode offers both doors.

### CR-285B (dash-cards-3) - the cap refusal named a page that does not exist and an act that frees nothing - FIXED (cards_pool.py)

`_full_sentence` read "Ask one of them to leave it, or an admin can close an
idle one on Settings > Timeline Cards." There is no Settings > Timeline Cards
page anywhere in the tree - the only close control is the form on the landing
page itself - and "leaving" releases nothing: a seat is held by the ENTRY, and
`occupants()` lapsing after 15 minutes changes the wording and nothing else.
A blocked editor was told to do a no-op and then sent looking for a page that
is not there. The sentence now names `[ CLOSE ]` beside the episode on that
same page, and says an idle one may be closed by anybody - which is true as of
CR-285P below, and would have been a second lie without it.

### CR-285C (dash-cards-4) - the /cards/sw.js kill switch deleted every cache on the origin - FIXED (cards_landing.py)

`KILL_SW`'s activate handler was `for (const k of await caches.keys()) await
caches.delete(k)`. CacheStorage is per ORIGIN, not per worker scope, so that
sweep also emptied the dashboard PWA's own `ccsync-<version>` precache - the
offline page and `htmx_errors.js`, which DUI-2 precached precisely for a bad
connection - and the dashboard's worker does not re-run `install` until its own
`__VERSION__` bytes change, so a phone stayed without an offline page until the
next dashboard release. It also took `cards-media`, the clips an editor
deliberately downloaded for an offline session, which after the 2026-09-12
incident is not a small thing. It now deletes only `cards-shell-*`, the stale
page shell it exists to remove; the names come from the other repo's own
`page/sw.js` (`SHELL = 'cards-shell-' + VER`, `MEDIA = 'cards-media'`), not
from a guess.

### CR-285D (dash-cards-5) - closing an episode leaked its 24-thread WSGI executor - FIXED (cards.py, cards_pool.py)

Every engine is wrapped in `a2wsgi.WSGIMiddleware(..., workers=24)`, which
builds a `ThreadPoolExecutor(max_workers=24)` in its own `__init__`.
`EnginePool.drop` / `stop_all` cleared `entry.asgi`, but `CardsDispatch._gates`
had no deletion path anywhere in the tree, so the middleware - and whatever
WSGI threads that episode had already spun up - stayed reachable from the
mounted dispatcher for the life of the container. An admin closing an episode
to free a seat therefore made the thread count worse than
`docs/CARDS_TWO_PROJECTS.md` §12's accounting says it is. The pool has no
reference to the dispatcher, so the eviction arrives as a callback:
`EnginePool.set_evict_hook(dispatch.evict)` is wired in `mount_cards`, `drop`
and `stop_all` call it, and `CardsDispatch.evict` pops `_gates[slug]` and calls
`executor.shutdown(wait=False)` - `wait=False` because a request may still be
in flight on one of those threads and the threads are what is being reclaimed,
not the request. The same-slug reopen path evicts the old gate too.

### CR-285E (dash-cards-6) - the per-slug data dir abandoned every engine's existing state with no word - FIXED (cards.py)

`data_dir_for` moved the engine's `data_dir` from `<data>/cards` to
`<data>/cards/<slug>` and nothing moved the files already there:
`cards_mirror.json`, `cards_pick.json`, `cards_lane_keys.json`, `cards_ui.json`,
the EN-index / translation caches and `library_backups` - the last of which is
the safety net for the cut list itself. They simply sat unread one directory up.

NOT adopted, on the verifier's reasoning and the owner's risk: which episode
the flat files belonged to is not recorded anywhere (§11 removed the boot root
in the same change), so an automatic adopt is a guess, and guessing wrong
writes another episode's pick and mirror into this one, which is worse than the
loss. `_say_where_the_old_state_went` logs ONE warning per data dir naming both
paths and the files it found, so nobody spends an evening looking for the
backups. The files are only orphaned, never deleted.

### CR-285F (dash-collector-alerts-2) - the 500-move cap dropped the rest of a pass permanently while its log line promised otherwise - FIXED (collector.py, notices.py, db.py)

`moves = moves[:DETECTED_MOVE_LIMIT]` runs AFTER the loop that has already
called `db.replace_nas_media` for every walked project, and those rows were the
only record of the old paths - so the surplus cannot be "picked up on later
cycles", which is what the warning said. A later cycle sees those files at
their new paths as ordinary inventory. The dropped moves are therefore a
DELETION as far as every machine is concerned: lane A re-uploads them to the
old paths, lane B's breaker parks proxy download on every machine that held
them, and the only trace was one `log.warning` in a container log a recreate
throws away. The truncation is alphabetical by `(from_slug, from_rel)`, so what
survived was arbitrary with respect to importance.

The log line no longer states an untruth (it says DISCARDING and the count),
and `notices.record_moves_dropped` files an ERROR notice naming both numbers
with the fix line "move the rest with [ MOVE ON THE SERVER AND ON EVERY
MACHINE ]". `file_moves_dropped` is registered in `db.NOTICE_KINDS` WITH its
writer and stamped `mark_notice_checked` from the same inventory pass that owns
`file_move_detected`, so a fleet that has never overrun the cap does not read
[ NOT CHECKED ] for ever. Not fixed here: making the cap RECOVERABLE (deferring
`replace_nas_media` for the affected projects) reorders phase 2 of the walk and
is not a fix-pass change - see "Not fixed".

### CR-285G (dash-collector-alerts-3) - a folder RENAMED in place was one detected row per file - FIXED (collector.py)

`_folder_move` derived its candidate folder from the shared SUFFIX only and
then iterated `range(shared, 1, -1)`. For a rename of the leaf folder itself
(`Interviews` -> `Interviews 2026`, `B-roll` -> `Broll`) the only shared
component is the basename, `shared == 1`, the range is empty, and every file
fell through to the per-file loop. Only a folder moved under a DIFFERENT parent
- which shares the folder name as well as the basename - was ever batched,
while `docs/HAND_MOVES_ON_THE_SERVER.md` section 7 phase 1 promises one row per
folder for both. A 300-clip rename was 300 `file_moves` rows, 300
`commands.file_moves` entries per holding machine, 300 events in the project
page's MOVES history and a third of CR-285F's 500-row cap in one pass; 600
files crossed it and lost the tail.

The candidate list now also carries the other end of the path: the first
component where the two paths DIFFER, bounded so it names a FOLDER and never
the file. `_folder_members` still does all the proving - every file under the
old folder moved to the matching path under the new one, and nothing stayed
behind - and the `Proxy` refusal at either end is unchanged. Two existing
tests had to be corrected rather than kept: the cap test's five files all moved
into one folder (one row now, which is the fix), and the idempotence test's
synthetic second diff held ONLY the moved file, which now legitimately reads as
that folder having been renamed. Both were given the shape the collector really
produces, and both cite the finding.

### CR-285H (dash-core-1, dash-core-6) - a secret file could land empty and the boot refusal passed on it - FIXED (secrets_boot.py, app.py)

`_write_secret_file` was `os.open(O_WRONLY|O_CREAT|O_TRUNC)` + `fh.write`: no
temp file, no rename, no fsync, no read-back. The good copy was destroyed
BEFORE the new bytes were written, `ensure_secrets` swallows the OSError and
carries on with the in-memory value, `_read_secret_file` strips an empty file
to `""`, and `check_persisted_secrets` - the whole DCORE-3 refusal - asked only
`is_file()`. So a create that succeeded and a flush that did not (ENOSPC on a
full `/data`, a kill or a host power loss between write and disk) left a
ZERO-BYTE file that satisfied the refusal, the dashboard served on a secret
that existed only in memory, and the next `docker restart` minted a different
one: every browser session and every non-expiring `cce1.` identity token in the
fleet 401'd at once, with nobody ever having known the lost value.
`DASH_SESSION_SECRET_PREVIOUS` cannot help with a value nobody knows.
`internal.env` and `syncthing.env` go through the same helper on EVERY boot,
where a truncated `CCSYNC_INTERNAL_TOKEN` is the dash-admin-2 outage by another
road (dash-core-6, the same root cause).

Both halves, as the verifier asked. The write is a sibling `.tmp` (same
directory, so `os.replace` is atomic), 0600 set on the fd before the rename so
the secret is never briefly world-readable, `fsync` before the rename, and the
temp removed on any failure so a failing volume does not fill with them.
`check_persisted_secrets` compares the file's CONTENT with the value this boot
is using rather than testing existence. `ai_providers.write_secret_file` shares
the helper and inherits both, which is what that docstring always promised.

### CR-285I (dash-db-1 = dash-collector-alerts-4) - a collector pass that held no write lock was recorded as the writer that held it, for ever - FIXED (collector.py, notices.py, db.py)

`_timed` measures `elapsed` around the WHOLE runner - `_run_inventory` is an
SSH walk of the NAS tree, `_run_enforce` and `_run_connections` are Syncthing
round trips - and treated anything over `BUSY_TIMEOUT_MS / 1000` as evidence
that the poll "held the database's write lock for longer than a request waits".
`_record_inventory`'s own docstring says the opposite, by design: every
filesystem walk happens BEFORE the first write, because an `os.walk` of a
ZFS/NFS tree inside an open SQLite write transaction is what made editors'
`POST /api/v1/report` 500. So on any tree of size the home page grew a
permanent `slow_write` card blaming an innocent pass, un-dismissable (`db.notice`
NULLs `cleared_at` on every re-assert), climbing by one per cycle, competing for
the 25 rows of `NOTICE_PANEL_LIMIT` with real findings - and it pointed the
`db_busy` fix line's cross-reference at the wrong thing.

The poll branch has its own kind (`slow_poll`), its own words ("the <kind> pass
took longer than a cycle ... most of a pass is a walk of the NAS tree or a
Syncthing round trip, which happen outside any database transaction, so on its
own this does not mean anything waited on the database"), its own threshold
(`notices.SLOW_POLL_SECONDS`, one cycle rather than the write-lock timeout) and
- the half the hunter asked for and nothing had - a CLEARING writer: a pass
that finishes inside a cycle closes its card. `record_slow_write` keeps its
wording and its one honest caller, `api_report`'s measured write burst.

A CLEAN PASS WRITES NOTHING, and that is load-bearing rather than tidy: the
first version of this fix cleared unconditionally, which is a write
transaction per poll per kind, and `tests/test_db_write_locks.py` went red with
`database is locked` on every companion report and took three minutes.
`_slow_polls` remembers which kinds have a card open and is seeded from the
table once per kind with a SELECT, so a card that survived a restart still
clears without a write on the happy path.

### CR-285J (dash-db-2 = dash-collector-alerts-5, tests-5) - two notice kinds with a writer and no registry row, and the test that could not see them - FIXED (db.py, notices.py, collector.py, tests/test_alerts.py)

The 2026-09-17 busy-database rework added `db_busy` and `slow_write` writers
and no `NOTICE_KINDS` rows. That registry is where every rendered property of a
notice comes from: `notice_kinds()` builds the WHAT THE SERVER CHECKS panel,
`notice_href()` builds `[ TAKE ME THERE ]`, and `ui.py`'s health rows take the
row's TITLE from it with the raw key as the fallback. So an operator under
contention read a problem card headed `db_busy` with no link, and the panel
that exists to answer "is it even looking?" had no line for database contention
at all - the mirror image of the false `[ OK ]` this registry was built for.

All four kinds of this wave are registered (`db_busy`, `slow_write`,
`slow_poll`, `file_moves_dropped`, plus `broll_archive_unreadable` from
CR-285R), each WITH its writer, and `notices._check_contention` stamps the
three contention kinds' check times on the notices cycle - not from `_timed`,
which would be the per-poll write CR-285I is about. `tests-5`'s half is the
test: `test_every_new_kind_is_in_the_registry_and_the_weekly_list` loops over
sixteen names typed into the test file, so it can only fail when a kind is
DELETED, never when one is added and forgotten, which is the failure its own
docstring claims to prevent and which shipped twice in one week. The new
`test_every_notice_kind_any_writer_passes_to_db_notice_is_registered` walks the
AST of every module under `src/ccsync_dashboard/`, resolves a module-level
constant kind, and REPORTS a call whose kind it cannot read rather than
skipping it.

### CR-285K (dash-mounts-ui-4) - five amber conditions behind [ DETAILS ] that the note count did not know about - FIXED (health.py)

`detail_notes`' own docstring says its count "is the one thing shown beside the
collapsed expander, so that folding a row's diagnostics away can never hide a
real problem silently". The 2026-09-11 declutter moved five conditions INTO
that fold and into neither `detail_notes` nor `why_causes`/`fleet_headline`:
`skipped_exists`, `transport.express_last_error`, `transport.express_dropped`,
`guard.trash_bytes` over 5 GB and `guard.ingest_staging_bytes`. An editor whose
express upload had been failing for a week drew a muted "Idle, nothing owed"
headline, three quiet lane chips, and `[ DETAILS ]` with no count at all: the
one place the failure was stated was inside a fold with nothing to suggest
opening it. All five are notes now. `transport` is fetched as defensively as
`guard` and `proxy` (a build that never sent the section has no key), and the
trash threshold is the TEMPLATE's 5 GB, because a count that disagreed with the
chip beside it would be worse than no count.

### CR-285L (live-1, dashboard half) - a stall the companion recovered from a week ago was reported as a current blockage and alerted daily, for ever - FIXED (health.py)

SYNC-1 (2026-08-28) made the companion's stall record persistent so a restart
could not erase the evidence, and gave it no expiry and no "the lane has since
completed a pass" condition. `~/.ccsync/state/lane_stall.json` therefore rides
every report for the life of the install, and `_why_code` read any record as a
CURRENT blockage. Live on 2026-09-18: ruskin's lane A was killed once after 25
minutes of no progress on 2026-09-11 and restarted the same day; a week later
all three of his lanes were idle with nothing owed, his last report was four
minutes old, and his row still said `blocked_reason=lane_stalled since
2026-09-11`, his tray was red, and "CC Sync: still not fixed after 4 day(s)"
had gone out by mail four mornings running. leso's Mac had the same shape from
a 2026-09-17 stall. Nothing any editor or admin could do cleared it.

`health.stall_is_current(row, now)` is the one predicate, and it is safe alone
against a 0.9.74 companion - which is the whole fleet - because it reads only
what those builds already send: `stalled_at` in the guard block, and the lane
rows' `last_sync`. A record stops being current when that lane has completed a
pass since the kill, or when it is more than `STALL_CURRENT_SECONDS` (24 h)
old. NO `stalled_at` keeps the old behaviour: "cannot tell" must never quietly
turn a real stall green. The companion half (clearing or stamping the file when
a pass completes) is `companion-core`'s and is not needed for this. CORRECTED
2026-09-18 by the second builder: this section originally said the fix stops
the mails fleet-wide in one deploy, and it stops the ROW and the tray. The
mail is `alerts._check_lane_stalled`, which had no age test of its own - see
CR-285AP, which is the other half of the same sentence.

### CR-285M (live-2 = dash-api-6) - a publish placed its bytes before the row existed, so a failed insert left a replaced live artefact - FIXED (package_store.py)

`store_verified_package` did `os.replace(part_path, dest_dir / filename)` and
only THEN `db.insert_companion_package`, with the commit later still. The PUT
route 409s on `db.get_package` before the body is streamed, so two publishes of
one version that OVERLAP both pass that check - the ship interrupted and
re-run while uvicorn drains the first, `publish_latest` retried after a timeout
- and the loser's bytes were already at the served filename when its INSERT hit
`UNIQUE (kind, platform, version)`. Seen live on 2026-09-17: the 0.9.74 publish
hit the route twice, each time answering a 500 that is now an open
`server_error` notice telling the admin to send the detail to support, and each
time swapping the artefact under a row whose `sha256` describes the first
upload's bytes. Every companion downloading that build then failed its hash
check and could not upgrade, with the Packages page showing a normal record.

Two changes. A version this server already holds is answered BEFORE anything
on disk moves: the same bytes are a no-op with a note ("already published at
this version, with these exact bytes"), different bytes are a 409 naming what
to do, and the `.part` is unlinked either way. And the `os.replace` moved to
AFTER `conn.commit()`, past the REL-1 make-current gate that can raise, so the
worst case is the other way round: a row whose file is missing, which is a loud
404 on download and is fixed by publishing again. That is the direction DASH-3's
commit-then-unlink ordering already chose for the pruned files on the next line.

### CR-285N (live-4, comp-resolve-5, comp-broll-tiers-5) - three report fields the dashboard threw away, one of them telling the admin to update a current dashboard - FIXED (api.py)

The companion's `stray_projects()` has carried `slugs` and `checked_at` since
the 2026-09-11 fix pass and `StrayProjectsIn` never declared them. An
undeclared key inside a reported SUB-MODEL is invisible to `model_extra`, which
is why the generic walker could not see it - what it did instead was open
`ignored_report_sections` as a warn on 2026-09-11 with the fix line "Update the
dashboard", on a dashboard that IS current, and keep it open for a week
(`last_seen 2026-09-18T03:42:07`). An admin who followed that line found nothing
to update, and a real future "companions ahead of the dashboard" event would
have been invisible behind it.

`slugs` (bounded at 20, like `paths`) and `checked_at` are declared. Two more in
exactly the same shape, owed here by `companion-core` and both dashboard-first:
`ProxyAttachIn.refreshed` (comp-resolve-5 - the companion counts refreshed
clips beside attached/failed now) and `ResolveHealthIn.standins_owed`, a bounded
`StandinsOwedIn(count, why)` (comp-broll-tiers-5). Declaring them is the
contract; storing them is a later decision, and the verification test feeds the
PRODUCER's real dicts through all three models so the next added field fails a
test instead of opening a notice.

### CR-285O (wire-2) - "a busy database is contention, not an error" stopped at the dashboard's own routes - FIXED (app.py)

`@app.exception_handler(Exception)` is installed on the PARENT FastAPI app's
`ServerErrorMiddleware`, and `/broll`, `/music` and `/ytdl` are real ASGI mounts
with error middleware of their own: they answer their own plain
`500 Internal Server Error` and the parent's `is_db_busy` -> 503 branch never
runs for them. Measured: parent route 503, mounted route 500. `broll/web`
opens its connections at sqlite3's default busy timeout and has no busy
translation anywhere, and the companion's ingest client treats any non-200 from
`/items/{uid}/result` as TERMINAL - it clears `described` and calls
`_fail_item`, so a `publish_db.py` swap holding a write for five seconds cost a
clip its minutes of local VLM work and nothing recorded that the archive
database was merely busy.

`_install_busy_handler_on_mounts` walks the parent's routes after every mount
and installs the same handler on any mounted app that has a handler registry,
so a fifth mount added later does not have to remember. Deliberately not a
reference taken at each mount site: the four mounts are built in four modules
on four tri-state contracts. `/cards` is skipped (its mount is a bare ASGI
callable, and its database is the episode's). The notice is written to the
DASHBOARD's database, because the sub-apps have no `settings.db_path` and the
PROBLEMS panel that has to show it lives here. A real defect under a mount is
still a 500.

### CR-285P (security-2) - any signed-in non-admin could take both Timeline Cards seats, and only an admin could give one back - FIXED (cards_pool.py, cards_landing.py, templates/cards_landing.html)

The pool caps live entries at `DASH_CARDS_ENGINES` and REFUSES the third rather
than evicting, which is deliberate. But opening was available to every session,
closing was admin-only with no self-close, and nothing ages a seat out
(`ACTIVE_SECONDS` only decorates the refusal sentence). So an editor who opened
the wrong episode by mistake and then the right one held both seats and could
release neither, and everybody else - including the person whose phone is
staging a cut - got CR-285B's refusal with no way to act on it until an admin
was found or the container restarted. A bad state the user cannot clear, on the
surface a phone stages a cut on.

`EnginePool.may_close(slug, editor, is_admin)` is the rule: an admin may close
anything; anyone else may close an episode they are themselves an occupant of,
or one nobody has been in for `ACTIVE_SECONDS`, which is exactly the "idle one"
the refusal now names. `cards_close` asks it and redirects with the refusal
when it says no; the template draws the button from `may_close` so the page
never promises an act it cannot do. Taking an episode away from somebody who IS
in it is still admin-only, because that is the act that must not happen by
accident.

### CR-285Q (res-fleet-2, comp-app-3) - a pushed update the machine can never take removed that computer from the jobs fleet, and the reply could not say why - FIXED (api.py)

Two halves of one silence. `_upgrade_info` withholds an offer - silently, by
design, because there is no "refused offer" shape in the protocol - for a
retracted build, one needing a newer dashboard, and one built for another
processor; and `machine_update_request` emitted `commands.upgrade` whenever a
request existed, computed independently of that. So a machine was asked for a
build it is not being offered, logged "this machine is not being offered that
build" once in a log on somebody else's PC, reported nothing back, and
`jobs.machine_facts` turned "has an update waiting" into a blanket refusal of
every job kind - out of the whisper/proxy/peaks fleet until
`db.expire_machine_update_requests` dropped the row 14 days later (the
verifier's correction: bounded, not "for ever").

`_machine_can_be_offered` asks the SAME `_upgrade_info` the offer comes from
rather than copying its three refusals, and fails OPEN - anything unexpected
sends the command exactly as before, so a defect here cannot take the push
channel away. When the answer is no the command is not sent, the request is
LEFT STANDING (the build may become offerable again: an un-retraction, a
dashboard update), and a plain `upgrade_none_reason` rides the reply.

That key is comp-app-3's half, owed here by `companion-core` and already
written on the companion side, inert until this lands: `_upgrade_info` takes an
optional `withheld` sink and the report reply carries
`upgrade_none_reason` when a build exists and is being held back, so the
companion can tell "there is no build" from "there is a build, we are just not
offering it to you" and stop clearing the standing refusal it is on. Additive
and ignored by every build in the field that does not read it. DASHBOARD FIRST.

### CR-285R (proxy-tiers-3, dashboard half) - an archive this container cannot list turned every insert into a preview, and nothing said so - FIXED (notices.py, mount_status.py, db.py)

Owed here by `companion-media`, whose half answers `known: false` and falls
back. `insert_target_detail` discovers a clip's original and its editing proxy
by LISTING the archive folder inside this container, and an OSError there - the
dataset unmounted, an SMB hiccup, `BROLL_DATA_ROOT` wrong after an image update
- was swallowed into "no entries", which is byte for byte the answer for "this
clip has no original". Ten minutes of that turned every Send to Resolve in the
window into a preview-only insert with a stand-in ledger row on the editor's
machine and a Resolve project pointing at a 540p file, damage that outlives the
outage for ever on projects nobody re-checks - and the dashboard showed no
error, because the detail view was otherwise complete.

`notices._check_broll_archive` runs on the notices cycle, asks
`mount_status.root_of("broll")` (a new accessor, so the check and the mount
cannot disagree about which directory this is) and files an ERROR notice naming
the path and the strerror when the listing raises, with the fix line pointing
at the bind mount. It clears itself when the mount comes back, and a build with
no b-roll mount writes and clears nothing - "could not check" is not evidence
that the archive is fine. `broll_archive_unreadable` is registered WITH the
writer. Not done: the matching `alerts.ALERT_KINDS` row, which would mail it -
see "Not fixed".

### CR-285S (dash-release-jobs-1) - the restart path still died on a full or read-only /data - FIXED (dashboard_update.py)

CR-260g routed the HEALER's two writes through `_write_json_best_effort` and
explicitly left every other caller unchanged - but the failure path that ledger
entry describes is `finish_restart -> consume_restart_request -> _set_state`,
which is a WRITE through the unguarded `_write_json`. So on a data dataset that
is full or read-only the OSError still escaped, `_exit_process(RESTART_EXIT_CODE)`
still never ran, uvicorn still exited 0 and `deploy/run.sh` still did not
re-exec the tree `current.json` already names. The fix moved the raise one line
later. The same unguarded write is the FIRST statement of `request_restart`, so
on the same disk the apply worker raised before `_signal_restart()` ever fired
and `_fail_state` then raised again inside its own `except`, leaving
`in_progress: true` on disk with no restart requested at all.

`_set_state` takes `best_effort`, and the three callers whose decision must
survive an unwritable volume use it: `consume_restart_request` (the exit code is
decided from the state it READ), `request_restart` (the restart matters, the
note about it does not) and `_fail_state` (it runs inside an `except`; a
`_fail_state` that raises replaces the real failure with an OSError). The
lifespan's `try/except` around `finish_restart` stays - it is the last net, not
the fix.

### CR-285T (dash-api-4 = dash-mounts-ui-5) - a lane a machine never reported drew as a quiet GREEN chip - FIXED (templates/partials/fleet_grid.html, static/style.css)

`health.lane_strip` fills a missing lane with `{"state": "not reported",
"chip": GREEN, "reported": False}` and the template coloured by `chip` alone
(`"quiet" if lane.chip == "green"`), so the `reported` flag it is handed was
never read: "this lane did not report" and "this lane is fine" were the same
grey box, differing only in the words inside. That is the "could not check must
never render as a green reassurance" rule the same file states twice about its
own disk chip and its Resolve block. The template reads `lane.reported` now and
draws an unreported lane in `.chip.lane.unknown` - dashed and dimmer, not
amber, because it is a gap in the evidence and not a fault. Fixed in the
template rather than in `lane_strip`, as the verifier asked: changing `chip` to
amber would change what every downstream counter keyed on chip colour sees.

### CR-285U (dash-mounts-ui-6) - the b-roll mount recorded its PROXIES directory as its root - FIXED (broll.py)

The hand-off wave added `record_root`'s `witness` parameter and updated music
and ytdl; b-roll was left on the older single-argument shape with the proxies
directory as its ROOT. `record_root`'s docstring states the contract the other
two now follow ("The root is still what the degraded sentence names: the admin
has to be told which mount is gone, not which file this server happened to
stat"), and `recheck` formats the first element - so with `/broll-data`
unmounted the notice named `/broll-data/proxies`, sending the admin at the NAS
to look for a subdirectory. Now `record_root("broll", get_data_root(),
witness=get_proxies_dir())`, which is also what CR-285R's archive check reads.

### CR-285V (dash-db-4) - the "who holds this file" query was a LIKE with the path's own wildcards unescaped - FIXED (db.py)

`file_move_target_machines` bound `media_rel_key(from_rel) + "/%"` into
`rel_path LIKE ?` with no `ESCAPE`. `_` is a single-character wildcard in SQL
LIKE and is in half the folder names this product handles (`Gold_Card_Meetup`,
`A_001`), and `%` is legal in a filename too - so a directory move of
`Gold_Card_Meetup` also matched any sibling of the same length differing only
where an underscore sits. That machine was sent a `commands.file_moves` entry
for a file it does not hold at that path; the companion's not-found arm answers
harmlessly, but the move's per-machine progress row on the project page was
wrong, and the next reader of this predicate would inherit the over-match.
`_like_prefix` escapes the escape character first, then `%` and `_`, and the
statement carries `ESCAPE '\'`. The other prefix LIKE in `db.py` documents
itself as a prefilter with an exact re-check and is unchanged.

### CR-285W (dash-db-5 = dash-mounts-ui-3) - the assignments picker offered a computer whose grid can never have a column - FIXED (assignments.py)

`_machine_options`' own docstring promises "Never a bucket option invented
beside two real computers", and it then APPENDED one whenever
`db.selections_for_machine(conn, editor, ANY_MACHINE)` was non-empty - on
exactly the legacy shape the docstring calls out. `_assignments_view`'s column
loop only ever emits a `machine=""` column under `if not machines:`, so choosing
the offered option filtered every column away and the page printed "this person
has no computer to show a plan for yet", which the picker had just contradicted
- and the bucket rows the option existed to expose could then be neither
inspected nor removed there. The narrow fix, per the verifier: the option is
offered only when the person has no registered machine, matching the column
loop. Building a bucket COLUMN beside real ones would create a tick target
`db.selections_for_machine` only honours for a machine with no plan of its own,
which is a write shape and not a display change (CR-110). The rows are not
lost: `db.fetch_machine_selections` expands the bucket onto every machine with
no plan, so the real column renders them ticked and correct.

### CR-285X (dash-core-3) - OIDC minted a session for a username the rest of the dashboard will not accept - FIXED (oidc.py)

`username_from_claims` lower-cased the claim and refused only `@`, `/` and `\`.
Everything else became the session identity - a space, a colon, non-ASCII, a
leading digit, 200 characters - while `db.record_known_editor`,
`db.set_selection` and `local_users` all gate on
`^[a-z][a-z0-9._-]{0,31}$` and simply refuse. On a deployment that lets the IdP
decide membership (`DASH_OIDC_ALLOWED_GROUPS`) with `DASH_OIDC_USERNAME_CLAIM`
pointed at a display name, that editor appeared signed in to a dashboard where
every tick, every Syncthing device join and every selection write did nothing,
with no sentence anybody could read. The regex is IMPORTED from `db` rather
than copied a third time, and the refusal names
`DASH_OIDC_USERNAME_CLAIM` and the shape it wants: a 403 an admin can act on
beats a session that half-works.

### CR-285Y (dash-core-4 = security-1) - the open PWA paths were method-agnostic although every comment beside them says GET only - FIXED (app.py)

`_open_path` took a path; `login_gate` called it before any method test. So any
verb on `/cards/sw.js`, `/cards/manifest.webmanifest`, `/cards/icon.svg`,
`/manifest.webmanifest`, `/sw.js`, `/offline`, `/favicon.ico`,
`/.well-known/assetlinks.json` and the whole `_OPEN_PATTERN` skipped the
session check - and under the cards mount `POST /cards/p/<slug>/sw.js` was
dispatched to that episode's gate and into the checkout's `do_POST`, which
reads and `json.loads`es the whole body and runs `offline.resolve_spans` BEFORE
any path match. Not exploitable today (the dashboard's own routes at those
names are GET-only and 405, `CardsDispatch` never builds an engine, and
`csrf_gate` skips an unauthenticated request anyway), but the invariant three
comments assert was not the one the code enforced, and the next handler
registered at one of those names would inherit an unauthenticated write door
with nothing in its diff to say so. `_open_path(path, method)` requires
GET/HEAD for the static members and the pattern; `/login`, `/api/v1/login`,
`/api/v1/report`, `/api/v1/diagnostics`, `/api/v1/ssh-key` and the setup pair
are POST targets whose credential is not a session and are untouched.

### CR-285Z (dash-core-5) - expired browser sessions accumulated on a long-running container - FIXED (collector.py, app.py)

`sessions.py` says "expired sessions are deleted rather than left to
accumulate", and the only unconditional sweep ran in the lifespan at BOOT.
`validate()` deletes a row only when that exact cookie is presented again after
it expired, and nothing in `collector.py` - the module that prunes the other
eight tables - touched `auth_sessions`. A session from a phone nobody opens
again, or a laptop that was reimaged, stayed until the next container restart;
on a container that runs for months `list_all(limit=200)` starts hiding live
sessions behind dead ones. The collector's prune cycle calls
`session_prune_fn`, which is the STORE's own `prune()` and `prune_attempts()`
on the store's own connection and write lock - not SQL on the collector's
connection, or two writers fight over one table. AND it runs AFTER
`conn.commit()`: the first version called it inside the open write transaction
`db.prune` leaves behind, which is a second writer waiting out its background
busy timeout while this one holds the lock, and `test_db_write_locks.py` caught
it as `database is locked` on every companion report.

### CR-285AA (dash-release-jobs-2) - an untrusted feed host could rewrite the provenance of a package this dashboard published itself - FIXED (release_feed.py)

PREMISE CORRECTED (2026-09-18b, verifier dash-release-jobs-2, checked by the orchestrator): the vendor channel document is signed as a WHOLE (`canonical_channel_bytes` dumps the entire document sorted; `verify_channel_signature` rejects it before use), so a feed host cannot rewrite `git_dirty` or any other field without the offline release key. The change below is harmless (a narrower `repair_provenance`) but the threat it names does not exist; keep it as hygiene, not as a security fix.

`git_sha` and `git_dirty` are outside the Ed25519 record signature by design
(REL-13 - they are advisory), so a feed host, or anyone who can serve its
static files, can edit them freely without breaking any signature.
`repair_provenance` read exactly those two fields off the feed and UPDATEd them
onto any already-published row whose sha256 matched, arguing that the sha check
means "a vendor copy that differs from ours cannot rewrite our row's story" - but
a matching sha proves only that the BYTES agree. So a build published here by
`ship.cmd -AllowDirty` and correctly stamped `+dirty` could have that chip
cleared, and the commit shown on the Packages page rewritten, on the one day
the chip exists for. The verifier's narrower alternative is what landed, because
the `published_by` gate would have stopped the repair working at all (the feed
page's own [ PUBLISH ] button stamps an admin's username, not `release-feed`):
ONE correction in ONE direction - a row that says dirty where the feed record
says clean, which is exactly the `bool("0")` bug this function was written for -
and `git_sha` is never written. Nothing may make a clean row look dirty.

### CR-285AB (dash-release-jobs-4) - a recall whose kind is not lower-case recalled nothing, silently - FIXED (release_feed.py)

`channel_retractions` folded `platform` and left `kind` at `.strip()`, while
`companion_packages` stores kind folded and `db.retract_package` ->
`get_package` matches it exactly. A recall entry spelled `"kind": "Companion"`
therefore un-currented nothing and `retract_package` answered False, which is
indistinguishable from "we never published that" - and nothing logged either
way. The module's own comment calls a recall "the one channel message whose
SUPPRESSION is the attack"; this was suppression by a capital letter. `kind` is
folded now, exactly as `platform` beside it and `_record_key` everywhere else.
(The verifier's correction: `_valid_records` builds both sides of its `recalled`
set from the raw kind, so the OFFER was suppressed correctly; the two halves
disagreed only against the database.)

### CR-285AC (dash-release-jobs-5) - re-applying the version already running erased the rollback target - FIXED (dashboard_update.py)

`"previous": previous if previous and previous != version else ""` blanks a key
whose `""` means "the image" to both `rollback` and `select_code_root`. So
applying the version `current.json` already names discarded the real previous
tree's name - not because there was no previous tree, but because the
arithmetic could not express "unchanged", and the admin who then pressed
ROLLBACK got the image's much older code against a v53 database. The verifier
replaced the hunter's scenario (`preflight` 409s on the version this dashboard
is RUNNING, and `force` does not bypass it) with the reachable one: after a
swap whose restart did not happen (CR-285S) or a boot that fell back to the
image, the running `VERSION` is not `current.json`'s version, so the re-apply
passes preflight. The existing `previous` is carried forward unchanged.

### CR-285AD (regression-4) - CR-259a's guard treated "the staged tree could not say what schema it knows" as schema v0 - FIXED (dashboard_update.py)

`select_code_root.tree_schema_version`'s own docstring says "None is NOT zero
and must never read as safe", and `revert_refusal` is built on that three-way
answer - but the writer was `int(checks.get("schema_version") or 0)` in both
places, and the stage-verify subprocess already defaults the key to `0` in its
own `except`. A tree whose probe could not answer was therefore recorded as a
tree CLAIMING schema v0, `0 >= live` is false for every live schema, and the
crash-loop rollback CR-259a exists to permit was refused for ever with a
sentence naming a number the tree never claimed. The key is written only when
the probe answered and popped otherwise, so "cannot tell" reads back as
`None`, which is what the reader wants.

### CR-285AE (dash-mounts-ui-1) - CR-270 wrote `retired_from` / `retired_reason` into a file no surface reads - FIXED (dashboard_update.py, templates/partials/admin_dashboard_update.html)

CR-270's retire branch clears `current.json`'s `version` and `previous` and
records WHY beside them; `dashboard_update.status()` builds its `current` dict
from a deliberately FIXED key list that did not carry the two keys, and the
Settings partial renders that dict. So an admin who applied a bundle over the
air came back weeks later, after a newer image was deployed, to a panel showing
no applied version and no reason at all, with the only record a stderr line in
a container log the appliance's whole promise says nobody should need. This is
the same shape as res-fleet-3, which was fixed one commit earlier for
`revert_refused_reason` with the comment "a refusal that reaches no API body
reaches no notice and no alert either". Both keys reach the body now and one
calm line renders them - not a banner: nothing is wrong, the image simply
carries it.

### CR-285AF (security-4, parse-cost half) - a locate body was fully parsed before its own cap was consulted - FIXED (app.py)

`LocateIn.files` has no `max_length`, so `MAX_LOCATE_FILES` (2000) ran INSIDE
the handler, after pydantic had built every `LocateFileIn` in a body up to the
4 MB default ceiling - roughly 100k entries - on a single-worker container by an
authenticated fleet caller. Fixed with a `_BODY_LIMITS` entry
(`MAX_LOCATE_BODY_BYTES`, 512 KB), which is a declared-length refusal before
any buffering, rather than with `Field(max_length=...)`: the verifier's point
is that the latter turns the route's careful 413 sentence into a pydantic 422
the companion has never seen, and that sentence exists precisely so a caller
does not read a truncated answer as "not on the server". The route's
cross-project SCOPE is not touched - `api_locate_files`' own docstring chose it
knowingly and the verifier REFUTED that half.

### CR-285AG (security-3) - the Cards carry-on cookie set `secure` from the raw request scheme - FIXED (cards_landing.py)

Every other cookie this server sets goes through `auth.cookie_secure`, which
honours `DASH_COOKIE_SECURE` and `X-Forwarded-Proto` from a TRUSTED proxy. The
new 90-day `ccsync_cards_last` cookie asked `request.url.scheme` directly,
which behind a TLS terminator (Tailscale Serve, the funnel port) is `http` - so
on a site that forces `DASH_COOKIE_SECURE=1` the session cookie carried Secure
and this one did not, invisibly. It carries only a slug and is httponly, so the
value of the finding is the one-helper rule, which is what stops the next
cookie from being a credential. `/cards/open` now goes through the exported
`remember()` helper with `auth.cookie_secure(settings, request)`, which also
gives that helper the caller its docstring claims.

### CR-285AH (dash-cards-7) - the raw build exception was rendered into the landing page - FIXED (cards_pool.py)

`_run_build` stored `entry.detail = f"{type(exc).__name__}: {exc}"` and
`cards_landing.html` renders it with no admin gate, so whatever
`ProjectAgentEngine.__init__`/`start()` raises reached any signed-in user's
browser: a psycopg `OperationalError` carries host, port, database and user, and
an `OSError` carries container paths. This was the one place in the dashboard
that printed another repo's exception to a browser, while `app.py`'s
`unhandled_error` deliberately derives nothing from an exception. The page gets
the exception's TYPE and "The dashboard log has the detail"; the warning one
line up already logs the full text, so nothing is lost to whoever can read the
log. An admin-only render was rejected (it still prints the DSN to a browser).

### CR-285AI (dash-cards-9) - the failed-episode test could not fail for the bug it sat next to - FIXED (tests/test_cards_pool.py)

`test_an_episode_that_will_not_build_holds_no_seat` proved only that a
DIFFERENT root can still be opened after one fails. Nothing re-opened the
failed root and nothing asserted the landing page offers a way out of `failed`,
which is why CR-285A shipped green. Three tests landed with that fix rather
than before it: a failed episode can be opened again, a failed episode is not
rebuilt on every click, and the close control is drawn from `may_close`.

### CR-285AJ (server-tools-1, CI step) - the third-party notices generator was in no gate - FIXED (.github/workflows/ci.yml)

Owed here by `webapps-tools`: an LGPL dependency shipped to customers had no
entry in `docs/legal/THIRD_PARTY_NOTICES.md`, and `tools/gen_notices.py` - the
generator that would have caught it - ran only when somebody remembered.
`gen_notices.py --check` is now a step in the LINUX job, immediately after the
`dashboard-container` licence gate, and nowhere else: `--check` RENDERS the
notices from the component venvs, so it can only pass in a job that has
installed every `requirements.lock`, and that is the one that has. Ordered
after the licence gate so an unlicensed package is still reported as a licence
failure first.

### CR-285AK (regression-6, dashboard half) - a neutered assertion that cannot fail - FIXED (tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py)

`assert not hasattr(settings, "release_feed_sig_url") or True` is true for
every input, so the line said nothing. What the docstring actually claims - the
poll works whether or not the attribute is there - is proved by the rest of the
test and by its sibling; the line is gone and the comment says why. The
companion twin was removed by `companion-core`.

### CR-285AL (dash-collector-alerts-1) - a hand move between two projects was detected only when both fell in one cycle's 8-project window - FIXED (collector.py, db.py)

`_record_inventory` walks at most `inventory_projects_per_cycle` (8) projects
a cycle through a rotating cursor, and `_matched_pairs` can only pair a vanish
with an appearance inside the walks of ONE pass. A move out of project A into
project B is a vanish in A's walk and an appearance in B's, so on any fleet
with more than 8 active projects - this studio has well over 8 - the two
halves land in different passes, and `db.replace_nas_media` has already
destroyed A's old rows by the time B is walked. The move could then never be
detected again: a later cycle sees the files at their new paths as ordinary
inventory, every machine that holds them treats them as deletions, lane A
re-uploads them to the old path and lane B's breaker parks proxy download -
CR-267a's two days of warnings, again, on the exact incident this feature was
built for. The collapse brake's refusal has the same shape.

The halves a pass cannot pair are PERSISTED now (`nas_media_pending_moves`,
schema v54) and paired on a later cycle. The refusals are the within-pass ones
applied to the union: one source and one destination for a
`(basename, size, mtime_ns)` key or nothing happens, a proxy is never a half
of its own (within a pass it travels on its original's row), and two new ones
that only waiting a cycle can raise - a file that comes BACK to the path it
left is not a move (lane A re-uploading in the window before a command lands,
or an admin undoing themselves) and cancels both halves, and the two ends must
be different paths. A cross-cycle pair is always a FILE move, never a folder
one: a folder rename is proved by "every file under the old folder moved and
nothing stayed behind", and carried halves are by construction a partial
picture of their project, so that proof cannot be made from them and a
one-file carry must never become a directory rename the fleet applies.
Nothing here forces a full-fleet walk, which is what the verifier ruled out:
an `os.walk` inside an open write transaction is what `_record_inventory`'s
phase split exists to prevent. `db.prune` ages a half out after two days (the
retention lives there, not in the collector, so a container that stops running
the inventory kind cannot grow the table), a dropped half is simply the old
behaviour, and the halves of a move the 500-row cap discarded are KEPT so the
next pass can try again.

The honesty half the verifier called out is the same change:
`db.mark_notice_checked(conn, "file_move_detected", now)` was stamped
unconditionally, so a pass whose project directories were unreadable, or whose
inventory the collapse brake refused, reported the check as having RUN over
evidence it never saw. A blind pass now leaves the last honest stamp in place
and says so in the log, which the checks panel renders as a time going stale -
truthful, where [ NOT CHECKED ] is reserved for a deployment that has never
had a clean pass. `file_moves_dropped` stays unconditional: whether this pass
overran the cap is a fact about this pass whatever it could not read.

### CR-285AM (res-fleet-4) - a renamed or forgotten computer stranded its outstanding commands, and the alert about it had never once fired - FIXED (db.py, api.py, alerts.py)

`file_move_targets` and `resolve_undo_requests` are keyed on the HOSTNAME and
nothing in `db.py` ever deleted from either, so `forget_machine` (CR-76) left
them behind and a rename left them under the old name. The target kept
`applied_at IS NULL`, was never offered again, aged into `expired_at` and then
raised a warn whose fix line ("use [ MOVE ON THE SERVER AND ON EVERY MACHINE ]
again once that computer is back online") named a computer the dashboard no
longer has. Meanwhile that machine still held the file at the old path and
lane A, which never deletes, put it back on the NAS at the path the admin had
just cleared: the failure the whole feature exists to prevent.

Four parts, and the re-key is the careful one. Both tables are in
`_MACHINE_STATE_TABLES` now, so a forget takes its commands with it.
`adopt_renamed_machine` - the point where the registry has already PROVED the
old and new hostnames are one `machine_id`, and refuses while both look live
(SYS-18a) - moves the unanswered rows across with `UPDATE OR IGNORE`. The two
`pending_*` queries take an optional `machine_id` and look under the former
names of that SAME identity (`db.command_machine_names`), which covers the
report or two SYS-18a defers the adoption by; never the editor's other
computers, because a machine that never held the file must not be told to move
it (the verifier's caution: res-fleet-3's gap made wider). Because a row may
then be filed under a name other than the reporting one, the offer carries
`target_machine` and `api._by_target_machine` stamps delivery against the
row's own key - a stamp written against the reporting hostname would update
nothing and the command would age out with the machine having been told every
thirty seconds.

And the fourth part, found while fixing the third: **`alerts._check_file_moves`
has never fired**. It selected `rel_path` from `file_move_targets`, which has
no such column (the path is on the `file_moves` row), so every cycle since v36
raised "no such column" into `_rows`' defensive swallow - which exists for a
table a parallel work package had not created yet and reads a typo as "nothing
to report". The path comes from the join now, and a target whose computer is
not in the registry is one warn about the FLEET rather than one unanswerable
row per file.

### CR-285AN (proxy-tiers-4, dashboard half) - the wired rig had no cheap signal that a clip was born from a stand-in - FIXED (api.py, db.py)

Built exactly to the contract this file's previous section sketched, because
a companion builder is building the other half to it. A stand-in is placed on
the REMOTE editor's machine and `broll_standins.record` is called in one place
on that machine, so its ledger is per machine: the wired rig that later opens
the project has an empty ledger for those clips, the "or the ledger says so"
half of the tier plan's last table row can never fire there, and what is left
is an ffprobe of every archive clip every 120 s whose one action is a
`replace_clip` onto the same path that answers "Already linked".

So the fact travels with the FLEET. `sync_guard.standins_placed`
(`rels`, max 200, `checked_at`) is declared on the report - on `sync_guard`
because it is about what this machine did to the ARCHIVE, not about Resolve -
and each rel is the NFC archive-relative path of the ORIGINAL, never an
absolute path (the vault is a drive letter here and a container mount there).
`broll_standins` (v54) is keyed `(archive_rel, editor_username, machine)` and
`db.record_standins_placed` REPLACES that machine's set on every report, like
`editor_media`: a rel the companion no longer lists has been upgraded to the
real editing proxy, and a stale row would send a wired rig looking for a
stand-in that is not there. An ABSENT section changes nothing, which is what
every build in the field sends today. The answer rides the report REPLY as
`standins_known: {rels}`, bounded to the same 200 and best-effort - a hint is
never worth failing a report over - because the machine that needs the answer
is already sending the list the answer is about, and a second route is a
second credential path for a question that is not a secret. Absent means "this
dashboard does not know", which the companion must read as "demux as before".
`db.prune` ages a row out on `machine_state`'s own 30 days and
`_MACHINE_STATE_TABLES` drops a forgotten computer's. Every part is additive.
DASHBOARD FIRST.

### CR-285AO (proxy-tiers-3, the alert row) - the notice was drawn and never mailed - FIXED (alerts.py)

CR-285R filed the notice and left the `ALERT_KINDS` row for a pass with more
than half an hour in it. A notice is on the home page for whoever opens it; an
alert is MAILED, and this is the finding whose ten silent minutes put a 540p
preview into a Resolve project and a false row in an editor's stand-in ledger,
damage that outlives the outage on projects nobody re-checks. The kind is
registered with its check and therefore with its weekly "checked and found
nothing wrong" line. The check RE-DOES the listing rather than reading the
notice: an alert that trusts another cycle's row cannot fire on a deployment
whose notices pass is the broken thing, and this is one `scandir` on a
directory the container has open anyway. No b-roll mount records no root and
writes nothing, because "could not check" is not evidence that the archive is
fine.

### CR-285AP (live-1, the alert half) - the daily mail about a stall that healed a week ago - FIXED (alerts.py)

CR-285L fixed the ROW's sentence and this file claimed it "stops the daily
stall mails and the red trays fleet-wide in one deploy". Half true, and the
coordinator caught it: `alerts._check_lane_stalled` fires on
`g.get("stalled_lane") or g.get("stalled_seconds")` with no age test at all,
so the mail for ruskin/DESKTOP-LQQ41TC would have gone out on the morning
after the deploy exactly as it did on the four before it. The check now asks
the same `health.stall_is_current(row, ctx.now)` predicate `_why_code` uses,
so the mail and the page cannot disagree: a stall older than 24 h, or one
whose lane has completed a pass since the kill, is not a finding, and the open
alert RECOVERS through the existing `open_alert_subjects` rule rather than
simply going quiet. A stall with no `stalled_at`, and a fresh one, still fire -
"cannot tell" may not turn a real stall green. CR-285L's claim above is
corrected in place.

### CR-285AQ (dash-api-3) - `as_of` reported the freshest project in the tree as the freshness of THIS answer - FIXED (locate.py)

`_as_of` was `SELECT MAX(refreshed_at) FROM nas_media`, and `refreshed_at` is
written per project only when that project's walk actually replaced its rows -
so a project whose walk has been refused since a NAS reboot three days ago
keeps its old stamp while one healthy project walked every cycle makes every
answer look a minute old. The companion logs that number beside a rename it
made from three-day-old data, so even the post-mortem points the wrong way.
An answer that found something is stamped with the OLDEST walk that
CONTRIBUTED to it, which bounds the answer instead of flattering it; an answer
with no matches keeps the tree-wide maximum, where there is nothing to bound
and "how old is the picture at all" is the question. Same string on the wire,
so no companion release is needed - the verifier's objection to a per-entry
stamp does not apply.

### CR-285AR (dash-api-5) - a per-project count rendered as a fact about the whole computer - FIXED (db.py, api.py, ui.py, templates/partials/fleet_grid.html)

`SkippedExistsIn.subpath` was declared by CR-267a so the nested-key audit
would stop flagging every 0.9.7x companion, and nothing read it. The
companion's scan is scoped to one project prefix; the stored figure is one
number per MACHINE and `ui.py`'s sentence states it of the whole computer - so
an admin looking for four files was looking in the wrong nine projects, and
(the half the hunter missed and the verifier found) on a machine syncing
several projects each scan OVERWROTE the last, project Y's zero hiding project
X's four. The scope travels with the count now:
`machine_state.skipped_exists_subpath` (v54) is written in the same statement
as the count and by the same CASE, so the two can never describe different
scans, and `ui.skipped_scope` puts " (counted under Projects/2026/FF5)" into
the chip's sentence. An older companion sends no subpath and the sentence
simply loses the scope, never inventing "the whole tree", which is the claim
that was wrong.

### CR-285AS (dash-collector-alerts-6) - every sentence about a parked lane B was said from this server's own default - FIXED (db.py, api.py, health.py, alerts.py)

`_disk_floor_hit` compared free space against `DISK_RED_FREE_BYTES`, which is
the DEFAULT of the companion's `lane_b_min_free_bytes` and not the floor any
particular machine uses. An editor on a small SSD who raised it to 60 GB was
parked at 55 GB with this server saying nothing; one who lowered it to 5 GB
was told "proxy download stopped itself" on a row for a computer that was
still downloading - the same class of false sentence CR-269 fixed.

THE FLOOR WAS ALREADY ON THE WIRE, which is what turns this from a wire change
into a storage one (the coordinator's correction, and the hunter's "the
companion reports no floor value" was wrong):
`lane_guard.DiskFloorLatch.report()` has sent `floor_bytes` on
`sync_guard.disk_floor` since SYNC-7 and `api.DiskFloorIn` has declared it all
along. Nothing stored it. `machine_state.disk_floor_bytes` (added to the same
v54 step, which has shipped nowhere) is written from `guard.disk_floor.
floor_bytes` on the report - COALESCE, like `trash_bytes` beside it rather
than the latch columns, because a floor is a SETTING on that computer and not
an incident, so a light tick or an older build keeps the last number that
machine told us rather than sending this server back to guessing.
`health.machine_disk_floor(row)` is the one reader: `_disk_floor_hit` and
`disk_status`'s ABSOLUTE half take it when it is there, the why sentence is
FLAT when the number came from the machine (either it reported the park itself
or it reported the floor), and the "probably ... unless it was set otherwise on
that computer" wording is now only what a machine that has never said gets.
`alerts._check_disk_low` passes the same floor, so a 5 GB floor with 15 GB
free is not mailed about daily. The grid CHIP keeps the 20 GB constant on
purpose: a chip is a warning about space, and only the callers that speak FOR
the companion hand the machine's own floor in. Nothing is owed to
companion-core.

### CR-285AT (dash-db-6) - the most sensitive detector in this territory could not say what it was measuring - FIXED (tests/test_db_write_locks.py)

`test_no_alert_is_sent_with_the_write_lock_held` asserted
`len(opener.in_transaction) >= 2` and `not any(...)` over a list nothing in
the test controlled. It went red once during the hunt and would not reproduce
for the hunter (seven runs) or the verifier (seven more) - and it went red for
me, once, in a four-file run, and then passed on three repeats of the same
command. Diagnosed rather than tidied: the failure is the test, and there were
two causes. The fixture's own boot leaves whatever open subjects `_check_tree`
and `_check_dashboard_space` found on the machine running the suite, so the
recovery pass sends a POST per subject and the count is the state of a
developer's disk. And `env` leaves the REAL collector thread running, which
runs the `alerts` kind on its OWN connection through the same monkeypatched
opener - so a POST from that thread recorded `conn.in_transaction` for a
connection it has nothing to do with, i.e. a reading of the test's own writes
and not of the sender's. The collector is stopped, the ledger is emptied and
the two POSTs this test is about are asserted exactly. The invariant is
untouched.

### CR-285AU (dash-mounts-ui-2) - "[ STAGED, NOT CURRENT ]" said of a version this server holds from different bytes - FIXED (ui.py, templates/partials/admin_packages.html)

The verifier REFUTED the headline (a recalled record is dropped by
`_valid_records` before `_vendor_rows` can see it) and what survives is the
sha half: a version this server published from a DIFFERENT binary
(`release_feed.sha_conflict`, the `--allow-replace` case) was classified
`held`, which says the vendor's bytes are already here - the one thing they
are not - and offered [ MAKE CURRENT ] on bytes nobody compared, while
`build_feed_view` routes exactly that case into the `sha_conflicts` block
further down the same page. `_vendor_state` is its own function now with five
answers: `conflict` draws [ SAME VERSION, DIFFERENT BYTES ] with the held
sha's first twelve characters and offers no button, and `recalled` is belt and
braces for the one way a retracted row can still be seen here (a vendor
un-retracting a version; nothing clears `retracted_at`) - cheap, and a page
must not offer an act `package_store.make_current_refusal` will 409.

### CR-285AV (regression-3) - the retire branch decided whether the schema guard was ever consulted, and asked the version question alone - FIXED (deploy/select_code_root.py)

CR-270's retire branch returns `image_pythonpath()` before the
`already_failed >= MAX_BOOT_ATTEMPTS` block that calls `revert_refusal`, and
it rewrote `current.json` as a fresh five-key dict - dropping
`revert_refused_reason` / `revert_refused_from`, which `alerts.py` is looking
for. It is safe only under `check_tree` rule 5's invariant ("an OTA tree is
always newer than the image"), which nothing enforces at that point. The
verifier downgraded it because reaching the danger needs an image whose
VERSION is not lower but whose SCHEMA is, which the release process does not
produce; it is still a latent invariant dependency plus a test gap, and the
fix is cheap. `revert_refusal("")` - is the IMAGE safe for this database - is
asked before retiring, with its own three-way rule intact (cannot tell does
not refuse); a refusal keeps the tree, records itself where the page and the
alert can read it, and is not cleared by the zero-counter branch two lines
later (that rule reads a zero as "the thing the refusal was about is over",
and a schema the image cannot run is not over). `_retire` carries the two
`revert_refused_*` keys through the write. The test world has a real
`APP_ROOT` for the first time, which is why no test could reach this branch.

### CR-285AW (regression-5) - a brand new deployment reported its own healthy collector as STOPPED - FIXED (db.py, alerts.py)

CR-258B derived the staleness bound from the collector's OBSERVED rhythm, and
the observed rhythm needs a kind to have started twice. With none it returned
the 180 s floor, which is the original bug's premise: on a Syncthing-less
deployment the fastest kind that runs is `alerts` at 600 s, so between about
t+3 min and the second alerts cycle a brand new zero-touch or vendor dashboard
showed "the last collector cycle finished too long ago" on its home page and
reported itself stale on `/api/v1/health`, on a collector that was perfectly
healthy. The alert, the notice and the chip were all correctly silent, so the
visible half was exactly the half CR-258B was written for: the first
impression of the product was a red banner.

CR-256o's decline is REVISITED rather than worked around, as the verifier
asked. What it declined was a second implementation of the cadence
arithmetic; this moves the ONE implementation to the side that both readers
can import (`db.configured_stale_bound`, with `alerts._stale_after_seconds`
calling it - `settings.py` imports nothing of ours, so the cycle CR-256o was
about does not exist on this side). Which kinds this deployment runs is read
from the DATABASE rather than from a config most of `collector_stale_bound`'s
callers do not hold: a `poll_runs` row for any kind outside
`SYNCTHING_FREE_KINDS` is the evidence that the 60 s Syncthing-backed kinds
are running here, and their second start arrives long before 180 s, so
nothing about noticing a collector that really stopped is slowed down. No such
row - a Syncthing-less site, or the first minutes of any site - takes the
configured bound.

The central gate caught the one case that reading the database cannot see: a
site WITH Syncthing whose Syncthing-backed kinds have NEVER run, which is
exactly a collector that died at boot and must still be noticed at 180 s. So
`settings` is passed where a caller has it (`alerts.Ctx`, `/api/v1/health`)
and DECIDES; the database heuristic is the fallback for the page renderers,
which have none. `test_a_site_with_syncthing_keeps_the_three_minute_threshold`
is green again on the code, not on an edited assertion.

### CR-285AX (res-fleet-3, the answer word) - "trashed locally, destination not synced here" had no spelling the server understood - FIXED (db.py, api.py, templates/partials/project_detail.html)

`companion-media` is implementing section 4b of
docs/HAND_MOVES_ON_THE_SERVER.md: a move whose DESTINATION project this
machine does not sync is trashed locally instead of being `mkdir(parents=True)`
into a directory with no `.ccsync-project` marker, which is a permanent
invisible orphan reported as done. The answer keeps `ok=True` and the detail
sentence and adds `state: "not_synced_here"`. This is the dashboard half of
that vocabulary, and the first builder's OWED line said it would have to come
back here: it has.

`db.FILE_MOVE_TARGET_NOT_SYNCED_HERE` joins `retrying` and `blocked`.
It is TERMINAL and `ok` is true: `mark_file_move_applied`'s non-retrying arm
stamps `applied_at`, so the command is never offered again - nothing about
that machine is going to change, and re-sending it would ask the same
impossible question every thirty seconds. It is not `blocked` (a machine that
ran out of attempts at something it should have managed) and not a plain
success (nothing arrived anywhere), so the MOVES history gives it its own
words: "trashed on this computer: it does not sync the destination project".
"moved" would be untrue and "FAILED" would send an admin looking for a fault
that is not there.

**What an unknown state word did until today, which the coordinator asked to
have confirmed: it 422'd the WHOLE report.** `FileMoveResultIn.state` is a
`Literal` and `file_moves_applied` is NOT one of `ReportIn`'s tolerant
sections, so a companion sending a word its dashboard does not know loses its
lanes, its presence and its alarms, once every thirty seconds - the field's own
comment says so about `applying` and answers it with "THE DASHBOARD DEPLOYS
FIRST", which is a rule about people rather than a property of the code. So a
0.9.75 companion sending `not_synced_here` to a **0.7.49** dashboard is NOT
recorded as done: it is a 422 per report until this build is live, and that is
the reason this half is DASHBOARD FIRST and hard. Two things follow, and both
landed here.

A `field_validator(mode="before")` maps an unrecognised state to NO state,
keeping `ok` and `detail`, which is the pre-RES-1 meaning (answered, terminal,
say what the machine said). That fixes the NEXT word and cannot help a
dashboard older than this build; the test says so in its name.

And the reply now carries **`dashboard_version`** (one additive key on
`api_report`'s result, ignored by every companion in the field). The companion
had nothing to gate a new word on - the report reply has never said which
dashboard is answering - so "deploy the dashboard first" was the only
protection a fleet had against losing a machine's whole report. From here a
companion sends a state word only to a dashboard that has told it its version
is 0.7.50 or newer, and answers every older one with `ok` plus the sentence and
no state, which those builds record as done. That is the companion's half to
implement and it is now possible to implement correctly.

### Verification

Run from `dashboard/` with `dashboard\.venv\Scripts\python.exe -m pytest`. The
whole of `tests/test_bug_hunt_2026_09_18_dashboard_mediums.py` was also run
against a pristine HEAD tree (`git archive HEAD` into the scratchpad, source
files only): **29 of its 36 tests fail there and 36 pass here**. The seven that
pass on both are named below as the guards they are.

- `tests/test_cards_pool.py::test_an_episode_that_failed_to_build_can_be_opened_again` -> fails before CR-285A, passes now
- `tests/test_cards_pool.py::test_a_failed_episode_is_not_rebuilt_on_every_click` -> fails before CR-285A's floor, passes now
- `tests/test_cards_pool.py::test_the_cap_refusal_names_a_place_that_exists_and_an_act_that_works` -> fails before CR-285B, passes now
- `tests/test_cards_pool.py::test_the_kill_switch_leaves_the_dashboards_own_caches_alone` -> fails before CR-285C, passes now
- `tests/test_cards_pool.py::test_closing_an_episode_evicts_its_wsgi_gate_and_its_thread_pool` -> fails before CR-285D (AttributeError: no `evict`), passes now
- `tests/test_cards_pool.py::test_the_flat_data_dir_is_named_rather_than_silently_orphaned` -> fails before CR-285E, passes now
- `tests/test_cards_pool.py::test_the_failed_episode_detail_is_not_another_repos_exception_text` -> fails before CR-285AH, passes now
- `tests/test_cards_pool.py::test_an_editor_can_close_the_episode_they_are_in_and_an_idle_one` -> fails before CR-285P (no `may_close`), passes now
- `tests/test_cards_pool.py::test_a_non_admin_cannot_close_an_episode_somebody_else_is_in` -> rewritten from the admin-only test CR-285P replaces
- `tests/test_bug_hunt_2026_09_18_dashboard_mediums.py::test_moves_dropped_by_the_cap_become_a_problem_the_server_found` -> fails before CR-285F, passes now
- `...::test_a_folder_renamed_in_place_is_one_row_not_one_per_file` -> fails before CR-285G, passes now
- `...::test_a_renamed_proxy_folder_is_still_refused_as_a_folder_move` -> a GUARD on CR-285G (passes on both; the `Proxy` refusal must not widen)
- `...::test_a_secret_write_that_fails_leaves_the_previous_file_intact` -> fails before CR-285H, passes now
- `...::test_a_zero_byte_secret_file_is_a_lost_secret_not_a_saved_one` -> fails before CR-285H, passes now
- `...::test_a_long_collector_pass_is_not_reported_as_a_held_write_lock` -> fails before CR-285I, passes now
- `...::test_a_clean_collector_pass_writes_nothing_about_how_long_it_took` -> a GUARD on CR-285I's own regression (passes on both)
- `tests/test_alerts.py::test_every_notice_kind_any_writer_passes_to_db_notice_is_registered` -> fails before CR-285J (`db_busy`, `slow_write` unregistered), passes now
- `...::test_the_folded_amber_conditions_are_counted_on_the_closed_summary` -> fails before CR-285K, passes now
- `...::test_a_stall_older_than_a_day_is_not_a_current_blockage` -> fails before CR-285L (no `stall_is_current`), passes now
- `...::test_a_lane_that_has_synced_since_the_kill_is_not_stuck_in_it` -> fails before CR-285L, passes now
- `...::test_a_stall_with_no_stamp_keeps_the_old_behaviour` -> fails before CR-285L, passes now (it is also the guard on the "cannot tell" direction)
- `...::test_a_publish_that_fails_to_insert_does_not_replace_the_live_artefact` -> fails before CR-285M, passes now
- `...::test_publishing_a_version_this_server_already_holds_is_a_refusal` -> fails before CR-285M, passes now
- `...::test_the_companions_real_report_sections_are_all_declared` -> fails before CR-285N, passes now (the PRODUCER's real dicts, all three models)
- `...::test_a_mounted_sub_app_answers_a_busy_database_with_the_same_503` -> fails before CR-285O (500), passes now
- `...::test_a_push_of_a_build_this_machine_cannot_take_is_not_sent` -> fails before CR-285Q, passes now
- `...::test_a_build_withheld_from_a_machine_says_so_on_the_reply` -> fails before CR-285Q (no `withheld`), passes now
- `...::test_an_archive_this_server_cannot_list_is_a_problem_it_found` -> fails before CR-285R, passes now
- `...::test_the_restart_still_happens_when_the_state_file_cannot_be_written` -> fails before CR-285S (the OSError escapes), passes now
- `...::test_a_restart_is_signalled_even_when_the_note_about_it_cannot_land` -> fails before CR-285S, passes now
- `...::test_an_unreported_lane_carries_the_flag_the_template_now_reads` -> a GUARD on CR-285T's data half (the flag predates the fix)
- `...::test_the_grid_draws_an_unreported_lane_in_its_own_style` -> fails before CR-285T's template change, passes now
- `...::test_the_broll_mount_records_its_root_and_a_witness_inside_it` -> fails before CR-285U (no `root_of`), passes now
- `...::test_a_move_of_an_underscored_folder_does_not_claim_its_siblings` -> fails before CR-285V, passes now
- `...::test_the_bucket_option_is_not_offered_beside_a_real_computer` -> fails before CR-285W, passes now
- `...::test_oidc_refuses_a_claim_the_rest_of_the_dashboard_will_not_accept` -> fails before CR-285X, passes now
- `...::test_the_open_pwa_paths_are_open_to_reads_only` -> fails before CR-285Y (TypeError: one positional arg), passes now
- `...::test_an_unauthenticated_post_to_an_open_path_is_sent_to_login` -> fails before CR-285Y (the POST falls through), passes now
- `...::test_the_collector_prunes_expired_sessions` -> fails before CR-285Z, passes now (and asserts the sweep is OUTSIDE the write transaction)
- `...::test_the_feed_may_clear_a_dirty_chip_and_may_not_write_a_commit` -> fails before CR-285AA (the feed's `git_sha` lands), passes now
- `...::test_a_recall_with_a_capitalised_kind_still_recalls` -> fails before CR-285AB, passes now
- `...::test_reapplying_the_running_version_keeps_the_rollback_target` -> WEAK: it re-states `apply`'s expression rather than driving a whole bundle, so it passes on both. CR-285AC's behaviour is otherwise unpinned.
- `...::test_a_tree_that_could_not_say_its_schema_is_not_recorded_as_schema_zero` -> fails before CR-285AD (a source assertion, for the same reason: `apply` needs a signed bundle)
- `...::test_a_naive_timestamp_is_read_as_utc_rather_than_raising` -> fails before live-3's fix, passes now
- `...::test_a_session_row_nobody_can_parse_is_no_session` -> a GUARD (HEAD's ValueError arm already covers a garbage date; the TypeError arm is what changed)
- `...::test_a_locate_body_is_refused_by_declared_length` -> fails before CR-285AF, passes now
- `tests/test_hardening.py::test_the_package_route_is_not_buffered_by_the_gate` -> the existing pin on `_BODY_LIMITS`' exact membership, updated with the new entry (CR-285AF) and citing it
- `tests/test_db_write_locks.py` (11) -> the suite that caught CR-285I's and CR-285Z's first drafts; green
- Suites re-run green after the changes: `test_cards_mount.py`, `test_notices.py`, `test_hand_moves_detected.py`, `test_sweep_2026_09_04_dashboard.py`, `test_alerts.py`, `test_release_feed.py`, `test_dashboard_update.py`, `test_select_code_root.py`, `test_bug_hunt_2026_09_11b_dash_release_jobs.py`, `test_admin_assignments.py`, `test_health.py`, `test_mount_status.py`, `test_fleet_grid_declutter_2026_09_11.py`, `test_pwa.py`, `test_packages.py`, `test_locate.py`, `test_broll_mount.py`, `test_music_mount.py`, `test_ytdl_mount.py`, `test_report_endpoint.py`, `test_oidc.py`, `test_auth.py`, `test_secrets_boot.py`, `test_db_busy_2026_09_17.py`, `test_health_page.py`, `test_bug_hunt_2026_09_18_dashboard.py`
- `py_compile` on every touched `.py`, a Jinja parse of the three touched templates, and a YAML parse of `.github/workflows/ci.yml`


Second builder (run from `dashboard/`, `dashboard\.venv\Scripts\python.exe -m pytest`).
Every one of these is in `tests/test_bug_hunt_2026_09_18_dashboard_lows.py`
unless another file is named, and every one fails on the tree as the first
builder left it - the four that call a function that did not exist
(`pending_move_halves`, `standins_known`, `_vendor_state`, the `blind` /
`machine_id` keywords) fail with a TypeError or an AttributeError there, which
is the honest "before".

- `...::test_a_move_between_two_projects_is_paired_across_two_passes` -> fails before CR-285AL, passes now
- `...::test_a_file_that_comes_back_to_its_old_path_is_not_a_move` -> a REFUSAL guard on CR-285AL
- `...::test_an_ambiguous_half_is_never_kept` -> a REFUSAL guard on CR-285AL
- `...::test_a_half_nobody_pairs_ages_out_of_the_table` -> pins the `db.prune` retention
- `...::test_a_pass_that_could_not_read_its_evidence_is_not_a_check` -> fails before CR-285AL's honesty half
- `...::test_forgetting_a_computer_takes_its_outstanding_commands_with_it` -> fails before CR-285AM
- `...::test_a_rename_carries_the_outstanding_commands_onto_the_new_name` -> fails before CR-285AM
- `...::test_a_command_under_a_former_hostname_is_still_offered` -> fails before CR-285AM (and asserts the fan-out that must NOT happen)
- `...::test_the_file_move_alert_can_fire_at_all` -> fails before CR-285AM (the check has never fired)
- `...::test_a_stranded_move_names_the_fleet_not_a_computer_that_is_gone` -> fails before CR-285AM
- `...::test_a_stand_in_this_machine_placed_is_known_to_the_whole_fleet` -> fails before CR-285AN (the PRODUCER's section in, the reply key out)
- `...::test_a_stand_in_the_machine_no_longer_lists_stops_being_reported` -> fails before CR-285AN
- `...::test_a_forgotten_computers_stand_ins_are_forgotten_too` -> fails before CR-285AN
- `...::test_an_unreadable_broll_archive_is_mailed_not_only_drawn` -> fails before CR-285AO
- `...::test_the_new_alert_kind_carries_its_weekly_line` -> fails before CR-285AO
- `...::test_a_healed_stall_is_not_mailed_every_morning` -> fails before CR-285AP (measured: reverted the guard, the test goes red, restored)
- `...::test_a_stall_from_an_hour_ago_still_raises_the_alarm` -> the GUARD on CR-285AP
- `...::test_as_of_is_the_oldest_walk_that_answered` -> fails before CR-285AQ
- `...::test_the_skipped_exists_count_carries_its_scope` -> fails before CR-285AR
- `...::test_a_disk_verdict_this_server_guessed_says_it_is_a_guess` -> fails before CR-285AS
- `...::test_a_machine_with_a_raised_floor_is_judged_against_its_own_number` -> fails before CR-285AS (the column does not exist, and the verdict is this server's default)
- `...::test_a_machine_with_a_lowered_floor_is_not_accused_of_stopping` -> fails before CR-285AS
- `...::test_a_machine_that_has_never_said_keeps_the_default_and_the_guess` -> the GUARD on CR-285AS (an older build keeps the constant, and the sentence says it is a guess)
- `...::test_a_move_trashed_locally_is_a_terminal_answer` -> fails before CR-285AX (422 on the report today; the PRODUCER's real answer shape through the report route), passes now
- `...::test_the_moves_history_gives_it_its_own_words` -> fails before CR-285AX
- `...::test_a_state_word_this_build_does_not_know_never_422s_the_report` -> fails before CR-285AX (the Literal rejects it and the whole report goes with it)
- `...::test_the_report_reply_says_which_dashboard_answered` -> fails before CR-285AX's `dashboard_version` key, passes now
- `tests/test_bug_hunt_2026_09_11b_dash_collector_alerts.py` (28) -> two reds from CR-285AW in the central gate, one contract and one precondition: `test_a_site_with_syncthing_keeps_the_three_minute_threshold` was a real break and is fixed in the CODE (`settings` now reaches `collector_stale_bound` through `collector_health` / `fetch_collector_status`, so a site WITH Syncthing keeps the 180 s bound even before its Syncthing-backed kinds have ever run - the one state where a collector that died at boot must still be noticed), and `test_a_syncthing_less_site_whose_collector_is_turning_is_not_stopped` asserted the stored flag was True as its PRECONDITION, which is the residue regression-5 closes, so that line now asserts False with the reason beside it. The contract both tests are named for holds.
- `...::test_a_version_held_from_different_bytes_is_not_staged` -> fails before CR-285AU
- `...::test_a_fresh_syncthingless_deployment_is_not_reported_as_stopped` -> fails before CR-285AW (and pins that a Syncthing site keeps the tight bound)
- `...::test_a_tree_the_image_cannot_run_is_not_retired` -> fails before CR-285AV, passes now (the first test world with a real `APP_ROOT`, which is why this branch had never been reached)
- `...::test_an_image_that_has_caught_up_still_retires_the_tree` -> the GUARD on CR-285AV (CR-270 must keep working)
- `...::test_a_retire_keeps_an_earlier_refusal_where_the_alert_looks_for_it` -> fails before CR-285AV
- `tests/test_db_write_locks.py::test_no_alert_is_sent_with_the_write_lock_held` -> CR-285AT: rewritten, and green on three repeats of the four-file command that caught it red
- Suites re-run green after these changes: `test_hand_moves_detected.py`, `test_alerts.py`, `test_db.py`, `test_db_write_locks.py`, `test_report_endpoint.py`, `test_health.py`, `test_health_page.py`, `test_locate.py`, `test_notices.py`, `test_packages.py`, `test_release_feed.py`, `test_select_code_root.py`, `test_dashboard_update.py`, `test_db_busy_2026_09_17.py`, `test_file_moves.py`, `test_fleet_halt.py`, `test_fleet_scope.py`, `test_recovery.py`, `test_sweep_2026_09_04_says_what_it_knows.py`, `test_admin_assignments.py`, `test_fleet_grid_declutter_2026_09_11.py`, `test_hardening.py`, `test_sweep_2026_09_04_dashboard.py`, `test_bug_hunt_2026_09_11b_dash_release_jobs.py`, `test_bug_hunt_2026_09_11b_dash_mounts_ui.py`, `test_bug_hunt_2026_09_18_dashboard.py`, `test_bug_hunt_2026_09_18_dashboard_mediums.py`
- `py_compile` on every touched `.py` and a Jinja parse of the two touched templates

### Not fixed

Nothing in this group is left unfixed. The four lines the second builder
left here were closed by other groups the same evening, as the orchestrator
records: dash-release-jobs-3 by `webapps-tools` as CR-286AJ, regression-7 by
`webapps-tools` as CR-286AK, proxy-tiers-4's companion half by
`companion-media` as CR-284H (built to the contract below, unchanged), and
dash-collector-alerts-1's RECOVERABLE cap is narrowed by CR-285AL (the halves
of a capped cross-cycle move are kept and retried; only a within-pass surplus
is lost, and the notice names it), which is the residue this pass accepts.

### OWED TO ANOTHER GROUP

- webapps-tools: `music/web/tests/test_bug_hunt_2026_09_11_music.py:307-315` (`test_...force...`): the test `pytest.skip()`s when a production `apply_for_track(..., force=True)` caller appears, so a caller landing makes it skip silently for the rest of the repo's life. Make the caller case an explicit assertion about what the docstring must then say, or delete the test and keep the docstring fix (regression-7). No deploy order - a test only.
- webapps-tools: `tools/publish_feed.py` `published_assets` (~:746) and the skip in `github_upload` (~:818): add `.state` to the `--jq` and treat an asset as held only when `state == "uploaded"`, so an interrupted upload is re-pushed instead of skipped for ever (dash-release-jobs-3). `tools/tests/` pins the runner verb for verb, so the new `--jq` string needs those pins updated in the same change. Publisher-side only; no deploy order.
- companion-media: `companion/file_moves.py` `apply_move` and `companion/app.py` `_apply_file_moves`: the §4b branch for a destination project this machine does not sync - trash locally and answer "trashed locally, destination not synced here" - instead of `mkdir(parents=True)` into a directory with no `.ccsync-project` marker, which is a permanent invisible orphan reported as done (res-fleet-3). The dashboard side is deliberately NOT changed: `db.file_move_target_machines` computes targets from the SOURCE project on purpose (a machine that holds the file must be told the move happened), and the destination check belongs where the plan is known. The answer vocabulary HAS gained that state and the dashboard half landed with it (CR-285AX, `state: "not_synced_here"`). **DASHBOARD FIRST, and hard**: `file_moves_applied` is not a tolerant section, so that word reaching a fleet before 0.7.50 is live 422s every report from that machine, every thirty seconds. The companion must gate the word on the reply's new `dashboard_version` key (>= 0.7.50); below that, answer `ok` plus the sentence and no `state`, which every older dashboard records as done.
- companion-core (or whoever owns the tray): the companion may now read `upgrade_none_reason` on the report reply for a build it is being withheld (CR-285Q). Already written on the companion side per the coordinator; nothing further owed.
- companion-core: SYNC-1's stall record (`~/.ccsync/state/lane_stall.json`) still has no expiry and nothing clears it when the lane completes a pass, so it rides every report for the life of the install. The dashboard now ignores a stale one on both surfaces (CR-285L, CR-285AP) and needs nothing further; clearing it on the companion side is still the honest fix, and until it lands the evidence in the raw report is a week old. No deploy order.
- companion-media: the other half of proxy-tiers-4, to the contract below and unchanged: send `sync_guard.standins_placed.rels` (NFC archive rels, max 200) and READ `standins_known` off the report reply, treating an absent key as "demux as before" and never as "there are none". DASHBOARD FIRST; this side is built and inert until a companion sends it.

### proxy-tiers-4 contract (owed here by companion-media; the dashboard half is BUILT to this, CR-285AN, and the contract has NOT changed)

The ask: a stand-in fact that travels with the FLEET, so a wired rig can ask
one cheap question per clip instead of demuxing the archive. Sketched, not
built; it needs schema v54 and a companion half, and v54 is free.

1. **Report payload.** A new bounded section on the report's `sync_guard`
   block, NOT on `resolve_health` (it is about what this machine did to the
   archive, not about Resolve):
   `standins_placed: {rels: list[str] (max_length=200), checked_at: str}`,
   where each `rel` is the ARCHIVE-relative path of the ORIGINAL the stand-in
   stands in for, in NFC (`db.media_rel_key`), never an absolute path - the
   vault is a drive letter here and a container mount there. Declared in
   `api.py` as `StandinsPlacedIn(_BoundedSectionIn)` first, dashboard-first,
   per this file's standing rule.
2. **Schema v54.** `broll_standins (archive_rel TEXT NOT NULL, editor_username
   TEXT NOT NULL, machine TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen
   TEXT NOT NULL, PRIMARY KEY (archive_rel, editor_username, machine))`, keyed
   by the NFC archive rel. `db.record_standins_placed(conn, editor, machine,
   rels, now)` replaces that machine's set (the report is a full picture, like
   `editor_media`), and `db.prune` drops rows whose `last_seen` is older than
   `MACHINE_STATE_MAX_AGE_DAYS` and rows for a machine that has been forgotten
   (add the table to `_MACHINE_STATE_TABLES` - res-fleet-4's lesson).
3. **Asking.** On the report REPLY, not a new route: for the rels this machine
   listed in its own `media_tree`/`local_manifest` the reply carries
   `standins_known: {rels: list[str]}` - "these archive rels were placed as a
   stand-in by SOME machine in this fleet". Bounded to the same 200. A reply
   key rather than a fleet route because the wired rig already sends the list
   the answer is about, and a second route is a second credential path for a
   question that is not a secret.
4. **Compatibility.** Every part is additive: a companion that sends nothing
   contributes nothing and a companion that reads nothing is unaffected;
   `standins_known` absent means "this dashboard does not know", which the
   companion must treat as "demux as before", never as "no stand-ins".
   DASHBOARD FIRST.

### Deploy order

- **Schema v54 is TAKEN** (`nas_media_pending_moves`, `broll_standins`,
  `machine_state.skipped_exists_subpath`, `machine_state.disk_floor_bytes`):
  one step, four findings, gapless.
  Every new reader of those tables is defensive or best-effort, so a dashboard
  rolled back past it behaves exactly as it did the day before. The next pass
  takes v55.
- **CR-285AX is the one that is dangerous to get the wrong way round**: a
  companion answering `not_synced_here` to a dashboard below 0.7.50 fails
  the report model and loses that machine's whole report, not just the
  answer. Deploy this dashboard before the companion that sends it.
- **DASHBOARD FIRST, in every case.** Nothing here needs a companion release
  to be correct, and three things are the companion's other half waiting on
  this side: CR-285L and CR-285AP together stop the daily stall mails, the
  recovered messages and the red trays fleet-wide in one deploy with no
  companion change at all; CR-285N declares three fields
  0.9.74 already sends, so `ignored_report_sections` clears the moment this is
  live; CR-285Q's `upgrade_none_reason` is read by a companion half that is
  already written and inert until this lands.
- One thing to watch on the deploy, not a blocker: CR-285M turns a duplicate
  publish from a 500 into a 409 (different bytes) or a 200 with a note (same
  bytes). `tools/publish_latest.py` and `installer/build_editor_package.ps1`
  read the route's answer; neither should be surprised by a 409 it already gets
  from the route's own pre-check, but the 200-with-a-note path is new.
- The open `server_error` notices for `/api/v1/admin/feed/publish` on the live
  dashboard (id 31552) and for the naive session (id 31154) can be dismissed
  once 0.7.50 is live: both causes are fixed here.

### Owner decisions

- **CR-285E does not adopt the orphaned Timeline Cards state**, it names it in
  the log. The safer of the hunter's two options, and the verifier's
  preference: which episode `<data>/cards`'s flat `cards_pick.json` and
  `library_backups` belonged to is not recorded anywhere, so an automatic adopt
  is a guess that can write one episode's cut into another. The loss has
  already happened once on this dashboard (the pool went live 2026-09-14). If
  you want those backups, they are still on disk one directory up and the log
  line names both paths.
- **CR-285P lets a non-admin close an idle episode.** An episode nobody has
  been in for 15 minutes can now be closed by any signed-in user, which is
  what makes CR-285B's sentence true. It is not free (`drop()`'s docstring:
  the upstream threads stay), so a bored editor closing episodes is a slow
  thread leak. The alternative is leaving the cap unclearable without an admin.
- **CR-285P does NOT redact the occupants' names from the cap refusal**, which
  security-2 also asked for: the landing page's own table already lists who is
  in which episode to every signed-in user (deliberately, Alex 2026-09-14 -
  "an editor drives their OWN account's companions, so another person being
  live here is something to know"). Redacting one of the two would be theatre.
- **CR-285AA writes no `git_sha` from the feed at all**, which is stricter than
  the finding asked for. The `published_by` gate the hunter suggested would
  have stopped the repair working (the feed page's [ PUBLISH ] button stamps an
  admin's username), and the narrow version closes the hole without a
  provenance column. If a future feature really needs the vendor's commit
  string on a locally published row, it needs the field inside the signature
  first.
- **CR-285I gives the collector's slow pass its own notice kind rather than
  re-timing the write burst.** Measuring the real lock-hold means threading a
  clock through every runner's internal commits; the verifier called the
  re-wording the safer half to land first. `slow_write` still exists and
  `api_report` still writes it from a measured burst.
- **Schema v54 is UNUSED.** Nobody in the first builder's pass took it. Three
  deferred items wanted it (dash-collector-alerts-1's pending-halves table,
  dash-api-5's per-subpath count, proxy-tiers-4's `broll_standins`) and the
  second builder took it ONCE, for all three (CR-285AL / AN / AR).
- **A cross-cycle move is recorded as a FILE move, one row per file, never a
  folder one** (CR-285AL). A folder rename spread over two passes is therefore
  N rows and N `commands.file_moves` entries rather than one, which is the
  shape dash-collector-alerts-3 was about. The alternative is proving a folder
  rename from a partial picture of its project, which can tell a fleet to
  rename a directory on the strength of one file, so the safe direction was
  taken. If the row count ever bites, the answer is a later pass that
  re-derives folders from complete walks, never a looser proof here.
- **Two days is the shelf life of an unpaired half** (CR-285AL,
  `db.PENDING_MOVE_HALF_MAX_AGE_DAYS`): long enough for the rotating cursor to
  make several full rounds of a big fleet, short enough that a file which
  really was deleted, and whose bytes appear elsewhere a week later, is not
  paired with it.
- **A blind inventory pass no longer stamps `file_move_detected`**
  (CR-285AL). An operator with one permanently unreadable project directory
  will watch that check's time go stale on the WHAT THE SERVER CHECKS panel
  while every other check stays current. That is the truth, and the unreadable
  directory is its own finding beside it, but it is a visible change.
- **A forgotten computer's outstanding file moves are DELETED, not kept**
  (CR-285AM), so its per-machine line disappears from the project page's MOVES
  history with it. The alternative is a row nobody can ever answer raising a
  warn nobody can act on, which is what the finding was.
- **CR-285AS leaves the grid's DISK chip on the 20 GB constant** and gives the
  machine's own floor only to the callers that speak for the companion (the
  why sentence, the `disk_low` alert). A chip is a warning about space; a
  sentence that says a computer has stopped itself is a claim about that
  computer.
- **CR-285AT rewrote a test rather than product code.** The invariant it
  guards is unchanged; what changed is that its subjects are now known, so the
  next time it goes red somebody can tell what broke.
