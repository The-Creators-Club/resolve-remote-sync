# Timeline Cards: the planning board

## What the board is

### BRD-001: Planning is a hand-worked board of theme columns holding transcript paragraphs.
- What was going on: The owner wants "a kind of kanban" (a board of columns): "create your own column with themes", paragraphs dragged in, "still in .md format" so it "can be transferred elsewhere".
- What the product must do: A person drags transcript paragraphs onto the board as cards, makes, names and reorders theme columns, and the board saves as a self-contained Markdown file.
- Kind: 2
- State: still open
- From: P19-015, D04-071

### BRD-002: The board is the first step of Timeline Cards, offered pre-sorted or empty.
- What was going on: The owner: "the board should be integrated as part of timeline cards, as a step 1", answering "yes both" to an automatic first sort and an empty board.
- What the product must do: The order is clips in, board, cut, Resolve; processing offers a first sort, a person can start empty, and nothing goes from board straight to Resolve.
- Kind: 2
- State: still open
- From: P19-016

### BRD-003: The board has a notes area, and the assistant reworks the board from it.
- What was going on: The owner wants "a place to write your notes" on the board, then a way to have the assistant "update the canvas based on your ideas".
- What the product must do: A person writes notes on the board and calls the assistant, which reworks themes and card placement from those notes as proposals.
- Kind: 2
- State: still open
- From: P19-018

### BRD-004: Planning needs no outside notes program.
- What was going on: The owner ruled the notes program once used for planning "is gone" and needs "a replacement" inside the product.
- What the product must do: No step of planning, transcribing or cutting needs an outside notes program, its links, embeds or folders.
- Kind: 2
- From: P19-014

### BRD-005: Planning has no game-like screens or stages.
- What was going on: A game-style planner for ordering a film with the assistant was built, then cut: "the game thing is annoying".
- What the product must do: Planning has no game-style screens, rules, stages or animations; it is the plain board of theme columns.
- Kind: 2
- From: P19-017, C06-095

### BRD-006: Cutting never changes the board, and a second hand-over never overwrites a cut.
- What was going on: The board's order is handed to the cutting editor; the owner ruled the cut never writes back to the plan, and a cut already being edited holds work.
- What the product must do: Handing the board to the cut is one-way; handing it again into an existing cut is shown as a previewed merge, never an overwrite.
- Kind: 2
- From: M04-123, D04-070

### BRD-007: One shoot's interviews can feed two episode boards, with crossover.
- What was going on: One shoot yielded two episodes in one Resolve project; each interviewee spoke about both, and the owner said this "should be heavily factored in".
- What the product must do: One pool of interviews can be planned into several episode boards, each from its own story brief; a paragraph can sit on both, flagged as crossover.
- Kind: 2
- From: M03-067, P06-003, M04-029, P14-010

### BRD-008: An episode's board opens on a phone from a short, memorable address.
- What was going on: The owner could not find how to view a board on his phone and asked for "this mobile link to be on an easy to remember url".
- What the product must do: Every episode board opens on a phone from a short, memorable address, reachable without knowing a file path.
- Kind: 2
- State: outcome not found
- From: P14-012

### BRD-009: Planning documents live with their episode, under plain names.
- What was going on: Documents written beside the media were invisible to the editor and orphaned, and the owner told the assistant to stop putting its own name in titles.
- What the product must do: An episode's planning documents are kept in one place with that episode where the editor finds them, never beside media, and their names never include the assistant's name.
- Kind: 2
- From: M04-027

### BRD-010: Planning documents reach every editor's computer on their own, with a "sync now".
- What was going on: The owner asked whether a new draft had reached his laptop, then asked for a way to force a sync; one existed but was switched off everywhere.
- What the product must do: Planning documents reach every editor's computer within minutes unaided, and a "sync now" action does a full round trip and says what it did.
- Kind: 2
- State: outcome not found
- From: P16-047

## Cards on the board

