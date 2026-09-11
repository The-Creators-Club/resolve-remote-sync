# Hand moves on the server: making them a non-event

Written 2026-09-11 evening, from the owner's words after the third trip of
the day: "this happening every time I move something on the server is a
major issue, can we come up with a better solution to this problem."
Status: phases 1 and 2 BUILT 2026-09-11 evening (dashboard 0.7.45 schema v53, companion 0.9.73; ledgers `docs/bug-hunt-2026-09-11b/ledger/hand-moves-phase-1.md` and `hand-moves-phase-2.md`); phase 3 (the UI) not started. Two bounds found while building: cross-project matching is per inventory PASS (a destination walked in a different cycle is not matched), and a project that loses ALL its originals to one move trips the DASH-5 collapse brake and is not diffed at all - both the safe direction, both in FILE_MOVES.md section 8. Related: `docs/FILE_MOVES.md` (the button),
`docs/SYNC_SAFETY.md` (the breaker, CR-44, CR-45), KNOWN_BUGS CR-267a.

## 1. What happened today, exactly

1. 2026-09-09: the Gold Card Meetup shoot was moved BY HAND on the NAS from
   `Projects/2026/CCT/Creator Profiles/Season 1/Interviewees/Interviews/`
   to `Projects/2026/FF5/Talent Gap/Interviewees/`. Explorer moved the
   originals, the XML sidecars and the Proxy folder; a second Proxy folder
   with 67 files (6.7 GB, byte-identical) stayed behind at the old path.
2. The dashboard's proxy_pairs check saw 56 orphaned proxies in the old
   folder and said so, two at a time (CR-267a).
3. 2026-09-11 18:47 and 19:05: the leftover folder was deleted on the NAS.
4. 2026-09-11 ~19:10: Ruskin's machine, which syncs Creator Profiles Season
   1, ran a lane B pass, found 69 files gone on the server, moved its 69
   local copies to `.ccsync-trash`, and because 69 is over the breaker's
   limit of 50 files per pass, PARKED lane B: "proxy download stopped
   itself and needs a person to check the server". An admin resumed it at
   19:30 from the fleet page.

Every step behaved as designed. The design is what is wrong: a move an
owner makes in Explorer in ten seconds costs the fleet a two-day trail of
warnings and a stopped lane on every machine that held the files.

## 2. What exists today, and where each one stops

| Mechanism | What it does | Where it stops |
|---|---|---|
| **The MOVE button** (`docs/FILE_MOVES.md`, project page) | Records the move, renames on the server, tells every holding machine; the companion moves its copy, relinks Resolve, keeps the old path out of lane A for a day. Nothing deletes. | Only for moves made THROUGH the button. A hand move in Explorer, which is how everybody moves things, gets none of it. The button lives on one project's page, so a move BETWEEN projects (today's case) is not even offered. |
| **CR-44, the breaker's own move probe** | Before tripping, lane B re-lists the scope and matches trashed files on basename + exact size; a match counts as a relocation, not a deletion. | The scope is the PROJECT being synced. A folder moved to another project is outside it, so it "still looks like a deletion and still trips" (SYNC_SAFETY.md says exactly this). Today's move was cross-project. |
| **CR-45, the breaker** | Parks lane B (never `error`) when a pass trashes over 50 files or too large a fraction; only a human clears it. | Correct as a last line of defence. The problem is how often the first two lines let a plain move reach it. |
| **Lane A never deletes** | Every machine still holding a file at the old path re-uploads it after a hand move. | The property that keeps footage safe. Not negotiable; the fix has to make the OTHER end move too. |

## 3. The idea: the server notices its own moves

The dashboard already walks every project's files into `nas_media` every
15 minutes (`interval_inventory`), keeping `rel_path`, `size` and
`mtime_ns` per file. A hand move is visible in that table as a plain diff
between two walks: a set of `(basename, size, mtime_ns)` that VANISHED from
one path and APPEARED at another. Nothing else on the NAS produces that
shape (a re-encode changes size and mtime; a copy leaves the source in
place; a delete has no destination). The match is exact, per file, and
needs no hashing.

So: **make the collector recognise a move, and hand it to the machinery
the MOVE button already drives.** `file_moves` and `file_move_targets`
(v29/v36) are the contract every companion since 0.9.55 already honours:
move the local copy, relink Resolve, suppress the old path in lane A,
answer `file_moves_applied`, retry until done or blocked. A detected move
is written as a `file_moves` row with `source = 'detected'` and the same
target rows as a button move, and from that moment the fleet treats the
hand move exactly as if the button had been pressed.

Three consequences fall out for free:

- **Lane A stops re-uploading** the old path on every holding machine (the
  one-day suppression the button already uses).
- **Lane B never sees a deletion**: the companion moved its copy to the new
  path before its next proxy pass, so there is nothing to trash and nothing
  to trip on.
- **Resolve keeps its links** through `resolve_bridge.replace_clip`, with the
  same save point and undo journal the button gets.

## 4. What still needs doing in the companion

Two places where the detection alone is not enough:

**4a. The race with lane B.** A lane B pass can run in the window between
the hand move and the next inventory walk (up to 15 minutes). Today that
pass trashes the local copies and, over 50 files, trips. Two fixes,
both needed:

