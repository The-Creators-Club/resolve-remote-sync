# wire - every contract between two processes, both sides side by side

Files read (with approximate coverage): `git diff 40f931a..HEAD` in full for
`dashboard/src/ccsync_dashboard/api.py` (the report models, `flatten_sync_guard`,
`undeclared_report_sections`/`_nested_extra_keys`, `_upgrade_info`,
`targeted_staged_package`, `_update_push_done`, `roll_fleet_back`,
`api_claim_job`), `companion/src/ccsync_companion/app.py` (report reply
handlers: upgrade push, file moves, resolve_health/sync_guard builders),
`file_moves.py` (whole), `upgrade.py` (offer acceptance + refusal retirement),
`jobs_runner.py`, `jobs_media.py`, `broll_server.py`, `music_server.py`,
`timeline_cards_role.py`, `dashboard/.../cards_tunnel.py`, `release_feed.py`,
`jobs.py`, `db.py` (`machine_update_request`, `request_machine_update`,
`mark_file_move_applied`, `claim_next_job`), `broll/web/app/routes_fleet.py`,
`music/web/musicweb/routes_fleet.py`, `ytdl/web/ytdlweb/routes_fleet.py` +
`ytdlweb/db.py` lease helpers, `broll/web/static/ingest.js` and
`music/web/static/ingest.js` retry paths, `companion/.../sync/repath.py`,
`sync/rclone_lane.py` + `sync/lane_guard.py` trash/breaker report shapes,
`watcher.py` list readers. Skimmed: `docs/API.md`, `docs/FILE_MOVES.md`,
`KNOWN_BUGS.md` (grep).

Tests run: ad-hoc snippets only, from the two component venvs (no suite run):
`companion/.venv` - `FileMoveLedger.record_intent()` -> `state=applying`,
`retry_due()=False`; `dashboard/.venv` - `ReportIn`/`SyncGuardIn` validation of
a real `repath_events` entry -> `ValidationError`.

## Findings

### wire-1 - the crash-resume arm of the file-move ledger is unreachable, and the redelivered move is answered as a permanent failure
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:7523-7540` (the redelivery
  short-circuit) against `companion/src/ccsync_companion/file_moves.py:247-263`
  (`apply_move`'s resume arm) and
  `dashboard/src/ccsync_dashboard/api.py:8411` /
  `dashboard/src/ccsync_dashboard/db.py:5563-5572`
  (`FileMoveResultIn.state` vocabulary, `mark_file_move_applied`).
- What: res-companion-1 added `STATE_APPLYING` ("applying") to the companion's
  ledger and a resume arm inside `apply_move`, but `_apply_file_moves` never
  reaches `apply_move` on the redelivered command: it looks up the ledger entry
  first and `retry_due()` is False for anything that is not `retryable`, so an
  `applying` row takes the "already answered" branch. That branch queues
  `ok=False`, `state=None` (it only maps `blocked`), and the dashboard's
  `FileMoveResultIn.state` vocabulary is `done|failed|retrying|blocked` - a
  missing `state` means "answered, stop asking", so `mark_file_move_applied`
  writes `applied_at` and the command is never re-sent
  (`... AND t.applied_at IS NULL`). The new state exists on the companion and
  has no spelling on the wire.
- Failure scenario: the tray is killed (CR-93 abort, a reboot, an upgrade swap)
  between `src.replace(dest)` and `ledger.record()`. Next start, the dashboard
  redelivers move #N. The companion answers
  `{"id": N, "ok": false, "detail": "applying it on this machine",
  "relink_pending": true}`; the project page shows that machine as FAILED with
  a sentence that is an internal state name, the move is retired, the resume
  (proxy siblings + Resolve relink) never runs, and the ledger row stays
  `applying` for ever - which also holds that path out of lane A's excludes
  only for the exclude window, after which lane A re-uploads nothing (the file
  did move) but Resolve stays offline on the clip with no pending relink the
  dashboard knows about. Before this afternoon the same crash answered
  `ok=true, "nothing at the old path on this machine"`: the fix turned a wrong
  success into a wrong failure and delivered neither half of the resume.
- Evidence: `companion/.venv` snippet - `record_intent()` gives
  `state=applying, ok=False, detail='applying it on this machine'` and
  `retry_due()` -> `False`. `app.py`'s branch then runs
  `_queue_file_move_answer(move_id, done["ok"], done["detail"],
  state=("blocked" if state == STATE_BLOCKED else None), ...)`. The regression
  test `companion/tests/test_bug_hunt_2026_09_11_comp_sync.py:438` calls
  `file_moves.apply_move(...)` DIRECTLY, bypassing the very short-circuit that
  makes the arm unreachable, so it passes over a dead code path.
- Ledger: new (CR-233..248's res-companion-1 does not fix res-companion-1's own
  scenario end to end).
- Suggested fix: in `_apply_file_moves`, treat `state == STATE_APPLYING` like a
  due retry - fall through to `apply_move(..., ledger=self.file_moves)` instead
  of re-answering - or, at minimum, answer `state="retrying"` for it so the
  dashboard does not retire the command. Add `"applying"` to
  `FileMoveResultIn.state` only if the companion is ever meant to report it.

### wire-2 - `sync_guard.repath_events[].at` is a float on the companion and a string in the model: every report from a machine that has had a project renamed is 422'd
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/repath.py:243` (`"at":
  float(self._now())`) -> `companion/src/ccsync_companion/app.py:5050-5063`
  (`repath_events()` passes the ledger dict through unchanged) ->
  `companion/src/ccsync_companion/app.py:6416-6418` (`guard["repath_events"]`)
  against `dashboard/src/ccsync_dashboard/api.py:393-405`
  (`RepathEventIn.at: str | None = Field(max_length=64)`) and
  `api.py:7523-7524` (`SyncGuardIn.repath_events`).
