# CI.md — what runs on a runner, and what still only runs here

Added 2026-08-17 for `docs/COMMERCIAL_READINESS.md` item 13. Before this there
was no CI of any kind: ~5,250 tests ran when someone remembered, on one Windows
box, and `tools\ship.cmd` gated on exactly one suite (`server/`).

Three workflows, all in `.github/workflows/`:

| Workflow | Trigger | What it is for |
|---|---|---|
| `ci.yml` | every push + PR | every suite, on the OS each one is for, plus the licence and line-ending gates |
| `release-windows.yml` | manual | build `ccsync-companion.exe` on clean hardware; upload it; **never publishes** |
| `release-macos.yml` | manual | build the macOS companion **on an actual Mac**; upload it; **never publishes** |

---

## `ci.yml`

Three jobs, one per runner OS. Every step inside a job carries
`if: ${{ !cancelled() }}`, so a failing suite does not hide the ones after it —
the same behaviour `tools\run_all_tests.ps1` has locally, and for the same
reason: one red suite should not cost you a second round trip to see the others.

### `windows-latest`

`companion`, `onboarding`, `bench`, and the installer's PowerShell drive-map
parser test. These are the Windows-first pieces by construction: ctypes Win32
calls, a registry Run key, a logon task, a loopback SMB share, Tk dialogs, and
a PowerShell bootstrap. Two things happen before any of that:

- **Git's bash goes ahead of WSL's on PATH.** `windows-latest` carries both —
  `C:\Program Files\Git\bin\bash.exe` (a real POSIX shell) and
  `C:\Windows\System32\bash.exe` (the WSL launcher stub), with WSL winning by
  default PATH order. `companion/tests/test_publish_password_hygiene.py` and
  `test_rclone_stanza_rewrite.py` find bash with `shutil.which("bash")`, i.e.
  whatever PATH says first; WSL's stub answers in UTF-16, which reads as every
  assertion about the script's stdout failing at once rather than as "wrong
  interpreter" (measured on run 32036759518: 37 failures). The first step
  prepends `C:\Program Files\Git\bin` to `GITHUB_PATH`, which GitHub *prepends*
  to PATH for every later step.
- **A pinned `rclone` lands at `companion/.tools/rclone.exe`.**
  `companion/tests/conftest.py`'s `rclone_binary` fixture checks PATH first,
  then that path; a bare `windows-latest` runner has no rclone on PATH at all,
  so the 24 real-rclone lane-direction tests (lane A carries video UP only,
  lane B carries `**/Proxy/**` DOWN only — the most destructive thing in the
  system to get backwards) silently **skipped** rather than ran. The download
  is the same version+hash `installer/windows_bootstrap.ps1` ships to every
  editor (`$RcloneVersion`/`$RcloneZipSha256`), verified before extraction,
  same as the installer does — so this exercises the exact build the fleet
  gets, not whatever `winget` resolves to today.

The job also runs `tools/check_licenses.py --strict --only companion
--platform win32` after the companion suite — see "The licence gate is split
by platform" below.

### `ubuntu-latest`

`dashboard`, `server` (through bash), `broll/web`, `music/web`, `ytdl/web`,
`broll/indexer`, and `tools` — plus:

- **the licence gate**, `tools/check_licenses.py --strict --only
  dashboard-container --platform linux`. Strict because by that point every
  lock this target needs (`dashboard`, `music/web`, `ytdl/web`) has been
  installed, so "could not read this package's licence" is a real gap rather
  than "not on this developer's machine". `--only`/`--platform` scope it away
  from the `companion` target — see below — and `tools/license_allowlist.toml`
  is where a copyleft package gets an excuse.
- **two line-ending checks.** `.gitattributes` forces `eol=lf` on everything
  the NAS container or a Mac executes, because a CRLF `run.sh` once took the
  dashboard down (`set -eu` → *"Illegal option -"*: dash read the CR as an
  option character) and `installer/macos_bootstrap.sh` had the same defect
  while already sitting on the editor share. The developer-side check is
  unreliable — **MSYS grep strips a CR before matching** — so the runner
  byte-scans instead, and separately asserts `git ls-files --eol` shows `i/lf`.

