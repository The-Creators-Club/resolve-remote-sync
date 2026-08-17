# installer/ -- CC Sync: editor bootstrap scripts

CC Sync -- fleet sync for DaVinci Resolve(R). Requires DaVinci Resolve Studio
on every editing machine (the free edition exposes neither collaboration nor
the external scripting interface these scripts configure).

Per-editor bootstrap scripts that get a new remote editor's Windows or Mac
machine ready for the sync system: Tailscale, rclone, Syncthing (installed
**and running**), the local sync root (verified as a real mount when it is
on an external volume), the tree-drive mapping (Windows) or Resolve's
**Mapped Mount** preference (Mac -- set automatically while Resolve is quit;
see `../docs/EDITOR_SETUP.md` step 6 for the manual fallback), rclone remote
config, a seeded companion config, and the companion app itself plus its
autostart entry.

## The site manifest decides, not this code (2026-08-17)

Nothing tenant-shaped is compiled into these scripts any more
(`../docs/COMMERCIAL_READINESS.md` items 10 and 11). Both bootstraps fetch

    GET <dashboard>/api/v1/site

before they do anything, and every site-shaped value below resolves in this
order: **the flag you passed** → **the manifest** → **a neutral fallback, or a
named capability miss where guessing would put terabytes in the wrong place.**

| Manifest key | Used for | Fallback |
|---|---|---|
| `canonical_prefix` | the Windows drive letter the tree is mounted as, and Resolve's Mapped Mount prefix on macOS | `P:\` |
| `tree_name` | `%SystemDrive%\<tree>` / `~/<tree>` when no `-LocalRoot`, and the Explorer drive label | `CCSync` |
| `remote_root` | lanes A/B destination | none — capability miss |
| `rclone_remote` | the `[section]` name in `rclone.conf` | `ccsync_sftp` |
| `sftp_port`, `sftp_shell_type` | the rclone SFTP stanza | `22`, `unix` |
| `nas_syncthing_id` | lane C pairing | none — capability miss |

Everything the Windows bootstrap derives from `canonical_prefix` moves with
it: the `subst`/`net use` commands, the loopback share name (`CCSync_<letter>`),
the logon task (`CCSync-Subst<letter>`), the `HKCU\...\Run` fallback entry,
the Explorer `MountPoints2` label key, and the "is this drive already
somebody else's?" guard. `windows_uninstall.ps1` reads the letter back out of
`~/.ccsync/config.toml` (it has to work on a machine that is off the tailnet)
and takes `-DriveLetter` to override. `installer/tests/Test-DriveMapParser.ps1`
pins both the parser and the absence of any `CCSync_P` / `CCSync-SubstP`
literal in the bootstrap's code.

## Pinned downloads, and how to bump one

