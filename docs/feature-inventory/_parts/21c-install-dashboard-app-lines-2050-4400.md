I read all of lines 2050 to 4400 and both compose templates the code uses. Five gaps stood out, listed first; the full notes follow.

- **Synology loses five site features.** The Synology deploy renders the compose file from the template, and both templates hard-code `"0"` for YouTube download, YouTube unblock, the CLI AI providers, the studio CLI lock and auto-update. So a Synology site's own `site.toml` choices for these never reach its container. The TrueNAS path does pass them through. I did not trace whether `main()` patches the rendered file afterwards.
- **The Synology file also lacks eight pieces the TrueNAS deploy adds:** `group_add`, the Cards vault and media mounts, the sorter pool mount, the snapshot mount, the deno mount, the Node mount, the `bgutil` sidecar and the Cards editor variables. The snapshot variables are still filled in, so a Synology container may be told a snapshot folder exists that was never mounted.
- **Two different "roll back" answers.** After a failed health check the script prints, and with `--rollback-on-unhealthy` runs, a swap of the app folder. After a failed image-mode boot check it prints "redeploy with `--mode bind`" instead. Only the first can run on its own.
- **Image-mode version check.** In image mode, `verify_dashboard_after_restart` still expects this checkout's version unless the caller passes the expected one. Whether `main()` always does was outside my range.
- **The health budget is not a hard limit.** It is 150 seconds, but each attempt can wait up to 60 seconds for its SSH call, so a run can take up to about 210 seconds.

# Deploy script, lines 2050 to 4400: image mode, health and rollback, container environment, compose rendering, secrets, music index install

## Checking the NAS service account's uid and gid (TrueNAS) (source: install_dashboard_app.py `truenas_identity_mismatch`)
- `[stack] private_gid` (default: same as `[stack] uid`, which defaults to 3000) is the group on the container's private folders (data, venv, music-data, ytdl-data, sorter-data).
- `[stack] uid` defaults to 3000 and `[stack] gid` to 3001. The container runs as `uid:gid`.
- The service account name is `[stack] owner` (default `broll`) and the editors group is `[stack] group` (default `editors`).
- The check is skipped entirely on a dry run, which returns "no mismatch".
- Otherwise it runs `id -u <owner>; getent group <group> | cut -d: -f3` over SSH (30 s timeout).
- If the SSH call raises, it prints `WARNING: could not read the live uid/gid of '<owner>': <error>` and passes as "no mismatch".
- If the answer is a non-zero exit, fewer than two lines, or not digits, it prints `WARNING: could not read the live uid/gid of '<owner>' / '<group>'; deploying with [stack] uid/gid U:G unchecked` and passes.
- On a mismatch it returns a sentence for the caller to show, naming the difference and the fix:
  - "'<owner>' is uid X on this box but the container would run as Y"
  - and/or "group '<group>' is gid X but the container would use Y"
  - followed by ". Set [stack] uid = X and gid = Y in site.toml (the container then writes the tree as the account the editors' share is owned by)."
  - Whether this is a refusal is decided in `main()`, which I did not read.

## Which NAS platform and which deploy shape (source: install_dashboard_app.py `deploy_nas_kind`, `resolve_stack_mode`, `resolve_container_image`, `mount_target`)
- **Platform:** `--nas-kind`, else environment `CCSYNC_NAS_KIND`, else `[nas] kind`. If that lookup raises a configuration error it silently becomes `truenas`.
- **Stack mode** is `bind` or `image`. It comes from `--mode`, else `[stack] mode`, else `bind`, and is lower-cased.
  - Any other value is a refusal: `unknown stack mode '<x>' -- expected one of bind, image. It comes from --mode, else [stack] mode in the site manifest; 'bind' is the default and what every deployment runs today (docs/DOCKER.md).`
- **Bind mode** runs a stock pinned `python:3.12.7-slim` image with the app code bind-mounted in from the NAS.
- **Image mode** runs the vendor-built image. The image is chosen from `--container-image`, else environment `CCSYNC_IMAGE`, else `[stack] image`, else `ghcr.io/the-creators-club/ccsync:1`.
- When a volume entry is filtered by its container path, the path is taken as the second colon-separated field. This copes with host paths that contain spaces, such as "B-roll Archive".

## Expected runtime id (source: install_dashboard_app.py `expected_runtime_id`)
- The script computes the "runtime id" an image built from this checkout would carry. It does this from `dashboard/deploy/requirements.lock` and `dashboard/deploy/Dockerfile`, using the dashboard's own runtime-id code loaded by file path.
- Any failure gives an empty value and is advisory only. It never stops a deploy.

## Vendor defaults switch and release keys (source: install_dashboard_app.py `_vendor_switch`, `effective_release_pubkeys`, `effective_release_feed_url`, `invalid_release_pubkeys`)
- Environment `DASH_VENDOR_DEFAULTS` in the deploying shell: exactly `1` turns the switch on; anything else is off (default off).
- **`DASH_RELEASE_PUBKEYS` handed to the container:** the deploying shell's `DASH_RELEASE_PUBKEYS` if it has any non-blank content. Otherwise, with the switch on, the vendor's baked-in public key(s) from `vendor_defaults.VENDOR_RELEASE_PUBKEYS`, comma-joined. Otherwise the raw (blank) value.
- **Release feed URL:** `[releases] feed_url`. If blank and the switch is on, `vendor_defaults.VENDOR_FEED_URL`. Otherwise blank.
- **Key validation:** the value is split on commas and whitespace. Each item must base64-decode strictly to exactly 32 bytes (an Ed25519 public key). Items that fail are listed as bad.

