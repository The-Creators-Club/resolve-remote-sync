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

### A byte-parity gate fails on a file nobody edited

Added 2026-08-18. Several modules exist twice on purpose, vendored verbatim
because the two consumers cannot import each other: `broll_vlm` in the
companion against `broll_index`, `ytdl_common.py` and the three `identity.py`
copies, `normalize.py` in `broll/web`. `tools/release.ps1` and
`server/tests/test_cross_component.py` compare each pair **byte for byte**, so
a working copy where one half is CRLF and the other is LF is reported as drift
in code that is identical. Nothing in the diff explains it, because the index
holds LF for both.

Every pair is now pinned `text eol=lf` in `.gitattributes`. The catch is the
one from the top of this section: **a working copy checked out before a rule
was added keeps its CRLF** until the file is re-checked-out
(`rm <file>` then `git checkout -- <file>`). Confirm with `git ls-files --eol`,
which reports the index and the working tree separately, rather than with grep,
which strips CRs before matching.

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
dropped the operator's own account from the dashboard admin list and with it
the ability to publish packages at all. Caught only because `--dry-run` prints the compose
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
  CCSYNC_SSH_HOSTKEY="$(ssh-keyscan -t ed25519 <nas> | awk '{print $2, $3}')"
  ```

- **DaVinci Resolve holds its attached proxy files open without
  share-delete**, so lane B's move-to-trash of superseded proxies fails
  with a lock error and retries every pass -- the tray says "tidying old
  files in slices" indefinitely and the machine's manifest over-counts
  proxies (99/69 on owen_laptop, 2026-07-26) until Resolve is closed once
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

  **Still seen on a pinned companion (2026-08-14, an editor's box, v0.7.4.)**
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
  (owen_laptop, 2026-07-26). The bootstraps now seed the NAS device via
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

**It happened again on 2026-08-18**, with a new window: a companion suite run
left a real "MAKING PROXIES" `WorkProgressWindow` on the operator's desktop.
`_no_real_tk_windows` is autouse, so the only ways past it are constructing a
window outside the fixture's reach or running the file with an interpreter
that never loaded `companion/tests/conftest.py` (a bare `python -m pytest
some_test.py` from the repo root does exactly that). Any new test that touches
`popup.py` goes through the conftest pattern, and a window on your desktop
after a test run is a bug in the test, never in the app.

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

### `-progress`: `out_time_ms` is microseconds, and an unread pipe hangs the encode

Added 2026-08-17 with the proxy ledger (`proxy_history.py`), which is where
the tray's per-clip percentage comes from.

`ffmpeg -progress pipe:1` writes repeating `key=value` blocks, and the one
worth reading is `out_time_us` -- output written, so dividing by the probed
source duration is the percentage. Older builds emit **`out_time_ms`, which
also holds MICROSECONDS**: it is a long-standing ffmpeg misnaming, not a
typo, and treating it as milliseconds puts every encode at 0% for ever.
`parse_progress` scales both the same way.

The pipe itself is the sharper edge. Asking for `pipe:1` means the child now
writes to a pipe whose OS buffer is ~64 KB, and a full pipe **blocks the
encoder**, permanently -- the classic `Popen` deadlock the bounded stderr
deque already exists to avoid. So `_default_popen` opens stdout as a PIPE
only when the argv asked for `-progress` (`wants_progress`), and `_run_ffmpeg`
starts a drain thread for it in the same breath. If you ever add `-progress`
to an argv that some other code path runs, make sure that path drains it.

Two smaller ones. The `-progress` flag is a **global** option: it goes right
after the binary, never after the output path, and the output must stay last
because several callers index `cmd[-1]`. And publish at most once a second --
ffmpeg emits a block per output packet, hundreds a second, and each one takes
the lock the tray's refresh thread reads `gap()` under.

## 12. Fleet credentials and the write paths behind the login

Added 2026-08-17 with `COMMERCIAL_READINESS.md` item 15. Four rules that all
changed on the same day, and each one fails in a way that looks like something
else.

### An editor now has their own report token, and it outranks the shared one

Every companion in the field authenticates with the single
`DASH_REPORT_TOKEN`. It cannot be revoked for one person, everyone who has
ever been onboarded holds it, and rotating it takes the whole fleet off the
dashboard at once. **Settings > Users > REPORT TOKENS** mints a per-editor token
instead: `cce1.<id>.<secret>`, stored only as a sha256, revocable on its own
row, and **shown exactly once** -- nothing can print it again, because nothing
has it.

Handing it over is deliberately manual and there is no pairing flow for it
yet. `/api/v1/verify` -- the tray's *Sign in…* -- only ever answers with the
SHARED token; it is the bootstrap endpoint an unauthenticated companion calls,
so it must not be able to hand out a per-editor credential to whoever asks.
The admin passes the value on the same channel they already use for that
editor's NAS password, and the editor (or the admin, over SSH) puts it in
`~/.ccsync/config.toml`:

```toml
report_token = "cce1.…"
```

Restart the companion. `identity.preferred_report_token` decides what goes on
the wire, most specific first: `identity.json`'s `editor_report_token`,
`config.toml`'s `report_token`, the shared token captured at the last sign-in,
`config.toml`'s `dashboard_token`. **A sign-in never demotes a migrated
machine** -- `save_identity` carries `editor_report_token` through the rewrite,
which is the one bug in this area that would have gone unnoticed until the
shared token was switched off.

The token BINDS. A report or a selection read under it may only claim the
editor it was minted for; the dashboard 401s a mismatch by name in the log.
That is the whole point -- the shared token proves only "somebody in this
fleet", which is why `X-CCSync-Identity` had to exist beside it.

**When can the shared token be turned off?** The dashboard says so at every
boot: it names the machines whose *last* report used the shared credential
(`report_auth` table), and the same numbers are on the Users page. When that
list is empty, set `DASH_SHARED_REPORT_TOKEN_ENABLED=0` and redeploy. Do it
before that and every un-migrated machine goes dark simultaneously.

### `~/.ccsync` is owner-only now, and on Windows that means `icacls`

`identity.json` and `config.toml` hold credentials and were written at the
process default umask. On POSIX that is 0644. **On Windows `os.chmod` does not
help at all** -- it toggles the read-only attribute and says nothing about who
may read the file; the profile directory's inherited ACL decides, and on a
shared or domain-joined machine that routinely includes other local accounts.
`secretfile.harden` runs `icacls <path> /inheritance:r /grant:r <owner>:(R,W)`
in ONE call (two calls leave a window where the file has no ACEs, and a crash
in between leaves identity.json unreadable by its own owner). It never raises:
a machine that cannot be tightened still runs, with one WARNING naming the
file. An install that predates this gets its `config.toml` tightened once, at
the next companion start.

### No dashboard call follows a redirect any more (with one carve-out)

`urllib.request.urlopen` follows 3xx automatically and strips only the
`Authorization` header -- `X-CCSync-Token` and `X-CCSync-Identity` ride along
to whatever host the `Location` names. The upgrade channel has refused
redirects since AUDIT_3 H-1; the reporter, the selection client and the ytdl
executor now do too, through the same `upgrade.build_no_redirect_opener()`. A
3xx arrives as an `HTTPError`, which every one of those callers already treats
as a failed request.

**If you stub HTTP in a companion test, stub the opener, not `urlopen`** --
patching `urllib.request.urlopen` now leaves the test passing against code
that never calls it.

#### The ONE carve-out: the vendor release feed (2026-08-18)

`dashboard/src/ccsync_dashboard/release_feed.py`'s two fetches -- `channel.json`
(+ `.sig`) and the artefact download -- follow up to **5 redirects, every hop
`https://`**. They had to: the feed host is GitHub Releases, and
`https://github.com/OWNER/REPO/releases/download/TAG/FILE` answers **302** with
a `Location` on a short-lived signed `release-assets.githubusercontent.com`
URL. Refusing that is refusing the host entirely.