- What: comp-sync-4 put the repath ledger's events on the wire and declared
  `at` as a string. The producer writes an epoch FLOAT. `_BoundedSectionIn`'s
  before-validator only truncates and clamps; it does not coerce types, and
  pydantic v2 does not coerce float -> str. `sync_guard` is deliberately NOT one
  of ReportIn's tolerant sections, so the whole report fails validation.
- Failure scenario: an admin renames a project on the server; the companion
  (0.9.71, shipping tonight) repaths the folder and records an event. From that
  moment every 30 s report from that machine is rejected 422 by the dashboard
  for the life of the ledger entry (`EVENTS_MAX` entries, no time-based
  eviction visible on the reported path). The machine goes dark on the fleet
  grid - no lane state, no breaker/halt state, and, because the reply is the
  only channel back, no `commands.halt`, no `commands.upgrade`, no
  `commands.file_moves`, no lane B resume. The editor sees nothing at all.
- Evidence: `dashboard/.venv` (pydantic 2.13.4):
  `ReportIn(editor_name=..., machine=..., reported_at=..., lanes=[],
  sync_guard={'repath_events':[{'slug':'ff5','old':'a','new':'b',
  'at':1757600000.5}]})` ->
  `1 validation error ... sync_guard.repath_events.0.at Input should be a valid
  string [type=string_type, input_value=1757600000.5]`. The same payload with
  `'at': '2026'` validates. The companion-side regression test
  `companion/tests/test_bug_hunt_2026_09_11_comp_app.py:595` invents
  `"at": "2026-09-11T09:00:00+00:00"` - an ISO string the producer never
  writes - so it passes for a reason unrelated to the code it guards, and no
  dashboard test feeds a real event at all.
- Ledger: new (comp-sync-4 landed both halves to two different contracts).
- Suggested fix: accept the producer's type - `at: float | str | None` on
  `RepathEventIn` (the same way `TrashIn.oldest` is a float epoch) - or convert
  in `app.repath_events()` before it goes on the wire. Whichever side changes,
  pin it with a test that feeds `repath.Ledger.record(...)`'s actual output
  through `ReportIn`.

