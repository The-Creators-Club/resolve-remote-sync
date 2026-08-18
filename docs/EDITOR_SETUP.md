# Editor Setup -- CC Sync

Step-by-step for a remote editor joining a project. Read this once, top to
bottom; most of it is one-time setup.

CC Sync is a fleet-sync companion **for DaVinci Resolve®**. It **requires
DaVinci Resolve Studio** on this machine: the free edition does not expose the
external scripting interface the companion uses, so the watcher, the fixer,
the relink popup, "Send to Resolve" and the proxy attach all do nothing
without it. DaVinci Resolve and DaVinci Resolve Studio are products of
Blackmagic Design Pty Ltd, licensed to you separately by them; CC Sync is not
affiliated with, endorsed by or sponsored by Blackmagic Design (2026-08-17,
docs/COMMERCIAL_READINESS.md item 3).

## 0. Before you start

**DaVinci Resolve Studio, installed and activated**, with *Preferences →
System → General → External scripting using* set to **Local**. Then, from the
admin:
- Your TrueNAS username (they set this up with `server/setup_editor_account.py`).
  It is **lowercase** and case-sensitive.
- The tailnet hostname/IP of the NAS (something like `truenas.tailXXXX.ts.net`
  or a `100.x.y.z` address).
- The Resolve Project Server database name + credentials for the project(s)
  you're joining.
- The dashboard address and your dashboard token (the admin runs a sync
  dashboard; you pick your projects there).
- Which project(s) you're on -- you tick them on the dashboard once you're
  signed in. There is **no** project list to fill in by hand anywhere; see
  section 3.5.

You'll also want a drive with real headroom for the local sync root --
originals you add and every proxy that comes down both live there. If your
system drive is tight, use `-LocalRoot` (Windows) / `--local-root` (Mac) in
step 2 to put it elsewhere. On a Mac that is normally the external SSD you
edit from; see section 6.2 for what happens when you unplug it.

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
responsiveness.

## 2. Run the bootstrap script

Run this from the folder you were sent (every file it mentions is in there,
side by side).

**Windows** -- open a **normal** PowerShell window. Do **not** use *Run as
Administrator*:
```powershell
powershell -ExecutionPolicy Bypass -File .\windows_bootstrap.ps1 -TailnetHost <tailnet-host> -DashboardUrl <your-dashboard-url> -EditorName <your-username> -DashboardToken <token-from-admin>
```

The script asks for admin rights itself, once, for the one step that needs
them -- approve that prompt. Running the *whole* script elevated is the one
way to break the install silently: a drive mapped from an elevated window is
invisible to your normal session, so Resolve sees no `P:` until you log off
and back on. If you already ran it elevated, log off and on before opening
Resolve.

