# Commercial readiness — what must change to sell CC Sync to other organisations

> **Status as at 2026-09-04; not maintained: check `KNOWN_BUGS.md`.**
> This is the 2026-08-17 audit and the fix pass that followed it, left as
> written. It is a *record of a decision point*, not a live status board:
> the per-item paragraphs below were true on the evening of 2026-08-17 and
> several of the things they call unshipped shipped weeks ago. Where an item
> has a ledger id, the ledger is the maintained truth (SYS-19, 2026-09-04).

Audit date: 2026-08-17. Scope: all 580 tracked files plus full git history
(147 commits), via six parallel audits (org-specific hardcoding, secrets/PII,
security surface, licensing/ToS, platform portability, data safety); every
top-tier claim was re-verified against source before it went in here.
Nothing in this document had been acted on when it was written; see the status block below and the per-item status paragraphs.

Companion doc: `SYNOLOGY_PORT_PLAN.md` (the platform half of item 12).

**Status 2026-08-17 (evening) — every item below has been worked, in repo,
on branch `commercial-readiness`, by a 15-agent Opus fleet (one agent per
area, disjoint file territories, an integration agent afterwards, all suites
green at the end). The Synology port (item 12's platform half) landed first
on `main`. Each item now carries a "Status 2026-08-17" paragraph saying what
is done, what is only drafted, and what still needs an operator, a
certificate, counsel or a Mac. NOTHING is shipped: the fleet is still on
companion 0.7.11 / dashboard 0.4.1 / installer 1.0.29 (this branch bumps them to 0.8.0 / 0.5.0 / 1.0.30, unpublished), and the per-finding
ledger is `KNOWN_BUGS.md` CR-1..CR-21. The consolidated operator checklist is
at the end of this document ("What the operator does next").**

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

**Status 2026-08-17 — DONE in repo. Ship state: see `KNOWN_BUGS.md` CR-1 (indexer) and CR-2 (ytdl).** Both halves converted to the `anthropic` SDK with the customer's `ANTHROPIC_API_KEY`. Indexer: `broll_index/claude_client.py` (key from env or keyfile, never config.yaml — the loader refuses it), contact sheets as image blocks, thread-pool concurrency with a client-enforced in-flight cap, 429/5xx/overloaded retry then account-wide classification, `use_subscription` deleted; 29 fake-client tests; not yet run against a live key (`broll/docs/indexing-api.md`). Ytdl: `ytdlweb/claude_cli.py` on the SDK, prompt split so fetched titles are fenced data in the user turn; `claude-bin`/`claude-home`/`YTDL_CLAUDE_HOME` and the one-time `/login` deleted from the installer, both compose files and `run.sh`. Operator: export the key (indexer env; compose for the container, `--recreate`), set a spend limit, run one small share and read `usage.jsonl`; on the live NAS `rm -rf <host-root>/claude-home <host-root>/claude-bin` and REVOKE the OAuth credential.

**Status 2026-08-18 — CLI providers reintroduced, deliberately, as customer-installed adapters.** The product owner asked for a Settings page where an admin can enter API keys **and/or** sign in with Claude Code and Codex, with the ytdl service using the first available of `claude_code > anthropic_api > codex > openai_api > deepseek_api`. That is implemented (`dashboard/src/ccsync_dashboard/ai_providers.py`, `ytdl/web/ytdlweb/ai_backend.py`, Settings → AI providers) **without reopening any of the three ToS problems above**:

* **Redistribution — still fixed, and this is the vendor's half.** Nothing in this repo downloads, bundles, vendors, installs, updates or version-pins `claude` or `codex`. There is no `claude-bin`, no image layer, no installer step, no cached download. A CLI provider is an adapter for an executable found on the container's `PATH` (or at a path an admin typed) **because the customer put it there**.
* **Consumer-plan service use and seat sharing — the customer's decision, asked explicitly.** The whole CLI half is behind `site.toml [features] ai_cli_providers`, **default off in the vendor build**; while it is off the rows are hidden and *never probed* (no subprocess runs at all). The page states, above the switch: "using a personal Claude/ChatGPT subscription for a service may breach its terms — that is your decision". `docs/legal/YOUTUBE_FEATURE_NOTICE.md` carries the long form.
* **API keys remain the vendor default**, per tenant, rotatable and metered: `<data>/secrets/ai/*` 0600 (or the environment, which always wins), a masked read-back, a Test button, and nothing secret in `GET /api/v1/site`. A deployment that never visits the page behaves exactly as it did on 2026-08-17.
* We cannot and do not script an interactive OAuth: a logged-out CLI is reported as "not signed in" with the command the admin runs **on the host**.

Operator: nothing to do unless you want a non-Anthropic provider — set keys on Settings → AI providers, and leave `ai_cli_providers` off unless a customer has asked for it and understands the sentence above.

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

**Status 2026-08-17 — DONE in repo, counsel owed.** `site.toml [features] youtube_download` defaults OFF end to end (no mount, fleet routes 404, no companion surface, no tooling installed); a rights/ToS attestation is recorded per user (`ytdl.db.attestations`) and per machine with version + digest + timestamp and gates the browser, the claim and `capabilities()`; copyright + rate disclaimers stand on the page; `docs/legal/YOUTUBE_FEATURE_NOTICE.md` explains the customer's responsibilities. The PO-token sidecar, deno solver and cookie sign-in are a second opt-in (`youtube_unblock` / `--enable-youtube-unblock`); the default compose body carries none of them (pinned by `test_safety`). All text is a draft for counsel; a retention policy for the records is still open. This studio's git-ignored `site.toml` sets both flags on.

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

**Status 2026-08-17 — largely DONE in repo; counsel + one licence grant outstanding.** pystray is out of the companion entirely — `ccsync_companion/tray_native.py` (Win32 ctypes / AppKit PyObjC, original, from the API docs) replaces it, the win32 monkeypatches are deleted, `pyproject.toml`/`build.spec`/`requirements.lock`/licence allowlist agree, and `tools/check_licenses.py` fails if it returns; proved on Windows with `companion/tools/tray_smoke.py`, **macOS unverified**. The NAS fetches its own sha256-pinned ffmpeg by default (`--push-ffmpeg-from-local` prints the GPLv3 §6 notice). `LICENSE`, `docs/legal/{EULA,PRIVACY,TELEMETRY,THIRD_PARTY_NOTICES}.md` + `tools/gen_notices.py` landed as DRAFTS FOR COUNSEL; the wizard takes EULA acceptance and the companion gates its lanes on it. `docs/EDITOR_SETUP.md` carries the "for DaVinci Resolve®" / "requires Studio" / non-affiliation lines; the Blackmagic Cloud comparison is marked internal in `bench/`. **Still blocking a sale:** counsel review and the real legal entity name (placeholder "Cablewrap Creative" was inferred from the email domain), a written licence grant for the vendored `yt-credit-downloader` (`ytdl/web/ytdlweb/vendor/PROVENANCE.md`), and config switches to disable `resolve_project` / `local_manifest` / `media_tree` reporting independently of sync.

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

**Status 2026-08-17 — DONE (code), BLOCKED ON PURCHASE (certificates).** Offline Ed25519 release key (`tools/release_key.py`, private half at `%USERPROFILE%\.ccsync-release\release.key`, never in the repo; public half baked into `ccsync_companion/release_pubkey.py`, pure-Python verifier). `tools/sign_release.py` signs each package record at publish; the dashboard verifies against `DASH_RELEASE_PUBKEYS` and rejects unsigned publishes (422) / unconfigured key (503); the companion verifies before downloading, checks the signed sha256 after, refuses anything below its monotonic downgrade floor, and refuses plain HTTP off the tailnet. Migration is additive — 0.7.11 can take the first signed build. `signtool` / `codesign`+`notarytool`+`stapler` hooks are wired behind env vars, loud "UNSIGNED BUILD" advisory otherwise; `ship` refuses `-MakeCurrent` of an unsigned binary without `-AllowUnsignedBinary`. A key was generated on this rig (pubkey `GKNmk8MktRkGkrBv+ziF7O6ZNKCnjXfC9/TwDiYwKDY=`) — decide keep/rotate before the first customer ship and BACK IT UP OFFLINE. Remaining: buy an OV/EV Authenticode certificate + Apple Developer ID, set the env vars, set `DASH_RELEASE_PUBKEYS` on both live dashboards (+ `--recreate`), copy the key to the Mac.

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

**Status 2026-08-17 — DONE in repo. Ship state: see `KNOWN_BUGS.md` CR-7.** `loopback_guard.py` holds the rules; `broll_server.py` vets every request at the dispatch layer (Host, Origin, token, content type) before any handler. CORS is an exact allow-list built from `dashboard_url` + the cached site manifest in both schemes; a refused caller gets 403 with no `Access-Control-Allow-Origin` and a generic body. `share` is one safe segment (fixing the macOS `/Volumes` traversal), `probe_darwin_mount` realpath-contains, `/insert` shares the containment check, bundles are revealed rather than opened, fetches are capped at two and refuse when `root_guard` says the tree is absent. The tests that pinned the wildcard were rewritten and ~130 added; `docs/YTDL_LOCAL_DOWNLOAD.md:331` and `broll/SPEC.md` corrected; `docs/LOOPBACK_API.md` written. **Operator action before the ship:** confirm each companion's `dashboard_url` (or the site manifest's) equals the origin editors actually browse — a mismatch turns every Send-to-Resolve into a 403 (`loopback_extra_origins` is the per-machine escape hatch).

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