## Image-mode preflight, run before anything moves (source: install_dashboard_app.py `image_mode_preflight`)
- Always prints `stack mode: image -- <image>`.
- If the image reference has no `@sha256:`, it prints a NOTE to stderr that a tag is mutable and suggests pinning `[stack] image` to a digest.
- If the image starts with `ghcr.io/the-creators-club/ccsync:1`, it prints a NOTE that the `:1` tag only exists after a `v*` release and to use `:edge` or its digest until then.
- If the release feed URL is blank, it prints a WARNING. The text says the vendor feed is off (no poller, no network call, no code update offered on the Packages page), that image mode without a feed is still valid, and to set the URL if self-updating is why you are migrating.
- If the expected runtime id was computed, it prints `expected runtime id: <id>` and `  after boot:  docker exec <container> cat /venv/.runtime-id`. It adds that a different value is not an error but means over-the-air updates stamped with this one will be refused as a runtime change.
- If it could not be computed, it prints a NOTE that the post-deploy check will report the container's value without comparing it.
- **Refusal 1:** any `DASH_RELEASE_PUBKEYS` entry that is not a 32-byte base64 key. The message starts `DASH_RELEASE_PUBKEYS holds a value that is not an Ed25519 public key (<first 12 chars>...).`
  - It explains that the dashboard silently drops such a value, so every publish answers 503 and every feed record is refused.
  - It says the value is the vendor's 44-character base64 public key, and "Do not run `openssl rand` on it."
- **Refusal 2:** `DASH_RELEASE_PUBKEYS` empty, after applying the vendor switch. The message starts `DASH_RELEASE_PUBKEYS is empty, and image mode needs it.`
  - It explains that the image verifies every code tree in `/data/code` against these keys before booting it. With no keys the image always wins and no over-the-air update can ever apply, and the publish route answers 503.
  - Fix: set the vendor's key, or export `DASH_VENDOR_DEFAULTS=1`.
  - It warns that a customer must not mint their own key: a self-signed key rejects every vendor build and cuts the site off the vendor feed.
- On a dry run that passes, it prints `[dry-run] DASH_RELEASE_PUBKEYS is set`.

## Post-deploy health probe (both modes) (source: install_dashboard_app.py `probe_dashboard_health`, `health_probe_command`, `parse_health_line`, `repo_dashboard_version`)
- **Budget:** `HEALTH_PROBE_SECONDS` = 150 s total, with a 5 s pause between attempts (`HEALTH_PROBE_INTERVAL`).
- **How it probes:** over SSH it runs `sudo docker exec <container> sh -c "<probe>"` (60 s SSH timeout per attempt). The probe uses `/venv/bin/python` (not curl) to GET `http://127.0.0.1:<port>/api/v1/health` with a 5 s timeout and print the JSON.
- The first output line that parses as a JSON object is used. Extra lines from sudo, SSH or docker are tolerated.
- **Success needs two things:** a JSON answer, and its `version` equal to the expected version. If no version is expected, any answer counts.
- **The expected version** in bind mode is the `VERSION = "..."` line in `dashboard/src/ccsync_dashboard/__init__.py`, read by regex. It is blank if the file cannot be read.
  - In image mode (`expected_after_restart`) it is whatever version the dashboard was serving before the restart, because this script ships no dashboard code there. If nothing was serving, any version that answers counts.
- **"Serving now" reading:** a single probe with a 5 s budget gives the version currently live, or blank. A dry run gives blank.
- **Failure details kept for the final message:**
  - "the container is serving vX, but this checkout deployed vY"
  - or the docker exec error text (first 200 characters, or "docker exec exited N")
  - or "/api/v1/health answered nothing a JSON object could be read from".
- **Dry run:** prints `[dry-run] would probe /api/v1/health inside <container> on port <port> (up to 150s) and require version == <version or '<the repo VERSION>'>`, and counts as success.

## Post-restart verdict and rollback (source: install_dashboard_app.py `verify_dashboard_after_restart`, `rollback_one_liner`, `roll_back_app_tree`, `_LAST_OLD_DIRS`)
- **Return code:** 0 when healthy, 1 when not. The comments say this is what stops `tools/ship.cmd` from publishing companions against a dashboard that is down.
- **On success** (real run) it prints `dashboard is SERVING: v<version> ok=<ok> (v<live> after N probe(s))`.
- **On failure** it prints to stderr:
  - `FAILED: the dashboard did not answer /api/v1/health from inside the container as v<expected> within 150s: <detail>`
  - a line saying nothing was deleted and the replaced tree is still on the NAS
  - `ROLL BACK with:` followed by the one-liner below
  - advice to read `docker logs <container>`.
- **The rollback one-liner** is `mv <root>/app <root>/app.failed-<YYYYmmddHHMMSS>; mv <previous> <root>/app; docker restart <container>`.
  - `<previous>` is the exact `app.old.<ts>` folder this run renamed aside, or the literal placeholder `<root>/app.old.<ts>` if none was recorded.
- **Flag `--rollback-on-unhealthy`** (default off; without it the script prints `  (--rollback-on-unhealthy does the above for you.)`) runs the rollback automatically, as root over SSH (300 s timeout).
  - It refuses when this run renamed no app tree aside, printing `CANNOT ROLL BACK AUTOMATICALLY: this run never renamed an app tree aside ...` and advising a hand restore from the newest `app.old.*`.
  - Before running it prints `--rollback-on-unhealthy: running` followed by the command.
  - If the rollback command fails it prints `THE ROLLBACK ITSELF FAILED (<err>) -- the app tree may now be at <root>/app.failed-*. Fix it by hand, and do not run another deploy until the dashboard answers.`
  - After a rollback it probes again with the full 150 s budget and any version:
    - healthy: `rolled back: the dashboard is answering again as vX (...). This deploy is UNDONE, not finished.`
    - not: `rolled back, but the dashboard still does not answer (...) -- the fault is not this deploy's app tree.`
  - The exit code is still 1 after a rollback.
