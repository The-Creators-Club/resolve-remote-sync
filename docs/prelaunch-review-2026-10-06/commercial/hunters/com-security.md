# Pre-launch commercial review - lens `com-security` (2026-10-06)

Security posture as a buyer's security questionnaire would probe it. Working
tree at HEAD 08b40eb plus the uncommitted changes, read-only.

**Covered (read end to end):** `dashboard/src/ccsync_dashboard/app.py` (login_gate,
csrf_gate, exempt lists, open paths), `auth.py` (verify_credentials, tokens,
cookie flags, plaintext-login refusal, password floor), `local_users.py`
(scrypt hashing), `oidc.py` (claims, id_token verification, fleet membership),
`api.py` (resolve_companion_credential, `_account_refusal`, `/verify`,
selection read/write/untick gates, package publish/current/roll-fleet-back,
report-token mint/revoke, create-user), `ai_providers.py` (CLI path route),
`db.audit` and every caller, `dashboard_update.py` header,
`broll/web/app/routes_share.py`, `dashboard/deploy/compose*.yaml`,
`server/install_dashboard_app.py` credential handling, `tools/release_key.py`,
`tools/publish_latest.py`, `companion/.../release_pubkey.py`,
`.github/workflows/*.yml`, `docs/COMMERCIAL_READINESS.md`, `docs/INSTALL.md`,
`docs/CLIENT_FOLDERS.md` §3, `docs/legal/EULA.md`/`PRIVACY.md`, KNOWN_BUGS
CR-6/7/8/9/18.

**Not covered:** the companion loopback (CR-7, verified by earlier hunts), the
mounted SPAs' own route-level authz, the Cards sub-app, macOS signing, the
Android app, a live probe of Tailscale Funnel path handling, the NAS-side
editor account model (`setup_editor_account.py`) beyond its docs.

## SOC2-lite answer sheet as the code stands today

| Question a buyer asks | Honest answer today |
|---|---|
| SSO / SAML / OIDC? | OIDC code exists (`oidc.py`), never run against a real IdP; default claim does not fit Entra/Okta/Google; the companion still signs in with a NAS password. No SAML. |
| MFA? | **No**, for any role, in any auth mode. |
| Password policy? | Local mode: 12-char minimum, scrypt, throttle with backoff. SMB mode: whatever the NAS enforces. No breach-list check. |
| Session management? | Server-side revocable sessions, 12 h idle / 7 d absolute, HttpOnly, SameSite=Lax, Secure only behind TLS. Good. |
| CSRF? | Synchroniser token on dashboard pages; the three SPAs and several admin JSON routes rely on SameSite=Lax only (com-security-7). |
| Encryption in transit? | Tailnet: WireGuard. **LAN listener is always on and is plain HTTP**; passwords and tokens cross it in clear (com-security-5). |
| Encryption at rest? | No. SQLite, API keys, SMTP password are 0600 plaintext files on the NAS dataset; relies on NAS disk encryption, which we do not configure. |
| Secrets management? | Env vars in the container (`docker inspect`-readable), NAS admin password there by default (com-security-6). Base rig: DPAPI. |
| Least privilege to infrastructure? | Scoped TrueNAS key exists but is optional; DSM always holds the admin password and requires 2FA OFF on that admin. |
| Audit logging? | `fleet_audit` for many admin actions; NOT for sign-ins, admin creation, token mint/revoke, AI keys. Mutable, no retention, no export, no SIEM forward (com-security-9). |
| Offboarding? | Works only if the admin uses the dashboard's suspend/delete. Removing a person at the NAS or IdP does not stop their machine (com-security-4). |
| Software supply chain? | Hash-pinned lockfiles (good), Ed25519-signed release records (good). One unencrypted signing key on an always-online workstation, no Authenticode/notarisation, CI actions pinned by mutable tag, no CVE scanning, no SBOM (com-security-1, -2). |
| Vulnerability disclosure / PSIRT? | A generic contact address in the EULA. No SECURITY.md, no advisory channel, no SLA (com-security-10). |
| Pen test? | Never. Internal AI-driven bug hunts only. |
| Incident response / breach notification? | No written procedure. |
| Public internet exposure? | Optional Funnel for client share links, path-scoped; served by the same single process as the fleet dashboard, no rate limit (com-security-11). |

