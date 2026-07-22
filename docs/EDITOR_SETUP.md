# Editor Setup -- Creators Club Sync

Step-by-step for a remote editor joining a project. Read this once, top to
bottom; most of it is one-time setup.

## 0. Before you start

You'll need, from the admin:
- Your TrueNAS username (they set this up with `server/setup_editor_account.py`).
- The tailnet hostname/IP of the NAS (something like `truenas.tailXXXX.ts.net`
  or a `100.x.y.z` address).
- The Resolve Project Server database name + credentials for the project(s)
  you're joining.

## 1. Install Tailscale and join the tailnet

The bootstrap script (step 2) installs the Tailscale client but does not
log it in -- that's an interactive one-time step:

```
tailscale up
```

This opens a browser window to authenticate. Once you're logged in, tell
the admin so they can confirm your device shows up as connected on their
tailnet and that it's getting a **direct** connection to the NAS, not a
relayed (DERP) one -- direct matters a lot for Resolve's database
responsiveness (see "Flaws" #5 in `../SPEC.md`).

## 2. Run the bootstrap script

**Windows:**
```powershell
powershell -ExecutionPolicy Bypass -File installer\windows_bootstrap.ps1 -TailnetHost <tailnet-host> -EditorName <your-username>
```

**Mac:**
```bash
./installer/macos_bootstrap.sh --tailnet-host <tailnet-host> --editor-name <your-username>
```

This installs rclone + Syncthing, creates your local sync root
(`C:\Creators_Club` on Windows, `~/Creators_Club` on Mac), maps `P:` (or
prepares the LaunchAgent for `~/Creators_Club` on Mac), and writes an
rclone remote config template. It prints your **Syncthing device ID** at
the end -- copy that.

If it warns that your SSH private key doesn't exist yet, generate one and
send the admin the `.pub` half:

```
ssh-keygen -t ed25519 -f ~/.ssh/ccsync_ed25519
```
(Windows: same command works in PowerShell/Git Bash; the key path the
bootstrap script expects is `%USERPROFILE%\.ssh\ccsync_ed25519`.)

## 3. Send the admin your Syncthing device ID

The admin runs `server/accept_device.py` once per project you need access
to. Nothing syncs on lane C (audio/GFX/AE/subs/docs) until this happens.

## 4. Connect DaVinci Resolve to the Project Server

Resolve's Project Manager -> the database selector (usually a small icon in
the top-left of Project Manager, or **File > Project Server Login**
depending on version) -> **Connect to a Database** (or **+** to add one):

- **Database Type:** PostgreSQL
- **Server:** the tailnet hostname/IP the admin gave you
- **Port:** `5432`
- **User** / **Password:** given to you by the admin

Once connected, the shared project(s) should appear in Project Manager
exactly as they do for every other editor -- same bins, same timelines.

## 5. Playback -> Proxy Handling -> Prefer Proxies

In the Resolve menu bar: **Playback > Proxy Handling > Prefer Proxies**.
This makes Resolve play the locally-synced H.264 proxy for any clip whose
camera original isn't on your machine (it won't be, for anything you
didn't shoot/add yourself -- proxies travel down to you, originals travel
up from whoever added them). The host machine (Alex's) is configured the
opposite way (prefers camera originals) since it holds everything locally.

## 6. Mac only: Mapped Mount preference (manual, one-time)

Resolve's scripting API cannot set this -- it's a manual step, and the
companion app can only *detect* if it's missing, not fix it.

All paths in the shared database are stored in the **Windows-style form**
`P:\Projects\<year>\<series>\<project>\...` (since that's the host's path
convention). On your Mac, the same files live under `~/Creators_Club/...`.
Resolve's **Mapped Mount** feature is what lets a Mac resolve `P:\...` paths
to your local `~/Creators_Club` folder.

**DaVinci Resolve > Preferences (Cmd+,) > Media Storage tab**, find the
**Mapped Mount** section (older/newer Resolve versions may label this
slightly differently -- look for a table that maps one filesystem path to
another; that's it):

1. Click **Add Mount** (or the `+` under that table).
2. **Local Path** (or "Actual Path" -- whatever the left/first column is
   called): browse to `/Users/<you>/Creators_Club` (i.e. `~/Creators_Club`).
3. **Mapped Path** (or "Remote Path" -- the right/second column): enter it
   in the Windows-style form the database uses: `P:\`
4. Save / close Preferences.

To sanity-check it worked: open a timeline that has a clip whose stored
path is `P:\Projects\...`, and confirm it plays (via proxy) without a
manual relink prompt. If Resolve prompts you to locate the file, the
mapping isn't right yet -- double check the two path forms above are typed
exactly as shown (trailing colon+backslash on the mapped side matters).

The companion app checks this at startup by asking Resolve for a timeline
clip's resolved path and confirming it lands inside your local
`~/Creators_Club`; if it doesn't, you'll get a "mapping looks wrong" tray
warning pointing you back to this section.

## 7. You're set up. What to expect day to day

- Anything you drop into your local project folder under `Audio/`,
  `AE/`, `Subs/`, etc. syncs both ways automatically (Syncthing, lane C).
- Video you add (in `B-roll/`, `Interviewees/`, etc., outside any `Proxy/`
  folder) uploads to the NAS automatically but does **not** download to
  other editors as originals -- only its generated proxy comes back down,
  once Alex's PC has generated one (this can take minutes to hours; the
  tray app shows the upload/proxy-wait queue).
- If you add a clip to a timeline from somewhere *outside* your synced
  project folder (e.g. straight off your Desktop), the companion app pops
  up a dialog listing the offending clip(s) with a suggested destination
  (editable) and a **Fix** button that copies the file into the tree,
  relinks the clip, and queues the upload for you. There's also an
  **Ignore** option (per-session) if you don't want to deal with it right
  now.
- **Never reorganize/rename/delete folders on your own machine and expect
  it to reflect back to the NAS for video files.** Lane A (your uploads)
  never deletes anything on the NAS, by design (archival safety net) -- so
  a local rename/move just creates a second copy on the server under the
  new name, and the old one sits there as an orphan. If a project needs
  reorganizing, ask the admin to do it server-side (see
  `../docs/SERVER.md`). This does **not** apply to the Syncthing lane
  (audio/AE/subs/etc.) -- renames and deletes there do propagate, and
  the server keeps a versioned trash so nothing's truly gone.