It is safe **there** because both halves hold, and neither is optional:

1. **The call carries no credential.** No cookie, no `Authorization`, no
   `X-CCSync-*`. There is nothing for a `Location` to steal. A test
   (`test_no_credential_rides_along_on_any_hop`) asserts the request headers
   are empty, so adding one breaks the build rather than the security model.
2. **Every byte it returns is content-verified afterwards** -- the channel
   against `settings.release_pubkeys` (Ed25519), the artefact against the
   sha256 pinned inside that signed channel, then again by
   `package_store.store_verified_package`. A redirect can change *which host*
   answers; it cannot produce bytes that verify.

A `Location:` on `http://` is refused, not followed -- a downgrade is the one
thing an on-path attacker could use. Details: `docs/RELEASE_FEED.md` §3.1, §5.

**This is not precedent.** Do NOT cite it to add a redirect follow to the
reporter, the selection client, the ytdl executor, the upgrade channel, any
admin route, or anything else that sends a token or a session cookie: for
those, following a 3xx *is* the credential leak, which is why the rule exists.
If a call is authenticated, or if it acts on bytes it has not independently
verified, it refuses redirects. Both conditions above must be true, and the
feed client is the only place in this codebase where they are.

### Both mounted apps' ingest routes are fail-closed

`broll/web`'s `/api/ingest/*` treated an unset `BROLL_INGEST_TOKEN` as "dev
mode, ingest is open". That branch is gone: no token, **503**, with a log line
saying why. A bare dev checkout needs a token like any deployment
(`openssl rand -hex 24`); the indexer needs the same value.

`music/web` never had a token because its ingest is drag-and-drop from a
logged-in browser -- true only while it is MOUNTED in the dashboard. Standalone
there is no login in front of it at all, so `/api/ingest` there now demands
`MUSIC_INGEST_TOKEN` and refuses without one. The dashboard's mount declares
itself with `musicweb.config.set_login_gated(True)`, which is a CALL from
`mount_music`, not an env var: a host that merely has a variable set is not a
process with the middleware wrapped around it. One request is also bounded now
(`MAX_INGEST_FILES`, `MAX_INGEST_TOTAL_BYTES`) -- `app.py`'s `body_size_gate`
only makes a *declaration* check on `/music/api/ingest`, on purpose, because
buffering a dropped album is the memory problem that middleware exists to
prevent.

### An editor no longer reads the whole fleet

`/api/v1/editors`, `/api/v1/projects`, `/api/v1/projects/{slug}` and the
missing-files routes used to answer everything to anyone with a session:
other editors' machine names, builds, completion, and the actual file paths
missing from a named person's laptop. Now an editor sees their own machines
plus summary counts, and an admin sees all (with `?as=` to focus one editor).
Missing-files for somebody else's device is a **404, not a 403** -- an editor
must not learn that the device id exists. The redaction lives in `api.py`
(`_scope_projects_view` / `_scope_editors_view`) and `ui.py` imports it, so
the JSON API and the pages cannot drift apart.

---

## 13. Windows desktop identity

### The taskbar shows a snake, or the wrong logo, whatever the title bar shows

Added 2026-08-18 (KNOWN_BUGS CR-24). `theme.apply_window_icon` had been setting
the title-bar icon since 0.4.7, and the taskbar button ignored it: it wore
`python.exe`'s icon in a dev tree and the exe's `icon.ico` in a frozen build.

The Windows taskbar decides which **application** a window belongs to when the
button is created. A process that has never declared an AppUserModelID is "the
exe", so the button takes the exe's icon and groups every popup under it.
`theme.claim_app_identity()` declares `com.ccsync.companion` (Windows only,
idempotent, silent); `app.run()` calls it before `load_config()`, which is the
earliest thing that can put a dialog up, and `apply_window_icon` calls it again
so a process that never went through `run()` (the wizard, a test) still claims
it before its first window maps.

**The ordering is the whole gotcha.** Measured: set before the first `tk.Tk()`
or after it but before the first map, the taskbar shows the tinted window mark;
set after the first window has mapped, that button is already grouped and stays
on the exe icon for the life of the process. So a new entry point that opens a
window must claim the identity first, not "somewhere during startup".

Which mark appears is a separate question, and not a leak: the Creators Club
mark is the product default (CR-25), and a white-label fleet selects the
neutral one with `brand_logo` in the site manifest.

