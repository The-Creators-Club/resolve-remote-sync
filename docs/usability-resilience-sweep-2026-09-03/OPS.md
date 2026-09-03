# NAS-side scripts, installers, uninstallers, onboarding wizard, appliance install (OPS)

## Summary
The scripts are the most defensively written code in the repo, and most of the
08-28 structural findings got BUILT (post-deploy health probe, NAS banner,
snapshot log, `Get-DriveMapping` in the uninstaller, the wrong-profile refusal,
the mid-install breadcrumb). What this sweep finds is a usability posture that
stops at the script boundary: the wizard is the front door for every new editor
and it runs a 30-minute child process with no progress, keeps its only log in a
widget that dies with the window, can show a green DONE page to a machine with no
tree drive, and never mentions the two Resolve steps without which none of it
works. On the owner's side, the documented install never wires up the restore
path the backup doc calls "the primary route", and never backs up the one key the
whole upgrade channel depends on. Cheapest wins: stream the bootstrap's stdout
into the log widget, and normalise a scheme-less dashboard URL instead of
answering "wait a few seconds and retry" forever.

## Findings

### OPS-1: an editor whose tree drive could not be mapped is shown the green DONE page
- **Lens:** both  **Who:** editor
- **Where:** `installer/windows_bootstrap.ps1:1221-1244`, `:2253-2267`;
  `onboarding/onboard.py:1189-1210`
- **Today:** `$script:PIsForeign` is set when the drive is somebody else's mapping
  OR when `Get-DriveMapping` cannot answer. The script prints an ERROR, four
  warnings, and `"Skipping the whole $DriveRoot mapping section; everything else
  below still runs."` It is the only refusal in the file that never calls
  `Add-CapabilityMiss` (5 call sites, none of them this), so the run exits 0 and
  the wizard renders `"DONE: SEND THESE TWO VALUES TO YOUR ADMIN"`. The machine
  has no tree drive: no Resolve path resolves, lane B has nowhere to land, and the
  editor has been told to tell their admin they are set up.
- **Proposed:** `Add-CapabilityMiss "the $DriveRoot drive was NOT created: it is
  already mapped to '<target>'. Nothing in DaVinci Resolve can find the project
  tree until that is sorted. Disconnect it (Explorer > This PC > right-click
  $DriveRoot > Disconnect) and re-run, or ask your admin."` That alone routes it
  to exit 3 and the existing NOT-READY page. Same for could-not-determine.
- **Effort:** S   **Value:** critical   **Confidence:** high
- **Related:** INST-5 built the exit-3 contract for exactly this; B7.

### OPS-2: an editor account needs an SSH key the editor can only make after they have an account
- **Lens:** usability  **Who:** owner, editor
- **Where:** `dashboard/templates/partials/admin_users.html:313-325`
  (`<textarea name="ssh_pubkey" ... required>`), `ui.py:1938`, `api.py:3726-3730`,
  `api.py:4113-4122` (`add_ssh_key` is `_require_local_mode`),
  `onboarding/onboard.py:1002-1012`
- **Today:** in NAS mode (both live sites) `[ CREATE NEW EDITOR ACCOUNT ]` refuses
  without a key ("does not look like an OpenSSH public key"). The wizard is what
  generates `~/.ssh/ccsync_ed25519`, and it cannot get there because sign-in needs
  the account. The real order - editor runs `ssh-keygen` by hand and emails the
  .pub first - appears only as step 2 of the MANUAL path
  (`installer/START_HERE.md:194-208`). After creation there is no way to add or
  replace a key in NAS mode: the keys route is local-mode only.
- **Proposed:** accept an empty key on create, with the row showing
  `[ NO SSH KEY ]` and "lanes A and B will not run until a key is added"; add
  `[ UPDATE SSH KEY ]` per row posting to the same `create_or_update_editor`; and
  have the wizard POST its new public key with the identity token it already
  holds, into a pending-keys queue approved in one click (the device ID already
  arrives that way, `api.py:3487` + `_pending_owner_hint`).
- **Effort:** M   **Value:** high   **Confidence:** high

