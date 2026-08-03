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
   command `tools/release_macos.sh`. **None of it has run on a Mac yet** — every
   macOS-only path (diskutil, launchctl, xattr, pyobjc, the Resolve preference edit) is
   written from documentation, not from a live run. Treat macOS as code-complete, not
   validated, until the supervised first-session checklist in
   `installer/MACOS_FIRST_RUN.md` has been walked end to end.
