# dash-mounts-ui - the dashboard's UI layer, the three optional mounts, the templates/static it serves, the deploy image and CI

Files read (with approximate coverage):
- `git diff 40f931a..HEAD` over the whole territory, every hunk (100%).
- `dashboard/src/ccsync_dashboard/ui.py` (~40%: `safe_to_close`, `_fleet_view`
  and all five `fleet_grid.html` render sites, `_help_response`/`page_help*`,
  `service_worker`, `web_manifest`, `page_offline`, the admin partials touched
  by the diff).
- `dashboard/src/ccsync_dashboard/broll.py` (~80%: the gate, the token policy,
  `_identified_scope`/`_fleet_stamp`/`_token_ok`, `_init_broll_storage`),
  `music.py` (~30%, the changed hunk and the shared helpers it imports),
  `ytdl.py` (~25%, imports + `_init_ytdl_storage`).
- `dashboard/templates/partials/fleet_grid.html` (the new resolve-detail block
  in full, plus the `fleet.*` surface), `partials/my_queue.html`,
  `partials/transfers.html`, `help.html`.
- `dashboard/static/sw.js` (100%), `dashboard/static/htmx_errors.js` (the
  changed module in full), `htmx.min.js` 1.9.12 (the event-detail shapes:
  `requestConfig`, `responseInfo`, `triggerEvent`'s `detail.elt`).
- `dashboard/deploy/Dockerfile` (docs COPY block), `run.sh` (uid block + the
  whole youtube_unblock block), `select_code_root.py` (`main`, `check_tree`,
  `bump_boot_attempts`, `revert`), `.dockerignore`, `compose.image.yaml` /
  `compose.appliance.yaml` volume lists.
- `.github/workflows/ci.yml` (the installer step + the surrounding jobs).
- Supporting, outside the territory but needed to verify both sides:
  `published_docs.py`, `help.py` (signatures), `mount_status.py`,
  `api.build_transfers_view` + the report models `ResolveHealthIn` and
  friends, `db.store_resolve_health_detail`/`resolve_health_detail`,
  `dashboard_update.py` (`MAX_BOOT_ATTEMPTS`, the packages view).

Tests run:
`dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py tests/test_help_page.py -q`
-> 58 passed, 1 skipped (the mounts-ui file on its own: 20 passed, `sh` and
`node` both present on this machine, so no conditional test was skipped there).

## Findings

### dash-mounts-ui-b-1 - the res-fleet-2 runtime mount probe watches the bind MOUNTPOINT, which never goes away
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/broll.py:535`,
  `dashboard/src/ccsync_dashboard/music.py:449`,
  `dashboard/src/ccsync_dashboard/ytdl.py:700` (probe in
  `dashboard/src/ccsync_dashboard/mount_status.py:recheck`)
- What: the three mounts record their *data root* for the collector's
  per-cycle `os.path.isdir` re-probe, and on every shipped deployment that
  root is a container bind-mount TARGET (`/broll-data`, `/music-data`,
  `/ytdl-data`, from `compose.image.yaml` lines 128/141/145 and
  `compose.appliance.yaml` 183-184). A bind-mount target is a directory in the
  container's own mount namespace: it exists whether or not the host still has
  anything mounted there, and `os.path.isdir` on it answers True in every
  failure the fix names. `recheck` only degrades when the probe answers False.
- Failure scenario: the exact scenario in the new docstring - the NAS export
  flaps at 03:00 and `/broll-data` goes empty - leaves `mount_status` saying
  `mounted`, the topbar still advertising B-ROLL and MUSIC, and every request
  under them failing, with no notice and no degraded verdict. The probe can
  only fire if something *deletes* the container's mountpoint directory, which
  nothing does.
- Evidence: `mount_status.recheck` (`probe = is_dir or os.path.isdir`;
  `if not present and status == MOUNTED`). `broll/web/app/config.get_data_root`
  returns `Path(os.environ["BROLL_DATA_ROOT"]).resolve()` = `/broll-data`;
  `musicweb/config.DATA_ROOT` = `/music-data`; `ytdl.py:697` reads
  `YTDL_DATA_ROOT` = `/ytdl-data`. Worse, `_init_*_storage` `mkdir(parents=True,
  exist_ok=True)`s that same path at boot, so even an image-mode container
  started with the volume missing creates the directory the probe will later
  find. No test covers the degraded transition against a real path shape - the
  collector test injects `is_dir`.
- Ledger: new (the fix being probed is res-fleet-2, landed in 18e69f3; this is
  "res-fleet-2 does not fix res-fleet-2's own scenario")
- Suggested fix: record something *inside* the root that only exists when the
  data is really there - `broll_config.get_db_path()`, `music_config.DB_PATH`,
  `Path(root)/"cache"` for ytdl - or probe for a non-empty listing / the db
  file rather than the mountpoint. A mountpoint is never evidence about what is
  mounted on it.

### dash-mounts-ui-b-2 - a permanently unbootable code tree is now never reverted, because only a tree that PASSES check_tree is counted
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/deploy/select_code_root.py:281-296`
- What: dash-mounts-ui-8 moved `bump_boot_attempts` from before `check_tree` to
  after it, to stop environment-shaped refusals counting against the bundle.
  But `check_tree` returns a reason for TREE-shaped failures too - a missing
  `manifest.json`, a `record.json` that does not verify, a `runtime_id` that no
  longer matches the image, a tree missing `src/` - and `main()` now returns
  before the bump in all of them. `revert()` is reachable only through
  `already_failed >= MAX_BOOT_ATTEMPTS`, and `boot_attempts` is only ever
  raised by `bump_boot_attempts`. So the counter can now only ever describe a
  tree that was selected and then crashed, never one that cannot be selected at
  all - and the crash-loop guard no longer covers the bundle failures it was
  written for.
- Failure scenario: a site takes an OTA update to 0.7.43, then the IMAGE is
  updated and its `/venv/.runtime-id` changes. `check_tree` refuses with "was
  built for runtime ..., this image is ..." on every boot from then on.
  Previously two boots reverted `current.json` to the previous tree and wrote
  `reverted_reason`, which Settings -> Packages renders. Now `current.json`
  claims 0.7.43 for ever, the container silently runs the image's older code,
  `boot_attempts` renders 0, `reverted_reason` is empty, and the only evidence
  is one `run.sh` WARNING line per boot in a container log. There is no alert
  kind for it (`grep -n "boot_attempts\|code tree" alerts.py health.py` -> no
  hits).
- Evidence: read `main()` (lines 258-299), `bump_boot_attempts` (234),
  `revert` (241), `check_tree` (180-220). The new regression test
  (`test_a_refused_tree_is_not_counted_as_a_failed_boot`) stubs `check_tree` to
  return an *environment*-shaped reason only, so it cannot see this: it pins
  "no bump on refusal" as an unconditional rule rather than the rule the
  finding asked for.
- Ledger: new (regression introduced by the CR-243 fix for dash-mounts-ui-8)
- Suggested fix: have `check_tree` classify its refusals (`("env", reason)` vs
  `("tree", reason)`) and bump only on the tree-shaped class, or bump on
  refusal but reset the counter whenever the reason is environment-shaped.
  Either way the watchdog has to keep covering "this bundle can never boot".

### dash-mounts-ui-b-3 - the new stale-while-revalidate does not hold the service worker alive, so the revalidation it was added for can be killed
- Severity: medium
- Confidence: CONFIRMED (by the Service Worker lifetime contract; not
  reproduced on a device)
- Where: `dashboard/static/sw.js:129-148`
- What: on a cache hit the handler returns `hit` immediately and lets the
  revalidating `fetch(...).then(... cache.put ...)` run detached. A service
  worker's lifetime is extended only by the promises passed to
  `event.respondWith` and `event.waitUntil`; once the responded-with promise
  settles and the body is delivered, the user agent may terminate the worker.
  The background fetch and its `caches.open(...).put(...)` are registered with
  neither, so on the slow/flaky mobile connection this fix exists for they are
  the most likely thing to be cut off - and the asset stays stale exactly as
  before.
- Failure scenario: a CSS hotfix is redeployed under an unchanged dashboard
  VERSION. An installed phone on a poor link loads the page, gets the cached
  CSS, and the background revalidation is killed with the worker before
  `cache.put` runs. Next load: same cached CSS. Repeat indefinitely - the
  dash-mounts-ui-5 symptom, now behind a fix that looks applied.
- Evidence: read the handler; `network` is never passed to `event.waitUntil`
  (`waitUntil` appears only in `install` and `activate`). The node harness in
  `test_a_cached_static_asset_is_revalidated_in_the_background` models no
  worker lifetime at all - it just waits 10 ms in a process that stays alive -
  so it passes either way and cannot fail on this.
- Ledger: new (incomplete fix for dash-mounts-ui-5, CR-243)
- Suggested fix: `event.waitUntil(network)` (guarded with `.catch(function(){})`)
  before returning the cached hit, so the revalidation is an extended-lifetime
  promise.

### dash-mounts-ui-b-4 - the image build now hard-fails on a document published_docs.py calls best effort
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/deploy/Dockerfile:115`
  (`COPY docs/HOW_IT_WORKS.md docs/EDITOR_SETUP.md /app/docs/`) vs
  `dashboard/src/ccsync_dashboard/published_docs.py:REQUIRED_DOCS`
- What: `published_docs.py` states the policy explicitly - only
  `HOW_IT_WORKS.md` and the `legal` tree are REQUIRED, "everything else on the
  list is best effort, because a missing document is not a reason to refuse to
  ship a dashboard". The Dockerfile names `docs/EDITOR_SETUP.md` in a COPY, and
  a COPY that names a missing file fails the BUILD - which is exactly why the
  line it replaced was a glob (the removed comment says so). The OTA bundler
  and the bind-mode deploy treat the same file as optional, so the three
  shipping routes now disagree about how bad its absence is.
- Failure scenario: `docs/EDITOR_SETUP.md` is renamed (or moved under
  `docs/editor/`) in a branch. `tools/build_dashboard_bundle.py` and
  `install_dashboard_app.py` ship happily; `.github/workflows/image.yml` fails
  the image build with a bare `COPY failed` and no mention of the doc policy.
- Evidence: the two files, side by side; `REQUIRED_DOCS = ("HOW_IT_WORKS.md",)`.
- Ledger: new (hygiene left by CR-243's dash-mounts-ui-1)
- Suggested fix: either promote `EDITOR_SETUP.md` to `REQUIRED_DOCS` (one
  decision, documented) or copy the optional files with a shape that tolerates
  absence, and say which in the comment beside the COPY.

### dash-mounts-ui-b-5 - run.sh's new uid fallback blames APP_UID for a number it read off /data
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/deploy/run.sh:36-45`
- What: when `APP_UID` is unset, `expected_uid` comes from `stat -c %u /data`,
  but the warning still prints "...files are owned by uid $expected_uid
  (APP_UID)" and sends the admin to "fix compose's `user:` line". On the case
  the fallback exists for, the number did not come from APP_UID at all, and the
  cause may be the opposite of what the sentence says.
- Failure scenario: a hand-rolled or appliance first boot where `/data` was
  created by docker as root and `install_dashboard_app.py`'s chown has not run.
  The container correctly runs as 3000; the warning tells the admin that the
  deployment's own files are owned by uid 0 "(APP_UID)" and to change the
  compose `user:` line to 0 - the one change that would be wrong. The right
  action is to chown `/data`.
- Evidence: read the block; `expected_uid` has two provenances and one
  sentence. `test_the_uid_warning_works_without_app_uid_in_the_environment`
  asserts the strings are present and never reads the message.
- Ledger: new (copy defect in the CR-243 fix for dash-mounts-ui-6)
- Suggested fix: branch the sentence on which provenance was used - "(APP_UID)"
  only when `APP_UID` was set, and "chown -R $(id -u) /data" as the advice when
  the number came from `stat`.

### dash-mounts-ui-b-6 - the refusal banner's path is consumed by the FIRST swap of a response, so an out-of-band banner loses it
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/static/htmx_errors.js:210-234`
- What: htmx fires `htmx:afterSwap` once per element in `settleInfo.elts`, and
  an out-of-band swap adds its elements to that same list. The handler deletes
  the WeakMap entry on the first one, so if the `.error-banner` arrives in the
  second (an `hx-swap-oob` fragment), `path` is null and the banner is not
  moved to the button - the DUI-6 symptom the module exists to prevent, for
  that shape of response.
- Failure scenario: a write route that answers with a main partial plus an OOB
  error strip. The strip renders two thousand pixels above the viewport and
  nothing scrolls to it.
- Evidence: `htmx.min.js` 1.9.12, `oe(n.elts, function(e){ ... ce(e,"htmx:afterSwap",u) })`
  - one loop over every settled element with the same `responseInfo`. Note the
  primary path is sound: I verified `requestConfig.elt` IS set in 1.9.12
  (`ce(n,"htmx:configRequest",H)` and `ce` does `r["elt"]=e`), so the new
  `detail.requestConfig.elt` read is not dead code.
- Ledger: new (pre-existing shape carried through the CR-243 fix for
  dash-mounts-ui-7)
- Suggested fix: do not delete the WeakMap entry in `afterSwap`; the map is
  weak and the entry dies with the xhr anyway.

## Coverage note
Not covered: the bulk of `ui.py` (the ~150 routes outside the diff - admin
settings, projects, assignments, jobs, packages); the full route surface of
`MusicGate`/`YtdlGate` (I read `BrollGate` closely and spot-checked that the
other two mirror it); `dashboard/templates/*` beyond the five files above;
`.github/workflows/{image,release-*,android}.yml`; `requirements.lock`.

Two things the suite does not cover and a reader should not assume are tested:
`mount_status.recheck` is only ever exercised with an injected `is_dir`, so no
test says anything about the real path shape (finding b-1); and neither node
harness models the thing it is asserting about (the sw one has no worker
lifetime, finding b-3; the htmx one fires exactly one afterSwap per response,
finding b-6). `test_a_refused_tree_is_not_counted_as_a_failed_boot` stubs
`check_tree` and therefore pins a broader rule than the finding asked for
(finding b-2).

I could not run `pwsh` on this machine, so the CI change (dash-mounts-ui-4,
seven previously-unrun installer suites now gating every release through
`publish_latest.py`) is unverified from here: if any of the six that never ran
in CI is red on a hosted windows runner, the vendor feed has no green run to
publish from. Worth one deliberate CI run before shipping. The enumeration
itself is correct - `installer/tests/*.ps1` is eight files, all of them tests,
no helper modules, and `test_macos_site_values.sh` is still run by the linux
job at ci.yml:432.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/mount_status.py`: `recheck`'s probe is the
  other half of finding b-1 - `os.path.isdir` is too weak a question for a
  mountpoint, whatever path the callers record (dash-collector-alerts).
- `dashboard/src/ccsync_dashboard/broll.py` (whole-file note): `BrollGate`
  strips and re-stamps identity headers only for `scope["type"] == "http"`; a
  `websocket` scope would reach the sub-app with `X-CCSync-Admin` intact. Inert
  today - none of the three sub-apps has a websocket route (grepped) - but it
  is a route added upstream away from being real (security lens).
