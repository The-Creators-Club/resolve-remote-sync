# GOTCHAS.md -- things that will waste your afternoon

Every entry here cost real debugging time at least once. They are written as
**symptom first**, because that is what you have when you arrive: an error
message, not a diagnosis.

If something "doesn't work" and you are about to start reading code, spend
thirty seconds here first. Several of these produce errors that name a line
that is perfectly correct.

Related: [RELEASE.md](RELEASE.md) is the shipping runbook,
[SERVER.md](SERVER.md) the NAS/dashboard operations manual.

---

## 0. The meta-gotcha: you are probably not running the code you are reading

**Three separate incidents have started this way.** The repo is not the
companion on your machine, not the exe on the share, not the container on the
NAS, and not the build the fleet self-upgrades to. Those are five different
things and they drift independently.

```powershell
.\tools\check_deploy_drift.ps1
```

Run it **before** debugging, not after. On 2026-07-25 three rounds of
companion fixes were written and "verified" against a repo at v0.4.5 while
the machine ran v0.4.3. Nothing was wrong with any of the fixes.

The exit code says only that the check ran. Drift is reported on the VERDICT
line, not in the status.

---

## 1. Line endings

### `set: Illegal option -` from a shell script that is obviously fine

```
/app/deploy/run.sh: 6: set: Illegal option -
```

Line 6 is `set -eu`, which is valid POSIX. The illegal option is an invisible
carriage return. The tell is a **blank line after every error**: the CR sends
the cursor back to column 0.

**Cause.** `core.autocrlf=true` (normal on Windows) rewrites LF to CRLF on
*checkout*. `dashboard/deploy/run.sh` is executed as `/bin/sh
/app/deploy/run.sh` inside `python:3.12-slim`, where `/bin/sh` is dash, and
dash reads the trailing `\r` as an option character. The container
restart-loops and the dashboard is down.

**Why it is invisible.** The index holds LF. `git status` stays clean and
`git diff` shows nothing, because the corruption happens on the way *out* of
git, not on the way in. It reappears on every fresh clone and every branch
switch. Normalising the working file and committing produces "1 file changed"
that does not include the file you just fixed.

**Fix.** `.gitattributes` pins `eol=lf` for `*.sh` and `*.bash` (and
`eol=crlf` for `*.ps1`, which is what Windows editors expect). Verify with:

```powershell
git check-attr eol -- dashboard/deploy/run.sh
```

**Add any new POSIX-executed file to `.gitattributes`.** On 2026-07-26 both
`dashboard/deploy/run.sh` and `installer/macos_bootstrap.sh` had this defect,
and the second was already on the editor share, where the first Mac install
would have failed identically.

The blanket `*.sh text eol=lf` rule covers new files, but every shell script
that leaves this machine is **also** listed by name, deliberately: a
one-line diff is the only thing that makes "is this file safe on a Mac?"
reviewable. `installer/macos_uninstall.sh` and `tools/release_macos.sh` were
added on 2026-08-03. `build_editor_package.ps1 -Publish` now refuses to
publish `macos_bootstrap.sh` at all if a byte-scan finds a CR in it -- the
`.sh` is served to Macs by the dashboard's `[ INSTALLER ]` link, where a
single CR makes it fail on the first line (`bad interpreter: bash^M`).

Audit the whole tree at once:

```powershell
Get-ChildItem -Recurse -Include *.sh -File |
  Where-Object { $_.FullName -notmatch '\\\.venv\\' } |
  ForEach-Object {
    $b = [IO.File]::ReadAllBytes($_.FullName); $c = 0
    for ($i=1; $i -lt $b.Length; $i++) { if ($b[$i] -eq 10 -and $b[$i-1] -eq 13) { $c++ } }
    "{0,-45} CRLF={1}" -f $_.Name, $c
  }
```

---

## 2. PowerShell 5.1

### A script that succeeded exits non-zero

A clean `check_deploy_drift.ps1` run exited **128**; `release.ps1` exited
**255**. Neither had failed.

**Cause.** With no explicit `exit`, PowerShell returns whatever the last
native command left behind. The last one is usually `git` or `pytest`.

**Fix.** End every script that is used as a gate with an explicit `exit 0`.
Both scripts now do.

### `NativeCommandError` on a command that worked

