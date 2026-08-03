# MACOS_FIRST_RUN.md -- the first supervised Mac session

The macOS port is **code-complete and unvalidated**. Every macOS-only path in
it -- `diskutil`, `launchctl`, `xattr`, `plutil`, pyobjc, `caffeinate`, and
the edit of Resolve's own preference files -- was written from documentation
and research, not from a live run. This file is the script for the session
that changes that.

Work top to bottom. Each step says **what to run**, **what success looks
like**, and **what failing looks like** -- because on a Mac most of these
fail quietly, and "nothing happened" is a result you have to be able to
recognise.

**Record as you go.** A step that half-worked is the most valuable thing this
session can produce, and it is worthless if it is remembered as "fine". Keep
a running note of: the exact command, what was printed, and anything you had
to do that this document does not mention.

**Ground rules**

- Use a **scratch project** and a **scratch SSD** where possible. Section E
  deliberately provokes the failure that fills an internal disk.
- Never `rm -rf` anything under `/Volumes`. `sudo rmdir` refuses when a
  directory is not empty; that refusal is the safety feature.
- Keep `tail -f ~/.ccsync/companion.log` open in a spare Terminal tab for the
  whole session. Most of the evidence lands there.
- If a step fails, **record it and continue** where the next step does not
  depend on it. A full pass with five recorded defects beats half a pass.

Reference material: `installer/README.md` (what the scripts do),
`docs/RELEASE.md` → "The macOS release" (the build/publish model),
`docs/GOTCHAS.md` § 10 (the traps this is all written around),
`docs/EDITOR_SETUP.md` § 6 (what the editor is told).

---

## A. Build session (on the Mac)

- [ ] **A1. The right python3.** Use **python.org CPython 3.12** or a
  `uv`-managed 3.12 -- **not** Homebrew's python.

  ```bash
  python3 -V          # 3.12.x
  which python3       # /Library/Frameworks/Python.framework/... or a uv path
  python3 -c "import tkinter; print(tkinter.TkVersion)"
  ```

  *Why:* PyInstaller's Tk collection is the fragile part of this build.
  Homebrew's python links against a Homebrew Tcl/Tk that PyInstaller
  collects incorrectly (or not at all), and the failure surfaces much later
  as a companion that starts, logs normally, and never shows a dialog.

  **Failing looks like:** `which python3` → `/opt/homebrew/bin/python3`, or
  `import tkinter` raising. Fix the PATH before building; do not "work
  around" it.

- [ ] **A2. Fresh checkout, clean tree, LF line endings.**

  ```bash
  git pull
  git status --porcelain          # expect: empty
  git log --oneline -5
  file installer/macos_bootstrap.sh installer/macos_uninstall.sh tools/release_macos.sh
  ```

  **Success:** the five macOS-port commits are present; `file` says
  `ASCII text` / `Bourne-Again shell script`, **not** `with CRLF line
  terminators`.

  **Failing looks like:** `with CRLF line terminators` -- the checkout
  ignored `.gitattributes`. `git add --renormalize <file>` (or re-clone) and
  do not proceed: a CR makes the script fail on its first line with
  `bad interpreter: bash^M`, and a CRLF `macos_bootstrap.sh` is refused by
  the publisher anyway. A dirty tree is not fatal but stamps the build
  `<version>+dirty`; clean it if you intend to publish.

- [ ] **A3. Build it: `./tools/release_macos.sh`** (no `--publish` yet).

  **Success:** six steps announce themselves in order --
  platform → version parity → venv + tests → PyInstaller + `codesign` →
  manifest → "NOTHING IS PUBLISHED YET". The suite is ~1500 companion tests.

  **Tests may surface Windows-assuming stragglers.** That is expected on the
  first Mac run and is *information*, not an obstacle:
  1. record the failing node IDs verbatim (`pytest -q` prints them),
  2. re-run with `--skip-tests` to get the build,
  3. file them; the manifest will honestly say `tests_run: false`.
  Do not patch tests in a hurry mid-session.

  **Failing looks like:**
  - `no python3 on PATH` → A1.
  - `pip install failed` → almost always the `tray` extra
    (`pystray`/`Pillow`/`pyobjc-framework-Cocoa`). Nothing was built.
  - `PyInstaller reported success but there is no binary` → check
    `companion/build.spec`'s darwin branches.

