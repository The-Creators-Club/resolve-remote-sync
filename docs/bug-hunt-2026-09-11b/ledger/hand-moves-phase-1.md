## Hand moves on the server, phase 1: the dashboard notices, 2026-09-11

Not a hunt finding: the owner's words after the third trip of the day, "this
happening every time I move something on the server is a major issue, can we
come up with a better solution to this problem." The design is
`docs/HAND_MOVES_ON_THE_SERVER.md`; this ledger is its phase 1, the only
phase built here. Phases 2 (`/api/v1/files/locate` plus the companion) and 3
(the breaker message, proxy_pairs, the MOVES history) are other builders'.

### What it does

The collector's inventory cycle already walks every project's files into
`nas_media` every 15 minutes. A hand move is a plain diff between two of
those walks: a `(basename, size, mtime_ns)` that VANISHED from one path and
APPEARED at exactly one other. `collector.detect_moves` does that match
across the WHOLE pass, not per project, because the case that started this
was cross-project (a shoot that left Creator Profiles for FF5 Talent Gap is a
vanish in one walk and an arrival in another). Basenames are compared through
`db.media_rel_key`, like every other path comparison here (CR-90); the
destination is recorded in the bytes the NAS spells it in, because that is
the path a companion renames to.

Each proven move is written by `db.record_file_move` with the new
`file_moves.source = 'detected'` (v53) and the target machines
`db.file_move_target_machines` computes, which is the button's rule factored
out: every computer with the source project ticked in either mode, plus any
computer whose manifest says it holds the file. The row is written in the
state a COMPLETED server rename lands in, because the rename has already
happened; from that moment the fleet follows it through exactly the
machinery `docs/FILE_MOVES.md` describes, and nothing new had to be taught to
any companion.

### The refusals, which are most of the feature

- Two destinations for one key (a file copied twice, then the original
  deleted), or two sources for one arrival: an ambiguity, and an ambiguity is
  a refusal. It stays a deletion for lane B and the breaker keeps its say.
- A file that only vanished is a DELETION. This code does nothing with it,
  ever.
- A file nothing could stat keys on nothing: two NULLs are not evidence that
  two files are the same file.
- A folder is ONE row only when every file the last walk saw under it moved
  to the matching path under one new folder AND nothing was left behind at
  the old path. Today's leftover `Proxy` folder (67 byte-identical files that
  stayed) is precisely the "something stayed" case, so that move is recorded
  as its originals, one row each, and the leftovers remain a proxy_pairs
  finding. A `Proxy` folder is never either end of a detected move, because
  the button refuses one and a detected move may not do what the button would
  have refused; a proxy that moved WITH its original rides on its row.
- Nothing here touches the filesystem, on the NAS or anywhere else.

### Bounds and blast radius

`DETECTED_MOVE_LIMIT = 500` rows per pass, the excess logged loudly (a pass
bigger than that is a restore or a remount, not an afternoon of filing). An
identical move recorded in the last day is not recorded twice, which is the
walk-races-the-move case. A project whose walk was refused by the collapse
brake (DASH-5) is not diffed at all, so a refusal cannot manufacture the same
"vanish" every cycle. The whole detection is wrapped and runs LAST in the
cycle: the inventory walk is what tells every editor whether their footage is
on the server, and a convenience on top of it may never take it down.

One known bound, recorded in FILE_MOVES.md §8: a project that loses ALL of
its originals to one move trips the collapse brake, which keeps the previous
file list, so that move is not detected. Safe direction, and the brake exists
for a reason an unmounted dataset taught us.

### What the owner sees

One log line per move naming source, destination and the number of machines
following, and a `notices` row of the new kind `file_move_detected`
(severity info, subject = the destination path, registered in
`db.NOTICE_KINDS` WITH its writer). Its fix line is "Nothing to do; the
computers follow on their own. If this was not a move, open the project
page's MOVES history." `db.mark_notice_checked` is the new fourth call on the
notice registry, and it exists because this kind is EVENT-shaped: its notices
must not be auto-closed by the next clean pass 15 minutes later, and without
an explicit stamp the WHAT THE SERVER CHECKS panel would show it
[ NOT CHECKED ] on every fleet that has never had a hand move.

### Files

- `dashboard/src/ccsync_dashboard/collector.py`: the detection section at the
  end of the module (`InventoryWalk`, `DetectedMove`, `detect_moves` and its
  helpers), `_record_detected_moves`, and the three lines in `_run_inventory`
  that keep each project's previous file list and hand the diff over.
- `dashboard/src/ccsync_dashboard/db.py`: `SCHEMA_V53` (`file_moves.source`,
  default `'admin'`), `FILE_MOVE_SOURCE_*`, `record_file_move(source=...)`,
  `file_move_target_machines`, `file_move_recorded`, `nas_media_rows`,
  `mark_notice_checked`, the `file_move_detected` registry row.
- `dashboard/tests/test_hand_moves_detected.py`, `docs/FILE_MOVES.md` §8.

### Left out, deliberately

`api.move_project_files` still computes its target machines inline rather
than calling the new `db.file_move_target_machines` (which is that code,
comment for comment). The work package forbade edits to `api.py` because two
other builders were in that file at the same time; the two copies agree
today, and folding the button onto the helper is a three-line follow-up for
whoever owns `api.py` next.
