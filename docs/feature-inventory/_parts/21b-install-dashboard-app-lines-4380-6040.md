# Dashboard deploy script, lines 4380 to 6040: tool provisioning, code-tree install, Synology host setup, restart and mode flag

I read every line of `E:\Projects\Editing\ccsync\server\install_dashboard_app.py` from 4380 to 6048, all of my range. To settle values I also read lines 250-330, 425-514 and 1855-1918 (constants), and 7064-7093 (only to see when the provisioning steps run). For TrueNAS vs Synology behaviour I read short excerpts of `server\backends\{base,truenas,synology}.py`, and I grepped `server\common.py` and `server\tests` for the remaining values.

## ffmpeg and ffprobe provisioning (source: install_dashboard_app.py `provision_ffmpeg`, `fetch_ffmpeg_tarball`, `build_ffmpeg_*_script`, `install_ffmpeg_over_lan`)

**When it runs**
- It runs only if the music app or the YouTube downloader (ytdl) app is being shipped, and `--no-ffmpeg` is not passed (main, line 7072).
- It is non-fatal throughout. Every failure prints a `NOTE:` and the deploy carries on. Without ffmpeg, /music's queued ingest answers 503.

**Install location**
- Binaries go into `<host-root>/ffmpeg/ffmpeg` and `<host-root>/ffmpeg/ffprobe`.
- They are owned root:root, mode 755, and the directory is chmod 755. The container is meant to mount this read-only at `/opt/ffmpeg`.

**Constants and environment variables**
- Default URL: `https://johnvansickle.com/ffmpeg/releases/ffmpeg-7.0.2-amd64-static.tar.xz`.
- Pinned sha256: `abda8d77ce8309141f83ab8edf0596834087c52467f6badf376a6a2a4c87cf67`.
- `MUSIC_FFMPEG_URL` overrides the URL (default: the pinned URL). If it is set to empty, the step is skipped, unless fetch mode is `local` and `MUSIC_FFMPEG_FILE` is set. The skip prints: `NOTE: MUSIC_FFMPEG_URL is empty -- skipping ffmpeg. /music's queued ingest will answer 503 until ffmpeg and ffprobe are on PATH in the container (mount <dir> at /opt/ffmpeg).`
- `MUSIC_FFMPEG_SHA256` overrides the hash (default: the pinned hash).
  - If the URL was overridden but the hash was not, checksumming is turned off and it prints: `NOTE: MUSIC_FFMPEG_URL was overridden without MUSIC_FFMPEG_SHA256 -- the download will NOT be checksummed.`
  - If the hash is set to empty, there is no check at all.
- `MUSIC_FFMPEG_FILE` (default unset) points at a local tarball. It is used only in `local` fetch mode. In `remote` mode it is ignored and the script prints: `NOTE: MUSIC_FFMPEG_FILE=<f> is ignored in 'remote' fetch mode -- the NAS downloads its own copy. Pass --push-ffmpeg-from-local to push that file instead.`
- `MUSIC_FFMPEG_CACHE` (default `<repo>/.cache/ffmpeg`) is the workstation cache folder.
  - Cache file name: the first 12 hex digits of the sha256 of the URL, a hyphen, then the URL's basename (fallback name `ffmpeg.tar.xz`).
- Fetch modes are `local` and `remote`. The default is `remote` (constants `FFMPEG_FETCH_MODES` and `DEFAULT_FFMPEG_FETCH`). The flags that choose the mode (`--ffmpeg-fetch`, `--push-ffmpeg-from-local`) are parsed in main.
- Timeouts:
  - NAS-side download step: 1800 s (`FFMPEG_REMOTE_INSTALL_TIMEOUT`).
  - Workstation download: 300 s (`FFMPEG_FETCH_TIMEOUT`).
  - Unpack over the LAN: 300 s.
  - "Already present" probe: 120 s.
  - Byte-count check of the staged file: 120 s.

**Order of events**
1. **Presence probe first.** It checks `[ -x ffmpeg ] && [ -x ffprobe ]` over SSH.
   - If both exist, it prints `ffmpeg already provisioned at <dir>` and stops. This happens before anything is downloaded.
   - A failed or unreadable probe counts as "absent".
   - In a dry run the probe is only echoed and always answers "absent".