### OPS-3: Settings -> RECOVERY can never restore anything on a documented install
- **Lens:** both  **Who:** owner
- **Where:** `docs/BACKUP_RESTORE.md:14-42`, `recovery.py:47,76`;
  `DASH_SNAPSHOT_DIR` has zero hits in `server/`, `INSTALL.md`, `SERVER.md`,
  `SERVER-SYNOLOGY.md`
- **Today:** BACKUP_RESTORE opens with "START AT THE DASHBOARD, NOT AT THIS
  DOCUMENT ... Settings -> RECOVERY is the primary route", then notes it needs
  `DASH_SNAPSHOT_DIR` and `DASH_SNAPSHOT_PROJECTS_SUBPATH`. Neither is set by the
  deploy or mentioned in any runbook, so every install that follows the docs gets
  a RECOVERY page that can only print commands. The owner finds out during an
  incident, having been told twice that the page is the way.
- **Proposed:** set both in the compose env from `site.toml` during the deploy
  (the pool path is already resolved there); until then, an install step that
  does, and a page that says "this deployment was never given a snapshot mount"
  instead of degrading silently.
- **Effort:** M   **Value:** high   **Confidence:** high

### OPS-4: the wizard runs a 30-minute child process and shows nothing while it does
- **Lens:** usability  **Who:** editor
- **Where:** `onboarding/steps.py:1036-1060` (`stdout=PIPE`, `communicate`),
  `steps.py:333` (`BOOTSTRAP_TIMEOUT_SECONDS = 1800`), `onboard.py:1031-1042`
- **Today:** the whole install - winget, two pinned downloads, the UAC share
  helper, `--setup-resolve-prefs --wait-for-resolve 180` - is captured to a pipe
  and printed in one block at the end. On screen: `"running bootstrap for editor
  'jsmith'…"` then nothing for two to thirty minutes, BEGIN INSTALL and BACK both
  disabled, no spinner, no elapsed time, no way to tell working from hung. The
  bootstrap prints a good `[ccsync]` line per step and none of it is visible until
  it is over. macOS is worse: all three downloads use `curl -fsSL`, whose `-s`
  kills curl's own progress meter (`macos_bootstrap.sh:1611`, `:1711`, `:2224`).
- **Proposed:** read the child's stdout line by line on a reader thread through
  `_append_log` (already thread-safe via `_safe_after`), keeping the aggregate for
  `parse_device_id` / `bootstrap_capability_warnings`; add an elapsed counter to
  the heading; use `curl -fSL --progress-bar` on macOS.
- **Effort:** S   **Value:** high   **Confidence:** high

### OPS-5: the install log exists only inside a window that is about to be closed
- **Lens:** both  **Who:** editor, owner
- **Where:** `onboarding/onboard.py:862-870`, `:61`, `build_onboard.spec:134` /
  `build_onboard_macos.spec:193` (`console=False`)
- **Today:** a frozen windowed build has no stderr, so every `log.info` /
  `log.exception` goes nowhere, and the bootstrap output only ever reaches a
  `tk.Text`. On failure the page says "Send them this list instead" with no
  [ COPY LOG ], no [ SAVE LOG ], no file path, and the record gone when the window
  closes. The owner debugging a remote install has nothing to ask for but a phone
  photo of the screen.
- **Proposed:** tee everything `_append_log` receives to
  `~/.ccsync/logs/onboard-<ts>.log`, print that path as the log's first line and
  on both finish pages, and add [ COPY LOG ] beside CLOSE / RETRY INSTALL.
- **Effort:** S   **Value:** high   **Confidence:** high

### OPS-6: a dashboard URL typed without `http://` produces "wait a few seconds and retry", forever
- **Lens:** usability  **Who:** editor
- **Where:** `onboarding/steps.py:796-801` (`except Exception: return False`),
  `steps.py:704-716`, `onboard.py:670-673`
- **Today:** the admin says "the dashboard is nas.tail26290e.ts.net"; the editor
  types exactly that. `urlopen` raises `ValueError: unknown url type`, swallowed by
  `dashboard_reachable`, so the page says "tailscale is up, but the dashboard isn't
  reachable yet -- wait a few seconds and retry" and NEXT stays disabled forever.
  On the base path the same typo shows as "sign-in failed: unknown url type:
  'nas.../api/v1/verify'". Nothing says "put https:// in front".
