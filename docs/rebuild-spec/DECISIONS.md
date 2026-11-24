# The decision list (step 4 of the rebuild plan)

Stays behind: under the purge rule this file is never shown to the session
that rebuilds the product. Only the owner's answers, restated as what the
product does, reach the specification. The plan is
[`../REBUILD_PLAN.md`](../REBUILD_PLAN.md).

Questions are put to the owner a page at a time. Each has what exists
today, the options, a recommendation and what the choice changes for a
person. An answer he gave in a past session is shown with its date, not
asked again.

## Page 1: what can be switched on and off (asked and ANSWERED 2026-11-13)

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

**The owner, 2026-11-13: "I'll accept all the recommendations."** So every
recommendation in the table is his decision. Restated as what the product
does, for the specification:

- A site can switch five things on and off, each by itself: the b-roll
  archive (client folders included), music, YouTube downloads, Timeline
  Cards (footage in, the board, the editor and the hand-over, as one), and
  camera cards with the Footage Sorter.
- The help for the editing program is a sixth switch, on by default. With
  it off nothing mentions that program, and b-roll, music and Timeline
  Cards offer exports instead of sending to it.
- Making proxies on editors' computers and sharing heavy work across the
  computers are always available, each with its per-computer setting
  (and, for shared work, its per-kind setting).
- One site-wide switch turns the assistant off. Everything else still
  works, and no assistant control is left on screen.
- Mail alerts, the weekly report and the daily health report are settings
  of the always-on part.
- A part that is switched off is visible to nobody except an admin, in
  settings, listed with its switch.

## Page 2: where you ruled two ways at different times (asked 2026-11-13, ANSWERED 2026-11-24)

These come from the knowledge base. In each, an earlier ruling of yours and
a later one (or a later report) point different ways, and the dates alone
did not settle which you want. The recommendation is the later position
unless something argues against it.

| # | Question | Earlier | Later | Recommendation |
|---|---|---|---|---|
| 1 | Inserting a music cue at a point where a music clip is already playing: make room for it, or refuse? | Insert was to make room | Making room cut clips in half, so it was changed to refuse before touching anything | **Refuse, and offer "place it on the track below" in the same message.** Nothing on the timeline is ever cut by a music insert |
| 2 | A project ticked "upload only" on a computer: does its empty folder structure come down, so the editor can see where originals go? | You wanted the folders, as places to put originals | A report that upload-only filled the local folder with empty folders, fixed so that nothing comes down | **Nothing comes down.** The editor's own folders go up as they are made. Say if you want the structure after all |
| 3 | Quitting or updating the app while a file is uploading: stop the upload, or let it finish? | Not ruled; the app sometimes left the old upload running beside a new one | The rule became "never two uploads of one file" | **Quitting stops it and it picks up where it left off next time. An update waits for the file in flight, up to a limit, then does the same.** No progress is thrown away |
| 4 | The sync drive comes back under a different name (macOS sometimes adds a number): carry on, or pause with instructions? | The same drive should resume under any name | A numbered remount pauses, with instructions | **Carry on when it is provably the same drive**, whatever it is called; pause only when the product cannot tell. Fewer manual steps, same safety |
| 5 | The Footage Sorter moving originals into their final folders: does each move still wait for an admin's approval? | Yes: a dry run, then one clip, then everything, each approved | Clips dropped in should now process on their own, with a manual override | **Keep the approval for moves of originals.** Sorting is proposed on its own, and one approval sends it. "Runs on its own" was about preparing interviews for Timeline Cards, not about moving originals |
| 6 | Montages: may they use the studio news anchors' link lines? | No: an early montage excluded them | "Montages are always and ONLY downloaded material - newsreaders, coverage, etc." | **Yes, newsreaders' lines are in.** Only the film's own interviews are out |
| 7 | A cut sent to Resolve: are markers placed on the timeline? | No markers | Later you asked for section markers and gap-note markers | **Yes: sections and gap notes become markers.** Nothing else is marked. (This is about markers only. By your separate ruling a noted gap long enough to hold one also arrives as on-screen text, and that stays either way) |

Reply with the numbers you disagree with; anything not mentioned is taken
as the recommendation.

**ANSWERED 2026-11-24** (asked one by one, he chose each):

