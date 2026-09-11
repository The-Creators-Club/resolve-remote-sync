## Dashboard database, boot and NAS backends, 2026-09-11 (CR-240)

Nine findings from the 2026-09-11 hunt (`hunters/dash-db.md`,
`hunters/dash-core.md`, verdicts in `verifiers/dashboard-a.md`). Seven of
them are a rule this repo already states applied to one more place; the
eighth is a cap that capped the work but not the rows, and the ninth is a
setting whose two readers disagreed about zero.

### CR-240a (dash-core-1) - the Synology backend still followed redirects, so a 307 replayed the DSM admin password - FIXED (`nas/synology.py`)

CR-111 put `allow_redirects=False` plus an explicit 3xx refusal on the OIDC
token POST and on `TrueNASClient._request`, and CLAUDE.md states the
invariant as "No dashboard call follows a redirect". The Synology backend
was missed: `SynologyClient._http` called `session.post` / `session.get`
with `requests`' default of True, and `_json` only rejects a non-2xx AFTER
the chain has already resolved. Every DSM credential this dashboard holds
rides in a POST BODY - `_ensure_session` posts `passwd=<DASH_NAS_PW>`,
`_request` puts `_sid` and `SynoToken` in the body, `set_known_password` a
freshly set editor password - and a 307/308 preserves method and body
verbatim. `requests` strips an `Authorization` header across a host change
but never a form body and never a custom header, which the verifier
measured: the login body arrived at the redirect target intact. Anything in
front of DSM can produce that 3xx: a reverse proxy, a captive portal, a
DSM forced to redirect :5000, a hijacked `DASH_NAS_HOST`. `_http` now
passes `allow_redirects=False` and raises a `NasError` naming the status
and the `Location` and saying that nothing was sent on, copied from
`nas/truenas.py`. The refusal is in `_http` and not in `_json` because
`_json` only ever sees the resolved response.

### CR-240b (dash-core-2) - `syncthing_client` handed the fleet's API key to a redirect target - FIXED (`syncthing_client.py`)

The same miss one tier down. `_request` sent `X-API-Key` and left
`allow_redirects` at its default; the `if resp.status_code >= 300: raise`
line reads like a redirect refusal but ran after the chain had been
followed, so it never saw a 3xx that resolved. A custom header is not one
of the three `requests` strips on a cross-host redirect, so a
`SYNCTHING_GUI_URL` pointing at anything that 302s (a proxy in front of
Syncthing, an http to https upgrade) handed the key over. Now
`allow_redirects=False` with a `SyncthingError` naming the `Location`.

### CR-240c (dash-core-3) - the Secrets wizard task rewrote `internal.env` without `APP_UID`/`APP_GID` - FIXED (`secrets_boot.py`)

`setup_engine._run_secrets` deliberately passes a snapshot of the five
`SECRET_ENV_VARS` only, so pressing [ DO IT ] on Secrets does not mutate the
running process's environment. `ensure_secrets` ends with an unconditional
`_write_sidecar_env_files(env, ...)`, which reads `env["APP_UID"]` and
`env["APP_GID"]` - neither of which is a secret and neither of which was in
that snapshot - so the first press rewrote `<data>/secrets/internal.env`
with the token line alone and silently dropped the ownership pair boot had
written. Nothing fails at that moment; the next `docker compose up -d sftp`
starts the sidecar with no uid/gid, which is the ownership mismatch the
pair exists to prevent (dash-admin-2). In practice
`compose.appliance.yaml` sets both in the service's own `environment:` key
as well, which takes precedence over `env_file:`, so this was belt losing
its brace rather than a live break - which is what downgraded it.
`_write_sidecar_env_files` now falls back to `os.environ` for the two
non-secret keys, so no future caller can drop them by choosing a narrow
mapping.

### CR-240d (dash-core-4) - `Origin: null` was read as "no Origin" by the /cards/ CSRF gate - FIXED (`app.py`)

