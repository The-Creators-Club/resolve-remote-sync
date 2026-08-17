# macOS first-run findings — 2026-08-04 (session 1, partial)

> **Archive.** Kept as history; the addresses, hostnames and people in it are
> those of the original deployment. Do not copy commands out of it.

Record of the first time any of the macOS port has run on a Mac, against the
checklist in `installer/MACOS_FIRST_RUN.md`.

**Scope reached: A1–A6 only.** The build now exists and is signed. Nothing was
installed, nothing was published, and no macOS *runtime* path has executed —
`diskutil`, `launchctl`, `xattr`, the Resolve preference edit, `caffeinate`,
the root guard and the self-upgrade swap are all still unexercised. Sections
A7–H were not attempted.

**The honest status of macOS is unchanged: code-complete, unvalidated.** One
build succeeding is not validation. Do not update KNOWN_BUGS.md item 8, the
`installer/README.md` status block, or the banner comments in
`macos_bootstrap.sh` / `macos_uninstall.sh` on the strength of this session.

The one thing that did change: **`tools/release_macos.sh` produces a correct
binary**, and the single defect that stopped it (MAC-1) is understood.

---

## The machine

| | |
|---|---|
| Hardware / OS | Apple silicon (arm64), macOS 15.7.4 (24G517) |
| Repo | `<mac-checkout>` @ `0f5d99d`, clean at session start |
| Line endings | `installer/*.sh`, `tools/release_macos.sh` all checked out LF — `.gitattributes` worked, A2 passes |
| Resolve | 21.0.0, direct build (not App Store — prefs are in `~/Library/Preferences/…`, not a sandbox container) |
| Tailscale | installed, up; `nas` (100.65.15.123) reachable direct |

**Python had to be installed before A3 could run.** The Mac had python.org
3.11.0 only, below the `requires-python = ">=3.12"` floor. Per A1's allowance
of "a uv-managed 3.12", installed `uv` 0.12.1 → CPython **3.12.13** and
symlinked `~/.local/bin/python3` at it (`~/.local/bin` is first on PATH via
`.zshrc`). Homebrew is not installed on this machine and was not used
anywhere. The 3.11 install is untouched.

**Prior partial bootstrap.** Something ran `macos_bootstrap.sh` here at
13:43–13:44 on 2026-08-04, before this session, and left: `rclone` +
`syncthing` in `~/.local/ccsync/bin`, an `~/.config/rclone/rclone.conf`
stanza, an `~/.ssh/ccsync_ed25519` keypair, a seeded `~/.ccsync/config.toml`,
an empty `~/Creators_Club`, and a Syncthing LaunchAgent that **is not
loaded** (`launchctl list` shows nothing). The companion itself was never
installed — consistent with there being no published `macos` package to
download. Section C should be run on a clean machine, or this state
deliberately accounted for, before its results mean anything.

---

## MAC-1. UTF-8 BOM in `companion/pyproject.toml` breaks every clean build — CRITICAL [verified]

- **Where:** `companion/pyproject.toml:1` — file begins `ef bb bf`.
- **Defect:** Python's `tomllib` rejects a leading BOM. `pip install -e .`
  therefore dies in `pip/_internal/pyproject.py` → `load_pyproject_toml` with
  `tomllib.TOMLDecodeError: Invalid statement (at line 1, column 1)`.
- **Failure:** `tools/release_macos.sh` aborts at step 3/6 with
  `pip install failed -- nothing was built`. There is no macOS binary and no
  way to get one. Reproduced twice; a from-scratch venv fails 100% of the time.
- **Why Windows never caught it:** `tools/release.ps1` does not install the
  package. `Get-VenvPython` (`tools/release.ps1:133`) *reuses* a pre-existing
  `companion\.venv` and only falls back to `python` on PATH. The base rig's
  venv predates the BOM, so the file is never parsed by a build. Nothing on
  Windows exercises a clean editable install; `release_macos.sh:269` is the
  first thing in this repo that does.
