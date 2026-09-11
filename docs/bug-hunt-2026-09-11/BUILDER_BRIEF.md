# Fix-pass brief (2026-09-11) - read fully before editing anything

Repo: E:\Projects\resolve-remote-sync (git HEAD 40f931a, companion 0.9.70,
dashboard 0.7.42, installer 1.0.41). You are ONE builder in a fleet of 16,
each owning a disjoint FILE TERRITORY. The hunt is in
`docs/bug-hunt-2026-09-11/hunters/<territory>.md` (every finding, all
severities) and the adversarial verdicts on every high and medium are in
`docs/bug-hunt-2026-09-11/verifiers/*.md` (`grep -n "^## <finding-id>"`).
The verdict OVERRIDES the hunter where they differ: read its "Fix note",
it often names a second file the fix must touch, or a suggested fix that
would break something. Nothing was refuted, so every finding in your list
is to be fixed, low ones included. A low that was DOWNGRADED because the
scenario is narrow still gets its fix; keep it small.

## Rules
1. Edit ONLY files in your territory (listed in your task) plus the tests
   for them. Two builders may share a large file (`db.py`, `api.py`) on
   DISJOINT functions named in the task: in that case use the Edit tool
   only, never Write on an existing file, and re-read the region before
   each edit. No `git` state changes (no stash/checkout/commit/reset). If a
   fix genuinely needs a file outside your territory, do NOT touch it:
   record exactly what is needed under "OWED TO ANOTHER TERRITORY" in your
   ledger file and fix your own side so it is safe without the other half.
2. Read `CLAUDE.md` at the repo root first; it lists the invariants. Then
   read your hunter report and every verdict for your findings in full.
3. Every finding gets a REGRESSION TEST that fails before the fix and
   passes after. Write the test FIRST, run it and see it fail, then fix,
   then run it again. Put it in the territory's existing test file for that
   module, or a new `tests/test_bug_hunt_2026_09_11_<territory>.py`. A test
   that mocks away the very thing that breaks is not a regression test.
   Follow the conftest patterns (no live Resolve, no real Tk dialog, no
   network).
4. Run ONLY the test files you added or edited, plus `py_compile` (or
   `node --check` / PowerShell parse) on every file you touched. NEVER run
   `tools\run_all_tests.ps1`, a whole component suite, or another
   territory's tests (owner rule: the full gate runs once, centrally, after
   the last builder). Venvs are in CLAUDE.md "Running tests".
5. At each code site, cite the finding id in the comment that explains the
   constraint (`# comp-sync-2 (2026-09-11): ...`), so `grep -rn <id>` finds
   the fix. Comments explain constraints, history and failure modes, never
   what the next line does.
6. NO EM DASHES in user-visible text (tray lines, popup/window copy,
   templates, SPA strings, HTTP `detail`, wizard steps). Use a hyphen with
   spaces, a colon, or two sentences. Comments and docs are exempt.
7. Do NOT bump any version number (companion `VERSION`, dashboard
   `VERSION`, `INSTALLER_VERSION`, pyproject): the orchestrator bumps them
   once at the end. Do NOT edit `KNOWN_BUGS.md` directly.
8. A wire change (a new field on a report, a command, a fleet route body)
   must be tolerant of the OTHER side being one release older or newer:
   optional on read, harmless when ignored. Say in your ledger which side
   must deploy first if it matters.
9. A schema change on the dashboard DB is owned by the `dash-api-jobs`
   builder alone (next version is v52). Anyone else who needs one records it
   as OWED and ships without it.
10. Time-box: finish in roughly 45-75 minutes of work. Do the highs first,
    then mediums, then lows. If you cannot finish a low, say so in the
    ledger rather than half-doing it.

## Ledger entry (required)
Write `docs/bug-hunt-2026-09-11/ledger/<territory>.md`. The orchestrator
appends it to `KNOWN_BUGS.md` under the number assigned in your task
(`CR-nnn`), so write it in that file's house style: a `## <title> (CR-nnn,
2026-09-11)` heading, then for each finding id a short paragraph in the
existing entries' voice (what was wrong, why it mattered, what the fix is,
where the test is). Read the tail of `KNOWN_BUGS.md` (`grep -an "^## " |
tail`, then read one recent entry such as CR-232) for the voice. End with:

```
### Verification
- <test file>::<test name> -> fails at 40f931a, passes now  (one line per finding)

### OWED TO ANOTHER TERRITORY
- <file>: <what and why>  (or "none")

### Owner decisions
- <anything you chose that the owner might want to choose differently>  (or "none")
```

Use a hyphen, never an em dash, anywhere in the ledger.