```
+ CategoryInfo : NotSpecified: (WARNING: accept...:String) [], RemoteException
+ FullyQualifiedErrorId : NativeCommandError
```

**Cause.** Redirecting a native executable's stderr with `2>&1` inside
PowerShell 5.1 wraps each stderr line in an ErrorRecord and sets `$?` to
`$false` even on exit code 0. Any tool that writes an advisory to stderr (ssh
host-key warnings, pip, pytest) triggers it.

**Fix.** Do not add `2>&1` to native commands. stderr is captured anyway.

### `git commit -m` with a here-string fails with `pathspec ... did not match`

```
error: pathspec 'is' did not match any file(s) known to git
```

**Cause.** Embedded **double quotes** inside the message break PowerShell
5.1's native-argument re-quoting, and the message is split on whitespace into
pathspecs.

**Fix.** Write the message to a file and use `git commit -F <file>`. Or keep
double quotes out of commit messages entirely.

### Other 5.1 traps

- No `&&` / `||` chaining. Use `A; if ($?) { B }`.
- No ternary, `??`, or `?.`.
- `Set-Content` / `Add-Content` default to ANSI. Pass `-Encoding utf8` for
  anything another tool will read.
- Closing `'@` of a here-string must be at **column 0**. Indenting it is a
  parse error.

---

## 3. Running these scripts from an agent or a fresh shell

### `running scripts is disabled on this system`

A new PowerShell window has no execution-policy bypass:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

`-Scope Process` lasts only for that window and changes nothing permanently.

### `Read-Host` prompts cannot be automated

`build_editor_package.ps1 -Publish` and `check_deploy_drift.ps1 -AdminUser`
both call `Read-Host -AsSecureString`. Non-interactive shells have stdin on
the null device and get EOF; piping through Bash does not help either. **Run
those two in a real console window.**

### Environment variables do not survive between agent tool calls

Shell state (variables, functions) is discarded between invocations; only the
working directory persists. Setting `$env:FOO` in one call and running the
script in the next means the script sees **nothing**.

This is not cosmetic. On 2026-07-26 it made `install_dashboard_app.py` fall
back to the default `DASH_ADMIN_USERS=truenas_admin`, which would have
dropped `alex` from the dashboard admin list and with it the ability to
publish packages at all. Caught only because `--dry-run` prints the compose
body.

**Fix.** Set the variables and run the command in **one** invocation, and
always `--dry-run` first and read the values back.

---

## 4. Deploying the dashboard

### A change appears to do nothing at all

**Cause.** A plain re-run of `install_dashboard_app.py` uploads code and
restarts the container **with the old compose**. Everything compose-level is
baked in at create time: bind addresses, image tag, mounts, ports,
healthcheck, and every environment variable.

**Fix.** `--recreate`. The script prints a reminder after a plain re-run;
believe it.

### `--recreate` silently deploys default secrets

`--recreate` rebuilds the compose environment from scratch and **does not
read the current values back off the running app**. Anything you omit is
silently replaced by its default:

| Variable | Omitting it costs you |
|---|---|
| `DASH_SESSION_SECRET` | every editor logged out of the dashboard |
| `DASH_REPORT_TOKEN` | every companion stops reporting |
| `DASH_ADMIN_USERS` | defaults to `truenas_admin`, so real admins lose admin |
| `SYNCTHING_GUI_URL` | collector points at the wrong Syncthing |

**Read the deployed values first** rather than reconstructing them:

```
POST https://<nas>/api/v2.0/app/config   body: "ccsync-dashboard"
```

returns `services.dashboard.environment` with everything the running app
actually has. `DASH_REPORT_TOKEN` should equal `dashboard_token` in each
editor's `~/.ccsync/config.toml`; verify that before you deploy.

### The container starts but nothing answers on 8480

Check the app state and the container log. Both need sudo:

```
GET https://<nas>/api/v2.0/app/id/ccsync-dashboard        -> state
echo "$SUDO_PW" | sudo -S docker ps -a --filter name=ccsync
echo "$SUDO_PW" | sudo -S docker logs --tail 150 <container>
```

`state: STOPPED` with `containers: 0` in the API while `docker ps -a` shows
`Restarting (2)` means the entrypoint is crash-looping. See section 1.

### `/api/v1/health` lost most of its fields

