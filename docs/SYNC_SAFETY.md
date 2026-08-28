# Sync safety: the lane B breaker, trash retention, and the halt

Added 2026-08-17 for `COMMERCIAL_READINESS.md` item 9 ("close the remaining
data-loss edges"), sync half. Companion side lives in
`companion/src/ccsync_companion/sync/lane_guard.py`; the dashboard side is the
`sync_guard` report section, the machine_state v16 columns, and
`/api/v1/fleet/halt`.

## Why any of this exists

Lane B is `rclone sync <NAS> <editor>` — the one verb in this system that
removes local files. It already carried two guards:

* every removal is a MOVE into `<local_root>/.ccsync-trash/<timestamp>/`
  (`--backup-dir`), so nothing lane B does is unrecoverable; and
* `--max-delete 100` / `--max-delete-size 20G`.

That pair bounds **one pass**. Nothing bounded the sequence. A wrong
`remote_root`, a NAS that lists empty while its pool is still importing, or a
project unshared behind the companion's back all present to `rclone sync` as
"the source no longer has these files", and the cap then walks the editor's
whole proxy set into the trash at 20 GB per pass, one pass at a time, forever
— with the fleet grid showing lane B idle and green throughout.

## 1. The circuit breaker

`lane_guard.LaneBBreaker`, persisted to
`~/.ccsync/lane_b_breaker.json` so a trip survives the tray restart an
editor will absolutely try first. It moved out of `~/.ccsync/state/` on
2026-08-28 (resilience sweep APP-3): `state/` is the directory a support
session is most likely to be told to delete, so the latch only a human may
clear was sitting where "close CCSync, delete state, start it again" cleared
it. A latch left over from an older build is moved into place once, on
start (`lane_guard.adopt_legacy_latch`). Three triggers:

| # | When | Fires |
|---|---|---|
| 1 | `remote_root` holds none of the marker dirs (`Projects/`); the NAS lists the scope EMPTY where it was not empty before; the listing shrinks past `lane_b_remote_shrink_fraction` (0.5) | **before** the pass runs — nothing is deleted |
| 2 | one pass moved more than `lane_b_max_deletes_per_pass` (50) files, or more than `lane_b_max_delete_fraction` (0.25) of the local proxy set under that scope | after the pass; rclone's cap bounded that one |
| 3 | cumulative deletions since the last resume exceed `lane_b_max_deletes_cumulative` (4× the per-pass cap) | catches a slow leak |

A **failed** listing is deliberately not a trip: rclone fails the run on its
own, and a flapping tailnet must not need an operator.

**The marker-directory half of trigger 1 needs its own probe, and until
2026-08-21 it never ran on a managed fleet** (sync-safety-5). The breaker
applies the marker rule only to the whole-tree scope, and in managed mode
every pass names a project subpath, so the one check that catches a
`remote_root` pointing at the wrong dataset was never reached. The sequencer
now asks lane B for `check_remote_root()` once per process, before the first
pass: one `rclone lsf` of `remote_root` itself, cached once it passes (a root
that holds `Projects/` does not stop holding it mid-run). A failed listing is
still not a trip, and the probe never blocks a pass - if it trips, the
breaker parks lane B the same way it always does. This is what makes the
"stale copy of the tree" case (a backup dataset, a snapshot clone mounted for
a restore drill) fail at the probe rather than after it has trashed every
proxy newer than the copy.

**The breaker file and the halt file are written atomically** (sync-safety-8):
`lane_guard._write_json` writes a `.tmp` beside the target and `os.replace`s
it into place, so a machine that loses power mid-write comes back to the old
state rather than to a truncated file. A safety latch that a torn write can
erase is not a latch, and both of these files exist precisely to survive the
restart an editor tries first.

When it trips:

* lane B parks in `paused` with `STOPPED (safety): <reason>` — never `error`,
  because the lane is not broken, it was stopped on purpose;
* **lanes A and C keep running.** Uploads continue, shared project files
  continue. This is the whole point of a breaker rather than a shutdown;
* one tray toast, one `ERROR` log line, a tray menu line, and a
  `sync_guard.lane_b_breaker` report field that raises a dashboard alarm.

Clearing it is an explicit operator act, and there are two ways to be that
operator (CR-45, 2026-08-20): the editor at tray → **Resume proxy
download…**, behind a confirm dialog that names the reason, or an admin at
Dashboard → FLEET → **[ RESUME ]** beside the red chip, which asks that one
machine to do the same thing on its next report. Either way it resets the
counters too — resuming without clearing them re-trips on the cumulative rule
next pass, which reads as "the button doesn't work".

The admin route exists because the tray-only rule meant a remote machine
stayed parked until its owner was next at the keyboard, and the admin who
checked the NAS is the person best placed to say it is healthy. It changes
who can reach the decision, not the decision: the companion does exactly what
the tray click does, only while its breaker is actually tripped, and the
request is dropped as soon as that machine reports itself clear so it can
never sit there and silently clear some later trip.

## 2. `.ccsync-trash` retention

**This reverses an earlier decision.** `_backup_dir`'s original comment said
"nothing ever prunes it — deleting the recovery copy would defeat its whole
purpose" (AUDIT_2 C-7). That was right while the trash was the only thing
between a mis-sync and permanent loss. With the breaker in front of it the
trash is a 14-day undo window, not an archive, and an unbounded one filled
editor SSDs.

`lane_guard.prune_trash`, run by the companion at most every
`trash_prune_interval_seconds` (6 h) at the end of a healthy lane B pass:

1. drop any timestamped batch older than `trash_max_age_days` (14);
2. if what remains still exceeds `trash_max_bytes` (50 GB), drop the OLDEST
   batches until it does not — **never the newest one**, however big;
3. **nothing at all is pruned while the breaker is tripped.** A trip is
   precisely the window in which somebody is about to need what is in there.

Every removal is logged with its size. The total is on the tray (above 1 GB)
and on the fleet grid (above 5 GB).

## 3. "Remove from this machine" is gated

`rmtree` on a project whose originals have not reached the NAS is the one
destructive action in this system with no undo anywhere. The only guard used
to be a sentence in the confirm dialog asking the editor to go and check the
dashboard's TRANSFERS page themselves.

`CompanionApp.removal_blockers()` now asks both outbound lanes:

* **lane A** — a `--dry-run` of the real lane A command for that project, so
  the answer uses the lane's own filters and age/size floors;
* **lane C** — Syncthing's `/rest/db/completion?folder=<slug>` (aggregate,
  no device) plus `needTotalItems`.

