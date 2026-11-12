# Editor machines: the installers, upgrade and uninstall scripts, and the first-run wizard

Terms used throughout:

- **Editor machine**: a Windows or macOS computer an editor cuts on.
- **Companion**: the CC Sync tray app installed on an editor machine (`ccsync-companion.exe` on Windows, `CC Sync.app` on macOS).
- **Dashboard**: the CC Sync web server on the NAS that every editor machine reports to.
- **Site manifest**: the unauthenticated JSON answer of the dashboard at `GET <dashboard>/api/v1/site`, carrying the site's settings (tree name, drive prefix, NAS paths, Syncthing device ID, SSH host key, brand names, feature flags). The installers and the wizard read it; it carries no secrets.
- **Tree**: the shared project folder tree. **Tree drive**: the drive letter (Windows, default `P:`) or mount path (macOS, default `/Volumes/<tree name>`) under which every clip path in DaVinci Resolve's database points into the tree. **Canonical prefix**: that drive letter or mount path as the site manifest publishes it.
- **Local root**: the folder on the editor machine that holds this machine's copy of the tree.
- **Lane A / lane B / lane C**: the three sync paths. Lane A uploads video originals (rclone over SFTP), lane B downloads proxies (rclone over SFTP), lane C syncs everything else (Syncthing).
- **Fleet token**: the credential a companion uses to report to the dashboard.
- **Capability miss**: a required piece the installer could not set up; it is printed as `CAPABILITY MISSING: <text>` and makes the run end "not ready".
- **Wizard**: the first-run onboarding program (`onboard.exe` on Windows, `CC Sync Setup.app` on macOS).
- **Wired** role (the wizard calls it "base" internally): a computer physically connected to the NAS that works straight off it; **remote** role: a computer that keeps its own local copy and syncs.

## Windows bootstrap: inputs and refusals before anything changes
(source: installer/windows_bootstrap.ps1, installer/drive_mapping.ps1)

- Runs under Windows PowerShell 5.1 or later. Idempotent: every step checks the current state, prints what it did or skipped, and can be re-run.
- Does NOT join the tailnet (`tailscale up`) and does NOT generate SSH keys.
- Is intended to be run unelevated (normal PowerShell window). Exactly one step asks for administrator rights through a single UAC prompt (creating the loopback share plus its firewall rule).
- Every line it prints is prefixed `[ccsync] `. Skips print `[ccsync] SKIP: ...` (grey); warnings `[ccsync] WARNING: ...` (yellow); capability misses `[ccsync] WARNING: CAPABILITY MISSING: ...` (red).
- When its output is redirected (the wizard captures it), it forces UTF-8 output; on an interactive console it leaves the console encoding alone.
- Forces TLS 1.2 for downloads; if that fails it warns "could not force TLS 1.2 on this .NET runtime; direct downloads may fail on older Windows".
- Installer version printed and registered: `1.0.47`. One installer version number is shared by this script, the macOS bootstrap and the wizard.
- Parameters:
  - `-TailnetHost` (required): NAS hostname or IP on the tailnet. Written into the rclone remote as `host`, used as the Syncthing NAS address and as the known-hosts host.
  - `-EditorName` (required): the editor's NAS username. Trimmed and lowercased; when that changes the value it warns "normalized -EditorName '<raw>' -> '<new>' (unix usernames are case-sensitive ...)".
  - `-LocalRoot` (default empty): local root. Resolved in order: the flag; the `local_root` line of an existing `%USERPROFILE%\.ccsync\config.toml` (prints "local root from your existing config.toml: ..."); `%SystemDrive%\<tree name>` (prints "no -LocalRoot given -- using ...").
  - `-RemoteRoot` (default empty): absolute NAS path of the tree. Flag, else the manifest's `remote_root`.
  - `-DriveLabel` (default empty): Explorer name for the tree drive. Flag, else the tree name.
  - `-CanonicalPrefix` (default empty): flag, else manifest `canonical_prefix`, else `P:\`.
  - `-TreeName` (default empty): flag, else manifest `tree_name`, else `CCSync`.
  - `-CompanionExePath` (default `%LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe`): where the companion lives and runs.
  - `-CompanionExeSource` (default empty): a companion exe to copy into place. Blank means do not install one.
  - `-ResolvePrefsWaitSeconds` (default `180`): how long the Resolve preference step waits for an open Resolve to be quit. `0` skips the wait.
  - `-DashboardUrl` (default empty, effectively required): falls back to the environment variable `CCSYNC_DASHBOARD_URL`. Trailing `/` stripped.
  - `-DashboardToken` (default empty): fleet token. When blank, the environment variable `CCSYNC_DASHBOARD_TOKEN` is used. That environment variable is then cleared in every case so nothing the script launches inherits it.
  - `-SftpPort` (default `0`): `0` means manifest `sftp_port`, else `22`.
  - `-NasSyncthingId` (default empty): flag, else environment variable `CCSYNC_NAS_SYNCTHING_ID`, else manifest `nas_syncthing_id`.
  - `-KeepRemoteSmbOpen` (switch): do not add the inbound SMB block firewall rule.
  - `-DryRun` (switch): print what would happen; installs and writes nothing (read-only probes still run).
- Other environment variables read:
  - `CCSYNC_UNINSTALL_KEY_ROOT`: overrides the registry root of the Apps & features entry (default `HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall`). Test hatch.
  - `CCSYNC_RCLONE_REMOTE`, `CCSYNC_SFTP_SHELL_TYPE`, `CCSYNC_SFTP_HOSTKEY`: rclone remote name, SFTP shell type, NAS SSH host key; each wins over the manifest (the wizard sets them).
  - `CCSYNC_FROM_WIZARD`: `1` changes the closing "remaining steps" text (see below).
- Refusals, in order (each exits before changing anything relevant):
  - Wrong account: the signed-in console user (from the system's console user name, else the owner of `explorer.exe`) is compared, case-insensitively and with domain or `@` suffix stripped, with the running user. On a mismatch it prints "You are running as <running> but <signedIn> is signed in. Everything this installs is per-user, so <signedIn> would get nothing. <signedIn> does not need to sign in again: close this window and run the script again from a PowerShell window opened normally in <signedIn>'s session, not through Run as administrator or with another account's password (it does not need administrator rights)." then "Nothing on this computer has been changed." and exits `2`. If the console user cannot be read, it warns and continues.
  - `drive_mapping.ps1` missing beside the script: prints an error telling the user to download the package again, exits `1`.
  - No dashboard URL: prints "ERROR: no -DashboardUrl." plus an explanation, exits `2`.
  - Canonical prefix is not a drive-letter path (a UNC path, a POSIX path, a bare letter without a colon): prints "ERROR: canonical_prefix is '<value>', which is not a drive-letter path." and exits `2`. It never falls back to `P:` in that case.
  - Local root contains a double quote: prints an error and exits `2`.
  - Tailscale not installed and `winget` absent: warns "winget not available. Download and install Tailscale manually from https://tailscale.com/download/windows then re-run this script." and exits `1`.
- Site manifest fetch: `GET <dashboard>/api/v1/site`, 8 s timeout. Failure (404 on an old dashboard, or unreachable) is a warning "no site manifest from <url> (...) -- using the values passed on the command line"; every manifest-derived value then uses flags or fallbacks.
- Manifest keys this script reads: `remote_root`, `nas_syncthing_id`, `sftp_port`, `tree_name`, `canonical_prefix`, `org_name`, `rclone_remote`, `sftp_shell_type`, `sftp_hostkey`.
- Low free space warning (never a refusal): if the volume holding the local root (walking up to the first existing parent) has less than 200 GB free, warns "This drive has <N> GB free. Synced proxies for one project are typically 50 to 300 GB. Sync will still be set up here; keep an eye on the drive, or re-run with -LocalRoot pointing at a bigger one." Says nothing when free space cannot be measured.
- Remote root checks (capability misses, not refusals):
  - Empty: miss "the NAS project-tree path is not known: ... Lanes A and B have nowhere to sync to ...".
  - Not starting with `/`: miss "-RemoteRoot '<value>' is not an absolute path, so nothing was configured for upload and proxy download. ..." and the value is dropped.
- Elevation: when running elevated it prints four warnings that drive letters mapped from an elevated window are invisible to the normal session and that it will try to map at the normal integrity level. Unelevated it prints "running unelevated -- will fall back to an HKCU Run entry if scheduled-task registration is denied".
- Prints "installer v<version> -- configuring for editor '<name>', local root '<root>', NAS '<host>'".

## Windows bootstrap: the steps, in order
(source: installer/windows_bootstrap.ps1, installer/drive_mapping.ps1)

- **Bin folder**: creates `%LOCALAPPDATA%\ccsync\bin` if missing.
- **Uninstaller and Apps & features entry** (step 1a):
  - Copies `windows_uninstall.ps1` and `drive_mapping.ps1` from beside the script into the bin folder. If the uninstaller is not beside the script (a bare script run), no copy and no entry. Copy failure warns "could not copy windows_uninstall.ps1 into <bin> (...). Keep the installer package: it is the only other copy."
  - Writes the per-user uninstall registry entry `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\CCSync` (same id every version, so a re-run overwrites): `DisplayName` = `CC Sync (<org_name>)` when the manifest publishes `org_name`, else `CC Sync`; `UninstallString` = `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<bin>\windows_uninstall.ps1"`; `Publisher` = `Cablewrap Creative Ltd`; `DisplayVersion` = installer version; `InstallLocation` = bin folder; `DisplayIcon` = companion exe (only if it exists); `NoModify` = 1; `NoRepair` = 1.
  - Success prints "CC Sync is listed in Apps & features (Settings > Apps > Installed apps)"; failure warns with the manual uninstall command line.
  - After the companion exe is in place (step 9), the icon value is set if the entry exists (so a first install also gets an icon).
- **Tailscale** (step 1): skipped if `tailscale` is on PATH or `%ProgramFiles%\Tailscale\tailscale.exe` exists. Otherwise `winget install --id Tailscale.Tailscale -e --accept-source-agreements --accept-package-agreements`; a non-zero exit only warns. No winget: refusal above (exit 1).
- **rclone** (step 2):
  - Already installed if `<bin>\rclone.exe` exists, or `rclone` is on PATH outside winget's versioned `WinGet\Packages\` folder. A copy only inside that versioned folder is kept as a last resort.
  - Otherwise, in order: the pinned download (rclone `v1.75.0`, `https://downloads.rclone.org/v1.75.0/rclone-v1.75.0-windows-amd64.zip`, sha256 `203581f0...89ac0`); then `winget install --id Rclone.Rclone -e ... --disable-interactivity`; then `scoop install rclone`; then the versioned winget copy with a warning that it moves on the next winget upgrade.
  - Pinned download rules (same for Syncthing): download to `%TEMP%\<slug>-<version>.zip` with a 600 s timeout; sha256 of the archive checked against the hardcoded value BEFORE unzipping; on mismatch prints "CHECKSUM MISMATCH for <what>" with expected and actual digests and "The download was NOT installed and has been deleted. ..." and deletes the file; the exe is copied into the bin folder.
  - After winget or scoop, the script reloads PATH from the registry and looks in `%LOCALAPPDATA%\Microsoft\WinGet\Links\` first.
  - Adds the bin folder to the user PATH if absent. When the existing user PATH contains `%VAR%` references it writes the registry value directly, preserving its expandable type ("log off and back on to pick it up"); otherwise it sets it normally ("restart your terminal to pick it up"). Failure warns with manual instructions.
  - Adds the bin folder to this session's PATH too, so the companion launched later finds rclone.
  - Final check: if no rclone can be found, capability miss "rclone is NOT installed. Lanes A and B -- every video upload and every proxy download -- cannot run at all on this machine. ...".
- **Syncthing** (step 3):
  - Already installed if found at, in order: `<bin>\syncthing.exe`; `syncthing` on PATH outside the versioned winget folder; `WinGet\Links\syncthing.exe`; `%ProgramFiles%\Syncthing\syncthing.exe`; `%ProgramFiles(x86)%\Syncthing\syncthing.exe`.
  - Otherwise: the pinned download (Syncthing `v2.1.3`, GitHub release asset `syncthing-windows-amd64-v2.1.3.zip`, sha256 `c0b79cff...a21`); then `winget install --id Syncthing.Syncthing ...`; then any versioned winget copy, with a warning.
  - None found: capability miss "Syncthing is NOT installed. Lane C -- audio, After Effects projects, graphics, subtitles, .drp project files and docs -- will never sync on this machine. ...".
- **Local root** (step 4): creates the local root folder if missing.
- **"Is the tree drive ours?" check** (before step 5, also in a dry run):
  - Reads the current user's `subst` and `net use` output for the drive letter (through a one-shot scheduled task at normal integrity when elevated).
  - Ours: a `subst` mapping, or a `net use` mapping to `\\localhost\CCSync_<letter>`. Not mapped: free to map.
  - Anything else, including disconnected or "Unavailable" persistent mappings, and including "could not read the mappings", is treated as somebody else's. The script prints "ERROR: <drive> is already mapped to '<target>' -- that is not a mapping this installer created." plus advice (disconnect it in Explorer and re-run; on the base rig use the BASE role), skips the whole drive section and the Explorer label, and records a capability miss. Two wordings: foreign target ("... Disconnect it yourself (Explorer > This PC > right-click <drive> > Disconnect) and re-run this installer, or ask your admin. If this machine works straight off the NAS, run the wizard again and pick 'I'M PHYSICALLY CONNECTED TO THE SERVER/NAS' instead ...") and undetermined ("... this logon session would not report its drive mappings ... Sign out and back in, then re-run this installer ...").
- **Tree drive mapping** (step 5), only when the drive is ours:
  - Tear-down first, every run: removes scheduled task `CCSync-Subst<letter>` (on failure tells the user to run `schtasks /Delete /TN CCSync-Subst<letter> /F` in an admin prompt), removes the Run value `CCSyncSubst<letter>` and its `.cmd`/`.vbs` shims in the bin folder, runs `subst <drive> /D` and `net use <drive> /delete /y`.
  - Preferred: a loopback SMB share named `CCSync_<letter>` pointing at the local root, full access granted only to the current user, mapped with `net use <drive> \\localhost\CCSync_<letter> /persistent:yes` (restores itself at logon with no task).
    - Share already exists pointing at the local root: reused. If the firewall rule is missing: added when elevated; otherwise a warning prints the exact `New-NetFirewallRule` command to run as administrator.
    - Elevated: removes a stale share of that name pointing elsewhere, creates the share, adds the firewall rule.
    - Unelevated: writes a one-off helper script `%LOCALAPPDATA%\ccsync\elevate\make_share_<random>.ps1` (folder and file restricted to the user, SYSTEM and Administrators), runs it once through a UAC prompt ("creating the '<share>' share needs administrator rights -- approve the UAC prompt..."), deletes it afterwards whether or not the prompt was approved. The helper creates the share and the firewall rule in the same elevated trip.
    - UAC declined or share failure: falls back to `subst` ("... falling back to subst (<drive> will show the host volume's name in Explorer)").
  - Fallback: `subst <drive> "<local root>"` now, plus a logon scheduled task `CCSync-Subst<letter>` (trigger: at logon; runs `cmd.exe /c subst ...` as the user). If task registration is denied, a hidden HKCU Run entry `CCSyncSubst<letter>` instead. If both fail, warns that the drive will not come back at logon and to run the subst command by hand, and NOT to re-run as administrator.
  - Hidden Run entries (used for the subst fallback and Syncthing): a `.cmd` file (written in the console OEM codepage) holding the command, launched by a one-line `.vbs` file (system ANSI codepage) via `wscript.exe`, so no console window flashes at logon. Run value = `wscript.exe "<bin>\<name>.vbs"`. If a path cannot be represented in that codepage, it warns that autostart may be silently broken.
  - When elevated, every mount or unmount is run through a one-shot scheduled task `CCSync-OneShot-<8 hex>` at the user's normal integrity level (polled every 0.5 s for up to 30 s, then removed). If that fails it runs in the elevated session and, at the end of step 5, prints a red block: "<drive> HAD TO BE MAPPED FROM THIS ELEVATED WINDOW. ... LOG OFF AND BACK ON (or restart) BEFORE OPENING RESOLVE. ... Do not re-run this installer to 'fix' it ...".
- **Firewall rule** `CC Sync: block remote SMB (tree share is loopback-only)`: inbound block, TCP 139 and 445, any remote address, all profiles. Re-created (removed and added) each time it is set. Skipped with `-KeepRemoteSmbOpen` ("... NOT blocking remote SMB. This machine serves '<share>' (your whole project tree) to any network it joins."). Failure warns with what to do by hand.
- **Explorer label** (step 5b): only for a `net use` mapping. Writes `_LabelFromReg` = drive label under `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\MountPoints2\##localhost#CCSync_<letter>` (creates the key only if missing), then asks Explorer to refresh. Already labelled: skip. For a `subst` mapping it warns that Explorer will show the host volume's name and that re-running unelevated and approving the UAC prompt gives the nicer name. Skipped entirely when the drive is not ours. Never restarts Explorer.
- **Syncthing daemon** (step 6):
  - Syncthing home: `%LOCALAPPDATA%\ccsync\syncthing-config`. Runs `syncthing generate --home=...` if that folder does not exist.
  - Autostart: hidden HKCU Run entry `CCSyncSyncthing` running `"<syncthing>" serve --no-browser --home="<home>"`. If the entry exists but its `.cmd` does not name the currently found Syncthing exe, it is rewritten ("Syncthing autostart exists but its command line does not point at ... -- rewriting it").
  - Starts `syncthing serve --no-browser` hidden now unless a `syncthing` process is already running.
  - NAS device seeding (when a NAS device ID is known): reads the API key and GUI address (default `127.0.0.1:8384`) from `config.xml`; pings `/rest/system/ping` up to 20 times, 1 s apart; a 401 or 403 means a different Syncthing owns the port and seeding is refused with a warning; not up within 20 s: warning. If the device is not already configured, POSTs it to `/rest/config/devices` with name `ccsync-nas`, addresses `tcp://<TailnetHost>:22000` and `dynamic`, compression `metadata`, not an introducer, not paused, auto-accept folders OFF. Every failure is a warning.
  - No device ID known: capability miss "the NAS Syncthing device ID is not known ... Lane C ... will never connect ...".
  - Syncthing path unknown: the whole step is skipped with a warning.
