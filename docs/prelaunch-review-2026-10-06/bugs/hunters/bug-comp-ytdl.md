# bug-comp-ytdl - companion YouTube downloader and its contract with ytdl/web and the dashboard mount

Pre-commercial-launch bug hunt, 2026-10-06, HEAD 08b40eb plus the uncommitted working tree.

**Covered (read):** `companion/src/ccsync_companion/ytdl_executor.py` (FleetClient, DownloadJob, edit-ready staging/swap, module guard, cancel/progress), `ytdlp_manager.py` (all of it, including the CR-361 nightly channel, the update stamp and the retry backoff), `ytdl_server.py`, `ytdl_cookies.py`, `ytdl_browser_login.py`, `ytdl_attestation.py`, `youtube_import.py` (gate, collect, import batch) and the uncommitted CR-357 `resolve_bridge._import_files_to_bin_path_locked` diff it calls. On the other side of the wire: `ytdl/web/ytdlweb/routes_fleet.py` (claim, heartbeat, manifest, clip status, the fleet gates), `identity.read_identity_token`, `attestation.py`, `dashboard/src/ccsync_dashboard/ytdl.py` (YtdlGate stamping), `api.account_bar_reason` / `_account_refusal`, the app.py fleet-route bypass, the ytdl SPA's dispatch, hand-back and progress code, and lane A's `YTDL_WORK_EXCLUDE_RULES`.

**Probes (scratchpad, companion venv, no network, no Tk):** (1) the tray's attestation text against the server's, normalised; (2) `YtDlpManager.ensure()` with a fake runner where `--update-to nightly` succeeds and the next `--version` times out.

**Checked against:** KNOWN_BUGS.md (CR-259g, CR-263b, CR-286L, CR-327, CR-357, CR-360, CR-361), docs/bug-hunt-2026-09-24 (the earlier bug-comp-ytdl-1..5 and the wave-2 ledger `c-ytdl.md`, all of which are fixed in the tree and not re-reported).

**Not covered:** live Chromium behaviour of the sign-in flow, a real yt-dlp nightly's self-update on Windows while another yt-dlp.exe is running, NFD (Mac) label spelling through `destination_for`, and `sidecar_tools.ensure` beyond its pins.

---

### bug-comp-ytdl-1 - A suspended, disabled or deleted editor can still claim, write into and poison YouTube jobs through the shared fleet token for up to 30 days

- **Severity:** high
- **Confidence:** CONFIRMED (code path read end to end)
- **Where:** dashboard/src/ccsync_dashboard/ytdl.py:265-266 (`_fleet_stamp`: `AUTH_SHARED` returns `b"shared"` without asking `_account_bar`); :267-281 (the suspension check runs only for `AUTH_EDITOR`); ytdl/web/ytdlweb/routes_fleet.py:134-178 (`require_fleet_token` accepts the `shared` stamp, `require_fleet_caller` then trusts `require_identity`); ytdl/web/ytdlweb/identity.py:64-95 (`read_identity_token` checks only signature and expiry); dashboard/src/ccsync_dashboard/api.py:2449-2455 (`/api/v1/verify` hands every signed-in companion the shared report token while `shared_report_token_enabled` is on, which is the default). broll.py:338 and music.py:208 have the same shape.
- **What:** CR-259g (security-1) made the three mounts withhold the fleet stamp for a suspended editor, but only on the per-editor `cce1.` path. A companion holding the SHARED report token (what `/verify` gives every signed-in companion by default) gets the `shared` stamp with no account check. The sub-app then takes the editor name from the signed identity token, which is stateless and valid for 30 days. Suspension, a disabled local account and deletion are never consulted on `/ytdl/api/jobs/{id}/(claim|heartbeat|download-manifest|clips/*/status)`.
- **Scenario:** an admin suspends a freelancer who has left (the case CR-259g was written for: "a freelancer who left on Friday could still ... pull a YouTube download into the tree, from the laptop nobody collected"). The laptop still holds `dashboard_token` (shared) and an identity token with weeks left. From that laptop, with curl or the tray, the person can: claim any job in phase `downloading` by integer id (claims are not owner-scoped, by design), read its manifest (URLs, project label, project path), have clips land in the shared tree through lane A, and post `done` with any filename. That last one writes `filepath`/ledger rows the dedupe trusts, so later searches report "the fleet already has this" for clips that do not exist. They can also post `failed` for every clip of a colleague's job. This is the default configuration, because `shared_report_token_enabled` defaults to on and `/verify` hands the shared token out.
- **Recommendation:** in `YtdlGate._fleet_stamp` (and the b-roll and music twins), for `AUTH_SHARED` also read the identity header, verify it the way `require_identity` does, and withhold the stamp (or answer 403 with a reason) when `api.account_bar_reason` names that editor. Better still, have `login_gate`'s fleet-route bypass refuse a barred identity for every mount in one place. Separately, give identity tokens a server-side revocation check: a deny-list keyed by user plus issued-at, consulted by `require_identity`, so deleting a user takes effect before the 30 days run out.
- **Known:** extends CR-259g (marked FIXED; the shared-token path was never covered).