### wire-3 - the same section sends seven keys and declares four, and `_nested_extra_keys` now turns that into a daily warning and a SYS-3 banner line
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/repath.py:232-247` (event keys
  `id, slug, old, new, at, relinked, note, moved`) against
  `dashboard/src/ccsync_dashboard/api.py:393-405` (`RepathEventIn` declares
  `old, new, at, relinked`) plus `api.py:8441-8466` (`_nested_extra_keys`, which
  now walks list items one level down) and `api.py:8489-8494`
  (`undeclared_report_sections`). Same shape on
  `companion/src/ccsync_companion/sync/lane_guard.py:1224`
  (`prune_trash` -> `{"skipped": "breaker tripped", ...}`) against
  `api.py:7019-7033` (`TrashIn`, no `skipped`).
- What: comp-app-2 flipped `_BoundedSectionIn` to `extra="allow"` and taught the
  walker to look inside sub-models and lists precisely so a dropped sub-key is
  NAMED. The same afternoon, comp-sync-4 added a section whose items carry three
  undeclared keys, and `trash` has carried an undeclared `skipped` since the
  breaker prune guard was written. So as soon as wire-2 is fixed, every machine
  that has had a rename logs `sync_guard.repath_events.id/.slug/.note/.moved`
  once a day and renders them on the "sections this dashboard does not read"
  banner, and every machine with a tripped lane B breaker adds
  `sync_guard.trash.skipped`.
- Failure scenario: an admin opens the fleet page after the first rename of the
  week and is told the companion is sending four fields the dashboard drops.
  Nothing is wrong, nothing can be cleared, and the banner that exists to catch
  a real dropped section (SYS-3's whole point) is now carrying noise - the
  fourth recurrence of SYS-3 was found because the banner was quiet.
- Evidence: read both sides; `_nested_extra_keys` iterates `items = value if
  isinstance(value, list) else [value]` and collects `item.model_extra`, which
  for `RepathEventIn` is exactly `{id, slug, note, moved}`.
- Ledger: new (related to comp-app-2 / comp-sync-4, both in 18e69f3).
- Suggested fix: declare `id`, `slug`, `note`, `moved` on `RepathEventIn` (they
  are the useful half: `slug` is the project and `moved`/`note` are the blocked
  case), and `skipped` on `TrashIn`; or drop them in `app.repath_events()`
  before sending. Declaring is better - `moved=False` is "this machine could not
  follow the rename", which nothing on the server can currently see.

### wire-4 - the cards tunnel stopped accepting the agent's `name`, so every companion below 0.9.71 now registers as the bare editor and two of one editor's machines collide
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/cards_tunnel.py:247` (was
  `body.get("machine") or body.get("name")`, now `body.get("machine") or ""`)
  against `companion/src/ccsync_companion/timeline_cards_role.py:869-878` (the
  companion only started sending `machine` in this same commit) and
  `cards_tunnel.agent_name()` (`editor` alone when the machine is empty).
