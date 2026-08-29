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
- The editor tree root is **site data, not code** (2026-08-17,
  COMMERCIAL_READINESS.md item 11): the drive letter comes from the site
  manifest's `canonical_prefix` (default `P:\`) and the tree name from
  `tree_name`; both installers, both uninstallers and the companion read the
  same two keys. `P:` remains the shipped default and every machine in the
  field is on it — what changed is that a second customer no longer forks
  the installer. The b-roll archive is `<prefix>\Assets\B-roll Archive`,
  shared by SMB browsing, the search UI's media, and Resolve timelines alike.
- **No customer's name in code.** Brand strings come from the site manifest
  (`org_name`/`org_short`) with the product name (`CC Sync`) as the last
  fallback; the tray/popup copy goes through `companion/site.drive_phrase()`,
  the dashboard's through `ui._render`'s `brand_org`. macOS bundle ids and
  launchd labels are `com.ccsync.*`; any installer that writes the new label
  must boot out and delete the legacy `com.creatorsclub.*` pair.
- **Optional features are off in the vendor build and turned on per
  customer** in `site.toml [features]`, published by `GET /api/v1/site` and
  read by the companion via `site.feature_enabled` (fails closed).
  `youtube_download` gates the whole `/ytdl` stack; `youtube_unblock`
  additionally gates the anti-anti-automation components. The code stays in
  the tree, dormant — never a second binary.
- The b-roll indexer and the ytdl service call an **AI provider over HTTP**,
  never a bundled CLI (2026-08-17, COMMERCIAL_READINESS item 1 — we shipped
  the 304 MB `claude` binary to customer hardware and ran every deployment on
  one consumer account). The indexer is the `anthropic` SDK with
  `ANTHROPIC_API_KEY`; cost/knobs in `broll/docs/indexing-api.md`.
  **The ytdl service since 2026-08-18 resolves a provider per call**
  (`ytdlweb/ai_backend.py` ← `ccsync_dashboard/ai_providers.py`): the first
  available of `claude_code > anthropic_api > codex > openai_api >
  deepseek_api`, with keys entered on **Settings → AI providers** (files
  under `<data>/secrets/ai/`, 0600; the environment always wins) and an
  admin pin. The two **CLI** entries are adapters for a binary on the
  dashboard host, dark unless `site.toml [features] ai_cli_providers` is on
  (off in the vendor build). **We BUNDLE nothing and never will** (item 1:
  no image layer, no package record, no release artefact) — but since
  2026-08-18 `cli_tools.py`'s **SET UP wizard** can fetch one at the admin's
  click, from the publisher's own distribution, checksum-verified, into
  `<data>/tools/<tool>/`, and drive the browser sign-in through a pty (URL
  out, code back, five-minute timeout). **That checksum is a CONDITION**
  (trust-model-7, 2026-08-21): a release that publishes no checksum for the
  asset is REFUSED, never installed unverified behind a note in a state file
  nobody reads, and the admin is sent to the "type its full path" fallback
  for a copy they installed and vouch for themselves. Its `$HOME` is
  `<data>/tools/<tool>/home` for the probe, the Test button AND the real
  ytdl call — one helper, `cli_tools.cli_env`; never the container's HOME,
  which an image update takes with it. Accepting the wizard's notice is what
  turns the feature flag on. No key, code or token is ever in
  `/api/v1/site`, a log, or an API response (masked `sk-…abcd`).
- **Client folders** (`docs/CLIENT_FOLDERS.md`, 2026-08-18): editors curate
  archive clips into a folder and hand a client a link, `/broll/share/<token>/`,
  which the dashboard's `login_gate` opens with NO session: the 128-bit token
  is the credential, `broll/web/app/routes_share.py` re-checks it and clip
  membership on every request, and nothing under it writes or names a path.
  Every asset the viewer needs is under that one prefix on purpose (its own
  `/share/assets` mount, document-relative URLs), because that prefix is what
  the operator publishes past the tailnet with Tailscale Funnel on a separate
  port. The ledger is `client_shares.db` beside `broll.db`, NOT tables in it:
  `publish_db.py` replaces `broll.db` and must never be able to take a
  customer's client links with it.