Add `-LocalRoot F:\<tree root>` (any drive you like) if your system drive
is short on space. Add `-CompanionExeSource .\ccsync-companion.exe` to have
it install the companion (the tray app) for you -- otherwise you'd copy
`ccsync-companion.exe` into `%LOCALAPPDATA%\ccsync\bin\` yourself and run it
from there. Don't keep it anywhere else; that folder is the only one the
script starts at logon.

**Mac** -- get the script from the dashboard: sign in, open the menu (the
three bars at the top left) and click `[ INSTALLER ]`, which downloads
`ccsync-onboard-<version>.sh` to a Mac browser. To fetch the OTHER platform's
package (an admin on Windows setting a Mac up), open `/installer`, which shows
both. Then, in Terminal:
```bash
cd ~/Downloads
chmod +x ccsync-onboard-*.sh
./ccsync-onboard-*.sh --tailnet-host <tailnet-host> --editor-name <your-username> --local-root "/Volumes/<YourSSD>/<tree root>"
```

`--local-root` is the one flag worth getting right: point it at the external
SSD you edit from (see section 6.2). Leave it off and everything lands in
your home folder on the internal disk. `DASHBOARD_TOKEN=<token-from-admin>`
in front of the command is what lets it download and install the companion
app; without it the script sets everything else up and tells you, loudly,
that nothing on the Mac will sync by itself.

Because the file came from a browser it carries macOS's quarantine flag,
which blocks *executing* it. Either clear it once --
`xattr -d com.apple.quarantine ccsync-onboard-*.sh` -- or skip the `chmod`
and run `bash ccsync-onboard-*.sh ...` instead: handing the file to `bash`
as an argument is not an execution of the file, so quarantine does not
apply.

This installs rclone + Syncthing, creates your local sync root, maps `P:` to
it (Windows) or sets Resolve's Mapped Mount for you (Mac, section 6), starts
the Syncthing daemon and sets it to start at logon, writes an rclone remote
config template, seeds `~/.ccsync/config.toml`, and installs the companion
app. It prints your **Syncthing device ID** at the end -- copy that.

Every step checks the current state before acting and says what it did or
skipped, so re-running it is safe and is the normal way to fix a typo'd
flag. A dry run (`-DryRun` on Windows, `--dry-run` on the Mac) prints what it
would do and touches nothing.

On Windows, `P:` shows up in Explorer under your studio's tree name so you can tell
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

The admin approves your machine **once** (they run `server/accept_device.py`
to accept and name the device). They do not share individual projects with
you by hand any more -- which projects reach this machine is decided by the
projects you tick on the dashboard, so approval plus a tick is all it takes.
Until the admin has approved this device, nothing syncs on lane C
(audio/GFX/AE/subs/docs).

## 3.5 About `~/.ccsync/config.toml`

The bootstrap script fills in everything needed for syncing: `editor_name`,
`local_root`, `remote`, `remote_root`. **You do not list projects here** --
you tick them on the dashboard (see below).

**Only the projects you tick sync to this machine**, and they sync **one at
a time, top to bottom in the order you ticked them**, each getting up to
about 10 minutes of transfer per turn before the next one takes over. So a
project further down the list starts moving even while a huge one above it
is still going -- it just takes longer overall. Nothing that isn't ticked is
downloaded at all.

Project folders on the server look like this, and you don't need to know or
configure any of it:

```
<tree root>/Projects/<year>/<series>/<project>/...
```

for example `Projects/2026/Creator Profiles/Season 1` alongside
`Projects/2025/FF4/Nuclear` — any year, any series, any project, added at any
time, with no config change on your side. Spaces in names are fine. A new
project just appears in the dashboard's list, ready to tick.

Two optional keys exist and are easy to misread:

| Key | What it actually does |
|---|---|
| `active_project` | Only the destination the popup fixer suggests when you add media from outside the tree. Blank just means it suggests the tree root. |
| `projects` | Only pairs positionally with `syncthing_folder_ids` for lane C's folder-ID check. Nothing to do with what syncs. |

One value worth understanding if you ever hand-edit it: `remote_root` must be
an **absolute** NAS path (`/mnt/<pool>/<share>/<tree>` on TrueNAS, `/volume1/<share>/<tree>` on Synology). SFTP
sessions start in your home directory on the NAS, so a relative value like
`<tree>` quietly means `~/<tree>` -- a directory that doesn't
exist -- rather than the shared tree.

The companion validates its config at startup and writes anything wrong to
`~/.ccsync/companion.log`, separating problems that stop syncing from ones
that merely degrade the popup. If something isn't syncing, read that first.

Two more values matter here: `dashboard_url` (REQUIRED -- your admin's, e.g.
`http://<tailnet-ip>:8480`) and `dashboard_token`. The bootstrap script
writes both if you passed `-DashboardToken` in step 2; otherwise ask the
admin for the token and either re-run the script with it or add the line by
hand. With them set, your companion reports its lane status to the dashboard
once a minute (so the admin can see sync health without asking you) and,
crucially, picks up the projects you tick. Leaving `dashboard_url` blank
disables both.

**Sign in from the tray first -- this is the switch that turns sync on.**
Right-click the tray icon → **Sign in…** and enter your TrueNAS username and
password. Until the tray says `Signed in as <you>`, nothing syncs. It is a
separate step from signing in to the dashboard in a browser, and it is not
optional: the companion deliberately does nothing until it knows who you
are.

Signing in is also what makes this machine **visible to the admin**. Status
reports are stamped with who you signed in as, and the server rejects
anything unsigned -- so a machine that has never been signed in doesn't
appear on the admin's fleet view at all. If they tell you they can't see
your machine, check the tray says `Signed in as <you>` before anything else.