It **fails closed**: a probe that could not answer blocks the removal, which is
the opposite of the fail-open posture everywhere else in `app.py`. For every
other guard "I could not tell" costs a warning; for this one it costs footage.

The dialog names what is pending. An override is possible — an editor with a
dead NAS and a full disk has to be able to act — but it requires typing the
project's folder name, and it is logged locally AND reported to the dashboard
(`sync_guard.removal_overrides`, which the server logs at WARNING).

## 4. Halt: local and fleet-wide

**Pause is not stop.** "Pause syncing" stops the rclone rotation and the
express upload and deliberately leaves lane C running — it exists for "my
laptop is on a hotspot".

The halt (`lane_guard.HaltState`, `~/.ccsync/sync_halt.json`, moved out of
`state/` with the breaker above) stops lanes
A and B **and pauses every lane C folder through Syncthing's own REST API**, and
survives a restart. Two scopes:

* **local** — tray → Advanced → *Stop ALL syncing on this machine…*. The
  editor can clear it (top-level *► Start syncing again*).
* **fleet** — an admin sets it on the dashboard: Settings → Users →
  **FLEET SYNC HALT**, or `POST /api/v1/fleet/halt {"active": true, "reason": "..."}`
  (admin only; `GET` is readable by any signed-in user). It is persisted in
  the `meta` table and handed to every companion on its **next report reply**
  (`commands.halt`), so a machine that is off right now adopts it when it comes
  back. A companion refuses to clear a fleet halt locally.

The reason is mandatory when halting and is shown in every editor's tray.
A reply with **no** `commands.halt` key (an older dashboard) leaves a live halt
alone — absence of the field is absence of information, not a release.

**What "every lane C folder" covers** (sync-safety-2, sync-safety-4,
2026-08-21). **This is a property of the companion build, not of the
dashboard**: it needs the companion carrying the 2026-08-21 fix pass (the
build after 0.9.43, unshipped at the time of writing), and every machine in
the fleet still on an older one keeps the old behaviour - a fleet halt leaves
its asset libraries syncing. Check the version in the tray before you rely on
this.

