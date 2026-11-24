# Decision list, page 26: Timeline Cards: the editor, part 3

Stays behind: never shown to the session that rebuilds the product.

10 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 26.1 Card Find shows up to 30 matches on a desk and up to 40 on a phone. Keep the two numbers, or make them the same?

- **Today:** the desk's pop-over stops at 30 rows and says how many more there are; the phone's Find tab lists up to 40.
- **Options:** A: keep 30 on a desk and 40 on a phone, as they are. B: one number everywhere (40).
- **Recommended:** A, because both screens were shaped by use and the difference costs nothing to build.
- **What you would notice:** with B a desk shows ten more rows before "N more".
- (cards-editor-3-Q1)

### 26.2 Should the transcript panel's intake (drop media, then send a transcription, proxy, audio or waveform job to a chosen computer by hand) stay, now that dropped clips process themselves?

- **Today:** dropping media files on the transcript panel lists them in an intake, finds them in the episode, and offers one button per kind of job and a choice of computer. In the new build footage in is automatic and heavy work is shared out on its own.
- **Options:** A: keep the intake as it is, job buttons and computer choice included. B: a drop on the panel hands the clips to footage in, which processes them on its own; the intake only lists what was dropped and how far each clip has got, with no job buttons and no computer choice. C: remove the drop and the intake from the panel; clips are dropped where footage in takes them.
- **Recommended:** B, because it keeps the gesture he uses and removes a second, hand-run way of starting work the product already does by itself.
- **What you would notice:** with B or C an editor can no longer aim one job at one computer from the editor; with B the drop still works where it does now.
- (cards-editor-3-Q2)

### 26.3 There are two daily allowances of assistant calls with two settings (300 a day for lining English up with the original, 200 a day for glosses and join checks). One allowance, or keep two?

- **Today:** two number boxes in two different settings panels of the editor, each with its own "used today" count.
- **Options:** A: one daily allowance for all the editor's assistant work, with one count. B: keep the two.
- **Recommended:** A, one setting and one count is simpler to understand and to build.
- **What you would notice:** with A one setting caps both, so heavy lining up can use up the allowance for join checks on the same day.
- (cards-editor-3-Q3)

### 26.4 Anyone who can open the editor can change the daily allowances of assistant calls, which cost the studio money. Should only an admin change them?

- **Today:** any person who can open the editor can change both allowances.
- **Options:** A: only an admin may change them; editors see the count. B: anyone who can open the editor, as now.
- **Recommended:** A, because the allowance is the studio's spending on the assistant.
- **What you would notice:** with A an editor sees the allowance and what is used but cannot raise it.
- (cards-editor-3-Q4)

### 26.5 The floating English-selection toolbar shows Play on shelf cards, where it always refuses ("Only a card in the cut can play from here."). Keep it there, or hide it on shelf cards?

- **Today:** the button shows on shelf cards and answers with that refusal.
- **Options:** A: hide Play on shelf cards. B: keep it, with its refusal.
- **Recommended:** A, a button that can only refuse is a dead control.
- **What you would notice:** with A the toolbar on a shelf card has one button fewer.
- (cards-editor-3-Q5)

### 26.6 Some messages assume the editor can be opened without the right to write into the episode (a "read-only run" without a "working copy"). Is there a read-only way of opening the editor, and what should those messages say?

- **Today:** the editor can be started read-only; then bins cannot change and no job can be sent, with messages that name a "read-only run" and a "working copy".
- **Options:** A: no read-only opening: every person who can open the editor can write, and these messages go. B: keep a read-only opening for a person who may only look, with the messages reworded to say that this person may only read this episode.
- **Recommended:** A unless the studio has people who should only look, because it removes a second mode from every editing control.
- **What you would notice:** with B a viewer could read and search but every change is refused with a plain reason.
- (cards-editor-3-Q6)

### 26.7 The assistant's strength is chosen differently in each place: search starts at the fastest, the edit chat at the most capable, shortening is fixed with no choice. Should one choice of strength apply everywhere?

- **Today:** the search sheet has its own Model picker (fastest by default), the edit chat its own (most capable by default, and the server can fix it for everyone), and shortening uses a fixed strength.
- **Options:** A: one choice per person, used by every assistant feature of the editor. B: each feature keeps its own choice and default, as now.
- **Recommended:** B, because the defaults differ for good reasons (search is read-heavy and repeated, the chat writes the cut) and each picker sits where the work is.
- **What you would notice:** with A changing strength in search also changes it for the chat and shortening.
- (cards-editor-3-Q7)

### 26.8 Every search scope, strength and kind is its own conversation that reads the whole scope again the first time (slow, and paid again). Is that acceptable, or should switching scope, strength or kind keep the assistant's reading?

- **Today:** switching from one person to all interviews, from fastest to stronger, or from By meaning to Closest wording starts a cold conversation that reads its transcripts again, and the sheet says so.
- **Options:** A: keep separate conversations, each warm on its own, as now. B: one conversation per episode and strength that both kinds and every scope share, so only a change of strength reads again.
- **Recommended:** A, because a scope that holds only its own transcripts is what makes a one-person search answer only from that person, which he ruled.
- **What you would notice:** with B switching kind or scope would be quick after the first search, but a one-person answer could be drawn from a conversation that has read everyone.
- (cards-editor-3-Q9)

### 26.9 An idea search with exact quotes lives outside the product and writes pages for the notes program. Should any of it join the editor's By meaning search?

- **Today:** a separate assistant tool searches one person or a whole episode, scores each quote on point, relevant or tangential, names the nearest interviewer question before each hit and who had no hits, and saves its results as pages.
- **Options:** A: nothing more: By meaning already finds passages about an idea, and pages for the notes program are cut. B: add the scores, the nearest interviewer question and the list of who had nothing to By meaning's results, without saving pages.
- **Recommended:** A, fewest parts, and By meaning already gives a reason per passage.
- **What you would notice:** with B each result card carries a score and its question, and the answer names who had nothing.
- (cards-editor-3-Q10)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 26.10 | Four searches ask the assistant about the same transcripts. Is the transcript search sheet the one to keep, with the search inside one transcript and the search across the montage clips going? | the search sheet (all interviews, one person or the montage clips; by meaning or by closest wording) and the edit chat's own reading are reached from the editor. The search inside one transcript and the search across the montage source clips are only started by a page no person reaches any more. | A, the search sheet already searches one person's interviews and the montage clips, so the other two add nothing a person can do. (cards-editor-3-Q8) |

## Your answers

Not yet answered.
