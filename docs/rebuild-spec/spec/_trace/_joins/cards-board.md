# Joins aimed at cards-board

## Checked

- J1 | F1, F2
- J2 | F3, F4
- J3 | F5
- J4 | F5, F6
- J5 | fine
- J6 | fine
- J7 | F7, F8, F9
- J8 | F10, F11
- J9 | fine

## Findings

### F1: The board lets an interviewer question play and hands it to the cut, but the cut list can never hold one
- Kind: contradiction
- From: cards-editor-2 / A cut list holds the cut, the bench and the timeline's facts
- Here: Interviewer questions never play; A re-ordered board is checked before it is handed over; The board hands its order to the cut
- From says: "a question can never be in the cut (the house rule "no questions included in the edit ever"), only on the bench"
- Here says: "A question that the owner's notes name for a place in the film is exempt, and is shown as exempt rather than as a fault." and "By hand: a person can drag a question into play. It is then flagged until his notes name it for that place." (the hand-over table says nothing about a question card in a column that plays)
- Settled by: two rulings disagree, BRD-041 ("An order or cut holding an interviewer question is flagged unless the owner's notes name that card for that place") and CE1-021 ("Any edit, by hand or by the assistant, that would put an interviewer's question in the cut is refused"), so the owner must say: when his notes name an interviewer question for a place in the film and the board is handed to the cut, does that question play in the cut there, or does it go to the shelf like every other question?
- Fix: both change: the board's hand-over table gets a row for a question card in a column that plays (cut or shelf, per his answer), and cards-editor-2 says the same thing.

