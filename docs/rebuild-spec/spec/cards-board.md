# Timeline Cards: the board

The board is where the film is planned before it is cut. Every paragraph of an episode's interviews becomes a card, the cards sit in columns that are the film's themes, and the owner and the editors drag cards and columns around until the order reads as the film they want. It arrives sorted into proposed themes as the last step of getting footage in, or starts empty, and it is worked by hand, with the assistant called in only when a person asks. The board is a Markdown file, complete in itself, and it hands its order to the Timeline Cards editor, never straight to an editing program. The board is part of Timeline Cards, which is off on a new site until an admin switches it on: while Timeline Cards is off, nobody but an admin sees the board, and the admin sees it only as Timeline Cards' switch in settings. When the assistant is switched off, the board works fully by hand, a new board starts empty beside its transcripts, and no assistant control appears on it.

## What the board is

### The board plans the film from every paragraph of an episode

Before cutting, every paragraph of every interview of an episode can sit in front of the owner, sorted by theme, and from it he builds the film's order. Each column is a theme, and each theme is a section of the film. A card is a transcript paragraph (or a note of his own). The owner's hand order is the authority: the assistant may read it, judge it and propose, but only a person moves cards, unless he explicitly asks for a full re-order, which makes a new version of the board and leaves his own untouched.

The board is a plain board of theme columns and cards, worked directly. Nothing outside the product is needed to plan, and no folder has to be kept in a certain shape.

The order of the work is fixed: clips in, the board, the cut, the hand-over to the editing program. A new episode's board arrives sorted, as the last automatic step of getting its footage in, or a person starts it empty and fills it by hand. Nothing goes from the board straight to an editing program.

- Who: anyone signed in who can open Timeline Cards.
- On its own: a new episode's board is sorted into proposed themes when its interviews finish processing.
- By hand: a person can start from an empty board instead, at any time before or after the sort, and the sorted board is kept as a version he can go back to. Every card and column the sort placed can be moved, renamed or removed by hand, and nothing he sets by hand is undone by a later automatic pass.
- Name and search words: the board. Search words: board, planning, themes, kanban, sort, plan the film.
- When the assistant is off: a new board starts empty, with the episode's transcripts beside it to drag paragraphs from.

### Every paragraph of the episode is accounted for

On a sorted board every paragraph of the episode is on the board exactly once: nothing is lost and nothing is doubled. A paragraph no theme claims is still on the board, in a final column called "Uncategorised". On a board started empty, the transcripts beside the board show which paragraphs are not on it yet, and a count of them per interview. Every count the board shows (cards remaining, cards not yet on the board, cards set aside) can be opened to show exactly those cards, and each can be acted on from there.

- Who: anyone signed in who can open the board.

### One shoot can feed several episodes, each with its own board

When one shoot is cut into several episodes, the episodes share one set of transcripts, and each episode has its own story brief, its own themes, its own first sort and its own board. With no episodes named, the shoot is one episode named after the shoot. A list of episodes must hold at least one name, and a person who saves an empty list is told so and the list is kept as it was. A paragraph can sit on more than one episode's board; where it does, its card on each board is marked as crossover, naming the other episode.

- Who: anyone signed in who can open Timeline Cards.
- On its own: each episode's first sort draws from the whole shared pool, guided by that episode's story brief.
- By hand: a person writes and changes each episode's story brief, drags any paragraph onto or off any episode's board, and can mark or unmark a card as crossover.

### An episode's board opens from a short address on any device

Every episode's board opens from a short, memorable address, on a phone as on a desk, without knowing where any file is kept. An address that names a shoot but no episode of it shows that shoot's episodes to choose from. Reopening a board, on any day, resumes its latest saved state.

- Who: anyone signed in who can open Timeline Cards.
- Phone and desk: the same address opens the same board on both.

### The board is a Markdown file kept with its episode

The board is a Markdown file, complete in itself and readable in any text program: its columns in order with their names, each card in order with its speaker, its original wording, its English and the reference of the paragraph it came from, and the board's notes. Opening a board file back in the product gives the same board. An episode's planning documents (its board and its versions, its notes, its story reports, its house style and its shortening rubric) are kept together in one place with the episode, where an editor finds them, never among the media files. They are named plainly by the episode and what each document is, and never carry the assistant's name.

An editor whose computer takes the episode has its planning documents, as they stand, within minutes of any change, with nothing to press. A person can also ask for them to be brought up to date right now: that makes the full round trip at once and says what it did (see Sync: What syncs where).

- Who: anyone signed in who can open the board.
- Name and search words: board file. Search words: board file, markdown, export board, planning document.

### Everything reads the board in the same order and every card has a number

The board is read one way by everything that reads it: the columns in order, and inside each column its cards in order. Only order counts. Every card, note cards included, carries a number 1, 2, 3 and so on in that order, shown on the card. The assistant's reports and the owner's notes refer to a card by its number together with its paragraph's own reference, and a mention of a card in the notes is a link to that card, so it still finds the card after numbers shift. Numbers shift as soon as a card is added or moved, so the assistant reads the board afresh every time and never relies on a number from an earlier reading. In a board file opened from elsewhere, a card standing before the first column is read after all columns as "(ungrouped)" and the person is told how many there are, and a column with no name is called "(unnamed group)".

