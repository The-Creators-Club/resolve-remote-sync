# NAS-side scripts, installers and onboarding (OPS)

## Summary
This is the most defensively-written area of the repo: staged-verify-swap everywhere, host-key
pinning, marker identity refusals, `Get-DriveMapping` instead of `Test-Path`, quarantine
stripping, signature/sha gates, `fail_after_app_swap`. Almost every finding below is therefore a
*hole in an existing guard* rather than a missing one. The biggest risk found: a bind-mount
dashboard deploy (the mode every live site runs) never asks whether the dashboard came back after
the restart - it prints "restarted container" and returns 0, while `app.old.<ts>` sits one rename
away. Second biggest: nothing on the server side ever looks at NAS free space, while the snapshot
policy this repo installs pins 30 days of a multi-TB media tree's churn. Cheapest win: make every
server script print the NAS **host** and the `site.toml` it resolved before it does anything - two
lines, and it is the only defence against the owner running `setup_tree.py` at the wrong box.

## Findings

### OPS-1: a bind-mode deploy never checks that the dashboard came back up
- **Lens:** pitfall
- **Where:** `server/install_dashboard_app.py:4458-4483` (the `installed` branch), `:3164-3205`
  (`build_swap_script`), `:860-956` (`verify_image_boot`, image mode only)
- **Scenario:** owner runs `tools\ship.cmd`. The app tree ships and verifies (count+bytes), the
  container is restarted onto it, and the new code raises at import (a template moved, a module
  added to the repo but excluded by `EXCLUDE_DIRS`, a lockfile drift, a bad `site.toml` value).
- **Today:** `restart_dashboard_container` returns True (the docker restart itself succeeded),
  `print("restarted container: ...")`, `return 0`. Nothing probes `/api/v1/health`. In image mode
  `verify_image_boot` runs but its result is **discarded** on this path (`if image_mode and
  restarted: verify_image_boot(...)` then `return 0`). `ship.cmd` sees exit 0 and carries on to
  publish companions. The fleet dashboard - "what tells everyone whether their footage is
  syncing" - is down, and the only signal is an owner opening a browser.
- **Proposed:** after any restart, probe `/api/v1/health` from inside the container (the probe
  already exists at `:940-947`) with a short retry budget covering the healthcheck `start_period`.
  On failure: print the exact one-line rollback (`mv <root>/app <root>/app.failed-<ts>; mv
  <root>/app.old.<ts> <root>/app; docker restart <container>`), offer `--rollback-on-unhealthy` to
  do it automatically, and **return non-zero** so `ship.cmd` stops before publishing companions.
  Honour `verify_image_boot`'s return on the redeploy path too.
- **Effort:** M   **Severity:** critical   **Confidence:** high
- **Related:** OPS-2/OPS-3/SERVER-8 in this file's own comments; `build_prune_script`'s mountinfo
  belt is the only thing that currently limits the blast radius.

### OPS-2: nothing anywhere looks at NAS free space, and the snapshot policy pins deleted blocks for 30 days
- **Lens:** safeguard
- **Where:** `server/setup_snapshots.py:25-28` (24 hourly + 30 daily on `[tree] pool_root`),
  `server/check_health.py:1-27` (the seven checks; none is capacity), grep for
  `df|statvfs|disk_usage|free space` across `server/` returns nothing operational
- **Scenario:** lane A uploads camera originals continuously. An editor deletes or replaces 2 TB
  in the tree; hourly snapshots hold every one of those blocks for up to 30 days. The pool
  crosses 95%, then 100%.
- **Today:** no script warns. `setup_tree`'s `mkdir`/`chown` fails with an opaque rc, lane A
  fails per-file, the dashboard's sqlite writes start failing, and on ZFS a 100%-full pool is hard
  to *delete* out of. The snapshot comment ("cost only the blocks that CHANGED") is true and
  misleading for a media tree - the churn is the whole file.
