# onboarding — all-in-one Windows installer wizard

A single guided GUI installer (`onboard.exe`) for **fresh machines AND
machines with any previous install state** — it removes every trace of
older CCSync versions (old exe copies in all historical locations,
autostart entries, the subst logon task, shim files), unmounts and
remounts the P: drive (editor role), and installs the current companion,
which self-updates from the dashboard from then on. It **gates on account
verification** — an editor without valid TrueNAS credentials cannot get
past the sign-in page, so nothing installs under a bogus identity.

The wizard asks whether the machine is a **REMOTE EDITOR** or the **BASE
rig**. Base mode installs only the companion (config `mode = "base"`, LAN
dashboard URL) and deliberately never touches drive mappings, Tailscale,
Syncthing, or rclone. What's always preserved, both roles: the Syncthing
device identity (`%LOCALAPPDATA%\ccsync\syncthing-config` — no admin
re-approval), `~/.ssh/ccsync_ed25519*`, and existing `config.toml` values
the installer doesn't own (it merges, not replaces).

This directory does not modify `companion/`, `dashboard/`, or `server/` —
it only reads from `companion/src/ccsync_companion` (identity.py/config.py/
theme.py) and invokes `installer/windows_bootstrap.ps1` as a subprocess.

## Files

- `onboard.py` — the tkinter wizard (GUI). Thin: layout and wiring only.
- `steps.py` — the actual logic, pure/injectable, fully unit tested.
- `build_onboard.spec` — PyInstaller spec producing `onboard.exe`.
- `tests/test_steps.py` — covers every `steps.py` function with fakes; no
  network, no winget/tailscale/powershell processes actually run.

## Wizard flow

1. **Welcome** — what this does + installer/bundled-companion versions.
2. **Role** — REMOTE EDITOR or BASE rig. Sets the dashboard-URL default
   (editor: tailnet `http://100.71.216.3:8480`, base: LAN
   `http://192.168.0.102:8480`; also settable via `CCSYNC_DASHBOARD_URL`
   or the on-page field) and which pages follow.
3. **Tailscale** *(editor only)* — checks whether Tailscale is installed;
   offers a winget install or the download page. "Check connection" runs
   `tailscale status` parsing + a live `GET /api/v1/health` against the
   dashboard. **Next is disabled until both succeed.**
4. **Sign in** — TrueNAS username + password. POSTs to
   `{dashboard_url}/api/v1/verify`. **This is the gate**: on failure the
   wizard shows the error and does not advance. On success it holds the
   verified username, identity token, role, and shared report token in
   memory.
5. **Install** — first the **clean-slate phase** (kills companion/syncthing
   processes, removes all four historical autostart Run values, the
   `CCSync-SubstP` task, old exe copies + `.old`/`.new` files everywhere,
   shim files; editor role also unmounts P: via both `subst /D` and
   `net use /delete`). Then `config.toml` is written/merged and
   `identity.json` written — BEFORE anything launches the companion.
   Editor: `windows_bootstrap.ps1` runs (remounts P: fresh, re-registers
   the logon task, installs tools, installs the companion to
   `%LOCALAPPDATA%\ccsync\bin`, launches it). Base:
   `steps.install_companion()` + autostart + launch, nothing else.
   Editor installs refuse to run when onboard.exe itself lives on P: or a
   network share (it would unmount its own drive, and running it off the
   NAS locks the file for everyone — seen live 2026-07-25).
6. **Finish** — editor: Syncthing device ID + SSH public key with Copy
   buttons; base: success + dashboard link.

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

## Running the tests

```powershell
cd onboarding
python -m pytest tests -q
```

`tests/conftest.py` puts both `onboarding/` (for `import steps`) and
`companion/src/` (for `from ccsync_companion import identity, config`) on
`sys.path`, so no install step is required first. All 35 tests are pure —
they inject fake `http_post`/`http_get`/`run` callables and never touch the
network, the filesystem outside of `tmp_path`, or a real subprocess.

## Notes / things left for a human

- **Not built here**: `onboard.exe` itself was not produced by this task
  (no PyInstaller run) — only documented above. Build it before handing a
  package to an editor.
- **Code signing / SmartScreen**: unaddressed, see above.
- **Icon**: `build_onboard.spec` has `icon=None`; add a `.ico` if wanted.
