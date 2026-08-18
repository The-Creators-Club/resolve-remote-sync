# Known bugs

**Status 2026-08-15: everything below that says "in repo, unshipped" IS NOW
SHIPPED** — the 08-14 hunt pass, R14 and R15 all went out in one commit
(`5ab221d`) as **companion 0.7.8 / installer 1.0.27**, together with phases
1+2 of requester-first ytdl downloads. Base rig verified after the ship:
`check_deploy_drift.ps1` clean, running build sha-identical to
`companion/dist` and stamped with that commit, `ytdlp_manager` installed
yt-dlp 2026.07.04 on first run. Note the version skew: `docs/
YTDL_LOCAL_DOWNLOAD.md` was written against a **0.8.0** target and the
feature actually shipped under **0.7.8**. Still owed, as ever: the **Mac
builds** (not cross-buildable from Windows) and every editor accepting the
tray upgrade. The `setup_syncthing_folder.py` re-run this paragraph used to
ask for is NOT owed — see R15.

**Status 2026-08-11 (evening): the morning's 82-finding hunt is FIXED — same
day, all of it, plus the 45-finding ytdl ledger and the delete-protection
patch.** The full hunt text with per-entry resolutions and the deliberate
divergences is archived at `docs/bug-hunt-2026-08-11.md`; the ytdl ledger
(`docs/youtube_dlp_bugs.md`) carries its own resolution header. The fix pass
was eleven Opus agents over disjoint file territories, orchestrator-verified,
~125 files, +6.7k lines (about half of it tests). All ten suites green
(`tools\run_all_tests.ps1` — which now genuinely runs all of them, OPS-6).

That pass SHIPPED the same day as companion 0.7.0 / installer 1.0.22 /
dashboard 0.4.0 (drift doctor clean, base rig upgraded, sprites and the
migrated b-roll DB pushed to the NAS). Only the Mac builds were left behind,
and they still are.

This file is the ledger of what is STILL open.

**2026-08-14: a third full-repo hunt ran (12 Opus hunters + 12 adversarial
verifiers, every tracked source file, briefed on this ledger and both 08-11
archives). It confirmed 94 NEW findings — 10 critical / 46 major / 38 minor —
plus 7 uncertain. FIXED the same evening by an 11-agent Opus fix pass
(disjoint file territories, orchestrator-reconciled; resolution header in
`docs/bug-hunt-2026-08-14.md` — the per-finding OUTCOMES are not in that
file, each fix cites its finding id and date at the code site instead, so
`grep -rn COMP-GUARD-1` is how you find what was done about one). All 10 criticals
fixed; all 10 suites green (`tools\run_all_tests.ps1`: 0 of 10 failed,
~+250 tests); eight findings deliberately NOT fixed — see R16. Two pieces
of the pass already happened outside the repo: the base rig's
`broll-indexer-watchdog` scheduled task was re-registered against the
in-repo `watchdog.ps1` (still Disabled, ops half of BROLL-IDX-2), and the
music UI's reveal now requires a companion carrying `POST /music/reveal` —
one more entry in the "editors need a republished companion" column.
SHIPPED 2026-08-15 as companion 0.7.8 / installer 1.0.27 (commit `5ab221d`)
— NOT the 0.8.0 the ytdl plan names as its target.**

---

**Status 2026-08-17 (evening): the commercial-readiness pass
(`docs/COMMERCIAL_READINESS.md`, all 15 items) was IMPLEMENTED IN REPO by a
15-agent Opus fleet on branch `commercial-readiness` (disjoint file
territories, integration agent + full-suite verification afterwards; ~220
files, ~+18k lines, roughly half tests). NOTHING FROM IT IS SHIPPED. Every
entry below tagged CR-n is "fixed in repo, unshipped" unless it says
otherwise, and several need an operator step on a live NAS, a certificate,
counsel, or a Mac before the fix is real. The consolidated operator list is
the "Status 2026-08-17" paragraphs in `docs/COMMERCIAL_READINESS.md`.**

---

## Open — the 2026-08-17 commercial-readiness pass (CR-n)

### CR-1 — the b-roll indexer billed a personal Claude Code subscription — FIXED in repo 2026-08-17, unshipped
`broll/indexer` drove `claude -p` against one operator's claude.ai login: a
customer install has no `claude` binary and no such login, the session
limits are per-person, and the Consumer Terms do not cover reselling it. The
`claude` stage now calls the Messages API through the `anthropic` SDK
(`broll_index/claude_client.py`), key from `ANTHROPIC_API_KEY` (name
configurable) or a keyfile — never from config.yaml, which the loader
refuses. Contact sheets travel as base64 image blocks; `parallel_claude.py`
is a thread pool whose `--workers` is also the client's in-flight ceiling;
429/5xx/overloaded retry with jittered backoff honouring `retry-after`, then
classify as account-wide so the queue stays resumable. `total_cost_usd` in
`usage.jsonl` is now a LOCAL ESTIMATE. Not yet exercised against a live key —
owed: one real pass on a customer key to re-baseline per-clip cost.
`broll/docs/indexing-api.md`.

### CR-2 — the YouTube feature shipped on by default, with the vendor's Claude account, an unverified identity and no rights record — FIXED in repo 2026-08-17, unshipped
Items 1, 2, 3, 7/H5, 15 of the readiness doc, all in the ytdl stack:
- **It was on for everybody.** Now `site.toml [features] youtube_download`
  (default OFF, published in `GET /api/v1/site`): off, `mount_ytdl()` returns
  `disabled` before importing anything, `/ytdl` and every fleet route 404, and
  each companion hides its tray items, refuses `/ytdl/*` loopback calls and
  installs no tooling. A client that cannot read the manifest treats it as off.
  THIS studio's git-ignored `site.toml` sets both flags on.
- **No rights record.** A rights/ToS attestation is now accepted per user
  (`ytdl.db.attestations`) and per machine
  (`~/.ccsync/state/ytdl-attestation.json`) with wording version, digest and
  timestamp; downloads 403 (`reason:'attestation'`) in the browser, at the
  claim and in `capabilities()`. Wording is a DRAFT FOR COUNSEL
  (`docs/legal/YOUTUBE_FEATURE_NOTICE.md`).
- **The circumvention components were part of the install.** PO-token
  sidecar, deno n-challenge solver and cookie sign-in are a second, narrower
  opt-in (`[features] youtube_unblock` / `--enable-youtube-unblock`). The
  vendor build provisions none of them; the code stays dormant.
- **Every deployment ran on one human's Claude account** (`claude -p` +
  a hand-performed `/login` in a `claude-home` volume). Now the `anthropic`
  SDK with the CUSTOMER's `ANTHROPIC_API_KEY`; claude-bin/claude-home mounts
  deleted (removal + credential revocation steps in `ytdl/web/DEPLOY.md`).
  Untrusted page/title text goes in the user turn as fenced data.
- **The fleet token was treated as an identity (H5).** `X-CCSync-Identity`
  now carries the dashboard's signed identity token and `routes_fleet`
  verifies it against `DASH_SESSION_SECRET` (fails closed); `is_leaseholder`
  no longer accepts a nameless caller. `YTDL_DEV_USER` is gone, replaced by an
  in-process `session.set_test_user()`.
Owed: a written licence grant for `ytdl/web/ytdlweb/vendor/`
(`PROVENANCE.md` — upstream `The-Creators-Club/Utilities` has no licence
file), counsel review of the attestation wording, a retention policy for the
attestation + download records, and on the live NAS `rm -rf
<host-root>/claude-home <host-root>/claude-bin` + revoking the OAuth
credential.

### CR-3 — pystray (LGPLv3) was frozen into the companion, and its internals were copied — FIXED in repo 2026-08-17, unshipped
`pystray` is LGPLv3 (verified from installed metadata). It was collected into
the single-file PyInstaller freeze, which conveys it with no way to relink
against a modified copy, and `tray.py:242-395` monkeypatched its win32
internals. Replaced by `ccsync_companion/tray_native.py` — original, written
from the Shell_NotifyIconW / TrackPopupMenuEx / CreateIconIndirect and
NSStatusBar / NSMenu documentation. Removed from `pyproject.toml`,
`build.spec` and `requirements.lock`; `tools/check_licenses.py` FAILS if it
comes back. `CCSYNC_TRAY_BACKEND=pystray` remains as a dev escape hatch that
refuses under `sys.frozen`. Two old bugs die with it: the HMENU is built at
right-click time and destroyed on close (the destroyed-handle race and USER
leak behind the 2026-07-26 freezes are structurally impossible), and the
menu-open flag is set by the backend on BOTH platforms. Verified on the base
rig with `companion/tools/tray_smoke.py` (icon added, menu read back out of
USER32, item selected). **macOS is code-complete but unverified.**

