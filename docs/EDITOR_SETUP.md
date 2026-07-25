# Editor Setup -- Creators Club Sync

Step-by-step for a remote editor joining a project. Read this once, top to
bottom; most of it is one-time setup.

## 0. Before you start

You'll need, from the admin:
- Your TrueNAS username (they set this up with `server/setup_editor_account.py`).
  It is **lowercase** and case-sensitive.
- The tailnet hostname/IP of the NAS (something like `truenas.tailXXXX.ts.net`
  or a `100.x.y.z` address).
- The Resolve Project Server database name + credentials for the project(s)
  you're joining.
- Which project(s) you're on, so you can fill in `projects` and
  `active_project` in `~/.ccsync/config.toml` (the bootstrap script can't
  know these).

You'll also want a drive with real headroom for the local sync root --
originals you add and every proxy that comes down both live there. If your
system drive is tight, use `-LocalRoot` (step 2) to put it elsewhere.

> **Do not map any NAS share to a drive letter of your own.**
> This one is worth reading before you start; see the warning in section 2.1.

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

Add `-LocalRoot F:\Creators_Club` (any drive you like) if your system drive
is short on space. An **elevated** PowerShell is preferred -- without it the
script can't register a scheduled task and falls back to a registry autostart
entry instead. Either way it completes; it just tells you which path it took.

**Mac:**
```bash
./installer/macos_bootstrap.sh --tailnet-host <tailnet-host> --editor-name <your-username>
```

This installs rclone + Syncthing, creates your local sync root, maps `P:` to
it (Windows) or prepares the Mapped Mount (Mac), starts the Syncthing daemon
and sets it to start at logon, writes an rclone remote config template, and
seeds `~/.ccsync/config.toml`. It prints your **Syncthing device ID** at the
end -- copy that.

On Windows, `P:` shows up in Explorer as **TheCreatorsClub** so you can tell
it apart from your own drives at a glance. Only project material belongs in
there. (The name is cosmetic and per-user; Explorer may need a restart to
show it.)

### 2.1 Do NOT map any NAS share to another drive letter

This is the single easiest way to silently break the whole design, and it
produces no error message of any kind.

Every clip path in the shared Resolve database is stored with the **host's**
drive letter. If you `net use` (or otherwise mount) a NAS share to a letter
that collides with one of those stored paths, Resolve will happily resolve
those absolute paths straight against the live SMB mount -- and stream
**full-resolution camera originals** over the tailnet for every playback.
No warning, no relink prompt. Your local proxies and `P:` are simply ignored,
and it just feels inexplicably slow.

Concretely:

- `P:` is reserved. The bootstrap script owns it.
- **Do not map `T:`** -- it has been observed to collide with host-side paths
  stored in the database.
- Before mapping *any* NAS share to *any* letter, ask the admin which letters
  the host machine uses locally, and avoid those. If you don't actually need
  a second mount, don't create one -- everything you need arrives via `P:`.
- On Mac the same hazard applies to mounting the NAS over SMB alongside your
  Mapped Mount.

If playback is unexpectedly slow, or the tray app shows little sync activity
while Resolve is clearly pulling data, check your mapped drives first
(`net use` on Windows, `mount` on Mac).

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

## 3.5 About `~/.ccsync/config.toml`

The bootstrap script fills in everything needed for syncing: `editor_name`,
`local_root`, `remote`, `remote_root`. **You do not need to list projects.**

The whole tree replicates. Lanes A and B sync `local_root` against
`remote_root` as complete trees, so the server's structure is mirrored
verbatim, whatever it contains:

```
Creators_Club/Projects/<year>/<series>/<project>/...
```

for example `Projects/2026/Creator Profiles/Season 1` alongside
`Projects/2025/FF4/Nuclear` — any year, any series, any project, added at any
time, with no config change on your side. Spaces in names are fine.

Two optional keys exist and are easy to misread:

| Key | What it actually does |
|---|---|
| `active_project` | Only the destination the popup fixer suggests when you add media from outside the tree. Blank just means it suggests the tree root. |
| `projects` | Only pairs positionally with `syncthing_folder_ids` for lane C's folder-ID check. Nothing to do with what syncs. |

One value worth understanding if you ever hand-edit it: `remote_root` must be
an **absolute** NAS path (`/mnt/tank/TheCreatorsPool/Creators_Club`). SFTP
sessions start in your home directory on the NAS, so a relative value like
`Creators_Club` quietly means `~/Creators_Club` -- a directory that doesn't
exist -- rather than the shared tree.

The companion validates its config at startup and writes anything wrong to
`~/.ccsync/companion.log`, separating problems that stop syncing from ones
that merely degrade the popup. If something isn't syncing, read that first.

If the admin runs the sync dashboard, they will also give you two values to
add here: `dashboard_url` (e.g. `http://<tailnet-ip>:8480`) and
`dashboard_token`. With those set, your companion reports its lane status to
the dashboard once a minute so the admin can see sync health without asking
you. Leaving `dashboard_url` blank disables this entirely.

**Choosing what syncs (dashboard login).** Open the dashboard in a browser
and sign in with your TrueNAS username and password. Tick the projects you
want on this machine -- they sync **one at a time, in the order you ticked
them**, and the dashboard shows live speed, files remaining, and ETA for
the current one. Unticking stops that project syncing to you; files already
on your disk stay there (delete them yourself if you need the space).
Nothing syncs until you tick at least one project. With `dashboard_url` set,
the companion follows your ticks automatically; if the dashboard is
unreachable it keeps using the last selection it saw.

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
  now. The popup only sees clips on the **current timeline** — for media
  you imported into bins but haven't cut in yet, use the tray's **Scan
  whole project** to check the entire media pool at once.
- **Onboarding a project you already started** (media scattered around your
  own disk before you joined the sync system): use the tray's **Consolidate
  pre-existing project…**. It scans the whole media pool, shows a report of
  how much will be copied into the project folder and uploaded to the NAS,
  and — once you confirm — copies every out-of-tree clip into the tree,
  relinks Resolve, then uploads the originals and pulls any proxies. Your
  scattered originals are **copied, never moved**, so nothing is at risk;
  delete the old copies yourself once you've confirmed everything's up.
- **Never reorganize/rename/delete folders on your own machine and expect
  it to reflect back to the NAS for video files.** Lane A (your uploads)
  never deletes anything on the NAS, by design (archival safety net) -- so
  a local rename/move just creates a second copy on the server under the
  new name, and the old one sits there as an orphan. If a project needs
  reorganizing, ask the admin to do it server-side (see
  `../docs/SERVER.md`). This does **not** apply to the Syncthing lane
  (audio/AE/subs/etc.) -- renames and deletes there do propagate, and
  the server keeps a versioned trash so nothing's truly gone.
