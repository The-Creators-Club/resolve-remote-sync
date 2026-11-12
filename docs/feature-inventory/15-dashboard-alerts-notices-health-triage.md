# Dashboard: alerts, notices, invariants, health and the daily triage agent

Terms used throughout:

- **Finding**: one problem the dashboard has detected right now, about one
  **subject** (usually a computer written `editor/machine`, or a fixed phrase
  such as "the server").
- **Alert kind**: one named check in the alert registry. Each has a severity
  (`error` or `warn`), a title, a "what" line (used in the weekly report), and
  a check that returns zero or more findings.
- **Sink**: where alerts are delivered: `none`, `smtp` (email) or `webhook`.
- **Alert ledger**: the dashboard's record of every alert it composed, one row
  per (kind, subject) per send attempt, with whether delivery worked.
- **Notice**: a standing problem recorded on the dashboard home page panel
  "PROBLEMS THE SERVER FOUND", keyed by (kind, subject), each with a fix line.
- **Collector**: the dashboard's background loop that runs periodic jobs
  ("kinds") such as the alerts pass, the notices pass and the invariants pass.
- **Companion**: the CC Sync tray app on an editor's computer that reports to
  the dashboard.

## Alert settings (who configures what, defaults, validation)
(source: alerts.py)

- Stored per site, not published to editors' installers (`GET /api/v1/site`
  never carries them).
