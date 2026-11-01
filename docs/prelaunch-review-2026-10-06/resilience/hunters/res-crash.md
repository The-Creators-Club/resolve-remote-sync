# Pre-launch resilience review - lens `res-crash` (crash and power loss mid-operation)

Date: 2026-10-06. Tree: HEAD 08b40eb plus the uncommitted working tree, read as it stands.

## What was covered

- Every write-then-rename in `companion/src/ccsync_companion` (about 60 sites), checked for
  fsync, tmp-name uniqueness, and above all what the READER does with a torn, empty or NUL-filled
  file: fail safe, fail open, or overwrite the evidence.
- Self-upgrade swap (`upgrade.py` download, two renames, rollback, crash-loop revert),
  `supervisor.restore_interrupted_upgrade`, and the autostart entries the installers write
  (`windows_bootstrap.ps1` Run-key shim and scheduled task, `macos_bootstrap.sh` LaunchAgent).
- `config.py` write/load/backup (probed: see res-crash-1).
- FIX ALL copy (`fixer.fix_clip`, `copy_with_progress`, the reservation and stale-tmp sweeps).
- File moves on both sides (`companion/file_moves.py`, `dashboard/api.py move_project_files`,
  `reconcile_file_moves`).
- Resolve edit journal (`resolve_journal.py`) and `resolve_bridge.replace_clip` ordering;
  `resolve_prefs.py` two-file write.
- Lane A/B partial handling (`.partial`, `--ignore-existing`, size-only checks), media jobs
  `.partial` publish, b-roll ingest mirror.
- Dashboard: `db.migrate` transactionality, WAL/synchronous settings, boot lifespan,
  `dashboard_update` stage/verify/swap/backup/restore, `package_store` publish ordering,
  `.part` sweep, `publish_db.py` (read the design, not re-traced).

Not covered in depth: Syncthing's own crash behaviour, the Timeline Cards engine's state files,
the ytdl web service's job DB, the b-roll/music indexers' own SQLite writers, and macOS-specific
APFS behaviour beyond what applies equally to NTFS.

Already fixed and therefore NOT re-reported: APP-4 (truncated/invalid config.toml falls back to
the backup), comp-app-5 (unreadable machine.json no longer mints a new id), CR-249f (a stranded
`.ccsync-move-` file no longer uploads), CR-251i (supervisor puts `.old` back when it is awake to
see the hole), DASH-1 (dashboard move row before the rename), the migration replay fix, the
package "bytes land last" ordering (dash-api-6), lane A orphan `.partial` reporting.

---

### res-crash-1 - A zero-byte config.toml silently loads ALL DEFAULTS and overwrites the good backup with an empty one

- Severity: high
- Confidence: CONFIRMED (probed)
- Where: `companion/src/ccsync_companion/config.py:1803-1860` (`load_config`), `:1756-1785` (`_refresh_backup`)
- What: APP-4's protection only fires on `tomllib.TOMLDecodeError`. An EMPTY file is valid TOML
  (`tomllib.loads("") == {}`), so `load_config` takes the success branch: no `_config_load_error`,
  `_config_from_backup` False, every key a default (blank `dashboard_url`, `local_root`,
  `dashboard_token`), and then `_refresh_backup(path, "")` replaces `config.toml.bak` with the empty
  text because the content "changed". The one copy that could have rescued the machine is
  destroyed on the same call that needed it.
- Scenario: probe in the scratchpad against the repo code: good file loaded (backup written),
  then the file truncated to 0 bytes. Result: `url: ''`, `err: None`, `from_bak: False`,
  `bak now: ''`. A NUL-filled file, by contrast, correctly loads the backup. Zero-length files are
  what a disk-full `write_text`/PowerShell `Set-Content` (installer and upgrade scripts write this
  file), an interrupted hand edit, some sync/backup tools and some power losses leave behind. The
  machine stops reporting (no dashboard URL, no token), drops off the fleet grid, and the only
  recovery is a reinstall or someone who still has the token - at a customer site we cannot reach.