2. **Remote mode.** The NAS runs, as root (`echo "$SUDO_PW" | sudo -S sh -c ...`):
   - `curl -fsSL --retry 3` into a `mktemp -d /tmp/ccsync-ffmpeg.XXXXXX` folder, which is removed on exit;
   - `sha256sum -c` if a hash is set;
   - `tar -xJf`;
   - a search for the first files named `ffmpeg` and `ffprobe`. If either is missing it fails with `the archive holds no ffmpeg/ffprobe`;
   - `install` to `ffmpeg.new` and `ffprobe.new`, then runs each with `-version`. If they do not run it fails with `the downloaded ffmpeg/ffprobe does not run on this host` and deletes the `.new` files;
   - `mv` into place;
   - prints `ffmpeg provisioned: <dir>`.
   - Failure prints `NOTE: ffmpeg was NOT provisioned (<err 200 chars>). Everything else deploys; ...`. It also explains that the NAS pulls johnvansickle at about 28 kB/s (about 25 min) against the 1800 s ceiling, and that `--push-ffmpeg-from-local` makes the operator the distributor of a GPLv3 binary.
   - Dry run prints `[dry-run] would have the NAS download <url> and provision static ffmpeg/ffprobe into <dir>`.
3. **Local mode.**
   - It always prints the GPL notice to stderr first, dry runs included: `NOTE: --push-ffmpeg-from-local conveys a GPLv3 binary (ffmpeg {version}) to the target host. Under GPLv3 s6 you must accompany it with the corresponding source, or a written offer valid for three years. Source: https://johnvansickle.com/ffmpeg/ (build scripts) and https://ffmpeg.org/download.html (upstream {version}). See docs/legal/THIRD_PARTY_NOTICES.md.`
   - The version is read from the tarball name (regex `ffmpeg-(\d[0-9A-Za-z.]*)`), otherwise it says `version unknown`.
   - Tarball source order:
     1. `MUSIC_FFMPEG_FILE`. Errors: `MUSIC_FFMPEG_FILE=<f> is not a file`, or `<path> does not match the pinned sha256 (got <digest>)`. Success prints `using the ffmpeg tarball at <p> (<size>)`.
     2. The cache, re-hashed on every use. A hit prints `using the cached ffmpeg tarball at ...`. A mismatch prints `NOTE: the cached tarball at <p> no longer matches the pinned sha256 -- re-downloading`.
     3. The network, into `<cache>.part`, in 1 MiB chunks. Prints `fetching <url>`. Any exception deletes the `.part`. A hash mismatch deletes it and errors `the download does not match the pinned sha256 (got <d>) -- nothing was sent to the NAS`. Success renames it into the cache and prints `fetched <size> to <path>`.
   - A fetch failure prints `NOTE: ffmpeg was NOT provisioned -- the tarball could not be fetched here (<err>)...` with advice to retry, set `MUSIC_FFMPEG_FILE`, or use `--ffmpeg-fetch remote`.
   - With no hash, the digest of the fetched file is computed and sent, which proves only that the transfer was intact.
   - The push:
     - A staging folder is made with `mktemp -d /tmp/ccsync-ffmpeg-upload.XXXXXX`. If that fails: `no staging dir could be created on the NAS`.
     - The tarball is SFTP'd there as `ffmpeg.tar.xz`. A transfer exception returns `the ffmpeg tarball transfer did not finish (... staging left at <dir>)`.
     - `wc -c` must equal the local size, otherwise `the staged tarball does not match what was sent (<n> bytes on the NAS vs <m> locally; staging left at ...)`. Success prints `pushed <size> to staging <dir>`.
     - The unpack script runs as root. It checks the sha before mkdir or mktemp: exit 7 with `the staged tarball does not match the digest that was sent -- the transfer was corrupted; nothing installed`. Then the same unpack, run-check and `mv` as remote mode. Staging is removed only on success.
     - A failure prints `NOTE: ffmpeg was NOT provisioned (<err>). Everything else deploys; ...`.
   - Dry run prints `[dry-run] would fetch <url> to <cache path> and push it to the NAS over the LAN` and `[dry-run] would SFTP the ffmpeg tarball to <staged> ... and unpack it into <dir>`.

**Overwrite and keep rules**
- An existing install is never re-provisioned. Both scripts exit 0 if both binaries are already executable. So a newer pinned version never replaces an old install, because the check is presence-only.

## ytdl helper binary: deno (source: `provision_ytdl_binaries`, `fetch_pinned_file`, `build_binary_install_script`, `install_binary_over_lan`, `YTDL_BINARIES`)

