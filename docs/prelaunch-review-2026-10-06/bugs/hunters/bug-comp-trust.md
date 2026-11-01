# Pre-launch bug hunt: companion trust / update / network (bug-comp-trust)

Date 2026-10-06, working tree on top of 08b40eb. Read-only review.

Covered (read end to end): `upgrade.py` (offer parse, signature/kind/platform/floor checks,
download, swap, rollback, crash-loop revert), `release_pubkey.py`, `ed25519.py`, `transport.py`,
`loopback_guard.py`, the request envelope and GET/POST dispatch of `broll_server.py` (vetting,
CORS, path translation/containment, body handling), `music_server.py`, `identity.py`,
`machine.py`, `machine_settings.py`, `reporter.py` (post path, withholding, payload fitting),
`site.py`, `secretfile.py`, `win_trust.py`, `capabilities.py`, and the relevant parts of
`config.py` (`set_value`, `load_config`, site-manifest merge, dashboard_url checks). Cross-checked
the dashboard side of the per-editor token binding (`api.py` resolve_companion_credential callers)
and the release tooling defaults (`sign_release.py`, `build_editor_package.ps1`).
Probed `loopback_guard.origins_for_url` with the companion venv.

Not covered in depth: `broll_server.build_insert_response` internals, `ytdl_executor`/`ytdl_server`
beyond `reveal_command`, `broll_ingest` beyond `prepare`'s path rule, `app.py` outside the
upgrade/sign-out/pushed-update paths, and most of `config.py`'s DEFAULTS and validation.

### bug-comp-trust-1 - The one release signing key every customer trusts sits in plaintext on the everyday workstation
- Severity: high
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/release_pubkey.py:56-58; %USERPROFILE%\.ccsync-release\release.key (exists, 279 bytes, plain file); tools/release_key.py:229 (no passphrase wrap, by decision); docs/COMMERCIAL_READINESS.md:144
- What: `RELEASE_PUBKEYS` holds one key, generated on 2026-08-17 by an agent session on the base rig. Its private half is an unencrypted file in the profile of the machine that also edits, browses, runs yt-dlp and runs Claude Code with bypass permissions. Anything running as `alex` can read it. The docs call it "offline". It is not. COMMERCIAL_READINESS item 4 still says "decide keep/rotate before the first customer ship and BACK IT UP OFFLINE".
- Scenario: any process on the base rig reads release.key: a malicious dependency in a venv, a compromised download, or an agent acting on injected content. It can then sign a companion record that every customer's fleet will install and run, because the dashboard is removed from the trust chain and the key is the whole chain. The attacker can also sign a record with a huge `min_version` (version == min_version, so `_min_version_above_own` passes). That raises every machine's monotonic floor, and every later genuine vendor build is refused. Recovery then means deleting `upgrade_floor.json` by hand on every machine of every customer. There is no revocation path except shipping a new build, which that floor would refuse.
- Recommendation: before the first paying customer, generate the production key on an offline machine or a hardware token (YubiKey/HSM, or a dedicated signing VM with no browsing or agents), bake it, and run the overlap release. At minimum, encrypt the key at rest with DPAPI. The android keystore password is already DPAPI-wrapped in the same folder, so the pattern exists. Keep `.ccsync-release` out of every agent session's filesystem scope. Write a compromise runbook, including a second "emergency" public key baked now whose private half is kept offline.
- Known: COMMERCIAL_READINESS.md item 4, "decide keep/rotate", still OPEN.

