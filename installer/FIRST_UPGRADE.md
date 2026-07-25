# Updating CCSync — one-time manual step

Hi! We've added **automatic updates** to the companion app. Future updates
are one click. This one time, you need to do the update by hand, because the
version you're running doesn't know how to update itself yet. ~2 minutes.

## What to do

1. You should have received this folder (the new CC_Sync package) from your
   admin — either as a download link or copied onto your machine. Open
   **PowerShell** in this folder (in Explorer: File → Open Windows PowerShell,
   or shift-right-click → "Open PowerShell window here").

2. Run:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\windows_upgrade.ps1
   ```

   That's it. The script stops the running companion, swaps in the new app,
   keeps **everything** else (your sign-in, Syncthing identity, SSH key,
   `P:` drive, settings — nothing to re-approve), and starts it again.

3. Check the tray icon is back (green/orange dot). Right-click it — if it
   says **NOT SIGNED IN**, click **Sign in…** and use your usual username
   and password. Do this even if everything else looks fine: until the tray
   reads `Signed in as <you>`, nothing syncs and your machine doesn't show
   up on your admin's side at all.

## What you get

- **One-click updates from now on.** When your admin publishes a new version,
  your tray icon pops a notification and the tray menu grows an
  **"Update available → vX.Y — Update now"** entry. Click it, confirm, and
  the app updates and restarts itself. No more downloading packages.
- **Project folder structure.** When you tick a project to sync, your local
  copy now gets the project's **complete folder layout from the server** —
  including folders that are still empty — so your bins match everyone
  else's from the start.

## If something looks wrong

- **No tray icon after the upgrade:** run the companion once by hand —
  it's at `%LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe` — then log off/on
  once so autostart takes over.
- **Tray icon red, or anything confusing:** message your admin with a
  screenshot of the tray menu. The log at `%USERPROFILE%\.ccsync\companion.log`
  explains most problems in plain English near the top.

*(You only ever need this file once. Future updates: click the tray item.)*