- Recommendation: treat an empty or whitespace-only config.toml as a load failure (same branch as
  `TOMLDecodeError`: load the backup, set `_config_load_error`). Never refresh the backup from a
  parse that yielded no keys, or more generally never let `_refresh_backup` replace a backup that
  has a `dashboard_url`/`local_root` with one that has neither. Add a test for the 0-byte case
  beside APP-4's truncated-file test.
- Known: extends APP-4 (fixed for invalid TOML only); the 0-byte case is new.

### res-crash-2 - A power cut during a self-upgrade can leave a machine with no runnable companion, and nothing restarts it

- Severity: medium
- Confidence: CONFIRMED (code path); the corrupted-exe half is PLAUSIBLE (depends on the OS write-back window)
- Where: `companion/src/ccsync_companion/upgrade.py:1810-1830` (download, no fsync), `:1920-1960` (two renames);
  `supervisor.py:346-388, 700-708` (`restore_interrupted_upgrade`, only when the supervisor is alive and a
  marker exists); `installer/windows_bootstrap.ps1:645-680` (Run-key `.cmd` shim runs the exe directly);
  `installer/macos_bootstrap.sh:2580-2597` (LaunchAgent runs `$COMPANION_PATH` directly)
- What: two holes CR-251i does not close.
  1. Power loss (or BSOD) between `os.replace(exe, exe.old)` and `os.replace(new, exe)`: the
     supervisor dies with the machine, so `restore_interrupted_upgrade` never runs. At the next
     logon the scheduled task / Run key / LaunchAgent points at a name that does not exist, the
     companion (and with it the supervisor) never starts, and the machine syncs nothing.
  2. The verified download is never `fsync`ed before it is renamed over the exe and launched. A
     power loss in the seconds after the swap can leave `ccsync-companion.exe` at full size with
     unwritten (zero) regions. It then exists, so the supervisor's "fill a hole, never overwrite"
     rule refuses to restore `.old`, and the APP-5 crash-loop revert lives inside the exe that
     cannot start.
- Scenario: an office with an unreliable supply, an editor laptop whose battery dies while the
  tray is applying an unattended `auto_update` push. Next morning nothing launches, there is no
  tray icon to say why, and the dashboard shows the machine as silent. The fix is a human renaming
  `ccsync-companion.exe.old` - on a customer machine we cannot reach.
- Recommendation: `fh.flush(); os.fsync(fh.fileno())` on the download before the sha check returns,
  and fsync the directory where the platform allows. Put the recovery OUTSIDE the binary: make the
  Run-key `.cmd` shim (and a tiny wrapper for the scheduled task and LaunchAgent) do "if the exe is
  missing or fails a size/sha check against `~/.ccsync/version_state` and `.old` exists, rename
  `.old` back, then launch". Persist the expected sha256 of the installed exe before the swap so
  the shim can tell a torn exe from a good one.
- Known: CR-251i (FIXED, covers only the case where the supervisor survives); this residue is open.

### res-crash-3 - Companion safety state is not fsynced, and a torn file reads as "no state": latches fail OPEN and the next write destroys the evidence

- Severity: medium
- Confidence: PLAUSIBLE (the missing fsync and the fail-open reads are CONFIRMED by reading; whether a given power loss leaves zeros depends on OS write-back)
- Where: `companion/src/ccsync_companion/sync/lane_guard.py:171-215` (`_read_json` -> `{}`, `_write_json` no fsync:
  `lane_b_breaker.json`, `sync_halt.json`, `remote_counts`); `file_moves.py:1042-1088` (ledger `_load`
  returns empty on ValueError, `_save` rewrites without fsync); `resolve_journal.py:351-388` (`_read` -> `{}`,
  read-modify-write, no fsync); `upgrade.py:713-760` (`read_floor` -> "" on corrupt); `sync/rclone_lane.py:359-367`;
  `selection.py:388`. Only `fixer._write_json_atomic`, `identity`, `eula`, `site` and the dashboard's
  `secrets_boot` fsync.
