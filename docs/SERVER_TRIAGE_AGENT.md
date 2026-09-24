# The server triage agent

Owner request, 2026-09-24: a Claude Code (Opus 5.5) agent on the server that
runs twice a day, reads everything the dashboard knows is open, stuck or
failing, and emails the owner an analysis with suggested actions - and a
reply to that email carries the chosen actions out.

Owner decisions (2026-09-24):

| question | answer |
|---|---|
| authority of the scheduled run | **read-only**: it reads and emails, it never changes anything itself |
| schedule | **06:00 and 18:00, Asia/Taipei** |
| a run with nothing to say | **always send** (an "all clear" mail), so silence means the agent is broken |
| where replies are read | **the owner's own inbox, filtered**: replies go to `Alex+ccsync@thecreatorsclub.co` and only mail to that address is looked at |
| what a reply can make it do | **dashboard actions only**: a fixed catalogue of operations that already have a button; never a shell |

## 1. Shape

Everything lives in the dashboard container, in three modules:

- `triage.py`: the schedule, the evidence bundle, the Claude Code run, the
  report email, the run ledger.
- `triage_actions.py`: the action CATALOGUE and its executor.
- `triage_mail.py`: the IMAP reply poller, reply authentication, reply
  interpretation, the confirmation email.

It is gated by an alerts setting, `alerts_triage` (default `"0"`, so off in
the vendor build and on every site until an admin turns it on), AND by the
Claude Code CLI being usable (`site_store.feature_enabled(...,
"ai_cli_providers")` plus `ai_providers.cli_path(conn, CLAUDE_CODE,
settings)` non-empty). The Anthropic API provider is NOT a fallback: the run
needs Claude Code's read-only tools over files, which the SDK path does not
have. No bundled binary (CLAUDE.md, COMMERCIAL_READINESS item 1): it uses the
CLI the admin already installed through Settings -> AI providers, through
`cli_tools.cli_env` exactly as `cards_ai.Runner._cli` does.

## 2. The scheduled run (read-only)

**Schedule.** New alerts settings (in `alerts.SETTING_KEYS`, NOT
`site_store.KEYS`, for the reason the block above SETTING_KEYS gives):

- `alerts_triage` bool, default `"0"`
- `alerts_triage_hours` str, default `"6,18"`, validated: comma-separated
  integers 0-23, 1-4 of them
- `alerts_triage_reply_to` str, default `""`: the Reply-To address; blank
  disables replies (the report is still sent)
- `alerts_imap_host` str, default `""` = derived from `alerts_smtp_host`
  (`smtp.gmail.com` -> `imap.gmail.com`, otherwise `smtp.` -> `imap.`), port
  993, implicit TLS, certificate verified (the same `alerts_smtp_verify_tls`
  opt-out, never a silent fallback)

Hours are read in `alerts_timezone` (`alerts._zone_or_utc`). The live site
has none set (UTC); deploying this sets `alerts_timezone = Asia/Taipei`,
which also moves the Monday report from 08:00 UTC to 08:00 Taipei.

"Due" follows `alerts.weekly_due` exactly: the most recent slot (any of the
hours, today or yesterday) at or before now in the zone; owed when there is
no `ok=1` `alert_log` row of kind `triage` at or after that slot, subject to
`alerts._retry_due`'s backoff. Durable, not a timer: a restart at 05:59 runs
it once, a container down at 06:00 runs it late, six restarts do not run it
six times.

**Where it runs.** `alerts.run_cycle` calls `triage.maybe_start(settings,
now)` after the heartbeat. That only decides and starts a DAEMON THREAD with
its own connection (`db.connect(settings.db_path)`); the run itself takes
minutes and must never hold the collector thread (the collector watchdog
replaces a container whose cycle stalls). One run at a time: a module lock
plus a `meta` row `triage_running_since`; a row older than 90 minutes is a
dead run and does not block.

