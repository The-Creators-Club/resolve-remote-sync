# Server Runbook -- Creators Club Sync

Admin-facing runbook for TrueNAS-side operations. All scripts referenced
live in `../server/`; see `../server/README.md` for env vars and per-script
assumptions. Every script supports `--dry-run` -- use it first.

## Onboarding a new editor, end to end

1. Get their SSH public key (`.pub` file -- they generate the keypair
   locally, per `docs/EDITOR_SETUP.md`; you only ever receive the public
   half).
2. Create their TrueNAS account:
   ```
   python server/setup_editor_account.py --name jsmith --ssh-pubkey-file jsmith.pub --tailnet-host <nas-tailnet-host>
   ```
   This creates (or updates) the user, adds them to the `editors` group
   (creating that group if it doesn't exist yet), installs their SSH key,
   enables SMB access, and attempts to disable password-based SSH login
   (key-only) -- see the **open question** below if that ever fails.
3. Send the editor: the tailnet hostname of the NAS, their username, and
   the printed rclone remote stanza (they don't need to type it by hand --
   `installer/windows_bootstrap.ps1` / `installer/macos_bootstrap.sh`
   write it for them, they just need the tailnet host + their own
   username as script arguments).
4. Editor runs their bootstrap script (`docs/EDITOR_SETUP.md`) and sends
   you their Syncthing device ID.
5. For each project they need:
   ```
   python server/accept_device.py --device-id <their-id> --folder-id <project-folder-id> --gui-url <syncthing-gui-url> --api-key <syncthing-api-key>
   ```
   (`<project-folder-id>` is the slug printed by `setup_syncthing_folder.py`
   when the project was created, e.g. `2025-ff4-nuclear`.)
6. Give them the Resolve Project Server credentials (Postgres user/pass for
   whichever project database they're joining) -- this is managed via
   Resolve's own Project Server tooling, not by these scripts.
7. Run `python server/check_health.py` and confirm their account shows up
   under the editor-accounts check.

**Open question flagged, not resolved:** TrueNAS's per-user "disable
password login" setting may also disable SMB (both are password/hash
based). `setup_editor_account.py` tries to set it and automatically rolls
back if SMB access breaks as a result, printing a warning either way --
if you see that warning, decide by hand (TrueNAS UI) whether this editor
needs key-only SSH or SMB access more, since as currently understood you
may not get both simultaneously on one account.

## Onboarding a new project

1. Create the folder tree:
   ```
   python server/setup_tree.py --year 2025 --series FF4 --project Nuclear
   ```
   Creates `Creators_Club/Projects/2025/FF4/Nuclear/{AE, Audio/Music,
   Audio/Voiceover, B-roll, Interviewees, Render in Place, Subs, Youtube}`,
   owned `broll:editors`, mode `2770` (setgid, so anything editors create
   stays group-writable for other editors too). `Proxy/` subfolders are
   **not** pre-created -- see "Where proxies come from" below.
2. Create its Syncthing folder (lane C):
   ```
   python server/setup_syncthing_folder.py --project-rel-path 2025/FF4/Nuclear --gui-url <url> --api-key <key>
   ```
   This sets staggered versioning and the ignore list (video extensions +
   `**/Proxy`, since those travel via rclone lanes A/B instead).
3. Share it to whichever editors are on this project:
   ```
   python server/accept_device.py --device-id <their-id> --folder-id 2025-ff4-nuclear --gui-url <url> --api-key <key>
   ```
4. Set up the Resolve Project Server database for this project (Resolve's
   own Project Manager tooling on the host, not scripted here) and the
   Blackmagic Proxy Generator watch folder (see below).
5. Give editors their DB credentials.

## Delete / rename rules (see SPEC.md "Flaws" #2)

This is the single most important thing to get right as an admin, because
it's asymmetric and easy to get bitten by:

- **Lane A (video originals, editor -> NAS, rclone)** never deletes
  anything on the NAS. This is intentional (archival safety net against a
  clumsy local delete propagating upstream). The consequence: **if an
  editor renames or moves a folder locally, the NAS ends up with the old
  copy *and* the new one** -- rclone just uploads under the new name/path
  and the stale original sits there forever.
- **Lane B (proxies, NAS -> editor, rclone)** mirrors the server exactly,
  so **reorganize projects on the server (host) side, never on an
  editor's machine.** When you rename/move something server-side, lane B
  will propagate that rename down to every editor automatically.
- **Lane C (everything else, bidirectional, Syncthing)** does propagate
  deletes and renames in both directions -- but the server keeps staggered
  versioning (a versioned trash), so a mistaken delete is recoverable from
  the server's Syncthing folder version history, not gone for good.

Practical rule for editors (documented for them too, in
`docs/EDITOR_SETUP.md`): reorganize video folders by asking the admin to do
it server-side; reorganize everything else (audio/AE/subs/etc.) locally,
it'll propagate correctly.

## Where proxies come from

The **Blackmagic Proxy Generator (BPG)** runs on Alex's PC (the host),
watching per-project folders under `P:` (the host's own SMB mount of the
same tree). It natively decodes BRAW (ffmpeg can't), is GPU-accelerated,
preserves timecode, and writes proxies into the existing in-place `Proxy/`
subfolder convention next to the source media -- exactly what Resolve
auto-links against (same filename + timecode in the adjacent `Proxy/`
folder). Output format is H.264 1080p for cross-platform compatibility.

This means: **BPG only proxies media it can see on `P:`.** Since editors'
uploads (lane A) land in the same tree on the NAS, and the host's `P:` is
just an SMB mount of that same NAS path, anything an editor uploads gets
picked up by BPG's watch folder automatically -- no separate step needed,
other than BPG being on and pointed at the right watch folders per
project. **BPG depends on the host PC being on** (there's Wake-on-LAN
configured for it as a mitigation); a NAS-side ffmpeg fallback container
for non-BRAW formats when the PC is off is a documented future nice-to-have,
not built yet.

## Health check

```
python server/check_health.py --gui-url <syncthing-gui-url> --api-key <syncthing-api-key>
```

Prints plain PASS/FAIL lines for: Postgres reachable on `:5432`, the
Tailscale app's container is logged in (and its tailnet IP), Syncthing app
reachable + its folder list, the project tree root exists, and the
`editors` group has members. Exit code is the number of failed checks (0 =
all good) -- wire this into whatever monitoring/cron you want later.