* The halt pauses the **shared asset libraries** too - the b-roll archive, the
  music library and the LUT library - not just the editor's selected projects.
  It used to walk the project selection alone, so a halt pressed *because* a
  bad ingest or a mass rename in `Assets/B-roll Archive` was spreading left
  exactly that folder syncing on every machine in the fleet while every tray
  said nothing was. The list comes from `sequencer.halt_folder_ids()`.
* The shared-folder reconcile, which runs every pass and exists to put those
  libraries back online after a crash or a hand-pause, **will not release them
  while a halt is live**. Otherwise the halt undid itself within one rotation.
* Releasing a halt goes back through the same filter the leak-recovery sweep
  uses (`sequencer.release_for_halt()`), so a folder deliberately left paused
  because its `.stignore` never landed stays paused. The old release PATCHed
  `paused: false` onto everything it had paused, which could put an unfiltered
  `sendreceive` folder online offering every original and every `Proxy/` file.

## 5. Lane A: "skipped, exists"

Lane A is `copy --ignore-existing`: the first version of a name to reach the
NAS is the only one that ever will. Re-export a clip under the same name — what
every "fix the audio and render again" does — and lane A skips it forever, with
the lane showing green.

`scan_size_mismatches` runs on the orphan-scan cadence:
`rclone check --one-way --size-only --differ -` with the lane's own filter
file. Same name, different size = a file this machine will never upload. It is
**reported only** (tray line, `sync_guard.skipped_exists`, a `[ WON'T UPLOAD ]`
chip on the grid) — overwriting the NAS copy would be lane A growing a
delete/replace path, which is exactly what this system does not do. The fix is
a human one: rename the local file, or have an admin remove the NAS copy.

## 6. Syncthing supervision: keeping the sync engine alive

Added 2026-08-18 (SYNC-17). `companion/src/ccsync_companion/sync/syncthing_supervisor.py`,
state at `~/.ccsync/state/syncthing_supervisor.json`.

**What happened.** An editor's Windows session ended at 00:53 (rclone exited
`0x40010004 DBG_TERMINATE_PROCESS`, Syncthing logged "Syncthing is being
stopped / Exiting"). The companion came back at 18:24 by itself. Syncthing did
not, and stayed dead for eighteen hours, because the only thing that starts it
is an HKCU `Run` entry and **the Run key fires at logon and never again**. For
those eighteen hours the companion logged `repath: local syncthing unreachable`
at DEBUG, reported lane C as **idle, green, 0 queued**, and 12 GB sat unsynced.
Nothing else on an editor machine supervises Syncthing.

**The rules.** Driven from lane C's own poll (every 15 s), so there is no
thread of its own:

| | |
|---|---|
| Grace | the API must have been unreachable for **30 s** before anything starts. A Syncthing restarting mid-config-commit is back inside that. |
| Launcher | Windows: `wscript.exe //B //Nologo %LOCALAPPDATA%\ccsync\bin\CCSyncSyncthing.vbs` -- the SAME shim the Run key executes, so a supervised start and a logon start are the same command line (including the `--home`, which lives in the `.cmd` beside it). macOS: `launchctl kickstart -k gui/<uid>/com.ccsync.syncthing`. |
| Detachment | Windows spawns with `DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP`, `close_fds`, all handles to `DEVNULL`. A Syncthing started as an ordinary child of the tray dies with the tray, and with its self-upgrade. |
| Confirmation | after launching, the API is polled for up to 20 s. A launch that never answers is a **failed attempt**, not a success. |
| Backoff | 30 s, 1 m, 2 m, 4 m, 8 m, capped at **10 m**, measured from when the last attempt finished. A machine where Syncthing genuinely cannot start costs about six log lines an hour. |
| Three strikes | `INFO` per attempt; at the third failure a `WARNING` naming the last stderr line, and one tray balloon: *"Sync engine will not start: &lt;why&gt;"*. |
| Recovery | when the API answers again: one balloon, *"Sync engine was not running: restarted it"*, once per incident. |
| Persistence | `since`, `attempts`, `last_error`, `last_attempt` are written to `~/.ccsync/state/syncthing_supervisor.json`. The companion self-upgrades; a three-strike counter that resets on restart would never reach three. |

**It respects the latches.** Nothing is restarted while `sync_halt.json` is
active, while syncing is paused from the tray, or on a machine with
`sync_enabled = false` (the base rig). The refusal is logged with its reason,
once per edge -- resurrecting the engine somebody deliberately stopped is the
one thing a supervisor must not do.