Not a regression. Since dashboard v0.2.0 the unauthenticated response is
trimmed to `{"ok", "version"}`, because that route is open for the Docker
healthcheck and the full body carries project slugs, labels and Syncthing
error strings. Send `X-CCSync-Token` (or a session cookie) for the detail.

---

## 5. The upgrade channel and the fleet

### "Update available" offers an **older** version

By design. The channel advertises *different*, not *newer*, so that a
rollback reaches the fleet like any other update. The tray wording
distinguishes them:

- **"Update available -> vX.Y.Z (install)"** when newer
- **"Roll back to vX.Y.Z (older -- install)"** when older
- **"Switch to vX.Y.Z (install)"** when they cannot be ranked

If your own machine is being offered a downgrade, the channel's current
package is older than your build. Publish.

### Publishing returns 409

That version is already published. Bump `VERSION` in **both**
`companion/src/ccsync_companion/config.py` and `companion/pyproject.toml`. A
rebuild without a bump cannot reach the fleet.

Versions must match `^\d+\.\d+\.\d+$` exactly. No `0.4.5-dev`, no `0.4.5rc1`.

### Nothing is pushed, ever

"The fleet is upgraded" means **each editor clicked the tray item**. Watch
who has not.

Two machines will never get there on their own:

- **Pre-0.4.0 companions** predate the self-upgrade mechanism. They need the
  manual path: `windows_upgrade.ps1` from the share, per
  `installer/FIRST_UPGRADE.md`.
- **Mac editors** are offered only what the **macOS** channel carries, which
  a Windows ship never updates (PyInstaller does not cross-compile -- see
  RELEASE.md, "The macOS release"). Between Mac build sessions they keep
  their build and are correctly *not* flagged out of date; the advisory
  printed by `ship.ps1` / `build_editor_package.ps1` /
  `check_deploy_drift.ps1` is the reminder to run
  `./tools/release_macos.sh --publish --make-current` on the Mac.

### Ordering: companion before dashboard

The dashboard requires `X-CCSync-Identity` on selection reads
(`api.py:_require_selection_read`), and only companions >= 0.4.5 send it. An
older companion gets a 401 and **falls back silently to its cached
selection**, so it keeps working from a stale project list until it upgrades.
Publish the companion first, then deploy the dashboard.

A signed-out companion has no identity token either, so the same fallback
applies until the editor signs in from the tray.

---

## 6. Building

### "THE EXE IS STALE" immediately after a successful build

The staleness check compares **mtimes**, and `git checkout` / `git merge`
rewrites the mtime of every file it touches without changing a byte. A branch
switch therefore makes a perfectly current exe look stale.

**Do not rebuild reflexively, and never touch mtimes to silence it.** Check
content instead: the manifest's `git_commit` against `HEAD`, plus a clean
tree.

```powershell
Get-Content companion\dist\ccsync-release.json | ConvertFrom-Json |
  Select-Object version, git_commit, git_dirty
git rev-parse --short HEAD
git status --porcelain
```

If the manifest commit equals HEAD and the tree is clean, the exe is built
from exactly that source and the warning is an artifact.

On the `-Publish` path the same check is a **hard refusal**, not a warning.
There the honest fix is a real rebuild via `tools/release.ps1`.

### Rebuild order: companion, then onboard

`onboard.exe` **bundles** `ccsync-companion.exe`, `onboarding/*.py` and
`installer/windows_bootstrap.ps1`. Rebuilding the companion after onboard
leaves a package whose installer ships the previous companion. Shipping a
stale `onboard.exe` is exactly how the 2026-07-25 rollout handed a new editor
an old build.

Order: `tools\release.ps1` (companion) then
`build_editor_package.ps1 -RebuildOnboard`.

PyInstaller is not reproducible: an identical rebuild produces a different
sha256. Rebuilding to silence a cosmetic warning puts your installed exe out
of step with the published one for no gain.

---

## 7. Talking to the NAS

- **Docker needs sudo.** Without it: `permission denied while trying to
  connect to the Docker daemon socket`. Wrap as
  `echo "$SUDO_PW" | sudo -S sh -c '...'`.
- **`common.run_ssh` returns `(rc, stdout, stderr)`**, a 3-tuple. Treating
  the return value as a string yields the exit code and looks like empty
  output.
