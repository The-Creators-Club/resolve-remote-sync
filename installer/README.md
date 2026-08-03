# installer/ -- Creators Club Sync: editor bootstrap scripts

Per-editor bootstrap scripts that get a new remote editor's Windows or Mac
machine ready for the sync system: Tailscale, rclone, Syncthing (installed
**and running**), the local sync root (verified as a real mount when it is
on an external volume), the `P:` mapping (Windows) or Resolve's **Mapped
Mount** preference (Mac -- set automatically while Resolve is quit; see
`../docs/EDITOR_SETUP.md` step 6 for the manual fallback), rclone remote
config, a seeded companion config, and the companion app itself plus its
autostart entry.

**Status:** the Windows script has now been run end-to-end on a real editor
machine (`DESKTOP-LQQ41TC`, 2026-07-24); the bugs that run exposed are fixed
here and listed under "Fixed after the first live run" below. `onboard.exe`
(built from `onboarding/`) wraps it and is the path a new Windows editor
should actually take.

**macOS status: code-complete, pending first real-Mac validation
(2026-08-03).** The whole path now exists -- a macOS companion build
(`tools/release_macos.sh`), an installer that downloads and installs it, sets
Resolve's Mapped Mount and verifies the external SSD, and an uninstaller --
but **not one line of the macOS-only code has run on a Mac**. `bash -n`
clean, `--dry-run` exercised under Git Bash, the Resolve mapping helper
unit-tested from its extracted source (32 tests); `diskutil`, `launchctl`,
`xattr`, pyobjc and the preference edit itself are written from
documentation and research, not from a live run. Treat the first install as a
**supervised** one and walk
[`MACOS_FIRST_RUN.md`](MACOS_FIRST_RUN.md) -- the ordered first-session
checklist, with the expected output and the failure shape for every step.

**Building and shipping a companion release is documented in
[`../docs/RELEASE.md`](../docs/RELEASE.md)** — `tools\release.ps1` (parity
check + tests + PyInstaller + provenance manifest), then
`build_editor_package.ps1 -Publish -MakeCurrent`, then verify with
`tools\check_deploy_drift.ps1`. The macOS companion is a **second** build on
a **second machine** (`./tools/release_macos.sh --publish --make-current` --
PyInstaller does not cross-compile), also in RELEASE.md. Read it before
concluding that a fix "didn't work": on 2026-07-25 a rig ran v0.4.3 for an
afternoon while every fix was being verified against v0.4.5.

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
does. The upload is refused when onboard.exe is stale or its version wasn't
bumped -- and the installer version now lives in **three**
files that must agree (`$InstallerVersion` in `windows_bootstrap.ps1`,
`INSTALLER_VERSION` in `onboarding/steps.py`, `INSTALLER_VERSION` in
`macos_bootstrap.sh`).

The same `-Publish` run uploads `macos_bootstrap.sh` as the **macos**
`kind=onboard` package, so `/download` serves the current script to anyone on
a Mac. It is computed independently of the Windows upload (a stale
`onboard.exe` must not stop the `.sh` from shipping, and vice versa), and it
is refused outright if a byte-scan finds a carriage return in the file -- a
Mac's `bash` fails on the first line of a CRLF script. Either upload being
skipped now **fails** the ship rather than warning.

What `-Publish` **cannot** do is build the macOS *companion*: PyInstaller
does not cross-compile. That is one command on a Mac
(`./tools/release_macos.sh --publish --make-current`), and until it is run
the macos companion channel stays where it was -- `build_editor_package.ps1`,
`tools/ship.ps1` and `tools/check_deploy_drift.ps1` each print an advisory
when they notice the gap. See
[`../docs/RELEASE.md`](../docs/RELEASE.md) → "The macOS release".

Contents (11 files, all copied by `build_editor_package.ps1`):

| File | Why it's there |
|---|---|
| `onboard.exe` | **The primary path.** One-click wizard: clean slate, bootstrap, account verification, sign-in. What a new Windows editor runs. |
| `START_HERE.md` | The editor-facing quick start (wizard first, manual steps after). |
| `FIRST_UPGRADE.md` | One-time hand-upgrade instructions for editors on a pre-self-update build. |
| `windows_bootstrap.ps1` | Manual/repair install path (what `onboard.exe` drives internally). |
| `windows_upgrade.ps1` | Manual upgrade: swaps the exe, keeps identity/config. |
| `windows_uninstall.ps1` | Removal; `-Full` also drops sign-in + Syncthing identity. |
| `macos_bootstrap.sh` | The Mac install/repair path. Also published to the dashboard, which is where Mac editors should get it (`[ INSTALLER ]` → `/download`). |
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
DASHBOARD_TOKEN=<token> ./macos_bootstrap.sh \
    --tailnet-host truenas.tailnet.ts.net --editor-name jsmith \
    --local-root "/Volumes/RigSSD/Creators_Club"
