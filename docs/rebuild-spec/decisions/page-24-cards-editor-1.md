# Decision list, page 24: Timeline Cards: the editor, part 1

Stays behind: never shown to the session that rebuilds the product.

14 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 24.1 Should Delete take out a marked in and out range wherever the keyboard is, or only while the lane's strip has the keyboard?

- **Today:** the help sheet says Delete takes out an in and out range, but it does so only while the lane's strip holds the keyboard; elsewhere Delete arms the selection.
- **Options:** A: keep it to the strip, where the range is marked (I and O are strip keys too). B: wherever the keyboard is, a valid range wins over the selection.
- **Recommended:** A, because with the keyboard in the cards a selected card is the obvious target, and the range is set and seen on the strip.
- **What you would notice:** with B a Delete pressed in the cards could take out a range the person was not looking at.
- (cards-editor-1-Q4)

### 24.2 Should Alt+S and "To safe cuts" always act when asked, even with the safe-cut aid switched off?

- **Today:** Alt+S on an armed edge moves it to a safe cut whether or not the safe-cut aid is on, while Alt+S on picked words, and the snap while dragging an edge, do nothing when it is off.
- **Options:** A: a key or button pressed on purpose always acts; only what happens without asking (the ticks and the drag snap) follows the aid. B: everything follows the aid, so Alt+S on an edge also does nothing when it is off. C: keep the mix.
- **Recommended:** A, because a person pressing Alt+S wants the move, and the aid only decides what is drawn and snapped unasked.
- **What you would notice:** with A, Alt+S on picked words starts working with the aid off.
- (cards-editor-1-Q5)

### 24.3 Should paragraphs and cuts keep showing their short paragraph reference (the "^ref"), as plain text?

- **Today:** each transcript paragraph has a short id, shown with a "^" in front on cards, staged cards, the lane's readouts, toasts and search, and a copied cut carries it. The "^" form came from the notes program's block links, which the owner has cut. The paragraph ids themselves are kept, because every existing cut list points at its paragraphs by them.
- **Options:** A: keep the reference visible as plain text ("^ref"), searchable, never a link into another program. B: hide it, and name a cut by its speaker and words only.
- **Recommended:** A, because the reference is already how a cut list names a paragraph, the editor's exact screens show it, and it costs nothing once it is no longer a link.
- **What you would notice:** with B every toast, readout and search row that shows "^ref" changes.
- (cards-editor-1-Q6)

### 24.4 Shortening works in two ways (a planned review accepted suggestion by suggestion, and a slider driven by scores given once per cut list). Keep both, or one?

- **Today:** both ways of shortening exist (they are written in part 4 of this editor). The section summaries on the overview and on a folded section, the third feature the question named, are kept: your rulings ask for a folded section to show its summary and for each summary to fit in a few lines.
- **Options:** A: keep only the slider. B: keep only the planned review. C: keep both.
- **Recommended:** A, because one way of shortening is the fewest parts, and the slider already shows the cut getting shorter as it moves.
- **What you would notice:** with A or B one of the two shortening panels goes.
- (cards-editor-1-Q9)

### 24.5 Should the lane keep taking its keys from the editor's own keyboard preset in Resolve, now that nothing before the hand-over is meant to need an editing program?

- **Today:** where the editor's Resolve keyboard preset can be read, the lane uses the same keys for the same commands; otherwise it uses its own keys, which are Resolve's defaults. Your rulings ask for exactly this. Your later requirement says only the hand-over knows about an editing program, and that with the help for the editing program off nothing mentions it.
- **Options:** A: keep it, as an extra that applies only where the help for the editing program is on and a preset can be read; the lane's own keys stay Resolve's defaults either way. B: drop it: the lane has its own fixed keys, and a person who wants others changes them in the editor.
- **Recommended:** A, because it is your own ruling, it costs a person nothing when there is no Resolve, and it disappears with the help for the editing program.
- **What you would notice:** with B an editor whose Resolve keys differ from the defaults has to learn the lane's.
- (cards-editor-1-Q10)

### 24.6 Should a clip's waveform sit on a shared baseline at the foot of the clips, or centred?

- **Today:** the waveform is drawn under the words, along a baseline at the foot shared by every clip. One ruling asks for waveforms to "sit centred", like Resolve's; a later ruling asks for narrow clips to keep their waveform on the same baseline as their neighbours.
- **Options:** A: a shared baseline at the foot, under the words. B: centred in each clip.
- **Recommended:** A, because it keeps the words readable above it and every neighbour on one baseline, which both rulings want.
- **What you would notice:** with B the waveform runs through the middle of the words.
- (cards-editor-1-Q12)