- What: dash-release-jobs-6 removed the `name` fallback on the dashboard side
  and added the `machine` field on the companion side in one commit. The two
  halves ship separately: the dashboard goes out first by house rule ("deploy
  the dashboard before the companions"), and the field runs 0.9.65..0.9.71 plus
  a Mac on 0.9.70. Any of those tunnel `/cards/agent/state` with no `machine`,
  so the cards server is now told the agent's name is `leso`, not
  `leso/RAZER`.
- Failure scenario: leso's iMac (0.9.70) and MacBook (0.9.70) both have the
  cards role on. Both now register under the single name `leso`: the page's
  "which computer is driving Resolve" answer is wrong, two agents share one
  identity on the cards server's registry, and any state keyed by that name
  (the last-poll line, the release/reload handshake) is written by whichever
  polled last. Work dispatched to the name `leso/RAZER` that the pre-deploy
  agent registered is orphaned the moment the dashboard is swapped.
- Evidence: read both sides of the diff; `agent_name(editor, "")` returns
  `editor` (cards_tunnel.py:161-173), and the companion's `machine` key is added
  only for `suffix == "state"` in 18e69f3.
- Ledger: new (dash-release-jobs-6 is a one-sided fix for the deploy window).
- Suggested fix: keep the spoof-proofing but give an older companion a machine:
  fall back to the editor's most recently reporting machine for that fleet
  identity, or keep the body's `name` ONLY when no `machine` was declared and
  mark it unverified in the rendered string. Failing that, gate the change on
  the companion version the tunnel already knows.

### wire-5 - dash-api-6's new 403 has no answer in the companion's fleet-jobs error model: a suspended editor's machine keeps running the job and writing into the vault
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:9923-9934`
  (`_require_fleet_caller` -> `_refuse_barred_account`) against
  `companion/src/ccsync_companion/jobs_runner.py:732-767` (`_heartbeat`: only
  410 stops; everything else, including 403, returns "keep going") and
  `_post_result` (any non-200 is swallowed).
- What: the gate refuses the HTTP calls of a suspended editor's machine, but
  the only status the runner treats as "this job is not yours" is 410. A 403 is
  read as a blip, the child keeps running, the heartbeat cannot renew the lease
  the dashboard is refusing to touch, the lease expires, and the dashboard
  re-dispatches the same job to another machine while the first is still
  encoding into the shared vault. The docstring's claim - "still claim,
  heartbeat and finish fleet jobs into the shared vault ... one line per gate
  makes the word mean the same thing everywhere" - is true of the doors and not
  of the work already in flight.
- Failure scenario: an admin suspends a freelancer mid-afternoon. Their machine
  is 40 minutes into a `proxy-480p` job. It finishes it, writes
  `<name>.partial`, renames it into the archive, and fails to post the result;
  a second machine has meanwhile been given the same job and is writing the same
  output. Rule 2 (first writer wins) keeps that from corrupting the file, but
  the suspended machine did exactly the write the gate was added to prevent, and
  nothing ever tells it to stop or tells the admin it happened.
- Evidence: `_heartbeat`'s `if status == 410: return False`, everything else
  `return True`; `_post_result`'s bare `except Exception` around `_call` and no
  status check at all. No `403` appears anywhere in `jobs_runner.py`.
- Ledger: new (dash-api-6 does not close its own stated scenario for work in
  flight).
- Suggested fix: treat 401/403 on heartbeat as terminal for the current job the
  way 410 is (stop the child, record `cancelled`, do not retry) and surface the
  refusal on the tray the way `reporter`'s APP-1 credential notice does - the
  editor otherwise has a machine burning CPU on work nobody will accept.

## Coverage note
Checked and found consistent (so NOT reported): the rollback wire end to end
(`roll_fleet_back` -> v52 `update_requested_from` -> `_update_push_done` ->
`targeted_staged_package` -> the companion's `_apply_pushed_update` offer match
-> `_check_offer`'s floor); `_version_tuple`'s numeric-prefix change against
the companion's own `compare_to_running`; the ytdl lease's new `machine_id`
(body / query / header, optional on all three, both Nones in `lease_held_by`
and `heartbeat_download` mean what the docstrings say); `jobs_mod.fleet_caps`
into `claim_next_job`'s CAS; `_signature_url`; `_record_key` folding vs the
admin publish route; the music retry loopback (`{batch_uid, staging_id}` ->
202 from `run()`) and the b-roll take-over dispatch. NOT covered: the
`/cards/agent/{pending,result}` bodies against the other repo's engine (the
contract lives in `MulticamPipeline`, outside this tree); the b-roll
`/broll/ingest/run` with `staging_id: null` on a machine that DOES hold the
staging (it discards the local bytes association - possible re-fetch, not
traced); `provision`/`android` routes; the Syncthing admin wire. No suite was
run (owner rule: the gate runs once, centrally) - the two findings above with
CONFIRMED evidence were proved with snippets from the component venvs instead.

## OUT OF TERRITORY
- `companion/tests/test_bug_hunt_2026_09_11_comp_sync.py:438` and
  `companion/tests/test_bug_hunt_2026_09_11_comp_app.py:585`: both tests for
  this afternoon's file-move and repath fixes exercise a path or a payload
  shape the product never produces (see wire-1 and wire-2) - a `tests` lens
  item as much as a wire one.
- `companion/src/ccsync_companion/file_moves.py:249`: the resume arm calls
  `move_proxy_siblings(src, dest)` with `src` already gone, so it can only ever
  return 0 - the proxies a crash left behind are never moved even if the arm is
  made reachable.
