# verdicts - comp-broll-tiers-res-companion

Verified against the working tree as read at 2026-09-18 (uncommitted fix pass
over 214869b). Companion venv used for the two scratch reproductions.

## comp-broll-tiers-2
- Verdict: CONFIRMED (medium stands for this hunter's own scenario; the root
  cause is a high elsewhere)
- Duplicate of: proxy-tiers-1 (high) - same unfalsifiable `size: null` row,
  same three poisoned readers; that hunter reaches it by the `busy` branch,
  this one by the abandoned poll. Both must be fixed by the same change.
- Reasoning: `broll_server.py:1176-1183` writes the intent row with
  `size=None`; `broll_standins.record` (`:404`) falls back to
  `_size_of(local_path)`, which is None because this branch only runs when the
  file is absent, so the row really is stored with `size: null`. The rewrite
  with the real size is at `:1246`, reachable only if the SAME request
  observes `STATE_DONE` - the `downloading` return at `:1188-1197` and the
  `busy` return at `:1198-1211` both leave the row as written. `_entry_is_stale`
  returns False for a non-int size unconditionally, so nothing falsifies it:
  the ledger is not consulted for size anywhere else, `pending_upgrades()`
  skips the row (its `upgrade` is None), and `_prune_locked` cannot drop it
  because the file exists. `_real_original_here` (resolve_bridge.py:2959-2976)
  therefore answers False for ever, which is exactly the `.mp4` rule
  proxy-tiers-1 was written to enforce, inverted.
- Evidence: scratch run from `companion/.venv` with HOME redirected to a temp
  dir - `record(..., size=None)`, then 100 bytes at the path, then 999999
  bytes: `after preview bytes: is_standin True is_stale False`; `after REAL
  original: is_standin True is_stale False`; `size field: None`;
  `pending_upgrades: []`. Reproduces the hunter's claim exactly, and the empty
  `pending_upgrades` shows no existing lane can repair the row.
- Fix note: the hunter's fix (stamp the observed size the first time the file
  is seen) is the right shape but must be written as a FALSIFIER, not as
  "trust the first bytes we see": stamping whatever is on disk at the moment
  `get()` runs would stamp the REAL original's size if it got there first and
  then call it a stand-in for ever. proxy-tiers-1's alternative - "size is
  None AND the file exists" reads as stale, because the intent row is only
  ever written while the file is absent - is sound and covers both hunters.
  Whatever is chosen, `broll_server.py`'s `busy` branch needs the same
  `forget()` the `state != DONE` branch has, and
  `companion/tests/test_broll_standins.py` +
  `tests/test_broll_insert_tiers.py` pin the current "non-int size is still a
  stand-in" reading (`_entry_is_stale`'s docstring says so in words), so both
  the test and the docstring have to move with the code.

## comp-broll-tiers-3
- Verdict: CONFIRMED
- Duplicate of: none (CR-284I in KNOWN_BUGS.md describes the stage-live post
  as FIXED behaviour; the failing-original interaction is not in the ledger,
  and `grep -an` finds no other entry for it)
- Reasoning: read both sides. `_pump_uploads` calls `_maybe_stage_live` at
  `broll_ingest.py:2989` before the `broken` branch, and the guard inside it
  is only "everything missing is an original", which is still true after the
  original's rclone has failed four times - so the live post goes first on the
  very tick the failure is handled. `mark_uploaded`
  (`ingest_batches.py:1216-1240`) writes `ingest_items.state = 'live'` with
  `original_uploaded = 0` and leaves `videos.original_path` NULL. `live` is in
  `ITEM_TERMINAL`, and `_check_transition` (`:852-880`) raises 400
  `illegal_transition` for `new in ITEM_ENDINGS and old in ITEM_TERMINAL`, so
  the later `_fail_item` -> `item_status(..., failed)` cannot land. `release`
  computes `done_with_errors` from `_recount`, which reads the server's own
  `ingest_items.state`, so `n_failed` is 0 and the batch releases as `done`
  with the clip shown live and no original on the NAS.
- Evidence: the four code sites above, read in full. One correction to the
  hunter: `IngestClient.item_status` (`broll_ingest.py:438-441`) logs the
  refusal at WARNING, not debug, so there IS a companion-log trace; the 400 is
  still swallowed (it returns `{}` and raises nothing) and nothing
  server-side, SPA-side or fleet-side ever learns, which is the substance of
  the finding. The batch `summary` the companion posts does carry
  `{"failed": 1}` into `ingest_batches.error`, a faint trace behind a tooltip,
  while the batch state itself still says `done`.
- Fix note: the hunter's fix is right in direction but "call `_maybe_stage_live`
  only after the broken/unknown branches" is not sufficient on its own - the
  broken branch `continue`s, so moving the call after it means a clip whose
  original is on retry 1 of 4 never stages live at all, which gives back
  CR-284I. The fix wants both halves: stage live only while the original is
  genuinely in flight (no entry in `failures`, attempts under the ceiling),
  AND a surfaced ending for an item that went live early and then lost its
  original. That second half has to be server-side: either a legal
  `live -> failed`-equivalent (a flag on the live row, not a state, since
  `release`'s "rows that already reached live STAY" rule is deliberate) or a
  notice. Files a fix must touch: `companion/src/ccsync_companion/broll_ingest.py`,
  `broll/web/app/ingest_batches.py` (`_check_transition` and/or `mark_uploaded`),
  `broll/web/tests/test_fleet_ingest.py` and
  `companion/tests/test_broll_ingest.py::test_a_clip_goes_live_when_its_proxies_land_not_when_its_original_does`,
  which pins the current unconditional early post.

## res-companion-3
- Verdict: UPGRADED to high (as a duplicate; the same code is rated high by
  the other hunter and is in the builders' hands now)
- Duplicate of: comp-broll-tiers-1 (high) - identical code
  (`broll_standins._prune_locked`), identical root cause (`_size_of` returning
  None for unreachable as well as absent), identical remedy.
- Reasoning: I could not refute it. `_size_of` (`:242-248`) catches `OSError`
  and bare `Exception` and answers None; `_prune_locked` (`:315-342`) treats
  that as "gone" for any entry older than 30 days, with no root-presence test,
  while `_entry_is_stale` (`:483-495`) reads the SAME None from the same helper
  as "the entry still stands" - the two readings sit twelve lines apart in one
  module. Worse than the hunter says in one respect: `_load_locked` early-returns
  when the file's (mtime, size) stamp is unchanged, and the ledger file lives in
  `~/.ccsync`, not on the absent drive - so the pruned view survives in memory
  for the life of the process even if nothing ever persists it, and a later
  write only makes it permanent.
- Evidence: code reading plus the reproduction under comp-broll-tiers-2 (same
  module, same venv) confirming `_size_of` is the only absence test the prune
  makes. No root guard is imported by `broll_standins.py` at all
  (`grep root_guard` in the module: nothing).
- Fix note: the hunter's fix (`os.path.isdir(parent) and not
  os.path.exists(path)`) is better than nothing but still wrong on Windows for
  an unmapped drive letter whose parent is also unreadable - it happens to fail
  safe there (isdir False, no prune), so it is acceptable; the stronger form is
  comp-broll-tiers-1's, "skip the whole prune when the archive root is not
  present". Do not fix this one separately: it is the same lines as the high,
  and `companion/tests/test_broll_standins.py`'s prune tests (which construct
  entries whose files simply do not exist, with no root at all) will need a
  present-root fixture or they will start asserting the opposite of the new
  rule.
