# Whole-product audit brief (2026-11-10) - read fully before touching the code

The owner asked: "Examine this entire product, including timeline cards and
footage sorter modules, for issues, inefficiencies, ways to improve
performance, memory leaks, examine it from every angle", and then added: "look
into potential ways to make the code more efficient, make deploying more
efficient, streamline the whole thing".

Twelve earlier fleet hunts looked for BUGS, logic errors and UI problems. This
one is different on purpose: its first questions are **performance, wasted
work, leaks and streamlining**. Correctness bugs still count, most of all in
code written since the last hunt (2026-10-06), but a report that is only a
bug list has missed the brief.

## The four trees

| Tree | Path | State |
|---|---|---|
| CC Sync | `E:\Projects\Editing\ccsync` | HEAD `6b5c0c6`, companion 0.9.90 / dashboard 0.7.79, clean |
| Timeline Cards (the LIVE page at `/cards`) | `E:\Projects\Editing\Resolve\MulticamPipeline` (inside the `E:\Projects\Editing` repo, HEAD `78f0bb0`) | clean |
| Timeline Cards, the REBUILT editor (`/cards/edit`, not released) | `C:\Users\alex\AppData\Local\Temp\claude\tc-standalone\Resolve\MulticamPipeline\editor` (branch `standalone-editor`, `3dcf3b6`) | ANOTHER SESSION'S LIVE WORKTREE, edited today. Read only. No `npm`, no build, no test run inside it. |
| Footage Sorter (the `/sorter` mount) | `E:\Projects\Editing\footage-sorter` (nested repo, branch `sorter-dashboard-module`, `abe2539`) | clean. What ships to the NAS is `footage_sorter/` (Python) + `public/` only; `server.js`, `lib/` are the older Node server; `ingest/tray/*.ps1` and `mover.ps1` run on Windows machines |

Scale to reason with: today's fleet is 4 editor machines + 1 TrueNAS
container, about 100 projects, tens of thousands of media files per project
tree, a b-roll index of about 5,000 clips, cut lists of hundreds of cards.
The product is going commercial (open beta), so also ask what happens at 20
machines / 500 projects / 500k files. The companion runs for weeks without a
restart on an editor's machine beside DaVinci Resolve, which needs the CPU,
the GPU and the RAM more than we do. The dashboard is one uvicorn process in
one container with SQLite.

## What to look for (in this order)

1. **PERFORMANCE and WASTED WORK.** Work repeated every cycle that could be
   cached or skipped (full tree walks, re-hashing, re-parsing a file that did
   not change, re-reading config, re-spawning a subprocess per item); O(n^2)
   or worse over files, projects, cards or rows; N+1 SQL, a query with no
   usable index, a commit per row, a full-table read to count; blocking I/O
   or `subprocess` inside an `async def` on the event loop; a lock held
   across network or disk I/O; polling where an event exists, or polling far
   faster than the thing changes; payloads that carry everything every time;
   JSON re-serialised in a loop; work done at import or boot that most runs
   never need (startup time); frontend: layout thrash, a whole list
   re-rendered for one change, unthrottled scroll/pointer/resize handlers,
   huge DOM, no caching headers, a fetch per row, assets re-downloaded.
2. **LEAKS and UNBOUNDED GROWTH.** In memory: module- or instance-level
   dict/list/set/deque keyed by something that keeps arriving (path, job id,
   session, machine, request) with no eviction; `lru_cache` on a method or
   with unbounded keys; threads started and never joined or one per event;
   `Popen` whose pipes are never drained or closed; file handles, sockets,
   SQLite connections, HTTP responses not closed on the error path; Tk /
   GDI / PyObjC objects; closures or tracebacks pinning big structures. In
   the browser: `addEventListener` with no removal on re-render, `setInterval`
   / `requestAnimationFrame` never cancelled, observers never disconnected,
   object URLs never revoked, `AudioContext` / media elements / decoded
   audio buffers kept, WebSocket reconnects that stack handlers, Maps that
   cache per card or per clip forever, detached DOM kept by a closure. On
   disk: logs with no rotation, state / journal / trash / tmp / `.partial`
   files nothing prunes, DB tables nothing prunes, caches with no cap.
3. **IDLE COST.** With nothing to do, what does this process still do every
   second / minute / hour: CPU wakeups, disk walks, subprocess spawns,
   network calls, DB writes, log lines? Name the cadence and the cost.
4. **BUGS**, weighted to code newer than 2026-10-06 (the Footage Sorter and
   its mount, field backup / card copy / TeraCopy / ledger, the `/cards/edit`
   supervisor and proxy, CR-381..CR-383, fixed card readers) and to the three
   non-ccsync trees, which earlier fleet hunts mostly did not read: wrong
   logic, races, unhandled errors on realistic input, data loss, security
   (auth bypass, path traversal, secret leakage, missing fail-closed),
   cross-platform breakage, wire mismatches (read BOTH sides), resilience
   holes (NAS gone mid-call, disk full, killed between two writes, restart
   mid-operation, a thread that dies with nothing to restart it).
5. **STREAMLINING.** Only where it costs something real (time, risk, bytes
   shipped, or a class of bug): the same logic implemented twice and able to
   drift (name both copies and whether they HAVE drifted); dead code, dead
   flags, dead routes, dead files still shipped; a file so large or a
   function so long that it is where bugs keep landing; a dependency that
   could go; a step in a deploy / release / test flow that is slow, manual,
   repeated or could be skipped safely. Give the saving (lines, seconds,
   megabytes, steps). "This could be refactored" with no saving is not a
   finding.