- **A sync plan belongs to a COMPUTER, not to a person** (2026-08-18,
  `docs/MULTI_MACHINE_PLAN.md`): `selections` is keyed
  `(editor_username, machine, project_slug)` -- the same `(editor, machine)`
  key `machine_state`, `editor_media_project` and the lane reports already
  use -- so one person can own two editing machines with two plans. The
  registry is `machines` (v23): hostname as the key, plus the
  companion-minted `machine_id` (`~/.ccsync/machine.json`, survives a rename)
  and that machine's Syncthing device id, which is what lets the enforce
  cycle share a folder with ONE of an editor's computers. `machine = ''` is
  the unassigned bucket, resolved in `db.selections_for_machine`, and a
  machine with a plan is never also handed it. A request with no `?machine=`
  is the PERSON: the union to read, every computer to tick, everywhere to
  untick (under-sharing is the safe direction for a removal). **Deploy the
  dashboard before the companions** -- a per-machine table read by a
  person-level enforce cycle is the B16 unshare-the-fleet shape.
- **A tick has a MODE** (`docs/UPLOAD_ONLY_TICK.md`, 2026-08-27):
  `selections.sync_mode` (v28) is `full` or `upload_only`. Upload-only is
  **lane A alone** for that project on that machine: the companion skips
  lane B and the lane C turn, and the enforce cycle never shares the
  Syncthing folder with it - "no share", deliberately NOT a `sendonly`
  folder, which would read as permanently out of sync everywhere. Every
  reader of `selections` that decides what comes DOWN must ask for
  `sync_modes=(db.SYNC_MODE_FULL,)`; a companion reading an unknown mode
  syncs the project not at all. Only video originals go up (lane A's filter
  is unchanged). Deploy the dashboard before the companions: a build older
  than 0.9.54 runs lane B for it too.
- **A file moved on the NAS by hand comes back** (`docs/FILE_MOVES.md`,
  2026-08-27): lane A never deletes, so every machine still holding the
  file at the old path re-uploads it. Move through the project page's
  `[ MOVE ON THE SERVER AND ON EVERY MACHINE ]` instead: the dashboard
  renames it (proxies with it), records it (`file_moves`, v29) and tells
  every holding machine through `commands.file_moves`; the companion moves
  its copy, relinks Resolve, keeps the old path out of lane A for a day,
  and answers in `file_moves_applied`. Nothing in that path deletes.
- **Wired or remote is the COMPUTER's own setting** (CR-88, companion
  0.9.54): `effective_mode()` reads config `mode` only, set from the tray's
  Settings window (THIS COMPUTER). The `role` the dashboard's `/verify`
  still sends is admin-derived, i.e. about the person, and is diagnostics
  only now; never make it gate sync again. The right-click menu is the
  ten-item layout in KNOWN_BUGS CR-88; everything else lives in
  `settings_window.py`, and both call the same `action_*(app)` functions.
- **A base rig can hold no tick** (CR-28): `machine_state.mode` (v22) records
  the role on the machine's own row, `db.base_only_editors` is the one
  predicate every queue source shares, and the tick itself 409s. It syncs
  nothing, so a tick could never clear -- which is how the base rig sat in
  [ QUEUED ] under a permanent GETTING READY chip.
- **An update can reach a machine without its editor clicking** (2026-08-18,
  `MULTI_MACHINE_PLAN.md` §9): Settings -> Packages has [ UPDATE NOW ] per
  out-of-date machine (`commands.upgrade` on that machine's next report, the
  channel the fleet halt already uses), and `site.toml [features]
  auto_update` (off in the vendor build) lets a companion take any NEWER
  build unattended. Neither installs anything the tray click could not: the
  command names a VERSION and the bytes come from the signed offer already in
  hand, `apply_upgrade`'s stand-down test still refuses mid-popup/consolidate,
  and auto-update never rolls a machine backwards.
