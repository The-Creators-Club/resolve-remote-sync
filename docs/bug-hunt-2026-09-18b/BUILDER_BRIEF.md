# Fix-pass brief (2026-09-18b): the twelve highs - read fully before editing anything

Repo: E:\Projects\Editing\ccsync. git HEAD 214869b; the WORKING TREE holds the
whole day's fix pass UNCOMMITTED (`git diff`; companion 0.9.75 / dashboard
0.7.50 schema v54 in the tree; ledgers in `docs/bug-hunt-2026-09-18/ledger/`,
`KNOWN_BUGS.md` CR-282..CR-286). You are ONE of FOUR builders, each owning a
disjoint FILE GROUP, fixing the HIGH findings of the tenth hunt
(`docs/bug-hunt-2026-09-18b.md`, "The twelve that matter most"; full text
under `### <id>` in `docs/bug-hunt-2026-09-18b/hunters/<report>.md`). These
findings are about TODAY'S fixes: read the morning's ledger section each one
cites (`grep -rn "<original-id>" docs/bug-hunt-2026-09-18/ledger/`) and the
code comment at the site (`grep -rn "<original-id>"`) before touching it, and
build ON today's fix, never around it. Thirteen verifiers are reading the
same tree for the mediums at the same time; that is fine, they are read-only.

## Groups and findings (in fix order)

**companion-core** (companion `file_moves.py`, `app.py`, `sync/*`, `tray*.py`,
and their tests; ledger `docs/bug-hunt-2026-09-18b/ledger/highs-companion-core.md`, CR-287):
1. `comp-sync-1`: an EMPTY plan (`_synced_project_rels` -> `[]`) must read as
   "cannot tell" and take the pre-4b path (move normally, no trash), never as
   "syncs nothing". Decide what the 4b branch may trust: a plan with at least
   one entry, or an explicit "managed and empty" signal, and say which.
2. `comp-sync-2` = `res-companion-1`: the 4b intent row must not carry the
   trash path into the completion row (`record()` carries paths forward when
   `paths` is falsy), and `moved_to()` must skip `not_synced_here` as it skips
   `applying`, so RES-10 never offers a relink into `.ccsync-trash`.
