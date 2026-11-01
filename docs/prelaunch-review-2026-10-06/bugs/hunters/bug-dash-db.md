# Pre-launch bug hunt: bug-dash-db (dashboard db.py, schema.sql, invariants.py)

Reviewed on 2026-10-06 against HEAD 08b40eb plus the uncommitted working tree.

**What I covered:**
- The migration machinery: `migrate`, `_split_statements`, `_already_applied` and the step list v1 to v59.
- I probed migrations on a fresh database and on databases cut at v1, v10, v22, v23, v30, v40, v50 and v58, then upgraded each one with data in it. Every upgraded schema came out identical to the fresh one. Replaying every step one version back also passed.
- Connection and transaction setup: `connect`, `bulk_insert`, the legacy isolation mode, BEGIN IMMEDIATE in the report path, and the collector's commit discipline.
- The selection model: `add_selection`, `add_selection_for_person`, `remove_selection`, `materialise_bucket`, `copy_machine_plan`, `adopt_renamed_machine`, `selections_for_machine`, `fetch_*_selections`, `plan_*_map` and `fetch_sync_backlog`.
- The machine registry, its eviction and forget paths, and the device id release.
- Jobs: claim, fail, expire and the cancel CAS.
- Notices and invariant results, `prune`, the report opt-outs, subject export and pseudonymisation, and the account-page settings asks.
- In `invariants.py`, checks 1 to 7 and 9.

**Already fixed, not re-reported:** bug-dash-db-1, -2 and -3 from the 2026-09-24 hunt, and logic-plans-1.

**Not covered:** the full body of `upsert_machine_state` (I read only its COALESCE and mode rules), the cards and ytdl tables, the triage tables, and the session store's own DDL.

### bug-dash-db-1 - The unassigned bucket never empties, so every new computer a person registers starts syncing it
- **Severity:** medium
- **Confidence:** CONFIRMED (probed with the real db functions)
- **Where:**
  - `dashboard/src/ccsync_dashboard/db.py:7147-7176` (`add_selection_for_person` writes `machine=''` when the person has no computer yet)
  - `db.py:7715-7739` (`selections_for_machine` falls back to the bucket)
  - `db.py:7831-7921` (`fetch_machine_selections` fans the bucket out to every machine with no own rows)
  - `db.py:7061-7108` (`materialise_bucket` copies the bucket and never removes it)
  - `collector.py:1376-1382` (the seed also writes the bucket)
- **What:** Ticking for a person who has no registered computer writes the `''` bucket. This is the normal onboarding order for a new customer: create the user, tick their projects, then install the companion. Nothing ever empties that bucket:
  - the first report does not adopt it, although the collector comment says "the first report from that machine adopts" it;
  - a later per-machine tick only COPIES it onto that machine (`materialise_bucket`).

  The bucket therefore stays for good and applies to every computer that person registers later. MULTI_MACHINE_PLAN.md §3.2 says a new machine must start EMPTY, because inheritance "silently starts a 50 GB download on a laptop that was never given a plan". Its implementation notes say "a migrated fleet has none". Both are untrue for any person ticked before their first report.
- **Scenario:** The admin onboards eve and ticks projects a and b before her desktop has reported. The desktop reports, and later the admin ticks c for DESK only. Months later eve installs CC Sync on a new LAPTOP. Probe results:
  - `selections_for_machine(eve, LAPTOP)` returns `['a', 'b']`;
  - `fetch_machine_selections(full, for_enforce=True)` maps a and b to `(eve, LAPTOP)`.

  The enforce cycle therefore shares both Syncthing folders with the laptop, and lane B starts downloading every proxy. Nobody ticked anything for that laptop, and nothing on the page says the plan was inherited.
- **Recommendation:** When a person's first computer registers, move the bucket rows onto it in `_register_machine`, in the same transaction, so a migrated or onboarded person ends with no bucket rows. Alternatively, never apply the bucket to a computer whose `machines.first_seen` is later than the newest bucket row. Either way, keep `selections_for_machine` and `fetch_machine_selections` agreeing with each other. Add a test: tick before any report, register DESK, register LAPTOP, and expect LAPTOP's plan to be empty.
- **Known:** No. logic-plans-1 (fixed) is a different bucket defect.

### bug-dash-db-2 - Archiving a project or suspending an editor raises false severity-error alerts that every tick is "not shared"
- **Severity:** medium
- **Confidence:** CONFIRMED (probed `notices._check_plan_without_share` and `invariants._check_plan_has_share`)
- **Where:**
  - `dashboard/src/ccsync_dashboard/notices.py:557-608`
  - `dashboard/src/ccsync_dashboard/invariants.py:286-330`
  - compare with `collector.py:1474-1520`, which drops `suspended` editors and `archived` slugs from the desired shares
- **What:** Archive (DCORE-5) and suspend (DCORE-4) work by having the enforce cycle REMOVE the Syncthing shares. They deliberately leave the `selections` rows in place so that unarchive or resume restores them. The two readers that compare plan against shares filter neither archived projects nor suspended editors:
  - `_check_plan_without_share` (an error-severity notice, which also reaches the `notice_error` alert);
  - invariant 1 (`invariant_broken`, also error severity).

  The next pass after the share is removed therefore files an error for every (computer, project) pair the admin just deliberately stopped.
