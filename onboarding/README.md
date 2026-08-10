# onboarding — all-in-one installer wizard (Windows + macOS)

A single guided GUI installer (`onboard.exe` on Windows, `CCSync
Onboarding.app` on macOS) for **fresh machines AND machines with any
previous install state** — it removes every trace of older CCSync versions
(old binaries, autostart entries; on Windows also the subst logon task and
shim files, on macOS the two LaunchAgents), unmounts and remounts the P:
drive (Windows editor role), and installs the current companion, which
self-updates from the dashboard from then on. It **gates on account
verification** — an editor without valid TrueNAS credentials cannot get
past the sign-in page, so nothing installs under a bogus identity — and on
a live tailnet **connection check** before that. Those are the two gates
whose absence from the Terminal-only macOS route caused the worst support
incidents (see `docs/macos-onboarding-handoff.md` §2).

On both platforms the wizard asks whether the machine is a **REMOTE
EDITOR** or the **BASE rig** — today's studio base rig is Windows, but the
commercial deployments this is built for can run a Mac as the base rig.
Base mode installs only the companion (config `mode = "base"`, LAN
dashboard URL) and deliberately never touches drive mappings / NAS mounts,
Tailscale, Syncthing, or rclone; on macOS its autostart is a LaunchAgent
(the same plist shape `macos_bootstrap.sh` writes for editors) instead of
an HKCU Run value, and its default tree is the NAS share mounted under
`/Volumes`. What's always preserved, all roles and platforms: the Syncthing
device identity (`%LOCALAPPDATA%\ccsync\syncthing-config` /
`~/.local/ccsync/syncthing-config` — no admin re-approval),
`~/.ssh/ccsync_ed25519*`, and existing `config.toml` values the installer
doesn't own (it merges, not replaces).

This directory does not modify `companion/`, `dashboard/`, or `server/` —
it only reads from `companion/src/ccsync_companion` (identity.py/config.py/
theme.py) and invokes `installer/windows_bootstrap.ps1` (or
`installer/macos_bootstrap.sh` on darwin) as a subprocess.

## Files

- `onboard.py` — the tkinter wizard (GUI), both platforms. Thin: layout
  and wiring only.
- `steps.py` — the actual logic, pure/injectable, fully unit tested;
  platform-keyed functions take an injectable `platform`.
- `build_onboard.spec` — PyInstaller spec producing `onboard.exe`.
- `build_onboard_macos.spec` — PyInstaller spec producing
  `CCSync Onboarding.app` (build on a Mac; see below).
- `tests/test_steps.py` / `tests/test_cleanup_steps.py` — cover every
  `steps.py` function with fakes; no network, no winget/tailscale/
  powershell processes actually run.
- `tests/test_macos_steps.py` — every darwin branch, runnable on any host,
  plus source-level pins of the `macos_bootstrap.sh` wizard contract
  (CAPABILITY MISSING: marker, exit 3, RESOLVE-MAPPING-STATUS) and the
  four-way installer-version parity.

## Wizard flow

1. **Welcome** — what this does + installer/bundled-companion versions.
2. **Role** — REMOTE EDITOR or BASE rig, both platforms. Sets the
   dashboard-URL default (editor: tailnet `http://100.71.216.3:8480`,
   base: LAN `http://192.168.0.102:8480`; also settable via
   `CCSYNC_DASHBOARD_URL` or the on-page field), the local-root default
   (base on macOS: the NAS share mount under `/Volumes`) and which pages
   follow.
3. **Tailscale** *(editor only)* — checks whether Tailscale is installed;
   offers a winget install (Windows) or the download page. "Check
   connection" runs `tailscale status` parsing (on macOS falling back to
   the CLI inside `/Applications/Tailscale.app`, which is never on PATH)
   + a live `GET /api/v1/health` against the dashboard. **Next is
   disabled until both succeed.**
4. **Sign in** — TrueNAS username + password. POSTs to
   `{dashboard_url}/api/v1/verify`. **This is the gate**: on failure the
   wizard shows the error and does not advance. On success it holds the
   verified username, identity token, role, and shared report token in
   memory. On macOS a `base`-verified account is refused here.
