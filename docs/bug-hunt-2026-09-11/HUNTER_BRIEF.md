# Bug hunt + resilience brief (2026-09-11) - read fully before touching the code

Repo: E:\Projects\resolve-remote-sync (git HEAD 40f931a, companion 0.9.70,
dashboard 0.7.42, installer 1.0.41). You are ONE hunter in a fleet of 19;
each hunter owns a disjoint TERRITORY of files (two cross-cutting hunters
own a LENS instead, see below). Hunt only inside yours; if you notice a
defect outside it while following a call, record it under "OUT OF
TERRITORY" at the bottom with one line, do not chase it.

Seventh fleet hunt. The previous one (2026-09-03, `docs/bug-hunt-2026-09-03.md`)
found 84 defects at 097f5a3 and every one was fixed the same day as
CR-102..CR-119. Since then 36 commits landed about 50,000 changed source
lines (the usability/resilience sweep waves 0-5, CR-145..CR-186; the
Timeline Cards mount and jobs scheduler work; CR-187..CR-232). NEW CODE IS
WHERE THE BUGS ARE: `git log --oneline 097f5a3..HEAD -- <your files>` and
`git diff 097f5a3..HEAD -- <your files>` tell you what changed in your
territory; read those diffs with particular care, then the rest.

## Rules
1. READ-ONLY. Do NOT edit, create or delete any file inside the repo, with
   ONE exception: your own report file under `docs/bug-hunt-2026-09-11/hunters/`.
   No `git` commands that change state (no stash/checkout/commit/reset). You
   may run your territory's pytest suite and ad-hoc python snippets that
   import the code, from the component's venv (see CLAUDE.md "Running
   tests"); write scratch scripts to your scratchpad directory, never into
   the repo. Do NOT run `tools\run_all_tests.ps1` or any other territory's
   suite (owner rule: the full gate runs once, centrally, at the end).
2. Read `CLAUDE.md` at the repo root FIRST (it lists the invariants the code
   is supposed to hold, each of which is a bug if violated), then skim
   `SPEC.md` for the parts your territory implements, then the docs it names.
3. `KNOWN_BUGS.md` (16k lines, grep with `-a`, it contains a stray binary
   byte) is the ledger through CR-232. Before reporting, `grep -an` the
   ledger for the function / file / symptom; if it is already recorded as
   OPEN, cite the id and do not re-describe it; if it is recorded as FIXED
   and you find it is NOT actually fixed, that IS a finding (say "regression
   of CR-nn"). Prior hunts: docs/bug-hunt-2026-09-03.md (and its
   hunters/ dir for the shape of a good report), docs/bug-hunt-2026-08-21.md,
   docs/USABILITY_RESILIENCE_SWEEP_2026-09-03.md, docs/RESILIENCE_SWEEP_2026-08-28.md.
4. Hunt for REAL DEFECTS, not style: wrong logic, off-by-one, races,
   unhandled exceptions on realistic input, resource leaks, state that is
   not persisted when CLAUDE.md says it must be, security holes (auth
   bypass, path traversal, token leakage into logs/responses, missing
   fail-closed), cross-platform breakage (Windows/macOS/Linux, NFC/NFD, CRLF,
   drive letters, path separators), version-compare bugs with two-digit
   minors (0.9.70 vs 0.10.0), schema-migration hazards (the dashboard is at
   schema v50+; a migration that cannot run twice, or on a DB from the last
   shipped 0.7.34 build, is a finding), API contract mismatches between
   companion <-> dashboard <-> web apps (compare BOTH sides of every wire
   format you see; a field one side sends and the other ignores, or a
   version gate that reads the wrong version), tests that assert the wrong
   thing or that a bug would not catch, and CLAUDE.md invariants that the
   code does not actually enforce. Also: user-visible copy with an em dash
   (owner rule) in tray/popup/template/SPA/HTTP-detail strings.
5. RESILIENCE is half of this hunt. For every path that touches the disk,
   the network, a subprocess, a database or another machine, ask: what
   happens when the NAS is unreachable mid-call, the disk is full, the
   process is killed between two writes, the container restarts, the DB is
   locked, the clock is wrong, the other side is one release older or newer
   (dashboard 0.7.34 with companion 0.9.70, or dashboard 0.7.42 with
   companion 0.9.65 - both are real fleet states today), a file is
   half-written, a value is None because a report from an older build did
   not carry it, or an exception escapes a thread and nothing restarts it.
   "Green while dead" (a status that stays OK after the thing it describes
   stopped), a safety latch that is in-memory only, a retry loop with no
   backoff or no ceiling, a background thread with no supervisor, and a
   failure that is logged but never surfaced to the person who must act, are
   all findings. Read the resilience-sweep docs for the standard the code is
   held to.
6. VERIFY before you claim. Read the callee, not just the call. Trace the
   actual data flow. Where feasible, prove it with a small python snippet
   from the venv or by pointing at a test that would fail. State your
   confidence honestly. A finding you could not verify is marked PLAUSIBLE,
   not CONFIRMED. Do not pad: five confirmed defects beat twenty guesses.
7. Read the tests in your territory too: a test that pins the wrong
   behaviour, or that mocks away the exact thing that breaks, is a finding.
8. Time-box: aim to finish in about 30-45 minutes of work. Prioritise the
   diff since 097f5a3, the files CLAUDE.md talks about most, and the code
   paths that touch data, the fleet, or an editor's Resolve.

## Output
Write your report to `docs/bug-hunt-2026-09-11/hunters/<territory-id>.md`,
Markdown, in EXACTLY this shape so the orchestrator can merge them
mechanically:

```
# <territory-id> - <one-line scope>
Files read (with approximate coverage): ...
Tests run: <command> -> <result>   (or "none")

## Findings

### <territory-id>-1 - <short title>
- Severity: high | medium | low
- Confidence: CONFIRMED | PLAUSIBLE
- Where: <path>:<line> (repo-relative, plus a second location if two-sided)
- What: <the defect in 1-3 sentences, mechanism not symptom>
- Failure scenario: <concrete input/state -> concrete wrong outcome>
- Evidence: <what you ran / read that proves it; snippet output if any>
- Ledger: <"new" | "regression of CR-nn" | "related to CR-nn (open)">
- Suggested fix: <one or two sentences>

### <territory-id>-2 - ...

## Coverage note
<what you did NOT get to, and what the suite does not cover>

## OUT OF TERRITORY
- <path>: <one line>
```

Severity guide: high = data loss, sync of the wrong thing, security, fleet-wide
outage, the dashboard/tray dying, an editor's Resolve project damaged;
medium = a feature wrong for some real input or platform, a bad state the
user cannot clear, misleading UI that causes a wrong action, a failure
nobody is told about; low = edge case, cosmetic, hygiene with a real but
small consequence.

Use a hyphen, never an em dash, in your report.