**When it runs**
- Only when ytdl is shipped AND `youtube_unblock == "1"` (site.toml `[features] youtube_unblock` or `--enable-youtube-unblock`, per a constant comment) AND `--no-ytdl-bins` is not passed. It is non-fatal.

**What it installs**
- One binary, `deno`: host folder `<host-root>/deno`, container mount `/opt/deno`.
- What breaks without it: `yt-dlp has no JS runtime for YouTube's challenges, so signed-in extraction returns no formats`.

**Environment variables**
- `YTDL_DENO_URL`: no default.
- `YTDL_DENO_SHA256`: no default.
- `YTDL_DENO_FILE`: a local copy.
- `YTDL_BINARY_CACHE`: default `<repo>/.cache/ytdl`, naming as for ffmpeg, with fallback name `download`.
- `YTDL_WEB_SRC` overrides the ytdl web folder (default `<repo>/ytdl/web`). Function `ytdl_web_source`; its use is in main.

**Behaviour**
- If neither URL nor file is set, it prints `NOTE: YTDL_DENO_URL is not set -- skipping deno. Everything else deploys; until a deno binary exists in <dir> (mounted /opt/deno), <consequence>.`
- If there is no hash, it prints `NOTE: YTDL_DENO_SHA256 is not set -- the deno download will NOT be checksummed.`
- Presence probe: `[ -x <dir>/deno ]`. If present: `deno already provisioned at <dir>`.
- Fetch order: the local file, then the cache, then the network.
  - Errors: `<p> is not a file`; `<p> does not match the supplied sha256`; `the download does not match the supplied sha256 -- nothing was sent to the NAS`.
  - Cache messages: `using the cached deno download at ...`, `NOTE: the cached deno download at ... no longer matches the supplied sha256 -- re-downloading`.
  - Download timeout: 300 s.
  - A fetch failure prints a NOTE with `Retry, or point YTDL_DENO_FILE at a file already on this machine.`
  - With no supplied hash, the fetched file's digest is sent instead.
- Staging is `/tmp/ccsync-deno-upload.XXXXXX`. The staged file keeps the URL's basename, because its extension decides how it is unpacked:
  - `.zip`: `unzip -oq`, or python3 `zipfile` when unzip is absent;
  - `.tar.gz` / `.tgz`: `tar -xzf`;
  - `.tar.xz` / `.txz`: `tar -xJf`;
  - anything else is treated as the bare binary.
- Install script, run as root:
  - exits 0 if the binary is already present;
  - checks the sha first (exit 7, `the staged deno download does not match the digest that was sent -- the transfer was corrupted; nothing installed`);
  - unpacks into `mktemp /tmp/ccsync-ytdlbin.XXXXXX`;
  - if nothing is found: `the deno download holds no deno executable`;
  - installs `deno.new` with mode 755 and runs `--version`; failure gives `the downloaded deno does not run on this host`;
  - `mv` into place, removes staging, prints `deno provisioned: <dir>`.
- Install timeout: 300 s. Failure prints a NOTE.

## Node for the new Timeline Cards editor (source: `provision_node`, `node_published_digest`, `parse_shasums`, `build_node_install_script`)

**When it runs**
- When `cards_editor == "1"` (site.toml turned on the new editor) and `--no-node` is not passed. It is non-fatal.
- Returns True when Node is provisioned, already present, or a dry run.
- The consequence named in every NOTE: `the new Timeline Cards editor at /cards/edit will say it has no Node runtime`.

**Pinned values**
- Version: Node `24.22.2`.
- Tarball: `node-v24.22.2-linux-x64.tar.xz`.
- URL: `https://nodejs.org/dist/v24.22.2/...`.
- sha256: `48cc0e21e048790e54c0cf5749c2725005313d652651c40b7a21feb9697aaf75`.
- Host folder: `<host-root>/node`. Mount: `/opt/node`.

**Checksum policy: two keys, both required**
1. **Published list first.** It fetches `.../SHASUMS256.txt` (60 s timeout, reads up to 2 MiB) and needs an exact filename match on a 64-hex line.
   - Unreachable: `NOTE: Node was NOT provisioned -- <SHASUMS url> could not be fetched (...). A download with no published checksum is never installed.`
   - No line for the tarball: `... lists no checksum for <tarball>`.
   - The list disagrees with the pin: `NOTE: Node was NOT provisioned -- nodejs.org now publishes <x> for <tarball>, not the pinned <pin>. Either the pin is stale or the download host is not what it was; nothing was fetched.`