- Who: anyone signed in who can open the board.

### The unused material is listed theme by theme

A person can ask for the material not in the cut. Every paragraph of the episode not in a column that plays (set aside, alternates, "Uncategorised", or not on the board at all) is listed under its theme, themes with the most unused paragraphs first. Each shows its speaker and its English, or its original wording when it has no English, or "(no text)", and interviewer questions are marked as questions. The list also gives, per speaker, how many of their paragraphs exist and how many are used.

- Who: anyone signed in who can open the board.
- Name and search words: unused material. Search words: unused, leftovers, not in cut, speaker balance, pool.

### The board hands its order to the cut

A person hands the board to the Timeline Cards editor, and its order becomes a cut list the editor opens, with no editing program needed. Work starts the moment the board is chosen, and anything that takes more than a second shows its progress until it is done.

| On the board | In the cut |
|---|---|
| A theme column that plays | A section, in the same order, with the theme's name and a colour from the editor's fixed rotation of section colours by its position among the sections that play, Blue first, so the cut and the hand-over to the editing program always agree |
| The cold-open group | The first section |
| The alternates column | An alternates section, its cards placed and ready to swap in |
| "Uncategorised" | A shelf category after the cut |
| A set-aside group that holds cards | A shelf category after the cut, named after the theme it belongs to |
| A paragraph card | A cut on its interview's clip, with its speaker, colour and text, playing its highlighted part, or the whole paragraph when nothing is highlighted, through to its last word however long it is |
| A note card | A note; an empty one reads "(empty card)" |
| A card whose paragraph cannot be found | An "unmatched" note holding the card's text and a link to its paragraph |

A paragraph card is tied to its paragraph and its timed words, so it lands without any search for its words. Before anything is written, a preview shows the beginning of the result first. Afterwards the person is told how many cards were placed and how many did not land (each of those with its number, paragraph, speaker, first words and the reason), how many notes, alternates and set-aside cards there are, and for each interview which clip its cards were placed on.

Handing over is one way: cutting never changes the board. Handing the board over again into a cut that already exists never overwrites it. It is shown as a preview of a merge: the cards the board has added, the cards it has moved and the cards it no longer holds, and the person takes what he wants. The cut's own edits and trims are kept. What the editor then does with the cut is described in Timeline Cards: the editor (Editing, undo and the cut list, and Notes and the staged shelf).

- Who: anyone signed in who can open the board.

#### Lessons

- Met: BRD-001, BRD-002, BRD-003, BRD-004, BRD-005, BRD-006, BRD-007, BRD-008, BRD-009, BRD-010.

## Cards on the board

### A card is a paragraph, a note, or a paragraph from another episode

A board holds three kinds of card.

- A paragraph card holds one transcript paragraph: its original wording (for a Mandarin interview, the verbatim Chinese) and its English. It always knows which interview and which paragraph it came from. A paragraph is at least two sentences and at most a short passage, broken at sentence boundaries, with every character of the original kept and questions or chatter never merged into an answer (how paragraphs are made is in Timeline Cards: footage in, ready to cut: The transcript and its English). An interviewer's question is a paragraph card too, shown as a heading so it stands apart from answers.
- A note card holds a person's own direction with no paragraph behind it (for example "b-roll: harbour at dawn"). It is part of the order but is not a quote, and it counts as no running time.
- A paragraph from another episode's interview (for example from an earlier season) can be placed too. It plays from its own interview, and its speaker keeps the colour they have everywhere.

A card's full text can always be read wherever a decision is made about it, on the board, in a proposal, in a report or a question, scrolling when it is long.

- Who: anyone signed in who can open the board.
- By hand: a person adds, edits and deletes note cards, and drags paragraphs from any episode's transcripts onto the board.

### A card's speaker is the interviewee

A card's speaker is the person interviewed, as getting footage in identified them (and as a person set by hand there), never a file name. Two transcripts of the same person (two shoot days, a follow-up interview, an online call) are one speaker everywhere: one colour, one count in speaker balance, one self-introduction.

- On its own: the speaker comes from the interview's speaker, decided when the footage came in.
- By hand: who is speaking is set by hand in Timeline Cards: footage in, ready to cut (Running on its own, with a hand on every decision), and the board follows it.

### Every interviewee has one colour everywhere

Each interviewee has one colour, the same on the board, on their clips and on their cuts in the editor and in the hand-over. A paragraph card is its speaker's colour throughout: text, background and border. A legend on the board says which colour is whom. The palette is 16 colours in a fixed order: #1375a0, #ec4b93, #448f64, #00b5b8, #dbaf80, #966145, #f09ec1, #000035, #c8a9fe, #16552f, #b8ad4c, #4577a1, #7a3b8f, #2f6f5e, #a0522d, #5470c6. A person given a colour keeps it for good, across episodes too, and when more of their material is added.

