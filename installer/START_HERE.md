# CC Sync Remote Editing — Start Here

CC Sync — fleet sync for DaVinci Resolve®. **Requires DaVinci Resolve Studio**
(the paid version): collaboration and the scripting interface do not exist in
the free edition.

Welcome! This gets you editing on our shared DaVinci Resolve project server with
proxies synced to your machine automatically. ~20 minutes, one time.

## Easiest: run onboard.exe (Windows)

The freshest copy is always on the dashboard: sign in and click
`[ INSTALLER ]` in the header — it downloads the right installer for your
computer straight to your Downloads folder. If you were pointed at this
shared folder instead, **copy `onboard.exe` to your Desktop first, then run
it from there** — never run it straight off the share (it locks the file
for everyone, and the installer refuses to run that way).

Follow the wizard: pick **REMOTE EDITOR** on the role page (BASE is only
for the studio base rig). It cleans out any older CCSync install first,
remounts your P: drive fresh, installs everything, signs you in with your
NAS account (you can't finish without valid credentials), and at the
end shows you two values — your **Syncthing device ID** and **SSH public
key** — to send to your admin so they can approve you.

"Cleans out" only means the old app files are replaced. Nothing you've
synced is touched — your project tree folder, proxies, sign-in, Syncthing
identity and SSH key all stay exactly as they are, so there's nothing to
re-approve. Re-running the wizard any time is safe. Once installed, the
companion updates itself: when your admin publishes a new version, the tray shows
a one-click "Update now".

During the install a **UAC (administrator) prompt appears once** — approve
it. It's what lets the installer set up the P: drive so it shows up in
Explorer named properly instead of echoing your local disk's name. If you
decline it, everything still works; the drive just keeps the wrong name.

If you'd rather do it by hand, follow the manual steps below instead.

**On a Mac?** There's no click-through wizard, but the setup script does the
same work — see step 2. Sign in to the dashboard on your Mac and click
`[ INSTALLER ]`: it serves the Mac script (`ccsync-onboard-<version>.sh`) to
your Downloads folder. Your admin will give you the exact flags to run it
with (which SSD to sync to, your username, your token). Everything after
that — the menu-bar app, automatic upload, the out-of-tree popup, dashboard
reporting, one-click updates — works the same as on Windows.

---

**You need:** DaVinci Resolve **Studio** (paid version — collaboration doesn't
work in the free one), a decent internet connection, and a drive with room to
spare. Proxies for every project land on your machine, plus any footage you add,
so think in hundreds of GB rather than tens. It does **not** have to be your
`C:` drive — see step 2 if `C:` is tight.

## 1. Join the private network (Tailscale)

1. Install Tailscale: https://tailscale.com/download
2. Sign in with the **invite link your admin sends you** (it joins you to your
   organisation's private network).
3. That's it — you can now reach the server privately. No port forwarding, no VPN config.

## 2. Run the setup script

**Windows** — open a **normal** PowerShell window. Do **not** right-click →
*Run as Administrator*. Then:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\windows_bootstrap.ps1 -TailnetHost <nas-host> -DashboardUrl <your-dashboard-url> -EditorName <yourname> -DashboardToken <token-from-your-admin>
```

The script asks for admin rights by itself, once, for the one step that
needs them — approve that prompt when it appears. Running the *whole* script
elevated is the one thing that quietly breaks the install: a drive mapped
from an elevated window is invisible to your normal session, so `P:` won't
exist for Resolve until you log off and back on again. If you already did it
that way, log off and on before opening Resolve.

`-DashboardToken` is the value your admin gives you; without it the app installs
fine but never reports to the dashboard and never follows your project
ticks.

To put the sync folder on a different drive, add `-LocalRoot`:

```powershell
.\windows_bootstrap.ps1 -TailnetHost <nas-host> -DashboardUrl <your-dashboard-url> -EditorName <yourname> -LocalRoot F:\<tree>
```

**macOS** — download the script from the dashboard (`[ INSTALLER ]` in the
header), then, in Terminal:

```bash
cd ~/Downloads
chmod +x ccsync-onboard-*.sh
DASHBOARD_TOKEN=<token-from-your-admin> ./ccsync-onboard-*.sh \
    --tailnet-host <nas-host> --editor-name <yourname> \
    --local-root "/Volumes/<YourSSD>/<tree>"
```

Use the flags your admin gives you. `--local-root` should point at the
external drive you edit from; leave it out and everything lands in
your home folder on the internal disk. `DASHBOARD_TOKEN` is what lets the
script install the sync app — without it the script says, loudly, that
nothing on this Mac will sync.

macOS tags anything downloaded through a browser and refuses to *run* it. If
you get "cannot be opened because it is from an unidentified developer", or
`Operation not permitted`, either clear the tag once:

```bash
xattr -d com.apple.quarantine ccsync-onboard-*.sh
```

or skip the `chmod` and start it with `bash` instead — handing the file to
`bash` as an argument isn't affected by the tag:

```bash
DASHBOARD_TOKEN=<token> bash ccsync-onboard-*.sh --tailnet-host <nas-host> --editor-name <yourname> --local-root "/Volumes/<YourSSD>/<tree>"
```

Re-running the script is safe — it checks everything before it changes
anything, and re-running is the normal way to fix a mistyped flag. Add
`--dry-run` to see what it would do without touching anything.

Use your username exactly as your admin gave it to you — it's **lowercase** and
case-sensitive. The script lowercases it for you and says so if it had to.

The script installs the sync tools, creates your project folder, starts the
background sync service, and at the end prints your **Syncthing device ID** —
**send that to your admin.**

If it warns that you have no SSH key yet, run this and send your admin the
`.pub` file it creates (the whole one-line contents):

```powershell
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\ccsync_ed25519"
```
```bash
ssh-keygen -t ed25519 -f ~/.ssh/ccsync_ed25519      # macOS
```

Then wait for your admin to confirm you're approved — nothing syncs until
they've added both. It only takes them a minute.

## ⚠️ One thing that will silently break everything

**Do not map any of our server's shares to a drive letter yourself** — no
`net use`, no "Map network drive", no mounting the NAS over SMB on a Mac.

On Windows, `P:` is created for you and is the only one you need. In Explorer
it shows up under your studio's tree name so you can tell it apart from your own
drives — only project material goes in there. On a Mac there is no `P:`
drive at all: Resolve's **Mapped Mount** setting does that job, and the setup
script fills it in for you (see EDITOR_SETUP.md step 6).

Why it matters: the shared Resolve database stores clip paths using the
*server's* drive letters. If you map a share to a letter that collides with
one of those, Resolve resolves those paths straight to the live network share
and streams **full-resolution camera originals** across the internet for every
playback — ignoring your local proxies completely. There's no error and no
warning; it just feels mysteriously slow. **`T:` is known to collide** — never
map that one. If you think you need another mount, ask your admin first.

## 3. Install the companion app

Easiest: let the setup script do it, by pointing it at the exe in this
folder — it copies the app into place *and* registers auto-start:

```powershell
.\windows_bootstrap.ps1 -TailnetHost <nas-host> -DashboardUrl <your-dashboard-url> -EditorName <yourname> -CompanionExeSource .\ccsync-companion.exe
```

By hand instead: copy `ccsync-companion.exe` into

```
%LOCALAPPDATA%\ccsync\bin\
```

(paste that into Explorer's address bar; create the `bin` folder if it isn't
there) and run it from there. **Don't** keep it in your project tree
folder, on the Desktop, or anywhere else — that's the one location the setup
script starts at logon, and stray copies elsewhere cause problems later.
Re-running the setup script will *not* find a copy you put somewhere else.

**On a Mac** there is nothing to do here: the setup script downloads and
installs the app itself (that's what `DASHBOARD_TOKEN` is for) into
`~/.local/ccsync/bin` and starts it at login. If step 2 ended with a big
"THE SYNC APP IS NOT INSTALLED ON THIS MAC" warning, ask your admin for the
token and run the script again — everything else it set up is fine and will
be skipped.

Once it's running a tray icon appears (the menu bar, top right, on a Mac):
**green = synced, orange = syncing, red = problem**. It also watches your Resolve timeline — if you cut in a file
from outside the project folder (Desktop, Downloads…), it pops up and offers
to **copy it into the right place** and relink Resolve. Say yes — that's what
makes your added media appear for everyone else. Your original stays where it
is; delete it yourself later if you want.

**Now sign in — this is the switch that turns sync on.** Right-click the
tray icon → **Sign in…** and enter your NAS username and password
(the ones your admin set up). Until the tray says `Signed in as <you>`, nothing
syncs — and your machine won't show up on your admin's side either, since the
app only reports in once it knows who you are. If they say they can't see your
machine, check this first.

Then right-click the tray icon → **Open dashboard** — sign in there with the
same username and password — and **tick the projects you want synced to this
machine**. Nothing syncs until you tick something either; that's on purpose,
so you only pull the projects you're actually working on. (If you didn't pass
`-DashboardToken` in step 2, ask your admin for the token and re-run the setup
script with it, or the app can't report status or follow your ticks.)

## 4. Connect Resolve to the project server

1. Resolve → Project Manager → ⋮ (or the network/globe icon) → **Add Project Library**
2. Type: **Network / PostgreSQL**, and enter:
   - Host: `<nas-host>`
   - Username: `postgres`
   - Password: *(your admin sends this separately)*
3. Open the shared project. Set **Playback → Proxy Handling → Prefer Proxies**.
4. **macOS only:** the setup script already set Resolve's **Mapped Mount**
   (`P:\` → your sync folder) for you. Check it under Preferences → Media
   Storage. If step 2 said it couldn't — because Resolve was open, or had
   never been launched on this Mac — quit Resolve, then run
   `./ccsync-onboard-*.sh --resolve-mapping-only --local-root "/Volumes/<YourSSD>/<tree>"`.
   EDITOR_SETUP.md step 6 has both that and the by-hand walkthrough.

## How it works (the 30-second version)

- **You pick which projects sync** on the dashboard (tray → Open dashboard →
  tick). They sync **one project at a time, in the order you ticked them** —
  the dashboard shows live speed, files remaining and ETA for the current one.
  Untick to stop a project (files already downloaded stay on your disk).
- **Proxies download to you**, camera originals stay on the server. You edit
  proxies; Resolve handles the swap at export time on the studio base rig.
- **Anything you add** (music, graphics, your own footage) **uploads
  automatically** — as long as it lives inside your project tree folder. The
  popup keeps you honest here; use tray → **Scan whole project** to check media
  you imported but haven't cut in yet.
- **Starting from a project you already had?** Tray → **Consolidate
  pre-existing project…** copies your scattered media into the project folder
  and uploads it, so everything lands neatly on the server. It **copies,
  never moves** — your originals stay exactly where they are.
- **Don't reorganize/rename folders** — that happens on the server side only.
  Deleting a shared file deletes it for everyone (there's a server-side trash,
  but still — ask first).

## Updating or removing CCSync

- **Update to a new build:** your admin sends you a fresh package; run
  `.\windows_upgrade.ps1` from inside it. It swaps in the new app and keeps
  everything else (your Syncthing identity, key, drive mapping, settings) —
  nothing to re-approve. Add `-DashboardToken <value>` if your admin gives you
  one.
- **Remove it:** `.\windows_uninstall.ps1` removes the app but keeps your
  identity so a reinstall is painless. `.\windows_uninstall.ps1 -Full` also
  removes your saved sign-in and Syncthing identity (a reinstall then needs
  your admin to re-approve you). Neither mode ever deletes your synced media in
  `<tree root>` (e.g. `C:\CCSync`).
- **On a Mac:** updates arrive the same way (menu bar → **Update now**), and
  removal is `./macos_uninstall.sh` — same two modes, `--full` for the
  thorough one, `--dry-run` to see what it would do first. It never touches
  your synced media on the SSD, and it leaves Resolve's Mapped Mount alone
  (it tells you how to remove that by hand if you want to).

Problems? Tray icon red, clips offline, popup confused — message your admin
with a screenshot of the tray menu. If sync seems dead, the log at
`~/.ccsync/companion.log` says what's wrong in plain English near the top.

---

DaVinci Resolve is a registered trademark of Blackmagic Design Pty Ltd. CC Sync
is not affiliated with, endorsed by, or sponsored by Blackmagic Design.
