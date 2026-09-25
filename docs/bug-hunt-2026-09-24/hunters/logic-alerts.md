# logic-alerts - self-diagnosis and triage: alerts, notices, invariants, health, triage, triage_mail, triage_actions (wave 2: logic + usability)
Files read (approximate coverage): triage.py (all), triage_mail.py (all), triage_actions.py (all), notices.py (1-1100, 1480-1703: run_checks, collector/tree/identity/pending/plan/space/forgotten/mounts/broll/contention/sink/crashes/dashboard-space/feed checks, CR-320 RESOLVE_RULES), alerts.py (Ctx 1031-1240, checks 1371-2100, 2262-2600, 2677-3300, 3489-3790, delivery/deliver/run_cycle 4272-4775, schedules 740-920), invariants.py (1-180, 286-670, 1035-1412), health.py (why_not_syncing 400-1000, fleet_headline 1051-1170, disk_status), db.py notice ledger (3655-3870), collector.py (hand-move recording, _run_invariants, _timed), mount_status.py (head), protection.py (snapshot lines 300-452), release_feed.py (record_offer_state, _apply_policy). KNOWN_BUGS CR-320 inventory, bug-dash-diag.md (wave 1, same files) read first to avoid duplicates.
Tests/probes run: four ad-hoc probes from the dashboard venv against temp databases (scratchpad la1.py, la2.py, la3.py, la4.py), quoted in the findings. No suite run.

## Findings

### logic-alerts-1 - A mount a site deliberately left OFF raises a permanent "page is not available, check the bind mounts" warning
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/notices.py:720-746 (_check_feature_mounts); statuses from ytdl.py:651-654 and cards.py:677-687
- What: `_check_feature_mounts` treats every status other than `mounted` as a fault. But `disabled` is the mounts' own word for "this deployment did not ask for it" (cards.py:80-84 says so): the YouTube feature is off in the vendor build (`youtube_download`, CLAUDE.md), and Cards is `disabled` wherever `DASH_CARDS_SRC` / `DASH_CARDS_ENABLED` is not set. Each of those becomes an open `feature_not_mounted` warn card whose fix is "Check the container's bind mounts, then restart the dashboard". Nothing the owner can do clears it, because nothing is broken.
- Failure scenario: a customer runs the vendor build with YouTube downloading off and no Timeline Cards. Two warn cards stand on PROBLEMS THE SERVER FOUND for the life of the install: "The YOUTUBE page is not available on this server: this site has not enabled the YouTube downloader... Check the container's bind mounts (docs/DOCKER.md), then restart the dashboard." A non-technical owner restarts the container, the cards come straight back, and the twice-daily server check reads both in its evidence bundle.
- Evidence: probe la1.py with broll/music `mounted`, ytdl `disabled`, cards `disabled` -> two open `feature_not_mounted` warn notices with the bind-mount fix. No test covers the `disabled` status (tests use only `absent`).
- Ledger: new (DDIAG-7 designed the kind; dash-collector-alerts-8 fixed its keep-list; neither looked at `disabled`)
- Suggested fix: treat `disabled` like `mounted` for this notice (skip it and leave it out of the keep-list so a card from a previous `absent` boot closes). Write the card only for `absent` and `degraded`.

### logic-alerts-2 - `versions_behind` counts builds that are not on offer, so a computer running the CURRENT build is "3 releases behind" and is told to press a button that cannot help
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/alerts.py:2379-2427 (_check_versions_behind)
- What: "newer" is every non-retracted row in `companion_packages` for the platform, which includes STAGED builds (held by the soak gate or waiting for an admin) plus every version in the vendor feed. So a machine already on the current build is counted behind by builds this site has not made current. The finding then says "running 0.9.70, current is 0.9.70" in the same sentence as "3 releases behind", and its fix is [ UPDATE NOW ], which pushes the current build, i.e. the one it already runs. `triage_actions._v_push_update` refuses exactly that ("already runs the current build"), so the triage agent cannot act on it either.
- Failure scenario: this is the studio's own state in memory ("macos 0.9.70 held by the soak rule" while 0.9.71/0.9.72/0.9.74 are staged). leso's Mac on 0.9.70 raises a warn saying it is three releases behind the current 0.9.70. The owner presses UPDATE NOW, nothing happens, and the alert stays. On a `manual`-policy customer site every computer is "behind" as soon as the vendor has published three builds the admin has not adopted, which is exactly the SYS-2 case the vendor-feed counting was meant for. That case needs "update the dashboard / make a newer build current", not UPDATE NOW.
- Evidence: probe la2.py: macos packages 0.9.70 current plus 0.9.71/0.9.72/0.9.74 staged, machine on 0.9.70 -> finding "leso/Mac is 3 releases behind on CC Sync (it is running 0.9.70, current is 0.9.70)... fix: [ UPDATE NOW ] on that computer."
- Ledger: new (related to REL-6 / SYS-2, which set the counting)
- Suggested fix: count only builds newer than the running one AND at or below the platform's current, for the "press UPDATE NOW" finding. When the running build IS current but newer builds exist on the shelf or in the feed, raise a different sentence ("newer builds are published but not current: make one current on Packages, or update the dashboard if the feed refused them").

