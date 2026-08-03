# installer/ -- Creators Club Sync: editor bootstrap scripts

Per-editor bootstrap scripts that get a new remote editor's Windows or Mac
machine ready for the sync system: Tailscale, rclone, Syncthing (installed
**and running**), the local sync root, the `P:` mapping (Windows) or Mapped
Mount prep (Mac -- the actual Resolve preference is a manual step, see
`../docs/EDITOR_SETUP.md`), rclone remote config, a seeded companion config,
and a companion-app autostart entry (best-effort, since the companion app is
built separately in `companion/` and may not exist on disk yet).

**Status:** the Windows script has now been run end-to-end on a real editor
machine (`DESKTOP-LQQ41TC`, 2026-07-24); the bugs that run exposed are fixed
here and listed under "Fixed after the first live run" below. `onboard.exe`
(built from `onboarding/`) wraps it and is the path a new Windows editor
should actually take.

**macOS is not a supported editor platform yet.** `macos_bootstrap.sh` is
syntax-checked with `bash -n` and exercised with `--dry-run` under Git Bash
only -- it has never been run on an actual Mac. More importantly **there is
no macOS companion app**: nothing in this repo builds or ships one, so the
script sets up rclone and Syncthing and stops. A Mac editor ends up with no
tray app, no lane A/B sync, no out-of-tree popup and no dashboard reporting.
The script now says so loudly at the top. Don't hand this package to a Mac
editor without talking to them first.

**Building and shipping a companion release is documented in
[`../docs/RELEASE.md`](../docs/RELEASE.md)** — `tools\release.ps1` (parity
check + tests + PyInstaller + provenance manifest), then
`build_editor_package.ps1 -Publish -MakeCurrent`, then verify with
`tools\check_deploy_drift.ps1`. Read it before concluding that a fix "didn't
work": on 2026-07-25 a rig ran v0.4.3 for an afternoon while every fix was
being verified against v0.4.5.

## The editor package

The folder handed to a new editor lives at one canonical location:

```
P:\Assets\Software\CC_Sync
```

(on the NAS at `/mnt/tank/TheCreatorsPool/Creators_Club/Assets/Software/CC_Sync`)

Rebuild it with `build_editor_package.ps1`, which copies every file from this
repo so the package can't silently drift:

```powershell
.\build_editor_package.ps1 -RebuildExe     # -RebuildExe whenever companion/src changed
```

It reports what it copied, whether the companion exe is older than any
`companion/src` file (the one thing not generated from repo text, so the one
most likely to be stale), and the commit it built from. **Always run it with
`-RebuildExe` after touching the companion**, otherwise editors get new
scripts wrapped around an old binary — which is precisely how the first
package ended up eleven fixes behind without anyone noticing.

To also push the build to the dashboard's **upgrade channel** (each running
companion then offers its editor a one-click "Update now" in the tray):

```powershell
.\build_editor_package.ps1 -RebuildExe -Publish [-MakeCurrent]
```

Publishing needs the version bumped first — in BOTH
`companion/src/ccsync_companion/config.py` (`VERSION`) and
`companion/pyproject.toml` — and prompts for the dashboard admin password
(`-AdminUser`, default `alex`; `-DashboardUrl` defaults to the tailnet
address). Without `-MakeCurrent` the build is staged until you flip
`[ MAKE CURRENT ]` on the dashboard's admin page. Publishing **keeps every
previous build** (nothing is auto-pruned any more, so rollback stays
available); add `?prune=1` to the publish URL if you deliberately want the
old current-plus-2 trimming. Full runbook: `docs/SERVER.md` → "Publishing a
companion update".

`-Publish` also uploads `onboarding/dist/onboard.exe` as the `kind=onboard`
package (version = `$InstallerVersion`), which the dashboard serves to any
signed-in user via the `[ INSTALLER ]` header link (`/download` — picks
Windows or macOS from the browser). That download is the supported way to
hand an editor the installer: onboard.exe refuses to run from the NAS share
anyway, and the dashboard copy can't drift behind the way a hand-copied one
does. The upload is skipped with a warning when onboard.exe is stale or its
version wasn't bumped (`$InstallerVersion` in `windows_bootstrap.ps1` AND
`INSTALLER_VERSION` in `onboarding/steps.py`). The macOS slot has no
automated publisher yet; if you need it, publish `macos_bootstrap.sh` by
hand: `PUT /api/v1/admin/packages/macos/<version>?kind=onboard&sha256=...`.