---

### com-security-1 - One unencrypted signing key, on an always-online workstation, controls code execution at every customer
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `tools/release_key.py:1-27,225-245` (no passphrase, by design), `companion/src/ccsync_companion/release_pubkey.py:40-42` (exactly ONE baked key), `tools/publish_latest.py:18-27` ("CI builds, this rig signs"), `dashboard/src/ccsync_dashboard/dashboard_update.py:1-15` (dashboard code updates verify the same baked key), `dashboard/src/ccsync_dashboard/release_feed.py:1002,1089-1098` (feed auto-publish), KNOWN_BUGS CR-6 ("decide whether to keep it before the first customer ship").
- **What:** The Ed25519 seed at `%USERPROFILE%\.ccsync-release\release.key` is a plaintext base64 line. It signs companion builds, onboard installers and dashboard code bundles for the vendor feed every customer reads. Customer dashboards can auto-publish from that feed, and companions with `auto_update` install from it unattended. Only one public key is baked in. There is no second, offline key to rotate to, and no revocation path. The rig that holds the key is also the studio's daily workstation and runs autonomous coding agents with full shell access. The "keep or rotate before the first customer ship" decision in CR-6 is still open, and no Authenticode or Developer ID certificate exists.
- **Scenario:** Malware, a malicious dependency in any project on that rig, or an agent session with a poisoned prompt reads one file. The attacker signs a companion that does what they like and also bakes out the vendor key. That build reaches every customer's editors through auto-update or the next admin click, and its signature check passes. The vendor has no recovery short of a reinstall on every machine at every customer.
- **Recommendation:** Before the first sale: (1) generate a NEW key on a hardware token (YubiKey PIV / OpenPGP Ed25519, or a cloud KMS key with an approval step) that never exists as a file, and retire the 2026-08-17 key it replaces in the overlap release. (2) Bake a second "recovery" public key whose private half is kept offline in a safe, so a compromise of the signing key can be answered without reinstalling everything. (3) Sign on a machine that does not run agents or browse. (4) Buy the OV/EV Authenticode certificate and Apple Developer ID (owner purchase), so that EDR tools at customer sites do not quarantine the companion. Owner decision plus purchase. About a day of engineering.
- **Known:** CR-6 (open: certificates not bought, key keep/rotate undecided).

### com-security-2 - The CI build that this rig signs is not provenance-checked, its actions are pinned by mutable tags, and nothing scans dependencies for CVEs
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `.github/workflows/*.yml` (`actions/checkout@v4`, `setup-python@v5`, `upload-artifact@v4`, `docker/build-push-action@v7`, `sigstore/cosign-installer@v3`, etc., all tag-pinned), `tools/publish_latest.py` (checks branch ancestry, then signs the downloaded artefact), no `.github/dependabot.yml`, no pip-audit/osv/trivy/codeql anywhere in `.github` or `tools/`.
- **What:** The companion exe the vendor signs is built on a hosted runner. That build runs third-party actions whose tags can be moved, the tj-actions/changed-files incident pattern. `publish_latest.py` confirms the run's commit is on `main` (good). It has no way to confirm that the bytes came from that commit unmodified: there is no reproducible build, no SLSA/GitHub attestation check, and no rebuild-and-compare. The signature then lends those bytes full trust. Separately, eleven hash-pinned lockfiles keep builds reproducible but freeze them: nothing alerts when a pinned version (starlette, jinja2, cryptography, pyjwt, paramiko, pillow, the rclone/Syncthing/ffmpeg/yt-dlp sidecars) gets a CVE. No SBOM is produced either, and enterprise buyers increasingly ask for one.
- **Scenario:** An upstream action tag is repointed to a payload that patches the PyInstaller output. CI goes green, `publish_latest` sees a green run on `main`, and the owner signs and ships it to every customer.
- **Recommendation:** Pin every action to a full commit SHA (Dependabot can keep them current). Emit `actions/attest-build-provenance` in the release workflows and have `publish_latest.py` verify it (`gh attestation verify`) before signing. Add a weekly `pip-audit`/osv-scanner job over every `requirements.lock`, plus Dependabot security alerts on the GitHub repo. Generate a CycloneDX SBOM per release (`cyclonedx-py` over the lock) and publish it beside the artefact. Engineering, a few days.
- **Known:** not recorded.