- On its own: new interviewees are taken in alphabetical order, ignoring letter case, and each takes the first palette colour nobody in the episode has yet. With more than 16 people, colours repeat.
- By hand: the owner can give any person another colour, and that person is recoloured everywhere from then on. A colour set by hand is never changed by a later automatic pass.

### The part of a card that plays is highlighted on it

When only part of a paragraph is to play, that part is highlighted on the card's English, and several parts of one card may be highlighted. The original-language line is never changed. The highlight is made in the same step that places or trims the card, never only described in a note, and what is highlighted is exactly what plays in the cut.

- Who: anyone signed in who can open the board.
- By hand: a person highlights or clears any part of any card. A highlight a person made is never changed by the assistant.

### A card stays tied to its paragraph when a transcript is re-paragraphed

When a transcript's paragraphs are split or merged, every card that cites them, on any episode's board, points to the paragraph that now holds its text, so no card is left pointing at nothing.

### A re-ordered section opens with a flag card

In a new version of the board made by a full re-order, each section opens with one bright yellow "TRANSITION / FLAG" note card: the section's name in capitals, short notes (up to 12 lines) on how that section was ordered and what it hands on, and a line saying it was re-ordered on that date from the board's notes. Card references in it point at paragraphs, never at numbers from the earlier order or at the assistant's own working labels.

- By hand: a flag card is a note card like any other, and can be edited, moved or deleted.

#### Lessons

- Met: BRD-011, BRD-012, BRD-013, BRD-014, BRD-015.

## Working the board by hand

### A person drags paragraphs from a transcript onto the board

Beside the board, a person opens any of the episode's transcripts (or another episode's) and drags a paragraph out of it onto the board, into any column at any place. Several selected paragraphs drag together. Paragraphs already on the board are marked in the transcript, and dragging one again does not make a second card: it moves the existing one to where it was dropped.

- Who: anyone signed in who can open the board.
- Phone and desk: by touch on a phone or tablet, by mouse on a desk.

### Dragging cards and columns

A person drags a card to any place in any column. While it is dragged, the card under it moves aside to open a gap, so no card ever covers another, and the cards around shuffle to close the gap it left. Columns are dragged the same way, their cards riding with them, without any card changing column or place. "Uncategorised" stays the last column. Escape cancels a drag and puts everything back. Each drag is one undo step, back to exactly the board before it.

- Who: anyone signed in who can open the board.
- Phone and desk: drag by touch on a phone or tablet, by mouse on a desk.

### Selecting several cards and acting on them at once

A person selects one card or many, with the same keys and gestures as in the Timeline Cards editor, and moves, sets aside or deletes them together as one undoable step.

- Who: anyone signed in who can open the board.

### Setting cards aside and tagging the cold open

The same key and the same gesture that move a cut to the shelf in the editor (see Timeline Cards: the editor: Notes and the staged shelf) set aside one card, or every selected card at once. Each set-aside card goes to the set-aside group of the theme it belongs with most, named after that theme, and arrives on the cutting editor's shelf under that name. A set-aside card counts as handled.

Tagging a card for the cold open copies it into the cold-open group at the head of the board while the card itself stays where it was. The copy is marked as a copy, and does not count as a second appearance of the paragraph. Groups within a column carry visible numbers.

- Who: anyone signed in who can open the board.
- On its own: a set-aside card goes to the group of its most relevant theme.
- By hand: a person drags a set-aside card to any other set-aside group, or back into play.

### Making, naming and removing themes

A person adds a column anywhere, names it and renames it at any time. Two columns may not share a name: a name already in use is refused, and the person is told which column has it. A person can also make a new theme from chosen cards: the selected cards are lifted out of whatever columns they sit in into a new column, placed where the person puts it, with the cards in the order they were chosen. The columns they left close up in their remaining order. Cards keep their text and colour. A column is deleted by hand; its cards go to "Uncategorised" unless the person moves them first.

- Who: anyone signed in who can open the board.
- On its own: a column emptied by a change stays on the board, empty, as a placeholder.
- By hand: a person deletes an empty column when he no longer wants it.

### No change can lose or double a card

Every change to a board, made by hand, by the assistant, or by opening a board file back in, is checked before it is kept: every card ends up in exactly one column, the count of cards before and after matches, and no card is doubled. A change that would break any of these is refused, the person is told what it would have broken, and the board is left as it was. A change that would leave cards outside every column is refused with the advice to place those cards first, so no card is ever left behind unseen.

### Every change can be seen and undone

Every change to the board is one undo step, back to exactly the board before it, whether a person or the assistant made it. Earlier states of the board are kept, and a person can see and return to any of them. Undo and redo use the same keys and gestures as in the Timeline Cards editor.

- Who: anyone signed in who can open the board.

### A later interview joins a board in use without disturbing it

A board being worked on is never rebuilt from scratch, because that would throw away the arrangement. When another interview of the episode finishes processing after the board is in use, its paragraphs are offered as proposals at the end of the themes they fit, and nothing else on the board moves. Paragraphs already on the board are skipped and listed, so a transcript that grows brings in only its new paragraphs.