### bug-comp-ytdl-2 - The tray's YouTube terms are a materially shorter text recorded under the same TEXT_VERSION as the web notice

- **Severity:** medium (legal exposure)
- **Confidence:** CONFIRMED (probe)
- **Where:** companion/src/ccsync_companion/ytdl_attestation.py:49-84 (`TEXT_VERSION = "2026-08-17.1"`, `NOTICE_TEXT`); ytdl/web/ytdlweb/attestation.py:46-80; the comments claiming the two are "kept word for word" sit at companion/tests/test_bug_hunt_2026_09_24_w2_c-ytdl.py:297 and companion/tests/test_sweep_2026_09_04_copy.py:448. No test compares the two texts.
- **What:** both sides record acceptance as version `2026-08-17.1`, but the tray's text leaves out three statements the web text makes:
  - "YouTube's terms restrict downloading content except through features YouTube itself provides or where you have the rights holder's permission."
  - "...and it makes no representation that any download is lawful."
  - "...so that what was downloaded, and on whose say-so, can be answered later."

  The tray also adds sentences of its own: the pacing disclaimer, and "Accepting records that you have read this on THIS computer". Normalised for whitespace and punctuation, the probe found the texts unequal and all three server sentences absent from the tray.
- **Scenario:** a customer's editor accepts on the tray. The per-computer record (`~/.ccsync/state/ytdl-attestation.json`) says they agreed to version 2026-08-17.1. That is the record that lets the companion download from the editor's own IP. In a dispute, the vendor's records claim agreement to wording the person was never shown, including the explicit ToS-restriction sentence that is the point of the notice. The server's `text_sha256` evidence covers only the web text.
- **Recommendation:** make the tray text the web text verbatim, or vendor it from one source as `ytdl_common` is. Add a test that compares them with whitespace normalised, so a future edit fails CI. Then bump TEXT_VERSION on both sides, because the tray wording a person accepted changes, and record a hash of the shown text in the tray's state file too. Counsel should see both texts.
- **Known:** new

### bug-comp-ytdl-3 - The signed-in YouTube session survives sign-out, so the next person on that computer downloads as the previous person's Google account

