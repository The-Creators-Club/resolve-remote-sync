## CR-299 - Timeline Cards landing, the kill switch and the retire banner - FIXED in repo 2026-09-18 (mediums wave, dashboard-cards-ui)

Three confirmed mediums on the dashboard's Cards surfaces: a kill switch that
deleted the live per-episode page's cache, a retire that left a refusal banner
no admin could clear, and an idle release that cannot see an editor working
offline.

### CR-299A (dash-cards-1) - the kill switch deletes the NEW per-episode page's shell cache too - FIXED (dashboard/src/ccsync_dashboard/cards_landing.py)

`KILL_SW`'s sweep was narrowed by CR-285C to `cards-shell-*`, on the belief
that the prefix belonged to the dead flat page. It does not: `page.render_sw()`
bakes ONE `page_version()` per checkout, so the flat page and every live
`/cards/p/<slug>/` page name their shell cache `cards-shell-<same VER>` on one
origin. The kill switch therefore deleted the live per-episode worker's shell,
and nothing refills it - only `install` writes `SHELL_URLS`, the navigation arm
never caches a navigation - so an installed episode app lost its offline shell
until the next Cards republish. The worker cannot tell the two apart (it does
not know the live VER), so it now deletes NO cache at all: unregistering plus
reloading the clients is the whole act, and the per-episode worker's own
`activate` already prunes stale shells behind an `n !== SHELL` guard. The test
is `test_the_kill_switch_deletes_no_cache_at_all`, which asserts the string
`caches` does not occur anywhere from the `install` listener onwards; it fails
on the old source because the `caches.keys()` loop is there.

### CR-299B (dash-mounts-ui-1) - a retire carries a refusal the admin can never clear - FIXED (dashboard/deploy/select_code_root.py)

regression-3 made `_retire` CARRY `revert_refused_reason` /
`revert_refused_from` so `alerts.py` kept its evidence. The carry is permanent:
`_retire` writes `version: ""`, and every later boot returns at `main()`'s
`if not version:` long before the clearing rule, so nothing in the script can
drop the keys again, while `admin_dashboard_update.html` renders the banner on
the key alone. The admin read "restore a backup" on a healthy container for
ever. The keys are now dropped, because the sentence is false by construction
at that point: the branch is reached only after `revert_refusal("")` answered
"" - the image has just been judged able to run this database. The evidence is
moot too, since `alerts.py`'s check compares an APPLIED version against the
image and there is no applied version left.

Owner decision recorded here because it contradicts a pinned test:
`test_a_retire_keeps_an_earlier_refusal_where_the_alert_looks_for_it` pinned
the carry, and it is REPLACED by
`test_a_retire_drops_a_refusal_the_admin_could_never_clear` (same file), which
also boots a second time to prove the banner does not come back. The verifier
asked for exactly this rewrite and gave the reason above.

### CR-299C (security-1) - the 15-minute idle release measures SERVER REQUESTS - PARTLY FIXED (cards_pool.py, cards_tunnel.py, cards_landing.py, templates/cards_landing.html)

`Entry.seen` was stamped only by a request SERVED through the mount (plus the
landing's open), so an editor working OFFLINE in Cards - the shipped feature
the sw.js kill switch was narrowed to protect - held no seat after
`ACTIVE_SECONDS`, and any other signed-in session could close the engine their
companion agent is driving Resolve against. Two changes, neither of which
lengthens `ACTIVE_SECONDS` (that would trade this against the wedge CR-285P
exists to end). First, a SECOND liveness signal: `EnginePool.note_agent(editor)`
stamps the seat, called from `cards_tunnel.local_engine` once `engine_for` has
routed an agent call by the identity `_require_fleet_caller` verified - the one
beat that reaches the container when the browser cannot, best effort and never
able to fail an agent call. Second, the close is an INFORMED act: `Entry.last_in()`
answers who was in last and how long ago, `_state` carries it onto the row, the
landing names it in the Who column when the occupant list is empty, and
[ CLOSE ] confirms with a server-built prompt (emitted through `tojson`, since
an apostrophe in an episode name would otherwise end the JS string). The row
flag and the POST gate still ask the same `pool.may_close`, so they cannot
disagree. Tests:
`test_an_agents_poll_keeps_its_editors_seat_while_their_browser_is_offline`,
`test_note_agent_never_raises_for_an_editor_in_no_episode`,
`test_the_row_names_who_was_last_in_and_when`,
`test_the_landing_page_renders_the_confirm_and_the_last_in_line`.

What is NOT done, and is OWED as a follow-up: the verifier's third signal -
treating an episode as occupied while the OFFLINE seam still has unacknowledged
work (the page's last known rev). An offline session with no companion agent
attached is still closable after fifteen quiet minutes; it is now closable only
by somebody who has been told who was last in and when.

### Verification
- dash-cards-1: `dashboard/tests/test_cards_pool.py -k kill_switch` (3 passed).
- dash-mounts-ui-1: `dashboard/tests/test_bug_hunt_2026_09_18_dashboard_lows.py -k retire` (3 passed).
- security-1: `dashboard/tests/test_cards_pool.py` (43 passed), plus
  `test_cards_mount.py test_cards_tunnel.py test_cards_page_prefix.py`
  (61 passed, 5 skipped) for the neighbours of the tunnel change.
- Pre-existing and NOT mine: `test_a_move_between_two_projects_is_paired_across_two_passes`
  and `test_a_file_that_comes_back_to_its_old_path_is_not_a_move` in the lows
  file fail on the current uncommitted tree (file_moves / db.py, another
  group's live edit); nothing I touched is on that path.

### Not fixed
- security-1's offline-rev seam (above): an episode with unacknowledged offline
  work and no agent attached still reads as idle.

### OWED TO ANOTHER GROUP
- `KNOWN_BUGS.md` (nobody edits it this wave): the CR-285C entry should gain a
  line saying the narrowed `cards-shell-` sweep was narrowed to NOTHING, because
  one `page_version()` per checkout means the live per-episode pages share the
  prefix, and that the kill switch now deletes no cache; and the regression-3
  entry should gain a line that the retire carry it introduced was permanent
  (the `if not version:` return) and has been dropped.
- No companion, no cross-repo and no MulticamPipeline change is needed.

### Deploy order
Dashboard only, and it may be deployed alone in either direction. The kill
switch and the retire change are container-local. `note_agent` is stamped from
a route the companion already calls with an unchanged request and response
shape, so a companion one release older or newer, and a dashboard ROLLBACK,
all behave exactly as today (the seat simply stops being stamped again).

### Owner decisions
- The regression-3 test was rewritten rather than kept: see CR-299B.
