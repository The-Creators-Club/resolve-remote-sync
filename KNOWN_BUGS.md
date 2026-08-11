# Known bugs

**Status 2026-08-03: every bug in the 2026-08 six-agent hunt (B1–B26 plus all listed
minors) has a fix in the working tree**, applied by an eight-agent fix fleet and verified
suite-by-suite. All five test suites are green:

| Suite | Result (final, after the follow-up pass) |
|---|---|
| companion | 1252 passed |
| dashboard | 350 passed, 1 skipped (opt-in b-roll checkout gate) |
| server | 157 passed under system python; 156 + 1 skip under dashboard/.venv (no paramiko there) |
| onboarding | 139 passed (run under companion/.venv — onboarding/.venv lacks pytest) |
| bench | 157 passed, 1 skipped (iperf3 not on PATH) |

*Counts as of 2026-08-05, on macOS:* companion **1586 passed, 18 skipped** (grew with
the MAC-6/7/9 regression tests); onboarding **197 passed, 18 failed** — the failures are
Windows-shaped tests running unguarded on darwin, see item 15. dashboard/server/bench
unchanged and not re-run here (no fastapi/paramiko in the Mac venv).

**Status 2026-08-06: a six-agent fix pass closed every open item fixable from the base
rig** — items 9, 10, 12, 14 and 15, plus the code follow-ups inside items 0, 16, 17, 18
and 19. All five suites green on Windows: companion **1796 passed**, onboarding **222
passed**, dashboard **369 + 1 skip**, server **161 + 1 skip** (dashboard/.venv), bench
**157 + 1 skip**. Still open and needing something other than this machine: MAC-12's
wedged FSEvents stream (someone at Leso's Mac), item 1's Syncthing 1.x live-verify,
item 16's stable code-signing identity, the `._*` sweep of the NAS tree (item 12
residual), and the macOS runtime-validation checklist — including one watched Mac build
of the now-onedir wizard (item 9) and a darwin run of the re-guarded onboarding suite
(item 15).

The original worklist (file:line, failure scenarios, fix hints) is archived verbatim at
`docs/bug-hunt-2026-08.md`. Summary of what was done, then the follow-ups that remain.

## Fixed

- **B1–B4 + b-roll minors (fix-forward, feature kept):** installer ships the
  `broll-platform/web` checkout into `broll-web` via the staged→verify→atomic-swap path
  and refuses to run without it while `broll_enabled=1`; the *mounted* archive path is
  prepared `broll:editors 2770` (unused `broll-data` removed); a blank/placeholder/weak
  `BROLL_INGEST_TOKEN` refuses to build the app, and a `BrollGate` ASGI wrapper re-checks
  the token on every ingest request (and 404s `/broll/docs`), so upstream's dev-mode-open
  guard is unreachable; tests are portable (fake `app.main`, one opt-in real-checkout
  test gated on `BROLL_WEB_SRC`); `mount_broll` is tri-state and a degraded mount is
  never advertised; volumes drift test added.
- **B5/B14 + sequencer minors:** a failed `set_ignores` now leaves the folder paused
  (`_ignores_unconfirmed` latch on both sequencer and admin, gating every unpause sweep);
  `pending_folders()` failures fail closed; null slugs rejected; bookkeeping pruned; the
  fake admin now mirrors the real accept ordering, and the tests that enshrined the bugs
  are rewritten and mutation-verified.
- **B6:** companion prioritizes (selected-first, recency) and caps projects at 64 before
  walking, and sheds payload sections least-valuable-first against a 7 MiB budget; the
  dashboard truncates instead of 422-ing, logs and echoes the truncation. The base rig
  can no longer drop off the grid.
- **B7/B20/B21/B22 + onboarding minors:** exit 3 is the only capability-suppressed exit;
  install dispatch keys on the verified role; the P: guard parses `subst`+`net use` at
  user integrity and treats "can't tell" as foreign (verified live on the base rig);
  base worker pre-flights the companion exe before clean-slate; tokens moved off argv
  (env var / `curl -K -`); `finalize_config_identity` wired in; bare-drive-root and
  homes-root guards; PATH `REG_EXPAND_SZ` preserved; macOS staging via `mktemp`.
- **B8–B11 + companion-runtime minors:** logger name fixed plus a package-wide test that
  no logger escapes `"ccsync"`; keep-awake/shutdown-block requires fresh progress
  (180 s), no known-disconnected peer, and an 8 h max hold; the login gate now covers
  Pause→Resume (both legacy *and* managed paths); `copy_diagnostics` and consolidate
  respect `_popup_active_lock`; popup-queue stranding, shutdown re-entrancy, tray text,
  progress-bar inflation, window-class lifetime, dead-pump restartability, `size_bytes`
  all fixed. Note: the `config.example.toml` "drift" entry in the hunt was stale — keys
  were present by design; drift tests strengthened instead.
- **B12:** identical `.partial` ignore patterns in all three `.stignore` builders, plus
  `server/tests/test_cross_component.py` locking builder/`VIDEO_EXTS`/`slugify`/marker
  parity across components.
- **B13 + rclone_lane minors:** spawn is check-stop→spawn→publish-handle inside one
  critical section on both express and periodic paths; busy-requeue keeps `first_seen`
  and honours the batch cap; case-insensitive `Projects` with canonical rel casing;
  stop-vs-debounce race closed; stderr reader join bounded (30 s) with an abandon flag.
  Follow-up: live transfer rows now carry `project_slug` (marker-derived, omitted when
  unknown, length-capped sender-side).
- **B15:** `/api/v1/report` streams through a bounded buffer regardless of
  Content-Length, and the token is checked before the body is read or parsed.
- **B16:** an editor username must be a *known account* (new `known_editors` table,
  recorded on verified report/user-create/device-approve), not merely username-shaped;
  unknown names are warned and left alone; the enforce brake counts (folder, device)
  removals, not devices.
- **B17:** `transport_health` (+ orphan/express counters) accepted, persisted
  (schema v13, COALESCE across light ticks), and rendered as chips on the fleet grid.
- **B18:** companion reads `detail` (falls back to `error`), 403 mapped to the
  actionable text; the test pinning the wrong contract fixed; onboarding inherits via
  the shared helper.
- **B19:** WAN puller tuning included in the server script's folder object (create and
  `--force`) and repaired by a collector drift pass; a cross-file test greps the two
  copies against each other.
- **B23/B24 + ship minors:** `build_editor_package.ps1` exits 1 on missing/locked/stale
  artifacts (verified live with a locked destination exe); `install_syncthing_app.py`
  uses full-list-then-filter; zero-byte `last_version.txt` handled; uninstall sweeps
  `CCSync-OneShot-*`.
- **B25/B26 + bench minors:** sync completion requires the global index
  (`globalBytes >= expected`) and an untimed peer-connection wait (verified live against
  a real Syncthing); flags emit on key-presence so `--multi-thread-streams 0` prints;
  short-transfer guard, secret redaction, iperf3 cleanup/`--lanes` filtering,
  cached-combo cleanup, loud rejection of `direction="bidirectional"`.
- **Cross-component minors:** `report_token` from `/api/v1/verify` now adopted at
  sign-in end-to-end; device IDs validated on the dashboard side too; dashboard version
  drift fixed (0.3.5) with a test; duplicate-path folder creation refused by the
  collector; `install_dashboard_app.py` backup prune is newline-delimited (space-safe)
  and `retire_old_venv` failures now abort the install.