- On its own: each new paragraph is proposed for the theme it fits best, at the end of that theme's order. Its card takes its speaker's colour.
- By hand: a person takes, declines or drags each proposal, or takes them all into one chosen theme, or leaves some out (chatter can be left out), or ignores the proposals and drags paragraphs from the transcript himself. A paragraph not taken stays off the board and does not go to "Uncategorised". The person can give the new cards another colour, and is told whether the colour was the speaker's own or a new one.
- When the assistant is off: nothing is proposed; the interview's transcript appears beside the board with its paragraphs marked as not yet on it.

### Putting the themes in story order with one action

One action on a board in use puts the "Personal Stories" column first and the "Ending" column last (each recognised by name in any letter case), leaves every other column where it was, and keeps "Uncategorised" last. If the board is already in that order, nothing changes and the person is told so. Afterwards the person is shown how far each column moved, earlier or later.

- Who: anyone signed in who can open the board.
- By hand: columns can be dragged into any order afterwards.

### The board's notes

The board has a place to write notes: the owner's ideas about the film, written while reading it. Notes are kept exactly as he wrote them, with their date. Any mention of a card in the notes is a working link to that card. A person can call the assistant to tidy the notes: it keeps his wording and the strength of his instructions, gathers them into the shape of the film (its acts and beats, each with what it does, what it opens on, what it is built from and what it lands on), the moves he wants (naming cards, each to be ticked off when done), lines to build on, and open questions, and leaves his raw notes beneath exactly as written. Notes he has not decided stay open. Every line written as the assistant's own reading is marked as its own. It checks that every card the notes mention is still on the board, and lists any that are not.

- Who: anyone signed in who can open the board.
- When the assistant is off: the notes are written and read by hand, and their card links still work.

### A large board stays smooth

A board of 2,700 cards and a million characters of text scrolls, pans and zooms smoothly, on a phone as on a desk.

- Phone and desk: the same holds on both.

### The board works by touch first, and by keys

The board has the Timeline Cards editor's look and is built for touch first. Wherever the same act exists on the board and in the editor (selecting, moving, undo and redo), it uses the same keys and the same gestures, so nothing has to be learned twice. The keys of the editor are given in Timeline Cards: the editor (Selecting, deleting, inserting and keys).

- Phone and desk: every act on the board can be done by touch on a phone or tablet and by mouse and keys on a desk.

#### Lessons

- Met: BRD-016, BRD-017, BRD-018, BRD-019, BRD-020, BRD-021, BRD-022.

## What the assistant may do

### The assistant proposes the themes

Having read every paragraph of every interview of the episode, the assistant proposes the themes the film could be built from, by the owner's rules (see "What makes a theme" below). It proposes at most 30, always including "Personal Stories" and "Ending", and names which interviews it read. Each proposed theme has a name, a one- or two-sentence description of what belongs in it, and its evidence (how many interviewees and about how many paragraphs, and whose). The list is ordered strongest first (most paragraphs, then most interviewees); that order is only for choosing, not the film's order.

- On its own: the themes, their names, descriptions and evidence are decided by the assistant from the paragraphs, as the last automatic step of getting the episode's footage in, and the first sort follows into those themes.
- By hand: the proposal stays beside the board. A person drops any proposed theme, renames any, adds his own with a description that paragraphs are matched against, and asks for the sort to be made again into the themes he keeps. While nobody has arranged the board, the new sort replaces the first. Once a person has arranged it, a theme he adds or drops moves only the cards it touches, as proposals.
- When the assistant is off: no themes are proposed, and a new board starts empty.

### The first sort places every paragraph in one theme

The first sort places every paragraph of the episode in exactly one theme, judging each paragraph's place against every theme and the whole episode at once, never piece by piece. A paragraph that would fit two goes to the single most relevant. Interviewer questions that set up an answer, chatter, and only light trims are set aside; every other paragraph goes into a theme, in order. A theme that ends up with no paragraphs is still shown, empty. After the sort the person is told how many themes there are, how many paragraphs were placed against how many exist, how many went to "Uncategorised", and whether every paragraph was placed exactly once (a mismatch is called out).

- On its own: which theme each paragraph goes into, decided from its substance in either language against each theme's description, or its name when the description is thin.
- On its own: which answer each interviewer question belongs to, decided from the content: the answer it sets up, or that it sets up nothing and is non-content.
- On its own: what is non-content and goes to "Uncategorised" (sound checks, door noise, filming and scheduling logistics, restarts, goodbyes, and questions that set nothing up).
- On its own: the order of cards inside each theme, whether each theme opens, is body or ends the film, and the order of the body themes.
- By hand: a person drags any card to another theme or place (its theme and its order), drags a question next to the answer he chooses, brings any card out of "Uncategorised" or a set-aside group into play, sets each theme's role, and renames, adds, removes or moves any theme. Nothing set by hand is undone by a later automatic pass.
- When the assistant is off: no first sort is made.

### The assistant acts only when called, and its changes arrive as proposals

