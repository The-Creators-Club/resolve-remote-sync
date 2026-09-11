## Dashboard surface, mounts and deploy machinery, 2026-09-11 (CR-243)

### CR-243a - /help served this studio's whole internal docs tree to any signed-in editor, and all three shipping routes put it on a customer's server to begin with - FIXED 2026-09-11 (`published_docs.py`, `help.py`, `Dockerfile`, `.dockerignore`, `build_dashboard_bundle.py`, `install_dashboard_app._stage_docs_tree`)

**Found** by the 2026-09-11 hunt (dash-mounts-ui-1 with server-tools-2, one
defect seen from both ends). A `jsmith` session cookie against
`create_app(admin_users={"owen"})`:

    _root/KNOWN_BUGS.md 200 1469667
    _root/CLAUDE.md     200   93580
    SECRETS.md          200   59674
    PRODUCT_REPO.md     200   72382
    index entries: 133

**Cause:** the 2026-09-04 widening of /help from one customer explainer to
"every markdown file the repository carries" was done in two halves and only
the first was about paths. All three shipping routes were widened to carry
the whole `docs/` tree plus the four top-level documents under `_root/` (the
image's `COPY docs` + `COPY *.md`, the OTA bundle's `TREES`, bind mode's
`_stage_docs_tree`), and `help.resolve_document` allow-listed the SHAPE of a
path - markdown, inside the root, no `..`, no symlink out - and never the
AUDIENCE. The route is behind the login gate, not the admin one, and the nav
entry is `admin_only=False` on purpose. So every editor on every customer's
fleet could read the defect ledger, CLAUDE.md, SECRETS.md, PRODUCT_REPO.md,
every plan and every bug-hunt report: documents that name this studio's
editors, their machines and its infrastructure addresses. That is CLAUDE.md's
"no customer's name in code" broken by the shipping change rather than by the
code, and `tests/test_help_page.py:383` pinned it as correct behaviour.

**Fixed:** what SHIPS and what may be READ now come from one list,
`dashboard/src/ccsync_dashboard/published_docs.py`: `HOW_IT_WORKS.md`,
`EDITOR_SETUP.md` and `docs/legal/`, with `REQUIRED_DOCS`/`REQUIRED_TREES`
marking the two a build is refused without (the guide and the licence
agreement). Four readers, no second copy: `help.resolve_document(rel,
is_admin=False)` and `document_groups`/`page_context` (the index never lists
what the route would refuse, because a list of titles is disclosure too);
`build_dashboard_bundle` (its `("docs","docs")` tree and its `ROOT_DOCS` are
gone, the rest of the list is best effort); `install_dashboard_app`, which
loads the module BY PATH because server/ deliberately does not import the
dashboard package, and ships the required set alone if it cannot read it; and
the Dockerfile plus `.dockerignore`, which cannot import anything and restate
the list in `COPY docs/HOW_IT_WORKS.md docs/EDITOR_SETUP.md /app/docs/` +
`COPY docs/legal /app/docs/legal` and three `!docs/...` re-includes, with
`test_bug_hunt_2026_09_11_dash_mounts_ui.py::test_the_three_shipping_routes_agree_with_the_one_list`
failing the moment they and the tuple disagree. Everything outside the list
is ADMIN ONLY and, on a customer's deployment, not present at all, which is
what keeps the owner's 2026-09-04 ask (read every document in this viewer)
working on the base rig. The audience flag defaults to False everywhere: an
audience gate that fails open is not a gate. **Deploy the dashboard to close
it on the images already out there** - the gate travels with the code, the
narrowed image only with the next build.

### CR-243b - "safe to close" was computed for the PERSON and worded for the computer - FIXED (`ui.safe_to_close`)