**Choosing what syncs (dashboard login).** Then open the dashboard in a
browser and sign in with the same username and password. Tick the projects you
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
up from whoever added them). The studio base rig is configured the
opposite way (prefers camera originals) since it holds everything locally.

## 6. Mac only: Mapped Mount preference (set for you; check it once)

All paths in the shared database are stored in the **Windows-style form**
`P:\Projects\<year>\<series>\<project>\...` (since that's the host's path
convention). On your Mac, the same files live under your local root (e.g.
`/Volumes/<YourSSD>/<tree root>/...`). Resolve's **Mapped Mount** feature
is what lets a Mac resolve `P:\...` paths to that folder. There is no `P:`
drive on a Mac and there never will be -- the Mapped Mount does that job.

**The bootstrap script sets this for you.** Resolve has no scripting API for
the preference, but it keeps it in plain-text files the installer can edit,
so a normal run ends with `DONE FOR YOU: Resolve maps P:\ to <your root>`.
Both files are backed up (timestamped, next to the originals) before
anything is written.

It can only do that while **Resolve is quit**, and only if Resolve has been
launched at least once on this Mac. So one of these lines may appear at the
end of the run instead:

- *"NOT DONE -- Resolve was running."* Resolve rewrites its preferences when
  it quits, so an edit made while it is open would be thrown away. Quit
  Resolve completely, then re-run just that step:
  ```bash
  ./ccsync-onboard-*.sh --resolve-mapping-only --local-root "/Volumes/<YourSSD>/<tree root>"
  ```
- *"NOT DONE -- Resolve has never been launched on this Mac."* Resolve
  writes its preference files on its own first run and the installer will
  not invent them. Launch Resolve once, quit it, then run the same
  `--resolve-mapping-only` command above.

`--resolve-mapping-only` touches nothing else -- no NAS, no account, no
sync -- and it is safe to re-run: if the mapping is already right it says
`already maps P:\ to ... -- nothing written` and exits.

**To check it by eye:** DaVinci Resolve > Preferences (Cmd+,) > **Media
Storage**. Your local root should be listed with `P:\` as its mapped path.
Restart Resolve and look again -- if it has vanished, tell the admin (that
would mean Resolve rewrote the file over the top of the edit).

**The real test:** open a timeline with a clip whose stored path is
`P:\Projects\...` and confirm it plays (via proxy) without a manual relink
prompt. If Resolve prompts you to locate the file, the mapping isn't right
yet.

**For the admin -- a read-only check that works with Resolve open.** The
mapping tool is embedded in the bootstrap script; extract and ask it:

```bash
sed -n '/^# ---CCSYNC-MAPPING-HELPER-BEGIN---$/,/^# ---CCSYNC-MAPPING-HELPER-END---$/p' \
    ccsync-onboard-*.sh > /tmp/ccsync_mapping.py
