# Verifier brief (2026-09-24): the eleventh hunt's MEDIUMS - read fully first

Repo: E:\Projects\Editing\ccsync. The eleventh hunt
(`docs/bug-hunt-2026-09-24.md`) filed 124 MEDIUM findings that nobody has
checked. You are one of a fleet of adversarial verifiers, each given a group
of them. Your job is to REFUTE each one if you can.

**Judge against HEAD, not the working tree.** Four builders are editing the
tree right now to fix the eleven highs, so read the code as
`git show HEAD:<path>` (or `git grep ... HEAD`), which is what the hunters
read. A medium that a builder's work happens to touch is still judged on HEAD.

## For each finding

1. Read its full text under `### <id>` in
   `docs/bug-hunt-2026-09-24/hunters/<hunter>.md` (the hunter is the id less
   its trailing number).
2. Read the code it cites AND its callers and callees. Check CLAUDE.md for a
   stated intent, and `KNOWN_BUGS.md` (`grep -a`) and earlier hunts
   (`docs/bug-hunt-*.md`) for an existing open, fixed or declined entry.
   Owner decisions that are NOT defects: a computer with nothing ticked is
   fine; any editor's companion may finish another editor's expired YouTube
   job.
3. Try to reproduce it: a snippet from the component venv into your
   scratchpad, or a named test that would fail. Read-only: never edit a repo
   file other than your own verdict file, never touch `~/.ccsync`, the NAS,
   the live dashboard, Resolve, or a live process, and never call
   `scriptapp()`.
4. Verdict:
   - `CONFIRMED` - real, and medium is right.
   - `UPGRADE` - real, and worse than medium (say why: data loss, security,
     fleet-wide).
   - `DOWNGRADE` - real but low (say why).
   - `REFUTED` - not a defect: the mechanism does not hold, it is guarded
     elsewhere, it is intended, or it is a duplicate of an open entry (name it).
   - `UNCERTAIN` - you could not decide; say what would decide it.
   Default to REFUTED when the mechanism does not survive reading the code.
   Also name a DUPLICATE when two findings in your group, or a finding and a
   high, are the same defect.

## Output

Write `docs/bug-hunt-2026-09-24/verifiers/<group>.md`: one section per
finding with the verdict, severity, a reason of 2-6 sentences, and the
evidence (what you ran or read). Then return the same as structured output.
Use a hyphen, never an em dash.