- **Severity:** medium (privacy and account risk, shared machines)
- **Confidence:** CONFIRMED (code read; nothing anywhere deletes either file)
- **Where:** companion/src/ccsync_companion/ytdl_cookies.py:80-104 (`default_cookies_path()` = `~/.ccsync/youtube-cookies.txt`, resolved for whoever is signed in); ytdl_browser_login.py:211-213, :32 ("The profile is kept") (`~/.ccsync/yt-login-profile`, a full Chromium profile signed in to Google); companion/src/ccsync_companion/app.py:6910-6924 and identity.py:554-560 (sign-out removes only the identity file); ytdl_executor.py:2999-3020 (the jar is used on the first bot check).
- **What:** the cookie jar and the browser profile belong to the OS user, not to the CC Sync editor who created them. The attestation is per editor ("a shared machine does not carry one person's acceptance over to the next"), but the Google session carries over.
- **Scenario:** editor A uses "Sign in to YouTube" on a shared edit-suite PC, then signs out of the tray. Editor B signs in and accepts the terms. On B's first bot-checked clip, `_run_ytdlp_paths` retries with A's cookies.txt. The download is attributed to B in the ledger but made with A's Google account. If YouTube flags the session (the CR-80 shape), A's personal Google account takes the hit. The kept profile also leaves A's live Google login in `yt-login-profile`, open to anyone who launches a Chromium with that `--user-data-dir`.
- **Recommendation:** record which editor installed the jar (a sidecar JSON next to it). `resolve()` should return None when the signed-in editor differs. On sign-out (and on "forget this computer"), delete `youtube-cookies.txt`, its status file, and `yt-login-profile`. Mention it in the sign-out copy.
- **Known:** new

### bug-comp-ytdl-4 - Free space is checked once, at the claim, so one local job can fill the editor's disk to zero

- **Severity:** medium
- **Confidence:** CONFIRMED (code read; `free_bytes` is read only in `capabilities()` and the claim)
- **Where:** companion/src/ccsync_companion/ytdl_executor.py:2265-2278 (one check: `MIN_FREE_BYTES_MARGIN + NOMINAL_JOB_BYTES` = 200 MB + 5 GiB); :2422-2453 (the clip loop has no space check); :2689-2700 (a conversion holds the staged original and the `.editready` output at the same time)
- **What:** the server side grew free-space guards for every executor path it runs (YTWEB-9, CR-263b, CR-286L). The companion's only check is a nominal 5.2 GB before the claim, whatever the job's size, and it is never repeated.
- **Scenario:** an editor's tree drive (often the system drive on a laptop) has 6 GB free. They download a 40-clip 1080p search, roughly 12 GB, or one 2-hour clip that needs converting (the original plus a full re-encode). Clips land until the disk is at 0 bytes. yt-dlp then fails with ENOSPC, the next two clips fail the same way, and the breaker hands the job back. By then the disk is full. Syncthing, lane B, Resolve's cache and render, and the tray's own state writes all start failing on the editor's machine, and nothing said why before it happened.
- **Recommendation:** before each clip (and before a conversion), re-measure `free_bytes_at(outdir)`. When it falls below the margin plus a per-clip estimate, stop and hand back with an editor sentence (the hand-back channel already exists). Use the size yt-dlp reports, or `--max-filesize` together with a floor, as the estimate. A conversion should also need room for a second copy.
- **Known:** new (the server-side twins are CR-263b and CR-286L, both fixed)

### bug-comp-ytdl-5 - Every editor machine now takes the newest yt-dlp nightly daily, with no remote way to pin, hold or roll back a bad build

