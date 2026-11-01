# bug-installer: installer/ and onboarding/ (pre-launch hunt, 2026-10-06)

Lens: the Windows bootstrap/uninstall/upgrade scripts, `drive_mapping.ps1`, the
macOS bootstrap/uninstall, and the onboarding wizard (`onboard.py`, `steps.py`).
Scenarios looked at: a fresh machine, a re-install, an uninstall, a non-admin
user, a drive letter other than P:, and non-English Windows. The working tree
was reviewed at HEAD 08b40eb plus the uncommitted changes.

What I read end to end: `installer/windows_bootstrap.ps1`, `drive_mapping.ps1`,
`windows_uninstall.ps1`, `windows_upgrade.ps1` (lines 1-580), and
`macos_uninstall.sh`. In `onboarding/steps.py` I read the cleanup plan and
executor (Windows and macOS), `run_bootstrap`, `ensure_config`, the launch
helpers, `validate_local_root`, the breadcrumb and log helpers, and the
forbidden-drive check. In `onboard.py` I read the install workers. For
`macos_bootstrap.sh` I read only the companion download, the local root/volume
section and the chmod sites.

Probes I ran:
- An icacls probe in the scratchpad: the bootstrap's exact
  `Protect-CCSyncPath` command, run against a directory that already has
  children. This is the evidence for finding 1.
- `winget show` for Rclone.Rclone and Syncthing.Syncthing. Both are
  `portable (zip)` packages, which is the evidence for finding 2.

Not covered:
- `build_editor_package.ps1`
- the rest of `macos_bootstrap.sh` (Resolve Mapped Mount helper, LaunchAgents)
- the EULA, privacy and Tailscale pages of the wizard, which the 09-24 hunt
  covered closely
- Tk layout

Before reporting, I checked every item below against KNOWN_BUGS.md and the
2026-09-24 hunt.

---

### bug-installer-1 - The bootstrap strips the ACL inheritance from ~/.ccsync. Every file and folder already inside it becomes unreadable, including the companion's safety latches in state\