- **Status: NOT COMMITTED.** The three BOM bytes were stripped in the working
  tree to get past it, and that strip is the only uncommitted change in the
  repo. It is deliberately left uncommitted pending review. **The committed
  tree at `0f5d99d` still cannot build on a clean machine.**
- **Fix hint:** strip the BOM and commit. Worth a guard so it cannot come
  back: a test that `tomllib.load`s every `pyproject.toml` in the repo, and/or
  a `.gitattributes` entry. Note the same Windows-editor origin left a BOM on
  `companion/tests/test_config.py` too — harmless there (Python decodes
  `utf-8-sig` source) but the same cause.

---

## MAC-2. The companion suite is not green on macOS: 18 failed, 2 errors, 39 skipped — EXPECTED, RECORDED

`1492 passed, 39 skipped, 18 failed, 2 errors in 26.74s` under Python
3.12.13. A3 anticipated exactly this, so per its instruction nothing was
patched and the build was taken with `--skip-tests` (manifest honestly
records `tests_run: false`).

Every failure was triaged. **Most are the tests' own platform assumptions,
not product defects** — but see MAC-3, which is not.

### 2a. Windows-only code paths with no posix skip

The test fakes the platform, then a real posix API refuses to play along.

```
tests/test_paths.py::test_delooped_translates_localhost_share
tests/test_resolve_bridge.py::test_pin_frozen_python3_home_sets_env_when_bundled
tests/test_upgrade.py::test_the_replaced_pid_is_set_on_windows_too
tests/test_watcher.py::test_poll_once_warns_when_the_subst_never_ran
tests/test_watcher.py::test_mapping_warning_re_arms_after_the_mapping_is_fixed
```

`test_the_replaced_pid_is_set_on_windows_too` is the clearest example: the
`windows` fixture fakes `sys.platform`, so `UpgradeManager._default_spawn`
(`upgrade.py:698`) enters its win32 branch and hits
`AttributeError: module 'subprocess' has no attribute 'DETACHED_PROCESS'` —
those constants do not exist in macOS's `subprocess`. Faking the platform is
not enough when the branch touches platform-only attributes.

### 2b. Expectations built with `os.path.join` — the product is right, the test is wrong

```
tests/test_canon.py::test_canonical_translates_on_windows_too
tests/test_canon.py::test_local_to_canonical_on_windows_matches_the_old_join
tests/test_fixer.py::test_canonical_clip_path_translates_local_root_to_prefix
tests/test_fixer.py::test_fix_clip_relinks_to_canonical_path_not_physical
```

These assert against `"P:\\" + os.path.join(...)`, which is backslashes on
Windows and forward slashes on macOS. `fixer.canonical_clip_path` returned
`P:\B-roll\clip.mov` — **the correct, portable, backslash spelling SPEC.md
flaw-7 requires** — and the test demanded `P:\B-roll/clip.mov`. Fixing these
means hardcoding the backslash expectation, never re-deriving it from the
host. The two `test_canon` cases are the mirror image: they pass a Windows
`local_root` (`F:\Creators_Club`) and expect a Windows-joined *local* path,
which is not a situation that can occur on a Mac.

### 2c. Case-insensitive path assumptions — see MAC-3

```
tests/test_app.py::test_subpath_containment_helper
tests/test_consolidate.py::test_plan_dedupes_and_sizes
tests/test_consolidate.py::test_run_consolidation_publishes_rich_progress_and_can_stop
tests/test_fixer.py::test_ignore_tracker_is_ignored_and_normalizes_case_on_windows
tests/test_popup.py::test_build_popup_rows_falls_back_to_basename_for_clip_name
tests/test_popup.py::test_dedupe_collapses_same_path_different_case_and_slashes
tests/test_popup.py::test_build_popup_rows_always_dedupes_before_building
tests/test_popup.py::test_perform_fix_all_passes_all_grouped_media_pool_items_to_fix_clip
```

These look like platform assumptions and are partly that, but they sit on top
of a real product gap. Do not silence them without reading MAC-3 first.