Timeline Cards' ~70 POST routes are exempt from the CSRF token (they are
another repo's `BaseHTTPRequestHandler` routes, carried byte for byte) and
are held instead by an origin-only check, explicitly because they drive a
Resolve timeline. `_origin_mismatch` folded `Origin: null` into the same
branch as an absent Origin and, with no `Referer`, answered "not a
mismatch". `null` is an OPAQUE origin: it is what a browser sends precisely
when the request comes from somewhere that is definitively not this site (a
sandboxed iframe, a `data:`/`blob:` document, some cross-origin redirect
chains), so the check inverted its meaning for the one value that is
unambiguous. Nothing got through today - the session cookie is
`SameSite=Lax`, so those shapes arrive with no session and `login_gate`
401s them - but the defence-in-depth layer was not doing what its comment
claims. An ABSENT Origin still passes (the documented carve-out for
same-origin form posts); a literal `null` with no usable Referer is now a
refusal.

### CR-240e (dash-core-5) - `DASH_SITE_TEMPLATE_FOLDERS` was the one path-list door with no `..` filter - FIXED (`provision.py`)

The CR-111 pass hardened both path-list keys in `site_store`'s CSV
validator and additionally made `provision.shared_asset_folders_for` drop
`..` itself, with the stated reason that the environment is the door no
validator sees. The identical env door for template folders was left
stripping leading separators only. `site_store._shape` falls back to
`provision.TEMPLATE_FOLDERS` verbatim on every deployment that has not
saved on the Settings page, and `api.create_tree_project` does
`(target / sub).mkdir(parents=True, exist_ok=True)` for each entry, so a
site.toml rendered with `../../Assets` made every project creation mkdir
outside the project. `_site_list` now drops `..` segments, so both env
doors are covered by one rule.

### CR-240f (dash-core-6) - a build with no EULA left the wizard permanently un-finishable - FIXED (`setup_engine.py`, `setup_routes.py`)

REL-5 rightly changed the no-EULA state from `ok` to `warn`: a build that
ships without a licence agreement should be visibly wrong rather than
quietly complete. But `eula` is registered required, so it cannot be
skipped (`run_skip` raises, the route 400s), `_accept_eula` returns the same
`warn`, and `outstanding_required` therefore held it for ever - a permanent
amber row, a Setup badge that never clears, and no button anywhere that
changes it. The state is a property of the BUILD (an image from before the
`COPY docs /app/docs`, a bind-mount of `dashboard/src` alone, a
hand-assembled code root), not something an admin can act on. Two fixes:
`WARN_SATISFIES_IDS` (today just `eula`) makes a warn on that one task
satisfy `outstanding_required` and `outstanding_for_done` without changing
what the row says, and `eula_path()` re-resolves the file per call so an OTA
bundle that adds it heals without a process restart - `EULA_PATH` was read
once at import. A path something set deliberately (a test's monkeypatch,
`DASH_EULA_DOC`) is still returned as it stands.

### CR-240g (dash-core-7) - `DASH_SESSION_ABSOLUTE_SECONDS=0` bricked sign-in with no message - FIXED (`settings.py`)

The two consumers disagreed about what `0` means. `auth.start_session` does
`int(... or SESSION_TTL_SECONDS)`, so `0.0` is falsy and the COOKIE got the
seven-day module default; `SessionStore` stored `0.0` literally, so
`validate` computed `age > 0` on the very next request, deleted the row and
answered None - which `_resolve_session` reads as a revocation. An operator
who set it to 0 meaning "no limit" (a common convention) got: /login
succeeds, the next page is /login, nothing logged, `check_boot_secrets`
silent. `Settings.__post_init__` now falls back to the shipped default for
a non-positive idle or absolute lifetime and says so at ERROR, naming the
variable. There is no unlimited posture; a long value is the answer.

### CR-240h (dash-db-1) - a WIRED machine's OWN tick still came out of `fetch_machine_selections` - FIXED (`db.py`)

