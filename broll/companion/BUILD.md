# Building "BRoll Companion" one-file executables

PyInstaller does not cross-compile — build on each target OS separately.
This has **not** been run/verified in this environment (per task instructions);
run these yourself and sanity-check the resulting binary before shipping.

## Prerequisites (both OS)

```
cd companion
python -m venv .venv
```

Windows:
```
.venv\Scripts\activate
pip install -e .[dev]
pip install pyinstaller
# optional tray icon support:
pip install -e .[tray]
```

macOS:
```
source .venv/bin/activate
pip install -e '.[dev]'
pip install pyinstaller
# optional tray icon support:
pip install -e '.[tray]'
```

## Build

From `companion/`, with the venv active:

```
pyinstaller build.spec
```

Output: `dist/BRoll Companion` (macOS, no extension) or
`dist/BRoll Companion.exe` (Windows) — a single-file executable with no
external Python dependency.

If pystray/Pillow were installed when you ran `pyinstaller`, the tray icon
is bundled in; if not, the build still succeeds and the app runs headless
(console log lines only). `build.spec` detects this automatically at build
time.

## One-liners

Windows (PowerShell), from `companion/`:
```powershell
.venv\Scripts\python.exe -m PyInstaller build.spec
```

macOS (bash/zsh), from `companion/`:
```bash
.venv/bin/python -m PyInstaller build.spec
```

## Notes

- The output is named "BRoll Companion" per the task brief; PyInstaller will
  add the platform-appropriate extension.
- `console=True` in build.spec keeps a visible console window with the
  `[companion] ...` log lines, since that's the only feedback mechanism when
  running headless (no tray icon). Flip to `console=False` once/if a tray
  icon becomes mandatory for your rollout.
- Re-run `pyinstaller build.spec` (not `pyinstaller --onefile ...` from
  scratch) so the hidden-import detection for pystray/Pillow stays in sync
  with build.spec.