### com-security-3 - No MFA for anyone, and the SSO path is unproven and does not fit the common IdPs
- **Severity:** high
- **Confidence:** CONFIRMED (absence of MFA; OIDC default claim); PLAUSIBLE (IdP-specific behaviour)
- **Where:** `dashboard/src/ccsync_dashboard/auth.py:142-180` (`AUTH_METHODS = ("smb","oidc","local")`, password only), `oidc.py:12-15,280-312` (default `preferred_username`, refuses an `@`), `api.py:2405-2433` (`/api/v1/verify` calls `verify_credentials`, which for `oidc` is an SMB password probe), `docs/COMMERCIAL_READINESS.md` item 12 ("never pointed at a real IdP").
- **What:** No auth mode has a second factor: no TOTP, no WebAuthn. That includes the admin, who can push fleet updates, roll the fleet back, delete users, read every editor's reports, and set an executable path the container runs (com-security-6). OIDC has unit tests against an in-process IdP only. Its default username claim is `preferred_username`, but Entra ID puts the UPN there and Okta puts the email, and `username_from_claims` refuses anything containing `@`. So on the two most common enterprise IdPs, SSO does not work until someone maps a custom claim. Google publishes no `preferred_username` at all. Even with SSO working, the companion tray signs in through `/api/v1/verify` with a NAS password, so every editor still needs a NAS password and sends it over the LAN (com-security-5).
- **Scenario:** A buyer's questionnaire asks "MFA enforced for administrative access?" and "SSO with our Entra tenant?". The honest answers are no, and "untested, needs a custom claim".
- **Recommendation:** Add TOTP (RFC 6238, stdlib-only) for local accounts, required for admins, with recovery codes. Under OIDC, defer MFA to the IdP and say so. Run OIDC once against real Entra, Okta and Google tenants and ship a documented claim mapping for each. Key the identity on `sub` (stored per user) rather than a mutable display claim. Give the companion a device-code / browser sign-in under OIDC so editors never type a NAS password. Engineering, 1-2 weeks.
- **Known:** COMMERCIAL_READINESS item 12 (OIDC "never pointed at a real IdP"); MFA not recorded.

### com-security-4 - Offboarding: removing a person at the NAS or the IdP does not stop their computer
- **Severity:** high
- **Confidence:** CONFIRMED (fleet API); PLAUSIBLE (Syncthing shares keep flowing)
- **Where:** `dashboard/src/ccsync_dashboard/api.py:238-272` (`_account_refusal`: in smb/oidc mode only a dashboard *suspension* refuses; "this dashboard has no disabled flag for it"), `api.py:182-204` (`resolve_companion_credential`: shared token accepted), `api.py:2433-2450` (`/verify` hands every verified editor the SHARED report token), `auth.py:74,375-391` (`IDENTITY_TTL_SECONDS` = 100 years, "no server-side row to revoke"), `settings.py:135` (`shared_report_token_enabled = True` by default).
- **What:** The default credential pair on a new site is the site-wide shared report token, handed to every editor at sign-in, plus a never-expiring HMAC identity token. In smb mode (the default `DASH_AUTH_METHOD`) and in oidc mode, nothing checks that the person still exists. Deleting their NAS account, or disabling them in the IdP, leaves `/api/v1/report`, the selection read, the untick and the fleet job routes all accepting their machine. Their plan stays in `selections`, so the enforce cycle presumably keeps their Syncthing device shared (PLAUSIBLE, not traced). Access stops only if the admin also presses SUSPEND or DELETE on the dashboard, mints per-editor tokens site-wide and turns off the shared one, or rotates `DASH_SESSION_SECRET`, which signs the whole fleet out. A browser session survives IdP disablement for up to 7 days.
- **Scenario:** A freelancer's contract ends. IT disables them in Entra and deletes the NAS account, the standard leaver checklist. Their laptop keeps reporting, and the footage on it stays shared, until someone remembers the dashboard has its own off switch.
- **Recommendation:** (1) New installs default to per-editor `cce1` tokens minted at `/verify`, with no shared token (`DASH_SHARED_REPORT_TOKEN_ENABLED=0` for any site that never had one). (2) Run a periodic reconciliation: an editor absent from the NAS user list or the `editors` group (smb), or absent from the IdP via SCIM or a short OIDC re-auth window (oidc), is auto-suspended and an alert is raised. (3) Make identity tokens revocable per user (a per-user generation counter in the HMAC payload). (4) Write the leaver procedure down in the admin guide. Engineering about a week, plus a doc.
- **Known:** CR-18 (per-editor tokens built; shared token still default-on), CR-86 (identity tokens made non-expiring on purpose).