- [ ] **A4. The signature is ad-hoc, not absent.**

  ```bash
  codesign -dv companion/dist/ccsync-companion
  ```

  **Success:** output includes `Signature=adhoc`. (The release script
  already checks this and fails the build without it.)

  **Failing looks like:** `code object is not signed at all`. An **unsigned**
  arm64 binary is killed by the kernel the moment it launches -- the editor
  sees `zsh: killed`, or from launchd, absolutely nothing. Re-sign with
  `codesign --force --sign - companion/dist/ccsync-companion` and work out
  why PyInstaller did not.

- [ ] **A5. It is arm64, and it is a bare binary.**

  ```bash
  file companion/dist/ccsync-companion
  ```

  **Success:** `Mach-O 64-bit executable arm64`.

  **Failing looks like:** `x86_64` (built under Rosetta -- the whole fleet is
  Apple silicon), `universal binary` (not what anyone asked for), or `Zip
  archive` / a directory (the spec produced a bundle instead of the onefile
  binary; the download path expects a **bare binary**, not a zip and not a
  `.app`).

- [ ] **A6. Manifest sanity -- the BSD tool spellings.**

  ```bash
  cat companion/dist/ccsync-release.json
  ```

  **Success:** `size_bytes` non-zero, `artifact_mtime` a real timestamp,
  `built_by` `<user>@<host>`, `arch` `arm64`, `platform` `macos`.

  **Failing looks like:** `size_bytes: 0`, empty `artifact_mtime`, or
  `unknown@unknown`. Those three come from `stat -f%z`, `date -u -r` and
  `hostname -s` -- **BSD** spellings. A PATH that puts GNU coreutils first
  breaks them silently. Record it; the build is still good, the provenance
  is not.

- [ ] **A7. Menu-bar smoke run.** From Terminal, with no companion already
  running:

  ```bash
  ./companion/dist/ccsync-companion
  ```

  **Success, all four:**
  1. a CCSync icon appears in the **menu bar** within a few seconds;
  2. **no Dock icon appears** (the accessory activation policy worked);
  3. `~/.ccsync/companion.log` gains `ccsync-companion vX.Y.Z starting`;
  4. menu → **Open log** opens `~/.ccsync/companion.log` (via `open`, so
     whatever macOS has associated with `.log` -- Console or TextEdit).

  **Failing looks like:**
  - process dies instantly / `Killed: 9` → A4.
  - a **Dock icon** appears → the activation policy call failed. Both the
    success and failure lines for it are logged at **DEBUG**, so set
    `log_level = "DEBUG"` in `~/.ccsync/config.toml` and restart to see
    `could not set the macOS activation policy …`. Cosmetic in itself, but
    record it: it also implies pyobjc is not doing what the shutdown guard's
    delegate half expects.
  - no menu-bar icon at all, log otherwise normal → the tray extra was not
    bundled. Rebuild; do not ship this binary.
  - an `osascript` alert saying **"CCSync is already running."** → that is
    the single-instance guard doing its job. Quit the other one. Record how
    the alert *rendered* -- it is deliberately `display alert` (a dialog the
    user must dismiss) rather than `display notification` (a banner that
    auto-dismisses and gets missed). While you are here, also record whether
    `display notification` shows anything at all from this binary, since the
    tray's toasts depend on it.

- [ ] **A8. Publish it.**

  ```bash
  ./tools/release_macos.sh --publish --make-current
  ```

  **Success:** `pre-flight: vX.Y.Z is not on the server yet` → `logged in as
  <admin>` → `published macos companion vX.Y.Z and made it CURRENT`, then a
  WHAT NEXT block.

  **Failing looks like:** `409` (that version is already published -- bump
  `VERSION` in **both** `config.py` and `pyproject.toml`); `is not a
  dashboard admin`; a login failure (the dashboard authenticates against SMB
  accounts -- `truenas_admin` is not a dashboard login).

  Confirm from the base rig afterwards:
  `.\tools\check_deploy_drift.ps1 -AdminUser <you>` must show the current
  **macos** package at this version.

---

## B. Spike checks -- these gate the Batch-3 UI design

Three open questions that can only be answered on real hardware. Answer them
before anyone designs UI on top of assumptions.