5. **Install** — first the **clean-slate phase**. Windows: kills
   companion/syncthing processes, removes all four historical autostart
   Run values, the `CCSync-SubstP` task, old exe copies + `.old`/`.new`
   files everywhere, shim files; editor role also unmounts P: via both
   `subst /D` and `net use /delete`. macOS: boots both CCSync
   LaunchAgents out of launchd, kills only processes running our binaries
   (a Homebrew Syncthing is left alone, INST-20), removes the plists and
   old companion binaries from `~/.local/ccsync/bin` — there is no drive
   to unmount. Then `config.toml` is written/merged and `identity.json`
   written — BEFORE anything launches the companion.
   Editor: the platform bootstrap runs (`windows_bootstrap.ps1`: remounts
   P: fresh, re-registers the logon task, installs tools, installs the
   companion to `%LOCALAPPDATA%\ccsync\bin`, launches it;
   `macos_bootstrap.sh`: installs rclone/Syncthing, writes + loads both
   LaunchAgents, installs the bundled companion via `--companion-file`,
   sets Resolve's Mapped Mount). Base: `steps.install_companion()` +
   autostart + launch, nothing else (autostart = HKCU Run value on
   Windows, LaunchAgent write + `launchctl` load on macOS).
   Editor installs refuse to run when onboard.exe itself lives on P: or a
   network share (it would unmount its own drive, and running it off the
   NAS locks the file for everyone — seen live 2026-07-25).
6. **Finish** — editor: Syncthing device ID + SSH public key with Copy
   buttons; base: success + dashboard link. On macOS a failed Resolve
   Mapped Mount write ("Resolve was running", "never launched", …) is
   surfaced here as a warning via the bootstrap's
   `RESOLVE-MAPPING-STATUS:` marker, not buried in the log.

## Building onboard.exe

```powershell
cd onboarding
python -m venv .venv
.venv\Scripts\activate
pip install pyinstaller
pyinstaller build_onboard.spec
```

Output: `dist\onboard.exe` (ONEFILE build — a single exe bundling the
bootstrap script and the companion exe; nothing else to hand out). The
normal path is `installer\build_editor_package.ps1 -RebuildExe
-RebuildOnboard`, which rebuilds both exes in the right order and reports
staleness — onboard.exe bundles the companion, so it must be rebuilt
whenever the companion is.

`steps.find_bootstrap_script()` looks for `windows_bootstrap.ps1` in this
order: an explicit override, PyInstaller's `sys._MEIPASS` extraction dir,
next to `onboard.exe` itself, then (dev tree only) next to `steps.py` or in
`../installer/`. The spec's `datas` entry bundles it at the top level of
the frozen app, matching the second case.

No code signing is set up — Windows SmartScreen will likely warn on first
run of an unsigned `onboard.exe` from a fresh machine; that's expected and
not something this task addresses.

## Building CCSync Onboarding.app (macOS)

On a Mac, after `./tools/release_macos.sh` has produced
`companion/dist/ccsync-companion` (the wizard bundles it and refuses to
build without it):

```bash
./tools/build_onboard_macos.sh
```

That script checks installer-version parity, verifies the companion binary
against its `ccsync-release.json`, runs PyInstaller with
`build_onboard_macos.spec`, confirms the signature (`codesign -dv`, then
`--verify --deep --strict` on the bundle *and* on the unzipped copy), and
produces `dist/CCSync Onboarding.app` plus a `ditto`-zipped
`dist/ccsync-onboard-macos-<version>.zip`.

**ONEDIR since 2026-08-05 — the first Mac build after that change has not
happened yet.** The spec used to build the `.app` in onefile mode, which
PyInstaller 6.21 warns about and 7.0 rejects outright (KNOWN_BUGS item 9);
it is now `EXE(exclude_binaries=True)` → `COLLECT` → `BUNDLE`. Nothing
downstream changes — the shipped artifact is still the same `.app` inside the
same `ditto` zip, and `sys._MEIPASS` still holds `macos_bootstrap.sh`, the
companion binary and `ccsync_companion/assets/icon.png` (it now points at
`<app>/Contents/Frameworks`, with data files cross-linked in from
`Contents/Resources`) — but it has only been verified by reading PyInstaller
6.21's bundle-assembly code on Windows. Watch the build, and re-walk the
wizard step of `installer/MACOS_FIRST_RUN.md` (§C) before publishing.
Also true of everything else macOS here: the first build and first
double-click are checklist items, not assumptions.

Side effect of onedir: `dist/ccsync-onboard/` now exists as a plain build
directory next to the `.app`. It is not shipped and nothing reads it.

Gatekeeper: the bundle is ad-hoc signed (mandatory on Apple silicon — an
unsigned arm64 binary is killed on launch). If the zip reaches the editor
with the quarantine xattr (browser download, AirDrop), first open needs
System Settings → Privacy & Security → "Open Anyway", once. A `curl`/`scp`
copy carries no quarantine and opens directly.

Distribution: `./tools/build_onboard_macos.sh --publish --make-current`
uploads the zip as the `macos`/`onboard` package — **that is what a Mac's
`[ INSTALLER ]` click downloads by default** (the dashboard names macos
onboard uploads by content: zip magic → `.zip`, anything else → `.sh`, so
pre-1.0.17 script rows keep serving correctly). Windows ships no longer
push `macos_bootstrap.sh` into that slot; `build_editor_package.ps1` only
warns when the channel falls behind the repo's installer version. The
Terminal script remains available inside the editor package on `P:\` and
in this repo.

## Running the tests

```powershell
cd onboarding
python -m pytest tests -q
```

`tests/conftest.py` puts both `onboarding/` (for `import steps`) and
`companion/src/` (for `from ccsync_companion import identity, config`) on
`sys.path`, so no install step is required first. All tests are pure —
they inject fake `http_post`/`http_get`/`run` callables and never touch the
network, the filesystem outside of `tmp_path`, or a real subprocess. The
darwin branches are tested the same way (explicit `platform="darwin"`), so
the full suite runs green on the Windows dev box.

## Notes / things left for a human

- **The macOS wizard has never been built or run** — the spec and build
  script are code-complete but need the Mac (PyInstaller does not
  cross-compile), and the first double-click is behind the same B1
  question (pystray/Tk coexistence does not apply here — the wizard has no
  tray — but Gatekeeper and Tk 9.0 do). See
  `docs/macos-onboarding-handoff.md`.
- **Code signing / SmartScreen / Gatekeeper**: unaddressed beyond ad-hoc
  signing, see above.
