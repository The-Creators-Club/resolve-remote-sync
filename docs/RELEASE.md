# RELEASE.md — shipping a companion build (and proving it shipped)

The code in this repo is not the code your editors are running. It becomes
that only after a build, a publish, and an install. This document is the
short list of steps between the two, and the two commands that tell you
whether you actually did them.

**Read this first if you are about to debug something.** Check which build
is running *before* you spend an afternoon on a fix.

```powershell
.\tools\check_deploy_drift.ps1
```

**And if something is already broken:** [GOTCHAS.md](GOTCHAS.md) collects the
failures that have actually happened here, symptom first. Several of them
produce an error naming a line that is perfectly correct (a CRLF in a shell
script, a PowerShell exit code inherited from `git`, a staleness warning
caused by `git checkout` rewriting mtimes).

---

## Why this file exists

**2026-07-25.** Three rounds of companion fixes were written, reviewed and
"verified" against the repo, which was at `VERSION = "0.4.5"`. The base rig
had been running the exe built at 15:54 that afternoon, which was **v0.4.3**
— `~/.ccsync/companion.log` says so in plain text:

```
2026-07-25 15:54:31,576 INFO  ccsync.app: ccsync-companion v0.4.3 starting
```

Every behaviour observed that afternoon — every "the fix didn't work", every
follow-up fix written to explain it — was an observation of v0.4.3. Nothing
was wrong with the code. It was simply never installed.

The same failure mode has a dashboard variant: the Docker container keeps
serving the image it was last built from, so an API fix "doesn't work"
because the container predates it.

The countermeasures are:

- **one build command** that refuses to run on inconsistent version stamps
  and records what it produced (`tools/release.ps1`),
- **a provenance manifest** (`ccsync-release.json`) that travels with the exe
  from `companion/dist` → editor package → `%LOCALAPPDATA%\ccsync\bin`, so a
  machine can always say *which* build it has,
- **one doctor command** that compares repo / built / installed / published /
  live-dashboard versions in one screen (`tools/check_deploy_drift.ps1`).

---

## Where versions live

| What | File | Notes |
|---|---|---|
| **Companion VERSION** | `companion/src/ccsync_companion/config.py` → `VERSION` | **Single source of truth.** Reported to the dashboard, shown in the tray, and what the upgrade channel compares against. |
| Companion version (dup) | `companion/pyproject.toml` → `version` | Must equal the above. `tools/release.ps1` and `build_editor_package.ps1 -Publish` both refuse on drift. |
| Installer version | `installer/windows_bootstrap.ps1` → `$InstallerVersion` | Separate number; the bootstrap script's own version. |
| Installer version (dup) | `onboarding/steps.py` → `INSTALLER_VERSION` | Must equal the above (`onboard.exe` bundles the bootstrap script). Parity is enforced by `tools/release.ps1`. |
| Installer version (dup) | `installer/macos_bootstrap.sh` → `INSTALLER_VERSION` | Third copy of the **same** number — the macOS bootstrap ships as the `macos` `kind=onboard` package and is versioned by it. Parity is now **three-way**: enforced by `tools/release.ps1` and `build_editor_package.ps1 -Publish` (which refuses to publish either onboard package on drift), reported by `tools/check_deploy_drift.ps1`, and warned about by `tools/release_macos.sh` (which publishes none of the three, so it reports rather than fails). |
| macOS companion build | `tools/release_macos.sh` | Carries **no** version of its own: it reads `config.py`/`pyproject.toml` for the companion version and all three installer constants for the parity report. Runs only on a Mac (`--dry-run` degrades to inspection mode elsewhere). |
| Dashboard VERSION | `dashboard/src/ccsync_dashboard/__init__.py` → `VERSION` | Ships separately (Docker). Served by `GET /api/v1/health`. Bump it when you deploy dashboard changes, otherwise the live/repo comparison can never detect a stale container. |

Bumping the companion means editing **two** files (`config.py` and
`pyproject.toml`) to the same value. Bumping the *installer* means editing
**three** (`windows_bootstrap.ps1`, `onboarding/steps.py`,
`macos_bootstrap.sh`). The build refuses to start otherwise and lists every
mismatch it found.

Version numbers must look like `1.2.3` — the dashboard rejects anything else
(`_PACKAGE_VERSION_RE`), so no `0.4.5-dev` or `0.4.5rc1` in `config.py`.

---

## The release run

### 1. Bump

Edit `VERSION` in `companion/src/ccsync_companion/config.py` **and** `version`
in `companion/pyproject.toml`. Publishing a version the dashboard already has
is a **409** — a rebuild without a bump cannot reach the fleet.

### 2. Build

```powershell
.\tools\release.ps1
```

