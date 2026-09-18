# CR-294 - the b-roll insert wire during a container outage - PARTLY FIXED in repo 2026-09-18 (mediums wave, companion-broll)

### CR-294A (proxy-tiers-3) - a `known: false` object must carry no judgement forward - FIXED (companion/src/ccsync_companion/broll_server.py)

The finding is that the `known` outage guard (CR-284G) is understood by 0.9.75
and later only, while every build in the field today is 0.9.74, so a ten-minute
unreadable archive folder still turns every Send to Resolve into a ledgered
stand-in. Most of it was already closed in the working tree: `derive_insert_paths`
has the `known is False` branch, `plan_insert` returns PLAN_FETCH_ORIGINAL from
it, and broll-1's explicit-null handling (`original_known`) means even a
dashboard ROLLED BACK below the `known` fix answers an outage with
`original_rel: null` and gets PLAN_PREVIEW_ONLY here, never a stand-in. What was
still open was the server half - the verifier's `original_is_edit_weight: true`
on the known=false path - and that lives in `broll/web/app/routes_api.py`, which
belongs to the webapps-broll group, so it is under OWED below, written out
verbatim. The one piece in this group's files is the consequence of that OWED
change: once the route forces `true`, this build would have carried the lie into
its derived tiers (`weight = insert.get(...)` runs unconditionally after the
`known` branch), so a reader of the tiers - the insert debug line today, a
decision tomorrow - would read "a 6K original is already small enough to edit
with" off the one object whose whole point is that the server judged nothing.
The weight is now reset to `None` when `known is False`; `geometry` is not,
because it comes off the `videos` row and never touched the failed listing. Four
tests in a new file pin it: the weight is null and `from_page` false on the
outage object, the plan is still "fetch the file the editor asked for", a
healthy heavy clip still keeps `False` and still plans a stand-in (the reset is
scoped), and the rolled-back-dashboard outage shape is still preview-only.

### Verification
- CR-294A: `companion/tests/test_bug_hunt_2026_09_18b_mediums_broll.py` - 4
  passed; with the new branch disabled,
  `test_a_known_false_object_carries_no_weight_judgement_forward` fails
  (`assert True is None`). `tests/test_broll_insert_tiers.py` and
  `tests/test_bug_hunt_2026_09_18b_companion_media.py` re-run together: 46
  passed. `py_compile` clean on both touched files.

### Not fixed
- proxy-tiers-3's server half (`original_is_edit_weight: true` on the
  known=false path) is not this group's file; see OWED. Without it the fleet's
  0.9.74 builds remain unprotected during a container outage, exactly as the
  finding says.

### OWED TO ANOTHER GROUP
- **webapps-broll (CR-302), `broll/web/app/routes_api.py`, `_insert_object`.**
  Replace `"original_is_edit_weight": _is_edit_weight(video),` with the forced
  answer on the outage path:

  ```python
        # proxy-tiers-3 (2026-09-18b mediums): FORCED on the known=false
        # path, and it is the only field in this object that is not the
        # truth. `known` is read by companion 0.9.75 and later only; every
        # build in the field today reads `original_is_edit_weight` alone, and
        # a `false` there during an outage is what makes it plan a stand-in
        # and write a ledger row that outlives the outage for ever. `true`
        # forces PLAN_FETCH_ORIGINAL on 0.9.65..0.9.74 - fetch the file the
        # editor asked for, which is the route 0.9.75 takes from `known`
        # anyway, so nothing changes for a new build (it returns before the
        # weight is consulted). The dashboard deploys first, so this is what
        # protects the fleet in between. It must stay scoped to this path: a
        # `true` on the healthy path would suppress every stand-in.
        "original_is_edit_weight": (
            True if target.get("known") is False
            else _is_edit_weight(video)),
  ```

  `edit_proxy_rel` is already null there, so nothing else changes. Test:
  `broll/web/tests/test_insert_target.py`'s known=false cell (around lines
  250-271) is a 3 Mb/s clip that is already edit-weight, so it cannot pin
  this - add a NEW cell with a HEAVY row (e.g. 2160p, 200 Mb/s, h264) whose
  archive listing raises, asserting `insert["known"] is False` and
  `insert["original_is_edit_weight"] is True`, and keep an assert on a HEALTHY
  heavy clip that it is still `False`.

### Deploy order
Dashboard first, companion second - unchanged, and the OWED change is precisely
what makes that order safe. This group's change is inert on its own (it only
nulls a field the outage path never consults) and tolerates a dashboard one
release older or newer, including a rollback below the `known` fix: with no
`known` key, the explicit-null path (broll-1) still answers preview-only.

### Owner decisions
None.