Apart from the first sort, the assistant does nothing to a board unless a person calls it. Every placement, order, join and splice it suggests arrives as a proposal on the board, which a person takes, declines or drags elsewhere. Taking or declining always acts on the proposal shown, and the card shown always belongs to that proposal. No card is placed twice, and a card a person has locked never moves. A small adjustment (an added theme, an added interview, a change from a note) moves only what it touches and keeps every other card, order and deletion. It never rebuilds the board. What the assistant changed can be seen, and undone like any other change.

The assistant never removes material on its own judgement. A sort or re-order keeps every card except interviewer questions, chatter and clearly extraneous lines, and lists any other removal it would propose with a one-line reason, for a person to decide.

- Who: anyone signed in who can open the board.
- By hand: a person locks or unlocks any card.
- When the assistant is off: no proposals are made, and no control to call the assistant is shown.

### The assistant updates the board from the notes

A person writes on the board's notes and calls the assistant to rework the board to follow them. First it pins down every card the notes mention: a paragraph reference, a quote (found in the English or the original), "X's part", "run from", "the end". It checks that each quoted line really is on the card it points at. Every beat in the notes reaches the board: a heading broken over several lines is read as one, and a heading it cannot read is reported by name.

Before it changes anything, it puts every doubt to him: a quote or card not found, a card no longer on the board, a vague destination, two notes wanting one card, a note that contradicts an earlier decision or the shape, whether a run continues past a change of topic, a card whose content does not fit the section it was filed under. Each doubt is a choice between concrete options, naming and quoting the cards and saying what follows from each, with "keep it open" where fair. Answers are written into the notes as his decisions. Undecided ones stay open. If he is part way through reading, only what he has written is asked about, and the sections not yet read are noted as open. The notes taken in are dated and kept with his raw notes. He is then told what moved where, what is still open, and which readings were the assistant's own, and the changes arrive on the board as proposals.

- Who: anyone signed in who can open the board.
- When the assistant is off: the notes stay, and the board is reworked by hand.

### A full re-order makes a new version of the board

Only when a person explicitly asks for one, the assistant re-orders the whole board from the notes. It never changes his board, the pool or any earlier version: it makes a new version, numbered next, from the board as it stood when he asked. First it asks whatever the notes do not settle, all before it starts, and says roughly what the job will cost and how long it will take. It turns the notes' shape into target sections, each with its purpose, what belongs in it and its fixed ways in and out, places every card, orders each section, makes the splices, and checks the result. It must cope with an episode of 16 interviewees and about 2,200 cards. Its progress is shown throughout.

Where he does not answer, these choices are made for him:

| Choice | Unless he says otherwise |
|---|---|
| Where set-aside cards go | Into a set-aside group directly before the section they would belong to, named after that section |
| How much is set aside | Lightly |
| A cold open made of copied cards | The copies are dropped and the originals stay where they are |
| Interviewer questions and chatter | One set-aside group, "Interviewer questions and chatter" |
| Special groups (a jettisoned theme, personal stories) | Hold only set-aside cards |
| Self-introductions | Placed by the owner's rule |
| Sections not yet read | Asked |

- Who: anyone signed in who can open the board.
- On its own: each choice in the table, from his notes, or the default shown.
- By hand: he sets each choice when he asks for the re-order, and the new version is a board like any other, worked by hand afterwards.
- When the assistant is off: there is no re-order.

### A re-ordered board is checked before it is handed over

Before a person gets a new version, the assistant checks that no card is doubled, that no interviewer question plays except one his notes name (listed in the report), that the count of unused paragraphs is the same as in the version it came from so nothing went missing.

### After a re-order he is told what was done and every call he did not make

The notes record what was applied, in which new version, and which beat of his shape became which sections. His own notes are left as they were. He gets a report: a table of new sections by act, the size of each set-aside group, confirmation that every fixed way in or out and every named card was honoured, how many flags and splices were made, and under "Calls for you to check" every choice he did not make himself, every place his order was changed and why, splices that could not be made, and translation slips (fixed only with clear evidence from the original language, and listed).

### The assistant reads the board and says what story it tells

When a person asks whether the edit works, what the story is, how sections connect, or for bridges between sections, the assistant reads the ordered board against the whole pool of paragraphs. It reads and reports only: it never changes the board or the pool, and every suggestion names cards so a person can drag them himself. It reads the whole order end to end and then every unused paragraph end to end, with no skimming or sampling, using the original Mandarin where a card's meaning turns on it. The check is made afresh every time.

The report is kept with the episode as a dated document. It opens with the date, which version of the board was read, the card count, the count of distinct quotes and the running time, then its five parts and the bridges (see "The story check's five parts" and "Bridges for weak joins" below). Every run makes a new dated report beside the earlier ones, which are all kept, the newest shown first. When an earlier report exists, the assistant reads it first and notes what changed. With the report, the person is shown a short summary: the total and per-section running times, a two or three sentence verdict, how many joins are weak, the headline finding about the structure and where the report is.

- Who: anyone signed in who can open the board.
- When the assistant is off: there is no story check.
- Name and search words: story check. Search words: story check, does it work, structure, joins, bridges, report.