### 2d. What skipped — all 39, by cause

A skip is not a pass, and on a first port the skip list is as informative as
the failure list. Captured with `pytest -q -rsEf`.

| Count | Where | Reason given |
|---|---|---|
| **24** | `test_rclone_filters.py` (23), `test_rclone_orphans.py` (1) | `rclone not found on PATH or at companion/.tools/rclone.exe` — **see MAC-4, since resolved** |
| 7 | `test_shutdown_guard.py:550,556,569,647,664,854,1383` | `Windows-only guard` ×2, `needs a real HWND` ×2, `needs a real window class` ×2, `AppKit may genuinely be importable here` ×1 |
| 4 | `test_app.py:1772,1800,1820,1840` | `windows-only feature` |
| 2 | `test_canon.py:161,210` | `drive-rooted local_root is a Windows shape`, `P:\ as local_root is the Windows base rig` |
| 1 | `test_tray.py:671` | `pystray win32 backend only` |
| 1 | `test_upgrade.py:871` | `Windows-only creation flags` |

The 15 non-rclone skips are all legitimate and correctly gated — Windows-only
guards, real Win32 handles, Windows-shaped paths. Notably
`test_shutdown_guard.py:1383` skips with `AppKit may genuinely be importable
here`, which is the suite correctly anticipating a real Mac; compare the
darwin-guard *failure* in 2c, where the same assumption was left implicit and
therefore broke.

### 2e. The 2 errors: a fixture gap opened by the macOS UI dispatcher

```
tests/test_app.py::test_run_tray_start_non_import_error_still_runs_shutdown
tests/test_app.py::test_run_on_windows_starts_no_dispatcher_and_keeps_its_wait_loop
```

Both tripped `conftest._no_real_tk_windows` (`tests/conftest.py:111`), the
guard that fails a test which tries to open a real Tk window. Cause:
`app.run()` now calls `ui_dispatch.start()` (`app.py:3008`) →
`_make_root()` (`ui_dispatch.py:177`) → `tkinter.Tk()`. That call was added
by 99c4931 (*Companion: main-thread UI dispatcher for macOS*). On Windows the
dispatcher never starts, so these tests never needed to inject a fake root;
on macOS they do. Fix by injecting a fake root factory, not by weakening the
guard — that guard exists because a real dialog once got mistaken for a live
bug for a day.

**Sub-finding, worth its own look:** the second test's whole point is that no
dispatcher starts on Windows, and the dispatcher started anyway. Its platform
fake is not reaching `ui_dispatch.start()`. Either the fake is applied too
late or `start()` reads the platform somewhere the fake does not cover — so
this test currently proves nothing about the Windows path either.

---

## MAC-3. `_norm_path` uses posix semantics on canonical `P:\` strings — REAL, gated on B2 [verified by reading]

- **Where:** `resolve_bridge.py::_norm_path` —
  `os.path.normcase(os.path.normpath(str(p)))`. Consumers:
  `popup.dedupe_out_of_tree_items`, `fixer.IgnoreTracker.is_ignored/ignore`,
  and the consolidate planner. Same family: `popup.py:281` and `popup.py:457`
  use `os.path.basename(path)`.