- [ ] **B1. Does pystray's `run_detached` coexist with a Tk pump?**

  With the companion running (A7), open the menu-bar menu → **Sign in…**.

  **Success:** the dialog appears, takes keyboard input, closes cleanly, the
  menu is still responsive afterwards -- and a **second** dialog opens after
  the first (the popup lock released properly).

  **Failing looks like:** nothing appears; a beachball; the menu-bar icon
  freezes; a crash mentioning `main thread is not in main loop`,
  `NSInternalInconsistencyException`, or "Tcl_AsyncDelete: async handler
  deleted by the wrong thread". **Record the exact text** -- this single
  answer decides whether macOS UI can use Tk dialogs at all, or whether
  Batch-3 has to move to native sheets.

- [ ] **B2. Does the Resolve scripting bridge bind, and in which spelling do
  clip paths come back?**

  Launch Resolve, open a project whose clips are stored as `P:\Projects\...`,
  put some on a timeline, and watch the log.

  **Success:** no `Resolve didn't answer` toast, and **one** INFO line,
  once per process:

  ```
  resolve (macOS): N of M timeline clip paths came back in canonical drive
  spelling; first canonical='P:\...' first other='...'
  ```

  **Record which side won.** If Resolve returns the stored `P:\` strings, the
  fixer/classifier/proxy-relinker are looking at canonical paths and
  `canon.py` translates for probes. If it returns Mapped-Mount-resolved local
  paths (`/Volumes/...`), they are looking at local paths and every
  local↔canonical assumption downstream needs re-reading. A **mixture** is
  the interesting case and must be recorded exactly.

  **Failing looks like:** no line at all (the bridge never connected -- check
  for a `DaVinciResolveScript` import error in the log; the env bootstrap
  paths differ between Resolve versions and between the App Store and direct
  builds), or the line reporting `0 of 0`.

- [ ] **B3. Does SIGTERM reach the shutdown guard?**

  At startup the log should already contain:
  `shutdown guard: SIGTERM will shut the companion down gracefully`. Then:

  ```bash
  launchctl bootout gui/$(id -u)/com.creatorsclub.ccsync.companion
  # (or, for a Terminal-run instance: kill -TERM <pid>)
  ```

  **Success:** the log gains
  `SIGTERM received (logout or launchctl bootout) -- shutting down`
  followed by the normal shutdown lines, and the process is gone within a
  second or two.

  **Failing looks like:** the process disappears with **no** such line. That
  means python's signal handler never ran, because pystray's AppKit run loop
  owns the main thread and python only dispatches signals between bytecodes
  it is executing. The fix is already seamed: `_DarwinShutdownGuard` takes a
  `signal_fn` constructor parameter -- swap it for
  `PyObjCTools.MachSignals.signal`, which is exactly what pystray's own
  darwin backend uses for SIGINT.

  Also record: if startup logged `could not install a SIGTERM handler`
  instead, the guard was started off the main thread.

- [ ] **B4. Which quit routes reach `applicationShouldTerminate_`?**

  With a lane actively transferring, try each and record what happens:
  menu-bar **Quit**; `osascript -e 'tell application "ccsync-companion" to
  quit'`; a real logout.

  **Success (for at least one route):** a notification naming what is still
  moving, the quit is *delayed once*, and an immediate second attempt goes
  through. Log: `quit requested while syncing -- asking once: …`.

  **Failing looks like:** `shutdown guard: pyobjc/AppKit unavailable` (the
  build lost pyobjc) or `something else owns the app delegate (<repr>)` --
  in which case record the repr: pystray is documented as **not** setting an
  NSApplication delegate, and if that has changed, this half is disabled by
  design rather than broken. Also record whether **install ordering** matters
  (guard started before vs. after the tray), since the delegate slot is
  claimed first-come.

---

## C. Install drill

Do this as the *editor* would, on the real SSD, with the companion from A8
coming down the wire.

- [ ] **C1. Dry run first.**

  ```bash
  ./installer/macos_bootstrap.sh --tailnet-host <nas> --editor-name <you> \
      --local-root "/Volumes/<SSD>/Creators_Club" --dry-run
  ```

  **Success:** every action prefixed `[dry-run]`, including "would verify
  … is a real mount … and write ~/.ccsync/volume.json" and "would run the
  embedded helper". Nothing exists afterwards that did not before
  (`ls ~/.ccsync`, `ls ~/Library/LaunchAgents`).

  **Failing looks like:** any file appearing. That is a bug -- record the
  step that created it.

