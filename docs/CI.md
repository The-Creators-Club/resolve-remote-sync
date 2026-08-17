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
a PowerShell bootstrap.

### `ubuntu-latest`

`dashboard`, `server` (through bash), `broll/web`, `music/web`, `ytdl/web`,
`broll/indexer`, and `tools` — plus:

- **the licence gate**, `tools/check_licenses.py --strict`. Strict because by
  that point every lock in the job has been installed, so "could not read this
  package's licence" is a real gap rather than "not on this developer's
  machine". See `tools/license_allowlist.toml`.
- **two line-ending checks.** `.gitattributes` forces `eol=lf` on everything
  the NAS container or a Mac executes, because a CRLF `run.sh` once took the
  dashboard down (`set -eu` → *"Illegal option -"*: dash read the CR as an
  option character) and `installer/macos_bootstrap.sh` had the same defect
  while already sitting on the editor share. The developer-side check is
  unreliable — **MSYS grep strips a CR before matching** — so the runner
  byte-scans instead, and separately asserts `git ls-files --eol` shows `i/lf`.

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

### `release-macos.yml`

**This is the one that closes a real gap.** PyInstaller does not cross-compile,
so `tools\ship.cmd` publishes neither macOS artefact and prints an advisory
instead — and the consequence in the field is that Mac editors run a build from
a previous fix pass until someone sits at a Mac. A hosted `macos-latest` runner
is that Mac, on demand.

It runs `tools/release_macos.sh` without `--publish`, then best-effort
`tools/build_onboard_macos.sh`, and uploads both `dist/` trees.

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

## Operator setup

1. Push the repo to GitHub (it has never had a remote CI provider).
2. Add the signing secrets above **if and when** certificates exist. Without
   them CI is fully green and the release workflows produce unsigned builds.
3. Optionally make `ci.yml` a required status check on the default branch.
4. Note that `macos-latest` minutes are billed at a multiplier on private
   repositories. If that bites, drop the macOS job from `ci.yml` (keeping
   `release-macos.yml`, which is manual and infrequent).
