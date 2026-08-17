# Commercial readiness — what must change to sell CC Sync to other organisations

Audit date: 2026-08-17. Scope: all 580 tracked files plus full git history
(147 commits), via six parallel audits (org-specific hardcoding, secrets/PII,
security surface, licensing/ToS, platform portability, data safety); every
top-tier claim was re-verified against source before it went in here.
Nothing in this document has been acted on yet.

Companion doc: `SYNOLOGY_PORT_PLAN.md` (the platform half of item 12).

## Verdict

This is a well-engineered **single-tenant appliance built for one NAS, one
tailnet, one drive letter, one NLE and one company**. The engineering hygiene
is unusually good — pinned sidecars, fail-closed gates, stage-verify-swap
deploys, a real defect ledger, ~5,250 tests — but nothing has been done for a
*second* customer, and the legal layer is entirely absent. Four things are
stop-ship on their own: the Claude-subscription / CLI-redistribution path, the
YouTube circumvention stack, an LGPL library frozen into an unsigned
self-updating exe, and a loopback API any web page can drive.

**Pragmatic v1 shape:** sell it as a *Resolve Studio + TrueNAS SCALE* product
(state both as requirements), one dashboard container per customer, and do the
list below — roughly one quarter. NAS-agnostic and multi-tenant-in-one-instance
is a separate, architectural project.