- **Severity:** critical
- **Confidence:** CONFIRMED (code read, and probed with the exact icacls command)
- **Where:** `installer/windows_bootstrap.ps1:551-575` (Protect-CCSyncPath), `:2179-2181` (applied to `$CCSyncConfigDir`); wizard writes into that dir first: `onboarding/onboard.py:526` (eula_accepted.json), `onboarding/steps.py:2500-2518` (state/ install breadcrumb), `:2320-2341` (logs/onboard-*.log), `:3681` (config.toml)
- **What:** `Protect-CCSyncPath` runs this command on the `~/.ccsync`
  *directory*:

  ```
  icacls <dir> /inheritance:r /grant:r <me>:(F) SYSTEM:(F) Administrators:(F)
  ```

  The grants have no `(OI)(CI)` flags, so the directory keeps no inheritable
  ACEs. Windows re-propagates inheritance when the directory's DACL changes, so
  every existing child whose ACEs were all inherited ends up with an EMPTY DACL.
  The user can no longer read or write those files, and nobody can create
  anything inside those subfolders. Only `config.toml` and `identity.json` get
  their own explicit grant afterwards (`:2182-2186`).

  I reproduced this in the scratchpad. After the command:
  - `dot\companion.log` reads "Access is denied".
  - `dot\state\x.json` reads "Access is denied".
  - Creating `dot\state\new.json` is denied.
  - New files created directly in `dot\` are fine.
- **Scenario:** This hits every Windows editor install through the wizard,
  fresh machines included. Before the bootstrap starts, the wizard has already
  written several things into `~/.ccsync`:
  - the EULA page writes `eula_accepted.json`
  - `_clean_slate` writes `state\<breadcrumb>`
  - the install log is open at `logs\onboard-<ts>.log`
  - `ensure_config` writes `config.toml`

  When the bootstrap reaches section 8, `Test-Path ~/.ccsync` is true and the
  directory is "protected". What follows:
  1. The rest of the wizard's install log cannot be appended, and the log file
     the finish page points the editor to cannot be opened.
  2. The companion's `eula.read_acceptance` hits an OSError, returns None, and
     the companion treats the EULA as not accepted. It shows the licence dialog
     and refuses to sync, although the editor accepted the EULA a minute
     earlier in the wizard.
  3. The `~/.ccsync\state` directory is permanently unusable. That is where
     `lane_b_breaker.json`, `sync_halt.json`, `drive_unfinished.json`,
     `project_prompts.json` and every other latch live. `lane_guard._read_json`
     maps the OSError to `{}`, and writes fail. So the safety latches that
     CLAUDE.md says must never be in-memory-only can no longer be persisted.
  4. On a RE-RUN on a working machine, the breaker that had parked lane B
     reads back as "not tripped", so lane B resumes and the safety latch is
     bypassed. The undo journals under `resolve_edits\` and the crash reports
     also become unreadable.
  5. `clear_install_breadcrumb` fails silently.

  The code comment (`:2174-2178`) assumes children inherit the restricted
  ACL. In fact it takes away the existing children's access entirely.
- **Recommendation:**
  - Grant with inheritance on directories:
    `/grant:r "<me>:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F"`.
  - Or harden only files, as `companion/secretfile.py` does.
  - Ship a repair for machines already hit: re-grant with `(OI)(CI)` plus
    `/T` on `~/.ccsync`, from the next bootstrap, `windows_upgrade.ps1`, and
    ideally from the companion at startup. `state\` is unrecoverable for the
    user without that.
  - Apply the same `(OI)(CI)` fix to `$helperDir`.
  - Add an installer test that runs `Protect-CCSyncPath` on a temp directory
    with a pre-existing child and asserts the child is still readable.
- **Known:** not recorded. CLAUDE.md memory "EULA gate parks self-upgraded editors" may be a symptom.

### bug-installer-2 - On a fresh machine with winget, rclone and Syncthing installed by winget are invisible to the same run: the first install always ends "NOT READY" with no Syncthing set up, and it bypasses the pinned, sha256-verified binaries

- **Severity:** high
- **Confidence:** CONFIRMED (code read; `winget show` confirms both packages are `portable (zip)`)
- **Where:** `installer/windows_bootstrap.ps1:1089-1100, 1239-1248` (rclone), `:1281-1301, 1338-1343` (Syncthing), `:1951-1957` (section 6 skipped), `:2486-2488` (device-ID miss); `onboarding/steps.py:1870` (child env = the wizard's stale environment)
- **What:** winget is tried before the pinned download. For portable packages,
  winget puts the exe under `%LOCALAPPDATA%\Microsoft\WinGet\Packages\...`
  (or a Links symlink) and adds that to the user PATH in the registry. The
  running PowerShell's `$env:Path` is not updated.

  rclone:
  - The "authoritative check" re-probes with `Test-CommandExists rclone` on
    the same stale PATH and finds nothing.
  - So it adds the capability miss "rclone is NOT installed".

  Syncthing:
  - `Get-SyncthingExePath` probes only PATH, the bin dir and Program Files,
    so it returns `$null`.
  - `$installed` is nevertheless set to `$true` at `:1290`, so the pinned
    direct download is skipped.
  - With `$syncthingPath` null, section 6 is skipped entirely: no `generate`,
    no `CCSyncSyncthing` Run shim, no daemon, no NAS device seeding.
  - Then section 10 adds the "device ID could NOT be determined" miss.

  Separately, whenever winget succeeds the machine gets winget's current
  build, not `$RcloneVersion` / `$SyncthingVersion`. The commercial-readiness
  promise (item 13: same, verified binaries on every machine) only holds on
  machines without winget, which today is almost none.
- **Scenario:**
  1. A new customer's editor runs onboard.exe on a stock Windows 11 PC. winget
     is present; rclone and Syncthing are not.
  2. The bootstrap exits 3. The wizard shows "NOT READY" with three misses
     (rclone, Syncthing, device ID).
  3. The companion launched from the bootstrap inherits the stale PATH, so
     lanes A/B report "rclone not found" until the next logon.
  4. Lane C never starts at all: there is no Run shim, and
     `syncthing_supervisor` relaunches only through that shim.
  5. The documented fix is "re-run", which repeats `_clean_slate`. Only a
     re-launch from a fresh Explorer environment (or a reboot) gets through.

  So every first install by a paying customer's editor fails.
- **Recommendation:**
  - Prefer the pinned, verified download into `$BinDir`. Use winget only as a
    fallback, or drop it.
  - If winget is kept, refresh `$env:Path` from the registry
    (Machine + User) after each winget call, and probe
    `%LOCALAPPDATA%\Microsoft\WinGet\Links`.
  - Never set `$installed = $true` without a located exe.
  - Pass the resolved absolute rclone path into config.toml.
- **Known:** not recorded (ui-onboarding-4 is the same stale-PATH shape for Tailscale in the wizard, fixed there only).

### bug-installer-3 - A Syncthing installed by winget gets its versioned package folder baked into the logon shim, so `winget upgrade` silently kills lane C

- **Severity:** medium
- **Confidence:** PLAUSIBLE
- **Where:** `installer/windows_bootstrap.ps1:1259, 1967, 2007` (Run shim bakes `$syncthingPath`); `companion/src/ccsync_companion/sync/syncthing_supervisor.py:167-223` (relaunch goes through the same shim)
- **What:** When Syncthing came from winget and the editor re-ran the
  bootstrap once PATH had refreshed (the only way finding 2 gets resolved),
  `Get-Command syncthing` returns
  `...\WinGet\Packages\Syncthing.Syncthing_...\syncthing-windows-amd64-v2.1.x\syncthing.exe`.
  The base rig's own PATH shows exactly this shape: the package directories
  are on PATH because the Links symlink was not used. That versioned path is
  written into `CCSyncSyncthing.cmd`. `winget upgrade` (run by the user, by
  IT, or by `winget upgrade --all`) removes the old version directory. After
  that, the logon Run entry and the companion's supervisor both launch a path
  that no longer exists.
- **Scenario:**
  1. The machine is set up via winget.
  2. Weeks later IT runs `winget upgrade --all`.
  3. At the next logon Syncthing does not start. The supervisor's restarts
     fail with "launcher missing/failed".
  4. Lane C carries nothing until someone re-runs the installer.
- **Recommendation:**
  - Always run our own pinned copy from `$BinDir` (also fixes finding 2).
  - Otherwise resolve to the stable `WinGet\Links\syncthing.exe` when present.
- **Known:** not recorded.

### bug-installer-4 - Re-running the wizard silently downgrades the companion to whatever build that onboard.exe bundled, and skips the downgrade floor

- **Severity:** medium
- **Confidence:** CONFIRMED (code read)
- **Where:** `onboarding/steps.py:2980, 3011-3019` (clean slate deletes `%LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe`), `:3107-3229`; `installer/windows_bootstrap.ps1:2276-2300` (copies the bundled exe whenever the destination is missing); base role `onboard.py:1733` (`install_companion`); no version comparison anywhere in either path
- **What:** The installer docs and the wizard both present "re-run the
  installer" as the safe repair. A re-run deletes the installed companion,
  whatever version it has self-upgraded to, and installs the copy bundled
  inside the onboard.exe being run. Editors keep the onboard.exe they first
  downloaded. Neither the wizard nor `windows_upgrade.ps1` compares versions.
  `~/.ccsync/upgrade_floor.json` is consulted only for channel offers, so the
  companion runs the older build without complaint.
- **Scenario:**
  1. An editor installed with onboard 1.0.40, which bundles companion 0.9.6x.
  2. The fleet has since auto-updated to 0.9.82.
  3. Their tree drive vanishes, and they re-run the onboard.exe from
     Downloads.
  4. The machine now runs 0.9.6x again, a build that predates the security
     and safety fixes since then (the report_* opt-out keys, the CR-3xx sync
     fixes).
  5. With `auto_update` off (the vendor default) it stays there until someone
     clicks UPDATE.
- **Recommendation:**
  - Read the installed build's version (`ccsync-release.json`) before
    clean-slate.
  - If it is newer than the bundled build, keep it and skip the copy, or at
    least say so and ask.
  - Apply the same guard in `windows_upgrade.ps1`.
- **Known:** not recorded.

### bug-installer-5 - The tree-drive letter being a real volume (USB disk, card reader, DVD, a second partition) is read as "free": the install says DONE with no tree drive and leaves a logon task that fails at every logon

- **Severity:** medium
- **Confidence:** CONFIRMED (code read)
- **Where:** `installer/drive_mapping.ps1:131-202` (Get-DriveMapping sees only `subst` + `net use`); `installer/windows_bootstrap.ps1:1476-1494, 1691-1736` (map attempts warn only); `onboarding/steps.py:2156-2226` (validate_local_root never checks the tree letter itself)
- **What:** The ownership check reads only `subst` and `net use` output. A
  letter held by a local or removable volume appears in neither, so
  `Mapped = $false` and the code proceeds:
  1. The teardown is a no-op.
  2. `net use Q: \\localhost\CCSync_Q /persistent:yes` fails with system
     error 85, "the local device name is already in use".
  3. It falls back to subst: the logon task `CCSync-SubstQ` (or the Run
     entry) is registered.
  4. `subst Q: "C:\Tree"` fails.

  Each failure is only a `Write-Warn2`. Nothing calls `Add-CapabilityMiss`,
  so the script exits 0 and the wizard shows the green DONE page. OPS-1 /
  CR-153 closed only the "mapped to someone else" variant.
- **Scenario:** On a commercial site the drive letter is site data
  (`canonical_prefix = "E:\"`, or a P: that an editor's external drive or card
  reader already occupies). The editor finishes the wizard with DONE. Every
  Resolve clip path under that letter is offline, lane B has nowhere to land,
  and a hidden task runs a failing `subst` at every logon. If the volume later
  goes away, the logon subst silently takes the letter, which hides the cause.
