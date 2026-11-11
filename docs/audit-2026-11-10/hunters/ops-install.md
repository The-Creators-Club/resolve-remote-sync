# ops-install - editor install, upgrade, uninstall and the first-run wizard (installer/ + onboarding/)
Files read (approximate coverage): installer/windows_bootstrap.ps1 (~45%: header, sections 0-3, 5, 6-10 in full), installer/macos_bootstrap.sh (~30%: manifest fetch, sections 1-3, Syncthing seeding, 6-7, Resolve waits), installer/windows_upgrade.ps1 (steps 1-5b in full), installer/build_editor_package.ps1 (~40%: params, rebuilds, file list, staleness checks, publish head), installer/windows_uninstall.ps1 (grep only), onboarding/onboard.py (~35%: UI pump, install page, both workers, close handler), onboarding/steps.py (~25%: bootstrap runner/streaming, run_bootstrap, clean slate (Windows), validate_local_root, install log, launch_companion, Resolve scripting, site manifest helpers), onboarding/build_onboard.spec (full). Cross-read: companion state_acl.py, upgrade.py `_default_spawn`, rclone_lane.rclone_available.
Probes run: (1) `icacls <dir> /inheritance:r /grant:r ...` + `icacls <dir>\* /reset /T /C /Q` on a synthetic 50-dir / 5,000-file tree in my scratch folder: grant 266 ms, recursive reset 555 ms. (2) Cold `powershell -NoProfile -Command exit 0`: 194 ms. Nothing was run against ~/.ccsync, %LOCALAPPDATA%\ccsync or any installer.

## Findings