Which does, and stops at the first failure:

1. **Version parity** — the table above; lists every mismatch and exits 1.
2. **Both test suites** — `companion/.venv` and `dashboard/.venv` pythons,
   `python -m pytest -q` in each. `-SkipTests` skips them and stamps
   `tests_run: false` into the manifest.
3. **PyInstaller** — `python -m PyInstaller build.spec --noconfirm` in
   `companion/`, exactly as `build_editor_package.ps1 -RebuildExe` runs it.
4. **Manifest** — `companion/dist/ccsync-release.json`: version, sha256,
   size, build time, `git describe`, dirty flag, who built it.
5. **Prints the next two steps.** It deliberately does not publish or install
   — those touch the fleet and the running companion.

A **dirty working tree does not block the build** (that would make the normal
case impossible), but it is called out loudly and the manifest version is
stamped `0.4.5+dirty`. Do not publish a `+dirty` build to the fleet: nobody
will be able to reproduce what your editors are running. `-AllowDirty` only
shortens the warning; `-DryRun` prints every step and changes nothing.

`tools/release.ps1` never runs a git write command — it only reads
`rev-parse` / `describe` / `status --porcelain` for provenance.

### 3. Publish to the dashboard upgrade channel

```powershell
.\installer\build_editor_package.ps1 -Publish -MakeCurrent
```

This assembles the editor package at
`P:\Assets\Software\CC_Sync` (including the new
`ccsync-release.json`) and uploads the exe:

```
POST /api/v1/login                                     (session cookie)
PUT  /api/v1/admin/packages/windows/<version>?sha256=<64 hex>&make_current=1
     body = raw exe bytes
```

- The version comes from `config.py`; the upload refuses on version drift, on
  an exe older than `companion/src`, and on a **409** (already published).
- The server verifies the sha256 before the build becomes visible.
- Without `-MakeCurrent` the build is *staged* — published but not offered.
  Flip `[ MAKE CURRENT ]` on the dashboard admin page when you are ready.
- Old builds are retained; `?prune=1` is opt-in. Rollback = make an older
  version current again, which the fleet takes like any other update
  (`_upgrade_info` compares *different*, not *newer*).

### 4. Upgrade the fleet (tray self-upgrade)

Nothing is pushed. Each companion reports its `companion_version` on every
`/api/v1/report`; when a current package exists for its platform and the
version differs, the response carries an `upgrade` block (version, URL,
sha256, size). The companion then:

- pops a tray notification, and grows a menu entry whose wording depends on
  how the offered version ranks against the running one — the channel
  advertises "different", not "newer", so a rollback is a normal thing to
  see here:
  **“Update available → vX.Y.Z (install)”** when it is newer,
  **“Roll back to vX.Y.Z (older — install)”** when it is older, and
  **“Switch to vX.Y.Z (install)”** when the two can't be ranked;
- on click, confirms in a dialog, downloads (same-origin URL only, sha256
  verified, size-capped, free-space checked), renames the running exe to
  `.old`, moves the new one into place, and respawns;
- on the next start it notices the version marker changed and toasts
  *“Update complete — now running vX.Y.Z”*.

So "the fleet is upgraded" means **each editor clicked the tray item**. Watch
who has not on the dashboard's editors/fleet view (per-machine companion
version), or with `check_deploy_drift.ps1 -AdminUser <you>`, which lists
`outdated_machines` straight from `GET /api/v1/admin/packages`.

A machine too old to self-upgrade (pre-0.4.0) needs the manual path:
`installer/FIRST_UPGRADE.md` → `windows_upgrade.ps1` from the package folder.

### 5. Upgrade THIS machine

The base rig is not part of the tray upgrade flow if you are testing a build
you have not published. Install it directly:

```powershell
.\installer\windows_upgrade.ps1 -CompanionExe "E:\Projects\resolve-remote-sync\companion\dist\ccsync-companion.exe"
```

It stops `ccsync-companion.exe` (and any source-mode `pythonw launcher.py`),
copies the exe into `%LOCALAPPDATA%\ccsync\bin`, copies `ccsync-release.json`
next to it, re-registers the `HKCU\...\CurrentVersion\Run` value
`CCSyncCompanion`, migrates missing config keys (never overwrites), and
relaunches. It now prints **which version** it installed — previously it
reported only a path and a timestamp, which is precisely how the 0.4.3
situation stayed invisible.

By hand, if you must: stop the process, copy the exe over
`%LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe`, start it again. Copying
without stopping fails — the running image is locked.

### 6. Deploy the dashboard (only if `dashboard/` changed)

Bump `dashboard/src/ccsync_dashboard/__init__.py`'s `VERSION`, then rebuild
the container (`dashboard/deploy/compose.yaml`,
`docker compose up -d --build`). `GET /api/v1/health` must report the new
version — that is the only externally visible proof the container is current.