**Status 2026-08-17 — DONE in repo on both sides; TLS terminator = Tailscale Serve (decided, verified on the Synology); live-NAS steps owed.** Dashboard: server-side revocable sessions (`sessions.py`; logout, log-out-everywhere, admin revoke; 12h idle / 7d absolute), `X-Forwarded-Proto` believed only from `DASH_TRUSTED_PROXIES` (default loopback), `DASH_COOKIE_SECURE=1` forces `Secure` and refuses plaintext login — behind Serve set `1`, not `auto` (the request arrives from the docker bridge). Server: host-key pinning is the rule (`[nas] ssh_hostkey`, `--trust-host-key-on-first-use` records to `~/.ccsync/known_hosts`, a changed key refuses); `verify=False` became `TRUENAS_VERIFY_SSL` (CA path works from the container); `sudo` may have its own password; `server/create_api_key.py` mints a scoped TrueNAS API key and with `TRUENAS_API_KEY` the deploy keeps the admin password OUT of the container (DSM has no equivalent and keeps the password behind loopback). Open: verify the `api_key.create` body against the customer's TrueNAS version; export a CA for this fleet; pin this fleet's host key; set `DASH_COOKIE_SECURE=1` + `DASH_SITE_DASHBOARD_URL=https://…ts.net` on the Serve-published sites; the three mounted SPAs still sit on the CSRF-exempt list.

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