- **Defect:** `canon.py` correctly imports `ntpath` and handles canonical
  strings with it whatever the host is (SPEC.md path-canon paragraph).
  `_norm_path` does not — it uses `os.path`, which on macOS is `posixpath`,
  where `normcase` is a no-op and `\` is an ordinary filename character.
- **Failure (if Resolve on macOS returns stored `P:\…` spellings):**
  - `os.path.basename(r"P:\Desktop\track.wav")` returns the **entire string**,
    so any popup row whose `clip_name` is absent displays a full path where a
    filename belongs.
  - `dedupe_out_of_tree_items` stops collapsing anything, because its key no
    longer normalizes. Its own docstring records what that dedupe prevents:
    duplicate rows, and the garbage-collected-`StringVar` bug that leaves a
    still-visible Combobox bound to an unset Tcl variable, i.e. a blank
    dropdown.
  - `IgnoreTracker` degrades to exact-string matching (low impact — Resolve is
    likely to return a consistent spelling — but it is no longer the
    documented case-insensitive behaviour).
- **This is conditional on B2 and cannot be resolved before it.** If Resolve
  hands back Mapped-Mount-resolved local paths (`/Volumes/…`), `os.path` is
  the right module and there is no bug. If it hands back the stored `P:\`
  strings — which is what SPEC.md's path-canon design expects, since the DB
  stores canonical paths and the Mapped Mount resolves them inside Resolve —
  then every consumer of `_norm_path` is mis-parsing on every Mac.
- **Fix hint:** if B2 says canonical, `_norm_path` and the `basename` calls
  need the same `ntpath`-whatever-the-host treatment `canon.py` already
  applies, and the 2c tests then become correct as written rather than
  needing platform-conditioning. **Answer B2 first.**

---

## MAC-4. The rclone test gate looks for a Windows filename, so 24 lane-filter tests can never run on macOS — MAJOR [verified, and the coverage recovered]

- **Where:** `companion/tests/conftest.py::_find_rclone` (~:152-158) and the
  `rclone_binary` fixture (~:173-178).
- **Defect:** the gate tries `shutil.which("rclone")`, then falls back to
  `COMPANION_ROOT / ".tools" / "rclone.exe"` — a hardcoded **Windows**
  filename. On macOS the fallback can never match (the binary is `rclone`,
  no extension), so unless rclone happens to be on PATH the fixture skips.
  The companion's own installed rclone lives at
  `~/.local/ccsync/bin/rclone` and is deliberately **not** on PATH — that is
  the whole point of the `rclone_path` config key and the INST-7 comment in
  `config.toml`. So the default state of a correctly-installed Mac is
  "24 tests silently skipped".
- **Why it matters:** these are the tests that shell out to a **real** rclone
  to check `--filter` semantics — the rules deciding that lane A carries video
  originals *up only* and lane B carries `**/Proxy/**` *down only*. Getting
  those backwards is the most destructive failure mode in the system. The
  fixture's own docstring says these exist to "invoke rclone rather than being
  permanently skipped", which is exactly what was happening. `pytest` exits 0
  either way: a false green, on the safety-critical path, on every Mac.
- **The coverage was recovered, and it is good news.** Re-run with the
  installed rclone put on PATH:

  ```
  PATH="$HOME/.local/ccsync/bin:$PATH" .venv/bin/python -m pytest -q \
      tests/test_rclone_filters.py tests/test_rclone_orphans.py
  → 81 passed in 31.29s     (rclone v1.75.0, darwin 15.7.4, arm64)
  ```

  **All 24 previously-skipped tests pass on macOS against real rclone.** The
  lane filter semantics hold on this platform. That is a genuine, if narrow,
  piece of macOS validation — and it was invisible until the gate was worked
  around.
- **Fix hint:** make the fallback platform-aware (`rclone.exe` on Windows,
  `rclone` elsewhere) and also consult `~/.local/ccsync/bin/rclone` — the path
  the macOS installer actually uses. Consider making the whole thing fail
  rather than skip in CI/release contexts: `release_macos.sh` treats a green
  suite as permission to build, and 24 silent skips on the lane-direction
  tests is not the assurance that gate is assumed to give.

---

## MAC-5. The activation-policy call ran before Tk, so the companion aborted at startup on every Mac — CRITICAL [fixed]

Found in **session 2** (same day), on the first attempt at **A7**. The
companion died instantly, `zsh: abort`, with nothing after `config OK` in
`~/.ccsync/companion.log`.

- **Where:** `app.py` — `_set_darwin_activation_policy()` was called at the
  top of `run()`, above the `starting` log line and ~40 lines before
  `ui_dispatch.start()`.
- **Defect:** `NSApp` is a singleton whose **class is fixed by its first
  caller**. That helper calls `AppKit.NSApplication.sharedApplication()`,
  creating a plain `NSApplication`. Tk-Aqua expects to install its own
  subclass (`TKApplication`) and then sends it selectors only that subclass
  implements, so `tkinter.Tk()` died in the ObjC runtime during its first
  colour lookup:

  ```
  *** Terminating app due to uncaught exception 'NSInvalidArgumentException',
      reason: '-[NSApplication macOSVersion]: unrecognized selector sent to instance'
      … GetRGBA → TkpGetColor → Tk_GetColor → Tk_Get3DBorder → Tk_InitOptions
        → TkCreateFrame → Tkapp_New → _tkinter_create
  libc++abi: terminating due to uncaught exception of type NSException
  ```

- **Why no Python handler helped:** an uncaught `NSException` aborts the
  process via `libc++abi`. The `try/except Exception` wrapped around
  `ui_dispatch.start()` never sees it, and there is no Python traceback —
  just a stack of C frames and a dead binary. On a real editor's Mac this is
  a companion that starts, writes four normal log lines, and disappears.
- **Confirmed by A/B**, companion venv, macOS 15.7.4 / Tcl-Tk **9.0**:

  | order | result |
  |---|---|
  | `sharedApplication()` → `tkinter.Tk()` | **abort** (the trace above) |
  | `tkinter.Tk()` → `sharedApplication()` | **`B survived`** |

- **Fix:** the call moved below `ui_dispatch.start()`, with the reasoning
  inline and a `test_app.py` ordering regression test
  (`test_run_sets_the_activation_policy_only_after_the_tk_root_exists`).
  Once Tk owns `NSApp`, `sharedApplication()` returns the `TKApplication` —
  an `NSApplication` subclass — so the policy still applies.
  `shutdown_guard`'s AppKit half was already safe: it starts from
  `self.start()`, after the root exists.
- **⚠️ The published macOS companion 0.4.20 has this bug and cannot start.**
  It is `current` for the `macos` package. Nothing has taken it (no Mac has
  the companion installed yet), but it must be superseded before any Mac
  installs — bump `VERSION` and publish the fix.
- **Cheap generalisation, not yet done:** anything that touches `AppKit`
  before the Tk root now has this failure mode. There are exactly two
  callers today and both are correct; a third would be silent until someone
  runs it on a Mac.

---

## Observations (not defects)

- **pyobjc/AppKit is genuinely available in the venv and the darwin guard does
  install itself.** `test_shutdown_guard.py::test_the_darwin_guard_survives_a_start_stop_with_every_seam_defaulted`
  failed with `guard.active is True` where it expected `False`; the test's
  docstring assumes "no AppKit (so no delegate)", which is false on a real Mac
  with `pyobjc-framework-Cocoa` installed. Early partial evidence for **B4** —
  the delegate half is reachable — but it says nothing yet about which quit
  routes actually call `applicationShouldTerminate_`, which still needs the
  live test.
- **Tcl/Tk 9.0, and PyInstaller handles it.** The uv-managed 3.12.13 ships
  Tcl/Tk **9.0**, not the 8.6 that A1's warning implicitly assumes. Verified
  before building the companion: a `--onefile` PyInstaller build of a minimal
  tkinter app under this interpreter opened a real Tk window and exited
  cleanly (PyInstaller 6.21.0). So the A1 hazard is not present here. This
  does **not** pre-answer **B1** — coexistence with pystray's AppKit run loop
  is a different question from Tk collection working at all.
- **PyInstaller rewrote the macOS SDK version** on the output —
  `Rewriting the executable's macOS SDK version (26.2.0) to match the SDK
  version of the Python library (15.5.0)`. Informational, but record it if
  anything downstream behaves oddly.

### Partial answer to D5, read-only, before any mapping edit was attempted

Read from this Mac's live preference files. **The mapping helper has not been
run**, so this is Resolve's own untouched shape and is the closest thing this
session produced to what D5 asks for:

- `config.dat` — `Site.1.FS.Count = 2`, entries at `Site.1.FS.1`
  (`~/Movies`) and `Site.1.FS.2` (`/Volumes`). **1-based**, all
  `MappedRoot` blank, `MacDIO = 1` on both, and the `/Volumes` auto-entry is
  last, as the code expects.
- `.config.data` — `IoFsNum = 1`, `IoFsMount_1 = <home>/Movies`,
  `IoFsMappedMount_1` blank, `IoFsDirectIO_1 = 1`. **1-based.**
- **⚠️ The two files disagree, and the code's assumption is the wrong way
  round.** `.config.data` carries **no `/Volumes` entry at all** — only
  `config.dat` has one. `installer/MACOS_FIRST_RUN.md` D5 states the helper
  "keeps the trailing entry last in both, on the assumption that it does"
  carry one. On this machine that assumption is false. **Verify what the
  helper does with a `.config.data` whose last entry is a real media path
  before running it in write mode**, and diff both backups afterwards.
- **`.config.data` is owned by `root`** (`-rw-rw-rw- root staff`), while
  `config.dat` is owned by the local user. Mode 666 means the helper can write
  it, but an atomic write-temp-then-rename will leave the replacement owned by
  that user. Probably harmless — Resolve runs as them — but it is a change to the file's
  ownership that nothing in the design anticipated, and it is not reversible
  by re-running the helper.

---

## The build that came out

Produced with `--allow-dirty --skip-tests` (both accurately reflected in the
manifest). A4, A5 and A6 all pass.

```
companion/dist/ccsync-companion
  Mach-O 64-bit executable arm64      (thin — not universal, not x86_64)
  Signature=adhoc                     (A4)
  no com.apple.quarantine xattr
  sha256 c0fcc048912c7a4c2e39d278ca888944e0f8f80206e968313e0b5378c49009c6
  20954128 bytes
```

Manifest fields are all populated — `built_by <user>@<mac-hostname>`,
real `artifact_mtime`, `arch arm64`, `platform macos` — so A6's GNU-coreutils
trap did not fire: `stat -f%z`, `date -u -r` and `hostname -s` all resolve to
the BSD spellings on this machine.

Stamped `0.4.20+dirty` / `git_commit 0f5d99d-dirty` because of the
still-uncommitted MAC-1 strip, and `tests_run: false`. **This artifact must
not be published.** It is a development build of an unvalidated port, built
from a tree that differs from any commit, with the suite skipped.

---

## Still unanswered

Everything below was not attempted. Listed so the gap is not mistaken for a
pass.

| Checklist | Status |
|---|---|
| A7 menu-bar smoke run | **attempted, crashed** — MAC-5; fixed, needs a rebuild and a retry |
| A8 publish | not run, deliberately |
| B1 Tk dialogs vs pystray's AppKit loop | **open** — gates Batch-3 UI design |
| B2 Resolve bridge binding + clip-path spelling | **open** — also gates MAC-3 |
| B3 SIGTERM reaching the shutdown guard | **open** |
| B4 which quit routes reach `applicationShouldTerminate_` | **open** (partial: delegate is reachable) |
| C1–C7 install drill, TCC prompts, quarantine strip | not run |
| D1–D6 Resolve mapping write + survival across restart | not run (D5 partially answered read-only, above) |
| E1–E4 SSD unplug / ghost dir / numbered remount | not run — **the point of the port** |
| F1–F5 self-upgrade | not run |
| G1–G3 caffeinate | not run |
| H1–H5 uninstall | not run |

**Blocking the install drill:** sections C and F need a published `macos`
package (A8), and E needs an external SSD as the sync root. The current
`~/.ccsync/config.toml` has `local_root = ~/Creators_Club` — the
internal disk — which makes the entire external-SSD root guard inert. The one
external volume present (`/Volumes/<external-ssd>`) is **ExFAT** and already holds
unrelated project material; ExFAT has no POSIX permissions or symlinks and is
a poor fit for a sync root, so the SSD drills need a decision about which
drive and which filesystem before they can mean anything.
