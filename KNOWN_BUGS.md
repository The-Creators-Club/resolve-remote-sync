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
   queue and drain. (b) B9 liveness thresholds are being promoted to config keys
   (defaults unchanged).
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

9. **The macOS wizard build will break on PyInstaller 7.** `onboarding/build_onboard_macos.spec`
   builds a `.app` bundle in **onefile** mode, and PyInstaller 6.21 now warns:
   *"Onefile mode in combination with macOS .app bundles (windowed mode) don't make sense
   … and clashes with macOS's security. Please migrate to onedir mode. This will become an
   error in v7.0."* It builds and runs today — 1.0.17 was built, published and verified
   end-to-end on 2026-08-04 (downloaded from `[ INSTALLER ]`, unzipped, `codesign --verify
   --deep --strict` passes). But the next PyInstaller major turns this into a hard failure,
   and the only machine that can build this artifact is a Mac, so it would surface as a
   broken release on the one path with no fallback. Migrate the spec to onedir before any
   v7 upgrade; the zip shape the dashboard serves does not change (a onedir `.app` is still
   a directory tree inside the same zip).

10. **The publish scripts cannot survive a password containing control characters.**
    `tools/release_macos.sh:92` and `tools/build_onboard_macos.sh:241` share
    `json_escape()`, which escapes backslashes and double quotes only, and the login body
    is assembled with `printf`. A password carrying any byte < 0x20 therefore produces
    invalid JSON, and the dashboard answers `422 json_invalid / "Invalid control character
    at"` — which reads as "wrong password" and is not. Hit live on 2026-08-04: the reported
    offset is the *byte position* of the offending character (verified against the live
    endpoint: a control char first/middle/last in the value reports 31/35/37 for
    `{"username":"alex","password":"…"}`), so offset 31 means the FIRST byte of the
    password. The usual source is a bracketed paste — zsh wraps pasted text in
    `ESC[200~ … ESC[201~` and `read -r -s` captures the escapes. Typing the password works;
    the scripts should strip the paste wrappers and reject any remaining non-printable byte
    with a sentence naming the problem, since stripping alone would turn a 422 into a
    misleading 401.

    **MAC-8, critical — FIXED in installer 1.0.18:** the same class of defect took the
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

11. **Lane C has never run on macOS — the pairing is one-sided.** Everything the installer
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

12. **Both rclone lanes sync macOS AppleDouble sidecars (`._*`) — VERIFIED 2026-08-04.**
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

13. **MAC-9, critical: the installer emptied rclone.conf on macOS — FIXED in 1.0.18.**
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