**Evidence bundle.** A per-run directory `<data>/triage/<run id>/` (the data
volume's parent of `db_path`, like `cards_ai._scratch_dir`), holding
`evidence.json` built only from readers that already exist:

- open notices (`db.open_notices`, a generous limit)
- the last 48 h of `alert_log` and the last scan's open counts
  (`db.META_ALERTS_OPEN`)
- invariants (`invariants.page_view`)
- collector health (`db.fetch_collector_status`)
- the fleet grid (`api.build_editors_view`): every machine's version, lanes,
  why-not-syncing sentence, guard (stalls, crashes, blocked reason, breaker,
  halt, upgrade refusals)
- transfers + queue (`api.build_transfers_view`, with CR-311's `held`)
- open jobs (`db.list_jobs(state="open")`) and counts by kind/state
- packages (`api.build_packages_view`): current builds vs what each machine
  runs
- the previous run's action outcomes (so it does not re-suggest what was just
  done or refused)

Each section is built in its own try/except: a reader that raises becomes
`{"error": "..."}` in that section, never a failed run. Then a SCRUB pass
over the serialised JSON: anything matching `sk-[A-Za-z0-9_-]{8,}`,
`cce1\.[A-Za-z0-9._-]+`, `ghp_\w+`, a `password`/`token`/`secret`/`api_key`
field value, is replaced with `[redacted]`. Nothing from `site_settings` or
`<data>/secrets` is ever read into the bundle.

**The Claude Code run.** Argv, never a shell:
`[cli, "-p", "--output-format", "json", "--model", <alias>,
"--allowedTools", "Read,Grep,Glob", "--disallowedTools",
"Bash,Edit,Write,MultiEdit,NotebookEdit,WebFetch,WebSearch,Task",
"--add-dir", <installed ccsync_dashboard package dir>]`, cwd = the run
directory, env = `cli_tools.cli_env(settings, CLAUDE_CODE)`, prompt on
stdin, timeout 20 minutes. Model: `cards_ai.cli_model_arg(settings,
"claude-opus-5-5")` (the family alias, CR-309). The prompt (a module
constant, `TRIAGE_PROMPT`) says: you are reviewing a video-sync fleet's
server; read `evidence.json`; the source of the running dashboard is at the
added dir; say what needs a person, ranked, each with the evidence and the
suggested action; suggest actions ONLY from the catalogue (rendered into the
prompt from `triage_actions.CATALOGUE`: name, parameters, what it does, when
it is right); a code defect is a finding with a `code_fix_prompt` (a
paste-ready prompt for a Claude Code session in the repo), never an action;
answer with ONE JSON object:

```json
{"subject": "...", "headline": "...", "all_clear": false,
 "findings": [{"title": "...", "severity": "error|warn|info",
               "evidence": "...", "suggestion": "...",
               "action_refs": [1], "code_fix_prompt": ""}],
 "actions": [{"n": 1, "action": "resume_breaker",
              "params": {"editor": "ruskin", "machine": "DESKTOP-LQQ41TC"},
              "why": "..."}]}
```

Parsing: `cards_ai._cli_reply` for the CLI envelope, then the JSON object in
`result` (tolerate a fenced block). Every proposed action is VALIDATED
against the catalogue (`triage_actions.validate`: known name, required
params present and well-typed, and the target exists now, e.g. the machine
row). An invalid one is dropped and listed in the email as "suggested but not
offered: <reason>".

**The report email.** Plain text, sent with `alerts._transmit`, subject
prefixed `[CC Sync] Server check`, `Reply-To: alerts_triage_reply_to` when
set. Body: the headline; the findings, numbered; the offered actions as
`[1] Resume proxy download on ruskin/DESKTOP-LQQ41TC - <why>`; the code-fix
prompts under their findings; and the footer:

```
To carry any of these out, reply to this email, e.g. "do 1 and 3".
Reference: CCT-<token>   (valid until <local time>, each action runs once)
```

No em dashes anywhere in the body (the owner's rule; the model's text is
passed through a replace of U+2014 with " - "). `_transmit` needs a
`reply_to` keyword threaded to `_send_smtp`; webhook sinks ignore it.

**Failure still sends.** A CLI that is missing, exits non-zero, times out or
answers with no parseable object produces a FALLBACK email: "The server
check could not run its analysis: <reason>", followed by a plain summary
made in code from the bundle (open notices' titles, the fleet grid's
why-sentences, collector kinds not ok). "Always send" means an absent email
is the only sign of a dead agent, so the agent's own failure must be an
email, not a log line.

**Ledger.** `alert_log` row of kind `triage` (ok = the email went out),
plus table `triage_runs` (schema step): `id, started_at, finished_at,
status (ok|fallback|failed), token_hash, token_expires_at, report_json,
email_ok, detail`. The token is 128 bits (`secrets.token_urlsafe(16)`),
stored only as sha256; valid 48 h. And `triage_actions`: `run_id, n, action,
params_json, why, state (offered|done|refused|failed|expired), result,
reply_message_id, acted_at`. Keep 60 days of runs (prune in the same pass).

## 3. The reply path

**Polling.** `triage_mail.poll(settings)` runs from the same daemon
machinery every 120 s while `alerts_triage == "1"` and a reply address is
set. IMAP4_SSL to the derived host, login with `alerts_smtp_user` and the
SMTP password (`alerts.read_password`; a Gmail app password works for IMAP),
`SELECT INBOX` read-only is NOT enough (we mark handled mail); search
`UNSEEN TO "<reply_to>" SINCE <2 days ago>`. Never look at any other mail:
the search is the fence, and a message whose To/Cc does not contain the
reply address after parsing is skipped. Each handled message: set `\Seen`,
record its Message-ID in `triage_replies` (`message_id UNIQUE, received_at,
from_addr, run_id, verdict, detail`) so a message is never acted on twice
even if the flag is lost. The IMAP password never reaches a log or the
bundle.

**Authentication, all required.** A reply is acted on only if:

1. `From` (parsed with `email.utils.parseaddr`, compared case-folded) is one
   of the addresses in `alerts_smtp_to`;
2. the receiving server's `Authentication-Results` (the TOPMOST one, which
   the receiving server adds and a sender cannot pre-empt) says `dkim=pass`
   or `dmarc=pass` for the From domain;
