# Pre-launch bug hunt 2026-10-06 - lens `bug-server`

Territory: `server/` (common.py, install_dashboard_app.py main flow + install_tree /
swap / prune / db swap / ffmpeg scripts, publish_db.py, broll_drain.py,
setup_tree.py, setup_editor_account.py, setup_syncthing_folder.py,
accept_device.py, write_marker.py, setup_snapshots.py, secure_syncthing_gui.py,
create_api_key.py, backends/truenas.py and the deploy/identity half of
backends/synology.py), `dashboard/deploy/` (Dockerfile, run.sh,
select_code_root.py, compose.yaml / compose.image.yaml / compose.appliance.yaml,
the sftp sidecar), and docs/APPLIANCE_INSTALL.md against what the stack does.

Probes (scratchpad, no network, no NAS): `Settings.from_env()` with the exact
environment compose.appliance.yaml gives the dashboard (auth method, SMB host,
admins, Syncthing URL); run.sh's trap/wait loop reproduced in a shell.
Not covered in depth: check_health.py (read-only, scanned for mutations only),
install_syncthing_app.py beyond its GUI binding, the Synology DSM identity
calls beyond the takeover guards, tools/Dockerfile.indexer-gpu.

Checked against KNOWN_BUGS.md, docs/bug-hunt-2026-09-24*, COMMERCIAL_READINESS.md.

### bug-server-1 - The appliance stack boots with no way for anyone to sign in
- Severity: critical
- Confidence: CONFIRMED (probed)
- Where: dashboard/deploy/compose.appliance.yaml:153-173; dashboard/src/ccsync_dashboard/settings.py:807; dashboard/src/ccsync_dashboard/setup_routes.py:60-90; auth.py:158-165
- What: compose.appliance.yaml sets no `DASH_AUTH_METHOD`, so it defaults to `smb`. It sets no `DASH_SMB_HOST` and no `DASH_ADMIN_USERS` either. Under `smb`, the first-run window is closed (`setup_routes` returns False unless the method is `local`), every `/api/v1/setup/*` route needs an admin session, and `verify_credentials` probes SMB on an empty host. `auth.check_boot_secrets` does not object, so the container boots healthy.
- Scenario: A customer follows APPLIANCE_INSTALL.md: paste compose, `up`, open :8480. `/setup` redirects to /login, and no username or password can pass it. There is no admin, no wizard and no recovery short of editing the compose file the doc says must not be edited. Probe: `Settings.from_env()` on that environment returns `auth_method smb`, `smb_host ''`, `admins frozenset()`, `syncthing_url ''`, and the boot raises no problem about any of them.
- Recommendation: Set `DASH_AUTH_METHOD: "local"` in compose.appliance.yaml, and add a tools/tests/test_compose_appliance.py assertion that pins it. Also have `check_boot_secrets` refuse `smb` with an empty `smb_host`, because that combination can never authenticate anyone.
- Known: none (APPLIANCE_INSTALL.md describes steps 1-2 as working)

### bug-server-2 - Appliance dashboard is never wired to its own Syncthing, its release keys or the tailnet
- Severity: high
- Confidence: CONFIRMED
- Where: dashboard/deploy/compose.appliance.yaml:153-203; settings.py:797,840,910; setup_engine.py:881-899; docs/APPLIANCE_INSTALL.md (step 3 table row 6, "What IS true today")
- What: Nothing sets `SYNCTHING_GUI_URL`, and no DB or site_settings path sets it either (`settings.syncthing_url` comes from the env only). The dashboard is not in tailscale's network namespace, so it could only reach Syncthing at `http://tailscale:8384`, and nothing points it there. `DASH_RELEASE_PUBKEYS` is also unset, and nothing generates or bakes it: it is the vendor's public key and cannot be minted at first boot as the compose comment claims. Serve is never configured, so the dashboard stays on 127.0.0.1. `DASH_NAS_KIND` is left unset "so the dashboard knows the wizard has not run", but settings.py:840 turns unset into `truenas`.
- Scenario: The "Sync engine" step that APPLIANCE_INSTALL.md says "reaches the Syncthing already in the stack" stays `todo: SYNCTHING_GUI_URL not configured` forever. The collector runs only the Syncthing-free kinds, so no project folder is ever provisioned or shared, and lane C never works. The release feed and the publish route refuse without pubkeys (no companion builds, no OTA). Editors' companions cannot reach a loopback-only dashboard. The appliance cannot sync anything.
- Recommendation: Add `SYNCTHING_GUI_URL: "http://tailscale:8384"` to the dashboard service (or move the dashboard into the tailscale netns) and test it. Bake the vendor pubkey into the image or the appliance compose as non-secret data. Either finish WP B's Serve call or stop calling the appliance installable. Fix or remove the DASH_NAS_KIND comment.
- Known: APPLIANCE_INSTALL.md admits Serve and publishing are "NOT YET TRUE". The Syncthing URL and pubkey gaps are not recorded anywhere.