**Status 2026-08-17 — DONE in repo; migration of THIS fleet is an operator step.** New editors are nologin + `ForceCommand internal-sftp` with `PasswordAuthentication no` (`[stack] editor_shell`, default `sftp-only`; the manifest's `sftp_shell_type=none` follows automatically); `setup_editor_account.py --migrate-existing` (dry-run default) converts an existing fleet, `--revoke-key --lock` makes the passphrase-less keys revocable. ChrootDirectory evaluated and rejected (would re-root every absolute path the manifest publishes). `[stack] project_acl = "per-project"` adds `proj-<slug>` groups plus setgid+sticky containers (the sticky bit is what stops one editor deleting another's project); default stays `shared`. `server/secure_syncthing_gui.py` puts a generated login on the Syncthing GUI and `[syncthing] gui_bind` narrows its bind, without touching the API key. Ytdl fleet routes verify the signed `X-CCSync-Identity` (H5). Multi-org = one container per customer, stated in `docs/TENANCY.md`. Open: THIS fleet's `site.toml` pins `editor_shell = "shell"` until `--migrate-existing --apply` runs (flipping early breaks every editor's rclone checksums); DSM per-project is a grant plus an operator TODO; the dashboard provisioner does not yet imply group membership on a tick; `secure_syncthing_gui.py` has not been run on either NAS.

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