## 14. Processes die with the session that started them

### Syncthing is not running, and nothing was going to notice

Added 2026-08-18 (KNOWN_BUGS SYNC-17). An editor's Windows session ended at
00:53. rclone exited `0x40010004` (`DBG_TERMINATE_PROCESS`) and Syncthing
logged "Syncthing is being stopped / Exiting". The companion came back at
18:24 on its own; Syncthing stayed dead for **eighteen hours**, with 12 GB
unsynced and lane C reporting idle and green the whole time.

**The Run key fires at logon and never again.** Everything CC Sync starts on
Windows starts from `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`:

| entry | what it starts |
|---|---|
| `CCSyncCompanion` | the tray app |
| `CCSyncSyncthing` | `wscript CCSyncSyncthing.vbs` -> `CCSyncSyncthing.cmd` -> `syncthing serve --no-browser --home=%LOCALAPPDATA%\ccsync\syncthing-config` |

That is a **start**, not a service. Nothing restarts either one if it exits,
and nothing did until the supervisor landed (`docs/SYNC_SAFETY.md` section 6,
`sync/syncthing_supervisor.py`). The tray app got away with it because an
editor who sees no tray icon restarts it; nobody looks at Syncthing, which is
why it went eighteen hours.

Corollaries worth knowing before you debug one of these:

* **A process launched over SSH dies when that session closes.** Starting
  Syncthing (or the companion, or a long ffmpeg) from a remote shell to "fix"
  a machine buys you exactly as long as you stay connected. On Windows the
  child is killed with `DBG_TERMINATE_PROCESS`, which in `syncthing.log`
  looks like an ordinary clean stop. Use the Run-key shim
  (`wscript.exe //B //Nologo %LOCALAPPDATA%\ccsync\bin\CCSyncSyncthing.vbs`),
  which detaches, rather than `syncthing serve` in the SSH session.
* **A logoff, a fast-user-switch and a forced restart all look the same** in
  the logs: a clean exit at an odd hour with nothing after it. If two of our
  processes stopped within a second of each other, that is the session, not
  a crash.
