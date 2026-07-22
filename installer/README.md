# installer/ -- Creators Club Sync: editor bootstrap scripts

Per-editor bootstrap scripts that get a new remote editor's Windows or Mac
machine ready for the sync system: Tailscale, rclone, Syncthing,
`C:\Creators_Club` / `~/Creators_Club`, the `P:` mapping (Windows) or
Mapped Mount prep (Mac -- the actual Resolve preference is a manual step,
see `../docs/EDITOR_SETUP.md`), rclone remote config, and a companion-app
autostart entry (best-effort, since the companion app is built separately
in `companion/` and may not exist on disk yet).

**Neither script has been run.** They were parse-checked and, for the
Windows script, exercised end-to-end with `-DryRun` on a real Windows
PowerShell 5.1 host (this one) to confirm every mutating step is properly
gated -- confirmed no files, registry keys, or scheduled tasks were created.
The macOS script was syntax-checked with `bash -n` and exercised with
`--dry-run` under Git Bash (not a real Mac -- brew/launchctl/plutil calls
were never actually reached because dry-run guards them, same pattern as
the Windows script); it has **not** been run on an actual Mac.

## windows_bootstrap.ps1

```powershell
.\windows_bootstrap.ps1 -TailnetHost truenas.tailnet.ts.net -EditorName jsmith
```

PowerShell 5.1 compatible: no `&&`, no ternary/null-coalescing operators,
every branch is a plain `if`/`else`. Requires an execution-policy bypass to
run at all on a default Windows install, e.g.:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows_bootstrap.ps1 -TailnetHost <host> -EditorName <name>
```

Steps (each idempotent, each prints what it did/skipped):
1. Tailscale via winget, else prints the manual download URL and exits.
2. rclone via winget, else scoop, else a direct zip to
   `%LOCALAPPDATA%\ccsync\bin` (which is added to the user `PATH` if not
   already there).
3. Syncthing via winget, else a direct zip to the same bin folder.
4. `C:\Creators_Club`.
5. A logon scheduled task (`CCSync-SubstP`) running `subst P:
   C:\Creators_Club`, plus running `subst` once immediately (skipped if
   `P:` is already correctly mapped; warns instead of clobbering if `P:`
   is mapped to something else).
6. Writes a `[creators_club_sftp]` stanza into
   `%APPDATA%\rclone\rclone.conf` (skipped if that section already
   exists). Warns if the referenced SSH private key
   (`%USERPROFILE%\.ssh\ccsync_ed25519`) doesn't exist yet -- generating
   it and sending the `.pub` to the admin is a separate manual step.
7. Registers `ccsync-companion.exe` (path parametrized via
   `-CompanionExePath`) to autostart via the `HKCU\...\Run` registry key --
   guarded: if the exe doesn't exist yet (companion app not built/installed
   yet), this step is skipped with a note, not a hard failure.
8. Generates a Syncthing config under `%LOCALAPPDATA%\ccsync\syncthing-config`
   if one doesn't exist, then prints the device ID and a short list of the
   remaining manual steps (`tailscale up`, generate SSH keypair, Resolve
   Project Server connection, Prefer Proxies).

`-DryRun` prints every action it would take without touching the
filesystem, registry, or Task Scheduler.

## macos_bootstrap.sh

```bash
./macos_bootstrap.sh --tailnet-host truenas.tailnet.ts.net --editor-name jsmith
```

Equivalent steps using `brew` where available, falling back to direct
`curl` downloads of official release tarballs/casks otherwise. Uses
`~/Creators_Club` instead of a drive letter (Resolve's Mapped Mount
preference bridges the two -- manual, one-time, documented in
`../docs/EDITOR_SETUP.md`, since it isn't exposed by the scripting API).
Syncthing and (if present) the companion app are wired to autostart via
`LaunchAgent` plists written to `~/Library/LaunchAgents/` (the script
writes the plist but does not `launchctl load` it automatically -- it
prints the exact command to run).

`--dry-run` prints every action it would take without touching the
filesystem or writing any LaunchAgent.

## Assumptions / things a human should confirm before relying on these

- **winget package IDs** (`Tailscale.Tailscale`, `Rclone.Rclone`,
  `Syncthing.Syncthing`) are believed correct as of writing but were not
  verified against a live winget source from this environment -- if any of
  them 404, the script falls back to the next method (scoop/direct
  download for rclone and Syncthing; a printed manual URL for Tailscale).
- **Syncthing release asset names**
  (`syncthing-windows-amd64.zip`, `syncthing-macos-{amd64,arm64}.tar.gz`)
  match the current GitHub Releases naming convention as of writing;
  confirm against the latest release if this breaks.
- **Companion app packaging** (a single `ccsync-companion.exe` on Windows,
  a `.app` bundle on Mac) is a placeholder assumption -- adjust
  `-CompanionExePath` / `--companion-app-path` (and the LaunchAgent's
  `ProgramArguments` on Mac) once the actual `companion/` build output
  (PyInstaller `build.spec`, per SPEC.md) is known.
- Both scripts assume the editor will run `ssh-keygen` themselves (or the
  admin will send them a keypair) for the rclone SFTP remote -- neither
  script generates one, since a fresh keypair with no matching account yet
  is dead weight; the script just checks for the file and warns if it's
  missing.