- **Proposed:** (a) a `check_health` capacity check: `zfs list -o name,avail,used,usedsnap` /
  DSM equivalent for the tree and apps datasets, WARN under 15% free, FAIL under 5%, and print
  `usedbysnapshots` explicitly so "the snapshots are eating the pool" is legible. (b) A pre-flight
  in `install_dashboard_app` and `publish_db` refusing to stage when free space is under
  2x the payload. (c) Surface the number on the dashboard's admin page next to the fleet grid so
  the non-technical owner sees it without running anything. (d) Document/lower tree snapshot
  retention, or exclude a high-churn sub-path.
- **Effort:** M   **Severity:** high   **Confidence:** high

### OPS-3: `setup_tree`'s `chown -R` runs through an unguarded 120 s inactivity timeout
- **Lens:** pitfall
- **Where:** `server/setup_tree.py:269` (`run_ssh(script, dry_run=...)`, default `timeout=120`),
  `server/backends/truenas.py:800-819` (`chown -R` + `find -type d -exec chmod 2770 +` over the
  whole project base), `server/common.py:1232` (paramiko channel timeout = *inactivity*),
  `server/install_dashboard_app.py:2968-3002` (`tree_ssh_timeout` + `run_ssh_guarded`, the fix
  that was never carried here)
- **Scenario:** the documented repair action - "re-running this against an existing project is the
  supported way to repair permissions" - on a project that now holds 4 TB and 200k files.
  `chown -R` prints nothing for ten minutes.
- **Today:** `socket.timeout` after 120 s of silence. `setup_tree` does not use `run_ssh_guarded`,
  and `cli()` only catches `EnvError`/`NotImplementedError` - so the operator gets a raw paramiko
  traceback while the `chown -R` **keeps running on the NAS**. Nothing says whether it finished.
  A worried re-run starts a second concurrent recursive chown.
- **Proposed:** route it through the same pair the deploy uses: a `run_ssh_guarded` equivalent plus
  a size-derived timeout (or simply a large fixed one for the recursive step), and have the remote
  script emit a heartbeat line (`chown -R ... & while kill -0 $!; do echo .; sleep 20; done`) so
  the channel is never idle. On a transport failure, print "the chown may still be running on the
  NAS; re-run this command when it settles - it is idempotent" rather than a traceback.
- **Effort:** S   **Severity:** high   **Confidence:** high
- **Related:** OPS-3 (2026-08-11) in `install_dashboard_app`; the lesson exists, it just never
  reached `setup_tree.py`/`write_marker.py:182`.

### OPS-4: no server script says WHICH NAS it is about to change, and the destructive ones apply by default
- **Lens:** user-error
- **Where:** `server/setup_tree.py:240` (prints the path, never the host), `server/setup_tree.py:218`
  / `setup_editor_account.py:432` / `install_dashboard_app.py:3640` (all `--dry-run` opt-in, i.e.
  apply-by-default), vs `publish_db.py:523-527` and `setup_snapshots.py` (dry-run default),
  `server/common.py:87-117` (`load_site` search order: `--site` > `$CCSYNC_SITE` > `<repo>/site.toml`)
- **Scenario:** the owner has a vendor `site.toml` in the repo and a customer's under `--site`.
  In a second terminal, or after a `git pull` that restored the repo default, he forgets `--site`
  and runs `setup_tree.py --year 2026 ...`.
- **Today:** the run prints `Target project root: /mnt/<pool>/<tree>/Projects/...` and nothing
  else, then `chown -R`s on whichever host `[nas] host` resolved to. The pinned host key is the
  only backstop and it is *silent* when both hosts happen to be recorded in
  `~/.ccsync/known_hosts`. There is no confirmation prompt and no host in any output line.
- **Proposed:** one shared banner from `common` printed by every script before its first
  connection: `NAS: <user>@<host>:<port> (<kind>)  site: <site_file() or "<none>">  tree:
  <DEFAULT_CC_ROOT>`. For the recursive/destructive ones (`setup_tree`, `install_dashboard_app
  --recreate`, `setup_editor_account --revoke-key`), require either `--apply` or a typed
  confirmation of the host's short name when stdin is a tty. Cheap, and it is the guard the
  non-technical owner actually needs.
