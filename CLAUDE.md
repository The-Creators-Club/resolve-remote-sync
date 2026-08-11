# CC Sync — Creators Club fleet sync + b-roll platform

Multi-machine video workflow for a DaVinci Resolve editing fleet: a TrueNAS
server holds the canonical project tree, remote editors sync slices of it, and
a set of companion apps keep Resolve, the filesystem, and the fleet dashboard
honest. `SPEC.md` is the architecture document; `KNOWN_BUGS.md` is the live
defect ledger (numbered entries, per-platform prefixes).

## Components

| Dir | What it is | Runs where |
|---|---|---|
| `companion/` | `ccsync_companion` — editor tray app: sync lanes (A rclone-up, B rclone-down, C Syncthing), Resolve watcher/fixer/popup, LUT link, upgrade channel client, and the b-roll "Send to Resolve" loopback server (`broll_server.py`, 127.0.0.1:8899) | every editor machine + base rig, frozen via PyInstaller |
| `dashboard/` | `ccsync_dashboard` — FastAPI fleet dashboard (sync status, transfers, provisioning, admin) | TrueNAS container; deployed by `server/install_dashboard_app.py` |
| `server/` | NAS-side install/setup scripts (dashboard app, Syncthing folders, editor accounts, tree) | run from the base rig against the NAS over SSH |
| `installer/` | per-OS editor bootstrap (drive mapping, companion install, Resolve prefs) | editor machines |
| `onboarding/` | first-run wizard | editor machines |
| `bench/` | `ccbench` sync-engine benchmark harness | ad hoc |
| `broll/` | the b-roll platform, folded in from the standalone `broll-platform` repo 2026-08-10 (pre-fold git history stays there): `web/` search UI + API, `indexer/` Claude-based clip indexing pipeline, `eval/` search eval | web: mounted in-process at `/broll` by the dashboard (see below); indexer: base rig |
| `music/` | the music tagger, folded in from the standalone `music-tagger` repo 2026-08-10 (pre-fold history stays there): `web/` CLAP search UI + API, `indexer/` CLAP embedding/tagging pipeline, `eval/` quality measurement | web: mounted in-process at `/music` by the dashboard; indexer: base rig (needs the GPU) |
| `docs/` | operational docs (SERVER, EDITOR_SETUP, GOTCHAS, bug-hunt notes) | — |

`broll/companion/` no longer exists: the standalone BRoll Companion was
absorbed into `ccsync_companion/broll_server.py` (2026-08-10). It must not
run alongside the tray app — it would hold port 8899.

## How the pieces join

- The dashboard mounts `broll/web`'s FastAPI app at `/broll`
  (`dashboard/src/ccsync_dashboard/broll.py`) — in-process, behind the
  dashboard's login, with its own fail-closed ingest-token gate. A broken or
  absent b-roll checkout must NEVER stop the dashboard from booting.
  Deployment ships `broll/web` to the NAS (`install_dashboard_app.py`,
  `BROLL_WEB_SRC` overrides); a bare dev checkout works too (mount_broll
  falls back to the in-repo path).
- The b-roll web UI's "Send to Resolve" button calls the companion's loopback
  server on 127.0.0.1:8899. Frontend URLs are document-relative on purpose —
  `broll/web/tests/test_mounted_prefix.py` pins this; never introduce a
  root-relative `/api|/media|/static` URL in `broll/web/static/`.
- The dashboard mounts `music/web` at `/music` on the same contract as b-roll
  (`dashboard/src/ccsync_dashboard/music.py`): in-process so the audio route's
  Range/206 responses are not proxied, behind the dashboard login, tri-state
  and best-effort so a broken music checkout can never stop the dashboard
  booting. Its frontend URLs are document-relative for the same reason
  b-roll's are — `music/web/tests/test_mounted_prefix.py` pins it, and the
  bare `/music` → `/music/` redirect is load-bearing, not incidental.
- The music UI's "send to Resolve" calls the companion's loopback on
  127.0.0.1:8899 too — `POST /music/send` / `GET /music/status`, added to
  `broll_server.py`'s handler rather than a second server, since a second
  listener on 8899 breaks the tray app. The body is `{action, share,
  rel_path}`, never a path: the page is served from the NAS, so only the
  editor's own browser can reach their Resolve, and only their companion knows
  the library is at `P:\Assets\Music` there. **Editors need a republished
  companion before any of this exists for them** — the deployed build 404s on
  `/music/*`.
- **The music web package is `musicweb`, deliberately NOT `app`.** `broll/web`
  is deployed by putting its tree on PYTHONPATH and importing it as top-level
  `app`; a second package of that name would collide in `sys.modules` and one
  would silently win.
- Music indexing needs the GPU and stays on the base rig. The container only
  ever embeds *query text* (measured 18 ms/query on CPU, and only the 125M-param
  text tower of the 194M model) — audio embeddings, tags, axes, waveform peaks
  and the source-bias axes are all precomputed into `music/web/data/music.db`.
- Companion builds reach editors through the dashboard's upgrade channel
  (publish with `-Publish -MakeCurrent`). macOS bundles must be built ON a
  Mac (`tools/release_macos.sh`); they cannot be cross-built from Windows.
- The editor tree root is the P: drive, **deliberately hardcoded** (a
  configurable drive letter is explicitly deferred). The b-roll archive is
  `P:\Assets\B-roll Archive`, shared by SMB browsing, the search UI's media,
  and Resolve timelines alike.