### bug-server-3 - Syncthing GUI is an unauthenticated admin surface on both install paths
- Severity: high
- Confidence: PLAUSIBLE (the netstack forwarding was not probed live; the compose file's own claims about :22/:22000 rely on the same mechanism)
- Where: dashboard/deploy/compose.appliance.yaml:264-279; server/backends/truenas.py:304-323,387-393; server/secure_syncthing_gui.py (never run by any installer)
- What: Appliance: `STGUIADDRESS: 0.0.0.0:8384` inside the tailscale container's network namespace, which runs `--tun=userspace-networking`. In that mode tailscaled forwards inbound tailnet TCP to the listeners in its namespace. That is exactly how the comment says :22 and :22000 become reachable, so :8384 is reachable from every tailnet peer too. No GUI user or password is ever set, by secrets-init or by the dashboard (no code calls `/rest/config/gui`). The comment "The GUI is deliberately never exposed anywhere outside this namespace" contradicts the comment two blocks above it. TrueNAS: install_syncthing_app publishes the GUI on every NAS interface with no password unless `[syncthing] gui_bind` is set and an operator separately runs secure_syncthing_gui.py. It only prints a WARNING.
- Scenario: Any editor laptop on the customer's tailnet opens `http://<node-ip>:8384`. It gets full Syncthing admin over `/data` (the whole tree): it can share any folder to its own device, re-point folders, or turn on delete propagation. On TrueNAS the same applies to anyone on the LAN.
- Recommendation: Bind the GUI to 127.0.0.1 in the appliance and reach it some other way (shared netns or a socket), or have the dashboard set a GUI user and a random password at boot through the API key. Make install_syncthing_app run the secure_syncthing_gui step itself instead of printing advice.
- Known: COMMERCIAL_READINESS item 7 finding H4 (the TrueNAS half is "documented"). The appliance half is not recorded.

### bug-server-4 - TrueNAS setup_editor_account.py takes over ANY existing account, admin and root included
- Severity: high
- Confidence: CONFIRMED (code read)
- Where: server/setup_editor_account.py:493-581; server/backends/truenas.py:443-529,505-516 (no guard); contrast backends/synology.py:607-701 `_refuse_non_editor` and dashboard/src/ccsync_dashboard/nas/truenas.py:65-67 `MIN_EDITOR_UID`
- What: `USERNAME_RE` accepts `root`, `truenas_admin` and any existing staff account. `find_user` finds it, and `update_editor` then PUTs `sshpubkey=<editor key>`, which REPLACES the account's authorized keys, and adds the account to `editors`. Then `ensure_home_permissions` runs setperm 700 stripacl on its home (only `/root`, `/home` and the homes parent are forbidden), and `set_password_disabled` PUTs `password_disabled: true`. The Synology backend refuses reserved, system and non-editors accounts. The dashboard refuses uid < 1000. The TrueNAS path in server/ has neither guard.
- Scenario: An operator onboards themselves or a colleague whose editor username equals an existing NAS login, for example the owner whose admin account is `alex`, or a typo of `truenas_admin`. The admin's SSH key becomes the editor's key, so a freelancer's passphrase-less key now logs in as the admin. The admin joins `editors`, so the sshd `Match Group editors` block forces internal-sftp and `PasswordAuthentication no` on it, and every script in server/ (password SSH as the admin) stops working. If the account is not an SMB user, its password login is disabled outright, which can mean losing the web UI too.
- Recommendation: Port `_refuse_non_editor` to TrueNASBackend.create_editor/update_editor. Refuse builtin, uid < 1000 and accounts not already in `editors`, and refuse any name equal to `[nas] admin_user`. Add a test.
- Known: none

### bug-server-5 - run.sh image mode: `docker stop` kills PID 1 before uvicorn finishes shutting down
- Severity: medium
- Confidence: CONFIRMED (probed)
- Where: dashboard/deploy/run.sh:592-602
- What: When the trapped signal arrives, `wait "$app_pid"` returns 143 immediately. The trap only forwards TERM, and the script then sees rc=143 (not 75) and `exit 143`. PID 1 exits while uvicorn is still in its graceful shutdown, and the kernel SIGKILLs every remaining process in the container. The comment says the trap exists to avoid exactly that kill. Probe: the parent printed `wait returned rc=143; child alive? yes` and exited, and the child's 2-second cleanup ran after the parent was gone.
- Scenario: Every `docker stop`, NAS image update, `--recreate` or reboot in image mode (the mode the studio and every feed customer run) skips the lifespan shutdown. That shutdown stops the Cards engines and their threads, the collector, ytdl workers and in-flight requests, all of which now die mid-write. Bind mode is unaffected (it `exec`s uvicorn).
- Recommendation: After the first `wait`, loop `while kill -0 "$app_pid" 2>/dev/null; do wait "$app_pid" || rc=$?; done` before deciding on the exit code. Or `exec` a tiny supervisor as ZERO_DOWNTIME_DEPLOY 3.1 plans.
- Known: KNOWN_BUGS WPK-3 (open, generic: "the exit-75 loop under a real container runtime's signal handling" untested)

### bug-server-6 - select_code_root boots OTA code whose files are never re-verified
- Severity: medium
- Confidence: CONFIRMED (code read)
- Where: dashboard/deploy/select_code_root.py `check_tree`; dashboard/src/ccsync_dashboard/dashboard_update.py:846-866 (files_sha256 checked at apply only)
- What: At boot, the signature check covers record.json and a few manifest fields. Nothing hashes `/data/code/<v>/src`, the three sub-app trees, or ties manifest.json's `files_sha256` back to the files on disk. The docstring says "the tree in /data ... gets no vote: nothing from it is imported, executed or trusted before the verification below passes", but the verification never looks at the files that are then imported.
- Scenario: One code-execution bug in any in-process app runs as the dashboard uid, which owns /data. The ytdl worker, for example, runs an unpinned nightly yt-dlp on untrusted pages. That bug rewrites `/data/code/<v>/src/ccsync_dashboard/*.py`. The modified tree is booted on every restart, recreate and image pull (until the image catches up), reported as a signed, verified tree, and keeps NAS credentials in reach.
- Recommendation: In check_tree, re-hash the tree against `files_sha256`, and make sure that list is covered by the signature (put the manifest digest into the signed record). A mismatch is a refusal that counts toward the revert. Or keep the trees in a location the app uid cannot write.
- Known: none

### bug-server-7 - Image-mode deploys fail their own health gate whenever the image is not the checkout's VERSION
- Severity: medium
- Confidence: CONFIRMED (code read)
- Where: server/install_dashboard_app.py:1762-1778, 1889-1930, 5990, 6139
- What: `verify_dashboard_after_restart` requires the running `/api/v1/health` version to equal the checkout's `dashboard/__init__.py` VERSION in both modes. Image mode ships no code: what runs is the image's version or an OTA tree, which is routinely newer or older than whatever checkout the operator runs from. server/tests/conftest.py stubs the probe to return the expected version, so the suite cannot see this.
- Scenario: The studio (image mode) runs `install_dashboard_app.py --recreate` to apply a compose change from a checkout one version ahead of `:1`, or with an OTA-applied 0.7.74 running. The probe reports "serving v0.7.73 but this checkout deployed v0.7.74" for 150 s, then prints a rollback one-liner for an app tree this run never touched, and exits 1. ship.cmd stops. With `--rollback-on-unhealthy` it prints CANNOT ROLL BACK.
- Recommendation: In image mode, compare against the version the image or current.json declares (verify_image_boot already reads boot facts), or accept any healthy answer. Do not print the bind-mode rollback line in image mode.
- Known: none

### bug-server-8 - Optional Postgres profile publishes a superuser with Resolve's default password on all interfaces
- Severity: medium
- Confidence: CONFIRMED (code read)
- Where: dashboard/deploy/compose.yaml:763-783; dashboard/deploy/compose.image.yaml:~415-425
- What: `POSTGRES_PASSWORD: "${PG_PASSWORD:-DaVinci}"` with `ports: "${DASH_PG_PORT:-5432}:5432"`, which binds 0.0.0.0. This is the only port in the stack published on every interface without an explicit bind address.
- Scenario: A customer enables `--profile project-server` as documented and keeps the default password, as Resolve users routinely do. Anyone on the LAN, or on any interface the NAS gains later, connects as `postgres` superuser. They can read or alter every Resolve project, and `COPY ... FROM PROGRAM` gives them a shell in the container, which mounts `<apps root>/postgres`.
- Recommendation: Bind to the same DASH_BIND_* addresses as the dashboard, and refuse to start the profile while PG_PASSWORD is unset or equal to `DaVinci` (`${PG_PASSWORD:?}`).
- Known: none

### bug-server-9 - The "scoped" TrueNAS API key is still root-equivalent
- Severity: medium
- Confidence: PLAUSIBLE (TrueNAS role semantics not probed)
- Where: server/create_api_key.py:1-60,76-82,160-175; COMMERCIAL_READINESS item 6 / H3
- What: The key exists so the container no longer holds a root-equivalent credential. Its scope is ACCOUNT_WRITE (PUT /user on any account, password and sshpubkey included) plus FILESYSTEM_ATTRS_WRITE (setperm/chown of any path). Both are root by one step: reset the admin's password or keys, or chmod/chown anything. And without `--username` the key is minted as TRUENAS_USER, the admin itself (the script only warns).
- Scenario: The threat model is code execution in the dashboard container. That code reads TRUENAS_API_KEY, PUTs `/user/id/<truenas_admin>` with a known password or its own sshpubkey, and SSHes in with sudo. The deploy prints "the admin password is NOT written into the container", which an operator reads as containment that is not there.
- Recommendation: Refuse to mint without a dedicated `--username`. Document the residual risk honestly. Prefer a middleware-side constraint (TrueNAS privileges scoped to a group, if available), or move account writes out of the container to an operator-run path.
- Known: COMMERCIAL_READINESS item 6 (treated as mitigated)

### bug-server-10 - Live b-roll databases sit in the editor-writable SMB share
- Severity: medium
- Confidence: PLAUSIBLE (depends on the dataset ACL, the shape install_dashboard_app creates)
- Where: server/install_dashboard_app.py:5659-5713 (archive root `<uid>:editors 2770`); server/publish_db.py:198 (broll.db installed `broll:editors 660`); broll/web/app/client_folders.py:143 (client_shares.db in the data root)
- What: `/broll-data` is the shared archive editors browse as `P:\Assets\B-roll Archive`. broll.db is group-editors read/write, and because the directory is 2770 group-writable, any editor can also delete, rename or replace client_shares.db (the client-link ledger, kept apart from broll.db precisely so a publish cannot take it) and every `broll.db.drain-*` and `.prev-*`.
- Scenario: Ransomware on one wired editor's PC encrypts what P: shows. That takes out the live search index, every customer's client share links and the publish rollback copies in one pass. Any editor can also substitute a crafted broll.db that the dashboard process, which holds NAS credentials, opens and renders.
- Recommendation: Keep the databases in a private app directory (like music.db under `<apps root>/music-data`) and expose only proxies, sprites, posters and sheets through the share. At minimum, make broll.db 0600 owned by the service uid and put the DB files in a non-editor-writable subdirectory.
- Known: none

### bug-server-11 - Two rename sequences can leave the live thing missing or nested on a partial failure
- Severity: low
- Confidence: CONFIRMED (code read)
- Where: server/install_dashboard_app.py:3359-3364 (build_db_swap_script), 1846-1860 (rollback_one_liner)
- What: (a) Under `set -e`, after `mv db old` the sidecar `mv`s run before the guarded `mv new db || {rollback}`. A failing sidecar move exits the script with the live index renamed away and nothing in its place. (b) The rollback one-liner is `mv app app.failed-X; mv old app; docker restart` with `;` and UNQUOTED paths (HOST_ROOT_RE allows spaces). If the first `mv` fails, the second moves the old tree INSIDE the failed `app/` and the restart serves the failed code. A space in the root breaks both commands.
- Scenario: An EBUSY or EPERM on the `-shm` during a publish leaves `/broll-data/broll.db` absent, and /broll 500s until someone renames `.prev-*` back by hand.
- Recommendation: Move the sidecars inside the guarded group, or put the db and its sidecars back on any failure after the first rename. Use `&&` and shell_quote in rollback_one_liner.
- Known: none

### bug-server-12 - Pinned ffmpeg URL points at a directory the upstream prunes
- Severity: low
- Confidence: PLAUSIBLE (not fetched: network excluded)
- Where: server/install_dashboard_app.py:424-430
- What: `https://johnvansickle.com/ffmpeg/releases/ffmpeg-7.0.2-amd64-static.tar.xz` comes from a personal mirror whose `releases/` directory carries the current release only; superseded builds move to `old-releases/`. It is also amd64-only, while the Dockerfile advertises arm64.
- Scenario: Once upstream ships a newer release, every new customer's `remote` fetch 404s. The step is non-fatal, so the deploy says success while /music ingest, /ytdl's edit-ready transcode and Timeline Cards' audio extraction all lack ffmpeg.
- Recommendation: Host the pinned tarball yourselves (with the GPL source offer), or fall back to `old-releases/`, and make a missing ffmpeg a loud deploy summary line.
- Known: none

### bug-server-13 - TrueNAS custom_app body carries secrets unescaped through compose interpolation
- Severity: low
- Confidence: PLAUSIBLE (whether the middleware escapes `$` was not verified)
- Where: server/install_dashboard_app.py:2627-2662 (compose_config environment), deploy_stack (backends/truenas.py:168-195)
- What: TRUENAS_PW/DASH_NAS_PW (operator-chosen), ANTHROPIC_API_KEY and the site strings go into the compose dict verbatim. If the middleware hands that to `docker compose` as YAML, `$x` is interpolated and a lone `$` is a template error. The Synology path guards its `.env` explicitly (render_env_file); this path has no equivalent.
- Scenario: A customer whose NAS admin password contains `$` deploys. The container's DASH_NAS_PW is silently truncated, so Admin > Users fails authentication, or the create job fails with "invalid interpolation format".
- Recommendation: Escape `$` as `$$` in every literal value of the dict, or refuse the value as render_env_file does, and add a test.
- Known: none

### bug-server-14 - Unpinned nightly yt-dlp installed into the process that holds NAS credentials
- Severity: low
- Confidence: CONFIRMED (deliberate)
- Where: dashboard/deploy/run.sh:353-425; ytdl/web/ytdlweb/ytdlp_nightly.py:80-90
- What: `pip install --pre --upgrade` from PyPI with no hash, daily, shadowing the hash-pinned lock on sys.path of the dashboard process (which holds TRUENAS_PW/API key, the report token and the session secret). It is gated on the site's YouTube flags (off in the vendor build).
- Scenario: A compromised or typosquatted yt-dlp pre-release reaches every customer with youtube_download on within 20 h, as code running inside the fleet dashboard.
- Recommendation: Run the downloader in its own sidecar without the dashboard's secrets, or pin nightly by digest from yt-dlp's signed GitHub releases.
- Known: CR-361 (owner decision 2026-10-05; the exception to COMMERCIAL_READINESS item 13)