### ops-install-1 - The bootstrap re-fetches the site manifest the wizard already holds, and three keys come ONLY from that second fetch
- Category: bug
- Severity: medium
- Confidence: CONFIRMED (code path; the trigger is a failed second fetch)
- Where: installer/windows_bootstrap.ps1:870-879 (unconditional `Invoke-RestMethod .../api/v1/site -TimeoutSec 8`), :2154-2162 and :2173 (`rclone_remote`, `sftp_shell_type`, `sftp_hostkey` read only via `Get-SiteValue`); installer/macos_bootstrap.sh:302 (same fetch), :442, :2294, :2303; onboarding/steps.py:1909-1992 (run_bootstrap passes remote_root, nas id, port, canonical_prefix, tree_name - never the other three); onboarding/steps.py ensure_config (writes `remote` from the wizard's site, falling back to the CACHED manifest)
- What: run_bootstrap's own comment says passing manifest values "keeps ONE fetch per install", but both bootstraps fetch `/api/v1/site` again unconditionally, and the rclone remote NAME, the SFTP shell type and the NAS SSH host-key pin (GL-19 / CR-368) have no flag, so they come only from the bootstrap's fetch. install-onboard-2 (2026-09-11) closed exactly this class for canonical_prefix/tree_name and left these three open.
- Cost / failure scenario: wizard signs in and fetches the manifest (remote = the site's name, e.g. not `ccsync_sftp`); minutes later the bootstrap's 8 s fetch fails (dashboard restarting, tailnet blip). config.toml gets `remote = "<site name>"` from ensure_config, rclone.conf gets `[ccsync_sftp]` - every lane A/B pass fails with "didn't find section in config file" on a machine the install reported green - and the stanza is written with NO `known_hosts_file`, i.e. the editor's lanes trust any host key until someone re-runs the installer. Every install also pays one extra round trip (up to 8 s on a slow tailnet).
- Evidence: the param block (windows_bootstrap.ps1:140-224) has no RcloneRemote/SftpShellType/SftpHostKey; run_bootstrap builds argv/env without them; the fetch at :872 is not conditional on any flag.
- Ledger: new (same class as install-onboard-2, which was fixed for two keys only)
- Suggested change: hand the bootstrap the manifest the wizard already has (e.g. `CCSYNC_SITE_JSON` in the child environment, read by both scripts in place of their own fetch when present; hand-runs keep fetching). Must not break the hand-run path or the "flag wins over manifest" order.
- Effort / risk: S effort; low risk

### ops-install-2 - Windows and macOS bootstraps implement the same eight steps twice and have drifted; the drifted ones are cheap to move into the companion CLI like --setup-resolve-prefs already was
- Category: streamline
- Severity: medium
- Confidence: CONFIRMED (each drift read in both files)
- Where: installer/windows_bootstrap.ps1 (manifest 857-1000, rclone 1213-1360, Syncthing 1363-1446, device seeding 1952-2037, rclone stanza 2144-2300, config seed 2303-2462, companion 2465-2615) vs installer/macos_bootstrap.sh (manifest 290-450, rclone 1731-1823, Syncthing 1826-2077, seeding 2079-2133, stanza 2286-2417, companion 2420-2669, config 2672-2812)
- What: drift found, each one a behaviour difference an editor would see:
  1. Companion "already current?": Windows compares size + `LastWriteTimeUtc -gt` (:2478-2481), so a same-size different build with an older mtime (a rollback package) is skipped; macOS compares sha256 (:2512).
  2. Replacing a RUNNING companion: macOS boots the agent out first (:2520-2522); Windows `Copy-Item` over the live exe unguarded under EAP=Stop (:2490) - see ops-install-5.
  3. Syncthing REST wait: Windows 20 x (Invoke-RestMethod -TimeoutSec 3 + Start-Sleep 1) = up to 80 s while the warning says "within 20s" (:1989-2009); macOS 10 x 1 s (:2098-2107) plus a fixed `sleep 2` before a pgrep check (:2070) that the ping loop makes redundant.
  4. Temp files: macOS stages downloads in `mktemp -d` with a trap; Windows leaves zips + extract dirs in %TEMP% (ops-install-4).
  5. Launch order: Windows seeds/repairs config.toml (section 8) BEFORE launching the companion (section 9); macOS loads the companion agent (6a, :2661) BEFORE repairing `rclone_path` (6b, :2703-2725). In the wizard flow the config holds `rclone_path = "rclone"` until 6b, and lanes bake `rclone_path` at construction (companion app.py:2770), so a companion that reads its config before bash reaches 6b (tens of ms) runs lanes A/B against a bare name launchd cannot resolve (INST-7) until its next restart. PLAUSIBLE race, usually won by bash.
  6. Post-launch liveness: Windows waits 3 s and checks the PID (:2600-2609); macOS reports "loaded companion LaunchAgent" with no check that it stayed up.
  7. Pinned versions + sha256s are duplicated (`$RcloneVersion`/`RCLONE_VERSION` etc., ps1:331-334, sh:79-82) with no parity test (INSTALLER_VERSION has one).
  The wizard already writes config.toml first (ensure_config), so both scripts' config-SEEDING blocks (~160 + ~140 lines) are dead in the wizard flow and live only for hand-runs.
- Cost / failure scenario: every fix lands twice (MAC-9, INST-7, GL-28, CR-372 all had two halves); the list above is what slipped. Lines that could leave both scripts for one Python implementation in the companion (precedent: `--setup-resolve-prefs`, chosen "so there is ONE implementation ... rather than a second one in PowerShell and a third in bash"): manifest resolution, pinned download + sha256 verify (Python could also fetch rclone and Syncthing in parallel), rclone stanza write/rewrite, Syncthing device seeding, config seed + rclone_path repair, device-ID parse. Estimated ~750 lines out of windows_bootstrap.ps1 and ~650 out of macos_bootstrap.sh; drive mapping/SMB/UAC (Windows) and LaunchAgents/Mapped Mount/SSD checks (macOS) stay native.
- Evidence: line references above.
- Ledger: new (individual drifts not in KNOWN_BUGS; MAC-9/INST-7/GL-28 are the precedents)
- Suggested change: first the cheap parity fixes (sha256 on Windows, one wait helper with the same bound, launch after config repair on macOS, a parity test for the pins); then add `ccsync-companion --setup-rclone-remote / --seed-syncthing-device / --install-tools` subcommands both scripts call, so hand-runs keep working. Must keep the scripts runnable standalone from the package.
- Effort / risk: S for the parity fixes, L for the consolidation; low / medium risk

### ops-install-3 - macOS install waits for Resolve to quit twice, back to back, each up to 180 s
- Category: perf
- Severity: low
- Confidence: PLAUSIBLE (depends on bug-resolve-5, open)
- Where: installer/macos_bootstrap.sh:1622-1624 (run_resolve_mapping -> wait_for_resolve_quit), :1494 (run_resolve_prefs -> wait_for_resolve_quit again), :575 (180 s default), :1450-1467 (3 s poll)
- What: when the first wait times out (the editor kept Resolve open), the second step starts its own full 180 s wait, which will almost always time out the same way.
- Cost / failure scenario: once per Mac install with Resolve open: 3 extra minutes of dead time on a page that says "this will continue automatically". Today `pgrep -x "DaVinci Resolve"` may never match (bug-resolve-5, open), in which case neither wait happens and both edits run under a live Resolve; fixing bug-resolve-5 turns this on.
- Evidence: both call sites, no shared "already timed out" state.
- Ledger: related to bug-resolve-5 (open)
- Suggested change: record the first wait's verdict and skip the second wait (go straight to the "the companion applies them later" branch) when it already timed out. Fix together with bug-resolve-5.
- Effort / risk: S; low

### ops-install-4 - The Windows pinned download leaves ~130 MB of zips and extracted folders in %TEMP% on every install that downloads
- Category: disk-growth
- Severity: low
- Confidence: CONFIRMED
- Where: installer/windows_bootstrap.ps1:783-816 (`Install-PinnedBinary`)
- What: `$env:TEMP\<slug>-<ver>.zip` and `$env:TEMP\<slug>-extract` are created and never removed (only the extract dir is cleared at the START of the next call). Nothing in the uninstaller knows about them. The macOS twin uses a `mktemp -d` stage dir with a cleanup trap.
- Cost / failure scenario: once per fresh install (and per re-run that needs the download): rclone zip ~23 MB + extracted ~65 MB, Syncthing zip ~13 MB + extracted ~30 MB, about 130 MB (estimated from release sizes) left until the editor cleans %TEMP%. A re-run also re-downloads even when the verified zip is still sitting there.
- Evidence: no `Remove-Item` of `$zipPath`/`$extractDir` after the copy (grep for zipPath/extractDir: lines 783-810 only).
- Ledger: new
- Suggested change: `try/finally` removing both after the copy (or a per-run `New-Guid` stage dir under %LOCALAPPDATA%\ccsync\elevate-style ACL'd folder). Optional: reuse an existing zip that passes `Test-PinnedDownload`.
- Effort / risk: S; low

### ops-install-5 - A hand re-run of windows_bootstrap.ps1 with -CompanionExeSource aborts at step 9 while the companion is running
- Category: bug
- Severity: low
- Confidence: CONFIRMED (Windows refuses to overwrite a running image; the copy is outside any try)
- Where: installer/windows_bootstrap.ps1:2490 (`Copy-Item -LiteralPath $CompanionExeSource -Destination $CompanionExePath -Force`), :225 / :1740 (`$ErrorActionPreference = "Stop"`)
- What: the script is documented "safe to re-run"; on a machine whose companion is running and the bundled exe differs in size/mtime, the copy throws "being used by another process", which is terminating. Autostart registration, the Resolve prefs step, the launch, the device-ID print and the exit-3 capability summary never run. The wizard path is not affected (its clean slate kills and deletes the exe first).
- Cost / failure scenario: an admin re-running the package's bootstrap by hand on a live editor machine (the documented repair path) gets a red PowerShell error halfway through with no summary; the exit code is not 3, so it reads as a hard failure.
- Evidence: macOS twin stops the agent first (macos_bootstrap.sh:2520-2522); windows_upgrade.ps1 kills + renames aside + retries for exactly this reason (:179-254).
- Ledger: new
- Suggested change: same shape as windows_upgrade.ps1: stop the running companion (and only then), rename the live exe aside, copy, and catch/warn on failure.
- Effort / risk: S; low

### ops-install-6 - windows_upgrade.ps1 runs a full recursive ACL reset inside the companion-down window, every upgrade, while the companion repeats the job only when needed
- Category: perf
- Severity: low
- Confidence: CONFIRMED (mechanism); cost MEASURED on a synthetic tree, size of a real ~/.ccsync estimated
- Where: installer/windows_upgrade.ps1:456-475 (`Repair-CCSyncStateAcl`, unconditional `icacls ~/.ccsync\* /reset /T`), :483-502 (two more icacls), between the kill (:184) and the relaunch (:530); also :193 fixed `Start-Sleep -Milliseconds 800` ahead of a copy that already retries
- What: the tray is down from step 1 to step 5; between them the script re-grants ~/.ccsync and resets every file under it (crashes/, logs/, state/, resolve_edits/ ...), then icacls's two files. companion state_acl.repair_if_needed already does a bounded probe at start and repairs only on a denial, so the upgrade's pass is redundant for every companion that carries it.
- Cost / failure scenario: once per manual upgrade per machine: grant 0.27 s + reset 0.55 s per 5,000 files (measured) + ~0.2 s for the two secret files + 0.8 s fixed sleep, all added to tray downtime (~2-3 s of script work total). Small today; grows with the size of ~/.ccsync.
- Evidence: probe numbers above; the companion's module docstring (state_acl.py:12-17) says the installers' repair exists for machines that never run the companion's.
- Ledger: related to CR-144 (open suggestion about the same Stop-Process upgrade path)
- Suggested change: move the ACL repair and the secret-file tightening AFTER the relaunch-and-confirm (step 5) - they are best-effort and need no downtime - or gate the recursive reset on the same denied-file probe. Replace the 800 ms sleep with `Wait-Process` on the killed PIDs (timeout 5 s). Must keep the repair for pre-state_acl companions.
- Effort / risk: S; low

### ops-install-7 - build_editor_package's "onboard.exe is up to date" check ignores four of the files bundled into onboard.exe
- Category: deploy
- Severity: low
- Confidence: CONFIRMED
- Where: installer/build_editor_package.ps1:870-887 (`$onboardInputs` = onboarding/*.py + windows_bootstrap.ps1 + companion exe), :39-44 (param doc says the same three); onboarding/build_onboard.spec datas (also drive_mapping.ps1, windows_uninstall.ps1, assets/EULA.md, THIRD_PARTY_LICENSES.txt, THIRD_PARTY_NOTICES.md, ccsync-release.json)
- What: a change to drive_mapping.ps1 (the bootstrap dot-sources it for the drive-ownership check) or windows_uninstall.ps1 (installed as the Apps & features uninstaller) prints "onboard.exe is newer than all of its inputs -- up to date" while the package beside it carries the NEW loose copies - the wizard and the loose scripts then disagree.
- Cost / failure scenario: only on a run without -RebuildOnboard (ship.cmd and CI rebuild every time); new editors get the old uninstaller / drive-mapping guard with a green report.
- Evidence: spec datas list vs `$onboardInputs`.
- Ledger: new
- Suggested change: build `$onboardInputs` from the same list the spec uses (or glob installer\*.ps1 + onboarding\assets + the licence files).
- Effort / risk: S; low

### ops-install-8 - The base-rig wizard path never switches on Resolve's External scripting and never sets the LUT/stills prefs
- Category: bug
- Severity: low
- Confidence: CONFIRMED
- Where: onboarding/onboard.py:1714-1774 (`_worker_base`: no `steps.enable_resolve_scripting()`, no `--setup-resolve-prefs`) vs :1696-1705 (editor worker); finish page :1950 shows the checklist with `resolve_scripting` unset, so it always tells the base user to do it by hand
- What: CR-373 / GL-29 wrote the scripting preference only on the editor path. The base rig is the machine that runs Resolve for the Cards agent and the fixer, both of which need External scripting = Local.
- Cost / failure scenario: every base-rig install: one manual Resolve preference the wizard could have written, and a companion whose watcher/fixer is silent until it is done.
- Evidence: the two worker bodies.
- Ledger: related to CR-373 (fixed for editors)
- Suggested change: call `enable_resolve_scripting()` in `_worker_base` after the companion install (it already refuses safely while Resolve runs and never touches the scripting API).
- Effort / risk: S; low

### ops-install-9 - Locked exe copies renamed to `.stale-<epoch>` by the clean slate are never pruned
- Category: disk-growth
- Severity: low
- Confidence: CONFIRMED
- Where: onboarding/steps.py:3359-3365 (`os.replace(path, path + ".stale-<ts>")`); COMPANION_FILE_NAMES (:522-526) and every later cleanup omit the pattern; repo-wide grep finds no other reference
- What: each wizard run that meets a locked companion exe (AV scan, lingering handle) leaves a ~48 MB `.stale-<ts>` beside it, under %LOCALAPPDATA%\ccsync\bin, the local root or the tree drive root; the next run cannot see it and adds another.
- Cost / failure scenario: rare per run, unbounded over re-runs: 48 MB each; the uninstaller removes the bin dir but not copies under the local root.
- Evidence: grep for `stale-` (steps.py:3360 and one test only).
- Ledger: new
- Suggested change: add a `*.stale-*` glob for the same candidate dirs to build_cleanup_plan's exe list (delete if unlocked now, leave otherwise).
- Effort / risk: S; low

## What is already good
- The bootstrap child is streamed line by line with a watchdog thread and killed as a process group on close or timeout (steps.py:1747-1865); the worker->Tk handoff is a main-thread queue pump, so no Tk call ever happens off the UI thread.
- Pinned downloads are hash-verified BEFORE extraction, with progress rendering switched off and a per-request timeout (windows_bootstrap.ps1:786-812); this is already the fast path in PS 5.1.
- windows_upgrade.ps1 keeps the replaced build (`.prev`), retries the copy, confirms the relaunch by PID and rolls back on a dead start; the `.prev`/`.failed` copies are single fixed names, so they do not accumulate.
- The companion's start-up ACL probe (state_acl.py) is bounded at 400 entries and repairs only on a denial: leave it alone; it is the reason the installers' unconditional pass can move off the critical path.
- The share helper is per-run, ACL'd and deleted in `finally`; re-runs reuse an existing correct share and never raise a second UAC prompt.

## Coverage note
Not read in depth: macos_bootstrap.sh sections 4-5 (SSD ghost-directory checks, Mapped Mount helper), windows_bootstrap.ps1 sections 1a and 5b, the macOS uninstaller, windows_uninstall.ps1 beyond a grep, build_editor_package.ps1's publish/signing tail, onboard.py pages before the install page, steps.py macOS clean slate and the EULA/privacy helpers. Not measured: a real fresh-install wall clock (not allowed on this machine); the time split above is from reading (Tailscale winget and the Resolve-quit wait dominate; downloads ~10-20 s; the companion confirm is a fixed 3 s). Not raised for lack of proof: the per-keystroke local-root probe on the Tk thread (Path.exists + disk_usage on every edit; can stall on a disconnected network letter, base role only) and the onefile onboard.exe extracting its 48 MB companion copy to %TEMP% on every launch.

## OUT OF TERRITORY
- dashboard package store: every release stores the companion twice (the windows package ~48 MB and onboard.exe ~61 MB which embeds it); check that `<data>/packages` prunes old versions, not only deletes to .trash.
- companion/src/ccsync_companion/app.py:2770: lanes bake `rclone_path` at construction; a config change (installer repair, Settings) needs a restart to take effect.
