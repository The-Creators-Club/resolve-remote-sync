# Fix-pass brief (2026-09-18): the ten highs - read fully before editing anything

Repo: E:\Projects\Editing\ccsync (git HEAD 214869b; companion 0.9.74,
dashboard 0.7.49 schema v53, installer 1.0.43). You are ONE builder, fixing
the ten HIGH findings of the ninth fleet hunt, in the order the summary
gives them. Read `docs/bug-hunt-2026-09-18.md` from the top through "The ten
that matter most" and "Duplicate groups" first. Every finding's full text
(mechanism, failure scenario, evidence, suggested fix) is a `### <id>`
heading in `docs/bug-hunt-2026-09-18/hunters/<report>.md` (`grep -rn "^### <id>"
docs/bug-hunt-2026-09-18/hunters/`), and EVERY finding has an adversarial
verifier's verdict with a "Fix note" in `docs/bug-hunt-2026-09-18/verifiers/*.md`
(`grep -rn "^## <id>" docs/bug-hunt-2026-09-18/verifiers/`). Read the fix
note before touching the code: several say the hunter's suggested fix would
break something, or name a second file the fix must touch.

## The ten, in order (duplicates in brackets share the fix)

1. `comp-sync-1` [= `dash-api-1`]: `companion/.../sync/rclone_lane.py`
   `_relocate_trashed` and `dashboard/.../locate.py`. Fix BOTH ends: the
   companion drops any candidate place equal to the path it just trashed the
   file from (§4a "found ELSEWHERE"); the dashboard's locate join excludes
   projects whose `nas_inventory_state` is flagged unreadable (`last_error`
   non-empty) or stale (`walked_at` older than a few collector intervals),
   and carries the excluded slugs in the answer so the companion's log can
   say the server could not tell. Each side must be safe with the other side
   one release older: the companion's own-path exclusion must work against
   a 0.7.49 dashboard, and the dashboard's exclusion must not break a 0.9.74
   companion's parse of the answer.
2. `res-companion-2`: `rclone_lane.py` `_relocate_trashed` (the hand-move
   follow) plus `file_moves.py` / the companion `app.py`. When lane B renames
   a local copy to follow a server move, it must leave the evidence the later
   `file_moves` command needs: either write the intent row (`STATE_APPLYING`)
   so `apply_move`'s resume branch relinks, or relink Resolve itself through
   the existing `_relink_moved_result` path. The verifier notes lane B only
   relocates `**/Proxy/**`; make the fix cover exactly what lane B moves.
3. `comp-broll-tiers-1` [= `res-companion-1`]: `broll_server.py`
   `fetch_standin`: record the ledger intent BEFORE the fetch starts (or from
   the job's own completion, not the polling request). The existing test at
   `companion/tests/test_broll_insert_tiers.py:288` pins the WRONG behaviour
   (`assert broll_standins.all() == []`): change that assertion to the right
   one and add the "page stops polling, job finishes" test.
4. `comp-resolve-1`: `resolve_bridge.replace_clip` and
   `proxy_relink.apply_relinks`. Read the verifier's fix note in
   `verifiers/comp-ui-resolve.md` FIRST: a bare `force=` flag makes the
   after-read success test vacuous (`after == norm_new` is always true) and
   would write a no-op undo-journal entry. The refresh must (a) actually call
   `ReplaceClip`, (b) verify by geometry (`Frames` / resolution), not by
   `File Path`, (c) take the save point only when it really mutates, and
   (d) not burn an `allow_automatic` grant on a refresh that changes
   nothing. Test with the REAL default `replace_fn` against a fake media pool
   item.
5. `comp-resolve-2` [= `res-companion-3`]: `proxy_relink._geometry_disagrees`.
   Ask the cheap question first: only probe a clip whose stand-in ledger
   says `is_stale` (exists, uncalled) or whose stored geometry disagrees with
   a header-only probe (`ffprobe -show_streams`, no `-count_packets`); persist
   a per-(path, size, mtime) verdict across passes so an agreeing clip is
   never asked twice. Keep the media-tree heartbeat honest if a probe is
   still needed (stamp it per clip, not per pass). Do NOT "fix" it by
   probing only ledgered clips: on the wired rig the ledger is empty by
   construction (proxy-tiers-4), and that would disable the feature.
6. `dash-api-2` [= `dash-db-3` = `dash-core-2`]: `dashboard/.../app.py`
   `unhandled_error`'s busy branch (and the `record_server_error` branch
   below it). Record off the event loop (`run_in_threadpool`) with a short
   busy timeout (`db.connect` already takes `busy_ms`), or coalesce in
   memory and let the collector flush. The 503 answer itself must never wait
   on the database.
