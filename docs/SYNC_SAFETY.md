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
`~/.ccsync/state/lane_b_breaker.json` so a trip survives the tray restart an
editor will absolutely try first. Three triggers:

| # | When | Fires |
|---|---|---|
| 1 | `remote_root` holds none of the marker dirs (`Projects/`); the NAS lists the scope EMPTY where it was not empty before; the listing shrinks past `lane_b_remote_shrink_fraction` (0.5) | **before** the pass runs — nothing is deleted |
| 2 | one pass moved more than `lane_b_max_deletes_per_pass` (50) files, or more than `lane_b_max_delete_fraction` (0.25) of the local proxy set under that scope | after the pass; rclone's cap bounded that one |
| 3 | cumulative deletions since the last resume exceed `lane_b_max_deletes_cumulative` (4× the per-pass cap) | catches a slow leak |

A **failed** listing is deliberately not a trip: rclone fails the run on its
own, and a flapping tailnet must not need an operator.

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

The halt (`lane_guard.HaltState`, `~/.ccsync/state/sync_halt.json`) stops lanes
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