- Settings and defaults:
  - `alerts_sink`: `none` (default), `smtp` or `webhook`. Anything else is
    refused: "alerts_sink must be one of none, smtp, webhook".
  - `alerts_smtp_host`: text, no default.
  - `alerts_smtp_port`: default `587`; must be 1 to 65535 ("must be a port
    number between 1 and 65535"); blank allowed.
  - `alerts_smtp_user`, `alerts_smtp_from`: text.
  - `alerts_smtp_to`: one or more addresses separated by commas or semicolons.
  - `alerts_smtp_tls`: `1` (default) uses STARTTLS; `0` sends unencrypted.
  - `alerts_smtp_verify_tls`: `1` (default) verifies the mail server's
    certificate and host name; `0` is an explicit opt-out for a self-signed
    internal relay. A verification failure never falls back silently.
  - `alerts_webhook_url`: must start with `https://` or the save is refused
    ("the webhook URL must start with https:// (an alert body names your
    editors and computers)"). Also re-checked at send time.
  - `alerts_timezone`: an IANA zone name; an unknown name is refused when
    typed ("'X' is not a time zone this server knows (use an IANA name such as
    Europe/London)"). Blank falls back to a site `timezone` row if any exists,
    then UTC. If the container cannot load the zone at run time, it logs a
    warning and uses UTC for the schedule.
  - `alerts_weekly`: `1` (default) sends the weekly report.
  - `alerts_heartbeat`: `0` (default); `1` sends the daily "still here" message.
  - `alerts_digest`: three values. Blank (default) follows the sink: digest
    (one message per check cycle) for smtp, one message per finding for
    webhook. `1` forces digest, `0` forces one message per finding.
  - `alerts_triage`: `0` (default); `1` turns on the server triage agent.
  - `alerts_triage_hours`: default `6,18`. Hours 0 to 23, comma separated,
    deduplicated and sorted; at most 4 per day ("at most 4 checks a day"). A
    blank field saves the default, never "never".
  - `alerts_triage_reply_to`: one plain email address (strict pattern); blank
    disables replies to the triage report (the report is still sent).
  - `alerts_imap_host`: a host name; blank means derive it from the SMTP host.
- Every value: no control characters ("must not contain control
  characters"), at most 400 characters. Booleans accept `1`, `0` or blank
  (blank stored as `0`).
- An unknown key is refused ("'X' is not an alert setting").
- A save is all-or-nothing: every field is validated first; one bad field
  changes nothing.
- The webhook URL is shown masked past its origin (`https://host/…`). If a
  form posts back exactly that mask, the stored URL is kept unchanged.
- **Catch-up on first configuration**: when the sink changes from `none` to
  anything else, every ledger row recorded as "no sink configured" is re-filed
  as undelivered, so every finding still open is raised again on the next
  pass. The next digest then opens "CC Sync: here is everything currently open
  (N)" and says it is the catch-up, not N new faults.
- **SMTP password**: kept in a file `<data>/secrets/alerts/smtp_password`
  (mode 0600), never in the settings table.
  - Environment variable `DASH_ALERTS_SMTP_PASSWORD` overrides the file
    ("env wins"); the page then says the value came from the deployment.
  - Setting: refused if blank ("the password is blank"), over 400 characters,
    or containing control characters ("the password contains control
    characters, paste it again"). A write failure names the directory that
    must be writable by the container's user.
  - Clearing deletes the file.
  - The page only ever sees whether a password is set, its source, and a mask
    (first 3 and last 4 characters; values under 12 characters show only "…").
- **Per-kind switches ("which kinds are sent")**: an admin can switch off
  individual alert kinds. Stored as the list of kinds switched OFF, so a kind
  added by a later build is on by default. Every name must be a registry kind
  or the save is refused ("not an alert kind: …"). Unknown stored names are
  dropped on read.
  - A switched-off kind is still checked, still shown under CURRENTLY OPEN, in
    the weekly report and in the topbar count. Only the message is withheld,
    and no ledger row is written for it (so switching it back on sends a
    still-true condition as new).
  - An open alert of a switched-off kind that clears is closed silently
    ("closed without a message: this kind of alert is switched off").
  - Switching off a kind also silences "that check could not run" for it.
    "The whole scan failed" is always sent.
  - The page groups the kinds: editors' computers; sharing and fleet controls;
    this server; updates; projects and footage; fleet jobs; youtube downloads;
    b-roll.
- **Is the channel actually working** (shown on the protection line and
  invariant `alerts_deliverable`): green only when a sink is set AND it has
  delivered something (a successful row with a recipient) in the last 30
  days, AND the most recent failed attempt is older than the last success.
  Red sentences:
  - "no mail server and no webhook is set, so nothing this server finds is
    ever sent to anybody"
  - "the smtp channel is set up and has never managed to send anything: …"
  - "the smtp channel is set up but nothing has ever been sent through it"
  - "the last message this server tried to send did not go out: …"
  - "nothing has been delivered through the smtp channel since YYYY-MM-DD"
  - Green: "the smtp channel delivered something N hour(s) ago".

## The alerts pass (scan, deliver, schedule)
(source: alerts.py)

- Runs once per collector "alerts" cycle (the collector interval
  `interval_alerts`, 600 s by the code's own fallback). Every kind in the
  registry is evaluated, in registry order, then delivery runs, then the weekly
  report and heartbeat if owed, then the triage agent is offered a chance to
  start.
- The scan runs whether or not a sink is set; with sink `none` the findings
  still show on the Alerts page, the topbar count and `/api/v1/health`.
- **Check that raises**: becomes a finding of kind `check_failed` (error,
  title "a health check could not run") with the failing kind's name as the
  subject: "The check for '<what>' could not run, so this server does not know
  whether that is all right. Treat it as unchecked, not as fine." Fix: "Send
  us the container log from the NAS."
- **Whole scan fails** (cannot even gather state): a single `check_failed`
  finding, subject "the whole scan": "This server could not read its own state
  to check whether anything is wrong, so nothing below has been checked." No
  open alert is declared recovered on such a pass.
- **Cap per kind**: at most 40 findings per kind per pass. Beyond that a 41st
  finding is added under subject "and more of the same": "There are N of these
  and this server shows the first 40. The other M are real and are not listed
  here." Fix: "Open the dashboard and work through the list: something
  fleet-wide is usually behind this many at once." A capped kind is never
  treated as having recovered the subjects it could not list.
- **Open counts**: `{error: n, warn: n}` of the last scan are stored after
  each pass and drive the topbar chip on every page and `/api/v1/health`.
- **Repeat rule** (by severity):
  - `error`: sent when first found and then re-sent once per day (24 h dedup
    window) for as long as it stays true.
  - `warn`: sent once; not again until it has cleared and come back.
  - A finding may be marked "do not repeat" (said once while it stays true),
    "quiet" (say nothing and keep the ledger row where it is) or "withdrawn"
    (close an open row without any message, recorded as "closed without a
    message: that computer no longer reports what this checks").
  - The dedup reads any previous row, successful or failed, so a broken sink
    does not retry every cycle.
- **Recovery**: an open (kind, subject) that the scan no longer produces, for
  a kind that ran successfully and was not capped, is declared cleared.
  Message: subject "CC Sync: cleared - <title> - <subject>", body "This has
  cleared on its own or somebody fixed it. No action is needed." Recorded
  under `<kind>.ok`. "Open" is decided by comparing the last alert row with the
  last `.ok` row, so it survives a container restart.
- A `check_failed` that stops failing is also declared cleared.
- **Per-finding message** (non-digest mode): subject "CC Sync: <title> -
  <subject>", body = the diagnosis, then "What to do: <fix>", then "Detail:
  <technical line>", then "Open the CC Sync dashboard for the full picture."
  Body capped at 60,000 characters.
- **Digest message** (default for smtp): everything one pass would send goes
  out as ONE message, with one ledger row per finding sharing a batch id.
  - Subject, in priority order:
    - catch-up: "CC Sync: here is everything currently open (N)";
    - new findings: "CC Sync: 1 new problem: <title>" or "CC Sync: N new
      problem(s)";
    - only repeats: "CC Sync: still not fixed after D day(s): <first two
      headlines> and K more";
    - only recoveries: "CC Sync: cleared - <headline>" or "CC Sync: N
      problem(s) cleared".
  - Body: errors before warns. New findings as full blocks labelled "PROBLEM:"
    (error) or "TO LOOK AT:" (warn). Repeats as one line each under "STILL NOT
    FIXED" with "(open for D day(s))", followed by "The full description of
    each of these went out when it was first found. Nothing about them has
    changed." Recoveries as "CLEARED:" blocks. Then "Still open from before: N
    (see the HEALTH page)" when warns or non-repeating errors are still open.
  - "Days open" is counted from the first alert after the last recovery;
    minimum 1.
- **Time budget**: one pass may spend at most 120 s on sending; each single
  send is limited to 20 s. Findings not sent in time are not recorded and are
  offered again next pass. In digest mode it is all or nothing.
  - When anything was left over, notice `alerts_delivery_slow` (warn, subject
    "delivery") is filed: "Sending this server's alerts took longer than the
    120 seconds one pass is allowed, so N of them were left for the next pass.
    …" Fix: "On Settings, Alerts: press "Send a test" and time it. …" It is
    cleared on every pass that leaves nothing over.
- **Collector panel note** after a pass:
  - "S of T alert(s) sent this pass; the alert channel is slow";
  - with sink `none`: "N alert(s) were written down here and nobody was told:
    no alert channel is set up";
  - "N alert(s) could not be delivered";
  - otherwise "N problem(s) open" when errors are open.
- Every outgoing text (alerts, digests, weekly, triage) gets the site's
  support contact appended to "send us …" lines where the site has one.

## Delivery channels
(source: alerts.py)

- **none**: nothing leaves the server. Each composed alert is recorded as not
  delivered with detail "no sink configured".
- **webhook**: an HTTPS POST of JSON `{"subject": …, "text": …}` with
  User-Agent `ccsync-dashboard-alerts`, 20 s timeout. Redirects are never
  followed. Only the URL's origin is written to the ledger (the path is
  treated as a credential). Errors: "no webhook URL is set", "the webhook URL
  must be https", "the webhook answered HTTP N", "could not reach the webhook
  (…)".
- **smtp**: plain-text email, 20 s timeout, STARTTLS (verified by default) if
  enabled, login if a user is set. Optional Reply-To header (used only by the
  triage report). Errors: "no SMTP host is set", "SMTP needs a FROM address
  and at least one TO address", "the certificate <host> presented could not be
  verified (…). If this is your own mail server with its own certificate, turn
  off 'Verify the mail server's certificate' on this page.", "the mail server
  refused the sign-in" (never echoes the server's reply), "could not send
  through <host> (…)". No delivery failure ever stops the collector.

## The weekly fleet report
(source: alerts.py)

- Sent at Monday 08:00 in the site's time zone (computed from the local
  calendar, so it does not drift across daylight saving), if `alerts_weekly`
  is on.
- "Owed" is durable: compared against the most recent Monday-08:00 slot, so a
  container down all Monday sends it on Tuesday, and restarts do not send it
  twice. A failed send does not retire the slot; retries back off 10 min, then
  1 h, then 6 h after successive failures in the same slot.
- With sink `none` it is still composed and recorded as "generated, not sent
  (no sink configured)", which does not count as a failure.
- Subject: "CC Sync weekly: N computer(s), E problem(s), W thing(s) to look
  at".
- Body sections, in order:
  - "Fleet health for the week ending <now>." and "N computer(s) reporting."
  - "PROBLEMS (n)" and "THINGS TO LOOK AT (n)": every open finding with its
    diagnosis, fix and detail, or "none.".
  - "BUILDS": count of computers per companion version ("0.9.55: 6 of 8
    computers"), then each outdated or unknown-version computer: "<who> has
    been on <build> for <span>; current for <platform> is <version>".
  - "WHAT CHANGED THIS WEEK (n entries)": up to 40 audit-log lines, then "...
    and N more on the TIMELINE page." or "nothing.".
  - "ALERTS SENT THIS WEEK": up to 50 ledger rows, failures marked "(SEND
    FAILED: …)".
  - Bytes moved per transfer per computer: `DORMANT`, printed only if the lane
    table ever gains a byte column (it has none today).
  - "JOBS: q queued, r running, a abandoned this week" (printed every week when
    the jobs table exists).
  - The protection panel's standing block ("WHAT IS PROTECTED…"), or "WHAT IS
    PROTECTED: this section could not be read this week. Treat it as
    unchecked, not as fine."
  - "RECOVERABLE FILES IN .ccsync-trash": per computer that reported trash
    bytes and file count.
  - "CHECKED AND FOUND NOTHING WRONG (k of N)" with "ok - <what>" per clean
    kind; then "COULD NOT BE CHECKED (n)" listing failed checks.
  - "NOT SENT AS ALERTS (n, switched off on Settings, Alerts; still checked and
    listed above)" with "off - <what>" per muted kind.
  - Closing line: "This report is composed from what the dashboard already
    knows. Anything it could not read is named above rather than left out."
- A failed weekly send raises alert `weekly_send_failed` (below).

## The daily heartbeat ("still here")
(source: alerts.py)

- Off by default (`alerts_heartbeat`). Only when a sink is set.
- One per calendar day in the site's time zone; a failed send retries with the
  same 10 min / 1 h / 6 h backoff.
- Subject: "CC Sync: all quiet - N computer(s), E problem(s)" (no errors) or
  "CC Sync: still here - …".
- Body explains "IF THESE STOP ARRIVING, THE SERVER ITSELF IS DOWN", lists
  computers known, problems open, things to look at, and "Turn this off on the
  dashboard: SETTINGS, ALERTS, DAILY 'STILL HERE' MESSAGE."
- Never counted as a problem, never "recovered", never on CURRENTLY OPEN.

## The alert ledger page helpers
(source: alerts.py)

- "WHAT WAS SENT" groups ledger rows by the message they went out in (batch
  id); rows without a batch id are each their own message. Each group shows a
  count and whether every row in it was delivered.

## Alert kinds: editors' computers
(source: alerts.py)

Each bullet: kind name, severity, title, the condition, the wording, the fix.
"who" is `editor/machine`.

- `machine_silent` (error), "a computer has gone quiet".
  - Condition: the computer has never reported, or last reported 24 h or more
    ago.
  - "<who> has not been in touch since <age>. Everything this dashboard shows
    for that computer is frozen at that moment, so a green row there means
    nothing right now."
  - Fix: "Ask that editor to check the CC Sync tray icon is running and that
    the computer is on and online. If that computer is gone for good, open
    Sync status and press "Forget" on its row so this stops."
  - After 14 days of silence it is said once and not repeated daily (stays
    open; the home panel gets notice `machine_forgotten` instead).
- `red_unexplained` (error), "a computer is not syncing". Runs last.
  - Condition: the computer's status is red, no other kind named it this
    pass, and it has been in that state 1 h or more (oldest lane state age, or
    report age).
  - Text: the computer's own "why" sentence, or "<who> has been showing a
    problem for <duration> and this dashboard cannot say which. It is not
    syncing normally.", plus " Nothing more specific could be worked out from
    what that computer has reported."
  - Fix: "Open that computer's row on the Sync status page and press "Ask this
    computer why", then send us the diagnostics it returns."
- `breaker_tripped` (error), "proxy download stopped itself".
  - Condition: the computer reports its proxy-download brake (lane B circuit
    breaker) tripped.
  - "Proxy download has stopped itself on <who>, <age>. Until somebody clears
    it, that computer gets no new proxies, so the editor cannot see anyone
    else's footage. Uploads from it are still running and nothing has been
    deleted."
  - Fix: press "Resume" on the computer's row on Sync status, after checking
    the server looks right.
- `disk_park` (error), "a computer stopped its own downloads for space".
  - Condition: the computer reports it blocked itself for `disk_full`.
  - "<who> has stopped its own proxy download because the drive is nearly full
    (X free). …" Fix: clear space or untick a project.
- `disk_low` (error), "a computer is running out of space".
  - Condition: the disk colour computed against the computer's own reported
    floor is red, AND the computer is not a base (wired) machine AND (when
    known) holds at least one full tick.
  - "<who> has X free on its sync drive (P percent). Proxy download fills a
    drive file by file, and the recoverable-files bin cannot be cleared while
    the brake is on, so this ends with that editor unable to work."
- `engine_down` (error), "the sync engine is down on a computer".
  - Condition: the computer's Syncthing supervisor has reported "down since" for
    1 h or more; skipped for base (wired) machines.
  - "The sync engine on <who> has been down for <duration>. …" Fix: quit and
    restart CC Sync from the tray; send diagnostics if it repeats. Detail
    names failed restart attempts and last error.
- `lane_stalled` (error), "a sync transfer is stuck".
  - Condition: the computer reports a stalled lane (or its "why" reason is
    `lane_stalled`) and the stall is current (a stall record with no time
    still counts).
  - Text: the computer's why-sentence plus "A drive that has stopped answering
    reads exactly like this, and the other transfers on that computer wait
    behind it." Fix: restart CC Sync and check the drive opens.
- `lane_error` (error), "a sync transfer has been failing".
  - Condition: any lane in state `error` for 1 h or more. Subject is
    "<who> <lane label>".
  - "<label> on <who> has been failing for <duration>. …"
- `report_refused` (error), "a computer is being turned away".
  - Condition: the server has refused that computer's report.
  - "<who> IS running and IS trying to report, and this server is turning it
    away (<age>). …" Fix: "Ask that editor to click Sign in on the CC Sync tray
    on that computer."
- `clock_skew` (error), "a computer's clock is wrong".
  - Condition: reported clock skew 5 minutes or more either way.
  - "…Proxy download only takes files past a minimum age, so a clock this far
    out makes it transfer nothing at all while reporting no error…" Fix: turn
    on Set time automatically.
- `folders_unfiltered` (warn), "a shared folder has no filter".
  - Condition: the computer reports shared folders with no ignore filter,
    unless EVERY named folder was ticked for that computer within the last 30
    minutes (fresh ticks are unfiltered for one sync turn by design).
  - "N shared folder(s) on <who> has/have no ignore filter written yet.
    Without it, that computer will carry camera originals in both directions
    over the internet instead of proxies only."
- `thread_restarts` (warn), "CC Sync keeps restarting itself": 3 or more
  self-restarts of background work in 24 h. Fix: use the companion's
  diagnostics button and send it.
- `crashes` (warn), "background tasks have crashed": any crash reports on the
  computer.
- `file_move_expired` (warn), "a file move was never confirmed".
  - Condition: a file-move target whose request aged out unconfirmed (first 40).
    Subject "<machine> <old path>". Fix: re-run "Move on the server and on
    every computer" once online.
  - Targets whose computer is no longer registered are grouped into one
    finding, subject "computers this server no longer has".
- `loopback_down` (warn), "Send to Resolve cannot work on a computer".
  - Condition: the companion's loopback (port 8899) is enabled and reported
    not bound.
  - Fix: "Quit whatever holds port 8899 on that computer (an old BRoll
    Companion, a leftover process), then restart the CC Sync tray."
- `dashboard_reached_over_public_http` (error), "a computer reaches this
  dashboard unencrypted over the internet".
  - Condition: the computer's last report arrived over plain http from a
    public address. Plain http on a LAN or tailnet is never alerted.
  - Repeats daily only while the computer has reported in the last 24 h;
    otherwise said once. Fix: serve over https (Tailscale Serve), set the
    https address in the tray, update CC Sync, or Forget the computer.

## Alert kinds: sharing and fleet controls
(source: alerts.py)

- `fleet_halt` (warn), "syncing is stopped for the whole fleet": an admin's
  fleet-wide stop is active and not expired. Fix: Settings, Users, "Start
  syncing again" or "Keep it stopped".
- `fleet_halt_expired` (warn), "a fleet-wide stop expired by itself": the stop
  is past its expiry, and only for 24 h after the expiry time.
- `enforce_refusal` (error), "a sharing change was refused", subject "sharing
  brake": the collector refused a change that would unshare folders from too
  many computers at once.
- `deactivation_refusal` (error), "a mass project deactivation was refused",
  subject "project deactivation brake": too many projects disappeared from
  the tree at once.
- `enforce_plan` (warn), "a sharing change is held", subject "sharing plan
  held": a computed plan exists with at least one add or remove (an empty plan
  is not raised).