### 24.7 Should cards be joinable into stacks again, one collapsible card made of neighbouring cuts, only when you ask?

- **Today:** the editor you use every day has no stacks at all. Only a page that is gone had them, with these controls: the J key on a card to join it to the stack above or start a new stack there, the small join and split controls on a card, J or a join button to join a whole box selection into one closed stack, W or the chips on a card to open or close one stack, and Shift+W (or a row in the drawer, or the phone's stack icon) to open or close all of them. Your ruling says cards are gathered into a stack only when you ask.
- **Options:** A: leave stacks out: every cut stays its own card, and folding a section is the way to gather cards out of sight. B: bring them back, only on request, with the controls listed.
- **Recommended:** A, because you already cut every day without them, folded sections already hide a run of cards, and stacks would add a second way of collapsing cards, their own keys and a remembered state for every stack.
- **What you would notice:** with A nothing changes from what you use now; with B the J, W and Shift+W keys and the join, split and stack chips come back on the cards.
- (cards-editor-1-Q13)

### 24.8 After you trim or extend a clip, should the playhead stay on the same spoken moment of its clip, as it does now?

- **Today:** after any edge edit the playhead stays on the same spoken moment of the clip it was in; it is never carried forward; if the trim removed that very moment it lands on the clip's last frame; in a gap it keeps its distance into the gap; past the end it keeps its time; nothing moves while playing. An older ruling of yours said ripple trims "carry the playhead", which could be read as the playhead moving with the edge.
- **Options:** A: yes, as it is: the playhead stays on its spoken moment. B: the playhead is carried with the edge that moved.
- **Recommended:** A, because it is how the editor behaves in your daily use, and the word you were listening to stays under the playhead.
- **What you would notice:** with A nothing changes; with B the playhead jumps with each trim.
- (cards-editor-1-Q14)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 24.9 | Should every way of zooming the lane stop at the same limits, from the whole cut in to 400 px per second? | the = and - keys zoom from 0.5 to 2000 px per second; the wheel, a trackpad pinch and the controller stop at 0.5 and 400; the lane itself says it zooms from the whole cut to 400 px per second. Zoomed fully out at 0.5 px per second, a long cut does not fit the window. | A, because one range is the fewest parts, 400 px per second already shows single frames, and "the whole cut" as the outer limit is what makes a 2.5-hour cut fit whole. (cards-editor-1-Q1) |
| 24.10 | Should Escape on the keyboard and B on the controller back out in the same order? | Escape disarms an armed edge, then clears the selection, and never clears the in and out range; the controller's B clears the range first. | A, because each already gives the person a way to clear the range and nothing else would need adding. (cards-editor-1-Q2) |
| 24.11 | The lane could be split into a track band and a ruler band that scrubs, a split that is never switched on. Can it go? | the split exists but the whole lane is track, so it never applies; the lane's ruler already scrubs the playhead on its own. | A, because the ruler already scrubs and a second way of scrubbing the same strip adds parts for nothing. (cards-editor-1-Q3) |
| 24.12 | When a marker comes with only a colour and no kind, which colours mean a note, a plain marker and a section? | a marker added on the lane with no kind is a note when Green and a section in any other colour; a marker read back from a Resolve timeline is a note when Green, and the readers disagree on the rest (one says a colour that is neither Green nor a section colour becomes a note heading, another that every colour except Green and Red becomes a section). | A, because one rule is the fewest parts and your ruling already keeps the kind apart from the colour once it is set. (cards-editor-1-Q7) |
| 24.13 | For a clip shot at a different frame rate from the timeline, should its length on the cards and in Resolve both be its real running time? | the cards and the preview scale such a clip's length to the timeline's rate (its real running time), while the timeline handed to Resolve lays one timeline frame per source frame, so its length and the markers after it can differ from what the cards showed. | A, because the cut the editor hears and times on the cards is the one that should arrive. (cards-editor-1-Q8) |
| 24.14 | The builders' own tools can go: a custom key layout nobody can supply, and hand-run commands that recolour section headings, bring cut lists in line with montage names and rates, and make light audio copies in advance. Agreed? | the editor can take a custom key layout but always starts with the default and no person can change it; section headings can be recoloured to the default rotation by a command run by hand, dry run by default; the two other commands are described with editing the cut list. | A, because none of them is something a person does in the product. (cards-editor-1-Q11) |

## Your answers

ANSWERED 2026-11-24. After answering pages 2 and 3 and most of page 4 one
by one, he said of everything still waiting: "accept all the
recommendations." So every question on this page is answered with its
recommendation.