- **`truenas_admin` is not a dashboard login.** `/api/v1/login`
  authenticates against SMB accounts; the NAS admin account is not one, even
  though it is listed in `DASH_ADMIN_USERS`. Its password works for the
  TrueNAS API and SSH, not for the dashboard UI.
- **The SSH host key is unpinned** by default, and every call prints a
  first-use-trust warning. Pin it:

  ```
  CCSYNC_SSH_HOSTKEY="$(ssh-keyscan -t ed25519 192.168.0.102 | awk '{print $2, $3}')"
  ```

- **DaVinci Resolve holds its attached proxy files open without
  share-delete**, so lane B's move-to-trash of superseded proxies fails
  with a lock error and retries every pass -- the tray says "tidying old
  files in slices" indefinitely and the machine's manifest over-counts
  proxies (99/69 on alex_laptop, 2026-07-26) until Resolve is closed once
  and the sweep completes.

- **rclone silently rewrites fullwidth punctuation in filenames on
  Windows.** Its default local encoding maps forbidden characters to
  fullwidth forms (`?` -> `？`) and QUOTES a name that already contains a
  fullwidth form by prefixing U+201B (`‛`). yt-dlp titles are full of
  legitimate fullwidth punctuation, so lane B delivered proxies whose
  basenames no longer matched their Resolve clips -- 29 of 68 proxies on
  one editor's machine could never relink (2026-07-26, proven by
  downloading one file and watching the `‛` appear). The reverse applied
  on lane A: a local `？` uploaded as a raw `?`. Fixed by pinning
  `--local-encoding` without the punctuation mappings on every transfer
  command (rclone_lane.LOCAL_ENCODING). If a proxy-vs-source name ever
  mismatches by exactly one `‛`, suspect a companion predating v0.4.8 --
  and do NOT hand-rename the local file: pre-fix rclone treats the
  corrected name as a different file and re-downloads the `‛` version.

  **Still seen on a pinned companion (2026-08-14, ruskin's box, v0.7.4.)**
  Lane A flapped `error` on Creator Profiles/Season 1 with
  `failed to open source object: ...Satu‛‛： Piloting...: The system cannot
  find the file specified` -- a DOUBLY escaped name that exists on no disk,
  which only an rclone run WITHOUT the pin can produce. Every builder
  (`build_up_command`, `build_express_command`, `build_down_command`)
  carries it via `_transport_flags()`, and hand-running the same argv with
  the pin succeeds, so the offending invocation was never identified.
  Diagnose it in one read-only command pair -- diff the names from
  `rclone lsl <dir> --local-encoding <LOCAL_ENCODING>` against plain
  `rclone lsl <dir>`: on that project 628 of 2507 entries differed, i.e. a
  quarter of the tree resolves to two different names depending on one flag.
  Belt and braces, applied on that machine: set the USER env var
  `RCLONE_LOCAL_ENCODING` to the same value as LOCAL_ENCODING. rclone reads
  it for the implicit local backend, so it covers every invocation whatever
  its argv, and an explicit `--local-encoding` still wins where one is
  passed. It is inherited from the environment the companion was started
  in, so the companion must be restarted (or the user logged back in)
  before it takes effect.

- **A Syncthing that connects and drops after exactly ~1 second is a
  device-list problem, not a network problem.** NAS-side log signature:
  `Established secure connection` then `Lost device connection ...
  error="reading length: EOF"` one second later, forever. TLS succeeding
  means the certificate (device ID) is right; the EOF means the OTHER side
  read the hello and hung up because the dialing device is not in its own
  config -- a fresh `syncthing generate` config knows nobody
  (alex_laptop, 2026-07-26). The bootstraps now seed the NAS device via
  REST; if it recurs, also check for TWO syncthing.exe processes from
  different homes (`Get-Process syncthing | Select-Object Id, Path`).
- **An editor machine can run Syncthing from a different home than the
  ccsync-managed one** (`%LOCALAPPDATA%\ccsync\syncthing-config`). The
  companion used to statically prefer the managed home's API key, so every
  REST call 403'd against the veteran instance: lane C reported a
  misleading error AND every sequencer write (ignores, versioning, folder
  policy) was silently dead -- the folder then indexes the 30 GiB of media
  lanes A/B own. The companion now tries every known home's key against
  the live instance; the lane error text distinguishes "not running" from
  "running but rejected every known API key".

---

## 8. Tests that depend on your desktop

Three autouse fixtures in `companion/tests/conftest.py` exist because the
suite's result depended on the state of the developer's own machine. All
three were added on 2026-07-25 after real incidents.

| Guard | Without it |
|---|---|
| `_isolate_ccsync_home` | Tests read the developer's live `identity.json` (a signed-in `role="base"` identity flips `_sync_enabled`), and `setup_logging()` appends test tracebacks to the real `~/.ccsync/companion.log` -- the one artifact the docs tell editors to send in. |
| `_no_real_tk_windows` | A test opens a **real dialog on the desktop** and blocks its thread. One popped the exact "NEW PROJECT / New Doc" dialog the suite was written to prevent, and was mistaken for the live bug for a day. |
| `_single_instance_slot_is_free` | The named Windows mutex is global to the login session, so a **running companion** makes `run()` return early and construction-order tests fail with `'construct' is not in list`. The suite was green all afternoon only because the companion happened to be stopped. |

The lesson generalises: if a test's outcome can depend on whether a real
process is running or a real file exists, it needs a guard, not a fix at the
call site.

Also: tests marked `needs_bash` require a POSIX shell and **skip** under
PowerShell. A count of "97 passed, 12 skipped" on Windows and "108 passed, 1
skipped" under Git Bash are the same run.

### The same suite, three different answers, depending on where you launched it

`server/tests` executes the *generated remote scripts* under a stub `sudo` and
`chown` (`run_remote_script`). Measured on 2026-08-10, same code, same
interpreter, same machine:

| launched from | result |
|---|---|
| Git Bash | `214 passed, 1 skipped` — the truth |
| PowerShell, no `bash` on PATH | `197 passed, 18 skipped` — the shell-level half never ran |
| PowerShell, `bash` on PATH | **`5 failed`, 210 passed** — false failures |

The middle row is the ordinary skip. The last one is the trap: the harness
prepends its stub directory using `os.pathsep`, which is `;` on Windows, and
the bash that inherits that Windows-style `PATH` resolves `chown` to MSYS's
real one instead of the stub — so three swap-script tests and two music-deploy
tests die on `chown: invalid user: 'root:root'` and look like real regressions
in code that is fine.

Fix is where pytest runs, not what is on `PATH`: launch it *inside* the shell
(`bash -lc "cd server && …/python.exe -m pytest tests -q"`). `tools\ship.ps1`
does exactly that in step 0, pinning **Git's** `bash.exe` (derived from
`git.exe`, `Git\cmd` → `Git\bin`) rather than whatever `bash` resolves to —
on a machine with WSL that is `System32\bash.exe`, whose filesystem view makes
every path in the command wrong.