- **Severity:** medium
- **Confidence:** CONFIRMED (the lever does not exist)
- **Where:** companion/src/ccsync_companion/ytdlp_manager.py:80-83, :125, :934-1022 (`_check_for_newer` runs `--update-to nightly` on every daily pass); ytdl/web/ytdlweb/routes_fleet.py:294-301 (`/ytdl/api/config/ytdl-client` publishes only `min_ytdlp_version`, so a floor can only go up); the only off switch is `ytdlp_max_age_days = 0`, typed by hand into each machine's config.toml.
- **What:** CR-361 (owner decision) moved the fleet from stable to the nightly channel, applied within 24 h. Nightlies are untested builds. If one regresses (extraction broken, a crash on start, a changed filename sanitiser that breaks the naming contract `TEMPLATE_VERSION` cannot see), every customer's machines take it within a day. Nobody has a dashboard setting, site flag or client-config key to say "stay on X" or "go to stable", and the companion cannot downgrade: the floor only rises, and `--update-to` is always `nightly`.
- **Scenario:** a nightly published at 23:00 breaks merges on Windows. By the next evening every Windows editor across every customer is on it. Local downloads fail clip by clip, and the identical-failure breaker hands each job to the server, which runs its own nightly (CR-361 server half) and may be broken the same way. The vendor's only fix is to wait for the next nightly, or to ask each customer to edit config.toml on each machine.
- **Recommendation:** add `ytdlp_channel` (`nightly` / `stable` / `pin:<version>`) and an optional `max_ytdlp_version` to the ytdl client config and the site manifest. The companion honours them with `--update-to <channel>@<tag>`, which can move a binary backwards, and the dashboard can flip them fleet-wide. Consider a soak, for example taking a nightly only once it is N hours old. Keep the vendor feed able to override it.
- **Known:** CR-361 (BUILT, unshipped). This is a launch risk of that change, not a regression it recorded.

### bug-comp-ytdl-6 - A self-update whose new binary cannot be read is published as "ok" under the OLD version