- The 8899 loopback is origin-allow-listed (`loopback_guard.py`,
  2026-08-17): only the configured dashboard origin gets CORS headers, and a
  POST needs that origin or the `~/.ccsync/loopback-token` header. If
  `dashboard_url` does not match the URL editors actually browse, every
  Send-to-Resolve call 403s — the companion log names both the refused
  origin and the list it holds. `docs/LOOPBACK_API.md`.

## Running tests

Everything at once: `powershell -File tools\run_all_tests.ps1` (runs all 13
suites with the right interpreters, summary table at the end; the exit code is
the number of failed suites).

Per-component venvs; run pytest from the component dir so `python -m pytest`
puts the in-repo package first on sys.path:

```powershell
cd companion;     .venv\Scripts\python.exe -m pytest tests -q
cd dashboard;     .venv\Scripts\python.exe -m pytest tests -q
cd server;        ..\dashboard\.venv\Scripts\python.exe -m pytest tests -q   # no venv of its own; RUN IT FROM GIT BASH (see below)
cd onboarding;    python -m pytest tests -q                                  # system python
cd bench;         .venv\Scripts\python.exe -m pytest tests -q
cd broll\web;     E:\Projects\broll-platform\web\.venv\Scripts\python.exe -m pytest tests -q
cd broll\indexer; python -m pytest tests -q                                  # system python
cd music\web;     .venv\Scripts\python.exe -m pytest tests -q                # own venv, deliberately no torch
cd music\indexer; python -m pytest tests -q                                  # system python; the path/config half, torch-free on purpose
cd ytdl\web;      ..\..\dashboard\.venv\Scripts\python.exe -m pytest tests -q # no venv of its own -- the deployed reality is the dashboard's
cd tools;         ..\dashboard\.venv\Scripts\python.exe -m pytest tests -q   # stdlib-only by design; the dashboard venv has pytest + packaging
powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-DriveMapParser.ps1   # the "installer" row is FOUR scripts: this,
#   Test-LicenceGate.ps1, Test-PrevRollback.ps1 (wave 3) and Test-ConsoleUser.ps1 (wave 4, OPS-7), each run the same way
bash installer/tests/test_macos_site_values.sh                               # Git Bash; macos_bootstrap.sh's string helpers, no Mac needed
```

`broll/web` still borrows the old standalone repo's venv; `run_all_tests.ps1`
falls back to the dashboard venv when that path is absent, and the dashboard
venv can substitute by hand too.