Contents (11 files, all copied by `build_editor_package.ps1`):

| File | Why it's there |
|---|---|
| `onboard.exe` | **The primary path.** One-click wizard: clean slate, bootstrap, account verification, sign-in. What a new Windows editor runs. |
| `START_HERE.md` | The editor-facing quick start (wizard first, manual steps after). |
| `FIRST_UPGRADE.md` | One-time hand-upgrade instructions for editors on a pre-self-update build. |
| `windows_bootstrap.ps1` | Manual/repair install path (what `onboard.exe` drives internally). |
| `windows_upgrade.ps1` | Manual upgrade: swaps the exe, keeps identity/config. |
| `windows_uninstall.ps1` | Removal; `-Full` also drops sign-in + Syncthing identity. |
| `macos_bootstrap.sh` | rclone + Syncthing only -- see the macOS status note above. |
| `macos_uninstall.sh` | Mac removal; mirrors `windows_uninstall.ps1` semantics and never touches the SSD. |
| `EDITOR_SETUP.md` | The long-form setup reference. Copied **flat**, so its commands must not reference an `installer\` prefix or `../` links. |
| `config.example.toml` | Reference copy of every companion config key. |
| `ccsync-companion.exe` | The tray app itself, for the manual path and repairs. |

Note this path does **not** reach editors automatically. Lane B's filter only
pulls down `Proxy/` contents and the Syncthing folders are scoped to
individual projects under `Projects/`, so nothing under `Assets/` syncs
outward. Point editors at the share, or send them a copy.

`START_HERE.md` lives in this directory and is version-controlled. It used to
exist only inside the built package, which is why it drifted out of step with
the scripts it describes.

## windows_bootstrap.ps1

```powershell
.\windows_bootstrap.ps1 -TailnetHost truenas.tailnet.ts.net -EditorName jsmith
```

PowerShell 5.1 compatible: no `&&`, no ternary/null-coalescing operators,
every branch is a plain `if`/`else`. Requires an execution-policy bypass to
run at all on a default Windows install, e.g.:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows_bootstrap.ps1 -TailnetHost <host> -EditorName <name> -DashboardToken <token>
```

**Run it from a normal, unelevated shell.** Do not tell an editor to "Run as
Administrator": the whole script runs in one process, and a drive mapped by
an elevated token is invisible to the user's normal session (UAC linked-token
isolation), so Resolve sees no `P:` until the next logon. The script raises
UAC by itself, once, for the only step that needs it (creating the loopback
share), and falls back to an `HKCU\...\Run` entry where it can't register a
scheduled task. No step aborts the run.

| Parameter | Default | Notes |
|---|---|---|
| `-TailnetHost` | *(required)* | Tailnet hostname or `100.x.y.z` of the NAS. |
| `-EditorName` | *(required)* | TrueNAS username. Lowercased automatically. |
| `-LocalRoot` | `C:\Creators_Club` | Point at a volume with room for originals + proxies. |
| `-RemoteRoot` | `/mnt/tank/TheCreatorsPool/Creators_Club` | Must be absolute -- see below. |
| `-DriveLabel` | `TheCreatorsClub` | Explorer display name for `P:`. |
| `-CompanionExePath` | `%LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe` | Where the companion is expected to live and what gets autostarted. Skipped with a note if absent. |
| `-CompanionExeSource` | *(none)* | Path to the exe in the package; copies it to `-CompanionExePath` if missing/older, then registers autostart. Without it the editor has to place the exe there by hand. |
| `-DashboardUrl` | `http://100.71.216.3:8480` | Written to the seeded `config.toml` as `dashboard_url`. |
| `-DashboardToken` | *(empty)* | Written as `dashboard_token`. **Required for a reporting (managed) install** -- with it blank the companion never reports and never receives the editor's project ticks, i.e. a silently unmanaged machine. |
| `-DryRun` | off | Prints every action, touches nothing. |

