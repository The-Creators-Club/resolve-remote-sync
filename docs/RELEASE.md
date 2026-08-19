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
| Installer version (dup) | `onboarding/build_onboard_macos.spec` → `CFBundleShortVersionString` | **Fourth** copy of the same number — the macOS wizard bundle's Info.plist. Not enforced by the release scripts (they predate it); `onboarding/tests/test_macos_steps.py::TestInstallerVersionParity::test_all_four_agree` is what catches it, which is why "bump the installer" means **four** files, not three. |
| Installer version (dup) | `installer/macos_bootstrap.sh` → `INSTALLER_VERSION` | Third copy of the **same** number — the macOS bootstrap ships as the `macos` `kind=onboard` package and is versioned by it. Parity is now **three-way**: enforced by `tools/release.ps1` and `build_editor_package.ps1 -Publish` (which refuses to publish either onboard package on drift), reported by `tools/check_deploy_drift.ps1`, and warned about by `tools/release_macos.sh` (which publishes none of the three, so it reports rather than fails). |
| macOS companion build | `tools/release_macos.sh` | Carries **no** version of its own: it reads `config.py`/`pyproject.toml` for the companion version and all three installer constants for the parity report. Runs only on a Mac (`--dry-run` degrades to inspection mode elsewhere). |
| Dashboard VERSION | `dashboard/src/ccsync_dashboard/__init__.py` → `VERSION` | Ships separately (Docker, and since 2026-08-18 over the feed as a code bundle). Served by `GET /api/v1/health`, and stamped into the bundle by `tools/build_dashboard_bundle.py`. Bump it when you deploy dashboard changes, otherwise the live/repo comparison can never detect a stale container. |
| Dashboard version (dup) | `dashboard/pyproject.toml` → `version` | Must equal the above. Neither `release.ps1` nor `check_deploy_drift.ps1` reads it (both read `__init__.py`), which is how it once drifted three releases behind unnoticed; `dashboard/tests/test_hardening.py::test_dashboard_version_does_not_drift` is the guard. |