### Running time is shown from real durations, and never used to cut

Running time is given per card, per section and for the whole board, and is the sum of the real played durations of the passages placed (the highlighted part of a card, or the whole paragraph), taken from the timed words. Note cards count as no time. A card whose words are not timed yet shows its time as not known, and a total says how many cards it leaves out. No sort, re-order or placement removes or sets aside material to meet a running time unless a person asks for a shortening. A draft reports each interviewee's minutes, and flags an interviewee used noticeably less than every other as a candidate to cut entirely.

- Who: anyone signed in who can open the board.

### Long work shows its progress

Anything the board or the assistant does that takes more than a second (a sort, a re-order, a story check, a hand-over to the cut) starts the moment it is asked for and shows visible progress until it is done.

#### Lessons

- Met: BRD-023, BRD-024, BRD-025, BRD-026, BRD-027, BRD-029, BRD-030, BRD-031, BRD-032, BRD-033, BRD-034, BRD-036.

## The owner's editorial rules

These rules are what the assistant follows whenever it sorts, orders, checks or shortens, on the board and in the editor. They are the owner's; where a person asks for something that breaks one, the assistant does what was asked and says in one sentence what the rule would have done.

### The studio's house style, and an episode's own

The house style the assistant follows unless asked otherwise:

- never any interviewer question;
- withhold, then reveal: the film raises one big question early and keeps it open until near the end, with smaller withheld cycles where they help, never one demanded per section, and never a section that opens on its own answer;
- part of a sentence can be the whole card;
- end sections on a cliffhanger;
- space out revelations;
- never invent tension or change what was said;
- make the cut feel like one conversation between people who were never in one room: every join is judged as a reply, word hooks ("Because", "But", a repeated noun) are preferred, and a question is never used to bridge.

An episode can carry its own house style in place of the studio's, written and changed in the product beside the board's notes. An empty or unreadable one falls back to the studio's. A change applies from the assistant's next answer on, in the editor's edit chat too (see Timeline Cards: the editor: Shortening, the edit chat and the assistant).

- Setting: House style for an episode. Does: replaces the studio's house style for the assistant's work on that episode. Default: the studio's house style. Who: anyone signed in who can open the episode's board. Applies to: a project. Search words: house style, editorial rules, episode style, tone.
- When the assistant is off: the house style is still kept and shown, and nothing follows it on its own.

### The shortening rubric, and an episode's own

When a person asks for a shortening, the assistant keeps and cuts by this rubric.

- Keep, in order of stubbornness: the sentence a paragraph walks towards, concrete details, turns, first mentions that later cards depend on, spans the editor highlighted, a section's summary card and its last card.
- Cut first: restatement, scene-setting the picture already covers, the second of two examples, throat-clearing, and cards in a "maybe" colour.
- Never remove a noted card, a section's last card, or a card another kept card refers back to.

Every removal has a one-clause reason in the editor's terms. An episode can carry its own rubric in place of this one, written and changed in the product beside the board's notes. An empty or unreadable one falls back to the studio's. A change applies from the assistant's next answer on.

- Setting: Shortening rubric for an episode. Does: replaces the studio's rules for what a shortening keeps and cuts first on that episode. Default: the studio's rubric. Who: anyone signed in who can open the episode's board. Applies to: a project. Search words: shortening, rubric, trim rules, what to cut.

### What makes a theme

An episode runs to about 300 to 700 paragraphs. Proposed themes follow these rules:

- at most 30 themes, fewer is fine, two always present: "Personal Stories" (how each contributor came to this, who they are) and "Ending" (the closing beat: what it was all for, the next generation, where this leaves us);
- broad homes for material, not narrow topics: the test is how much of the episode fits;
- two candidates that would draw on the same passages are one theme;
- each should plausibly hold 20 or more paragraphs from 2 or more interviewees; less is a detail inside a bigger theme;
- 80 or more paragraphs suggests two stories under one label: the seam is found and two are proposed (100 or more is almost always two or three);
- one interviewee's large story (a campaign, a place, an event) is a valid theme when it can carry a section;
- short, punchy names;
- if every paragraph were placed now, most should land somewhere; if many would not, themes are merged and the proposal made again.

### Every paragraph goes to exactly one theme

Every paragraph goes into exactly one theme: none twice, none thrown away. Placement is aggressive: a serviceable home beats a leftover. It is judged on substance, from either language. A theme a person typed in is treated exactly like a proposed one, matched on its description, or its name when the description is thin. A theme a person renamed keeps the material it was proposed with. Paragraph text is copied exactly, never reworded. "Uncategorised" is only for paragraphs with no content, is shown last, and must hold under a tenth of the episode: the person is told plainly when it holds more than 10%.

### Interviewer questions never play