### F2: A note card can hold many lines (a flag card up to 12), but a note row in the cut list is one line
- Kind: contradiction
- From: cards-editor-2 / A cut list holds the cut, the bench and the timeline's facts
- Here: The board hands its order to the cut; A re-ordered section opens with a flag card
- From says: "A note row is a direction card or an "unmatched" line, one line of text (it may be empty)."
- Here says: "A note card | A note; an empty one reads "(empty card)"" and "short notes (up to 12 lines) on how that section was ordered and what it hands on"
- Settled by: the owner must say: when a note card of several lines (such as a section's flag card) is handed to the cut, does the cut show all its lines in one note, or only one line of it?
- Fix: both change: the board's hand-over table says what a note card of several lines becomes, and cards-editor-2 lets a note row hold that (or says how the lines are joined).

### F3: Building a montage by describing it is left to the board by the editor, but the board does not meet the lesson's whole must
- Kind: missing
- From: cards-editor-3 / The search sheet has pickers for which transcripts, how many results, which strength of assistant, and a fresh start
- Here: A montage board
- From says: "CE3-054 (building a montage by describing it belongs with the board and footage-in montages, not with search)"
- Here says: "A person can describe the montage he wants and call the assistant to draft it: the draft is one story-ordered run of about 40 lines, freely rearrangeable." (nothing on choosing which clip folders the montage draws from, nor on a revision coming back in seconds; CE3-054 is not in the board's met list, which ends at BRD-048)
- Settled by: CE3-054 (ruling): "A described montage becomes a cut list, a revision returns in seconds, unplaced quotes are listed, and results play and drag into the cut."
- Fix: the board's "A montage board" says that a person picks which clip folders the montage is drawn from, that a revision of a described montage comes back in seconds, and lists CE3-054 as met.

### F4: The montage clips are "the montage pool" on the board and "corpus clips" in the editor's search
- Kind: differs
- From: cards-editor-3 / The search sheet has pickers for which transcripts, how many results, which strength of assistant, and a fresh start
- Here: A montage board
- From says: ""All corpus clips" searches only the montage source clips, not the interviews"
- Here says: "A montage is planned on a board of its own, from a pool of downloaded news and archive clips only" and "A search of the montage pool gives ranked, playable extracts"
- Settled by: OWNER_REQUIREMENTS section 5: "Every page, part and setting therefore has a plain name and a few search words in this specification."
- Fix: the board names the montage pool by the editor's Exact label ("corpus clips", the episode's montage source clips) so a builder knows the board's pool and the search scope are one set of clips.

### F5: An episode's own style is "House style for an episode" and "Shortening rubric for an episode" here, but a "chat style note" and a "shortening style note" in the editor
- Kind: differs
- From: cards-editor-4 / An episode can carry its own description of what counts as fluff; The chat follows a house style of seven editorial rules, which an episode can replace with its own
- Here: The studio's house style, and an episode's own; The shortening rubric, and an episode's own
- From says: "When the episode has its own shortening style note and it is not empty" and "An episode's own chat style note, when present and not empty, replaces these whole"
- Here says: "Setting: House style for an episode." and "Setting: Shortening rubric for an episode."
- Settled by: OWNER_REQUIREMENTS section 5: "Every page, part and setting therefore has a plain name and a few search words in this specification."
- Fix: cards-editor-4 calls them by the board's setting names ("House style for an episode", "Shortening rubric for an episode"), and makes plain that the chat's style note is the same episode house style the board's assistant follows.

### F6: The seven house-style rules are written out in full in both pieces, already in slightly different words
- Kind: said twice
- From: cards-editor-4 / The chat follows a house style of seven editorial rules, which an episode can replace with its own
- Here: The studio's house style, and an episode's own
- From says: "never invent tension (the speakers' own words in their own order)"
- Here says: "never invent tension or change what was said;"
- Settled by: the rules are the owner's rulings met by the board (BRD-037 to BRD-044, e.g. BRD-040, BRD-041), and the board states they hold "on the board and in the editor"
- Fix: cards-editor-4 drops its own list of the seven rules and points to Timeline Cards: the board, The studio's house style, and an episode's own.

### F7: An interviewee's colour is given when their first footage comes in, here in alphabetical order of the episode's people
- Kind: contradiction
- From: cards-footage-in / Each interviewee is given a colour
- Here: Every interviewee has one colour everywhere
- From says: "Each interviewee gets one colour, assigned when their first footage comes in" and "Until then a person sees "no colour assigned yet"."
- Here says: "new interviewees are taken in alphabetical order, ignoring letter case, and each takes the first palette colour nobody in the episode has yet"
- Settled by: the owner must say: when new interviewees come in, does each take the next free colour in the order their footage arrives, or are they coloured in alphabetical order of their names?
- Fix: both pieces state the one order he chooses, and the board also says what a person sees before a colour is given ("no colour assigned yet").

### F8: The board lets only "the owner" recolour a person, footage-in lets any person
- Kind: contradiction
- From: cards-footage-in / Each interviewee is given a colour
- Here: Every interviewee has one colour everywhere
- From says: "By hand: a person can pick another colour for an interviewee."
- Here says: "By hand: the owner can give any person another colour, and that person is recoloured everywhere from then on."
- Settled by: page 23.2 (answered 2026-11-24, recommendation A): "one colour per person everywhere, always the remembered one (changed only by you, everywhere at once)"; "the owner" is no role in the product, so the owner must say: who may change an interviewee's colour, anyone signed in who can open Timeline Cards, or only an admin?
- Fix: both pieces name the same role (an admin, or anyone who can open Timeline Cards) in place of "the owner" and "a person".

### F9: The board lets a later interview's new cards take a colour other than their speaker's
- Kind: contradiction
- From: cards-footage-in / Each interviewee is given a colour
- Here: A later interview joins a board in use without disturbing it
- From says: "Each interviewee gets one colour ... used for their cards on the board and for their multicam wherever it is shown"
- Here says: "The person can give the new cards another colour, and is told whether the colour was the speaker's own or a new one."
- Settled by: page 23.2 (answered 2026-11-24, recommendation A): "one colour per person everywhere, always the remembered one (changed only by you, everywhere at once)"
- Fix: the board removes that sentence: a later interview's cards always take the speaker's one colour, which is changed only by recolouring the person everywhere.

### F10: Footage-in keeps a question directly above its answer on the board; the board sets it aside in its answer's set-aside group
- Kind: contradiction
- From: cards-footage-in / Off-topic chatter is set apart (and its neighbour "The product marks which paragraphs are the interviewer's questions")
- Here: Interviewer questions never play; The first sort places every paragraph in one theme
- From says: "A question is kept directly above the answer it sets up, on the board as in the transcript, and travels with it"
- Here says: "one that sets up an answer is set aside in the set-aside group of its answer's theme" and "Interviewer questions that set up an answer, chatter, and only light trims are set aside"
- Settled by: BRD-041 (ruling): "An order or cut holding an interviewer question is flagged unless the owner's notes name that card for that place"; a question directly above its answer in a column that plays would play
- Fix: cards-footage-in says a question stays above its answer in the transcript, and on the board goes to the set-aside group of its answer's theme (pointing to Timeline Cards: the board, Interviewer questions never play).

### F11: The board decides chatter for itself, from a list that differs from footage-in's chatter mark
- Kind: contradiction
- From: cards-footage-in / Off-topic chatter is set apart
- Here: The first sort places every paragraph in one theme
- From says: "Sound checks, door noise, filming and scheduling logistics, restarts, goodbyes and talk about translating are put in small paragraphs of their own and marked as not content" and "By hand: a person can mark or unmark any paragraph as chatter. The mark is kept through every later pass."
- Here says: "On its own: what is non-content and goes to "Uncategorised" (sound checks, door noise, filming and scheduling logistics, restarts, goodbyes, and questions that set nothing up)."
- Settled by: OWNER_REQUIREMENTS section 6: "A value set by hand is never overwritten by a later automatic pass."
- Fix: the board's first sort sends to "Uncategorised" exactly the paragraphs footage-in marks as chatter (by hand or on its own), plus questions that set nothing up, and points to footage-in for what chatter is instead of keeping its own list.
