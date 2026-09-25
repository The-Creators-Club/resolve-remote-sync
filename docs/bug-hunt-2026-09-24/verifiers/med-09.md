# Verifier med-09 (2026-09-25)

Judged against HEAD (63d4290) via `git show HEAD:<path>`. Working-tree
health.py is unmodified, so the one snippet below ran against HEAD code.

## logic-sync-truth-1 - CONFIRMED (medium)

`lane_chip` (health.py:230) returns RED "this companion has been silent for 15
minutes or more" for every lane once `received_at` is 15 min old, while
`report_freshness` says AMBER until 6 h. `why_causes`/`_why_first` has no
"not reporting" reason, so `fleet_headline` falls through to `_lane_fault`,
which takes the first red lane (lane A) and writes "Upload has stopped: ...",
level red. The row dot also goes red (api.py:977-996 folds the lane chips into
`worst()`), defeating UX-2's amber window. Not in KNOWN_BUGS or earlier hunts.

Evidence: ran in the dashboard venv, three idle lanes received 20 min ago:
`report_freshness` -> `('amber', 'no report since ...')`; `fleet_headline`
-> `{'reason': 'lane_error', 'text': 'Upload has stopped: this companion has
been silent for 15 minutes or more', 'level': 'red'}`.

## logic-sync-truth-2 - CONFIRMED (medium)

The companion appends to `proxies`/`originals` only while `len < 2000` and sets
`truncated` (manifest.py:208-223); `replace_editor_media` keeps 2000 per kind.
`down_totals_q` counts every NAS proxy NOT EXISTS in `editor_media`, so
proxies 2001+ held locally are reported owed for ever (overcount), while
`up_totals_q` only walks `editor_media`, so an un-uploaded original past the
cap is never counted (undercount). `safe_to_close` (ui.py:419-470) sums only
up-direction queues and ignores `manifest_truncated`, so it can say "Safe to
close". transfers.html:78 says only "totals may undercount". The part CR-314
did not cover; display-only (lane A still uploads), so medium, not higher.

## logic-sync-truth-3 - DOWNGRADE (low)

The mechanism is real: check_once reports STATE_SYNCING with
`queued=needTotalItems` without consulting the connection summary, sets no
progress token, and `_sync_line`/`compute_overall_color`/`should_pulse` never
read `_lane_peer_states()`. But both named scenarios are covered elsewhere:
NAS Syncthing down raises the dashboard's `syncthing_reachable` alert
(alerts.py:1593-1608); a tailnet drop fails both rclone lanes, which yields the
`transport_offline` blocked reason, and `_sync_line` renders `blocked.detail`
BEFORE the up/down counts. On the dashboard, `editor_status` turns a
behind-and-not-connected device RED after OFFLINE_RED_SECONDS on the project
views. What is left is a single machine whose Syncthing path alone fails while
SFTP works: the tray over-claims activity and the fleet lane chip stays amber.
A misleading status line in a narrow case, nothing lost.

## logic-sync-truth-4 - CONFIRMED (medium)

`DiskFloorLatch.check` parks under `min_free_bytes` and clears only at
`clear_free_bytes = 2 x min` (lane_guard.py:955, 1021); `prune_trash`'s
pressure loop stops at `free >= min_free_bytes` (lane_guard.py:1292) and
rclone_lane.py:4531 passes `disk_floor.min_free_bytes`. So a machine whose
only recoverable space is `.ccsync-trash` ends between 1x and 2x with lane B
parked until a human resumes, while trash that could have released it stays.
CHIP_HELP["disk"] (ui.py:315-318) still says the trash "cannot prune while
proxy download is stopped", which is false since SYNC-16 moved the prune to
the sequencer (sequencer.py `_prune_trash`, blocked only by a tripped
breaker). Lane B stuck off indefinitely is a real functional stop, so medium.

## logic-plans-2 - DOWNGRADE (low)

The buttons do post `?mode=` with no machine, and `add_selection_for_person`
INSERTs a row on every non-wired computer. But docs/UPLOAD_ONLY_TICK.md §2
states this on purpose: "Like the tick button it is the PERSON's control
(every computer they use)", and the plain TICK does the same insert. So
ticking the other computers, and flattening a mixed plan, is the documented
design. What is left is that SWITCH TO FULL SYNC has no UX-1 capacity
`hx-confirm` (project_detail.html:90-101), unlike the tick button (lines
~55-63). That is a missing warning on a documented action, not a wrong
action, so low.

## logic-plans-4 - CONFIRMED (medium)

`file_move_target_machines` (db.py:5842-5884) is the only target list (used by
api.py:2856 and collector.py:1908). It unions the machines whose plan holds
`from_slug` (`fetch_machine_selections(for_enforce=True)`, no borrower
expansion) with the machines whose `editor_media` lists the file. A borrower
machine ticks the borrower slug, and its manifest builds per-file lists only
for `rel_to_slug`, which is deliberately selection-only (sequencer.py:512-516,
855-863). So it is in neither set. The borrower still runs lane A over the
borrowed subtree (`_borrowed_includes`, `known_rels`), so a file it uploaded
into the lender folder and that was later moved on the NAS is uploaded back to
the old path. `fetch_borrowers_by_lender` exists (db.py:2948) but is not
consulted here. No KNOWN_BUGS entry covers moves OUT of a borrowed folder
(CR-283J is moves INTO one, on the companion side).

## Duplicates

None within the group, and none with the eleven highs.