- **Effort:** S   **Severity:** high   **Confidence:** high

### OPS-5: the sshd Match block is written with no validation, no backup and no post-write probe
- **Lens:** pitfall
- **Where:** `server/backends/truenas.py:626-661` (`ensure_sshd_editor_policy`, `PUT /ssh
  {"options": ...}`), `server/setup_editor_account.py:267-280` (a failed PUT is a WARNING only)
- **Scenario:** the site already has its own text in the ssh service's Auxiliary Parameters (that
  is usually why the field is non-empty). Our block is appended at the END; a `Match` line already
  present in the operator's text, or a later operator addition typed *after* ours in the DSM/SCALE
  UI, changes what the directives apply to. Or middleware simply rejects the combined config.
- **Today:** the PUT either succeeds (and nothing re-reads sshd, restarts it, or reconnects to
  prove SSH still works) or fails with a printed WARNING and the account is created anyway. If
  sshd stops accepting connections, *every* script in this package, `publish_db`, the deploy and
  every editor's rclone lanes A/B lose the NAS at once, and the recovery needs console access.
- **Proposed:** before the PUT, save the previous `options` to `~/.ccsync/sshd_options.<host>.<ts>.bak`
  (so the rollback survives the script dying) and print the path. After the PUT, open a **fresh**
  `ssh_client()` and run `true`; on failure, PUT the saved value back automatically and say so.
  Refuse up front when `current` contains a `Match` line outside our markers - our block cannot be
  appended safely there, and the operator should be told rather than guessed at.
- **Effort:** M   **Severity:** high   **Confidence:** high

### OPS-6: closing the onboarding wizard mid-install kills a half-finished machine
- **Lens:** user-error
- **Where:** `onboarding/onboard.py:805` (`threading.Thread(target=worker, daemon=True).start()`),
  `:807-825` (`_clean_slate` unmaps the drive, kills the companion, deletes autostart), no
  `WM_DELETE_WINDOW` protocol handler anywhere in the file
- **Scenario:** the install log stalls on a slow winget/Tailscale step. The editor closes the
  window ("I'll try again later") or reboots.
- **Today:** Tk exits, the daemon worker dies at an arbitrary point, and the spawned bootstrap
  PowerShell keeps running **unparented**. The machine can be left with: no tree drive (unmapped
  by `_clean_slate`, never remapped), no companion, no autostart, and a `config.toml` written or
  not depending on timing. Re-running does recover (everything is idempotent) but nothing tells
  the editor they must, and a second run can race the orphaned PowerShell.
- **Proposed:** `root.protocol("WM_DELETE_WINDOW", ...)`: while `self._installing`, show
  "Closing now can leave this machine half-installed - your tree drive is currently unmapped.
  [ KEEP INSTALLING ] / [ CLOSE ANYWAY ]". On CLOSE ANYWAY, terminate the bootstrap child
  process group first. Write a breadcrumb (`~/.ccsync/state/install_in_progress.json` with the
  phase) at the start of `_clean_slate` and clear it on Finish; the wizard reads it at startup and
  opens on "the last install did not finish - [ RESUME ]" instead of the welcome page.
- **Effort:** M   **Severity:** high   **Confidence:** high
- **Related:** B7, B20, B22 (all about this worker's failure paths); `execute_cleanup` is the
  destructive half.

### OPS-7: the whole Windows install lands in the wrong profile if UAC prompts for another account
- **Lens:** user-error
- **Where:** `installer/windows_bootstrap.ps1:450` and `:1505` (task principal
  `$env:USERDOMAIN\$env:USERNAME`), `:859` (`$BinDir = $env:LOCALAPPDATA\ccsync\bin`), `:1397`
  (share FullAccess), `:1954` (`$env:USERPROFILE\.ccsync`), `:660-700` (HKCU Run entries)
- **Scenario:** the editor's day-to-day account is a standard user (or they simply reflex
  right-click > Run as administrator). Windows prompts for **credentials**, not consent, and they
  type the machine's admin account.