The film is one conversation between the interviewees, with no voiceover and no interviewer. On the board, an interviewer question is kept, never dropped: one that sets up an answer is set aside in the set-aside group of its answer's theme, and one that sets nothing up ("Could you repeat that?", "Shall we start again?", "Do you want some water?") goes to "Uncategorised". A question anywhere in the order that plays is flagged as a fault, and the person is told how many there are and where, so he can set each one aside. Questions already set aside are still marked as questions but not counted in the warning. A question that the owner's notes name for a place in the film is exempt, and is shown as exempt rather than as a fault. In the unused material, questions are marked as context only, and are never proposed for the cut, not even as a bridge.

- By hand: a person can drag a question into play. It is then flagged until his notes name it for that place.

### Themes run in story order

Each theme has a role: opening, body or ending. A theme with no stated role is the opening if it is called "Personal Stories", the ending if it is called "Ending" (any letter case), and body otherwise. A sorted board opens with Personal Stories, then the body themes in the order a viewer should meet them (context before consequence, problem before response, a specific case before what it means), never by size, then Ending, then "Uncategorised" last. A sorted board never doubles a card and never brings back a card a person deleted. The person is told why the middle themes run in the order chosen.

- On its own: each theme's role and the order of the themes on a new board.
- By hand: a person sets a theme's role and drags themes into any order.

### Cards run by argument, intercutting the speakers

Inside a theme or section, cards are ordered by what each answers and what it sets up (setup, detail, punchline), speakers intercut as replies to one another. Never by the order in which things were said, not even as a tiebreak, and never in runs of one interviewee kept together for their own sake.

- On its own: the order of the cards inside each theme on a new board.
- By hand: a person drags cards within a theme into any order.

### A paragraph plays once

The same paragraph appearing twice in the order that plays is flagged at its second appearance ("this already played"), and the person is warned with every duplicate and where it falls. A cold-open copy is not a second appearance. When two of the owner's notes want the same card, the assistant asks him rather than choosing.

### A speaker plays only after the section that introduces them

A placement that puts a speaker's card ahead of the section that introduces that speaker is flagged, and the assistant never makes one.

### Each speaker's self-introduction comes after their first real line

Each speaker keeps at most one self-introduction, their single best. It is placed right after the end of that speaker's first continuous stretch of cards in the film, so the viewer hears what they say before who they are. A speaker with more than one candidate is reported ("keep the best, restage the rest"). A speaker with no line in the film has the introduction set aside. A speaker with no introduction at all is fine and only listed. Any ordering check warns when a speaker's introduction comes before that speaker's first substantive line.

- On its own: where each self-introduction goes in a re-order.
- By hand: the owner turns self-introduction placing off when he asks for a re-order, and drags any introduction anywhere.

### The story check's five parts

Every claim in a story check cites the card's number and paragraph reference.