- The failed tree is renamed `app.failed-<ts>`, never deleted.

## Image-mode boot verification (source: install_dashboard_app.py `verify_image_boot`, `parse_image_boot`)
- **Dry run:** prints what it would read and passes.
- **Real run:**
  - Waits 10 s, then reads `docker logs --tail 200 <container>` (120 s SSH timeout).
  - If the log cannot be read it prints a NOTE naming the two lines that matter (`run.sh: PYTHONPATH=...` and `select_code_root: ...`) and returns not-ok.
- **What it takes from the log:** the last `run.sh: PYTHONPATH=` line, every `select_code_root:` line (echoed), and every `run.sh:` line containing `FATAL` (echoed to stderr).
- **Which code is running**, from the first PYTHONPATH entry:
  - `/app/src`: prints `code root: the IMAGE (/app/src)`.
  - anything under `/data/code/`: prints that a code bundle applied over the air is running on top of the image.
  - anything else, or no line: not-ok, `FAILED: the container printed no run.sh: PYTHONPATH= line ...`. The likely cause given is a `/venv` mount shadowing the image's layer (`/venv/.image-baked` missing).
- **Runtime id:** runs `docker exec <container> cat /venv/.runtime-id` (60 s) and prints `runtime id (in the container): <id>`.
  - If it differs from the expected id, a NOTE explains that bundles built here would be refused as a runtime change and the Packages page will say 'runtime update' instead of offering a button.
  - If it is missing, not-ok: `FAILED: /venv/.runtime-id is not in the container. This image predates ... Rebuild or re-pull the image.`
- **Health:** runs the same health one-liner and prints `live dashboard: vX ok=Y`. No answer is not-ok: `FAILED: /api/v1/health did not answer from inside the container on port <port>.`
- **On any not-ok** it prints rollback advice: re-run `python server/install_dashboard_app.py --mode bind`.
- The result is advisory and never reverts anything. The caller decides the exit code.

## Image pull (source: install_dashboard_app.py `pull_container_image`)
- Runs `sudo docker pull <image>` over SSH with a 900 s timeout. It is identical on TrueNAS and Synology.
- **Dry run** passes this to the SSH layer as a dry run and reports success.
- **Failure is a NOTE, not a refusal.** It explains three cases:
  - an image already loaded with `docker load` is expected;
  - a 401 means the NAS has no route out (the GHCR package is public);
  - a 404 or manifest-unknown means the tag does not exist, so try `:edge`.
- **Success** prints `pulled image: <image>`.