- [ ] **C2. The real run.**

  ```bash
  DASHBOARD_TOKEN=<token> ./installer/macos_bootstrap.sh \
      --tailnet-host <nas> --editor-name <you> \
      --local-root "/Volumes/<SSD>/Creators_Club"
  ```

  **Success -- these lines, in this order-ish:**
  - `local root is on the external volume /Volumes/<SSD> -- verifying …`
  - `volume /Volumes/<SSD> is mounted (UUID …, filesystem apfs)`
  - `recorded the sync volume in ~/.ccsync/volume.json`
  - `downloaded companion verified against its published sha256`
  - `installed the companion: ~/.local/ccsync/bin/ccsync-companion (sha256 …)`
  - `wrote companion LaunchAgent` + `loaded companion LaunchAgent`
  - a **Syncthing device ID** in the closing block
  - step 6: `DONE FOR YOU: Resolve maps P:\ to …` (or one of the documented
    deferrals -- section D)

  **Failing looks like:**
  - `diskutil does not recognise /Volumes/<SSD> as a volume` → record the raw
    output of `diskutil info -plist "/Volumes/<SSD>"`; the parser expects a
    plist with `VolumeUUID` and `FilesystemType`.
  - a `volume.json` with an empty `volume_uuid` → `plutil -extract` is
    missing or shaped differently on this macOS and the `sed` fallback also
    missed. Record both:
    ```bash
    plutil -extract VolumeUUID raw -o - /tmp/volinfo.plist
    ```
    Without a UUID the root guard degrades from `misplaced` detection to
    plain `absent` -- section E4 then cannot pass.
  - `the dashboard sent no X-CCSync-SHA256 header` / `does not match its
    published checksum` → nothing was installed, deliberately.
  - the whole `THE SYNC APP IS NOT INSTALLED ON THIS MAC` block plus a
    non-zero exit → read the stated reason; a 404 means A8 never happened.

- [ ] **C3. Record every TCC prompt.** macOS will ask for permission at
  least once -- the "…would like to access files on a removable volume"
  prompt is the expected one, triggered by the first companion/rclone access
  to `/Volumes/<SSD>`.

  Record: the exact wording, which process triggered it, at what moment, and
  that you clicked **Allow**. Also note any Full Disk Access, Files and
  Folders, or Network prompt.

  **Failing looks like:** no prompt at all *and* rclone reporting permission
  errors -- meaning the prompt was consumed by a process the user never saw
  (launchd-started daemons cannot show one). If that happens, the install
  needs a documented "run it once from Terminal" step.

- [ ] **C4. Quarantine is not on the binary.**

  ```bash
  xattr -l ~/.local/ccsync/bin/ccsync-companion   # expect: no output
  file ~/.local/ccsync/bin/ccsync-companion       # Mach-O … arm64
  ```

  **Failing looks like:** `com.apple.quarantine` listed → the strip failed;
  launchd will start it and it will die with no dialog and no log line.

- [ ] **C5. `ismount` agrees with reality.** This is the guard's core
  predicate; check it directly, once:

  ```bash
  python3 -c "import os; print(os.path.ismount('/Volumes/<SSD>'))"   # True
  mount | grep -F "/Volumes/<SSD>"                                    # listed
  ```

- [ ] **C6. Approve and go green.** Send the device ID to the dashboard
  (admin → approve), sign in from the **menu bar** (`Sign in…`), tick a
  project on the dashboard.

  **Success:** the machine appears on the fleet grid with platform `macos`;
  lanes leave `PAUSED`/not-set-up and go green; the dashboard shows progress.

  **Failing looks like:** `folder not configured` / a device that never
  connects → that is the known "regenerated device ID" shape; check the
  server Syncthing's pending devices.

- [ ] **C7. Re-run is a no-op.** Run C2's command again verbatim.

  **Success:** `SKIP:` lines throughout, including `companion already
  installed and identical (sha256 …)` and `companion LaunchAgent already
  present and correct`, and the mapping step saying it was already correct.

---

## D. Resolve mapping

- [ ] **D1. It was set, or it deferred honestly.** From C2's closing block,
  step 6 says exactly one of: `DONE FOR YOU`; `NOT DONE -- Resolve was
  running`; `NOT DONE -- Resolve has never been launched on this Mac`;
  `NOT DONE -- … format`; `SKIPPED`.

  For the deferral paths, do what it says and re-run:

  ```bash
  # quit Resolve completely first (or launch it once and quit, for the
  # never-launched case)
  ./installer/macos_bootstrap.sh --resolve-mapping-only \
      --local-root "/Volumes/<SSD>/Creators_Club"
  ```

  **Success:** `Mapped Mount configured: P:\ -> /Volumes/<SSD>/Creators_Club`
  and, on a second run, `already maps … -- nothing written`.

  **Failing looks like:** exit 5 (`not in the format this installer knows`)
  -- capture both preference files before doing anything else; that is the
  single most valuable artifact this session can produce.