- `key_drain` (warn), "computers are still on the old sign-in key": computers
  still identifying with a rotated server key 7 days or more after rotation.

## Alert kinds: this server
(source: alerts.py)

- `nas_engine_down` (error), "the server's sync engine is unreachable": the
  collector cannot reach Syncthing. Silent on a deployment with no
  `syncthing_url`.
- `data_disk` (error), "the server is running out of space": the dashboard's
  data volume has under 10 percent free. If free space cannot be read, the
  check fails (becomes `check_failed`).
- `nas_tree` (error), "the project tree is missing": the configured projects
  directory does not exist or is empty ("is not there at all" / "is there but
  completely empty"). Silent when no projects directory is configured.
- `notice_error` (error), "the server found a problem": every open notice of
  severity error (most recent 200 read, capped at 40 shown). Subject
  "<notice kind>: <subject>"; text = the notice's body plus "(first seen
  <age>)"; fix = the notice's fix.
- `collector_stale` (error), "the server's collector has stopped": the
  collector has not started a cycle recently. On a site without Syncthing the
  threshold is two cadences of the quickest kind configured, never less than
  180 s.
- `watchdog_restart` (error), "the server restarted its collector": raised
  only when the alerts pass is told the watchdog restarted the collector N
  times; it is an event, not a state.
- `collector_kind_failed` (error), "a server background job is failing": a
  collector kind whose last run failed. Subject "poll <kind>".
- `collector_kind_overdue` (warn), "a server background job is late": a kind
  whose last run was OK and whose last finish is older than its own overdue
  bound plus one alerts interval. The retention job (`prune`) gets its own
  wording about deleting history on the privacy schedule. While the collector
  is stale or the kind's last run failed, an already-open overdue alert is
  held quiet.
- `code_not_applied` (error), "this server is not running the update that was
  applied to it": the container booted its built-in image code while the
  applied-update record names a newer version.
- `invariant_broken` (error), "something this system relies on is not true":
  one finding per broken invariant subject (see Invariants). Text = the
  invariant's consequence sentence plus "This server checks that <title>, and
  as of <age> it is not true."
- `protection_missing` (error), "a safety net is not there": protection panel
  lines in state broken. Silent until a protection pass has run at least once.
- `protection_unverifiable` (warn), "a safety net this server cannot check":
  protection lines that cannot be verified or whose check failed.
- `ignored_sections` (warn), "computers are reporting things nobody reads":
  computers send report sections this dashboard drops. Fix: "This dashboard
  needs updating. Send us this list."
- `weekly_send_failed` (error), "the weekly report could not be sent": the
  most recent weekly report row is a failure. Cleared early as soon as any
  later real delivery (a test, an alert, a recovery) succeeds through the
  channel.
- `sftp_transport_unsafe` (error), "the SFTP settings can cut big downloads
  short": the stored SFTP chunk size and concurrency are ones this NAS's sshd
  cannot serve. Fix: chunk 64Ki, concurrency 16 (or blank), then re-download
  proxies over 514 MiB.
- `tailnet_node_down` (error), "this server's tailnet connection is down": the
  bundled Tailscale node reports a state other than Running. Silent when no
  bundled node exists.
- `tailnet_key_expiring` (error), "this server's tailnet key is about to
  expire": key expires within 14 days, or already expired. If the node did not
  answer, the check fails rather than clearing.
- `tailnet_serve_missing` (error), "the dashboard is not published on the
  tailnet": node Running but nothing publishes the dashboard; includes the
  last automatic repair attempt's detail. Fix includes the terminal command
  `docker compose exec tailscale tailscale serve --bg http://dashboard:8480`.
- `fleet_silent_at_once` (error), "most computers went quiet at the same time".
  - Condition: of computers that reported within 24 h (at least 2), the largest
    group that went silent within a 10-minute window, each silent between 30
    minutes and 24 h, is at least half of them (minimum 2); AND either the
    server's own tailnet node is unhealthy, or at least 2 and at least half of
    that group were mid-transfer at their last report.
  - Two wordings depending on which corroboration applied; fix is to check the
    NAS and its Tailscale app, not the editors one by one.

## Alert kinds: updates
(source: alerts.py)

- `upgrade_failed` (error), "an update will not install": 8 or more failed
  attempts at the same update. If the last error shows a crash loop and
  roll-back, different wording: do not install that version by hand, send
  diagnostics, publish a newer build.
- `upgrade_refused` (error), "a computer is refusing every update": the
  computer refused an offered version (bad signature, below its downgrade
  floor, plain http to a public host) within the last 24 h. Older refusal
  records are ignored. Fix: publish a build it will accept or install by hand.
- `upgrade_reverted` (warn), "a computer rolled an update back".
- `retracted_running` (error), "a recalled build is still running".
- `rollout_stalled` (warn), "a new build is not being taken": a platform's
  current build was made current 48 h or more ago and at least one computer
  that reported within that window is still on an older build. Silent when the
  "made current" time is unknown.
- `versions_behind` (warn), "a computer is several releases behind": 3 or more
  non-recalled builds (published here or offered by the vendor feed) are newer
  than the computer's.
  - Computers already on (or ahead of) this dashboard's current build, or on a
    platform with no current build, are grouped per platform under subject
    "the <platform> computers" with wording explaining "Update now" cannot help.
- `soak_failed` (warn), "a trial build is failing": a staged (trial) build,
  not older than the current one, has crashed on or been rolled back by at
  least one computer since it started running there.
- `feed_stale` (warn), "this dashboard cannot check for updates": the vendor
  feed was last checked 7 days or more ago, never, or the last check errored.
- `feed_runtime_mismatch` (warn), "updates cannot install on this NAS": every
  offered build needs a newer container.
- `platform_channel_stale` (warn), "one platform's build is behind": with two
  or more platforms having a current build, a lagging platform is behind the
  leader by 7 days or more of "made current" time, or (if either time is
  unknown) by more than 2 published builds. Three fix wordings: make an
  already-published newer build current; ask the vendor (dashboard fed from
  the vendor feed); build on a Mac with the two macOS release commands.

## Alert kinds: projects and footage
(source: alerts.py)

- `out_of_tree` (warn), "footage is outside the tree".
  - Condition: the computer's last Resolve scan found clips referenced from
    outside the sync tree. Raised only if the open project can be tied to a
    tree project (by a manual mapping, a ticked or known project's name, or a
    confident label match), or if the computer has not said which project is
    open. A personal project is silent (and an already-open alert is held
    quiet).
  - Title becomes "footage is outside the tree in '<project>'" when the
    project is known.
- `unopened_out_of_tree` (warn), "footage on one computer only": the
  companion's sweep of projects NOT open lists projects whose clips exist only
  on that computer. Title "footage on one computer only in '<first>' and N
  other projects"; lists up to 5. Fix: open each project and press FIX ALL.
- `stray_projects` (warn), "project folders outside the tree".
- `moved_project_dir` (warn), "a project folder has moved".
- `ingest_staging` (warn), "footage is waiting in a drop folder".
- For `unopened_out_of_tree` (category `resolve_project`) and
  `stray_projects` / `moved_project_dir` (category `local_manifest`): if the
  computer withholds that reporting category, nothing is raised, and an open
  alert is closed without a message.

## Alert kinds: fleet jobs
(source: alerts.py)

- `jobs_starved` (warn), "work is queued and nobody is taking it": the oldest
  queued job is 6 h or more old AND the scheduler's reason for it is one of: no
  capable computer, every capable computer has that kind switched off, syncing
  is halted, or every capable computer has stopped reporting. Transient
  reasons (all busy, idle wait, fleet cap, cooling down) never raise it.
- `jobs_abandoned` (warn), "the fleet gave up on some work": any job abandoned
  in the last 24 h; one finding for all of them.
- `jobs_pinned_no_executor` (error), "a job is pinned here and nothing here can
  run it": pinned jobs exist and Timeline Cards is not mounted; or it is
  mounted but the old page was retired (fix: cancel and requeue); or the
  drain worker is not running; or a pinned job claimed by this server has had
  no heartbeat for over 1 h ("a stranded pinned job").

## Alert kinds: YouTube downloads and media tools
(source: alerts.py)