- **Severity:** low
- **Confidence:** CONFIRMED (probe)
- **Where:** companion/src/ccsync_companion/ytdlp_manager.py:979-992
- **What:** `after = version(...) if updated else None`, then `if not updated or after is None:` publishes `ok=True, version=current` with "could not check for a newer nightly build today". When the update DID replace the binary but the new one did not answer `--version` (the first run of a fresh PyInstaller exe behind Defender, which the module's own `VERSION_TIMEOUT_SECONDS` comment describes, or a genuinely broken nightly), the status names a binary that is no longer on disk and still says ok. Probe: `[['--version'], ['--update-to', 'nightly'], ['--version' (timeout)]]` gave `{'ok': True, 'version': '2026.09.01', 'action': 'none', 'message': '... could not check for a newer nightly build today ...'}`.
- **Scenario:** a broken nightly lands. `capabilities()` answers ok with the old version string, the claim reports a version that is not the one running, the dashboard's fleet grid shows the old version as current, and every local clip then fails until the breaker trips. The log says "could not check", which sends whoever reads it after GitHub rather than after the binary.
- **Recommendation:** treat `updated and after is None` as its own outcome: publish `ok=False`, `version=None`, a message saying the update ran and the new binary does not answer, and let `_ytdlp_pass_failed` give it the short retry.
- **Known:** new (a gap in CR-361's new branch)

### bug-comp-ytdl-7 - The executor's "this failure looks like an old yt-dlp" poke is now swallowed by the 20 h update throttle

- **Severity:** low
- **Confidence:** CONFIRMED (code read)
- **Where:** companion/src/ccsync_companion/ytdl_executor.py:2887-2915 (`_maybe_poke_ytdlp` calls `ensure()` on `http error 403` or `requested format is not available`); ytdlp_manager.py:914-932, :966-976 (`_recently_checked` short-circuits to "was the newest N h ago")
- **What:** the poke exists so "the fix reaches a machine at its next failure instead of at its next daily check". With CR-361's throttle, a poke within 20 h of the last successful check runs no update unless the floor moved. Yet the poke's trigger, a 403 or "format not available" on a binary, is exactly the case where a newer nightly is most likely to exist.
- **Scenario:** YouTube changes something at 10:00 and yt-dlp's nightly fixes it at 14:00. A machine that checked at 08:00 fails every clip until 08:00 the next day, with the poke firing and doing nothing. Each job hands back to the server meanwhile.
- **Recommendation:** have the poke pass `force_check=True` through `ensure()` to `_check_for_newer`, bypassing the stamp but keeping one poke per job (and perhaps a 1 h floor).
- **Known:** new

### bug-comp-ytdl-8 - A stop that lands just after yt-dlp finishes leaves the clip under its deliverable name, never probed

- **Severity:** low
- **Confidence:** PLAUSIBLE
- **Where:** companion/src/ccsync_companion/ytdl_executor.py:2555-2561 (`if self._should_stop(): self._cleanup_current(); return` right after yt-dlp returns); :3253-3261 (`_cleanup_current` only sweeps sweepable names)
- **What:** CR-327 and the bug-comp-ytdl-2 fix move an unprobed or convert-needed download onto the `.source.editready` staging name when a stop lands during the probe or the conversion. The earlier window has no such handling. The window is a stop (the page's [ STOP ], Quit, a 410, a CredentialLost) that arrives after yt-dlp renamed the merged file into its final name but before the probe: yt-dlp exiting normally, or being killed while it deletes the `.fNNN` intermediates and writes the info json.
- **Scenario:** the editor presses [ STOP ] as a clip finishes merging. The landed `<title> [id].mp4` stays in the term folder, unprobed and unreported. If it needed converting (VFR, or a non-AVC rung), lane A uploads it after 120 s under the final name, and the importer files it. That is the CR-79/CR-327 undecodable-clip shape, through a narrower door.
- **Recommendation:** in that branch, run the same move-aside the probe branch does when `landed_file()` finds a file this attempt created (`not in before`), so the sweep removes it.
- **Known:** related to CR-327 / bug-comp-ytdl-2 (2026-09-24), both fixed. This window was not covered.

### bug-comp-ytdl-9 - /ytdl/fetch will pull any file under Projects/ from the NAS, not only YouTube originals

- **Severity:** low
- **Confidence:** CONFIRMED (code read)
- **Where:** companion/src/ccsync_companion/ytdl_server.py:328-387 (`build_fetch_response`: any contained `rel_path` under the Projects mount); broll_fetch.py:106 (`PROJECTS_REMOTE_REL = "Projects"`), :220-261 (`fetch_refusal` checks containment and mount only)
- **What:** the route exists for one purpose: fetching a YouTube original the server downloaded (CR-32). It accepts any path under `Projects/`, including camera originals of projects this computer does not sync. It checks only that the tree is mounted.
- **Scenario:** a page on the dashboard origin (the only origin the loopback guard accepts, so this needs an XSS or a hostile admin-authored page) POSTs `{"rel_path": "2026/Other Show/Footage/A001.R3D"}` in a loop. The editor's companion pulls multi-GB originals of a project it does not sync into a local folder that no lane manages or cleans, with no space check in that path.
- **Recommendation:** require the path to sit under `<label>/Youtube/` and to name a video extension. Optionally also require the label to be in this computer's selection, the same rule `_label_is_ours` applies to downloads.
- **Known:** new

### bug-comp-ytdl-10 - THIRD_PARTY_NOTICES still says the NAS runs the lock-pinned yt-dlp; since CR-361 it runs an unpinned nightly from PyPI

- **Severity:** low (legal doc drift)
- **Confidence:** CONFIRMED (doc read against `ytdlp_nightly` / run.sh as described in CR-361)
- **Where:** docs/legal/THIRD_PARTY_NOTICES.md:431 ("yt-dlp (NAS side) | the version pinned in `dashboard/deploy/requirements.lock`"), :364 (yt-dlp 2026.8.19 listed as what ships in the container)
- **What:** CR-361 installs `pip install --pre --upgrade --no-deps` nightly builds into `/data/ytdlp-nightly` at boot and every 6 h, and they shadow the pinned copy. The notices, which LG-13/LG-16 exist to keep truthful, describe the pinned version and the lock as the source. That is no longer what runs on a customer's NAS.
- **Scenario:** a customer's compliance review, or counsel, reads the notices and believes the container's yt-dlp is the hash-pinned locked version. It is whatever PyPI served that morning.
- **Recommendation:** update the row to "newest nightly from PyPI at boot, falls back to the pinned version", and teach `tools/gen_notices.py` / the LG-16 drift check about the nightly path.
- **Known:** follows from CR-361 (BUILT, unshipped)