- **Proposed:** normalise in one helper used by all three callers - with no `://`,
  try `https://` then `http://` and write the working form back into the field -
  and split host-unknown ("that address does not exist on this network, check the
  spelling") from refused/timeout instead of one "not reachable yet".
- **Effort:** S   **Value:** high   **Confidence:** high

### OPS-7: the wizard path delivers no documentation at all, and never mentions Resolve
- **Lens:** usability  **Who:** editor
- **Where:** `onboarding/onboard.py:1189-1210`,
  `dashboard/templates/installer.html:16-49`,
  `installer/build_editor_package.ps1:645-676`, `windows_bootstrap.ps1:2225-2242`
- **Today:** the recommended route is "sign in, click [ INSTALLER ], run the exe",
  and that page hands over one binary: no guide, no "what happens next", no link.
  The Finish page ends on the tray sign-in and the two values. Neither mentions
  connecting Resolve to the Project Library or Playback > Proxy Handling > Prefer
  Proxies (`docs/EDITOR_SETUP.md:266`, `:293`) - which appear once, as items 4 and
  5 of a "Remaining manual steps" list printed into a log the editor cannot keep,
  mixed with steps 1-3 the wizard already did, citing a doc they never received.
- **Proposed:** a third Finish block ("TWO THINGS LEFT, IN RESOLVE - 1. Project
  Manager > Add Project Library > Network / PostgreSQL, host `<from the site
  manifest>`, user `postgres`, password from your admin. 2. Playback > Proxy
  Handling > Prefer Proxies") with a copy button; an [ OPEN THE SETUP GUIDE ]
  button pointing at a `/guide` page serving EDITOR_SETUP.md, linked from
  `installer.html` too; and suppress the bootstrap's steps 1-3 when
  `-CompanionExeSource` says the wizard invoked it.
- **Effort:** M   **Value:** high   **Confidence:** high

### OPS-8: the release signing key has no backup path anywhere in the backup documentation
- **Lens:** resilience  **Who:** owner
- **Where:** `docs/INSTALL.md:181-197` (Step 6 mints it to
  `%USERPROFILE%\.ccsync-release\release.key`); `docs/BACKUP_RESTORE.md:46-58` and
  `:514-526` mention neither; the only "BACK IT UP OFFLINE" in the repo is one
  sentence in `docs/COMMERCIAL_READINESS.md:137`
- **Today:** the key lives on one Windows profile, never on the NAS, never
  snapshotted. A companion trusts only keys baked into the build it is running, so
  losing it means no signed publish is possible for the fleet until every machine
  is reinstalled by hand - and RELEASE.md's rotation needs the OLD key to publish
  the overlap release.
- **Proposed:** a row in the BACKUP_RESTORE §1 table naming the key, what protects
  it (nothing) and the cost of losing it; one line in INSTALL.md Step 6: "copy
  `release.key` into your password manager now - it is not on the NAS and no
  snapshot covers it." Same for the Android keystore beside it.
- **Effort:** S   **Value:** high   **Confidence:** high

### OPS-9: Step 4 configures snapshots and never checks that anything got scheduled
- **Lens:** both  **Who:** owner
- **Where:** `docs/INSTALL.md:156-166`; `docs/BACKUP_RESTORE.md:60-83` (server-6:
  on this fleet's own box `/mnt/tank/apps` is a plain directory, so
  `setup_snapshots.py` refuses the app target and `dashboard.db`, `music.db`,
  `ytdl.db` have no scheduled snapshot at all)
- **Today:** "snapshots, before anything else writes" runs the dry run then
  `--apply` and stops. The known trap - `[apps] root` must BE a dataset, and the
  deploy only ever `mkdir -p`s it - is documented three files away, and the
  verification (`--list --apply`) appears only in BACKUP_RESTORE §2. The
  documented install can end with the fleet database unprotected and a green
  transcript.
- **Proposed:** a Step 1 prerequisite ("create `[apps] root` as its own dataset
  first: `sudo zfs create -p tank/apps/ccsync-dashboard`") and a third line in
  Step 4 running `--list --apply` with "both targets must name a dataset; a
  non-zero exit means one is unprotected". Better: have the deploy warn.
- **Effort:** S   **Value:** high   **Confidence:** high

### OPS-10: the owner is told to invent `SYNCTHING_API_KEY`, and to export it before the step that produces it
- **Lens:** usability  **Who:** owner
- **Where:** `docs/INSTALL.md:120-122`, `:129-131` ("this is where
  SYNCTHING_API_KEY comes from, so it must come FIRST"), `:235-244` (the table,
  then "Generate each with `openssl rand -hex 24`")
- **Today:** on TrueNAS the catalog app generates its own key on first boot;
  `install_syncthing_app.py` neither mints nor prints one. An owner following §3
  literally invents a value that can never match, and every later call
  (`install_dashboard_app.py`, `setup_syncthing_folder.py`, `check_health.py`,
  `accept_device.py`) 403s with nothing pointing at the cause. Step 2 also orders
  the export before the step that produces it. On Synology the opposite is true -
  `compose.yaml`'s `STGUIAPIKEY` is seeded from the env var - so one instruction
  cannot serve both.
- **Proposed:** split the row by backend: "TrueNAS: do NOT invent this. Install
  Syncthing (Step 3.1), then read it from `http://<nas>:8384` > Settings > GUI >
  API Key and export it before Step 3.2. Synology: generate it now like the rest."
- **Effort:** S   **Value:** high   **Confidence:** high

### OPS-11: macOS tells an editor with no Resolve installed to "launch it once, quit it, then re-run"
- **Lens:** usability  **Who:** editor
- **Where:** `installer/macos_bootstrap.sh:1509-1512`; contrast the Tailscale probe
  at `:1547` (`[ -d "/Applications/Tailscale.app" ]`)
- **Today:** status 4 = `never-launched` fires whenever Resolve's preference files
  are absent, and nothing checks whether `/Applications/DaVinci Resolve.app`
  exists. An editor who has not installed Resolve at all gets advice that cannot be
  followed and never learns the real cause. The same sentence reaches the wizard's
  Finish page via `steps.resolve_mapping_warning`.
- **Proposed:** probe for the bundle first and emit a distinct status: "DaVinci
  Resolve is not installed on this Mac. CC Sync needs Resolve Studio (the paid
  version). Install it, then run: `$0 --resolve-mapping-only`."
- **Effort:** S   **Value:** high   **Confidence:** high

### OPS-12: a non-absolute `--remote-root` is a warning, so lane A uploads into the editor's SFTP home
- **Lens:** resilience  **Who:** editor, owner
- **Where:** `installer/macos_bootstrap.sh:327-336`;
  `installer/windows_bootstrap.ps1:774-777`
- **Today:** an EMPTY remote root is a named capability miss and exit 3. A
  MIS-TYPED one (`mnt/pool/tree`) is only `warn "--remote-root '...' is not
  absolute. The SFTP session starts in your home directory on the NAS..."` and the
  run completes green - the worse outcome, because lane A then uploads camera
  originals into the editor's bare SFTP home, where nothing indexes them and the
  dashboard never sees them.
- **Proposed:** promote the non-absolute case to a capability miss on both
  platforms, same wording plus "nothing was configured for lanes A and B".
- **Effort:** S   **Value:** high   **Confidence:** high

### OPS-13: only the companion has its quarantine flag stripped; rclone and Syncthing do not
- **Lens:** resilience  **Who:** editor
- **Where:** `installer/macos_bootstrap.sh:2289-2291` (the file's only
  `xattr -d com.apple.quarantine`) vs `:1620-1623` and `:1722-1723`
- **Today:** the script's own comment says a quarantined binary launched by launchd
  "fails with no visible dialog at all", and applies the fix to the companion only.
  rclone and Syncthing are unzipped from curl-downloaded archives into the same
  `~/.local/ccsync/bin`. Because the re-run guard is `[ -x "$BIN_DIR/rclone" ]`,
  every later run prints `skip "rclone already installed"` forever. It presents as
  "lanes A and B just never do anything".
- **Proposed:** `xattr -d com.apple.quarantine "$BIN_DIR/rclone" 2>/dev/null ||
  true` after each `cp`, and the same for syncthing.
- **Effort:** S   **Value:** high   **Confidence:** med

### OPS-14: a truncated download is reported to the editor as tampering, and cites a developer file
- **Lens:** usability  **Who:** editor
- **Where:** `installer/macos_bootstrap.sh:194-197` and
  `installer/windows_bootstrap.ps1:527-531` (identical copy); no download site
  tests curl's exit status and `macos_bootstrap.sh:54` is `set -u` only
- **Today:** hotel wifi drops mid-transfer, or the disk is full; the partial file
  reaches `verify_sha256` and the editor reads "CHECKSUM MISMATCH ... Either the
  mirror served something else, or the pin in this installer is stale -- see
  'Bumping a pinned download' in installer/README.md." Two of three claims are
  wrong and the file named is a repo document they have never seen.
- **Proposed:** test the transfer first: "the download did not finish (network
  interrupted, or this disk is full). Nothing was installed - check your
  connection and free space, then run this again." Keep the mismatch text for a
  complete file that hashes wrong, ending in "tell your admin".
- **Effort:** S   **Value:** med   **Confidence:** high

### OPS-15: nothing can bump a pinned rclone/Syncthing version except a new installer build
- **Lens:** resilience  **Who:** owner, developer
- **Where:** `installer/windows_bootstrap.ps1:301-306` (`v1.75.0`, `v2.1.3` +
  sha256), `installer/macos_bootstrap.sh:79-82` (the same two, separate literals),
  `installer/tests/test_macos_site_values.sh:138` (asserts only that they exist)
- **Today:** the pins are right, but duplicated with no test comparing them and no
  override anywhere. When a publisher withdraws or re-tags a release, every new
  install on that platform ends in a capability miss until a new installer is
  built, signed and published; and a one-line bump on Windows only would silently
  leave the fleet on two different sync engines.
- **Proposed:** a test asserting both files carry the same version AND sha256 (the
  byte-for-byte pattern in `server/tests/test_cross_component.py`), and let the
  site manifest publish `rclone_pin`/`syncthing_pin` that the scripts prefer over
  their compiled-in default, so a withdrawn asset is a dashboard edit.
- **Effort:** M   **Value:** med   **Confidence:** high

### OPS-16: `config.toml` is written non-atomically on macOS and a truncated one is never repaired
- **Lens:** resilience  **Who:** editor
- **Where:** `installer/macos_bootstrap.sh:2424-2425`, `:2482-2541`
- **Today:** every other file this script may need to repair is guarded by a
  CONTENT check that self-heals (the plists compare their program path);
  `config.toml` is guarded by existence alone. A Ctrl-C or a full disk during the
  heredoc leaves a file with no `dashboard_token` and no `remote`, and every future
  run of this "safe to re-run" script prints `skip "companion config already
  exists"` and never fixes it.
- **Proposed:** write to `.tmp` and `mv` into place (the pattern
  `rewrite_rclone_stanza` already uses); before skipping, check the file parses and
  carries the required keys, else "the existing config.toml is incomplete -
  rewriting it".
- **Effort:** S   **Value:** med   **Confidence:** high

### OPS-17: there is no way to uninstall CC Sync that a normal person can find
- **Lens:** usability  **Who:** editor, owner
- **Where:** `installer/build_editor_package.ps1:653-655` (uninstallers ship inside
  the package zip only); no `...\CurrentVersion\Uninstall\...` key is written
  anywhere in the repo (grep: zero hits); `installer/START_HERE.md:283-296`
- **Today:** the wizard path never delivers the package, so the only copy of
  `windows_uninstall.ps1` is in a zip the editor may never have had, and CC Sync
  does not appear in Apps & features. To the editor, their own IT, and the next
  reviewer of this product, the machine has an unremovable background app with a
  tray icon and a firewall rule.
- **Proposed:** have the bootstrap copy `windows_uninstall.ps1` into
  `%LOCALAPPDATA%\ccsync\bin` and register an HKCU uninstall entry (DisplayName
  from the site brand, `UninstallString = powershell -NoProfile -ExecutionPolicy
  Bypass -File "<that path>"`, `NoModify=1`); on macOS drop `macos_uninstall.sh`
  into `~/.local/ccsync/bin` and name it in the completion banner. A tray
  "Uninstall CC Sync…" item is the discoverable version.
- **Effort:** S   **Value:** med   **Confidence:** high

### OPS-18: two copies of the wizard can run at once, each doing its own clean slate
- **Lens:** resilience  **Who:** editor
- **Where:** `onboarding/onboard.py:1259-1264` (no instance guard), `:937-966`,
  `onboarding/steps.py:1063-1090` (`terminate_bootstrap` knows only its own child)
- **Today:** `onboard.exe` is a one-file PyInstaller build that unpacks for several
  seconds with no splash and no window; the natural response to "nothing happened"
  is a second double-click. Two wizards then run two clean slates and two
  bootstraps against the same drive letter, bin directory, `config.toml` and
  Syncthing home; the second teardown can delete what the first just installed, and
  the breadcrumb is cleared by whichever finishes last.
- **Proposed:** a named mutex (`Global\ccsync-onboard`, or a lockfile under
  `~/.ccsync/state`) at the top of `main()`; a second instance raises the first
  window or says "The CC Sync installer is already running on this computer."
- **Effort:** S   **Value:** med   **Confidence:** high

### OPS-19: the Tailscale button reports success whatever winget did
- **Lens:** both  **Who:** editor
- **Where:** `onboarding/onboard.py:639-651`
- **Today:** `subprocess.run([...winget install...])` with no `check`, no
  return-code test and no captured output; the only failure path is winget being
  absent. A declined UAC prompt, a source failure, "no applicable installer found"
  all end at "winget install finished -- sign in to Tailscale, then Check
  connection". The editor then gets "tailscale isn't joined yet -- open the
  Tailscale tray icon and sign in" and hunts for an icon that is not there.
- **Proposed:** keep the return code; on non-zero: "Tailscale did not install
  (winget exit <n>). Use [ OPEN DOWNLOAD PAGE ] and install it by hand, then come
  back and check the connection." Re-run `steps.tailscale_installed()` so the
  INSTALLED / NOT INSTALLED line is not stale.
- **Effort:** S   **Value:** med   **Confidence:** high

### OPS-20: nothing prepares a new editor for SmartScreen, which is their first click
- **Lens:** usability  **Who:** editor, owner
- **Where:** `dashboard/templates/installer.html:16-49`,
  `installer/START_HERE.md:11-45`, `tools/check_deploy_drift.ps1:558-565`
- **Today:** with no certificate yet, `onboard.exe` from the dashboard meets
  "Windows protected your PC", default button **Don't run**, the way through hidden
  behind "More info". The developer side is documented everywhere (KNOWN_BUGS,
  RELEASE.md, a drift check); the EDITOR side nowhere. START_HERE explains the
  macOS quarantine equivalent in detail and says nothing about Windows.
- **Proposed:** under the Windows pick on `installer.html`: "Windows will say
  'Windows protected your PC'. Click **More info**, then **Run anyway** - the
  installer is not code-signed yet. The file's sha256 is shown above if you want to
  check it." (The page already renders `pkg.sha256`.) Same in START_HERE.md.
- **Effort:** S   **Value:** med   **Confidence:** high

### OPS-21: START_HERE.md tells Mac editors there is no wizard, and hardcodes `P:`
- **Lens:** usability  **Who:** editor
- **Where:** `installer/START_HERE.md:47-53`, `:26-30`
- **Today:** "**On a Mac?** There's no click-through wizard ... it serves the Mac
  script (`ccsync-onboard-<version>.sh`)". Since installer 1.0.17 the wizard runs
  on macOS (`build_onboard_macos.spec`; `tools/build_onboard_macos.sh:588` - "a
  Mac's [ INSTALLER ] click now downloads ccsync-onboard-$VERSION.zip"), so every
  Mac editor is sent down the hard path: Terminal, chmod, quarantine xattr, and
  flags from the owner. The same file says the wizard "remounts your P: drive
  fresh" after the drive letter became site data, and names the role buttons
  "REMOTE EDITOR" / "BASE" where the wizard reads "I'M A REMOTE EDITOR" / "I'M
  PHYSICALLY CONNECTED TO THE SERVER/NAS" (`onboard.py:474-490`).
- **Proposed:** rewrite the Mac paragraph around the .app wizard with the .sh as
  fallback; say "your project drive (P: by default)"; quote the buttons as rendered.
- **Effort:** S   **Value:** med   **Confidence:** high

### OPS-22: Syncthing's own config is outside both snapshot targets and is not named as a gap
- **Lens:** resilience  **Who:** owner
- **Where:** `server/install_syncthing_app.py:50-60` (`"config": {"type":
  "ix_volume", ...}`), `docs/BACKUP_RESTORE.md:46-58` and `:514-526`
- **Today:** on TrueNAS, Syncthing is a catalog app whose config - every device
  pairing, every folder share, the GUI credentials - lives in a TrueNAS-managed
  `ix_volume`, outside both `[tree] pool_root` and `[apps] root`, the only two
  things `setup_snapshots.py` knows about. The protected table lists five databases
  and the app code and never mentions it; §8 does not list it as a deliberate
  omission either. Losing that volume loses every editor's pairing.
- **Proposed:** add the row with an honest "NOT covered - relies on the TrueNAS
  Apps pool", and name the real recovery path (re-approve every device via
  `accept_device.py` or the pending-devices panel) in §8.
- **Effort:** S   **Value:** med   **Confidence:** high

### OPS-23: the hand-run instructions leak the fleet token and produce unusable SSH keys
- **Lens:** resilience  **Who:** editor, owner
- **Where:** `installer/macos_bootstrap.sh:115-116`, `MACOS_FIRST_RUN.md:335-337`,
  `docs/macos-onboarding-handoff.md:114`; `macos_bootstrap.sh:2174`, `:2656-2657`,
  `windows_bootstrap.ps1:2232-2233`, `START_HERE.md:203-208`
- **Today:** (a) the documented hand-run is `DASHBOARD_TOKEN=<token>
  ./macos_bootstrap.sh ...`, so the fleet credential lands in `~/.zsh_history`
  permanently - while the same value is passed in the environment rather than argv
  by the wizard and chmod 600'd in `config.toml` (SEC-14). (b) Every printed
  `ssh-keygen -t ed25519 -f <path>` omits `-N ""`, so a security-minded editor sets
  a passphrase; rclone under a LaunchAgent has no agent to unlock it and lanes A/B
  fail authentication forever with a message that never mentions passphrases.
- **Proposed:** accept `--token-file <path>` (stdin for `-`) and document that
  form, plus one line after a hand-run about `history -d`; add `-N ""` to every
  printed keygen with "no passphrase: the sync app has to use this key with nobody
  logged in", and have `ensure_ssh_key` detect an encrypted key
  (`ssh-keygen -y -P ""` fails) and raise `SshKeyError` into the warning list.
- **Effort:** S   **Value:** med   **Confidence:** med

### OPS-24: INSTALL.md's walkthrough has three small blockers for a non-technical owner
- **Lens:** usability  **Who:** owner
- **Where:** `docs/INSTALL.md:87-92` (`$EDITOR site.toml`, on a base rig INSTALL.md
  itself calls Windows at line 55); `:343-380` with `check_health.py`
  (`site_bool("stack", "project_server", True)`); `docs/SERVER-SYNOLOGY.md:375`
- **Today:** the first command block of the whole install is bash syntax that does
  nothing in PowerShell. The Step 8 verification then FAILs the Postgres check on
  any site not running a shared Resolve Project Server, because the flag defaults
  to true and Step 1 never mentions it. And several SERVER-SYNOLOGY examples omit
  `--site`, which silently targets the wrong customer's NAS on a laptop holding
  several `site.toml` files.
- **Proposed:** `notepad site.toml`; add "not running a shared Resolve Project
  Server? set `[stack] project_server = false` or the Postgres check FAILs by
  design" to Step 1; pass `--site site.toml` in every example.
- **Effort:** S   **Value:** med   **Confidence:** high

### OPS-25: small copy defects with real consequences
- **Lens:** usability  **Who:** editor
- **Where:** `onboarding/onboard.py:1184` (`warnings[:6]`), `:1247-1251`,
  `:1195-1198`; `installer/macos_bootstrap.sh:1415` + `:1470`
  (`wait_for_resolve_quit || true`), `:169-173`
- **Today:** seven capability warnings render as six with no "and 1 more" while the
  heading counts all seven. [ COPY ] gives no feedback on the one page whose
  purpose is copying two values, and when the device ID was not found it copies the
  sentence "(not found automatically -- open http://127.0.0.1:8384, Actions > Show
  ID)" into the message sent to the admin. "Please quit DaVinci Resolve. This will
  continue automatically" is broken silently at 180 s: the timeout return is
  discarded and an unrelated-looking "Resolve is running -- quit it and re-run"
  appears minutes later. A missing `--editor-name` dumps the usage block without
  naming the missing flag.
- **Proposed:** scroll the warning list; flash [ COPIED ] and disable the button on
  a placeholder; "gave up waiting for Resolve after 180s - carrying on without the
  Mapped Mount, run `$0 --resolve-mapping-only` later"; name the missing flag.
- **Effort:** S   **Value:** low   **Confidence:** high

## Still open from 08-28
- OPS-2 NAS free space / snapshot churn: **not built** (no `df`/`zfs list` in
  `server/`; `check_health.py` still has no capacity check).
- OPS-5 sshd Match block: no backup, no post-write SSH probe, no refusal when the
  operator's own text already carries a `Match`: **not built**
  (`server/backends/truenas.py:626-661`).
- OPS-10 `publish_db` never sweeps its own `/tmp` staging: **not built**.
- OPS-11 index backups uncounted: **partly built** - `--rollback` finds the newest
  `.prev-*`, nothing lists or totals them.
- OPS-13 the project marker is written non-atomically and a slug-less marker is a
  dead end: **not built** (`server/common.py:719-723`).
- OPS-14 `check_health` validates liveness only: **partly built** - it prints a
  score now; no capacity, snapshot-freshness, marker-invariant,
  marker-vs-Syncthing-folder or deployed-version check.
- OPS-17 a timed-out `run_ssh` leaves the remote command running with no lock:
  **not built** (no `flock` in `server/`).
(Built since: 08-28 OPS-1, -3, -4, -6, -7, -8, -9, -12, -15, -16.)

## Cross-cutting notes
- **Dashboard agent:** OPS-2 is half yours - Settings > Users holds the ordering
  trap and the missing key-update control (`admin_users.html:313-325`,
  `api.py:4113` local-mode-only key routes); the page shows `has_ssh_key` with no
  way to act on a `false`. OPS-3's RECOVERY page should say it was never given a
  snapshot mount rather than degrade silently.
- **Companion agent:** the wizard's Finish page and the tray both claim "signed in"
  and neither confirms the machine has reported; a "this computer is now visible to
  your admin" tick driven by the first successful report would close the loop the
  two-values ceremony leaves open.
- **Release/CI agent:** the CR guard in `build_editor_package.ps1:690-701` checks
  `macos_bootstrap.sh` only, while `macos_uninstall.sh` also ships in the package
  and executes on a Mac - loop it over every `.sh` in `$Files`. OPS-15's pins,
  OPS-20's SmartScreen copy and OPS-8's key backup sit beside the Authenticode work.
- **Docs:** `MACOS_FIRST_RUN.md:246`, `:620` still drill the retired
  `com.creatorsclub.ccsync.companion` label and `:690` checks for a
  `[creators_club_sftp]` stanza (both renamed 2026-08-17), so a validator records
  passing drills as failures. `APPLIANCE_INSTALL.md:17-20` promises "No SSH, no
  terminal" and its step 4 (`:117-142`) is a `docker compose exec` from a shell;
  one line before it ("this step needs a terminal, despite the promise above")
  keeps the honesty. `SYNOLOGY_EASY_INSTALL.md` reads like a runbook and should be
  titled DESIGN ONLY.
