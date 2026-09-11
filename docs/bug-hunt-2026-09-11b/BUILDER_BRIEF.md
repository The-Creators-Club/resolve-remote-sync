# Fix-pass brief (2026-09-11b) - read fully before editing anything

Repo: E:\Projects\Editing\ccsync (git HEAD f1eeb42; companion 0.9.71,
dashboard 0.7.43 schema v52, installer 1.0.42). You are ONE builder in a fleet
of 17, each owning a disjoint FILE TERRITORY (the same territories the hunt
used; the file lists are in `HUNTER_BRIEF.md` under "Territories"). Your
findings are listed in `ASSIGNMENTS.md` under your territory; every finding's
full text (mechanism, failure scenario, evidence, suggested fix) is a `###
<id>` heading in `hunters/*.md` - lens findings (`wire-*`, `res-*`,
`security-*`, `tests-*`, `regression-*`) live in the lens's report, not your
territory's, so `grep -rn "^### <id>" docs/bug-hunt-2026-09-11b/hunters/`.
Read `docs/bug-hunt-2026-09-11b.md` "The eleven that matter most" and
"Cross-cutting patterns" first: this hunt was OF a fix pass, and most of
your findings are a same-day fix that landed half of itself, opened a
neighbour, or was pinned by a test that cannot fail. Read the previous fix
at the code site (`grep -rn <old-id>`, the id the finding names) before
changing it.

## Rules
1. Edit ONLY files in your territory plus the tests for them. `api.py` is
   dash-api's alone, `db.py` dash-db's alone, `ui.py` dash-mounts-ui's
   alone, the companion's `app.py` comp-app's alone. No `git` state changes
   (no stash/checkout/commit/reset). If a fix genuinely needs a file outside
   your territory, do NOT touch it: record exactly what is needed under
   "OWED TO ANOTHER TERRITORY" in your ledger file (file, function, the
   exact change, and which side must deploy first) and make your own side
   safe without the other half. The orchestrator routes every OWED line to
   its owner in a second wave.
2. Read `CLAUDE.md` at the repo root first; it lists the invariants.
3. Every finding gets a REGRESSION TEST that fails before the fix and passes
   after. Write the test FIRST, run it and watch it fail, then fix, then run
   it again. The tests lens found last pass's tests were mostly good and
   showed exactly how the bad ones failed: a test that passes on reverted
   source because it probes a different callable (`os.path.ismount` vs
   `posixpath.ismount`), asserts a constant, uses a timestamp that
   round-trips exactly, or monkeypatches away the gate that breaks, is not a
   regression test. For a wire finding, feed the PRODUCER's real output
   through the RECEIVER's model. Put tests in the territory's existing test
   file for that module or a new `tests/test_bug_hunt_2026_09_11b_<territory>.py`.
   Follow the conftest patterns (no live Resolve, no real Tk dialog, no
   network). The companion and onboarding suites also run on the macOS
   release runner: a test with drive letters, NFD/NFC or a Windows-only
   ctypes call must say which platform it means (`pytest.mark.skipif`) or
   stub what is absent.
4. Run ONLY the test files you added or edited, plus `py_compile` (or
   `node --check` / a PowerShell parse) on every file you touched. NEVER run
   `tools\run_all_tests.ps1`, a whole component suite, or another
   territory's tests (owner rule: the full gate runs once, centrally, after
   the last builder). Venvs are in CLAUDE.md "Running tests"; run pytest
   from the component directory.
5. At each code site, cite the finding id in the comment that explains the
   constraint (`# wire-2 (2026-09-11b): ...`), so `grep -rn <id>` finds the
   fix. Comments explain constraints, history and failure modes, never what
   the next line does.
6. NO EM DASHES in user-visible text (tray lines, popup/window copy,
   templates, SPA strings, HTTP `detail`, wizard steps). Use a hyphen with
   spaces, a colon, or two sentences. Comments and docs are exempt.
7. Do NOT bump any version number (companion `VERSION`, dashboard
   `VERSION`, `INSTALLER_VERSION`, pyproject): the orchestrator bumps them
   once at the end (dashboard 0.7.44, companion 0.9.72, installer 1.0.43).
   Do NOT edit `KNOWN_BUGS.md` directly.
8. A wire change must be tolerant of the OTHER side being one release older
   or newer: optional on read, harmless when ignored. The field today runs
   companions 0.9.65..0.9.71 (a Mac on 0.9.70) against dashboards
   0.7.34..0.7.43. Say in your ledger which side must deploy first.
9. A schema change on the dashboard DB is owned by the `dash-db` builder
   alone (next version is v53). Anyone else who needs one records it as OWED
   and ships without it.
10. Do not touch `~/.ccsync`, `%LOCALAPPDATA%\ccsync`, the NAS, the live
    dashboard or any running process: the dashboard 0.7.43 is live and the
    tray is running on this machine.
11. Time-box: roughly 45-75 minutes of work. Highs first, then mediums, then
    lows. If you cannot finish a low, say so in the ledger rather than
    half-doing it.

## Ledger entry (required)
Write `docs/bug-hunt-2026-09-11b/ledger/<territory>.md`. The orchestrator
appends it to `KNOWN_BUGS.md` under the number assigned in `ASSIGNMENTS.md`
(`CR-nnn`), so write it in that file's house style: a `## <title> (CR-nnn,
2026-09-11)` heading, then one `### CR-nnnX (<finding-id>) - <title> - FIXED
(<file>)` section per finding in the existing entries' voice (what was wrong,
why it mattered, what the fix is, where the test is). Read one recent entry
(`grep -an "^## " KNOWN_BUGS.md | tail -3`, then CR-247) for the voice. End
with:

```
### Verification
- <test file>::<test name> -> fails at f1eeb42, passes now  (one line per finding)

### OWED TO ANOTHER TERRITORY
- <territory>: <file>: <function>: <exact change>; <which side deploys first>  (or "none")

### Owner decisions
- <anything you chose that the owner might want to choose differently>  (or "none")
```

Use a hyphen, never an em dash, anywhere in the ledger. When finished, reply
with a 5-line summary: findings fixed / not fixed, tests added, OWED lines,
and anything the orchestrator must know before the gate.