- **rcta/** deleted (contents verified against the hunt's description first); its
  `.gitignore` entry removed.

## Remaining / follow-ups

0. **MAC-12 (open, 2026-08-05): the companion hangs at startup with lane A's file
   watcher blocked in `open()` on the external SSD.** On Leso's Mac the companion now
   stops dead immediately after the `lane_a_video_up: managed mode` log line — no
   timeline watcher, no tray, no sequencer. `sample` shows the watchdog thread in
   `watchdog_add_watch → FSEventStreamCreate → watch_path → open()`, blocked in the
   kernel for 100% of samples **while holding the GIL**, which is why every other thread
   (main included) sits in `take_gil` and the process looks alive but does nothing.

   **Not a regression from 0.5.0**: 0.4.23, rebuilt from its own commit and ad-hoc
   re-signed, hangs at exactly the same point. It is the FSEvents watch on
   `/Volumes/SAMDISK/Creators_Club` (exFAT, `ifree 0`); the same binary starts fully
   (watcher + tray + UI dispatch) against a `/tmp` root on the internal APFS disk.
   It began after the companion was stopped and restarted several times in one session
   — most likely a wedged FSEvents stream on that volume, which needs the SSD
   remounted or the Mac rebooted. **Needs someone at the machine.**

   Two things this exposed that are worth fixing regardless:
   - a blocking `open()` in the watchdog can freeze the entire companion, because it
     holds the GIL. Lane A's observer start deserves a watchdog-of-the-watchdog, or at
     minimum to run somewhere its blocking cannot take the tray and the sign-in UI with
     it.
   - replacing the binary by hand (`cp`) invalidates its ad-hoc signature and launchd
     then refuses to spawn it with `OS_REASON_CODESIGNING` — silently, with nothing in
     the companion log. Any hand-install must `codesign --force --sign -` afterwards;
     the self-upgrade path already does the right thing and should be preferred.

   **UPDATE 2026-08-06: the first bullet is FIXED in the working tree.**
   `RcloneLane._start_watchdog()` now pre-flights the root with a short-lived
   subprocess probe (`probe_watch_root()`, 5 s bound, kill-without-blocking — a
   `subprocess.run(timeout=)` would sit in its post-kill `communicate()` against an
   unkillable child, the very hang being avoided) before any `Observer()` exists. A
   root whose filesystem does not answer opens gets **no watcher**: an ERROR naming
   the condition ("disconnect and reconnect the drive, or restart the computer"), one
   tray toast, and a 60 s → 900 s backoff retry that recovers on remount without a
   restart — tray, sign-in and the sequencer's scheduled uploads all stay alive.
   Frozen builds probe via `/bin/ls` / `cmd /c dir` (`sys.executable` is the companion
   there); source runs use a minimal `-c` snippet. 21 tests in
   `companion/tests/test_watch_probe.py`, including real-subprocess probes. The wedged
   stream on Leso's SSD itself still **needs someone at the machine** (remount or
   reboot); the second bullet stays a hand-install rule, not code.

1. **Bench Syncthing v1/v2 — RESOLVED 2026-08-03:** the runner auto-detects the major
   version (cached probe) and uses the right CLI shape for 1.x and 2.x; unsupported
   versions produce a skipped row, never a fake measurement; v2 instances are pinned to
   `--data` inside the run workspace so they can't touch the machine's real Syncthing
   state. Live-verified on 2.1.2 (real runs + selftest green). Residual: the v1 argv is
   test-pinned to the previously-working shape but not live-verified (no 1.x binary
   here) — confirm once on a 1.x machine.
2. **Restart window — RESOLVED 2026-08-03:** startup (and pause→resume) now verifies
   each selected folder's ignores via `GET /rest/db/ignores` before any unpause,
   latching folders whose ignores are missing/incomplete/unreadable (fail-closed) until
   the per-turn re-assert confirms a successful write. Rollout note: the first launch
   after this upgrade logs one WARNING per folder fleet-wide (existing `.stignore`
   files lack the new `.partial` pair) and self-heals on each folder's first turn.
3. **Dry-run secret leak — RESOLVED 2026-08-03:** all five secret-bearing compose values
   (`SYNCTHING_API_KEY`, `DASH_REPORT_TOKEN`, `DASH_SESSION_SECRET`,
   `BROLL_INGEST_TOKEN`, `TRUENAS_PW`) are masked through one
   `resolve_compose_secrets()` chokepoint, strictly *after* validation (the mask string
   would itself pass the weak-token check). Set-vs-unset still visible; tests guard
   against future compose keys being added unmasked.
4. **Folder-ID derivation — RESOLVED 2026-08-03:** `setup_syncthing_folder.py` resolves
   the id as `--slug` > marker slug (read over SSH, shared parser, validated) >
   `slugify(rel)` only when the marker is truly absent; unreadable/malformed markers
   refuse rather than guess, and a duplicate-path guard refuses a second folder over an
   already-served directory (on create *and* `--force`). Live-validated: all 5 real
   Syncthing folders resolve to their marker slugs.
5. **Posture decisions (settled 2026-08-03):** (a) the CORE-M13 reversal is KEPT —
   consolidate holds `_popup_active_lock` through the long copy; holding a live Tk root
   with the lock released was the exact hazard the lock prevents, and losing batches now
   queue and drain. (b) B9 liveness thresholds were promoted to config keys
   (`keep_awake_stale_seconds` / `keep_awake_max_hold_seconds`, defaults unchanged) —
   done, in `config.py` and `config.example.toml`.
6. **`INSTALLER_VERSION` — RESOLVED 2026-08-03:** bumped to 1.0.15 in both
   `steps.py` and `windows_bootstrap.ps1` (the token-over-environment contract);
   verified against `build_editor_package.ps1`'s drift-gate patterns, and the test
   fixture now interpolates the version so it can't go stale.
7. **b-roll archive posture on the NAS — VERIFIED LIVE 2026-08-03:** the mounted path
   already exists and is populated; the whole tree carries inherited NFSv4 ACLs giving
   `user:broll` and `group:editors` full access (same as `Projects/`), so editors are
   not locked out and inheritance covers container-created files (defusing the
   `umask 077` concern). `aclmode=restricted` confirmed — the installer's `chmod 2770`
   will be rejected there, which is why that step is non-fatal-with-a-NOTE by design.
   Incidental: the NAS `editors` group contains a machine-shaped real account
   (`alex_laptop`) — a live cousin of B16; consider renaming it if it's a machine.
8. **macOS — CODE-COMPLETE 2026-08-03, PENDING FIRST REAL-MAC VALIDATION.** The
   self-upgrade gap is **RESOLVED**: `upgrade.py` derives both the platform key and the
   staged filename from `sys.platform` (`ccsync-companion.new` on darwin, `.new.exe`
   only on Windows) and chmods `0o755` after the sha256 verify but before the swap, and the
   respawn is `start_new_session` with `CCSYNC_REPLACES_PID` set so the new process waits
   out its predecessor's posix lock instead of exiting as a duplicate
   (`platform_key`, `new_download_name`, `_make_executable`). Shipped alongside
   it: path canon (`canon.py`), the external-SSD root guard (`root_guard.py` + lane-level
   `isdir` gates), darwin keep-awake (`caffeinate`) and shutdown guard (SIGTERM →
   graceful; **no** shutdown-blocking screen on macOS — honest reduced parity), installer
   1.0.16 (`macos_bootstrap.sh` with the automatic Resolve Mapped Mount, plus
   `macos_uninstall.sh`), the dashboard's `macos` package channel, and the Mac-side build
   command `tools/release_macos.sh`.

   **UPDATE 2026-08-04 — it has now BUILT and TESTED on a Mac; it has still not RUN on
   one.** First real hardware (arm64, macOS 15.7.4): `release_macos.sh` produces a signed
   arm64 binary, a clean-venv editable install succeeds, and the companion suite is
   **1563 passed / 18 skipped / 0 failed** with every skip genuinely Windows-only and all
   24 real-rclone lane-direction tests executing. Five defects were found and fixed
   (`docs/macos-first-run-2026-08-04.md`, summarised in `installer/README.md`):

   - **MAC-1, critical:** a UTF-8 BOM on `companion/pyproject.toml` (introduced by the
     0.4.20 bump itself) made `pip install -e .` impossible, so no macOS build could be
     produced at all. It also broke `test_version_matches_pyproject` on **every** host —
     `main` was red everywhere and nobody knew, because `tools/release.ps1` never
     installed the package and every other Windows reader of that file uses a regex.
   - **MAC-4, major:** the rclone test fixture looked for a hardcoded `rclone.exe`, so
     the 24 tests proving lane A is up-only and lane B is down-only skipped silently on
     every Mac while `pytest` still exited 0 — a false green on the most destructive
     path in the system.
   - **MAC-3:** `resolve_bridge._norm_path` and popup's basename fallback used the host's
     `os.path` on canonical `P:\` strings, which on posix folds nothing and returns whole
     paths from `basename` — silently disabling the popup dedupe and the duplicate-
     `ReplaceClip` guard behind it.
   - A drive-rooted `dest_rel` (`C:/Windows/Temp`) passed the containment check on posix,
     where it is an ordinary relative join.
   - **D5:** the Resolve mapping helper kept the trailing `/Volumes` entry last in
     `config.dat` but not `.config.data`, contradicting its own documentation; and its
     atomic save silently re-owns a root-owned `.config.data`.

   **Still true: no macOS RUNTIME path has executed** — `diskutil`, `launchctl`, `xattr`,
   pyobjc, the Resolve preference *write*, `caffeinate`, the external-SSD root guard and
   the self-upgrade swap remain written-from-documentation. Checklist sections A7–H are
   unrun, and the external-SSD drills (E) are blocked on choosing a drive and filesystem.

   **UPDATE 2026-08-04 (later) — the onboarding wizard now runs on macOS, code-complete
   (installer 1.0.17).** Option A of `docs/macos-onboarding-handoff.md` §2: `steps.py`
   grew fully-tested darwin branches (bash bootstrap invocation, LaunchAgent clean
   slate, posix local-root validation with a /Volumes ghost-mount pre-check),
   `onboard.py` asks the same EDITOR/BASE question on both platforms (commercial
   deployments can run a Mac base rig: companion + LaunchAgent autostart, NAS mount
   untouched, default tree `/Volumes/TheCreatorsPool/Creators_Club`), and
   `macos_bootstrap.sh` speaks the wizard contract (`CAPABILITY MISSING:` + exit 3,
   `RESOLVE-MAPPING-STATUS:`, and an existing-config `rclone_path` repair that the
   wizard flow depends on — it pre-creates `config.toml`, so the bootstrap's own
   seeding never runs there). `build_onboard_macos.spec` + `tools/build_onboard_macos.sh
   [--publish --make-current]` produce and publish `CCSync Onboarding.app`;
   **the zipped wizard is now what a Mac's [ INSTALLER ] click downloads** (dashboard
   0.3.7 names macos onboard uploads by content — zip → `.zip`, script → `.sh` — and
   Windows ships no longer push `macos_bootstrap.sh` into that slot; they only warn on
   staleness). The .app has **never been built or double-clicked** (needs the Mac,
   after A8). 76 new onboarding tests + 2 dashboard tests, all green on Windows.
   Treat macOS as **builds-and-tests-clean, runtime-unvalidated** until the supervised
   first-session checklist in `installer/MACOS_FIRST_RUN.md` has been walked end to end;
   `installer/README.md` → "Next steps for macOS" has the ordered plan.

   **UPDATE 2026-08-04 (later still) — the companion has now RUN on a Mac**, 0.4.21 on a
   16" MBP (macOS 15.7.4, arm64). It starts, keeps its lanes gated behind sign-in, and
   shuts down gracefully. Three defects, all of them invisible to the test suite because
   all three are properties of the *second* Tk interpreter that `ui_dispatch` introduces
   on darwin and none has a runtime symptom a unit test can see:

   - **MAC-7, major: the tray icon was never drawn, and the log said `tray icon started`.**
     pystray reports success once the `NSStatusItem` exists. On a full menu bar macOS
     gives the item a frame in the menu bar row and then does not render it. Measured:
     screen 1728x1117, notch spanning x 771..956, four items created at once landed on
     x = 812, 774, 736, 698 — every one of them invisible, including the one that cleared
     the notch entirely. **Anything left of the notch's right edge is not drawn.** Ruled
     out by experiment, each a live probe on the hardware: it is not a pystray/Tk run-loop
     conflict (identical placement with no Tk in the process, and Tk's own windows draw
     fine), not the activation policy (`setActivationPolicy_(1)` returns True and reads
     back Accessory), not packaging (a real `.app` bundle with `LSUIElement` and a working
     `CFBundleIdentifier` places identically), and not icon width. The fix is diagnostic,
     not corrective — nothing app-side can conjure menu bar space: `tray.classify_status_item_placement()`
     compares the item's frame against `NSScreen.auxiliaryTop{Left,Right}Area` three
     seconds after `run_detached()` and logs a warning plus a toast when the icon landed
     where macOS will not draw it. Editors on notched MacBooks WILL hit this.
   - **MAC-6, critical: a filled-in sign-in form failed with "username and password are
     both required".** A masterless `tk.StringVar()` binds to `tkinter._default_root`,
     which on darwin is `ui_dispatch`'s hidden root — a different interpreter from the
     dialog. The `Entry` wrote into the dialog's interpreter and `.get()` read the hidden
     one's empty variable. Same defect in the fixer's destination comboboxes, where it
     would have filed media at the tree root. Fixed by `master=`; `tests/test_tk_interpreter_hygiene.py`
     is an AST guard so it cannot come back.
   - **MAC-6, critical: the dialog opened exactly once per session.** Tk's loop runs
     `while Tk_GetNumMainWindows() > 0` and that count is **per thread, not per
     interpreter**, so the hidden root keeps a dialog's nested `mainloop()` spinning after
     the dialog is destroyed. The caller never returned, `app._popup_active_lock` was
     never released, and every later dialog was refused with "Another CCSync window is
     already open" — the same wedged main thread also made the process ignore SIGTERM and
     need a `kill -9`. Fixed with `ui_dispatch.run_dialog()` (`tkwait window` on darwin,
     `mainloop()` unchanged everywhere else). `root.quit()` is NOT an alternative:
     _tkinter's quit flag is process-global and would break `serve()` out of its own loop.

   The drive-and-filesystem question that blocked the external-SSD drills (E) is now
   ANSWERED, but not the way the deployment is tested: the Mac's sync root is a 2 TB
   **exFAT** volume (`/Volumes/SAMDISK`, uuid `A8424FB3-…`), chosen because it already
   holds 1.1 TB of the editor's work and reformatting to APFS has nowhere to park that.
   `local_root = /Volumes/SAMDISK/Creators_Club`, the root guard recorded the volume on
   its first present sighting, and Resolve maps `P:\` to it (helper `verify` exits 0).
   So drills E run on exFAT: no POSIX ownership or permissions, case-insensitive names,
   and macOS writing `._` AppleDouble sidecars into the tree — which lanes A and B both
   carry today (see item 12). Sections A7–H otherwise remain unrun, and lane C has never
   run at all (see item 11).

9. **The macOS wizard build will break on PyInstaller 7 — MIGRATED IN THE WORKING TREE
   2026-08-05, NEEDS ONE MAC BUILD TO BE BELIEVED.** `onboarding/build_onboard_macos.spec`
   is now onedir: `EXE(exclude_binaries=True)` → `COLLECT` → `BUNDLE(coll, …)`, with the
   `runtime_tmpdir` (onefile-only) dropped and every other setting kept — name, ad-hoc
   `codesign_identity=None`, `console=False`, `bundle_identifier`, the whole `info_plist`
   including the `CFBundleShortVersionString` the release scripts diff against
   `INSTALLER_VERSION`. Dry-verified against PyInstaller 6.21's own bundle-assembly code
   (`building/osx.py`) rather than a build, because the artifact can only be built on a
   Mac: top-level `datas` land in `Contents/Resources` and are cross-linked into
   `Contents/Frameworks`, which is where `sys._MEIPASS` points in an .app bundle
   (`loader/pyimod02_importers.py:89`), so `steps.find_bootstrap_script()`,
   `find_companion_exe()` and `theme.icon_path()` all still resolve — the last through a
   *directory* cross-link. The bundled companion is Mach-O, so Analysis reclassifies it
   from `datas` to `binaries` (it already did in onefile) and it lands directly in
   `Contents/Frameworks`, keeping its 0755 bit. `tools/build_onboard_macos.sh` needed no
   path change (`dist/CCSync Onboarding.app` is a directory either way and is all the
   script touches); it gained `codesign --verify --all-architectures --deep --strict` on
   the bundle *and* on the unzipped copy, because onedir is the first version of this
   artifact with real nested code inside it and `codesign -dv` cannot see a broken nested
   signature. Seven AST/source guards in `onboarding/tests/test_macos_steps.py`
   (`TestMacBundleIsOnedir`), mutation-verified: reverting the spec to onefile fails 5 of
   the 7 while the other 2 still pass. **What remains: build it on the Mac and watch it**
   (`installer/MACOS_FIRST_RUN.md` §C's wizard note has the success/failure shapes).
   Original entry, for the reasoning: the spec
   built its `.app` bundle in **onefile** mode, and PyInstaller 6.21 warns:
   *"Onefile mode in combination with macOS .app bundles (windowed mode) don't make sense
   … and clashes with macOS's security. Please migrate to onedir mode. This will become an
   error in v7.0."* It builds and runs today — 1.0.17 was built, published and verified
   end-to-end on 2026-08-04 (downloaded from `[ INSTALLER ]`, unzipped, `codesign --verify
   --deep --strict` passes). But the next PyInstaller major turns this into a hard failure,
   and the only machine that can build this artifact is a Mac, so it would surface as a
   broken release on the one path with no fallback. The zip shape the dashboard serves does
   not change (a onedir `.app` is still a directory tree inside the same zip), which is why
   this could be done ahead of the v7 upgrade rather than under it.

10. **The publish scripts cannot survive a password containing control characters —
    FIXED in the working tree 2026-08-05, needs no release (they are dev-box tools).**
    `tools/release_macos.sh:92` and `tools/build_onboard_macos.sh:241` shared
    `json_escape()`, which escaped backslashes and double quotes only, and the login body
    is assembled with `printf`. A password carrying any byte < 0x20 therefore produced
    invalid JSON, and the dashboard answered `422 json_invalid / "Invalid control character
    at"` — which reads as "wrong password" and is not. Hit live on 2026-08-04: the reported
    offset is the *byte position* of the offending character (verified against the live
    endpoint: a control char first/middle/last in the value reports 31/35/37 for
    `{"username":"alex","password":"…"}`), so offset 31 means the FIRST byte of the
    password. The usual source is a bracketed paste — zsh wraps pasted text in
    `ESC[200~ … ESC[201~` and `read -r -s` captures the escapes. Typing the password works.

    Fixed in three layers, because no one of them is enough. `strip_bracketed_paste()`
    removes both wrappers wherever they appear; `reject_non_printable()` then refuses any
    value (password *or* `--admin-user`) still carrying a byte < 0x20 or 0x7f, naming it —
    *"the password contains a non-printable character (byte 0x1b at position 4) — retype it
    rather than pasting"* — because stripping alone would turn the 422 into a misleading
    401; and `json_escape()` now escapes the control range too (`\n`/`\r`/`\t`/`\b`/`\f`,
    `\u00XX` for the rest), so every other value it writes (the release manifest's version,
    arch and `git describe`) is valid JSON regardless. All three live between
    `# ---CCSYNC-PASSWORD-HYGIENE-{BEGIN,END}---` sentinels and are **byte-identical in the
    two scripts**, which `companion/tests/test_publish_password_hygiene.py` asserts the way
    B19's cross-file test does. It escapes byte-wise through `od`+`awk` rather than `sed`,
    with `LC_ALL=C`: a password may contain bytes that are not valid UTF-8, which BSD sed
    answers with *"RE error: illegal byte sequence"*, and in a UTF-8 locale awk's `%c`
    re-encodes each byte it is given (measured: `70 c3 9f 77` → `70 c3 83 c2 9f 77`) — the
    same GNU-vs-BSD-vs-locale trap as MAC-9. 37 tests, run against the real scripts under
    the local `od`/`awk`/`sed`, mutation-verified: restoring the two-rule `json_escape`
    fails 12, removing the rejection fails the "leftover control byte" test, removing the
    stripping fails the "a bracketed paste is accepted" ones, and editing one copy of the
    block fails the drift test. Suite: **1760 passed**.

    Not changed: `installer/macos_bootstrap.sh:278` still carries the old two-rule
    `json_escape`. It escapes a volume UUID, a mount point and a local root into
    `~/.ccsync/`'s mapping record — no password, no terminal paste — so it is a much
    smaller target, but it is the third copy of a helper that has now been fixed twice.

    **MAC-8, critical — FIXED, shipped in installer 1.0.19:** the same class of defect took the
    whole wizard down on macOS. `OnboardWizard._safe_after()` marshalled every background
    result to the UI with `self.root.after(0, fn)` **called from the worker thread**. On
    Windows/Tk 8.6 that works, which is why it shipped; on macOS with Tk 9 it raises
    NOTHING and never runs the callback — verified on Tcl/Tk 9.0.3, 2026-08-04:

        after() from worker: no exception raised
        landed=[]          # 3 s later, the callback has still not run

    So the `except Exception: pass` in `_safe_after` was not even reached — there was no
    exception, just a silently discarded UI update, no log line anywhere. All **eleven**
    call sites are affected, i.e. every background result the wizard produces: the
    Tailscale check (where it is first visible — the status label sits on "checking…"
    forever), sign-in, the bootstrap run, install failure, and both finish pages. The
    published 1.0.17 wizard is unusable past page 3 on a Mac. Fixed by the same shape as
    the companion's `ui_dispatch`: a `queue.Queue` drained by an `after()` timer that is
    created and re-armed **on the main thread**, so only `queue.put()` ever crosses the
    boundary. Verified against the real `OnboardWizard` driving the real page-3 worker.

11. **Lane C — RESOLVED 2026-08-05.** It now runs: the NAS shared the folders with this
    Mac's device, the sequencer accepted them, and lane C is delivering (audio, AE, subs,
    b-roll). The blocker was never client-side, which is the point worth keeping:
    everything the installer owns was already correct and the machine still synced
    nothing. Original diagnosis, for the next editor who reports the same silence:
    **the pairing is one-sided.** Everything the installer
    owns is in place on the first real Mac: the binary (`~/.local/ccsync/bin/syncthing`,
    installed by `macos_bootstrap.sh`), the LaunchAgent, the NAS device seeded into the
    local config, and the API key auto-discovered from the managed `config.xml` (so a blank
    `syncthing_api_key` is correct, not a misconfiguration). What is missing is server-side:
    the NAS's Syncthing has never added this Mac's device, so the connection sits
    `NOT connected`, `pending/folders` is `{}`, and no folder has ever been offered for the
    sequencer to accept. Not a network problem — the NAS answers on
    `truenas.tail26290e.ts.net:22000` in 5 ms. Nothing in the installer or the wizard can
    fix this from the editor side; someone with TrueNAS Syncthing access has to share the
    folders with the device. Until then the macOS validation covers lanes A and B only, and
    the `.stfolder`-marker behaviour the root guard and lane B's mass-delete defence both
    depend on is untested on this platform.

12. **Both rclone lanes sync macOS AppleDouble sidecars (`._*`) — VERIFIED 2026-08-04,
    FIXED in the working tree 2026-08-06.**
    On any filesystem without native extended-attribute support — exFAT, FAT32, SMB, i.e.
    exactly the external SSDs this deployment is built around — macOS stores resource forks
    and xattrs in sidecar files named `._<original>`. The lane filters do not exclude them,
    and because the sidecar keeps the original's extension, lane A's `+ *.mov` (and every
    other `+ *<ext>`) matches it. Confirmed against the real rule builders and the real
    rclone binary, not by reading the rules:

        $ rclone ls --filter-from <build_filter_rules_up()>   ./ftest
              0 ._A001.mov          <-- uploaded to the NAS
              0 A001.mov
        $ rclone ls --filter-from <build_filter_rules_down()> ./ftest
              0 Proxy/._p.mov       <-- pulled down to every editor
              0 Proxy/p.mov

    So a Mac editor on an exFAT drive publishes a junk 4 KB `._clip.mov` beside every real
    clip, into a shared tree that Windows editors also see, and lane B redistributes the
    proxy-side ones. `.DS_Store` is already safe — it matches no `+ *<ext>` rule and dies on
    the trailing `- **`. Fix is one rule per lane, placed FIRST because rclone filter
    matching is first-match-wins (a later `+ *.mov` would otherwise win): `- ._*` at the
    head of both `build_filter_rules_up()` and `build_filter_rules_down()`. Worth pairing
    with a sweep for `._*` already uploaded, since the tree predates the fix.

    **FIXED:** `APPLEDOUBLE_EXCLUDE_RULE = "- ._*"` is emitted at index 0 of both
    builders. Measured against the real binary rather than assumed: the single
    no-slash rule drops `._A001.mov`, `Proxy/._p.mov` *and* `Sub/Proxy/._n.mov` — no
    `**/` form needed (it is the `/`-anchored rules that need both forms) — and it
    matches basenames only, so a directory *named* `._x/` still syncs, pinned by test
    so the rule and the predicate cannot drift in opposite directions. The fix also
    closed a third hole this entry did not know about: the express path passes **no
    filter file at all** (rclone rejects `--filter-from` with `--files-from-raw`), so
    `path_matches_lane_a_filter()` is the entire filter there and would have uploaded
    the exact sidecar the periodic pass now refuses — it rejects `._` basenames too.
    Real-rclone tests in both directions plus rule-order and predicate tests,
    mutation-verified (reverting the rule fails 9). **Residual:** the NAS tree
    predates the fix — a one-time sweep for already-uploaded `._*` is still owed.

13. **MAC-9, critical: the installer emptied rclone.conf on macOS — FIXED in 1.0.19.**
    `macos_bootstrap.sh`'s "the stanza disagrees with the values you passed" branch —
    i.e. **re-running the installer**, the normal upgrade path — rewrote the remote by
    passing the seven-line stanza through `awk -v stanza=...`. macOS ships BWK awk, which
    rejects a `-v` value containing a newline:

        awk: newline in string [creators_club_sftp]... at source line 1
        exit 2, zero bytes written

    The script then `chmod`ped and `mv`d that empty output over `~/.config/rclone/
    rclone.conf` with **no check on awk's exit status and no check that the output was
    non-empty**, destroying every remote in the file — credentials for unrelated remotes
    included, directly contradicting the comment above it ("every other remote in the
    file is preserved"). GNU awk accepts multi-line `-v` values, so no Linux or CI run
    ever reproduced it. Hit live on the first real Mac, 2026-08-04: lanes A and B went
    from an SSH-auth failure to `didn't find section in config file`.

    Fixed in two layers, because either alone is insufficient: awk now only DELETES the
    old section (single-line `-v`, no newline anywhere) and the shell appends the stanza;
    and nothing is swapped into place until awk has succeeded, the new section is present,
    and **every other section the file started with is still there**, with a timestamped
    backup kept. Mutation-verified: reintroducing the old awk fails 3 of the 7 tests in
    `companion/tests/test_rclone_stanza_rewrite.py` while the other 4 still pass, because
    the verify-before-swap layer refuses the write and leaves the config intact — a
    data-destroying bug becomes a clean failure with a fix-it-by-hand message. The tests
    run the real function out of the real script under the local `awk`, which is the only
    way this class of bug is visible at all. Side effect: the rewritten section moves to
    the end of the file (rclone is order-independent).