### bug-comp-trust-2 - No downgrade floor by default, so any older signed build can be pushed back onto a fleet
- Severity: medium
- Confidence: CONFIRMED
- Where: installer/build_editor_package.ps1:1043-1044 (`CCSYNC_MIN_VERSION` defaults to 0.0.0); tools/sign_release.py:460; companion/src/ccsync_companion/upgrade.py:726-776, 1502-1565
- What: the floor only rises when a signed record carries a `min_version`. The ship path signs `0.0.0` unless someone sets `CCSYNC_MIN_VERSION` by hand. "Different, not newer" therefore lets a dashboard offer any build ever signed for that platform, and `commands.upgrade` installs it without a click.
- Scenario: a customer's dashboard is compromised (it is the party the signing key was introduced to distrust), or an admin mis-clicks. It re-offers an older signed companion: for example a 0.9.x from before comp-core-1 (2026-09-03), which installs a signed `onboard` record over itself, or any build from before a fixed loopback or path-containment hole. `_check_offer` passes it, and the machine runs a known-vulnerable build. The downgrade floor the docs describe is in force nowhere, because no published record raised it.
- Recommendation: make the release pipeline publish a real floor. A good default is the oldest build with no known security fix outstanding, raised at each security-relevant release (comp-core-1, LG-4, the loopback guard). Consider refusing `0.0.0` in `sign_release.py` for `companion` records unless `--allow-no-floor` is passed.
- Known: design decision ("downgrade is first-class"), not tracked as a defect.

### bug-comp-trust-3 - A second person signing in on a computer provisioned with someone else's per-editor token is locked out of the fleet
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/identity.py:146-176 (preferred_report_token), 498-506 (sign_in keeps editor_report_token), 279-288 (_adopt_report_token); onboarding/steps.py:3622 (the wizard writes the cce1 token to config.toml `report_token`); dashboard/src/ccsync_dashboard/api.py:2649-2658, 2718-2724, 10172-10177, 11729-11734
- What: the per-editor `cce1.` token is bound to one editor on the dashboard. The companion always prefers it (from config.toml `report_token` or identity.json) over the shared token, whoever is signed in. A tray sign-in by another person swaps only the identity token. The fleet credential stays the first editor's, and nothing notices that they now disagree.
- Scenario: editor A's laptop, or a shared edit bay, was set up by the wizard with A's per-editor token. Editor B uses "Sign in..." with B's own account, and the sign-in succeeds. Every report, selection read/write and fleet-job call then carries A's cce1 token with B's identity. The dashboard answers 401/403 "this X-CCSync-Token belongs to a different editor". The machine drops off the grid and syncs no plan, while the tray says B is signed in. If the site has disabled the shared token, /verify sends no replacement, so signing in again cannot fix it. Only a wizard re-run by an admin can.
- Recommendation: have /verify report which editor (if any) the companion's current `X-CCSync-Token` belongs to, or send that token along on verify. On a mismatch, either refuse the sign-in with a clear sentence ("this computer is set up for A, ask an admin"), or drop the per-editor token and mint or ask for B's. At least, surface "token belongs to another editor" as its own tray state rather than a generic report failure.
- Known: not recorded.

### bug-comp-trust-4 - The loopback token adds nothing against local processes: any non-browser caller can send an allowed Origin
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/broll_server.py:2048-2104 (_vet_request/_post_authorised); loopback_guard.py:13-28
- What: `_post_authorised` accepts a POST/PUT when the `Origin` header is on the allow-list OR the token is presented. Origin is only unforgeable for browsers. curl, a script, or another OS user's process can set `Origin: https://<dashboard>` and pass with no token. The allow-list is easy to learn: it is the studio's dashboard address, and `site.json` is not hardened. The module's own threat model says non-browser callers have to prove themselves with the token, and the code does not enforce that.
- Scenario: a shared Mac or Windows edit bay with several OS accounts, or low-privilege malware running under another account, POSTs to 127.0.0.1:8899 with the dashboard Origin. It can claim fleet ytdl jobs under the logged-in editor's identity (`/ytdl/download`), insert media into their open Resolve timeline (`/insert`), start NAS fetches (`/ytdl/fetch`, music send), or start ingest batches that upload under their name.
- Recommendation: require the token for any request that does not carry browser-only evidence. For example, when an Origin is present, also require `Sec-Fetch-Site`/`Sec-Fetch-Mode`, which browsers always send and scripts usually do not. Better: have the page obtain a short-lived capability from the dashboard that the companion can verify. Correct the docstring either way.
- Known: not recorded. trust-model-9 covers XSS on the allowed origin, which is a different issue.