---

## 9. Quick reference

```powershell
.\tools\check_deploy_drift.ps1                    # what is ACTUALLY running, everywhere
.\tools\release.ps1                               # parity + tests + build + manifest
.\installer\build_editor_package.ps1 -RebuildOnboard          # refresh the share only
.\installer\build_editor_package.ps1 -Publish -MakeCurrent    # ship to the fleet (real console)
.\installer\windows_upgrade.ps1 -CompanionExe <path>          # install here
python server\install_dashboard_app.py --recreate --dry-run   # ALWAYS dry-run first
git check-attr eol -- <file>                      # is this file going to break on POSIX
Set-ExecutionPolicy -Scope Process Bypass         # fresh window
```

---

## 10. macOS

Nothing in this section has been paid for in debugging time **yet** -- the
macOS port is code-complete and unvalidated (`installer/MACOS_FIRST_RUN.md`).
These are the traps the implementation is written around, recorded here so
the first real Mac session recognises them instead of rediscovering them.

### Resolve's Mapped Mount is TWO files, and `config.dat` alone does nothing

Resolve keeps the preference in both:

| File | Shape | Whose form |
|---|---|---|
| `config.dat` | `Site.<n>.FS.<i>.Root` / `.MappedRoot` | the engine's mirror |
| `.config.data` | `IoFsMount_<i>` / `IoFsMappedMount_<i>` + `IoFsNum` | the GUI's own form |