**Lane C can no longer be green while the engine is down.** An unreachable
API is `state: "error"` on lane C, whatever the supervisor is doing, carrying
one of three sentences that the tray line and the dashboard chip repeat
verbatim:

* `the sync engine (Syncthing) is not running on this machine -- restarting it`
* `the sync engine (Syncthing) could not be started: <why>` (after three failures)
* `the sync engine (Syncthing) is not running on this machine, and it is not being restarted: <why>` (halted, paused, or supervision switched off)

A `401`/`403` from the API is **not** an outage: the process is up and holding
a different home's key, and restarting it would be the wrong fix applied
forever (see `default_api_key_paths`).

An open incident also rides the report as `sync_guard.syncthing_supervisor`
(`down_since`, `attempts`, `last_error`, `supervising`), and the section is
**absent while the engine is up** -- the same "empty means healthy" contract
the ingest sections use. **The dashboard does not read that section yet**
(`SyncGuardIn` does not declare the key, so `extra="ignore"` drops it); what
turns the grid chip red today is lane C's own `state`/`last_error`. Wiring the
section up is a dashboard schema change, not another companion release.

**The upgrade path.** `installer/windows_upgrade.ps1` never replaces
`syncthing.exe`, so nothing there stops it -- but an upgrade is one of the few
moments a machine is being looked at, so step 5b starts the engine through the
same shim when no `syncthing` process is running. That is the belt for a
machine whose companion has not been upgraded yet; the supervisor is the
braces.

**Kill switch.** `supervise_syncthing = false` in `~/.ccsync/config.toml`
(default `true`; a `[sync]` table with the same key is honoured too). With it
off nothing is ever started, and lane C still reports the error.

## 7. The one deletion surface with no latch: a human on the NAS

Everything above guards the *fleet* against the NAS. Nothing guards the NAS
against a person standing in front of it, and that asymmetry is deliberate: the
NAS copy is authoritative, so an admin deleting a Proxy folder or a shoot there
is, as far as every mechanism in this document is concerned, a legitimate
instruction. What happens next (sync-safety-6, 2026-08-21):

* **Lane B mirrors it down.** Up to 50 proxies per pass per editor go into that
  editor's `.ccsync-trash`, which is pruned at **14 days**, before the breaker
  trips on the 51st.
* **Lane C keeps a version, for a while.** Syncthing's staggered versioning on
  the NAS keeps deleted project metadata under `.stversions/`. The retention
  numbers do not currently agree: the NAS-side folders are provisioned with
  `maxAge` **365 days** (`server/setup_syncthing_folder.py`,
  `dashboard/.../provision.py`) while an editor's own folders are configured
  with **30** (`companion/.../syncthing_admin.py`). That was left alone
  deliberately (`KNOWN_BUGS.md` R5) and is worth reconciling to one number.
* **Video originals have no version at all.** They travel on the rclone lanes,
  not lane C, and the NAS side has no `--backup-dir`.

So the actual latch for a NAS-side deletion is a **NAS snapshot**, and that
lives outside this document: `server/setup_snapshots.py --apply` and
`docs/BACKUP_RESTORE.md`. Two things to check before relying on it:

1. **Has it been run on this box?** `KNOWN_BUGS.md` CR-10 is explicit that
   until it is, "this entry is code, not protection". `python
   server/setup_snapshots.py --list --apply` is the check; it must name a dataset with
   a slash in it for **both** targets (see BACKUP_RESTORE §1 -- an `apps` root
   that is a folder in the pool root schedules nothing).
2. **Nothing in the product says when it is missing.** The dashboard holds the
   NAS credential and renders every other safety chip, but there is no banner
   for "this NAS has no snapshot schedule". Until there is, it is a runbook
   item, not a system property.

Recovery order for "an admin deleted footage on the NAS", best first:

1. the NAS snapshot (BACKUP_RESTORE §4a/§4b);
2. `.stversions/` inside the folder on the NAS, for lane C files;
3. the editors' `.ccsync-trash/<timestamp>/`, within 14 days, for proxies;
4. whichever editor still has the originals locally -- which is not a backup,
   it is a replica that has not caught up yet.

## 8. Borrowed folders (shared between projects)