- 1: the recommendation. A music insert where music is already playing is
  refused, with "place it on the track below" offered.
- 2: **against the recommendation.** A project ticked "upload only" DOES
  bring its empty folder structure down, so the editor sees where
  originals go. Nothing else comes down.
- 3: the recommendation. Quitting stops an upload and it carries on where
  it left off; an update waits for the file in flight up to a limit.
- 4: the recommendation. A sync drive that comes back under another name
  carries on when it is provably the same drive.
- 5: **against the recommendation.** The Footage Sorter moves originals
  into their final folders on its own, with no approval, and a person can
  overrule by hand afterwards.
- 6: the recommendation. Montages may use the newsreaders' lines; only the
  film's own interviews are out.
- 7: the recommendation. Sections and gap notes become markers. (A noted
  gap long enough also arrives as on-screen text, by his separate ruling.)

Asked the same day: every Footage Sorter control is usable by touch, on a
phone as at a desk. He confirmed ("Yes, all by touch").

Not asked, because the rule holds either way: about 385 lessons marked
still open, outcome not found, or fixed but never shipped (listed in
`knowledge-base/_owner/QUESTIONS.md`). Each stands as a rule the rebuild
must meet unless you say one is no longer wanted. Sixteen factual
disagreements were settled from the code and the record
(`knowledge-base/_owner/SETTLED_BY_EVIDENCE.md`).

## Pages 3 to 30: the questions that came out of writing the specification (written and ANSWERED 2026-11-24)