- **Today:** every artefact - bin dir, `~/.ccsync/config.toml`, identity, Syncthing home, Run
  entries, the scheduled task principal, the share's FullAccess grant - is created for the
  ADMIN profile. The script reports success and prints a device ID. The editor logs back into
  their own account: no tray icon, no tree drive, no config. The dashboard shows a machine that
  reported once and then never again. Nothing in the script compares the running identity with
  the interactive one.
- **Proposed:** at the top, read the console user (`(Get-CimInstance Win32_ComputerSystem).UserName`,
  or the owner of `explorer.exe`) and compare with `$env:USERNAME`. If they differ, REFUSE with:
  "You are running as <A> but <B> is signed in. Everything this installs is per-user, so <B>
  would get nothing. Sign in as <B> and run it again (it does not need administrator rights)."
  Same check at the top of `onboard.py` before the role page.
- **Effort:** S   **Severity:** high   **Confidence:** med

### OPS-8: the uninstaller inverts the "can't tell = foreign" rule the bootstrap was fixed to obey
- **Lens:** pitfall
- **Where:** `installer/windows_uninstall.ps1:180-205` (`Get-PSDrive` + `Test-Path`, then
  `$looksLikeOurs = [string]::IsNullOrWhiteSpace($displayRoot) -or ...`), vs
  `installer/windows_bootstrap.ps1:584-620` + `:1280-1300` (`Get-DriveMapping`, `$null` = foreign)
- **Scenario A (wrong default):** on the base rig `P:` is a real SMB mapping of the NAS. `Get-PSDrive`
  is wrapped in a `try{}catch{}` that leaves `$pDrive` `$null`; any failure there makes
  `$displayRoot` blank, which the expression reads as "subst mapping, ours", and the script runs
  `net use P: /delete /y` - the exact D-8/B21 destruction the bootstrap refuses to risk.
- **Scenario B (ordering under elevation):** the editor runs the uninstaller elevated (reasonable -
  `Remove-SmbShare` needs it). The elevated session's device map does not contain their mapping, so
  `Test-Path "P:\"` is false and the unmap is skipped - but `Remove-SmbShare` **succeeds**. The
  user's session keeps a `P:` pointing at a share that no longer exists: a drive letter that errors
  rather than one that is cleanly gone. The script's own catch-block comment acknowledges the
  device-map split; the code does not act on it.
- **Today:** as described; the uninstaller never got the bootstrap's `Get-DriveMapping` /
  `Invoke-AtUserIntegrity` treatment.
- **Proposed:** share `Get-DriveMapping`/`Invoke-MappingCommand` (dot-source or a small shared
  `.ps1`), treat `$null` as foreign, route the unmap through the user's integrity level when
  elevated, and remove the share **only after** the unmap reported success (otherwise leave both
  and print the two commands).
- **Effort:** S   **Severity:** high   **Confidence:** med