2. **The pin.** It is enforced again at fetch time and on the NAS. Building the install script with no checksum raises `no checksum, no install: Node is never provisioned unverified`.

**Behaviour**
- The published list is fetched before the "already present" check, so every run makes this network call.
- Presence check: run `<dir>/bin/node --version` (120 s timeout, without sudo). It must print exactly `v24.22.2`, otherwise it is treated as absent. If present: `node v24.22.2 already provisioned at <dir>`.
- Local copy: `CARDS_NODE_FILE` (its checksum is still enforced). The cache is the ytdl binary cache (`YTDL_BINARY_CACHE`, default `.cache/ytdl`). A fetch failure prints a NOTE telling the operator to point `CARDS_NODE_FILE` at the tarball.
- Push: staging `/tmp/ccsync-node-upload.XXXXXX`, then the same size check as deno.
- Install script, run as root:
  - exits 0 if the existing `bin/node` already reports the pinned version (a different version is replaced);
  - sha check, exit 7 with `the staged node download does not match the pinned digest -- the transfer was corrupted; nothing installed`;
  - extracts only `*/bin/node` with `tar --wildcards` (GNU tar);
  - error if missing: `the node download holds no bin/node`;
  - the candidate must print exactly `v24.22.2`, otherwise `the downloaded node does not run on this host (or is not v24.22.2)`;
  - the previous binary is kept as `bin/node.prev` (one copy, overwritten each time);
  - chmod 755 on the folder and `bin`, removes staging, prints `node v24.22.2 provisioned: <dir>`.
- Dry run prints `[dry-run] would provision Node v24.22.2 ... require sha256 48cc0e21e048... AND the same line in <SHASUMS url>, push it over the LAN and install bin/node into <dir> (mounted read-only at /opt/node)`. It also echoes the presence probe. It never fetches the published list.

## Ingest token strength check (source: `weak_ingest_token`)

- The token passes only if it is non-empty, not a known placeholder, at least 24 characters long, and has at least 8 distinct characters.
- Placeholder values (checked case-insensitively): `replace_me`, `replaceme`, `replace-me`, `change_me`, `changeme`, `change-me`, `changethis`, `todo`, `tbd`, `secret`, `password`, `token`, `test`, `example`, `your-token-here`, `xxx`, `none`, `null`.
- Reasons it returns: `is not set`; `is the placeholder '<v>' (a value that is in the public repo)`; `is only N characters; at least 24 are required`; `has too little variety to be a random secret`.
- It mirrors the dashboard's boot-time check. The caller (main) decides what to do with the reason.

## Code-tree upload, verify, swap and prune (source: `install_tree`, `upload_tree`, `build_swap_script`, `build_prune_script`, `make_staging_dir`, `prune_orphaned_staging`, `tree_ssh_timeout`, `run_ssh_guarded`)

This is used for every code tree: app, broll-web, the music trees, ytdl-web, cards and sorter (per main), and app/docs.

**What is uploaded**
- Every file under the source folder, sorted.
- Skipped: any path containing a folder named `.venv`, `__pycache__` or `.pytest_cache`, and every `*.pyc`.
- The b-roll tree also skips `.git`, `.github`, `tests` and `node_modules` (constant `BROLL_EXCLUDE_DIRS`).
- Symlinked files are uploaded as their contents, because `is_file` follows links.

**Refusals and messages**
- Empty source: `FAILED: <source> contains no files to ship -- refusing to install an empty <target>`.
- Staging folder could not be made: `FAILED: no staging dir on the NAS -- <target> is untouched`.
- About the staging folder:
  - It is made with `mktemp -d <parent>/<slug>.XXXXXX`, mode 700, owned by the SSH user.
  - The answer must start with `<parent>/<slug>.`, otherwise it prints `FAILED to create staging dir: <err>`.
  - The default parent is `/tmp`. Main passes a code-staging parent for the code trees and docs; the big music artefacts stage under `<host-root>/staging`.
  - Slugs: `ccsync-dashboard-upload` (default), `ccsync-docs-upload`, and others set by main.
  - In a dry run the folder name is `<parent>/<slug>.dryrun`.

