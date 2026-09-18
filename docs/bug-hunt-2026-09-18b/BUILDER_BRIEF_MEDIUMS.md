# Fix-pass brief (2026-09-18b, mediums wave): a 15-MINUTE box - read this in two minutes, then build

Repo: E:\Projects\Editing\ccsync, working tree UNCOMMITTED (the whole day's
fix pass plus this evening's highs, CR-282..CR-290; `git diff` is the state).
You are ONE of fifteen builders on disjoint FILE GROUPS, each with the
confirmed MEDIUM findings listed for your group in
`docs/bug-hunt-2026-09-18b/ASSIGNMENTS_MEDIUMS.md`. Each finding's full text
is `### <id>` in `docs/bug-hunt-2026-09-18b/hunters/<report>.md`, and each
has a verifier's verdict with a Fix note under `## <id>` in
`docs/bug-hunt-2026-09-18b/verifiers/*.md`: READ THE FIX NOTE, it often
corrects the hunter's mechanism or suggested fix.

## The box
You have about 15 minutes of wall clock. Take your findings in the order
listed. A fix you cannot finish honestly inside the box goes under "Not
fixed" with one line; a half-landed fix is worse than none (that is what the
last two hunts were about). Do not start a finding you cannot finish.

## Rules (unchanged, short form)
1. Edit ONLY your group's files plus their tests. Another group's file: record
   the exact change under OWED, make your side safe alone. No git state
   changes, no version bumps, no `KNOWN_BUGS.md` edits.
2. `CLAUDE.md` invariants hold. No `scriptapp()` outside `connect()`; every
   Resolve mutation through `resolve_bridge.replace_clip` / `link_proxy_media`.
3. Every fix gets a regression test that fails before and passes after (write
   it first; watch it fail). No test that passes on the reverted source for
   another reason. Producer's real output through the receiver for a wire.
4. Run ONLY the test files you touch plus `py_compile` on every file. Never a
   whole suite.
5. Cite the id at the code site (`# dash-core-1 (2026-09-18b mediums): ...`).
   Comments explain constraints and failure modes.
6. NO EM DASHES in user-visible text.
7. A wire change tolerates the other side one release older or newer and a
   dashboard ROLLBACK; say which side deploys first.
8. Do not touch `~/.ccsync`, `%LOCALAPPDATA%\ccsync`, the NAS, the live
   dashboard, Resolve or any running process.

## Ledger (required, short)
`docs/bug-hunt-2026-09-18b/ledger/mediums-<group>.md`, house style: a
`## CR-nnn - <title> - FIXED in repo 2026-09-18 (...)` heading (your CR number
is in the assignments), one `### CR-nnnX (<id>) - <title> - FIXED (<file>)`
section per finding (three to six sentences each: what was wrong, the fix,
the test), then `### Verification` (one line per finding), `### Not fixed`,
`### OWED TO ANOTHER GROUP`, `### Deploy order`, `### Owner decisions`.
Hyphens, never em dashes. Final message: fixed / not fixed, test files to
re-run, files touched, OWED lines.