### BRD-011: A card holds a short paragraph: at least two sentences, never a long speech.
- What was going on: One transcript split into single-word and single-sentence cards; others held paragraphs "too long, it makes it unwieldy to edit with and move around".
- What the product must do: Cards hold at least two sentences and at most a short passage, split at sentence boundaries, keep every character, and never merge questions or chatter into answers.
- Kind: 2
- From: P16-045, P07-056

### BRD-012: The part of a card that will play is highlighted on the card.
- What was going on: The owner: "it is unlikely the entire paragraph will be used, far more likely that only a sentence or section will be"; the played part is highlighted in the English.
- What the product must do: The played part of a card is highlighted, with the original language untouched, in the same step that places the card, never only described in a note.
- Kind: 2
- From: M04-036

### BRD-013: Re-paragraphing a transcript left cards on other boards pointing at nothing.
- What was going on: Re-paragraphing one interviewee's transcript left 28 cards on two other episodes' boards citing paragraphs that no longer existed.
- What the product must do: When a transcript's paragraphs are split or merged, every card citing them on any board points to the paragraph now holding its text.
- Kind: 3
- State: outcome not found
- From: P15-012

### BRD-014: A placed long quote lost its last line.
- What was going on: Placed spans were capped in length and stopped short of a quote's end, dropping the final caption line of long quotes.
- What the product must do: A card handed to the cut plays every word of its marked passage through to its end, however long.
- Kind: 3
- State: fixed, never shipped
- From: M04-042

### BRD-015: A card's full text could not be read during review.
- What was going on: The owner: "during review I can't see the full text of the card ... it needs a scroll bar".
- What the product must do: A card's full text is readable wherever a decision is made about it, scrolling if it is long.
- Kind: 3
- State: outcome not found
- From: P13-037

## Working the board by hand

### BRD-016: Dragging a card opens a gap and the others shuffle; each drag can be undone.
- What was going on: Cards dropped on each other covered each other; the owner wanted others to reflow live, groups reorderable, and asked "can I undo a decision I've just made".
- What the product must do: A dropped card opens a gap so no card covers another, columns reorder, each drag is one undo step back to the exact prior board, and Escape cancels a drag.
- Kind: 2
- State: outcome not found
- From: M05-021, P03-017, P13-039

### BRD-017: Setting cards aside takes one key and works on several at once.
- What was going on: The owner: "Pressing 0 should stage cards. Also I can't multi select cards right now ... there's no way to easily stage things".
- What the product must do: One or many selected cards are set aside with one key, and set-aside cards count as handled.
- Kind: 2
- State: outcome not found
- From: P13-040

### BRD-018: Set-aside cards are grouped under the theme they would have belonged to.
- What was going on: The owner: weak material goes in "a staged -- category which is named after the MOST RELEVANT category"; a group named "Staged-- China actually scared" belongs to that theme.
- What the product must do: Each set-aside card sits in a set-aside group named after its most relevant theme, and arrives on the cutting editor's shelf under that name.
- Kind: 2
- From: P11-071, D05-073, C05-085

### BRD-019: A cold-open pick stays in its theme and is also listed under the cold open.
- What was going on: The owner: "cold open material doesn't need to be pulled out of the rest of the categories ... just added to an 'extra' cold open category"; subcategories are numbered.
- What the product must do: Tagging a card for the cold open copies it into a cold-open group while the original stays put, and subgroups carry visible numbers.
- Kind: 2
- From: P11-029

### BRD-020: The board said 35 cards remained but showed none of them.
- What was going on: After placing every card he could see, the owner was told cards were unplaced, with no way to find them, and set them aside by hand.
- What the product must do: Every card counted as remaining can be shown and acted on from the count itself.
- Kind: 3
- State: outcome not found
- From: P13-041