### bug-comp-trust-5 - On plain-http LAN, the unauthenticated site manifest is persisted and widens the loopback allow-list and the SMB target
- Severity: medium
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/site.py:142-198 (fetch + save_site, no auth, no integrity); loopback_guard.py:244 (the manifest's dashboard_url joins the allow-list); config.py:1912 (the manifest's smb_unc becomes server_p_unc); reporter.py:1323-1420 (the reply drives on_report_response: commands.upgrade, machine_settings, file_moves, resume lane B); transport.py (LAN http allowed by design)
- What: `transport` refuses only public cleartext. A studio-LAN deployment (`http://192.168.x`) is accepted with a note. On that channel nothing authenticates the dashboard's replies. The site manifest is an unauthenticated GET, cached to `~/.ccsync/state/site.json` and trusted from then on. Its `dashboard_url` is added to the loopback Origin allow-list, its `smb_unc` becomes the grade swap's SMB target, and its `features` flip auto_update and youtube_unblock.
- Scenario: someone on the studio LAN (a guest device, or a compromised box next to the NAS) ARP-spoofs one `/api/v1/site` fetch and writes `dashboard_url: https://attacker.example` and `smb_unc: \\attacker\share` into site.json. From then on the attacker's web page has loopback POST rights on that editor's machine, and the next grade swap sends the editor's NTLM credentials to the attacker's SMB server. The cache survives after the spoof ends. Report-reply commands can be injected the same way (file moves, machine settings, lane B resume). None of this applies over Tailscale (WireGuard).
- Recommendation: for commercial customers, make https (Tailscale Serve) the supported transport and treat LAN http as unsupported or opt-in. At minimum, do not let the manifest's `dashboard_url` widen the loopback allow-list unless its host matches config's `dashboard_url`, and do not accept a manifest `smb_unc` whose host differs from the dashboard/NAS host.
- Known: "require https site-wide" is deferred (LEGAL_GAP_FEATURES_PLAN section 6). The manifest-to-allow-list and manifest-to-SMB persistence is not recorded.

### bug-comp-trust-6 - A dashboard_url written with an explicit default port makes every Send to Resolve fail with 403
- Severity: low
- Confidence: CONFIRMED (probed)
- Where: companion/src/ccsync_companion/loopback_guard.py:208-231 (origins_for_url keeps the netloc verbatim)
- What: `origins_for_url("https://dash.x.ts.net:443")` returns `{"https://dash.x.ts.net:443", "http://dash.x.ts.net:443"}`. A browser's Origin omits default ports (`https://dash.x.ts.net`), so `origin_allowed` is False. The same happens for `http://host:80`. The http/https twin also carries the other scheme's port, which is meaningless.
- Scenario: an admin types the Serve address with `:443` into the wizard or config.toml. Every b-roll, music and ytdl browser call to the companion is refused with 403, and the log names an allow-list that looks right.
- Recommendation: normalise the netloc. Drop `:443` for https and `:80` for http, and for the twin emit the other scheme's default form only when the port was the default.
- Known: not recorded.

### bug-comp-trust-7 - A jobs_kinds typo turns a restriction into "take every kind"
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/capabilities.py:101-135 (job_kinds), used for the report's `job_kinds` and the runner's gate
- What: unknown names are dropped with a warning, and an empty result means every kind. So `jobs_kinds = "peeks"`, meant to limit a laptop to one cheap kind, reports `[]` and takes whisper and proxies too. The docstring states the opposite intent ("a machine that silently takes no work"). `machine_settings._validate` refuses this shape for dashboard asks, but a hand edit does not.
- Scenario: an editor restricts their laptop to `peaks`, mistypes it, and the fleet schedules GPU whisper and 480p proxy jobs onto it while they are working.
- Recommendation: when a non-empty `jobs_kinds` yields no known kind, treat it as "no kinds" (take no work) and show the warning in Settings. Do not fall back to every kind.
- Known: not recorded.
