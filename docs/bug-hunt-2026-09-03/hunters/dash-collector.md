# dash-collector — the collector loop, the ALERT_KINDS registry, alert delivery, notices/invariants/protection/recovery/health

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/alerts.py` (2080 lines, ~95% — settings, password store, the
  clock, all 40 checks, `scan`, `compose_weekly`, `_send_smtp`, `_send_webhook`, `send`,
  `_is_open`, `deliver`, `run_cycle`)
- `dashboard/src/ccsync_dashboard/collector.py` (~40% — module header, `Collector.__init__`,
  `_loop`, `run_cycle`, `_timed`, `_run_invariants`, `_run_alerts`, `_run_inventory`)
- `dashboard/src/ccsync_dashboard/notices.py` (~80% — `run_checks` and every `_check_*`)
- `dashboard/src/ccsync_dashboard/invariants.py` (~35% — `Outcome`, `evaluate` tail, `run_cycle`,
  `page_view` head)
- `dashboard/src/ccsync_dashboard/protection.py` (~40% — `NasProbe`, `Ctx`, `run_cycle`, states)
- `dashboard/src/ccsync_dashboard/recovery.py` (~45% — snapshot path handling, `_under`,
  `preview_restore`, `restore_into_quarantine`)
- `dashboard/src/ccsync_dashboard/health.py` (~60% — statuses, lane chips, disk)
- supporting: `db.py` (alert_log / notices / invariant_results helpers, `NOTICE_KINDS`),
  `app.py` (`CollectorWatchdog`), `api.py` (`/api/v1/health`, the four recovery routes),
  `ui.py` (recovery partials), `docs/SELF_DIAGNOSIS.md` sections 5-9.

Tests run:
`dashboard\.venv\Scripts\python.exe -m pytest tests/test_alerts.py tests/test_collector.py
tests/test_notices.py tests/test_invariants.py tests/test_protection.py tests/test_recovery.py
tests/test_health.py tests/test_crash_report.py -q` -> **203 passed** (86.9 s).
Plus three ad-hoc scripts from the dashboard venv (in the scratchpad, not the repo).

## Findings

### dash-collector-1 — a check that CRASHED is printed in the weekly report's "CHECKED AND FOUND NOTHING WRONG" list
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/alerts.py:1786` (`clean = [k for k in ALERT_KINDS if not by_kind.get(k.kind)]`), against `alerts.py:1560-1576` (`scan` files a failed check under `CHECK_FAILED.kind`, not under its own kind)
- What: when a check raises, `scan()` appends a finding whose `kind` is `check_failed` and whose
  `subject` is the failing kind's name. `compose_weekly` computes the "quiet" list by asking
  whether each registry kind produced findings *under its own kind* - which a crashed check never
  does. So the crashed kind is counted and printed as `ok - <its what>`, in the same report that
  separately lists it under `COULD NOT BE CHECKED`. `deliver()` gets this right
  (`alerts.py:1998-2000` subtracts the `check_failed` subjects); only the report does not.
- Failure scenario: `_check_breaker` raises (e.g. `build_editors_view` returns a row where `guard`
  is a string, or any of the several checks that touch `shutil`/`Path`/the NAS mount). The Monday
  report says `CHECKED AND FOUND NOTHING WRONG (40 of 40)` including
  `ok - a computer's proxy download brake`, while a tripped lane B breaker sits unreported. The
  owner reads the exact reassurance the module's docstring says must never be printed.
- Evidence: ad-hoc run against a migrated temp DB with `ALERT_KINDS[0].check` replaced by a
  raising function:
  ```
  '  [check_failed] breaker_tripped'
  "      The check for 'a computer's proxy download brake' could not run, ... Treat it as unchecked, not as fine."
  "  ok - a computer's proxy download brake"      <-- the same kind, in the clean list
  'COULD NOT BE CHECKED (1)'
  '  breaker_tripped: RuntimeError: kaboom'
  ```
- Ledger: new (KNOWN_BUGS:6118-6123 documents the section; nothing records this defect)
- Suggested fix: build the clean list the way `deliver` does - subtract the `check_failed`
  findings' subjects: `failed = {f["subject"] for f in by_kind.get(CHECK_FAILED.kind, [])}` and
  `clean = [k for k in ALERT_KINDS if not by_kind.get(k.kind) and k.kind not in failed]`, and make
  the `(n of 40)` count match.