rclone and Syncthing used to be fetched as "latest" (`rclone-current-*.zip`;
a GitHub API lookup for Syncthing's version-stamped asset) and installed with
**no integrity check at all**. Since 2026-08-17 both bootstraps pin a version
and a sha256 per asset, verify before unpacking, and delete anything that does
not match rather than install it (`COMMERCIAL_READINESS.md` item 13). This is
the same contract the companion's `sidecar_tools.py` already used for ffmpeg
and deno.

Current pins (bump the two files **together** — `build_editor_package.ps1`
ships both, and a Windows fleet on one rclone and a Mac fleet on another is a
support problem before it is a security one):

| Tool | Version | Where |
|---|---|---|
| rclone | `v1.75.0` | `windows_bootstrap.ps1` `$RcloneVersion` / `macos_bootstrap.sh` `RCLONE_VERSION` |
| Syncthing | `v2.1.3` | `windows_bootstrap.ps1` `$SyncthingVersion` / `macos_bootstrap.sh` `SYNCTHING_VERSION` |

**Bumping a pinned download**

1. Pick the new version. rclone: `https://downloads.rclone.org/version.txt`.
   Syncthing: the latest release tag on GitHub.
2. Take the digests from the PUBLISHER'S OWN checksum list, never from the
   download you just made:
   ```bash
   curl -s https://downloads.rclone.org/<ver>/SHA256SUMS | grep -E 'windows-amd64|osx-(amd64|arm64)'
   curl -sL https://github.com/syncthing/syncthing/releases/download/<ver>/sha256sum.txt.asc      | grep -E '^.*syncthing-(windows-amd64|macos-(amd64|arm64))-<ver>\.zip'
   ```
   Syncthing's list is PGP-signed; verify the signature if you are being
   careful. Fetching a hash from the same host that served the bytes proves
   nothing on its own — that is why the digest is hardcoded, not downloaded.
3. Edit **all six constants**: `$RcloneVersion` + `$RcloneZipSha256` and
   `$SyncthingVersion` + `$SyncthingZipSha256` (Windows, amd64 only);
   `RCLONE_VERSION` + `RCLONE_SHA256_ARM64`/`_AMD64` and `SYNCTHING_VERSION` +
   `SYNCTHING_SHA256_ARM64`/`_AMD64` (macOS).
4. Bump `INSTALLER_VERSION` in `windows_bootstrap.ps1`, `macos_bootstrap.sh`
   AND `onboarding/steps.py` — `release.ps1` refuses on drift between them.
5. Run one bootstrap with `-DryRun` / `--dry-run` and confirm it prints the
   new URL and digest, then one real install on a scratch machine.

The winget / scoop / brew routes are still tried first and are **not** pinned:
those package managers verify their own manifest hashes, and a customer who
already manages rclone that way should keep doing so. The direct download —
the route that had no verification at all — is the pinned one.

**Status:** the Windows script has now been run end-to-end on a real editor
machine (2026-07-24); the bugs that run exposed are fixed
here and listed under "Fixed after the first live run" below. `onboard.exe`
(built from `onboarding/`) wraps it and is the path a new Windows editor
should actually take.

**macOS status: builds and tests clean on a real Mac; the RUNTIME is still
unvalidated (2026-08-04).** The whole path exists -- a macOS companion build
(`tools/release_macos.sh`), an installer that downloads and installs it, sets
Resolve's Mapped Mount and verifies the external SSD, and an uninstaller.

What a real Mac has now done (arm64, macOS 15.7.4, Python 3.12.13), and what
it has not:

| | |
|---|---|
| **Done** | Sections A1–A6 of the checklist: a signed arm64 binary built by `release_macos.sh`; a clean-venv `pip install -e ".[dev,tray]"`; the full companion suite **1563 passed, 18 skipped, 0 failed**, with all 18 skips genuinely Windows-only; all 24 real-rclone lane-direction tests executed; the Resolve mapping helper run in `verify` mode against live preference files |
| **Not done** | Every macOS **runtime** path: `diskutil`, `launchctl`, `xattr`, the Resolve preference *write*, `caffeinate`, the external-SSD root guard, the self-upgrade swap, the menu-bar tray. Sections A7–H are unrun |

That first run (`docs/macos-first-run-2026-08-04.md`) found five defects, four
of them in code or test infrastructure that had never been exercised
anywhere. They are fixed -- see "Fixed by the first Mac run" below -- but a
green suite is not a validated port. Treat the first install as a
**supervised** one and walk
[`MACOS_FIRST_RUN.md`](MACOS_FIRST_RUN.md) -- the ordered first-session
checklist, with the expected output and the failure shape for every step.

### Fixed by the first Mac run (2026-08-04)

- **MAC-1 — a UTF-8 BOM on `companion/pyproject.toml` made the package
  uninstallable.** pip reads pyproject with a binary `tomllib.load`, which
  rejects a BOM, so `pip install -e .` died and there was no way to build a
  macOS companion at all. Introduced by the 0.4.20 version bump itself
  (PowerShell `Set-Content` prepends one); invisible on Windows because every
  Windows consumer of that file parses it with a regex and `release.ps1`
  never installed the package. It also broke `test_version_matches_pyproject`
  on **every** host, so `main` was red everywhere. Guarded now by a test that
  binary-loads every `pyproject.toml` in the repo.
- **MAC-4 — the rclone test gate looked for `rclone.exe`,** so on a Mac the
  24 tests that invoke a real rclone to prove lane A is video-up-only and
  lane B is `**/Proxy/**`-down-only skipped silently and `pytest` still
  exited 0. The fixture is platform-aware and also consults
  `~/.local/ccsync/bin/rclone` (the installer's own path, deliberately off
  `PATH` per INST-7); `CCSYNC_REQUIRE_RCLONE=1`, which both release scripts
  set, makes an absent rclone a failure rather than a skip.
- **MAC-3 — canonical `P:\` paths were parsed with posix semantics.**
  `resolve_bridge._norm_path` and popup's display-name fallback used the
  host's `os.path`; on posix `normcase` is a no-op and `basename` answers the
  *whole* string. That silently disabled the popup's dedupe (its own
  docstring records the blank-Combobox bug that dedupe prevents, and
  `fixer.fix_clip` guards a duplicate `ReplaceClip` behind it) and would have
  rendered full paths where filenames belong. Both now route through
  `canon.plat_for()`, which `canon.py` already used for exactly this.
- **A drive-rooted destination escaped the containment check on posix** --
  `Path(root) / "C:/Windows/Temp"` is an ordinary relative join there, so
  free text from the popup's editable combobox landed inside the tree and was
  approved. Refused explicitly now.
- **D5 — the mapping helper was asymmetric.** `insert_position()` was a
  `ConfigDat`-only override, so `.config.data` appended *after* Resolve's
  trailing `/Volumes` entry while `config.dat` inserted in front, and the docs
  claimed both did the same. Moved to the base class. Also: `.config.data` on
  that Mac is root-owned mode 666, and the atomic save silently transfers
  ownership to the running user -- now warned about before the write.

Two test-infrastructure findings from the same run are worth knowing because
they mean coverage was weaker than the numbers implied: the "no dispatcher
starts on Windows" test **faked nothing at all** (it was green by accident of
being written on a Windows box, and on macOS its assertion still passed for
the wrong reason), and the darwin shutdown-guard test asserted "no AppKit"
while a real Mac has pyobjc installed. Both now inject what they claim.

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

(on the NAS at `<remote_root>/Assets/Software/CC_Sync`)

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
(`-AdminUser`, or `$env:CCSYNC_ADMIN_USER`; there is no compiled-in default
any more — it used to be one operator's username, 2026-08-17,
`COMMERCIAL_READINESS.md` item 10. `-DashboardUrl` comes from `site.toml` /
`$env:CCSYNC_DASHBOARD_URL`). Without `-MakeCurrent` the build is staged until you flip
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
| `-LocalRoot` | *(existing `config.toml`, else `%SystemDrive%\<tree name from the site manifest>`)* | Point at a volume with room for originals + proxies. |
| `-RemoteRoot` | *(the site manifest's `remote_root`)* | Must be absolute -- see below. A capability miss when neither is set. |
| `-DriveLabel` | *(the site manifest's tree name, else `CCSync`)* | Explorer display name for `P:`. |
| `-CompanionExePath` | `%LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe` | Where the companion is expected to live and what gets autostarted. Skipped with a note if absent. |
| `-CompanionExeSource` | *(none)* | Path to the exe in the package; copies it to `-CompanionExePath` if missing/older, then registers autostart. Without it the editor has to place the exe there by hand. |
| `-DashboardUrl` | *(required; or `$env:CCSYNC_DASHBOARD_URL`)* | Written to the seeded `config.toml` as `dashboard_url`, and where the site manifest (`GET /api/v1/site`) is read from. The script refuses to run without it. |
| `-DashboardToken` | *(empty)* | Written as `dashboard_token`. **Required for a reporting (managed) install** -- with it blank the companion never reports and never receives the editor's project ticks, i.e. a silently unmanaged machine. |
| `-DryRun` | off | Prints every action, touches nothing. |

Steps (each idempotent, each prints what it did/skipped):
1. Tailscale via winget, else prints the manual download URL and exits.
2. rclone via winget, else scoop, else a direct zip to
   `%LOCALAPPDATA%\ccsync\bin` (which is added to the user `PATH` if not
   already there).
3. Syncthing via winget, else the **pinned, sha256-verified** zip (see
   "Pinned downloads" above).
4. The local sync root (`-LocalRoot`).
5. Maps the tree drive (the manifest's `canonical_prefix`, `P:` unless the
   site says otherwise) to `<LocalRoot>`. Preferred: creates a private
   loopback SMB share `CCSync_<letter>` of the local root (admin-only -- via
   a one-off UAC prompt, which is why the script itself must not be run
   elevated) and maps
   `net use <drive> \\localhost\CCSync_<letter> /persistent:yes` -- self-restores at
   logon with no scheduled task, and (crucially) net-use drives are the
   only kind Explorer can display-name. The `net use` itself deliberately
   runs UNelevated: a drive mapped by an elevated token is invisible to
   the user's normal session (UAC linked-token isolation). If the share
   can't be created (UAC declined, SMB server off): falls back to the old
   `subst <drive> <LocalRoot>` with a logon scheduled task
   (`CCSync-Subst<letter>`), falling back further to an `HKCU\...\Run`
   entry -- works identically, but the drive shows the host volume's label
   in Explorer.

   **The share is loopback-only, and is now firewalled that way.** It exists
   solely so Explorer will show the tree's name on the drive; nothing outside
   the machine is meant to reach it. The same elevated step therefore installs
   an inbound **block** rule for TCP 139/445 on all profiles
   (`CC Sync: block remote SMB (tree share is loopback-only)`). That does not
   break the mapping: Windows Firewall does not filter loopback traffic, and
   the mapping is `\\localhost\...`. A scoped *allow* rule would have been
   weaker and wrong — block rules win by precedence and the built-in File and
   Printer Sharing allow rules are already on. Pass `-KeepRemoteSmbOpen` only
   on a machine that deliberately serves SMB to its network; the uninstaller
   removes the rule with the share (`COMMERCIAL_READINESS.md` item 15).
6. Labels the tree drive as `-DriveLabel` in Explorer via the per-user
   `MountPoints2\##localhost#CCSync_<letter>\_LabelFromReg` value (what Explorer
   itself writes when you F2-rename a network drive), then restarts
   Explorer so it shows immediately. `subst`-mapped drives cannot be
   labelled at all on current Windows 11 -- `DriveIcons\DefaultLabel`
   (HKCU and HKLM) and `autorun.inf label=` were all verified ignored on
   build 26200. **Not** `label P:` either: that renames the whole
   underlying volume.