### 7. Verify — do not skip

```powershell
.\tools\check_deploy_drift.ps1
```

It must report the installed companion as the repo version. If it does not,
whatever you are about to test is not what you just built.

---

## The macOS release (a second machine, a second command)

**PyInstaller does not cross-compile.** Nothing on the Windows base rig can
produce the Mac binary, so the release above is a *Windows* release that
happens to also publish the macOS *bootstrap script*. The macOS **companion**
channel does not move until someone runs one command on a Mac:

```bash
git pull && ./tools/release_macos.sh --publish --make-current
```

That is the whole macOS ship. It refuses to start on anything but macOS
(`--dry-run` degrades to inspection mode on the base rig, for the parity and
provenance half only), and does, stopping at the first failure:

1. **Platform** — `uname -s` must say `Darwin`; prints the arch and OS
   version.
2. **Version parity + provenance** — `config.py` vs `pyproject.toml` (fatal
   on drift), the three installer constants (reported, not fatal — this
   script publishes none of those files), `^\d+\.\d+\.\d+$`, and
   `git rev-parse/describe/status`. A dirty tree does not block the build but
   stamps the manifest `<version>+dirty`.
3. **venv + tests** — `python3 -m venv companion/.venv`,
   `pip install -e '.[dev,tray]' pyinstaller` (the `tray` extra is what
   carries pystray/Pillow/pyobjc; without it the build silently has no
   menu-bar icon), then the full companion suite. `--skip-tests` records
   `tests_run: false` in the manifest.
4. **Build + signature** — `PyInstaller build.spec --noconfirm`, then
   `codesign -dv`. PyInstaller ad-hoc signs macOS binaries; an **unsigned**
   arm64 binary is killed on launch by the kernel, so a missing signature is
   a hard failure here rather than a mystery on the editor's Mac. `file` is
   then read for the real arch and anything but `arm64` is warned about.
5. **Manifest** — `companion/dist/ccsync-release.json`, same field names and
   order as the Windows one plus `platform: "macos"` and a **measured**
   `arch`. Warns if any `companion/src/**.py` is newer than the binary.
6. **Publish** — a pre-flight ranged GET (one byte) using the
   `dashboard_token` already in `~/.ccsync/config.toml`, so "already
   published" is discovered before the password prompt rather than as a 409
   after the build; then `POST /api/v1/login` (password read from the
   terminal, never argv) and
   `PUT /api/v1/admin/packages/macos/<version>?kind=companion&sha256=…&make_current=1`
   with the raw binary as the body.

The artifact is a **bare `ccsync-companion` Mach-O**, not a zip and not a
`.app`. It never goes on the `P:\Assets\Software\CC_Sync` share — that
package carries the Windows exe and the two `.sh` scripts. The dashboard's
package channel is the *only* place a macOS companion is ever served from,
including for a fresh install: `macos_bootstrap.sh` fetches
`GET /api/v1/companion/package/macos/current` and verifies the bytes against
the `X-CCSync-SHA256` response header.

### What the lag looks like, and why it is expected

A Windows ship (`build_editor_package.ps1 -Publish -MakeCurrent`) publishes
the Windows companion, `onboard.exe`, **and** `macos_bootstrap.sh` as the
`macos` `kind=onboard` package. It cannot publish the macOS companion. So
between the Windows ship and the next Mac build session:

- the dashboard's `[ PUBLISHED PACKAGES ]` box shows the current `macos`
  `companion` at an older version than the current `windows` one;
- Mac editors keep running the build they have and are **not** offered an
  update — "out of date" is always computed against the current package for
  *that machine's own platform*, so a Mac shows `[ OUT OF DATE ]` only once
  the macOS channel itself moves ahead of it;
- `build_editor_package.ps1`, `tools/ship.ps1` and
  `tools/check_deploy_drift.ps1` all print an advisory saying so (a 1-byte
  ranged GET against the download route — which is GET-only; HEAD is a 405).

**That advisory is not a failure.** It is the honest statement that half the
fleet has not been built yet. It never blocks the Windows flow. Clear it by
running the one command above on the Mac.

**First publish:** until `release_macos.sh --publish` has ever run, there is
no `macos` companion package at all, the advisory reads "Mac editors have
nothing to install", and `macos_bootstrap.sh` fails its companion download
with "no published macOS package" — which the script reports as the
unmissable THE SYNC APP IS NOT INSTALLED block and a non-zero exit. Publish
first, install second. (`--companion-file <path>` installs from a local copy
instead, which is the supervised-first-install path in
`installer/MACOS_FIRST_RUN.md`.)