## Container log cap (source: install_dashboard_app.py `LOG_ROTATION`; compose.yaml / compose.image.yaml)
- Every service in the stack (dashboard, the `bgutil` sidecar, and the template's syncthing and postgres) uses the json-file log driver with `max-size: 20m` and `max-file: 5`, so at most 100 MB per service.

## Session cookie and trusted proxies (source: install_dashboard_app.py `cookie_secure_for`, `trusted_proxies_for`)
- **`DASH_COOKIE_SECURE`:** `1` when the dashboard URL (the parameter, else `[net] dashboard_url`) starts with `https://` (any case). Otherwise `auto`, which honours X-Forwarded-Proto.
- **`DASH_TRUSTED_PROXIES`** (whose X-Forwarded-For the dashboard believes) is chosen in this order:
  - environment `DASH_TRUSTED_PROXIES` in the deploying shell;
  - else `[net] trusted_proxies`;
  - else `127.0.0.1,::1,<bridge>`, where `<bridge>` is `[net] docker_bridge_cidr` (default `172.16.0.0/12`), plus the tailnet bind address if one is set and not already listed.

## Own-footage b-roll shares (source: install_dashboard_app.py `broll_creators_shares_default`, `LEGACY_BROLL_CREATORS_SHARES`)
- **`BROLL_CREATORS_SHARES`** is the explicit value passed in (`main()` passes environment `BROLL_CREATORS_SHARES`). Otherwise `[broll] creators_shares`.
- If that key is blank: a manifest that has a `[broll]` table (any key at all) gives blank, meaning the whole archive browses as Downloads.
- A manifest with no `[broll]` table at all gives the legacy hard-coded value `mofa-disaster`. This is a transitional fallback.

## SFTP transport values for editors (source: install_dashboard_app.py `_derived_sftp`, `sftp_transport_refusal`; common.py)
- These come from `[net] sftp_chunk_size` and `[net] sftp_concurrency`.
- **On Synology:**
  - A blank chunk becomes `64Ki` and a blank or 0 concurrency becomes `16`.
  - Refusal text (checked before anything moves, in `main()`): `sftp_chunk_size '<x>' is not a size (use "64Ki")`, or `sftp_chunk_size '<x>' is above 64Ki: DSM's sshd silently truncates downloads over 514 MiB at that size`, and/or `sftp_concurrency N is above 16`.
- **On TrueNAS** the values pass through unchanged and no limits apply.

## Site identity block (what `GET /api/v1/site` serves) (source: install_dashboard_app.py `site_env`)
Every one of these is written into the container's environment. The tree root defaults to `DEFAULT_CC_ROOT`. The NAS host falls back to environment `TRUENAS_HOST`, then the default host.
- **Identity and branding:**
  - `DASH_SITE_ORG_NAME` = `[site] org_name`
  - `DASH_SITE_ORG_SHORT` = `[site] org_short`; blank stays blank, and the dashboard then uses `org_name`
  - `DASH_SITE_SUPPORT_CONTACT` = `[site] support_contact`; blank means the vendor's address
  - `DASH_SITE_PRODUCT_NAME` = `[site] product_name`
  - `DASH_SITE_BRAND_LOGO` = `[site] brand_logo`; blank means the product mark
- **Release feed:**
  - `DASH_RELEASE_FEED_URL` = the effective feed URL; blank turns the feed off
  - `DASH_RELEASE_FEED_POLICY` = `[releases] policy`; the comments say manual, stage or current
- **Tree:**
  - `DASH_SITE_TREE_NAME` = `[tree] tree_name`
  - `DASH_SITE_TEMPLATE_FOLDERS` = `[tree] template_folders`, comma-joined
  - `DASH_SITE_SHARED_ASSETS` = `[tree] shared_assets`, comma-joined
- **B-roll:**
  - `BROLL_DEFAULT_COLLECTION` = `[broll] default_collection`
  - `BROLL_DEFAULT_COLLECTION_LABEL` = `[broll] default_collection_label`
  - `BROLL_ARCHIVE_CREATORS_DIR` = `[broll] archive_creators_dir`
- **Paths:**
  - `DASH_SITE_CANONICAL_PREFIX` = `[site] canonical_prefix`, else `P:\`
  - `DASH_SITE_REMOTE_ROOT` = the tree root
  - `DASH_SITE_SMB_UNC` = `[tree] smb_unc`
- **SFTP:**
  - `DASH_SITE_SFTP_HOST` = `[net] sftp_host`, with no fallback to the NAS host
  - `DASH_SITE_SFTP_PORT` = `[net] sftp_port`, else `22`
  - `DASH_SITE_SFTP_HOSTKEY` = the NAS host key line the toolchain holds. Blank when `[security] skip_lane_host_key_pin` is true.
  - `DASH_SITE_SFTP_CHUNK_SIZE` and `DASH_SITE_SFTP_CONCURRENCY` = the derived pair above; a concurrency of 0 is written blank
  - `DASH_SITE_SFTP_SHELL_TYPE` = `none` when the editor shell is SFTP-only, else `[net] shell_type`
  - `DASH_SITE_RCLONE_REMOTE` = `[net] rclone_remote`, else `ccsync_sftp`
- **Projects:**
  - `DASH_PROJECT_ACL` = the project ACL mode
  - `DASH_NAS_PROJECTS_ROOT` = `<tree root>/Projects`
- **Other:**
  - `DASH_SITE_NAS_SYNCTHING_ID` = `[syncthing] device_id`
  - `DASH_SITE_DASHBOARD_URL` = the URL passed in, else `[net] dashboard_url`

## Certificate checking for NAS API calls (source: install_dashboard_app.py `configured_verify_ssl`, `container_verify_ssl`)
- **The configured value** is environment `TRUENAS_VERIFY_SSL`, else `[nas] verify_ssl`. If set, it passes through untouched; the studio's `0` turns checking off.
- **If unset**, the container gets a `sha256:` pin of the NAS certificate (port 443 on TrueNAS, the Synology port on Synology). This comes from `common.default_cert_pin`: the recorded pin, one recorded now with `--trust-host-key-on-first-use`, or a refusal raised there.
- **On a dry run** no connection is made. It shows `sha256:<recorded>`, or `sha256:<recorded-at-deploy>` if none is recorded.
- **When rendering a compose file to paste** (no NAS contact), only the configured raw value is used. That can be blank.

## Dashboard admins kept separate from the NAS admin (source: install_dashboard_app.py `resolve_dashboard_admins`)
- The explicit list (comma-separated, trimmed, blanks dropped) becomes `DASH_ADMIN_USERS`.
- **Empty list:** refused unless `[security] allow_nas_admin_as_dashboard_admin = true`, in which case the NAS admin account is used. The refusal reads `DASH_ADMIN_USERS is not set. Name the dashboard admin account(s) -- an editor account, NOT the NAS admin ('<user>') -- e.g. DASH_ADMIN_USERS=alex. ...`
- **List names the NAS admin** (case-insensitive): refused unless the same legacy flag is set. The refusal reads `DASH_ADMIN_USERS names the NAS admin account '<user>'. Use a separate account for the dashboard (COM-H5), or set [security] allow_nas_admin_as_dashboard_admin = true ...`

## TrueNAS API key is required (source: install_dashboard_app.py `require_nas_api_key`)
- **TrueNAS with no `TRUENAS_API_KEY`:** refused unless `[security] allow_nas_password_in_container = true`. The refusal reads `TRUENAS_API_KEY is not set. The dashboard container no longer holds the NAS admin password: mint a key and export it, then redeploy` and gives the command `python server/create_api_key.py --name ccsync-dashboard --username <service-account>`.
- Synology is never refused here. DSM has no API keys, so the container keeps the password.

## Shared report token switch (source: install_dashboard_app.py `shared_report_token_flag`)
- `DASH_SHARED_REPORT_TOKEN_ENABLED` is environment `DASH_SHARED_REPORT_TOKEN_ENABLED` if non-empty, else `1` when `[security] shared_report_token` is true, else `0`.
- The same rule feeds both the TrueNAS dictionary and the rendered file.

## The dashboard container definition (TrueNAS path posts this) (source: install_dashboard_app.py `compose_config`, `healthcheck_config`)
- **Tree root** is required: a missing value is refused, naming `[tree] pool_root/tree_name`.
- **Bind addresses** are required when none are passed in. A missing one is refused, naming `[net] bind_lan` / `--bind-lan` or `[net] bind_tailnet` / `--bind-tailnet`. The defaults come from the TrueNAS backend's LAN and tailnet bind constants.
- **Image:** bind mode uses `python:3.12.7-slim`. Image mode uses the given vendor image, else the site/default image.
- **User:** `uid:gid` (`[stack]` uid and gid, or the values passed in).
- **`group_add`** (extra groups for the container): present only when the vault or sorter pool helpers return a group list; the key is omitted when empty.
- **Command:** `/bin/sh /app/deploy/run.sh`.
- **Ports:** one `<addr>:<port>:<port>` entry per bind address (LAN and tailnet), never 0.0.0.0. The default port is 8480.
- **Restart policy:** `unless-stopped`.
- **Healthcheck:** a CMD-SHELL python one-liner that GETs `http://127.0.0.1:<port>/api/v1/health` (5 s timeout) and passes only if the JSON's `ok` is true. Interval 60s, timeout 10s, retries 3, start_period 120s.
- **Logging:** the 100 MB cap above.

### Environment variables written into the container (TrueNAS dictionary)
- **Image mode only:** `APP_UID` and `APP_GID`.
- **Syncthing:** `SYNCTHING_GUI_URL` (passed in) and `SYNCTHING_API_KEY` (secret).
- **Tokens and admins:**
  - `DASH_REPORT_TOKEN` (secret)
  - `DASH_SHARED_REPORT_TOKEN_ENABLED` (rule above)
  - `DASH_SESSION_SECRET` (secret)
  - `DASH_ADMIN_USERS` = the admin list, falling back to the NAS user if blank
- **Network and cookies:**
  - `DASH_SMB_HOST` = `[net] smb_host`, else the NAS host (used for editor logins)
  - `DASH_COOKIE_SECURE` (rule above)
  - `DASH_TRUSTED_PROXIES` (computed with the tailnet bind)
- **Fixed paths:**
  - `DASH_DB_PATH=/data/dashboard.db`
  - `DASH_CRASH_DIR=/data/crashes`
  - `DASH_PORT`
  - `DASH_PROJECTS_DIR=/projects`
- **B-roll:**
  - `DASH_BROLL_ENABLED` (default `1`)
  - `BROLL_DATA_ROOT=/broll-data`
  - `BROLL_SHARES=broll:Main b-roll archive`
  - `BROLL_CREATORS_SHARES` (rule above)
  - `BROLL_INGEST_TOKEN` (secret)
- **Music** (no on/off variable; shipping the code is the switch):
  - `MUSIC_DATA_ROOT=/music-data`
  - `MUSIC_SHARE_ROOT=/music-share`
  - `MUSIC_PROXIES_DIR=/music-proxies`
  - `MUSIC_TEXT_ENCODER_DIR=/music-encoder`
- **YouTube downloader:**
  - `YTDL_DATA_ROOT=/ytdl-data`
  - `YTDL_PROJECTS_ROOT=/projects`
  - `YTDL_DASH_DB=/data/dashboard.db`
  - `ANTHROPIC_API_KEY` (the customer's, blank unless supplied)
  - `YTDL_CACHE_DIR=/ytdl-data/cache`
  - `YTDL_LOCAL_DOWNLOAD=1`, always on (requester-first downloads)
- **Feature flags:**
  - `DASH_SITE_YOUTUBE_DOWNLOAD` (default `0`)
  - `DASH_SITE_YOUTUBE_UNBLOCK`: `1` only if both unblock and download are `1`
  - `DASH_SITE_AI_CLI_PROVIDERS` (default `0`)
  - `DASH_STUDIO_CLI_PROVIDERS` (default `0`)
  - `DASH_SITE_AUTO_UPDATE` (default `0`)
- **Unblock only** (DORMANT in the vendor build):
  - `YTDL_POT_BASE_URL=http://bgutil:4416`
  - `YTDL_COOKIES_FILE=/ytdl-data/cookies.txt`
- **Releases:**
  - `DASH_RELEASE_PUBKEYS` (effective keys)
  - `DASH_VENDOR_CUSTOMER`: `1` when the vendor switch is on, else blank
- **NAS credentials:**
  - `TRUENAS_HOST`, `TRUENAS_USER`, `TRUENAS_PW`
  - `TRUENAS_API_KEY` and `DASH_NAS_API_KEY` (same value)
  - `TRUENAS_API_KEY_USER` and `DASH_NAS_API_KEY_USER`, both from environment `TRUENAS_API_KEY_USER`
  - `DASH_NAS_API_TRANSPORT` = environment `TRUENAS_API_TRANSPORT`, else `DASH_NAS_API_TRANSPORT`. Blank means auto; the comments say auto, jsonrpc or rest.
  - `DASH_NAS_KIND`
  - `DASH_NAS_HOST`, `DASH_NAS_USER`, `DASH_NAS_PW` (duplicates of the TRUENAS_* trio)
- **NAS SSH and accounts:**
  - `DASH_NAS_SSH_PORT` (passed in, default `22`)
  - `DASH_NAS_SSH_HOSTKEY` (passed in)
  - `DASH_NAS_SSH_KEY_PROBE` (default `1`; `0` stops the Users page opening an SSH session per render)
  - `DASH_NAS_HOMES_PARENT` = `[tree] homes_parent`, else `<dataset root>/homes`
  - `DASH_NAS_SERVICE_USER` = `[stack] owner` (default `broll`)
  - `TRUENAS_VERIFY_SSL` (rule above)
- **Merged from helpers outside my range:** Timeline Cards variables, plus the Cards editor variables when the editor is `1`; sorter variables; `DASH_JOBS_ROOTS`; the dataset names `DASH_TREE_DATASET` and `DASH_UPDATE_SNAPSHOT_DATASET` (from `site.toml`, overridden by non-blank names passed in from the NAS lookup); the snapshot variables (blank unless a snapshot source was passed); the site identity block above.

### Volumes (TrueNAS dictionary; image mode drops `/app`, `/venv`, `/broll-app`, `/music-app`, `/ytdl-app`)
- **Code mounts:**
  - `<host>/app:/app:ro`
  - `<host>/venv:/venv`
  - `<host>/broll-web:/broll-app:ro`
  - `<host>/music-web:/music-app:ro`
  - `<host>/ytdl-web:/ytdl-app:ro`
  - `<host>/cards-web:/cards-app:ro` (kept in image mode)
  - `<host>/sorter-web:/sorter-app:ro` (kept in image mode)
- **Data mounts:**
  - `<host>/data:/data`
  - `<tree>/Projects:/projects:rw`
  - `<tree>/Assets/B-roll Archive:/broll-data:rw`
  - `<host>/music-data:/music-data:rw`
  - `<host>/music-encoder:/music-encoder:ro`
  - `<host>/music-proxies:/music-proxies:ro`
  - `<tree>/Assets/Music:/music-share:rw`
  - `<host>/ytdl-data:/ytdl-data:rw`
  - `<host>/sorter-data:/sorter-data:rw`
- **Tools:** `<host>/ffmpeg:/opt/ffmpeg:ro`.
- **Per-site extras:** the Cards vault and media mounts, the sorter pool mount and the snapshot mount, each only when configured or verified (built by helpers outside my range).
- **Optional:**
  - `<host>/deno:/opt/deno:ro`, only with unblock on (DORMANT in the vendor build)
  - `<host>/node:/opt/node:ro`, only with the Cards editor on

### `bgutil` sidecar (DORMANT unless `[features] youtube_unblock` and download are both on)
- Service `bgutil`, image `brainicism/bgutil-ytdlp-pot-provider:1.3.1-deno`, `restart: unless-stopped`, log cap, no published ports.

## Compose template rendering, used by the Synology path and as the manual paste file (source: install_dashboard_app.py `compose_template_for`, `compose_bind_lines`, `compose_pg_bind_lines`, `compose_variables`, `render_compose_yaml`, `COMPOSE_ENV_ONLY_IN_DICT`)
- **Which template:** `dashboard/deploy/compose.image.yaml` in image mode, else `dashboard/deploy/compose.yaml`.
- **Placeholders** are written `{{NAME}}`, with names of capitals, digits and underscores. Compose's own `${...}` substitutions are left untouched.
- **An unknown placeholder is a hard refusal:** `<template> uses {{NAME}}, which compose_variables() does not provide -- add it there ...`
- **Bind lines:** each `- "${ENVNAME:-addr}:<port>:<port>"`, so the address can be overridden by `DASH_BIND_LAN` / `DASH_BIND_TAILNET` at compose runtime.
- **Postgres bind lines:** `- "${ENVNAME:-addr}:${DASH_PG_PORT:-5432}:5432"` on the same two interfaces. `DASH_PG_PORT` defaults to 5432.
- **Roots:** the host root is required (`[apps] root` / `--host-root`), as is the tree root.
  - The NAS host falls back to environment `TRUENAS_HOST`, then the default. The NAS user falls back to environment `TRUENAS_USER`, then the default.
  - Binds default to the backend's `dash_binds(port)`.
- **Variables that differ from the dictionary:**
  - `NAS_SSH_PORT` = `[net] sftp_port`, else 22
  - `NAS_SSH_HOSTKEY` = the toolchain's recorded host key line, else `[nas] ssh_hostkey`
  - `NAS_SSH_KEY_PROBE` = `[nas] ssh_key_probe`, else `1`
  - `DASH_BROLL_ENABLED` = the parameter, else `1`; deliberately not from the shell
  - `NAS_ADMIN_USERS` = the parameter, else the NAS user; deliberately not from the shell
  - `CCSYNC_IMAGE` = the given image, else the site/default image
  - `NAS_HOMES_PARENT` = the parameter, else the default
  - `SYNCTHING_URL` = the parameter, else `[syncthing] gui_url`
  - Timeline Cards and sorter "enabled" come from `site.toml` intent (`[timeline_cards] enabled`, `[footage_sorter] enabled`), not from whether a checkout exists. The Cards token is excluded. `DASH_SORTER_SETTINGS` is pre-escaped for a single-quoted YAML scalar.
  - The site block is the same `site_env` output with the leading `DASH_` removed.
- **The template carries `REPLACE_ME` for:** SYNCTHING_API_KEY, DASH_REPORT_TOKEN, DASH_SESSION_SECRET, BROLL_INGEST_TOKEN, ANTHROPIC_API_KEY, DASH_CARDS_TOKEN, TRUENAS_PW and DASH_NAS_PW.
  - The Synology deploy turns these into `${KEY}` references into a 0600 `.env` file (that conversion function is outside my range).
- **The template references these from compose's own environment:**
  - `TRUENAS_API_KEY` and `DASH_NAS_API_KEY` as `${TRUENAS_API_KEY:-}`
  - the API-key-user pair as `${TRUENAS_API_KEY_USER:-}`
  - `DASH_NAS_API_TRANSPORT` as `${TRUENAS_API_TRANSPORT:-}`
- **The template hard-codes:** `DASH_SITE_YOUTUBE_DOWNLOAD "0"`, `DASH_SITE_YOUTUBE_UNBLOCK "0"`, `DASH_SITE_AI_CLI_PROVIDERS "0"`, `DASH_STUDIO_CLI_PROVIDERS "0"`, `DASH_SITE_AUTO_UPDATE "0"` and `YTDL_LOCAL_DOWNLOAD "1"`. These are not filled from `site.toml`.
- **The template has no:** `group_add`, Cards vault/media mounts, sorter pool mount, snapshot mount, deno mount, node mount, `bgutil` service or Cards editor variables.
- **The list of dictionary keys allowed to be missing from the templates is empty.**

## Optional services inside the compose templates (source: compose.yaml, compose.image.yaml)
- **`syncthing`** (profile `bundled-syncthing`; inert unless started with `--profile bundled-syncthing`):
  - image `syncthing/syncthing:1.30.0`, running as the app uid:gid
  - `STGUIAPIKEY` is required from `SYNCTHING_API_KEY`; compose errors with "set SYNCTHING_API_KEY" if it is missing
  - `STGUIADDRESS=0.0.0.0:8384`
  - volumes `<tree>:/data` and `<host>/syncthing-config:/var/syncthing/config`
  - ports `127.0.0.1:8384:8384`, `22000/tcp`, `22000/udp`, `21027/udp`
  - `unless-stopped`, log cap
- **`postgres`** (profile `project-server`; the Resolve project server):
  - image `postgres:13`, `POSTGRES_USER=postgres`, `POSTGRES_PASSWORD=${PG_PASSWORD:-}`
  - volume `<host>/postgres:/var/lib/postgresql/data`, ports on the LAN and tailnet only
  - It refuses to start when the password is empty, `DaVinci` or `davinci`, printing `refusing to start: set PG_PASSWORD to a long random value, never the Resolve default (docs/TAILNET_POLICY.md)`.
  - On an existing database it first resets the postgres role password in single-user mode. If that fails it prints `refusing to start: could not set the project-server password on the existing database`.
  - `unless-stopped`, log cap
- **Bind template only:** the image is pinned `python:3.12.7-slim`.
- **Image template only:** `image: "${CCSYNC_IMAGE:-<rendered image>}"`, which can be overridden at compose runtime, and `APP_UID` / `APP_GID` in the environment.

## Secrets: masking and resolution (source: install_dashboard_app.py `SECRET_ENV_VARS`, `STACK_ENV_SECRETS`, `dry_run_mask`, `resolve_compose_secrets`)
- **Masked secrets:** SYNCTHING_API_KEY, DASH_REPORT_TOKEN, DASH_SESSION_SECRET, BROLL_INGEST_TOKEN, TRUENAS_PW, TRUENAS_API_KEY, ANTHROPIC_API_KEY, DASH_CARDS_TOKEN.
- **Secrets that go to the Synology `.env`:** the same list minus TRUENAS_API_KEY, plus DASH_NAS_PW (8 in total).
- **Dry run:** each secret is printed as `<NAME-not-shown-in-dry-run>` when set in the shell environment, or `<NAME-unset-dry-run>` when not. Values are never printed.
- **Real run:**
  - `SYNCTHING_API_KEY`, `DASH_REPORT_TOKEN` and `DASH_SESSION_SECRET` are required from the environment (refused if missing, by `require_env`).
  - `BROLL_INGEST_TOKEN` is the already-validated value passed in.
  - `TRUENAS_PW` is the NAS admin password (`TRUENAS_PW` or `SYNO_PW`, whichever the site uses).
  - Validation always runs against the real values, before masking.

## Where the add-on code and music data come from (source: install_dashboard_app.py `broll_web_source`, `music_web_source`, `music_data_source`)
- **B-roll code:** environment `BROLL_WEB_SRC`, else the repo's `broll/web`.
- **Music code:** environment `MUSIC_WEB_SRC`, else the repo's `music/web`.
- **Music data:** environment `MUSIC_DATA_SRC`, else `<music web source>/data`. It holds `music.db`, `text_encoder/` and `proxies/`.

## `--music-data`: which music artefacts are shipped (source: install_dashboard_app.py `parse_music_data_push`, `music_component_paths`, `music_components_present`, `music_components_to_push`, `music_data_sizes`, `human_bytes`)
- **The three components:**
  - `db`: `music.db` into `<host>/music-data/`
  - `encoder`: `text_encoder/` into `<host>/music-encoder`
  - `proxies`: `proxies/` into `<host>/music-proxies`
- **Values:** `auto`, `none` or blank force nothing. `all` forces all three. A comma-separated subset forces exactly those.
  - Unknown names are refused: `unknown --music-data component(s) X; expected auto, none, all, or a comma-separated subset of db, encoder, proxies`.
- **`none`** ships nothing. **An explicit list or `all`** ships exactly that every time, which is how a re-index is published. **`auto`** ships only components the NAS does not already have.
- **Presence probe:** one root SSH call (120 s). A component counts as present only if its path exists and is non-empty.
  - A failed probe counts everything as absent, so everything is re-pushed.
  - A dry run reports everything absent and shows the full first-run plan.
- **Local sizes** (file count and bytes) are measured per component. Folders excluded from shipping are skipped.
- **Byte display** uses 1024-based B, KB, MB, GB with one decimal (whole bytes for B).

## Installing `music.db` on the NAS (source: install_dashboard_app.py `install_music_db`, `build_db_swap_script`)
- **No local file:** `FAILED: no music.db at <path> -- nothing to install`.
- **Unsaved local writes:** if `music.db-wal` or `music.db-shm` beside the source is non-empty, it warns that the base rig has writes not yet in the .db and that only the .db is shipped. It suggests closing the indexer or running `PRAGMA wal_checkpoint(TRUNCATE)`. Not fatal.
- **Staging:** creates a staging folder on the NAS (default parent `/tmp`, slug `ccsync-musicdb-upload`). If that fails: `FAILED: no staging dir on the NAS -- the installed index is untouched`.
- **Upload:** uploads by SFTP. A transfer error gives `FAILED: the SFTP transfer of music.db did not finish (<type>: <msg>) -- the installed index is untouched (staging left at <dir> for inspection).`
- **Size check:** compares the staged byte count (`wc -c`). A mismatch gives `FAILED: the staged index does not match what was sent (N bytes on the NAS vs M locally) ...`. A match prints `staged index verified: N bytes`.
- **Swap**, run as root:
  1. Create the data folder.
  2. Copy the staged file to `<target>.new`.
  3. Set owner `<uid>:<private gid>` (default 3000:3000) and mode 660.
  4. Check the size again. On a mismatch print `candidate index incomplete: X bytes, expected Y -- the installed index is untouched` and exit 8.
  5. Run any extra verification.
  6. Rename the live db to `music.db.old.<YYYYmmddHHMMSS>` and move its `-wal` / `-shm` along with it.
  7. Rename `.new` into place.
  8. If that rename fails, restore the old db and its sidecars, print `swap failed, previous index restored` and exit 9.
  9. Remove the staging folder.
- **Owner and mode values** are restricted to letters, digits and `_.:-`. Anything else is refused: `refusing to build a swap script with owner=...`. A blank owner or mode skips the chown or chmod (the Synology share case, used by `publish_db.py`).
- **The old index is never deleted or pruned.**
- **Results:**
  - failure: `FAILED to install the music index into <target>: <err>` plus a line that the previous index is still in place
  - success: `installed music index: <target> (<size>; previous index kept at <old>)`
- **Dry run** prints `[dry-run] would SFTP music.db (<size>) from <path> to <staging> on the NAS`. The swap command goes to the SSH layer as a dry run.
- **The SSH timeout** scales with file size (from a helper outside my range).

## ffmpeg provisioning, start only (source: install_dashboard_app.py `build_ffmpeg_install_script`, lines 4387 to 4408 only)
- I read only the docstring and the first line. It says the step is idempotent, the download is checked against a pinned hash, the candidate is run with `-version` before being moved into place, and nothing is deleted. The body after line 4408 is outside my range, so none of this is confirmed.

## Looks redundant or overlapping
- The health one-liner exists three times: `health_probe_command`, `verify_image_boot`'s inline copy, and the healthcheck's (which checks `ok`). The container definition also exists three times: the Python dictionary and two YAML templates kept in step only by tests.
- The NAS credentials are written under two names each: `TRUENAS_HOST/USER/PW/API_KEY/API_KEY_USER` and `DASH_NAS_*`.
- After every restart, `verify_image_boot` and `verify_dashboard_after_restart` both probe `/api/v1/health`.
- There are two rollback paths with different advice: the app-folder swap one-liner, and "redeploy with `--mode bind`" for image mode.
- The legacy `mofa-disaster` fallback is a one-customer special case still carried in code.
- `DASH_SITE_SFTP_CONCURRENCY` calls the SFTP derivation twice.

## Claims the code does not back
- `STACK_ENV_SECRETS` comment: "DASH_NAS_PW is the sixth". The tuple holds 8 names.
- `compose.yaml` header: "fill in EVERY REPLACE_ME value" lists 5 names. The template has 8 `REPLACE_ME` keys (it also has ANTHROPIC_API_KEY, DASH_CARDS_TOKEN and DASH_NAS_PW).
- `compose_config` comment on `DASH_ADMIN_USERS`: "Falls back to the account this deploy authenticates as". That is true in the function, but `resolve_dashboard_admins` refuses the NAS admin unless the legacy flag is set. The fallback only happens if a caller passes blank.
- `probe_dashboard_health`: "Retries until budget seconds have passed". Each attempt may take up to 60 s for SSH, so the real wall time can go past 150 s.
- `verify_image_boot` rollback text: "the host code trees under <host-root> were never touched". This depends on `main()` not shipping code trees in image mode, which I did not check. The image template's header says the script "still creates all of them".
- The `compose.image.yaml` header says the two templates carry "the same environment keys". The image template adds `APP_UID` and `APP_GID`, which the bind template lacks.
- `SECRET_ENV_VARS` comment: DASH_NAS_API_KEY "is already masked by the time it gets there". `compose_config` writes whatever `truenas_api_key` it is given; whether `main()` passes the masked value on a dry run is outside my range.
- The `compose.yaml` comment says `DASH_PORT_BINDS` is "127.0.0.1 only on Synology". The bind list comes from the backend's `dash_binds`, outside my range.

## Could not determine
- Whether `main()` or `backends/synology.py` add the missing feature flags, mounts, `group_add`, `bgutil`, the snapshot mount and the Cards editor variables to the Synology compose file. Without that, Synology sites would always deploy with those features off or unmounted.
- What the helpers outside my range return: `cards_env`, `cards_editor_env`, `sorter_env`, `jobs_env`, `datasets_env`, `snapshot_env`, `cards_volumes`, `sorter_volumes`, `snapshot_volumes`, `dashboard_group_add`, `nas_ssh_hostkey_line`, `project_acl_mode`, `editor_shell_is_sftp_only`, `tree_ssh_timeout`, `make_staging_dir`, `secrets_as_env_refs`.
- Whether `truenas_identity_mismatch`'s answer is a refusal or a warning (decided in `main()`).
- Whether `default_cert_pin` refuses or fetches when no pin is recorded.
- The default LAN and tailnet bind addresses (the TrueNAS backend's constants).
- The `ffmpeg` install script body after line 4408.

Lines read: `server/install_dashboard_app.py` 2009 to 4408 in full (2009 to 2049 for the healthcheck and uid/gid defaults). Lines 7410 to 7483 were read only to settle how the Synology file is rendered. `dashboard/deploy/compose.yaml` 1 to 888 and `dashboard/deploy/compose.image.yaml` 1 to 532 in full. Spot lookups: constant definitions at lines 259 to 2006 by search, and `server/common.py` 160 to 229 plus five definition lines (sftp limits, owner, group, homes parent). `compose.appliance.yaml` was not read, because `compose_template_for()` never points to it.