### BRD-021: Reopening the board on a later day showed an empty board.
- What was going on: Work was kept under the day it began, so reopening the next day showed a fresh board and hid 521 of 666 cards already placed.
- What the product must do: Reopening an episode's board resumes its latest saved state, whatever the date.
- Kind: 3
- State: outcome not found
- From: P13-042, M04-039

### BRD-022: A board of 2,700 cards panned at 2 to 3 frames a second.
- What was going on: A board of 2,700 text cards, 1.09 million characters, redrew every card's text on every frame while the owner moved around it zoomed out.
- What the product must do: A board of 2,700 cards and a million characters stays smooth to scroll and zoom.
- Kind: 3
- From: M05-080

## What the assistant may do

### BRD-023: The assistant never cuts material on its own judgement.
- What was going on: The owner: "you shouldn't cut things without asking me and justifying why"; "do not cut it down to an hour yourself ... the rest must be up to me".
- What the product must do: An assistant sort or re-order keeps every card except interviewer questions, chatter and clearly extraneous lines, and lists any other proposed removal with a one-line reason.
- Kind: 2
- From: M03-072, P11-028

### BRD-024: A first sort before the editor's notes sets aside only lightly.
- What was going on: A first draft set about 310 cards aside, a redo set aside nothing; the owner: "I didn't say stage nothing, I said stage relatively lightly", because he edits against a full draft.
- What the product must do: A first sort sets aside questions, chatter and only light trims, putting every other card into a theme in order.
- Kind: 2
- From: P16-043, M04-032

### BRD-025: Running time is shown, never used to cut for length.
- What was going on: The owner's rule is "never pre-cut to runtime": a running-time meter against a target is wanted, but nothing may drop material to hit it.
- What the product must do: No sort, re-order or placement removes or sets aside material because of a running-time target unless the editor asks for a shortening.
- Kind: 2
- From: D06-002

### BRD-026: A board's running-time estimate came out at 0.84 of the real cut.
- What was going on: Durations estimated on a planning board ran about 0.84 times the real runtime once cut, so a plan aimed at 90 minutes ran much longer.
- What the product must do: Running time on the board is the sum of the real played durations of the placed passages, not an estimate.
- Kind: 3
- From: M04-031

### BRD-027: An interviewee used noticeably less than every other is flagged for cutting.
- What was going on: The owner ruled that if one interviewee's screen time is "noticeably lower than any other interviewee he needs to be cut overall".
- What the product must do: A draft reports each interviewee's minutes and flags one noticeably below every other for cutting entirely.
- Kind: 2
- From: P16-044

### BRD-028: Themes are proposed, the owner picks, and only then are cards sorted.
- What was going on: The owner sorts every interview paragraph into themes; he wants up to 30 proposed, picks about 12, then sees content sorted.
- What the product must do: The assistant proposes at most 30 themes, names which interviews it will read, and sorts paragraphs only into the themes the owner picked.
- Kind: 2
- From: P01-006

### BRD-029: The assistant decides placement with the whole board and notes in view.
- What was going on: Splitting a 666-card board among separate helpers hid cross-section links and the play-once rule, and ignored the owner's notes: "the whole canvas surely does not exceed" capacity.
- What the product must do: Placement is decided with every card and every note in view at once, splitting only when they truly exceed the assistant's capacity.
- Kind: 2
- From: M04-037, P13-035

### BRD-030: The assistant's changes arrive as proposals the owner takes, declines or drags.
- What was going on: A batch re-order gave the owner nothing to see or steer; he wanted his rules enforced live: a card plays once, named cards stay locked.
- What the product must do: Each suggested placement, order, join and splice is a proposal to accept, decline or drag; no card is placed twice and a locked card never moves.
- Kind: 2
- From: M04-038

### BRD-031: The accept and decline offer did not match the card on screen.
- What was going on: The owner: "why is the deal take / decline underneath different to the current card being looked at".
- What the product must do: Accept and decline always act on the proposal shown, and the card shown always belongs to that proposal.
- Kind: 3
- State: outcome not found
- From: P13-038

