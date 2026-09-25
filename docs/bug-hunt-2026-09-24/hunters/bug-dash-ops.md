# bug-dash-ops - dashboard ops modules: triage agent + reply path, CLI tools/auto-update, ytdl mount, OTA/release trust, crash reports, small helpers
Files read (approximate coverage): triage_mail.py (full), triage_actions.py (full), triage.py (full), cli_tools.py (install/auto-update/env sections, ~45%), ytdl.py (gates, ~70%), release_trust.py (full), crash_report.py (full), android.py (full), published_docs.py (full), internal_sftp.py (full), tailscale_local.py (full), dashboard_update.py (first 500 lines + extraction), release_feed.py (redirect handling only), ai_providers.py (mask/keys only), nas/synology.py (grep for shell/quoting only). Callees read: db.set_fleet_halt, db.request_job_cancel, db.notice, auth._resolve_session / read_session_cookie, app.csrf_gate, notices._check_ai_cli_update, notices._triage_reply_accepted.
Tests/probes run: three ad-hoc snippets from dashboard\.venv (session cookie signed with a previous secret through YtdlGate; Starlette cookie_parser vs ytdl._session_cookie on a duplicated cookie; crash_report.redact on env-style and quoted-key secrets). No suite run.

## Findings

### bug-dash-ops-1 - The "same Message-ID is in my Sent folder" proof is an IMAP substring search, so a forged From passes the authentication check
- Severity: medium
- Confidence: CONFIRMED (mechanism); exploit needs a live CCT token, so practical risk is bounded
- Where: dashboard/src/ccsync_dashboard/triage_mail.py:599 (the search), :499 (the override)
- What: `_in_sent` runs `SEARCH HEADER Message-ID "<mid>"`, and RFC 3501 HEADER search is a SUBSTRING match. It also never compares anything else about the message. `handle_message` then treats a hit as proof of authorship when `sender == alerts_smtp_user`, and that override applies even when the topmost Authentication-Results says `dmarc=fail`.
- Failure scenario: someone sends mail From the owner's address (the smtp user) To the reply address, with `Message-ID: mail.gmail.com` (or any fragment that appears in any message the owner ever sent), plus a CCT reference from a report sent in the last 48 h (for example one the owner forwarded, or one quoted in a thread). With a domain DMARC policy of none or quarantine-to-inbox, it reaches INBOX, the Sent search matches, `ok` becomes True, and the actions run (release the fleet halt, push updates, cancel jobs). The second of the three documented checks is no longer a check.
- Evidence: read `_in_sent` and `handle_message`. The only filter on `mid` is that it has no `"` or `\`. RFC 3501 6.4.4: HEADER matches messages "that contains the specified string in the text of the header".
- Ledger: new (the feature is from 2026-09-24, commits 19dc9cf/9ee90d0)
- Suggested fix: fetch the Sent hit and require an exact Message-ID match plus a matching body hash (or the raw bytes) before crediting it. Never let the Sent proof override an explicit `dkim=fail`/`dmarc=fail` in the topmost header.

### bug-dash-ops-2 - /ytdl drops the identity of every session signed with a previous DASH_SESSION_SECRET
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/ytdl.py:171 (and :555, where the gate gets only `settings.session_secret`)
- What: login_gate (`auth._resolve_session`) accepts a cookie signed with a secret in `session_secrets_previous` (DASH-2, "a rotation must not sign every admin out"). `YtdlGate._identified_scope` calls `auth.read_session_cookie(self._secret, cookie)` with no `previous`. So the cookie passes the login gate, but no X-CCSync-User is stamped on it.
- Failure scenario: an admin rotates DASH_SESSION_SECRET and keeps the old one in the previous list. Every editor still gets into the dashboard, but every /ytdl UI call reaches ytdlweb with no identity header and returns its own 401. The downloader stays broken for everyone until each person logs out and back in (up to the 7-day cookie lifetime). Nothing says why.
- Evidence: probe with the dashboard venv. A cookie made with secret `o*40` resolves to `bob` via `_read_token_any(new, (old,), ...)`, but `YtdlGate(new)._identified_scope` returns headers `[]` (no identity).
- Ledger: new (a gap in DASH-2's rotation carve-out)
- Suggested fix: have the gate verify with `previous_session_secrets(settings)` too (e.g. `_read_token_any(secret, previous, cookie, PURPOSE_SESSION)`). Better still, stamp the identity login_gate already resolved (it checks the server-side row) instead of re-reading the cookie. broll.py:232 and music.py:242 have the same shape.

### bug-dash-ops-3 - The ytdl gate reads the FIRST ccsync_session cookie while login_gate reads the LAST, and the gate never checks revocation
- Severity: low
- Confidence: CONFIRMED (mechanism), PLAUSIBLE (impact)
- Where: dashboard/src/ccsync_dashboard/ytdl.py:307-324
- What: `_session_cookie` returns the first `ccsync_session` in the Cookie header. Starlette's `cookie_parser` (used by `request.cookies`, and so by login_gate) keeps the last. login_gate checks the server-side session row; the ytdl gate only checks the signature and expiry. So the identity given to ytdlweb can be a different user from the one the login gate authenticated, taken from a cookie that has been logged out or revoked.
- Failure scenario: the browser holds two ccsync_session cookies (one set with a narrower Path, or planted by any page on the same host, since cookies ignore ports). Browsers send the longer-path cookie first. The request is authenticated as user B's live session, but ytdlweb acts as user A, whose session was revoked by "log out everywhere".
- Evidence: probe. For `ccsync_session=FIRST; ccsync_session=LAST`, `cookie_parser` gives `LAST` and `ytdl._session_cookie` gives `FIRST`.
- Ledger: new
- Suggested fix: take the username login_gate already resolved (request state or a scope key) instead of parsing the cookie a second time. At minimum, use the same last-wins parse and check the session store.

### bug-dash-ops-4 - crash_report.redact misses the very secrets its docstring names (env-style and quoted keys)
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/crash_report.py:66
- What: the key pattern is `\b(token|password|passwd|secret|api[_-]?key|dsn|pw)\b\s*[:=]`. In `TRUENAS_PW`, `DASH_SESSION_SECRET` and `SYNCTHING_API_KEY`, the underscore is a word character, so `\b` never matches before the key. In a JSON or Python dict repr, the closing quote after the key sits between the name and the `:`. Either way the value goes through unredacted. This redactor also feeds `notices.error_detail` (CR-266b), so its output reaches the home page and DB backups, not only crash files.
- Failure scenario: an exception message that quotes the environment or a request payload (for example a TrueNAS client error echoing `{'password': ...}`, or a config error naming `DASH_SESSION_SECRET=...`) is written verbatim into a crash file an operator emails, or into a notice body rendered on the dashboard.
- Evidence: probe. `redact('DASH_SESSION_SECRET=abcdef123')`, `redact('TRUENAS_PW=hunter2')`, `redact('SYNCTHING_API_KEY: zzzz')`, `redact("{'password': 'hunter2'}")` and `redact('{"api_key": "k123"}')` all come back unchanged. `redact('token=abc')` is redacted.
- Ledger: related to CR-266b (fixed; this is a gap it did not cover)
- Suggested fix: use `(?<![A-Za-z0-9])` / `(?:^|[^A-Za-z0-9])` boundaries that treat `_` as a separator, allow an optional closing quote (`["']?\s*[:=]\s*["']?`), and add tests for these five strings.

### bug-dash-ops-5 - Reply poll cap counts already-handled messages, so an older unhandled reply can be starved forever
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/triage_mail.py:653-663
- What: since UNSEEN was dropped, the search returns every message to the reply address in the 2-day window. `numbers[-20:]` is taken BEFORE the "already in triage_replies" skip, so known messages use up the 20 slots. The comment says "the rest wait for the next poll", but the next poll picks the same newest 20.
- Failure scenario: 20 or more messages reach the plus-address within 2 days (several replies plus confirmations quoted back, or anyone mailing the address, which is also a cheap deliberate block). The owner's reply that is 21st from the newest is never read. It falls out of the SINCE window unhandled, and nothing says so.
- Evidence: read the loop. `continue` on a known Message-ID happens after the slice.
- Ledger: new
- Suggested fix: apply the cap to messages actually handled (walk newest to oldest and skip known ones without counting them), or search with UID and remember the highest UID handled.

### bug-dash-ops-6 - The CCT reply token is stored in plaintext beside its hash
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/triage.py:694-696 (with :488 and :656)
- What: `triage_runs.token_hash` stores only sha256(token), so a database reader cannot mint a reply. But `_finish` stores the whole mailed body, including `Reference: CCT-<token>`, in `report_json`. `report_text` serves it on /admin/alerts/triage/{id}, and it travels in every DB backup and snapshot for 48 h of validity.
- Failure scenario: anyone with a copy of dashboard.db (a backup, a diagnostics bundle, a snapshot) reads a live token. That is the third authentication factor from bug-dash-ops-1.
- Evidence: read `run()`. The body is composed with `token=token` and persisted.
- Ledger: new
- Suggested fix: store the body with the reference line masked (e.g. `CCT-...` plus the last 4), and keep the plaintext only in the outgoing email.

### bug-dash-ops-7 - Authentication-Results is trusted without checking its authserv-id
- Severity: low
- Confidence: PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/triage_mail.py:212-236
- What: the "topmost header is the receiver's" assumption holds only when the receiver adds one. The code's own 2026-09-24 comment records that Google adds NONE for mail that never leaves the Workspace. For such mail, the topmost Authentication-Results is whatever the sender wrote, and it is not checked against an expected authserv-id (e.g. `mx.google.com`).
- Failure scenario: a message submitted inside the same Workspace domain with a hand-written `Authentication-Results: x; dkim=pass header.d=<domain>` and a From in `alerts_smtp_to` passes check 2 with no DKIM ever evaluated. It still needs a CCT token.
- Evidence: read `auth_results_pass`. There is no authserv-id comparison.
- Ledger: new
- Suggested fix: require the header's authserv-id to be the configured or derived receiver (e.g. `mx.google.com` for imap.gmail.com), and ignore any other one.

### bug-dash-ops-8 - A second CLI update inside the grace hour deletes the still-in-grace version at once
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/cli_tools.py:1231-1254, 1300
- What: `_finish_install` rebuilds the state record from scratch and records only the version it is replacing as `previous_version`. A version still waiting in its PRUNE_GRACE_SECONDS from the update before is neither spared nor carried forward. `_prune_old_versions` then removes it at once.
- Failure scenario: an admin clicks UPDATE (A to B), and within the hour UPDATE again, or the auto-updater and an admin both land (B to C). A Timeline Cards call started on A just before the first flip (up to 900 s long) loses its binary's path mid-run, which is the exact CR-309 failure the grace period exists to stop.
- Evidence: read `_finish_install` / `_prune_old_versions`. `spared = {keep, "home", ".staging"} | {previous}`, where `previous` is only the most recent one.
- Ledger: related to CR-309
- Suggested fix: keep a list of superseded versions with their timestamps (carry forward any still in grace) and spare all of them until `sweep_superseded` retires each.

### bug-dash-ops-9 - Two crashes of the same thread in the same second overwrite one crash file
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/crash_report.py:133-139
- What: the file name is `<when to the second>-<thread>.json`, opened with O_TRUNC. Two unhandled exceptions from threads that share a name (e.g. repeated `ThreadPoolExecutor-0_0`, or a restart loop) within one second leave only the second.
- Failure scenario: the first, usually causal, traceback of a burst is lost.
- Evidence: read `write_report`.
- Ledger: new
- Suggested fix: add a counter or random suffix, or open with O_EXCL and retry with `-1`, `-2`.

## Coverage note
Not reached in depth: dashboard_update.py after line 500 (apply/rollback worker, stage-verify), release_feed.py beyond its redirect walker, package_store.py, nas/truenas.py and most of nas/synology.py, syncthing_client.py, truenas_client.py, runtime_id.py, help.py, the sign-in half of cli_tools.py (pty/token capture) and most of ai_providers.py. These modules have been through several earlier hunts (dash-release-*, trust-model-*). The new 2026-09-24 triage code got the most attention.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/broll.py:232 and music.py:242: same previous-secret and first-cookie identity gaps as bug-dash-ops-2/3.
