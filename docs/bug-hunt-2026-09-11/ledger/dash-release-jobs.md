## Dashboard release channel, self-update and the cards tunnel, 2026-09-11 (CR-242)

### CR-242a - a restart request left behind by a KILLED container wedged every apply and every rollback for the life of the next process - FIXED (dashboard, `dashboard_update.py`, dash-release-jobs-2)

`_heal_orphaned_progress` is the guard REL-9 put on the `in_progress` latch:
a flag owned by a pid/nonce that is not this process reads as "failed,
interrupted" and is cleared, because otherwise a container killed mid-apply
answers 409 for ever and the appliance shape has no shell to delete
`/data/code/update_state.json` with. It returned BEFORE that ownership test
whenever `restart_requested` was set, and that flag is written by
`request_restart` a moment before the process SIGTERMs itself. A process that
never reaches the lifespan's shutdown (SIGKILL, OOM, NAS power loss) leaves
`in_progress: true, restart_requested: true` on disk owned by a nonce that no
longer exists, and `consume_restart_request` - the only thing that clears it -
runs exclusively in that shutdown. The next process then refused both
`preflight` and `rollback` with "an update to 0.7.43 is in progress (step:
restarting)" at every admin click. Not for ever, which is what downgraded it:
the next CLEAN shutdown of any later process does consume the flag, so a
container restart cured it. It is the one door REL-9's fix left open.

The exemption now depends on the flag's OWNER, not on the flag. A
`restart_requested` state whose `owner_nonce` is this process's is honoured
exactly as before (that is what lets `finish_restart` choose
RESTART_EXIT_CODE, and the pid is deliberately not part of this test - the
nonce is what identifies a process, REL-9); one owned by any other nonce is
spent, and the first `read_state` of the new process clears it to `step:
done, in_progress: False` and says so in the log. A process that was killed
mid-restart therefore exits 0 rather than 75 at its next shutdown, which is
correct: the re-exec already happened.

### CR-242b - a feed URL with a query string could never fetch its signature, so such a site silently received nothing - FIXED (dashboard, `release_feed.py`, dash-release-jobs-3)

The detached channel signature was fetched at `<feed url> + ".sig"`, which is
the right file only when the feed URL is a bare path. The threat model this
module is written against contemplates "an S3 bucket, whatever a customer's
outbound network reaches", and a pre-signed or CDN-token URL carries a query:
`https://host/channel.json?X-Amz-Signature=...` + `.sig` is a URL that does
not exist. Every check then failed with a 404 naming a URL the operator never
configured, the feed cached it as `last_error`, and the site quietly stopped
receiving builds - REL-11's exact shape. `_signature_url` splits the URL and
appends `.sig` to the PATH, leaving the query intact (a fragment is dropped:
it never reaches the server anyway).

### CR-242c - `FeedPoller.start()` after `stop()` started nothing and said it had - FIXED (dashboard, `release_feed.py`, dash-release-jobs-4)

`stop()` set the event and joined but never cleared `_thread`, and `start()`
returned early whenever `_thread` was set, so a reused poller reported itself
started and never polled - green while dead - against a docstring that claims
both calls are idempotent. Nothing in the field reaches it today because
`app.py` builds a fresh poller per lifespan; it was waiting for the first
caller that reuses one (a reload path, a test harness, a future pause/resume
button). `start()` now clears the event and `stop()` drops the thread, which
is the shape `cards_exec.PinnedExecutor` has always had - the two threads in
this territory disagreed about the same pattern.

### CR-242d - the cards tunnel fell back to the agent's self-asserted hostname - FIXED (dashboard, `cards_tunnel.py`, dash-release-jobs-6)

Rule 1 of that module is that the name the cards page shows is the VERIFIED
identity plus the machine the caller DECLARED, never the body's own `name` -
which is the agent's `socket.gethostname()` string. The state route
implemented it as `body["machine"] or body["name"] or ""`, so a caller that
declared no machine got its own hostname through. The editor half stays
verified, so this was display spoofing and not an auth bypass: anything
holding a fleet credential could make the away/stale text read
`alex/ANYTHING-I-LIKE`, which is misleading exactly where "which computer is
driving Resolve" is the question. It is `body["machine"]` alone now, falling
back to the editor by themselves.