3. the body or subject contains `CCT-<token>` whose sha256 matches a
   `triage_runs` row that has not expired.

A reply failing any of these is recorded with its reason and NOT answered by
email (an answer to a forged sender is backscatter); it becomes a `warn`
notice `triage_reply_refused` (registered in `db.NOTICE_KINDS` WITH its
writer, per the self-diagnosis rule) naming the reason, so a genuine reply
that failed a check is visible on the home page. Point 2 must be verified
against a REAL reply from the owner's Gmail after deploy before trusting it;
if Google Workspace omits the header for same-domain mail, the check fails
closed and the notice says so.

**Interpretation.** The reply text (quoted history stripped: cut at the
first `On ... wrote:` line or `>`-quoted block) and that run's offered
actions go to a second, small `claude -p` call (no tools at all:
`--disallowedTools` everything, `--model sonnet`, 3-minute timeout) that
answers `{"do": [1, 3], "skip": [2], "unclear": "...", "note": "..."}`.
A reply of only digits/"all"/"none" is parsed in code without the model.
Numbers not offered in that run are ignored and reported.

**Execution.** For each chosen number: the action must be `offered` (not
done, not expired), re-validated NOW (the machine still exists; for
`resume_breaker`, the breaker is still tripped, etc.), then executed through
the catalogue's executor, which calls the SAME function the dashboard
button's route calls, with `actor = "triage-email:<from>"`. Never a new
mutation path, never a shell, never a raw SQL write. Each outcome goes to
`triage_actions` and the dashboard's own audit trail (whatever the button
already writes).

**Confirmation email.** One reply per handled message, `Re: <subject>`,
listing each action: done / refused (why) / failed (error) / not
understood, plus anything the interpreter flagged as unclear.

## 4. The catalogue (v1)

Each entry: `name`, `params` (typed), `summary` (one line for the email),
`when` (for the prompt), `validate(conn, settings, params) -> str | None`,
`execute(conn, settings, params, actor) -> str`. v1 is limited to
operations that exist today as admin buttons; the builder maps each to its
route's function and cites it:

| action | button today |
|---|---|
| `push_update(editor, machine)` | Settings -> Packages [ UPDATE NOW ] (`db.request_machine_update`) |
| `cancel_push(editor, machine)` | its [ CANCEL ] |
| `resume_breaker(editor, machine)` | FLEET [ RESUME ] (CR-45) |
| `clear_fleet_halt()` / `keep_halted()` | the halt banner |
| `cancel_job(job_id)` | `POST /api/v1/jobs/{id}/cancel` |
| `dismiss_notice(notice_id)` | PROBLEMS THE SERVER FOUND [ DISMISS ] |
| `approve_device(device_id, editor)` | Settings -> Users pending devices |
| `request_diagnostics(editor, machine)` | [ ASK THIS COMPUTER WHY ] |
| `nudge_collector()` | the tick's nudge (`collector.nudge`) |