### OPS-9: "no snapshot" is a stderr line in a 500-line log and nothing durable
- **Lens:** safeguard
- **Where:** `server/common.py:1784-1830` (`snapshot_before`, best-effort, warns and returns
  False), `server/setup_tree.py:266` and `server/install_dashboard_app.py:3994` (both **discard**
  the return value), `KNOWN_BUGS.md:147` WPK-6 ("nobody read the WARNING because the deploy went
  on to succeed")
- **Scenario:** exactly WPK-6 again, from any of the other reasons a snapshot can fail: API key
  scope, a Synology without Snapshot Replication, a dataset renamed, `[apps] root` moved.
- **Today:** one `WARNING:` on stderr, buried; the deploy/chown proceeds; the operator's memory of
  "backups are configured" is never contradicted. `CCSYNC_REQUIRE_SNAPSHOT` exists but no
  documented workflow sets it (COMMERCIAL_READINESS says "once verified" - it never was).
- **Proposed:** make the fact durable and visible, not louder. `snapshot_before` appends
  `{ts, label, path, ok, detail}` to `~/.ccsync/snapshot_log.jsonl`; every script prints a
  one-line verdict in its FINAL summary block ("this run had a snapshot behind it: yes/NO"), not
  only mid-log; `check_health` adds a check that a `ccsync-*` snapshot of the tree and the apps
  dataset exists within the last 2 hours, and `tools\ship.cmd` refuses to proceed to the companion
  publish if the deploy's snapshot did not happen (or requires `-NoSnapshot`).
- **Effort:** M   **Severity:** high   **Confidence:** high

### OPS-10: `publish_db` stages a database into `/tmp` on TrueNAS and never sweeps its own orphans
- **Lens:** pitfall
- **Where:** `server/publish_db.py:396-421` (`staging_parent` returns `/tmp` for anything that is
  not Synology), `:598`, vs `server/install_dashboard_app.py:3035-3072` (`prune_orphaned_staging`,
  OPS-8/SERVER-5: "/tmp on the NAS may be RAM-backed", swept for every parent the deploy uses)
- **Scenario:** `music.db` is 20 MB today; the b-roll index grows with the archive. A deterministic
  failure (a `quick_check` refusal, an OPS-3-style timeout) is re-run several times.
- **Today:** each failed run deliberately leaves `/tmp/ccsync-brolldb-upload.XXXXXX` behind for
  inspection - and `publish_db` never calls `prune_orphaned_staging`, so nothing ever reclaims
  them. The two lessons the deploy learned (don't stage big payloads in `/tmp`; sweep every parent
  you stage into) were both written down and neither was carried into the script whose entire job
  is shipping a database.
- **Proposed:** call `prune_orphaned_staging(dry_run, ("/tmp", f"{root}/staging"))` at the top of
  `publish_db.main()`, and use `<apps root>/staging` on every backend rather than only DSM.
- **Effort:** S   **Severity:** med   **Confidence:** high

### OPS-11: index backups accumulate forever, uncounted and unbudgeted
- **Lens:** safeguard
- **Where:** `server/publish_db.py:452-457` ("a publish keeps exactly one .prev per run and never
  deletes them"), `server/install_dashboard_app.py:2189-2196` (`music.db.old.<ts>`, "never pruned
  automatically")
- **Scenario:** weekly index publishes over a year on a nearly-full pool (see OPS-2).
- **Today:** unbounded growth in the b-roll archive and `music-data`, with no listing, no count and
  no warning. The deliberate no-auto-delete rule is right; the absence of *visibility* is not.
- **Proposed:** at the end of every publish, list the existing `.prev-*`/`.old.*` with sizes and
  total, and warn past a threshold (say 5 or 2 GB) with the exact `rm` line. Add
  `publish_db.py --list-backups` and mention them in `check_health`'s capacity check.
- **Effort:** S   **Severity:** low   **Confidence:** high

### OPS-12: the ship asks for the dashboard password only after the whole build, and gives one attempt
- **Lens:** user-error
- **Where:** `installer/build_editor_package.ps1:960-972` (Read-Host, then `exit 1` on a failed
  login), vs `:285-304` (the CR-52 floor check, deliberately "at second 1 ... PyInstaller takes
  minutes")
- **Scenario:** the owner mistypes the password, or the dashboard is mid-restart from the deploy
  step that `ship.cmd` just ran.
- **Today:** `Write-Warn2 "dashboard login failed ... NOT publishing"; exit 1` after the full
  build. The whole `ship.cmd` run (gates, deploy, PyInstaller x2) has to be repeated - and a
  half-shipped release (dashboard deployed, companion not published) is a state this repo has been
  bitten by before (the 2026-08-12 note in this same file).
- **Proposed:** do the login **before** the build when `-Publish` is set (the same argument the
  CR-52 comment makes), keep the session for the upload, and allow 3 attempts with a distinct
  message for "wrong password" vs "cannot reach the dashboard".
- **Effort:** S   **Severity:** med   **Confidence:** high

### OPS-13: the project marker is written non-atomically, and a slug-less marker is a dead end
- **Lens:** pitfall
- **Where:** `server/common.py:690-748` (`build_marker_write_cmd`: `printf '%s' <json> > <marker>`
  under `sudo sh -c`), `:717-745` (the `only_if_absent` branch compares `had_slug` to `want_slug`),
  `server/write_marker.py:51-65` (`parse_marker_slug` tolerates garbage and returns `""`)
- **Scenario:** the redirection truncates the marker and the write does not complete (full pool -
  see OPS-2 - an I/O error, or a killed remote shell).
- **Today:** the marker exists with no readable slug. `setup_tree` re-runs then take the "marker
  already present with a DIFFERENT identity ... NOT overwriting" branch **forever** (`had_slug=""`
  never equals the wanted slug), `setup_syncthing_folder` treats an unparseable marker as a
  REFUSAL by design, and the original slug is unrecoverable except from the dashboard's own rows.
  `write_marker.py --force` can repair it only if a human knows the old slug.
- **Proposed:** write to `<marker>.tmp` and `mv` it into place (atomic on the same filesystem) in
  `build_marker_write_cmd`. Add a fourth state to the read side: MARKER-PRESENT-BUT-NO-SLUG, which
  every caller reports as "damaged marker at <path>; recover the slug from the dashboard and run
  write_marker.py --slug <it> --force" instead of the identity-change refusal.
- **Effort:** S   **Severity:** med   **Confidence:** med

### OPS-14: `check_health` validates liveness, never the invariants this area can break
- **Lens:** safeguard
- **Where:** `server/check_health.py:1-27` (the seven checks), `:388-417` (`check_tree` = one
  `test -d`)
- **Scenario:** the owner runs the one command he has been told validates the server side.
- **Today:** it proves Postgres/Tailscale/Syncthing/tree-dir/editors-group/dashboard are up. It
  does not check: a snapshot task exists and fired recently (OPS-9), free space (OPS-2), that
  every project directory carries exactly one marker and no marker is nested under another (the
  invariant `setup_tree` refuses to break but nothing re-verifies afterwards), that each marker's
  slug has a matching Syncthing folder and vice versa (the orphan-folder failure
  `setup_syncthing_folder`'s docstring describes), or that the deployed dashboard version matches
  the repo's.
- **Proposed:** add those five as checks 8-12 - all are cheap reads (`find -name .ccsync-project`
  under `sudo`, `GET /rest/config/folders`, `GET /api/v1/health`) and each maps to a failure that
  today is only discovered by an editor noticing they are not syncing. Print a one-line health
  score at the end so a non-technical owner has something to read.
- **Effort:** M   **Severity:** med   **Confidence:** high

### OPS-15: on a Mac where the companion fails to install, the LEGACY launch agent is left running
- **Lens:** pitfall
- **Where:** `installer/macos_bootstrap.sh:2177-2223` (download/verify can leave
  `COMPANION_MISSING=1`), `:2296-2302` (`retire_legacy_agent "$COMPANION_PLIST_LEGACY"` sits in the
  **else** branch), vs `:1736` where the Syncthing legacy retire is unconditional
- **Scenario:** a Mac provisioned before 2026-08-17 (running `com.creatorsclub.ccsync.companion`)
  is re-bootstrapped, and the companion download fails - a stale token, no published macOS
  package, or the unsigned-package refusal at `:2205`.
- **Today:** the script prints the big "THE SYNC APP IS NOT INSTALLED ON THIS MAC" banner, removes
  only `$COMPANION_PLIST` (the new label), and leaves the legacy agent loaded. An OLD companion
  keeps running, keeps holding loopback 8899, and keeps syncing under old rules - so the banner is
  actively wrong, and when the install later succeeds the two agents race for 8899 (the exact
  failure the `retire_legacy_agent` call was added to prevent).
- **Proposed:** move `retire_legacy_agent` out of the else, next to the Syncthing one at `:1736`,
  so it runs on every path; and in the failure banner state whether a legacy companion was found
  and booted out ("an older CC Sync was running on this Mac and has been stopped").
- **Effort:** S   **Severity:** med   **Confidence:** high

### OPS-16: Ctrl-C during a deploy skips `fail_after_app_swap`
- **Lens:** user-error
- **Where:** `server/install_dashboard_app.py:3478-3505` (`fail_after_app_swap` is reached only via
  `return`), `server/common.py:1836-1851` (`cli()` catches `EnvError`/`NotImplementedError` only),
  `:4342-4427` (every post-swap step)
- **Scenario:** the owner watches the 1.4 GB music push crawl and presses Ctrl-C.
- **Today:** `KeyboardInterrupt` escapes `main()` and `cli()`. The container is still serving the
  inode now called `app.old.<ts>`, no restart happens, and the deploy "did nothing" as far as the
  owner can tell - while the dashboard is silently running the previous code. `build_prune_script`'s
  mountinfo check stops the next deploy from deleting it, so this is exposure, not loss.
- **Proposed:** catch `KeyboardInterrupt` (and `BaseException`) around the post-swap region and
  route it through `fail_after_app_swap`; print "the app tree was already swapped, so the container
  was restarted onto the new code before stopping." Add the same handler in `cli()` for the other
  scripts so an interrupt prints one line instead of a traceback.
- **Effort:** S   **Severity:** med   **Confidence:** high

### OPS-17: a timed-out `run_ssh` leaves the remote command running, with no way to ask whether it finished
- **Lens:** safeguard
- **Where:** `server/common.py:1232-1270` (`run_ssh`; the paramiko timeout is per-read, and the
  `finally: client.close()` does not stop the remote process), `install_dashboard_app.py:2987-3002`
  (`run_ssh_guarded` turns it into rc 255 "assume it did not finish")
- **Scenario:** any long privileged step - the `chown -R` of OPS-3, a `cp -a` of the music
  artefacts, a `docker pull` - exceeds its timeout.
- **Today:** the caller assumes "it did not finish" and either fails or retries; the remote command
  is still running. Two concurrent `cp -a`/`chown -R` on the same paths is a real possibility on a
  retry, and nothing detects it.
- **Proposed:** give the long steps an idempotency lock on the NAS: wrap them in
  `flock -n <root>/.ccsync-<step>.lock` (or a pidfile probe), so a retry that arrives while the
  first is still running is REFUSED with "the previous run's <step> is still going on the NAS
  (started <ts>) - wait for it or clear <lockfile>", rather than racing it. The lock file also
  gives the operator the "did it finish?" answer that does not exist today.
- **Effort:** M   **Severity:** med   **Confidence:** med

## Cross-cutting notes
- **Dashboard agent:** `dashboard_update.snapshot_before` (`dashboard/src/.../dashboard_update.py:835`)
  is the container-side twin of `common.snapshot_before` and has the same "warn and continue"
  shape plus WPK-5's missing-dataset skip; the durable snapshot log proposed in OPS-9 should cover
  both, and the dashboard is the right place to *show* it.
- **Companion agent:** the uninstaller and the wizard both `Stop-Process -Force` /
  taskkill the companion (`windows_uninstall.ps1:96-118`, `steps.execute_cleanup`) with no
  quiesce - if a Resolve mutation or an `resolve_edits` undo-journal write is in flight, it is cut
  mid-write. A "stop cleanly" IPC on the loopback server (8899) would make both installers safer.
- **Release/CI agent:** OPS-1's proposed non-zero exit changes `tools\ship.cmd`'s contract - the
  companion publish must be gated on the dashboard actually being healthy, which is the ordering
  CLAUDE.md already insists on ("deploy the dashboard before the companions").