Mac editors are still never pushed to: each companion learns about the new
version on its next report and its editor has to click **Update now** in the
menu bar, exactly as on Windows.

---

## The doctor: `tools/check_deploy_drift.ps1`

Read-only: no files, no registry, no processes, no git writes; GETs only
(plus a login POST with `-AdminUser`). It prints:

- **REPO** — companion `VERSION`, `pyproject.toml`, both installer constants,
  dashboard `VERSION`, `git describe`, and parity verdicts.
- **BUILT** — `companion/dist/ccsync-companion.exe`: mtime, size, sha256, the
  manifest's version/commit, whether the manifest actually describes that
  file, and whether any `companion/src/**.py` is newer than the exe.
- **INSTALLED** — `%LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe`: mtime,
  size, sha256, and its version. **The exe has no `--version` flag** (it is a
  windowed PyInstaller build; `launcher.py` calls `app.run()` with no argv
  handling, and running an unknown build to ask it would start a second
  companion). The version is therefore established in this order:
  1. `ccsync-release.json` next to the installed exe, sha256-matched;
  2. `~/.ccsync/state/last_version.txt` (`upgrade.note_version_start`,
     companion ≥ 0.4.5);
  3. the last `ccsync-companion vX.Y.Z starting` line in
     `~/.ccsync/companion.log` — what the running process said about itself;
  4. sha256 equality with the built artifact.
- **RUNNING** — is the process alive, is it the exe we inspected, is the exe
  on disk newer than the running process (installed but never restarted), and
  does the Run key point at it.
- **DASHBOARD** — `GET /api/v1/health` → `version` (unauthenticated; still
  works if that response is ever trimmed to `ok` + `version`), compared with
  the repo's dashboard `VERSION`. With `-AdminUser`, also the current and
  published Windows packages and every machine behind them.
- **VERDICT** — installed vs repo, in one line.

Example of it doing its job (base rig, 2026-07-25, before this build landed):

```
-- INSTALLED (this machine)
  version    0.4.3   [last start line in companion.log (2026-07-25 15:54:31)]
-- VERDICT
  DRIFT installed companion is v0.4.3, repo is v0.4.5
        => anything you 'verified' against this repo has NOT been tested on this machine.
```

---

## The provenance manifest

`tools/release.ps1` writes `companion/dist/ccsync-release.json`:

```json
{
  "version": "0.4.5",
  "version_stamp": "0.4.5+dirty",
  "platform": "windows",
  "artifact": "ccsync-companion.exe",
  "sha256": "d000eb…",
  "size_bytes": 21141562,
  "built_at": "2026-07-25T14:06:34Z",
  "artifact_mtime": "2026-07-25T08:42:50Z",
  "git_commit": "b989422",
  "git_describe": "b989422-dirty",
  "git_dirty": true,
  "tests_run": true,
  "built_by": "alex@CREATOR_1",
  "built_with": "tools/release.ps1"
}
```

It travels: `companion/dist/` → `build_editor_package.ps1` copies it into the
CC_Sync package → `windows_bootstrap.ps1` / `windows_upgrade.ps1` copy it into
`%LOCALAPPDATA%\ccsync\bin` beside the exe it describes.

Every consumer **sha256-matches it against the exe first** and ignores it on
mismatch. A manifest describing a build that is not the one installed would
make the drift check lie, which is worse than having no manifest at all. For
the same reason `windows_upgrade.ps1` deletes a stale manifest when the new
package does not carry one.

The tray self-upgrade path does not write a manifest (it downloads a bare exe
from the dashboard); there the version comes from
`~/.ccsync/state/last_version.txt` and the log line, which is why the doctor
has four fallbacks rather than one.

---

## Quick reference

```powershell
.\tools\check_deploy_drift.ps1                  # what is actually running, anywhere
.\tools\release.ps1                             # parity + tests + build + manifest
.\tools\release.ps1 -DryRun                     # show the pipeline, change nothing
.\tools\release.ps1 -SkipTests -AllowDirty      # fast local iteration build
.\installer\build_editor_package.ps1 -Publish -MakeCurrent   # ship to the fleet
.\installer\windows_upgrade.ps1 -CompanionExe <path-to-exe>  # install here
.\tools\check_deploy_drift.ps1 -AdminUser alex  # + published version, machines behind
```

These are PowerShell 5.1 scripts. Execution policy on a fresh shell:
`Set-ExecutionPolicy -Scope Process Bypass`.

On the Mac (bash, and only there):

```bash
./tools/release_macos.sh                        # parity + tests + build + sign + manifest
./tools/release_macos.sh --dry-run              # show the pipeline, change nothing
./tools/release_macos.sh --publish --make-current   # ship to the Mac editors
```