14. **rclone's real error never reaches the log — FIXED in the working tree
    2026-08-06.** `sync/rclone_lane.py:515` logged
    `(proc.stderr or "").strip()[:300]` — the **first** 300 characters. For any SFTP
    remote, rclone's host-key `NOTICE` is ~260 of them, so the actual failure is always
    truncated mid-sentence. Live cost, 2026-08-05: an SSH auth failure that had stopped
    lanes A and B entirely appeared in the log as `CRITICAL: Failed to create file system
    for` and nothing else — no remote, no reason. Finding it took a hand-run of the same
    command, which is exactly what the log line exists to avoid. Log the tail instead, or
    filter the NOTICE line out before truncating.

    **FIXED:** both, via one `_stderr_for_log()` — drop `NOTICE:` lines, then keep the
    tail (`STDERR_LOG_CHARS`), falling back to the raw text when the stream is nothing
    *but* notices so a failure never logs an empty string. Applied at the `_run_lsf`
    site and the two existing `[-300:]` sites so all three read the same. The lane runs
    themselves use `--use-json-log` (notices are JSON records there, no `NOTICE:`
    substring), so `_run_lsf` was the one plain-text caller — the one that produced the
    live symptom. The regression test reproduces it: the `CRITICAL: Failed to create
    file system for …` line now survives into the log, remote and reason included.