- **rclone remote** (step 7):
  - File: `%APPDATA%\rclone\rclone.conf` (folder created if missing).
  - Remote name: `CCSYNC_RCLONE_REMOTE`, else manifest `rclone_remote`, else `ccsync_sftp`.
  - Stanza: `type = sftp`, `host = <TailnetHost>`, `user = <EditorName>`, `port = <SftpPort>`, `key_file = %USERPROFILE%\.ssh\ccsync_ed25519`, `shell_type = <CCSYNC_SFTP_SHELL_TYPE, else manifest sftp_shell_type, else unix>`.
  - Host key pinning: when the host key (`CCSYNC_SFTP_HOSTKEY`, else manifest `sftp_hostkey`) looks like `ssh-...`, `ecdsa-...` or `sk-...` plus a key, writes `%USERPROFILE%\.ccsync\nas_known_hosts` with one line (`<host> <key>`, or `[<host>]:<port> <key>` for a non-22 port), and adds `known_hosts_file` and `host_key_algorithms` (the key's own type; `ssh-rsa` becomes `rsa-sha2-512 rsa-sha2-256`) to the stanza. Without a published key: skip line "the site publishes no NAS SSH host key: rclone will not verify the NAS's identity ...".
  - Existing stanza with the same host, user and (if pinned) known-hosts file and algorithm: skip. Different: warns with old and new host/user and rewrites only that stanza, leaving other remotes byte for byte. No stanza: appends it. Always UTF-8 without BOM.
  - If `%USERPROFILE%\.ssh\ccsync_ed25519` does not exist: warning with the `ssh-keygen -t ed25519 -f ...` command and "send the .pub half to the admin".
- **Companion config** (step 8):
  - Before writing: if `%USERPROFILE%\.ccsync` exists, re-grants it to (user, SYSTEM, Administrators) with inheritance to children and resets every file inside to inherit ("repaired permissions on everything inside ..."); restricts `config.toml` and `identity.json` if they exist ("restricted <file> (it holds your fleet token) to you, SYSTEM and Administrators"). Permission failures are warnings only.
  - Config already exists: not overwritten. Only `rclone_path` may be fixed: replaced with the located rclone when the current value is the bare name `rclone`/`rclone.exe` or an absolute path to a missing file; never replaced when it names an existing file or is a bare name and the new value is also bare. Then prints the four values (`editor_name`, `local_root`, `remote`, `remote_root`) under "confirm these values match, the companion will not fix them for you".
  - No config: writes `%USERPROFILE%\.ccsync\config.toml` (UTF-8, no BOM) containing: `editor_name`, `local_root`, `canonical_prefix`, `remote`, `remote_root` (or a comment `# remote_root NOT SET ...` when unknown, so the key is absent), `projects = []`, `active_project = ""`, `poll_interval = 3`, `scan_interval_up = 300`, `scan_interval_down = 120`, `watch_debounce_seconds = 10`, `transfers = 4`, `syncthing_url = "http://127.0.0.1:8384"`, `syncthing_api_key = ""`, `syncthing_folder_ids = []`, `rclone_path` (the located rclone as an absolute path; bare `rclone` if none located, if the path contains a single quote, or if it is inside winget's versioned folder), `log_path = "~/.ccsync/companion.log"`, `log_level = "INFO"`, `dashboard_url`, `dashboard_token`. Then restricts the file to the user, SYSTEM and Administrators.
- **Companion install and launch** (step 9):
  - With `-CompanionExeSource`: missing source warns and skips. Copies it over the destination if the destination is missing, a different size, or older than the source. If `ccsync-release.json` sits beside the source and its `sha256` equals the source exe's hash, copies it beside the installed exe and prints "companion build: v<version_stamp> (built <built_at>)"; a mismatching manifest is not copied ("... describes a different exe -- not recording a version").
  - Companion exe missing: warns and skips autostart, Resolve preferences and launch.
  - Autostart: HKCU Run value `CCSyncCompanion` = companion exe path (skip if already equal).
  - Resolve preferences: runs `<companion> --setup-resolve-prefs --wait-for-resolve <ResolvePrefsWaitSeconds>`, indenting its output. Non-zero exit warns "Resolve's LUT/stills preferences were not set now -- the companion will apply them the next time Resolve is closed".
  - Launch: if a process with the exe's name is not already running, starts it, waits 3 s, and reports "companion app confirmed running (PID n) -- all set" or warns "companion app exited within 3s of launch ... check %USERPROFILE%\.ccsync\companion.log for why".
- **Device ID and closing banner** (step 10):
  - Device ID parsed from `syncthing generate --home=...` output (`device=XXXXXXX-...` 8 groups of 7), falling back to the old `--device-id` flag. Not found: capability miss "the Syncthing device ID could NOT be determined ... Get it from the Syncthing web UI at http://127.0.0.1:8384 under Actions > Show ID and send it to the admin."
  - Banner "Bootstrap complete." with the device ID in cyan and "Send this device ID to the admin so they can approve this machine on the dashboard. ...".
  - Remaining steps text: when `CCSYNC_FROM_WIZARD=1`, "1-3. DONE BY THE SETUP WIZARD: Tailscale is joined, this computer's SSH key is made, and the companion is signed in. ..."; otherwise the manual list (1. `tailscale up`; 2. `ssh-keygen -t ed25519 -f "<key>"` and send the .pub; 3. SIGN IN from the tray's "Sign in..." with the username and password the admin gave, "NOTHING SYNCS UNTIL YOU DO THIS ..."). Always followed by: 4. connect Resolve (Studio) to the PostgreSQL project library and set Preferences > System > General > External scripting using = Local; 5. Playback > Proxy Handling > Prefer Proxies; 6. do not map any NAS share to another drive letter.
  - Dry run ends with "Bootstrap complete (dry run). No changes were made."
- **Exit codes**: `0` everything in place; `3` one or more capability misses, with a red numbered list headed "THIS MACHINE IS NOT READY TO SYNC -- <n> required piece(s) are missing:" and "Do NOT tell the admin you are set up yet."; `2` refusals listed above; `1` missing drive library or missing Tailscale without winget. Any other uncaught error stops the script (error action is Stop).
- Windows only, everything is per-user: `%LOCALAPPDATA%\ccsync\bin`, `%USERPROFILE%\.ccsync`, HKCU Run values, the logon task principal, the share's single grantee.

## Windows uninstaller
(source: installer/windows_uninstall.ps1, installer/drive_mapping.ps1)

- How it is reached: the bootstrap copies it to `%LOCALAPPDATA%\ccsync\bin\windows_uninstall.ps1` and registers it as the Apps & features "Uninstall" button; it also ships in the editor package zip.
- Never deletes synced media: the local root and everything in it is left as is in both modes. Never uninstalls Tailscale, or an rclone or Syncthing installed as system packages (winget or scoop). Never deletes the SSH key in `%USERPROFILE%\.ssh`.
- Parameters:
  - `-DriveLetter` (default empty): the tree drive letter. Blank: read from `canonical_prefix` in `%USERPROFILE%\.ccsync\config.toml`, else `P`. Only the first character is used, uppercased. Read locally, never from the dashboard.
  - `-Full` (switch): also remove the saved sign-in and the Syncthing identity.
  - `-DryRun` (switch): report only.
- Environment variable `CCSYNC_UNINSTALL_KEY_ROOT`: overrides the Apps & features registry root (test hatch).
- Lines are prefixed `[uninstall] `; skips `[uninstall] (skip) ...`; warnings `[uninstall] WARNING: ...`.
- Opening lines: the mode ("FULL (also removes your sign-in + Syncthing identity)" or "keep sign-in + settings"), "your synced media is never touched by this script -- only the CCSync app itself.", and "DRY RUN -- nothing will be changed" in a dry run.
- If `drive_mapping.ps1` is not beside it, the uninstall still runs but leaves the drive mapping and the share alone (warning) and prints the two manual commands.
- Steps, in order:
  1. Stops processes named `ccsync-companion` and `syncthing` (forced, not waited on), and any `pythonw.exe` whose command line contains `launcher.py` (a companion run from source).
  2. Removes HKCU Run values `CCSyncCompanion`, `CCSyncSyncthing`, `CCSyncSubst<letter>`; unregisters scheduled task `CCSync-Subst<letter>`; unregisters every leftover `CCSync-OneShot-*` scheduled task.
  3. Tree drive:
     - Classifies the mapping exactly like the bootstrap (subst, or `net use` to `\localhost\CCSync_<letter>`, is ours; anything else, or unreadable, is somebody else's and is left alone with a skip or warning).
     - Ours: runs `subst <drive> /D` and `net use <drive> /delete /y` (at the user's normal integrity level when elevated), then re-reads the mappings. Only a confirmed-gone mapping counts as unmapped; otherwise it warns "<drive> still points at ... after the unmap. Keeping the '<share>' share ...".
     - Share `CCSync_<letter>`: removed only when the drive was confirmed unmapped (or not mapped). If the mapping stayed, the share is kept and it prints `net use <drive> /delete /y` and `Remove-SmbShare -Name <share> -Force (administrator PowerShell)`. Removal needs administrator rights; on failure it prints the admin command. After removal it re-reads the shares.
     - Firewall rule `CC Sync: block remote SMB (tree share is loopback-only)`: removed only when the share is confirmed gone; kept (with a skip message) while the share is still published or cannot be read.
     - Removes only the `_LabelFromReg` value under `HKCU\...\Explorer\MountPoints2\##localhost#CCSync_<letter>`, leaving the key. Removes the whole legacy key `HKCU\...\Explorer\DriveIcons\<letter>` if present.
  4. Deletes `%LOCALAPPDATA%\ccsync\bin` (rclone, Syncthing, companion exe). Re-reads it; files other than the running uninstaller and `drive_mapping.ps1` that survive are listed (first 8, then "...and N more") with "To finish: sign out and back in (or restart), then run this uninstaller again from Apps & features, or delete <bin> by hand."
     - Apps & features entry `HKCU\...\Uninstall\CCSync`: removed only when the bin folder is clear; otherwise left in place ("leaving CC Sync in Apps & features so you can run this again ...").
     - Removes the bin folder from the user PATH, preserving `%VAR%` entries and the value type.
  5. Without `-Full`: keeps `%LOCALAPPDATA%\ccsync\syncthing-config` ("KEPT Syncthing identity ... reinstall reuses the same device ID -- no re-approval needed") and `%USERPROFILE%\.ccsync` ("KEPT your sign-in and settings ... (config.toml, state)"), and says "run with -Full to also remove your sign-in and Syncthing identity."
  6. With `-Full`:
     - Deletes all of `%LOCALAPPDATA%\ccsync` (including `syncthing-config`, the device identity, and the `elevate` helper folder) and re-reads it; survivors are listed.
     - Deletes everything in `%USERPROFILE%\.ccsync` EXCEPT the `state` folder (config.toml, identity.json, logs, the NAS known-hosts file, the EULA record all go), re-reads, lists survivors, and prints "KEPT <profile>\state -- the prompts you have already answered stay answered after a reinstall ...".
     - If the Syncthing home is still present: warning that the identity is STILL there and a reinstall reuses the SAME device ID. If gone: "FULL uninstall: your saved sign-in and Syncthing device identity are gone. A reinstall generates a NEW device ID -- send it to the admin ...".
     - Notes that the SSH key `%USERPROFILE%\.ssh\ccsync_ed25519` remains.
- Closing verdict, between two `====` rules:
  - Program files left: "CCSync uninstall NOT complete: <n> program file(s) are still in <bin>. Sign out and back in, then run this uninstaller again from Apps & features."
  - `-Full` items left: "CCSync uninstall NOT complete: ..." with one of two explanations depending on whether the Syncthing identity survived.
  - Otherwise "CCSync uninstall complete." (plus " (dry run -- nothing changed)").
  - Always "Tailscale / rclone / Syncthing installed as system packages were left alone; remove them from Apps & features if wanted."
  - When the running uninstaller is inside the bin folder: on an incomplete run "LEAVE this uninstaller where it is at <path> - it is what you run to retry ..."; on a complete run "this uninstaller is still on disk at <path> (it was running). Delete that file, and the folder it is in, whenever you like."
- What it does NOT remove in either mode: the `[<remote>]` stanza in `%APPDATA%\rclone\rclone.conf`; the SSH key and `.pub`; `%USERPROFILE%\.ccsync\state`; Tailscale; system-package rclone or Syncthing; the local root and media.
- Exit code: not set explicitly (0 unless an unexpected error stops it).

## Windows upgrade script (swap in a new companion build)
(source: installer/windows_upgrade.ps1)

- For a machine that already ran the bootstrap. Replaces only the companion exe; leaves the Syncthing identity, rclone key and config, tree drive mapping and settings alone. Safe to re-run.
- Lines are prefixed `[upgrade] `; skips `[upgrade] (skip) ...`; warnings `[upgrade] WARNING: ...`.
- Parameters:
  - `-CompanionExe` (default: `ccsync-companion.exe` beside the script): the new build. Missing: "new companion exe not found at: <path>" / "run this from inside the CC_Sync package folder, or pass -CompanionExe <path>." and exit `1`.
  - `-DashboardToken` (default empty): if given, sets or replaces `dashboard_token` in config.toml.
  - `-DashboardUrl` (default empty; falls back to environment variable `CCSYNC_DASHBOARD_URL`): used only when config.toml has no `dashboard_url`.
  - `-SkipWizard` (switch): never launch the setup wizard for the licence.
  - `-DryRun` (switch): report only.
- The "package folder" is the folder holding the new exe; `onboard.exe` and `EULA.md` are looked for there.
- Version identification: if `ccsync-release.json` sits beside the new exe and its `sha256` matches the exe, prints "version: v<version_stamp> (built <built_at> from <git_describe>)" and, when the build came from an uncommitted tree, warns "this build came from an uncommitted tree -- fine for testing, not for the fleet". A mismatching manifest: "... describes a DIFFERENT file -- ignoring it; version unknown". No manifest: "version: unknown (no ccsync-release.json beside the exe; build with tools\release.ps1)". Always prints the exe's sha256, size and timestamp.
- Steps, in order:
  1. Stops `ccsync-companion` processes and any `pythonw.exe` running `launcher.py` (forced), then waits 0.8 s. "companion was not running" when there was none.
  2. Renames the installed `%LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe` to `ccsync-companion.exe.prev` (the previous version is read from the installed `ccsync-release.json` for messages). Rename failure warns "could not set the current build aside ... upgrading in place, with nothing to roll back to". Copies the new exe in, up to 5 attempts 2 s apart ("copy attempt n/5 failed (...) -- retrying in 2s"; after the last: "close anything that might have it open (Explorer preview, AV scan) and re-run this script."). If every copy failed and no exe is left, renames `.prev` back ("restored the previous build ... -- this machine is where it started").
  3. After a successful copy: copies the new `ccsync-release.json` beside the exe ("recorded provenance: ..."), or deletes a stale one when the new package has none.
  4. After a successful copy: runs `%SystemRoot%\System32\ie4uinit.exe -show` hidden to refresh the shell icon cache (best effort, silent on failure).
  5. Always (even after a failed copy): sets HKCU Run value `CCSyncCompanion` to the installed exe path.
  6. Config migration on `%USERPROFILE%\.ccsync\config.toml` (read and written as UTF-8 without BOM). Missing config: warns "no config at <path> -- run windows_bootstrap.ps1 to seed it, then re-run this." Adds only missing keys, never overwrites (except the token when `-DashboardToken` is passed):
     - `dashboard_url` from the flag or environment variable; if neither exists, warns "config.toml has no dashboard_url and none was given ... this companion will not report, will not take managed sync selections, and will never be offered another upgrade. ..." and adds nothing.
     - `dashboard_token`: set from `-DashboardToken`; otherwise added blank if absent.
     - `mode = "editor"` if absent (an existing `mode`, for example `base`, is never changed).
     - New keys go in a block headed `# -- added by windows_upgrade.ps1 --`, inserted before the first `[section]` header if the file has one, else at the end. "config already has the new keys -- no changes" when nothing was added.
  7. Permissions repair: re-grants `%USERPROFILE%\.ccsync` to (user, SYSTEM, Administrators) with inheritance to children and resets everything inside to inherit; restricts `config.toml` and `identity.json` to those three. Failures warn only.
  8. Relaunch: starts the installed exe (working folder = bin folder), waits 3 s, checks that the launched process has not exited.
     - Running: "companion is running (pid n)".
     - Exited: warns "the companion EXITED within 3s of being started." with the command to run it by hand and the log path. If a `.prev` was kept, renames the failed exe to `ccsync-companion.exe.failed`, restores `.prev`, starts it, waits 3 s; if that stays up: "the new build would not start - this machine is back on v<prev>" and "the build that failed is kept at <...>.failed; the version record beside the exe is now WRONG until the next upgrade". If it also dies, or there is no `.prev`: warning that the machine has NO companion running and nothing will retry before the next logon.
     - No exe at all: "nothing to relaunch ...".
  9. Sync engine check: if no `syncthing` process runs, starts `%LOCALAPPDATA%\ccsync\bin\CCSyncSyncthing.vbs` through `wscript.exe //B //Nologo`, waits 2 s and confirms a `syncthing` process appeared. No shim: warns "the sync engine (Syncthing) is NOT running and there is no autostart shim ... Re-run windows_bootstrap.ps1."
  10. Licence check:
      - Needed when `%USERPROFILE%\.ccsync\eula_accepted.json` is missing ("the licence agreement has not been accepted on this machine"), unreadable or has no version ("... record on this machine is unreadable"), or its `version` is older than the `<!-- EULA-VERSION: x.y -->` marker in the package's `EULA.md` ("the licence agreement has been updated (v<new>; this machine accepted v<old>)"). Versions compare numerically part by part. A package without `EULA.md` or without a marker never triggers a re-accept.
      - Route, first match wins: not needed: "licence agreement already accepted on this machine"; the relaunched companion is running (and not a dry run): it is left to the companion's own licence window ("... accept in its licence window, or from the tray (Tray > Accept the licence agreement). The setup wizard is not needed for this."); `-SkipWizard`: warning only; config has `mode = "base"`: warning, wizard NOT launched; dry run: says what a real run would do; no `onboard.exe` in the package: "... Get the current installer from the dashboard's [ INSTALLER ] link and run it."; otherwise launches `onboard.exe` (not waited on).
- Summary block:
  - Copy failed: "Upgrade INCOMPLETE: the new companion build could not be installed (see the WARNING above); the previous build was relaunched instead." and exit `1`.
  - Copied but not running: "Upgrade INSTALLED BUT NOT RUNNING: ..." and exit `1`.
  - Otherwise "Upgrade complete." with " -- now running v<version>" when known (and " (dry run -- nothing changed)").
  - Always "Syncthing identity, rclone key, drive mapping, and settings were preserved."
  - Licence state line (wizard open / companion asking / NOT SYNCING).
  - If no `-DashboardToken` and config.toml has an empty `dashboard_token`: warns "dashboard_token is blank -- fleet reporting + project selection are off. Re-run with -DashboardToken <value> (ask the admin) to enable them."
- Exit codes: `0` success (and every dry run); `1` new exe missing, copy failed, or the companion is not running afterwards. Note: when the new build would not start but the previous build was restored and runs, the exit code is `0`.
- Does not touch Syncthing, rclone, Tailscale or the drive mapping.

## Building, assembling and publishing the editor package (operator tool, Windows)
(source: installer/build_editor_package.ps1)

- Run by the operator on the base rig (also called by the ship tool). Assembles the "editor package" folder editors are pointed at, optionally rebuilds the two Windows executables, and optionally publishes them to the dashboard's upgrade channel. Lines prefixed `[pkg] `.
- Parameters:
  - `-Destination` (default empty): package folder. Blank: `<canonical_prefix>\Assets\Software\CC_Sync`, the prefix read from `canonical_prefix` in `%USERPROFILE%\.ccsync\config.toml`, else from the cached site manifest `%USERPROFILE%\.ccsync\site.json`, else `P:\`. An existing folder is overwritten file by file, never deleted. If the destination's drive letter does not exist: three warnings naming where the letter came from, exit `1`, before anything is built.
  - `-RebuildExe`: rebuild the companion exe with PyInstaller (`companion\build.spec`) using `companion\.venv\Scripts\python.exe`, or `python` on PATH with a warning.
  - `-RebuildOnboard`: rebuild `onboard.exe` with PyInstaller (`onboarding\build_onboard.spec`) using `onboarding\.venv\Scripts\python.exe` or `python`.
  - `-DryRun`: report only.
  - `-Publish`: upload to the dashboard. Requires `-DashboardUrl` (or environment variable `CCSYNC_DASHBOARD_URL`) and `-AdminUser` (or `CCSYNC_ADMIN_USER`); either missing is exit `1` before anything else.
  - `-MakeCurrent`: with `-Publish`, flip both uploads to current at the end.
  - `-AllowUnsignedBinary`: allow `-MakeCurrent` for an `onboard.exe` with no valid Authenticode signature.
  - `-AllowKeyRotation`: publish although this rig's signing key differs from the key that signed the fleet's current build.
  - `-EmitKindExtras`: sign `requires_dashboard` and `arch` into the release record (opt-in).
  - `-IReallyMeanDirtyCurrent`: allow `-MakeCurrent` for a build made from an uncommitted tree.
- Environment variables: `CCSYNC_DASHBOARD_URL`, `CCSYNC_ADMIN_USER`, `CCSYNC_MIN_VERSION` (the release record's rollback floor; empty lets the signing tool use its per-kind floor file).
- Order of work:
  1. With `-Publish`: refuses (exit `1`) if `CCSYNC_MIN_VERSION` is above the companion version, with a six-line explanation that every machine would raise its floor and refuse this build.
  2. With `-Publish`, not a dry run: checks `GET <dashboard>/api/v1/health` (20 s timeout; any HTTP answer counts as reachable). Unreachable: exit `1` ("cannot reach the dashboard ... This is not a password problem ..."). Then prompts "dashboard password for '<user>'" (hidden), logs in with `POST /api/v1/login`, up to 3 tries on 401/403 ("wrong password for '<user>' (n of 3) -- try again"; after three, exit `1`). Any other login error, or a non-admin user: exit `1`. All before building.
  3. With `-Publish`: compares this rig's release signing key id with the key that signed the current Windows companion (`GET /api/v1/admin/packages`). Same: OK. No current build or no recorded key: note and continue. Different without `-AllowKeyRotation`: long explanation that every machine on the current build would refuse this build, exit `1`. With the flag: warnings only.
  4. `-RebuildExe`: runs PyInstaller, then the frozen-dependency scan (`tools\scan_frozen.py --component companion`); a refused exe is deleted and the run marked failed. On success writes `companion\dist\ccsync-release.json` with `version`, `version_stamp` (plus `+dirty` when the git tree has changes), `platform` = `windows`, `artifact`, `sha256`, `size_bytes`, `built_at`, `artifact_mtime`, `git_commit`, `git_describe`, `git_dirty`, `tests_run` = false, `built_by` (`user@computer`), `built_with`. A failed PyInstaller marks the run failed and does not restamp.
  5. `-RebuildOnboard`: PyInstaller, then the frozen-dependency scan (`--component onboarding`; a refused exe is deleted), then Authenticode signing through `tools\sign_windows_binary.ps1` (a no-op without a configured signing identity); signing failure marks the run failed.
  6. Byte-scans `installer\macos_bootstrap.sh` for any carriage return; one found, unreadable or missing marks the run failed ("... a Mac's bash would fail on the first line ..."); else "macos_bootstrap.sh is LF-clean". Runs on every assembly.
  7. Copies into the package (missing sources and copy failures are listed and mark the run failed; one locked file does not stop the rest): `START_HERE.md`, `FIRST_UPGRADE.md`, `windows_bootstrap.ps1`, `drive_mapping.ps1`, `windows_upgrade.ps1`, `windows_uninstall.ps1`, `macos_bootstrap.sh`, `macos_uninstall.sh`, `EDITOR_SETUP.md` (from `docs\`), `EULA.md` (the companion's bundled copy), `config.example.toml`, `ccsync-companion.exe`, `onboard.exe`. Optional: `ccsync-release.json` (absence is only a skip line).
  8. Provenance report: files assembled; companion exe time versus newest companion source ("THE EXE IS STALE -- companion source has changed since it was built. Re-run this script with -RebuildExe ..."); `onboard.exe` time versus the newest of `onboarding\*.py`, `windows_bootstrap.ps1` and the companion exe ("ONBOARD.EXE IS STALE -- re-run with -RebuildOnboard before shipping."); the git commit, noting uncommitted changes. Staleness here is a warning, not a failure.
  9. Publish (only with `-Publish`):
     - Refusals (exit `1`): `VERSION` in `companion\src\ccsync_companion\config.py` unreadable; differs from `companion\pyproject.toml`; PyInstaller failed earlier this run; no exe; exe older than the newest companion source; release-record signing failed (prints how to create the key with `tools\release_key.py new`); signing output unparseable; the signed record's sha256 differs from the exe; `min_version` above the version.
     - Advisories: release manifest describes a different exe (its provenance is dropped); built from an uncommitted tree; no manifest; exe has no valid Authenticode signature (boxed "UNSIGNED BUILD" warning about SmartScreen).
     - A dirty build with `-MakeCurrent` and no `-IReallyMeanDirtyCurrent` is published staged, not current, with an explanation.
     - Uploads are always staged first: `PUT /api/v1/admin/packages/windows/<version>?sha256=...&make_current=0<signed query>`, body = the exe.
     - 409 (version already there): byte-identical server copy continues to the installer ("already published (byte-identical)"); different bytes: bump the version in both files, exit `1`. Other failure: exit `1`.
     - Lists the Windows companion versions on the server, `*` marking the current one.
     - Installer upload (`kind=onboard`, version = shared installer version) is skipped and the run marked failed when: the onboard PyInstaller failed this run; the installer version cannot be read from `windows_bootstrap.ps1`, `onboarding\steps.py` and `macos_bootstrap.sh`, or they disagree; no `onboard.exe`; `onboard.exe` older than the companion exe; its record could not be signed or parsed. 409 with different bytes: failure telling the operator to bump the installer version; same bytes: "already published (unchanged)".
     - `-MakeCurrent` with an unsigned `onboard.exe` and no `-AllowUnsignedBinary`: refuses before any upload, exit `1` ("Nothing was published.").
     - `-MakeCurrent`: `POST /api/v1/admin/packages/windows/<version>/current?kind=companion`, then the same for `kind=onboard`. A refusal prints the dashboard's `detail` verbatim and ends with exit `3` ("BOTH builds are PUBLISHED and STAGED. ... push the staged build to one machine ... let it soak, and click [ MAKE CURRENT ] there ...").
     - Without `-MakeCurrent`: "NOTE: v<version> is staged but NOT current -- flip [ MAKE CURRENT ] on the dashboard admin page ...".
     - macOS advisories (never change the exit code): no macOS installer published; macOS installer channel behind the repo version; macOS installer channel serving a `.sh` instead of the wizard; macOS companion channel missing or at a different version. Each names the Mac-side command.
  10. Any failure above ends with "THIS RUN DID NOT FULLY SUCCEED -- see the FAILED line(s) above." and exit `1`.
- Dry run prints every copy, build and PUT it would do, with URIs and sizes.
- macOS artefacts are never built or published from this script.

## macOS bootstrap: inputs and refusals
(source: installer/macos_bootstrap.sh)

- A bash script, idempotent; every step checks state and prints what it did or skipped. Lines prefixed `[ccsync] `; warnings and capability misses go to standard error. Does not join the tailnet and does not create SSH keys. Installer version `1.0.47` (shared with Windows and the wizard).
- On macOS nothing is mounted at a drive letter: the tree is reached by a Resolve "Mapped Mount" preference that rewrites `<canonical prefix>` (for example `P:\`) to the local root.
- Command-line flags:
  - `--tailnet-host <host>` (required unless `--resolve-mapping-only`): NAS host for rclone and the Syncthing NAS address.
  - `--editor-name <name>` (required unless `--resolve-mapping-only`): NAS username, lowercased (warning "normalized --editor-name '<raw>' -> '<new>'" when changed).
  - `--local-root <path>`: local root. Default: the `local_root` line of an existing `~/.ccsync/config.toml` ("local root from your existing config.toml: ..."), else `~/<tree name>` ("no --local-root given -- using ... (pass --local-root to put the tree on an external volume)").
  - `--remote-root <abs-path>`: else manifest `remote_root`.
  - `--sftp-port <n>`: `0`/absent/non-numeric means manifest `sftp_port`, else `22`.
  - `--companion-file <path>`: install the companion from a local file (no token needed).
  - `--companion-version <x.y.z|current>` (default `current`): published macOS companion version to download.
  - `--companion-path <path>` (default `~/.local/ccsync/bin/ccsync-companion`): where the companion binary lives. It is a single binary run directly by launchd, not an app bundle.
  - `--skip-resolve-mapping`: leave the Mapped Mount and the LUT/stills preferences alone.
  - `--resolve-mapping-only`: set only Resolve's Mapped Mount and exit; needs neither the NAS host nor the editor name nor a dashboard.
  - `--dry-run`: print what would happen.
  - `-h`/`--help`, or any unknown argument ("Unknown argument: <arg>"): prints usage and exits `1`.
- Environment variables:
  - `DASHBOARD_URL` (else `CCSYNC_DASHBOARD_URL`): required for a full run.
  - `DASHBOARD_TOKEN`: fleet token, used to download the companion and written to config.toml.
  - `CCSYNC_TREE_NAME`, `CCSYNC_CANONICAL_PREFIX`, `CCSYNC_RCLONE_REMOTE`, `CCSYNC_SFTP_SHELL_TYPE`, `CCSYNC_SFTP_HOSTKEY`, `CCSYNC_NAS_SYNCTHING_ID`: each wins over the manifest (the wizard sets them).
  - `RESOLVE_PREFS_WAIT_SECONDS` (default `180`): how long to wait for Resolve to be quit.
  - `CCSYNC_UNINSTALLER`: a path to `macos_uninstall.sh` to install (else the copy beside the script).
  - `CCSYNC_RESOLVE_APP`: an extra place to look for the Resolve app bundle.
  - `CCSYNC_FROM_WIZARD=1`: changes the closing "remaining steps" text.
  - `BMD_RESOLVE_CONFIG_DIR`: overrides Resolve's preference folder for the Mapped Mount helper (test hook).
- Refusals:
  - A required flag missing: "Missing required argument: --tailnet-host and --editor-name" (whichever are missing), "Your admin gives you both values (the NAS host and your username).", usage, exit `1`.
  - No dashboard URL on a full run: "ERROR: no dashboard URL." with the `DASHBOARD_URL=... ./macos_bootstrap.sh ...` example, exit `2`.
  - Canonical prefix is not a drive-letter path: "ERROR: the site manifest's canonical_prefix is '<value>', which is not a drive-letter path." exit `2`. The prefix is normalised to `<LETTER>:\`.
  - Tailscale missing and no Homebrew: "Homebrew not found. Download and install Tailscale manually from https://tailscale.com/download/mac then re-run this script." exit `1`.
  - External-volume problems (see below): exit `1`.
- Site manifest: `curl` of `<dashboard>/api/v1/site`, 8 s limit; failure warns "no site manifest from <url> (an older dashboard, or not reachable yet) -- using the values passed on the command line". Keys read: `remote_root`, `nas_syncthing_id`, `sftp_port`, `tree_name` (fallback `CCSync`), `canonical_prefix` (fallback `P:\`), `rclone_remote` (fallback `ccsync_sftp`), `sftp_shell_type` (fallback `unix`), `sftp_hostkey`.
- Remote root: empty or not starting with `/` is a capability miss with the same wording as Windows (flag named `--remote-root`); a relative value is dropped.
- Low free space: same 200 GB warning as Windows, measured with `df` on the first existing parent.
- Downloads are staged in a private per-run temporary folder (`$TMPDIR/ccsync-stage.XXXXXXXX`), deleted on exit.

## macOS bootstrap: the steps, in order
(source: installer/macos_bootstrap.sh)

- Prints "ccsync macOS bootstrap <version> -- editor '<name>', local root '<root>', NAS '<host>'" (or "-- Resolve mapping only, local root ...").
- `--resolve-mapping-only` runs only the Mapped Mount step (below), prints `[ccsync] RESOLVE-MAPPING-STATUS: <status>`, then "done -- nothing else was touched (--resolve-mapping-only)." and exit `0` when the status is `ok` or `dry-run`, otherwise "the Mapped Mount was NOT set (see above). Nothing else was touched (--resolve-mapping-only)." and exit `1`.
- Creates `~/.local/ccsync/bin`.
- Installs the uninstaller: copies `macos_uninstall.sh` (from `CCSYNC_UNINSTALLER` or beside the script) to `~/.local/ccsync/bin/macos_uninstall.sh`, makes it executable, clears its quarantine flag. Absent: nothing, and the closing banner says to get it from the package or the admin.
- **Tailscale**: skipped if `tailscale` is on PATH or `/Applications/Tailscale.app` exists; else `brew install --cask tailscale` (failure only warns); no Homebrew: refusal above.
- **rclone**: already installed if `rclone` is on PATH or `~/.local/ccsync/bin/rclone` is executable. Otherwise the pinned download first: rclone `v1.75.0`, `rclone-v1.75.0-osx-arm64.zip` or `-osx-amd64.zip` by CPU (`uname -m`), each with its own hardcoded sha256, from `downloads.rclone.org`; verified with `shasum -a 256` before unzipping (mismatch: same CHECKSUM MISMATCH messages as Windows, file deleted); copied to the bin folder, made executable, quarantine flag removed. Fallback: `brew install rclone` with the warning "falling back to brew's rclone: NOT the pinned v1.75.0". Not found afterwards: capability miss "rclone is NOT installed. Lanes A and B ... cannot run on this Mac. ...". Prints "rclone resolved to: <path>" after a fresh install.
- **Syncthing**: already installed if `syncthing` is on PATH or in the bin folder. Otherwise pinned download (Syncthing `v2.1.3`, `syncthing-macos-<arm64|amd64>-v2.1.3.zip` from GitHub releases, per-CPU sha256), then `brew install syncthing` with "falling back to brew's Syncthing: NOT the pinned v2.1.3". Not found: capability miss "Syncthing is NOT installed. Lane C ... will never sync on this Mac. ...".
  - Generates the config at `~/.local/ccsync/syncthing-config` if that folder does not exist.
  - Retires the legacy LaunchAgent `com.creatorsclub.ccsync.syncthing` (boots it out, unloads, deletes `~/Library/LaunchAgents/com.creatorsclub.ccsync.syncthing.plist`; "retired the legacy LaunchAgent ... (renamed to com.ccsync.*, 2026-08-17)").
  - LaunchAgent `~/Library/LaunchAgents/com.ccsync.syncthing.plist`: label `com.ccsync.syncthing`, runs `<syncthing> serve --home=<home> --no-browser`, `RunAtLoad` true, `KeepAlive` true. Kept if it exists and its program equals the found binary; otherwise (re)written and reloaded (bootout then bootstrap, falling back to unload/load). Reload failure prints the two `launchctl` commands.
  - No Syncthing binary: no plist is written; a previously written plist with an empty program is removed.
  - Starts the daemon if no `syncthing` process (or `syncthing ... serve`) is running (`launchctl bootstrap gui/<uid>`, else `launchctl load`), waits 2 s and confirms ("Syncthing daemon is running", or a warning to check `launchctl list | grep ccsync`).
  - NAS device seeding (device ID from `CCSYNC_NAS_SYNCTHING_ID`, else the manifest): reads the API key from `config.xml`, pings `http://127.0.0.1:8384/rest/system/ping` up to 10 times 1 s apart (401/403 means another Syncthing owns the port: not seeded, warning), then adds the device exactly as Windows does (name `ccsync-nas`, `tcp://<host>:22000` and `dynamic`, compression metadata, auto-accept folders off) unless already listed. Non-200: "could not seed the NAS Syncthing device (HTTP <code>)". No device ID: capability miss naming `CCSYNC_NAS_SYNCTHING_ID`.
- **Local root and external volumes**:
  - If the local root is under `/Volumes/<Name>/...`:
    - The volume path does not exist: if a numbered remount like `/Volumes/<Name> 1` is mounted, the ghost-directory abort (below); otherwise "<mount> does not exist -- plug the drive in (and unlock it if it is encrypted), then re-run this script." exit `1`.
    - The path exists but is not a mount point (per `mount`): ghost-directory abort. A boxed warning "<mount> IS NOT A MOUNTED VOLUME." that explains either the numbered remount ("Your drive is actually mounted at: <numbered> ... must NOT be used as the sync root") or a leftover directory ("... Syncing into it would fill your Mac's internal disk instead of the SSD."), then the fix: eject (`diskutil eject`), `sudo rmdir "<mount>"`, unplug and replug, re-run. Exit `1`.
    - Real mount plus a numbered sibling also mounted: warning "two drives with the same name are how the wrong one gets synced -- rename one of them." and continue.
    - `diskutil info -plist` fails: "diskutil does not recognise <mount> as a volume ... Refusing to guess" exit `1`.
    - Reads the volume UUID and filesystem type. No UUID: warning that the companion's root guard will have only the mount point. Not APFS: warning that exFAT/HFS+ lose macOS metadata and exFAT cannot store case-sensitive names.
    - Writes `~/.ccsync/volume.json` (mode 600; folder mode 700) with `volume_uuid`, `mount_point`, `local_root`. The companion reads it to tell "SSD unplugged" from "SSD mounted but empty".
  - Otherwise: skip line "local root ... is not under /Volumes -- no external-volume checks".
  - Creates the local root folder.
- **rclone remote**: `~/.config/rclone/rclone.conf`, same stanza fields and host-key pinning rules as Windows (known-hosts file `~/.ccsync/nas_known_hosts`, mode 600). Existing matching stanza: skip. Mismatching: warns with old and new host and user and rewrites only that section; the rewrite first checks that the new stanza and every other original section survive, keeps a timestamped backup `rclone.conf.ccsync-backup-<YYYYmmdd-HHMMSS>`, sets mode 600, and if anything fails leaves the file untouched ("... it was LEFT UNTOUCHED, nothing was lost." plus manual fix). No stanza: appends. Missing `~/.ssh/ccsync_ed25519`: the same SSH key warning as Windows.
- **Companion binary** (`~/.local/ccsync/bin/ccsync-companion` by default):
  - From `--companion-file`: a missing file is a failure reason; otherwise its sha256 is printed.
  - No file and no `DASHBOARD_TOKEN`: if a companion is already installed, it is left as is ("no DASHBOARD_TOKEN, so it was not checked for updates"); otherwise failure.
  - Download: `GET <dashboard>/api/v1/companion/package/macos/<version>` with header `X-CCSync-Token: <token>`. Refused (not installed) when: the download fails ("wrong DASHBOARD_TOKEN, no tailnet route to the dashboard, or no published macOS package"); the response has no `X-CCSync-Signature` header ("the dashboard served this companion build WITHOUT a release signature, so it was NOT installed. ..."); no `X-CCSync-SHA256` header; the file's sha256 differs from that header (also "Tell the admin: either the published package is corrupt or something is rewriting the download."). The script does not verify the signature itself, only its presence and the sha256.
  - Identical to the installed one: skip. Otherwise boots out the running companion agent, stages the file as `<path>.ccsync-new`, makes it executable, moves it into place, clears the quarantine flag.
  - Retires the legacy LaunchAgent `com.creatorsclub.ccsync.companion` (always).
  - Companion missing: a boxed warning "THE SYNC APP IS NOT INSTALLED ON THIS MAC." with the reason and what will not work (lanes A, B, C, reporting, project picking), plus a note when the legacy autostart was just removed that this Mac will now start no companion at logon. Removes our own companion plist if it points at a missing binary.
  - Companion present: LaunchAgent `~/Library/LaunchAgents/com.ccsync.companion.plist`: label `com.ccsync.companion`, runs the binary directly, `RunAtLoad` true, `AbandonProcessGroup` true, deliberately no `KeepAlive`. Kept when its program matches, it has `AbandonProcessGroup` and no `KeepAlive`; otherwise rewritten and reloaded.
- **Companion config** `~/.ccsync/config.toml`:
  - Exists: not overwritten; folder set to 700 and file to 600. If rclone was located and the file's `rclone_path` is missing, relative/bare, or an absolute path that is not executable, it is replaced with the located absolute path (or appended under `# -- set by macos_bootstrap.sh --`), printing the old and new values. Then prints the five values to confirm (adds `rclone_path` compared to Windows).
  - Absent: writes the same keys and defaults as the Windows seeded config (with `rclone_path` as the absolute located path, or `rclone` with a warning when none was found, and `remote_root` omitted when unknown), mode 600, folder 700 ("... (mode 600, dir 700 -- it holds the dashboard token)").
- **Resolve Mapped Mount** (`<prefix>` -> local root):
  - `--skip-resolve-mapping`: status `skipped`.
  - Waits for Resolve to quit: if a `DaVinci Resolve` process runs, prints once "DaVinci Resolve is running. It rewrites its own preferences when it quits, so anything set now would be thrown away. --> Please quit DaVinci Resolve. This will continue automatically.", polls every 3 s up to `RESOLVE_PREFS_WAIT_SECONDS`; on quit "Resolve is closed -- continuing."; on time-out warns "gave up waiting for DaVinci Resolve after <n>s - carrying on WITHOUT setting Resolve's Mapped Mount. Everything else still installs. When you can quit Resolve, run: <script> --resolve-mapping-only".
  - Local root missing: warning that the mapping is still written.
  - No `python3`: status `no-python`, warning to run `xcode-select --install` and re-run with `--resolve-mapping-only`, plus manual instructions ("DaVinci Resolve > Preferences (Cmd+,) > Media Storage, add a Mapped Mount: local path <root>, mapped path <prefix>").
  - Runs the embedded helper (extracted from the script itself, else from a built-in copy) with `apply --local-root <root> --mapped-root <prefix>`. Result to status: `0` ok ("Mapped Mount configured: ..."); `3` running ("Resolve is running -- quit it and re-run: <script> --resolve-mapping-only"); `4` with Resolve installed (`/Applications/DaVinci Resolve/DaVinci Resolve.app`, `/Applications/DaVinci Resolve.app` or `CCSYNC_RESOLVE_APP`) `never-launched` ("launch it once, quit it, then re-run"), without `not-installed` ("DaVinci Resolve is not installed on this Mac. CC Sync needs Resolve Studio (the paid version)."); `5` format ("not in the format this installer knows -- nothing was changed" plus manual steps); anything else `error`. Helper extraction failure: `error`.
  - Always prints the machine-readable line `[ccsync] RESOLVE-MAPPING-STATUS: <ok|running|never-launched|not-installed|format|skipped|no-python|dry-run|error|unset>`.
- **Resolve LUT library and shared stills gallery**: skipped with `--skip-resolve-mapping`; companion not installed: warning (the companion sets them itself later); waits for Resolve to quit again (time-out: warning, not set now); then runs `<companion> --setup-resolve-prefs --wait-for-resolve 0`, output indented; failure warns that the companion retries on its own schedule.
- **Device ID and closing banner**: device ID parsed from `syncthing generate` output, falling back to `--device-id`. Not found: capability miss plus "Get it from the Syncthing web UI (http://127.0.0.1:8384) under Actions > Show ID". Banner "Bootstrap complete (installer <version>)." with the device ID and the same admin-approval text as Windows. Steps: 1-2 (wizard: "DONE BY THE SETUP WIZARD: Tailscale is joined and this Mac's SSH key is made ..."; manual: `tailscale up`, `ssh-keygen`); 3 (companion missing: "INSTALL THE SYNC APP -- it is not on this Mac yet ..."; wizard: "DONE BY THE SETUP WIZARD: the companion is signed in."; manual: sign in from the menu-bar icon); 4 Resolve PostgreSQL library and External scripting = Local; 5 Prefer Proxies; 6 the Mapped Mount line worded by status (`ok`: "DONE FOR YOU: Resolve maps <prefix> to <root>"; others: "NOT DONE -- ..." with the fix, or "SKIPPED"); 7 do not mount any NAS share over SMB alongside this; then how to uninstall ("bash <path>" or "run macos_uninstall.sh from the installer package your admin sent you, or ask them for it").
- **Exit codes**: companion not installed: a final "REMINDER: THE SYNC APP IS NOT INSTALLED ON THIS MAC." block ending "Do not report yourself ready." and exit `1` (this wins over capability misses). Capability misses: "THIS MAC IS NOT READY TO SYNC -- <n> required piece(s) are missing:" numbered list, exit `3` (the only exit 3). Otherwise `0`. Dry run ends "Bootstrap complete (dry run). No changes were made." and exit `0`.
- Differences from Windows: no wrong-account check; no Apps & features style entry; no firewall rule, share or drive letter; no `.prev` rollback; companion downloaded from the dashboard (Windows only copies a given exe); Syncthing kept alive by launchd (`KeepAlive`), while Windows uses a logon-only Run entry; external-volume checks and `volume.json` exist only on macOS; the token comes from `DASHBOARD_TOKEN` (Windows: `CCSYNC_DASHBOARD_TOKEN` or `-DashboardToken`).

## The Resolve Mapped Mount helper (embedded in the macOS bootstrap)
(source: installer/macos_bootstrap.sh, the Python block between the CCSYNC-MAPPING-HELPER sentinels)

- A standalone command `ccsync-resolve-mapping` with three subcommands: `apply`, `verify` (read-only), `remove`. Options: `--local-root` (required for apply and verify; a trailing `/` is stripped), `--mapped-root` (default `P:\`), `--config-dir` (default `BMD_RESOLVE_CONFIG_DIR`, else the standard folders).
- Finds Resolve's preference folder: `BMD_RESOLVE_CONFIG_DIR` used as is; else the first of `~/Library/Preferences/Blackmagic Design/DaVinci Resolve` and the Mac App Store container path `~/Library/Containers/com.blackmagic-design.DaVinciResolve/Data/Library/Preferences/Blackmagic Design/DaVinci Resolve` that holds `config.dat`. Never creates preference files.
- Edits two files that must agree: `config.dat` (`Site.<n>.FS.<i>.Root` / `.MappedRoot`, count `Site.<n>.FS.Count`) and `.config.data` (`IoFsMount_<i>` / `IoFsMappedMount_<i>`, count `IoFsNum`).
- `apply` behaviour per file: an entry already mapping the prefix to the root: nothing; mapping the prefix elsewhere: repointed; an entry for the root without the prefix: the prefix added (plus direct I/O on); otherwise a new entry (`config.dat`: Type `IOFileSys`, Root, MappedRoot, `MacDIO` 1, `BrightClip` 0; `.config.data`: Mount, MappedMount, `DirectIO` 1) inserted before Resolve's own trailing `/Volumes` or `ResolveVirtual` entry. Entries are renumbered keeping the file's own numbering base, and the count line corrected.
- Prefix comparison ignores case and trailing backslashes; local-root comparison ignores a trailing `/`.
- Refuses while Resolve runs (`pgrep -f "DaVinci Resolve"`; no `pgrep` counts as not running) for apply and remove.
- Before writing: backs up BOTH files as `<file>.ccsync-backup-<YYYYmmdd-HHMMSS>`, then writes atomically, keeping the file mode, line endings, spacing and unknown lines. Warns when a file is owned by another user (it will come back owned by the current user).
- Warnings: several Sites declared (only the first is patched); a numbering base other than 0 or 1; a count that disagreed with the entries (corrected); several entries mapping the same prefix (first used).
- Messages: "Resolve already maps <prefix> to <root> (<dir>) -- nothing written", "backed up <file>", "updated <file> (<action>)", "Resolve now maps <prefix> to <root>"; verify: "Resolve maps ...", "no <prefix> mapping in <dir>", "<file> maps <prefix> to <x>, not <root>", "<file> has no <prefix> mapping"; remove: "removed the <prefix> mapping from <file>" or "no <prefix> mapping to remove in <dir>".
- Exit codes: `0` success / already correct / verify OK / removed or absent; `2` bad usage; `3` Resolve running; `4` preference files or folder not found ("... Launch Resolve once, quit it, then re-run."); `5` unrecognised format (no count line, or unreadable count); `6` verify: no mapping; `7` verify: mapping points elsewhere; `8` read, write or backup failure.
- Only `apply` is used by the installer; `verify` and `remove` are reachable only by running the extracted helper by hand.

## macOS uninstaller
(source: installer/macos_uninstall.sh)

- Reached as `~/.local/ccsync/bin/macos_uninstall.sh` (installed there by the bootstrap; the closing banner tells the editor `bash "<path>"`) or from the package. Never touches synced media. Never removes Homebrew-installed Tailscale, rclone or Syncthing, or the SSH key.
- Flags: `--full` (also remove `~/.ccsync` except `state`), `--dry-run`; `-h`/`--help` or an unknown argument prints usage and exits `1`. Lines prefixed `[uninstall] `.
- Reads `local_root`, `remote` (default `ccsync_sftp`) and `canonical_prefix` (default `P:\`) from `~/.ccsync/config.toml` when present.
- Opening lines: the mode, "your synced media is never touched by this script -- only the CCSync software itself.", and "DRY RUN -- nothing will be changed" for a dry run.
- Steps:
  1. LaunchAgents: for `com.ccsync.companion.plist`, `com.ccsync.syncthing.plist` and the legacy `com.creatorsclub.ccsync.companion.plist` / `com.creatorsclub.ccsync.syncthing.plist` in `~/Library/LaunchAgents`: boots out, unloads, deletes.
  2. Processes: kills only `ccsync-companion` and `syncthing` processes whose executable lives under `~/.local/ccsync`; any other (for example a personal Homebrew Syncthing) is left alone with a skip line naming it.
  3. Deletes all of `~/.local/ccsync` (binaries, the uninstaller itself, AND the Syncthing identity in `syncthing-config`), even in the default mode. On success: "removed ... (binaries and the Syncthing identity)" and a warning that a reinstall generates a NEW device ID the admin must approve. If anything survives: "could NOT remove ...: ... Remove it by hand: sudo rm -rf \"<path>\"" and the run is marked incomplete. Dry run: says it "would" remove it and that a reinstall "would" get a new device ID.
  4. rclone: removes only the `[<remote>]` stanza from `~/.config/rclone/rclone.conf` (every other remote kept, file mode 600). No backup is kept.
  5. Without `--full`: keeps `~/.ccsync` ("KEPT your sign-in and settings: ... (config.toml, identity.json, state)") and says "run with --full to also remove your sign-in and settings."
  6. With `--full`: deletes everything in `~/.ccsync` except `state` (config.toml, identity.json, volume.json, logs, known-hosts file, EULA record), re-lists, and reports survivors ("These can hold your sign-in ... Remove them by hand: sudo rm -rf ..."). Then "FULL uninstall: your saved sign-in is gone. A reinstall needs the admin to approve this Mac again ..." or, with survivors, "... your saved sign-in may still be on this Mac ...". Notes the SSH key location if it exists.
- Closing block: "CCSync uninstall complete." (plus " (dry run -- nothing changed)") or "CCSync uninstall NOT complete: some of what it removes is still on this Mac ..."; "Resolve still maps <prefix> -> <local root>; remove it in DaVinci Resolve > Preferences > Media Storage if desired." (the Mapped Mount is deliberately left); the Homebrew note; "YOUR SYNCED MEDIA ON THE SSD WAS NOT TOUCHED -- ...".
- Exit code: not set (0).
- Differences from the Windows uninstaller: the macOS default mode removes the Syncthing identity (Windows keeps it unless `-Full`); macOS removes the rclone stanza (Windows never does); macOS leaves Resolve's Mapped Mount (Windows has none); Windows has drive, share, firewall, PATH and Apps & features steps that macOS lacks.

## First-run wizard: overview, window and start-up
(source: onboarding/onboard.py, onboarding/steps.py)

- One program on both platforms: `onboard.exe` on Windows; a macOS app bundle on a Mac. A single fixed-layout window, title `CCSYNC.EXE: onboarding` (Windows) or `CCSYNC.APP: onboarding` (macOS), 660x560, minimum 560x480, in the companion's dark theme; pages are swapped in place.
- The window grows taller by itself (never shrinks, never wider, capped at screen height minus 80 px) when a page needs more room; each page's button bar is laid out so it is the last thing to lose space.
- Keyboard: Tab moves between buttons (a focus ring appears on the focused one); Enter or keypad Enter presses the focused button; Enter in a form field presses that page's main action (NEXT on the role page, VERIFY on sign-in). A page's enabled NEXT gets focus when it opens; on form pages the first empty field gets it. Enter cannot press a disabled button.
- Page order: (interrupted-install page, only if needed) -> Licence -> Welcome -> (wrong-account refusal, only if needed) -> Step 1 role and dashboard address -> Step 2 Tailscale (remote editors only) -> Step 3 sign in -> Step 4 reporting choices -> Step 5 install -> finish page (remote-editor or wired version).
- Every background result (Tailscale check, sign-in, install, finish pages) is handed to the window through a queue drained every 50 ms.
- Install log file: at start the wizard creates `~/.ccsync/logs/onboard-<YYYYmmdd-HHMMSS>.log` (one per run, kept) and writes the program's own log lines and everything shown in the install log box into it as it happens, line by line. If it cannot be created, the install page says "log file: could not be created (your home folder is not writable), so use COPY LOG before closing this window".
- Interrupted-install record: `~/.ccsync/state/install_in_progress.json` (`phase` = `clean_slate:<role>`, `started_at`, `installer_version`) is written just before the destructive clean-slate step and deleted only when a finish page is reached. An unreadable or malformed file still counts as present. (The comment says the companion refuses to sync while it exists; that is companion behaviour outside this part.) If it cannot be written, the log says "WARNING: could not record that an install is in progress (~/.ccsync/state is not writable). ...".
- Closing the window: free on every page except while an install is running. Mid-install a Yes/No dialog titled "CCSync onboarding" asks "The install is part-way through. Closing now leaves this computer with <loss>. Close anyway?" (default No), where `<loss>` is "no CCSync and no <letter> drive" for a Windows remote-editor install and "no CCSync" for a wired install or any Mac. Yes kills the running bootstrap and everything it started (Windows `taskkill /T /F`, macOS the whole process group), then closes. If the dialog itself fails, the window stays open.
- The "tree drive letter" shown in all page text is the site manifest's (from this run's fetch once signed in, else the cached manifest `~/.ccsync/state/site.json`, else `P`).

## Wizard page: THE LAST INSTALL DID NOT FINISH
(source: onboarding/onboard.py, onboarding/steps.py)

- Shown first, instead of the licence, when the interrupted-install record exists.
- Text: "This computer was part-way through an install when the wizard closed. Until it is finished, there is <loss> on this machine. <tail>" where `<tail>` is "Nothing is syncing." (remote editor), "Your <letter>: drive mappings were not touched, but the companion is not running." (wired, Windows) or "Your NAS mounts were not touched, but the companion is not running." (wired, Mac); then "It started at <time>." when known, and "Finishing the install is safe and is the only thing that fixes it. You will be asked for your sign-in again."
- The role radio is pre-set to the role of the interrupted run (from the record's phase).
- Buttons: CLOSE (closes); FINISH THE INSTALL (goes to the licence page; the record is not cleared until an install finishes).

## Wizard page: LICENCE AGREEMENT
(source: onboarding/onboard.py, onboarding/steps.py)

- Skipped when `~/.ccsync/eula_accepted.json` holds a `version` at least as new (numeric compare, part by part) as the `<!-- EULA-VERSION: x.y -->` marker in the bundled licence. Never skipped when the bundled licence or its marker cannot be found.
- Bundled licence lookup: an explicit path, the frozen bundle's `assets/EULA.md`, `assets/EULA.md` beside the executable, `onboarding/assets/EULA.md`, then `docs/legal/EULA.md` (dev tree).
- Shows the text read-only and scrollable, converted for display: HTML comments removed, top two heading levels in capitals, bold/italic/code markup removed, links shown as "text (url)", em dashes replaced by " - ". (The stored hash is of the raw file.) If no licence is bundled: "The licence document is missing from this build of the installer. Ask your administrator for a copy before continuing ...".
- Intro: "Read the agreement below. ACCEPT records your agreement on this machine and continues; DECLINE closes the installer and nothing is changed." Footer "version <x.y>" (or "?").
- DECLINE: closes the wizard, changes nothing.
- ACCEPT: writes `~/.ccsync/eula_accepted.json` atomically: `version`, `accepted_at` (UTC ISO time), `eula_sha256` (of the licence text with line endings normalised). A write failure is logged and the wizard continues anyway.

## Wizard page: WELCOME
(source: onboarding/onboard.py, onboarding/steps.py)

- Windows text: sets up or refreshes the machine, "removes every trace of older CCSync versions, remounts the project drive, installs the current companion app (which updates itself from the dashboard from now on), and signs it in." macOS text: also "installs the sync tools" and "points DaVinci Resolve's <letter>:\ mapping at your local copy of the project tree." Both end "You'll need two things from your admin: the dashboard address, and the username and password they set up for you. Safe to re-run any time."
- Grey line: "installer v<installer version>, bundles companion v<bundled companion version>" ("?" if unknown).
- Button: NEXT.

## Wizard page: WRONG ACCOUNT (Windows)
(source: onboarding/onboard.py, onboarding/steps.py)

- Checked once, when leaving the welcome page. The console user is read with `(Get-CimInstance Win32_ComputerSystem).UserName` (20 s limit) and compared, ignoring case and any domain or `@` suffix, with the running account (`USERNAME`/`USER`). macOS and Linux never check. A probe that fails or cannot tell never refuses.
- On a mismatch: heading WRONG ACCOUNT, red text "You are running as <x> but <y> is signed in. Everything this installs is per-user, so <y> would get nothing. <y> does not need to sign in again: close this and start the installer again by double-clicking it, and do not choose Run as administrator or type another account's password if Windows asks (it does not need administrator rights).", "Nothing on this computer has been changed.", and only a CLOSE button.

## Wizard page: STEP 1: HOW IS THIS MACHINE CONNECTED?
(source: onboarding/onboard.py, onboarding/steps.py)

- Intro: "Pick how this computer reaches the footage. Any number of machines can sit on the studio network and work straight off the NAS."
- Radio "I'M A REMOTE EDITOR" (stored role `editor`). Windows subtitle: "Installs Tailscale, the sync tools, and maps the <letter>: project drive (re-created fresh)." macOS: "Installs the sync tools and points Resolve's <letter>:\ mapping at your local copy of the project tree."
- Radio "I'M PHYSICALLY CONNECTED TO THE SERVER/NAS" (stored role `base`, called "wired" in this document). Windows subtitle: "... Installs only the companion app - no sync tools, and your <letter>: drive mappings are NOT touched." macOS: "... works directly off the NAS share mounted under /Volumes. Installs only the companion app - no sync tools, and your NAS mounts are NOT touched."
- Starting selection: the `mode` in this computer's existing `~/.ccsync/config.toml` if it is `editor` or `base`, else `editor` (or the interrupted run's role, see above).
- Field "dashboard url (REQUIRED -- your admin gives you this):". Prefilled from environment variable `CCSYNC_DASHBOARD_URL` (remote) or `CCSYNC_BASE_DASHBOARD_URL` (wired); both empty by default. Switching the radio swaps the prefill only while the field still holds one of those two defaults; it also swaps the local-root prefill (see the install page) only while that still holds a default.
- NEXT (also Enter in the field):
  - Adds a scheme to an address typed without one and writes it back into the field: `http://` for an IP address, `localhost`, `127.0.0.1`, `::1` or a `.local` name; `https://` for a `.ts.net` name (any port), for a name with no port, or with port 443; otherwise `http://`. The next page shows "(you typed '<x>', which has no http:// or https:// in front. Go Back and edit it if the one above is wrong.)" in amber.
  - Empty: "dashboard url is required -- ask your admin for it (e.g. http://<your-dashboard>:8480)".
  - Plain http to a public internet address (judged by the companion's own address table, which may look the name up): refused with "<url> is plain http on the public internet, so your password would cross it unencrypted. Nothing was sent. Ask your admin for the dashboard's https address." A check that fails never refuses. A second NEXT while the check runs is ignored; an edit during the check discards its answer.
  - Then: wired goes to sign-in; remote editor goes to the Tailscale page.
- BACK: welcome page.

## Wizard page: STEP 2: JOIN THE NETWORK (remote editors only)
(source: onboarding/onboard.py, onboarding/steps.py)

- Intro: "The project server lives on a private Tailscale network. Install Tailscale and sign in with the invite link your admin sent you, then come back here and check the connection."
- Status line "Tailscale: INSTALLED" (green) or "Tailscale: NOT INSTALLED" (amber), read from disk when the page opens and after every check: `tailscale` on PATH, else `%ProgramFiles%\Tailscale\tailscale.exe` (Windows) or `/Applications/Tailscale.app` / its inner CLI (macOS).
- Button INSTALL TAILSCALE (winget) (Windows only): runs `winget install --id Tailscale.Tailscale -e --accept-source-agreements --accept-package-agreements` (shows "installing via winget... this opens its own window"). Success is judged by Tailscale being on disk afterwards: green "Tailscale is installed. Sign in to it (its icon in the tray), then press CHECK CONNECTION." or red "winget did not install Tailscale (winget exit code <n>). Try OPEN DOWNLOAD PAGE and run the installer from there." An exception: "winget install failed: <error>. Try OPEN DOWNLOAD PAGE instead."
- Button OPEN DOWNLOAD PAGE: opens `https://tailscale.com/download/windows` or `https://tailscale.com/download/mac` in the browser.
- Grey line "dashboard: <url>", plus the amber "you typed" note, plus (worked out in the background) the companion's amber note for an allowed plain-http local or tailnet address.
- Button CHECK CONNECTION (has focus; one check at a time per page; greyed while running; shows "checking..."):
  - Tailscale joined: runs `tailscale status` (15 s limit; tries `tailscale` then the install location); joined when it exits 0 and the output does not contain "logged out", "needs login" or "stopped". Not joined: red "tailscale isn't joined yet -- open the Tailscale tray icon and sign in" ("menu-bar" on macOS).
  - Then `GET <dashboard>/api/v1/health` (10 s, never following a redirect, refusing public plain http). Results shown in amber: no address ("no dashboard address set. Ask your admin for it."); unknown host ("that address does not exist on this network: <url>. Check the spelling with your admin."); timeout ("<url> did not answer in time. If you have just signed in to Tailscale, wait a few seconds and check again."); refused ("<url> refused the connection: the address exists, but nothing is serving the dashboard on that port. Check the port with your admin."); an HTTP error ("<url> answered with an error (<code>). The address is right, so this is the dashboard's end: tell your admin."); a redirect ("the dashboard answered with a redirect (<code>) to <target>. CC Sync never follows one, so nothing more was sent. Ask your admin for the dashboard's direct address."); public plain http (the refusal sentence); other ("could not reach <url>: <error>").
  - Success: green "connected: the dashboard is answering" and NEXT becomes enabled and focused.
  - No address: "no dashboard url set -- go Back and enter the one your admin gave you".
- NEXT starts disabled. BACK: role page.

## Wizard page: STEP 3: SIGN IN
(source: onboarding/onboard.py, onboarding/steps.py)

- Intro: "Enter the username and password your admin set up for you. This is checked against the dashboard right now -- if it doesn't match, the install will not proceed."
- Fields `username:` and `password:` (masked with `*`). Enter in either presses VERIFY & CONTINUE.
- Shows the dashboard address note as on the Tailscale page.
- VERIFY & CONTINUE:
  - Both fields required ("username and password are both required"); no address ("no dashboard url set -- go Back to the role page ..."); a second press while verifying shows "still verifying the last attempt...".
  - Adds a missing scheme as above (the wired path never saw the Tailscale page).
  - `POST <dashboard>/api/v1/verify` with JSON `{username, password, machine: <this computer's network name>}`, 15 s timeout, never following a redirect, refused before sending for a public plain-http address. Shows "verifying against the dashboard...".
  - Failure: red "sign-in failed: <reason>" (the companion's wording for 401/429/503 and other HTTP errors, the redirect sentence, or the network error), and the password field is cleared.
  - Success: keeps the returned `username`, identity `token`, `report_token`, `role` and `report_token_kind`; then fetches `GET <dashboard>/api/v1/site` (5 s) and caches it to `~/.ccsync/state/site.json` (a failure leaves an empty manifest; the cached file, if no older than 30 days and from the same dashboard host and port, is used instead where a value is needed). Re-applies the local-root prefill from the fetched tree name. Goes to the reporting page.
  - The role the account has on the dashboard does NOT change the radio choice.
  - Decides whether a per-editor fleet key must be asked for: only when the dashboard said `report_token_kind = "editor"`, gave no shared `report_token`, and this computer holds no per-editor key already (in `identity.json` `editor_report_token`, or `config.toml` `report_token`).
  - A result that arrives after the editor left the page is ignored.
- BACK: role page (wired) or Tailscale page (remote).

## Wizard page: STEP 4: WHAT THIS COMPUTER REPORTS
(source: onboarding/onboard.py, onboarding/steps.py)

- Intro: "Choose what this computer tells the dashboard. Sync works the same whichever you pick, and you can change these later in the companion's Settings, THIS COMPUTER, PRIVACY. Switching one off also deletes what the dashboard already holds about it."
- Four tick boxes, each with a grey "cost" line:
  - "The name of the open Resolve project". Off: "the dashboard does not offer to set up a new project for it, you cannot be the first to map a Resolve project to a folder (an admin can), and projects are not mapped automatically from this computer."
  - "The list of media files on this computer". Off: "file names in the Resolve and conflict checks are sent only as counts, the dashboard sends this computer every file move in every active project, and shows its holdings and upload progress as not reported."
  - "The Resolve bin structure". "Also off whenever the project name is off, because bins are organised by project."
  - "How long since the keyboard or mouse was used". Off: "background jobs that wait for an idle computer are not offered to this one."
- Starting ticks: this computer's own `report_*` keys in `config.toml` (absent = on; present but not true/false = off; an unparseable file is read from its last good copy; no file = all on).
- A box the site manifest switches off for everyone is shown unticked, greyed, with the amber note "Turned off for everyone by your administrator". The bins box is greyed and unticked with "Off while the project name is off" whenever the project-name box is off. Greyed boxes keep this computer's own answer underneath.
- Grey footer: "Still sent, because sync or your own action needs them: the names of files being transferred and recently transferred, the result of a file move the dashboard ordered, a project name you type or send when setting up a project, and, only if the Timeline Cards agent is turned on for this computer, the project and timeline it is driving."
- NEXT: install page. BACK: sign-in page.

## Wizard page: STEP 5: INSTALL
(source: onboarding/onboard.py, onboarding/steps.py)

- Heading "STEP 5: INSTALL  (signed in as <username>)" and a role- and platform-specific sentence (removes older versions; remote Windows: "remounts your <letter>: project drive fresh, installs Tailscale/rclone/Syncthing (if needed) and the companion app"; remote Mac: installs rclone/Syncthing and the companion and "points Resolve's <letter>:\ mapping at your sync folder"; wired: installs and signs in the companion, drive mappings or NAS mounts "are NOT touched").
- Field "local sync folder:" (remote) or "project tree root:" (wired), with a grey hint per role and platform ("Point this at a drive with room to spare ... doesn't have to be C:."; Mac remote: "Best on an external SSD, plugged in right now: /Volumes/YourSSD/CCSync ..."; wired: "The project-tree folder on the NAS mapping ..." / "... on the NAS share ... mount the share first if it isn't under /Volumes yet.").
- Prefill: remote Windows `C:\<tree name>`, remote Mac `~/<tree name>` (tree name from the manifest, else `CCSync`; a name with a slash, `.` or `..` counts as none); wired Windows `<site letter>:\`; wired Mac empty.
- Validation, re-run on every keystroke; a problem shows in red with a cross and disables BEGIN INSTALL. Windows: empty ("enter a folder for the project tree, e.g. C:\CCSync"); leading or trailing space; a double quote; not starting with a drive letter (a `\\server\share` path gets its own message); for remote editors only, a bare volume root like `D:\` ("... on its own is the whole volume -- the install shares this folder over the network and maps <letter>: at it ...") and any path on the tree drive letter itself ("<letter>: is the drive this installer creates for you -- pick the real folder it should point at ..."); a drive letter that does not exist ("drive D: does not exist on this machine"). macOS: empty (example differs by role), leading or trailing space, a leading `~` ("write the full path instead of ~ ..."), not starting with `/`, `/` or `/Volumes` alone, for remote editors a bare `/Volumes/<Name>` ("... is the whole drive -- pick a folder ON it instead ..."), and a `/Volumes/<Name>` that is not a mount point (remote: "... is not a mounted drive right now -- plug the SSD in (and unlock it if encrypted) ... a leftover folder from an unclean eject may be in the way ..."; wired: "... is not mounted right now -- connect the NAS share first (Finder > Go > Connect to Server) ..."). A probe that itself fails never blocks.
- Amber free-space line (never blocks), only when the path is otherwise valid: "This drive has <N> GB free. Synced proxies for one project are typically 50 to 300 GB." when under 200 GB.
- Fleet key field (only when the sign-in decided one is needed): amber explanation "This dashboard gives every computer its own fleet key. Paste the report token your admin made for you (it starts with cce1., from Settings > Users > REPORT TOKENS). You can leave it empty and add it later, but nothing syncs until it is in." and a `report token:` field. Checked when BEGIN INSTALL is pressed: blank is allowed; surrounding spaces ("remove the space before or after the key") or anything not shaped `cce1.<16 hex>.<48 hex>` ("that is not a report token: ...") refuses.
- Buttons: BEGIN INSTALL; COPY LOG (puts the whole log file, or the box's text if there is no file, on the clipboard and flashes "[ COPIED ]" for 1.2 s); BACK (to the reporting page). While installing, BEGIN INSTALL and BACK are disabled.
- Live log box (read-only, scrolling) showing every step and every bootstrap line as it is printed; below it "log file: <path>".
- On failure BEGIN INSTALL turns into "[ RETRY INSTALL ]" and BACK is re-enabled.

## Wizard: what BEGIN INSTALL does (remote editor)
(source: onboarding/onboard.py, onboarding/steps.py)

1. Refuses (log message and RETRY) when the running installer is on a forbidden location, frozen builds only: Windows: on the site's tree drive letter, on `P:` on any site, or on a `\\` network path ("this installer is running from <letter>: or a network share - the install is about to unmount that drive out from under itself (and running it off the NAS locks the file for everyone). Copy onboard.exe to your Desktop and run it from there."). macOS: under `/Volumes/`, or on any volume other than the boot volume, its data volume or the home folder's ("this installer is running from a volume under /Volumes ... Copy the app into your home folder (Downloads or Desktop) and run it from there."). A probe that cannot tell does not refuse.
2. Re-checks the address for public plain http ("not installing: <reason>").
3. SSH key `~/.ssh/ccsync_ed25519`: both halves present: nothing. Private key only: derives the `.pub` with `ssh-keygen -y`. Neither: `ssh-keygen -t ed25519 -f ~/.ssh/ccsync_ed25519 -N ""` (no passphrase), 60 s limit. Failures (no `ssh-keygen`: "ssh-keygen was not found. Install the Windows OpenSSH Client (Settings > System > Optional features > Add > OpenSSH Client) and re-run the installer."; non-zero exit; no `.pub`) are not fatal but become a "no SSH key: ..." warning that makes the finish page NOT READY. Never overwrites an existing key.
4. Clean slate (see below), after writing the interrupted-install record.
5. Writes `config.toml` and `identity.json` (see below). Logs "config written (mode=editor).", which reporting categories were switched off, and, when something was switched off and the bundled companion is version 0.9.80 or older (or its version cannot be read from the `ccsync-release.json` beside it), a warning that the switches are not honoured by that build. With a fleet key asked for and none given: warning "no fleet key: this dashboard no longer hands out the shared report token, and no report token was entered, so the dashboard will refuse every report from this computer ..." (NOT READY).
6. Offers the SSH public key: `POST <dashboard>/api/v1/ssh-key` with header `X-CCSync-Identity: <identity token>` and JSON `{username, ssh_pubkey, machine: <host name>}`, 15 s. Success: "SSH public key sent to the dashboard: your admin approves it on the Users page." Failure is logged only.
7. Finds the bundled companion (`ccsync-companion.exe` / `ccsync-companion` in the frozen bundle, beside the executable, `onboarding/`, or `companion/dist/`); not found is logged and the bootstrap runs without it.
8. Runs the platform bootstrap from the bundle, streaming every line into the log; 1800 s limit, after which the whole process tree is killed and the log says "bootstrap timed out after 1800s -- it may be stuck on a prompt (e.g. winget) or a stalled download; re-run the installer, or run <script> by hand to see where it hangs." (exit treated as 1).
   - Windows: `powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File windows_bootstrap.ps1 -TailnetHost <host> -EditorName <verified user> -DashboardUrl <url>` plus, when known, `-RemoteRoot`, `-NasSyncthingId`, `-SftpPort` (only when not 22), `-LocalRoot`, `-CanonicalPrefix`, `-TreeName`, `-CompanionExeSource`.
   - macOS: `bash macos_bootstrap.sh --tailnet-host <host> --editor-name <user>` plus `--remote-root`, `--sftp-port` (not 22), `--local-root`, `--companion-file`.
   - The host is the manifest's `sftp_host`, else the host part of the dashboard URL.
   - Environment given to the bootstrap: `CCSYNC_DASHBOARD_TOKEN` (the shared report token; never on the command line), `CCSYNC_FROM_WIZARD=1`, `CCSYNC_NAS_SYNCTHING_ID` (when known), `CCSYNC_RCLONE_REMOTE`, `CCSYNC_SFTP_SHELL_TYPE`, `CCSYNC_SFTP_HOSTKEY` (each only when the manifest published it, otherwise removed from the inherited environment); on macOS also `DASHBOARD_TOKEN`, `DASHBOARD_URL`, `CCSYNC_CANONICAL_PREFIX`, `CCSYNC_TREE_NAME`. Canonical prefix and tree name are passed only when this run's manifest (or a recent same-dashboard cached one) actually published them.
9. Re-asserts `editor_name` in `config.toml` if it differs from the verified username.
10. Reads the bootstrap output: every `CAPABILITY MISSING:` line (and some older phrasings) becomes a warning; a macOS `RESOLVE-MAPPING-STATUS:` other than ok/dry-run/skipped/unset becomes a warning worded per status (running, never-launched, not-installed, format, no-python, error, or "reported an unexpected status").
11. Exit code: `0` success; `3` with at least one capability line: finished but NOT READY; anything else (including `3` with no capability lines): "bootstrap exited with code <n> -- it stopped part-way through, so this install did NOT finish (only exit 3 means 'finished, but something is missing'). See the log above." and RETRY.
12. Resolve External scripting (both platforms, remote editors only): detects Resolve; if it is not found and has no preference files, the note "Could not find DaVinci Resolve on this computer. CC Sync's Resolve features need Resolve Studio, the paid edition (the free edition has no scripting). Install Studio, open it once, quit it, then run this installer again."; otherwise writes "External scripting using = Local" into Resolve's preferences through the companion's preference code (never through Resolve's scripting connection). Outcomes: done or already set (no note); Resolve open ("... Quit Resolve, then in Resolve open Preferences > System > General and set 'External scripting using' to Local."); never opened ("... After its first launch, open Preferences > ..."); preference files incomplete ("... set 'External scripting using' to Local and click Save."); other. When a Studio licence is found, " (Resolve Studio licence found.)" is appended to a note. Logs "Resolve scripting preference: <status>".
13. Parses the Syncthing device ID from the output and shows the remote-editor finish page.
- Any unexpected error: "install failed: <error>" and RETRY.

## Wizard: what BEGIN INSTALL does (wired machine)
(source: onboarding/onboard.py, onboarding/steps.py)

1. Before anything else, finds the bundled companion; missing: "companion app not bundled with this installer (...). Nothing has been changed on this machine. Get a complete CC_Sync package (onboard.exe next to ccsync-companion.exe) and run that instead." and RETRY.
2. Re-checks the address (as above). No forbidden-location check, no SSH key, no bootstrap, no Resolve scripting step.
3. Clean slate (role `base`: the drive is never unmounted).
4. Writes `config.toml` and `identity.json`.
5. Copies the companion into `%LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe` (Windows) or `~/.local/ccsync/bin/ccsync-companion` (macOS, made executable 755).
6. Windows: sets HKCU Run value `CCSyncCompanion` to the exe, then starts it detached with no console window and a clean PyInstaller environment, waits 3 s: "companion launched and running (check your tray)." or "WARNING: companion did not stay running -- start it by hand (<exe>) and check ~/.ccsync/companion.log." macOS: retires the legacy `com.creatorsclub.*` agents, writes `~/Library/LaunchAgents/com.ccsync.companion.plist` (same content as the bootstrap's: RunAtLoad, AbandonProcessGroup, no KeepAlive) and loads it (bootout, unload, bootstrap, fallback load): "companion LaunchAgent loaded (check your menu bar)." or a warning with the `launchctl bootstrap` command.
7. Shows the wired finish page.

## Wizard: the clean slate (removing older installs)
(source: onboarding/steps.py, onboarding/onboard.py)

- Windows, in order (warnings collected, never fatal):
  1. `taskkill /F /IM ccsync-companion.exe` and `ccsync-companion.new.exe`.
  2. Syncthing: lists running `syncthing.exe` processes; kills only those whose executable is under `%LOCALAPPDATA%\ccsync`, the bin folder, or `~/.ccsync` ("stopped our Syncthing (pid n, path)"); any other is left alone with the warning "another Syncthing is running from <path> (pid n) -- left alone; it is not ours to stop or restart".
  3. Kills any `pythonw.exe` running `launcher.py`. Waits 1 s.
  4. Deletes HKCU Run values `CCSyncCompanion`, `CCSyncSyncthing`, `CCSyncSubst<site letter>`, `CCSyncSubstP`, `ccsync-companion`.
  5. Deletes scheduled tasks `CCSync-Subst<site letter>` and `CCSync-SubstP` (`schtasks /Delete /F`). "Access denied" gives a warning with the exact admin command, explicitly not "re-run as administrator".
  6. Deletes old companion files (`ccsync-companion.exe`, `.exe.old`, `ccsync-companion.new.exe`) in: the bin folder; for remote editors the chosen local root and the `local_root` of the existing config; `C:\<tree name>`; `C:\Creators_Club` (the pre-2026-08-17 default); for remote editors `<letter>:\`; the folder the old `CCSyncCompanion` Run value pointed at; `~/.ccsync/bin`. Three tries 1 s apart; a locked file is renamed `<file>.stale-<epoch>` with a warning.
  7. Deletes shim files `CCSyncSubst<letter>.cmd/.vbs`, `CCSyncSubstP.cmd/.vbs`, `CCSyncSyncthing.cmd/.vbs` in the bin folder and `ccsync-companion.cmd/.vbs` in `~/.ccsync/bin`; removes `~/.ccsync/bin` if now empty.
  8. Remote editors only: reads the tree drive's mapping (`subst`, then `net use <letter>:`). Ours (subst, or `\\localhost\CCSync_<letter>`): `subst <letter>: /D` and `net use <letter>: /delete /y`, then warns "<letter>: is still mapped after unmounting -- something has files open on it; close those apps and retry" if it is still there. Not ours (including the manifest's `smb_unc` share, any other UNC, or unreadable mappings): left alone with a warning explaining why and how to disconnect it by hand.
- macOS, in order: boots out and unloads `com.ccsync.companion`, `com.ccsync.syncthing` and the two legacy `com.creatorsclub.ccsync.*` agents; sends SIGTERM to `ccsync-companion` / `ccsync-companion.new` processes whose executable is that binary or under `~/.local/ccsync` / `~/.ccsync`; does the same for Syncthing under those folders (others left alone with the same warning); deletes the plist files; deletes `ccsync-companion`, `.old`, `.new`, `.ccsync-new` from `~/.local/ccsync/bin`. No drive, Run values or tasks.
- Never removed on either platform: rclone and Syncthing binaries, the Syncthing identity folder, SSH keys, `identity.json`, `config.toml`, `rclone.conf`, `volume.json`.
- Every action and warning goes to the log ("removing traces of previous CCSync versions...", "clean slate done.").

## Wizard: what it writes into config.toml and identity.json
(source: onboarding/steps.py)

- `~/.ccsync/config.toml`: an existing file is merged line by line (comments, other keys and order kept); a missing file starts from the companion's default template. A file that is not valid UTF-8 is renamed `config.toml.unreadable-<epoch>` and replaced from the template. Keys added at the end go under `# -- set by the CCSync installer --`.
- Always set (overwriting): `editor_name` (verified username), `dashboard_url`, `mode` (`editor` or `base`).
- `dashboard_token`: set when the sign-in returned a shared report token; otherwise only filled in when absent or blank (an existing token is never blanked).
- `report_token`: set when a per-editor key was pasted; never cleared.
- The four reporting switches (`report_*` keys whose exact names come from the companion's policy table): written true/false when the reporting page was shown; left untouched otherwise.
- Wired: `local_root` and `canonical_prefix` both set to the chosen root.
- Remote: `canonical_prefix` = the site's prefix (`<letter>:\`, manifest or cache, else `P:\`); `local_root` = the chosen folder; `remote` = the manifest's `rclone_remote` when published, else left as is, else `ccsync_sftp` if blank; `remote_root` = the manifest's `remote_root` only when the key is absent or blank (never overwrites, never writes a blank).
- `~/.ccsync/identity.json`: written when the sign-in returned a token, through the companion's own identity code: username, identity token, the account's role (diagnostics only), the shared report token (or the previous one if none came back), and any per-editor key already there.
- `~/.ccsync/state/site.json`: the cached site manifest.
- `~/.ccsync/eula_accepted.json`, `~/.ccsync/logs/onboard-*.log`, `~/.ccsync/state/install_in_progress.json`: see above.

## Wizard finish page: remote editor
(source: onboarding/onboard.py, onboarding/steps.py)

- Reaching it deletes the interrupted-install record.
- With warnings: heading "COMPLETED WITH <n> WARNING(S): NOT READY YET", amber "This machine is NOT ready to sync. Do not tell your admin you are set up until the problems below are fixed. Send them this list instead. ...", then up to 6 warnings in red, and "... and <n> more. All of them are in the install log (use COPY LOG at the bottom of this page, or the file named there)." when there are more.
- Without warnings, and the SSH key was sent: heading "DONE: SEND YOUR DEVICE ID TO YOUR ADMIN", intro that nothing syncs until the admin approves this computer and that the companion is installed and signed in as <user>, hint that the key is already waiting on the dashboard's Users page, and "Send the Syncthing device ID above to your admin to finish signup."
- Without warnings, key not sent: heading "DONE: SEND THESE TWO VALUES TO YOUR ADMIN", "Send these two values to your admin to finish signup."
- Read-only field "Syncthing device ID:" with COPY; when not found it shows "(not found automatically - open http://127.0.0.1:8384, Actions > Show ID)" and the button reads "NOTHING TO COPY" (disabled).
- Read-only field "SSH public key:" with COPY; when absent "(no SSH public key found - check ~/.ssh/ccsync_ed25519.pub)" and "NOTHING TO COPY". COPY flashes "[ COPIED ]".
- "Connect Resolve" checklist (amber heading "BEFORE YOU OPEN A PROJECT, CONNECT RESOLVE (needs DaVinci Resolve Studio):"): 1. Project Manager > Add Project Library > PostgreSQL, "Host: <manifest sftp_host, else the dashboard's host, else 'ask your admin'>", user name and password from the admin; 2. "External scripting is already set to Local ..." when the scripting step succeeded, else the manual instruction plus the step's note; 3. "Open the shared project. Playback > Proxy Handling > Prefer Proxies."
- "Problems? Contact <support contact from the manifest, else the vendor default>".
- "install log: <path>".
- Buttons: CLOSE; COPY LOG; OPEN-SOURCE LICENCES (opens a 720x560 read-only window with the bundled third-party licence texts, from `assets/THIRD_PARTY_LICENSES.txt` in the bundle or the companion's copy or dev-tree copies; if none: "The open-source licence texts are not bundled in this build. Copies are available on request from the contact address in the licence agreement."; its own CLOSE).

## Wizard finish page: wired machine
(source: onboarding/onboard.py, onboarding/steps.py)

- With warnings (in practice only the missing fleet key): "INSTALLED WITH <n> WARNING(S): NOT READY YET" and the list. Otherwise "DONE: CONNECTED TO THE NAS".
- Text: "The companion app is installed, signed in as <user>, and will start automatically at login. No sync lanes run on this machine (it works directly off the NAS); the tray (menu bar) still watches your Resolve timeline for media outside the project tree, and future companion updates arrive as a one-click prompt in the tray."
- "dashboard: <url>", the same Resolve checklist (scripting is never written here, so item 2 is always the manual instruction), support line, log path, and the same three buttons.

## Building the wizard executables
(source: onboarding/build_onboard.spec, onboarding/build_onboard_macos.spec, onboarding/requirements.in, onboarding/requirements.lock)

- Windows `onboard.exe`: a single-file, windowed (no console) executable with the CC Sync icon and a Windows version resource ("CC Sync setup wizard", version = the installer version, original name `onboard.exe`). Not UPX-packed. Bundles: `windows_bootstrap.ps1`, `drive_mapping.ps1`, `windows_uninstall.ps1`, `ccsync-companion.exe`, the companion's `ccsync-release.json` when present, three brand images (the Creators Club mark as the default, a neutral CC Sync mark, the legacy icon), `assets/EULA.md`, `assets/THIRD_PARTY_LICENSES.txt`, `assets/THIRD_PARTY_NOTICES.md`.
- macOS `CCSync Onboarding.app`: built only on a Mac (the spec refuses elsewhere), folder-style build wrapped in an app bundle, bundle id `com.ccsync.onboard`, `CFBundleShortVersionString` `1.0.47`, ad-hoc code signature, no icon file. Bundles `macos_bootstrap.sh`, `macos_uninstall.sh`, the macOS companion binary, the same release manifest, images, EULA and licence texts.
- Both builds refuse to start without the companion binary already built and without the two licence-text files.
- Both leave out the companion's tray, watcher, popup, fixer, Resolve bridge, selection, consolidate, manifest and lane modules and their heavy dependencies, and `setuptools`.
- No runtime Python dependencies; the lock file pins only the test runner (`pytest` 9.1.1 and its dependencies, with hashes).

## Documents shipped in the editor package and in these folders
(source: installer/START_HERE.md, installer/FIRST_UPGRADE.md, installer/README.md, installer/MACOS_FIRST_RUN.md, onboarding/README.md, onboarding/assets/EULA.md)

- `START_HERE.md` (in the package): editor-facing instructions: run `onboard.exe` (copied to the Desktop first), how to get past SmartScreen ("More info" > "Run anyway", Unblock, Smart App Control) and Gatekeeper ("Open Anyway"), the manual PowerShell and Terminal routes, the "never map a NAS share to a drive letter yourself (T: collides)" warning, connecting Resolve, and how to update and uninstall.
- `FIRST_UPGRADE.md` (in the package): a one-time "run `.\windows_upgrade.ps1`" note for machines whose companion could not yet update itself.
- `EULA.md`: the licence the wizard displays and records (marker `EULA-VERSION: 1.1`, 14 sections). Not a feature in itself; its version marker drives the wizard's and the upgrade script's re-consent checks.
- `installer/README.md`, `installer/MACOS_FIRST_RUN.md`, `onboarding/README.md`: developer documentation and a first-Mac-session checklist; they do not change behaviour.

## Looks redundant or overlapping

- Two independent "clean slate" implementations of uninstall-like removal: the wizard's clean-slate step (Windows and macOS) and the two uninstall scripts enumerate overlapping process, autostart, task, plist and file lists separately, with different rules (the wizard keeps the Syncthing identity; the macOS uninstaller's default mode deletes it; the Windows uninstaller keeps it).
- The "is the tree drive ours?" test exists twice: in `drive_mapping.ps1` (bootstrap and uninstaller) and re-implemented in Python in the wizard (`p_mapping_is_ours`), with slightly different inputs (the wizard also knows the site's `smb_unc`).
- Companion autostart and launch are written in three places: the Windows bootstrap (Run value + launch + 3 s check), the wizard's wired-machine path (Run value + detached launch + 3 s check), and the upgrade script (Run value + launch + 3 s check + rollback). The macOS LaunchAgent plist is likewise written by both the macOS bootstrap and the wizard's wired path.
- Resolve preferences are set from three places: the bootstraps call the companion's `--setup-resolve-prefs` (LUT library and stills folder, and on Windows the scripting setting per the closing banner), the wizard separately writes "External scripting = Local", and the macOS bootstrap carries its own embedded Python helper for the Mapped Mount (with `verify` and `remove` subcommands nothing calls).
- Both bootstraps and the wizard fetch the site manifest independently; the wizard then passes most values to the bootstrap through flags and environment variables, so most of the bootstrap's own fetch is a fallback for hand runs.
- Config seeding: the bootstraps write a full seeded `config.toml` only when none exists, but in the wizard flow the wizard always writes it first, so the bootstrap's seeding branch is only reached on a hand run; both then also repair `rclone_path`.
- The companion is installed on Windows by copying a bundled exe (bootstrap `-CompanionExeSource`, wizard wired path, upgrade script) and on macOS either by copying (`--companion-file`) or by downloading from the dashboard; three update paths (upgrade script, in-app self-upgrade referenced by the docs, re-running the wizard) coexist.
- Low-free-space warnings are computed in three places (Windows bootstrap, macOS bootstrap, wizard) with the same threshold and wording.
- The wrong-account check exists in both the Windows bootstrap and the wizard with near-identical text.
- `build_editor_package.ps1` duplicates parts of the release tooling (manifest restamping, signing, publishing, Authenticode checks, macOS channel advisories) that it says other tools also perform.

## Claims the code does not back

- `macos_bootstrap.sh` header says "NOTHING IN THIS FILE HAS RUN ON A REAL MAC YET", while comments in the same file describe fixes found "live on the first real Mac (2026-08-04)".
- `onboarding/README.md` says the Windows clean slate "kills companion/syncthing processes" and removes "all four historical autostart Run values" and "the `CCSync-SubstP` task": the code kills only Syncthing processes running from CC Sync's own folders, removes five Run values, and removes the site-letter task plus the P task.
- `onboarding/README.md` says wired mode uses the "LAN dashboard URL": the URL is whatever is typed (the only LAN default is the optional environment variable `CCSYNC_BASE_DASHBOARD_URL`).
- `onboarding/README.md` says "No code signing is set up" for `onboard.exe`; `build_editor_package.ps1 -RebuildOnboard` Authenticode-signs it when a signing identity is configured and refuses to make an unsigned one current without `-AllowUnsignedBinary`.
- `onboarding/README.md` and `START_HERE.md` say sign-in uses "TrueNAS"/"NAS" credentials; the code posts to the dashboard's `/api/v1/verify`, whatever account system the dashboard uses.
- `installer/README.md` says `macos_uninstall.sh` has "the same semantics" as the Windows uninstaller, and `START_HERE.md` says the Mac uninstaller has the "same two modes": the macOS default mode deletes the Syncthing identity (and the rclone stanza); the Windows default keeps the identity and never touches rclone.conf.
- `installer/README.md` says the macOS bootstrap script is published to the dashboard by `build_editor_package.ps1 -Publish`; the code explicitly does not publish any macOS artefact since installer 1.0.17.
- `steps.run_bootstrap` docstring says the bootstrap installs the companion "into place (P:\ once mapped)"; it is installed to `%LOCALAPPDATA%\ccsync\bin`.
- `build_onboard_macos.spec` says the macOS bootstrap copies the uninstaller "into ~/.ccsync/bin"; it copies it to `~/.local/ccsync/bin`.
- The macOS forbidden-location message says "the install is about to unmount it out from under itself"; no macOS install path unmounts anything.
- `windows_upgrade.ps1` summary for a failed copy says "the previous build was relaunched instead"; that is only true when a previous build existed and stayed up.
- `windows_upgrade.ps1` description says step 4 adds "any config keys the new version needs"; it only ever adds `dashboard_url`, `dashboard_token` and `mode`.
- `windows_bootstrap.ps1` description says "No step aborts the run"; several steps exit (missing drive library, no dashboard URL, bad prefix, quote in the local root, no winget for Tailscale), and any uncaught error stops the script.
- `START_HERE.md` and the Windows bootstrap banner say a UAC prompt appears once during the wizard install for the drive name; on a run where the share already exists, or the subst fallback is used, no prompt appears, and the firewall rule then needs a manual command.
- The wired-machine finish page shows the "connect Resolve" checklist as if the scripting step ran; the wired install never runs it, so item 2 is always the manual instruction.

## Could not determine

- Whether the companion really refuses to sync while `~/.ccsync/state/install_in_progress.json` exists, and what `--setup-resolve-prefs --wait-for-resolve` changes in Resolve (companion code, outside this part).
- What exactly `resolve_prefs.enable_scripting` and `detect_resolve` write and detect, and which file `site.support_contact` reads (companion modules, not read here).
- Which four config key names the reporting switches use (they come from the companion's `telemetry_policy` table, not read here); the labels and costs are as quoted.
- What the dashboard returns from `/api/v1/verify`, `/api/v1/ssh-key`, `/api/v1/site`, `/api/v1/companion/package/macos/<version>` and the admin package routes beyond the fields these scripts read.
- Whether the macOS onedir wizard build and the macOS paths of the bootstrap and uninstaller work on a real Mac; the code's own comments say parts were never run.
- `installer/README.md` was read only in its section headings and lines 453 to 505; `installer/MACOS_FIRST_RUN.md` and `onboarding/assets/EULA.md` were read only for their headings and version marker. Any further claims in those three documents were not checked.