7. `res-fleet-1`: `dashboard/.../app.py:~736` boot gate. Start the pinned
   executor and run `release_pinned_jobs()` unconditionally when Timeline
   Cards is mounted (the pool builds engines lazily; `available()` at boot is
   always false). Fix the untrue boot log line. Make DDIAG-6's
   `_check_jobs_pinned_no_executor` see a `pinned` row with no live executor
   thread. Add a lifespan test.
8. `dash-cards-1`: `cards_tunnel.cards_agent_pending`. Honour the `wait`
   long-poll on the "no engine for this editor" path (sleep up to `seconds`,
   waking early if an engine appears for that editor), dashboard-only so it
   needs no companion release. Leave `dash-cards-8` (companion side) alone;
   it is not in scope.
9. `wire-1`: `broll_ingest._pump_uploads`. Give the non-200/non-409 branch
   real accounting: a 4xx is terminal (fail the item with the server's
   `reason`, release its share of the batch), a 5xx/connection error is
   retried with the 409 branch's attempt counter and `MAX_UPLOAD_ATTEMPTS`.
   `wire-2` (the mount answering 500 for a busy DB) is NOT in scope; make
   sure a 500 from that path is retried, not treated as terminal.
10. `ytdl-web-1`: `ytdl/web/tests/test_api.py:470`. Derive the fresh and
    stale versions from the clock (`date.today() - timedelta(days=1)` and
    `days=config.YTDLP_MAX_AGE_DAYS + 1`), so the test pins the rule, not a
    calendar date. Check the rest of the tree for another literal date
    compared against `today()`.

## Rules
1. Edit only what a fix needs. No `git` state changes (no stash, checkout,
   commit, reset). Do NOT bump any version number and do NOT edit
   `KNOWN_BUGS.md`: the orchestrator does both after verifying.
2. Read `CLAUDE.md` at the repo root first; it lists the invariants. Every
   Resolve mutation goes through `resolve_bridge.replace_clip` /
   `link_proxy_media`; never call `scriptapp()` outside `connect()`.
3. Every finding gets a REGRESSION TEST that fails before the fix and passes
   after. Write the test FIRST, run it, watch it fail, fix, run it again. A
   test that passes on the reverted source because it probes a different
   callable, asserts a constant, or monkeypatches away the gate that breaks,
   is not a regression test. For a wire finding, feed the PRODUCER's real
   output through the RECEIVER. Put tests in the existing test file for the
   module or in `tests/test_bug_hunt_2026_09_18_<component>.py`. Follow the
   conftest patterns (no live Resolve, no real Tk dialog, no network). The
   companion suite also runs on the macOS release runner: a test with drive
   letters or Windows-only calls must `skipif` or stub.
4. Run ONLY the test files you added or edited, plus `py_compile` on every
   file you touched. NEVER run `tools\run_all_tests.ps1` or a whole
   component suite (owner rule: the full gate runs once, centrally, by the
   orchestrator after you finish). Venvs are in CLAUDE.md "Running tests";
   run pytest from the component directory.
5. At each code site, cite the finding id in the comment that explains the
   constraint (`# comp-sync-1 (2026-09-18): ...`) so `grep -rn <id>` finds
   the fix. Comments explain constraints, history and failure modes, never
   what the next line does.
6. NO EM DASHES in user-visible text (tray lines, popup copy, templates,
   SPA strings, HTTP `detail`). Comments and docs are exempt.
7. A wire change must tolerate the other side being one release older or
   newer: optional on read, harmless when ignored. Say in the ledger which
   side must deploy first.
8. Do not touch `~/.ccsync`, `%LOCALAPPDATA%\ccsync`, the NAS, the live
   dashboard, Resolve or any running process: this is the studio's base rig
   and its companion is running.
9. Time-box: roughly 90-120 minutes. If a fix cannot be finished honestly,
   say so in the ledger rather than half-doing it; a half-landed fix is the
   exact shape the last two hunts were about.

## Ledger entry (required)
Write `docs/bug-hunt-2026-09-18/ledger/highs.md` in `KNOWN_BUGS.md`'s house
style: a `## <title> (CR-282, 2026-09-18)` heading, then one `### CR-282X
(<finding-id>) - <title> - FIXED (<file>)` section per finding (A..J) in the
existing entries' voice (what was wrong, why it mattered, what the fix is,
where the test is). Read CR-278 and CR-281 in `KNOWN_BUGS.md` (`grep -an`,
the file holds a stray binary byte) for the voice. End with:

```
### Verification
- <test file>::<test name> -> fails at 214869b, passes now  (one line per finding)

### Deploy order
- <which side first, and why>  (or "either")

### Owner decisions
- <anything you chose that the owner might want to choose differently>  (or "none")
```

Use a hyphen, never an em dash, anywhere in the ledger. When finished, reply
with a summary: findings fixed / not fixed, tests added, files touched, and
anything the orchestrator must know before running the gate.