* **`DETACHED_PROCESS` alone is not enough** if the child inherits handles:
  an inherited pipe keeps it tied to the parent's console. The supervisor
  spawns with `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, `close_fds=True`
  and all three standard handles on `DEVNULL` for that reason; `upgrade.py`'s
  `_default_spawn` does the same for the companion's own relaunch.
* **macOS does not have this problem in the same shape**: Syncthing runs from
  a LaunchAgent (`com.ccsync.syncthing`), and launchd restarts it. The
  supervisor's macOS half is therefore a `launchctl kickstart -k`, which
  fixes a half-loaded agent rather than a missing process.

**First thing to check** when an editor's audio, graphics or subtitles have
stopped arriving: is `syncthing.exe` in Task Manager? Then
`~/.ccsync/state/syncthing_supervisor.json` (`attempts`, `last_error`) and the
companion log's `ccsync.sync.supervisor` lines.

## 15. Resolve's script server, and why a poll can kill it (CR-68)

Resolve's scripting API is not inside Resolve.exe. Late in launch (90-470 s
on the base rig: the project library connects first) Resolve spawns
`fuscript.exe`, which listens on TCP **1144**; Resolve then connects to it
and registers as the "HostApp". `fusionscript.dll`'s `scriptapp("Resolve")`
connects to 1144, is handed Resolve's own port, and talks to that.

The rule that matters: **the script server exits when its last connection
closes**. Any client that connects between "Started script server" and
Resolve's own registration finds no host, drops, and the server exits with
it. Resolve tries three times (the 10-20 s launch hang), logs
`Failed to connect to script server`, and never tries again: scripting is
dead for that Resolve process, for every client on the machine. The only
cure was quit Resolve, quit every poller, start Resolve, start the pollers.

Who was polling: the companion's watcher (3 s), the media-tree refresh, the
MCP server, the MulticamPipeline tools. The race is short (the window is
~0.3 s) and so it looked intermittent for months.

**Diagnosis.** `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\logs\
davinci_resolve.log`: search `script server`. A healthy launch has ONE
`Started script server: <pid>`; the broken one has three with `Failed to
connect` between them and a "Script server log:" block showing `Incoming
connection` / `HostApp destroy` / `Terminated: done: 1`. `netstat -ano |
findstr :1144` on a healthy machine shows fuscript LISTENING and exactly one
ESTABLISHED pair owned by Resolve.exe; a long tail of TIME_WAIT rows is a
poller.

**The fix in the companion** is `ccsync_companion/script_server.py`: read the
TCP table (no connection, ~6 ms), and refuse to call `scriptapp` while a
`fuscript` listener exists with no ESTABLISHED connection from its parent
process. Everything else fails open. `resolve_bridge.connect()` is the one
chokepoint, so nothing else in the companion needs to know.

**For any other Resolve client on the same machine** (the MCP server, the
MulticamPipeline tools): copy `script_server.py` next to your code - it is
stdlib-only, Windows via ctypes and macOS via lsof - and gate every
`scriptapp()` call:

    from script_server import is_starting
    if is_starting():
        return None          # Resolve is launching; try again next poll
    app = dvr.scriptapp("Resolve")

One badly behaved client is enough to take the server down for all of them,
so every client on a machine has to carry the guard. "Wait N seconds after
Resolve.exe appears" does not work: the server starts 90-470 s in, and it is
the server's start, not the process's, that opens the window.

## 16. The project library knows what the API will not tell you (library walk, 2026-08-26)

### Every click in every Resolve client goes slow while the companion polls

Measured on the base rig (Resolve 21.0.1.11, library "FF5" on the fleet's
postgres:13, timeline "Civil Defence - E1", 904-926 items): the watcher's old
API walk took **11-14 s**, because `GetClipProperty()` with no argument builds
a 60-key dictionary per clip at **12.5 ms** a clip. Resolve answers scripting
calls one at a time, so every other client on the machine queues behind it:
Timeline Cards' card click went from **0.3 s to 7 s**
(`E:\Projects\Editing\Resolve\MulticamPipeline\LAG-INVESTIGATION.md`).

The same walk out of the project library is **7 ms** and costs Resolve
nothing. The media-pool walk went 20.0 s -> 31 ms, with 1,298 / 1,298 paths
and bin paths identical to the API's.

Worse than slow, it was blind. On that timeline the API finds **0-3 usable
file paths out of 904**: every item is a multicam, a multicam answers `""` to
`GetClipProperty("File Path")`, and the API exposes nothing at all about its
angles. The library finds all **44**.

Two things came out of that and both matter if you are reading a clip path:

* `GetClipProperty("File Path")` (ONE argument) is 0.1 ms against 12.5 ms and
  agreed with the dict on all 1,298 clips of the open project, every clip kind
  (BRAW, R3D, ProRes, PNG sequence, multicam, compound). The one-arg overload
  is not documented for every build we support, so `_clip_property` in
  `resolve_bridge.py` probes it once per process and falls back to the dict.
  This alone takes the API walk from 11 s to under 1 s on a timeline whose
  library cannot be read.
* Nothing else you write should poll clip properties in a loop either. See
  section 15: one badly behaved client is enough to spoil the machine.

### Where the clips actually live in the library

PostgreSQL on the NAS for a network library, the project's `Project.db`
(SQLite) for a disk library. `library.py` reads both, read-only, SELECTs only.

The chain, all measured against FF5 on 2026-08-26:

| need | where |
|---|---|
| the project | `SM_Project.ProjectName` -> `SM_Project_id` |
| its timelines | `SM_Project_Sm2Timeline` (`DbOwner` = project, `DbAssociate` = timeline) |
| a timeline's sequence | `Sm2Sequence.Sm2Timeline_id` |
| its tracks | `Sm2SequenceContainer.Sm2Sequence_id` -> `Sm2SequenceContainer_Sm2TiTrack` -> `Sm2TiTrack` |
| its items | `Sm2TiItem.Sm2TiTrack_id` (`Name`, `MediaRef` = pool uid, `Start`, `Duration`) |
| a multicam's / compound's angles | the same chain with `Sm2Sequence.Sm2MpMedia_id` = that clip's pool uid; the tracks are named *Angle N* |
| a pool clip's LIVE path | `BtVideoInfo.Clip` / `BtAudioInfo.Clip`, keyed by `Sm2MpMedia_id` |
| the project's bins | `SM_Project.MediaPool` -> the one `Sm2MpFolder` whose `Sm2MediaPool_id` matches and whose `Sm2MpFolder_Owner_id` is NULL; descend by `Sm2MpFolder_Owner_id` |

`Sm2MpMedia_id` **is** `MediaPoolItem.GetUniqueId()`, which is the whole
reason a library-walked item can still be acted on: `media_pool_item_by_uid()`
re-finds the live object on demand (~0.15 s for 1,318 clips) instead of the
walk carrying one per clip.

The `Clip` value is a Resolve blob header followed by a **zstd frame**, and
inside that a protobuf where field 1 is the directory and field 2 the file
name (length-prefixed varints).

### The path in the database is not the path you want

Four different columns look like they hold a media path. Three of them lie.

* **`Sm2TiItem.MediaFilePath` is a placement-time snapshot.** It goes stale on
  relink: 10 items in Energy Transition still carry the pre-relink `P:\` path
  while the pool says `W:\Creators_Club\...`. `library.py` never reads it.
* **`Sm2MpMedia.FieldsBlob` holds the PROXY path**, not the media path, and it
  is behind a SECOND nested zstd frame inside a UTF-16 property bag.
* **`BtVideoInfo.Proxy` is a bare reference stub** - 197 bytes of property bag
  (UniqueId, DbType `BtVideoProxy`, DataManagerID), present on 3,873 of 3,873
  rows whether the clip has a proxy or not, with no path and no state.
* **Raw `Clip` bytes look like a path with letters missing.** Those are zstd
  back-references into the directory name. Decompress before you believe
  anything you see in a hex dump.

### Joins that are NULL, and other schema traps

* **`Sm2Timeline.SM_Project_id` is NULL for every row** (24/24 here). Use the
  association table `SM_Project_Sm2Timeline`.
* **`Sm2TiTrack.Sm2Sequence_id` is likewise NULL.** Go through
  `Sm2SequenceContainer` and `Sm2SequenceContainer_Sm2TiTrack`, whose
  **`DbIndex` is the only place the track order lives**. `Sm2TiTrack` has no
  index column and its `SubType` is uninitialised garbage (0x20202020 on V1
  here). `DbIndex` restarts at 0 **per track Type**, so a track's index means
  nothing until you know its type.
* **`Sm2TiTrack.Type` is not just 0/1: subtitle tracks are Type 2** (6 of
  FF5's 287 tracks, carrying 3,360 items). A subtitle track reported as
  "video" collides with a real V1/V2, which is why only Types 0 and 1 are
  walked.
* **`Sm2TiItem.Start` / `Duration` are varchar columns** holding decimal frame
  counts. Sort them as numbers or a long timeline orders itself lexically.
* **One library holds every project** (FF5: five of them, 4,005 pool clips).
  Always scope: timelines by the project association, the pool by the
  project's own folder tree.
* **Resolve 21.0.1 returns None from `GetCurrentDatabase()` AND
  `GetDatabaseList()`.** There is no API answer to "which library is this".
  `library.locate()` falls back to mining Resolve's own log (the project
  pointer line names the library and Network/Disk; the startup lines give each
  postgres library's host), and the config overrides beat both.
* **The library trails the UI by the Live Save interval** (~0.3 s here), or
  until the next manual save with Live Save off. See the 60 s ceiling below.

### Rules for touching the library from companion code

* **A database read NEVER happens under `_API_LOCK`.** A library that has gone
  away takes the module's 5 s statement timeout to say so, and 5 s of
  `_API_LOCK` is 5 s of frozen tray menu and 5 s of every other scripting
  client queueing, i.e. exactly the thing this work exists to remove.
* **Lock order is `_LIBRARY_LOCK` then `_API_LOCK`, never the reverse.**
  `locate()` asks Resolve which library this is, and the proxy enrichment asks
  Resolve about clips the library has already named, so the two locks do meet.
* **`ProjectLibrary.changed()` is dead with Live Save off.** It rides on
  `SM_Project.LastModTimeInSecs` and `MAX(Sm2Sequence.DbSavedTime)`, and
  `DbSavedTime` only moves when the project is SAVED. Live Save is a
  per-machine preference this companion does not control, so an editor can
  relink a clip and `changed()` will keep saying "no" until they press Ctrl-S,
  which might be after lunch. `_LIBRARY_CACHE_MAX_SECONDS = 60.0` is the
  ceiling that makes that survivable: one extra walk a minute of an operation
  measured in milliseconds.
* **Close the backend when construction fails.** `ProjectLibrary._connect()`
  used to let a raising `_find_project_id()` propagate out of `__init__` with
  a live postgres session nobody could reach. Measured: 8 failed constructions
  left 8 sessions on the server until the gc happened to run. The watcher
  retries every 3 s and postgres ships with `max_connections=100`, so that is
  the whole fleet locked out of the library inside five minutes.
* **A query with no project id is worse than an error.** `self._uid("")` binds
  NULL, `WHERE "SM_Project_id" = NULL` matches nothing, the fingerprint reads
  `(None, None)` so `changed()` is False forever, and the pool path cache
  freezes at whatever it last saw. `_ready()` raises `LibraryUnavailable`
  instead, and the API walk takes over.
* **Every public method raises `LibraryUnavailable` and nothing else.** A bare
  pg8000/sqlite3/zstd exception reaching the watcher would be a crash, and the
  whole point of the walk is that it is optional.

### The log says "library walk unavailable"

The commonest cause is a library **name** mined from a log that no longer
matches, or a project name that is not in the library we found. You will see:

    resolve: library walk unavailable (project id unknown for 'Civil Defence - E1'
    in PostgreSQL FF5 (10.x.x.x:5432)) -- using the API walk; clicks in other
    Resolve clients will lag during walks

or `... has no project named ...`. Nothing breaks: the API walk answers, more
slowly and without the angles. The line is WARNING **once per process**, then
INFO at most every 5 minutes (`_LIBRARY_FALLBACK_LOG_SECONDS = 300.0`),
because permanent fallback is a legitimate state on plenty of machines (a disk
library we have no reader for, a laptop off the NAS's network) and a line
every 3 s poll would be the loudest and least useful thing in the log. A
failed attempt is not retried for 60 s (`_LIBRARY_RETRY_SECONDS`): a NAS that
is off costs 5 s of stalled watcher thread per attempt.

A working one says so once, at INFO:

    resolve: reading clips from the project library PostgreSQL FF5 (10.x.x.x:5432)
    for 'Civil Defence'

To switch the whole thing off and get the old behaviour, `library_walk = false`
in `~/.ccsync/config.toml`. To point it somewhere by hand:
`library_db_host`, `library_db_port`, `library_db_name`, `library_db_user`,
`library_db_password` (blank password = Resolve's own default, which is what
the fleet's libraries use; `config.toml` is owner-only because it already
carries `report_token`). Changing any of the six drops the open library
immediately, so an editor who fixes a wrong host does not restart anything.

### The proxy keys follow BOTH readers, and half an answer is no answer (review 2, 2026-08-26)

The library cannot give `proxy_path` / `proxy_state` cheaply (the proxy path
sits behind a second nested zstd frame in `Sm2MpMedia.FieldsBlob`), so the
pool walk reads them through the API, one-arg, in 100-clip chunks with
`_API_LOCK` released between chunks. The first cut gated that on
`proxy_gen_enabled` alone. The reader of those keys is
`app._relink_proxies_once`, gated on `proxy_relink_enabled` (default true),
and `proxy_gen_enabled` derives to FALSE on every lane-B editor rig - exactly
where lane B syncs proxies down. Result would have been 1,300 clips reported
as "no proxy" and 1,300 unsolicited `LinkProxyMedia` calls on the next
media-tree refresh. Rules now in `_enrich_proxy_keys`: enrich when EITHER
reader is on; a run that cannot finish (project switched, uid map empty)
returns False and `get_media_pool_items` answers from the API walk instead of
handing out half-enriched items; `_LIBRARY_LOCK` is never held while
enriching. `""` in those keys means "nobody reads them", never "unknown".

## 17. A Mac spells filenames differently (Unicode NFD, CR-90, 2026-08-28)

macOS hands filenames back **decomposed**. The NAS, Windows, rclone and
Syncthing all serve the same name **composed**. Two byte strings, one file:

```
NFC (NAS, Windows)  Matej Šimalčík   S=U+0160  c=U+010D  i=U+00ED
NFD (macOS listdir) Matej Šimalčík   S+U+030C  c+U+030C  i+U+0301
```

`==` says no. Anything that compares a path a Mac reported against a path
anything else reported must fold the normalisations first. This cost a day of
a remote editor's fleet page saying they were 12 files / 2.9 GB behind on
footage that was already on their disk (CR-90): the lane A/B backlog is a
rel_path diff done in SQL, and SQL cannot normalise. Lane B kept correctly
reporting `transferred 0 file(s)` throughout, because **rclone folds the
normalisations when it compares** - as does Syncthing - so the sync engines
were never wrong; only the view was.

Rules:

* **Compare through a normaliser.** `db.media_rel_key()` for the media
  presence tables, `links.normalise_declared()` for declared paths,
  `resolve_bridge._nfc()` for Resolve bin and clip names. Add to that
  list rather than inlining a `normalize` call.
* **Normalise on the way IN when the value is only ever compared or
  displayed** (`nas_media.rel_path`, `editor_media.rel_path`). Then the SQL
  can stay an exact match, which is the only thing that is fast.
* **Never normalise a path something opens, renames or deletes.** There the
  bytes on disk are the truth, and on APFS the truth can be NFD.
  `file_moves` keeps its own copy of the path for exactly this reason.
* **CJK will not warn you.** Han characters, kana and Hangul syllables have
  no decomposed form, so a tree full of Chinese folder names matches
  perfectly and one accented Latin or Cyrillic name in the same tree does
  not. A mismatch presents as "most of it synced", never as "nothing works".
* **Test with a real pair.** `dashboard/tests/test_unicode_paths.py` carries
  the actual NFC/NFD spellings taken off the NAS and off that MacBook.

## 18. A Tk root freed on the wrong thread kills the process (CR-93, 2026-08-29)

A `tk.Tk()` root owns a Tcl interpreter. `_tkinter` frees that interpreter in
`Tkapp_Dealloc` - **inline, on whatever thread drops the last Python
reference**, with none of the marshaling an ordinary Tk call gets. Tcl
answers an interpreter deleted from a thread other than its creator with

```
Tcl_AsyncDelete: async handler deleted by the wrong thread
```

which is `Tcl_Panic`, which is `abort()`. Note what that costs you: **no
exception, no `finally`, no `atexit`, no `sys.excepthook`, no crash file, and
nothing in the log.** The process is gone mid-instruction. On Windows the
only trace is the Event Log:

```
Faulting module name: tcl86t.dll   Exception code: 0x80000003
```

The companion builds every dialog on the thread that wanted it (win32; see
`ui_dispatch`'s docstring, and it must stay that way), so this is live for
any Tk object that outlives its thread. It cost the base rig seven silent
deaths in eleven days before anyone read the Event Log, because "the tray
keeps closing itself" does not sound like a crash.

**And then it recurred on the fixed build (2026-08-30, twice), which is the
half of this section worth remembering.** The first fix counted references
at the end of each dialog and parked the root when a widget still held the
interpreter. That closes "a widget kept in an attribute". It cannot close
this:

```python
def _build_settings_window(app, lock):
    root = tk.Tk()
    ...
    def _refresh():
        ...
        refresh_job[0] = root.after(_REFRESH_MS, _refresh)   # references ITSELF
