# The decision list (step 4 of the rebuild plan)

Stays behind: under the purge rule this file is never shown to the session
that rebuilds the product. Only the owner's answers, restated as what the
product does, reach the specification. The plan is
[`../REBUILD_PLAN.md`](../REBUILD_PLAN.md).

Questions are put to the owner a page at a time. Each has what exists
today, the options, a recommendation and what the choice changes for a
person. An answer he gave in a past session is shown with its date, not
asked again.

## Page 1: what can be switched on and off (asked 2026-11-13, not yet answered)

This page comes first because the specification's shape hangs on it: each
thing that can be switched on and off becomes its own document.

### Already decided (2026-11-12), shown for confirmation

- **Syncing is always on.** "sync is core to dashboard and the companion."
  It is never something a site can switch off.
- **One program on each editor's computer.** Every optional part is built
  into it and can be switched on or off, but the program updates as a
  whole, not part by part.
- **One home for all the code**, with a self-contained, separately
  versioned folder for each optional part. Switching a part off hides it
  and stops its work; it never deletes anything.

### Questions

| # | Question | Today | Recommendation | What it changes for a person |
|---|---|---|---|---|
| 1 | Which things can a site switch on and off by itself? | B-roll, music, Timeline Cards and YouTube downloads can each be absent; the Footage Sorter is a separate program | Five: **b-roll archive**, **music**, **YouTube downloads**, **Timeline Cards**, **camera cards and the Footage Sorter** | A customer who only wants syncing sees none of the five; each is one switch in settings |
| 2 | Is Timeline Cards one switch or several? | The board, footage processing and the editor are separate tools | **One switch.** Footage in, the board, the editor and the hand-over to Resolve go on and off together | No half-working state, such as an editor with nothing feeding it |
| 3 | Are client folders (the links handed to clients) part of b-roll or their own switch? | Part of b-roll | **Part of b-roll** | One fewer switch; a site without b-roll has no client links |
| 4 | Is the Resolve help a switch? (Noticing missing media, relinking, the fix-all, shared LUTs and stills, "send to Resolve") | Always on | **Its own switch, on by default.** You asked for the product to work with other editing programs later; a studio on another program switches this off and later switches on the one for its program | With it off, nothing mentions Resolve; b-roll, music and Timeline Cards still work but offer exports instead of "send to Resolve" |
| 5 | Is making proxies on editors' computers a switch? | A setting per computer | **Always available, with the per-computer setting kept.** Proxies coming down is the founding purpose of syncing | Nothing changes |
| 6 | Is sharing heavy work across the computers a switch? (Transcribing, making proxies and previews on whichever computer is free) | A setting per computer, plus per kind of work | **Always available, with the per-computer and per-kind settings kept.** Timeline Cards and b-roll both lean on it | An editor can still keep their laptop out of it |
| 7 | Can the assistant be switched off for a whole site? | Each assistant feature depends on whether a key is set | **One site-wide switch.** With it off, everything else still works and every assistant button is gone, not broken | A customer who must not send footage text to an outside service has one switch to prove it |
| 8 | Are alerts by mail, the weekly report and the daily health report switches? | Settings, off for customers by default | **Settings of the always-on part, not separate parts** | Nothing changes |
| 9 | When a part is off, who can see that it exists? | Mixed: some show a greyed tab, some vanish | **Nobody sees it except an admin in settings**, where it is listed with its switch | Editors never meet a dead tab |

Reply with the numbers you disagree with; anything not mentioned is taken
as the recommendation.
