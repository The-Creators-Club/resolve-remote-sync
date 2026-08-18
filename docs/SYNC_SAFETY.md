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

Clearing it is an explicit operator act: tray → **Resume proxy download…**,
behind a confirm dialog that names the reason. That resets the counters too —
resuming without clearing them re-trips on the cumulative rule next pass, which
reads as "the button doesn't work".

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
5. Once the server is right, tell the editor to use tray →
   **Resume proxy download…**. There is no remote resume: someone has to look.

**Halting the fleet.** Dashboard → USERS → FLEET SYNC HALT, with a reason.
Every companion stops within one report interval and shows the reason. Release
with the same panel; editors cannot release it themselves.
