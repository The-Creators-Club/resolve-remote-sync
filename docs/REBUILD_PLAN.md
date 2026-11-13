# The clean rebuild: what we are doing, where it stands, how to resume

Written 2026-11-12. This is the hand-over note for the work started that
day. Paste the "To resume" text at the bottom into a new Claude Code session
in `E:\Projects\Editing\ccsync` to carry on.

## What the owner wants

In his words, 2026-11-12:

- "I believe ccsync may be extremely bloated."
- "The point of this is for a completely fresh instance of claude to look at
  the feature list and start a complete rebuild of the whole project, without
  having any bias as to how the original architecture was built. I imagine
  there is a lot of frankenstein patches on patches as I was designing as I
  built, so I want a completely clean rebuild of the whole thing."
- "Would it be possible to build it in rust?"
- "This rebuild should include footage sorter, too."
- Added later the same day: "all the real-world user feedback which was
  gathered and worked on through various sessions, for example all the
  changes that were made today based on real world behaviour, needs to be in
  the final document. ... I want to make sure that every thing that was found
  and reported and fixed makes it into the rebuild document so that none of
  those bugs have to be re-discovered and re-fixed. It should be like a
  knowledge base."
- Also 2026-11-12: "For the rebuild, I also want every individual component
  to be a module which lives inside its own codebase and slots into the
  dashboard, so each one can be maintained, updated, enabled and disabled
  individually."
- Also 2026-11-12, about Timeline Cards: "Timeline cards doesn't need Google
  translate or Claude translate any more because it does the translation and
  word matching and then auto picks the English from the Span. The workflow
  should support no obsidian, so just dragging clips in and they auto
  process, this is for potential clients down the line so it's NLE-agnostic.
  They should also thus be able to make multicams and with automation. The
  whole pipeline should be automated, from dragging in to transcription to
  translation and word timing etc." See "Timeline Cards in the rebuild:
  footage in, ready to cut", below.

## The guiding principle: elegance

The owner, 2026-11-12: "For this rebuild - the keyword is elegance. We go for
the most elegant option with the least moving parts every time, to achieve
the desired functionality. This is the guiding principle for the whole
operation."

It governs every choice in this plan, in the briefing pack and in the rebuild
itself, and it goes at the top of the specification in his words. How it is
applied:

- **It decides HOW, never WHAT.** What the product does is the owner's to
  decide (step 4). Elegance never removes a feature, a ruling of his, or a
  lesson from real use; it removes mechanisms. Every kind 1 to 3 rule in the
  knowledge base still has to hold.
- **The test for any part:** take it away. If everything the product must do
  can still be done, it goes.
- **A design in which a failure cannot happen beats a mechanism that catches
  it.** Most of the old build's machinery was added one failure at a time.
  The rebuild is given the failures (the knowledge base) and asked for the
  fewest parts that meet all of them at once, not for one guard each.
- **One way to do each thing**: one channel for telling a computer something,
  one place a setting comes from, one way to publish a build. Where the
  inventory shows several, the specification describes the one, and step 4
  asks only where choosing changes what a person can do.
- **Every recommendation in step 4 is the option with the fewest moving
  parts** that still does the job, and says which parts it removes.
- **Engineering questions are never put to the owner and never written
  into the pack.** How many engines, which tools, which processes: the fresh
  instance answers those itself from the principle, knowing nothing of what
  the old build chose. (An earlier draft of this plan listed three such
  questions, each naming an old mechanism. The owner struck them out
  2026-11-12; see the purge rule.)

## The purge rule

The owner, 2026-11-12, on that earlier draft: "NOTHING about how this product
was actually built should make it into the rebuild document, only what it
achieves. For example if you had told the new session that the product
originally used 3 sync engines, surely it would bias it to used 3 sync
engines again, even if not necessary. This is the exact kind of bias I was
trying to ensure is purged."

This is absolute. It is the reason the whole operation exists.

**What crosses to the fresh instance, and nothing else:**

1. What the product achieves for a person: what they can do, what happens
   for them on its own, what they are told, what is refused, with the limits
   and numbers that matter to them.
2. The owner's own requirements for the NEW build, in his words: elegance;
   one repository with a folder per module, each maintained, versioned and
   switched on and off by itself; syncing is core. These are his decisions
   about the future, not descriptions of the past.
3. **Givens**: the things the product has to live with because the people
   who use it have them. DaVinci Resolve, Windows and macOS, the cameras and
   their cards, the kinds of NAS a studio owns, YouTube, the network a
   studio really has. Facts about these cross, stated plainly. Since the
   owner's requirement of 2026-11-12 that Timeline Cards must not depend on
   one editing program, Resolve is a given only as "the editing program this
   studio uses, and the first one supported", never as something the
   pipeline before the hand-over may lean on.
4. What real use taught, stated as what must hold for a person (the
   knowledge base, with the split below).
5. What information the live studio holds that must still be there
   afterwards (people, their computers, what each one syncs, cut lists,
   client links, and so on), named as information, not as files or tables.

**What never crosses:**

- Any tool, library, language or engine the old build CHOSE (as opposed to a
  given it had to live with), and anything that reveals the choice: how many
  engines, processes, channels or copies it had.
- The old build's own nouns for its insides (its names for its transfer
  routes, queues, roles, stores, switches), every file, function, route,
  setting and table name, and every bug number.
- Why a mechanism existed, where the reason is itself a mechanism. Only the
  failure a person would have seen crosses.