### CR-4 — the installer conveyed a GPLv3 ffmpeg to the customer's NAS — FIXED in repo 2026-08-17
`install_dashboard_app.py` defaulted to `--ffmpeg-fetch local`: this
workstation SFTP-pushed johnvansickle's GPLv3 static build onto the target —
conveying under §6 with no source offer. Default flipped to `remote` (the
NAS curls the same pinned URL and verifies the same sha256); the 2026-08-10
reason for `local` (42 MB at ~28 kB/s outlived `run_ssh`'s 600 s) is
answered by `FFMPEG_REMOTE_INSTALL_TIMEOUT = 1800`, `curl --retry 3`, still
NON-FATAL. Air-gapped sites keep the push behind `--push-ffmpeg-from-local`,
which prints `FFMPEG_LOCAL_PUSH_GPL_NOTICE` before any bytes move. Watch the
first deploy: first time a NAS does the ~25-minute download under the new
ceiling.

### CR-5 — no LICENSE, EULA, privacy policy, telemetry disclosure or third-party notices — DRAFTED 2026-08-17, awaiting counsel
All exist as DRAFTS FOR COUNSEL: `LICENSE`, `docs/legal/EULA.md`,
`PRIVACY.md`, `TELEMETRY.md`, `THIRD_PARTY_NOTICES.md` (generated by
`tools/gen_notices.py`, `--check` as a CI gate). The wizard's new page 0
requires acceptance and records `~/.ccsync/eula_accepted.json`; the companion
refuses to start lanes without a current one, and FAILS OPEN when the bundled
document is missing (a packaging fault must never stop a fleet syncing —
`build.spec`'s `assets/EULA.md` datas line is pinned by
`test_build_spec_ships_the_eula`). Bumping the EULA's `<!-- EULA-VERSION -->`
marker pushes every editor in every fleet back through the wizard — a
release-level decision. Open and both hard: counsel review starting with the
legal entity name (placeholder "Cablewrap Creative" was INFERRED from the
operator's email domain), and the `yt-credit-downloader` grant (CR-2). Also
from TELEMETRY.md: `resolve_project` / `local_manifest` / `media_tree`
reporting has no "off" but uninstalling — a config switch is owed.

### CR-6 — the upgrade channel was unauthenticated (STOP-SHIP) — FIXED in repo 2026-08-17, certificates NOT bought
`upgrade.url` and the sha256 that "verified" the download arrived in the SAME
plain-HTTP `/api/v1/report` response, so anything able to answer as the
dashboard could hand an editor an arbitrary binary plus a matching hash,
which `upgrade.py` renamed over the running companion and launched. FIXED:
every published record is signed offline with an ed25519 key that exists on
no server (`tools/release_key.py`, `tools/sign_release.py`; public half baked
into `ccsync_companion/release_pubkey.py`, pure-Python RFC 8032 verifier in
`ed25519.py`, no new frozen dep). The companion verifies BEFORE downloading
and the signed sha256 after; the dashboard verifies on publish against
`DASH_RELEASE_PUBKEYS` and refuses an unsigned publish (422) or an
unconfigured key (503). Plus a monotonic downgrade floor
(`~/.ccsync/upgrade_floor.json`, `min_version` in the signed record) and a
transport rule (https, or plain http to tailnet/LAN only, logged once).
Migration is additive: 0.7.11 can still take the first signed build. A key WAS
generated on this rig (`%USERPROFILE%\.ccsync-release\release.key`, pubkey
`GKNmk8MktRkGkrBv+ziF7O6ZNKCnjXfC9/TwDiYwKDY=`, id `ed717ff9611d6ec8`) — decide
whether to keep it before the first customer ship, and BACK IT UP OFFLINE
(losing it means no build can ever be offered to the fleet again). STILL
OPEN: no Authenticode or Developer ID certificate exists, so every build is
`signed_binary=false` and `tools\ship.cmd` needs `-AllowUnsignedBinary`; and
`DASH_RELEASE_PUBKEYS` must be set on both live dashboards (+ `--recreate`) or
every publish 503s. `docs/RELEASE.md` "Code signing".

### CR-7 — the 8899 loopback answered any page in the editor's browser (CRITICAL C1) — FIXED in repo 2026-08-17, unshipped
`broll_server.py` sent `Access-Control-Allow-Origin: *` plus
`Access-Control-Allow-Private-Network: true` and checked no Origin, Host,
token or content type — any ad iframe or phished link could insert clips
into the timeline being graded, start NAS fetches, spawn Explorer/`open`, and
claim fleet ytdl jobs. Three smaller holes went with it: `probe_darwin_mount`
interpolated `share` into `/Volumes/<share>` unvalidated (`../..` = `/`),
`/insert` was the one path route without containment, and a reveal could
`open` a `.app`. `docs/YTDL_LOCAL_DOWNLOAD.md:331` claimed an origin check
existed; it never had. Now: `loopback_guard.py` allow-lists the Origin to this
deployment's dashboard (`dashboard_url` + the cached site manifest, both
schemes); a POST needs that Origin OR the `X-CCSync-Loopback` token from
`~/.ccsync/loopback-token`, plus `Content-Type: application/json` and a
loopback `Host`; `share` is one safe segment; every path route
realpath-contains; bundles are revealed, never opened; fetches are capped at 2
and go through `root_guard`. `docs/LOOPBACK_API.md`. **Ops note for the ship:
every companion's `dashboard_url` must equal the origin editors actually
browse** (Tailscale Serve `https://nas.<tailnet>.ts.net` vs a provisioned
`http://100.x:8480`) or every Send-to-Resolve 403s; `loopback_extra_origins`
is the per-machine escape hatch, the site manifest's `dashboard_url` the
fleet-wide one.

### CR-8 — the dashboard's session layer: no revocation, no secret floor, spoofable X-Forwarded-Proto, no CSRF token — FIXED in repo 2026-08-17, unshipped
Items 6/H1, 12 and 15. A stolen session cookie was good for seven days and
nothing could stop it (rotating `DASH_SESSION_SECRET` signs out the fleet AND
invalidates every companion identity token); two browsers signing in as the
same editor in the same second got a byte-identical cookie;
`X-Forwarded-Proto` was believed from anyone; `DASH_SESSION_SECRET` /
`DASH_REPORT_TOKEN` had no strength check while compose ships `REPLACE_ME`;
the login throttle was an unlocked in-process dict, per-username only; CSRF
rested on `SameSite=Lax`; `DASH_REPORT_TOKEN_OPTIONAL` was one env var from
unauthenticated fleet writes. Fixed: server-side revocable sessions
(`sessions.py`, `auth_sessions` keyed by HMAC(secret, cookie); logout,
`[ LOGOUT ALL ]`, admin revoke on Users; 12h idle / 7d absolute), per-login
nonce, `DASH_TRUSTED_PROXIES` (default loopback), `DASH_COOKIE_SECURE=1`
refuses plaintext login, `check_boot_secrets` reuses
`broll.check_ingest_token` and REFUSES TO START on a weak secret, SQLite
throttle per-username AND per-IP with backoff and one generic message, CSRF
synchroniser token on every dashboard htmx/form POST, 12-char floor on
passwords the dashboard SETS, `DASH_AUTH_METHOD=oidc` (PKCE, state/nonce,
JWKS via PyJWT, `/login?local=1` break-glass) — never pointed at a real IdP.
`DASH_DEV_INSECURE=1` is the ONE dev/test bypass (`dashboard/tests/conftest.py`
sets it). BEHAVIOUR CHANGES ON DEPLOY: everyone is signed out once; the
container REFUSES TO BOOT if either secret is under 24 chars/placeholder —
CHECK THE LIVE VALUES FIRST; behind Tailscale Serve set `DASH_COOKIE_SECURE=1`
(not `auto` — the request arrives from the docker bridge, not loopback).
STILL OPEN: the three mounted SPAs (`/broll`, `/music`, `/ytdl`) do not send
the CSRF token yet and sit on `app._CSRF_EXEMPT_PREFIXES` (the token is on
the topbar they inject as `data-csrf`; one header each).

### CR-9 — the base rig trusted any host key, the container held the NAS root password, and every editor had a shell — FIXED in repo 2026-08-17, unshipped
Items 6 (H2/H3) and 7 (H4). SSH: `ssh_client` accepted whatever answered on
22 while writing the admin password to that channel — pinning is now the rule
(`[nas] ssh_hostkey`); an unknown host is a refusal, first use needs
`--trust-host-key-on-first-use` and is recorded in `~/.ccsync/known_hosts`, a
CHANGED key refuses naming both fingerprints. TLS: `verify=False` became
`TRUENAS_VERIFY_SSL` (off still allowed, warned every run, CA path works from
the container). Container: `server/create_api_key.py` mints a scoped TrueNAS
API key; with `TRUENAS_API_KEY` set the deploy writes NO password into the
container (DSM has no equivalent and keeps the password behind loopback).
Editors: new accounts are `nologin` + sshd `Match Group editors` block
(`ForceCommand internal-sftp`, `PasswordAuthentication no`) and the manifest
publishes `sftp_shell_type=none` automatically; NO ChrootDirectory (would
re-root every absolute path the manifest publishes); `[stack] project_acl =
"per-project"` adds `proj-<slug>` groups + setgid+sticky containers
(`docs/TENANCY.md`), default `shared`. `server/secure_syncthing_gui.py` puts
a login on the Syncthing GUI (an unauthenticated admin surface on both
platforms until it is run). Residual, deliberate: THIS fleet is pinned to
`[stack] editor_shell = "shell"` in its site.toml until
`setup_editor_account.py --migrate-existing --apply` runs (deploying with it
flipped early breaks every editor's rclone checksums); the `api_key.create`
body shape and the chart's `web_port.host_ips` are coded from knowledge and
marked "verify against the live version"; the dashboard provisioner does not
yet add proj-<slug> membership on a tick; DSM per-project is a grant plus an
operator TODO.

### CR-10 — the fleet had no backups at all, and the b-roll index was published by `copy` over a live WAL database — FIXED in repo 2026-08-17, NOT YET APPLIED to either NAS
Zero references to snapshots, replication or restore existed; the only
`broll.db` publish recipe was a plain SMB copy over a WAL-mode database the
container holds open read-write. `server/setup_snapshots.py` creates the
periodic tasks on the tree AND the apps dataset (hourly keep 24, daily keep
30, recursive) idempotently — TrueNAS via `/pool/snapshottask`; DSM prints the
exact Snapshot Replication click path and exits 1. `common.snapshot_before()`
snapshots before `setup_tree.py`'s `chown -R` and before the deploy /
`--recreate` swap (best-effort unless `--require-snapshot` /
`$CCSYNC_REQUIRE_SNAPSHOT`). `server/publish_db.py --which broll|music` is
the ff3 memory-note recipe as code: checkpoint, local `sqlite3.backup()`,
`quick_check` locally AND on the NAS, >10 % row-count shrink refusal, atomic
rename, `<name>.db.prev-<ts>` kept, `--rollback`. Runbook
`docs/BACKUP_RESTORE.md`. Owed by the operator: `setup_snapshots.py --apply`
on the TrueNAS (and the Synology), then `--list` within the hour — until then
this entry is code, not protection; the `pool.snapshottask` payload is
unverified against a live 25.10 middleware.

### CR-11 — lane B could walk a proxy set into the trash 20 GB per pass with the grid green — FIXED in repo 2026-08-17, unshipped
`--max-delete 100 / 20G` bounds ONE pass, not the sequence: a wrong
`remote_root`, a NAS listing empty while its pool imports, or a project
unshared behind the companion's back all present as "the source no longer
has these files". Four more edges went with it: `.ccsync-trash` never pruned;
"Remove from this machine" `rmtree`'d with no caught-up check; Pause was not
Stop and nothing could halt lane C or the fleet; lane A silently never
re-uploads a same-name re-export. Fixed in `sync/lane_guard.py`: a persisted
**circuit breaker** (trips BEFORE a pass on a marker-less/empty/halved
remote, AFTER on >50 deletions or >25 % of the local proxy set, and on a
cumulative leak; lane B parks `paused` — never `error` — while lanes A and C
keep running; cleared only from the tray); **trash retention** (14 days /
50 GB, oldest first, never while tripped — a deliberate reversal of AUDIT_2
C-7); a fail-closed **removal gate** (lane A `--dry-run` + Syncthing
completion; override = type the project name, logged AND reported); a real
**halt** (lanes A+B stopped and every lane C folder paused via Syncthing REST,
persisted; fleet-wide via `POST /api/v1/fleet/halt` + a Users-page panel,
delivered on the report reply's `commands.halt`); and a `rclone check
--one-way --size-only` "won't upload" counter. Dashboard: schema v16,
`sync_guard` report section, row chips + fleet banners. `docs/SYNC_SAFETY.md`.
Costs: one extra `rclone lsf` per lane B pass; the first pass after upgrade
computes the baseline and may trip once on a project mid-reorganisation.

### CR-12 — the companion rewrote Resolve project databases with no save, no backup and no undo — FIXED in repo 2026-08-17, unshipped
Four code paths write clip paths — FIX ALL, the automatic canonical relink,
the automatic proxy repoint, the post-import canonicaliser — and two are
unprompted; none saved, exported or journalled, and Resolve's Undo does not
cover a scripted `ReplaceClip`. Now `resolve_journal.py` + a
`_before_mutation()` hook inside `resolve_bridge.replace_clip` /
`link_proxy_media`: `SaveProject()`, best-effort
`ProjectManager.ExportProject()` to `~/.ccsync/resolve_edits/<project>/<ts>.drp`,
and a per-burst JSON journal of old/new path per clip; Tray → Advanced →
"Undo the last clip-path change CCSync made…" replays it in reverse; the
unprompted paths are rate-limited to one burst per project per 15 min; the
fixer re-checks its O_EXCL reservation immediately before `os.replace` and
verifies copy size + source stability before relinking; `fixer_dry_run` /
`proxy_dry_run` rehearsal switches. `docs/RESOLVE_EDIT_SAFETY.md`. Add new
Resolve mutations THROUGH those two bridge functions. The companion suite's
`_no_live_resolve` conftest fixture exists because the save point calls
`connect()`. Unverified: that `ExportProject` really writes the `.drp` on a
live Resolve (fakes only) — check once on the base rig.

### CR-13 — proxy generation: no free-space floor, one-sample growing-source test, would encode a proxy of a proxy — FIXED in repo 2026-08-17, unshipped
`free_space_shortfall()` keeps max(20 GB, 5 %) clear
(`proxy_gen_free_space_floor_gb/_pct`), checked before anything is created,
skipped-and-surfaced (log, tray, `coverage()["low_space"]`); two (size,
mtime) samples `proxy_gen_stability_seconds` apart replace the single mtime
(rclone/Syncthing/card copiers stamp mtime at create AND finish); `is_proxy_path`
refuses `Proxy/`/`proxies/` at any depth, `.partial`, and a file that is its
own output.

### CR-14 — `fix_10bit_proxies.py --apply` could transcode an archive ORIGINAL in place, and `build_archive.py --apply` undid its repairs — FIXED in repo 2026-08-17
`reencode()` overwrote whatever it was handed and `source_for()` fell back to
the target itself whenever the parent was not `Proxy` — a row pointing at the
top-slot original got the archive's best copy re-encoded to 540p over
itself, `fixed` printed beside it. Now refused outright (`is_a_proxy`),
refusals printed in the dry run too. `build_archive --apply` decided by size
alone, so every R9 repair looked un-copied and the next build put the 10-bit
source back — now `needs_copy()` walks absent → size → mtime → quick
head+tail hash, `broll_index/inplace_fixes.py` records repairs at the archive
root and protects them, and anything replaced is stashed under
`.ccsync-replaced/<ts>/` (never swept automatically).

### CR-15 — the onboarding wizard tore down a real NAS `P:` mapping — FIXED in repo 2026-08-17
`execute_cleanup` ran `subst P: /D` + `net use P: /delete /y` on the ROLE
alone; the bootstrap (INST-15) and uninstaller (D-8) already refused to touch
a `P:` they did not create. Now `p_mapping_is_ours()` applies the bootstrap's
rule verbatim (subst = ours, `\\localhost\CCSync_P` = ours, the site's
`smb_unc` or any other UNC = refuse, unreadable = refuse).

### CR-16 — a Mac upgraded across the LaunchAgent rename could run two companions — FIXED on both sides in repo 2026-08-17, unshipped
Bundle ids and launchd labels moved `com.creatorsclub.*` → `com.ccsync.*`
(item 10). A machine installed before that has the legacy label still
bootstrapped, pointing at the same `~/.local/ccsync/bin`. The wizard
(`steps.retire_legacy_launch_agents()`) and `installer/macos_bootstrap.sh`
(`retire_legacy_agent`) both bootout + unload + delete the legacy pair before
writing the new one; `macos_uninstall.sh` enumerates both generations. Never
run on a Mac — the first Mac upgrade after this must be watched
(`launchctl list | grep ccsync` shows exactly one companion). Also from the
brand pass: every "Creators Club" string is site data (`org_name`/`org_short`,
fallback `product_name` = "CC Sync"), the tray mark is the neutral
`assets/ccsync_mark.png` unless `CCSYNC_BRAND_LOGO=cc_mark_white.png`, the
b-roll own-footage slug is `BROLL_DEFAULT_COLLECTION` (default `owned`, legacy
`creators_club` still routed), and the music `W:\Creators_Club` probe is
`MUSIC_LIBRARY_ROOT`. Not changed on purpose: the PHYSICAL `Creators_Club`
archive/tree directory name — a migration, not an edit.

### CR-17 — the installers were a fork per customer, and shipped unverified binaries — FIXED in repo 2026-08-17, unshipped
`P:` and `Creators_Club` were literals at ~70 sites in `windows_bootstrap.ps1`
(mount, teardown, `CCSync-SubstP` task, `CCSync_P` share, `MountPoints2`
label, the "is this drive somebody else's?" guard); a site mounting elsewhere
got an uninstaller that silently removed nothing. Both now derive from the
manifest's `canonical_prefix`/`tree_name`; the uninstallers read the prefix
from the local `config.toml` (off-tailnet). rclone (v1.75.0) and Syncthing
(v2.1.3) are pinned by version + sha256 in both bootstraps, verified before
unpacking, "latest" resolvers gone. The editor-laptop SMB share now comes with
an inbound block on TCP 139/445 (loopback is not filtered, so the mapping
still works; `-KeepRemoteSmbOpen` opts out); the elevated helper is a per-run
random name in an ACL'd per-user dir; `config.toml`/`identity.json` get
`icacls /inheritance:r` on install AND upgrade; `setx` for the four operator
secrets is replaced by `tools/load_secrets.ps1` (DPAPI) + `docs/SECRETS.md`.
Client data files (`config.queue.yaml`, `config.ff2.yaml`,
`duplicates_report.md`, `broll/eval/queries_*.yaml`) moved to a git-ignored
`private/`; `docs/macos-onboarding-handoff.md` scrubbed; `.gitignore` gained
the defence-in-depth patterns; `tools/make_product_repo.ps1` +
`docs/PRODUCT_REPO.md` are the squashed-product-repo recipe (not run). Owed:
`INSTALLER_VERSION` 1.0.30, one real install on a scratch Windows machine, and
the macOS half has still never run on a Mac.

### CR-18 — one fleet token for everyone, and four write paths behind it — FIXED in repo 2026-08-17, unshipped
`DASH_REPORT_TOKEN` proved "this is a companion", nothing about WHOSE, and
was not revocable per editor. Now an admin mints a per-editor token on Admin
› Users (`cce1.<id>.<secret>`, stored as sha256, shown once, revocable) and it
BINDS: a report or selection read under it may not claim another editor; the
shared token stays accepted behind `DASH_SHARED_REPORT_TOKEN_ENABLED`
(default 1) and the dashboard NAMES the machines still using it at every
boot. Handing a token over is manual by design (`/api/v1/verify` is the
unauthenticated bootstrap and must never issue one); it goes in `config.toml`
as `report_token`. Also: `identity.json`/`config.toml` owner-only via
`secretfile.harden` (`icacls` on Windows — `chmod` is a no-op there); the
reporter, selection client and ytdl executor no longer follow redirects
(stub the OPENER in tests, never `urlopen`); `broll/web` standalone ingest
fail-closed (no token = 503, dev branch deleted); `music/web` ingest
fail-closed when not behind the dashboard login and bounded (64 files /
512 MB); error bodies no longer carry NAS hosts or absolute paths (+ a global
500 handler); fleet reads are scoped (an editor sees their own machines plus
counts; another editor's device is a 404). Owed: publish a companion build
BEFORE minting any token; flip the shared token off only when the boot log
goes quiet; set `BROLL_INGEST_TOKEN` on any dev checkout of `broll/web`.

### CR-19 — the container's dependency set was never recorded, and no CI ever ran — FIXED in repo 2026-08-17, unshipped
Every dependency was a floor, one exact pin, no lockfile, no
`--require-hashes`. Now eleven `requirements.lock` files (`uv pip compile
--universal --generate-hashes`), `deploy/run.sh` prefers the lock with
`--require-hashes`, `dashboard/deploy/Dockerfile` bakes it into a
digest-pinned image (`compose.image.yaml`, `docs/DOCKER.md` — bind-mount mode
stays the default and both share one entrypoint), `.github/workflows/ci.yml`
runs every suite on Windows/Linux/macOS with `tools/check_licenses.py` and a
CRLF byte-scan; `release-windows.yml` / `release-macos.yml` build (never
publish) — the Mac runner is the answer to "PyInstaller needs a Mac".
`crash_report.py` on both sides writes a local redacted crash JSON always and
sends only on an explicit opt-in the shipped builds cannot satisfy (no
`sentry_sdk`). NOT verified: nothing has been through `docker build` (no
Docker on the base rig; `--require-hashes` forbids the source-build fallback,
so a wheel-less package fails early); `install_dashboard_app.py` still deploys
bind-mount mode only; the repo has never been pushed to a CI provider.

### CR-20 — the music queue drain overwrote every upload queued while it ran — FIXED in repo 2026-08-17 (MUSIC-13)
"Pull `music.db`, drain on the base rig, push back" is a file copy with no
merge — every `pending` row created during the window was discarded. Now
`ingest_queue.uid` (migration `003_ingest_journal.sql`), `index_music.py
--queue --export-drain` writes a result bundle, and `python -m musicweb.drain
apply` merges it in one transaction (`INSERT … ON CONFLICT`), closing only
the named uids and only when the live journal still agrees on `rel_path` +
`content_hash`. Also from item 14: both indexers' paths are
required-not-defaulted (`BROLL_DATA_ROOT`, `BROLL_DB_PATH`, `CCSYNC_WHISPER_*`,
`MUSIC_DB_PATH`, …; the base rig must now SET the two whisper keys or
transcription skips), the faster-whisper env is in-repo
(`broll/indexer/tools/make_whisper_env.*`), and `tools/Dockerfile.indexer-gpu`
packages both indexers (written, not built). `docs/INDEXERS.md`. The NAS's
`music.db` migrates to v3 on the first redeployed dashboard boot; the first
real drain has not been run.

---

### CR-21 — a declined NEW PROJECT prompt could come back after a companion restart — FIXED in repo 2026-08-17 (found by the integration pass), unshipped
`project_setup._record_asked` wrote the "already asked" map with
`write_text` (create-truncate-write-close), so a concurrent reader could see
zero bytes; `_load_asked` swallowed the `JSONDecodeError` and the whole map
came back empty — the popup returns for a project the editor already
declined (the same family as the 2026-07-25 recurring-popup incident). It
surfaced as one intermittent test failure during the 13-suite integration
run. Now temp-file + `os.replace`, like `identity.save_identity`; two tests
pin it.

### CR-22 — 0.8.0 upgraded a machine into "this machine isn't set up yet" and left no way out — FIXED in repo 2026-08-18, unshipped
Seen live on the base rig the morning after the 0.8.0 build. CR-5's licence
gate is correct — `_start_lanes()` refuses without a current
`~/.ccsync/eula_accepted.json` — but the ONLY thing that wrote that record was
the onboarding wizard, and **the wizard does not run on the path editors
upgrade by**: `upgrade.py` swaps the exe in place and restarts. So the new
build came up, refused to sync, and `tray._format_lane_line_from` rendered
that refusal as the generic *"NOT SYNCING (this machine isn't set up yet)"* on
all three lanes — a sentence that points at the admin, for a state only the
person at the keyboard can clear. A toast said the real reason; nothing in the
menu could act on it. Every editor taking the 0.8.0 offer would have landed
here, silently, one machine at a time.

Now the companion asks, showing the document it already bundles:
`popup.licence_dialog` (scrolling, verbatim `assets/EULA.md`, ACCEPT /
DECLINE — no Return binding, since this is the one dialog where a stray
keypress records a legal agreement), `app.prompt_licence_acceptance` once per
run three seconds after the tray starts, and a **tray item** *"► Accept the
licence agreement to start syncing…"* that is present exactly while the gate
is (in the menu fingerprint, or it would survive the click that cleared it —
UI-3's shape). ACCEPT calls `_start_lanes()` in the same breath, so syncing
resumes with no restart. A build with no bundled document refuses to record
anything rather than accept nothing (the gate itself still fails OPEN there,
per CR-5). The wizard remains the fresh-install path, and
`installer/windows_upgrade.ps1` now launches it (step 6) when a package
upgrade finds no current acceptance — skipped on `mode = "base"`, where
`tools\ship.cmd` runs that script at the end of every release and the rig's
config is hand-built. The package ships `EULA.md` beside `onboard.exe` so the
script can read the `<!-- EULA-VERSION -->` marker a frozen exe hides.

### CR-23 — item 10's de-branding took a fleet's logo and could only be given back machine by machine — FIXED in repo 2026-08-18, unshipped
The tray/window mark became `theme.PRODUCT_MARK_ASSET` with one escape hatch,
`$CCSYNC_BRAND_LOGO` — **machine environment**. Right for the vendor default
and wrong for the fleet already wearing its own logo: on upgrade every editor
silently swapped to the neutral mark, and getting the studio's back meant
setting an env var on every machine (in practice, a reinstall). The customer
noticed the same morning as CR-22, on the same build.

The mark now travels with the brand strings it belongs to: `brand_logo` in
`[site]`, published by `GET /api/v1/site` (additive to schema 1, blank = the
product's own), editable on the dashboard's Settings page with no container
`--recreate`, seeded at deploy by `DASH_SITE_BRAND_LOGO`. `theme.
brand_logo_override()` is now env → manifest → product mark; **the env var
still wins**, because an escape hatch a server can overrule is not one. A bare
name still selects a mark the build ships — `build.spec` keeps
`cc_mark_white.png` beside `ccsync_mark.png` for exactly this — and a manifest
naming a missing file falls back rather than failing, since a server can now
set it. `companion/tests/conftest.py` clears the env var for every test: a
developer's own branded rig was otherwise deciding what the suite measured.

---

## Open — residuals from the 2026-08-14 fix pass

### R16 — eight 08-14 findings deliberately not fixed
Each was investigated by its territory's agent and declined for cause; the
full reasoning lives in each finding's entry in `docs/bug-hunt-2026-08-14.md`.

Needs a live spike or real-media benchmark before any code change:
- **YTDL-WEB-5** (enrich re-fetches flat-search metadata) — the collapse
  would silently drop the availability gate, the BotCheckError tripwire and
  `upload_date`; needs a live yt-dlp session to establish what flat entries
  actually carry.
- **COMP-GUARD-8** (proactive MappedRoot canon) — MappedRoot is unproven in
  both directions and `ensure_media_storage` renumbers `GALLERY_FS_KEY`
  entries; needs a base-rig experiment.
- **BROLL-IDX-7** (fold frame extraction into the scene-detect decode) —
  crosses the status-gated `organised` stage boundary and most timestamps
  derive FROM the detection output; needs benchmarking, and `stage_frames`
  is already input-seek + marker-idempotent.

Two-sided designs that must land atomically (design written, not built):
- **BROLL-WEB-7** (incremental semantic-cache invalidation) — the web half
  alone reintroduces the BROLL-17/R2 staleness class, and the vocabulary
  half is unsound without per-token refcounting; the safe two-sided design
  (dirty-video generation ledger in `meta`) is in the b-roll agent's report
  inside the hunt doc's entry.

New subsystems, not patches:
- **SERVER-10** (rclone-backed music-data push) — new command + remote
  config + root-owned post-step; its concrete costs were reduced by
  SERVER-1/-5/-6 this pass. **SERVER-11** (image-based provisioning) — no
  proven build/delivery path from this fleet's infrastructure.

Architecture changes declined on the merits:
- **DASH-8** (polling → SSE) — verifier holed two premises; unweighed costs
  on the page whose failure mode is "nobody can tell whether footage syncs".
- **DASH-7**'s cache halves (pending devices are not stored anywhere to
  serve from; a TrueNAS roster TTL cache would stale the admin's own
  actions) — the real harm (one backend blip blanks the whole panel) WAS
  fixed: the two backends now fail independently.

Also carried from the pass: `resolve_bridge.bridge_activity()` (COMP-MEDIA-9)
is a new zero-I/O reader nothing surfaces yet — a tray status line or
reporter field would make a wedged fusionscript call visible without log
archaeology.

### R18 — requester-first downloads never engaged; the fleet ran the server path for two days without anyone noticing — FIXED in repo 2026-08-16 (companion 0.7.9 + dashboard env), unshipped
Read live on an editor's machine the morning after they took 0.7.8 (SSH,
`companion.log`, `127.0.0.1:8899`, the dashboard's fleet + ytdl APIs), while
chasing five symptoms they reported at once. What each turned out to be:

- **"Syncing 48 GB of Creator Profiles he already has"** — lane B's first
  pass after 0.7.4 → 0.7.8: 0.7.6's `+ /Youtube/**` pulling every YouTube
  original in the project (58 GB) down to him. Working as designed, and the
  design was wrong — see the fix below.
- **"Not showing on the dashboard"** — his reporter timed out 10:43–11:16
  (WinError 10060, around the upgrade/restart); it has reported cleanly since
  11:20. Transient.
- **"Videos land in F: not P:"** — on his machine P: *is* `\\localhost\CCSync_P`
  = `F:\Creators_Club`; the reveal opens the local-root spelling by design
  (a Mac has no drive letters). Not a defect.
- **"Weren't downloads supposed to happen locally?"** — they never once did.
  Every job `download_mode: server`, `claimed_by: null`, for **two
  independent reasons**: (a) the NAS dashboard had no `YTDL_LOCAL_DOWNLOAD=1`
  (`/ytdl/api/health` → `local_download: false`; the ship checklist named the
  step, `install_dashboard_app.py` never performed it), so the SPA never
  probed the companion; (b) his machine has **no ffmpeg** —
  `/ytdl/capabilities` → `ok:false, "ffmpeg is not installed"` (COMP-BROLL-5
  refusing correctly) — and nothing had ever shipped one to an editor.
  Invisible because the server path is the designed fallback and kept working.
- **Age-restricted clip fails ("Sign in to confirm your age")** — failed
  *server-side* (job 34). The NAS `cookies.txt` is present (`cookies: true`)
  but carries only the `__Secure-3P*` half of a session (no `SID`/`HSID`/
  `SSID`/`APISID`/`SAPISID`/`LOGIN_INFO`), and yt-dlp rewrites it on every
  run (mtime = job time). Whatever account it was exported from either is not
  age-verified or the export was partial. **FIXED both ways** (fix 7 + the
  operator note below): the NAS cookies.txt was re-exported and reinstalled,
  and the LOCAL executor now passes `--cookies` too (it used to pass none),
  so an editor who runs "Sign in to YouTube" downloads age-gated clips on
  their own machine — no server round trip.
- **"Open in Explorer opens the default folder"** — real, and every clip:
  `Popen(list)` quotes any argument containing a space, every path in this
  tree has one, so Explorer got `"/select,F:\...\Season 1\clip.mp4"` — a
  token starting with a quote, which it does not recognise as a switch and
  silently answers with Documents. Endpoint said ok:true, a window opened.
- **Music "+ Resolve" dead-ends "file not found — is the share mounted?"** —
  the library is not a synced folder any more than the b-roll archive is, and
  `music_server.build_send_response` had no on-demand fetch (b-roll's
  `/insert` got one 2026-08-11).
- **"Open dashboard" not opening** — `webbrowser.open()` returns False with
  no log line, so nothing distinguished "a tab opened and timed out" (the
  dashboard WAS unreachable from his box 10:43–11:16) from "nothing
  launched". His log's three `TrackPopupMenuEx returned 0, GetLastError=0`
  are `TPM_RETURNCMD` dismissals, not failures.
- His three local Syncthing folders carry 23 of 29 ignore lines and the
  sequencer's startup verify latched them "paused until a re-assert" — but
  they were never paused (0.7.4 left them running), so the claim in the log
  is wrong while the risk is nil (the six missing lines are the `.part`/
  `.ytdl` set the NAS now filters at source; the lane C turn re-asserts).
  Left as-is; verify it self-healed after his lane B pass.

FIXED, all in repo:
1. **`sidecar_tools.py`** (companion 0.7.9): a *pinned* static ffmpeg +
   ffprobe (eugeneware/ffmpeg-static `b6.1.1`) AND a deno (denoland/deno
   `v2.9.5`), each sha256 hardcoded per asset and verified against a real
   download, installed into the same tools dir as yt-dlp on the yt-dlp
   manager's daily thread, under the same opt-out. `ffmpeg_tools
   ._resolve_binary`/`ffmpeg_available` fall back to the managed ffmpeg
   behind PATH for the bare default `ffmpeg_path` only; the executor hands
   yt-dlp the deno by path. An editor's own ffmpeg/deno, or an explicit
   path, is never touched. capabilities() turns ok the moment ffmpeg lands;
   no restart, no config edit.
2. **`YTDL_LOCAL_DOWNLOAD=1`** set by `install_dashboard_app.py` and
   `dashboard/deploy/compose.yaml` (pinned equal by test_safety), so a
   redeploy can never drop it again.
3. **Lane B no longer pulls `/Youtube/**`** (owner's call: originals go UP
   only, other editors' clips are bandwidth). Editor-local originals the NAS
   lacks are now excluded rather than swept to trash (item 22's Youtube case
   is gone). `Youtube/<term>/Proxy/` still comes down. The reveal's not-here
   message says where the clip is instead of "has it synced here yet?".
4. **Explorer reveal**: `ytdl_server.windows_command_line` builds
   `explorer /select,"<path>"` by hand and `spawn()` hands Popen ONE string
   on win32 (verbatim to CreateProcess, no shell). Verified live on the base
   rig by reading the opened window's `Shell.Application` LocationURL, not
   by "a window appeared". A path containing `"` is refused (Windows names
   cannot), never escaped. Music's reveal shares the function.
5. **Music on-demand fetch**: `broll_fetch` takes a `remote_rel`
   (`Assets/Music`), `music_server.build_send_response` pulls the missing
   track down and answers `state:"downloading"` with progress; the music UI
   re-POSTs every 1.5 s until the send goes through. Same gate as b-roll
   (derived mount only, never a base rig, never another share).
6. `_open_dashboard` logs the attempt, logs when no browser launched, and
   tells the editor the URL in a toast.
7. **Signed-in LOCAL downloads (COMP-YTDL)**: measured that anonymous
   downloads reach 1080p with no JS runtime but a `--cookies` file makes
   every format vanish without one — hence the deno sidecar (fix 1). The
   executor sends `--cookies` from `ytdl_cookies.resolve()`: the
   `ytdl_cookies_file` config key, else the tray-written
   `~/.ccsync/youtube-cookies.txt`, else nothing. The tray's **"Sign in to
   YouTube (for downloads)…"** validates a browser-exported cookies.txt
   (Netscape header + real youtube.com session cookies; the `__Secure-3P*`-
   only logged-out shape is rejected — same shape as the NAS's own broken
   file) and saves it 0600. Proven end-to-end: the real `build_argv`'s
   command line passes the age gate (`Clay | 480p | age_limit=18`) with a
   managed deno + a signed-in cookies.txt on this residential IP, no
   PO-token provider. Deliberately a FILE not `--cookies-from-browser`
   (Chrome app-bound encryption; reading a live profile rotates the session).

Also this session, OPERATOR side (done, not code): the NAS `cookies.txt`
was re-exported from a signed-in age-verified session and installed
(uid 3000, 0600); `ggfhWx8h5Tg` — the clip that started this — now extracts
in-container. The old partial file is `cookies.txt.bak-20260816`.

Ship: `tools\ship.cmd` (dashboard deploy carries the flag; companion 0.7.9
publishes the sidecar + lane B + reveal + music + YouTube sign-in). An
editor's box gets ffmpeg+deno ~30 s after their tray takes 0.7.9; their next
YouTube job downloads locally, and age-gated clips work once they run "Sign
in to YouTube" with their own cookies.txt. **Still open after the ship:** Mac builds.

### R17 — ten clips whose proxies Resolve refuses, and R10 does not explain nine of them
Found 2026-08-15 reading the base rig's `companion.log` after the 0.7.8 ship:
**1,357** `proxy relink: Resolve refused …` WARNINGs between 2026-08-11 13:10
and 2026-08-15 07:05, over **10 distinct clips**, re-offered every ~120 s for
as long as Resolve was open.

**The retry loop itself is already closed** — COMP-MEDIA-5 (0.7.8) remembers
each refusal against the proxy's `(mtime, size)`, demotes the per-clip line to
DEBUG and prints one summary WARNING per pass. Those 1,357 lines are 0.7.7
behaviour and will not recur. What is still open is *why these ten are
refused*, because R10's answer does not cover nine of them.

All ten proxies come from the same batch: the one-off Energy Transition driver
run of 2026-08-11 13:10–14:04 (the archive one re-touched by the R10 sweep at
08-12 01:02). Measured with ffprobe, 2026-08-15:

- **Nine of ten** (the FF5 Energy Transition YouTube clips) have **no embedded
  timecode on either side**, identical `r_frame_rate`, identical `nb_frames`,
  matching duration, same `pix_fmt`, same stream layout — R10's "timecode-less
  source, nothing to mismatch" class, which the sweep skipped on purpose
  (2,152 of them). A **control** in the same tree is decisive: `…/typhoon
  powercuts/…[SZqTalujBTc].mp4` has the identical shape (640x480, 30000/1001,
  no timecode either side) and **links fine** — its proxy was written 08-14 by
  the ordinary `proxy_gen`. Nor is it the CJK names: the same log holds 54
  successful relinks, CJK ones among them. The only variable left standing is
  which encoder run produced the file.
- **One of ten** (`20250323_fx3_traffic_yu_ba_ba_1057.mp4`, ff3 archive) is a
  real timecode mismatch: source `03:40:27:12` (colon), preview
  `03:40:27;12` (semicolon) — the DF normalization R10's second half applies
  at 59.94. This is the one case where that rule can be wrong: it cannot tell
  "Sony printed a colon form for drop-frame material" (the case measured live
  on 08-12) from a genuinely non-drop-frame recording, and at 3h40m the two
  readings are thousands of frames apart. The sweep's "799 fixed, 0 failed"
  counted successful remuxes, not Resolve acceptances.

Two cheap experiments, both needing Resolve open on the rig, neither run yet:
re-encode one of the nine with 0.7.8's `proxy_gen` and re-link (if it
attaches, the 08-11 driver batch is the suspect and the repair is a re-encode
sweep over those 438); and remux the ff3 preview with the **colon** form and
re-link (if it attaches, `dropframe_normalized` needs a way to tell real NDF
material from Sony's colon-printed DF, and the 799 swept previews need
re-checking).

Cost while open: those ten clips edit without a proxy. Nothing else.

## Open — residuals from the 2026-08-11 fix pass

### R1 — the TrueNAS password rode `net use`'s argv — FIXED 2026-08-11 (afternoon)
`drive_swap.py` now maps P: via in-process `WNetAddConnection2W` (credentials
in call arguments, no argv, no console prompt to hang — the error-1223
constraint dissolves rather than being worked around) and persists via
`CredWriteW`. The 30 s ceiling survives on a daemon thread. Live-verified on
the base rig with a scratch target: the stored entry is byte-identical in
shape to what `cmdkey /add` wrote (`Domain:target=<host>`), so Explorer and
uncredentialed connects find it as before. Deliberate behaviour change:
error 1219 (session-credential conflict) no longer classifies as an auth
failure — the old localized-text match tripped it incidentally and looped a
login prompt into the same error. Still owed at ship time: one real
credentialed swap from an editor machine to confirm which error code the NAS
actually returns for "needs credentials" (5/86/1223/1326 are mapped), and
frozen-build DLL resolution per the verify-against-deployed rule.

### R2 — same-size re-index could serve stale semantic vectors — FIXED 2026-08-11 (afternoon)
Broll schema v10 adds a `meta` search-generation counter bumped in the same
transaction as every embeddings/search_norm/transcript write (web ingest AND
the indexer's sqlite backend), folded into the semantic and fuzzy cache keys
(count/high-water stay as belt and braces). Negative control ran: with the
generation neutered, exactly the two residual tests fail. The live
`E:\broll-queue\broll.db` is migrated to v10; the NAS copy migrates itself
on the next dashboard deploy's boot (same story as 009).

### R3 — 428 b-roll rows remain on the legacy sprite fallback — AUDITED, nothing to do
Audited 2026-08-11 afternoon: all 390 proxy-less rows are `skipped` rows
(the over-length duration cap — 156 ff3, 230 ff4, 4 mofa-disaster) that were
never proxied, never sprited, and never surface a scrub UI; none has ever had
a sheet on disk. The 38 with proxies are error/degenerate rows (sub-second,
audio-only, broken). No rebuild pass is warranted. `sprite_cell_h IS NULL`
stays the work-list query if any of them ever become real
(`broll/indexer/regen_sprites.py` is the sweep, idempotent).

### R4 — two OPS fixes unverified against the live NAS — VERIFIED 2026-08-11
Checked over SSH against the real box, no deploy involved:
- OPS-2 prune guard: the container's bind source appears in mountinfo as the
  ZFS-dataset-relative path (`/apps/ccsync-dashboard/app`, not
  `/mnt/tank/...`) — and the guard greps the BASENAME, which that line
  contains, so it works. Proven both ways as root on the live host: the
  running container's mount is visible to a `/proc/*/mountinfo` sweep (1
  process), and the existing unmounted `app.old.20260811090814`'s basename
  matches nothing (correctly prunable).
- OPS-8 staging: `mkdir + chown truenas_admin + chmod 700` of
  `<host-root>/staging` succeeds on this dataset (no aclmode=restricted
  refusal), and the unprivileged SSH user can write there. Cleaned up after.

### R5 — delete-protection pre-flight — VERIFIED AND ROLLED OUT NAS-SIDE 2026-08-11
The partial `PATCH {"ignoreDelete": true}` round-trips on the deployed NAS
Syncthing (GET confirms the flag, staggered versioning untouched), and it was
then applied to **all 9 NAS folders** (7 projects + both asset libraries) —
so the critical direction, an editor's slip deleting the NAS's authoritative
copy, is closed as of today with no code deployed. The collector's drift
repair keeps it asserted once the new dashboard ships. Still pending: editor
machines get their own flag from the companion's per-turn retrofit at the
fleet republish (verify one editor's folder then, per the doc); the base
rig runs no local Syncthing (nothing to flag there). Still open,
deliberately untouched: the staggered-versioning `maxAge` disagreement
(companion 30 d vs server/dashboard 365 d — pick one and reconcile).

### R6 — BROLL-16 overrode a documented decision — review it
`is_excluded_dir` is now case-insensitive. The old test pinned
case-SENSITIVITY as deliberate ("the NAS holds `youtube` and `Youtube` as
distinct folders"), but every configured share root today is a
case-insensitive Windows drive letter, so the premise no longer holds. If a
NAS-rooted (case-sensitive) share is ever configured, this flips back.

### R8 — the base rig's companion is still 0.6.1 — OPS-4 observed in the wild
Discovered 2026-08-11 while starting the Energy Transition proxy run:
`%LOCALAPPDATA%\ccsync\bin\ccsync-release.json` says **0.6.1** (built
2026-08-10), though the 4075b3c ship published 0.6.3 as CURRENT — i.e. the
exact OPS-4 failure (windows_upgrade fails, exits 0, relaunches the old exe,
ship prints complete). Consequences live on this machine right now: the
broken proxy muxer (its generator failure-capped all 1,046 gap clips
overnight and its queue reads 0), no `/music/send`/`/music/status`, none of
today's fixes. The Energy Transition proxies were therefore generated by a
one-off driver over the repo's fixed `encode_once` path (identical
artifacts; the companion's next scan simply sees them as covered). The next
`ship.cmd` — with the OPS-4 hard stop now in place — replaces this build and
clears the poisoned caps by restart; verify with `check_deploy_drift.ps1`.

### R7 — ytdl behavioural-JS tests need node
`ytdl/web/tests/test_static_app.py` runs the real `app.js` in a `node:vm`
shim; its 13 behavioural tests skip cleanly where node is absent (the 8
source-level assertions still run). Dev machines and any future CI should
have node so those don't skip silently — `run_all_tests.ps1` will show the
skips.

### R9 — many browser previews are 10-bit H.264 — pipeline FIXED, archive sweep DECLINED
Reported by a remote editor 2026-08-11 (evening): poster fine, clicked-into
player black, on Creators_Club clips. Cause: the indexer's `build_proxy`
never pinned a pixel format, so libx264 inherited the source's — and every
FX3/FX30 shoot is 10-bit, so those previews came out H.264 High 10 /
yuv420p10le, which browsers draw as a black rectangle (sampled 12 across 4
creators shares: 10 were 10-bit; Downloads are YouTube-sourced 8-bit and all
fine). Encoder now pins `-pix_fmt yuv420p`
(`broll/indexer/broll_index/ffmpeg_tools.py`, regression test cuts a proxy
from a 10-bit source and asserts 8-bit out). Dry-run measured the archive:
7,110 previews, **3,467 browser-hostile** — and not only under
Creators_Club/; plenty of 10-bit FX3 shots were filed under
Downloads/<category>/ by the archive build. **Admin declined the re-encode
sweep 2026-08-12** ("okay on Chrome"): playback relies on the browser
falling back to software decode, which current Chrome does. If a black
player comes back on some machine/browser, the prepared fix is
`broll/indexer/fix_10bit_proxies.py --apply` on the base rig (dry-run by
default; re-encodes from the adjacent top-slot original, atomic replace, DB
untouched, archive is under no sync lane so nothing fans out). NOT the
companion's proxy generator: its 10-bit HEVC editing proxies are for
Resolve, deliberate, untouched.

### R10 — archive previews can't attach as Resolve proxies (no timecode) — FIXED, sweep RUN 2026-08-12
Reported 2026-08-12: a b-roll insert landed from the correct archive path
but with Proxy: None. Diagnosed live against Resolve: scripted ImportMedia
never runs the adjacent-Proxy auto-attach, and an explicit LinkProxyMedia is
REFUSED — because Resolve validates the pairing and the preview carries no
embedded timecode while the camera original does (fps/frames/duration all
match; remuxing the same bytes with `-timecode 03:40:27;12` flipped the
identical link to accepted, in .mov and .mp4 alike — timecode is the
deciding factor, container irrelevant). Fixes: `build_proxy` now embeds the
source's timecode (`read_timecode` + `-timecode`); companion 0.7.4's insert
explicitly links `<dir>/Proxy/<stem>.*` after import, best-effort (a refusal
is logged, never fails the insert). SECOND half of the root cause (1643880):
Sony rtmd tags print colon (non-drop) forms for drop-frame material, and at
59.94 the colon reading is a different absolute frame — equally refused —
so both the encoder and the sweep normalize to the semicolon form at
29.97/59.94 (`dropframe_normalized`). The sweep
(`broll/indexer/fix_proxy_timecode.py --apply`, a `-c copy` container remux,
unrelated to the declined R9 re-encode) RAN 2026-08-12: 799 previews fixed,
0 failed; 4,046 already matched; 2,152 have timecode-less sources (YouTube —
nothing to mismatch); 113 have no unique top-slot sibling. End-to-end
verified live: the archive preview now links to its imported clip. Editors
need the 0.7.4 republish for the explicit link on insert.

### R11 — the Windows self-upgrade races its own single-instance mutex — FIXED in repo 2026-08-12, ships with 0.7.6
A remote editor's Windows machine was left with **no
companion at all** by a one-click update. Its log is the whole proof:

    00:34:53,950 upgrade: v0.7.3 launched; shutting down v0.7.0
    00:34:53,950 timeline watcher stopped
    00:34:55,034 another ccsync-companion is already running -- this instance is exiting

The second line is the CHILD. `upgrade.apply()` has to spawn the new build
before the old one exits (a failed spawn is what the rollback hangs off —
`upgrade.py` ~line 635), so for a second or two there really are two
companions. On posix the newcomer copes: `CCSYNC_REPLACES_PID` names the
predecessor and `app._acquire_lock_file()` waits up to
`PREDECESSOR_WAIT_SECONDS` for that exact pid to let go. **On Windows it does
not.** `acquire_single_instance()` reads `_replaced_pid()` only to drop it,
then returns False the moment `CreateMutexW` reports `ERROR_ALREADY_EXISTS`
— on the stated assumption (`upgrade.py` ~line 734) that "the named mutex is
released the instant we die and the child simply wins by timing". That is
backwards: the child reaches the guard ~1.1 s after being spawned, while the
parent is still tearing down lanes and holding the mutex. The child exits,
the parent finishes exiting, and nothing is left running. Nothing retries —
the Run-key autostart is logon-only — so the editor is silently offline until
the next reboot or a manual start.

It is a RACE, not a certainty: the same machine's 0.4.22 → 0.7.0 upgrade
earlier the same day survived it, and the base rig has never lost it. That is
why this has shipped several times unnoticed.

Fixed 2026-08-12 (companion 0.7.5, both halves of the sketch above):
- `app._acquire_mutex_win32()` — the win32 branch now keeps the
  `_replaced_pid()` value and, on `ERROR_ALREADY_EXISTS` during an upgrade
  hand-off, polls up to `PREDECESSOR_WAIT_SECONDS` re-trying `CreateMutexW`
  each pass. Deliberately NOT `_wait_for_predecessor()`'s liveness-only
  loop: `_pid_is_alive_win32` can read a dead process as alive (exit code
  259 + both fail-safe arms), so the wait is keyed on the mutex actually
  clearing; liveness only decides "the holder isn't our predecessor". Every
  probe handle is closed before waiting — our own handle would keep the
  named object alive forever. No hand-off pid → immediate refusal, exactly
  the old behaviour. The mutex-broken fallback now hands the already-popped
  pid to `_acquire_lock_file(replaces_pid=…)` instead of losing the wait to
  a second (empty) env pop.
- Belt and braces: `_default_spawn` returns the Popen and `apply()` watches
  it for `CHILD_TAKEOVER_GRACE_SECONDS` (2 s) — a child that dies inside the
  window rolls the swap back and keeps the old build running instead of
  standing down over a corpse.

Aftermath on that machine, worth knowing about:
- The editor tried to restart it by hand at 00:37:42 and got a **stale
  packaged build** — it logged `ccsync-companion v0.1.0 starting`, could not
  use the current v2 identity (`sign-in required`, `dashboard report skipped:
  no verified editor identity`) and was gone within 3 s. Prefetch shows it
  ran from a path used exactly once (`CCSYNC-COMPANION.EXE-6E2F19E6.pf`,
  distinct from the installed `…-BB78F76F.pf`) that no longer exists — most
  likely the July `CCSync_Editor_Package` opened straight out of its zip or
  out of the recycle bin (`C:\Users\user\Downloads\CCSync_Editor_Package.zip`
  is still there; the extracted folder is in the recycle bin, and the exe in
  it is a genuine v0.1.0 — its PYZ has `watcher`/`theme` and no
  `reporter`/`identity`/`upgrade`). Unresolved residual: that log block also
  contains lines only a post-0.2.0 build emits (`config OK:`, `sign-in
  required`, `timeline watcher started`, the reporter DEBUG), so the "v0.1.0"
  stamp and the code that ran do not match any commit here. Either two
  processes interleaved into `~/.ccsync/companion.log`, or a build exists in
  the wild whose `config.VERSION` was never bumped. Two lessons stand
  regardless: pre-guard builds (< 0.2.0) have **no** single-instance guard at
  all and will happily run alongside the real one, and every build shares the
  one log file, so a stray old exe corrupts the evidence.
- Resolved 2026-08-12 by installing **0.7.4** over SSH (exe + release
  manifest into `%LOCALAPPDATA%\ccsync\bin`, sha256 verified against
  `companion/dist`) and launching it into the console session via a throwaway
  `InteractiveToken` scheduled task — an SSH-spawned process lands in the
  network-logon session with no visible tray. It came up clean: identity
  intact, lanes and sequencer started, Resolve bridge connected.
  Note the CIM `*-ScheduledTask` cmdlets hang over that SSH logon; classic
  `schtasks /create /xml` works, and the XML's `UserId` must be the **SID**
  (`DOMAIN\user` fails with "No mapping between account names and security
  IDs was done").
- Both machines now have a Start Menu **CCSync** shortcut pointing at
  `%LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe`, so a lost companion is a
  Start-menu search away rather than a hunt for a stale exe.
- Still owed: 0.7.4 is NOT published to the dashboard upgrade channel, which
  still advertises 0.7.3 as current. Both machines are on 0.7.4, and
  `upgrade.py`'s deliberate "different, not newer" rule means they will be
  offered an "Install v0.7.3" downgrade until the channel is bumped.

### R15 — the empty Youtube folder: ytdl delivered json and corpses, never videos — FOUR FIXES, SHIPPED 2026-08-15 in 0.7.8
Investigated live on an editor's machine 2026-08-13 23:2x → 2026-08-14 (full
writeup: "The Empty Youtube Folder" artifact; hybrid redesign plan:
docs/YTDL_LOCAL_DOWNLOAD.md). One editor-visible symptom — every
`credits.json` and 540p preview present, zero videos, a growing pile of
`.part` files — decomposed into four independent defects:

1. **The ytdl page's project select reverts to position 1 on every load**
   (`app.js` rebuilt it fresh, ordered by the editor's dashboard sync
   positions, nothing remembered), so searches meant for Energy Transition
   filed 16 term folders under Creator Profiles. Fixed: last pick persisted
   in localStorage, restored only if the slug is still in the server's list
   (assigning a `<select>` a missing value silently selects nothing);
   ytdl/web suite 362.
2. **YouTube serving one format truncated failed the whole clip.** Video
   SAQBbd1Rxmo's f137 died at ~10 MB from BOTH the NAS's IP and the base
   rig's ("N bytes read, M more expected … Giving up after 10 retries")
   while f136 worked; five clips across the tree had a stalled `.part` and
   no deliverable anywhere. Fixed in `worker.py` (vendor file untouched —
   retry policy is the worker's): the truncation signature (both markers,
   DownloadError by name) triggers ONE retry a rung down via the
   downloader's own QUALITY_HEIGHTS, note recorded on the done row;
   transient 403s/bot checks never downgrade. Final failure now sweeps the
   clip's own `[id]`-bearing `.part`/`.ytdl` litter via the unified
   `_record_failure()`. All five stranded clips hand-recovered to the NAS
   the same night (two only had 720p left server-side).
3. **Syncthing replicated yt-dlp's in-flight files and the editor-side
   `ignoreDelete=True` retrofit (2026-08-11) made them immortal** —
   `.stignore` ignored rclone's `*.partial` but not `*.part`/`*.part-Frag*`/
   `*.ytdl`: 27 orphans, 1.6 GB, three days deep on that editor's disk (cleaned).
   Fixed three ways in lockstep — server/common.py, dashboard provision.py
   (the load-bearing copy: `collector._ensure_ignores` re-POSTs on ANY
   list difference, so a server-only fix would be stripped every provision
   cycle), companion syncthing_admin.py — plus a three-way cross-component
   pin. server 244, dashboard 425, companion 2752.
4. **The watcher's per-clip "missing on disk" DEBUG line rotated 5 MB of
   log every ~25 min** on a machine missing media (thousands of clips ×
   every poll), rotating away the very upgrade history the investigation
   needed. Fixed: per-watcher dedupe set (assignment-per-pass, so recovery
   re-arms and the set is bounded by the open timeline), one line per
   newly-missing path plus a per-pass count summary.

Delivery context, so the symptom reads right: NO lane carried Youtube
originals on his 0.7.4 build (Syncthing stignores video extensions by
design, lane B was Proxy-only until 8985571's `+ /Youtube/**` shipped in
0.7.6, lane A is up-only) — the fix existed a full day, published 12:40
2026-08-13, parked behind the notify-and-one-click upgrade he hadn't
clicked. The LNG folders (~9 GB, 86 clips) were hand-pulled to his machine
that night via his own rclone under schtasks; both folders verified equal
to the NAS.

All four shipped 2026-08-15: the dashboard deploy is `ship.cmd` step 1 and
the companion publish is step 2, so fix 3's two halves landed together (it
was INERT until both — the deployed collector strips the new ignore lines
every provision cycle until it is redeployed).

The NAS side needed no hand-work at all, and the "re-run
`setup_syncthing_folder.py` per existing project" this entry used to list as
owed was **never necessary**: the same exact-equality repair that would have
stripped a server-only fix pushes the dashboard's list instead, on every
existing folder, every provision cycle (`collector._ensure_ignores`).
Verified read-only 2026-08-16 against the live NAS Syncthing config API — 7
project folders, **0 missing** `(?i)**/*.part`, `(?i)**/*.part-Frag*` or
`(?i)**/*.ytdl`. Re-running the server script by hand is now only for a
folder the collector cannot see (no marker, or a project it refuses to
provision). **Still owed:** that editor (plus any other stale tray) accepting the
upgrade — the editor half lives in the companion's own `STIGNORE_LINES`,
re-asserted at startup and per turn, so it reaches a machine only when its
companion does.

### R14 — the BPG hand-off launched a generator that watched nothing, then never started it — FIXED, SHIPPED 2026-08-15 in 0.7.8
`bpg.py` opened the Blackmagic Proxy Generator whenever BRAW/R3D/CRM had no
proxy and deliberately touched neither its watch list ("that config is
yours") nor its window. Both halves were load-bearing, and on the base rig
both were empty:

- `watchFolderList=@Invalid()` — Qt's spelling of "no folders". BPG rewrites
  that file from memory on every exit, so a folder removed once is gone for
  good, and a watcher with no folders is a silent no-op. The rig launched it
  at 14:09, 15:26 and 18:13 on 2026-08-13 alone, against 6 BRAW clips that
  had had no proxy since 2026-05-20 (`…/Creator Profiles/Season 1/B-roll/
  Editor Added/<editor>/`), and the gap never moved.
- Even with folders, the window opens **Idle** with a **Start** button and the
  folders at "Waiting". There is no flag, env var or INI key for it.

Fixed: `proxy_scan` now reports `needs_resolve_dirs` (a count cannot tell a
watcher where to look), `bpg.ensure_watch_folders` seeds the list additively
before launch — user entries carried over as text, ancestors honoured, one
`.ccsync-backup`, capped, only while BPG is down since a running one would
overwrite the file — and `bpg.press_start` presses Start over UI Automation
(PowerShell + `UIAutomationClient`, the CIM probe's precedent). The control's
NAME is its state, "Start"/"Stop", so we press only when it says "Start" and
never press Stop; `InvokePattern.Invoke()` works where `TogglePattern.Toggle()`
silently does not. Both halves have config opt-outs
(`bpg_manage_watch_folders`, `bpg_autostart`, on by default). Live-verified
end to end on the rig the same evening: all 6 BRAW clips now have proxies.

**Open decision — the duplicate-encode collateral.** BPG watches folders, not
files, and recognises only its own `Proxy/<stem>.mov`; it re-encoded 172 clips
in that folder that the companion had already proxied as `.mp4` (the 161 `.mp4`
duplicates were deleted afterwards, keeping BPG's `.mov` side, which is what
BPG itself tracks). The candidate fix is to make `proxy_scan.GENERATED_EXT`
`.mov` (with `-f mov` in both `ffmpeg_tools` builders) so BPG treats companion
output as done and only ever encodes what ffmpeg cannot decode. It does not
touch the b-roll browser, which serves the INDEXER's 540p H.264 `.mp4`
(`broll/web/app/routes_media.py:44-47`, `Content-Type` hardcoded `video/mp4`)
from the archive tree and never a `proxy_gen` file — and `archive_path` may
already be `.mov` today by design (`broll/indexer/build_archive.py:181-183`).
Not taken yet: it changes what every machine in the fleet writes.

### R13 — a half-failed ship had no way to finish itself — FIXED in repo 2026-08-13
The 0.7.6 ship published the companion, then failed on the installer:
`onboard.exe` bundles the companion exe, so a companion release changes the
installer's bytes by itself, and 1.0.24 was already published — the server
kept the old build and `build_editor_package.ps1` correctly called that a
failed run (the 1.0.21 rule, third time it has bitten). What it left behind
had no supported exit: the fix is installer-only, but `ship.cmd`'s fail-fast
gate hard-stops on "companion 0.7.6 is ALREADY published", and
`build_editor_package.ps1` publishes the companion FIRST and exited 1 on any
409 — including a 409 whose bytes are identical, which is exactly what a
half-failed ship guarantees.

- Installer version bumped 1.0.24 → 1.0.25 across all four sites.
- The companion 409 now compares the server's sha256 against the local exe,
  the same way the installer upload has always done: identical bytes → say
  so and carry on to the installer; different bytes (or unknown) → the old
  hard stop, since the fleet would silently keep the old build. `-MakeCurrent`
  cannot ride a skipped upload, so it says to confirm CURRENT by hand.

`ship.cmd`'s own gate is deliberately NOT relaxed — a full ship builds a new
companion, so re-shipping a published version is a real error there. Recovery
runs the individual script, which is what it is for.

### R12 — the Energy Transition path-canon incident — FIXED in repo 2026-08-12 (evening), unshipped
Two hundred–plus clips in the shared "Energy Transition" project carried
machine-private paths with zero warnings from anyone: 47 imported on the base
rig via `W:\Creators_Club\...`, 158 imported by the remote editor from his
`F:\Creators_Club\...\Youtube\<term>\Proxy\*.mp4` (the 540p previews were the
ONLY rendition any sync lane ever delivered to him), plus strays on `Z:\`,
`I:\` and a Desktop. All relinked to `P:\` by script the same day; the repo
fixes that stop it recurring, all with tests, all green (2646 + 81 + 77):

- `resolve_bridge.replace_clip` now verifies by re-reading File Path with
  retries — ReplaceClip returns None even on success, so the old code
  misreported every success (resolve-relink's relink_one pattern).
- Lane B also pulls `/Youtube/**` (originals + credits sidecars) down to
  editors; `*.part`/`*.ytdl` debris excluded. youtube_import skips a root
  `Youtube/Proxy/` dir instead of importing it as a term named "Proxy".
- Canonicalize-at-import: youtube_import, the b-roll insert and the music
  worker now ReplaceClip freshly imported clips to the `P:\` spelling
  (identity no-op on the base rig); their dedupe folds both spellings.
- `paths.classify_path` grew NON_CANONICAL (in-tree, local spelling →
  auto-relinked, once per path) and FOREIGN (another machine's path, not on
  disk → tray warn-once; MISSING stays reserved for canonical not-yet-synced
  files). Wired into the timeline watcher AND a new classification pass on
  the existing 120 s media-tree sweep — bins are no longer a blind spot.
- Stale-fusionscript recovery: when the Resolve the companion had connected
  to exits, the companion restarts itself (upgrade.restart_self — the R11
  spawn/hand-off machinery without the swap; `bridge_auto_restart = false`
  opts out). Left in place, the stale client wedges every NEW Resolve
  session's scripting server for every client — proven live on the remote
  editor's rig across three Resolve restarts, healed only by
  companion-then-Resolve restart order. NO_SCRIPTING_MESSAGE now gives that
  order.
- Web UIs no longer assert "companion not running" on a rejected fetch (a
  Chrome local-network-permission block on the http:// dashboard origin is
  indistinguishable); they hedge and offer the `127.0.0.1:8899/status`
  self-test. The music UI's inverted error mapping fixed.

Not addressed here: serving the dashboard over HTTPS (makes the browser's
local-network permission grantable/durable), and routing inserts through the
dashboard's companion-poll channel instead of browser→loopback — both remain
open options if the block recurs. Ships with the next companion release;
remember the upgrade channel still advertises 0.7.3 (R11's residual).

---

## Carryover — unchanged from before the 2026-08-11 hunt

Full write-ups in `docs/bug-hunt-2026-08.md` and
`docs/macos-first-run-2026-08-05.md`.

- **Proxy generator, live-attach proof (was item 23) — still the SHIP-BLOCKER
  for the editor proxy rollout.** The four-point Resolve proof (HEVC Main-10 +
  `hvc1` + source timecode; adjacent-`Proxy/` auto-link; `LinkProxyMedia`
  over a stale absolute path; byte-flag parity with the b-roll indexer) has
  still not been run on the base rig. MED-1/MED-4 were exactly the class of
  gap this proof exists to catch — and both were real.
- **Lane B can sweep an editor-generated proxy into `.ccsync-trash` (was item
  22)** — tracked risk, mitigated by the tri-state `proxy_gen_enabled`
  default; revisit only if editor-side generation is ever wanted.
- **AppleDouble sweep (was item 12 residual)** — the `._*` excludes are
  fixed, but the one-time NAS sweep for already-uploaded sidecars is still
  owed.
- **macOS code-signing (was item 16)** — ad-hoc signature means the TCC/Full
  Disk Access grant dies on every self-upgrade; a Developer ID identity (a
  purchase) is the real fix.
- **macOS runtime validation backlog** — `installer/MACOS_FIRST_RUN.md`
  §A7–H unrun; wizard bundle never built on a Mac; onboarding suite needs a
  darwin run; lane C `.stfolder` behaviour untested there; MAC-12's wedged
  FSEvents stream on a Mac editor's external disk still needs hands on the
  machine.
- **Bench Syncthing 1.x (was item 1 residual)** — v1 argv test-pinned but
  never live-verified.
- **Mac builds owed — now carrying the whole 2026-08-11 fix pass.** Until
  `release_macos.sh --publish --make-current` and
  `build_onboard_macos.sh --publish --make-current` run on a Mac, Mac
  editors have none of today's fixes (including both UI criticals, which are
  worst on darwin), and `/music/send` + `/music/status` still 404 on every
  deployed companion until the fleet republish.
- **NAS hygiene (was item 7 incidental)** — `owen_laptop` in the `editors`
  group still looks like a machine-shaped account; rename if it is one.