7. Generates the Syncthing config, registers `syncthing serve` for autostart,
   and **starts the daemon now**.
8. Writes an rclone stanza (named by the site manifest's `rclone_remote`, else `ccsync_sftp`) into
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
    --tailnet-host nas.tailnet.ts.net --editor-name jsmith \
    --local-root "/Volumes/RigSSD/<tree>"
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
| `--local-root` | your existing `config.toml`'s `local_root`, else `$HOME/<tree_name from the site manifest>` | Normally the editing SSD: `/Volumes/<Name>/<tree>`. See the external-volume rules below. |
| `--remote-root` | *(the site manifest's `remote_root`)* | Must be absolute -- SFTP lands in the editor's NAS home directory. A capability miss when neither is set. |
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

Its LaunchAgent (`com.ccsync.companion` -- renamed from
`com.creatorsclub.ccsync.companion` on 2026-08-17, `COMMERCIAL_READINESS.md`
item 10; both bootstraps and both uninstallers unload and delete the legacy
label first, so a Mac provisioned before the rename never ends up running two
companions) runs the binary
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
plists), and drops only this deployment's rclone stanza from
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
   (the rclone remote name). Fixed at the source, and both installers now seed
   the config file directly. The companion also validates its config at
   startup and logs a specific complaint per missing value.
6. **The local sync root was hardcoded** to a fixed path. Now
   `-LocalRoot` / `--local-root`, flowing through to the `subst` target and
   the companion's `local_root`.
7. **`-EditorName` wasn't normalized.** A case mismatch (`Editor` typed here
   vs the account's real lowercase spelling) produced a working-looking
   `rclone.conf` that failed much later
   with a generic SSH auth error pointing nowhere near the typo. Now
   lowercased, with the change reported.
8. **`remote_root` resolved to the wrong place.** An SFTP session lands in the
   editor's home directory on the NAS, so a relative `remote_root =
   "<tree>"` meant `~/<tree>` -- a path that does not exist --
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
  Resolve preference **write** (the two formats' numbering bases are no
  longer guesswork -- a real Mac's files were read on 2026-08-04 and both are
  1-based, `MacDIO = 1`, with the `/Volumes` auto-entry last in `config.dat`
  and **absent entirely** from `.config.data` -- but nothing has written to
  them yet).
  `MACOS_FIRST_RUN.md` turns each of these into a checkable step.

## Next steps for macOS

In order. Each one is blocked by the one above it.

1. **Commit and cut a Mac build.** `main` at `0f5d99d` cannot `pip install`
   at all, so nothing downstream is possible until the BOM fix lands.
   Then `./tools/release_macos.sh` on the Mac — no `--skip-tests` and no
   `--allow-dirty` this time, so the manifest records `tests_run: true`
   against a clean tree.
2. **A7 — the menu-bar smoke run.** Needs a human watching: does the tray
   icon appear, does a Tk dialog open without deadlocking against pystray's
   AppKit run loop (**B1**, still open and gating any further macOS UI work)?
   This is the first thing that exercises the main-thread UI dispatcher for
   real.
3. **A8 — publish**, then **C1–C7**, the install drill on a machine that has
   not been hand-primed. The current Mac has a half-finished bootstrap on it
   (rclone, syncthing, a seeded `config.toml`, an unloaded Syncthing
   LaunchAgent) — either wipe that first or the drill proves nothing.
   The onboarding gap (option A of `docs/macos-onboarding-handoff.md` §2) is
   now **code-complete**: the wizard runs on macOS (installer 1.0.17 —
   `onboarding/steps.py` darwin branches, `build_onboard_macos.spec`,
   `tools/build_onboard_macos.sh`, and `macos_bootstrap.sh` speaking the
   wizard's CAPABILITY/exit-3/RESOLVE-MAPPING-STATUS contract). Build it on
   the Mac after A8 and prefer it as the vehicle for the C drill — it
   exercises the same bootstrap underneath, plus the two gates the Terminal
   route lacks. Publishing it (`--publish --make-current`) fills the
   `macos`/`onboard` slot with the zipped .app, which is what a Mac's
   `[ INSTALLER ]` click then downloads by default — Windows ships no longer
   push `macos_bootstrap.sh` into that slot (they warn when it goes stale).
   It has **never been built or double-clicked**; treat the first run as
   supervised. **Extra reason to watch that build (2026-08-05):**
   `build_onboard_macos.spec` moved from onefile to **onedir**
   (`EXE(exclude_binaries=True)` → `COLLECT` → `BUNDLE`), because a onefile
   `.app` is deprecated in PyInstaller 6.21 and a hard error in 7.0
   (`KNOWN_BUGS.md` item 9). The change was made on Windows and verified only
   against PyInstaller's own bundle-assembly source; the zip the dashboard
   serves is unchanged in shape, and `sys._MEIPASS` still resolves the
   bootstrap script, the bundled companion and the window icon — but no Mac
   has built it. First Mac build: run `tools/build_onboard_macos.sh` (it now
   also runs `codesign --verify --deep --strict` on the bundle and on the
   unzipped copy), then unzip and double-click before `--publish`.
4. **B2 — what path spelling does Resolve on macOS actually return?**
   Answer it from the live bridge: canonical `P:\…` strings, or Mapped-Mount
   resolved `/Volumes/…` paths? The MAC-3 fix is safe either way (`plat_for`
   picks `ntpath` only for drive-rooted or backslash-bearing strings), so
   this no longer blocks anything — but it decides whether the popup/fixer
   layer is doing real work or a no-op on that host.
5. **D1–D6 — the Resolve mapping write**, then quit/relaunch Resolve and
   confirm the mapping survives. Diff both backups afterwards. Expect the
   ownership warning on `.config.data`; record whether Resolve minds.
6. **E1–E4 — the external-SSD drills**, which are the point of the port and
   are currently inert: `config.toml` has
   `local_root = /Users/<editor>/<tree>`, i.e. the internal disk, so the
   root guard can never fire. **Blocked on a decision**: the only external
   volume present is ExFAT and already holds unrelated material, and ExFAT
   has no POSIX permissions or symlinks. Pick a drive and a filesystem
   before running these.
7. **F1–F5 self-upgrade**, **G1–G3 caffeinate**, **H1–H5 uninstall.**

Only after E–H should `KNOWN_BUGS.md` item 8 or the status block above be
softened further.

---

DaVinci Resolve is a registered trademark of Blackmagic Design Pty Ltd. CC Sync
is not affiliated with, endorsed by, or sponsored by Blackmagic Design.
