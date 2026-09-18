# Fix-pass brief (2026-09-18, second wave): the mediums and lows - read fully before editing anything

Repo: E:\Projects\Editing\ccsync (companion 0.9.75, dashboard 0.7.50 in the
tree, both unshipped; git HEAD 214869b plus the UNCOMMITTED first wave, which
fixed the ten highs as CR-282A..J - `git diff` shows it, `docs/bug-hunt-2026-09-18/ledger/highs.md`
explains it, and you build ON it, never around it). You are ONE of FOUR
builders, each owning a disjoint FILE GROUP named in
`docs/bug-hunt-2026-09-18/ASSIGNMENTS.md`, which also lists your findings in
priority order (mediums first). Every finding's full text is a `### <id>`
heading in `docs/bug-hunt-2026-09-18/hunters/<report>.md`
(`grep -rn "^### <id>" docs/bug-hunt-2026-09-18/hunters/`), and every one has
an adversarial verifier's verdict with a "Fix note" in
`docs/bug-hunt-2026-09-18/verifiers/*.md` (`grep -rn "^## <id>"`). READ THE
FIX NOTE FIRST: several say the hunter's suggested fix would break something,
name the second file a fix must touch, or corrected the hunter's line number
or mechanism. A finding the verifier DOWNGRADED still gets fixed; one it
REFUTED is not in your list. The summary `docs/bug-hunt-2026-09-18.md`
("Other verdicts worth reading") has the cross-cutting notes.

## Rules (the first wave's rules, plus the territory rule)
1. Edit ONLY files in your group plus their tests. If a fix genuinely needs a
   file in another group, do NOT touch it: record exactly what is needed under
   "OWED TO ANOTHER GROUP" in your ledger (file, function, the exact change,
   which side deploys first) and make your own side safe without the other
   half. The orchestrator routes every OWED line to its owner afterwards. No
   `git` state changes (no stash, checkout, commit, reset). Do NOT bump any
   version number and do NOT edit `KNOWN_BUGS.md`.
2. Read `CLAUDE.md` at the repo root first; it lists the invariants. Every
   Resolve mutation goes through `resolve_bridge.replace_clip` /
   `link_proxy_media`; never call `scriptapp()` outside `connect()`.
3. Every finding gets a REGRESSION TEST that fails before the fix and passes
   after. Write the test first, run it, watch it fail, fix, run it again. A
   test that passes on the reverted source because it probes a different
   callable, asserts a constant, or monkeypatches away the gate that breaks,
   is not a regression test. For a wire finding, feed the PRODUCER's real
   output through the RECEIVER. Put tests in the existing test file for the
   module or in `tests/test_bug_hunt_2026_09_18_<group>.py`. Follow the
   conftest patterns (no live Resolve, no real Tk dialog, no network). The
   companion and onboarding suites also run on the macOS release runner: a
   test with drive letters or Windows-only calls must `skipif` or stub.
4. Run ONLY the test files you added or edited, plus `py_compile` (or
   `node --check` / a PowerShell parse) on every file you touched. NEVER run
   `tools\run_all_tests.ps1` or a whole component suite (owner rule: the full
   gate runs once, centrally, after the last builder). Venvs are in CLAUDE.md
   "Running tests"; run pytest from the component directory; the `server/`
   suite from Git Bash.
5. At each code site, cite the finding id in the comment that explains the
   constraint (`# dash-cards-2 (2026-09-18): ...`) so `grep -rn <id>` finds
   the fix. Comments explain constraints, history and failure modes, never
   what the next line does.
6. NO EM DASHES in user-visible text (tray lines, popup copy, templates, SPA
   strings, HTTP `detail`, wizard steps). Comments and docs are exempt.
7. A wire change must tolerate the other side being one release older or
   newer: optional on read, harmless when ignored. The field runs companions
   0.9.65..0.9.74 against dashboards 0.7.34..0.7.49; the whole studio fleet
   is on 0.9.74 / 0.7.49. Say in the ledger which side deploys first.
8. A schema change on the dashboard DB belongs to the `dashboard` builder
   alone (next version is v54). Anyone else records it as OWED.
9. Do not touch `~/.ccsync`, `%LOCALAPPDATA%\ccsync`, the NAS, the live
   dashboard, Resolve or any running process: this is the studio's base rig
   and its companion is running.
10. Time-box: roughly 90-150 minutes. Mediums first, in the order listed,
    then lows. If you cannot finish a low honestly, say so in the ledger
    under "Not fixed" with one line of reason rather than half-doing it; a
    half-landed fix is the exact shape the last two hunts were about.

## Ledger entry (required)
Write `docs/bug-hunt-2026-09-18/ledger/<group>.md` in `KNOWN_BUGS.md`'s
house style: a `## CR-28n - <title> - FIXED in repo 2026-09-18 (...)` heading
(your CR number is in ASSIGNMENTS.md), then one `### CR-28nX (<finding-id>)
- <title> - FIXED (<file>)` section per finding, lettered in list order, in
the existing entries' voice (what was wrong, why it mattered, what the fix
is, where the test is). Read CR-282 in `KNOWN_BUGS.md` (`grep -an "^## CR-282"`;
the file holds a stray binary byte) for the voice. End with:

```
### Verification
- <test file>::<test name> -> fails before the fix, passes now  (one line per finding)

### Not fixed
- <id>: <one line why>  (or "none")

### OWED TO ANOTHER GROUP
- <group>: <file>: <function>: <exact change>; <which side deploys first>  (or "none")

### Deploy order
- <which side first, and why>  (or "either")

### Owner decisions
- <anything you chose that the owner might want to choose differently>  (or "none")
```

Use a hyphen, never an em dash, anywhere in the ledger. When finished, reply
with a summary: findings fixed / not fixed, tests added, files touched, OWED
lines, and anything the orchestrator must know before running the gate.