Both live in `~/Library/Preferences/Blackmagic Design/DaVinci Resolve/`
(**no** `Preferences` subfolder, unlike Windows). Editing `config.dat` alone
looks like it worked and then silently reverts, because the GUI form is what
Resolve rebuilds `config.dat` from on the next launch. The installer's helper
edits both or neither.

### Resolve rewrites its preferences ON QUIT -- and never pre-create them

Two consequences, and the helper refuses rather than guessing on either:

- **Resolve running → exit 3.** An edit made while Resolve is open is
  overwritten when it quits. Quit Resolve, re-run
  `macos_bootstrap.sh --resolve-mapping-only`.
- **No `config.dat` at all → exit 4, nothing created.** A missing file means
  Resolve has never completed a first run, and first-run onboarding
  regenerates the whole config -- so a preference file invented by an
  installer would be thrown away along with everything else in it. "Launch
  Resolve once, quit, re-run" is the fix, not a workaround.

Other exit codes worth knowing: `5` unrecognised format (nothing touched),
`6`/`7` from `verify` only (no mapping / mapped elsewhere), `8` I/O.

### `MacDIO`, not `DIO`

The direct-IO key in `config.dat` is platform-specific and Resolve ignores
the wrong one. New entries the helper writes on macOS carry `MacDIO = 1`;
`DIO = 1` is the Windows spelling. Same idea in `.config.data`, where the
field is `IoFsDirectIO_<i>`.

Also: Resolve appends its own trailing filesystem entry (`/Volumes` on
macOS, `ResolveVirtual` on Windows) and expects it **last**, so the helper
inserts in front of it — in **both** `config.dat` and `.config.data`. That
symmetry is newer than it looks: `insert_position()` was a `ConfigDat`-only
override until 2026-08-04, so `.config.data` appended *after* its `/Volumes`
entry while `config.dat` inserted before, and the two files disagreed about
the order of the same mapping. The first real Mac hid it — its `.config.data`
had no `/Volumes` entry at all, which is a legitimate shape and still just
appends.

### The Mac App Store build keeps its preferences somewhere else

If Resolve came from the App Store, the config directory is inside its
container:

```
~/Library/Containers/com.blackmagic-design.DaVinciResolve/Data/Library/Preferences/Blackmagic Design/DaVinci Resolve
```

The helper checks the normal location first and the container second,
choosing whichever actually holds a `config.dat`; `BMD_RESOLVE_CONFIG_DIR`
overrides both (and is used as-is, so an override with no `config.dat`
reports "never launched" rather than silently falling back to a different
profile).

### Quarantine is set by browsers, not by `curl`

`com.apple.quarantine` comes from the *downloader*, not from the file:

| How it arrived | Quarantined? |
|---|---|
| Safari/Chrome (the dashboard's `[ INSTALLER ]` link) | **yes** |
| `curl` / `urllib` (the bootstrap's companion download, the tray self-upgrade) | no |
| copied off a share, `scp`, AirDrop from a trusted device | no |

Quarantine blocks **executing** the file. So a browser-downloaded
`ccsync-onboard-*.sh` needs `xattr -d com.apple.quarantine <file>` *or* to be
run as `bash <file>` -- passing it to `bash` as an argument is not an
execution of the file and is unaffected. The bootstrap strips the attribute
from the companion binary anyway, belt and braces, because **a quarantined
binary launched by launchd fails with no dialog and no log line at all** --
the symptom is a LaunchAgent that appears to load and a menu bar with
nothing in it.

### `/Volumes` ghost directories and numbered remounts

An unclean eject leaves an empty **directory** at `/Volumes/<Name>` on the
boot disk. `os.path.isdir()` and `[ -d ]` both say yes to it, which is why
neither is ever the only check in this codebase: `rclone sync <NAS>
<local_root>` against that path does not fail, it fills the Mac's internal
disk with the project that was supposed to be on the SSD.

With the ghost in place, the real drive then mounts at `/Volumes/<Name> 1` --
a name that **changes between replugs** and must never be adopted as a sync
root or baked into Resolve's Mapped Mount.

Both are refused, never adapted to: the installer aborts with the fix, and
the companion's `root_guard.py` classifies a ghost as `absent` (pause, wait)
and a numbered remount as `misplaced` (pause, and show the editor a dialog).
`misplaced` is only distinguishable when a `VolumeUUID` was recorded in
`~/.ccsync/volume.json` at install time; without one it degrades to
`absent`, which says the same thing with less detail.

Diagnosing by hand: `ls /Volumes` shows the name either way; `mount` lists
only real mounts. Present in `ls` and absent from `mount` = ghost. The fix is
always eject → `sudo rmdir "/Volumes/<Name>"` (rmdir, **not** `rm -rf`: it
refuses if anything real is in there) → replug.

### launchd gives the companion a minimal PATH

A LaunchAgent job inherits `PATH=/usr/bin:/bin:/usr/sbin:/sbin`. Neither
`/opt/homebrew/bin` nor `~/.local/ccsync/bin` is on it, so
`shutil.which("rclone")` fails and lanes A/B report "rclone not found on
PATH" forever, on a machine where `rclone` works fine in Terminal (INST-7).
The bootstrap therefore seeds `rclone_path` in `config.toml` with an
**absolute** path. Anything else the companion shells out to needs the same
treatment.

### The companion's LaunchAgent has no `KeepAlive`, and does have `AbandonProcessGroup`

Both are load-bearing and both look like omissions:

- **No `KeepAlive`.** The companion self-upgrades by replacing its own
  binary and re-execing. With `KeepAlive`, launchd *also* restarts the
  process it just saw exit, and the Mac ends up running two companions
  fighting over the single-instance lock and the sync queue.
- **`AbandonProcessGroup = true`.** Without it launchd kills the whole
  process group when the main process exits -- taking the freshly re-execed
  upgrade child with it, i.e. an upgrade that removes the companion.

The plist is rewritten (after a `launchctl bootout`) whenever it points at
the wrong program or is missing either property. It runs the binary
directly: there is no `.app` and no `open -a` indirection, so launchd
supervises the real process.


---

## 11. Making proxies with ffmpeg

Added 2026-08-10 with the companion proxy generator (`proxy_gen.py`). Both
of these are cheap to get wrong and expensive to notice.

### `GetLastInputInfo` is 32-bit, and so must the subtraction be

The idle probe the generator gates on (`idle.py`) compares
`GetLastInputInfo().dwTime` against `GetTickCount`. Both are **DWORDs
sampled from the same 32-bit millisecond counter**, which rolls over every
49.7 days. On the days either side of a rollover a plain `now - last` is
either a negative number (harmless: reads as "not idle") or a ~49-day idle
time (**not** harmless: it says nobody has touched the machine for seven
weeks while somebody is typing on it, and the generator starts encoding
under their hands). `_elapsed_ms` does the subtraction modulo 2^32, which
is right on both sides.

Two traps in the same place: do **not** "fix" this by reading
`GetTickCount64` -- mixing a 64-bit now with a 32-bit last reintroduces the
bug in a form that only appears after 49.7 days of uptime. And bind the
ctypes prototypes explicitly (`restype = wintypes.DWORD`): ctypes defaults
to `c_int`, which sign-extends anything past 0x7FFFFFFF into a negative
number -- the same bug, 24.9 days in.

Also worth knowing before trusting an idle number: it is **per session**
(a second logged-in user, or an RDP session, keeps its own input timer), and
it cannot see an unattended Resolve render -- that machine looks perfectly
idle. `proxy_gen_skip_while_resolve_running = true` is the escape hatch;
no input-based probe can answer it.

### HEVC in MP4 needs `-tag:v hvc1`, or the proxy plays everywhere except Resolve

ffmpeg tags HEVC-in-MP4 as `hev1` by default. QuickTime and DaVinci Resolve
both refuse that tag; VLC plays it happily. So a proxy written without
`-tag:v hvc1` looks perfect when you double-click it to check, and shows
**Media Offline** in the one application it exists for. `own_proxy_cmd`
always passes it.

Its neighbour in the same argv is not decoration either: `-map_metadata 0`
plus an explicit `-timecode` from ffprobe. Resolve's `LinkProxyMedia`
refuses a proxy whose timecode does not match the original
(`proxy_relink.py:35-37`), and an mp4 written without one starts at
00:00:00:00 -- i.e. every generated proxy would be rejected, silently, by
the relinker that is supposed to attach it. A source with no timecode gets
no `-timecode` flag at all: writing a zero onto it is a mismatch of its own.
