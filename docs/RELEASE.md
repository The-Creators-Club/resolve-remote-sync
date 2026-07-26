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
| Dashboard VERSION | `dashboard/src/ccsync_dashboard/__init__.py` → `VERSION` | Ships separately (Docker). Served by `GET /api/v1/health`. Bump it when you deploy dashboard changes, otherwise the live/repo comparison can never detect a stale container. |

Bumping the companion means editing **two** files (`config.py` and
`pyproject.toml`) to the same value. The build refuses to start otherwise and
lists every mismatch it found.

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