Bumping the companion means editing **two** files (`config.py` and
`pyproject.toml`) to the same value. Bumping the *installer* means editing
**four** (`windows_bootstrap.ps1`, `onboarding/steps.py`, `macos_bootstrap.sh`,
and `onboarding/build_onboard_macos.spec`'s `CFBundleShortVersionString`). The
build refuses to start on the first three and lists every mismatch it found;
the fourth is caught only by `onboarding`'s suite, so run that too — or let
`tools\ship.cmd` do it (2026-08-10: a 1.0.19 → 1.0.20 bump missed the .spec
and only the test noticed).

Version numbers must look like `1.2.3` — the dashboard rejects anything else
(`_PACKAGE_VERSION_RE`), so no `0.4.5-dev` or `0.4.5rc1` in `config.py`.

---

## The release run

**Steps 1–7 below are what `.\tools\ship.cmd` runs for you** — it is the command
to reach for, and it stops before touching anything on a dirty tree, an
already-published version, or a failing `server/` suite. Read the steps to
understand what it did, or to redo one of them by hand; do not assemble a
release out of them.

### What a whole release is, as of 2026-08-18

`ship.cmd` is still the one command, but it only serves **this** deployment's
dashboard. A release that reaches feed customers as well is four commands, in
this order, and the last two are skipped only when nothing they carry changed:

```powershell
.\tools\ship.cmd                                     # 1. this fleet: gates, build, deploy, publish, upgrade
dashboard\.venv\Scripts\python.exe tools\publish_feed.py `
    --manifest companion\dist\ccsync-release.json `
    --feed-dir .\feed --github-repo <owner/repo> --github-upload   # 2. the companion, to every feed customer
dashboard\.venv\Scripts\python.exe tools\build_dashboard_bundle.py --out .\dist
dashboard\.venv\Scripts\python.exe tools\publish_feed.py `
    --artifact .\dist\ccsync-dashboard-<v>.tar.gz --kind dashboard --platform linux `
    --version <v> --feed-dir .\feed --github-repo <owner/repo> --github-upload   # 3. their dashboard's own code
dashboard\.venv\Scripts\python.exe tools\publish_feed.py `
    --asset music\web\data\audio_encoder\music-clap-audio-1.onnx `
    --asset music\web\data\audio_encoder\music-clap-audio-1.params.json `
    --asset-kind music-clap-audio --asset-version 1 `
    --feed-dir .\feed --github-repo <owner/repo> --github-upload   # 4. the CLAP audio tower
```

Three things to know before you start:

- **The CLAP artefacts are not in git.** `music/web/data/audio_encoder/` is
  ignored, and the two files are produced on the base rig by
  `music/indexer/export_audio_encoder.py`. Step 4 is needed only when
  `music_models.MODELS["clap-audio"]["version"]` changed, but a feed with no
  copy of the version the shipped companion pins means **no editor can ingest
  music at all**, so check the digest matches the build you are shipping
  (`docs/RELEASE_FEED.md` §6) rather than assuming the last upload still fits.
- **Never put a lock change and a code fix in the same dashboard release.**
  The bundle carries code; the image carries the dependency closure. Any edit
  to `dashboard/deploy/requirements.lock` or the Dockerfile's `ARG BASE_IMAGE`
  changes the `runtime_id`, which turns that release into a **runtime update**:
  every customer is shown a click for their NAS UI and offered no over-the-air
  button, so the code fix travelling with it reaches nobody until they do it.
  Split them into two releases (step 6 says the same thing at more length).
- **The first OTA update at any image site needs an image rebuilt from the
  current Dockerfile** (KNOWN_BUGS WPK-1/WPK-2). The two-tier rule keys off
  `/venv/.runtime-id`, which only the updated Dockerfile writes, and every
  image built before 2026-08-18 is additionally missing `templates/` and
  `static/`: it answers `/api/v1/health` and 500s every page. Until that
  rebuild the site is bind-mount mode, every apply is refused with "this
  deployment updates from the base rig", and that refusal is correct. Every
  live site today is bind-mount mode, so this is an order-of-operations note
  for the first image site, not a defect.

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

#### The vendored-file pairs the build refuses to ship past

Step 1 also **byte-compares every vendored copy against its source of truth**
and exits 1 on drift, because the exe about to be built bakes in whatever is
in `companion/src`. The pairs are declared in one place — `$VendorPairs` in
`tools/release.ps1` — and `server/tests/test_cross_component.py` pins the same
comparison in the suites (and asserts the two lists agree):

| Source of truth (edit THIS one) | Vendored into the companion |
|---|---|
| `ytdl/web/ytdlweb/ytdl_common.py` | `ccsync_companion/ytdl_common.py` |
| `broll/indexer/broll_index/local_models.py` | `ccsync_companion/broll_vlm/local_models.py` |
| `broll/indexer/broll_index/local_runtime.py` | `ccsync_companion/broll_vlm/local_runtime.py` |
| `broll/indexer/broll_index/local_vlm.py` | `ccsync_companion/broll_vlm/local_vlm.py` |
| `broll/indexer/broll_index/compact_format.py` | `ccsync_companion/broll_vlm/compact_format.py` |
| `broll/indexer/broll_index/contract.py` | `ccsync_companion/broll_vlm/contract.py` |
| `broll/indexer/broll_index/prompts/index_clip_v7_compact.md` | `ccsync_companion/broll_vlm/prompts/index_clip_v7_compact.md` |

Fixing a drift is always the same move: **edit the source, then re-copy the
whole file into the companion below its
`# --- vendored content below, byte-identical ---` line**, leaving the header
above it alone. The prompt is the one exception — it carries no header, because
its bytes are what the model is sent, so it is copied whole and compared whole.

Why copies at all: the frozen exe has neither `ytdlweb` nor `broll_index` in
it and never will (`broll_index` alone would bring anthropic, xxhash, pyyaml,
requests and jieba — ~50 MB and a licence surface onto every editor machine),
and the container has no `ccsync_companion`. `docs/YTDL_LOCAL_DOWNLOAD.md` §5
and `docs/BROLL_INGEST_PLAN.md` §3.3 are the two designs that chose this.
A drifted copy never throws: it downloads the same YouTube clip under a second
filename, or describes clips with a different prompt into the one search
database, and is found months later if at all.

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
     &signature=<base64>&pubkey_id=<id>&min_version=<x.y.z>
     &published_at=<iso>&signed_binary=0|1
     body = raw exe bytes
```

- The version comes from `config.py`; the upload refuses on version drift, on
  an exe older than `companion/src`, and on a **409** (already published).
- The server verifies the sha256 before the build becomes visible.
- The `&signature=...` half comes from `tools/sign_release.py`, which
  `build_editor_package.ps1` runs for you with the offline release key.
  **An unsigned publish is refused (422), not warned about** — see
  *The release signing key* below.
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

**…unless you push it (2026-08-18).** "Each editor clicked the tray item" is
how a fleet-wide fix ends up landing whenever each owner happens to notice a
balloon — ruskin's PC sat two versions behind for a day with its lanes parked.
Two ways round it, both in `docs/MULTI_MACHINE_PLAN.md` §9:

- **One machine, deliberately.** Settings → Packages lists out-of-date
  machines; each row has **[ UPDATE NOW ]** (`POST /api/v1/admin/machines/
  {editor}/{machine}/update`). It records a version, which rides
  `commands.upgrade` on that machine's **next report** — the same channel as
  the fleet halt, so it arrives within one report interval with no push
  infrastructure and no inbound connection to an editor's PC. The request
  clears itself when the machine reports that version.
- **Every machine, standing.** `site.toml [features] auto_update = true`
  (off in the vendor build, published in `GET /api/v1/site`). A companion
  then applies any offer that is **newer** than what it runs, unattended.

Neither can install anything the tray click could not: the command names a
VERSION and the bytes come from the signed offer the companion already holds
(release-key verified, floor-checked), and `apply_upgrade`'s stand-down test
still refuses while a CCSync window is open or media is being copied in.
Auto-update never takes an OLDER build — a rollback stays a deliberate push,
because a rollback taken silently is a one-click loss of everything the
running build fixed (seen live 2026-07-25).

A refused push is **retried, not parked** (CR-41, companion 0.9.41): when the
stand-down test says no, the companion tries again on a later report (90 s
after a window/consolidate refusal, 10 min after a failed download) and tells
the editor once per request, not once per try. Cancelling and pushing again
on the dashboard is a new request and gets a fresh attempt at once. Before
0.9.41 the first refusal silently ended the push until the tray restarted.
Both paths need a companion that reads the flag/command: `auto_update` was
stripped by the companion's manifest whitelist before 0.9.41 (CR-40), so a
fleet on 0.9.3 or 0.9.4 ignores it however the site is configured.

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

Since 1.0.31 it also has a **step 6**: if this machine has no current licence
acceptance (`~/.ccsync/eula_accepted.json`, compared against the
`<!-- EULA-VERSION -->` marker in the `EULA.md` the package now ships), it
launches `onboard.exe` from the package folder — because a companion without
one comes up and refuses to sync, and says so only as "this machine isn't set
up yet" (KNOWN_BUGS CR-22). `-SkipWizard` suppresses it for an unattended
re-run; the summary then says the machine is not syncing. **It never fires on
`mode = "base"`** — `ship.cmd` runs this script on the base rig at the end of
every release, and the rig's `config.toml` is hand-built. Accept there from
the tray instead ("► Accept the licence agreement to start syncing…"), which
is also how every self-upgrading editor accepts: the tray dialog shows the
same bundled document and starts the lanes on ACCEPT, with no restart.

By hand, if you must: stop the process, copy the exe over
`%LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe`, start it again. Copying
without stopping fails — the running image is locked.

### 6. Deploy the dashboard (only if `dashboard/` changed)

Bump `dashboard/src/ccsync_dashboard/__init__.py`'s `VERSION`, then rebuild
the container (`dashboard/deploy/compose.yaml`,
`docker compose up -d --build`). `GET /api/v1/health` must report the new
version — that is the only externally visible proof the container is current.

**For feed customers, that is not how the dashboard is updated** (2026-08-18,
`ZERO_TOUCH_PLAN.md` WP K). Their dashboards pull their own **code** from the
signed feed, so a dashboard release is two more commands on this rig:

```powershell
dashboard\.venv\Scripts\python.exe tools\build_dashboard_bundle.py --out .\dist
dashboard\.venv\Scripts\python.exe tools\publish_feed.py `
    --artifact .\dist\ccsync-dashboard-<version>.tar.gz `
    --kind dashboard --platform linux --version <version> `
    --feed-dir .\feed --github-repo ccsync/ccsync-releases --github-upload
```

`build_dashboard_bundle.py` refuses a dirty tree (`--allow-dirty` for a
deliberate hotfix), stamps the bundle with the dashboard's own `VERSION` — the
one `/api/v1/health` reports — and prints the `runtime_id` that
`publish_feed.py` then reads straight out of the bundle. Each customer's
Packages page grows a `[ UPDATE NOW ]` button; ~10 s later they are on it.

**When a customer has to click in their NAS UI instead.** The bundle carries
only code; the image carries Python and the dependency closure. So **any**
change to `dashboard/deploy/requirements.lock` or to the Dockerfile's
`ARG BASE_IMAGE` line changes the `runtime_id`, and that release is a
**runtime update**: every dashboard shows it with the exact click for their
platform and offers no button, until they update the image. Plan releases
accordingly — a new dependency and a code fix in the same release means
nobody gets the code fix over the air. Split them.

`.github/workflows/release-dashboard.yml` builds the same bundle on a hosted
runner (`workflow_dispatch`, artifact only, never publishes) for the case
where the bundle must come from clean hardware; the signing and the upload
still happen here, next to the offline key.

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
   `pip install -e '.[dev,tray]' pyinstaller` (the `tray` extra carries
   Pillow and, on macOS, pyobjc; without it the build silently has no
   menu-bar icon. It no longer carries pystray — the tray backend is
   `ccsync_companion/tray_native.py`, ours, since 2026-08-17,
   docs/COMMERCIAL_READINESS.md item 3), then the full companion suite. `--skip-tests` records
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

### The no-Mac path: hosted runner + `tools/publish_package.py` (2026-08-17)

The Mac in "a second machine" no longer has to be anyone's laptop.
`.github/workflows/release-macos.yml` runs steps 1–5 above on a hosted
`macos-latest` runner (manual trigger; it builds, it never publishes — see
its header for why) and uploads `companion/dist/**` and `onboarding/dist/**`
as the artifact `ccsync-companion-macos`. Step 6 then happens **from the base
rig**, with the offline key, using the publish-only tool
(`docs/ZERO_TOUCH_PLAN.md` WP E, first slice):

```powershell
gh workflow run release-macos.yml --ref main
gh run watch                                        # ~10 min
gh run download -n ccsync-companion-macos -D .\ci-mac
dashboard\.venv\Scripts\python.exe tools\publish_package.py `
    --manifest ci-mac\companion\dist\ccsync-release.json `
    --dashboard-url <url> --admin-user <you> --make-current
# and the wizard, if onboarding/dist produced one:
dashboard\.venv\Scripts\python.exe tools\publish_package.py `
    --artifact ci-mac\onboarding\dist\<zip> --kind onboard --platform macos `
    --version <installer version> --dashboard-url <url> --admin-user <you> --make-current
```

`publish_package.py` signs first (no key, no login), pre-flights the version
over `DASH_REPORT_TOKEN` if present, prompts for the dashboard password
(getpass; `--password-stdin` for automation — never argv or env), PUTs, reads
the row back. `--manifest` **refuses** a `git_dirty` or `tests_run: false`
manifest unless `--allow-dirty` / `--allow-untested` — OPS-1 applies to
CI-built artefacts too. `--dry-run` prints the exact PUT without touching the
network. Exit codes: 2 usage, 3 already published, 4 login, 5 publish.

### What the lag looks like, and why it is expected

A Windows ship (`build_editor_package.ps1 -Publish -MakeCurrent`) publishes
the Windows companion and `onboard.exe`. It cannot publish either macOS
artifact: the companion binary comes from `tools/release_macos.sh --publish`
on the Mac, and (since installer 1.0.17) the `macos` `kind=onboard` package
is the **zipped onboarding wizard** from `tools/build_onboard_macos.sh
--publish` on the Mac too — the pre-1.0.17 behavior of pushing
`macos_bootstrap.sh` into that slot from Windows is retired (the script
still ships inside the editor package and inside the wizard bundle). So
between the Windows ship and the next Mac build session:

- the dashboard's `[ PUBLISHED PACKAGES ]` box shows the current `macos`
  `companion` (and possibly the `macos` installer) at an older version than
  the current `windows` ones;
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

## The release signing key (the upgrade channel's trust anchor)

*Added 2026-08-17 — `docs/COMMERCIAL_READINESS.md` item 4 (STOP-SHIP, C2).*

Until this existed, the upgrade channel had **no authentication at all**. The
companion learned about a new build from a plain-HTTP `/api/v1/report`
response, and the sha256 that "verified" the download came from *that same
response* — so anything able to answer as the dashboard could hand an editor
an arbitrary binary plus a matching hash, which the companion then renamed
over its own running exe and launched detached. Origin pinning and the
no-redirect opener narrowed that to "whoever controls the dashboard", which
on a customer install is a container on **their** NAS.

Now every published package carries an **Ed25519 signature over its whole
record**, made offline by a key that exists on no fleet machine and in no
repo. The dashboard stores and serves a signature it cannot produce.

### What is signed

```
kind · platform · version · filename · sha256 · size_bytes ·
min_version · published_at · signed_binary
```

The *whole record*, not just the hash: signing only the sha256 would leave
the server free to relabel a genuine build as another version, platform or
kind — which is how a Mac gets handed a Windows exe, or how the onboarding
installer gets offered as a companion self-upgrade. The `url` is deliberately
**not** signed: it is server-relative, and its host is pinned to the
configured dashboard by `upgrade.same_origin()`.

**One kind signs a tenth field.** A `dashboard` record — the dashboard's own
code bundle, applied by the container to itself (`ZERO_TOUCH_PLAN.md` WP K,
2026-08-18) — adds `runtime_id`, because that value decides whether the update
may be applied at all and an unsigned one could be relabelled. It is scoped to
the kind (`release_pubkey.KIND_EXTRA_FIELDS`), NOT added to every record: a
tenth field for everyone would need a `v2` prefix and an overlap release,
since an old companion canonicalises only the fields it knows and would reject
every new record. No companion ever sees a `dashboard` record.
`docs/RELEASE_FEED.md` §2.1a.

### Where the key lives

| | |
|---|---|
| **Private key** | `%USERPROFILE%\.ccsync-release\release.key` (mode 0600), **outside the repo, never committed**. Override with `CCSYNC_RELEASE_KEY`. |
| **Public key** | baked into `companion/src/ccsync_companion/release_pubkey.py` → `RELEASE_PUBKEYS` (a *list*, so keys can rotate). |
| **Dashboard's copy** | `DASH_RELEASE_PUBKEYS` in the container env (comma-separated). Verify-on-publish only. |

```powershell
python tools\release_key.py new       # once, ever. Refuses to clobber.
python tools\release_key.py pubkey    # the value for DASH_RELEASE_PUBKEYS
python tools\release_key.py bake      # writes the PUBLIC half into the companion
```

**Back the key file up offline.** Losing it means you can never offer the
fleet another build: every companion trusts only the keys baked into its own
binary, and the only way out is a hand reinstall on every machine.

`tools/release.ps1` refuses to build when `RELEASE_PUBKEYS` is empty (a
companion like that would refuse *every* update, permanently) and when the
key on this rig is not one the build trusts.

### Rotating

`RELEASE_PUBKEYS` is a list and **every** key in it is trusted. Rotation is a
two-release dance, and skipping the overlap strands the fleet:

1. `python tools\release_key.py new --force` then `... bake --add` — the new
   public key joins the old one. **Ship this build with the OLD key still
   signing.**
2. Once `check_deploy_drift.ps1` (and the dashboard's fleet grid) shows every
   machine on that build, sign with the new key and drop the old one from the
   list in a later release.

### The dashboard side

`DASH_RELEASE_PUBKEYS` unset ⇒ the publish route answers **503** and says so.
That is deliberate: a dashboard that would accept an unsigned build is one
compromise away from owning every editor's machine. A customer running their
own dashboard pins the **vendor's** key here.

**In image mode it is not optional at all.** A site whose `site.toml` says
`[stack] mode = "image"` (`docs/DOCKER.md`) gets a container whose `run.sh`
picks its code root at boot by verifying `/data/code/<version>` against these
keys — so with none, the image always wins and the dashboard's own
over-the-air code updates can never apply, not merely the publish route.
`server/install_dashboard_app.py --mode image` therefore **refuses to deploy**
with an empty value, before anything moves, rather than let a site migrate for
a feature it cannot have.

**Beyond one dashboard:** everything above is "one build reaches one
dashboard because someone PUT it there." For N customers there is also the
**release feed** (`docs/RELEASE_FEED.md`, `docs/ZERO_TOUCH_PLAN.md` WP E) —
publish the signed record once to a static host, and every dashboard that
has `DASH_RELEASE_FEED_URL` set pulls it and offers (or, on policy
`stage`/`current`, auto-applies) the same PUT this section describes,
through the exact same signature check. `DASH_RELEASE_FEED_URL` unset (the
default) means nothing here changes.

---

## Publishing the release feed (one command, no dashboard password)

Since 2026-08-18 `tools/publish_feed.py` does the upload itself, to **GitHub
Releases** (the chosen feed host). Build the exe as usual (`tools/release.ps1`,
step 2 above), then:

```powershell
dashboard\.venv\Scripts\python.exe tools\publish_feed.py `
    --manifest companion\dist\ccsync-release.json `
    --feed-dir .\feed --github-repo ccsync/ccsync-releases --github-upload
```

That is the whole ship for feed customers:

1. **build** — `tools\release.ps1` produces `companion\dist\ccsync-companion.exe`
   and its `ccsync-release.json` (the same manifest gate applies here: a
   `git_dirty` or `tests_run: false` manifest is refused unless
   `--allow-dirty`/`--allow-untested`).
2. **publish the feed** — the command above signs the record with the offline
   key, writes and signs `channel.json`, re-verifies its own output offline,
   and only then uploads `channel.json`, `channel.json.sig` and the artefacts
   to the release with `gh release upload … --clobber` (creating the release on
   first run). Re-running is idempotent; the tag is a stable pointer, not a
   per-version archive.
3. **the customer's dashboard** picks the channel up on its own schedule (or an
   admin's "Check now"), shows it under `[ AVAILABLE FROM THE VENDOR ]`, and an
   admin clicks **Publish** (or **Publish + make current**). On feed policy
   `stage`/`current` even that click is automatic — `docs/RELEASE_FEED.md` §4.

**No dashboard password is involved anywhere in this path.** That is the point
of it: `installer\build_editor_package.ps1 -Publish` (and
`tools\publish_package.py`) log in to one specific dashboard and prompt for its
admin password via `Read-Host`/`getpass`, which is N passwords and N ships for N
customers. The feed authenticates nothing to anyone — it publishes signed bytes
to a public host, and every dashboard decides for itself whether the offline
key signed them.

- `--github-repo OWNER/REPO` also **derives** `--base-url`
  (`https://github.com/OWNER/REPO/releases/download/<tag>`), and passing a
  `--base-url` that disagrees is refused: the download URL is inside the signed
  document, so a channel pointing away from its own assets cannot be corrected
  without re-signing. `--github-tag` (default `ccsync-releases-v1`) moves both.
- **`--github-upload` is required to upload.** Without it the tool only builds
  and signs the directory — regenerating a feed to look at it must never
  publish to the world.
- The **release key never goes near GitHub**. It signs on this rig; what
  travels is the already-signed channel plus the artefacts, and the only
  credential used is your own `gh auth login`. A missing or unauthenticated
  `gh` fails the run (exit 5) *after* the local feed is written and verified,
  and says which of the two to fix.

For any other host (S3, a CDN, a bucket) nothing changed: pass `--base-url`
and copy the directory yourself (`rclone sync .\feed remote:… --checksum`).

---

## The downgrade floor (`min_version`)

The offer has always been *"different, not newer"* — the dashboard advertises
whatever is `current`, so a deliberate rollback is offered to the fleet
exactly like an upgrade, with one click. That is a feature; it is also how a
stolen-or-replayed old build could reintroduce a whole round of security
fixes. Hence the floor.

- Each signed record carries `min_version`: **the oldest build this release
  says the fleet may still be rolled back to.**
- A companion remembers the **highest** `min_version` it has ever accepted in
  `~/.ccsync/upgrade_floor.json` and refuses any offer below it.
- Above the floor, nothing changes: rolling back to any version ≥ floor is
  still one click, still worded "Roll back to vX (older build)".

Set it per release with `$env:CCSYNC_MIN_VERSION` (Windows ship) /
`CCSYNC_MIN_VERSION` (macOS scripts); default `0.0.0`, i.e. no floor. **Raise
it whenever a release fixes something a downgrade would reintroduce.**

### Lowering it

**You cannot.** The floor is monotonic on purpose, and no signed record can
lower it — if a record could, then possessing one old, genuinely-signed
record with a low `min_version` would be enough to unwind the entire
mechanism, and old signed records are exactly what an attacker has.

To roll a machine below its floor, an operator deletes
`~/.ccsync/upgrade_floor.json` **on that machine** and restarts the
companion. That is hands-on, per box, and unautomatable from the dashboard —
which is the point: undoing a security floor should cost someone a trip to
each machine, not one click on a web page they may not control.

---

## Code signing (Authenticode / Developer ID)

Two *different* signatures, and neither substitutes for the other:

| | Protects against | Set by |
|---|---|---|
| **Release record** (Ed25519, above) | the fleet installing a build the vendor did not make | always, `tools/sign_release.py` |
| **Authenticode / Developer ID** | SmartScreen, Gatekeeper, AV quarantine, enterprise allowlists | only when a certificate is configured |

A build with no Authenticode signature still publishes and still upgrades
correctly. What it does is greet every *fresh* install with "Windows
protected your PC" (or, on a Mac, "cannot be opened because the developer
cannot be verified") — the single loudest signal a customer gets that this is
not a product. The manifest records `signed_binary`, `sign_release.py` signs
that into the record, and **`tools\ship.cmd` refuses `-MakeCurrent` for an
unsigned binary** unless you pass `-AllowUnsignedBinary`.

### What to buy

- **Windows:** an **OV** ("standard") or **EV** Authenticode code-signing
  certificate — DigiCert, Sectigo, SSL.com, GlobalSign. Roughly $200–600/yr.
  Since June 2023 the private key must live on FIPS-140-2 hardware (a USB
  token or a cloud HSM), so plan for the token to arrive by post and for the
  signing machine to be the one it is plugged into. **EV** starts with
  SmartScreen reputation from day one; **OV** has to earn it over some weeks
  of downloads, during which editors still see the warning.
- **macOS:** an **Apple Developer Program** membership ($99/yr) and the
  **Developer ID Application** certificate it lets you create, plus an
  app-specific password for `notarytool`. Notarisation is not optional for
  anything downloaded.

### Where the env vars go

Set them on the **release machine** (`setx` on Windows, the shell profile on
the Mac) — never in the repo, never in the dashboard.

```powershell
# Windows, EV token / HSM: the cert's SHA1 thumbprint in CurrentUser\My
setx CCSYNC_SIGN_THUMBPRINT  "A1B2C3..."
# or an OV .pfx on disk
setx CCSYNC_SIGN_PFX          "C:\certs\ccsync-ov.pfx"
setx CCSYNC_SIGN_PFX_PASSWORD "..."
# optional; defaults to http://timestamp.digicert.com
setx CCSYNC_SIGN_TIMESTAMP_URL "http://timestamp.sectigo.com"
```

```bash
# macOS
export CCSYNC_APPLE_DEV_ID="Developer ID Application: Your Co (TEAMID)"
export CCSYNC_NOTARY_PROFILE="ccsync-notary"
# created once:
xcrun notarytool store-credentials ccsync-notary \
    --apple-id you@example.com --team-id TEAMID --password <app-specific-password>
```

`tools/release.ps1` signs with `signtool sign /fd sha256 /tr <url> /td sha256`
(the timestamp is not optional — without it every signature this build ever
made turns invalid the day the certificate expires) and **stops the run** if
signtool fails: a build that was meant to be signed must not slip out
unsigned under a signed build's version number. `tools/release_macos.sh` and
`tools/build_onboard_macos.sh` do `codesign --sign "$CCSYNC_APPLE_DEV_ID"
--options runtime --timestamp`, then `notarytool submit --wait`, then
`stapler`. The wizard `.app` is stapled *before* the shipping zip is made
(the bare companion Mach-O cannot be stapled at all — Gatekeeper looks its
ticket up online instead).

With nothing configured, each script prints a loud **UNSIGNED BUILD**
advisory and marks the record `signed_binary: false`.

### Operator TODO

No certificate exists for this fleet yet. Everything above is wired and
tested; buying the certificates and setting the four env vars is the whole
remaining step, and until it happens `tools\ship.cmd` needs
`-AllowUnsignedBinary`.

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
  "built_by": "<user>@<build-host>",
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

## Refreshing the lockfiles

Every component carries a `requirements.lock` — the exact, hash-pinned closure
`uv pip compile` resolved from its `pyproject.toml` (or `requirements.txt`).
They are what CI installs, what `dashboard/deploy/Dockerfile` bakes into the
image, what `deploy/run.sh` prefers over `requirements.txt` inside the
container, and what `tools/check_licenses.py` judges. Added 2026-08-17
(`docs/COMMERCIAL_READINESS.md` item 13); the floors in `pyproject.toml` and
`deploy/requirements.txt` are still the hand-maintained source of truth, and a
lock is only ever regenerated FROM them.

**A version bump goes in the `pyproject.toml`/`requirements.txt` floor first,
then into the lock.** Editing a lock by hand invalidates its hashes.

```bash
# One component. --universal keeps the win32/darwin/linux markers, so ONE lock
# serves the Windows exe, the Mac app and the Linux container.
cd companion && uv pip compile --universal --generate-hashes \
    --python-version 3.12 -o requirements.lock pyproject.toml --extra tray --extra dev
```

The full set, with the extras each one needs (run from the repo root; `uv` is
the resolver — `pip-compile --generate-hashes` from pip-tools produces the same
thing if you prefer it):

| Component | Input | Extras |
|---|---|---|
| `companion` | `pyproject.toml` | `tray`, `dev` |
| `dashboard` | `pyproject.toml` | `broll`, `music`, `ytdl`, `ytdl_unblock`, `synology`, `oidc`, `dev` |
| `dashboard/deploy` | `requirements.txt` | — (the base container set) |
| `dashboard/deploy` (unblock) | `requirements-unblock.txt` | — (the GPLv3 YouTube-unblock plugin, installed only when `[features] youtube_unblock` is on — see the file's own header and `docs/CI.md`) |
| `server` | `requirements.txt` | — |
| `onboarding` | `requirements.in` | — |
| `bench` | `pyproject.toml` | `dev` |
| `broll/web`, `music/web`, `ytdl/web` | `pyproject.toml` | `test` |
| `broll/indexer` | `pyproject.toml` | `dev` |
| `music/indexer` | `pyproject.toml` | `dev` |

Two of these have caveats worth knowing before you regenerate them:

- **`dashboard/deploy/requirements.lock` is the one the fleet runs.** Changing
  it changes what every customer's container installs on its next boot, and
  `run.sh` re-runs pip only when the file's hash changes — so a bump here *is*
  the container upgrade mechanism, exactly as `requirements.txt` was.
  `dashboard/deploy/requirements-unblock.lock` is the same mechanism for one
  optional package (`bgutil-ytdlp-pot-provider`, GPLv3): `run.sh` installs it
  into the same venv only when `DASH_SITE_YOUTUBE_UNBLOCK=1`, so this lock
  never reaches a customer who has not turned `[features] youtube_unblock`
  on (`docs/COMMERCIAL_READINESS.md` items 2/3). Regenerate it the same way,
  from `requirements-unblock.txt`, and keep `dashboard/pyproject.toml`'s
  `ytdl_unblock` extra in step — `dashboard/tests/test_hardening.py`'s
  `test_deploy_unblock_requirements_match_pyproject_ytdl_unblock_group`
  checks both directions.
- **`music/indexer` pulls `torch` and, on Linux, the whole `nvidia-*` set.**
  That is the CPU/default-PyPI wheel set and it is correct for the base rig;
  the CUDA-index build belongs to the GPU image (item 14), not here. It is
  deliberately not installed by CI.

After regenerating, run `python tools/check_licenses.py` — a new transitive
dependency with a copyleft licence is exactly what the gate exists to catch,
and the lock is where it first appears.

---

## Quick reference

```powershell
.\tools\ship.cmd                                # ALL OF THE ABOVE, in order, gated
.\tools\ship.cmd -DashboardOnly                 # stop after the dashboard deploy
.\tools\ship.cmd -AllowDirty                    # publish from a dirty tree (deliberate hotfix)
.\tools\ship.cmd -AllowUnsignedBinary           # make an exe with no Authenticode signature CURRENT
python tools\release_key.py new|pubkey|bake     # the offline release signing key (once, ever)
.\tools\check_deploy_drift.ps1                  # what is actually running, anywhere
.\tools\release.ps1                             # parity + tests + build + manifest
.\tools\release.ps1 -DryRun                     # show the pipeline, change nothing
.\tools\release.ps1 -SkipTests -AllowDirty      # fast local iteration build
.\installer\build_editor_package.ps1 -Publish -MakeCurrent   # ship to the fleet (prompts for the dashboard password)
python tools\publish_feed.py --manifest companion\dist\ccsync-release.json `
    --feed-dir .\feed --github-repo <owner/repo> --github-upload   # ship to EVERY feed customer (no password)
python tools\publish_feed.py --verify .\feed                 # offline-check a feed dir
python tools\build_dashboard_bundle.py --out .\dist          # the DASHBOARD's own code bundle
python tools\build_dashboard_bundle.py --verify .\dist\ccsync-dashboard-<v>.tar.gz
python tools\publish_feed.py --artifact .\dist\ccsync-dashboard-<v>.tar.gz `
    --kind dashboard --platform linux --version <v> `
    --feed-dir .\feed --github-repo <owner/repo> --github-upload   # every feed customer's dashboard
python tools\publish_feed.py --asset music\web\data\audio_encoder\music-clap-audio-1.onnx `
    --asset music\web\data\audio_encoder\music-clap-audio-1.params.json `
    --asset-kind music-clap-audio --asset-version 1 `
    --feed-dir .\feed --github-repo <owner/repo> --github-upload   # the CLAP audio tower (not in git)
.\installer\windows_upgrade.ps1 -CompanionExe <path-to-exe>  # install here
.\tools\check_deploy_drift.ps1 -AdminUser <your-dashboard-admin>   # + published version, machines behind
```

These are PowerShell 5.1 scripts. Execution policy on a fresh shell:
`Set-ExecutionPolicy -Scope Process Bypass`.

On the Mac (bash, and only there):

```bash
./tools/release_macos.sh                        # parity + tests + build + sign + manifest
./tools/release_macos.sh --dry-run              # show the pipeline, change nothing
./tools/release_macos.sh --publish --make-current   # ship to the Mac editors
```