```

The same steps as the Windows script, using `brew` where available and
falling back to direct `curl` downloads of official release archives
otherwise. Every step checks current state before acting and prints what it
did or skipped, so it is safe to re-run -- which is the supported way to fix
a typo'd flag. It does **not** run `tailscale up` or generate SSH keys;
those stay interactive one-time steps.

| Flag | Default | Notes |
|---|---|---|
| `--tailnet-host` | *(required)* | Tailnet hostname or `100.x.y.z` of the NAS. |
| `--editor-name` | *(required)* | TrueNAS username. Lowercased automatically. |
| `--local-root` | `$HOME/Creators_Club` | Normally the editing SSD: `/Volumes/<Name>/Creators_Club`. See the external-volume rules below. |
| `--remote-root` | `/mnt/tank/TheCreatorsPool/Creators_Club` | Must be absolute -- SFTP lands in the editor's NAS home directory. |
| `--companion-file` | *(none)* | Install the companion from a local file instead of downloading it (no `DASHBOARD_TOKEN` needed). The supervised-first-install path. |
| `--companion-version` | `current` | Published version to fetch. |
| `--companion-path` | `$HOME/.local/ccsync/bin/ccsync-companion` | Where the binary lives and what the LaunchAgent runs. |
| `--skip-resolve-mapping` | off | Leave Resolve's Mapped Mount alone. |
| `--resolve-mapping-only` | off | Set the Mapped Mount and do nothing else -- needs no NAS, no account, and not even `--tailnet-host`. This is what the error messages tell editors to re-run. |
| `--dry-run` | off | Prints every action, touches nothing (no filesystem writes, no LaunchAgent). |

Environment: `DASHBOARD_URL` (default the tailnet address) and
`DASHBOARD_TOKEN` (empty), which the admin's onboarding tooling sets.

**The local sync root, when it is on an external volume.** A `--local-root`
under `/Volumes` is verified to be a **real mount**, not merely an existing
directory. Two failure modes are refused rather than adapted to, because
adapting silently syncs terabytes to the wrong place: a *ghost directory*
left at `/Volumes/<Name>` by an unclean eject (every "does the path exist"
check passes, and the sync lands on the internal disk), and a *numbered
remount* at `/Volumes/<Name> 1` caused by that ghost (a name that changes on
every replug). Both abort with the human fix spelled out -- eject,
`sudo rmdir` the leftover, replug. On success the volume's `VolumeUUID`,
mount point and local root are recorded in `~/.ccsync/volume.json` (mode
600), which is the contract the companion's root guard reads to tell "the
SSD is unplugged" apart from "the tree is missing". A non-APFS filesystem is
warned about, not refused.

**The companion.** Downloaded from
`GET <dashboard>/api/v1/companion/package/macos/current` with
`X-CCSync-Token`, verified against the `X-CCSync-SHA256` response header
before it is installed (no header or a mismatch = not installed, loudly),
staged and `chmod +x`'d, then quarantine-stripped with `xattr -d
com.apple.quarantine` -- a quarantined binary launched by launchd fails with
no dialog at all. Skipped as already-installed when the sha matches. If it
cannot be installed, the run ends with an unmissable "THE SYNC APP IS NOT
INSTALLED ON THIS MAC" block **and a non-zero exit**, because everything
else succeeding otherwise reads as a finished install.

Its LaunchAgent (`com.creatorsclub.ccsync.companion`) runs the binary
directly -- no `.app`, no `open -a` -- with `RunAtLoad`, **no `KeepAlive`**
(which would race the self-upgrade's re-exec and leave two companions
fighting over the instance lock) and **`AbandonProcessGroup`** (without it
launchd kills the upgrade child along with the process it replaced). The
plist is rewritten and reloaded whenever it points somewhere else or is
missing either property. Syncthing's agent is written **and loaded** the same
way (`launchctl bootstrap`, falling back to `launchctl load`).

**Resolve's Mapped Mount** (`P:\` → the local root) is set for the editor by
a python3 helper embedded in this script, which edits both of Resolve's
plain-text preference files losslessly, atomically, and after a timestamped
backup of each -- while Resolve is quit. Distinct outcomes are reported
distinctly, and each names the exact command to re-run: Resolve running
(exit 3), Resolve never launched so there are no preference files to patch
(exit 4, nothing created), unrecognised format (exit 5), no `python3`.
The closing summary's step 6 is worded for what actually happened, never for
what was intended, and the manual walkthrough stays in
`../docs/EDITOR_SETUP.md` step 6. Full reasoning: `SPEC.md` flaw 7 and
`../docs/GOTCHAS.md` § 10.

The helper's source lives in exactly one place -- the quoted heredoc between
the `CCSYNC-MAPPING-HELPER` sentinel comments --
and `companion/tests/test_resolve_mapping_helper.py` extracts and imports
*that* range, so the module under test is byte-for-byte the module the
installer runs. The sentinels are load-bearing; don't reword them.

## macos_uninstall.sh

```bash
./macos_uninstall.sh [--full] [--dry-run]
```

The macOS counterpart of `windows_uninstall.ps1`, with the same semantics.
**It never touches synced media** -- the project tree on the SSD is left
exactly as it is in both modes, and the closing summary says so by path.

Default mode stops and removes what this installer put in
`~/.local/ccsync` (companion + Syncthing binaries and the Syncthing
identity), removes both LaunchAgents (booting them out *before* deleting the
plists), and drops only the `[creators_club_sftp]` stanza from
`~/.config/rclone/rclone.conf`. `--full` also removes `~/.ccsync` --
except `~/.ccsync/state`, which holds the prompts this machine has already
answered once and for all; deleting it makes every dismissed prompt come
back after a reinstall, which reads as "the fix didn't work".

Deliberately left alone: Homebrew-installed Tailscale/rclone/Syncthing
(shared with other tools -- `brew uninstall` them yourself), the rclone SSH
key in `~/.ssh` (shared location; `--full` just says where it is), and
**Resolve's Mapped Mount preference** -- it is Resolve's own configuration,
harmless without CCSync, and removing it would mean editing Resolve's
preference files behind the editor's back. One closing line says how to
remove it by hand.

Processes are matched by pattern and then filtered to those whose executable
actually lives under `~/.local/ccsync`, so a Mac running its own Homebrew
Syncthing for personal files keeps it.

## How the macOS pieces are distributed

Unlike Windows, **the macOS companion is never on the `P:` editor share.**
That package carries the Windows exe plus the two `.sh` scripts; the Mac
binary is served only from the dashboard's package channel, which is also
where the bootstrap fetches it from. So:

- the **bootstrap script** reaches a Mac editor via the dashboard's
  `[ INSTALLER ]` link (`/download` picks macOS from the User-Agent and
  serves `ccsync-onboard-<version>.sh`), published by
  `build_editor_package.ps1 -Publish`;
- the **companion binary** reaches them via
  `/api/v1/companion/package/macos/current` -- at install time through the
  bootstrap, and afterwards through the tray's own self-upgrade -- published
  by `tools/release_macos.sh --publish --make-current` **on a Mac**;
- a browser download of the `.sh` **is** quarantined (that is the
  downloader's doing, not the file's). Quarantine blocks *executing* it:
  `xattr -d com.apple.quarantine ccsync-onboard-*.sh`, or just run
  `bash ccsync-onboard-*.sh …`, which is unaffected. The companion binary is
  fetched by `curl`, which sets no quarantine, and the script strips it
  anyway.

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
- **Companion app packaging.** Windows: a single `ccsync-companion.exe` in
  `%LOCALAPPDATA%\ccsync\bin`, autostarted from there. macOS: a **bare
  arm64 Mach-O** named `ccsync-companion` in `~/.local/ccsync/bin` --
  deliberately *not* a `.app` bundle, so the LaunchAgent execs the real
  process instead of going through `open -a` and losing sight of it. It is
  **ad-hoc signed** (PyInstaller does this; `release_macos.sh` fails the
  build if the signature is missing, since an unsigned arm64 binary is
  killed on launch by the kernel) and **not notarized** -- which is fine
  precisely because it is never browser-downloaded: `curl` and the tray's
  self-upgrade set no quarantine, and the installer strips the attribute
  regardless. The Dock icon is suppressed at runtime via
  `NSApplicationActivationPolicyAccessory`, so it presents as a menu-bar
  agent. All of this is **unverified on real hardware** -- see
  `MACOS_FIRST_RUN.md`.
- Both scripts assume the editor will run `ssh-keygen` themselves (or the
  admin will send them a keypair) for the rclone SFTP remote -- neither
  script generates one, since a fresh keypair with no matching account yet is
  dead weight; the script just checks for the file and warns if it's missing.
- **Every macOS-only code path is unexercised on real hardware**:
  `launchctl bootstrap gui/$(id -u)`, `diskutil info -plist` /
  `plutil -extract` output shapes, `xattr`, `pgrep -f "DaVinci Resolve"`,
  `osascript` alerts, the pyobjc app-delegate install, `caffeinate`, and the
  two Resolve preference formats (the helper reads each file's own
  numbering base -- `.config.data`'s `IoFs<F>_<i>` and `config.dat`'s
  `Site.<n>.FS.<i>` alike -- but a real macOS file confirming those bases
  is still outstanding).
  `MACOS_FIRST_RUN.md` turns each of these into a checkable step.
