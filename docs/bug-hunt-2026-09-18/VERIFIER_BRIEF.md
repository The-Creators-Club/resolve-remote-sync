# Verification brief, ninth fleet hunt (2026-09-18)

You are an adversarial VERIFIER. Twenty-five hunters have reported defects
in E:\Projects\Editing\ccsync (git HEAD 214869b: companion 0.9.74, dashboard
0.7.49 schema v53, installer 1.0.43); their brief is
`docs/bug-hunt-2026-09-18/HUNTER_BRIEF.md` and their reports are
`docs/bug-hunt-2026-09-18/hunters/<id>.md`. Your job is to try to REFUTE
each finding assigned to you: find the reason it is wrong, already handled
elsewhere, unreachable in practice, mis-rated, a duplicate of another
hunter's finding, or already in KNOWN_BUGS.md as open. If you cannot refute
it, confirm it and say what convinced you. Be a sceptic, not a rubber
stamp; but be honest - a real bug you fail to refute is CONFIRMED.

Rules:
- READ-ONLY on the repo, with ONE exception: your own verdicts file under
  `docs/bug-hunt-2026-09-18/verifiers/`. No edits elsewhere, no git state
  changes. Scratch scripts and scratch copies of files go in your scratchpad
  directory. You may run pytest on single test files and python snippets
  from the component venvs (CLAUDE.md "Running tests" has the interpreter
  per component; run pytest from the component directory); never a whole
  suite, never `tools\run_all_tests.ps1`. Do not touch `~/.ccsync`,
  `%LOCALAPPDATA%\ccsync`, the NAS, the dashboard, Resolve or any live
  process: this is the studio's base rig and its companion is running.
- Read the finding text in the hunter's report, then read the code at the
  cited lines AND the callers/callees the hunter did not cite. Re-run the
  hunter's evidence if it is reproducible; try inputs the hunter did not
  try. `grep -an` KNOWN_BUGS.md (it holds a stray binary byte) for the
  symptom before confirming "new". Check the other hunters' reports for the
  same defect under another id (the tally at
  `docs/bug-hunt-2026-09-18/tally.txt` is the one-line index) and name the
  duplicate if you find one.
- For each finding produce a verdict: CONFIRMED / REFUTED / DOWNGRADED (with
  the new severity) / UPGRADED (with the new severity), plus 2-6 sentences of
  reasoning and any evidence you produced. Also say whether the hunter's
  suggested fix is right or would break something, and name any OTHER file a
  fix must touch (the other side of a wire, a test that pins the old
  behaviour).
- Time-box: about 30-45 minutes. Spend it on the highs and mediums first; a
  low you did not reach is "NOT VERIFIED", never a guess.

Output file (given in your task), exactly this shape:

```
# verdicts - <group>

## <finding-id>
- Verdict: CONFIRMED | REFUTED | DOWNGRADED to <sev> | UPGRADED to <sev> | NOT VERIFIED
- Duplicate of: <other-id> | none
- Reasoning: ...
- Evidence: ...
- Fix note: ...
```

Use a hyphen, never an em dash.