Anything not in this table cannot be done by reply. Adding one later is a
catalogue row plus its test.

## 5. Settings UI

Settings -> Alerts gains a SERVER CHECK block: the on/off box, the hours, the
reply address, the last run (time, status, link to its report) and a
[ RUN NOW ] button (starts a run regardless of the schedule; still one at a
time). No em dashes in any of it.

## 6. Tests (dashboard suite)

Schedule (slots, restart, backoff, zone), bundle (a raising reader, the
scrub), argv (read-only tools, never Bash), parse/validate (bad action
dropped), fallback email on CLI failure, report body (token footer, no em
dash), reply auth (each of the three checks failing alone), quote
stripping, digits-only parse, idempotency (same Message-ID twice, same
action twice, expired token), execution through the button's function (a
stub proves the route's function was called), confirmation text. No test
touches a real CLI, SMTP or IMAP server.

## 7. Built (2026-09-24, dashboard 0.7.53, schema v57)

Uncommitted in the working tree; not deployed.

**Files.**

- `dashboard/src/ccsync_dashboard/triage.py` (new): schedule
  (`previous_slot`, `triage_due`), `cli_gate`, evidence bundle
  (`build_bundle`, `scrub`), the Claude Code run (`build_argv`, `run_cli`,
  `parse_report`, `clean_report`, `validate_actions`), the report and fallback
  emails, the ledger (`expire_actions`, `prune`), the machinery
  (`maybe_start`, `start_run`, the reply poller thread), `status_view` and
  `report_text` for the page.
- `dashboard/src/ccsync_dashboard/triage_actions.py` (new): `CATALOGUE`,
  `validate`, `execute`, `set_collector`.
- `dashboard/src/ccsync_dashboard/triage_mail.py` (new): `poll`,
  `handle_message`, `auth_results_pass`, `find_run`, `strip_quotes`,
  `parse_simple`, `interpret`, `execute_choices`, `compose_confirmation`.
- `db.py`: `SCHEMA_V57` (`triage_runs`, `triage_actions`, `triage_replies`)
  as migration step 57; `NOTICE_KINDS["triage_reply_refused"]`.
- `alerts.py`: the four settings (`alerts_triage`, `alerts_triage_hours`,
  `alerts_triage_reply_to`, `alerts_imap_host`) with their validators;
  `_transmit(..., reply_to=)` threaded to `_send_smtp` as a Reply-To header
  (webhook ignores it); `run_cycle` calls `triage.maybe_start` after the
  heartbeat and its commit, inside a try that can never cost the pass.
- `app.py`: registers the collector with `triage_actions.set_collector`
  (and clears it on shutdown) so `nudge_collector` can reach it from the
  poller thread.
- `ui.py` + `templates/partials/admin_alerts.html`: the SERVER CHECK block in
  Settings -> Alerts (on/off, hours, reply address, IMAP host, the gate's
  state, last run with `[ READ ITS REPORT ]` -> `GET
  /admin/alerts/triage/{id}` as plain text, last reply poll, `[ RUN NOW ]` ->
  `POST /partials/admin/alerts/triage/run`, audited `alerts.triage_run`).
- Tests: `dashboard/tests/test_triage.py`, `dashboard/tests/test_triage_mail.py`.
- `__init__.py` / `pyproject.toml`: 0.7.52 -> 0.7.53 (a schema step ships
  with its own version, as v56 did in 0.7.51).

**The catalogue as shipped.** Each executor calls the function the button's
route calls (file:line cited in `triage_actions.py`):