python3 /tmp/ccsync_mapping.py verify --local-root "/Volumes/<YourSSD>/<tree root>"
```

Exit `0` = mapped correctly, `6` = no `P:\` mapping at all, `7` = mapped
somewhere else (it prints where), `4` = Resolve has no preference files yet.
`verify` never writes anything.

### 6.1 Setting it by hand (fallback)

Only needed if the installer said it could not do it, or you passed
`--skip-resolve-mapping`.

**DaVinci Resolve > Preferences (Cmd+,) > Media Storage tab**, find the
**Mapped Mount** section (older/newer Resolve versions may label this
slightly differently -- look for a table that maps one filesystem path to
another; that's it):

1. Click **Add Mount** (or the `+` under that table).
2. **Local Path** (or "Actual Path" -- whatever the left/first column is
   called): browse to your local root, e.g.
   `/Volumes/<YourSSD>/<tree root>`.
3. **Mapped Path** (or "Remote Path" -- the right/second column): enter it
   in the Windows-style form the database uses: `P:\`
4. Save / close Preferences.

Type the two path forms exactly as shown -- the trailing colon+backslash on
the mapped side matters.

The companion app checks this at startup by asking Resolve for a timeline
clip's resolved path and confirming it lands inside your local root; if it
doesn't, you'll get a "mapping looks wrong" tray warning pointing you back
to this section. That check is behavioural, so it catches a mapping that
Resolve later dropped as well as one that was never set.

### 6.2 Mac only: the sync drive, and unplugging it

Your local root normally lives on the external SSD you edit from
(`--local-root "/Volumes/<YourSSD>/<tree root>"`). Remember there is no
`P:` drive on a Mac -- Resolve's Mapped Mount (section 6) is what stands in
for it. Three things follow from the SSD.

**Unplugging is fine.** The companion watches the volume. Pull the drive
mid-sync and it pauses every lane, the menu-bar icon goes orange, and the
menu says `PAUSED — drive disconnected`. Plug it back in and syncing
resumes on its own -- there is nothing to click, and nothing is lost beyond
the transfer that was in flight (files restart, they do not corrupt).

**macOS will ask for permission to read the drive, once.** The first time
the companion (or rclone) touches a removable volume, macOS shows a
"…would like to access files on a removable volume" prompt. **Allow it.**
If you decline, syncing fails in ways that look like a broken install; you
can undo the mistake in System Settings > Privacy & Security > Files and
Folders.

**The one failure that needs you: a leftover folder at `/Volumes/<Name>`.**
If the drive is ever ejected uncleanly, macOS can leave an empty *directory*
behind at the path the volume used to occupy. It looks exactly like the
mounted drive to anything that just checks "does this path exist" -- and
worse, the next time you plug the real drive in, macOS mounts it at
`/Volumes/<Name> 1` instead, a name that changes on every replug.

Both the installer and the companion refuse to touch that: the installer
aborts, and the companion pauses and shows you a window rather than syncing
terabytes onto your internal disk. The fix belongs to you and takes a
minute:

1. Eject the drive (Finder, or `diskutil eject "/Volumes/<Name>"`).
2. `sudo rmdir "/Volumes/<Name>"` -- `rmdir`, **not** `rm -rf`: it refuses
   if the directory is not empty, which would mean real files live there
   and you should ask the admin before deleting anything.
3. Plug the drive back in, confirm it appears as `/Volumes/<Name>` (no
   number), and carry on. Sync resumes by itself.

You can see the current state with `ls /Volumes` (the drive should appear
once, unnumbered) and `mount | grep Volumes` (it should be listed there --
if the name shows in `ls` but not in `mount`, it is a leftover directory).

### 6.3 Mac only: files downloaded through a browser

macOS tags anything a browser downloads with `com.apple.quarantine`, and a
quarantined file cannot be *executed* -- which is why the bootstrap script
needs one of the two workarounds in section 2 (`xattr -d
com.apple.quarantine <file>`, or run it as `bash <file>`, which is not an
execution of the file).

The companion app itself is not affected: the installer downloads it with
`curl` (which sets no quarantine) and strips the attribute anyway before
installing it. `xattr -l ~/.local/ccsync/bin/ccsync-companion` should print
nothing. If it ever does list `com.apple.quarantine` -- e.g. because
somebody hand-downloaded the binary through Safari -- the app will fail to
start with no visible error at all; clear it with:

```bash
xattr -d com.apple.quarantine ~/.local/ccsync/bin/ccsync-companion
```

## 7. You're set up. What to expect day to day

- Anything you drop into your local project folder under `Audio/`,
  `AE/`, `Subs/`, etc. syncs both ways automatically (Syncthing, lane C).
- Video you add (in `B-roll/`, `Interviewees/`, etc., outside any `Proxy/`
  folder) uploads to the NAS automatically but does **not** download to
  other editors as originals -- only its generated proxy comes back down,
  once the base rig has generated one (this can take minutes to hours; the
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
  reorganizing, ask the admin to do it server-side. This does **not** apply
  to the Syncthing lane (audio/AE/subs/etc.) -- renames and deletes there do
  propagate, and the server keeps a versioned trash so nothing's truly gone.
- **If you open the Syncthing web UI, expect to see projects marked
  "Paused".** That's normal and it's CCSync doing it: because your projects
  sync one at a time, the companion pauses the other project folders while
  the current one takes its turn, then unpauses them when their turn comes.
  **Don't pause, unpause, or remove folders by hand** -- the companion will
  just put them back, and hand-editing there is a good way to stop a project
  syncing without any visible reason.
