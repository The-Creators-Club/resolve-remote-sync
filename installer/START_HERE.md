# Creators Club Remote Editing — Start Here

Welcome! This gets you editing on our shared DaVinci Resolve project server with
proxies synced to your machine automatically. ~20 minutes, one time.

## Easiest: run onboard.exe (Windows)

**Copy `onboard.exe` to your Desktop first, then run it from there** —
never run it straight off this shared folder (it locks the file for
everyone, and the installer refuses to run that way).

Follow the wizard: pick **REMOTE EDITOR** on the role page (BASE is only
for Alex's studio machine). It cleans out any older CCSync install first
(your Syncthing identity and SSH key are kept — nothing to re-approve),
remounts your P: drive fresh, installs everything, signs you in with your
TrueNAS account (you can't finish without valid credentials), and at the
end shows you two values — your **Syncthing device ID** and **SSH public
key** — to send to Alex so he can approve you. Re-running it any time is
safe. Once installed, the companion updates itself: when Alex publishes a
new version, the tray shows a one-click "Update now".

During the install a **UAC (administrator) prompt appears once** — approve
it. It's what lets the installer set up the P: drive so it shows up in
Explorer named properly instead of echoing your local disk's name. If you
decline it, everything still works; the drive just keeps the wrong name.

If you'd rather do it by hand, or you're on a Mac, follow the manual steps
below instead.

---

**You need:** DaVinci Resolve **Studio** (paid version — collaboration doesn't
work in the free one), a decent internet connection, and a drive with room to
spare. Proxies for every project land on your machine, plus any footage you add,
so think in hundreds of GB rather than tens. It does **not** have to be your
`C:` drive — see step 2 if `C:` is tight.

## 1. Join the private network (Tailscale)

1. Install Tailscale: https://tailscale.com/download
2. Sign in with the **invite link Alex sends you** (it joins you to the
   `cablewrapcreative.com` network).
3. That's it — you can now reach the server privately. No port forwarding, no VPN config.

## 2. Run the setup script

**Windows** — open PowerShell **as Administrator** (right-click PowerShell →
*Run as Administrator*), then:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\windows_bootstrap.ps1 -TailnetHost 100.71.216.3 -EditorName <yourname>
```

Administrator isn't strictly required — the script falls back to an equivalent
method and tells you which one it used — but with it you get a cleaner logon
task for the `P:` drive.

To put the sync folder on a different drive, add `-LocalRoot`:

```powershell
.\windows_bootstrap.ps1 -TailnetHost 100.71.216.3 -EditorName <yourname> -LocalRoot F:\Creators_Club
```

**macOS** — in Terminal:

```bash
bash macos_bootstrap.sh --tailnet-host 100.71.216.3 --editor-name <yourname>
```
(add `--local-root /Volumes/Media/Creators_Club` to place it elsewhere)

Use your username exactly as Alex gave it to you — it's **lowercase** and
case-sensitive. The script lowercases it for you and says so if it had to.

The script installs the sync tools, creates your project folder, starts the
background sync service, and at the end prints your **Syncthing device ID** —
**send that to Alex.**

If it warns that you have no SSH key yet, run this and send Alex the `.pub`
file it creates (the whole one-line contents):

```powershell
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\ccsync_ed25519"
```
```bash
ssh-keygen -t ed25519 -f ~/.ssh/ccsync_ed25519      # macOS
```

Then wait for Alex to confirm you're approved — nothing syncs until he's added
both. It takes a minute on his side.

## ⚠️ One thing that will silently break everything

**Do not map any of our server's shares to a drive letter yourself** — no
`net use`, no "Map network drive", no mounting the NAS over SMB on a Mac.

`P:` is created for you and is the only one you need. In Explorer it shows up
as **TheCreatorsClub** so you can tell it apart from your own drives — only
project material goes in there.

Why it matters: the shared Resolve database stores clip paths using the
*server's* drive letters. If you map a share to a letter that collides with
one of those, Resolve resolves those paths straight to the live network share
and streams **full-resolution camera originals** across the internet for every
playback — ignoring your local proxies completely. There's no error and no
warning; it just feels mysteriously slow. **`T:` is known to collide** — never
map that one. If you think you need another mount, ask Alex first.

## 3. Copy the companion app

Copy `ccsync-companion.exe` somewhere permanent (e.g. into your `Creators_Club`
folder) and run it. A tray icon appears: **green = synced, orange = syncing,
red = problem**. It also watches your Resolve timeline — if you cut in a file
from outside the project folder (Desktop, Downloads…), it pops up and offers to
**move it into the right place for you**. Say yes — that's what makes your added
media appear for everyone else.

Re-run the setup script after copying it and it'll add the app to auto-start.

Right-click the tray icon → **Open dashboard** to sign in (your TrueNAS
username + password, same one Alex set up) and **tick the projects you want
synced to this machine**. Nothing syncs until you tick something — that's on
purpose, so you only pull the projects you're actually working on. Alex will
give you a **dashboard token** to paste into `~/.ccsync/config.toml` as
`dashboard_token` so the app can report status and follow your ticks.

## 4. Connect Resolve to the project server

1. Resolve → Project Manager → ⋮ (or the network/globe icon) → **Add Project Library**
2. Type: **Network / PostgreSQL**, and enter:
   - Host: `100.71.216.3`
   - Username: `postgres`
   - Password: *(Alex sends this separately)*
3. Open the shared project. Set **Playback → Proxy Handling → Prefer Proxies**.
4. **macOS only:** Preferences → Media Storage → add your `Creators_Club`
   folder, and set its **Mapped Mount** to `P:\` — see EDITOR_SETUP.md for the
   walkthrough.

## How it works (the 30-second version)

- **You pick which projects sync** on the dashboard (tray → Open dashboard →
  tick). They sync **one project at a time, in the order you ticked them** —
  the dashboard shows live speed, files remaining and ETA for the current one.
  Untick to stop a project (files already downloaded stay on your disk).
- **Proxies download to you**, camera originals stay on the server. You edit
  proxies; Resolve handles the swap at export time on Alex's machine.
- **Anything you add** (music, graphics, your own footage) **uploads
  automatically** — as long as it lives inside your `Creators_Club` folder. The
  popup keeps you honest here; use tray → **Scan whole project** to check media
  you imported but haven't cut in yet.
- **Starting from a project you already had?** Tray → **Consolidate
  pre-existing project…** copies your scattered media into the project folder
  and uploads it, so everything lands neatly on the server.
- **Don't reorganize/rename folders** — that happens on the server side only.
  Deleting a shared file deletes it for everyone (there's a server-side trash,
  but still — ask first).

## Updating or removing CCSync

- **Update to a new build:** Alex sends you a fresh package; run
  `.\windows_upgrade.ps1` from inside it. It swaps in the new app and keeps
  everything else (your Syncthing identity, key, drive mapping, settings) —
  nothing to re-approve. Add `-DashboardToken <value>` if Alex gives you one.
- **Remove it:** `.\windows_uninstall.ps1` removes the app but keeps your
  identity so a reinstall is painless. `.\windows_uninstall.ps1 -Full` wipes
  everything (you'd then need Alex to re-approve your device).

Problems? Tray icon red, clips offline, popup confused — message Alex with a
screenshot of the tray menu. If sync seems dead, the log at
`~/.ccsync/companion.log` says what's wrong in plain English near the top.