### dash-collector-2 — an invariant whose check RAISES silently clears its own broken subjects, closes the operator's notices, and mails "this has cleared"
- Severity: medium (arguably high: it is the one failure mode both modules exist to prevent)
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:2889-2895` (`record_invariant_result`'s unconditional
  DELETE of subject rows) + `invariants.py:795-821` (`run_cycle` passes `subjects=[]` for a
  `check_failed` outcome and omits those subjects from `clear_notices_of_kind`'s keep-list) +
  `alerts.py:1332-1359` (`_check_invariants` reads `db.broken_invariants`, so it emits nothing and
  does NOT raise, leaving `invariant_broken` inside `deliver`'s `checked_kinds`)
- What: `evaluate()` turns an exception into `Outcome(CHECK_FAILED, ...)` with an empty `subjects`
  list. `record_invariant_result` then writes the summary row and executes
  `DELETE ... WHERE invariant=? AND subject<>'' AND subject NOT IN ('')`, wiping every previously
  broken subject row for that invariant. `run_cycle` likewise leaves those subjects out of the
  `invariant_broken` keep-list, so `clear_notices_of_kind` closes their notices. The alert kind
  `invariant_broken` then produces no findings without raising, so `deliver()` treats every one of
  those subjects as RECOVERED and sends `CC Sync: cleared - ... - This has cleared on its own or
  somebody fixed it. No action is needed.`
- Failure scenario: invariant `tick_is_shared` is broken for `alex/base-rig`. Next cycle its check
  raises (a transient `sqlite3.OperationalError`, a Syncthing shape change). The invariants page
  loses the subject row, the home page's PROBLEMS panel loses the notice, and the admin is mailed
  that it cleared - while the tick is still unshared. Only a generic `invariant_check_failed`
  notice keyed on the invariant name remains, which does not name the subject.
- Evidence: script against a migrated temp DB:
  ```
  after broken : [{'invariant': 'tick_is_shared', 'subject': 'alex/base', ...}]
  open notices : [{'kind': 'invariant_broken', 'subject': 'tick_is_shared: alex/base', 'cleared_at': None}]
  after failed : []                                             <-- broken_invariants() is now empty
  open notices : [{... 'cleared_at': '2026-09-03T02:52:56+00:00'}]  <-- and the notice is closed
  ```
- Ledger: new (the SYS-9 work package is KNOWN_BUGS:7827; this is not recorded)
- Suggested fix: in `record_invariant_result`, only run the subject DELETE when the verdict is a
  verdict (`state in (OK, BROKEN)`); on `check_failed`/`not_checked` leave the previous subject
  rows in place (stale, but stamped with their old `checked_at`) or mark them `check_failed`. And
  in `invariants.run_cycle`, seed `broken_subjects` with the still-stored subjects of any
  invariant that could not run, so `clear_notices_of_kind` does not close them.
  `protection.run_cycle` has the same recovered-mail edge, but it at least files a
  `protection_unverifiable` warn naming the line, so it is a lesser case of the same shape.

### dash-collector-3 — the SMTP sink negotiates STARTTLS with no SSL context, so the certificate and hostname are never verified
- Severity: medium (security)
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/alerts.py:1874` (`client.starttls()`)
- What: `smtplib.SMTP.starttls()` with `context=None` builds `ssl._create_stdlib_context()`, which
  has `check_hostname=False` and `verify_mode=CERT_NONE`. The connection is encrypted but
  unauthenticated: anyone able to answer on `alerts_smtp_host:port` (a hijacked DNS answer, an
  ARP/router position on the NAS's LAN) gets a clean STARTTLS handshake and is then handed
  `client.login(user, password)` with the stored SMTP password in plaintext, followed by an alert
  body naming every editor, machine and exactly what is broken. The module is otherwise very
  careful with this secret (0600 file, `mask()`, never echoed in a refusal), and the webhook path
  correctly refuses non-https at both save and send time - the mail path is the hole.
- Failure scenario: a customer configures Gmail/Office365 relay with an app password. An attacker
  on the NAS's network answers port 587; the dashboard authenticates to them and hands over the
  app password plus the fleet's diagnosis. Nothing is logged as unusual - `send()` records `ok=1`.
- Evidence: `dashboard\.venv\Scripts\python.exe` (3.12.10) -
  `inspect.getsource(smtplib.SMTP.starttls)` shows `if context is None: context = ssl._create_stdlib_context()`,
  and `ssl._create_stdlib_context()` reports `check_hostname False verify 0`.
- Ledger: new
- Suggested fix: pass a verifying context - `client.starttls(context=ssl.create_default_context())`
  - and surface `ssl.SSLCertVerificationError` as an `AlertError` naming the host so a self-signed
  internal relay is a readable refusal (with an explicit opt-out setting if a site needs one),
  rather than silently unverified for everyone.

### dash-collector-4 — a cleared WARN can stop being clearable, and then that warn never fires again for that subject
- Severity: medium
- Confidence: PLAUSIBLE (mechanism read end to end; the trigger is row volume)
- Where: `dashboard/src/ccsync_dashboard/alerts.py:2011-2021` (`_open_subjects` derives its
  candidate set from `db.fetch_alerts(conn, limit=500)`) + `db.py:5219`
  (`fetch_alerts` hard-caps the limit at 500) + `alerts.py:1983-1984` (`if was_open and severity != SEV_ERROR: continue`)
- What: a WARN is announced once and then, for as long as `_is_open` says it is open, `deliver`
  `continue`s without writing any further `alert_log` row. Its single row therefore ages out of the
  most recent 500 while ERROR kinds write a row per subject per day. Once it has scrolled out,
  `_open_subjects` no longer offers it, so no `<kind>.ok` record is ever written; `_is_open`
  (which queries `alert_log` directly, not the 500-row window) keeps answering True for ever. That
  subject's warn is permanently muted, including when the condition recurs.
- Failure scenario: `folders_unfiltered` fires once for `ruskin/RUSKIN-PC`. Twenty-five days later
  (20 open error findings x 1 row/day fills the window) the folder gets filtered and re-loses its
  filter. Nothing is sent, on the page or by mail, because the ledger still says that subject is
  alerted. Same for `fleet_halt`, `crashes`, `thread_restarts`, `upgrade_reverted`,
  `protection_unverifiable`.
- Evidence: read-through of `_open_subjects` / `_is_open` / `deliver`; `fetch_alerts`'s
  `max(1, min(int(limit), 500))` means the caller cannot widen the window.
- Ledger: new
- Suggested fix: derive the open set from a query that does not depend on recency - e.g. a
  `SELECT DISTINCT kind, subject FROM alert_log WHERE kind IN (...)` (or a
  `last_alert_at`-per-subject query) - instead of paging the last 500 rows.

### dash-collector-5 — the webhook URL is a bearer credential and it lives in the database, unlike the SMTP password
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/alerts.py:136` (`alerts_webhook_url` in `SETTING_KEYS`,
  written into `site_settings`), `alerts.py:1936` (`sent_to = url` is then stored verbatim in
  `alert_log.sent_to` on every send), against `alerts.py:230-234` (the comment putting the SMTP
  password in a file precisely so "a database backup must not be a working credential")
- What: every common webhook receiver (Slack `hooks.slack.com/services/T…/B…/…`, Teams, Discord)
  puts the secret in the path of the URL. That URL is stored in `site_settings`, is echoed back in
  `settings_view()`, and is copied into an `alert_log` row for every delivery - so a database
  backup, a support dump of `site_settings`, or the Alerts page's "what was sent" list all carry a
  working credential, which is exactly the property the SMTP password was deliberately kept out of
  the database to avoid.
- Failure scenario: a `broll.db`/`ccsync.db` backup handed to support (or a restored snapshot on a
  developer laptop) contains a live Slack webhook for the customer's ops channel.
- Evidence: read-through; `mask()` is applied to the SMTP password in `settings_view` and to
  nothing else.
- Ledger: new
- Suggested fix: store the webhook URL's secret half beside the SMTP password under
  `<data>/secrets/alerts/` (or store the whole URL there and keep only its origin in
  `site_settings`), and record the origin - not the full URL - in `alert_log.sent_to`.

### dash-collector-6 — `machine_disk_low` / `machine_trash_oversize` have no freshness gate, so a decommissioned machine keeps a permanent warn from a months-old reading
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/notices.py:486-516` (`disk_at` is SELECTed and never read)
- What: the check reads `disk_root_free_bytes` straight off `machine_state` with no age test, and
  `clear_notices_of_kind` re-keeps the subject every cycle, so the notice can only clear if that
  machine reports again with more space. `alerts._check_disk_low` at least reports its measurement
  age in the detail line; this one does not. The unused `disk_at` in the SELECT list is evidence a
  freshness gate was intended and dropped.
- Failure scenario: an editor's laptop is retired at 30 GB free. The home page's PROBLEMS panel
  carries `<editor>/<laptop> has 30 GB free ...` for ever, with a fix ("untick a project for that
  computer") that cannot be acted on, and it never clears.
- Ledger: new
- Suggested fix: skip (or explicitly stale-mark) a row whose `disk_at` is older than the silent
  threshold `alerts.SILENT_SECONDS`, and let `clear_notices_of_kind` close it.

### dash-collector-7 — `feed_unreachable` / `feed_runtime_mismatch` render [ NOT CHECKED ] for ever on any site with no vendor feed configured
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/notices.py:552-554` (`if not settings.release_feed_url: return`)
  against `db.py:2686-2712` (`NOTICE_CHECKS_META` / `notice_check_times`: a kind with no evidence
  renders `[ NOT CHECKED ]`)
- What: the early return skips both `db.notice` and `db.clear_notice`, which are the only two
  functions that stamp `_mark_notice_checked`. On the vendor default (no `DASH_RELEASE_FEED_URL`),
  two of the registry's kinds sit permanently at `[ NOT CHECKED ]`, which the panel's own contract
  reads as "no writer runs anywhere in this build" - i.e. a gap - rather than "not applicable here".
- Ledger: new
- Suggested fix: on the early-return path call `db.clear_notices_of_kind(conn, "feed_unreachable",
  (), now=now)` (and the mismatch kind) so the panel says CHECKED, or give the panel an explicit
  NOT APPLICABLE state for a feature this deployment does not have.

### dash-collector-8 — `health.lane_chip_status` is defined twice; the first definition is dead
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/health.py:153` (shadowed) and `health.py:244` (the live one)
- What: the pre-SYS-1 colour-only implementation is still in the file above the SYS-1 rewrite and
  is unconditionally overwritten at import. It is not merely dead: it encodes the *old* rule (no
  stall test), so anyone maintaining the "lane dot colour" logic can edit a copy that has no
  effect, and a reader comparing the two can reasonably conclude the stall is not applied.
- Evidence: two `def lane_chip_status` at module level, the second at line 244; Python keeps the
  last.
- Ledger: new
- Suggested fix: delete the definition at line 153.

## Coverage note
- Not covered: `crash_report.py` (opened only via the passing suite, not read line by line),
  the bulk of `collector.py`'s Syncthing cycles (`_run_config` / `_run_enforce` /
  `_run_connections` / `_run_completion` / `_run_remoteneed` / `_run_prune` and the retarget
  branch) - the enforce blast-radius brake in particular is worth its own pass, most of
  `invariants.py`'s ten checks and `protection.py`'s eight lines (I read the registries' plumbing,
  not each predicate), and `recovery.run_drill` / `page_view` / the printed runbook.
- Checked and found nothing: every kind in `db.NOTICE_KINDS` (35) has at least one writer module
  (scripted check across the package) - the CLAUDE.md "registered kind with no writer" invariant
  holds today; recovery's path handling (`_snapshot_dir`, `_under`) refuses traversal correctly and
  all four routes are `_require_admin`-gated; `restore_into_quarantine` does call
  `dashboard_update.snapshot_before` first, per CLAUDE.md; the unauthenticated branch of
  `/api/v1/health` returns only `{ok, version}`; the NAS probe's clients carry timeouts (30 s
  TrueNAS / 15 s DSM), well inside the 900 s wedged threshold; the em-dash scan test covers this
  package's string literals and passes.
- What the suite does not cover: no test drives `compose_weekly` with a raising check (which is
  why finding 1 survives), no test drives `record_invariant_result` with a `check_failed` verdict
  after a `broken` one (finding 2), no test exercises `_send_smtp`'s TLS layer (the suite
  substitutes `_smtp_class`, which is exactly the thing that would break - finding 3), and
  `_open_subjects` is only ever tested with a handful of rows, well inside the 500-row window
  (finding 4).

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/api.py:1331-1345`: `/api/v1/health`'s `_open_alerts_block` runs a
  full `alerts.scan()` (40 checks, `build_editors_view`, `shutil.disk_usage`, a `projects_dir`
  `iterdir`, `protection.page_view`) on every authenticated request, even though `run_cycle` stores
  `db.META_ALERTS_OPEN` specifically so a reader need not - contradicting `_check_invariants`'s own
  docstring ("a scan that ran them again per `/api/v1/health` call would be a scan somebody turns
  off").