- **Recommendation:**
  - Before mapping, test whether the letter is in use at all, for example
    `[IO.DriveInfo]::GetDrives()` or `Get-PSDrive` run at user integrity.
    Treat a letter that is not ours, mapping or volume, as a foreign-drive
    capability miss.
  - After mapping, verify that `<letter>:\` resolves to `$CCRoot`, and record
    a capability miss if it does not.
  - Have the wizard refuse up front when the site's letter is a local volume.
- **Known:** not recorded (CR-153/OPS-1 is the mapped-foreign case only).

### bug-installer-6 - Any Syncthing the editor already runs is taken to be ours: ours is never started, lane C is wired to the wrong instance, and the wizard still says DONE. The Windows uninstaller kills that Syncthing too

- **Severity:** medium
- **Confidence:** CONFIRMED (code read)
- **Where:** `installer/windows_bootstrap.ps1:2010-2013` (`Get-Process -Name syncthing` means "already running"), `:1895-1901` (API-key 401/403 is a warning only), `:2027-2030`; `installer/windows_uninstall.ps1:321-331` (`Stop-Process` on every `syncthing`); `installer/windows_upgrade.ps1:572-579`
- **What:** INST-20 taught the wizard's clean-slate and the macOS uninstaller
  to touch only a Syncthing running from our own directories. The Windows
  bootstrap, the Windows uninstaller and `windows_upgrade.ps1` still match by
  process name. If the editor runs a personal Syncthing (SyncTrayzor, a winget
  or scoop copy), it owns `127.0.0.1:8384` with its own home. In that case:
  - The bootstrap skips starting ours.
  - Seeding gets a 401/403. It prints a WARNING and returns, with no
    capability miss.
  - The companion's lane C then talks to the editor's personal instance with
    our API key.
  - At every logon our Run shim's `syncthing serve` fails to bind 8384.
- **Scenario:** A freelance editor who already syncs personal files with
  Syncthing installs CC Sync. The wizard says DONE. Lane C never connects to
  the NAS, and the fleet grid shows Syncthing errors with no explanation.
  Separately, when the editor uninstalls CC Sync, `windows_uninstall.ps1`
  force-kills their personal Syncthing mid-transfer.
- **Recommendation:**
  - Use the same path filter as `steps.execute_cleanup` (`_path_under_any`
    over the managed dirs) in all three scripts.
  - In the bootstrap, when a foreign Syncthing holds 8384, either give ours a
    different GUI/listen port (written into config.toml `syncthing_url`) or
    record a capability miss naming the conflict.
- **Known:** INST-20 (fixed in the wizard and in macos_uninstall.sh only).

### bug-installer-7 - Every wizard install blocks ALL inbound SMB (139/445) on every network profile, the wizard cannot opt out, and the editor is never told

- **Severity:** medium
- **Confidence:** CONFIRMED (code read)
- **Where:** `installer/windows_bootstrap.ps1:1413-1434, 1649-1659` (rule: Inbound Block TCP 139,445, RemoteAddress Any, Profile Any); `onboarding/steps.py:1829-1856` (never passes `-KeepRemoteSmbOpen`)
- **What:** The rule is a machine-wide firewall change. Every file share the
  machine already serves to the LAN stops working, not just the loopback
  CCSync share: a render-output folder, a printer share, a share used by the
  customer's backup or asset system. The only opt-out is a hand-run flag that
  the wizard never exposes, and the wizard's pages and finish page say nothing
  about it.
- **Scenario:**
  1. A studio's IT has an editing workstation that shares `D:\Exports` to the
     colourist's machine.
  2. After onboarding CC Sync, the colourist gets "network path not found".
     Nothing on the editor's machine names CC Sync as the cause.
  3. On a domain machine, Group Policy may also override or fight the rule.
- **Recommendation:**
  - Scope the rule to the CCSync share's purpose only. One option is to skip
    the share entirely, since subst plus `_LabelFromReg` is the only reason
    for it.
  - Otherwise, before adding the rule, detect existing non-default shares
    (`Get-SmbShare | ? Special -eq $false`), and ask in the wizard or report
    it on the finish page.
  - Document it for customer IT in the install notes.
- **Known:** COMMERCIAL_READINESS item 15 introduced the rule deliberately; the side effect is not recorded.

### bug-installer-8 - The wizard and the uninstaller skip their schtasks "not found" check on non-English Windows

- **Severity:** low
- **Confidence:** CONFIRMED (code read)
- **Where:** `onboarding/steps.py:3184-3203`
- **What:** `schtasks /Delete` failures are classified by matching English
  substrings in stderr: "cannot find", "does not exist", "access", "denied".
  On a German, French or Chinese Windows every missing-task case lands in the
  generic `else` branch, and the logged text is mangled. The
  `CAPTURE_TEXT_KWARGS` decode is UTF-8, but schtasks writes the OEM codepage.
- **Scenario:** A German editor's install log shows "WARNING: schtasks
  /Delete CCSync-SubstP failed: FEHLER: Das System kann die angegebene Datei
  nicht finden" for both task names on every install. A real access-denied
  failure loses its targeted fix-it command.
- **Recommendation:**
  - Query with `schtasks /Query /TN <task>` first: its exit code means
    "exists".
  - Or use `Get-ScheduledTask` through PowerShell.
  - Do not parse localized text.
- **Known:** not recorded.

### bug-installer-9 - The macOS default uninstall deletes the Syncthing device identity; the Windows default keeps it

- **Severity:** low
- **Confidence:** CONFIRMED (code read)
- **Where:** `installer/macos_uninstall.sh:242-256` vs `installer/windows_uninstall.ps1:798-806`
- **What:**
  - On Windows, the default mode keeps `syncthing-config` so the admin does
    not have to re-approve, and only `-Full` removes it.
  - On macOS, the default mode `rm -rf ~/.local/ccsync`, which includes
    `syncthing-config`.
  - The wizard's macOS clean-slate deliberately never touches the identity.

  So "uninstall, then reinstall" behaves differently on the two platforms, and
  the macOS script's own header says the default keeps "your sign-in and
  settings".
- **Scenario:** A Mac editor uninstalls to fix a problem and reinstalls. The
  device ID changes, the admin must approve a new device, and lane C stalls in
  the meantime (the stuck-lane-C shape).
- **Recommendation:** Keep `~/.local/ccsync/syncthing-config` unless `--full`,
  as Windows does, and print the same KEPT line.
- **Known:** not recorded.