| action | calls | route(s) |
|---|---|---|
| `push_update(editor, machine)` | `db.request_machine_update(..., current build)` | `ui.partial_admin_machine_update`, `api.api_push_machine_update` |
| `cancel_push(editor, machine)` | `db.clear_machine_update_request` | `ui.partial_admin_machine_update_cancel`, `api.api_cancel_machine_update` |
| `resume_breaker(editor, machine)` | `db.request_lane_b_resume` | `api.api_resume_machine_lane_b`, `ui.partial_admin_resume_lane_b` |
| `clear_fleet_halt()` | `db.set_fleet_halt(active=False)` | `ui.partial_admin_set_fleet_halt`, `api.api_set_fleet_halt` |
| `keep_halted()` | `db.set_fleet_halt(active=True, extend=True)` | the same two |
| `cancel_job(job_id)` | `db.request_job_cancel` | `api.api_cancel_job`, `ui.partial_admin_cancel_job` |
| `dismiss_notice(notice_id)` | `db.dismiss_notice` | `ui.partial_notice_dismiss` |
| `request_diagnostics(editor, machine)` | `db.request_diagnostics` | `ui.partial_admin_ask_why`, `api.api_admin_ask_why` |
| `nudge_collector()` | `collector.nudge()` | `api._nudge_collector` |

Validators are the routes' own pre-checks (machine exists, a current build is
published, the breaker is tripped, the halt is active, the job is not
terminal, the notice is open), run when the model proposes and again when a
reply chooses. A refused or failed action is final (`refused`/`failed`); a
choice of it again answers "not done again".

**Dropped or deviating.**

- `approve_device` is NOT in v1. Its logic is inline in two routes that
  disagree (the JSON route audits `device.approve`, the Users page partial
  does not), the Syncthing pending-device list it would pick from is not in
  the evidence bundle, and it is the one entry that grants a new device
  access to footage. Adding it means extracting one shared helper from
  `api.api_admin_approve_device` / `ui.partial_admin_approve_device`, which
  changes the partial's behaviour (it would start auditing): an owner-visible
  change for its own commit.
- The schedule is not due, and [ RUN NOW ] refuses, while `alerts_sink` is
  `none`: a report with nowhere to go is not worth a Claude Code session.
  [ RUN NOW ] also refuses while `alerts_triage` is off.
- The CLI gate is not a silent off-switch: with the check on and Claude Code
  unavailable (feature off or no executable), each scheduled run sends the
  FALLBACK email naming why, and the CLI is never invoked. "Always send"
  wins over going quiet.
- Replies are polled only when the check is on, a reply address is set AND
  the sink is `smtp` (the IMAP login is the SMTP account).
- A reply of digits, "all" or "none", optionally prefixed "do" and joined by
  commas/"and"/"&" (the footer's own "do 1 and 3"), is parsed in code; only
  prose goes to the model.
- The refused-reply notice is keyed by the check that failed (`sender`,
  `authentication`, `reference`), so a forged-mail flood is at most three
  cards; the sender's address is in the body. A message the IMAP search
  matched whose parsed To/Cc is not the reply address is recorded and left
  UNSEEN.
- The confirmation email carries the same Reply-To and the run's reference,
  so a second reply ("do 2") to the confirmation works; idempotency makes a
  repeat harmless. It is logged as alert kind `triage_reply`, which never
  satisfies a slot.
- The last reply poll's outcome is kept in `meta.triage_imap_last_poll` and
  shown in the block, so a failing IMAP login is visible without the log.

**Must be verified live, before trusting the reply path.**

1. Send a real report and reply from the owner's Gmail; confirm the reply's
   TOPMOST `Authentication-Results` (the receiving server's) says `dkim=pass`
   or `dmarc=pass` with `header.i=@<domain>` / `header.from=<domain>`. If
   Google Workspace omits it for same-domain mail, every reply is refused
   with an `authentication` card: the check fails closed, by design.
2. IMAP is enabled on the Workspace account (Admin console and the user's
   Gmail settings) and the SMTP app password is accepted for IMAP login; the
   SERVER CHECK block's "Replies last read" line shows the result.
3. Set `alerts_timezone = Asia/Taipei` (Settings -> Alerts). This also moves
   the Monday report from 08:00 UTC to 08:00 Taipei. The save validates the
   zone with `zoneinfo`: if the image has no zone database it is refused
   with a message rather than silently running on UTC (the Windows test venv
   has none; the tests use a fixed +08:00 offset).
4. That the installed Claude Code CLI accepts the argv as built
   (`--allowedTools Read,Grep,Glob`, `--disallowedTools ...`, `--add-dir`)
   and denies an unlisted tool non-interactively in `-p` mode, and that a
   20-minute ceiling is enough for a full run over this fleet's evidence.