- This plan, the inventory, the decision list, the bug ledger, the gotchas,
  the memory notes, and every analysis in them (including the comparison of
  ways to update a module on an editor's machine).

**The hard case: lessons about a chosen tool.** A large share of what real
use taught is about tools the old build picked. Putting those lessons in the
pack tells the fresh instance what was picked. Leaving them out means that
if it picks the same tool on its own merits, it meets the same failures
again, which the owner also ruled out. So they are **sealed**: written up
per tool, kept out of the pack, and released one tool at a time only AFTER
the fresh instance has committed its design in writing and named the tools
it will use. It gets the notes for what it chose and never learns what else
is in the drawer. The same goes for the old data's actual formats: sealed
until the design is fixed and an importer is being written.

**How the purge is checked, before the pack is handed over:**

- **A word scan.** A script builds the banned list from the inventory and
  the code (every tool, library, file, route, setting, table and internal
  noun) and fails the pack on any hit.
- **A blind reader.** A fresh agent is given only the pack and asked: how
  was the original built? What tools did it use? How many of anything did it
  have? Every question it can answer is a leak to be fixed. The pack passes
  when its guesses are no better than they would be for any product of this
  kind.
- **The clean room.** The rebuild session must not be ABLE to see the old
  build, not merely be told not to look. It runs in a new, empty repository
  with no read access to the three old repositories, without this machine's
  project instructions (the `CLAUDE.md` files describe the old build in
  detail), without the memory notes, and without the tools that search past
  sessions. This has to be set up and tested ("try to find out how the old
  one worked") before the rebuild starts. Step 6.

**DECIDED by the owner 2026-11-12: what a person SEES and TOUCHES is kept,
all of it.** The screens, the menus, the wording, the keys, the controller
and the gestures in Timeline Cards are what the product achieves, shaped by
seven months of his feedback, and they cross in full ("No exactly, keep all
that"). The purge applies to everything behind the glass.

**AMENDED by the owner the same day, for the dashboard only:** what each
page lets a person do is kept, but the old menu and the old settings
arrangement are NOT. He finds them confusing and wants them redone ("The
dashboard's shape in the rebuild", below). So for the dashboard the pack
carries what can be done and what each setting is, never where the old build
put it. Timeline Cards is unchanged: its screens, keys and gestures cross
exactly.

**AMENDED again the same day, for Timeline Cards' translation only:** the
editor's translate controls do NOT cross ("Timeline cards doesn't need
Google translate or Claude translate any more"). A card's English is picked
from the part of the transcript the card covers, on its own. The controls
that exist only for the notes program go as well (pasting its links as
cards, copying cards out as its embeds): "obsidian is gone". Everything else
a person sees and touches in the editor still crosses exactly. And the
editor gains a front door it does not have today: dropping clips in (next
section but one).

**DECIDED the same day: the look is kept exactly.** "I also want to keep the
exact same visual style, I really like the way the timeline cards rebuild
looks." So the pack carries a sixth thing:

6. **The look book.** What the product looks like, as a person sees it:
   reference screenshots of every screen in every state, at desk and phone
   sizes, and the look written down as plain values (each colour, typeface,
   size, spacing, shape and motion, and how each kind of control looks and
   behaves), with the fonts, icons and artwork themselves. The Timeline
   Cards editor already has this in good shape (its design document and
   `design/reference` screenshots in the Editing repo); the document must be
   stripped of file names and build steps before it crosses. The rebuild is
   checked against the screenshots.

**DECIDED by the owner 2026-11-12: "The whole product takes the timeline
cards editor's look."** The product has more than one look today: the
dashboard's pages use an older style with square-bracket buttons, and the
Timeline Cards editor dropped those on his instruction (2026-10-28: "I don't
like the bracket buttons"). In the rebuild there is ONE look, the editor's,
on every surface: the dashboard's pages, b-roll, music, YouTube downloads,
the Footage Sorter and the app on an editor's computer. What follows:

- The look book's VALUES and control styles come from the Timeline Cards
  editor alone. Nothing of the older dashboard style crosses, not even as a
  screenshot, or it would be copied.
- For every screen outside Timeline Cards, the pack carries what is ON the
  screen (from the specification: every control, every message, what each
  does) but not a picture of how it looks today. The fresh instance draws it
  in the editor's look.
- The Timeline Cards editor's own screens cross as reference screenshots and
  are matched exactly.
- Still to ask: the public page a client opens from a share link has its own
  look today. Does it take the editor's look too, or keep its own? By
  the guiding principle it takes the editor's look unless he says the client
  page is deliberately different.

## The dashboard's shape in the rebuild (owner's requirements, 2026-11-12)

In his words: "the old settings menu and the menu layout is somewhat
confusing. In the rebuild it should focus on UX cleanliness." These are
requirements for the new build and cross to the fresh instance as written.

- **An Overview page is the home page.** Syncing is no longer the home page.
  Overview "does much the same as now, showing problems, health, sync
  status, module status, version, and offering quick links to various
  commonly used settings", plus anything else that is useful in an overview.
- **A Projects page.** "You can see all the projects, click into them to
  manage them, tick them, untick them, do all the relevant stuff."
- **Transfers is a page of its own.** "It's confusing that 'transfers' is a
  menu bar link but then it takes you to what is just a page in the
  settings. I think transfers does deserve its own page."
- **"Sync" in the menu bar opens a dropdown** holding Projects and
  Transfers, "if you roll over 'sync'", and a third entry: **the
  per-computer view** (which computer is syncing what, and how far along).
  DECIDED 2026-11-12 ("I agree, third entry"). Overview shows only a summary
  of syncing and anything that is wrong. The entry's name is not chosen yet.
- **Settings is reworked** "so that it's laid out more logically".
- **A general search in the menu bar** "which you can use to jump to
  different modules, as well as jump to certain settings". DECIDED
  2026-11-12: it also finds projects, computers and people.
- **A second search inside Settings**, "specifically only for settings".

How this is carried out without bringing the old layout back:

- The pack lists every setting and every action by what it does, with no
  record of which old page or group it sat in. The fresh instance proposes
  the menu and the grouping of Settings from that list alone, and the owner
  approves the map BEFORE any page is built. A session that knows the old
  layout must not draw the new one.
- Every page, module and setting has a plain name and a few search words in
  the specification, because both searches depend on them.

Points still open:

- The product's look is touch-first and the dashboard is used on phones,
  where nothing can be rolled over. Written into the requirement: the Sync
  menu opens on rollover with a mouse and on a tap on a touch screen. Put to
  the owner 2026-11-12; he answered the other two points and did not object
  to this one.
- Ticking a project exists in several places today. The Projects page is
  its home; whether any other place keeps a tick is a step 4 question.

## Timeline Cards in the rebuild: footage in, ready to cut (owner's requirements, 2026-11-12)

His words are quoted in full under "What the owner wants". Restated as
requirements for the new build, in words that name no tool the old build
chose. These cross to the fresh instance:

- **Drop clips in and they process themselves.** A person drops an
  interview's clips into the product and does nothing more. The product
  works out which clips are the same interview seen by different cameras and
  recorders, lines them up by their sound, makes the multicam, transcribes
  the speech, translates it, and times every word, so that any part of the
  English stands for exact words of the original. When it finishes, the
  interview is ready to cut in Timeline Cards.
- **Every step runs on its own.** "The whole pipeline should be automated,
  from dragging in to transcription to translation and word timing." No
  step waits for a person to start it.
- **Nothing outside the product is needed.** No separate notes program, no
  folder of notes a person must keep in a certain shape, and no editing
  program open while the footage is processed.
- **It is not tied to one editing program.** "This is for potential clients
  down the line so it's NLE-agnostic." Everything up to the finished cut
  works with no editing program at all. Handing over to an editing program
  (the multicams, and the cut as a timeline) is the only part that belongs
  to one program.
- **Multicams are made automatically**, as part of the first point.
- **No translate controls in the editor.** A card's English is picked from
  the part of the transcript it covers. The translate button and the draft
  translations go.
- **The cut can be exported as timeline files and as a script.** "We should
  also keep the ability to export an xml otio edl and a txt script"
  (2026-11-12). The editor does this today (inventory sections 32 and 33:
  Final Cut Pro XML, OpenTimelineIO, a CMX3600 EDL, and the plain script as
  text or Markdown, each export listing what the format could not carry),
  so it already crossed under "what a person sees and touches"; his word
  makes it a requirement that no later cut may remove. These files are also
  what makes "not tied to one editing program" true from the first day: a
  program with no hand-over of its own can still open the cut. Reading such
  a file back in (the editor's Import) is kept on the same footing unless
  he says otherwise.

What this changes in the plan (for the preparing sessions; none of this
crosses):

- **The inventory's scope grew, so step 1 is open again.** The pipeline
  before the editor was left out on purpose ("not part of CC Sync"). It is
  in now: sections 41 and 42, started 2026-11-12. Today it is a row of
  stages a person runs by hand, several of them through Resolve and through
  an assistant working in a notes program, which is exactly what he wants
  gone. The inventory records what each stage ACHIEVES and what it needs
  from outside; the specification then describes one capability, "footage
  in, ready to cut", with no stages in it.
- **That capability runs through two of today's products.** The Footage
  Sorter already takes footage in, groups it and (being built now) matches
  sound; Timeline Cards' pipeline lines up angles by sound too. In step 3
  this is written once. Which of today's two behaviours survives where they
  differ is a step 4 question.
- **The word "Obsidian" does not cross**, and neither does anything shaped
  by it (block links, embeds, a vault, a canvas file). The requirement
  crosses; the tool does not. This studio's existing transcripts and cut
  lists are information that must survive, so they go in the old-data
  drawer.
- **Translation still happens**, once, when the footage is processed. What
  goes is translating again, on request, inside the editor. Which translator
  is used is the fresh instance's choice and is never put to the owner.

Answered by the owner 2026-11-12 (these cross, as requirements):

1. **Resolve only to start.** Nothing before the hand-over touches an
   editing program; the hand-over is written for Resolve first, and each
   further program is its own module when a client needs it. Assumed, not
   yet said by him: this is about Timeline Cards only, and the syncing
   product's Resolve features stay Resolve features.
2. **The notes program is gone**, for this studio too. Nothing in the
   rebuild reads its links, writes its embeds or expects its folders.
3. **Every automatic guess can be corrected** in the product: a word, a
   translation, a speaker, which clips belong to one interview.
   Strengthened the same day: "for the multicam generation and transcript
   names and everything there must always be a manual override of
   everything." So this is a rule for the whole of "footage in, ready to
   cut", with no exceptions: anything the product decides on its own (which
   clips make an interview, which camera or recorder is which angle, how
   the angles line up, what the interview, the multicam and the transcript
   are called, who is speaking, the language, where paragraphs break, which
   lines are questions, the translation, the word timing, the themes and
   the first sort) a person can see and set by hand. A value set by hand is
   never overwritten by a later automatic pass. The specification must list
   every such decision and, beside each, how it is overridden; a decision
   with no override is a defect in the specification.
4. **The join check stays**: the editor reads a join between two cuts afresh
   and warns when the meaning or the grammar broke.

### The board: themes and outline (owner's requirement, 2026-11-12)

In his words: "the initial step which is a themed canvas and outline tool,
originally canvas in obsidian, needs a replacement. It should be a kind of
kanban which you can do manually by dragging paragraphs out from a
transcript into, create your own column with themes and drag things around,
etc., and it should still be in .md format so that it stays in the same
format as the transcripts themselves and can be transferred elsewhere."

Restated, and crossing to the fresh instance:

- **A board inside the product for planning the film**, before cutting.
  Columns are themes. Cards are paragraphs of the transcripts.
- **A person drags a paragraph out of a transcript onto the board**, makes
  their own columns, names them, and drags cards and columns around.
- **The board is a Markdown file**, like the transcripts, complete in
  itself and readable anywhere, so it can be taken elsewhere.
- **A place on the board to write notes, and the assistant can be called to
  update the board from them.** "Still want claude assists on the themes and
  things. There needs to be a place to write your notes in this canvas, and
  then a way to call claude to get it to update the canvas based on your
  ideas" (2026-11-12). So the assistant helps in two places: it proposes the
  themes and makes the first sort, and later, when asked, it rearranges the
  board to follow what he has written. It acts only when called, and what
  it changed can be seen and undone.
- **One file per interview holds everything together** (DECIDED 2026-11-12:
  "make it one file where everything is together"): the text, the
  translation, the time of every word, and which English words go with
  which original words. They are tied to each other directly, never found
  again by matching text, so correcting a word cannot loosen its timing or
  its translation.
- **There is always a readable Markdown transcript that can be taken
  elsewhere.** DECIDED 2026-11-12: it is a copy the product writes and
  keeps in step, alongside the one file that holds everything ("readable
  markdown is a copy file kept alongside, that's fine"). The product does
  not promise to follow changes made to the copy in another program.
- **Existing transcripts are brought in once**, and every paragraph keeps
  the reference it has today, so every existing cut list still points at
  the right paragraphs.

What this changes in the plan (for the preparing sessions; does not cross):

- The canvas tools and Story Deck are in the inventory's scope after all:
  the board cannot be specified without knowing what the planning step does
  for him today. Sections 43 (the canvas tools and the two story
  instruction files) and 44 (Story Deck) started 2026-11-12. Section 43
  is written. What its reader found that bears on the board: today there
  are two routes from the canvas to a cut that disagree in details, three
  tools that change a canvas in place with three different rules for which
  group a card is in, and a re-order from his notes that takes seven steps
  and many agents, mostly because the canvas does not keep its own order.
  A board that keeps its own order removes the need for most of that.
- "Markdown" crosses because he asked for it. The old files' exact layout
  does not: it stays in the old-data drawer, and the fresh instance designs
  its own layout. The specification says only what a person must be able to
  read in the file.
- Real episodes have several hundred paragraphs. The specification must
  give the real sizes (paragraphs per interview, interviews per episode,
  themes per board), measured from this studio's work, so the board is
  designed for them.

Answered by the owner later the same day (these cross, as requirements):

1. **The product makes the first sort, and the board can also be worked by
   hand** ("yes both"). The first sort (themes proposed, every paragraph
   placed in one) is the last automatic step of processing. Everything on
   the board can then be dragged, and a person can start from an empty
   board instead.
2. **Story Deck is cut.** "Story deck gets canned, the game thing is
   annoying." Nothing of it crosses: not the stages, the quests, the
   scoring or the look. There is one board.
3. **The board is part of Timeline Cards, as its step 1.** "The board hands
   to timeline cards and timeline cards hands to resolve, but the board
   should be integrated as part of timeline cards, as a step 1." So
   Timeline Cards, in order: clips dropped in and processed, the board, the
   cut, the hand-over to the editing program. One module, one look, and
   only the last step knows about an editing program. Nothing goes from the
   board straight to an editing program.
4. **The cut list stays a `.cut.md` file "as it currently is".** The file
   keeps its present format exactly.

What answers 2 and 4 change in the plan (for the preparing sessions):

- **Story Deck is not inventoried.** Its reader was stopped when he cut it.
  What it had written (the rules, stages, agents and notes; not the page)
  is kept as `feature-inventory/44-story-deck.md`, marked partial, as a
  record only. It feeds no later step.
- **The cut list's file format is the one place where something the old
  build shaped crosses on purpose**, by his decision. It crosses as a format
  a person meets: what the file looks like and what each part means
  (inventory section 34 has it exactly), with no word about the code that
  reads it. The gain is that every cut list this studio has opens in the
  rebuild unchanged. The board's file is new, designed by the fresh
  instance to sit beside it.
- **The transcripts do NOT keep their present format** (his decision the
  same day, after asking what it is). Today a transcript is five separate
  pieces per interview (the text, the word timings, two subtitle files, the
  phrase alignment, the word links) that find each other by matching text
  and by a fingerprint of the text, which is where a good share of this
  year's Timeline Cards bugs came from, and which a correction made in the
  product would break every time. None of that description crosses. What
  crosses is the three requirements above. The present layout goes in the
  old-data drawer, for the importer.
- **What Story Deck was for is kept, without the game** (answered above):
  notes on the board, and the assistant called to update the board from
  them. Today two instruction files do this outside the board (the story
  check and the re-order from his notes; section 43). Which of their
  particular behaviours the board keeps is a step 4 page, with section 43's
  list in hand.
- **Story Deck's reader is not to be resumed** (his word, 2026-11-12).
- **The board must follow the editor's ways of working.** The editor is
  touch-first and is driven by keys, a controller and gestures that cross
  exactly. The board is new, so it has no screenshots to match; it takes
  the editor's look and, where the same act exists in both (select, move,
  undo), the same keys and gestures.

So the product of this work is **a briefing pack a fresh Claude can rebuild
from**, covering CC Sync, the Timeline Cards editor with the pipeline that
feeds it, and the Footage Sorter.
The rebuild itself is a later job, done by a different session that must not
read the current code.

## The plan (approved 2026-11-12; step 2 added the same day)

| Step | What | State |
|---|---|---|
| 1 | **Finish the inventory**: a list of everything the software does, read from the code alone, in `docs/feature-inventory/`. | **40 sections written 2026-11-12**, the Footage Sorter (35 to 38) and the engine behind Timeline Cards (39, 40) included. **Sections 41 to 43 added the same day**, when the owner brought the pipeline before the editor, and the planning step, into the rebuild; section 44 (Story Deck) is a partial record only, because he cut Story Deck. **Complete at 43.** Two top-ups owed before it is used: sections 06 and 10 (ten companion commits about camera cards landed after they were read), and section 36's audio sync (read while another session was still building it). |
| 2 | **The knowledge base**: everything real use taught, gathered from every place it was written down (the owner's own messages, the bug ledger, the gotchas, the hunts, the memory notes, the commits), one entry per lesson, each ending in a rule the rebuild can be tested against. In `docs/rebuild-spec/knowledge-base/`. | **Written 2026-11-13; the owner's part is open.** 7,855 register items, read in 59 slices into 4,442 lessons, merged per capability, repeats across capabilities folded: **2,230 lessons cross, in 18 files** (`docs/rebuild-spec/knowledge-base/<capability>.md`), and **209 sealed tool notes** wait in `docs/rebuild-spec/sealed/`. Every count closes (`check_parts.py`, `check_merge.py`, `check_cross.py`, `assemble_kb.py`, all `OK`). Still owed: the owner's answers to `knowledge-base/_owner/QUESTIONS.md` (lessons still open, outcomes not found, fixes never shipped, disagreements), his test of twenty remembered problems, razer's history, and the top-up before hand-over. Method and state: `docs/rebuild-spec/knowledge-base/README.md`. |
| 3 | **Rewrite the inventory as one specification organised by what people do** (sync a project, make proxies, find b-roll, cut in Timeline Cards, and so on). No source-file tags, no route or config-key names, each capability described once, each capability linked to the knowledge-base entries that apply to it. | Not started. |
| 4 | **A decision list for the owner**: every overlap in what a person can do, every several-ways-in, every dormant or dead feature, each as a keep / cut / merge question with a recommendation. Only questions about WHAT the product does; never an engineering question. A question he has already answered in a past session is shown with his answer, not asked cold. The list itself stays behind; only his answers, restated as what the product does, reach the specification. | Not started. |
| 5 | **Three companions**: (a) the givens the rebuild must live with, taken from the knowledge base; (b) what information must still be there afterwards; (c) the look book: screenshots of every screen plus the look written as plain values. Plus the two sealed drawers: notes per chosen tool, and the old data's real formats. | Not started. |
| 6 | **The purge check and the clean room**: the word scan, the blind reader, and a place for the rebuild session to run where the old build cannot be seen. | Not started. |

The fresh instance is then given the specification, the unsealed part of the
knowledge base and the three companions, and nothing else. Everything in the
REST of this plan (the inventory, the notes on language, the module
analysis, the cost comparison) is for the sessions preparing the pack. It is
full of the old build and none of it crosses.

## Why the inventory alone is not the brief

- It lists what exists, not what is wanted: every duplicate, dormant feature
  and workaround is in it.
- Its sections are cut along the old code's seams, each heading carries a
  source tag, and it lists routes, config keys and per-computer command
  channels. A fresh instance would copy those shapes.
- Anything that spans the editor's machine and the server is described two or
  three times, once from each side.
- Hard-won facts about the outside world are mixed in with features instead
  of standing as a list of constraints.
- Nothing in it says what data must survive the rebuild.
- **It says what the code does, never why.** The readers were told to trust
  only the executable code and to ignore comments and documents. That was
  right for an honest feature list, and it means every reason learned from
  real use was left out on purpose: why a wait is 90 seconds, why a check
  exists, what broke on an editor's machine before it was added. A fresh
  instance given the feature list alone would build the features and meet
  the same failures again. Step 2 exists to carry those reasons across.

## Decisions and steers so far

- **Ask every overlap question.** Shown examples of overlaps, the owner said
  "most of these I would want to keep", and then: "Six places to tick a
  project is an example of something that could be removed. The questions
  should still be asked." So step 4 puts EVERY overlap to him, including the
  several-ways-in ones. Nothing is kept or dropped by default.
- **Keeping a feature is not keeping every copy of it.** Where one capability
  has several ways in, or is written two or three times, the specification
  describes it once with all its ways in, and flags where the current copies
  behave differently so he can pick which behaviour wins.
- **Language (preparing sessions only; see the purge rule).** Of this
  bullet, the only thing that may cross is the owner's wish for Rust, if he
  confirms it as a requirement, and one given: Resolve can only be scripted
  from Python or Lua. Every tool named below is a choice, so none of it
  crosses. Original note:
  Rust is the working choice for the editor-machine app (the
  biggest gain: one native program, no bundled Python, no window-toolkit
  thread crashes) and for the server. The browser pages stay JavaScript or
  TypeScript. The Resolve link stays a small Python or Lua helper, because
  Resolve's scripting only speaks those. The indexers CAN be Rust if every
  model runs through a portable engine (ONNX Runtime, a llama.cpp-style
  runtime, whisper.cpp, ffmpeg); proposed as a rule for the specification.
  Stanza (Timeline Cards' reading aids, Python only, about 1.7 GB) is an open
  question for the decision list.
- **Modules (owner's requirement, 2026-11-12).** Every component is a module
  in its own codebase that slots into the dashboard, so each can be
  maintained, updated, switched on and switched off by itself. This is a
  requirement of the brief, not a question for the fresh instance.
  **"Its own codebase" is DECIDED (owner, 2026-11-12): "one repository with
  a self contained separately versioned folder per module."** Not a
  repository per module. So the rebuild is ONE repository holding the core
  and every module, Timeline Cards and the Footage Sorter included; each
  module's folder holds everything of its own (server half, editor-machine
  half, pages, tests, its version number) and nothing in one module's folder
  reaches into another's except through the contract. What it means in
  practice, and what is still open:
  - **A small core that cannot be switched off**: signing in, people,
    computers, the page frame, updates, the thing that hosts modules, and
    **syncing**. DECIDED by the owner 2026-11-12: "sync is core to dashboard
    and the companion." It is not a module on either side.
  - **A written contract between the core and a module**, small and
    versioned: how a module adds its pages, its records, its settings, its
    alerts, its background work and its jobs, and how it says which core
    version it needs. Separate codebases only stay cheap if this contract is
    small; every change to it touches every module. The contract is part of
    the specification.
  - **Most modules have two halves.** B-roll has a search page on the server
    and "send to Resolve" on the editor's machine; YouTube, music, the sorter
    and Timeline Cards are the same shape. "Slots into the dashboard" covers
    the server half only, so the contract must also cover the editor's app:
    a module switched off on the server is switched off on every computer,
    and the two halves of one module must refuse to work together when their
    versions do not match (the old build's "deploy the dashboard before the
    companions" traps were all this).
  - **Updating one module on an editor's machine is the hard part** and is
    NOT settled. One native program (the reason for choosing Rust) is
    rebuilt whole when any module in it changes, so modules there could be
    switched on and off one by one but not updated one by one. The
    alternative is a small core app that fetches each module's editor half
    as its own signed piece, which gives up some of the "one program"
    gain. The costs were laid out for the owner on 2026-11-12 ("What
    separate module updates cost on an editor's machine", below). SETTLED BY
    THE GUIDING PRINCIPLE the same day: one program, every module built in
    and switchable, because it is the option with the fewest moving parts.
    The owner can overrule it by saying that updating one module by itself
    on an editor's machine is something he needs, not just a means.
  - **Modules lean on each other.** Timeline Cards uses fleet jobs and the
    Resolve link; b-roll uses the Resolve link; the sorter uses card copying
    and the footage ledger. Each module's section states what it needs from
    the others and exactly what a person sees when that other module is off.
  - **Each module owns its own records**, so updating, switching off or
    removing one can never damage another's. Switching a module off hides it
    and stops its work; it deletes nothing.
  - **Where the module lines fall is the fresh instance's to draw**, from
    what people do. The owner is asked only which things he wants to be able
    to switch on and off separately (for example b-roll, music, YouTube
    downloads, Timeline Cards, camera cards and the sorter), which is a
    question about what the product does. An earlier first cut here listed
    modules named after the old build's internal machinery; it was removed
    under the purge rule.
  - Under the purge rule, none of the sub-points above about halves,
    versions, helpers or contracts crosses to the fresh instance. They are
    notes for the preparing sessions. What crosses is the owner's
    requirement in his own words, and "syncing is core".
  - History worth knowing: today Timeline Cards and the Footage Sorter are
    separate repositories mounted into the dashboard, deployed by naming a
    commit of each, and b-roll and music were separate until they were
    folded in as folders on 2026-08-10. The decision above keeps that
    fold-in and brings the other two into the same repository, which ends
    "which commit of which repository is live" (the sorter's `master` trap,
    the unpushed Editing `main`). `CARRY_OVER.md` must say what happens to
    the Editing and footage-sorter repositories and their histories.
- **Size.** Measured 2026-11-12: ccsync's Python is 309,710 lines outside the
  tests, of which 173,105 (56 %) hold code; the tests are another 325,786
  lines. The editor is about 95,000 lines and the Footage Sorter about 45,000.
  A rebuild loses the comment-and-history lines and the duplicated
  implementations; Rust gives some of that back. Expect smaller, not
  dramatically smaller, unless features are cut in step 4.

## What separate module updates cost on an editor's machine

For the preparing sessions only: under the purge rule nothing in this
section crosses to the fresh instance, which decides this for itself from
the guiding principle. Put to the owner 2026-11-12. Measured that day on
creator-1: the installed companion is one 53.4 MB file, runs as four
processes, and its main process holds 108 MB of memory. The seven companion
releases of 10 to 12 November (0.9.90 to 0.9.96) were all camera-card and
sorter work, and each one replaced the whole program on every machine that
took it.

Three ways to build the editor's app:

- **A (recommended, see the end of this section). One program, modules
  built in.** Each module is still its own codebase and can be switched on
  and off by itself, but any module change means a new build of the whole
  program.
- **B. A core app plus one small helper program per module**, each fetched,
  checked against the signed channel, started and watched by the core, and
  talking to it by messages.
- **C. B, but only where a module does real work on the machine.** (First
  offered as the recommendation; that was the cheapest way to meet the
  owner's stated wish, not the best design. Corrected the same day.) The core offers a few fixed abilities any module's page may ask
  for (put this file in Resolve, fetch this file from the archive, show this
  message), so b-roll, music and most of Timeline Cards need nothing of
  their own on the editor's machine. Only the modules with heavy or
  fast-changing work get a helper: YouTube downloading, camera cards and
  field backup, local indexing and transcription, and possibly proxies. Four
  or five helpers, not ten. The abilities must stay narrow and fixed: never
  "run this command", or the server could run anything on an editor's
  machine.

What B or C keeps of the Rust gain: no bundled Python, no window-toolkit
crashes, fast start, most of the size and memory saving. What they give up:
one file with one version number, and joins between parts that are checked
when the program is built.

The costs of B or C, in order of weight:

1. The contract between core and module becomes messages between programs,
   which must be designed, versioned and tested. A mismatch shows up when it
   runs, not when it is built, so every helper must state which core it
   works with and the core must refuse a mismatch out loud.
2. A machine has several version numbers, not one. The Packages page becomes
   a grid, and "which build is this computer on" has several answers.
3. Release work multiplies: every helper is built for Windows and for macOS,
   signed, published, and has its own rollback and floor.
4. More programs for the operating system to trust. No Windows signing
   certificate exists yet; each unsigned program is one more thing antivirus
   can flag. On macOS each helper is signed and notarised, and whether a
   helper inherits the app's disk permissions must be TESTED on a Mac, not
   assumed.
5. The updater has to swap a helper while the core runs, and wait while that
   helper is mid-job (a card copy, a download).
6. Anything shared is reached through the core: Resolve (one program may
   talk to it), sign-in, settings, tray messages, file transfer. Each need is
   one more message in the contract.
7. A change that spans the core and a module is two releases in the right
   order: the old "dashboard before companions" trap, on one machine.
8. Size and memory: each helper carries its own copy of the shared parts,
   about 5 to 10 MB each on disk (estimate) and a few MB of memory when
   running. Small next to today's 53 MB and 108 MB.

What they buy: a camera-card fix reaches only the machines with that module
on, without restarting the app that is syncing; a module that crashes does
not take the tray and syncing down with it; a module that is off is not on
the disk at all. And the app already starts and watches separate programs
(rclone, Syncthing, ffmpeg, yt-dlp, the Resolve helper) and already updates
yt-dlp by itself, so "a core that runs other programs" is not new work.

**The recommendation, asked for with the owner's own preference set aside:
A.** Reasons:

- What B and C buy is smaller than it looks. A Rust app restarts in a second
  or two and can wait for a gap in the work; the heavy jobs already run as
  separate programs (ffmpeg, yt-dlp, rclone), so a crash in one is already
  contained; and the seven releases in three days were the owner's own
  development loop on two machines, which is no faster with helpers.
- What they cost lands on this project's known weak points: halves at
  different versions, the release pipeline, the Mac builds that lag, and
  safety machinery piling up around simple acts. For a fleet of four
  machines and one operator, several update streams on two platforms is the
  kind of bloat the rebuild is meant to remove.
- One signed file with one version number is the easiest thing to get past
  Windows antivirus and macOS, and the easiest thing to support for a paying
  customer.
- It is the choice that can be changed later. If the join between core and
  module is kept clean inside the one program, a module that later proves it
  needs its own update stream can be moved out into a helper. Going the
  other way throws the message contract away.

Two cheap additions give most of what separate updates would: every module
has a remote off switch (so a bad module is stopped at once while a fix is
built), and every release says which modules it changed (so a machine with
none of them switched on skips it).

What A does not give: a fix to one module still ships as a new build of the
whole app.

**Outcome: A, by the guiding principle (elegance, fewest moving parts),
2026-11-12.** The owner did not pick A in so many words; he set the
principle, and A is what it selects. He was told so and can overrule it.

Raised at the same time and since ANSWERED: "its own codebase" means one
repository with a self-contained, separately versioned folder per module
(see "Modules" above). That decision makes A the natural fit, since every
module is already built and checked against the same contract in one step.

## Step 1 in detail: what was owed (all written 2026-11-12)

Every section below is now written and committed; the tables are kept as the
record of how the code was split between readers. What the readers found
that matters beyond the inventory:

- Likely defects in the LIVE product, none confirmed by running anything:
  the Android app installs an update that has no checksum; the apps'
  settings routes do not check who is calling; a clean install of the b-roll
  indexer from its pinned list looks unable to start (a missing package);
  the local indexing option can give stills the wrong timestamps; the
  planner and the Resolve agent work out cut lengths differently for clips
  at another frame rate. Bring these to the owner; they are not rebuild work.
- The Footage Sorter is two complete servers answering about 35 of the same
  routes, and has three generations of card copying.
- There are four separate routes from a cut list into Resolve and four
  separate searches of the transcripts.
- Several Footage Sorter controls cannot be reached on a phone, and its
  pages carry one studio's names and paths.

A lesson for step 2's readers: every reader shares one temporary folder.
Three used the same file names and one overwrote another's. Give each reader
a prefix for its temporary files in its prompt.

The index and the status table are in
[`feature-inventory/README.md`](feature-inventory/README.md). The rules every
reader follows are in
[`feature-inventory/_parts/INVENTORY_BRIEF.md`](feature-inventory/_parts/INVENTORY_BRIEF.md):
the code is the only source of truth, read every line, describe behaviour and
not architecture, end with three lists (looks redundant, claims the code does
not back, could not determine).

Each reader's prompt is: "First read the brief at
`E:\Projects\Editing\ccsync\docs\feature-inventory\_parts\INVENTORY_BRIEF.md`
and follow it exactly. Do NOT start sub-agents of your own." Then one
paragraph saying what the software is, the files that are its part, the
output path and the section title.

### Owed in CC Sync

| | Files | Write to |
|---|---|---|
| 24 | every non-test file in `ccsync\broll\indexer\` and `ccsync\broll\eval\`, and anything directly under `ccsync\broll\` that is not `web` | `24-broll-indexer-and-search-eval.md` |

### Owed in the Timeline Cards editor (`E:\Projects\Editing\Resolve\MulticamPipeline\editor`)

Skip folders named `test` and `shots`, and files ending `.test.ts`.

| | Files | Write to |
|---|---|---|
| 31 | `features\search`, `features\shorten`, `features\chat`, `features\translate` | `31-timeline-cards-search-shorten-chat-translate.md` |
| 32 | `features\resolve`, `features\projects`, `features\video`, `features\montage`, `features\markers` | `32-timeline-cards-resolve-projects-video-montage-markers.md` |
| 33 | `features\shelf`, `features\gapnotes`, `features\keep`, `features\looks`, `features\lane`, `audio`, `adapters`, and `..\apps` (the Windows and Android apps) | `33-timeline-cards-shelf-notes-looks-audio-apps.md` |
| 34 | `server`, `core`, `cutmd` (the editor's own server, every route; the cut-list model; the `.cut.md` file format exactly as a person or another tool meets it) | `34-timeline-cards-server-and-cut-list-format.md` |

### The engine behind Timeline Cards (found owed 2026-11-12, during the resume)

The editor's server calls a Python engine,
`E:\Projects\Editing\Resolve\MulticamPipeline\multicam_pipeline\cards`
(about 38,000 lines without the old page), for the real work. No section
covered it, and section 31's reader could not settle several behaviours
because of that. Two more sections:

| | Files | Write to |
|---|---|---|
| 39 | `cards\resolve_engine.py`, `project_engine.py`, `project_conform.py`, `project_diff.py`, `project_edit.py`, `project_agent.py`, `project_pick.py`, `agent.py`, `cutlist.py`, `timecode.py`, and the `multicam_pipeline\resolve` package | `39-timeline-cards-engine-sending-to-resolve.md` |
| 40 | every other file directly in `cards\` except `handler.py`, `server.py` and `page.py` (the old page's server, retired) | `40-timeline-cards-engine-library-shorten-search-chat.md` |

Skip the `cards\page` folder, `tests` and `__pycache__`.

### The pipeline before the editor (brought into scope 2026-11-12)

Left out on purpose until the owner asked for the whole path, from dropping
clips in to a transcript with word timing, to be automatic and part of the
rebuild. In `E:\Projects\Editing\Resolve\MulticamPipeline`. Both sections
were written and committed 2026-11-12; section 41 says, for every stage,
what it needs from Resolve and from the notes program.

What the two readers found that bears on the owner's requirement:

- Most stages already need neither Resolve nor the notes program. The ones
  that need Resolve are the first transcript export, rendering each
  multicam's sound, and the checks that police Resolve's own transcript.
  A later stage that adopts the speech-to-text result directly makes those
  checks unnecessary for new interviews.
- Paragraphing, question marking and translating an interview are done by
  an AI assistant following an instruction file, started by a person. This
  is the largest hand-run step.
- There are three separate translation routes today and two separate
  speech-to-text set-ups. (For the preparing sessions only.)
- Likely defects in the live tools, not confirmed by running anything: the
  in-place library editor stops with an error whenever it is given markers;
  two stages match a clip to an interviewee's folder by different rules, so
  one clip could in rare cases land in two folders.
- `deploy\site.toml` in that repo holds two live credentials in plain text
  (kept out of git). Told to the owner 2026-11-12.

| | Files | Write to |
|---|---|---|
| 41 | `multicam_pipeline\transcripts`, `pipeline.py`, `pipeline_web.py`, `zh_fold.py`, `zh_fold_table.py`, `paths.py`, `webtheme.py`, `tools\gen_zh_fold.py` (about 10,300 lines) | `41-interview-pipeline-transcripts-translation-word-timing.md` |
| 42 | `multicam_pipeline\library` (about 4,800 lines), the interview-preparation instruction file `~\.claude\skills\canvas-sorter` (not code, but it is what runs), and `deploy` | `42-project-library-tools-and-interview-prep.md` |

The planning step, in scope since the owner asked for a board to replace
the canvas (2026-11-12). Readers started the same day:

| | Files | Write to |
|---|---|---|
| 43 | `multicam_pipeline\canvas` (about 4,800 lines) and the instruction files `~\.claude\skills\story-flow` and `structure-notes` | `43-planning-canvas-tools-and-story-skills.md` |
| 44 | `multicam_pipeline\storydeck` with its page, `storydeck_web.py`, and the `storydeck_*` files in `tools` (about 15,000 lines). **Stopped part-way 2026-11-12 when the owner cut Story Deck**: the Python side is written, the page was not read. Not to be resumed (the owner, 2026-11-12). | `44-story-deck.md` (partial, a record only) |

### The Footage Sorter (`E:\Projects\Editing\footage-sorter`, not started)

Check out nothing: read the working tree as it is (branch
`sorter-dashboard-module` on 2026-11-12; four files had uncommitted changes).
Skip `node_modules`, `cache`, `data`, `test` and `tests`.

| | Files | About | Write to |
|---|---|---|---|
| 35 | `footage_sorter\` (first half of the modules, by size) | 19,656 lines in all | `35-footage-sorter-engine-part-1.md` |
| 36 | `footage_sorter\` (second half) | | `36-footage-sorter-engine-part-2.md` |
| 37 | `public\` (the pages: every screen and control) | 13,376 lines | `37-footage-sorter-pages.md` |
| 38 | `server.js`, `lib\`, `ingest\`, `nas\`, `cloud\`, `tools\`, `mover.ps1` | about 18,000 lines | `38-footage-sorter-server-ingest-cloud-tools.md` |

For 35 and 36, list the modules with `wc -l` first and split them into two
halves of about 10,000 lines each, by subject where possible.

When a section is written, change its row in `feature-inventory/README.md`
from OWED to a link, and add the Footage Sorter rows there.

## Running it without burning the usage allowance

What happened on 2026-11-12: twenty readers launched at once took the account
from low usage to the hard five-hour limit in about 25 minutes.

- **Arm the watcher first.** "The watcher" is
  `E:\Projects\Utilities\claude-usage\usage.mjs`. Run
  `node usage.mjs wait-high --at 70 --poll 240` as a background command before
  starting any reader. When it prints PAUSE, stop every reader and report.
  `node usage.mjs status` reads the figures at any time.
- **Four readers at a time**, a new one only as one finishes.
- **Readers must not start sub-agents.** Stopping a parent does not stop its
  children.
- **A stopped reader keeps what it read.** Send it a message to carry on; do
  not start it again from nothing.
- **Cost, measured 2026-11-12:** the last eleven sections took the
  five-hour window from 7 % to about 40 %, so roughly 3 % a section (each
  reader used about 450,000 to 550,000 tokens and ran 7 to 13 minutes). On
  that figure step 2 (the knowledge base: about 27 readers and 6 mergers) is
  about one window, not the two first estimated, and step 3 about a third of
  one. Still estimates for work of a different kind.

## Step 2 in detail: the knowledge base

### Where the feedback lives (measured 2026-11-12)

No single place holds it. The same problem is usually written down three or
four times: the owner's message reporting it, the ledger entry, a memory
note, the commit that fixed it, sometimes a gotcha. Each source catches
things the others miss, so all of them are read, and duplicates are merged
afterwards.

| Source | How much | What it is good for |
|---|---|---|
| **Everything the owner ever typed to Claude Code**: `C:\Users\alex\.claude\history.jsonl` on creator-1 | 7,755 messages since 2026-04-09. 3,333 were typed inside the product's folders and another 324 elsewhere mention it: about 420,000 characters. Razer has its own file, not yet counted. | The purest record of real use: "Ruskin isn't syncing", "I'm not getting the prompt", "the tray keeps closing itself". It covers the whole life of the project. It holds his words only, no replies. |
| **Session transcripts** (both sides of the conversation) | Only from about 2026-09-29. Claude Code deletes a session file after 30 days, so the local files start 2026-10-08; the synced store (the `memory-sync` tools) reaches a little further back and has no tool output. | What a report turned out to be, and what he decided when asked. For anything older, the outcome has to come from the ledger, the commits and the memory notes of the same days. |
| **The bug ledger**: `KNOWN_BUGS.md` | 34,423 lines. 384 numbered `CR-` entries plus the earlier lettered series; 191 sections, 1,151 sub-entries. | The fullest account of each problem: what was seen, the cause, the fix, what is still open. |
| **The gotchas** | `docs/GOTCHAS.md` (1,648 lines, 25 sections) and `Resolve\MulticamPipeline\GOTCHAS.md` (813 lines) | Facts about the outside world, already half distilled. |
| **Hunts, sweeps, audits, reviews** | Ten `docs/bug-hunt-*.md` files and six folders, two sweeps, the 2026-11-10 audit, the pre-launch review: about 19,000 lines | Problems found by READING the code, not by using the product. Kept, and marked as such. |
| **Memory notes** | About 415 files, 15,400 lines, across the `ccsync`, `Editing`, `Projects`, footage-sorter and home folders under `C:\Users\alex\.claude\projects\`, plus razer's | The owner's rulings ("nothing ticked is fine", "YouTube jobs are shared across editors") and root causes in a paragraph each. |
| **Commit messages** | 650 in ccsync, 575 in Editing, 66 in footage-sorter | The net for fixes that never got a ledger number, such as the card-copy changes of 2026-11-12. Their subject lines are already plain statements of behaviour. |
| **Plans and investigations in the other two repos** | About 40 files in `Resolve\MulticamPipeline\docs`, 11 in `footage-sorter\docs` | Timeline Cards and sorter problems that never reached the ccsync ledger. |
| **Tests and code comments** | 17,421 test functions in 715 files; 161 distinct `CR-` numbers cited in non-test code | Too big to read through. Used only as a cross-check: a bug number or a dated reason found there and nowhere in the knowledge base means something was missed. |

One gap to know about: transcripts from before late September 2026 are gone.
The owner's own messages from those months survive (first row), and so do the
ledger, the notes and the commits, so the problems are still recoverable. The
back-and-forth is not.

Not yet looked at: anything editors told the owner outside Claude Code
(messages from Ruskin or Leso). Ask him whether any of that should be read.

### How it is gathered

1. **The register (scripts, no usage cost).** A script turns every source
   into numbered items, one row each, with a stable id: `P-` for one of the
   owner's messages (date, folder, text, and the pasted text where there was
   any), the ledger's own numbers, `H-` for a hunt finding, `M-` for a memory
   note, `C-` for a commit, `G-` for a gotcha section. The raw register goes
   in `docs/rebuild-spec/_raw/`, which is **gitignored**: the owner's messages
   can hold passwords and people's names, so they are never committed. Run it
   on razer too.
2. **The readers (four at a time, same rules as step 1).** Each takes one
   slice of the register and writes entries in the format below. For one of
   the owner's messages the reader first decides what it is: a report of real
   behaviour, a ruling on how he wants something to work, a request for a new
   feature, or none of these. A report is then followed to its outcome,
   through the transcript where one exists and through the ledger, commits and
   notes of the same days where it does not. A report whose outcome cannot be
   found still gets an entry, marked "outcome not found", and those are
   brought to the owner in one batch.
3. **The mergers.** One pass per subject (the same subjects as the
   specification) folds the copies of one problem into one entry that keeps
   every source id. Where two sources disagree about the cause or the fix,
   the later one wins.
   **The finished document holds only what is still true and still needed**
   (the owner, 2026-11-12: "if there are any lessons which are no longer
   relevant, or repeated lessons, or superseded lessons, etc, they should
   all get removed from the final document"). So the mergers remove:
   - **repeats**: one rule appears once, however many times it was met;
   - **superseded lessons**: an earlier ruling he later changed, a fact
     about a given that a later finding corrected, a rule a later rule
     replaced. Only the current one stays, with no mention of the old;
   - **lessons that no longer apply**: anything about a thing he has cut
     from the rebuild (Story Deck, the notes program and everything shaped
     by it, the translate controls in the editor, the old Timeline Cards
     page, and whatever step 4 cuts later), and anything a decision of his
     about the rebuild makes impossible (a lesson about text-matched
     transcripts once transcripts are one file).
   Nothing removed is lost: each removed entry goes to the trace that stays
   behind, with the reason and what replaced it, so the count still closes.
   Step 4's cuts run the same filter again before the pack is handed over.
4. **The count.** A script checks that every id in the register appears
   either in an entry or in `NO_ENTRY.md` with a reason (not about the
   product, small talk, a duplicate, about running the live system only).
   Step 2 is finished when nothing is left unaccounted for. This count is the
   only honest way to say "everything made it in". Then the owner names
   twenty things he remembers going wrong, and each must be findable.

### What an entry looks like

**Terse.** The owner, 2026-11-12: "the point of this knowledge base should
ultimately be for it to be terse." It will hold thousands of lessons and is
only useful if each can be read in seconds. So in the finished knowledge
base an entry is at most three short sentences: what a person saw (15 words
at most), what was going on (one sentence, 30 words at most, the fact and
not the story of finding it), and what the product must do (one sentence,
30 words at most, that could be turned into a test). Numbers that matter
stay; history, hedging and second examples go. The mergers cut harder than
the readers: one rule appears once, however many times it was reported.
There is no limit on how many pages a capability's lessons run to ("no hard
rule on how many pages", the owner, same day): the limit is on each entry,
not on how many there are. Everything longer (the sources, the old build's account of the
cause) is in the trace that stays behind.

Written in plain words under the purge rule: no file, function, route or
setting name, no tool the old build chose, none of its internal nouns, and
nothing that reveals how many of anything it had. An entry says what a
person saw and what must hold for them, never what was built to make it
hold:

- **What a person saw.** The title.
- **What was going on.** The situation and the real cause, stated as a fact
  about the world wherever it is one.
- **What the product must do.** One rule the rebuild can be tested against.
- **Kind** (below), **how it was found** (reported from real use, found by
  reading the code, found by a test), the date, and its state (fixed and
  live, fixed but never shipped, still open, declined by the owner).
- **Sources.** Kept in a separate trace file that stays behind, not in the
  entry: bug numbers and commit ids are the old build's and never cross.

The kinds decide where an entry goes:

| Kind | Example | Goes to the fresh instance? |
|---|---|---|
| 1a. A fact about a GIVEN (something the studio has, whatever the build) | Resolve's scripting dies for the whole session if anything connects during its launch; a Mac spells file names differently from Windows and the NAS | Yes, in full. These also become `CONSTRAINTS.md` in step 5. |
| 1b. A fact about a tool the old build CHOSE | How a particular sync or download tool behaves and fails | SEALED. Filed per tool, outside the pack, and released only once the fresh instance has named that tool in its own committed design (see the purge rule). |
| 2. The owner's ruling | A computer with nothing ticked is never an error; no long dashes in anything a person reads | Yes, in full, and step 4 does not ask the question again. |
| 3. A situation the product must survive | The sync drive pulled out mid-upload; a file moved on the NAS by hand comes back; proxies a few frames short that Resolve refuses | Yes, in full, under the capability it belongs to. |
| 4. A mistake only the old build could make | The tray dying because a window was cleaned up on the wrong thread | No. It stays behind whole. Where it hides something a person needs ("a stop that protects footage is still in force after a restart"), that need is written as a kind 3 entry with no trace of the mechanism. |
| 5. Running the live system | How to reach an editor's machine, deploy traps, where a secret lives | No. It belongs with the runbooks, and with `CARRY_OVER.md` where it affects moving the fleet across. |

Entries are filed by the same capabilities as the specification, so the
section on proxies and the lessons about proxies sit side by side.

### What it changes in the later steps

- **The specification (step 3)** is written from the inventory AND the
  knowledge base. Each capability ends with "what real use taught", linking
  its entries, and every kind 1 to 3 rule must be visible in the behaviour
  described or be listed as not yet covered.
- **The decision list (step 4)** shows a ruling he has already made as
  "decided on this date, in these words" for him to confirm, never as a fresh
  question. Where he ruled two ways at different times, both are shown and
  the later is the default. Problems still open become questions too.
- **The rebuild's own tests.** Every kind 1 to 3 rule is a test the new
  build must pass before it is called done. That is what stops a fixed bug
  being found a second time.

### Keeping it true after it is written

- The knowledge base's README records how far each source was read (the date
  of the last owner message, the last commit in each repo, the last ledger
  number). Work on the live product does not stop, so a short top-up pass
  from those marks runs just before the pack is handed over.
- Once it exists, each of the three repos' `CLAUDE.md` gets one rule: a fix
  that came from real use adds or updates a knowledge-base entry in the same
  change.
- Session files are still being deleted at 30 days. Proposed to the owner
  2026-11-12 and NOT yet done: raise `cleanupPeriodDays` in
  `C:\Users\alex\.claude\settings.json` on both machines so no more are lost.

## Steps 3 to 5: how to do them

**Step 3, the specification.** One document set under `docs/rebuild-spec/`,
organised by capability, not by program, with the capabilities grouped into
the modules the owner confirms (see "Modules" above). It opens with the core
and the contract every module is written against; each module then gets its
own document that can be handed to a session working on that module alone,
stating what it needs from the core and from other modules and what a person
sees when it is switched off. The whole of it is written under the purge
rule and must pass the word scan and the blind reader (step 6). The list
below is a first cut made BEFORE the purge rule and still carries some of
the old build's own nouns ("lane", "fleet jobs", "ledger", "safety stops");
each must be restated as what a person gets (for example "heavy work is done
on whichever computer is free", "knowing where every copy of every clip
is") before it is used as a heading. A first cut of the capabilities:
signing in and people; computers and what each one syncs; uploading
originals; downloading proxies and originals; the shared-folder lane; safety
stops; proxies; Resolve (relinking, fixing, undo, LUTs and stills); moving
files; camera cards and field backup; the footage ledger and the sorter;
b-roll (search, ingest, indexing, client folders); music; YouTube downloads;
Timeline Cards (cut lists, lane, cards, transcripts, search, shorten, chat,
translation, sending to Resolve, offline); fleet jobs; updates and releases;
alerts and self-diagnosis; recovery and snapshots; installing a site;
installing an editor's machine; personal data. For each capability: what a
person can do, what happens on its own, every limit, number and message that
matters to a person, and every refusal. Write it from the inventory and the
knowledge base; settle each "could not determine" by reading the other
section that answers it, or the code. End each capability with "what real
use taught", linking its knowledge-base entries.

**Step 4, the decision list.** `docs/rebuild-spec/DECISIONS.md`. One numbered
question per overlap, in plain words, each with: what exists today, the
options, a recommendation, and what the choice changes for a person. Gather
them from every section's "Looks redundant or overlapping" list and from the
duplicates found while writing step 3. A question the knowledge base shows he
has already answered carries his answer and its date. Group them so he can answer a page at
a time. The first page is the module questions, because the specification's
shape hangs on them: the module list, and confirming the two things already
settled (syncing is core; one program on the editor's machine). That one page is put to him
BEFORE step 3 is written, not after it. Kinds of question after that:
several ways in to one thing (keep which?), the
same job built twice (which behaviour wins?), dormant or dead features (can
they go?), and either-or tools (built-in card copier or TeraCopy, and so on).

**Step 5, the two companions.**
- `CONSTRAINTS.md`: facts about the outside world, stated without reference
  to the old code. For example: Resolve's scripting server and the launch
  window in which a client must not connect; macOS file names being a
  different Unicode form from Windows and the NAS; what Syncthing, rclone,
  TrueNAS and Synology DSM do and refuse; what YouTube blocks. These are the
  knowledge base's kind 1 entries, gathered into one list; check each one
  against the code before writing it down.
- `CARRY_OVER.md`: everything the live system holds that a rebuild must read
  or migrate: the dashboard's records, the `.cut.md` cut lists, the b-roll
  and music indexes, client share links, each editor's settings and sync
  identities, the Resolve undo journals, the signed release channel and its
  keys. And how the live fleet moves from the old build to the new one.

## Things found along the way

- **Shipped the same day, both live:** dashboard 0.7.80 (the old Timeline
  Cards page retired, the picker's Open opens the editor;
  `docs/CARDS_OLD_PAGE_RETIREMENT.md`) and Timeline Cards at Editing commit
  `94cbab7` (the controller moves the transcript's playhead, LT plus the
  right stick selects, LT + X inserts after the selected card).
- **Deploy trap:** the installer's default Footage Sorter ref is `master`,
  which was OLDER than the live sorter. Read the live
  `sorter-web/DEPLOYED_COMMIT` and pass `--sorter-commit <live>`.
- **The Editing repo's `main` is 160 commits ahead of GitHub** and was not
  pushed.
- **A controller behaviour that cannot work** (inventory section 28): in the
  transcript, LT + D-pad left/right is meant to step through search results,
  but the controller switches to the results map whenever results are open.

## To resume

Paste this into a new Claude Code session opened in
`E:\Projects\Editing\ccsync`:

> Read `docs/REBUILD_PLAN.md`, `docs/feature-inventory/README.md` and
> `docs/rebuild-spec/knowledge-base/README.md`, then carry on with the plan.
> Step 1, the inventory, is complete at 43 sections. Step 2, the knowledge
> base, is written (2,230 lessons in 18 capability files, 209 sealed tool
> notes); `python docs/rebuild-spec/tools/assemble_kb.py --check` must print
> OK. What is open in step 2 is mine to answer: bring me
> `docs/rebuild-spec/knowledge-base/_owner/QUESTIONS.md` a page at a time,
> then my test of twenty remembered problems. Do NOT rebuild the register,
> the merge bundles or the cross batches: the parts, merged files and
> rulings are keyed to them. Read "The guiding principle" and "The purge
> rule" before anything else: nothing about how the old product was built
> may reach the pack. Check usage first
> (`E:\Projects\Utilities\claude-usage\usage.mjs status`) and keep to 70 %
> of a window, run at most four agents at a time, on Opus, tell every agent
> not to start sub-agents and to prefix its temporary files. Then step 3,
> the specification. Bring me the step 4 questions a page at a time. Commit
> each finished piece; push nothing.