Each recommendation must be SAFE under the repo's stated invariants. Read
`CLAUDE.md` at the top of your tree first: a great deal of what looks like
waste or duplication there is a deliberate answer to an incident, and says
so with a date or a CR number. Proposing to remove one of those is a wasted
finding; proposing a cheaper way to keep the same guarantee is a good one.

## Rules

1. READ-ONLY. Do NOT edit, create or delete any file in any of the four
   trees, with ONE exception: your own two report files (below). No git
   command that changes state. No `npm install`, no build.
2. This machine is the studio's base rig and its companion is RUNNING. Do
   not touch `~/.ccsync`, `%LOCALAPPDATA%\ccsync`, the NAS (`P:`, `W:`, SSH),
   the live dashboard, Resolve, or any live process. Never call
   `scriptapp()`. Do not bind ports 1144, 8384, 8765, 8801, 8899 or 22000.
3. Probes are welcome and make a finding much stronger: a `timeit` of the
   function on a synthetic 50k-file tree, `EXPLAIN QUERY PLAN` against the
   real schema built in a temp DB, `tracemalloc` across 1,000 calls, a count
   of listeners after 100 re-renders in a headless page, `python -X
   importtime`. Run them from the component's own venv (ccsync `CLAUDE.md`,
   "Running tests", names each interpreter) with every file under YOUR
   scratch folder: `C:\Users\alex\AppData\Local\Temp\claude\0821e15b7e474fe8\33581ba8-e460-4553-81c2-83b2208b6619\scratchpad\<your-id>\`.
   You may run a single test file that exercises your code. Do NOT run a
   whole suite, `tools\run_all_tests.ps1`, or the Cards `run_all.py` gate.
4. Do not re-report what is already known. In ccsync: `KNOWN_BUGS.md` (grep
   with `-a`; never edit it) and `docs/bug-hunt-*.md`,
   `docs/PRELAUNCH_REVIEW_2026-10-06.md` + `docs/prelaunch-review-2026-10-06/`.
   Grep them for your function, file or symptom before reporting. An OPEN
   entry is cited in one line, not re-described; a FIXED entry you find still
   broken IS a finding. Cards: `GOTCHAS.md` and `docs/` in MulticamPipeline;
   the editor's own `PERF.md`, `ARCHITECTURE.md`, `PARITY.md`. Sorter:
   `SPEC.md`, `INGEST.md`, `docs/`.
5. Owner decisions that are NOT findings: a computer with nothing ticked is
   fine; any editor's companion may finish another editor's expired YouTube
   job; subagent-run Claude features cost money by design; the Cards engine
   pool refuses a third engine rather than evicting.
6. QUANTIFY. Every perf / leak / idle / streamlining finding states (a) how
   often the code runs, (b) what n is today and at commercial scale, and (c)
   the cost, MEASURED where you could and labelled "estimated" where you
   could not. A finding with no multiplier is not a finding. Do not pad: six
   proven findings beat twenty guesses. Style nits are not findings.
7. You own ONE territory. Hunt inside it; something you notice outside it
   goes under "OUT OF TERRITORY" as one line. Time-box about 45 minutes.

## Output

Write TWO files into `E:\Projects\Editing\ccsync\docs\audit-2026-11-10\hunters\`:

**`<your-id>.md`**

```
# <your-id> - <one-line scope>
Files read (approximate coverage): ...
Probes run: ... (or "none")

## Findings

### <your-id>-1 - <short title>
- Category: perf | leak | idle | disk-growth | bug | concurrency | security | resilience | streamline | deploy
- Severity: high | medium | low
- Confidence: CONFIRMED | PLAUSIBLE
- Where: <path>:<line> (path relative to its tree; name the tree if not ccsync)
- What: <the mechanism, 1-3 sentences>
- Cost / failure scenario: <how often x how big = what it costs; or concrete input -> concrete wrong outcome>
- Evidence: <what you measured or read that proves it>
- Ledger: new | regression of CR-nn | related to CR-nn (open)
- Suggested change: <one or two sentences, and what it must not break>
- Effort / risk: S | M | L effort; low | medium | high risk of the change itself

## What is already good
<two to five lines: things in this territory that are efficient or well
bounded and should be left alone, so nobody "optimises" them>

## Coverage note
<what you did not get to>

## OUT OF TERRITORY
- <path>: <one line>
```

**`<your-id>.json`** - the same findings, machine readable: a JSON array of
objects with exactly these keys: `id`, `title`, `category`, `severity`,
`confidence`, `where`, `what`, `cost`, `evidence`, `ledger`, `fix`,
`effort`, `risk`. Valid JSON, UTF-8, no trailing commas.

Severity: **high** = data loss, syncing the wrong thing, security, the
dashboard or tray dying or wedging, an editor's Resolve project damaged, a
leak or growth that takes a long-running process down or fills a disk within
weeks of normal use, a hot path that visibly stalls an editor's machine or
the dashboard at TODAY's scale; **medium** = a real, measurable cost at
today's scale (seconds per cycle, hundreds of MB, minutes per deploy), a
leak that needs months, a cliff that arrives at commercial scale, a feature
wrong for some real input, a failure nobody is told about; **low** = small
saving, edge case, hygiene.

Use a hyphen, never an em dash, in your report.

Your FINAL MESSAGE back is short: a tally line (`high N / medium N / low N`),
then one line per finding (`id | severity | category | title`), then at most
three lines on what you could not cover. The detail lives in your files.