Steps (each idempotent, each prints what it did/skipped):
1. Tailscale via winget, else prints the manual download URL and exits.
2. rclone via winget, else scoop, else a direct zip to
   `%LOCALAPPDATA%\ccsync\bin` (which is added to the user `PATH` if not
   already there).
3. Syncthing via winget, else a direct zip whose URL is **resolved from the
   GitHub releases API** (the asset name is version-stamped, so a fixed URL
   goes stale -- see below).
4. The local sync root (`-LocalRoot`).
5. Maps `P:` to `<LocalRoot>`. Preferred: creates a private loopback SMB
   share `CCSync_P` of the local root (admin-only -- via a one-off UAC
   prompt, which is why the script itself must not be run elevated) and maps
   `net use P: \\localhost\CCSync_P /persistent:yes` -- self-restores at
   logon with no scheduled task, and (crucially) net-use drives are the
   only kind Explorer can display-name. The `net use` itself deliberately
   runs UNelevated: a drive mapped by an elevated token is invisible to
   the user's normal session (UAC linked-token isolation). If the share
   can't be created (UAC declined, SMB server off): falls back to the old
   `subst P: <LocalRoot>` with a logon scheduled task (`CCSync-SubstP`),
   falling back further to an `HKCU\...\Run` entry -- works identically,
   but the drive shows the host volume's label in Explorer.
6. Labels `P:` as `-DriveLabel` in Explorer via the per-user
   `MountPoints2\##localhost#CCSync_P\_LabelFromReg` value (what Explorer
   itself writes when you F2-rename a network drive), then restarts
   Explorer so it shows immediately. `subst`-mapped drives cannot be
   labelled at all on current Windows 11 -- `DriveIcons\DefaultLabel`
   (HKCU and HKLM) and `autorun.inf label=` were all verified ignored on
   build 26200. **Not** `label P:` either: that renames the whole
   underlying volume.
7. Generates the Syncthing config, registers `syncthing serve` for autostart,
   and **starts the daemon now**.
8. Writes a `[creators_club_sftp]` stanza into
   `%APPDATA%\rclone\rclone.conf` (skipped if that section already exists).
   Warns if the referenced SSH private key
   (`%USERPROFILE%\.ssh\ccsync_ed25519`) doesn't exist yet -- generating it
   and sending the `.pub` to the admin is a separate manual step.
9. Seeds `~/.ccsync/config.toml` with the values it already knows
   (`editor_name`, `local_root`, `remote`, `remote_root`, plus
   `dashboard_url` / `dashboard_token` from the matching parameters). If the
   file already exists it is left alone and the expected values are printed
   for comparison.
10. Installs the companion from `-CompanionExeSource` (if given) to
    `-CompanionExePath`, then registers it to autostart via `HKCU\...\Run` --
    guarded: skipped with a note if no exe is there.
11. Prints the Syncthing device ID and the remaining manual steps.

## macos_bootstrap.sh

```bash
./macos_bootstrap.sh --tailnet-host truenas.tailnet.ts.net --editor-name jsmith
```

Equivalent steps using `brew` where available, falling back to direct `curl`
downloads of official release archives otherwise. Accepts `--local-root`
(default `~/Creators_Club`) and `--remote-root`. Uses a path instead of a
drive letter (Resolve's Mapped Mount preference bridges the two -- manual,
one-time, documented in `../docs/EDITOR_SETUP.md`, since it isn't exposed by
the scripting API). Syncthing is wired to autostart via a `LaunchAgent` plist
in `~/Library/LaunchAgents/`, and the script now **loads it** (`launchctl
bootstrap`, falling back to `launchctl load`) rather than just printing the
command. The companion step is dead code today -- there is no macOS companion
build for it to find, so it always warns and skips; see the macOS status note
at the top of this file.

`--dry-run` prints every action it would take without touching the filesystem
or writing any LaunchAgent.

## Fixed after the first live run (2026-07-24)