- `ytdlp_stale` (warn), "a computer's YouTube downloader is old": the
  computer marks its yt-dlp stale, unless it is in fact the newest release
  (the companion says so, or for older companions: its version is the newest
  any computer or this server knows AND its message says "already the newest
  release").
- `ytdlp_failed` (error), "a computer has no working YouTube downloader".
- `media_sidecar_failed` (warn), "a computer could not install its media
  tools": ffmpeg/ffprobe/deno install failed 2 or more checks in a row; quotes
  the cause.
- The next five read this server's own /ytdl stack and are silent when it is
  not mounted:
  - `ytdl_worker_dead` (error), "the YouTube downloader is not running".
  - `ytdl_downloads_failing` (warn), "YouTube downloads are failing": the last
    real download failed AND the server's own test-clip (canary) also failed.
  - `ytdl_pot_provider_unreachable` (warn): the configured PO-token helper is
    unreachable (not raised for "unconfigured" or "unknown").
  - `ytdl_plugin_install_failed` (warn): the anti-bot plugin install at boot
    failed.
  - `ytdl_stale` (warn), "this server's YouTube downloader is old".

## Alert kinds: b-roll
(source: alerts.py)

- `broll_archive_unreadable` (error), "the b-roll archive cannot be read":
  re-lists the archive itself each pass (same probe as the notice). "…every
  clip an editor sends to Resolve is the small preview instead of the editing
  proxy…"
- `broll_batch_stuck` (warn), "a b-roll indexing job has stopped": an ingest
  batch queued, claimed or running with no heartbeat for 24 h. Read through a
  read-only connection; silent when b-roll is not mounted.
- `broll_share_expiring` (warn), "a client link is about to expire": a
  non-revoked client folder link expiring within 7 days (already-expired links
  are not raised).

## Notices: the "PROBLEMS THE SERVER FOUND" pass
(source: notices.py)

- A read-only self-diagnosis pass, run once per collector "notices" cycle.
  Each check is isolated; findings are committed after each check.
- A notice is upserted on (kind, subject); "cleared" closes it. State-shaped
  kinds are re-asserted every pass while true and cleared the first pass they
  are not. Event-shaped kinds close by the rules in "Notices that close
  themselves" below. A kind with no closing rule stays until an admin presses
  dismiss (the dismiss control itself is not in these files).
- A check that cannot reach its input (Syncthing not asked, mount status not
  recorded) writes nothing and clears nothing.
- **A check that raises**: notice `notice_check_failed` (error), subject = the
  check's name: "The server's own check `<name>` stopped with an error (…), so
  whatever it watches is not being watched right now. Its last findings are
  left as they were." Fix: look for "notice check <name> failed" in the
  container log; roll back from Settings, Packages if it follows an update.
  Cleared automatically the next time that check runs cleanly.
- Severity `error` notices are also mailed through alert kind `notice_error`.

## Notice kinds written by the per-cycle pass
(source: notices.py)

- `collector_cycle_failed` (error), subject = the collector job name. When a
  job's last run failed: "The '<job>' job has been failing <for about N
  hour(s)>: <meaning>. The server reported: <error, 200 chars>". Meanings and
  fixes per job:
  - `provision`: "new and moved project folders are not being set up for
    syncing"; fix: look at other problems (a stray project marker is the usual
    cause), else restart.
  - `config`: "this server cannot read its own sync engine…"; check Syncthing,
    see the Collector panel.
  - `enforce`: "projects ticked or unticked on this dashboard are not reaching
    the editors' computers"; check Syncthing, untick and re-tick one project.
  - `inventory`: "the server's own file list is not being refreshed…"; check
    the projects folder is mounted.
  - `connections`, `completion`, `remoteneed`: Syncthing-dependent meanings;
    check Syncthing.
  - `prune`: "old rows are not being cleared out of the database"; check free
    space.
  - `invariants`: "the checks that re-verify the facts this system relies on
    are not running"; open Settings, Invariants, restart.
  - Any other job: generic meaning, "Restart the dashboard, then read the
    Collector panel".
  - Cleared when the job's last run is OK.