15. **The onboarding suite is red on macOS: 18 failed, 197 passed — FIXED in the
    working tree 2026-08-06, pending one darwin run to confirm.** All in
    `test_steps.py` / `test_cleanup_steps.py`, all Windows-shaped assertions (PowerShell
    argv, drive letters, UNC paths, `.exe` fallbacks, registry Run values) executed
    unguarded on darwin — the same class as MAC-2 for the companion suite. Pre-existing
    and unrelated to any 2026-08-05 change (verified identical with the tree stashed), but
    it means the suite cannot gate the platform the wizard now ships to. Either give the
    Windows-only tests a `platform=` seam like the rest of `steps.py` has, or skip them on
    darwin — silently passing on 91% is worse than an honest skip.

    **FIXED, test by test:** 14 of the 18 now pin `platform="win32"` through the
    existing seam, so they run and pass on every host; 4 are honest `skipif`s because
    the code under test is genuinely Windows-only (registry Run values, host-built
    `dist/` artifacts, host-`os.path` containment) — each with its darwin counterpart
    already covered in `test_macos_steps.py`. Three further tests that were passing
    *vacuously* on darwin (asserting `-LocalRoot` absent from an argv that was never
    PowerShell's) were pinned too — the same silently-green disease this item names,
    one line from where it was diagnosed. The posix-semantics predictions behind the
    skips were verified empirically on Windows via `posixpath` and the darwin branches.
    Windows: 222 passed. Expected darwin: **211 passed, 4 skipped** — confirm on the
    next Mac session.

16. **The companion's TCC grants do not survive a self-upgrade.** It is ad-hoc signed
    (`TeamIdentifier=not set`), so its Full Disk Access identity is a hash of the binary
    and every upgrade presents as a different program needing a fresh grant. On a Mac
    whose sync root is an external volume — the deployment this port exists for — losing
    that grant means the tree becomes unreadable to the companion after an update, with no
    error that names the cause. `rclone` and `syncthing` are properly signed and need
    granting once. Either sign the companion with a stable identity, or have the tray
    surface "macOS is blocking access to the sync volume" when a post-upgrade read fails.

    **UPDATE 2026-08-06: the tray fallback is in the working tree.**
    `root_guard.access_is_blocked()` detects darwin + EACCES/EPERM reading the root (or
    its volume — an unreadable parent hides its children) *while the volume is still
    mounted*, which is what distinguishes a revoked grant from an unplugged SSD (that
    stays root-absent, already handled). `app._check_macos_volume_access()` runs it
    once, 3 s after the first start on a new build (`note_version_start()`), and
    surfaces a toast naming Full Disk Access in System Settings, an ERROR log naming
    the path and the ad-hoc-signing cause, and a diagnostics suffix. ENOENT, ghost
    mounts, exotic errors and every non-darwin host return False without touching the
    disk. Signing with a stable identity remains the real fix and is **still open**
    (needs a Developer ID certificate — a purchase, not a patch).

17. **MAC-10, critical: the Resolve bridge never connected on macOS — FIXED in the
    working tree, needs a release.** `resolve_bridge._default_modules_dir()` returned
    `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Scripting/Modules`.
    The real path has a `Developer/` component — `.../DaVinci Resolve/Developer/Scripting/
    Modules` — exactly like the Windows branch three lines above it, which gets it right
    (`Support\Developer\Scripting\Modules`). The short path exists on no machine, so
    `import DaVinciResolveScript` failed, `connect()` returned None, and **every** Resolve
    feature was dead on darwin: no out-of-tree popup, no BAD_PREFIX mapping warnings, no
    relink, no project name on the dashboard.

    It was invisible because the whole chain logs at DEBUG: `connect()` logs the import
    failure at debug, and `watcher.poll_once` logs `"DaVinci Resolve is not running"` at
    debug (`watcher.py:135`). At the shipped `log_level = "INFO"` the log looks perfectly
    healthy — v0.4.22 ran for hours on the first real Mac with an out-of-tree PSD sitting
    on the timeline and not one line in `companion.log` ever mentioned Resolve. Found
    2026-08-05 only by probing the scripting API by hand.

    Two follow-ups worth doing, because the path fix alone leaves the same trap armed:
    the "Resolve is not running" poll result should be logged at INFO **once** on the
    transition (it is a user-visible capability going away, not a debug detail), and the
    tray/diagnostics should say whether the bridge has ever connected this session.
    **Both DONE in the working tree 2026-08-06 — details under item 19.**

    Workaround for an already-installed build, no rebuild needed —
    `_ensure_env_and_syspath()` honours a preset `RESOLVE_SCRIPT_API`, so adding
    `EnvironmentVariables` to `~/Library/LaunchAgents/com.creatorsclub.ccsync.companion.plist`
    and reloading the agent fixes it in place. Confirmed live: the popup fired 2 s after
    the restart, and the frozen build reached fusionscript fine without a bundled
    libpython, so `build.spec`'s deliberate no-pin on darwin is vindicated.

18. **MAC-11, critical: a SUCCESSFUL fix-all left an unclosable window that wedged the
    whole companion — FIXED in the working tree, needs a release.** Hit live 2026-08-05,
    on the first fix-all ever run on a Mac (the one MAC-10 above made reachable). The copy
    completed, `ReplaceClip` relinked the timeline, Syncthing carried the file to the NAS
    — and the popup stayed on screen forever, ignoring every click.

    `PopupDialog._safe_after` (`popup.py`) was the **one cross-thread Tk call** in the
    dialog: the fix-all worker ends with `self.root.after(0, lambda: self._fix_done(...))`,
    and its `except Exception: pass` swallowed the failure whole. Progress had worked
    throughout because the worker only ever *published to a dict* that a `root.after(250)`
    tick read on the Tk thread — the correct pattern, used everywhere except the final
    handoff. With `_fix_done` never running, nothing on screen could dismiss the window:
    FIX ALL and IGNORE are disabled by `_run_fix`, STOP/SKIP/CANCEL only set flags a
    finished worker will never read again, and `_on_close_request` turns the X into
    "cancel all" while `_fixing` is still True.

    It is worse than one dead window, because of how dialogs run on darwin. `run_dialog`
    uses `tkwait window` (correctly — a nested `mainloop()` never returns, MAC-6), and the
    popup is opened from inside `MainThreadDispatcher._pump`'s timer callback. A popup
    that never destroys is therefore a **`tkwait` the pump is parked inside**: it never
    re-arms, so every later dialog request queues forever (proven in the log:
    `UI dispatch: stopped with 1 window request(s) waiting`), and `serve()`'s mainloop
    cannot return, so **SIGTERM cannot finish a shutdown**. The companion logged
    `SIGTERM received`, stopped the watcher and the lanes, and then sat there alive with
    the window up — and because the singleton guard still saw its pid, every relaunch
    exited with `another ccsync-companion is already running`. It took `kill -9`.

    Fixed by removing the dependency on that one call, not by making it more reliable:
    the worker publishes its results to the same lock-protected dict progress goes
    through and *then* tries `_safe_after`; `_deliver_results()` runs the finisher exactly
    once, whichever route arrives first, and the 250 ms tick — already on the Tk thread,
    needing no cross-thread call at all — is the route that cannot fail. Plus: `on_done`
    runs in a `try` (an exception in the app's callback must not cost a dismissable
    window), the X finishes a batch that has already ended instead of "cancelling" it, and
    a failed marshal is logged. Four regression tests in `tests/test_popup.py`,
    mutation-verified — deleting the tick delivery fails 2 of the 4 while the other 2
    still pass. Suite: **1590 passed, 18 skipped**.

    **Follow-up — DONE in the working tree 2026-08-06, both mechanisms.**
    `run_dialog()` now registers its window with the dispatcher (`note_dialog` /
    `forget_dialog`, a stack, innermost-first) and `stop()` destroys whatever it is
    parked in before tearing down the hidden root. The destroy is scheduled with
    `after(0)` on the *hidden root*: Tcl's timer queue is per **thread**, not per
    interpreter, and `tkwait window` spins in `Tk_DoOneEvent`, which services that
    queue — so the timer fires while the pump's own chain is parked. Because a
    cross-thread Tk call blocks the caller until the UI thread services it, the
    marshal rides a throwaway daemon thread joined at 5 s — `stop()` runs inside a
    SIGTERM handler and must not hang; and `note_dialog()` refuses once stopped,
    closing the open-a-window-into-shutdown race. Backstop for the dialog that cannot
    be reached at all (a dialog with no timer callbacks never even executes the signal
    handler's bytecode): `shutdown()` arms a 10 s timer that re-checks and, only if the
    mainloop is *still* serving after lanes/guards/reporter have all stopped and the
    upgrade swap has already happened, logs ERROR naming the open windows, flushes the
    log handlers and `os._exit(1)`s — inside the successor's 20 s predecessor-wait, so
    an upgrade respawn is unaffected. 16 tests across `test_ui_dispatch.py` /
    `test_app.py`, mutation-verified.

19. **Resolve's own script server can die at launch, and the companion called that
    "DaVinci Resolve is not running" — message FIXED in the working tree, the Resolve-side
    failure is not ours to fix.** Hit live on the base rig 2026-08-05, Resolve Studio
    21.0.1.0011, with Resolve open on screen the whole time.

    Resolve starts its Fusion script server as a child process at launch and the scripting
    API talks to *that*, not to `Resolve.exe`. On this launch it failed three times and
    gave up (`%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\logs\davinci_resolve.log`):

    ```
    22:44:59 | Fusion | Started script server: 36660
               Failed to connect to script server, retrying
               Started script server: 32936
               Failed to connect to script server, retrying
               Started script server: 38896
               Failed to connect to script server
       141.265 [40792] Incoming connection
       141.265 [40792] RemoteApp::Connect (…) - ioctlsocket(block) err 1
       141.265 [40792] Incoming connection
       141.265 [40792] RemoteApp::Connect (…) - ioctlsocket(block) err 1
       141.375 [40792] Script Server Terminated: done: 1, err: 0
    ```

    **Resolve never retries.** Probes 15 minutes later produced no new lines at all, so the
    API was dead for that process's entire lifetime. Only a restart of Resolve brings it
    back — confirmed the same night: relaunched 23:10:57, `Script server connection
    succeeded`, bridge live again.

    Every cheap liveness check says everything is fine while this is happening, which is
    what makes it so expensive to diagnose. `Resolve.exe` is running, `Started listener
    socket at port 15000` is in the log, and 15000/20321/49152 all accept TCP. What fails
    is one layer up: from plain Python 3.12 with the stock env, `scriptapp("Resolve")` and
    `scriptapp("Fusion")` both return `None`. Preferences were correct throughout
    (`System.Scripting.Mode = 1` in both `config.dat` and `.config.data`, "External
    scripting using: Local" on screen).

    Likely trigger — two clients hitting the server inside its startup window (the two
    `Incoming connection` lines a millisecond apart); this rig runs the companion and a
    Resolve MCP server, both of which connect unprompted. It is marginal rather than
    deterministic: the 2026-08-04 16:37 launch and the successful 23:10 restart each
    needed one retry before succeeding. Staggering clients behind a fully-loaded Resolve
    makes it less likely; nothing in this repo can make it impossible.

    **Our half, fixed.** `connect()` returning `None` has four causes needing four
    different actions — Resolve not running (start it), bad scripting env (admin), failed
    import (admin), dead script server (restart Resolve) — and `resolve_bridge` reported
    all four as `"DaVinci Resolve is not running"`. That message named the one action that
    could not help, and cost an hour of debugging aimed at the companion while Resolve sat
    open. `resolve_prefs.resolve_is_running()` already existed to tell the cases apart; it
    just was not wired in. Now: the locked helpers return a `_NOT_CONNECTED` sentinel and
    `_explain_disconnection()` swaps in `NOT_RUNNING_MESSAGE` or `NO_SCRIPTING_MESSAGE`
    ("…is running but isn't accepting scripting connections. Quit Resolve and reopen it.")
    **outside `_API_LOCK`** — the probe shells out to `tasklist`/`pgrep`, and doing that
    under the bridge lock would park the watcher, the tray and any fix-all behind a
    subprocess on every failed poll, i.e. every 3 s with Resolve shut. A 30 s TTL cache
    keeps a closed Resolve at two spawns a minute instead of twenty. The probe's
    fail-closed bias is inherited deliberately: an inconclusive check reports the
    "running" wording, because "quit and reopen Resolve" still works for someone whose
    Resolve is shut, while "it is not running" is a dead end for someone looking straight
    at it. Seven regression tests in `tests/test_resolve_bridge.py`, mutation-verified —
    reverting the distinction fails 6, moving the probe back inside the lock fails the
    cross-thread lock test. Suite: **1666 passed**.

    **Follow-ups — DONE in the working tree 2026-08-06.** Both were asked for in item
    17 and this incident was the second time they would have paid. The watcher now
    logs the bridge state at INFO exactly **once per transition** (`Resolve bridge:
    connected to DaVinci Resolve` / the distinguished disconnect message; a change of
    *reason* — not-running → not-accepting — is its own transition; repeats stay
    DEBUG). Only `NOT_RUNNING_MESSAGE`/`NO_SCRIPTING_MESSAGE` count as disconnection —
    "no project open"/"no timeline open" mean the bridge answered, so closing a
    project logs nothing. The tray gains a `Resolve:` status line (`connected` /
    `not connected right now — …` / `NOT CONNECTED this session — …`) and diagnostics
    a `resolve bridge:` line with has-connected-this-session, fed by a session record
    at `_explain_disconnection()` — the chokepoint both enumerators share, so a tray
    Scan keeps it current even when the watcher never runs. The tray reads a cached
    dict; nothing on the render path ever probes fusionscript. With these, this
    incident would have been a glance at the log rather than an evening. Tests across
    `test_watcher.py` / `test_resolve_bridge.py` / `test_tray.py` / `test_app.py`
    (+31), mutation-verified.

20. **Right-clicking the tray icon often did nothing, or opened the menu seconds late
    — FIXED in the working tree 2026-08-10.** Two independent causes, both on Windows,
    both diagnosed from the code and reproduced in tests rather than from a live capture.

    **Cause 1, dominant: GIL starvation by the timeline watcher.** Every fusionscript
    call holds the GIL for its full native duration (the same property behind MAC-12's
    hang), and `_get_timeline_items_locked` makes three or four PER CLIP, every
    `poll_interval` (3 s). pystray's win32 message pump is a Python window procedure, so
    it cannot process the `WM_RBUTTONUP` that opens the menu *at all* without the GIL: a
    large project meant a 1–3 s blackout every 3 s, and a click landing inside one was
    late or lost. `ui_state.wait_while_menu_open()` — added 2026-07-26 for the hover-
    highlight freeze — cannot help here by construction: the flag is set inside the
    wrapped `TrackPopupMenuEx`, i.e. only once the menu is *already* open, so it protects
    every click except the one trying to open it.

    Fixed on both axes. The sweeps (`_get_timeline_items_locked` and
    `_walk_media_pool_folder`) now call `time.sleep(0.002)` every 25 clips — a real GIL
    yield, so the pump is never more than 25 clips from a scheduling slot; a 1000-clip
    timeline pays 80 ms per sweep. And most polls do not need the sweep at all: the poll
    first gathers a cheap fingerprint (project name, timeline name + `GetUniqueId`, one
    `GetItemListInTrack` per track) and returns the previous poll's items unchanged when
    it matches. **Safety valve: a full walk at least every 10th poll (~30 s) regardless**
    — an in-place relink changes no name and no count, and the watcher feeds the popup
    fixer, which must not go blind to it. The cache is armed by `allow_cached=`, reachable
    only through `poll_timeline_items()`, which only `TimelineWatcher` binds: tray → Scan
    whole project, the fixer and the proxy relinker act on what they are shown and always
    walk. A disconnection cannot be masked by it either — the fingerprint is gathered
    from the live project, so `connect()` returning None, no project and no timeline all
    reach the caller as themselves, ahead of any cache read. `replace_clip`,
    `refresh_lut_list` and `link_proxy_media` were also the three public entry points
    that never deferred to an open menu; they do now, like the other four.

    **Cause 2: an unsafe cross-thread menu rebuild in pystray.** `_win32.Icon._update_menu`
    (`pystray/_win32.py:99`) `DestroyMenu`s the old handle **first**, rebuilds ~30 items
    plus a submenu, and publishes `self._menu_handle` last — so for the whole rebuild the
    handle a concurrent right-click hands to `TrackPopupMenuEx` is already destroyed. It
    returns 0 and shows nothing, silently: pystray declares the function with no
    `restype` and no `errcheck`. Worse, it is driven from two threads that know nothing
    of each other — our refresh loop on every `icon.menu = …`, and pystray's own
    `_base.Icon.__call__` / `_base._handler` on the **pump** thread after every left-click
    and every menu selection — so two interleaving rebuilds `DestroyMenu` one handle twice
    and leak the other. At the 10 000-object USER quota `CreatePopupMenu` starts failing,
    `_menu_handle` goes `None`, and right-click does nothing at all until the companion is
    restarted. That is the cumulative "it gets worse the longer it runs" half of the
    symptom.

    Fixed by `tray._atomic_update_menu`, installed over the backend by `_MenuSwapGuard`
    in the same shape as `_MenuOpenGuard` (install-once, win32-only, never-raise, stock
    behaviour on any pystray whose internals have moved): one module lock, **build the
    new menu first, publish it, destroy the old one last**, and skip the rebuild entirely
    when `icon.menu` is the same object as at the last successful build — which is every
    post-click `update_menu()`, since the refresh loop only assigns on a fingerprint
    change. A raising or NULL-returning `_create_menu` logs and leaves the previous handle
    intact and usable: a menu one refresh stale beats no menu. The residual race is a
    right-click that read `_menu_handle` microseconds before a swap, instead of one
    landing anywhere inside a whole rebuild.

    **Cause 3: none of it was visible.** `setup_logging` attached the file handler to
    `logging.getLogger("ccsync")` only, so everything pystray says about itself ("An error
    occurred in the main loop") went nowhere — the windowed build has no stderr, so
    logging's last resort had nowhere to write either. The `"pystray"` logger now gets the
    same handlers and level, and the `TrackPopupMenuEx` wrapper captures the return value:
    a falsy one logs `tray menu failed to open or was dismissed immediately` with
    `GetLastError`. That fires on an ordinary Escape too, which is the honest trade — the
    two are indistinguishable at that call, and a right-click that does nothing is the
    most-reported tray symptom. The wrapper also posts `WM_NULL` to the owner window
    afterwards, MSDN's `TrackPopupMenu` note that pystray omits.

    24 tests across `test_resolve_bridge.py` / `test_watcher.py` / `test_tray.py`,
    mutation-verified — restoring pystray's destroy-first ordering fails the two-thread
    handle test with 300 violations while the rest still pass. Suite: **1896 passed**.
    Not fixed, and deliberately: the swap lock is *not* taken across the blocking
    `TrackPopupMenuEx` call. It would close the last microsecond of the race and open a
    worse one — a rebuild thread parked for as long as the editor leaves the menu open.

21. **The tray menu opens behind an auto-hide taskbar, covering Quit — FIXED in the
    working tree 2026-08-10, ships as companion v0.5.1.** Reported on the base rig
    (Windows 11, taskbar set to auto-hide) against v0.5.0: item 20 made the right-click
    menu appear instantly, and the thing that appears has its bottom edge — the Quit
    item — under the taskbar.

    **Item 20 did not cause this; it revealed it.** pystray anchors the popup at the raw
    `GetCursorPos` point with `TPM_RIGHTALIGN | TPM_BOTTOMALIGN | TPM_RETURNCMD`
    (`pystray/_win32.py:215`), i.e. "put the menu's bottom-right corner exactly HERE" —
    and HERE is inside the taskbar band, because that is where the tray icon the editor
    just clicked lives. What normally rescues that is Windows itself: `TrackPopupMenuEx`
    keeps the menu inside the monitor's **work area**, and a docked always-visible
    taskbar is subtracted from the work area, so the menu is nudged clear of it. An
    auto-hide bar is not: it reserves one pixel, the work area is effectively the whole
    screen, no constraint is violated, and the topmost bar — raised, because the pointer
    is on it — draws over the last item. Timing changed nothing about positioning rules;
    pre-fix the same geometry came out of the same flags, on the fraction of right-clicks
    that opened at all, seconds late and mid-GIL-blackout, which is why nobody filed it.

    Fixed in `tray.py` by extending the same `TrackPopupMenuEx` wrapper item 20 installed
    (`_MenuOpenGuard.tracked`): `_with_clamped_anchor` rewrites the positional
    `(hmenu, flags, x, y, …)` before delegating, `_taskbar_geometry` reads the bar via
    `SHAppBarMessage(ABM_GETTASKBARPOS)` — which reports the SHOWN rectangle even while an
    auto-hide bar is hidden, i.e. exactly the region the menu must clear — and the pure
    `_clamp_menu_anchor(x, y, flags, rect, edge)` does the arithmetic: an anchor inside the
    rect moves to the bar's inner edge (bottom → `rect.top`, top → `rect.bottom`,
    left → `rect.right`, right → `rect.left`), an anchor outside it is untouched, and the
    alignment is **rewritten, not or-ed on**. That last part is the non-obvious one:
    `TPM_LEFTALIGN` and `TPM_TOPALIGN` are `0`, so they exist only as the absence of the
    other bits on their axis — for a top or left taskbar, pystray's `RIGHT|BOTTOM` has to
    be cleared or the menu is moved off the bar and then drawn straight back over it.
    Everything else in the flags word (`TPM_RETURNCMD` above all, which is how pystray
    learns which item was clicked) is preserved.

    Fail-open throughout, deliberately: no geometry, a shell that will not answer, a
    non-Windows platform or a pystray that stops passing coordinates positionally, and the
    original arguments go through unchanged. A menu one taskbar-height too low beats the
    bug this file just spent item 20 climbing out of — a menu that does not open.

    Six tests in `test_tray.py` (all four docked edges as a table, inside vs outside the
    rect, flag composition, the OR-cannot-express-LEFT/TOP case, a raising and a
    None-returning geometry lookup, and one end-to-end through the installed wrapper with
    a fake `win32` asserting user32 is handed the clamped anchor). Suite: **1902 passed**.
    Version bumped to **0.5.1** in `config.py` + `pyproject.toml` — 0.5.0 is already
    published as CURRENT and the publish path refuses a same-version republish.

22. **Lane B can sweep an editor-generated proxy into `.ccsync-trash` (tracked risk,
    2026-08-10, mitigated by default).** Lane B is `rclone sync` — the one verb in this
    system that deletes local files — and it deletes anything under `**/Proxy/**` that
    the NAS does not have. A proxy the companion generates locally for a **synced**
    project is exactly that: the NAS has never seen it, so the next lane-B pass moves it
    into `.ccsync-trash` (recoverable, per DEL-2, but gone from where Resolve looks).
    The loop only closes through the base rig: editor originals go up lane A, the base
    rig's `local_root` IS the NAS tree, and a proxy made there fans back out over lane B
    to everybody.

    Mitigated, not fixed: `proxy_gen_enabled` is **tri-state and derived** — absent means
    `not lane_b_enabled`, so generation is ON where the result lands on the NAS and OFF
    where lane B would sweep it. Editors still get the notifier, and an editor who sets
    `proxy_gen_enabled = true` explicitly keeps proxies for projects lane B does not
    manage and loses them for the ones it does (the generated config says so next to the
    key). Revisit only if editor-side generation is ever wanted for synced projects: that
    needs the generated file to reach the NAS, i.e. a lane A rule change (`+ **/Proxy/**`
    upward), which is a far bigger decision than this feature.

23. **The generated proxy's timecode / `LinkProxyMedia` attach is UNVERIFIED against a
    real Resolve (ship-blocker for the editor rollout, 2026-08-10).** Resolve refuses a
    proxy whose timecode does not match the original (`proxy_relink.py:35-37`), and an
    mp4 written without `-timecode` starts at 00:00:00:00. `own_proxy_cmd` therefore
    passes `-map_metadata 0` plus the ffprobe-read source timecode, and omits the flag
    entirely when the source claims none — but **that is reasoning, not evidence**: no
    generated proxy has yet been attached by a real Resolve. Until one has, the feature
    stays base-rig-only by the derived default in item 22.

    What has to be proven, on the base rig, before any editor rollout: (1) a generated
    own-footage proxy probes as HEVC Main-10 with the `hvc1` tag and the source
    timecode; (2) Resolve's adjacent-`Proxy/` auto-link picks it up on a clip with no
    proxy attached; (3) `proxy_relink.py`'s `LinkProxyMedia` accepts it on a clip
    carrying a stale absolute proxy path; (4) a preview-tier proxy is byte-flag-identical
    to one the b-roll indexer's `build_proxy` produces. Failure of (1)–(3) means the
    generator is making files nothing will attach — visible only as Media Offline beside
    a perfectly good proxy, which is the exact failure `proxy_relink.py` exists for.

24. **The proxy generator could not encode a single clip — no `-f mp4`, `.partial`
    destination (found live on the base rig, fixed 2026-08-11).** `own_proxy_cmd` and
    `preview_proxy_cmd` passed no output format, and the generator's destination is
    `<name>.mp4.partial` (item 22's two-writers rule) — ffmpeg chooses the muxer from the
    extension, ".partial" names none, and every encode exited `EINVAL` at muxer init
    before one frame. Overnight 2026-08-10→11 on 0.6.1 the base rig attempted its whole
    1040-clip queue — 6290 ffmpeg spawns, 978 clips failed to the retry cap, **zero
    proxies made**. Reproduced in isolation: the identical argv fails on a
    `.mp4.partial` destination and succeeds with `-f mp4`.

    Never caught earlier because (a) no test runs a real ffmpeg (deliberate — see
    test_ffmpeg_tools.py's header) and the argv pins simply pinned the bug, (b) the
    b-roll indexer this spec was copied from writes straight to `<name>.mp4` so never
    needed the flag, and (c) the give-up log line kept only the LAST three stderr lines
    — ffmpeg explains this failure in the FIRST ("Unable to choose an output format"),
    so the log showed boilerplate. Fixed by appending `-f mp4` to both builders (an
    output option, before the destination; changes no output byte, so preview parity
    with the indexer holds), regression-pinned on a literal `.mp4.partial` destination,
    and the failure log now keeps five lines/500 chars. Item 23's live-proof gate exists
    for exactly this class; it still has not been run — the encode half is now proven
    only as far as "ffmpeg accepts the argv", and the Resolve-attach half remains open.
    Version bumped to **0.6.2** (0.6.1 is published as CURRENT; same-version republish
    is refused). The failure cap is in-process only, so the fleet retries everything on
    the upgrade restart with no state to clear.

Session-2 macOS findings in full — MAC-6 through MAC-9, what is now proven on real
hardware, and the outstanding list these items come from — are written up in
`docs/macos-first-run-2026-08-05.md`.