- The breaker's relocation probe (CR-44) becomes tree-wide, by asking the
  dashboard instead of re-listing the scope: `POST /api/v1/files/locate`
  with the trashed `[basename, size]` pairs, answered from `nas_media`
  across EVERY project the dashboard has walked (one indexed query, no NAS
  I/O). The dashboard's copy of the tree is at most 15 minutes stale, so
  the answer is "found elsewhere" for a move older than the last walk, and
  "not found" otherwise; "not found" keeps today's behaviour exactly. A
  probe that cannot reach the dashboard answers 0, as now.
- When the probe says "relocated", lane B does not trash: it MOVES the local
  copy to the new relative path when the machine syncs that project (or
  will after the plan catches up), and trashes it only when it does not.
  Either way the file counts as a relocation, not a deletion, and the
  breaker does not count it.

**4b. A destination the machine does not sync.** Ruskin syncs Creator
Profiles but not FF5 Talent Gap. His copy at the old path has no new home
on his disk. The right answer is the one lane B gives today for a project
that left the plan: trash it locally (recoverable for a year), quietly,
without counting toward the breaker, because the server has told us it is
a move. The `file_move_targets` row for such a machine records `trashed
locally, destination not synced here` rather than `done`.

## 5. What the owner sees

- Nothing, in the normal case. A hand move on the NAS is followed within
  15 minutes by every machine moving its copy, and the project page's
  MOVES history shows the row with `detected` as its source, who-knows-who
  as the actor, and the machines that followed.
- If a move is only PARTLY recognisable (some files matched, some not,
  because they were re-encoded or renamed in the same session), the
  matched half is a detected move and the rest is what it is today.
- The breaker message, when it still trips, names where the files went
  when the locate call found them, and offers `[ IT WAS A MOVE, CARRY ON ]`
  which resumes the lane AND records the move so the other machines
  follow. Today the message says "needs a person to check the server" and
  gives that person nothing to check with.
- proxy_pairs (CR-267a) stops raising for a folder whose originals are
  found elsewhere by the same locate query: the finding becomes "a Proxy
  folder was left behind by a move to X" with `[ DELETE THE LEFTOVER ]`,
  which is the first-class version of what was done by hand today.

## 6. Safety rules, unchanged

- Nothing in this design deletes anything, on the server or on a machine.
  A detected move renames; a copy with no destination is trashed (a year,
  recoverable); the breaker still parks on anything that is not a match.
- A detected move is only ever a rename the server ALREADY DID. The
  collector never moves files on the NAS from a guess; it records what it
  saw and asks the machines to follow.
- The match is basename + exact size + exact mtime. CJK and NFD names go
  through `db.media_rel_key` like every other comparison (CR-90); the
  basename is compared normalised, the path a companion renames to is the
  bytes the server holds.
- Ambiguity is a refusal, not a guess: the same `(basename, size, mtime)`
  appearing at two new paths (a file copied twice, then the original
  deleted) is NOT recorded as a move; it stays a deletion for lane B and
  the breaker keeps its say.
- A machine below 0.9.55 ignores `commands.file_moves` and behaves exactly
  as today; nothing here depends on every companion being new.

## 7. Build plan, if approved

| Phase | What | Where | Size |
|---|---|---|---|
| 1 | Detection in the collector: diff consecutive `nas_media` walks per (basename, size, mtime), write `file_moves` rows (`source='detected'`) with target rows, batch a folder move into one row per folder | `dashboard/collector.py`, `db.py` (v-next: `file_moves.source`), tests | 1 builder, a day |
| 2 | `POST /api/v1/files/locate` on the fleet credential; the companion's CR-44 probe calls it before it re-lists the scope; lane B moves instead of trashing when the destination is synced here | `dashboard/api.py`, `companion/sync/lane_guard.py`, `sync/rclone_lane.py`, tests | 1 builder, a day; companion 0.9.73 |
| 3 | The breaker message names the destination and offers `[ IT WAS A MOVE, CARRY ON ]`; proxy_pairs uses locate and offers `[ DELETE THE LEFTOVER ]`; MOVES history shows detected rows | `ui.py`, templates, `invariants.py`, tests | 1 builder, half a day |

Phases 1 and 3 are dashboard-only and reach the fleet on the next
dashboard deploy; phase 2 needs a companion release and, until every
machine has it, the old machines simply keep today's behaviour. Deploy the
dashboard before the companions, as always.

## 8. What was considered and set aside

- **Raising the breaker limit.** A move of 500 files would still trip, and
  a real deletion of 49 would still not. The limit is not the problem.
- **Watching the NAS with inotify.** Faster than a 15-minute walk, but the
  container's bind mount does not deliver events for changes made over
  SMB, and a walk is what the dashboard already trusts.
- **Teaching Explorer users to use the button.** Nobody will, and the
  button cannot do a cross-project move today anyway. Making the button
  cross-project is worth doing regardless (a small phase 3 item), but it is
  not the fix.
- **Content hashing to match moved files.** Exact size + mtime is already
  unique in practice for video, and hashing 6 GB folders on every walk is
  what would make the walk too slow to keep.