### BRD-032: A small adjustment shifts the current board; it never rebuilds it.
- What was going on: The owner: "dont regenerate the whole thing every time I make an adjustment, just shift the current canvas"; rebuilds renumbered cards and threw away his hand-set order and deletions.
- What the product must do: Once the owner has arranged a board, an adjustment or added theme or interview moves only what it touches, keeping every other card, order and deletion.
- Kind: 2
- From: M03-071, M04-028, P06-004

### BRD-033: A note on one card usually means that speaker's run after it.
- What was going on: The owner: "when I say 'run' - it means the section of that speaker usually after the specified card".
- What the product must do: A re-order from the notes moves the speaker's following run with the named card unless the note says otherwise.
- Kind: 2
- From: P11-070

### BRD-034: Every beat in the owner's notes must reach the board.
- What was going on: A beat heading broken over two lines was not recognised, so its cards piled onto the previous beat and some beats vanished.
- What the product must do: Every beat in the notes appears on the board, a heading broken over lines is read as one, and an unreadable heading is reported by name.
- Kind: 3
- State: outcome not found
- From: P13-036, M03-068

### BRD-035: One action's several refusals stacked identical red notices.
- What was going on: Each refused change raised its own red 8-second notice, so a single turn stacked several identical ones on screen.
- What the product must do: Several refusals from one action show as one summary with a count, the details kept where they can be read.
- Kind: 3
- State: still open
- Move to: whole-product
- From: D05-063

### BRD-036: Handing the board to the cut paused 7.6 seconds with nothing on screen.
- What was going on: After the board was chosen, preparing the cut took about 7.6 seconds with no sign of progress.
- What the product must do: Work starts when the board is chosen, and any step over a second shows visible progress until done.
- Kind: 3
- From: P10-060, M01-072

## The owner's editorial rules

### BRD-037: Themes run in story order: personal stories first, ending last.
- What was going on: The owner ruled the middle follows "the best logical story flow", not most to fewest cards, and deleted cards stay out.
- What the product must do: A sorted board opens with personal stories, ends with ending material, orders the middle by story, never duplicates a card and never brings back a deleted one.
- Kind: 2
- From: P07-057

### BRD-038: Cards are ordered by argument, never by when they were said.
- What was going on: The owner: transcript order "is completely not a priority", "often it's better to sort things out of order"; he corrected a sort that kept each interviewee together.
- What the product must do: Cards are ordered by what each answers and sets up, intercutting speakers, never by spoken order even as a tiebreak, nor in one-interviewee runs.
- Kind: 2
- From: M04-033, M03-074

### BRD-039: The cut plays as one conversation between people never in one room.
- What was going on: The owner's house style: each card should sound like a reply, objection, example or continuation of the last, not just the next topic.
- What the product must do: Any ordering judges every join as a reply, prefers word hooks ("Because", "But", a repeated noun), and never uses a question to bridge.
- Kind: 2
- From: D06-004

### BRD-040: The film raises its big question early and answers it late.
- What was going on: The owner: "ASK QUESTIONS, tactically withhold information ... drip feed out the answer"; the whole-film cycle "is a MUST", smaller cycles "a vibe thing".
- What the product must do: Orderings keep one whole-film question open until near the end, add smaller withheld cycles where they help, never demand one per section, and never open a section on its answer.
- Kind: 2
- From: P15-010, D06-005, M04-034

### BRD-041: Interviewer questions never play, except one the owner's notes name.
- What was going on: The owner: "questions are banned from our house style"; the assistant kept using them as joins; his one exception is a question his notes place.
- What the product must do: An order or cut holding an interviewer question is flagged unless the owner's notes name that card for that place, and that exemption is shown.
- Kind: 2
- From: M03-073, D06-003, C06-094, P13-034

