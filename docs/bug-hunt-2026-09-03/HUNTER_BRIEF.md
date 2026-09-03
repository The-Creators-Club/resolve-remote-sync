# Bug hunt brief (2026-09-03) — read fully before touching the code

Repo: E:\Projects\resolve-remote-sync (git HEAD 097f5a3, companion 0.9.64,
dashboard 0.7.27). You are ONE hunter in a fleet of 17; each hunter owns a
disjoint TERRITORY of files. Hunt only inside yours; if you notice a defect
outside it while following a call, record it under "OUT OF TERRITORY" at the
bottom with one line, do not chase it.

## Rules
1. READ-ONLY. Do NOT edit, create or delete any file inside the repo. No
   `git` commands that change state (no stash/checkout/commit/reset). You may
   run the territory's pytest suite and ad-hoc python snippets that import the
   code, from the component's venv (see CLAUDE.md "Running tests"); write any
   scratch script to your scratchpad directory, never into the repo.
2. Read `CLAUDE.md` at the repo root FIRST (it lists the invariants the code
   is supposed to hold, each of which is a bug if violated), then skim
   `SPEC.md` for the parts your territory implements, then the docs it names.
3. `KNOWN_BUGS.md` (10k lines) is the ledger through CR-101. Before reporting,
   `grep -n` the ledger for the function / file / symptom; if it is already
   recorded as OPEN, cite the id and do not re-describe it; if it is recorded
   as FIXED and you find it is NOT actually fixed, that IS a finding (say
   "regression of CR-nn"). Prior hunts: docs/bug-hunt-2026-08-21.md,
   docs/bug-hunt-2026-08-14.md, docs/bug-hunt-2026-08-11.md.
4. Hunt for REAL DEFECTS, not style: wrong logic, off-by-one, races,
   unhandled exceptions on realistic input, resource leaks, state that is
   not persisted when CLAUDE.md says it must be, security holes (auth
   bypass, path traversal, token leakage into logs/responses, missing
   fail-closed), cross-platform breakage (Windows/macOS/Linux, NFC/NFD, CRLF,
   drive letters, path separators), version-compare bugs with two-digit
   minors (0.9.64 vs 0.10.0), schema-migration hazards, API contract
   mismatches between companion <-> dashboard <-> web apps (compare both
   sides of every wire format you see), tests that assert the wrong thing or
   that a bug would not catch, and CLAUDE.md invariants that the code does
   not actually enforce. Also: user-visible copy with an em dash (owner rule)
   in tray/popup/template/SPA/HTTP-detail strings.
5. VERIFY before you claim. Read the callee, not just the call. Trace the
   actual data flow. Where feasible, prove it with a small python snippet
   from the venv or by pointing at a test that would fail. State your
   confidence honestly. A finding you could not verify is marked PLAUSIBLE,
   not CONFIRMED. Do not pad: five confirmed defects beat twenty guesses.
6. Read the tests in your territory too: a test that pins the wrong
   behaviour, or that mocks away the exact thing that breaks, is a finding.
7. Time-box: aim to finish in about 25-40 minutes of work. Prioritise the
   files CLAUDE.md talks about most and the code paths that touch data,
   money, or the fleet.

## Output
Write your report to the file named in your task (under the scratchpad
`findings/` directory), Markdown, in EXACTLY this shape so the orchestrator
can merge them mechanically:

```
# <territory-id> — <one-line scope>
Files read (with approximate coverage): ...
Tests run: <command> -> <result>   (or "none")

## Findings

### <territory-id>-1 — <short title>
- Severity: high | medium | low
- Confidence: CONFIRMED | PLAUSIBLE
- Where: <path>:<line> (repo-relative, plus a second location if two-sided)
- What: <the defect in 1-3 sentences, mechanism not symptom>
- Failure scenario: <concrete input/state -> concrete wrong outcome>
- Evidence: <what you ran / read that proves it; snippet output if any>
- Ledger: <"new" | "regression of CR-nn" | "related to CR-nn (open)">
- Suggested fix: <one or two sentences>

### <territory-id>-2 — ...

## Coverage note
<what you did NOT get to, and what the suite does not cover>

## OUT OF TERRITORY
- <path>: <one line>
```

Severity guide: high = data loss, sync of the wrong thing, security, fleet-wide
outage, the dashboard/tray dying; medium = a feature wrong for some real
input or platform, a bad state the user cannot clear, misleading UI that
causes a wrong action; low = edge case, cosmetic, hygiene with a real but
small consequence.