Since 2026-08-24 a project can declare that it borrows a folder from another
project (`SHARED_FOLDERS_PLAN.md`; the declaration is `includes` in the
borrower's `.ccsync-project`). The safety shape, lane by lane:

- **Lanes A/B** run the borrowed dir as an extra, deeper subpath inside the
  borrowing project's turn. Same filters, same `.ccsync-trash` layout, and
  the breaker is **scoped to the borrowed subpath**, so a trip there parks
  only that subtree's proxy download, not the borrower's own.
- **Lane C** shares the LENDER's whole Syncthing folder with the borrowing
  machine, restricted by a device-local `.stignore`
  (`syncthing_admin.restricted_ignore_lines`): the standard project ignores,
  then `!/<sub>` + `!/<sub>/**` per borrowed dir, then `**`. The manager
  (`sync/borrowed_folders.py`) never unpauses the folder until that
  restricted list is CONFIRMED — the plain project list on a lender folder
  here would pull the lender's entire non-video tree to a machine that never
  ticked it. Verified against Syncthing v2.1.2 (the fleet installs v2.1.3):
  no ancestor `!` lines — a pattern matching a directory matches everything
  within it, so `!/Interviewees` would leak every sibling.
- **A halt pauses borrowed lender folders too** (`halt_folder_ids` includes
  them), and the reconcile refuses to release them while halted, exactly as
  it does for the asset libraries.
- **Ticking a lender you were borrowing from** hands the folder to the
  sequencer: it detects the leftover restriction (`is_restricted`) and keeps
  the folder paused until the full ignore list is rewritten.
- **Removing a project from a machine**: removing the borrower rmtree's only
  the borrower's own dir (the partial lender dir stays; its Syncthing config
  is dropped by the manager once no borrower needs it, files untouched).
  Removing a lender that a selected borrower still shares from is blocked
  with a named reason; the removal gate also dry-runs each borrowed subpath
  so un-uploaded footage in a borrowed dir blocks like any other.
- **Nothing here deletes on the NAS**, same as everywhere else.

## Config knobs

All documented commented-out in `config.example.toml` (the shipped numbers are
the measured-safe defaults; pinning them in every first-run file is how a later
re-tune reaches nobody):

```toml
# lane_b_max_deletes_per_pass = 50
# lane_b_max_delete_fraction = 0.25
# lane_b_remote_shrink_fraction = 0.5
# trash_max_age_days = 14
# trash_max_bytes = 53687091200
# trash_prune_interval_seconds = 21600
# supervise_syncthing = true
```

Undocumented but read the same way, for the rare tune:
`lane_b_max_deletes_cumulative`, `lane_b_min_local_sample`,
`lane_b_min_remote_sample`, `lane_b_remote_marker_dirs`.

## Operator runbook

**An editor's tray says PROXY DOWNLOAD STOPPED / the grid shows the alarm.**

1. Read the reason on the fleet grid chip or the machine's `companion.log`
   (`lane B CIRCUIT BREAKER TRIPPED: …`).
2. If it names `remote_root`: that machine's `~/.ccsync/config.toml` is
   pointing somewhere that is not the tree. Fix it and restart the companion.
3. If it names an empty/shrunken NAS listing: check the NAS. Is the pool
   imported? Is the share mounted? Is the project still shared to that editor?
4. If it names a pass that trashed too much: look in that machine's
   `<local_root>/.ccsync-trash/<timestamp>/` — everything is there.
5. Once the server is right, clear it: Dashboard → FLEET → **[ RESUME ]**
   on that machine, or tell the editor to use tray → **Resume proxy
   download…**. Someone still has to look — that is the point of the latch —
   but since CR-45 the someone no longer has to be sitting at the machine.
   The dashboard button needs companion 0.9.43+ on the far end; older builds
   ignore the command, so those still need the tray click.

A trip that names a pass which trashed a lot of files is worth one check
before anything else: **was a folder MOVED on the NAS?** Since CR-44 the
breaker asks that question itself (it re-lists the scope and matches trashed
files on basename + exact size before tripping), so a move should no longer
reach you as an alarm — but a move to a *different project*, outside the
scope being synced, still looks like a deletion and still trips.

**Halting the fleet.** Dashboard → USERS → FLEET SYNC HALT, with a reason.
Every companion stops within one report interval and shows the reason. Release
with the same panel; editors cannot release it themselves.