**Upload**
- SFTP, creating missing parent folders.
- On Synology the path is rewritten for DSM's chroot: the leading `/volumeN` is stripped. On TrueNAS the path is used as-is.
- The byte total is the size the SFTP server confirms per file.
- A transport failure prints `FAILED: the SFTP transfer of <src> to <staging> did not finish (...) -- nothing on the NAS has been moved (staging left at <staging> for inspection).` then `<target> is untouched -- it is only ever replaced by a rename, and no rename has run.`
- Success prints `uploaded N files to staging <dir>`. Dry run prints `[dry-run] would SFTP N files from <src> to <staging> on the NAS`.

**Staged-copy check**
- File count via `find | wc -l`, and total bytes via `find -printf '%s'` plus awk (metadata only).
- A mismatch prints `FAILED: staged tree does not match what was sent (<n> files/<b> bytes on the NAS vs <n>/<b> locally) -- <target> is untouched (staging left at <dir> for inspection)`.
- Success prints `staged tree verified: N files, B bytes`.
- An internal assertion prints `FAILED: internal manifest mismatch (x vs y)`.

**Timeout for tree-sized steps**
- 300 s + (bytes / 5 MiB) × 3. For example, 1.4 GB is about 1100 s.
- Any SSH transport exception becomes rc 255 with `the SSH channel dropped after <t>s (...)`.

**Swap, run as root under `set -e`**
1. `rm -rf <target>.new`, then mkdir it.
2. `cp -a staging/. new/`, `chown -R root:root`, `chmod -R u+rwX,go+rX,go-w`.
3. Re-verify count and bytes on the candidate. A mismatch exits 8: `candidate tree incomplete: $n files/$b bytes, expected N/B -- app left untouched`. The `.new` folder is left behind.
4. `mkdir -p <target>`. On a first install this creates an empty folder, which then becomes the first backup.
5. `mv <target> <target>.old.<YYYYmmddHHMMSS>`. The timestamp is in workstation local time, to the second.
6. `mv new target`. On failure the old folder is moved back, with exit 9: `swap failed, previous code restored`.
7. `rm -rf staging`, on success only.

- Swap failure prints `FAILED to install code into <target>: <err 500 chars>`, plus that the previous code is still in place and where staging and the candidate were left.
- Success prints `installed code: <target> (previous code kept at <old>)`. The exact backup folder is remembered so a later rollback hint can name it.

**Prune, after a successful swap only, non-fatal, run as root**
- It lists `<target>.old.*`, sorts them, and deletes all but the newest one.
- It skips any backup whose name appears in some process's `/proc/*/mountinfo`, printing `keeping <d> -- still bind-mounted by a running container`.
- It is safe with spaces in names (`IFS= read -r`).
- Net effect: exactly one previous copy is kept (the one just replaced), plus any still mounted.

**Orphaned staging sweep**
- Main calls it with the parents `/tmp` and `<root>/staging`. It runs without sudo and is non-fatal.
- For each parent that exists, it runs `find -maxdepth 1 -name 'ccsync-*-upload.*' -mmin +120` and deletes the matches.
- It prints `reclaimed N orphaned staging dir(s) from the NAS (left by an earlier FAILED run): <first 4> ...`.
- Failed runs leave their staging folders behind on purpose, and this is the only thing that removes them, after 2 hours.

## Shipping the documents (source: `ship_dashboard_docs`, `_stage_docs_tree`)

- Target: `<host-root>/app/docs`, installed through install_tree with the slug `ccsync-docs-upload`. It is re-shipped on every deploy.
- The workstation assembles the docs in a temporary folder named `ccsync-docs-*`, which is always deleted afterwards.
- **Required set:** `docs/HOW_IT_WORKS.md`, `docs/EDITOR_SETUP.md`, and the `docs/legal/` tree.
  - If `legal/` is missing, nothing is shipped (returns False): `NOTE: not shipping legal -- absent from <docs>. The first-run wizard will say no licence agreement is included in this build.`
  - If a required `.md` is missing, everything else is still shipped: `NOTE: <names> is absent from <docs> and will not be shipped; /help will say that guide is not installed. Everything else, including the licence agreement, is being shipped.`
- **Extra documents:**
  - Files and trees listed in the dashboard's `published_docs` module (`PUBLISHED_DOCS`, `PUBLISHED_TREES`) are added.
  - If that module cannot be loaded, only the required set is shipped.
  - Only `.md` files are copied, plus licence `.txt` files that the module's `is_licence_text` accepts.
  - Symlinks and non-files are skipped.