### logic-alerts-3 - `platform_channel_stale` tells the owner to BUILD a Mac release that already exists and is only waiting to be made current (and names repo commands on sites that have no repo)
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/alerts.py:2986-3055 (_check_platform_channel_stale)
- What: the check compares the two platforms' CURRENT versions and counts the leader's published builds. It never asks whether the lagging platform already has a newer build published but staged, for example held by the soak gate. It always concludes "nothing will offer it to them until somebody builds it", and the fix is a hard-coded pair of `release_macos.sh --publish --make-current` commands. Two wrong cases follow. (a) When the Mac build is already staged, re-running the publish is refused ("version already published") and the real action is one click on Settings, Packages. (b) On a customer dashboard fed by the vendor feed there is no repo and no Mac build machine, so the fix cannot be carried out at all. The same text also appears when the lagging platform is Windows.
- Failure scenario: studio state from memory: Windows current 0.9.74, macOS current 0.9.70 with 0.9.71/0.9.72/0.9.74 staged. The owner (non-technical) is mailed "it is 3 builds behind... nothing will offer it to them until somebody builds it" plus terminal commands for a Mac. The build exists and only needs making current.
- Evidence: probe la3.py with exactly that package table -> finding "The current CC Sync build for macos computers is 0.9.70 and it is 3 builds behind... until somebody builds it", fix "On a Mac, in the repo: git pull && ./tools/release_macos.sh --publish --make-current...".
- Ledger: new (REL-13 introduced the kind)
- Suggested fix: first look for a published, non-retracted lagging-platform build newer than its current. If there is one, say "0.9.74 for macOS is published but not current (staged since ...): make it current on Settings, Packages" and name the soak state. Keep the build commands only for the vendor's own site (e.g. behind a vendor/site flag) and word the customer case as "the vendor has not published a macOS build yet".

### logic-alerts-4 - Every server check email carries the reply address, but a reply to one with no actions (all-clear, fallback) is refused and leaves a warn card whose fix cannot be done
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/triage.py:733 (run: `_send(..., reply_to, now)` for report AND fallback), triage.py:522-525 (no CCT line when nothing is offered); triage_mail.py:500-506, 426-439 (refusal + card)
- What: `run()` sends every report with `Reply-To: <reply address>`, including the all-clear, the "Nothing in this check can be done by reply" report and the "analysis could not run" fallback. None of those bodies contains a `CCT-` reference. The owner's natural reply ("thanks", "what about the Mac?") passes the sender and authentication checks and is then refused under `reference`. That opens a `triage_reply_refused` warn card: "Reply to the most recent server check email. A reference is good for 48 hours". The most recent email had no reference to reply with, and the owner gets no answer at all, although this is an authenticated owner, not the forged sender the no-answer rule exists for. Under CR-320 the card closes only on a later ACTED reply from the same address or after 7 days.
- Failure scenario: the 06:00 check is an all-clear. The owner replies "great, thanks". Nothing comes back, and a warn card appears on the home page telling him his reply was not acted on and to reply to an email that has nothing to reply with. It stays for up to a week, and the next check's evidence bundle includes it, so the agent may report it back to him.
- Evidence: probe la4.py: `compose_report` for an all-clear gives a body with no CCT line; `handle_message` on an allowed, DKIM-passing reply to it returns `refused` and writes the `triage_reply_refused` / `reference` notice with that fix.
- Ledger: new
- Suggested fix: send the Reply-To header (and keep the token) only when the report offers actions. For an authenticated allowed sender whose reply has no token, send a short confirmation ("this check had nothing to act on; nothing was changed") instead of a card, since the backscatter reason does not apply once sender and DKIM have passed.