- **Scenario:** The admin archives a finished project that 4 editors on 2 computers each had ticked. One enforce cycle later there are 8 open "has ticked X to sync, but this server is not sending that project to it" error notices. Invariant 1 is BROKEN, and two error alert mails go out, repeating per the alert dedup until the project is unarchived. The fix text says "Untick and re-tick that project", which is not the fix. Suspending an editor produces the same result for every tick they hold. My probe after `archive_project` returned a `plan_without_share` error row and an `Outcome(state='broken')`, and the same after `suspend_editor`.
- **Recommendation:** Apply the enforce cycle's own two filters (`db.archived_project_slugs`, `db.suspended_editors`) in both readers. Better, do it once in `fetch_machine_selections(for_enforce=True)`, so that "what should this machine hold" has one definition (the dash-db-4 lesson). Add tests for archive and suspend against both readers.
- **Known:** No.

### bug-dash-db-3 - After a computer is renamed, its old name stays on the fleet grid for 30 days, raises daily "gone quiet" error alerts, and FORGET answers 404
- **Severity:** medium
- **Confidence:** CONFIRMED (probed `adopt_renamed_machine` + `forget_machine`)
- **Where:**
  - `dashboard/src/ccsync_dashboard/db.py:6944-7058` (`adopt_renamed_machine` deletes only the `machines` row of the old name)
  - `api.py:1058-1105` (`build_editors_view` builds the grid from `lane_report_current` and `machine_state`, not the registry)
  - `alerts.py:1580-1605` (`_check_silent`)
  - `api.py:5391-5409` and `db.py:8886-8900` (forget refuses a name the registry does not hold)
- **What:** The adoption moves the plan, the sticky root and the pending commands. It then DELETEs the old registry row and leaves that name's `machine_state`, `lane_report_current`, `active_transfers` and `editor_media*` rows. Its docstring says these "age out through evict_extra_machines", but eviction only runs past 20 machines per person. In practice they last until `prune` removes them at 30 days. The fleet grid draws a machine for every `machine_state` and `lane_report_current` key, so the old hostname stays on the grid, frozen. Once it is 24 h old, `machine_silent` (error severity) mails "OLDNAME has not been in touch". It repeats daily until the 14-day give-up and then becomes the standing notice. The alert's fix says to press "Forget", but `forget_machine_everywhere` looks the name up in `machines`, finds nothing and answers 404 "no computer 'OLD' for 'eve'". The admin has no way to clear it.
- **Scenario:** An editor renames their PC, which is routine on a new Windows install or a Mac Bonjour '-2' rename. SYS-18a confirms the rename and adopts. Probe: registry `['NEW']`; `machine_state` has rows for both OLD and NEW; `forget_machine(eve, OLD)` returns None. For the next month the owner gets an error mail about a computer that does not exist and cannot be removed.
- **Recommendation:** In `adopt_renamed_machine`, also delete (or re-key, where NEW has no row yet) the old name's rows in `machine_state`, `lane_report_current`, `active_transfers`, `editor_media_project`, `editor_media`, `media_tree_clips`, `report_auth` and `broll_standins`. The other per-machine tables in `_MACHINE_STATE_TABLES` are already handled. Separately, let FORGET fall back to sweeping those tables by (editor, machine) when no registry row exists, so a ghost can always be cleared.
- **Known:** No.

### bug-dash-db-4 - One Syncthing device id reported by two different people flips between their plans on every report, and the invariant that should catch it reads OK
- **Severity:** medium
- **Confidence:** CONFIRMED (probed `release_device_id_elsewhere` + invariant 3)
- **Where:**
  - `dashboard/src/ccsync_dashboard/db.py:5201-5238` (`release_device_id_elsewhere` takes the id off EVERY other row, across editors)
  - `api.py:7876-7892` (called on every report with the companion's self-reported id, with no check that the device belongs to that person)
  - `invariants.py:375-433` (the device half of invariant 3 groups by `machines.syncthing_device_id`)
  - `collector.py:1490-1495` (`machine_devices` built from that column)
- **What:** The release was written for one editor's refused rename. It is not scoped to the reporting editor, so a device id moves to whichever PERSON reported it last. Two cases:
  - **Imaged machines.** A studio that images editor PCs from a master that already contains Syncthing's key gives two people's computers the same device id. Each report then moves the id. The enforce cycle hands the device whichever person's plan holds the id at that moment, adding one plan and removing the other (the removals pass through the brake), so folders flap on Syncthing.
  - **A hostile insider.** Any editor with their own `cce1` token can report a colleague's device id. That steals the mapping, so the colleague's device receives the attacker's plan and loses its own until the colleague's next report.

  Because the release keeps the id on exactly one row at any instant, the device-collision half of invariant 3 ("one place on the sync network claimed twice") can never see the condition. The only trace is a container log warning.
- **Scenario:** Probe: alice reports device D (mapped to alice/A-PC), then bob reports D (now mapped to bob/B-PC only). Invariant 3 returns `ok: "1 sync device id(s), each on one computer"`. In production this repeats every 30 s per machine, and the enforce cycle rewrites the folder shares for that device every pass.
- **Recommendation:**
  - Scope the release to the reporting editor's own rows.
  - When the id is held by ANOTHER person's row, refuse to move it and raise an `identity_collision` notice naming both people.
  - Have invariant 3 (and `notices._check_identity_collisions`) record cross-editor contention: persist the last N claims, or a counter of moves per device.
  - Consider checking a reported device id against the Syncthing `devices` row mapped to that editor before accepting it.
- **Known:** No. data-model-5 introduced the release for the same-editor case.