| Measure | Value |
|---|---|
| Stop-ship items (legal / ToS / signing) | 4 |
| Security findings | 2 critical, 5 high, 10 medium, 14 low |
| Data-safety gaps | 2 high, 9 medium |
| `Creators_Club` / `P:\` hardcoded hits | 608 / 603 |
| Live secrets ever committed | 0 |
| LICENSE · CI · code signing | none of the three exist |

## The ranked list

Ordered by what must be true before money changes hands, then by blast radius.
Effort: *days / weeks / quarter / architectural*.

### 1. Replace the consumer Claude subscription with per-tenant API keys; stop redistributing the Claude Code binary — STOP-SHIP, weeks

The b-roll indexer defaults to `use_subscription: True` and actively strips
`ANTHROPIC_API_KEY` so the claude.ai OAuth login is used, then runs four
concurrent `claude -p` workers (`broll/indexer/broll_index/config.py:134`,
`claude_client.py:102-121`, `parallel_claude.py:20,138`). The ytdl feature
runs `claude` headless on the customer's NAS under a shared login
(`ytdl/web/DEPLOY.md:69-95`), and the installer pushes the 304 MB proprietary
CLI onto customer hardware (`server/install_dashboard_app.py:355-379`).
Seat-sharing, service use of a consumer plan, and redistribution of Anthropic
software — three ToS problems in one feature.

Fix: Anthropic SDK + customer-supplied key, per tenant, no subscription path;
delete the CLI push and purge `.cache/ytdl/claude`.

### 2. Put a legal wrapper around — or drop — the YouTube download stack — STOP-SHIP, weeks + counsel

Editors export a live Google session into `~/.ccsync/youtube-cookies.txt` from
a tray menu; the NAS path adds a PO-token provider and deno "n-challenge"
solver whose only purpose is defeating YouTube's bot check
(`ytdl_cookies.py:1-51`, `dashboard/deploy/requirements.txt:53-71`,
`sidecar_tools.py:16-25`). Downloads land straight in timelines. There is no
rights attestation, copyright notice or rate disclaimer anywhere. As a
vendor-shipped feature this is DMCA §1201 / EUCD Art. 6 exposure, not just
yt-dlp's.

Fix: customer-enabled and customer-configured (off by default), explicit
rights attestation, remove the circumvention components from the vendor
build, outside-counsel read before it is sold.

### 3. Resolve the licensing debt — STOP-SHIP, weeks

- `pystray` is **LGPLv3** (verified from installed metadata) and is frozen
  into the single-file companion (`companion/build.spec:33-40`);
  `tray.py:242-395` also copies its Win32 internals, which strengthens the
  derivative-work reading.
- The installer SFTP-pushes a GPLv3 static ffmpeg onto the customer's NAS
  (`install_dashboard_app.py:296-302,1232-1261`) — that is conveying, with no
  source offer. The editor-side ffmpeg (gyan essentials via GitHub mirror) is
  also GPL, though fetched by the end user's machine.
- The repo has **no** LICENSE, copyright headers, third-party NOTICE, EULA,
  privacy policy or telemetry disclosure — and the companion reports the open
  Resolve project name, the local media manifest and the media-pool bin tree
  every few seconds (`reporter.py:40-56`), which is employee monitoring under
  GDPR.

Fix: swap pystray for a thin ctypes/PyObjC tray (two-thirds already exists) or
ship it separably per LGPL §4; make the NAS fetch ffmpeg itself or use an LGPL
build; add LICENSE, NOTICE (generate with `pip-licenses`), installer EULA,
privacy + telemetry disclosure. Also: written licence grant for the vendored
`yt-credit-downloader` (`ytdl/web/ytdlweb/vendor/`); "for DaVinci Resolve®"
attribution and "requires Resolve Studio" everywhere; keep the Blackmagic
Cloud benchmark comparison internal.

### 4. Sign the binaries and authenticate the upgrade channel — STOP-SHIP + security, weeks

Windows exe is unsigned, macOS is ad-hoc signed and not notarized
(`build.spec:120,139-146`, `tools/release_macos.sh:472-492`) — so TCC/Full
Disk Access dies on every self-upgrade. The companion downloads a build over
plain HTTP and verifies a sha256 *that arrived in the same response*
(`upgrade.py:122-131,565-568`); publish is gated only by an admin session
posted in clear (`build_editor_package.ps1:645-652`). Anyone holding an admin
cookie, spoofing the dashboard host, or compromising the container can push an
executable to every editor. Downgrade is first-class ("different, not newer").

Fix: Authenticode + Developer ID/notarization; sign the release manifest with
an offline key baked into the companion (minisign/ed25519) and verify before
`os.replace`; TLS-only same-origin; monotonic min-version floor against
downgrade re-offers.

### 5. Lock down the companion loopback API on 127.0.0.1:8899 — CRITICAL security, days

`broll_server.py:564-573` sends `Access-Control-Allow-Origin: *` and
`Access-Control-Allow-Private-Network: true`; no Origin/Host/token check
exists (docs claim otherwise at `docs/YTDL_LOCAL_DOWNLOAD.md:331`). Any web
page the editor visits can insert clips into the open Resolve timeline,
trigger NAS fetches, spawn Explorer/`open`, and claim fleet ytdl jobs under the
editor's identity. On macOS `probe_darwin_mount` builds `f"/Volumes/{share}"`
with no validation (`:294`) — `share="../.."` reaches `/`, and the reveal path
will `open` a directory ending in `.app`. Tests pin the wildcard
(`companion/tests/test_broll_server.py:1120-1176`).

Fix: allow-list Origin to the configured dashboard origin, require
`Content-Type: application/json`, check Host, validate `share` as one safe
segment, realpath-contain `/insert`, never `open` a bundle, cap concurrent
fetch children. Update the tests.

### 6. TLS everywhere; scoped credentials instead of the NAS admin password — HIGH security, weeks

No HTTPS anywhere (`KNOWN_BUGS.md:642`): passwords, 7-day unrevocable session
cookies, the shared fleet token and identity tokens cross the LAN in clear;
`cookie_secure` is off on http. The root-equivalent `TRUENAS_PW` lives in the
container environment (`install_dashboard_app.py:555-566`) with
`TRUENAS_VERIFY_SSL=0`, and the base-rig scripts use paramiko `AutoAddPolicy`
plus `verify=False` (`server/common.py:545,614`). Any RCE in
dashboard/broll/music/ytdl — all reachable by every editor — escalates to NAS
root.

Fix: TLS terminator (Tailscale Serve or Caddy sidecar), `DASH_COOKIE_SECURE=1`,
server-side session revocation; scoped TrueNAS API key for user/group
management only; pinned host key + CA (`CCSYNC_SSH_HOSTKEY`,
`TRUENAS_VERIFY_SSL=<ca.pem>` already exist — make them mandatory).

### 7. Decide and enforce the tenancy model on the NAS and in the fleet API — HIGH security, weeks

Every editor gets `/usr/bin/bash` (`setup_editor_account.py:325`), the whole
tree is `2770 broll:editors` so any editor can delete any other editor's
project, and the Syncthing GUI/API is published on all interfaces with no
password set (`install_syncthing_app.py:183`). The ytdl fleet routes authorise
on the shared fleet token with self-asserted identity
(`ytdl/web/ytdlweb/routes_fleet.py:62-133`) — any editor can claim others'
jobs. Multi-org inside one instance does not exist: no tenant table, global
slugs shared with Syncthing folder IDs, fleet-wide auto-shared asset
libraries.

Fix: `nologin` + `ForceCommand internal-sftp`; per-project groups or NFSv4
ACLs; Syncthing GUI auth + loopback bind; verify `X-CCSync-Identity` on ytdl
routes. For orgs: **one container per customer** — retrofitting in-instance
tenancy is a schema + Syncthing-namespace rewrite.

### 8. Put a backup floor under the authoritative tree, and codify the DB publish — HIGH data safety, days

There are zero references to ZFS snapshots, replication or restore in code or
docs. Every recovery path is a rename-aside, `.ccsync-trash`, or Syncthing
versioning; a mistaken `chown -R`, deploy or fleet-side bug has nothing behind
it. The only in-repo recipe for publishing the b-roll index is a plain `copy`
over the live WAL-mode `broll.db` the container holds open read-write
(`broll/HANDOFF.md:172`) — the safe stage/verify/swap procedure lives only in
a memory note.

Fix: periodic TrueNAS snapshot task on the pool + app dataset, snapshot before
`chown -R`/deploy/`--recreate`; a `broll.db` swap script reusing
`build_db_swap_script` with `PRAGMA quick_check`; a written backup/restore
runbook.

### 9. Close the remaining data-loss edges — MEDIUM data safety, weeks

- Lane B is `rclone sync` with a per-pass cap (`--max-delete 100 / 20G`), not
  a stop — a wrong `remote_root` or empty NAS listing walks the local proxy
  set into trash 20 GB per pass, and trash is never pruned
  (`sync/rclone_lane.py:1277-1306`). Add a circuit-breaker + dashboard alarm.
- "Remove from this machine" `rmtree` has no "lanes caught up" gate —
  un-uploaded footage is permanently deleted on a human's say-so
  (`app.py:2838-2915`).
- Pause ≠ stop; no fleet-wide halt from the dashboard; lane C cannot be
  stopped from the tray (`app.py:1307-1322`).
- `ReplaceClip`/`LinkProxyMedia`, including two unprompted automatic paths,
  have no `SaveProject`/backup/undo (`app.py:1595`, `proxy_relink.py:362`).
- `project_path()` rejects `/` but not `..` (`server/common.py:264-269`) →
  `--year ..` can `chown -R` every editor home and lock the fleet out of
  lanes A/B. One-line fix.
- Proxy gen: no free-space check, growing-source detection is a single mtime
  sample; `fix_10bit_proxies.py` can transcode an original in place if the
  parent isn't `Proxy` (`:97-98`); `build_archive --apply` overwrites on size
  mismatch and undoes in-place fixes.
- Wizard unmaps `P:` without the "is it ours?" check the bootstrap has
  (`onboarding/steps.py:1431`); macOS uninstall deletes the Syncthing
  identity by default.

### 10. De-tenant: a site manifest, no compiled-in identity, and a fresh repo — HIGH universal, weeks

There is no site-level config endpoint; everything site-shaped is baked into
installers or per-machine `config.toml`. The production NAS's **Syncthing
device ID** is the *default* in both bootstraps (`windows_bootstrap.ps1:138`,
`macos_bootstrap.sh:1637`) — a second customer literally pairs with our NAS.
Tailnet/LAN IPs are code defaults in ten shipped files
(`companion/config.py:175`, `dashboard/settings.py:24,43`,
`onboarding/steps.py:104-106`, …); `tools/ship.ps1` has four hardcoded URLs
and no parameter; `dashboard/deploy/compose.yaml` is a tenant file, not a
template. Brand strings, the `com.creatorsclub.*` bundle IDs, "your Creators
Club drive" tray copy, and the b-roll `creators_club` collection slug have zero
indirection. Client business data (`broll/indexer/config.queue.yaml`,
`config.ff2.yaml`, `duplicates_report.md`, `broll/eval/queries_*.yaml`) and a
real editor's machine dossier (`docs/macos-onboarding-handoff.md:212-246`) are
in-tree; a contributor's real name and machine-derived email are in 8 commits'
metadata.

Fix: `GET /api/v1/site` (org, brand, tree name, canonical prefix, remote root,
rclone remote, NAS Syncthing ID, template folders, shared assets) consumed by
companion/wizard/installers; blank every IP/ID/user default and fail loudly;
generate compose from the manifest; delete the studio data files; neutralise
fixtures (`leso`/`ruskin`/`alex`/`SAMDISK`); start the product repo from a
squashed commit and keep this one as the private engineering archive (no
secret was ever committed, so the rewrite is for identity, not keys).

### 11. Make the tree shape and drive letter customer data, not code — MEDIUM universal, weeks

`Creators_Club` as the tree root name (608 hits), `P:` as the canonical prefix
(603 hits, 23 companion modules + installers, explicitly deferred per
CLAUDE.md), the documentary-specific template folders (`Interviewees`,
`Render in Place`…) triplicated in `server/common.py:94-103` /
`provision.py:30-37` / `setup_tree.py`, the video-extension list and stignore
lines that must stay byte-identical across three components, the forced
`creators_club_sftp` remote name (`onboarding/steps.py:1770`),
`W:\Creators_Club\Assets\Music` in the music web app, and
`C:\Users\alex\tools\…` as *dataclass defaults* in both indexers.

Fix: `canon.py` is already generic — the work is defaults, the Windows
installer's ~40 `P:` sites, and the music probe; template folders and
shared-asset registry become server-side data served by the manifest; delete
the personal-path defaults.

### 12. State the platform envelope honestly, then widen it deliberately — MEDIUM universal, quarter → architectural

The whole server layer (~5,000 lines) is a TrueNAS SCALE REST + root-SSH
client: app-catalog installs, custom-app compose POSTs, `/filesystem/setperm`
ZFS-ACL workarounds, uid 3000/gid 3001, a `/mnt/…/apps/ccsync-dashboard`
regex safety check, `docker exec tailscale`. Editor password auth is an SMB
session probe against the NAS (the only method TrueNAS 25.10 allows) — no
SSO/OIDC/LDAP; `DASH_AUTH_METHOD` is a seam with one implementation. Tailscale
is the security perimeter, not a transport option (b-roll standalone has *no
auth*). macOS is code-complete but its 731-line first-run script has never
been run and Mac editors are a whole fix pass behind because PyInstaller needs
a Mac; Linux does not exist. Resolve Studio coupling is deep by design — BPG
is driven by UI-Automation clicks on `Resolve.exe -pg`.

Fix (v1): declare TrueNAS SCALE + Resolve Studio + Tailscale-or-TLS as
requirements; ship a real Dockerfile so the container is self-contained; add
an OIDC auth backend; validate macOS on a Mac and add a Mac release runner.
v2: a `ServerBackend` protocol (TrueNAS / Synology / generic Linux — see
`SYNOLOGY_PORT_PLAN.md`); Linux client only if a customer asks.

### 13. Product-grade operations: CI, lockfiles, crash reporting, docs for strangers — MEDIUM ops, weeks

No CI of any kind runs the 5,256 tests; releases are hand-run PowerShell on
one Windows box. Every dependency is a floor (`>=`) — one exact pin in the
whole repo, no lockfile, no `--require-hashes`. rclone/Syncthing installer
downloads are "latest" with no checksum (unlike the pinned sidecars). No crash
reporting, metrics, or telemetry hooks; the only log rotation is the
companion's 5 MB file. ~8,200 lines of excellent docs, all written as a
runbook for one NAS (literal `ssh truenas_admin@192.168.0.102`), four of them
dated bug-hunt archives; no install guide, architecture overview or API
reference for a third party. Over 100 env/TOML knobs with no schema. English
only, no i18n, near-zero accessibility.

Fix: GitHub Actions running all suites (Windows + macOS runners solve the Mac
release gap too); `uv lock`/`pip-compile --generate-hashes` per component + a
licence gate; Sentry-class crash reporting with opt-in; a generic install
guide + architecture doc; a `site.toml` schema and validator.

### 14. Package the GPU indexers or scope them out of v1 — LOW universal, weeks

Both indexers are `pip install -e .` from source with hand-edited YAML. Music
needs an RTX-class GPU (9 min per full rebuild) and adding one track is a
documented lossy pull-drain-push; b-roll transcription shells out to a
faster-whisper environment at `C:\Users\alex\tools\whisper` that isn't in
this repo.

Fix: a GPU Docker image covering CUDA/whisper/torch; required-not-defaulted
`data_root`/`db.path`; a queue drain with no lost-write window — or ship
search-only from a vendor-built index in v1.

### 15. Security hardening sprint (medium tier) — weeks

- Standalone b-roll ingest is *open* when `BROLL_INGEST_TOKEN` is unset
  (`broll/web/app/routes_ingest.py:20-25`) — safe only under the dashboard's
  gate; delete the dev branch.
- `DASH_SESSION_SECRET`/`DASH_REPORT_TOKEN` strength unchecked (compose ships
  `REPLACE_ME`) while the ingest token gets a 24-char floor — reuse
  `check_ingest_token`. A weak session secret = forged admin cookie.
- Login throttle is per-username, in-process, unlocked dict, no per-IP budget
  (`auth.py:45-46,131-151`).
- One shared fleet token for every editor, written to `config.toml` and
  `identity.json` at default umask on Windows (`identity.py:98-119`); no
  per-editor tokens; non-upgrade requests follow redirects.
- CSRF rests on `SameSite=Lax` alone; htmx POST partials have no token.
- Editor laptops become SMB servers of the whole tree (`New-SmbShare
  CCSync_P`) with no firewall scoping; base-rig secrets via `setx`; elevated
  helper is a fixed-name script in `%TEMP%`.
- `YTDL_DEV_USER` and `DASH_REPORT_TOKEN_OPTIONAL` are one env var from full
  impersonation / unauthenticated writes — remove from shipped builds.

## Detail by area

### A. What is hardcoded to this deployment

| Token | Hits | Representative locations | Configurable today? |
|---|---|---|---|
| `Creators_Club` (tree root name) | 608 | `server/common.py:41`, `onboarding/steps.py:109-170`, both bootstraps, `build_archive.py:51`, `musicweb/config.py:29` | Per-machine `local_root`/`remote_root` yes; every default/example/doc no |
| `P:\` canonical prefix | 603 | `canon.py` (38), `paths.py` (25), `app.py` (20), `popup.py` (16), installer ~40 sites | `canonical_prefix` is a key; installers/music web hardwired |
| `/mnt/tank` · `TheCreatorsPool` | 153 · 85 | `server/common.py:40`, `truenas_client.py:28`, `drive_swap.py:16,477` (derives UNC structurally), compose ×17 mounts | Flags on server scripts only |
| NAS tailnet IP `100.71.216.3` | 75 | `companion/config.py:175,651` (baked into default TOML), `steps.py:104`, `windows_bootstrap.ps1:129`, `release*.sh/ps1` | Overridable at edges; compiled-in default phones home to this NAS |
| NAS LAN IP `192.168.0.102` | 56 | `settings.py:24,43`, `common.py:38`, `ship.ps1:161,194,329,404` (no parameter) | Env vars exist; defaults are ours |
| NAS Syncthing device ID | 2 | `windows_bootstrap.ps1:138`, `macos_bootstrap.sh:1637` as parameter **defaults** | Flag/env; the default is the bug |
| Brand strings + assets | 57+ | `topbar.html:9`, four `static/index.html`, `app.py:129`, `theme.py`, `assets/cc_mark_white.png`, tray copy ×8, `com.creatorsclub.*` plists | No |
| Template folders / structural names | — | `common.py:94-103` ≡ `provision.py:30-37`; `Proxy`, `Youtube`, `Assets/*` in ~15 modules | No; must stay identical across 3 components |
| Business rules | — | Lane A video up-only / lane B Proxy down-only (`rclone_lane.py:377-426`); b-roll `creators_club` collection slug; ytdl prompts with documentary + 中文 bias (`claude_cli.py:221-267`); CJK normalisation always on | Membership env-driven; labels/policies not |
| Dev-machine paths | ~12 | `broll_index/config.py:116`, `music_index/config.py:23-24`, `musicweb/routes_ingest.py:66`, `watchdog.ps1:31-32` | Delete |

Already generic and worth keeping: project depth is marker-based
(`.ccsync-project`), slugging, `canon.py`'s prefix abstraction, ~70 companion
TOML keys with validation, ~30 `DASH_*` env vars, and the bench harness. The
structural gap is a site manifest endpoint — `dashboard/api.py` has 20 routes
and none serves site config.

### B. Secrets, PII and repo hygiene

Clean — cryptographic secrets:
- No key, token, password, private key or `.env`/`cookies.txt`/`.db` was ever
  committed (full-history scan, both branches).
- Compose ships `REPLACE_ME` placeholders; test fixtures are labelled as such
  — confirm `9f3c…5061` in `dashboard/tests/test_broll_mount.py:37` was never
  the live ingest token (rotate if in doubt).
- Client-side handling is careful: `WNetAddConnection2W`/`CredWriteW` instead
  of argv, sudo password on stdin, redacted logs, cookies 0600.

Fix — identity and PII:
- Contributor's real name + machine-derived email in 8 commits' author fields.
- `leso` home paths in **production** source (`stills.py:14`,
  `resolve_prefs.py:29,344`) and ~20 tests; full machine dossier incl. tailnet
  IP and "SSH is open" in `docs/macos-onboarding-handoff.md`.
- `ruskin` + hostname `DESKTOP-LQQ41TC` across KNOWN_BUGS; `alex` as default
  admin in 8 files.
- Client catalogue: 25 named projects, episode titles, camera bodies, sizes in
  `config.queue.yaml`; ~450 real archive filenames in `duplicates_report.md`.

Fix — at-rest handling:
- Fleet token in `~/.ccsync/config.toml` and `identity.json`; macOS chmods
  600, Windows sets no ACL (`windows_bootstrap.ps1:1587-1600`).
- All five server secrets in the TrueNAS app compose env (plaintext,
  `docker inspect`-readable).
- Live Claude OAuth credential and Google session cookies stored on the NAS
  (700/600 — correct modes, wrong idea).
- Add `.env`, `*.pem`, `*.key`, `cookies.txt`, `identity.json`, `rclone.conf`
  to root `.gitignore` as defence in depth.

### C. Security surface — full ranking

| # | Sev | Finding | Where |
|---|---|---|---|
| C1 | crit | Loopback 8899: CORS `*`, no Origin/Host/token; macOS `share` traversal to `/`; `open` of arbitrary dir | `broll_server.py:270-294,365,492,564-588`, `music_server.py:136-144,304-313` |
| C2 | crit | Unsigned self-updating exe trusting sha256 from the same plaintext-HTTP reply; downgrade is first-class | `upgrade.py:122-131,494-568`, `macos_bootstrap.sh:1935-1991` |
| H1 | high | No TLS; clear-text passwords/cookies/tokens on LAN; 7-day unrevocable sessions; `X-Forwarded-Proto` trusted from anyone | `auth.py:43,246-262`, `compose.yaml:191-192` |
| H2 | high | Base-rig scripts: `AutoAddPolicy`, no known_hosts, `verify=False`, same password for SSH+sudo+API | `server/common.py:31,432-495,545,611-615` |
| H3 | high | NAS admin password in container env; TrueNAS TLS verify off; Syncthing API plain http | `install_dashboard_app.py:555-566`, `truenas_client.py:34-42` |
| H4 | high | Editors get bash; tree group-rw for all; Syncthing GUI published, no password; passphrase-less keys never removed | `setup_editor_account.py:325`, `setup_tree.py:167-180`, `install_syncthing_app.py:183` |
| H5 | high | ytdl fleet routes: shared token only, self-asserted identity; any editor claims/poisons any job | `ytdl/web/ytdlweb/routes_fleet.py:62-240`, `db.py:606-617` |
| M1–M10 | med | Secret strength; login throttle; shared fleet token at default umask; no lockfiles; unverified rclone/Syncthing installer downloads + `%TEMP%` elevation TOCTOU; laptop SMB share unscoped; `setx` secrets; on-demand fetch bypasses root guard; music ingest unbounded; CSRF on Lax only | see item 15 |
| L1–L14 | low | Unscoped fleet reads; error detail leaks; standalone broll ingest open; admin password min length 1; prompt injection into shared Claude credential; secrets on argv in docs; `project_path` `..`; symlink windows; onefile `_MEI` temp; uninstall leftovers; phished dashboard URL receives password + SFTP host | various |

Done well and worth keeping: versioned HMAC tokens with purpose separation and
`compare_digest`; SMB guest/null-session rejection; auth-before-body on
`/report` with size ceilings; fail-closed ingest gate at boot;
`resolve()`+`is_relative_to` containment and parametrised SQL throughout;
sidecars pinned by tag + sha256 with verify-before-inflate; yt-dlp verified
against upstream SHA2-256SUMS with host allow-list; all subprocesses
list-argv, no `shell=True`, no pickle/eval; container `/app` ro, venv 700,
`umask 077`, never `0.0.0.0`.

### D. Data safety — destructive operations

| Op | Where | Guards | Residual | Add |
|---|---|---|---|---|
| Lane B `rclone sync` NAS→local Proxy | `rclone_lane.py:1277-1306` | `--backup-dir` trash, `--max-delete 100/20G`, `--min-age`, fail-closed filter | M | Circuit-breaker on trash growth; prune policy; alarm |
| Lane A `copy --ignore-existing` | `:1063-1093` | Additive only, 0-byte guard | L | Surface "skipped, exists" (same-name re-export silently never uploads) |
| Lane C Syncthing deletes | `syncthing_admin.py:463-481`, NAS folders | `ignoreDelete` both sides, staggered versioning | L | Mac builds still lack the editor-side flag; rename ⇒ duplication undocumented; conflicts never cleaned |
| "Remove from this machine" `rmtree` | `app.py:2838-2915` | Confirm, base-rig refusal, containment, root-present | M | Gate on lane A/C pending = 0 |
| Fixer copy + `ReplaceClip`; auto relink; `config.dat` rewrite | `fixer.py:409-866`, `app.py:1595`, `resolve_prefs.py:266-515` | O_EXCL claim, tmp+replace, never touches source; refuses if Resolve running; `.ccsync-bak` | M | `SaveProject`/export before edits; re-check reservation at `:866`; size verify |
| Proxy gen / BPG / `fix_*` scripts | `proxy_gen.py:1575-1622`, `bpg.py`, `fix_10bit_proxies.py:97-116` | Structural `Proxy/` path, first-writer-wins, only own `.partial` removed; dry-run defaults | M | Free-space gate; two-sample stability; refuse self-source; tests for `fix_*` |
| `broll.db` publish · `build_archive --apply` · music prune | `HANDOFF.md:172`, `build_archive.py:484-529`, `musicweb/db.py:325` | None · tmp+replace · empty/20% refusal | H · M · M | Swap script with `quick_check`; hash compare; backup before prune |
| Ytdl writes into the tree; NAS `_sweep_stale` | `ytdl_executor.py:1521-1567`, `worker.py:672-696` | Server-composed paths, id-scoped cleanup | L | `--no-overwrites`; id-scope the sweep; base-rig double-write race |
| `setup_tree.py` `chown -R`/`chmod 2770`; deploy swap | `common.py:264-269`, `install_dashboard_app.py:1745-1947` | Marker refusals, `HOST_ROOT_RE`, count+bytes verify, rollback | M · L | Reject `..`; test "no rm/mv names a data path" |
| Backups / snapshots | — | **None referenced anywhere** | H | ZFS snapshot task; snapshot before privileged ops; restore runbook |

Cross-cutting: dry-run exists for server scripts, installers, consolidate and
indexer reports, but not for the fixer copy, Resolve edits, proxy gen, ytdl,
the wizard, or `sort`/`regen_sprites`. Only `companion.log` (5 MB rotating)
and `proxy_history.jsonl` record destructive ops. No fleet-wide pause/kill
switch. Trash (`.ccsync-trash`) is never pruned.

### E. Licensing, third parties, ToS

| Component | How obtained | Licence | Risk |
|---|---|---|---|
| Claude Code CLI (304 MB) + consumer subscription | Pushed to NAS by installer; `claude -p` ×4 | Proprietary | crit — redistribution + seat-sharing |
| yt-dlp + `bgutil-ytdlp-pot-provider` + deno EJS + cookies | Sidecar / docker / runtime fetch | Unlicense / unverified / MIT | high — ToS + anti-circumvention |
| pystray | Frozen into onefile exe; internals copied in `tray.py` | **LGPLv3** (verified) | high — replace or ship separably |
| ffmpeg (editor: gyan essentials via GitHub mirror; NAS: johnvansickle static, SFTP-pushed) | sha256-pinned | GPLv3 (both, by build name) | high — NAS copy is conveyed; no source offer |
| paramiko · libsndfile/libsoxr (via soundfile/librosa) · certifi/CTranslate2 | pip | LGPL-2.1 · LGPL-2.1 · MPL-2.0 | med — internal / base-rig only today; notice needed |
| rclone · Syncthing · Tailscale | winget/brew/zip ("latest", no checksum) | MIT · MPL-2.0 · BSD + paid SaaS | med — pin + notice; Tailscale = customer-supplied or partner terms |
| CLAP (ONNX text-tower export shipped) · MiniLM via fastembed · Whisper | HF at runtime / exported | Apache-2.0 · Apache-2.0 · MIT | low — NOTICE; undisclosed HF egress from customer container |
| DaVinci Resolve scripting · BPG UI-automation · `config.dat` edits | Not vendored (good); imported from user's install | BMD proprietary; Studio required | med — EULA read on automation; product name uses "Resolve" |
| PyInstaller · python3.dll · Tcl/Tk · htmx (banner stripped) | bundled | GPLv2+exception · PSF · BSD · 0BSD | low — notices only |
| Customer LUT/music/footage fan-out | Feature | Customer content | med — indemnity clause (per-seat LUT packs) |

Absent: LICENSE, copyright headers, NOTICE, EULA, privacy policy, ToS,
telemetry disclosure, export-control note, security contact. No AGPL/SSPL
anywhere (checked all five venvs). No customer media, DBs, weights or fonts in
git.

### F. Platform envelope today

Server: TrueNAS SCALE 25.10 REST + root SSH; app-catalog Syncthing;
custom-app compose; ZFS ACL workarounds; uid/gid literals. No Dockerfile for
the dashboard (pip-installs into a bind-mounted venv at boot); compose binds
to two literal IPs and 17 absolute mounts. Postgres Project Server assumed,
not automated. Single uvicorn worker is load-bearing; four SQLite DBs;
collector cadence scales as folders × devices.

Network & identity: Tailscale is the perimeter (645 mentions); IPs not
MagicDNS; ACLs out-of-band. Auth = SMB session probe on :445
(TrueNAS-specific); no SSO; four identity systems correlated by username
string; Resolve/Postgres users unmanaged. ~7 manual touchpoints per new editor.

Clients: Windows-first (ctypes Win32, registry Run key, logon task, loopback
SMB share, Tk dialogs, PyInstaller onefile). macOS: real platform branches
everywhere, 2,400-line bootstrap, but first-run unrun and builds lag; ad-hoc
signing kills TCC on upgrade. Linux: no sidecars, no package channel, bridge
returns None. Resolve Studio + external scripting set by hand; BPG via UI
Automation, Windows-only.

## A phased plan

- **Phase 0 — before any sale:** items 1–4 (API-key Claude path, YouTube
  legal wrapper or drop, pystray/ffmpeg posture + LICENSE/NOTICE/EULA/privacy/
  telemetry disclosure, code signing); item 8 (snapshots + backup runbook,
  codified DB publish); fresh product repo from a squashed commit; delete
  client data files; neutralise fixtures.
- **Phase 1 — security:** item 5 (loopback origin/share validation — days, do
  first); item 6 (TLS, secure cookies, revocable sessions, scoped TrueNAS key,
  pinned host key/CA); item 7 (SFTP-only shells, per-project ACLs, Syncthing
  GUI auth, ytdl identity verification); item 15 hardening sprint; lockfiles +
  `--require-hashes`; installer download checksums.
- **Phase 2 — de-tenant:** item 10 (`/api/v1/site` manifest; blank every
  identity default; compose from template; brand block + neutral assets;
  rename bundle IDs); item 11 (tree name, drive letter, template folders,
  shared assets, remote name as data); item 9 (lane B breaker, remove-project
  gate, fleet halt, Resolve edit backups, `..` fix, proxy-gen gates).
- **Phase 3 — platform:** item 12 (real Dockerfile; OIDC backend; validate
  macOS on a Mac; CI with Windows + macOS runners); item 13 (crash reporting,
  generic install/architecture docs, config schema); item 14 (GPU indexer
  image or search-only v1). v2 candidates: `ServerBackend` abstraction
  (`SYNOLOGY_PORT_PLAN.md`), in-instance multi-tenancy, Linux client.

## What is already product-grade

- Release discipline: one command with real gates (secrets present, clean
  tree, version parity across four files, server suite green), stage-verify-
  swap deploys, provenance manifest, sha-verified self-upgrade with rollback,
  first-class rollback via "different not newer".
- Destructive-op design: lane A never deletes; lane B always trashes;
  ignoreDelete both sides; fixer is copy-only with O_EXCL claims; proxy gen
  structurally cannot overwrite an original; the single `rmtree` is confirmed,
  contained and base-rig-refused.
- Supply chain on the client: sidecars and yt-dlp pinned and verified before
  the exec bit is set; no `shell=True`; sanitized child env; secrets never on
  argv.
- Test depth: ~5,250 tests including real-rclone filter tests,
  cross-component byte-identity pins, deploy resilience and safety suites.
- Documentation of reasoning: nearly every non-obvious decision cites a date
  or bug id; `KNOWN_BUGS.md` is a genuine ledger — raw material for a
  customer-facing security whitepaper once the identity is scrubbed.

## Not verified from the repo

- Live values: session-secret strength, cookie flags, NAS Syncthing GUI
  password/bind, sshd `ForceCommand`, whether ZFS snapshots exist out-of-band,
  laptop firewall state, packages in the deployed container venv, whether the
  deployed companion matches source.
- Licences stated from knowledge, not the repo: ffmpeg build variants (GPL),
  libsndfile/libsoxr, `bgutil-ytdlp-pot-provider`, CLAP weights — confirm
  before quoting.
- Browser behaviour for the loopback CSRF (Chrome Local Network Access prompt
  vs Firefox/Safari) — reasoned from code, not executed; the code offers no
  defence either way.
- Whether `9f3c…5061` in `dashboard/tests/test_broll_mount.py:37` was ever the
  live ingest token.