`build_transfers_view` is scoped by editor and never by machine, and every
branch of the sentence said "this computer" three times, on a dashboard whose
own invariant is that a plan belongs to a COMPUTER. An editor with a laptop
and a desktop (the shape MULTI_MACHINE_PLAN.md exists for) read "Not yet: 412
file(s) still uploading from this computer" on the laptop that owed nothing,
and left the wrong machine running overnight. The error was always the
conservative way round - the safe answer needs NO machine of theirs to owe an
upload - so this is a copy fix, not a resilience one. The rows already carry
`machine`, so the sentence names the computers the work is actually on
("Not yet: 4 file(s) still uploading from DESKTOP (900 B). Leave that
computer running."), and names none rather than inventing one when a report
did not carry a machine name.

### CR-243c - run.sh recorded `ok: true` for a PO-token plugin install it never performed - FIXED (`deploy/run.sh`)

The install was gated on a STAMP (`.requirements-unblock-hash`) that lives
apart from the ARTEFACT (`unblock-site/yt_dlp_plugins`), and where the stamp
matched and no marker existed run.sh wrote `ok: true, attempts: 0` having run
no pip and stat'd no package. `/ytdl/api/health` and the self-diagnosis read
that marker, so a wiped plugin under a surviving stamp read GREEN while every
server download crawled the throttled HLS ladder at ~1.8 MiB/s or landed
empty - CR-73/CR-75's symptom behind a healthy-looking route, which is the
shape SELF_DIAGNOSIS.md forbids ("an unverified check is NOT CHECKED, never
OK"). The artefact test is on the INSTALL condition, not just on the marker:
a missing `yt_dlp_plugins` reinstalls, and the backfill marker is written only
when the stamp matches AND the plugin is on disk. No third marker state was
needed - `_plugin_install_state` already reads a missing marker as `ok: None`
/ NOT CHECKED.

### CR-243d - CI gated a release on one of the installer's test scripts - FIXED (`.github/workflows/ci.yml`)

`ci.yml` ran `Test-DriveMapParser.ps1` and nothing else, while
`ls installer/tests/*.ps1` was seven files (eight as of this pass) - the
licence gate and the previous-install rollback among the six that never ran.
`tools/publish_latest.py` publishes "the newest GREEN CI run on main", the
pathway that reached the fleet for 0.9.61 and 0.9.70, so a green run was
evidence about one of seven covered behaviours. The step enumerates the glob
now, in run_all_tests.ps1's own words ("this comment has now been wrong
twice"), checks `$LASTEXITCODE` per script (a bare foreach in pwsh fails
nothing) and seeds it, because `$null -ne 0` reads as a failure on the first
iteration. All eight were run on this rig before wiring them in.

### CR-243e - a same-version redeploy left every installed phone on the old CSS and JS - FIXED (`static/sw.js`)

The whole cache-invalidation story was "a release changes VERSION, which
changes the worker's bytes, which drops the old cache". The `/static/` branch
was cache-first with no revalidation and the asset URLs carry no version
query, so a CSS or JS change shipped under an unchanged VERSION (a hotfix
redeploy, an OTA code bundle, `--allow-replace`) produced a byte-identical
`sw.js`, was never installed, and an installed phone kept the broken asset for
ever - with a hard reload no help, because the worker answers before the
network. The branch is stale-while-revalidate now: the cached copy is still
what paints (offline is when it matters most), and the background fetch
replaces it for the next load. Seeding the cache NAME from a per-deploy id
was the other suggestion and was not taken: it discards the precache on every
container restart, which costs exactly the phones the PWA exists for.

### CR-243f - the uid mismatch warning was dead in bind-mount mode - FIXED (`deploy/run.sh`)

`APP_UID`/`APP_GID` are in the container's environment in IMAGE mode only, so
the warning written for COMMERCIAL_READINESS item 12 (DSM assigns uids >=
1026) never fired on the bind-mount deployments it was written for. The uid
half falls back to the deploy's own evidence, `stat -c %u /data` - the deploy
chowns /data to APP_UID - so a container running as the wrong uid says so
instead of silently writing files editors cannot open over SMB. No gid
fallback: /data carries the app's PRIVATE gid, not `editors`, so comparing
them would warn on every healthy boot.

### CR-243g - a concurrent poll could steal the refusal banner's move - FIXED (`static/htmx_errors.js`)

DUI-6's "render the refusal beside the button that caused it" kept the
request path in ONE module-level slot, set on every write's `beforeRequest`
and consumed by the NEXT `afterSwap` whichever element that swap belonged to.
The fleet grid polls every 15 s, notices and transfers on their own timers:
any of them settling between the click and the write's own swap took the slot,
and the refusal stayed two thousand pixels above the viewport - the exact
symptom the code was written to fix, intermittently. The path is read off the
swap's own `requestConfig.elt`, with a WeakMap keyed on the xhr as the
fallback.

### CR-243h - select_code_root counted a boot against an OTA tree it never booted - FIXED (`deploy/select_code_root.py`)

`bump_boot_attempts` ran BEFORE `check_tree`, so a boot that refused the tree
and ran the IMAGE still counted against it - and `check_tree`'s
environment-shaped refusals (`DASH_RELEASE_PUBKEYS is not set`, `this image
has no /venv/.runtime-id`) are indistinguishable from tree-shaped ones to a
counter. Two restarts with the keys omitted from the deploy command (the
documented image-mode redeploy recipe notes they must be in the same command)
permanently rewrote `current.json` back to the previous tree with
`reverted_reason` "failed to reach a healthy boot 2 times", which is not what
happened. The bump is below the check now, so `boot_attempts`' own docstring
("a non-zero count here always means the last boot of this tree did not
work") is true again.

### CR-243i - the nine wave-3 `resolve_health` fields now RENDER (comp-app-2's dashboard half) - `ui._fleet_view`, `partials/fleet_grid.html`

Owed by dash-api-jobs and dash-db-core, who made them survive the report and
land in `meta`. The machine panel shows them beside the v38 counters they
belong with: one state line (connected / not connected / not checked, the
project open, "wedged 12 s in GetMediaPool" in red, the proxy attach pass, a
capped proxy queue, a low-space note, a failing stills check), and
`missing_clips` / `non_canonical_refused` behind a count in a `<details>`
with a `data-key`, because either list can be fifty clips and this is a cell
in a grid. `ui._fleet_view` is the one place the detail is read (one row per
machine, beside `build_editors_view`'s per-fleet maps) and it is attached at
all five fleet-grid render sites. A machine that has not sent them renders
NOTHING: "could not check" must never appear as a reassurance.

### Verification
- dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py::test_an_editor_cannot_read_the_internal_documents -> fails at 40f931a, passes now (dash-mounts-ui-1 / server-tools-2)
- dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py::test_the_route_refuses_an_editor_and_serves_an_admin -> fails at 40f931a, passes now
- dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py::test_the_index_lists_only_what_this_reader_may_open -> fails at 40f931a, passes now
- dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py::test_the_three_shipping_routes_agree_with_the_one_list -> fails at 40f931a, passes now
- tools/tests/test_build_dashboard_bundle.py::test_only_the_customer_facing_documents_travel -> fails at 40f931a, passes now
- server/tests/test_image_mode.py::test_bind_mode_ships_the_customer_facing_documents_only -> fails at 40f931a, passes now
- dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py::test_safe_to_close_names_the_machine_it_is_talking_about -> fails at 40f931a, passes now (dash-mounts-ui-2)
- dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py::test_a_wiped_plugin_is_reinstalled_rather_than_marked_ok -> fails at 40f931a, passes now (dash-mounts-ui-3)
- dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py::test_ci_runs_every_installer_script_by_enumerating_them -> fails at 40f931a, passes now (dash-mounts-ui-4)
- dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py::test_a_cached_static_asset_is_revalidated_in_the_background -> fails at 40f931a, passes now (dash-mounts-ui-5)
- dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py::test_the_uid_warning_works_without_app_uid_in_the_environment -> fails at 40f931a, passes now (dash-mounts-ui-6)
- dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py::test_a_poll_settling_first_does_not_steal_the_refusal -> fails at 40f931a, passes now (dash-mounts-ui-7)
- dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py::test_a_refused_tree_is_not_counted_as_a_failed_boot -> fails at 40f931a, passes now (dash-mounts-ui-8)
- dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py::test_the_machine_panel_shows_what_resolve_last_said -> fails at 40f931a, passes now (comp-app-2, the rendering half)
- dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py::test_a_machine_that_has_not_sent_them_renders_nothing -> fails at 40f931a, passes now (comp-app-2)

Also updated because they pinned the old behaviour:
`dashboard/tests/test_help_page.py` (six tests now ask as an admin, including
the `/help/GOTCHAS.md` route test the verdict named at line 383),
`dashboard/tests/test_templates_wave3_2026_09_04.py` (the safe-to-close
sentence), `tools/tests/test_build_dashboard_bundle.py` and
`server/tests/test_image_mode.py` (what the two shippers carry).

### OWED TO ANOTHER TERRITORY
- `dashboard/deploy/compose.yaml` + `server/install_dashboard_app.compose_config()`
  (server-tools): the hunter's own fix for dash-mounts-ui-6 was to add
  `APP_UID`/`APP_GID` to the bind-mode template's `environment:` block. That
  needs the same two keys in `compose_config()`'s dict or
  `server/tests/test_safety.py::test_env_keys_match_compose` and
  `test_compose_template.py::test_image_mode_takes_the_same_environment_as_the_default_mode`
  fail, and `compose_config` is not mine this pass. My side is safe without
  it: run.sh derives the expected uid from /data's owner when the variable is
  absent. If the keys are added later, the env branch simply wins again.
- `tools/tests/test_docs_index.py::test_every_doc_is_listed` fails on the
  current working tree because `docs/STAGE_A_FOLDER.md` is untracked and has
  no row in `docs/README.md` (the hunt noted this; it predates this pass and
  is nothing to do with these fixes).

### Owner decisions
- WHICH documents are customer-facing is now one tuple, and I chose the
  narrow reading: `HOW_IT_WORKS.md`, `EDITOR_SETUP.md` and `docs/legal/`.
  `INSTALL.md`, `APPLIANCE_INSTALL.md`, `CLIENT_DELIVERY.md`, `MOBILE.md` and
  `SYNOLOGY_EASY_INSTALL.md` are the plausible next candidates (all except
  MOBILE.md are already clean of this studio's names and addresses); adding
  one is a line in `published_docs.PUBLISHED_DOCS` plus the matching
  Dockerfile/.dockerignore line the drift test insists on.
- Everything NOT on that list is admin-only rather than unserved, so the base
  rig keeps the 2026-09-04 "read every document in this viewer" behaviour on
  a dev checkout. If the owner would rather /help never served an internal
  document to anyone, the change is one `if` in `help.resolve_document`.
- `/help`'s nav entry stays `admin_only=False`: an editor standing on
  Transfers is exactly who the guide is for, and the gate is now on the
  documents rather than on the page.