### logic-alerts-5 - Invariant 9 "the customer's data is on a snapshot schedule" is OK when ANY task exists, checks the dashboard's dataset, and names the tree in its fix
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/invariants.py:627-666 (_check_snapshot_schedule), 1102-1112 (its registry row)
- What: the check passes when any enabled periodic snapshot task exists anywhere on the NAS. The only dataset it checks by name is `DASH_UPDATE_SNAPSHOT_DATASET` (the dashboard's own data, per its broken sentence). Yet the registry fix says "add a task for the dataset the project tree lives on", so a broken verdict about the dashboard's dataset sends the owner to snapshot the tree. And on the same Protection/Invariants surfaces, `protection.snapshot_tree` (which does check `DASH_TREE_DATASET`) can say MISSING while invariant 9 reads green "the customer's data is on a snapshot schedule". That contradiction is exactly the "every page renders green about it" failure the docstring cites.
- Failure scenario: the NAS has one hourly task on `tank/apps/ccsync-dashboard` (the CR-227 dataset) and none on the footage. Invariant 9 is OK ("1 enabled snapshot task(s) on this NAS") while the protection panel says the tree has no snapshot task. If `DASH_UPDATE_SNAPSHOT_DATASET` names an uncovered dataset, the card body talks about "the dashboard's own data" and the fix tells the owner to snapshot the project tree.
- Evidence: read of both functions and the registry row; protection.py:325-352 shows the tree/apps split that invariant 9 predates.
- Ledger: new (related to bug-dash-diag's coverage note on `protection._check_snapshot_recent`, same any-task shape)
- Suggested fix: make invariant 9 defer to the protection lines it duplicates (read `protection`'s stored tree/apps verdicts), or at least check `DASH_TREE_DATASET` for the tree and word the fix per dataset it actually found uncovered.

### logic-alerts-6 - The invariants collector job can never be green: two invariants are hard-wired NOT CHECKED, so its note is always "2 not checked here" (amber)
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/invariants.py:1376-1386 (_note), 1092-1101 and 1155-1177 (skip_reason rows); db.py collector_health ("A kind with a note is amber")
- What: `versioning_agrees` (8) and `cards_tree_matches_source` (14) carry a permanent `skip_reason`, so every pass has two NOT_CHECKED results. `_note` turns any NOT_CHECKED count into text, the collector returns it as the kind's note, and `collector_health` renders any note as amber. So the invariants job is amber on every pass of every site, and `_note`'s own docstring promises the opposite ("None on a wholly clean pass: a panel that always carries text stops being read").
- Failure scenario: the collector health panel on the home page permanently shows the invariants job amber with "2 not checked here" (plus "no full ticks with a known computer to check" on a fleet with nothing ticked). An owner learns to ignore amber there, which is the moment a real "1 invariant(s) broken" note arrives unread.
- Evidence: `_note(_counts(...))` over the registry with every checkable invariant OK returns "2 not checked here" (probe run inline); `db.collector_health` status = "amber" if note.
- Ledger: new
- Suggested fix: leave invariants with a static `skip_reason` out of the note's NOT_CHECKED count (they are "not checkable in this build", not "could not check this pass"), or count only NOT_CHECKED results that came from a check which ran.

### logic-alerts-7 - A hand move with no computer to follow it keeps its "computers are following" card for 7 days
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/notices.py:1602-1628 (_file_move_followed), collector.py:1904-1931 (the card)
- What: the CR-320 evidence returns "" when the detected move has no targets, so the card falls back to the 7-day quiet period. A zero-target move needs nothing more: no computer holds the file, the move is complete when it is detected, and the card itself says "0 computer(s) are following... Nothing to do". The docstring's reason for waiting ("a never-answered one is file_move_expired's business") only applies when there are targets.
- Failure scenario: the owner reorganises footage on the base rig, which works straight off the NAS (a wired machine holds no synced copy), or files that only ever lived on the server. Every such move is an info card saying nothing is needed, and it stays on PROBLEMS THE SERVER FOUND for a week, not the 24 h that CR-320 gives a move whose followers finished.
- Evidence: read; `if not targets: return ""` at notices.py:1624-1625, then `quiet_hours` 7*24.
- Ledger: related to CR-320 (fixed in repo, unshipped; this is a gap in its rule table)
- Suggested fix: treat "no targets" as evidenced ("no computer held a copy"), still subject to `min_hours` = 24, so the card is readable for a day and then closes.

### logic-alerts-8 - Disk warnings about a computer that syncs nothing name a consequence that cannot happen and a fix that cannot be done
- Severity: low
- Confidence: PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/alerts.py:1440-1467 (_check_disk_low, error, daily repeat); notices.py:593-610 (machine_disk_low)
- What: neither check looks at the computer's plan or role. For a computer with nothing ticked (owner rule: a fine state), or one set to wired, the diagnosis says "Proxy download fills a drive file by file... this ends with that editor unable to work" or "stops it syncing", and both fixes say "untick a project for that computer". There is nothing to untick and no proxy download running. `disk_low` is an ERROR, so it is re-mailed daily.
- Failure scenario: alex/Razer (nothing ticked, per the owner's own example) has 15 GB free on its drive: a daily error mail saying proxy download will leave the editor unable to work, with an untick instruction that has no target.
- Evidence: read; no `plan`/`mode` read in either check, while `health._why_first` and `invariants._check_machine_has_plan` both special-case these machines. Not probed against a live report, so whether a nothing-ticked or wired companion reports `disk_root_*` for a real drive is unverified.
- Ledger: new
- Suggested fix: for a machine with no full tick (or mode `base`), either skip the alert or use a plain "this computer's drive is nearly full" sentence with no sync consequence and no untick fix, as a warn rather than a daily error.

### logic-alerts-9 - The reply poll takes the newest 20 messages BEFORE skipping the handled ones, so an older unhandled reply is never read
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/triage_mail.py:628-640 (poll)
- What: since the search stopped using UNSEEN (2026-09-24), it returns every message to the reply address in the last two days, handled ones included. It slices `[-MAX_MESSAGES_PER_POLL:]` first and only then skips the Message-IDs already in `triage_replies`. The comment ("the rest wait for the next poll") is false: every later poll takes the same newest 20, so anything older than the newest 20 in the window is never handled and ages out of the 2-day SINCE window unread.
- Failure scenario: a burst of mail to the +address (a mailing loop, a forwarding rule, or simply many short replies over two days) pushes the owner's real reply, sent earlier, outside the newest 20. It is never acted on, never refused and never mentioned anywhere.
- Evidence: read of lines 628-640: the slice is applied to the raw search result before the `triage_replies` lookup.
- Ledger: new
- Suggested fix: filter out known Message-IDs first (the header peek is already there), then cap the number of UNHANDLED messages processed per poll.

## Coverage note
Not reached in depth: alerts `_check_out_of_tree` / `_synced_project` (CR-232), `_check_folders_unfiltered` beyond CR-318's grace, ytdl server-side kinds (3299-3480), `compose_weekly`, `compose_digest`, `compose_heartbeat`; notices 1100-1480 (accounts, error redaction, record_db_busy / slow_write writers); invariants proxy_pairs, 11-15; health 1-400 (editor_status colours) and detail_notes. Not repeated here: the wave-1 bug-dash-diag findings on the same files (check_failed never recovering, protection flap on a NAS blip). Double reporting of one condition as both a notice and an alert kind was declined in the 2026-09-03 sweep (DDIAG), so it is not re-raised.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/protection.py:405-452: `_check_snapshot_recent` takes the newest run of ANY enabled task, so an hourly task on an unrelated dataset keeps "a snapshot was taken in the last day" green while the tree's own task is weeks stale (flagged for wave 2 by bug-dash-diag; confirmed by read).
- dashboard/src/ccsync_dashboard/triage_actions.py:326-332: the `dismiss_notice` summary says the card "comes back by itself if the condition is still true", which is false for the event-shaped kinds (server_error, db_busy, triage_reply_refused), where a dismiss is final.