- What: tmp + `os.replace` without `fsync` guarantees no reader sees a HALF-written file while the
  machine is up; it does not survive power loss. On NTFS a renamed file whose data had not been
  flushed commonly comes back at full length reading as NULs (or empty), and APFS gives the same
  shape. Every reader above maps that to "absent": the lane B breaker that an admin or editor
  must clear by hand is released; the `remote_counts` memory the empty/shrink probes compare against is
  gone, so those probes cannot fire on the next pass (the module's own docstring says so); the
  file-move ledger loses its intent rows, so the res-companion-1 resume (`apply_move`) answers
  "nothing at the old path" and the clip stays Media Offline; the Resolve undo journal for the open
  burst is emptied, and the next `record()` writes a journal with only the new entry, so the earlier
  edits of that burst can no longer be undone from the journal.
- Scenario: the breaker trips because the NAS listing looks empty during a building power event;
  the editor's machine loses power seconds later. On restart `lane_b_breaker.json` is NULs, the
  latch is off, `remote_counts` is gone, and the first lane B pass against a still-wrong NAS has
  no shrink baseline. Only the `--max-delete` caps and `.ccsync-trash` stand between that pass and
  the editor's proxy set. The tray and the grid say nothing, because "no file" is the normal
  state.
- Recommendation: one shared `atomic_write_json(path, payload)` helper in the companion that
  does write, flush, `os.fsync(file)`, `os.replace`, and on POSIX fsyncs the directory. Use it for
  every latch, ledger and journal. Make the readers tell apart "absent" and "present but
  unreadable": an unreadable latch file keeps the latch TRIPPED (fail closed) and says so; an
  unreadable ledger or journal is renamed aside (`.corrupt-<ts>`) before anything rewrites it, so
  the evidence survives for support.
- Known: comp-sync-1 / sync-safety-8 (atomic write, persist-failure reporting) are fixed; the
  power-loss / fail-open half is new.

### res-crash-4 - Footage and proxies written without fsync can survive a power loss at full size with zeroed content, and size-only comparisons then make the damage permanent and fleet-wide

- Severity: medium
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/fixer.py:566-686` (`copy_with_progress`: no fsync, then `shutil.copystat`
  copies the SOURCE mtime), `fixer.py:1438-1442` (`os.replace(tmp_path, dest_path)` then Resolve relink);
  `ytdl_executor.py:1787-1822`, `jobs_media.py:401-425`, `proxy_gen.py:1794`, `broll_ingest.py:2611`
  (`.partial` -> final, no fsync); lane A is `copy --ignore-existing` (`sync/rclone_lane.py:2016-2055`) and its
  only after-the-fact audit is `--size-only` (`:1877-1896`); lane B is `rclone sync` on size + modtime
  (`:2312-2345`)
- What: every media writer here relies on "rename only a complete file", which protects against a
  killed process but not against power loss: the rename (journaled metadata) can reach the disk
  before the data. The result is a file at its FINAL name, at the right size, with a zeroed tail or
  holes. Then nothing ever repairs it. A FIX ALL copy carries the source's old mtime
  (`copystat`), so lane A's `--min-age` does not hold it back after the reboot; lane A uploads it
  once, and `--ignore-existing` means the good bytes can never replace it; lane C fans it out. The
  size-mismatch audit cannot see it because the size matches. A proxy lane B downloaded has the
  NAS's size and modtime, so lane B never fetches it again. Resolve has already been relinked to
  the damaged copy.
- Scenario: an editor runs FIX ALL on a 40 GB card dump onto an internal drive with write caching
  on; the copy finishes, Resolve is relinked, and the power drops before the cache is written back.
  After the reboot the clip plays with corrupted frames, the NAS receives the same bytes within
  minutes, and every editor syncing the project gets them. The original on the card is fine, but
  nobody knows the NAS copy is bad.
- Recommendation: `os.fsync` the destination before every `.partial`/tmp -> final rename of media
  written by this codebase (fixer, ytdl, media jobs, proxy_gen, ingest). On Windows that is a
  FlushFileBuffers through `os.fsync`; the cost is seconds per multi-GB file, which a FIX ALL can
  afford. For lane A, consider `--checksum` or a sampled-hash check on first upload of a file this
  machine wrote itself (the fixer already has `_same_bytes_sampled`). Optionally have the
  stale-tmp/startup sweep verify the last N files the fixer landed (sampled compare against the
  source) when the previous run ended without a clean shutdown.
- Known: new. (CR-281 / the Ruskin short-proxy incident is a different cause: short files, not
  zeroed ones.)

### res-crash-5 - A damaged dashboard.db has no integrity check, no automatic recovery and no message outside the container log

- Severity: medium
- Confidence: CONFIRMED (absence of any check or recovery path); the corruption itself is PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/app.py:736-738` (lifespan: `db.connect` + `db.migrate`, unguarded);
  `db.py:716-726` (WAL, `synchronous=NORMAL`); `dashboard_update.py:997-1040, 1263-1288` (backups exist only
  before a code update, and restore is a manual rollback flag); `notices.py:270-273` (runtime DB faults are
  written as notices INTO the same database). `grep -r "quick_check\|integrity_check"` finds no caller in
  the dashboard, b-roll web, music web or ytdl web.
- What: if the database header, schema or `user_version` pages are damaged, `migrate` raises
  inside the lifespan, uvicorn exits, the container restarts, and it loops. CR-259a's code rollback
  cannot help (every tree reads the same file). There is no home page, so PROBLEMS THE SERVER FOUND
  cannot render, and alert delivery runs inside the same process. If the damage is in a later page,
  the dashboard boots and individual routes fail with "database disk image is malformed". The
  notice that would say so is a write into the damaged file. Recovery means ZFS snapshots (CR-10,
  operator work still owed on the owner's own NAS), or a `/data/backups/<ts>-before-<version>`
  that may be weeks old, restored by hand over SSH.
- Scenario: a customer's NAS has a pool error, unclean shutdown or full dataset during a write. The
  dashboard - "what tells everyone whether their footage is syncing" - is down, every companion's
  reports fail, and the customer's only signal is a browser error. Nobody at the vendor is
  told.
- Recommendation: at boot, before `migrate`, run `PRAGMA quick_check` (bounded; fast on this size
  of DB). On failure, do not crash-loop. Quarantine the file (`dashboard.db.corrupt-<ts>` with its
  -wal/-shm), try `.recover`/the newest `/data/backups` copy, and serve a minimal DEGRADED page that
  names what happened and what was restored. Add a daily `backup_database` into `/data/backups`
  (pruned like the update backups), so the newest backup is at most a day old rather than "the last
  update". Have the existing alert sink deliver a "database damaged" alert from the degraded mode.
- Known: CR-10 (snapshots, operator half open); the in-product detection and recovery is new.

### res-crash-6 - A case-only rename interrupted between its two renames strands the editor's file under `.ccsync-move-<pid>-<name>`, and the redelivered command then reports success

- Severity: medium
- Confidence: CONFIRMED (by reading)
- Where: `companion/src/ccsync_companion/file_moves.py:340-370` (`_rename_case_only`), `:686-724` (`apply_move`:
  `src` missing and `dest` missing -> "nothing at the old path on this computer", ok, no paths);
  no sweep anywhere recovers `.ccsync-move-*` (only the lane A exclusion in `sync/rclone_lane.py:115-123, 2133`).
- What: the case-only rename goes `src -> .ccsync-move-<pid>-<name> -> dest`. If the process dies
  between the two (power loss, CR-93-style abort, a kill), or if the second rename AND the restore
  both fail (Resolve holding a handle, the case CR-249f describes), then on a case-insensitive disk
  neither `src` nor `dest` exists. The intent row says `applying`, but the resume arm also requires
  `dest.exists()`, so the redelivered command answers ok/"nothing at the old path". The dashboard
  records this computer as having followed, no relink is offered, and the clip stays Media Offline.
  The footage sits under a dot-name that lane A (since CR-249f) and the fixer's dot-filtering walk
  both ignore, so nothing ever points at it again.
- Scenario: an admin fixes the spelling of `A001_Interview.braw` on the server; an editor's
  companion is mid-rename when the laptop hibernates on low battery (or Resolve holds the file).
  The file is still on the editor's disk but invisible, and the MOVES history says done.
- Recommendation: in `apply_move`, before answering "nothing at the old path", look for
  `.ccsync-move-*-<src.name>` beside `src` (any pid, case-folded name match) and finish the rename
  to `dest` (or put it back to `src` if `dest` is taken). Add the same check to the startup
  `.ccsync-tmp` sweep so a stranded staging file is restored or at least reported on the tray, not
  only in a log line.
- Known: CR-249f (FIXED for the upload half only); the recovery half is open.

### res-crash-7 - A package row committed without its file cannot be healed by publishing again

- Severity: low
- Confidence: CONFIRMED (by reading)
- Where: `dashboard/src/ccsync_dashboard/package_store.py:477-489` (same sha already held -> "already published
  ... nothing to do", `.part` unlinked), `:536-552` (commit, THEN `os.replace` of the bytes);
  `api.py:7403-7406` (download 404 "package file missing on server")
- What: dash-api-6 deliberately commits the row first and moves the bytes last, accepting "a row
  whose file is missing ... fixed by publishing again". Publishing again does not fix it: the
  republish finds the row with the same sha256, deletes the newly uploaded `.part`, and returns
  "already held at these exact bytes". The served file stays missing. If the row was made current,
  every companion that tries the update hits the 404, files it as `ERROR_DOWNLOAD`, and burns its
  REL-8 attempt budget on that version.
- Scenario: the container is restarted, or `/data` fills, between `conn.commit()` and `os.replace`
  during a `publish_latest` or a feed pull. The Packages page shows a normal current record; the
  fleet cannot update; the documented remedy (publish again) reports success and changes nothing.
- Recommendation: in the "already held at these exact bytes" branch, if the served file is missing
  (or its size/sha differs), move the verified `.part` into place instead of deleting it. Add a
  boot/collector check that every `companion_packages` row has its file, raised as a notice with
  that next action.
- Known: new (dash-api-6 documents the shape but its stated remedy does not work).

### res-crash-8 - Three hard power losses within ten minutes in the first hour after an update are counted as a crash loop and revert a healthy build

- Severity: low
- Confidence: CONFIRMED (by reading)
- Where: `companion/src/ccsync_companion/upgrade.py:253-330` (`note_version_start`: only a clean shutdown resets
  `starts`), `:116-117` (3 starts / 600 s); `app.py:11760-11771` (revert on `crash_loop`); `app.py:7083-7100`
  (the reverted version is then refused unattended)
- What: a power loss or hard reset sends no WM_ENDSESSION/SIGTERM, so it counts as a start without
  a clean shutdown (CR-316 deliberately still reports it as a crash). While `.old` still exists
  (up to an hour after an update), three such starts inside ten minutes trigger APP-5's revert to
  the previous build, and `crash_looped` then blocks unattended re-installs of the good version
  until a newer one ships or a person clicks.
- Scenario: a site with a failing UPS or brownouts the afternoon an `auto_update` lands. The fleet
  shows that machine "reverted off vX because it kept crashing", the admin is alerted to a bad
  build that is fine, and that computer sits on the old version.
- Recommendation: count a start as a crash only if the previous run left evidence that it died in
  user space (the run marker exists AND the system boot time is older than the previous start).
  On Windows compare `GetTickCount64`/last boot time; on macOS `kern.boottime`. A start right after
  an OS boot does not count against the build.
- Known: new (APP-5 / REL-2 / CR-316 context).