```

`_refresh` reaches itself through its own closure cell - function -> closure
tuple -> cell -> the same function - and reaches `root` the same way. That is
a **reference cycle**, and a cycle is freed by the **cyclic garbage
collector, not by refcounts**: the frame returning frees nothing, and the
collector runs on whichever thread's allocations trip it next. Both
recurrences died on the watcher thread, inside `Garbage-collecting`, during a
project-library read (a hundred thousand fresh objects is what makes the
collector run a full pass), minutes to hours after the window had closed.
The minidump's stack, symbolised with python.org's PDBs, reads
`gc_collect_main -> delete_garbage -> cell_clear -> func_dealloc ->
func_clear -> tupledealloc -> cell_dealloc -> ... -> subtype_dealloc ->
Tkapp_Dealloc -> Tcl_DeleteInterp -> Tcl_AsyncDelete -> Tcl_Panic`. No
refcount taken INSIDE the dialog can see this, because inside the dialog the
frame is alive and every count is legitimately high. "Every Tk object is a
frame local, so they die with the frame" was the wrong belief: locals die
with the frame; a cycle among them does not.

The rule that holds, now in `ui_dispatch`:

* **Every Tcl interpreter is pinned the moment it is born** (a
  `Py_IncRef` through ctypes, invisible to Python and to finalisation),
  through a wrapper on `tkinter.Tk.__init__` installed when `ui_dispatch` is
  imported. Whoever drops the last visible reference, on whatever thread,
  only ever lowers the count to the pin. Tkapp_Dealloc has exactly one path
  left: `_try_free()`.
* **It is freed on the thread that built it, or not at all.** At the end of
  every `ui_dispatch.dispatch(fn)` - fn's frame has returned, its closures
  are garbage - the building thread runs `gc.collect()` itself and frees the
  interpreter if nothing else holds it. `release_root()` does the same for
  the windows that own their root. A root still held after that stays pinned
  (1.8 MB, measured), and the log names what holds it, with referrer chains
  (`CCSYNC_TK_AUDIT=1` logs the whole registry after every pass).
* **A thread that has exited can never free what it built.** Tcl ties the
  interpreter to that thread's storage. The tray's per-click worker threads
  are the usual case; the registry reports such an interpreter once as a
  leak. `release_root()` called from any other thread frees nothing and says
  so - the previous graveyard keyed on `threading.get_ident()`, which Windows
  reuses, and a sweep on a recycled ident would have been the abort again.
* **Do not "fix" it by keeping the root alive in a module global.**
  Interpreter shutdown clears module globals from the main thread, so that
  just moves the abort to exit (measured: exit code 3). The pin is a real
  extra refcount, which finalisation cannot undo.
* **It is not only widgets.** A `tk.StringVar`, a `ttk.Style`, a
  `PhotoImage`, a bound method handed to a worker, and now any nested
  function that reaches `root` - each holds the interpreter as firmly as a
  Button does.

Generalise it: **any object whose C-level destructor has a thread affinity
(a Tcl interpreter, a COM object, a GUI handle) must never be reachable only
through a reference cycle**, because the cyclic GC frees cycles on an
arbitrary thread. Pin it, and free it explicitly from the right thread.

Proving any of this needs a subprocess - the failure kills the interpreter
running the test. `companion/tests/test_tk_release_native.py` is the pattern:
run the shape in a child, assert on its exit code. It carries both shapes
(the widget-in-an-attribute one and the closure-cycle one), each as a
"disease" child that must still abort and a "cure" child that must not.

And because an abort has no `finally`, the companion no longer relies on
staying alive: `supervisor.py` (the same exe re-entered with `--supervise`)
waits on the companion's process handle and relaunches it after a death
that left the run marker behind - never after a Quit, a Stop-Process or a
self-upgrade, and never more than three times an hour.

---

## 19. A fleet job's path (root + rel), and two traps in it (phase 0, 2026-08-29)

`docs/TIMELINE-CARDS-INTO-CCSYNC.md` §4.1: a job on the queue never carries
an absolute path. The tree is spelled the same everywhere on purpose (`P:\`),
and the two roots a Timeline Cards job needs are not: the vault is `X:\` on
creator-1, `/vault` inside the Timeline Cards container, and a UNC path on
the wire. So the queue carries `("vault", "Vault/2026/FF5/...")` and the
machine that claims the job resolves it (`companion/job_paths.py`).

**Trap 1: `/vault/2026/...` looks relative if you strip before you check.**
The obvious implementation -- `value.strip("/")` and then "is it absolute?"
-- accepts the container's own spelling and silently turns it into a path
under whatever `jobs_vault_root` is. It cost nothing here because a CLI test
caught it, but the failure it would have produced is the worst kind: a job
that runs, succeeds, and writes in the wrong place. **Test the RAW value**,
in `tools/jobs.py:check_relative` and in `job_paths.resolve`, before any
normalisation. Both refuse a leading `/`, a drive letter, and `..`.

**Trap 2: a root that is CONFIGURED is not a root that is THERE.** An
external drive gets unplugged and a `subst` does not always run at login.
`job_paths.roots()` checks existence, so an absent root is not reported as a
mount, is not offered work that requires it, and is refused if a job arrives
anyway. Reporting a configured-but-absent root is exactly how a job gets
claimed by the one machine that cannot read a single file of it.

**And a third thing, about credentials rather than paths:** the job submit
routes are SESSION routes, so a non-browser client needs a CSRF token and
has no page to read one off. `POST /api/v1/login` returns the caller's own
(`csrf`) since 2026-08-29 -- an HMAC over that session's id, worthless
without the cookie. Do NOT reach for the other answer (exempting the write
route): `_CSRF_EXEMPT_*` is for bearer-token routes, and a session route in
it is a session route anyone's browser can be made to call.


## 20. Renaming an ffmpeg output changes the FILE (phase 1, 2026-08-30)

Two things bit while moving Timeline Cards' three media recipes onto the
fleet (`companion/src/ccsync_companion/jobs_media.py`). Both are about the
same mistake: treating a derived file's NAME as cosmetic.

**ffmpeg picks its muxer from the output's extension, so `.partial` breaks
it.** Timeline Cards writes `<out>.tmp.m4a` and lets `.m4a` select the `ipod`
muxer; this repo writes `<out>.partial`, because `.partial` is the suffix
every sync lane already excludes in both directions and a half-written proxy
must never reach another machine. `<name>.m4a.partial` has no extension
ffmpeg knows, and the command fails with "Unable to find a suitable output
format" -- or, worse on some builds, picks something plausible. So the argv
has to say it: **`-f ipod` for `.m4a`, `-f mp4` for `.mp4`, `-f ogg` for
`.ogg`** (Timeline Cards already passed the last one). Those are exactly what
the three extensions resolve to; the m4a and the mp4 were measured
byte-identical against the Timeline Cards command on 2026-08-30, and the ogg
differs only in its random Ogg stream serial, which the muxer re-rolls on
every run of any argv at all.

If you ever change where a recipe writes, check the muxer, not just the path.

**A derived file can be NEWER than its source and still be stale.** Both
Timeline Cards and this module decide "already made" with
`mtime(out) >= mtime(src)`, which is right for a proxy and wrong for a
`.peaks`: the file's THIRD BYTE is the rate it was made at (200/s since
2026-08-28, 50/s before), and a file at the old rate is newer than the rush it
came from. The entry check knew that; the `os.replace` re-check -- rule 2's
"has a finished file appeared while we worked?" -- did not, so it discarded
every freshly-made 200/s file in favour of the stale 50/s one, for ever. The
fix is that `_with_partial` takes an `already_made` predicate and peaks passes
its own. **Wherever you re-check before publishing, re-check with the SAME
question the entry check asked**, or the two disagree and the disagreement is
invisible: the job succeeds, the page redraws, and nothing changes.

**And a third, from the same afternoon: a report field the dashboard's model
does not declare is dropped SILENTLY.** `CapabilitiesIn` is a pydantic model
with `extra` ignored, deliberately -- a newer companion that grows a field
must never 422 its whole report and vanish from the fleet grid. The cost is
that adding a capability is TWO changes, and forgetting the second one
produces no error anywhere: companion 0.9.57 reported `ffprobe: true`, the
model dropped it, the column stored `0`, and every machine in the fleet was
correctly and invisibly refused all three media kinds. The pin is in
`dashboard/tests/test_jobs_contract.py`, which now asserts that EVERY scalar
the companion's `capabilities.build()` produces comes back out of
`db.machine_capabilities` unchanged -- so the next field cannot be added to
one side only.

---

## 21. Two Resolve clients on one machine (Timeline Cards, phase 2, 2026-08-30)

§15 (CR-68) says one unguarded poller kills scripting for every client on the
machine for the whole Resolve session. Phase 2 puts a SECOND scheduler inside
the companion -- the Timeline Cards engine, sweeping at 1 Hz with a 10 Hz
playhead read -- so the rules that keep that true are worth stating on their
own.

**One process, one connection.** The engine does not call `scriptapp()`. It is
handed `timeline_cards_bridge.CardsBridge`, whose `resolve()` is
`resolve_bridge.connect()` -- the one chokepoint, carrying the guard. An
engine that still owns a connection is REFUSED at start
(`BRIDGE_CONTRACT_VERSION`, plan §7c.1), and the refusal names the document.

**One machine, one client.** `timeline_cards_role` refuses to start if a
standalone `reorder_web.py --agent` (or the PC's own `reorder_web.py 8800`) is
running, and it does NOT kill it. The probe FAILS CLOSED: an unlistable
process table counts as "one is running". A false refusal costs the page until
somebody looks; a false clearance costs scripting for every client on that
machine, and the cure is closing Resolve.

**One lock, three cadences.** The watcher polls every 3 s, the engine sweeps
every 1 s and reads the playhead every 0.1 s, and all of them take
`resolve_bridge._API_LOCK` -- from outside that module through the one public
entry, `resolve_bridge.api_call(name)`. Two rules keep that from starving
anything:

* **Never hold the lock for a walk.** The per-clip property crawl is 11-95 s
  on a big project (§16). The engine's sweep asks `bridge.sweep_items()`,
  which reads the project library with the lock RELEASED -- and which returns
  None rather than answering out of the API walk, because handing that back
  would put the crawl on the sweep's hot path with the lock held for all of
  it.
* **Measure it.** `bridge.stats()` carries `takes`, `held_total`, `held_max`
  and `held_max_call` for the life of the process, and a take past 0.5 s is
  logged with its name (at most once a minute). "The tray went quiet" is then
  a number, not an argument. Measured with the fake bridge: 100 takes, under
  5 ms each.

**A halt refuses a start; it does not interrupt an edit.** Every edit is a
synthetic keystroke SEQUENCE, and one stopped half way through is a timeline
nobody asked for. The companion's shutdown is what lets go of Resolve.

**The release/reload handshake has never run live.** `SaveProject`,
`CloseProject`, `LoadProject`, `SetCurrentTimeline`: four calls that
`TRUENAS-APP-PLAN.md` §0 says twice have never been executed against a real
project. Run them on FF5lab from the standalone agent BEFORE turning
`cards_agent` on. Do not port an unexercised path and change its host in the
same week.

---

## 22. Mounting somebody else's HTTP server inside yours (Timeline Cards, phase 3, 2026-08-30)

`/cards` is not a FastAPI sub-app like `/broll`, `/music` and `/ytdl`. It is a
`BaseHTTPRequestHandler` from another repository, with ~70 hand-dispatched
routes and its own Range/ETag/gzip code, mounted through
`dashboard/src/ccsync_dashboard/cards_wsgi.py` + `a2wsgi`. Four things about
that are not obvious and one of them takes the whole fleet down.

**1. `POST /api/restart` would `os._exit(0)` THE DASHBOARD.** In the
standalone server that route closes its listener and re-execs the process --
the page's ⟳ button, for picking up code edits. Mounted here, "the process" is
the container that every companion reports to. `cards.CardsGate` refuses the
path before the handler sees it, and the handler's `self.server` is a
`_NoServer` whose `shutdown()` logs a refusal. Two locks, because the failure
is unrecoverable and the button is right there in the header.

**2. Do not buffer the response.** `/audio` and `/video` serve whole media
files; a 480p proxy of an hour-long interview is hundreds of megabytes. The
shim parses the status line and headers out of the handler's first `wfile`
write, calls `start_response` once, and hands every later chunk to the WSGI
`write()` callable -- which a2wsgi puts on an asyncio queue of ten and blocks
on. That block IS the backpressure the real socket used to provide. A shim
that collected the chunks into a list would work in every test and OOM the
container the first time somebody scrubbed a lane on a phone.

**3. `Date` and `Server` come out twice otherwise.** `send_response` emits
both and uvicorn emits both again. Two `Date` headers is a malformed response
and which one a proxy believes is undefined; the shim drops the handler's.

**4. The engine's threads are yours to stop.** Starlette runs **no lifespan
for a mounted app** -- the same trap `broll._init_broll_storage` exists for on
the other side (nobody creates the data dirs either). `mount_cards` starts the
engine and `app.py`'s lifespan `finally` calls `cards.stop_engine`. They are
all daemon threads, so this is not what ends the process: it is what stops a
library sweep from running against a database the next process is opening.

And the one that is not about HTTP at all: **an unprivileged container cannot
setuid**, so the page cannot write a share owned by somebody else without
`group_add` AND a group-writable, setgid vault on the host. Neither half works
alone and both fail quietly -- `docs/DOCKER.md`, "The chown, and why it is
needed BEFORE the first deploy".

## 23. A dead pid still holds its handles (single-instance, CR-120, 2026-09-03)

The companion's single-instance slot on Windows is the named mutex
`Local\ccsync-companion-single-instance`. R11 (2026-08-12) taught the guard to
wait when the environment says this build was spawned to REPLACE a pid
(`CCSYNC_REPLACES_PID`): a self-upgrade's or self-restart's child reaches the
guard about a second after being spawned, while the predecessor is still
tearing down its lanes and still holding the mutex. The wait retried
`CreateMutexW` and gave up early if the predecessor's pid had read dead before
a retry that still saw `ERROR_ALREADY_EXISTS` -- reasoning that a dead process
has already dropped its handles, so the mutex must be somebody else's.

**A pid can read dead while the process still owns every handle it had.**
Windows sets `Process->ExitStatus` at the START of termination:
`NtTerminateProcess` writes it before the threads are torn down, and
`ExitProcess` runs `LdrShutdownProcess` (every `DLL_PROCESS_DETACH`) before
its own final `NtTerminateProcess`. `GetExitCodeProcess` reports that status,
so it answers "not `STILL_ACTIVE`" for tens to hundreds of milliseconds -- and
for a frozen Python + Tk + ctypes process, comfortably longer -- while the
handle table, the named mutex included, is still intact. On the base rig at
16:34 on 2026-09-03 the replacement refused 1.4 s after being spawned, the
predecessor finished the shutdown it had already announced, and the machine
had NO companion until the owner relaunched the tray.

Two rules come out of it, both in `companion/src/ccsync_companion/app.py`:

**"pid gone" only starts a clock.** `_acquire_mutex_win32` keeps retrying for
`PREDECESSOR_RELEASE_GRACE_SECONDS` (15 s) after the first dead reading and
only calls the slot a different companion's if it is still held when that
expires. The overall 90 s deadline is unchanged, and a slot that frees is
taken on the next retry whatever the probe says -- that was R11's other point.

**Ask the process OBJECT, not the exit code.** `_pid_is_alive_win32` opens
with `PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE` (`SYNCHRONIZE`,
0x00100000, is what `WaitForSingleObject` needs on a process handle -- without
it the wait fails with access denied) and treats `WaitForSingleObject(h, 0) ==
WAIT_OBJECT_0` as dead, because the object is signalled only once termination
is complete. `GetExitCodeProcess` is the fallback for when the wait call
itself fails. Signalled is dead whatever the exit code says, which is also how
the old "a process that genuinely exited with 259 reads as alive forever" case
stopped mattering. Every other arm still fails SAFE (unknown means alive):
letting a second companion take a live instance's slot is the worse mistake,
and it is the one the guard exists to prevent.

The POSIX path (`_acquire_lock_file`) shares the probe but not the bug: a pid
file has no handle semantics, so there is nothing to hold on past death.