### BRD-042: A speaker never plays before the section that introduces them.
- What was going on: The owner reverted a move of one speaker's figures ahead of her introduction; her lines could land only after she and the argument had come first.
- What the product must do: Any placement putting a speaker's card ahead of the section introducing that speaker is flagged or refused.
- Kind: 2
- From: M04-035

### BRD-043: A speaker's self-introduction plays after their first real line.
- What was going on: House style: an introduction card follows the speaker's first substantive line; an opponent may enter by rebutting.
- What the product must do: An ordering check warns when a speaker's introduction card comes before that speaker's first substantive line.
- Kind: 2
- From: D06-006

### BRD-044: A highlights cut is a new board of about five minutes, cut by whole cards.
- What was going on: The owner: "trim extraneous material", not individual cards, and "It MUST flow logically as a story"; a 3:26 pass was too thin.
- What the product must do: Highlights are a separate board of about five minutes, made by dropping whole cards and re-ordering for story, leaving the long version untouched.
- Kind: 2
- From: M03-078, P09-004

## Montages

### BRD-045: A montage draws only on downloaded news and archive footage.
- What was going on: The owner: "Montages are always and ONLY downloaded material - newsreaders, coverage, etc."; an early montage was to use reporters' voiceover and residents' soundbites.
- What the product must do: A montage's pool holds only downloaded news and archive clips, never the film's own interviews or their transcripts.
- Kind: 2
- Check: Are studio anchors' link lines still excluded? An early montage ruling excluded them, later rulings favour newsreader delivery.
- From: P12-040, M03-076, P04-038

### BRD-046: A montage draft is one story-ordered run of lines, searchable and draggable.
- What was going on: The owner wanted about 40 best sentences from all news transcripts in one proposed story order to inspect and drag, without a document per clip.
- What the product must do: A described montage yields one story-ordered draft of about 40 lines, freely rearrangeable; a search yields ranked playable extracts that drag into the cut.
- Kind: 2
- From: P04-039, P08-049

### BRD-047: Montage lines are picked for quality, never from a dubbed soundbite.
- What was going on: The owner likes many sources intercut and spliced; "the quality of the montage takes precedence over the language rule"; "a long run is also fine if it is necessary".
- What the product must do: Montages search every clip, prefer the strongest lines, use language mix only as a tiebreak, allow a long run, and exclude soundbites voiced over by a translator.
- Kind: 2
- From: M03-077, P12-041, P08-054, P09-002

### BRD-048: A news montage builds to a dramatic end on newsreader delivery.
- What was going on: The owner rejected a montage leaning on one calm interviewee: "more dramatic newsreader speech than 'interview' style delivery", building "to a dramatic end".
- What the product must do: A news montage favours newsreader delivery, spreads across many speakers, follows a clear story arc and ends on its strongest beat.
- Kind: 2
- From: P09-003

### BRD-049: A montage's assistant conversation continues instead of starting over.
- What was going on: Each describe, revise or search re-sent the whole material as a fresh request, costing minutes and losing context: "I don't want it to reset context every time".
- What the product must do: Requests about one montage continue one remembered conversation, and a lost conversation is reported, not silently restarted.
- Kind: 2
- From: C03-047, P09-008

## Removed

- M04-045 | no longer applies: cards are tied to transcript words directly, not found by matching text
- D05-016 | no longer applies: the notes program and its board files are cut
- P11-052 | no longer applies: the notes program's canvas is cut
- M03-070 | no longer applies: card sizing on the notes program's canvas is cut
- M03-069 | no longer applies: canvas layout tidying is cut
- P04-040 | no longer applies: column heights on the canvas; board columns are now themes
- P03-016 | no longer applies: building a canvas file from theme assignments is cut
- D07-025 | no longer applies: the notes program's block links are cut
- P13-043 | no longer applies: Story Deck is cut
- D05-062 | no longer applies: Story Deck is cut
- P13-044 | no longer applies: Story Deck is cut
- P13-033 | superseded by BRD-005
- D06-001 | superseded by BRD-005