## Running tests

Everything at once: `powershell -File tools\run_all_tests.ps1` (runs all 8
suites with the right interpreters, summary table at the end).

Per-component venvs; run pytest from the component dir so `python -m pytest`
puts the in-repo package first on sys.path:

```powershell
cd companion;   .venv\Scripts\python.exe -m pytest tests -q
cd dashboard;   .venv\Scripts\python.exe -m pytest tests -q
cd bench;       .venv\Scripts\python.exe -m pytest tests -q
cd server;      ..\dashboard\.venv\Scripts\python.exe -m pytest tests -q   # no venv of its own; RUN IT FROM GIT BASH (see below)
cd onboarding;  python -m pytest tests -q                                  # system python
cd broll\indexer; python -m pytest tests -q                                # system python
cd broll\web;   E:\Projects\broll-platform\web\.venv\Scripts\python.exe -m pytest tests -q
cd music\web;   .venv\Scripts\python.exe -m pytest tests -q                # own venv, deliberately no torch
powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-DriveMapParser.ps1
```

`broll/web` still borrows the old standalone repo's venv (the in-repo copy
has none yet); the dashboard venv also has its deps and can substitute.

**Run `server/`'s suite from Git Bash, not PowerShell.** 18 of its tests
execute the generated remote scripts under a stub `sudo`/`chown`, and where
pytest is launched from decides what they mean (measured 2026-08-10): from Git
Bash, 214 pass; from PowerShell with no `bash`, those 18 **skip silently**;
from PowerShell with `bash` on PATH, **5 fail falsely** — the harness prepends
its stub dir using `os.pathsep` (`;`), and a bash inheriting that Windows-style
PATH resolves `chown` to MSYS's real one (`chown: invalid user: 'root:root'`).
`tools\ship.cmd` handles this itself by invoking pytest through Git's bash.

## Building & shipping (existing commands — don't invent wrappers)

**There is one command. It is `tools\ship.cmd`.** Everything below it is what
that command already runs; reach for the individual scripts only to redo one
part, never to assemble a release by hand.

```powershell
tools\ship.cmd            # THE ship: gates -> dashboard deploy -> companion + onboard.exe build
                          # -> publish + make current -> upgrade this machine -> drift check.
                          # Prompts ONCE for your dashboard admin password (build_editor_package.ps1
                          # Read-Host, no env-var path) -- so it needs a real interactive terminal.
                          # (.cmd, not .ps1 -- execution policy blocks the direct .ps1 invocation)
```

It refuses to start, before anything moves, on: a missing `TRUENAS_PW` /
`DASH_REPORT_TOKEN` / `DASH_SESSION_SECRET` / `SYNCTHING_API_KEY`, a **dirty
working tree** (a `+dirty` build must not reach the fleet — `-AllowDirty` for a
deliberate hotfix), a companion version **already published** (bump `VERSION` in
`config.py` *and* `pyproject.toml`), or a failing **`server/` suite** — the one
suite `release.ps1` does not run, guarding the deploy script step 1 executes
(`-SkipTests` to skip). Flags: `-DashboardOnly`, `-SkipLocalUpgrade`.

```powershell
tools\release.ps1                                            # Windows companion: parity + tests + PyInstaller + manifest
installer\build_editor_package.ps1 -RebuildExe -RebuildOnboard   # editor package (add -Publish -MakeCurrent to ship it)
installer\windows_upgrade.ps1 -CompanionExe <path>           # install a build on THIS machine
tools\check_deploy_drift.ps1 [-AdminUser alex]               # read-only doctor: repo vs built vs installed vs live
tools\run_all_tests.ps1                                      # all 8 suites (ship only gates on server/)
```

**The Mac half cannot run from Windows** — PyInstaller does not cross-compile,
so `ship` publishes neither macOS artifact and prints an advisory instead. Both
of these run **on a Mac**, and until they do, Mac editors stay on their old build:

```bash
git pull && ./tools/release_macos.sh --publish --make-current   # macOS companion
./tools/build_onboard_macos.sh --publish                        # macOS wizard (installer ≥ 1.0.17)
```

Full runbook, including what each version number means and how to roll back:
`docs/RELEASE.md`.

## Conventions that matter here

- **Comments explain constraints, history, and failure modes** — never what
  the next line does. Most non-obvious decisions cite a date or a bug id;
  keep doing that.
- Never gut the live thing: deploys stage-verify-swap; optional features
  (like the /broll mount) fail absent, not fatal; "the dashboard is what
  tells everyone whether their footage is syncing" outranks any feature.
- `.gitattributes` forces `eol=lf` on shell scripts — anything the NAS
  container or a Mac executes. A CRLF `run.sh` once took the dashboard down,
  and a working copy checked out BEFORE a rule was added stays CRLF until
  re-checked-out (`rm` + `git checkout --`; verify with `git ls-files --eol`).
  Do not trust MSYS grep to find a CR — it strips them before matching;
  byte-scan instead (2026-08-10).
- Verify companion/tray fixes against the **deployed** build
  (`%LOCALAPPDATA%\ccsync\bin`), not just the repo: the running tray won't
  reflect source changes until a build is published.
- Windows pytest here can spawn real Tk dialogs if fixtures are bypassed —
  follow the existing conftest patterns when touching popup/tray tests.
- Version lives in `companion/src/ccsync_companion/config.py` (`VERSION`);
  the upgrade channel's version-difference rule makes republishing an older
  build a first-class rollback.
