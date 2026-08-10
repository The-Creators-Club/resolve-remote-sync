# BRoll Companion

A small local agent editors run alongside DaVinci Resolve. It listens on
`127.0.0.1:8899` and lets the b-roll web search UI insert a selected clip
straight into your current Resolve timeline — no manual import required.

## Requirements

- **DaVinci Resolve Studio** (the free version does not expose the scripting
  API used here).
- Resolve's external scripting API must be enabled:
  **Resolve → Preferences → System → General → External scripting using:
  set to `Local`.** Restart Resolve after changing this.
- Python 3.12 if running from source (skip this if you were given a prebuilt
  `BRoll Companion` executable — see `BUILD.md`).

## Install & run (from source)

```
cd companion
python -m venv .venv
```

Windows:
```
.venv\Scripts\activate
pip install -e .
broll-companion
```

macOS:
```
source .venv/bin/activate
pip install -e .
broll-companion
```

(Optional tray icon instead of a console window: `pip install -e '.[tray]'`
first — needs `pystray` + `Pillow`. Works headless without them.)

You should see:
```
[companion] BRoll Companion v0.1.0 listening on http://127.0.0.1:8899
[companion] config: C:\Users\you\.broll-companion.json
[companion] mounts: {}
```

Leave this running in the background while you edit. Close the window /
Ctrl+C to stop it (or use the tray icon's Quit if installed).

## First run: set your mount

On first run, the companion writes two files to your home directory:

- `~/.broll-companion.json` — the actual config (edit this).
- `~/.broll-companion.README.txt` — a plain-text explanation of each field,
  since JSON can't hold comments.

Edit `~/.broll-companion.json` and fill in `mounts` — this maps each share
name used by the web UI to wherever that share is mounted on **your**
machine:

```json
{
  "server_url": "http://127.0.0.1:8000",
  "mounts": {
    "broll": "B:/"
  }
}
```

- **Windows** example: `"broll": "B:/"` (or `"Y:/broll"` if the share root
  itself lives a level down on the drive).
- **macOS** example: `"broll": "/Volumes/broll"`.

On macOS, if you don't add an entry for a share, the companion will also try
`/Volumes/<share>`, `/Volumes/<share>-1`, `/Volumes/<share>-2` automatically
(handles Finder's "already mounted" renaming) — but an explicit entry always
wins if present.

Restart the companion after editing the config.

## How insert works

When you hit Enter (or click Insert) in the web UI on a clip with an in/out
selection, it POSTs to `http://127.0.0.1:8899/insert`. The companion:

1. Translates `(share, rel_path)` to a local path using your `mounts` config.
2. Checks the file actually exists there.
3. Connects to a running DaVinci Resolve.
4. Finds (or creates) a bin named **B-Roll** at the root of your media pool.
5. Reuses the clip if it's already been imported into that bin (matched by
   file path), otherwise imports it.
6. Appends it to your **currently open timeline**, trimmed to the in/out
   points you picked, using in/out frame numbers translated from the
   original clip's fps.

If anything's missing (Resolve not running, no project open, no timeline
open, file not found, mount not configured), the web UI shows a plain-English
message instead of silently failing — nothing here should ever crash the
companion process itself.

`mode: "playhead"` (insert at playhead instead of appending) is reserved for
a future version and currently returns "not implemented yet".

## Troubleshooting

- **"DaVinci Resolve is not running"** — start Resolve. The companion
  connects lazily on each request; it doesn't launch Resolve for you.
- **"no project open in Resolve"** / **"no timeline open — create one
  first"** — open/create one in Resolve, then retry the insert.
- **"no mount configured for share '...'"** — add that share to `mounts` in
  `~/.broll-companion.json` and restart.
- **"file not found at ... — is the share mounted?"** — the mapped
  drive/volume isn't actually connected right now, or the path inside it is
  wrong.
- Nothing responds on port 8899 at all — check the console window / tray
  icon is actually running, and that no firewall rule blocks
  127.0.0.1:8899 (it's loopback-only, so this is rare).

## Development

Tests: `pip install -e '.[dev]'` then `pytest` from `companion/`. DaVinci
Resolve interaction is fully mocked in tests — nothing here launches or
connects to a real Resolve instance.

Packaging into a one-file executable: see `BUILD.md`.