- **Repo-root documents:** none. The list is empty (`SHIPPED_ROOT_DOCS = ()`), so no `_root/` folder is made.
- **Any failure** (an exception while staging, or install_tree failing):
  - An exception while staging first prints `NOTE: the documents could not be staged (<exc>).`
  - Then: `NOTE: the licence agreement and the help guide were NOT installed. The dashboard is up either way; /setup will say no licence agreement is included in this build.` and the function returns False. It never raises.

## Synology host folders and tree folders (source: `SYNOLOGY_HOST_DIRS`, `build_synology_host_dirs`, `build_synology_tree_dirs`, `secrets_as_env_refs`)

**Host folders made under `<root>`**
- Code folders, root:root, mode 755: `app`, `broll-web`, `music-web`, `music-encoder`, `music-proxies`, `ffmpeg`, `ytdl-web`, `deno`, `cards-web`, `sorter-web`.
- Private folders, owned by the service uid, mode 700, not recursive: `venv`, `data`, `music-data`, `ytdl-data`, `sorter-data`, `syncthing-config`. The contents (the databases) are never touched.
- Staging folder: `<root>/staging`, owned by the SSH user, mode 700.
- `<root>` itself is root:root 755.
- No `node` folder is in this list. The Node install script makes it.

**Inside the tree share** (the b-roll archive and the music library)
- Only `mkdir -p`. Never chown or chmod, so the share's inherited `editors` permission stays intact.

**TrueNAS difference**
- The equivalent TrueNAS chain lives in main (group 3000 and 3001, mode 2770). The comment says it is deliberately not reused here.
- `HOST_DIRS_TIMEOUT_S = 900` is the ceiling for step 1's recursive ownership pass.

**Secrets in the Synology compose file**
- Each `NAME: "REPLACE_ME"` line becomes `NAME: "${NAME:?set NAME in .env}"`, because the compose file is 0644 and the secrets live in a 0600 `.env`.
- Exactly one match per name is required, otherwise the deploy is refused with `expected exactly one `NAME: "REPLACE_ME"` line in the rendered compose file, found N. dashboard/deploy/compose.yaml and this script have drifted -- refusing to deploy a stack whose secrets may be the literal REPLACE_ME.`

## Platform selection, container restart, `--mode` and app-installed check (source: `backend`, `restart_dashboard_container`, `fail_after_app_swap`, `mode_flag_needs_recreate`, `apply_mode_flag`, `app_installed`)

**Platform choice**
- `--nas-kind`, else environment variable `CCSYNC_NAS_KIND`, else site.toml, else `truenas` (common.py:2100). Built once per run.

**Restart**
- TrueNAS: `sudo docker restart <dashboard container>`, 120 s timeout.
- Synology: compose `restart dashboard` as root, 300 s timeout.
- A dry run counts as success.

**Restart after a later step fails** (fail_after_app_swap: once the app code has been swapped, a later failure restarts the container before returning exit 1)
- Success prints `restarted the container onto the freshly installed code before failing -- it was still serving the previous code directory, which the next deploy would prune (OPS-2).`
- Failure prints `NOTE: could not restart the container after the app swap (<err>) -- harmless if the app is not installed yet; otherwise restart 'ccsync-dashboard' from the TrueNAS UI before the next deploy, ...`. This message names the TrueNAS UI on Synology too.

**`--mode` and `--recreate`**
- Nothing happens if `--mode` is absent or `--recreate` is already set.
- Otherwise it reads the running container's image via `docker inspect .Config.Image` (60 s timeout). It does not read it on a dry run.
  - Image unreadable: it implies `--recreate`, with reason `the running app's image could not be read`.
  - Same image: it does not recreate, and prints `--mode <m>: NOT re-creating the app (the app already runs <img>, so nothing compose-level would change). This is a routine redeploy: the code and data steps run and the container is restarted. Pass --recreate as well to force a re-create.`
  - Different image: it prints `--mode <m>: implying --recreate (the app runs <live> and this run gives it <wanted>; the mode and the image are baked in at create time, and a restart would keep the old ones). Nothing under <host-root> is deleted either way.` A dry run adds a sentence saying a real run asks the container first.
- A dry run always reports a re-create.

