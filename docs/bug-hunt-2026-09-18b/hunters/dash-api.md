# dash-api - dashboard api.py, package_store.py, settings.py, local_users.py, provision.py, android.py, locate.py

Files read (with approximate coverage): `git diff` over the three changed files
in the territory in full (`api.py` +287, `locate.py` +71, `package_store.py`
+44); `locate.py` whole (100%); `package_store.py` `store_verified_package` and
the gates around it (60%); `api.py` the changed regions plus their callees and
call sites - `_upgrade_info` / `targeted_staged_package` /
`_machine_can_be_offered`, the report handler from `flatten_sync_guard` to the
`commands` block, `_package_filename` / the PUT publish route /
`build_packages_view` / `_trash_package_file` (about 25% of a 12k-line file,
chosen by the diff); `settings.py`, `local_users.py`, `provision.py`,
`android.py` skimmed (unchanged by the fix pass, no findings). Read as the
other ends of the wires: `db.py` (`pending_file_moves`,
`command_machine_names`, `mark_file_move_applied`, `mark_resolve_undo_applied`,
`record_standins_placed`, `standins_known`, `replace_nas_media`,
`record_inventory_error`, `adopt_renamed_machine`), `collector.py`
`_record_inventory`, `release_feed.py` `publish_from_feed` /
`auto_publish`, `ui.py`'s feed-publish partial, `jobs.py` `fleet_facts` /
`machine_facts` / `policy`, companion `app.py` `_note_dashboard_version` /
`_dashboard_knows_state_word`, `proxy_relink.note_fleet_standins` /
`fleet_says_standin`, and `dashboard/tests/test_bug_hunt_2026_09_18_dashboard_lows.py`.

Tests run:
- `dashboard\.venv\Scripts\python.exe -m pytest tests/test_locate.py tests/test_packages.py -q` -> 84 passed
- three ad-hoc snippets against `dashboard/.venv` in the scratchpad (outputs quoted below)

## Findings

### dash-api-1 - res-fleet-4 landed the OFFER under a former hostname and not the ANSWER
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:9474-9478` and `:9487-9493`
  (the answer loops), against `dashboard/src/ccsync_dashboard/api.py:9828-9850`
  (the new offer + `_by_target_machine` delivery stamp);
  `dashboard/src/ccsync_dashboard/db.py:5923` (`mark_file_move_applied`),
  `:6168` (`mark_resolve_undo_applied`), `:3041` (`_file_move_answer`)
- What: `pending_file_moves` / `pending_resolve_undos` now look the command up
  under every hostname of the same `machine_id` (`command_machine_names`), and
  the delivery stamp was correctly moved onto the row's own key
  (`_by_target_machine`). The three writers that record the machine's ANSWER
  were not: they all still match `WHERE ... AND machine = <reporting
  hostname>`, so for exactly the rows this fix newly offers - those filed under
  the FORMER name, before SYS-18a adopts the rename - the answer updates zero
  rows and is silently dropped, including the de-dupe read that decides whether
  to log it.
- Failure scenario: a computer with `machine_id` mid-1 is renamed OLD-PC ->
  NEW-PC while a file move is outstanding. The next report now offers the move
  (good), the companion moves the file and answers `ok/done`, and
  `mark_file_move_applied(..., "NEW-PC", ...)` returns False: `applied_at`
  stays NULL, nothing is logged, the command is re-sent every 30 s. It
  self-heals once `adopt_renamed_machine` re-keys the row, but where adoption
  is refused (SYS-18a refuses while both names look live, i.e. a rename the
  companion cannot prove) the row now carries a `delivered_at` it never had
  before, so `expire_delivered_file_moves` ages it into `expired_at` and raises
  a `file_move_expired` warn for a move that was actually applied. The Resolve
  undo path has the same shape with no self-healing on the answer either.
- Evidence: snippet against the dashboard venv on a migrated in-memory DB:
  `offered: [(1, 'OLD-PC')]` / `applied ok?: False` /
  `row after answer: {'machine': 'OLD-PC', 'applied_at': None, 'delivered_at': None}`
  / `undo offered: [{'id': 1, ... 'target_machine': 'OLD-PC'}]` /
  `undo applied ok?: False`. The new test
  `test_a_command_under_a_former_hostname_is_still_offered`
  (`tests/test_bug_hunt_2026_09_18_dashboard_lows.py:231`) asserts the offer
  and the `target_machine` key and never sends an answer back, which is why the
  gap is green.
- Ledger: CR-285 / res-fleet-4 does not fix the whole of res-fleet-4 (new)
- Suggested fix: give `mark_file_move_applied`, `mark_resolve_undo_applied` and
  `_file_move_answer` the same `machine_id` fallback (`machine IN
  command_machine_names(...)`), or have the report handler answer against
  `target_machine` the way `_by_target_machine` already stamps delivery.

### dash-api-2 - locate excludes a project for ever after one transient inventory error
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/locate.py:92-101` (the new
  `COALESCE(s.last_error,'') = ''` filter) and `:151-170` (`_unreadable_slugs`);
  the other end is `dashboard/src/ccsync_dashboard/collector.py:1750-1751` and
  `db.record_inventory_error` (`db.py:8897`)