- A. The story as it plays now, beat by beat: where the film states its question and whether it answers it, who it is about, whether the argument escalates or flattens into a survey, and the act breaks that can actually be found.
- B. Section by section: its job, how it opens, the state it leaves the viewer in, its running time, and its faults: cards out of order, an answer before its setup, a term used before it is introduced, two cards making the same point, a section that peaks and then trails. Not a fault: a speaker's self-introduction landing after their first substantive line, unless the delay runs to minutes or interrupts an argument.
- C. The joins: for every boundary between two sections, the last card out and the first card in, with a verdict of "lands", "bumps" or "hard cut", and the reason in terms of what changes across the join (subject, speaker, register, scale, place, time, stance).
- D. Against everything unused: themes with many unused paragraphs the order never touches (checking specifically for personal stories, stakes and an ending), unused material that contradicts or answers a claim in the order, stronger unused versions of a point made, and speaker balance (each speaker's paragraphs available against those used).
- E. Mechanical faults: paragraphs that play twice, note cards still unresolved, interviewer questions in play, cards that match nothing in the pool, cards outside every section.

### Bridges for weak joins

Only joins graded "bumps" or "hard cut", and joins inside a section that need one, get proposals, and "leave it" is said where a join works. For each, two or three bridges are proposed, ranked by preference: a hinge quote naming both subjects, a widening beat, a cost or stakes beat, a human beat, and only when nothing unused can do it, a beat that is not a quote (b-roll, archive, narration, location), specified exactly. An interviewer question is never a bridge. Every proposed paragraph really is unused and is quoted word for word, never paraphrased. A speaker the viewer has already met is preferred, and moving a card already in play is preferred over adding one (naming both places). Each proposal says where it goes (closing the outgoing section, opening the incoming one, or both, "after card N"), names the hinge word or idea, and gives its seconds and its cost.

### A note on one card means that speaker's run

A paragraph reference in the owner's notes is a pointer, not a boundary. A note on one card, and "run from" a card, mean that speaker's stretch from the named card onward, in the same section, until someone else speaks, and a re-order moves that run with the named card unless the note says otherwise. A named card does not move alone when its neighbours belong with it, and neighbours that drift off the topic are not dragged along. Whether a run continues past a change of topic is asked, not assumed.

### The standing rules for any re-order

These hold in every re-order:

- Never cut down to a running time. Remove only interviewer questions and chatter; deleting is the owner's job.
- Relevance decides where a card goes, for named and unnamed cards alike.
- The order inside a section is whatever strengthens its argument, with no priority for the order the cards had.
- Strong transitions first, and no voiceover.
- Intercut the speakers as one conversation, each card a reply to the last; never keep a speaker's run together for its own sake.
- Expect to splice a linking word (所以 / 然後 / 但是) between cards.
- A specific note beats a blanket one.
- A paragraph reference is a pointer, not a boundary.
- A card plays once.
- Ask, never guess. An interpretation written without asking is marked as the assistant's own.

### Where each card goes in a re-order, and whether it plays

For every card the assistant judges from what the card says which target section it belongs in and whether it plays there or is set aside there. Cards his notes name are fixed in the section they name, playing, and their neighbours are judged around them; a card named for two sections is put to him. Cards of a theme he sends wholesale to one section go there. Cards meant only for a set-aside group are always set aside. A set-aside card is still given the section it would have been in. Setting aside is light: only dead cards, unplayable fragments or clearly weaker repeats, and no card is ever dropped. Every card of the earlier order ends up exactly once: playing, set aside, or in the questions and chatter group. He gets a tally per section of cards playing, set aside and minutes, and a section far over its share of the running time is noted.

- On its own: each card's section, and whether it plays.
- By hand: his notes fix any card, and after the re-order every card can be dragged.

### The order inside each section in a re-order

Each section is ordered to build its argument: speakers intercut as replies, his fixed ways in and out honoured, moving from setup to landing without giving away the next section early. Each section ends handing the viewer to the next section's fixed first card. The assistant then reads every join (the last two cards of a section and the first two of the next) and may fix a bad hand-off, saying so in its report.

- On its own: the order inside each section.
- By hand: every card can be dragged afterwards, and his fixed ways in and out are never moved.

### Which words play when only part of a card is used

Where a join needs only part of a card, the part that plays is highlighted on the card's English, and several parts of one card may be highlighted. The original-language line is never changed. Only splices the ordering asked for are made, plus optional ones only where the join depends on them. None are invented, and set-aside cards get none. A splice is always whole sentences or clauses, copied word for word from the card (a splice described in the original language is mapped to the English), and must occur exactly once on the card. One that cannot be found exactly once is skipped and reported. A card the owner has already highlighted himself is left alone entirely: his highlight wins.

- On its own: which words of a card play, when a re-order splices it.
- By hand: a person highlights or clears any part of any card, and a highlight he made is never changed by the assistant.

### Columns that are set aside from the cut

A column is one of these kinds, which a person sees on the column itself:

| Kind | What it is | In the cut |
|---|---|---|
| Theme | A section of the film | Plays |
| Set-aside group | Cards set aside, named after the theme they belong with; one per theme | A shelf category of that name, when it holds cards |
| Alternates | Alternative takes, not in the cut | An alternates section beside the cut, matched and ready to swap in |
| Cold open | Copies of cards tagged for the cold open | Plays first |
| Uncategorised | Paragraphs with no content | A shelf category |

In the board file, a set-aside group's heading begins "Staged" followed by the theme's name ("Staged - China actually scared" is the set-aside group of "China actually scared"; a bare "Staged" is the plain shelf), and an alternates column's heading begins "Alternates". Both are recognised in any letter case when a board file is opened, and two set-aside groups of the same name share one shelf.

- By hand: a person sets any column's kind.

### A highlights board

A highlights cut is a separate board of about five minutes, made from a board by dropping whole cards, never parts, and re-ordering for story. The long board is left untouched.

- Who: anyone signed in who can open the board.
- By hand: a person makes a highlights board himself by copying a board and dropping cards, or calls the assistant to draft one.

#### Lessons

- Met: BRD-037, BRD-038, BRD-039, BRD-040, BRD-041, BRD-042, BRD-043, BRD-044.

## Montages

### A montage board

A montage is planned on a board of its own, from a pool of downloaded news and archive clips only, never the film's own interviews or their transcripts. A montage card names its exact clip and its in and out (minutes and seconds), with its quote and speaker above it, so it needs no finding. A person can describe the montage he wants and call the assistant to draft it: the draft is one story-ordered run of about 40 lines, freely rearrangeable. A search of the montage pool gives ranked, playable extracts that drag onto the board and into the cut. Lines are picked for quality: every clip is searched, the strongest lines are preferred, the mix of languages is only a tiebreak, a long run is allowed, and a soundbite voiced over by a translator is never used. A news montage favours newsreader delivery, spreads across many speakers, follows a clear story arc and ends on its strongest beat.

When a montage board is handed to the cut, each card plays its clip from its in to its out. A card with an in but no out, an interview card, or a paragraph from another episode becomes an unmatched note and is listed with the reason ("no pinned span", "needs matching"). A card with no clip becomes a plain note.

- Who: anyone signed in who can open the board.
- On its own: a board is treated as a montage when more of its cards name a clip than point at an interview paragraph, and otherwise as interviews.
- By hand: a person sets a board to montage or interviews, and that choice is never changed by the product afterwards.
- When the assistant is off: a montage is built by hand from searches of the pool.

#### Lessons

- Met: BRD-045, BRD-046, BRD-047, BRD-048.