Everything in this section was found by actually running the Windows script
on a new editor's machine. Recorded here because most of these fail
*silently* -- the script appears to succeed and nothing syncs.

1. **Stale Syncthing download URL.** GitHub's
   `/releases/latest/download/<name>` alias only resolves when that exact
   filename exists in the release; Syncthing's assets are version-stamped
   (`syncthing-windows-amd64-v2.1.2.zip`), so the unversioned URL 404s. Both
   scripts now resolve the real asset via the GitHub releases API, with a
   redirect-sniffing backstop for when the unauthenticated API hits its
   60-requests/hour rate limit. **macOS assets are `.zip`, not `.tar.gz`** --
   the old script downloaded a nonexistent tarball *and* would have tried to
   `tar -xzf` a zip.
2. **`Register-ScheduledTask` took the whole script down.** With
   `$ErrorActionPreference = "Stop"` and no try/catch, the `Access is denied`
   thrown on an unelevated run killed every remaining step -- rclone.conf,
   companion autostart, and the device-ID print never ran. Now wrapped, warns,
   and falls back to an `HKCU\...\Run` entry.
3. **`syncthing --device-id` no longer exists** (removed in v2; exits 80 with
   `unknown flag`). The ID is parsed out of `syncthing generate` instead,
   which is safe to re-run against an existing home, with the old flag kept
   as a v1 fallback. If both fail the script says so and points at the web UI
   rather than printing an empty ID.
4. **The Syncthing daemon was never started or autostarted.** Both scripts
   only ever ran `generate`. Nothing ran `serve`, so after a reboot there was
   no daemon, no REST API on 127.0.0.1:8384, and **lane C did not sync at all
   for any editor**. Windows registers a hidden autostart (via a `.vbs` shim
   so no console window flashes at logon) and starts it immediately; macOS
   loads the LaunchAgent it writes and then confirms the process is running.
5. **The companion's config defaults were wrong.** `remote` defaulted to
   `"nas"`, which matches no rclone remote the installers ever create
   (`creators_club_sftp`). Fixed at the source, and both installers now seed
   the config file directly. The companion also validates its config at
   startup and logs a specific complaint per missing value.
6. **The local sync root was hardcoded** to `C:\Creators_Club`. Now
   `-LocalRoot` / `--local-root`, flowing through to the `subst` target and
   the companion's `local_root`.
7. **`-EditorName` wasn't normalized.** A case mismatch (`Ruskin` vs the real
   `ruskin`) produced a working-looking `rclone.conf` that failed much later
   with a generic SSH auth error pointing nowhere near the typo. Now
   lowercased, with the change reported.
8. **`remote_root` resolved to the wrong place.** An SFTP session lands in the
   editor's home directory on the NAS, so a relative `remote_root =
   "Creators_Club"` meant `~/Creators_Club` -- a path that does not exist --
   rather than the shared tree. It must be absolute; the installers seed it
   that way and the companion refuses to treat a relative value as valid.

## Assumptions / things a human should confirm before relying on these

- **winget package IDs** (`Tailscale.Tailscale`, `Rclone.Rclone`,
  `Syncthing.Syncthing`) are believed correct as of writing but were not
  verified against a live winget source -- if any 404, the script falls back
  to the next method (scoop/direct download for rclone and Syncthing; a
  printed manual URL for Tailscale).
- **Companion app packaging.** Windows is settled: a single
  `ccsync-companion.exe`, installed to `%LOCALAPPDATA%\ccsync\bin` and
  autostarted from there. The Mac side is **not** -- `macos_bootstrap.sh`
  looks for a `.app` bundle that nothing in this repo builds or ships, so
  its companion step always skips. Until a `.app` exists (and is notarized,
  or shipped with documented `xattr -dr com.apple.quarantine` instructions),
  macOS editors have no companion at all.
- Both scripts assume the editor will run `ssh-keygen` themselves (or the
  admin will send them a keypair) for the rclone SFTP remote -- neither
  script generates one, since a fresh keypair with no matching account yet is
  dead weight; the script just checks for the file and warns if it's missing.
- The macOS script's `launchctl bootstrap gui/$(id -u)` path has not been
  exercised on a real Mac.