- [ ] **D2. Preferences shows it.** Resolve → Preferences (Cmd+,) → Media
  Storage: your local root listed with `P:\` as its mapped path.

- [ ] **D3. It survives a restart.** Quit Resolve, relaunch, look again.

  **This is the real test of the two-file edit.** If it is gone, `.config.data`
  (the GUI form) did not take and Resolve rebuilt `config.dat` from it --
  exactly the failure the helper exists to avoid. Capture both files.

- [ ] **D4. A `P:\` clip resolves.** Open a timeline whose clips are stored
  as `P:\Projects\...` and confirm they play from the local proxy with no
  relink prompt.

- [ ] **D5. Read the real preference files** -- the questions the code had to
  guess at. Config dir first:

  ```bash
  ls -a ~/Library/Preferences/Blackmagic\ Design/DaVinci\ Resolve/
  # App Store build instead?
  ls -a ~/Library/Containers/com.blackmagic-design.DaVinciResolve/Data/Library/Preferences/Blackmagic\ Design/DaVinci\ Resolve/ 2>/dev/null
  ```

  Then, in that directory:

  - [ ] **Backups exist:** `ls *.ccsync-backup-*` shows a timestamped copy of
    **both** files from the run.
  - [ ] **`.config.data` numbering base:** `grep -n '^IoFs' .config.data`.
    Does it start at `IoFsMount_0` or `_1`? The helper reads the base from
    the file (`min` of the indices found) -- confirm the entry it added
    landed at the right index and that `IoFsNum` equals the number of
    entries.
  - [ ] **`config.dat` numbering base:** `grep -n 'Site\.[0-9]*\.FS\.' config.dat`.
    The helper reads this base from the file too (`min` of the indices found,
    1-based when the block is empty -- matching every sample seen so far).
    Confirm the added entry landed in the file's own base and that Resolve's
    pre-existing entries kept their numbers.
  - [ ] **The `/Volumes` auto-entry:** Resolve appends its own filesystem
    entry for `/Volumes` and expects it **last**. Confirm it is still last in
    `config.dat` after the edit -- and record whether `.config.data` carries
    its own `/Volumes` entry too (the code keeps the trailing entry last in
    both, on the assumption that it does).
  - [ ] **`MacDIO`, not `DIO`:** the new entry should carry `MacDIO = 1` in
    `config.dat` and `IoFsDirectIO_<i> = 1` in `.config.data`. Record what
    Resolve's *own* entries use.
  - [ ] **Nothing else moved:** `diff` the backup against the live file. The
    only differences should be the added entry, the renumbering it forced,
    and the count line. Unknown keys, blank lines, indentation, spacing and
    line-ending style must be untouched.

- [ ] **D6. Read-only verify works with Resolve open.**

  ```bash
  sed -n '/^# ---CCSYNC-MAPPING-HELPER-BEGIN---$/,/^# ---CCSYNC-MAPPING-HELPER-END---$/p' \
      installer/macos_bootstrap.sh > /tmp/ccsync_mapping.py
  python3 /tmp/ccsync_mapping.py verify --local-root "/Volumes/<SSD>/Creators_Club"; echo "exit=$?"
  ```

  **Success:** `Resolve maps P:\ to …`, `exit=0`, with Resolve running.
  (`verify` never writes and never checks whether Resolve is running.)

---

## E. SSD drills

The point of the port. Do these deliberately, in order.

- [ ] **E1. Unplug mid-sync.** Start a real transfer, then physically
  disconnect the SSD (no eject -- that is the realistic case).

  **Success, all of:**
  - a notification: *"Sync paused — your Creators Club drive is
    disconnected."*
  - menu bar icon orange; menu says `PAUSED — drive disconnected`; lane
    detail says `PAUSED: your Creators Club drive is disconnected -- plug it
    back in and syncing resumes on its own`
  - log: `sync paused: local_root … is not available (absent)`
  - **`ls /Volumes` shows no leftover directory for the drive**
  - the boot volume did **not** grow: check `df -h /` before and after.

  **Failing looks like:** lanes continuing; the tray saying "project deleted
  locally" or a mass-deletion figure; **any** new directory appearing under
  `/Volumes`; free space on `/` dropping. Stop the companion immediately and
  record -- that is the failure the whole guard exists to prevent.

- [ ] **E2. Replug.**

  **Success:** within one guard poll -- log `local_root … is back --
  resuming sync`, notification *"Drive reconnected — sync resumed."*, lanes
  resume by themselves, and `~/.ccsync/volume.json` has a fresh mtime
  (`stat -f '%Sm' ~/.ccsync/volume.json`).

  **Failing looks like:** staying paused (check the log for the guard's own
  errors), or requiring a restart of the companion.

- [ ] **E3. Ghost-directory simulation.** With the drive **unplugged**:

  ```bash
  sudo mkdir "/Volumes/<SSD>"
  ```

  **Success:**
  - the companion stays paused (the guard classifies the ghost as `absent`,
    not `present` -- `os.path.isdir` alone would say it is there);
  - re-running the bootstrap **aborts** with the
    `/Volumes/<SSD> IS NOT A MOUNTED VOLUME` banner and the three-step fix;
  - `python3 -c "import os; print(os.path.ismount('/Volumes/<SSD>'))"` →
    `False`.

  Then recover, and confirm the recovery works:

  ```bash
  sudo rmdir "/Volumes/<SSD>"     # refuses if anything real is inside
  # replug
  ```

  **Failing looks like:** the guard reporting `present`, or the bootstrap
  proceeding. Either one means a real editor's sync lands on their internal
  disk.

- [ ] **E4. Numbered remount.** With the ghost directory still in place,
  plug the drive in: macOS should mount it at `/Volumes/<SSD> 1`.

  **Success:** the companion classifies `misplaced` (needs the recorded
  `VolumeUUID` from C2), pauses, logs `the sync drive is mounted somewhere
  other than …`, notifies, and shows the once-per-episode dialog explaining
  eject → delete the leftover folder → replug. Re-running the bootstrap
  aborts with `Your drive is actually mounted at: /Volumes/<SSD> 1`.

  **Failing looks like:** the numbered path being adopted anywhere -- in
  `config.toml`, in `volume.json`, or in Resolve's Mapped Mount. That name
  changes on every replug.

  Then clean up: eject, `sudo rmdir "/Volumes/<SSD>"`, replug, confirm the
  unnumbered mount and an automatic resume.

---

## F. Self-upgrade

- [ ] **F1. Publish a bumped build.** Bump `VERSION` in **both**
  `companion/src/ccsync_companion/config.py` and `companion/pyproject.toml`,
  then `./tools/release_macos.sh --publish --make-current`.

- [ ] **F2. The offer arrives.** Within a report cycle (~60 s) the menu-bar
  menu grows **Update available → vX.Y.Z (install)** and a notification
  appears once.

  **Failing looks like:** no offer → the machine's reported platform is not
  `macos`, or the package is staged rather than current.

- [ ] **F3. Take it.** Menu → **Update now** → confirm.

  **Success, all of:**
  - the swap completes and the new process starts;
  - `~/.ccsync/companion.log` gains `ccsync-companion vX.Y.Z starting` with
    the **new** version;
  - a toast: *Update complete. Now running vX.Y.Z.*;
  - **exactly one** process: `pgrep -fl ccsync-companion` → one PID.

  **Failing looks like:**
  - `Permission denied` / the new binary not executable → the post-verify
    `chmod 0o755` did not run (this was the original macOS upgrade bug);
  - a file named `ccsync-companion.new.exe` anywhere → the platform-derived
    staged name regressed;
  - **two** companions, or the log line `another ccsync-companion is already
    running -- this instance is exiting` followed by no companion at all →
    the `CCSYNC_REPLACES_PID` predecessor wait did not work (posix uses a
    liveness check, and the dying predecessor is alive for a second or two).

- [ ] **F4. `AbandonProcessGroup` held.** The respawn happens while launchd
  is watching the old process exit. Confirm the new process **survived** it
  (it is alive per F3).

  Then record the honest nuance: after a self-upgrade the running companion
  was spawned **detached**, so it is no longer launchd's supervised child.
  Note what
  `launchctl print gui/$(id -u)/com.creatorsclub.ccsync.companion` says while
  the upgraded process is running, and then **log out and back in** and
  confirm exactly **one** companion starts, at the new version.

  **Failing looks like:** the upgraded process dying seconds after the swap
  (the process group was killed with the predecessor -- check the plist still
  contains `AbandonProcessGroup`), or two companions after the next login.

- [ ] **F5. `.old` is cleaned on the next start.** After the restart:

  ```bash
  ls ~/.local/ccsync/bin
  ```

  **Success:** just `ccsync-companion` (plus rclone/syncthing) -- no `.old`,
  no `.new`, and no `.exe` anything.

---

## G. caffeinate

- [ ] **G1. Held while syncing.** With a lane actively transferring:

  ```bash
  pmset -g assertions | grep -i sleep
  pgrep -fl caffeinate
  ```

  **Success:** `PreventUserIdleSystemSleep` is asserted, attributed to
  `caffeinate`, and the process line reads `caffeinate -i -w <companion
  pid>`. **`PreventUserIdleDisplaySleep` must NOT be held** -- the screen
  still blanks on schedule (we never pass `-d`).

  **Failing looks like:** no assertion, with `keep-awake: caffeinate did not
  start -- this Mac may sleep …` in the log.

- [ ] **G2. Released when idle.** Let the lanes go quiet and wait past one
  poll (~30 s), then re-check both commands.

  **Success:** the assertion is gone and no `caffeinate` child remains.

  **Failing looks like:** either surviving. A caffeinate nobody reaps keeps
  the Mac awake indefinitely -- the exact harm the module exists to avoid
  causing. Kill it by hand and file it.

- [ ] **G3. It dies with us.** Kill the companion outright
  (`kill -9 <pid>`); the `caffeinate -w <pid>` child must exit on its own.

---

## H. Uninstall drill

- [ ] **H1. Count the media first.** So "your media was not touched" is a
  measurement, not a hope:

  ```bash
  find "/Volumes/<SSD>/Creators_Club" -type f | wc -l
  du -sh "/Volumes/<SSD>/Creators_Club"
  ```

- [ ] **H2. Dry run.** `./installer/macos_uninstall.sh --dry-run` -- every
  line prefixed `[dry-run]`, nothing changed.

- [ ] **H3. Default uninstall.** `./installer/macos_uninstall.sh`

  **Success:**
  - both LaunchAgents unloaded and deleted:
    `ls ~/Library/LaunchAgents | grep ccsync` → nothing;
    `launchctl list | grep ccsync` → nothing;
  - `~/.local/ccsync` gone;
  - only the `[creators_club_sftp]` stanza removed from
    `~/.config/rclone/rclone.conf` -- **diff it** and confirm any other
    remotes survived;
  - `~/.ccsync` **kept** (config, identity, state);
  - closing lines: Resolve still maps `P:\ → <root>` (with the by-hand
    removal note), Homebrew tools left alone, and the media-untouched line
    naming the real path;
  - H1's file count and size **unchanged**.

  **Failing looks like:** any process left running from `~/.local/ccsync`;
  a personal (non-CCSync) Syncthing having been stopped -- it filters by
  executable path, so record the `ps -p <pid> -o comm=` output if it did.

- [ ] **H4. `--full`.** Reinstall (C2), then
  `./installer/macos_uninstall.sh --full`.

  **Success:** `~/.ccsync` is emptied **except `state/`** (the
  already-answered prompts survive on purpose); the SSH key in `~/.ssh` is
  left in place with a note; the warning about needing re-approval appears;
  media still untouched.

- [ ] **H5. Reinstall from scratch.** Confirm the Mac comes back with a
  **new** Syncthing device ID needing approval, and that everything above
  still holds on a clean machine.

---

## Closing out the session

Write up, in the repo:

1. **Answers to B1/B2/B3/B4** -- they gate design work, not just bugs.
2. **Everything from D5** -- the real shapes of Resolve's two preference
   files are the thing this whole port had to guess at.
3. Every defect, with the command and the output.
4. Then update the status lines that currently say *"pending first real-Mac
   validation"*: `KNOWN_BUGS.md` item 8, `installer/README.md`'s macOS status
   block, and the banner comments at the top of `macos_bootstrap.sh`,
   `macos_uninstall.sh` and the embedded mapping helper's docstring.

Until those are updated, the honest description of macOS remains
**code-complete, unvalidated**.