- What: the filter assumes `last_error` is self-clearing. It is cleared only by
  a successful `replace_nas_media`, and `record_inventory_error` does NOT clear
  or invalidate `tree_sig`. The collector skips the whole walk when the
  directory signature is unchanged (`if sig == db.nas_inventory_sig(...):
  continue`), so a project that took one error and then went back to normal is
  never re-walked (nothing changed on the NAS - that is the normal state of an
  archived project) and its `last_error` stands for ever. The docstring's
  reasoning ("a project whose `tree_sig` has not changed is legitimately not
  re-walked") is the exact case that makes the flag permanent.
- Failure scenario: a NAS mount flap makes `proj_dir.is_dir()` false (or the
  dir momentarily has no `.stfolder` and no media) for one collector cycle.
  `nas_inventory_state.last_error` is written; the NAS comes back; the
  signature matches, so no walk ever runs again. From then on every locate
  answers `found: []` for every file in that project and returns its slug in
  `unreadable` on every call, so the CR-268 hand-move question degrades
  permanently and silently to its pre-feature behaviour for that project - the
  moved files read as deletions on every machine and lane B's breaker parks
  them, which is the failure this feature exists to prevent.
- Evidence: snippet (scratchpad), same DB before and after a single
  `record_inventory_error`:
  `locate before: ... 'unreadable': [], 'found': [{'project_slug': 'p1', 'rel_path': 'B-roll/A001.braw'}]`
  then `tree_sig after error: sig-1` and
  `locate after a transient error: ... 'unreadable': ['p1'], 'found': []`.
  `tree_sig` is unchanged, which is what makes `collector.py:1750` skip the
  re-walk that would clear it.
- Ledger: new (the dash-api-1 fix of the morning pass opens this)
- Suggested fix: make the error path invalidate the walk rather than only
  record it - `record_inventory_error` should null `tree_sig` (or the collector
  should re-walk whenever `last_error` is set even if the signature matches),
  so one good cycle clears the exclusion.

### dash-api-3 - res-fleet-2 withholds the command but leaves the machine out of the job fleet
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:9711-9733`
  (`_machine_can_be_offered` arm of the pushed-update block);
  `dashboard/src/ccsync_dashboard/jobs.py:621-631` (`fleet_facts.upgrading`),
  `:511` (`machine_facts`), `:805` (`policy`)
- What: the new arm stops sending `commands.upgrade` for a build this machine
  is not being offered, and deliberately LEAVES THE REQUEST STANDING. Its own
  comment names the larger harm it is fixing: "`jobs.machine_facts` turned 'has
  an update waiting' into a blanket refusal of every job kind, so that computer
  was out of the whisper/proxy/peaks fleet until
  `expire_machine_update_requests` dropped the row 14 days later." That half is
  untouched: `upgrading` is still computed from
  `machines.update_requested_version` being non-empty and nothing else, so the
  machine is refused every job for the full 14 days, exactly as before.
- Failure scenario: an admin pushes 0.9.75 to an Intel Mac and the record is
  arm64 (or the build is later retracted). The command is now correctly
  withheld and a reason rides the reply, but `update_requested_version` stays
  set, `policy()` answers `REFUSE_UPGRADING, "this computer has an update
  waiting to apply"` for every kind, and that machine takes no whisper, proxy,
  audio-extract or peaks job for two weeks - while the Packages page still
  shows the push as outstanding and nothing ever applies it.
- Evidence: `jobs.py:621-631` selects `upgrading` straight from `machines`;
  `policy` at `:805` returns `REFUSE_UPGRADING` before any capability is
  looked at; `grep -n "update_requested" dashboard/src/ccsync_dashboard/jobs.py`
  finds no other reader, so nothing consults whether the build is offerable.
- Ledger: CR-285 / res-fleet-2 does not fix the whole of res-fleet-2 (new)
- Suggested fix: either exclude an unofferable request from `upgrading` (ask
  the same `_machine_can_be_offered` predicate in `fleet_facts`/`machine_facts`,
  fail-closed to "upgrading" only when it can be answered), or surface the
  standing-but-unsendable request on the Packages page as needing the admin to
  withdraw it, so it cannot silently cost the fleet a machine.

### dash-api-4 - a publish killed between the commit and the rename leaves a CURRENT row with no bytes, and nothing raises it
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/package_store.py:525-538` (the
  `os.replace` moved after `conn.commit()`), and `:454-468` (the
  identical-bytes early return)
- What: dash-api-6 deliberately swapped the failure direction to "a row whose
  file is missing", reasoning that it is "a loud 404 on download". It is not
  loud on this server: nothing in `alerts.ALERT_KINDS` or `notices` checks that
  a published package's file exists - the only place it shows is
  `build_packages_view`'s `file_exists` field on a page nobody opens after a
  successful publish. The window is real for an unattended feed publish of a
  200 MB artefact (container restart, OOM, SIGKILL between the commit and the
  rename), and the row may already be CURRENT because the flip happens inside
  that same transaction. Secondly, the new early return answers a re-publish of
  identical bytes before `make_current` is considered, so in the overlapping-
  publish race it describes, a loser that asked for the flip returns "already
  published" and the flip is silently not applied (harmless today only because
  both HTTP doors 409 on `get_package` first).
- Failure scenario: the feed's daily poller publishes companion 0.9.75 with
  `policy = current`, the container is recreated a second after the commit; the
  fleet is offered 0.9.75, every companion's download 404s, every upgrade
  attempt fails, and the server says nothing until somebody looks at the
  Packages row.
- Evidence: `grep -rn "package" dashboard/src/ccsync_dashboard/alerts.py` finds
  only `retracted_packages`; no notice kind covers a package file. The ordering
  is in the diff itself (`commit()` then `dest_dir.mkdir` then `os.replace`).
- Ledger: related to CR-285 / dash-api-6 = live-2 (new)
- Suggested fix: do the `os.replace` after the insert but BEFORE the commit (a
  failed rename then rolls the row back, which is the old direction without the
  race the fix closed), or add an alert kind that checks `is_file()` for the
  current package of each kind/platform every collector cycle.

### dash-api-5 - `standins_known` never sends the empty list its own contract promises
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:9866-9876`
  (`if known: result["standins_known"] = ...`), against the comment three lines
  above it and `db.standins_known`'s docstring (`db.py:8869-8880`) and the
  companion's reader (`companion/src/ccsync_companion/proxy_relink.py:440-487`)
- What: the comment states "an empty list is sent for the same reason, so the
  two shapes cannot be confused", and the companion implements three states
  (`_FLEET_KNOWN` False = ask the probe; known + empty = the fleet has none).
  The code only sets the key when the list is non-empty, so the "known and
  empty" state is unreachable and absence carries both meanings.
- Failure scenario: a fleet with no stand-ins recorded yet (every fleet, on the
  day of the deploy) never gets the key, so `fleet_says_standin` returns None
  and the wired rig keeps running the header/packet probes for every archive
  clip - the cost proxy-tiers-4 exists to remove. Behaviour is safe, only the
  saving is lost, and the two sides' comments disagree with the code.
- Evidence: the `if known:` guard in the diff; `note_fleet_standins` sets
  `_FLEET_KNOWN = True` for any dict with a list `rels`, including an empty one.
- Ledger: related to CR-285 / proxy-tiers-4 (new)
- Suggested fix: send `result["standins_known"] = {"rels": known}`
  unconditionally when the read succeeded, and only omit it on the exception
  path (which is what "this dashboard does not know" actually is).

### dash-api-6 - locate's module docstring still documents the old `as_of`
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/locate.py:28-30`
- What: dash-api-3 changed `as_of` to the OLDEST walk that contributed to an
  answer (falling back to the tree-wide newest only when nothing matched), and
  documented that on `_as_of`; the module docstring, which is where the
  contract for the caller is written down, still says "`as_of` is the newest
  `refreshed_at` in the table". The companion logs this number beside a rename
  it makes, so the two readings differ by days on exactly the tree that
  motivated the change.
- Failure scenario: the next reader of this module (or the doc it is quoted
  into) reasons from "newest" and concludes the answer is fresher than it is.
- Evidence: both texts are in the same file after the diff.
- Ledger: new
- Suggested fix: one sentence in the module docstring pointing at `_as_of`.

## Coverage note
Not reached: `settings.py`, `local_users.py`, `provision.py` and `android.py`
beyond a skim (none is touched by the fix pass, and nothing new calls into
them); the admin/provisioning routes in `api.py` outside the diff; the
`/api/v1/jobs` routes (dash-release-jobs); the schema-migration question for
the new `broll_standins` table (dash-db). The suite does not cover: any answer
coming back from a machine whose command is filed under a former hostname
(dash-api-1 - the new test only checks the offer); a locate after an inventory
error that later clears (dash-api-2 - `tests/test_locate.py` has no
`last_error` lifecycle case, only the excluded/included pair); a publish
interrupted between `conn.commit()` and `os.replace` (dash-api-4); and the job
scheduler's view of a machine carrying an unofferable update request
(dash-api-3).

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/db.py:8830-8866`: `record_standins_placed`
  DELETEs the machine's rows and then re-INSERTs them, so the `ON CONFLICT ...
  DO UPDATE` arm is dead and `first_seen` is reset to `now` on every report -
  the docstring's promise that "`first_seen` survives a re-report of the same
  rel, because 'how long has this clip been standing in' is the question an
  operator asks" is not what the code does (dash-db).