Not pytest, but part of the gate: `dashboard\.venv\Scripts\python.exe
tools\check_licenses.py` reads every `requirements.lock` and exits 1 on
unexcused copyleft (`--strict` in CI, where every lock is installed).

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
tools\check_deploy_drift.ps1 [-AdminUser <admin>]            # read-only doctor: repo vs built vs installed vs live (also reports the package signature state)
tools\run_all_tests.ps1                                      # all 13 suites (ship only gates on server/)
```

**The Mac half cannot run from Windows** — PyInstaller does not cross-compile,
so `ship` publishes neither macOS artifact and prints an advisory instead. Both
of these run **on a Mac**, and until they do, Mac editors stay on their old build:

```bash
git pull && ./tools/release_macos.sh --publish --make-current   # macOS companion
./tools/build_onboard_macos.sh --publish --make-current         # macOS wizard (installer ≥ 1.0.17)
```

**The upgrade channel is signed (2026-08-17).** `tools\ship.cmd` signs each
package record with the offline key at `%USERPROFILE%\.ccsync-release\release.key`
(`tools/release_key.py new|pubkey|bake`); the dashboard needs
`DASH_RELEASE_PUBKEYS` set to its public half or it refuses every publish with
a 503. The public key is baked into the companion, so **an editor only trusts
keys present in the build they are already running** — rotating one costs an
overlap release (`release_key.py bake --add`, ship, then drop the old key).
`-AllowUnsignedBinary` is needed until an Authenticode certificate exists.
`.github/workflows/release-*.yml` build (never publish) on hosted runners —
the macOS runner is the answer to "PyInstaller needs a Mac"; publishing still
happens from the base rig. Secrets for the ship come from
`tools/load_secrets.ps1` (DPAPI, session-scoped), not `setx` — `docs/SECRETS.md`.

**CI builds, this rig signs, and `ship.cmd` is the studio's own dashboard**
(release-pipeline-7/-10, 2026-08-19): the vendor feed every customer reads is
published by `tools\publish_latest.py`, which takes the newest GREEN CI run on
`main` (verified with `git merge-base --is-ancestor`, because a branch label is
a claim a force-push can make untrue), signs it here with the offline key and
uploads it through `publish_feed.py`; `-Publish -MakeCurrent` from `ship.cmd`
puts a build into THIS studio's dashboard only. Refusals worth knowing before
you hit one: a version below what the channel carries (`--allow-older`), the
same version with different bytes (`--allow-replace`, and the answer is
normally a version bump), a `min_version` below the highest already published
for that kind/platform (`--allow-floor-drop`), and a `min_version` above the
build it describes, which nothing anywhere will sign (CR-52).

Full runbook, including what each version number means and how to roll back:
`docs/RELEASE.md`.

## Conventions that matter here

- **No em dashes in user-visible text** (owner's rule, 2026-08-18): tray
  lines, popup/window copy, dashboard templates and SPA strings, wizard
  steps, HTTP `detail` messages an editor reads. Use a hyphen with spaces, a
  colon, or two sentences. Comments, docstrings, docs and log lines are not
  covered. Each web/dashboard suite carries a scan test that fails on one.
- **A path a Mac reported is not `==` a path anything else reported**
  (CR-90, `docs/GOTCHAS.md` §17): macOS listdir is Unicode NFD, the NAS and
  Windows are NFC, and `Matej Šimalčík` in the two spellings is two byte
  strings. Compare through a normaliser - `db.media_rel_key`,
  `links.normalise_declared`, `resolve_bridge._nfc` - and normalise on the
  way IN for a value that is only ever compared or shown, so the SQL can
  stay an exact match. NEVER normalise a path something opens, renames or
  deletes: there the bytes on disk are the truth. rclone and Syncthing fold
  it themselves, so a mismatch shows up as a view that disagrees with a lane
  reporting zero transferred, and CJK names never warn you (no decomposed
  form).
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
  build a first-class rollback — above the machine's signed `min_version`
  floor (`~/.ccsync/upgrade_floor.json`).
- **The tray is ours (`tray_native.py`), not pystray** — ctypes on Windows,
  PyObjC on macOS, written from the OS APIs. pystray was LGPLv3 and frozen
  single-file (2026-08-17, item 3). Do not re-add it: `tools/check_licenses.py`
  fails if you do. `CCSYNC_TRAY_BACKEND=pystray` is a dev-only hatch, inert
  in a frozen build. The popup HMENU is built at right-click time and
  destroyed on close, so `icon.menu = ...` is a plain attribute assignment.
- **Legal paperwork lives in `docs/legal/`** and is DRAFT FOR COUNSEL.
  `THIRD_PARTY_NOTICES.md` is generated — edit `tools/gen_notices.py` or the
  hand-maintained block between its sentinels, never the generated half. The
  EULA's version comes from its `<!-- EULA-VERSION: -->` marker; bumping it
  pushes every editor in every fleet back through the wizard.
- **Snapshot before anything privileged and recursive.** `chown -R`, the
  deploy swap and `--recreate` all call `common.snapshot_before()` first
  (`server/setup_snapshots.py` configures the schedule;
  `docs/BACKUP_RESTORE.md` is the runbook). A search index is published with
  `server/publish_db.py --which broll|music`, never by copying over the live
  file — the container holds it open read-write in WAL mode.
- **The base rig refuses an unpinned NAS host key** (`[nas] ssh_hostkey`, or
  a one-off `--trust-host-key-on-first-use` recorded in
  `~/.ccsync/known_hosts`); a changed key is a refusal, never a re-trust. The
  dashboard container should hold `TRUENAS_API_KEY` (`server/create_api_key.py`),
  not the admin password. `[stack] editor_shell` and `[net] shell_type` are
  not independent — sftp-only forces `sftp_shell_type=none` into the manifest
  (`docs/TENANCY.md`).
- Dashboard secrets are checked at BOOT: `DASH_SESSION_SECRET` and
  `DASH_REPORT_TOKEN` go through `broll.check_ingest_token` (>= 24 chars, no
  placeholder) and a weak one refuses to start. `DASH_DEV_INSECURE=1` is the
  ONE test/dev bypass — `dashboard/tests/conftest.py` sets it at import time;
  it must never be set on a deployment. Fleet credentials come in two shapes:
  the shared `DASH_REPORT_TOKEN` (migration only) and per-editor `cce1.…`
  tokens that BIND to an identity. No dashboard call follows a redirect —
  stub the *opener* in tests, never `urlopen`. `docs/GOTCHAS.md` §12. ONE
  carve-out since 2026-08-18: `release_feed.py`'s vendor-feed fetch follows
  up to 5 hops, https-only, because GitHub Releases 302 to
  `release-assets.githubusercontent.com`. It is safe *there* because no
  credential is on the wire and every byte is signature/sha-verified after
  the fact — neither is true of any other call, so it is not precedent.
- Lane B can STOP ITSELF: `sync/lane_guard.py`'s circuit breaker parks proxy
  download in `paused` (never `error`) whenever the NAS stops looking like
  the tree or a pass trashes too much; lanes A and C keep running, and only a
  human clears it — the editor at the tray, or an admin at Dashboard → FLEET
  → [ RESUME ] (CR-45, companion 0.9.43+, delivered in the same `commands`
  block as the halt and the pushed update). A pass that is about to trip
  first asks whether the files were MOVED rather than deleted, by re-listing
  the scope and matching basename + exact size (CR-44); that probe is lazy,
  and every failure in it falls back to "treat them as deletions". Before
  "lane B isn't downloading", check `~/.ccsync/state/lane_b_breaker.json`,
  the tray line, or the grid chip. Same for `sync_halt.json`. Never make a
  safety latch in-memory-only. `docs/SYNC_SAFETY.md`.
- **An external sync drive pulled mid-transfer gets a warning that names what
  is owed, then a reminder every half hour until it is back** (CR-92,
  companion 0.9.55, `drive_reminder.py`): the verdict is
  `PendingTracker.live_busy()` - the power guards' liveness bound, never
  `busy_lanes()` - so a lane stuck in `syncing` (CR-91) earns no reminder;
  the episode lives in `~/.ccsync/state/drive_unfinished.json` across
  restarts and only the drive coming back clears it. `drive_reminder_minutes`
  (0 = first warning only). A drive pulled with nothing owed keeps the one
  calm "Sync paused" balloon.
- **The server diagnoses itself, and an unverified check is NOT CHECKED, never
  OK** (wave 4 of the resilience sweep, 2026-08-28, `docs/SELF_DIAGNOSIS.md`):
  a diagnosis the collector used to `log.error` into a log nobody opens goes
  into `notices` (v37, keyed `(kind, subject)`, every row carrying the exact
  next action) and shows on the home page as PROBLEMS THE SERVER FOUND; forty
  alert kinds in `alerts.ALERT_KINDS` (data, not a chain of ifs) are evaluated
  every collector cycle from state the dashboard already holds, logged
  (`alert_log`, v38) and delivered through `alerts_sink` (none in the vendor
  build / smtp / https webhook), with a Monday weekly report. Adding a check
  is adding a registry row. A check that raises is its own `check_failed`
  finding; a kind nothing evaluates renders `[ NOT CHECKED ]` on the checks
  panel (evidence in `NOTICE_CHECKS_META`). Register a notice kind WITH its
  writer - a registered kind with no writer was the first build's own bug.
  Nothing here formats a secret; the smtp password lives in
  `<data>/secrets/alerts/smtp_password`.
- **A fleet halt expires** (24 h default, `[ KEEP HALTED ]` extends, history in
  `meta.fleet_halt_history`) and a package delete goes to
  `<data>/packages/.trash/` for 30 days through ONE helper
  (`api._trash_package_file`, both routes). A file move is two-phase (v36):
  the companion answers `retrying` and is re-sent the command until done or
  blocked, so deploy the dashboard BEFORE companion 0.9.55 or the retry
  never happens (`docs/FILE_MOVES.md`).
- **A Tk root must be freed on the thread that built it** (CR-93,
  2026-08-29, `docs/GOTCHAS.md` section 18). `_tkinter` deletes the Tcl
  interpreter in `Tkapp_Dealloc`, inline, on whatever thread drops the last
  reference; from any other thread Tcl answers `Tcl_Panic` - `abort()`, no
  traceback, no `finally`, nothing in the log, the whole tray gone (seven
  silent deaths on the base rig before the Event Log was read). Every
  dialog here still builds its root on the thread that wanted it, so a
  window that keeps widgets in ATTRIBUTES must clear them and end its root
  with `ui_dispatch.release_root()`, which parks a still-held interpreter
  instead of letting another thread free it and NAMES the holder in the
  log. Widgets that are frame locals need none of this. A `StringVar`, a
  `ttk.Style` and a `PhotoImage` count as widgets. Since the same commit a
  death nobody asked for is no longer silent: `crash_report.install_native`
  (faulthandler + a run marker cleared at the top of `shutdown()`) turns it
  into an `UncleanExit` crash file on the next start.
- **Never call `scriptapp("Resolve")` outside `resolve_bridge.connect()`**
  (CR-68, 2026-08-21). Resolve's script server (`fuscript.exe`, TCP 1144)
  exits when its last client leaves, and a client that connects before
  Resolve has registered with it kills scripting for that whole Resolve
  session, for every client on the machine - the "close Resolve, close the
  companion, reopen both in order" dance. `connect()` asks
  `script_server.state()` (TCP table, no connection, fail-open) first and
  holds off during the launch window. `docs/GOTCHAS.md` §15 has the
  drop-in guard for other Resolve clients on the same machine.
- Every media-pool write goes through `resolve_bridge.replace_clip` /
  `link_proxy_media`, which take a `SaveProject`+export save point and write an
  undo journal under `~/.ccsync/resolve_edits` — add new Resolve mutations
  *through those two functions*. The companion suite's `_no_live_resolve`
  conftest fixture exists because that save point calls `connect()`.
- Both indexers require their paths (`BROLL_DATA_ROOT`, `BROLL_DB_PATH`,
  `CCSYNC_WHISPER_*`, `MUSIC_DB_PATH`, …); every refusal names the key. Never
  push a drained `music.db` back over the live one — `--export-drain` then
  `python -m musicweb.drain apply`. `docs/INDEXERS.md`.
- Every component carries a hash-pinned `requirements.lock`; bump the floor
  in `pyproject.toml`/`requirements.txt` first, then regenerate
  (`docs/RELEASE.md`, "Refreshing the lockfiles"). A new dependency must clear
  `tools/check_licenses.py`. CI is `.github/workflows/ci.yml` (`docs/CI.md`).