**Is the app installed?**
- TrueNAS: GET `/app`, filtered on the workstation side. An HTTP failure prints `FAILED to query installed apps: HTTP <code> <text>` and answers "unknown".
- Synology: `docker compose ls --format json --all`, looking for project `ccsync`. Failures print `FAILED to list compose projects on the NAS: ...` or `FAILED: `docker compose ls --format json` was not JSON: ...` and answer "unknown".
- A dry run answers "not installed".

## Looks redundant or overlapping

- The tool download path is written twice. `fetch_ffmpeg_tarball` and `fetch_pinned_file` are near-identical (file, then cache, then network, with a `.part` file). `build_ffmpeg_install_script`, `build_ffmpeg_unpack_script`, `build_binary_install_script` and `_NODE_INSTALL_TEMPLATE` are four versions of one "verify, unpack, run-check, mv" install script. `install_ffmpeg_over_lan` and `install_binary_over_lan` are the same push.
- ffmpeg has two fetch modes (NAS download vs workstation push), each with its own messages, cache and GPL notice.
- Presence probes are duplicated: `ffmpeg_present` and `binary_present` on the workstation side, and the remote scripts re-check the same thing.
- File count and byte total are checked twice per tree: once on staging, once on the `.new` candidate.
- Node uses the ytdl binary cache folder (`.cache/ytdl`, `YTDL_BINARY_CACHE`).

## Claims the code does not back

- `ship_dashboard_docs` docstring: "plus four files that live one level ABOVE it". `SHIPPED_ROOT_DOCS` is empty, so no repo-root files are shipped.
- Constant comment, lines 306-311: "the bind-mode deploy refuses the same absence" of EDITOR_SETUP.md. The code ships everything else with a NOTE; only a missing `legal/` tree is refused.
- main comment, lines 7066-7068: ffmpeg is "by default fetched HERE and pushed over the LAN". The default fetch mode is `remote`, meaning the NAS downloads it.
- `count_and_size_cmd` docstring: "this script SSHes nowhere else" (only to TrueNAS with GNU find). The Synology path uses the same `find -printf` and the same `head -n -1` prune on DSM.
- `build_swap_script` docstring: "cp/chown/chmod fails -> app.new left for inspection". True, but the next run's first command `rm -rf <target>.new` deletes it silently.
- `build_ffmpeg_install_script` docstring: "Idempotent ... nothing is deleted". It is idempotent only by presence, so a changed pin never upgrades an installed ffmpeg. The same holds for deno.
- `fail_after_app_swap` message tells the operator to restart from "the TrueNAS UI" on Synology too.

## Could not determine

- Whether the ffmpeg, deno and Node LAN pushes work on Synology. They stage under `/tmp` and SFTP to the raw path without the DSM path rewrite that `upload_tree` uses. The backend comment says `/tmp` is not reachable over SFTP on DSM, so I expect these to fail there (each with a non-fatal NOTE), but I did not verify it.
- Whether DSM's `find` supports `-printf`, and whether its `head` accepts `-n -1`, so whether the staged-tree check and the prune work on Synology.
- Whether the Synology compose file mounts `<root>/node`, and whether its absence from `SYNOLOGY_HOST_DIRS` matters before Node is provisioned. The compose rendering is outside my range.
- How `run_ssh` supplies `$SUDO_PW` to the remote shell (common.py, not read).
- The exact flags `--ffmpeg-fetch`, `--push-ffmpeg-from-local`, `--no-ffmpeg`, `--no-ytdl-bins`, `--no-node` and `--enable-youtube-unblock`, and how `youtube_unblock` and `cards_editor` are read from site.toml. These are in main, which you are covering.
- What `published_docs_module()` loads, and from where (line 335, outside my range).
- Whether the ytdl web tree's exclusions are applied (the constant list is at about line 514; only its comment was in view).

## Line ranges read

- `E:\Projects\Editing\ccsync\server\install_dashboard_app.py` 4380-6048, every line, which covers all of the assigned 4380-6040.
- For constants only: 250-330, 425-514, 1855-1918.
- From main, to see when the provisioning steps run: 7064-7093.
- Excerpts of `server\backends\base.py`, `truenas.py` and `synology.py` (`app_installed`, `restart_stack`, `container_image`, `sftp_path`).
- Grep hits only in `server\common.py` (`CCSYNC_NAS_KIND`) and `server\tests`.