CR-110 dropped the unassigned bucket for wired machines and made
`selections_for_machine` answer `[]` for one, but it filtered `base_machines`
on the bucket-inheritance branch only. A machine that had `selections` rows
of its OWN and later flipped to wired in the tray (CR-88 made that the
computer's own one click) still read as holding a full tick: the companion
correctly syncs nothing, the enforce cycle correctly makes no share (CR-110's
belt at `collector.py`), and then `notices._check_plan_without_share` writes a
severity `error` notice on the home page - "has ticked ff5 to sync, but this
server is not sending that project to it" - plus a BROKEN invariant row,
about a correct configuration. `fetch_machine_selections` now takes
`for_enforce=True`, which drops a wired machine's own rows as well. It is a
parameter and not the new default because `assignments.py` builds the admin
tick grid from the same map: filtering there would make the stale tick an
invisible cell, present in the table with no button left to clear it, which
is the only way out of the notice today. The two readers that need the new
view are in another builder's files this pass and are recorded as owed.

### CR-240i (dash-db-2) - a transient `database is locked` read as "nobody is suspended, nothing is archived" - FIXED (`db.py`)

`suspended_editors`, `editor_suspension`, `archived_project_slugs`,
`fetch_archived_projects` and `fetch_pending_ssh_keys` swallowed EVERY
`sqlite3.OperationalError` and answered the empty value. Their docstrings
justify it as tolerating a pre-v50 database, but `migrate()` runs at boot on
every entry point that then reads them, so the missing-column case is
unreachable in a running dashboard. What the bare except actually caught is
`database is locked` and `disk I/O error` - and for suspension that is a
fail-OPEN of an admin control: the enforce cycle filters its plan with those
two sets, so one exceeded busy timeout (a long report write, a restore
drill) makes that pass re-share every folder the admin just suspended or
archived, silently, and the next cycle takes it away again. A new
`_schema_predates()` narrows the tolerance to "no such table" / "no such
column"; everything else, a lock included, is raised so the caller that
wants fail-open owns that decision explicitly the way `api.py` already
does.

### CR-240j (dash-db-3) - `MAX_INCLUDES` bounded the work but not the rows - FIXED (`links.py`)

The cap is documented as "a tampered marker must not be able to make either
unbounded", but `resolve_marker_includes` appended an `invalid` LinkResult
for every entry past 32 and carried on. A marker with 10,000 includes
therefore produced 10,000 rows in `project_links` - keyed
`(borrower_slug, declared_path)`, with the declared path chosen by whoever
wrote the marker, which is a plain JSON file on a share every editor can
write - rewritten by every provision cycle and rendered in full on the
shared-folders admin page. The loop now appends one refusal row saying how
many were ignored, logs it, and breaks.

### CR-240k (comp-app-2, owed by the dash-api-jobs builder) - the nine wave-3 `resolve_health` fields were declared and stored nowhere - FIXED (`db.py`)

`app.resolve_health()` has put `connected`, `project_open`, `wedged_seconds`,
`wedged_call`, `missing_clips`, `non_canonical_refused`, `proxy_attach`,
`proxy_gaps` and `stills` on the wire since 2026-09-04, and
`ResolveHealthIn` now declares all nine - but `db.store_resolve_health`'s
fixed column list carries only the v38 counters, so "Resolve is wedged on
GetMediaPool for 40 seconds" arrived on every report and was dropped.
`store_resolve_health` now calls `store_resolve_health_detail`, which keeps
the nine as one JSON blob in `meta` under `resolve_health:<editor>/<machine>`
and is read back by `db.resolve_health_detail`. `meta` and not nine more
columns, for the reason `api._store_ytdlp_state` gives about itself: an
opaque per-machine verdict with no SQL reader, and a schema number is a
shared resource - so no migration was needed and v52 stays with the
dash-api-jobs builder. The LATCH rule applies as everywhere else in this
group: written from any guard-bearing report, and a section that says
nothing deletes the row. An EMPTY list is kept ("the pass ran and refused
nothing" is an answer); only an absent field is silence.

### CR-240l (comp-resolve-3, owed by the dash-api-jobs builder) - the cards gate detail was truncated below what the model accepts - FIXED (`db.py`)

`store_machine_capabilities` cut `cap_cards_detail` to 255 while
`CardsAgentIn.detail` now accepts 1000. That detail is the sentence naming
the other program holding the Resolve client and its path ("one machine, one
Resolve client"), which is longer than 255 on a real Windows path, so the
one line that says WHY the role refused to start arrived complete and was
stored cut off. Raised to 1000 to match.

### CR-240m (dash-collector-alerts-3, owed by the dash-collector-alerts builder) - a dead collector read as fresh on the home page and /api/v1/health - FIXED (`db.py`)

`db.fetch_collector_status` computed `collector_stale` only inside
`if reachable and finished_at`, and `reachable` is the `ok` of the newest
non-Syncthing-free run. So a collector whose last act was a FAILED cycle,
and a Syncthing-less deployment which never runs such a kind at all, could
never be stale: the flag stopped being computed in exactly the two states
worth computing it in. It is now taken from the last cycle START of ANY kind
(`MAX(started_at)`), which is `alerts._collector_started_recently`'s rule and
the right question - anything starting proves the thread is turning,
whatever the cycle then made of itself. No rows at all stays not-stale: a
fresh container is "cannot tell", never "stopped". `syncthing_reachable`'s
own finished-recently test is unchanged; the two ask different questions of
the same rows.

### CR-240n (dash-collector-alerts-6, owed by the dash-collector-alerts builder) - `notices` had no retention, and a 500 was recorded under its concrete path - FIXED (`db.py`, `app.py`)

Two halves of one finding. `db.prune` had no statement for `notices` at all:
bounded in practice by the `(kind, subject)` upsert, but a cleared row about
a computer nobody owns any more lived for ever. It is now aged out on
`NOTICE_MAX_AGE_DAYS` (120, `alert_log`'s window and for the same reason),
CLEARED ROWS ONLY - an open notice is a problem the server has found and no
cleanup pass may take one off the home page because it is old. And app.py's
500 handler now passes `route=` from the matched route's path template when
`request.scope["route"]` has a `.path`, so a failing route is ONE row
(`/api/v1/jobs/{id}/why`) rather than one per id, and a
`/broll/share/<token>/` path is not written into a table a page renders. A
Mount has no usable `.path` and an unmatched request has no route at all;
both fall back to `""`, which is `notices.redact_path`'s existing first-two-
segments behaviour rather than something new.

### Verification
- `dashboard/tests/test_bug_hunt_2026_09_11_dash_db_core.py::test_the_synology_client_refuses_a_redirect_instead_of_replaying_the_password` -> fails at 40f931a (the password arrives at the sink), passes now
- `...::test_the_syncthing_client_refuses_a_redirect_instead_of_handing_over_the_api_key` -> fails at 40f931a, passes now
- `...::test_a_narrow_env_mapping_cannot_drop_app_uid_from_internal_env` -> fails at 40f931a, passes now
- `...::test_origin_null_is_refused_on_the_cards_prefix` (with `...::test_an_absent_origin_still_passes_the_cards_gate` as the control) -> fails at 40f931a, passes now
- `...::test_the_template_folders_env_door_drops_dotdot` -> fails at 40f931a, passes now
- `...::test_a_build_with_no_eula_does_not_wall_the_wizard`, `...::test_eula_path_is_re_resolved_when_the_import_time_answer_is_missing`, `...::test_a_deliberately_set_eula_path_is_left_alone` -> fail at 40f931a, pass now
- `...::test_a_zero_session_lifetime_falls_back_instead_of_bricking_sign_in`, `...::test_a_negative_session_lifetime_is_treated_the_same` -> fail at 40f931a, pass now
- `...::test_a_wired_machines_own_tick_is_not_in_the_enforce_view` (with `...::test_the_admin_grid_still_sees_that_stale_tick` as the control) -> fails at 40f931a, passes now
- `...::test_a_locked_database_raises_instead_of_answering_empty` (five parametrisations, against a REAL rollback-journal lock; `...::test_a_pre_v50_database_is_still_tolerated` is the compat control) -> fails at 40f931a, passes now
- `...::test_a_marker_with_thousands_of_includes_yields_a_bounded_number_of_rows` -> fails at 40f931a, passes now
- `...::test_the_wave_three_resolve_fields_are_stored`, `...::test_a_companion_that_stops_sending_the_detail_clears_it` -> fail at 40f931a, pass now
- `...::test_the_cards_gate_detail_is_not_truncated_below_what_the_model_accepts` -> fails at 40f931a, passes now
- `...::test_a_collector_whose_cycles_fail_is_still_reported_stale_when_it_stops` (controls: `...::test_a_collector_that_started_a_cycle_just_now_is_not_stale`, `...::test_a_fresh_container_with_no_runs_is_not_stale`) -> fails at 40f931a, passes now
- `...::test_prune_ages_out_cleared_notices_but_never_an_open_one` (control: `...::test_prune_keeps_a_recently_cleared_notice`) -> fails at 40f931a, passes now
- `...::test_a_500_is_recorded_under_the_route_template_not_the_concrete_path` -> fails at 40f931a, passes now
- Two existing tests pinned the fixed behaviour and were updated with the reason:
  `dashboard/tests/test_links.py::test_marker_caps_includes` (one refusal row, not one per entry) and
  `dashboard/tests/test_setup_engine.py::test_eula_warns_when_no_eula_shipped` (the warn no longer holds `done`).
- Also run green after the change: `tests/test_links.py`, `tests/test_setup_engine.py`,
  `tests/test_synology_client.py`, `tests/test_secrets_boot.py`, `tests/test_setup_routes.py`,
  `tests/test_sessions.py`, and for the five items added mid-pass `tests/test_db.py`,
  `tests/test_notices.py`, `tests/test_notices_sweep_wave2.py`, `tests/test_health.py`,
  `tests/test_health_page.py`, `tests/test_collector.py`, `tests/test_jobs_machines.py`
  (442 passed in total).
- Central gate fallout, fixed here (2026-09-11): six suites' fakes did not accept the new
  keyword - `tests/test_perf_tuning.py`'s `FakeSession.request` and
  `tests/test_cross_seams_2026_08_21.py::test_the_client_takes_a_per_call_timeout`'s stub now
  take `**kwargs` and ASSERT `allow_redirects is False` (a fake that merely tolerates a wire
  change is how the next one goes unnoticed), and
  `tests/test_api.py::test_a_dead_collector_shows_up_in_ok_while_the_status_stays_200` now
  clears `poll_runs` before seeding its old run: its scenario is a collector that has not
  STARTED a cycle in a long time, and under dash-collector-alerts-3 a ledger still holding a
  start from a second ago is a collector that is turning. The test's seeding was the wrong
  side, not the new rule. All four files green (39 + 16 + 31).

### OWED TO ANOTHER TERRITORY
- `dashboard/src/ccsync_dashboard/api.py` (`flatten_sync_guard`, ~:7623): CR-240k needs ONE key
  added beside the v38 `resolve_*` entries -
  `"resolve_health_detail": (None if rh is None else rh.model_dump(exclude_none=False))`,
  the same shape the `ytdlp` and `youtube_import` keys already use. The db side is in and
  harmless without it (an absent key stores nothing and deletes nothing that was never
  written), but until that line lands the nine fields are still dropped.
- `dashboard/src/ccsync_dashboard/notices.py` (`_check_plan_without_share`, :532) and
  `dashboard/src/ccsync_dashboard/invariants.py` (`_check_plan_has_share`, :270): both must
  call `db.fetch_machine_selections(conn, sync_modes=(db.SYNC_MODE_FULL,), for_enforce=True)`
  - the new parameter added by CR-240h. Until they do, a wired machine that still carries its
  own `selections` rows keeps raising the uncleanable `plan_without_share` error notice and the
  BROKEN invariant row. Nothing breaks without it (the default is unchanged), and the admin can
  still escape by unticking that project for that computer.
  `invariants.py:565` and `api.py:2713` (the file-move fan-out) read the same map and are worth
  a look under the same change: a wired machine cannot be holding a copy to move.
- No schema change was needed (dash-db-1 was fixed as a read-side view, not by deleting rows
  when a machine reports `mode='base'`).

### Owner decisions
- CR-240k: stored in `meta` as one JSON blob rather than nine machine_state columns (the
  `_store_ytdlp_state` precedent). If something later wants to ask "which machines are wedged"
  in SQL, promote it to columns then; a column per field is several migrations of guessing
  which fields matter.
- CR-240n: cleared notices are aged at 120 days, matching `alert_log`. Open notices are never
  pruned at any age.
- CR-240f: a warn on `eula` now satisfies the wizard's gates rather than blocking them. The
  alternative was to make the task optional (skippable, which records an explicit accept). The
  amber line and its wording are unchanged either way; what changed is only that it no longer
  walls a build the admin cannot fix.
- CR-240g: a non-positive session lifetime falls back to the shipped default and logs an ERROR.
  The alternative was to refuse to boot. A dashboard that will not start is worse than one that
  signs people in for the default seven days and says so, given "the dashboard is what tells
  everyone whether their footage is syncing" - but a boot refusal is the stricter reading of
  the secrets-at-boot precedent, and is a one-line change if the owner prefers it.
- CR-240i: the five helpers now RAISE on a lock rather than retrying. Every one of them is
  called inside a request or a collector cycle that already handles an exception by showing a
  banner or skipping a pass, and a retry loop here would hide contention the busy timeout is
  supposed to surface. If the field shows this firing, a bounded retry in `connect()`'s busy
  timeout is the place for it, not in each reader.
