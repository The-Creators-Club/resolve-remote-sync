# Bug hunt brief, eleventh fleet hunt (2026-09-24) - read fully before touching the code

Repo: E:\Projects\Editing\ccsync. git HEAD is `63d4290` (dashboard 0.7.56 /
companion 0.9.77), working tree CLEAN. This is a whole-repo hunt, not a hunt
of one fix pass: every component (companion, dashboard, broll, music, ytdl,
server, installer, onboarding, tools, bench) is in scope. Three waves run at
the same time, each with its own question:

- **Wave 1, `bug-*`: BUGS.** Code that does the wrong thing: wrong logic,
  off-by-one, races, unhandled exceptions on realistic input, resource leaks,
  state not persisted when CLAUDE.md says it must be, security holes (auth
  bypass, path traversal, token leakage, missing fail-closed), cross-platform
  breakage (NFC/NFD, CRLF, drive letters, separators), version compares with
  two-digit minors, schema-migration hazards, wire mismatches between
  companion, dashboard and the web apps (read BOTH sides), resilience holes
  (NAS gone mid-call, disk full, killed between two writes, container
  restart, DB locked, None from an older build, a thread dying with nothing
  to restart it, "green while dead"), and tests that a bug would not fail.
- **Wave 2, `logic-*`: LOGICAL ERRORS AND USABILITY.** Code that does what it
  was written to do, but the design or the rule is wrong for the person using
  it: a rule that contradicts another rule or a CLAUDE.md invariant, a state
  machine with a state you cannot leave, a check that can never fire or always
  fires, a count that counts the wrong thing, a decision taken on the wrong
  key (person vs computer, path vs normalised key), a flow where the editor or
  admin cannot tell what happened or what to do next, a refusal that does not
  name its next action, a warning that cries wolf, a default that surprises,
  a step that makes a non-technical owner (see memory: Alex is
  non-technical) guess. Owner decisions that are NOT findings: a computer
  with nothing ticked is fine (never an error anywhere); any editor's
  companion may finish another editor's expired YouTube job.
- **Wave 3, `ui-*`: UI PROBLEMS.** What a person sees: broken or misaligned
  layout, desktop AND phone widths (390 px), overflow, unreadable contrast,
  dark-theme holes, stale or contradictory state on screen, buttons that do
  nothing or give no feedback, missing loading/empty/error states, htmx swaps
  that lose focus or scroll, accessibility (labels, keyboard, focus rings),
  inconsistent vocabulary between surfaces, and ANY em dash in user-visible
  text (owner rule; comments/docs/logs exempt). Read templates, CSS and JS
  together; where a page can be rendered from a test client or a static file
  in the venv, render it and look.

You own ONE territory. Hunt inside it; a defect you notice outside while
following a call goes under "OUT OF TERRITORY" as one line.

## Rules
1. READ-ONLY. Do NOT edit, create or delete any file inside the repo, with
   ONE exception: your own report at
   `docs/bug-hunt-2026-09-24/hunters/<territory-id>.md`. No git commands that
   change state. You may run the tests that exercise your files and ad-hoc
   snippets from the component's venv (CLAUDE.md "Running tests" names the
   interpreter; `server/` from Git Bash). Scratch files go to your scratchpad,
   never the repo. Do NOT run `tools\run_all_tests.ps1` or another
   territory's whole suite. Do not touch `~/.ccsync`,
   `%LOCALAPPDATA%\ccsync`, the NAS, the live dashboard, Resolve, or any live
   process: this machine is the studio's base rig and its companion is
   running. Never call `scriptapp()`.
2. Read `CLAUDE.md` at the repo root first (each invariant it states is a
   finding if the code violates it), then the parts of `SPEC.md` and `docs/`
   your territory implements.
3. `KNOWN_BUGS.md` (grep with `-a`; it holds a stray binary byte) is the
   ledger through CR-321. Before reporting, grep it for the function, file or
   symptom. An OPEN entry is cited, not re-described; a FIXED entry you find
   still broken IS a finding ("regression of CR-nn"). Earlier hunts live in
   `docs/bug-hunt-*.md` and their folders; do not re-report a finding that is
   recorded there as open or declined.
4. VERIFY before you claim. Read the callee, trace the data, and where
   feasible prove it with a snippet or name the test that would fail. An
   unverified finding is PLAUSIBLE, not CONFIRMED. Do not pad: five confirmed
   defects beat twenty guesses. Style nits are not findings.
5. Time-box about 30-45 minutes.

## Output
Write your report to `docs/bug-hunt-2026-09-24/hunters/<territory-id>.md` in
this shape, AND return the same findings as structured output:

```
# <territory-id> - <one-line scope>
Files read (approximate coverage): ...
Tests/probes run: ... (or "none")

## Findings

### <territory-id>-1 - <short title>
- Severity: high | medium | low
- Confidence: CONFIRMED | PLAUSIBLE
- Where: <path>:<line> (repo-relative; a second location if two-sided)
- What: <the defect, mechanism not symptom, 1-3 sentences>
- Failure scenario: <concrete input/state -> concrete wrong outcome>
- Evidence: <what you ran or read that proves it>
- Ledger: new | regression of CR-nn | related to CR-nn (open)
- Suggested fix: <one or two sentences>

## Coverage note
<what you did not get to>

## OUT OF TERRITORY
- <path>: <one line>
```

Severity: high = data loss, syncing the wrong thing, security, a fleet-wide
outage, the dashboard or tray dying, an editor's Resolve project damaged, a
deploy that breaks the fleet in the documented order, a UI that leads a
person to a destructive wrong action; medium = a feature wrong for some real
input or platform, a state the user cannot clear, misleading UI, a failure
nobody is told about; low = edge case, cosmetic, small hygiene.

Use a hyphen, never an em dash, in your report.