3. `comp-app-1`: `_note_dashboard_version` must FORGET on an absent key (its
   own docstring's contract) so a dashboard rollback stops the state word
   within one report; test the rollback direction.
4. `res-companion-2`: the file-move ledger has two writer threads (lane and
   reporter) and no lock; one lock around mutate+`_save()`, and a per-process
   unique tmp name or the lock covering the tmp.

**companion-media** (companion `proxy_relink.py`, `resolve_bridge.py`,
`broll_standins.py`, `broll_server.py`, `broll_ingest.py`, `broll_fetch.py`,
`watcher.py`, their tests; ledger `highs-companion-media.md`, CR-288):
5. `comp-resolve-1` = `regression-1`: the geometry verdict must be written and
   read under ONE key. Key it on the openable spelling in both places (or
   note it under both), and add a test whose canonical and local spellings
   differ (a fake `exists`/`_openable_path` seam), which is the case every
   macOS editor is in.
6. `proxy-tiers-1`: the pre-fetch intent row must be retired on `STATE_BUSY`
   (nothing started) and must never be unfalsifiable: give a `size=None` row
   an expiry (a fetch that has not finished within N hours is not a
   stand-in) or record the intent only once the download has actually
   started, and make the real original arriving at that path falsify it.
7. `comp-broll-tiers-1`: the 30-day prune must not read "cannot stat" as
   "gone": check the tree root is present (`root_guard` / `drive_swap`
   answer it) and skip the prune entirely when it is not.
8. `wire-1`: the two-stage `/uploaded` must not make the item terminal while
   the original is still going up. Prefer the companion-side fix (do not
   post the first stage through a route that writes `live`; or post it with
   a state the server treats as non-terminal) and record the server change
   as OWED to webapps-tools if the route must learn a new word; an original
   whose upload fails after the clip is visible must be reported, retryable,
   and visible on the batch.

**dashboard** (everything under `dashboard/`; ledger `highs-dashboard.md`, CR-289):
9. `dash-db-1` = `res-fleet-1` = `dash-api-1`: `mark_file_move_applied`,
   `mark_resolve_undo_applied` and `_file_move_answer` must match on the row's
   own `target_machine` (the name the offer carried, which the companion
   echoes) or on every name `command_machine_names` returns; test the answer
   to a command filed under a former hostname.
10. `dash-db-2`: `command_machine_names` must include only QUIET former names
    (no report in the last N minutes, or the row's `last_seen` older than the
    reporting row's), never a second live twin; test the cloned-disk case
    SYS-18a leaves behind.
11. `dash-collector-alerts-1`: cross-cycle pairing must not produce a
    `FILE_MOVE_DONE` command from two passes on `(basename, size, mtime_ns)`
    alone. Either require corroboration (the vanish and the arrival within
    one walk of each other AND no other file of that key anywhere else in
    the tree, AND the source project's own walk since the vanish confirming
    it stayed gone) or downgrade the cross-cycle pair to a NOTICE for an
    admin to confirm through the existing move button. Say which and why.

**webapps-tools** (`broll/`, `music/`, `ytdl/`, `server/`, `tools/`,
`installer/`, `onboarding/`; ledger `highs-webapps-tools.md`, CR-290):
12. `broll-indexer-1`: the cheap frame check may only SKIP the source count
    when the proxy count equals the source's estimate exactly AND the source
    count is then confirmed, or simpler: always count the source once per
    original (cache it per (path, size, mtime)) and compare exactly, keeping
    `frames_match`'s one-rule invariant; a 1-2 frame short proxy must be
    refused by both indexer producers.
    Plus any server half `companion-media` owes you for wire-1.

## Rules (the day's rules, unchanged)
1. Edit ONLY files in your group plus their tests. A fix that needs another
   group's file: record it under "OWED TO ANOTHER GROUP" with the exact
   change, make your side safe alone, and the orchestrator routes it. No
   `git` state changes. Do NOT bump version numbers and do NOT edit
   `KNOWN_BUGS.md`.
2. Read `CLAUDE.md` first. Every Resolve mutation goes through
   `resolve_bridge.replace_clip` / `link_proxy_media`; never `scriptapp()`
   outside `connect()`.
3. Every finding gets a REGRESSION TEST that fails before the fix and passes
   after; write it first, watch it fail. Not a test that passes on the
   reverted source for another reason. For a wire finding, feed the
   producer's real output through the receiver. Follow the conftest patterns
   (no live Resolve, no real Tk, no network); the companion suite also runs
   on the macOS release runner.
4. Run ONLY the test files you added or edited plus `py_compile` on every
   file you touched. Never a whole suite (the gate runs once, centrally).
5. Cite the finding id at the code site (`# comp-sync-1 (2026-09-18b): ...`).
   Comments explain constraints and failure modes, never the next line.
6. NO EM DASHES in user-visible text.
7. A wire change must tolerate the other side one release older or newer,
   in both directions, and must survive a dashboard ROLLBACK (today's
   lesson). Say which side deploys first.
8. Do not touch `~/.ccsync`, `%LOCALAPPDATA%\ccsync`, the NAS, the live
   dashboard, Resolve or any running process.
9. Time-box: roughly 60-90 minutes. Do not half-land a fix; if one cannot be
   finished honestly, say so under "Not fixed".

## Ledger entry (required)
Write your ledger file (named above) in `KNOWN_BUGS.md`'s house style: a
`## CR-28n - <title> - FIXED in repo 2026-09-18 (...)` heading, one
`### CR-28nX (<finding-id>) - <title> - FIXED (<file>)` section per finding
in list order, then:

```
### Verification
- <test file>::<test name> -> fails before the fix, passes now

### Not fixed
- <id>: <why>  (or "none")

### OWED TO ANOTHER GROUP
- <group>: <file>: <function>: <exact change>; <which side deploys first>  (or "none")

### Deploy order
- ...

### Owner decisions
- ...  (or "none")
```

Use a hyphen, never an em dash. When finished, reply with: findings fixed /
not fixed, tests added, files touched, OWED lines, and anything the
orchestrator must know before the gate.