**Status 2026-08-17 — code complete, NOT YET APPLIED to either NAS.** `server/setup_snapshots.py` creates idempotent hourly (keep 24) + daily (keep 30) snapshot tasks on both the tree and the apps dataset — TrueNAS through `/pool/snapshottask`, Synology through the backend seam, which prints the exact DSM click path and exits non-zero where the Snapshot Replication package is missing. `snapshot_now`/`list_snapshots`/`ensure_snapshot_schedule` on both backends; `common.snapshot_before()` wired into `setup_tree.py`'s `chown -R` and the deploy/`--recreate` swap (best-effort unless `--require-snapshot`). The `broll.db` publish that lived only in a memory note is `server/publish_db.py --which broll|music` (checkpoint, stage, `quick_check` on the NAS, shrink refusal, atomic rename, `.prev-<ts>`, `--rollback`); `broll/HANDOFF.md` and `music/web/DEPLOY.md` point at it. Runbook `docs/BACKUP_RESTORE.md`; 35 new server tests. **Remaining: an operator runs `setup_snapshots.py --apply` on each NAS and confirms with `--list`; the `pool.snapshottask` payload is unverified against a live 25.10 middleware; offsite replication is deliberately out of scope.**

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

**Status 2026-08-17 — DONE in repo. Ship state: see `KNOWN_BUGS.md` CR-11 (lane B breaker), CR-12 (the Resolve undo journal) and CR-13 (proxy generation).** Sync: lane B circuit breaker (`sync/lane_guard.py`; pre-flight marker/empty/shrunken-remote probe, per-pass and cumulative delete caps, trips to `paused` with lanes A/C running, persisted, cleared only from the tray), `.ccsync-trash` retention (14 d / 50 GB, never while tripped — reversal of AUDIT_2 C-7), fail-closed "Remove from this machine" gate (lane A `--dry-run` + Syncthing completion; typed-name override, logged + reported), a real halt (lanes A/B + lane C folders paused via Syncthing REST, persisted; fleet-wide via `POST /api/v1/fleet/halt` + Users-page panel, delivered on the report reply's `commands.halt`), lane A "skipped, exists" counter; dashboard schema v16, `sync_guard` report section, row chips + fleet banners; `docs/SYNC_SAFETY.md`. Resolve/proxy: every `ReplaceClip`/`LinkProxyMedia` takes a `SaveProject` + `ExportProject` save point and writes an undo journal (`resolve_journal.py`, Tray → Advanced → Undo), unprompted paths rate-limited to one burst per project per 15 min, fixer re-checks its O_EXCL reservation and verifies size + source stability before relinking; proxy gen gained a free-space floor, two-sample growing-source detection and a refusal to encode from a proxy; `fix_10bit_proxies.py` refuses anything outside `Proxy/`; `build_archive --apply` compares hashes, protects recorded repairs and trashes what it replaces; the wizard applies the bootstrap's "is P: ours?" test; `fixer_dry_run` / `proxy_dry_run` (`sort`/`regen_sprites` already had `--dry-run` — the table's claim was wrong); `docs/RESOLVE_EDIT_SAFETY.md`. `project_path()`'s `..` was fixed by the Synology port. Owed: a live-Resolve check that `ExportProject` writes the `.drp`; the ship.

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

**Status 2026-08-17 — DONE in repo except the product-repo squash (a recipe, not run).** The manifest grew `org_short`, `product_name`, `features`, a read-only `video_extensions`, and `[tree] template_folders` / `shared_assets` overrides (defaults pinned cross-component); every user-visible "Creators Club" — dashboard topbar, four SPA headers, eight companion tray/popup sentences, module descriptions — is site data or the neutral product string, with a neutral default mark (`assets/ccsync_mark.png`) behind `$CCSYNC_BRAND_LOGO`. macOS bundle ids and launchd labels moved to `com.ccsync.*` with the legacy pair retired by both the wizard and `macos_bootstrap.sh`. The wizard takes the rclone remote name from the manifest and never renames an existing one; the b-roll own-footage slug is `BROLL_DEFAULT_COLLECTION` (default `owned`, legacy `creators_club` still routed); the music `W:\Creators_Club` probe is gone (`MUSIC_LIBRARY_ROOT`). Client data files moved to git-ignored `private/`; `docs/macos-onboarding-handoff.md` scrubbed; `alex` defaults neutralised; `.gitignore` gained the defence-in-depth patterns; `tools/make_product_repo.ps1` + `docs/PRODUCT_REPO.md` are the squashed-repo recipe. Test fixtures are neutralised as of 2026-08-17: `leso`→`editor1`, `ruskin`→`editor2`, `RUSKIN-PC`→`EDITOR-PC-02`, `SAMDISK`→`EXT-DISK`, `alex`→`owen`, and every real tailnet/LAN address and the tailnet name replaced with `site.example.toml`'s placeholders — zero hits repo-wide outside this audit, the archived bug-hunt notes, and the product-repo scrubber's own denylist (which excludes itself from the export). Note the open conflict: `make_product_repo.ps1` treats the placeholder licensor name as a tenant marker while requiring `LICENSE` to ship — resolved the day counsel supplies the real entity name. Not changed on purpose: the PHYSICAL `Creators_Club` tree/archive directory name (a migration).

**Follow-up 2026-08-18, later — the neutral mark itself was the wrong reading (KNOWN_BUGS CR-25).** The owner's ruling: *"our brand on every customer's build is what I want. It's branded Creators Club software being sold like DaVinci Resolve or Premiere Pro, which all have their own branded logos."* So item 10's rule is **no customer's name in code**, not *no brand*: the Creators Club mark (`cc_mark_white.png`) is the product default again on tray, title bars and taskbar; the neutral `ccsync_mark.png` stays shipped as the white-label option a fleet selects with `brand_logo`. Names (`org_name`/`org_short`) remain site data — the customer's name is theirs, the mark is ours.

**Follow-up 2026-08-18 — the neutral mark was a one-way door (KNOWN_BUGS CR-23).** `$CCSYNC_BRAND_LOGO` is *machine environment*, so the fleet already wearing its own logo lost it the moment its editors upgraded, and giving it back meant touching every machine — in practice a reinstall, which is exactly the cost this item existed to remove. The mark now travels with the brand strings beside it: `brand_logo` in the manifest (`[site]`, `DASH_SITE_BRAND_LOGO`, editable on Settings with no `--recreate`), resolved env → manifest → product mark. The env var still wins: an escape hatch a server can overrule is not one. The lesson generalises — **anything this item made "site data" has to be settable from the server, not only from an installer**, or de-tenanting reads as de-branding to the customer who already had one.

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

**Status 2026-08-17 — DONE in repo. Ship state: see `KNOWN_BUGS.md` CR-17.** Every `P:` and `Creators_Club` site in `windows_bootstrap.ps1`, `windows_uninstall.ps1`, `windows_upgrade.ps1`, `macos_bootstrap.sh` and `macos_uninstall.sh` derives from the manifest's `canonical_prefix` / `tree_name` (loopback share name, logon task, Explorer label key, the "is this drive ours?" guard included); the uninstallers read the prefix from the local `config.toml` so they work off-tailnet; 61 new table-test cases across `Test-DriveMapParser.ps1` and the new `installer/tests/test_macos_site_values.sh`; three `-DryRun` runs against fake `W:`/`Y:` manifests. Template folders and the shared-asset registry are `site.toml [tree]` overrides served by the manifest; the video-extension list has one canonical copy (`dashboard/provision.py`) the other three are pinned to; the forced `creators_club_sftp` remote name is gone; personal-path defaults are deleted from both indexers (paths are required — item 14). Owed: `INSTALLER_VERSION` 1.0.30 in three files, one real install on a scratch Windows machine, and the macOS half has still never run on a Mac.

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

**Status 2026-08-17 — DONE in repo for everything a Windows base rig can do.** Platform envelope stated (Resolve Studio + TrueNAS SCALE 25.x or Synology DSM 7.2 + Tailscale; `docs/INSTALL.md`, `docs/ARCHITECTURE.md`); the `ServerBackend`/`NasBackend` seams and the Synology port landed on `main` (v2 pulled forward). `dashboard/deploy/Dockerfile` builds a self-contained, digest-pinned, non-root, `--require-hashes` image with `compose.image.yaml` as a full template variant; bind-mount mode remains the default and both share one entrypoint (`docs/DOCKER.md`); NOT built — no Docker on the base rig — and `install_dashboard_app.py` still deploys bind-mount mode only. **No longer true as at 2026-09-04 (SYS-19):** `install_dashboard_app.py` deploys either (`STACK_MODES = ("bind", "image")`) and this fleet's dashboard runs in image mode. `DASH_AUTH_METHOD=oidc` is a real second implementation (`oidc.py`: discovery, PKCE, state/nonce, JWKS via PyJWT, `/login?local=1` break-glass; 17 tests against an in-process IdP) — never pointed at a real IdP. The Mac release gap is closed by `.github/workflows/release-macos.yml`; macOS validation on a real Mac is still owed. Linux client and in-instance multi-tenancy remain deferred.

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

**Status 2026-08-17 — DONE in repo.** Eleven hash-pinned `requirements.lock` files (`uv pip compile --universal --generate-hashes`), consumed by `run.sh --require-hashes`, the image build and CI (refresh recipe in `docs/RELEASE.md`); `.github/workflows/ci.yml` runs every suite on Windows/Linux/macOS with `tools/check_licenses.py` (+ `tools/license_allowlist.toml`) and a CRLF byte-scan; `release-windows.yml` / `release-macos.yml` build (never publish) with the item-4 signing secrets wired; rclone/Syncthing installer downloads pinned by version + sha256; `crash_report.py` on both sides (local redacted crash JSON always, Sentry-compatible send only on explicit opt-in the shipped builds cannot even satisfy) plus optional json-lines log rotation under `DASH_LOG_DIR`. Docs for strangers: `docs/INSTALL.md`, `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/CONFIG.md` (the `site.toml` schema in prose — the loader in `server/common.py` is the validator), `docs/README.md` index; the operational docs de-tenanted (literal IPs/names → placeholders or `site.toml` keys; the dated bug-hunt files kept as archives). Owed: push the repo to a CI provider (it has never had one); i18n/accessibility untouched.

### 14. Package the GPU indexers or scope them out of v1 — LOW universal, weeks

Both indexers are `pip install -e .` from source with hand-edited YAML. Music
needs an RTX-class GPU (9 min per full rebuild) and adding one track is a
documented lossy pull-drain-push; b-roll transcription shells out to a
faster-whisper environment at `C:\Users\alex\tools\whisper` that isn't in
this repo.

Fix: a GPU Docker image covering CUDA/whisper/torch; required-not-defaulted
`data_root`/`db.path`; a queue drain with no lost-write window — or ship
search-only from a vendor-built index in v1.

**Status 2026-08-17 — mostly DONE.** Every path in both indexers is required-not-defaulted with a refusal naming the key and env overrides (`BROLL_DATA_ROOT`, `BROLL_DB_PATH`, `CCSYNC_WHISPER_PYTHON/_SCRIPT/_MODEL_DIR`, `BROLL_MODEL_CACHE`, `MUSIC_DB_PATH`, `MUSIC_MODEL_CACHE`); no personal path left in any default. The faster-whisper environment is in-repo (`broll/indexer/tools/make_whisper_env.ps1|.sh`, `tools/whisper_transcribe.py`, a `[transcribe]` extra). `tools/Dockerfile.indexer-gpu` + `tools/compose.indexer-gpu.yaml` package both indexers on a pinned CUDA base with nvidia device reservations (**written, not built**). The lossy pull-drain-push is gone: an append-only ingest journal (`ingest_queue.uid`, migration 003) plus a verified result-bundle merge (`musicweb/drain.py`). `docs/INDEXERS.md` documents what runs where and the v1 scope-out (search-only from a vendor-built index for customers without a GPU). Operator: set the two whisper keys on the base rig (they no longer default), set `MUSIC_DB_PATH`, build and smoke the image on a GPU host, run one real drain end to end; the ffmpeg-in-image licence posture is a counsel question before any registry publish.

**2026-08-18 — the "package or scope out" question has a third answer for b-roll: local, zero-cost, and it shipped.** `indexer.backend = local | anthropic` (`broll/indexer/broll_index/config.py`), default **`local`** for a new install; an existing config naming `anthropic:` keeps running unchanged. Local runs **Qwen3-VL** (Apache-2.0) through a vendored **llama.cpp** `llama-server` (MIT) — two tiers, Good (4B, 8 GB VRAM) and Best (8B, 12 GB VRAM), pinned model/runtime sha256 in `broll_index/local_models.py`, fetched and verified by `broll_index/local_runtime.py` (`broll-index models pull`, `broll-index doctor`). The design (frames not sheets, a GBNF grammar bounding the decode, timecodes looked up not trusted, category assigned in code, and a segment-merge post-process for the format's own over-segmentation) is exactly what `broll/eval/local_vlm/`'s 100-clip eval proved out (`results/report.md`) after `broll/docs/local-indexing-options-2026-08-17.md`'s four-clip prototype found the naive drop-in wanting. `pipeline.stage_claude` is now `pipeline.stage_describe`, dispatching on backend; the Anthropic path is byte-for-byte unchanged. Docs: `broll/docs/indexing-local.md` (new), `docs/INDEXERS.md`, `broll/docs/indexing-api.md`, `docs/ZERO_TOUCH_PLAN.md` §8 all updated. 100 new tests (`broll/indexer/tests/test_{compact_format,local_vlm_merge,local_vlm_server,local_runtime,indexer_backend_config,dashboard_site,cli_local_backend}.py`), a real GPU smoke on 2 archive clips on the base rig's RTX 3080 (~10-14 s/clip, grammar-valid, merge collapsed the compact format's over-segmentation as designed). llama.cpp/Qwen3-VL are downloaded at install time, not pip packages — `tools/check_licenses.py`'s gate does not see them (by design, same posture as whisper/CLAP weights today); inventoried by hand in `docs/legal/THIRD_PARTY_NOTICES.md`. Not yet built/smoked: `tools/Dockerfile.indexer-gpu` does not yet vendor llama.cpp for the container path (still Anthropic-only in that image); the 8B tier's files were not downloaded to prove the pin (its sha256 is Hugging Face's own API-reported digest, cross-checked against the 4B's, which WAS downloaded and byte-verified).

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

**Status 2026-08-17 — DONE in repo across all its rows. Ship state: see `KNOWN_BUGS.md` CR-8 (sessions/CSRF) and CR-18 (per-editor fleet tokens); the remaining rows have no single ledger id, status unknown as at 2026-09-04.** Standalone b-roll ingest fail-closed (503, dev branch deleted); music ingest fail-closed when not behind the dashboard login and bounded (64 files / 512 MB); secret strength enforced at boot with the ingest token's rule; login throttle in SQLite with per-username AND per-IP budgets and backoff; CSRF synchroniser token on every dashboard htmx/form POST (the three mounted SPAs still on the exempt list — one header each to close); per-editor fleet tokens end to end (minted/revoked on Admin › Users, hashed, shown once, bound to an editor) with the shared token behind `DASH_SHARED_REPORT_TOKEN_ENABLED` and a boot log naming the machines still using it; `identity.json`/`config.toml` owner-only on both platforms (`secretfile.harden`, `icacls` on Windows) plus the installer's `icacls` on install and upgrade; no dashboard call follows a redirect; error bodies carry no NAS hosts or absolute paths; fleet reads scoped to the viewer; the editor-laptop SMB share gets an inbound 139/445 block rule; the elevated helper is a per-run random name in an ACL'd per-user dir; `setx` secrets replaced by `tools/load_secrets.ps1` (DPAPI) + `docs/SECRETS.md`; `YTDL_DEV_USER` deleted; `DASH_REPORT_TOKEN_OPTIONAL` inert outside `DASH_DEV_INSECURE`; admin password floor of 12 on set/change. Operator: publish a companion build before minting any per-editor token; flip the shared token off only when the boot log goes quiet.

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
- `ruskin` + hostname `DESKTOP-<redacted>` across KNOWN_BUGS; `alex` as default
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

### 16. Zero-touch install: the customer installs Tailscale and one container, only we build — quarter

Added 2026-08-17 after items 1–15 landed. Everything above still leaves the
customer as tenant, release engineer and signing authority on a Windows
"base rig" with a git checkout: 41 manual steps, `PyInstaller` per release,
their own release key, `--recreate` from a shell for any site change, no
vendor feed and no dashboard self-update. The answer is an appliance — one
vendor-built image, Syncthing + SFTP + Tailscale as sidecars in the same
stack, a browser setup wizard, dashboard-local identity, invites, and a
signed release feed every dashboard pulls. Full design, work packages and
spikes: [`ZERO_TOUCH_PLAN.md`](ZERO_TOUCH_PLAN.md).

**Status 2026-08-17 — PLANNED, nothing built.** Depends on item 12's image
(never yet `docker build`-ed) and reuses `SYNOLOGY_EASY_INSTALL.md`'s
checklist and invite designs.

## What the operator does next (consolidated, 2026-08-17)

Ordered so that nothing breaks the fleet that is currently on 0.7.11.

1. **Before ANY dashboard deploy:** check the live `DASH_SESSION_SECRET` and
   `DASH_REPORT_TOKEN` are ≥ 24 chars and not placeholders (the container now
   refuses to boot otherwise — CR-8); set `DASH_RELEASE_PUBKEYS` to the baked
   public key (CR-6); set `ANTHROPIC_API_KEY` in the deploying shell (CR-2);
   confirm this studio's `site.toml` has `[features] youtube_download =
   youtube_unblock = true` and `[stack] editor_shell = "shell"`; expect every
   browser session to be signed out once (CR-8) and migrations v14–v16 to run.
2. **Deploy the dashboard** (`tools\ship.cmd -DashboardOnly` or the full ship);
   then on the NAS: `setup_snapshots.py --apply` + `--list` (CR-10),
   `secure_syncthing_gui.py` (CR-9), `rm -rf <host-root>/claude-home
   <host-root>/claude-bin` + revoke the OAuth credential (CR-2), and consider
   `create_api_key.py` → `TRUENAS_API_KEY` + redeploy (CR-9). Pin the NAS host
   key in `site.toml` (CR-9). Same on the Synology where applicable.
3. **Confirm every companion's `dashboard_url`** matches the origin editors
   browse (CR-7) BEFORE publishing the companion; behind Tailscale Serve set
   `DASH_COOKIE_SECURE=1` + `DASH_SITE_DASHBOARD_URL=https://…ts.net`.
4. **Bump versions and ship**: `tools\ship.cmd -AllowUnsignedBinary` until
   certificates exist. Back up `%USERPROFILE%\.ccsync-release\release.key`
   offline first (CR-6). Watch the first deploy's ffmpeg fetch (CR-4) and the
   first lane B pass per machine (CR-11 baseline). Publish the first signed
   build BEFORE editors upgrade past 0.7.11.
   *Updated 2026-08-18:* the versions are now **companion 0.9.0 / dashboard
   0.6.0 / installer 1.0.32**, the installer number lives in **four** files
   (not three), and `ship.cmd` is no longer the whole release. A release that
   reaches feed customers is four commands (`docs/RELEASE.md`, "What a whole
   release is"): the ship, the companion to the feed, the dashboard code
   bundle, and the CLAP audio artefacts that music ingest cannot run without.
5. **After the ship:** mint per-editor tokens and later flip
   `DASH_SHARED_REPORT_TOKEN_ENABLED=0` (CR-18); check `~/.ccsync/resolve_edits/`
   gets a `.drp` on the base rig (CR-12); set the whisper keys + `MUSIC_DB_PATH`
   on the base rig and run one real music drain (CR-20); run one real indexing
   pass on the API key (CR-1); once verified, `CCSYNC_REQUIRE_SNAPSHOT=1`.
6. **Purchases / people:** Authenticode + Apple Developer ID certificates
   (CR-6); counsel review of `docs/legal/*` and the entity name (CR-5), the
   YouTube attestation wording (CR-2), the ffmpeg-in-image posture (item 14);
   a written licence grant for `yt-credit-downloader` (CR-2); an Anthropic key
   on the customer's own organisation per site (CR-1/CR-2).
7. **On a Mac:** `tools/release_macos.sh` / `build_onboard_macos.sh` (with the
   release key copied to `~/.ccsync-release/`), watch the LaunchAgent rename
   migration (`launchctl list | grep ccsync` shows one companion — CR-16), and
   run the first-run script that has never run.
8. **Later:** push the repo to GitHub for CI (CR-19), first `docker build` of
   the dashboard image and the GPU indexer image, `setup_editor_account.py
   --migrate-existing --apply` then flip `editor_shell` to `sftp-only` (CR-9),
   the three SPAs' CSRF header (CR-8), a Keycloak/Entra sign-in for OIDC,
   `tools/make_product_repo.ps1` when the product repo is wanted.

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