### CR-242e - a feed record whose platform is not lower-case is dropped, not offered as a button that can never work - FIXED (dashboard, `release_feed.py`, dash-release-jobs-7)

`_record_key` kept a record's own spelling while the admin [ PUBLISH ] route
case-folds what the page posts, so a build published as `Windows` was listed
as available and then answered `404 no verified feed record for
companion/windows/0.9.0 -- run Check now first` at every click, telling the
admin to re-check a feed that was fine. Folding the key alone is not enough
and the fix went further than the hunt suggested: the platform string is
inside the record's SIGNATURE, so publishing the folded spelling fails
`store_verified_package`'s re-verification with "no configured release public
key verifies this record" - a sentence about trust for what is really a
spelling. So `_record_key` now speaks one spelling for every consumer (the
view, the dedupe, the `current` pointer, the publish lookup) AND
`_valid_records` drops a record whose kind or platform is not already
canonical, naming it in the log beside the other two drop reasons. No producer
we ship emits one; a hand-edited channel is what this defends.

### Verification
- dashboard/tests/test_dashboard_update.py::test_a_restart_request_left_by_a_DEAD_process_is_spent_not_honoured -> fails at 40f931a, passes now (dash-release-jobs-2)
- dashboard/tests/test_release_feed.py::test_a_feed_url_with_a_query_string_still_finds_its_signature -> fails at 40f931a, passes now (dash-release-jobs-3)
- dashboard/tests/test_release_feed.py::test_a_plain_feed_url_still_asks_for_the_same_signature_url -> passes before and after, pins the unchanged half
- dashboard/tests/test_release_feed.py::test_a_stopped_feed_poller_starts_again -> fails at 40f931a, passes now (dash-release-jobs-4)
- dashboard/tests/test_cards_tunnel.py::test_the_body_s_own_name_is_never_the_machine_half -> fails at 40f931a, passes now (dash-release-jobs-6)
- dashboard/tests/test_release_feed.py::test_a_capitalised_platform_is_never_offered_as_available -> fails at 40f931a, passes now (dash-release-jobs-7)
- dashboard/tests/test_release_feed.py::test_a_record_key_speaks_one_spelling -> fails at 40f931a, passes now (dash-release-jobs-7)
- dashboard/tests/test_release_feed.py::test_the_lower_case_spelling_of_the_same_record_is_published_normally -> passes before and after, pins the path every site in the field uses
- Whole files run: tests/test_release_feed.py (60 passed), tests/test_cards_tunnel.py (23 passed), tests/test_dashboard_update.py (64 passed).
- One existing test changed: test_cards_tunnel.py::test_the_verified_identity_becomes_the_agent_name now declares `machine` alongside the bogus `name`, because the behaviour it asserted (the hostname becoming the machine half) is the defect.

### OWED TO ANOTHER TERRITORY
- `companion/src/ccsync_companion/timeline_cards_role.py`: the tunnel no
  longer accepts the agent's `name` as the machine half, and nothing on the
  companion side puts a `machine` field in the `/agent/state` body today (the
  engine's `AgentClient` carries `role.machine` as its own `name`). The page
  will therefore show `alex` rather than `alex/CREATOR-1` until the companion
  declares `{"machine": <this machine>}` in that body. Safe either way, and
  the feature is off everywhere (`cards_agent`), so nothing in the field
  changes; the companion side is a one-line addition when someone owns that
  file.

### Owner decisions
- CR-242e drops a capitalised-platform record instead of publishing it under
  a folded spelling. The alternative, storing it under its own spelling so
  the signature verifies, would put a `Windows` row in `companion_packages`
  where every other surface says `windows`. The cost of the choice made: such
  a build disappears from the page with only a log line to say why, the same
  way a record with a bad `min_version` already does.
- Not fixed here because they are `db.py` and belong to dash-api-jobs:
  dash-release-jobs-1 (a cancelled job re-queued when its lease expires) and
  dash-release-jobs-3-as-numbered-by-the-hunter (the per-kind fleet cap is
  advisory across concurrent claims).