### com-security-5 - Every deployment publishes the dashboard on the LAN over plain HTTP; passwords and fleet tokens cross it in clear
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `server/install_dashboard_app.py:2401` (`DASH_BIND_LAN` is `require_site_value`, i.e. mandatory), `dashboard/deploy/compose.yaml:493-506`, `auth.py:562-584` (`cookie_secure=auto` = off on http), `auth.py:105-139` (in smb mode the dashboard password IS the editor's NAS/SMB password), `docs/INSTALL.md:40-48` ("then the LAN is the perimeter - say so out loud").
- **What:** Tailscale traffic is WireGuard-encrypted. The LAN listener is not, and it is always present. In smb mode, the login form and the companion's `/verify` carry the editor's NAS password, which also opens SMB and SFTP to the tree. Session cookies go without `Secure`. The companion's `X-CCSync-Token` and identity token go on every report. Anyone on a shared studio LAN or guest Wi-Fi, or with one compromised IoT device, can collect working NAS credentials passively.
- **Scenario:** A coworking-space studio. One laptop on the same VLAN runs a packet capture for a day and comes away with every editor's NAS password and the admin's session.
- **Recommendation:** Make TLS the default on the LAN as well: either Tailscale Serve only (drop the LAN bind for remote-editor sites), or a Caddy sidecar with an internal CA whose root the wizard installs. Make the LAN bind opt-in with a dashboard banner while it is plain HTTP. Never send an SMB password over a plaintext socket: refuse `/login` and `/verify` on a non-TLS, non-tailnet peer unless the site sets an explicit "I accept plaintext LAN" flag. Engineering about a week. Product decision: whether a LAN-only, no-Tailscale deployment remains a supported SKU at all.
- **Known:** COMMERCIAL_READINESS item 6 / CR-8 (mechanism built; plaintext LAN remains the default).

### com-security-6 - The container holds a NAS root-equivalent credential by default, and a dashboard admin can make the container execute a binary
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** `server/install_dashboard_app.py:2627-2648` (`TRUENAS_PW` always written; the API key is optional), `:5306-5320` (a NOTE, not a refusal, when no scoped key), `:5325-5335` (`TRUENAS_VERIFY_SSL` defaults to `0`), `docs/INSTALL.md:32-34` (DSM: the admin account must have **2FA off**, and DSM has no API key so always holds the password), `dashboard/src/ccsync_dashboard/ai_providers.py:1176-1205` (admin-set executable path, probed via `subprocess.run` at `:611`), `cli_tools.py` (admin-triggered download-and-run of a CLI).
- **What:** COMMERCIAL_READINESS item 6 asked for the scoped key and CA pinning to become mandatory. They are optional, and the default deploy writes the NAS admin password into the container env, readable by `docker inspect` and by any code execution inside. On Synology there is no alternative, and the install additionally requires 2FA to be disabled on a NAS administrator. Inside the product, a dashboard admin is one feature switch (`ai_cli_providers`, settable from Settings) and one typed path away from the container running an arbitrary existing executable. Combined with password-only admin login over LAN HTTP (com-security-3, -5), a phished or sniffed dashboard admin session becomes NAS root, so every customer's footage is exposed.
- **Scenario:** A buyer's security reviewer asks "what is the blast radius of a compromised application admin?" The answer is the whole NAS, including the parts that have nothing to do with this product.
- **Recommendation:** Make `TRUENAS_API_KEY` mandatory on TrueNAS: refuse to deploy without it, keeping the password only for the deploy-time SSH session, never in the container env. On DSM, use a dedicated non-admin service account where the API allows, and document the residual risk in the security sheet. Default `TRUENAS_VERIFY_SSL` to a pinned cert fingerprint captured at install. Restrict CLI paths to an allow-listed directory (`<data>/tools/`), and audit the setting (com-security-9). Product decision: state in the EULA and security docs that a dashboard admin is a NAS-privileged role.
- **Known:** COMMERCIAL_READINESS item 6 / CR-9 (built as optional; never made mandatory).

### com-security-7 - Admin and plan-changing routes skip both the CSRF token and the Origin check
- **Severity:** medium
- **Confidence:** CONFIRMED (code path); PLAUSIBLE (practical exploit needs a same-site page)
- **Where:** `dashboard/src/ccsync_dashboard/app.py:222-235,1079-1085` (`_CSRF_EXEMPT_PREFIXES = ("/api/v1/selection/", "/api/v1/admin/packages/", "/broll/", "/music/", "/ytdl/")`, which return before `_origin_mismatch` runs); `api.py:7091` (`POST /admin/packages/{p}/{v}/current`) and `api.py:7281` (`POST .../roll-fleet-back`), both session-authenticated through `_require_admin` with no body; `api.py:2848,2938` (selection PUT/DELETE accept a session).
- **What:** The exemption comment justifies these prefixes as bearer-token routes, and it is true for the companion. But the same routes also accept the admin's session cookie, and on that path neither the synchroniser token nor the Origin check runs (the Cards mount gets the Origin check, these do not). `roll-fleet-back` and `current` take only query parameters, so a plain HTML `<form method=POST>` triggers them. SameSite=Lax blocks a cross-*site* attacker, but not a same-site one: any other web app on the NAS's address on another port (TrueNAS apps, a media server), or any page under the customer's `<tailnet>.ts.net`, including a Funnel'd node.
- **Scenario:** An XSS in another app hosted on the same NAS IP auto-submits a form to `http://nas:8480/api/v1/admin/packages/windows/<old>/roll-fleet-back` while the admin is signed in, and the fleet is pushed back to an older signed build.
- **Recommendation:** In `csrf_gate`, when a request on an exempt path carries the session cookie (`auth.session_is_tracked`), apply `_origin_mismatch` and the token check exactly as for any other route. Exemption should depend on the credential presented, not the path. Then finish the SPA header work KNOWN_BUGS CR-8 already lists. Hours.
- **Known:** CR-8 records the three SPAs as exempt; the admin/package and selection session path is not recorded.

### com-security-8 - No security response headers anywhere
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** repo-wide grep: no `Content-Security-Policy`, `X-Frame-Options`/`frame-ancestors`, `X-Content-Type-Options` or `Strict-Transport-Security` in `dashboard/src`, `broll/web/app`, `music/web`, `ytdl/web`; only `routes_share.py:63-67` sets Referrer-Policy/X-Robots-Tag.
- **What:** The dashboard, the four SPAs and the public share viewer send none of the baseline headers a scanner (OWASP ZAP, Qualys, any pen tester) reports in its first five minutes. There is no clickjacking defence on admin pages and no nosniff on media and uploaded files the apps serve. Behind Tailscale Serve there is no HSTS, and there is no CSP to limit the impact of any future XSS in templates that render editor-controlled strings (clip titles, project names, display names).
- **Scenario:** The first external pen-test report a buyer commissions opens with five "missing header" findings, which reads as an immature product even if each one is low on its own.
- **Recommendation:** One middleware in `app.py` (covering the mounts too): `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` / `frame-ancestors 'none'` (check that the Cards and SPA embeds do not need framing), `Referrer-Policy: same-origin`, HSTS when `request_is_https`, and a CSP that starts in report-only mode and is then tightened. The public share prefix gets the strictest set. A day.
- **Known:** not recorded.

### com-security-9 - The audit trail misses the security events a buyer asks for, and it is mutable and unexported
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `db.audit` callers (grep): no row for sign-in success/failure (`api.py:2262-2290`, `ui.py:1019`), admin account creation incl. role (`api.py:4588-4618`, `ui.py:3075-3100`, `setup_api.py:88`), per-editor token mint/revoke (`api.py:5568-5612`, a `log.info` only), AI key set/delete, CLI path, CLI install (`ai_providers.py:1112-1205`), or OIDC admin-by-claim grants (`oidc.py:499-505`). `db.py:9879` rewrites `fleet_audit.actor` on erasure. `run.sh:547-551`: the access log is off unless `DASH_ACCESS_LOG=1`.
- **What:** The ledger is good for fleet operations, but it cannot answer "who signed in as admin last Tuesday", "who created this admin", or "who minted the token that machine used". It lives in the same SQLite file the app writes, with no retention policy and no append-only guarantee. There is no export or syslog/webhook forwarding to a customer SIEM. The GDPR erasure path rewriting the actor is defensible, but it must be documented as such.
- **Scenario:** A customer's incident: an unknown admin pushed a rollback. The investigation finds the `package.roll_fleet_back` row naming a user it does not recognise, but no record of when that user was made an admin, by whom, or from which IP they signed in.
- **Recommendation:** Audit `auth.login_ok` / `auth.login_failed` (username, IP, method), `user.create` (role), `user.role_change`, `report_token.mint` / `.revoke`, `ai.key_set` / `.key_clear` / `.cli_path` / `.cli_install`, `oidc.admin_claim`, and `setup.admin_created`. Add an admin CSV/JSON export and an optional syslog/https sink (alerts_sink already exists). Publish a retention default. Days.
- **Known:** not recorded.

### com-security-10 - No vulnerability disclosure process, no pen test, no incident-response or breach-notification procedure
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** no `SECURITY.md` in the repo or `.github/`; `docs/legal/EULA.md:206-207` (security reports go to the general `contact@` address); `docs/legal/PRIVACY.md:103-110` (promises breach notification "without undue delay" in support cases, with no procedure behind it); no threat-model document (the term appears only in passing in RELEASE_FEED/SECRETS/ZERO_TOUCH docs); `package.retract` exists (`db.py:4665`) but there is no customer-facing advisory channel.
- **What:** A vendor selling software that runs with NAS privileges and self-updates on customer machines will be asked for: a security contact and PGP key, a disclosure policy with response SLAs, a description of how customers learn about vulnerabilities (advisories, CVE assignment), the last pen-test date and summary, an incident-response plan with GDPR Art. 33-style notification timelines, and a filled questionnaire (CAIQ-lite / SIG-lite). None of these exist.
- **Scenario:** The first procurement team sends a 60-question vendor security questionnaire, and the sale stalls for weeks while the answers are invented.
- **Recommendation:** Owner and counsel produce: `SECURITY.md` plus `/.well-known/security.txt` on the vendor site (dedicated `security@` mailbox, response SLA), a one-page IR and breach-notification procedure, and a security overview PDF (architecture, data flows, the answer sheet at the top of this file, corrected after the fixes). Engineering adds an "advisory" field to the signed feed so dashboards can show a vendor security notice. Commission one external pen test of the dashboard plus companion loopback before the first enterprise sale (a budget decision for the owner).
- **Known:** not recorded.

### com-security-11 - The public share link is served by the same single process that runs the fleet, with no rate limiting
- **Severity:** medium
- **Confidence:** PLAUSIBLE
- **Where:** `docs/CLIENT_FOLDERS.md:96-170` (Funnel on :8443 proxies to `127.0.0.1:8480/broll/share`), `app.py:1309-1316` (login_gate opens `/broll/share/`), `broll/web/app/routes_share.py` (Range media streaming, no throttle), `auth.py:533-549` (`DASH_TRUSTED_PROXIES` defaults to loopback, so Funnel traffic from 127.0.0.1 is a trusted proxy and its `X-Forwarded-For` is believed).
- **What:** The Funnel scoping is sound (path-prefixed, 128-bit tokens, allow-listed columns, one 404 for every dead link). But anonymous internet traffic lands in the dashboard's own uvicorn: the process that tells the fleet whether its footage is syncing. Nothing rate-limits the share routes. A leaked link (forwarded email) or a scripted Range-request flood can saturate the process or the NAS uplink, and no per-IP budget exists for anonymous requests.
- **Scenario:** A client's link is posted publicly. Hundreds of viewers stream 540p proxies, the dashboard stops answering companion reports, and lanes show stale on every editor's tray.
- **Recommendation:** Serve `/broll/share` from a separate lightweight process or container that has read-only access to `client_shares.db` and the proxies. At minimum add a per-IP and per-token request budget and a concurrent-stream cap on the share routes. Document the bandwidth exposure for customers. Days.
- **Known:** not recorded.

### com-security-12 - Insecure defaults a new customer inherits without choosing them
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** `docs/CONFIG.md:185` (`project_acl = shared`: "every editor can read, write and delete every other editor's project"), `settings.py:135` (shared report token on), `auth.py:562` (`cookie_secure=auto`), `install_dashboard_app.py:5325` (`TRUENAS_VERIFY_SSL=0`), `dashboard/deploy/compose.yaml:751-776` (optional Postgres profile: `POSTGRES_PASSWORD` default `DaVinci`, published on `${DASH_PG_PORT:-5432}` on all interfaces), no tailnet ACL/grants template in `docs/` (Tailscale is "the perimeter" per INSTALL.md:42, yet every tailnet device can reach the dashboard, SFTP and Syncthing 22000).
- **What:** Each choice is documented as an option, but a security reviewer reads defaults, not options. Together they mean a fresh install is: one shared fleet secret, any editor able to delete any project, NAS TLS unverified, an optional Resolve database with a well-known password exposed to the LAN, and no network segmentation inside the tailnet.
- **Scenario:** A buyer's IT team runs the documented install and then a network scan. Postgres on 5432 accepts `postgres/DaVinci`, and an intern's laptop on the tailnet reaches the admin dashboard.
- **Recommendation:** For new sites: `project_acl = per-project`, shared token off, `TRUENAS_VERIFY_SSL` pinned, generate a random `PG_PASSWORD` and bind Postgres to LAN plus tailnet only. Ship a `docs/TAILNET_POLICY.md` with a grants template (editors -> dashboard:443, sftp, 22000; admins -> everything; nothing else). Keep this studio's existing values pinned in its own `site.toml`. Days.
- **Known:** COMMERCIAL_READINESS items 6, 7 (built as options).

### com-security-13 - Local-account password policy is length-only
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** `auth.py:86,884-889` (`MIN_PASSWORD_CHARS = 12`, nothing else), `local_users.py:76-106` (scrypt, good).
- **What:** No breached-password check (HIBP k-anonymity or a bundled top-100k list), no reuse check, no expiry or rotation option. Throttling is good. A questionnaire will ask about NIST 800-63B alignment, which wants the breach-list check.
- **Recommendation:** Reject the top-100k common passwords from a bundled list (offline, no egress). Otherwise state the policy as NIST 800-63B-aligned once that is in place. Hours.
- **Known:** COMMERCIAL_READINESS item 15 (floor of 12 added).

### com-security-14 - The triage agent's email replies drive admin actions on email authentication alone
- **Severity:** low
- **Confidence:** PLAUSIBLE
- **Where:** `dashboard/src/ccsync_dashboard/triage_mail.py`, `triage_actions.py` (per CLAUDE.md: From in `alerts_smtp_to`, DKIM/DMARC pass, an unexpired `CCT-` reference).
- **What:** The catalogue is closed and calls existing functions, which is good. But a compromised admin mailbox, or a mail relay that rewrites Authentication-Results above ours, becomes a second admin door with no session, no MFA and no IP. The feature is off by default.
- **Recommendation:** Keep it off in the vendor build. Document it in the security overview as a separate authenticator. Consider limiting reply actions to read-only or reversible ones, and audit each one with the message-id.
- **Known:** not recorded.