354 questions on pages 3 to 29, gathered from the 27 writers of the
specification by `python docs/rebuild-spec/tools/build_decisions.py` (it
never writes over a page that holds answers), and 14 more on page 30,
written by hand. Each writer folded the readers' questions on the same
point into one, so nothing is asked twice within a page; the same point can
still come up on two pages where two parts of the product share it, and
those are marked when the pages are put to him. One page per piece of the
specification, each in two halves: **choices** (two forms of one thing that
behave differently, an either-or, a change the lessons or his requirements
ask for) in full, then **tidy-ups** (one thing reachable from several
places, the same job built twice, things switched off for everyone, things
nobody can reach, builders' tools) as a table. The specification is already
written to each recommendation, with a "Pending" mark on the passage; where
the recommendation is to cut something, the passage is still there, ready
to delete.

He answers a page by naming the numbers he disagrees with. An answer is
typed into that page under "Your answers", starting with the word ANSWERED
and the date, and the passage in the specification is then changed and its
Pending mark removed.

| Page | About | Choices | Tidy-ups | State |
|---|---|---|---|---|
| 3 | [The whole product](decisions/page-03-whole-product.md) | 6 | 4 | ANSWERED 2026-11-24 |
| 4 | [Sync, part 1](decisions/page-04-sync-1.md) | 17 | 4 | ANSWERED 2026-11-24 |
| 5 | [Sync, part 2](decisions/page-05-sync-2.md) | 0 | 3 | ANSWERED 2026-11-24 |
| 6 | [The dashboard, part 1](decisions/page-06-dashboard-1.md) | 4 | 13 | ANSWERED 2026-11-24 |
| 7 | [The dashboard, part 2](decisions/page-07-dashboard-2.md) | 6 | 5 | ANSWERED 2026-11-24 |
| 8 | [The app on each editor's computer](decisions/page-08-editor-app.md) | 8 | 11 | ANSWERED 2026-11-24 |
| 9 | [Accounts, privacy and the legal paperwork](decisions/page-09-accounts-privacy-legal.md) | 9 | 9 | ANSWERED 2026-11-24 |
| 10 | [Releases and updates](decisions/page-10-releases-and-updates.md) | 4 | 9 | ANSWERED 2026-11-24 |
| 11 | [The server: installing it and keeping it running, part 1](decisions/page-11-server-install-and-running-1.md) | 8 | 13 | ANSWERED 2026-11-24 |
| 12 | [The server: installing it and keeping it running, part 2](decisions/page-12-server-install-and-running-2.md) | 4 | 2 | ANSWERED 2026-11-24 |
| 13 | [Work shared out across the computers](decisions/page-13-fleet-jobs.md) | 4 | 8 | ANSWERED 2026-11-24 |
| 14 | [Proxies and file moves](decisions/page-14-proxies-and-file-moves.md) | 2 | 1 | ANSWERED 2026-11-24 |
| 15 | [Resolve on the editor's computer](decisions/page-15-resolve-on-the-editors-computer.md) | 5 | 7 | ANSWERED 2026-11-24 |
| 16 | [The b-roll archive](decisions/page-16-broll.md) | 16 | 12 | ANSWERED 2026-11-24 |
| 17 | [Music](decisions/page-17-music.md) | 3 | 4 | ANSWERED 2026-11-24 |
| 18 | [YouTube downloads](decisions/page-18-youtube.md) | 9 | 12 | ANSWERED 2026-11-24 |
| 19 | [The Footage Sorter and camera cards, part 1](decisions/page-19-footage-sorter-and-camera-cards-1.md) | 15 | 11 | ANSWERED 2026-11-24 |
| 20 | [The Footage Sorter and camera cards, part 2](decisions/page-20-footage-sorter-and-camera-cards-2.md) | 7 | 4 | ANSWERED 2026-11-24 |
| 21 | [The Footage Sorter and camera cards, part 3](decisions/page-21-footage-sorter-and-camera-cards-3.md) | 5 | 1 | ANSWERED 2026-11-24 |
| 22 | [Timeline Cards: footage in, ready to cut](decisions/page-22-cards-footage-in.md) | 8 | 0 | ANSWERED 2026-11-24 |
| 23 | [Timeline Cards: the board](decisions/page-23-cards-board.md) | 7 | 1 | ANSWERED 2026-11-24 |
| 24 | [Timeline Cards: the editor, part 1](decisions/page-24-cards-editor-1.md) | 8 | 6 | ANSWERED 2026-11-24 |
| 25 | [Timeline Cards: the editor, part 2](decisions/page-25-cards-editor-2.md) | 8 | 6 | ANSWERED 2026-11-24 |
| 26 | [Timeline Cards: the editor, part 3](decisions/page-26-cards-editor-3.md) | 9 | 1 | ANSWERED 2026-11-24 |
| 27 | [Timeline Cards: the editor, part 4](decisions/page-27-cards-editor-4.md) | 4 | 9 | ANSWERED 2026-11-24 |
| 28 | [Timeline Cards: the editor, part 5](decisions/page-28-cards-editor-5.md) | 5 | 8 | ANSWERED 2026-11-24 |
| 29 | [Timeline Cards: the hand-over to Resolve, and exports](decisions/page-29-cards-to-resolve-and-exports.md) | 4 | 5 | ANSWERED 2026-11-24 |
| 30 | [What only he can answer](decisions/page-30-open-points.md): points neither the writers nor the code could settle, places where the code differs from what the specification assumed, the assistant's name on screen, the client page's look, Rust | 14 | 0 | ANSWERED 2026-11-24 |

**ANSWERED 2026-11-24.** Page 3 and most of page 4 he answered one by one;
then, of everything still waiting: "accept all the recommendations." Each
page records it. Against the recommendation: 3.9 (the subscription way of
running the assistant stays, off by default) and 4.6 ("Resume downloads" is
still offered after a low-disk pause). Held back by me and put to him
again: 5.2 (see that page). The same message added a requirement of his
own, now in `spec/OWNER_REQUIREMENTS.md`: the rebuild tests the real speed
of every way of syncing, with the studio's remote editor and with computers
in other countries.

| 31 | [What came up while the answers were applied](decisions/page-31-after-the-answers.md): live editing of Resolve from the cards confirmed cut; no wait before the Sorter moves a clip; no fixed share of the assistant's budget for work that runs on its own; "Same loudness" levels to the clips in the cut | 4 | 0 | ANSWERED 2026-11-24 |
| 32 | [What the pieces disagreed about](decisions/page-32-the-joins.md): does a new computer wait for approval; a question your notes name playing in the cut; the fillers reading aid; sorted interviews reaching Timeline Cards by themselves; who makes a full-quality download link; whether a file move ever lapses; the shortening review | 7 | 7 | written 2026-11-24, NOT YET ASKED |

Still to add: a page pruning settings
nobody would feel (303 were written; some only tune machinery).