- `collector_db_write_failed` (error), subject = job: raised alongside the
  above when the error text contains a disk/database fault marker ("disk i/o
  error", "database or disk is full", "readonly database", "database is
  locked", "unable to open database", "database disk image is malformed").
  "…Nothing this server records is safe while that is true."
- `syncthing_unreachable` (error), subject "server": the sync engine is not
  answering. Cleared when it answers; left alone when unknown.
- `enforce_refusal` (error), subject "share removals": the sharing brake held
  back N share removals over the limit; lists the folders (200 chars). Fix:
  check no computer was renamed or removed; press "Apply these removals" on
  the fleet page or raise the per-computer allowance under Settings, Sharing
  safety; mentions `DASH_ENFORCE_MAX_REMOVALS` as the flat floor.
- `share_without_plan` (warn), subject "<folder> -> <device>": up to 20, one
  per pair the brake held, "This computer is still being sent a project that
  nobody has ticked for it…". All cleared when the brake clears.
- `deactivation_refusal` (error), subject "projects": N projects looked
  deleted in one pass, over the limit, so none were marked gone.
- `ignored_report_sections` (warn), subject "report fields": companions send
  fields this dashboard is too old to store; lists them. Fix: Settings,
  Packages, "Update now" in the This dashboard panel, or a newer container
  image.
- `projects_dir_missing` (error), subject = the projects path: the folder
  cannot be read (names the OS error), is not there, or is EMPTY ("which
  normally means the storage is not mounted… Nothing has been marked as
  deleted."). When healthy, every open notice of this kind (any path) is
  cleared.
- `inventory_refused` (error), subject = project slug: a project's file walk
  was refused; "The figures on that project's page are the last good ones".
  Fix mentions "Move on the server and on every computer" if renamed. Only
  checked when the projects folder is healthy.
- `duplicate_machine_id` (error), subject = the machine id: two or more
  registered computers report the same identity (a cloned disk). Fix: on the
  newer computer quit CCSync, delete `.ccsync/machine.json` in the user's
  home folder, start again.
- `duplicate_device_id` (error), subject = Syncthing device id: two computers
  claim the same device id. Fix: reinstall or reset its Syncthing identity.
- `pending_device_approval` (warn), subject = device id: a device has waited
  24 h or more (or no time is known) to be approved on the server's sync
  engine; names the computer if known. Fix: approve it on Settings, Users,
  pending devices.
- `plan_without_share` (error), subject "<editor>/<machine> -> <slug>": a
  computer's full tick for a project is not matched by an actual share to its
  device id (wired machines' rows and unassigned ticks excluded). Skipped
  until this process has a cached folder/device snapshot. Fix: untick and
  re-tick; check the row has a Syncthing device id.
- `machine_disk_low` (warn), subject = computer: free space under 50 GB on
  the computer's drive, from a reading no older than 48 h (an unstamped or
  older reading is skipped, which clears it). Two wordings: computers that
  download proxies ("Proxy downloads for one project are typically 50 to 300
  GB…", fix: untick a project or clear space) and wired or nothing-ticked
  computers ("No project footage comes down to this computer… anything else it
  syncs, such as the shared LUT library, stops when it runs out", fix: clear
  space).
- `machine_trash_oversize` (warn): over 200 GB of deleted-file safety copies
  on a computer. Fix text says the computer clears these every 6 hours unless
  proxy download has stopped itself, and points at "Resume".
- `machine_forgotten` (warn), up to 20 computers: last report over 14 days
  ago. "…so this server has stopped asking about it. Nothing is syncing to or
  from that computer, and anything ticked for it is sitting unapplied." Fix:
  press "Forget" on Sync status, or nothing if it is coming back. Clears when
  the computer reports again or is forgotten.
- `feature_not_mounted` (warn), subject = mount name: one of the optional
  pages (B-ROLL, MUSIC, YOUTUBE, TIMELINE CARDS, FOOTAGE SORTER) did not start
  at boot. "The <label> page is not available on this server: <reason>.
  Editors will not see the link in the menu." Status `mounted` or `disabled`
  (the deployment did not ask for it) raises nothing. A mount with no recorded
  verdict keeps any open notice.
- `alerts_sink_none` (warn), subject "alerts": no alert channel set. "Nobody
  is being told when this server finds a problem…" Fix: set an address or
  webhook on Settings, Alerts, then "Send a test".
- `server_crash_report` (error), subject "this server": the dashboard's own
  crash files written since this process started. "This server's own
  background tasks have crashed N time(s) since it started…" Fix: press
  "Download crash reports" on the notice and attach the zip. Closes itself
  (recorded with the reason) once the newest crash is 24 h old; a new crash
  reopens it.
- `dashboard_disk_low` (error), subject = data directory: under 2 GB free on
  the dashboard's own data volume, or free space unmeasurable ("That is not
  the same as knowing it is fine."). Fix: delete old builds on Settings,
  Packages or enlarge the volume.
- `feed_unreachable` (warn), subject "vendor feed": a release feed URL is
  configured and its last read errored, is older than 48 h, or never
  happened. Fix: "Check now" on Settings, Packages. With no feed URL
  configured, both feed kinds are cleared.
- `feed_runtime_mismatch` (warn), subject "dashboard image": every offered
  dashboard build was made for a different container image.
- `ai_cli_update_failed` (warn), subject "Claude Code": the unattended Claude
  Code updater's last recorded result is "failed" (only when the auto-update
  feature and CLI providers are on). Names installed and latest versions and
  the reason; "Timeline Cards keeps working on the version it has, but a new
  Claude model may be refused until it is updated." Fix: Settings, AI
  providers, UPDATE.
- `cli_lock_stranded` (error), subject "Claude Code / Codex": the site has CLI
  AI providers switched on but this build does not include them. Three
  wordings: a Claude API key is set but a non-Claude provider is pinned; only
  a non-Claude key exists; no key at all. Clears when no stranded setting
  remains or a Claude provider resolves.
- `editor_without_machine` (info), subject = account name: an editor account
  at least 30 days old (or of unknown age) for which no computer has ever
  reported. Fix: send the installer, or delete the account on Settings, Users.
- `broll_archive_unreadable` (error), subject = archive root: the archive's
  witness path (its proxies folder) is missing ("the archive folder is there
  but its contents are not"), the root cannot be listed, or it lists empty
  ("the folder is there but completely empty"). Silent when no b-roll mount
  recorded a root.
- Contention kinds (`db_busy`, `slow_write`, `slow_poll`): each pass only
  stamps them as "checked" so the checks panel does not show NOT CHECKED.

## Notices written at boot
(source: notices.py)

- `insecure_secret` (error), subject = the setting names (never values):
  `report_token`, `session_secret` or `syncthing_api_key` has leading or
  trailing spaces or is wrapped in matching quotes. "Everything that uses it
  will be refused, on every computer at once."
- `dev_insecure` (error), subject "DASH_DEV_INSECURE": the server runs with
  the dev/test security bypass on. "…weak passwords are accepted, sessions are
  not checked against the server, and the anti-forgery token is not
  enforced…" Fix: remove the variable and restart.

## Notices written by events elsewhere (writers in this file)
(source: notices.py)

- `file_moves_dropped` (error), subject "the last inventory pass": one pass
  found more hand moves of files on the server than it may record; the excess
  is lost. Stays until dismissed.
- `server_error` (error), subject "<route or redacted path> (<exception
  class>)": an unhandled server error on a request. Counted: "N time(s) a
  request to <path> failed with an error (<class>). Whoever was using that
  page saw a failure. What went wrong: <class>: <message, redacted, 700
  chars> Where: <three innermost frames, repo-relative>". Whole detail capped
  at 1,500 characters. Fix: copy the notice text to support.
  - Paths: the matched route template when known (120 chars); otherwise only
    the first two path segments plus "/…" (so a client-share token in the
    third segment is never stored).
- `db_busy` (warn), subject "<path> (database busy)": a request waited the
  database busy timeout out and got a 503. Counted.
- `slow_write` (warn), subject = the writer: a write held the lock longer than
  a request waits; carries the last duration. Fix: "Nothing on the reporting
  computer causes this and nothing needs unticking…".
- `slow_poll` (warn), subject "collector poll <kind>": a background pass took
  over 60 s. Closed by the next pass of that kind that finishes inside a
  cycle.
- `alerts_delivery_slow` (warn) is written by the alerts pass (see above).

## Notices that close themselves
(source: notices.py)

- Runs last in each pass. Each event-shaped kind closes when its rule says it
  is over, with the reason recorded:
  - `server_error`, `db_busy`, `slow_write`, `collector_watchdog_restart`: not
    seen again for 24 h.
  - `triage_reply_refused`: a later reply from the same refused sender was
    accepted and acted on; otherwise not seen again for 7 days.
  - `file_move_detected`: once the card is at least 24 h old, every computer
    the move was sent to moved its copy (or no computer held one); otherwise 7
    days with no recurrence.
- Evidence that cannot be read is never treated as resolved.

## Server crash reports download
(source: notices.py)

- The newest 20 crash report files from the dashboard's crash directory can be
  downloaded as a zip built in memory (nothing is written to the data volume).
  The files are already redacted when written. An unreadable directory yields
  an empty list. (The route that serves it is not in these files.)

## Invariants: facts re-verified on a schedule
(source: invariants.py)

- Runs once per collector "invariants" cycle (the code's comments name a
  15-minute cadence and `DASH_INTERVAL_INVARIANTS` as the setting; the
  interval itself is set outside these files). It names problems and repairs
  nothing.
- Each invariant ends a pass in one of four states: `ok` (with evidence text,
  for example "34 full tick(s), all shared"), `broken` (with up to 20 named
  subjects, each with a detail), `not_checked` (with the reason the check
  could not run) or `check_failed` (the check raised; type and message, 200
  characters).
- For each broken subject a notice `invariant_broken` is filed with the
  invariant's severity, subject "<key>: <subject>", body "<consequence> This
  server checks that <title>, and right now it is not true: <detail>.", fix =
  the invariant's fix. Subjects no longer broken are cleared.
  - Subjects beyond the 20-subject cap stay open (not cleared by the cap).
    When the check can name its whole broken set (up to 2,000), exactly that
    set is kept open; otherwise up to 200 previously known subjects are
    carried in memory (lost on container restart).
  - A pass that reaches no verdict (not checked or failed) keeps the
    invariant's previously open subjects open.
- An invariant whose check raises also files notice `invariant_check_failed`
  (error), subject = key: "The check for '<title>' could not run, so this
  server does not know whether that is all right. Treat it as unchecked, not
  as fine." Fix: "Send us the container log from the NAS." Cleared when it
  runs again.
- Every broken invariant is also mailed through alert kind `invariant_broken`.
- Collector panel note: "N invariant(s) broken; M check(s) could not run; K
  not checked here", counting only invariants this build can check at all
  (the two permanently skipped ones are left out of the note); no note on a
  clean pass.
- Admin page view: every registered invariant with its last state, detail,
  checked time and subjects. An invariant with no stored result shows NOT
  CHECKED (with its skip reason if it has one).

### The fifteen invariants
(source: invariants.py)

1. `plan_has_share` (error): "every project ticked to sync is actually shared
   with that computer".
   - Not checked until this process has read the sync engine's folder list.
     Full ticks only; wired machines and unassigned ticks excluded; ticks on
     computers with no device id are counted as unknown.
   - Broken subject "<editor>/<machine> -> <slug>": "ticked to sync, not shared
     with that computer". Not checked if no full tick has a known computer.
2. `machine_has_plan` (warn): "what each computer that reports is set to
   sync". NEVER broken: reports ok and lists computers (other than wired ones)
   with nothing ticked, informationally. Not checked with no computers.
3. `one_identity_per_computer` (error): two or more computer rows with the same
   machine id ("two computers on one identity", or, if both reported within
   15 minutes, "both reported within 15 minutes, so a copied disk is in use on
   two computers at once"), or the same Syncthing device id ("one place on the
   sync network claimed twice"). Fix: delete `.ccsync/machine.json` on the
   newer computer and restart CC Sync.
4. `project_markers` (error): every active project folder visible to this
   container has its `.ccsync-project` marker and the marker names the same
   project id. Folders missing entirely are skipped. Not checked when no
   project tree is mounted (`DASH_PROJECTS_DIR`) or no folder can be located.
5. `tree_markers` (error): the project tree root is readable and not empty
   (empty = broken: "normally means the storage is not mounted"). Not checked
   when unreadable or not mounted. Ok text counts top-level entries and how
   many are projects.
6. `package_floor` (error): no current published build has a minimum version
   above its own version ("a computer that accepts it can never install
   anything again"), or below the highest minimum already published on its
   channel.
7. `companion_floor` (error): every computer that reported a version runs at
   least 0.9.43 (needed for "Resume" and "Update now"), or 0.9.54 if it holds
   an upload-only tick. Fix notes a computer below 0.9.3 cannot be reached by
   "Update now".
8. `versioning_agrees` (warn): "deleted-file retention agrees between the
   server and the editors". `UNREACHABLE`: permanently not checked; the
   companion does not report its retention number.
9. `snapshot_schedule` (error): the NAS has at least one enabled periodic
   snapshot task, and each dataset the deployment names (the tree dataset and
   the dashboard data dataset, from environment variables) is covered by an
   enabled task (a recursive parent counts). Only on TrueNAS with a configured
   NAS API; otherwise not checked. A dataset not named is reported as "not
   checked here" in the ok text. Fix: add a task in the NAS's Data Protection,
   Periodic Snapshot Tasks.
10. `proxy_pairs` (warn): every proxy file in a `Proxy/` folder on the server
    has an original with the same name stem in the folder above it. Camera
    proxies ending in `S03` (Sony) are also matched with that suffix removed
    (case-insensitive). Files starting with "." (macOS `._` files,
    `.DS_Store`) are ignored. One subject per Proxy folder, naming up to 5
    clips and counting the rest. Originals without proxies are never flagged.
11. `fleet_current_with_vendor` (error): for each platform, the newest
    companion build the vendor feed offers is this dashboard's current build.
    Broken wordings: not published here; published but not current; current
    is older. Not checked with no feed configured (`DASH_RELEASE_FEED_URL`)
    or before any feed check has recorded offers.
12. `dashboard_meets_requirements` (error): no non-recalled build on the shelf
    requires a newer dashboard than this one ("it needs dashboard X and this
    dashboard is Y, so it can never be handed to the fleet from here").
13. `mount_assets_open` (error): the installable-app files are open without
    sign-in: `/manifest.webmanifest`, `/sw.js`, `/cards/manifest.webmanifest`,
    `/cards/icon.svg`, `/cards/sw.js`. Checked against the sign-in gate's own
    open list, not by fetching. Fix says it is a code change.
14. `cards_tree_matches_source` (warn): `UNREACHABLE`: permanently not
    checked; nothing records which checkout the Timeline Cards page was
    shipped from.
15. `alerts_deliverable` (warn): the alert channel check described under
    alert settings; broken subject "the alerts destination". Not checked if
    the alert ledger cannot be read.

## Health colours: computer, project and fleet dots
(source: health.py)

- Three colours, worst wins everywhere: red over amber over green.
- **Report freshness** of one computer (time since its companion last
  reported; companions report about every 30 s):
  - under 15 min: green; 15 min to under 6 h: amber ("no report since
    <time>"); 6 h or more: red ("no report since <time>").
  - An unreadable last-report time is amber ("the last report time on record
    cannot be read"). A device with no companion row at all is green here (the
    grid marks it "unmapped" separately).
- **One computer within one project** (editor status), first match wins:
  - any lane in `error`: red;
  - report freshness red: red;
  - behind (files still needed, or completion under 100 percent) and not
    connected, and last connected 15 min or more ago (or never): red;
  - Syncthing reachable and the completion figure is 5 min or more old: red;
  - behind, or any lane `syncing`, or freshness amber: amber;
  - otherwise green.
- **Project** status = worst of its computers; **fleet** status = worst of its
  projects.
- **Media presence per computer per project** (role-aware):
  - wired base machine: red if the server has originals and the machine holds
    fewer; otherwise green.
  - editor machine: green if the server has no proxies or the machine has all
    of them; amber if it has none or only some. Proxy-only (no originals,
    some proxies) is normal.

## Lane chips and the stall rule
(source: health.py)

- Each lane (upload, proxy download, folder sync) gets a chip colour and an
  optional reason:
  - state `error`: red, reason = the lane's last error.
  - the lane's report 6 h or more old: red, "this companion has been silent
    for 6 hours or more"; 15 min or more: amber, "this companion has been
    silent for 15 minutes or more".
  - **stall**: a lane not in `idle`, `error` or `paused` whose progress token
    (changes whenever real bytes move) has not changed for more than 30 min,
    or more than 3 of its rotation periods if that is longer: red, "syncing,
    no progress for N min". The time is the server's own clock (when the first
    report carrying the current token arrived). No token (older companion) or
    an unreadable time gives no verdict.
  - `syncing`: amber; otherwise green.
- **Lane strip**: every row always shows three chips in a fixed order, labelled
  "upload", "proxy download", "folder sync". A lane the computer did not
  report shows as "not reported" (green, muted). Green is drawn muted.
- **Is a companion's reported stall still current**: only if it has a stall
  record; with no stall time it counts as current; it stops being current
  when the record is over 24 h old or that same lane has completed a sync
  after the stall time (lanes matched by letter A/B/C).

## Disk colour and tick-size warning
(source: health.py)

- Disk chip for one computer's sync drive:
  - red if under 5 percent free or under the absolute floor (20 GB, or the
    computer's own reported proxy-download floor when the caller passes it);
  - amber if under 10 percent or under 50 GB free;
  - otherwise green. No reported disk section: no chip at all (never a green
    reassurance).
- "Has the computer hit its proxy-download floor": free space under the
  computer's reported floor, or 20 GB if it has not reported one. No free-space
  figure is never a stop.
- **Capacity warning when ticking a project for a computer**: when both the
  project's proxy size and the computer's free space are known, warn unless
  the proxies plus 20 GB fit AND the proxies are under half the free space.
  Text: "<project> is <size> of proxies. <machine> has <free> free." plus "That
  is more than will fit." when larger than free space. It never refuses the
  tick.

## "Why is this computer not syncing" sentence
(source: health.py)

- One plain sentence (and a reason code) per computer, used on the fleet grid,
  the editor's home view and diagnostics. No reason found is NOT shown as "all
  good"; it is simply no sentence.
- The companion's own reported block reason wins, except a reported
  `lane_stalled` that the server can show has healed (see the stall rule).
  Then the dashboard derives a reason itself, in this order: not signed in
  (unverified), clock skew of 60 s or more, disk floor hit, fleet halt, local
  halt, proxy-download brake, nothing ticked (not for wired machines),
  unfiltered shared folders, upload-only plan, current stall (companion record
  or server-side token watch), sync engine down (not for wired machines).
- Reason codes in rank order and their sentences:
  - `not_signed_in`: "Not syncing: this computer is not signed in"
  - `licence_pending`: "Not syncing: the licence agreement has not been
    accepted on this computer yet" (only from the companion's report)
  - `clock_skew`: "Not syncing: this computer's clock is <duration> out from
    the server, so proxy download transfers nothing"
  - `root_absent`: "Not syncing: the sync drive is not there on this computer"
  - `root_not_answering`: "Not syncing: the sync drive is mapped but not
    answering, so nothing can be read or written"
  - `root_misplaced`: "Not syncing: the sync drive is pointing at the wrong
    place"
  - `disk_full`: when the computer said so (reported the park, or reported
    its floor): "Not downloading proxies: proxy download stopped itself, the
    drive has <free> free"; when the server is guessing with its 20 GB
    default: "Proxy download has probably stopped itself: the drive has <free>
    free, under the 20 GB this computer's build stops at unless it was set
    otherwise on that computer".
  - `fleet_halt`: "Not syncing: syncing is stopped by your admin for the whole
    fleet"
  - `local_halt`: "Not syncing: syncing is stopped on this computer"
  - `paused`: "Not syncing: syncing is paused on this computer" (only from the
    companion's report)
  - `breaker_tripped`: "Not downloading proxies: proxy download stopped itself
    and needs a person to check the server"
  - `no_selection` (informational, not a fault): "Nothing ticked for this
    computer"
  - `folders_unfiltered`: "Not syncing safely: N shared folder(s) on this
    computer has/have no ignore filter yet"
  - `upload_only` (informational): "Nothing to download: this project is
    upload-only on this computer"
  - `lane_stalled`: "Not syncing: <upload / proxy download / folder sync /
    express upload> has been busy for <duration> with nothing moving"
  - `syncthing_down`: "Not syncing: the sync engine on this computer is down"
  - `transport_offline`: "Not syncing: this computer cannot reach the server"
    (only from the companion's report)
  - an unknown reason from a newer companion: "Not syncing: this computer
    reported a reason this dashboard is too old to explain"
- The companion's detail text is appended in brackets unless it only
  restates the sentence (a word-set comparison), is over 120 characters, or
  the reason is `no_selection`.
- **Second cause**: if another independently fixable cause is also true
  (fleet halt, local halt, paused, brake, disk floor), it is appended as ".
  Also: <sentence without its lead-in>". At most two causes.
- **Queue holds on the transfers page**: a queued file in lane A, B or C is
  labelled on hold, with the reason sentence and since-time, only when the
  companion itself reported a block reason that holds that lane: not signed
  in, licence pending, drive absent / not answering / misplaced, fleet halt,
  local halt, paused, offline hold all three lanes; clock skew, disk full,
  brake hold proxy download only; sync engine down holds folder sync only. A
  stall never marks a hold.
- The companion diagnostics route named in every "send us diagnostics" line:
  "Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN".

## Fleet grid row headline
(source: health.py)

- Each computer's row leads with one line and a level (red, amber or muted),
  first match wins:
  - a fault "why" sentence: red;
  - the row's report is stale: if nothing is ticked, muted "Nothing ticked for
    this computer. Last report <YYYY-MM-DD HH:MM> UTC"; otherwise "Not heard
    from since <YYYY-MM-DD HH:MM> UTC" (or "Not heard from this computer for 15
    minutes or more"), amber until 6 h, then red;
  - companion out of date: amber, "Out of date: running X, current is Y";
  - a lane chip red: red, "<Lane> has stopped: <reason>";
  - an informational sentence: muted;
  - any lane syncing: muted "Syncing";
  - otherwise muted "Idle between passes, N file(s) still to move", "Idle,
    nothing owed" (only when a file backlog count is known) or "Idle".
- **Details count**: the number shown beside the collapsed DETAILS expander
  counts these notes: N crashes; "the drive is filling up" (disk not green);
  N clips outside the tree; N projects not open with clips only on this
  computer; N stray project folders; "a project folder has moved"; N sync
  conflicts; "a shared folder has no filter yet"; "an update keeps failing";
  "this computer is being refused"; N files it will not upload; "a lot of
  footage in the local trash" (over 5 GB); "footage waiting in the drop
  folder"; "the express upload is failing" / "the express upload dropped
  files"; N clips need proxies; "the cards role is not running" (state
  refused, stopped, credential_refused or unreachable); N YouTube clips
  waiting for Resolve / "the YouTube import gave up"; N clips <missing-clips
  label>; "Resolve is wedged on a call".
- **Missing-clips wording** depends on the companion version: 0.9.76 or later
  "with neither the original nor a proxy on this computer"; older or
  unparseable "whose original is not on this computer", each with its own
  hover text.

## Privacy and licence facts on the fleet grid
(source: health.py)

- **Withheld reporting chip**: for each category a computer does not send, a
  grey chip "NOT REPORTED BY THIS COMPUTER" with the category label: "OPEN
  RESOLVE PROJECT", "FILE LIST", "RESOLVE BINS", "IDLE TIME". Hover text: the
  computer's own privacy switch (tray, Settings, THIS COMPUTER, PRIVACY) or the
  site's (Settings, Site, TELEMETRY) is off; "Sync is not affected, and
  nothing here is a fault." Never changes any colour, headline, note or alert.
- **Licence line**: compares only the licence version the computer reports
  with the version this dashboard serves to /setup: equal = green "Licence X
  accepted"; different = amber "Older licence accepted"; nothing reported =
  grey "Not reported"; no bundled licence = shown uncoloured. Shown on the
  fleet grid and on /account.

## Optional page mount status and live re-check
(source: mount_status.py)

- The dashboard records, at boot, a verdict for each optional page: `broll`,
  `music`, `ytdl`, `cards`, `sorter`. Verdicts are `mounted`, `absent`,
  `degraded` or `disabled`, each with a reason sentence. This is what the
  `feature_not_mounted` notice, several alert kinds and the health route read.
- Each mount may also record the data folder it serves and a "witness" path
  (a folder or file whose absence proves the data is gone; b-roll uses its
  proxies folder, music uses its database file).
- **Live re-check every collector cycle**: the witness (or root) is checked
  for existence. If it has gone and the page was `mounted`, the page becomes
  `degraded`: "the folder it serves is not there any more (<root>). Every
  request to that page will fail until the server's bind mount is back." If
  it comes back, the boot verdict is restored, but only for a page this
  re-check itself downgraded (a page that failed at boot still needs a
  restart). A check that errors changes nothing. A verdict rewritten by
  something else during the check (the YouTube feature switch) wins.

## The dashboard's own crash reports and log files
(source: crash_report.py)

- Any unhandled exception in the main thread or any background thread (except
  Ctrl-C / exit) writes a crash report file. It runs at boot of the web app.
  It never stops the dashboard.
- Location: `DASH_CRASH_DIR` if set, else a `crashes` folder beside the
  database (`DASH_DB_PATH`, default `/data/dashboard.db`). File name
  `<UTC timestamp>-<thread name>.json`, then `~01`, `~02` … for more in the
  same second (up to 99). Owner-only permissions (0600). At most 20 files are
  kept; the oldest are deleted.
- Contents: component "ccsync-dashboard", time, dashboard version, thread,
  operating system and Python version, exception type, message and full
  traceback. Message and traceback are redacted first:
  - `token`, `password`, `passwd`, `secret`, `api_key`/`api-key`, `dsn`, `pw`
    (and names with `_SUFFIX` parts) followed by `=` or `:`: value replaced
    with `<redacted>` (quoted values taken whole);
  - user:password in URLs; `Bearer <token>`; bare `sk-…` keys; `cce1.…` fleet
    tokens; GitHub `gh?_…` tokens.
  - The same redaction is applied to server-error notices and the JSON log
    file.
- A log line names the file written. Nothing is sent anywhere by default.
- **Opt-in remote reporting** (`DORMANT` by default): `DASH_SENTRY_DSN` set
  AND the `sentry_sdk` package installed (it is not in the shipped
  requirements) sends each crash to Sentry (no personal data, no tracing). If
  the DSN is set but the package is missing, a log line says crash files
  only.
- **Opt-in log file** (`DORMANT` by default): `DASH_LOG_DIR` set adds
  `dashboard.jsonl` there, one JSON object per log line (time, level, logger,
  redacted message, redacted exception), rotating at 5 MB with 3 backups.
  Stdout logging is unchanged.
- The notices pass counts crash files written since this process started (see
  `server_crash_report`) and offers the newest 20 as a zip download.

## The daily server check (triage agent): schedule and switch
(source: triage.py, alerts.py)

- `DORMANT` by default (`alerts_triage = 0`). Turned on in Settings, Alerts.
- A read-only review by Claude Code of everything the dashboard knows is
  open, stuck or failing, mailed to the owner with numbered suggested actions
  that a reply can carry out.
- **Schedule**: at each hour in `alerts_triage_hours` (default 06:00 and
  18:00) in the site's time zone. Decided after every alerts pass. Durable:
  owed when no report has been successfully sent since the most recent slot,
  so a container down at the slot runs it late and restarts do not repeat it.
  Failed sends retry with the 10 min / 1 h / 6 h backoff.
- Never due when switched off or when the alert sink is `none`.
- **One at a time**: a second run is refused ("a server check is already
  running", or "a server check has been running since <time>"); a run marker
  older than 90 minutes counts as dead and does not block.
- The run happens on its own background thread so it never holds up the
  collector.
- **RUN NOW** (the control is on the settings page, not in these files):
  starts a run regardless of the schedule. Refused with "the server check is
  off. Turn it on and save first." or "no alert channel is set up, so the
  report would go nowhere." Also starts the reply poller immediately.

## The daily server check: what Claude Code is allowed and given
(source: triage.py)

- **Which Claude Code** (the gate):
  - Normal (studio) build: requires the site feature `ai_cli_providers` on
    ("Claude Code is switched off on this server (the site feature
    ai_cli_providers)") and a Claude Code executable found by the AI
    providers settings ("Claude Code is not installed on this server
    (Settings, AI providers)").
  - Locked (vendor) build: requires the site's Anthropic API key ("The server
    check needs an Anthropic API key (Settings, AI providers) on this build")
    and a Claude Code executable (a typed path, PATH, or the publisher install
    under `<data>/tools`). The run gets no stored sign-in or setup token; only
    the API key, and its own writable home folder `.../api-home` (mode 0700).
  - The Anthropic API (SDK) is never used as a substitute.
- **Command**: `claude -p --output-format json --model <opus family alias>
  --allowedTools Read,Grep,Glob --disallowedTools
  Bash,Edit,Write,MultiEdit,NotebookEdit,WebFetch,WebSearch,Task --add-dir
  <the dashboard's own source package>`, run in the run's folder, prompt on
  stdin, 20-minute timeout.
- **Evidence file** `<data>/triage/<run id>/evidence.json`, built from: open
  notices (200), alert ledger rows of the last 48 h (500), the open alert
  counts, the invariants page, collector status, the fleet grid, live
  transfers and queue, open fleet jobs (500, with counts per kind/state), the
  packages view, and the previous run's offered actions and what became of
  them. A section that cannot be read becomes `{"error": …}`. Nothing from the
  settings table or the secrets folder is read.
  - Scrubbed before writing: any field whose name contains password, passwd,
    token, secret or api key is replaced with `[redacted]`; any value looking
    like `sk-…`, `cce1.…` or `ghp_…` is replaced.
- **Prompt** (fixed text): read-only role; read evidence.json; read the source
  when needed; list what needs a person, most important first, with evidence
  and a suggested action; do not list what is fine; "A computer with no
  projects ticked is never a problem"; all_clear when nothing needs a person;
  suggest actions only from the catalogue; a code defect is a finding with a
  paste-ready `code_fix_prompt`, never an action; plain text, no markdown, no
  em dashes; answer with one JSON object (subject, headline, all_clear,
  findings with title/severity/evidence/suggestion/action_refs/
  code_fix_prompt, actions with n/action/params/why).
- **Answer cleaning**: at most 30 findings and 20 actions; severity forced to
  error/warn/info (default warn); texts capped at 4,000 characters; em dashes
  replaced with " - "; all_clear only if there are no findings.
- **Action validation before offering**: each proposed action needs a number
  1 to 99, unique; must be a catalogue action with exactly its parameters and
  must pass its check against the database now; duplicates dropped. Dropped
  proposals are listed under "Suggested but not offered:" with the reason.

## The daily server check: the email
(source: triage.py)

- Sent through the alert channel (`_transmit`), recorded in the alert ledger
  as kind `triage`, subject "server check".
- Subject: "[CC Sync] Server check: <model's subject, or 'all clear' / 'what
  needs you'>".
- Body: the headline (or "All clear: nothing on the server or the fleet needs
  a person."); "WHAT NEEDS YOU" with numbered findings "[SEVERITY] title",
  "Evidence:", "Suggested:", "Actions: [n]", and "A prompt for a code fix
  (paste into Claude Code in the repo):"; "ACTIONS A REPLY CAN CARRY OUT"
  with "[n] <action description> - <why>"; the dropped list; then either the
  reply footer or "Nothing in this check can be done by reply."
- Reply footer: 'To carry any of these out, reply to this email, e.g. "do 1
  and 3".' and "Reference: CCT-<token>   (valid until <local time>, each action
  runs once)". If replies are off: "Replies are switched off on this server
  (Settings, Alerts, SERVER CHECK: reply address), so these can only be done
  on the dashboard."
- The reference token is random (16 bytes), valid 48 h; only its hash is
  stored. The stored copy of the email shows only its last four characters.
- A Reply-To header (the reply address) is added only when actions were
  offered and replies are enabled.
- **Fallback email** when the analysis cannot run (gate refused, CLI timeout
  "Claude Code did not answer within 20 minute(s)", could not start, non-zero
  exit, error reported, no JSON object): subject "[CC Sync] Server check: the
  analysis could not run"; body names the reason, then what the dashboard
  itself can say: open notices (up to 40, by kind description and subject),
  "Computers not syncing:" (each fault why-sentence) and "Background jobs
  failing:", then "This message is sent because the check always reports. If
  these stop arriving, the server check itself is broken."
- **Crash email**: if the run itself fails: subject "[CC Sync] Server check:
  the check failed", body "The server check failed before it could finish:
  <error> … Nothing was changed. The next check will try again."
- **Run record and retention**: each run is recorded (start, finish, status
  ok / fallback / failed, whether the email went, detail, the stored report).
  Offered actions whose token has expired are marked `expired` at the start of
  each run and each poll. Runs, their actions, their folders and reply
  records older than 60 days are deleted at the start of each run.
- **Settings page block "SERVER CHECK"** shows: on or off, whether Claude Code
  is available and why not, the IMAP host, whether replies are enabled, the
  time zone, the last run (time, status, email sent, detail), "running since"
  if one is running, and the last reply poll's outcome. A stored report can
  be shown as text ("Subject: …" plus the masked body, or a one-line status if
  no body).

## The daily server check: replies by email
(source: triage_mail.py)

- **Enabled only when** the check is on, a reply address is set, and the
  alert sink is `smtp` (the IMAP login is the SMTP account's user and
  password).
- **IMAP host**: `alerts_imap_host`, else derived: `smtp.gmail.com` gives
  `imap.gmail.com`, `smtp.X` gives `imap.X`; otherwise none and the poll
  cannot read ("replies cannot be read: the IMAP host, the SMTP user or the
  SMTP password is not set").
- **Poll**: a background thread every 120 s while replies are enabled; it
  stops itself when they are switched off and is restarted by the next alerts
  pass. IMAP over TLS, port 993, 30 s timeout, certificate verification
  following `alerts_smtp_verify_tls`.
  - Searches INBOX for messages TO the reply address SINCE two days ago (read
    and unread alike).
  - Handles at most 20 not-yet-handled messages per poll (oldest first),
    peeking at up to 500 headers to skip already-handled ones.
  - The last poll's outcome (time, ok, handled count, "nothing new" or the
    verdicts, or the error) is stored for the settings page.
  - Errors: "could not read the inbox (<type>: <server message>)".
- **Per message**, in order:
  - Already handled (by Message-ID): ignored; skipped ones keep their flags.
  - Not actually addressed (To/Cc) to the reply address: recorded as skipped,
    flags untouched.
  - Sender not one of `alerts_smtp_to`: refused (check "sender").
  - Authentication: the receiving server's Authentication-Results must report
    `dkim=pass` (signing domain = sender's domain) or `dmarc=pass` (header.from
    = sender's domain). For `imap.gmail.com` only a header written by
    `mx.google.com` counts; otherwise the topmost header. Parenthesised
    comments are ignored. If no such pass exists, the message still passes when
    the sender is the mailbox account itself AND the identical message (same
    Message-ID, From, Subject and body; up to 5 candidates compared) is in
    that account's Sent folder (found by its Sent flag) AND no explicit
    dkim/dmarc fail or permerror is present. Otherwise refused (check
    "authentication").
  - Must carry `CCT-<token>` (in subject or body) matching an unexpired run;
    otherwise refused (check "reference": "the reference in the reply has
    expired (a check's actions can be chosen for 48 hours)" or "the reply
    carries no reference (CCT-...) from a check this server sent").
  - Accepted: recorded as "acting" before anything is done, so a crash never
    acts twice; then interpreted and executed; recorded as "acted" with a
    summary like "1=done, 3=refused".
  - Handled messages are marked read (\Seen).
- **Refusal**: never answered by email. Notice `triage_reply_refused` (warn),
  subject = the failed check: "A reply to the server check email from <who>
  was not acted on: <reason>. Nothing was changed, and no answer was sent,
  because answering a forged sender sends mail to whoever it pretended to
  be." Fixes per check: reply from an address in Settings, Alerts, TO; the
  mail provider did not vouch for the message (use the dashboard's buttons);
  reply to the most recent check email within 48 hours. Closes itself when a
  later reply from the same sender is acted on, or after 7 days.
- **Reading the reply**: only the reply's own words (text above "On … wrote:",
  a ">" quote, "Original Message", or "--"; HTML is stripped of tags), at most
  4,000 characters.
  - Read in code without any model: "all" / "do all" / "all of them" (all
    offered), "none" / "nothing" (none), or a list of numbers such as "1, 3",
    "do 1 and 3", "1 & 2".
  - Anything else goes to a second Claude Code call (model "sonnet", every
    tool disallowed, 180 s timeout) that answers which numbers to do or skip
    and what is unclear. If Claude Code is unavailable: "the reply is not a
    list of numbers, and Claude Code is not available to read it (…)".
- **Executing**: each chosen number once, in order. States: done, refused (re-
  validation said no), failed (error), "not done again" (already handled),
  "not understood" (not offered). Each action can run only once across all
  replies.
- **Confirmation email** (only for accepted replies): subject "Re: <original
  subject>"; "What your reply asked for:" then "[n] <action>: done / refused /
  failed / not done again / not understood - <detail>", or "Your reply did not
  choose any of the offered actions, so nothing was changed."; "Not clear from
  your reply: …"; "Note: …"; "Nothing else was changed."; how to carry out
  another; the reference line again. Recorded in the alert ledger as kind
  `triage_reply`.

## The daily server check: actions a reply can carry out
(source: triage_actions.py)

- Each action is checked when offered and again when chosen; a failed check
  is a refusal with the reason. Parameters: names exactly as listed, strings
  up to 128 characters with no control characters, ids positive integers;
  editor names are lower-cased. Every action calls the same function the
  dashboard button does (and writes the same audit rows that function
  writes). The acting user is recorded as "triage-email:<sender>".
- `push_update(editor, machine)`: "Push the current companion build to
  editor/machine". Refused if no such computer, no current companion build for
  its platform, or it already runs the current build. Result: "asked e/m to
  update to X on its next report".
- `cancel_push(editor, machine)`: "Withdraw the pushed update for e/m".
  Refused if no such computer or no update is waiting.
- `resume_breaker(editor, machine)`: "Resume proxy download on e/m". Refused
  if no such computer or its last report does not show the brake tripped.
- `clear_fleet_halt()`: "Start syncing again everywhere (release the
  fleet-wide stop)". Refused if no fleet-wide stop is active.
- `keep_halted()`: "Keep syncing stopped everywhere, for 24 hours from the
  reply". Extends the stop's expiry, keeping its reason and start. Refused if
  not active.
- `cancel_job(job_id)`: "Cancel fleet job #N". Refused if no such job or it
  is already finished. Result explains it stops on its next report, or, for a
  job pinned to the server, when the server's own worker next checks it.
- `dismiss_notice(notice_id)`: "Dismiss notice #N". Refused if no open notice
  with that id. "it comes back by itself if the condition is still true".
- `request_diagnostics(editor, machine)`: "Ask e/m for its diagnostics".
- `nudge_collector()`: "Ask the server's background jobs to run now". Refused
  if the collector is not running in this process.
- Not available by reply: approving a pending device (deliberately left out).

## Looks redundant or overlapping

- The same condition is reported on several surfaces at once, often mailed
  twice: every open notice of severity error is mailed by alert kind
  `notice_error`, so a notice that also has its own alert kind goes out twice.
  Pairs found: `broll_archive_unreadable` (notice and alert, same probe);
  `enforce_refusal` (notice and alert); `deactivation_refusal` (notice and
  alert); `feed_runtime_mismatch` (notice and alert); `ignored_report_sections`
  notice and `ignored_sections` alert; `syncthing_unreachable` notice and
  `nas_engine_down` alert; `collector_cycle_failed` notice and
  `collector_kind_failed` alert.
- Broken invariants are written as `invariant_broken` notices (error ones then
  mailed by `notice_error`) AND mailed by the `invariant_broken` alert kind.
- Identity collisions are found three times: notices `duplicate_machine_id` /
  `duplicate_device_id`, invariant 3 `one_identity_per_computer`, and the
  resulting `invariant_broken` notice and alerts.
- Tree missing or empty is checked by notice `projects_dir_missing`, alert
  `nas_tree` and invariant 5 `tree_markers`, each with its own wording.
- A tick with no share: notice `plan_without_share` and invariant 1
  `plan_has_share` compute the same fact.
- No alert channel: notice `alerts_sink_none`, invariant 15
  `alerts_deliverable` and the protection panel's sink line.
- Feed health: notice `feed_unreachable` (48 h) and alert `feed_stale`
  (7 days) use different thresholds for the same feed.
- Disk space, editor computers: alert `disk_low` (red chip), alert `disk_park`,
  notice `machine_disk_low` (under 50 GB), the DISK chip and the why sentence.
  Server's own volume: notice `dashboard_disk_low` (under 2 GB) and alert
  `data_disk` (under 10 percent).
- Silent computers: alert `machine_silent` (24 h, stops repeating at 14
  days), notice `machine_forgotten` (14 days), alert `fleet_silent_at_once`,
  the row's red dot at 6 h and the headline.
- Release channel: alerts `versions_behind`, `rollout_stalled`,
  `platform_channel_stale`, `soak_failed`, `retracted_running`,
  `upgrade_failed`, `upgrade_refused`, `upgrade_reverted`, `feed_stale`,
  `feed_runtime_mismatch`, `code_not_applied`, plus invariants 6, 7, 11, 12:
  about fifteen overlapping views of "did the build reach the fleet".
- yt-dlp age is checked per computer (`ytdlp_stale`) and on the server
  (`ytdl_stale`); yt-dlp failure per computer (`ytdlp_failed`) and on the
  server (`ytdl_downloads_failing`, `ytdl_worker_dead`).
- Four scheduled outgoing messages: the per-cycle digest, the weekly report,
  the daily heartbeat and the triage report (up to four a day). The weekly
  report repeats the scan the digest already sent.
- Two separate secret scrubbers with different patterns: the crash report
  redactor (crash_report.py) and the triage evidence scrubber (triage.py).
- The alert scan recomputes the b-roll archive probe that the notice pass also
  runs every cycle.

## Claims the code does not back

- triage_mail.py docstring: "`UNSEEN TO "<reply_to>" SINCE <2 days ago>` is
  the only query this module sends". The code searches without `UNSEEN`
  (`TO … SINCE …`) and also searches the Sent folder by Message-ID.
- triage_mail.py docstring: a reply needs the TOPMOST Authentication-Results
  to pass. The code, for `imap.gmail.com`, uses the first header written by
  `mx.google.com`, and also accepts a reply with no passing header when the
  identical message is in the mailbox account's own Sent folder.
- invariants.py `Invariant` docstring: a `warn` invariant "does not" reach the
  alert sink. The `invariant_broken` alert kind mails every row the broken
  invariants ledger returns, with no severity filter in alerts.py (assuming
  the ledger read returns warn invariants too; that read is in db.py).
- notices.py `_check_alerts_sink` docstring: "Forty checks, ten invariants".
  The registry holds 70 alert kinds (plus `check_failed`) and 15 invariants.
- mount_status.py docstring: "the four optional mounts". `NAMES` lists five
  (`broll`, `music`, `ytdl`, `cards`, `sorter`).
- alerts.py defines `DATA_DISK_RED_PERCENT = 5.0`; nothing uses it. The
  `data_disk` alert fires at under 10 percent, always as an error.
- alerts.py `_lane_bytes_section`: the weekly report's "bytes moved" section is
  described as a feature but never prints (the column does not exist).
- triage.py docstring: "twice-daily" at 06:00 and 18:00; the hours are a
  setting (up to four a day). The "studio sets Asia/Taipei on deploy" remark
  is not in these files.
- invariants.py docstring: "THREE STATES, NEVER TWO" while listing and using
  four states.
- Fix texts that state other components' behaviour that these files do not
  show: `machine_trash_oversize` ("clears these by itself every 6 hours"),
  `dashboard_disk_low` ("Below a floor it refuses to publish builds"),
  `unopened_out_of_tree` ("The companion reminds them every 30 minutes"),
  `keep_halted` ("for 24 hours from the reply").

## Could not determine

- The exact dedup window behind "already sent today" (`db.alert_recently_sent`)
  and what `db.broken_invariants`, `db.notice`, `db.clear_notice`,
  `db.auto_clear_notice` and `db.dismiss_notice` do beyond their names: they
  live in db.py, outside this part. Comments say the window is 24 h.
- The collector intervals for the alerts, notices and invariants passes, and
  where the watchdog restart count comes from (collector.py / app.py).
- The routes and page controls that drive these features (Settings, Alerts
  form, "Send a test", the per-kind switches form, CURRENTLY OPEN, WHAT WAS
  SENT, dismiss on a notice, "Download crash reports", RUN NOW, the
  Invariants page, `/api/v1/health`). Only the helpers are in these files.
- How a notice of severity `info` (`editor_without_machine`) is displayed.
- The writers of the `collector_watchdog_restart` and `file_move_detected`
  notices, and the callers of `record_db_busy`, `record_slow_write`,
  `record_slow_poll`, `record_server_error` and `record_moves_dropped` (all in
  other files), so exactly when those events fire.
- How long `keep_halted` actually extends a stop (decided in db.py).
- The wording of the "retired" reason in `jobs_pinned_no_executor`, which is
  composed in cards_exec.py.

## Files in this part and where they appear

- alerts.py: alert settings, the alerts pass, delivery channels, weekly report,
  heartbeat, ledger page helpers, every alert kind section.
- notices.py: the notices sections (pass, kinds, boot, events, self-closing,
  crash zip).
- invariants.py: the invariants sections.
- health.py: health colours, lane chips, disk, why sentence, headline, privacy
  and licence facts.
- mount_status.py: optional page mount status.
- crash_report.py: crash reports and log files.
- triage.py, triage_mail.py, triage_actions.py: the daily server check
  sections.