`broll/indexer`'s install step also `pip install`s `numpy==2.5.2` — unpinned by
hash, pinned by version, deliberately outside the `--require-hashes -r
requirements.lock` install. `broll_index/embed.py` imports numpy
unconditionally even though the module's own docstring calls only `fastembed`
optional; the lock was compiled with `--extra dev` only (its own header
comment) and has never carried numpy, and the `embeddings` extra that would
(pulling in fastembed's ONNX runtime too) stays out on purpose — this job only
needs numpy importable so collection does not explode, not the model runtime.
The version matches what `broll/web` and `music/web` already hash-lock, so it
is not a floating pin; **do not regenerate `broll/indexer/requirements.lock`**
to "fix" this instead — the indexer is not a conveyed artefact (see the
licence gate above) and this is a test-time import only.

### The licence gate is split by platform

`companion`'s lock is `platforms=["win32", "darwin"]` — ONE lock feeds two
frozen builds nobody builds on the same machine — so no single CI job can ever
install both halves: `colorama`'s marker is `sys_platform == 'win32'`,
`pyobjc-core`/`pyobjc-framework-cocoa`'s is `== 'darwin'`, and pip will never
install either on the other OS no matter what runs `pip install`. Before
`tools/check_licenses.py` grew `--only`/`--platform` (2026-08-17, first hosted
CI run), the Linux job's `--strict` reported every one of companion's ten
packages `UNSCANNED` — a failure no install step could ever fix from Linux.
Now: the `windows` job asserts companion's win32 half, the `macos` job asserts
its darwin half, and the `linux` job does not touch companion at all (`--only
dashboard-container`) rather than report a false gap. Between the three, every
package in every target's full platform closure is still asserted somewhere,
`--strict`, exactly once, on the one job that could have actually installed
it. See `tools/check_licenses.py`'s `check()` docstring for the mechanism.

Two details there are not stylistic:

- **`server/` runs through bash.** 18 of its tests execute the generated remote
  scripts under a stub `sudo`/`chown`, and where pytest is launched from decides
  what they mean: from PowerShell with no bash they **skip silently** and the
  summary prints PASS (measured 2026-08-10, OPS-6).
- **`python -m pytest` from the component dir.** Module-run puts the cwd first
  on `sys.path`, which is what makes the in-repo package win over anything
  stale. The dashboard additionally gets `PYTHONPATH=src`, because its package
  lives under `src/` — which is also exactly what `deploy/run.sh` does in
  production.

### `macos-latest`

The companion suite, and `tools/release_macos.sh --dry-run` as a smoke test of
the release script itself (it prints every step and builds nothing). The macOS
port is code-complete with real platform branches everywhere, and until this job
existed **none of them ran anywhere**.

Same pinned-rclone step as the Windows job, downloading the `osx-arm64` build
(`macos-latest` is Apple Silicon) to `companion/.tools/rclone` — same
version+hash `macos_bootstrap.sh` ships to every editor Mac
(`RCLONE_VERSION`/`RCLONE_SHA256_ARM64`). Without it this job ran the suite
with 51 rclone tests silently skipped rather than executed; this is the "yes,
cheap enough" half of the same fix `release-macos.yml` needed as a hard
failure (see below). The job also runs `tools/check_licenses.py --strict
--only companion --platform darwin` — see "The licence gate is split by
platform" above.

The job has a 30-minute timeout on purpose: the companion suite can spawn real
Tk dialogs when a fixture is bypassed (CLAUDE.md), and on a runner with no
window server a stray dialog *hangs* rather than failing.

### Dependencies

Every suite gets its own venv, installed from that component's
`requirements.lock` with `--require-hashes`. No suite installs "whatever pip
resolves today", and `pip` is cached by `actions/setup-python` keyed on the
lockfiles. Regenerating a lock is documented in `docs/RELEASE.md`
("Refreshing the lockfiles").

`music/indexer` is **deliberately absent**: its dependency set is `torch` plus
the whole `nvidia-*` stack, which belongs to the GPU image (item 14). Its lock
exists; CI does not install it.

---

## What CI cannot cover

A GitHub runner cannot reach the NAS (`192.168.0.10` / the Synology /
either tailnet address), an editor machine, DaVinci Resolve, a real rclone
remote, a Syncthing instance, or the dashboard. The suites already account for
this — they probe for the binary or the host and skip themselves — and if you
add a test that needs one of those, **make it skip, do not make CI green by
deleting it.**

So these remain local-only, on the base rig:

- anything that touches the live NAS: `server/install_*.py` against a real host,
  `tools/check_deploy_drift.ps1`, the dashboard deploy.
- the Resolve bridge, the BPG UI-Automation path, and the tray's real Windows
  shell integration.
- `tools\ship.cmd` end to end. **CI is not a release path.** Neither release
  workflow publishes: a runner cannot reach the tailnet, and an upgrade channel
  that any workflow could write to would be a supply-chain hole rather than a
  convenience.

---

## The release workflows

Both are `workflow_dispatch` only, with `skip_tests` / `allow_dirty` inputs, and
both upload the artefact for a human to publish from a machine on the tailnet.

### `release-windows.yml`

Runs `tools/release.ps1` — version parity, both suites, PyInstaller,
provenance manifest — then uploads `ccsync-companion.exe` and
`ccsync-release.json`, and prints the manifest into the run summary.

It installs `pyinstaller==6.21.0` explicitly, because `release.ps1` creates the
venv but assumes the freezer is already there (on the base rig it always has
been). PyInstaller is deliberately **not** in `requirements.lock`: it is a
GPL-2.0 *build tool*, not something we convey, and keeping it out is what lets
`tools/check_licenses.py` stay strict about the frozen set.

It also installs the same pinned `rclone` as `ci.yml`'s windows job, into
`companion/.tools/rclone.exe`, before the build step: `release.ps1` runs the
companion suite with `CCSYNC_REQUIRE_RCLONE=1` — a missing binary is a hard
*failure* there, not a skip, because a release must not be cut without the
lane A/B direction coverage.

### `release-macos.yml`

**This is the one that closes a real gap.** PyInstaller does not cross-compile,
so `tools\ship.cmd` publishes neither macOS artefact and prints an advisory
instead — and the consequence in the field is that Mac editors run a build from
a previous fix pass until someone sits at a Mac. A hosted `macos-latest` runner
is that Mac, on demand.

It installs the same pinned `rclone` (`osx-arm64`) as `ci.yml`'s macos job
before the build step, for the same reason `release-windows.yml` does:
`release_macos.sh` runs the companion suite with `CCSYNC_REQUIRE_RCLONE=1`, so
a missing binary is a hard failure rather than a silently-dropped 24 tests —
which is exactly what happened on this workflow's first-ever run
(32036993646, before this step existed): 31 errors, "rclone not found.
Searched: PATH, companion/.tools/rclone, ~/.local/ccsync/bin/rclone".

It runs `tools/release_macos.sh` without `--publish`, then best-effort
`tools/build_onboard_macos.sh`, and uploads both `dist/` trees.

`skip_tests` stays as the emergency valve for the ~20 non-rclone macOS
failures (tray ctypes, `WindowsPath`, BPG, ports, proxy history,
`resolve_bridge`) tracked separately — a suite-only failure should not by
itself block getting an artefact to a Mac editor when the exe/app build
succeeded regardless.

### Signing secrets

Nothing is required; a build with none of these set is unsigned and says so.
Names are the ones `tools/release.ps1` already reads (item 4):

| Secret | Used by | Note |
|---|---|---|
| `CCSYNC_SIGN_THUMBPRINT` | windows | SHA1 of a cert in `CurrentUser\My`. An EV token is physical — **not usable from a hosted runner.** |
| `CCSYNC_SIGN_PFX_BASE64` | windows | An OV `.pfx`, base64'd. The workflow decodes it under `RUNNER_TEMP` (never the workspace, which is what gets uploaded) and exports `CCSYNC_SIGN_PFX`. This is the one a hosted runner can actually use. |
| `CCSYNC_SIGN_PFX_PASSWORD` | windows | with the above |
| `CCSYNC_SIGN_TIMESTAMP_URL` | windows | optional RFC3161 override. A timestamp is not optional in substance: without one, every signature the build ever made goes invalid the day the certificate expires. |
| `CCSYNC_APPLE_DEV_ID` | macos | Reserved. `release_macos.sh` ad-hoc signs today (which is why a macOS upgrade resets TCC permissions); the variable is already exported so the workflow needs no edit when the script learns to use it. |

---

## Known test-side failures on the first hosted run, not fixed here

Run 32036759518 also failed for reasons that are bugs in the *tests*, not the
CI environment — out of scope for whoever owns `.github/workflows/*` and
`tools/check_licenses.py` (this doc's owner) to touch, since the suites
themselves belong to other components:

- **`onboarding/tests/test_steps.py::test_find_companion_exe_falls_back_to_dev_dist`**
  is `skipif`'d on `sys.platform != "win32"` only. On `windows-latest` that
  guard passes, but the job never builds `companion/dist/ccsync-companion.exe`
  (nothing in the onboarding job does), so the test fails with
  `FileNotFoundError` instead of skipping. The fix is in the test's own
  `skipif`, not the workflow: also skip when
  `(repo root)/companion/dist/ccsync-companion.exe` does not exist, e.g.
  `sys.platform != "win32" or not (Path(__file__).resolve().parents[2] /
  "companion" / "dist" / "ccsync-companion.exe").exists()`.
- **`server/tests/test_synology_backend.py`** (×2) raise
  `common.EnvError: Required environment variable TRUENAS_PW is not set`. They
  only pass on the base rig because `TRUENAS_PW` happens to be in that
  operator's shell environment — a CI-environment difference the test should
  not depend on, not something `ci.yml` should paper over by setting a fake
  credential.
- `dashboard/tests/test_topbar_partial.py` and some `music/web` failures are
  also test-side; see those suites' own owners.

## Operator setup

1. Push the repo to GitHub (it has never had a remote CI provider).
2. Add the signing secrets above **if and when** certificates exist. Without
   them CI is fully green and the release workflows produce unsigned builds.
3. Optionally make `ci.yml` a required status check on the default branch.
4. Note that `macos-latest` minutes are billed at a multiplier on private
   repositories. If that bites, drop the macOS job from `ci.yml` (keeping
   `release-macos.yml`, which is manual and infrequent).
